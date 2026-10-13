"""현행 생성 배달의 이름 해석, 충돌 처리, 입력 무결성 계약."""

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
    COMPOSITION_FINGERPRINT_HWPX,
    RuntimeMaterializerConformanceManifest,
    RuntimeMaterializerConformanceRegistry,
    runtime_conformance_digest,
)
from hwpxfiller.application.execution_contract_set import (
    ExecutionBasis,
    build_execution_contract_set,
    build_sealed_plan,
)
from hwpxfiller.application.execution_semantic_kernel import (
    ExecutionContractSemantics,
    SealedExecutionPlanValue,
)
from hwpxfiller.application.record_validation import (
    CurrentValidatedDataRecord,
    ValidatedDataRecord,
    validate_data_record_against_current_value,
    validate_data_record_against_plan,
)
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    INTENTIONAL_BLANK,
    SOURCE,
    ExactText,
    FieldBindingRule,
    TextSlice,
)
from hwpxfiller.domain.raw_data_record import (
    RawRecordCaptureProvenance,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
)

_POLICY_ID = "document-content-value/v1"
_THEOREM = COMPOSITION_FINGERPRINT_HWPX
_PROV = RawRecordCaptureProvenance(
    source_adapter_contract_id="excel-adapter/v1", captured_at="2026-01-01T00:00:00+09:00"
)
_CLOCK = "2026-03-04T09:15:00+09:00"
_PATTERN = "공고서-{{f_name}}-{{date:YYYYMMDD}}-{{seq:001}}"


# ─── Plan / VDR scaffold(S5-06/12 real builders) ─────────────────────────────────────────
def _rules():
    return (
        EffectiveFieldBindingRule("f_name", "SOURCE", FromSource("name", None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_amount", "SOURCE", FromSource("amount", None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_flag", "SOURCE", FromSource("flag", None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_const", "CONSTANT", ConstantValue(ExactText("보증금"), None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_blank", "INTENTIONAL_BLANK", IntentionalBlank()),
    )


def _contracts(**over):
    kw = dict(
        slot_selection_contract_id="slot-selection/v1",
        field_binding_contract_id="field-binding/v3",
        source_schema_contract_id="source-schema/v2",
        raw_record_contract_id="raw-record/v1",
        execution_semantic_contract_id="execution-semantics/v1",
        binding_value_contract_id="binding-value/v2",
        document_value_resolution_contract_id="document-content-value/v2",
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
        plan_schema_version="hwpx-execution-plan/v2",
    )


def _snapshot(name="홍길동", *, identity="rec-1", dept="총무과", extra_pairs=()):
    pairs = [
        ("name", SourceText(name)),
        ("amount", SourceText("1500.00")),
        ("flag", SourceText("TRUE")),
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


def _current_vdr(
    plan: SealedExecutionPlanValue, snapshot,
) -> CurrentValidatedDataRecord:
    result = validate_data_record_against_current_value(
        plan=plan, snapshot=snapshot, validated_at=_CLOCK
    )
    assert isinstance(result, CurrentValidatedDataRecord), result
    return result


def _resolve_current(
    plan: SealedExecutionPlanValue,
    snapshots,
    *,
    pattern="{{f_name}}",
    occupied=(),
    occupancy_entries=None,
    collision="ADD_SUFFIX",
    inactive_rules=(),
    basis=None,
    clock=_CLOCK,
    records=None,
):
    if basis is None:
        basis = _basis_dto(plan, pattern=pattern, inactive_rules=inactive_rules)
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis), basis
    entries = (
        tuple(occupancy_entries)
        if occupancy_entries is not None
        else tuple(gd.PathOccupancyEntry(name, gd.REGULAR_FILE) for name in occupied)
    )
    return gd.resolve_current_generation_delivery(
        sealed_execution_plan=plan,
        ordered_validated_records=(
            tuple(_current_vdr(plan, item) for item in snapshots)
            if records is None else records
        ),
        ordered_raw_snapshots=snapshots,
        delivery_binding_basis=basis,
        exact_pattern=pattern,
        captured_delivery_clock=clock,
        run_delivery_intent=RunDeliveryIntent("C:/out", collision),
        path_occupancy=gd.PathOccupancyObservation("C:/out", entries, clock),
    )


def test_current_resolver_returns_planned_path() -> None:
    plan = _current_plan()
    result = _resolve_current(plan, (_snapshot(),))
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert result.ordered_items[0].resolved_output_relative_path == "홍길동.hwpx"


def test_current_resolver_fails_closed_on_validation_basis_mismatch() -> None:
    plan, snapshot = _current_plan(), _snapshot()
    record = _current_vdr(plan, snapshot)
    record = dataclasses.replace(
        record,
        validation_basis=dataclasses.replace(
            record.validation_basis, record_validation_contract_id="record-validation/v999"
        ),
    )
    basis = _basis_dto(plan, pattern="{{f_name}}", inactive_rules=())
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis)
    result = gd.resolve_current_generation_delivery(
        sealed_execution_plan=plan,
        ordered_validated_records=(record,),
        ordered_raw_snapshots=(snapshot,),
        delivery_binding_basis=basis,
        exact_pattern="{{f_name}}",
        captured_delivery_clock=_CLOCK,
        run_delivery_intent=RunDeliveryIntent("C:/out"),
        path_occupancy=gd.PathOccupancyObservation("C:/out", (), _CLOCK),
    )
    assert isinstance(result, gd.DeliveryPlanContextError)
    assert result.code == gd.CURRENT_RECORD_VALIDATION_BASIS_MISMATCH


def test_current_resolver_fails_closed_on_raw_vdr_pair_mismatch() -> None:
    plan = _current_plan()
    snapshot = _snapshot(identity="record-a")
    other = _snapshot(identity="record-b")
    record = _current_vdr(plan, snapshot)
    basis = _basis_dto(plan, pattern="{{f_name}}", inactive_rules=())
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis)
    result = gd.resolve_current_generation_delivery(
        sealed_execution_plan=plan,
        ordered_validated_records=(record,),
        ordered_raw_snapshots=(other,),
        delivery_binding_basis=basis,
        exact_pattern="{{f_name}}",
        captured_delivery_clock=_CLOCK,
        run_delivery_intent=RunDeliveryIntent("C:/out"),
        path_occupancy=gd.PathOccupancyObservation("C:/out", (), _CLOCK),
    )
    assert isinstance(result, gd.DeliveryPlanContextError)
    assert result.code == gd.RAW_VALIDATED_RECORD_MISMATCH


