"""pywebview 창 + 브리지 + 엔트리 — 웹 프론트엔드의 링2.

    python -m hwpxfiller.webapp        # 개발 구동(창)
    hwpx-filler-web                    # 설치 후 gui-script

브리지(:class:`WebFrontend`)는 화면 id → 컨트롤러(:mod:`~hwpxfiller.webapp.screens`)
라우팅을 얇게 얹는다. 웹→Python 은 ``js_api``(``initial``·``dispatch``·네이티브 동작),
Python→웹은 버전 있는 제품 파사드 하나 ``window.__hwpx``(N-07, :mod:`.product_api`)다.

자가검증은 그와 **별도 계정**인 ``window.__hwpxTest``(N-09, :mod:`.selftest_api`)로 가고,
그 전역은 능력을 명시로 요구한 라이브 실행에서만 선다 — 정상 실행에는 없다.

사람 대신 창을 모는 실행(부팅 자가검증 · Quickstart 101 하니스)의 호출 계약은
:mod:`.live_run` 이 소유한다(N-11A). ``main(argv, live=…)`` 이 그 유일한 입구다.

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
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from ..host import boot_budget
from . import live_run, product_api, selftest_api
from ..external import settings
from .action_registry import validate_dispatch
from ..web_artifact import (
    VerifiedWebArtifact,
    WebArtifactViolation,
    resolve_web_artifact,
)
from ..external.hwpx_engine import make_hwpx_engine
from ..external.job_store import JobRegistry
from ..host.locations import default_jobs_dir, default_text_templates_dir
from ..external.text_registry import TextTemplateRegistry
from ..data.excel import ambiguous_sheets, sheet_overview  # 다중 시트 확정 게이트 판정(#33)
# 데이터 소스 factory 조립(P2-16) — concrete 선택은 Host 인 이 파일 한 곳만 한다.
# 링1(run_state)·링2(screen_job)는 포트로 관통만 한다(`gui → data.factory` 역간선 제거).
from ..data.factory import source_for_path, source_from_pool_item
from ..gui.edit_session import SECTION_BINDING  # 편집기 기본 착지 탭(계약 §5.1 어휘)
from ..gui.file_filters import EXCEL_FILTER_PATTERN  # 확장자 단일 출처(RC-34) — Qt-free 상수
from ..host.native import single_instance
from ..host.native.clipboard import set_clipboard_text
from ..host.native.debug import log
from ..host.native.dialogs import open_file_dialog, open_folder_dialog
from ..host.native.reveal import open_path as _native_open_path
from ..host.native.reveal import reveal_in_explorer as _native_reveal
from .screen_editor import EditorController
from .screen_library import LibraryController
from .screen_job import JobController
from .screen_pool import PoolController
from .screen_template import TemplateController
from .screen_workbench import TargetFontSetting, WorkbenchController
from .template_groups import TemplateGroupModel
from .screens import (
    collect_owned_paths,
    default_pool_registry,
    source_label,
    validate_owned_path,
)


_DISPATCH_REJECTION_KEY = "__hwpx_dispatch_rejection_v1__"


WINDOW_TITLE = "문서나르미"  # 창 제목(#258 제품명) = 파일 다이얼로그 소유주 창을 FindWindowW 로 찾는 키
DEFAULT_WINDOW_WIDTH = 1440
DEFAULT_WINDOW_HEIGHT = 900

# 파일 선택 다이얼로그 필터 — pick_data_file·pick_pool_data_file 공유 단일 출처(둘 다
# "엑셀/CSV 데이터" 참조를 다루므로 필터가 같다; 확장자 자체의 단일 출처는 EXCEL_FILTER_PATTERN).
_EXCEL_OR_ANY_FILTERS = [("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")]
# 템플릿 필터 — pick_template_path(재연결) 전용. 가져오기는 F8 통일로
# _LIBRARY_IMPORT_FILTERS 를 쓴다(§10.17.2 판정 C — hwpx·txt·RAW 수용).
_TEMPLATE_FILTERS = [("HWPX 템플릿", "*.hwpx"), ("모든 파일", "*.*")]
# 라이브러리 가져오기 필터(#108 결정 4) — HWPX·TXT 겸용. 확장자가 곧 매체 라우팅(복사 대상
# 루트 결정)이라 두 형식을 함께 연다("모든 파일"은 오확장 유입 방지로 제외 — import 는 확장자로만 라우팅).
_LIBRARY_IMPORT_FILTERS = [("HWPX·TXT 템플릿", "*.hwpx;*.txt")]


# ------------------------------------------------------ native 대화상자 단일 입구
#: 현재 라이브 실행(:mod:`.live_run`)이 세운 대체. ``None`` = 실물 OS 대화상자.
#: 라이브 실행이 아닌 정상 실행에서는 끝까지 ``None`` 이라 분기 자체가 죽어 있다.
_live_file_dialogs: "live_run.FileDialogs | None" = None


def _file_dialog(filters: "list[tuple[str, str]]") -> "str | None":
    """native 파일 열기의 **유일한 입구**.

    호출부가 ``open_file_dialog`` 를 직접 부르면 라이브 실행의 대체가 그 자리만 비껴간다 —
    종전 하니스가 모듈 전역을 통째로 갈아끼워야 했던 이유가 그것이고, 그 치환은 대체 대상이
    하나 늘 때마다 조용히 반쪽이 됐다. 입구를 하나로 모아 그 반쪽을 구조적으로 없앤다
    (``tests/test_architecture.py`` 가 우회 호출 0을 센다).
    """
    dialogs = _live_file_dialogs
    if dialogs is not None:
        return dialogs.open_file(filters, owner_title=WINDOW_TITLE)
    return open_file_dialog(filters, owner_title=WINDOW_TITLE)


def _folder_dialog(title: str) -> "str | None":
    """native 폴더 선택의 유일한 입구 — :func:`_file_dialog` 의 짝."""
    dialogs = _live_file_dialogs
    if dialogs is not None:
        return dialogs.open_folder(title, owner_title=WINDOW_TITLE)
    return open_folder_dialog(title, owner_title=WINDOW_TITLE)


# ------------------------------------------------------------------ 경로 해석
def _repo_root() -> Path:
    # app.py = <repo>/src/hwpxfiller/webapp/app.py → parents[3] = <repo>
    return Path(__file__).resolve().parents[3]


def web_artifact() -> VerifiedWebArtifact:
    """현재 제품이 사용할 유일한 검증 완료 웹 산출물을 반환한다.

    Source checkout은 fresh ``build/web/``과 현재 ``frontend/``·lock·config 입력까지
    검증한다. Frozen 제품은 ``sys._MEIPASS/web``의 seal과 전체 파일 트리만 검증하며
    repository source, Node 또는 dev server를 찾지 않는다.
    """
    if getattr(sys, "frozen", False):
        return resolve_web_artifact(
            frozen_root=Path(sys._MEIPASS),  # type: ignore[attr-defined]
        )
    return resolve_web_artifact(repo_root=_repo_root())


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
    # 가로 판정은 제목줄 **전체 폭**과 화면의 겹침으로(#276 리뷰) — 왼쪽 64px 조각만 보면
    # 왼쪽 모서리가 64px 넘게 화면 밖인 창(예: x=-100, 폭 1180)은 제목줄 대부분이 보이는데도
    # 미가시로 판정돼, 쓸 만한 저장 위치를 버리고 다음 부팅이 창을 예고 없이 리셋한다.
    overlap = min(x + width, vx + vw) - max(x, vx)
    return overlap >= min(width, 64) and y + 32 > vy and y < vy + vh


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
        hwpx_engine = make_hwpx_engine()
        # txt 템플릿 그룹 모델 — 관리 화면과 편집기 TXT 밴드가 공유하는 단일 실체(#135).
        txt_groups = TemplateGroupModel("txt")
        # 대상 글꼴 선언(결정 17)은 **앱 전역 영속** — 단일 실체 주입 규율은 소비자가
        # 작업대 하나가 된 지금도 유지한다(사본 캐시 = 선언≠실제 결함류, 코덱스 P2).
        target_font = TargetFontSetting()
        # 추적성 로케이트 화이트리스트(#53-B)용 레지스트리 참조(밑줄=js_api 반영 제외).
        self._job_registry = job_registry
        self._pool_registry = pool_registry
        # 진행 중인 런의 **단일 사실**(9R P1) — 규칙을 쓰는 표면이 여럿이라(「문서 만들기」·
        # 라이브러리 재연결·편집기 진입) 자물쇠가 한 화면 소유이면 나머지가 조용히 빠진다.
        generation_lock = threading.Lock()
        # 화면 등록 — 새 화면 = 컨트롤러 1개 추가(순수 데이터는 dispatch, 네이티브는 아래 메서드).
        controllers = [
            # 「문서 작업」 전역 라이브러리(§19.6) — 홈 화면의 승계자(재작성 F2). TXT
            # 레지스트리는 편집기·템플릿 관리와 공유(변경이 반영). pool_registry 공유 =
            # 등록 데이터에서 생긴 손상이 라이브러리 경보에 즉시 보인다(#45).
            LibraryController(job_registry, registry, self._push, pool_registry=pool_registry,
                              generation_lock=generation_lock, engine=hwpx_engine),
            # 「문서 만들기」 — 세션 패널(v6 screen-data 2열). 링1 VM 을 직접 소유하며
            # 실행 결정 계약을 소비하는 유일 세션 표면이다. TXT 레지스트리는 고지 ①
            # (후보 TXT 구획 빈 상태, F6 PR-B)의 술어 전용 — tpl·편집기와 같은 인스턴스.
            JobController(job_registry, self._push, pool_registry=pool_registry,
                          generation_lock=generation_lock, engine=hwpx_engine,
                          text_registry=registry,
                          file_source_factory=source_for_path,
                          pool_source_factory=source_from_pool_item),
            # 템플릿 관리(#13) — TXT 레지스트리는 편집기·「문서 만들기」와 공유(변경이 반영).
            TemplateController(registry, self._push, txt_groups=txt_groups),
            # 등록 데이터 참조·수명(#26 #4) — 화면은 사망하고 데이터 선택 다이얼로그가 소비(F1).
            PoolController(pool_registry, self._push),
            # TXT 검토·복사 작업대(v6 S7, 재작성 F6) — 「문서 만들기」에서 TXT 작업을 실행하면
            # 여기로 온다. 대상 글꼴(TargetFontSetting)은 앱 전역 영속 선언의 단일 실체다.
            WorkbenchController(job_registry, self._push, clock=datetime.now,
                                target_font=target_font),
        ]
        # 에디터의 템플릿 라이브러리 = tpl 화면의 VM **같은 인스턴스**:
        # 별도 인스턴스면 두 표면의 스캔 캐시가 갈라져(가져오기·삭제가 한쪽에만 반영) 신규
        # 1단계 피커가 관리 화면과 다른 목록을 조용히 보인다(라이브러리=단일 실체).
        tpl_ctrl = next(c for c in controllers if c.name == "tpl")
        controllers.insert(
            2,
            EditorController(
                job_registry, self._push,
                clock=datetime.now,
                # (pool_registry 주입은 #347 에서 제거 — 자동등록·기본 데이터 재진술 사망.)
                template_library=tpl_ctrl.vm,
                # 1단계 피커 그룹 구획 = tpl 화면과 **같은 hwpx 그룹 모델**:
                # 별도 인스턴스면 접힘·지정 인메모리 캐시가 갈라져 두 표면이 다른 조직을 보인다.
                template_groups=tpl_ctrl.hwpx_groups,
                # TXT 밴드(F6 PR-B — 「기안」 화면 사망의 생성 경로 승계처)도 같은 단일 실체:
                # TXT 레지스트리·그룹 모델을 tpl 화면과 공유한다(가져오기·접힘이 함께 반영).
                text_registry=registry,
                txt_groups=txt_groups,
                # 라이브러리 결과 재진술 줄(F8 — `#tplResult` 승계): 성형·수명은 tpl 컨트롤러가
                # 계속 소유하고 편집기 스냅샷은 읽기만 한다(성형 두 벌 금지 — §10.17.2 판정 B).
                library_result=lambda: {
                    "text": tpl_ctrl.result_text, "level": tpl_ctrl.result_level,
                },
            ),
        )
        self.controllers = {c.name: c for c in controllers}
        # 라이브러리 삭제의 타 화면 무장 세션 가드 배선(#268 리뷰) — 라이브러리가 「문서
        # 만들기」보다 먼저 생성되므로 사후 주입. 삭제는 이 조회로 무장 세션을 먼저 묻는다.
        # (「기안」 가드는 화면 사망(F6 PR-B)과 함께 걷혔다 — 작업대는 몰입 표면이라
        # 라이브러리와 동시에 보이지 않고, 진입 자체가 「문서 만들기」 세션을 지난다.)
        # 작업대 배선(F6) — 「문서 만들기」가 진입 판정을 내고 세션 개시만 위임한다.
        # 컨트롤러 객체가 아니라 **handoff callable** 을 결선한다(P2-24): 화면 간 결합은
        # 이 조립부의 한 줄뿐이고, 「문서 만들기」는 작업대의 형체를 모른다.
        self.controllers["job"].workbench_open = self.controllers["workbench"].open
        self.controllers["library"].session_guards = [
            self.controllers["job"].session_guard_for,
        ]

    def _controller(self, screen: str):
        try:
            return self.controllers[screen]
        except KeyError:  # confirm-or-alarm: 미등록 화면은 시끄럽게.
            raise ValueError(f"등록되지 않은 화면: {screen!r}") from None

    # -------------------------------------------------- 관측 푸시(Python→웹)
    def _push(self, screen: str, snapshot: dict) -> None:
        """제품 공개 경계 하나로만 나간다(N-07 · D-06) — 내부 이름 `window.__push` 는 모른다.

        종전과 같이 **발사 후 망각**이다: 반환을 검사하지 않는다. 느린 렌더러에서 ack 를
        기다리기 시작하면 이 스레드가 화면 갱신마다 매달린다.
        """
        if self._window is None:
            return
        product_api.ProductApiClient.for_window(self._window).push(screen, snapshot)

    # -------------------------------------------------- 웹→Python (js_api)
    def initial(self, screen: str) -> dict:
        """화면 부팅 시 웹이 1회 당겨 가는 초기 상태."""
        return self._controller(screen).initial()

    def dispatch(self, screen: str, action: str, payload: "dict | None" = None):
        """순수 데이터 액션(창 불필요) 라우팅.

        ``ValueError`` 는 pywebview 자체 예외 왕복에 맡기지 않는다. 그 경로는 Python 작업
        스레드가 traceback 을 만든 뒤 UI 스레드의 ``evaluate_js`` 를 동기로 다시 불러 Promise
        rejection 을 완성한다. 패키징 CI 의 상승 실행에서는 정상적인 거절 두 건이 그 콜백에서
        멎어 프로브 시한을 소진했다. 그래서 예상 가능한 도메인/스키마 거절만 성공 transport 의
        작은 봉투로 보내고, 프런트 단일 브리지가 즉시 같은 Promise rejection 으로 복원한다.

        성공값은 종전처럼 그대로 반환하고, 예상 밖 예외도 감싸지 않는다. 후자는 pywebview 로그와
        traceback 을 잃지 않아야 실제 결함이 정상 거절로 위장하지 않는다.
        """
        try:
            checked = validate_dispatch(screen, action, {} if payload is None else payload)
            return self._controller(screen).dispatch(action, checked)
        except ValueError as exc:
            return {
                _DISPATCH_REJECTION_KEY: {
                    "name": type(exc).__name__,
                    "message": str(exc),
                }
            }

    def set_theme(self, mode: str) -> str:
        """테마 선택 영속 — 프런트 토글이 부른다(#74). 확정값 반환(비유효는 ValueError)."""
        settings.save_theme(mode)
        return mode

    def set_font_scale(self, scale: str) -> str:
        """앱 전역 글자 배율 영속 — 브라우저 줌 대신 예측 가능한 3단계 앱 배율."""
        settings.save_font_scale(scale)
        return scale

    # ``set_rail_collapsed`` 는 레일 사망(F2 PR-B)과 함께 제거 — 브리지 표면에 남으면
    # 표면 없는 설정을 쓰는 통로가 되고, 그 통로가 다음 세션에 레일을 되살린다.

    def set_master_width(self, width: int) -> int:
        settings.save_master_width(width)
        return width

    # 바깥 파일의 유일 입구는 import_template_file(가져오기=복사)이다.
    def import_template_file(self, screen: str) -> "str | None":
        """Win32 열기 다이얼로그(HWPX·TXT) → 라이브러리 복사 → 편집기 채택 판정(F8 통일).

        가져오기 통일(§10.17.2 판정 C): **복사 권위는 tpl 컨트롤러의 import_into_library
        하나**(잠금·매체 라우팅·충돌 접미·무잔재)이고, 편집기는 사본으로 세션을 시작할 수
        있는지만 판정한다(RAW·손상 = 목록 합류 + 수선 경로 notice). 실패는 ``ERROR:`` 접두.
        """
        path = _file_dialog(_LIBRARY_IMPORT_FILTERS)
        if not path:
            return None
        try:
            dest = self._controller("tpl").import_into_library(path)
            return self._controller(screen).adopt_imported_template(dest)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"

    def import_templates_folder(
        self,
        folder: "str | None" = None,
        confirm: bool = False,
        files: "list[str] | None" = None,
    ) -> "dict | None":
        """「폴더에서 가져오기…」(#339 · U2 §2.16 narrow) — 직속 .hwpx/.txt 일괄 등록.

        2왕복 계약: ①무인자 = 폴더 피커 → **읽기 전용 스캔** → 재진술 dict(``needs_confirm``
        + 후보 ``files``) — 확정 전에는 홈에 아무것도 쓰지 않는다. ②``folder``+``files``+
        ``confirm`` = 실행 — 재스캔이 아니라 **확정 시점 후보 목록에 결속**된다(PR #355
        리뷰: 스캔~확정 사이 폴더가 바뀌어도 확인 안 된 파일이 따라 들어오지 않고, 사라진
        확정 건은 부분 실패로 사유 병기). 복사 권위는 단건(:meth:`import_template_file`)과
        같은 tpl 복사 몸통의 반복(잠금·매체 라우팅·충돌 번호 접미·무잔재)이고 **채택은
        없다**(편집 세션 무변경 — 웹도 새-세션 확인을 걸지 않는다).

        직접 브리지 메서드(action registry 밖)라 payload 검증은 본문 소유: 실행 호출은
        ``confirm`` 명시 + 비어 있지 않은 문자열 ``folder`` + 문자열 목록 ``files`` 필수
        (재진술 없이 임의 폴더·임의 목록을 바로 실행하는 경로 차단) — 폴더 실재와 항목
        형태(basename·허용 확장자)는 tpl 권위가 loud 검증한다. 반환은 처음부터 dict 계약
        (실패 = ``{"ok": False, "error": …}``), ``None`` = 피커 취소.
        """
        tpl = self._controller("tpl")
        if folder is None:
            path = _folder_dialog("가져올 템플릿 폴더 선택")
            if not path:
                return None
            try:
                return tpl.scan_import_folder(path)
            except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
                return {"ok": False, "error": str(exc)}
        if not confirm:  # confirm-or-alarm: 재진술을 지나지 않은 실행은 시끄럽게 거절.
            raise ValueError("재진술 확정 없이 폴더 실행을 부를 수 없습니다(confirm 필수).")
        if not isinstance(folder, str) or not folder.strip():
            raise ValueError("폴더 경로가 비어 있습니다.")
        if not isinstance(files, list) or not files:
            raise ValueError("확정된 가져오기 목록이 없습니다 — 스캔 재진술을 먼저 받으세요.")
        try:
            return tpl.import_folder(folder, files)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return {"ok": False, "error": str(exc)}
    def _mount_descriptor(self, screen: str, path: str, sheet: str = "") -> dict:
        """마운트 성사 descriptor(U2 §2.7 3행) — ``label·path·sheet·rows``.

        마운트한 **그 호출이 결과를 말한다**: 종전엔 파일명 문자열만 돌려줘 「이 데이터
        고정」이 서는 데 필요한 path 를 웹이 다음 pool/job 푸시 도착에서 주워야 했다 —
        발신 순서에 기대는 배선([[bridge-call-ordering-contract]] 결함류). label 은
        :func:`~hwpxfiller.webapp.screens.source_label` 합성 그대로(링2 재조립 금지).
        """
        controller = self._controller(screen)
        return {
            "label": source_label("file", Path(path).name),
            "path": path,
            "sheet": sheet,
            "rows": len(getattr(controller, "records", []) or []),
        }

    def pick_data_file(self, screen: str) -> "str | dict | None":
        """Win32 파일 다이얼로그 → 링1 VM 로드. 실패는 ``ERROR:`` 접두로 시끄럽게 반환.

        다중 시트 워크북이면 **조용히 첫 시트를 쓰지 않는다**(#33) — 로드를 미루고 시트
        목록을 실은 ``{"needs_sheet": True, ...}`` 를 돌려줘 웹이 시트를 확정받게 한다.
        확정된 시트로의 실제 로드는 :meth:`load_data_sheet` 가 담당한다.

        성사 반환은 **descriptor**(``label·path·sheet·rows``, U2 §2.7 3행)다 — 데이터
        선택 면이 닫히지 않고 「현재 데이터」를 재진술하려면 이 호출의 결과만으로 고정
        버튼(`origin==="file" && path`)이 서야 한다.
        """
        log(f"pick_data_file: enter screen={screen}")
        filters = _EXCEL_OR_ANY_FILTERS
        path = _file_dialog(filters)
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
        return self._mount_descriptor(screen, path)

    def load_data_sheet(self, screen: str, path: str, sheet: str) -> "str | dict | None":
        """웹에서 확정한 시트로 데이터 로드(#33) — 다중 시트 확정 게이트의 착지 지점.

        ``sheet`` 는 반드시 해당 워크북의 **실제 시트명**이어야 한다 — 모르는 이름을 조용히
        첫 시트로 강등하지 않고 시끄럽게 거절한다(confirm-or-alarm). 실패는 ``ERROR:`` 접두.
        시트 재조회(sheet_overview)도 로드와 같은 예외 변환 경계 안에 둔다 — 모달을 연 뒤
        파일이 사라지거나 잠기면 그 실패도 웹에 시끄럽게 되돌린다(P2).
        성사 반환은 :meth:`pick_data_file` 과 같은 descriptor(U2 §2.7 3행)다.
        """
        try:
            names = [n for n, _r, _c in sheet_overview(path)]
            if sheet not in names:
                return f"ERROR: '{sheet}' 시트를 찾을 수 없습니다. 시트를 다시 선택하세요."
            self._controller(screen).load_data_path(path, sheet=sheet)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return self._mount_descriptor(screen, path, sheet)

    def copy_clipboard(self, screen: str, token: "str | None" = None) -> dict:
        """작업점 카드 렌더를 OS 클립보드로 — 거래는 **컨트롤러가 원자로 소유**한다(5R P1).

        **확인 대상 = 복사 대상**(F6 3R P1): ``token`` 은 웹이 사전확인한 카드의 정체
        (작업점 + 지금 규칙)이고, 컨트롤러의 :meth:`copy_to` 가 잠금 안에서 대조→렌더→
        쓰기→전진을 한 거래로 밟는다. 브리지는 OS 쓰기 함수만 건넨다.

        「기안」 사망(F6 PR-B)으로 소비자는 작업대 하나다 — 종전의 비-원자 폴백(render/
        can_copy/note_copied 네 걸음)은 소비자 0 이라 걷었다. 거래 없는 화면의 호출은
        오배선이므로 loud 거절한다(조용한 반쪽 복사 금지).
        """
        atomic = getattr(self._controller(screen), "copy_to", None)
        if atomic is None:
            raise ValueError(f"'{screen}' 화면은 클립보드 복사 거래를 소유하지 않습니다.")
        return atomic(token or "", set_clipboard_text)

    def pick_output_folder(self, screen: str) -> "str | None":
        """Win32 폴더 피커(SHBrowseForFolder) → 저장 폴더 지정. 「작업」 세션 패널의 네이티브 표면.

        선택 경로의 표시명 또는 None(취소). 실패는 ``ERROR:`` 접두로 시끄럽게 반환.
        """
        path = _folder_dialog("저장 폴더 선택")
        if not path:
            return None
        try:
            self._controller(screen).set_output_folder(path)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return path

    def generate(
        self, screen: str, confirm_overwrite: bool = False, run_token: str = "",
    ) -> dict:
        """세션 패널(screen 파라미터) 동기 생성 — 게이트 판정·덮어쓰기 재진술·결과 요약 dict.

        ``run_token`` 은 호출자가 낸 불투명 상관 문자열이다 — 컨트롤러가 판정에 쓰지 않고
        direct 반환·진행 델타에 그대로 되돌린다(R4-03). 생략하면 ``""``.
        """
        return self._controller(screen).generate(
            confirm_overwrite=bool(confirm_overwrite),
            run_token=run_token if isinstance(run_token, str) else "",
        )

    # (import_library_template 브리지는 tpl 화면과 함께 사망(F8) — 소비자 0 인 통로는 남기지
    #  않는다(F2 PR-B set_rail_collapsed 선례). 유일 가져오기 = import_template_file(통일,
    #  §10.17.2 판정 C — 복사 권위는 여전히 TemplateController.import_into_library).)

    def editor_has_unsaved_work(self) -> bool:
        """에디터에 진행 중인(미저장) 작업 세션이 있는가 — 크로스스크린 진입 전 폐기 확인용(#25)."""
        return self._controller("editor").has_unsaved_work()

    def close_guard_state(self) -> dict:
        """창 종료로 사라질 세션 상태를 한 시점에 판정한다(#218 G1).

        **참여는 프로토콜이지 명단이 아니다**(F6 1R P2 근본 조치). 종전에는 화면 이름 셋을
        손으로 셌고, 그래서 새 컨트롤러(작업대)가 미저장 매핑·복사 진행을 들고 있어도 창을
        닫으면 **무경보로 사라졌다** — 가드의 완전성이 「누가 이 목록을 갱신했는가」에 걸려
        있었다는 뜻이다. 이제 컨트롤러가 :meth:`close_guard_reason` 을 구현하면 자동으로
        참여한다: 다음 세션 표면은 여기 손댈 필요가 없고, 구현을 빠뜨리면 그건 **선언된
        비참여**다(조용한 무시와 다르다 — 아래 테스트가 그 선언을 센다).

        순서는 컨트롤러 등록 순서다(`self.controllers` 삽입 순) — 결정적이면 충분하고,
        어느 것이 먼저인지는 이 문안이 답할 질문이 아니다.
        """
        reasons: list[str] = []
        for controller in self.controllers.values():
            reason_of = getattr(controller, "close_guard_reason", None)
            if reason_of is None:
                continue
            reason = reason_of()
            if reason:
                reasons.append(reason)
        return {"armed": bool(reasons), "reasons": reasons}

    def _show_close_prompt(self, state: dict) -> None:
        """closing 콜백 바깥 스레드에서 웹 확인창을 연다(WinForms UI 재진입 회피).

        종전 표현(``window.AppCloseGuard && window.AppCloseGuard.prompt(…)``)은 가드 **부재를
        falsy 무동작으로 삼켰다** — 확인창이 안 뜬 채 창만 남고 아무도 그 사실을 몰랐다.
        제품 경계는 부재를 구조화된 실패로 돌려주므로 여기서 시끄럽게 만든다. 실패 시
        처분은 종전 그대로 **안전측**이다: 창 유지 + 대기 해제 + 내구성 경보(fail-open 금지).
        """
        if self._window is None:
            self._close_prompt_open = False
            return
        try:
            outcome = product_api.ProductApiClient.for_window(self._window).close_request(state)
            outcome.raise_for_failure()
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
        """데이터 고정·등록 모달 '찾아보기' → **경로만** 반환(#26 #4).

        ``pick_data_file`` 과 달리 어떤 컨트롤러에도 로드하지 않는다 — 등록은 참조
        저장이지 데이터 로드가 아니다(행 미저장 불변식). None = 취소.
        """
        filters = _EXCEL_OR_ANY_FILTERS
        return _file_dialog(filters)

    def pick_template_path(self) -> "str | None":
        """템플릿 다시 연결(#67) '찾아보기' → **경로만** 반환(``pick_pool_data_file`` 미러).

        ``import_template_file`` 과 달리 어떤 컨트롤러에도 로드하지 않는다 — 재연결의
        검증·확정은 dispatch(``relink_template``)의 confirm 게이트가 담당. None = 취소.
        """
        return _file_dialog(_TEMPLATE_FILTERS)

    def reveal_corrupt_job(self, path: str) -> "str | None":
        """홈 손상 카드 '폴더 열기' → 탐색기에서 해당 파일 표시(#26 #8 해소 동선).

        경로는 홈 컨트롤러의 손상 목록 화이트리스트로 검증한다 — 웹 페이로드로 임의
        경로를 여는 통로를 봉쇄. 실패는 ``ERROR:`` 접두.
        """
        try:
            target = self._controller("library").validate_corrupt_path(path)
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

    def open_job_in_editor(self, name: str, context: "dict | None" = None) -> "str | None":
        """저장된 작업을 **진입 문맥과 함께** 편집 세션으로 연다(계약 §5.1, 재작성 F7).

        웹은 이 호출 후 편집기 화면으로 전환한다. 실패(작업 손상·템플릿 부재·RAW·**미배선
        진입 사유**)는 ``ERROR:`` 접두로 시끄럽게 반환 — 사유를 조용히 `voluntary` 로
        떨어뜨리면 배너가 아무 말도 못 하는 진입이 생긴다. 미저장 세션 확인은 웹이
        ``editor_has_unsaved_work`` 로 선판단한다(#25 미러).

        ``context`` = ``{entry_reason, evidence, return_context, section, target}``. 기본값
        (빈 사전)은 자발적 진입이고 그때는 배너 자체가 서지 않는다(할 말이 없으면 침묵).
        ``section`` 은 deep-link 의 **거친 형태**(어느 탭인가), ``target`` 은 필드 단위
        deep-link(§10.14.3 — ``binding/<fieldId>`` / ``filename/filenamePattern``)다.
        target 이 서면 착지 탭도 target 이 정한다(load_job 소관).
        """
        ctx = context or {}
        try:
            # **진행 중 런과 겹치는 진입은 거절한다**(9R P1). `setBusy()` 는 「문서 만들기」
            # 루트 아래만 비활성화하므로 상단 탭·라이브러리 컨트롤은 생성 중에도 눌린다 —
            # 여기서 열면 진행 중 배치가 고정한 옛 vm 과 무관하게 durable 규칙이 저장되고,
            # 그 배치의 결과가 **디스크에 없는 세대**를 자기 근거로 댄다(§13-7). 판정은
            # 「문서 만들기」가 소유한 단일 술어를 쓴다(자물쇠는 앱이 공유 주입).
            self._controller("job").raise_if_generating("편집기를 여세요")
            self._controller("editor").load_job(
                name,
                landing_section=str(ctx.get("section") or SECTION_BINDING),
                entry_reason=str(ctx.get("entry_reason") or "voluntary"),
                evidence=ctx.get("evidence"),
                return_context=ctx.get("return_context"),
                target=str(ctx.get("target") or ""),
            )
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return name

    def new_job_from_data(self, context: "dict | None" = None) -> "str | None":
        """「문서 만들기」의 **마운트 데이터를 든 채** 신규 작업 마법사를 연다(U2 §2.4·§4 E).

        데이터의 정체를 웹이 실어 보내지 않고 여기서 「문서 만들기」 컨트롤러에 **되묻는**
        이유: 그 화면이 지금 무엇을 마운트하고 있는지의 단일 출처는 그 컨트롤러이고, 웹이
        기억한 값을 실으면 스냅샷 도착 순서에 따라 **다른 파일로 작업을 시작**할 수 있다
        ([[bridge-call-ordering-contract]] 결함류). 되묻는 창구는 ``new_work_handoff``
        하나이고 **버튼의 가부와 같은 판정**이다(#349 리뷰 P1) — 여기서 `data_path` 만 보고
        따로 판정하면, 파일이 아닌 마운트(조립 파이프라인 등록분)에서 화면은 「누를 수 있다」고
        그려 놓고 백엔드는 「데이터가 없다」고 거절하는 어긋남이 난다. 열 수 없으면 조용히 빈
        마법사를 열지 않고 그 사유를 그대로 되돌린다.

        ``context`` = ``{entry_reason, evidence, return_context}``(계약 §5.1) — 보낸 표면이
        자기가 본 것을 싣는다. 미배선 사유·미지 복귀 표면은 링1 이 fail-closed 로 거절하고
        그 거절은 ``ERROR:`` 로 되돌아간다(조용한 `voluntary` 강등 금지).
        """
        ctx = context or {}
        job = self._controller("job")
        try:
            # 진행 중 런과 겹치는 진입 거절은 `open_job_in_editor` 와 같은 술어다.
            job.raise_if_generating("새 작업을 시작하세요")
            source_ref, blocked = job.new_work_handoff()
            if blocked:
                raise ValueError(blocked)
            self._controller("editor").new_draft_with_data(
                source_ref,
                entry_reason=str(ctx.get("entry_reason") or "voluntary"),
                evidence=ctx.get("evidence"),
                return_context=ctx.get("return_context"),
            )
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return str(source_ref.get("path") or "")

    # (load_template_into_editor 브리지는 tpl 화면과 함께 사망(F8) — 크로스스크린 「이
    #  서식으로 새 작업」의 발신 표면이 죽어 소비자 0. 편집기 안 선택은 dispatch
    #  use_library_template(같은 new_job_session seam + assert_library_path)가 소유한다.)


# ------------------------------------------------------------- 자가검증 드라이버
# N-09: 이 자리에 있던 **JS 프로브 상수 28개(139,206자)와 `evaluate_js` 호출 71곳**이 전부
# 사라졌다. UI 내부 계측은 이제 프런트가 소유하고(`frontend/src/selftest/probes/` 45개 +
# `runner.js`), 파이썬은 버전 있는 뿌리 하나 `window.__hwpxTest.run(...)` 으로 **구조화된
# 요청과 결과만** 다룬다. 표현식 조립·호스트 연산 허용목록·결과 판정은 `selftest_api.py` 가
# 소유하므로 이 파일은 JS 문자열을 손으로 잇지 않는다.
#
# 여기 남는 `evaluate_js` 는 **문서 밖**을 재는 둘뿐이고, 둘 다 제품 화면·DOM id·서비스
# 이름을 한 글자도 담지 않는다(그 부재를 `tests/test_web_runtime_artifact.py` 가 센다):
#
#   ① `window_geometry` 호스트 연산 — 네이티브 OS 창 프레임(screenX·outerWidth·screen.avail*).
#      pywebview 가 이 값을 달리 노출하지 않아 평가기가 유일한 통로다. N-08 이 이 op 를
#      `owner: "host"` 로 못박은 이유가 그것이다(문서 안은 프런트, 문서 밖은 호스트).
#   ② 비노출 음성 대조 — **부재를 묻는 질문**이라 구조적으로 파사드를 지날 수 없다.
#      `typeof` 만 쓰고 아무것도 호출하지 않는다.


def _write_selftest_output(result: "Mapping[str, object]") -> Path:
    """증거를 결정적 위치에 쓴다 — 종료와 **분리된** 절반이다.

    출력 경로: 테스트 하네스(#30 접근 A)가 ``HWPX_SELFTEST_OUT`` 로 결정적 위치를 준다.
    미설정 시 동결 exe 옆(dist) — 기존 부팅 자가검증 거동 불변.
    """
    out_override = os.environ.get("HWPX_SELFTEST_OUT")
    out = (
        Path(out_override)
        if out_override
        else Path(sys.executable).resolve().parent / "selftest_result.json"
    )
    out.write_text(json.dumps(dict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _live_terminator(
    window: "object", write_output: "Callable[[Mapping[str, object]], object]"
) -> "Callable[[Mapping[str, object]], None]":
    """라이브 실행의 종결자 — 증거 쓰기 **다음** 정식 종료, 각각 정확히 한 번.

    종전의 합친 이름 ``_finish_selftest`` 를 대신한다. 그 이름은 캡처 하니스가 자기 드라이브
    끝에서 **직접 부르려고** 남아 있었고, 그래서 101 경로만 호스트 연산 허용목록을 통째로
    비껴갔다(쓰기 payload 검증도, 이중 종료 거절도 그 경로엔 없었다). 이제 두 실행이 같은
    :class:`~.selftest_api.HostOperations` 를 지난다 — 표에 있는데 아무도 부르지 않는 op 는
    선언만 살고 결과가 죽는 자리가 되므로, 소비자를 늘리는 쪽이 옳다.

    **1회성은 거래 전체가 진다**(#425 리뷰 P2). op 각각의 가드에 기대면 두 번째 호출이 쓰기를
    먼저 통과해 **첫 증거를 덮어쓴 뒤** 종료 거절 로그만 남긴다 — 실행의 결론이 조용히 바뀌고,
    그 자리에 남는 것은 "종료를 두 번 불렀다"는 엉뚱한 진단뿐이다. 종결은 실행 하나의 결론을
    확정하는 사건이라 그 결론은 **처음 것**이다.

    실패를 삼키지 않는다 — 그리고 **내구성 채널**로 삼키지 않는다. 종전 두 실패는
    :func:`~hwpxfiller.host.native.debug.log` 로 갔는데 그것은 ``HWPX_WEBAPP_LOG`` 가 없으면 no-op
    이라, "사유를 stderr 로라도 남긴다"고 적힌 주석이 실제로는 아무 데도 안 남기고 있었다.
    종결의 실패는 하니스가 **파일 부재로만** 만나는 사건이라 사유가 없으면 원인이 한 겹
    가려진다. 그래서 :func:`.settings.alert`(stderr + 홈 로그)를 쓴다.
    """
    operations = selftest_api.HostOperations(
        write_output=write_output,
        destroy=lambda: window.destroy(),  # type: ignore[attr-defined]
    )
    consumed: "list[list[str]]" = []

    def finish(result: "Mapping[str, object]") -> None:
        if consumed:
            settings.alert(
                "live-run 종결이 두 번 요청됐습니다(already_consumed) — "
                f"확정된 결론은 {consumed[0]!r} 이고 버린 것은 {sorted(map(str, result))!r}"
            )
            return
        consumed.append(sorted(map(str, result)))
        written = operations.dispatch("output_write", {"result": dict(result)})
        if not written.ok:
            settings.alert(f"live-run output_write 실패: [{written.code}] {written.detail}")
        destroyed = operations.dispatch("window_destroy")
        if not destroyed.ok:
            settings.alert(f"live-run window_destroy 실패: [{destroyed.code}] {destroyed.detail}")

    return finish


def _selftest_artifact_identity(launched_artifact: VerifiedWebArtifact) -> dict:
    """``artifact_identity`` 호스트 연산 — 정체를 **다시 풀어** 창 생성 이후의 교체를 거절한다.

    종전 ``_runtime_selftest_evidence`` 의 호스트 절반이다. 나머지 절반(같은 오리진 판정·
    금지 자원·외부 fetch 대조)은 문서 안이라 프런트 ``runtime`` 프로브가 승계했다.

    교체를 발견하면 **예외**로 올린다 — 구조화된 거절로 접으면 "정체가 바뀌었다"가 프로브
    실패 하나로 뭉개진다. 이건 그 층에서 삼킬 사건이 아니다.
    """
    current_artifact = web_artifact()
    if (
        current_artifact.artifact_id != launched_artifact.artifact_id
        or current_artifact.tree_sha256 != launched_artifact.tree_sha256
    ):
        raise WebArtifactViolation(
            "web artifact changed after the product window was created"
        )
    return {
        "artifact_id": launched_artifact.artifact_id,
        "tree_sha256": launched_artifact.tree_sha256,
    }


#: 네이티브 창 프레임 측정 — 문서 **밖**이라 호스트가 진다. 제품 이름이 없는 표현식이다.
_WINDOW_GEOMETRY_JS = (
    "({x:screenX,y:screenY,width:outerWidth,height:outerHeight,"
    "avail_x:screen.availLeft||0,avail_y:screen.availTop||0,"
    "avail_width:screen.availWidth,avail_height:screen.availHeight})"
)

#: 전역 allowlist 실측(N-10) — 창이 실제로 들고 있는 own 전역을 재되 **작게** 낸다.
#: DOM 을 건드리지 않고 읽기만 한다.
#:
#: 두 번의 설계 실패가 이 모양을 정했고, 둘 다 **계측이 관측 대상을 바꾼** 사례다.
#:
#: ① 같은 오리진 ``about:blank`` iframe 으로 "엔진이 원래 주는 것"의 기준선을 떠 차집합을
#:    냈다. 측정은 정확했지만(엔진 own 1228 기준선) iframe 부착이 서브프레임 항법을 일으키고,
#:    pywebview 의 ``loaded`` 가 UI 스레드에서 테마 주입·``show()`` 를 다시 탄다. 동기로
#:    붙들고 있던 ``evaluate_js`` 와 맞물려 창이 멈췄다 — 전체 스위트 **3회 실행 3회** 90s
#:    시한 초과. 손대지 않은 기준선(``9a5f554``)은 같은 기계에서 2410 passed 로 깨끗했다.
#: ② iframe 을 걷고 이름 **목록 전수**(1232개)를 그대로 돌려줬다. 단독 실행은 6/6 정상인데
#:    pytest 가 파이프로 잡고 띄우면 매달렸다. 큰 배열을 ``pywebview.stringify`` 로 접어
#:    다리 너머로 보내는 값이 그만큼이다.
#:
#: 그래서 판정에 필요한 것만 낸다: 수량, ``__hwpx`` 이름공간 전수, 은퇴 별칭 27의 잔존, 그리고
#: 이름 **집합의 정체**를 접은 digest 둘. ``digest_without_test`` 는 ``__hwpxTest`` 를 뺀
#: 집합의 정체라, 능력 있는 창의 그것이 능력 없는 창의 ``digest`` 와 같으면 **두 집합이
#: ``__hwpxTest`` 하나만 다르다**가 정확히 성립한다(D-07). 수량 비교만으로는 하나가 사라지고
#: 둘이 생긴 경우를 놓치는데, digest 는 그것을 잡는다.
#:
#: 엔진 전역 목록을 저장소에 못박는 길은 택하지 않았다 — CI 의 WebView2 판이 다르면 제품과
#: 무관한 이유로 빨개진다. 그 대가로 **임의 이름의 런타임 누수**는 이 층이 절대적으로는 잡지
#: 못하고, 정적 AST 게이트(``tests/js/n10_global_hygiene.test.js``)가 진다.
_GLOBAL_DELTA_FN = r"""function () {
  var RETIRED = ['AppCloseGuard','Bridge','Copy','DataPicker','DataZone','EditorEntry',
    'EditorScreen','GroupList','Guard','Intent','JobScreen','LibraryScreen','Modal','Nav',
    'PathTrack','Personalization','Popover','Preserve','Relink','SegView','SheetPicker',
    'SurfaceSheet','Theme','UndoToast','WorkbenchScreen','__push','escHtml'];
  var names = Object.getOwnPropertyNames(window).sort();
  var digest = function (list) {
    var h = 0x811c9dc5;
    for (var i = 0; i < list.length; i++) {
      var t = list[i];
      for (var j = 0; j < t.length; j++) {
        h ^= t.charCodeAt(j);
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
      }
      h ^= 10;
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h >>> 0;
  };
  var hwpx = [], retired = [], withoutTest = [];
  for (var i = 0; i < names.length; i++) {
    if (names[i].indexOf('__hwpx') === 0) { hwpx.push(names[i]); }
    if (RETIRED.indexOf(names[i]) !== -1) { retired.push(names[i]); }
    if (names[i] !== '__hwpxTest') { withoutTest.push(names[i]); }
  }
  return {
    total_own: names.length,
    hwpx_namespace: hwpx,
    retired_present: retired,
    digest: digest(names),
    digest_without_test: digest(withoutTest),
    has_document: names.indexOf('document') !== -1,
    has_location: names.indexOf('location') !== -1
  };
}"""

#: 능력 있는 창 전용 모드가 쓰는 단독 표현식 — 같은 함수 본문을 공유한다.
_GLOBAL_DELTA_JS = "(" + _GLOBAL_DELTA_FN + ")()"

#: 비노출 음성 대조 — ``typeof`` 만 쓰고 **아무것도 호출하지 않는다**. 쿼리·해시를 실제로
#: 얹은 뒤 다시 물어 "URL 로는 켜지지 않는다"를 실행으로 확인한다. 부재만 재면 "페이지가 안
#: 떴다"와 구별되지 않으므로 제품 API 존재를 **양성 대조**로 같은 창에서 함께 잰다.
#:
#: 이름 하나의 부재만 묻는다는 것이 이 상수의 한계다 — 전역 **전수**는 아래
#: :data:`_GLOBAL_DELTA_JS` 가 따로 잰다(N-10).
_NON_EXPOSURE_JS = r"""
(function () {
  var own = function () {
    return Object.prototype.hasOwnProperty.call(window, '__hwpxTest');
  };
  var out = {
    selftest_own: own(),
    selftest_typeof: typeof window.__hwpxTest,
    product_typeof: typeof window.__hwpx,
    host_claim_typeof: typeof (window.pywebview
      && window.pywebview.api && window.pywebview.api.selftest_claim)
  };
  /* 전역 전수는 **URL 을 만지기 전에**, 그리고 **같은 평가 안에서** 잰다.
     아래 replaceState 는 창의 주소를 바꾸고, 그 뒤에 두 번째 evaluate_js 를 보내면
     간헐적으로 응답이 오지 않는다 — 로컬 전체 스위트와 CI 에서 90s 시한 초과로 드러났다.
     그래서 이 모드의 평가는 **한 번**이고, 순서가 계약이다. */
  out.global_delta = (GLOBAL_DELTA_FN)();

  try {
    window.history.replaceState(null, '',
      window.location.pathname + '?selftest=1&hwpxTest=on#selftest');
    out.url_after = window.location.href;
    out.selftest_own_after_query_hash = own();
    out.selftest_typeof_after_query_hash = typeof window.__hwpxTest;
  } catch (e) {
    out.query_hash_error = String(e && e.message ? e.message : e);
  }
  return out;
})()
""".replace(
    "GLOBAL_DELTA_FN", _GLOBAL_DELTA_FN
)


#: 전역 allowlist 측정 전용 모드. **성공 모드가 아니다** — 프런트 엔진을 몰지 않고 능력이
#: **선** 창의 전역 전수만 잰다. ``no_capability`` 와 짝을 이뤄 "시험 실행이 더하는 전역은
#: 정확히 ``__hwpxTest`` 하나"를 뺄셈으로 묻는다(D-07).
#:
#: 왜 ``full`` 증거에 얹지 않고 모드를 따로 두는가: ``full``·쓰기 모드의 최상위 키 수는
#: ``packaging/build.ps1`` 의 책임 게이트(43)와 헤드리스 dict 동치 계약이 함께 못박은 값이다.
#: 측정 하나를 그 자루에 넣으면 릴리스 빌드가 터지고, 터지지 않게 숫자를 올리면 이번엔
#: "책임 42" 라는 계측점이 측정용 키 때문에 흐려진다. 재는 것과 재어지는 것을 섞지 않는다.
_MODE_GLOBAL_DELTA = "global_delta"

#: 음성 대조 전용 모드 이름. **성공 모드가 아니다** — 프런트 엔진을 돌리지 않고 능력 부재만
#: 잰다. 그래서 성공 모드 합집합(47키)에 들지 않는다.
_MODE_NO_CAPABILITY = "no_capability"

#: 모드 → 증거에 먼저 실리는 **에코 키**. 요청한 값 자체는 실행이 실패해도 남아야 한다
#: (무엇을 시도했는지 잃으면 실패를 읽을 수 없다) — 레거시가 결과 dict 를 그 키로 시작한
#: 이유가 그것이다.
_SELFTEST_ECHO_KEYS = {"theme_write": "theme_write", "font_scale_write": "font_scale_write"}

#: 파이썬 프로세스 예산(초). JS 실행 시한(기본 75s)보다 **길고** 게이트 하네스의 프로세스
#: 상한(90s, ``tests/test_web_selftest_gate.py``)보다 **짧다**. 순서가 계약이다: JS 가 먼저
#: 깨어 구조화된 실패를 주고, 그마저 안 오면 파이썬이 시끄럽게 끝내고, 하네스는 마지막
#: 그물이다. 어느 예산도 레거시보다 늘리지 않았다 — 레거시엔 실행 전체 상한이 아예 없었다.
_SELFTEST_BUDGET_S = 80.0


def _selftest_host_operations(
    window_of: "Callable[[], object]",
    artifact_of: "Callable[[], VerifiedWebArtifact]",
) -> "selftest_api.HostOperations":
    """프런트가 **요청할 수 있는** 호스트 표면. 창은 늦게 결속한다(파사드는 창보다 먼저 선다).

    주입은 정확히 여섯이고, 그래서 ``provides()`` 도 정확히 여섯이다 — 프로브 45개가 실제로
    요구하는 op 전수와 같다. 이 일치가 계약이다: 대지 못할 것을 댄다고 말하면 프로브가 계획
    단계에서 초록이었다가 실행에서 죽는다.

    **출력 쓰기와 창 종료는 여기 없다.** 그 둘은 드라이버 소유이고, 프런트에 대주면 페이지
    쪽에서 증거 파일을 쓰거나 창을 죽일 수 있는 통로가 된다. 능력 자체를 주지 않는 것이
    "요청은 거절된다"보다 강하다.
    """
    return selftest_api.HostOperations(
        resize=lambda width, height: window_of().resize(width, height),  # type: ignore[attr-defined]
        geometry=lambda: window_of().evaluate_js(_WINDOW_GEOMETRY_JS),  # type: ignore[attr-defined]
        current_url=lambda: window_of().get_current_url(),  # type: ignore[attr-defined]
        artifact_identity=lambda: _selftest_artifact_identity(artifact_of()),
        settings_source=settings,
        inputs={
            "theme": os.environ.get("HWPX_SELFTEST_SET_THEME", ""),
            "font_scale": os.environ.get("HWPX_SELFTEST_SET_FONT_SCALE", ""),
        },
    )


def _selftest_capability_wanted(
    run: "live_run.LiveRun | None", environ: "Mapping[str, str]"
) -> bool:
    """이 프로세스가 시험 능력을 **붙여야 하는가**.

    조건은 실행의 명시 선언(:attr:`~.live_run.LiveRun.capability`) 하나다. URL·빌드 플래그는
    여기 없다. 음성 대조 모드는 능력을 일부러 빼고 부팅해 "능력이 없으면 전역도 없다"를 실
    창에서 잰다.

    종전 조건은 ``"--selftest" in argv`` 라는 **문자열**이었다. 그래서 창을 빌리려는 다른
    소비자가 같은 플래그를 흉내 내는 순간 시험 능력까지 딸려 왔다 — 101 하니스가 정확히
    그랬고, 문서 스크린샷은 ``__hwpxTest`` 가 서 있는 창을 찍고 있었다. 두 질문("창을 빌려
    도는가" / "시험 표면이 필요한가")을 가르면 그 동반은 구조적으로 사라진다(#372 D-07).
    """
    return bool(run is not None and run.capability) and not environ.get(
        "HWPX_SELFTEST_NO_CAPABILITY"
    )


def _selftest_mode(environ: "Mapping[str, str]") -> "tuple[str, str]":
    """환경변수 → ``(모드, 입력값)``. 우선순위는 레거시 그대로다."""
    if environ.get("HWPX_SELFTEST_NO_CAPABILITY"):
        return _MODE_NO_CAPABILITY, ""
    if environ.get("HWPX_SELFTEST_GLOBAL_DELTA"):
        return _MODE_GLOBAL_DELTA, ""
    if environ.get("HWPX_SELFTEST_GEOMETRY_ONLY"):
        return "geometry_only", ""
    font_scale = environ.get("HWPX_SELFTEST_SET_FONT_SCALE")
    if font_scale:
        return "font_scale_write", font_scale
    theme = environ.get("HWPX_SELFTEST_SET_THEME")
    if theme:
        return "theme_write", theme
    return "full", ""


def _selftest_non_exposure_evidence(window: "object") -> dict:
    """음성 대조 모드 — 능력을 **붙이지 않은 채** 실 창에서 비노출을 잰다.

    정상 실행에는 드라이버가 없어(``webview.start()`` 에 함수를 주지 않는다) 창 안을
    들여다볼 길이 없다. 그렇다고 정상 경로에 관측용 통로를 새로 내면 그 통로 자체가 제품
    표면이 된다. 그래서 ``--selftest`` 의 드라이버는 빌리되 **파사드만 붙이지 않는다** —
    능력이 없을 때의 창은 정상 실행의 창과 같은 번들·같은 코드 경로다.
    """
    evidence: dict = {"mode": _MODE_NO_CAPABILITY}

    # 전역 델타 게이트의 **음성 대조**(N-10). 부재를 재는 계측은 자기가 부재를 볼 줄 아는지
    # 먼저 증명해야 한다 — 아무것도 못 보는 프로브도 "누수 0" 을 낸다(계측 층의 조용한 오류).
    # 그래서 시험 요청이 있으면 창에 이름 하나를 **일부러 심고** 게이트가 그것을 잡아내는지
    # 본다. 심는 자리는 selftest 드라이버이지 제품이 아니다: 정상 실행에는 이 코드로 가는
    # 길이 없고(`--selftest` + 전용 환경변수), 제품 번들은 한 글자도 달라지지 않는다.
    sentinel = os.environ.get("HWPX_SELFTEST_LEAK_SENTINEL")
    if sentinel:
        evidence["leak_sentinel"] = sentinel
        try:
            window.evaluate_js(  # type: ignore[attr-defined]
                f"(function () {{ window[{json.dumps(sentinel)}] = 1; return true; }})()"
            )
        except Exception as exc:  # noqa: BLE001 — 심지 못했으면 대조가 성립하지 않는다
            evidence["error"] = f"누수 파수꾼 설치 실패: {exc!r}"
            return evidence

    try:
        probed = window.evaluate_js(_NON_EXPOSURE_JS)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — 관측 실패를 성공으로 접지 않는다
        evidence["error"] = f"비노출 음성 대조 평가 실패: {exc!r}"
        return evidence
    if not isinstance(probed, Mapping):
        evidence["error"] = f"비노출 음성 대조 반환이 객체가 아니다: {probed!r}"
        return evidence
    # 한 번의 평가가 둘을 함께 낸다 — 갈라 담되 창은 한 번만 문다(위 상수 머리말).
    probed = dict(probed)
    evidence["global_delta"] = dict(probed.pop("global_delta", {}))
    evidence["non_exposure"] = probed
    return evidence


def _selftest_global_delta(window: "object") -> dict:
    """창이 실제로 들고 있는 own 전역 전수를 재 **제품이 더한 것**만 남긴다(N-10).

    두 모드가 같은 표현식을 쓴다: 능력 없는 실행과 능력 있는 시험 실행. 그래야 "시험 실행은
    정상 실행보다 정확히 ``__hwpxTest`` 하나가 많다"를 **뺄셈으로** 물을 수 있다(D-07).
    측정 실패를 성공으로 접지 않는다 — 사유를 그대로 실어 게이트가 읽게 한다.
    """
    try:
        probed = window.evaluate_js(_GLOBAL_DELTA_JS)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — 관측 실패를 성공으로 접지 않는다
        return {"added_globals_error": f"전역 델타 평가 실패: {exc!r}"}
    if not isinstance(probed, Mapping):
        return {"added_globals_error": f"전역 델타 반환이 객체가 아니다: {probed!r}"}
    return dict(probed)


def _selftest_live_run() -> "live_run.LiveRun":
    """부팅 자가검증 실행의 선언 — ``--selftest`` 가 고르는 **하나**.

    종전에는 이런 선언이 없었고 ``main()`` 이 모듈 전역 ``_selftest_drive`` 를 호출 시점에
    찾았다. 캡처 하니스는 그 자리를 갈아끼우는 방식으로 창을 빌렸고, 그래서 두 실행이 같은
    플래그·같은 전역·같은 종결 함수를 공유하면서도 **계약은 어디에도 없었다**.
    """
    return live_run.LiveRun(
        name="selftest",
        drive=_selftest_drive,
        write_output=_write_selftest_output,
        capability=True,
    )


def _selftest_context(
    window: "object", artifact: "VerifiedWebArtifact | None" = None
) -> "live_run.LiveContext":
    """자가검증 봉투 조립 — ``main()`` 과 단위 시험이 **같은 조립**을 쓴다.

    두 곳이 각자 봉투를 지으면 필드가 하나 늘 때 한쪽만 낡고, 그 낡음은 시험이 초록인 채로
    산다(이 파일이 고치고 있는 결함류 그 자체다).
    """
    return live_run.context_for(
        _selftest_live_run(),
        window=window,
        artifact=artifact,
        finish=_live_terminator(window, _write_selftest_output),
    )


def _selftest_drive(ctx: "live_run.LiveContext") -> None:
    """동결 exe 부팅 자가검증 — 프런트 엔진을 몰아 증거를 확정하고 정식 종료한다.

    인자는 :class:`~.live_run.LiveContext` **하나**다. 종전에는 pywebview 가 넘기는 위치 인자
    튜플을 그대로 받았고(``window``, 뒤에 ``launched_artifact`` 가 붙었다), 그 튜플이 길어진
    #375 에서 캡처 하니스의 드라이버와 조용히 어긋났다.

    ``ctx.artifact`` 는 여기서 **풀지 않는다**. 정체 재확인은 ``artifact_identity`` 호스트
    연산이 지고, 그 연산은 프런트 ``runtime`` 프로브(full 모드)만 요청한다 — 쓰기 모드가
    산출물 봉인을 요구하지 않던 레거시 거동 그대로다.

    쓰기 모드(``HWPX_SELFTEST_SET_THEME``·``HWPX_SELFTEST_SET_FONT_SCALE``)는 저장값을 심어
    다음 콜드부트의 오리진 비의존 영속 되읽기를 준비한다(#74).
    """
    window = ctx.window
    mode, echo_value = _selftest_mode(os.environ)

    if mode == _MODE_NO_CAPABILITY:
        ctx.finish(_selftest_non_exposure_evidence(window))
        return

    if mode == _MODE_GLOBAL_DELTA:
        # 능력이 선 창의 전역 전수만 잰다 — 프로브는 돌리지 않는다. 능력 설치는 비동기라
        # 준비를 먼저 기다린다: 한 번만 물으면 아직 안 선 상태를 "없다"로 확정하고, 그
        # 확정이 곧 "차이 0" 이라는 거짓 초록이 된다.
        probe_client = selftest_api.SelftestClient.for_window(
            window, budget_s=_SELFTEST_BUDGET_S, log=log
        )
        delta_evidence: dict = {"mode": _MODE_GLOBAL_DELTA}
        try:
            probe_client.await_readiness(probe_client.new_deadline())
        except Exception as exc:  # noqa: BLE001 — 능력 부재를 성공으로 접지 않는다
            delta_evidence["error"] = f"시험 능력 준비 실패: {exc!r}"
        else:
            delta_evidence["global_delta"] = _selftest_global_delta(window)
        ctx.finish(delta_evidence)
        return

    client = selftest_api.SelftestClient.for_window(
        window, budget_s=_SELFTEST_BUDGET_S, log=log
    )

    outcome = client.drive(
        mode,
        probe_input=echo_value or None,
        flags={"offlineProbe": bool(os.environ.get("HWPX_SELFTEST_OFFLINE_PROBE"))},
    )

    # 에코가 **먼저** 선다 — 실행이 실패해도 "무엇을 요청했는지"는 증거에 남아야 한다.
    evidence: dict = {}
    echo_key = _SELFTEST_ECHO_KEYS.get(mode)
    if echo_key is not None:
        evidence[echo_key] = echo_value
    if outcome.has_evidence:
        evidence.update(outcome.evidence or {})
    if not outcome.ok and "error" not in evidence:
        # 러너가 증거를 못 냈거나 프로토콜 단계에서 죽었다 — 조용히 통과시키지 않는다.
        evidence["error"] = outcome.alarm_text

    # 출력·종료는 드라이버 소유 책임이지만 **같은 허용목록**을 지난다 — 표에 있는데 아무도
    # 부르지 않는 op 는 선언만 살고 결과가 죽는 자리가 된다. 그 두 걸음의 순서·1회성은
    # :func:`_live_terminator` 가 지고, 101 하니스도 같은 종결자를 쓴다.
    ctx.finish(evidence)


# ------------------------------------------------------------------ 엔트리
def _alarm(msg: str, window: "object | None" = None) -> None:
    """부팅 경보 — 내구성 채널(stderr + 홈 로그, settings.alert) + (가능하면) JS alert.

    내구성 채널은 settings.alert 가 소유한다(홈 경로·경보 로그가 거기 있고, settings 층 코드도
    같은 채널로 알려야 한다 — 순환 import 회피). 이 함수는 그 위에 창(JS alert) 계층만 얹는다.
    JS alert 는 fire-and-forget — 미루기는 이제 파사드가 진다(``notice`` 처리기를 다음 태스크로
    넘긴다). evaluate_js 가 alert 해소를 기다리다 호출 스레드(loaded 핸들러·폴백 타이머)를
    매달지 않는다는 성질은 그대로다.

    창 계층의 실패로 **다시 경보하지 않는다** — 경보를 알리려다 경보를 내면 재귀한다.
    그래서 판정은 버린다(내구성 채널이 이미 권위 있게 기록했다)."""
    if window is None:
        settings.alert(msg)
        return
    product_api.ProductApiClient.for_window(window).notice(msg)


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


def main(
    argv: "Sequence[str] | None" = None,
    *,
    live: "live_run.LiveRun | None" = None,
) -> int:
    """제품 창 하나를 띄운다. ``live`` 가 주어지면 그 실행이 창을 몬다.

    ``argv`` 를 인자로 받는 이유는 하나다 — 종전 캡처 하니스는 ``sys.argv`` 를 통째로
    덮어써서(``[argv0, "--selftest"]``) 제품 ``main()`` 을 다시 불렀고, 그 변조는 프로세스
    전역이라 그 뒤의 어떤 코드도 원래 인자를 볼 수 없었다. 라이브 실행은 이제 ``live`` 로
    자기를 선언하고 프로세스 상태를 건드리지 않는다.
    """
    global _live_file_dialogs
    args = list(sys.argv if argv is None else argv)
    run = live if live is not None else (_selftest_live_run() if "--selftest" in args else None)
    if run is not None:
        live_run.validate(run)  # 계약 위반은 워커 스레드가 아니라 **여기서** 시끄럽다

    try:
        artifact = web_artifact()
    except (OSError, WebArtifactViolation) as exc:
        _alarm(f"웹 제품 산출물 검증 실패 — 창을 열지 않습니다: {exc}")
        return 2

    import webview

    log(
        "verified web artifact: "
        f"id={artifact.artifact_id} tree={artifact.tree_sha256} root={artifact.root}"
    )

    # 단일 인스턴스(이 홈 기준): 두 번째 실행은 기존 창을 앞으로 내고 조용히 종료한다. private_mode
    # 의 clear_user_data 가 동시 인스턴스 프로필을 밑에서 지우던 경합과, 그를 막으려던 per-pid
    # 프로필·부팅 스윕·profile.lock 기계 전부를 이 가드가 대체한다(#74 리뷰3). rc=0 = 정상 이중
    # 실행(오류 아님). 라이브 실행은 하네스 부팅(격리 홈, 순차 실행)이라 우회한다.
    if run is None:
        # 뮤텍스 핸들은 프로세스 종료 시 OS 가 회수하므로 파이썬 참조를 붙들 필요는 없다 —
        # None(=다른 인스턴스 보유)일 때만 분기하면 된다.
        if single_instance.acquire(settings.home_dir()) is None:
            single_instance.focus_existing(WINDOW_TITLE)
            return 0

    frontend = WebFrontend(default_text_templates_dir())

    # 시험 능력 부착(N-09 · D-07) — **실행이 명시로 요구할 때만**. 정상 실행의 `js_api` 에는
    # 시험 메서드가 아예 없고, 그래서 프런트의 `testHost.available()` 이 거짓이 되어
    # `window.__hwpxTest` 가 서지 않는다. 101 하니스처럼 창만 빌리는 실행도 마찬가지다.
    #
    # 창보다 **먼저** 붙인다: pywebview 는 페이지 로드 시점(`_pywebviewready`)에 `js_api` 의
    # 공개 메서드를 훑어 `pywebview.api` 를 만든다. 호스트 연산이 필요로 하는 `window` 는
    # 아래에서 대입되지만, 주입이 지연 호출 클로저라 호출 시점엔 이미 서 있다.
    if _selftest_capability_wanted(run, os.environ):
        selftest_api.attach_selftest_facade(
            frontend,
            selftest_api.SelftestHostFacade(
                _selftest_host_operations(lambda: window, lambda: artifact), log=log
            ),
        )

    saved_geometry = settings.load_window_geometry()
    if saved_geometry is not None and not _geometry_is_visible(saved_geometry):
        settings.alert("저장된 창 위치가 현재 화면 밖이라 기본 위치로 복원합니다")
        saved_geometry = None
    window = webview.create_window(
        WINDOW_TITLE,
        str(artifact.index_path),
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
            # 종전 두 왕복(개인화·테마)이 제품 경계의 `preferences` 하나로 접혔다(N-07).
            # 접었다고 **귀속을 잃지는 않는다**: 파사드가 실제로 적용한 조각 이름을 돌려주고
            # 판정이 빠진 이름을 지목하므로, "개인화가 죽었다"와 "테마가 죽었다"는 여전히
            # 다른 문장으로 나온다. 그 둘은 원인도 조치도 다르다.
            client = product_api.ProductApiClient.for_window(window)
            # 버전·능력을 **먼저 묻는다** — 미지 버전을 v1 로 강등해 조용히 절반만 적용하는
            # 경로를 만들지 않는다(D-06). 실패는 예외로 올라와 아래 except 가 받는다.
            client.describe((product_api.EVENT_PREFERENCES,))
            outcome = client.preferences(
                {
                    "font_scale": settings.load_font_scale(),
                    "master_width": settings.load_master_width(),
                },
                settings.load_theme(),
            )
            # 테마는 저장값이 light/dark 일 때만 실린다 — 그 판정은 payload 조립이 진다.
            # Theme.apply 경유라 data-theme 설정 + themechange 발신으로 레일 라벨까지 재동기된다.
            if not outcome.ok:
                err = outcome.failure_text
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
        if run is not None:
            # 인자 0개 콜러블 — `webview.start(fn)` 은 `args=None` 분기로 들어가 위치 인자를
            # 넘기지 않는다. 드라이버가 알아야 할 것은 전부 봉투 하나에 실린다(#423).
            _live_file_dialogs = run.file_dialogs
            entry = live_run.entrypoint(
                run,
                live_run.context_for(
                    run,
                    window=window,
                    artifact=artifact,
                    finish=_live_terminator(window, run.write_output),
                    # 위에서 **이미 무장한** 예산을 그대로 건넨다(#460 리뷰 P1). 드라이버가
                    # 다시 계산하면 아래 loaded 콜백이 먼저 쓴 완주 스탬프를 읽어, 콜드로
                    # 무장한 이 부팅을 웜 예산으로 재게 된다.
                    boot_budget_s=budget_seconds,
                    boot_budget_reason=budget_reason,
                ),
            )
            webview.start(entry, gui=gui, storage_path=str(storage_dir))
        else:
            webview.start(gui=gui, storage_path=str(storage_dir))
    finally:
        _live_file_dialogs = None  # 대체는 이 실행의 것이다 — 프로세스에 남기지 않는다
        timer.cancel()
        shutil.rmtree(storage_dir, ignore_errors=True)  # 자기 정리(크래시로 못 지우면 다음 부팅 청소)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
