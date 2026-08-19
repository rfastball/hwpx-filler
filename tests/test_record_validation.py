"""S5-12(#708) ValidateDataRecordAgainstPlan·ValidatedDataRecord·immutable VDR ref.

exact logical text(SOURCE/CONSTANT/INTENTIONAL_BLANK)·required missing/null/blank blocker·Plan 결속·
requirement completeness·values-not-in-Plan-identity·content-addressed retention 을 본다.
"""

from __future__ import annotations

import dataclasses

import pytest

from hwpxfiller.application.execution_capture import (
    MATERIALIZATION_BASE_CONTRACT_ID,
    EffectiveSelectionBasis,
    ExactTemplateExecutionBasis,
)
from hwpxfiller.application.execution_compilation import (
    ConstantValue,
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
    ExecutionBasis,
    build_execution_contract_set,
    build_sealed_plan,
    execution_basis_digest,
    plan_semantic_digest,
)
from hwpxfiller.application.execution_contract_semantics import ExecutionContractSemantics
from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue
from hwpxfiller.application.record_validation import (
    PLAN_INTEGRITY_ERROR,
    RAW_RECORD_INTEGRITY_ERROR,
    RECORD_BLANK_POLICY_VIOLATION,
    RECORD_EXPLICIT_NULL_NOT_ALLOWED,
    RECORD_REQUIRED_VALUE_MISSING,
    RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR,
    RECORD_REVIEW_EVIDENCE_STALE,
    RECORD_REVIEW_REQUIRED,
    RECORD_VALUE_TYPE_INVALID,
    UNSUPPORTED_BINDING_VALUE_CONTRACT,
    UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
    UNSUPPORTED_RAW_RECORD_CONTRACT,
    UNSUPPORTED_RECORD_REVIEW_CONTRACT,
    UNSUPPORTED_RECORD_VALIDATION_CONTRACT,
    UNSUPPORTED_SOURCE_SCHEMA_CONTRACT,
    ImmutableVdrStore,
    CurrentValidatedDataRecord,
    RecordValidationBlocked,
    RecordValidationContextError,
    ValidatedDataRecord,
    ValidatedRecordIntegrityError,
    VdrRetentionError,
    validate_data_record_against_plan,
    validate_data_record_against_current_value,
    validate_data_records_against_current_value,
    verify_validated_record_completeness,
)
from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest
from hwpxfiller.domain.field_binding import (
    BOOLEAN,
    DECIMAL,
    EXACT_TEXT,
    ExactText,
)
from hwpxfiller.domain.raw_data_record import (
    RawRecordCaptureProvenance,
    SourceBoolean,
    SourceDecimal,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
    build_record_review_evidence,
)

_POLICY_ID = "document-content-value/v1"
_THEOREM = theorem_evidence_digest(THEOREM_EVIDENCE_V1)
_PROV = RawRecordCaptureProvenance(
    source_adapter_contract_id="excel-adapter/v1", captured_at="2026-01-01T00:00:00+09:00"
)


# ─── Plan builders(real value types) ────────────────────────────────────────────────────
def _rules():
    return (
        EffectiveFieldBindingRule("f_name", "SOURCE", FromSource("name", EXACT_TEXT, None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_amount", "SOURCE", FromSource("amount", DECIMAL, None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_flag", "SOURCE", FromSource("flag", BOOLEAN, None, _POLICY_ID)),
        EffectiveFieldBindingRule(
            "f_const", "CONSTANT", ConstantValue(ExactText("보증금"), None, _POLICY_ID)
        ),
        EffectiveFieldBindingRule("f_blank", "INTENTIONAL_BLANK", IntentionalBlank()),
    )


def _contracts(**over):
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
        composition_theorem_evidence_manifest_digest=_THEOREM,
    )
    kw.update(over)
    return build_execution_contract_set(**kw)


