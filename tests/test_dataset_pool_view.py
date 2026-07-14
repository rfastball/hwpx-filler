"""데이터셋 풀 GUI(J1) 스모크 — offscreen. 패널 배선 + 위저드 데이터 강등 + 실행뷰 풀 겨눔.

깊은 로직은 test_dataset_pool*.py 가 헤드리스로 검증한다. 여기선 위젯 배선과 관통을 확인한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from hwpxfiller.core.dataset_pool import (  # noqa: E402
    STATUS_ACTIVE,
    DatasetPoolItem,
    DatasetPoolRegistry,
)
from hwpxfiller.data.secret_store import (  # noqa: E402
    NARA_SERVICE_KEY_NAME,
    MemorySecretStore,
)

FIXTURES = Path(__file__).parent / "fixtures"
_LIVE_KEY = "aB3+xY/z9Q==pLm4Kn7"


def _fixture_bytes() -> bytes:
    return (FIXTURES / "nara_std_response.json").read_bytes()


def _acquire_and_wait(dlg, timeout: float = 8.0) -> None:
    """나라 대화상자 취득이 QThread(RC-12)로 돌므로 busy 해제까지 이벤트 루프를 돌린다."""
    import time

    from PySide6.QtCore import QCoreApplication

    dlg._on_acquire()
    deadline = time.monotonic() + timeout
    while dlg._busy:
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("나라 취득이 제한시간 내에 끝나지 않았습니다")
        time.sleep(0.005)
    QCoreApplication.processEvents()


def _wait_pool_load(view, timeout: float = 8.0) -> None:
    """실행뷰 풀 복원이 QThread(RC-12)로 돌므로 완료(스레드 해제)까지 이벤트 루프를 돌린다."""
    import time

    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + timeout
    while view._data_thread is not None:
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("풀 복원이 제한시간 내에 끝나지 않았습니다")
        time.sleep(0.005)
    QCoreApplication.processEvents()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ------------------------------------------------------------ 패널 배선
def test_panel_renders_cards_with_gated_actions(qapp, tmp_path):
    from PySide6.QtWidgets import QPushButton

    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="활성D", kind="excel", opts={"path": "/a.xlsx"}))
    retired = DatasetPoolItem(name="은퇴D", kind="nara",
                              opts={"bgn_dt": "202606010000", "end_dt": "202606302359"})
    retired.retire()
    reg.save(retired)

    panel = DatasetPoolPanel(reg)
    assert panel.windowTitle() == "HWPX Filler — 데이터 관리"
    assert panel.btn_add_pipeline.text() == "데이터 조립…"
    assert panel.list.count() == 2
    by_name = {}
    for i in range(panel.list.count()):
        it = panel.list.item(i)
        by_name[it.text()] = panel.list.itemWidget(it)
    active_btns = [b.text() for b in by_name["활성D"].findChildren(QPushButton)]
    retired_btns = [b.text() for b in by_name["은퇴D"].findChildren(QPushButton)]
    assert active_btns == ["보관", "은퇴", "삭제"]
    assert retired_btns == ["활성화", "삭제"]


def test_panel_register_excel(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    reg = DatasetPoolRegistry(tmp_path)
    panel = DatasetPoolPanel(reg)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "d.csv"), "")
    )
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("6월데이터", True))
    panel._on_register_excel()
    assert reg.exists("6월데이터")
    assert reg.load("6월데이터").opts["path"].endswith("d.csv")
    assert panel.list.count() == 1


def test_panel_wires_in_place_registration_into_builder(qapp, tmp_path, monkeypatch):
    """#19 — 데이터 관리에서 연 조립 창은 기존 등록 절차 둘을 콜백으로 받는다."""
    from hwpxfiller.gui import pipeline_builder as pb
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    captured = {}

    class FakeBuilder:
        Accepted = 1

        def __init__(self, registry, parent, **kwargs):
            captured.update(kwargs)

        def exec(self):
            return 0

    monkeypatch.setattr(pb, "PipelineBuilderDialog", FakeBuilder)
    panel = DatasetPoolPanel(DatasetPoolRegistry(tmp_path / "pool"))
    panel._on_build_pipeline()
    assert captured["on_register_excel"] == panel._register_excel
    assert captured["on_register_nara"] == panel._register_nara


