"""S5-06(#702) closed ExecutionContractSet + capture·basis·Plan canonical digests.

contract set 결속·nested digest 재계산 검증·Plan functional dependency·capture evidence codec 을
커버한다. semantic identity 가 timestamp/path/revision provenance 에 의존하지 않음을 함께 못박는다.
"""

from __future__ import annotations

import dataclasses

import pytest

from hwpxfiller.application.execution_capture import (
    MATERIALIZATION_BASE_CONTRACT_ID,
    EffectiveSelectionBasis,
    ExactTemplateExecutionBasis,
    QualificationProfileSemanticPayload,
)
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    THEOREM_EVIDENCE_V1,
    UnsupportedCompositionContract,
    theorem_evidence_digest,
)
from hwpxfiller.application.execution_compilation import (
    EffectiveFieldBindingBasis,
    EffectiveFieldBindingRule,
    FromSource,
    IntentionalBlank,
    active_binding_digest,
    encode_value_expression,
    required_source_key_set_digest,
)
from hwpxfiller.application.execution_contract_set import (
    AttemptSealCaptureEvidence,
    CaptureEvidenceProvenance,
    CompleteSealCaptureEvidence,
    DurableCaptureEvidenceIntegrityError,
    ExecutionBasis,
    ExecutionBasisIntegrityError,
    ExecutionContractSet,
    ExecutionContractSetIntegrityError,
    ExecutionContractSetRegistry,
    ExecutionPlanCompilationIntegrityError,
    ExecutionPlanIntegrityError,
    PlanCompilationKey,
    PlanCompilationLedger,
    QualificationProfileManifestIntegrityError,
    UnsupportedPlanSchemaError,
    build_execution_contract_set,
    build_sealed_plan,
    contract_set_manifest_digest,
    decode_durable_capture_evidence,
    encode_effective_selection,
    encode_durable_capture_evidence,
    execution_basis_digest,
    plan_compilation_key_of,
    plan_semantic_digest,
    qualification_profile_semantic_digest,
    require_consistent_qualification_profile,
    verify_execution_basis_integrity,
    verify_sealed_plan_integrity,
)

_THEOREM_DIGEST = theorem_evidence_digest(THEOREM_EVIDENCE_V1)
_PLAN_SCHEMA = "hwpx-execution-plan/v1"


# ─── fixtures ─────────────────────────────────────────────────────────────────────────
def _contracts(**over) -> ExecutionContractSet:
    kw = dict(
        slot_selection_contract_id="slot-selection/v1",
        field_binding_contract_id="field-binding/v1",
        source_schema_contract_id="source-schema/v1",
        raw_record_contract_id="raw-record/v1",
        execution_semantic_contract_id="execution-semantics/v1",
        binding_value_contract_id="binding-value/v1",
        document_value_resolution_contract_id="document-content-value/v1",
        record_validation_contract_id="record-validation/v1",
        record_review_contract_id="record-review/v1",
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        materialization_contract_id="materialization/v1",
        composition_theorem_evidence_manifest_digest=_THEOREM_DIGEST,
    )
    kw.update(over)
    return build_execution_contract_set(**kw)


def _template() -> ExactTemplateExecutionBasis:
    return ExactTemplateExecutionBasis(
        execution_base_kind="APPLIED_TEMPLATE_CANDIDATE",
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        work_authority_id="work-1",
        template_application_id="app-1",
        exact_content_digest="sha256:aaaa",
        canonical_blob_reference="blob://store/path",  # 제외 대상(store address)
    )


def _selection(**over) -> EffectiveSelectionBasis:
    kw = dict(
        slot_mode="SLOTTED",
        work_id="work-1",
        template_application_id="app-1",
        selection_semantic_contract_id="slot-selection/v1",
        template_structure_digest="sha256:struct",
        effective_selection_digest="sha256:eff",
        declared_selection_digest="sha256:decl",
    )
    kw.update(over)
    return EffectiveSelectionBasis(**kw)


_RULES = (
    EffectiveFieldBindingRule(
        "f_name", "SOURCE", FromSource("name", "TEXT", None, "document-content-value/v1")
    ),
    EffectiveFieldBindingRule("f_blank", "INTENTIONAL_BLANK", IntentionalBlank()),
)


