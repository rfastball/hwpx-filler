"""S5 Raw Data Record snapshot·Record Review evidence — mutable row 를 exact bytes 로 고정 (S5-12 · #708).

이 모듈이 소유하는 것: ``raw-data-record/v1`` semantic contract, :data:`CanonicalSourceValue`
합타입(exact tagged scalar + explicit null), :class:`RawDataRecordSnapshot` payload/record/codec/
digest, source adapter duplicate-key boundary, 그리고 :class:`RecordReviewEvidence` 계약·basis digest.

핵심 불변식(issue #708):
- **MISSING ≠ explicit NULL ≠ empty text ≠ whitespace text**. 넷을 절대 합치지 않는다. MISSING 은
  key 부재(snapshot 에 항목 없음), NULL 은 :class:`SourceNull`, empty 는 ``ExactText("")``,
  whitespace 는 ``ExactText(" ")`` 로 서로 다른 저장이다.
- **duplicate exact source key 는 map 축약 전에 거절**(``RAW_RECORD_DUPLICATE_KEY``). source adapter
  가 exact key stream 을 넘기고 이 경계가 첫 축약 전에 검사한다 — dict 로 뭉갠 뒤 보면 늦다.
- **actual row 값은 여기서 얼지만 Plan identity 에 들어가지 않는다**(S5-00 불변식 19). Plan 은 값이
  아니라 requirement 를 식별한다. 값은 이 snapshot·downstream VDR 에서만 산다.

canonical byte framing·SHA-256 은 S5-06 closed set(:mod:`.canonical_execution_encoding`). scalar
검증(canonical decimal·ISO date·명시 timezone·NaN/Infinity 거절·lone surrogate)은 S5-01
:mod:`.field_binding` 의 값 모델을 **그대로 재사용**한다 — source scalar 와 binding constant 는 같은
``binding-value/v1`` 의미 언어를 쓴다. PURE domain: store·HWPX·native·application 을 import 하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    canonical_execution_bytes,
    canonical_execution_digest,
)
from hwpxfiller.domain.field_binding import (
    SOURCE_SCHEMA_VERSION,
    CanonicalBindingValue,
    CanonicalBoolean,
    CanonicalDate,
    CanonicalDateTime,
    CanonicalDecimal,
    ExactText,
    digest_source_schema,
    value_type_of,
)

# ─── semantic 버전·contract id(코드·문서 단일 출처) ─────────────────────────────────────
RAW_RECORD_SCHEMA_VERSION = "raw-data-record/v1"
RAW_RECORD_CONTRACT_ID = "raw-record/v1"
RECORD_REVIEW_CONTRACT_ID = "record-review/v1"
RECORD_REVIEW_BASIS_SCHEMA = "record-review-basis/v1"

# explicit null 의 tagged value_type — empty/whitespace text 와 다른 별개 tag.
SOURCE_NULL_TYPE = "NULL"

# v1 review policy basis — "검토·수용" 이지 승인이 아니다(승인 판단은 S6 밖·이 계층 밖).
RECORD_REVIEW_EXAMINED = "EXAMINED"


class RawDataRecordError(Exception):
    """raw record 의미 오류의 뿌리 — 소비자는 ``.code`` 로 분기한다."""

    code = "RAW_RECORD_ERROR"


class RawRecordDuplicateKeyError(RawDataRecordError):
    code = "RAW_RECORD_DUPLICATE_KEY"


class RawRecordIntegrityError(RawDataRecordError):
    code = "RAW_RECORD_INTEGRITY_ERROR"


class RecordReviewEvidenceIntegrityError(RawDataRecordError):
    code = "RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR"


# ─── CanonicalSourceValue = exact tagged scalar | explicit null ─────────────────────────
@dataclass(frozen=True)
class SourceNull:
    """explicit source null — key 부재(MISSING)와도, empty text 와도 다른 별개 값."""


# source scalar 는 binding-value/v1 값 모델을 그대로 쓴다(같은 canonical 규율·value_type 매핑).
# spec 어휘로 재노출한다 — SourceText("") 는 유효 empty 값이고 SourceNull 과 절대 같지 않다.
SourceText = ExactText
SourceDecimal = CanonicalDecimal
SourceDate = CanonicalDate
SourceDateTime = CanonicalDateTime
SourceBoolean = CanonicalBoolean

CanonicalSourceValue = CanonicalBindingValue | SourceNull


def _require_scalar_text(value: object, what: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RawRecordIntegrityError(f"{what} 는 문자열이어야 한다")
    if not allow_empty and value == "":
        raise RawRecordIntegrityError(f"{what} 는 비어 있을 수 없다")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogate·invalid scalar
        raise RawRecordIntegrityError(f"{what} 에 유효하지 않은 Unicode scalar") from exc
    return value


def source_value_type_of(value: CanonicalSourceValue) -> str:
    """source 값의 value_type 코드 — SourceNull 은 ``NULL``, 나머지는 binding value_type."""
    if isinstance(value, SourceNull):
        return SOURCE_NULL_TYPE
    return value_type_of(value)


def encode_source_value(value: CanonicalSourceValue) -> dict[str, Any]:
    """source 값의 canonical JSON-safe 표현 — NULL 은 literal 없이 tag 만(empty text 와 구분)."""
    if isinstance(value, SourceNull):
        return {"value_type": SOURCE_NULL_TYPE}
    if isinstance(value, ExactText):
        literal: Any = value.text
    elif isinstance(value, CanonicalDecimal):
        literal = value.literal
    elif isinstance(value, CanonicalDate):
        literal = value.iso
    elif isinstance(value, CanonicalDateTime):
        literal = value.iso
    else:  # CanonicalBoolean(합타입 소진)
        literal = value.value
    return {"value_type": source_value_type_of(value), "literal": literal}


# ─── capture provenance(raw semantic digest 에서 제외) ──────────────────────────────────
@dataclass(frozen=True)
class RawRecordCaptureProvenance:
    """capture 사실 — raw_record_digest 에 참여하지 않는다(adapter·관찰 ref·시각)."""

    source_adapter_contract_id: str
    captured_at: str
    source_observation_ref: str | None = None

    def __post_init__(self) -> None:
        _require_scalar_text(
            self.source_adapter_contract_id, "source_adapter_contract_id"
        )
        _require_scalar_text(self.captured_at, "captured_at")
        if self.source_observation_ref is not None:
            _require_scalar_text(self.source_observation_ref, "source_observation_ref")


# ─── RawDataRecordSnapshot ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RawDataRecordSnapshot:
    """mutable row 를 고정한 immutable snapshot — exact tagged scalar + canonical digest.

    ``semantic_payload_encoded`` 는 S5-06 canonical encoder 로 hash 되는 JSON-safe dict 다
    (capture provenance 제외). ``_values`` 는 source_key → :data:`CanonicalSourceValue` lookup 으로,
    validation 이 mutable row 를 다시 읽지 않고 이 frozen 사본만 참조하게 한다.
    """

    raw_record_digest: str
    record_identity: str
    source_schema_digest: str
    semantic_payload_encoded: Mapping[str, Any]
    capture_provenance: RawRecordCaptureProvenance
    _values: Mapping[str, CanonicalSourceValue]

    @property
    def canonical_payload_bytes(self) -> bytes:
        return canonical_execution_bytes(self.semantic_payload_encoded)

    def has_key(self, source_key: str) -> bool:
        return source_key in self._values

    def value_for(self, source_key: str) -> CanonicalSourceValue | None:
        """존재하면 exact source 값, 부재(MISSING)면 ``None``. NULL 은 :class:`SourceNull` 로 반환."""
        return self._values.get(source_key)


def build_raw_record_snapshot(
    *,
    source_schema_keys: Iterable[str],
    source_values: Iterable[tuple[str, CanonicalSourceValue]],
    record_identity: str,
    capture_provenance: RawRecordCaptureProvenance,
) -> RawDataRecordSnapshot:
    """source adapter 의 exact key stream 을 snapshot 으로 고정한다(duplicate 는 축약 전에 거절).

    ``source_values`` 는 map 이 아니라 exact (key, value) stream 이어야 한다 — dict 로 뭉갠 뒤에는
    duplicate 를 볼 수 없다(issue 즉시 상향 조건). 첫 dict 축약 전에 중복 key 를 검사한다. schema 에
    없는 additional key 도 exact 하게 보존한다(v1 정책: unused key 는 Plan/VDR requirement 에 무영향).
    """
    _require_scalar_text(record_identity, "record_identity")

    # duplicate exact key 를 map 축약(그리고 schema digest) 전에 먼저 거절한다 — RAW_RECORD_DUPLICATE_KEY.
    values: dict[str, CanonicalSourceValue] = {}
    for key, value in source_values:
        _require_scalar_text(key, "source_key", allow_empty=True)
        if not isinstance(value, (SourceNull, ExactText, CanonicalDecimal,
                                  CanonicalDate, CanonicalDateTime, CanonicalBoolean)):
            raise RawRecordIntegrityError(
                f"source value 가 CanonicalSourceValue 가 아니다: {key!r}"
            )
        if key in values:
            raise RawRecordDuplicateKeyError(f"raw record 중복 exact source key: {key!r}")
        values[key] = value

    schema_digest = digest_source_schema(source_schema_keys)

    # source_values[] 는 source_key unsigned UTF-8 byte order — 삽입/adapter 순서 무관 digest.
    ordered = sorted(values.items(), key=lambda kv: kv[0].encode("utf-8"))
    payload: dict[str, Any] = {
        "raw_record_schema_version": RAW_RECORD_SCHEMA_VERSION,
        "canonical_encoding_version": CANONICAL_ENCODING_VERSION,
        "source_schema_contract_id": SOURCE_SCHEMA_VERSION,
        "raw_record_contract_id": RAW_RECORD_CONTRACT_ID,
        "record_identity": record_identity,
        "source_schema_digest": schema_digest,
        "source_values": [
            {"source_key": key, "tagged_value": encode_source_value(value)}
            for key, value in ordered
        ],
    }
    return RawDataRecordSnapshot(
        raw_record_digest=canonical_execution_digest(payload),
        record_identity=record_identity,
        source_schema_digest=schema_digest,
        semantic_payload_encoded=_freeze(payload),
        capture_provenance=capture_provenance,
        _values=MappingProxyType(dict(values)),
    )


def verify_raw_record_snapshot(snapshot: RawDataRecordSnapshot) -> None:
    """저장 payload 의 canonical digest 가 자기 content-address 와 같은지 재계산·대조(fail-closed)."""
    recomputed = canonical_execution_digest(snapshot.semantic_payload_encoded)
    if recomputed != snapshot.raw_record_digest:
        raise RawRecordIntegrityError(
            "raw record snapshot 의 canonical digest 가 content-address 와 불일치"
        )


# ─── RecordReviewEvidence ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RecordReviewEvidence:
    """raw record 가 검토·수용됐다는 증거 — exact Plan·raw record·record identity·policy 에 결속.

    ``review_basis_digest`` 는 plan_semantic_digest·raw_record_digest·record_identity·contract·exact
    review policy basis 만 hash 한다. ``reviewed_at``·``actor_binding`` 은 provenance 로 보존하되 basis
    에서 제외한다 — 그래서 다른 Plan/raw/identity/policy 에는 재사용되지 않는다(digest 로 시끄럽게 걸린다).
    """

    workspace_instance_id: str
    work_authority_id: str
    plan_semantic_digest: str
    raw_record_digest: str
    record_identity: str
    record_review_contract_id: str
    review_policy_basis: str
    review_basis_digest: str
    actor_binding: str
    reviewed_at: str

    def __post_init__(self) -> None:
        for name in (
            "workspace_instance_id",
            "work_authority_id",
            "plan_semantic_digest",
            "raw_record_digest",
            "record_identity",
            "record_review_contract_id",
            "review_policy_basis",
            "review_basis_digest",
            "actor_binding",
            "reviewed_at",
        ):
            _require_scalar_text(getattr(self, name), name)


def _review_basis_payload(
    *,
    plan_semantic_digest: str,
    raw_record_digest: str,
    record_identity: str,
    record_review_contract_id: str,
    review_policy_basis: str,
) -> dict[str, Any]:
    return {
        "record_review_basis_schema": RECORD_REVIEW_BASIS_SCHEMA,
        "plan_semantic_digest": plan_semantic_digest,
        "raw_record_digest": raw_record_digest,
        "record_identity": record_identity,
        "record_review_contract_id": record_review_contract_id,
        "review_policy_basis": review_policy_basis,
    }


def compute_review_basis_digest(
    *,
    plan_semantic_digest: str,
    raw_record_digest: str,
    record_identity: str,
    record_review_contract_id: str,
    review_policy_basis: str,
) -> str:
    """review basis 의 content-address — reviewed_at·actor session token 제외."""
    return canonical_execution_digest(
        _review_basis_payload(
            plan_semantic_digest=plan_semantic_digest,
            raw_record_digest=raw_record_digest,
            record_identity=record_identity,
            record_review_contract_id=record_review_contract_id,
            review_policy_basis=review_policy_basis,
        )
    )


def build_record_review_evidence(
    *,
    workspace_instance_id: str,
    work_authority_id: str,
    plan_semantic_digest: str,
    raw_record_digest: str,
    record_identity: str,
    record_review_contract_id: str = RECORD_REVIEW_CONTRACT_ID,
    review_policy_basis: str = RECORD_REVIEW_EXAMINED,
    actor_binding: str,
    reviewed_at: str,
) -> RecordReviewEvidence:
    """exact Plan·raw·identity·policy 에 결속된 review evidence 를 만든다(basis digest 계산 포함)."""
    return RecordReviewEvidence(
        workspace_instance_id=workspace_instance_id,
        work_authority_id=work_authority_id,
        plan_semantic_digest=plan_semantic_digest,
        raw_record_digest=raw_record_digest,
        record_identity=record_identity,
        record_review_contract_id=record_review_contract_id,
        review_policy_basis=review_policy_basis,
        review_basis_digest=compute_review_basis_digest(
            plan_semantic_digest=plan_semantic_digest,
            raw_record_digest=raw_record_digest,
            record_identity=record_identity,
            record_review_contract_id=record_review_contract_id,
            review_policy_basis=review_policy_basis,
        ),
        actor_binding=actor_binding,
        reviewed_at=reviewed_at,
    )


def verify_record_review_evidence_integrity(evidence: RecordReviewEvidence) -> None:
    """review_basis_digest 를 재계산해 대조 — tamper 된 evidence 를 시끄럽게 닫는다(fail-closed)."""
    recomputed = compute_review_basis_digest(
        plan_semantic_digest=evidence.plan_semantic_digest,
        raw_record_digest=evidence.raw_record_digest,
        record_identity=evidence.record_identity,
        record_review_contract_id=evidence.record_review_contract_id,
        review_policy_basis=evidence.review_policy_basis,
    )
    if recomputed != evidence.review_basis_digest:
        raise RecordReviewEvidenceIntegrityError(
            "review_basis_digest 재계산 불일치(tampered evidence)"
        )


def _freeze(value: Any) -> Any:
    """JSON-safe 값을 재귀 동결한다(dict→MappingProxyType, list→tuple) — 봉인 뒤 변이 차단."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value
