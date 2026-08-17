"""S4-06(#676) pure resolver·successor reconciliation·retained intent·source delta."""

from __future__ import annotations

import pytest

from hwpxfiller.application.execution_structure import (
    ContentEntry,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
)
from hwpxfiller.application.selection_compatibility import (
    AUTO_KEEP,
    DETACHED,
    REVIEW_REQUIRED,
    ChainApplicationFacts,
)
from hwpxfiller.application.slot_reconciliation import (
    BLOCKED,
    COMPLETE,
    NOT_APPLICABLE,
    RESOLVED,
    SELECTED_OPTION_REMOVED,
    SLOT_REMOVED,
    UNSUPPORTED_SELECTION_POLICY,
    DetachedSelection,
    ReconciliationApplication,
    ReconciliationIntegrityError,
    derive_reconciliation_source_delta,
    find_nearest_predecessor_configuration,
    plan_successor_reconciliation,
    resolve_slot_configuration,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_slot_configuration import (
    EMPTY,
    RECONCILED_FROM_PREDECESSOR,
    WorkSlotConfigurationDraft,
)
from hwpxfiller.domain.slot_selection import (
    CARDINALITY_VIOLATION,
    MISSING_REQUIRED_SELECTION,
    NO_AVAILABLE_OPTIONS,
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SelectionSemanticContractManifest,
    SlotSelection,
    SlotSelectionSet,
    declared_selection_digest,
)

V1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
NOW = "2026-08-16T00:00:00Z"


def _structure(*slots: tuple[str, list[str]]) -> TemplateStructure:
    return TemplateStructure(
        slots=tuple(
            TemplateSlot(sid, options=tuple(TemplateOption(o) for o in opts))
            for sid, opts in slots
        )
    )


def _sel(*pairs: tuple[str, list[str]]) -> SlotSelectionSet:
    return SlotSelectionSet(tuple(SlotSelection(s, tuple(o)) for s, o in pairs))


def _status(res, slot_id: str) -> str:
    return next(sr.status for sr in res.slots if sr.slot_id == slot_id)


# ── resolver status matrix ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "available,declared,expected",
    [
        (["A", "B"], ["A"], RESOLVED),
        (["A", "B"], [], MISSING_REQUIRED_SELECTION),
        (["A", "B"], ["A", "B"], CARDINALITY_VIOLATION),
        ([], [], NO_AVAILABLE_OPTIONS),
        (["A"], ["Z"], SELECTED_OPTION_REMOVED),  # 선택했지만 available 밖
    ],
)
def test_per_slot_status(available, declared, expected) -> None:
    res = resolve_slot_configuration(
        _sel(("s", declared)) if declared else _sel(),
        _structure(("s", available)),
        V1,
    )
    assert _status(res, "s") == expected


def test_unsupported_policy_status() -> None:
    bad = SelectionSemanticContractManifest(
        "slot-selection/x", "s", "c", "MANY", ("MANY",), "v"
    )
    res = resolve_slot_configuration(_sel(("s", ["A"])), _structure(("s", ["A"])), bad)
    assert _status(res, "s") == UNSUPPORTED_SELECTION_POLICY


def test_multiple_diagnostics_on_cardinality() -> None:
    # selected=[A,B], available=[A] → primary CARDINALITY_VIOLATION + B removed diagnostic.
    res = resolve_slot_configuration(_sel(("s", ["A", "B"])), _structure(("s", ["A"])), V1)
    sr = res.slots[0]
    assert sr.status == CARDINALITY_VIOLATION
    assert [d.option_id for d in sr.diagnostics] == ["B"]


def test_effective_holds_only_resolved() -> None:
    res = resolve_slot_configuration(
        _sel(("ok", ["A"])),  # "bad" 는 declared entry 없음 → MISSING
        _structure(("ok", ["A", "B"]), ("bad", ["X"])),
        V1,
    )
    assert res.effective_selections == _sel(("ok", ["A"]))
    assert res.blocking_kinds == (MISSING_REQUIRED_SELECTION,)


