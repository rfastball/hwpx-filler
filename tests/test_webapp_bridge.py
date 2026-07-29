"""웹 프론트엔드 브리지 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 마이그레이션 토대의 회귀 심. 스파이크 Q1(링1 Qt-free)의 배당금이 살아있는지와,
화면 컨트롤러가 링1 VM 을 그대로 구동해 스냅샷을 만드는지를 창 없이 확인한다. 미지 액션은
시끄럽게 거부(confirm-or-alarm)해야 한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
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
    from hwpxfiller.core.job import Job
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile

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
        def evaluate_js(self, script):
            calls.append(script)

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
    assert calls and "AppCloseGuard.prompt" in calls[-1]
    # closing 이벤트가 확인 모달이 열린 동안 다시 와도 모달을 중복 생성하지 않는다.
    prompt_calls = len(calls)
    assert frontend._handle_window_closing() is False
    assert len(calls) == prompt_calls
    assert frontend.cancel_window_close() is True
    assert frontend._close_prompt_open is False
    assert frontend.confirm_window_close() is True
    assert calls[-1] == "destroy"
    assert frontend._handle_window_closing() is None


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
    from hwpxcore.native.dialogs import _filter_block

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
    assert result == "multi_sheet.xlsx"
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
    """단일 시트/CSV = 물을 것이 없음 → 확정 게이트 없이 곧장 로드(파일명 반환)."""
    from hwpxfiller.webapp import app as app_mod

    frontend = _frontend(tmp_path, monkeypatch)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명,추정가격\n전산장비,1000\n", encoding="utf-8-sig")
    monkeypatch.setattr(app_mod, "open_file_dialog", lambda *a, **k: str(csv))

    result = frontend.pick_data_file("editor")
    assert result == "d.csv"
    assert frontend.controllers["editor"].data_path == str(csv)


def test_load_data_sheet_loads_confirmed_sheet(tmp_path, monkeypatch):
    """확정한 시트로 로드 → 그 시트의 필드가 컨트롤러에 반영(파일명 반환)."""
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("editor", str(MULTI_SHEET), "낙찰현황")
    assert result == "multi_sheet.xlsx"
    assert frontend.controllers["editor"].source_fields == ["업체명", "낙찰금액", "계약일"]


def test_load_data_sheet_rejects_unknown_sheet_loudly(tmp_path, monkeypatch):
    """모르는 시트명은 조용히 첫 시트로 강등하지 않고 시끄럽게 거절(로드 안 함)."""
    frontend = _frontend(tmp_path, monkeypatch)
    result = frontend.load_data_sheet("editor", str(MULTI_SHEET), "없는시트")
    assert isinstance(result, str) and result.startswith("ERROR:")
    assert "없는시트" in result
    assert frontend.controllers["editor"].data_path == ""  # 로드되지 않음


def test_web_assets_present_and_wired():
    """web/ 골격이 서 있고 index.html 이 생성 토큰 CSS 와 화면 스크립트를 물었는가."""
    for rel in ("index.html", "css/tokens.css",
                "js/bridge.js", "js/app.js", "js/screens/workbench.js"):
        assert (WEB / rel).exists(), f"web/{rel} 없음"
    # 앱 스타일시트는 분할됐다 — 목록 단일 출처는 매니페스트이고, 링크 순서·전수 등재는
    # test_web_css_manifest 가 진다. 여기서는 골격 존재만 본다.
    from _web_css import APP_CSS_FILES
    for name in APP_CSS_FILES:
        assert (WEB / "css" / name).exists(), f"web/css/{name} 없음"
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "css/tokens.css" in html and "js/bridge.js" in html
    # 레일 계약은 NAV_SCREENS 단일 출처(PR-5 리뷰 F7 — 3곳 하드코딩은 후속 레일 변경마다
    # 어긋난 채 초록이 된다). 「기안」 실화면 심은 사망(F6 PR-B) — 승계 표면은 작업대.
    from test_web_dom_contract import NAV_SCREENS
    for scr in NAV_SCREENS:
        assert f'data-scr="{scr}"' in html, f"레일에 {scr} 없음"
    assert 'id="scr-workbench"' in html


# ============================================================ #26 #6 — 풀 겨눔(브리지 경로)
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry


def test_job_load_pool_and_nara_frozen(tmp_path):
    """풀 겨눔(UD-25 비대칭 해소) — 엑셀 참조 성공(라벨 서버 소유), 나라 동결 거절.

    (구 「기안」 표본의 이식 — F6 PR-B) 믹스인 계약(PoolTargetingMixin._do_load_pool)의
    생존 소비자는 「문서 만들기」 하나 — 실 사용자 풀을 건드리지 않게 tmp 레지스트리로
    직접 조립한다(브리지 dispatch 검증은 registry 완결성 테스트가 별도로 진다).
    """
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.webapp.screen_job import JobController

    csv = tmp_path / "d.csv"
    csv.write_text("공고명,담당자\n전산장비,김주무\n", encoding="utf-8")
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="기안데이터", kind="excel", opts={"path": str(csv)}))
    pool.save(DatasetPoolItem(name="나라쿼리", kind="nara",
                              opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    ctrl = JobController(JobRegistry(tmp_path / "jobs"), lambda s, snap: None,
                         pool_registry=pool)
    res = ctrl.dispatch("load_pool", {"name": "기안데이터"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 기안데이터"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 기안데이터"
    assert snap["record_count"] == 1   # 참조 재읽기로 실 레코드 도착
    res2 = ctrl.dispatch("load_pool", {"name": "나라쿼리"})
    assert res2["ok"] is False and "지원되지 않습니다" in res2["error"]


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
    missing = [
        name for name, ctrl in frontend.controllers.items()
        if name not in not_session and not hasattr(ctrl, "close_guard_reason")
    ]
    assert not missing, (
        "세션을 든 컨트롤러가 창 종료 가드에 참여하지 않습니다 — "
        f"close_guard_reason() 를 구현하거나 배제 사유를 적으세요: {missing}"
    )
    # 배제 표가 stale 해지지 않게: 적어 둔 이름이 실제로 존재해야 한다.
    assert set(not_session) <= set(frontend.controllers)


def test_workbench_session_blocks_the_window_close(tmp_path, monkeypatch):
    """작업대의 미저장 연결·복사 진행은 창 종료에서 **경보한다**(리뷰 P2 회귀).

    「문서 만들기」의 선택이 1클릭으로 재현 가능해 job 가드가 무장하지 않는 상태에서도
    작업대 세션은 잃을 것이 있다 — 그 소실을 아무도 말하지 않는 것이 결함이었다.
    """
    from hwpxfiller.core.job import Job
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile

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