def _basis(**over):
    rules = _rules()
    keys = ("amount", "flag", "name")
    binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=rules,
        active_binding_digest=active_binding_digest(rules),
        required_source_keys=tuple(sorted(keys, key=lambda k: k.encode("utf-8"))),
        required_source_key_set_digest=required_source_key_set_digest(keys),
    )
    kw = dict(
        workspace_instance_id="ws-1",
        work_authority_id="work-1",
        qualification_profile_semantic_digest="sha256:qual",
        template=ExactTemplateExecutionBasis(
            execution_base_kind="APPLIED_TEMPLATE_CANDIDATE",
            materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
            work_authority_id="work-1",
            template_application_id="app-1",
            exact_content_digest="sha256:aaaa",
            canonical_blob_reference="blob://x",
        ),
        contracts=_contracts(),
        selection=EffectiveSelectionBasis(
            slot_mode="SLOTLESS",
            work_id="work-1",
            template_application_id="app-1",
            selection_semantic_contract_id="slot-selection/v1",
            template_structure_digest="sha256:struct",
            effective_selection_digest="sha256:eff",
            declared_selection_digest="sha256:decl",
        ),
        field_binding=binding,
    )
    kw.update(over)
    return ExecutionBasis(**kw)


def _plan(basis=None):
    rules = _rules()
    requirements = [
        {
            "field_id": r.field_id,
            "expected_active_occurrence_count": 1,
            "value_expression": encode_value_expression(r.value_expression),
        }
        for r in rules
    ]
    operations = [
        {"op": "APPLY_FIELD_BINDING", "field_id": r.field_id} for r in rules
    ]
    return build_sealed_plan(
        execution_basis=basis or _basis(),
        active_field_requirements=requirements,
        ordered_operations=operations,
        plan_schema_version="hwpx-execution-plan/v1",
    )


def _snapshot(pairs=None, *, identity="rec-1"):
    pairs = pairs if pairs is not None else [
        ("name", SourceText("홍길동")),
        ("amount", SourceDecimal("1500.00")),
        ("flag", SourceBoolean(True)),
        ("extra", SourceText("unused")),  # schema 밖 key 도 보존(무영향)
    ]
    return build_raw_record_snapshot(
        source_schema_keys=[k for k, _ in pairs],
        source_values=pairs,
        record_identity=identity,
        capture_provenance=_PROV,
    )


def _current_plan() -> SealedExecutionPlanValue:
    legacy = _plan()
    basis = legacy.execution_basis
    return SealedExecutionPlanValue(
        qualification_profile_id="profile-1",
        template_application_id=basis.template.template_application_id,
        contract_semantics=ExecutionContractSemantics.from_contract_set(basis.contracts),
        exact_template_execution_basis=basis.template,
        effective_selection_basis=basis.selection,
        effective_field_binding_basis=basis.field_binding,
        active_field_requirements=legacy.active_field_requirements,
        ordered_operations=legacy.ordered_operations,
        plan_schema_version=legacy.plan_schema_version,
        canonical_encoding_version=legacy.canonical_encoding_version,
    )


def _validate(plan=None, snapshot=None, **over):
    return validate_data_record_against_plan(
        plan=plan or _plan(),
        snapshot=snapshot or _snapshot(),
        validated_at="2026-01-01T00:00:00+09:00",
        **over,
    )


