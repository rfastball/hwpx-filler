"""이전 판(field-binding/v4) 판본의 처리 — 가공이 두 방식·빈 값뿐이던 판을 손실 없이 승격하거나 막는다.

v4 판본은 가공(v5)의 새 방식(``before``·``after``·``between``·``head``·``tail``·``replace``·
``remove``)도 ``on_missing="keep"`` 도 실을 자리가 없다 — 두 방식(글자 범위·구분자 나누기)과
빈 값뿐이다. v3 와 같은 규율을 따른다(:mod:`tests.test_field_binding_v3_upgrade` 짝):

- capture 는 v4 판본을 실행 입력으로 올리지 않고 NEEDS_BINDING_SEMANTIC_MIGRATION 으로 닫는다.
- 판본의 모든 규칙이 현재 Mapping 의 v4 사영(v4 가 적을 수 있던 명세 그대로)과 정확히 같으면
  봉인 직전 자동으로 현재 판(v5)으로 다시 확정한다 — v4 의 두 방식·빈 값은 v5 에서 같은 뜻이라
  더해지는 것이 없다(무손실).
- Mapping 이 판본 뒤에 v5 가 더한 방식이나 ``keep`` 을 얻었으면 승격하지 않는다 — blocker 가
  남고 편집기 확정이 푼다.

디스크의 v4 판본은 이전 빌드가 쓴 모양 그대로(append-only 이력 + current pointer) 만든다.
"""
from __future__ import annotations

import dataclasses
import uuid
import zipfile
from datetime import datetime
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
    FIELD_BINDING_SEMANTIC_VERSION_V4,
    RUNTIME_DATE,
    digest_binding_rules,
)
from hwpxfiller.domain.text_slice import TextSlice
from hwpxfiller.external.field_binding_store import (
    WorkFieldBindingStore,
    load_current_revision,
)
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore
from hwpxfiller.host.locations import default_template_authority_dir, home_dir

WORK = "이전판v4"


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
    """현재 판본을 이전 빌드(field-binding/v4)가 적었을 모양으로 이력 끝에 덧붙이고 가리킨다.

    v4 는 규칙 객체가 v5 와 같고(두 방식·빈 값뿐인 가공만 적을 수 있다) framing·판 이름만 다르다.
    """
    bindings, works = _stores()
    application_id = works.load(work_id).work.current_template_application_id
    current = _current_revision(work_id)
    assert all(
        rule.text_slice is None or rule.text_slice.is_v4_expressible
        for rule in current.binding_rules
    )
    digest = digest_binding_rules(
        current.binding_rules, contract_id=FIELD_BINDING_SEMANTIC_VERSION_V4
    )
    revision_id = field_binding_authority_revision_identity(
        work_authority_id=current.work_authority_id,
        base_template_application_id=current.base_template_application_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V4,
        source_schema_contract_id=current.source_schema_contract_id,
        raw_record_contract_id=current.raw_record_contract_id,
        canonical_binding_digest=digest,
        canonical_source_schema_digest=current.canonical_source_schema_digest,
    )
    v4 = dataclasses.replace(
        current,
        field_binding_authority_revision=revision_id,
        field_binding_semantic_contract_id=FIELD_BINDING_SEMANTIC_VERSION_V4,
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
            immutable_binding_revisions=aggregate.immutable_binding_revisions + (v4,),
        )

    bindings.update(work_id, stored.aggregate_version, mutate)
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V4
    )
    return v4


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


def test_a_v4_revision_never_becomes_an_execution_input(app, tmp_path):
    work_id = _seat_slotless_work(app, tmp_path / "out")
    _write_as_previous_build(work_id)

    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)


