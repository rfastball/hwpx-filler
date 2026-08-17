"""S5 exact batch output-name resolution + managed GenerationPlan bridge (S5-13 · #709).

이 모듈이 소유하는 것: ``filename-pattern/v1`` exact PatternToken parser(기존 :mod:`hwpxfiller.naming`
의미 보존), :class:`GenerationDeliveryBindingBasis`(inactive Field token 값 근거), batch-level
:func:`resolve_generation_delivery_plan`, resolved output path canonical payload/digest, output
blocker taxonomy, :class:`ManagedGenerationPlan` DTO, :class:`MaterializationInput` port,
runtime conformance admission bridge, managed/legacy/continuation adapter 분리.

핵심 불변식(issue #709):
- **일반 token 은 target Field ID 다**(raw source key 아님, invariant 21). Active token 은 VDR 의
  document_value 를 재사용하고, inactive token 만 별도 delivery-binding basis 에서 exact FieldBinding
  revision 으로 해석한다.
- **date·seq·duplicate suffix·item ordinal 은 batch 전체에서 한 번만 결정한다**(invariant 22).
  filename pattern 은 provenance 이고 실행 시점의 naming authority 는 resolved_output_relative_path 다.
- **S5 는 native mutation·Artifact·실제 delivery write·production Generate route cutover 를 하지
  않는다**(전부 S6). managed Plan 을 legacy generator 입력으로 변환하지 않는다(invariant 23).
- confirm-or-alarm: 미치환/미해소 token 은 조용한 빈칸이 아니라 시끄러운 blocker. unknown pattern/
  delivery/overwrite contract 는 latest fallback 없이 fail-closed.

canonical framing·digest 는 S5-06 closed set(:mod:`hwpxfiller.domain.canonical_execution_encoding`).
filename 조립(금지문자 sanitation·date/seq 서식)은 기존 :mod:`hwpxfiller.naming` 의 증명된 v1 의미를
재사용한다 — 의미를 조용히 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from hwpxfiller import naming
from hwpxfiller.application.execution_composition import (
    RuntimeMaterializerConformanceRegistry,
)
from hwpxfiller.application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
    plan_semantic_digest,
)
from hwpxfiller.application.record_validation import (
    DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
    ImmutableVdrStore,
    ValidatedDataRecord,
    verify_validated_record_completeness,
)
from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest
from hwpxfiller.domain.field_binding import (
    BOOLEAN,
    CONSTANT,
    DATE,
    DATETIME,
    DECIMAL,
    EXACT_TEXT,
    INTENTIONAL_BLANK,
    SOURCE,
    WHITESPACE_PRESERVE_EXACT,
    WHITESPACE_STRIP_LEADING_TRAILING,
    FieldBindingRule,
    UnsupportedDocumentValuePolicyError,
    require_single_rule_per_field,
    resolve_document_value_policy,
)
from hwpxfiller.domain.raw_data_record import (
    RawDataRecordSnapshot,
    SourceNull,
    encode_source_value,
    source_value_type_of,
)

# ─── contract/schema 버전(코드·문서 단일 출처) ────────────────────────────────────────────
FILENAME_PATTERN_CONTRACT_ID = "filename-pattern/v1"
DELIVERY_CONTRACT_ID = "generation-delivery/v1"
DELIVERY_BINDING_BASIS_SCHEMA = "generation-delivery-binding-basis/v1"
OUTPUT_NAME_BASIS_SCHEMA = "output-name-basis-canonical/v1"
GENERATION_DELIVERY_PLAN_SCHEMA = "generation-delivery-plan-canonical/v1"
MANAGED_GENERATION_PLAN_SCHEMA = "managed-generation-plan/v1"

# S5 정본 delivery 확장자 — naming.make_output_filename 과 같은 v1 규약.
_HWPX_EXT = ".hwpx"

# ─── overwrite policy 어휘(disk disposition 은 S6 가 집행, S5 는 planned disposition 만 기록) ──
OVERWRITE_EXISTING = "OVERWRITE_EXISTING"
SKIP_EXISTING = "SKIP_EXISTING"
FAIL_ON_EXISTING = "FAIL_ON_EXISTING"
_DISPOSITION_BY_POLICY = {
    OVERWRITE_EXISTING: "WRITE_OVERWRITE",
    SKIP_EXISTING: "WRITE_IF_ABSENT",
    FAIL_ON_EXISTING: "WRITE_FAIL_IF_EXISTS",
}

# ─── output blocker taxonomy(user-fixable — seal terminal blocker 아님) ─────────────────────
OUTPUT_NAME_TOKEN_UNRESOLVED = "OUTPUT_NAME_TOKEN_UNRESOLVED"
OUTPUT_NAME_BINDING_AMBIGUOUS = "OUTPUT_NAME_BINDING_AMBIGUOUS"
OUTPUT_NAME_VALUE_RESOLUTION_FAILED = "OUTPUT_NAME_VALUE_RESOLUTION_FAILED"
OUTPUT_NAME_PATTERN_INVALID = "OUTPUT_NAME_PATTERN_INVALID"
OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED = "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED"

# ─── context/integrity 어휘(user-fixable 로 낮추지 않는 fail-closed 실패) ─────────────────────
GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR = "GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR"
UNSUPPORTED_FILENAME_PATTERN_CONTRACT = "UNSUPPORTED_FILENAME_PATTERN_CONTRACT"
UNSUPPORTED_DELIVERY_CONTRACT = "UNSUPPORTED_DELIVERY_CONTRACT"
UNSUPPORTED_OVERWRITE_POLICY = "UNSUPPORTED_OVERWRITE_POLICY"
DELIVERY_BINDING_BASIS_INTEGRITY_ERROR = "DELIVERY_BINDING_BASIS_INTEGRITY_ERROR"
VALIDATED_RECORD_PLAN_MISMATCH = "VALIDATED_RECORD_PLAN_MISMATCH"
RAW_VALIDATED_RECORD_MISMATCH = "RAW_VALIDATED_RECORD_MISMATCH"
OUTPUT_PATH_ESCAPE_DETECTED = "OUTPUT_PATH_ESCAPE_DETECTED"
UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT = (
    "UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT"
)

# runtime admission 어휘.
MANAGED_RUN_STARTABLE = "MANAGED_RUN_STARTABLE_IN_S6"
MANAGED_RUN_CONSTRUCTION_ONLY = "MANAGED_RUN_CONSTRUCTION_ONLY_NOT_ADMITTED"

# adapter S5 exact guarantee marker — managed adapter 만 소유(legacy 는 표시하지 않는다).
S5_EXACT_DELIVERY_GUARANTEE = "s5-managed-delivery/v1"

# value expression kind(field_binding kind 와 같은 어휘).
_KIND_FROM_SOURCE = "FROM_SOURCE"
_KIND_CONSTANT = "CONSTANT"
_KIND_INTENTIONAL_BLANK = "INTENTIONAL_BLANK"

_BOOLEAN_TRUE_TEXT = "true"
_BOOLEAN_FALSE_TEXT = "false"


# ─── 예외(구성된 DTO 무결성) / 내부 signal ─────────────────────────────────────────────────
class GenerationDeliveryError(Exception):
    """S5-13 delivery 의미 오류의 뿌리 — 소비자는 ``.code`` 로 분기한다."""

    code = "GENERATION_DELIVERY_ERROR"


class DeliveryBindingBasisIntegrityError(GenerationDeliveryError):
    code = DELIVERY_BINDING_BASIS_INTEGRITY_ERROR


class ResolvedDeliveryPlanIntegrityError(GenerationDeliveryError):
    code = GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR


class ManagedGenerationPlanIntegrityError(GenerationDeliveryError):
    code = "MANAGED_GENERATION_PLAN_INTEGRITY_ERROR"


class MaterializationInputResolutionError(GenerationDeliveryError):
    code = "MATERIALIZATION_INPUT_RESOLUTION_ERROR"


class _DeliveryContextSignal(Exception):
    """평가 자체 불가(fail-closed) — 서비스 top 이 DeliveryPlanContextError 로 변환한다."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _PatternInvalidSignal(Exception):
    """malformed/unknown pattern — OUTPUT_NAME_PATTERN_INVALID blocker 로 변환한다."""


