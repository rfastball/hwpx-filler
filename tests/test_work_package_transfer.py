"""작업 꾸러미 내보내기 조립·불러오기 계획의 순수 규칙(#1188 WP-03·WP-04).

제품 조립을 거치는 왕복은 ``test_webapp_work_package.py`` 가 진다. 여기는 이름 짓기(덮어쓰지 않는
사본 이름·예약 장치 이름)·계획 지문·계약 해독 거절·내보내기 사본(출처 메타만 비움·원본 불변)·
서식 폴더 새 파일 쓰기를 작은 입력으로 고정한다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hwpxfiller.application.work_package_export import (
    ExportDataUnavailable,
    draft_work_package,
)
from hwpxfiller.application.work_package_import import (
    TEMPLATE_NEW,
    TEMPLATE_REUSE,
    imported_job,
    plan_import,
)
from hwpxfiller.domain.copy_name import (
    device_safe_file_name,
    numbered_file_name,
    numbered_label,
)
from hwpxfiller.domain.job import Job
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.preset import SelectionPreset
from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet
from hwpxfiller.domain.work_package import (
    PackagedJob,
    PackagedTemplate,
    WorkPackageError,
    WorkPackageManifest,
)
from hwpxfiller.external.template_files import TemplateFileStore
from hwpxfiller.external.text_registry import TextTemplateRegistry

NOW = "2026-10-15T09:00:00"
BLOB = b"hwpx template bytes"
DIGEST = hashlib.sha256(BLOB).hexdigest()
OTHER = hashlib.sha256(b"other").hexdigest()
SELECTION = SlotSelectionSet((SlotSelection(slot_id="s1", selected_option_ids=("o1",)),))


def _mapping() -> MappingProfile:
    return MappingProfile(
        name="공고",
        mappings=[FieldMapping("건명", "공고명"), FieldMapping("담당", type="const", const="홍길동")],
        provenance={"dataset": "보낸쪽데이터.xlsx"},
    )


def _template(digest: str = DIGEST, name: str = "공고서.hwpx") -> PackagedTemplate:
    return PackagedTemplate(digest=digest, media="hwpx", display_name=name, size=len(BLOB))


def _job(name: str, digest: str = DIGEST, **kw) -> PackagedJob:
    return PackagedJob(
        name=name, media="hwpx", template_digest=digest,
        mapping=MappingProfile(mappings=[FieldMapping("건명", "공고명")]),
        filename_pattern="공고-{{seq:001}}", **kw,
    )


def _manifest(*jobs: PackagedJob, templates=None) -> WorkPackageManifest:
    return WorkPackageManifest(
        created_at=NOW, templates=tuple(templates or (_template(),)), jobs=jobs
    )


class Side:
    """받는 쪽 사실의 대역 — 이미 있는 작업·프리셋·파일 이름과 재사용할 템플릿."""

    def __init__(self, jobs=(), presets=(), files=(), existing=None) -> None:
        self.jobs, self.presets, self.files = set(jobs), set(presets), set(files)
        self.existing = existing or {}

    def job_taken(self, name: str) -> bool:
        return name in self.jobs

    def job_key(self, name: str) -> str:
        return name.casefold()

    def preset_taken(self, name: str) -> bool:
        return name in self.presets

    def file_taken(self, file_name: str) -> bool:  # Windows 파일 시스템처럼 대소문자 무관
        return file_name.casefold() in {name.casefold() for name in self.files}

    def existing_template(self, template: PackagedTemplate) -> "str | None":
        return self.existing.get(template.digest)


def test_copy_names_never_reuse_a_taken_name_and_avoid_device_names():
    assert numbered_label("계약", 1) == "계약"
    assert numbered_label("계약", 3) == "계약 (3)"
    assert numbered_file_name("계약.안내.hwpx", 2) == "계약.안내 (2).hwpx"
    assert numbered_file_name("확장자없음", 2) == "확장자없음 (2)"
    assert device_safe_file_name("CON.hwpx") == "CON_.hwpx"
    assert device_safe_file_name("lpt1.backup.txt") == "lpt1_.backup.txt"
    assert device_safe_file_name("CONTRACT.hwpx") == "CONTRACT.hwpx"


def test_plan_renames_collisions_with_numbered_copies_and_reuses_same_bytes():
    preset = SelectionPreset(name="계약", selection_set=SELECTION, provenance={}, created_at=NOW)
    manifest = _manifest(_job("계약", selection_presets=(preset,)), _job("기안"))
    side = Side(jobs={"계약", "계약 (2)"}, presets={"계약"}, existing={DIGEST: "C:/서식/공고서.hwpx"})

    plan = plan_import(manifest, side)

    assert [(j.final_name, j.renamed) for j in plan.jobs] == [("계약 (3)", True), ("기안", False)]
    (planned_preset,) = plan.presets
    assert (planned_preset.job_name, planned_preset.preset.name) == ("계약 (3)", "계약 (2)")
    assert planned_preset.renamed and planned_preset.preset.provenance == ()
    (template,) = plan.templates
    assert (template.action, template.target) == (TEMPLATE_REUSE, "C:/서식/공고서.hwpx")


def test_new_template_names_are_device_safe_and_unique_within_the_plan():
    templates = (_template(name="CON.hwpx"), _template(OTHER, name="con.hwpx"))
    manifest = _manifest(_job("가"), _job("나", OTHER), templates=templates)
    plan = plan_import(manifest, Side(files={"CON_.hwpx"}))
    assert [(t.action, t.target) for t in plan.templates] == [
        (TEMPLATE_NEW, "CON_ (2).hwpx"), (TEMPLATE_NEW, "con_ (3).hwpx"),
    ]


def test_basis_changes_when_the_receiving_side_changes_and_is_stable_otherwise():
    manifest = _manifest(_job("계약"))
    first = plan_import(manifest, Side())
    assert plan_import(manifest, Side()).basis == first.basis
    assert plan_import(manifest, Side(jobs={"계약"})).basis != first.basis
    assert plan_import(manifest, Side(existing={DIGEST: "x.hwpx"})).basis != first.basis


def test_broken_data_contract_is_refused_before_anything_is_planned():
    manifest = _manifest(_job("계약", data_contract={"schema": "data-contract/v9", "fields": []}))
    with pytest.raises(WorkPackageError, match="데이터 계약을 읽을 수 없습니다"):
        plan_import(manifest, Side())


def test_imported_job_lands_without_data_binding_or_local_history():
    plan = plan_import(_manifest(_job("계약")), Side())
    job = imported_job(plan.jobs[0], "C:/서식/공고서.hwpx")
    assert (job.name, job.template_path, job.data_path, job.authority_id) == (
        "계약", "C:/서식/공고서.hwpx", "", "",
    )
    assert (job.reviewed_rules, job.previous_rules, job.template_revision) == ({}, {}, 1)
    assert job.mapping is not plan.jobs[0].source.mapping


class Sources:
    """보내는 쪽 사실의 대역 — 데이터는 ``rows`` 가 None 이면 읽을 수 없다."""

    def __init__(self, rows=None, selection=None) -> None:
        self.rows, self.selection = rows, selection

    def template_bytes(self, job: Job) -> bytes:
        return BLOB

    def declared_selection(self, job: Job):
        return self.selection

    def records(self, job: Job):
        if self.rows is None:
            raise ExportDataUnavailable(job.name)
        return self.rows


def _sender_job(name: str, *, bound: bool = True) -> Job:
    return Job(
        name=name, template_path="C:\\홈\\template_authority\\applied\\x\\공고서.hwpx",
        mapping=_mapping(), data_path="C:\\데이터\\보낸쪽데이터.xlsx" if bound else "",
    )


def test_draft_dedupes_template_bytes_and_strips_only_provenance_from_copies():
    jobs = [_sender_job("가"), _sender_job("나")]
    draft = draft_work_package(
        jobs, Sources(rows=[{"공고명": "전산장비"}], selection=SELECTION), created_at=NOW
    )
    assert [t.display_name for t in draft.manifest.templates] == ["공고서.hwpx"]
    assert dict(draft.templates) == {DIGEST: BLOB}
    assert draft.without_contract == ()
    first = draft.manifest.jobs[0]
    assert first.mapping.provenance == {} and first.mapping.mappings == jobs[0].mapping.mappings
    assert jobs[0].mapping.provenance == {"dataset": "보낸쪽데이터.xlsx"}, "원본 작업은 그대로"
    assert [(p.name, p.provenance) for p in first.selection_presets] == [("가", ())]
    assert first.data_contract is not None and "전산장비" not in str(first.data_contract)


def test_jobs_whose_data_cannot_be_read_ship_without_contract_and_are_named():
    draft = draft_work_package(
        [_sender_job("가"), _sender_job("나", bound=False)], Sources(rows=None), created_at=NOW
    )
    assert draft.without_contract == ("가", "나")
    assert all(job.data_contract is None and job.selection_presets == ()
               for job in draft.manifest.jobs)


def test_add_bytes_never_overwrites_an_existing_library_file(tmp_path: Path):
    root = tmp_path / "templates"
    root.mkdir()
    (root / "공고서.hwpx").write_bytes(b"theirs")
    store = TemplateFileStore(lambda: root, TextTemplateRegistry(root))

    added = store.add_bytes("공고서.hwpx", BLOB)

    assert added == root / "공고서 (2).hwpx" and added.read_bytes() == BLOB
    assert (root / "공고서.hwpx").read_bytes() == b"theirs"
    assert sorted(p.name for p in root.iterdir()) == ["공고서 (2).hwpx", "공고서.hwpx"]
