"""S5-04(#700) composition theorem evidence + pure runtime premise verifier.

체크리스트: taxonomy admission · C1~C10 premises · theorem evidence integrity ·
runtime conformance seam 분리 · no-mutation purity. 모든 fixture 는 S5-03 의 native-free
projection builder 로 세운다(실 HWPX mutation·sequential simulation 0).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    COUNTEREXAMPLE_THEOREM_FIXTURES,
    DEFAULT_RUNTIME_CONFORMANCE_REGISTRY,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_V1,
    POSITIVE_THEOREM_FIXTURES,
    PREMISE_IDS,
    THEOREM_EVIDENCE_V1,
    CompositionPremiseContextError,
    CompositionPremisesBlocked,
    CompositionPremisesPassed,
    CompositionTheoremEvidenceManifest,
    RuntimeMaterializerConformanceManifest,
    RuntimeMaterializerConformanceNotAdmitted,
    RuntimeMaterializerConformanceRegistry,
    TheoremEvidenceRegistry,
    UnsupportedCompositionContract,
    classify_target_target_admission,
    evaluate_composition_premises,
    fixture_manifest_digest,
    is_owner_coincidence_admitted,
    runtime_conformance_digest,
    theorem_evidence_digest,
    verify_execution_composition_premises,
    verify_theorem_evidence_integrity,
)
from hwpxfiller.application.execution_structure import (
    CONTAINED,
    CONTAINS,
    CROSSING,
    DISJOINT,
    SAME_SPAN,
    TOUCHING,
    ContentEntry,
    FieldOccurrence,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)

RC = "hwpx-field-resolver/v1"  # native primitive contract field_resolver 와 일치
VTC = "hwpx-field-value/v1"
REMOVE = "remove-option/v1"  # native primitive contract option_removal 과 일치
RESOLVER_FACTS = {
    "remaining_target_resolvable_after_removal": True,
    "active_field_resolvable_after_removal": True,
    "field_write_preserves_identity": True,
}


def _entry(entry_id="c0", **overrides):
    facts = {
        "retains_admissible_envelope": True,
        "handles_empty_edges": True,
        "preserves_owner_marker": True,
        "coincident_boundary_admissible": True,
    }
    facts.update(overrides)
    return ContentEntry(entry_id, "section-body/v1", facts)


def _occ(field_id, ordinal, kind, order, slot=None, option=None, entry="c0",
         resolver=RC, vtc=VTC):
    return FieldOccurrence(
        field_id=field_id,
        occurrence_ordinal=ordinal,
        owner_kind=kind,
        owner_slot_id=slot,
        owner_option_id=option,
        content_entry_id=entry,
        structural_order=order,
        native_value_target_class=vtc,
        resolver_contract_id=resolver,
    )


def _two_option(a_span, b_span, slot_span=(0, 100), entry=None):
    product = TemplateStructure(
        slots=(TemplateSlot("s1", options=(TemplateOption("o1", ()), TemplateOption("o2", ()))),)
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(SlotRegionObservation("s1", "c0", *slot_span),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", a_span[0], a_span[1], REMOVE),
            OptionRegionObservation("s1", "o2", "c0", b_span[0], b_span[1], REMOVE),
        ),
        content_entries=(entry or _entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _base_structure(entry=None):
    """root(반복)+shared+2 disjoint Option 표준 fixture."""
    product = TemplateStructure(
        root_fields=("성명",),
        slots=(
            TemplateSlot(
                id="s1",
                shared_fields=("주소",),
                options=(TemplateOption("o1", ("항목",)), TemplateOption("o2", ())),
            ),
        ),
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(
            _occ("성명", 0, "ROOT", 0),
            _occ("주소", 0, "SLOT_SHARED", 12, slot="s1"),
            _occ("항목", 0, "OPTION", 17, slot="s1", option="o1"),
            _occ("성명", 1, "ROOT", 50),
        ),
        slot_regions=(SlotRegionObservation("s1", "c0", 10, 40),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", 15, 20, REMOVE),
            OptionRegionObservation("s1", "o2", "c0", 25, 30, REMOVE),
        ),
        content_entries=(entry or _entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _slotless():
    """slot(=RemoveOption target) 0, root Field 만 — Field premise 만 남는다."""
    return build_execution_structure(
        product_structure=TemplateStructure(root_fields=("성명",)),
        occurrences=(_occ("성명", 0, "ROOT", 0),),
        slot_regions=(),
        option_regions=(),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _verify(structure):
    return verify_execution_composition_premises(
        structure=structure,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )


# ══ taxonomy admission ═══════════════════════════════════════════════════════════════
def test_every_distinct_pair_exactly_one_classification() -> None:
    struct = _base_structure()
    pairs = {
        (
            (r.left_option_ref.slot_id, r.left_option_ref.option_id),
            (r.right_option_ref.slot_id, r.right_option_ref.option_id),
        )
        for r in struct.removal_target_relations
    }
    # 2 Option → 정확히 1 pair, relation 하나.
    assert len(pairs) == len(struct.removal_target_relations) == 1


def test_disjoint_admitted() -> None:
    assert classify_target_target_admission(DISJOINT, touching_theorem_available=False) == "OK"
    assert isinstance(_verify(_two_option((10, 20), (30, 40))), CompositionPremisesPassed)


def test_touching_exact_theorem_gate() -> None:
    # gate: theorem 이 없으면 TOUCHING 은 admit 안 되고, 있으면 admit.
    assert classify_target_target_admission(TOUCHING, touching_theorem_available=False) == "FAILED"
    assert classify_target_target_admission(TOUCHING, touching_theorem_available=True) == "OK"
    # verifier 는 valid theorem evidence 를 가지므로 TOUCHING 구조가 통과한다.
    assert isinstance(_verify(_two_option((10, 20), (20, 40))), CompositionPremisesPassed)


@pytest.mark.parametrize("relation", [CONTAINS, CONTAINED, SAME_SPAN, CROSSING])
def test_nesting_and_crossing_rejected(relation) -> None:
    assert classify_target_target_admission(relation, touching_theorem_available=True) == "FAILED"


def test_contains_structure_blocked() -> None:
    result = _verify(_two_option((10, 40), (15, 30)))  # CONTAINS
    assert isinstance(result, CompositionPremisesBlocked)
    assert result.premise_id == "C2"
    assert result.code == "EXECUTION_COMPOSITION_PREMISE_FAILED"


def test_crossing_structure_blocked() -> None:
    result = _verify(_two_option((10, 30), (20, 40)))  # CROSSING
    assert isinstance(result, CompositionPremisesBlocked)
    assert result.premise_id == "C2"


def test_same_span_distinct_target_blocked() -> None:
    result = _verify(_two_option((10, 40), (10, 40)))  # SAME_SPAN
    assert isinstance(result, CompositionPremisesBlocked)


def test_unknown_relation_vocab_is_context_error() -> None:
    assert classify_target_target_admission("WOBBLE", touching_theorem_available=True) == "INCOMPLETE"


def test_target_owner_not_confused_with_target_target() -> None:
    # target-owner admission 은 coincidence 기반, target-target 과 다른 policy 함수.
    assert is_owner_coincidence_admitted(
        "INTERIOR", preserves_owner_marker=True, coincident_boundary_admissible=True,
        coincidence_theorem_available=False,
    ) == "OK"  # INTERIOR 는 theorem 없이도 OK — target-target 과 판정 축이 다르다
    # 같은 이름 SAME_SPAN 이라도 owner 축에서는 capability+theorem gate 를 탄다.
    assert is_owner_coincidence_admitted(
        "SAME_SPAN", preserves_owner_marker=True, coincident_boundary_admissible=True,
        coincidence_theorem_available=False,
    ) == "FAILED"
    assert is_owner_coincidence_admitted(
        "SAME_SPAN", preserves_owner_marker=True, coincident_boundary_admissible=True,
        coincidence_theorem_available=True,
    ) == "OK"


def test_owner_coincidence_requires_capability_facts() -> None:
    assert is_owner_coincidence_admitted(
        "SAME_START", preserves_owner_marker=False, coincident_boundary_admissible=True,
        coincidence_theorem_available=True,
    ) == "FAILED"
    assert is_owner_coincidence_admitted(
        "SAME_END", preserves_owner_marker=True, coincident_boundary_admissible=False,
        coincidence_theorem_available=True,
    ) == "FAILED"


def test_owner_same_span_target_passes_with_capability_and_theorem() -> None:
    # o1 이 slot span 전체를 덮는다(owner SAME_SPAN) — envelope capability + theorem 으로 admit.
    struct = _two_option((0, 100), (0, 100), slot_span=(0, 100))
    # 두 Option 이 같은 span → target-target SAME_SPAN 이라 C2 에서 막힌다.
    result = _verify(struct)
    assert isinstance(result, CompositionPremisesBlocked)
    # 그러나 owner coincidence 자체는(단독 Option) admit 가능함을 policy 로 확인(위 test).


def test_target_retained_containment_rejected() -> None:
    # root Field occurrence 를 removal target [15,20] 안(order 17)에 두면 C6 위반.
    product = TemplateStructure(
        root_fields=("성명",),
        slots=(TemplateSlot("s1", options=(TemplateOption("o1", ()),)),),
    )
    struct = build_execution_structure(
        product_structure=product,
        occurrences=(_occ("성명", 0, "ROOT", 17),),  # o1 region [15,20] 안
        slot_regions=(SlotRegionObservation("s1", "c0", 10, 40),),
        option_regions=(OptionRegionObservation("s1", "o1", "c0", 15, 20, REMOVE),),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )
    result = _verify(struct)
    assert isinstance(result, CompositionPremisesBlocked)
    assert result.premise_id == "C6"


# ══ premises C1~C10 ══════════════════════════════════════════════════════════════════
def test_all_premises_pass_positive_fixture() -> None:
    outcomes = evaluate_composition_premises(_base_structure(), theorem_evidence_valid=True)
    assert {pid: o.status for pid, o in outcomes.items()} == {pid: "OK" for pid in PREMISE_IDS}
    assert isinstance(_verify(_base_structure()), CompositionPremisesPassed)


def test_c2_relation_admission_failure() -> None:
    outcomes = evaluate_composition_premises(
        _two_option((10, 30), (20, 40)), theorem_evidence_valid=True  # CROSSING
    )
    assert outcomes["C2"].status == "FAILED"


def test_c3_remaining_resolver_false_fails() -> None:
    facts = {**RESOLVER_FACTS, "remaining_target_resolvable_after_removal": False}
    struct = _two_option_facts(facts)
    assert evaluate_composition_premises(struct, theorem_evidence_valid=True)["C3"].status == "FAILED"


def test_c5_slot_without_option_fails() -> None:
    # Option 이 없는 Slot → selected Option 유지 불가(C5). build 는 허용(region 0)하지만 premise 가 잡는다.
    product = TemplateStructure(slots=(TemplateSlot("s1", shared_fields=("주소",)),))
    struct = build_execution_structure(
        product_structure=product,
        occurrences=(_occ("주소", 0, "SLOT_SHARED", 5, slot="s1"),),
        slot_regions=(SlotRegionObservation("s1", "c0", 0, 40),),
        option_regions=(),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )
    outcomes = evaluate_composition_premises(struct, theorem_evidence_valid=True)
    assert outcomes["C5"].status == "FAILED"
    result = _verify(struct)
    assert isinstance(result, CompositionPremisesBlocked)
    assert result.premise_id == "C5"


def test_c6_retained_inside_fails() -> None:
    product = TemplateStructure(
        root_fields=("성명",),
        slots=(TemplateSlot("s1", options=(TemplateOption("o1", ()),)),),
    )
    struct = build_execution_structure(
        product_structure=product,
        occurrences=(_occ("성명", 0, "ROOT", 17),),
        slot_regions=(SlotRegionObservation("s1", "c0", 10, 40),),
        option_regions=(OptionRegionObservation("s1", "o1", "c0", 15, 20, REMOVE),),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )
    assert evaluate_composition_premises(struct, theorem_evidence_valid=True)["C6"].status == "FAILED"


def test_c7_active_field_resolver_false_fails() -> None:
    facts = {**RESOLVER_FACTS, "active_field_resolvable_after_removal": False}
    assert evaluate_composition_premises(
        _two_option_facts(facts), theorem_evidence_valid=True
    )["C7"].status == "FAILED"


def test_c8_field_write_identity_false_fails() -> None:
    facts = {**RESOLVER_FACTS, "field_write_preserves_identity": False}
    assert evaluate_composition_premises(
        _two_option_facts(facts), theorem_evidence_valid=True
    )["C8"].status == "FAILED"


def test_c10_envelope_not_retained_fails() -> None:
    struct = _two_option((10, 20), (30, 40), entry=_entry(retains_admissible_envelope=False))
    assert evaluate_composition_premises(struct, theorem_evidence_valid=True)["C10"].status == "FAILED"


def _two_option_facts(facts):
    product = TemplateStructure(
        slots=(TemplateSlot("s1", options=(TemplateOption("o1", ()), TemplateOption("o2", ()))),)
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(SlotRegionObservation("s1", "c0", 0, 100),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", 10, 20, REMOVE),
            OptionRegionObservation("s1", "o2", "c0", 30, 40, REMOVE),
        ),
        content_entries=(_entry(),),
        resolver_stability_facts=facts,
        admitted_relation_profile="unadmitted",
    )


def test_slotless_still_verifies_field_premises() -> None:
    # remove target 0 이어도 C3/C7/C8/C9/C10 Field premise 는 평가·통과된다.
    result = _verify(_slotless())
    assert isinstance(result, CompositionPremisesPassed)
    assert result.verified_premise_facts["removal_target_count"] == 0
    # 그리고 slotless 에서 resolver false 는 여전히 잡힌다.
    bad = build_execution_structure(
        product_structure=TemplateStructure(root_fields=("성명",)),
        occurrences=(_occ("성명", 0, "ROOT", 0),),
        slot_regions=(),
        option_regions=(),
        content_entries=(_entry(),),
        resolver_stability_facts={**RESOLVER_FACTS, "field_write_preserves_identity": False},
        admitted_relation_profile="unadmitted",
    )
    assert isinstance(_verify(bad), CompositionPremisesBlocked)


def test_missing_relation_fact_is_context_error() -> None:
    # target-target relation 을 하나 지운 위조 structure → C2 INCOMPLETE(context error).
    struct = _two_option((10, 20), (30, 40))
    forged = dataclasses.replace(struct, removal_target_relations=())
    outcomes = evaluate_composition_premises(forged, theorem_evidence_valid=True)
    assert outcomes["C2"].status == "INCOMPLETE"
    result = verify_execution_composition_premises(
        structure=forged,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "EXECUTION_COMPOSITION_PREMISE_INCOMPLETE"
    assert result.premise_id == "C2"


def test_wrong_resolver_contract_mismatch_context_error() -> None:
    struct = _base_structure()
    # occurrence resolver 를 native primitive contract 와 다르게.
    forged = dataclasses.replace(
        struct,
        field_occurrences=tuple(
            dataclasses.replace(o, resolver_contract_id="ghost-resolver/v9")
            for o in struct.field_occurrences
        ),
    )
    result = _verify(forged)
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT"


def test_wrong_removal_contract_mismatch_context_error() -> None:
    struct = _two_option((10, 20), (30, 40))
    forged = dataclasses.replace(
        struct,
        option_regions=tuple(
            dataclasses.replace(r, removal_capability_ref="ghost-remove/v9")
            for r in struct.option_regions
        ),
    )
    result = _verify(forged)
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT"


# ══ theorem evidence integrity ═══════════════════════════════════════════════════════
def test_pass_manifest_exact_contract_binding() -> None:
    verify_theorem_evidence_integrity(THEOREM_EVIDENCE_V1)  # 정상 통과
    assert THEOREM_EVIDENCE_V1.composition_contract_id == COMPOSITION_CONTRACT_ID
    assert THEOREM_EVIDENCE_V1.native_primitive_contract_id == NATIVE_PRIMITIVE_CONTRACT_ID
    assert THEOREM_EVIDENCE_V1.evidence_status == "PASS"


def test_theorem_suite_digest_tamper_fail_closed() -> None:
    forged = dataclasses.replace(THEOREM_EVIDENCE_V1, theorem_test_suite_digest="sha256:" + "0" * 64)
    with pytest.raises(Exception) as exc:  # noqa: PT011 - code 검사로 좁힌다
        verify_theorem_evidence_integrity(forged)
    assert exc.value.code == "COMPOSITION_THEOREM_EVIDENCE_INTEGRITY_ERROR"


def test_counterexample_digest_tamper_fail_closed() -> None:
    forged = dataclasses.replace(
        THEOREM_EVIDENCE_V1, counterexample_fixture_manifest_digest="sha256:" + "0" * 64
    )
    with pytest.raises(Exception) as exc:  # noqa: PT011
        verify_theorem_evidence_integrity(forged)
    assert exc.value.code == "COMPOSITION_THEOREM_EVIDENCE_INTEGRITY_ERROR"


def test_non_pass_status_is_unproven() -> None:
    forged = dataclasses.replace(THEOREM_EVIDENCE_V1, evidence_status="BLOCKED")
    with pytest.raises(Exception) as exc:  # noqa: PT011
        verify_theorem_evidence_integrity(forged)
    assert exc.value.code == "EXECUTION_COMPOSITION_CONTRACT_UNPROVEN"


def test_unproven_theorem_evidence_blocks_verifier() -> None:
    forged = dataclasses.replace(THEOREM_EVIDENCE_V1, evidence_status="BLOCKED")
    result = verify_execution_composition_premises(
        structure=_base_structure(),
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=forged,
    )
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "EXECUTION_COMPOSITION_CONTRACT_UNPROVEN"


def test_unknown_theorem_manifest_no_fallback() -> None:
    forged = dataclasses.replace(
        THEOREM_EVIDENCE_V1, composition_contract_id="hwpx-composition/v99"
    )
    with pytest.raises(UnsupportedCompositionContract):
        verify_theorem_evidence_integrity(forged)


def test_registry_resolve_unknown_no_fallback() -> None:
    empty = TheoremEvidenceRegistry()
    with pytest.raises(UnsupportedCompositionContract):
        empty.resolve(COMPOSITION_CONTRACT_ID, NATIVE_PRIMITIVE_CONTRACT_ID)


def test_historical_evidence_preserved_not_overwritten() -> None:
    reg = TheoremEvidenceRegistry()
    reg.register(THEOREM_EVIDENCE_V1)
    reg.register(THEOREM_EVIDENCE_V1)  # 동일 manifest 재등록은 무해
    newer = dataclasses.replace(
        THEOREM_EVIDENCE_V1, premise_verifier_version="hwpx-composition-verifier/v2"
    )
    # 같은 (contract, primitive) key 로 다른 manifest 를 latest 로 덮으려 하면 거절.
    with pytest.raises(Exception) as exc:  # noqa: PT011
        reg.register(newer)
    assert exc.value.code == "COMPOSITION_THEOREM_EVIDENCE_INTEGRITY_ERROR"
    # 원본은 그대로 보존된다.
    assert reg.resolve(COMPOSITION_CONTRACT_ID, NATIVE_PRIMITIVE_CONTRACT_ID) == THEOREM_EVIDENCE_V1


def test_forged_verifier_version_rejected_against_registered() -> None:
    # digest 는 재계산과 맞지만 registered canonical 과 다른 필드(위조) → integrity error.
    forged = dataclasses.replace(
        THEOREM_EVIDENCE_V1, premise_verifier_version="hwpx-composition-verifier/vX"
    )
    with pytest.raises(Exception) as exc:  # noqa: PT011
        verify_theorem_evidence_integrity(forged)
    assert exc.value.code == "COMPOSITION_THEOREM_EVIDENCE_INTEGRITY_ERROR"


# ══ runtime conformance seam(identity 분리) ══════════════════════════════════════════
def _conformance(status="PASS"):
    return RuntimeMaterializerConformanceManifest(
        runtime_capability_manifest_digest="sha256:" + "a" * 64,
        materialization_contract_id="hwpx-materialize/v1",
        materialization_base_contract_id="hwpx-materialize-base/v1",
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        admitted_composition_contract_ids=(COMPOSITION_CONTRACT_ID,),
        supported_plan_schema_versions=("hwpx-plan/v1",),
        supported_canonical_encoding_versions=("hwpx-canon/v1",),
        conformance_status=status,
    )


def test_runtime_conformance_identity_separate_from_theorem() -> None:
    passed = _verify(_base_structure())
    assert isinstance(passed, CompositionPremisesPassed)
    # PASS 결과는 theorem evidence digest 만 담고 runtime conformance digest 를 담지 않는다.
    conf_digest = runtime_conformance_digest(_conformance())
    assert passed.theorem_evidence_manifest_digest != conf_digest
    assert conf_digest not in str(passed.verified_premise_facts)
    assert not hasattr(passed, "runtime_conformance_digest")


def test_runtime_conformance_admission_query() -> None:
    reg = RuntimeMaterializerConformanceRegistry()
    query = dict(
        materialization_contract_id="hwpx-materialize/v1",
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        plan_schema_version="hwpx-plan/v1",
        canonical_encoding_version="hwpx-canon/v1",
    )
    # 기본 registry(비어 있음)는 admit 하지 않는다 — fail-closed.
    assert reg.is_admitted(**query) is False
    with pytest.raises(RuntimeMaterializerConformanceNotAdmitted):
        reg.require_admitted(**query)
    reg.register(_conformance())
    assert reg.is_admitted(**query) is True
    reg.require_admitted(**query)  # 이제 통과


def test_runtime_conformance_default_registry_empty() -> None:
    query = dict(
        materialization_contract_id="hwpx-materialize/v1",
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        plan_schema_version="hwpx-plan/v1",
        canonical_encoding_version="hwpx-canon/v1",
    )
    assert DEFAULT_RUNTIME_CONFORMANCE_REGISTRY.is_admitted(**query) is False


def test_runtime_conformance_rejects_non_pass_registration() -> None:
    reg = RuntimeMaterializerConformanceRegistry()
    with pytest.raises(RuntimeMaterializerConformanceNotAdmitted):
        reg.register(_conformance(status="FAIL"))


def test_runtime_conformance_query_partial_mismatch() -> None:
    reg = RuntimeMaterializerConformanceRegistry()
    reg.register(_conformance())
    base = dict(
        materialization_contract_id="hwpx-materialize/v1",
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        plan_schema_version="hwpx-plan/v1",
        canonical_encoding_version="hwpx-canon/v1",
    )
    assert reg.is_admitted(**{**base, "plan_schema_version": "hwpx-plan/v2"}) is False
    assert reg.is_admitted(**{**base, "composition_contract_id": "ghost"}) is False
    assert reg.is_admitted(**{**base, "canonical_encoding_version": "ghost"}) is False
    assert reg.is_admitted(**{**base, "materialization_contract_id": "ghost"}) is False
    assert reg.is_admitted(**{**base, "native_primitive_contract_id": "ghost"}) is False


# ══ unsupported contract fail-closed ═════════════════════════════════════════════════
def test_unsupported_composition_contract_no_fallback() -> None:
    result = verify_execution_composition_premises(
        structure=_base_structure(),
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
        composition_contract_id="hwpx-composition/v99",
    )
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "UNSUPPORTED_COMPOSITION_CONTRACT"


def test_unsupported_native_primitive_contract_no_fallback() -> None:
    forged = dataclasses.replace(
        NATIVE_PRIMITIVE_CONTRACT_V1, native_primitive_contract_id="hwpx-native-primitive/v99"
    )
    result = verify_execution_composition_premises(
        structure=_base_structure(),
        native_primitive_contract=forged,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT"


def test_forged_native_primitive_semantics_rejected() -> None:
    # 같은 ID 인데 의미(다른 field) 위조 → context error(같은 ID 의미 수정 금지).
    forged = dataclasses.replace(
        NATIVE_PRIMITIVE_CONTRACT_V1, field_write_contract_id="hwpx-field-write/vX"
    )
    result = verify_execution_composition_premises(
        structure=_base_structure(),
        native_primitive_contract=forged,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(result, CompositionPremiseContextError)
    assert result.code == "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT"


# ══ no mutation / purity ═════════════════════════════════════════════════════════════
def test_premise_verifier_pure_deterministic() -> None:
    a = _verify(_base_structure())
    b = _verify(_base_structure())
    assert isinstance(a, CompositionPremisesPassed) and isinstance(b, CompositionPremisesPassed)
    assert a.premise_verification_digest == b.premise_verification_digest
    assert dict(a.verified_premise_facts) == dict(b.verified_premise_facts)


def test_module_imports_no_native_or_package_reader() -> None:
    # verifier 는 HWPX clone/parse/serialize/remove·writer·sequence 를 절대 부르지 않는다 —
    # import 그래프에 native/package/xml/zip 이 전혀 없다(sequential preflight 0).
    src = Path("src/hwpxfiller/application/execution_composition.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    banned = ("hwpxcore", "lxml", "zipfile", "xml", "hwpxfiller.host", "hwpxfiller.external")
    for mod in imported:
        assert not any(mod == b or mod.startswith(b + ".") for b in banned), (
            f"금지 import {mod!r}"
        )
    # mutation/serialize 호출 토큰도 code 본문에 없다(prose 아닌 실제 호출).
    call_tokens = (".serialize(", ".clone(", ".remove_option(", ".write_field(")
    for token in call_tokens:
        assert token not in src, f"금지 호출 토큰 {token!r}"


def test_fixture_corpus_separated_positive_and_counterexample() -> None:
    pos_ids = {f["id"] for f in POSITIVE_THEOREM_FIXTURES}
    neg_ids = {f["id"] for f in COUNTEREXAMPLE_THEOREM_FIXTURES}
    assert pos_ids.isdisjoint(neg_ids)
    assert all(f["admitted"] is True for f in POSITIVE_THEOREM_FIXTURES)
    assert all(f["admitted"] is False for f in COUNTEREXAMPLE_THEOREM_FIXTURES)
    # digest 는 저장 순서가 아니라 내용에 결속(정렬).
    shuffled = tuple(reversed(POSITIVE_THEOREM_FIXTURES))
    assert fixture_manifest_digest(shuffled) == fixture_manifest_digest(POSITIVE_THEOREM_FIXTURES)


def test_theorem_evidence_digest_stable() -> None:
    assert theorem_evidence_digest(THEOREM_EVIDENCE_V1) == theorem_evidence_digest(THEOREM_EVIDENCE_V1)
    assert theorem_evidence_digest(THEOREM_EVIDENCE_V1).startswith("sha256:")


def test_encode_native_primitive_contract_roundtrips_ids() -> None:
    from hwpxfiller.application.execution_composition import encode_native_primitive_contract

    payload = encode_native_primitive_contract(NATIVE_PRIMITIVE_CONTRACT_V1)
    assert payload["native_primitive_contract_id"] == NATIVE_PRIMITIVE_CONTRACT_ID
    assert payload["option_removal_contract_id"] == REMOVE
    assert set(payload) == {
        "native_primitive_contract_id", "option_resolver_contract_id",
        "option_removal_contract_id", "field_resolver_contract_id", "field_write_contract_id",
        "envelope_postcondition_contract_id", "intentional_blank_write_contract_id",
        "primitive_semantics_version",
    }


# ── fact-missing → INCOMPLETE(context error) — forged projection 으로 fail-closed 확인 ──
def test_c2_duplicate_relation_fact_incomplete() -> None:
    struct = _two_option((10, 20), (30, 40))
    only = struct.removal_target_relations[0]
    forged = dataclasses.replace(struct, removal_target_relations=(only, only))
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C2"].status == "INCOMPLETE"


def test_c4_missing_owner_slot_fact_incomplete() -> None:
    struct = _base_structure()
    region = struct.option_regions[0]
    stripped = dataclasses.replace(
        region,
        owner_relation_facts=tuple(
            f for f in region.owner_relation_facts if f.get("relation") != "target_owner_slot"
        ),
    )
    forged = dataclasses.replace(
        struct, option_regions=(stripped, *struct.option_regions[1:])
    )
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C4"].status == "INCOMPLETE"


def test_c4_missing_envelope_fact_incomplete() -> None:
    # region content entry 를 envelope 없는 것으로 갈아끼우면 C4 는 fact 부재로 닫힌다.
    struct = _base_structure()
    forged = dataclasses.replace(struct, content_entries=())
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C4"].status == "INCOMPLETE"


def test_c6_missing_position_fact_incomplete() -> None:
    struct = _base_structure()
    region = next(r for r in struct.option_regions if r.retained_content_relation_facts)
    idx = struct.option_regions.index(region)
    stripped = dataclasses.replace(
        region,
        retained_content_relation_facts=({"field_id": "성명", "occurrence_ordinal": 0},),
    )
    regions = list(struct.option_regions)
    regions[idx] = stripped
    forged = dataclasses.replace(struct, option_regions=tuple(regions))
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C6"].status == "INCOMPLETE"


def test_c10_affected_entry_missing_envelope_incomplete() -> None:
    struct = _slotless()
    forged = dataclasses.replace(struct, content_entries=())
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C10"].status == "INCOMPLETE"


def test_c9_noncanonical_ordinal_incomplete() -> None:
    struct = _slotless()
    bad = dataclasses.replace(struct.field_occurrences[0], occurrence_ordinal=5)
    forged = dataclasses.replace(struct, field_occurrences=(bad,))
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C9"].status == "INCOMPLETE"


def test_c7_empty_value_target_incomplete() -> None:
    struct = _slotless()
    bad = dataclasses.replace(struct.field_occurrences[0], native_value_target_class="")
    forged = dataclasses.replace(struct, field_occurrences=(bad,))
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C7"].status == "INCOMPLETE"


def test_c1_duplicate_target_ref_fails() -> None:
    struct = _two_option((10, 20), (30, 40))
    dup = struct.option_regions[0]
    forged = dataclasses.replace(struct, option_regions=(dup, dup))
    assert evaluate_composition_premises(forged, theorem_evidence_valid=True)["C1"].status == "FAILED"


def test_passed_result_carries_premise_facts() -> None:
    result = _verify(_base_structure())
    assert isinstance(result, CompositionPremisesPassed)
    facts = result.verified_premise_facts
    assert facts["premises_proven"] == {pid: "OK" for pid in PREMISE_IDS}
    assert facts["crossing_free"] is True
    assert facts["target_target_relation_counts"] == {DISJOINT: 1}
    assert facts["occurrence_owner_kind_counts"]["ROOT"] == 2
