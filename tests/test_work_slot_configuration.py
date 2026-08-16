"""S4-02(#672) Application-bound Working Configuration·version 의미·codec·tombstone."""

from __future__ import annotations

import pytest

from hwpxfiller.application.work_slot_configuration import (
    EMPTY,
    RECONCILED_FROM_PREDECESSOR,
    SCHEMA_VERSION,
    WorkSlotConfigurationAggregate,
    WorkSlotConfigurationDraft,
    WorkSlotConfigurationError,
    apply_selections,
    create_empty,
    create_reconciled,
    decode_aggregate,
    encode_aggregate,
)
from hwpxfiller.domain.slot_selection import (
    SlotSelection,
    SlotSelectionSet,
    declared_selection_digest,
)

NOW = "2026-08-16T00:00:00Z"


def _sel(pairs: list[tuple[str, list[str]]]) -> SlotSelectionSet:
    return SlotSelectionSet(tuple(SlotSelection(s, tuple(o)) for s, o in pairs))


def _reconciled(selections: SlotSelectionSet) -> WorkSlotConfigurationDraft:
    return create_reconciled(
        "w1", "A18", selections, "A17", 3, declared_selection_digest(selections), NOW
    )


# ── identity / version ────────────────────────────────────────────────────────
def test_empty_configuration_is_version_1_without_provenance() -> None:
    c = create_empty("w1", "A18", NOW)
    assert c.version == 1
    assert c.origin == EMPTY
    assert c.reconciled_from_application_id is None
    assert c.is_empty


def test_reconciled_configuration_version_1_with_full_provenance() -> None:
    c = _reconciled(_sel([("s", ["o"])]))
    assert c.version == 1
    assert c.origin == RECONCILED_FROM_PREDECESSOR
    assert c.reconciled_from_application_id == "A17"
    assert c.reconciled_from_version == 3


def test_reconciled_requires_all_provenance() -> None:
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationDraft(
            "w1", "A18", 1, _sel([("s", ["o"])]), RECONCILED_FROM_PREDECESSOR,
            "A17", None, "sha256:x", NOW, NOW,
        )


def test_empty_origin_forbids_provenance() -> None:
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationDraft(
            "w1", "A18", 1, SlotSelectionSet(()), EMPTY,
            "A17", 3, "sha256:x", NOW, NOW,
        )


def test_version_below_one_rejected() -> None:
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationDraft(
            "w1", "A18", 0, SlotSelectionSet(()), EMPTY, None, None, None, NOW, NOW
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"work_id": ""},  # empty id
        {"selections": object()},  # not a SlotSelectionSet
        {"origin": "MADE_UP"},  # unknown origin
    ],
)
def test_malformed_draft_rejected(kwargs: dict) -> None:
    base = dict(
        work_id="w1",
        base_template_application_id="A18",
        version=1,
        selections=SlotSelectionSet(()),
        origin=EMPTY,
        reconciled_from_application_id=None,
        reconciled_from_version=None,
        reconciled_from_declared_selection_digest=None,
        created_at=NOW,
        updated_at=NOW,
    )
    base.update(kwargs)
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationDraft(**base)


def test_reconciled_version_below_one_rejected() -> None:
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationDraft(
            "w1", "A18", 1, _sel([("s", ["o"])]), RECONCILED_FROM_PREDECESSOR,
            "A17", 0, "sha256:x", NOW, NOW,
        )


def test_empty_aggregate_helper() -> None:
    from hwpxfiller.application.work_slot_configuration import empty_aggregate

    agg = empty_aggregate("w1")
    assert agg.work_id == "w1"
    assert agg.configurations == ()


# ── version bump semantics ────────────────────────────────────────────────────
def test_semantic_noop_keeps_version_and_identity() -> None:
    c = _reconciled(_sel([("s", ["a", "b"])]))
    same = apply_selections(c, _sel([("s", ["b", "a"])]), "later")  # order-independent
    assert same is c  # unchanged draft returned


def test_actual_change_increments_version_and_stamps_updated_at() -> None:
    c = create_empty("w1", "A18", NOW)
    changed = apply_selections(c, _sel([("s", ["o"])]), "later")
    assert changed.version == 2
    assert changed.updated_at == "later"
    assert changed.created_at == NOW
    assert changed.origin == EMPTY  # 생성 이력 보존


def test_clearing_last_entry_keeps_configuration_and_bumps_version() -> None:
    c = _reconciled(_sel([("s", ["o"])]))
    cleared = apply_selections(c, SlotSelectionSet(()), "later")
    assert cleared.version == 2
    assert cleared.is_empty  # tombstone: 존재하되 비었다


# ── aggregate invariants ──────────────────────────────────────────────────────
def test_aggregate_rejects_duplicate_application() -> None:
    a = create_empty("w1", "A18", NOW)
    b = create_empty("w1", "A18", NOW)
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationAggregate(SCHEMA_VERSION, "w1", (a, b))


def test_aggregate_rejects_foreign_work_id() -> None:
    foreign = create_empty("w2", "A18", NOW)
    with pytest.raises(WorkSlotConfigurationError):
        WorkSlotConfigurationAggregate(SCHEMA_VERSION, "w1", (foreign,))


# ── codec ─────────────────────────────────────────────────────────────────────
def test_roundtrip_preserves_empty_tombstone_and_provenance() -> None:
    agg = WorkSlotConfigurationAggregate(
        SCHEMA_VERSION,
        "w1",
        (
            create_empty("w1", "A17", NOW),  # explicit-empty tombstone
            _reconciled(_sel([("s", ["o"])])),
        ),
    )
    restored = decode_aggregate(encode_aggregate(agg))
    assert restored == agg
    assert restored.configurations[0].is_empty


def test_decode_unknown_schema_fails_closed() -> None:
    with pytest.raises(WorkSlotConfigurationError):
        decode_aggregate({"schema_version": "nope", "work_id": "w1", "configurations": []})


def test_decode_detects_tampered_selection_digest() -> None:
    encoded = encode_aggregate(
        WorkSlotConfigurationAggregate("work-slot-configuration-v1", "w1", (_reconciled(_sel([("s", ["o"])])),))
    )
    encoded["configurations"][0]["declared_selection_digest"] = "sha256:tampered"
    with pytest.raises(WorkSlotConfigurationError):
        decode_aggregate(encoded)


def test_no_derived_status_fields_stored() -> None:
    encoded = _reconciled(_sel([("s", ["o"])]))
    from hwpxfiller.application.work_slot_configuration import _encode_config

    keys = set(_encode_config(encoded))
    forbidden = {"status", "complete", "broken", "missing", "available_options",
                 "structure", "policy", "effective_selections", "detached", "projection"}
    assert keys.isdisjoint(forbidden)
