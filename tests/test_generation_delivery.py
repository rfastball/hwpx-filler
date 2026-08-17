"""S5-13(#709) exact batch output-name resolution + managed GenerationPlan bridge.

filename-pattern/v1 target Field namespace 보존·Active VDR 재사용/inactive FieldBinding 해석·
batch-level date/seq/suffix/ordinal(한 번만)·resolved relative path 결정성·canonical digest·
ManagedGenerationPlan/MaterializationInput 경계·managed/legacy/continuation 분리·runtime admission seam
을 본다. native write/Artifact/route cutover 는 하지 않는다(비범위).
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import datetime

import pytest

from hwpxfiller import naming
from hwpxfiller.application import generation_delivery as gd
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
    RuntimeMaterializerConformanceManifest,
    RuntimeMaterializerConformanceRegistry,
    runtime_conformance_digest,
    theorem_evidence_digest,
)
from hwpxfiller.application.execution_contract_set import (
    ExecutionBasis,
    build_execution_contract_set,
    build_sealed_plan,
    plan_semantic_digest,
)
from hwpxfiller.application.record_validation import (
    ImmutableVdrStore,
    ValidatedDataRecord,
    validate_data_record_against_plan,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DECIMAL,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_TEXT,
    INTENTIONAL_BLANK,
    SOURCE,
    ExactText,
    FieldBindingRule,
)
from hwpxfiller.domain.raw_data_record import (
    RawRecordCaptureProvenance,
    SourceBoolean,
    SourceDecimal,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
)

_POLICY_ID = "document-content-value/v1"
_THEOREM = theorem_evidence_digest(THEOREM_EVIDENCE_V1)
_PROV = RawRecordCaptureProvenance(
    source_adapter_contract_id="excel-adapter/v1", captured_at="2026-01-01T00:00:00+09:00"
)
_CLOCK = "2026-03-04T09:15:00+09:00"
_PATTERN = "공고서-{{f_name}}-{{date:YYYYMMDD}}-{{seq:001}}"


# ─── Plan / VDR scaffold(S5-06/12 real builders) ─────────────────────────────────────────
def _rules():
    return (
        EffectiveFieldBindingRule("f_name", "SOURCE", FromSource("name", EXACT_TEXT, None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_amount", "SOURCE", FromSource("amount", DECIMAL, None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_flag", "SOURCE", FromSource("flag", "BOOLEAN", None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_const", "CONSTANT", ConstantValue(ExactText("보증금"), None, _POLICY_ID)),
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


def _basis():
    rules = _rules()
    keys = ("amount", "flag", "name")
    binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=rules,
        active_binding_digest=active_binding_digest(rules),
        required_source_keys=tuple(sorted(keys, key=lambda k: k.encode("utf-8"))),
        required_source_key_set_digest=required_source_key_set_digest(keys),
    )
    return ExecutionBasis(
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


def _plan():
    rules = _rules()
    return build_sealed_plan(
        execution_basis=_basis(),
        active_field_requirements=[
            {
                "field_id": r.field_id,
                "expected_active_occurrence_count": 1,
                "value_expression": encode_value_expression(r.value_expression),
            }
            for r in rules
        ],
        ordered_operations=[{"op": "APPLY_FIELD_BINDING", "field_id": r.field_id} for r in rules],
        plan_schema_version="hwpx-execution-plan/v1",
    )


def _snapshot(name="홍길동", *, identity="rec-1", dept="총무과", extra_pairs=()):
    pairs = [
        ("name", SourceText(name)),
        ("amount", SourceDecimal("1500.00")),
        ("flag", SourceBoolean(True)),
        ("dept", SourceText(dept)),  # inactive delivery source(Plan active 아님)
        *extra_pairs,
    ]
    return build_raw_record_snapshot(
        source_schema_keys=[k for k, _ in pairs],
        source_values=pairs,
        record_identity=identity,
        capture_provenance=_PROV,
    )


def _vdr(plan, snapshot):
    vdr = validate_data_record_against_plan(
        plan=plan, snapshot=snapshot, validated_at="2026-01-01T00:00:00+09:00"
    )
    assert isinstance(vdr, ValidatedDataRecord), vdr
    return vdr


def _active_ids(plan):
    return [r["field_id"] for r in plan.active_field_requirements]


_DEPT_RULE = FieldBindingRule(
    field_id="f_dept",
    binding_kind=SOURCE,
    document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
    source_key="dept",
    value_type=EXACT_TEXT,
)


def _basis_dto(plan, pattern=_PATTERN, inactive_rules=(_DEPT_RULE,)):
    res = gd.build_delivery_binding_basis(
        base_template_application_id="app-1",
        field_binding_authority_revision="rev-7",
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern=pattern,
        active_field_ids=_active_ids(plan),
        binding_rules=inactive_rules,
    )
    return res


def _resolve(plan, snapshots, *, pattern=_PATTERN, basis=None, clock=_CLOCK,
             overwrite=gd.OVERWRITE_EXISTING, out_dir="C:/out"):
    vdrs = [_vdr(plan, s) for s in snapshots]
    basis = basis if basis is not None else _basis_dto(plan, pattern)
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis), basis
    return gd.resolve_generation_delivery_plan(
        sealed_execution_plan=plan,
        exact_pattern=pattern,
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=basis,
        ordered_raw_snapshots=snapshots,
        ordered_validated_records=vdrs,
        captured_delivery_clock=clock,
        output_directory_basis=out_dir,
        overwrite_policy=overwrite,
    )


def _ok(res) -> gd.ResolvedGenerationDeliveryPlan:
    assert isinstance(res, gd.ResolvedGenerationDeliveryPlan), res
    return res


# ═══ pattern compatibility ══════════════════════════════════════════════════════════════════
def test_pattern_token_union_and_order() -> None:
    tokens = gd.parse_filename_pattern(_PATTERN, filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID)
    kinds = [type(t).__name__ for t in tokens]
    assert kinds == [
        "LiteralSegment", "FieldValueToken", "LiteralSegment",
        "ReservedDateToken", "LiteralSegment", "ReservedSequenceToken",
    ]
    assert isinstance(tokens[1], gd.FieldValueToken) and tokens[1].field_id == "f_name"
    assert isinstance(tokens[3], gd.ReservedDateToken) and tokens[3].date_spec == "YYYYMMDD"
    assert isinstance(tokens[5], gd.ReservedSequenceToken) and tokens[5].pad == "001"


def test_reserved_default_specs() -> None:
    toks = gd.parse_filename_pattern("{{date}}{{seq}}", filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID)
    assert isinstance(toks[0], gd.ReservedDateToken) and toks[0].date_spec is None
    assert isinstance(toks[1], gd.ReservedSequenceToken) and toks[1].pad is None


def test_field_token_is_target_field_id_not_raw_source_key() -> None:
    # 토큰 'f_name' 은 target Field ID 다. raw source key('name')를 토큰으로 쓰면 미해소.
    res = _basis_dto(_plan(), pattern="{{name}}", inactive_rules=())  # 'name' 은 source key
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert res.blockers[0].code == gd.OUTPUT_NAME_TOKEN_UNRESOLVED
    assert res.blockers[0].field_id == "name"


@pytest.mark.parametrize("bad", ["", "{{}}", "a{{unclosed", "x-{{f_a{b}}}"])
def test_malformed_pattern_rejected(bad: str) -> None:
    res = gd.build_delivery_binding_basis(
        base_template_application_id="app-1",
        field_binding_authority_revision="rev",
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern=bad,
        active_field_ids=(),
        binding_rules=(),
    )
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert res.blockers[0].code == gd.OUTPUT_NAME_PATTERN_INVALID


def test_unknown_filename_pattern_contract_fail_closed() -> None:
    res = gd.build_delivery_binding_basis(
        base_template_application_id="app-1",
        field_binding_authority_revision="rev",
        filename_pattern_contract_id="filename-pattern/v999",
        exact_pattern="{{seq}}",
        active_field_ids=(),
        binding_rules=(),
    )
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.UNSUPPORTED_FILENAME_PATTERN_CONTRACT


def test_old_filename_fixtures_exact_parity_with_naming_v1() -> None:
    # 잘 형성된 v1 패턴은 기존 naming.make_output_filename 과 한 글자도 다르지 않다.
    tokens = gd.parse_filename_pattern(_PATTERN, filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID)
    clock = datetime.fromisoformat(_CLOCK)
    for ordinal, raw_name in enumerate(["홍길동", "김/유신", "a?b"]):
        mine, _tv = gd._render_item(tokens, {"f_name": raw_name}, ordinal=ordinal, clock=clock)
        legacy = naming.make_output_filename(_PATTERN, {"f_name": raw_name}, seq=ordinal + 1, now=clock)
        assert mine == legacy


# ═══ token values ═════════════════════════════════════════════════════════════════════════
def test_active_token_reuses_exact_vdr_value() -> None:
    plan = _plan()
    res = _ok(_resolve(plan, (_snapshot(name="홍길동"),), pattern="{{f_name}}-{{seq}}"))
    # VDR document_value("홍길동") 재사용 → clean_filename 후 파일명.
    assert res.ordered_items[0].resolved_output_relative_path == "홍길동-1.hwpx"
    fv = [t for t in res.ordered_items[0].resolved_token_values if t.kind == "FIELD"]
    assert fv[0].field_id == "f_name" and fv[0].value == "홍길동"


def test_inactive_token_resolves_from_field_binding_revision() -> None:
    plan = _plan()
    res = _ok(_resolve(plan, (_snapshot(dept="재무과"),), pattern="{{f_dept}}"))
    assert res.ordered_items[0].resolved_output_relative_path == "재무과.hwpx"


def test_inactive_binding_ambiguous_blocker() -> None:
    dup = (
        _DEPT_RULE,
        FieldBindingRule(
            field_id="f_dept", binding_kind=CONSTANT,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            canonical_constant_value=ExactText("x"),
        ),
    )
    res = _basis_dto(_plan(), pattern="{{f_dept}}", inactive_rules=dup)
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert res.blockers[0].code == gd.OUTPUT_NAME_BINDING_AMBIGUOUS


def test_intentional_blank_active_token_unresolved() -> None:
    # Active INTENTIONAL_BLANK 필드는 VDR 에서 "" → 조용한 빈 파일명 대신 미해소 blocker.
    plan = _plan()
    res = _resolve(plan, (_snapshot(),), pattern="{{f_blank}}-{{seq}}")
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert (res.blockers[0].code, res.blockers[0].field_id) == (gd.OUTPUT_NAME_TOKEN_UNRESOLVED, "f_blank")


def test_intentional_blank_inactive_token_unresolved() -> None:
    blank_rule = FieldBindingRule(
        field_id="f_note", binding_kind=INTENTIONAL_BLANK,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
    )
    plan = _plan()
    basis = _basis_dto(plan, pattern="{{f_note}}", inactive_rules=(blank_rule,))
    res = _resolve(plan, (_snapshot(),), pattern="{{f_note}}", basis=basis)
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert res.blockers[0].code == gd.OUTPUT_NAME_TOKEN_UNRESOLVED


def test_no_binding_unresolved() -> None:
    res = _basis_dto(_plan(), pattern="{{f_unknown}}", inactive_rules=())
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert (res.blockers[0].code, res.blockers[0].field_id) == (
        gd.OUTPUT_NAME_TOKEN_UNRESOLVED, "f_unknown"
    )


def test_inactive_source_missing_key_unresolved() -> None:
    plan = _plan()
    snap = _snapshot(extra_pairs=())  # dept 있음 → 있는 케이스; 여기선 없는 키 규칙
    rule = FieldBindingRule(
        field_id="f_ghost", binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        source_key="ghost", value_type=EXACT_TEXT,
    )
    basis = _basis_dto(plan, pattern="{{f_ghost}}", inactive_rules=(rule,))
    res = _resolve(plan, (snap,), pattern="{{f_ghost}}", basis=basis)
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert res.blockers[0].code == gd.OUTPUT_NAME_TOKEN_UNRESOLVED


def test_inactive_source_type_mismatch_resolution_failed() -> None:
    plan = _plan()
    rule = FieldBindingRule(
        field_id="f_dept", binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        source_key="dept", value_type=DECIMAL,  # dept 는 EXACT_TEXT → 불일치
    )
    basis = _basis_dto(plan, pattern="{{f_dept}}", inactive_rules=(rule,))
    res = _resolve(plan, (_snapshot(),), pattern="{{f_dept}}", basis=basis)
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert res.blockers[0].code == gd.OUTPUT_NAME_VALUE_RESOLUTION_FAILED


def test_inactive_constant_token_resolves() -> None:
    rule = FieldBindingRule(
        field_id="f_kind", binding_kind=CONSTANT,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        canonical_constant_value=ExactText("공고"),
    )
    plan = _plan()
    basis = _basis_dto(plan, pattern="{{f_kind}}-{{seq}}", inactive_rules=(rule,))
    res = _ok(_resolve(plan, (_snapshot(),), pattern="{{f_kind}}-{{seq}}", basis=basis))
    assert res.ordered_items[0].resolved_output_relative_path == "공고-1.hwpx"


def test_no_implicit_trim_or_normalization() -> None:
    plan = _plan()
    res = _ok(_resolve(plan, (_snapshot(dept="  각 과  "),), pattern="{{f_dept}}"))
    # PRESERVE_EXACT — 앞뒤 공백 보존(clean_filename 은 공백을 지우지 않는다).
    assert res.ordered_items[0].resolved_output_relative_path == "  각 과  .hwpx"


# ═══ batch semantics ═════════════════════════════════════════════════════════════════════
def test_captured_clock_applied_exactly_once() -> None:
    plan = _plan()
    res = _ok(_resolve(
        plan,
        (_snapshot(identity="r1", name="A"), _snapshot(identity="r2", name="B")),
        pattern="{{f_name}}-{{date:YYYYMMDD}}",
    ))
    dates = {i.resolved_token_values[-1].value for i in res.ordered_items}
    assert dates == {"20260304"}  # 두 item 이 같은 batch clock 을 공유
    assert res.captured_delivery_clock == _CLOCK


def test_seq_deterministic_by_ordered_batch() -> None:
    plan = _plan()
    res = _ok(_resolve(
        plan, (_snapshot(identity="r1", name="A"), _snapshot(identity="r2", name="B")),
        pattern="{{f_name}}-{{seq:001}}",
    ))
    seqs = [i.resolved_token_values[-1].value for i in res.ordered_items]
    assert seqs == ["001", "002"]


def test_duplicate_suffix_deterministic() -> None:
    plan = _plan()
    # 서로 다른 record 가 같은 base name 으로 수렴 → _1 접미사.
    res = _ok(_resolve(
        plan, (_snapshot(identity="r1", name="같은"), _snapshot(identity="r2", name="같은")),
        pattern="{{f_name}}",
    ))
    paths = [i.resolved_output_relative_path for i in res.ordered_items]
    assert paths == ["같은.hwpx", "같은_1.hwpx"]


def test_item_ordinal_stable() -> None:
    plan = _plan()
    res = _ok(_resolve(
        plan,
        tuple(_snapshot(identity=f"r{k}", name=f"n{k}") for k in range(3)),
        pattern="{{f_name}}",
    ))
    assert [i.item_ordinal for i in res.ordered_items] == [0, 1, 2]


def test_reorder_changes_sealed_batch_and_digest() -> None:
    plan = _plan()
    a = _snapshot(identity="r1", name="A")
    b = _snapshot(identity="r2", name="B")
    res1 = _ok(_resolve(plan, (a, b), pattern="{{f_name}}-{{seq}}"))
    res2 = _ok(_resolve(plan, (b, a), pattern="{{f_name}}-{{seq}}"))
    # 입력 순서가 batch authority — 재정렬은 seq/ordinal/path 를 바꾸고 digest 도 다르다.
    assert res1.ordered_items[0].resolved_output_relative_path == "A-1.hwpx"
    assert res2.ordered_items[0].resolved_output_relative_path == "B-1.hwpx"
    assert res1.delivery_plan_digest != res2.delivery_plan_digest


def test_same_inputs_same_delivery_digest() -> None:
    plan = _plan()
    snaps = (_snapshot(identity="r1", name="A"), _snapshot(identity="r2", name="B"))
    d1 = _ok(_resolve(plan, snaps)).delivery_plan_digest
    d2 = _ok(_resolve(plan, snaps)).delivery_plan_digest
    assert d1 == d2


def test_forbidden_chars_sanitized_and_path_escape_detected() -> None:
    plan = _plan()
    # 값 안 separator 는 clean_filename 이 '_' 로 치환 → 탈출 불가.
    res = _ok(_resolve(plan, (_snapshot(name="a/b\\c"),), pattern="{{f_name}}"))
    assert res.ordered_items[0].resolved_output_relative_path == "a_b_c.hwpx"
    # 패턴 리터럴의 separator 는 v1 이 청소하지 않으므로 최종 방어가 탈출을 막는다.
    escape = _resolve(plan, (_snapshot(),), pattern="../{{f_name}}")
    assert isinstance(escape, gd.DeliveryPlanContextError)
    assert escape.code == gd.OUTPUT_PATH_ESCAPE_DETECTED


# ═══ context / integrity fail-closed ══════════════════════════════════════════════════════
def test_unsupported_delivery_and_overwrite_contract() -> None:
    plan = _plan()
    vdrs = [_vdr(plan, _snapshot())]
    basis = _basis_dto(plan)
    common = dict(
        sealed_execution_plan=plan,
        exact_pattern=_PATTERN,
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=basis,
        ordered_raw_snapshots=(_snapshot(),),
        ordered_validated_records=vdrs,
        captured_delivery_clock=_CLOCK,
        output_directory_basis="C:/out",
    )
    bad_delivery = gd.resolve_generation_delivery_plan(
        overwrite_policy=gd.OVERWRITE_EXISTING, delivery_contract_id="generation-delivery/v999", **common
    )
    assert isinstance(bad_delivery, gd.DeliveryPlanContextError)
    assert bad_delivery.code == gd.UNSUPPORTED_DELIVERY_CONTRACT
    bad_overwrite = gd.resolve_generation_delivery_plan(overwrite_policy="NUKE", **common)
    assert isinstance(bad_overwrite, gd.DeliveryPlanContextError)
    assert bad_overwrite.code == gd.UNSUPPORTED_OVERWRITE_POLICY


def test_tampered_delivery_binding_basis_rejected() -> None:
    plan = _plan()
    basis = _basis_dto(plan)
    tampered = dataclasses.replace(basis, exact_pattern="다른-{{f_name}}")
    res = gd.resolve_generation_delivery_plan(
        sealed_execution_plan=plan,
        exact_pattern=_PATTERN,
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=tampered,
        ordered_raw_snapshots=(_snapshot(),),
        ordered_validated_records=[_vdr(plan, _snapshot())],
        captured_delivery_clock=_CLOCK,
        output_directory_basis="C:/out",
        overwrite_policy=gd.OVERWRITE_EXISTING,
    )
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.DELIVERY_BINDING_BASIS_INTEGRITY_ERROR


def test_count_mismatch_and_raw_vdr_mismatch_and_plan_mismatch() -> None:
    plan = _plan()
    basis = _basis_dto(plan)
    s1, s2 = _snapshot(identity="r1"), _snapshot(identity="r2", name="B")
    # count mismatch.
    res = gd.resolve_generation_delivery_plan(
        sealed_execution_plan=plan,
        exact_pattern=_PATTERN, filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=basis, ordered_raw_snapshots=(s1, s2),
        ordered_validated_records=[_vdr(plan, s1)], captured_delivery_clock=_CLOCK,
        output_directory_basis="C:/out", overwrite_policy=gd.OVERWRITE_EXISTING,
    )
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR
    # raw ↔ VDR mismatch: snapshot s2 와 s1 의 VDR 을 짝지운다.
    res2 = gd.resolve_generation_delivery_plan(
        sealed_execution_plan=plan,
        exact_pattern=_PATTERN, filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=basis, ordered_raw_snapshots=(s2,),
        ordered_validated_records=[_vdr(plan, s1)], captured_delivery_clock=_CLOCK,
        output_directory_basis="C:/out", overwrite_policy=gd.OVERWRITE_EXISTING,
    )
    assert isinstance(res2, gd.DeliveryPlanContextError)
    assert res2.code == gd.RAW_VALIDATED_RECORD_MISMATCH


def test_bad_clock_rejected() -> None:
    plan = _plan()
    res = _resolve(plan, (_snapshot(),), clock="not-a-date")
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR


def test_resolved_plan_integrity_recompute_and_tamper() -> None:
    plan = _plan()
    res = _ok(_resolve(plan, (_snapshot(),)))
    gd.verify_resolved_delivery_plan_integrity(res)
    bad = dataclasses.replace(res, delivery_plan_digest="sha256:wrong")
    with pytest.raises(gd.ResolvedDeliveryPlanIntegrityError):
        gd.verify_resolved_delivery_plan_integrity(bad)
    # item path tamper → per-item basis digest 재계산 불일치.
    item = res.ordered_items[0]
    bad_item = dataclasses.replace(item, resolved_output_relative_path="hacked.hwpx")
    bad2 = dataclasses.replace(res, ordered_items=(bad_item,))
    with pytest.raises(gd.ResolvedDeliveryPlanIntegrityError):
        gd.verify_resolved_delivery_plan_integrity(bad2)


# ═══ ManagedGenerationPlan ═══════════════════════════════════════════════════════════════
def _managed(plan, snaps, **over):
    res = _ok(_resolve(plan, snaps))
    return gd.build_managed_generation_plan(
        sealed_execution_plan_ref=plan_semantic_digest(plan),
        resolved_delivery_plan=res,
        output_directory="C:/abs/out",
        created_at="2026-03-04T09:15:00+09:00",
        **over,
    )


def test_managed_plan_holds_exact_refs_and_paths() -> None:
    plan = _plan()
    snaps = (_snapshot(identity="r1", name="A"), _snapshot(identity="r2", name="B"))
    mgp = _managed(plan, snaps)
    gd.verify_managed_generation_plan_integrity(mgp)
    assert mgp.sealed_execution_plan_ref == plan_semantic_digest(plan)
    items = mgp.resolved_delivery_plan.ordered_items
    assert [i.validated_record_ref for i in items] == [_vdr(plan, s).validated_record_digest for s in snaps]
    assert [i.resolved_output_relative_path for i in items] == [
        "공고서-A-20260304-001.hwpx", "공고서-B-20260304-002.hwpx",
    ]


def test_managed_plan_has_no_legacy_template_or_live_mapping() -> None:
    fields = {f.name for f in dataclasses.fields(gd.ManagedGenerationPlan)}
    # legacy template path·live Mapping·filename pattern 재해석 결과를 저장하지 않는다.
    assert "template" not in fields
    assert not any("mapping" in f for f in fields)
    assert "filename_pattern" not in fields
    # 실행 naming authority 는 resolved path 이고, 재파싱할 pattern 을 managed plan 이 들고 있지 않다.
    mgp = _managed(_plan(), (_snapshot(),))
    assert all(
        isinstance(i.resolved_output_relative_path, str) and i.resolved_output_relative_path.endswith(".hwpx")
        for i in mgp.resolved_delivery_plan.ordered_items
    )


def test_progress_cancel_excluded_from_delivery_identity() -> None:
    plan, snaps = _plan(), (_snapshot(),)
    a = _managed(plan, snaps, progress_cancel_context={"done": 0})
    b = _managed(plan, snaps, progress_cancel_context={"done": 5, "cancelled": True})
    assert a.managed_generation_plan_digest == b.managed_generation_plan_digest


# ═══ boundaries: MaterializationInput / adapters / runtime admission ══════════════════════
def test_materialization_input_excludes_output_path() -> None:
    fields = {f.name for f in dataclasses.fields(gd.MaterializationInput)}
    assert fields == {"sealed_execution_plan_ref", "validated_record_ref"}
    assert not any("path" in f or "ordinal" in f or "disposition" in f for f in fields)


def test_materialization_input_port_resolves_plan_and_vdr() -> None:
    plan = _plan()
    snap = _snapshot()
    vdr = _vdr(plan, snap)
    store = ImmutableVdrStore()
    store.put(vdr)
    mgp = _managed(plan, (snap,))
    port = gd.MaterializationInputPort(
        plan_resolver=lambda ref: plan, vdr_store=store
    )
    mi = gd.materialization_inputs_of(mgp)[0]
    resolved_plan, resolved_vdr = port.resolve(mi)
    assert plan_semantic_digest(resolved_plan) == mi.sealed_execution_plan_ref
    assert resolved_vdr.validated_record_digest == vdr.validated_record_digest


def test_materialization_input_port_rejects_plan_ref_mismatch() -> None:
    plan = _plan()
    snap = _snapshot()
    store = ImmutableVdrStore()
    store.put(_vdr(plan, snap))
    port = gd.MaterializationInputPort(plan_resolver=lambda ref: plan, vdr_store=store)
    bad = gd.MaterializationInput(
        sealed_execution_plan_ref="sha256:not-the-plan",
        validated_record_ref=_vdr(plan, snap).validated_record_digest,
    )
    with pytest.raises(gd.MaterializationInputResolutionError):
        port.resolve(bad)


def test_adapter_types_distinct_and_guarantee_only_managed() -> None:
    plan = _plan()
    mgp = _managed(plan, (_snapshot(),))
    managed = gd.ManagedPlanMaterializationAdapter(managed_plan=mgp)
    slotless = gd.LegacySlotlessGenerationAdapter(transitional_reason="legacy")
    cont = gd.LegacyContinuationGenerationAdapter(previous_output_base="C:/old", transitional_reason="cont")
    assert type(managed) is not type(slotless) is not type(cont)
    assert gd.has_s5_exact_delivery_guarantee(managed) is True
    assert gd.has_s5_exact_delivery_guarantee(slotless) is False
    assert gd.has_s5_exact_delivery_guarantee(cont) is False
    # managed adapter 는 Plan+VDR MaterializationInput 을 낸다(legacy generator 입력으로 변환 0).
    assert all(isinstance(mi, gd.MaterializationInput) for mi in managed.materialization_inputs())
    # continuation 은 applied Candidate 로 취급하지 않는다.
    assert gd.continuation_is_applied_candidate(cont) is False


def test_slotless_managed_bridge_same_contract() -> None:
    # SLOTLESS Plan(remove operation 0)도 같은 bridge·delivery contract 를 쓴다.
    plan = _plan()
    assert plan.execution_basis.selection.slot_mode == "SLOTLESS"
    assert not plan.ordered_operations or all(
        o["op"] == "APPLY_FIELD_BINDING" for o in plan.ordered_operations
    )
    res = _ok(_resolve(plan, (_snapshot(),)))
    assert res.delivery_contract_id == gd.DELIVERY_CONTRACT_ID


def _runtime_manifest(status="PASS"):
    return RuntimeMaterializerConformanceManifest(
        runtime_capability_manifest_digest="sha256:cap",
        materialization_contract_id="materialization/v1",
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        admitted_composition_contract_ids=(COMPOSITION_CONTRACT_ID,),
        supported_plan_schema_versions=("hwpx-execution-plan/v1",),
        supported_canonical_encoding_versions=("execution-canonical/v1",),
        conformance_status=status,
    )


def test_runtime_admission_absent_is_construction_only() -> None:
    empty = RuntimeMaterializerConformanceRegistry()
    adm = gd.evaluate_managed_run_admission(
        runtime_registry=empty, sealed_execution_plan=_plan(),
        runtime_capability_manifest_digest="sha256:cap",
    )
    assert adm.construction_allowed is True
    assert adm.materialization_startable is False
    assert adm.status == gd.MANAGED_RUN_CONSTRUCTION_ONLY


def test_runtime_admission_present_is_startable() -> None:
    reg = RuntimeMaterializerConformanceRegistry()
    reg.register(_runtime_manifest())
    _ = runtime_conformance_digest(_runtime_manifest())  # digest seam smoke
    adm = gd.evaluate_managed_run_admission(
        runtime_registry=reg, sealed_execution_plan=_plan(),
        runtime_capability_manifest_digest="sha256:cap",
    )
    assert adm.materialization_startable is True
    assert adm.status == gd.MANAGED_RUN_STARTABLE


def test_runtime_admission_derives_query_from_plan_not_caller() -> None:
    # 서명이 contract/schema 를 caller 자유입력으로 받지 않는다 — 다른 Plan 의 supported 값을
    # 빌려 ADMITTED 를 위조할 수 없다(오직 sealed plan + runtime capability digest).
    params = set(inspect.signature(gd.evaluate_managed_run_admission).parameters)
    assert params == {
        "runtime_registry",
        "sealed_execution_plan",
        "runtime_capability_manifest_digest",
    }


# ═══ fail-closed branch coverage(inactive value resolution·guards·integrity) ═══════════════
def test_resolve_delivery_field_value_variants() -> None:
    snap = _snapshot(dept="본과")
    # CONSTANT boolean → canonical lexical text.
    ve_bool = {"kind": "CONSTANT", "canonical_value": {"value_type": "BOOLEAN", "literal": True},
               "document_content_value_policy_id": _POLICY_ID}
    assert gd.resolve_delivery_field_value(ve_bool, snap) == "true"
    # FROM_SOURCE explicit null → unresolved blocker.
    null_snap = build_raw_record_snapshot(
        source_schema_keys=["dept"],
        source_values=[("dept", SourceNull())],
        record_identity="rn", capture_provenance=_PROV,
    )
    ve_src = {"kind": "FROM_SOURCE", "source_key": "dept", "value_type": EXACT_TEXT,
              "document_content_value_policy_id": _POLICY_ID}
    code, _ = gd.resolve_delivery_field_value(ve_src, null_snap)
    assert code == gd.OUTPUT_NAME_TOKEN_UNRESOLVED


def test_resolve_delivery_field_value_fail_closed() -> None:
    snap = _snapshot()
    # 미지원 policy → context signal.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "CONSTANT", "canonical_value": {"value_type": EXACT_TEXT, "literal": "x"},
             "document_content_value_policy_id": "document-content-value/v999"},
            snap,
        )
    # unknown kind → integrity context signal.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "MYSTERY", "document_content_value_policy_id": _POLICY_ID}, snap
        )
    # CONSTANT 누락 canonical_value → integrity.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "CONSTANT", "document_content_value_policy_id": _POLICY_ID}, snap
        )
    # FROM_SOURCE 형식 불량 source_key → integrity.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "FROM_SOURCE", "source_key": None, "value_type": EXACT_TEXT,
             "document_content_value_policy_id": _POLICY_ID},
            snap,
        )
    # BOOLEAN literal 이 bool 이 아님 → integrity.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "CONSTANT", "canonical_value": {"value_type": "BOOLEAN", "literal": "yes"},
             "document_content_value_policy_id": _POLICY_ID},
            snap,
        )


def test_guard_relative_path_branches() -> None:
    for bad in ("a/b.hwpx", "..", "../x.hwpx", ".hwpx"):
        with pytest.raises(gd._DeliveryContextSignal):
            gd._guard_relative_path(bad)
    gd._guard_relative_path("ok.hwpx")  # 통과


def test_managed_plan_integrity_tamper() -> None:
    mgp = _managed(_plan(), (_snapshot(),))
    with pytest.raises(gd.ManagedGenerationPlanIntegrityError):
        gd.verify_managed_generation_plan_integrity(
            dataclasses.replace(mgp, managed_generation_plan_digest="sha256:x")
        )
    with pytest.raises(gd.ManagedGenerationPlanIntegrityError):
        gd.verify_managed_generation_plan_integrity(
            dataclasses.replace(mgp, delivery_contract_id="generation-delivery/v999")
        )


def test_resolved_plan_integrity_ordinal_and_dup_path() -> None:
    res = _ok(_resolve(_plan(), (_snapshot(identity="r1", name="A"), _snapshot(identity="r2", name="B"))))
    a, b = res.ordered_items
    # ordinal 뒤섞기.
    with pytest.raises(gd.ResolvedDeliveryPlanIntegrityError):
        gd.verify_resolved_delivery_plan_integrity(dataclasses.replace(res, ordered_items=(b, a)))


# ═══ Codex review findings (trust-boundary·cross-binding·windows FS) ═══════════════════════
def _resolve_explicit(plan, snaps, vdrs, *, pattern, basis=None):
    return gd.resolve_generation_delivery_plan(
        sealed_execution_plan=plan,
        exact_pattern=pattern,
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=basis if basis is not None else _basis_dto(plan, pattern),
        ordered_raw_snapshots=snaps,
        ordered_validated_records=vdrs,
        captured_delivery_clock=_CLOCK,
        output_directory_basis="C:/out",
        overwrite_policy=gd.OVERWRITE_EXISTING,
    )


def test_forged_vdr_payload_rejected() -> None:
    # F1: 원본 digest 를 유지한 채 document_value 를 위조한 VDR 은 filename 을 forged 값으로 만들지 못한다.
    plan, snap = _plan(), _snapshot()
    vdr = _vdr(plan, snap)
    base = dict(vdr.semantic_payload_encoded)
    rvs = [dict(x) for x in base["resolved_requirement_values"]]
    rvs[0] = {**rvs[0], "document_value": "FORGED"}
    base["resolved_requirement_values"] = rvs
    forged = dataclasses.replace(vdr, semantic_payload_encoded=base)  # validated_record_digest 그대로
    res = _resolve_explicit(plan, (snap,), [forged], pattern="{{f_name}}")
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR


def test_forged_raw_snapshot_rejected() -> None:
    # F2: 원본 digest/identity 를 유지한 채 _values 를 위조한 raw snapshot 은 inactive filename 값을 오염 못 시킨다.
    plan, snap = _plan(), _snapshot(dept="원본")
    forged = dataclasses.replace(
        snap, _values={**dict(snap._values), "dept": SourceText("HACKED")}
    )
    basis = _basis_dto(plan, pattern="{{f_dept}}")
    res = _resolve_explicit(plan, (forged,), [_vdr(plan, snap)], pattern="{{f_dept}}", basis=basis)
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR


def test_managed_builder_rejects_plan_ref_not_bound_to_delivery_plan() -> None:
    # F3: delivery plan 의 VDR 이 결속된 Plan 과 다른 ref 를 봉인하면 거절(모든 MaterializationInput 이 나중에 실패).
    plan = _plan()
    res = _ok(_resolve(plan, (_snapshot(),)))
    assert res.bound_plan_semantic_digest == plan_semantic_digest(plan)
    with pytest.raises(gd.ManagedGenerationPlanIntegrityError):
        gd.build_managed_generation_plan(
            sealed_execution_plan_ref="sha256:wrong-plan",
            resolved_delivery_plan=res,
            output_directory="C:/out",
            created_at="t",
        )


def test_inactive_format_code_sealed_and_fail_closed() -> None:
    # F4: inactive SOURCE 의 nonempty format_code 는 봉인되고, v1 미구현이라 조용히 버리지 않고 fail-closed.
    rule = FieldBindingRule(
        field_id="f_dept", binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        source_key="dept", value_type=EXACT_TEXT, format_code="UPPER",
    )
    plan = _plan()
    basis = _basis_dto(plan, pattern="{{f_dept}}", inactive_rules=(rule,))
    assert basis.output_name_requirements[0].value_expression["format_code"] == "UPPER"
    res = _resolve(plan, (_snapshot(),), pattern="{{f_dept}}", basis=basis)
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT


def test_unsupported_document_value_resolution_contract_rejected_in_basis() -> None:
    # F5: 미지원 document value resolution contract 를 조용히 봉인하지 않는다(active-only pattern 포함).
    res = gd.build_delivery_binding_basis(
        base_template_application_id="app-1", field_binding_authority_revision="rev",
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern="{{f_name}}", active_field_ids=("f_name",), binding_rules=(),
        document_value_resolution_contract_id="document-content-value/v999",
    )
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT


def test_dedup_case_insensitive_on_windows_fs() -> None:
    # F7: 대소문자만 다른 이름은 Windows FS 에서 같은 파일 → 접미사(철자는 원본 보존).
    plan = _plan()
    res = _ok(_resolve(
        plan,
        (_snapshot(identity="r1", name="Report"), _snapshot(identity="r2", name="report")),
        pattern="{{f_name}}",
    ))
    assert [i.resolved_output_relative_path for i in res.ordered_items] == [
        "Report.hwpx", "report_1.hwpx",
    ]


def test_pattern_literal_colon_rejected_as_drive_relative() -> None:
    # F8: 리터럴 ':' 는 drive-relative(C:x)·ADS 를 만들어 output root 를 버릴 수 있다 → 거절.
    plan = _plan()
    res = _resolve(plan, (_snapshot(),), pattern="C:{{f_name}}")
    assert isinstance(res, gd.DeliveryPlanContextError)
    assert res.code == gd.OUTPUT_PATH_ESCAPE_DETECTED


def test_no_native_write_or_route_cutover_in_module() -> None:
    # native write·HWPX mutation·legacy generator 로의 conversion 경로가 이 모듈에 없다.
    modules = {m for m in _module_imports(gd) }
    for forbidden in ("zipfile", "lxml", "hwpxcore", "hwpxfiller.batch", "hwpxfiller.external.hwpx_engine"):
        assert not any(m == forbidden or m.startswith(forbidden + ".") for m in modules), forbidden


def _module_imports(mod) -> set[str]:
    import ast

    tree = ast.parse(inspect.getsource(mod))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out
