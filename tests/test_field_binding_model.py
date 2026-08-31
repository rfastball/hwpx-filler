"""S5-01 field-binding/v2 값·소스 스키마·규칙 semantic 모델 (#697).

v2 는 데이터 값 유형 어휘를 물리 제거했다 — 값 알파벳은 exact text 단형이고 규칙 canonical
프레이밍은 6 슬롯(value_type 슬롯 없음)이다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.domain.field_binding import (
    BINDING_VALUE_VERSION,
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_BLANK_POLICY,
    FIELD_BINDING_SEMANTIC_VERSION,
    INTENTIONAL_BLANK,
    SOURCE,
    SOURCE_SCHEMA_VERSION,
    VALUE_KIND_NULL,
    VALUE_KIND_TEXT,
    CanonicalBindingValue,
    ExactText,
    FieldBindingInputIntegrityError,
    FieldBindingRule,
    SourceSchemaDuplicateKeyError,
    UnsupportedDocumentValuePolicyError,
    UnsupportedFieldBindingContractError,
    canonicalize_binding_rules,
    canonicalize_source_schema,
    digest_binding_rules,
    digest_source_schema,
    require_field_binding_contract,
    require_registered_document_value_policy,
    require_single_rule_per_field,
    require_source_schema_contract,
    resolve_document_value_policy,
    validate_source_schema_keys,
)

POLICY = DOCUMENT_CONTENT_VALUE_POLICY_V1


def _source(field_id: str, key: str = "k") -> FieldBindingRule:
    return FieldBindingRule(field_id, SOURCE, POLICY, source_key=key)


# ─── 값 알파벳 — 단형(v2) ────────────────────────────────────────────────────────
def test_contract_versions_are_v2() -> None:
    assert FIELD_BINDING_SEMANTIC_VERSION == "field-binding/v2"
    assert SOURCE_SCHEMA_VERSION == "source-schema/v2"
    assert BINDING_VALUE_VERSION == "binding-value/v2"


def test_tagged_value_kind_alphabet_has_one_home() -> None:
    """Plan constant 인코더와 source 값 인코더가 같은 리터럴을 각자 짓지 않는다."""
    from hwpxfiller.domain.raw_data_record import SOURCE_NULL_KIND, SOURCE_TEXT_KIND

    assert (VALUE_KIND_TEXT, VALUE_KIND_NULL) == ("TEXT", "NULL")
    assert (SOURCE_TEXT_KIND, SOURCE_NULL_KIND) == (VALUE_KIND_TEXT, VALUE_KIND_NULL)


def test_value_alphabet_is_exact_text_only() -> None:
    """값 union 이 서던 자리는 단형 별칭으로 남는다 — 타입 있는 값 생성자는 존재하지 않는다."""
    import hwpxfiller.domain.field_binding as fb

    assert CanonicalBindingValue is ExactText
    for gone in (
        "DECIMAL",
        "DATE",
        "DATETIME",
        "BOOLEAN",
        "EXACT_TEXT",
        "VALUE_TYPES",
        "CanonicalDecimal",
        "CanonicalDate",
        "CanonicalDateTime",
        "CanonicalBoolean",
        "value_type_of",
        "require_value_type",
        "UnsupportedFieldValueTypeError",
    ):
        assert not hasattr(fb, gone), gone
    assert ExactText("x") == ExactText("x")
    assert ExactText("1") != ExactText("1.0")


def test_exact_text_preserves_whitespace_and_empty() -> None:
    assert ExactText("  x ").text == "  x "  # trim 0
    assert ExactText("").text == ""  # 빈 문자열도 유효 값
    # NFC/NFD 는 서로 다른 스칼라열 — 정규화 추측 0.
    assert ExactText("é") != ExactText("é")


@pytest.mark.parametrize(
    "display_text",
    ["1,000,000", "2026.8.31", "금 오백만원", "계약 후 90일 이내", "NaN", "1e5", "예"],
)
def test_display_shaped_text_is_an_ordinary_value(display_text: str) -> None:
    """v1 에서 타입 검증이 막던 표시형 문자열이 v2 에선 그냥 값이다(#915 서사 반전)."""
    assert ExactText(display_text).text == display_text


def test_lone_surrogate_rejected() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        ExactText("\ud800")


# ─── binding kind exclusivity ────────────────────────────────────────────────────
def test_source_constant_blank_shapes() -> None:
    src = FieldBindingRule("f", SOURCE, POLICY, source_key="k")
    const = FieldBindingRule("f", CONSTANT, POLICY, canonical_constant_value=ExactText("v"))
    blank = FieldBindingRule("f", INTENTIONAL_BLANK, POLICY)
    assert src.binding_kind == SOURCE
    assert const.canonical_constant_value == ExactText("v")
    assert blank.canonical_constant_value is None


@pytest.mark.parametrize(
    "kwargs",
    [
        # SOURCE + constant 합성
        {"binding_kind": SOURCE, "source_key": "k",
         "canonical_constant_value": ExactText("v")},
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


def test_source_rule_no_longer_accepts_a_value_type() -> None:
    """삭제된 필드는 조용히 무시되지 않는다 — 생성자가 TypeError 로 거절한다."""
    with pytest.raises(TypeError):
        FieldBindingRule(  # type: ignore[call-arg]
            "f", SOURCE, POLICY, source_key="k", value_type="DECIMAL"
        )


def test_non_string_scalar_and_format_code() -> None:
    with pytest.raises(FieldBindingInputIntegrityError):
        ExactText(123)  # type: ignore[arg-type]
    # format_code(빈 문자열 허용)는 검증만 통과한다.
    rule = FieldBindingRule("f", SOURCE, POLICY, source_key="k", format_code="%Y")
    assert rule.format_code == "%Y"


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
        FieldBindingRule("f", SOURCE, "policy/v1", source_key="k")  # type: ignore[arg-type]


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


def test_source_schema_canonical_bytes_carry_the_v2_version() -> None:
    assert SOURCE_SCHEMA_VERSION.encode("utf-8") in canonicalize_source_schema(["a"])


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


def test_binding_rule_framing_has_six_slots_and_the_v2_version() -> None:
    """v2 프레이밍 실측: field_id·kind·policy_id·source_key·format_code·constant text."""
    from hwpxfiller.domain.field_binding import _encode_rule, _opt_text, _text

    rule = FieldBindingRule("f", SOURCE, POLICY, source_key="k", format_code="%Y")
    assert _encode_rule(rule) == (
        _text("f")
        + _text(SOURCE)
        + _text(POLICY.policy_id)
        + _opt_text("k")
        + _opt_text("%Y")
        + _opt_text(None)
    )
    const = FieldBindingRule("f", CONSTANT, POLICY, canonical_constant_value=ExactText(""))
    assert _encode_rule(const) == (
        _text("f")
        + _text(CONSTANT)
        + _text(POLICY.policy_id)
        + _opt_text(None)
        + _opt_text(None)
        + _opt_text("")
    )
    assert FIELD_BINDING_SEMANTIC_VERSION.encode("utf-8") in canonicalize_binding_rules(
        [rule]
    )


def test_empty_constant_text_is_not_absent_constant() -> None:
    """``ExactText("")`` 과 constant 부재는 canonical bytes 에서 갈린다(빈칸 ≠ 없음)."""
    empty = FieldBindingRule("f", CONSTANT, POLICY, canonical_constant_value=ExactText(""))
    blank = FieldBindingRule("f", INTENTIONAL_BLANK, POLICY)
    assert digest_binding_rules([empty]) != digest_binding_rules([blank])


# ─── registries / policies (no fallback) ─────────────────────────────────────────
def test_contract_and_policy_registries_fail_closed() -> None:
    assert require_field_binding_contract("field-binding/v2")
    assert require_source_schema_contract("source-schema/v2")
    # 퇴역한 v1 계약은 v2 로 풀지 않는다 — v1 은 store 마이그레이션 경로만 안다.
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_field_binding_contract("field-binding/v1")
    with pytest.raises(UnsupportedFieldBindingContractError):
        require_source_schema_contract("source-schema/v1")
    with pytest.raises(UnsupportedDocumentValuePolicyError):
        resolve_document_value_policy("document-content-value/v9")


def test_document_policy_splits_escaping_to_native_materializer() -> None:
    # XML escaping 은 S6 소유 — 이 계층은 logical text 만.
    assert POLICY.escaping_responsibility == "NATIVE_MATERIALIZER"
    assert EXACT_BLANK_POLICY == "WRITE_EMPTY_TEXT_PRESERVE_FIELD"


def test_registered_policy_id_with_altered_behavior_rejected() -> None:
    # policy_id 만 persist 되므로, 등록 id 로 동작 필드를 바꾼 객체는 loud 로 거절(#1).
    from dataclasses import replace as _replace

    diverged = _replace(POLICY, whitespace_policy="STRIP_LEADING_TRAILING")
    with pytest.raises(UnsupportedDocumentValuePolicyError):
        require_registered_document_value_policy(diverged)
    with pytest.raises(UnsupportedDocumentValuePolicyError):
        FieldBindingRule("f", SOURCE, diverged, source_key="k")
    assert require_registered_document_value_policy(POLICY) is POLICY


# ── TXT 짝(S10-04 · #861) — 값 의미는 같고 escaping 책임만 갈린다 ───────────────
def test_txt_policies_mirror_the_hwpx_pair_except_for_escaping() -> None:
    """같은 데이터가 두 매체에서 **같은 logical text** 를 내야 한다 — 갈리는 축은 하나뿐이다."""
    from hwpxfiller.domain.field_binding import (
        DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
        DOCUMENT_CONTENT_VALUE_POLICY_TXT_LEGACY_STRIP,
        DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1,
        ESCAPING_NATIVE_MATERIALIZER,
        ESCAPING_PLAINTEXT_MATERIALIZER,
        txt_document_value_policy,
    )

    for hwpx, txt in (
        (DOCUMENT_CONTENT_VALUE_POLICY_V1, DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1),
        (
            DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
            DOCUMENT_CONTENT_VALUE_POLICY_TXT_LEGACY_STRIP,
        ),
    ):
        assert txt.whitespace_policy == hwpx.whitespace_policy
        assert txt.line_break_policy == hwpx.line_break_policy
        assert hwpx.escaping_responsibility == ESCAPING_NATIVE_MATERIALIZER
        assert txt.escaping_responsibility == ESCAPING_PLAINTEXT_MATERIALIZER
        # 번역은 표 하나가 진다 — 사용자에게 같은 결정을 두 번 시키지 않는다.
        assert txt_document_value_policy(hwpx.policy_id) is txt
        assert txt_document_value_policy(txt.policy_id) is txt


def test_txt_policy_translation_refuses_a_policy_without_a_pair() -> None:
    from hwpxfiller.domain.field_binding import (
        UnsupportedDocumentValuePolicyError,
        txt_document_value_policy,
    )

    with pytest.raises(UnsupportedDocumentValuePolicyError):
        txt_document_value_policy("document-content-value/v9")
