"""웹 프론트엔드 브리지 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 마이그레이션 토대의 회귀 심. 스파이크 Q1(링1 Qt-free)의 배당금이 살아있는지와,
화면 컨트롤러가 링1 VM 을 그대로 구동해 스냅샷을 만드는지를 창 없이 확인한다. 미지 액션은
시끄럽게 거부(confirm-or-alarm)해야 한다.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

from _web_source import (
    APP_CSS_FILES,
    NAV_SCREENS,
    REPO_ROOT,
    SOURCE_CSS_DIR,
    SOURCE_ENTRY,
    SOURCE_INDEX,
    SOURCE_ROOT,
    source_text,
)

REPO = REPO_ROOT
WEB = SOURCE_ROOT
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"


def _frontend(tmp_path, monkeypatch):
    """WebFrontend 브리지 — 실 사용자 jobs 디렉터리를 건드리지 않게 tmp 로 우회."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    return app_mod.WebFrontend(tmp_path / "txt")


def _armed_workbench(frontend, tmp_path):
    """작업대 세션을 열어 복사 진행 1건을 만든다 — 창 종료 가드 무장의 최소 경로.

    「기안」 사망(F6 PR-B)으로 가드 무장의 헤드리스 표본이 작업대로 승계됐다
    (붙여넣기 원문 대신 복사 진행 = 잃을 것).
    """
    from hwpxfiller.domain.job import Job
    from hwpxfiller.domain.mapping import FieldMapping, MappingProfile

    tpl = tmp_path / "기안.txt"
    tpl.write_text("수신: {{수신}}", encoding="utf-8")
    wb = frontend.controllers["workbench"]
    job = Job(name="기안", template_path=str(tpl),
              mapping=MappingProfile(mappings=[
                  FieldMapping(template_field="수신", source="부서")]))
    wb.registry.save(job)
    wb.open(wb.registry.load("기안"), [(0, {"부서": "총무과"}), (1, {"부서": "회계과"})])
    wb.note_copied(wb.render()[1])  # 2건 중 1건 복사 = 진행 소실 위험
    return wb


def test_native_close_guard_allows_clean_and_blocks_armed_session(tmp_path, monkeypatch):
    """네이티브 X는 클린 상태 즉시 통과, 무장 세션(작업대 진행)은 웹 확인 전 닫기를 취소한다.

    무장 경로가 「기안」 붙여넣기 → 작업대 복사 진행으로 승계됐다(F6 PR-B) — 브리지의
    닫기 프로토콜(취소·확인·중복 모달 금지) 계약 자체는 화면 불가지라 그대로 산다.
    """
    frontend = _frontend(tmp_path, monkeypatch)
    assert frontend.close_guard_state() == {"armed": False, "reasons": []}
    assert frontend._handle_window_closing() is None

    _armed_workbench(frontend, tmp_path)
    state = frontend.close_guard_state()
    assert state["armed"] is True
    assert any("작업대" in reason for reason in state["reasons"])

    calls: list[str] = []

    class FakeWindow:
        """N-07 파사드가 선 창 — `deliver` 는 구조화된 성공을 돌려준다.

        파사드가 **없는** 창(반환 ``None``)은 이제 조용한 무동작이 아니라 loud 실패이고,
        그 갈래는 :func:`test_native_close_prompt_without_facade_is_loud_and_fails_closed`
        가 따로 진다 — 여기서 그 상태를 쓰면 확인창 발신 자체가 검사되지 않는다.
        """

        def evaluate_js(self, script):
            calls.append(script)
            return {"ok": True, "event": "close-request", "started": True}

        def destroy(self):
            calls.append("destroy")

    class ImmediateTimer:
        daemon = False

        def __init__(self, _delay, fn, args=()):
            self.fn, self.args = fn, args

        def start(self):
            self.fn(*self.args)

    frontend._window = FakeWindow()
    monkeypatch.setattr("hwpxfiller.webapp.app.threading.Timer", ImmediateTimer)
    assert frontend._handle_window_closing() is False
    # N-07 — 발신 자리는 제품 경계 하나다. 내부 이름(`AppCloseGuard.prompt`)은 나오지 않는다.
    assert calls and '"event": "close-request"' in calls[-1]
    assert calls[-1].startswith("window.__hwpx")
    assert "AppCloseGuard" not in calls[-1]
    # closing 이벤트가 확인 모달이 열린 동안 다시 와도 모달을 중복 생성하지 않는다.
    prompt_calls = len(calls)
    assert frontend._handle_window_closing() is False
    assert len(calls) == prompt_calls
    assert frontend.cancel_window_close() is True
    assert frontend._close_prompt_open is False
    assert frontend.confirm_window_close() is True
    assert calls[-1] == "destroy"
    assert frontend._handle_window_closing() is None


