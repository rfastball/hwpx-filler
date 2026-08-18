"""S5-07(#703) content-addressed Plan aggregate 값 모델·codec·순수 전이.

이 파일은 순수(파일 I/O 없음) 층을 검증한다 — content-address·create-once reuse·compilation
functional dependency·terminal outcome union·capture evidence·codec round-trip·fail-closed decode.
store lease/CAS/restart 는 ``test_work_execution_plan_store.py`` 가 얹는다(builders 를 재사용).
"""

from __future__ import annotations

import dataclasses

import pytest

from hwpxfiller.application.execution_capture import (
    MATERIALIZATION_BASE_CONTRACT_ID,
    EffectiveSelectionBasis,
    ExactTemplateExecutionBasis,
    ResolvedSealPolicy,
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
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    THEOREM_EVIDENCE_V1,
    theorem_evidence_digest,
)
from hwpxfiller.application.execution_contract_set import (
    AttemptSealCaptureEvidence,
    CaptureEvidenceProvenance,
    CompleteSealCaptureEvidence,
    ExecutionBasis,
    ExecutionContractSet,
    ExecutionPlanCompilationIntegrityError,
    ExecutionPlanIntegrityError,
    build_execution_contract_set,
    build_sealed_plan,
    encode_sealed_plan,
    execution_basis_digest,
    plan_semantic_digest,
)
from hwpxfiller.application.stored_execution_plan import (
    ExecutionPlanDependencyResolutionError,
    ExecutionPlanStoreError,
    ExecutionPlanStoreIntegrityError,
    ExecutionPolicyBlocked,
    ExecutionQualificationBlocked,
    PlanDependencySet,
    PlanPublished,
    PlanFirstSealedProvenance,
    RequestedAuto,
    RequestedExact,
    SealedExecutionPlanRecord,
    StaleExecutionBasis,
    apply_publish,
    decode_aggregate,
    empty_aggregate,
    encode_aggregate,
    verify_encoded_plan_integrity,
    verify_record_content_address,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    canonical_execution_digest,
    UnsupportedCanonicalEncodingError,
)

_PLAN_SCHEMA = "hwpx-execution-plan/v1"
_ENCODING = "execution-canonical/v1"
_THEOREM_DIGEST = theorem_evidence_digest(THEOREM_EVIDENCE_V1)


# ─── S5-06 payload builders(test_execution_contract_set 미러) ─────────────────────────
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
        canonical_blob_reference="blob://store/path",
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


def _requirements():
    return [
        {
            "field_id": r.field_id,
            "expected_active_occurrence_count": 1,
            "value_expression": encode_value_expression(r.value_expression),
        }
        for r in _RULES
    ]


def _operations(removed_option="o2"):
    return [
        {"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": removed_option},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_name"},
        {"op": "APPLY_FIELD_BINDING", "field_id": "f_blank"},
    ]


def plan(*, basis=None, removed_option="o2", plan_schema_version=_PLAN_SCHEMA):
    return build_sealed_plan(
        execution_basis=basis or _basis(),
        active_field_requirements=_requirements(),
        ordered_operations=_operations(removed_option),
        plan_schema_version=plan_schema_version,
    )


def policy(**over) -> ResolvedSealPolicy:
    kw = dict(
        policy_resolution_version="policy/v1",
        execution_base_kind="APPLIED_TEMPLATE_CANDIDATE",
        execution_semantic_contract_id="execution-semantics/v1",
        binding_value_contract_id="binding-value/v1",
        raw_record_contract_id="raw-record/v1",
        document_value_resolution_contract_id="document-content-value/v1",
        record_validation_contract_id="record-validation/v1",
        record_review_contract_id="record-review/v1",
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        composition_theorem_evidence_manifest_digest=_THEOREM_DIGEST,
        materialization_contract_id="materialization/v1",
        plan_schema_version=_PLAN_SCHEMA,
        canonical_encoding_version=_ENCODING,
    )
    kw.update(over)
    return ResolvedSealPolicy(**kw)


def deps(**over) -> PlanDependencySet:
    kw = dict(
        candidate_blob_ref="blob://candidate/1",
        pass_evidence_ref="evidence://pass/1",
        qualification_profile_manifest_ref="manifest://profile/1",
        template_structure_projection_ref="struct://projection/1",
        execution_contract_set_ref="contractset://1",
        composition_theorem_evidence_manifest_ref="theorem://1",
    )
    kw.update(over)
    return PlanDependencySet(**kw)