# ─── PatternToken 합타입 ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiteralSegment:
    text: str


@dataclass(frozen=True)
class ReservedDateToken:
    date_spec: str | None  # None = 기본 YYYYMMDD


@dataclass(frozen=True)
class ReservedSequenceToken:
    pad: str | None  # None = 무 pad. ``{{seq:001}}`` → pad "001"(폭 3)


@dataclass(frozen=True)
class FieldValueToken:
    field_id: str  # target logical Field ID(raw source key 아님)


PatternToken = LiteralSegment | ReservedDateToken | ReservedSequenceToken | FieldValueToken

_RESERVED_DATE = "date"
_RESERVED_SEQ = "seq"


def parse_filename_pattern(
    pattern: object, *, filename_pattern_contract_id: str
) -> tuple[PatternToken, ...]:
    """exact pattern text + contract ID → PatternToken 열(문서 순서 = filename component 조립 순서).

    unknown contract → fail-closed context signal. empty pattern·닫히지 않은 ``{{``·빈 ``{{}}``·
    inner brace 는 OUTPUT_NAME_PATTERN_INVALID(``_PatternInvalidSignal``). well-formed v1 pattern
    (``{{date}}``·``{{seq:001}}``·``{{필드}}``·리터럴)은 기존 naming 의미와 동치다 — v1 이 조용히
    출력에 누출하던 malformed brace 만 시끄럽게 거절한다(confirm-or-alarm 상향).
    """
    if filename_pattern_contract_id != FILENAME_PATTERN_CONTRACT_ID:
        raise _DeliveryContextSignal(
            UNSUPPORTED_FILENAME_PATTERN_CONTRACT,
            f"미지원 filename pattern contract: {filename_pattern_contract_id!r}",
        )
    if not isinstance(pattern, str) or pattern == "":
        raise _PatternInvalidSignal("filename pattern 이 비어 있다")
    tokens: list[PatternToken] = []
    buf: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern[i : i + 2] == "{{":
            close = pattern.find("}}", i + 2)
            if close == -1:
                raise _PatternInvalidSignal("닫히지 않은 '{{' token")
            inner = pattern[i + 2 : close]
            if inner == "" or "{" in inner or "}" in inner:
                raise _PatternInvalidSignal(f"malformed token: {pattern[i : close + 2]!r}")
            if buf:
                tokens.append(LiteralSegment("".join(buf)))
                buf = []
            head, _, spec = inner.partition(":")
            has_spec = ":" in inner
            if head == _RESERVED_DATE:
                tokens.append(ReservedDateToken(spec if has_spec else None))
            elif head == _RESERVED_SEQ:
                tokens.append(ReservedSequenceToken(spec if has_spec else None))
            else:
                tokens.append(FieldValueToken(inner))
            i = close + 2
        else:
            # 단일 '{'·짝 없는 '}' 는 v1 과 동일하게 리터럴로 취급한다(과잉 거절 금지).
            buf.append(pattern[i])
            i += 1
    if buf:
        tokens.append(LiteralSegment("".join(buf)))
    return tuple(tokens)


def pattern_field_token_ids(tokens: Iterable[PatternToken]) -> tuple[str, ...]:
    """token 열이 참조하는 Field ID(문서순·중복 제거)."""
    out: dict[str, None] = {}
    for tok in tokens:
        if isinstance(tok, FieldValueToken):
            out.setdefault(tok.field_id, None)
    return tuple(out)


# ─── inactive Field 값 표현(delivery basis 가 봉인하는 exact requirement) ──────────────────────
def _encode_delivery_value_expression(rule: FieldBindingRule) -> dict[str, Any]:
    """inactive FieldBindingRule 을 delivery basis 가 담을 canonical value expression 으로 인코딩한다.

    Active requirement(VDR 재사용)와 합치지 않는 delivery-only requirement 다 — 같은 document-value-
    resolution 계약을 쓰되 별개 basis 에 산다.
    """
    policy_id = rule.document_content_value_policy.policy_id
    if rule.binding_kind == SOURCE:
        return {
            "kind": _KIND_FROM_SOURCE,
            "source_key": rule.source_key,
            "value_type": rule.value_type,
            "document_content_value_policy_id": policy_id,
        }
    if rule.binding_kind == CONSTANT:
        assert rule.canonical_constant_value is not None  # CONSTANT 규칙 불변식
        return {
            "kind": _KIND_CONSTANT,
            "canonical_value": encode_source_value(rule.canonical_constant_value),
            "document_content_value_policy_id": policy_id,
        }
    # INTENTIONAL_BLANK — filename 으로는 항상 미해소(값 없음). basis 는 provenance 로 보존한다.
    return {
        "kind": _KIND_INTENTIONAL_BLANK,
        "document_content_value_policy_id": policy_id,
    }


@dataclass(frozen=True)
class DeliveryOutputNameRequirement:
    field_id: str
    value_expression: Mapping[str, Any]


@dataclass(frozen=True)
class GenerationDeliveryBindingBasis:
    """filename pattern 의 inactive Field token 값 근거 — Active binding 만 소유하는 Plan basis 와 분리.

    exact FieldBinding authority revision provenance 를 포함해 해당 revision 의미를 고정한다.
    inactive Field token 을 Plan basis 에 추가하지 않는다.
    """

    base_template_application_id: str
    field_binding_authority_revision: str
    filename_pattern_contract_id: str
    exact_pattern: str
    document_value_resolution_contract_id: str
    output_name_requirements: tuple[DeliveryOutputNameRequirement, ...]
    delivery_binding_basis_digest: str


