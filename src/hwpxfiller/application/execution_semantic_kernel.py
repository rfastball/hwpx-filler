"""Compute a sealed execution plan value from exact captured Work authority.

The kernel checks the supported composition/native primitive pair and C1~C10
structural facts, then compiles effective content and deterministic operations.
It has no store, registry, or native mutation dependency. The legacy serialized
composition fingerprint remains part of captured policy and plan payload identity.
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
    COMPOSITION_POLICY_IDENTITY_MISMATCH,
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
    composition_fingerprint,
    resolve_native_primitive_contract,
)
from hwpxfiller.application.execution_contract_semantics import ExecutionContractSemantics
from hwpxfiller.application.execution_contract_set import canonicalize_execution_operations
from hwpxfiller.application.field_binding_input import FieldBindingInput
from hwpxfiller.application.slot_selection_input import SlotSelectionInput
from hwpxfiller.domain.canonical_execution_encoding import CANONICAL_ENCODING_VERSION

# plan schema identity — kernel 이 fail-closed 로 아는 supported 값(단일 shipping v2).
_SUPPORTED_PLAN_SCHEMAS = ("hwpx-execution-plan/v2",)


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
    """exact snapshot → Sealed Plan value(순수, registry·closed manifest 미사용).

    :func:`compile_candidate` 와 같은 실행 의미를 내되 closed contract manifest 를
    kernel 경로에서 만들지 않는다: C1~C10 admission 은
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

    # (1) direct C1~C10 structural admission. native primitive 는
    # policy 가 선언한 것을 **표에서 푼다**(S10-04 #861): 상수를 박으면 TXT Plan 이 HWPX
    # primitive 로 증명돼 조용히 틀린다. 미등록 id 는 latest 로 풀지 않고 fail-closed.
    try:
        native_primitive = resolve_native_primitive_contract(
            policy.native_primitive_contract_id
        )
        fingerprint = composition_fingerprint(
            policy.composition_contract_id, policy.native_primitive_contract_id
        )
    except CompositionAdmissionError as exc:
        raise SemanticKernelContextError(str(exc), cause_code=exc.code) from exc
    if policy.composition_theorem_evidence_manifest_digest != fingerprint:
        raise SemanticKernelContextError(
            "composition fingerprint 가 resolved policy 와 불일치",
            cause_code=COMPOSITION_POLICY_IDENTITY_MISMATCH,
        )
    admitted = admit_composition_premises(
        structure=structure,
        native_primitive_contract=native_primitive,
        composition_contract_id=policy.composition_contract_id,
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
    profile admission·fence·registry·closed contract manifest 를 **쥐지 않는다**.

    반환:
      - :class:`SealedExecutionPlanValue` — sealable Plan value.
      - :class:`SealedExecutionPlanBlocked` — user-fixable Active Field/구성 blocker(Plan 없음).
    raise:
      - :class:`SemanticKernelContextError` — C1~C10 위반·context·미지원 구현(fail-closed, Plan 없음).
    """
    snapshot = compute_execution_snapshot(authority)
    return compile_sealed_plan_from_snapshot(snapshot)
