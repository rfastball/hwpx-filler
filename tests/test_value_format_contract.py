"""field-binding/v3 표시형 계약 — 쌍의 모양·렌더 단일 출처·판 framing·legacy migration (#1081 PR0b).

legacy Mapping 의 ``type``·``fmt`` 가 문서 글자를 정한다. v3 는 그 결정을 규칙의 표시형 쌍
(``format_kind`` × ``format_code``)으로 싣고, 렌더는 legacy 와 같은 해석기 하나가 한다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.field_binding_input import (
    RUNTIME_TODAY_UNSUPPORTED,
    LegacyFieldBindingEntry,
    build_field_binding_input,
    legacy_value_format,
    prepare_legacy_field_binding_migration,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    FIELD_BINDING_SEMANTIC_VERSION,
    FIELD_BINDING_SEMANTIC_VERSION_V2,
    FIELD_BINDING_SEMANTIC_VERSION_V3,
    FORMAT_KINDS,
    SOURCE,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    UnsupportedFieldBindingContractError,
    UnsupportedValueFormatError,
    canonicalize_binding_rules,
    digest_binding_rules,
    is_current_field_binding_contract,
    render_value_format,
    require_current_field_binding_contract,
    require_field_binding_contract,
    require_value_format,
)
from hwpxfiller.domain.mapping import SOURCE_CARRIER_TYPES, apply_transform

_STRIP = DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP


def _source(field_id: str, *, kind=None, code=None, policy=_STRIP) -> FieldBindingRule:
    return FieldBindingRule(
        field_id, SOURCE, policy, source_key=field_id, format_code=code, format_kind=kind
    )


# ─── 어휘·모양 ───────────────────────────────────────────────────────────────────
def test_format_kinds_are_the_legacy_source_carrier_types() -> None:
    """표시형 kind 는 legacy 소스 carrier 유형과 같은 이름이다 — 둘이 갈리면 migration 이 깨진다."""
    assert FORMAT_KINDS == SOURCE_CARRIER_TYPES


@pytest.mark.parametrize(
    ("kind", "code"),
    [(None, None), ("amount", ""), ("amount", "{:,}"), ("date", ""), ("date", "kor"),
     ("text", "phone")],
)
def test_canonical_value_formats_are_accepted(kind, code) -> None:
    require_value_format(kind, code)


@pytest.mark.parametrize(
    ("kind", "code", "reason"),
    [
        (None, "{:,}", "kind 없이"),       # v2 가 type 을 버린 모양 — 해석기를 모른다
        ("today", "", "미지원"),            # 닫힌 어휘(#950 은 binding kind 문제)
        ("currency", "{:,}", "미지원"),
        ("amount", None, "문자열"),
        ("text", "", "(None, None)"),       # 같은 뜻의 두 번째 모양
    ],
)
def test_non_canonical_value_formats_are_loud(kind, code, reason) -> None:
    with pytest.raises(UnsupportedValueFormatError, match=reason):
        require_value_format(kind, code)


def test_format_kind_is_source_only() -> None:
    with pytest.raises(FieldBindingInputIntegrityError, match="SOURCE"):
        FieldBindingRule(
            "고정", CONSTANT, DOCUMENT_CONTENT_VALUE_POLICY_V1,
            canonical_constant_value=ExactText("값"), format_kind="amount", format_code="",
        )


def test_rule_rejects_a_malformed_kind_pair() -> None:
    with pytest.raises(FieldBindingInputIntegrityError, match="미지원 표시형"):
        _source("금액", kind="money", code="")


# ─── 렌더 = legacy 해석기 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("legacy_type", "fmt", "raw", "expected"),
    [
        ("amount", "", "24750000", "24,750,000원"),
        ("amount", "{:,}", "24750000", "24,750,000"),
        ("amount", "{:,.2f}", "1500", "1,500.00"),
        ("amount", "", "미정", "미정"),                     # 수가 아니면 원문(legacy degrade)
        ("amount", "{bad", "1500", "1500"),                  # 잘못된 코드도 원문(legacy degrade)
        ("date", "", "2026-07-17", "2026. 7. 17."),
        ("date", "y2", "2026-07-17", "'26.7.17."),
        ("date", "kor", "2026-06-15 09:00", "2026년 6월 15일 09:00"),
        ("date", "%Y.%m.%d", "2026-06-15", "2026.06.15"),
        ("date", "%H:%M", "1400", "14:00"),
        ("text", "", " 그대로 ", "그대로"),
        ("text", "phone", "01012345678", "010-1234-5678"),
        ("text", "biz", "1234567890", "123-45-67890"),
    ],
)
def test_render_matches_legacy_apply_transform(legacy_type, fmt, raw, expected) -> None:
    """migration 이 옮긴 쌍 + legacy strip 정책 = legacy ``apply_transform`` 과 같은 글자."""
    kind, code = legacy_value_format(legacy_type, fmt)
    legacy = apply_transform(legacy_type, raw, "", fmt)
    assert legacy == expected
    assert render_value_format(kind, code, raw.strip()) == legacy


def test_render_without_format_is_identity() -> None:
    assert render_value_format(None, None, " 원문 ") == " 원문 "


def test_render_refuses_unknown_kind_instead_of_passing_text_through() -> None:
    with pytest.raises(UnsupportedValueFormatError):
        render_value_format("currency", "", "1500")


# ─── 판 framing ──────────────────────────────────────────────────────────────────
#: master(field-binding/v2 시절)가 아래 규칙 집합에 대해 적던 digest — 디스크의 v2 판본은 이
#: bytes 로 봉인돼 있으므로 v2 framing 은 한 bit 도 바뀌면 안 된다.
_V2_GOLDEN = "sha256:cfa259678c366512012cc2f9de78ec98eb99f5b5a680b5d13313f5669e3bb4e1"


def _golden_rules() -> tuple[FieldBindingRule, ...]:
    return (
        FieldBindingRule("계약금액", SOURCE, _STRIP, source_key="계약금액", format_code="{:,}"),
        FieldBindingRule("사업명", SOURCE, DOCUMENT_CONTENT_VALUE_POLICY_V1, source_key="사업명"),
        FieldBindingRule(
            "고정", CONSTANT, DOCUMENT_CONTENT_VALUE_POLICY_V1,
            canonical_constant_value=ExactText("값"),
        ),
    )


def test_v2_framing_is_frozen_byte_for_byte() -> None:
    rules = _golden_rules()
    assert digest_binding_rules(rules, contract_id=FIELD_BINDING_SEMANTIC_VERSION_V2) == _V2_GOLDEN


def test_v3_framing_carries_the_kind_and_changes_identity() -> None:
    plain = (_source("금액"),)
    amount = (_source("금액", kind="amount", code=""),)
    assert digest_binding_rules(amount) != digest_binding_rules(plain)
    assert b"field-binding/v4" in canonicalize_binding_rules(amount)
    assert b"field-binding/v3" in canonicalize_binding_rules(
        amount, contract_id=FIELD_BINDING_SEMANTIC_VERSION_V3
    )
    # 같은 규칙이라도 판이 다르면 다른 bytes 다(판이 framing 을 고른다).
    assert digest_binding_rules(plain) != digest_binding_rules(
        plain, contract_id=FIELD_BINDING_SEMANTIC_VERSION_V2
    )


def test_the_two_spellings_of_no_format_share_one_v3_identity() -> None:
    """v2 시절 철자 ``(None, "")`` 는 표시형 없음이다 — 현재 판에서 ``(None, None)`` 과 한 identity."""
    require_value_format(None, "")
    assert digest_binding_rules((_source("이름", code=""),)) == digest_binding_rules(
        (_source("이름"),)
    )
    assert render_value_format(None, "", " 원문 ") == " 원문 "


def test_v2_framing_refuses_a_kind() -> None:
    with pytest.raises(FieldBindingInputIntegrityError, match="v2 판"):
        digest_binding_rules(
            (_source("금액", kind="amount", code=""),),
            contract_id=FIELD_BINDING_SEMANTIC_VERSION_V2,
        )


def test_v3_framing_refuses_a_code_without_kind() -> None:
    """v2 모양((None, code))은 현재 판으로 봉인되지 않는다 — 조용한 원문 해석 금지."""
    with pytest.raises(FieldBindingInputIntegrityError, match="표시형"):
        digest_binding_rules((_source("금액", code="{:,}"),))


def test_v2_is_readable_but_not_an_execution_contract() -> None:
    assert require_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION_V2)
    assert not is_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION_V2)
    assert is_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION)
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION_V2)
    # v3(가공 슬롯 이전 판)도 같은 자리 — 읽되 실행 입력이 되지 않는다.
    assert require_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION_V3)
    assert not is_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION_V3)
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION_V3)
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_field_binding_contract("field-binding/v5")


def test_execution_input_is_always_the_current_contract() -> None:
    field_binding = build_field_binding_input(
        workspace_instance_id="ws",
        work_authority_id="work",
        base_template_application_id="app",
        binding_rules=(_source("금액", kind="amount", code=""),),
        source_schema_keys=("금액",),
        raw_record_contract_id="raw-record/v1",
        captured_at="2026-09-29T00:00:00",
    )
    assert field_binding.field_binding_semantic_contract_id == FIELD_BINDING_SEMANTIC_VERSION


# ─── legacy Mapping → v3 migration ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("legacy_type", "fmt", "expected"),
    [
        ("text", "", (None, None)),
        ("text", "phone", ("text", "phone")),
        ("date", "", ("date", "")),
        ("date", "%Y-%m-%d", ("date", "%Y-%m-%d")),
        ("amount", "", ("amount", "")),
        ("amount", "{:,}", ("amount", "{:,}")),
    ],
)
def test_legacy_value_format_keeps_the_type_decision(legacy_type, fmt, expected) -> None:
    assert legacy_value_format(legacy_type, fmt) == expected


def test_legacy_value_format_refuses_unknown_types() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        legacy_value_format("currency", "")


def test_migration_candidates_carry_the_format_pair() -> None:
    draft = prepare_legacy_field_binding_migration(
        work_authority_id="work",
        base_template_application_id="app",
        legacy_entries=(
            LegacyFieldBindingEntry("금액", "amount", "금액", "", ""),
            LegacyFieldBindingEntry("일자", "date", "일자", "", "kor"),
            LegacyFieldBindingEntry("이름", "text", "이름", "", ""),
            LegacyFieldBindingEntry("고정", "const", "", "값", ""),
            LegacyFieldBindingEntry("오늘", "today", "", "", ""),
        ),
        captured_at="2026-09-29T00:00:00",
    )
    pairs = {c.field_id: (c.format_kind, c.format_code) for c in draft.candidate_rules}
    assert pairs == {
        "금액": ("amount", ""),
        "일자": ("date", "kor"),
        "이름": (None, None),
        "고정": (None, None),
    }
    # 「오늘 날짜」는 이 판에서도 binding kind 가 없다 — 명명 blocker 그대로(#950).
    assert [(b.field_id, b.reason) for b in draft.blockers] == [
        ("오늘", RUNTIME_TODAY_UNSUPPORTED)
    ]
