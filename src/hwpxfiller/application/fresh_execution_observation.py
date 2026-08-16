"""fresh execution observation 순수 판정 — currentness·admission·readiness (S5-11 · #707).

historical seal outcome(ledger 의 immutable first-seen 결과)과 **분리된** 축이다: 이 모듈은
지금 이 순간의 current Work/Profile/runtime 관계를 recompute 하는 순수 판정만 소유한다. 저장·fence·
wall-clock 을 모른다 — exact fact 를 이미 읽어 온 :mod:`hwpxfiller.webapp.seal_execution_plan_product`
가 그 값을 넘겨 여기서 상태를 파생시킨다.

세 축:

- **semantic currentness** — Plan.execution_basis_digest == CurrentWork.execution_basis_digest 여부.
  current_plan pointer·latest Plan·Template revision·Configuration version·UI dirty flag 로 판정하지
  않는다. current basis 가 domain 상 sealable 하지 않으면 STALE(CURRENT_BASIS_NOT_SEALABLE).
- **runtime-policy admission** — 현재 authoritative facts(Profile admission·base kind·runtime
  materializer conformance·plan schema/encoding runtime support)로 ADMITTED/NOT_ADMITTED/CONTEXT_ERROR.
  unknown support 를 admitted 로 fallback 하지 않는다. Plan semantic identity 에는 넣지 않는다.
- **materialization readiness** — READY iff currentness==CURRENT and admission==ADMITTED. 그 외 NOT_READY.

S6 미출하 상태에서 materializer conformance 는 admit 하지 않으므로 합법적 S5 종료 상태는
CURRENT + NOT_ADMITTED(MATERIALIZATION_CONTRACT_NOT_ADMITTED) + NOT_READY 다 — Plan seal 성공을
generation readiness 로 과장하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ─── semantic currentness ────────────────────────────────────────────────────────────
CURRENT = "CURRENT"
STALE = "STALE"
CURRENTNESS_CONTEXT_ERROR = "CONTEXT_ERROR"

# currentness reason(canonical equality 를 훼손하지 않는 display/diagnostic projection).
DIGEST_MISMATCH = "DIGEST_MISMATCH"
CURRENT_BASIS_NOT_SEALABLE = "CURRENT_BASIS_NOT_SEALABLE"
TEMPLATE_APPLICATION_CHANGED = "TEMPLATE_APPLICATION_CHANGED"

# ─── runtime-policy admission ────────────────────────────────────────────────────────
ADMITTED = "ADMITTED"
NOT_ADMITTED = "NOT_ADMITTED"
ADMISSION_CONTEXT_ERROR = "CONTEXT_ERROR"

QUALIFICATION_PROFILE_REVOKED = "QUALIFICATION_PROFILE_REVOKED"
QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING = (
    "QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING"
)
EXECUTION_BASE_NOT_ADMITTED = "EXECUTION_BASE_NOT_ADMITTED"
MATERIALIZATION_CONTRACT_NOT_ADMITTED = "MATERIALIZATION_CONTRACT_NOT_ADMITTED"
PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME = "PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME"
CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME = "CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME"
RUNTIME_CAPABILITY_CONTEXT_ERROR = "RUNTIME_CAPABILITY_CONTEXT_ERROR"

# ─── materialization readiness ───────────────────────────────────────────────────────
READY = "READY"
NOT_READY = "NOT_READY"

# ─── current Work sealability(비-published outcome 용) ─────────────────────────────────
SEALABLE = "SEALABLE"
DOMAIN_BLOCKED = "DOMAIN_BLOCKED"
POLICY_BLOCKED = "POLICY_BLOCKED"
SEALABILITY_CONTEXT_ERROR = "CONTEXT_ERROR"

# runtime materializer conformance verdict 어휘(S6 가 admit 을 구현, S5 는 NOT_ADMITTED).
MATERIALIZER_ADMITTED = "ADMITTED"
MATERIALIZER_NOT_ADMITTED = "NOT_ADMITTED"
MATERIALIZER_CONTEXT_ERROR = "CONTEXT_ERROR"


@dataclass(frozen=True)
class RuntimeAdmissionFacts:
    """admission 판정이 소비하는 현재 authoritative facts(Plan semantic identity 와 무관)."""

    profile_admission_state: str | None  # ADMITTED | REVOKED | None(state missing)
    execution_base_kind_admitted: bool
    plan_schema_supported_by_runtime: bool
    canonical_encoding_supported_by_runtime: bool
    materializer_conformance: str  # MATERIALIZER_ADMITTED | _NOT_ADMITTED | _CONTEXT_ERROR


@dataclass(frozen=True)
class RuntimePolicyAdmission:
    state: str  # ADMITTED | NOT_ADMITTED | CONTEXT_ERROR
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticCurrentness:
    state: str  # CURRENT | STALE | CONTEXT_ERROR
    reason: str | None = None


@dataclass(frozen=True)
class PublishedPlanObservation:
    """historical PlanPublished 에 대한 fresh 관찰 — 그 Plan 의 현재 currentness·admission·readiness."""

    opaque_plan_ref: str
    semantic_currentness: SemanticCurrentness
    runtime_policy_admission: RuntimePolicyAdmission
    materialization_readiness: str  # READY | NOT_READY
    observed_at: str
    observed_execution_basis_digest: str | None = None
    observed_runtime_capability_manifest_digest: str | None = None


@dataclass(frozen=True)
class CurrentWorkExecutionObservation:
    """Plan 이 만들어지지 않은 outcome 에 대해 current Work 가 지금 무엇을 고쳐야 하는지 관찰.

    new command outcome 이 아니며 ledger 에 저장하지 않는다. fresh observation 실패가 historical
    outcome 을 소거하지 않는다.
    """

    work_authority_ref: str
    current_sealability: str  # SEALABLE | DOMAIN_BLOCKED | POLICY_BLOCKED | CONTEXT_ERROR
    observed_at: str
    current_template_application_ref: str | None = None
    normalized_blockers_or_policy: tuple[str, ...] = field(default_factory=tuple)
    observed_execution_basis_digest: str | None = None


@dataclass(frozen=True)
class ExecutionObservationContextError:
    """fresh observation 자체가 실패했을 때 — historical outcome 은 보존되고 이 축만 context error."""

    code: str
    detail: str


FreshExecutionObservation = (
    PublishedPlanObservation
    | CurrentWorkExecutionObservation
    | ExecutionObservationContextError
)


def decide_runtime_policy_admission(
    facts: RuntimeAdmissionFacts,
) -> RuntimePolicyAdmission:
    """현재 facts → admission. unknown support 를 admitted 로 fallback 하지 않는다(fail-closed).

    precedence: context error(state missing·runtime capability context error)가 우선한다 —
    determinable 하지 않으면 NOT_ADMITTED 로 단정하지 않고 CONTEXT_ERROR 로 시끄럽게 닫는다.
    그 외에는 모든 not-admitted 사유를 누적한다.
    """
    context_reasons: list[str] = []
    if facts.profile_admission_state is None:
        context_reasons.append(QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING)
    if facts.materializer_conformance == MATERIALIZER_CONTEXT_ERROR:
        context_reasons.append(RUNTIME_CAPABILITY_CONTEXT_ERROR)
    if context_reasons:
        return RuntimePolicyAdmission(ADMISSION_CONTEXT_ERROR, tuple(context_reasons))

    reasons: list[str] = []
    if facts.profile_admission_state == "REVOKED":
        reasons.append(QUALIFICATION_PROFILE_REVOKED)
    if not facts.execution_base_kind_admitted:
        reasons.append(EXECUTION_BASE_NOT_ADMITTED)
    if not facts.plan_schema_supported_by_runtime:
        reasons.append(PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME)
    if not facts.canonical_encoding_supported_by_runtime:
        reasons.append(CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME)
    if facts.materializer_conformance != MATERIALIZER_ADMITTED:
        reasons.append(MATERIALIZATION_CONTRACT_NOT_ADMITTED)
    if reasons:
        return RuntimePolicyAdmission(NOT_ADMITTED, tuple(reasons))
    return RuntimePolicyAdmission(ADMITTED)


def decide_materialization_readiness(
    currentness: SemanticCurrentness, admission: RuntimePolicyAdmission
) -> str:
    """READY iff CURRENT and ADMITTED — 그 외 NOT_READY(S6 미출하 상태를 READY 로 과장하지 않는다)."""
    if currentness.state == CURRENT and admission.state == ADMITTED:
        return READY
    return NOT_READY
