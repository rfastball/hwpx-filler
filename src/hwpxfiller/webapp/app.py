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
from ..gui.edit_session import SECTION_BINDING  # 편집기 기본 착지 탭(계약 §5.1 어휘)
from ..gui.file_filters import EXCEL_FILTER_PATTERN  # 확장자 단일 출처(RC-34) — Qt-free 상수
from hwpxcore.native import single_instance
from hwpxcore.native._debug import log
from hwpxcore.native.clipboard import set_clipboard_text
from hwpxcore.native.dialogs import open_file_dialog, open_folder_dialog
from hwpxcore.native.reveal import open_path as _native_open_path
from hwpxcore.native.reveal import reveal_in_explorer as _native_reveal
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
                              generation_lock=generation_lock),
            # 「문서 만들기」 — 세션 패널(v6 screen-data 2열). 링1 VM 을 직접 소유하며
            # 실행 결정 계약을 소비하는 유일 세션 표면이다. TXT 레지스트리는 고지 ①
            # (후보 TXT 구획 빈 상태, F6 PR-B)의 술어 전용 — tpl·편집기와 같은 인스턴스.
            JobController(job_registry, self._push, pool_registry=pool_registry,
                          generation_lock=generation_lock, text_registry=registry),
            # 템플릿 관리(#13) — TXT 레지스트리는 편집기·「문서 만들기」와 공유(변경이 반영).
            TemplateController(registry, self._push, txt_groups=txt_groups),
            # 등록 데이터 참조·수명(#26 #4) — 화면은 사망하고 데이터 선택 다이얼로그가 소비(F1).
            PoolController(pool_registry, self._push),
            # TXT 검토·복사 작업대(v6 S7, 재작성 F6) — 「문서 만들기」에서 TXT 작업을 실행하면
            # 여기로 온다. 대상 글꼴(TargetFontSetting)은 앱 전역 영속 선언의 단일 실체다.
            WorkbenchController(job_registry, self._push, target_font=target_font),
        ]
        # 에디터의 템플릿 라이브러리 = tpl 화면의 VM **같은 인스턴스**:
        # 별도 인스턴스면 두 표면의 스캔 캐시가 갈라져(가져오기·삭제가 한쪽에만 반영) 신규
        # 1단계 피커가 관리 화면과 다른 목록을 조용히 보인다(라이브러리=단일 실체).
        tpl_ctrl = next(c for c in controllers if c.name == "tpl")
        controllers.insert(
            2,
            EditorController(
                job_registry, self._push,
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
        self.controllers["job"].workbench = self.controllers["workbench"]
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
        path = open_file_dialog(_LIBRARY_IMPORT_FILTERS, owner_title=WINDOW_TITLE)
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
            path = open_folder_dialog("가져올 템플릿 폴더 선택", owner_title=WINDOW_TITLE)
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
        """데이터 고정·등록 모달 '찾아보기' → **경로만** 반환(#26 #4).

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

    # (load_template_into_editor 브리지는 tpl 화면과 함께 사망(F8) — 크로스스크린 「이
    #  서식으로 새 작업」의 발신 표면이 죽어 소비자 0. 편집기 안 선택은 dispatch
    #  use_library_template(같은 new_job_session seam + assert_library_path)가 소유한다.)


# 모달 접근성 동적 프로브(#27/#28) — 실 브라우저에서 Modal 헬퍼의 초기포커스·Escape·복귀를
# 되읽는다. 알려진 트리거(첫 내비 버튼)에 포커스 → txtEditModal 열기 → Escape → 복귀 확인.
# (표적 모달은 두 번 이사했다: pasteModal → draftSaveTplModal → txtEditModal — 화면이
# 죽을 때마다 같은 Modal 헬퍼를 쓰는 생존 커스텀 모달로 재겨눔. F6 PR-B. F8: tpl 화면
# 사망에도 txtEditModal DOM 은 셸 레벨 생존·소유 JS 만 editor.js 로 이전 — 표적 불변.)
# IIFE 가 JSON 직렬화 가능한 객체를 반환하고, 게이트 테스트가 각 필드를 단언한다.
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
  window.Modal.open('txtEditModal', { initialFocus: document.getElementById('txtEditName') });
  var opened = !document.getElementById('txtEditModal').classList.contains('hidden');
  var focusIn = document.activeElement.id;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  var escapeClosing = document.getElementById('txtEditModal').classList.contains('is-closing');
  finishModal('txtEditModal');
  var closed = document.getElementById('txtEditModal').classList.contains('hidden');
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
  // 3택 모달(재작성 F7) — patch 처분처럼 답이 셋인 자리. 확인 모달을 두 번 물으면
  // "취소가 무엇을 취소하는지"가 갈리므로 골격을 따로 뒀다. 여기서 보는 것은 ①세 버튼이
  // 라벨을 받고 실제로 보이는가 ②초기 포커스가 **거절**(머무르기)인가 ③보조 버튼이 제
  // 값을 돌려주는가. 배선만 하고 안 보이면 사용자는 나갈 길이 없다.
  var chooseSpec = {
    title: '처분 확인', body: '3택 프로브',
    choices: [{value:'save',label:'저장하고 이동'},
              {value:'discard',label:'버리고 이동'},
              {value:'stay',label:'머무르기'}],
  };
  var chPromise = window.Modal.choose(chooseSpec);
  var chRoot = document.getElementById('chooseModal');
  var chOpen = !chRoot.classList.contains('hidden');
  var chDisplay = getComputedStyle(chRoot).display;
  var chFocus = document.activeElement ? document.activeElement.id : '';
  var chLabels = ['chooseModalOk','chooseModalAlt','chooseModalCancel'].map(function (id) {
    return document.getElementById(id).textContent;
  }).join('|');
  var chVisible = ['chooseModalOk','chooseModalAlt','chooseModalCancel'].every(function (id) {
    return getComputedStyle(document.getElementById(id)).display !== 'none';
  });
  document.getElementById('chooseModalAlt').click();     // 보조 = 버리고 이동
  finishModal('chooseModal');
  var chValue = '';
  chPromise.then(function (v) { chValue = v; window.__chooseValue = v; });

  return {
    choose_opened: chOpen,          // F7: 3택 골격이 열렸는가
    choose_display: chDisplay,      // F7: 열린 동안 display(flex 기대)
    choose_focus: chFocus,          // F7: 초기 포커스 = 거절(머무르기)
    choose_labels: chLabels,        // F7: 세 버튼이 호출부 라벨을 받았는가
    choose_all_visible: chVisible,  // F7: 세 버튼이 **실제로 보이는가**
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
  ['editor', 'job'].forEach(function (scr) {
    window.pywebview.api.initial(scr).then(function (s) { window.__snaps[scr] = s; });
  });
  window.Nav.go('editor', { force: true });  // 스크롤은 가시 화면에서만 유효 → 편집기 가시화
})()
"""

_PRESERVE_REAL_PROBE_JS = r"""
(function () {
  var out = {}, snaps = window.__snaps || {};
  ['editor', 'job'].forEach(function (scr) {
    try {
      if (!snaps[scr]) { out[scr] = 'no-snap'; return; }
      window.__push(scr, snaps[scr]);   // 실 render() (Preserve.around 래핑)
      out[scr] = 'ok';
    } catch (e) { out[scr] = 'throw:' + (e && e.message); }
  });
  // 편집기 스크롤 보존 end-to-end(구 「기안」 토큰 패널 프로브의 승계 — F6 PR-B): 실제
  // 내부 스크롤 요소인 #editor-body(data-preserve-scroll)를 스키마 40행으로 길게 만들고
  // 스크롤 → 실 재렌더 → 유지를 잰다. 스냅샷에 필드를 주입하는 이유는 재렌더가 innerHTML
  // 을 다시 짓기 때문이다 — DOM 에만 spacer 를 꽂으면 재렌더가 걷어 가 측정이 성립 안 한다.
  try {
    var snap = snaps['editor'];
    if (!snap) { out.editor_scroll_top = 'no-snap'; return out; }
    var fields = [];
    for (var i = 0; i < 40; i++) {
      fields.push({ name: '필드' + i, inferred_type: 'text', in_table: false,
        occurrences: 1, context: '' });
    }
    snap.section = 'template';
    snap.template_path = 'C:/t/스크롤검증.hwpx';
    snap.template_name = '스크롤검증.hwpx';
    snap.template_media = 'hwpx';
    snap.field_count = fields.length;
    snap.fields = fields;
    snap.schema_summary = '필드 40개';
    window.__push('editor', snap);
    var box = document.getElementById('editor-body');
    box.scrollTop = 60;                 // 오버플로 안 — 클램프 없이 남을 값
    window.__push('editor', snap);      // 실 재렌더 — Preserve 가 스크롤 복원해야
    out.editor_scroll_top = document.getElementById('editor-body').scrollTop;
  } catch (e) { out.editor_scroll_top = 'throw:' + (e && e.message); }
  window.Nav.go('job', { force: true });  // 자기 판을 자기가 걷는다(몰입 셸 잔존 금지)
  return out;
})()
"""




# 「작업」 본문 존 거울 + 재진술 블록(블록 6 D2/D1, 슬라이스 2) — 합성 스냅샷을 shipped __push 로
# 실 render() 에 흘려 거울 테이블 4상태 행·미입력 클릭형·재진술 이름 목록·드리프트 차단 배너가
# 실 WebView2 에서 실제로 그려지는지 되읽는다(정적 계약은 test_web_dom_contract, 값 합성은
# test_webapp_job 가 보고, 여기선 렌더 거동 — 부록 B-9 overlay/hidden 눈검증의 자동판).
_JOB_DATA_FIRST_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    // 작업 미선택 + 데이터 마운트(데이터-우선 §18.2) 합성 스냅샷 — vm-None 분기가 방출하는
    // 전 키 유효 모양 그대로. 후보 2종(available/needs_action)·prework 게이트·표시순 목록.
    var snap = {
      job_name:'', has_job:false,
      out_dir:'', data_label:'d.csv', data_source_label:'파일: d.csv', data_notice:null,
      template_name:'', template_path:'', filename_pattern:'', template_missing:false,
      has_data:true, record_count:2, selected_count:1,
      records:[{index:1, selected:true, name:'', summary:'사무비품'},
               {index:0, selected:false, name:'', summary:'전산장비'}],
      // 후보 구획(슬라이스 2 + 재작성 F6) — 순위 카드 2건(즐겨찾기·추천)·잘린 수·확인 필요.
      // **두 작업 방식이 섞인 판**이라 방식 구획 머리글이 실제로 서는지도 함께 본다(§19.3).
      candidates:{
        top:[{name:'공고서', tier:'favorite', favorited:true,
              last_run_at:'2026-07-20T09:00:00', suggested:false,
              mode:'hwpx_generate', mode_label:'HWPX 생성',
              last_run_label:'마지막 성공 실행 2026-07-20',
              template_name:'공고서.hwpx', template_path:'C:\\t\\공고서.hwpx',
              template_missing:false, conn_label:''},
             {name:'계약서', tier:'unused', favorited:false,
              last_run_at:'', suggested:true,
              mode:'text_review_copy', mode_label:'온나라 기안',
              last_run_label:'복사한 적 없음',
              template_name:'계약서.txt', template_path:'C:\\t\\계약서.txt',
              template_missing:false, conn_label:''}],
        sections:[{mode:'hwpx_generate', mode_label:'HWPX 문서 생성', names:['공고서']},
                  {mode:'text_review_copy', mode_label:'온나라 기안 검토·복사',
                   names:['계약서']}],
        more:2, needs_count:1,
        suggested:'계약서'},
      // 문서 탐색 구획(슬라이스 3) — 확인 필요 탭 + 검색으로 걸러낸 수.
      browse:{tab:'needs_action', query:'견적',
              rows:[{name:'견적서', missing:['담당자'], mode:'hwpx_generate',
                     mode_label:'HWPX 생성'}],
              sections:[{mode:'hwpx_generate', mode_label:'HWPX 문서 생성',
                         names:['견적서']}],
              available_count:7, needs_count:1, filtered_out:2},
      filter:{active:false, reapply_available:false, reapply_hint:'', search:'', chips:[],
              definition:'', branches:[],
              columns:[{name:'공고명', kind:'text', active:false}]},
      table:{columns:[{name:'공고명', kind:'text'}],
             rows:[{index:1, selected:true, name:'', summary:'사무비품',
                    cells:[[['사무비품',false]]]},
                   {index:0, selected:false, name:'', summary:'전산장비',
                    cells:[[['전산장비',false]]]}],
             visible_count:2, hidden_selected:[]},
      restate:{origin:'manual', filter_active:false, in_def:0, extra:0, sample:[1]},
      preflight:{level:'', text:''}, mirror:[], drift:[], name_tokens:[],
      gate:{enabled:false, level:'warn', text:'문서 작업을 선택하세요.'}
    };
    window.__push('job', snap);
    out.zones_shown = getComputedStyle(document.getElementById('jobZones')).display !== 'none';
    // 액션바의 정렬 **기준면**은 좌 열의 오른쪽 끝(= 구분선)이다(U2 §2.2 · 리뷰 R5). 같은
    // 컬럼 템플릿을 공유해도 재는 상자가 다르면(패딩) 트랙 끝이 어긋나는데, 규칙은 둘 다
    // 맞아 보여 정적 검사가 못 본다. 재는 것은 **눈에 보이는 마지막 것**이지 행의 상자가
    // 아니다 — 폭 0 인 빈 문안이 flex 항목으로 남으면 그 앞 gap 이 살아 마지막 버튼만
    // 물러서는데, 행의 오른쪽 끝은 여전히 기준면이라 행을 재면 통과한다.
    out.actionbar_plane = (function () {
      var side = document.querySelector('#jobZones .data-grid > .dg-side');
      var row = document.querySelector('#jobActionBar .actionbar-row');
      if (!side || !row) return null;
      var visible = Array.prototype.filter.call(row.children, function (c) {
        return c.getBoundingClientRect().width > 0;
      });
      if (!visible.length) return null;
      return Math.round(visible[visible.length - 1].getBoundingClientRect().right
                        - side.getBoundingClientRect().left);
    })();
    // 문안이 **빈** 상태도 잰다 — 생성이 열린 화면이 그 상태다. 스냅샷을 바꾸지 않고 문안만
    // 잠시 비웠다 되돌린다(이 프로브의 다른 측정과 같은 방식).
    out.actionbar_plane_empty_note = (function () {
      var note = document.getElementById('jobGate');
      var side = document.querySelector('#jobZones .data-grid > .dg-side');
      var row = document.querySelector('#jobActionBar .actionbar-row');
      if (!note || !side || !row) return null;
      var saved = note.textContent;
      note.textContent = '';
      var visible = Array.prototype.filter.call(row.children, function (c) {
        return c.getBoundingClientRect().width > 0;
      });
      var gap = visible.length
        ? Math.round(visible[visible.length - 1].getBoundingClientRect().right
                     - side.getBoundingClientRect().left)
        : null;
      note.textContent = saved;
      return gap;
    })();
    // 행동이 붙은 캡션(⤢)은 **오른쪽 끝**에 선다(리뷰 R5) — `.zone-cap{display:block}` 이
    // 곁의 `.zone-cap-actions{display:flex}` 를 덮으면 ⤢ 가 제목 바로 뒤에 붙는데, 규칙은
    // 둘 다 살아 있어 정적 검사로는 안 보인다(같은 특정도·나중 로드가 이기는 자리).
    out.cap_actions = (function () {
      var cap = document.querySelector('#jobZones .zone-cap.zone-cap-actions');
      var btn = cap && cap.querySelector('button');
      if (!cap || !btn) return null;
      return {display: getComputedStyle(cap).display,
              far_edge: Math.round(cap.getBoundingClientRect().right
                                   - btn.getBoundingClientRect().right)};
    })();
    // 행동이 붙은 캡션(⤢)은 **오른쪽 끝**에 선다(리뷰 R5) — `.zone-cap{display:block}` 이
    // 곁의 `.zone-cap-actions{display:flex}` 를 덮으면 ⤢ 가 제목 바로 뒤에 붙는데, 규칙은
    // 둘 다 살아 있어 정적 검사로는 안 보인다(같은 특정도·나중 로드가 이기는 자리).
    out.cap_actions = (function () {
      var cap = document.querySelector('#jobZones .zone-cap.zone-cap-actions');
      var btn = cap && cap.querySelector('button');
      if (!cap || !btn) return null;
      return {display: getComputedStyle(cap).display,
              far_edge: Math.round(cap.getBoundingClientRect().right
                                   - btn.getBoundingClientRect().right)};
    })();
    out.actionbar_shown = getComputedStyle(document.getElementById('jobActionBar')).display !== 'none';
    out.cands_row_shown = getComputedStyle(document.getElementById('jobCandsRow')).display !== 'none';
    out.cand_buttons = document.querySelectorAll('#jobCandidates [data-cand]').length;
    // 확인 필요·순위 밖은 후보 줄에서 **수치 + 출구**로만 말한다(슬라이스 3 이사).
    out.cand_exit = !!document.querySelector('#jobCandidates [data-browse-open]');
    out.cand_more_text = (function () {
      var m = document.querySelector('#jobCandidates .cand-more');
      return m ? m.textContent.replace(/\s+/g, ' ').trim() : '';
    })();
    out.cand_disabled_chips = document.querySelectorAll('#jobCandidates button[disabled]').length;
    // 문서 탐색 면(슬라이스 3) — 출구 클릭으로 실제로 열리고, 탭 라벨·행·사유·검색 고지가
    // 실 WebView2 에 그려지는지 되읽는다(닫아 두고 뒤 프로브를 방해하지 않는다).
    (function () {
      var exit = document.querySelector('#jobCandidates [data-browse-open]');
      if (!exit) { out.browse_open = 'no-exit'; return; }
      exit.click();
      var sheet = document.getElementById('jobBrowseSheet');
      out.browse_open = !sheet.classList.contains('hidden');
      out.browse_tabs = Array.prototype.map.call(
        sheet.querySelectorAll('[data-browse-tab]'),
        function (b) { return b.textContent + '/' + b.getAttribute('aria-selected'); });
      out.browse_rows = Array.prototype.map.call(
        sheet.querySelectorAll('.browse-row'),
        function (r) { return r.textContent.replace(/\s+/g, ' ').trim(); });
      out.browse_note = document.getElementById('jobBrowseNote').textContent;
      out.browse_focus_is_query =
        document.activeElement === document.getElementById('jobBrowseQuery');
      // 왕복 중 이어 친 검색어가 옛 스냅샷에 덮이지 않는가(리뷰 4R P2): 입력에 포커스를 두고
      // 새 글자를 넣은 뒤, **옛 검색어를 담은** 스냅샷을 밀어도 입력값이 살아 있어야 한다.
      (function () {
        var qi = document.getElementById('jobBrowseQuery');
        qi.focus();
        qi.value = '견적요청';                      // 사용자가 이어 친 상태
        window.__push('job', snap);                // 옛 검색어('견적')를 담은 응답 도착
        out.browse_query_kept = qi.value;
        qi.blur();
        window.__push('job', snap);                // 포커스가 떠난 뒤엔 서버 값으로 확정
        out.browse_query_settled = qi.value;
      })();
      // 탭 전환 재렌더에서 키보드 포커스가 살아남는가(리뷰 1R P2 — 안정 id + preserve.js).
      var tabA = document.getElementById('jobBrowseTab-available');
      if (tabA) {
        tabA.focus();
        window.__push('job', snap);            // 재렌더(탭 노드 교체)
        out.browse_tab_focus = document.activeElement && document.activeElement.id;
      }
      // 사용 가능 행을 고르면 포커스가 **방금 고른 작업 카드**에 착지한다(모달 복귀 트리거는
      // 재렌더로 해제되므로 명시 착지). 실 select_job 왕복은 스텁으로 대체하고, 이어 도착할
      // 스냅샷(job_name 채움)을 우리가 밀어 렌더 훅을 태운다.
      // 사용 가능 행을 고르면 **성사 뒤에** 면이 닫히고 포커스가 그 시점의 실 DOM 에 선다.
      // 스텁은 select_job 만 가로채고(교차오염 금지) **Python push 를 흉내 내지 않는다** —
      // 프로덕션에선 push·render 가 resolve 보다 먼저 끝나므로, 여기서 우리가 스냅샷을
      // 밀어 주면 그 순서를 가려 버린다(3R P2 지적). 이미 렌더된 카드에 서는지만 본다.
      (function () {
        var avail = JSON.parse(JSON.stringify(snap));
        avail.browse = {tab:'available', query:'', rows:[{name:'공고서', missing:[]}],
                        available_count:7, needs_count:1, filtered_out:0};
        window.__push('job', avail);
        var row = document.getElementById('jobBrowseRow-' + encodeURIComponent('공고서'));
        if (!row) { window.__browsePickFocus = 'no-row'; window.__browseDone = true; return; }
        var real = window.Bridge.call;
        var stub = function (screen, action) {
          if (action !== 'select_job') return real.apply(null, arguments);
          return Promise.resolve({});
        };
        window.Bridge.call = stub;
        var unstub = function () {                 // 새 스텁이 이미 들어섰으면 건드리지 않는다
          if (window.Bridge.call === stub) window.Bridge.call = real;
        };
        window.__browseDone = false;
        row.click();
        // 착지는 **닫힘 전이 종료 뒤**(Modal.finishClose→onClose)에 확정된다 — 즉시 읽으면
        // 늘 직전 포커스가 보여 프로브가 거짓 통과한다(관측자 오염). 두 사유를 차례로 본다:
        // ① 고르고 닫음 = 그 작업 카드 ② 그냥 닫음(취소) = 다시 열 출구.
        setTimeout(function () {
          unstub();
          var cls = document.getElementById('jobBrowseSheet').classList;
          window.__browseSheetClosed = cls.contains('is-closing') || cls.contains('hidden');
          window.__browsePickFocus = document.activeElement && document.activeElement.id;
          window.__push('job', snap);            // 원판 복구(뒤 프로브 방해 금지)
          document.querySelector('#jobCandidates [data-browse-open]').click();  // 다시 열고
          setTimeout(function () {
            document.getElementById('jobBrowseClose').click();                  // 그냥 닫기
            setTimeout(function () {
              window.__browseCloseFocus = document.activeElement && document.activeElement.id;
              window.__browseDone = true;
            }, 450);
          }, 60);
        }, 450);
      })();
      // 단순 닫기(면 안에서 재렌더가 있었어도)에서 포커스가 페이지로 돌아오는가(6R P2) —
      // 붙잡아 둔 노드가 아니라 **그 시점의 출구**를 다시 찾아 세운다. 전이 종료를 기다리지
      // 않도록 Modal 의 즉시 종료 경로(닫힘 전이 없는 환경)와 타이머 경로 모두를 허용한다.

    })();
    // 순위 카드(슬라이스 2) — 받은 순서 그대로·별 상태·추천 표지·「외 N건」 고지.
    out.cand_order = Array.prototype.map.call(
      document.querySelectorAll('#jobCandidates [data-cand]'),
      function (b) { return b.getAttribute('data-cand'); });
    out.fav_pressed = Array.prototype.map.call(
      document.querySelectorAll('#jobCandidates [data-fav]'),
      function (b) { return b.getAttribute('aria-pressed'); });
    out.suggested_marks = document.querySelectorAll('#jobCandidates .cand-sug').length;
    // 방식 구획(§19.3, F6) — 두 방식이 섞였으므로 머리글이 **선다**. 카드 부제의 방식
    // 텍스트는 구획이 퇴화해도 남는 값이라 함께 되읽는다.
    out.cand_sec_caps = Array.prototype.map.call(
      document.querySelectorAll('#jobCandidates .cand-sec-cap'),
      function (h) { return h.textContent; });
    out.cand_mode_texts = Array.prototype.map.call(
      document.querySelectorAll('#jobCandidates .cand-mode'),
      function (m) { return m.textContent; });
    out.suggested_dashed = (function () {
      var card = document.querySelector('#jobCandidates .job-cand-card.suggested');
      return card ? getComputedStyle(card).borderStyle : '';
    })();
    out.more_text = (function () {
      var m = document.querySelector('#jobCandidates .cand-more');
      return m ? m.textContent : '';
    })();
    out.last_run_text = (function () {
      var r = document.querySelector('#jobCandidates .cand-run');
      return r ? r.textContent : '';
    })();
    // 왕복 중 두 번째 클릭이 의도를 뒤집는가(리뷰 3R P2) — 표시는 push 뒤에 바뀌므로 DOM
    // 을 읽으면 같은 의도를 두 번 보내고, 멱등 처리 탓에 "껐다" 가 사라진다. Bridge 를
    // 미결로 세운 뒤 두 번 눌러 **보낸 의도열**을 되읽는다.
    (function () {
      // 즐겨찾기 쓰기 계약 2건을 실 DOM·실 핸들러로 되읽는다(리뷰 4R·5R P2).
      // 브리지를 **우리가 한 건씩 풀어 주는** 스텁으로 갈아 큐 상태를 관측한다. 단계 전이는
      // setTimeout(0) — 각 단계 사이에 이벤트 루프가 돌아 체인이 실제로 진행된다.
      // 노드 참조를 들고 있지 않는다 — 뒤따르는 포커스 프로브의 재푸시가 DOM 을 교체하므로
      // 매 단계에서 **이름으로 다시 찾는다**(떼어진 노드 클릭은 조용한 무동작이 된다).
      var starOf = function (name) {
        return document.getElementById('jobFav-' + encodeURIComponent(name));
      };
      if (!starOf('공고서') || !starOf('계약서')) { out.fav_intents = 'no-stars'; return; }
      var sent = [], release = [], real = window.Bridge.call;
      window.Bridge.call = function (screen, action, payload) {
        if (action !== 'toggle_favorite') return real.apply(null, arguments);
        sent.push(payload.value);
        return new Promise(function (res) { release.push(res); });
      };
      window.__favSent = sent;          // 배열 참조 — Python 이 마지막에 최종 상태를 읽는다
      window.__favChain = null;
      var drain = function (res) { var r = release.shift(); if (r) r(res); };
      // 레일 진입(Nav.go)이 유발한 **실 refresh** 스냅샷이 뒤늦게 도착해 합성 화면을 덮는다
      // (실 홈엔 데이터가 없어 후보 줄이 비워진다). 클릭 단계마다 합성 스냅샷을 다시 밀어
      // 카드를 되살린다 — 스냅샷이 다시 와도 **표시는 여전히 낡은 상태**이므로 DOM-대-미결
      // 의도 시나리오는 그대로 성립한다(오히려 실제와 같다).
      var repush = function () { window.__push('job', snap); };
      starOf('공고서').click();
      starOf('공고서').click();
      out.fav_sync_sends = sent.length;   // 0 — 클릭은 체인 진입이고 즉시 발신하지 않는다
      out.fav_intents = JSON.stringify(sent);
      var steps = [
        // ① 직렬화: 앞 왕복이 끝나기 전엔 둘째를 보내지 않는다(발신 1건).
        function () { window.__favChain = JSON.stringify({inflight: sent.length}); drain({ok: true}); },
        function () { drain({ok: true}); },                       // 첫 카드 큐 소진
        // ② 정리 식별: 같은 값이 다시 큐에 드는 3연속(true→false→true) 뒤,
        //    **첫 왕복만** 실패로 완료(스냅샷 없음)시키고 4번째 클릭의 의도를 관측한다.
        function () {
          repush();
          starOf('계약서').click(); starOf('계약서').click(); starOf('계약서').click();
        },
        function () { drain({ok: false, error: '실패 시늉'}); },
        function () { repush(); starOf('계약서').click(); },
        // 남은 큐를 전부 흘려 보내 최종 발신열을 확정한다(각 단계 = 이벤트 루프 1회전).
        function () { drain({ok: false, error: '실패 시늉'}); },
        function () { drain({ok: false, error: '실패 시늉'}); },
        function () { drain({ok: false, error: '실패 시늉'}); },
        function () { window.Bridge.call = real; }
      ];
      window.__favDiag = [];
      (function step(i) {
        if (i >= steps.length) { window.__favDone = true; return; }
        setTimeout(function () {
          try {
            steps[i]();
            window.__favDiag.push('ok' + i);
          }
          catch (e) {
            window.__favDiag.push('err' + i + ':' + (e && e.message) + ' ids=' +
              Array.prototype.map.call(document.querySelectorAll('#jobCandidates [data-fav]'),
                function (b) { return b.id; }).join('|') +
              ' html=' + document.getElementById('jobCandidates').innerHTML.slice(0, 80));
          }
          step(i + 1);
        }, 0);
      })(0);
    })();
    // 별 포커스가 재렌더(=별을 누르면 카드가 1순위로 이동)를 가로질러 살아남는가 —
    // preserve.js 는 id 로 복원하므로 이름 유래 안정 id 가 실제로 붙었는지 실물로 본다.
    (function () {
      var star = document.getElementById('jobFav-' + encodeURIComponent('계약서'));
      if (!star) { out.fav_focus_restored = 'no-id'; return; }
      star.focus();
      var moved = JSON.parse(JSON.stringify(snap));   // 깊은 사본만 만진다(원판 불변)
      moved.candidates.top.reverse();
      moved.candidates.top[0].favorited = true;   // 즐겨찾기 지정 후 1순위로 이동한 판
      window.__push('job', moved);
      out.fav_focus_restored =
        document.activeElement && document.activeElement.id === 'jobFav-' +
        encodeURIComponent('계약서') ? 'kept' : String(
          document.activeElement && document.activeElement.id);
      window.__push('job', snap);                 // 뒤 프로브를 위해 원판 복구
    })();
    out.gate_text = document.getElementById('jobGate').textContent;
    out.gen_disabled = document.getElementById('jobGenBtn').disabled;
    // 「선택한 작업」 존 사망(U2 §4, #342) — 작업 미선택이면 액션바 이름도 비고 자리를 접는다.
    out.action_name_empty = document.getElementById('jobActionName').textContent === '';
    out.tbl_rows_order = Array.prototype.map.call(
      document.querySelectorAll('#jobTableBody tr[data-i]'),
      function (r) { return r.getAttribute('data-i'); });
    // #302 리뷰 P2 두 건의 실렌더 되읽기 — prework 과진술·폴더 선택 금지.
    out.restate_hidden = getComputedStyle(document.getElementById('jobRestate')).display === 'none';
    out.folder_pick_disabled = document.getElementById('jobBtnPickFolder').disabled;
  } catch (e) { out.error = String(e); }
  return out;
})()
"""

_JOB_MIRROR_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    var snap = {
      job_name:'공고서', has_job:true,
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
    window.__jobToggleValues = toggleValues;   // 큐에서 풀리는 둘째 발신까지 담긴다(아래 참조)
    window.Bridge.call = function (screen, action, payload) {
      if (action === 'toggle_record') {
        toggleValues.push(payload.value);
        // **해소되는** 스텁이다(리뷰 2R): 존 변이는 한 체인에 직렬화되므로 영원히 미결인
        // 첫 발신은 둘째를 영영 막는다. 이 프로브가 재는 것은 "push 가 오기 전 재클릭이
        // 화면의 현재 상태를 쓰는가"이지 promise 가 매달리는가가 아니다 — push 는 여전히
        // 안 온다(스텁이 스냅샷을 밀지 않는다). 둘째 값은 마이크로태스크 뒤에 실리므로
        // 드라이브가 **별도 evaluate** 로 되읽는다.
        return Promise.resolve({});
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
    out.row_toggle_values = toggleValues.slice();   // 즉시분(첫 발신) — 최종 확인은 별도 되읽기
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
      {sel_count:3, in_def:2, extra:1, filter_active:true, filter_parts:2, ack_count:2},
      '데이터를 바꾸면');
    // ack 0 분기도 함께 핀한다 — 없는 손실을 열거하면 과경고(경보의 인플레)다.
    out.guard_body_no_ack = window.JobScreen.guardBody(
      {sel_count:1, in_def:0, extra:0, filter_active:false, filter_parts:0, ack_count:0},
      '데이터를 바꾸면');
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
    // #272: 420px 거울 캡과 두 펼침 면을 실 DOM 이동/복귀 및 기존 dispatch까지 검증한다.
    snap.drift = []; snap.name_tokens = [];
    snap.gate = {enabled:true, level:'', text:'생성 준비'};
    snap.mirror = [];
    for (var mi = 0; mi < 36; mi++) snap.mirror.push({
      name:'필드' + mi, state:mi === 0 ? 'missing' : 'filled', acknowledged:false,
      value:mi === 0 ? '(빈 값)' : '값 ' + mi, formatted:false
    });
    window.__push('job', snap);
    // CI 가상 데스크톱은 window.resize(1440, 900)을 실제 화면 상한(약 1024px)에서
    // 클램프한다. 운영 CSS를 바꾸지 않고 컨테이너 자체를 900px 경계 너머로 고정해 wide
    // 분기를 검증한 뒤 즉시 복원한다(실 협폭 분기는 별도 실제 창 프로브가 맡는다).
    var jobPanel = document.getElementById('jobPanel');
    var jobPanelFlex = jobPanel.style.flex, jobPanelWidth = jobPanel.style.width;
    jobPanel.style.flex = '0 0 1100px'; jobPanel.style.width = '1100px';
    out.job_grid_wide = getComputedStyle(document.getElementById('jobDataGrid')).gridTemplateColumns;
    jobPanel.style.flex = jobPanelFlex; jobPanel.style.width = jobPanelWidth;
    var mirror = document.getElementById('jobMirror');
    var restate = document.getElementById('jobRestate');
    var mirrorParent = mirror.parentNode, restateParent = restate.parentNode;
    out.mirror_capped = mirror.clientHeight <= 421 && mirror.scrollHeight > mirror.clientHeight;
    out.mirror_capstrip = !document.getElementById('jobMirrorCapstrip').hidden &&
      /전체\s*36필드/.test(document.getElementById('jobMirrorCapstrip').textContent);
    var mirrorTrigger = document.getElementById('jobMirrorExpand');
    mirrorTrigger.focus(); mirrorTrigger.click();
    out.confirm_moved = document.getElementById('jobConfirmSheetMirrorSlot').contains(mirror) &&
      document.getElementById('jobConfirmSheetRestateSlot').contains(restate);
    var dispatched = [];
    var sheetRealCall = window.Bridge.call;
    window.Bridge.call = function (screen, action, payload) {
      dispatched.push({screen:screen, action:action, field:payload && payload.field});
      return Promise.resolve({});
    };
    mirror.querySelector('.mir-row.miss').click();
    window.Bridge.call = sheetRealCall;
    out.confirm_dispatch = dispatched.length === 1 && dispatched[0].action === 'ack_field' &&
      dispatched[0].field === '필드0';
    document.getElementById('jobConfirmSheetClose').click();
    (function () { var card = document.querySelector('#jobConfirmSheet .modal-card');
      var ev = new Event('transitionend', {bubbles:true});
      Object.defineProperty(ev, 'propertyName', {value:'opacity'}); card.dispatchEvent(ev); })();
    out.confirm_restored = mirror.parentNode === mirrorParent && restate.parentNode === restateParent &&
      document.activeElement === mirrorTrigger;

    // ⤢ 데이터 펼침 면은 **비동기 프로브**(_DATA_SHEET_PROBE_SETUP_JS)로 떼어 냈다: 열기가
    // Python 왕복(초안 생성) 뒤로 바뀌어(F3) 동기 측정으로는 열리기 전을 재게 된다.

    // 편집기가 자기 화면으로 나가며(재작성 F7) 「편집 모드가 시트를 닫는다」는 계약은
    // 화면 전환이 승계했다: 편집기로 가면 이 화면의 펼침 면은 화면째 시야에서 사라지고,
    // 실 DOM 이 overlay 슬롯에 남는 교차 상태는 복귀 시 닫기가 정리한다.
    mirrorTrigger.click();
    window.Nav.go('editor', {force:true});
    out.edit_closes_sheets = !document.getElementById('scr-job').classList.contains('on') &&
      document.getElementById('scr-editor').classList.contains('on');
    window.Nav.go('job', {force:true});
    document.getElementById('jobConfirmSheetClose').click();
    (function () { var card = document.querySelector('#jobConfirmSheet .modal-card');
      var ev = new Event('transitionend', {bubbles:true});
      Object.defineProperty(ev, 'propertyName', {value:'opacity'}); card.dispatchEvent(ev); })();
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 좌 목록 사망(F2 PR-B)이 넘긴 두 의무를 승계처에서 되읽는다(지도 §10.9 판정 C·E).
# **별도 프로브로 떼어 낸 이유**: 후보 카드 클릭은 전환 재진입 가드(switching)를 잡으므로,
# 같은 스크립트 안에서 돌면 뒤이어 풀리는 문서 탐색 착지(setTimeout 연속)의 선택이 조용히
# 거절된다 — 프로브가 프로브를 오염시키는 자리다(관측자 오염 리트머스). 탐색 착지가 끝난
# 것을 Python 이 확인한 뒤에 이 프로브를 돌린다.
_JOB_INHERITED_AFFORDANCE_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    var snap = {
      job_name:'', has_job:false, out_dir:'', data_label:'d.csv',
      data_source_label:'파일: d.csv', data_notice:null,
      template_name:'', template_path:'', filename_pattern:'', template_missing:false,
      has_data:true, record_count:1, selected_count:1,
      records:[{index:0, selected:true, name:'', summary:'사무비품'}],
      candidates:{top:[{name:'공고서', favorited:false, suggested:false, last_run_at:''}],
                  more:0, needs_count:0, suggested:''},
      browse:{tab:'available', query:'', rows:[], available_count:1, needs_count:0, filtered_out:0},
      guard:{armed:false, sel_count:1, in_def:0, extra:0, filter_active:false, filter_parts:0},
      table:{columns:[{name:'공고명', kind:'text'}],
             rows:[{index:0, selected:true, name:'', summary:'사무비품',
                    cells:[[['사무비품',false]]]}],
             visible_count:1, hidden_selected:[]},
      restate:{origin:'manual', filter_active:false, in_def:0, extra:0, sample:[0]},
      preflight:{level:'', text:''}, mirror:[], drift:[], name_tokens:[],
      gate:{enabled:false, level:'warn', text:'문서 작업을 선택하세요.'}
    };
    window.__push('job', snap);
    // ① 「여는 중」 지연 표지(#217 R1) — 좌 목록 행에 있던 계약을 후보 카드가 진다. 왕복을
    //    **우리가 풀 수 있는** 미결로 세워 클릭 프레임의 표지를 읽고 곧바로 풀어 준다.
    var card = document.getElementById('jobCand-' + encodeURIComponent('공고서'));
    if (!card) { out.opening_marker_immediate = 'no-card'; }
    else {
      var release, real = window.Bridge.call;
      window.Bridge.call = function () {
        return new Promise(function (res) { release = res; });
      };
      card.click();
      out.opening_marker_immediate = card.getAttribute('aria-busy') === 'true' &&
        card.textContent.indexOf('여는 중') >= 0;
      window.Bridge.call = real;
      if (release) release({});
    }
    // ② 흡수처 출구(판정 C) — 데이터가 있으면 숨고(소음 금지), 데이터·작업이 둘 다 없으면
    //    상주해 막다른 화면을 막는다.
    out.no_data_exit_with_data =
      getComputedStyle(document.getElementById('jobNoDataExit')).display !== 'none';
    var empty = JSON.parse(JSON.stringify(snap));
    empty.has_data = false; empty.record_count = 0; empty.records = [];
    empty.table = {columns:[], rows:[], visible_count:0, hidden_selected:[]};
    empty.candidates = {top:[], more:0, needs_count:0, suggested:''};
    window.__push('job', empty);
    out.no_data_exit_shown =
      getComputedStyle(document.getElementById('jobNoDataExit')).display !== 'none';
    out.no_data_exit_target = !!document.getElementById('jobPickInLibrary');
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""


# 활성 카드 승계 + 경고 카드 클릭 대체(U2 §4, #342) — 죽은 「선택한 작업」 존의 승계처가
# 실 WebView2 에서 실제로 서는지 되읽는다. 정적 계약(test_web_dom_contract)은 조각의 존재만
# 보고, 여기는 ①액션바가 활성 작업 이름을 말하는가 ②활성 카드의 확장 부제(템플릿 파일명)와
# ⋮ — 부유 메뉴의 두 항목이 실제로 그 템플릿 경로를 겨누는가 ③경고 카드의 「연결 상태」
# 텍스트 ④경고 카드 클릭이 **선택이 아니라** 안내 다이얼로그인가(취소하면 select_job 0건 —
# 발신열을 스텁으로 관측)를 실 클릭으로 본다. 확인 다이얼로그의 취소는 160ms 정착 뒤에
# 끝나므로 발신열 회수는 _probe_late(__candProbeDone) 로 미룬다.
_JOB_ACTIVE_CARD_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    var snap = {
      job_name:'공고서', has_job:true, out_dir:'C:\\Results', data_label:'d.csv',
      data_source_label:'파일: d.csv', data_notice:null,
      template_name:'공고서.hwpx', template_path:'C:\\t\\공고서.hwpx',
      template_missing:false, filename_pattern:'doc-{{seq:001}}',
      has_data:true, record_count:1, selected_count:1,
      records:[{index:0, selected:true, name:'doc-001.hwpx', summary:'사무비품'}],
      candidates:{
        top:[{name:'공고서', tier:'recent', favorited:false,
              last_run_at:'2026-07-20T09:00:00', suggested:false,
              mode:'hwpx_generate', mode_label:'HWPX 생성',
              last_run_label:'마지막 성공 실행 2026-07-20',
              template_name:'공고서.hwpx', template_path:'C:\\t\\공고서.hwpx',
              template_missing:false, conn_label:''},
             {name:'계약서', tier:'unused', favorited:false,
              last_run_at:'', suggested:false,
              mode:'hwpx_generate', mode_label:'HWPX 생성',
              last_run_label:'실행한 적 없음',
              template_name:'계약서.hwpx', template_path:'C:\\t\\계약서.hwpx',
              template_missing:true, conn_label:'템플릿 없음'}],
        sections:[], more:0, needs_count:0, suggested:'', txt_note:''},
      browse:{tab:'available', query:'', rows:[], available_count:2, needs_count:0,
              filtered_out:0},
      filter:{active:false, reapply_available:false, reapply_hint:'', search:'', chips:[],
              definition:'', branches:[], columns:[{name:'공고명', kind:'text', active:false}]},
      table:{columns:[{name:'공고명', kind:'text'}],
             rows:[{index:0, selected:true, name:'doc-001.hwpx', summary:'사무비품',
                    cells:[[['사무비품',false]]]}],
             visible_count:1, hidden_selected:[]},
      restate:{origin:'manual', filter_active:false, in_def:0, extra:0, sample:[0]},
      preflight:{level:'ok', text:'ok'}, mirror:[], drift:[], name_tokens:[],
      gate:{enabled:true, level:'', text:'생성 준비'}
    };
    window.__push('job', snap);
    // ① 액션바가 활성 작업 이름을 말한다(§4-A 상속 의무 — 상수 높이 층의 정체 표시).
    out.action_name = document.getElementById('jobActionName').textContent;
    // ② 활성 카드 — 확장 부제(템플릿 파일명)와 ⋮ 는 활성 카드에만 선다(판정 B).
    var activeCard = document.querySelector('#jobCandidates .job-cand-card.active');
    out.active_tpl = (function () {
      var t = activeCard && activeCard.querySelector('.cand-tpl');
      return t ? t.textContent : ''; })();
    out.menu_btn_in_active = !!(activeCard && activeCard.querySelector('[data-cand-menu]'));
    out.menu_btn_count = document.querySelectorAll('#jobCandidates [data-cand-menu]').length;
    // ⋮ 클릭 → 부유 메뉴(.ctx-menu)의 두 항목이 그 템플릿 경로를 겨눈다(PathTrack 위임).
    document.getElementById('jobCandMenuBtn').click();
    var menu = document.getElementById('jobCandMenu');
    out.menu_open = menu.style.display !== 'none';
    out.menu_items = Array.prototype.map.call(
      menu.querySelectorAll('[data-track-act]'),
      function (b) { return b.getAttribute('data-track-act') + ':' +
        b.getAttribute('data-path') + ':' + b.textContent; });
    window.Popover.closeAll();          // 바깥닫기 기제 경유(뒤 프로브 오염 방지)
    out.menu_closed = menu.style.display === 'none';
    // ③ 경고 카드 — 「연결 상태」 는 텍스트가 정본이다(판정 C — 색만으로 말하지 않는다).
    var warnCard = document.querySelector('#jobCandidates .job-cand-card.warn');
    out.warn_conn = (function () {
      var c = warnCard && warnCard.querySelector('.cand-conn');
      return c ? c.textContent : ''; })();
    // ③-b **도달 보장 축**(3R 근본 조치) — 활성 작업의 템플릿이 부재면 후보 구획이 어떤
    //    상태든(여기선 아예 데이터 미마운트라 구획이 통째로 숨는다) 액션바가 연결 상태와
    //    재연결을 세운다. 정상 상태에선 조용하다(거짓 경보 금지).
    out.conn_quiet_when_ok = document.getElementById('jobActionConn').hidden === true &&
      document.getElementById('jobActionRelink').hidden === true;
    (function () {
      var gone = JSON.parse(JSON.stringify(snap));
      gone.has_data = false; gone.record_count = 0; gone.records = [];
      gone.table = {columns:[], rows:[], visible_count:0, hidden_selected:[]};
      gone.candidates = {top:[], sections:[], more:0, needs_count:0, suggested:'', txt_note:''};
      gone.template_missing = true; gone.conn_label = '템플릿 없음';
      window.__push('job', gone);
      out.cands_hidden_when_no_data =
        getComputedStyle(document.getElementById('jobCandsRow')).display === 'none';
      out.cand_cards_when_no_data = document.querySelectorAll('#jobCandidates [data-cand]').length;
      var conn = document.getElementById('jobActionConn');
      var relink = document.getElementById('jobActionRelink');
      out.conn_text_no_data = conn.hidden ? '' : conn.textContent;
      // 실제로 **눈에 보이는가** — hidden 을 지운 것과 렌더된 것은 다른 사실이다(프로브
      // click 이 hidden 을 통과한다는 교훈의 같은 계열).
      out.relink_visible_no_data = !relink.hidden && relink.offsetParent !== null;
      window.__push('job', snap);                 // 원판 복구(뒤 단계 오염 금지)
    })();
    // ④ 경고 카드 클릭 = 선택이 아니다(판정 D) — 안내 다이얼로그가 서고, 취소하면 아무
    //    발신도 없다. 발신열은 취소 정착(160ms) 뒤 _probe_late 가 회수한다.
    var sent = [], real = window.Bridge.call;
    window.Bridge.call = function (screen, action, payload) {
      sent.push(action);
      return Promise.resolve({});
    };
    window.__candProbeDone = false;
    document.getElementById('jobCand-' + encodeURIComponent('계약서')).click();
    var cm = document.getElementById('confirmModal');
    out.warn_redirect_modal = !!cm && !cm.classList.contains('hidden');
    out.warn_modal_body = document.getElementById('confirmModalBody').textContent;
    document.getElementById('confirmModalCancel').click();
    setTimeout(function () {
      window.Bridge.call = real;
      window.__candSent = JSON.stringify(sent);
      window.__candProbeDone = true;
    }, 400);
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""



# 「작업」 패널 두 모드(에디터 흡수, 블록 2 개정 결정 39~41) — 편집 호스트/세션 4존의 배타
# 표시와 신규=단계(번호 표지)·편집=탭(자유 이동 버튼) 이원 표현을 실 render 로 되읽는다
# (부록 B-9 overlay/hidden 눈검증의 자동판 — 이사한 DOM 이 실 WebView2 에서 실제로 선다).
# 결과 3태 구획(F4, 지도 §10.10) — Python 이 내는 결과 dict 를 실 렌더러에 그대로 흘려
# ①태·색 채널 ②실패 행 식별·「원인 진단 미연결」 경계 ③증거 접힘이 재렌더를 건너 열린 채
# ④지문 변화 = **강등**(파기 아님) ⑤구획 행동의 busy-lock ⑥닫기 뒤 포커스 착지를 되읽는다.
# 정적 계약(test_web_dom_contract)은 조각의 존재만 보고, 이 프로브는 그 조각들이 실제로
# 그 순서로 살아 움직이는지를 본다 — §10.9.5 가 세운 "경로가 이어지는가"의 기계판.
_JOB_RESULT_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('job');
    // 이 프로브의 세션 = 작업 '공고서' — 결과의 주체와 같은 값에서 출발한다(2R P2 비교군).
    window.__jobResultSnap = {
      job_name:'공고서', last_run_job:'공고서', has_job:true, out_dir:'D:\\out', data_label:'d.csv',
      data_source_label:'파일: d.csv', data_notice:null,
      template_name:'t.hwpx', template_path:'D:\\t.hwpx', filename_pattern:'doc-{{seq:001}}',
      template_missing:false, has_data:true, record_count:1, selected_count:1,
      records:[{index:0, selected:true, name:'', summary:'사무비품'}],
      candidates:{top:[], more:0, needs_count:0, suggested:''},
      browse:{tab:'available', query:'', rows:[], available_count:0, needs_count:0, filtered_out:0},
      guard:{armed:false, sel_count:1, in_def:0, extra:0, filter_active:false, filter_parts:0},
      table:{columns:[], rows:[], visible_count:0, hidden_selected:[]},
      restate:{origin:'manual', filter_active:false, in_def:0, extra:0, sample:[0]},
      preflight:{level:'', text:''}, mirror:[], drift:[], name_tokens:[],
      gate:{enabled:false, level:'warn', text:'확인이 필요합니다.'}
    };
    window.__push('job', window.__jobResultSnap);
    var partial = {
      ok:true, status:'partiallyCompleted', title:'2개 성공 · 1개 실패',
      summary:'완료. 성공 2/3, 실패 1.', level:'danger', stage:'', message:'', known:true,
      out_dir:'D:\\out', succeeded:2, failed:1, failed_selectable:1, total:3,
      failures:[{index:7, identity:'사무비품', filename:'doc-003.hwpx',
                 reason:'설명 없는 오류', known:false}],
      fill_notes:['누름틀 값 자리를 새로 만들어 채웠습니다.'],
      cancelled:false, attempted:3, unstarted:0
    };
    window.JobScreen.renderResult(partial);
    var box = document.getElementById('jobResult');
    out.state = box.dataset.state;
    out.level = box.dataset.level;
    out.shown = !box.hidden;
    out.title = document.getElementById('jobResultTitle').textContent;
    out.fail_row = !!document.getElementById('jobResultFail-7');
    out.fail_identity = document.getElementById('jobResultFails').textContent.indexOf('사무비품') >= 0;
    out.undiagnosed = document.getElementById('jobResultFails')
      .textContent.indexOf('원인 진단 미연결') >= 0;
    out.failed_sel_shown = !document.getElementById('jobResultFailedSel').hidden;
    out.failed_sel_label = document.getElementById('jobResultFailedSel').textContent;
    // 증거는 접혀서 서고, 사용자가 연 뒤에는 재렌더(스냅샷 푸시)를 건너 열린 채 남는다.
    var ev = document.getElementById('jobResultEvidence');
    out.evidence_shown = !ev.hidden;
    ev.open = true;
    window.JobScreen.renderResult(partial);
    out.evidence_open_survives_rerender = document.getElementById('jobResultEvidence').open;
    // 배치 진입 전 실패(행 0개·전량 실패) — 복구 행동이 행 목록에서 파생되면 여기서
    // 통째로 사라진다(1R P2). 노출·라벨은 Python 수치(failed_selectable)가 정한다.
    window.JobScreen.renderResult({
      ok:true, status:'failed', title:'문서 생성 실패',
      summary:'문서를 만들지 못했습니다. 대상 3건이 모두 생성되지 않았습니다.',
      level:'danger', stage:'생성 시작 전', message:'[WinError 5] 액세스가 거부되었습니다',
      known:true, out_dir:'D:\out', succeeded:0, failed:3, failed_selectable:3, total:3,
      failures:[], fill_notes:[], cancelled:false, attempted:0, unstarted:3
    });
    out.rowless_recovery_shown = !document.getElementById('jobResultFailedSel').hidden;
    out.rowless_recovery_label = document.getElementById('jobResultFailedSel').textContent;
    out.rowless_no_fake_rows = document.getElementById('jobResultFails').children.length === 0;
    window.JobScreen.renderResult(partial);
    // 지문 변화 = 강등이지 파기가 아니다(판정 G) — 결과가 남고 「직전 실행」이 붙는다.
    window.JobScreen.markResultStale();
    out.stale_shown = !document.getElementById('jobResultStale').hidden;
    out.alive_after_stale = !document.getElementById('jobResult').hidden;
    // 처분은 지문 성분별 2분기다(U2 §2.18) — 작업 전환·데이터 교체 = 초기화(+ 퇴장 한 줄),
    // 선택·규칙·저장 폴더 = 강등 유지. 이름 변경은 전환이 아니다(주체가 이름을 추종한다).
    // ① 이름 변경(3R P2) — 같은 작업인데 정체 표기만 바뀐 경우. 주체가 그 전이를 따라오므로
    //    결과가 살고 행동이 그대로 남아야 한다(여기서 걷히면 사용자는 제 결과를 이어서 못 손댄다).
    var snapR = JSON.parse(JSON.stringify(window.__jobResultSnap));
    snapR.job_name = '공고서(수정)'; snapR.last_run_job = '공고서(수정)';
    window.__push('job', snapR);
    window.JobScreen.markResultStale();
    out.renamed_rename_shown = !document.getElementById('jobResultRename').hidden;
    out.renamed_failedsel_shown = !document.getElementById('jobResultFailedSel').hidden;
    out.renamed_keeps_result = !document.getElementById('jobResult').hidden;
    // ② 다른 작업으로 전환(§2.18) — 링1 이 증거를 죽인 축이라 존이 닫히고, 실행 기록에
    //    퇴장 한 줄(주체·건수·경로)이 남는다. 이름 변경 직후라 주체 표기는 '공고서(수정)'.
    var snapB = JSON.parse(JSON.stringify(snapR));
    snapB.job_name = '둘째';
    window.__push('job', snapB);
    out.switch_resets_result = document.getElementById('jobResult').hidden;
    out.switch_exit_line = document.getElementById('jobRunLogLast').textContent;
    // 강등 렌더러의 주체 방어(3R P2)는 남는다 — 푸시를 거치지 않고 결과가 재수립되는 경로
    // (직접 renderResult)에서 남의 작업을 겨누는 버튼이 서지 않는지 몸통을 직접 찌른다.
    window.JobScreen.renderResult(partial);
    window.JobScreen.markResultStale();
    out.foreign_rename_hidden = document.getElementById('jobResultRename').hidden;
    out.foreign_failedsel_hidden = document.getElementById('jobResultFailedSel').hidden;
    out.foreign_evidence_alive = !!document.getElementById('jobResultFail-7');
    out.foreign_stale_names_owner =
      document.getElementById('jobResultStale').textContent.indexOf('공고서') >= 0;
    // ③ 선택 변경 = 강등 유지(§2.18) — 「실패한 N건만 선택」이 자기 결과를 없애면 안 된다.
    window.__push('job', window.__jobResultSnap);   // 비교군 복귀(원 작업 문맥)
    window.JobScreen.renderResult(partial);
    var snapSel = JSON.parse(JSON.stringify(window.__jobResultSnap));
    snapSel.selection_key = '0,1';
    window.__push('job', snapSel);
    out.selection_change_keeps_result = !document.getElementById('jobResult').hidden;
    out.selection_change_demotes = !document.getElementById('jobResultStale').hidden;
    // ④ 데이터 교체 = 초기화 + 퇴장 한 줄(경로 포함).
    var snapData = JSON.parse(JSON.stringify(snapSel));
    snapData.data_label = 'e.csv'; snapData.data_source_label = '파일: e.csv';
    window.__push('job', snapData);
    out.data_swap_resets_result = document.getElementById('jobResult').hidden;
    out.data_swap_exit_line = document.getElementById('jobRunLogLast').textContent;
    window.__push('job', window.__jobResultSnap);   // 비교군 복귀(다음 단계는 같은 작업 문맥)
    window.JobScreen.renderResult(partial);
    // 구획 행동은 생성 중 잠긴다(계약면 2) — 선언 표식이 실제로 disabled 를 받는가.
    var acts = ['jobResultClose', 'jobResultFailedSel', 'jobResultRename'];
    out.busy_lock_declared = acts.every(function (id) {
      return document.getElementById(id).hasAttribute('data-busy-lock');
    });
    // 진행 태에서는 저장 폴더 줄이 숨는다 — display:flex 가 UA [hidden] 을 이기는
    // 결함 클래스(부록 B-9)라 계산 스타일로 확인한다(속성만 보면 통과해 버린다).
    window.JobScreen.renderResult({running:true, title:'생성 중… 1/3', summary:''});
    out.folder_hidden_while_running =
      getComputedStyle(document.querySelector('#jobResult .result3-folder')).display === 'none';
    window.JobScreen.renderResult(partial);
    out.folder_shown_on_result =
      getComputedStyle(document.querySelector('#jobResult .result3-folder')).display !== 'none';
    // 닫기 = 유일한 명시 파기 + 포커스는 다음 행동으로 착지(계약면 3).
    document.getElementById('jobResultClose').click();
    out.closed = document.getElementById('jobResult').hidden;
    out.close_focus = document.activeElement && document.activeElement.id;
    // 명시 파기는 퇴장 한 줄을 남기지 않는다(U2 §2.18 파기 대칭) — 실행 기록이 기본 문안으로
    // 돌아왔는지 되읽는다(자동 초기화 경로만 흔적을 남긴다).
    out.close_runlog_last = document.getElementById('jobRunLogLast').textContent;
    // 실행 기록은 기본 접힘이되(노이즈 억제) 마지막 한 줄은 접힌 채로 보인다 — 접힘이
    // 소음 제거가 되면 이 화면의 유일한 비모달 사건 채널이 조용해진다.
    out.runlog_collapsed = !document.getElementById('jobRunLog').open;
    out.runlog_last_visible =
      getComputedStyle(document.getElementById('jobRunLogLast')).display !== 'none';
    // 실행 전 거절은 3태가 아니라 rejected 태로 선다 — 결과 자리를 비워 두지 않는다.
    var real = window.Bridge.generate;
    window.Bridge.generate = function () {
      return Promise.resolve({ok:false, error:'빈 값 필드를 먼저 확인하세요: 추정가격', level:'warn'});
    };
    document.getElementById('jobGenBtn').disabled = false;
    document.getElementById('jobGenBtn').click();
    window.__resultRejectProbe = true;
    setTimeout(function () {
      var b = document.getElementById('jobResult');
      window.__rejectState = b.dataset.state;
      window.__rejectText = document.getElementById('jobResultSummary').textContent;
      // 거절 사유는 log() 도 탄다 — 접힌 요약 줄이 그 사실을 실제로 나르는가.
      window.__runlogLast = document.getElementById('jobRunLogLast').textContent;
      window.Bridge.generate = real;
      window.__resultProbeDone = true;
    }, 60);
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""


_JOB_EDITMODE_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    // 몰입 표면(재작성 F7) — 편집기는 자기 화면이고 상단 2탭을 **실제로** 덮는가.
    // 정적 계약(클래스 존재)만 보면 「배선했지만 여전히 나갈 구멍이 있는」 상태를 통과시킨다.
    window.Nav.go('editor', {force:true});
    out.editor_screen_on = document.getElementById('scr-editor').classList.contains('on');
    out.job_screen_off = !document.getElementById('scr-job').classList.contains('on');
    out.nav_hidden = getComputedStyle(document.querySelector('.nav')).display === 'none';
    out.back_shown = getComputedStyle(document.getElementById('editorBack')).display !== 'none';
    // section 어휘(재작성 F7 판정 B) — 탭 집합은 Python 이 매체에서 파생해 내려준다.
    var draft = {section:'template', sections:['template','binding','filename'],
      reachable:{template:false, binding:false, filename:false}, dirty_sections:[],
      is_draft:true, dirty:false, changes:{}, context:{entry_reason:'voluntary', evidence:{}, return_context:{}},
      revisions:{}, template_path:'', template_name:'',
      field_count:0, fields:[], raw_block:'', gate_error:false, gate:null, notice:null,
      editing_origin:''};
    window.__push('editor', draft);
    out.wizard_steps = document.querySelectorAll('#editor-steps .wstep-tab .k').length;
    out.foot_shown_new = getComputedStyle(document.getElementById('editor-foot')).display !== 'none';
    draft.editing_origin = '공고서';
    draft.is_draft = false;
    window.__push('editor', draft);
    out.edit_tabs = document.querySelectorAll('#editor-steps button.wstep-tab.as-tab').length;
    // 편집의 주 행동(「변경 저장」)은 어느 탭에서도 상시 있다(§10.13 판정 E) — 구판은 저장
    // 분류에만 푸터가 있어 다른 탭에선 저장 자체가 도달 불가였다.
    out.foot_shown_edit = getComputedStyle(document.getElementById('editor-foot')).display !== 'none';
    // 「변경 버리기」는 상시 표시 + 상태 비활성(U2 §2.17) — 존재 단언은 상시 표시가 되는
    // 순간 무엇을 밀어 넣어도 참이라 조용히 죽는다. 비활성 판정으로 승격해 clean/dirty
    // **두 값**을 각각 재고, 저장이 같은 술어를 쓰는지도 함께 본다(음성·양성 대조).
    var discardOf = function () {
      return document.querySelector('#editor-foot [data-act="discard-patch"]');
    };
    var saveOf = function () {
      return document.querySelector('#editor-foot [data-act="save"]');
    };
    out.discard_shown_clean = !!discardOf();
    out.discard_disabled_clean = !!(discardOf() && discardOf().disabled);
    out.save_disabled_clean = !!(saveOf() && saveOf().disabled);
    out.edit_dirty_tab_marked = (function () {
      draft.dirty_sections = ['binding'];
      draft.dirty = true;                     // 세션 수준 판정은 Python 이 낸 값 하나(3R)
      window.__push('editor', draft);
      // 손댄 상태에서는 머리가 「저장하지 않은 변경」을 말하고 제자리 되돌리기가 활성이다 —
      // 「저장됨」이라 말하면서 버릴 길도 없던 자리(3R P2).
      out.dirty_head = document.getElementById('editorSaveState').textContent;
      out.discard_shown_dirty = !!discardOf();
      out.discard_enabled_dirty = !!(discardOf() && !discardOf().disabled);
      out.save_enabled_dirty = !!(saveOf() && !saveOf().disabled);
      return document.querySelectorAll('#editor-steps button.wstep-tab.dirty').length;
    })();
    // 머리 — 이름(안정 입력)·저장 상태·판본(§10.13 판정 O 표시 자리 ①).
    draft.name = '공고서';
    draft.revisions = {template:2, binding:5};
    draft.dirty_sections = [];
    draft.dirty = false;
    window.__push('editor', draft);
    out.name_input_value = document.getElementById('editorName').value;
    out.save_state = document.getElementById('editorSaveState').textContent;
    // 진입 문맥 배너 — 사유가 있으면 서고 자발적 진입이면 침묵한다.
    out.ctx_hidden_when_voluntary =
      getComputedStyle(document.getElementById('editorContext')).display === 'none';
    draft.context = {entry_reason:'preview_result', evidence:{'보고 있던 행':'4 / 12'},
      return_context:{surface:'preview'}};
    window.__push('editor', draft);
    out.ctx_shown = getComputedStyle(document.getElementById('editorContext')).display !== 'none';
    out.ctx_text = document.getElementById('editorContext').textContent;
    out.ctx_return_btn = !!document.querySelector('#editorContext [data-act="context-return"]');
    // 나간 뒤엔 셸이 돌아온다 — 몰입이 영구 은닉이 되면 다른 화면으로 갈 길이 사라진다.
    window.Nav.go('job', {force:true});
    out.nav_back_after_leave = getComputedStyle(document.querySelector('.nav')).display !== 'none';
  } catch (e) { out.error = 'throw:' + (e && e.message); }
  return out;
})()
"""

