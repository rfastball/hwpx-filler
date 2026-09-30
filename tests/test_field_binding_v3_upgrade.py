"""이전 판(field-binding/v3) 판본의 처리 — 가공 슬롯이 없던 판을 조용한 손실 없이 승격하거나 막는다.

v3 판본은 가공(v4)을 실을 자리가 없다. 그대로 실행 입력으로 올리면 현재 Mapping 이 가공을 들고
있어도 칸 전체가 문서로 나간다. 그래서 v2 와 같은 규율을 따른다:

- capture 는 v3 판본을 실행 입력으로 올리지 않고 NEEDS_BINDING_SEMANTIC_MIGRATION 으로 닫는다.
- 판본의 모든 규칙이 현재 Mapping 의 v3 사영(가공 없음 포함)과 정확히 같으면 봉인 직전 자동으로
  현재 판으로 다시 확정한다 — 가공이 설 수 없던 판이라 더해지는 것이 없다(무손실).
- Mapping 이 판본 뒤에 가공을 얻었으면 승격하지 않는다 — blocker 가 남고 편집기 확정이 푼다.

디스크의 v3 판본은 이전 빌드가 쓴 모양 그대로(append-only 이력 + current pointer) 만든다.
"""
from __future__ import annotations

import dataclasses
import uuid
import zipfile
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.application.field_binding_input import (
    NEEDS_BINDING_SEMANTIC_MIGRATION,
    FieldBindingRevision,
    field_binding_authority_revision_identity,
)
from hwpxfiller.application.stored_field_binding import ApplicationRevisionPointer
from hwpxfiller.domain.field_binding import (
    FIELD_BINDING_SEMANTIC_VERSION,
    FIELD_BINDING_SEMANTIC_VERSION_V3,
    digest_binding_rules,
)
from hwpxfiller.domain.text_slice import TextSlice
from hwpxfiller.external.field_binding_store import (
    WorkFieldBindingStore,
    load_current_revision,
)
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore
from hwpxfiller.host.locations import default_template_authority_dir, home_dir

WORK = "이전판v3"


@pytest.fixture
def app(tmp_path):
    from hwpxfiller.webapp.app import WebFrontend

    frontend = WebFrontend()
    assert frontend.dispatch("tpl", "install_examples", {"confirm": True})["ok"] is True
    return frontend


def _asset(name: str) -> Path:
    return next(home_dir().rglob(name))


def _seat_slotless_work(app, out: Path) -> str:
    editor = app.controllers["editor"]
    app.dispatch("editor", "new_session", {})
    app.dispatch("editor", "use_library_template", {"path": str(_asset("계약체결안내.hwpx"))})
    editor.load_data_path(str(_asset("계약목록.csv")))
    app.dispatch("editor", "goto_section", {"section": "binding"})
    app.dispatch("editor", "confirm_suggested", {})
    app.dispatch("editor", "set_name", {"name": WORK})
    assert app.dispatch("editor", "save", {}) == {"ok": True, "saved_name": WORK}
    job = app.controllers["job"]
    app.dispatch("job", "select_job", {"name": WORK})
    app.dispatch("job", "set_all", {})
    pick_output_folder(job, out)
    return job.registry.load(WORK).authority_id


def _stores() -> tuple[WorkFieldBindingStore, AtomicWorkTemplateStateStore]:
    root = default_template_authority_dir()
    return WorkFieldBindingStore(root / "field_bindings"), AtomicWorkTemplateStateStore(
        root / "works"
    )


def _current_revision(work_id: str) -> FieldBindingRevision:
    bindings, works = _stores()
    application_id = works.load(work_id).work.current_template_application_id
    revision = load_current_revision(bindings, work_id, application_id)
    assert revision is not None
    return revision


