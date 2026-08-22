"""S5 exact execution capture 경계 — capture result algebra + applied-Candidate base (S5-02 #698).

S4 의 exact applied Template(:class:`~hwpxfiller.application.slot_configuration_context.ExactAppliedTemplateInput`)·
Slot Selection 합타입(:data:`~hwpxfiller.application.slot_selection_input.SlotSelectionInput`)과
S5-01 의 immutable Field Binding(:class:`~hwpxfiller.application.field_binding_input.FieldBindingInput`)을
**그대로 조합**해 S5 의 exact capture 경계를 만든다. 이 모듈은 그 세 계약을 재정의하지 않는다 —
composite DTO·cross-reference integrity rule·capture result 합타입·applied-Candidate base 고정만 소유한다.

경계(:mod:`slot_selection_input` 의 ``plan_capture`` 와 같은 규율):
- 순수하다. store·fence·token·wall-clock·HWPX 를 모른다. 시간은 caller 가 넘긴 ``captured_at`` 이다.
- fence 아래 context resolution 과 fence 획득은 S5-10(runner)이 진다. 이 모듈은 이미 복원된
  (template, selection, field binding, policy) 로 capture 판정만 한다.
- complete/domain/policy/context 결과를 **하나로 합치지 않는다** — 4-변형 합타입으로 가른다.
- confirm-or-alarm: unknown base/contract 는 latest 로 풀지 않고 시끄럽게 context error 로 닫는다.

S5 v1 execution base 는 applied Candidate 하나(:data:`APPLIED_TEMPLATE_CANDIDATE`)로 고정한다.
continuation(previous output document base)은 exact applied Candidate 가 아니라 policy block 이다.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Protocol

from hwpxfiller.application.execution_structure import (
    ExecutionTemplateStructure,
    template_structure_digest,
)
from hwpxfiller.application.field_binding_input import (
    NEEDS_BINDING_SEMANTIC_MIGRATION,
    NEEDS_FIELD_BINDING_APPLICATION_REVIEW,
    FieldBindingInput,
)
from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest
from hwpxfiller.application.slot_configuration_context import ExactAppliedTemplateInput
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
    SlotSelectionInput,
)
from hwpxfiller.domain.slot_selection import digest_selection_set
from hwpxfiller.application.work_bootstrap import (
    NEEDS_CONFIGURATION,
    NEEDS_CONFIGURATION_REVIEW,
)

# ─── execution base 어휘(S5 v1 admitted base 는 정확히 하나) ─────────────────────────
APPLIED_TEMPLATE_CANDIDATE = "APPLIED_TEMPLATE_CANDIDATE"
# legacy continuation 은 previous output document 를 mutation base 로 쓴다 — managed S5 base 가 아니다.
CONTINUATION_OUTPUT_DOCUMENT = "CONTINUATION_OUTPUT_DOCUMENT"
MATERIALIZATION_BASE_CONTRACT_ID = "applied-template-candidate-base/v1"

# S4 SlotSelectionInput → 실행 selection 의미의 pure projection 계약.
EXECUTION_SELECTION_SEMANTICS_CONTRACT = "execution-semantics/v1"
SLOTLESS = "SLOTLESS"
SLOTTED = "SLOTTED"

# ─── domain blocker 어휘(예 — 사용자가 구성/Binding 을 고쳐야 exact input 이 완성된다) ────
SLOT_CONFIGURATION_INCOMPLETE = "SLOT_CONFIGURATION_INCOMPLETE"
# NEEDS_CONFIGURATION / NEEDS_CONFIGURATION_REVIEW 는 work_bootstrap, binding 계열은 field_binding_input 재사용.

# ─── policy block 어휘 ────────────────────────────────────────────────────────────
QUALIFICATION_PROFILE_REVOKED = "QUALIFICATION_PROFILE_REVOKED"
EXECUTION_PROFILE_NOT_SEALABLE = "EXECUTION_PROFILE_NOT_SEALABLE"
EXECUTION_POLICY_NOT_ADMITTED = "EXECUTION_POLICY_NOT_ADMITTED"
CONTINUATION_BASE_NOT_SUPPORTED = "CONTINUATION_BASE_NOT_SUPPORTED"

# ─── context error 어휘(issue 열거 그대로) ─────────────────────────────────────────
APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR = "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"
QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR = (
    "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR"
)
SELECTION_CONTRACT_INTEGRITY_ERROR = "SELECTION_CONTRACT_INTEGRITY_ERROR"
FIELD_BINDING_INPUT_INTEGRITY_ERROR = "FIELD_BINDING_INPUT_INTEGRITY_ERROR"
UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION = "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION"
UNSUPPORTED_LOCAL_IMPLEMENTATION = "UNSUPPORTED_LOCAL_IMPLEMENTATION"
EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR = "EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR"


class ExecutionCaptureIntegrityError(ValueError):
    """DTO 조립 시 내부 무결성 위반 — 구조적으로 self-consistent 하지 않은 값은 만들지 않는다.

    cross-object mismatch(request↔template↔selection↔binding)는 예외가 아니라 result 합타입의
    :class:`ExecutionCaptureContextError` 로 낸다. 여기서 raise 하는 것은 **한 DTO 안의** 위반뿐이다.
    """


def _require_nonempty(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ExecutionCaptureIntegrityError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


# ─── Work route ↔ authority 역할 분리 ─────────────────────────────────────────────
@dataclass(frozen=True)
class WorkRouteRef:
    """Product route/display locator — **identity 가 아니다**.

    WorkAuthorityId(= Job.authority_id = DocumentWork.work_id = SlotSelectionInput.work_id)는
    별도의 immutable aggregate identity 다. route resolution ``(workspace_instance_id, work_ref)
    → WorkAuthorityId`` 은 caller(S5-10)가 기존 mapping 으로 조회한다 — 이 모듈은 **새 Work
    identity 를 발급하지 않는다**(durable mapping·generator 0).
    """

    workspace_instance_id: str
    work_ref: str


# ─── Qualification semantic payload(digest 가 식별해야 하는 semantic 집합) ─────────────
@dataclass(frozen=True)
class QualificationProfileSemanticPayload:
    """qualification_profile_semantic_digest 가 식별하는 exact semantic 집합.

    포함: profile id·media·adapter/product/operation/projection contract version·manifest payload.
    제외: created_at·store path/file envelope·runtime revocation state·현 구현 지원 여부. 현재 S3
    ``manifest_digest`` 를 전체 qualification semantics 의 digest 로 간주하지 않는다.
    """

    qualification_profile_id: str
    media: str
    adapter_contract_version: str
    product_rule_version: str
    operation_alphabet_version: str
    projection_schema_version: str
    manifest_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "qualification_profile_id",
            "media",
            "adapter_contract_version",
            "product_rule_version",
            "operation_alphabet_version",
            "projection_schema_version",
        ):
            _require_nonempty(getattr(self, name), name)
        # frozen dataclass 는 attribute 재바인딩만 막고 nested mapping/list 는 못 막는다 —
        # deep-copy 로 alias 를 완전히 끊어야 build 이후 caller 가 nested 값을 고쳐도 digest 가 안 흔들린다.
        object.__setattr__(
            self,
            "manifest_payload",
            MappingProxyType(copy.deepcopy(dict(self.manifest_payload))),
        )


@dataclass(frozen=True)
class ExactTemplateQualificationContext:
    """current Application 의 exact qualification context(재해석·재실행 없음).

    ``qualification_profile_semantic_digest`` 의 canonical byte 계산은 S5-06 소유다 — 여기서는
    digest 가 어떤 semantic payload 를 식별해야 하는지의 타입·integrity seam 만 닫는다.
    """

    pass_evidence_id: str
    qualification_profile_id: str
    qualification_profile_semantic_payload: QualificationProfileSemanticPayload
    structure_projection_schema_version: str
    template_structure_digest: str
    execution_structure: ExecutionTemplateStructure
    composition_profile_state: str
    # exact PASS Evidence 의 revision — applied Candidate 와 결속해 attestation 을 옮겨 붙지 못하게 한다.
    revision_id: str
    qualification_profile_semantic_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "pass_evidence_id",
            "qualification_profile_id",
            "structure_projection_schema_version",
            "template_structure_digest",
            "composition_profile_state",
            "revision_id",
        ):
            _require_nonempty(getattr(self, name), name)
        payload = self.qualification_profile_semantic_payload
        # 내부 정합: payload 는 자기 profile/schema 를 정확히 담아야 한다(위조 payload 차단).
        if payload.qualification_profile_id != self.qualification_profile_id:
            raise ExecutionCaptureIntegrityError(
                "semantic payload 의 profile id 가 qualification_profile_id 와 불일치"
            )
        if payload.projection_schema_version != self.structure_projection_schema_version:
            raise ExecutionCaptureIntegrityError(
                "semantic payload 의 projection schema 가 context 와 불일치"
            )
        # ExecutionTemplateStructure 는 타입상 v2 뿐이지만 context 의 선언 schema 와도 정합해야 한다.
        if (
            self.execution_structure.projection_schema_version
            != self.structure_projection_schema_version
        ):
            raise ExecutionCaptureIntegrityError(
                "execution_structure schema 가 context 선언 schema 와 불일치"
            )
        # template_structure_digest 는 claim 을 믿지 않고 execution_structure 에서 recompute·대조한다.
        recomputed = template_structure_digest(self.execution_structure)
        if recomputed != self.template_structure_digest:
            raise ExecutionCaptureIntegrityError(
                "template_structure_digest 가 execution_structure recompute 와 불일치"
            )


@dataclass(frozen=True)
class CapturedTemplateExecutionInput:
    """exact applied Template + qualification context 의 composite(같은 이름 재정의 아님).

    ``applied`` 은 S4 의 :class:`ExactAppliedTemplateInput` 을 **그대로** 담는다 — PASS Evidence/
    Profile/Structure 를 덧붙인 새 타입을 만들지 않는다.
    """

    workspace_instance_id: str
    work_authority_id: str
    applied: ExactAppliedTemplateInput
    qualification: ExactTemplateQualificationContext
    captured_at: str

    def __post_init__(self) -> None:
        _require_nonempty(self.workspace_instance_id, "workspace_instance_id")
        _require_nonempty(self.work_authority_id, "work_authority_id")
        _require_nonempty(self.captured_at, "captured_at")
        # work_authority_id == applied.work_id (four-way equality 의 template 쪽 anchor).
        if self.work_authority_id != self.applied.work_id:
            raise ExecutionCaptureIntegrityError(
                "work_authority_id 가 applied.work_id 와 불일치"
            )
        # qualification media 는 applied media 와 정합해야 한다(media cross-claim).
        payload = self.qualification.qualification_profile_semantic_payload
        if payload.media != self.applied.media:
            raise ExecutionCaptureIntegrityError(
                "qualification semantic payload media 가 applied media 와 불일치"
            )
        # PASS Evidence 는 exact applied revision 에 결속돼야 한다 — media 만 같은 다른 Candidate 에
        # 남의 attestation·구조 사실을 옮겨 붙지 못하게 한다(evidence↔candidate binding).
        if self.qualification.revision_id != self.applied.revision_id:
            raise ExecutionCaptureIntegrityError(
                "qualification revision_id 가 applied.revision_id 와 불일치"
            )


# ─── ResolvedSealPolicy(raw intent 와 서버가 resolve 한 exact policy 분리) ──────────────
@dataclass(frozen=True)
class ResolvedSealPolicy:
    """서버가 resolve 한 exact policy — raw request intent 가 아니다.

    S4 Selection·Field Binding 이 소유하는 contract ID 는 captured input 에서 온다. 최종
    ``ExecutionContractSet`` 합성은 S5-06 소유다 — 여기서는 policy 값 모델만 고정한다.
    """

    policy_resolution_version: str
    execution_base_kind: str
    execution_semantic_contract_id: str
    binding_value_contract_id: str
    raw_record_contract_id: str
    document_value_resolution_contract_id: str
    record_validation_contract_id: str
    record_review_contract_id: str
    composition_contract_id: str
    native_primitive_contract_id: str
    materialization_base_contract_id: str
    composition_theorem_evidence_manifest_digest: str
    materialization_contract_id: str
    plan_schema_version: str
    canonical_encoding_version: str

    def __post_init__(self) -> None:
        # 모든 contract identity/version/digest 는 nonempty — 누락된 계약을 capture 로 실어 나르지 않는다.
        for name in (
            "policy_resolution_version",
            "execution_base_kind",
            "execution_semantic_contract_id",
            "binding_value_contract_id",
            "raw_record_contract_id",
            "document_value_resolution_contract_id",
            "record_validation_contract_id",
            "record_review_contract_id",
            "composition_contract_id",
            "native_primitive_contract_id",
            "materialization_base_contract_id",
            "composition_theorem_evidence_manifest_digest",
            "materialization_contract_id",
            "plan_schema_version",
            "canonical_encoding_version",
        ):
            _require_nonempty(getattr(self, name), name)


@dataclass(frozen=True)
class ExactTemplateExecutionBasis:
    """S5 v1 execution base — applied Candidate 하나로 고정하고 두 계약 값을 명시적으로 담는다.

    의미: current WorkTemplateApplication → exact immutable Candidate bytes → Plan dependency →
    S6 materialization base. Job.template_path·mutable source·latest Candidate·raw HWPX path·
    legacy GenerationPlan.template·template_override·previous output document 는 base 가 아니다.
    """

    execution_base_kind: str
    materialization_base_contract_id: str
    work_authority_id: str
    template_application_id: str
    exact_content_digest: str
    canonical_blob_reference: str


def build_exact_execution_basis(
    template: CapturedTemplateExecutionInput, policy: ResolvedSealPolicy
) -> ExactTemplateExecutionBasis:
    """applied Candidate 를 exact execution base 로 고정한다(APPLIED_TEMPLATE_CANDIDATE 전용).

    base kind 나 materialization contract 가 admitted 값이 아니면 fail-closed 로 거절한다 —
    fallback 없음. 정상 경로는 mutable source·latest·template_override 를 읽지 않고 exact Candidate
    bytes(applied.exact_content_digest / canonical_blob_reference)만 base 로 삼는다.
    """
    if policy.execution_base_kind != APPLIED_TEMPLATE_CANDIDATE:
        raise ExecutionCaptureIntegrityError(
            f"S5 v1 admitted base 는 APPLIED_TEMPLATE_CANDIDATE 뿐: {policy.execution_base_kind!r}"
        )
    if policy.materialization_base_contract_id != MATERIALIZATION_BASE_CONTRACT_ID:
        raise ExecutionCaptureIntegrityError(
            f"materialization base contract 가 {MATERIALIZATION_BASE_CONTRACT_ID!r} 가 아니다"
        )
    return ExactTemplateExecutionBasis(
        execution_base_kind=APPLIED_TEMPLATE_CANDIDATE,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        work_authority_id=template.work_authority_id,
        template_application_id=template.applied.template_application_id,
        exact_content_digest=template.applied.exact_content_digest,
        canonical_blob_reference=template.applied.canonical_blob_reference,
    )


# ─── EffectiveSelectionBasis(S4 SlotSelectionInput 의 pure projection) ──────────────
@dataclass(frozen=True)
class EffectiveSelectionBasis:
    """SlotSelectionInput → execution-semantics/v1 pure projection. ``slot_mode`` 는 variant 파생."""

    slot_mode: str
    work_id: str
    template_application_id: str
    selection_semantic_contract_id: str
    template_structure_digest: str
    effective_selection_digest: str | None
    declared_selection_digest: str | None


def project_effective_selection(selection: SlotSelectionInput) -> EffectiveSelectionBasis:
    """SlotlessSelectionContext → SLOTLESS, SlotConfigurationSnapshot → SLOTTED. ``None`` 은 안 받는다.

    incomplete/review-required 에서 S4 가 exact input 을 주지 않으면 여기 도달하지 않는다 —
    snapshot 을 합성하지 않는다.
    """
    if isinstance(selection, SlotlessSelectionContext):
        return EffectiveSelectionBasis(
            slot_mode=SLOTLESS,
            work_id=selection.work_id,
            template_application_id=selection.template_application_id,
            selection_semantic_contract_id=selection.selection_semantic_contract_id,
            template_structure_digest=selection.template_structure_digest,
            effective_selection_digest=None,
            declared_selection_digest=selection.declared_selection_digest,
        )
    if isinstance(selection, SlotConfigurationSnapshot):
        # claimed effective digest 를 믿지 않고 effective_selections 에서 recompute·대조한다 —
        # 위조/stale digest 로 다른 selection 이 같은 Plan identity 를 훔치지 못하게 한다.
        contract_id = selection.selection_semantic_contract_id
        recomputed = digest_selection_set(contract_id, selection.effective_selections)
        if recomputed != selection.effective_selection_digest:
            raise ExecutionCaptureIntegrityError(
                "effective_selection_digest 가 effective_selections recompute 와 불일치"
            )
        return EffectiveSelectionBasis(
            slot_mode=SLOTTED,
            work_id=selection.work_id,
            template_application_id=selection.template_application_id,
            selection_semantic_contract_id=contract_id,
            template_structure_digest=selection.template_structure_digest,
            effective_selection_digest=selection.effective_selection_digest,
            declared_selection_digest=selection.declared_selection_digest,
        )
    raise ExecutionCaptureIntegrityError(
        f"미지원 SlotSelectionInput variant: {type(selection).__name__}"
    )


# ─── observation 모델(complete 와 domain-blocked 를 가른다) ─────────────────────────
@dataclass(frozen=True)
class CapturedSelection:
    """exact SlotSelectionInput 을 복원한 selection 관찰."""

    selection: SlotSelectionInput


@dataclass(frozen=True)
class DomainBlockedSelection:
    """selection 이 사용자 구성 수정을 요구하는 상태(예: SLOT_CONFIGURATION_INCOMPLETE)."""

    blocker_code: str
    detail: str


@dataclass(frozen=True)
class CapturedFieldBinding:
    """exact FieldBindingInput 을 복원한 binding 관찰."""

    field_binding: FieldBindingInput


@dataclass(frozen=True)
class DomainBlockedFieldBinding:
    """binding 이 migration/application-review 를 요구하는 상태."""

    blocker_code: str
    detail: str


SelectionObservation = CapturedSelection | DomainBlockedSelection
FieldBindingObservation = CapturedFieldBinding | DomainBlockedFieldBinding


# ─── capture result 합타입의 4 변형 ───────────────────────────────────────────────
@dataclass(frozen=True)
class CapturedExecutionInput:
    """모든 exact input 을 완전하게 복원한 경우만 사용한다.

    ``captured_execution_input_digest`` 의 canonical bytes 는 S5-06 이 채운다 — complete input 이
    아닌 variant 에는 이 digest 를 부여하지 않는다(여기선 기본 ``None``).
    """

    workspace_instance_id: str
    work_authority_id: str
    template: CapturedTemplateExecutionInput
    selection: SlotSelectionInput
    field_binding: FieldBindingInput
    resolved_seal_policy: ResolvedSealPolicy
    captured_execution_input_semantic_projection: Mapping[str, Any]
    captured_at: str
    captured_execution_input_digest: str | None = None


@dataclass(frozen=True)
class CapturedExecutionDomainBlock:
    """Work authority 는 읽혔지만 사용자가 구성/Binding 을 고쳐야 exact input 이 완성되는 상태."""

    workspace_instance_id: str
    work_authority_id: str
    template_observation: CapturedTemplateExecutionInput
    selection_observation: SelectionObservation
    field_binding_observation: FieldBindingObservation
    resolved_seal_policy: ResolvedSealPolicy
    normalized_blockers: tuple[str, ...]
    captured_attempt_semantic_projection: Mapping[str, Any]
    captured_at: str
    captured_attempt_digest: str | None = None


@dataclass(frozen=True)
class CapturedExecutionPolicyBlock:
    """exact domain input 을 읽기 전/후, 현재 policy 상 새 seal 을 허용할 수 없는 상태.

    Profile admission authority 의 실제 판정/버전은 S5-08, ordered capture 는 S5-10 소유다 —
    여기서는 policy block 의 **타입**과 continuation exclusion 만 소유한다.
    """

    policy_code: str
    observed_at: str
    qualification_profile_id: str | None = None
    observed_policy_version: str | None = None
    policy_observation_digest: str | None = None
    captured_attempt_digest: str | None = None


@dataclass(frozen=True)
class ExecutionCaptureContextError:
    """exact context·canonical contract·dependency·persistence·authority integrity 복원 실패.

    terminal command outcome 이 아니며 request ID 를 소비하지 않는다(재시도 가능한 실패).
    """

    # 결과이지 명령의 종결이 아니다 — request ID 회계에 참여하지 않는다.
    is_terminal_command_outcome: ClassVar[bool] = False
    consumes_request_id: ClassVar[bool] = False

    code: str
    detail: str


CaptureExecutionQualificationResult = (
    CapturedExecutionInput
    | CapturedExecutionDomainBlock
    | CapturedExecutionPolicyBlock
    | ExecutionCaptureContextError
)


# ─── legacy continuation ≠ managed Plan materialization(타입 분리) ──────────────────
@dataclass(frozen=True)
class LegacyContinuationGenerationAdapter:
    """previous output document 를 mutation base 로 쓰는 legacy adapter.

    S5 exact guarantee·semantic currentness·Plan-bound Candidate provenance 를 **주장하지 않는다**.
    managed Plan materialization 과 **별개 타입**이다.
    """

    supported_execution_base: str = CONTINUATION_OUTPUT_DOCUMENT
    claims_exact_guarantee: bool = False
    claims_plan_bound_provenance: bool = False


@dataclass(frozen=True)
class ManagedPlanMaterializationAdapter:
    """exact applied Candidate 를 base 로 Plan-bound materialization 을 하는 managed adapter."""

    supported_execution_base: str = APPLIED_TEMPLATE_CANDIDATE
    claims_exact_guarantee: bool = True
    claims_plan_bound_provenance: bool = True


# 향후 managed continuation 모델(비범위 후속 — 여기서 구현하지 않는다):
# ContinuationDocumentSnapshot(exact bytes/content digest, Field structure inspection evidence,
# admissible operation projection, qualification contract, immutable snapshot ref).


# ─── under-fence exact capture port ───────────────────────────────────────────────
class CaptureExecutionQualificationInputUnderFence(Protocol):
    """caller 가 shared PerWorkMutationFence 를 이미 보유한 상태의 exact capture port.

    (R2-05b(#740)로 ProfileFence 가 사라져 보유 전제는 PerWorkFence 하나다 — #806 정정.)

    helper 는 fence 를 재획득하지 않는다. S4 capture 와 FieldBinding exact read 를 같은 Work fence
    안에서 수행하고, 정상 capture 에서 mutable source·Job.template_path·template_override·latest
    Revision/Evidence·Template Qualification 재실행·HWPX parse/mutation·Data Source reload 를 하지
    않는다. 구현(fence 아래 context resolution)은 S5-10 소유다.
    """

    def __call__(
        self,
        workspace_instance_id: str,
        work_authority_id: str,
        expected_template_application_id: str,
        expected_profile_id: str,
        resolved_seal_policy: ResolvedSealPolicy,
    ) -> CaptureExecutionQualificationResult: ...


# ─── semantic projection seam(DTO 전체 직렬화를 digest input 으로 쓰지 않는다) ──────────
def _encode_applied_semantic_claims(applied: ExactAppliedTemplateInput) -> dict[str, Any]:
    # canonical_blob_reference 는 store/object address 라 제외한다(exact_content_digest 가 semantic).
    return {
        "work_id": applied.work_id,
        "template_application_id": applied.template_application_id,
        "revision_id": applied.revision_id,
        "media": applied.media,
        "template_lineage_id": applied.template_lineage_id,
        "exact_content_digest": applied.exact_content_digest,
    }


def _encode_qualification_claims(
    qualification: ExactTemplateQualificationContext,
) -> dict[str, Any]:
    payload = qualification.qualification_profile_semantic_payload
    return {
        "pass_evidence_id": qualification.pass_evidence_id,
        "qualification_profile_id": qualification.qualification_profile_id,
        "structure_projection_schema_version": (
            qualification.structure_projection_schema_version
        ),
        "template_structure_digest": qualification.template_structure_digest,
        "composition_profile_state": qualification.composition_profile_state,
        "qualification_profile_semantic_payload": {
            "qualification_profile_id": payload.qualification_profile_id,
            "media": payload.media,
            "adapter_contract_version": payload.adapter_contract_version,
            "product_rule_version": payload.product_rule_version,
            "operation_alphabet_version": payload.operation_alphabet_version,
            "projection_schema_version": payload.projection_schema_version,
            "manifest_payload": dict(payload.manifest_payload),
        },
    }


def _encode_selection_claims(basis: EffectiveSelectionBasis) -> dict[str, Any]:
    # source_configuration_version 은 durable provenance 지 execution semantic identity 가 아니다 — 제외.
    # projection 계약 version 을 담아 projection-rule 변경이 semantic identity 를 바꾸게 한다.
    return {
        "selection_projection_contract": EXECUTION_SELECTION_SEMANTICS_CONTRACT,
        "slot_mode": basis.slot_mode,
        "work_id": basis.work_id,
        "template_application_id": basis.template_application_id,
        "selection_semantic_contract_id": basis.selection_semantic_contract_id,
        "template_structure_digest": basis.template_structure_digest,
        "effective_selection_digest": basis.effective_selection_digest,
        "declared_selection_digest": basis.declared_selection_digest,
    }


def _encode_field_binding_claims(field_binding: FieldBindingInput) -> dict[str, Any]:
    # field_binding_authority_revision 은 durable provenance 라 effective identity 에 안 넣는다 — 제외.
    return {
        "base_template_application_id": field_binding.base_template_application_id,
        "field_binding_semantic_contract_id": (
            field_binding.field_binding_semantic_contract_id
        ),
        "source_schema_contract_id": field_binding.source_schema_contract_id,
        "raw_record_contract_id": field_binding.raw_record_contract_id,
        "canonical_binding_digest": field_binding.canonical_binding_digest,
        "canonical_source_schema_digest": field_binding.canonical_source_schema_digest,
    }


def _encode_resolved_seal_policy(policy: ResolvedSealPolicy) -> dict[str, Any]:
    return {
        "policy_resolution_version": policy.policy_resolution_version,
        "execution_base_kind": policy.execution_base_kind,
        "execution_semantic_contract_id": policy.execution_semantic_contract_id,
        "binding_value_contract_id": policy.binding_value_contract_id,
        "raw_record_contract_id": policy.raw_record_contract_id,
        "document_value_resolution_contract_id": (
            policy.document_value_resolution_contract_id
        ),
        "record_validation_contract_id": policy.record_validation_contract_id,
        "record_review_contract_id": policy.record_review_contract_id,
        "composition_contract_id": policy.composition_contract_id,
        "native_primitive_contract_id": policy.native_primitive_contract_id,
        "materialization_base_contract_id": policy.materialization_base_contract_id,
        "composition_theorem_evidence_manifest_digest": (
            policy.composition_theorem_evidence_manifest_digest
        ),
        "materialization_contract_id": policy.materialization_contract_id,
        "plan_schema_version": policy.plan_schema_version,
        "canonical_encoding_version": policy.canonical_encoding_version,
    }


def build_captured_execution_semantic_projection(
    *,
    template: CapturedTemplateExecutionInput,
    selection: SlotSelectionInput,
    field_binding: FieldBindingInput,
    resolved_seal_policy: ResolvedSealPolicy,
) -> dict[str, Any]:
    """complete input 의 명시적 semantic projection.

    포함: workspace·WorkAuthorityId·applied semantic claims·exact Qualification context·selection
    semantic claims·FieldBinding exact semantic claims·ResolvedSealPolicy·ExecutionBaseKind. 제외:
    모든 captured_at·store path/object address·opaque token/UI/actor session·
    field_binding_authority_revision·source_configuration_version. DTO 전체 직렬화가 아니라
    semantic claim 을 골라 담으므로 DTO field order/serialization 우연 변화와 분리된다.
    """
    return {
        "workspace_instance_id": template.workspace_instance_id,
        "work_authority_id": template.work_authority_id,
        "applied": _encode_applied_semantic_claims(template.applied),
        "qualification": _encode_qualification_claims(template.qualification),
        "selection": _encode_selection_claims(project_effective_selection(selection)),
        "field_binding": _encode_field_binding_claims(field_binding),
        "resolved_seal_policy": _encode_resolved_seal_policy(resolved_seal_policy),
        "execution_base_kind": resolved_seal_policy.execution_base_kind,
    }


def build_captured_attempt_semantic_projection(
    *,
    template: CapturedTemplateExecutionInput,
    resolved_seal_policy: ResolvedSealPolicy,
    selection_observation: SelectionObservation,
    field_binding_observation: FieldBindingObservation,
) -> dict[str, Any]:
    """incomplete attempt 의 명시적 semantic projection(complete digest 는 부여하지 않는다).

    complete projection 과 같은 exclusion 규칙을 따른다. captured 부분은 semantic claim 을,
    domain-blocked 부분은 blocker code 를 담아 attempt 를 재현 가능하게 하되 complete-input digest
    를 주지 않는다.
    """
    if isinstance(selection_observation, CapturedSelection):
        selection_view: Any = _encode_selection_claims(
            project_effective_selection(selection_observation.selection)
        )
    else:
        selection_view = {"blocked": selection_observation.blocker_code}
    if isinstance(field_binding_observation, CapturedFieldBinding):
        binding_view: Any = _encode_field_binding_claims(
            field_binding_observation.field_binding
        )
    else:
        binding_view = {"blocked": field_binding_observation.blocker_code}
    return {
        "workspace_instance_id": template.workspace_instance_id,
        "work_authority_id": template.work_authority_id,
        "applied": _encode_applied_semantic_claims(template.applied),
        "qualification": _encode_qualification_claims(template.qualification),
        "selection": selection_view,
        "field_binding": binding_view,
        "resolved_seal_policy": _encode_resolved_seal_policy(resolved_seal_policy),
        "execution_base_kind": resolved_seal_policy.execution_base_kind,
    }


def semantic_projection_digest(projection: Mapping[str, Any]) -> str:
    """capture semantic projection 의 content-address(S5-06 closed canonical byte framing).

    complete input 이면 captured_execution_input_digest, attempt 면 captured_attempt_digest 의
    단일 seam 이다. byte framing·SHA-256·golden vector 는 S5-06
    :mod:`hwpxfiller.domain.canonical_execution_encoding` 소유다(정렬 JSON 아님).
    """
    return canonical_execution_digest(dict(projection))


# ─── cross-reference integrity(mismatch 마다 typed context error) ──────────────────
def _cross_reference_error(
    template: CapturedTemplateExecutionInput,
    workspace_instance_id: str,
    work_authority_id: str,
    expected_template_application_id: str,
    expected_profile_id: str,
    selection: SlotSelectionInput | None,
    field_binding: FieldBindingInput | None,
) -> ExecutionCaptureContextError | None:
    """request↔template↔selection↔binding cross-reference. 위반이면 party 별 typed context error.

    Selection variant 에는 workspace field 가 아예 없으므로 selection 의 workspace 를
    **비교하지 않는다** — workspace three-way 는 template·field_binding 으로만 증명한다.
    """
    # request ↔ template(applied Candidate 가 요청 context 와 결속돼야 한다).
    if template.workspace_instance_id != workspace_instance_id:
        return ExecutionCaptureContextError(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "template workspace 가 요청 workspace 와 불일치",
        )
    if template.work_authority_id != work_authority_id:
        return ExecutionCaptureContextError(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "template work authority 가 요청 WorkAuthorityId 와 불일치",
        )
    if template.applied.template_application_id != expected_template_application_id:
        return ExecutionCaptureContextError(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "applied Application 이 expected_template_application_id 와 불일치",
        )
    if template.qualification.qualification_profile_id != expected_profile_id:
        return ExecutionCaptureContextError(
            QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR,
            "qualification profile 이 expected_profile_id 와 불일치",
        )
    # structure projection schema 는 ExactTemplateQualificationContext.__post_init__ 이 v2 로
    # 강제한다(ExecutionTemplateStructure 가 v2-only) — 여기서 재확인하면 unreachable 이므로 두지
    # 않는다. UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION 은 decode/runner 층이 낸다.
    # template ↔ field_binding.
    if field_binding is not None:
        if field_binding.workspace_instance_id != template.workspace_instance_id:
            return ExecutionCaptureContextError(
                FIELD_BINDING_INPUT_INTEGRITY_ERROR,
                "field binding workspace 가 template 과 불일치",
            )
        if field_binding.work_authority_id != template.work_authority_id:
            return ExecutionCaptureContextError(
                FIELD_BINDING_INPUT_INTEGRITY_ERROR,
                "field binding work authority 가 template 과 불일치",
            )
        if field_binding.base_template_application_id != (
            template.applied.template_application_id
        ):
            return ExecutionCaptureContextError(
                FIELD_BINDING_INPUT_INTEGRITY_ERROR,
                "field binding base Application 이 template 과 불일치",
            )
    # template ↔ selection(selection 은 workspace field 가 없다 — work·application·structure 만 비교).
    if selection is not None:
        if selection.work_id != template.work_authority_id:
            return ExecutionCaptureContextError(
                SELECTION_CONTRACT_INTEGRITY_ERROR,
                "selection work_id 가 template WorkAuthorityId 와 불일치",
            )
        if selection.template_application_id != template.applied.template_application_id:
            return ExecutionCaptureContextError(
                SELECTION_CONTRACT_INTEGRITY_ERROR,
                "selection Application 이 template 과 불일치",
            )
        # selection 은 어떤 구조에서 캡처됐는지도 qualification context 와 일치해야 한다 — 같은 Work·
        # Application id 라도 다른 structure(schema·digest)에서 온 선택이면 exact input 이 아니다.
        qual = template.qualification
        if selection.structure_projection_schema_version != (
            qual.structure_projection_schema_version
        ):
            return ExecutionCaptureContextError(
                SELECTION_CONTRACT_INTEGRITY_ERROR,
                "selection structure schema 가 qualification context 와 불일치",
            )
        if selection.template_structure_digest != qual.template_structure_digest:
            return ExecutionCaptureContextError(
                SELECTION_CONTRACT_INTEGRITY_ERROR,
                "selection template_structure_digest 가 qualification context 와 불일치",
            )
        # claimed effective/selection digest self-consistency(재계산)도 여기서 함께 닫는다 —
        # project_effective_selection 이 recompute·raise 하는 것을 typed context error 로 옮긴다.
        try:
            project_effective_selection(selection)
        except ExecutionCaptureIntegrityError as exc:
            return ExecutionCaptureContextError(
                SELECTION_CONTRACT_INTEGRITY_ERROR, str(exc)
            )
    return None


# ─── pure capture 판정 core(runner 가 fence 아래에서 부른다) ──────────────────────────
def judge_captured_execution(
    *,
    workspace_instance_id: str,
    work_authority_id: str,
    expected_template_application_id: str,
    expected_profile_id: str,
    resolved_seal_policy: ResolvedSealPolicy,
    template: CapturedTemplateExecutionInput,
    selection_observation: SelectionObservation,
    field_binding_observation: FieldBindingObservation,
    captured_at: str,
    policy_block: CapturedExecutionPolicyBlock | None = None,
) -> CaptureExecutionQualificationResult:
    """복원된 (template, selection, binding, policy) 로 capture result 합타입을 낸다(순수).

    순서:
      1. execution base kind — continuation 이면 policy block, unknown 이면 context error.
      2. S5-08 이 낸 policy block(revoked/unsealable/not-admitted)이 있으면 그대로 낸다.
      3. request↔template cross-reference — 위반이면 context error.
      4. selection/binding 중 domain-blocked 가 있으면 domain block(captured 부분도 cross-check).
      5. 둘 다 captured 면 full cross-reference 뒤 complete CapturedExecutionInput.
    """
    # 1. execution base — continuation 은 exact applied Candidate 가 아니라 policy block.
    base = resolved_seal_policy.execution_base_kind
    if base == CONTINUATION_OUTPUT_DOCUMENT:
        return CapturedExecutionPolicyBlock(
            policy_code=CONTINUATION_BASE_NOT_SUPPORTED,
            observed_at=captured_at,
            qualification_profile_id=expected_profile_id,
        )
    if base != APPLIED_TEMPLATE_CANDIDATE:
        # unknown base 는 latest/default 로 풀지 않는다 — 시끄럽게 fail-closed.
        return ExecutionCaptureContextError(
            UNSUPPORTED_LOCAL_IMPLEMENTATION,
            f"미지원 execution base kind: {base!r}",
        )
    if resolved_seal_policy.materialization_base_contract_id != (
        MATERIALIZATION_BASE_CONTRACT_ID
    ):
        return ExecutionCaptureContextError(
            EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR,
            "materialization base contract 가 applied-template-candidate-base/v1 이 아니다",
        )

    # 2. policy admission block(S5-08 판정) — exact domain 을 읽기 전이라도 새 seal 불가.
    if policy_block is not None:
        # profile-specific block 은 요청 profile 에 결속돼야 한다 — 다른/구 profile 의 판정을
        # 이 profile 의 결과로 되돌려주지 않는다(profile-bound policy result).
        if (
            policy_block.qualification_profile_id is not None
            and policy_block.qualification_profile_id != expected_profile_id
        ):
            return ExecutionCaptureContextError(
                QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR,
                "policy block 의 qualification_profile_id 가 요청 profile 과 불일치",
            )
        return policy_block

    # 3. request ↔ template cross-reference(domain-blocked 여부와 무관하게 먼저).
    captured_selection = (
        selection_observation.selection
        if isinstance(selection_observation, CapturedSelection)
        else None
    )
    captured_binding = (
        field_binding_observation.field_binding
        if isinstance(field_binding_observation, CapturedFieldBinding)
        else None
    )
    context_error = _cross_reference_error(
        template,
        workspace_instance_id,
        work_authority_id,
        expected_template_application_id,
        expected_profile_id,
        captured_selection,
        captured_binding,
    )
    if context_error is not None:
        return context_error

    # 4. domain block — 사용자가 구성/Binding 을 고쳐야 exact input 이 완성된다.
    selection_blocked = isinstance(selection_observation, DomainBlockedSelection)
    binding_blocked = isinstance(field_binding_observation, DomainBlockedFieldBinding)
    if selection_blocked or binding_blocked:
        blockers: list[str] = []
        if isinstance(selection_observation, DomainBlockedSelection):
            blockers.append(selection_observation.blocker_code)
        if isinstance(field_binding_observation, DomainBlockedFieldBinding):
            blockers.append(field_binding_observation.blocker_code)
        attempt_projection = build_captured_attempt_semantic_projection(
            template=template,
            resolved_seal_policy=resolved_seal_policy,
            selection_observation=selection_observation,
            field_binding_observation=field_binding_observation,
        )
        return CapturedExecutionDomainBlock(
            workspace_instance_id=workspace_instance_id,
            work_authority_id=work_authority_id,
            template_observation=template,
            selection_observation=selection_observation,
            field_binding_observation=field_binding_observation,
            resolved_seal_policy=resolved_seal_policy,
            normalized_blockers=tuple(blockers),
            captured_attempt_semantic_projection=attempt_projection,
            captured_at=captured_at,
            captured_attempt_digest=semantic_projection_digest(attempt_projection),
        )

    # 5. complete — 모든 exact input 을 복원했다. base 를 고정하고 semantic projection 을 낸다.
    assert captured_selection is not None  # domain-block 아니므로 captured
    assert captured_binding is not None
    build_exact_execution_basis(template, resolved_seal_policy)  # base 계약 재확인(fail-closed)
    projection = build_captured_execution_semantic_projection(
        template=template,
        selection=captured_selection,
        field_binding=captured_binding,
        resolved_seal_policy=resolved_seal_policy,
    )
    return CapturedExecutionInput(
        workspace_instance_id=workspace_instance_id,
        work_authority_id=work_authority_id,
        template=template,
        selection=captured_selection,
        field_binding=captured_binding,
        resolved_seal_policy=resolved_seal_policy,
        captured_execution_input_semantic_projection=projection,
        captured_at=captured_at,
        captured_execution_input_digest=semantic_projection_digest(projection),
    )


# 재-export — 소비자(runner·S5-08/10)가 blocker/policy 어휘를 한 곳에서 참조.
__all__ = [
    "APPLIED_TEMPLATE_CANDIDATE",
    "CONTINUATION_OUTPUT_DOCUMENT",
    "MATERIALIZATION_BASE_CONTRACT_ID",
    "EXECUTION_SELECTION_SEMANTICS_CONTRACT",
    "SLOTLESS",
    "SLOTTED",
    "NEEDS_CONFIGURATION",
    "NEEDS_CONFIGURATION_REVIEW",
    "SLOT_CONFIGURATION_INCOMPLETE",
    "NEEDS_BINDING_SEMANTIC_MIGRATION",
    "NEEDS_FIELD_BINDING_APPLICATION_REVIEW",
    "QUALIFICATION_PROFILE_REVOKED",
    "EXECUTION_PROFILE_NOT_SEALABLE",
    "EXECUTION_POLICY_NOT_ADMITTED",
    "CONTINUATION_BASE_NOT_SUPPORTED",
    "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR",
    "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR",
    "SELECTION_CONTRACT_INTEGRITY_ERROR",
    "FIELD_BINDING_INPUT_INTEGRITY_ERROR",
    "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION",
    "UNSUPPORTED_LOCAL_IMPLEMENTATION",
    "EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR",
    "ExecutionCaptureIntegrityError",
    "WorkRouteRef",
    "QualificationProfileSemanticPayload",
    "ExactTemplateQualificationContext",
    "CapturedTemplateExecutionInput",
    "ResolvedSealPolicy",
    "ExactTemplateExecutionBasis",
    "build_exact_execution_basis",
    "EffectiveSelectionBasis",
    "project_effective_selection",
    "CapturedSelection",
    "DomainBlockedSelection",
    "CapturedFieldBinding",
    "DomainBlockedFieldBinding",
    "SelectionObservation",
    "FieldBindingObservation",
    "CapturedExecutionInput",
    "CapturedExecutionDomainBlock",
    "CapturedExecutionPolicyBlock",
    "ExecutionCaptureContextError",
    "CaptureExecutionQualificationResult",
    "LegacyContinuationGenerationAdapter",
    "ManagedPlanMaterializationAdapter",
    "CaptureExecutionQualificationInputUnderFence",
    "build_captured_execution_semantic_projection",
    "build_captured_attempt_semantic_projection",
    "semantic_projection_digest",
    "judge_captured_execution",
]
