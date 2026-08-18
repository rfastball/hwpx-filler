"""SealExecutionPlan orchestration runner — optimistic capture → pure compile → final seal (S5-10 · #706).

짧은 exact capture gate 와 짧은 final publication gate 사이에서 **fence 밖** pure qualification·
compile 을 수행한다. capture 는 reservation 이 아니다: publish 직전에 candidate 가 사용한 exact
contracts 로 current semantic basis 를 재구성해 equality·Profile policy·functional dependency·
dependency resolvability 를 다시 확인한 뒤 Plan 또는 first-seen terminal outcome 을 atomic commit 한다.

global lock order 를 엄격히 지킨다(바깥→안):

    QualificationProfileAdmissionFence → PerWorkMutationFence → 단일 Store writer lease

WorkFence/lease 를 잡은 뒤 다른 ProfileFence 를 기다리지 않는다 — final gate 에서 current summary 가
candidate Profile 과 달라졌으면 fence 를 풀고 stale/context 로 닫는다(다른 ProfileFence 를 WorkFence
아래 잡지 않는다). 장기 pure section 동안은 어떤 fence 도 보유하지 않는다.

판정·값 모델·순수 전이는 :mod:`hwpxfiller.application.seal_execution_plan` 소유다. 이 어댑터는
fence 획득·capture port 호출·store atomic primitive 결선만 진다(#675 pattern).

이 runner 는 **additive** 다 — 어떤 product Generate route 도 이 slice 에서 cut over 하지 않는다
(S5-11 Product API / S5-13 bridge 소유). capture port·fresh observation·shipping policy resolver 는
injectable seam 이라 실 store/HWPX 결선은 downstream 이 주입한다.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable

from hwpxfiller.application.execution_capture import (
    CaptureExecutionQualificationInputUnderFence,
    CapturedExecutionInput,
)
from hwpxfiller.application.execution_composition import (
    DEFAULT_THEOREM_EVIDENCE_REGISTRY,
    TheoremEvidenceRegistry,
)
from hwpxfiller.application.seal_execution_plan import (
    MAX_DISCOVERY_ATTEMPTS,
    CandidateCompilation,
    CaptureTerminal,
    ExecutionCaptureRetryExhausted,
    FinalPublish,
    FinalVerdict,
    FreshWorkObservationPort,
    PlanCandidate,
    SealExecutionPlanCommand,
    ShippingSealPolicyResolver,
    classify_capture_result,
    compile_candidate,
    decide_final_verdict,
    final_verdict_profile_moved,
    publication_kind_for,
    published_outcome_for,
    require_exact_selector_consistency,
)
from hwpxfiller.application.stored_execution_plan import SealTerminalOutcome
from hwpxfiller.host.per_work_fence import per_work_mutation_fence
from hwpxfiller.host.profile_admission_fence import profile_admission_fence

from .work_execution_plan_store import WorkExecutionPlanStore

_ProfileFence = Callable[[str], AbstractContextManager[None]]
_WorkFence = Callable[[str, str], AbstractContextManager[None]]
_RouteResolver = Callable[[str, str], str]
_Authorizer = Callable[[str, SealExecutionPlanCommand], None]
_Clock = Callable[[], str]


@dataclass(frozen=True)
class SealExecutionPlanResult:
    """command 의 현재-state 결과 — 매 호출이 현재 authority 에서 재계산한 terminal outcome(R2-04a).

    historical replay·first-seen record 를 싣지 않는다. publish(sealable) 은 content-addressed
    store 에 여전히 create/reuse 되지만(04b 대상), 응답은 replayed 된 과거가 아니라 방금 계산한
    ``PlanPublished``/block/policy/stale 다.
    """

    terminal_outcome: SealTerminalOutcome


def seal_execution_plan(
    command: SealExecutionPlanCommand,
    *,
    plan_store: WorkExecutionPlanStore,
    resolve_route: _RouteResolver,
    authorize: _Authorizer,
    read_summary: FreshWorkObservationPort,
    capture_under_fence: CaptureExecutionQualificationInputUnderFence,
    resolve_shipping_policy: ShippingSealPolicyResolver,
    clock: _Clock,
    profile_fence: _ProfileFence = profile_admission_fence,
    work_fence: _WorkFence = per_work_mutation_fence,
    theorem_registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
    max_discovery_attempts: int = MAX_DISCOVERY_ATTEMPTS,
) -> SealExecutionPlanResult:
    """route → auth → capture gate → pure compile → final gate → 현재-state terminal(R2-04a).

    같은 request 를 다시 호출해도 historical response 를 replay 하지 않고 현재 authority 에서 다시
    계산한다. block/policy/stale terminal 은 durable 하게 남기지 않고 fresh 로 되돌린다. sealable
    plan 은 content-addressed store 에 create/reuse 로 publish 한다(04b 대상). route/auth/context/
    integrity/store 실패는 attempt error 로 raise 한다.
    """
    ws = command.workspace_instance_id
    work_authority_id = resolve_route(ws, command.work_ref)  # 실패는 port 가 attempt 로 raise
    authorize(work_authority_id, command)  # 매 호출 재확인(replay 없음)

    # ── short exact capture gate(optimistic Profile discovery + bounded 재시도) ──────
    captured: CapturedExecutionInput | None = None
    for _ in range(max_discovery_attempts):
        observed = read_summary(ws, work_authority_id)
        with profile_fence(observed.qualification_profile_id):
            with work_fence(ws, work_authority_id):
                exact = read_summary(ws, work_authority_id)
                if exact.qualification_profile_id != observed.qualification_profile_id:
                    continue  # 잘못된 ProfileFence — 두 fence 풀고 재시도
                policy = resolve_shipping_policy(command, exact)
                require_exact_selector_consistency(command, policy)
                cap = capture_under_fence(
                    ws,
                    work_authority_id,
                    exact.template_application_id,
                    exact.qualification_profile_id,
                    policy,
                )
                classification = classify_capture_result(cap, policy)
                if isinstance(classification, CaptureTerminal):
                    # capture gate terminal(block/policy) 을 fresh 로 되돌린다(durable 기록 없음).
                    return SealExecutionPlanResult(classification.outcome)
                captured = classification.captured
        break  # complete capture — fence 를 풀고 pure work 로 진행
    else:
        raise ExecutionCaptureRetryExhausted(
            f"work {work_authority_id} 의 Profile discovery 재시도 소진"
        )
    assert captured is not None

    # ── pure qualification + compile(어떤 fence 도 보유하지 않는다) ──────────────────
    candidate = compile_candidate(captured, theorem_registry=theorem_registry)

    # ── short final gate(candidate ProfileFence → WorkFence 재진입) ─────────────────
    with profile_fence(candidate.qualification_profile_id):
        with work_fence(ws, work_authority_id):
            summary = read_summary(ws, work_authority_id)
            if summary.qualification_profile_id == candidate.qualification_profile_id:
                # 같은 Profile fence 아래에서 current(=summary) Application 의 basis 를 재구성한다.
                # Application 이 같으면 candidate 와 대조, 이동했으면 다른 basis digest → stale.
                current = capture_under_fence(
                    ws,
                    work_authority_id,
                    summary.template_application_id,
                    candidate.qualification_profile_id,
                    candidate.resolved_seal_policy,
                )
                current_compiled: "CandidateCompilation | None" = (
                    compile_candidate(current, theorem_registry=theorem_registry)
                    if isinstance(current, CapturedExecutionInput)
                    else None
                )
                verdict = decide_final_verdict(
                    candidate, current, current_compiled, summary
                )
            else:
                # Profile 이 이동했다 — 다른 ProfileFence 를 WorkFence 아래 잡지 않는다. 대신 우리가
                # 쥔 candidate ProfileFence 아래 candidate profile 의 admission 을 관찰해(revoked →
                # policy block, precedence 상 stale 보다 앞) moved 로 revocation 을 놓치지 않는다.
                observation = capture_under_fence(
                    ws,
                    work_authority_id,
                    candidate.template_application_id,
                    candidate.qualification_profile_id,
                    candidate.resolved_seal_policy,
                )
                verdict = final_verdict_profile_moved(candidate, observation, summary)
            return _commit_verdict(
                plan_store, command, work_authority_id, verdict, clock()
            )


def _commit_verdict(
    plan_store: WorkExecutionPlanStore,
    command: SealExecutionPlanCommand,
    work_authority_id: str,
    verdict: FinalVerdict,
    now: str,
) -> SealExecutionPlanResult:
    """FinalPublish → content-addressed store 에 create/reuse publish. block/policy/stale → fresh.

    first-seen ledger·replay 없이 publish 한다: REUSE 는 store 가 무변경으로 흡수하고, CREATE 만
    version 을 올린다. 응답은 방금 계산한 :class:`PlanPublished`(또는 fresh terminal)다.
    """
    if not isinstance(verdict, FinalPublish):
        return SealExecutionPlanResult(verdict.outcome)
    plan = verdict.candidate
    assert isinstance(plan, PlanCandidate)
    ws = command.workspace_instance_id
    aggregate = plan_store.load_or_empty(work_authority_id, ws)
    kind = publication_kind_for(aggregate, plan.plan_semantic_digest)
    published = published_outcome_for(plan, kind)
    plan_store.publish_sealed_plan_atomic(
        work_authority_id=work_authority_id,
        workspace_instance_id=ws,
        expected_aggregate_version=aggregate.aggregate_version,
        request_id=command.request_id,
        resolved_seal_policy=plan.resolved_seal_policy,
        capture_evidence=plan.capture_evidence,
        plan_payload=plan.plan_payload,
        dependency_set=plan.dependency_set,
        published_outcome=published,
        now=now,
    )
    return SealExecutionPlanResult(published)