def _delivery_binding_basis_payload(
    *,
    base_template_application_id: str,
    field_binding_authority_revision: str,
    filename_pattern_contract_id: str,
    exact_pattern: str,
    document_value_resolution_contract_id: str,
    requirements: Iterable[DeliveryOutputNameRequirement],
) -> dict[str, Any]:
    return {
        "delivery_binding_basis_schema": DELIVERY_BINDING_BASIS_SCHEMA,
        "base_template_application_id": base_template_application_id,
        "field_binding_authority_revision": field_binding_authority_revision,
        "filename_pattern_contract_id": filename_pattern_contract_id,
        "exact_pattern": exact_pattern,
        "document_value_resolution_contract_id": document_value_resolution_contract_id,
        # field_id UTF-8 byte order — 저장 순서가 basis identity 를 쪼개지 못하게 한다.
        "output_name_requirements": [
            {"field_id": r.field_id, "value_expression": dict(r.value_expression)}
            for r in sorted(requirements, key=lambda r: r.field_id.encode("utf-8"))
        ],
    }


def build_delivery_binding_basis(
    *,
    base_template_application_id: str,
    field_binding_authority_revision: str,
    filename_pattern_contract_id: str,
    exact_pattern: str,
    active_field_ids: Iterable[str],
    binding_rules: Iterable[FieldBindingRule],
    document_value_resolution_contract_id: str = DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
) -> GenerationDeliveryBindingBasis | DeliveryPlanBlocked | DeliveryPlanContextError:
    """pattern 의 inactive Field token 마다 exact FieldBinding revision 에서 delivery requirement 를 봉인한다.

    Active token(Plan active requirement/VDR 소유)은 basis 에 넣지 않는다. binding 없는 inactive token
    → OUTPUT_NAME_TOKEN_UNRESOLVED. 같은 field_id 에 규칙이 둘 → OUTPUT_NAME_BINDING_AMBIGUOUS.
    """
    try:
        tokens = parse_filename_pattern(
            exact_pattern, filename_pattern_contract_id=filename_pattern_contract_id
        )
    except _PatternInvalidSignal as exc:
        return DeliveryPlanBlocked(
            (DeliveryPlanBlocker(OUTPUT_NAME_PATTERN_INVALID, None, None, str(exc)),)
        )
    except _DeliveryContextSignal as sig:
        return DeliveryPlanContextError(sig.code, sig.detail)

    try:
        ordered_rules = require_single_rule_per_field(binding_rules)
    except Exception as exc:  # noqa: BLE001 — 중복 field_id 규칙 = ambiguous binding
        return DeliveryPlanBlocked(
            (DeliveryPlanBlocker(OUTPUT_NAME_BINDING_AMBIGUOUS, None, None, str(exc)),)
        )
    rule_by_field = {r.field_id: r for r in ordered_rules}
    active = set(active_field_ids)

    requirements: list[DeliveryOutputNameRequirement] = []
    blockers: list[DeliveryPlanBlocker] = []
    for field_id in pattern_field_token_ids(tokens):
        if field_id in active:
            continue  # Active token → VDR 재사용(basis 소유 아님)
        rule = rule_by_field.get(field_id)
        if rule is None:
            blockers.append(
                DeliveryPlanBlocker(
                    OUTPUT_NAME_TOKEN_UNRESOLVED,
                    None,
                    field_id,
                    f"filename token {field_id!r} 에 대응하는 Active requirement·FieldBinding 규칙이 없다",
                )
            )
            continue
        requirements.append(
            DeliveryOutputNameRequirement(
                field_id=field_id,
                value_expression=MappingProxyType(_encode_delivery_value_expression(rule)),
            )
        )
    if blockers:
        return DeliveryPlanBlocked(tuple(blockers))

    payload = _delivery_binding_basis_payload(
        base_template_application_id=base_template_application_id,
        field_binding_authority_revision=field_binding_authority_revision,
        filename_pattern_contract_id=filename_pattern_contract_id,
        exact_pattern=exact_pattern,
        document_value_resolution_contract_id=document_value_resolution_contract_id,
        requirements=requirements,
    )
    return GenerationDeliveryBindingBasis(
        base_template_application_id=base_template_application_id,
        field_binding_authority_revision=field_binding_authority_revision,
        filename_pattern_contract_id=filename_pattern_contract_id,
        exact_pattern=exact_pattern,
        document_value_resolution_contract_id=document_value_resolution_contract_id,
        output_name_requirements=tuple(requirements),
        delivery_binding_basis_digest=canonical_execution_digest(payload),
    )


def verify_delivery_binding_basis_integrity(basis: GenerationDeliveryBindingBasis) -> None:
    """저장 digest 를 payload 에서 재계산해 대조한다(claim 신뢰 금지, fail-closed)."""
    payload = _delivery_binding_basis_payload(
        base_template_application_id=basis.base_template_application_id,
        field_binding_authority_revision=basis.field_binding_authority_revision,
        filename_pattern_contract_id=basis.filename_pattern_contract_id,
        exact_pattern=basis.exact_pattern,
        document_value_resolution_contract_id=basis.document_value_resolution_contract_id,
        requirements=basis.output_name_requirements,
    )
    if canonical_execution_digest(payload) != basis.delivery_binding_basis_digest:
        raise DeliveryBindingBasisIntegrityError(
            "delivery_binding_basis_digest 가 canonical recompute 와 불일치"
        )


# ─── inactive Field 값 해석(exact requirement + raw snapshot → logical text | blocker) ───────
def _apply_whitespace_policy(text: str, whitespace_policy: str) -> str:
    if whitespace_policy == WHITESPACE_STRIP_LEADING_TRAILING:
        return text.strip()
    if whitespace_policy == WHITESPACE_PRESERVE_EXACT:
        return text
    raise _DeliveryContextSignal(
        UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
        f"미지원 whitespace policy: {whitespace_policy!r}",
    )


def _scalar_literal_text(value_type: str, literal: Any, what: str) -> str:
    if value_type == BOOLEAN:
        if not isinstance(literal, bool):
            raise _DeliveryContextSignal(
                UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
                f"{what} BOOLEAN literal 이 bool 이 아니다",
            )
        return _BOOLEAN_TRUE_TEXT if literal else _BOOLEAN_FALSE_TEXT
    if value_type in (EXACT_TEXT, DECIMAL, DATE, DATETIME):
        if not isinstance(literal, str):
            raise _DeliveryContextSignal(
                UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
                f"{what} {value_type} literal 이 문자열이 아니다",
            )
        return literal
    raise _DeliveryContextSignal(
        UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
        f"{what} 미지원 value_type: {value_type!r}",
    )


