"""SG-01(#733) selection compatibility — AUTO_KEEP/REVIEW_REQUIRED/DETACHED 판정.

fixture 는 hand-authored native-free 관찰값에서 exact v2 execution structure 를 조립한다
(실 HWPX parse 없음). A1~A8 음성/양성 + fingerprint 안정성(무관한 Slot 변경 불변)을 소유한다.
A9(user reselect)는 command flow 소유라 test_slot_command.py 에 산다.
"""

from __future__ import annotations

from hwpxfiller.application.execution_structure import (
    ContentEntry,
    FieldOccurrence,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
)
from hwpxfiller.application.selection_compatibility import (
    AUTO_KEEP,
    DETACHED,
    DETACHED_ABSENT,
    EVIDENCE_MISSING,
    FINGERPRINT_CHANGED,
    POLICY_CHANGED,
    PRESENT_MATCH,
    REMOVED_IN_CHAIN,
    REVIEW_REQUIRED,
    classify_selection,
    option_compatibility_fingerprint,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)

RESOLVER_FACTS = {
    "remaining_target_resolvable_after_removal": True,
    "active_field_resolvable_after_removal": True,
    "field_write_preserves_identity": True,
}
V1 = "slot-selection/v1"
EXACTLY_ONE = "EXACTLY_ONE"


def _entry(envelope: str = "section-body/v1") -> ContentEntry:
    return ContentEntry(
        "c0",
        envelope,
        {
            "retains_admissible_envelope": True,
            "handles_empty_edges": True,
            "preserves_owner_marker": True,
            "coincident_boundary_admissible": True,
        },
    )


