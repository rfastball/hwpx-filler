"""「오늘 날짜」의 판본 규칙 — RUNTIME_DATE binding kind (field-binding/v4 · #950).

#1092/#1093 이 HWPX 생성을 managed 하나로 모은 뒤 「오늘 날짜」 행이 있는 작업은 봉인에서
``RUNTIME_TODAY_UNSUPPORTED`` 로 막혔다(legacy 경로가 하던 일). 값이 데이터 열도 고정 리터럴도 아닌
**실행 시각**에서 오므로 SOURCE·CONSTANT 로 접으면 거짓 durable 규칙이 된다 — 그래서 kind 다.

여기가 재는 것:

- 규칙 불변식 — source·constant·가공 없음, date 표시형만, 공백 보존 정책만.
- 판 framing — v4 에서만 봉인되고(v2·v3 동결) 같은 규칙은 같은 digest, 저장 codec 왕복.
- legacy migration — ``today`` + date 프리셋 전부가 RUNTIME_DATE 후보가 되고 legacy 와 같은 글자.
- 실행 계획 — 규칙만 봉인하고 시각은 싣지 않는다(Plan digest 가 시각과 무관).
- record validation — caller 가 캡처한 시각 하나로 렌더, 결측·표식 없음, 시각 없으면 닫힘.
- 파일 이름 — 날짜 토큰·「오늘 날짜」 토큰(Active·inactive)이 배달 시각 하나에서 나온다(RC-02).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from hwpxfiller.application import generation_delivery as gd
from hwpxfiller.application.execution_compilation import (
    EffectiveFieldBindingRule,
    FromSource,
    RuntimeDate,
    encode_value_expression,
)
from hwpxfiller.application.field_binding_input import (
    LegacyFieldBindingEntry,
    prepare_legacy_field_binding_migration,
)
from hwpxfiller.application.record_validation import (
    MISSING_VALUE_MARKED,
    RUNTIME_CLOCK_UNAVAILABLE,
    UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
    CurrentValidatedDataRecord,
    RecordValidationContextError,
    ValidatedDataRecord,
    validate_data_record_against_current_value,
    validate_data_record_against_plan,
    validate_data_records_against_current_value,
)
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent
from hwpxfiller.application.stored_field_binding import _decode_rule, _encode_rule
from hwpxfiller.domain import format_engine
from hwpxfiller.domain.field_binding import (
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    FIELD_BINDING_SEMANTIC_VERSION,
    FIELD_BINDING_SEMANTIC_VERSION_V2,
    FIELD_BINDING_SEMANTIC_VERSION_V3,
    RUNTIME_DATE,
    SOURCE,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    RuntimeClockError,
    canonicalize_binding_rules,
    digest_binding_rules,
    parse_runtime_clock,
    render_runtime_date,
)
from hwpxfiller.domain.mapping import FieldMapping, apply_transform
from hwpxfiller.domain.text_slice import TextSlice
from tests.test_generation_delivery import (
    _CLOCK,
    _POLICY_ID,
    _basis as _base_basis,
    _snapshot,
)
from hwpxfiller.application.execution_compilation import (
    EffectiveFieldBindingBasis,
    active_binding_digest,
    required_source_key_set_digest,
)
from hwpxfiller.application.execution_contract_semantics import ExecutionContractSemantics
from hwpxfiller.application.execution_contract_set import build_sealed_plan
from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue

NOW = datetime(2026, 6, 15, 18, 4)
POLICY = DOCUMENT_CONTENT_VALUE_POLICY_V1
#: format_engine 이 「오늘 날짜」에 내주는 프리셋 — date 표와 같은 표다(U4 §2.14 판정 1).
DATE_PRESETS = [code for _label, code in format_engine.presets("today")]


def _today(field_id: str = "작성일", code: str = "") -> FieldBindingRule:
    return FieldBindingRule(field_id, RUNTIME_DATE, POLICY, format_kind="date", format_code=code)


# ─── 규칙 불변식 ──────────────────────────────────────────────────────────────────
def test_presets_are_the_date_presets() -> None:
    assert DATE_PRESETS == [code for _label, code in format_engine.presets("date")]
    assert len(DATE_PRESETS) == 9


def test_runtime_date_rule_carries_only_the_date_format_pair() -> None:
    rule = _today(code="kor")
    assert (rule.source_key, rule.canonical_constant_value, rule.text_slice) == (None, None, None)
    assert (rule.format_kind, rule.format_code) == ("date", "kor")


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"source_key": "작성일"}, "source/constant"),
        ({"canonical_constant_value": ExactText("2026-06-15")}, "source/constant"),
        ({"text_slice": TextSlice("chars", start=1)}, "가공"),
        ({"format_kind": None, "format_code": None}, "date"),
        ({"format_kind": "amount", "format_code": ""}, "date"),
        ({"format_kind": "text", "format_code": "phone"}, "date"),
        ({"format_kind": "date", "format_code": None}, "문자열"),
    ],
)
def test_runtime_date_rule_rejects_every_other_slot(over, reason) -> None:
    kw = {"format_kind": "date", "format_code": "", **over}
    with pytest.raises(FieldBindingInputIntegrityError, match=reason):
        FieldBindingRule("작성일", RUNTIME_DATE, POLICY, **kw)


def test_runtime_date_rule_requires_a_whitespace_preserving_policy() -> None:
    # 실행 시각 값은 소스 텍스트가 아니다 — legacy 도 다듬지 않았다.
    with pytest.raises(FieldBindingInputIntegrityError, match="공백"):
        FieldBindingRule(
            "작성일", RUNTIME_DATE, DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
            format_kind="date", format_code="",
        )
    # TXT 짝(같은 공백 의미, 다른 escaping 책임)은 받는다.
    FieldBindingRule(
        "작성일", RUNTIME_DATE, DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1,
        format_kind="date", format_code="",
    )


# ─── 판 framing·저장 codec ──────────────────────────────────────────────────────────
def test_runtime_date_is_sealed_only_by_the_current_contract() -> None:
    rules = (_today(),)
    assert canonicalize_binding_rules(rules).count(RUNTIME_DATE.encode("utf-8")) == 1
    for frozen in (FIELD_BINDING_SEMANTIC_VERSION_V2, FIELD_BINDING_SEMANTIC_VERSION_V3):
        with pytest.raises(FieldBindingInputIntegrityError):
            canonicalize_binding_rules(rules, contract_id=frozen)


def test_runtime_date_digest_is_deterministic_and_distinct() -> None:
    a = digest_binding_rules((_today(code="kor"), FieldBindingRule("이름", SOURCE, POLICY, source_key="n")))
    b = digest_binding_rules((FieldBindingRule("이름", SOURCE, POLICY, source_key="n"), _today(code="kor")))
    assert a == b  # 순서 무관
    assert digest_binding_rules((_today(code="kor"),)) != digest_binding_rules((_today(code=""),))
    # 같은 표시형의 날짜 **데이터 열**과는 다른 규칙이다(kind 가 identity 에 든다).
    source_date = FieldBindingRule(
        "작성일", SOURCE, POLICY, source_key="", format_kind="date", format_code="kor"
    )
    assert digest_binding_rules((_today(code="kor"),)) != digest_binding_rules((source_date,))
    assert FIELD_BINDING_SEMANTIC_VERSION == "field-binding/v4"


def test_stored_codec_round_trips_a_runtime_date_rule() -> None:
    rule = _today(code="%Y.%m.%d")
    encoded = _encode_rule(rule)
    assert encoded["binding_kind"] == RUNTIME_DATE and "text_slice" not in encoded
    assert _decode_rule(encoded) == rule


# ─── legacy migration ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("code", DATE_PRESETS)
def test_legacy_today_migrates_with_each_date_preset(code) -> None:
    draft = prepare_legacy_field_binding_migration(
        work_authority_id="work",
        base_template_application_id="app",
        legacy_entries=(LegacyFieldBindingEntry("작성일", "today", "", "", code),),
        captured_at="2026-09-30T00:00:00",
    )
    assert draft.blockers == ()
    (candidate,) = draft.candidate_rules
    rule = FieldBindingRule(
        candidate.field_id,
        candidate.binding_kind,
        POLICY,
        source_key=candidate.source_key,
        format_code=candidate.format_code,
        canonical_constant_value=candidate.canonical_constant_value,
        format_kind=candidate.format_kind,
        text_slice=candidate.text_slice,
    )
    assert rule.binding_kind == RUNTIME_DATE
    # 판본 규칙의 글자 = legacy 「오늘 날짜」의 글자(같은 시각이면).
    assert render_runtime_date(rule.format_code or "", NOW) == apply_transform(
        "today", fmt=code, now=NOW
    )
    assert FieldMapping("작성일", type="today", fmt=code).value_for({}, now=NOW) == (
        render_runtime_date(code, NOW)
    )


def test_runtime_clock_parsing_is_loud() -> None:
    assert parse_runtime_clock("2026-06-15T18:04:00") == NOW
    for bad in (None, "", "어제", 20260615):
        with pytest.raises(RuntimeClockError):
            parse_runtime_clock(bad)


# ─── 실행 계획 · record validation ───────────────────────────────────────────────────
def _rules():
    return (
        EffectiveFieldBindingRule("f_name", "SOURCE", FromSource("name", None, _POLICY_ID)),
        EffectiveFieldBindingRule("f_today", RUNTIME_DATE, RuntimeDate("%Y-%m-%d", _POLICY_ID)),
    )


def _plan(rules=None):
    rules = rules or _rules()
    keys = ("name",)
    basis = _base_basis()
    binding = EffectiveFieldBindingBasis(
        effective_active_binding_rules=rules,
        active_binding_digest=active_binding_digest(rules),
        required_source_keys=keys,
        required_source_key_set_digest=required_source_key_set_digest(keys),
    )
    return build_sealed_plan(
        execution_basis=dataclasses.replace(basis, field_binding=binding),
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


def _current(plan) -> SealedExecutionPlanValue:
    basis = plan.execution_basis
    return SealedExecutionPlanValue(
        qualification_profile_id="profile-1",
        template_application_id=basis.template.template_application_id,
        contract_semantics=ExecutionContractSemantics.from_contract_set(basis.contracts),
        exact_template_execution_basis=basis.template,
        effective_selection_basis=basis.selection,
        effective_field_binding_basis=basis.field_binding,
        active_field_requirements=plan.active_field_requirements,
        ordered_operations=plan.ordered_operations,
        plan_schema_version=plan.plan_schema_version,
        canonical_encoding_version=plan.canonical_encoding_version,
    )


def test_plan_seals_the_rule_not_the_clock() -> None:
    encoded = encode_value_expression(RuntimeDate("kor", _POLICY_ID))
    assert encoded == {
        "kind": RUNTIME_DATE,
        "format_kind": "date",
        "format_code": "kor",
        "document_content_value_policy_id": _POLICY_ID,
    }
    plan = _plan()
    # 봉인 값에는 어떤 시각도 들지 않는다 — 같은 규칙이면 날이 바뀌어도 같은 Plan 이다.
    assert "2026" not in repr(plan.active_field_requirements)


def test_vdr_renders_the_runtime_date_from_the_given_clock() -> None:
    plan = _plan()
    vdr = validate_data_record_against_plan(
        plan=plan,
        snapshot=_snapshot(),
        validated_at="2099-01-01T00:00:00",  # provenance — 값의 출처가 아니다
        runtime_clock="2026-06-15T18:04:00",
    )
    assert isinstance(vdr, ValidatedDataRecord), vdr
    assert dict(vdr.document_values_in_order())["f_today"] == "2026-06-15"


def test_runtime_date_is_never_missing_or_marked() -> None:
    plan = _current(_plan())
    blank_row = _snapshot(name="")  # 소스 칸이 비어도 실행 시각 값은 선다
    result = validate_data_record_against_current_value(
        plan=plan, snapshot=blank_row, validated_at=_CLOCK, runtime_clock=_CLOCK
    )
    assert isinstance(result, CurrentValidatedDataRecord), result
    values = dict(result.document_values_in_order())
    assert values["f_today"] == "2026-03-04"
    facts = result.validation_provenance.validation_facts
    assert f"{MISSING_VALUE_MARKED}:f_today" not in facts
    assert f"{MISSING_VALUE_MARKED}:f_name" in facts


def test_a_batch_shares_one_runtime_clock() -> None:
    plan = _current(_plan())
    results = validate_data_records_against_current_value(
        plan=plan,
        snapshots=(_snapshot(identity="r1"), _snapshot(identity="r2")),
        validated_at=_CLOCK,
        runtime_clock="2026-06-15T23:59:59",
    )
    assert {dict(r.document_values_in_order())["f_today"] for r in results} == {"2026-06-15"}


@pytest.mark.parametrize("clock", [None, "", "not-a-time"])
def test_missing_runtime_clock_is_a_context_error_not_now(clock) -> None:
    result = validate_data_record_against_plan(
        plan=_plan(), snapshot=_snapshot(), validated_at=_CLOCK, runtime_clock=clock
    )
    assert isinstance(result, RecordValidationContextError), result
    assert result.code == RUNTIME_CLOCK_UNAVAILABLE


def test_plans_without_runtime_dates_need_no_clock() -> None:
    rules = (_rules()[0],)
    result = validate_data_record_against_plan(
        plan=_plan(rules), snapshot=_snapshot(), validated_at=_CLOCK
    )
    assert isinstance(result, ValidatedDataRecord), result


@pytest.mark.parametrize(
    "mutation",
    [
        {"format_kind": "amount"},
        {"format_kind": None},
        {"format_code": None},
        {"text_slice": {"mode": "chars", "start": 1}},
        {"source_key": "name"},
    ],
)
def test_a_malformed_runtime_date_requirement_is_closed(mutation) -> None:
    plan = _current(_plan())
    requirements = [dict(r) for r in plan.active_field_requirements]
    for requirement in requirements:
        if requirement["field_id"] == "f_today":
            requirement["value_expression"] = {**requirement["value_expression"], **mutation}
    forged = dataclasses.replace(plan, active_field_requirements=tuple(requirements))
    result = validate_data_record_against_current_value(
        plan=forged, snapshot=_snapshot(), validated_at=_CLOCK, runtime_clock=_CLOCK
    )
    assert isinstance(result, RecordValidationContextError), result
    assert result.code == UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT


# ─── 파일 이름 — 한 시각(RC-02) ─────────────────────────────────────────────────────
def _resolve_current(plan, *, pattern, inactive_rules=(), vdr_clock, delivery_clock):
    basis = gd.build_delivery_binding_basis(
        base_template_application_id="app-1",
        field_binding_authority_revision="rev-7",
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern=pattern,
        active_field_ids=[r["field_id"] for r in plan.active_field_requirements],
        binding_rules=inactive_rules,
    )
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis), basis
    snapshot = _snapshot()
    record = validate_data_record_against_current_value(
        plan=plan, snapshot=snapshot, validated_at=vdr_clock, runtime_clock=vdr_clock
    )
    assert isinstance(record, CurrentValidatedDataRecord), record
    return basis, gd.resolve_current_generation_delivery(
        sealed_execution_plan=plan,
        ordered_validated_records=(record,),
        ordered_raw_snapshots=(snapshot,),
        delivery_binding_basis=basis,
        exact_pattern=pattern,
        captured_delivery_clock=delivery_clock,
        run_delivery_intent=RunDeliveryIntent("C:/out", "ADD_SUFFIX"),
        path_occupancy=gd.PathOccupancyObservation("C:/out", (), delivery_clock),
    )


def test_active_runtime_token_uses_the_delivery_clock_like_the_date_token() -> None:
    """미리보기 VDR 은 자정 전, 배달 준비는 자정 뒤 — 이름의 두 날짜가 배달 시각 하나를 말한다."""
    plan = _current(_plan())
    _basis, result = _resolve_current(
        plan,
        pattern="{{date:%Y%m%d}}-{{f_today}}-{{f_name}}",
        vdr_clock="2026-06-15T23:59:59",
        delivery_clock="2026-06-16T00:00:01",
    )
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert result.ordered_items[0].resolved_output_relative_path == "20260616-2026-06-16-홍길동.hwpx"


def test_inactive_runtime_token_is_sealed_as_a_rule_and_rendered_from_the_delivery_clock() -> None:
    plan = _current(_plan((_rules()[0],)))  # 「오늘 날짜」 Field 가 이번 실행에서 비활성
    inactive = _today("f_later", code="%Y.%m.%d")
    basis, result = _resolve_current(
        plan,
        pattern="{{f_name}}-{{f_later}}",
        inactive_rules=(inactive,),
        vdr_clock="2026-06-15T09:00:00",
        delivery_clock="2026-06-16T09:00:00",
    )
    (requirement,) = basis.output_name_requirements
    assert dict(requirement.value_expression) == {
        "kind": RUNTIME_DATE,
        "format_kind": "date",
        "format_code": "%Y.%m.%d",
        "document_content_value_policy_id": POLICY.policy_id,
    }
    assert isinstance(result, gd.CurrentResolvedDelivery), result
    assert result.ordered_items[0].resolved_output_relative_path == "홍길동-2026.06.16.hwpx"


def test_sealed_resolver_names_runtime_tokens_from_the_captured_clock() -> None:
    plan = _plan()
    snapshot = _snapshot()
    vdr = validate_data_record_against_plan(
        plan=plan, snapshot=snapshot, validated_at=_CLOCK, runtime_clock=_CLOCK
    )
    assert isinstance(vdr, ValidatedDataRecord), vdr
    pattern = "{{f_today}}-{{date:%Y%m%d}}"
    basis = gd.build_delivery_binding_basis(
        base_template_application_id="app-1",
        field_binding_authority_revision="rev-7",
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern=pattern,
        active_field_ids=[r["field_id"] for r in plan.active_field_requirements],
        binding_rules=(),
    )
    assert isinstance(basis, gd.GenerationDeliveryBindingBasis), basis
    result = gd.resolve_generation_delivery_plan(
        sealed_execution_plan=plan,
        exact_pattern=pattern,
        filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID,
        delivery_binding_basis=basis,
        ordered_raw_snapshots=(snapshot,),
        ordered_validated_records=(vdr,),
        captured_delivery_clock=_CLOCK,
        output_directory_basis="C:/out",
        overwrite_policy=gd.OVERWRITE_EXISTING,
    )
    assert isinstance(result, gd.ResolvedGenerationDeliveryPlan), result
    (item,) = result.ordered_items
    assert item.resolved_output_relative_path == "2026-03-04-20260304.hwpx"
    # 이름의 「오늘 날짜」 = 같은 시각으로 만든 VDR 의 본문 값.
    assert dict(vdr.document_values_in_order())["f_today"] == "2026-03-04"


def test_runtime_token_without_a_clock_is_closed() -> None:
    with pytest.raises(gd._DeliveryContextSignal):
        gd.resolve_delivery_field_value(
            gd._encode_delivery_value_expression(_today()), _snapshot()
        )
    value = gd.resolve_delivery_field_value(
        gd._encode_delivery_value_expression(_today(code="%Y.%m.%d")),
        _snapshot(),
        clock=NOW,
    )
    assert value == "2026.06.15"