def test_zero_slots_is_not_applicable_not_complete() -> None:
    res = resolve_slot_configuration(_sel(), _structure(), V1)
    assert res.applicable is False
    assert res.slot_selections_complete is False
    assert res.configuration_status == NOT_APPLICABLE


def test_all_resolved_is_complete() -> None:
    res = resolve_slot_configuration(_sel(("s", ["A"])), _structure(("s", ["A"])), V1)
    assert res.slot_selections_complete is True
    assert res.configuration_status == COMPLETE


def test_blocked_status_when_incomplete() -> None:
    res = resolve_slot_configuration(_sel(), _structure(("s", ["A"])), V1)
    assert res.configuration_status == BLOCKED


# ── retained intent lifecycle (resolver over structures) ──────────────────────
def test_removed_slot_is_detached_nonblocking() -> None:
    # Slot Z 선택이 있으나 structure 에 Z 없음 → detached, blocking 아님, effective 제외.
    res = resolve_slot_configuration(_sel(("Z", ["C"])), _structure(("s", ["A"])), V1)
    assert res.detached_selections == (DetachedSelection("Z", ("C",), SLOT_REMOVED),)
    assert res.blocking_diagnostics == (("s", MISSING_REQUIRED_SELECTION),)  # Z 는 blocking 아님


def test_reappearing_slot_option_auto_resolves() -> None:
    # 같은 declared entry 를 유지한 채 Z 가 다시 structure 에 나타나면 자동 RESOLVED.
    kept = _sel(("Z", ["C"]))
    gone = resolve_slot_configuration(kept, _structure(("s", ["A"])), V1)
    assert gone.detached_selections[0].slot_id == "Z"
    back = resolve_slot_configuration(kept, _structure(("Z", ["C", "D"])), V1)
    assert _status(back, "Z") == RESOLVED


def test_cleared_detached_reappears_missing() -> None:
    # clear = entry 제거. 그 뒤 Slot 이 돌아오면 복원되지 않고 MISSING.
    cleared = _sel()  # Z entry 를 지운 상태
    res = resolve_slot_configuration(cleared, _structure(("Z", ["C"])), V1)
    assert _status(res, "Z") == MISSING_REQUIRED_SELECTION


def test_removed_option_is_blocking_and_restores_on_reappear() -> None:
    declared = _sel(("s", ["C"]))
    removed = resolve_slot_configuration(declared, _structure(("s", ["A"])), V1)
    assert _status(removed, "s") == SELECTED_OPTION_REMOVED  # blocking, entry 보존
    restored = resolve_slot_configuration(declared, _structure(("s", ["A", "C"])), V1)
    assert _status(restored, "s") == RESOLVED


# ── nearest predecessor search ────────────────────────────────────────────────
def _app(app_id, prev, epoch, work="W", lineage="L") -> ReconciliationApplication:
    return ReconciliationApplication(app_id, prev, epoch, work, lineage)


def _draft(app_id, selections, version=1, work="W") -> WorkSlotConfigurationDraft:
    return WorkSlotConfigurationDraft(
        work_id=work, base_template_application_id=app_id, version=version,
        selections=selections, origin=EMPTY,
        reconciled_from_application_id=None, reconciled_from_version=None,
        reconciled_from_declared_selection_digest=None, created_at=NOW, updated_at=NOW,
    )


def test_nearest_source_skips_configless_application() -> None:
    apps = {
        "A18": _app("A18", "A17", 3),
        "A17": _app("A17", "A16", 2),  # config 없음
        "A16": _app("A16", None, 1),
    }
    configs = {"A16": _draft("A16", _sel(("s", ["A"])))}
    found = find_nearest_predecessor_configuration("A18", apps, configs)
    assert found is not None and found.base_template_application_id == "A16"


