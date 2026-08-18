"""content-addressed Plan aggregate value model·codec·전이(S5-07 · #703).

S5-06(:mod:`.execution_contract_set`)이 Plan identity(``plan_semantic_digest``)·
``PlanCompilationKey``·``DurableSealCaptureEvidence`` 를 이미 소유한다. 이 모듈은 그 위에
**durable Work aggregate** 의 값 모델과 순수 전이를 얹는다:

- ``SealedExecutionPlanRecord`` — content-address(``plan_semantic_digest``)로 주소화하는
  create-once Plan record. random/current/latest/superseded pointer 를 만들지 않는다.
- ``plans_by_compilation_key`` — ``PlanCompilationKey → plan_semantic_digest`` functional
  dependency(같은 key 에 다른 payload = loud integrity error, 조용한 overwrite 금지).
- Plan dependency set(append-only retention refs) — upstream object 를 GC 하지 않고 참조만 보존.

파일 I/O·lease·CAS·atomic replace 는 :mod:`hwpxfiller.external.work_execution_plan_store` 소유다.
이 모듈은 **순수** 하다: 저장소·HWPX·native 를 import 하지 않고, 전이는 새 frozen aggregate 를 낸다.

fail-closed: unknown schema/encoding·digest 불일치·compilation 충돌은 latest 로 풀지 않고
시끄럽게 닫는다. R2-04a(#740): first-seen request ledger·replay·idempotency 를 제거했다 —
같은 request 재호출은 historical outcome 을 replay 하지 않고 현재 authority 에서 재계산한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any

from hwpxfiller.application.execution_capture import ResolvedSealPolicy
from hwpxfiller.application.execution_contract_set import (
    PLAN_APPLY_FIELD_BINDING,
    PLAN_REMOVE_OPTION,
    CompleteSealCaptureEvidence,
    DurableSealCaptureEvidence,
    ExecutionPlanCompilationIntegrityError,
    ExecutionPlanIntegrityError,
    PlanCompilationKey,
    SealedExecutionPlanSemanticPayload,
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




def _require_mapping(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionPlanStoreIntegrityError(f"{what} 는 매핑이어야 한다")
    return value


def _freeze(value: Any) -> Any:
    """JSON-safe 값을 재귀적으로 동결한다(Mapping→MappingProxyType, sequence→tuple).

    봉인 뒤 소비자가 payload 를 고쳐 content-address 와 어긋나게 하지 못하게 한다.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
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

    def __post_init__(self) -> None:
        # 저장 payload 를 재귀 동결 — 봉인 뒤 소비자 변이로 content-address 와 어긋나지 못하게 한다.
        object.__setattr__(
            self, "semantic_payload_encoded", _freeze(self.semantic_payload_encoded)
        )

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


def _encoded_field_id(entry: object, what: str) -> str:
    m = _require_mapping(entry, what)
    value = m.get("field_id")
    if not isinstance(value, str) or value == "":
        raise ExecutionPlanIntegrityError(f"{what} 에 field_id 가 없다")
    return value


def _verify_encoded_operation_structure(reqs: list, ops: list) -> None:
    """requirement↔APPLY bijection(순서 포함)·REMOVE-before-APPLY·operand·op code 를 강제한다.

    S5-06 :func:`verify_sealed_plan_integrity` 의 구조 규칙을 stored bytes 위에서 재현한다.
    """
    req_fields = [_encoded_field_id(r, "active field requirement") for r in reqs]
    apply_fields = [
        _encoded_field_id(o, "APPLY_FIELD_BINDING operation")
        for o in ops
        if isinstance(o, Mapping) and o.get("op") == PLAN_APPLY_FIELD_BINDING
    ]
    if len(set(req_fields)) != len(req_fields):
        raise ExecutionPlanIntegrityError("active field requirement field 중복")
    if len(set(apply_fields)) != len(apply_fields):
        raise ExecutionPlanIntegrityError("APPLY_FIELD_BINDING field 중복")
    if req_fields != apply_fields:
        raise ExecutionPlanIntegrityError("requirement ↔ APPLY_FIELD_BINDING 순서/집합 불일치")
    seen_apply = False
    for op in ops:
        m = _require_mapping(op, "operation")
        code = m.get("op")
        if code == PLAN_APPLY_FIELD_BINDING:
            seen_apply = True
        elif code == PLAN_REMOVE_OPTION:
            if seen_apply:
                raise ExecutionPlanIntegrityError(
                    "operation order 비canonical: REMOVE_OPTION 이 APPLY_FIELD_BINDING 뒤에 온다"
                )
            for name in ("slot_id", "option_id"):
                v = m.get(name)
                if not isinstance(v, str) or v == "":
                    raise ExecutionPlanIntegrityError(f"REMOVE_OPTION 에 {name} 가 없다/비어 있다")
        else:
            raise ExecutionPlanIntegrityError(f"미지원 operation code: {code!r}")