# ─── exact logical text ──────────────────────────────────────────────────────────────────
def test_current_value_validator_has_no_legacy_plan_identity_or_review_authority() -> None:
    result = validate_data_record_against_current_value(
        plan=_current_plan(), snapshot=_snapshot(), validated_at="now"
    )
    assert isinstance(result, CurrentValidatedDataRecord)
    assert not hasattr(result, "plan_semantic_digest")
    assert not hasattr(result, "execution_basis_digest")
    assert result.validation_provenance.record_review_evidence_refs == ()

    import inspect

    assert set(inspect.signature(validate_data_record_against_current_value).parameters) == {
        "plan",
        "snapshot",
        "validated_at",
    }


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        (
            [("amount", SourceDecimal("1")), ("flag", SourceBoolean(True))],
            RECORD_REQUIRED_VALUE_MISSING,
        ),
        (
            [("name", SourceNull()), ("amount", SourceDecimal("1")), ("flag", SourceBoolean(True))],
            RECORD_EXPLICIT_NULL_NOT_ALLOWED,
        ),
        (
            [
                ("name", SourceText("ok")),
                ("amount", SourceText("1")),
                ("flag", SourceBoolean(True)),
            ],
            RECORD_VALUE_TYPE_INVALID,
        ),
        (
            [
                ("name", SourceText(" ")),
                ("amount", SourceDecimal("1")),
                ("flag", SourceBoolean(True)),
            ],
            RECORD_BLANK_POLICY_VIOLATION,
        ),
    ],
)
def test_current_value_validator_preserves_exact_blocker_distinctions(pairs, expected: str) -> None:
    result = validate_data_record_against_current_value(
        plan=_current_plan(), snapshot=_snapshot(pairs), validated_at="now"
    )
    assert isinstance(result, RecordValidationBlocked)
    assert expected in {blocker.code for blocker in result.blockers}


def test_current_batch_shares_one_validation_basis_value() -> None:
    results = validate_data_records_against_current_value(
        plan=_current_plan(),
        snapshots=(_snapshot(identity='rec-1'), _snapshot(identity='rec-2')),
        validated_at='now',
    )
    first, second = results
    assert isinstance(first, CurrentValidatedDataRecord)
    assert isinstance(second, CurrentValidatedDataRecord)
    assert first.validation_basis is second.validation_basis


def test_current_vdr_basis_ignores_non_validation_execution_meaning() -> None:
    plan = _current_plan()
    other_contracts = dataclasses.replace(
        plan.contract_semantics, materialization_contract_id="materialization/v2"
    )
    other = dataclasses.replace(
        plan,
        contract_semantics=other_contracts,
        ordered_operations=tuple(reversed(plan.ordered_operations)),
    )
    a = validate_data_record_against_current_value(
        plan=plan, snapshot=_snapshot(), validated_at="a"
    )
    b = validate_data_record_against_current_value(
        plan=other, snapshot=_snapshot(), validated_at="b"
    )
    assert isinstance(a, CurrentValidatedDataRecord)
    assert isinstance(b, CurrentValidatedDataRecord)
    assert plan != other
    assert a.validation_basis == b.validation_basis
    assert a.document_values_in_order() == b.document_values_in_order()


def test_happy_path_exact_logical_text_all_kinds() -> None:
    vdr = _validate()
    assert isinstance(vdr, ValidatedDataRecord)
    values = dict(vdr.document_values_in_order())
    assert values == {
        "f_name": "홍길동",       # SOURCE EXACT_TEXT
        "f_amount": "1500.00",   # SOURCE DECIMAL — literal 보존(float 아님)
        "f_flag": "true",        # SOURCE BOOLEAN — canonical lexical
        "f_const": "보증금",      # CONSTANT
        "f_blank": "",           # INTENTIONAL_BLANK — exact empty logical text
    }


def test_source_text_no_implicit_trim() -> None:
    snap = _snapshot([
        ("name", SourceText("  spaced  ")),
        ("amount", SourceDecimal("1")),
        ("flag", SourceBoolean(False)),
    ])
    vdr = _validate(snapshot=snap)
    assert isinstance(vdr, ValidatedDataRecord)
    assert dict(vdr.document_values_in_order())["f_name"] == "  spaced  "
    assert dict(vdr.document_values_in_order())["f_flag"] == "false"