def _binding(keys=("addr", "name")) -> EffectiveFieldBindingBasis:
    return EffectiveFieldBindingBasis(
        effective_active_binding_rules=_RULES,
        active_binding_digest=active_binding_digest(_RULES),
        required_source_keys=tuple(sorted(keys, key=lambda k: k.encode("utf-8"))),
        required_source_key_set_digest=required_source_key_set_digest(keys),
    )


def _basis(**over) -> ExecutionBasis:
    kw = dict(
        workspace_instance_id="ws-1",
        work_authority_id="work-1",
        qualification_profile_semantic_digest="sha256:qual",
        template=_template(),
        contracts=_contracts(),
        selection=_selection(),
        field_binding=_binding(),
    )
    kw.update(over)
    return ExecutionBasis(**kw)


def _requirements() -> list[dict]:
    # value_expression 은 effective binding rule 과 정확히 일치해야 verify 를 통과한다(P1-4).
    return [
        {"field_id": r.field_id, "expected_active_occurrence_count": 1,
         "value_expression": encode_value_expression(r.value_expression)}
        for r in _RULES
    ]


def _operations() -> list[dict]:
    return [
        {"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": "o2"},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_name"},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_blank"},
    ]


def _plan(**over):
    kw = dict(
        execution_basis=_basis(),
        active_field_requirements=_requirements(),
        ordered_operations=_operations(),
        plan_schema_version=_PLAN_SCHEMA,
    )
    kw.update(over)
    return build_sealed_plan(**kw)


# ─── ExecutionContractSet ───────────────────────────────────────────────────────────────
def test_build_binds_all_ids_with_manifest_digest() -> None:
    c = _contracts()
    assert c.contract_set_manifest_digest.startswith("sha256:")
    assert c.contract_set_manifest_digest == contract_set_manifest_digest(c)


def test_unknown_composition_no_latest_fallback() -> None:
    with pytest.raises(UnsupportedCompositionContract):
        _contracts(composition_contract_id="unknown-composition/v9")


def test_wrong_materialization_base_rejected() -> None:
    with pytest.raises(ExecutionContractSetIntegrityError):
        _contracts(materialization_base_contract_id="wrong-base/v1")


def test_wrong_theorem_evidence_digest_rejected() -> None:
    with pytest.raises(ExecutionContractSetIntegrityError):
        _contracts(composition_theorem_evidence_manifest_digest="sha256:forged")


def test_empty_role_rejected() -> None:
    with pytest.raises(ExecutionContractSetIntegrityError):
        _contracts(raw_record_contract_id="")


def test_manifest_digest_tamper_rejected() -> None:
    good = _contracts()
    with pytest.raises(ExecutionContractSetIntegrityError):
        dataclasses.replace(good, contract_set_manifest_digest="sha256:tampered")


def test_role_change_changes_manifest_digest() -> None:
    # 같은 schema 라도 결속된 ID 가 다르면 다른 manifest(우연 동일성 없음).
    a = _contracts()
    b = _contracts(materialization_contract_id="materialization/v2")
    assert a.contract_set_manifest_digest != b.contract_set_manifest_digest


def test_registry_same_schema_different_meaning_rejected() -> None:
    reg = ExecutionContractSetRegistry()
    reg.register(_contracts())
    reg.register(_contracts())  # 동일 재등록 idempotent
    with pytest.raises(ExecutionContractSetIntegrityError):
        reg.register(_contracts(materialization_contract_id="materialization/v2"))


def test_registry_unknown_resolve_no_fallback() -> None:
    reg = ExecutionContractSetRegistry()
    with pytest.raises(ExecutionContractSetIntegrityError):
        reg.resolve("execution-contract-set/v9")


def test_registry_preserves_historical_manifest() -> None:
    reg = ExecutionContractSetRegistry()
    c = _contracts()
    reg.register(c)
    assert reg.resolve(c.contract_set_schema_version) == c


def test_bad_schema_version_rejected() -> None:
    good = _contracts()
    with pytest.raises(ExecutionContractSetIntegrityError):
        dataclasses.replace(good, contract_set_schema_version="execution-contract-set/v9")


