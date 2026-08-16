"""S5 Plan-bound record validation — raw snapshot + Plan → exact logical document text (S5-12 · #708).

이 모듈이 소유하는 것: :func:`validate_data_record_against_plan` 서비스, ``validated-record/v1``
:class:`ValidatedDataRecord` payload/record/codec/digest, record validation blocker 어휘, logical
document value resolution, requirement-value completeness/integrity 검증, 최소 immutable VDR
ref/retention port(:class:`ImmutableVdrStore`).

서비스는 Plan 의 **모든** Active Field requirement 에 대해 exact logical Unicode document text 를
완성한다:

- ``FROM_SOURCE`` — required source key 를 frozen snapshot 에서만 읽어(mutable row 재조회 0) value
  policy 로 exact 텍스트를 낸다.
- ``CONSTANT`` — Plan 의 canonical tagged constant 를 raw 값과 무관하게 resolve.
- ``INTENTIONAL_BLANK`` — exact empty logical text(missing/null 승인이 아니라 의도된 빈칸).

경계(issue #708): VDR 의 ``document_value`` 는 native writer 에 전달할 **logical Unicode text** 다 —
XML escaped text·XML fragment·serialized ``hp:t`` bytes 가 아니다(그건 S6 소유). unresolved/missing/
null/blank/type-mismatch 는 조용한 빈칸이 아니라 시끄러운 blocker 다(confirm-or-alarm). unsupported
local implementation(format code·unknown policy·미지원 contract)은 user-fixable blocker 로 낮추지
않고 context error 로 닫는다.

canonical framing·digest 는 S5-06 closed set(:mod:`hwpxfiller.domain.canonical_execution_encoding`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from hwpxfiller.application.execution_contract_set import (
    ExecutionBasisIntegrityError,
    ExecutionPlanIntegrityError,
    SealedExecutionPlanSemanticPayload,
    UnsupportedPlanSchemaError,
    execution_basis_digest,
    plan_semantic_digest,
    verify_sealed_plan_integrity,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    CanonicalExecutionEncodingError,
    UnsupportedCanonicalEncodingError,
    canonical_execution_bytes,
    canonical_execution_digest,
)
from hwpxfiller.domain.field_binding import (
    BINDING_VALUE_VERSION,
    BOOLEAN,
    DATE,
    DATETIME,
    DECIMAL,
    EXACT_BLANK_POLICY,
    EXACT_TEXT,
    SOURCE_SCHEMA_VERSION,
    WHITESPACE_PRESERVE_EXACT,
    WHITESPACE_STRIP_LEADING_TRAILING,
    UnsupportedDocumentValuePolicyError,
    resolve_document_value_policy,
)
from hwpxfiller.domain.raw_data_record import (
    RAW_RECORD_CONTRACT_ID,
    RECORD_REVIEW_CONTRACT_ID,
    RECORD_REVIEW_EXAMINED,
    RawDataRecordSnapshot,
    RawRecordIntegrityError,
    RecordReviewEvidence,
    RecordReviewEvidenceIntegrityError,
    SourceNull,
    encode_source_value,
    source_value_type_of,
    verify_raw_record_snapshot,
    verify_record_review_evidence_integrity,
)

VALIDATED_RECORD_SCHEMA_VERSION = "validated-record/v1"
RECORD_VALIDATION_CONTRACT_ID = "record-validation/v1"
DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID = "document-content-value/v1"
# 이 validator 가 지원하는 exact plan schema 집합 — 미지원은 v1 로 풀지 않고 fail-closed.
SUPPORTED_PLAN_SCHEMA_VERSIONS = ("hwpx-execution-plan/v1",)

# boolean logical text — canonical lexical form(v1 결정). downstream 이 format code 로 확장한다.
_BOOLEAN_TRUE_TEXT = "true"
_BOOLEAN_FALSE_TEXT = "false"

# value expression kind(S5-05 encode_value_expression 와 동일 어휘).
_KIND_FROM_SOURCE = "FROM_SOURCE"
_KIND_CONSTANT = "CONSTANT"
_KIND_INTENTIONAL_BLANK = "INTENTIONAL_BLANK"

# ─── record validation blocker 어휘(user-fixable, deterministic Plan order) ───────────────
RECORD_REQUIRED_VALUE_MISSING = "RECORD_REQUIRED_VALUE_MISSING"
RECORD_EXPLICIT_NULL_NOT_ALLOWED = "RECORD_EXPLICIT_NULL_NOT_ALLOWED"
RECORD_VALUE_TYPE_INVALID = "RECORD_VALUE_TYPE_INVALID"
RECORD_VALUE_FORMAT_INVALID = "RECORD_VALUE_FORMAT_INVALID"
RECORD_BLANK_POLICY_VIOLATION = "RECORD_BLANK_POLICY_VIOLATION"
RECORD_REVIEW_REQUIRED = "RECORD_REVIEW_REQUIRED"
RECORD_REVIEW_EVIDENCE_STALE = "RECORD_REVIEW_EVIDENCE_STALE"
RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED = "RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED"

# ─── context/integrity error 어휘(user-fixable 로 낮추지 않는 fail-closed 실패) ─────────────
RAW_RECORD_CANONICALIZATION_ERROR = "RAW_RECORD_CANONICALIZATION_ERROR"
RAW_RECORD_INTEGRITY_ERROR = "RAW_RECORD_INTEGRITY_ERROR"
VALIDATED_RECORD_INTEGRITY_ERROR = "VALIDATED_RECORD_INTEGRITY_ERROR"
PLAN_INTEGRITY_ERROR = "PLAN_INTEGRITY_ERROR"
UNSUPPORTED_RAW_RECORD_CONTRACT = "UNSUPPORTED_RAW_RECORD_CONTRACT"
UNSUPPORTED_RECORD_VALIDATION_CONTRACT = "UNSUPPORTED_RECORD_VALIDATION_CONTRACT"
UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT = (
    "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT"
)
UNSUPPORTED_RECORD_REVIEW_CONTRACT = "UNSUPPORTED_RECORD_REVIEW_CONTRACT"
UNSUPPORTED_SOURCE_SCHEMA_CONTRACT = "UNSUPPORTED_SOURCE_SCHEMA_CONTRACT"
UNSUPPORTED_BINDING_VALUE_CONTRACT = "UNSUPPORTED_BINDING_VALUE_CONTRACT"
RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR = "RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR"


class ValidatedRecordIntegrityError(Exception):
    """VDR 무결성 위반(digest·완결성·Plan 결속) — result 합타입이 아닌 예외."""

    code = VALIDATED_RECORD_INTEGRITY_ERROR


class VdrRetentionError(Exception):
    """immutable VDR ref 가 비어 있거나 복원 불가·content 대체 시도 — 조용히 넘기지 않는다."""

    code = "VDR_RETENTION_ERROR"


# ─── 내부 context 신호(서비스 top 이 RecordValidationContextError 로 변환) ──────────────────
class _ContextSignal(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ─── result 합타입 ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RecordValidationBlocker:
    code: str
    field_id: str | None
    detail: str


@dataclass(frozen=True)
class RecordValidationBlocked:
    """사용자가 source 값/검토를 고치면 풀리는 blocker 집합(deterministic Plan requirement order)."""

    blockers: tuple[RecordValidationBlocker, ...]


@dataclass(frozen=True)
class RecordValidationContextError:
    """평가 자체 불가 — Plan/raw integrity·미지원 contract·tampered evidence(fail-closed)."""

    code: str
    detail: str


@dataclass(frozen=True)
class ValidationProvenance:
    """VDR identity 에서 제외되는 검증 사실(validated_at·review refs·source provenance)."""

    validation_facts: tuple[str, ...]
    record_review_evidence_refs: tuple[str, ...]
    validated_at: str
    source_value_provenance: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class ValidatedDataRecord:
    """Plan 에 결속된 immutable record — 모든 Active requirement 의 exact logical document text.

    ``semantic_payload_encoded`` 는 S5-06 canonical encoder 로 hash 되는 JSON-safe dict(provenance
    제외). ``document_value`` 는 native writer 로 갈 logical Unicode text 이지 XML escaped/fragment 가
    아니다 — escaping 은 S6 소유.
    """

    validated_record_digest: str
    semantic_payload_encoded: Mapping[str, Any]
    validation_provenance: ValidationProvenance

    @property
    def canonical_payload_bytes(self) -> bytes:
        return canonical_execution_bytes(self.semantic_payload_encoded)

    @property
    def plan_semantic_digest(self) -> str:
        return str(self.semantic_payload_encoded["plan_semantic_digest"])

    def document_values_in_order(self) -> tuple[tuple[str, str], ...]:
        """(field_id, document_value) 를 Plan requirement 순서 그대로 반환."""
        return tuple(
            (str(rv["field_id"]), str(rv["document_value"]))
            for rv in self.semantic_payload_encoded["resolved_requirement_values"]
        )


ValidateDataRecordResult = (
    ValidatedDataRecord | RecordValidationBlocked | RecordValidationContextError
)


# ─── logical document value resolution ────────────────────────────────────────────────────
def _apply_whitespace_policy(text: str, whitespace_policy: str) -> str:
    if whitespace_policy == WHITESPACE_STRIP_LEADING_TRAILING:
        return text.strip()
    if whitespace_policy == WHITESPACE_PRESERVE_EXACT:
        return text
    # 미지원 whitespace policy 는 조용히 preserve 로 풀지 않는다(fail-closed).
    raise _ContextSignal(
        UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
        f"미지원 whitespace policy: {whitespace_policy!r}",
    )


def _scalar_literal_text(value_type: str, literal: Any, what: str) -> str:
    """tagged scalar literal → logical text(locale·repr 변환 없음)."""
    if value_type == BOOLEAN:
        if not isinstance(literal, bool):
            raise _ContextSignal(
                UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
                f"{what} BOOLEAN literal 이 bool 이 아니다",
            )
        return _BOOLEAN_TRUE_TEXT if literal else _BOOLEAN_FALSE_TEXT
    if value_type in (EXACT_TEXT, DECIMAL, DATE, DATETIME):
        if not isinstance(literal, str):
            raise _ContextSignal(
                UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
                f"{what} {value_type} literal 이 문자열이 아니다",
            )
        return literal
    raise _ContextSignal(
        UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
        f"{what} 미지원 value_type: {value_type!r}",
    )


def _resolve_policy(policy_id: str) -> Any:
    try:
        return resolve_document_value_policy(policy_id)
    except UnsupportedDocumentValuePolicyError as exc:
        raise _ContextSignal(
            UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT, str(exc)
        ) from exc


def _require_no_format_code(ve: Mapping[str, Any]) -> None:
    """v1 resolution 은 format code 를 구현하지 않는다 — 있으면 조용히 무시하지 않고 닫는다."""
    format_code = ve.get("format_code")
    if format_code is not None and format_code != "":
        raise _ContextSignal(
            UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
            f"v1 resolution 은 format_code 를 지원하지 않는다: {format_code!r}",
        )


def _resolve_from_source(
    ve: Mapping[str, Any],
    field_id: str,
    snapshot: RawDataRecordSnapshot,
) -> str | RecordValidationBlocker:
    """required source key 를 frozen snapshot 에서만 읽어 logical text 를 낸다(row 재조회 0)."""
    _require_no_format_code(ve)
    source_key = ve.get("source_key")
    expected_type = ve.get("value_type")
    if not isinstance(source_key, str) or not isinstance(expected_type, str):
        raise _ContextSignal(
            PLAN_INTEGRITY_ERROR,
            f"FROM_SOURCE requirement {field_id!r} 의 source_key/value_type 형식 불량",
        )
    policy = _resolve_policy(str(ve.get("document_content_value_policy_id")))

    if not snapshot.has_key(source_key):
        return RecordValidationBlocker(
            RECORD_REQUIRED_VALUE_MISSING,
            field_id,
            f"required source key {source_key!r} 가 raw record 에 없다(MISSING)",
        )
    value = snapshot.value_for(source_key)
    if isinstance(value, SourceNull):
        return RecordValidationBlocker(
            RECORD_EXPLICIT_NULL_NOT_ALLOWED,
            field_id,
            f"source key {source_key!r} 가 explicit null 이다",
        )
    assert value is not None  # has_key True 이고 NULL 이 아니면 scalar
    actual_type = source_value_type_of(value)
    if actual_type != expected_type:
        return RecordValidationBlocker(
            RECORD_VALUE_TYPE_INVALID,
            field_id,
            f"source key {source_key!r} 타입 {actual_type} 가 요구 타입 {expected_type} 와 불일치",
        )
    literal = encode_source_value(value)["literal"]
    if expected_type == EXACT_TEXT:
        assert isinstance(literal, str)
        # blank(빈/공백만) source 는 조용히 빈 문서 필드로 새지 않고 시끄럽게 막는다.
        # 의도된 빈칸은 Plan 의 INTENTIONAL_BLANK 이지 blank source 값이 아니다.
        if literal.strip() == "":
            return RecordValidationBlocker(
                RECORD_BLANK_POLICY_VIOLATION,
                field_id,
                f"source key {source_key!r} 가 빈/공백만 텍스트다(blank policy 위반)",
            )
    text = _scalar_literal_text(expected_type, literal, f"source key {source_key!r}")
    return _apply_whitespace_policy(text, policy.whitespace_policy)


def _resolve_constant(ve: Mapping[str, Any], field_id: str) -> str:
    """Plan 의 canonical tagged constant 를 raw 값과 무관하게 logical text 로 resolve."""
    _require_no_format_code(ve)
    policy = _resolve_policy(str(ve.get("document_content_value_policy_id")))
    canonical = ve.get("canonical_value")
    if not isinstance(canonical, Mapping):
        raise _ContextSignal(
            PLAN_INTEGRITY_ERROR,
            f"CONSTANT requirement {field_id!r} 에 canonical_value 가 없다",
        )
    value_type = canonical.get("value_type")
    if not isinstance(value_type, str):
        raise _ContextSignal(
            PLAN_INTEGRITY_ERROR,
            f"CONSTANT requirement {field_id!r} 의 value_type 형식 불량",
        )
    text = _scalar_literal_text(
        value_type, canonical.get("literal"), f"constant {field_id!r}"
    )
    return _apply_whitespace_policy(text, policy.whitespace_policy)


def _resolve_requirement(
    requirement: Mapping[str, Any],
    snapshot: RawDataRecordSnapshot,
) -> str | RecordValidationBlocker:
    field_id = requirement.get("field_id")
    if not isinstance(field_id, str) or field_id == "":
        raise _ContextSignal(PLAN_INTEGRITY_ERROR, "requirement 에 field_id 가 없다")
    ve = requirement.get("value_expression")
    if not isinstance(ve, Mapping):
        raise _ContextSignal(
            PLAN_INTEGRITY_ERROR, f"requirement {field_id!r} 에 value_expression 이 없다"
        )
    kind = ve.get("kind")
    if kind == _KIND_FROM_SOURCE:
        return _resolve_from_source(ve, field_id, snapshot)
    if kind == _KIND_CONSTANT:
        return _resolve_constant(ve, field_id)
    if kind == _KIND_INTENTIONAL_BLANK:
        # exact_blank_policy 를 확인한다 — unknown 을 조용히 WRITE_EMPTY 로 풀지 않는다(fail-closed).
        if ve.get("exact_blank_policy") != EXACT_BLANK_POLICY:
            raise _ContextSignal(
                UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
                f"requirement {field_id!r} 의 미지원 blank policy: "
                f"{ve.get('exact_blank_policy')!r}",
            )
        return ""  # WRITE_EMPTY_TEXT_PRESERVE_FIELD — field 는 보존, 값만 비운다.
    raise _ContextSignal(
        PLAN_INTEGRITY_ERROR, f"requirement {field_id!r} 의 value_expression kind 미상: {kind!r}"
    )


# ─── 주 진입점 ──────────────────────────────────────────────────────────────────────────────
def validate_data_record_against_plan(
    *,
    plan: SealedExecutionPlanSemanticPayload,
    snapshot: RawDataRecordSnapshot,
    review_evidence: RecordReviewEvidence | None = None,
    record_review_required: bool = False,
    validated_at: str,
) -> ValidateDataRecordResult:
    """exact Plan + raw snapshot → 모든 Active requirement 의 logical text 를 완성한 VDR(순수·deterministic).

    precedence: (1) Plan/raw canonical integrity → (2) 미지원 contract → (3) review evidence
    integrity → (4) user-fixable blocker(값·검토) → (5) VDR 봉인·완결성 검증. context/integrity/미지원
    실패는 user-fixable blocker 로 낮추지 않는다(fail-closed).
    """
    try:
        return _validate(
            plan=plan,
            snapshot=snapshot,
            review_evidence=review_evidence,
            record_review_required=record_review_required,
            validated_at=validated_at,
        )
    except _ContextSignal as sig:
        return RecordValidationContextError(sig.code, sig.detail)


def _validate(
    *,
    plan: SealedExecutionPlanSemanticPayload,
    snapshot: RawDataRecordSnapshot,
    review_evidence: RecordReviewEvidence | None,
    record_review_required: bool,
    validated_at: str,
) -> ValidateDataRecordResult:
    # (1) Plan canonical integrity — nested digest·bijection·operation order·supported schema 재검증.
    #     tautological self-schema 가 아니라 validator 의 exact supported set 으로 검증한다(미지원 schema
    #     를 v1 로 풀지 않는다). verifier 가 낼 수 있는 integrity·미지원-version 예외를 전부 잡아 결과
    #     union 밖으로 새지 않게 PLAN_INTEGRITY_ERROR 로 닫는다.
    try:
        verify_sealed_plan_integrity(
            plan, supported_plan_schemas=SUPPORTED_PLAN_SCHEMA_VERSIONS
        )
    except (
        ExecutionPlanIntegrityError,
        UnsupportedPlanSchemaError,
        ExecutionBasisIntegrityError,
        UnsupportedCanonicalEncodingError,
    ) as exc:
        raise _ContextSignal(PLAN_INTEGRITY_ERROR, str(exc)) from exc
    # raw snapshot canonical integrity — digest·lookup·identity 재계산 실패는 결과 union 으로 매핑한다.
    try:
        verify_raw_record_snapshot(snapshot)
    except RawRecordIntegrityError as exc:
        raise _ContextSignal(RAW_RECORD_INTEGRITY_ERROR, str(exc)) from exc
    except CanonicalExecutionEncodingError as exc:
        raise _ContextSignal(RAW_RECORD_CANONICALIZATION_ERROR, str(exc)) from exc

    contracts = plan.execution_basis.contracts
    plan_digest = plan_semantic_digest(plan)
    basis_digest = execution_basis_digest(plan.execution_basis)

    # (2) 미지원 contract — 모든 관여 contract id 를 exact supported constant 와 대조한다. 미지원은
    #     v1 로 풀지 않고 user-fixable 로도 낮추지 않는다(fail-closed context error).
    if contracts.raw_record_contract_id != RAW_RECORD_CONTRACT_ID:
        raise _ContextSignal(
            UNSUPPORTED_RAW_RECORD_CONTRACT,
            f"미지원 raw record contract: {contracts.raw_record_contract_id!r}",
        )
    snap_payload = snapshot.semantic_payload_encoded
    if snap_payload["raw_record_contract_id"] != RAW_RECORD_CONTRACT_ID:
        raise _ContextSignal(
            UNSUPPORTED_RAW_RECORD_CONTRACT,
            "snapshot 의 raw_record_contract_id 가 지원 contract 와 불일치",
        )
    if contracts.source_schema_contract_id != SOURCE_SCHEMA_VERSION:
        raise _ContextSignal(
            UNSUPPORTED_SOURCE_SCHEMA_CONTRACT,
            f"미지원 source schema contract: {contracts.source_schema_contract_id!r}",
        )
    # snapshot 의 source schema contract 가 Plan 과 일치해야 literal 을 같은 의미로 읽는다.
    if snap_payload["source_schema_contract_id"] != contracts.source_schema_contract_id:
        raise _ContextSignal(
            UNSUPPORTED_SOURCE_SCHEMA_CONTRACT,
            "snapshot 의 source_schema_contract_id 가 Plan source schema contract 와 불일치",
        )
    if contracts.binding_value_contract_id != BINDING_VALUE_VERSION:
        raise _ContextSignal(
            UNSUPPORTED_BINDING_VALUE_CONTRACT,
            f"미지원 binding value contract: {contracts.binding_value_contract_id!r}",
        )
    if contracts.record_validation_contract_id != RECORD_VALIDATION_CONTRACT_ID:
        raise _ContextSignal(
            UNSUPPORTED_RECORD_VALIDATION_CONTRACT,
            f"미지원 record validation contract: {contracts.record_validation_contract_id!r}",
        )
    if contracts.record_review_contract_id != RECORD_REVIEW_CONTRACT_ID:
        raise _ContextSignal(
            UNSUPPORTED_RECORD_REVIEW_CONTRACT,
            f"미지원 record review contract: {contracts.record_review_contract_id!r}",
        )
    if contracts.document_value_resolution_contract_id != DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID:
        raise _ContextSignal(
            UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT,
            f"미지원 document value resolution contract: "
            f"{contracts.document_value_resolution_contract_id!r}",
        )

    # 순서 키를 가진 blocker 수집 — Plan requirement order 로 deterministic 정렬한다.
    ordered_blockers: list[tuple[int, RecordValidationBlocker]] = []

    # (3)·(4a) review evidence: integrity(context)·binding(stale blocker)·required(blocker).
    review_ref = _evaluate_review(
        review_evidence=review_evidence,
        record_review_required=record_review_required,
        plan=plan,
        snapshot=snapshot,
        plan_digest=plan_digest,
        blockers=ordered_blockers,
    )

    # (4b) requirement 값 resolution — Plan requirement 순서 그대로.
    resolved: list[dict[str, Any]] = []
    for index, requirement in enumerate(plan.active_field_requirements):
        outcome = _resolve_requirement(requirement, snapshot)
        if isinstance(outcome, RecordValidationBlocker):
            ordered_blockers.append((index, outcome))
            continue
        resolved.append(
            {"field_id": str(requirement["field_id"]), "document_value": outcome}
        )

    if ordered_blockers:
        ordered_blockers.sort(key=lambda ib: (ib[0], ib[1].code, ib[1].field_id or ""))
        return RecordValidationBlocked(tuple(b for _, b in ordered_blockers))

    # (5) VDR 봉인 — payload·digest·완결성 검증.
    payload: dict[str, Any] = {
        "record_schema_version": VALIDATED_RECORD_SCHEMA_VERSION,
        "canonical_encoding_version": CANONICAL_ENCODING_VERSION,
        "plan_semantic_digest": plan_digest,
        "execution_basis_digest": basis_digest,
        "record_identity": snapshot.record_identity,
        "raw_record_digest": snapshot.raw_record_digest,
        "record_validation_contract_id": RECORD_VALIDATION_CONTRACT_ID,
        "document_value_resolution_contract_id": DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
        "resolved_requirement_values": resolved,
    }
    provenance = ValidationProvenance(
        validation_facts=(f"validated:{len(resolved)}",),
        record_review_evidence_refs=(review_ref,) if review_ref is not None else (),
        validated_at=validated_at,
    )
    record = ValidatedDataRecord(
        validated_record_digest=canonical_execution_digest(payload),
        semantic_payload_encoded=_freeze(payload),
        validation_provenance=provenance,
    )
    # 완결성·Plan 결속을 최종 재검증한다(claim 신뢰 금지 — restored input 도 같은 검증을 받는다).
    verify_validated_record_completeness(record, plan)
    return record


def _evaluate_review(
    *,
    review_evidence: RecordReviewEvidence | None,
    record_review_required: bool,
    plan: SealedExecutionPlanSemanticPayload,
    snapshot: RawDataRecordSnapshot,
    plan_digest: str,
    blockers: list[tuple[int, RecordValidationBlocker]],
) -> str | None:
    """review evidence 를 exact Plan/raw/identity/policy 에 대조한다.

    tampered(basis digest 재계산 불일치) → context error. 다른 Plan/raw/identity/contract 에 결속된
    재사용 → RECORD_REVIEW_EVIDENCE_STALE blocker. required 인데 부재 → RECORD_REVIEW_REQUIRED blocker.
    review blocker 는 field 에 매이지 않으므로 정렬 순서 -1(모든 field 앞).
    """
    contracts = plan.execution_basis.contracts
    if review_evidence is None:
        if record_review_required:
            blockers.append(
                (
                    -1,
                    RecordValidationBlocker(
                        RECORD_REVIEW_REQUIRED,
                        None,
                        "이 Plan 은 record review evidence 를 요구하는데 제공되지 않았다",
                    ),
                )
            )
        return None
    # tampered evidence 는 fail-closed context error(user-fixable 아님).
    try:
        verify_record_review_evidence_integrity(review_evidence)
    except RecordReviewEvidenceIntegrityError as exc:
        raise _ContextSignal(RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR, str(exc)) from exc
    basis = plan.execution_basis
    mismatches = (
        review_evidence.plan_semantic_digest != plan_digest
        or review_evidence.raw_record_digest != snapshot.raw_record_digest
        or review_evidence.record_identity != snapshot.record_identity
        or review_evidence.record_review_contract_id != contracts.record_review_contract_id
        or review_evidence.workspace_instance_id != basis.workspace_instance_id
        or review_evidence.work_authority_id != basis.work_authority_id
    )
    if mismatches:
        blockers.append(
            (
                -1,
                RecordValidationBlocker(
                    RECORD_REVIEW_EVIDENCE_STALE,
                    None,
                    "review evidence 가 다른 Plan/raw record/identity/policy 에 결속돼 재사용 불가",
                ),
            )
        )
        return None
    # review policy basis 가 지원 policy(EXAMINED)여야 한다 — self-consistent 한 NOT_REVIEWED 등
    # 임의 basis 를 v1 examination 으로 받지 않는다(fail-closed). 미지원 policy = context error.
    if review_evidence.review_policy_basis != RECORD_REVIEW_EXAMINED:
        raise _ContextSignal(
            UNSUPPORTED_RECORD_REVIEW_CONTRACT,
            f"미지원 review policy basis(examination 아님): "
            f"{review_evidence.review_policy_basis!r}",
        )
    return review_evidence.review_basis_digest


# ─── requirement-value completeness/integrity ──────────────────────────────────────────────
def verify_validated_record_completeness(
    record: ValidatedDataRecord, plan: SealedExecutionPlanSemanticPayload
) -> None:
    """VDR 이 Plan 에 정확히 결속되고 requirement 값이 완결됐는지 재검증한다(fail-closed).

    확인: canonical digest 자기정합·Plan/ExecutionBasis/contract 결속·resolved_requirement_values
    sequence 가 Plan active_field_requirements sequence 와 정확히 동일(집합·순서·중복 0·누락 0·추가 0).
    S6 는 count/order 를 재조립하지 않는다 — 이 검증이 그 전제를 진다.
    """
    payload = record.semantic_payload_encoded
    if canonical_execution_digest(payload) != record.validated_record_digest:
        raise ValidatedRecordIntegrityError(
            "validated record 의 canonical digest 가 content-address 와 불일치"
        )
    # digest 자기정합만으로는 부족하다 — record schema·canonical encoding version 을 exact supported
    # 와 대조한다(미지원 version 을 rehash 로 v1 처럼 통과시키지 않는다, fail-closed).
    if payload.get("record_schema_version") != VALIDATED_RECORD_SCHEMA_VERSION:
        raise ValidatedRecordIntegrityError(
            f"미지원 VDR record schema version: {payload.get('record_schema_version')!r}"
        )
    if payload.get("canonical_encoding_version") != CANONICAL_ENCODING_VERSION:
        raise ValidatedRecordIntegrityError(
            f"미지원 VDR canonical encoding version: {payload.get('canonical_encoding_version')!r}"
        )
    if payload["plan_semantic_digest"] != plan_semantic_digest(plan):
        raise ValidatedRecordIntegrityError("VDR plan_semantic_digest 가 Plan 과 불일치")
    if payload["execution_basis_digest"] != execution_basis_digest(plan.execution_basis):
        raise ValidatedRecordIntegrityError("VDR execution_basis_digest 가 Plan 과 불일치")
    contracts = plan.execution_basis.contracts
    if payload["record_validation_contract_id"] != contracts.record_validation_contract_id:
        raise ValidatedRecordIntegrityError("VDR record_validation_contract_id 가 Plan 과 불일치")
    if (
        payload["document_value_resolution_contract_id"]
        != contracts.document_value_resolution_contract_id
    ):
        raise ValidatedRecordIntegrityError(
            "VDR document_value_resolution_contract_id 가 Plan 과 불일치"
        )
    plan_fields = [str(r["field_id"]) for r in plan.active_field_requirements]
    vdr_fields = [str(rv["field_id"]) for rv in payload["resolved_requirement_values"]]
    if len(set(vdr_fields)) != len(vdr_fields):
        raise ValidatedRecordIntegrityError("VDR resolved_requirement_values 에 중복 field")
    if vdr_fields != plan_fields:
        raise ValidatedRecordIntegrityError(
            "VDR resolved_requirement_values sequence 가 Plan requirement sequence 와 불일치"
        )
    for rv in payload["resolved_requirement_values"]:
        if not isinstance(rv.get("document_value"), str):
            raise ValidatedRecordIntegrityError(
                f"document_value 가 logical text(str)가 아니다: field {rv.get('field_id')!r}"
            )


# ─── 최소 immutable VDR ref/retention port ─────────────────────────────────────────────────
class ImmutableVdrStore:
    """content-addressed(``validated_record_digest``) create-once VDR store — GenerationPlan 수명까지 보존.

    ref 는 곧 content-address 라 같은 ref 는 항상 같은 bytes 로만 resolve 된다. tampered digest·다른
    bytes 로의 대체는 fail-closed. mutable raw row 를 붙들지 않고 봉인된 VDR bytes 만 보존한다.
    """

    # ponytail: process-local dict, no fsync/durability — v1 desktop 은 workspace 당 writer 1 (#620).
    #           durable/run-owned package·GC 는 S5-12 비범위(후속 slice 가 진다).
    def __init__(self) -> None:
        self._by_digest: dict[str, ValidatedDataRecord] = {}

    def put(self, record: ValidatedDataRecord) -> str:
        ref = record.validated_record_digest
        if not isinstance(ref, str) or ref == "":
            raise VdrRetentionError("VDR ref(validated_record_digest)가 비어 있다")
        # digest 를 bytes 에서 재계산해 대조 — claim 만 믿고 저장하지 않는다.
        if canonical_execution_digest(record.semantic_payload_encoded) != ref:
            raise VdrRetentionError("VDR digest 가 canonical bytes 재계산과 불일치")
        existing = self._by_digest.get(ref)
        if existing is not None:
            if existing.canonical_payload_bytes != record.canonical_payload_bytes:
                raise VdrRetentionError("같은 VDR ref 에 다른 canonical bytes(content 대체 금지)")
            return ref  # create-once idempotent
        self._by_digest[ref] = record
        return ref

    def resolve(self, ref: str) -> ValidatedDataRecord:
        record = self._by_digest.get(ref)
        if record is None:
            raise VdrRetentionError(f"VDR ref 복원 불가: {ref!r}")
        if canonical_execution_digest(record.semantic_payload_encoded) != ref:
            raise VdrRetentionError("resolve 한 VDR 의 digest 가 ref 와 불일치")
        return record


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value