def complete_evidence(**over) -> CompleteSealCaptureEvidence:
    projection = {"captured": "input", "seed": over.pop("seed", "a")}
    digest = canonical_execution_digest(projection)
    return CompleteSealCaptureEvidence(
        captured_execution_input_semantic_projection=projection,
        captured_execution_input_digest=digest,
        provenance=CaptureEvidenceProvenance(
            field_binding_authority_revision=over.pop("revision", "fb-rev-7"),
            source_configuration_version="src-cfg-3",
            captured_at="2026-08-17T00:00:00Z",
        ),
    )


def attempt_evidence() -> AttemptSealCaptureEvidence:
    projection = {"attempt": "partial"}
    return AttemptSealCaptureEvidence(
        captured_attempt_semantic_projection=projection,
        captured_attempt_digest=canonical_execution_digest(projection),
        normalized_blockers=("SLOT_CONFIGURATION_INCOMPLETE",),
        provenance=CaptureEvidenceProvenance(
            field_binding_authority_revision="fb-rev-7",
            source_configuration_version="src-cfg-3",
            captured_at="2026-08-17T00:00:00Z",
        ),
    )


def published_outcome(a_plan, evidence, kind="CREATED") -> PlanPublished:
    return PlanPublished(
        publication_kind=kind,
        plan_semantic_digest=plan_semantic_digest(a_plan),
        execution_basis_digest=execution_basis_digest(a_plan.execution_basis),
        captured_execution_input_digest=evidence.captured_execution_input_digest,
    )


def qual_blocked(evidence, ref="ev://1") -> ExecutionQualificationBlocked:
    """대응 capture evidence 와 정합한 ExecutionQualificationBlocked(store 교차검증 통과용)."""
    if isinstance(evidence, CompleteSealCaptureEvidence):
        return ExecutionQualificationBlocked(
            capture_evidence_ref=ref,
            normalized_blockers=("COMPILER_BLOCK",),
            captured_execution_input_digest=evidence.captured_execution_input_digest,
        )
    return ExecutionQualificationBlocked(
        capture_evidence_ref=ref,
        normalized_blockers=evidence.normalized_blockers,
        captured_attempt_digest=evidence.captured_attempt_digest,
    )


def _publish(aggregate, *, request_id, a_plan, evidence, kind="CREATED", now="t0"):
    return apply_publish(
        aggregate,
        request_id=request_id,
        resolved_seal_policy=policy(),
        capture_evidence=evidence,
        plan_payload=a_plan,
        dependency_set=deps(),
        published_outcome=published_outcome(a_plan, evidence, kind),
        now=now,
    )


# ─── identity / create-once ───────────────────────────────────────────────────────────
def test_plan_record_addressed_by_semantic_digest_only() -> None:
    p = plan()
    agg = _publish(
        empty_aggregate("work-1", "ws-1"),
        request_id="r1",
        a_plan=p,
        evidence=complete_evidence(),
    )
    digest = plan_semantic_digest(p)
    record = agg.plans_by_semantic_digest[digest]
    assert record.plan_semantic_digest == digest
    verify_record_content_address(record)


def test_no_random_current_latest_pointer_fields() -> None:
    names = {f.name for f in dataclasses.fields(SealedExecutionPlanRecord)}
    for forbidden in ("plan_id", "current_plan_id", "latest_plan", "is_current",
                      "invalidated", "superseded_by"):
        assert forbidden not in names
    agg_names = {f.name for f in dataclasses.fields(
        type(empty_aggregate("w", "ws")))}
    for forbidden in ("current_plan_id", "latest_plan", "is_current"):
        assert forbidden not in agg_names




def test_same_digest_republish_is_reuse_no_version_bump() -> None:
    # R2-04a: 같은 plan 재-publish 는 content-addressed REUSE — aggregate 무변경(version bump 없음),
    # first-seen ledger 없음(replay 제거). 최초 봉인 provenance 는 overwrite 없이 보존된다.
    p = plan()
    agg = _publish(
        empty_aggregate("work-1", "ws-1"), request_id="r1",
        a_plan=p, evidence=complete_evidence(seed="a"), now="t0",
    )
    ev2 = complete_evidence(seed="b")
    agg2 = apply_publish(
        agg, request_id="r2", resolved_seal_policy=policy(), capture_evidence=ev2,
        plan_payload=p, dependency_set=deps(),
        published_outcome=published_outcome(p, ev2, "REUSED"), now="t1",
    )
    digest = plan_semantic_digest(p)
    assert (
        agg2.plans_by_semantic_digest[digest]
        .first_sealed_provenance.first_sealed_by_request_id == "r1"
    )
    assert agg2 is agg  # REUSE = 무변경(같은 객체 반환)
    assert agg2.aggregate_version == agg.aggregate_version
    assert not hasattr(agg2, "first_seen_ledger")


