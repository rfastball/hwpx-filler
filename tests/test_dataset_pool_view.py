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


def test_panel_register_nara_from_dialog_saves_query_only(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel
    from hwpxfiller.gui.nara_view import NaraAcquireDialog

    reg = DatasetPoolRegistry(tmp_path)
    store = MemorySecretStore({NARA_SERVICE_KEY_NAME: _LIVE_KEY})
    panel = DatasetPoolPanel(reg, store=store, fetcher=lambda url: _fixture_bytes())

    dlg = NaraAcquireDialog(store=store, fetcher=lambda url: _fixture_bytes())
    dlg._on_acquire()  # 취득 성공(수용 가능 상태)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("공고6월", True))
    panel._register_nara_from_dialog(dlg)

    assert reg.exists("공고6월")
    item = reg.load("공고6월")
    assert item.kind == "nara" and "service_key" not in item.opts
    saved = reg.path_for("공고6월").read_text(encoding="utf-8")
    assert _LIVE_KEY not in saved


def test_panel_delete_confirms_then_removes(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.dataset_pool_panel import DatasetPoolPanel

    reg = DatasetPoolRegistry(tmp_path)
    reg.save(DatasetPoolItem(name="D", kind="excel", opts={"path": "/d.xlsx"}))
    panel = DatasetPoolPanel(reg)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    panel._dispatch("delete", "D")
    assert reg.exists("D")  # 거절 → 유지

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
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
    dlg._on_preview()
    assert dlg.tbl_preview.rowCount() == 1
    assert dlg.tbl_preview.item(0, 2).text() == "서울"
    assert dlg.lbl_error.isHidden()
    # 저장 → 참조만 풀 항목
    dlg.edt_name.setText("조립6월")
    dlg._on_save()
    assert dlg.saved_name == "조립6월"
    assert reg.load("조립6월").kind == "pipeline"


def test_pipeline_builder_preview_error_surfaces(qapp, tmp_path):
    from hwpxfiller.gui.pipeline_builder import PipelineBuilderDialog

    reg = DatasetPoolRegistry(tmp_path / "pool")
    dlg = PipelineBuilderDialog(reg)
    dlg._on_preview()  # 소스 없음 → 시끄러운 오류 라벨(빈 표 조용히 금지)
    assert not dlg.lbl_error.isHidden()
    assert "소스" in dlg.lbl_error.text()


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
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", sources=["공고명"])]),
        filename_pattern="doc-{{공고명}}",
    )
    view = RunView(job, pool_registry=reg)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("6월", True))
    view._pick_from_pool()
    assert view.records and view.records[0]["공고명"] == "전산장비"
    assert view.ed_data.text().startswith("풀: 6월")


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
    assert "활성 데이터가 없습니다" in seen.get("msg", "")