def test_legacy_strip_policy_strips_whitespace() -> None:
    # 명시 legacy-strip policy 를 쓴 CONSTANT 는 leading/trailing whitespace 를 제거한다(암묵 아님).
    rules = (
        EffectiveFieldBindingRule(
            "f_const",
            "CONSTANT",
            ConstantValue(ExactText("  x  "), None, "document-content-value/legacy-strip-v1"),
        ),
    )
    binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=rules,
        active_binding_digest=active_binding_digest(rules),
        required_source_keys=(),
        required_source_key_set_digest=required_source_key_set_digest(()),
    )
    plan = build_sealed_plan(
        execution_basis=_basis(field_binding=binding),
        active_field_requirements=[{
            "field_id": "f_const",
            "expected_active_occurrence_count": 1,
            "value_expression": encode_value_expression(rules[0].value_expression),
        }],
        ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": "f_const"}],
        plan_schema_version="hwpx-execution-plan/v1",
    )
    vdr = _validate(plan=plan, snapshot=_snapshot([("name", SourceText("unused"))]))
    assert isinstance(vdr, ValidatedDataRecord)
    assert dict(vdr.document_values_in_order())["f_const"] == "x"


def test_document_value_is_logical_unescaped_text() -> None:
    snap = _snapshot([
        ("name", SourceText("a<b>&\"'")),  # XML 특수문자가 escaping 없이 그대로.
        ("amount", SourceDecimal("1")),
        ("flag", SourceBoolean(True)),
    ])
    vdr = _validate(snapshot=snap)
    assert dict(vdr.document_values_in_order())["f_name"] == "a<b>&\"'"


# ─── required missing/null/blank/type blockers ───────────────────────────────────────────
def test_missing_required_value_blocks() -> None:
    snap = _snapshot([("amount", SourceDecimal("1")), ("flag", SourceBoolean(True))])
    res = _validate(snapshot=snap)
    assert isinstance(res, RecordValidationBlocked)
    codes = {(b.code, b.field_id) for b in res.blockers}
    assert (RECORD_REQUIRED_VALUE_MISSING, "f_name") in codes


def test_explicit_null_blocks() -> None:
    snap = _snapshot([
        ("name", SourceNull()),
        ("amount", SourceDecimal("1")),
        ("flag", SourceBoolean(True)),
    ])
    res = _validate(snapshot=snap)
    assert isinstance(res, RecordValidationBlocked)
    assert (RECORD_EXPLICIT_NULL_NOT_ALLOWED, "f_name") in {
        (b.code, b.field_id) for b in res.blockers
    }


@pytest.mark.parametrize("text", ["", " ", "\t\n"])
def test_blank_source_text_blocks(text: str) -> None:
    snap = _snapshot([
        ("name", SourceText(text)),
        ("amount", SourceDecimal("1")),
        ("flag", SourceBoolean(True)),
    ])
    res = _validate(snapshot=snap)
    assert isinstance(res, RecordValidationBlocked)
    assert (RECORD_BLANK_POLICY_VIOLATION, "f_name") in {
        (b.code, b.field_id) for b in res.blockers
    }


def test_type_mismatch_blocks() -> None:
    snap = _snapshot([
        ("name", SourceText("ok")),
        ("amount", SourceText("not-a-decimal")),  # DECIMAL 요구 vs EXACT_TEXT
        ("flag", SourceBoolean(True)),
    ])
    res = _validate(snapshot=snap)
    assert isinstance(res, RecordValidationBlocked)
    assert (RECORD_VALUE_TYPE_INVALID, "f_amount") in {
        (b.code, b.field_id) for b in res.blockers
    }


def test_multiple_blockers_deterministic_plan_order() -> None:
    snap = _snapshot([("flag", SourceBoolean(True))])  # name·amount 둘 다 MISSING
    res = _validate(snapshot=snap)
    assert isinstance(res, RecordValidationBlocked)
    # Plan requirement 순서(f_name 먼저, f_amount 다음)로 정렬.
    fields = [b.field_id for b in res.blockers]
    assert fields == ["f_name", "f_amount"]


# ─── raw row 재조회 0(frozen snapshot 만 읽는다) ──────────────────────────────────────────
def test_validation_reads_only_frozen_snapshot() -> None:
    snap = _validate().semantic_payload_encoded  # noqa: F841 - 아래 대조용 아님
    # 서비스 signature 는 live row callback 을 받지 않는다 — snapshot 만 인자.
    import inspect

    sig = inspect.signature(validate_data_record_against_plan)
    assert set(sig.parameters) == {
        "plan",
        "snapshot",
        "review_evidence",
        "record_review_required",
        "validated_at",
    }