def test_same_digest_different_payload_rejected() -> None:
    p = plan()
    digest = plan_semantic_digest(p)
    tampered = SealedExecutionPlanRecord(
        plan_semantic_digest=digest,
        semantic_payload_encoded={"tampered": True},
        dependency_set=deps(),
        first_sealed_provenance=PlanFirstSealedProvenance("t0", "r0"),
    )
    seeded = dataclasses.replace(
        empty_aggregate("work-1", "ws-1"),
        plans_by_semantic_digest={digest: tampered},
    )
    with pytest.raises(ExecutionPlanIntegrityError):
        _publish(seeded, request_id="r1", a_plan=p, evidence=complete_evidence())


def test_same_digest_different_dependency_set_rejected() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    ev = complete_evidence(seed="b")
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            agg, request_id="r2",            resolved_seal_policy=policy(), capture_evidence=ev, plan_payload=p,
            dependency_set=deps(candidate_blob_ref="blob://OTHER"),
            published_outcome=published_outcome(p, ev, "REUSED"), now="t1",
        )


def test_same_compilation_key_different_digest_rejected() -> None:
    a = plan(removed_option="o2")
    b = plan(removed_option="o3")  # 같은 basis → 같은 compilation key, 다른 plan digest
    assert plan_semantic_digest(a) != plan_semantic_digest(b)
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=a, evidence=complete_evidence())
    with pytest.raises(ExecutionPlanCompilationIntegrityError):
        _publish(agg, request_id="r2", a_plan=b, evidence=complete_evidence(seed="b"))


def test_different_schema_key_coexistence() -> None:
    a = plan(plan_schema_version="hwpx-execution-plan/v1")
    b = plan(plan_schema_version="hwpx-execution-plan/v2")
    agg = apply_publish(
        empty_aggregate("work-1", "ws-1"), request_id="r1",        resolved_seal_policy=policy(plan_schema_version="hwpx-execution-plan/v1"),
        capture_evidence=complete_evidence(), plan_payload=a, dependency_set=deps(),
        published_outcome=published_outcome(a, complete_evidence(), "CREATED"), now="t0",
    )
    ev = complete_evidence(seed="b")
    agg2 = apply_publish(
        agg, request_id="r2",        resolved_seal_policy=policy(plan_schema_version="hwpx-execution-plan/v2"),
        capture_evidence=ev, plan_payload=b, dependency_set=deps(),
        published_outcome=published_outcome(b, ev, "CREATED"), now="t1",
    )
    assert len(agg2.plans_by_semantic_digest) == 2
    assert len(agg2.plans_by_compilation_key) == 2


def test_publication_kind_mismatch_rejected() -> None:
    p = plan()
    with pytest.raises(ExecutionPlanIntegrityError):
        _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                 a_plan=p, evidence=complete_evidence(), kind="REUSED")


# ─── publish integrity guards ─────────────────────────────────────────────────────────
def test_plan_schema_must_match_policy() -> None:
    p = plan()
    ev = complete_evidence()
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            empty_aggregate("work-1", "ws-1"), request_id="r1",            resolved_seal_policy=policy(plan_schema_version="hwpx-execution-plan/vX"),
            capture_evidence=ev, plan_payload=p, dependency_set=deps(),
            published_outcome=published_outcome(p, ev), now="t0",
        )


def test_encoding_must_match_policy() -> None:
    p = plan()
    ev = complete_evidence()
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            empty_aggregate("work-1", "ws-1"), request_id="r1",            resolved_seal_policy=policy(canonical_encoding_version="other/v9"),
            capture_evidence=ev, plan_payload=p, dependency_set=deps(),
            published_outcome=published_outcome(p, ev), now="t0",
        )


@pytest.mark.parametrize("bad", ["plan_semantic_digest", "execution_basis_digest",
                                 "captured_execution_input_digest"])