def test_current_add_suffix_avoids_disk_and_ordered_batch_case_insensitively() -> None:
    plan = _current_plan()
    snapshots = (
        _snapshot(name="보고서", identity="record-1"),
        _snapshot(name="보고서", identity="record-2"),
    )
    result = _resolve_current(
        plan,
        snapshots,
        occupied=("보고서.HWPX", "보고서_1.hwpx"),
    )
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert [item.resolved_output_relative_path for item in result.ordered_items] == [
        "보고서_2.hwpx",
        "보고서_3.hwpx",
    ]
    assert [item.item_ordinal for item in result.ordered_items] == [0, 1]
    assert all(
        item.collision_disposition == gd.WRITE_ADD_SUFFIX
        for item in result.ordered_items
    )
    assert _resolve_current(
        plan,
        snapshots,
        occupied=("보고서.HWPX", "보고서_1.hwpx"),
    ) == result


def test_current_fail_reports_existing_path_without_changing_batch_suffix() -> None:
    plan = _current_plan()
    result = _resolve_current(
        plan,
        (
            _snapshot(name="보고서", identity="record-1"),
            _snapshot(name="보고서", identity="record-2"),
        ),
        occupied=("보고서.hwpx", "보고서_1.hwpx"),
        collision="FAIL",
    )
    assert isinstance(result, gd.DeliveryPlanBlocked), result
    assert [
        (item.code, item.item_ordinal, item.conflicting_relative_path)
        for item in result.blockers
    ] == [
        (gd.OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED, 0, "보고서.hwpx"),
        (gd.OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED, 1, "보고서_1.hwpx"),
    ]


def test_current_explicit_overwrite_marks_only_existing_exact_path() -> None:
    plan = _current_plan()
    result = _resolve_current(
        plan,
        (
            _snapshot(name="보고서", identity="record-1"),
            _snapshot(name="새문서", identity="record-2"),
        ),
        occupied=("보고서.HWPX",),
        collision="OVERWRITE_EXPLICIT",
    )
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert [item.resolved_output_relative_path for item in result.ordered_items] == [
        "보고서.hwpx",
        "새문서.hwpx",
    ]
    assert [item.collision_disposition for item in result.ordered_items] == [
        gd.WRITE_OVERWRITE,
        gd.WRITE_NEW,
    ]


