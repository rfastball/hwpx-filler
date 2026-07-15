"""pywebview 창 + 브리지 + 엔트리 — 웹 프론트엔드의 링2.

    python -m hwpxfiller.webapp        # 개발 구동(창)
    hwpx-filler-web                    # 설치 후 gui-script

브리지(:class:`WebFrontend`)는 스파이크 ``app.py`` 의 ``Api`` 를 **다화면용으로 승격**한 것:
화면 id → 컨트롤러(:mod:`~hwpxfiller.webapp.screens`) 라우팅을 얇게 얹는다. 웹→Python 은
``js_api``(``initial``·``dispatch``·네이티브 동작), Python→웹은 관측 푸시(``window.__push``).

소이슈 흡수(SPIKE_FINDINGS.md 끝):
- ① 정식 종료: 스파이크의 ``os._exit`` 강제 종료를 **버린다**. 정상 닫기는 사용자가 창 X →
  ``webview.start()`` 가 반환 → 프로세스 클린 종료(매달림 없음). 프리즈 자가검증도
  ``window.destroy()`` 정식 API 로 닫는다.
- ② WebView2 backend 핀: Windows 에서 ``gui="edgechromium"`` 명시 → WinForms 접근성 재귀
  크래시(외부 UIA 주입에서만 관측)의 backend 고정 항. 버전은 pyproject gui extra 에서 핀.
- ③ 배포 형태(onedir)는 packaging/hwpx_filler_web.spec 에서 결정.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ..core.job import JobRegistry, default_jobs_dir
from ..core.text_registry import TextTemplateRegistry, default_text_templates_dir
from ..gui.file_filters import EXCEL_FILTER_PATTERN  # 확장자 단일 출처(RC-34) — Qt-free 상수
from hwpxcore.native._debug import log
from hwpxcore.native.clipboard import set_clipboard_text
from hwpxcore.native.dialogs import open_file_dialog, open_folder_dialog, save_file_dialog
from .screen_editor import EditorController
from .screen_home import HomeController
from .screen_matrix import MatrixController
from .screen_run import RunController
from .screen_template import TemplateController
from .screens import TxtController


WINDOW_TITLE = "HWPX Filler"  # 창 제목 = 파일 다이얼로그 소유주 창을 FindWindowW 로 찾는 키


# ------------------------------------------------------------------ 경로 해석
def _repo_root() -> Path:
    # app.py = <repo>/src/hwpxfiller/webapp/app.py → parents[3] = <repo>
    return Path(__file__).resolve().parents[3]


def web_dir() -> Path:
    """정적 자산 루트 — 동결 시 ``sys._MEIPASS/web``, 개발 시 ``<repo>/web``."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return _repo_root() / "web"


