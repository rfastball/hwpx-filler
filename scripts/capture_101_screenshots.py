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
- 앱은 :func:`hwpxfiller.webapp.app.main` 에 **라이브 실행을 선언**해 빌린다
  (:class:`hwpxfiller.webapp.live_run.LiveRun`, N-11A · #423). 종전에는 모듈 전역
  ``_selftest_drive`` 를 통째로 갈아끼우고 ``sys.argv`` 를 덮어썼는데, 그 관용이 실제로
  고장 났다 — #375 가 pywebview 에 넘기는 위치 인자를 ``window`` 에서 ``(window, artifact)``
  로 늘렸을 때 여기 드라이버는 그대로였고, ``TypeError`` 가 워커 스레드에서 나 캡처가
  한 줄도 안 돈 채 GUI 루프가 무한 대기했다. 이제 드라이버는 봉투 하나(``LiveContext``)를
  받고 진입점의 인자는 0개다.
- 이 실행은 시험 능력을 요구하지 않는다(``capability=False``) — 101 은 ``window.__hwpxTest``
  가 서지 않는 **정상 런타임**을 찍는다.
- native 파일·폴더 대화상자만 대체한다(``LiveRun.file_dialogs`` 답변 큐) — 그 아래 실
  로드·검증 경로는 전부 실물이 돈다. 그 외 모든 확인은 in-page 모달이라 실 클릭으로 지난다.
- 픽셀 캡처는 Win32 ``PrintWindow(PW_RENDERFULLCONTENT)`` — WebView2 는
  DirectComposition 이라 이 플래그 없이는 검은 화면이 나온다.
- 화면 전환은 **실 DOM 클릭**이다(상단 탭 ``.navbtn[data-scr=…]``). N-10 이전에는 임시
  전역 ``window.Nav.go(…)`` 를 직접 불렀는데, 그 전역이 사라지면서 이 스크립트가 마지막
  executable 소비자였다. 사용자가 실제로 밟는 경로와 같아져 캡처의 충실도도 올라간다.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
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

    def shot(self, name: str, settle: float = 0.45) -> None:
        """캡처 1컷 — ``settle`` 은 셔터 앞 정착 시간(렌더·모션 ≤160ms·스크롤).

        대기 조건은 **먼저 참이 되는 것 하나**만 본다(예: 복사 카운터). 같은 왕복이
        낳는 다른 재렌더(왼쪽 표 전체)가 아직 합성 중이면 ``PrintWindow`` 가 반쪽
        프레임을 뜬다 — 실제로 그렇게 찢긴 컷이 나왔다. 조건을 더 붙여도 「마지막
        페인트가 끝났는가」는 DOM 에서 못 재므로, 재렌더가 큰 자리만 정착을 늘린다.
        """
        time.sleep(settle)
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
    # 텍스트가 **있다**는 것과 **보인다**는 것은 다르다: 스키마 표는 템플릿 목록 아래라
    # 기본 스크롤에서 폴드 밖이고, 위 조건은 그 상태에서도 참이다(문서가 "6개 필드를
    # 확인한다"고 적은 그림에 표가 없게 된다). 겨눠 스크롤해 그 말을 그림이 지게 한다.
    d.scroll_to("#scr-editor table.schema-fields")
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
    # 좌 목록 사망 뒤 저장된 작업을 찾는 자리는 「문서 작업」 하나다(F2 PR-B).
    d.click_sel('.navbtn[data-scr="library"]')
    d.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청서\"]')",
        "저장·라이브러리 반영",
    )
    d.click_sel('#libraryList [data-work="발주요청서"]')
    d.wait("!!document.querySelector('#libraryDetail [data-use]')", "상세 상시 행동")
    d.shot("library-detail")
    d.click_sel('#libraryDetail [data-use="발주요청서"]')
    # 작업↔데이터 결속(`Job.default_dataset_ref`)과 자동 조준은 U2 §5.3 판정 D 로 폐기됐다
    # (#347) — 「문서 만들기에서 사용」은 **데이터 선택을 반드시 지난다**. 데이터가 없으면
    # 백엔드가 그 명시 사건을 보관만 하고(reason=no_data), 마운트 순간
    # `_apply_preferred_work` 가 그때 판정해 작업을 연다. 101 도 이 순서를 그대로 가르친다.
    d.wait("document.querySelector('#scr-job.on') !== null", "문서 만들기 착지")
    _DIALOG_ANSWERS.append(CSV)
    d.click_sel("#jobBtnPickData")
    d.wait(
        "!document.getElementById('dataPickerModal').classList.contains('hidden')",
        "데이터 선택 면",
    )
    d.click_sel("#dataPickerBrowse")
    # 찾아보기 성사는 **면을 닫지 않는다**(U2 §2.7, #343): 「현재 데이터」가 방금 고른
    # 파일로 재진술되고 그 자리에 「이 데이터 고정…」이 선다. 존재만 재면 hidden 버튼도
    # 통과하므로(프로브 click 이 hidden 을 지나는 것과 같은 함정) **가시성**으로 잰다.
    d.wait(
        "(function(){"
        "if(document.getElementById('dataPickerModal').classList.contains('hidden'))return false;"
        "if(!document.querySelector('#dataPickerCurrent .tplcard-name'))return false;"
        "const b=document.getElementById('dataPickerPin');"
        "return !!b && getComputedStyle(b).display !== 'none';})()",
        "찾아보기 성사·면 유지·고정 버튼 가시",
        timeout=25.0,
    )
    d.click_sel("#dataPickerClose")
    # 보관된 명시 사건이 이 마운트에서 판정돼 작업이 열린다. 「열렸다」의 정본은 액션바
    # 이름이다(「선택한 작업」 존 사망의 승계처 — U2 §4 판정 A, #342): 후보 카드 문안으로
    # 재면 카드 목록에 이름이 **있기만 해도** 참이 돼 안 열린 화면을 통과로 읽는다.
    d.wait(
        "document.getElementById('dataPickerModal').classList.contains('hidden')"
        " && document.getElementById('jobActionName').textContent.trim() === '발주요청서'"
        " && document.getElementById('jobDataLabel').value.length > 0"
        " && !document.getElementById('jobSelAll').disabled",
        "데이터 마운트·보관 작업 승격",
        timeout=25.0,
    )
    # 데이터-우선 계약(§18.2): 새 데이터의 선택은 **0건**에서 시작한다 — 무엇을 만들지는
    # 사용자가 고른다. 그래서 마운트만으로는 게이트가 열리지 않고, 여기서 전체 선택을
    # 눌러야 「N개 생성」이 열린다. 101 도 이 순서를 그대로 가르친다.
    d.click_sel("#jobSelAll")

    # ---- S5a 첫 실행의 결과 확인(F5) ---------------------------------------
    # 방금 만든 작업은 아직 한 번도 문서를 만들지 않았다 — §13-3 대로 결과를 확인해야
    # 실행할 수 있다. 행을 골라도 게이트는 아직 닫혀 있고, 미리보기에서 확인해야 열린다.
    # 101 은 이 순서를 그대로 가르친다(다음 실행부터는 §13-2 대로 조용하다).
    # 게이트가 「생성 값 미리보기」를 지목하는데 그 버튼이 잠겨 있으면 이행 불가능한
    # 지시다 — 지목과 가용성을 **같이** 재고 나서 누른다(누를 것을 찾지 못하는 상태에서
    # click 만 던지면 「버튼 못 찾음」이 아니라 조용한 무반응이 된다).
    d.wait(
        "document.getElementById('jobGenBtn').disabled"
        " && document.getElementById('jobGate').textContent.includes('생성 값 미리보기')"
        " && !document.getElementById('jobPreviewOpen').disabled",
        "첫 실행 검토 요구",
    )
    d.click_sel("#jobPreviewOpen")
    d.wait(
        "!document.getElementById('previewSheet').classList.contains('hidden')"
        " && document.querySelectorAll('#previewRows .mir-row').length > 0"
        " && document.getElementById('previewFilename').textContent.length > 0",
        "확인 면(생성 값 미리보기)·값·파일 이름",
    )
    # 시트 전이(합성 레이어 신설 + 본문 채우기)도 같은 반쪽 프레임 함정이 있다 —
    # 모달 컷이 간헐적으로 찢겼던 자리라 정착을 넉넉히 준다.
    d.shot("preview-drawer", settle=1.2)
    d.click_sel("#previewApprove")
    # 승인은 명시 사건이다 — 버튼이 사라지는 것이 그 사건의 착지다(면은 열린 채 남아
    # 나머지 문서를 계속 넘겨볼 수 있다).
    d.wait(
        "getComputedStyle(document.getElementById('previewApprove')).display === 'none'",
        "결과 확인 착지",
    )
    d.click_sel("#previewClose")
    d.wait(
        "document.getElementById('previewSheet').classList.contains('hidden')"
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

    # ---- S6 본문 확인(한 줄) ------------------------------------------------
    # 거울 표와 필드축 ack 는 U2 §2.13 으로 폐기됐다(#346) — 값을 말하는 표면은 확인 면
    # 하나이고, 이 존에 남은 것은 빈 값 표지·이름 건수·확인 면 출구 한 줄이다. 그 줄이
    # **서 있는 것을 확인한 뒤** 찍는다: 존만 겨눠 찍으면 한 줄이 hidden 인 화면(선택 0건·
    # 차단 배너)도 같은 컷으로 지나간다.
    d.wait(
        "!document.getElementById('jobMirrorLine').hidden"
        " && document.getElementById('jobMirrorSummary').textContent.trim().length > 0",
        "본문 확인 한 줄",
    )
    d.scroll_to("#jobMirrorZone")
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
    d.click_sel('.navbtn[data-scr="library"]')
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
    # (구 「등록 데이터 동명 확인 → [덮어쓰기]」 왕복은 #347 로 사라졌다 — 저장은 데이터를
    #  등록하지도 결속하지도 않는다. 풀 등록은 데이터 선택 면의 「이 데이터 고정」뿐이다.)
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "TXT 작업 저장 착지",
        timeout=30.0,
    )
    d.click_sel("#editorBack")
    d.wait("document.querySelector('#scr-job.on') !== null", "편집기 이탈(트랙 B)")

    # ---- S9 작업대 진입·검토 -----------------------------------------------
    # 실행 버튼이 매체 분기(판정 D)로 「검토·복사 시작 · 3건」으로 서고 작업대가 열린다.
    d.click_sel('.navbtn[data-scr="library"]')
    d.wait(
        "!!document.querySelector('#libraryList [data-work=\"발주요청 기안\"]')",
        "TXT 작업 라이브러리 반영",
    )
    d.click_sel('#libraryList [data-work="발주요청 기안"]')
    d.wait("!!document.querySelector('#libraryDetail [data-use=\"발주요청 기안\"]')", "TXT 상세")
    d.click_sel('#libraryDetail [data-use="발주요청 기안"]')
    # 이번엔 데이터 선택을 다시 지나지 않는다 — 앞 단계에서 마운트한 발주목록이 **세션
    # 소유**라 작업 전환에서 생존한다(데이터-우선 §18.2). 그래서 prefer_work 가 즉시
    # 승격시키고, 그 사실을 액션바 이름이 말한다.
    d.wait(
        "document.getElementById('jobActionName').textContent.trim() === '발주요청 기안'"
        " && !document.getElementById('jobSelAll').disabled",
        "TXT 작업 전환",
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
    # 복사 왕복은 카운터·완료 배지·왼쪽 표를 함께 다시 그린다 — 카운터만 재고 곧바로
    # 셔터를 누르면 표가 합성 중인 반쪽 프레임이 남는다(관측됨).
    d.shot("workbench-copied", settle=1.2)
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
    d.click_sel('.navbtn[data-scr="library"]')
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
    d.wait(
        "document.querySelector('#scr-editor').textContent.includes('저장했습니다')",
        "오류 연습 저장 착지",
        timeout=30.0,
    )
    d.click_sel("#editorBack")
    d.wait("document.querySelector('#scr-job.on') !== null", "편집기 이탈(오류 연습)")
    d.click_sel('.navbtn[data-scr="library"]')
    d.wait(
        "!!document.querySelector('#libraryList [data-work=\"오류연습\"]')",
        "오류 연습 작업 반영",
    )
    d.click_sel('#libraryList [data-work="오류연습"]')
    d.wait("!!document.querySelector('#libraryDetail [data-use=\"오류연습\"]')", "오류 연습 상세")
    d.click_sel('#libraryDetail [data-use="오류연습"]')
    # 여기도 데이터는 그대로다(세션 소유) — 작업만 바뀐다. 화면 전체 텍스트로 재면 후보
    # 카드에 이름이 **떠 있기만 해도** 참이 되므로 액션바 이름으로 겨눈다.
    d.wait(
        "document.getElementById('jobActionName').textContent.trim() === '오류연습'"
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
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "build-web.ps1"),
        ],
        cwd=ROOT,
        check=True,
    )
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)  # 스크린샷은 전량 재생성 — 스테일 프레임 잔존 금지

    os.environ["HWPXFILLER_HOME"] = str(Q101)

    from hwpxfiller.webapp import app as webapp_app
    from hwpxfiller.webapp import live_run

    def answer_file_dialog(filters, owner_title=None):  # noqa: ARG001 — 시그니처 계약 유지
        return _DIALOG_ANSWERS.popleft() if _DIALOG_ANSWERS else None

    def answer_folder_dialog(title, owner_title=None):  # noqa: ARG001 — 시그니처 계약 유지
        # 대본이 폴더 피커를 밟지 않는다. 밟는 순간 조용히 취소로 접지 않고 시끄럽게 죽는다 —
        # 답이 없는 대화상자를 None 으로 넘기면 그 뒤의 화면이 "사용자가 취소했다"가 된다.
        raise RuntimeError(f"대본에 없는 폴더 대화상자 요청: {title!r}")

    def write_capture_result(result) -> Path:
        out = Q101 / "_capture_result.json"
        out.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    state = {"ok": False, "error": None}

    def drive(ctx) -> None:
        window = ctx.window
        result: dict = {}
        try:
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                # 준비 신호는 제품 공개 API 다(#372 D-06). 종전에는 내부 이름 `window.Nav` 를
                # 봤는데, 그 임시 전역은 N-10 에서 사라졌다. `__hwpx` 는 합성 루트가 서비스·
                # 화면·앱 셸을 **전부 구성한 뒤** 마지막에 거는 이름이라 준비 신호로 더 정확하다.
                if window.evaluate_js(
                    "!!(window.pywebview && window.pywebview.api && window.__hwpx)"
                ):
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
            ctx.finish(result)  # 증거 쓰기 → 정식 종료, 제품과 **같은 호스트 연산 허용목록**
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

    # 라이브 실행 선언 하나가 종전의 세 침습(전역 치환·argv 변조·종결 함수 직접 호출)을
    # 대신한다. `argv=[]` 는 "이 프로세스의 명령행은 이 실행과 무관하다"는 뜻이다.
    rc = webapp_app.main(
        argv=[],
        live=live_run.LiveRun(
            name="quickstart-101",
            drive=drive,
            write_output=write_capture_result,
            file_dialogs=live_run.FileDialogs(
                open_file=answer_file_dialog, open_folder=answer_folder_dialog
            ),
        ),
    )

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