def test_published_outcome_claim_must_match(bad) -> None:
    p = plan()
    ev = complete_evidence()
    outcome = dataclasses.replace(published_outcome(p, ev), **{bad: "sha256:forged"})
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            empty_aggregate("work-1", "ws-1"), request_id="r1",            resolved_seal_policy=policy(), capture_evidence=ev, plan_payload=p,
            dependency_set=deps(), published_outcome=outcome, now="t0",
        )


def test_publish_requires_complete_evidence() -> None:
    p = plan()
    ev = attempt_evidence()
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            empty_aggregate("work-1", "ws-1"), request_id="r1",            resolved_seal_policy=policy(), capture_evidence=ev, plan_payload=p,
            dependency_set=deps(),
            published_outcome=PlanPublished("CREATED", plan_semantic_digest(p),
                                            execution_basis_digest(p.execution_basis),
                                            "sha256:x"),
            now="t0",
        )






def test_empty_request_id_rejected() -> None:
    p = plan()
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        _publish(empty_aggregate("work-1", "ws-1"), request_id="", a_plan=p,
                 evidence=complete_evidence())


# ─── ledger-only terminal ─────────────────────────────────────────────────────────────








# ─── retention / dependencies ─────────────────────────────────────────────────────────
def test_retained_dependency_refs_append_only() -> None:
    a = plan(plan_schema_version="hwpx-execution-plan/v1")
    b = plan(plan_schema_version="hwpx-execution-plan/v2")
    agg = apply_publish(
        empty_aggregate("work-1", "ws-1"), request_id="r1",        resolved_seal_policy=policy(plan_schema_version="hwpx-execution-plan/v1"),
        capture_evidence=complete_evidence(), plan_payload=a,
        dependency_set=deps(candidate_blob_ref="blob://A"),
        published_outcome=published_outcome(a, complete_evidence(), "CREATED"), now="t0",
    )
    ev = complete_evidence(seed="b")
    agg2 = apply_publish(
        agg, request_id="r2",        resolved_seal_policy=policy(plan_schema_version="hwpx-execution-plan/v2"),
        capture_evidence=ev, plan_payload=b,
        dependency_set=deps(candidate_blob_ref="blob://B"),
        published_outcome=published_outcome(b, ev, "CREATED"), now="t1",
    )
    retained = {d.candidate_blob_ref for d in agg2.retained_dependency_refs()}
    assert retained == {"blob://A", "blob://B"}


def test_dependency_set_has_no_runtime_implementation_field() -> None:
    names = {f.name for f in dataclasses.fields(PlanDependencySet)}
    assert not any("runtime" in n or "conformance" in n or "implementation" in n
                   for n in names)
    assert names == {
        "candidate_blob_ref", "pass_evidence_ref", "qualification_profile_manifest_ref",
        "template_structure_projection_ref", "execution_contract_set_ref",
        "composition_theorem_evidence_manifest_ref",
    }


def test_empty_dependency_ref_rejected() -> None:
    with pytest.raises(ExecutionPlanDependencyResolutionError):
        deps(pass_evidence_ref="")


# ─── selector / fingerprint codec ─────────────────────────────────────────────────────




def test_requested_exact_empty_rejected() -> None:
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        RequestedExact("")




# ─── aggregate codec round-trip + fail-closed decode ──────────────────────────────────
def test_aggregate_round_trip_content_address() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    restored = decode_aggregate(encode_aggregate(agg), "work-1")
    assert restored == agg
    # 저장된 selection semantic 이 그대로 복원된다(exact S4 Selection round-trip).
    payload = restored.plans_by_semantic_digest[plan_semantic_digest(p)].semantic_payload_encoded
    assert payload["execution_basis"]["selection"]["slot_mode"] == "SLOTTED"


def test_decode_unknown_store_schema_fail_closed() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    content["store_schema_version"] = "work-execution-plan-store/v999"
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        decode_aggregate(content, "work-1")


def test_decode_cross_work_file_rejected() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        decode_aggregate(encode_aggregate(agg), "work-OTHER")


def test_decode_tampered_plan_payload_fail_closed() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    content["plans"][0]["semantic_payload"]["plan_schema_version"] = "tampered"
    with pytest.raises(ExecutionPlanIntegrityError):
        decode_aggregate(content, "work-1")






def test_decode_compilation_map_dangling_plan_rejected() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    content["compilation_map"][0]["plan_semantic_digest"] = "sha256:ghost"
    with pytest.raises(ExecutionPlanCompilationIntegrityError):
        decode_aggregate(content, "work-1")