def test_current_non_regular_collision_blocks_overwrite_and_add_suffix_avoids_it() -> None:
    plan = _current_plan()
    occupied = (gd.PathOccupancyEntry("보고서.hwpx", gd.NON_REGULAR),)
    blocked = _resolve_current(
        plan,
        (_snapshot(name="보고서"),),
        occupancy_entries=occupied,
        collision="OVERWRITE_EXPLICIT",
    )
    assert isinstance(blocked, gd.DeliveryPlanBlocked), blocked
    assert blocked.blockers[0].code == gd.OUTPUT_PATH_NON_REGULAR_CONFLICT
    assert blocked.blockers[0].conflicting_relative_path == "보고서.hwpx"

    suffixed = _resolve_current(
        plan,
        (_snapshot(name="보고서"),),
        occupancy_entries=occupied,
    )
    assert isinstance(suffixed, gd.CurrentResolvedDelivery), suffixed
    assert suffixed.ordered_items[0].resolved_output_relative_path == "보고서_1.hwpx"
    assert suffixed.ordered_items[0].collision_disposition == gd.WRITE_ADD_SUFFIX


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("1500.00", "1500.00"),
        ("1,500,000", "1,500,000"),
        ("2026.8.31", "2026.8.31"),
        ("2026-08-20T09:15:00+09:00", "2026-08-20T09_15_00+09_00"),
        ("TRUE", "TRUE"),
    ],
)
def test_current_inactive_filename_uses_the_frozen_source_text_verbatim(
    raw_text: str, expected: str,
) -> None:
    plan = _current_plan()
    rule = FieldBindingRule(
        field_id="f_typed",
        binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        source_key="typed",
    )
    result = _resolve_current(
        plan,
        (_snapshot(extra_pairs=(("typed", SourceText(raw_text)),)),),
        pattern="{{f_typed}}",
        inactive_rules=(rule,),
    )
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert result.ordered_items[0].resolved_output_relative_path == f"{expected}.hwpx"


def test_current_inactive_fields_share_one_frozen_source_key() -> None:
    rules = tuple(
        FieldBindingRule(
            field_id=field_id,
            binding_kind=SOURCE,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            source_key="shared",
        )
        for field_id in ("f_text", "f_decimal")
    )
    result = _resolve_current(
        _current_plan(),
        (_snapshot(extra_pairs=(("shared", SourceText("1")),)),),
        pattern="{{f_text}}-{{f_decimal}}",
        inactive_rules=rules,
    )
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert result.ordered_items[0].resolved_output_relative_path == "1-1.hwpx"


def test_current_inactive_filename_applies_slice_before_format() -> None:
    rule = FieldBindingRule(
        field_id="f_dept",
        binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        source_key="dept",
        format_kind="amount",
        format_code="{:,}",
        text_slice=TextSlice("split", delimiter="원", index=1),
    )
    result = _resolve_current(
        _current_plan(),
        (_snapshot(dept="1500000원 (VAT 포함)"),),
        pattern="{{f_dept}}",
        inactive_rules=(rule,),
    )
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert result.ordered_items[0].resolved_output_relative_path == "1,500,000.hwpx"


@pytest.mark.parametrize(
    ("pattern", "inactive_rules"),
    [
        ("{{f_blank}}", ()),
        ("{{f_missing}}", (
            FieldBindingRule(
                "f_missing", SOURCE, DOCUMENT_CONTENT_VALUE_POLICY_V1,
                source_key="missing",
            ),
        )),
        ("{{f_empty}}", (
            FieldBindingRule("f_empty", INTENTIONAL_BLANK, DOCUMENT_CONTENT_VALUE_POLICY_V1),
        )),
    ],
)
def test_current_unresolved_field_blocks_output_name(pattern, inactive_rules) -> None:
    result = _resolve_current(
        _current_plan(), (_snapshot(),), pattern=pattern, inactive_rules=inactive_rules
    )
    assert isinstance(result, gd.DeliveryPlanBlocked), result
    assert result.blockers[0].code == gd.OUTPUT_NAME_TOKEN_UNRESOLVED


def test_current_rejects_tampered_binding_basis() -> None:
    plan = _current_plan()
    basis = _basis_dto(plan, pattern="{{f_name}}", inactive_rules=())
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis)
    result = _resolve_current(
        plan, (_snapshot(),),
        basis=dataclasses.replace(basis, delivery_binding_basis_digest="sha256:wrong"),
    )
    assert isinstance(result, gd.DeliveryPlanContextError), result
    assert result.code == gd.DELIVERY_BINDING_BASIS_INTEGRITY_ERROR


def test_current_rejects_tampered_raw_snapshot_and_invalid_clock() -> None:
    plan = _current_plan()
    snapshot = _snapshot()
    record = _current_vdr(plan, snapshot)
    tampered = dataclasses.replace(snapshot, _values={**snapshot._values, "name": SourceText("변조")})
    result = _resolve_current(plan, (tampered,), records=(record,))
    assert isinstance(result, gd.DeliveryPlanContextError), result
    assert result.code == gd.GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR

    result = _resolve_current(plan, (snapshot,), clock="not-a-date")
    assert isinstance(result, gd.DeliveryPlanContextError), result
    assert result.code == gd.GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR


def test_current_rejects_path_escape() -> None:
    result = _resolve_current(_current_plan(), (_snapshot(),), pattern="../{{f_name}}")
    assert isinstance(result, gd.DeliveryPlanContextError), result
    assert result.code == gd.OUTPUT_PATH_ESCAPE_DETECTED


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