# ─── Qualification Profile semantic digest ───────────────────────────────────────────────
def _profile(**over) -> QualificationProfileSemanticPayload:
    kw = dict(
        qualification_profile_id="hwpx-template-qualification-v2",
        media="hwpx",
        adapter_contract_version="adapter/1",
        product_rule_version="product/1",
        operation_alphabet_version="op/1",
        projection_schema_version="hwpx-structure-projection-v2",
        manifest_payload={"k": "v"},
    )
    kw.update(over)
    return QualificationProfileSemanticPayload(**kw)


def test_qualification_digest_deterministic() -> None:
    assert qualification_profile_semantic_digest(_profile()) == (
        qualification_profile_semantic_digest(_profile())
    )


def test_qualification_manifest_payload_changes_digest() -> None:
    a = qualification_profile_semantic_digest(_profile(manifest_payload={"k": "v"}))
    b = qualification_profile_semantic_digest(_profile(manifest_payload={"k": "w"}))
    assert a != b


def test_qualification_consistency_guard() -> None:
    p = _profile()
    d = qualification_profile_semantic_digest(p)
    require_consistent_qualification_profile({}, p)  # 처음 관찰 OK
    require_consistent_qualification_profile({p.qualification_profile_id: d}, p)  # 같은 digest OK
    with pytest.raises(QualificationProfileManifestIntegrityError):
        require_consistent_qualification_profile(
            {p.qualification_profile_id: "sha256:other"}, p
        )


# ─── effective selection / binding digests ───────────────────────────────────────────────
def test_effective_selection_excludes_declared_digest() -> None:
    from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest

    a = canonical_execution_digest(encode_effective_selection(_selection()))
    b = canonical_execution_digest(
        encode_effective_selection(_selection(declared_selection_digest="sha256:different"))
    )
    assert a == b  # declared/provenance 는 effective identity 에 안 들어간다


# ─── ExecutionBasis ─────────────────────────────────────────────────────────────────────
def test_execution_basis_digest_deterministic() -> None:
    assert execution_basis_digest(_basis()) == execution_basis_digest(_basis())


def test_execution_basis_digest_excludes_blob_reference() -> None:
    other = dataclasses.replace(_template(), canonical_blob_reference="blob://elsewhere")
    assert execution_basis_digest(_basis()) == execution_basis_digest(_basis(template=other))


def test_execution_basis_integrity_passes_for_valid() -> None:
    verify_execution_basis_integrity(_basis())  # no raise


def test_execution_basis_active_binding_tamper_rejected() -> None:
    bad = dataclasses.replace(_binding(), active_binding_digest="sha256:tampered")
    with pytest.raises(ExecutionBasisIntegrityError):
        verify_execution_basis_integrity(_basis(field_binding=bad))


def test_execution_basis_source_key_tamper_rejected() -> None:
    bad = dataclasses.replace(_binding(), required_source_key_set_digest="sha256:tampered")
    with pytest.raises(ExecutionBasisIntegrityError):
        verify_execution_basis_integrity(_basis(field_binding=bad))


def test_qualification_semantic_digest_binds_plan_identity() -> None:
    # P1-1: 다른 qualification semantics(다른 profile manifest/product rule)면 다른 basis/Plan identity.
    a = execution_basis_digest(_basis())
    b = execution_basis_digest(_basis(qualification_profile_semantic_digest="sha256:other-qual"))
    assert a != b


def test_cross_work_basis_rejected() -> None:
    # P1-2: selection.work_id 가 basis/template 와 어긋나면 verifier 가 fail-closed.
    bad_sel = _selection(work_id="work-OTHER")
    with pytest.raises(ExecutionBasisIntegrityError):
        verify_execution_basis_integrity(_basis(selection=bad_sel))
    bad_app = _selection(template_application_id="app-OTHER")
    with pytest.raises(ExecutionBasisIntegrityError):
        verify_execution_basis_integrity(_basis(selection=bad_app))


def test_source_key_tuple_order_does_not_split_identity() -> None:
    # P2-10: 같은 key 집합이면 tuple 순서가 달라도 같은 basis digest.
    forward = _binding(keys=("addr", "name"))
    reverse = dataclasses.replace(forward, required_source_keys=("name", "addr"))
    assert execution_basis_digest(_basis(field_binding=forward)) == execution_basis_digest(
        _basis(field_binding=reverse)
    )


# ─── Sealed Plan + PlanCompilationKey ────────────────────────────────────────────────────
def test_plan_digest_deterministic_same_inputs() -> None:
    assert plan_semantic_digest(_plan()) == plan_semantic_digest(_plan())


