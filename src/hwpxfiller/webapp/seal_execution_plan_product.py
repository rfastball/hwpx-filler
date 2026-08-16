"""SealExecutionPlan Product API — historical outcome replay + fresh observation 분리 (S5-11 · #707).

두 질의를 **절대 섞지 않고** 나란히 노출한다:

- ``command_outcome`` — durable first-seen terminal outcome 의 immutable replay(무엇이 일어났는가).
  S5-10 application service(:func:`seal_execution_plan`)가 소유·commit 한 ledger 를 그대로 되읽는다.
- ``fresh_observation`` — 지금 이 순간의 current Work/Profile/runtime 관계 recompute(현재 상태).
  historical PlanPublished 이면 그 Plan 을 fresh observe(currentness·admission·readiness), 그 외
  terminal outcome 이면 current Work sealability 를 관찰한다.

historical event 를 current state 로 덮어쓰지 않고, blocked/stale outcome 에 임의의 이전 Plan 을 붙이지
않는다. fresh observation 실패는 historical outcome 을 소거하지 않는다(그 축만 context error).

opaque Plan ref 는 raw digest 를 직접 신뢰하지 않게 하는 route-bound HMAC signed wrapper 다 — resolve
시 route 가 정한 Work 와 claims 의 Work 를 **독립 비교**해 cross-Work ref 를 거절한다.

**additive 경계**: 이 Product service 는 headless(pywebview 비의존)이고 production Generate route 를
cut over 하거나 native materialization 을 시작하지 않는다(S6 소유). action registry·bridge·frontend
generated types 배선은 downstream wiring slice(S5-13) 소유다 — 여기서는 하지 않는다. capture port·
shipping policy resolver·fresh observation summary·admission-state read 는 injectable seam 이라 실
store/HWPX 결선은 downstream 이 주입한다(#706 과 동일). admission-state read 는 Product 가 보유한
ProfileFence 아래에서 호출되며, downstream 은 ``read_qualification_profile_admission_under_fence`` 로
배선한다(under-fence helper 를 직접 참조하지 않아 per-Work fence 우회 게이트를 지킨다).
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
from ..application.execution_plan_reference import (
    PLAN_REF_PURPOSE,
    PLAN_REF_SCHEMA_VERSION,
    InvalidPlanReference,
    OpaquePlanReferenceClaims,
    PlanReferenceError,
    PlanReferencePurposeMismatch,
    open_plan_reference,
    plan_reference_actor_binding_digest,
    sign_plan_reference,
)
from ..application.fresh_execution_observation import (
    CURRENT,
    CURRENT_BASIS_NOT_SEALABLE,
    CURRENTNESS_CONTEXT_ERROR,
    DIGEST_MISMATCH,
    DOMAIN_BLOCKED,
    MATERIALIZER_ADMITTED,
    MATERIALIZER_NOT_ADMITTED,
    POLICY_BLOCKED,
    SEALABILITY_CONTEXT_ERROR,
    SEALABLE,
    STALE,
    TEMPLATE_APPLICATION_CHANGED,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    FreshExecutionObservation,
    PublishedPlanObservation,
    RuntimeAdmissionFacts,
    RuntimePolicyAdmission,
    SemanticCurrentness,
    decide_materialization_readiness,
    decide_runtime_policy_admission,
)
from ..application.seal_execution_plan import (
    BlockedCandidate,
    PlanCandidate,
    SealAttemptError,
    SealExecutionPlanCommand,
    WorkExecutionSummary,
    compile_candidate,
)
from ..application.stored_execution_plan import (
    ExecutionPolicyBlocked,
    ExecutionQualificationBlocked,
    FirstSeenSealCommandRecord,
    PlanPublished,
    RequestedVersionSelector,
    SealTerminalOutcome,
    StaleExecutionBasis,
    WorkExecutionPlanAggregate,
)
from ..external.seal_orchestration_runner import seal_execution_plan
from ..external.work_execution_plan_store import WorkExecutionPlanStore
from ..host.per_work_fence import per_work_mutation_fence
from ..host.profile_admission_fence import profile_admission_fence

#: 단일 사용자 데스크톱 로컬 actor — token·session 과 독립으로 매 요청 확인한다.
LOCAL_ACTOR = "local-user"

MAX_OBSERVATION_ATTEMPTS = 8

# Product contract error codes.
PLAN_REFERENCE_INVALID = "PLAN_REFERENCE_INVALID"
PLAN_REFERENCE_PURPOSE_MISMATCH = "PLAN_REFERENCE_PURPOSE_MISMATCH"
PLAN_REFERENCE_ROUTE_MISMATCH = "PLAN_REFERENCE_ROUTE_MISMATCH"
PLAN_REFERENCE_WORK_MISMATCH = "PLAN_REFERENCE_WORK_MISMATCH"
PLAN_REFERENCE_UNRESOLVABLE = "PLAN_REFERENCE_UNRESOLVABLE"
EXECUTION_OBSERVATION_CONTEXT_ERROR = "EXECUTION_OBSERVATION_CONTEXT_ERROR"


class SealExecutionPlanProductError(Exception):
    """Product API 거절 — code 로 원인 구분(ledger 에 기록하지 않는다). integrity/context 를
    user-fixable seal blocker 로 낮추지 않는다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject(code: str, message: str) -> SealExecutionPlanProductError:
    return SealExecutionPlanProductError(code, message)