# 매핑 분류 칩-라이브(블록 2 결정 12·13, 슬라이스 5 PR-3) — 합성 매핑 스냅샷을 __push 로 실
# render() 에 흘려 (a) 사용할 헤더가 **즉시 토글 칩**(체크박스 스테이징 소거)으로, (b) 미사용
# 구역이 펼쳐지고(ignored_expanded), (c) 소유권 태그 4종(확정·수동·제안·후보 없음)이,
# (d) touched 행에 '자동 제안으로 되돌리기'(↩)가 실 WebView2 에서 그려지는지 되읽는다.
# 정의 surface 는 몰입 표면(재작성 F7)에 산다 — 루트도 #scr-editor.
_EDITOR_GUARD_PROBE_SETUP_JS = r"""
(() => {
  /* 탭 처분 3택의 **이어짐**(재작성 F7 1R P1) — 「저장하고 이동」이 저장까지만 하고 이동을
     안 하면 사용자가 고른 처분이 절반만 일어난다(저장은 됐는데 가려던 곳에 못 간다).
     정적 계약은 이 결함을 못 본다: 배선·문안·판정이 전부 제자리이고 **성사 뒤 이어짐**만
     끊긴다. 그래서 실 클릭 → 실 모달 → 실 재발신 순서를 그대로 밟고 발신 기록을 되읽는다.

     자기 액션만 스텁하고 복원은 "내 스텁일 때만"(프로브 교차 오염 금지 —
     [[gate-env-gotchas]]). 모달은 비동기라 완료 표지를 남기고 폴링한다. */
  const out = { pending: true, calls: [] };
  window.__editorGuard = out;
  const real = window.Bridge.call;
  const mine = function (screen, action, payload) {
    if (screen !== 'editor') return real(screen, action, payload);
    out.calls.push(action + (payload && payload.disposition ? ':' + payload.disposition : ''));
    if (action === 'goto_section' && !(payload && payload.disposition)) {
      return Promise.resolve({
        ok: false, needs_section_guard: true, section: 'binding',
        section_label: '필드 연결·표시', target: payload.section,
      });
    }
    if (action === 'save') return Promise.resolve({ ok: true, saved_name: '공고서' });
    return Promise.resolve({});
  };
  const finish = (why) => {
    if (window.Bridge.call === mine) window.Bridge.call = real;
    // **자기 판을 자기가 걷는다**(프로브 교차 오염 금지 — 첫 판에서 실제로 밟았다):
    // 편집기는 셸을 덮는 화면이라 그대로 두면 뒤따르는 프로브가 상단 탭·브랜드를
    // 「사라졌다」고 읽고, 모달이 남긴 포커스는 다음 프로브의 복귀 표적을 오염시킨다.
    try {
      window.Nav.go('job', { force: true });
      const home = document.querySelector('.navbtn[data-scr="job"]');
      if (home) home.focus();
    } catch (e) { out.teardown_error = String(e && e.message); }
    out.why = why;
    out.pending = false;
  };
  try {
    window.Nav.go('editor', { force: true });
    window.__push('editor', {
      section: 'binding', sections: ['template', 'binding', 'filename'],
      reachable: { template: true, binding: true, filename: true },
      dirty_sections: ['binding'], dirty: true, is_draft: false, changes: {},
      context: { entry_reason: 'voluntary', evidence: {}, return_context: {} },
      revisions: { template: 1, binding: 2 }, template_path: 'C:/t/공고서.hwpx',
      template_name: '공고서.hwpx', field_count: 0, fields: [], raw_block: '',
      gate: null, gate_error: false, notice: null, editing_origin: '공고서',
      name: '공고서', pattern: 'x', rows: [], source_fields: [],
      active_source_fields: [], ignored_source_fields: [], sample_rows: [],
      type_options: [], fmt_options: {}, provenance: null,
    });
    window.Bridge.call = mine;
    const tab = document.querySelector('#editor-steps button[data-section="filename"]');
    if (!tab) { finish('탭 버튼 없음'); return; }
    tab.click();
    let ticks = 0;
    const step = () => {
      ticks += 1;
      const ok = document.getElementById('chooseModalOk');
      const open = !document.getElementById('chooseModal').classList.contains('hidden');
      if (open && ok) {
        out.modal_label = ok.textContent;
        ok.click();                       // 「저장하고 이동」
        setTimeout(() => finish('완료'), 400);   // 모달 정착(160ms) + 재발신 왕복
        return;
      }
      if (ticks > 40) { finish('모달 미개방'); return; }
      setTimeout(step, 50);
    };
    setTimeout(step, 50);
  } catch (e) {
    out.error = 'throw:' + (e && e.message);
    finish('예외');
  }
})()
"""