# ─── Plan 결속·completeness ───────────────────────────────────────────────────────────────
def test_vdr_binds_plan_basis_contract() -> None:
    plan = _plan()
    vdr = _validate(plan=plan)
    p = vdr.semantic_payload_encoded
    assert p["plan_semantic_digest"] == plan_semantic_digest(plan)
    assert p["execution_basis_digest"] == execution_basis_digest(plan.execution_basis)
    assert p["record_validation_contract_id"] == "record-validation/v1"
    assert p["document_value_resolution_contract_id"] == "document-content-value/v1"
    verify_validated_record_completeness(vdr, plan)


def test_requirement_sequence_matches_plan_order_exactly() -> None:
    plan = _plan()
    vdr = _validate(plan=plan)
    vdr_fields = [f for f, _ in vdr.document_values_in_order()]
    plan_fields = [r["field_id"] for r in plan.active_field_requirements]
    assert vdr_fields == plan_fields


def test_completeness_rejects_missing_duplicate_additional_order_mismatch() -> None:
    plan = _plan()
    vdr = _validate(plan=plan)
    base = dict(vdr.semantic_payload_encoded)
    rvs = [dict(x) for x in base["resolved_requirement_values"]]

    def _mutant(new_rvs):
        payload = dict(base)
        payload["resolved_requirement_values"] = new_rvs
        from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest

        return ValidatedDataRecord(
            validated_record_digest=canonical_execution_digest(payload),
            semantic_payload_encoded=payload,
            validation_provenance=vdr.validation_provenance,
        )

    # missing.
    with pytest.raises(ValidatedRecordIntegrityError):
        verify_validated_record_completeness(_mutant(rvs[:-1]), plan)
    # additional/duplicate.
    with pytest.raises(ValidatedRecordIntegrityError):
        verify_validated_record_completeness(_mutant(rvs + [rvs[0]]), plan)
    # order mismatch.
    swapped = [rvs[1], rvs[0]] + rvs[2:]
    with pytest.raises(ValidatedRecordIntegrityError):
        verify_validated_record_completeness(_mutant(swapped), plan)


def test_completeness_rejects_plan_and_contract_binding_mismatch() -> None:
    from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest

    plan = _plan()
    vdr = _validate(plan=plan)
    base = dict(vdr.semantic_payload_encoded)

    def _mutant(**over):
        payload = dict(base)
        payload.update(over)
        return ValidatedDataRecord(
            validated_record_digest=canonical_execution_digest(payload),
            semantic_payload_encoded=payload,
            validation_provenance=vdr.validation_provenance,
        )

    for over in (
        {"plan_semantic_digest": "sha256:other"},
        {"execution_basis_digest": "sha256:other"},
        {"record_validation_contract_id": "record-validation/v9"},
        {"document_value_resolution_contract_id": "document-content-value/v9"},
    ):
        with pytest.raises(ValidatedRecordIntegrityError):
            verify_validated_record_completeness(_mutant(**over), plan)

    # document_value 가 logical text(str) 가 아니면 거절.
    bad = [dict(x) for x in base["resolved_requirement_values"]]
    bad[0]["document_value"] = 123
    with pytest.raises(ValidatedRecordIntegrityError):
        verify_validated_record_completeness(
            _mutant(resolved_requirement_values=bad), plan
        )


def test_tampered_vdr_digest_rejected() -> None:
    plan = _plan()
    vdr = _validate(plan=plan)
    tampered = dataclasses.replace(vdr, validated_record_digest="sha256:wrong")
    with pytest.raises(ValidatedRecordIntegrityError):
        verify_validated_record_completeness(tampered, plan)


