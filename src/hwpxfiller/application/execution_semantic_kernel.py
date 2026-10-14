"""Compute the canonical sealed execution plan from exact captured Work authority.

The kernel checks the supported composition/native primitive pair and C1~C10
structural facts, then compiles effective content and deterministic operations.
It has no store, registry, or native mutation dependency. The legacy serialized
composition fingerprint remains part of captured policy and plan payload identity.
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
    COMPOSITION_POLICY_IDENTITY_MISMATCH,
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
from hwpxfiller.application.execution_contract_set import (
    ExecutionBasis,
    ExecutionBasisIntegrityError,
    ExecutionContractSetIntegrityError,
    ExecutionPlanIntegrityError,
    SealedExecutionPlanSemanticPayload,
    UnsupportedPlanSchemaError,
    build_execution_contract_set,
    build_sealed_plan,
    qualification_profile_semantic_digest,
    verify_sealed_plan_integrity,
)
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
class SealedExecutionPlanBlocked:
    """composition 은 통과했으나 Active Field/구성 blocker 로 Plan 이 없다 — user-fixable.

    fail-closed 의 정상 갈래다(context error 아님): 사용자가 구성/Binding 을 고치면 Plan 이
    생긴다. blocker 코드는 링1/도메인이 낸 값을 불투명하게 되싣는다(문안 조립은 Presentation).
    """

    qualification_profile_id: str
    template_application_id: str
    normalized_blockers: tuple[str, ...]


KernelResult = SealedExecutionPlanSemanticPayload | SealedExecutionPlanBlocked


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


def _build_execution_basis(
    captured: CapturedExecutionInput, compiled: QualifiedExecutionCompilation
) -> ExecutionBasis:
    """Capture와 compile 결과에서 물질화와 digest가 공유하는 basis를 한 번 조립한다."""
    policy = captured.resolved_seal_policy
    contracts = build_execution_contract_set(
        slot_selection_contract_id=captured.selection.selection_semantic_contract_id,
        field_binding_contract_id=captured.field_binding.field_binding_semantic_contract_id,
        raw_record_contract_id=policy.raw_record_contract_id,
        source_schema_contract_id=captured.field_binding.source_schema_contract_id,
        execution_semantic_contract_id=policy.execution_semantic_contract_id,
        binding_value_contract_id=policy.binding_value_contract_id,
        record_validation_contract_id=policy.record_validation_contract_id,
        record_review_contract_id=policy.record_review_contract_id,
        document_value_resolution_contract_id=policy.document_value_resolution_contract_id,
        composition_contract_id=policy.composition_contract_id,
        native_primitive_contract_id=policy.native_primitive_contract_id,
        materialization_base_contract_id=policy.materialization_base_contract_id,
        materialization_contract_id=policy.materialization_contract_id,
        composition_theorem_evidence_manifest_digest=(
            policy.composition_theorem_evidence_manifest_digest
        ),
    )
    return ExecutionBasis(
        workspace_instance_id=captured.workspace_instance_id,
        work_authority_id=captured.work_authority_id,
        qualification_profile_semantic_digest=qualification_profile_semantic_digest(
            captured.template.qualification.qualification_profile_semantic_payload
        ),
        template=compiled.exact_template_execution_basis,
        contracts=contracts,
        selection=compiled.effective_selection_basis,
        field_binding=compiled.effective_field_binding_basis,
    )


def _require_supported_plan_identity(policy: ResolvedSealPolicy) -> None:
    """지원하지 않는 판본을 현재 지원 판본으로 풀지 않는다."""
    if policy.plan_schema_version not in _SUPPORTED_PLAN_SCHEMAS:
        raise SemanticKernelContextError(f"미지원 plan schema: {policy.plan_schema_version!r}")
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION:
        raise SemanticKernelContextError(
            f"미지원 canonical encoding: {policy.canonical_encoding_version!r}"
        )


def compile_sealed_plan_from_snapshot(captured: CapturedExecutionInput) -> KernelResult:
    """Exact capture에서 단일 봉인 계획을 순수 계산한다."""
    policy = captured.resolved_seal_policy
    qual = captured.template.qualification
    applied = captured.template.applied
    structure = qual.execution_structure
    _require_supported_plan_identity(policy)

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

    # (3) 물질화·현재성·저장 codec이 함께 쓰는 정확한 Plan 조립.
    semantic_payload = compiled.execution_basis_semantic_payload
    try:
        plan = build_sealed_plan(
            execution_basis=_build_execution_basis(captured, compiled),
            active_field_requirements=semantic_payload["active_field_requirements"],
            ordered_operations=semantic_payload["ordered_operations"],
            plan_schema_version=policy.plan_schema_version,
            canonical_encoding_version=policy.canonical_encoding_version,
        )
        verify_sealed_plan_integrity(plan, supported_plan_schemas=_SUPPORTED_PLAN_SCHEMAS)
    except (
        ExecutionBasisIntegrityError,
        ExecutionContractSetIntegrityError,
        ExecutionPlanIntegrityError,
        UnsupportedPlanSchemaError,
    ) as exc:
        raise SemanticKernelContextError(str(exc)) from exc
    return plan


def compute_sealed_execution_plan(authority: DurableExecutionAuthority) -> KernelResult:
    """exact durable authority → immutable canonical sealed plan(순수, control plane 밖).

    경로: capture snapshot → :func:`compile_sealed_plan_from_snapshot`(C1~C10 direct admission +
    effective content/Active Field/deterministic operation compile + canonical payload 조립).
    store·ledger·profile admission·fence·registry 를 쥐지 않는다.

    반환:
      - :class:`SealedExecutionPlanSemanticPayload` — sealable Plan.
      - :class:`SealedExecutionPlanBlocked` — user-fixable Active Field/구성 blocker(Plan 없음).
    raise:
      - :class:`SemanticKernelContextError` — C1~C10 위반·context·미지원 구현(fail-closed, Plan 없음).
    """
    snapshot = compute_execution_snapshot(authority)
    return compile_sealed_plan_from_snapshot(snapshot)