@pytest.mark.parametrize("factory", [
    lambda: PlanPublished("WAT", "sha256:a", "sha256:b", "sha256:c"),
    lambda: ExecutionQualificationBlocked(capture_evidence_ref="ev", normalized_blockers=("",)),
    lambda: ExecutionPolicyBlocked(policy_code=""),
    lambda: StaleExecutionBasis("sha256:i", "sha256:b", "WAT"),
])
def test_outcome_post_init_guards(factory) -> None:
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        factory()








@pytest.mark.parametrize("mutate", [
    lambda plans: plans.append(dict(plans[0])),  # 중복 plan digest
])
def test_decode_duplicate_plan_digest_fail_closed(mutate) -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    mutate(content["plans"])
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        decode_aggregate(content, "work-1")


def test_decode_duplicate_compilation_key_fail_closed() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    content["compilation_map"].append(dict(content["compilation_map"][0]))
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        decode_aggregate(content, "work-1")




@pytest.mark.parametrize("mutate", [
    lambda c: c.__setitem__("aggregate_version", 0),
    lambda c: c.__setitem__("aggregate_version", True),
    lambda c: c.__setitem__("plans", "notalist"),
    lambda c: c.__setitem__("compilation_map", "notalist"),
])
def test_decode_structural_corruption_fail_closed(mutate) -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    mutate(content)
    with pytest.raises(ExecutionPlanStoreError):
        decode_aggregate(content, "work-1")


# ─── Codex review round: trust-boundary cross-binding (9 findings) ────────────────────
def _other_work_basis(*, work="work-OTHER", ws="ws-1"):
    """다른 Work 로 자기정합한 basis(verify_sealed_plan_integrity 통과, aggregate 결속만 어긋난다)."""
    template = ExactTemplateExecutionBasis(
        execution_base_kind="APPLIED_TEMPLATE_CANDIDATE",
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        work_authority_id=work, template_application_id="app-1",
        exact_content_digest="sha256:aaaa", canonical_blob_reference="blob://store/path",
    )
    return _basis(work_authority_id=work, workspace_instance_id=ws, template=template,
                  selection=_selection(work_id=work))


def test_p1_1_publish_binds_plan_basis_work_to_aggregate() -> None:
    # fingerprint 는 aggregate 와 일치하지만 plan basis 는 다른 Work → 저장 거절.
    p = plan(basis=_other_work_basis(work="work-OTHER"))
    with pytest.raises(ExecutionPlanIntegrityError):
        _publish(empty_aggregate("work-1", "ws-1"), request_id="r1", a_plan=p,
                 evidence=complete_evidence())


def test_p1_1_publish_binds_plan_basis_workspace_to_aggregate() -> None:
    p = plan(basis=_other_work_basis(work="work-1", ws="ws-OTHER"))
    with pytest.raises(ExecutionPlanIntegrityError):
        _publish(empty_aggregate("work-1", "ws-1"), request_id="r1", a_plan=p,
                 evidence=complete_evidence())


@pytest.mark.parametrize("field", [
    "execution_semantic_contract_id", "binding_value_contract_id", "raw_record_contract_id",
    "materialization_contract_id",
])
def test_p1_2_publish_rejects_policy_contract_mismatch(field) -> None:
    p = plan()
    ev = complete_evidence()
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            empty_aggregate("work-1", "ws-1"), request_id="r1",            resolved_seal_policy=policy(**{field: "wrong/v9"}), capture_evidence=ev,
            plan_payload=p, dependency_set=deps(),
            published_outcome=published_outcome(p, ev), now="t0",
        )


def test_p1_2_publish_rejects_policy_base_kind_mismatch() -> None:
    p = plan()
    ev = complete_evidence()
    with pytest.raises(ExecutionPlanIntegrityError):
        apply_publish(
            empty_aggregate("work-1", "ws-1"), request_id="r1",
            resolved_seal_policy=policy(execution_base_kind="CONTINUATION_OUTPUT_DOCUMENT"),
            capture_evidence=ev, plan_payload=p, dependency_set=deps(),
            published_outcome=published_outcome(p, ev), now="t0",
        )


















def test_p1_5_encoded_plan_integrity_accepts_valid_payload() -> None:
    verify_encoded_plan_integrity(encode_sealed_plan(plan()))