class ObservationRetryExhausted(Exception):
    """fresh observation Profile discovery 가 bounded 재시도를 소진 — historical outcome 은 보존."""

    code = "EXECUTION_OBSERVATION_CONTEXT_ERROR"


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

    따라서 합법적 S5 종료 상태는 CURRENT + NOT_ADMITTED(MATERIALIZATION_CONTRACT_NOT_ADMITTED) +
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


# ─── historical outcome Product DTOs ─────────────────────────────────────────────────
@dataclass(frozen=True)
class PlanPublishedProductOutcome:
    publication_kind: str
    opaque_plan_ref: str
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
    command_replayed: bool
    fresh_observation: FreshExecutionObservation


@dataclass(frozen=True)
class ResolvedPlanReference:
    """opaque ref resolve 결과 — exact digest identity 복원 + 그 Plan 의 fresh observation."""

    plan_semantic_digest: str
    plan_schema_version: str
    canonical_encoding_version: str
    fresh_observation: FreshExecutionObservation


_Route = Callable[[str, str], str]
_Authorize = Callable[[str, str], None]
_ProfileFence = Callable[[str], Any]
_WorkFence = Callable[[str, str], Any]


class SealExecutionPlanProduct:
    """Product API — route/auth + S5-10 seal dispatch + historical/fresh mapping + opaque ref.

    seal seam(capture/shipping/summary)은 injected — production 결선은 downstream 소유다.
    """

    def __init__(
        self,
        *,
        plan_store: WorkExecutionPlanStore,
        read_admission_state: Callable[[str], "str | None"],
        load_secret: Callable[[], bytes],
        resolve_route: _Route,
        authorize: _Authorize,
        read_summary: Callable[[str, str], WorkExecutionSummary],
        capture_under_fence: Callable[..., Any],
        resolve_shipping_policy: Callable[..., ResolvedSealPolicy],
        clock: Callable[[], str],
        runtime_conformance: RuntimeMaterializerConformancePort = (
            s6_absent_runtime_conformance
        ),
        actor_subject: str = LOCAL_ACTOR,
        theorem_registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
        profile_fence: _ProfileFence = profile_admission_fence,
        work_fence: _WorkFence = per_work_mutation_fence,
        max_observation_attempts: int = MAX_OBSERVATION_ATTEMPTS,
    ) -> None:
        self._plan_store = plan_store
        self._read_admission = read_admission_state
        self._load_secret = load_secret
        self._resolve_route = resolve_route
        self._authorize = authorize
        self._read_summary = read_summary
        self._capture = capture_under_fence
        self._resolve_policy = resolve_shipping_policy
        self._clock = clock
        self._runtime = runtime_conformance
        self._actor = actor_subject
        self._theorem_registry = theorem_registry
        self._profile_fence = profile_fence
        self._work_fence = work_fence
        self._attempts = max_observation_attempts

    # ── public Product API ────────────────────────────────────────────────────────
    def seal_execution_plan(
        self, command: SealExecutionPlanProductCommand
    ) -> SealExecutionPlanResponse:
        """route → auth(seal 내부에서 replay 마다 재확인) → S5-10 dispatch → 응답 조립.

        attempt error(route/auth/context/store)는 response success union 밖이라 그대로 전파된다.
        """
        ws = command.workspace_instance_id
        inner = SealExecutionPlanCommand(
            workspace_instance_id=ws,
            work_ref=command.work_ref,
            request_id=command.request_id,
            requested_execution_base_kind=command.requested_execution_base_kind,
            **_selectors(command),
        )
        # 봉인 dispatch 전에 signing dependency(HMAC secret)를 preflight·retain 한다 — seal 은
        # request ID 를 소비·commit 하므로, 그 뒤에 secret 이 손상/부재면 durable outcome 이 기록됐는데도
        # ref 발급이 실패해 재시도가 이미 소비된 request 만 replay 하는 stranded 상태가 된다(finding 3).
        secret = self._load_secret()
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
        work_id = result.record.request_intent_fingerprint.work_authority_id
        outcome = result.terminal_outcome
        # commit 뒤엔 fallible work 를 하지 않는다 — ref 는 반환된 record 로만 구성하고 preloaded
        # secret 으로 서명한다(store 재조회·secret 재로딩 없음).
        opaque_ref = (
            self._issue_reference(ws, work_id, outcome, result.record, secret)
            if isinstance(outcome, PlanPublished)
            else None
        )
        command_outcome = self._map_command_outcome(outcome, opaque_ref)
        fresh = self._observe(ws, work_id, outcome, inner, opaque_ref)
        return SealExecutionPlanResponse(
            command_outcome=command_outcome,
            command_replayed=result.replayed,
            fresh_observation=fresh,
        )

    def resolve_plan_reference(
        self, opaque_plan_ref: str, work_ref: str, workspace_instance_id: str
    ) -> ResolvedPlanReference:
        """opaque ref 를 검증·resolve 해 exact digest identity 복원 + fresh observation 을 낸다.

        검증: signature/purpose/schema(open) → workspace route equality → route-resolved Work
        equality(token claim Work 를 채택하지 않는다) → actor authorization → Plan store exact
        resolve → canonical integrity(store decode 가 재검증). 매 호출 route·auth 를 다시 한다.
        """
        ws = workspace_instance_id
        work_id = self._resolve_route(ws, work_ref)
        self._authorize(work_id, ws)
        claims = self._open_ref(opaque_plan_ref)
        if claims.workspace_instance_id != ws:
            raise _reject(PLAN_REFERENCE_ROUTE_MISMATCH, "ref workspace 가 route 와 다르다")
        if claims.actor_binding_digest != self._actor_binding(ws):
            raise _reject(PLAN_REFERENCE_ROUTE_MISMATCH, "ref actor binding 불일치")
        if claims.work_authority_id != work_id:
            # token 이 가리키는 Work 를 요청 대상으로 채택하지 않는다(cross-Work 거절).
            raise _reject(PLAN_REFERENCE_WORK_MISMATCH, "ref Work 가 route Work 와 다르다")
        aggregate = self._plan_store.load_or_empty(work_id, ws)
        plan = aggregate.plans_by_semantic_digest.get(claims.plan_semantic_digest)
        if plan is None:
            raise _reject(
                PLAN_REFERENCE_UNRESOLVABLE, "ref 가 가리키는 Plan 을 store 에서 찾을 수 없다"
            )
        # fresh observation 실패는 exact digest resolve(historical fact)를 막지 않는다(_fresh_published
        # 가 fresh 축만 degrade). historical store 손상은 위 store 접근에서 이미 surface 된다.
        fresh = self._fresh_published(ws, work_id, aggregate, claims.plan_semantic_digest, opaque_plan_ref)
        return ResolvedPlanReference(
            plan_semantic_digest=claims.plan_semantic_digest,
            plan_schema_version=claims.plan_schema_version,
            canonical_encoding_version=claims.canonical_encoding_version,
            fresh_observation=fresh,
        )

    # ── historical outcome mapping ────────────────────────────────────────────────
    def _map_command_outcome(
        self, outcome: SealTerminalOutcome, opaque_ref: "str | None"
    ) -> SealExecutionPlanCommandOutcome:
        if isinstance(outcome, PlanPublished):
            assert opaque_ref is not None
            return PlanPublishedProductOutcome(
                publication_kind=outcome.publication_kind,
                opaque_plan_ref=opaque_ref,
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
        # stale outcome 에 임의의 이전 Plan ref 를 붙이지 않는다.
        return StaleExecutionBasisProductOutcome(stale_reason=outcome.stale_reason)

    def _issue_reference(
        self,
        ws: str,
        work_id: str,
        outcome: PlanPublished,
        record: FirstSeenSealCommandRecord,
        secret: bytes,
    ) -> str:
        # commit 뒤 fallible work 0: plan schema·encoding 을 반환된 record 의 resolved policy 에서
        # 되읽고(store 재조회 없음) preloaded secret 으로 서명한다. store 는 이 둘이 plan payload 와
        # 일치함을 apply_publish 에서 이미 강제했으므로 record 가 권위다(finding 3).
        policy = record.resolved_seal_policy
        claims = OpaquePlanReferenceClaims(
            ref_schema_version=PLAN_REF_SCHEMA_VERSION,
            ref_purpose=PLAN_REF_PURPOSE,
            workspace_instance_id=ws,
            work_authority_id=work_id,
            plan_semantic_digest=outcome.plan_semantic_digest,
            plan_schema_version=policy.plan_schema_version,
            canonical_encoding_version=policy.canonical_encoding_version,
            actor_binding_digest=self._actor_binding(ws),
            issued_at=self._clock(),
        )
        return sign_plan_reference(claims, secret)

    # ── fresh observation dispatch ────────────────────────────────────────────────
    def _observe(
        self,
        ws: str,
        work_id: str,
        outcome: SealTerminalOutcome,
        command: SealExecutionPlanCommand,
        opaque_ref: "str | None",
    ) -> FreshExecutionObservation:
        if isinstance(outcome, PlanPublished):
            assert opaque_ref is not None
            # historical store 접근은 degrade 밖 — 손상이면 surface(fresh 축이 아니라 store 무결성).
            aggregate = self._plan_store.load_or_empty(work_id, ws)
            return self._fresh_published(
                ws, work_id, aggregate, outcome.plan_semantic_digest, opaque_ref
            )
        # 비-published: current Work sealability 를 fresh 관찰(historical store read 없음).
        return self._degrade(lambda: self._observe_current_work(ws, work_id, command))

    def _fresh_published(
        self,
        ws: str,
        work_id: str,
        aggregate: WorkExecutionPlanAggregate,
        plan_digest: str,
        opaque_ref: str,
    ) -> FreshExecutionObservation:
        """historical store-derived setup(손상이면 surface) + fresh 관찰(실패면 context error)."""
        # 이 setup 은 historical store 를 읽는다 — plan 부재·ledger 손상은 degrade 하지 않고 surface.
        plan = aggregate.plans_by_semantic_digest[plan_digest]
        plan_basis_digest = plan.semantic_payload_encoded["execution_basis_digest"]
        plan_app_id = plan.semantic_payload_encoded["execution_basis"]["template"][
            "template_application_id"
        ]
        policy = self._resolved_policy_for_plan(aggregate, plan)
        return self._degrade(
            lambda: self._observe_published_plan(
                ws, work_id, plan_basis_digest, plan_app_id, policy, opaque_ref
            )
        )

    def _degrade(
        self, observe: Callable[[], FreshExecutionObservation]
    ) -> FreshExecutionObservation:
        """fresh observation 은 best-effort 다: observation-only port(summary·shipping·admission·
        capture·compile) 실패는 ExecutionObservationContextError 로 강등해 historical outcome 을
        보존한다. historical store 접근은 이 호출 **전에** 끝나 손상은 여기서 삼켜지지 않는다(finding 2).
        """
        try:
            return observe()
        except Exception as exc:  # noqa: BLE001 - fresh 축 전용 degrade(store 접근은 이미 완료)
            return ExecutionObservationContextError(
                EXECUTION_OBSERVATION_CONTEXT_ERROR, str(exc)
            )

    def _observe_published_plan(
        self,
        ws: str,
        work_id: str,
        plan_basis_digest: str,
        plan_app_id: str,
        policy: ResolvedSealPolicy,
        opaque_ref: str,
    ) -> PublishedPlanObservation:
        for _ in range(self._attempts):
            observed = self._read_summary(ws, work_id)
            with self._profile_fence(observed.qualification_profile_id):
                with self._work_fence(ws, work_id):
                    exact = self._read_summary(ws, work_id)
                    if exact.qualification_profile_id != observed.qualification_profile_id:
                        continue
                    # 우리가 보유한 ProfileFence 아래에서 current profile admission 을 읽는다 —
                    # port 는 downstream 이 read_qualification_profile_admission_under_fence 로 배선한다
                    # (under-fence helper 를 직접 참조하지 않아 fence 우회 게이트를 지킨다).
                    admission_state = self._read_admission(
                        exact.qualification_profile_id
                    )
                    current = self._capture(
                        ws, work_id, exact.template_application_id,
                        exact.qualification_profile_id, policy,
                    )
                    currentness, observed_basis = self._classify_currentness(
                        plan_basis_digest, plan_app_id, exact, current
                    )
                    conformance = self._runtime(
                        plan_schema_version=policy.plan_schema_version,
                        canonical_encoding_version=policy.canonical_encoding_version,
                        materialization_contract_id=policy.materialization_contract_id,
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
                    readiness = decide_materialization_readiness(currentness, admission)
                    return PublishedPlanObservation(
                        opaque_plan_ref=opaque_ref,
                        semantic_currentness=currentness,
                        runtime_policy_admission=admission,
                        materialization_readiness=readiness,
                        observed_at=self._clock(),
                        observed_execution_basis_digest=observed_basis,
                        observed_runtime_capability_manifest_digest=(
                            conformance.runtime_capability_manifest_digest
                        ),
                    )
        raise ObservationRetryExhausted("fresh observation Profile discovery 재시도 소진")

    def _observe_current_work(
        self, ws: str, work_id: str, command: SealExecutionPlanCommand
    ) -> CurrentWorkExecutionObservation:
        for _ in range(self._attempts):
            observed = self._read_summary(ws, work_id)
            with self._profile_fence(observed.qualification_profile_id):
                with self._work_fence(ws, work_id):
                    exact = self._read_summary(ws, work_id)
                    if exact.qualification_profile_id != observed.qualification_profile_id:
                        continue
                    # CURRENT shipping policy 를 fresh resolve 한다 — durable first-seen record
                    # policy 를 재사용하면 AUTO default 가 바뀐 뒤 obsolete contract 로 관찰하게 된다
                    # (finding 1: historical 과 fresh 는 recorded policy 를 공유하지 않는다).
                    policy = self._resolve_policy(command, exact)
                    current = self._capture(
                        ws, work_id, exact.template_application_id,
                        exact.qualification_profile_id, policy,
                    )
                    sealability, blockers, basis = self._classify_sealability(current)
                    return CurrentWorkExecutionObservation(
                        work_authority_ref=work_id,
                        current_sealability=sealability,
                        observed_at=self._clock(),
                        current_template_application_ref=exact.template_application_id,
                        normalized_blockers_or_policy=blockers,
                        observed_execution_basis_digest=basis,
                    )
        raise ObservationRetryExhausted("fresh observation Profile discovery 재시도 소진")

    def _classify_currentness(
        self, plan_basis_digest: str, plan_app_id: str,
        exact: WorkExecutionSummary, current: Any,
    ) -> tuple[SemanticCurrentness, str | None]:
        """Plan 의 exact contracts 로 rebuild 한 current basis 와 Plan basis digest 를 비교(순수 판정).

        effective-only equality 라 detached/inactive/authority-only 변경은 CURRENT 다. current 가
        seal 불가면 STALE(CURRENT_BASIS_NOT_SEALABLE), 복원 실패는 currentness CONTEXT_ERROR.
        """
        if isinstance(current, ExecutionCaptureContextError):
            return SemanticCurrentness(CURRENTNESS_CONTEXT_ERROR), None
        if isinstance(current, (CapturedExecutionPolicyBlock, CapturedExecutionDomainBlock)):
            return SemanticCurrentness(STALE, CURRENT_BASIS_NOT_SEALABLE), None
        assert isinstance(current, CapturedExecutionInput)
        try:
            compiled = compile_candidate(current, theorem_registry=self._theorem_registry)
        except SealAttemptError:
            return SemanticCurrentness(CURRENTNESS_CONTEXT_ERROR), None
        if isinstance(compiled, BlockedCandidate):
            return SemanticCurrentness(STALE, CURRENT_BASIS_NOT_SEALABLE), None
        assert isinstance(compiled, PlanCandidate)
        if compiled.execution_basis_digest == plan_basis_digest:
            return SemanticCurrentness(CURRENT), compiled.execution_basis_digest
        reason = (
            TEMPLATE_APPLICATION_CHANGED
            if exact.template_application_id != plan_app_id
            else DIGEST_MISMATCH
        )
        return SemanticCurrentness(STALE, reason), compiled.execution_basis_digest

    def _classify_sealability(
        self, current: Any
    ) -> tuple[str, tuple[str, ...], str | None]:
        if isinstance(current, ExecutionCaptureContextError):
            return SEALABILITY_CONTEXT_ERROR, (), None
        if isinstance(current, CapturedExecutionPolicyBlock):
            return POLICY_BLOCKED, (current.policy_code,), None
        if isinstance(current, CapturedExecutionDomainBlock):
            return DOMAIN_BLOCKED, current.normalized_blockers, None
        assert isinstance(current, CapturedExecutionInput)
        try:
            compiled = compile_candidate(current, theorem_registry=self._theorem_registry)
        except SealAttemptError:
            return SEALABILITY_CONTEXT_ERROR, (), None
        if isinstance(compiled, BlockedCandidate):
            return DOMAIN_BLOCKED, compiled.normalized_blockers, None
        assert isinstance(compiled, PlanCandidate)
        return SEALABLE, (), compiled.execution_basis_digest

    # ── helpers ───────────────────────────────────────────────────────────────────
    def _resolved_policy_for_plan(
        self, aggregate: WorkExecutionPlanAggregate, plan: Any
    ) -> ResolvedSealPolicy:
        """Plan 을 최초 봉인한 first-seen record 의 resolved policy(그 Plan 의 exact contracts)."""
        record = aggregate.first_seen_by_request(
            plan.first_sealed_provenance.first_sealed_by_request_id
        )
        if record is None:  # pragma: no cover - publish 는 항상 자기 ledger record 를 남긴다
            raise ObservationRetryExhausted("Plan 의 봉인 ledger record 를 찾을 수 없다")
        return record.resolved_seal_policy

    def _actor_binding(self, ws: str) -> str:
        return plan_reference_actor_binding_digest(self._actor, ws)

    def _open_ref(self, opaque_plan_ref: str) -> OpaquePlanReferenceClaims:
        try:
            return open_plan_reference(opaque_plan_ref, self._load_secret())
        except PlanReferencePurposeMismatch as exc:
            raise _reject(PLAN_REFERENCE_PURPOSE_MISMATCH, str(exc)) from exc
        except (InvalidPlanReference, PlanReferenceError) as exc:
            raise _reject(PLAN_REFERENCE_INVALID, str(exc)) from exc


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
    "LOCAL_ACTOR",
    "SealExecutionPlanProduct",
    "SealExecutionPlanProductCommand",
    "SealExecutionPlanResponse",
    "SealExecutionPlanCommandOutcome",
    "PlanPublishedProductOutcome",
    "ExecutionQualificationBlockedProductOutcome",
    "ExecutionPolicyBlockedProductOutcome",
    "StaleExecutionBasisProductOutcome",
    "ResolvedPlanReference",
    "RuntimeMaterializerConformance",
    "RuntimeMaterializerConformancePort",
    "s6_absent_runtime_conformance",
    "SealExecutionPlanProductError",
]
