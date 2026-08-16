"""S5-01 field-binding/v1 값·소스 스키마·규칙 semantic 모델 (#697)."""

from __future__ import annotations

import pytest

from hwpxfiller.domain.field_binding import (
    BOOLEAN,
    CONSTANT,
    DATE,
    DECIMAL,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_BLANK_POLICY,
    EXACT_TEXT,
    INTENTIONAL_BLANK,
    SOURCE,
    CanonicalBoolean,
    CanonicalDate,
    CanonicalDateTime,
    CanonicalDecimal,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    SourceSchemaDuplicateKeyError,
    UnsupportedDocumentValuePolicyError,
    UnsupportedFieldBindingContractError,
    UnsupportedFieldValueTypeError,
    canonicalize_binding_rules,
    canonicalize_source_schema,
    digest_binding_rules,
    digest_source_schema,
    require_field_binding_contract,
    require_single_rule_per_field,
    require_source_schema_contract,
    require_value_type,
    resolve_document_value_policy,
    validate_source_schema_keys,
    value_type_of,
)

POLICY = DOCUMENT_CONTENT_VALUE_POLICY_V1


def _source(field_id: str, key: str = "k") -> FieldBindingRule:
    return FieldBindingRule(field_id, SOURCE, POLICY, source_key=key, value_type=EXACT_TEXT)


# ─── typed value equality / distinctness ─────────────────────────────────────────
def test_typed_values_are_distinct_across_variants() -> None:
    assert CanonicalDecimal("1") != ExactText("1")
    assert CanonicalBoolean(True) != ExactText("true")
    assert CanonicalDecimal("1") != CanonicalDecimal("1.0")  # literal 보존
    assert ExactText("x") == ExactText("x")
    assert value_type_of(CanonicalBoolean(False)) == BOOLEAN
    assert value_type_of(CanonicalDate("2026-01-02")) == DATE


def test_exact_text_preserves_whitespace_and_empty() -> None:
    assert ExactText("  x ").text == "  x "  # trim 0
    assert ExactText("").text == ""  # 빈 문자열도 유효 값
    # NFC/NFD 는 서로 다른 스칼라열 — 정규화 추측 0.
    assert ExactText("é") != ExactText("é")


@pytest.mark.parametrize(
    "bad",
    ["NaN", "Infinity", "-Infinity", "inf", "1e5", "1,000", "", " 1", "01"],
)
def test_canonical_decimal_rejects_non_canonical(bad: str) -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        CanonicalDecimal(bad)


def test_canonical_decimal_accepts_plain_literals() -> None:
    for good in ("0", "1", "-3", "1.50", "-0.5"):
        assert CanonicalDecimal(good).literal == good


def test_canonical_date_and_datetime_validate() -> None:
    assert CanonicalDate("2026-02-28").iso == "2026-02-28"
    with pytest.raises(FieldBindingInputIntegrityError):
        CanonicalDate("2026-13-01")
    with pytest.raises(FieldBindingInputIntegrityError):
        CanonicalDate("2026/01/01")
    assert CanonicalDateTime("2026-01-01T09:00:00+09:00")
    # implicit timezone(naive) 거절.
    with pytest.raises(FieldBindingInputIntegrityError):
        CanonicalDateTime("2026-01-01T09:00:00")
    with pytest.raises(FieldBindingInputIntegrityError):
        CanonicalDateTime("not-a-datetime")


def test_lone_surrogate_rejected() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        ExactText("\ud800")
    with pytest.raises(FieldBindingInputIntegrityError):
        CanonicalBoolean("true")  # type: ignore[arg-type]


# ─── binding kind exclusivity ────────────────────────────────────────────────────
def test_source_constant_blank_shapes() -> None:
    src = FieldBindingRule("f", SOURCE, POLICY, source_key="k", value_type=DECIMAL)
    const = FieldBindingRule("f", CONSTANT, POLICY, canonical_constant_value=ExactText("v"))
    blank = FieldBindingRule("f", INTENTIONAL_BLANK, POLICY)
    assert src.binding_kind == SOURCE
    assert const.canonical_constant_value == ExactText("v")
    assert blank.canonical_constant_value is None