def test_a_lossless_v4_revision_is_upgraded_before_sealing(app, tmp_path):
    """v4 가 적을 수 있던 명세(구분자 나누기, 빈 값)와 RUNTIME_DATE 를 실은 판본은 그대로 v5 로 오른다."""
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    job = app.controllers["job"]

    def add_slice_and_today(saved) -> None:
        for item in saved.mapping.mappings:
            if item.template_field == "공고번호":
                item.slice = TextSlice("split", delimiter="-", index=1)
            elif item.template_field == "납품조건":
                item.type, item.source, item.fmt = "today", "", "%Y-%m-%d"

    job.registry.mutate(WORK, add_slice_and_today)
    assert job.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True
    v4 = _write_as_previous_build(work_id)
    assert any(r.text_slice is not None for r in v4.binding_rules)
    assert any(r.binding_kind == RUNTIME_DATE for r in v4.binding_rules)

    job._clock = lambda: datetime(2026, 6, 15, 18, 4)
    app.dispatch("job", "resolve_execution", {})  # 봉인 직전 무손실 승격

    upgraded = _current_revision(work_id)
    assert upgraded.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION
    # v4 가 적을 수 있던 명세뿐이다 — 규칙은 한 글자도 바뀌지 않고 판만 오른다.
    assert set(upgraded.binding_rules) == set(v4.binding_rules)
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    text = _section_text(out)
    assert "20260812-001" not in text and "20260812" in text
    assert ">2026-06-15<" in text and "계약 후 90일 이내" not in text


def test_a_v4_revision_behind_a_new_mode_slice_stays_blocked_until_confirmed(app, tmp_path):
    """v4 는 새 방식(v5)을 적을 수 없었다 — Mapping 이 그 명세를 쓰면 판본 뒤의 편집이라 승격을 막는다."""
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    _write_as_previous_build(work_id)
    job = app.controllers["job"]

    def use_a_new_mode_without_confirming(saved) -> None:
        for item in saved.mapping.mappings:
            if item.template_field == "공고번호":
                item.slice = TextSlice("before", delimiter="-")

    job.registry.mutate(WORK, use_a_new_mode_without_confirming)
    app.dispatch("job", "resolve_execution", {})

    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V4
    )
    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)
    refused = app.generate("job")
    assert refused["ok"] is False
    assert not list(out.glob("*.hwpx"))

    # 편집기 확정(저장 hook)이 현재 Mapping 으로 다시 확정한다 — 새 방식 결과가 판본에 실린다.
    assert job.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True
    current = _current_revision(work_id)
    assert current.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION
    sliced = {r.field_id: r.text_slice for r in current.binding_rules}
    assert sliced["공고번호"] == TextSlice("before", delimiter="-")
    app.dispatch("job", "resolve_execution", {})
    result = app.generate("job")
    assert result["ok"] is True and result["status"] == "completed", result
    text = _section_text(out)
    assert "20260812-001" not in text and "20260812" in text


def test_a_v4_revision_behind_a_kept_miss_stays_blocked_until_confirmed(app, tmp_path):
    """v4 는 ``on_missing="keep"`` 을 적을 수 없었다(빈 값뿐이다) — 그 결정도 판본 뒤의 편집이다."""
    out = tmp_path / "out"
    work_id = _seat_slotless_work(app, out)
    job = app.controllers["job"]

    def add_slice(saved) -> None:
        for item in saved.mapping.mappings:
            if item.template_field == "공고번호":
                item.slice = TextSlice("split", delimiter="-", index=1)

    job.registry.mutate(WORK, add_slice)
    assert job.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True
    _write_as_previous_build(work_id)

    def keep_without_confirming(saved) -> None:
        for item in saved.mapping.mappings:
            if item.template_field == "공고번호":
                item.slice = TextSlice("split", delimiter="-", index=1, on_missing="keep")

    job.registry.mutate(WORK, keep_without_confirming)
    app.dispatch("job", "resolve_execution", {})
    assert _current_revision(work_id).field_binding_semantic_contract_id == (
        FIELD_BINDING_SEMANTIC_VERSION_V4
    )
    assert NEEDS_BINDING_SEMANTIC_MIGRATION in _seal_blockers(app)

    assert job.on_editor_mapping_saved(WORK)["binding_commit_ok"] is True
    current = _current_revision(work_id)
    assert current.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION
    sliced = {r.field_id: r.text_slice for r in current.binding_rules}
    assert sliced["공고번호"] == TextSlice(
        "split", delimiter="-", index=1, on_missing="keep"
    )