def resolve_delivery_field_value(
    value_expression: Mapping[str, Any],
    snapshot: RawDataRecordSnapshot,
) -> str | tuple[str, str]:
    """inactive Field token 값을 exact requirement + raw snapshot 에서 해석한다.

    반환: exact logical text | (blocker_code, detail). 미지원 policy/value_type/contract 는 blocker 로
    낮추지 않고 ``_DeliveryContextSignal`` 로 닫는다(fail-closed). Active token 은 이 함수를 거치지 않고
    VDR 값을 재사용한다.
    """
    try:
        policy = resolve_document_value_policy(
            str(value_expression.get("document_content_value_policy_id"))
        )
    except UnsupportedDocumentValuePolicyError as exc:
        raise _DeliveryContextSignal(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT, str(exc)
        ) from exc
    kind = value_expression.get("kind")
    if kind == _KIND_INTENTIONAL_BLANK:
        return (OUTPUT_NAME_TOKEN_UNRESOLVED, "INTENTIONAL_BLANK 은 filename token 으로 미해소")
    if kind == _KIND_CONSTANT:
        canonical = value_expression.get("canonical_value")
        if not isinstance(canonical, Mapping):
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR, "CONSTANT requirement 에 canonical_value 가 없다"
            )
        text = _scalar_literal_text(
            str(canonical.get("value_type")), canonical.get("literal"), "constant"
        )
        return _apply_whitespace_policy(text, policy.whitespace_policy)
    if kind == _KIND_FROM_SOURCE:
        source_key = value_expression.get("source_key")
        expected_type = value_expression.get("value_type")
        if not isinstance(source_key, str) or not isinstance(expected_type, str):
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                "FROM_SOURCE requirement 의 source_key/value_type 형식 불량",
            )
        if not snapshot.has_key(source_key):
            return (OUTPUT_NAME_TOKEN_UNRESOLVED, f"source key {source_key!r} 가 raw record 에 없다")
        value = snapshot.value_for(source_key)
        if isinstance(value, SourceNull):
            return (OUTPUT_NAME_TOKEN_UNRESOLVED, f"source key {source_key!r} 가 explicit null")
        assert value is not None
        actual_type = source_value_type_of(value)
        if actual_type != expected_type:
            return (
                OUTPUT_NAME_VALUE_RESOLUTION_FAILED,
                f"source key {source_key!r} 타입 {actual_type} 가 요구 타입 {expected_type} 와 불일치",
            )
        literal = encode_source_value(value)["literal"]
        text = _scalar_literal_text(expected_type, literal, f"source key {source_key!r}")
        return _apply_whitespace_policy(text, policy.whitespace_policy)
    raise _DeliveryContextSignal(
        GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
        f"미지원 delivery value expression kind: {kind!r}",
    )


# ─── batch 해석 결과 합타입 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DeliveryPlanBlocker:
    code: str
    item_ordinal: int | None
    field_id: str | None
    detail: str


@dataclass(frozen=True)
class DeliveryPlanBlocked:
    blockers: tuple[DeliveryPlanBlocker, ...]


@dataclass(frozen=True)
class DeliveryPlanContextError:
    code: str
    detail: str


@dataclass(frozen=True)
class ResolvedTokenValue:
    kind: str  # "DATE" | "SEQ" | "FIELD"
    field_id: str | None
    value: str


@dataclass(frozen=True)
class ResolvedGenerationItem:
    validated_record_ref: str
    record_identity: str
    raw_record_digest: str
    resolved_token_values: tuple[ResolvedTokenValue, ...]
    item_ordinal: int
    resolved_output_relative_path: str
    output_name_basis_digest: str
    overwrite_disposition: str


@dataclass(frozen=True)
class ResolvedGenerationDeliveryPlan:
    delivery_contract_id: str
    filename_pattern_contract_id: str
    exact_pattern: str
    captured_delivery_clock: str
    output_directory_basis: str
    overwrite_policy: str
    delivery_binding_basis_digest: str
    ordered_items: tuple[ResolvedGenerationItem, ...]
    delivery_plan_digest: str


ResolveGenerationDeliveryPlanResult = (
    ResolvedGenerationDeliveryPlan | DeliveryPlanBlocked | DeliveryPlanContextError
)


def _resolved_token_values_payload(
    values: Iterable[ResolvedTokenValue],
) -> list[dict[str, Any]]:
    return [
        {"kind": v.kind, "field_id": v.field_id, "value": v.value} for v in values
    ]


def _output_name_basis_payload(
    *,
    filename_pattern_contract_id: str,
    exact_pattern: str,
    captured_delivery_clock: str,
    validated_record_ref: str,
    record_identity: str,
    raw_record_digest: str,
    resolved_token_values: Iterable[ResolvedTokenValue],
    item_ordinal: int,
    resolved_output_relative_path: str,
    overwrite_disposition: str,
) -> dict[str, Any]:
    return {
        "output_name_basis_schema": OUTPUT_NAME_BASIS_SCHEMA,
        "filename_pattern_contract_id": filename_pattern_contract_id,
        "exact_pattern": exact_pattern,
        "captured_delivery_clock": captured_delivery_clock,
        "validated_record_ref": validated_record_ref,
        "record_identity": record_identity,
        "raw_record_digest": raw_record_digest,
        "resolved_token_values": _resolved_token_values_payload(resolved_token_values),
        "item_ordinal": item_ordinal,
        "resolved_output_relative_path": resolved_output_relative_path,
        "overwrite_disposition": overwrite_disposition,
    }


def _item_identity_payload(item: ResolvedGenerationItem) -> dict[str, Any]:
    return {
        "validated_record_ref": item.validated_record_ref,
        "record_identity": item.record_identity,
        "raw_record_digest": item.raw_record_digest,
        "resolved_token_values": _resolved_token_values_payload(item.resolved_token_values),
        "item_ordinal": item.item_ordinal,
        "resolved_output_relative_path": item.resolved_output_relative_path,
        "output_name_basis_digest": item.output_name_basis_digest,
        "overwrite_disposition": item.overwrite_disposition,
    }


def _delivery_plan_payload(
    *,
    delivery_contract_id: str,
    filename_pattern_contract_id: str,
    exact_pattern: str,
    captured_delivery_clock: str,
    output_directory_basis: str,
    overwrite_policy: str,
    delivery_binding_basis_digest: str,
    items: Iterable[ResolvedGenerationItem],
) -> dict[str, Any]:
    return {
        "generation_delivery_plan_schema": GENERATION_DELIVERY_PLAN_SCHEMA,
        "delivery_contract_id": delivery_contract_id,
        "filename_pattern_contract_id": filename_pattern_contract_id,
        "exact_pattern": exact_pattern,
        "captured_delivery_clock": captured_delivery_clock,
        "output_directory_basis": output_directory_basis,
        "overwrite_policy": overwrite_policy,
        "delivery_binding_basis_digest": delivery_binding_basis_digest,
        # 입력 순서(exact ordered batch authority) 그대로 — 재정렬 금지.
        "ordered_items": [_item_identity_payload(it) for it in items],
    }