_EDITOR_DISCARD_CANCEL_PROBE_JS = r"""
(() => {
  /* 「변경 버리기」의 **취소 뒤 정합**(U2 §2.17 2R P2) — 1R 이 버튼을 blur 전에 눌리게
     연 자리다. 시나리오: 클린 세션의 이름을 고치고(대기 편집 발생) 곧바로 버리기를 눌러
     확인을 연 뒤 **취소**한다. 정산 없이 열면 blur 가 큐에 넣은 `set_name` 이 모달이 떠
     있는 사이 도착해 push→render 가 `#editor-foot` 을 갈아 끼우고, 저장해 둔 트리거가
     분리돼 취소가 화면 루트로 떨어진다(모달의 대안 착지). 정적 계약은 이 결함을 못 본다:
     배선·문안·판정이 전부 제자리이고 **비동기 도착 순서**만 어긋난다.

     자기 액션만 스텁하고 복원은 "내 스텁일 때만"(프로브 교차 오염 금지 —
     [[gate-env-gotchas]]). 모달은 비동기라 완료 표지를 남기고 폴링한다. */
  const out = { pending: true, calls: [] };
  window.__editorDiscardCancel = out;
  const real = window.Bridge.call;
  const clean = {
    section: 'filename', sections: ['template', 'binding', 'filename'],
    reachable: { template: true, binding: true, filename: true },
    dirty_sections: [], dirty: false, is_draft: false, changes: {},
    context: { entry_reason: 'voluntary', evidence: {}, return_context: {} },
    revisions: { template: 1, binding: 2 }, template_path: 'C:/t/공고서.hwpx',
    template_name: '공고서.hwpx', field_count: 0, fields: [], raw_block: '',
    gate: null, gate_error: false, notice: null, editing_origin: '공고서',
    name: '공고서', pattern: '공고서-{{ID}}', pattern_preview: '공고서-1.hwpx',
    rows: [], source_fields: [], active_source_fields: [], ignored_source_fields: [],
    sample_rows: [], type_options: [], fmt_options: {}, provenance: null,
    default_dataset: null, has_unsaved_work: false, dataset_name: '', schema_only: true,
    counts: { filled: 0, empty: 0, unmapped: 0 }, preview_empties: [],
    preview_index: 0, preview_count: 0, is_complete: true,
  };
  const dirty = Object.assign({}, clean, {
    dirty: true, dirty_sections: ['template'], has_unsaved_work: true, name: '공고서 수정',
  });
  const discardOf = () => document.querySelector('#editor-foot [data-act="discard-patch"]');
  const mine = function (screen, action, payload) {
    if (screen !== 'editor') return real(screen, action, payload);
    out.calls.push(action);
    if (action === 'set_name') {
      // 큐에 든 blur 발신이 **늦게** 도착하는 실제 조건을 그대로 만든다: 응답 전 지연 +
      // 도착 시 dirty 스냅샷 push(= `#editor-foot` 재구성 → 옛 트리거 분리).
      return new Promise((resolve) => setTimeout(() => {
        window.__push('editor', dirty);
        resolve({});
      }, 120));
    }
    return Promise.resolve({});
  };
  const finish = (why) => {
    if (window.Bridge.call === mine) window.Bridge.call = real;
    try {
      window.Nav.go('job', { force: true });
      const home = document.querySelector('.navbtn[data-scr="job"]');
      if (home) home.focus();
    } catch (e) { out.teardown_error = String(e && e.message); }
    out.why = why;
    out.pending = false;
  };
  try {
    window.Nav.go('editor', { force: true });
    window.__push('editor', clean);
    window.Bridge.call = mine;
    const nameEl = document.getElementById('editorName');
    if (!nameEl || !discardOf()) { finish('편집 표면 미구성'); return; }
    // ① 클린 세션에 타이핑 — 대기 편집이 서고 버리기가 열린다(1R 계약).
    nameEl.focus();
    nameEl.value = '공고서 수정';
    nameEl.dispatchEvent(new Event('input', { bubbles: true }));
    out.discard_enabled_on_typing = !discardOf().disabled;
    // ② 곧바로 버리기 클릭. 실제 순서 그대로 blur→change(=큐 적재) 뒤 click 이 온다.
    nameEl.dispatchEvent(new Event('change', { bubbles: true }));
    nameEl.blur();
    discardOf().click();
    let ticks = 0;
    const step = () => {
      ticks += 1;
      const cancel = document.getElementById('confirmModalCancel');
      const open = !document.getElementById('confirmModal').classList.contains('hidden');
      if (open && cancel) {
        // 확인이 열린 시점 = 정산이 끝난 뒤여야 한다: 큐의 set_name 이 이미 도착했으므로
        // 그 push 의 재구성도 끝났고, 모달이 든 트리거는 **지금 살아 있는** 버튼이다.
        out.flushed_before_open = out.calls.indexOf('set_name') === 0;
        out.trigger_connected_at_open = !!(discardOf() && discardOf().isConnected);
        cancel.click();                                   // ③ 취소
        setTimeout(() => {
          // ④ 취소 뒤 정합: 초점이 화면 루트가 아니라 버리기 버튼으로 돌아오고, 친 값과
          //    dirty 술어(두 버튼 활성)가 그대로다. 취소는 아무것도 버리지 않는다.
          const active = document.activeElement;
          out.focus_back_on_discard = !!(active && active.dataset &&
            active.dataset.act === 'discard-patch');
          out.focus_fell_to_screen_root = !!(active && active.id === 'scr-editor');
          const nm = document.getElementById('editorName');
          out.name_value_after_cancel = nm ? nm.value : null;
          const save = document.querySelector('#editor-foot [data-act="save"]');
          out.discard_enabled_after_cancel = !!(discardOf() && !discardOf().disabled);
          out.save_enabled_after_cancel = !!(save && !save.disabled);
          out.discarded = out.calls.indexOf('discard_patch') !== -1;
          finish('완료');
        }, 300);
        return;
      }
      if (ticks > 60) { finish('모달 미개방'); return; }
      setTimeout(step, 50);
    };
    setTimeout(step, 50);
  } catch (e) {
    out.error = 'throw:' + (e && e.message);
    finish('예외');
  }
})()
"""


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
      section:'binding', sections:['template','binding','filename'], notice:null,
      reachable:{template:true, binding:false, filename:false}, dirty_sections:[],
      is_draft:false, dirty:false, changes:{}, revisions:{},
      context:{entry_reason:'voluntary', evidence:{}, return_context:{}},
      template_path:"C:/t/공고서.hwpx", template_name:"공고서.hwpx", field_count:4,
      schema_summary:"", fields:[], raw_block:"", gate:null, gate_error:false,
      data_path:"C:/d/대장.xlsx", data_name:"대장.xlsx", data_sheet:"물품", record_count:3,
      source_fields:["품명","세부품명","수량","비고"],
      active_source_fields:["품명","수량","비고"], ignored_source_fields:["세부품명"],
      active_count:3, ignored_count:1, ignored_expanded:true,
      sample_rows:[["A","a","3","-"],["B","b","6","x"],["C","c","1","-"]],
      type_options:["text","date","amount","const"],
      fmt_options:{text:[],date:[],amount:[],const:[]},
      name:"", pattern:"x", has_unsaved_work:true, editing_origin:"",
      provenance:null,
      rows:[row(0,"품명","품명",true,true,true),     // 확정
            row(1,"수량","수량",false,true,true),     // 수동(touched 미확정)
            row(2,"규격","비고",false,false,true),    // 제안(시스템 소유)
            row(3,"담당자","",false,false,false)],    // 후보 없음
      counts:{filled:3,empty:0,unmapped:1}, preview_empties:[], preview_index:1, preview_count:3,
      is_complete:false, schema_only:false
    };
    window.Nav.go('editor', {force:true});
    window.__push('editor', snap);
    var root = document.getElementById('scr-editor');
    out.active_chips = root.querySelectorAll('.hchip.on[data-act="toggle-header"]').length;
    out.has_checkbox_staging = !!root.querySelector('.hbx');  // 스테이징 소거 → false 여야
    out.ignored_chip = !!root.querySelector('.hchip.ign[data-act="toggle-header"]');
    out.ignored_fold_open = !!root.querySelector('details.hidden-hdrs[open]');
    out.use_none_btn = !!root.querySelector('[data-act="use-none"]');
    out.tags = Array.from(root.querySelectorAll('table.map .tag')).map(function (t) {
      return t.textContent.trim();
    });
    out.auto_revert_option = !!root.querySelector('table.map [data-act="revert-source"]');
    // 재제안 버튼이 **select 와 같은 줄에** 서는가(U2 §2.6). 종전엔 select 가 width:100% 로
    // 열폭을 다 먹고 버튼이 뒤에 인라인으로 붙어 둘째 줄로 밀렸다 — 정적 CSS 검사로는 못
    // 보고 실렌더 높이로만 드러나는 결함이라, 수동 행(버튼 有)과 제안 행(버튼 無)의 「데이터
    // 열」 칸 높이를 재서 비교한다. 같으면 안 밀린 것이다.
    var cells = root.querySelectorAll('table.map tbody tr td:nth-child(3)');
    var manual = cells[1], suggested = cells[2];
    out.src_cell_h_manual = manual ? Math.round(manual.getBoundingClientRect().height) : -1;
    out.src_cell_h_suggested = suggested ? Math.round(suggested.getBoundingClientRect().height) : -1;
    // 버튼과 select 의 세로 중심이 같은가 — 줄이 갈리면 중심이 한 줄 높이만큼 벌어진다.
    var wrap = manual && manual.querySelector('.srcwrap');
    var sel = wrap && wrap.querySelector('.sel');
    var btn = wrap && wrap.querySelector('[data-act="revert-source"]');
    if (sel && btn) {
      var a = sel.getBoundingClientRect(), b = btn.getBoundingClientRect();
      out.revert_same_line = Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)) < 4;
    } else { out.revert_same_line = null; }
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
  return out;
})()
"""

# 데이터 선택 다이얼로그(재작성 F1) — `pool` 화면 사망의 승계처가 **실제로 서는지** 되읽는다.
# 정적 DOM 계약이 못 잡는 것 셋: ①「이 데이터 고정」이 파일 출처에서만 뜨는가(pool 출처는 이미
# 고정된 참조라 숨는다) ②보관 항목이 목록에 남아 `활성화` 에 도달 가능한가(§10.7.2 C — 활성만
# 실으면 그 동사가 사라진다) ③손상 격리가 목록 아래 상주 재진술되는가(RC-05).
# 합성 pool 스냅샷을 실 __push 로 밀어 렌더 경로를 그대로 통과시킨다.
# 데이터 선택 다이얼로그 — pool 화면 승계(§10.7.4) + 단일 경로화(U2 §2.7). 찾아보기 마운트가
# 비동기(브리지 스텁 await)라 setup+stash 형식이다. §2.7 의 실렌더 완료 기준: 찾아보기 성사
# 뒤 면이 열려 있고 「이 데이터 고정」이 **가시**여야 한다 — 프로브 click 은 hidden 요소도
# 통과하므로(F8 교훈) 존재가 아니라 계산 스타일·offsetParent 로 가시성까지 단언한다.
_DATA_PICKER_PROBE_SETUP_JS = r"""
(function () {
  window.__dataPicker = { pending: true };
  var out = {};
  (async function () {
  try {
    window.Nav.go('job');
    DataPicker.open({screen:'job', current:{
      label:'파일: 대장.xlsx', detail:'3건', path:'C:/d/대장.xlsx', sheet:'물품', origin:'file'}});
    out.opened = !document.getElementById('dataPickerModal').classList.contains('hidden');
    out.pin_offered = !!document.getElementById('dataPickerPin');
    // 「＋ 직접 등록…」 사망(U2 §2.7 4행) — DOM 자체가 없어야 한다.
    out.register_gone = !document.getElementById('dataPickerRegister');
    function row(key, name, status, badge, level, actions) {
      return {key:key, name:name, kind:'excel', kind_label:'엑셀/CSV', status:status,
        badge_label:badge, badge_level:level, reference:'C:/d/' + name + '.xlsx (물품)',
        locate_path:'C:/d/' + name + '.xlsx', sheet:'물품', missing:false, note:'',
        actions:actions};
    }
    window.__push('pool', {
      rows:[row('k1','7월 공고목록','active','활성','ok',[{key:'archive',label:'보관'},{key:'delete',label:'삭제'}]),
            row('k2','6월 보관분','archived','보관','muted',[{key:'activate',label:'활성화'},{key:'delete',label:'삭제'}])],
      corrupted:[{file:'broken.dataset.json', error:'JSON 을 읽을 수 없습니다'}],
      // 같은 데이터 등록 2건(§5.3 구판 병합 대상) — loud 재진술 카드가 실제로 서는지 되읽는다.
      duplicates:[{reference:'파일: 대장.xlsx · 시트 물품',
                   entries:[{key:'k1', name:'7월 공고목록'}, {key:'k2', name:'6월 보관분'}]}],
      count:'2건', empty:false, result:{text:'', level:'muted'}});
    var host = document.getElementById('dataPickerPinned');
    out.rows = host.querySelectorAll('.tplcard').length;
    var uses = host.querySelectorAll('[data-act="use"]');
    out.use_active_enabled = uses.length > 0 && !uses[0].disabled;
    out.use_archived_disabled = uses.length > 1 && !!uses[1].disabled;
    out.activate_reachable = !!host.querySelector('[data-act="activate"]');
    out.relink_reachable = !!host.querySelector('[data-act="relink"]');
    // 행동 버튼이 슬롯 키를 겨눈다(§5.3 — 이름은 라벨). 키 없는 버튼은 남의 항목을 겨눈다.
    out.use_targets_key = uses.length > 0 && uses[0].dataset.key === 'k1';
    out.corrupt_shown =
      document.getElementById('dataPickerCorrupt').textContent.indexOf('손상') >= 0;
    // 병합 대상(같은 데이터 등록 2건) — 숨김·자동 정리 금지: 카드와 확정 버튼이 실제로 선다.
    var dupes = document.getElementById('dataPickerDupes');
    out.dupes_shown = dupes.textContent.indexOf('같은 데이터') >= 0
      && dupes.querySelectorAll('[data-dup-keep]').length === 2;
    // 「이 데이터 고정」 = 등록 모달 재사용(현재 대상 프리필) — 제목·프리필까지 되읽는다.
    document.getElementById('dataPickerPin').click();
    out.pin_title = document.getElementById('poolRegTitle').textContent;
    out.pin_ok = document.getElementById('poolRegOk').textContent;
    out.pin_path = document.getElementById('poolRegPath').value;
    out.pin_sheet = document.getElementById('poolRegSheet').value;
    // pin 모드 참조 잠금(U2 §2.7 5행) — path·sheet 읽기전용 + 폼 안 찾아보기 감춤.
    out.pin_path_readonly = document.getElementById('poolRegPath').readOnly;
    out.pin_sheet_readonly = document.getElementById('poolRegSheet').readOnly;
    out.pin_browse_hidden =
      getComputedStyle(document.getElementById('poolRegBrowse')).display === 'none';
    Modal.close('poolRegModal');
    // 찾아보기 성사 = 면 유지(U2 §2.7 1행) — 브리지를 descriptor 스텁으로 갈아 실클릭한다.
    var origPick = window.Bridge.pickDataFile;
    window.Bridge.pickDataFile = function () {
      return Promise.resolve({label:'파일: 새목록.xlsx', path:'C:/d/새목록.xlsx', sheet:'', rows:5});
    };
    try {
      document.getElementById('dataPickerBrowse').click();
      // browseFile 은 async — 상태줄 재진술이 설 때까지 짧게 폴링(마이크로태스크 흘리기).
      for (var i = 0; i < 50; i++) {
        await new Promise(function (r) { setTimeout(r, 10); });
        var note = document.getElementById('dataPickerNote').textContent;
        if (note.indexOf('새목록.xlsx') >= 0) break;
      }
    } finally {
      window.Bridge.pickDataFile = origPick;
    }
    out.browse_kept_open =
      !document.getElementById('dataPickerModal').classList.contains('hidden');
    out.browse_restated =
      document.getElementById('dataPickerCurrent').textContent.indexOf('새목록.xlsx') >= 0;
    var pin2 = document.getElementById('dataPickerPin');
    // 가시성까지 단언한다 — click 은 hidden 을 통과하므로 존재만으론 눈과 다른 결론이 난다.
    out.browse_pin_visible = !!pin2 && getComputedStyle(pin2).display !== 'none'
      && pin2.offsetParent !== null;
    Modal.close('dataPickerModal');
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
  out.pending = false;
  window.__dataPicker = out;
  })();
})()
"""



# 편집(탭) 저장 게이트의 **입력 지연**(리뷰 R2) — `s.dirty` 는 `change`(=blur)에서만 갱신되는데
# 「변경 저장」이 그때까지 disabled 면 방금 고친 사람의 첫 클릭이 삼켜진다(비활성 버튼은 click 을
# 내지 않는다). 정적 검사로는 못 본다 — 실 DOM 에서 타이핑 이벤트를 흘려 버튼 상태를 되읽는다.
_EDITOR_SAVE_GATE_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    var snap = {
      section:'filename', sections:['template','binding','filename'], notice:null,
      reachable:{template:true, binding:true, filename:true}, dirty_sections:[],
      is_draft:false, dirty:false, changes:{}, revisions:{template:1, binding:1},
      context:{entry_reason:'voluntary', evidence:{}, return_context:{}},
      template_path:"C:/t/공고서.hwpx", template_name:"공고서.hwpx", field_count:1,
      schema_summary:"", fields:[], raw_block:"", gate:null, gate_error:false,
      data_path:"", data_name:"", data_sheet:"", record_count:0,
      source_fields:[], active_source_fields:[], ignored_source_fields:[],
      active_count:0, ignored_count:0, ignored_expanded:false, sample_rows:[],
      type_options:["text"], fmt_options:{text:[]},
      name:"공고서", pattern:"공고서-{{공고번호}}", pattern_preview:"공고서-1.hwpx",
      has_unsaved_work:false, editing_origin:"공고서",
      provenance:null, rows:[],
      counts:{filled:0,empty:0,unmapped:0}, preview_empties:[], preview_index:0, preview_count:0,
      is_complete:true, schema_only:true
    };
    window.Nav.go('editor', {force:true});
    window.__push('editor', snap);
    var saveBtn = function () {
      return document.querySelector('#editor-foot [data-act="save"]');
    };
    out.save_present = !!saveBtn();
    // ① 깨끗한 저장본 — 바꾼 것이 없으니 잠겨 있다(U2 §2.4 게이트 자체).
    out.clean_disabled = !!(saveBtn() && saveBtn().disabled);
    // ② 이름을 고친다. 발신은 change(=blur) 뿐이지만 **버튼은 지금 열려야** 첫 클릭이 산다.
    var nameEl = document.getElementById('editorName');
    nameEl.focus();
    nameEl.value = '공고서 수정';
    nameEl.dispatchEvent(new Event('input', {bubbles:true}));
    out.typing_enabled = !!(saveBtn() && !saveBtn().disabled);
    // 「변경 버리기」도 **같은 술어로 지금** 열려야 한다(§2.17 · PR #354 리뷰) — 저장만
    // 열면 clean 세션 타이핑 직후 버리기의 첫 클릭이 삼켜진다(같은 결함류의 다른 버튼).
    var discardBtn = function () {
      return document.querySelector('#editor-foot [data-act="discard-patch"]');
    };
    out.typing_discard_enabled = !!(discardBtn() && !discardBtn().disabled);
    // ②-b 그 사이 push 가 와 footer 가 다시 그려져도 열린 채여야 한다 — 직접 켠 버튼만으로는
    // 재렌더 한 번에 도로 잠기고, 그 push 는 사용자가 만지지 않은 다른 이유로도 온다.
    window.__push('editor', snap);
    out.rerender_keeps_enabled = !!(saveBtn() && !saveBtn().disabled);
    // ③ 되돌려 치면 편집이 없던 것과 같다 — 열어 둔 채로 두지 않는다.
    nameEl.value = '공고서';
    nameEl.dispatchEvent(new Event('input', {bubbles:true}));
    out.reverted_disabled = !!(saveBtn() && saveBtn().disabled);
    out.reverted_discard_disabled = !!(discardBtn() && discardBtn().disabled);
    // ④ 파일명 패턴도 같은 자격(재구성되는 입력이라 위임으로 받는다).
    var patEl = document.querySelector('#editor-body input[data-act="pattern"]');
    out.pattern_present = !!patEl;
    if (patEl) {
      patEl.focus();
      patEl.value = '공고서-{{공고번호}}-2';
      patEl.dispatchEvent(new Event('input', {bubbles:true}));
      out.pattern_typing_enabled = !!(saveBtn() && !saveBtn().disabled);
      // 다음 단계로 넘어가기 전에 이 편집을 되돌린다 — 안 그러면 대기 상태가 그대로 이어져
      // 다음 단계의 「깨끗한 상태」 측정이 거짓 양성이 된다(프로브가 자기 잔재를 재는 꼴).
      patEl.value = snap.pattern;
      patEl.dispatchEvent(new Event('input', {bubbles:true}));
      patEl.blur();
    }
    nameEl.blur();
    // ⑤ 매핑 행의 상수 입력도 **같은 자격**이다(리뷰 R3) — 머리·꼬리 입력만 세면 이 자리에서만
    // 첫 클릭이 삼켜진다. 행이 있는 단계로 갈아 끼우고 같은 것을 잰다.
    var rowSnap = Object.assign({}, snap, {
      section:'binding', schema_only:false, field_count:1,
      source_fields:['품명'], active_source_fields:['품명'], active_count:1,
      sample_rows:[['A']], type_options:['text','const'], fmt_options:{text:[],const:[]},
      rows:[{index:0, template_field:'품명', inferred_type:'text', context:'', source:'',
             type:'const', const:'고정값', fmt:'', confirmed:false, touched:true,
             has_content:true, suggestion_score:0, preview:'고정값', preview_empty:false,
             preview_error:false, row_state:'unconfirmed'}]
    });
    window.__push('editor', rowSnap);
    out.row_clean_disabled = !!(saveBtn() && saveBtn().disabled);
    var constEl = document.querySelector('#editor-body [data-act="row-const"]');
    out.row_const_present = !!constEl;
    if (constEl) {
      constEl.focus();
      constEl.value = '고정값 수정';
      constEl.dispatchEvent(new Event('input', {bubbles:true}));
      out.row_typing_enabled = !!(saveBtn() && !saveBtn().disabled);
      constEl.value = '고정값';
      constEl.dispatchEvent(new Event('input', {bubbles:true}));
      out.row_reverted_disabled = !!(saveBtn() && saveBtn().disabled);
      // ⑥ **타이핑 도중 푸시**(리뷰 R4 P1) — `#editor-body` 가 옛 스냅샷으로 다시 그려져도
      // 친 값이 살아 있어야 한다. 값이 사라졌는데 버튼만 열려 있으면 사용자는 사라진 값을
      // 저장했다고 믿는다(조용한 소실 + 그것을 가리는 표지).
      constEl.value = '푸시 중 입력';
      constEl.dispatchEvent(new Event('input', {bubbles:true}));
      window.__push('editor', rowSnap);
      var after = document.querySelector('#editor-body [data-act="row-const"]');
      out.row_value_survives_push = !!after && after.value === '푸시 중 입력';
      out.row_enabled_after_push = !!(saveBtn() && !saveBtn().disabled);
      // ⑦ 되돌릴 자리가 사라지면(단계 이동) 대기도 버려야 한다 — 남은 편집이 없는데 열린
      // 버튼은 거짓말이다.
      window.__push('editor', snap);
      out.gone_control_disables = !!(saveBtn() && saveBtn().disabled);
      window.__push('editor', rowSnap);
      constEl = document.querySelector('#editor-body [data-act="row-const"]');
      if (constEl) constEl.blur();
    }
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
  return out;
})()
"""


# 편집기 「템플릿」 탭 관리 표면(F8 — tpl 화면 사망의 승계, §10.17.2 판정 D) — 구
# _TPL_LIST_GROUP_PROBE_JS 의 재작성: 검증 대상(그룹 헤더·접힘 뷰 제외·⋮ 구성·＋그룹지정
# 칩·이동 다이얼로그 개폐·퇴화 평면)이 전부 편집기 표면으로 살아 이주했으므로 합성 editor
# 스냅샷을 실 render() 에 흘려 같은 항목을 #scr-editor 에서 되읽는다(부록 B-9 자동판 승계).
# 신규 항목: 상단 행동 줄 3버튼·결과 재진술 줄·채움 고지 줄·개수/루트 캡션.
_EDITOR_LIBRARY_MANAGE_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('editor', {force:true});
    var acts = [{key:'compile', label:'누름틀 변환'}, {key:'review', label:'검토'}];
    var H = function (name, group, cur, warns) {
      return {key:name, group:group, name:name, path:'C:/lib/' + name,
              badge_label:'누름틀', badge_level:'ok', is_error:false, detail:'필드 3개',
              fill_warns:warns || [], actions:acts, current:!!cur};
    };
    var draft = {section:'template', sections:['template','binding','filename'],
      reachable:{template:false, binding:false, filename:false}, dirty_sections:[],
      is_draft:true, dirty:false, changes:{}, revisions:{},
      context:{entry_reason:'voluntary', evidence:{}, return_context:{}},
      template_path:'', template_name:'',
      field_count:0, fields:[], raw_block:'', gate_error:false, gate:null, notice:null,
      editing_origin:'',
      library:{
        hwpx:{flat:false, count:4, group_names:['계약','입찰'], dir:'C:/lib', sections:[
          {group:'입찰', collapsed:false, count:2,
           items:[H('a.hwpx','입찰',true), H('b.hwpx','입찰',false)]},
          {group:'계약', collapsed:true, count:1, items:[H('c.hwpx','계약',false)]},
          {group:'', collapsed:false, count:1,
           items:[H('d.hwpx','',false,['빈 값 2건은 공란으로 채워집니다'])]}
        ]},
        txt:{flat:true, count:1, group_names:[], dir:'C:/txt', sections:[
          {group:'', collapsed:false, count:1,
           items:[{key:'메모.txt', group:'', name:'메모', path:'C:/txt/메모.txt',
                   field_count:2, error:'', current:false}]}
        ]},
        result:{text:'검토: 문제 없음', level:'ok'}
      }};
    window.__push('editor', draft);
    var host = document.getElementById('scr-editor');
    // 상단 행동 줄(죽은 .tpl-libbar 승계) — 가져오기·폴더 일괄(#339)·새 TXT·새로고침.
    out.toolbar = ['import-template', 'import-folder', 'lib-new-txt', 'lib-refresh'].map(function (a) {
      return !!host.querySelector('button[data-act="' + a + '"]');
    });
    out.grp_heads = host.querySelectorAll('.job-grp-head').length;          // 입찰·계약·그룹없음
    out.rows_visible = host.querySelectorAll('.libselrow').length;          // 계약 접힘 제외 → 3+1
    out.row_more = host.querySelectorAll('[data-act="lib-more"]').length;   // 모든 가시 행
    out.grp_more = host.querySelectorAll('.grp-more').length;               // 명명 그룹만
    out.assign_chips = host.querySelectorAll('[data-act="lib-assign"]').length; // 무그룹 행만(d+메모)
    out.fill_warn = /빈 값 2건/.test(host.textContent);                     // #154 사전 고지 승계
    var res = host.querySelector('.run-result');
    out.result_line = !!res && /검토: 문제 없음/.test(res.textContent) &&
      res.className.indexOf('ok') !== -1;                                   // #tplResult 승계
    out.band_caption = /4개/.test(host.textContent) && /C:\/lib/.test(host.textContent);
    // 앞선 프로브가 Popover 바깥-닫기 pointerdown 을 남기면 "다음 click 1회 소비" 플래그가
    // 상주해 우리 첫 click 을 먹는다(교차 프로브 오염) — 던짐 click 으로 청소.
    var flush = function () { document.body.click(); };
    var menu = document.getElementById('tplRowMenu');
    // 그룹 있는 HWPX 행 ⋮ = [링1 상태 동사(변환·검토), 이동, 삭제] — 소비 동사 없음(행 버튼 소유).
    flush();
    host.querySelector('[data-act="lib-more"][data-key="b.hwpx"]').click();
    out.menu_shown = getComputedStyle(menu).display !== 'none';
    out.hwpx_menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    document.body.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true}));
    out.menu_closed = getComputedStyle(menu).display === 'none';
    // 무그룹 TXT 행 ⋮ = [내용 편집, 삭제](이동은 칩 소관).
    flush();
    host.querySelector('[data-act="lib-more"][data-key="메모.txt"]').click();
    out.txt_menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    document.body.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true}));
    // 그룹 헤더 ⋮ = [개명, 해산].
    flush();
    host.querySelector('.grp-more').click();
    out.group_menu_items = Array.prototype.map.call(
      menu.querySelectorAll('button[data-menu]'), function (b) { return b.dataset.menu; });
    document.body.dispatchEvent(new MouseEvent('pointerdown', {bubbles:true}));
    // ＋그룹지정 칩 → 이동 다이얼로그(기존 #tplMoveModal DOM 재사용).
    out.move_hidden_before = document.getElementById('tplMoveModal').classList.contains('hidden');
    flush();
    host.querySelector('[data-act="lib-assign"]').click();
    out.move_shown_after_chip = !document.getElementById('tplMoveModal').classList.contains('hidden');
    window.Modal.close('tplMoveModal');
    (function () {
      var card = document.querySelector('#tplMoveModal .modal-card');
      var ev = new Event('transitionend', {bubbles:true});
      Object.defineProperty(ev, 'propertyName', {value:'opacity'});
      card.dispatchEvent(ev);
    })();
    // 퇴화 평면(그룹 0개) — 헤더 없는 행 나열.
    draft.library.hwpx = {flat:true, count:1, group_names:[], dir:'C:/lib',
      sections:[{group:'', collapsed:false, count:1, items:[H('d.hwpx','',false)]}]};
    draft.library.txt = {flat:true, count:0, group_names:[], dir:'C:/txt', sections:[]};
    window.__push('editor', draft);
    out.flat_heads = host.querySelectorAll('.job-grp-head').length;
    out.flat_rows = host.querySelectorAll('.libselrow').length;
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
    window.Nav.go('editor', {force:true});
    var it = function (name, badge, level, cur) {
      return {key:name, name:name, path:'C:/lib/' + name, badge_label:badge, badge_level:level,
              is_error:false, detail:'필드 3개', current:!!cur};
    };
    var draft = {section:'template', sections:['template','binding','filename'],
      reachable:{template:false, binding:false, filename:false}, dirty_sections:[],
      is_draft:true, dirty:false, changes:{}, revisions:{},
      context:{entry_reason:'voluntary', evidence:{}, return_context:{}},
      template_path:'', template_name:'',
      field_count:0, fields:[], raw_block:'', gate_error:false, gate:null, notice:null,
      editing_origin:'',
      library:{hwpx:{flat:false, sections:[
        {group:'입찰', collapsed:false, count:2,
         items:[it('a.hwpx','준비됨','ok',true), it('b.hwpx','변환 필요','warn',false)]},
        {group:'계약', collapsed:true, count:1, items:[it('c.hwpx','준비됨','ok',false)]},
        {group:'', collapsed:false, count:1, items:[it('d.hwpx','준비됨','ok',false)]}
      ]}, txt:{flat:true, sections:[]}}};
    window.__push('editor', draft);
    var host = document.getElementById('scr-editor');
    out.grp_heads = host.querySelectorAll('.job-grp-head').length;              // 입찰·계약·그룹없음
    out.rows_visible = host.querySelectorAll('.libselrow').length;             // 계약 접힘 → 2+1
    out.pick_btns = host.querySelectorAll('.libselrow button[data-act="use-library"]').length;
    out.current_marked = host.querySelectorAll('.libselrow.cur').length;       // 현 선택(a) 1
    out.import_btn = !!host.querySelector('button[data-act="import-template"]');
    // F6 PR-B — 「HWPX 서식만」 단일 매체 고지는 2밴드 구조로 대체됐다: 각 밴드가 자기
    // 산출물(파일 생성/복사)을 말한다. 두 고지의 실재를 되읽는다.
    out.filter_notice = /\.hwpx 문서 파일을 만드는/.test(host.textContent)
      && /복사해 쓰는 작업/.test(host.textContent);
    var caret = host.querySelector('.job-grp-head[aria-expanded="false"] .grp-caret');
    out.caret_collapsed = caret ? getComputedStyle(caret).visibility : 'missing';
    // F13 — 그룹 헤더에 안정 id(재렌더 뒤 포커스 복원 근거). F14 — 파일명 칸 말줄임/축소.
    var head0 = host.querySelector('.job-grp-head');
    out.grp_head_has_id = !!(head0 && head0.id);
    var fn = host.querySelector('.libselrow .fname');
    out.fname_ellipsis = fn ? getComputedStyle(fn).textOverflow : 'missing';
    out.fname_minwidth = fn ? getComputedStyle(fn).minWidth : 'missing';
    // 퇴화 평면(그룹 0개) — 헤더 없는 선택 행 나열.
    draft.library = {hwpx:{flat:true, sections:[{group:'', collapsed:false, count:1, items:[it('d.hwpx','준비됨','ok',false)]}]},
                     txt:{flat:true, sections:[]}};
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
_VIEW_ORDER_PROBE_SETUP_JS = r"""
(() => {
  /* 전체 표시순서 축(재작성 F3)의 **실 왕복**을 본다: 선택기 change → Python `set_view_order`
     → push 재렌더가 방금 고른 값을 유지하는가. 정적 계약은 요소 존재까지만 보고, 이 축의
     결함류는 "왕복 뒤 옛 값으로 되돌아간다"라 실행으로만 잡힌다.
     **양성대조 선행**(measurement-litmus): 프로브가 실물을 재는지 먼저 증명한다 — 부팅 직후
     값이 기본값과 같음을 확인하고(렌더가 실제로 이 요소를 쓴다), 그 다음 바뀌는지 본다.
     같은 값이면 통과하는 프로브였다면 두 단언 중 하나는 반드시 깨진다. */
  const out = { pending: true };
  window.__viewOrder = out;
  const sel = document.getElementById('jobOrderSel');
  out.present = !!sel;
  if (!sel) { out.pending = false; return; }
  out.options = Array.from(sel.options).map((o) => o.value);
  Bridge.initial('job')
    .then((snap) => {
      out.control_before = sel.value === snap.view_order && sel.value === 'sourceDesc';
      out.note_before = String(document.getElementById('jobOrderNote').textContent || '');
      sel.value = 'sourceAsc';
      sel.dispatchEvent(new Event('change'));
      return new Promise((r) => setTimeout(r, 400));   // 왕복 + push 재렌더 여유
    })
    .then(() => {
      out.after_roundtrip = sel.value;                 // 되돌아왔으면 'sourceDesc'
      return Bridge.call('job', 'set_view_order', { value: 'sourceDesc' });
    })
    .then(() => new Promise((r) => setTimeout(r, 200)))
    .then(() => { out.restored = sel.value; })
    .catch((e) => { out.error = String((e && e.message) || e); })
    .then(() => { out.pending = false; });
})();
"""