def test_nearest_empty_barrier_stops_search() -> None:
    apps = {
        "A18": _app("A18", "A16", 3),
        "A16": _app("A16", "A15", 2),
        "A15": _app("A15", None, 1),
    }
    configs = {
        "A16": _draft("A16", _sel()),  # empty tombstone — barrier
        "A15": _draft("A15", _sel(("s", ["OLD"]))),
    }
    found = find_nearest_predecessor_configuration("A18", apps, configs)
    assert found.base_template_application_id == "A16"  # A15 를 부활시키지 않는다


@pytest.mark.parametrize(
    "apps",
    [
        {"A2": ("A1", 2), "A1": ("A2", 1)},  # cycle
        {"A2": ("A9", 2)},  # dangling
        {"A2": ("A1", 1), "A1": (None, 2)},  # epoch 역행(prev epoch >= current)
    ],
)
def test_integrity_gates_fail_closed(apps) -> None:
    application_map = {
        aid: _app(aid, prev, epoch) for aid, (prev, epoch) in apps.items()
    }
    with pytest.raises(ReconciliationIntegrityError):
        find_nearest_predecessor_configuration("A2", application_map, {})


def test_missing_target_application_rejected() -> None:
    with pytest.raises(ReconciliationIntegrityError):
        find_nearest_predecessor_configuration("ghost", {}, {})


def test_epoch_skip_rejected() -> None:
    # epoch 3 → 1 직접(중간 epoch 2 를 건너뜀) → tombstone 우회 위험이라 거절.
    apps = {"A3": _app("A3", "A1", 3), "A1": _app("A1", None, 1)}
    with pytest.raises(ReconciliationIntegrityError):
        find_nearest_predecessor_configuration("A3", apps, {})


def test_corruption_past_nearest_config_still_fails_closed() -> None:
    # nearest(A2) 에 config 가 있어도 그 뒤 chain 의 dangling 을 신뢰하지 않는다.
    apps = {"A3": _app("A3", "A2", 3), "A2": _app("A2", "A_ghost", 2)}
    configs = {"A2": _draft("A2", _sel(("s", ["A"])))}
    with pytest.raises(ReconciliationIntegrityError):
        find_nearest_predecessor_configuration("A3", apps, configs)


def _reconciled(app_id, from_app, from_version, from_digest) -> WorkSlotConfigurationDraft:
    return WorkSlotConfigurationDraft(
        work_id="W", base_template_application_id=app_id, version=1,
        selections=_sel(("s", ["A"])), origin=RECONCILED_FROM_PREDECESSOR,
        reconciled_from_application_id=from_app, reconciled_from_version=from_version,
        reconciled_from_declared_selection_digest=from_digest,
        created_at=NOW, updated_at=NOW,
    )


def test_coherent_reconciled_provenance_accepted() -> None:
    # A2 가 A1 에서 reconciled 됐고 version·digest 가 A1 config 와 일치 → 통과.
    apps = {"A3": _app("A3", "A2", 3), "A2": _app("A2", "A1", 2), "A1": _app("A1", None, 1)}
    a1 = _draft("A1", _sel(("s", ["OLD"])))
    a2 = _reconciled("A2", "A1", a1.version, declared_selection_digest(a1.selections))
    found = find_nearest_predecessor_configuration("A3", apps, {"A1": a1, "A2": a2})
    assert found.base_template_application_id == "A2"


@pytest.mark.parametrize(
    "from_app,from_version,from_digest_ok",
    [
        ("A_missing", 1, True),  # dangling
        ("A1", 99, True),  # version 불일치
        ("A1", 1, False),  # digest 불일치
    ],
)
def test_stale_reconciled_provenance_rejected(from_app, from_version, from_digest_ok) -> None:
    apps = {"A3": _app("A3", "A2", 3), "A2": _app("A2", "A1", 2), "A1": _app("A1", None, 1)}
    a1 = _draft("A1", _sel(("s", ["OLD"])))
    digest = declared_selection_digest(a1.selections) if from_digest_ok else "sha256:x"
    a2 = _reconciled("A2", from_app, from_version, digest)
    with pytest.raises(ReconciliationIntegrityError):
        find_nearest_predecessor_configuration("A3", apps, {"A1": a1, "A2": a2})