def test_p1_5_encoded_plan_integrity_rejects_bad_basis_digest() -> None:
    enc = dict(encode_sealed_plan(plan()))
    enc["execution_basis_digest"] = "sha256:forged"
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_encoded_plan_integrity_rejects_bad_operation_order() -> None:
    enc = dict(encode_sealed_plan(plan()))
    ops = list(enc["ordered_operations"])
    enc["ordered_operations"] = [ops[1], ops[0], ops[2]]  # APPLY before REMOVE
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_encoded_plan_integrity_rejects_unsupported_encoding() -> None:
    enc = dict(encode_sealed_plan(plan()))
    enc["canonical_encoding_version"] = "other/v9"
    with pytest.raises(UnsupportedCanonicalEncodingError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_encoded_plan_integrity_rejects_bad_requirement_shape() -> None:
    enc = dict(encode_sealed_plan(plan()))
    enc["active_field_requirements"] = "notalist"
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_encoded_plan_integrity_rejects_duplicate_apply() -> None:
    enc = dict(encode_sealed_plan(plan()))
    ops = list(enc["ordered_operations"])
    enc["ordered_operations"] = [*ops, ops[1]]  # APPLY f_name 중복
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_encoded_plan_integrity_rejects_unknown_op_code() -> None:
    enc = dict(encode_sealed_plan(plan()))
    ops = list(enc["ordered_operations"])
    enc["ordered_operations"] = [*ops, {"op": "WAT"}]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_encoded_plan_integrity_rejects_bad_remove_operand() -> None:
    enc = dict(encode_sealed_plan(plan()))
    ops = list(enc["ordered_operations"])
    enc["ordered_operations"] = [{"op": "REMOVE_OPTION", "slot_id": "s1", "option_id": ""},
                                 ops[1], ops[2]]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_decode_rejects_readdressed_malformed_plan() -> None:
    # content-address 는 맞지만 구조가 깨진 record 를 decode 가 거절한다(hash 일치 ≠ 유효 Plan).
    from hwpxfiller.application import stored_execution_plan as sep

    enc = dict(encode_sealed_plan(plan()))
    ops = list(enc["ordered_operations"])
    enc["ordered_operations"] = [ops[1], ops[0], ops[2]]
    digest = canonical_execution_digest(enc)
    record_dict = {
        "plan_semantic_digest": digest, "semantic_payload": enc,
        "dependency_set": {f.name: "x" for f in dataclasses.fields(PlanDependencySet)},
        "first_sealed_provenance": {"first_sealed_at": "t0", "first_sealed_by_request_id": "r0"},
    }
    with pytest.raises(ExecutionPlanIntegrityError):
        sep._decode_plan_record(record_dict)


def test_p2_6_stored_payload_is_deeply_immutable() -> None:
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=plan(), evidence=complete_evidence())
    record = next(iter(agg.plans_by_semantic_digest.values()))
    with pytest.raises(TypeError):
        record.semantic_payload_encoded["plan_schema_version"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        record.semantic_payload_encoded["execution_basis"]["work_authority_id"] = "x"  # type: ignore[index]


def test_p2_7_decode_rejects_mismatched_compilation_key() -> None:
    p = plan()
    agg = _publish(empty_aggregate("work-1", "ws-1"), request_id="r1",
                      a_plan=p, evidence=complete_evidence())
    content = encode_aggregate(agg)
    content["compilation_map"][0]["key_digest"] = "sha256:not-the-real-key"
    with pytest.raises(ExecutionPlanCompilationIntegrityError):
        decode_aggregate(content, "work-1")








# ─── outcome↔evidence 교차검증 나머지 분기 + operation 구조 분기 ────────────────────────










def test_p1_5_operation_structure_requirement_missing_field_id() -> None:
    enc = dict(encode_sealed_plan(plan()))
    enc["active_field_requirements"] = [{"no": "id"}]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_operation_structure_duplicate_requirement_field() -> None:
    enc = dict(encode_sealed_plan(plan()))
    reqs = list(enc["active_field_requirements"])
    enc["active_field_requirements"] = [reqs[0], dict(reqs[0])]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)


def test_p1_5_operation_structure_requirement_apply_set_mismatch() -> None:
    enc = dict(encode_sealed_plan(plan()))
    reqs = list(enc["active_field_requirements"])
    enc["active_field_requirements"] = [*reqs, {"field_id": "f_extra"}]
    with pytest.raises(ExecutionPlanIntegrityError):
        verify_encoded_plan_integrity(enc)