_DATA_SHEET_PROBE_SETUP_JS = r"""
(() => {
  /* ⤢ 데이터 펼침 면의 실 DOM 이동·복귀(#271/#272)와 범위 편집기 footer 의 자리(F3).
     열기가 **Python 왕복 뒤**로 바뀌었으므로(초안이 서야 면이 연다) 동기 프로브로는 열리기
     전을 재게 된다 — 완료 표지를 남기고 폴링한다.

     이 프로브가 세우는 전제 둘, 둘 다 실패 표본에서 왔다:
     ① **앞 프로브의 늦은 push 를 먼저 흘려보낸다**(quiesce). 실 세션은 작업 미선택이라
        `!has_job` 스냅샷이 도착하면 `syncModeDisplay` 가 펼침 면을 정당하게 닫는다 —
        내 면이 남의 push 에 닫히면 "이동 안 됨"으로 오독된다(관측자 오염의 반대 방향).
     ② 자기 판은 자기가 세운다: 표 헤더 고정을 재려면 실제로 그려진 표가 있어야 한다.
     초안 생성만 자기 액션으로 스텁하고 복원은 "내 스텁일 때만"(프로브 교차 오염 금지). */
  const out = { pending: true };
  window.__dataSheet = out;
  const ids = ['jobRecsHead', 'jobOrderBar', 'jobFilterChips', 'jobTableHost',
               'jobSelStrip', 'jobColPanel', 'jobRangeFoot'];
  const nodes = ids.map((id) => document.getElementById(id));
  out.present = nodes.every(Boolean);
  if (!out.present) { out.pending = false; return; }
  const parents = nodes.map((el) => el.parentNode);
  const slot = document.getElementById('dataSheetSlot');
  const trigger = document.getElementById('jobDataExpand');
  const real = window.Bridge.call;
  const mine = function (screen, action, payload) {
    if (screen === 'job' && action === 'range_draft_open') return Promise.resolve({ ok: true });
    return real(screen, action, payload);
  };
  const restoreCall = () => { if (window.Bridge.call === mine) window.Bridge.call = real; };
  const settle = (id) => {
    const card = document.querySelector('#' + id + ' .modal-card');
    const ev = new Event('transitionend', { bubbles: true });
    Object.defineProperty(ev, 'propertyName', { value: 'opacity' });
    card.dispatchEvent(ev);
  };
  setTimeout(() => {                       // ① 앞 프로브의 늦은 push 를 흘려보낸다
    window.Bridge.call = mine;
    // `Nav.go('job')` 를 부르지 않는다: 화면 전환은 REFRESH_ON_NAV 로 **실 refresh** 를 쏘고,
    // 그 응답(작업 미선택 스냅샷)이 내가 연 면을 닫는다. 부팅 기본 화면이 이미 job 이다.
    window.__push('job', {                 // ② 자기 판
      job_name: '공고서', has_job: true, out_dir: 'C:\Results',
      data_label: 'd.csv', data_source_label: 'd.csv (파일)', data_notice: null,
      template_name: 't.hwpx', template_path: 'C:\t.hwpx', template_missing: false,
      filename_pattern: 'doc-{{seq}}', has_data: true, record_count: 2, selected_count: 2,
      view_order: 'sourceDesc', order_note: '보이는 순서대로 생성됩니다.',
      range_draft: { open: true, dirty: false, sel_count: 2, selected_only: false,
                     view_order: 'sourceDesc' },
      records: [{ index: 1, selected: true, name: 'doc-001.hwpx', summary: '사무비품' },
                { index: 0, selected: true, name: 'doc-002.hwpx', summary: '전산장비' }],
      filter: { active: false, reapply_available: false, reapply_hint: '', search: '',
                chips: [], definition: '', branches: [],
                columns: [{ name: '공고명', kind: 'text' }] },
      table: { columns: [{ name: '공고명', kind: 'text' }],
               rows: [{ index: 1, selected: true, name: 'doc-001.hwpx', summary: '사무비품',
                        cells: [[['사무비품', false]]] },
                      { index: 0, selected: true, name: 'doc-002.hwpx', summary: '전산장비',
                        cells: [[['전산장비', false]]] }],
               visible_count: 2, hidden_selected: [] },
      restate: { origin: 'manual', filter_active: false, in_def: 0, extra: 0, sample: [1, 0] },
      preflight: { level: 'ok', text: 'ok' }, mirror: [], drift: [], name_tokens: [],
      gate: { enabled: true, level: '', text: '생성 준비' },
    });
    trigger.focus();
    trigger.click();
    setTimeout(() => {
      try {
        out.moved = nodes.every((el) => slot.contains(el));
        out.not_moved = ids.filter((id, i) => !slot.contains(nodes[i]));
        out.first_sticky = getComputedStyle(
          document.querySelector('#jobTableHead th:first-child')).position === 'sticky';
        // footer 는 면 안에서만 선다 — 화면 안에서 숨긴 것과 같은 CSS 규칙의 반대 분기.
        out.foot_shown_in_sheet =
          getComputedStyle(document.getElementById('jobRangeFoot')).display !== 'none';
        // 닫기는 **비동기**다(리뷰 1R: 초안 폐기 성사 뒤에 닫는다) — 클릭 직후를 재면 아직
        // 안 끝난 복귀를 실패로 읽는다. 퇴장 전이를 정착시키며 복귀를 폴링한다.
        document.getElementById('dataSheetClose').click();
        let tries = 0;
        const finish = () => {
          try { settle('dataSheet'); } catch (e2) { /* 카드 부재 = 이미 정착 */ }
          const done = nodes.every((el, i) => el.parentNode === parents[i]);
          if (done || tries++ > 40) {
            out.restored = done && document.activeElement === trigger;
            restoreCall();
            out.pending = false;
            return;
          }
          setTimeout(finish, 50);
        };
        setTimeout(finish, 50);
      } catch (e) {
        out.error = 'throw:' + (e && e.message);
        // 실패해도 면은 **반드시** 닫는다: 열린 채 남기면 뒤 프로브의 포커스·모달 스택이
        // 통째로 오염돼 남의 계약이 대신 깨진다(프로브가 프로브를 오염시키는 자리).
        try { window.SurfaceSheet.closeAndRestore('dataSheet'); settle('dataSheet'); } catch (e2) {}
        restoreCall();
        out.pending = false;
      }
    }, 0);
  }, 300);
})();
"""

