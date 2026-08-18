"""S5F-01(#740 R1) execution semantic kernel — control-plane 없이 실행 의미를 계산한다.

두 차례 Architecture Falsification Audit 는 S5 의 semantic compiler/validator 는 유지하되
`SealedExecutionPlan` 을 둘러싼 durable proof/control plane(store·ledger·first-seen·profile
admission·ProfileFence·theorem registry authority·13-role manifest digest lattice)이 현재 v1
topology 에 과대하다고 판정했다. 이 모듈은 그 판정의 **첫 실물 조치**다: 기존에 검증된 순수
계산만 조립해 다음 경로를 control plane 밖으로 독립시킨다.

    exact durable Work authority
            │  (judge_captured_execution — 순수, store·fence·token 모름)
            ▼
    exact execution snapshot(CapturedExecutionInput)
            │  effective content · Active Fields · deterministic operations
            │  direct C1~C10 structural admission (fail-closed)
            │  (compile_candidate — 순수, "fence 밖"으로 이미 문서화됨)
            ▼
    immutable SealedExecutionPlan **value**

**이 모듈이 하지 않는 것(R1 금지 목록):** store·ledger·registry·Profile abstraction·HMAC token·
digest hierarchy·contract manifest·global execution_generation·history/replay·MaterializationRun·
PreparedBatch persistence 를 **새로 만들지 않는다**. 기존 ProfileFence·theorem registry·Plan store
도 **삭제하지 않는다** — 이 R1 은 추출만 하고 철거는 R2 소유다.

**SealedExecutionPlan 의 제품 의미는 유지**하되 durable aggregate 가 아니라 exact durable
authority 에서 재계산 가능한 **record-independent immutable value** 로 취급한다: 같은 authority 는
같은 Plan 을 낳고(결정적), Plan store 없이도 authority 만으로 재계산된다.

**PerWorkFence 는 여전히 capture 단계(store 에서 exact authority 를 읽는 runner)의 계약**이다 —
이 kernel 은 그 fence 아래에서 이미 확정된 exact authority 를 소비하는 순수 재계산이라 fence 를
쥐지도, 우회하지도 않는다(#740 방향 3 보존).
"""

from __future__ import annotations

from dataclasses import dataclass

from hwpxfiller.application.execution_capture import (
    CapturedExecutionInput,
    CapturedFieldBinding,
    CapturedSelection,
    CapturedTemplateExecutionInput,
    ResolvedSealPolicy,
    judge_captured_execution,
)
from hwpxfiller.application.execution_contract_set import (
    ExecutionBasis,
    SealedExecutionPlanSemanticPayload,
)
from hwpxfiller.application.field_binding_input import FieldBindingInput
from hwpxfiller.application.seal_execution_plan import (
    BlockedCandidate,
    PlanCandidate,
    compile_candidate,
)
from hwpxfiller.application.slot_selection_input import SlotSelectionInput


class SemanticKernelContextError(Exception):
    """authority 로 실행 의미를 계산할 수 없다 — user-fixable blocker 가 아니라 context/무결성/
    미지원 구현 실패다. fail-closed: latest/default 로 풀지 않고 시끄럽게 raise 한다.

    ``cause_code`` 는 원인 계산층(capture context error·composition premise·compile context)이 낸
    코드를 **불투명하게** 되싣는다 — kernel 은 그 어휘 구조를 재조립하지 않는다.
    """

    def __init__(self, message: str, *, cause_code: str = "") -> None:
        super().__init__(message)
        self.cause_code = cause_code


@dataclass(frozen=True)
class DurableExecutionAuthority:
    """kernel 입력 — Plan 재계산에 필요한 exact durable Work authority 하나.

    이미 확정된 durable authority DTO 를 담는다(store·fence 없이). 필드는 전부 exact 값이고
    kernel 은 여기서 아무 것도 다시 조회하지 않는다.

    - ``template``      : exact applied Candidate + historical Qualification meaning
                          (PASS Evidence·profile semantic payload·structure projection 포함)
    - ``selection``     : Work-local Slot Selection intent
    - ``field_binding`` : Field Binding authority
    - ``resolved_seal_policy`` : 서버가 resolve 한 exact contract/version 집합(값 모델)
    """

    workspace_instance_id: str
    work_authority_id: str
    expected_template_application_id: str
    expected_profile_id: str
    resolved_seal_policy: ResolvedSealPolicy
    template: CapturedTemplateExecutionInput
    selection: SlotSelectionInput
    field_binding: FieldBindingInput
    captured_at: str


@dataclass(frozen=True)
class SealedExecutionPlanValue:
    """재계산 가능한 record-independent immutable Sealed Execution Plan value.

    durable aggregate 가 아니다 — store ref·first-seen·request id·digest history 를 싣지 않는다.
    제품 의미(exact basis·effective content·Active Fields·ordered operations·composition 통과
    사실)는 ``plan_payload`` 와 ``execution_basis`` 가 그대로 진다. 두 필드는 기존 검증된
    :func:`compile_candidate` 산출물을 **그대로** 담는다(재조립·재판정 0).
    """

    qualification_profile_id: str
    template_application_id: str
    execution_basis: ExecutionBasis
    plan_payload: SealedExecutionPlanSemanticPayload

    @property
    def active_field_requirements(self) -> tuple:
        """Active Field 요구 — parity 비교의 실행 의미 축(effective content 투영)."""
        return self.plan_payload.active_field_requirements

    @property
    def ordered_operations(self) -> tuple:
        """deterministic operations — RemoveOption + ApplyFieldBinding 정렬열."""
        return self.plan_payload.ordered_operations


