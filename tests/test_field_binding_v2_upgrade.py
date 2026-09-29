"""이전 판(field-binding/v2) 판본의 처리 — 조용한 손실 없이 승격하거나 시끄럽게 막는다 (#1081 PR0b).

v2 판본은 legacy ``type`` 을 버려 표시형을 모른다. 그대로 실행하면 ``24,750,000원`` 이 되어야
할 자리에 ``24750000`` 이 나간다. 그래서:

- capture 는 v2 판본을 실행 입력으로 올리지 않고 NEEDS_BINDING_SEMANTIC_MIGRATION 으로 닫는다.
- 판본의 모든 규칙이 현재 Mapping 의 v2 사영과 정확히 같으면(= Mapping 이 곧 그 판본의 출처)
  봉인 직전 자동으로 현재 판으로 다시 확정한다 — 더해지는 것은 잃었던 ``type`` 하나뿐이다.
- Mapping 이 판본 뒤에 바뀌었으면 승격하지 않는다 — blocker 가 남고 편집기 확정이 푼다.

디스크의 v2 판본은 이전 빌드가 쓴 모양 그대로(append-only 이력 + current pointer) 만든다.
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
    FIELD_BINDING_SEMANTIC_VERSION_V2,
    digest_binding_rules,
)
from hwpxfiller.external.field_binding_store import (
    WorkFieldBindingStore,
    load_current_revision,
)
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore
from hwpxfiller.host.locations import default_template_authority_dir, home_dir

WORK = "이전판"


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
    # 라우팅은 PR2 몫 — 이 slot 없는 Work 를 managed 갈래로 보낸다(나머지는 실제 조립).
    job.execution.is_managed_hwpx = lambda _ref, j: bool(j.media == "hwpx" and j.authority_id)
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
    """현재 판본을 이전 빌드(field-binding/v2)가 적었을 모양으로 이력 끝에 덧붙이고 가리킨다.

    v2 는 ``type`` 을 버리고 ``fmt or None`` 만 적었다 — 그 모양 그대로다.
    """
    bindings, works = _stores()
    application_id = works.load(work_id).work.current_template_application_id
    current = _current_revision(work_id)
    v2_rules = tuple(
        dataclasses.replace(rule, format_kind=None, format_code=rule.format_code or None)
        for rule in current.binding_rules
    )
    digest = digest_binding_rules(v2_rules, contract_id=FIELD_BINDING_SEMANTIC_VERSION_V2)
    revision_id = field_binding_authority_revision_identity(
        work_authority_id=current.work_authority_id,
        base_template_application_id=current.base_template_application_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V2,
        source_schema_contract_id=current.source_schema_contract_id,
        raw_record_contract_id=current.raw_record_contract_id,
        canonical_binding_digest=digest,
        canonical_source_schema_digest=current.canonical_source_schema_digest,
    )
    v2 = dataclasses.replace(
        current,
        field_binding_authority_revision=revision_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V2,
        binding_rules=v2_rules,
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
            immutable_binding_revisions=aggregate.immutable_binding_revisions + (v2,),
        )

    bindings.update(work_id, stored.aggregate_version, mutate)
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V2
    )
    return v2


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


def test_a_v2_revision_never_becomes_an_execution_input(app, tmp_path):
    work_id = _seat_slotless_work(app, tmp_path / "out")
    _write_as_previous_build(work_id)

    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)


def test_a_lossless_v2_revision_is_upgraded_before_sealing(app, tmp_path):
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    v2 = _write_as_previous_build(work_id)

    app.dispatch("job", "resolve_execution", {})  # 봉인 직전 무손실 승격

    upgraded = _current_revision(work_id)
    assert upgraded.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION
    assert {r.field_id for r in upgraded.binding_rules} == {r.field_id for r in v2.binding_rules}
    kinds = {r.field_id: (r.format_kind, r.format_code) for r in upgraded.binding_rules}
    assert kinds["계약금액"] == ("amount", "")   # v2 가 잃었던 type 이 Mapping 에서 돌아왔다
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    assert "24,750,000원" in _section_text(out)


def test_a_v2_revision_behind_an_edited_mapping_stays_blocked_until_confirmed(app, tmp_path):
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    _write_as_previous_build(work_id)
    job = app.controllers["job"]

    def edit_without_confirming(saved) -> None:
        for item in saved.mapping.mappings:
            if item.template_field == "계약금액":
                item.fmt = "{:,}"

    job.registry.mutate(WORK, edit_without_confirming)
    app.dispatch("job", "resolve_execution", {})

    # Mapping 이 판본의 출처임을 증명할 수 없다 — 승격하지 않고, 실행도 열리지 않는다.
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V2
    )
    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)
    refused = app.generate("job")
    assert refused["ok"] is False
    assert not list(out.glob("*.hwpx"))

    # 편집기 확정(저장 hook)이 현재 Mapping 으로 다시 확정한다 — 그때 실행이 열린다.
    assert job.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION
    )
    app.dispatch("job", "resolve_execution", {})
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    assert "24,750,000<" in _section_text(out)