def verify_encoded_plan_integrity(encoded: Mapping[str, Any]) -> None:
    """load trust 경계: stored plan payload 를 구조까지 재검증한다(hash 일치 = 유효 Plan 아님).

    확인: plan schema nonempty·canonical encoding closure·nested execution_basis_digest 자기정합·
    requirement↔operation bijection·operation order canonicality. rule/value_expression 은 S5-06
    semantic 인코딩에서 제외돼 stored bytes 에 없으므로 여기서 재검증 대상이 아니다 —
    active_binding_digest 재계산은 full object 를 가진 publish 시점(:func:`verify_sealed_plan_integrity`)이
    이미 진다.
    """
    # ponytail: rules 는 S5-06 semantic encoding 이 제외 → load 에서 active_binding_digest 재계산 불가.
    #           그 검증은 publish 시점의 full-object verify_sealed_plan_integrity 가 소유한다.
    _require_str(encoded.get("plan_schema_version"), "plan_schema_version")
    require_supported_encoding(
        _require_str(encoded.get("canonical_encoding_version"), "canonical_encoding_version")
    )
    basis = _require_mapping(encoded.get("execution_basis"), "execution_basis")
    declared_basis_digest = _require_str(
        encoded.get("execution_basis_digest"), "execution_basis_digest"
    )
    if canonical_execution_digest(basis) != declared_basis_digest:
        raise ExecutionPlanIntegrityError(
            "stored execution_basis_digest 가 basis 재계산과 불일치"
        )
    reqs = encoded.get("active_field_requirements")
    ops = encoded.get("ordered_operations")
    # freeze 경로는 tuple, JSON 복원 경로는 list — 둘 다 받는다(문자열은 배제).
    if not isinstance(reqs, (list, tuple)) or not isinstance(ops, (list, tuple)):
        raise ExecutionPlanIntegrityError("plan requirement/operation 형식 불량")
    _verify_encoded_operation_structure(list(reqs), list(ops))


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
    verify_encoded_plan_integrity(record.semantic_payload_encoded)
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


# ─── WorkExecutionPlanAggregate ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class WorkExecutionPlanAggregate:
    """Work(``work_authority_id``) 단위 durable aggregate — current/latest pointer 를 담지 않는다.

    currentness 는 저장하지 않는다: Work 의 현재 basis 와의 equality 로 파생한다. R2-04a(#740):
    first-seen request ledger 를 담지 않는다 — 같은 request 재호출은 historical outcome 을 replay
    하지 않고 현재 authority 에서 재계산한다(content-addressed Plan history 만 남는다, 04b 대상).
    """

    work_authority_id: str
    workspace_instance_id: str
    aggregate_version: int
    plans_by_semantic_digest: Mapping[str, SealedExecutionPlanRecord]
    plans_by_compilation_key: Mapping[str, str]  # compilation_key_digest → plan_semantic_digest

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
    workspace_instance_id = _require_str(
        content.get("workspace_instance_id"), "workspace_instance_id"
    )

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
        # P2-7: map key 가 실제로 그 plan 의 basis/schema/encoding 에서 파생한 key 인지 재계산해 확인한다.
        if _recompute_plan_compilation_key_digest(plans[plan_digest]) != key_digest:
            raise ExecutionPlanCompilationIntegrityError(
                "compilation_map key 가 참조 plan 의 재계산 compilation key 와 불일치"
            )
        compilation_map[key_digest] = plan_digest

    return WorkExecutionPlanAggregate(
        work_authority_id=work_authority_id,
        workspace_instance_id=workspace_instance_id,
        aggregate_version=version,
        plans_by_semantic_digest=plans,
        plans_by_compilation_key=compilation_map,
    )


def _recompute_plan_compilation_key_digest(record: SealedExecutionPlanRecord) -> str:
    encoded = record.semantic_payload_encoded
    return plan_compilation_key_digest(
        PlanCompilationKey(
            execution_basis_digest=_require_str(
                encoded.get("execution_basis_digest"), "execution_basis_digest"
            ),
            plan_schema_version=_require_str(
                encoded.get("plan_schema_version"), "plan_schema_version"
            ),
            canonical_encoding_version=_require_str(
                encoded.get("canonical_encoding_version"), "canonical_encoding_version"
            ),
        )
    )


# ─── 순수 전이: publish ─────────────────────────────────────────────────────────────────


# policy 가 소유하는 contract identity → plan ExecutionContractSet 의 대응 field(둘이 일치해야 한다).
# slot_selection/field_binding/source_schema 는 S4 Selection·FieldBinding 소유라 policy 가 안 정한다.
_POLICY_CONTRACT_FIELDS = (
    "execution_semantic_contract_id",
    "binding_value_contract_id",
    "raw_record_contract_id",
    "document_value_resolution_contract_id",
    "record_validation_contract_id",
    "record_review_contract_id",
    "composition_contract_id",
    "native_primitive_contract_id",
    "materialization_base_contract_id",
    "composition_theorem_evidence_manifest_digest",
    "materialization_contract_id",
)


