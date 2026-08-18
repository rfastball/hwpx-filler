"""SealExecutionPlan Product API — command outcome + current Sealed Plan observation (S5-11 · #707).

두 질의를 나란히 노출한다:

- ``command_outcome`` — 방금 계산한 terminal seal outcome(PlanPublished/blocked/policy/stale). S5-10
  application service(:func:`seal_execution_plan`)가 현재 authority 에서 재계산한다.
- ``fresh_observation`` — 지금 이 순간 current Work 의 **SealedExecutionPlanValue** 재계산(sealable 이면
  그 value + runtime admission + readiness, 아니면 current-work blocker). historical durable Plan 을
  조회·대조하지 않는다.

**S5F R2-04b-1(#740):** historical durable Plan lookup + opaque Plan ref/HMAC + resolve_plan_reference +
PublishedPlanObservation + digest-vs-stored currentness(CURRENT/STALE) + command_replayed 를 제거했다.
observation 은 store 의 과거 Plan 이 아니라 current authority 에서 SealedExecutionPlanValue 를 직접
계산한다(value 가 곧 현재라 currentness 축이 없다). command_outcome 의 StaleExecutionBasis(capture→
final gate concurrency)와 ProfileFence·runtime admission 은 유지한다. content-addressed Plan store 로의
publish(create/reuse)는 orchestration 이 아직 진다 — 그 제거는 04b-2 대상이다.

**additive 경계**: 이 Product service 는 headless(pywebview 비의존)이고 production Generate route 를
cut over 하거나 native materialization 을 시작하지 않는다(S6 소유). action registry·bridge·frontend
generated types 배선은 downstream wiring slice(S5-13) 소유다. capture port·shipping policy resolver·
fresh observation summary·admission-state read 는 injectable seam 이라 실 store/HWPX 결선은 downstream 이
주입한다(#706 과 동일). admission-state read 는 Product 가 보유한 ProfileFence 아래에서 호출되며,
downstream 은 ``read_qualification_profile_admission_under_fence`` 로 배선한다(under-fence helper 를
직접 참조하지 않아 per-Work fence 우회 게이트를 지킨다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    CapturedExecutionDomainBlock,
    CapturedExecutionInput,
    CapturedExecutionPolicyBlock,
    ExecutionCaptureContextError,
    ResolvedSealPolicy,
)
from ..application.execution_composition import (
    DEFAULT_THEOREM_EVIDENCE_REGISTRY,
    TheoremEvidenceRegistry,
)
from ..application.execution_semantic_kernel import (
    SealedExecutionPlanBlocked,
    SealedExecutionPlanValue,
    SemanticKernelContextError,
    compile_sealed_plan_from_snapshot,
)
from ..application.fresh_execution_observation import (
    DOMAIN_BLOCKED,
    MATERIALIZER_NOT_ADMITTED,
    POLICY_BLOCKED,
    SEALABILITY_CONTEXT_ERROR,
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    FreshExecutionObservation,
    RuntimeAdmissionFacts,
    decide_materialization_readiness,
    decide_runtime_policy_admission,
)
from ..application.seal_execution_plan import (
    SealExecutionPlanCommand,
    WorkExecutionSummary,
)
from ..application.stored_execution_plan import (
    ExecutionPolicyBlocked,
    ExecutionQualificationBlocked,
    PlanPublished,
    RequestedVersionSelector,
    SealTerminalOutcome,
    StaleExecutionBasis,
)
from ..external.seal_orchestration_runner import seal_execution_plan
from ..external.work_execution_plan_store import WorkExecutionPlanStore
from ..host.per_work_fence import per_work_mutation_fence
from ..host.profile_admission_fence import profile_admission_fence

MAX_OBSERVATION_ATTEMPTS = 8

# Product contract error code(fresh observation 축 전용 강등 코드).
EXECUTION_OBSERVATION_CONTEXT_ERROR = "EXECUTION_OBSERVATION_CONTEXT_ERROR"


class ObservationRetryExhausted(Exception):
    """fresh observation Profile discovery 가 bounded 재시도를 소진 — command outcome 은 보존."""

    code = EXECUTION_OBSERVATION_CONTEXT_ERROR


# ─── runtime materializer conformance port(S6 가 admit 을 구현, S5 는 미출하) ────────────
@dataclass(frozen=True)
class RuntimeMaterializerConformance:
    """현재 runtime 이 이 Plan schema/encoding·materialization contract 를 admit 하는지의 판정."""

    verdict: str  # MATERIALIZER_ADMITTED | MATERIALIZER_NOT_ADMITTED | CONTEXT_ERROR
    plan_schema_supported: bool
    canonical_encoding_supported: bool
    runtime_capability_manifest_digest: str | None = None


class RuntimeMaterializerConformancePort(Protocol):
    """current runtime capability facts 를 판정하는 port. S5-11 은 선언·소비만 하고 S6 가 구현한다."""

    def __call__(
        self,
        *,
        plan_schema_version: str,
        canonical_encoding_version: str,
        materialization_contract_id: str,
        execution_base_kind: str,
    ) -> RuntimeMaterializerConformance: ...


def s6_absent_runtime_conformance(
    *,
    plan_schema_version: str,
    canonical_encoding_version: str,
    materialization_contract_id: str,
    execution_base_kind: str,
) -> RuntimeMaterializerConformance:
    """S6 미출하 기본 판정 — Plan schema/encoding 은 알려졌지만 materializer 는 아직 admit 하지 않는다.

    따라서 합법적 S5 종료 상태는 sealable + NOT_ADMITTED(MATERIALIZATION_CONTRACT_NOT_ADMITTED) +
    NOT_READY 다 — unknown support 를 admitted 로 fallback 하지 않는다(fail-closed).
    """
    return RuntimeMaterializerConformance(
        verdict=MATERIALIZER_NOT_ADMITTED,
        plan_schema_supported=True,
        canonical_encoding_supported=True,
        runtime_capability_manifest_digest=None,
    )


# ─── Product command ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SealExecutionPlanProductCommand:
    workspace_instance_id: str
    work_ref: str
    request_id: str
    requested_execution_base_kind: str = APPLIED_TEMPLATE_CANDIDATE
    requested_execution_semantic_contract: "RequestedVersionSelector | None" = None
    requested_plan_schema: "RequestedVersionSelector | None" = None
    requested_canonical_encoding: "RequestedVersionSelector | None" = None

    def __post_init__(self) -> None:
        for name in ("workspace_instance_id", "work_ref", "request_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{name} 는 비어 있지 않은 문자열이어야 한다")


# ─── command outcome Product DTOs ────────────────────────────────────────────────────
@dataclass(frozen=True)
class PlanPublishedProductOutcome:
    publication_kind: str
    plan_semantic_digest: str
    execution_basis_digest: str
    captured_execution_input_digest: str


@dataclass(frozen=True)
class ExecutionQualificationBlockedProductOutcome:
    normalized_blockers: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionPolicyBlockedProductOutcome:
    policy_code: str
    qualification_profile_id: str | None
    observed_policy_version: str | None


@dataclass(frozen=True)
class StaleExecutionBasisProductOutcome:
    stale_reason: str


SealExecutionPlanCommandOutcome = (
    PlanPublishedProductOutcome
    | ExecutionQualificationBlockedProductOutcome
    | ExecutionPolicyBlockedProductOutcome
    | StaleExecutionBasisProductOutcome
)


@dataclass(frozen=True)
class SealExecutionPlanResponse:
    command_outcome: SealExecutionPlanCommandOutcome
    fresh_observation: FreshExecutionObservation


_Route = Callable[[str, str], str]
_Authorize = Callable[[str, str], None]
_ProfileFence = Callable[[str], Any]
_WorkFence = Callable[[str, str], Any]


class SealExecutionPlanProduct:
    """Product API — route/auth + S5-10 seal dispatch + command outcome / current Sealed Plan 관찰.

    seal seam(capture/shipping/summary)은 injected — production 결선은 downstream 소유다.
    """

    def __init__(
        self,
        *,
        plan_store: WorkExecutionPlanStore,
        read_admission_state: Callable[[str], "str | None"],
        resolve_route: _Route,
        authorize: _Authorize,
        read_summary: Callable[[str, str], WorkExecutionSummary],
        capture_under_fence: Callable[..., Any],
        resolve_shipping_policy: Callable[..., ResolvedSealPolicy],
        clock: Callable[[], str],
        runtime_conformance: RuntimeMaterializerConformancePort = (
            s6_absent_runtime_conformance
        ),
        theorem_registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
        profile_fence: _ProfileFence = profile_admission_fence,
        work_fence: _WorkFence = per_work_mutation_fence,
        max_observation_attempts: int = MAX_OBSERVATION_ATTEMPTS,
    ) -> None:
        self._plan_store = plan_store
        self._read_admission = read_admission_state
        self._resolve_route = resolve_route
        self._authorize = authorize
        self._read_summary = read_summary
        self._capture = capture_under_fence
        self._resolve_policy = resolve_shipping_policy
        self._clock = clock
        self._runtime = runtime_conformance
        self._theorem_registry = theorem_registry
        self._profile_fence = profile_fence
        self._work_fence = work_fence
        self._attempts = max_observation_attempts

    # ── public Product API ────────────────────────────────────────────────────────
    def seal_execution_plan(
        self, command: SealExecutionPlanProductCommand
    ) -> SealExecutionPlanResponse:
        """route → auth(seal 내부에서 매 호출 재확인) → S5-10 dispatch → 응답 조립.

        attempt error(route/auth/context/store)는 response success union 밖이라 그대로 전파된다.
        fresh observation 은 command outcome 을 소거하지 않는다(관찰 축만 강등).
        """
        ws = command.workspace_instance_id
        inner = SealExecutionPlanCommand(
            workspace_instance_id=ws,
            work_ref=command.work_ref,
            request_id=command.request_id,
            requested_execution_base_kind=command.requested_execution_base_kind,
            **_selectors(command),
        )
        result = seal_execution_plan(
            inner,
            plan_store=self._plan_store,
            resolve_route=self._resolve_route,
            authorize=lambda wid, _cmd: self._authorize(wid, ws),
            read_summary=self._read_summary,
            capture_under_fence=self._capture,
            resolve_shipping_policy=self._resolve_policy,
            clock=self._clock,
            profile_fence=self._profile_fence,
            work_fence=self._work_fence,
            theorem_registry=self._theorem_registry,
        )
        outcome = result.terminal_outcome
        work_id = self._resolve_route(ws, command.work_ref)
        command_outcome = self._map_command_outcome(outcome)
        fresh = self._degrade(lambda: self._observe_current_work(ws, work_id, inner))
        return SealExecutionPlanResponse(
            command_outcome=command_outcome,
            fresh_observation=fresh,
        )

    # ── command outcome mapping ───────────────────────────────────────────────────
    def _map_command_outcome(
        self, outcome: SealTerminalOutcome
    ) -> SealExecutionPlanCommandOutcome:
        if isinstance(outcome, PlanPublished):
            return PlanPublishedProductOutcome(
                publication_kind=outcome.publication_kind,
                plan_semantic_digest=outcome.plan_semantic_digest,
                execution_basis_digest=outcome.execution_basis_digest,
                captured_execution_input_digest=outcome.captured_execution_input_digest,
            )
        if isinstance(outcome, ExecutionQualificationBlocked):
            return ExecutionQualificationBlockedProductOutcome(
                normalized_blockers=outcome.normalized_blockers
            )
        if isinstance(outcome, ExecutionPolicyBlocked):
            return ExecutionPolicyBlockedProductOutcome(
                policy_code=outcome.policy_code,
                qualification_profile_id=outcome.qualification_profile_id,
                observed_policy_version=outcome.observed_policy_version,
            )
        assert isinstance(outcome, StaleExecutionBasis)
        return StaleExecutionBasisProductOutcome(stale_reason=outcome.stale_reason)

    # ── fresh observation(current Sealed Plan value 재계산) ─────────────────────────
    def _degrade(
        self, observe: Callable[[], FreshExecutionObservation]
    ) -> FreshExecutionObservation:
        """fresh observation 은 best-effort 다: observation-only port(summary·shipping·admission·
        capture) 실패는 ExecutionObservationContextError 로 강등해 command outcome 을 보존한다.
        """
        try:
            return observe()
        except Exception as exc:  # noqa: BLE001 - fresh 축 전용 degrade
            return ExecutionObservationContextError(
                EXECUTION_OBSERVATION_CONTEXT_ERROR, str(exc)
            )

    def _observe_current_work(
        self, ws: str, work_id: str, command: SealExecutionPlanCommand
    ) -> FreshExecutionObservation:
        """current Work 를 ProfileFence→WorkFence 아래 관찰해 current Sealed Plan value 를 재계산한다.

        exact capture → kernel compile: sealable 이면 SealedExecutionPlanValue + admission + readiness,
        seal 불가면 current-work blocker. store 를 읽지 않는다(historical Plan lookup 없음).
        """
        for _ in range(self._attempts):
            observed = self._read_summary(ws, work_id)
            with self._profile_fence(observed.qualification_profile_id):
                with self._work_fence(ws, work_id):
                    exact = self._read_summary(ws, work_id)
                    if exact.qualification_profile_id != observed.qualification_profile_id:
                        continue
                    # CURRENT shipping policy 를 fresh resolve 한다 — AUTO default 가 바뀐 뒤
                    # obsolete contract 로 관찰하지 않게 매 관찰이 현재 policy 를 쓴다.
                    policy = self._resolve_policy(command, exact)
                    current = self._capture(
                        ws, work_id, exact.template_application_id,
                        exact.qualification_profile_id, policy,
                    )
                    return self._classify_current(work_id, exact, policy, current)
        raise ObservationRetryExhausted("fresh observation Profile discovery 재시도 소진")

    def _classify_current(
        self,
        work_id: str,
        exact: WorkExecutionSummary,
        policy: ResolvedSealPolicy,
        current: Any,
    ) -> FreshExecutionObservation:
        """capture 결과 → current Sealed Plan value 또는 current-work blocker(순수 판정 + 관찰).

        sealable 은 CurrentSealedPlanObservation(value + admission + readiness), block/context 는
        CurrentWorkExecutionObservation. C1~C10·미지원·compile context error 는 currentness 를 확정할
        수 없으므로 CONTEXT_ERROR 로 관찰한다(port 예외가 아니라 값 판정이라 degrade 되지 않는다).
        """
        app_ref = exact.template_application_id
        if isinstance(current, ExecutionCaptureContextError):
            return self._blocked_work(work_id, SEALABILITY_CONTEXT_ERROR, app_ref, ())
        if isinstance(current, CapturedExecutionPolicyBlock):
            return self._blocked_work(
                work_id, POLICY_BLOCKED, app_ref, (current.policy_code,)
            )
        if isinstance(current, CapturedExecutionDomainBlock):
            return self._blocked_work(
                work_id, DOMAIN_BLOCKED, app_ref, current.normalized_blockers
            )
        assert isinstance(current, CapturedExecutionInput)
        try:
            value = compile_sealed_plan_from_snapshot(current)
        except SemanticKernelContextError:
            return self._blocked_work(work_id, SEALABILITY_CONTEXT_ERROR, app_ref, ())
        if isinstance(value, SealedExecutionPlanBlocked):
            return self._blocked_work(
                work_id, DOMAIN_BLOCKED, app_ref, value.normalized_blockers
            )
        assert isinstance(value, SealedExecutionPlanValue)
        return self._observe_sealable(exact, policy, value)

    def _blocked_work(
        self, work_id: str, sealability: str, app_ref: str, blockers: tuple[str, ...]
    ) -> CurrentWorkExecutionObservation:
        return CurrentWorkExecutionObservation(
            work_authority_ref=work_id,
            current_sealability=sealability,
            observed_at=self._clock(),
            current_template_application_ref=app_ref,
            normalized_blockers_or_policy=blockers,
        )

    def _observe_sealable(
        self,
        exact: WorkExecutionSummary,
        policy: ResolvedSealPolicy,
        value: SealedExecutionPlanValue,
    ) -> CurrentSealedPlanObservation:
        """current sealable value 에 runtime admission·readiness 를 얹는다(ProfileFence 아래).

        admission-state read 는 우리가 보유한 ProfileFence 아래에서 호출된다(port 는 downstream 이
        read_qualification_profile_admission_under_fence 로 배선). readiness 는 admission 만으로 갈린다.
        """
        admission_state = self._read_admission(exact.qualification_profile_id)
        conformance = self._runtime(
            plan_schema_version=value.plan_schema_version,
            canonical_encoding_version=value.canonical_encoding_version,
            materialization_contract_id=value.contract_semantics.materialization_contract_id,
            execution_base_kind=policy.execution_base_kind,
        )
        admission = decide_runtime_policy_admission(
            RuntimeAdmissionFacts(
                profile_admission_state=admission_state,
                execution_base_kind_admitted=(
                    policy.execution_base_kind == APPLIED_TEMPLATE_CANDIDATE
                ),
                plan_schema_supported_by_runtime=conformance.plan_schema_supported,
                canonical_encoding_supported_by_runtime=(
                    conformance.canonical_encoding_supported
                ),
                materializer_conformance=conformance.verdict,
            )
        )
        readiness = decide_materialization_readiness(admission)
        return CurrentSealedPlanObservation(
            sealed_plan_value=value,
            runtime_policy_admission=admission,
            materialization_readiness=readiness,
            observed_at=self._clock(),
        )


def _selectors(command: SealExecutionPlanProductCommand) -> dict[str, RequestedVersionSelector]:
    """생략된 selector(None)는 inner command 의 AUTO 기본값에 맡긴다(EXACT 만 명시 전달)."""
    out: dict[str, RequestedVersionSelector] = {}
    for name in (
        "requested_execution_semantic_contract",
        "requested_plan_schema",
        "requested_canonical_encoding",
    ):
        value = getattr(command, name)
        if value is not None:
            out[name] = value
    return out


__all__ = [
    "SealExecutionPlanProduct",
    "SealExecutionPlanProductCommand",
    "SealExecutionPlanResponse",
    "SealExecutionPlanCommandOutcome",
    "PlanPublishedProductOutcome",
    "ExecutionQualificationBlockedProductOutcome",
    "ExecutionPolicyBlockedProductOutcome",
    "StaleExecutionBasisProductOutcome",
    "RuntimeMaterializerConformance",
    "RuntimeMaterializerConformancePort",
    "s6_absent_runtime_conformance",
    "EXECUTION_OBSERVATION_CONTEXT_ERROR",
]