def test_same_key_different_payload_integrity_error() -> None:
    ledger = PlanCompilationLedger()
    plan = _plan()
    key = plan_compilation_key_of(plan)
    ledger.record(key, plan_semantic_digest(plan))
    ledger.record(key, plan_semantic_digest(plan))  # idempotent
    with pytest.raises(ExecutionPlanCompilationIntegrityError):
        ledger.record(key, "sha256:conflicting-plan")
    assert ledger.get(key) == plan_semantic_digest(plan)


def test_schema_version_change_distinct_plan_allowed() -> None:
    ledger = PlanCompilationLedger()
    p1 = _plan()
    p2 = _plan(plan_schema_version="hwpx-execution-plan/v2")
    assert plan_semantic_digest(p1) != plan_semantic_digest(p2)
    ledger.record(plan_compilation_key_of(p1), plan_semantic_digest(p1))
    ledger.record(plan_compilation_key_of(p2), plan_semantic_digest(p2))  # 다른 key → 허용


def test_plan_canonicalizes_requirement_order_and_ignores_map_order() -> None:
    # build 가 requirement 를 APPLY 순서로 정본화하므로 입력 순서(뒤집기)는 identity 를 안 바꾼다.
    reordered = list(reversed(_requirements()))
    assert plan_semantic_digest(_plan()) == plan_semantic_digest(
        _plan(active_field_requirements=reordered)
    )
    # map key 삽입 순서도 identity 가 아니다(같은 요구, dict 키 순서만 뒤집음).
    shuffled = [
        {"value_expression": r["value_expression"],
         "expected_active_occurrence_count": r["expected_active_occurrence_count"],
         "field_id": r["field_id"]}
        for r in _requirements()
    ]
    assert plan_semantic_digest(_plan()) == plan_semantic_digest(
        _plan(active_field_requirements=shuffled)
    )


def test_verify_plan_valid_passes() -> None:
    verify_sealed_plan_integrity(_plan(), supported_plan_schemas=[_PLAN_SCHEMA])


def test_verify_plan_unsupported_schema_no_fallback() -> None:
    with pytest.raises(UnsupportedPlanSchemaError):
        verify_sealed_plan_integrity(_plan(), supported_plan_schemas=["other/v1"])


def test_build_plan_unsupported_encoding_rejected() -> None:
    from hwpxfiller.domain.canonical_execution_encoding import UnsupportedCanonicalEncodingError

    with pytest.raises(UnsupportedCanonicalEncodingError):
        _plan(canonical_encoding_version="execution-canonical/v9")


def test_verify_plan_bijection_corruption_rejected() -> None:
    # requirement 하나에 대응 APPLY 가 없다(bijection 위반).
    ops = [o for o in _operations() if o.get("field_id") != "f_blank"]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(ordered_operations=ops), supported_plan_schemas=[_PLAN_SCHEMA]
        )


def test_verify_plan_operation_order_corruption_rejected() -> None:
    # REMOVE 가 APPLY 뒤에 온다(비canonical order).
    ops = [
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_name"},
        {"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": "o2"},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_blank"},
    ]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(ordered_operations=ops), supported_plan_schemas=[_PLAN_SCHEMA]
        )


def test_verify_plan_unknown_operation_rejected() -> None:
    ops = _operations() + [{"op": "MYSTERY_OP"}]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(ordered_operations=ops), supported_plan_schemas=[_PLAN_SCHEMA]
        )


def test_verify_plan_duplicate_apply_rejected() -> None:
    ops = _operations() + [{"op": "APPLY_FIELD_BINDING", "field_id": "f_name"}]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(ordered_operations=ops), supported_plan_schemas=[_PLAN_SCHEMA]
        )


def test_verify_plan_missing_field_id_rejected() -> None:
    ops = [{"op": "APPLY_FIELD_BINDING"}]  # field_id 없음
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(active_field_requirements=[], ordered_operations=ops),
            supported_plan_schemas=[_PLAN_SCHEMA],
        )


def test_verify_plan_duplicate_requirement_rejected() -> None:
    reqs = _requirements() + [dict(_requirements()[0])]  # f_name 중복
    ops = _operations()
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(active_field_requirements=reqs, ordered_operations=ops),
            supported_plan_schemas=[_PLAN_SCHEMA],
        )


