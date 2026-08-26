"""fresh execution observation 순수 판정 — current Sealed Plan value·admission·readiness (S5-11 · #707).

지금 이 순간의 current Work/Profile/runtime 관계를 recompute 하는 순수 판정만 소유한다. 저장·fence·
wall-clock 을 모른다 — exact fact 를 이미 읽어 온 :mod:`hwpxfiller.webapp.seal_execution_plan_product`
가 그 값을 넘겨 여기서 상태를 파생시킨다.

**S5F R2-04b-1(#740):** historical durable Plan lookup + digest-vs-stored currentness(CURRENT/STALE)
축을 제거했다. observation 은 이제 store 에 저장된 과거 Plan 과 대조하지 않고 **current SealedExecutionPlanValue**
를 직접 계산해 그 위에 runtime admission·readiness 를 얹는다. opaque Plan ref·PublishedPlanObservation·
SemanticCurrentness 는 사라졌다 — value 가 곧 현재이므로 currentness 는 자명하다.

두 축:

- **runtime-policy admission** — 현재 authoritative facts(Profile admission·base kind·runtime
  materializer conformance·plan schema/encoding runtime support)로 ADMITTED/NOT_ADMITTED/CONTEXT_ERROR.
  unknown support 를 admitted 로 fallback 하지 않는다. Plan semantic identity 에는 넣지 않는다.
- **materialization readiness** — READY iff admission==ADMITTED. 그 외 NOT_READY. current value 는
  방금 계산됐으므로 currentness 는 자명하다 — readiness 는 admission 만으로 갈린다.

S6 미출하 상태에서 materializer conformance 는 admit 하지 않으므로 합법적 S5 종료 상태는
current sealable + NOT_ADMITTED(MATERIALIZATION_CONTRACT_NOT_ADMITTED) + NOT_READY 다 — Plan seal 성공을
generation readiness 로 과장하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hwpxfiller.application.execution_semantic_kernel import SealedExecutionPlanValue
from hwpxfiller.application.field_binding_input import FieldBindingInput

# ─── runtime-policy admission ────────────────────────────────────────────────────────
ADMITTED = "ADMITTED"
NOT_ADMITTED = "NOT_ADMITTED"
ADMISSION_CONTEXT_ERROR = "CONTEXT_ERROR"

EXECUTION_BASE_NOT_ADMITTED = "EXECUTION_BASE_NOT_ADMITTED"
MATERIALIZATION_CONTRACT_NOT_ADMITTED = "MATERIALIZATION_CONTRACT_NOT_ADMITTED"
#: 아직 확인하지 않았다 — runtime/policy 가 거절한 것이 **아니라** 판정 재료가 없다(#912 D1).
#: :func:`decide_runtime_policy_admission` 은 이 사유를 내지 않는다: facts 를 받은 판정은 언제나
#: 실제 축으로 답한다. 이 사유는 판정 자체가 아직 돌지 않은 자리(fresh observation 부재·seal 불가)
#: 를 정직하게 NOT_ADMITTED 로 닫는 어휘이고, 그래서 runtime/policy 거절 문안을 끌어오지 않는다.
EXECUTION_EVIDENCE_NOT_OBSERVED = "EXECUTION_EVIDENCE_NOT_OBSERVED"
PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME = "PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME"
CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME = "CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME"
RUNTIME_CAPABILITY_CONTEXT_ERROR = "RUNTIME_CAPABILITY_CONTEXT_ERROR"

# ─── materialization readiness ───────────────────────────────────────────────────────
READY = "READY"
NOT_READY = "NOT_READY"

# ─── current Work sealability(seal 불가 outcome 용) ────────────────────────────────────
DOMAIN_BLOCKED = "DOMAIN_BLOCKED"
POLICY_BLOCKED = "POLICY_BLOCKED"
SEALABILITY_CONTEXT_ERROR = "CONTEXT_ERROR"

# runtime materializer conformance verdict 어휘(S6 가 admit 을 구현, S5 는 NOT_ADMITTED).
MATERIALIZER_ADMITTED = "ADMITTED"
MATERIALIZER_NOT_ADMITTED = "NOT_ADMITTED"
MATERIALIZER_CONTEXT_ERROR = "CONTEXT_ERROR"


@dataclass(frozen=True)
class RuntimeAdmissionFacts:
    """admission 판정이 소비하는 현재 authoritative facts(Plan semantic identity 와 무관).

    S5F R2-05a(#740): mutable Profile admission(ADMITTED/REVOKED) 축을 제거했다 — runtime admission 은
    base kind·plan schema/encoding runtime support·materializer conformance capability 만 본다.
    """

    execution_base_kind_admitted: bool
    plan_schema_supported_by_runtime: bool
    canonical_encoding_supported_by_runtime: bool
    materializer_conformance: str  # MATERIALIZER_ADMITTED | _NOT_ADMITTED | _CONTEXT_ERROR


@dataclass(frozen=True)
class RuntimePolicyAdmission:
    state: str  # ADMITTED | NOT_ADMITTED | CONTEXT_ERROR
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrentSealedPlanObservation:
    """current sealable Work 의 관찰 — 지금 계산한 SealedExecutionPlanValue + admission + readiness.

    historical durable Plan 을 조회·대조하지 않는다(R2-04b-1). value 는 방금 current authority 에서
    재계산됐으므로 currentness 축이 없다 — readiness 는 admission 만으로 갈린다.
    """

    sealed_plan_value: SealedExecutionPlanValue
    runtime_policy_admission: RuntimePolicyAdmission
    materialization_readiness: str  # READY | NOT_READY
    observed_at: str
    # 같은 current capture 에서 온 exact binding facts. delivery-only inactive token 해석에
    # 소비되며 Plan identity·durable state 가 아니다.
    current_field_binding: FieldBindingInput | None = None


@dataclass(frozen=True)
class CurrentWorkExecutionObservation:
    """current Work 가 seal 불가일 때(blocked/policy/context) 지금 무엇을 고쳐야 하는지 관찰.

    new command outcome 이 아니며 durable 하게 저장하지 않는다. fresh observation 실패가 command
    outcome 을 소거하지 않는다.
    """

    work_authority_ref: str
    current_sealability: str  # DOMAIN_BLOCKED | POLICY_BLOCKED | CONTEXT_ERROR
    observed_at: str
    current_template_application_ref: str | None = None
    normalized_blockers_or_policy: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExecutionObservationContextError:
    """fresh observation 자체가 실패했을 때 — command outcome 은 보존되고 이 축만 context error."""

    code: str
    detail: str


FreshExecutionObservation = (
    CurrentSealedPlanObservation
    | CurrentWorkExecutionObservation
    | ExecutionObservationContextError
)


def decide_runtime_policy_admission(
    facts: RuntimeAdmissionFacts,
) -> RuntimePolicyAdmission:
    """현재 facts → admission. unknown support 를 admitted 로 fallback 하지 않는다(fail-closed).

    precedence: context error(runtime capability context error)가 우선한다 — determinable 하지
    않으면 NOT_ADMITTED 로 단정하지 않고 CONTEXT_ERROR 로 시끄럽게 닫는다. 그 외에는 모든
    not-admitted 사유를 누적한다.
    """
    if facts.materializer_conformance == MATERIALIZER_CONTEXT_ERROR:
        return RuntimePolicyAdmission(
            ADMISSION_CONTEXT_ERROR, (RUNTIME_CAPABILITY_CONTEXT_ERROR,)
        )

    reasons: list[str] = []
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


def decide_materialization_readiness(admission: RuntimePolicyAdmission) -> str:
    """READY iff ADMITTED — current value 는 자명히 현재이므로 admission 만으로 갈린다.

    S6 미출하 상태를 READY 로 과장하지 않는다(admission 이 NOT_ADMITTED 로 닫는다).
    """
    return READY if admission.state == ADMITTED else NOT_READY