def test_native_close_prompt_without_facade_is_loud_and_fails_closed(tmp_path, monkeypatch):
    """파사드 부재는 **조용한 무동작이 아니다**(N-07) — 창은 살고 경보가 남는다.

    종전 표현 ``window.AppCloseGuard && window.AppCloseGuard.prompt(…)`` 은 가드가 없으면
    falsy 로 아무 일도 하지 않았다: 확인창은 안 뜨고 창만 남았으며 아무도 그 사실을 몰랐다.
    사용자가 X 를 눌렀는데 아무 반응이 없는 그 상태가 이 게이트가 막는 회귀다.

    실패 처분은 여전히 **안전측**이다 — 닫기는 취소되고(fail-open 금지), 대기 표식은 걷혀
    다음 X 가 새 판정을 받으며, 사유는 내구성 채널로 재진술된다.
    """
    frontend = _frontend(tmp_path, monkeypatch)
    _armed_workbench(frontend, tmp_path)

    scripts: list[str] = []
    alerts: list[str] = []

    class FacadeLessWindow:
        def evaluate_js(self, script):
            scripts.append(script)
            return None  # 파사드 부재 — evaluate_js 는 미정의 전역에 None 을 준다

        def destroy(self):  # pragma: no cover — 여기 오면 fail-open 이다
            raise AssertionError("파사드 부재인데 창이 닫혔습니다 — fail-open 회귀입니다.")

    monkeypatch.setattr("hwpxfiller.external.settings.alert", alerts.append)

    class ImmediateTimer:
        daemon = False

        def __init__(self, _delay, fn, args=()):
            self.fn, self.args = fn, args

        def start(self):
            self.fn(*self.args)

    frontend._window = FacadeLessWindow()
    monkeypatch.setattr("hwpxfiller.webapp.app.threading.Timer", ImmediateTimer)

    assert frontend._handle_window_closing() is False  # 닫기 취소 = 창 유지
    assert frontend._close_prompt_open is False, "대기 표식이 걸린 채 남으면 다음 X 가 죽는다"
    assert alerts, "부재가 조용히 지나갔습니다 — 내구성 경보가 없습니다."
    assert any("종료 확인창 표시 실패" in message for message in alerts)
    assert any('"event": "close-request"' in script for script in scripts)


