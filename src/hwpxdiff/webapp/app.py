"""pywebview 창 + 브리지 + 엔트리 — diff 웹 프론트엔드.

    python -m hwpxdiff.webapp        # 개발 구동(창)
    hwpx-diff-web                    # 설치 후 gui-script

filler webapp(:mod:`hwpxfiller.webapp.app`)의 브리지 구조를 그대로 복제한다: 웹→Python 은
``js_api``(``initial``·``dispatch``·네이티브 동작), Python→웹은 관측 푸시(``window.__push``).
diff 는 단일 화면이라 컨트롤러 하나(:class:`~hwpxdiff.webapp.screen_diff.DiffController`)만 등록한다.

네이티브 자원(파일 다이얼로그)은 :mod:`hwpxcore.native` 공용 계층을 쓴다 — filler webapp 과
같은 Win32 comdlg32 우회(pywebview WinForms 접근성 재귀 크래시 회피). 정식 종료·WebView2
backend 핀·``--selftest`` DOM 자가검증도 filler 소이슈 ①②③ 처리를 그대로 따른다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hwpxcore.native._debug import log
from hwpxcore.native.dialogs import open_file_dialog

from .screen_diff import DiffController

WINDOW_TITLE = "HWPX 규격서 개정 비교"  # 창 제목 = 파일 다이얼로그 소유주 창 FindWindowW 키
# comdlg32 필터: (레이블, 패턴) 쌍 — dialogs._filter_block 이 "레이블 (패턴)"으로 조립하므로
# 레이블엔 패턴을 다시 박지 않는다(이중 표기·RC-34 게이트). filler webapp 의 필터 관례와 동일.
HWPX_FILTERS = [("HWPX", "*.hwpx"), ("모든 파일", "*.*")]


# ------------------------------------------------------------------ 경로 해석
def _repo_root() -> Path:
    # app.py = <repo>/src/hwpxdiff/webapp/app.py → parents[3] = <repo>
    return Path(__file__).resolve().parents[3]


def web_dir() -> Path:
    """정적 자산 루트 — 동결 시 ``sys._MEIPASS/web-diff``, 개발 시 ``<repo>/web-diff``.

    filler 는 ``web/`` 을 쓴다 — diff 는 별도 exe·별도 창이고 두 spec 이 서로 excludes 하므로
    자산도 경계를 미러해 별도 번들(``web-diff/``)을 쓴다.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web-diff"  # type: ignore[attr-defined]
    return _repo_root() / "web-diff"


# ------------------------------------------------------------------ 브리지
class WebFrontend:
    """웹→Python js_api + 화면 라우팅. 컨트롤러를 소유하고 창(네이티브 자원)을 쥔다."""

    def __init__(self) -> None:
        # 창 참조는 비공개(_) — pywebview js_api 자동노출 반영(util.get_functions)이 공개 속성을
        # dir() 재귀 순회하는데, 공개면 Window→native(WinForms)→AccessibilityObject 무한 재귀로
        # 부팅이 불안정해진다(filler app.py 동일 항). 밑줄 접두면 반영이 건너뛴다.
        self._window: "object | None" = None  # webview.Window (지연 배선)
        controllers = [DiffController(self._push)]
        self.controllers = {c.name: c for c in controllers}

    def _controller(self, screen: str) -> DiffController:
        try:
            return self.controllers[screen]
        except KeyError:  # confirm-or-alarm: 미등록 화면은 시끄럽게.
            raise ValueError(f"등록되지 않은 화면: {screen!r}") from None

    # -------------------------------------------------- 관측 푸시(Python→웹)
    def _push(self, screen: str, snapshot: dict) -> None:
        if self._window is None:
            return
        payload = json.dumps(snapshot, ensure_ascii=False)
        self._window.evaluate_js(f"window.__push({json.dumps(screen)}, {payload})")  # type: ignore[attr-defined]

    # -------------------------------------------------- 웹→Python (js_api)
    def initial(self, screen: str) -> dict:
        """화면 부팅 시 웹이 1회 당겨 가는 초기 상태."""
        return self._controller(screen).initial()

    def dispatch(self, screen: str, action: str, payload: "dict | None" = None):
        """순수 데이터 액션(창 불필요) 라우팅. 액션이 값을 돌려주면 그대로 웹에 반환."""
        return self._controller(screen).dispatch(action, payload or {})

    def pick_old_file(self, screen: str) -> "str | None":
        """Win32 열기 다이얼로그(HWPX) → 구판 경로 로드. 파일명·None(취소)·``ERROR:`` 접두."""
        return self._pick(screen, "old")

    def pick_new_file(self, screen: str) -> "str | None":
        """Win32 열기 다이얼로그(HWPX) → 신판 경로 로드. 파일명·None(취소)·``ERROR:`` 접두."""
        return self._pick(screen, "new")

    def _pick(self, screen: str, side: str) -> "str | None":
        log(f"pick_{side}_file: enter screen={screen}")
        path = open_file_dialog(HWPX_FILTERS, owner_title=WINDOW_TITLE)
        log(f"pick_{side}_file: dialog returned {path!r}")
        if not path:
            return None
        ctrl = self._controller(screen)
        try:
            (ctrl.load_old_path if side == "old" else ctrl.load_new_path)(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name

    def compare(self, screen: str) -> dict:
        """비동기 비교 시작 — 워커 스레드 + push(완료 시 결과). 즉시 running 상태 반환."""
        return self._controller(screen).compare()


# ------------------------------------------------------------------ 자가검증
def _selftest_drive(window: "object") -> None:
    """동결 exe 부팅 자가검증 — 창이 뜨고 비교/렌더/브리지가 도는지 되읽어 파일로 확정 후 종료.

    filler ``_selftest_drive`` 미러: ``os._exit`` 대신 ``window.destroy()`` 정식 종료.
    """
    import time

    time.sleep(4.5)
    result: dict = {}
    try:
        result["url"] = window.get_current_url()  # type: ignore[attr-defined]
        result["title_dom"] = window.evaluate_js("document.title")  # type: ignore[attr-defined]
        result["has_pickers"] = window.evaluate_js(  # type: ignore[attr-defined]
            "!!document.getElementById('pickOld') && !!document.getElementById('pickNew')")
        result["kpi_slots"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.querySelectorAll('#diffKpis .kpi').length")
        result["compare_btn"] = window.evaluate_js(  # type: ignore[attr-defined]
            "!!document.getElementById('compareBtn')")
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    out = Path(sys.executable).resolve().parent / "selftest_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    window.destroy()  # type: ignore[attr-defined]  # 정식 종료(os._exit 대체)


# ------------------------------------------------------------------ 엔트리
def main() -> int:
    import webview

    frontend = WebFrontend()
    window = webview.create_window(
        WINDOW_TITLE,
        str(web_dir() / "index.html"),
        js_api=frontend,
        width=1180,
        height=820,
        min_size=(760, 600),
    )
    frontend._window = window
    # Windows 는 EdgeChromium(WebView2) 백엔드 명시 핀(filler 소이슈 ②).
    gui = "edgechromium" if sys.platform == "win32" else None
    if "--selftest" in sys.argv:
        webview.start(_selftest_drive, window, gui=gui)
    else:
        webview.start(gui=gui)  # 정상 닫기 = 여기서 반환 → 클린 종료(소이슈 ①)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
