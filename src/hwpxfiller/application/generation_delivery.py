"""현재 생성의 배치 파일명·충돌 해석과 materialization admission.

이름 조립·경로 안전성은 :mod:`hwpxfiller.domain.output_name` 에 맡긴다. 여기서는
inactive Field token 의 결속 근거, 현재 저장 폴더의 점유와 충돌, 실행 입력 검증을 판정한다.

핵심 불변식(issue #709):
- **일반 token 은 target Field ID 다**(raw source key 아님, invariant 21). Active token 은 VDR 의
  document_value 를 재사용하고, inactive token 만 별도 delivery-binding basis 에서 exact FieldBinding
  revision 으로 해석한다.
- **date·seq·duplicate suffix·item ordinal 은 batch 전체에서 한 번만 결정한다**(invariant 22).
  filename pattern 은 provenance 이고 실행 시점의 naming authority 는 resolved_output_relative_path 다.
- **「오늘 날짜」(RUNTIME_DATE, #950)의 시각 권위는 ``captured_delivery_clock`` 하나다**(RC-02). 파일
  이름의 날짜 토큰·「오늘 날짜」 Field 토큰(Active·inactive 모두)이 이 값으로 렌더되고, managed 생성은
  문서 본문의 RUNTIME_DATE 도 같은 값으로 렌더한다(:mod:`hwpxfiller.external.managed_generation`).
  그래서 Active RUNTIME_DATE 토큰은 VDR 값을 재사용하지 않고 이 시각에서 다시 렌더한다 — 레코드
  준비(미리보기 VDR)는 배달 준비보다 먼저, 다른 순간에 찍히기 때문이다.
- confirm-or-alarm: 미치환/미해소 token 은 조용한 빈칸이 아니라 시끄러운 blocker. unknown pattern/
  collision policy 는 latest fallback 없이 fail-closed.

canonical framing·digest 는 S5-06 closed set(:mod:`hwpxfiller.domain.canonical_execution_encoding`).
filename 조립(금지문자 sanitation·date/seq 서식·안전 판정·casefold 충돌)은 이름 kernel 한 곳을
쓴다 — 표시 표면(「문서」 열·편집기 예시)과 같은 함수라 미리 보인 이름이 실제 이름이다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
    RUNTIME_DATE,
    SOURCE,
    WHITESPACE_PRESERVE_EXACT,
    WHITESPACE_STRIP_LEADING_TRAILING,
    FieldBindingRule,
    UnsupportedDocumentValuePolicyError,
    UnsupportedValueFormatError,
    encode_text_slice,
    render_runtime_date,
    render_source_value,
    require_runtime_date_format,
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
# v3: inactive FROM_SOURCE requirement 가 표시형 kind 를 함께 봉인한다(field-binding/v3).
# field-binding/v4 의 가공은 이 schema 안의 **가산 키**(``text_slice``)로 싣는다 — 가공 없는 요구는
# byte 동일하게 남아, 이미 봉인된 basis 의 재계산 대조(:func:`verify_delivery_binding_basis_integrity`)가
# 판 올림만으로 깨지지 않는다. 가공이 있는 요구만 새 키를 갖고 그 digest 는 스스로 일관된다.
DELIVERY_BINDING_BASIS_SCHEMA = "generation-delivery-binding-basis/v3"
# ─── output blocker taxonomy(user-fixable — seal terminal blocker 아님) ─────────────────────
OUTPUT_NAME_TOKEN_UNRESOLVED = "OUTPUT_NAME_TOKEN_UNRESOLVED"
OUTPUT_NAME_BINDING_AMBIGUOUS = "OUTPUT_NAME_BINDING_AMBIGUOUS"
# OUTPUT_NAME_PATTERN_INVALID 는 이름 kernel(:mod:`hwpxfiller.domain.output_name`) 소유 — 위 import.
OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED = "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED"
OUTPUT_PATH_NON_REGULAR_CONFLICT = "OUTPUT_PATH_NON_REGULAR_CONFLICT"

# ─── context/integrity 어휘(user-fixable 로 낮추지 않는 fail-closed 실패) ─────────────────────
GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR = "GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR"
UNSUPPORTED_FILENAME_PATTERN_CONTRACT = "UNSUPPORTED_FILENAME_PATTERN_CONTRACT"
UNSUPPORTED_OVERWRITE_POLICY = "UNSUPPORTED_OVERWRITE_POLICY"
DELIVERY_BINDING_BASIS_INTEGRITY_ERROR = "DELIVERY_BINDING_BASIS_INTEGRITY_ERROR"
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

# value expression kind(field_binding kind 와 같은 어휘).
_KIND_FROM_SOURCE = "FROM_SOURCE"
_KIND_CONSTANT = "CONSTANT"
_KIND_INTENTIONAL_BLANK = "INTENTIONAL_BLANK"
_KIND_RUNTIME_DATE = RUNTIME_DATE

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
    if rule.binding_kind == RUNTIME_DATE:
        # 실행 계획의 인코딩과 같은 모양 — 시각은 싣지 않고(basis 는 시각과 무관) 표시형만 봉인한다.
        return {
            "kind": _KIND_RUNTIME_DATE,
            "format_kind": rule.format_kind,
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


def _render_delivery_runtime_date(
    value_expression: Mapping[str, Any], clock: datetime | None
) -> str:
    """RUNTIME_DATE 토큰 값 — 배달 시각(``captured_delivery_clock``)을 date 표시형으로 렌더한다.

    legacy ``apply_transform("today", …)``·record validation 과 **같은 함수**
    (:func:`~hwpxfiller.domain.field_binding.render_runtime_date`)다. 모양이 어긋나거나 시각이 없으면
    원문·현재 시각으로 메우지 않고 닫는다.
    """
    format_code = value_expression.get("format_code")
    if any(
        value_expression.get(key) is not None
        for key in ("text_slice", "source_key", "canonical_value")
    ):
        raise _DeliveryContextSignal(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            "실행 시각 값에는 데이터 열·고정값·가공이 없다",
        )
    try:
        require_runtime_date_format(value_expression.get("format_kind"), format_code)
    except UnsupportedValueFormatError as exc:
        raise _DeliveryContextSignal(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            f"파일 이름 값의 실행 시각 표시형을 해석할 수 없다: {exc}",
        ) from exc
    if clock is None:
        raise _DeliveryContextSignal(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            "실행 시각 토큰을 렌더할 captured_delivery_clock 이 없다",
        )
    assert isinstance(format_code, str)  # require_runtime_date_format 이 강제
    return render_runtime_date(format_code, clock)


def _runtime_date_requirements(
    requirements: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """Plan 의 Active RUNTIME_DATE requirement(field_id → value expression)."""
    found: dict[str, Mapping[str, Any]] = {}
    for requirement in requirements:
        value_expression = requirement.get("value_expression")
        if (
            isinstance(value_expression, Mapping)
            and value_expression.get("kind") == _KIND_RUNTIME_DATE
        ):
            found[str(requirement.get("field_id"))] = value_expression
    return found


def resolve_delivery_field_value(
    value_expression: Mapping[str, Any],
    snapshot: RawDataRecordSnapshot,
    *,
    clock: datetime | None = None,
) -> str | tuple[str, str]:
    """inactive Field token 값을 exact requirement + raw snapshot 에서 해석한다.

    반환: exact logical text | (blocker_code, detail). 미지원 policy/contract 는 blocker 로
    낮추지 않고 ``_DeliveryContextSignal`` 로 닫는다(fail-closed). Active token 은 이 함수를 거치지 않고
    VDR 값을 재사용한다(RUNTIME_DATE 는 예외 — 모듈 설명). 소스 값은 언제나 타입 없는 텍스트다 —
    여기서 판정하는 것은 존재뿐이다. ``clock`` 은 RUNTIME_DATE 가 렌더할 배달 시각이다.
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
    if kind == _KIND_RUNTIME_DATE:
        return _apply_whitespace_policy(
            _render_delivery_runtime_date(value_expression, clock), policy.whitespace_policy
        )
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
    runtime_by_field = _runtime_date_requirements(
        sealed_execution_plan.active_field_requirements
    )
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
            if field_id in runtime_by_field:
                # 레코드 준비(미리보기 VDR)의 시각이 아니라 배달 시각 — 문서 본문과 같은 값.
                value = _render_delivery_runtime_date(runtime_by_field[field_id], clock)
            elif field_id in active_map:
                value = active_map[field_id]
            elif field_id in inactive_by_field:
                value = resolve_delivery_field_value(
                    inactive_by_field[field_id], snapshot, clock=clock
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


# ─── MaterializationInput = SealedExecutionPlan + ValidatedDataRecord ─────────────────────────
@dataclass(frozen=True)
class MaterializationInput:
    """검증된 Plan·VDR 한 쌍. 배달 경로·배치 순서는 별도 입력이다."""

    plan: SealedExecutionPlanSemanticPayload
    record: ValidatedDataRecord

    def __post_init__(self) -> None:
        verify_validated_record_completeness(self.record, self.plan)

    @property
    def sealed_execution_plan_ref(self) -> str:
        return plan_semantic_digest(self.plan)

    @property
    def validated_record_ref(self) -> str:
        return self.record.validated_record_digest


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