def test_cross_work_chain_rejected() -> None:
    apps = {
        "A2": _app("A2", "A1", 2, work="W"),
        "A1": _app("A1", None, 1, work="OTHER"),
    }
    with pytest.raises(ReconciliationIntegrityError):
        find_nearest_predecessor_configuration("A2", apps, {})


# ── compatibility-gated reconciliation plan (SG-01 #733) ────────────────────────
_RF = {
    "remaining_target_resolvable_after_removal": True,
    "active_field_resolvable_after_removal": True,
    "field_write_preserves_identity": True,
}
_ENTRY = ContentEntry(
    "c0",
    "section-body/v1",
    {
        "retains_admissible_envelope": True,
        "handles_empty_edges": True,
        "preserves_owner_marker": True,
        "coincident_boundary_admissible": True,
    },
)


def _exec(slot="s", options=("A",), *, removal="remove-option/v1"):
    """slot 하나 + option region(들)만 있는 최소 v2 execution structure(field 없음)."""
    product = TemplateStructure(
        root_fields=(),
        slots=(
            TemplateSlot(slot, shared_fields=(), options=tuple(TemplateOption(o) for o in options)),
        ),
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(SlotRegionObservation(slot, "c0", 10, 40),),
        option_regions=tuple(
            OptionRegionObservation(slot, o, "c0", 12 + 3 * i, 14 + 3 * i, removal)
            for i, o in enumerate(options)
        ),
        content_entries=(_ENTRY,),
        resolver_stability_facts=_RF,
        admitted_relation_profile="unadmitted",
    )


def _exec_slotless():
    return build_execution_structure(
        product_structure=TemplateStructure(root_fields=(), slots=()),
        occurrences=(),
        slot_regions=(),
        option_regions=(),
        content_entries=(),
        resolver_stability_facts=_RF,
        admitted_relation_profile="unadmitted",
    )


def _cf(structure, digest="sha256:same") -> ChainApplicationFacts:
    return ChainApplicationFacts(structure, "slot-selection/v1", "EXACTLY_ONE", digest)


def test_same_lineage_auto_keeps_compatible_different_lineage_empty() -> None:
    apps = {
        "A18": _app("A18", "A17", 2, lineage="L"),
        "A17": _app("A17", None, 1, lineage="L"),
    }
    configs = {"A17": _draft("A17", _sel(("s", ["A"])))}
    facts = {"A17": _cf(_exec()), "A18": _cf(_exec())}  # 동일 의미 → AUTO_KEEP
    plan = plan_successor_reconciliation(
        "A18", _structure(("s", ["A"])), V1, apps, configs, chain_facts=facts
    )
    assert plan.initial_selections == _sel(("s", ["A"]))
    assert plan.source_application_id == "A17"
    assert plan.compatibility_facts[0].classification == AUTO_KEEP

    apps["A18"] = _app("A18", "A17", 2, lineage="OTHER")
    plan2 = plan_successor_reconciliation(
        "A18", _structure(("s", ["A"])), V1, apps, configs, chain_facts=facts
    )
    assert plan2.initial_selections == _sel()  # 다른 Lineage → empty
    assert plan2.compatibility_facts == ()


def test_same_lineage_incompatible_drops_to_review() -> None:
    # 같은 id 이지만 target 의 option 의미가 바뀜(removal contract) → 자동 승계 0, REVIEW.
    apps = {"A18": _app("A18", "A17", 2), "A17": _app("A17", None, 1)}
    configs = {"A17": _draft("A17", _sel(("s", ["A"])))}
    facts = {
        "A17": _cf(_exec(removal="remove-option/v1")),
        "A18": _cf(_exec(removal="remove-option/v2")),
    }
    plan = plan_successor_reconciliation(
        "A18", _structure(("s", ["A"])), V1, apps, configs, chain_facts=facts
    )
    assert plan.initial_selections == _sel()  # AUTO_KEEP 0
    assert plan.compatibility_facts[0].classification == REVIEW_REQUIRED