def _write_as_previous_build(work_id: str) -> FieldBindingRevision:
    """현재 판본을 이전 빌드(field-binding/v3)가 적었을 모양으로 이력 끝에 덧붙이고 가리킨다.

    v3 는 규칙 객체가 v4 와 같고(가공 슬롯만 없다) framing·판 이름만 다르다 — 그 모양 그대로다.
    """
    bindings, works = _stores()
    application_id = works.load(work_id).work.current_template_application_id
    current = _current_revision(work_id)
    assert all(rule.text_slice is None for rule in current.binding_rules)
    digest = digest_binding_rules(
        current.binding_rules, contract_id=FIELD_BINDING_SEMANTIC_VERSION_V3
    )
    revision_id = field_binding_authority_revision_identity(
        work_authority_id=current.work_authority_id,
        base_template_application_id=current.base_template_application_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V3,
        source_schema_contract_id=current.source_schema_contract_id,
        raw_record_contract_id=current.raw_record_contract_id,
        canonical_binding_digest=digest,
        canonical_source_schema_digest=current.canonical_source_schema_digest,
    )
    v3 = dataclasses.replace(
        current,
        field_binding_authority_revision=revision_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V3,
        canonical_binding_digest=digest,
    )
    stored = bindings.load(work_id)

    def mutate(aggregate):
        pointers = tuple(
            ApplicationRevisionPointer(p.application_id, revision_id)
            if p.application_id == application_id
            else p
            for p in aggregate.current_by_application
        )
        return dataclasses.replace(
            aggregate,
            aggregate_version=aggregate.aggregate_version + 1,
            current_by_application=pointers,
            immutable_binding_revisions=aggregate.immutable_binding_revisions + (v3,),
        )

    bindings.update(work_id, stored.aggregate_version, mutate)
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V3
    )
    return v3


def _seal_blockers(app) -> tuple[str, ...]:
    outcome = app.controllers["job"].execution.seal_execution.seal_execution_plan(
        WORK, uuid.uuid4().hex
    ).command_outcome
    return tuple(getattr(outcome, "normalized_blockers", ()) or ())


def _section_text(out: Path) -> str:
    return "".join(
        zipfile.ZipFile(doc).read("Contents/section0.xml").decode("utf-8")
        for doc in sorted(out.glob("*.hwpx"))
    )


def test_a_v3_revision_never_becomes_an_execution_input(app, tmp_path):
    work_id = _seat_slotless_work(app, tmp_path / "out")
    _write_as_previous_build(work_id)

    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)


def test_a_lossless_v3_revision_is_upgraded_before_sealing(app, tmp_path):
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    v3 = _write_as_previous_build(work_id)

    app.dispatch("job", "resolve_execution", {})  # 봉인 직전 무손실 승격

    upgraded = _current_revision(work_id)
    assert upgraded.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION
    # 가공이 설 수 없던 판이다 — 규칙은 한 글자도 바뀌지 않고 판만 오른다.
    assert set(upgraded.binding_rules) == set(v3.binding_rules)
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    assert "24,750,000원" in _section_text(out)


def test_a_v3_revision_behind_a_sliced_mapping_stays_blocked_until_confirmed(app, tmp_path):
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    _write_as_previous_build(work_id)
    job = app.controllers["job"]

    def slice_without_confirming(saved) -> None:
        for item in saved.mapping.mappings:
            if item.template_field == "공고번호":
                item.slice = TextSlice("split", delimiter="-", index=1)

    job.registry.mutate(WORK, slice_without_confirming)
    app.dispatch("job", "resolve_execution", {})

    # 판본 뒤에 가공이 생겼다 — Mapping 이 판본의 출처임을 증명할 수 없어 승격하지 않는다.
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V3
    )
    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)
    refused = app.generate("job")
    assert refused["ok"] is False
    assert not list(out.glob("*.hwpx"))

    # 편집기 확정(저장 hook)이 현재 Mapping 으로 다시 확정한다 — 가공이 판본에 실린다.
    assert job.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True
    current = _current_revision(work_id)
    assert current.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION
    sliced = {r.field_id: r.text_slice for r in current.binding_rules}
    assert sliced["공고번호"] == TextSlice("split", delimiter="-", index=1)
    app.dispatch("job", "resolve_execution", {})
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    text = _section_text(out)
    assert "20260812-001" not in text and "20260812" in text