def test_importing_webapp_screens_loads_no_qt():
    """링1 을 임포트하는 컨트롤러 모듈이 PySide6/PyQt 를 한 줄도 끌어오지 않는다(스파이크 Q1).

    깨끗한 서브프로세스에서 검사 — 전체 스위트가 다른 곳에서 Qt 를 미리 로드하면 sys.modules
    검사가 위양성이 되므로(격리 필요).
    """
    # app 까지(브리지 전체 그래프 — webview 는 지연 임포트라 여기선 안 끌림).
    code = (
        "import sys; import hwpxfiller.webapp.app;"
        "qt=[m for m in sys.modules if 'PySide6' in m or 'PyQt' in m];"
        "print('QT:'+','.join(qt)); sys.exit(1 if qt else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, f"webapp.screens 임포트가 Qt 오염: {proc.stdout}{proc.stderr}"


# (「기안」 세션 계약 테스트군 삭제 — F6 PR-B: 대상 DraftController·휘발 세션 자체가
#  사망했다. 작업점 카드·큐 퇴화·복사 거래의 승계 계약은 작업대 테스트
#  (test_webapp_workbench.py)가, 시각 계약은 test_workcard_contract.py 가 소유한다.)
def test_win32_filter_block_derives_from_exts_and_is_double_null_terminated():
    """Win32 comdlg32 필터 블록이 EXCEL_EXTS 파생·이중 널 종결 구조인가.

    파일 다이얼로그를 pywebview WinForms(접근성 재귀 크래시) 대신 Win32 comdlg32 로 옮긴
    회귀 심(소이슈 ②). 확장자 단일 출처(EXCEL_EXTS)가 필터에 자동 반영되는지도 함께 가드.
    """
    from hwpxfiller.data.factory import EXCEL_EXTS
    from hwpxfiller.gui.file_filters import EXCEL_FILTER_PATTERN
    from hwpxfiller.host.native.dialogs import _filter_block

    for ext in EXCEL_EXTS:
        assert f"*{ext}" in EXCEL_FILTER_PATTERN  # 확장자 추가가 필터에 자동 반영
    block = _filter_block([("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")])
    assert block.endswith("\0\0")  # 이중 널 종결(comdlg32 요구)
    assert block.count("\0") == 5  # 4항목 사이 널 3 + 종결 널 2
    assert f"엑셀/CSV 데이터 ({EXCEL_FILTER_PATTERN})" in block


# ------------------------------------------------------------- 다중 시트 확정 게이트(#33)
# 브리지가 모호(2+ 시트) 워크북을 조용히 첫 시트로 로드하지 않고 웹에 시트 확정을 요구하는지,
# 확정된 시트만 로드하고 모르는 시트는 시끄럽게 거절하는지 — 창 없이(다이얼로그 우회) 가드.


def test_pick_data_file_multi_sheet_defers_and_asks(tmp_path, monkeypatch):
    """다중 시트 = 조용히 첫 시트 로드 금지 → needs_sheet 페이로드로 확정 요구, 로드 보류."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(MULTI_SHEET))

    result = frontend.pick_data_file("editor")
    assert isinstance(result, dict) and result["needs_sheet"] is True
    assert result["path"] == str(MULTI_SHEET)
    assert result["name"] == "multi_sheet.xlsx"
    assert [s["name"] for s in result["sheets"]] == ["공고목록", "낙찰현황"]
    assert result["sheets"][0]["rows"] and result["sheets"][0]["cols"]  # 행×열 근사 동반
    # 핵심: 아직 아무 것도 로드하지 않았다(조용한 첫 시트 강등 없음).
    assert frontend.controllers["editor"].data_path == ""


@pytest.mark.parametrize("screen", ["editor", "job"])
def test_pick_data_file_multi_sheet_defers_on_every_screen(screen, tmp_path, monkeypatch):
    """pick_data_file 반환 계약은 screen-불가지 — 데이터를 붙이는 화면 모두 needs_sheet 로
    보류돼야 한다(리뷰 P1: 한 화면이 객체를 못 다뤄 첫 시트로 조용히 강등되던 회귀 차단).

    데이터-부착 화면은 editor·job(기안 사망=F6 PR-B) — 두 화면 모두 관통을 지킨다."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(MULTI_SHEET))
    result = frontend.pick_data_file(screen)
    assert isinstance(result, dict) and result["needs_sheet"] is True
    assert [s["name"] for s in result["sheets"]] == ["공고목록", "낙찰현황"]


def test_load_data_sheet_threads_confirmed_sheet_into_job_controller(tmp_path, monkeypatch):
    """확정 시트가 브리지→컨트롤러(load_data_path sheet=)→링1 VM 까지 관통해 로드된다(리뷰 P1).

    (구 「기안」 표본의 이식 — F6 PR-B) 「문서 만들기」 컨트롤러도 작업 없이 세션이
    데이터를 소유하므로(§18.2) 단독 로드로 브리지 경로를 검증할 수 있다 — editor 의
    sheet 관통은 그쪽 컨트롤러 테스트가 픽스처와 함께 본다.
    """
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("job", str(MULTI_SHEET), "낙찰현황")
    # 성사 반환 = descriptor(U2 §2.7 3행) — 면 유지 재진술·고정 버튼이 이 호출만으로 선다.
    assert result == {
        "label": "파일: multi_sheet.xlsx",
        "path": str(MULTI_SHEET),
        "sheet": "낙찰현황",
        "rows": 3,
    }
    job = frontend.controllers["job"]
    assert job.data_label == "multi_sheet.xlsx"
    # 첫 시트(공고목록, 2건)가 아니라 확정 시트(낙찰현황, 3건)가 실렸는가 — 조용한 강등 아님.
    assert job.snapshot()["record_count"] == 3


def test_pick_data_file_corrupt_workbook_returns_error_not_raise(tmp_path, monkeypatch):
    """손상 xlsx 의 시트 메타 조회 실패는 날것 예외로 새지 않고 ERROR: 로 시끄럽게 반환한다.

    리뷰 P2: ambiguous_sheets(=sheet_overview) 가 예외 변환 경계 밖이면 BadZipFile 이 pywebview
    Promise 로 그대로 전파돼 웹 핸들러(ERROR: 접두 검사)가 못 잡고 조용해진다.
    """
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a real zip/xlsx")  # openpyxl → BadZipFile
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(broken))
    result = frontend.pick_data_file("editor")
    assert isinstance(result, str) and result.startswith("ERROR:"), (
        f"손상 워크북이 ERROR: 로 안 돌아옴(날것 예외 유출 위험): {result!r}"
    )
    assert frontend.controllers["editor"].data_path == ""  # 로드 안 됨