# ─── values NOT in Plan identity ─────────────────────────────────────────────────────────
def test_actual_values_do_not_enter_plan_identity() -> None:
    plan = _plan()
    d1 = plan_semantic_digest(plan)
    # 완전히 다른 row 값으로 VDR 두 개 — Plan digest 는 불변.
    a = _validate(plan=plan, snapshot=_snapshot([
        ("name", SourceText("A")), ("amount", SourceDecimal("1")), ("flag", SourceBoolean(True))]))
    b = _validate(plan=plan, snapshot=_snapshot([
        ("name", SourceText("ZZZ")), ("amount", SourceDecimal("999")), ("flag", SourceBoolean(False))]))
    assert plan_semantic_digest(plan) == d1
    # 다른 값 → 다른 VDR digest(값은 VDR 에만 산다).
    assert a.validated_record_digest != b.validated_record_digest
    assert a.plan_semantic_digest == b.plan_semantic_digest == d1


def test_validation_provenance_excluded_from_vdr_identity() -> None:
    plan = _plan()
    a = validate_data_record_against_plan(
        plan=plan, snapshot=_snapshot(), validated_at="2026-01-01T00:00:00+09:00"
    )
    b = validate_data_record_against_plan(
        plan=plan, snapshot=_snapshot(), validated_at="2099-12-31T23:59:59+09:00"
    )
    assert a.validated_record_digest == b.validated_record_digest


# ─── review evidence ─────────────────────────────────────────────────────────────────────
def _evidence(plan, snapshot, **over):
    kw = dict(
        workspace_instance_id="ws-1",
        work_authority_id="work-1",
        plan_semantic_digest=plan_semantic_digest(plan),
        raw_record_digest=snapshot.raw_record_digest,
        record_identity=snapshot.record_identity,
        actor_binding="user:alice",
        reviewed_at="2026-01-01T00:00:00+09:00",
    )
    kw.update(over)
    return build_record_review_evidence(**kw)


def test_review_required_but_absent_blocks() -> None:
    res = _validate(record_review_required=True)
    assert isinstance(res, RecordValidationBlocked)
    assert RECORD_REVIEW_REQUIRED in {b.code for b in res.blockers}


def test_matching_review_evidence_accepted() -> None:
    plan, snap = _plan(), _snapshot()
    ev = _evidence(plan, snap)
    vdr = validate_data_record_against_plan(
        plan=plan, snapshot=snap, review_evidence=ev,
        record_review_required=True, validated_at="2026-01-01T00:00:00+09:00",
    )
    assert isinstance(vdr, ValidatedDataRecord)
    assert vdr.validation_provenance.record_review_evidence_refs == (ev.review_basis_digest,)


def test_review_evidence_for_other_plan_is_stale() -> None:
    plan, snap = _plan(), _snapshot()
    other = _evidence(plan, snap, plan_semantic_digest="sha256:other-plan")
    # tamper 가 아니라 다른 Plan 에 올바르게 결속된 evidence(basis 재계산 통과) → stale blocker.
    res = validate_data_record_against_plan(
        plan=plan, snapshot=snap, review_evidence=other, validated_at="t",
    )
    assert isinstance(res, RecordValidationBlocked)
    assert RECORD_REVIEW_EVIDENCE_STALE in {b.code for b in res.blockers}


def test_tampered_review_evidence_is_context_error() -> None:
    plan, snap = _plan(), _snapshot()
    ev = _evidence(plan, snap)
    tampered = dataclasses.replace(ev, record_identity="rec-swapped")  # basis digest 불일치
    res = validate_data_record_against_plan(
        plan=plan, snapshot=snap, review_evidence=tampered, validated_at="t",
    )
    assert isinstance(res, RecordValidationContextError)
    assert res.code == RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR


# ─── 미지원 contract·format(context error, user-fixable 아님) ─────────────────────────────
def test_unsupported_raw_record_contract_is_context_error() -> None:
    plan = _plan(_basis(contracts=_contracts(raw_record_contract_id="raw-record/v2")))
    res = _validate(plan=plan)
    assert isinstance(res, RecordValidationContextError)
    assert res.code == UNSUPPORTED_RAW_RECORD_CONTRACT