def test_seal_deep_freezes_against_post_seal_mutation() -> None:
    # P1-3: 봉인에 넘긴 원본 nested dict 를 이후 고쳐도 plan_semantic_digest 는 흔들리지 않는다.
    reqs = _requirements()
    plan = _plan(active_field_requirements=reqs)
    before = plan_semantic_digest(plan)
    reqs[0]["value_expression"]["source_key"] = "TAMPERED"  # 원본 변이
    assert plan_semantic_digest(plan) == before
    # 봉인된 payload 자체도 immutable(frozen mapping)이라 쓰기 시도가 실패한다.
    with pytest.raises(TypeError):
        plan.active_field_requirements[0]["expected_active_occurrence_count"] = 99  # type: ignore[index]


def test_verify_plan_requirement_value_expression_mismatch_rejected() -> None:
    # P1-4: field 는 그대로 두고 value_expression 만 바꾼 위조 requirement 를 잡는다.
    reqs = _requirements()
    reqs[0] = dict(reqs[0])
    reqs[0]["value_expression"] = {
        "kind": "FROM_SOURCE", "source_key": "SOMETHING_ELSE",
        "value_type": "TEXT", "format_code": None,
        "document_content_value_policy_id": "document-content-value/v1",
    }
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(active_field_requirements=reqs), supported_plan_schemas=[_PLAN_SCHEMA]
        )


def test_verify_plan_requirement_without_binding_rule_rejected() -> None:
    # requirement field 가 APPLY 와 짝은 맞지만 effective binding rule 이 없으면 fail-closed.
    reqs = _requirements() + [
        {"field_id": "f_ghost", "expected_active_occurrence_count": 1,
         "value_expression": {"kind": "INTENTIONAL_BLANK", "exact_blank_policy": "EXACT_BLANK"}}
    ]
    ops = _operations() + [{"op": "APPLY_FIELD_BINDING", "field_id": "f_ghost"}]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(
            _plan(active_field_requirements=reqs, ordered_operations=ops),
            supported_plan_schemas=[_PLAN_SCHEMA],
        )


def test_deep_freeze_recurses_into_lists() -> None:
    from hwpxfiller.application.execution_contract_set import _deep_freeze

    frozen = _deep_freeze({"a": [1, {"b": 2}]})
    assert frozen["a"] == (1, {"b": 2})
    with pytest.raises(TypeError):
        frozen["a"][1]["b"] = 9  # type: ignore[index]


def test_verify_plan_apply_order_swap_rejected() -> None:
    # P2-9: APPLY 두 개를 뒤바꾸면 requirement 순서와 어긋나 거절된다.
    plan = _plan()
    swapped_ops = (
        {"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": "o2"},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_blank"},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_name"},
    )
    tampered = dataclasses.replace(plan, ordered_operations=swapped_ops)
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_sealed_plan_integrity(tampered, supported_plan_schemas=[_PLAN_SCHEMA])


def test_verify_plan_remove_option_missing_operand_rejected() -> None:
    # P2-11: 빈/비문자열 slot·option 을 가진 REMOVE_OPTION 은 decode 경계에서 거절.
    for bad_remove in (
        {"op": "REMOVE_OPTION"},
        {"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": ""},
        {"op": "REMOVE_OPTION", "slot_id": 1, "option_id": "o2"},
    ):
        ops = [bad_remove] + [o for o in _operations() if o["op"] == "APPLY_FIELD_BINDING"]
        with pytest.raises(ExecutionPlanIntegrityError):
            verify_sealed_plan_integrity(
                _plan(ordered_operations=ops), supported_plan_schemas=[_PLAN_SCHEMA]
            )


def test_verify_plan_recomputes_basis_nested_digest() -> None:
    bad = dataclasses.replace(_binding(), active_binding_digest="sha256:tampered")
    with pytest.raises(ExecutionBasisIntegrityError):
        verify_sealed_plan_integrity(
            _plan(execution_basis=_basis(field_binding=bad)),
            supported_plan_schemas=[_PLAN_SCHEMA],
        )


def test_plan_key_encoding_stable() -> None:
    from hwpxfiller.application.execution_contract_set import plan_compilation_key_digest

    key = PlanCompilationKey("sha256:basis", _PLAN_SCHEMA, "execution-canonical/v1")
    assert plan_compilation_key_digest(key) == plan_compilation_key_digest(key)