def _guard_relative_path(name: str) -> None:
    """resolved path 가 output directory 밖으로 탈출하지 못하게 flat relative 임을 강제한다.

    field/date 값은 이미 naming.clean_filename 이 separator 를 제거하지만, pattern 리터럴은 v1 이
    청소하지 않으므로 여기서 최종 방어한다 — separator·drive·``..`` 는 OUTPUT_PATH_ESCAPE_DETECTED.
    """
    if "/" in name or "\\" in name or "\x00" in name:
        raise _DeliveryContextSignal(
            OUTPUT_PATH_ESCAPE_DETECTED, f"resolved path 에 경로 구분자: {name!r}"
        )
    if name in (".", "..") or name.startswith(".."):
        raise _DeliveryContextSignal(
            OUTPUT_PATH_ESCAPE_DETECTED, f"resolved path 가 상위 경로 참조: {name!r}"
        )
    if len(name) <= len(_HWPX_EXT):
        # 확장자만 남는(빈 stem) 이름은 조용한 빈 파일명이라 막는다.
        raise _DeliveryContextSignal(
            OUTPUT_PATH_ESCAPE_DETECTED, "resolved path 의 stem 이 비어 있다"
        )


def _render_item(
    tokens: Iterable[PatternToken],
    field_values: Mapping[str, str],
    *,
    ordinal: int,
    clock: datetime,
) -> tuple[str, tuple[ResolvedTokenValue, ...]]:
    """token 열을 filename 으로 조립한다(naming v1 sanitation·date/seq 서식 재사용).

    seq = ordinal + 1(1-based), date = batch clock. field 값은 clean_filename 으로 청소한다 —
    naming.make_output_filename 과 같은 규약. 확장자 ``.hwpx`` 를 보장한다.
    """
    parts: list[str] = []
    resolved: list[ResolvedTokenValue] = []
    for tok in tokens:
        if isinstance(tok, LiteralSegment):
            parts.append(tok.text)
        elif isinstance(tok, ReservedDateToken):
            text = naming._fmt_date(tok.date_spec, clock)
            parts.append(text)
            resolved.append(ResolvedTokenValue("DATE", None, text))
        elif isinstance(tok, ReservedSequenceToken):
            text = naming._fmt_seq(tok.pad, ordinal + 1)
            parts.append(text)
            resolved.append(ResolvedTokenValue("SEQ", None, text))
        else:  # FieldValueToken
            cleaned = naming.clean_filename(field_values[tok.field_id])
            parts.append(cleaned)
            resolved.append(ResolvedTokenValue("FIELD", tok.field_id, cleaned))
    stem = "".join(parts)
    name = stem if stem.lower().endswith(_HWPX_EXT) else stem + _HWPX_EXT
    return name, tuple(resolved)


def _dedupe_batch(base_names: list[str]) -> list[str]:
    """배치 내 같은 이름 충돌에 결정적 접미사(_1·_2…)를 붙인다(naming.OutputNamer 규칙).

    접미사는 확장자 앞에 넣는다(``stem_1.hwpx``). batch 순서로 한 번 계산한다 — item 별 독립
    재결정 금지(invariant 22).
    """
    seen: set[str] = set()
    out: list[str] = []
    for name in base_names:
        if name not in seen:
            seen.add(name)
            out.append(name)
            continue
        stem, ext = name[: -len(_HWPX_EXT)], name[-len(_HWPX_EXT) :]
        i = 1
        cand = f"{stem}_{i}{ext}"
        while cand in seen:
            i += 1
            cand = f"{stem}_{i}{ext}"
        seen.add(cand)
        out.append(cand)
    return out


def resolve_generation_delivery_plan(
    *,
    exact_pattern: str,
    filename_pattern_contract_id: str,
    delivery_binding_basis: GenerationDeliveryBindingBasis,
    ordered_raw_snapshots: Iterable[RawDataRecordSnapshot],
    ordered_validated_records: Iterable[ValidatedDataRecord],
    captured_delivery_clock: str,
    output_directory_basis: str,
    overwrite_policy: str,
    delivery_contract_id: str = DELIVERY_CONTRACT_ID,
) -> ResolveGenerationDeliveryPlanResult:
    """ordered raw snapshots + VDRs + exact pattern + captured clock → resolved output relative paths.

    순수·deterministic batch 해석. date·seq·duplicate suffix·item ordinal 을 ordered batch 전체에서
    한 번만 계산한다(invariant 22). 입력 순서가 exact ordered batch authority 다 — UI/source store
    순서를 나중에 다시 읽지 않는다. filename pattern 은 provenance, resolved_output_relative_path 가
    실행 naming authority 다.
    """
    try:
        return _resolve(
            exact_pattern=exact_pattern,
            filename_pattern_contract_id=filename_pattern_contract_id,
            delivery_binding_basis=delivery_binding_basis,
            ordered_raw_snapshots=tuple(ordered_raw_snapshots),
            ordered_validated_records=tuple(ordered_validated_records),
            captured_delivery_clock=captured_delivery_clock,
            output_directory_basis=output_directory_basis,
            overwrite_policy=overwrite_policy,
            delivery_contract_id=delivery_contract_id,
        )
    except _PatternInvalidSignal as exc:
        return DeliveryPlanBlocked(
            (DeliveryPlanBlocker(OUTPUT_NAME_PATTERN_INVALID, None, None, str(exc)),)
        )
    except _DeliveryContextSignal as sig:
        return DeliveryPlanContextError(sig.code, sig.detail)