def test_panel_register_nara_from_dialog_saves_query_only(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel
    from hwpxfiller.gui.nara_view import NaraAcquireDialog

    reg = DatasetPoolRegistry(tmp_path)
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    panel = DatasetPoolPanel(reg, store=store, fetcher=lambda url: _fixture_bytes())

    dlg = NaraAcquireDialog(store=store, fetcher=lambda url: _fixture_bytes())
    _acquire_and_wait(dlg)  # 취득 성공(수용 가능 상태)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("공고6월", True))
    panel._register_nara_from_dialog(dlg)

    assert reg.exists("공고6월")
    item = reg.load("공고6월")
    assert item.kind == "nara" and "service_key" not in item.opts
    # 저장된 쿼리는 취득 시점 스냅샷과 동일(위젯 현재값 재독 아님 — RC-13).
    snap = dlg.query_options()
    assert item.opts["bgn_dt"] == snap["bgn_dt"]
    assert item.opts["end_dt"] == snap["end_dt"]
    assert item.opts["num_rows"] == 100 and item.opts["page_no"] == 1
    saved = reg.path_for("공고6월").read_text(encoding="utf-8")
    assert _LIVE_KEY not in saved


def test_panel_register_nara_refuses_stale_edited_dialog(qapp, tmp_path, monkeypatch):
    """RC-13: 취득 뒤 위젯 편집은 스냅샷을 무효화 — 등록은 시끄럽게 거절되고 풀은 무변화
    (편집된 미검증 기간이 죽은 참조로 조용히 저장되는 경로 차단)."""
    from PySide6.QtWidgets import QDialogButtonBox

    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel
    from hwpxfiller.gui.nara_view import NaraAcquireDialog

    reg = DatasetPoolRegistry(tmp_path)
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    panel = DatasetPoolPanel(reg, store=store, fetcher=lambda url: _fixture_bytes())

    dlg = NaraAcquireDialog(store=store, fetcher=lambda url: _fixture_bytes())
    _acquire_and_wait(dlg)  # 취득 성공
    dlg.dt_bgn.setDateTime(dlg.dt_bgn.dateTime().addMonths(-6))  # 취득 후 기간 편집
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()  # 수용 게이트 잠김

    seen = {}
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("스테일", True))
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: seen.setdefault("msg", a[2])
    )
    panel._register_nara_from_dialog(dlg)  # 게이트 우회 시도(헤드리스)도 거절
    assert not reg.exists("스테일")
    assert "가져오기" in seen.get("msg", "")


def test_panel_delete_confirms_then_removes(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui import dataset_pool_panel as dpp
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="D", kind="excel", opts={"path": "/d.xlsx"}))
    panel = DatasetPoolPanel(reg)

    # 파괴 확인은 공용 헬퍼 경유(RC-15) — 거절 → 유지.
    monkeypatch.setattr(dpp, "confirm_destructive", lambda *a, **k: False)
    panel._dispatch("delete", "D")
    assert reg.exists("D")

    monkeypatch.setattr(dpp, "confirm_destructive", lambda *a, **k: True)
    panel._dispatch("delete", "D")
    assert not reg.exists("D")


