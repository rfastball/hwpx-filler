"""101 사용설명서 스크린샷 자동 캡처(#260) — 실앱(WebView2)을 띄워 단계별 화면을 찍는다.

문서 스크린샷의 드리프트를 막는 재생성 도구다: UI 가 바뀌면 이 스크립트를 다시 돌려
`examples/quickstart-101/img/` 를 통째로 갱신한다. 캡처 과정이 곧 101 트랙 A·B 의
**실 렌더 완주**다 — 실 버튼 클릭·실 dispatch·실 생성(HWPX 3건)·실 클립보드 복사를
그대로 밟으므로, 완주가 깨지면 스크린샷이 아니라 시끄러운 실패가 남는다
(confirm-or-alarm — 문서와 앱이 어긋난 채 조용히 찍히지 않게).

실행(저장소 루트, Windows 데스크톱 세션 필요; 클립보드를 한 번 덮어쓴다)::

    uv run --with pillow --extra gui python scripts/capture_101_screenshots.py

전제: ``examples/quickstart-101`` 이 깨끗한 상태여야 한다(실습 잔재 = 비결정 화면).
잔재가 있으면 지우지 않고 **거부**한다 — 사용자의 로컬 실습 상태를 말없이 파괴하지
않는다. ``reset-101.cmd`` 로 정리한 뒤 다시 실행하라. 캡처가 끝나면 자기 잔재를
스스로 치워 재실행 가능 상태로 돌려놓는다(실패 시엔 진단을 위해 남긴다).

기술 노트
---------
- 앱은 ``--selftest`` 부팅(단일 인스턴스 가드 우회·정식 종료 경로)을 빌리되, 드라이브
  함수를 이 스크립트 것으로 갈아끼운다(:func:`hwpxfiller.webapp.app.main` 이 런타임에
  모듈 전역 ``_selftest_drive`` 를 찾는 점을 이용 — 앱 코드 무변경).
- native 파일 대화상자만 스텁한다(``app.open_file_dialog`` 를 답변 큐로 치환) — 그
  아래 실 로드·검증 경로는 전부 실물이 돈다. 그 외 모든 확인은 in-page 모달이라
  실 클릭으로 지난다.
- 픽셀 캡처는 Win32 ``PrintWindow(PW_RENDERFULLCONTENT)`` — WebView2 는
  DirectComposition 이라 이 플래그 없이는 검은 화면이 나온다.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import time
from collections import deque
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Q101 = ROOT / "examples" / "quickstart-101"
OUT_DIR = Q101 / "img"

# 캡처 창 크기(논리 px) — 문서 스크린샷 고정 규격(리사이즈로 강제, 저장 기하 무시).
WINDOW_W, WINDOW_H = 1180, 760
# 저장 폭 상한(물리 px) — DPI 배율 캡처를 문서 무게에 맞게 축소.
MAX_PNG_WIDTH = 1600

# 실습 잔재 정리 목록(reset-101.cmd 와 같은 집합).
_PRACTICE_STATE = [
    "jobs", "datasets", "mapping_bases", "webview", "out", "Results",
    "templates/Results", "ui_settings.ini", "settings.json", "webapp-alerts.log",
]
# 캡처 거부 판별은 webview/ 를 뺀다 — 앱이 부팅마다 스스로 통청소하는 프로필이라
# (app._prepare_webview_profile) 잔존해도 화면 결정성에 영향이 없고, 워치독 종료
# 직후엔 잠겨 있어 지우지 못한 채 남는 것이 정상이다.
_REFUSE_STATE = [p for p in _PRACTICE_STATE if p != "webview"]

# native 파일 대화상자 답변 큐 — 드라이브가 단계마다 미리 채운다.
_DIALOG_ANSWERS: "deque[str]" = deque()

CSV = str(Q101 / "data" / "발주목록.csv")


# ------------------------------------------------------------------ Win32 캡처 코어
_PW_RENDERFULLCONTENT = 0x00000002


def _find_hwnd(title: str, timeout: float = 30.0) -> int:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd and user32.IsWindowVisible(hwnd):
            return int(hwnd)
        time.sleep(0.2)
    raise RuntimeError(f"보이는 창을 찾지 못함: {title!r} (FOUC 은닉 미해제?)")


def _capture_window(hwnd: int, path: Path) -> None:
    """클라이언트 영역을 PrintWindow 로 떠서 PNG 로 저장한다(폭 상한 축소 포함)."""
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise RuntimeError("GetClientRect 실패")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"창 클라이언트 영역이 비정상: {width}x{height}")

    hdc_win = user32.GetDC(wintypes.HWND(hwnd))
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
    try:
        gdi32.SelectObject(hdc_mem, bmp)
        # PW_RENDERFULLCONTENT 미지정 시 WebView2(DirectComposition) 영역이 검게 나온다.
        ok = user32.PrintWindow(wintypes.HWND(hwnd), hdc_mem, _PW_RENDERFULLCONTENT | 0x1)
        if not ok:
            raise RuntimeError("PrintWindow 실패")

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = width, -height  # top-down
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        buf = ctypes.create_string_buffer(width * height * 4)
        got = gdi32.GetDIBits(hdc_mem, bmp, 0, height, buf, ctypes.byref(bmi), 0)
        if got != height:
            raise RuntimeError(f"GetDIBits {got}/{height}")
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(wintypes.HWND(hwnd), hdc_win)

    image = Image.frombuffer("RGB", (width, height), buf.raw, "raw", "BGRX", 0, 1)
    if image.width > MAX_PNG_WIDTH:
        ratio = MAX_PNG_WIDTH / image.width
        image = image.resize((MAX_PNG_WIDTH, round(image.height * ratio)), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"  {shown}: {image.width}x{image.height}")


# ------------------------------------------------------------------ 드라이브 공통
# 텍스트로 버튼을 찾는 JS 헬퍼 — data-act 가 없는 푸터류도 문안으로 정확히 겨눈다.
_JS_HELPERS = """
window.__cap = {
  btn(scopeSel, text) {
    const scope = scopeSel ? document.querySelector(scopeSel) : document;
    if (!scope) return null;
    return [...scope.querySelectorAll('button')].find(
      (b) => b.textContent.trim() === text && !b.disabled) || null;
  },
  clickBtn(scopeSel, text) {
    const b = this.btn(scopeSel, text);
    if (!b) return false;
    b.click();
    return true;
  },
  setValue(sel, value) {
    const el = document.querySelector(sel);
    if (!el) return false;
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  },
};
true;
"""


class Driver:
    def __init__(self, window, hwnd: int) -> None:
        self.window = window
        self.hwnd = hwnd
        self.shot_no = 0

    def js(self, expr: str):
        return self.window.evaluate_js(expr)

    def wait(self, expr: str, what: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(expr):
                return
            time.sleep(0.15)
        raise RuntimeError(f"대기 시한 초과: {what} — {expr}")

    def click(self, scope_sel: str, text: str) -> None:
        ok = self.js(f"window.__cap.clickBtn({scope_sel!r}, {text!r})")
        if not ok:
            raise RuntimeError(f"버튼 못 찾음: {scope_sel} 안 {text!r}")

    def click_sel(self, sel: str) -> None:
        ok = self.js(
            f"(function(){{const el=document.querySelector({sel!r});"
            "if(!el)return false; el.click(); return true;})()"
        )
        if not ok:
            raise RuntimeError(f"요소 못 찾음: {sel}")

    def scroll_to(self, sel: str) -> None:
        """대상 구획을 뷰포트 중앙으로 — 폴드 아래 상태가 컷에서 잘리지 않게(즉시, 무모션)."""
        ok = self.js(
            f"(function(){{const el=document.querySelector({sel!r});"
            "if(!el)return false; el.scrollIntoView({block:'center',behavior:'instant'});"
            "return true;})()"
        )
        if not ok:
            raise RuntimeError(f"스크롤 대상 못 찾음: {sel}")

    def shot(self, name: str) -> None:
        time.sleep(0.45)  # 렌더·모션(≤160ms)·스크롤 안정
        self.shot_no += 1
        _capture_window(self.hwnd, OUT_DIR / f"{self.shot_no:02d}-{name}.png")


def _refuse_dirty_home() -> None:
    stale = [p for p in _REFUSE_STATE if (Q101 / p).exists()]
    if stale:
        raise SystemExit(
            "examples/quickstart-101 에 실습 잔재가 있어 캡처를 거부합니다(비결정 화면·"
            f"로컬 상태 보호): {stale}\n→ reset-101.cmd 로 정리 후 다시 실행하세요."
        )


def _clean_practice_state() -> None:
    for rel in _PRACTICE_STATE:
        target = Q101 / rel
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink(missing_ok=True)
        except OSError:
            pass  # 잠긴 파일(실행 중 프로필 등)은 남긴다 — 다음 부팅/reset 이 치운다


# ------------------------------------------------------------------ 단계 대본
def _drive(d: Driver) -> None:
    """트랙 A·B 를 실 렌더로 완주하며 단계별 캡처."""
    # ---- S1 부팅 랜딩(작업 · 빈 상태) --------------------------------------
    d.wait("document.querySelector('#jobEmptyNewBtn') !== null", "빈 상태 랜딩")
    d.shot("job-landing")

    # ---- S2 새 작업 → 편집 모드 1단계(라이브러리 피커) ----------------------
    d.click_sel("#jobEmptyNewBtn")
    d.wait(
        "!document.getElementById('jobEditHost').hidden"
        " && !!window.__cap.btn('#jobEditHost','이 템플릿으로')",
        "편집 모드·라이브러리 피커",
    )
    # 발주요청서 행의 "이 템플릿으로" — data-path 로 정확 겨눔.
    d.click_sel('#jobEditHost button[data-act="use-library"][data-path*="발주요청서"]')
    d.wait(
        "document.querySelector('#jobEditHost').textContent.includes('공고번호')",
        "템플릿 선택·필드 스키마",
    )
    d.shot("template-pick")

    # ---- S3 2단계: 데이터 연결 + 모두 확정 ---------------------------------
    d.click("#jobEditHost", "다음 ▶")
    d.wait("!!window.__cap.btn('#jobEditHost','파일 선택…')", "2단계 데이터 관문")
    _DIALOG_ANSWERS.append(CSV)
    d.click("#jobEditHost", "파일 선택…")
    d.wait(
        "!!window.__cap.btn('#jobEditHost','모두 확정')"
        " && document.querySelector('#jobEditHost').textContent.includes('해양수산부')",
        "데이터 로드·매핑표 미리보기",
    )
    d.click("#jobEditHost", "모두 확정")
    d.wait(
        "document.querySelector('#jobEditHost').textContent.includes('확정 6/6')",
        "전 행 확정",
    )
    # 확정 게이트 줄(확정 6/6·모두 확정)이 폴드 아래로 잘리지 않게 겨눠 스크롤.
    d.js("window.__cap.btn('#jobEditHost','모두 해제')?.scrollIntoView({block:'center'}); true;")
    d.shot("mapping-confirm")

    # ---- S4 3단계: 이름·파일명 패턴 → 저장 ---------------------------------
    d.click("#jobEditHost", "다음 ▶")
    d.wait("!!document.querySelector('#jobEditHost input[data-act=\"name\"]')", "3단계 저장 폼")
    assert d.js("window.__cap.setValue('#jobEditHost input[data-act=\"name\"]', '발주요청서')")
    assert d.js(
        "window.__cap.setValue('#jobEditHost input[data-act=\"pattern\"]',"
        " '발주요청서-{{공고번호}}')"
    )
    d.wait(
        "document.querySelector('#jobEditHost').textContent.includes('발주요청서-2026-001')",
        "파일명 라이브 예시",
    )
    d.shot("save-job")
    d.click("#jobEditHost", "작업 저장")
    d.wait(
        "!!document.querySelector('.job-item[data-job=\"발주요청서\"]')",
        "저장·목록 반영",
    )

    # ---- S5 실행 세션(작업 선택 → 기본 데이터 자동 연결) --------------------
    # 3단계의 "데이터 함께 등록" 기본값 덕에 저장된 작업은 기본 데이터를 갖는다 —
    # 선택만으로 자동 연결 고지 + 3건 로드 + 게이트 열림까지 온다(#53-A 자동 조준).
    d.click_sel('.job-item[data-job="발주요청서"]')
    d.wait(
        "!document.getElementById('jobGenBtn').disabled"
        " && document.querySelector('#scr-job').textContent.includes('자동으로 연결')",
        "자동 연결·게이트 열림",
        timeout=25.0,
    )
    d.shot("session-panel")

    # ---- S6 본문 확인(거울) ------------------------------------------------
    d.scroll_to("#jobMirror")
    d.shot("mirror-check")

    # ---- S7 생성 → 완료 요약 ----------------------------------------------
    d.click_sel("#jobGenBtn")
    d.wait(
        "(document.getElementById('jobGenResult')||{textContent:''}).textContent"
        ".includes('성공 3/3')",
        "생성 완료 요약",
        timeout=60.0,
    )
    d.scroll_to("#jobGenResult")
    d.shot("generated")

    # ---- S8 기안: 템플릿 + 데이터 채움 -------------------------------------
    d.js("window.Nav.go('draft'); true;")
    d.wait("document.querySelector('#scr-draft.on') !== null", "기안 화면")
    d.wait("document.querySelectorAll('#draftTplSel option').length >= 2", "템플릿 콤보 채움")
    assert d.js("window.__cap.setValue('#draftTplSel', '발주요청_기안')")
    d.wait(
        "(document.getElementById('draftCardRender')||{textContent:''}).textContent"
        ".includes('발주 요청')",
        "기안 원문 렌더",
    )
    _DIALOG_ANSWERS.append(CSV)
    d.click_sel("#draftBtnPickData")
    d.wait(
        "(document.getElementById('draftCardRender')||{textContent:''}).textContent"
        ".includes('해양수산부')",
        "기안 채움 미리보기",
        timeout=25.0,
    )
    d.scroll_to("#draftCard")
    d.shot("draft-filled")

    # ---- S9 복사(클립보드) -------------------------------------------------
    d.click_sel("#draftCardCopy")
    d.wait(
        "(document.getElementById('draftNote')||{textContent:''}).textContent"
        ".includes('복사')",
        "복사 완료 노트",
    )
    d.scroll_to("#draftNote")
    d.shot("draft-copied")

    # ---- S10 오류 연습: 미치환 토큰 경고 -----------------------------------
    assert d.js("window.__cap.setValue('#draftTplSel', '오류연습_미치환')")
    # 무장 세션 전환 가드 — in-page 확인 모달이 뜨면 실 클릭으로 지난다.
    d.wait(
        "(document.getElementById('draftCardRender')||{textContent:''}).textContent"
        ".includes('담당연락처')"
        " || !!window.__cap.btn(null,'바꾸기')",
        "전환 가드 or 전환 완료",
    )
    d.js("window.__cap.clickBtn(null,'바꾸기'); true;")
    # 전환은 데이터를 유지한다 — 해제된 경우에만 다시 겨눈다(답변도 그때만 큐잉).
    time.sleep(0.8)
    if not d.js(
        "((document.getElementById('draftDataLabel')||{value:'',textContent:''}).value||''"
        " + (document.getElementById('draftDataLabel')||{textContent:''}).textContent)"
        ".includes('발주목록')"
    ):
        _DIALOG_ANSWERS.append(CSV)
        d.click_sel("#draftBtnPickData")
    d.wait(
        "(document.getElementById('draftCardRender')||{textContent:''}).textContent"
        ".includes('{{담당연락처}}')",
        "미치환 토큰 표시",
        timeout=25.0,
    )
    d.scroll_to("#draftCard")
    d.shot("missing-token")


# ------------------------------------------------------------------ 부팅 배선
def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("Windows 데스크톱 세션 전용(WebView2 실창 캡처)")
    _refuse_dirty_home()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)  # 스크린샷은 전량 재생성 — 스테일 프레임 잔존 금지

    os.environ["HWPXFILLER_HOME"] = str(Q101)
    os.environ.setdefault("HWPX_SELFTEST_OUT", str(Q101 / "_capture_result.json"))

    from hwpxfiller.webapp import app as webapp_app

    def stub_open_file_dialog(filters, owner_title=None):  # noqa: ARG001 — 시그니처 계약 유지
        return _DIALOG_ANSWERS.popleft() if _DIALOG_ANSWERS else None

    webapp_app.open_file_dialog = stub_open_file_dialog  # native 표면만 스텁 — 로드 경로는 실물

    state = {"ok": False, "error": None}

    def drive(window) -> None:
        result: dict = {}
        try:
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                if window.evaluate_js("!!(window.pywebview && window.pywebview.api && window.Nav)"):
                    break
                time.sleep(0.15)
            else:
                raise RuntimeError("브리지 준비 시한 초과")
            window.resize(WINDOW_W, WINDOW_H)
            time.sleep(0.6)
            window.evaluate_js(_JS_HELPERS)
            hwnd = _find_hwnd(webapp_app.WINDOW_TITLE)
            _drive(Driver(window, hwnd))
            if _DIALOG_ANSWERS:
                raise RuntimeError(f"대화상자 답변 잔량 {len(_DIALOG_ANSWERS)} — 대본 어긋남")
            state["ok"] = True
            result["captured"] = sorted(p.name for p in OUT_DIR.glob("*.png"))
        except Exception as exc:  # noqa: BLE001 — 드라이브 스레드 조용한 증발 금지
            state["error"] = repr(exc)
            result["error"] = repr(exc)
        finally:
            webapp_app._finish_selftest(window, result)
            # 워치독: window.destroy 후에도 WinForms 루프가 안 내려오는 pywebview
            # teardown 매달림이 관측됐다(faulthandler 스택: Application.Run 상주).
            # 정상 종료에 10s 유예를 주고, 그래도 살아 있으면 여기서 정리·요약을
            # 대행하고 하드 종료한다 — 조용한 무한 대기 금지. 실패 완주면 스택을
            # 남겨 진단 증거를 확보한다.
            def _watchdog() -> None:
                time.sleep(10)
                if state["ok"]:
                    _clean_practice_state()
                    (Q101 / "_capture_result.json").unlink(missing_ok=True)
                    count = len(list(OUT_DIR.glob("*.png")))
                    os.write(
                        1,
                        (
                            f"완료: {count}컷 → {OUT_DIR} "
                            "(teardown 매달림 → 워치독 종료; 잠긴 webview/ 는 다음 부팅이 청소)\n"
                        ).encode("utf-8", "replace"),
                    )
                    os._exit(0)
                import faulthandler

                with (Q101 / "_capture_hang_stacks.txt").open("w", encoding="utf-8") as fh:
                    faulthandler.dump_traceback(file=fh)
                os._exit(7)

            import threading

            threading.Thread(target=_watchdog, daemon=True).start()

    webapp_app._selftest_drive = drive  # main() 은 런타임 전역 조회 — 앱 코드 무변경 치환
    sys.argv = [sys.argv[0], "--selftest"]
    rc = webapp_app.main()

    (Q101 / "_capture_result.json").unlink(missing_ok=True)
    if not state["ok"]:
        print(f"캡처 실패 — 잔재를 진단용으로 남깁니다: {state['error']}", file=sys.stderr)
        return 1
    _clean_practice_state()  # 성공 완주 — 자기 잔재를 치워 재실행 가능 상태로
    count = len(list(OUT_DIR.glob("*.png")))
    print(f"완료: {count}컷 → {OUT_DIR.relative_to(ROOT)} (실습 잔재 정리됨)")
    return 0 if rc == 0 else rc


if __name__ == "__main__":
    raise SystemExit(main())
