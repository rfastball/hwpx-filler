"""S5 exact batch output-name resolution + managed GenerationPlan bridge (S5-13 · #709).

이 모듈이 소유하는 것: ``filename-pattern/v1`` 계약 확인(해석·조립·안전 판정·충돌 규칙 자체는
이름 kernel :mod:`hwpxfiller.domain.output_name` 소유, #798), :class:`GenerationDeliveryBindingBasis`(inactive Field token 값 근거), batch-level
:func:`resolve_generation_delivery_plan`, resolved output path canonical payload/digest, output
blocker taxonomy, :class:`ManagedGenerationPlan` DTO, :class:`MaterializationInput` port,
runtime conformance admission bridge, managed adapter(S5 guarantee 단일 소유).

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
filename 조립(금지문자 sanitation·date/seq 서식·안전 판정·casefold 충돌)은 이름 kernel 한 곳을
쓴다 — 표시 표면(「문서」 열·편집기 예시)과 같은 함수라 미리 보인 이름이 실제 이름이다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from hwpxfiller.application.execution_composition import (
    RuntimeMaterializerConformanceRegistry,
)
from hwpxfiller.application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
    plan_semantic_digest,
)
from hwpxfiller.application.record_validation import (
    CurrentValidatedDataRecord,
    DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
    ImmutableVdrStore,
    ValidatedDataRecord,
    ValidatedRecordIntegrityError,
    current_record_validation_basis,
    verify_current_validated_record_completeness,
    verify_validated_record_completeness,
)
from hwpxfiller.application.document_creation_vocabulary import COLLISION_POLICIES
from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue
from hwpxfiller.domain.canonical_execution_encoding import (
    CanonicalExecutionEncodingError,
    canonical_execution_digest,
)
# 이름 kernel 어휘의 re-export(``X as X``) — 배달 계획을 소비하는 쪽이 이 모듈에서 계속 찾는다.
from hwpxfiller.domain.output_name import (
    OUTPUT_NAME_PATTERN_INVALID as OUTPUT_NAME_PATTERN_INVALID,
    OUTPUT_PATH_ESCAPE_DETECTED as OUTPUT_PATH_ESCAPE_DETECTED,
    FieldValueToken as FieldValueToken,
    LiteralSegment as LiteralSegment,
    OutputNameError,
    PatternToken,
    ReservedDateToken as ReservedDateToken,
    ReservedSequenceToken as ReservedSequenceToken,
    dedupe_output_names,
    guard_output_name,
    pattern_field_token_ids,
    render_output_name,
)
from hwpxfiller.domain.output_name import (
    parse_filename_pattern as _parse_pattern_text,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    SOURCE,
    WHITESPACE_PRESERVE_EXACT,
    WHITESPACE_STRIP_LEADING_TRAILING,
    FieldBindingRule,
    UnsupportedDocumentValuePolicyError,
    UnsupportedValueFormatError,
    encode_text_slice,
    render_source_value,
    require_single_rule_per_field,
    resolve_document_value_policy,
)
from hwpxfiller.domain.raw_data_record import (
    SOURCE_TEXT_KIND,
    RawDataRecordSnapshot,
    RawRecordIntegrityError,
    SourceNull,
    encode_source_value,
    verify_raw_record_snapshot,
)

if TYPE_CHECKING:
    from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent

# ─── contract/schema 버전(코드·문서 단일 출처) ────────────────────────────────────────────
FILENAME_PATTERN_CONTRACT_ID = "filename-pattern/v1"
DELIVERY_CONTRACT_ID = "generation-delivery/v1"
# v3: inactive FROM_SOURCE requirement 가 표시형 kind 를 함께 봉인한다(field-binding/v3).
# field-binding/v4 의 가공은 이 schema 안의 **가산 키**(``text_slice``)로 싣는다 — 가공 없는 요구는
# byte 동일하게 남아, 이미 봉인된 basis 의 재계산 대조(:func:`verify_delivery_binding_basis_integrity`)가
# 판 올림만으로 깨지지 않는다. 가공이 있는 요구만 새 키를 갖고 그 digest 는 스스로 일관된다.
DELIVERY_BINDING_BASIS_SCHEMA = "generation-delivery-binding-basis/v3"
OUTPUT_NAME_BASIS_SCHEMA = "output-name-basis-canonical/v1"
GENERATION_DELIVERY_PLAN_SCHEMA = "generation-delivery-plan-canonical/v1"
MANAGED_GENERATION_PLAN_SCHEMA = "managed-generation-plan/v1"


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
# OUTPUT_NAME_PATTERN_INVALID 는 이름 kernel(:mod:`hwpxfiller.domain.output_name`) 소유 — 위 import.
OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED = "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED"
OUTPUT_PATH_NON_REGULAR_CONFLICT = "OUTPUT_PATH_NON_REGULAR_CONFLICT"

# ─── context/integrity 어휘(user-fixable 로 낮추지 않는 fail-closed 실패) ─────────────────────
GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR = "GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR"
UNSUPPORTED_FILENAME_PATTERN_CONTRACT = "UNSUPPORTED_FILENAME_PATTERN_CONTRACT"
UNSUPPORTED_DELIVERY_CONTRACT = "UNSUPPORTED_DELIVERY_CONTRACT"
UNSUPPORTED_OVERWRITE_POLICY = "UNSUPPORTED_OVERWRITE_POLICY"
DELIVERY_BINDING_BASIS_INTEGRITY_ERROR = "DELIVERY_BINDING_BASIS_INTEGRITY_ERROR"
VALIDATED_RECORD_PLAN_MISMATCH = "VALIDATED_RECORD_PLAN_MISMATCH"
RAW_VALIDATED_RECORD_MISMATCH = "RAW_VALIDATED_RECORD_MISMATCH"
CURRENT_RECORD_VALIDATION_BASIS_MISMATCH = (
    "CURRENT_RECORD_VALIDATION_BASIS_MISMATCH"
)
PATH_OCCUPANCY_OBSERVATION_MISMATCH = "PATH_OCCUPANCY_OBSERVATION_MISMATCH"
# OUTPUT_PATH_ESCAPE_DETECTED 는 이름 kernel 소유 — 위 import.
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

# current delivery disposition — publication guarantee 가 아니라 현재 관찰에 대한 계획이다.
WRITE_NEW = "WRITE_NEW"
WRITE_ADD_SUFFIX = "WRITE_ADD_SUFFIX"
WRITE_OVERWRITE = "WRITE_OVERWRITE"


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


# ─── PatternToken 합타입·parser 는 이름 kernel 소유(#798) ───────────────────────────────
# LiteralSegment·ReservedDateToken·ReservedSequenceToken·FieldValueToken·PatternToken·
# pattern_field_token_ids 는 :mod:`hwpxfiller.domain.output_name` 에서 그대로 re-export 한다.


def parse_filename_pattern(
    pattern: object, *, filename_pattern_contract_id: str
) -> tuple[PatternToken, ...]:
    """exact pattern text + contract ID → PatternToken 열 — 해석은 이름 kernel 한 곳이 한다.

    unknown contract → fail-closed context signal. 패턴 문법 위반(빈 패턴·닫히지 않은 ``{{``·빈
    ``{{}}``·inner brace)은 kernel 이 내는 OUTPUT_NAME_PATTERN_INVALID(``_PatternInvalidSignal``).
    """
    if filename_pattern_contract_id != FILENAME_PATTERN_CONTRACT_ID:
        raise _DeliveryContextSignal(
            UNSUPPORTED_FILENAME_PATTERN_CONTRACT,
            f"미지원 filename pattern contract: {filename_pattern_contract_id!r}",
        )
    try:
        return _parse_pattern_text(pattern)
    except OutputNameError as exc:
        raise _PatternInvalidSignal(exc.detail) from exc


# ─── inactive Field 값 표현(delivery basis 가 봉인하는 exact requirement) ──────────────────────
def _encode_delivery_value_expression(rule: FieldBindingRule) -> dict[str, Any]:
    """inactive FieldBindingRule 을 delivery basis 가 담을 canonical value expression 으로 인코딩한다.

    Active requirement(VDR 재사용)와 합치지 않는 delivery-only requirement 다 — 같은 document-value-
    resolution 계약을 쓰되 별개 basis 에 산다.
    """
    policy_id = rule.document_content_value_policy.policy_id
    if rule.binding_kind == SOURCE:
        encoded: dict[str, Any] = {
            "kind": _KIND_FROM_SOURCE,
            "source_key": rule.source_key,
            # 표시형 쌍을 봉인한다 — Active 경로(VDR)와 같은 해석기로 파일 이름 값도 렌더한다.
            "format_kind": rule.format_kind,
            "format_code": rule.format_code,
            "document_content_value_policy_id": policy_id,
        }
        # 가공(v4)은 있을 때만 싣는다 — Active 경로의 실행 계획 인코딩과 같은 규율.
        if rule.text_slice is not None:
            encoded["text_slice"] = encode_text_slice(rule.text_slice)
        return encoded
    if rule.binding_kind == CONSTANT:
        assert rule.canonical_constant_value is not None  # CONSTANT 규칙 불변식
        return {
            "kind": _KIND_CONSTANT,
            "canonical_value": encode_source_value(rule.canonical_constant_value),
            "format_code": rule.format_code,
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
    # 미지원 document value resolution contract 를 조용히 봉인하지 않는다(active-only pattern 포함, fail-closed).
    if document_value_resolution_contract_id != DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID:
        return DeliveryPlanContextError(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            f"미지원 document value resolution contract: {document_value_resolution_contract_id!r}",
        )
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


def _require_no_delivery_format_code(value_expression: Mapping[str, Any]) -> None:
    """고정값은 서식하지 않는다 — 표시형이 실려 오면 조용히 버리지 않고 fail-closed(Active 경로 일치)."""
    format_code = value_expression.get("format_code")
    if (
        (format_code is not None and format_code != "")
        or value_expression.get("format_kind") is not None
        or value_expression.get("text_slice") is not None
    ):
        raise _DeliveryContextSignal(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            "고정값에는 표시형·가공을 적용하지 않는다: "
            f"{value_expression.get('format_kind')!r}/{format_code!r}/"
            f"{value_expression.get('text_slice')!r}",
        )


def _render_delivery_format(value_expression: Mapping[str, Any], text: str) -> str:
    """inactive FROM_SOURCE 값의 가공·표시형 — Active 경로(record validation)와 같은 판정기·같은 순서."""
    try:
        return render_source_value(
            value_expression.get("format_kind"),
            value_expression.get("format_code"),
            value_expression.get("text_slice"),
            text,
        )
    except UnsupportedValueFormatError as exc:
        raise _DeliveryContextSignal(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            f"파일 이름 값의 표시형·가공을 해석할 수 없다: {exc}",
        ) from exc


def resolve_delivery_field_value(
    value_expression: Mapping[str, Any],
    snapshot: RawDataRecordSnapshot,
) -> str | tuple[str, str]:
    """inactive Field token 값을 exact requirement + raw snapshot 에서 해석한다.

    반환: exact logical text | (blocker_code, detail). 미지원 policy/contract 는 blocker 로
    낮추지 않고 ``_DeliveryContextSignal`` 로 닫는다(fail-closed). Active token 은 이 함수를 거치지 않고
    VDR 값을 재사용한다. 소스 값은 언제나 타입 없는 텍스트다 — 여기서 판정하는 것은 존재뿐이다.
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
        _require_no_delivery_format_code(value_expression)
        canonical = value_expression.get("canonical_value")
        if not isinstance(canonical, Mapping):
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR, "CONSTANT requirement 에 canonical_value 가 없다"
            )
        text = canonical.get("text")
        if canonical.get("kind") != SOURCE_TEXT_KIND or not isinstance(text, str):
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                "CONSTANT requirement 의 canonical_value 형식 불량",
            )
        return _apply_whitespace_policy(text, policy.whitespace_policy)
    if kind == _KIND_FROM_SOURCE:
        source_key = value_expression.get("source_key")
        if not isinstance(source_key, str):
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                "FROM_SOURCE requirement 의 source_key 형식 불량",
            )
        _render_delivery_format(value_expression, "")  # 모양은 값의 존재와 무관한 basis 사실
        if not snapshot.has_key(source_key):
            return (OUTPUT_NAME_TOKEN_UNRESOLVED, f"source key {source_key!r} 가 raw record 에 없다")
        value = snapshot.value_for(source_key)
        if isinstance(value, SourceNull):
            return (OUTPUT_NAME_TOKEN_UNRESOLVED, f"source key {source_key!r} 가 explicit null")
        assert value is not None
        return _render_delivery_format(
            value_expression, _apply_whitespace_policy(value.text, policy.whitespace_policy)
        )
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
    conflicting_relative_path: str | None = None


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
    # 이 batch 의 모든 VDR·item 이 결속된 exact Sealed Plan identity(managed builder cross-check 축).
    bound_plan_semantic_digest: str
    ordered_items: tuple[ResolvedGenerationItem, ...]
    delivery_plan_digest: str


