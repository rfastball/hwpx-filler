"""content-addressed Plan aggregate value model·codec·전이(S5-07 · #703).

S5-06(:mod:`.execution_contract_set`)이 Plan identity(``plan_semantic_digest``)·
``PlanCompilationKey``·``DurableSealCaptureEvidence`` 를 이미 소유한다. 이 모듈은 그 위에
**durable Work aggregate** 의 값 모델과 순수 전이를 얹는다:

- ``SealedExecutionPlanRecord`` — content-address(``plan_semantic_digest``)로 주소화하는
  create-once Plan record. random/current/latest/superseded pointer 를 만들지 않는다.
- ``plans_by_compilation_key`` — ``PlanCompilationKey → plan_semantic_digest`` functional
  dependency(같은 key 에 다른 payload = loud integrity error, 조용한 overwrite 금지).
- append-only ``first_seen_ledger`` — request 별 first-seen terminal outcome. reuse 요청도
  자기 durable capture evidence 로 새 ledger entry 를 남긴다.
- Plan dependency set(append-only retention refs) — upstream object 를 GC 하지 않고 참조만 보존.

파일 I/O·lease·CAS·atomic replace 는 :mod:`hwpxfiller.external.work_execution_plan_store` 소유다.
이 모듈은 **순수** 하다: 저장소·HWPX·native 를 import 하지 않고, 전이는 새 frozen aggregate 를 낸다.

fail-closed: unknown schema/encoding·digest 불일치·compilation 충돌·idempotency 키 재사용은
latest 로 풀지 않고 시끄럽게 닫는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from hwpxfiller.application.execution_capture import ResolvedSealPolicy
from hwpxfiller.application.execution_contract_set import (
    CompleteSealCaptureEvidence,
    DurableCaptureEvidenceIntegrityError,
    DurableSealCaptureEvidence,
    ExecutionPlanCompilationIntegrityError,
    ExecutionPlanIntegrityError,
    SealedExecutionPlanSemanticPayload,
    decode_durable_capture_evidence,
    encode_durable_capture_evidence,
    encode_sealed_plan,
    execution_basis_digest,
    plan_compilation_key_digest,
    plan_compilation_key_of,
    plan_semantic_digest,
    verify_sealed_plan_integrity,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    canonical_execution_bytes,
    canonical_execution_digest,
    require_supported_encoding,
)

PLAN_STORE_SCHEMA_VERSION = "work-execution-plan-store/v1"

_CREATED = "CREATED"
_REUSED = "REUSED"
_PUBLICATION_KINDS = frozenset({_CREATED, _REUSED})
_STALE_REASONS = frozenset({"DIGEST_MISMATCH", "CURRENT_BASIS_NOT_SEALABLE"})

_AUTO = "AUTO"
_EXACT = "EXACT"


# ─── 오류 ────────────────────────────────────────────────────────────────────────────
class ExecutionPlanStoreError(Exception):
    """Plan store 전이/영속 경계의 loud failure 기반."""

    code = "EXECUTION_PLAN_STORE_ERROR"


class StoreConcurrentModification(ExecutionPlanStoreError):
    """expected aggregate_version 이 현재와 불일치(CAS 실패) — first commit wins."""

    code = "STORE_CONCURRENT_MODIFICATION"


class IdempotencyKeyReused(ExecutionPlanStoreError):
    """같은 request ID 가 다른 intent fingerprint 로 재사용됨 — 최초 record 수정 0."""

    code = "IDEMPOTENCY_KEY_REUSED"


class ExecutionPlanDependencyResolutionError(ExecutionPlanStoreError):
    """Plan dependency ref 가 비어 있거나 복원 불가 — 조용히 넘기지 않는다."""

    code = "EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR"


class ExecutionPlanStoreIntegrityError(ExecutionPlanStoreError):
    """persisted aggregate envelope/schema/구조 손상 — partial 을 current 로 승격하지 않는다."""

    code = "EXECUTION_PLAN_INTEGRITY_ERROR"


# ─── 작은 검증 헬퍼 ──────────────────────────────────────────────────────────────────
def _require_str(value: object, what: str) -> str:
    # str() 강제 변환 금지 — null/number/list 를 조용히 문자열로 만들지 않고 fail-closed.
    if not isinstance(value, str) or value == "":
        raise ExecutionPlanStoreIntegrityError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


def _optional_str(value: object, what: str) -> "str | None":
    if value is None:
        return None
    return _require_str(value, what)


def _require_mapping(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionPlanStoreIntegrityError(f"{what} 는 매핑이어야 한다")
    return value


# ─── RequestedVersionSelector = AUTO | EXACT(value) ──────────────────────────────────
@dataclass(frozen=True)
class RequestedAuto:
    """서버 default 로 resolve 하라는 raw intent — resolve 된 exact 값과 동일 취급 금지."""


@dataclass(frozen=True)
class RequestedExact:
    """요청자가 못박은 exact contract/schema/encoding 값."""

    value: str

    def __post_init__(self) -> None:
        _require_str(self.value, "RequestedExact.value")


RequestedVersionSelector = RequestedAuto | RequestedExact


def _encode_selector(selector: RequestedVersionSelector) -> dict[str, Any]:
    if isinstance(selector, RequestedAuto):
        return {"kind": _AUTO}
    return {"kind": _EXACT, "value": selector.value}


def _decode_selector(value: object, what: str) -> RequestedVersionSelector:
    payload = _require_mapping(value, what)
    kind = payload.get("kind")
    if kind == _AUTO:
        return RequestedAuto()
    if kind == _EXACT:
        return RequestedExact(_require_str(payload.get("value"), f"{what}.value"))
    raise ExecutionPlanStoreIntegrityError(f"{what} selector kind 미상: {kind!r}")


# ─── SealRequestIntentFingerprintPayload ─────────────────────────────────────────────
@dataclass(frozen=True)
class SealRequestIntentFingerprintPayload:
    """raw request intent — resolve 결과가 아니다. AUTO 와 현재 resolve 값을 같은 intent 로 두지 않는다."""

    command_schema_version: str
    workspace_instance_id: str
    work_authority_id: str
    requested_execution_base_kind: str
    requested_execution_semantic_contract: RequestedVersionSelector
    requested_plan_schema: RequestedVersionSelector
    requested_canonical_encoding: RequestedVersionSelector

    def __post_init__(self) -> None:
        for name in (
            "command_schema_version",
            "workspace_instance_id",
            "work_authority_id",
            "requested_execution_base_kind",
        ):
            _require_str(getattr(self, name), name)


def encode_request_intent_fingerprint(
    fp: SealRequestIntentFingerprintPayload,
) -> dict[str, Any]:
    return {
        "command_schema_version": fp.command_schema_version,
        "workspace_instance_id": fp.workspace_instance_id,
        "work_authority_id": fp.work_authority_id,
        "requested_execution_base_kind": fp.requested_execution_base_kind,
        "requested_execution_semantic_contract": _encode_selector(
            fp.requested_execution_semantic_contract
        ),
        "requested_plan_schema": _encode_selector(fp.requested_plan_schema),
        "requested_canonical_encoding": _encode_selector(fp.requested_canonical_encoding),
    }


def decode_request_intent_fingerprint(
    value: object,
) -> SealRequestIntentFingerprintPayload:
    payload = _require_mapping(value, "request_intent_fingerprint")
    return SealRequestIntentFingerprintPayload(
        command_schema_version=_require_str(
            payload.get("command_schema_version"), "command_schema_version"
        ),
        workspace_instance_id=_require_str(
            payload.get("workspace_instance_id"), "workspace_instance_id"
        ),
        work_authority_id=_require_str(
            payload.get("work_authority_id"), "work_authority_id"
        ),
        requested_execution_base_kind=_require_str(
            payload.get("requested_execution_base_kind"), "requested_execution_base_kind"
        ),
        requested_execution_semantic_contract=_decode_selector(
            payload.get("requested_execution_semantic_contract"),
            "requested_execution_semantic_contract",
        ),
        requested_plan_schema=_decode_selector(
            payload.get("requested_plan_schema"), "requested_plan_schema"
        ),
        requested_canonical_encoding=_decode_selector(
            payload.get("requested_canonical_encoding"), "requested_canonical_encoding"
        ),
    )


def request_intent_fingerprint_digest(fp: SealRequestIntentFingerprintPayload) -> str:
    """raw intent 의 content-address — idempotency 재사용 판정의 단일 seam."""
    return canonical_execution_digest(encode_request_intent_fingerprint(fp))


# ─── ResolvedSealPolicy codec(재사용, 순수 field 열거) ───────────────────────────────
def _encode_resolved_policy(policy: ResolvedSealPolicy) -> dict[str, Any]:
    return {f.name: getattr(policy, f.name) for f in fields(policy)}


def _decode_resolved_policy(value: object) -> ResolvedSealPolicy:
    payload = _require_mapping(value, "resolved_seal_policy")
    # 모든 field 는 nonempty str(ResolvedSealPolicy.__post_init__ 가 강제) — 여기서 shape 검증.
    kwargs = {
        f.name: _require_str(payload.get(f.name), f"resolved_seal_policy.{f.name}")
        for f in fields(ResolvedSealPolicy)
    }
    return ResolvedSealPolicy(**kwargs)


# ─── PlanDependencySet(append-only retention refs) ───────────────────────────────────
@dataclass(frozen=True)
class PlanDependencySet:
    """Plan 존재 동안 GC 되지 않는 upstream object 참조들(refs 만 보존, ownership 이동 없음).

    runtime implementation/conformance manifest 는 semantic dependency 가 아니라 여기 없다.
    """

    candidate_blob_ref: str
    pass_evidence_ref: str
    qualification_profile_manifest_ref: str
    template_structure_projection_ref: str
    execution_contract_set_ref: str
    composition_theorem_evidence_manifest_ref: str

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not isinstance(value, str) or value == "":
                raise ExecutionPlanDependencyResolutionError(
                    f"Plan dependency ref {f.name} 가 비어 있다"
                )


def _encode_dependency_set(dep: PlanDependencySet) -> dict[str, Any]:
    return {f.name: getattr(dep, f.name) for f in fields(dep)}


def _decode_dependency_set(value: object) -> PlanDependencySet:
    payload = _require_mapping(value, "dependency_set")
    kwargs = {
        f.name: _require_str(payload.get(f.name), f"dependency_set.{f.name}")
        for f in fields(PlanDependencySet)
    }
    return PlanDependencySet(**kwargs)


# ─── SealedExecutionPlanRecord(create-once, content-address) ─────────────────────────
@dataclass(frozen=True)
class PlanFirstSealedProvenance:
    """digest 에 참여하지 않는 최초 봉인 사실(stable audit facts)."""

    first_sealed_at: str
    first_sealed_by_request_id: str

    def __post_init__(self) -> None:
        _require_str(self.first_sealed_at, "first_sealed_at")
        _require_str(self.first_sealed_by_request_id, "first_sealed_by_request_id")


@dataclass(frozen=True)
class SealedExecutionPlanRecord:
    """``plan_semantic_digest`` 로 주소화하는 immutable Plan record.

    ``semantic_payload_encoded`` 는 S5-06 :func:`encode_sealed_plan` 의 canonical dict 다 —
    stored bytes 가 자기 key 로 hash 되지 않으면 corruption(:func:`verify_record_content_address`).
    """

    plan_semantic_digest: str
    semantic_payload_encoded: Mapping[str, Any]
    dependency_set: PlanDependencySet
    first_sealed_provenance: PlanFirstSealedProvenance

    @property
    def canonical_payload_bytes(self) -> bytes:
        return canonical_execution_bytes(self.semantic_payload_encoded)


def verify_record_content_address(record: SealedExecutionPlanRecord) -> None:
    """stored payload 의 canonical digest 가 자기 content-address 와 같은지 검증(fail-closed)."""
    recomputed = canonical_execution_digest(record.semantic_payload_encoded)
    if recomputed != record.plan_semantic_digest:
        raise ExecutionPlanIntegrityError(
            "Plan record 의 canonical digest 가 content-address(key)와 불일치"
        )


def _encode_plan_record(record: SealedExecutionPlanRecord) -> dict[str, Any]:
    return {
        "plan_semantic_digest": record.plan_semantic_digest,
        "semantic_payload": dict(record.semantic_payload_encoded),
        "dependency_set": _encode_dependency_set(record.dependency_set),
        "first_sealed_provenance": {
            "first_sealed_at": record.first_sealed_provenance.first_sealed_at,
            "first_sealed_by_request_id": (
                record.first_sealed_provenance.first_sealed_by_request_id
            ),
        },
    }


def _decode_plan_record(value: object) -> SealedExecutionPlanRecord:
    payload = _require_mapping(value, "plan record")
    provenance = _require_mapping(
        payload.get("first_sealed_provenance"), "first_sealed_provenance"
    )
    record = SealedExecutionPlanRecord(
        plan_semantic_digest=_require_str(
            payload.get("plan_semantic_digest"), "plan_semantic_digest"
        ),
        semantic_payload_encoded=dict(
            _require_mapping(payload.get("semantic_payload"), "semantic_payload")
        ),
        dependency_set=_decode_dependency_set(payload.get("dependency_set")),
        first_sealed_provenance=PlanFirstSealedProvenance(
            first_sealed_at=_require_str(
                provenance.get("first_sealed_at"), "first_sealed_at"
            ),
            first_sealed_by_request_id=_require_str(
                provenance.get("first_sealed_by_request_id"),
                "first_sealed_by_request_id",
            ),
        ),
    )
    verify_record_content_address(record)
    return record


# ─── SealTerminalOutcome = 4 변형 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlanPublished:
    publication_kind: str  # CREATED | REUSED
    plan_semantic_digest: str
    execution_basis_digest: str
    captured_execution_input_digest: str

    def __post_init__(self) -> None:
        if self.publication_kind not in _PUBLICATION_KINDS:
            raise ExecutionPlanStoreIntegrityError(
                f"publication_kind 미상: {self.publication_kind!r}"
            )
        _require_str(self.plan_semantic_digest, "plan_semantic_digest")
        _require_str(self.execution_basis_digest, "execution_basis_digest")
        _require_str(
            self.captured_execution_input_digest, "captured_execution_input_digest"
        )


@dataclass(frozen=True)
class ExecutionQualificationBlocked:
    capture_evidence_ref: str
    normalized_blockers: tuple[str, ...]
    captured_execution_input_digest: "str | None" = None
    captured_attempt_digest: "str | None" = None

    def __post_init__(self) -> None:
        _require_str(self.capture_evidence_ref, "capture_evidence_ref")
        if not all(isinstance(b, str) and b for b in self.normalized_blockers):
            raise ExecutionPlanStoreIntegrityError("normalized_blockers 형식 불량")


@dataclass(frozen=True)
class ExecutionPolicyBlocked:
    policy_code: str
    qualification_profile_id: "str | None" = None
    observed_policy_version: "str | None" = None
    policy_observation_digest: "str | None" = None
    captured_attempt_digest: "str | None" = None

    def __post_init__(self) -> None:
        _require_str(self.policy_code, "policy_code")


@dataclass(frozen=True)
class StaleExecutionBasis:
    captured_execution_input_digest: str
    candidate_execution_basis_digest: str
    stale_reason: str  # DIGEST_MISMATCH | CURRENT_BASIS_NOT_SEALABLE
    observed_current_summary: "Mapping[str, Any] | None" = None

    def __post_init__(self) -> None:
        _require_str(
            self.captured_execution_input_digest, "captured_execution_input_digest"
        )
        _require_str(
            self.candidate_execution_basis_digest, "candidate_execution_basis_digest"
        )
        if self.stale_reason not in _STALE_REASONS:
            raise ExecutionPlanStoreIntegrityError(
                f"stale_reason 미상: {self.stale_reason!r}"
            )


SealTerminalOutcome = (
    PlanPublished | ExecutionQualificationBlocked | ExecutionPolicyBlocked | StaleExecutionBasis
)

_OUTCOME_PUBLISHED = "PLAN_PUBLISHED"
_OUTCOME_QUALIFICATION = "EXECUTION_QUALIFICATION_BLOCKED"
_OUTCOME_POLICY = "EXECUTION_POLICY_BLOCKED"
_OUTCOME_STALE = "STALE_EXECUTION_BASIS"


def _encode_terminal_outcome(outcome: SealTerminalOutcome) -> dict[str, Any]:
    if isinstance(outcome, PlanPublished):
        return {
            "kind": _OUTCOME_PUBLISHED,
            "publication_kind": outcome.publication_kind,
            "plan_semantic_digest": outcome.plan_semantic_digest,
            "execution_basis_digest": outcome.execution_basis_digest,
            "captured_execution_input_digest": outcome.captured_execution_input_digest,
        }
    if isinstance(outcome, ExecutionQualificationBlocked):
        return {
            "kind": _OUTCOME_QUALIFICATION,
            "capture_evidence_ref": outcome.capture_evidence_ref,
            "normalized_blockers": list(outcome.normalized_blockers),
            "captured_execution_input_digest": outcome.captured_execution_input_digest,
            "captured_attempt_digest": outcome.captured_attempt_digest,
        }
    if isinstance(outcome, ExecutionPolicyBlocked):
        return {
            "kind": _OUTCOME_POLICY,
            "policy_code": outcome.policy_code,
            "qualification_profile_id": outcome.qualification_profile_id,
            "observed_policy_version": outcome.observed_policy_version,
            "policy_observation_digest": outcome.policy_observation_digest,
            "captured_attempt_digest": outcome.captured_attempt_digest,
        }
    return {
        "kind": _OUTCOME_STALE,
        "captured_execution_input_digest": outcome.captured_execution_input_digest,
        "candidate_execution_basis_digest": outcome.candidate_execution_basis_digest,
        "stale_reason": outcome.stale_reason,
        "observed_current_summary": (
            dict(outcome.observed_current_summary)
            if outcome.observed_current_summary is not None
            else None
        ),
    }


def _decode_terminal_outcome(value: object) -> SealTerminalOutcome:
    payload = _require_mapping(value, "terminal_outcome")
    kind = payload.get("kind")
    if kind == _OUTCOME_PUBLISHED:
        return PlanPublished(
            publication_kind=_require_str(
                payload.get("publication_kind"), "publication_kind"
            ),
            plan_semantic_digest=_require_str(
                payload.get("plan_semantic_digest"), "plan_semantic_digest"
            ),
            execution_basis_digest=_require_str(
                payload.get("execution_basis_digest"), "execution_basis_digest"
            ),
            captured_execution_input_digest=_require_str(
                payload.get("captured_execution_input_digest"),
                "captured_execution_input_digest",
            ),
        )
    if kind == _OUTCOME_QUALIFICATION:
        blockers = payload.get("normalized_blockers")
        if not isinstance(blockers, list) or not all(isinstance(b, str) for b in blockers):
            raise ExecutionPlanStoreIntegrityError("normalized_blockers 형식 불량")
        return ExecutionQualificationBlocked(
            capture_evidence_ref=_require_str(
                payload.get("capture_evidence_ref"), "capture_evidence_ref"
            ),
            normalized_blockers=tuple(blockers),
            captured_execution_input_digest=_optional_str(
                payload.get("captured_execution_input_digest"),
                "captured_execution_input_digest",
            ),
            captured_attempt_digest=_optional_str(
                payload.get("captured_attempt_digest"), "captured_attempt_digest"
            ),
        )
    if kind == _OUTCOME_POLICY:
        return ExecutionPolicyBlocked(
            policy_code=_require_str(payload.get("policy_code"), "policy_code"),
            qualification_profile_id=_optional_str(
                payload.get("qualification_profile_id"), "qualification_profile_id"
            ),
            observed_policy_version=_optional_str(
                payload.get("observed_policy_version"), "observed_policy_version"
            ),
            policy_observation_digest=_optional_str(
                payload.get("policy_observation_digest"), "policy_observation_digest"
            ),
            captured_attempt_digest=_optional_str(
                payload.get("captured_attempt_digest"), "captured_attempt_digest"
            ),
        )
    if kind == _OUTCOME_STALE:
        summary = payload.get("observed_current_summary")
        return StaleExecutionBasis(
            captured_execution_input_digest=_require_str(
                payload.get("captured_execution_input_digest"),
                "captured_execution_input_digest",
            ),
            candidate_execution_basis_digest=_require_str(
                payload.get("candidate_execution_basis_digest"),
                "candidate_execution_basis_digest",
            ),
            stale_reason=_require_str(payload.get("stale_reason"), "stale_reason"),
            observed_current_summary=(
                dict(_require_mapping(summary, "observed_current_summary"))
                if summary is not None
                else None
            ),
        )
    raise ExecutionPlanStoreIntegrityError(f"미지원 terminal outcome kind: {kind!r}")


# ─── FirstSeenSealCommandRecord ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class FirstSeenSealCommandRecord:
    request_id: str
    request_intent_fingerprint: SealRequestIntentFingerprintPayload
    request_intent_fingerprint_digest: str
    resolved_seal_policy: ResolvedSealPolicy
    durable_capture_evidence: DurableSealCaptureEvidence
    terminal_outcome: SealTerminalOutcome
    first_completed_at: str


def _encode_first_seen(record: FirstSeenSealCommandRecord) -> dict[str, Any]:
    return {
        "request_id": record.request_id,
        "request_intent_fingerprint": encode_request_intent_fingerprint(
            record.request_intent_fingerprint
        ),
        "request_intent_fingerprint_digest": record.request_intent_fingerprint_digest,
        "resolved_seal_policy": _encode_resolved_policy(record.resolved_seal_policy),
        "durable_capture_evidence": encode_durable_capture_evidence(
            record.durable_capture_evidence
        ),
        "terminal_outcome": _encode_terminal_outcome(record.terminal_outcome),
        "first_completed_at": record.first_completed_at,
    }


def _decode_first_seen(value: object) -> FirstSeenSealCommandRecord:
    payload = _require_mapping(value, "first-seen record")
    fingerprint = decode_request_intent_fingerprint(
        payload.get("request_intent_fingerprint")
    )
    stored_digest = _require_str(
        payload.get("request_intent_fingerprint_digest"),
        "request_intent_fingerprint_digest",
    )
    # fingerprint digest 를 재계산해 대조 — 저장된 digest 만 믿지 않는다(신뢰 경계).
    if request_intent_fingerprint_digest(fingerprint) != stored_digest:
        raise ExecutionPlanStoreIntegrityError(
            "request_intent_fingerprint_digest 재계산 불일치"
        )
    try:
        evidence = decode_durable_capture_evidence(payload.get("durable_capture_evidence"))
    except DurableCaptureEvidenceIntegrityError as exc:
        raise ExecutionPlanStoreIntegrityError(
            f"durable capture evidence 손상: {exc}"
        ) from exc
    return FirstSeenSealCommandRecord(
        request_id=_require_str(payload.get("request_id"), "request_id"),
        request_intent_fingerprint=fingerprint,
        request_intent_fingerprint_digest=stored_digest,
        resolved_seal_policy=_decode_resolved_policy(payload.get("resolved_seal_policy")),
        durable_capture_evidence=evidence,
        terminal_outcome=_decode_terminal_outcome(payload.get("terminal_outcome")),
        first_completed_at=_require_str(
            payload.get("first_completed_at"), "first_completed_at"
        ),
    )


# ─── WorkExecutionPlanAggregate ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class WorkExecutionPlanAggregate:
    """Work(``work_authority_id``) 단위 durable aggregate — current/latest pointer 를 담지 않는다.

    currentness 는 저장하지 않는다: Work 의 현재 basis 와의 equality 로 파생한다.
    """

    work_authority_id: str
    workspace_instance_id: str
    aggregate_version: int
    plans_by_semantic_digest: Mapping[str, SealedExecutionPlanRecord]
    plans_by_compilation_key: Mapping[str, str]  # compilation_key_digest → plan_semantic_digest
    first_seen_ledger: tuple[FirstSeenSealCommandRecord, ...]

    def first_seen_by_request(self, request_id: str) -> "FirstSeenSealCommandRecord | None":
        for record in self.first_seen_ledger:
            if record.request_id == request_id:
                return record
        return None

    def retained_dependency_refs(self) -> tuple[PlanDependencySet, ...]:
        """Plan 존재 동안 보존되는 append-only dependency 참조 집합(GC 없음)."""
        return tuple(
            self.plans_by_semantic_digest[digest].dependency_set
            for digest in sorted(self.plans_by_semantic_digest)
        )


def empty_aggregate(
    work_authority_id: str, workspace_instance_id: str
) -> WorkExecutionPlanAggregate:
    """durable record 가 아직 없는 Work 의 version 0 empty aggregate(첫 commit 이 version 1 을 낸다)."""
    return WorkExecutionPlanAggregate(
        work_authority_id=_require_str(work_authority_id, "work_authority_id"),
        workspace_instance_id=_require_str(workspace_instance_id, "workspace_instance_id"),
        aggregate_version=0,
        plans_by_semantic_digest={},
        plans_by_compilation_key={},
        first_seen_ledger=(),
    )


def encode_aggregate(aggregate: WorkExecutionPlanAggregate) -> dict[str, Any]:
    """durable envelope content — plans/map 는 정렬 list(저장 순서 ≠ identity), ledger 는 append 순서."""
    return {
        "store_schema_version": PLAN_STORE_SCHEMA_VERSION,
        "work_authority_id": aggregate.work_authority_id,
        "workspace_instance_id": aggregate.workspace_instance_id,
        "aggregate_version": aggregate.aggregate_version,
        "plans": [
            _encode_plan_record(aggregate.plans_by_semantic_digest[digest])
            for digest in sorted(aggregate.plans_by_semantic_digest)
        ],
        "compilation_map": [
            {"key_digest": key_digest, "plan_semantic_digest": plan_digest}
            for key_digest, plan_digest in sorted(
                aggregate.plans_by_compilation_key.items()
            )
        ],
        "first_seen_ledger": [
            _encode_first_seen(record) for record in aggregate.first_seen_ledger
        ],
    }


def decode_aggregate(
    content: Mapping[str, Any], work_authority_id: str
) -> WorkExecutionPlanAggregate:
    """persisted content → aggregate. unknown schema·구조 손상·cross-work 파일은 fail-closed.

    각 plan record 는 content-address 를 재검증하고, compilation map 은 존재하는 plan 만 가리켜야 하며,
    functional dependency(key → 최대 1 plan)를 다시 강제한다(claim 신뢰 금지).
    """
    if content.get("store_schema_version") != PLAN_STORE_SCHEMA_VERSION:
        raise ExecutionPlanStoreIntegrityError(
            f"미지원 plan store schema: {content.get('store_schema_version')!r}"
        )
    stored_work = _require_str(content.get("work_authority_id"), "work_authority_id")
    if stored_work != work_authority_id:
        # 파일이 다른 Work 이름으로 이동/복사되면 digest 는 통과해도 key 결속이 깨진다.
        raise ExecutionPlanStoreIntegrityError(
            f"plan aggregate 파일이 다른 Work({stored_work}) 를 담았다"
        )
    version = content.get("aggregate_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ExecutionPlanStoreIntegrityError("aggregate_version 이 양의 정수가 아니다")

    plans_raw = content.get("plans")
    if not isinstance(plans_raw, list):
        raise ExecutionPlanStoreIntegrityError("plans 가 list 가 아니다")
    plans: dict[str, SealedExecutionPlanRecord] = {}
    for entry in plans_raw:
        record = _decode_plan_record(entry)
        if record.plan_semantic_digest in plans:
            raise ExecutionPlanStoreIntegrityError("plans 에 중복 plan digest")
        plans[record.plan_semantic_digest] = record

    map_raw = content.get("compilation_map")
    if not isinstance(map_raw, list):
        raise ExecutionPlanStoreIntegrityError("compilation_map 이 list 가 아니다")
    compilation_map: dict[str, str] = {}
    for entry in map_raw:
        pair = _require_mapping(entry, "compilation_map entry")
        key_digest = _require_str(pair.get("key_digest"), "key_digest")
        plan_digest = _require_str(pair.get("plan_semantic_digest"), "plan_semantic_digest")
        if key_digest in compilation_map:
            raise ExecutionPlanStoreIntegrityError("compilation_map 에 중복 key")
        if plan_digest not in plans:
            raise ExecutionPlanCompilationIntegrityError(
                "compilation_map 이 없는 plan 을 가리킨다"
            )
        compilation_map[key_digest] = plan_digest

    ledger_raw = content.get("first_seen_ledger")
    if not isinstance(ledger_raw, list):
        raise ExecutionPlanStoreIntegrityError("first_seen_ledger 가 list 가 아니다")
    ledger = tuple(_decode_first_seen(entry) for entry in ledger_raw)
    seen_requests = {record.request_id for record in ledger}
    if len(seen_requests) != len(ledger):
        raise ExecutionPlanStoreIntegrityError("first_seen_ledger 에 중복 request_id")

    return WorkExecutionPlanAggregate(
        work_authority_id=work_authority_id,
        workspace_instance_id=_require_str(
            content.get("workspace_instance_id"), "workspace_instance_id"
        ),
        aggregate_version=version,
        plans_by_semantic_digest=plans,
        plans_by_compilation_key=compilation_map,
        first_seen_ledger=ledger,
    )


# ─── 순수 전이: publish / ledger-only ─────────────────────────────────────────────────
def _require_matching_intent(
    aggregate: WorkExecutionPlanAggregate,
    fingerprint: SealRequestIntentFingerprintPayload,
) -> None:
    if fingerprint.work_authority_id != aggregate.work_authority_id:
        raise ExecutionPlanStoreIntegrityError(
            "fingerprint.work_authority_id 가 aggregate 와 불일치"
        )
    if fingerprint.workspace_instance_id != aggregate.workspace_instance_id:
        # durable workspace identity 는 fence·token 이 쓰는 값이라 재결속 금지.
        raise ExecutionPlanStoreIntegrityError(
            "fingerprint.workspace_instance_id 가 aggregate 와 불일치"
        )


def apply_publish(
    aggregate: WorkExecutionPlanAggregate,
    *,
    request_id: str,
    fingerprint: SealRequestIntentFingerprintPayload,
    resolved_seal_policy: ResolvedSealPolicy,
    capture_evidence: DurableSealCaptureEvidence,
    plan_payload: SealedExecutionPlanSemanticPayload,
    dependency_set: PlanDependencySet,
    published_outcome: PlanPublished,
    now: str,
) -> "tuple[WorkExecutionPlanAggregate, FirstSeenSealCommandRecord]":
    """Plan record create/reuse + compilation mapping + retention + first-seen ledger 를 한 전이로.

    같은 semantic Plan 은 create-once 로 재사용하고, 같은 compilation key 에 다른 payload 가 나타나면
    fail-closed 한다. reuse 요청도 자기 durable capture evidence 로 새 ledger entry 를 남긴다.
    """
    _require_str(request_id, "request_id")
    _require_matching_intent(aggregate, fingerprint)

    # Plan/policy 정합 — plan schema·encoding 은 resolve 된 policy 와 정확히 일치해야 한다.
    if plan_payload.plan_schema_version != resolved_seal_policy.plan_schema_version:
        raise ExecutionPlanIntegrityError("plan schema 가 resolved policy 와 불일치")
    if plan_payload.canonical_encoding_version != resolved_seal_policy.canonical_encoding_version:
        raise ExecutionPlanIntegrityError("canonical encoding 이 resolved policy 와 불일치")
    require_supported_encoding(plan_payload.canonical_encoding_version)
    # nested digest 재계산·bijection·operation order canonicality 전건 검증(claim 신뢰 금지).
    verify_sealed_plan_integrity(
        plan_payload, supported_plan_schemas=(resolved_seal_policy.plan_schema_version,)
    )

    plan_digest = plan_semantic_digest(plan_payload)
    basis_digest = execution_basis_digest(plan_payload.execution_basis)
    encoded_payload = encode_sealed_plan(plan_payload)

    # PlanPublished 는 complete capture evidence 를 요구한다(captured_execution_input_digest 존재).
    input_digest = _complete_input_digest(capture_evidence)
    _verify_capture_evidence_integrity(capture_evidence)

    # published outcome 의 claim 을 저장 사실과 대조(store 는 union invariant·canonical integrity 를 검증).
    if published_outcome.plan_semantic_digest != plan_digest:
        raise ExecutionPlanIntegrityError("PlanPublished.plan_semantic_digest 불일치")
    if published_outcome.execution_basis_digest != basis_digest:
        raise ExecutionPlanIntegrityError("PlanPublished.execution_basis_digest 불일치")
    if published_outcome.captured_execution_input_digest != input_digest:
        raise ExecutionPlanIntegrityError(
            "PlanPublished.captured_execution_input_digest 가 capture evidence 와 불일치"
        )

    existing = aggregate.plans_by_semantic_digest.get(plan_digest)
    new_plans = dict(aggregate.plans_by_semantic_digest)
    if existing is not None:
        # 같은 digest → canonical bytes·dependency set exact equality. 다르면 collision 추측 금지.
        if existing.canonical_payload_bytes != canonical_execution_bytes(encoded_payload):
            raise ExecutionPlanIntegrityError(
                "같은 plan digest 에 다른 canonical payload"
            )
        if existing.dependency_set != dependency_set:
            raise ExecutionPlanIntegrityError(
                "같은 plan digest 에 다른 dependency set"
            )
        determined_kind = _REUSED
        # 기존 record(최초 봉인 provenance)를 그대로 보존한다 — overwrite 없음.
    else:
        determined_kind = _CREATED
        new_plans[plan_digest] = SealedExecutionPlanRecord(
            plan_semantic_digest=plan_digest,
            semantic_payload_encoded=encoded_payload,
            dependency_set=dependency_set,
            first_sealed_provenance=PlanFirstSealedProvenance(
                first_sealed_at=now,
                first_sealed_by_request_id=request_id,
            ),
        )
    if published_outcome.publication_kind != determined_kind:
        raise ExecutionPlanIntegrityError(
            f"publication_kind({published_outcome.publication_kind}) 가 실제({determined_kind})와 불일치"
        )

    # compilation mapping — key → 최대 1 plan digest(functional dependency).
    key_digest = plan_compilation_key_digest(plan_compilation_key_of(plan_payload))
    prior_mapped = aggregate.plans_by_compilation_key.get(key_digest)
    if prior_mapped is not None and prior_mapped != plan_digest:
        raise ExecutionPlanCompilationIntegrityError(
            f"PlanCompilationKey 가 다른 plan digest 로 매핑됨: {prior_mapped} != {plan_digest}"
        )
    new_map = dict(aggregate.plans_by_compilation_key)
    new_map[key_digest] = plan_digest

    record = _build_first_seen(
        request_id=request_id,
        fingerprint=fingerprint,
        resolved_seal_policy=resolved_seal_policy,
        capture_evidence=capture_evidence,
        terminal_outcome=published_outcome,
        now=now,
    )
    new_aggregate = WorkExecutionPlanAggregate(
        work_authority_id=aggregate.work_authority_id,
        workspace_instance_id=aggregate.workspace_instance_id,
        aggregate_version=aggregate.aggregate_version + 1,
        plans_by_semantic_digest=new_plans,
        plans_by_compilation_key=new_map,
        first_seen_ledger=(*aggregate.first_seen_ledger, record),
    )
    return new_aggregate, record


def apply_ledger_only(
    aggregate: WorkExecutionPlanAggregate,
    *,
    request_id: str,
    fingerprint: SealRequestIntentFingerprintPayload,
    resolved_seal_policy: ResolvedSealPolicy,
    capture_evidence: DurableSealCaptureEvidence,
    terminal_outcome: SealTerminalOutcome,
    now: str,
) -> "tuple[WorkExecutionPlanAggregate, FirstSeenSealCommandRecord]":
    """BLOCKED/POLICY_BLOCKED/STALE terminal 을 Plan write 0 으로 ledger 에만 commit 한다."""
    _require_str(request_id, "request_id")
    _require_matching_intent(aggregate, fingerprint)
    if isinstance(terminal_outcome, PlanPublished):
        raise ExecutionPlanStoreError(
            "ledger-only commit 은 PlanPublished 를 받지 않는다(publish primitive 사용)"
        )
    _verify_capture_evidence_integrity(capture_evidence)
    record = _build_first_seen(
        request_id=request_id,
        fingerprint=fingerprint,
        resolved_seal_policy=resolved_seal_policy,
        capture_evidence=capture_evidence,
        terminal_outcome=terminal_outcome,
        now=now,
    )
    new_aggregate = WorkExecutionPlanAggregate(
        work_authority_id=aggregate.work_authority_id,
        workspace_instance_id=aggregate.workspace_instance_id,
        aggregate_version=aggregate.aggregate_version + 1,
        plans_by_semantic_digest=aggregate.plans_by_semantic_digest,
        plans_by_compilation_key=aggregate.plans_by_compilation_key,
        first_seen_ledger=(*aggregate.first_seen_ledger, record),
    )
    return new_aggregate, record


def _build_first_seen(
    *,
    request_id: str,
    fingerprint: SealRequestIntentFingerprintPayload,
    resolved_seal_policy: ResolvedSealPolicy,
    capture_evidence: DurableSealCaptureEvidence,
    terminal_outcome: SealTerminalOutcome,
    now: str,
) -> FirstSeenSealCommandRecord:
    return FirstSeenSealCommandRecord(
        request_id=request_id,
        request_intent_fingerprint=fingerprint,
        request_intent_fingerprint_digest=request_intent_fingerprint_digest(fingerprint),
        resolved_seal_policy=resolved_seal_policy,
        durable_capture_evidence=capture_evidence,
        terminal_outcome=terminal_outcome,
        first_completed_at=_require_str(now, "first_completed_at"),
    )


def _complete_input_digest(evidence: DurableSealCaptureEvidence) -> str:
    if not isinstance(evidence, CompleteSealCaptureEvidence):
        raise ExecutionPlanIntegrityError(
            "PlanPublished 는 complete capture evidence 를 요구한다"
        )
    return evidence.captured_execution_input_digest


def _verify_capture_evidence_integrity(evidence: DurableSealCaptureEvidence) -> None:
    # encode 는 semantic projection 에서 digest 를 재계산·대조한다 — tamper 를 시끄럽게 닫는다.
    encode_durable_capture_evidence(evidence)