_RANGE_DRAFT_PROBE_SETUP_JS = r"""
(() => {
  /* 범위 편집기 초안 거래(F3)를 실 창에서 본다: ⤢ 로 열면 초안이 서고 footer 가 면 안에
     보이며, 닫으면 초안이 정리된다. 정적 계약은 배선까지만 보고 — 이 표면의 결함류는
     "면은 열렸는데 초안이 안 섰다 / 닫았는데 초안이 남았다"라 상태를 되읽어야 잡힌다.
     데이터가 없으면 초안 생성이 **거절**되는 것이 계약이므로, 그 거절도 함께 확인한다
     (양성대조: 거절 경로와 성사 경로가 다른 값을 내야 프로브가 실물을 잰 것이다). */
  const out = { pending: true };
  window.__rangeDraft = out;
  const expand = document.getElementById('jobDataExpand');
  const foot = document.getElementById('jobRangeFoot');
  out.present = !!(expand && foot);
  if (!out.present) { out.pending = false; return; }
  out.foot_hidden_in_screen = getComputedStyle(foot).display === 'none';
  Bridge.call('job', 'range_draft_open', {})
    .then(() => { out.opened_without_data = true; },
          () => { out.opened_without_data = false; })   // 데이터 없음 = 거절이 계약
    .then(() => Bridge.initial('job'))
    .then((snap) => {
      out.draft_state = snap.range_draft;
      out.pending = false;
    })
    .catch((e) => { out.error = String((e && e.message) || e); out.pending = false; });
})();
"""

