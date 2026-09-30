"""S5 Field Binding 의미 언어 — 값·소스 스키마·바인딩 규칙 계약 (S5-01 · #697).

이 모듈이 소유하는 것: ``binding-value/v2`` 값 모델(:class:`CanonicalBindingValue` — exact
logical text 단형), ``source-schema/v2`` exact key 계약, ``field-binding/v4`` 규칙 semantic
모델과 exclusivity 불변식, ``document-content-value/v1`` 값 정책, Intentional Blank 의미,
**표시형**(:data:`FORMAT_KINDS` × format code) 쌍의 계약과 렌더 단일 출처, 그리고 이 slice 국소
canonical byte framing·digest.

**표시형은 규칙이 나른다**(v3, #1081 PR0b): legacy Mapping 의 ``type``(text/date/amount)·``fmt``
는 값의 모양을 **검증**하던 값 유형 어휘(v1, 퇴역)와 달리 문서에 적히는 글자를 **정한다**
(``24750000`` → ``24,750,000원``). v2 는 ``fmt`` 만 옮기고 ``type`` 을 버려서 같은 작업이
legacy 와 managed 에서 다른 문서를 냈다. v3 는 ``format_kind`` 슬롯을 더해 그 결정을 판본에
싣고, 렌더는 legacy 와 같은 :mod:`hwpxfiller.domain.format_engine` 한 곳이 한다.
v2 판본은 읽을 수 있지만(``field-binding/v2`` 는 **outdated** 로만 지원) 실행 입력이 되지
못한다 — ``type`` 이 없어 어떤 표시형이었는지 판본만으로는 알 수 없기 때문이다.

**가공도 규칙이 나른다**(v4): 데이터 칸의 일부만 쓰는 기초 가공(:mod:`hwpxfiller.domain.text_slice`
— 글자 범위·구분자 나누기)이 ``text_slice`` 슬롯으로 판본에 실린다. 순서는 공백 정책 → 가공 →
표시형이고 렌더는 :func:`render_source_value` 한 곳이다. v3 판본도 v2 처럼 읽기만 하는 outdated
판이다 — v3 에는 가공이 설 수 없었으므로 현재 Mapping 과 그대로 일치하면 무손실로 다시 확정된다.

**값 유형 어휘는 없다**(v2): 데이터가 나르는 값은 언제나 타입 없는 텍스트다. 타입 추론은
사용자가 고른 것이 아니라 필드 이름 휴리스틱의 산물이었고, 실제 문서에 적히는 값과도 무관한
검증이었다. 값이 맞는지는 사람이 본다 — 이 계층은 존재(결측·명시 null·빈 값)만 판정한다.
표시형(format engine)과 매핑 어휘(text/date/amount/…)는 별개 축이라 그대로 산다.

여기는 store·fence·Mapping legacy·Template Structure projection·Active Field 계산·native HWPX
타입을 **모른다**(Domain 은 순수). legacy 재해석·revision 저장·migration/review 결선은 위층이 진다.

canonical byte framing 은 S5-06 이 닫을 정본 digest set 이전의 **이 slice 국소 인코딩**이다
(length-prefixed UTF-8 위 sha256). 값 문법·semantic equality 는 이 이슈가 소유한다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from . import format_engine
from .text_slice import TextSlice, TextSliceError, apply_text_slice, text_slice_from_payload

_U32_MAX = 0xFFFF_FFFF

# semantic 버전 — 코드·문서 단일 출처.
FIELD_BINDING_SEMANTIC_VERSION = "field-binding/v4"
#: 가공 슬롯이 없던 판 — 읽기만 한다(실행 입력 금지). 가공이 설 수 없었던 판이라 현재 Mapping 과
#: 일치하면 무손실로 v4 가 된다(``upgrade_outdated_binding_if_lossless``).
FIELD_BINDING_SEMANTIC_VERSION_V3 = "field-binding/v3"
#: 표시형 슬롯이 없던 판 — 읽기만 한다(실행 입력 금지, :func:`is_current_field_binding_contract`).
FIELD_BINDING_SEMANTIC_VERSION_V2 = "field-binding/v2"
SOURCE_SCHEMA_VERSION = "source-schema/v2"
BINDING_VALUE_VERSION = "binding-value/v2"
#: 문서 값 **해석** 계약 — v2 는 규칙의 표시형을 적용한다(v1 은 format 을 거절했다). 규칙이
#: 싣는 값 정책 id(``document-content-value/v1`` 등)와는 다른 축이다.
DOCUMENT_CONTENT_VALUE_POLICY_VERSION = "document-content-value/v2"

# 이 slice 국소 canonical framing magic(8 bytes 고정).
_BINDING_MAGIC = b"HFBIND1\0"
_SCHEMA_MAGIC = b"HFSSC1\0\0"

# binding kind 어휘 — logical Field 하나당 정확히 하나만 유효하다.
SOURCE = "SOURCE"
CONSTANT = "CONSTANT"
INTENTIONAL_BLANK = "INTENTIONAL_BLANK"
BINDING_KINDS = (SOURCE, CONSTANT, INTENTIONAL_BLANK)

# Intentional Blank 의 exact plan 의미(S5-01 고정).
EXACT_BLANK_POLICY = "WRITE_EMPTY_TEXT_PRESERVE_FIELD"

# whitespace 정책 어휘 — legacy strip 은 명시 후보로만 등장한다(암묵 적용 금지).
WHITESPACE_PRESERVE_EXACT = "PRESERVE_EXACT"
WHITESPACE_STRIP_LEADING_TRAILING = "STRIP_LEADING_TRAILING"

# 표시형 어휘(v3) — legacy Mapping 의 소스 carrier 유형과 같은 이름·같은 해석기다. 닫힌 집합이라
# 미지 kind 는 조용히 원문으로 풀지 않고 시끄럽게 거절한다. ``today`` 는 여기 없다: 값이 소스가
# 아니라 실행 시각에서 오는 binding kind 문제라 #950 이 따로 연다.
FORMAT_KIND_TEXT = "text"
FORMAT_KIND_DATE = "date"
FORMAT_KIND_AMOUNT = "amount"
FORMAT_KINDS = (FORMAT_KIND_TEXT, FORMAT_KIND_DATE, FORMAT_KIND_AMOUNT)


class FieldBindingError(Exception):
    """S5 Field Binding 의미 오류의 뿌리 — 소비자는 ``.code`` 로 분기한다."""

    code = "FIELD_BINDING_ERROR"


class FieldBindingInputIntegrityError(FieldBindingError):
    code = "FIELD_BINDING_INPUT_INTEGRITY_ERROR"


class SourceSchemaDuplicateKeyError(FieldBindingError):
    code = "SOURCE_SCHEMA_DUPLICATE_KEY"


class UnsupportedFieldBindingContractError(FieldBindingError):
    code = "UNSUPPORTED_FIELD_BINDING_CONTRACT"


class UnsupportedDocumentValuePolicyError(FieldBindingError):
    code = "UNSUPPORTED_DOCUMENT_VALUE_POLICY"


class UnsupportedValueFormatError(FieldBindingError):
    """표시형 쌍이 이 계약이 아는 모양이 아니다 — 원문으로 조용히 풀지 않는다."""

    code = "UNSUPPORTED_VALUE_FORMAT"


class UnsupportedTextSliceError(UnsupportedValueFormatError):
    """가공 명세가 이 계약이 아는 모양이 아니다(v4) — 값 렌더 축의 오류라 표시형 오류의 하위형이다.

    하위형으로 두는 이유: 값을 렌더하는 소비자(record validation·delivery)가 이미 표시형 오류를
    context error 로 닫는다. 새 오류 축을 따로 세우면 그중 한 자리가 잡지 못해 원문이 새어 나간다.
    """

    code = "UNSUPPORTED_TEXT_SLICE"


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


# ─── binding-value/v2 값 모델 ────────────────────────────────────────────────────
#: tagged 값 표현의 kind 어휘 — Plan constant 도 raw source 값도 같은 알파벳을 쓴다. 이 두
#: 리터럴을 쓰는 자리(compile 의 인코더, validation·delivery 의 디코더)가 갈리지 않게 여기
#: 한 곳에서만 정의한다. ``NULL`` 은 소스 값에만 나타난다(binding constant 는 항상 값이 있다).
VALUE_KIND_TEXT = "TEXT"
VALUE_KIND_NULL = "NULL"


@dataclass(frozen=True)
class ExactText:
    """exact logical text — 빈 문자열도 유효 값이다(INTENTIONAL_BLANK 과 다르다)."""

    text: str

    def __post_init__(self) -> None:
        _require_scalar_text(self.text, "ExactText", allow_empty=True)


#: 값 알파벳은 단형이다 — 데이터가 나르는 값은 언제나 타입 없는 텍스트다(v2). 별칭을 남겨
#: 두는 이유는 "여기가 값 union 이 서던 자리"라는 계약 좌표를 유지하기 위해서다.
CanonicalBindingValue = ExactText


# ─── document-content-value/v1 정책 ──────────────────────────────────────────────
# escaping 책임의 정본 값 — S6-06(#809)에서 production materializer 가 이 값을 실제로 읽어
# fail-closed 한다(문자열 재타이핑 금지). 값 자체는 기존과 동일해 canonical digest 불변이다.
ESCAPING_NATIVE_MATERIALIZER = "NATIVE_MATERIALIZER"

#: TXT 물질화의 escaping 책임(S10-04 · #861) — **escape 문법이 없는 매체**라 이 책임의 이행은
#: 항등(0회)이다. HWPX 값(NATIVE_MATERIALIZER)을 그대로 쓰지 않는 이유는 그 선언이 "XML escaping
#: 은 native serialization 이 한다"는 사실을 담고 있어서다: 그 값을 든 값이 평문에 literal 로
#: 꽂히면 escape 를 두 번 하거나(pre-escaped) 한 번도 안 한 것이 조용히 지나간다. 어휘를 갈라
#: 두면 TXT materializer 의 gate 가 그 혼선을 시끄럽게 닫는다.
ESCAPING_PLAINTEXT_MATERIALIZER = "PLAINTEXT_MATERIALIZER"


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
    escaping_responsibility=ESCAPING_NATIVE_MATERIALIZER,  # XML escaping 은 S6 소유
    native_text_write_policy="WRITE_LOGICAL_TEXT_NODE",
)

# legacy 가 암묵으로 strip 하던 자리를 명시 정책으로 옮길 때 제시하는 후보(자동 적용 금지).
DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP = DocumentContentValuePolicy(
    policy_id="document-content-value/legacy-strip-v1",
    line_break_policy="PRESERVE_LOGICAL_LINE_BREAKS",
    whitespace_policy=WHITESPACE_STRIP_LEADING_TRAILING,
    escaping_responsibility=ESCAPING_NATIVE_MATERIALIZER,
    native_text_write_policy="WRITE_LOGICAL_TEXT_NODE",
)

# TXT 쌍(S10-04 · #861) — whitespace·line-break 의미는 HWPX 쌍과 **한 글자도 다르지 않다**.
# 갈리는 것은 escaping 책임 하나뿐이라, 같은 데이터가 두 매체에서 같은 logical text 를 낸다.
DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1 = DocumentContentValuePolicy(
    policy_id="document-content-value/txt-v1",
    line_break_policy="PRESERVE_LOGICAL_LINE_BREAKS",
    whitespace_policy=WHITESPACE_PRESERVE_EXACT,
    escaping_responsibility=ESCAPING_PLAINTEXT_MATERIALIZER,
    native_text_write_policy="WRITE_PLAINTEXT_SPAN",
)

DOCUMENT_CONTENT_VALUE_POLICY_TXT_LEGACY_STRIP = DocumentContentValuePolicy(
    policy_id="document-content-value/txt-legacy-strip-v1",
    line_break_policy="PRESERVE_LOGICAL_LINE_BREAKS",
    whitespace_policy=WHITESPACE_STRIP_LEADING_TRAILING,
    escaping_responsibility=ESCAPING_PLAINTEXT_MATERIALIZER,
    native_text_write_policy="WRITE_PLAINTEXT_SPAN",
)

#: HWPX 값 정책 → 같은 값 의미를 갖는 TXT 짝. legacy Mapping 을 TXT Work 의 Binding 으로 옮길 때
#: 정책을 **새로 고르게 하지 않고** 이 표로 옮긴다 — 사용자가 이미 확정한 값 의미(공백 보존/절삭)를
#: 매체가 바뀌었다고 다시 묻는 것은 같은 결정을 두 번 시키는 것이다.
_TXT_DOCUMENT_VALUE_POLICY_BY_HWPX_ID: dict[str, DocumentContentValuePolicy] = {
    DOCUMENT_CONTENT_VALUE_POLICY_V1.policy_id: DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1,
    DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP.policy_id: (
        DOCUMENT_CONTENT_VALUE_POLICY_TXT_LEGACY_STRIP
    ),
}

_DOCUMENT_VALUE_POLICIES: dict[str, DocumentContentValuePolicy] = {
    p.policy_id: p
    for p in (
        DOCUMENT_CONTENT_VALUE_POLICY_V1,
        DOCUMENT_CONTENT_VALUE_POLICY_LEGACY_STRIP,
        DOCUMENT_CONTENT_VALUE_POLICY_TXT_V1,
        DOCUMENT_CONTENT_VALUE_POLICY_TXT_LEGACY_STRIP,
    )
}


def txt_document_value_policy(policy_id: str) -> DocumentContentValuePolicy:
    """HWPX 값 정책 id → 같은 값 의미의 TXT 정책(이미 TXT 면 그대로). 미지는 시끄럽게 거절."""
    mapped = _TXT_DOCUMENT_VALUE_POLICY_BY_HWPX_ID.get(policy_id)
    if mapped is not None:
        return mapped
    policy = resolve_document_value_policy(policy_id)
    if policy.escaping_responsibility != ESCAPING_PLAINTEXT_MATERIALIZER:
        raise UnsupportedDocumentValuePolicyError(
            f"TXT 짝이 없는 문서 값 정책: {policy_id!r}"
        )
    return policy


def resolve_document_value_policy(policy_id: str) -> DocumentContentValuePolicy:
    """unknown policy 를 latest/default 로 폴백하지 않고 시끄럽게 거절한다."""
    policy = _DOCUMENT_VALUE_POLICIES.get(policy_id)
    if policy is None:
        raise UnsupportedDocumentValuePolicyError(f"미지원 문서 값 정책: {policy_id!r}")
    return policy


def require_registered_document_value_policy(
    policy: DocumentContentValuePolicy,
) -> DocumentContentValuePolicy:
    """등록된 policy_id 를 쓰되 동작 필드가 정본과 다르면 거절한다.

    canonical byte framing·store 는 policy_id 만 보존하므로, 같은 id 로 whitespace/line-break/
    native-write 를 바꾼 객체를 통과시키면 persist·reload 후 조용히 정본으로 되돌아가 실행 동작과
    content-addressed authority 가 어긋난다. 그 divergence 를 loud 로 막는다.
    """
    registered = resolve_document_value_policy(policy.policy_id)
    if policy != registered:
        raise UnsupportedDocumentValuePolicyError(
            f"등록된 policy_id 의 동작 필드를 변경했다: {policy.policy_id!r}"
        )
    return registered


# ─── 표시형(format kind × code) 계약 ──────────────────────────────────────────────
def require_value_format(format_kind: object, format_code: object) -> None:
    """표시형 쌍의 정본 모양을 강제한다(v3). 위반은 :class:`UnsupportedValueFormatError`.

    - ``(None, None)`` — 표시형 없음: 값 그대로(legacy ``text`` + 빈 코드와 같은 뜻). v2 가 쓰던
      ``(None, "")`` 도 같은 뜻으로 받되, 현재 판 framing 은 둘을 한 모양(None)으로 적는다.
    - ``(kind, code)`` — ``kind`` ∈ :data:`FORMAT_KINDS`, ``code`` 는 문자열(``""`` = kind 기본).

    같은 뜻이 두 모양을 갖지 않게 ``("text", "")`` 는 ``(None, None)`` 으로만 적는다(content-
    address 가 갈리지 않게). kind 없는 code 는 **어느 해석기로 읽을지 모르는** 값이라 거절한다 —
    v2 가 그 모양으로 ``type`` 을 버렸고, 그걸 원문으로 푸는 것이 이 계약이 막는 조용한 손실이다.
    """
    if format_kind is None:
        if format_code not in (None, ""):
            raise UnsupportedValueFormatError(
                f"표시형 kind 없이 format code 만 있다: {format_code!r}"
            )
        return
    if format_kind not in FORMAT_KINDS:
        raise UnsupportedValueFormatError(f"미지원 표시형 kind: {format_kind!r}")
    if not isinstance(format_code, str):
        raise UnsupportedValueFormatError(
            f"표시형 {format_kind!r} 의 format code 는 문자열이어야 한다(빈 문자열 = 기본)"
        )
    try:
        _require_scalar_text(format_code, "format_code", allow_empty=True)
    except FieldBindingInputIntegrityError as exc:
        raise UnsupportedValueFormatError(str(exc)) from exc
    if format_kind == FORMAT_KIND_TEXT and format_code == "":
        raise UnsupportedValueFormatError(
            "text 기본 표시형은 (None, None) 으로 적는다(같은 뜻의 두 번째 모양 금지)"
        )


def render_value_format(
    format_kind: str | None, format_code: str | None, text: str
) -> str:
    """logical text 에 규칙의 표시형을 적용한다 — legacy 와 **같은** 해석기(단일 출처).

    legacy :func:`hwpxfiller.domain.mapping.apply_transform` 이 부르는 바로 그
    :func:`hwpxfiller.domain.format_engine.render` 다. 해석기는 관대한 시도라 파싱할 수 없는
    값·코드는 원문을 낸다 — legacy 와 byte 동일해야 하므로 그 규칙을 그대로 따른다. 표시형 쌍
    자체의 모양은 :func:`require_value_format` 이 먼저 닫는다(모르는 kind 는 원문이 아니라 거절).
    """
    require_value_format(format_kind, format_code)
    if format_kind is None:
        return text
    assert format_code is not None  # require_value_format 이 강제
    return format_engine.render(format_kind, format_code, text)


# ─── 가공(text slice) 계약 — v4 ──────────────────────────────────────────────────
def require_text_slice(text_slice: object) -> TextSlice | None:
    """가공 명세를 정본 객체로 — ``None``·:class:`TextSlice`·직렬화 사전만 받는다.

    판정은 :mod:`hwpxfiller.domain.text_slice` 한 곳이다(편집 동사가 부르는 그 판정기). 모르는 모양은
    :class:`UnsupportedTextSliceError` 로 거절한다 — 가공을 버리고 칸 전체를 쓰면 다른 글자가
    조용히 문서로 나간다.
    """
    try:
        return text_slice_from_payload(text_slice)
    except TextSliceError as exc:
        raise UnsupportedTextSliceError(str(exc)) from exc


def encode_text_slice(text_slice: TextSlice | None) -> dict[str, object] | None:
    """실행 계획·delivery basis 가 봉인하는 가공 표현(없으면 None)."""
    return None if text_slice is None else text_slice.to_dict()


def render_source_value(
    format_kind: str | None,
    format_code: str | None,
    text_slice: object,
    text: str,
) -> str:
    """소스 값 하나의 문서 글자 — **가공 → 표시형**(v4). 모든 managed 렌더의 단일 출처.

    legacy :func:`hwpxfiller.domain.mapping.apply_transform` 과 같은 순서·같은 해석기다. 가공과
    표시형의 모양은 값보다 먼저 판정한다(빈 값이라서 거짓 모양이 통과하지 않게).
    """
    require_value_format(format_kind, format_code)
    spec = require_text_slice(text_slice)
    return render_value_format(format_kind, format_code, apply_text_slice(spec, text))


# ─── field-binding semantic contract registry ────────────────────────────────────
#: 읽을 수 있는 판(저장 revision 해독용). 실행 입력은 현재 판만 된다.
_SUPPORTED_SEMANTIC_CONTRACTS = frozenset(
    {
        FIELD_BINDING_SEMANTIC_VERSION,
        FIELD_BINDING_SEMANTIC_VERSION_V3,
        FIELD_BINDING_SEMANTIC_VERSION_V2,
    }
)
_SUPPORTED_SOURCE_SCHEMA_CONTRACTS = frozenset({SOURCE_SCHEMA_VERSION})


def require_field_binding_contract(contract_id: str) -> str:
    if contract_id not in _SUPPORTED_SEMANTIC_CONTRACTS:
        raise UnsupportedFieldBindingContractError(
            f"미지원 field-binding contract: {contract_id!r}"
        )
    return contract_id


def is_current_field_binding_contract(contract_id: str) -> bool:
    """이 판본이 실행 입력이 될 수 있는 현재 판인가(outdated 판은 읽기만 한다)."""
    return contract_id == FIELD_BINDING_SEMANTIC_VERSION


def require_current_field_binding_contract(contract_id: str) -> str:
    require_field_binding_contract(contract_id)
    if not is_current_field_binding_contract(contract_id):
        raise UnsupportedFieldBindingContractError(
            f"실행 입력은 현재 field-binding contract 여야 한다: {contract_id!r}"
        )
    return contract_id


def require_source_schema_contract(contract_id: str) -> str:
    if contract_id not in _SUPPORTED_SOURCE_SCHEMA_CONTRACTS:
        raise UnsupportedFieldBindingContractError(
            f"미지원 source-schema contract: {contract_id!r}"
        )
    return contract_id


# ─── field-binding 규칙 모델 ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldBindingRule:
    """한 logical Field 의 exact 바인딩 규칙 — kind 별 필드 존재/부재가 exclusivity 를 강제한다.

    ``format_kind`` 는 v3 표시형 슬롯이다. 표시형은 SOURCE 규칙에만 선다(legacy 고정값은 서식하지
    않았다). 쌍의 정본 모양은 현재 판 canonical framing 이 :func:`require_value_format` 으로
    강제한다 — 규칙 객체는 outdated(v2) 판본의 ``(None, code)`` 모양도 읽어야 해서, 여기서는
    kind 가 섰을 때의 모양과 SOURCE 전용만 본다.

    ``text_slice`` 는 v4 가공 슬롯이다. SOURCE 규칙에만 서고(고정값에는 원본 칸이 없다) 모양은
    :func:`require_text_slice` 가 규칙 구성 시점에 다시 판정한다 — 편집 시점 판정과 같은 판정기다.
    """

    field_id: str
    binding_kind: str
    document_content_value_policy: DocumentContentValuePolicy
    source_key: str | None = None
    format_code: str | None = None
    canonical_constant_value: CanonicalBindingValue | None = None
    format_kind: str | None = None
    text_slice: TextSlice | None = None

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
        # policy_id 만 persist 되므로 동작 필드가 정본과 다른 객체는 loud 로 막는다.
        require_registered_document_value_policy(self.document_content_value_policy)
        if self.format_code is not None:
            _require_scalar_text(self.format_code, "format_code", allow_empty=True)
        if self.format_kind is not None:
            if self.binding_kind != SOURCE:
                raise FieldBindingInputIntegrityError(
                    f"표시형은 SOURCE 규칙에만 선다: {self.binding_kind!r}"
                )
            try:
                require_value_format(self.format_kind, self.format_code)
            except UnsupportedValueFormatError as exc:
                raise FieldBindingInputIntegrityError(str(exc)) from exc
        if self.text_slice is not None:
            if self.binding_kind != SOURCE:
                raise FieldBindingInputIntegrityError(
                    f"가공은 SOURCE 규칙에만 선다: {self.binding_kind!r}"
                )
            # 사전·다른 객체가 규칙에 끼면 framing·렌더가 다른 모양을 보게 된다 — 정본 객체만 받는다.
            if not isinstance(self.text_slice, TextSlice):
                raise FieldBindingInputIntegrityError("text_slice 는 TextSlice 이어야 한다")
        if self.binding_kind == SOURCE:
            self._require_source()
        elif self.binding_kind == CONSTANT:
            self._require_constant()
        else:  # INTENTIONAL_BLANK
            self._require_blank()

    def _require_source(self) -> None:
        _require_scalar_text(self.source_key, "source_key", allow_empty=True)
        if self.canonical_constant_value is not None:
            raise FieldBindingInputIntegrityError(
                "SOURCE 규칙은 constant 값을 가질 수 없다(kind 합성 금지)"
            )

    def _require_constant(self) -> None:
        if self.canonical_constant_value is None:
            raise FieldBindingInputIntegrityError("CONSTANT 규칙은 canonical 값이 필요하다")
        if not isinstance(self.canonical_constant_value, ExactText):
            raise FieldBindingInputIntegrityError(
                "canonical_constant_value 가 CanonicalBindingValue 가 아니다"
            )
        if self.source_key is not None:
            raise FieldBindingInputIntegrityError(
                "CONSTANT 규칙은 source_key 를 가질 수 없다(kind 합성 금지)"
            )

    def _require_blank(self) -> None:
        if self.source_key is not None or self.canonical_constant_value is not None:
            raise FieldBindingInputIntegrityError(
                "INTENTIONAL_BLANK 규칙은 source/constant 를 가질 수 없다(kind 합성 금지)"
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


# ─── source-schema/v2 key 계약 ───────────────────────────────────────────────────
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


def _encode_text_slice(text_slice: TextSlice | None) -> bytes:
    """가공 슬롯(v4) — 없음은 0x00, 있으면 0x01 + 방식 + 방식별 고정 칸(정수는 10진 표기)."""
    if text_slice is None:
        return b"\x00"
    out = bytearray(b"\x01")
    out += _text(text_slice.mode)
    if text_slice.delimiter is None:  # chars — start 필수, length 선택
        out += _text(str(text_slice.start))
        out += _opt_text(None if text_slice.length is None else str(text_slice.length))
    else:  # split — delimiter·index 필수
        out += _text(text_slice.delimiter)
        out += _text(str(text_slice.index))
    return bytes(out)


def _encode_rule(rule: FieldBindingRule, contract_id: str) -> bytes:
    """규칙 프레이밍 — v2 는 6 슬롯, v3 는 표시형 kind 슬롯을 source_key 뒤에 더한 7 슬롯,
    v4 는 v3 뒤에 가공 슬롯을 더한 8 슬롯.

    v2·v3 프레이밍은 **동결**이다(디스크의 판본 digest 가 이 bytes 로 적혀 있다). v2 판에는
    ``format_kind`` 가, v2·v3 판에는 ``text_slice`` 가 설 수 없다. v3 이후 판은 표시형 쌍의
    정본 모양을 강제한다.
    """
    if rule.text_slice is not None and contract_id != FIELD_BINDING_SEMANTIC_VERSION:
        raise FieldBindingInputIntegrityError(
            f"{contract_id} 판에는 가공이 없다: {rule.field_id!r}"
        )
    out = bytearray()
    out += _text(rule.field_id)
    out += _text(rule.binding_kind)
    out += _text(rule.document_content_value_policy.policy_id)
    out += _opt_text(rule.source_key)
    if contract_id == FIELD_BINDING_SEMANTIC_VERSION_V2:
        if rule.format_kind is not None:
            raise FieldBindingInputIntegrityError(
                f"field-binding/v2 판에는 표시형 kind 가 없다: {rule.field_id!r}"
            )
        out += _opt_text(rule.format_code)
    else:
        try:
            require_value_format(rule.format_kind, rule.format_code)
        except UnsupportedValueFormatError as exc:
            raise FieldBindingInputIntegrityError(
                f"{rule.field_id!r} 의 표시형이 {contract_id} 모양이 아니다: {exc}"
            ) from exc
        out += _opt_text(rule.format_kind)
        # 표시형 없음의 두 철자((None, None)·(None, ""))는 한 identity 다 — 한 모양으로 적는다.
        out += _opt_text(None if rule.format_kind is None else rule.format_code)
    out += _opt_text(
        None
        if rule.canonical_constant_value is None
        else rule.canonical_constant_value.text
    )
    if contract_id == FIELD_BINDING_SEMANTIC_VERSION:
        out += _encode_text_slice(rule.text_slice)
    return bytes(out)


def canonicalize_binding_rules(
    rules: Iterable[FieldBindingRule],
    *,
    contract_id: str = FIELD_BINDING_SEMANTIC_VERSION,
) -> bytes:
    """규칙 집합의 정본 bytes — 저장 순서 무관, field_id UTF-8 byte 정렬. 판이 framing 을 고른다."""
    require_field_binding_contract(contract_id)
    ordered = require_single_rule_per_field(rules)
    out = bytearray()
    out += _BINDING_MAGIC
    out += _text(contract_id)
    out += _u32(len(ordered))
    for rule in sorted(ordered, key=lambda r: r.field_id.encode("utf-8")):
        encoded = _encode_rule(rule, contract_id)
        out += _u32(len(encoded))
        out += encoded
    return bytes(out)


def digest_binding_rules(
    rules: Iterable[FieldBindingRule],
    *,
    contract_id: str = FIELD_BINDING_SEMANTIC_VERSION,
) -> str:
    return "sha256:" + hashlib.sha256(
        canonicalize_binding_rules(rules, contract_id=contract_id)
    ).hexdigest()


def canonicalize_source_schema(keys: Iterable[str]) -> bytes:
    """source-schema/v2 정본 bytes — canonical order = unsigned UTF-8 byte order."""
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