def _verify_plan_basis_matches_context(
    aggregate: WorkExecutionPlanAggregate,
    plan_payload: SealedExecutionPlanSemanticPayload,
    resolved_seal_policy: ResolvedSealPolicy,
) -> None:
    """plan 의 execution basis 를 aggregate identity·resolved policy 에 교차 결속한다(fail-closed).

    - basis 의 work/workspace identity 가 이 aggregate 의 것이어야 한다(다른 Work 의 Plan 을 이 파일에
      저장하지 못하게 한다).
    - policy 가 소유하는 모든 contract identity·execution_base_kind 가 plan basis 와 정확히 일치해야
      한다(그 plan 을 만들지 않은 policy 를 durable 하게 기록하지 못하게 한다).
    """
    basis = plan_payload.execution_basis
    if basis.work_authority_id != aggregate.work_authority_id:
        raise ExecutionPlanIntegrityError(
            "plan basis 의 work_authority_id 가 aggregate 와 불일치(cross-Work Plan)"
        )
    if basis.workspace_instance_id != aggregate.workspace_instance_id:
        raise ExecutionPlanIntegrityError(
            "plan basis 의 workspace_instance_id 가 aggregate 와 불일치"
        )
    if resolved_seal_policy.execution_base_kind != basis.template.execution_base_kind:
        raise ExecutionPlanIntegrityError(
            "resolved policy 의 execution_base_kind 가 plan basis template 과 불일치"
        )
    for name in _POLICY_CONTRACT_FIELDS:
        if getattr(resolved_seal_policy, name) != getattr(basis.contracts, name):
            raise ExecutionPlanIntegrityError(
                f"resolved policy 의 {name} 가 plan basis contract set 과 불일치"
            )


def apply_publish(
    aggregate: WorkExecutionPlanAggregate,
    *,
    request_id: str,
    resolved_seal_policy: ResolvedSealPolicy,
    capture_evidence: DurableSealCaptureEvidence,
    plan_payload: SealedExecutionPlanSemanticPayload,
    dependency_set: PlanDependencySet,
    published_outcome: PlanPublished,
    now: str,
) -> WorkExecutionPlanAggregate:
    """Plan record create/reuse + compilation mapping + dependency retention 을 한 전이로(R2-04a).

    같은 semantic Plan 은 create-once 로 재사용하고, 같은 compilation key 에 다른 payload 가 나타나면
    fail-closed 한다. first-seen ledger 는 더 이상 남기지 않는다(replay 없음) — REUSE 는 aggregate 를
    **무변경**으로 되돌리고(version bump 없음, store 는 write 를 생략한다), CREATE 만 version 을 올린다.
    ``request_id``·``now`` 는 plan record 의 first-sealed provenance 로만 쓴다(idempotency authority 아님).
    """
    _require_str(request_id, "request_id")

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
    # basis identity·policy-owned contract 를 aggregate·policy 에 교차 결속(cross-Work·contradictory policy 차단).
    _verify_plan_basis_matches_context(aggregate, plan_payload, resolved_seal_policy)

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

    # compilation mapping key(functional dependency) — REUSE/CREATE 공통으로 재계산한다.
    key_digest = plan_compilation_key_digest(plan_compilation_key_of(plan_payload))
    prior_mapped = aggregate.plans_by_compilation_key.get(key_digest)
    if prior_mapped is not None and prior_mapped != plan_digest:
        raise ExecutionPlanCompilationIntegrityError(
            f"PlanCompilationKey 가 다른 plan digest 로 매핑됨: {prior_mapped} != {plan_digest}"
        )

    existing = aggregate.plans_by_semantic_digest.get(plan_digest)
    if existing is not None:
        # 같은 digest → canonical bytes·dependency set exact equality. 다르면 collision 추측 금지.
        if existing.canonical_payload_bytes != canonical_execution_bytes(encoded_payload):
            raise ExecutionPlanIntegrityError("같은 plan digest 에 다른 canonical payload")
        if existing.dependency_set != dependency_set:
            raise ExecutionPlanIntegrityError("같은 plan digest 에 다른 dependency set")
        if published_outcome.publication_kind != _REUSED:
            raise ExecutionPlanIntegrityError(
                f"publication_kind({published_outcome.publication_kind}) 가 실제(REUSED)와 불일치"
            )
        # REUSE: plan record·compilation map 이 이미 있다 → aggregate 무변경(version bump 없음).
        return aggregate

    if published_outcome.publication_kind != _CREATED:
        raise ExecutionPlanIntegrityError(
            f"publication_kind({published_outcome.publication_kind}) 가 실제(CREATED)와 불일치"
        )
    new_plans = dict(aggregate.plans_by_semantic_digest)
    new_plans[plan_digest] = SealedExecutionPlanRecord(
        plan_semantic_digest=plan_digest,
        semantic_payload_encoded=encoded_payload,
        dependency_set=dependency_set,
        first_sealed_provenance=PlanFirstSealedProvenance(
            first_sealed_at=now,
            first_sealed_by_request_id=request_id,
        ),
    )
    new_map = dict(aggregate.plans_by_compilation_key)
    new_map[key_digest] = plan_digest
    return WorkExecutionPlanAggregate(
        work_authority_id=aggregate.work_authority_id,
        workspace_instance_id=aggregate.workspace_instance_id,
        aggregate_version=aggregate.aggregate_version + 1,
        plans_by_semantic_digest=new_plans,
        plans_by_compilation_key=new_map,
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
