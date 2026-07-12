"""나라장터 GUI(N2) 스모크 — offscreen. 대화상자 배선 + DataPage 소스 선택 관통.

깊은 로직은 test_nara_state.py 가 헤드리스로 검증한다. 여기선 위젯이 뷰모델에 배선되고
취득 산출물이 위저드 세션에 심어져 매핑 어휘까지 관통하는지 최소 배선을 확인한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hwpxfiller.core.schema import FieldSpec, TemplateSchema  # noqa: E402
from hwpxfiller.data.secret_store import (  # noqa: E402
    NARA_SERVICE_KEY_NAME,
    MemorySecretStore,
)

FIXTURES = Path(__file__).parent / "fixtures"
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ------------------------------------------------------------ 대화상자 배선
def _dialog(store, fetcher):
    from hwpxfiller.gui.nara_view import NaraAcquireDialog

    return NaraAcquireDialog(store=store, fetcher=fetcher)


def _wait_idle(dlg, timeout: float = 8.0) -> None:
    """취득/시험이 QThread(RC-12)로 돌므로 busy 해제까지 이벤트 루프를 돌린다."""
    import time

    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while dlg._busy:
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("나라 요청이 제한시간 내에 끝나지 않았습니다")
        time.sleep(0.005)
    QCoreApplication.processEvents()  # 남은 큐 배출(시그널 전달 마무리)


def _drain_tasks(dlg, timeout: float = 8.0) -> None:
    """중지 후에도 백그라운드 태스크가 비워질 때까지 대기(스테일 결과 도착·폐기 확인)."""
    import time

    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while dlg._tasks:
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("백그라운드 태스크가 제한시간 내에 끝나지 않았습니다")
        time.sleep(0.005)


def _acquire(dlg) -> None:
    dlg._on_acquire()
    _wait_idle(dlg)


def test_dialog_key_registration_updates_status_and_clears_input(qapp):
    store = MemorySecretStore()
    dlg = _dialog(store, lambda url: _fixture_bytes())
    assert dlg.lbl_status.text() == "미등록"
    assert dlg.btn_save.text() == "등록"
    assert not dlg.btn_delete.isEnabled()

    dlg.ed_key.setText("MYKEY")
    dlg._on_save_key()
    assert store.get(NARA_SERVICE_KEY_NAME) == "MYKEY"
    assert dlg.ed_key.text() == ""          # 입력창에 키를 남기지 않음
    assert dlg.lbl_status.text() == "등록됨"
    assert dlg.btn_save.text() == "교체"
    assert dlg.btn_delete.isEnabled()


def test_dialog_acquire_enables_ok_and_captures_records(qapp):
    from PySide6.QtWidgets import QDialogButtonBox

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()  # 취득 전 확인 잠금

    _acquire(dlg)
    assert ok.isEnabled()
    assert len(dlg.records) == 2
    assert "bidNtceNo" in dlg.fields
    assert "나라장터" in dlg.label and "2건" in dlg.label
    # 산출 datasource 는 키 없는 스냅샷(어휘 노출).
    assert dlg.datasource.field_labels()["bidNtceNm"] == "공고명"


def test_dialog_acquire_failure_keeps_ok_locked_and_redacts(qapp):
    from PySide6.QtWidgets import QDialogButtonBox

    def boom(url: str) -> bytes:
        raise RuntimeError(f"HTTP Error 401 for url {url}")

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    dlg = _dialog(store, boom)
    _acquire(dlg)
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()           # 실패는 수용 불가
    assert dlg.records == []
    assert _LIVE_KEY not in dlg.lbl_result.text()
    assert "[REDACTED]" in dlg.lbl_result.text()
    assert dlg.btn_retry.isEnabled()    # 재시도 노출


def test_dialog_failure_after_success_resets_all_outputs(qapp):
    """RC-24: 성공 뒤 실패 — records 만이 아니라 fields/datasource/label 까지 원자 리셋."""
    from PySide6.QtWidgets import QDialogButtonBox

    calls = {"n": 0}

    def flaky(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            return _fixture_bytes()
        raise RuntimeError("boom")

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, flaky)
    _acquire(dlg)
    assert dlg.datasource is not None and dlg.label and dlg.fields

    _acquire(dlg)  # 실패 — 이전 성공값 잔존 금지
    assert dlg.records == []
    assert dlg.fields == []
    assert dlg.datasource is None
    assert dlg.label == ""
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()


def test_dialog_edit_after_acquire_locks_ok_and_requires_reacquire(qapp):
    """RC-13: 취득 성공 뒤 기간 편집 → OK 무효화 + 재취득 안내(미검증 기간 수용 금지)."""
    from PySide6.QtWidgets import QDialogButtonBox

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    _acquire(dlg)
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert ok.isEnabled()

    dlg.dt_bgn.setDateTime(dlg.dt_bgn.dateTime().addMonths(-6))  # 취득 후 기간 편집
    assert not ok.isEnabled()
    assert "다시 가져오세요" in dlg.lbl_result.text()
    assert dlg.records == [] and dlg.datasource is None and dlg.label == ""  # 원자 리셋

    _acquire(dlg)  # 편집된 기간(>1개월)은 재취득도 검증에 걸림 — 잠금 유지
    assert not ok.isEnabled()
    assert "1개월" in dlg.lbl_result.text()


def test_dialog_spin_edit_after_acquire_locks_ok_until_reacquire(qapp):
    """RC-13: 건수 편집도 게이트 무효화 — 유효 입력 재취득으로만 게이트 복원."""
    from PySide6.QtWidgets import QDialogButtonBox

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    _acquire(dlg)
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert ok.isEnabled()

    dlg.spin_rows.setValue(7)
    assert not ok.isEnabled()
    assert "다시 가져오세요" in dlg.lbl_result.text()

    _acquire(dlg)  # 재취득 → 새 스냅샷으로 복원
    assert ok.isEnabled()
    assert dlg.query_options()["num_rows"] == 7


def test_dialog_edit_before_acquire_is_noop(qapp):
    """취득 전(스냅샷 없음) 편집은 게이트·라벨에 무영향 — 이미 잠겨 있다."""
    from PySide6.QtWidgets import QDialogButtonBox

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    before = dlg.lbl_result.text()  # UD-09: 초기부터 게이트 사유가 발화돼 있다
    dlg.spin_page.setValue(3)
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert dlg.lbl_result.text() == before  # 편집은 사유 문구를 바꾸지 않는다(무영향)


def test_dialog_initial_gate_reason_is_always_spoken(qapp):
    """UD-09: 초기 상태에서 OK 잠금 사유가 라벨(muted)·툴팁으로 상시 발화된다."""
    from PySide6.QtWidgets import QDialogButtonBox

    from hwpxfiller.gui.nara_view import _GATE_HINT

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())

    # 사용자 행동 전부터 사유가 화면에 있다(침묵 해소).
    assert dlg.lbl_result.text() == _GATE_HINT
    assert dlg.lbl_result.property("muted") is True
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()
    assert ok.toolTip()                 # 비활성 확인 버튼 잠금 사유 툴팁
    assert dlg.btn_retry.toolTip()      # 재시도 잠금 사유
    assert dlg.btn_stop.toolTip()       # 중지 잠금 사유

    # 취득 성공 → 라벨이 요약(muted 해제)으로 교체되고 게이트가 열린다.
    _acquire(dlg)
    assert dlg.lbl_result.text() != _GATE_HINT
    assert not dlg.lbl_result.property("muted")
    assert ok.isEnabled()


def test_query_options_is_acquire_time_snapshot_or_loud_failure(qapp):
    """query_options 는 취득 시점 캡처값 — 스냅샷 없으면 조용한 위젯값 폴백 대신 시끄럽게."""
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    with pytest.raises(RuntimeError):
        dlg.query_options()  # 취득 전

    _acquire(dlg)
    opts = dlg.query_options()
    bgn, end = dlg.datetime_range()  # 편집 전이므로 위젯 현재값 == 취득 시점값
    assert (opts["bgn_dt"], opts["end_dt"]) == (bgn, end)
    assert (opts["num_rows"], opts["page_no"]) == (100, 1)


def test_dialog_connection_test_reports_result(qapp):
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    dlg._on_test()
    _wait_idle(dlg)  # 연결시험도 QThread(RC-12)
    assert "성공" in dlg.lbl_test.text()


# ------------------------------------------------------------ 백그라운드 취득(RC-12)
def test_acquire_runs_off_ui_thread_with_busy_lock(qapp):
    """RC-12: 취득 중 UI 스레드 비블로킹 — 즉시 반환 + 입력·액션 잠금 + 진행 표시."""
    import threading

    from PySide6.QtWidgets import QDialogButtonBox

    gate = threading.Event()

    def slow_fetch(url: str) -> bytes:
        gate.wait(5.0)  # 정부 API 지연 모사 — UI 스레드였다면 여기서 동결
        return _fixture_bytes()

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, slow_fetch)
    dlg._on_acquire()  # 동기 urlopen이었다면 이 호출 자체가 5초 블록 후 busy=False
    assert dlg._busy                       # 즉시 반환 — 백그라운드 진행 중
    assert not dlg.btn_acquire.isEnabled()  # 취득 중 버튼 비활성
    assert not dlg.btn_test.isEnabled()
    assert not dlg.dt_bgn.isEnabled()       # 진행 중 입력 잠금(스냅샷 경합 차단)
    assert dlg.btn_stop.isEnabled()         # 취소 수단 존재
    assert "가져오는 중" in dlg.lbl_result.text()  # 진행 표시
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()

    gate.set()
    _wait_idle(dlg)
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert len(dlg.records) == 2


def test_stop_discards_inflight_result(qapp):
    """RC-12: 중지 = 즉시 UI 복원 + 도착한 결과 폐기(스테일 스냅샷 수용 금지)."""
    import threading

    from PySide6.QtWidgets import QDialogButtonBox

    gate = threading.Event()

    def slow_fetch(url: str) -> bytes:
        gate.wait(5.0)
        return _fixture_bytes()

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, slow_fetch)
    dlg._on_acquire()
    assert dlg._busy

    dlg._on_stop_fetch()
    assert not dlg._busy                    # 프리즈 없이 즉시 복원
    assert "중지" in dlg.lbl_result.text()
    assert dlg.btn_acquire.isEnabled()      # 재시도 가능

    gate.set()
    _drain_tasks(dlg)                       # 뒤늦게 도착한 결과는 폐기된다
    assert dlg.vm.last_result is None
    assert dlg.records == []
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()


def test_stop_after_reacquire_syncs_gate_and_restates_residual(qapp):
    """UD-29 (D10): 성공→재취득→중지 시 라벨·게이트 정합.

    재취득 시작이 이전 성공 요약을 '가져오는 중…'으로 덮은 뒤 중지하면, 잔존
    스냅샷 기준으로 OK 가 재개방되는데 발화는 '중지'뿐이어서 무엇이 수용 대기인지
    화면에 없었다(신호 모순). 수리 후엔 중지 문구가 잔존 스냅샷 요약(기간·건수)을
    병기해 OK 재개방과 정합한다.
    """
    import threading

    from PySide6.QtWidgets import QDialogButtonBox

    gate = threading.Event()
    state = {"slow": False}

    def fetch(url: str) -> bytes:
        if state["slow"]:
            gate.wait(5.0)  # 2차(재취득)만 블로킹 — 중지 개입 창을 연다
        return _fixture_bytes()

    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, fetch)
    ok = dlg.buttons.button(QDialogButtonBox.Ok)

    _acquire(dlg)                                  # 1차 취득 성공 → 스냅샷·게이트 개방
    assert ok.isEnabled()
    assert dlg.vm.last_result is not None

    state["slow"] = True
    dlg._on_acquire()                              # 재취득 시작 — 진행 표시가 요약을 덮음
    assert dlg._busy
    assert "가져오는 중" in dlg.lbl_result.text()
    assert not ok.isEnabled()                      # 진행 중 게이트 잠금

    dlg._on_stop_fetch()                           # 중지 — 잔존 스냅샷 기준 복원
    assert not dlg._busy
    assert ok.isEnabled()                          # 게이트-라벨 정합: 직전 취득분 수용 대기
    text = dlg.lbl_result.text()
    assert "중지" in text                           # 중지 사실 발화
    assert "직전 취득분" in text                     # 무엇이 수용 대기인지 재진술
    assert "2건" in text                            # 잔존 스냅샷 요약(건수) 병기
    assert dlg.vm.last_result is not None          # 스냅샷 보존

    gate.set()
    _drain_tasks(dlg)                              # 뒤늦은 재취득 결과는 폐기(seq 무효화)
    assert dlg.vm.last_result is not None          # 여전히 1차 스냅샷 유지
    assert ok.isEnabled()


# ------------------------------------------------------------ DataPage 소스 선택
def _data_page(qapp, tmp_path, *, store=None, fetcher=None):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    # RC-25: 주입은 생성자 파라미터(선언 계약) — 키워드 오타는 TypeError 로 시끄럽게.
    wiz = JobEditorWizard(
        JobRegistry(tmp_path), secret_store=store, nara_fetcher=fetcher
    )
    page = wiz.page(wiz.pageIds()[1])  # DataPage
    return wiz, page


def test_datapage_source_toggle_swaps_input_rows(qapp, tmp_path):
    wiz, page = _data_page(qapp, tmp_path)
    assert not page.nara_row.isVisible() or page.rb_excel.isChecked()
    page.rb_nara.setChecked(True)
    assert page.excel_row.isHidden()      # offscreen: isVisible 대신 isHidden
    assert not page.nara_row.isHidden()
    # 소스 전환은 이전에 로드한 데이터 선택을 무효화한다(_valid=False). 단 J1 강등 이후
    # DataPage 는 선택 단계라 isComplete()==True(데이터 없이도 진행) — 둘은 분리됐다.
    assert not page._valid
    assert page.isComplete()


def test_datapage_apply_nara_result_seeds_session_and_vocab(qapp, tmp_path):
    """취득 결과 적용 → 위저드 세션에 레코드/어휘 심김 → MappingPage 가 어휘로 자동초안."""
    from hwpxfiller.gui.nara_state import AcquiredNaraData

    wiz, page = _data_page(qapp, tmp_path)
    records = [{"bidNtceNm": "전산장비 구매", "presmptPrce": "21326800"}]
    ds = AcquiredNaraData(records, ["bidNtceNm", "presmptPrce"])
    page.rb_nara.setChecked(True)
    page._apply_nara_result(records, ds.fields(), ds, "나라장터 · 1건")

    assert page.isComplete()
    assert wiz.datasource is ds
    assert wiz.records == records
    assert wiz.data_path == "나라장터 · 1건"

    # MappingPage 가 소스 어휘(field_labels)로 퍼지 자동초안 — bidNtceNm→공고명.
    wiz.template_path = "/t.hwpx"
    wiz.schema = TemplateSchema(fields=[FieldSpec("공고명", "text", 1, False)])
    mapping_page = wiz.page(wiz.pageIds()[2])
    mapping_page.initializePage()
    row = next(r for r in wiz.model.rows if r.template_field == "공고명")
    assert row.sources == ["bidNtceNm"]  # 어휘 관통(V1→N2) 자동제안


def test_key_never_reaches_job_serialization(qapp, tmp_path):
    """e2e 관통 — 취득→매핑→작업 저장 후 저장 JSON 에 ServiceKey 흔적 0(키 비직렬화)."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.nara_state import NaraAcquireViewModel

    store = MemorySecretStore()
    # 키 등록은 저장소로만(위저드/작업 경유 아님).
    NaraAcquireViewModel(store).save_key(_LIVE_KEY)

    wiz, page = _data_page(qapp, tmp_path, store=store, fetcher=lambda url: _fixture_bytes())
    vm = NaraAcquireViewModel(store, fetcher=lambda url: _fixture_bytes())
    res = vm.acquire("202606010000", "202606302359")
    page.rb_nara.setChecked(True)
    page._apply_nara_result(res.records, res.fields, res.as_datasource(), res.summary())

    wiz.template_path = "/t.hwpx"
    wiz.schema = TemplateSchema(fields=[FieldSpec("공고명", "text", 1, False)])
    mapping_page = wiz.page(wiz.pageIds()[2])
    mapping_page.initializePage()
    for i, row in enumerate(wiz.model.rows):
        if row.template_field == "공고명":
            wiz.model.set_sources(i, ["bidNtceNm"])
    wiz.model.confirm_all()

    profile = wiz.model.to_profile("공고작업")
    from hwpxfiller.core.job import Job

    job = Job(name="공고작업", template_path="/t.hwpx", mapping=profile)
    reg = JobRegistry(tmp_path)
    reg.save(job)
    saved = reg.path_for("공고작업").read_text(encoding="utf-8")
    assert _LIVE_KEY not in saved
    assert "ServiceKey" not in saved
