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
    # ---- S1 부팅 랜딩(문서 만들기 · 데이터도 작업도 없는 상태) --------------
    # 좌 목록이 죽은 뒤(F2 PR-B) 이 자리의 출구는 「문서 작업」으로 가는 버튼 하나다.
    d.wait("document.querySelector('#jobPickInLibrary') !== null", "빈 상태 랜딩")
    d.wait(
        "getComputedStyle(document.getElementById('jobNoDataExit')).display !== 'none'",
        "흡수처 출구 상주",
    )
    d.shot("job-landing")

    # ---- S2 「문서 작업」 → ＋ 새 작업 → 편집 모드 1단계(라이브러리 피커) ----
    d.click_sel("#jobPickInLibrary")
    d.wait("document.querySelector('#scr-library.on') !== null", "문서 작업 화면")
    d.shot("library-empty")
    d.click_sel("#libraryNewWork")
    # 편집기는 몰입 표면이다(재작성 F7) — 상단 2탭을 덮는 자기 화면으로 착지한다.
    d.wait(
        "document.querySelector('#scr-editor.on') !== null"
        " && !!window.__cap.btn('#scr-editor','이 템플릿으로')",
        "편집기 화면·라이브러리 피커",
    )
    # 발주요청서 행의 "이 템플릿으로" — data-path 로 정확 겨눔.
    d.click_sel('#scr-editor button[data-act="use-library"][data-path*="발주요청서"]')
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('공고번호')",
        "템플릿 선택·필드 스키마",
    )
    d.shot("template-pick")

    # ---- S3 2단계: 데이터 연결 + 모두 확정 ---------------------------------
    d.click("#scr-editor", "다음 ▶")
    d.wait("!!window.__cap.btn('#scr-editor','파일 선택…')", "「필드 연결·표시」 탭 데이터 관문")
    _DIALOG_ANSWERS.append(CSV)
    d.click("#scr-editor", "파일 선택…")
    d.wait(
        "!!window.__cap.btn('#scr-editor','모두 확정')"
        " && document.querySelector('#scr-editor').textContent.includes('해양수산부')",
        "데이터 로드·매핑표 미리보기",
    )
    d.click("#scr-editor", "모두 확정")
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('확정 6/6')",
        "전 행 확정",
    )
    # 확정 게이트 줄(확정 6/6·모두 확정)이 폴드 아래로 잘리지 않게 겨눠 스크롤.
    d.js("window.__cap.btn('#scr-editor','모두 해제')?.scrollIntoView({block:'center'}); true;")
    d.shot("mapping-confirm")

    # ---- S4 「파일 이름」 탭: 이름·패턴 → 저장 ------------------------------
    # 파일 이름은 F7 에서 **전용 탭**으로 승격했고(대조표 20행), 작업 이름은 화면 머리의
    # 인라인 입력이다(「저장」 분류 사망의 승계 — §10.13.3).
    d.click("#scr-editor", "다음 ▶")
    d.wait("!!document.querySelector('#scr-editor input[data-act=\"pattern\"]')", "파일 이름 탭")
    assert d.js("window.__cap.setValue('#editorName', '발주요청서')")
    assert d.js(
        "window.__cap.setValue('#scr-editor input[data-act=\"pattern\"]',"
        " '발주요청서-{{공고번호}}')"
    )
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('발주요청서-2026-001')",
        "파일명 라이브 예시",
    )
    d.shot("save-job")
    d.click("#scr-editor", "작업 저장")
    # 저장 착지를 먼저 확인한다 — 저장은 비동기라 곧바로 화면을 옮기면 라이브러리가 아직
    # 없는 작업을 기다린다(경합). 성공 재진술은 Python notice(ok) 채널이 낸다.
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "작업 저장 착지",
        timeout=30.0,
    )
    # 저장 뒤 머리가 판본을 말한다(§10.13 판정 O) — 첫 저장이므로 r1 이다.
    d.wait(
        "document.getElementById('editorSaveState').textContent.includes('r1')",
        "저장 상태·판본 표기",
    )
    # 편집기는 출구가 하나다 — back 이 원래 업무로 되돌린다(깨끗한 세션이라 가드 없음).
    d.click_sel("#editorBack")
    d.wait("document.querySelector('#scr-job.on') !== null", "편집기 이탈")

    # ---- S5 실행 세션(「문서 작업」에서 골라 문서 만들기로) ------------------
    # 좌 목록 사망 뒤 저장된 작업을 찾는 자리는 「문서 작업」 하나다(F2 PR-B). 3단계의
    # "데이터 함께 등록" 기본값 덕에 이 작업은 기본 데이터를 가지므로, 「문서 만들기에서
    # 사용」이 곧바로 열고 3건을 자동 연결한다(#53-A · 지도 §10.9 판정 I).
    d.js("window.Nav.go('library'); true;")
    d.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청서\"]')",
        "저장·라이브러리 반영",
    )
    d.click_sel('#libraryList [data-work="발주요청서"]')
    d.wait("!!document.querySelector('#libraryDetail [data-use]')", "상세 상시 행동")
    d.shot("library-detail")
    d.click_sel('#libraryDetail [data-use="발주요청서"]')
    d.wait(
        "document.querySelector('#scr-job').textContent.includes('자동으로 연결')",
        "기본 데이터 자동 연결",
        timeout=25.0,
    )
    # 데이터-우선 계약(§18.2): 새 데이터의 선택은 **0건**에서 시작한다 — 무엇을 만들지는
    # 사용자가 고른다. 그래서 자동 연결만으로는 게이트가 열리지 않고, 여기서 전체 선택을
    # 눌러야 「N개 생성」이 열린다. 101 도 이 순서를 그대로 가르친다.
    d.click_sel("#jobSelAll")

    # ---- S5a 첫 실행의 결과 확인(F5) ---------------------------------------
    # 방금 만든 작업은 아직 한 번도 문서를 만들지 않았다 — §13-3 대로 결과를 확인해야
    # 실행할 수 있다. 행을 골라도 게이트는 아직 닫혀 있고, 미리보기에서 확인해야 열린다.
    # 101 은 이 순서를 그대로 가르친다(다음 실행부터는 §13-2 대로 조용하다).
    d.wait(
        "document.getElementById('jobGenBtn').disabled"
        " && document.getElementById('jobGate').textContent.includes('미리보기')",
        "첫 실행 검토 요구",
    )
    d.click_sel("#jobPreviewOpen")
    d.wait(
        "!document.getElementById('previewModal').classList.contains('hidden')"
        " && document.querySelectorAll('#previewRows .mir-row').length > 0"
        " && document.getElementById('previewFilename').textContent.length > 0",
        "미리보기 드로어·값·파일 이름",
    )
    d.shot("preview-drawer")
    d.click_sel("#previewApprove")
    # 승인은 명시 사건이다 — 버튼이 사라지는 것이 그 사건의 착지다(면은 열린 채 남아
    # 나머지 문서를 계속 넘겨볼 수 있다).
    d.wait(
        "getComputedStyle(document.getElementById('previewApprove')).display === 'none'",
        "결과 확인 착지",
    )
    d.click_sel("#previewClose")
    d.wait(
        "document.getElementById('previewModal').classList.contains('hidden')"
        " && !document.getElementById('jobGenBtn').disabled",
        "확인 뒤 게이트 열림",
    )
    d.shot("session-panel")

    # ---- S5b 범위 편집기(⤢) — 초안 거래를 사람 순서로 한 바퀴(F3) ----------
    # 여는 것 자체가 Python 왕복(초안 생성)이고, 여기서의 편집은 **적용 전까지** 메인 범위를
    # 바꾸지 않는다. 캡처 뒤 **취소**로 나오므로 아래 단계들의 상태는 그대로다.
    d.click_sel("#jobDataExpand")
    d.wait(
        "!document.getElementById('dataSheet').classList.contains('hidden')"
        " && document.getElementById('dataSheetSlot').contains("
        "document.getElementById('jobRangeFoot'))",
        "범위 편집기·footer",
    )
    # 표시순서를 뒤집어 표가 실제로 따라오는지 본다(보이는 것 = 만들어지는 것).
    assert d.js("window.__cap.setValue('#jobOrderSel', 'sourceAsc')")
    d.wait(
        "(document.querySelector('#jobTableBody tr')||{dataset:{}}).dataset.i === '0'",
        "표시순서 전환 반영",
    )
    d.shot("range-editor")
    # 재렌더가 축 선택기를 커밋 값으로 되돌리지 않는지 — 행 하나를 껐다 켜서 **실 왕복**을
    # 만든다(초안의 축을 표는 따르는데 선택기만 옛 값으로 돌아가면 둘이 다른 말을 한다).
    # 판정 수치(footer 「선택 적용: N건」)가 바뀐 것을 먼저 확인해 **push 가 도착한 뒤**를
    # 재는 것이 요점이다 — 클릭 직후를 재면 아직 안 온 재렌더를 통과로 읽는다.
    d.click_sel('#jobTableBody tr[data-i="0"] input[type="checkbox"]')
    d.wait(
        "document.getElementById('jobRangeApply').textContent.includes('2건')"
        " && document.getElementById('jobOrderSel').value === 'sourceAsc'",
        "재렌더 뒤에도 초안 축 유지",
    )
    d.click_sel('#jobTableBody tr[data-i="0"] input[type="checkbox"]')
    d.wait(
        "document.getElementById('jobRangeApply').textContent.includes('3건')",
        "초안 선택 복원",
    )
    d.click_sel("#jobRangeCancel")
    # 변경이 있으므로 이탈 가드가 끼어든다(적용하지 않은 편집을 조용히 버리지 않는다).
    d.wait("!!window.__cap.btn(null,'버리고 닫기')", "이탈 가드")
    d.js("window.__cap.clickBtn(null,'버리고 닫기'); true;")
    # 취소 = 초안만 버린다: 메인 범위(선택 3건)와 축(최신 행 먼저)이 그대로여야 한다.
    d.wait(
        "document.getElementById('dataSheet').classList.contains('hidden')"
        " && document.getElementById('jobOrderSel').value === 'sourceDesc'"
        " && !document.getElementById('jobGenBtn').disabled",
        "취소 뒤 메인 범위 보존",
    )

    # ---- S6 본문 확인(거울) ------------------------------------------------
    d.scroll_to("#jobMirror")
    d.shot("mirror-check")

    # ---- S7 생성 → 완료 요약 ----------------------------------------------
    d.click_sel("#jobGenBtn")
    # 결과는 3태 구획이 받는다(F4) — 제목이 태를, 요약이 수치를 말한다.
    d.wait(
        "(document.getElementById('jobResult')||{dataset:{}}).dataset.state === 'completed'",
        "생성 완료 태",
        timeout=60.0,
    )
    d.scroll_to("#jobResult")
    d.shot("generated")

    # ---- S8 트랙 B: TXT 작업 만들기(편집기 「템플릿」 탭 TXT 밴드) ----------
    # 휘발 「기안」 화면은 F6 PR-B 로 사라졌다 — TXT 도 같은 편집기에서 **저장 작업**으로
    # 만들고(지도 §10.15.15 점검표 1행), 채워 복사는 검토·복사 작업대가 잇는다.
    d.js("window.Nav.go('library'); true;")
    d.wait("document.querySelector('#scr-library.on') !== null", "문서 작업 화면(트랙 B)")
    d.click_sel("#libraryNewWork")
    d.wait(
        "document.querySelector('#scr-editor.on') !== null && !!document.querySelector("
        "'#scr-editor button[data-act=\"use-library\"][data-path*=\"발주요청_기안\"]')",
        "편집기 TXT 밴드",
    )
    d.click_sel('#scr-editor button[data-act="use-library"][data-path*="발주요청_기안"]')
    # TXT 세션 = 탭 2개(템플릿·필드 연결) — 파일 이름 탭이 없다(§3.2, 파일을 만들지 않는 작업).
    d.wait(
        "document.querySelectorAll('#editor-steps .wstep-tab').length === 2"
        " && document.querySelector('#scr-editor').textContent.includes('공고번호')",
        "TXT 스키마·탭 2개",
    )
    d.click("#scr-editor", "다음 ▶")
    d.wait("!!window.__cap.btn('#scr-editor','파일 선택…')", "TXT 필드 연결 데이터 관문")
    _DIALOG_ANSWERS.append(CSV)
    d.click("#scr-editor", "파일 선택…")
    d.wait(
        "!!window.__cap.btn('#scr-editor','모두 확정')"
        " && document.querySelector('#scr-editor').textContent.includes('해양수산부')",
        "TXT 매핑표 미리보기",
    )
    d.click("#scr-editor", "모두 확정")
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('확정 6/6')",
        "TXT 전 행 확정",
    )
    assert d.js("window.__cap.setValue('#editorName', '발주요청 기안')")
    d.click("#scr-editor", "작업 저장")
    # 트랙 A 가 같은 CSV 를 이미 「발주목록」으로 등록했다 — 같은 이름 재등록 확인이 선다
    # (조용한 참조 덮어쓰기 금지). 같은 파일·같은 뜻이라 실습도 [덮어쓰기]로 지난다.
    d.wait("!!window.__cap.btn(null,'덮어쓰기')", "등록 데이터 동명 확인")
    d.js("window.__cap.clickBtn(null,'덮어쓰기'); true;")
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "TXT 작업 저장 착지",
        timeout=30.0,
    )
    d.click_sel("#editorBack")
    d.wait("document.querySelector('#scr-job.on') !== null", "편집기 이탈(트랙 B)")

    # ---- S9 작업대 진입·검토 -----------------------------------------------
    # 실행 버튼이 매체 분기(판정 D)로 「검토·복사 시작 · 3건」으로 서고 작업대가 열린다.
    d.js("window.Nav.go('library'); true;")
    d.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청 기안\"]')",
        "TXT 작업 라이브러리 반영",
    )
    d.click_sel('#libraryList [data-work="발주요청 기안"]')
    d.wait("!!document.querySelector('#libraryDetail [data-use=\"발주요청 기안\"]')", "TXT 상세")
    d.click_sel('#libraryDetail [data-use="발주요청 기안"]')
    d.wait(
        "document.querySelector('#scr-job').textContent.includes('자동으로 연결')",
        "TXT 기본 데이터 자동 연결",
        timeout=25.0,
    )
    d.click_sel("#jobSelAll")
    d.wait(
        "document.getElementById('jobGenBtn').textContent.includes('검토·복사 시작')"
        " && !document.getElementById('jobGenBtn').disabled",
        "검토·복사 진입 버튼",
    )
    d.click_sel("#jobGenBtn")
    # 카드 술어는 표시순서 무관하게 잡는다 — 고정 사본은 「최신 행 먼저」 기본 순서라 첫
    # 카드가 CSV 1행이 아니다. 템플릿 원문([발주 요청])과 채운 값(구매)이 함께 서야 채움이다.
    d.wait(
        "document.querySelector('#scr-workbench.on') !== null"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent"
        ".includes('[발주 요청]')"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent.includes('구매')",
        "작업대 카드 채움",
    )
    d.shot("workbench-review")

    # ---- S10 복사(클립보드) ------------------------------------------------
    d.click_sel("#wbCopy")
    d.wait(
        "(document.getElementById('wbCopied')||{textContent:''}).textContent"
        ".trim().indexOf('1 /') === 0",
        "복사 카운터",
    )
    d.shot("workbench-copied")
    # 미복사 잔량이 있는 이탈은 가드가 확인을 요구한다(T3 승계) — 실 클릭으로 지난다.
    d.click_sel("#wbBack")
    d.wait(
        "document.querySelector('#scr-job.on') !== null || !!window.__cap.btn(null,'나가기')",
        "작업대 이탈 가드",
    )
    d.js("window.__cap.clickBtn(null,'나가기'); true;")
    d.wait("document.querySelector('#scr-job.on') !== null", "작업대 이탈")

    # ---- S11 오류 연습: 데이터에 없는 항목 = 비움 확정 → 〈빈 값〉 ----------
    # 구 「기안」의 빨간 {{토큰}} 은 휘발 세션(미결속 허용)의 표면이었다. 저장 작업은 전 행
    # 확정이 저장 조건이라, 없는 항목은 편집기가 **비움 확정**을 요구하고(조용히 지나가지
    # 않는다) 작업대 카드에 〈빈 값〉으로 남는다 — 같은 경보의 새 거처를 그대로 찍는다.
    d.js("window.Nav.go('library'); true;")
    d.wait("document.querySelector('#scr-library.on') !== null", "문서 작업(오류 연습)")
    d.click_sel("#libraryNewWork")
    d.wait(
        "document.querySelector('#scr-editor.on') !== null && !!document.querySelector("
        "'#scr-editor button[data-act=\"use-library\"][data-path*=\"오류연습_미치환\"]')",
        "편집기 TXT 밴드(오류 연습)",
    )
    d.click_sel('#scr-editor button[data-act="use-library"][data-path*="오류연습_미치환"]')
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('담당연락처')",
        "오류 연습 스키마",
    )
    d.click("#scr-editor", "다음 ▶")
    d.wait("!!window.__cap.btn('#scr-editor','파일 선택…')", "데이터 관문(오류 연습)")
    _DIALOG_ANSWERS.append(CSV)
    d.click("#scr-editor", "파일 선택…")
    d.wait("!!window.__cap.btn('#scr-editor','모두 확정')", "매핑표(오류 연습)")
    d.click("#scr-editor", "모두 확정")
    # 데이터에 없는 「담당연락처」 — 채우지 않고 비움으로 확정할지 **묻는다**(이름게이트).
    d.wait("!!window.__cap.btn(null,'비움으로 확정')", "비움 확정 이름게이트")
    d.js("window.__cap.clickBtn(null,'비움으로 확정'); true;")
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('확정 3/3')",
        "오류 연습 전 행 확정",
    )
    assert d.js("window.__cap.setValue('#editorName', '오류연습')")
    d.click("#scr-editor", "작업 저장")
    d.wait("!!window.__cap.btn(null,'덮어쓰기')", "등록 데이터 동명 확인(오류 연습)")
    d.js("window.__cap.clickBtn(null,'덮어쓰기'); true;")
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "오류 연습 저장 착지",
        timeout=30.0,
    )
    d.click_sel("#editorBack")
    d.wait("document.querySelector('#scr-job.on') !== null", "편집기 이탈(오류 연습)")
    d.js("window.Nav.go('library'); true;")
    d.wait(
        "!!document.querySelector('#libraryList [data-work=\"오류연습\"]')",
        "오류 연습 작업 반영",
    )
    d.click_sel('#libraryList [data-work="오류연습"]')
    d.wait("!!document.querySelector('#libraryDetail [data-use=\"오류연습\"]')", "오류 연습 상세")
    d.click_sel('#libraryDetail [data-use="오류연습"]')
    # 이번엔 「자동으로 연결」 고지가 없다 — 같은 데이터(발주목록)가 앞 단계에서 이미
    # 마운트돼 있어 prefer_work 가 데이터 재연결 없이 작업만 바꾼다. 전환 사실로 기다린다.
    d.wait(
        "document.querySelector('#scr-job').textContent.includes('오류연습')"
        " && !document.getElementById('jobSelAll').disabled",
        "오류 연습 작업 전환",
        timeout=25.0,
    )
    d.click_sel("#jobSelAll")
    d.wait("!document.getElementById('jobGenBtn').disabled", "검토·복사 진입(오류 연습)")
    d.click_sel("#jobGenBtn")
    d.wait(
        "document.querySelector('#scr-workbench.on') !== null"
        " && (document.getElementById('wbCard')||{textContent:''}).textContent.includes('빈 값')"
        " && (document.getElementById('wbMapPanel')||{textContent:''}).textContent"
        ".includes('담당연락처')",
        "작업대 〈빈 값〉 표면",
    )
    d.shot("workbench-empty-value")


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
