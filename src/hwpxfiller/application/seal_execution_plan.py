"""SealExecutionPlan 순수 판정 — raw intent·candidate compile·final gate verdict (S5-10 · #706).

이 모듈은 **순수**하다: store·fence·wall-clock·HWPX·native 를 모른다. fence 획득과 capture port
호출은 :mod:`hwpxfiller.external.seal_orchestration_runner` 가 진다. 여기서는 그 runner 가 각
gate 에서 부르는 결정을 소유한다:

- short capture gate 결과 분류(complete → 계속, domain/policy block → fresh terminal, context
  error → attempt).
- fence 밖 pure qualification+compile → ``PlanCandidate`` | ``BlockedCandidate`` (context/composition
  실패는 attempt 로 raise — user-fixable blocker 로 낮추지 않는다).
- short final gate verdict: candidate 가 사용한 exact contracts 로 current basis 를 재구성해
  equality·policy·sealability 를 비교하고 publish/blocked/policy/stale/attempt 로 가른다.

R2-04a(#740): first-seen ledger·replay·idempotency·request fingerprint 를 제거했다 — 같은 request
재호출은 historical outcome 을 replay 하지 않고 현재 authority 에서 재계산한다. terminal outcome 은
durable 하게 소비하지 않고 fresh 로 되돌린다. R2-04b-2(#740)로 **content-addressed store publication
도 없다** — sealable candidate 는 store artifact 가 아니라 in-memory sealed plan payload 를 낸다
(:func:`sealed_outcome_for` · 조립부 주석 참조). 폐기된 publication 어휘를 되살리지 않는다(#806).

confirm-or-alarm & fail-closed: unknown 값을 latest/default 로 풀지 않고 시끄럽게 닫는다.
context/integrity/I-O 실패는 terminal 이 아니다(재시도 가능).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    UNSUPPORTED_LOCAL_IMPLEMENTATION,
    CaptureExecutionQualificationResult,
    CapturedExecutionDomainBlock,
    CapturedExecutionInput,
    CapturedExecutionPolicyBlock,
    CapturedFieldBinding,
    CapturedSelection,
    ExecutionCaptureContextError,
    ResolvedSealPolicy,
)
from hwpxfiller.application.execution_compilation import (
    ExecutionCompilationContextError,
    ExecutionQualificationBlocked as CompileQualificationBlocked,
    QualifiedExecutionCompilation,
    qualify_and_compile_execution,
)
from hwpxfiller.application.execution_composition import (
    DEFAULT_THEOREM_EVIDENCE_REGISTRY,
    NATIVE_PRIMITIVE_CONTRACT_V1,
    TheoremEvidenceRegistry,
    verify_execution_composition_premises,
)
from hwpxfiller.application.execution_contract_set import (
    AttemptSealCaptureEvidence,
    CaptureEvidenceProvenance,
    CompleteSealCaptureEvidence,
    DurableSealCaptureEvidence,
    ExecutionBasis,
    build_execution_contract_set,
    build_sealed_plan,
    execution_basis_digest,
    qualification_profile_semantic_digest,
    verify_execution_basis_integrity,
)
from hwpxfiller.application.slot_selection_input import SlotConfigurationSnapshot
from hwpxfiller.application.stored_execution_plan import (
    ExecutionPlanSealed,
    ExecutionPolicyBlocked,
    ExecutionQualificationBlocked,
    RequestedAuto,
    RequestedExact,
    RequestedVersionSelector,
    SealTerminalOutcome,
    StaleExecutionBasis,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    canonical_execution_digest,
)

COMMAND_SCHEMA_VERSION = "seal-execution-plan-command/v1"
# 지원 plan schema(latest fallback 없음 — unknown 은 시끄럽게 닫는다).
SUPPORTED_PLAN_SCHEMAS = ("hwpx-execution-plan/v1",)

# stale reason 어휘(S5-07 store 가 강제하는 두 값과 결속).
STALE_DIGEST_MISMATCH = "DIGEST_MISMATCH"
STALE_CURRENT_BASIS_NOT_SEALABLE = "CURRENT_BASIS_NOT_SEALABLE"

# provenance 가 exact S4 값을 못 가질 때의 sentinel(모든 digest 에서 제외되는 audit 값).
# ponytail: attempt/policy block 는 domain provenance 를 안 가질 수 있다 — 감사용 sentinel 로 둔다.
_PROVENANCE_UNRESOLVED = "unresolved"
_SLOTLESS_CONFIG_REF = "SLOTLESS_NO_CONFIGURATION"

# ─── attempt error(request 미소비) ────────────────────────────────────────────────────
class SealAttemptError(Exception):
    """terminal 이 아닌 실패의 뿌리 — request ID 를 소비하지 않는다(재시도 가능)."""

    code = "SEAL_ATTEMPT_ERROR"


class RouteResolutionError(SealAttemptError):
    code = "ROUTE_RESOLUTION_ERROR"


class AuthorizationError(SealAttemptError):
    code = "AUTHORIZATION_ERROR"


class ExecutionQualificationContextError(SealAttemptError):
    """exact context·contract·dependency·integrity 복원 실패 — terminal 아님."""

    code = "EXECUTION_QUALIFICATION_CONTEXT_ERROR"

    def __init__(self, message: str, *, cause_code: str | None = None) -> None:
        super().__init__(message)
        self.cause_code = cause_code


class UnsupportedLocalImplementation(SealAttemptError):
    """다른 shipping build 에서 지원될 수 있는 local attempt failure — semantic policy block 아님."""

    code = "UNSUPPORTED_LOCAL_IMPLEMENTATION"


# ─── fresh observation query port seam(S5-10 소유 선언) ────────────────────────────────
@dataclass(frozen=True)
class WorkExecutionSummary:
    """optimistic discovery·under-fence exact re-read 가 반환하는 current Work 요약.

    identity(profile·application)만 담는다 — exact bytes/selection/binding 은 capture port 소유다.
    """

    qualification_profile_id: str
    template_application_id: str


class FreshWorkObservationPort(Protocol):
    """current WorkTemplateApplication summary 관찰 port(fence 유무는 caller 가 안다).

    optimistic(fence 밖)일 때 관찰 직후 값이 바뀔 수 있다. under-fence 호출은 exact 다.
    state 부재(bootstrap 전)는 raise — implicit default 로 넘어가지 않는다.
    """

    def __call__(
        self, workspace_instance_id: str, work_authority_id: str
    ) -> WorkExecutionSummary: ...


class ShippingSealPolicyResolver(Protocol):
    """new request + AUTO 를 current shipping default 로 exact ResolvedSealPolicy 로 canonicalize 한다.

    EXACT selector 는 그대로 받아야 한다(요청 A / policy B 라는 모순 쌍을 만들지 않는다).
    """

    def __call__(
        self, command: "SealExecutionPlanCommand", observed: WorkExecutionSummary
    ) -> ResolvedSealPolicy: ...


# ─── S6 start admission port 선언(구현하지 않는다) ────────────────────────────────────
# S6 materialization 은 이 lock order 를 따라야 한다 — 짧은 ordered start-gate 로 Plan·current
# basis·runtime admission·VDR·dependency 를 pin 하고 fence 를 푼 뒤 긴 materialization 을 한다.
# R2-05b(#740): ProfileFence 제거로 outer rank 는 PerWorkMutationFence 다(S6 구현은 미착수·미변경).
S6_START_GATE_LOCK_ORDER = (
    "PerWorkMutationFence",
    "PlanAndCurrentBasisAndRuntimeAdmissionAndDependencyPin",
    "<fences released>",
    "LongMaterialization",
)


class S6StartAdmissionGate(Protocol):
    """S6 가 구현할 ordered start-gate port — S5-10 은 선언만 하고 구현하지 않는다.

    PerWorkFence 아래에서 Plan·current basis·runtime admission·dependency 를 pin 하고 fence 를
    release 한 뒤 long materialization 을 시작한다(:data:`S6_START_GATE_LOCK_ORDER`).
    S5-99 는 이 구현에 의존하지 않는다.
    """

    def __call__(
        self,
        *,
        plan_semantic_digest: str,
        work_authority_id: str,
        workspace_instance_id: str,
    ) -> None: ...


# ─── command + fingerprint ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SealExecutionPlanCommand:
    """생략된 selector 는 raw intent 에서 ``AUTO`` 로 canonicalize 한다(resolve 결과와 다른 취급)."""

    workspace_instance_id: str
    work_ref: str
    request_id: str
    requested_execution_base_kind: str = APPLIED_TEMPLATE_CANDIDATE
    requested_execution_semantic_contract: RequestedVersionSelector = RequestedAuto()
    requested_plan_schema: RequestedVersionSelector = RequestedAuto()
    requested_canonical_encoding: RequestedVersionSelector = RequestedAuto()

    def __post_init__(self) -> None:
        for name in ("workspace_instance_id", "work_ref", "request_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{name} 는 비어 있지 않은 문자열이어야 한다")


def require_exact_selector_consistency(
    command: SealExecutionPlanCommand, policy: ResolvedSealPolicy
) -> None:
    """EXACT selector·base kind 가 resolve 된 policy 와 일치하는지 확인(불일치=attempt).

    resolver 가 EXACT 요청을 무시하고 다른 값을 낸 것을 durable ledger 이전에 시끄럽게 잡는다.
    plan schema 지원 여부도 여기서 fail-closed 로 확인한다.
    """
    if command.requested_execution_base_kind != policy.execution_base_kind:
        raise ExecutionQualificationContextError(
            "resolved policy 의 execution_base_kind 가 요청과 불일치"
        )
    for selector, value, what in (
        (command.requested_execution_semantic_contract,
         policy.execution_semantic_contract_id, "execution_semantic_contract"),
        (command.requested_plan_schema, policy.plan_schema_version, "plan_schema"),
        (command.requested_canonical_encoding,
         policy.canonical_encoding_version, "canonical_encoding"),
    ):
        if isinstance(selector, RequestedExact) and selector.value != value:
            raise ExecutionQualificationContextError(
                f"resolved policy 의 {what} 가 EXACT 요청과 불일치"
            )
    if policy.plan_schema_version not in SUPPORTED_PLAN_SCHEMAS:
        raise UnsupportedLocalImplementation(
            f"미지원 plan schema(latest fallback 없음): {policy.plan_schema_version!r}"
        )
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION:
        raise UnsupportedLocalImplementation(
            f"미지원 canonical encoding: {policy.canonical_encoding_version!r}"
        )


# ─── candidate compile(fence 밖 pure) ─────────────────────────────────────────────────
@dataclass(frozen=True)
class PlanCandidate:
    """complete capture 가 sealable Plan 으로 compile 된 결과 — final gate seal 후보.

    R2-04b-2(#740): durable store 가 없어 plan_payload·plan_semantic_digest·dependency_set 를 싣지
    않는다. final gate 의 basis-equality staleness 판정과 성공 outcome 이 쓰는 ``execution_basis_digest``
    만 identity 로 남긴다.
    """

    qualification_profile_id: str
    template_application_id: str
    resolved_seal_policy: ResolvedSealPolicy
    execution_basis_digest: str
    plan_payload: Any  # SealedExecutionPlanSemanticPayload — S6 materialization/conformance 소비
    capture_evidence: CompleteSealCaptureEvidence
    captured_execution_input_digest: str


@dataclass(frozen=True)
class BlockedCandidate:
    """complete capture 지만 Active Field/구성 blocker 로 seal 불가 — final recheck 후 blocked commit."""

    qualification_profile_id: str
    template_application_id: str
    resolved_seal_policy: ResolvedSealPolicy
    normalized_blockers: tuple[str, ...]
    capture_evidence: CompleteSealCaptureEvidence
    captured_execution_input_digest: str


CandidateCompilation = PlanCandidate | BlockedCandidate


def _config_version_ref(selection: Any) -> str:
    if isinstance(selection, SlotConfigurationSnapshot):
        return str(selection.source_configuration_version)
    version = selection.source_configuration_version
    return str(version) if version is not None else _SLOTLESS_CONFIG_REF


def complete_capture_evidence(captured: CapturedExecutionInput) -> CompleteSealCaptureEvidence:
    """complete capture 의 durable evidence — semantic projection + exact provenance."""
    digest = captured.captured_execution_input_digest
    if not isinstance(digest, str) or digest == "":
        raise ExecutionQualificationContextError(
            "complete capture 에 captured_execution_input_digest 가 없다"
        )
    return CompleteSealCaptureEvidence(
        captured_execution_input_semantic_projection=(
            captured.captured_execution_input_semantic_projection
        ),
        captured_execution_input_digest=digest,
        provenance=CaptureEvidenceProvenance(
            field_binding_authority_revision=(
                captured.field_binding.field_binding_authority_revision
            ),
            source_configuration_version=_config_version_ref(captured.selection),
            captured_at=captured.captured_at,
        ),
    )


def compile_candidate(
    captured: CapturedExecutionInput,
    *,
    theorem_registry: TheoremEvidenceRegistry = DEFAULT_THEOREM_EVIDENCE_REGISTRY,
) -> CandidateCompilation:
    """complete capture → composition 증명 + compile + Plan candidate 구성(순수, fence 밖).

    context/composition/integrity 실패는 user-fixable blocker 로 낮추지 않고 attempt 로 raise 한다.
    """
    policy = captured.resolved_seal_policy
    require_exact_selector_consistency_for_compile(policy)
    structure = captured.template.qualification.execution_structure
    # theorem evidence 를 (composition, native primitive) 로 resolve — 미등록은 attempt(fail-closed).
    try:
        theorem = theorem_registry.resolve(
            policy.composition_contract_id, policy.native_primitive_contract_id
        )
    except Exception as exc:  # UnsupportedCompositionContract 등
        raise UnsupportedLocalImplementation(
            f"미지원 composition/native primitive contract: {exc}"
        ) from exc
    composition_result = verify_execution_composition_premises(
        structure=structure,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=theorem,
        composition_contract_id=policy.composition_contract_id,
        theorem_registry=theorem_registry,
    )
    compiled = qualify_and_compile_execution(
        captured=captured, composition_result=composition_result
    )
    if isinstance(compiled, ExecutionCompilationContextError):
        raise ExecutionQualificationContextError(
            f"compile context error({compiled.code}): {compiled.detail}",
            cause_code=compiled.code,
        )
    evidence = complete_capture_evidence(captured)
    if isinstance(compiled, CompileQualificationBlocked):
        return BlockedCandidate(
            qualification_profile_id=captured.template.qualification.qualification_profile_id,
            template_application_id=captured.template.applied.template_application_id,
            resolved_seal_policy=policy,
            normalized_blockers=tuple(b.code for b in compiled.normalized_blockers),
            capture_evidence=evidence,
            captured_execution_input_digest=evidence.captured_execution_input_digest,
        )
    assert isinstance(compiled, QualifiedExecutionCompilation)
    return _build_plan_candidate(captured, compiled, evidence, theorem_registry)


def require_exact_selector_consistency_for_compile(policy: ResolvedSealPolicy) -> None:
    """compile 이 build 하는 plan schema·encoding 이 지원 값인지 fail-closed 로 확인한다."""
    if policy.plan_schema_version not in SUPPORTED_PLAN_SCHEMAS:
        raise UnsupportedLocalImplementation(
            f"미지원 plan schema: {policy.plan_schema_version!r}"
        )
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION:
        raise UnsupportedLocalImplementation(
            f"미지원 canonical encoding: {policy.canonical_encoding_version!r}"
        )


def _build_plan_candidate(
    captured: CapturedExecutionInput,
    compiled: QualifiedExecutionCompilation,
    evidence: CompleteSealCaptureEvidence,
    theorem_registry: TheoremEvidenceRegistry,
) -> PlanCandidate:
    policy = captured.resolved_seal_policy
    qual = captured.template.qualification
    applied = captured.template.applied
    profile_semantic_digest = qualification_profile_semantic_digest(
        qual.qualification_profile_semantic_payload
    )
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
        # composition verification 이 쓴 registry 를 그대로 — DEFAULT 로 조용히 되돌아가면 injected
        # registry 가 admit 한 manifest 가 여기서 ExecutionContractSetIntegrityError 로 늦게 터진다.
        theorem_registry=theorem_registry,
    )
    basis = ExecutionBasis(
        workspace_instance_id=captured.workspace_instance_id,
        work_authority_id=captured.work_authority_id,
        qualification_profile_semantic_digest=profile_semantic_digest,
        template=compiled.exact_template_execution_basis,
        contracts=contracts,
        selection=compiled.effective_selection_basis,
        field_binding=compiled.effective_field_binding_basis,
    )
    verify_execution_basis_integrity(basis)
    # durable store·dependency retention·plan_semantic_digest identity 는 없다(R2-04b-2). 다만 sealed
    # plan payload 는 여전히 조립한다 — S6 materialization/conformance gate 가 소비하는 compiled plan
    # 이라 store artifact 가 아니다. candidate 는 그 payload + final gate staleness 가 쓰는
    # execution_basis_digest 만 싣는다(publication kind·plan digest 없음).
    semantic_payload = compiled.execution_basis_semantic_payload
    plan_payload = build_sealed_plan(
        execution_basis=basis,
        active_field_requirements=semantic_payload["active_field_requirements"],
        ordered_operations=semantic_payload["ordered_operations"],
        plan_schema_version=policy.plan_schema_version,
        canonical_encoding_version=policy.canonical_encoding_version,
    )
    return PlanCandidate(
        qualification_profile_id=qual.qualification_profile_id,
        template_application_id=applied.template_application_id,
        resolved_seal_policy=policy,
        execution_basis_digest=execution_basis_digest(basis),
        plan_payload=plan_payload,
        capture_evidence=evidence,
        captured_execution_input_digest=evidence.captured_execution_input_digest,
    )


# ─── capture gate 분류 ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CaptureComplete:
    captured: CapturedExecutionInput


@dataclass(frozen=True)
class CaptureTerminal:
    """capture gate 자체가 linearization point 인 즉시-commit terminal(domain/policy block)."""

    outcome: SealTerminalOutcome
    evidence: DurableSealCaptureEvidence


CaptureGateClassification = CaptureComplete | CaptureTerminal


def _attempt_evidence_of_domain_block(
    block: CapturedExecutionDomainBlock,
) -> AttemptSealCaptureEvidence:
    digest = block.captured_attempt_digest
    if not isinstance(digest, str) or digest == "":
        raise ExecutionQualificationContextError(
            "domain block 에 captured_attempt_digest 가 없다"
        )
    if isinstance(block.field_binding_observation, CapturedFieldBinding):
        revision = (
            block.field_binding_observation.field_binding.field_binding_authority_revision
        )
    else:
        revision = _PROVENANCE_UNRESOLVED
    if isinstance(block.selection_observation, CapturedSelection):
        config_ref = _config_version_ref(block.selection_observation.selection)
    else:
        config_ref = _PROVENANCE_UNRESOLVED
    return AttemptSealCaptureEvidence(
        captured_attempt_semantic_projection=block.captured_attempt_semantic_projection,
        captured_attempt_digest=digest,
        normalized_blockers=block.normalized_blockers,
        provenance=CaptureEvidenceProvenance(
            field_binding_authority_revision=revision,
            source_configuration_version=config_ref,
            captured_at=block.captured_at,
        ),
    )


def _policy_block_evidence_and_outcome(
    block: CapturedExecutionPolicyBlock, policy: ResolvedSealPolicy
) -> CaptureTerminal:
    projection = {
        "policy_block": {
            "policy_code": block.policy_code,
            "qualification_profile_id": block.qualification_profile_id,
            "observed_policy_version": block.observed_policy_version,
            "policy_observation_digest": block.policy_observation_digest,
            "execution_base_kind": policy.execution_base_kind,
        }
    }
    digest = canonical_execution_digest(projection)
    evidence = AttemptSealCaptureEvidence(
        captured_attempt_semantic_projection=projection,
        captured_attempt_digest=digest,
        normalized_blockers=(block.policy_code,),
        provenance=CaptureEvidenceProvenance(
            field_binding_authority_revision=_PROVENANCE_UNRESOLVED,
            source_configuration_version=_PROVENANCE_UNRESOLVED,
            captured_at=block.observed_at,
        ),
    )
    outcome = ExecutionPolicyBlocked(
        policy_code=block.policy_code,
        qualification_profile_id=block.qualification_profile_id,
        observed_policy_version=block.observed_policy_version,
        policy_observation_digest=block.policy_observation_digest,
        captured_attempt_digest=digest,
    )
    return CaptureTerminal(outcome=outcome, evidence=evidence)


def _context_error_to_attempt(error: ExecutionCaptureContextError) -> SealAttemptError:
    if error.code == UNSUPPORTED_LOCAL_IMPLEMENTATION:
        return UnsupportedLocalImplementation(error.detail)
    return ExecutionQualificationContextError(
        f"capture context error({error.code}): {error.detail}", cause_code=error.code
    )


def _require_policy_echo(result: object, policy: ResolvedSealPolicy) -> None:
    """capture adapter 가 요청 policy 를 그대로 echo 했는지 확인한다(fail-closed).

    stale/faulty adapter 가 다른 resolved policy 를 담은 결과를 봉인하지 못하게, complete·domain
    block 결과의 ``resolved_seal_policy`` 를 요청 policy 와 대조한다(불일치=attempt, request 미소비).
    """
    echoed = getattr(result, "resolved_seal_policy", None)
    if echoed is not None and echoed != policy:
        raise ExecutionQualificationContextError(
            "capture adapter 가 요청과 다른 resolved policy 를 echo 했다(fail-closed)"
        )


def classify_capture_result(
    result: CaptureExecutionQualificationResult, policy: ResolvedSealPolicy
) -> CaptureGateClassification:
    """capture gate 결과를 complete/terminal 로 가른다(context error 는 raise, request 미소비)."""
    if isinstance(result, CapturedExecutionInput):
        _require_policy_echo(result, policy)
        return CaptureComplete(result)
    if isinstance(result, CapturedExecutionDomainBlock):
        _require_policy_echo(result, policy)
        evidence = _attempt_evidence_of_domain_block(result)
        outcome = ExecutionQualificationBlocked(
            capture_evidence_ref=evidence.captured_attempt_digest,
            normalized_blockers=result.normalized_blockers,
            captured_execution_input_digest=None,
            captured_attempt_digest=evidence.captured_attempt_digest,
        )
        return CaptureTerminal(outcome=outcome, evidence=evidence)
    if isinstance(result, CapturedExecutionPolicyBlock):
        return _policy_block_evidence_and_outcome(result, policy)
    raise _context_error_to_attempt(result)


# ─── final gate verdict ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FinalPublish:
    candidate: PlanCandidate


@dataclass(frozen=True)
class FinalLedger:
    outcome: SealTerminalOutcome
    evidence: DurableSealCaptureEvidence


FinalVerdict = FinalPublish | FinalLedger


def _stale(candidate: PlanCandidate, reason: str, summary: WorkExecutionSummary) -> FinalLedger:
    return FinalLedger(
        outcome=StaleExecutionBasis(
            captured_execution_input_digest=candidate.captured_execution_input_digest,
            candidate_execution_basis_digest=candidate.execution_basis_digest,
            stale_reason=reason,
            observed_current_summary={
                "qualification_profile_id": summary.qualification_profile_id,
                "template_application_id": summary.template_application_id,
            },
        ),
        evidence=candidate.capture_evidence,
    )


def decide_final_verdict(
    candidate: CandidateCompilation,
    current_result: CaptureExecutionQualificationResult,
    current_compiled: CandidateCompilation | None,
    summary: WorkExecutionSummary,
) -> FinalVerdict:
    """candidate 가 사용한 exact contracts 로 재구성한 current 결과와 candidate 를 비교한다(순수).

    precedence: candidate Profile policy block → current not sealable → basis digest mismatch →
    publish/blocked. current context/integrity 복원 실패는 attempt 로 raise 한다. STALE 은 captured
    candidate 를 새 BLOCKED 로 rebase 하지 않는다 — current blocker 를 기록하지 않는다.
    """
    # 3. candidate Profile policy block(capture/final 사이 revocation 선형화).
    if isinstance(current_result, CapturedExecutionPolicyBlock):
        terminal = _policy_block_evidence_and_outcome(
            current_result, candidate.resolved_seal_policy
        )
        return FinalLedger(outcome=terminal.outcome, evidence=terminal.evidence)
    # 2. exact context/integrity 복원 실패 → attempt(no ledger).
    if isinstance(current_result, ExecutionCaptureContextError):
        raise _context_error_to_attempt(current_result)
    # capture adapter 가 candidate policy 를 그대로 echo 했는지 재확인(fail-closed).
    _require_policy_echo(current_result, candidate.resolved_seal_policy)
    # 4. current not sealable(domain block) → STALE, current blocker 를 기록하지 않는다.
    if isinstance(current_result, CapturedExecutionDomainBlock):
        return _verdict_current_not_sealable(candidate, summary)
    # current complete → current_compiled 로 비교.
    assert isinstance(current_result, CapturedExecutionInput)
    if current_compiled is None:  # pragma: no cover - runner 가 complete 면 항상 compile 한다
        raise ExecutionQualificationContextError("current complete capture 가 compile 되지 않았다")
    if isinstance(current_compiled, BlockedCandidate):
        return _verdict_current_blocked(candidate, current_compiled, summary)
    return _verdict_current_sealable(candidate, current_compiled, summary)


def _verdict_current_not_sealable(
    candidate: CandidateCompilation, summary: WorkExecutionSummary
) -> FinalVerdict:
    if isinstance(candidate, PlanCandidate):
        return _stale(candidate, STALE_CURRENT_BASIS_NOT_SEALABLE, summary)
    raise ExecutionQualificationContextError(
        "captured blocker 지만 current 가 seal 불가로 이동했다(재시도 가능)"
    )


def _verdict_current_blocked(
    candidate: CandidateCompilation,
    current: BlockedCandidate,
    summary: WorkExecutionSummary,
) -> FinalVerdict:
    if isinstance(candidate, PlanCandidate):
        # candidate 는 sealable 이었으나 current 는 blocker — not sealable STALE.
        return _stale(candidate, STALE_CURRENT_BASIS_NOT_SEALABLE, summary)
    # candidate·current 둘 다 blocked — 같은 exact input 이면 blocker 를 first-seen commit.
    if current.captured_execution_input_digest == candidate.captured_execution_input_digest:
        return FinalLedger(
            outcome=ExecutionQualificationBlocked(
                capture_evidence_ref=candidate.captured_execution_input_digest,
                normalized_blockers=candidate.normalized_blockers,
                captured_execution_input_digest=candidate.captured_execution_input_digest,
                captured_attempt_digest=None,
            ),
            evidence=candidate.capture_evidence,
        )
    raise ExecutionQualificationContextError(
        "captured blocker 의 semantic input 이 이동했다(재시도 가능)"
    )


def _verdict_current_sealable(
    candidate: CandidateCompilation,
    current: PlanCandidate,
    summary: WorkExecutionSummary,
) -> FinalVerdict:
    if isinstance(candidate, BlockedCandidate):
        # candidate 는 blocked 였는데 current 는 sealable — input 이 이동했다, 재판정.
        raise ExecutionQualificationContextError(
            "captured blocker 가 current 에서 sealable 로 이동했다(재시도 가능)"
        )
    # 5. basis digest equality — effective-only currentness(detached/inactive 는 같은 basis).
    if current.execution_basis_digest == candidate.execution_basis_digest:
        return FinalPublish(candidate)
    return _stale(candidate, STALE_DIGEST_MISMATCH, summary)


# ─── seal 성공 outcome(durable publication 없음) ────────────────────────────────────────
def sealed_outcome_for(candidate: PlanCandidate) -> ExecutionPlanSealed:
    """current candidate 에서 직접 seal 성공 outcome 을 낸다 — store commit·publication kind 없음."""
    return ExecutionPlanSealed(execution_basis_digest=candidate.execution_basis_digest)