def _resolve(
    *,
    exact_pattern: str,
    filename_pattern_contract_id: str,
    delivery_binding_basis: GenerationDeliveryBindingBasis,
    ordered_raw_snapshots: tuple[RawDataRecordSnapshot, ...],
    ordered_validated_records: tuple[ValidatedDataRecord, ...],
    captured_delivery_clock: str,
    output_directory_basis: str,
    overwrite_policy: str,
    delivery_contract_id: str,
) -> ResolveGenerationDeliveryPlanResult:
    # (1) contract fail-closed — 입력 자체 계약을 exact supported constant 와 대조한다.
    if delivery_contract_id != DELIVERY_CONTRACT_ID:
        raise _DeliveryContextSignal(
            UNSUPPORTED_DELIVERY_CONTRACT, f"미지원 delivery contract: {delivery_contract_id!r}"
        )
    if filename_pattern_contract_id != FILENAME_PATTERN_CONTRACT_ID:
        raise _DeliveryContextSignal(
            UNSUPPORTED_FILENAME_PATTERN_CONTRACT,
            f"미지원 filename pattern contract: {filename_pattern_contract_id!r}",
        )
    disposition = _DISPOSITION_BY_POLICY.get(overwrite_policy)
    if disposition is None:
        raise _DeliveryContextSignal(
            UNSUPPORTED_OVERWRITE_POLICY, f"미지원 overwrite policy: {overwrite_policy!r}"
        )

    # (2) delivery basis 무결성·cross-binding — digest 재계산 + pattern/contract 결속.
    verify_delivery_binding_basis_integrity(delivery_binding_basis)
    if delivery_binding_basis.filename_pattern_contract_id != filename_pattern_contract_id:
        raise _DeliveryContextSignal(
            DELIVERY_BINDING_BASIS_INTEGRITY_ERROR,
            "delivery basis 의 filename pattern contract 가 입력과 불일치",
        )
    if delivery_binding_basis.exact_pattern != exact_pattern:
        raise _DeliveryContextSignal(
            DELIVERY_BINDING_BASIS_INTEGRITY_ERROR,
            "delivery basis 의 exact_pattern 이 입력과 불일치",
        )

    # (3) batch shape — raw ↔ VDR 개수 일치. captured clock 은 한 번만 파싱한다.
    if len(ordered_raw_snapshots) != len(ordered_validated_records):
        raise _DeliveryContextSignal(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            "ordered raw snapshots 와 validated records 개수 불일치",
        )
    try:
        clock = datetime.fromisoformat(captured_delivery_clock)
    except (TypeError, ValueError) as exc:
        raise _DeliveryContextSignal(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            f"captured_delivery_clock 이 유효한 ISO 8601 이 아니다: {captured_delivery_clock!r}",
        ) from exc

    tokens = parse_filename_pattern(
        exact_pattern, filename_pattern_contract_id=filename_pattern_contract_id
    )
    inactive_by_field = {
        r.field_id: r.value_expression
        for r in delivery_binding_basis.output_name_requirements
    }

    # (4) item 순서대로 값 해석 → base name(dedupe 전). 입력 순서를 item ordinal 로 고정한다.
    plan_digest_seen: str | None = None
    blockers: list[DeliveryPlanBlocker] = []
    base_names: list[str] = []
    per_item: list[tuple[ValidatedDataRecord, RawDataRecordSnapshot, tuple[ResolvedTokenValue, ...]]] = []
    for ordinal, (snapshot, vdr) in enumerate(
        zip(ordered_raw_snapshots, ordered_validated_records, strict=True)
    ):
        # 모든 VDR 이 같은 Plan 에 결속돼야 한다(하나의 delivery batch = 하나의 Plan).
        if plan_digest_seen is None:
            plan_digest_seen = vdr.plan_semantic_digest
        elif vdr.plan_semantic_digest != plan_digest_seen:
            raise _DeliveryContextSignal(
                VALIDATED_RECORD_PLAN_MISMATCH,
                "batch 안 VDR 들이 서로 다른 Plan 에 결속됨",
            )
        # raw ↔ VDR cross-binding — VDR 이 이 raw snapshot 에서 나왔는지 확인한다.
        vdr_payload = vdr.semantic_payload_encoded
        if (
            vdr_payload["record_identity"] != snapshot.record_identity
            or vdr_payload["raw_record_digest"] != snapshot.raw_record_digest
        ):
            raise _DeliveryContextSignal(
                RAW_VALIDATED_RECORD_MISMATCH,
                f"item {ordinal} 의 raw snapshot 이 VDR 과 결속되지 않음",
            )

        active_map = dict(vdr.document_values_in_order())
        field_values: dict[str, str] = {}
        item_blocked = False
        for field_id in pattern_field_token_ids(tokens):
            if field_id in active_map:
                text: str | tuple[str, str] = active_map[field_id]
            elif field_id in inactive_by_field:
                text = resolve_delivery_field_value(inactive_by_field[field_id], snapshot)
            else:  # basis 가 이 field 를 안 담았다(active 도 inactive 도 아님)
                text = (
                    OUTPUT_NAME_TOKEN_UNRESOLVED,
                    f"filename token {field_id!r} 이 Active 도 delivery basis 도 아니다",
                )
            if isinstance(text, tuple):
                blockers.append(DeliveryPlanBlocker(text[0], ordinal, field_id, text[1]))
                item_blocked = True
                continue
            if text == "":
                # 빈 logical text(예: Active INTENTIONAL_BLANK)는 조용한 빈 파일명으로 새지 않는다.
                blockers.append(
                    DeliveryPlanBlocker(
                        OUTPUT_NAME_TOKEN_UNRESOLVED,
                        ordinal,
                        field_id,
                        f"filename token {field_id!r} 이 빈 logical text 로 해석됨",
                    )
                )
                item_blocked = True
                continue
            field_values[field_id] = text
        if item_blocked:
            base_names.append("")  # placeholder — blocked 면 최종 결과에 안 쓴다.
            per_item.append((vdr, snapshot, ()))
            continue
        name, resolved_tokens = _render_item(
            tokens, field_values, ordinal=ordinal, clock=clock
        )
        _guard_relative_path(name)
        base_names.append(name)
        per_item.append((vdr, snapshot, resolved_tokens))

    if blockers:
        blockers.sort(key=lambda b: (b.item_ordinal if b.item_ordinal is not None else -1, b.code, b.field_id or ""))
        return DeliveryPlanBlocked(tuple(blockers))

    # (5) duplicate suffix 를 batch 순서로 한 번 계산한다.
    resolved_paths = _dedupe_batch(base_names)

    # (6) item DTO + per-item·plan digest.
    items: list[ResolvedGenerationItem] = []
    for ordinal, ((vdr, snapshot, resolved_tokens), rel_path) in enumerate(
        zip(per_item, resolved_paths, strict=True)
    ):
        _guard_relative_path(rel_path)
        basis_payload = _output_name_basis_payload(
            filename_pattern_contract_id=filename_pattern_contract_id,
            exact_pattern=exact_pattern,
            captured_delivery_clock=captured_delivery_clock,
            validated_record_ref=vdr.validated_record_digest,
            record_identity=snapshot.record_identity,
            raw_record_digest=snapshot.raw_record_digest,
            resolved_token_values=resolved_tokens,
            item_ordinal=ordinal,
            resolved_output_relative_path=rel_path,
            overwrite_disposition=disposition,
        )
        items.append(
            ResolvedGenerationItem(
                validated_record_ref=vdr.validated_record_digest,
                record_identity=snapshot.record_identity,
                raw_record_digest=snapshot.raw_record_digest,
                resolved_token_values=resolved_tokens,
                item_ordinal=ordinal,
                resolved_output_relative_path=rel_path,
                output_name_basis_digest=canonical_execution_digest(basis_payload),
                overwrite_disposition=disposition,
            )
        )

    plan_payload = _delivery_plan_payload(
        delivery_contract_id=delivery_contract_id,
        filename_pattern_contract_id=filename_pattern_contract_id,
        exact_pattern=exact_pattern,
        captured_delivery_clock=captured_delivery_clock,
        output_directory_basis=output_directory_basis,
        overwrite_policy=overwrite_policy,
        delivery_binding_basis_digest=delivery_binding_basis.delivery_binding_basis_digest,
        items=items,
    )
    return ResolvedGenerationDeliveryPlan(
        delivery_contract_id=delivery_contract_id,
        filename_pattern_contract_id=filename_pattern_contract_id,
        exact_pattern=exact_pattern,
        captured_delivery_clock=captured_delivery_clock,
        output_directory_basis=output_directory_basis,
        overwrite_policy=overwrite_policy,
        delivery_binding_basis_digest=delivery_binding_basis.delivery_binding_basis_digest,
        ordered_items=tuple(items),
        delivery_plan_digest=canonical_execution_digest(plan_payload),
    )