ResolveGenerationDeliveryPlanResult = (
    ResolvedGenerationDeliveryPlan | DeliveryPlanBlocked | DeliveryPlanContextError
)


REGULAR_FILE = "REGULAR_FILE"
NON_REGULAR = "NON_REGULAR"
_PATH_OCCUPANCY_KINDS = frozenset({REGULAR_FILE, NON_REGULAR})


@dataclass(frozen=True)
class PathOccupancyEntry:
    relative_name: str
    kind: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relative_name, str)
            or not self.relative_name
            or not isinstance(self.kind, str)
            or self.kind not in _PATH_OCCUPANCY_KINDS
        ):
            raise ValueError("path occupancy entry is invalid")


@dataclass(frozen=True)
class PathOccupancyObservation:
    """한 output directory 를 한 번 읽은 read-only current observation."""

    output_directory: str
    occupied_entries: tuple[PathOccupancyEntry, ...]
    observed_at: str

    def __post_init__(self) -> None:
        if not self.output_directory or not self.observed_at:
            raise ValueError("path occupancy observation context is required")
        if any(not isinstance(entry, PathOccupancyEntry) for entry in self.occupied_entries):
            raise ValueError("occupied entries must be PathOccupancyEntry values")


@dataclass(frozen=True)
class CurrentResolvedDeliveryItem:
    record_identity: str
    item_ordinal: int
    resolved_output_relative_path: str
    collision_disposition: str
    resolved_token_values: tuple[ResolvedTokenValue, ...] = ()