# ------------------------------------------------------------------ 브리지
class WebFrontend:
    """웹→Python js_api + 화면 라우팅. 컨트롤러를 소유하고 창(네이티브 자원)을 쥔다."""

    def __init__(self, text_templates_dir: "str | Path") -> None:
        # 창 참조는 비공개(_) — pywebview 의 js_api 자동노출 반영(util.get_functions)이 공개
        # 속성을 dir() 로 재귀 순회하는데, 공개면 Window→native(WinForms)→AccessibilityObject 로
        # 무한 재귀(recursion depth 초과)하며 WebView2 COM 을 주입 스레드에서 건드려 부팅을
        # 불안정하게 만든다. 밑줄 접두면 반영이 건너뛴다 — 이 참조는 내부 배선일 뿐 JS API 아님.
        self._window: "object | None" = None  # webview.Window (지연 배선)
        registry = TextTemplateRegistry(text_templates_dir)
        job_registry = JobRegistry(default_jobs_dir())
        # 화면 등록 — 새 화면 = 컨트롤러 1개 추가(순수 데이터는 dispatch, 네이티브는 아래 메서드).
        controllers = [
            # 홈(대시보드) — 허브. TXT 레지스트리는 즉시 기안·템플릿 관리와 공유(변경이 반영).
            HomeController(job_registry, registry, self._push),
            TxtController(registry, self._push),
            EditorController(job_registry, self._push),
            RunController(job_registry, self._push),
            MatrixController(job_registry, self._push),
            # 템플릿 관리(#13) — TXT 레지스트리는 즉시 기안과 공유(변경이 양쪽에 반영).
            TemplateController(registry, self._push),
        ]
        self.controllers = {c.name: c for c in controllers}

    def _controller(self, screen: str):
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

    def pick_template_file(self, screen: str) -> "str | None":
        """Win32 열기 다이얼로그(HWPX) → 링1 스키마/게이트 로드. 실패는 ``ERROR:`` 접두."""
        path = open_file_dialog([("HWPX 템플릿", "*.hwpx"), ("모든 파일", "*.*")],
                                owner_title=WINDOW_TITLE)
        if not path:
            return None
        try:
            # 새 템플릿 진입 = 새 작업 세션(#25) — 이전 세션과 섞이지 않게 원자 초기화 후 로드.
            self._controller(screen).new_job_session(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name

    def pick_data_file(self, screen: str) -> "str | None":
        """Win32 파일 다이얼로그 → 링1 VM 로드. 실패는 ``ERROR:`` 접두로 시끄럽게 반환."""
        log(f"pick_data_file: enter screen={screen}")
        filters = [("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")]
        path = open_file_dialog(filters, owner_title=WINDOW_TITLE)
        log(f"pick_data_file: dialog returned {path!r}")
        if not path:
            return None
        try:
            self._controller(screen).load_data_path(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name

    def copy_clipboard(self, screen: str) -> dict:
        """현재 렌더 텍스트를 OS 클립보드로(완료=commit). 리포트를 돌려줘 웹이 재진술."""
        text, report = self._controller(screen).render()
        set_clipboard_text(text)
        return {"missing_fields": report.missing_fields, "empty_fields": report.empty_fields}

    def save_file(self, screen: str) -> "dict | None":
        """Win32 저장 다이얼로그 → 원자 쓰기(덮어쓰기 확인 포함)."""
        from hwpxcore.atomic import write_text_atomic

        path = save_file_dialog(
            "기안.txt", [("텍스트", "*.txt"), ("모든 파일", "*.*")],
            default_ext="txt", owner_title=WINDOW_TITLE,
        )
        if not path:
            return None
        text, report = self._controller(screen).render()
        write_text_atomic(path, text)
        return {
            "path": Path(path).name,
            "missing_fields": report.missing_fields,
            "empty_fields": report.empty_fields,
        }

    def pick_output_folder(self, screen: str) -> "str | None":
        """Win32 폴더 피커(SHBrowseForFolder) → 저장 폴더 지정. 실행 화면의 신규 네이티브 표면.

        선택 경로의 표시명 또는 None(취소). 실패는 ``ERROR:`` 접두로 시끄럽게 반환.
        """
        path = open_folder_dialog("저장 폴더 선택", owner_title=WINDOW_TITLE)
        if not path:
            return None
        try:
            self._controller(screen).set_output_folder(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return path

    def generate(self, screen: str, confirm_overwrite: bool = False) -> dict:
        """실행 화면 동기 생성 — 게이트 판정·덮어쓰기 재진술·결과 요약을 dict 로 반환."""
        return self._controller(screen).generate(confirm_overwrite=bool(confirm_overwrite))

    def pick_library_folder(self) -> "str | None":
        """Win32 폴더 피커 → 템플릿 관리 화면 HWPX 라이브러리 폴더 재지정. 경로·None(취소)·``ERROR:``."""
        path = open_folder_dialog("템플릿 라이브러리 폴더", owner_title=WINDOW_TITLE)
        if not path:
            return None
        try:
            self._controller("tpl").set_library_dir(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return path

    def editor_has_unsaved_work(self) -> bool:
        """에디터에 진행 중인(미저장) 작업 세션이 있는가 — 크로스스크린 진입 전 폐기 확인용(#25)."""
        return self._controller("editor").has_unsaved_work()

    def load_template_into_editor(self, path: str) -> "str | None":
        """템플릿 관리 '작업 만들기' → 그 템플릿을 에디터에 로드(크로스스크린). 파일명·``ERROR:``.

        웹은 이 호출 후 에디터 화면으로 전환한다 — 링1 seam(editor.new_job_session)을 재사용해
        VM 로직을 재구현하지 않는다. 새 템플릿 진입은 새 작업 세션이라 이전 세션을 원자
        초기화한다(#25) — 미저장 확인은 웹이 has_unsaved_work 로 선판단한다.
        """
        try:
            self._controller("editor").new_job_session(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name


# ------------------------------------------------------------------ 자가검증(Q3)
def _selftest_drive(window: "object") -> None:
    """동결 exe 부팅 자가검증 — 창이 뜨고 렌더/브리지가 도는지 되읽어 파일로 확정 후 정식 종료.

    소이슈 ①: ``os._exit`` 대신 ``window.destroy()`` 로 이벤트 루프를 정식 종료한다.
    """
    import time

    time.sleep(4.5)
    result: dict = {}
    try:
        result["url"] = window.get_current_url()  # type: ignore[attr-defined]
        result["title_dom"] = window.evaluate_js("document.title")  # type: ignore[attr-defined]
        result["nav_count"] = window.evaluate_js("document.querySelectorAll('.navbtn').length")  # type: ignore[attr-defined]
        result["tpl_options"] = window.evaluate_js(  # type: ignore[attr-defined]
            "Array.from(document.querySelectorAll('#tplSel option')).map(o=>o.value)")
        # 홈(허브)이 기본 화면으로 뜨고 KPI 타일이 실렌더됐는지 되읽는다(#20 착지 심).
        result["home_on"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.getElementById('scr-home').classList.contains('on')")
        result["home_kpi_count"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.querySelectorAll('#homeKpis .kpi').length")
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    # 출력 경로: 테스트 하네스(#30 접근 A)가 HWPX_SELFTEST_OUT 로 결정적 위치를 준다.
    # 미설정 시 동결 exe 옆(dist) — 기존 부팅 자가검증 거동 불변.
    out_override = os.environ.get("HWPX_SELFTEST_OUT")
    out = Path(out_override) if out_override else Path(sys.executable).resolve().parent / "selftest_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    window.destroy()  # type: ignore[attr-defined]  # 정식 종료(os._exit 대체)


# ------------------------------------------------------------------ 엔트리
def main() -> int:
    import webview

    frontend = WebFrontend(default_text_templates_dir())
    window = webview.create_window(
        WINDOW_TITLE,
        str(web_dir() / "index.html"),
        js_api=frontend,
        width=1180,
        height=820,
        min_size=(760, 600),
    )
    frontend._window = window
    # 소이슈 ②: Windows 는 EdgeChromium(WebView2) 백엔드 명시 핀.
    gui = "edgechromium" if sys.platform == "win32" else None
    if "--selftest" in sys.argv:
        webview.start(_selftest_drive, window, gui=gui)
    else:
        webview.start(gui=gui)  # 정상 닫기 = 여기서 반환 → 클린 종료(소이슈 ①)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