@dataclass(frozen=True)
class SealedExecutionPlanBlocked:
    """composition 은 통과했으나 Active Field/구성 blocker 로 Plan 이 없다 — user-fixable.

    fail-closed 의 정상 갈래다(context error 아님): 사용자가 구성/Binding 을 고치면 Plan 이
    생긴다. blocker 코드는 링1/도메인이 낸 값을 불투명하게 되싣는다(문안 조립은 Presentation).
    """

    qualification_profile_id: str
    template_application_id: str
    normalized_blockers: tuple[str, ...]


KernelResult = SealedExecutionPlanValue | SealedExecutionPlanBlocked


def compute_execution_snapshot(
    authority: DurableExecutionAuthority,
) -> CapturedExecutionInput:
    """exact durable authority → exact execution snapshot(순수).

    기존 검증된 :func:`judge_captured_execution` 을 그대로 부른다. authority 는 이미 확정된
    exact 값이라 selection/binding 은 :class:`CapturedSelection`/:class:`CapturedFieldBinding`
    으로 감싸 넘긴다(store 에서 blocked 관찰을 만드는 것은 runner 몫). complete
    ``CapturedExecutionInput`` 이 아니면(context error·domain block·policy block) fail-closed
    로 raise 한다 — kernel 은 이 R1 에서 durable, already-exact authority 만 다룬다.
    """
    result = judge_captured_execution(
        workspace_instance_id=authority.workspace_instance_id,
        work_authority_id=authority.work_authority_id,
        expected_template_application_id=authority.expected_template_application_id,
        expected_profile_id=authority.expected_profile_id,
        resolved_seal_policy=authority.resolved_seal_policy,
        template=authority.template,
        selection_observation=CapturedSelection(authority.selection),
        field_binding_observation=CapturedFieldBinding(authority.field_binding),
        captured_at=authority.captured_at,
        policy_block=None,
    )
    if isinstance(result, CapturedExecutionInput):
        return result
    # 미완성 갈래(context error / domain block / policy block)는 latest 로 풀지 않는다.
    code = getattr(result, "code", "") or getattr(result, "policy_code", "")
    detail = getattr(result, "detail", "") or type(result).__name__
    raise SemanticKernelContextError(
        f"durable authority 로 execution snapshot 을 확정하지 못했다: {detail}",
        cause_code=str(code),
    )


def compute_sealed_execution_plan(authority: DurableExecutionAuthority) -> KernelResult:
    """exact durable authority → immutable SealedExecutionPlan value(순수, control plane 밖).

    경로: capture snapshot → 기존 :func:`compile_candidate`(C1~C10 direct admission + effective
    content/Active Field/deterministic operation compile + Sealed Plan value 구성). store·ledger·
    fingerprint·profile admission·fence 를 **쥐지 않는다**.

    반환:
      - :class:`SealedExecutionPlanValue` — sealable Plan value.
      - :class:`SealedExecutionPlanBlocked` — user-fixable Active Field/구성 blocker(Plan 없음).
    raise:
      - :class:`SemanticKernelContextError` — C1~C10 위반·context·미지원 구현(fail-closed, Plan 없음).

    theorem evidence registry 는 공개 API 에서 노출하지 않는다 — C1~C10 이 TOUCHING·owner
    coincidence gate 를 열 때 쓰는 legacy registry 사용은 :func:`compile_candidate` 안에 숨은
    **private implementation detail** 이다(R2 첫 절개 대상 = 이 theorem runtime 결합 제거).
    미등록/미지원 contract 는 :func:`compile_candidate` 가 fail-closed 로 raise 한다.
    """
    snapshot = compute_execution_snapshot(authority)
    try:
        candidate = compile_candidate(snapshot)
    except Exception as exc:
        # compile 층의 attempt(미지원 구현·context·composition premise 실패)를 그대로 fail-closed.
        raise SemanticKernelContextError(
            f"execution semantic compile 실패: {exc}",
            cause_code=getattr(exc, "cause_code", "") or type(exc).__name__,
        ) from exc
    if isinstance(candidate, BlockedCandidate):
        return SealedExecutionPlanBlocked(
            qualification_profile_id=candidate.qualification_profile_id,
            template_application_id=candidate.template_application_id,
            normalized_blockers=candidate.normalized_blockers,
        )
    assert isinstance(candidate, PlanCandidate)  # compile_candidate 합타입의 잔여 갈래
    return SealedExecutionPlanValue(
        qualification_profile_id=candidate.qualification_profile_id,
        template_application_id=candidate.template_application_id,
        execution_basis=candidate.execution_basis,
        plan_payload=candidate.plan_payload,
    )