@dataclass(frozen=True)
class CurrentResolvedDelivery:
    exact_pattern: str
    captured_delivery_clock: str
    output_directory: str
    collision_policy: str
    ordered_items: tuple[CurrentResolvedDeliveryItem, ...]


ResolveCurrentGenerationDeliveryResult = (
    CurrentResolvedDelivery | DeliveryPlanBlocked | DeliveryPlanContextError
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
    bound_plan_semantic_digest: str,
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
        "bound_plan_semantic_digest": bound_plan_semantic_digest,
        # 입력 순서(exact ordered batch authority) 그대로 — 재정렬 금지.
        "ordered_items": [_item_identity_payload(it) for it in items],
    }


def _guard_relative_path(name: str) -> None:
    """최종 이름이 출력 폴더 안의 평평한 안전한 파일 이름인가 — 판정은 이름 kernel
    (:func:`~hwpxfiller.domain.output_name.guard_output_name`) 한 곳이다. 위반은 fail-closed
    OUTPUT_PATH_ESCAPE_DETECTED(경로 구분자·drive/ADS·금지/제어 문자·``..``·빈 stem·끝 점/공백·
    Windows 예약 장치 이름).
    """
    try:
        guard_output_name(name)
    except OutputNameError as exc:
        raise _DeliveryContextSignal(exc.code, exc.detail) from exc