_PREVIEW_DRAWER_PROBE_SETUP_JS = r"""
(() => {
  /* 미리보기 드로어(F5)를 실 창에서 본다. 정적 계약은 배선까지만 보고, 이 표면의 결함류는
     "면은 떴는데 값이 안 그려졌다 / 승인 버튼이 요구 없이 서 있다 / 닫았는데 상태만 닫혔다"라
     실제로 렌더된 DOM 을 되읽어야 잡힌다.

     **양성대조 선행**(measurement-litmus): 먼저 데이터 없이 열어 **거절**을 받는다. 거절과
     성사가 서로 다른 값을 내야 이 프로브가 실물을 잰 것이다 — 둘 다 통과하면 프로브가
     아무것도 안 재고 있다는 뜻이다.

     스텁은 자기 액션(`preview_open`)만 가로채고 복원은 "내 스텁일 때만" 한다(프로브 교차
     오염 금지 — 앞 블록의 복원이 뒤 블록의 발신을 삼키는 표본이 이미 있다). */
  const out = { pending: true };
  window.__previewDrawer = out;
  const btn = document.getElementById('jobPreviewOpen');
  const modal = document.getElementById('previewModal');
  out.present = !!(btn && modal);
  if (!out.present) { out.pending = false; return; }
  out.hidden_before = modal.classList.contains('hidden');
  const real = window.Bridge.call;
  const mine = function (screen, action, payload) {
    if (screen === 'job' && action === 'preview_open') return Promise.resolve({ ok: true });
    if (screen === 'job' && action === 'preview_close') return Promise.resolve(null);
    return real(screen, action, payload);
  };
  const restoreCall = () => { if (window.Bridge.call === mine) window.Bridge.call = real; };
  // 양성대조: 스텁을 걸기 **전에** 실 액션으로 거절을 받는다(데이터·작업 없음).
  Bridge.call('job', 'preview_open', {})
    .then(() => { out.opened_without_data = true; },
          () => { out.opened_without_data = false; })
    .then(() => new Promise((r) => setTimeout(r, 60)))   // 앞 프로브의 늦은 push 를 흘려보낸다
    .then(() => {
      window.Bridge.call = mine;
      window.__push('job', {
        job_name: '공고서', has_job: true, out_dir: 'C:\Results',
        data_label: 'd.csv', data_source_label: 'd.csv (파일)', data_notice: null,
        template_name: 't.hwpx', template_path: 'C:\t.hwpx', template_missing: false,
        filename_pattern: 'doc-{{seq}}', has_data: true, record_count: 2, selected_count: 2,
        view_order: 'sourceDesc', order_note: '보이는 순서대로 생성됩니다.',
        range_draft: { open: false, dirty: false, sel_count: 0, selected_only: false,
                       view_order: 'sourceDesc' },
        records: [], filter: { active: false, reapply_available: false, reapply_hint: '',
                               search: '', chips: [], definition: '', branches: [], columns: [] },
        table: { columns: [], rows: [], visible_count: 0, hidden_selected: [] },
        restate: { origin: null, filter_active: false, in_def: 0, extra: 0, sample: [] },
        preflight: { level: 'ok', text: 'ok' }, mirror: [], drift: [], name_tokens: [],
        gate: { enabled: false, level: 'warn', text: '나갈 이름과 값을 승인해야 생성할 수 있습니다.' },
        review: { required: true, approved: false, risk: 'presentation',
                  targets: ['금액(표시형)'], first_run: false, unknown_baseline: false,
                  structure_changed: false },
        preview: {
          open: true, can_open: true, pos: 1, total: 2, filename: 'doc-002.hwpx',
          rows: [{ name: '공고명', value: '전산장비' }, { name: '금액', value: '' }],
          evidence: { policy: 'formatted_value',
                      rows: [{ name: '금액', value: '1,000', note: '표시형이 적용된 값입니다.' }],
                      note: '' },
          can_approve: true, empty_note: '',
        },
      });
      btn.focus();
      btn.click();
      setTimeout(() => {
        try {
          out.flag_shown = getComputedStyle(
            document.getElementById('jobReviewFlag')).display !== 'none';
          out.opened = !modal.classList.contains('hidden');
          out.pos_text = document.getElementById('previewPos').textContent;
          out.prev_disabled = document.getElementById('previewPrev').disabled;
          out.next_disabled = document.getElementById('previewNext').disabled;
          out.value_rows = document.querySelectorAll('#previewRows .mir-row').length;
          out.evidence_rows =
            document.querySelectorAll('#previewEvidenceRows .mir-row').length;
          out.filename = document.getElementById('previewFilename').textContent;
          // 「적용 범위」 축 부재 되읽기(U2 §2.3) — 정적 계약이 id 부재를 보지만, 실렌더에서
          // JS 가 그 자리를 다시 만들지 않는지는 여기서만 확인된다.
          out.scope_axis = !!document.getElementById('previewScope');
          out.approve_shown = getComputedStyle(
            document.getElementById('previewApprove')).display !== 'none';
          // 원격 닫힘: Python 이 닫았다고 말하면 DOM 도 닫힌다(상태의 진실은 스냅샷이다).
          // 세션은 살려 둔다 — 트리거가 살아 있어야 "초점이 트리거로 돌아온다"를 잴 수 있다
          // (세션째 죽이면 트리거가 비활성이 되고, 그건 초점 **대안 착지**라는 다른 계약이다).
          window.__push('job', { job_name: '공고서', has_job: true,
            preview: { open: false, pos: 0, total: 2, can_open: true },
            review: { required: false, approved: false, risk: '', targets: [],
                      first_run: false, unknown_baseline: false, structure_changed: false },
            records: [], mirror: [], drift: [], name_tokens: [],
            gate: { enabled: false, level: 'warn', text: '' } });
          setTimeout(() => {
            try {
              const card = modal.querySelector('.modal-card');
              const ev = new Event('transitionend', { bubbles: true });
              Object.defineProperty(ev, 'propertyName', { value: 'opacity' });
              card.dispatchEvent(ev);              // 비동기 닫힘을 정착시킨다
              out.closed_by_state = modal.classList.contains('hidden');
              out.focus_returned = document.activeElement === btn;
              // 초점이 문서 맨 앞으로 떨어지지 않았다는 사실도 따로 센다 — `focus()` 가
              // 조용한 no-op 이 되는 경로(비활성 트리거)의 증상이 정확히 이것이다.
              out.focus_on_body = document.activeElement === document.body;
            } catch (e) { out.error = String((e && e.message) || e); }
            restoreCall();
            out.pending = false;
          }, 40);
        } catch (e) {
          out.error = String((e && e.message) || e);
          restoreCall();
          out.pending = false;
        }
      }, 60);
    })
    .catch((e) => {
      out.error = String((e && e.message) || e);
      restoreCall();
      out.pending = false;
    });
})();
"""

