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
from ..data.excel import ambiguous_sheets, sheet_overview  # 다중 시트 확정 게이트 판정(#33)
from ..gui.file_filters import EXCEL_FILTER_PATTERN  # 확장자 단일 출처(RC-34) — Qt-free 상수
from hwpxcore.native._debug import log
from hwpxcore.native.clipboard import set_clipboard_text
from hwpxcore.native.dialogs import open_file_dialog, open_folder_dialog, save_file_dialog
from hwpxcore.native.reveal import open_path as _native_open_path
from hwpxcore.native.reveal import reveal_in_explorer as _native_reveal
from .screen_editor import EditorController
from .screen_home import HomeController
from .screen_matrix import MatrixController
from .screen_pool import PoolController
from .screen_run import RunController
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
            EditorController(job_registry, self._push, pool_registry=pool_registry),
            RunController(job_registry, self._push, pool_registry=pool_registry),
            MatrixController(job_registry, self._push, pool_registry=pool_registry),
            # 템플릿 관리(#13) — TXT 레지스트리는 즉시 기안과 공유(변경이 양쪽에 반영).
            TemplateController(registry, self._push),
            # 데이터 관리(#26 #4) — 등록 데이터 참조·수명.
            PoolController(pool_registry, self._push),
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

    def pick_pool_data_file(self) -> "str | None":
        """데이터 관리 등록 모달 '찾아보기' → **경로만** 반환(#26 #4).

        ``pick_data_file`` 과 달리 어떤 컨트롤러에도 로드하지 않는다 — 등록은 참조
        저장이지 데이터 로드가 아니다(행 미저장 불변식). None = 취소.
        """
        filters = _EXCEL_OR_ANY_FILTERS
        return open_file_dialog(filters, owner_title=WINDOW_TITLE)

    def pick_template_path(self) -> "str | None":
        """템플릿 다시 연결(#67) '찾아보기' → **경로만** 반환(``pick_pool_data_file`` 미러).

        ``pick_template_file`` 과 달리 어떤 컨트롤러에도 로드하지 않는다 — 재연결의
        검증·확정은 dispatch(``relink_template``)의 confirm 게이트가 담당. None = 취소.
        """
        return open_file_dialog([("HWPX 템플릿", "*.hwpx"), ("모든 파일", "*.*")],
                                owner_title=WINDOW_TITLE)

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
        run = self._controller("run")
        session = [getattr(ed, "template_path", ""), getattr(ed, "data_path", ""),
                   getattr(run, "out_dir", "")]
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

        웹은 이 호출 후 에디터 화면으로 전환한다 — 링1 seam(editor.new_job_session)을 재사용해
        VM 로직을 재구현하지 않는다. 새 템플릿 진입은 새 작업 세션이라 이전 세션을 원자
        초기화한다(#25) — 미저장 확인은 웹이 has_unsaved_work 로 선판단한다.
        """
        try:
            self._controller("editor").new_job_session(path)
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
  return {
    opened: opened,               // 열기 후 hidden 해제됐는가
    focus_in: focusIn,            // 초기 포커스가 모달 안(pasteText)으로 들어갔는가
    closed_by_escape: closed,     // Escape 로 닫혔는가
    focus_before: before,         // 열기 직전 트리거(내비 data-scr)
    focus_restored: restored      // 닫은 뒤 포커스가 트리거로 복귀했는가
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
      var p1 = window.SheetPicker.choose('run', payload);
      var opened = !document.getElementById('sheetModal').classList.contains('hidden');
      var btns = document.querySelectorAll('#sheetList .sheet-opt');
      var focusFirst = document.activeElement === btns[0];
      btns[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
      var picked = await p1;
      // (2) 취소 경로 — 다시 열고 Escape → null 로 해소(로드 없음).
      var p2 = window.SheetPicker.choose('run', payload);
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
# 실 컨트롤러 스냅샷을 4개 실화면 render() 에 흘려 (a) Preserve.around 래핑이 실 render 를
# 깨지 않는지, (b) txt 프리뷰(#renderView)의 스크롤이 실 재렌더를 가로질러 유지되는지 되읽는다.
# 스냅샷은 실 컨트롤러 initial()(비동기) 로 당겨 stash 하고, 스크롤은 가시 화면에서만 유효하므로
# txt 를 가시화한다. 셋업(비동기 fire)과 되읽기 사이에 한 번 대기.
_PRESERVE_REAL_SETUP_JS = r"""
(function () {
  window.__snaps = {};
  ['txt', 'editor', 'run', 'matrix'].forEach(function (scr) {
    window.pywebview.api.initial(scr).then(function (s) { window.__snaps[scr] = s; });
  });
  window.Nav.go('txt');  // 스크롤은 가시 화면에서만 유효 → txt 가시화
})()
"""

_PRESERVE_REAL_PROBE_JS = r"""
(function () {
  var out = {}, snaps = window.__snaps || {};
  ['txt', 'editor', 'run', 'matrix'].forEach(function (scr) {
    try {
      if (!snaps[scr]) { out[scr] = 'no-snap'; return; }
      window.__push(scr, snaps[scr]);   // 실 render() (Preserve.around 래핑)
      out[scr] = 'ok';
    } catch (e) { out[scr] = 'throw:' + (e && e.message); }
  });
  // txt 스크롤 보존 end-to-end: 프리뷰를 강제로 길게 → 오버플로 → 스크롤 → 재렌더 → 유지?
  try {
    var snap = snaps['txt'];
    if (!snap) { out.txt_scroll_top = 'no-snap'; return out; }
    var lines = [];
    for (var i = 0; i < 200; i++) { lines.push('라인 ' + i + ' {{공고명}}'); }
    snap.template_text = lines.join('\n');
    window.__push('txt', snap);
    var box = document.getElementById('renderView');
    box.scrollTop = 150;
    window.__push('txt', snap);         // 실 재렌더 — Preserve 가 스크롤 복원해야
    out.txt_scroll_top = document.getElementById('renderView').scrollTop;
  } catch (e) { out.txt_scroll_top = 'throw:' + (e && e.message); }
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

    ``HWPX_SELFTEST_SET_THEME`` 이 설정되면 **쓰기 단계**로 동작한다: 저장 테마를 심고 바로 정식
    종료해 localStorage 를 storage_path 에 남긴다(다음 콜드부트의 영속·무깜빡임 되읽기용 사전 단계).
    """
    import time

    set_theme = os.environ.get("HWPX_SELFTEST_SET_THEME")
    if set_theme:
        time.sleep(4.0)  # 콜드부트 + theme.js 로드 대기
        result: dict = {"theme_write": set_theme}
        try:
            # 실 토글 헬퍼로 심는다(setAttribute + localStorage.setItem) — 실사용 경로와 동형.
            result["set_result"] = window.evaluate_js(  # type: ignore[attr-defined]
                "window.Theme.set(" + json.dumps(set_theme) + ")")
            time.sleep(1.2)  # WebView2 가 storage_path 로 플러시할 여유
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
        # 2소스 진입점(#26 #6) — 세 실행 표면의 '등록 데이터…' 버튼 실재.
        result["pool_buttons"] = window.evaluate_js(  # type: ignore[attr-defined]
            "['btnPoolData','btnMxPoolData','btnTxtPoolData']"
            ".every(function(i){return !!document.getElementById(i)})")
        # 커스텀 모달 접근성 동적 거동(#27/#28) — 정적 계약(role/aria)은 test_web_dom_contract 가
        # 보고, 여기선 실 브라우저에서 Modal 헬퍼가 초기포커스·Escape 닫기·트리거 복귀를 실제로
        # 수행하는지 되읽는다. 알려진 트리거(첫 내비 버튼)에 포커스를 두고 열었다가 Escape 로 닫는다.
        result["modal_a11y"] = window.evaluate_js(_MODAL_A11Y_PROBE_JS)  # type: ignore[attr-defined]
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
        # 다크모드 영속·무깜빡임(콜드부트 되읽기) — head FOUC 인라인이 이전 세션이 남긴 저장 테마를
        # 첫 페인트 전 data-theme 로 세웠는지. 저장값이 없으면 data_theme=null(=system). 앞선 쓰기
        # 프로세스가 남긴 값이 여기서 보이면 private_mode=False+storage_path 디스크 영속이 실증된다.
        result["theme_persist"] = window.evaluate_js(  # type: ignore[attr-defined]
            "({data_theme: document.documentElement.getAttribute('data-theme'),"
            " a_card: getComputedStyle(document.documentElement).getPropertyValue('--a-card').trim()})")
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
    _finish_selftest(window, result)


# ------------------------------------------------------------------ 엔트리
def _webview_storage_dir() -> str:
    """WebView2 영속 저장소(localStorage 등) 위치 — 홈 아래 ``webview/``.

    pywebview 기본 ``private_mode=True`` 는 세션 간 localStorage 를 버린다 — 테마 선택 영속에
    필요해 ``private_mode=False`` 로 지속화하되, 저장 위치는 다른 GUI 상태와 같은 홈 seam
    (``HWPXFILLER_HOME`` 또는 ``~/.hwpxfiller``) 아래로 모은다(레지스트리들과 동일 규약)."""
    root = os.environ.get("HWPXFILLER_HOME") or (Path.home() / ".hwpxfiller")
    return str(Path(root) / "webview")


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
    # 테마 선택을 세션 간 유지 — localStorage 지속화(private_mode=False + 홈 아래 storage_path).
    storage = _webview_storage_dir()
    if "--selftest" in sys.argv:
        webview.start(_selftest_drive, window, gui=gui, private_mode=False, storage_path=storage)
    else:
        webview.start(gui=gui, private_mode=False, storage_path=storage)  # 정상 닫기 = 클린 종료(소이슈 ①)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
