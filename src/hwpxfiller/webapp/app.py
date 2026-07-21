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
import shutil
import sys
import threading
from pathlib import Path

from . import settings
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
from .screen_editor import EditorController
from .screen_home import HomeController
from .screen_job import JobController
from .screen_pool import PoolController
from .screen_quickdraft import QuickDraftController
from .screen_template import TemplateController
from .screens import (
    TxtController,
    collect_owned_paths,
    default_pool_registry,
    validate_owned_path,
)


WINDOW_TITLE = "HWPX Filler"  # 창 제목 = 파일 다이얼로그 소유주 창을 FindWindowW 로 찾는 키

# 파일 선택 다이얼로그 필터 — pick_data_file·pick_pool_data_file 공유 단일 출처(둘 다
# "엑셀/CSV 데이터" 참조를 다루므로 필터가 같다; 확장자 자체의 단일 출처는 EXCEL_FILTER_PATTERN).
_EXCEL_OR_ANY_FILTERS = [("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")]
# 템플릿 필터 — import_template_file·pick_template_path 공유 단일 출처(PR #70 리뷰).
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
        # 데이터셋 풀(#26) — 단일 인스턴스를 화면들이 공유: 에디터 자동등록(#3)·실행 겨눔(#6)·
        # 관리 화면(#4)의 변경이 서로 즉시 보인다(레지스트리는 무상태 디렉터리 어댑터).
        pool_registry = default_pool_registry()
        # 추적성 로케이트 화이트리스트(#53-B)용 레지스트리 참조(밑줄=js_api 반영 제외).
        self._job_registry = job_registry
        self._pool_registry = pool_registry
        # 화면 등록 — 새 화면 = 컨트롤러 1개 추가(순수 데이터는 dispatch, 네이티브는 아래 메서드).
        controllers = [
            # 홈(대시보드) — 허브. TXT 레지스트리는 즉시 기안·템플릿 관리와 공유(변경이 반영).
            # pool_registry 공유 = 데이터 관리에서 생긴 손상이 홈 KPI 경보에 즉시 보인다(#45).
            HomeController(job_registry, registry, self._push, pool_registry=pool_registry),
            TxtController(registry, self._push, pool_registry=pool_registry),
            # 빠른 기안(R-flow 블록 5, #90 슬라이스 7) — 작업의 휘발 쌍둥이. TXT 레지스트리는
            # txt·템플릿 관리와 공유(라이브러리 변경이 반영), 풀도 공유 인스턴스.
            QuickDraftController(registry, self._push, pool_registry=pool_registry),
            # 「작업」 화면(R-flow, #90) — 좌 목록 + 우 세션 패널 4존. 링1 VM 을 직접 소유해
            # 실행 결정 계약을 소비하는 **유일 세션 표면**이다(실행 화면은 슬라이스 3에서 사망 —
            # 게이트 패리티 도달, 레일 「실행」 동시 제거, 부록 A-4-35~37·#94 중복 자연 소멸).
            JobController(job_registry, self._push, pool_registry=pool_registry),
            # 템플릿 관리(#13) — TXT 레지스트리는 즉시 기안과 공유(변경이 양쪽에 반영).
            TemplateController(registry, self._push),
            # 데이터 관리(#26 #4) — 등록 데이터 참조·수명.
            PoolController(pool_registry, self._push),
        ]
        # 에디터의 템플릿 라이브러리 = tpl 화면의 VM **같은 인스턴스**(PR-4 리뷰 F2):
        # 별도 인스턴스면 두 표면의 스캔 캐시가 갈라져(가져오기·삭제가 한쪽에만 반영) 신규
        # 1단계 피커가 관리 화면과 다른 목록을 조용히 보인다(라이브러리=단일 실체).
        tpl_ctrl = next(c for c in controllers if c.name == "tpl")
        controllers.insert(
            2,
            EditorController(
                job_registry, self._push,
                pool_registry=pool_registry,
                template_library=tpl_ctrl.vm,
                # 1단계 피커 그룹 구획 = tpl 화면과 **같은 hwpx 그룹 모델**(#108 슬라이스 3):
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
        return self._controller(screen).dispatch(action, payload or {})

    def set_theme(self, mode: str) -> str:
        """테마 선택 영속 — 프런트 토글이 부른다(#74). 확정값 반환(비유효는 ValueError)."""
        settings.save_theme(mode)
        return mode

    # pick_template_file(생 파일 직접 로드)은 R-info 2부(신규 1단계=라이브러리 정본)로
    # 소비자가 소멸해 제거 — 바깥 파일의 유일 입구는 import_template_file(가져오기=복사).
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
                return f"ERROR: '{sheet}' 시트를 찾을 수 없습니다 — 시트를 다시 선택하세요."
            self._controller(screen).load_data_path(path, sheet=sheet)
        except Exception as exc:  # noqa: BLE001  (사용자에 시끄럽게 반환)
            return f"ERROR: {exc}"
        return Path(path).name

    def copy_clipboard(self, screen: str) -> dict:
        """작업점 카드 렌더를 OS 클립보드로(복사=완료, 결정 16). 리포트를 돌려줘 웹이 재진술.

        복사 후 큐를 전진시킨다(작업점→처리 후미, 전진 opt-in) — 큐 상태 기제는 컨트롤러의
        :meth:`~hwpxfiller.webapp.screens.TxtController.note_copied` 가 소유(클립보드 쓰기는
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
# 되읽는다. 알려진 트리거(첫 내비 버튼)에 포커스 → pasteModal 열기 → Escape → 복귀 확인.
# IIFE 가 JSON 직렬화 가능한 객체를 반환하고, 게이트 테스트가 각 필드를 단언한다.
_MODAL_A11Y_PROBE_JS = r"""
(function () {
  var trigger = document.querySelector('.navbtn');
  trigger.focus();
  var before = document.activeElement.getAttribute('data-scr');
  window.Modal.open('pasteModal', { initialFocus: document.getElementById('pasteText') });
  var opened = !document.getElementById('pasteModal').classList.contains('hidden');
  var focusIn = document.activeElement.id;
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  var closed = document.getElementById('pasteModal').classList.contains('hidden');
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
  var cClosed = cm.classList.contains('hidden');
  var cDisplayClosed = getComputedStyle(cm).display;         // 닫힌 뒤 'none'
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
  return {
    opened: opened,               // 열기 후 hidden 해제됐는가
    focus_in: focusIn,            // 초기 포커스가 모달 안(pasteText)으로 들어갔는가
    closed_by_escape: closed,     // Escape 로 닫혔는가
    focus_before: before,         // 열기 직전 트리거(내비 data-scr)
    focus_restored: restored,     // 닫은 뒤 포커스가 트리거로 복귀했는가
    confirm_display_closed_before: cDisplayClosedBefore,  // #86: 열기 전 display(none 기대)
    confirm_opened: cOpened,      // #86: Modal.confirm 이 hidden 해제했는가
    confirm_display_open: cDisplayOpen,  // #86/B-9: 열린 동안 display(flex 기대)
    confirm_focus: cFocus,        // #86: 초기 포커스가 취소(머무르기)인가
    confirm_reentry_alerts: reentryAlerts,       // #92 #1: 재진입 거절이 loud 였는가(1 기대)
    confirm_body_after_reentry: bodyAfterReentry, // #92 #1: 첫 본문이 덮이지 않았는가
    confirm_trap_wrapped: trapWrapped,           // #92 #1: Tab 이 모달 안에서 순환했는가
    confirm_closed: cClosed,      // #86: 확인 클릭 후 다시 hidden 인가
    confirm_display_closed: cDisplayClosed,  // #86/B-9: 닫힌 뒤 display(none 기대, hidden 이 flex 를 이긴다)
    non_modal_open_rejected_loud: openRejected,   // #132.4: .modal 없는 open 이 loud 거절+미개방인가
    non_modal_close_rejected_loud: closeRejected  // #132.4: .modal 없는 close 도 loud 거절인가
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
      var picked = await p1;
      // (2) 취소 경로 — 다시 열고 Escape → null 로 해소(로드 없음).
      var p2 = window.SheetPicker.choose('job', payload);
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
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
  ['txt', 'editor', 'job'].forEach(function (scr) {
    window.pywebview.api.initial(scr).then(function (s) { window.__snaps[scr] = s; });
  });
  window.Nav.go('txt');  // 스크롤은 가시 화면에서만 유효 → txt 가시화
})()
"""

_PRESERVE_REAL_PROBE_JS = r"""
(function () {
  var out = {}, snaps = window.__snaps || {};
  ['txt', 'editor', 'job'].forEach(function (scr) {
    try {
      if (!snaps[scr]) { out[scr] = 'no-snap'; return; }
      window.__push(scr, snaps[scr]);   // 실 render() (Preserve.around 래핑)
      out[scr] = 'ok';
    } catch (e) { out[scr] = 'throw:' + (e && e.message); }
  });
  // txt 스크롤 보존 end-to-end: 작업점 카드 렌더를 강제로 길게 → 오버플로 → 스크롤 → 재렌더 →
  // 유지? 카드 렌더는 링1 render_segments(card.segments)를 페인트하므로(웹 정규식 사망, PR-3),
  // template_text 가 아니라 card.segments 를 200줄로 덮어 오버플로를 만든다.
  try {
    var snap = snaps['txt'];
    if (!snap) { out.txt_scroll_top = 'no-snap'; return out; }
    var segs = [];
    for (var i = 0; i < 200; i++) { segs.push({ text: '라인 ' + i + '\n', kind: 'literal', name: '' }); }
    snap.card = snap.card || {};
    snap.card.segments = segs;
    window.__push('txt', snap);
    var box = document.getElementById('txtCardRender');
    box.scrollTop = 150;
    window.__push('txt', snap);         // 실 재렌더 — Preserve 가 스크롤 복원해야
    out.txt_scroll_top = document.getElementById('txtCardRender').scrollTop;
  } catch (e) { out.txt_scroll_top = 'throw:' + (e && e.message); }
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
      table:{columns:['공고명','금액'],
             rows:[{index:0, selected:true, name:'doc-001.hwpx', summary:'전산장비',
                    cells:[[['전산',true],['장비',false]], [['1,000,000원',false]]]}],
             visible_count:1,
             hidden_selected:[{index:1, selected:true, name:'doc-002.hwpx', summary:'사무비품'}]},
      restate:{origin:'manual', filter_active:true, in_def:1, extra:1, sample:[0]},
      preflight:{level:'ok', text:'ok'},
      mirror:[
        {name:'공고명', state:'filled', acknowledged:false, value:'전산장비 (표본 · 외 1개 값)', formatted:false},
        {name:'금액', state:'filled', acknowledged:false, value:'2,000,000원', formatted:true},
        {name:'낙찰율', state:'missing', acknowledged:false, value:'(미입력) 선택 2행 중 1행에서 값이 비어 있습니다.', formatted:false},
        {name:'비고', state:'blank', acknowledged:false, value:'(의도적 빈칸)', formatted:false}
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
    out.tbl_mark = (function(){ var m = document.querySelector('#jobTableBody mark');
      return m ? m.textContent : ''; })();
    out.ficos = document.querySelectorAll('#jobTableHead .fico[data-col]').length;
    out.chips_text = document.getElementById('jobFilterChips').textContent;
    out.branch_prune = !!document.querySelector('#jobFilterChips [data-prune="공고명"]');
    out.strip_shown = getComputedStyle(document.getElementById('jobSelStrip')).display !== 'none';
    out.strip_text = document.getElementById('jobSelStrip').textContent;
    // 스트립 항목별 × 해제 어포던스(리뷰 #6 — 진술만 하고 행동을 못 주면 반쪽).
    out.strip_unsel = !!document.querySelector('#jobSelStrip [data-unsel="1"]');
    out.sel_line = document.getElementById('jobRestate').textContent;
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
    out.rows_visible = document.querySelectorAll('#jobListHwpx .job-item').length;
    out.grp_more = document.querySelectorAll('#jobListHwpx .grp-more').length;
    out.row_more = document.querySelectorAll('#jobListHwpx .job-more[data-more]').length;
    var caretOf = function (expanded) {
      var c = document.querySelector(
        '#jobListHwpx .job-grp-head[aria-expanded="' + expanded + '"] .grp-caret');
      return c ? getComputedStyle(c).visibility : 'missing';
    };
    out.caret_collapsed = caretOf('false');
    out.caret_expanded = caretOf('true');
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

# txt 데이터 존(전-선언 큐 선택 · 블록 3, 슬라이스 6 PR-2b) — 합성 스냅샷을 실 render() 에
# 흘려 datazone.js **두 번째 인스턴스**가 txt 화면에서: 가시 행 테이블 + <mark> 하이라이트 +
# 선두 「큐」 열 표지(작업점 ▶·대기 순번) + 칩 줄 + 필터 밖 선택 스트립 + 열 패널 기본
# 닫힘([hidden] vs display:flex — 부록 B-9 자동 눈검증)을 실 WebView2 에서 되읽는다.
# 작업 화면 인스턴스와의 격리(같은 클래스·다른 id)도 여기서 실증된다.
_TXT_ZONE_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('txt');
    var snap = {
      template_name:'샘플기안', template_text:'제목: {{공고명}}',
      tokens:[{name:'공고명', state:'fill'}],
      record_count:2,
      data_label:'d.csv', data_source_label:'파일: d.csv', data_key:'file:c:/d/d.csv',
      has_data:true, selected_count:2,
      filter:{active:true, reapply_available:false, search:'전산',
              chips:['(공고명) 포함 「전산」'], definition:'(공고명) 포함 「전산」',
              branches:['공고명'],
              columns:[{name:'공고명', kind:'text', active:false}]},
      table:{columns:['공고명'],
             rows:[{index:0, selected:true, qpos:1, copied:false, current:true,
                    cells:[[['전산',true],['장비 구매',false]]]}],
             visible_count:1,
             hidden_selected:[{index:1, selected:true, qpos:2, copied:false, current:false}]},
      // 작업점 카드(블록 3, 결정 16) — 상태 색인·채움 표지 삼분 세그먼트·동사 게이트.
      card:{index:0, has_current:true, is_copied:false, position:1,
            uncopied_count:2, copied_count:0, selected_count:2, is_complete:false,
            advance_after:false,
            segments:[{text:'제목: ', kind:'literal', name:''},
                      {text:'전산장비 구매', kind:'fill', name:'공고명'},
                      {text:'', kind:'blank', name:'담당자'}],
            missing_fields:[], empty_fields:['담당자'],
            index_map:[{index:0, state:'current', has_gap:false},
                       {index:1, state:'uncopied', has_gap:true}],
            // 선언-조건부 정렬 린트(결정 17) — 비례폭 선언 + 원문에 정렬 런 = 경보 상태.
            lint:{proportional:true, space_run:true, applied:false, active:true}},
      target_font:'malgun'
    };
    window.__push('txt', snap);
    out.rows = document.querySelectorAll('#txtTableBody tr[data-i]').length;
    out.mark = (function(){ var m = document.querySelector('#txtTableBody mark');
      return m ? m.textContent : ''; })();
    // 작업점 카드 되읽기 — 코드블록 렌더(채움 표지 삼분)·상태 색인 점·복사 동사(우상단).
    out.card_render = document.getElementById('txtCardRender').textContent;
    out.card_fill = !!document.querySelector('#txtCardRender .seg-fill');
    out.card_blank = !!document.querySelector('#txtCardRender .seg-blank');
    out.card_dots = document.querySelectorAll('#txtCardDots .wc-dot').length;
    out.card_current_dot = !!document.querySelector('#txtCardDots .wc-dot.current');
    out.card_gap_dot = !!document.querySelector('#txtCardDots .wc-dot.gap');
    // 복사 동사는 카드에 결속되고(전역 버튼 사망), 작업점이 있으면 활성.
    var cp = document.getElementById('txtCardCopy');
    out.card_copy_enabled = !!cp && !cp.disabled;
    out.card_global_copy_dead = !document.getElementById('btnCopy')
      && !document.getElementById('btnSave');  // 전역 복사·저장 버튼 소멸(결정 16·18)
    out.card_readout = document.getElementById('txtCardReadout').textContent;
    // 대상 글꼴 선언(결정 17) — 콤보 동기 + 원문 렌더가 선언 글꼴 클래스를 추종한다.
    out.font_sel = document.getElementById('txtTargetFont').value;
    out.font_class = document.getElementById('txtCardRender').className;
    // 정렬 린트 — 경보 줄이 실제로 서고 처방 버튼이 있는가(선언-조건부 발화의 렌더 되읽음).
    out.lint_shown = !document.getElementById('txtCardLint').hidden;
    out.lint_text = document.getElementById('txtCardLint').textContent;
    out.lint_fix = (function(){ var b = document.getElementById('txtLintAction');
      return b ? b.dataset.act : ''; })();
    // T3 가드 본문 합성기(순수) — 수치 재진술이 종류별로 서는지(결정 27). 앞머리는 제스처별로
    // 갈리고(데이터 교체 / 새 기안, #126) 잃는 것의 열거는 같은 술어를 공유한다.
    var guardState = {armed:true, sel_count:5, in_def:3, extra:2, filter_active:true,
                      filter_parts:2, copied_count:2, queue_partial:true};
    out.guard_body = window.TxtScreen.guardBody(guardState, '다른 데이터를 겨누면');
    out.guard_body_newdraft = window.TxtScreen.guardBody(guardState, '새 기안을 시작하면');
    // 「＋ 새 기안」 가드 배선 존재 핀(#126) — 홈이 소비하는 진입점의 삭제 회귀 표식.
    out.new_draft_guard_wired = typeof window.TxtScreen.confirmNewDraftIfArmed === 'function';
    // 빈칸 게이트 본문(#125 · 결정 16) — 복사 **전** 확인 모달의 문안 합성. 종류별 수치·열거와
    // 6개 초과 접기를 되읽는다(모달이 스크롤로 번지면 결론 버튼이 안 보인다).
    out.copy_gate_body = window.TxtScreen.copyGateBody(
      {row:2, missing_fields:['납품기한'], empty_fields:['비고']});
    out.copy_gate_body_many = window.TxtScreen.copyGateBody(
      {row:0, missing_fields:['a','b','c','d','e','f','g','h'], empty_fields:[]});
    out.copy_gate_body_empty_only = window.TxtScreen.copyGateBody(
      {row:0, missing_fields:[], empty_fields:['비고']});
    // 선두 「큐」 열 — 작업점 ▶ 표지(링1 큐 모델 사영, 결정 16). 순번은 큐 순서로 그리는
    // 상태 색인(PR-3) 몫이라 이 표엔 렌더하지 않는다(비단조 오독 차단, PR-2b 리뷰).
    out.lead = (function(){ var d = document.querySelector('#txtTableBody .doc-body');
      return d ? d.textContent : ''; })();
    out.head_lead = (function(){ var h = document.querySelector('#txtTableHead th.doccol');
      return h ? h.textContent : ''; })();
    out.chips_text = document.getElementById('txtFilterChips').textContent;
    out.strip_shown = getComputedStyle(document.getElementById('txtSelStrip')).display !== 'none';
    out.strip_text = document.getElementById('txtSelStrip').textContent;
    out.panel_hidden = getComputedStyle(document.getElementById('txtColPanel')).display === 'none';
    out.sel_count = document.getElementById('txtSelCount').textContent;
    // 린트 침묵 상태의 **계산된 표시**(부록 B-9 결함 클래스 2): hidden 프로퍼티만 보면
    // display:flex 가 UA [hidden] 을 이겨 빈 상자가 남는 함정을 못 잡는다. 고정폭 선언으로
    // 되밀어 실제로 사라지는지 본다(이 재푸시는 위 되읽기가 모두 끝난 뒤라 무해).
    snap.target_font = 'gulimche';
    snap.card.lint = {proportional:false, space_run:true, applied:false, active:false};
    window.__push('txt', snap);
    out.lint_silent_display =
      getComputedStyle(document.getElementById('txtCardLint')).display;
    out.font_class_fixed = document.getElementById('txtCardRender').className;
    // 두 인스턴스 격리 — txt 존 렌더가 작업 화면 데이터 존 DOM 을 만지지 않는다(id 분리).
    out.job_body_untouched = document.getElementById('jobTableBody').children.length === 0
      || !document.querySelector('#jobTableBody #txtRow-0');
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
  return out;
})()
"""


# 빠른 기안(R-flow 블록 5, 슬라이스 7 PR-2) — 파이프라인 토큰 폼 + 미리보기 채움 표지가 실
# WebView2 에서 그려지는지 되읽는다(txt 존 프로브 동형: 합성 스냅샷 push → DOM 되읽기).
# 미리보기·폼은 push 구동 렌더라 동기로 잡힌다. **탭 전환(원문 편집)은 여기서 되읽지 않는다**:
# 이 엔진의 evaluate_js 에서 dispatchEvent 로 만든 합성 클릭이 innerHTML 로 파싱된 노드의
# 리스너에 닿지 않아(순수 createElement 노드는 발화되나 파싱 노드는 불발 — 실측) 실 사용자
# 클릭과 달리 프로브로 구동 불가하다. 탭 버튼 존재는 DOM 계약이, 라이브 재구성·(수정됨) 강등
# 거동은 백엔드 test_edit_source_live_retokenizes_and_demotes 가 가드한다.
_QUICKDRAFT_PROBE_JS = r"""
(function () {
  var out = {};
  try {
    window.Nav.go('quickdraft');
    // 표시 여부는 클래스 토큰이 아니라 **실제 렌더**(offsetParent)로 잰다(계측 리트머스).
    var vis = function (id) {
      var el = document.getElementById(id);
      return !!(el && el.offsetParent !== null);
    };
    // PR-4 음성 대조 — 빈손 세션엔 「새 기안」·출구 푸터가 서 있으면 안 된다(dead 크롬 금지).
    // "보인다" 판정에 판별력을 주려면 먼저 "안 보임"을 관측해야 한다(부재 판별력).
    window.__push('quickdraft', {origin:null, template_name:null, template_text:'', modified:false,
      tokens:[], segments:[], missing_fields:[], empty_fields:[], unfilled_count:0,
      has_data:false, data_label:'', data_kind:''});
    out.fresh_visible_before = vis('qdBtnFresh');
    out.foot_visible_before = vis('qdFoot');
    // 휘발 표지는 **빈손에서도** 서 있다(#134) — 알약과 별개 요소라 내용이 생겨도 안 꺼진다.
    out.volatile_visible_before = vis('qdVolatile');
    out.pill_before = document.getElementById('qdStatus').textContent;
    var snap = {
      origin:'lib', template_name:'개찰참관보고',
      template_text:'제목: {{사업명}}\n금액: {{추정가격}}', modified:false,
      tokens:[{name:'사업명', state:'man', value:'행정정보시스템'},
              {name:'추정가격', state:'blank', value:''}],
      segments:[{text:'제목: ', kind:'literal', name:''},
                {text:'행정정보시스템', kind:'fill', name:'사업명'},
                {text:'\n금액: ', kind:'literal', name:''},
                {text:'{{추정가격}}', kind:'missing', name:'추정가격'}],
      missing_fields:['추정가격'], empty_fields:[], unfilled_count:1,
      has_data:false, data_label:'', data_kind:'',
      // 대상 글꼴 선언·정렬 린트 합류(#134 (g)) — 미리보기가 선언을 추종하고, 린트가
      // 선언-조건부로 서며 처방 버튼을 다는지 되읽는다.
      target_font:'malgun',
      lint:{proportional:true, space_run:true, applied:false, active:true}
    };
    window.__push('quickdraft', snap);
    // 내용이 실려도 휘발 표지는 살아 있다 — 잃을 것이 생긴 시점에 경고가 꺼지지 않는다.
    out.volatile_visible = vis('qdVolatile');
    out.render_font_class = (document.getElementById('qdRender') || {}).className || '';
    out.lint_text = (document.querySelector('#qdBody .qd-lint .txt') || {}).textContent || '';
    out.lint_action = (document.getElementById('qdLintAction') || {}).dataset
      ? document.getElementById('qdLintAction').dataset.act : '';
    // man 칩(사람이 친 값)의 **중립 티어** — 채움 계열 초록(--a-ok)을 쓰면 "검증된 값"으로
    // 읽힌다. 색 이름이 아니라 실제 계산색을 토큰 값과 대조한다(테마 무관 판정).
    out.chip_man_color = (function () {
      var c = document.querySelector('#qdBody .qd-chip.man');
      return c ? getComputedStyle(c).color : '';
    })();
    out.ok_color = (function () {
      var probe = document.createElement('span');
      probe.style.color = 'var(--a-ok)';
      document.body.appendChild(probe);
      var v = getComputedStyle(probe).color;
      probe.remove();
      return v;
    })();
    // 파이프라인 토큰 폼 — 행 수·값 textarea·칩 상태(무결속 수기 = man, 빈칸 = blank).
    out.rows = document.querySelectorAll('#qdBody .qd-trow').length;
    out.val0 = (document.getElementById('qdVal-0') || {}).value;
    out.chip1 = (document.getElementById('qdChip-1') || {}).textContent;
    // 미리보기 채움 표지 삼분 — fill(음영 값)·missing({{토큰}} 빨강)이 실제로 페인트된다.
    var render = document.getElementById('qdRender');
    out.render_text = render ? render.textContent : '';
    out.seg_fill = !!document.querySelector('#qdRender .seg-fill');
    out.seg_missing = !!document.querySelector('#qdRender .seg-missing');
    // 미채움 알약(휘발 표지 3상) — missing 1건이면 「미채움 1」.
    out.pill = document.getElementById('qdStatus').textContent;
    // 두 탭 버튼 존재(원문 편집 탭 진입점) — 전환 거동은 위 주석대로 백엔드/DOM 계약이 가드.
    out.tabs = document.querySelectorAll('#qdBody .qd-tabs .btn').length;
    // 껍데기 격리 — 빠른 기안 폼(qd-trow)이 작업 화면 데이터 존 DOM 으로 새지 않는다(id 분리).
    // jobTableBody 는 앞선 job 프로브가 채우므로 '빈가'가 아니라 '누출 없음'으로 판정한다.
    out.job_body_untouched = !document.querySelector('#jobTableBody .qd-trow');
    // PR-4 — 템플릿이 실리면 「새 기안」·출구 푸터가 선다(빈손 음성 대조와 짝). 복사 버튼 존재,
    // 표지 토글은 미리보기 탭 기본이라 aria-pressed=true(표지 ON), 승격 2동사는 정직한 비활성.
    out.fresh_visible = vis('qdBtnFresh');
    out.foot_visible = vis('qdFoot');
    out.copy_btn = !!document.getElementById('qdBtnCopy');
    var mt = document.getElementById('qdMarkerToggle');
    out.marker_toggle = !!mt;
    out.marker_pressed = mt ? mt.getAttribute('aria-pressed') : null;
    out.save_job_disabled = (document.getElementById('qdBtnSaveJob') || {}).disabled;
    out.save_tpl_disabled = (document.getElementById('qdBtnSaveTpl') || {}).disabled;
    out.promote_note = (document.getElementById('qdPromoteNote') || {}).textContent || '';
    // 데이터가 없는 지금은 「데이터 해제」·경보 상자가 화면에서 사라져 있어야 한다.
    out.clear_visible_before = vis('qdBtnClearData');
    out.note_visible_before = vis('qdNote');

    // ---- PR-3: 데이터 선택 스냅샷 — 경량 슬롯(라벨·행 스테퍼)·파이프라인 2열·근사 제안이
    // 실 WebView2 에서 그려지는지 되읽는다(결정 30·31·34).
    var aimed = {
      origin:'lib', template_name:'개찰참관보고',
      template_text:'제목: {{사업명}}\n금액: {{추정가격}}', modified:false,
      tokens:[{name:'사업명', state:'auto', value:'행정정보시스템', col:'사업명',
               fmt_kind:'text', fmt_code:'', suggest:''},
              {name:'추정가격', state:'blank', value:'', col:'',
               fmt_kind:'text', fmt_code:'', suggest:'추정가격(원)'}],
      segments:[{text:'제목: ', kind:'literal', name:''},
                {text:'행정정보시스템', kind:'fill', name:'사업명'},
                {text:'\n금액: ', kind:'literal', name:''},
                {text:'{{추정가격}}', kind:'missing', name:'추정가격'}],
      missing_fields:['추정가격'], empty_fields:[], unfilled_count:1,
      has_data:true, data_label:'낙찰현황.csv', data_kind:'file',
      data_source_label:'파일: 낙찰현황.csv',
      columns:['사업명','추정가격(원)'], record_count:12, row_idx:2,
      row_label:'행정정보시스템 유지보수',
      fmt_options:{text:[{code:'', label:'그대로'}], date:[], amount:[], const:[]}
    };
    window.__push('quickdraft', aimed);
    out.data_label_text = document.getElementById('qdDataLine').textContent;
    // PR-4 소유권 색 — 자동 결속 값(사업명)은 own-auto 로 페인트된다(폼 칩과 한 색 언어).
    out.own_auto = !!document.querySelector('#qdRender .seg-fill.own-auto');
    // 행 스테퍼 — 양끝이 아니면 두 버튼 다 살아 있다(경계에서만 disabled).
    var prev = document.getElementById('qdRowPrev'), next = document.getElementById('qdRowNext');
    out.stepper = !!prev && !!next && !prev.disabled && !next.disabled;
    out.clear_visible = vis('qdBtnClearData');
    // 교체로 굳은 자리 경보가 실제로 보이는지(문구는 Python 이 합성) — 지금 스냅샷엔 없다.
    out.note_visible = vis('qdNote');
    // 파이프라인 2열 — 결속 토큰은 소스 select 가 그 열을 고른 채 뜨고 표시형이 함께 산다.
    var src0 = document.getElementById('qdSrc-0');
    out.src0 = src0 ? src0.value : null;
    out.fmt0 = !!document.getElementById('qdFmt-0');
    // 무결속 토큰: 소스는 (직접 입력), 표시형 없음(dead control 금지), 근사 제안 버튼 존재.
    var src1 = document.getElementById('qdSrc-1');
    out.src1 = src1 ? src1.value : null;
    out.fmt1 = !!document.getElementById('qdFmt-1');
    // 파이프라인 방향 화살표(결정 34 `소스→표시형`, #134) — 표시형이 실제로 뜨는 행에만
    // 선다(없는 단계를 암시하지 않는다). 결속 행(0)엔 있고 무결속 행(1)엔 없다.
    out.pipe_arrow0 = !!document.querySelector('.qd-trow[data-i="0"] .qd-pipe .qd-arrow');
    out.pipe_arrow1 = !!document.querySelector('.qd-trow[data-i="1"] .qd-pipe .qd-arrow');
    out.suggest1 = !!document.getElementById('qdTake-1');
    out.suggest_text = (document.querySelector('#qdBody .qd-suggest') || {}).textContent || '';
    // 경보 되읽기 — frozen_notice 가 실리면 상자가 뜨고 문구가 그대로 선다(알람 갈래).
    var alarmed = JSON.parse(JSON.stringify(aimed));
    alarmed.frozen_notice = '바뀐 데이터에 없는 열이라 1개 자리(추정가격)의 값이 이전 값 그대로 굳었습니다.';
    window.__push('quickdraft', alarmed);
    out.note_visible_after = vis('qdNote');
    out.note_text = document.getElementById('qdNote').textContent;
    out.error = null;
  } catch (e) { out.error = String((e && e.message) || e); }
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
    out.cards_visible = host.querySelectorAll('.tplcard').length;           // 계약 접힘 → 2+1
    out.grp_more = host.querySelectorAll('.grp-more').length;               // 명명 그룹만(그룹없음 제외)
    out.card_more = host.querySelectorAll('.tplcard-more').length;
    out.assign_chips = host.querySelectorAll('.tpl-assign').length;         // 「그룹 없음」 카드만
    var caretOf = function (expanded) {
      var c = host.querySelector('.job-grp-head[aria-expanded="' + expanded + '"] .grp-caret');
      return c ? getComputedStyle(c).visibility : 'missing';
    };
    out.caret_collapsed = caretOf('false');   // 접힌 그룹 캐럿 상시 노출
    out.caret_expanded = caretOf('true');      // 펼친 그룹 캐럿 호버 전 숨김
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


# ------------------------------------------------------------------ 자가검증(Q3)
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

    set_theme = os.environ.get("HWPX_SELFTEST_SET_THEME")
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
        # 홈(허브)이 기본 화면으로 뜨고 KPI 타일이 실렌더됐는지 되읽는다(#20 착지 심).
        result["home_on"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.getElementById('scr-home').classList.contains('on')")
        result["home_kpi_count"] = window.evaluate_js(  # type: ignore[attr-defined]
            "document.querySelectorAll('#homeKpis .kpi').length")
        # 데이터 관리 화면(#26 #4) — 7번째 화면이 실제 init·렌더됐는지(빈 상태 문구도 렌더).
        result["pool_rendered"] = window.evaluate_js(  # type: ignore[attr-defined]
            "(document.getElementById('poolList')||{innerHTML:''}).innerHTML.length > 0")
        # 2소스 진입점(#26 #6) — 두 생성 표면(작업·txt)의 '등록 데이터…' 버튼 실재.
        result["pool_buttons"] = window.evaluate_js(  # type: ignore[attr-defined]
            "['jobBtnPoolData','btnTxtPoolData']"
            ".every(function(i){return !!document.getElementById(i)})")
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
        window.resize(1180, 820)  # type: ignore[attr-defined]  # 기본 크기 = 경계 위 → 2판 복귀
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
        result["job_editmode"] = window.evaluate_js(_JOB_EDITMODE_PROBE_JS)  # type: ignore[attr-defined]
        # 매핑 칩-라이브(슬라이스 5 PR-3) — 합성 매핑 스냅샷으로 실 render() 구동 후 칩·태그 되읽기.
        result["editor_chip"] = window.evaluate_js(_EDITOR_CHIP_PROBE_JS)  # type: ignore[attr-defined]
        # txt 데이터 존(슬라이스 6 PR-2b) — datazone.js 두 번째 인스턴스 실렌더 되읽기.
        result["txt_zone"] = window.evaluate_js(_TXT_ZONE_PROBE_JS)  # type: ignore[attr-defined]
        # 빠른 기안(슬라이스 7 PR-2) — 파이프라인 토큰 폼·미리보기 채움 표지 실렌더 되읽기.
        result["quickdraft"] = window.evaluate_js(_QUICKDRAFT_PROBE_JS)  # type: ignore[attr-defined]
        # 템플릿 관리(#108) — 매체 구획+그룹·⋮ 메뉴·＋그룹지정 칩·이동 다이얼로그 실렌더 되읽기.
        result["tpl_groups"] = window.evaluate_js(_TPL_LIST_GROUP_PROBE_JS)  # type: ignore[attr-defined]
        # 에디터 1단계 피커(#108 슬라이스 3) — 라이브러리 그룹 구획(선택 전용) 실렌더 되읽기.
        result["editor_lib"] = window.evaluate_js(_EDITOR_LIB_PICKER_PROBE_JS)  # type: ignore[attr-defined]
        # 다크모드 영속·무깜빡임(콜드부트 되읽기, #74) — 부팅 시 loaded 핸들러가 저장 테마
        # (settings.json, 오리진 비의존)를 show 전에 data-theme 로 주입했는지. 저장값이 없으면
        # data_theme=null(=system). 앞선 쓰기 프로세스가 남긴 값이 여기서 보이면 Python 설정
        # 영속이 실증된다(포트/오리진이 부팅마다 달라도 유지 = 실사용 그대로).
        result["theme_persist"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({data_theme: document.documentElement.getAttribute('data-theme'),"
            " a_card: getComputedStyle(document.documentElement).getPropertyValue('--a-card').trim()})")
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
    window = webview.create_window(
        WINDOW_TITLE,
        str(web_dir() / "index.html"),
        js_api=frontend,
        width=1180,
        height=820,
        min_size=(760, 600),
        hidden=True,  # 테마 주입 후 show — FOUC 은닉(#74, 아래 _apply_theme_then_show)
    )
    frontend._window = window
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

    def _apply_theme_then_show() -> None:  # loaded 콜백(0-인자로 호출됨, event.py:40)
        loaded_seen.set()
        err: "object | None" = None
        try:
            theme = settings.load_theme()
            if theme in ("light", "dark"):
                # Theme.apply(theme.js) 경유 — data-theme 설정 + themechange 발신으로 레일
                # 라벨까지 재동기된다(직접 setAttribute 는 라벨을 어긋난 채 남겼다). loaded 는
                # body 스크립트 실행 후라 window.Theme 실재가 계약 — 부재는 곧 주입 실패.
                ok = window.evaluate_js(  # type: ignore[attr-defined]
                    f"window.Theme ? (window.Theme.apply({json.dumps(theme)}), true) : false")
                if ok is not True:
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
        _alarm(
            "loaded 후 표시 매달림 — 폴백으로 창 표시(테마 미주입 가능)"
            if loaded_seen.is_set()
            else "loaded 미발화 — 폴백으로 창 표시(테마 미주입 가능)",
            window,
        )

    # 20s: 타이머가 webview.start() 전에 걸리므로 예산이 WebView2 콜드스타트(초회 런타임 부팅·
    # AV 스캔) 전체를 포함한다 — 짧으면 정상 부팅에서 폴백이 선발화해 무테마 창(FOUC)+거짓 경보.
    timer = threading.Timer(20.0, _fallback_show)
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