_CHAIN_RECOVERY_PROBE_SETUP_JS = r"""
(() => {
  /* 호출 직렬화 체인이 **실패 한 번으로 죽지 않는지** 실물로 본다(리뷰 5R).
     rejected 링이 CALL_CHAINS 에 남으면 이후 같은 키의 모든 호출이 그 링에 .then 으로 붙어
     영영 실행되지 않는다 — 접힘 영속이 한 번 실패했다고 그 화면의 탭·검색·필터가 세션 내내
     죽는 결함이다. 정적 계약으로는 "catch 가 있다"까지만 보이므로 실행으로 증명한다. */
  const out = { pending: true };
  window.__chainRecovery = out;
  const key = 'probe:' + String(Math.random());
  const seen = [];
  Intent.chained(key, () => Promise.reject(new Error('의도된 실패')))
    .then(() => { out.rejected_surfaced = false; },
          () => { out.rejected_surfaced = true; })   // 실패는 호출자에게 그대로 전해진다
    .then(() => Intent.chained(key, () => { seen.push('after'); return 'ok'; }))
    .then((v) => { out.after_value = v; })
    .catch((e) => { out.error = String((e && e.message) || e); })
    .then(() => {
      out.after_ran = seen.length === 1;
      out.pending = false;
    });
})();
"""