def _render_item(
    tokens: Iterable[PatternToken],
    field_values: Mapping[str, str],
    *,
    ordinal: int,
    clock: datetime,
) -> tuple[str, tuple[ResolvedTokenValue, ...]]:
    """token 열을 filename 으로 조립한다 — 조립 규칙은 이름 kernel 의 것(seq = ordinal + 1)."""
    name, parts = render_output_name(tokens, field_values, seq=ordinal + 1, now=clock)
    return name, tuple(ResolvedTokenValue(p.kind, p.field_id, p.text) for p in parts)


def _dedupe_batch(
    base_names: list[str], *, occupied_names: Iterable[str] = ()
) -> list[str]:
    """배치 내 같은 이름 충돌에 결정적 접미사(_1·_2…) — 대소문자 무관(casefold) 규칙은 kernel 소유.

    batch 순서로 한 번 계산한다 — item 별 독립 재결정 금지(invariant 22).
    """
    return dedupe_output_names(base_names, occupied_names=occupied_names)


def resolve_current_generation_delivery(
    *,
    sealed_execution_plan: SealedExecutionPlanValue,
    ordered_validated_records: Iterable[CurrentValidatedDataRecord],
    ordered_raw_snapshots: Iterable[RawDataRecordSnapshot],
    delivery_binding_basis: GenerationDeliveryBindingBasis,
    exact_pattern: str,
    captured_delivery_clock: str,
    run_delivery_intent: RunDeliveryIntent,
    path_occupancy: PathOccupancyObservation,
    filename_pattern_contract_id: str = FILENAME_PATTERN_CONTRACT_ID,
) -> ResolveCurrentGenerationDeliveryResult:
    """current Plan/VDR values + one occupancy observation -> exact planned paths.

    No legacy Plan shell, VDR ref, semantic digest, durable pointer, reservation, or write is
    constructed. Existing-path decisions are based only on ``path_occupancy``; a later publisher
    must recheck the filesystem race.
    """
    try:
        return _resolve_current(
            sealed_execution_plan=sealed_execution_plan,
            ordered_validated_records=tuple(ordered_validated_records),
            ordered_raw_snapshots=tuple(ordered_raw_snapshots),
            delivery_binding_basis=delivery_binding_basis,
            exact_pattern=exact_pattern,
            captured_delivery_clock=captured_delivery_clock,
            run_delivery_intent=run_delivery_intent,
            path_occupancy=path_occupancy,
            filename_pattern_contract_id=filename_pattern_contract_id,
        )
    except _PatternInvalidSignal as exc:
        return DeliveryPlanBlocked(
            (DeliveryPlanBlocker(OUTPUT_NAME_PATTERN_INVALID, None, None, str(exc)),)
        )
    except _DeliveryContextSignal as sig:
        return DeliveryPlanContextError(sig.code, sig.detail)


