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

    dlg._on_acquire()
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
    dlg._on_acquire()
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()           # 실패는 수용 불가
    assert dlg.records == []
    assert _LIVE_KEY not in dlg.lbl_result.text()
    assert "[REDACTED]" in dlg.lbl_result.text()
    assert dlg.btn_retry.isEnabled()    # 재시도 노출


def test_dialog_connection_test_reports_result(qapp):
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: "DUMMY"})
    dlg = _dialog(store, lambda url: _fixture_bytes())
    dlg._on_test()
    assert "성공" in dlg.lbl_test.text()


# ------------------------------------------------------------ DataPage 소스 선택
def _data_page(qapp, tmp_path, *, store=None, fetcher=None):
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    if store is not None:
        wiz.secret_store = store
    if fetcher is not None:
        wiz.nara_fetcher = fetcher
    page = wiz.page(wiz.pageIds()[1])  # DataPage
    return wiz, page


def test_datapage_source_toggle_swaps_input_rows(qapp, tmp_path):
    wiz, page = _data_page(qapp, tmp_path)
    assert not page.nara_row.isVisible() or page.rb_excel.isChecked()
    page.rb_nara.setChecked(True)
    assert page.excel_row.isHidden()      # offscreen: isVisible 대신 isHidden
    assert not page.nara_row.isHidden()
    assert not page.isComplete()          # 소스 전환은 이전 선택 무효화


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