def make_structure(slots, *, envelope: str = "section-body/v1"):
    """slots: [(slot_id, (b,e), [(option_id, fields, (b,e), removal_ref)])] → v2 structure."""
    product_slots = []
    occs = []
    slot_obs = []
    opt_obs = []
    for slot_id, slot_span, options in slots:
        product_slots.append(
            TemplateSlot(
                id=slot_id,
                shared_fields=(),
                options=tuple(TemplateOption(oid, fields) for oid, fields, _s, _r in options),
            )
        )
        slot_obs.append(SlotRegionObservation(slot_id, "c0", slot_span[0], slot_span[1]))
        for oid, fields, ospan, removal in options:
            opt_obs.append(OptionRegionObservation(slot_id, oid, "c0", ospan[0], ospan[1], removal))
            for i, fid in enumerate(fields):
                occs.append(
                    FieldOccurrence(
                        field_id=fid,
                        occurrence_ordinal=0,
                        owner_kind="OPTION",
                        owner_slot_id=slot_id,
                        owner_option_id=oid,
                        content_entry_id="c0",
                        structural_order=ospan[0] + 1 + i,
                        native_value_target_class="hwpx-field-value/v1",
                        resolver_contract_id="hwpx-field-resolver/v1",
                    )
                )
    return build_execution_structure(
        product_structure=TemplateStructure(root_fields=(), slots=tuple(product_slots)),
        occurrences=tuple(occs),
        slot_regions=tuple(slot_obs),
        option_regions=tuple(opt_obs),
        content_entries=(_entry(envelope),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _one(fields=("f1",), *, ospan=(15, 20), removal="remove-option/v1", envelope="section-body/v1"):
    return make_structure(
        [("s1", (10, 25), [("o1", fields, ospan, removal)])], envelope=envelope
    )


def _classify(
    chain,
    *,
    slot="s1",
    option="o1",
    source_cid=V1,
    target_cid=V1,
    source_pol=EXACTLY_ONE,
    target_pol=EXACTLY_ONE,
):
    return classify_selection(
        slot, option, chain,
        source_contract_id=source_cid, target_contract_id=target_cid,
        source_policy=source_pol, target_policy=target_pol,
    )


# ── A1: same id + same semantics → AUTO_KEEP ────────────────────────────────────
def test_a1_same_semantics_auto_keep() -> None:
    s = _one()
    fact = _classify([_one(), s])
    assert fact.classification == AUTO_KEEP
    assert fact.reason == PRESENT_MATCH
    assert fact.source_fingerprint == fact.target_fingerprint is not None


# ── A2: same id + option content(envelope) 변경 → REVIEW ─────────────────────────
def test_a2_content_change_review() -> None:
    fact = _classify([_one(envelope="section-body/v1"), _one(envelope="section-body/v2")])
    assert fact.classification == REVIEW_REQUIRED
    assert fact.reason == FINGERPRINT_CHANGED
    assert fact.source_fingerprint != fact.target_fingerprint


# ── A3: same id + Option-owned Field 추가/삭제 → REVIEW ──────────────────────────
def test_a3_owned_field_added_review() -> None:
    fact = _classify([_one(fields=("f1",)), _one(fields=("f1", "f2"))])
    assert fact.classification == REVIEW_REQUIRED
    assert fact.reason == FINGERPRINT_CHANGED


# ── A4: same id + selection policy/contract 변경 → REVIEW ────────────────────────
def test_a4_contract_change_review() -> None:
    fact = _classify([_one(), _one()], source_cid=V1, target_cid="slot-selection/v2")
    assert fact.classification == REVIEW_REQUIRED and fact.reason == POLICY_CHANGED


def test_a4_policy_change_review() -> None:
    fact = _classify([_one(), _one()], source_pol=EXACTLY_ONE, target_pol="AT_MOST_ONE")
    assert fact.classification == REVIEW_REQUIRED and fact.reason == POLICY_CHANGED


# ── A5: removed Slot/Option → DETACHED ──────────────────────────────────────────
def test_a5_removed_option_detached() -> None:
    target = make_structure([("s1", (10, 25), [("o2", (), (15, 20), "remove-option/v1")])])
    fact = _classify([_one(), target])
    assert fact.classification == DETACHED and fact.reason == DETACHED_ABSENT


# ── A6: removed 뒤 same id 재등장 → REVIEW(자동 복원 0) ──────────────────────────
def test_a6_reappear_after_removal_review() -> None:
    # source==target(같은 의미)이지만 중간 hop 에서 o1 이 사라졌다 재등장 → REMOVED_IN_CHAIN.
    mid = make_structure([("s1", (10, 25), [("oz", (), (15, 20), "remove-option/v1")])])
    fact = _classify([_one(), mid, _one()])
    assert fact.classification == REVIEW_REQUIRED
    assert fact.reason == REMOVED_IN_CHAIN


# ── A7: different id + same-looking content → 자동 migration 0 ───────────────────
def test_a7_different_id_no_migration() -> None:
    # target 에 같은 내용의 다른 id(o1_new). 옛 o1 은 target 에 없으므로 DETACHED(승계 아님).
    target = make_structure(
        [("s1", (10, 25), [("o1_new", ("f1",), (15, 20), "remove-option/v1")])]
    )
    fact = _classify([_one(), target])
    assert fact.classification == DETACHED


# ── A8: evidence/contract unknown → AUTO_KEEP 0 ─────────────────────────────────
def test_a8_target_missing_review_never_auto_keep() -> None:
    fact = _classify([_one(), None])
    assert fact.classification == REVIEW_REQUIRED and fact.reason == EVIDENCE_MISSING


def test_a8_empty_chain_review() -> None:
    fact = _classify([])
    assert fact.classification == REVIEW_REQUIRED and fact.reason == EVIDENCE_MISSING


def test_a8_missing_hop_review_never_auto_keep() -> None:
    # source 부재(v1/missing)여도 target present — 절대 AUTO_KEEP 아님.
    fact = _classify([None, _one()])
    assert fact.classification == REVIEW_REQUIRED and fact.reason == EVIDENCE_MISSING


# ── fingerprint 안정성: 무관한 Slot 변경·절대 위치 이동에 불변 ──────────────────
def test_fingerprint_stable_across_unrelated_slot_and_shift() -> None:
    a = make_structure(
        [
            ("s1", (10, 25), [("o1", ("f1",), (15, 20), "remove-option/v1")]),
            ("s2", (30, 50), [("x", ("g1",), (35, 40), "remove-option/v1")]),
        ]
    )
    # s2 를 앞으로, s1 을 뒤로 밀어 절대 order 가 전부 바뀌지만 s1/o1 의 intrinsic 은 동일.
    b = make_structure(
        [
            ("s1", (40, 55), [("o1", ("f1",), (45, 50), "remove-option/v1")]),
            ("s2", (10, 35), [("x", ("g1",), (15, 20), "remove-option/v1")]),
        ]
    )
    assert option_compatibility_fingerprint(a, "s1", "o1") == option_compatibility_fingerprint(
        b, "s1", "o1"
    )


def test_fingerprint_none_when_option_absent() -> None:
    target = make_structure([("s1", (10, 25), [("o2", (), (15, 20), "remove-option/v1")])])
    assert option_compatibility_fingerprint(target, "s1", "o1") is None


def test_removal_contract_change_review() -> None:
    fact = _classify([_one(removal="remove-option/v1"), _one(removal="remove-option/v2")])
    assert fact.classification == REVIEW_REQUIRED and fact.reason == FINGERPRINT_CHANGED