# ─── DurableSealCaptureEvidence codec ────────────────────────────────────────────────────
def _provenance() -> CaptureEvidenceProvenance:
    return CaptureEvidenceProvenance(
        field_binding_authority_revision="rev-7",
        source_configuration_version="cfg-3",
        captured_at="2026-08-16T00:00:00Z",
    )


def _complete_evidence() -> CompleteSealCaptureEvidence:
    from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest

    projection = {"workspace_instance_id": "ws-1", "work_authority_id": "work-1"}
    return CompleteSealCaptureEvidence(
        captured_execution_input_semantic_projection=projection,
        captured_execution_input_digest=canonical_execution_digest(projection),
        provenance=_provenance(),
    )


def _attempt_evidence() -> AttemptSealCaptureEvidence:
    from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest

    projection = {"workspace_instance_id": "ws-1", "blocked": "SLOT_CONFIGURATION_INCOMPLETE"}
    return AttemptSealCaptureEvidence(
        captured_attempt_semantic_projection=projection,
        captured_attempt_digest=canonical_execution_digest(projection),
        normalized_blockers=("SLOT_CONFIGURATION_INCOMPLETE",),
        provenance=_provenance(),
    )


def test_capture_evidence_complete_round_trip() -> None:
    ev = _complete_evidence()
    decoded = decode_durable_capture_evidence(encode_durable_capture_evidence(ev))
    assert isinstance(decoded, CompleteSealCaptureEvidence)
    assert decoded.captured_execution_input_digest == ev.captured_execution_input_digest
    assert decoded.provenance == ev.provenance


def test_capture_evidence_attempt_round_trip() -> None:
    ev = _attempt_evidence()
    decoded = decode_durable_capture_evidence(encode_durable_capture_evidence(ev))
    assert isinstance(decoded, AttemptSealCaptureEvidence)
    assert decoded.normalized_blockers == ev.normalized_blockers


def test_capture_evidence_encode_rejects_mismatched_digest() -> None:
    ev = dataclasses.replace(_complete_evidence(), captured_execution_input_digest="sha256:bad")
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        encode_durable_capture_evidence(ev)


def test_capture_evidence_attempt_encode_rejects_mismatched_digest() -> None:
    ev = dataclasses.replace(_attempt_evidence(), captured_attempt_digest="sha256:bad")
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        encode_durable_capture_evidence(ev)


def test_capture_evidence_decode_digest_tamper_rejected() -> None:
    payload = encode_durable_capture_evidence(_complete_evidence())
    payload["semantic_digest"] = "sha256:tampered"
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence(payload)


def test_capture_evidence_decode_unknown_kind_rejected() -> None:
    payload = encode_durable_capture_evidence(_complete_evidence())
    payload["kind"] = "MYSTERY"
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence(payload)


def test_capture_evidence_decode_malformed_rejected() -> None:
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence("not a mapping")
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence({"kind": "COMPLETE"})


def test_capture_evidence_decode_missing_provenance_field_rejected() -> None:
    payload = encode_durable_capture_evidence(_complete_evidence())
    del payload["provenance"]["captured_at"]
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence(payload)


def test_capture_evidence_decode_non_mapping_provenance_rejected() -> None:
    payload = encode_durable_capture_evidence(_complete_evidence())
    payload["provenance"] = "not-a-mapping"
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence(payload)


def test_capture_evidence_decode_non_string_provenance_field_rejected() -> None:
    # P2-6: null/number/mapping 을 str() 로 조용히 삼키지 않는다.
    for bad in ({"bad": 1}, 12345, None, ["x"]):
        payload = encode_durable_capture_evidence(_complete_evidence())
        payload["provenance"]["captured_at"] = bad
        with pytest.raises(DurableCaptureEvidenceIntegrityError):
            decode_durable_capture_evidence(payload)


def test_capture_evidence_attempt_bad_blockers_rejected() -> None:
    payload = encode_durable_capture_evidence(_attempt_evidence())
    payload["normalized_blockers"] = "not-a-list"
    with pytest.raises(DurableCaptureEvidenceIntegrityError):
        decode_durable_capture_evidence(payload)
