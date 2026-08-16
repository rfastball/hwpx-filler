"""S5 Field Binding 의미 언어 — 값·소스 스키마·바인딩 규칙 계약 (S5-01 · #697).

이 모듈이 소유하는 것: ``binding-value/v1`` 타입 값 모델(:class:`CanonicalBindingValue`
합타입), ``source-schema/v1`` exact key 계약, ``field-binding/v1`` 규칙 semantic 모델과
exclusivity 불변식, ``document-content-value/v1`` 값 정책, Intentional Blank 의미,
그리고 이 slice 국소 canonical byte framing·digest.

여기는 store·fence·Mapping legacy·Template Structure projection·Active Field 계산·native HWPX
타입을 **모른다**(Domain 은 순수). legacy 재해석·revision 저장·migration/review 결선은 위층이 진다.

canonical byte framing 은 S5-06 이 닫을 정본 digest set 이전의 **이 slice 국소 인코딩**이다
(length-prefixed UTF-8 위 sha256). 값 문법·semantic equality 는 이 이슈가 소유한다.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

_U32_MAX = 0xFFFF_FFFF

# semantic 버전 — 코드·문서 단일 출처.
FIELD_BINDING_SEMANTIC_VERSION = "field-binding/v1"
SOURCE_SCHEMA_VERSION = "source-schema/v1"
BINDING_VALUE_VERSION = "binding-value/v1"
DOCUMENT_CONTENT_VALUE_POLICY_VERSION = "document-content-value/v1"

# 이 slice 국소 canonical framing magic(8 bytes 고정).
_BINDING_MAGIC = b"HFBIND1\0"
_SCHEMA_MAGIC = b"HFSSC1\0\0"

# binding kind 어휘 — logical Field 하나당 정확히 하나만 유효하다.
SOURCE = "SOURCE"
CONSTANT = "CONSTANT"
INTENTIONAL_BLANK = "INTENTIONAL_BLANK"
BINDING_KINDS = (SOURCE, CONSTANT, INTENTIONAL_BLANK)

# SOURCE/CONSTANT 가 나르는 값 유형 — CanonicalBindingValue 변형과 1:1.
EXACT_TEXT = "EXACT_TEXT"
DECIMAL = "DECIMAL"
DATE = "DATE"
DATETIME = "DATETIME"
BOOLEAN = "BOOLEAN"
VALUE_TYPES = (EXACT_TEXT, DECIMAL, DATE, DATETIME, BOOLEAN)

# Intentional Blank 의 exact plan 의미(S5-01 고정).
EXACT_BLANK_POLICY = "WRITE_EMPTY_TEXT_PRESERVE_FIELD"

# whitespace 정책 어휘 — legacy strip 은 명시 후보로만 등장한다(암묵 적용 금지).
WHITESPACE_PRESERVE_EXACT = "PRESERVE_EXACT"
WHITESPACE_STRIP_LEADING_TRAILING = "STRIP_LEADING_TRAILING"


class FieldBindingError(Exception):
    """S5 Field Binding 의미 오류의 뿌리 — 소비자는 ``.code`` 로 분기한다."""

    code = "FIELD_BINDING_ERROR"


class FieldBindingInputIntegrityError(FieldBindingError):
    code = "FIELD_BINDING_INPUT_INTEGRITY_ERROR"


class SourceSchemaDuplicateKeyError(FieldBindingError):
    code = "SOURCE_SCHEMA_DUPLICATE_KEY"


class UnsupportedFieldBindingContractError(FieldBindingError):
    code = "UNSUPPORTED_FIELD_BINDING_CONTRACT"


class UnsupportedFieldValueTypeError(FieldBindingError):
    code = "UNSUPPORTED_FIELD_VALUE_TYPE"


class UnsupportedDocumentValuePolicyError(FieldBindingError):
    code = "UNSUPPORTED_DOCUMENT_VALUE_POLICY"


# ─── 텍스트·스칼라 검증 ──────────────────────────────────────────────────────────
def _require_scalar_text(value: object, what: str, *, allow_empty: bool = False) -> str:
    """유효 Unicode scalar sequence 만 통과(lone surrogate 거절). trim·normalize 0."""
    if not isinstance(value, str):
        raise FieldBindingInputIntegrityError(f"{what} 는 문자열이어야 한다")
    if not allow_empty and value == "":
        raise FieldBindingInputIntegrityError(f"{what} 는 비어 있을 수 없다")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogate·invalid scalar
        raise FieldBindingInputIntegrityError(
            f"{what} 에 유효하지 않은 Unicode scalar"
        ) from exc
    return value


# ─── binding-value/v1 값 모델 ────────────────────────────────────────────────────
_DECIMAL_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class ExactText:
    """exact logical text — 빈 문자열도 유효 값이다(INTENTIONAL_BLANK 과 다르다)."""

    text: str

    def __post_init__(self) -> None:
        _require_scalar_text(self.text, "ExactText", allow_empty=True)


@dataclass(frozen=True)
class CanonicalDecimal:
    """exact decimal literal — JSON float identity·NaN·Infinity·지수표기 거절.

    literal 문자열을 그대로 보존한다(``"1.50"`` ≠ ``"1.5"``). Python repr 로 재구성하지 않는다.
    """

    literal: str

    def __post_init__(self) -> None:
        _require_scalar_text(self.literal, "CanonicalDecimal")
        if not _DECIMAL_RE.fullmatch(self.literal):
            raise FieldBindingInputIntegrityError(
                f"CanonicalDecimal literal 이 canonical 십진수가 아니다: {self.literal!r}"
            )


@dataclass(frozen=True)
class CanonicalDate:
    """exact ISO 날짜(YYYY-MM-DD). locale·implicit timezone 없음."""

    iso: str

    def __post_init__(self) -> None:
        _require_scalar_text(self.iso, "CanonicalDate")
        if not _DATE_RE.fullmatch(self.iso):
            raise FieldBindingInputIntegrityError(f"CanonicalDate 형식 오류: {self.iso!r}")
        try:
            _dt.date.fromisoformat(self.iso)
        except ValueError as exc:
            raise FieldBindingInputIntegrityError(
                f"CanonicalDate 가 실제 날짜가 아니다: {self.iso!r}"
            ) from exc


@dataclass(frozen=True)
class CanonicalDateTime:
    """exact ISO 일시 — **명시 timezone offset 필수**(implicit timezone 거절)."""

    iso: str

    def __post_init__(self) -> None:
        _require_scalar_text(self.iso, "CanonicalDateTime")
        try:
            parsed = _dt.datetime.fromisoformat(self.iso)
        except ValueError as exc:
            raise FieldBindingInputIntegrityError(
                f"CanonicalDateTime 파싱 실패: {self.iso!r}"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise FieldBindingInputIntegrityError(
                f"CanonicalDateTime 은 명시 timezone offset 이 있어야 한다: {self.iso!r}"
            )


@dataclass(frozen=True)
class CanonicalBoolean:
    value: bool

    def __post_init__(self) -> None:
        if not isinstance(self.value, bool):
            raise FieldBindingInputIntegrityError("CanonicalBoolean 은 bool 이어야 한다")


# 합타입 — None 은 변형으로 쓰지 않는다.
CanonicalBindingValue = (
    ExactText | CanonicalDecimal | CanonicalDate | CanonicalDateTime | CanonicalBoolean
)


def _encode_value(value: CanonicalBindingValue) -> bytes:
    if isinstance(value, ExactText):
        return b"\x01" + _text(value.text)
    if isinstance(value, CanonicalDecimal):
        return b"\x02" + _text(value.literal)
    if isinstance(value, CanonicalDate):
        return b"\x03" + _text(value.iso)
    if isinstance(value, CanonicalDateTime):
        return b"\x04" + _text(value.iso)
    if isinstance(value, CanonicalBoolean):
        return b"\x05" + (b"\x01" if value.value else b"\x00")
    raise FieldBindingInputIntegrityError("미지원 CanonicalBindingValue")  # pragma: no cover - 합타입 소진


def value_type_of(value: CanonicalBindingValue) -> str:
    """값 변형의 value_type 코드 — SOURCE 규칙 value_type 과 대조에 쓴다."""
    if isinstance(value, ExactText):
        return EXACT_TEXT
    if isinstance(value, CanonicalDecimal):
        return DECIMAL
    if isinstance(value, CanonicalDate):
        return DATE
    if isinstance(value, CanonicalDateTime):
        return DATETIME
    if isinstance(value, CanonicalBoolean):
        return BOOLEAN
    raise UnsupportedFieldValueTypeError("미지원 값 유형")  # pragma: no cover - 합타입 소진


# ─── document-content-value/v1 정책 ──────────────────────────────────────────────
@dataclass(frozen=True)
class DocumentContentValuePolicy:
    """logical text resolution 과 XML escaping 을 분리한 값 정책.

    ``escaping_responsibility`` 가 NATIVE_MATERIALIZER 면 XML escaping 은 S6 native
    materializer 몫이고, 이 계층은 logical Unicode text 만 생산한다(VDR producer).
    """

    policy_id: str
    line_break_policy: str
    whitespace_policy: str
    escaping_responsibility: str
    native_text_write_policy: str

    def __post_init__(self) -> None:
        for name in (
            "policy_id",
            "line_break_policy",
            "whitespace_policy",
            "escaping_responsibility",
            "native_text_write_policy",
        ):
            _require_scalar_text(getattr(self, name), name)


DOCUMENT_CONTENT_VALUE_POLICY_V1 = DocumentContentValuePolicy(
    policy_id="document-content-value/v1",
    line_break_policy="PRESERVE_LOGICAL_LINE_BREAKS",
    whitespace_policy=WHITESPACE_PRESERVE_EXACT,
    escaping_responsibility="NATIVE_MATERIALIZER",  # XML escaping 은 S6 소유
    native_text_write_policy="WRITE_LOGICAL_TEXT_NODE",
)

# legacy 가 암묵으로 strip 하던 자리를 명시 정책으로 옮길 때 제시하는 후보(자동 적용 금지).
DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP = DocumentContentValuePolicy(
    policy_id="document-content-value/legacy-strip-v1",
    line_break_policy="PRESERVE_LOGICAL_LINE_BREAKS",
    whitespace_policy=WHITESPACE_STRIP_LEADING_TRAILING,
    escaping_responsibility="NATIVE_MATERIALIZER",
    native_text_write_policy="WRITE_LOGICAL_TEXT_NODE",
)

_DOCUMENT_VALUE_POLICIES: dict[str, DocumentContentValuePolicy] = {
    p.policy_id: p
    for p in (
        DOCUMENT_CONTENT_VALUE_POLICY_V1,
        DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
    )
}


def resolve_document_value_policy(policy_id: str) -> DocumentContentValuePolicy:
    """unknown policy 를 latest/default 로 폴백하지 않고 시끄럽게 거절한다."""
    policy = _DOCUMENT_VALUE_POLICIES.get(policy_id)
    if policy is None:
        raise UnsupportedDocumentValuePolicyError(f"미지원 문서 값 정책: {policy_id!r}")
    return policy


# ─── field-binding/v1 semantic contract registry ─────────────────────────────────
_SUPPORTED_SEMANTIC_CONTRACTS = frozenset({FIELD_BINDING_SEMANTIC_VERSION})
_SUPPORTED_SOURCE_SCHEMA_CONTRACTS = frozenset({SOURCE_SCHEMA_VERSION})


def require_field_binding_contract(contract_id: str) -> str:
    if contract_id not in _SUPPORTED_SEMANTIC_CONTRACTS:
        raise UnsupportedFieldBindingContractError(
            f"미지원 field-binding contract: {contract_id!r}"
        )
    return contract_id


def require_source_schema_contract(contract_id: str) -> str:
    if contract_id not in _SUPPORTED_SOURCE_SCHEMA_CONTRACTS:
        raise UnsupportedFieldBindingContractError(
            f"미지원 source-schema contract: {contract_id!r}"
        )
    return contract_id


def require_value_type(value_type: str) -> str:
    if value_type not in VALUE_TYPES:
        raise UnsupportedFieldValueTypeError(f"미지원 값 유형: {value_type!r}")
    return value_type


# ─── field-binding/v1 규칙 모델 ──────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldBindingRule:
    """한 logical Field 의 exact 바인딩 규칙 — kind 별 필드 존재/부재가 exclusivity 를 강제한다."""

    field_id: str
    binding_kind: str
    document_content_value_policy: DocumentContentValuePolicy
    source_key: str | None = None
    value_type: str | None = None
    format_code: str | None = None
    canonical_constant_value: CanonicalBindingValue | None = None

    def __post_init__(self) -> None:
        _require_scalar_text(self.field_id, "field_id")
        if self.binding_kind not in BINDING_KINDS:
            raise FieldBindingInputIntegrityError(
                f"미지원 binding_kind: {self.binding_kind!r}"
            )
        if not isinstance(
            self.document_content_value_policy, DocumentContentValuePolicy
        ):
            raise FieldBindingInputIntegrityError(
                "document_content_value_policy 는 DocumentContentValuePolicy 이어야 한다"
            )
        resolve_document_value_policy(self.document_content_value_policy.policy_id)
        if self.format_code is not None:
            _require_scalar_text(self.format_code, "format_code", allow_empty=True)
        if self.binding_kind == SOURCE:
            self._require_source()
        elif self.binding_kind == CONSTANT:
            self._require_constant()
        else:  # INTENTIONAL_BLANK
            self._require_blank()

    def _require_source(self) -> None:
        _require_scalar_text(self.source_key, "source_key", allow_empty=True)
        if self.value_type is None:
            raise FieldBindingInputIntegrityError("SOURCE 규칙은 value_type 이 필요하다")
        require_value_type(self.value_type)
        if self.canonical_constant_value is not None:
            raise FieldBindingInputIntegrityError(
                "SOURCE 규칙은 constant 값을 가질 수 없다(kind 합성 금지)"
            )

    def _require_constant(self) -> None:
        if self.canonical_constant_value is None:
            raise FieldBindingInputIntegrityError("CONSTANT 규칙은 canonical 값이 필요하다")
        if not isinstance(
            self.canonical_constant_value,
            (ExactText, CanonicalDecimal, CanonicalDate, CanonicalDateTime, CanonicalBoolean),
        ):
            raise FieldBindingInputIntegrityError(
                "canonical_constant_value 가 CanonicalBindingValue 가 아니다"
            )
        if self.source_key is not None or self.value_type is not None:
            raise FieldBindingInputIntegrityError(
                "CONSTANT 규칙은 source_key·value_type 을 가질 수 없다(kind 합성 금지)"
            )

    def _require_blank(self) -> None:
        if (
            self.source_key is not None
            or self.value_type is not None
            or self.canonical_constant_value is not None
        ):
            raise FieldBindingInputIntegrityError(
                "INTENTIONAL_BLANK 규칙은 source/value/constant 를 가질 수 없다(kind 합성 금지)"
            )


def require_single_rule_per_field(rules: Iterable[FieldBindingRule]) -> tuple[
    FieldBindingRule, ...
]:
    """logical Field 하나당 effective 규칙 정확히 하나 — 중복 field_id 는 exclusivity 위반."""
    seen: set[str] = set()
    ordered: list[FieldBindingRule] = []
    for rule in rules:
        if not isinstance(rule, FieldBindingRule):
            raise FieldBindingInputIntegrityError("규칙이 FieldBindingRule 이 아니다")
        if rule.field_id in seen:
            raise FieldBindingInputIntegrityError(
                f"한 Field 에 규칙이 둘 이상이다(exclusivity 위반): {rule.field_id!r}"
            )
        seen.add(rule.field_id)
        ordered.append(rule)
    return tuple(ordered)


# ─── source-schema/v1 key 계약 ───────────────────────────────────────────────────
def validate_source_schema_keys(keys: Iterable[str]) -> tuple[str, ...]:
    """exact Unicode·case-sensitive·whitespace 보존. duplicate exact key 는 loud error."""
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        _require_scalar_text(key, "source_schema_key", allow_empty=True)
        if key in seen:
            raise SourceSchemaDuplicateKeyError(f"source schema 중복 exact key: {key!r}")
        seen.add(key)
        ordered.append(key)
    return tuple(ordered)


# ─── 이 slice 국소 canonical framing·digest ─────────────────────────────────────
def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:  # pragma: no cover - 4GB 초과 텍스트는 발생하지 않는다
        raise FieldBindingInputIntegrityError("canonical text 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _opt_text(value: str | None) -> bytes:
    if value is None:
        return b"\x00"
    return b"\x01" + _text(value)


def _u32(value: int) -> bytes:
    if value < 0 or value > _U32_MAX:  # pragma: no cover - u32 범위 밖 count 는 발생하지 않는다
        raise FieldBindingInputIntegrityError("canonical count 가 u32 범위 초과")
    return value.to_bytes(4, "big")


def _encode_rule(rule: FieldBindingRule) -> bytes:
    out = bytearray()
    out += _text(rule.field_id)
    out += _text(rule.binding_kind)
    out += _text(rule.document_content_value_policy.policy_id)
    out += _opt_text(rule.source_key)
    out += _opt_text(rule.value_type)
    out += _opt_text(rule.format_code)
    if rule.canonical_constant_value is None:
        out += b"\x00"
    else:
        out += b"\x01" + _encode_value(rule.canonical_constant_value)
    return bytes(out)


def canonicalize_binding_rules(rules: Iterable[FieldBindingRule]) -> bytes:
    """field-binding/v1 규칙 집합의 정본 bytes — 저장 순서 무관, field_id UTF-8 byte 정렬."""
    ordered = require_single_rule_per_field(rules)
    out = bytearray()
    out += _BINDING_MAGIC
    out += _text(FIELD_BINDING_SEMANTIC_VERSION)
    out += _u32(len(ordered))
    for rule in sorted(ordered, key=lambda r: r.field_id.encode("utf-8")):
        encoded = _encode_rule(rule)
        out += _u32(len(encoded))
        out += encoded
    return bytes(out)


def digest_binding_rules(rules: Iterable[FieldBindingRule]) -> str:
    return "sha256:" + hashlib.sha256(canonicalize_binding_rules(rules)).hexdigest()


def canonicalize_source_schema(keys: Iterable[str]) -> bytes:
    """source-schema/v1 정본 bytes — canonical order = unsigned UTF-8 byte order."""
    validated = validate_source_schema_keys(keys)
    out = bytearray()
    out += _SCHEMA_MAGIC
    out += _text(SOURCE_SCHEMA_VERSION)
    out += _u32(len(validated))
    for key in sorted(validated, key=lambda k: k.encode("utf-8")):
        out += _text(key)
    return bytes(out)


def digest_source_schema(keys: Iterable[str]) -> str:
    return "sha256:" + hashlib.sha256(canonicalize_source_schema(keys)).hexdigest()
