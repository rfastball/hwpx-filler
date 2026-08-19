"""SealExecutionPlan orchestration runner — optimistic capture → pure compile → final seal (S5-10 · #706).

짧은 exact capture gate 와 짧은 final gate 사이에서 **fence 밖** pure qualification·compile 을
수행한다. capture 는 reservation 이 아니다: final 직전에 candidate 가 사용한 exact contracts 로
current semantic basis 를 재구성해 equality·Profile policy 를 다시 확인한 뒤 current candidate 에서
직접 terminal outcome 을 낸다. **S5F R2-04b-2(#740): durable Plan store 가 없다** — publish·create/
reuse·atomic commit 없이 방금 계산한 현재 결과(``ExecutionPlanSealed``/block/policy/stale)를 반환한다.

global lock order 를 엄격히 지킨다(바깥→안):

    QualificationProfileAdmissionFence → PerWorkMutationFence

WorkFence 를 잡은 뒤 다른 ProfileFence 를 기다리지 않는다 — final gate 에서 current summary 가
candidate Profile 과 달라졌으면 fence 를 풀고 stale/context 로 닫는다(다른 ProfileFence 를 WorkFence
아래 잡지 않는다). 장기 pure section 동안은 어떤 fence 도 보유하지 않는다.

판정·값 모델·순수 전이는 :mod:`hwpxfiller.application.seal_execution_plan` 소유다. 이 어댑터는
fence 획득·capture port 호출·verdict 결선만 진다(#675 pattern).

이 runner 는 **additive** 다 — 어떤 product Generate route 도 이 slice 에서 cut over 하지 않는다
(S5-11 Product API / S5-13 bridge 소유). capture port·fresh observation·shipping policy resolver 는
injectable seam 이라 실 결선은 downstream 이 주입한다.
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
    CandidateCompilation,
    CaptureTerminal,
    FinalPublish,
    FinalVerdict,
    FreshWorkObservationPort,
    PlanCandidate,
    SealExecutionPlanCommand,
    ShippingSealPolicyResolver,
    classify_capture_result,
    compile_candidate,
    decide_final_verdict,
    require_exact_selector_consistency,
    sealed_outcome_for,
)
from hwpxfiller.application.stored_execution_plan import SealTerminalOutcome
from hwpxfiller.host.per_work_fence import per_work_mutation_fence

_WorkFence = Callable[[str, str], AbstractContextManager[None]]
_RouteResolver = Callable[[str, str], str]
_Authorizer = Callable[[str, SealExecutionPlanCommand], None]


@dataclass(frozen=True)
class SealExecutionPlanResult:
    """command 의 현재-state 결과 — 매 호출이 현재 authority 에서 재계산한 terminal outcome.

    R2-04b-2(#740): durable Plan store 가 없다. sealable 은 current candidate 에서 직접
    ``ExecutionPlanSealed`` 를 낸다(content-addressed publish·create/reuse 없음). block/policy/stale
    도 durable 하게 남기지 않는다 — 응답은 방금 계산한 현재 terminal outcome 이다.

    ``work_authority_id`` 는 이 command 이 실제로 결속한 exact Work identity 다(#742). downstream
    이 command outcome 과 나란히 fresh observation 을 낼 때 work_ref 를 다시 resolve 하지 않고
    이 값을 재사용해야 command 과 observation 이 같은 Work 에 묶인다(사이에 rename/삭제가 나도).
    """

    terminal_outcome: SealTerminalOutcome
    work_authority_id: str


def seal_execution_plan(
    command: SealExecutionPlanCommand,
    *,
    resolve_route: _RouteResolver,
    authorize: _Authorizer,
    read_summary: FreshWorkObservationPort,
    capture_under_fence: CaptureExecutionQualificationInputUnderFence,
    resolve_shipping_policy: ShippingSealPolicyResolver,
    work_fence: _WorkFence = per_work_mutation_fence,
    theorem_registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
) -> SealExecutionPlanResult:
    """route → auth → capture gate → pure compile → final gate → 현재-state terminal.

    같은 request 를 다시 호출해도 historical response 를 replay 하지 않고 현재 authority 에서 다시
    계산한다. sealable 은 current candidate 에서 직접 ``ExecutionPlanSealed`` 를 내고(durable store
    없음), block/policy/stale 도 durable 하게 남기지 않는다. route/auth/context/integrity 실패는
    attempt error 로 raise 한다.
    """
    ws = command.workspace_instance_id
    work_authority_id = resolve_route(ws, command.work_ref)  # 실패는 port 가 attempt 로 raise
    authorize(work_authority_id, command)  # 매 호출 재확인(replay 없음)

    # ── exact capture gate(PerWorkFence 하나 아래에서 exact Work authority 를 직접 capture) ──
    # R2-05b(#740): ProfileFence·optimistic Profile discovery·bounded retry 를 제거했다. profile 은
    # 이제 immutable Template Application 의 함수라 fence 사이에 따로 관측할 대상이 아니다 —
    # PerWorkFence 아래에서 exact authority 를 바로 읽어 capture 한다.
    with work_fence(ws, work_authority_id):
        exact = read_summary(ws, work_authority_id)
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
            return SealExecutionPlanResult(classification.outcome, work_authority_id)
        captured = classification.captured

    # ── pure qualification + compile(어떤 fence 도 보유하지 않는다) ──────────────────
    candidate = compile_candidate(captured, theorem_registry=theorem_registry)

    # ── final gate(PerWorkFence 재진입, current Work basis recheck) ──────────────────
    with work_fence(ws, work_authority_id):
        summary = read_summary(ws, work_authority_id)
        # candidate 가 사용한 exact profile/policy 로 current Application 의 basis 를 재구성해 candidate
        # 와 대조한다. Application 이 이동했으면 다른 basis digest → StaleExecutionBasis(현재 blocker 를
        # 기록하지 않는다). policy/domain block·context error 는 decide_final_verdict 가 닫는다.
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
        verdict = decide_final_verdict(candidate, current, current_compiled, summary)
        return _result_for_verdict(verdict, work_authority_id)


def _result_for_verdict(
    verdict: FinalVerdict, work_authority_id: str
) -> SealExecutionPlanResult:
    """FinalPublish → current candidate 에서 직접 ``ExecutionPlanSealed``. block/policy/stale → 그대로.

    durable store 가 없다(R2-04b-2): publish·create/reuse·ledger 없이 방금 계산한 현재 terminal
    outcome 을 반환한다. ``work_authority_id`` 는 이 command 이 결속한 exact Work identity 로
    outcome 과 함께 실려 downstream 이 observation 을 같은 Work 에 묶게 한다(#742).
    """
    if not isinstance(verdict, FinalPublish):
        return SealExecutionPlanResult(verdict.outcome, work_authority_id)
    plan = verdict.candidate
    assert isinstance(plan, PlanCandidate)
    return SealExecutionPlanResult(sealed_outcome_for(plan), work_authority_id)
