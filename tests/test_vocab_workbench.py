"""어휘 워크벤치 + 위저드 베이스 시드(J3) 테스트 — offscreen.

베이스 적용의 이름 교집합 투영·미커버 loud 게이트, 베이스로 저장, 워크벤치 관리(참조수·
삭제·이름변경), home/app 라우팅을 못박는다. 코어(레지스트리·계보)는 test_mapping_base.py.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from hwpxfiller.core.job import Job, JobRegistry  # noqa: E402
from hwpxfiller.core.mapping import FieldMapping, MappingProfile  # noqa: E402
from hwpxfiller.core.mapping_base import MappingBaseRegistry  # noqa: E402
from hwpxfiller.core.schema import FieldSpec, TemplateSchema  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _base(name="조달어휘") -> MappingProfile:
    return MappingProfile(name=name, mappings=[
        FieldMapping(template_field="공고명", sources=["bidNtceNm"]),
        FieldMapping(template_field="추정가격", sources=["presmptPrce"], transform="amount"),
    ])


# ------------------------------------------------------ 위저드 베이스 시드(핵심)
def test_wizard_base_seed_projects_name_intersection_and_gates(qapp, tmp_path):
    """베이스 적용 = 이름 교집합 투영 + pre-confirm; 미커버 필드는 미확정 → 게이트 차단."""
    from hwpxfiller.gui.job_editor import JobEditorWizard

    wiz = JobEditorWizard(JobRegistry(tmp_path))
    wiz.base_mapping = _base()  # 공고명·추정가격
    wiz.template_path = "/t.hwpx"
    # 템플릿은 공고명(베이스 커버) + 담당자(베이스 미커버). 추정가격은 템플릿에 없음.
    wiz.schema = TemplateSchema(fields=[
        FieldSpec("공고명", "text", 1, False),
        FieldSpec("담당자", "text", 1, False),
    ])
    wiz.source_fields = []
    wiz.records = []
    page = wiz.page(wiz.pageIds()[2])  # MappingPage
    page.initializePage()

    rows = {r.template_field: r for r in wiz.model.rows}
    assert set(rows) == {"공고명", "담당자"}       # 템플릿 필드만(추정가격=베이스에만, skip)
    assert rows["공고명"].confirmed                 # 베이스 커버 → pre-confirm
    assert rows["공고명"].sources == ["bidNtceNm"]
    assert not rows["담당자"].confirmed             # 미커버 → 미확정
    assert not wiz.model.is_complete()              # 미커버 필드가 게이트 차단(ADR D, loud)


def test_wizard_apply_base_button_sets_lineage(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.job_editor import JobEditorWizard

    base_reg = MappingBaseRegistry(tmp_path / "bases")
    base_reg.save(_base())
    wiz = JobEditorWizard(JobRegistry(tmp_path / "jobs"), base_registry=base_reg)
    wiz.template_path = "/t.hwpx"
    wiz.schema = TemplateSchema(fields=[FieldSpec("공고명", "text", 1, False)])
    wiz.source_fields = []
    wiz.records = []
    page = wiz.page(wiz.pageIds()[2])
    page.initializePage()

    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("조달어휘", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    page._apply_base()
    assert wiz.base_mapping_name == "조달어휘"       # 계보 설정
    row = next(r for r in wiz.model.rows if r.template_field == "공고명")
    assert row.confirmed and row.sources == ["bidNtceNm"]


def test_wizard_save_base_registers_profile(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.mapping_state import MappingModel

    base_reg = MappingBaseRegistry(tmp_path / "bases")
    wiz = JobEditorWizard(JobRegistry(tmp_path / "jobs"), base_registry=base_reg)
    wiz.model = MappingModel.from_profile(_base())  # 확정본
    page = wiz.page(wiz.pageIds()[2])

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("새어휘", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    page._save_base()
    assert base_reg.exists("새어휘")
    assert base_reg.load("새어휘").template_fields() == ["공고명", "추정가격"]
    assert wiz.base_mapping_name == "새어휘"


def test_job_editor_accept_carries_base_mapping_name(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.mapping_state import MappingModel

    reg = JobRegistry(tmp_path)
    wiz = JobEditorWizard(reg)
    wiz.base_mapping_name = "조달어휘"
    wiz.template_path = "/t.hwpx"
    wiz.model = MappingModel.from_profile(_base())  # 확정·내용 있음
    wiz._save_page.ed_name.setText("공고작업")
    wiz.accept()  # 신규 이름 — 덮어쓰기 확인 없이 저장
    assert reg.load("공고작업").base_mapping_name == "조달어휘"


# ------------------------------------------------------ 워크벤치 VM (헤드리스)
def _setup(tmp_path, ref_job=True):
    base_reg = MappingBaseRegistry(tmp_path / "bases")
    base_reg.save(_base("조달어휘"))
    base_reg.save(_base("구매어휘"))
    job_reg = JobRegistry(tmp_path / "jobs")
    if ref_job:
        job_reg.save(Job(name="공고작업", template_path="/t.hwpx",
                         mapping=_base(), base_mapping_name="조달어휘"))
    return base_reg, job_reg


def test_workbench_vm_lists_with_ref_counts(qapp, tmp_path):
    from hwpxfiller.gui.vocab_workbench_state import VocabWorkbenchViewModel

    base_reg, job_reg = _setup(tmp_path)
    vm = VocabWorkbenchViewModel(base_reg, job_reg)
    rows = {r.name: r for r in vm.rows()}
    assert set(rows) == {"조달어휘", "구매어휘"}
    assert rows["조달어휘"].ref_count == 1
    assert rows["구매어휘"].ref_count == 0
    assert vm.ref_names("조달어휘") == ["공고작업"]


def test_workbench_vm_rename_updates_job_lineage(qapp, tmp_path):
    from hwpxfiller.gui.vocab_workbench_state import VocabWorkbenchViewModel

    base_reg, job_reg = _setup(tmp_path)
    vm = VocabWorkbenchViewModel(base_reg, job_reg)
    vm.rename("조달어휘", "조달표준어휘")
    assert not base_reg.exists("조달어휘") and base_reg.exists("조달표준어휘")
    # 참조 작업 계보가 새 이름으로 갱신(매핑 내용은 불변).
    assert job_reg.load("공고작업").base_mapping_name == "조달표준어휘"


def test_workbench_vm_rename_rejects_existing(qapp, tmp_path):
    from hwpxfiller.gui.vocab_workbench_state import VocabWorkbenchViewModel

    base_reg, job_reg = _setup(tmp_path)
    vm = VocabWorkbenchViewModel(base_reg, job_reg)
    with pytest.raises(ValueError):
        vm.rename("조달어휘", "구매어휘")  # 이미 존재


def test_workbench_vm_delete(qapp, tmp_path):
    from hwpxfiller.gui.vocab_workbench_state import VocabWorkbenchViewModel

    base_reg, job_reg = _setup(tmp_path, ref_job=False)
    vm = VocabWorkbenchViewModel(base_reg, job_reg)
    vm.delete("구매어휘")
    assert not base_reg.exists("구매어휘")
    assert [r.name for r in vm.rows()] == ["조달어휘"]


# ------------------------------------------------------ 패널 + 라우팅(offscreen)
def test_panel_renders_and_edit_emits(qapp, tmp_path):
    from hwpxfiller.gui.vocab_workbench import VocabWorkbenchPanel

    base_reg, job_reg = _setup(tmp_path)
    panel = VocabWorkbenchPanel(base_reg, job_registry=job_reg)
    assert panel.list.count() == 2
    seen = []
    panel.edit_base_requested.connect(seen.append)
    panel._dispatch("edit", "조달어휘")
    assert seen == ["조달어휘"]


def test_panel_delete_with_refs_confirms(qapp, tmp_path, monkeypatch):
    from hwpxfiller.gui import vocab_workbench as vw
    from hwpxfiller.gui.vocab_workbench import VocabWorkbenchPanel

    base_reg, job_reg = _setup(tmp_path)
    panel = VocabWorkbenchPanel(base_reg, job_registry=job_reg)
    # 파괴 확인은 공용 헬퍼 경유(RC-15) — 참조 재진술 문구를 함께 검증.
    seen = {}
    monkeypatch.setattr(
        vw, "confirm_destructive",
        lambda parent, title, text, label: seen.update(text=text) or True,
    )
    changed = []
    panel.base_changed.connect(lambda: changed.append(True))
    panel._delete("조달어휘")
    assert not base_reg.exists("조달어휘") and changed
    # 확인 문구가 파괴 대상·참조 작업을 구체 이름으로 재진술(RC-15).
    assert "조달어휘" in seen["text"] and "공고작업" in seen["text"]


def test_app_opens_workbench_and_seeds_editor_from_base(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path))
    from hwpxfiller.gui.app import AppController
    from hwpxfiller.gui.job_editor import JobEditorWizard
    from hwpxfiller.gui.vocab_workbench import VocabWorkbenchPanel

    ctrl = AppController(JobRegistry(tmp_path / "jobs"))
    ctrl.base_registry.save(_base("조달어휘"))

    ctrl._open_vocab_workbench()
    panels = [c for c in ctrl._children if isinstance(c, VocabWorkbenchPanel)]
    assert len(panels) == 1

    ctrl._open_editor_from_base("조달어휘")
    wizards = [c for c in ctrl._children if isinstance(c, JobEditorWizard)]
    assert len(wizards) == 1
    assert wizards[0].base_mapping_name == "조달어휘"
    assert wizards[0].base_mapping.template_fields() == ["공고명", "추정가격"]