# ------------------------------------------------------------ 파이프라인 빌더(KB)
def test_pipeline_builder_dialog_author_preview_save(qapp, tmp_path):
    """빌더 배선 스모크 — 소스 추가→키 제안→스텝 추가→미리보기→저장(참조만) 관통.

    깊은 로직은 test_pipeline_builder_state.py 헤드리스가 검증. 여기선 위젯 배선만.
    """
    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    a = tmp_path / "base.csv"
    b = tmp_path / "look.csv"
    a.write_text("id,name\n1,A\n", encoding="utf-8-sig")
    b.write_text("id,city\n1,서울\n", encoding="utf-8-sig")
    reg = DatasetPoolRegistry(tmp_path / "pool")
    reg.save(DatasetPoolItem(name="기준", kind="excel", opts={"path": str(a)}))
    reg.save(DatasetPoolItem(name="참조표", kind="excel", opts={"path": str(b)}))

    dlg = PipelineBuilderDialog(reg)
    # 소스 2개 추가
    dlg.cmb_pool.setCurrentText("기준")
    dlg._on_add_source()
    assert dlg.cmb_pool.findText("기준") == -1  # 이미 넣은 데이터는 선택지에서 제거
    dlg.cmb_pool.setCurrentText("참조표")
    dlg._on_add_source()
    assert dlg.lst_sources.count() == 2
    # 키 제안 → 콤보에 후보만(스텝 미생성 게이트)
    dlg.cmb_target.setCurrentIndex(1)
    dlg._on_suggest()
    assert dlg.cmb_key.currentText() == "id"
    assert dlg.vm.steps == []
    # 스텝 추가(사람 확정) → 미리보기 표
    dlg._on_add_step()
    assert dlg.lst_steps.count() == 1
    # 렌더 후 대상 선택 보존 — 씨앗(0)으로 조용히 리셋되면 연속 클릭이 자기스텝을 만든다.
    assert dlg.cmb_target.currentData() == 1
    dlg._on_preview()
    assert dlg.tbl_preview.rowCount() == 1
    assert dlg.tbl_preview.item(0, 2).text() == "서울"
    assert dlg.lbl_error.isHidden()
    # 저장 → 참조만 풀 항목
    dlg.edt_name.setText("조립6월")
    dlg._on_save()
    assert dlg.saved_name == "조립6월"
    assert reg.load("조립6월").kind == "pipeline"


def test_pipeline_builder_blocks_duplicate_and_restores_removed_choice(
    qapp, tmp_path, monkeypatch
):
    """#19 — 중복 데이터는 stale 선택까지 시끄럽게 차단하고, 제거하면 다시 고를 수 있다."""
    from PySide6.QtWidgets import QMessageBox

    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    reg = DatasetPoolRegistry(tmp_path / "pool")
    reg.save(DatasetPoolItem(name="기준", kind="excel", opts={"path": "/a.csv"}))
    dlg = PipelineBuilderDialog(reg)
    dlg.cmb_pool.setCurrentText("기준")
    dlg._on_add_source()
    assert dlg.lst_sources.count() == 1

    # 갱신 직전 stale 콤보를 흉내 내도 이중 게이트가 중복을 막는다.
    dlg.cmb_pool.addItem("기준")
    dlg.cmb_pool.setCurrentText("기준")
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: messages.append(a[2]))
    dlg._on_add_source()
    assert dlg.lst_sources.count() == 1
    assert messages and "이미" in messages[-1]

    dlg.lst_sources.setCurrentRow(0)
    dlg._on_remove_source()
    assert dlg.cmb_pool.findText("기준") >= 0


def test_pipeline_builder_registers_new_data_in_place(qapp, tmp_path):
    """#19 — 조립 창을 닫지 않고 등록한 데이터가 즉시 선택되고 등록 대화의 부모도 현재 창이다."""
    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    reg = DatasetPoolRegistry(tmp_path / "pool")
    owners = []

    def register_excel(owner):
        owners.append(owner)
        reg.save(DatasetPoolItem(name="새 데이터", kind="excel", opts={"path": "/new.csv"}))

    dlg = PipelineBuilderDialog(reg, on_register_excel=register_excel)
    assert dlg.btn_register_excel.isEnabled()
    dlg.btn_register_excel.click()
    assert owners == [dlg]
    assert dlg.cmb_pool.currentText() == "새 데이터"


def test_pipeline_builder_uses_plain_language_and_short_preview_title(qapp, tmp_path):
    """#19 — 사용자 표면에는 쿼리 내부어 대신 결과를 설명하는 쉬운 말을 쓴다."""
    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    dlg = PipelineBuilderDialog(DatasetPoolRegistry(tmp_path / "pool"))
    assert dlg.windowTitle() == "데이터 조립"
    assert dlg.lbl_preview_title.text() == "미리보기"
    assert dlg.cmb_op.itemText(0) == "같은 값끼리 열 결합"
    assert dlg.cmb_op.itemText(1) == "아래에 행 추가"
    assert [dlg.cmb_how.itemText(i) for i in range(dlg.cmb_how.count())] == [
        "일치하는 행만 남김",
        "기준 데이터의 모든 행 유지",
    ]


