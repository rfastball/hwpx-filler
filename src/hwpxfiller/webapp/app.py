"""pywebview 창 + 브리지 + 엔트리 — 웹 프론트엔드의 링2.

    python -m hwpxfiller.webapp        # 개발 구동(창)
    hwpx-filler-web                    # 설치 후 gui-script

브리지(:class:`WebFrontend`)는 화면 id → 컨트롤러(:mod:`~hwpxfiller.webapp.screens`)
라우팅을 얇게 얹는다. 웹→Python 은
``js_api``(``initial``·``dispatch``·네이티브 동작), Python→웹은 관측 푸시(``window.__push``).

정상 종료는 ``webview.start()`` 반환과 ``window.destroy()`` 를 사용한다. Windows backend 는
외부 UIA 주입 시 WinForms 접근성 재귀를 피하도록 ``edgechromium`` 으로 고정한다. 배포 형태는
``packaging/hwpx_filler_web.spec`` 이 소유한다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from pathlib import Path

from . import boot_budget, settings
from .action_registry import validate_dispatch
from ..core.job import JobRegistry, default_jobs_dir
from ..core.text_registry import TextTemplateRegistry, default_text_templates_dir
from ..data.excel import ambiguous_sheets, sheet_overview  # 다중 시트 확정 게이트 판정(#33)
from ..gui.file_filters import EXCEL_FILTER_PATTERN  # 확장자 단일 출처(RC-34) — Qt-free 상수
from hwpxcore.native import single_instance
from hwpxcore.native._debug import log
from hwpxcore.native.clipboard import set_clipboard_text
from hwpxcore.native.dialogs import open_file_dialog, open_folder_dialog
from hwpxcore.native.reveal import open_path as _native_open_path
from hwpxcore.native.reveal import reveal_in_explorer as _native_reveal
from .screen_draft import DraftController
from .screen_editor import EditorController
from .screen_home import HomeController
from .screen_job import JobController
from .screen_pool import PoolController
from .draft_session import TargetFontSetting
from .screen_template import TemplateController
from .template_groups import TemplateGroupModel
from .screens import (
    collect_owned_paths,
    default_pool_registry,
    validate_owned_path,
)


WINDOW_TITLE = "HWPX Filler"  # 창 제목 = 파일 다이얼로그 소유주 창을 FindWindowW 로 찾는 키
DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900

# 파일 선택 다이얼로그 필터 — pick_data_file·pick_pool_data_file 공유 단일 출처(둘 다
# "엑셀/CSV 데이터" 참조를 다루므로 필터가 같다; 확장자 자체의 단일 출처는 EXCEL_FILTER_PATTERN).
_EXCEL_OR_ANY_FILTERS = [("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")]
# 템플릿 필터 — import_template_file·pick_template_path 공유 단일 출처.
_TEMPLATE_FILTERS = [("HWPX 템플릿", "*.hwpx"), ("모든 파일", "*.*")]
# 라이브러리 가져오기 필터(#108 결정 4) — HWPX·TXT 겸용. 확장자가 곧 매체 라우팅(복사 대상
# 루트 결정)이라 두 형식을 함께 연다("모든 파일"은 오확장 유입 방지로 제외 — import 는 확장자로만 라우팅).
_LIBRARY_IMPORT_FILTERS = [("HWPX·TXT 템플릿", "*.hwpx;*.txt")]


# ------------------------------------------------------------------ 경로 해석
def _repo_root() -> Path:
    # app.py = <repo>/src/hwpxfiller/webapp/app.py → parents[3] = <repo>
    return Path(__file__).resolve().parents[3]


def web_dir() -> Path:
    """정적 자산 루트 — 동결 시 ``sys._MEIPASS/web``, 개발 시 ``<repo>/web``.

    ``HWPXFILLER_WEB_DIR`` 는 테스트 seam(홈 seam ``HWPXFILLER_HOME`` 과 동일 관용구) —
    스테일 캐시 회귀 게이트(#71)가 부팅 사이에 자산을 수정하려면 사본 루트를 서빙해야 한다.
    """
    override = os.environ.get("HWPXFILLER_WEB_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return _repo_root() / "web"


def _virtual_screen_bounds() -> "tuple[int, int, int, int] | None":
    """Windows 가상 데스크톱의 논리 경계. 조회 불가 플랫폼은 ``None``."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return (
            int(user32.GetSystemMetrics(76)),  # SM_XVIRTUALSCREEN
            int(user32.GetSystemMetrics(77)),  # SM_YVIRTUALSCREEN
            int(user32.GetSystemMetrics(78)),  # SM_CXVIRTUALSCREEN
            int(user32.GetSystemMetrics(79)),  # SM_CYVIRTUALSCREEN
        )
    except (AttributeError, OSError):
        return None


def _geometry_is_visible(
    geometry: "dict[str, int | bool]", bounds: "tuple[int, int, int, int] | None" = None
) -> bool:
    """저장 창의 제목줄 일부(64×32)가 현재 가상 화면 안에 남는지 판정한다."""
    bounds = _virtual_screen_bounds() if bounds is None else bounds
    if bounds is None:
        return True
    vx, vy, vw, vh = bounds
    if vw <= 0 or vh <= 0:
        return False
    x, y = int(geometry["x"]), int(geometry["y"])
    width = int(geometry["width"])
    return x + min(width, 64) > vx and x < vx + vw and y + 32 > vy and y < vy + vh