def test_format_code_unsupported_is_context_error() -> None:
    rules = (
        EffectiveFieldBindingRule(
            "f_name", "SOURCE", FromSource("name", EXACT_TEXT, "UPPER", _POLICY_ID)
        ),
    )
    binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=rules,
        active_binding_digest=active_binding_digest(rules),
        required_source_keys=("name",),
        required_source_key_set_digest=required_source_key_set_digest(("name",)),
    )
    basis = _basis(field_binding=binding)
    plan = build_sealed_plan(
        execution_basis=basis,
        active_field_requirements=[{
            "field_id": "f_name",
            "expected_active_occurrence_count": 1,
            "value_expression": encode_value_expression(rules[0].value_expression),
        }],
        ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": "f_name"}],
        plan_schema_version="hwpx-execution-plan/v1",
    )
    res = _validate(plan=plan, snapshot=_snapshot([("name", SourceText("x"))]))
    assert isinstance(res, RecordValidationContextError)
    assert res.code == UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT


# ─── immutable VDR ref / retention ───────────────────────────────────────────────────────
def test_vdr_store_content_addressed_resolve_and_idempotent() -> None:
    store = ImmutableVdrStore()
    vdr = _validate()
    ref = store.put(vdr)
    assert ref == vdr.validated_record_digest
    assert store.put(vdr) == ref  # create-once idempotent
    resolved = store.resolve(ref)
    assert resolved.canonical_payload_bytes == vdr.canonical_payload_bytes


def test_vdr_store_rejects_tampered_and_unknown_ref() -> None:
    store = ImmutableVdrStore()
    vdr = _validate()
    tampered = dataclasses.replace(vdr, validated_record_digest="sha256:wrong")
    with pytest.raises(VdrRetentionError):
        store.put(tampered)  # digest ≠ bytes 재계산
    with pytest.raises(VdrRetentionError):
        store.resolve("sha256:does-not-exist")


# ─── Codex 리뷰: 미지원 version/contract 는 v1 로 풀지 않고 fail-closed (findings 1~6·9) ────────
def _ctx(res):
    assert isinstance(res, RecordValidationContextError), res
    return res.code


def test_unknown_plan_schema_rejected_not_treated_as_v1() -> None:
    # finding 1: plan_schema_version 을 자기 자신으로 검증하던 tautology 제거 → v999 는 거절.
    plan = build_sealed_plan(
        execution_basis=_basis(),
        active_field_requirements=[{
            "field_id": r.field_id,
            "expected_active_occurrence_count": 1,
            "value_expression": encode_value_expression(r.value_expression),
        } for r in _rules()],
        ordered_operations=[
            {"op": "APPLY_FIELD_BINDING", "field_id": r.field_id} for r in _rules()
        ],
        plan_schema_version="hwpx-execution-plan/v999",
    )
    assert _ctx(_validate(plan=plan)) == PLAN_INTEGRITY_ERROR


def test_unknown_record_review_contract_rejected_even_without_evidence() -> None:
    # finding 2: record-review/v999 를 optional-evidence early return 전에 거절한다.
    plan = _plan(_basis(contracts=_contracts(record_review_contract_id="record-review/v999")))
    assert _ctx(_validate(plan=plan)) == UNSUPPORTED_RECORD_REVIEW_CONTRACT


def test_unsupported_review_policy_basis_rejected() -> None:
    # finding 3: self-consistent NOT_REVIEWED basis 를 examination 으로 받지 않는다.
    plan, snap = _plan(), _snapshot()
    ev = build_record_review_evidence(
        workspace_instance_id="ws-1", work_authority_id="work-1",
        plan_semantic_digest=plan_semantic_digest(plan),
        raw_record_digest=snap.raw_record_digest, record_identity=snap.record_identity,
        review_policy_basis="NOT_REVIEWED",
        actor_binding="user:alice", reviewed_at="t",
    )
    res = validate_data_record_against_plan(
        plan=plan, snapshot=snap, review_evidence=ev,
        record_review_required=True, validated_at="t",
    )
    assert _ctx(res) == UNSUPPORTED_RECORD_REVIEW_CONTRACT


