"""S5F-01(#740) execution semantic kernel — control-plane 없이 실행 의미를 계산한다.

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
    immutable SealedExecutionPlan **value**(closed contract manifest 없음)

**R2-01(#740) — theorem runtime bureaucracy 결합 제거:** C1~C10 admission 은 registry 를 consult
하지 않는 :func:`admit_composition_premises` 로 한다. theorem corpus 는 classifier correctness 를
증명하는 **test evidence** 로만 남는다(runtime authority 아님).

**R2-02(#740) — closed contract manifest 결합 제거:** kernel 은 13-role :class:`ExecutionContractSet`
(closed manifest + manifest digest + schema)을 **전혀 만들지도 싣지도 않는다**. 실제 저장소에서
contract id 를 deref 하는 compilation/validation/delivery 소비자가 읽는 semantics 만
:class:`ExecutionContractSemantics` 작은 값으로 담는다. 기존 ExecutionContractSet 은 legacy caller
용 **compatibility shell** 로 그대로 둔다(이 절개는 삭제하지 않는다).

**R2-03(#740) — semantic identity digest 비의존:** kernel 의 correctness·identity 는 explicit
semantic value(qualification_profile_id·contract semantics·exact bases·Active Field 요구·ordered
operations)로 정의되고, ``qualification_profile_semantic_digest``·``execution_basis_digest``·
``plan_semantic_digest`` 를 correctness dependency 로 **쓰지도 싣지도 않는다**(R2-02 에서
ExecutionBasis·plan_payload 를 걷어내며 이미 제거됨 — R2-03 이 명시·검증·고정). 두 값 비교(같음/다름)는
그 셋 digest 가 아니라 explicit value 로 갈린다. 그 digest 함수와 legacy identity 경로는 **삭제하지
않는다** — store/seal/reference consumer 가 compatibility layer 에서 계속 쓴다. 새 fingerprint·
counter·identity 를 만들지 않는다.

**이 모듈이 하지 않는 것:** store·ledger·registry·Profile abstraction·HMAC token·digest
hierarchy·contract manifest·global execution_generation·history/replay·MaterializationRun·
PreparedBatch persistence 를 **새로 만들지 않는다**. ProfileFence·theorem registry·Plan store·
semantic digest 전면 제거는 이 절개에서 건드리지 않는다. SealedExecutionPlan 의 제품 의미는
유지하되 durable aggregate 가 아니라 exact durable authority 에서 재계산 가능한
**record-independent immutable value** 로 취급한다.

**PerWorkFence 는 여전히 capture 단계(store 에서 exact authority 를 읽는 runner)의 계약**이다 —
이 kernel 은 그 fence 아래에서 이미 확정된 exact authority 를 소비하는 순수 재계산이라 fence 를
쥐지도, 우회하지도 않는다(#740 방향 3 보존).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hwpxfiller.application.execution_capture import (
    CapturedExecutionInput,
    CapturedFieldBinding,
    CapturedSelection,
    CapturedTemplateExecutionInput,
    EffectiveSelectionBasis,
    ExactTemplateExecutionBasis,
    ResolvedSealPolicy,
    judge_captured_execution,
)
from hwpxfiller.application.execution_compilation import (
    EffectiveFieldBindingBasis,
    ExecutionCompilationContextError,
    ExecutionQualificationBlocked,
    QualifiedExecutionCompilation,
    qualify_and_compile_execution,
)
from hwpxfiller.application.execution_composition import (
    CompositionAdmissionError,
    CompositionPremisesPassed,
    admit_composition_premises,
    resolve_native_primitive_contract,
)
from hwpxfiller.application.execution_contract_semantics import ExecutionContractSemantics
from hwpxfiller.application.execution_contract_set import canonicalize_execution_operations
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
    """재계산 가능한 record-independent immutable Sealed Execution Plan value(closed manifest 없음).

    R2-02: 13-role closed :class:`ExecutionContractSet` 을 싣지 않는다 — 실제 소비되는 contract
    semantics 만 :class:`ExecutionContractSemantics` 로 담는다. 나머지 제품 의미(exact template/
    selection/binding basis · Active Field 요구 · deterministic operations)는 compilation 산출
    그대로다. durable aggregate 가 아니다 — store ref·first-seen·request id·manifest digest 를 싣지
    않는다.
    """

    qualification_profile_id: str
    template_application_id: str
    contract_semantics: ExecutionContractSemantics
    exact_template_execution_basis: ExactTemplateExecutionBasis
    effective_selection_basis: EffectiveSelectionBasis
    effective_field_binding_basis: EffectiveFieldBindingBasis
    active_field_requirements: tuple[Mapping[str, Any], ...]
    ordered_operations: tuple[Mapping[str, Any], ...]
    plan_schema_version: str
    canonical_encoding_version: str


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


def _build_contract_semantics(captured: CapturedExecutionInput) -> ExecutionContractSemantics:
    """실제 소비되는 contract semantics 만 뽑은 작은 값(closed manifest 없음).

    필드 출처는 legacy contract-set 조립과 동일하다(raw_record 는 policy, source_schema 는 field
    binding). materialization base contract 의 admitted-base fail-closed 는 이미 capture 판정
    (:func:`judge_captured_execution`)이 상류에서 진다 — 여기서 재검하지 않는다(중복 방지). 모든
    역할의 nonempty 는 :class:`ExecutionContractSemantics` __post_init__ 이 강제한다.
    """
    policy = captured.resolved_seal_policy
    return ExecutionContractSemantics(
        raw_record_contract_id=policy.raw_record_contract_id,
        source_schema_contract_id=captured.field_binding.source_schema_contract_id,
        binding_value_contract_id=policy.binding_value_contract_id,
        record_validation_contract_id=policy.record_validation_contract_id,
        record_review_contract_id=policy.record_review_contract_id,
        document_value_resolution_contract_id=policy.document_value_resolution_contract_id,
        composition_contract_id=policy.composition_contract_id,
        native_primitive_contract_id=policy.native_primitive_contract_id,
        materialization_base_contract_id=policy.materialization_base_contract_id,
        materialization_contract_id=policy.materialization_contract_id,
    )


def compile_sealed_plan_from_snapshot(captured: CapturedExecutionInput) -> KernelResult:
    """exact snapshot → Sealed Plan value(순수, theorem registry·closed manifest 미사용).

    :func:`compile_candidate` 와 같은 실행 의미를 내되 (R2-01) theorem runtime bureaucracy 와
    (R2-02) closed contract manifest 를 kernel 경로에서 제거한다: C1~C10 admission 은
    :func:`admit_composition_premises`(registry 없음), contract semantics 는
    :class:`ExecutionContractSemantics` 작은 값, operation 정본화는 legacy plan payload 와 공유하는
    :func:`canonicalize_execution_operations` 단일 출처로 한다.
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

    # (1) direct C1~C10 structural admission — theorem registry 미consult. native primitive 는
    # policy 가 선언한 것을 **표에서 푼다**(S10-04 #861): 상수를 박으면 TXT Plan 이 HWPX
    # primitive 로 증명돼 조용히 틀린다. 미등록 id 는 latest 로 풀지 않고 fail-closed.
    try:
        native_primitive = resolve_native_primitive_contract(
            policy.native_primitive_contract_id
        )
    except CompositionAdmissionError as exc:
        raise SemanticKernelContextError(str(exc), cause_code=exc.code) from exc
    admitted = admit_composition_premises(
        structure=structure,
        native_primitive_contract=native_primitive,
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

    # (3) 작은 contract semantics + canonical operations — closed manifest 없이 Plan value 조립.
    contract_semantics = _build_contract_semantics(captured)
    semantic_payload = compiled.execution_basis_semantic_payload
    reqs, ops = canonicalize_execution_operations(
        semantic_payload["active_field_requirements"],
        semantic_payload["ordered_operations"],
    )
    return SealedExecutionPlanValue(
        qualification_profile_id=qual.qualification_profile_id,
        template_application_id=applied.template_application_id,
        contract_semantics=contract_semantics,
        exact_template_execution_basis=compiled.exact_template_execution_basis,
        effective_selection_basis=compiled.effective_selection_basis,
        effective_field_binding_basis=compiled.effective_field_binding_basis,
        active_field_requirements=reqs,
        ordered_operations=ops,
        plan_schema_version=policy.plan_schema_version,
        canonical_encoding_version=policy.canonical_encoding_version,
    )


def compute_sealed_execution_plan(authority: DurableExecutionAuthority) -> KernelResult:
    """exact durable authority → immutable SealedExecutionPlan value(순수, control plane 밖).

    경로: capture snapshot → :func:`compile_sealed_plan_from_snapshot`(C1~C10 direct admission +
    effective content/Active Field/deterministic operation compile + Sealed Plan value 조립). store·ledger·
    fingerprint·profile admission·fence·theorem registry·closed contract manifest 를 **쥐지 않는다**.

    반환:
      - :class:`SealedExecutionPlanValue` — sealable Plan value.
      - :class:`SealedExecutionPlanBlocked` — user-fixable Active Field/구성 blocker(Plan 없음).
    raise:
      - :class:`SemanticKernelContextError` — C1~C10 위반·context·미지원 구현(fail-closed, Plan 없음).
    """
    snapshot = compute_execution_snapshot(authority)
    return compile_sealed_plan_from_snapshot(snapshot)
