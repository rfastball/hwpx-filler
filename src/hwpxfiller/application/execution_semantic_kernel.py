"""S5F-01(#740 R1) execution semantic kernel — control-plane 없이 실행 의미를 계산한다.

두 차례 Architecture Falsification Audit 는 S5 의 semantic compiler/validator 는 유지하되
`SealedExecutionPlan` 을 둘러싼 durable proof/control plane(store·ledger·first-seen·profile
admission·ProfileFence·theorem registry authority·13-role manifest digest lattice)이 현재 v1
topology 에 과대하다고 판정했다. 이 모듈은 그 판정의 실물 조치다: 기존에 검증된 순수 계산만
조립해 다음 경로를 control plane 밖으로 독립시킨다.

    exact durable Work authority
            │  (judge_captured_execution — 순수, store·fence·token 모름)
            ▼
    exact execution snapshot(CapturedExecutionInput)
            │  direct C1~C10 structural admission (fail-closed, theorem registry 미consult)
            │  effective content · Active Fields · deterministic operations
            │  (admit_composition_premises + qualify_and_compile_execution — 순수)
            ▼
    immutable SealedExecutionPlan **value**

**R2-01(#740) 첫 절개 — theorem runtime bureaucracy 와 semantic kernel 의 결합 제거:** kernel 은
더 이상 :func:`compile_candidate` 를 거치지 않는다. C1~C10 admission 은 registry 를 consult 하지
않는 :func:`admit_composition_premises` 로, contract set 은
``build_execution_contract_set(theorem_registry=None)`` opt-out 으로 조립한다 — theorem evidence
manifest digest 는 policy 가 든 값을 그대로 싣는다(등록 canonical 과 byte 동일). theorem
registry/manifest integrity 의 runtime consult 는 kernel 경로에서 **사라졌다**. theorem corpus 는
classifier correctness 를 증명하는 **test evidence** 로만 남는다(runtime authority 아님).

**이 모듈이 하지 않는 것:** store·ledger·registry·Profile abstraction·HMAC token·digest
hierarchy·contract manifest·global execution_generation·history/replay·MaterializationRun·
PreparedBatch persistence 를 **새로 만들지 않는다**. 기존 ProfileFence·theorem registry·Plan store
도 **삭제하지 않는다**(다른 mechanism 은 별도 절개 소유). SealedExecutionPlan 의 제품 의미는
유지하되 durable aggregate 가 아니라 exact durable authority 에서 재계산 가능한
**record-independent immutable value** 로 취급한다.

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
from hwpxfiller.application.execution_compilation import (
    ExecutionCompilationContextError,
    ExecutionQualificationBlocked,
    QualifiedExecutionCompilation,
    qualify_and_compile_execution,
)
from hwpxfiller.application.execution_composition import (
    NATIVE_PRIMITIVE_CONTRACT_V1,
    CompositionPremisesPassed,
    admit_composition_premises,
)
from hwpxfiller.application.execution_contract_set import (
    ExecutionBasis,
    SealedExecutionPlanSemanticPayload,
    build_execution_contract_set,
    build_sealed_plan,
    qualification_profile_semantic_digest,
    verify_execution_basis_integrity,
)
from hwpxfiller.application.field_binding_input import FieldBindingInput
from hwpxfiller.application.slot_selection_input import SlotSelectionInput
from hwpxfiller.domain.canonical_execution_encoding import CANONICAL_ENCODING_VERSION

# plan schema identity — kernel 이 fail-closed 로 아는 supported 값(단일 shipping v1). 미지원은 latest
# 로 풀지 않는다. seal_execution_plan.SUPPORTED_PLAN_SCHEMAS 와 같은 값이되, 그 모듈을 import 하면
# theorem/store 결합이 되살아나므로 kernel 은 이 identity 만 지역 상수로 둔다(R2-01 결합 제거).
_SUPPORTED_PLAN_SCHEMAS = ("hwpx-execution-plan/v1",)


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
    사실)는 ``plan_payload`` 와 ``execution_basis`` 가 그대로 진다.
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


def _compile_sealed_plan_value(captured: CapturedExecutionInput) -> KernelResult:
    """exact snapshot → Sealed Plan value(순수, theorem registry 미consult).

    :func:`compile_candidate` 와 같은 실행 의미를 내되 theorem runtime bureaucracy(registry
    resolve·manifest integrity·digest match) 를 kernel 경로에서 제거한다:
      - C1~C10 admission 은 :func:`admit_composition_premises`(registry 없음).
      - contract set 은 ``build_execution_contract_set(theorem_registry=None)``(digest opaque).
    theorem evidence manifest digest 는 policy 가 든 값(등록 canonical 과 동일)이라 결과
    ExecutionBasis·Plan payload 는 registry 검증 경로와 **byte 동일**하다(semantic parity).
    """
    policy = captured.resolved_seal_policy
    qual = captured.template.qualification
    applied = captured.template.applied
    structure = qual.execution_structure

    # 지원 plan schema·encoding fail-closed(미지원은 latest 로 풀지 않는다).
    if policy.plan_schema_version not in _SUPPORTED_PLAN_SCHEMAS:
        raise SemanticKernelContextError(f"미지원 plan schema: {policy.plan_schema_version!r}")
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION:
        raise SemanticKernelContextError(
            f"미지원 canonical encoding: {policy.canonical_encoding_version!r}"
        )

    # (1) direct C1~C10 structural admission — theorem registry 미consult.
    admitted = admit_composition_premises(
        structure=structure,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence_manifest_digest=policy.composition_theorem_evidence_manifest_digest,
        composition_contract_id=policy.composition_contract_id,
        theorem_capability_available=True,
    )
    if not isinstance(admitted, CompositionPremisesPassed):
        # C1~C10 INCOMPLETE(ContextError) / FAILED(Blocked) — 둘 다 fail-closed(Plan 없음).
        premise = getattr(admitted, "premise_id", None)
        reason = getattr(admitted, "reason", type(admitted).__name__)
        raise SemanticKernelContextError(
            f"C1~C10 structural admission 실패(premise={premise}): {reason}",
            cause_code=getattr(admitted, "code", "") or type(admitted).__name__,
        )

    # (2) effective content · Active Fields · deterministic operations(순수 compile).
    compiled = qualify_and_compile_execution(captured=captured, composition_result=admitted)
    if isinstance(compiled, ExecutionCompilationContextError):
        raise SemanticKernelContextError(
            f"execution compile context error({compiled.code}): {compiled.detail}",
            cause_code=compiled.code,
        )
    if isinstance(compiled, ExecutionQualificationBlocked):
        return SealedExecutionPlanBlocked(
            qualification_profile_id=qual.qualification_profile_id,
            template_application_id=applied.template_application_id,
            normalized_blockers=tuple(b.code for b in compiled.normalized_blockers),
        )
    assert isinstance(compiled, QualifiedExecutionCompilation)

    # (3) contract set + basis + Sealed Plan value — theorem_registry=None(opt-out).
    contracts = build_execution_contract_set(
        slot_selection_contract_id=captured.selection.selection_semantic_contract_id,
        field_binding_contract_id=captured.field_binding.field_binding_semantic_contract_id,
        source_schema_contract_id=captured.field_binding.source_schema_contract_id,
        raw_record_contract_id=policy.raw_record_contract_id,
        execution_semantic_contract_id=policy.execution_semantic_contract_id,
        binding_value_contract_id=policy.binding_value_contract_id,
        document_value_resolution_contract_id=policy.document_value_resolution_contract_id,
        record_validation_contract_id=policy.record_validation_contract_id,
        record_review_contract_id=policy.record_review_contract_id,
        composition_contract_id=policy.composition_contract_id,
        native_primitive_contract_id=policy.native_primitive_contract_id,
        materialization_base_contract_id=policy.materialization_base_contract_id,
        materialization_contract_id=policy.materialization_contract_id,
        composition_theorem_evidence_manifest_digest=(
            policy.composition_theorem_evidence_manifest_digest
        ),
        theorem_registry=None,
    )
    basis = ExecutionBasis(
        workspace_instance_id=captured.workspace_instance_id,
        work_authority_id=captured.work_authority_id,
        qualification_profile_semantic_digest=qualification_profile_semantic_digest(
            qual.qualification_profile_semantic_payload
        ),
        template=compiled.exact_template_execution_basis,
        contracts=contracts,
        selection=compiled.effective_selection_basis,
        field_binding=compiled.effective_field_binding_basis,
    )
    verify_execution_basis_integrity(basis)
    semantic_payload = compiled.execution_basis_semantic_payload
    plan_payload = build_sealed_plan(
        execution_basis=basis,
        active_field_requirements=semantic_payload["active_field_requirements"],
        ordered_operations=semantic_payload["ordered_operations"],
        plan_schema_version=policy.plan_schema_version,
        canonical_encoding_version=policy.canonical_encoding_version,
    )
    return SealedExecutionPlanValue(
        qualification_profile_id=qual.qualification_profile_id,
        template_application_id=applied.template_application_id,
        execution_basis=basis,
        plan_payload=plan_payload,
    )


def compute_sealed_execution_plan(authority: DurableExecutionAuthority) -> KernelResult:
    """exact durable authority → immutable SealedExecutionPlan value(순수, control plane 밖).

    경로: capture snapshot → :func:`_compile_sealed_plan_value`(C1~C10 direct admission + effective
    content/Active Field/deterministic operation compile + Sealed Plan value 조립). store·ledger·
    fingerprint·profile admission·fence·theorem registry 를 **쥐지 않는다**.

    반환:
      - :class:`SealedExecutionPlanValue` — sealable Plan value.
      - :class:`SealedExecutionPlanBlocked` — user-fixable Active Field/구성 blocker(Plan 없음).
    raise:
      - :class:`SemanticKernelContextError` — C1~C10 위반·context·미지원 구현(fail-closed, Plan 없음).
    """
    snapshot = compute_execution_snapshot(authority)
    return _compile_sealed_plan_value(snapshot)