def verify_resolved_delivery_plan_integrity(plan: ResolvedGenerationDeliveryPlan) -> None:
    """delivery plan·item digest 를 재계산하고 ordinal·path 불변식을 강제한다(fail-closed).

    확인: item ordinal 0..n-1 연속·resolved path flat/유일·per-item basis digest 재계산·plan digest
    재계산. S6 는 이 불변식을 재조립하지 않는다 — 이 검증이 그 전제를 진다.
    """
    seen_paths: set[str] = set()
    for ordinal, item in enumerate(plan.ordered_items):
        if item.item_ordinal != ordinal:
            raise ResolvedDeliveryPlanIntegrityError(
                f"item_ordinal 이 batch 순서와 불일치: {item.item_ordinal} != {ordinal}"
            )
        _guard_relative_path(item.resolved_output_relative_path)
        if item.resolved_output_relative_path in seen_paths:
            raise ResolvedDeliveryPlanIntegrityError(
                f"resolved output path 중복: {item.resolved_output_relative_path!r}"
            )
        seen_paths.add(item.resolved_output_relative_path)
        basis_payload = _output_name_basis_payload(
            filename_pattern_contract_id=plan.filename_pattern_contract_id,
            exact_pattern=plan.exact_pattern,
            captured_delivery_clock=plan.captured_delivery_clock,
            validated_record_ref=item.validated_record_ref,
            record_identity=item.record_identity,
            raw_record_digest=item.raw_record_digest,
            resolved_token_values=item.resolved_token_values,
            item_ordinal=item.item_ordinal,
            resolved_output_relative_path=item.resolved_output_relative_path,
            overwrite_disposition=item.overwrite_disposition,
        )
        if canonical_execution_digest(basis_payload) != item.output_name_basis_digest:
            raise ResolvedDeliveryPlanIntegrityError(
                f"item {ordinal} 의 output_name_basis_digest 재계산 불일치"
            )
    plan_payload = _delivery_plan_payload(
        delivery_contract_id=plan.delivery_contract_id,
        filename_pattern_contract_id=plan.filename_pattern_contract_id,
        exact_pattern=plan.exact_pattern,
        captured_delivery_clock=plan.captured_delivery_clock,
        output_directory_basis=plan.output_directory_basis,
        overwrite_policy=plan.overwrite_policy,
        delivery_binding_basis_digest=plan.delivery_binding_basis_digest,
        items=plan.ordered_items,
    )
    if canonical_execution_digest(plan_payload) != plan.delivery_plan_digest:
        raise ResolvedDeliveryPlanIntegrityError("delivery_plan_digest 재계산 불일치")


# ─── ManagedGenerationPlan DTO ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ManagedGenerationPlan:
    """문서 bytes 의미(Sealed Plan + VDR)와 delivery 의미(resolved path + disposition)를 분리한 묶음.

    live Mapping·mutable record·filename pattern 재해석 결과·legacy ``template`` path 를 저장하지 않는다.
    progress/cancel context 는 보존하되 delivery identity(managed_generation_plan_digest)에서 제외한다.
    """

    sealed_execution_plan_ref: str
    resolved_delivery_plan: ResolvedGenerationDeliveryPlan
    output_directory: str
    delivery_contract_id: str
    created_at: str
    progress_cancel_context: Mapping[str, Any]
    managed_generation_plan_digest: str


def _managed_plan_identity_payload(
    *,
    sealed_execution_plan_ref: str,
    delivery_plan_digest: str,
    output_directory: str,
    delivery_contract_id: str,
) -> dict[str, Any]:
    # created_at·progress/cancel 은 제외(delivery identity 아님).
    return {
        "managed_generation_plan_schema": MANAGED_GENERATION_PLAN_SCHEMA,
        "sealed_execution_plan_ref": sealed_execution_plan_ref,
        "delivery_plan_digest": delivery_plan_digest,
        "output_directory": output_directory,
        "delivery_contract_id": delivery_contract_id,
    }


def build_managed_generation_plan(
    *,
    sealed_execution_plan_ref: str,
    resolved_delivery_plan: ResolvedGenerationDeliveryPlan,
    output_directory: str,
    created_at: str,
    progress_cancel_context: Mapping[str, Any] | None = None,
) -> ManagedGenerationPlan:
    """resolved delivery plan 을 managed GenerationPlan 으로 봉인한다(delivery plan 무결성 재검증 포함).

    delivery_contract_id 는 resolved plan 에서만 가져온다(별도 입력 금지 — 두 벌 판정 방지).
    """
    verify_resolved_delivery_plan_integrity(resolved_delivery_plan)
    frozen_progress = MappingProxyType(dict(progress_cancel_context or {}))
    digest = canonical_execution_digest(
        _managed_plan_identity_payload(
            sealed_execution_plan_ref=sealed_execution_plan_ref,
            delivery_plan_digest=resolved_delivery_plan.delivery_plan_digest,
            output_directory=output_directory,
            delivery_contract_id=resolved_delivery_plan.delivery_contract_id,
        )
    )
    return ManagedGenerationPlan(
        sealed_execution_plan_ref=sealed_execution_plan_ref,
        resolved_delivery_plan=resolved_delivery_plan,
        output_directory=output_directory,
        delivery_contract_id=resolved_delivery_plan.delivery_contract_id,
        created_at=created_at,
        progress_cancel_context=frozen_progress,
        managed_generation_plan_digest=digest,
    )