# ------------------------------------------------------------------ 브리지
class WebFrontend:
    """웹→Python js_api + 화면 라우팅. 컨트롤러를 소유하고 창(네이티브 자원)을 쥔다."""

    def __init__(self, text_templates_dir: "str | Path") -> None:
        # 창 참조는 비공개(_) — pywebview 의 js_api 자동노출 반영(util.get_functions)이 공개
        # 속성을 dir() 로 재귀 순회하는데, 공개면 Window→native(WinForms)→AccessibilityObject 로
        # 무한 재귀(recursion depth 초과)하며 WebView2 COM 을 주입 스레드에서 건드려 부팅을
        # 불안정하게 만든다. 밑줄 접두면 반영이 건너뛴다 — 이 참조는 내부 배선일 뿐 JS API 아님.
        self._window: "object | None" = None  # webview.Window (지연 배선)
        # 네이티브 X 닫기 가드(#218 G1) — 확인 뒤 destroy()가 다시 closing 이벤트를
        # 통과하므로 1회 통과 표지와 중복 모달 억제 표지를 브리지가 소유한다.
        self._close_confirmed = False
        self._close_prompt_open = False
        registry = TextTemplateRegistry(text_templates_dir)
        job_registry = JobRegistry(default_jobs_dir())
        # 데이터셋 풀(#26) — 단일 인스턴스를 화면들이 공유: 에디터 자동등록(#3)·실행 겨눔(#6)·
        # 관리 화면(#4)의 변경이 서로 즉시 보인다(레지스트리는 무상태 디렉터리 어댑터).
        pool_registry = default_pool_registry()
        # txt 템플릿 그룹 모델 — 관리 화면과 빠른 기안 승격이 공유하는 단일 실체(#135).
        txt_groups = TemplateGroupModel("txt")
        # 대상 글꼴 선언(결정 17)은 **앱 전역**이라 두 기안 표면이 한 실체를 본다(코덱스 P2:
        # 컨트롤러마다 사본을 캐시하면 한쪽에서 바꾼 선언이 다른 쪽에 재부팅까지 도달하지
        # 않는다 — 저장은 됐는데 그 화면의 콤보·미리보기·정렬 린트는 옛 값으로 판정).
        target_font = TargetFontSetting()
        # 추적성 로케이트 화이트리스트(#53-B)용 레지스트리 참조(밑줄=js_api 반영 제외).
        self._job_registry = job_registry
        self._pool_registry = pool_registry
        # 화면 등록 — 새 화면 = 컨트롤러 1개 추가(순수 데이터는 dispatch, 네이티브는 아래 메서드).
        controllers = [
            # 홈(대시보드) — 허브. TXT 레지스트리는 즉시 기안·템플릿 관리와 공유(변경이 반영).
            # pool_registry 공유 = 데이터 관리에서 생긴 손상이 홈 KPI 경보에 즉시 보인다(#45).
            HomeController(job_registry, registry, self._push, pool_registry=pool_registry),
            # 「작업」 화면 — 좌 목록 + 우 세션 패널 4존. 링1 VM 을 직접 소유하며
            # 실행 결정 계약을 소비하는 유일 세션 표면이다.
            JobController(job_registry, self._push, pool_registry=pool_registry),
            # 「기안」 화면 — TXT 작업-앵커 master-detail(「작업」의 대칭).
            # 같은 job_registry 를 쓰되 media=txt 만 조회한다(조회 경계 결정 13) — 저장 기계는
            # 하나·화면은 둘. 우 상세는 휘발 세션 4존이고, 세션 기계는 「기안문
            # 채우기」와 **같은 믹스인**이라 TXT 레지스트리·풀도 같은 공유 인스턴스를 쓴다
            # (라이브러리 변경·손상 경보가 두 표면에 함께 반영).
            DraftController(job_registry, self._push, registry, pool_registry=pool_registry,
                            target_font=target_font, txt_groups=txt_groups),
            # 템플릿 관리(#13) — TXT 레지스트리는 즉시 기안과 공유(변경이 양쪽에 반영).
            TemplateController(registry, self._push, txt_groups=txt_groups),
            # 데이터 관리(#26 #4) — 등록 데이터 참조·수명.
            PoolController(pool_registry, self._push),
        ]
        # 에디터의 템플릿 라이브러리 = tpl 화면의 VM **같은 인스턴스**:
        # 별도 인스턴스면 두 표면의 스캔 캐시가 갈라져(가져오기·삭제가 한쪽에만 반영) 신규
        # 1단계 피커가 관리 화면과 다른 목록을 조용히 보인다(라이브러리=단일 실체).
        tpl_ctrl = next(c for c in controllers if c.name == "tpl")
        controllers.insert(
            2,
            EditorController(
                job_registry, self._push,
                pool_registry=pool_registry,
                template_library=tpl_ctrl.vm,
                # 1단계 피커 그룹 구획 = tpl 화면과 **같은 hwpx 그룹 모델**:
                # 별도 인스턴스면 접힘·지정 인메모리 캐시가 갈라져 두 표면이 다른 조직을 보인다.
                template_groups=tpl_ctrl.hwpx_groups,
            ),
        )
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
        checked = validate_dispatch(screen, action, {} if payload is None else payload)
        return self._controller(screen).dispatch(action, checked)

    def set_theme(self, mode: str) -> str:
        """테마 선택 영속 — 프런트 토글이 부른다(#74). 확정값 반환(비유효는 ValueError)."""
        settings.save_theme(mode)
        return mode

    def set_font_scale(self, scale: str) -> str:
        """앱 전역 글자 배율 영속 — 브라우저 줌 대신 예측 가능한 3단계 앱 배율."""
        settings.save_font_scale(scale)
        return scale

    def set_rail_collapsed(self, collapsed: bool) -> bool:
        settings.save_rail_collapsed(collapsed)
        return collapsed

    def set_master_width(self, width: int) -> int:
        settings.save_master_width(width)
        return width

    # 바깥 파일의 유일 입구는 import_template_file(가져오기=복사)이다.
    def import_template_file(self, screen: str) -> "str | None":
        """Win32 열기 다이얼로그(HWPX) → 라이브러리로 **복사** 후 사본으로 새 세션(R-info 2부).

        ``pick_template_file``(생 파일 직접 로드)의 후계 — 신규 1단계는 라이브러리가 정본이라
        바깥 파일은 가져오기=복사로만 들어온다. 실패는 ``ERROR:`` 접두.
        """
        path = open_file_dialog(_TEMPLATE_FILTERS, owner_title=WINDOW_TITLE)
        if not path:
            return None
        try:
            return self._controller(screen).import_template(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"

    def pick_data_file(self, screen: str) -> "str | dict | None":
        """Win32 파일 다이얼로그 → 링1 VM 로드. 실패는 ``ERROR:`` 접두로 시끄럽게 반환.

        다중 시트 워크북이면 **조용히 첫 시트를 쓰지 않는다**(#33) — 로드를 미루고 시트
        목록을 실은 ``{"needs_sheet": True, ...}`` 를 돌려줘 웹이 시트를 확정받게 한다.
        확정된 시트로의 실제 로드는 :meth:`load_data_sheet` 가 담당한다.
        """
        log(f"pick_data_file: enter screen={screen}")
        filters = _EXCEL_OR_ANY_FILTERS
        path = open_file_dialog(filters, owner_title=WINDOW_TITLE)
        log(f"pick_data_file: dialog returned {path!r}")
        if not path:
            return None
        # 메타데이터 조회(ambiguous_sheets)와 로드를 같은 예외 변환 경계 안에 둔다 — 손상·잠긴
        # xlsx 의 BadZipFile/OSError 가 pywebview Promise 로 날것으로 새면 웹 핸들러가 못 잡아
        # 사용자에게 조용해진다(confirm-or-alarm). 모호하면 로드 전에 시트 확정 요구로 빠진다.
        try:
            overview = ambiguous_sheets(path)  # 모호할 때만 확정을 요구(빈 목록=단일/CSV)
            if overview:
                return {
                    "needs_sheet": True,
                    "path": path,
                    "name": Path(path).name,
                    "sheets": [{"name": n, "rows": r, "cols": c} for n, r, c in overview],
                }
            self._controller(screen).load_data_path(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name

    def load_data_sheet(self, screen: str, path: str, sheet: str) -> "str | None":
        """웹에서 확정한 시트로 데이터 로드(#33) — 다중 시트 확정 게이트의 착지 지점.

        ``sheet`` 는 반드시 해당 워크북의 **실제 시트명**이어야 한다 — 모르는 이름을 조용히
        첫 시트로 강등하지 않고 시끄럽게 거절한다(confirm-or-alarm). 실패는 ``ERROR:`` 접두.
        시트 재조회(sheet_overview)도 로드와 같은 예외 변환 경계 안에 둔다 — 모달을 연 뒤
        파일이 사라지거나 잠기면 그 실패도 웹에 시끄럽게 되돌린다(P2).
        """
        try:
            names = [n for n, _r, _c in sheet_overview(path)]
            if sheet not in names:
                return f"ERROR: '{sheet}' 시트를 찾을 수 없습니다. 시트를 다시 선택하세요."
            self._controller(screen).load_data_path(path, sheet=sheet)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name

    def copy_clipboard(self, screen: str) -> dict:
        """작업점 카드 렌더를 OS 클립보드로(복사=완료, 결정 16). 리포트를 돌려줘 웹이 재진술.

        복사 후 큐를 전진시킨다(작업점→처리 후미, 전진 opt-in) — 큐 상태 기제는 컨트롤러의
        :meth:`~hwpxfiller.webapp.draft_session.DraftSessionMixin.note_copied` 가 소유(클립보드 쓰기는
        네이티브라 브리지 몫). 큐가 없는 화면(``note_copied`` 부재)은 렌더·복사만 한다.
        """
        ctrl = self._controller(screen)
        text, report = ctrl.render()
        # 작업점 없는 화면(txt 큐, 선택 0·레이스) — 빈 템플릿을 클립보드에 쓰지 않는다(리뷰 F3:
        # 조용한 쓰레기·무피드백 차단). can_copy 부재 화면(다른 소비자)은 종전대로 렌더·복사.
        can = getattr(ctrl, "can_copy", None)
        if can is not None and not can():
            return {"missing_fields": report.missing_fields, "empty_fields": report.empty_fields,
                    "copied": False}
        set_clipboard_text(text)
        note = getattr(ctrl, "note_copied", None)
        if note is not None:  # txt 큐 카드 — 복사분 후미 이동·전진·재푸시(리포트 재사용, 재렌더 없음)
            note(report)
        return {"missing_fields": report.missing_fields, "empty_fields": report.empty_fields,
                "copied": True}

    def pick_output_folder(self, screen: str) -> "str | None":
        """Win32 폴더 피커(SHBrowseForFolder) → 저장 폴더 지정. 「작업」 세션 패널의 네이티브 표면.

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
        """세션 패널(screen 파라미터) 동기 생성 — 게이트 판정·덮어쓰기 재진술·결과 요약 dict."""
        return self._controller(screen).generate(confirm_overwrite=bool(confirm_overwrite))

    def import_library_template(self) -> "str | None":
        """Win32 열기 다이얼로그(HWPX·TXT) → 템플릿 관리 라이브러리로 **복사**(#108 결정 4).

        확장자로 매체 루트를 정해 복사한다(제자리 등록 아님 — 앱 소유 고정 루트). 사본은
        「그룹 없음」에서 시작. 실패는 ``ERROR:`` 접두로 시끄럽게 반환. None = 취소.
        (구 ``pick_library_folder`` 폐기: 고정 루트라 라이브러리 재지정 표면이 사라짐 —
        결정 4 "습관 고정".)"""
        path = open_file_dialog(_LIBRARY_IMPORT_FILTERS, owner_title=WINDOW_TITLE)
        if not path:
            return None
        try:
            return self._controller("tpl").import_into_library(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"

    def editor_has_unsaved_work(self) -> bool:
        """에디터에 진행 중인(미저장) 작업 세션이 있는가 — 크로스스크린 진입 전 폐기 확인용(#25)."""
        return self._controller("editor").has_unsaved_work()

    def close_guard_state(self) -> dict:
        """창 종료로 사라질 세션 상태를 한 시점에 판정한다(#218 G1)."""
        reasons: list[str] = []
        if self._controller("editor").has_unsaved_work():
            reasons.append("저장하지 않은 작업 편집")
        if self._controller("job")._guard_state()["armed"]:
            reasons.append("작업 화면의 완료하지 않은 선택")
        if self._controller("draft")._leave_guard()["armed"]:
            reasons.append("기안 화면의 미저장 원문·매핑 또는 큐 진행")
        return {"armed": bool(reasons), "reasons": reasons}

    def _show_close_prompt(self, state: dict) -> None:
        """closing 콜백 바깥 스레드에서 웹 확인창을 연다(WinForms UI 재진입 회피)."""
        if self._window is None:
            self._close_prompt_open = False
            return
        try:
            payload = json.dumps(state, ensure_ascii=False)
            self._window.evaluate_js(  # type: ignore[attr-defined]
                f"window.AppCloseGuard && window.AppCloseGuard.prompt({payload})"
            )
        except Exception as exc:  # noqa: BLE001 — 실패 시 안전측(창 유지)+loud
            self._close_prompt_open = False
            _alarm(f"종료 확인창 표시 실패: {exc!r}", self._window)

    def _handle_window_closing(self) -> "bool | None":
        """pywebview ``closing`` 이벤트 — False면 닫기를 취소한다."""
        if self._close_confirmed:
            return None
        state = self.close_guard_state()
        if not state["armed"]:
            return None
        if not self._close_prompt_open:
            self._close_prompt_open = True
            timer = threading.Timer(0, self._show_close_prompt, args=(state,))
            timer.daemon = True
            timer.start()
        return False

    def confirm_window_close(self) -> bool:
        """웹 종료 확인의 확정 착지 — 다음 closing 1회를 통과시켜 실제로 닫는다."""
        self._close_confirmed = True
        self._close_prompt_open = False
        if self._window is not None:
            self._window.destroy()  # type: ignore[attr-defined]
        return True

    def cancel_window_close(self) -> bool:
        """웹 종료 확인 취소 — 다음 X 입력에서 현재 상태를 다시 판정할 수 있게 한다."""
        self._close_prompt_open = False
        return True

    def pick_pool_data_file(self) -> "str | None":
        """데이터 관리 등록 모달 '찾아보기' → **경로만** 반환(#26 #4).

        ``pick_data_file`` 과 달리 어떤 컨트롤러에도 로드하지 않는다 — 등록은 참조
        저장이지 데이터 로드가 아니다(행 미저장 불변식). None = 취소.
        """
        filters = _EXCEL_OR_ANY_FILTERS
        return open_file_dialog(filters, owner_title=WINDOW_TITLE)

    def pick_template_path(self) -> "str | None":
        """템플릿 다시 연결(#67) '찾아보기' → **경로만** 반환(``pick_pool_data_file`` 미러).

        ``import_template_file`` 과 달리 어떤 컨트롤러에도 로드하지 않는다 — 재연결의
        검증·확정은 dispatch(``relink_template``)의 confirm 게이트가 담당. None = 취소.
        """
        return open_file_dialog(_TEMPLATE_FILTERS, owner_title=WINDOW_TITLE)

    def reveal_corrupt_job(self, path: str) -> "str | None":
        """홈 손상 카드 '폴더 열기' → 탐색기에서 해당 파일 표시(#26 #8 해소 동선).

        경로는 홈 컨트롤러의 손상 목록 화이트리스트로 검증한다 — 웹 페이로드로 임의
        경로를 여는 통로를 봉쇄. 실패는 ``ERROR:`` 접두.
        """
        try:
            target = self._controller("home").validate_corrupt_path(path)
            _native_reveal(target)  # explorer /select 승격 헬퍼 재사용(#53-B)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return None

    # ---------------------------------------- 추적성 로케이트(#53-B)
    def copy_path(self, path: str) -> "str | None":
        """추적성 '경로 복사' → 검증된 소유 경로를 클립보드에. 실패는 ``ERROR:`` 접두."""
        try:
            set_clipboard_text(str(self._validate_owned(path)))
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return None

    def reveal_path(self, path: str) -> "str | None":
        """추적성 '폴더에서 보기' → 검증된 소유 경로를 탐색기에서 선택 표시."""
        try:
            _native_reveal(self._validate_owned(path))
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"
        return None

    def open_path(self, path: str) -> "str | None":
        """추적성 '열기' → 검증된 소유 경로를 OS 기본 앱으로 연다."""
        try:
            _native_open_path(self._validate_owned(path))
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"
        return None

    def _validate_owned(self, path: str) -> str:
        """소유 화이트리스트(작업 템플릿·등록 데이터·현재 세션 경로)로 검증 — 순수 로직은
        :func:`screens.collect_owned_paths`/`validate_owned_path`(헤드리스 테스트 대상)."""
        ed = self._controller("editor")
        job = self._controller("job")
        session = [getattr(ed, "template_path", ""), getattr(ed, "data_path", ""),
                   getattr(job, "out_dir", "")]
        owned = collect_owned_paths(self._job_registry, self._pool_registry, session)
        return validate_owned_path(path, owned)

    def open_job_in_editor(self, name: str) -> "str | None":
        """홈 '편집' → 저장된 작업을 에디터 편집 세션으로 복원(#26 편집 모드).

        웹은 이 호출 후 에디터 화면으로 전환한다. 실패(작업 손상·템플릿 부재·RAW)는
        ``ERROR:`` 접두로 시끄럽게 반환. 미저장 세션 확인은 웹이 ``editor_has_unsaved_work``
        로 선판단한다(#25 미러).
        """
        try:
            self._controller("editor").load_job(name)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return name

    def load_template_into_editor(self, path: str) -> "str | None":
        """템플릿 관리 '작업 만들기' → 그 템플릿을 에디터에 로드(크로스스크린). 파일명·``ERROR:``.

        웹은 이 호출 후 편집 모드로 전환한다 — 링1 seam(editor.new_job_session)을 재사용해
        VM 로직을 재구현하지 않는다. 새 템플릿 진입은 새 작업 세션이라 이전 세션을 원자
        초기화한다(#25) — 미저장 확인은 웹이 has_unsaved_work 로 선판단한다.

        웹 유래 경로는 라이브러리 소속 확인을 거친다(PR-4 리뷰 F4) — use_library_template
        만 막고 이 seam 을 열어 두면 「가져오기=복사가 유일한 바깥 입구」(2부)가 문서만의
        불변식이 된다. tpl 화면과 VM 을 공유하므로 정상 경로는 항상 통과한다.
        """
        try:
            ctrl = self._controller("editor")
            ctrl.assert_library_path(path)
            ctrl.new_job_session(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name


# 모달 접근성 동적 프로브(#27/#28) — 실 브라우저에서 Modal 헬퍼의 초기포커스·Escape·복귀를
# 되읽는다. 알려진 트리거(첫 내비 버튼)에 포커스 → draftSaveTplModal 열기 → Escape → 복귀 확인.
# (구 pasteModal 은 #148 슬라이스 6 에서 scr-txt 와 함께 삭제 — 같은 Modal 헬퍼를 쓰는 생존
# 모달로 재겨눔.) IIFE 가 JSON 직렬화 가능한 객체를 반환하고, 게이트 테스트가 각 필드를 단언한다.
_MODAL_A11Y_PROBE_JS = r"""
(function () {
  function finishModal(id) {
    var card = document.querySelector('#' + id + ' .modal-card');
    if (!card) return;
    var ev = new Event('transitionend', { bubbles: true });
    Object.defineProperty(ev, 'propertyName', { value: 'opacity' });
    card.dispatchEvent(ev);
  }
  var trigger = document.querySelector('.navbtn');
  trigger.focus();
  var before = document.activeElement.getAttribute('data-scr');
  window.Modal.open('draftSaveTplModal', { initialFocus: document.getElementById('draftSaveTplName') });
  var opened = !document.getElementById('draftSaveTplModal').classList.contains('hidden');
  var focusIn = document.activeElement.id;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  var escapeClosing = document.getElementById('draftSaveTplModal').classList.contains('is-closing');
  finishModal('draftSaveTplModal');
  var closed = document.getElementById('draftSaveTplModal').classList.contains('hidden');
  var restored = document.activeElement.getAttribute('data-scr');
  // #86/B-9: 네이티브 confirm 대체 모달의 실 개폐 — .modal{display:flex} 가 hidden 을 덮지
  // 않는지 계산 스타일로 확인한다(부록 B-9 결함 클래스). 기본 포커스=취소(머무르기, 결정 27/36/38).
  // + PR #92 리뷰 #1: 단일 실행 직렬화(재진입 loud 거절)와 Tab 트랩을 실 DOM 에서 되읽는다.
  var cm = document.getElementById('confirmModal');
  var cDisplayClosedBefore = getComputedStyle(cm).display;   // 열기 전 'none'
  var alerts = [];
  var origAlert = window.alert;                              // 재진입 거절의 loud alert 를 기록으로 대체
  window.alert = function (m) { alerts.push(String(m)); };
  window.__cf1 = 'pending'; window.__cf2 = 'pending';
  window.Modal.confirm({ body: '첫 확인 본문' }).then(function (v) { window.__cf1 = v; });
  var cOpened = !cm.classList.contains('hidden');
  var cDisplayOpen = getComputedStyle(cm).display;           // 열린 뒤 'flex'
  var cFocus = document.activeElement.id;                    // 취소 버튼에 초기 포커스
  // 재진입 시도(#92 리뷰 #1) — 즉시 거절(refusal)돼야 하고 loud 해야 하며, 첫 다이얼로그의
  // 본문·리스너가 덮이지 않아야 한다(이중 바인딩이면 아래 OK 1클릭에 두 확정이 디스패치된다).
  window.Modal.confirm({ body: '둘째 확인 본문' }).then(function (v) { window.__cf2 = v; });
  var reentryAlerts = alerts.length;                         // 거절이 loud 였는가(1 기대)
  var bodyAfterReentry = document.getElementById('confirmModalBody').textContent;
  // Tab 트랩(#92 리뷰 #1) — 마지막 포커서블(확인)에서 Tab 이 배경으로 새지 않고 첫 요소로 순환.
  document.getElementById('confirmModalOk').focus();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
  var trapWrapped = document.activeElement.id;               // confirmModalCancel 기대
  document.getElementById('confirmModalOk').click();         // 확인 클릭 → 닫힘 + resolve(true)
  var confirmClosing = cm.classList.contains('is-closing');
  finishModal('confirmModal');
  var cClosed = cm.classList.contains('hidden');
  var cDisplayClosed = getComputedStyle(cm).display;         // 닫힌 뒤 'none'
  // #219 danger 변형 — 같은 안정 버튼이 danger↔neutral 양방향으로 클래스·계산색을 바꾸는가.
  window.Modal.confirm({ body: '영구 삭제', confirmLabel: '삭제', danger: true });
  var dangerOk = document.getElementById('confirmModalOk');
  var dangerClass = dangerOk.classList.contains('danger') && !dangerOk.classList.contains('primary');
  var dangerBg = getComputedStyle(dangerOk).backgroundColor;
  document.getElementById('confirmModalCancel').click();
  finishModal('confirmModal');
  window.Modal.confirm({ body: '중립 전환', confirmLabel: '계속' });
  var neutralReset = !dangerOk.classList.contains('danger') && dangerOk.classList.contains('primary');
  document.getElementById('confirmModalCancel').click();
  finishModal('confirmModal');
  window.alert = origAlert;
  // #132.4: Modal.open/close 가 .modal 없는 요소를 시끄럽게 거절하는가(조용한 no-op 차단).
  // 잠복 결함: .hidden 은 .modal.hidden 규칙으로만 숨어, .modal 없는 요소에 open 하면 토글이 무효다.
  var mErrs = [];
  var origErr = console.error;
  var np = document.createElement('div');
  np.id = '__nonModalProbe'; np.className = 'hidden';        // .modal 없음 — 숨김 규칙 안 먹음
  document.body.appendChild(np);
  var openRejected = false, closeRejected = false;
  console.error = function () { mErrs.push(Array.prototype.join.call(arguments, ' ')); };
  try {
    var e0 = mErrs.length;
    window.Modal.open('__nonModalProbe');                    // 거절 기대: loud + 미개방
    // loud 는 가드 자신의 메시지로 판정한다(무관한 미래 error 로 초록 위장 차단, 리뷰 F3).
    openRejected = mErrs.slice(e0).some(function (m) { return m.indexOf('Modal.open') >= 0; })
      && np.classList.contains('hidden');                    // + 상태 control: 안 열림(hidden 유지)
    var e1 = mErrs.length;
    window.Modal.close('__nonModalProbe');                   // 대칭 거절 기대
    closeRejected = mErrs.slice(e1).some(function (m) { return m.indexOf('Modal.close') >= 0; });
  } finally {
    console.error = origErr;                                 // 어떤 throw 에도 원복(리뷰 F2 — 아니면
    document.body.removeChild(np);                           // 실앱 console.error 가 영구 삼켜진다)
  }
  // Codex P2 회귀 잠금: confirm root 가 .modal 을 잃어도 (a) loud 거절, (b) pendingDialog 미교착
  // (후속 정상 confirm 이 열린다). _promiseModal 이 pendingDialog 세우기 *전* .modal 을 검증하므로
  // open 가드의 early-return 으로 플래그가 갇히지 않는다. confirmModal 을 한시 불량화 후 반드시 원복.
  var cmR = document.getElementById('confirmModal');
  var malfLoud = false, afterMalfOpens = false;
  var oErr2 = console.error, oAlert2 = window.alert;
  console.error = function () { malfLoud = true; };
  window.alert = function () {};                            // 불량 경로의 실 alert 블로킹 차단
  try {
    cmR.classList.remove('modal');                          // 골격 불량 재현
    window.Modal.confirm({ body: '불량 root' });             // pendingDialog 세우기 전에 거절돼야
    cmR.classList.add('modal');                             // 후속 정상 확인 전 원복
    window.Modal.confirm({ body: '후속 정상' });              // 교착이면 재진입 거절로 안 열린다
    afterMalfOpens = !cmR.classList.contains('hidden');
  } finally {
    if (!cmR.classList.contains('modal')) cmR.classList.add('modal');  // 어떤 경로든 .modal 원복
    console.error = oErr2; window.alert = oAlert2;
  }
  if (afterMalfOpens) {
    document.getElementById('confirmModalCancel').click();  // 후속 닫아 상태 원복
    finishModal('confirmModal');
  }
  return {
    opened: opened,               // 열기 후 hidden 해제됐는가
    focus_in: focusIn,            // 초기 포커스가 모달 안(pasteText)으로 들어갔는가
    closed_by_escape: closed,     // Escape 로 닫혔는가
    focus_before: before,         // 열기 직전 트리거(내비 data-scr)
    focus_restored: restored,     // 닫은 뒤 포커스가 트리거로 복귀했는가
    escape_entered_closing: escapeClosing, // H-16: display:none 전 퇴장 상태를 실제 거쳤는가
    confirm_display_closed_before: cDisplayClosedBefore,  // #86: 열기 전 display(none 기대)
    confirm_opened: cOpened,      // #86: Modal.confirm 이 hidden 해제했는가
    confirm_display_open: cDisplayOpen,  // #86/B-9: 열린 동안 display(flex 기대)
    confirm_focus: cFocus,        // #86: 초기 포커스가 취소(머무르기)인가
    confirm_reentry_alerts: reentryAlerts,       // #92 #1: 재진입 거절이 loud 였는가(1 기대)
    confirm_body_after_reentry: bodyAfterReentry, // #92 #1: 첫 본문이 덮이지 않았는가
    confirm_trap_wrapped: trapWrapped,           // #92 #1: Tab 이 모달 안에서 순환했는가
    confirm_closed: cClosed,      // #86: 확인 클릭 후 다시 hidden 인가
    confirm_entered_closing: confirmClosing, // H-16: 확인도 대칭 퇴장 상태를 실제 거쳤는가
    confirm_display_closed: cDisplayClosed,  // #86/B-9: 닫힌 뒤 display(none 기대, hidden 이 flex 를 이긴다)
    danger_class: dangerClass,      // #219: danger=true가 primary를 적색 변형으로 교체
    danger_background: dangerBg,    // #219: 실 계산 배경색(transparent 금지)
    danger_resets_to_neutral: neutralReset, // #219: 다음 중립 confirm에 danger 클래스 누수 없음
    non_modal_open_rejected_loud: openRejected,   // #132.4: .modal 없는 open 이 loud 거절+미개방인가
    non_modal_close_rejected_loud: closeRejected, // #132.4: .modal 없는 close 도 loud 거절인가
    malformed_confirm_root_refused_loud: malfLoud, // Codex P2: 불량(.modal 없는) confirm root loud 거절
    confirm_after_malformed_opens: afterMalfOpens  // Codex P2: 교착 없이 후속 confirm 이 열리는가
  };
})()
"""


# 다중 시트 확정 게이트 프로브(#33) — 실 브라우저에서 SheetPicker.choose 를 end-to-end 로 구동한다.
# 조용한 첫 시트 로드 금지의 핵심 보장을 실 DOM 에서 되읽는다: (1) 확정(시트 클릭)하면 그 시트로
# 로드돼 파일명이 해소되고, (2) 취소(Escape)하면 로드가 일어나지 않고 null 로 해소(중단)된다.
# Bridge.loadDataSheet 는 창을 실제로 열지 않도록 스텁(확정 시 파일명 반환) — 저장/복원한다.
# choose 는 async·상호작용 구동이라 setup 에서 fire→window.__sheetProbe 에 stash, 뒤에서 되읽는다.
_SHEET_PROBE_SETUP_JS = r"""
(function () {
  function finishModal(id) {
    var card = document.querySelector('#' + id + ' .modal-card');
    if (!card) return;
    var ev = new Event('transitionend', { bubbles: true });
    Object.defineProperty(ev, 'propertyName', { value: 'opacity' });
    card.dispatchEvent(ev);
  }
  window.__sheetProbe = { status: 'running' };
  var origLoad = window.Bridge.loadDataSheet;
  window.Bridge.loadDataSheet = function (screen, path, sheet) {
    return Promise.resolve('확정됨:' + sheet);  // 실 다이얼로그 대신 확정 시트명을 되쏨
  };
  var payload = {
    needs_sheet: true, path: 'C:/x/multi.xlsx', name: 'multi.xlsx',
    sheets: [{ name: '공고목록', rows: 3, cols: 2 }, { name: '낙찰현황', rows: 4, cols: 3 }]
  };
  (async function () {
    try {
      // (1) 확정 경로 — 열림·버튼수·초기포커스 되읽고 둘째 시트를 클릭해 해소.
      var p1 = window.SheetPicker.choose('job', payload);
      var opened = !document.getElementById('sheetModal').classList.contains('hidden');
      var btns = document.querySelectorAll('#sheetList .sheet-opt');
      var focusFirst = document.activeElement === btns[0];
      btns[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
      // onPick은 Bridge.loadDataSheet(Promise)를 await한 뒤 close하므로 마이크로태스크를 먼저
      // 흘려 실제 is-closing 진입을 만든 다음 transitionend를 완료시킨다.
      await Promise.resolve();
      finishModal('sheetModal');
      var picked = await p1;
      // (2) 취소 경로 — 다시 열고 Escape → null 로 해소(로드 없음).
      var p2 = window.SheetPicker.choose('job', payload);
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      finishModal('sheetModal');
      var cancelled = await p2;
      window.__sheetProbe = {
        status: 'done',
        opened: opened,                 // choose 가 모달을 열었는가
        btn_count: btns.length,         // 시트 수만큼 옵션 버튼
        focus_first: focusFirst,        // 초기 포커스가 첫 옵션에
        picked: picked,                 // 확정 시 확정 시트로 로드된 결과(확정됨:낙찰현황)
        cancelled: cancelled,           // 취소 시 null(중단 — 첫 시트 강등 없음)
        closed_after: document.getElementById('sheetModal').classList.contains('hidden')
      };
    } catch (e) {
      window.__sheetProbe = { status: 'throw', message: e && e.message };
    } finally {
      window.Bridge.loadDataSheet = origLoad;
    }
  })();
})()
"""


# 상호작용 보존 기제 프로브(#28) — 실 브라우저에서 Preserve 헬퍼가 innerHTML 재구성을 가로질러
# 포커스·캐럿(selection)·옵트인 스크롤을 실제로 보존하는지 되읽는다. 화면 네비/데이터 의존 없이
# 결정적으로 기제를 검증하기 위해 임시 픽스처를 만들어 실제 focus/setSelectionRange/scrollTop 을
# 건 뒤, render() 가 하는 것과 동일한 innerHTML 교체를 Preserve.around 로 감싸 되읽는다.
_PRESERVE_PROBE_JS = r"""
(function () {
  var host = document.createElement('div');
  host.id = 'preserveProbeHost';
  host.setAttribute('data-preserve-scroll', '');
  host.style.cssText = 'height:40px;overflow:auto';
  var markup = '<div style="height:400px"><input id="preserveProbeInput" value="abcdef"></div>';
  host.innerHTML = markup;
  document.body.appendChild(host);
  var input = document.getElementById('preserveProbeInput');
  input.focus();
  input.setSelectionRange(2, 4);
  host.scrollTop = 120;
  window.Preserve.around(function () { host.innerHTML = markup; });  // render() 의 재구성과 동형
  var a = document.activeElement;
  var res = {
    focus_id: a ? a.id : null,          // 재구성 뒤 같은 입력으로 포커스 복귀했는가
    sel_start: a ? a.selectionStart : null,  // 캐럿/선택 범위 보존(2)
    sel_end: a ? a.selectionEnd : null,      // (4)
    scroll_top: document.getElementById('preserveProbeHost').scrollTop  // 옵트인 스크롤 보존(120)
  };
  host.remove();
  return res;
})()
"""

# 실화면 회귀(#28 완료기준) — 위 기제 프로브는 합성 픽스처였고, 여기선 shipped __push 경로로
# 실 컨트롤러 스냅샷을 3개 실화면 render() 에 흘려 (a) Preserve.around 래핑이 실 render 를
# 깨지 않는지, (b) txt 작업점 카드 렌더(#txtCardRender)의 스크롤이 실 재렌더를 가로질러 유지되는지 되읽는다.
# 스냅샷은 실 컨트롤러 initial()(비동기) 로 당겨 stash 하고, 스크롤은 가시 화면에서만 유효하므로
# txt 를 가시화한다. 셋업(비동기 fire)과 되읽기 사이에 한 번 대기.
_PRESERVE_REAL_SETUP_JS = r"""
(function () {
  window.__snaps = {};
  ['draft', 'editor', 'job'].forEach(function (scr) {
    window.pywebview.api.initial(scr).then(function (s) { window.__snaps[scr] = s; });
  });
  window.Nav.go('draft');  // 스크롤은 가시 화면에서만 유효 → 기안 가시화(구 txt 흡수, 슬라이스 6)
})()
"""

_PRESERVE_REAL_PROBE_JS = r"""
(function () {
  var out = {}, snaps = window.__snaps || {};
  ['draft', 'editor', 'job'].forEach(function (scr) {
    try {
      if (!snaps[scr]) { out[scr] = 'no-snap'; return; }
      window.__push(scr, snaps[scr]);   // 실 render() (Preserve.around 래핑)
      out[scr] = 'ok';
    } catch (e) { out[scr] = 'throw:' + (e && e.message); }
  });
  // 기안 스크롤 보존 end-to-end: **맞추기 표 패널**(#draftTokPanel, max-height 300px·overflow
  // auto)을 강제로 길게 → 오버플로 → 스크롤 → 재렌더 → 유지? 작업점 카드(#draftCardRender)는
  // master-detail 우측 패널(.job-panel{overflow:auto})이 통째로 스크롤하는 설계라 자라기만 하고
  // 내부 스크롤이 없다(구 txt 전체화면과 다르다) — 실제 내부 스크롤 요소인 토큰 패널로 겨눈다.
  // renderMap 은 snap.tokens 를 그대로 그리므로 토큰 15개를 주입해 300px 를 넘긴다(패널 자체가
  // Preserve.around 안에서 재구성되므로 재렌더 가로지른 스크롤 복원을 실 render() 경로로 본다).
  try {
    var snap = snaps['draft'];
    if (!snap) { out.draft_scroll_top = 'no-snap'; return out; }
    var toks = [];
    for (var i = 0; i < 15; i++) {
      toks.push({ name: '토큰' + i, state: 'missing', source: '', own: '', manual: false,
        value: '', fmt_kind: 'text', fmt_code: '', suggest: '', can_revert: false,
        confirmed: false, blank_declared: false });
    }
    snap.tokens = toks;
    window.__push('draft', snap);
    var box = document.getElementById('draftTokPanel');
    box.scrollTop = 60;                 // 300px 패널의 오버플로 안 — 클램프 없이 남을 값
    window.__push('draft', snap);       // 실 재렌더 — Preserve 가 스크롤 복원해야
    out.draft_scroll_top = document.getElementById('draftTokPanel').scrollTop;
  } catch (e) { out.draft_scroll_top = 'throw:' + (e && e.message); }
  return out;
})()
"""


# 기안 펼침 면(#271) — 실 DOM 이동(복제 없음), Filled 강제, Escape/버튼 닫기 뒤 원위치·
# 포커스·스크롤 복귀, 데이터 첫 열 sticky를 실제 WebView2에서 되읽는다.
_DRAFT_SHEETS_PROBE_JS = r"""
(function () {
  var out = {};
  function finish(id) {
    var card = document.querySelector('#' + id + ' .modal-card');
    var ev = new Event('transitionend', {bubbles:true});
    Object.defineProperty(ev, 'propertyName', {value:'opacity'});
    card.dispatchEvent(ev);
  }
  try {
    window.Nav.go('draft');
    var map = document.getElementById('draftTokPanel');
    var legend = document.getElementById('draftMapLegend');
    var readout = document.getElementById('draftCardReadout');
    var render = document.getElementById('draftCardRender');
    var mapParent = map.parentNode, legendParent = legend.parentNode;
    var readoutParent = readout.parentNode, renderParent = render.parentNode;
    // 현재 스냅샷의 토큰 수와 무관하게 실제 오버플로를 만들어 이동 전 스크롤을 검증한다.
    var spacer = document.createElement('div'); spacer.style.height = '500px';
    map.appendChild(spacer); map.style.maxHeight = '80px'; map.style.height = '80px';
    map.scrollTop = 37;
    document.getElementById('draftViewSource').click();
    var trigger = document.getElementById('draftMapExpand');
    trigger.focus(); trigger.click();
    var sheet = document.getElementById('draftMapSheet');
    out.map_open = !sheet.classList.contains('hidden');
    out.map_moved = document.getElementById('draftMapSheetMapSlot').contains(map) &&
      document.getElementById('draftMapSheetMapSlot').contains(legend);
    out.preview_moved = document.getElementById('draftMapSheetPreviewSlot').contains(readout) &&
      document.getElementById('draftMapSheetPreviewSlot').contains(render);
    out.filled_forced = !render.hidden && document.getElementById('draftSrcView').hidden;
    out.same_map = map === document.getElementById('draftTokPanel');
    document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));
    finish('draftMapSheet');
    out.map_restored = map.parentNode === mapParent && legend.parentNode === legendParent &&
      readout.parentNode === readoutParent && render.parentNode === renderParent;
    out.map_scroll = map.scrollTop;
    out.map_focus_restored = document.activeElement === trigger;
    spacer.remove(); map.style.maxHeight = ''; map.style.height = '';

    var head = document.getElementById('draftRecsHead');
    var chips = document.getElementById('draftFilterChips');
    var table = document.getElementById('draftTableHost');
    var strip = document.getElementById('draftSelStrip');
    var panel = document.getElementById('draftColPanel');
    var parents = [head.parentNode, chips.parentNode, table.parentNode, strip.parentNode, panel.parentNode];
    var dataTrigger = document.getElementById('draftDataExpand');
    dataTrigger.focus(); dataTrigger.click();
    var slot = document.getElementById('dataSheetSlot');
    out.data_moved = slot.contains(head) && slot.contains(chips) && slot.contains(table) &&
      slot.contains(strip) && slot.contains(panel);
    var first = document.querySelector('#draftTableHead th:first-child');
    out.first_col_sticky = !first || getComputedStyle(first).position === 'sticky';
    document.getElementById('dataSheetClose').click(); finish('dataSheet');
    out.data_restored = head.parentNode === parents[0] && chips.parentNode === parents[1] &&
      table.parentNode === parents[2] && strip.parentNode === parents[3] && panel.parentNode === parents[4];
    out.data_focus_restored = document.activeElement === dataTrigger;
    out.error = null;
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""


# 「작업」 본문 존 거울 + 재진술 블록(블록 6 D2/D1, 슬라이스 2) — 합성 스냅샷을 shipped __push 로
# 실 render() 에 흘려 거울 테이블 4상태 행·미입력 클릭형·재진술 이름 목록·드리프트 차단 배너가
# 실 WebView2 에서 실제로 그려지는지 되읽는다(정적 계약은 test_web_dom_contract, 값 합성은
# test_webapp_job 가 보고, 여기선 렌더 거동 — 부록 B-9 overlay/hidden 눈검증의 자동판).
_JOB_MIRROR_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    var snap = {
      job_rows: [{name:'공고서', selected:true}], job_name:'공고서', has_job:true,
      out_dir:'C:\\Results', data_label:'d.csv', data_source_label:'d.csv (파일)', data_notice:null,
      template_name:'t.hwpx', template_path:'C:\\t.hwpx', template_missing:false,
      filename_pattern:'doc-{{seq}}', has_data:true, record_count:2, selected_count:2,
      records:[{index:0, selected:true, name:'doc-001.hwpx', summary:'전산장비'},
               {index:1, selected:true, name:'doc-002.hwpx', summary:'사무비품'}],
      // 필터 표면(블록 4, 슬라이스 4 PR-2b) — 검색 「전산」이 공고명 가지에 선 상태를 합성:
      // 가시 1행(하이라이트 세그먼트) + 필터 밖 선택 1행(스트립) + 유래 수치 병기(S4).
      // reapply_available 는 여기서만 active 와 공존한다 — 실모델의 3연언(#127)은 현 필터가
      // 빈 상태에서만 켜므로 이 조합은 합성이다. 어포던스 배선(켜짐/꺼짐·title)만 되읽는다.
      filter:{active:true, reapply_available:true, reapply_hint:'(공고명) 포함 「전산」',
              search:'전산',
              chips:['(공고명) 포함 「전산」'],
              definition:'(공고명) 포함 「전산」', branches:['공고명'],
              columns:[{name:'공고명', kind:'text', active:false},
                       {name:'금액', kind:'amount', active:false}]},
      table:{columns:[{name:'공고명', kind:'text'}, {name:'금액', kind:'amount'}],
             rows:[{index:0, selected:true, name:'doc-001.hwpx', summary:'전산장비',
                    cells:[[['전산',true],['장비',false]], [['1,000,000원',false]]]}],
             visible_count:1,
             hidden_selected:[{index:1, selected:true, name:'doc-002.hwpx', summary:'사무비품'}]},
      restate:{origin:'manual', filter_active:true, in_def:1, extra:1, sample:[0]},
      preflight:{level:'ok', text:'ok'},
      mirror:[
        {name:'공고명', state:'filled', acknowledged:false, value:'전산장비 (표본 · 외 1개 값)', formatted:false},
        {name:'금액', state:'filled', acknowledged:false, value:'2,000,000원', formatted:true},
        {name:'낙찰율', state:'missing', acknowledged:false, value:'(빈 값) 선택 2행 중 1행에서 값이 비어 있습니다.', formatted:false},
        {name:'비고', state:'blank', acknowledged:false, value:'(비움 확정)', formatted:false}
      ],
      drift:[], gate:{enabled:true, level:'', text:'생성 준비'}
    };
    window.__push('job', snap);
    out.mirror_rows = document.querySelectorAll('#jobMirror table.mir tbody tr').length;
    out.miss_clickable = !!document.querySelector('#jobMirror .mir-row.miss[role="button"]');
    out.chips = Array.prototype.map.call(
      document.querySelectorAll('#jobMirror .mir .st'), function (e) { return e.textContent; });
    out.restate_shown = getComputedStyle(document.getElementById('jobRestate')).display !== 'none';
    out.restate_names = document.querySelectorAll('#jobRestate .namelist .nm').length;
    // 필터 표면 되읽기(블록 4) — 가시 행·하이라이트·칩·가지 ×·스트립·유래 수치·아이콘.
    out.tbl_rows = document.querySelectorAll('#jobTableBody tr[data-i]').length;
    var renderedRow = document.querySelector('#jobTableBody tr[data-i]');
    var renderedAmount = document.querySelector('#jobTableBody td.col-amount');
    out.row_role = renderedRow && renderedRow.getAttribute('role');
    out.row_selected = renderedRow && renderedRow.getAttribute('aria-selected');
    out.row_checkbox = !!document.querySelector('#jobTableBody td.doccol input[type="checkbox"]');
    out.row_doccell_display = getComputedStyle(document.querySelector('#jobTableBody .doccell')).display;
    out.lead_hint = document.querySelector('#jobTableHead .col-hint').textContent;
    out.repeated_placeholder = document.querySelectorAll('#jobTableBody .doc-off:not([aria-hidden="true"])').length;
    out.amount_align = getComputedStyle(renderedAmount).textAlign;
    out.amount_nums = getComputedStyle(renderedAmount).fontVariantNumeric;
    out.tbl_mark = (function(){ var m = document.querySelector('#jobTableBody mark');
      return m ? m.textContent : ''; })();
    out.ficos = document.querySelectorAll('#jobTableHead .fico[data-col]').length;
    out.chips_text = document.getElementById('jobFilterChips').textContent;
    out.branch_prune = !!document.querySelector('#jobFilterChips [data-prune="공고명"]');
    var definitionChip = document.querySelector('#jobFilterChips .fchip.definition');
    var branchChip = document.querySelector('#jobFilterChips .fchip.branch');
    out.filter_role_labels = Array.from(document.querySelectorAll('.fchip .chip-role')).map(
      function (e) { return e.textContent; });
    out.definition_bg = getComputedStyle(definitionChip).backgroundColor;
    out.branch_bg = getComputedStyle(branchChip).backgroundColor;
    out.branch_border_style = getComputedStyle(branchChip).borderStyle;
    out.strip_shown = getComputedStyle(document.getElementById('jobSelStrip')).display !== 'none';
    out.strip_text = document.getElementById('jobSelStrip').textContent;
    out.strip_bg = getComputedStyle(document.getElementById('jobSelStrip')).backgroundColor;
    // 스트립 항목별 × 해제 어포던스(리뷰 #6 — 진술만 하고 행동을 못 주면 반쪽).
    out.strip_unsel = !!document.querySelector('#jobSelStrip [data-unsel="1"]');
    out.sel_line = document.getElementById('jobRestate').textContent;
    // 왕복을 일부러 미결로 둔 채 두 번 누른다. 둘째 값이 첫 낙관 표지를 기준으로 계산돼야
    // true→false→true가 되고, native checkbox·aria-selected·행 tint가 같은 프레임에 맞는다(#217 R2).
    var realCall = window.Bridge.call;
    var toggleValues = [];
    window.Bridge.call = function (screen, action, payload) {
      if (action === 'toggle_record') {
        toggleValues.push(payload.value);
        return new Promise(function () {});
      }
      if (action === 'filter_panel') return new Promise(function () {});
      return realCall.call(window.Bridge, screen, action, payload);
    };
    renderedRow.click();
    out.row_optimistic_off = !renderedRow.classList.contains('on') &&
      renderedRow.getAttribute('aria-selected') === 'false' && !renderedRow.querySelector('input').checked;
    renderedRow.click();
    out.row_optimistic_on = renderedRow.classList.contains('on') &&
      renderedRow.getAttribute('aria-selected') === 'true' && renderedRow.querySelector('input').checked;
    out.row_toggle_values = toggleValues.slice();
    // filter_panel 응답은 영원히 미결이어도 클릭 프레임에 제목+로딩 껍데기가 먼저 선다(#217 R4).
    document.querySelector('#jobTableHead .fico').click();
    var loadingPanel = document.getElementById('jobColPanel');
    out.panel_shell_immediate = !loadingPanel.hidden && loadingPanel.getAttribute('aria-busy') === 'true' &&
      loadingPanel.textContent.indexOf('불러오는 중') >= 0 && loadingPanel.textContent.indexOf('공고명') >= 0;
    loadingPanel.querySelector('[data-act="panel-close"]').click();
    window.Bridge.call = realCall;
    // 열 패널 기본 닫힘 — [hidden] 이 display:flex 를 실제로 이긴다(부록 B-9 overlay/hidden
    // 결함류의 자동 눈검증: .colpanel 은 flex 라 override 가 없으면 hidden 이 은닉에 실패한다).
    out.panel_hidden = getComputedStyle(document.getElementById('jobColPanel')).display === 'none';
    // 드리프트 스냅샷 → 거울 표가 차단 배너 + 행동 링크로 교체되는지(overlay 아닌 실제 교체).
    // 실앱에서 드리프트는 게이트 danger 를 합성하므로 게이트도 danger 로 세운다(재진술 은닉은
    // 게이트 단일 출처를 소비한다 — 리뷰).
    snap.drift = ['유령', '계약조건']; snap.mirror = [];
    snap.gate = {enabled:false, level:'danger', text:'템플릿 구조가 확정 매핑과 달라졌습니다.'};
    window.__push('job', snap);
    out.drift_banner = !!document.querySelector('#jobMirror .mir-drift[role="alert"]');
    out.drift_fix_link = !!document.querySelector('#jobMirror [data-act="fix-mapping"]');
    out.drift_no_table = !document.querySelector('#jobMirror table.mir');
    // danger 차단 중엔 재진술 블록을 숨긴다 — "생성 불가" 배너와 "N건 생성" 모순 방지(리뷰).
    out.restate_hidden_on_drift = getComputedStyle(document.getElementById('jobRestate')).display === 'none';
    // 파일명 토큰 danger(#128) — 드리프트와 **같은 자리·같은 형상**으로 서는지. 거울이 「채움」
    // 표를 그려 건강해 보이고 재진술은 사라지는(신호 없는 차단) 회귀의 핀.
    snap.drift = []; snap.name_tokens = ['납품기한'];
    snap.mirror = [{name:'공고명', state:'filled', acknowledged:false, value:'전산장비', formatted:false}];
    snap.gate = {enabled:false, level:'danger', text:'파일명 패턴의 토큰이…'};
    window.__push('job', snap);
    out.token_banner = !!document.querySelector('#jobMirror .mir-drift[role="alert"]');
    out.token_fix_link = !!document.querySelector('#jobMirror [data-act="fix-filename"]');
    out.token_no_table = !document.querySelector('#jobMirror table.mir');
    out.token_banner_text = (function(){ var b = document.querySelector('#jobMirror .mir-drift');
      return b ? b.textContent : ''; })();
    out.token_restate_hidden = getComputedStyle(document.getElementById('jobRestate')).display === 'none';
    snap.name_tokens = [];
    // 덮어쓰기 확인 본문 합성(수치·이름 배치) 되읽기 — 백엔드 overwrite_text 단언 폐기의 커버리지
    // 짝(리뷰). overwrite_count/new_count 스왑·이름 목록 누락이 여기서 잡힌다.
    out.ow_body = window.JobScreen.overwriteBody(
      {total:10, overwrite_count:3, new_count:7, conflict_names:['a.hwpx','b.hwpx'], conflict_more:5});
    // 세션 가드 재진술 본문 합성(결정 27 수치 재진술) — 되읽어 수치·소실 목록 드리프트를 막는다.
    out.guard_body = window.JobScreen.guardBody(
      {sel_count:3, in_def:2, extra:1, filter_active:true, filter_parts:2}, '작업을 전환하면');
    // 데이터 변경 사전 확인 배선 존재 핀(리뷰 #6) — JS 전용 가드 지점의 삭제 회귀 표식.
    out.data_guard_wired = typeof window.JobScreen.confirmDataSwapIfArmed === 'function';
    // 직전 필터 재적용 버튼(결정 28) — reapply_available 스냅샷이 어포던스를 실제로 켜고 끈다.
    // 양 분기 모두 핀(리뷰 #3): 켜짐만 고정하면 "항상 떠 있는 죽은 버튼" 회귀가 초록으로 샌다.
    out.reapply_shown = getComputedStyle(document.getElementById('jobFilterReapply')).display !== 'none';
    // 버튼이 설치할 정의를 업고 있는가(#127) — "무엇이 설치되는지 말하지 않는 버튼" 회귀 핀.
    out.reapply_title = document.getElementById('jobFilterReapply').title;
    snap.filter.reapply_available = false;
    window.__push('job', snap);
    out.reapply_hidden = getComputedStyle(document.getElementById('jobFilterReapply')).display === 'none';
    snap.filter.reapply_available = true;
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 「작업」 좌 목록 그룹·관리 메뉴(결정 43) — 합성 구획 스냅샷을 실 render() 에 흘려 그룹 헤더·
# 접힘(뷰 제외)·⋮ 메뉴 실개방/바깥닫기·접힘 화살표 가시성(결정 5: 접힌 그룹 상시 노출)·퇴화
# 불변식(그룹 0개=평면)을 실 WebView2 에서 되읽는다(부록 B-9 overlay/hidden 자동 눈검증 동형).
_JOB_LIST_GROUP_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    var snap = {
      job_rows: [{name:'물품 공고서', selected:false},{name:'물품 기안', selected:false},
                 {name:'용역 공고서', selected:false},{name:'회의 기안', selected:false}],
      job_flat: false,
      job_group_names: ['2026 상반기', '입찰'],
      job_sections: [
        {group:'2026 상반기', collapsed:false, count:2,
         rows:[{name:'물품 공고서', selected:false},{name:'물품 기안', selected:false}]},
        {group:'입찰', collapsed:true, count:1, rows:[{name:'용역 공고서', selected:false}]},
        {group:'', collapsed:false, count:1, rows:[{name:'회의 기안', selected:false}]}
      ],
      job_name:'', has_job:false,
      guard:{armed:false, sel_count:0, in_def:0, extra:0, filter_active:false, filter_parts:0},
      out_dir:'', data_label:'', data_source_label:'', data_notice:null,
      gate:{enabled:false, level:'warn', text:'왼쪽에서 작업을 선택하세요.'}
    };
    window.__push('job', snap);
    out.grp_heads = document.querySelectorAll('#jobListHwpx .job-grp-head').length;
    out.rows_visible = document.querySelectorAll(
      '#jobListHwpx > .job-row .job-item, #jobListHwpx .job-grp-rows:not([hidden]) .job-item').length;
    out.grp_more = document.querySelectorAll('#jobListHwpx .grp-more').length;
    out.row_more = document.querySelectorAll(
      '#jobListHwpx > .job-row .job-more[data-more], #jobListHwpx .job-grp-rows:not([hidden]) .job-more[data-more]').length;
    var caretOf = function (expanded) {
      var c = document.querySelector(
        '#jobListHwpx .job-grp-head[aria-expanded="' + expanded + '"] .grp-caret');
      return c ? getComputedStyle(c).visibility : 'missing';
    };
    out.caret_collapsed = caretOf('false');
    out.caret_expanded = caretOf('true');
    // 영속 왕복을 미결로 둬도 접힌 그룹의 aria/caret/body가 클릭 프레임에 먼저 열린다(#217 R3).
    var realCall = window.Bridge.call;
    window.Bridge.call = function () { return new Promise(function () {}); };
    var collapsedHead = document.querySelector('#jobListHwpx .job-grp-head[aria-expanded="false"]');
    collapsedHead.click();
    var openedBody = collapsedHead.closest('.job-grp').nextElementSibling;
    out.collapse_local_flip = collapsedHead.getAttribute('aria-expanded') === 'true' &&
      collapsedHead.querySelector('.grp-caret').textContent === '▾' && !openedBody.hidden;
    window.Bridge.call = realCall;
    // 검색 정산 promise가 이어지는 동안 select_job은 미결로 두되, 클릭 프레임의 여는 중 표지는
    // 즉시 보여야 한다(#217 R1). continuation이 mock을 잡은 뒤 다음 microtask에서 복원한다.
    window.Bridge.call = function () { return new Promise(function () {}); };
    var openingItem = document.querySelector('#jobListHwpx .job-item[data-job]');
    openingItem.click();
    out.opening_marker_immediate = openingItem.getAttribute('aria-busy') === 'true' &&
      openingItem.textContent.indexOf('여는 중') >= 0;
    Promise.resolve().then(function () { window.Bridge.call = realCall; });
    var more = document.querySelector('#jobListHwpx .job-more[data-more]');
    more.click();
    var menu = document.getElementById('jobRowMenu');
    out.menu_shown = getComputedStyle(menu).display !== 'none';
    out.menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    document.body.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true}));
    out.menu_closed = getComputedStyle(menu).display === 'none';
    out.move_modal_hidden = document.getElementById('groupMoveModal').classList.contains('hidden');
    snap.job_flat = true;
    snap.job_group_names = [];
    snap.job_sections = [
      {group:'', collapsed:false, count:1, rows:[{name:'회의 기안', selected:false}]}
    ];
    window.__push('job', snap);
    out.flat_heads = document.querySelectorAll('#jobListHwpx .job-grp-head').length;
    out.flat_rows = document.querySelectorAll('#jobListHwpx .job-item').length;
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 「기안」 좌 목록(#148 슬라이스 2b) — 「작업」과 같은 그룹 구획 스캐폴드 + 공용 grouplist.js
# 팩토리(⋮ 메뉴·이동 다이얼로그)의 **3번째 소비자**를 합성 스냅샷으로 실 render 구동해 되읽는다.
# 골격 메뉴는 편집 미노출(복제·이름변경·이동·삭제)이고, 이동 다이얼로그는 draftMoveModal(별도
# 요소)에 선다 — 화면별 id 격리로 job/tpl 과 리스너 충돌이 없음을 실 WebView 로 확증한다.
_DRAFT_LIST_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('draft');
    var flush = function () { document.body.click(); };  // Popover suppress 교차 오염 청소
    var snap = {
      job_flat: false,
      job_group_names: ['현장 A', '정기'],
      job_sections: [
        {group:'현장 A', collapsed:false, count:2,
         rows:[{name:'착수계 기안', selected:false},{name:'검사요청 기안', selected:false}]},
        {group:'정기', collapsed:true, count:1, rows:[{name:'준공계 기안', selected:false}]},
        {group:'', collapsed:false, count:1, rows:[{name:'회의록 기안', selected:false}]}
      ],
      job_name:'', has_job:false,
      // 세션 조각(#148 슬라이스 3a) — 목록 프로브도 이제 **전체 render** 를 구동하므로
      // 세션 키가 있어야 한다(빈 세션의 정직한 모양). 4존 되읽기는 아래 세션 프로브 몫.
      template_name:'', template_text:'', tokens:[], record_count:0,
      data_label:'', data_source_label:'', data_key:'', has_data:false, selected_count:0,
      target_font:'gulimche',
      filter:{active:false, reapply_available:false, search:'', chips:[], definition:'',
              branches:[], columns:[]},
      table:{columns:[], rows:[], visible_count:0, hidden_selected:[]},
      card:{index:null, has_current:false, is_copied:false, position:null,
            uncopied_count:0, copied_count:0, selected_count:0, is_complete:false,
            advance_after:false, segments:[], missing_fields:[], empty_fields:[],
            index_map:[], lint:{proportional:false, space_run:false, applied:false, active:false},
            last_copy:null}
    };
    window.__push('draft', snap);
    out.grp_heads = document.querySelectorAll('#draftList .job-grp-head').length;   // 현장 A·정기·그룹없음
    // 저장 기안 행만 센다(data-job) — 상시 「이번 세션」 행(.draft-vol, 슬라이스 5a)은 뺀다.
    out.rows_visible = document.querySelectorAll(
      '#draftList > .job-row .job-item[data-job], #draftList .job-grp-rows:not([hidden]) .job-item[data-job]').length;
    out.grp_more = document.querySelectorAll('#draftList .grp-more').length;        // 명명 그룹만
    out.row_more = document.querySelectorAll(
      '#draftList > .job-row .job-more[data-more], #draftList .job-grp-rows:not([hidden]) .job-more[data-more]').length;
    var realCall = window.Bridge.call;
    window.Bridge.call = function () { return new Promise(function () {}); };
    var collapsedHead = document.querySelector('#draftList .job-grp-head[aria-expanded="false"]');
    flush();
    collapsedHead.click();
    var openedBody = collapsedHead.closest('.job-grp').nextElementSibling;
    out.collapse_local_flip = collapsedHead.getAttribute('aria-expanded') === 'true' &&
      collapsedHead.querySelector('.grp-caret').textContent === '▾' && !openedBody.hidden;
    window.Bridge.call = realCall;
    // 미선택 = **휘발 세션**(결정 5) — 4존이 선다. 저장/휘발 한 패널(슬라이스 5a, 껍데기 stub 폐기).
    out.session_shown =
      getComputedStyle(document.getElementById('draftSessionPanel')).display !== 'none';
    // 상시 「이번 세션」 행 = 휘발 귀환구(껍데기 back 버튼 승계). 미결속이라 aria-current.
    out.vol_row_present = !!document.querySelector('#draftList .job-item.draft-vol');
    out.vol_row_current =
      document.querySelector('#draftList .job-item.draft-vol').getAttribute('aria-current') === 'true';
    // 행 ⋮ 메뉴 = [복제, 이름변경, 이동, 삭제] (편집 미노출 — 세션은 슬라이스 3).
    flush();
    document.querySelector('#draftList .job-more[data-more]').click();
    var menu = document.getElementById('draftRowMenu');
    out.menu_shown = getComputedStyle(menu).display !== 'none';
    out.menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    // ⋮ → 이동 → 공용 moveDialog 팩토리(3번째 소비자) 개폐 되읽기 — 라디오 목록·새 그룹 조립.
    document.querySelector('#draftRowMenu button[data-menu="move"]').click();
    out.move_shown = !document.getElementById('draftMoveModal').classList.contains('hidden');
    out.move_opts = document.querySelectorAll('#draftMoveList .grp-opt').length;    // 그룹 2 + 없음 + 새 = 4
    out.move_has_new = !!document.getElementById('draftMoveNewRadio');
    document.getElementById('draftMoveCancel').click();
    (function () {
      var card = document.querySelector('#draftMoveModal .modal-card');
      var ev = new Event('transitionend', {bubbles:true});
      Object.defineProperty(ev, 'propertyName', {value:'opacity'});
      card.dispatchEvent(ev);
    })();
    out.move_closed = document.getElementById('draftMoveModal').classList.contains('hidden');
    // 퇴화 평면(그룹 0개) — 헤더 없는 나열.
    snap.job_flat = true;
    snap.job_group_names = [];
    snap.job_sections = [{group:'', collapsed:false, count:1, rows:[{name:'회의록 기안', selected:false}]}];
    window.__push('draft', snap);
    out.flat_heads = document.querySelectorAll('#draftList .job-grp-head').length;
    out.flat_rows = document.querySelectorAll('#draftList .job-item[data-job]').length;  // 이번 세션 행 제외
    out.error = null;
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 「작업」 패널 두 모드(에디터 흡수, 블록 2 개정 결정 39~41) — 편집 호스트/세션 4존의 배타
# 표시와 신규=단계(번호 표지)·편집=탭(자유 이동 버튼) 이원 표현을 실 render 로 되읽는다
# (부록 B-9 overlay/hidden 눈검증의 자동판 — 이사한 DOM 이 실 WebView2 에서 실제로 선다).
_JOB_EDITMODE_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    window.JobScreen.showEditMode();
    out.edit_host_shown = getComputedStyle(document.getElementById('jobEditHost')).display !== 'none';
    out.zones_hidden = getComputedStyle(document.getElementById('jobZones')).display === 'none';
    out.status_text = document.getElementById('jobStatus').textContent;
    var draft = {step:0, reachable:[false,false], template_path:'', template_name:'',
      field_count:0, fields:[], raw_block:'', gate_error:false, gate:null, notice:null,
      editing_origin:''};
    window.__push('editor', draft);
    out.wizard_steps = document.querySelectorAll('#editor-steps .wstep-tab .k').length;
    out.foot_shown_new = getComputedStyle(document.getElementById('editor-foot')).display !== 'none';
    draft.editing_origin = '공고서';
    window.__push('editor', draft);
    out.edit_tabs = document.querySelectorAll('#editor-steps button.wstep-tab.as-tab').length;
    out.foot_hidden_edit = getComputedStyle(document.getElementById('editor-foot')).display === 'none';
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 매핑 분류 칩-라이브(블록 2 결정 12·13, 슬라이스 5 PR-3) — 합성 매핑 스냅샷을 __push 로 실
# render() 에 흘려 (a) 사용할 헤더가 **즉시 토글 칩**(체크박스 스테이징 소거)으로, (b) 미사용
# 구역이 펼쳐지고(ignored_expanded), (c) 소유권 태그 4종(확정·수동·제안·후보 없음)이,
# (d) touched 행에 '자동 제안으로 되돌리기'(↩)가 실 WebView2 에서 그려지는지 되읽는다.
# 정의 surface 는 흡수(결정 39)로 「작업」 패널 편집 호스트에 산다 — 루트도 #jobEditHost.
_EDITOR_CHIP_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    var row = function (i, f, src, conf, touch, hascontent) {
      return {index:i, template_field:f, inferred_type:"text", context:"", source:src,
        type:"text", const:"", fmt:"", confirmed:conf, touched:touch, has_content:hascontent,
        suggestion_score:src?1:0, preview:src?"값":"", preview_empty:false, preview_error:false,
        row_state: conf?"confirmed":(hascontent?"unconfirmed":"unmatched")};
    };
    var snap = {
      step:1, notice:null, reachable:[true,false],
      template_path:"C:/t/공고서.hwpx", template_name:"공고서.hwpx", field_count:4,
      schema_summary:"", fields:[], raw_block:"", gate:null, gate_error:false,
      data_path:"C:/d/대장.xlsx", data_name:"대장.xlsx", data_sheet:"물품", record_count:3,
      source_fields:["품명","세부품명","수량","비고"],
      active_source_fields:["품명","수량","비고"], ignored_source_fields:["세부품명"],
      active_count:3, ignored_count:1, ignored_expanded:true,
      sample_rows:[["A","a","3","-"],["B","b","6","x"],["C","c","1","-"]],
      type_options:["text","date","amount","const"],
      fmt_options:{text:[],date:[],amount:[],const:[]},
      name:"", pattern:"x", has_unsaved_work:true, editing_origin:"", dataset_name:"대장",
      provenance:null, default_dataset:null,
      rows:[row(0,"품명","품명",true,true,true),     // 확정
            row(1,"수량","수량",false,true,true),     // 수동(touched 미확정)
            row(2,"규격","비고",false,false,true),    // 제안(시스템 소유)
            row(3,"담당자","",false,false,false)],    // 후보 없음
      counts:{filled:3,empty:0,unmapped:1}, preview_empties:[], preview_index:1, preview_count:3,
      is_complete:false, schema_only:false
    };
    window.Nav.go('job');
    window.JobScreen.showEditMode();
    window.__push('editor', snap);
    var root = document.getElementById('jobEditHost');
    out.active_chips = root.querySelectorAll('.hchip.on[data-act="toggle-header"]').length;
    out.has_checkbox_staging = !!root.querySelector('.hbx');  // 스테이징 소거 → false 여야
    out.ignored_chip = !!root.querySelector('.hchip.ign[data-act="toggle-header"]');
    out.ignored_fold_open = !!root.querySelector('details.hidden-hdrs[open]');
    out.use_none_btn = !!root.querySelector('[data-act="use-none"]');
    out.tags = Array.from(root.querySelectorAll('table.map .tag')).map(function (t) {
      return t.textContent.trim();
    });
    out.auto_revert_option = !!root.querySelector('table.map [data-act="revert-source"]');
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
  return out;
})()
"""

# 「기안」 휘발 세션 4존(#148 슬라이스 3a) — 공용 팩토리(draftsession.js)의 **두 번째 소비
# 인스턴스**를 draft 화면에서 실 render 구동해 되읽는다. 같은 팩토리라도 id 맵이 어긋나면
# 이 화면에서만 조용히 죽으므로(getElementById 는 화면 은닉과 무관하게 해소된다 — poolList
# 전례) 존별로 하나씩 확인한다: ①데이터 존 테이블·스트립 ②필드 상태 ③카드 렌더·점·글꼴·린트
# ④복사 동사·전진. **미루기 버튼 부재**(결정 10 사망 — 새 표면에 짓지 않는다)도 함께 못박는다.
_DRAFT_SESSION_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('draft');
    var snap = {
      job_flat:true, job_group_names:[], job_sections:[], job_rows:[],
      job_name:'', has_job:false,
      template_name:'착수계',
      template_text:'제목: {{공고명}} 담당: {{담당자}} 비고: {{비고}} 수량: {{수량}}',
      // 맞추기 표(#148 슬라이스 3b) — 결속(auto)·결속 빈값(blank)·무결속+근사 제안(원클릭·값
      // 직접 입력)·**결속 값 고쳐 상수 강등(man, 소스 기억)**. 소유권 색 점.
      tokens:[
        // 유형·확정 열(#148 슬라이스 4) — auto 행만 유형 셀렉트가 뜨고(공고명·담당자), 확정
        // 체크박스는 전 행. blank_declared 는 확정-비움 표지(판정은 서버 is_empty_confirmed).
        {name:'공고명', state:'fill', source:'공고명', own:'auto', manual:false,
         value:'전산장비 구매', fmt_kind:'text', fmt_code:'', suggest:'', can_revert:false,
         confirmed:true, blank_declared:false},
        {name:'담당자', state:'blank', source:'담당열', own:'auto', manual:false,
         value:'', fmt_kind:'amount', fmt_code:'', suggest:'', can_revert:false,
         confirmed:true, blank_declared:false},
        {name:'비고', state:'missing', source:'', own:'', manual:false,
         value:'', fmt_kind:'text', fmt_code:'', suggest:'비고열', can_revert:false,
         confirmed:false, blank_declared:false},
        // 상수(man)인데 결속 소스를 기억 — 드롭다운은 열이 아니라 「(직접 입력)」이어야 한다
        // (Codex F1: t.source 로 selected 판정하면 옛 열이 이겨 결속된 듯 거짓 표시).
        {name:'수량', state:'fill', source:'공고명', own:'man', manual:true,
         value:'99', fmt_kind:'text', fmt_code:'', suggest:'', can_revert:true,
         confirmed:true, blank_declared:false}
      ],
      columns:['공고명','담당열','비고열'], fmt_options:{text:[], amount:[], date:[]},
      type_options:[{code:'text',label:'텍스트'},{code:'date',label:'날짜'},{code:'amount',label:'금액'}],
      record_count:2,
      data_label:'d.csv', data_source_label:'파일: d.csv', data_key:'file:c:/d/d.csv',
      has_data:true, selected_count:2, target_font:'malgun',
      filter:{active:true, reapply_available:false, search:'전산',
              chips:['(공고명) 포함 「전산」'], definition:'(공고명) 포함 「전산」',
              branches:['공고명'], columns:[{name:'공고명', kind:'text', active:false}]},
      table:{columns:['공고명'],
             rows:[{index:0, selected:true, qpos:1, copied:false, current:true,
                    cells:[[['전산',true],['장비 구매',false]]]}],
             visible_count:1,
             hidden_selected:[{index:1, selected:true, qpos:2, copied:false, current:false}]},
      card:{index:0, has_current:true, queue_degenerate:false, is_copied:false, position:1,
            uncopied_count:2, copied_count:0, selected_count:2, is_complete:false,
            advance_after:false,
            segments:[{text:'제목: ', kind:'literal', name:''},
                      {text:'전산장비 구매', kind:'fill', name:'공고명'},
                      {text:' 담당: ', kind:'literal', name:''},
                      {text:'', kind:'blank', name:'담당자'},
                      {text:' 비고: ', kind:'literal', name:''},
                      {text:'{{비고}}', kind:'missing', name:'비고'},
                      {text:' 수량: ', kind:'literal', name:''},
                      {text:'99', kind:'fill', name:'수량'}],
            missing_fields:['비고'], empty_fields:['담당자'],
            index_map:[{index:0, state:'current', has_gap:false},
                       {index:1, state:'uncopied', has_gap:true}],
            lint:{proportional:true, space_run:true, applied:false, active:true},
            last_copy:null}
    };
    window.__push('draft', snap);
    // 마일스톤 L #270 — 새 기본창에서 duo·sticky가 성립하고 평시 자동결속 8토큰은 300px 캡을
    // 발동하지 않는다. 22토큰 스트레스는 실제 scrollHeight 판정으로 capstrip을 세워야 한다.
    var calm = JSON.parse(JSON.stringify(snap));
    calm.tokens = [];
    for (var ci = 0; ci < 8; ci++) {
      calm.tokens.push({name:'기본' + ci, state:'fill', source:'공고명', own:'auto', manual:false,
        value:'값 ' + ci, fmt_kind:'text', fmt_code:'', suggest:'', can_revert:false,
        confirmed:true, blank_declared:false});
    }
    window.__push('draft', calm);
    out.density_wide_columns = getComputedStyle(document.getElementById('draftDuo')).gridTemplateColumns;
    out.density_preview_position = getComputedStyle(
      document.querySelector('#draftDuo .draft-preview-zone')).position;
    out.density_cap_height = getComputedStyle(document.getElementById('draftTokPanel')).maxHeight;
    out.density_default_client_height = document.getElementById('draftTokPanel').clientHeight;
    out.density_default_scroll_height = document.getElementById('draftTokPanel').scrollHeight;
    out.density_default_cap_hidden =
      getComputedStyle(document.getElementById('draftMapCapstrip')).display === 'none';
    var stress = JSON.parse(JSON.stringify(calm));
    stress.tokens = [];
    for (var di = 0; di < 22; di++) {
      stress.tokens.push({name:'스트레스' + di, state:'fill', source:'공고명', own:'auto', manual:false,
        value:'값 ' + di, fmt_kind:'text', fmt_code:'', suggest:'', can_revert:false,
        confirmed:true, blank_declared:false});
    }
    window.__push('draft', stress);
    out.density_stress_cap_shown =
      getComputedStyle(document.getElementById('draftMapCapstrip')).display !== 'none';
    out.density_stress_cap_text = document.getElementById('draftMapCapstrip').textContent;
    window.__push('draft', snap);  // 아래 기존 계약은 4토큰 정본으로 계속 검증
    // ① 데이터 존 — 두 번째 인스턴스가 draft id 로 섰는가(가시 행·하이라이트·관통 스트립).
    out.rows = document.querySelectorAll('#draftTableBody tr[data-i]').length;
    out.mark = (function(){ var m = document.querySelector('#draftTableBody mark');
      return m ? m.textContent : ''; })();
    out.strip_shown = getComputedStyle(document.getElementById('draftSelStrip')).display !== 'none';
    out.chips_text = document.getElementById('draftFilterChips').textContent;
    // 데이터 해제 버튼(R-flow 결정 30, 리뷰 F — 구 「빠른 기안」 승계) — 데이터가 물렸을 때만 뜬다
    // (has_data:true 인 이 스냅샷 = 노출). 무데이터 숨김은 아래 퇴화 섹션(clear_hidden)이 못박는다.
    out.clear_shown = document.getElementById('draftBtnClearData').hidden === false;
    // ② 맞추기 표(#148 슬라이스 3b) — 토큰 행·소유권 색 점·근사 제안 버튼·값 입력(항상 편집 가능,
    //   결속이면 데이터 값이 차 있고 고치면 상수 강등). 판정은 서버, 여긴 렌더 되읽기.
    out.map_rows = document.querySelectorAll('#draftTokPanel table.dmap tbody tr').length;
    out.map_own_auto = document.querySelectorAll('#draftTokPanel .own.auto').length;  // 공고명·담당자
    out.map_val_inputs = document.querySelectorAll('#draftTokPanel .mapval-in').length;  // 전 행 편집 가능
    // 결속(auto) 값 입력엔 현재 행의 데이터 값이 미리 차 있다(이음매가 값 사전을 낳는다).
    out.map_bound_value = (function(){
      var vs = document.querySelectorAll('#draftTokPanel .mapval-in');
      for (var k = 0; k < vs.length; k++) if (vs[k].value.indexOf('전산장비 구매') >= 0) return true;
      return false; })();
    out.map_suggest = !!document.querySelector('#draftTokPanel .mapsug');             // 비고 근사 제안
    out.map_src_options = (function(){ var s = document.querySelector('#draftTokPanel .mapsrc-sel');
      return s ? s.options.length : 0; })();  // (직접 입력)+열 3 = 4
    // man(상수)인데 소스를 기억한 자리(수량, i=3)의 드롭다운은 열이 아니라 「(직접 입력)」이어야
    // 한다(Codex F1 — 옛 열 selected 로 결속된 듯 거짓 표시 차단). 유효 선택 = 빈 값.
    out.map_man_src_value = (function(){ var s = document.getElementById('draftTokPanel-src-3');
      return s ? s.value : 'ABSENT'; })();
    // 유형·확정 열(#148 슬라이스 4) — 유형 셀렉트는 auto 행에만(공고명·담당자=2), 확정 체크박스는
    //   전 행(4). 유형 셀렉트의 유효 선택 = 서버 fmt_kind(담당자 amount). 확정 체크 되읽기.
    out.map_type_selects = document.querySelectorAll('#draftTokPanel .maptype').length;  // auto 2
    out.map_type_value = (function(){ var s = document.getElementById('draftTokPanel-type-1');
      return s ? s.value : 'ABSENT'; })();  // 담당자(i=1) = amount
    out.map_type_options = (function(){ var s = document.querySelector('#draftTokPanel .maptype');
      return s ? s.options.length : 0; })();  // 텍스트·날짜·금액 = 3
    out.map_confirmed_checks = document.querySelectorAll('#draftTokPanel .mapck').length;  // 전 행 4
    out.map_confirmed_checked = (function(){ var c = document.getElementById('draftTokPanel-ck-0');
      return !!c && c.checked; })();          // 공고명(i=0) = 확정
    out.map_unconfirmed = (function(){ var c = document.getElementById('draftTokPanel-ck-2');
      return !!c && !c.checked; })();         // 비고(i=2) = 미확정
    // 확정-비움(#148 슬라이스 4, 결정 12) — 비고를 확정+무내용으로 밀면 값 셀이 「비워둠(선언)」
    //   (「아직 안 씀」 아님)이고 행이 blank 로 표지된다. 게이트 제외는 Python 판정이라(pytest)
    //   여기선 표면 되읽기만. 격리 push 후 원상 복귀(뒤 되읽기 오염 방지).
    var bsnap = JSON.parse(JSON.stringify(snap));
    bsnap.tokens[2].confirmed = true; bsnap.tokens[2].blank_declared = true; bsnap.tokens[2].suggest = '';
    window.__push('draft', bsnap);
    out.blank_declared_marker = (function(){
      var tr = document.querySelectorAll('#draftTokPanel table.dmap tbody tr')[2];
      var m = tr && tr.querySelector('.mapval-declared');
      return m ? m.textContent : (tr ? '' : 'ABSENT'); })();
    out.blank_declared_no_textarea = (function(){
      var tr = document.querySelectorAll('#draftTokPanel table.dmap tbody tr')[2];
      return !!tr && !tr.querySelector('.mapval-in'); })();
    out.blank_declared_row = (function(){
      var tr = document.querySelectorAll('#draftTokPanel table.dmap tbody tr')[2];
      return !!tr && tr.classList.contains('row-blank-declared'); })();
    window.__push('draft', snap);  // 원상 복귀(비확정-비움) — 뒤 되읽기 오염 방지
    // ③ 원문 뷰 전환(결정 34) — 기본 채운 모습, 「원문」 클릭 시 배타 전환 + textarea 에 원문.
    out.view_default_filled =
      document.getElementById('draftViewFilled').getAttribute('aria-pressed') === 'true'
      && document.getElementById('draftSrcView').hidden === true;
    document.getElementById('draftViewSource').click();
    out.view_source_shown = document.getElementById('draftSrcView').hidden === false
      && document.getElementById('draftCardRender').hidden === true;
    out.src_has_text = (document.getElementById('draftSrcBox').value || '').indexOf('{{공고명}}') >= 0;
    document.getElementById('draftViewFilled').click();  // 원상 복귀(뒤 되읽기 오염 방지)
    // ③ 미리보기 — 채움 표지 삼분 + 상태 색인 점 + 선언 글꼴 추종 + 정렬 린트.
    out.card_render = document.getElementById('draftCardRender').textContent;
    out.card_fill = !!document.querySelector('#draftCardRender .seg-fill');
    out.card_blank = !!document.querySelector('#draftCardRender .seg-blank');
    out.card_dots = document.querySelectorAll('#draftCardDots .wc-dot').length;
    out.card_gap_dot = !!document.querySelector('#draftCardDots .wc-dot.gap');
    out.card_readout = document.getElementById('draftCardReadout').textContent;
    out.font_sel = document.getElementById('draftTargetFont').value;
    out.font_class = document.getElementById('draftCardRender').className;
    out.lint_shown = !document.getElementById('draftCardLint').hidden;
    out.lint_fix = (function(){ var b = document.getElementById('draftLintAction');
      return b ? b.dataset.act : ''; })();
    // ④ 완료 — 복사 동사 활성 + 자유 이동(◀▶) + 전진 토글. 미루기는 없다(결정 10 사망).
    var cp = document.getElementById('draftCardCopy');
    out.copy_enabled = !!cp && !cp.disabled;
    out.prev_disabled = document.getElementById('draftCardPrev').disabled;  // 첫 카드 = 경계 잠금
    out.next_enabled = !document.getElementById('draftCardNext').disabled;
    out.defer_absent = !document.getElementById('draftCardDefer');
    // 「템플릿으로 저장」(#148 슬라이스 6, #135) — 구 「빠른 기안」에서 흡수한 두 번째 승격 동사.
    // 휘발 세션 + 원문 있으면 뜨고(can_save_template), 플래그가 거짓이면(저장 결속·빈손) 숨는다
    // (사용자 결정 · dead button 금지 — hidden 으로 가른다). 판정은 Python, 여긴 렌더 되읽기.
    // 격리 push 후 원상 복귀(뒤 되읽기 오염 방지).
    var tsnap = JSON.parse(JSON.stringify(snap));
    tsnap.can_save_template = true;
    window.__push('draft', tsnap);
    out.savetpl_shown = document.getElementById('draftSaveTpl').hidden === false;
    tsnap.can_save_template = false;
    window.__push('draft', tsnap);
    out.savetpl_hidden = document.getElementById('draftSaveTpl').hidden === true;
    window.__push('draft', snap);  // 원상 복귀
    // (구 txt 화면 DOM 누출 검사는 슬라이스 6 에서 소멸 — 두 번째 인스턴스였던 txt 화면이
    // 삭제돼 #txtCardRender 자체가 없다. datazone 팩토리 격리는 test_web_datazone 정적 가드.)
    // 큐 퇴화(결정 8·14) — 유효 큐 ≤ 1건(단건·무데이터 가상 1건)이면 큐 장치 3종(진행 색인·
    // ◀▶ 다음 카드·자동 전진)이 **숨는다**. 무데이터 가상 카드는 작업점(index) None 이되
    // 복사 가능하고, 맞추기 표 값 열 머리가 「지금 행의 값」→「값」으로 바뀐다. 실 render() 로
    // 숨김·활성·머리글을 되읽는다(판정은 Python queue_degenerate, JS 는 표현만).
    var vsnap = JSON.parse(JSON.stringify(snap));
    vsnap.has_data = false;
    vsnap.columns = [];  // 무데이터 = 결속 후보 없음 → 「데이터 열」 드롭다운은 「직접 입력」만
    vsnap.card.queue_degenerate = true;
    vsnap.card.has_current = true;
    vsnap.card.index = null;
    window.__push('draft', vsnap);
    // 데이터 해제 버튼은 무데이터(has_data:false)에선 숨는다(dead control 금지, 리뷰 F).
    out.clear_hidden = document.getElementById('draftBtnClearData').hidden === true;
    // 무결속 토큰(비고, i=2)으로 무데이터 열 누출을 본다 — (직접 입력)만 = 1. 결속 토큰(공고명)은
    // 이제 결속 소스를 선택지에 보이므로(리뷰 5a P2) 누출 검사 대상이 아니다(첫 셀 = 공고명 결속).
    out.degen_src_options = (function(){ var s = document.getElementById('draftTokPanel-src-2');
      return s ? s.options.length : 0; })();  // 비고=무결속·무데이터 → (직접 입력)만 = 1(열 누출 없음)
    // **실제 표시(computed display)** 로 되읽는다 — `hidden` 속성만 보면 display:flex 가 UA
    // [hidden]{display:none} 을 이겨도(부록 B-9) 속성은 true 라 거짓 초록이 난다(Codex P2 실측).
    var gone = function(el){ return !!el && getComputedStyle(el).display === 'none'; };
    out.degen_dots_hidden = gone(document.getElementById('draftCardDots'));
    out.degen_prev_hidden = gone(document.getElementById('draftCardPrev'));
    out.degen_next_hidden = gone(document.getElementById('draftCardNext'));
    out.degen_advance_hidden = (function(){ var a = document.getElementById('draftAdvance');
      return gone(a && a.closest('.wc-advance')); })();
    out.degen_copy_enabled = !document.getElementById('draftCardCopy').disabled;
    // 값 열 머리 — 슬라이스 4 에서 확정 열이 뒤에 붙어 값 열은 더 이상 마지막이 아니다
    // (열: 토큰0·데이터열1·유형2·표시형3·값4·확정5). 값 열(index 4)을 명시로 읽는다.
    out.degen_val_head = (function(){
      var th = document.querySelectorAll('#draftTokPanel table.dmap thead th');
      return th.length > 4 ? th[4].textContent : ''; })();
    window.__push('draft', snap);  // 원상 복귀(비퇴화) — 뒤 되읽기 오염 방지
    out.nondegen_dots_shown =
      getComputedStyle(document.getElementById('draftCardDots')).display !== 'none';
    // 유래별 열 게이팅(#148 슬라이스 5a, 결정 7) — 휘발 모드(base snap: mode 미지정)에선 유형·확정
    // (.persist) 열이 숨고, 저장 모드에선 뜬다. **실 display 로 되읽는다**(부록 B-9: display:flex 가
    //   UA [hidden]{display:none} 을 이겨 속성만 보면 거짓 초록). 판정은 CSS([data-mode]), JS 는 표지만.
    var shownEl = function(el){ return !!el && getComputedStyle(el).display !== 'none'; };
    out.persist_hidden_volatile = !shownEl(document.querySelector('#draftTokPanel .maptype-cell'));
    out.volatile_note_shown = !!document.querySelector('#draftMapLegend .volatile-note');
    // 저장 기안 선택 → 세션이 그 Job 에서 복원(저장 모드): 세션 패널은 **그대로 서고**(껍데기 없음),
    // 유형·확정 열이 뜨고, 원문은 읽기 전용, 휘발 note 는 사라진다. 두 세션 병존이라 「이번 세션」
    // 행은 비결속(aria-current false)으로 남는다 — 그 행 클릭이 곧 선택 해제(휘발 귀환).
    var ssnap = JSON.parse(JSON.stringify(snap));
    ssnap.job_name = '착수계 기안'; ssnap.has_job = true;
    ssnap.mode = 'saved'; ssnap.source_readonly = true; ssnap.bound_job = '착수계 기안';
    window.__push('draft', ssnap);
    out.saved_session_shown = shownEl(document.getElementById('draftSessionPanel'));
    out.saved_persist_shown = shownEl(document.querySelector('#draftTokPanel .maptype-cell'));
    out.saved_src_readonly = document.getElementById('draftSrcBox').readOnly === true;
    out.saved_note_absent = !document.querySelector('#draftMapLegend .volatile-note');
    out.vol_row_current_saved = (function () {
      var v = document.querySelector('#draftList .job-item.draft-vol');
      return !!v && v.getAttribute('aria-current') === 'false'; })();
    // 저장 모드는 **원문 정의 진입점 전부 잠금**(리뷰 5a P1) — 콤보·붙여넣기도(textarea 뿐 아님).
    // 안 잠그면 저장 레시피가 조용히 다른 원문으로 바뀐다(계약 거짓말). 데이터 컨트롤은 안 잠근다.
    // ssnap(저장) 상태에서 먼저 읽는다 — 아래 5b 포크 블록이 fsnap(휘발)으로 밀기 전에.
    out.saved_tpl_locked = document.getElementById('draftTplSel').disabled === true
      && document.getElementById('draftBtnPaste').disabled === true;
    out.saved_data_unlocked = document.getElementById('draftBtnPickData').disabled === false;
    // 원문바(#148 슬라이스 5b) — 저장 모드: 「사본으로 편집」 뜨고 수정됨 표지는 없다(깨끗한
    // 정의). 원문 뷰로 들어가 **실 display** 로 되읽는다(부록 B-9 — 숨은 조상 밖에서 봐야 참).
    document.getElementById('draftViewSource').click();
    out.saved_fork_shown = shownEl(document.getElementById('draftSrcFork'));
    out.saved_modbadge_hidden = !shownEl(document.getElementById('draftModBadge'));
    out.saved_srcname = document.getElementById('draftSrcName').textContent;
    // 사본으로 편집(포크) 표현 — 휘발+수정됨: 「사본으로 편집」 숨고(이미 편집 가능), 수정됨 표지
    // 뜨고, 원문 textarea 편집 가능. 포크 판정은 Python(_do_fork_to_volatile), 여긴 표현 되읽기.
    var fsnap = JSON.parse(JSON.stringify(ssnap));
    fsnap.mode = 'volatile'; fsnap.source_readonly = false; fsnap.source_dirty = true;
    fsnap.has_job = false; fsnap.bound_job = '';
    window.__push('draft', fsnap);
    out.fork_fork_hidden = !shownEl(document.getElementById('draftSrcFork'));
    out.fork_modbadge_shown = shownEl(document.getElementById('draftModBadge'));
    out.fork_src_editable = document.getElementById('draftSrcBox').readOnly === false;
    document.getElementById('draftViewFilled').click();  // 원상 복귀(뒤 되읽기 오염 방지)
    // 선택 해제(휘발 귀환) → 세션 패널은 계속 서고 유형·확정 열이 다시 숨는다(휘발 모드).
    window.__push('draft', snap);  // mode 미지정 = 휘발
    out.back_restores_session = shownEl(document.getElementById('draftSessionPanel'));
    out.back_persist_hidden = !shownEl(document.querySelector('#draftTokPanel .maptype-cell'));
    out.vol_tpl_unlocked = document.getElementById('draftTplSel').disabled === false
      && document.getElementById('draftBtnPaste').disabled === false;
    // 복원 결속 정직 표시(리뷰 5a P2) — 데이터 미연결(columns 빈)이어도 결속된 열이 드롭다운
    // 선택지에 있고 selected 여야 한다(「(직접 입력)」 오표시 = 저장 매핑 거짓 표시 차단).
    var rsnap = JSON.parse(JSON.stringify(snap));
    rsnap.has_data = false; rsnap.columns = [];
    rsnap.tokens = [{name:'공고명', state:'blank', source:'복원열', own:'auto', manual:false,
      value:'', fmt_kind:'text', fmt_code:'', suggest:'', can_revert:false,
      confirmed:true, blank_declared:false}];
    window.__push('draft', rsnap);
    out.restored_bind_option = (function () {
      var s = document.querySelector('#draftTokPanel .mapsrc-sel');
      if (!s) return 'ABSENT';
      for (var k = 0; k < s.options.length; k++) {
        if (s.options[k].value === '복원열') return s.value === '복원열' ? 'selected' : 'present';
      }
      return 'MISSING'; })();
    window.__push('draft', snap);  // 원상 복귀
    // 「기안으로 저장」 승격 버튼(#148 슬라이스 5c, #135) — 라이브러리 배접(can_save_job)만 활성.
    // 붙여넣기·수정 원문은 비활성 + 사유(dead button 금지, #133). base snap 은 can_save_job
    // 미지정 = 비활성. 라벨은 유래로 갈린다(휘발=「기안으로 저장」·저장=「다른 이름으로 저장」).
    out.save_disabled_unbacked = document.getElementById('draftSaveJob').disabled === true;
    out.save_note_shown = !document.getElementById('draftSaveJobNote').hidden;
    var svsnap = JSON.parse(JSON.stringify(snap));
    svsnap.can_save_job = true;
    window.__push('draft', svsnap);
    out.save_enabled_backed = document.getElementById('draftSaveJob').disabled === false;
    out.save_note_hidden = document.getElementById('draftSaveJobNote').hidden === true;
    out.save_label_volatile = document.getElementById('draftSaveJob').textContent;
    svsnap.has_job = true; svsnap.mode = 'saved'; svsnap.bound_job = '착수계 기안';
    window.__push('draft', svsnap);
    out.save_label_saved = document.getElementById('draftSaveJob').textContent;
    window.__push('draft', snap);  // 원상 복귀(휘발) — 뒤 되읽기 오염 방지
    // 세션 교체 가드 문안(리뷰 F6) — leave_guard 가 **미저장 매핑 편집만**으로 무장한 경우(데이터·
    // 큐 0), 새 기안 가드는 그 편집을 열거해야 "사라지는 것: ."(빈 목록)이 되지 않는다. 같은 guardBody
    // 를 데이터 스왑(includeRecipe=false)으로 부르면 매핑 편집은 빠져야 한다(스왑은 유지 — over-warn
    // 차단). 순수 합성기라 DOM 무관, 두 갈래를 되읽어 문안≠집합 결함류를 못박는다.
    var gbG = {map_dirty:true, source_dirty:false, sel_count:0, queue_partial:false, filter_parts:0};
    out.guard_body_new_draft = window.DraftScreen.guardBody(gbG, '새 기안을 시작하면', true);
    out.guard_body_data_swap = window.DraftScreen.guardBody(gbG, '다른 데이터를 겨누면', false);
    out.error = null;
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 템플릿 관리(#108) — 매체 구획 + 그 안 그룹 구획이 실 WebView2 에서 서는지 되읽는다(job 목록
# 그룹 프로브 동형). 그룹 헤더·카드·⋮ 메뉴(그룹 있는 카드=이동+삭제 / 그룹 헤더=개명+해산)·
# ＋그룹지정 칩(「그룹 없음」에만)·접힘 캐럿 가시성·이동 다이얼로그 개폐를 확인 — 부록 B-9 눈검증의
# 자동판(이식한 그룹 UI 가 실제로 렌더되는가).
_TPL_LIST_GROUP_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('tpl');
    var C = function (key, group, name, badge) {
      return {key:key, group:group, name:name, path:'C:/lib/' + name, state:'compiled',
              badge_label:badge, badge_level:'ok', detail:'필드 3개', is_error:false,
              actions:[{key:'make_job', label:'새 작업'}]};
    };
    var snap = {
      hwpx: {
        count:4, flat:false, group_names:['계약','입찰'], dir:'C:/lib', empty_hint:'',
        sections:[
          {group:'입찰', collapsed:false, count:2,
           items:[C('a.hwpx','입찰','a.hwpx','누름틀'), C('b.hwpx','입찰','b.hwpx','누름틀')]},
          {group:'계약', collapsed:true, count:1, items:[C('c.hwpx','계약','c.hwpx','누름틀')]},
          {group:'', collapsed:false, count:1, items:[C('d.hwpx','','d.hwpx','누름틀')]}
        ]
      },
      txt: {count:0, flat:true, group_names:[], dir:'C:/txt', sections:[]},
      result:{text:'', level:'muted'}
    };
    window.__push('tpl', snap);
    var host = document.getElementById('tplHwpxGroups');
    out.grp_heads = host.querySelectorAll('.job-grp-head').length;          // 입찰·계약·그룹없음
    out.cards_visible = host.querySelectorAll('.tpl-grp-rows:not([hidden]) .tplcard').length; // 계약 접힘 → 2+1
    out.grp_more = host.querySelectorAll('.grp-more').length;               // 명명 그룹만(그룹없음 제외)
    out.card_more = host.querySelectorAll('.tpl-grp-rows:not([hidden]) .tplcard-more').length;
    out.assign_chips = host.querySelectorAll('.tpl-grp-rows:not([hidden]) .tpl-assign').length; // 「그룹 없음」 카드만
    var caretOf = function (expanded) {
      var c = host.querySelector('.job-grp-head[aria-expanded="' + expanded + '"] .grp-caret');
      return c ? getComputedStyle(c).visibility : 'missing';
    };
    out.caret_collapsed = caretOf('false');   // 접힌 그룹 캐럿 상시 노출
    out.caret_expanded = caretOf('true');      // 펼친 그룹 캐럿 호버 전 숨김
    var realCall = window.Bridge.call;
    window.Bridge.call = function () { return new Promise(function () {}); };
    var collapsedHead = host.querySelector('.job-grp-head[aria-expanded="false"]');
    document.body.click();
    collapsedHead.click();
    var openedBody = collapsedHead.closest('.job-grp').nextElementSibling;
    out.collapse_local_flip = collapsedHead.getAttribute('aria-expanded') === 'true' &&
      collapsedHead.querySelector('.grp-caret').textContent === '▾' && !openedBody.hidden;
    window.Bridge.call = realCall;
    // 앞선 프로브가 Popover 바깥-닫기 pointerdown 을 남기면 그 인스턴스의 "다음 click 1회 소비"
    // 플래그가 상주해 우리 첫 click 을 캡처 단계에서 먹는다(교차 프로브 오염). 던짐 click 으로
    // 미리 소비해 상태를 청소한다(메뉴 개폐 사이마다도 동일 — 우리 close pointerdown 자기 소비).
    var flush = function () { document.body.click(); };
    // 그룹에 속한 카드 ⋮ = [이동, 삭제].
    flush();
    host.querySelector('.tplcard-more').click();
    var menu = document.getElementById('tplRowMenu');
    out.menu_shown = getComputedStyle(menu).display !== 'none';
    out.card_menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    document.body.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true}));
    out.menu_closed = getComputedStyle(menu).display === 'none';
    // 그룹 헤더 ⋮ = [개명, 해산].
    flush();
    host.querySelector('.grp-more').click();
    out.group_menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    document.body.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true}));
    // ＋그룹지정 칩 → 이동 다이얼로그.
    out.move_hidden_before = document.getElementById('tplMoveModal').classList.contains('hidden');
    flush();
    host.querySelector('.tpl-assign').click();
    out.move_shown_after_chip = !document.getElementById('tplMoveModal').classList.contains('hidden');
    window.Modal.close('tplMoveModal');
    (function () {
      var card = document.querySelector('#tplMoveModal .modal-card');
      var ev = new Event('transitionend', {bubbles:true});
      Object.defineProperty(ev, 'propertyName', {value:'opacity'});
      card.dispatchEvent(ev);
    })();
    // 퇴화 평면(그룹 0개) — 헤더 없는 카드 나열.
    snap.hwpx.flat = true;
    snap.hwpx.group_names = [];
    snap.hwpx.sections = [{group:'', collapsed:false, count:1, items:[C('d.hwpx','','d.hwpx','누름틀')]}];
    window.__push('tpl', snap);
    out.flat_heads = host.querySelectorAll('.job-grp-head').length;
    out.flat_cards = host.querySelectorAll('.tplcard').length;
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
  return out;
})()
"""


# 에디터 1단계 피커(#108 슬라이스 3) — 라이브러리를 관리 화면과 **같은 그룹 구획**(선택 전용)으로
# 실 WebView2 에 그리는지. 그룹 헤더·접힌 그룹 행 제외·선택 전용 행·현 선택 표지·필터 고지·퇴화
# 평면을 되읽는다(관리 화면 tpl 프로브와 대칭 — 두 표면이 한 조직을 보인다는 실증).
_EDITOR_LIB_PICKER_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    window.JobScreen.showEditMode();
    var it = function (name, badge, level, cur) {
      return {key:name, name:name, path:'C:/lib/' + name, badge_label:badge, badge_level:level,
              is_error:false, detail:'필드 3개', current:!!cur};
    };
    var draft = {step:0, reachable:[false,false], template_path:'', template_name:'',
      field_count:0, fields:[], raw_block:'', gate_error:false, gate:null, notice:null,
      editing_origin:'',
      library:{flat:false, sections:[
        {group:'입찰', collapsed:false, count:2,
         items:[it('a.hwpx','준비됨','ok',true), it('b.hwpx','변환 필요','warn',false)]},
        {group:'계약', collapsed:true, count:1, items:[it('c.hwpx','준비됨','ok',false)]},
        {group:'', collapsed:false, count:1, items:[it('d.hwpx','준비됨','ok',false)]}
      ]}};
    window.__push('editor', draft);
    var host = document.getElementById('jobEditHost');
    out.grp_heads = host.querySelectorAll('.job-grp-head').length;              // 입찰·계약·그룹없음
    out.rows_visible = host.querySelectorAll('.libselrow').length;             // 계약 접힘 → 2+1
    out.pick_btns = host.querySelectorAll('.libselrow button[data-act="use-library"]').length;
    out.current_marked = host.querySelectorAll('.libselrow.cur').length;       // 현 선택(a) 1
    out.import_btn = !!host.querySelector('button[data-act="import-template"]');
    out.filter_notice = /HWPX 서식만/.test(host.textContent);  // 줄바꿈 무관 부분매치
    var caret = host.querySelector('.job-grp-head[aria-expanded="false"] .grp-caret');
    out.caret_collapsed = caret ? getComputedStyle(caret).visibility : 'missing';
    // F13 — 그룹 헤더에 안정 id(재렌더 뒤 포커스 복원 근거). F14 — 파일명 칸 말줄임/축소.
    var head0 = host.querySelector('.job-grp-head');
    out.grp_head_has_id = !!(head0 && head0.id);
    var fn = host.querySelector('.libselrow .fname');
    out.fname_ellipsis = fn ? getComputedStyle(fn).textOverflow : 'missing';
    out.fname_minwidth = fn ? getComputedStyle(fn).minWidth : 'missing';
    // 퇴화 평면(그룹 0개) — 헤더 없는 선택 행 나열.
    draft.library = {flat:true, sections:[{group:'', collapsed:false, count:1, items:[it('d.hwpx','준비됨','ok',false)]}]};
    window.__push('editor', draft);
    out.flat_heads = host.querySelectorAll('.job-grp-head').length;
    out.flat_rows = host.querySelectorAll('.libselrow').length;
    out.error = null;
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""


# 실제 클릭→Bridge.call→Python dispatch→initial snapshot 왕복(#189). 프로브가 만든 버튼도
# 브라우저의 click 이벤트 경로를 지나므로 API 직접 호출만으로는 잡지 못하는 이벤트/Promise
# 연결 단절을 함께 검출한다. 동작은 모두 빈 홈에서도 안전한 세션 초기화·새로고침이다.
_ACTION_ROUNDTRIP_PROBE_SETUP_JS = r"""
(() => {
  const out = { pending: true, families: {} };
  window.__actionRoundtrip = out;
  const specs = [
    ['editor', 'editor', 'new_session'],
    ['job', 'job', 'refresh'],
    ['draft', 'draft', 'refresh'],
    ['pool', 'pool', 'refresh'],
    ['template', 'tpl', 'refresh'],
  ];
  const host = document.createElement('div');
  host.hidden = true;
  host.id = 'selftestActionClicks';
  document.body.appendChild(host);
  Promise.all(specs.map(([family, screen, action]) => new Promise((resolve) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.family = family;
    button.addEventListener('click', async () => {
      try {
        await Bridge.call(screen, action, {});
        const snapshot = await Bridge.initial(screen);
        out.families[family] = {
          screen, action,
          snapshot: !!snapshot && typeof snapshot === 'object',
          snapshot_keys: snapshot && typeof snapshot === 'object' ? Object.keys(snapshot) : [],
        };
      } catch (e) {
        out.families[family] = { screen, action, error: String((e && e.message) || e) };
      }
      resolve();
    }, { once: true });
    host.appendChild(button);
    button.click();
  }))).then(() => { out.pending = false; host.remove(); });
  return true;
})()
"""


# ------------------------------------------------------------------ 자가검증(Q3)
_MILESTONE_H_WAVE1_PROBE_JS = r"""
(function () {
  function styleOf(el) {
    if (!el) return null;
    var s = getComputedStyle(el);
    return {
      font_size: s.fontSize, font_weight: s.fontWeight,
      background: s.backgroundColor, color: s.color,
      border_left: s.borderLeftColor, opacity: s.opacity
    };
  }
  function style(selector) { return styleOf(document.querySelector(selector)); }

  var gen = document.getElementById('jobGenBtn');
  var wasDisabled = gen.disabled;
  gen.disabled = true;
  var disabledPrimary = style('#jobGenBtn');
  gen.disabled = false;
  var enabledPrimary = style('#jobGenBtn');
  gen.disabled = wasDisabled;

  var card = document.querySelector('#tplHwpxGroups .tplcard, #tplTxtGroups .tplcard');
  if (!card) {
    card = document.createElement('div');
    card.className = 'tplcard';
    card.setAttribute('data-selftest-probe', 'card');
    document.querySelector('#scr-tpl .tpl-medium').appendChild(card);
  }
  var selectedCard = null;
  if (card) {
    var oldCurrent = card.getAttribute('aria-current');
    card.setAttribute('aria-current', 'true');
    selectedCard = styleOf(card);
    if (oldCurrent === null) card.removeAttribute('aria-current');
    else card.setAttribute('aria-current', oldCurrent);
  }

  var pathButtons = Array.from(document.querySelectorAll('.track-btn'));
  var scrollHost = document.createElement('div');
  scrollHost.className = 'tblwrap';
  scrollHost.style.height = '48px';
  scrollHost.innerHTML = '<table class="map"><thead><tr><th>머리</th></tr></thead><tbody>' +
    Array.from({length: 12}, function (_, i) { return '<tr><td>행 ' + i + '</td></tr>'; }).join('') +
    '</tbody></table>';
  document.body.appendChild(scrollHost);
  var scrollStyle = getComputedStyle(scrollHost);
  var stickyHead = scrollHost.querySelector('th');
  var stickyStyle = getComputedStyle(stickyHead);
  var stickyBefore = stickyHead.getBoundingClientRect().top;
  scrollHost.scrollTop = 40;
  var stickyAfter = stickyHead.getBoundingClientRect().top;
  var scrollContract = {
    overflow_y: scrollStyle.overflowY,
    gutter: scrollStyle.scrollbarGutter,
    overscroll: scrollStyle.overscrollBehavior,
    sticky_position: stickyStyle.position,
    sticky_holds: Math.abs(stickyAfter - stickyBefore) < 1,
    scroll_top: scrollHost.scrollTop
  };
  scrollHost.remove();
  return {
    headings: {
      screen: style('.scr-head h1'),
      section: style('.job-sec-head'),
      zone: style('#scr-job .zone-cap')
    },
    job_steps: Array.from(document.querySelectorAll('#scr-job .zone-cap')).map(function (e) {
      return e.textContent.trim();
    }),
    job_step_badges: document.querySelectorAll('#scr-job .zone-cap .znum').length,
    template_media_count: document.querySelectorAll('#scr-tpl .tpl-medium').length,
    template_media: style('#scr-tpl .tpl-medium'),
    template_card: styleOf(card),
    selected_card: selectedCard,
    disabled_primary: disabledPrimary,
    enabled_primary: enabledPrimary,
    pathtrack: {
      count: pathButtons.length,
      names: pathButtons.map(function (e) { return e.getAttribute('aria-label'); }),
      titled: pathButtons.every(function (e) { return !!e.getAttribute('title'); }),
      svg: pathButtons.every(function (e) { return !!e.querySelector('svg'); })
    },
    scroll: scrollContract
  };
})()
"""


# 마일스톤 H 최종 동적 프로브 — H-08/H-09/H-10/H-15/H-16의 계산 스타일과 실제
# dismissal/stack/IME/짧은 viewport 거동을 한 실 WebView2에서 검증한다. setup은 click 없는
# pointer 제스처의 다음-task 만료를 재현하므로 Python 드라이버가 한 task 이상 기다린 뒤 finish한다.
_MILESTONE_H_OVERLAY_PROBE_SETUP_JS = r"""
(function () {
  var out = { pending: true };
  window.__milestoneHOverlay = out;
  function finishModal(id) {
    var card = document.querySelector('#' + id + ' .modal-card');
    if (!card) return;
    var ev = new Event('transitionend', { bubbles: true });
    Object.defineProperty(ev, 'propertyName', { value: 'opacity' });
    card.dispatchEvent(ev);
  }
  try {
    var root = document.getElementById('overlayRoot');
    out.overlay_root_direct = root && root.parentElement === document.body;
    out.overlay_children_owned = Array.from(document.querySelectorAll('.modal,.ctx-menu,.colpanel'))
      .every(function (el) { return el.parentElement === root; });

    var scrollHost = document.createElement('div');
    scrollHost.className = 'jobtbwrap';
    scrollHost.style.cssText = 'height:72px;width:320px;overflow:auto';
    scrollHost.innerHTML = '<table class="jobtb"><thead><tr><th>머리</th></tr></thead><tbody>' +
      Array.from({length:16}, function (_, i) { return '<tr><td>행 ' + i + '</td></tr>'; }).join('') +
      '</tbody></table>';
    document.body.appendChild(scrollHost);
    var sb = getComputedStyle(scrollHost, '::-webkit-scrollbar');
    var sbtn = getComputedStyle(scrollHost, '::-webkit-scrollbar-button');
    var sh = getComputedStyle(scrollHost.querySelector('th'));
    out.scrollbar = { width: sb.width, button_display: sbtn.display,
      button_width: sbtn.width, button_height: sbtn.height };
    out.sticky_material = { position: sh.position, backdrop: sh.backdropFilter,
      background: sh.backgroundColor };
    scrollHost.remove();

    var cardRender = document.getElementById('draftCardRender');
    var dot = document.querySelector('#draftCardDots .wc-dot');
    var madeDot = false;
    if (!dot) {
      dot = document.createElement('button');
      dot.className = 'wc-dot';
      document.getElementById('draftCardDots').appendChild(dot);
      madeDot = true;
    }
    var cr = cardRender && getComputedStyle(cardRender);
    var ds = dot && getComputedStyle(dot);
    var dm = dot && getComputedStyle(dot, '::before');
    out.workcard = {
      max_height: cr && cr.maxHeight, overflow_y: cr && cr.overflowY,
      gutter: cr && cr.scrollbarGutter, overscroll: cr && cr.overscrollBehavior,
      dot_hit: ds && [ds.width, ds.height], dot_mark: dm && [dm.width, dm.height],
      dots_overflow: getComputedStyle(document.getElementById('draftCardDots')).overflow
    };
    if (madeDot) dot.remove();

    var trigger = document.createElement('button');
    trigger.id = '__hOverlayTrigger'; trigger.textContent = 'trigger';
    trigger.style.cssText = 'position:fixed;right:2px;bottom:2px';
    document.body.appendChild(trigger);
    var outside = document.createElement('button');
    outside.id = '__hOverlayOutside'; outside.textContent = 'outside';
    document.body.appendChild(outside);
    var pop = document.createElement('div');
    pop.className = 'ctx-menu'; pop.style.cssText = 'display:flex;width:260px;height:160px';
    pop.innerHTML = '<button id="__hOverlayInside">inside</button>';
    root.appendChild(pop);
    var popOpen = true;
    var closeCount = 0;
    function openPop() { popOpen = true; pop.style.display = 'flex'; }
    function closePop() { popOpen = false; pop.style.display = 'none'; closeCount += 1; }
    var unregister = window.Popover.register({
      isOpen: function () { return popOpen; },
      contains: function (t) { return pop.contains(t); },
      close: closePop
    });
    var placed = window.Popover.place(pop, trigger);
    var pr = pop.getBoundingClientRect();
    var ps = getComputedStyle(pop);
    out.popover_place = { placement: placed.placement,
      in_viewport: pr.left >= 0 && pr.top >= 0 && pr.right <= innerWidth && pr.bottom <= innerHeight,
      origin: pop.style.transformOrigin, radius: ps.borderRadius, shadow: ps.boxShadow };

    trigger.focus();
    window.Modal.open('draftSaveTplModal', {
      initialFocus: document.getElementById('draftSaveTplName'), returnFocus: trigger
    });
    var formModal = document.getElementById('draftSaveTplModal');
    out.modal_closed_popover = !popOpen;
    out.modal_focus_in = document.activeElement.id;
    out.z_order = parseInt(getComputedStyle(formModal).zIndex, 10) > parseInt(ps.zIndex, 10);
    var imeEscape = new KeyboardEvent('keydown', { key:'Escape', bubbles:true });
    Object.defineProperty(imeEscape, 'isComposing', { value:true });
    document.dispatchEvent(imeEscape);
    out.ime_escape_kept_open = !formModal.classList.contains('hidden') &&
      !formModal.classList.contains('is-closing');
    document.dispatchEvent(new KeyboardEvent('keydown', { key:'Escape', bubbles:true }));
    out.exit_blocks_pointer = formModal.classList.contains('is-closing') &&
      getComputedStyle(formModal).pointerEvents === 'auto';
    finishModal('draftSaveTplModal');
    out.menu_trigger_restored = document.activeElement === trigger;

    // 두 겹에서 Escape 한 번은 최상위만 퇴장시킨다.
    window.Modal.open('draftSaveTplModal', { returnFocus: trigger });
    window.Modal.open('confirmModal', { returnFocus: trigger });
    document.dispatchEvent(new KeyboardEvent('keydown', { key:'Escape', bubbles:true }));
    out.escape_one_layer = document.getElementById('confirmModal').classList.contains('is-closing') &&
      !document.getElementById('draftSaveTplModal').classList.contains('is-closing');
    finishModal('confirmModal');
    window.Modal.close('draftSaveTplModal'); finishModal('draftSaveTplModal');

    // 720x500에서 200줄 본문을 끝까지 스크롤하면 액션이 viewport 안에 도달한다.
    var longModal = document.getElementById('confirmModal');
    var longBody = document.getElementById('confirmModalBody');
    var savedBody = longBody.innerHTML;
    longBody.innerHTML = Array.from({length:200}, function (_, i) { return '<div>본문 ' + i + '</div>'; }).join('');
    window.Modal.open('confirmModal', { returnFocus: trigger });
    var longCard = longModal.querySelector('.modal-card');
    longCard.scrollTop = longCard.scrollHeight;
    var actions = longModal.querySelector('.modal-actions').getBoundingClientRect();
    out.short_viewport = { height: longCard.getBoundingClientRect().height,
      viewport: innerHeight, scrollable: longCard.scrollHeight > longCard.clientHeight,
      actions_reachable: actions.bottom <= innerHeight + 1 && actions.top >= -1 };
    window.Modal.close('confirmModal'); finishModal('confirmModal');
    longBody.innerHTML = savedBody;

    var outsideClicks = 0;
    outside.addEventListener('click', function () { outsideClicks += 1; });
    openPop();
    outside.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles:true, button:0, pointerId:77, isPrimary:true
    }));
    outside.dispatchEvent(new PointerEvent('pointerup', {
      bubbles:true, button:0, pointerId:77, isPrimary:true
    }));
    out.drag_closed = !popOpen;
    out.finish = function () {
      outside.click();
      out.click_after_drag = outsideClicks === 1;
      openPop();
      outside.dispatchEvent(new PointerEvent('pointerdown', {
        bubbles:true, button:2, pointerId:78, isPrimary:true
      }));
      outside.click();
      out.click_after_right = outsideClicks === 2;
      openPop();
      var inside = document.getElementById('__hOverlayInside');
      inside.focus();
      inside.dispatchEvent(new FocusEvent('focusout', { bubbles:true, relatedTarget:outside }));
      out.focusout_closed = !popOpen;
      openPop();
      document.body.dispatchEvent(new Event('scroll', { bubbles:false }));
      out.scroll_closed = !popOpen;
      openPop();
      window.Popover.closeAll();
      out.close_all_closed = !popOpen;
      unregister(); pop.remove(); trigger.remove(); outside.remove();
      out.close_count = closeCount;
      out.pending = false;
      delete out.finish;
      return out;
    };
  } catch (e) {
    out.pending = false;
    out.error = String((e && e.stack) || e);
  }
  return out;
})()
"""


def _finish_selftest(window: "object", result: dict) -> None:
    """되읽기 결과를 결정적 위치에 쓰고 정식 종료한다(쓰기·읽기 단계 공용).

    출력 경로: 테스트 하네스(#30 접근 A)가 HWPX_SELFTEST_OUT 로 결정적 위치를 준다.
    미설정 시 동결 exe 옆(dist) — 기존 부팅 자가검증 거동 불변. destroy 는 os._exit 대체(소이슈 ①).
    """
    out_override = os.environ.get("HWPX_SELFTEST_OUT")
    out = Path(out_override) if out_override else Path(sys.executable).resolve().parent / "selftest_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    window.destroy()  # type: ignore[attr-defined]


def _selftest_drive(window: "object") -> None:
    """동결 exe 부팅 자가검증 — 창이 뜨고 렌더/브리지가 도는지 되읽어 파일로 확정 후 정식 종료.

    ``HWPX_SELFTEST_SET_THEME`` 이 설정되면 **쓰기 단계**로 동작한다: 저장 테마를 Python 설정
    (settings.json)에 심고 바로 정식 종료한다(다음 콜드부트의 오리진 비의존 영속 되읽기용 사전 단계, #74).
    """
    import time

    if os.environ.get("HWPX_SELFTEST_GEOMETRY_ONLY"):
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if window.evaluate_js("document.readyState === 'complete' && !!document.body"):  # type: ignore[attr-defined]
                break
            time.sleep(0.1)
        time.sleep(0.4)  # 네이티브 최대화/복원 이벤트와 JS outer* 반영 안정
        geometry = window.evaluate_js(  # type: ignore[attr-defined]
            "({x:screenX,y:screenY,width:outerWidth,height:outerHeight,"
            "avail_x:screen.availLeft||0,avail_y:screen.availTop||0,"
            "avail_width:screen.availWidth,avail_height:screen.availHeight})"
        )
        geometry["maximized_like"] = (
            geometry["x"] <= geometry["avail_x"] + 32
            and geometry["y"] <= geometry["avail_y"] + 32
            and geometry["x"] + geometry["width"]
            >= geometry["avail_x"] + geometry["avail_width"] - 8
            and geometry["y"] + geometry["height"]
            >= geometry["avail_y"] + geometry["avail_height"] - 8
        )
        _finish_selftest(window, {"window_geometry": geometry})
        return

    set_theme = os.environ.get("HWPX_SELFTEST_SET_THEME")
    set_font_scale = os.environ.get("HWPX_SELFTEST_SET_FONT_SCALE")
    if set_font_scale:
        result = {"font_scale_write": set_font_scale}
        try:
            ready_probe = "!!(window.pywebview && window.pywebview.api && window.Personalization)"
            ready_deadline = time.monotonic() + 15.0
            while time.monotonic() < ready_deadline:
                if window.evaluate_js(ready_probe):  # type: ignore[attr-defined]
                    break
                time.sleep(0.1)
            else:
                result["error"] = "브리지 준비 시한 초과 — Personalization.setFontScale 미구동"
                _finish_selftest(window, result)
                return
            window.evaluate_js(  # type: ignore[attr-defined]
                "window.Personalization.setFontScale(" + json.dumps(set_font_scale) + ")"
            )
            deadline = time.monotonic() + 10.0
            while settings.load_font_scale() != set_font_scale and time.monotonic() < deadline:
                time.sleep(0.1)
            result["set_result"] = settings.load_font_scale()
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        _finish_selftest(window, result)
        return

    if set_theme:
        result: dict = {"theme_write": set_theme}
        try:
            # 실사용 경로 그대로 구동 — 토글 클릭이 지나는 theme.js Theme.set→Bridge.setTheme→
            # api.set_theme 홉 전체(브리지 가드 포함)를 게이트가 덮는다(api 직접 호출로 바꾸면
            # theme.js 결함이 무커버가 된다). 단 Theme.set 의 브리지 가드는 pywebview.api 미준비
            # 시 **조용히 no-op** 이라, 고정 sleep 으로 준비를 어림하면 느린 콜드부트에서 쓰기가
            # 아예 발화 안 돼 정상 빌드가 빨개진다(#75 리뷰 #5). 준비를 명시 폴링하고, 시한 초과는
            # 조용한 통과가 아니라 시끄러운 error 로 확정한다(confirm-or-alarm).
            ready_probe = "!!(window.pywebview && window.pywebview.api && window.Bridge && window.Theme)"
            ready_deadline = time.monotonic() + 15.0
            while time.monotonic() < ready_deadline:
                if window.evaluate_js(ready_probe):  # type: ignore[attr-defined]
                    break
                time.sleep(0.1)
            else:
                result["error"] = "브리지(pywebview.api) 준비 시한 초과 — Theme.set 미구동"
                _finish_selftest(window, result)
                return
            window.evaluate_js(  # type: ignore[attr-defined]
                "window.Theme.set(" + json.dumps(set_theme) + ")")
            # evaluate_js 는 promise 를 대기하지 않으므로 디스패치·파일 쓰기 완료를 데드라인까지
            # 폴링해 확정한다(#74).
            deadline = time.monotonic() + 10.0
            while settings.load_theme() != set_theme and time.monotonic() < deadline:
                time.sleep(0.1)
            result["set_result"] = settings.load_theme()  # 종료 전 실제 디스크 반영 확정
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        _finish_selftest(window, result)
        return

    time.sleep(4.5)
    result: dict = {}
    try:
        result["url"] = window.get_current_url()  # type: ignore[attr-defined]
        result["title_dom"] = window.evaluate_js("document.title")  # type: ignore[attr-defined]
        result["nav_count"] = window.evaluate_js("document.querySelectorAll('.navbtn').length")  # type: ignore[attr-defined]
        result["tpl_options"] = window.evaluate_js(  # type: ignore[attr-defined]
            "Array.from(document.querySelectorAll('#tplSel option')).map(o=>o.value)")
        # H-05: 콜드 부팅은 작업으로 진입하고, 홈은 KPI·이어서 없이 경보 허브로만 남는다.
        result["job_on"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.getElementById('scr-job').classList.contains('on')")
        result["home_kpi_count"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.querySelectorAll('#homeKpis .kpi').length")
        result["home_continue_count"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.querySelectorAll('#homeContinue .continue-run').length")
        result["home_alerts_present"] = window.evaluate_js(  # type: ignore[attr-defined]
            "!!document.getElementById('homeAlerts')")
        # 데이터 관리 화면(#26 #4) — 7번째 화면이 실제 init·렌더됐는지(빈 상태 문구도 렌더).
        result["pool_rendered"] = window.evaluate_js(  # type: ignore[attr-defined]
            "(document.getElementById('poolList')||{innerHTML:''}).innerHTML.length > 0")
        # 2소스 진입점(#26 #6) — 두 세션 표면(작업·기안)의 '등록 데이터…' 버튼 실재.
        # (구 txt 의 btnTxtPoolData 는 슬라이스 6 에서 삭제 — 「기안」의 draftBtnPoolData 로 재겨눔.)
        result["pool_buttons"] = window.evaluate_js(  # type: ignore[attr-defined]
            "['jobBtnPoolData','draftBtnPoolData']"
            ".every(function(i){return !!document.getElementById(i)})")
        # 다섯 액션군의 실 브라우저 클릭부터 Python registry dispatch, 반환 snapshot까지 한 실행
        # 단위로 완주한다(#189). 완료 표지를 폴링해 evaluate_js의 Promise 비대기 의미론과 분리.
        window.evaluate_js(_ACTION_ROUNDTRIP_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        action_deadline = time.monotonic() + 10.0
        while time.monotonic() < action_deadline:
            if window.evaluate_js(  # type: ignore[attr-defined]
                "!!(window.__actionRoundtrip && !window.__actionRoundtrip.pending)"
            ):
                break
            time.sleep(0.1)
        result["action_roundtrip"] = window.evaluate_js(  # type: ignore[attr-defined]
            "window.__actionRoundtrip")
        # 커스텀 모달 접근성 동적 거동(#27/#28) — 정적 계약(role/aria)은 test_web_dom_contract 가
        # 보고, 여기선 실 브라우저에서 Modal 헬퍼가 초기포커스·Escape 닫기·트리거 복귀를 실제로
        # 수행하는지 되읽는다. 알려진 트리거(첫 내비 버튼)에 포커스를 두고 열었다가 Escape 로 닫는다.
        result["modal_a11y"] = window.evaluate_js(_MODAL_A11Y_PROBE_JS)  # type: ignore[attr-defined]
        # promise 다이얼로그 해소값(#92 리뷰 #1) — 프로브가 .then 으로 stash 한 값을 별도
        # evaluate_js 로 되읽는다(마이크로태스크는 앞 스크립트 스택 해제 시 이미 플러시됨).
        # 첫 confirm=true(확인 클릭), 재진입 confirm=false(즉시 안전측 거절)여야 한다.
        result["modal_confirm_serial"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({ first: window.__cf1, second: window.__cf2 })")
        # 반응형 경계(#27) — 창을 최소폭(760<820 경계)으로 줄였다 넓히며 .app 그리드 열 수를
        # 실 엔진에서 되읽는다. 정적 CSS 경계 존재는 test_web_dom_contract 가, 실제 접힘/펴짐은
        # 여기가 가드. resize 는 OS 이벤트라 relayout 안정까지 짧게 대기(게이트는 flaky 금지).
        grid_probe = "getComputedStyle(document.querySelector('.app')).gridTemplateColumns"
        window.resize(760, 600)  # type: ignore[attr-defined]  # 최소 크기 = 경계 아래 → 세로 적층
        time.sleep(0.6)
        result["grid_narrow"] = window.evaluate_js(grid_probe)  # type: ignore[attr-defined]
        window.resize(1440, 900)  # type: ignore[attr-defined]  # 새 기본 크기 = 셸 2판 + 기안 duo
        time.sleep(0.6)
        result["grid_wide"] = window.evaluate_js(grid_probe)  # type: ignore[attr-defined]
        # 다중 시트 확정 게이트(#33) — SheetPicker.choose 를 실 DOM 에서 구동(확정→로드, 취소→중단).
        # async·상호작용 구동이라 fire 후 짧게 대기하고 stash 를 되읽는다(preserve_real 패턴).
        window.evaluate_js(_SHEET_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        time.sleep(0.8)  # choose 두 회차(확정·취소) 마이크로태스크 해소 여유
        result["sheet_gate"] = window.evaluate_js("window.__sheetProbe")  # type: ignore[attr-defined]
        # 상호작용 보존(#28) — Preserve 헬퍼가 재구성 가로질러 포커스·캐럿·스크롤 유지하는지(기제).
        result["preserve"] = window.evaluate_js(_PRESERVE_PROBE_JS)  # type: ignore[attr-defined]
        # 실화면 회귀(#28) — 실 컨트롤러 스냅샷으로 4화면 실 render() 구동 + txt 스크롤 보존 end-to-end.
        window.evaluate_js(_PRESERVE_REAL_SETUP_JS)  # type: ignore[attr-defined]  # 비동기 initial fire
        time.sleep(1.2)  # initial() 해소 + 렌더 안정
        result["preserve_real"] = window.evaluate_js(_PRESERVE_REAL_PROBE_JS)  # type: ignore[attr-defined]
        # 「작업」 거울 + 재진술 블록(슬라이스 2) — 합성 스냅샷으로 실 render() 구동 후 DOM 되읽기.
        result["job_mirror"] = window.evaluate_js(_JOB_MIRROR_PROBE_JS)  # type: ignore[attr-defined]
        # 「작업」 좌 목록 그룹·⋮ 관리 메뉴(결정 43) — 그룹 헤더·접힘·메뉴 개폐 실렌더 되읽기.
        result["job_list_groups"] = window.evaluate_js(_JOB_LIST_GROUP_PROBE_JS)  # type: ignore[attr-defined]
        # 「기안」 좌 목록(#148 슬라이스 2b) — 그룹 구획·⋮ 메뉴·이동 다이얼로그(grouplist.js 3번째 소비) 되읽기.
        result["draft_list"] = window.evaluate_js(_DRAFT_LIST_PROBE_JS)  # type: ignore[attr-defined]
        # 「기안」 휘발 세션 4존(#148 슬라이스 3a) — 공용 팩토리(draftsession.js)의 두 번째
        # 소비 인스턴스가 draft 화면 DOM 에서 실제로 서는지(데이터 존·카드·린트·완료) 되읽기.
        result["draft_session"] = window.evaluate_js(_DRAFT_SESSION_PROBE_JS)  # type: ignore[attr-defined]
        result["draft_sheets"] = window.evaluate_js(_DRAFT_SHEETS_PROBE_JS)  # type: ignore[attr-defined]
        # #270 컨테이너 쿼리의 협폭 분기 — 같은 DOM을 1180급 창에서 되읽어 적층·sticky 해제를
        # 실제 Chromium 레이아웃으로 고정하고 즉시 새 기본창으로 복원한다.
        window.resize(1180, 820)  # type: ignore[attr-defined]
        time.sleep(0.4)
        result["draft_density_narrow"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({columns:getComputedStyle(document.getElementById('draftDuo')).gridTemplateColumns,"
            "preview_position:getComputedStyle(document.querySelector('#draftDuo .draft-preview-zone')).position})"
        )
        window.resize(1440, 900)  # type: ignore[attr-defined]
        time.sleep(0.4)
        result["job_editmode"] = window.evaluate_js(_JOB_EDITMODE_PROBE_JS)  # type: ignore[attr-defined]
        # 매핑 칩-라이브(슬라이스 5 PR-3) — 합성 매핑 스냅샷으로 실 render() 구동 후 칩·태그 되읽기.
        result["editor_chip"] = window.evaluate_js(_EDITOR_CHIP_PROBE_JS)  # type: ignore[attr-defined]
        # (구 txt_zone·quickdraft 프로브는 #148 슬라이스 6 에서 두 화면과 함께 삭제 — 두 화면이
        # 쓰던 공용 팩토리(datazone.js·draftsession.js) 커버리지는 draft_session 프로브가 승계한다.)
        # 템플릿 관리(#108) — 매체 구획+그룹·⋮ 메뉴·＋그룹지정 칩·이동 다이얼로그 실렌더 되읽기.
        result["tpl_groups"] = window.evaluate_js(_TPL_LIST_GROUP_PROBE_JS)  # type: ignore[attr-defined]
        # 마일스톤 H 웨이브 1 — 실제 계산 타이포·표면·버튼 위계와 PathTrack 접근 이름을
        # 합성 작업/템플릿 렌더 뒤 실 WebView2에서 되읽는다.
        result["milestone_h_wave1"] = window.evaluate_js(  # type: ignore[attr-defined]
            _MILESTONE_H_WAVE1_PROBE_JS
        )
        # H 최종 실창 시나리오: overlay/modal/popover와 짧은 viewport, 전역 scrollbar/workcard를
        # 실제 계산 스타일·이벤트로 되읽는다. click 없는 pointer 제스처 만료는 task 경계를 둔다.
        window.resize(720, 500)  # type: ignore[attr-defined]
        time.sleep(0.3)
        window.evaluate_js(_MILESTONE_H_OVERLAY_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        time.sleep(0.1)
        result["milestone_h_overlay"] = window.evaluate_js(  # type: ignore[attr-defined]
            "window.__milestoneHOverlay.finish ? "
            "window.__milestoneHOverlay.finish() : window.__milestoneHOverlay"
        )
        window.resize(1440, 900)  # type: ignore[attr-defined]
        time.sleep(0.3)
        # 에디터 1단계 피커(#108 슬라이스 3) — 라이브러리 그룹 구획(선택 전용) 실렌더 되읽기.
        result["editor_lib"] = window.evaluate_js(_EDITOR_LIB_PICKER_PROBE_JS)  # type: ignore[attr-defined]
        # 다크모드 영속·무깜빡임(콜드부트 되읽기, #74) — 부팅 시 loaded 핸들러가 저장 테마
        # (settings.json, 오리진 비의존)를 show 전에 data-theme 로 주입했는지. 저장값이 없으면
        # data_theme=null(=system). 앞선 쓰기 프로세스가 남긴 값이 여기서 보이면 Python 설정
        # 영속이 실증된다(포트/오리진이 부팅마다 달라도 유지 = 실사용 그대로).
        result["theme_persist"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({data_theme: document.documentElement.getAttribute('data-theme'),"
            " a_card: getComputedStyle(document.documentElement).getPropertyValue('--a-card').trim()})")
        result["personalization_persist"] = window.evaluate_js(  # type: ignore[attr-defined]
            "(function(){"
            "var root=document.documentElement,app=document.querySelector('.app'),body=document.body;"
            "var p=document.createElement('p');p.textContent='선택 가능한 본문';body.appendChild(p);"
            "var r=document.createRange();r.selectNodeContents(p);var s=getSelection();s.removeAllRanges();s.addRange(r);"
            "var selected=s.toString();s.removeAllRanges();p.remove();"
            "return {font_scale:root.getAttribute('data-font-scale'),root_px:getComputedStyle(root).fontSize,"
            "rail_collapsed:app.classList.contains('rail-collapsed'),"
            "master_width:parseFloat(getComputedStyle(app).getPropertyValue('--master-width')),"
            "splitters:document.querySelectorAll('.master-splitter').length,"
            "body_overflow:body.scrollWidth>body.clientWidth+1,selected_text:selected};})()"
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    _finish_selftest(window, result)


# ------------------------------------------------------------------ 엔트리
def _alarm(msg: str, window: "object | None" = None) -> None:
    """부팅 경보 — 내구성 채널(stderr + 홈 로그, settings.alert) + (가능하면) JS alert.

    내구성 채널은 settings.alert 가 소유한다(홈 경로·경보 로그가 거기 있고, settings 층 코드도
    같은 채널로 알려야 한다 — 순환 import 회피). 이 함수는 그 위에 창(JS alert) 계층만 얹는다.
    JS alert 는 fire-and-forget(setTimeout) — evaluate_js 가 alert 해소를 기다리다
    호출 스레드(loaded 핸들러·폴백 타이머)를 매달지 않게 한다."""
    settings.alert(msg)
    if window is not None:
        try:
            window.evaluate_js(  # type: ignore[attr-defined]
                f"setTimeout(function(){{window.alert({json.dumps('[hwpx] ' + msg)})}},0)")
        except Exception:  # noqa: BLE001  창이 그 정도로 죽었으면 alert 채널도 없다
            pass


def _prepare_webview_profile(webview_root: Path) -> Path:
    """부팅용 WebView2 프로필 준비 — ``webview_root`` 를 통째 청소하고 고정 ``profile`` 폴더를 만든다.

    단일 인스턴스 가드(main() 뮤텍스)가 이 홈에 우리뿐임을 보장하므로 ``webview_root`` 전체가
    우리 것이다 → 크래시 고아 프로필·구판 단일 폴더 잔재(EBWebView)·재시작 간 공유 디스크
    캐시(#69/#71 스테일 자산)를 iterate·프로브 없이 한 줄로 소거한다. 오리진 비의존 영속
    (settings.json)은 홈 **루트** 에 있어 webview_root 와 분리 — 통째 삭제가 안전하다.
    이전의 per-pid 폴더 + 부팅 스윕 + profile.lock 기계 전부를 대체한다(#74 리뷰3).

    ``resolve()`` 필수: 상대 storage_path 는 WebView2 생성 실패 → MSHTML(IE) 조용한 폴백(#69/#71).

    청소 실패(좀비 WebView2·AV 가 락 보유)는 **조용히 삼키지 않는다**(#75 리뷰4 #1): 삭제한
    _purge_webview_http_cache 가 이 OSError 를 경보했던 것처럼, 스테일 프로필 재사용(=구자산
    서빙, #69/#71 클래스)이 신호 없이 일어나지 않게 시끄럽게 알린 뒤 진행한다(부팅 불사)."""
    try:
        shutil.rmtree(webview_root)
    except FileNotFoundError:
        pass  # 첫 부팅 — 청소할 것이 없다(정상)
    except OSError as exc:
        settings.alert(f"WebView2 프로필 청소 실패 — 스테일 프로필 재사용 가능(구자산 서빙): {exc!r}")
    storage_dir = webview_root / "profile"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def main() -> int:
    import webview

    # 단일 인스턴스(이 홈 기준): 두 번째 실행은 기존 창을 앞으로 내고 조용히 종료한다. private_mode
    # 의 clear_user_data 가 동시 인스턴스 프로필을 밑에서 지우던 경합과, 그를 막으려던 per-pid
    # 프로필·부팅 스윕·profile.lock 기계 전부를 이 가드가 대체한다(#74 리뷰3). rc=0 = 정상 이중
    # 실행(오류 아님). --selftest 는 테스트 하네스 부팅(격리 홈, 순차 실행)이라 우회한다.
    if "--selftest" not in sys.argv:
        # 뮤텍스 핸들은 프로세스 종료 시 OS 가 회수하므로 파이썬 참조를 붙들 필요는 없다 —
        # None(=다른 인스턴스 보유)일 때만 분기하면 된다.
        if single_instance.acquire(settings.home_dir()) is None:
            single_instance.focus_existing(WINDOW_TITLE)
            return 0

    frontend = WebFrontend(default_text_templates_dir())
    saved_geometry = settings.load_window_geometry()
    if saved_geometry is not None and not _geometry_is_visible(saved_geometry):
        settings.alert("저장된 창 위치가 현재 화면 밖이라 기본 위치로 복원합니다")
        saved_geometry = None
    window = webview.create_window(
        WINDOW_TITLE,
        str(web_dir() / "index.html"),
        js_api=frontend,
        width=int(saved_geometry["width"]) if saved_geometry else DEFAULT_WINDOW_WIDTH,
        height=int(saved_geometry["height"]) if saved_geometry else DEFAULT_WINDOW_HEIGHT,
        x=int(saved_geometry["x"]) if saved_geometry else None,
        y=int(saved_geometry["y"]) if saved_geometry else None,
        maximized=bool(saved_geometry["maximized"]) if saved_geometry else False,
        min_size=(760, 600),
        text_select=True,
        # 브라우저 줌은 앱 레이아웃·다이얼로그 좌표까지 임의 배율로 갈라놓는다. 대신 S1의
        # 저장형 100/125/150% 앱 글자 배율을 제공해 재시작 뒤에도 같은 레이아웃을 재현한다.
        zoomable=False,
        hidden=True,  # 테마 주입 후 show — FOUC 은닉(#74, 아래 _apply_theme_then_show)
    )
    frontend._window = window
    window.events.closing += frontend._handle_window_closing

    # 창 기하 영속(S5) — 최대화 중 들어오는 resize/move 값은 정상 창 복원 좌표를 덮지 않는다.
    geometry_state: "dict[str, int | bool]" = dict(saved_geometry or {
        "x": 0, "y": 0, "width": DEFAULT_WINDOW_WIDTH, "height": DEFAULT_WINDOW_HEIGHT,
        "maximized": False,
    })
    geometry_lock = threading.Lock()
    geometry_timer: "list[threading.Timer | None]" = [None]

    def _persist_geometry() -> None:
        with geometry_lock:
            snapshot = dict(geometry_state)
            geometry_timer[0] = None
        try:
            settings.save_window_geometry(**snapshot)  # type: ignore[arg-type]
        except (OSError, ValueError) as exc:
            settings.alert(f"창 위치 저장 실패 — 현재 실행은 계속합니다: {exc!r}")

    def _schedule_geometry_save() -> None:
        with geometry_lock:
            old = geometry_timer[0]
            if old is not None:
                old.cancel()
            timer = threading.Timer(0.25, _persist_geometry)
            timer.daemon = True
            geometry_timer[0] = timer
            timer.start()

    def _on_window_resized(width: int, height: int) -> None:
        with geometry_lock:
            if not geometry_state["maximized"]:
                geometry_state.update(width=max(760, int(width)), height=max(600, int(height)))
        _schedule_geometry_save()

    def _on_window_moved(x: int, y: int) -> None:
        with geometry_lock:
            if not geometry_state["maximized"]:
                geometry_state.update(x=int(x), y=int(y))
        _schedule_geometry_save()

    def _on_window_maximized() -> None:
        with geometry_lock:
            geometry_state["maximized"] = True
        _schedule_geometry_save()

    def _on_window_restored() -> None:
        with geometry_lock:
            geometry_state["maximized"] = False
        _schedule_geometry_save()

    window.events.resized += _on_window_resized
    window.events.moved += _on_window_moved
    window.events.maximized += _on_window_maximized
    window.events.restored += _on_window_restored
    window.events.closed += _persist_geometry
    # 소이슈 ②: Windows 는 EdgeChromium(WebView2) 백엔드 명시 핀.
    gui = "edgechromium" if sys.platform == "win32" else None

    # FOUC 은닉(#74): 테마 영속을 오리진 비의존 Python 설정으로 옮기면서(private_mode 기본 복원)
    # head 동기 인라인 판독원(localStorage)이 사라졌다. pywebview 엔 첫 페인트 전 주입 훅이
    # 없어(WebView2 AddScriptToExecuteOnDocumentCreated 미노출) 표준 pre-paint '예방' 대신
    # '은닉'을 쓴다 — 창을 숨긴 채 띄우고 DOM 로드(loaded) 시 저장 테마를 data-theme 로 주입한
    # 뒤 show 하여, 라이트 첫 페인트를 화면 밖에서 소진시킨다. show 는 정확히 1회.
    shown = threading.Event()
    loaded_seen = threading.Event()  # 폴백 오경보 판별 — 미발화 vs 발화-후-진행중 구분(#75 리뷰)
    show_lock = threading.Lock()  # check-then-show 원자화 — loaded 핸들러 vs 폴백 타이머 스레드

    def _show_once() -> bool:
        """창 표시(정확히 1회). **이 호출이 실제 표시를 수행했으면** True — 경합 경로가
        '내가 강제로 띄웠는가'를 판별해 오경보를 내지 않게 한다."""
        with show_lock:
            if shown.is_set():
                return False
            window.show()  # type: ignore[attr-defined]
            shown.set()  # show 성공 **후** — 먼저 세우면 show 실패가 다른 경로까지 영구 차단
            return True

    # 폴백 예산(#77) — 첫 부트스트랩(또는 런타임 교체)에만 넓힌다. 판정·근거는 boot_budget.
    runtime_version = boot_budget.detect_runtime_version()
    budget_seconds, budget_reason = boot_budget.decide(
        settings.load_boot_completed(), runtime_version
    )

    def _apply_theme_then_show() -> None:  # loaded 콜백(0-인자로 호출됨, event.py:40)
        loaded_seen.set()
        # 완주 스탬프(#77): loaded 가 실제로 왔다 = 이 환경에서 은닉 부팅이 끝까지 간다.
        # 다음 부팅부터 좁은 예산으로 돌아가 매달림을 빨리 잡는다. 저장 실패로 부팅을
        # 죽이지 않는다 — 대가는 '다음 부팅도 넓은 예산'뿐이라 안전측이다.
        try:
            settings.save_boot_completed(runtime_version)
        except OSError as exc:  # noqa: BLE001 — 스탬프는 힌트다(부팅 불사)
            settings.alert(f"부팅 완료 기록 저장 실패 — 다음 부팅도 넓은 예산: {exc!r}")
        err: "object | None" = None
        try:
            personalization = {
                "font_scale": settings.load_font_scale(),
                "rail_collapsed": settings.load_rail_collapsed(),
                "master_width": settings.load_master_width(),
            }
            personalized = window.evaluate_js(  # type: ignore[attr-defined]
                "window.Personalization ? (window.Personalization.apply("
                + json.dumps(personalization)
                + "), true) : false"
            )
            if personalized is not True:
                err = f"window.Personalization 부재(evaluate_js 반환={personalized!r})"
            theme = settings.load_theme()
            if theme in ("light", "dark"):
                # Theme.apply(theme.js) 경유 — data-theme 설정 + themechange 발신으로 레일
                # 라벨까지 재동기된다(직접 setAttribute 는 라벨을 어긋난 채 남겼다). loaded 는
                # body 스크립트 실행 후라 window.Theme 실재가 계약 — 부재는 곧 주입 실패.
                ok = window.evaluate_js(  # type: ignore[attr-defined]
                    f"window.Theme ? (window.Theme.apply({json.dumps(theme)}), true) : false")
                if ok is not True and err is None:
                    err = f"window.Theme 부재(evaluate_js 반환={ok!r})"
        except Exception as exc:  # noqa: BLE001  테마 실패로 창이 안 뜨면 안 된다 — show 진행 후 경보
            err = exc
        try:
            _show_once()
        except Exception as exc:  # noqa: BLE001  pywebview Event.set 이 logger 로 삼키면(#75 리뷰)
            # 창은 안 보이는데 경보가 없다 — 여기서 직접 경보(창 은닉 상태라 alert 채널은 생략).
            _alarm(f"창 표시(show) 실패: {exc!r}")
        if err is not None:
            _alarm(f"테마 주입 실패: {err!r}", window)

    window.events.loaded += _apply_theme_then_show

    # 폴백(confirm-or-alarm): loaded 가 끝내 안 오면 창이 영영 숨겨진다 — 상한 후 강제 show + 경보.
    # 순서 계약(#75 리뷰): show 가 경보보다 **먼저**다 — _alarm 의 evaluate_js 는 pywebview 가
    # _pywebviewready 를 최대 20s 대기하므로, 미발화 시나리오에서 경보를 먼저 하면 은닉 상한이
    # 사실상 40s 로 배가된다.
    def _fallback_show() -> None:
        if loaded_seen.is_set() and shown.wait(10.0):
            return  # loaded 도착·핸들러 진행 중이었고 유예 안에 정상 완주 — 경보 없음
        try:
            forced = _show_once()
        except Exception as exc:  # noqa: BLE001  타이머 데몬 스레드 — 조용한 증발 금지
            _alarm(f"폴백 show 실패: {exc!r}")
            return
        if not forced:
            return  # 그 사이 loaded 핸들러가 표시 완료 — 정상 부팅, 경보 없음
        # 어느 예산이 얼마 만에 발화했는지 함께 남긴다 — 예산이 짧아 선발화한 것인지 진짜
        # 매달림인지를 로그만 보고 가를 수 있어야 한다(#77 오경보 진단의 유일 단서).
        budget_note = f" [예산 {budget_seconds:.0f}s · {budget_reason}]"
        _alarm(
            ("loaded 후 표시 매달림. 폴백으로 창 표시(테마 미주입 가능)"
             if loaded_seen.is_set()
             else "loaded 미발화. 폴백으로 창 표시(테마 미주입 가능)") + budget_note,
            window,
        )

    # 타이머가 webview.start() 전에 걸리므로 예산이 WebView2 콜드스타트(초회 런타임 부팅·AV
    # 스캔) 전체를 포함한다 — 짧으면 정상 부팅에서 폴백이 선발화해 무테마 창(FOUC)+거짓 경보.
    # 그 콜드스타트는 설치 후 첫 실행에만 30~60s 이므로 예산도 그때만 넓힌다(#77, boot_budget).
    timer = threading.Timer(budget_seconds, _fallback_show)
    timer.daemon = True
    timer.start()

    # private_mode 기본(True) = 랜덤 빈 포트 + InPrivate(비영속) → 포트 스쿼팅·캐시 스테일·서버
    # 크로스톡 클래스 구조 소멸(#74). 프로필은 홈/webview/profile 고정 폴더 — 단일 인스턴스
    # 가드(위)가 이 홈에 우리뿐임을 보장하므로 부팅마다 webview_root 를 통째 청소하고 새로
    # 만든다(크래시 고아·구판 EBWebView 잔재·재시작 간 공유 디스크 캐시를 한 번에 소거).
    # 정상 닫기 = webview.start 반환 = 클린 종료(소이슈 ①); 크래시 잔재는 다음 부팅 청소가 담당.
    webview_root = (settings.home_dir() / "webview").resolve()
    storage_dir = _prepare_webview_profile(webview_root)
    try:
        if "--selftest" in sys.argv:
            webview.start(_selftest_drive, window, gui=gui, storage_path=str(storage_dir))
        else:
            webview.start(gui=gui, storage_path=str(storage_dir))
    finally:
        timer.cancel()
        shutil.rmtree(storage_dir, ignore_errors=True)  # 자기 정리(크래시로 못 지우면 다음 부팅 청소)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