@pytest.mark.parametrize(
    "kwargs",
    [
        # SOURCE + constant 합성
        {"binding_kind": SOURCE, "source_key": "k", "value_type": EXACT_TEXT,
         "canonical_constant_value": ExactText("v")},
        # SOURCE 인데 value_type 없음
        {"binding_kind": SOURCE, "source_key": "k"},
        # CONSTANT + source_key 합성
        {"binding_kind": CONSTANT, "canonical_constant_value": ExactText("v"),
         "source_key": "k"},
        # CONSTANT 인데 값 없음
        {"binding_kind": CONSTANT},
        # INTENTIONAL_BLANK + source
        {"binding_kind": INTENTIONAL_BLANK, "source_key": "k"},
        # unknown kind
        {"binding_kind": "MIXED"},
    ],
)
def test_rule_kind_exclusivity_rejected(kwargs: dict) -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        FieldBindingRule("f", document_content_value_policy=POLICY, **kwargs)


def test_source_rule_unknown_value_type_rejected() -> None:
    with pytest.raises(UnsupportedFieldValueTypeError):
        FieldBindingRule("f", SOURCE, POLICY, source_key="k", value_type="FLOAT")


def test_non_string_scalar_and_format_code() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        ExactText(123)  # type: ignore[arg-type]
    # format_code(빈 문자열 허용)는 검증만 통과한다.
    rule = FieldBindingRule("f", SOURCE, POLICY, source_key="k", value_type=DATE, format_code="%Y")
    assert rule.format_code == "%Y"


def test_value_type_of_covers_all_variants() -> None:
    assert value_type_of(ExactText("x")) == EXACT_TEXT
    assert value_type_of(CanonicalDecimal("1")) == DECIMAL
    assert value_type_of(CanonicalDateTime("2026-01-01T00:00:00+09:00")) == "DATETIME"


def test_constant_value_must_be_canonical_binding_value() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        FieldBindingRule("f", CONSTANT, POLICY, canonical_constant_value="raw")  # type: ignore[arg-type]


def test_single_rule_per_field() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        require_single_rule_per_field([_source("f"), _source("f", "k2")])
    with pytest.raises(FieldBindingInputIntegrityError):
        require_single_rule_per_field(["nope"])  # type: ignore[list-item]
    assert len(require_single_rule_per_field([_source("a"), _source("b")])) == 2


def test_rule_requires_policy_object_and_known_policy() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        FieldBindingRule("f", SOURCE, "policy/v1", source_key="k", value_type=EXACT_TEXT)  # type: ignore[arg-type]


# ─── source schema ───────────────────────────────────────────────────────────────
def test_source_schema_keys_exact_and_duplicate() -> None:
    keys = validate_source_schema_keys(["b", "a", " a "])  # whitespace 보존, 서로 다름
    assert keys == ("b", "a", " a ")
    with pytest.raises(SourceSchemaDuplicateKeyError):
        validate_source_schema_keys(["a", "a"])


def test_source_schema_canonical_order_is_byte_order() -> None:
    # 저장 순서 무관, 같은 집합은 같은 canonical bytes/digest.
    assert canonicalize_source_schema(["b", "a"]) == canonicalize_source_schema(["a", "b"])
    assert digest_source_schema(["a", "b"]) == digest_source_schema(["b", "a"])
    # 대소문자 구별.
    assert digest_source_schema(["A"]) != digest_source_schema(["a"])


# ─── binding rule canonicalization / digest ──────────────────────────────────────
def test_binding_rules_digest_is_order_independent() -> None:
    a = [_source("x"), _source("y")]
    b = [_source("y"), _source("x")]
    assert canonicalize_binding_rules(a) == canonicalize_binding_rules(b)
    assert digest_binding_rules(a) == digest_binding_rules(b)
    # 규칙 내용이 다르면 digest 도 다르다.
    assert digest_binding_rules([_source("x")]) != digest_binding_rules(
        [_source("x", "other")]
    )


# ─── registries / policies (no fallback) ─────────────────────────────────────────
def test_contract_and_value_type_and_policy_registries_fail_closed() -> None:
    assert require_field_binding_contract("field-binding/v1")
    assert require_source_schema_contract("source-schema/v1")
    assert require_value_type(EXACT_TEXT)
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_field_binding_contract("field-binding/v2")
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_source_schema_contract("source-schema/v2")
    with pytest.raises(UnsupportedFieldValueTypeError):
        require_value_type("FLOAT")
    with pytest.raises(UnsupportedDocumentValuePolicyError):
        resolve_document_value_policy("document-content-value/v9")


def test_document_policy_splits_escaping_to_native_materializer() -> None:
    # XML escaping 은 S6 소유 — 이 계층은 logical text 만.
    assert POLICY.escaping_responsibility == "NATIVE_MATERIALIZER"
    assert EXACT_BLANK_POLICY == "WRITE_EMPTY_TEXT_PRESERVE_FIELD"