def verify_managed_generation_plan_integrity(plan: ManagedGenerationPlan) -> None:
    """delivery plan 무결성 + managed digest 재계산 대조(fail-closed)."""
    verify_resolved_delivery_plan_integrity(plan.resolved_delivery_plan)
    if plan.delivery_contract_id != plan.resolved_delivery_plan.delivery_contract_id:
        raise ManagedGenerationPlanIntegrityError(
            "managed plan 의 delivery_contract_id 가 resolved plan 과 불일치"
        )
    recomputed = canonical_execution_digest(
        _managed_plan_identity_payload(
            sealed_execution_plan_ref=plan.sealed_execution_plan_ref,
            delivery_plan_digest=plan.resolved_delivery_plan.delivery_plan_digest,
            output_directory=plan.output_directory,
            delivery_contract_id=plan.delivery_contract_id,
        )
    )
    if recomputed != plan.managed_generation_plan_digest:
        raise ManagedGenerationPlanIntegrityError(
            "managed_generation_plan_digest 재계산 불일치"
        )


# ─── MaterializationInput = SealedExecutionPlan + ValidatedDataRecord ─────────────────────────
@dataclass(frozen=True)
class MaterializationInput:
    """document materialization 입력 = Plan ref + VDR ref. output path·batch order·disposition 없음.

    S6 materializer 는 document bytes 를 만들고, delivery coordinator 가 resolved item(별도 delivery
    authority)에 따라 저장한다 — 두 의미를 이 경계가 분리한다.
    """

    sealed_execution_plan_ref: str
    validated_record_ref: str


def materialization_inputs_of(
    managed_plan: ManagedGenerationPlan,
) -> tuple[MaterializationInput, ...]:
    """managed plan 의 각 item 을 document MaterializationInput 으로 투영한다(delivery 필드 제외)."""
    return tuple(
        MaterializationInput(
            sealed_execution_plan_ref=managed_plan.sealed_execution_plan_ref,
            validated_record_ref=item.validated_record_ref,
        )
        for item in managed_plan.resolved_delivery_plan.ordered_items
    )


class MaterializationInputPort:
    """MaterializationInput 의 Plan ref·VDR ref·Plan-bound dependency 를 resolve 하는 최소 port.

    Plan ref 는 plan_semantic_digest 로 재검증하고, VDR 이 그 Plan 에 결속됐는지 cross-bind 한다
    (:func:`verify_validated_record_completeness`). 실제 S6 start gate/pin·native materialization 은
    비범위 — 이 port 는 exact refs 를 안전하게 되읽는 seam 만 진다.
    """

    def __init__(
        self,
        *,
        plan_resolver: Callable[[str], SealedExecutionPlanSemanticPayload],
        vdr_store: ImmutableVdrStore,
    ) -> None:
        self._plan_resolver = plan_resolver
        self._vdr_store = vdr_store

    def resolve(
        self, materialization_input: MaterializationInput
    ) -> tuple[SealedExecutionPlanSemanticPayload, ValidatedDataRecord]:
        plan = self._plan_resolver(materialization_input.sealed_execution_plan_ref)
        if plan_semantic_digest(plan) != materialization_input.sealed_execution_plan_ref:
            raise MaterializationInputResolutionError(
                "resolve 한 Plan 의 semantic digest 가 ref 와 불일치"
            )
        vdr = self._vdr_store.resolve(materialization_input.validated_record_ref)
        if vdr.plan_semantic_digest != materialization_input.sealed_execution_plan_ref:
            raise MaterializationInputResolutionError(
                "VDR 이 이 Plan 에 결속되지 않음(Plan mismatch)"
            )
        # Plan-bound Candidate dependency 포함 완결성 재검증 — claim 신뢰 금지.
        verify_validated_record_completeness(vdr, plan)
        return plan, vdr


# ─── runtime conformance admission bridge ─────────────────────────────────────────────────
@dataclass(frozen=True)
class ManagedRunAdmission:
    """runtime admission 관찰 — S5 종료 시 NOT_ADMITTED 도 합법(construction 가능, start 차단)."""

    construction_allowed: bool
    materialization_startable: bool
    status: str


def evaluate_managed_run_admission(
    *,
    runtime_registry: RuntimeMaterializerConformanceRegistry,
    runtime_capability_manifest_digest: str,
    materialization_contract_id: str,
    materialization_base_contract_id: str,
    native_primitive_contract_id: str,
    composition_contract_id: str,
    plan_schema_version: str,
    canonical_encoding_version: str,
) -> ManagedRunAdmission:
    """Plan observation 으로 runtime admission 을 읽는다 — runtime manifest 를 delivery identity 에 넣지 않는다.

    권장 v1 정책: semantic/delivery contract 는 S5 에서 구성 가능(construction_allowed 항상 True),
    actual StartMaterialization 은 runtime ADMITTED 필수(materialization_startable = is_admitted).
    """
    admitted = runtime_registry.is_admitted(
        runtime_capability_manifest_digest=runtime_capability_manifest_digest,
        materialization_contract_id=materialization_contract_id,
        materialization_base_contract_id=materialization_base_contract_id,
        native_primitive_contract_id=native_primitive_contract_id,
        composition_contract_id=composition_contract_id,
        plan_schema_version=plan_schema_version,
        canonical_encoding_version=canonical_encoding_version,
    )
    return ManagedRunAdmission(
        construction_allowed=True,
        materialization_startable=admitted,
        status=MANAGED_RUN_STARTABLE if admitted else MANAGED_RUN_CONSTRUCTION_ONLY,
    )


# ─── managed/legacy/continuation adapter 분리 ─────────────────────────────────────────────
@dataclass(frozen=True)
class ManagedPlanMaterializationAdapter:
    """S5 managed path — 입력은 Plan + VDR(MaterializationInput). S5 exact guarantee 를 표시한다."""

    managed_plan: ManagedGenerationPlan
    exact_delivery_guarantee: str = S5_EXACT_DELIVERY_GUARANTEE

    def materialization_inputs(self) -> tuple[MaterializationInput, ...]:
        return materialization_inputs_of(self.managed_plan)


@dataclass(frozen=True)
class LegacySlotlessGenerationAdapter:
    """transitional slotless 호환 경로 — S5 Plan/VDR/exact guarantee 를 소유하지 않는다."""

    transitional_reason: str


@dataclass(frozen=True)
class LegacyContinuationGenerationAdapter:
    """이전 output base 를 잇는 continuation — S5 보장 없음. continuation 은 applied Candidate 가 아니다."""

    previous_output_base: str
    transitional_reason: str


def has_s5_exact_delivery_guarantee(adapter: object) -> bool:
    """S5 exact delivery guarantee 는 managed adapter 만 진다 — legacy/continuation 은 False.

    금지(invariant 23): S5 Plan → legacy GenerationPlan.template 변환, managed Plan 을 legacy
    generate_batch 로 우회, continuation 을 applied Candidate 로 표시, legacy 결과에 S5 guarantee 표시.
    """
    return isinstance(adapter, ManagedPlanMaterializationAdapter)


def continuation_is_applied_candidate(
    adapter: LegacyContinuationGenerationAdapter,
) -> bool:
    """continuation document 는 applied Candidate 가 아니다(항상 False) — S5 exact 계보에 넣지 않는다."""
    return False
