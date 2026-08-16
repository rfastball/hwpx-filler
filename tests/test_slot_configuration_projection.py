"""구조적 Interactive Slot Projection DTO (S4-08 · #678).

pure Resolution → Product DTO shaping 만 검증한다(store·fence·HWPX 무관). #676 resolver·
#674 context 값 모델을 fixture 로 재사용한다.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.slot_configuration_projection import (
    CONTEXT_ERROR,
    CURRENT,
    HAS_BROKEN_SELECTIONS,
    NEEDS_SELECTION,
    NOT_APPLICABLE,
    SLOT_SELECTIONS_COMPLETE,
    project_context_error,
    project_current_slot_configuration,
)
from hwpxfiller.application.slot_reconciliation import (
    SLOT_REMOVED,
    derive_reconciliation_source_delta,
    resolve_slot_configuration,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.domain.slot_selection import (
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SelectionSemanticContractManifest,
    SlotSelection,
    SlotSelectionSet,
)

V1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
BAD_CONTRACT = SelectionSemanticContractManifest(
    "slot-selection/x", "s", "c", "MANY", ("MANY",), "v"
)


def _structure(*slots: TemplateSlot) -> TemplateStructure:
    return TemplateStructure(slots=slots)


def _slot(sid: str, opts: list[TemplateOption], shared: tuple[str, ...] = ()) -> TemplateSlot:
    return TemplateSlot(sid, shared_fields=shared, options=tuple(opts))


def _sel(*pairs: tuple[str, list[str]]) -> SlotSelectionSet:
    return SlotSelectionSet(tuple(SlotSelection(s, tuple(o)) for s, o in pairs))


def _ctx(structure: TemplateStructure) -> SlotConfigurationContext:
    return SlotConfigurationContext(
        workspace_instance_id="ws",
        work_id="w1",
        template_application_id="A1",
        template_lineage_id="L1",
        application_epoch=1,
        pass_evidence_id="E1",
        revision_id="R1",
        qualification_profile_id="P1",
        structure_projection_schema_version="hwpx-structure-projection-v1",
        template_structure=structure,
        template_structure_digest="sha256:d",
        selection_semantic_contract_id="slot-selection/v1",
        selection_semantic_contract=V1,
    )


def _project(structure, selections, contract=V1, source_delta=None):
    resolution = resolve_slot_configuration(selections, structure, contract)
    return project_current_slot_configuration(
        _ctx(structure), None, resolution, source_delta
    )


# ── configuration_status mapping table ────────────────────────────────────────
@pytest.mark.parametrize(
    "structure,selections,contract,expected",
    [
        # 0 slots → NOT_APPLICABLE.
        (_structure(), _sel(), V1, NOT_APPLICABLE),
        # missing required, 다른 broker 없음 → NEEDS_SELECTION.
        (_structure(_slot("s", [TemplateOption("A")])), _sel(), V1, NEEDS_SELECTION),
        # removed selected option → HAS_BROKEN_SELECTIONS.
        (
            _structure(_slot("s", [TemplateOption("A")])),
            _sel(("s", ["Z"])),
            V1,
            HAS_BROKEN_SELECTIONS,
        ),
        # cardinality violation → HAS_BROKEN_SELECTIONS.
        (
            _structure(_slot("s", [TemplateOption("A"), TemplateOption("B")])),
            _sel(("s", ["A", "B"])),
            V1,
            HAS_BROKEN_SELECTIONS,
        ),
        # no available options → HAS_BROKEN_SELECTIONS.
        (_structure(_slot("s", [])), _sel(), V1, HAS_BROKEN_SELECTIONS),
        # unsupported policy → HAS_BROKEN_SELECTIONS.
        (
            _structure(_slot("s", [TemplateOption("A")])),
            _sel(("s", ["A"])),
            BAD_CONTRACT,
            HAS_BROKEN_SELECTIONS,
        ),
        # 전부 resolved → SLOT_SELECTIONS_COMPLETE.
        (
            _structure(_slot("s", [TemplateOption("A")])),
            _sel(("s", ["A"])),
            V1,
            SLOT_SELECTIONS_COMPLETE,
        ),
    ],
)
def test_configuration_status_mapping(structure, selections, contract, expected) -> None:
    view = _project(structure, selections, contract)
    assert view.view_status == CURRENT
    assert view.configuration_status == expected


def test_missing_and_broken_distinct_when_both_present() -> None:
    # missing + cardinality 동시 → broken 이 우선해 HAS_BROKEN_SELECTIONS.
    structure = _structure(
        _slot("m", [TemplateOption("A")]),
        _slot("c", [TemplateOption("A"), TemplateOption("B")]),
    )
    view = _project(structure, _sel(("c", ["A", "B"])))
    assert view.configuration_status == HAS_BROKEN_SELECTIONS
    assert view.summary is not None
    assert view.summary.missing_selection_count == 1
    assert view.summary.broken_selection_count == 1
    assert set(view.summary.blocking_kinds) == {
        "MISSING_REQUIRED_SELECTION",
        "CARDINALITY_VIOLATION",
    }


# ── view_status: CURRENT vs CONTEXT_ERROR ─────────────────────────────────────
def test_context_error_has_no_normal_projection() -> None:
    view = project_context_error("STALE_TEMPLATE_APPLICATION")
    assert view.view_status == CONTEXT_ERROR
    assert view.context_error == "STALE_TEMPLATE_APPLICATION"
    assert view.summary is None
    assert view.slots == () and view.detached_selections == ()
    assert view.configuration_status == NOT_APPLICABLE  # partial fallback 없음


# ── mutation-outcome vs current-view 분리 ─────────────────────────────────────
def test_fresh_projection_carries_no_request_stale_axis() -> None:
    # current view 는 request stale 관계를 담지 않는다 — 별도 mutation outcome 축이 진다.
    view = _project(_structure(_slot("s", [TemplateOption("A")])), _sel(("s", ["A"])))
    assert view.view_status == CURRENT
    assert not hasattr(view, "request_relation")
    assert not hasattr(view, "stale")


# ── slots / options projection ────────────────────────────────────────────────
def test_slot_option_projection_selected_effective_and_fields() -> None:
    structure = _structure(
        _slot(
            "s1",
            [
                TemplateOption("o1", fields=("f1", "f2")),
                TemplateOption("o2", fields=("f3",)),
            ],
            shared=("sh1",),
        )
    )
    view = _project(structure, _sel(("s1", ["o1"])))
    (slot,) = view.slots
    assert slot.slot_id == "s1" and slot.display_text == "s1"  # exact ID
    assert slot.shared_field_ids == ("sh1",)
    assert slot.declared_option_ids == ("o1",)
    assert slot.effective_option_ids == ("o1",)
    o1, o2 = slot.options
    assert o1.option_id == "o1" and o1.display_text == "o1"  # exact ID
    assert o1.selected is True and o1.effective is True
    assert o1.structurally_associated_field_ids == ("f1", "f2")
    assert o2.selected is False and o2.effective is False


def test_slots_follow_template_order() -> None:
    structure = _structure(
        _slot("b", [TemplateOption("A")]),
        _slot("a", [TemplateOption("A")]),
    )
    view = _project(structure, _sel())
    assert [s.slot_id for s in view.slots] == ["b", "a"]


def test_declared_effective_separation_on_removed_option() -> None:
    # 선택했지만 available 밖 → declared 는 남고 effective 는 빈다.
    view = _project(_structure(_slot("s", [TemplateOption("A")])), _sel(("s", ["Z"])))
    (slot,) = view.slots
    assert slot.declared_option_ids == ("Z",)
    assert slot.effective_option_ids == ()
    assert any(d.kind == "SELECTED_OPTION_REMOVED" for d in slot.diagnostics)


# ── detached projection ───────────────────────────────────────────────────────
def test_detached_selection_informational_and_clearable() -> None:
    # slot Z 가 structure 에 없다 → detached, clearable, SLOT_REMOVED.
    structure = _structure(_slot("s", [TemplateOption("A")]))
    view = _project(structure, _sel(("s", ["A"]), ("Z", ["C"])))
    (detached,) = view.detached_selections
    assert detached.slot_id == "Z"
    assert detached.selected_option_ids == ("C",)
    assert detached.clearable is True
    assert detached.status == SLOT_REMOVED
    # informational index 에도 실린다.
    assert any(c.slot_id == "Z" and c.kind == SLOT_REMOVED for c in view.informational_changes)


def test_zero_slots_still_shows_detached_selection() -> None:
    # slot 0개인데 retained detached 가 있으면 표시(NOT_APPLICABLE 이어도).
    view = _project(_structure(), _sel(("Z", ["C"])))
    assert view.configuration_status == NOT_APPLICABLE
    assert len(view.detached_selections) == 1
    assert view.summary is not None and view.summary.detached_selection_count == 1


# ── summary counts / blocking_items ───────────────────────────────────────────
def test_summary_and_blocking_items() -> None:
    structure = _structure(
        _slot("m", [TemplateOption("A")]),
        _slot("s", [TemplateOption("A")]),
    )
    view = _project(structure, _sel(("s", ["A"]), ("Z", ["C"])))
    assert view.summary is not None
    assert view.summary.missing_selection_count == 1  # m
    assert view.summary.detached_selection_count == 1  # Z
    assert view.summary.slot_selections_complete is False
    assert any(b.slot_id == "m" for b in view.blocking_items)


# ── reconciliation delta: source-relative 만, immediate transition 아님 ──────────
def test_reconciliation_changes_present_only_with_delta() -> None:
    structure = _structure(_slot("s", [TemplateOption("A")]))
    assert _project(structure, _sel(("s", ["A"]))).reconciliation_changes is None

    source = _structure(_slot("old", [TemplateOption("X")]))
    delta = derive_reconciliation_source_delta(
        "A0", 2, _sel(("old", ["X"])), source, "A1", structure
    )
    view = _project(structure, _sel(("s", ["A"])), source_delta=delta)
    rc = view.reconciliation_changes
    assert rc is not None
    assert rc.source_application_id == "A0" and rc.source_configuration_version == 2
    assert rc.added_slot_ids == ("s",) and rc.removed_slot_ids == ("old",)
    # source-relative refs 만 — "이번 변경" immediate transition 필드는 없다.
    assert not hasattr(rc, "immediate") and not hasattr(rc, "applied_now")


# ── JSON-safety ───────────────────────────────────────────────────────────────
def test_dto_serializes_to_primitives() -> None:
    structure = _structure(
        _slot("s", [TemplateOption("A", fields=("f1",))], shared=("sh1",))
    )
    delta = derive_reconciliation_source_delta(
        "A0", 1, _sel(("s", ["A"])), structure, "A1", structure
    )
    view = _project(structure, _sel(("s", ["A"]), ("Z", ["C"])), source_delta=delta)
    # asdict → dict/list/str/int/bool 만; json.dumps 가 통과하면 primitive 로만 구성됨.
    payload = json.dumps(dataclasses.asdict(view))
    assert json.loads(payload)["view_status"] == CURRENT
    # context error variant 도 JSON-safe.
    json.dumps(dataclasses.asdict(project_context_error("BOOM")))