def test_no_binding_unresolved() -> None:
    res = _basis_dto(_plan(), pattern="{{f_unknown}}", inactive_rules=())
    assert isinstance(res, gd.DeliveryPlanBlocked)
    assert (res.blockers[0].code, res.blockers[0].field_id) == (
        gd.OUTPUT_NAME_TOKEN_UNRESOLVED, "f_unknown"
    )








# ═══ runtime admission ═══════════════════════════════════════════════════════════════════


def _runtime_manifest(status="PASS"):
    return RuntimeMaterializerConformanceManifest(
        runtime_capability_manifest_digest="sha256:cap",
        materialization_contract_id="materialization/v1",
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        admitted_composition_contract_ids=(COMPOSITION_CONTRACT_ID,),
        supported_plan_schema_versions=("hwpx-execution-plan/v2",),
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
    # CONSTANT → tagged text 하나(값 유형 없음).
    ve_const = {"kind": "CONSTANT", "canonical_value": {"kind": "TEXT", "text": "고정"},
                "document_content_value_policy_id": _POLICY_ID}
    assert gd.resolve_delivery_field_value(ve_const, snap) == "고정"
    # FROM_SOURCE explicit null → unresolved blocker.
    null_snap = build_raw_record_snapshot(
        source_schema_keys=["dept"],
        source_values=[("dept", SourceNull())],
        record_identity="rn", capture_provenance=_PROV,
    )
    ve_src = {"kind": "FROM_SOURCE", "source_key": "dept",
              "document_content_value_policy_id": _POLICY_ID}
    code, _ = gd.resolve_delivery_field_value(ve_src, null_snap)
    assert code == gd.OUTPUT_NAME_TOKEN_UNRESOLVED


def test_resolve_delivery_field_value_fail_closed() -> None:
    snap = _snapshot()
    # 미지원 policy → context signal.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "CONSTANT", "canonical_value": {"kind": "TEXT", "text": "x"},
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
            {"kind": "FROM_SOURCE", "source_key": None,
             "document_content_value_policy_id": _POLICY_ID},
            snap,
        )
    # 구 tagged 표현(value_type/literal)은 v2 로 풀지 않는다 → integrity.
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            {"kind": "CONSTANT", "canonical_value": {"value_type": "EXACT_TEXT", "literal": "x"},
             "document_content_value_policy_id": _POLICY_ID},
            snap,
        )


def test_guard_relative_path_branches() -> None:
    for bad in ("a/b.hwpx", "..", "../x.hwpx", ".hwpx"):
        with pytest.raises(gd._DeliveryContextSignal):
            gd._guard_relative_path(bad)
    gd._guard_relative_path("ok.hwpx")  # 통과




def test_inactive_source_without_slice_keeps_the_sealed_shape() -> None:
    """가공 없는 요구는 키가 없다 — v4 이전에 봉인된 basis 의 재계산 대조가 그대로 선다."""
    rule = FieldBindingRule(
        field_id="f_dept", binding_kind=SOURCE,
        document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1, source_key="dept",
    )
    basis = _basis_dto(_plan(), pattern="{{f_dept}}", inactive_rules=(rule,))
    assert "text_slice" not in basis.output_name_requirements[0].value_expression


def test_inactive_malformed_slice_is_fail_closed() -> None:
    ve = {"kind": "FROM_SOURCE", "source_key": "dept", "format_kind": None,
          "format_code": None, "document_content_value_policy_id": _POLICY_ID,
          "text_slice": {"mode": "split", "delimiter": "", "index": 1}}
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(ve, _snapshot())
    constant = {"kind": "CONSTANT", "canonical_value": {"kind": "TEXT", "text": "x"},
                "format_code": None, "document_content_value_policy_id": _POLICY_ID,
                "text_slice": {"mode": "chars", "start": 1}}
    with pytest.raises(gd._DeliveryContextSignal):  # 고정값에는 가공이 없다
        gd.resolve_delivery_field_value(constant, _snapshot())


def test_inactive_value_format_of_unknown_kind_is_fail_closed() -> None:
    ve = {"kind": "FROM_SOURCE", "source_key": "dept", "format_kind": "currency",
          "format_code": "", "document_content_value_policy_id": _POLICY_ID}
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(ve, _snapshot())
    constant = {"kind": "CONSTANT", "canonical_value": {"kind": "TEXT", "text": "x"},
                "format_kind": "amount", "format_code": "",
                "document_content_value_policy_id": _POLICY_ID}
    with pytest.raises(gd._DeliveryContextSignal):  # 고정값은 서식하지 않는다
        gd.resolve_delivery_field_value(constant, _snapshot())


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