def test_pipeline_builder_save_collision_gated_by_question(qapp, tmp_path, monkeypatch):
    """동명 저장은 사람 확정 게이트 — 거절 시 원본 무손실, 수락 시에만 덮어쓰기."""
    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    a = tmp_path / "a.csv"
    a.write_text("id\n1\n", encoding="utf-8-sig")
    reg = DatasetPoolRegistry(tmp_path / "pool")
    reg.save(DatasetPoolItem(name="기준", kind="excel", opts={"path": str(a)}))

    dlg = PipelineBuilderDialog(reg)
    dlg.cmb_pool.setCurrentText("기준")
    dlg._on_add_source()
    dlg.edt_name.setText("기준")  # 기존 항목과 동명

    from hwpxfiller.gui import pipeline_builder as pb

    # 파괴 확인은 공용 헬퍼 경유(RC-15) — 거절 → 원본 유지.
    monkeypatch.setattr(pb, "confirm_destructive", lambda *a, **k: False)
    dlg._on_save()
    assert dlg.saved_name is None
    assert reg.load("기준").kind == "excel"

    monkeypatch.setattr(pb, "confirm_destructive", lambda *a, **k: True)
    dlg._on_save()
    assert dlg.saved_name == "기준"
    assert reg.load("기준").kind == "pipeline"  # 확정 후에만 치환


def test_pipeline_builder_preview_error_surfaces(qapp, tmp_path):
    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    reg = DatasetPoolRegistry(tmp_path / "pool")
    dlg = PipelineBuilderDialog(reg)
    dlg._on_preview()  # 소스 없음 → 시끄러운 오류 라벨(빈 표 조용히 금지)
    assert not dlg.lbl_error.isHidden()
    assert "데이터" in dlg.lbl_error.text()


# ------------------------------------------------------------ 위저드 데이터 강등
def test_datapage_is_optional_without_data(qapp, tmp_path):
    """DataPage 는 이제 선택 — 데이터를 안 골라도 isComplete()==True(진행 가능)."""
    from hwpxfiller.core.job import JobRegistry
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    assert len(wiz.pageIds()) == 4  # 강등이지 삭제 아님 — 4페이지 유지
    data_page = wiz.page(wiz.pageIds()[1])
    assert data_page.isComplete()  # 데이터 없이도 진행


# ------------------------------------------------------------ 실행뷰 풀 겨눔
def test_run_view_picks_from_pool(qapp, tmp_path, monkeypatch):
    from hwpxfiller.core.job import Job
    from hwpxfiller.core.mapping import FieldMapping, MappingProfile
    from hwpxfiller.gui.run_view import RunView

    template = tmp_path / "t.hwpx"
    template.write_bytes(b"dummy")
    csv = tmp_path / "d.csv"
    csv.write_text("공고명\n전산장비\n", encoding="utf-8")
    reg = DatasetPoolRegistry(tmp_path / "pool")
    reg.save(DatasetPoolItem(name="6월", kind="excel", opts={"path": str(csv)}))

    job = Job(
        name="실행", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="공고명")]),
        filename_pattern="doc-{{공고명}}",
    )
    view = RunView(job, pool_registry=reg)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("6월", True))
    view._pick_from_pool()
    _wait_pool_load(view)  # 복원은 QThread(RC-12) — 완료까지 이벤트 루프
    assert view.records and view.records[0]["공고명"] == "전산장비"
    assert view.ed_data.text().startswith("등록 데이터: 6월")
    assert view.btn_pool.isEnabled()  # 복원 후 데이터 버튼 잠금 해제


def test_run_view_pool_empty_informs(qapp, tmp_path, monkeypatch):
    from hwpxfiller.core.job import Job
    from hwpxfiller.gui.run_view import RunView

    reg = DatasetPoolRegistry(tmp_path / "pool")  # 비어 있음
    job = Job(name="실행", template_path="/t.hwpx", filename_pattern="doc-{{ID}}")
    view = RunView(job, pool_registry=reg)
    seen = {}
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: seen.setdefault("msg", a[2])
    )
    view._pick_from_pool()
    assert "등록 데이터가 없습니다" in seen.get("msg", "")