def test_unknown_blank_policy_rejected_not_treated_as_write_empty() -> None:
    # finding 4: INTENTIONAL_BLANK 의 exact_blank_policy 를 확인한다(CUSTOM → 거절).
    rules = (
        EffectiveFieldBindingRule(
            "f_blank", "INTENTIONAL_BLANK", IntentionalBlank(exact_blank_policy="CUSTOM")
        ),
    )
    binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=rules,
        active_binding_digest=active_binding_digest(rules),
        required_source_keys=(),
        required_source_key_set_digest=required_source_key_set_digest(()),
    )
    plan = build_sealed_plan(
        execution_basis=_basis(field_binding=binding),
        active_field_requirements=[{
            "field_id": "f_blank",
            "expected_active_occurrence_count": 1,
            "value_expression": encode_value_expression(rules[0].value_expression),
        }],
        ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": "f_blank"}],
        plan_schema_version="hwpx-execution-plan/v1",
    )
    assert _ctx(_validate(plan=plan, snapshot=_snapshot([("name", SourceText("x"))]))) == (
        UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT
    )


def test_unknown_vdr_record_schema_version_rejected() -> None:
    # finding 5: record_schema_version=v999 를 rehash 로 통과시키지 않는다.
    plan = _plan()
    vdr = _validate(plan=plan)
    payload = dict(vdr.semantic_payload_encoded)
    payload["record_schema_version"] = "validated-record/v999"
    mutant = ValidatedDataRecord(
        validated_record_digest=canonical_execution_digest(payload),
        semantic_payload_encoded=payload,
        validation_provenance=vdr.validation_provenance,
    )
    with pytest.raises(ValidatedRecordIntegrityError):
        verify_validated_record_completeness(mutant, plan)


def test_unknown_source_schema_and_binding_value_contract_rejected() -> None:
    # finding 6: source-schema/v999·binding-value/v999 를 v1 의미로 해석하지 않는다.
    p_ss = _plan(_basis(contracts=_contracts(source_schema_contract_id="source-schema/v999")))
    assert _ctx(_validate(plan=p_ss)) == UNSUPPORTED_SOURCE_SCHEMA_CONTRACT
    p_bv = _plan(_basis(contracts=_contracts(binding_value_contract_id="binding-value/v999")))
    assert _ctx(_validate(plan=p_bv)) == UNSUPPORTED_BINDING_VALUE_CONTRACT


def test_unknown_record_validation_contract_rejected() -> None:
    plan = _plan(
        _basis(contracts=_contracts(record_validation_contract_id="record-validation/v999"))
    )
    assert _ctx(_validate(plan=plan)) == UNSUPPORTED_RECORD_VALIDATION_CONTRACT


def test_divergent_restored_snapshot_values_returns_context_error() -> None:
    # findings 7·8: sealed payload 와 갈린 _values 는 잘못된 text 를 내지 않고 fail-closed context error.
    snap = _snapshot()
    diverged = dataclasses.replace(
        snap, _values={**dict(snap._values), "name": SourceText("TAMPERED")}
    )
    # digest 는 원본 그대로라 payload 와 lookup 이 갈린다.
    assert _ctx(_validate(snapshot=diverged)) == RAW_RECORD_INTEGRITY_ERROR


def test_tampered_plan_basis_integrity_returns_context_error() -> None:
    # finding 9: ExecutionBasisIntegrityError 가 결과 union 밖으로 새지 않고 PLAN_INTEGRITY_ERROR 로 닫힌다.
    bad_binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=_rules(),
        active_binding_digest="sha256:wrong",  # rule 재계산과 불일치.
        required_source_keys=("amount", "flag", "name"),
        required_source_key_set_digest=required_source_key_set_digest(("amount", "flag", "name")),
    )
    plan = _plan(_basis(field_binding=bad_binding))
    assert _ctx(_validate(plan=plan)) == PLAN_INTEGRITY_ERROR