def _resolve_current(
    *,
    sealed_execution_plan: SealedExecutionPlanValue,
    ordered_validated_records: tuple[CurrentValidatedDataRecord, ...],
    ordered_raw_snapshots: tuple[RawDataRecordSnapshot, ...],
    delivery_binding_basis: GenerationDeliveryBindingBasis,
    exact_pattern: str,
    captured_delivery_clock: str,
    run_delivery_intent: RunDeliveryIntent,
    path_occupancy: PathOccupancyObservation,
    filename_pattern_contract_id: str,
) -> ResolveCurrentGenerationDeliveryResult:
    if filename_pattern_contract_id != FILENAME_PATTERN_CONTRACT_ID:
        raise _DeliveryContextSignal(
            UNSUPPORTED_FILENAME_PATTERN_CONTRACT,
            f"미지원 filename pattern contract: {filename_pattern_contract_id!r}",
        )
    if run_delivery_intent.collision_policy not in COLLISION_POLICIES:
        raise _DeliveryContextSignal(
            UNSUPPORTED_OVERWRITE_POLICY,
            f"미지원 collision policy: {run_delivery_intent.collision_policy!r}",
        )
    if path_occupancy.output_directory != run_delivery_intent.output_directory:
        raise _DeliveryContextSignal(
            PATH_OCCUPANCY_OBSERVATION_MISMATCH,
            "filesystem observation output directory 가 RunDeliveryIntent 와 불일치",
        )
    try:
        verify_delivery_binding_basis_integrity(delivery_binding_basis)
    except DeliveryBindingBasisIntegrityError as exc:
        raise _DeliveryContextSignal(
            DELIVERY_BINDING_BASIS_INTEGRITY_ERROR, str(exc)
        ) from exc
    if (
        delivery_binding_basis.filename_pattern_contract_id
        != filename_pattern_contract_id
        or delivery_binding_basis.exact_pattern != exact_pattern
        or delivery_binding_basis.base_template_application_id
        != sealed_execution_plan.template_application_id
    ):
        raise _DeliveryContextSignal(
            DELIVERY_BINDING_BASIS_INTEGRITY_ERROR,
            "delivery binding basis 가 current Plan/pattern 과 불일치",
        )
    if len(ordered_raw_snapshots) != len(ordered_validated_records):
        raise _DeliveryContextSignal(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            "ordered raw snapshots 와 current validated records 개수 불일치",
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
        requirement.field_id: requirement.value_expression
        for requirement in delivery_binding_basis.output_name_requirements
    }
    expected_basis = current_record_validation_basis(sealed_execution_plan)
    blockers: list[DeliveryPlanBlocker] = []
    base_names: list[str] = []
    token_values: list[tuple[ResolvedTokenValue, ...]] = []
    for ordinal, (snapshot, record) in enumerate(
        zip(ordered_raw_snapshots, ordered_validated_records, strict=True)
    ):
        try:
            verify_raw_record_snapshot(snapshot)
        except (RawRecordIntegrityError, CanonicalExecutionEncodingError) as exc:
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                f"item {ordinal} raw snapshot 무결성 실패: {exc}",
            ) from exc
        if record.validation_basis != expected_basis:
            raise _DeliveryContextSignal(
                CURRENT_RECORD_VALIDATION_BASIS_MISMATCH,
                f"item {ordinal} current VDR validation basis 가 current Plan 과 불일치",
            )
        if (
            record.record_identity != snapshot.record_identity
            or record.raw_record_digest != snapshot.raw_record_digest
        ):
            raise _DeliveryContextSignal(
                RAW_VALIDATED_RECORD_MISMATCH,
                f"item {ordinal} raw snapshot 이 current VDR 과 결속되지 않음",
            )
        try:
            verify_current_validated_record_completeness(
                record, sealed_execution_plan, snapshot, expected_basis=expected_basis
            )
        except ValidatedRecordIntegrityError as exc:
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                f"item {ordinal} current VDR 완결성 실패: {exc}",
            ) from exc

        active_map = dict(record.document_values_in_order())
        field_values: dict[str, str] = {}
        item_blocked = False
        for field_id in pattern_field_token_ids(tokens):
            value: str | tuple[str, str]
            if field_id in active_map:
                value = active_map[field_id]
            elif field_id in inactive_by_field:
                value = resolve_delivery_field_value(
                    inactive_by_field[field_id], snapshot
                )
            else:
                value = (
                    OUTPUT_NAME_TOKEN_UNRESOLVED,
                    f"filename token {field_id!r} 이 Active 도 delivery basis 도 아니다",
                )
            if isinstance(value, tuple):
                blockers.append(DeliveryPlanBlocker(value[0], ordinal, field_id, value[1]))
                item_blocked = True
            elif value == "":
                blockers.append(
                    DeliveryPlanBlocker(
                        OUTPUT_NAME_TOKEN_UNRESOLVED,
                        ordinal,
                        field_id,
                        f"filename token {field_id!r} 이 빈 logical text 로 해석됨",
                    )
                )
                item_blocked = True
            else:
                field_values[field_id] = value
        if item_blocked:
            base_names.append("")
            token_values.append(())
            continue
        name, resolved_tokens = _render_item(
            tokens, field_values, ordinal=ordinal, clock=clock
        )
        _guard_relative_path(name)
        base_names.append(name)
        token_values.append(resolved_tokens)
    if blockers:
        blockers.sort(
            key=lambda blocker: (
                blocker.item_ordinal if blocker.item_ordinal is not None else -1,
                blocker.code,
                blocker.field_id or "",
            )
        )
        return DeliveryPlanBlocked(tuple(blockers))

    occupied = tuple(entry.relative_name for entry in path_occupancy.occupied_entries)
    non_regular_folded = {
        entry.relative_name.casefold()
        for entry in path_occupancy.occupied_entries
        if entry.kind == NON_REGULAR
    }
    policy = run_delivery_intent.collision_policy
    if policy == "ADD_SUFFIX":
        paths = _dedupe_batch(base_names, occupied_names=occupied)
    else:
        paths = _dedupe_batch(base_names)
    occupied_folded = {name.casefold() for name in occupied}
    if policy == "FAIL":
        conflicts = [
            DeliveryPlanBlocker(
                (
                    OUTPUT_PATH_NON_REGULAR_CONFLICT
                    if path.casefold() in non_regular_folded
                    else OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED
                ),
                ordinal,
                None,
                f"existing output path: {path}",
                path,
            )
            for ordinal, path in enumerate(paths)
            if path.casefold() in occupied_folded
        ]
        if conflicts:
            return DeliveryPlanBlocked(tuple(conflicts))
    if policy == "OVERWRITE_EXPLICIT":
        conflicts = [
            DeliveryPlanBlocker(
                OUTPUT_PATH_NON_REGULAR_CONFLICT,
                ordinal,
                None,
                f"non-regular output path: {path}",
                path,
            )
            for ordinal, path in enumerate(paths)
            if path.casefold() in non_regular_folded
        ]
        if conflicts:
            return DeliveryPlanBlocked(tuple(conflicts))

    items: list[CurrentResolvedDeliveryItem] = []
    for ordinal, (record, base_name, path, resolved_tokens) in enumerate(
        zip(ordered_validated_records, base_names, paths, token_values, strict=True)
    ):
        _guard_relative_path(path)
        if policy == "OVERWRITE_EXPLICIT" and path.casefold() in occupied_folded:
            disposition = WRITE_OVERWRITE
        elif policy == "ADD_SUFFIX" and path != base_name:
            disposition = WRITE_ADD_SUFFIX
        else:
            disposition = WRITE_NEW
        items.append(
            CurrentResolvedDeliveryItem(
                record_identity=record.record_identity,
                item_ordinal=ordinal,
                resolved_output_relative_path=path,
                collision_disposition=disposition,
                resolved_token_values=resolved_tokens,
            )
        )
    return CurrentResolvedDelivery(
        exact_pattern=exact_pattern,
        captured_delivery_clock=captured_delivery_clock,
        output_directory=run_delivery_intent.output_directory,
        collision_policy=policy,
        ordered_items=tuple(items),
    )