def test_same_lineage_content_change_drops_to_review() -> None:
    # 구조는 동일한데 applied content digest 가 다름 → 본문 변경 가능 → 자동 승계 0.
    apps = {"A18": _app("A18", "A17", 2), "A17": _app("A17", None, 1)}
    configs = {"A17": _draft("A17", _sel(("s", ["A"])))}
    facts = {"A17": _cf(_exec(), "sha256:src"), "A18": _cf(_exec(), "sha256:tgt")}
    plan = plan_successor_reconciliation(
        "A18", _structure(("s", ["A"])), V1, apps, configs, chain_facts=facts
    )
    assert plan.initial_selections == _sel()
    assert plan.compatibility_facts[0].classification == REVIEW_REQUIRED


def test_same_lineage_without_chain_facts_fails_closed() -> None:
    # chain_facts 미제공 = evidence-missing → fail-closed(아무것도 승계 안 함).
    apps = {"A18": _app("A18", "A17", 2), "A17": _app("A17", None, 1)}
    configs = {"A17": _draft("A17", _sel(("s", ["A"])))}
    plan = plan_successor_reconciliation("A18", _structure(("s", ["A"])), V1, apps, configs)
    assert plan.initial_selections == _sel()
    assert plan.compatibility_facts[0].classification == REVIEW_REQUIRED


def test_slotless_target_retained_source_detached_not_carried() -> None:
    # slotless target 에 예전 선택 slot 이 없으면 DETACHED — successor 로 자동 복원하지 않는다.
    apps = {"A18": _app("A18", "A17", 2), "A17": _app("A17", None, 1)}
    configs = {"A17": _draft("A17", _sel(("gone", ["C"])))}
    facts = {"A17": _cf(_exec_slotless()), "A18": _cf(_exec_slotless())}
    plan = plan_successor_reconciliation(
        "A18", _structure(), V1, apps, configs, chain_facts=facts
    )
    assert plan.initial_selections == _sel()
    assert plan.should_create_configuration is False  # 승계할 게 없어 생성 생략
    assert plan.compatibility_facts[0].classification == DETACHED
    assert plan.compatibility_facts[0].slot_id == "gone"


def test_slotless_target_without_source_skips_creation() -> None:
    apps = {"A18": _app("A18", None, 1)}
    plan = plan_successor_reconciliation("A18", _structure(), V1, apps, {})
    assert plan.should_create_configuration is False
    assert plan.resolution.configuration_status == NOT_APPLICABLE


# ── source delta ──────────────────────────────────────────────────────────────
def test_source_delta_added_removed_preserved() -> None:
    delta = derive_reconciliation_source_delta(
        "A17", 4, _sel(("keep", ["A"]), ("drop", ["X"])),
        _structure(("keep", ["A", "B"]), ("drop", ["X"])),
        "A18", _structure(("keep", ["A", "B"]), ("new", ["N"])),
    )
    assert delta.added_slot_ids == ("new",)
    assert delta.removed_slot_ids == ("drop",)
    assert delta.preserved_selection_refs == (("keep", "A"),)
    assert delta.removed_selected_option_refs == (("drop", "X"),)
    assert delta.source_configuration_version == 4


def test_source_delta_option_order_change() -> None:
    delta = derive_reconciliation_source_delta(
        "A17", 1, _sel(), _structure(("s", ["A", "B"])),
        "A18", _structure(("s", ["B", "A"])),
    )
    assert delta.option_order_changes == ("s",)
    assert delta.added_option_refs == () and delta.removed_option_refs == ()