def test_load_data_sheet_vanished_file_returns_error_not_raise(tmp_path, monkeypatch):
    """모달을 연 뒤 파일이 사라지면(경로 부재) load_data_sheet 의 sheet_overview 도 같은
    ERROR: 경계로 감싸져 시끄럽게 되돌린다(리뷰 P2 — load_data_sheet 측 대칭)."""
    frontend = _frontend(tmp_path, monkeypatch)
    gone = tmp_path / "gone.xlsx"  # 만들지 않음 → 조회 시 실패
    result = frontend.load_data_sheet("job", str(gone), "Sheet1")
    assert isinstance(result, str) and result.startswith("ERROR:"), (
        f"사라진 파일이 ERROR: 로 안 돌아옴: {result!r}"
    )


def test_pick_data_file_single_sheet_loads_directly(tmp_path, monkeypatch):
    """단일 시트/CSV = 물을 것이 없음 → 확정 게이트 없이 곧장 로드(descriptor 반환)."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격\n전산장비,1000\n", encoding="utf-8-sig")
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(csv))

    result = frontend.pick_data_file("editor")
    # 성사 반환 = descriptor(U2 §2.7 3행): label 은 링1 합성(source_label) 그대로,
    # path 는 「이 데이터 고정」이 서는 근거다(푸시 도착에 기대지 않는다).
    assert result == {"label": "파일: d.csv", "path": str(csv), "sheet": "", "rows": 1}
    assert frontend.controllers["editor"].data_path == str(csv)


def test_load_data_sheet_loads_confirmed_sheet(tmp_path, monkeypatch):
    """확정한 시트로 로드 → 그 시트의 필드가 컨트롤러에 반영(descriptor 반환)."""
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("editor", str(MULTI_SHEET), "낙찰현황")
    assert isinstance(result, dict) and result["label"] == "파일: multi_sheet.xlsx"
    assert result["sheet"] == "낙찰현황"
    assert frontend.controllers["editor"].source_fields == ["업체명", "낙찰금액", "계약일"]


def test_load_data_sheet_rejects_unknown_sheet_loudly(tmp_path, monkeypatch):
    """모르는 시트명은 조용히 첫 시트로 강등하지 않고 시끄럽게 거절(로드 안 함)."""
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("editor", str(MULTI_SHEET), "없는시트")
    assert isinstance(result, str) and result.startswith("ERROR:")
    assert "없는시트" in result
    assert frontend.controllers["editor"].data_path == ""  # 로드되지 않음


def test_web_assets_present_and_wired():
    """정적 소스 골격과 단일 module entry가 기존 자산 graph를 소유하는가."""
    for rel in (
        "index.html",
        "src/main.js",
        "css/tokens.css",
        "js/bridge.js",
        "src/shell/app.ts",
    ):
        assert (WEB / rel).exists(), f"source/{rel} 없음"
    # 앱 스타일시트는 분할됐다 — 목록 단일 출처는 공유 매니페스트다. 여기서는 골격 존재만 본다.
    for name in APP_CSS_FILES:
        assert (SOURCE_CSS_DIR / name).exists(), f"source css/{name} 없음"
    html = SOURCE_INDEX.read_text(encoding="utf-8")
    assert '<script type="module" src="./src/main.js"></script>' in html
    assert SOURCE_ENTRY.exists()
    assert not re.search(r"<script\b(?![^>]*\btype=\"module\")", html)
    # 장기 셸 계약은 살아 있는 두 화면만 허용한다. 「기안」 실화면 심은 사망(F6 PR-B) —
    # 승계 표면은 작업대다.
    for scr in NAV_SCREENS:
        assert f'data-scr="{scr}"' in html, f"레일에 {scr} 없음"
    assert html.count('id="reactScreenStage"') == 1
    product_screens = source_text("src/screens/product_screens.ts")
    assert 'screenProps("workbench", active)' in product_screens


# ============================================================ #26 #6 — 풀 겨눔(브리지 경로)
from hwpxfiller.domain.dataset_reference import DatasetReference
from hwpxfiller.external.dataset_store import DatasetPoolRegistry


def test_job_load_pool_and_nara_frozen(tmp_path, monkeypatch):
    """풀 겨눔 — 정상 참조는 읽되 직접·조립 속 나라 소스는 loader 전에 동결 거절.

    (구 「기안」 표본의 이식 — F6 PR-B) 믹스인 계약(PoolTargetingMixin._do_load_pool)의
    생존 소비자는 「문서 만들기」 하나 — 실 사용자 풀을 건드리지 않게 tmp 레지스트리로
    직접 조립한다(브리지 dispatch 검증은 registry 완결성 테스트가 별도로 진다).
    """
    from hwpxfiller.external.job_store import JobRegistry
    from hwpxfiller.external.hwpx_engine import make_hwpx_engine
    from hwpxfiller.data.factory import source_for_path, source_from_pool_item
    from hwpxfiller.webapp.screen_job import JobController
    from hwpxfiller.webapp.screens import NARA_FROZEN_TEXT

    csv = tmp_path / "d.csv"
    csv.write_text("공고명,담당자\n전산장비,김주무\n", encoding="utf-8")
    pool = DatasetPoolRegistry(tmp_path / "pool")

    def pipeline_opts(*sources):
        return {"sources": list(sources), "steps": []}

    excel_key = pool.add(DatasetReference(name="기안데이터", kind="excel", opts={"path": str(csv)}))
    nara_key = pool.add(DatasetReference(name="나라쿼리", kind="nara",
                                        opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    nested_ref: dict = {
        "kind": "nara",
        "opts": {"bgn_dt": "202607010000", "end_dt": "202607080000"},
    }
    for _ in range(3):
        nested_ref = {"kind": "pipeline", "opts": pipeline_opts(nested_ref)}
    nested_nara_key = pool.add(DatasetReference(
        name="중첩 나라 조립", kind="pipeline", opts=pipeline_opts(nested_ref)
    ))
    ctrl = JobController(JobRegistry(tmp_path / "jobs"), lambda s, snap: None,
                         clock=lambda: datetime(2026, 7, 21, 9, 0, 0),
                         engine=make_hwpx_engine(),
                         pool_registry=pool,
                         generation_lock=threading.Lock(),
                         file_source_factory=source_for_path,
                         pool_source_factory=source_from_pool_item)
    res = ctrl.dispatch("load_pool", {"key": excel_key})
    assert res["ok"] is True and res["label"] == "등록 데이터: 기안데이터"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 기안데이터"
    assert snap["record_count"] == 1   # 참조 재읽기로 실 레코드 도착

    load_calls = []

    def forbidden_loader(item):
        load_calls.append(item)
        raise AssertionError("나라 동결 관문 뒤 loader가 호출됐습니다.")

    monkeypatch.setattr(ctrl, "_load_pool_records", forbidden_loader)

    direct = ctrl.dispatch("load_pool", {"key": nara_key})
    nested = ctrl.dispatch("load_pool", {"key": nested_nara_key})
    assert direct == {"ok": False, "error": NARA_FROZEN_TEXT}
    assert nested == direct
    assert load_calls == []


def test_copy_clipboard_is_atomic_transaction_only(tmp_path, monkeypatch):
    """브리지 copy_clipboard = 원자 거래(copy_to) 전용 — 비-원자 폴백 사망(F6 PR-B).

    ① 거래를 소유한 화면(작업대)은 token 대조를 지나 실제로 클립보드에 쓴다.
    ② 거래 없는 화면(job)의 호출은 오배선 — 조용한 반쪽 복사 대신 ValueError 로 loud.
    """
    from hwpxfiller.webapp import app as app_mod

    fe = _frontend(tmp_path, monkeypatch)
    writes: list = []
    monkeypatch.setattr(app_mod, "set_clipboard_text", lambda t: writes.append(t))

    # ① 작업대 원자 경로 — 사전확인 토큰(copy_token)과 함께라야 통과한다.
    wb = _armed_workbench(fe, tmp_path)  # 2건 세션, 1건 복사됨(작업점은 그 카드에 머묾)
    res = fe.copy_clipboard("workbench", wb.copy_token())
    assert res["copied"] is True
    assert writes and "총무과" in writes[-1]
    # stale 토큰은 쓰지 않는다(확인 대상 = 복사 대상, 3R P1).
    n = len(writes)
    stale = fe.copy_clipboard("workbench", "stale-token")
    assert stale["copied"] is False and stale.get("stale") is True
    assert len(writes) == n, "stale 토큰인데 클립보드에 기록됐습니다."

    # ② 거래 미소유 화면 — loud 거절(조용한 무시 금지).
    with pytest.raises(ValueError, match="복사 거래"):
        fe.copy_clipboard("job")


def test_close_guard_is_a_protocol_every_session_surface_joins(tmp_path, monkeypatch):
    """창 종료 가드 참여는 **프로토콜**이지 손으로 세는 명단이 아니다(F6 1R P2).

    종전에는 화면 이름 셋을 하드 열거했고, 그래서 새 세션 표면(작업대)이 미저장 매핑·복사
    진행을 들고 있어도 창을 닫으면 무경보로 사라졌다 — 가드의 완전성이 「누가 이 목록을
    갱신했는가」에 걸려 있었다. 이 테스트는 **세션을 든 컨트롤러가 빠짐없이 참여하는지**를
    센다: 새 표면이 구현을 빠뜨리면 여기서 울고, 정말 참여하지 않을 것이면 아래 배제 표에
    사유를 적어야 통과한다(조용한 무시와 선언된 배제는 다르다).
    """
    frontend = _frontend(tmp_path, monkeypatch)

    # 세션을 들지 **않는** 컨트롤러 — 창을 닫아도 잃을 것이 없다(사유를 여기 적는다).
    not_session = {
        "library": "전역 목록 보기 — 상태는 전부 디스크에 있다",
        "tpl": "템플릿 관리 — 각 동사가 즉시 영속한다",
        "pool": "등록 데이터 참조 — 등록·전이가 즉시 영속한다",
    }
    # 세션을 **들고 잃지만, 계약으로 조용히 잃는** 컨트롤러(U2 §2.9 · #344). 「잃을 것이
    # 없다」(위 표)와는 다른 선언이라 같은 표에 넣으면 이 테스트가 거짓말을 한다. job 의
    # 무장 선택은 실제로 사라진다 — 사용자 계약이 "창 닫기 = 명시적 종료 선언, 진행 중 작업
    # 정보는 보존하지 않는다"로 그 소실을 수용했다. confirm-or-alarm 의 예외는 숨는 대신
    # 이 표에 적히는 방식으로 존재한다. (홈 삭제 가드 `session_guard_for` 와 데이터 재겨눔
    # 사전 확인 `_do_guard_state` 는 창 종료가 아니라서 이 계약 밖 — 그대로 산다.)
    silent_loss_by_contract = {
        "job": "창 닫기 = 명시적 종료 선언 — 진행 중 선택은 계약상 보존하지 않는다",
    }
    declared = set(not_session) | set(silent_loss_by_contract)
    missing = [
        name for name, ctrl in frontend.controllers.items()
        if name not in declared and not hasattr(ctrl, "close_guard_reason")
    ]
    assert not missing, (
        "세션을 든 컨트롤러가 창 종료 가드에 참여하지 않습니다 — "
        f"close_guard_reason() 를 구현하거나 배제 사유를 적으세요: {missing}"
    )
    # 배제 표가 stale 해지지 않게: 적어 둔 이름이 실제로 존재해야 한다.
    assert declared <= set(frontend.controllers)
    # 두 표는 배타다 — 한 이름이 양쪽에 적히면 어느 선언이 참인지 알 수 없다.
    assert not (set(not_session) & set(silent_loss_by_contract))
    # 계약상 침묵 표의 컨트롤러가 close_guard_reason 을 되살리면 이 표가 거짓이 된다
    # (참여하면서 배제 선언이 남는 이중 상태 금지 — 재유입 시 표에서 지우고 들어와야 한다).
    for name in silent_loss_by_contract:
        assert not hasattr(frontend.controllers[name], "close_guard_reason"), (
            f"{name} 이(가) 창 종료 가드에 다시 참여합니다 — "
            "silent_loss_by_contract 선언과 모순됩니다(#344)."
        )


def test_workbench_session_blocks_the_window_close(tmp_path, monkeypatch):
    """작업대의 미저장 연결·복사 진행은 창 종료에서 **경보한다**(리뷰 P2 회귀).

    「문서 만들기」의 선택이 1클릭으로 재현 가능해 job 가드가 무장하지 않는 상태에서도
    작업대 세션은 잃을 것이 있다 — 그 소실을 아무도 말하지 않는 것이 결함이었다.
    """
    from hwpxfiller.domain.job import Job
    from hwpxfiller.domain.mapping import FieldMapping, MappingProfile

    frontend = _frontend(tmp_path, monkeypatch)
    assert frontend.close_guard_state()["armed"] is False

    tpl = tmp_path / "기안.txt"
    tpl.write_text("수신: {{수신}}", encoding="utf-8")
    wb = frontend.controllers["workbench"]
    job = Job(name="기안", template_path=str(tpl),
              mapping=MappingProfile(mappings=[
                  FieldMapping(template_field="수신", source="부서")]))
    wb.registry.save(job)
    wb.open(wb.registry.load("기안"), [(0, {"부서": "총무과"}), (1, {"부서": "회계과"})])
    assert frontend.close_guard_state()["armed"] is False   # 아직 잃을 것이 없다

    wb.note_copied(wb.render()[1])                          # 2건 중 1건 복사 = 진행 소실
    state = frontend.close_guard_state()
    assert state["armed"] is True
    assert any("작업대" in reason for reason in state["reasons"]), state["reasons"]


def test_new_job_from_data_starts_the_wizard_on_the_mounted_data(tmp_path, monkeypatch):
    """U2 §2.4·§4 판정 E(#349) — 「이 데이터로 새 작업」의 크로스스크린 착지.

    데이터의 정체는 웹이 싣지 않고 브리지가 「문서 만들기」 컨트롤러에 **되묻는다**: 지금
    무엇이 올라와 있는지의 단일 출처가 그 화면이라, 웹이 기억한 값을 실으면 도착 순서에
    따라 다른 파일로 작업이 시작된다. 마운트가 없으면 조용히 빈 마법사를 열지 않는다 —
    「이 데이터로」라고 말한 진입이 데이터 없이 열리면 그 문안이 거짓이 된다.
    """
    frontend = _frontend(tmp_path, monkeypatch)
    job = frontend.controllers["job"]
    editor = frontend.controllers["editor"]

    # ① 마운트 전 — 시끄럽게 거절하고 편집 세션은 손대지 않는다.
    out = frontend.new_job_from_data({"entry_reason": "document_browser_new_work"})
    assert isinstance(out, str) and out.startswith("ERROR:") and "데이터" in out
    assert editor.data_path == ""

    csv = tmp_path / "발주.csv"
    csv.write_text("부서,사업명\n총무과,책상\n회계과,복사기\n", encoding="utf-8")
    job.load_data_path(str(csv))

    # ② 미배선 사유는 링1 이 fail-closed 로 거절하고 그 거절이 그대로 올라온다.
    bad = frontend.new_job_from_data({"entry_reason": "workbench_result"})
    assert isinstance(bad, str) and bad.startswith("ERROR:")
    assert editor.data_path == ""            # 거절이면 세션은 그대로

    # ③ 성사 — 편집기 초안이 **그 파일**을 들고 서고 진입 문맥이 살아 있다.
    ok = frontend.new_job_from_data({
        "entry_reason": "document_browser_new_work",
        "evidence": {"데이터": "발주.csv"},
        "return_context": {"surface": "data"},
    })
    assert ok == str(csv)
    assert editor.data_path == str(csv)
    assert editor.source_fields == ["부서", "사업명"]
    snap = editor.snapshot()
    assert snap["is_draft"] is True and snap["template_path"] == ""
    assert snap["context"]["entry_reason"] == "document_browser_new_work"
    # 「문서 만들기」 세션은 이 진입으로 흔들리지 않는다(데이터·선택은 그 화면 소유).
    assert job.data_path == str(csv)


def test_new_job_from_data_refuses_non_file_mounts_with_the_same_reason(tmp_path, monkeypatch):
    """#349 리뷰 P1 — 파일로 다시 열 수 없는 마운트는 **버튼과 브리지가 같은 말**을 한다.

    조립 파이프라인 등록분은 `_do_load_pool` 이 `data_path` 를 의도적으로 비워 두는데
    (그 값은 로케이트·고정 프리필의 것이라 파일 참조에만 의미가 있다) 버튼은 `has_data` 로
    서 있었다 — 화면은 「누를 수 있다」, 백엔드는 「데이터가 없다」로 갈리던 자리다. 이제
    판정이 하나이므로 스냅샷의 사유와 진입 거절 문구가 **같은 문자열**이어야 한다.
    """
    from hwpxfiller.domain.dataset_reference import DatasetReference

    frontend = _frontend(tmp_path, monkeypatch)
    job = frontend.controllers["job"]
    editor = frontend.controllers["editor"]
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("id,부서\n1,총무과\n", encoding="utf-8")
    b.write_text("id,사업명\n1,책상\n", encoding="utf-8")
    key = job.pool_registry.add(DatasetReference(name="6월 조립", kind="pipeline", opts={
        "sources": [
            {"kind": "excel", "opts": {"path": str(a)}},
            {"kind": "excel", "opts": {"path": str(b)}},
        ],
        "steps": [{"op": "merge", "source": 1, "on": "id", "how": "inner"}],
    }))
    assert job.dispatch("load_pool", {"key": key})["ok"] is True

    snap = job.snapshot()
    assert snap["has_data"] is True                      # 데이터는 있다 —
    assert snap["new_work"]["can"] is False              # 이 동선만 못 간다
    out = frontend.new_job_from_data({"entry_reason": "document_browser_new_work"})
    assert isinstance(out, str) and out.startswith("ERROR:")
    assert snap["new_work"]["reason"] in out, "버튼의 사유와 진입 거절 문구가 갈립니다."
    assert editor.data_path == ""                        # 조용한 빈 초안으로 가지 않는다


def test_job_selection_loss_is_contracted_silence_not_a_close_guard(tmp_path, monkeypatch):
    """U2 §2.9(#344) — job 의 무장 선택은 창 종료 가드를 세우지 **않는다**(계약상 침묵).

    창 닫기는 명시적 종료 선언이고 진행 중 작업 정보는 보존하지 않는다는 사용자 계약의
    착지다. 끊긴 것은 `_guard_state` 의 소비자 셋 중 **창 종료 하나뿐**이다: 같은 무장
    상태에서 데이터 재겨눔·재연결 사전 확인(`_do_guard_state`)은 그대로 무장을 답하고
    (홈 삭제 가드 `session_guard_for` 는 ``test_session_guard_for_cross_screen_query`` 가
    따로 못박는다), 미저장 산출물을 든 작업대·편집기는 여전히 창 종료에 참여한다 —
    국경은 화면이 아니라 소실의 종류(재현 가능한 선택 vs 미저장 산출물)다.
    """
    frontend = _frontend(tmp_path, monkeypatch)
    job = frontend.controllers["job"]
    csv = tmp_path / "d.csv"
    csv.write_text("부서,사업명\n총무과,책상\n회계과,복사기\n감사과,의자\n", encoding="utf-8")
    job.load_data_path(str(csv))
    job.dispatch("toggle_record", {"index": 0, "value": True})  # 부분 수작업 선택 = 무장
    assert job._do_guard_state({})["armed"] is True   # 재겨눔 사전 확인 소비자는 불변
    assert frontend.close_guard_state()["armed"] is False       # 창 종료만 계약상 침묵
    # 같은 프런트에서 미저장 산출물 표면들은 여전히 창 종료를 막는다.
    assert hasattr(frontend.controllers["editor"], "close_guard_reason")
    _armed_workbench(frontend, tmp_path)
    state = frontend.close_guard_state()
    assert state["armed"] is True
    assert state["reasons"] and all("작업대" in r for r in state["reasons"]), state["reasons"]