_ACTION_ROUNDTRIP_PROBE_SETUP_JS = r"""
(() => {
  const out = { pending: true, families: {} };
  window.__actionRoundtrip = out;
  const specs = [
    ['editor', 'editor', 'new_session'],
    ['job', 'job', 'refresh'],
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

  // 카드 상태 계약 표본(F8 이주) — .tplcard 는 tpl 화면 전용이 아니게 되어(피커 소비)도
  // 죽은 화면 문법 대신, 같은 선택자 묶음(hover·aria-current)의 생존 소비자 .jcard
  // (손상 작업 danger 카드가 계속 씀)로 잰다. 표본은 자급(self-seed — #137 교차오염 교훈).
  var card = document.createElement('div');
  card.className = 'jcard';
  card.setAttribute('data-selftest-probe', 'card');
  document.body.appendChild(card);
  var baseCard = styleOf(card);
  card.setAttribute('aria-current', 'true');
  var selectedCard = styleOf(card);
  card.remove();

  // 로케이트 어포던스 표본 자급(self-seed) — 종전엔 앞 프로브(job_mirror)가 남긴 DOM 에
  // 무임승차했는데, 데이터-우선 무조건 렌더가 빈 경로 스냅샷으로 정직하게 지우면서 교차
  // 의존이 드러났다(#137 프로브 교차오염 교훈). 이 프로브의 목적은 아이콘·접근 이름
  // *스타일 계약*이므로 표본을 직접 심는다(렌더 경로 검증은 각 화면 프로브 소관).
  if (!document.querySelector('.track-btn')) {
    var ot = document.getElementById('jobOutTrack');
    if (ot && window.PathTrack) {
      ot.innerHTML = window.PathTrack.affordances('C:\\Probe\\Results', {only: ['reveal', 'copy']});
    }
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
      // 15px 구획 역할의 표본 — 구 .job-sec-head(F6 PR-B)·.tpl-band .tb-t(F8, tpl 화면
      // 사망)가 차례로 죽어, 같은 역할군(base.css 한 선택자 묶음)의 정적 생존 표본
      // .modal-card h3 로 잰다(모달 DOM 은 셸 레벨 상주).
      section: style('.modal-card h3'),
      zone: style('#scr-job .zone-cap')
    },
    job_steps: Array.from(document.querySelectorAll('#scr-job .zone-cap')).map(function (e) {
      var label = e.cloneNode(true);
      label.querySelectorAll('button').forEach(function (b) { b.remove(); });
      return label.textContent.trim();
    }),
    job_step_badges: document.querySelectorAll('#scr-job .zone-cap .znum').length,
    // (H-04 매체 sunken 2면 항목은 은퇴 — 승계 표면인 편집기 밴드는 .grp 문법이고 그 시각
    //  계약은 editor_lib_manage 프로브가 잰다. 카드 상태 계약만 .jcard 로 승계.)
    card_base: baseCard,
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

    /* 워크카드 재질 — 승계처는 작업대 카드다(F6 PR-B): wbCard 는 render 가 wc-render 를
       입히지만 세션 없는 정적 상태에선 .wb-preview 뿐이라, 계약대로 두 클래스를 얹어 잰다. */
    var cardRender = document.getElementById('wbCard');
    var savedCardClass = cardRender.className;
    cardRender.className = 'wb-preview wc-render f-gulimche';
    var dot = document.querySelector('#wbDots .wc-dot');
    var madeDot = false;
    if (!dot) {
      dot = document.createElement('button');
      dot.className = 'wc-dot';
      document.getElementById('wbDots').appendChild(dot);
      madeDot = true;
    }
    var cr = cardRender && getComputedStyle(cardRender);
    var ds = dot && getComputedStyle(dot);
    var dm = dot && getComputedStyle(dot, '::before');
    out.workcard = {
      max_height: cr && cr.maxHeight, overflow_y: cr && cr.overflowY,
      font_family: cr && cr.fontFamily,
      /* 높이 계약이 열 수에 따라 갈린다 — 2열은 남는 높이(flex:1), 1열 퇴화는 캡.
         어느 쪽을 쟀는지 함께 실어야 단언이 창 폭에 따라 거짓말하지 않는다. */
      narrow: window.innerWidth <= 920, flex_grow: cr && cr.flexGrow,
      dot_hit: ds && [ds.width, ds.height], dot_mark: dm && [dm.width, dm.height],
      dots_overflow: getComputedStyle(document.getElementById('wbDots')).overflow
    };
    if (madeDot) dot.remove();
    cardRender.className = savedCardClass;

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
    window.Modal.open('txtEditModal', {
      initialFocus: document.getElementById('txtEditName'), returnFocus: trigger
    });
    var formModal = document.getElementById('txtEditModal');
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
    finishModal('txtEditModal');
    out.menu_trigger_restored = document.activeElement === trigger;

    // 두 겹에서 Escape 한 번은 최상위만 퇴장시킨다.
    window.Modal.open('txtEditModal', { returnFocus: trigger });
    window.Modal.open('confirmModal', { returnFocus: trigger });
    document.dispatchEvent(new KeyboardEvent('keydown', { key:'Escape', bubbles:true }));
    out.escape_one_layer = document.getElementById('confirmModal').classList.contains('is-closing') &&
      !document.getElementById('txtEditModal').classList.contains('is-closing');
    finishModal('confirmModal');
    window.Modal.close('txtEditModal'); finishModal('txtEditModal');

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


# 편집기 「템플릿」 탭 매체 2밴드(F6 PR-B) — 합성 스냅샷으로 실 render() 를 돌려 되읽는다.
# 겨누는 것 둘: ①TXT 밴드(선택 버튼 포함)가 실 DOM 에 서는가 ②TXT 세션의 탭이 Python 이
# 파생한 2개(파일 이름 탭 부재, §3.2)로 그려지는가. 스냅샷 성형 자체는 헤드리스가 본다 —
# 여기는 렌더러가 그 계약을 실제로 그리는지의 실물 가드다(editor_guard 프로브 동형).
_EDITOR_TXT_BAND_PROBE_SETUP_JS = r"""
(() => {
  const out = { pending: true };
  window.__editorTxtBand = out;
  const finish = (why) => {
    /* 자기 판을 자기가 걷는다(프로브 교차 오염 금지) — 편집기는 셸을 덮는 화면이라
       그대로 두면 뒤따르는 프로브가 상단 탭을 「사라졌다」고 읽는다(editor_guard 동형). */
    try {
      window.Nav.go('job', { force: true });
      const home = document.querySelector('.navbtn[data-scr="job"]');
      if (home) home.focus();
    } catch (e) { out.teardown_error = String(e && e.message); }
    out.why = why;
    out.pending = false;
  };
  try {
    window.Nav.go('editor', { force: true });
    const base = {
      section: 'template', sections: ['template', 'binding', 'filename'],
      reachable: { template: false, binding: false, filename: false },
      dirty_sections: [], dirty: false, is_draft: true, changes: {}, context: {},
      revisions: {}, template_path: '', template_name: '', template_media: '',
      field_count: 0, fields: [], raw_block: '', gate: null, gate_error: false,
      notice: null, editing_origin: '', name: '', pattern: '', rows: [],
      source_fields: [], active_source_fields: [], ignored_source_fields: [],
      sample_rows: [], type_options: [], fmt_options: {}, provenance: null,
      library: {
        hwpx: { sections: [], flat: true },
        txt: {
          sections: [{ group: '', count: 1, collapsed: false, items: [
            { key: '기안.txt', name: '기안', path: 'C:/t/기안.txt',
              field_count: 3, error: '', current: false },
          ] }],
          flat: true,
        },
      },
    };
    window.__push('editor', base);
    const caps = Array.prototype.map.call(
      document.querySelectorAll('#editor-body .grp .cap'), (el) => el.textContent);
    out.bands = caps.filter((t) => t === 'HWPX 서식' || t === 'TXT 기안');
    out.txt_pick = !!document.querySelector(
      '#editor-body [data-act="use-library"][data-path="C:/t/기안.txt"]');
    window.__push('editor', Object.assign({}, base, {
      sections: ['template', 'binding'], template_path: 'C:/t/기안.txt',
      template_name: '기안.txt', template_media: 'txt',
    }));
    out.txt_tabs = document.querySelectorAll('#editor-steps .wstep-tab').length;
    finish('완료');
  } catch (e) {
    out.error = String(e && e.message);
    finish('예외');
  }
})();
"""


# TXT 검토·복사 작업대(재작성 F6 PR-A) — 합성 스냅샷으로 실 render() 를 돌려 되읽는다.
# 정적 계약이 못 보는 것 셋을 겨눈다: ①몰입 셸(상단 2탭 은닉)이 실제로 걸리는가 ②큐 퇴화가
# 큐 장치 3종을 실제로 감추는가 ③이탈이 **가드를 지나** 화면을 바꾸는가(발신 순서까지).
_WORKBENCH_PROBE_SETUP_JS = r"""
(function () {
  const out = { pending: true };
  window.__workbench = out;
  const seg = (t, kind, name) => ({ text: t, kind: kind || 'literal', name: name || '' });
  const snap = {
    open: true, job_name: '발주요청_기안', mode_label: '온나라 기안 검토·복사',
    view: 'filled', target_font: 'malgun', fullwidth: false,
    notice: { text: '', level: 'muted' },
    total: 3, copied_count: 1, is_complete: false,
    revision: { template: 1, binding: 4 },
    source_fields: ['부서', '사업명'],
    fmt_options: { text: [{ code: 'plain', label: '그대로' }] },
    type_options: [{ code: 'text', label: '텍스트' }],
    rows: [
      { name: '수신', state: 'fill', source: '부서', own: 'auto', manual: false,
        value: '회계과', fmt_kind: 'text', fmt_code: 'plain', suggest: '',
        can_revert: false, confirmed: true, blank_declared: false },
      { name: '비고', state: 'blank', source: '', own: '', manual: false, value: '',
        fmt_kind: 'text', fmt_code: 'plain', suggest: '', can_revert: false,
        confirmed: true, blank_declared: true },
    ],
    dirty: { count: 1, fields: [{ name: '수신' }], pending: false },
    can_save: true, save_block: '',
    guard: { armed: true, lines: ['복사 진행 1/3건 — 나가면 이 진행은 사라집니다.'] },
    card: {
      index: 0, has_current: true, queue_degenerate: false, position: 0, source_row: 7,
      // 경계는 Python 이 낸다(2R P1) — 표시 자리는 머리(0)인데 순회상으로는 **후미**인
      // 상태를 합성한다(복사 직후의 실물). 표면이 서수로 계산하면 여기서 갈린다.
      can_prev: true, can_next: false,
      // 큐 색인(4R P2) — 순차 이동만으로는 아는 행에 못 간다. 자리 라벨은 원본 행 번호다.
      index_map: [{ index: 0, row: 7, state: 'current', recheck: true },
                  { index: 1, row: 4, state: 'uncopied', recheck: false }],
      review_state: 'recheck', uncopied_count: 2, advance_after: false,
      segments: [seg('수신: '), seg('회계과', 'fill', '수신'), seg('', 'blank', '비고')],
      missing_fields: [], empty_fields: [],
      lint: { proportional: true, space_run: true, applied: false, active: true },
      last_copy: null, copied_total: 1,
    },
  };
  window.Nav.go('workbench');
  window.__push('workbench', snap);
  setTimeout(() => {
    try {
      out.screen_on = !!document.querySelector('#scr-workbench.on');
      out.nav_hidden = getComputedStyle(document.querySelector('.nav')).display === 'none';
      out.title = document.getElementById('wbTitle').textContent;
      out.position = document.getElementById('wbPosition').textContent;
      out.copied = document.getElementById('wbCopied').textContent;
      out.revision = document.getElementById('wbRevision').textContent;
      out.dirty_note = document.getElementById('wbDirtyNote').textContent;
      out.review = document.getElementById('wbReview').textContent;
      out.map_rows = document.querySelectorAll('#wbMapPanel tbody tr').length;
      out.declared = document.querySelectorAll('#wbMapPanel .mapval-declared').length;
      out.card_fill = document.querySelectorAll('#wbCard .seg-fill').length;
      out.card_blank = document.querySelectorAll('#wbCard .seg-blank').length;
      out.lint_shown = document.getElementById('wbLint').style.display !== 'none';
      // 린트는 표지 + **행동**이 한 벌이다(2R P2) — 경고만 두면 손잡이 없는 통보가 된다.
      out.lint_action = (function () {
        var b = document.querySelector('#wbLint [data-fullwidth]');
        return b ? b.getAttribute('data-fullwidth') + ':' + b.textContent : '';
      })();
      out.dots = Array.prototype.map.call(
        document.querySelectorAll('#wbDots .wc-dot'),
        function (d) { return d.getAttribute('title'); });
      out.font_value = document.getElementById('wbTargetFont').value;
      out.prev_disabled = document.getElementById('wbPrev').disabled;
      out.next_disabled = document.getElementById('wbNext').disabled;
      out.save_enabled = !document.getElementById('wbSaveRules').disabled;
      // 결과 → 규칙(계약 §11) — 조각이 토큰 신원을 지고 나가고, 누르면 소유 행이 선다.
      // 정적으로는 조각도 표도 다 있어 통과한다: 둘을 잇는 길만 없는 상태가 여기서만 잡힌다.
      out.card_tokens = document.querySelectorAll('#wbCard [data-token]').length;
      (function () {
        var s = document.querySelector('#wbCard [data-token="수신"]');
        if (s) s.click();
      })();
      out.aim_row = (function () {
        var a = document.activeElement;
        return a && a.tagName === 'TR' ? (a.getAttribute('data-name') || '') : '';
      })();
      // 강조는 CSS 파생이라 **실 스타일 계산**까지 봐야 참이다 — 표 클래스가 스타일시트와
      // 어긋나 있으면(구 `maptable`) 배선은 멀쩡한데 선 행이 아무 표지도 못 받는다.
      out.aim_marked = (function () {
        var a = document.activeElement;
        if (!a || a.tagName !== 'TR' || !a.cells.length) return '';
        return getComputedStyle(a.cells[0]).boxShadow;
      })();
      // 큐 퇴화 — 1건이면 순회 장치가 숨는다(정보가 없어서지 장식이라서가 아니다).
      window.__push('workbench', Object.assign({}, snap, {
        total: 1, copied_count: 0,
        card: Object.assign({}, snap.card, { queue_degenerate: true, position: 0 }),
      }));
      setTimeout(() => {
        try {
          out.degen_prev = getComputedStyle(document.getElementById('wbPrev')).display;
          out.degen_adv = getComputedStyle(document.querySelector('.wb-adv')).display;
          // 이탈이 가드를 지나는가 — Nav.go 가 위임하고, 위임이 발신 순서를 지키는지.
          const calls = [];
          const real = window.Bridge.call;
          window.Bridge.call = function (screen, action, payload) {
            if (screen === 'workbench') {
              calls.push(action);
              if (action === 'leave_guard') return Promise.resolve({ armed: false, lines: [] });
              return Promise.resolve({ ok: true });
            }
            return real(screen, action, payload);
          };
          window.Nav.go('job');
          setTimeout(() => {
            try {
              window.Bridge.call = real;
              out.leave_calls = calls;
              out.landed = !!document.querySelector('#scr-job.on');
            } finally { out.pending = false; }
          }, 260);
        } catch (e) { out.error = String(e); out.pending = false; }
      }, 120);
    } catch (e) { out.error = String(e); out.pending = false; }
  }, 160);
})();
"""


def _probe_late(window: "object", flag: str, expr: str) -> dict:
    """프로브의 비동기 단계가 끝나길 기다렸다가 결과 묶음(JSON)을 한 번에 회수한다.

    setTimeout 사슬·microtask 로 확정되는 값은 프로브의 동기 반환에 담기지 않는다. 플래그가
    설 때까지 짧게 폴링하고, 여러 값을 **한 표현식**으로 받아 회수 코드 자체를 최소로 둔다.
    """
    import time

    for _ in range(50):
        if window.evaluate_js(f"!!window.{flag}"):  # type: ignore[attr-defined]
            break
        time.sleep(0.05)
    return json.loads(window.evaluate_js(expr))  # type: ignore[attr-defined]


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
        # H-05: 콜드 부팅은 작업으로 진입한다.
        result["job_on"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.getElementById('scr-job').classList.contains('on')")
        # 홈 화면 사망(재작성 F2) — 카드 나열·두 트랙·group-by 렌즈는 사라지고 「문서 작업」
        # 라이브러리가 그 자리를 잇는다. 죽은 DOM 이 남아 있으면 부활 경로가 된다.
        result["home_screen_gone"] = window.evaluate_js(  # type: ignore[attr-defined]
            "!document.getElementById('scr-home') && !document.getElementById('homeBrowser')")
        # 라이브러리 표면 실재 — 축 4종(보기 탭·방식 칩·태그 facet·검색)과 2-pane 골격.
        result["library_surface"] = window.evaluate_js(  # type: ignore[attr-defined]
            "['scr-library','libraryViewTabs','libraryModeFilters','libraryFacets',"
            "'librarySearch','libraryList','libraryDetail','libraryCount']"
            ".every(function(i){return !!document.getElementById(i)})")
        # 보기 탭 4종이 계약(§19.6 표)대로 서 있고 하나만 선택돼 있다.
        result["library_view_tabs"] = window.evaluate_js(  # type: ignore[attr-defined]
            "Array.from(document.querySelectorAll('#libraryViewTabs [data-library-view]'))"
            ".map(function(b){return b.dataset.libraryView})")
        # 데이터 선택 진입점(재작성 F1) — 두 세션 표면(작업·기안)의 단일 출구 버튼 실재.
        # 구 2버튼('등록 데이터…'·'파일 선택…')과 pool 화면은 사망하고 다이얼로그가 승계했다.
        result["data_picker_buttons"] = window.evaluate_js(  # type: ignore[attr-defined]
            "['jobBtnPickData']"
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
        # 표시순서 축의 실 왕복(재작성 F3) — 되돌림 결함은 실행으로만 잡힌다.
        window.evaluate_js(_VIEW_ORDER_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        order_deadline = time.monotonic() + 6.0
        while time.monotonic() < order_deadline:
            if window.evaluate_js(  # type: ignore[attr-defined]
                "!!(window.__viewOrder && !window.__viewOrder.pending)"
            ):
                break
            time.sleep(0.1)
        result["view_order"] = window.evaluate_js("window.__viewOrder")  # type: ignore[attr-defined]
        # ⤢ 데이터 펼침 면(실 DOM 이동·복귀 + footer 자리) — 열기가 왕복 뒤라 비동기.
        window.evaluate_js(_DATA_SHEET_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        sheet_deadline = time.monotonic() + 6.0
        while time.monotonic() < sheet_deadline:
            if window.evaluate_js(  # type: ignore[attr-defined]
                "!!(window.__dataSheet && !window.__dataSheet.pending)"
            ):
                break
            time.sleep(0.1)
        result["data_sheet"] = window.evaluate_js("window.__dataSheet")  # type: ignore[attr-defined]
        # 범위 편집기 초안 거래(재작성 F3) — 면과 초안이 같이 서고 같이 죽는지 상태로 본다.
        window.evaluate_js(_RANGE_DRAFT_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        draft_deadline = time.monotonic() + 6.0
        while time.monotonic() < draft_deadline:
            if window.evaluate_js(  # type: ignore[attr-defined]
                "!!(window.__rangeDraft && !window.__rangeDraft.pending)"
            ):
                break
            time.sleep(0.1)
        result["range_draft"] = window.evaluate_js("window.__rangeDraft")  # type: ignore[attr-defined]
        # 미리보기 드로어(재작성 F5) — 값·이름·증거가 실제로 그려지고 상태가 면을 여닫는지.
        # 회수는 공용 `_probe_late` 로 접는다: 실창에서만 도는 폴링 줄을 늘리면 커버리지
        # 플로어를 갉는다(위 머리말과 같은 규율).
        window.evaluate_js(_PREVIEW_DRAWER_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        result["preview_drawer"] = _probe_late(
            window, "__previewDrawer && !window.__previewDrawer.pending",
            "JSON.stringify(window.__previewDrawer)",
        )
        # 탭 처분 3택의 **이어짐**(F7 1R P1) — 「저장하고 이동」이 저장 뒤 실제로 이동을
        # 재발신하는지. 배선·문안·판정이 다 제자리여도 성사 뒤 이어짐만 끊길 수 있고,
        # 그건 정적 계약이 못 본다(실 클릭·실 모달·실 재발신 순서로만 드러난다).
        window.evaluate_js(_EDITOR_GUARD_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        result["editor_guard"] = _probe_late(
            window, "__editorGuard && !window.__editorGuard.pending",
            "JSON.stringify(window.__editorGuard)",
        )
        # 「변경 버리기」 취소 뒤 정합(§2.17 2R P2) — 대기 편집을 정산하고 확인을 여는가.
        # 비동기 도착 순서의 결함이라 정적 계약이 못 본다: 배선·문안·판정은 다 제자리이고
        # 큐에 든 blur 발신이 모달 뒤에 도착해 트리거를 분리시키는 것만 어긋난다.
        window.evaluate_js(_EDITOR_DISCARD_CANCEL_PROBE_JS)  # type: ignore[attr-defined]
        result["editor_discard_cancel"] = _probe_late(
            window, "__editorDiscardCancel && !window.__editorDiscardCancel.pending",
            "JSON.stringify(window.__editorDiscardCancel)",
        )
        # 편집기 「템플릿」 탭 매체 2밴드(F6 PR-B) — TXT 밴드 렌더 + TXT 세션 탭 2개.
        window.evaluate_js(_EDITOR_TXT_BAND_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        result["editor_txt_band"] = _probe_late(
            window, "__editorTxtBand && !window.__editorTxtBand.pending",
            "JSON.stringify(window.__editorTxtBand)",
        )
        # TXT 검토·복사 작업대(재작성 F6) — 몰입 셸·큐 퇴화·이탈 위임을 실 DOM 에서 되읽는다.
        window.evaluate_js(_WORKBENCH_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        result["workbench"] = _probe_late(
            window, "__workbench && !window.__workbench.pending",
            "JSON.stringify(window.__workbench)",
        )
        # 호출 직렬화 체인의 실패 복구(리뷰 5R) — 정적 계약이 못 보는 실행 성질이라 실물로.
        window.evaluate_js(_CHAIN_RECOVERY_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        chain_deadline = time.monotonic() + 5.0
        while time.monotonic() < chain_deadline:
            if window.evaluate_js(  # type: ignore[attr-defined]
                "!!(window.__chainRecovery && !window.__chainRecovery.pending)"
            ):
                break
            time.sleep(0.1)
        result["chain_recovery"] = window.evaluate_js(  # type: ignore[attr-defined]
            "window.__chainRecovery")
        # 커스텀 모달 접근성 동적 거동(#27/#28) — 정적 계약(role/aria)은 test_web_dom_contract 가
        # 보고, 여기선 실 브라우저에서 Modal 헬퍼가 초기포커스·Escape 닫기·트리거 복귀를 실제로
        # 수행하는지 되읽는다. 알려진 트리거(첫 내비 버튼)에 포커스를 두고 열었다가 Escape 로 닫는다.
        result["modal_a11y"] = window.evaluate_js(_MODAL_A11Y_PROBE_JS)  # type: ignore[attr-defined]
        # promise 다이얼로그 해소값(#92 리뷰 #1) — 프로브가 .then 으로 stash 한 값을 별도
        # evaluate_js 로 되읽는다(마이크로태스크는 앞 스크립트 스택 해제 시 이미 플러시됨).
        # 첫 confirm=true(확인 클릭), 재진입 confirm=false(즉시 안전측 거절)여야 한다.
        result["modal_confirm_serial"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({ first: window.__cf1, second: window.__cf2 })")
        # 반응형 경계(#27 → F2 PR-B 재정의) — 셸이 좌 레일에서 상단 토바로 바뀌면서 좁은 창의
        # 대응이 **열 접힘에서 토바 축약**으로 옮겼다: .app 은 항상 2행(토바+스테이지)이고,
        # 820px 아래에서 브랜드 워드마크·도구 값 라벨이 접혀 탭 4개의 자리를 먼저 지킨다
        # (도달성 우선). 그래서 되읽는 것도 열 수가 아니라 **탭 도달성 + 가로 오버플로**다 —
        # 좁은 창에서 탭이 잘려 화면에 못 가는 것이 이 셸의 진짜 회귀다. 정적 CSS 경계 존재는
        # test_web_dom_contract 가, 실 렌더는 여기가 가드. resize 는 OS 이벤트라 relayout
        # 안정까지 짧게 대기(게이트는 flaky 금지).
        grid_probe = """(function(){
          var app=document.querySelector('.app'),body=document.body;
          var tabs=Array.prototype.filter.call(document.querySelectorAll('.navbtn'),
            function(b){return b.offsetParent!==null});
          var brand=document.querySelector('.brand-name');
          return {rows:getComputedStyle(app).gridTemplateRows.split(' ').length,
                  tabs:tabs.length,
                  brand_visible:!!(brand&&brand.offsetParent!==null),
                  overflow:body.scrollWidth>body.clientWidth+1};})()"""
        window.resize(760, 600)  # type: ignore[attr-defined]  # 최소 크기 = 경계 아래 → 토바 축약
        time.sleep(0.6)
        result["grid_narrow"] = window.evaluate_js(grid_probe)  # type: ignore[attr-defined]
        window.resize(1440, 900)  # type: ignore[attr-defined]  # 새 기본 크기 = 토바 전개 + 기안 duo
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
        # 데이터-우선 prework 표면(§18.2) — 작업 미선택+데이터 마운트 합성 스냅샷의 실렌더
        # 되읽기. **mirror 프로브보다 먼저** 돈다: 이 프로브는 빈 경로 스냅샷을 남기므로,
        # 경로 어포던스(.track-btn)를 읽는 뒤 프로브(milestone_h)가 mirror 의 경로 있는
        # 스냅샷을 복원받게 순서로 오염을 차단한다(#137 프로브 교차오염 교훈).
        result["job_data_first"] = window.evaluate_js(_JOB_DATA_FIRST_PROBE_JS)  # type: ignore[attr-defined]
        # 체인 결과는 microtask 뒤에 확정된다 — 같은 프로브에서 동기로 읽을 수 없어 후속
        # 평가로 회수한다(즐겨찾기 쓰기 직렬화, 4R P2).
        # 비동기 단계(setTimeout 사슬·microtask)가 끝난 뒤 확정되는 값들은 한 번에 회수한다
        # — 프로브 회수 코드는 실창에서만 도는 줄이라 늘릴수록 커버리지 플로어를 갉는다.
        result["job_data_first"].update(_probe_late(
            window, "__favDone",
            "JSON.stringify({fav_chain: String(window.__favChain),"
            " fav_order: JSON.stringify(window.__favSent || null),"
            " fav_diag: JSON.stringify(window.__favDiag || null)})",
        ))
        result["job_data_first"].update(_probe_late(
            window, "__browseDone",
            "JSON.stringify({browse_pick_focus: String(window.__browsePickFocus),"
            " browse_sheet_closed: !!window.__browseSheetClosed,"
            " browse_close_focus: String(window.__browseCloseFocus)})",
        ))
        # 승계 어포던스 2건(F2 PR-B) — 탐색 착지가 끝난 **뒤에** 돈다(위 프로브 머리말).
        result["job_inherited"] = window.evaluate_js(  # type: ignore[attr-defined]
            _JOB_INHERITED_AFFORDANCE_PROBE_JS)
        # 활성 카드 승계·경고 카드 클릭 대체(U2 §4, #342) — 자기 합성 스냅샷을 밀므로 앞
        # 프로브의 비동기 사슬(즐겨찾기·탐색 착지)이 끝난 뒤에 돈다(교차오염 차단).
        result["job_active_card"] = window.evaluate_js(_JOB_ACTIVE_CARD_PROBE_JS)  # type: ignore[attr-defined]
        result["job_active_card"].update(_probe_late(
            window, "__candProbeDone",
            "JSON.stringify({warn_click_sends: String(window.__candSent)})",
        ))
        result["job_mirror"] = window.evaluate_js(_JOB_MIRROR_PROBE_JS)  # type: ignore[attr-defined]
        # 존 변이는 한 체인이라 둘째 토글 발신은 마이크로태스크 뒤다 — 같은 스크립트 안에서
        # 읽으면 아직 없다. 별도 evaluate(=새 JS 턴)로 되읽어 의도열 전체를 확인한다.
        result["job_mirror"]["row_toggle_values"] = window.evaluate_js(  # type: ignore[attr-defined]
            "window.__jobToggleValues")
        # 결과 3태 구획(F4) — 거울 프로브 뒤(같은 화면·같은 스냅샷 문맥)에서 돈다.
        result["job_result"] = window.evaluate_js(_JOB_RESULT_PROBE_JS)  # type: ignore[attr-defined]
        result["job_result"].update(_probe_late(
            window, "__resultProbeDone",
            "JSON.stringify({reject_state: String(window.__rejectState),"
            " reject_text: String(window.__rejectText),"
            " runlog_last: String(window.__runlogLast)})",
        ))
        # 협폭 적층 분기는 **창폭이 아니라 세션 패널 폭**(container query 900px)이 판정한다.
        # 좌 목록이 죽으며(F2 PR-B) 패널이 그만큼 넓어져 같은 창폭에서도 2열이 유지되므로,
        # 분기를 실제로 밟는 창으로 겨눈다 — 옛 1180 을 그대로 두면 프로브가 계약이 아니라
        # 옛 레이아웃 산술을 지키게 된다.
        window.resize(900, 820)  # type: ignore[attr-defined]
        time.sleep(0.4)
        result["job_density_narrow"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({columns:getComputedStyle(document.getElementById('jobDataGrid')).gridTemplateColumns,"
            "panel:Math.round(document.getElementById('jobPanel').getBoundingClientRect().width)})"
        )
        window.resize(1440, 900)  # type: ignore[attr-defined]
        time.sleep(0.4)
        # (구 「기안」 좌 목록·휘발 세션·펼침 면·밀도 프로브는 화면 사망(F6 PR-B)과 함께
        # 걷혔다 — 공용 팩토리 datazone.js 는 「문서 만들기」 프로브가, 몰입 셸·카드·린트는
        # workbench 프로브가, 커스텀 모달 표적은 txtEditModal 이 잇는다.)
        result["job_editmode"] = window.evaluate_js(_JOB_EDITMODE_PROBE_JS)  # type: ignore[attr-defined]
        # 데이터 선택 다이얼로그(재작성 F1 + U2 §2.7 단일 경로화) — pool 화면 사망의 승계처
        # 실렌더 되읽기. 「작업」이 활성인 지점에 둔다(다이얼로그가 Nav 를 옮기므로 화면 폭
        # 측정 프로브 앞이면 안 된다). 찾아보기 마운트가 비동기라 setup+stash 로 회수한다.
        window.evaluate_js(_DATA_PICKER_PROBE_SETUP_JS)  # type: ignore[attr-defined]
        result["data_picker"] = _probe_late(
            window, "__dataPicker && !window.__dataPicker.pending",
            "JSON.stringify(window.__dataPicker)",
        )
        time.sleep(0.4)  # 모달 닫힘 전이(CSS 160ms) 정산 — 다음 프로브의 클릭이 백드롭에 막히지 않게
        # 매핑 칩-라이브(슬라이스 5 PR-3) — 합성 매핑 스냅샷으로 실 render() 구동 후 칩·태그 되읽기.
        result["editor_chip"] = window.evaluate_js(_EDITOR_CHIP_PROBE_JS)  # type: ignore[attr-defined]
        # 편집(탭) 저장 게이트 — 타이핑이 change 로 확정되기 **전에** 주 행동이 열리는가.
        result["editor_save_gate"] = window.evaluate_js(  # type: ignore[attr-defined]
            _EDITOR_SAVE_GATE_PROBE_JS
        )
        # 편집기 라이브러리 관리 표면(F8 — 구 tpl 그룹 프로브의 승계 재작성): 그룹·⋮ 메뉴·
        # ＋그룹지정 칩·이동 다이얼로그·행동 줄·결과 줄 실렌더 되읽기.
        result["editor_lib_manage"] = window.evaluate_js(_EDITOR_LIBRARY_MANAGE_PROBE_JS)  # type: ignore[attr-defined]
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
            # 토바 높이는 라이브러리 2-pane 계산이 소비하는 **구조 치수**라 실측으로 핀한다
            # (리터럴 드리프트 = 페이지가 조용히 스크롤하는 자리, 지도 §10.9 판정 G).
            "topbar_h:Math.round(document.querySelector('.topbar').getBoundingClientRect().height),"
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