def resolve_generation_delivery_plan(
    *,
    sealed_execution_plan: SealedExecutionPlanSemanticPayload,
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
    """exact Sealed Plan + ordered raw snapshots + VDRs + exact pattern + captured clock → resolved paths.

    순수·deterministic batch 해석. date·seq·duplicate suffix·item ordinal 을 ordered batch 전체에서
    한 번만 계산한다(invariant 22). 입력 순서가 exact ordered batch authority 다 — UI/source store
    순서를 나중에 다시 읽지 않는다. filename pattern 은 provenance, resolved_output_relative_path 가
    실행 naming authority 다.

    trust-boundary: raw snapshot·VDR 은 복원/변조될 수 있으므로 claim(digest·identity)만 믿지 않고
    sealed payload 에서 재검증한다 — raw 는 :func:`verify_raw_record_snapshot`, VDR 은 exact Plan 에
    대한 :func:`verify_validated_record_completeness`. 모든 VDR 은 이 Plan 에 결속돼야 한다.
    """
    try:
        return _resolve(
            sealed_execution_plan=sealed_execution_plan,
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
    sealed_execution_plan: SealedExecutionPlanSemanticPayload,
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
    #     callee integrity 예외를 결과 union 밖으로 새지 않게 context error 로 닫는다.
    try:
        verify_delivery_binding_basis_integrity(delivery_binding_basis)
    except DeliveryBindingBasisIntegrityError as exc:
        raise _DeliveryContextSignal(
            DELIVERY_BINDING_BASIS_INTEGRITY_ERROR, str(exc)
        ) from exc
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
    # 모든 VDR·item 이 결속돼야 하는 exact Plan identity(한 번만 계산).
    bound_plan_digest = plan_semantic_digest(sealed_execution_plan)

    # (4) item 순서대로 값 해석 → base name(dedupe 전). 입력 순서를 item ordinal 로 고정한다.
    blockers: list[DeliveryPlanBlocker] = []
    base_names: list[str] = []
    per_item: list[tuple[ValidatedDataRecord, RawDataRecordSnapshot, tuple[ResolvedTokenValue, ...]]] = []
    for ordinal, (snapshot, vdr) in enumerate(
        zip(ordered_raw_snapshots, ordered_validated_records, strict=True)
    ):
        # raw snapshot trust-boundary: sealed payload 에서 값·digest·identity 를 재구성해 대조한다
        # (변조된 _values 는 claim 만 맞아도 여기서 닫힌다) — 이후 inactive lookup 이 신뢰할 수 있게.
        try:
            verify_raw_record_snapshot(snapshot)
        except (RawRecordIntegrityError, CanonicalExecutionEncodingError) as exc:
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                f"item {ordinal} raw snapshot 무결성 실패: {exc}",
            ) from exc
        # 모든 VDR 이 이 exact Plan 에 결속돼야 한다(하나의 delivery batch = 하나의 Plan).
        if vdr.plan_semantic_digest != bound_plan_digest:
            raise _DeliveryContextSignal(
                VALIDATED_RECORD_PLAN_MISMATCH,
                f"item {ordinal} 의 VDR 이 이 Sealed Plan 에 결속되지 않음",
            )
        # VDR trust-boundary: digest 재계산 + Plan 결속 + resolved value 완결성을 재검증한다 —
        # 복원/변조된 payload 가 forged document_value 로 filename 을 만들지 못하게 한다.
        try:
            verify_validated_record_completeness(vdr, sealed_execution_plan)
        except ValidatedRecordIntegrityError as exc:
            raise _DeliveryContextSignal(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                f"item {ordinal} VDR 완결성 실패: {exc}",
            ) from exc
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
        bound_plan_semantic_digest=bound_plan_digest,
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
        bound_plan_semantic_digest=bound_plan_digest,
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
        # Windows case-insensitive FS 기준 유일성 — 대소문자만 다른 경로도 같은 파일이다.
        if item.resolved_output_relative_path.casefold() in seen_paths:
            raise ResolvedDeliveryPlanIntegrityError(
                f"resolved output path 중복: {item.resolved_output_relative_path!r}"
            )
        seen_paths.add(item.resolved_output_relative_path.casefold())
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
        bound_plan_semantic_digest=plan.bound_plan_semantic_digest,
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

    cross-binding: resolved plan 의 VDR 들이 결속된 exact Plan(``bound_plan_semantic_digest``)이
    ``sealed_execution_plan_ref`` 와 일치해야 한다 — 안 그러면 모든 MaterializationInput 이 나중에
    실패할 잘못/오타난 plan ref 를 그대로 봉인한다.
    """
    verify_resolved_delivery_plan_integrity(resolved_delivery_plan)
    if resolved_delivery_plan.bound_plan_semantic_digest != sealed_execution_plan_ref:
        raise ManagedGenerationPlanIntegrityError(
            "sealed_execution_plan_ref 가 delivery plan 의 bound_plan_semantic_digest 와 불일치"
        )
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
    if plan.sealed_execution_plan_ref != plan.resolved_delivery_plan.bound_plan_semantic_digest:
        raise ManagedGenerationPlanIntegrityError(
            "sealed_execution_plan_ref 가 delivery plan 의 bound_plan_semantic_digest 와 불일치"
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
    sealed_execution_plan: SealedExecutionPlanSemanticPayload,
    runtime_capability_manifest_digest: str,
) -> ManagedRunAdmission:
    """exact Sealed Plan 에서 admission query 를 **파생**해 runtime admission 을 읽는다.

    contract/schema 값을 caller 자유입력으로 받으면 다른 Plan 의 supported 값을 빌려 ADMITTED 를
    위조할 수 있다 — 그래서 실제 봉인 Plan 의 ExecutionContractSet·schema/encoding 에서만 파생한다.
    ``runtime_capability_manifest_digest`` 만 runtime 관찰 축의 caller 입력이다(Plan 에 없다).

    권장 v1 정책: semantic/delivery contract 는 S5 에서 구성 가능(construction_allowed 항상 True),
    actual StartMaterialization 은 runtime ADMITTED 필수(materialization_startable = is_admitted).
    runtime manifest 는 Plan/VDR/delivery semantic identity 에 넣지 않는다.
    """
    contracts = sealed_execution_plan.execution_basis.contracts
    admitted = runtime_registry.is_admitted(
        runtime_capability_manifest_digest=runtime_capability_manifest_digest,
        materialization_contract_id=contracts.materialization_contract_id,
        materialization_base_contract_id=contracts.materialization_base_contract_id,
        native_primitive_contract_id=contracts.native_primitive_contract_id,
        composition_contract_id=contracts.composition_contract_id,
        plan_schema_version=sealed_execution_plan.plan_schema_version,
        canonical_encoding_version=sealed_execution_plan.canonical_encoding_version,
    )
    return ManagedRunAdmission(
        construction_allowed=True,
        materialization_startable=admitted,
        status=MANAGED_RUN_STARTABLE if admitted else MANAGED_RUN_CONSTRUCTION_ONLY,
    )


# ─── managed adapter(S5 exact guarantee 소유자) ─────────────────────────────────────────────
@dataclass(frozen=True)
class ManagedPlanMaterializationAdapter:
    """S5 managed path — 입력은 Plan + VDR(MaterializationInput). S5 exact guarantee 를 표시한다."""

    managed_plan: ManagedGenerationPlan
    exact_delivery_guarantee: str = S5_EXACT_DELIVERY_GUARANTEE

    def materialization_inputs(self) -> tuple[MaterializationInput, ...]:
        return materialization_inputs_of(self.managed_plan)


def has_s5_exact_delivery_guarantee(adapter: object) -> bool:
    """S5 exact delivery guarantee 는 managed adapter 만 진다.

    금지(invariant 23): S5 Plan → 다른 생성기 입력 변환, managed Plan 우회, managed 가 아닌 결과에
    S5 guarantee 표시. legacy slotless·continuation adapter 는 #1081 PR3 에서 걷혔다.
    """
    return isinstance(adapter, ManagedPlanMaterializationAdapter)
