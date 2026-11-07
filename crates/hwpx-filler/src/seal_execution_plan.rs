//! Pure seal request identity and selector consistency gate.

use crate::canonical_execution_encoding::CANONICAL_ENCODING_VERSION;
use crate::canonical_execution_encoding::canonical_execution_digest;
use crate::execution_capture::{APPLIED_TEMPLATE_CANDIDATE, ResolvedSealPolicy};
use crate::execution_capture::{
    CaptureExecutionQualificationResult, CapturedExecutionDomainBlock, CapturedExecutionInput,
    CapturedExecutionPolicyBlock, ExecutionCaptureContextError, FieldBindingObservation,
    SelectionObservation, UNSUPPORTED_LOCAL_IMPLEMENTATION,
};
use crate::execution_compilation::COMPOSITION_POLICY_IDENTITY_MISMATCH;
use crate::execution_composition::composition_fingerprint;
use crate::execution_contract_set::{
    CaptureEvidenceProvenance, DurableSealCaptureEvidence, SealedExecutionPlanSemanticPayload,
    encode_durable_capture_evidence, execution_basis_digest,
};
use crate::execution_semantic_kernel::{
    KernelResult, SemanticKernelContextError, compile_sealed_plan_from_snapshot,
};
use crate::stored_execution_plan::RequestedVersionSelector;
use crate::stored_execution_plan::{
    CURRENT_BASIS_NOT_SEALABLE, DIGEST_MISMATCH, ExecutionPlanSealed, ExecutionPolicyBlocked,
    ExecutionQualificationBlocked, SealTerminalOutcome, StaleExecutionBasis,
};
use crate::text_render::python_repr;
use serde_json::Value;
use std::fmt;

pub const COMMAND_SCHEMA_VERSION: &str = "seal-execution-plan-command/v1";
pub const SUPPORTED_PLAN_SCHEMAS: [&str; 1] = ["hwpx-execution-plan/v2"];
pub const STALE_DIGEST_MISMATCH: &str = "DIGEST_MISMATCH";
pub const STALE_CURRENT_BASIS_NOT_SEALABLE: &str = "CURRENT_BASIS_NOT_SEALABLE";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealExecutionPlanCommand {
    pub workspace_instance_id: String,
    pub work_ref: String,
    pub request_id: String,
    pub requested_execution_base_kind: String,
    pub requested_execution_semantic_contract: RequestedVersionSelector,
    pub requested_plan_schema: RequestedVersionSelector,
    pub requested_canonical_encoding: RequestedVersionSelector,
}
impl SealExecutionPlanCommand {
    pub fn new(
        workspace_instance_id: impl Into<String>,
        work_ref: impl Into<String>,
        request_id: impl Into<String>,
    ) -> Result<Self, SealAttemptError> {
        let command = Self {
            workspace_instance_id: workspace_instance_id.into(),
            work_ref: work_ref.into(),
            request_id: request_id.into(),
            requested_execution_base_kind: APPLIED_TEMPLATE_CANDIDATE.into(),
            requested_execution_semantic_contract: RequestedVersionSelector::Auto,
            requested_plan_schema: RequestedVersionSelector::Auto,
            requested_canonical_encoding: RequestedVersionSelector::Auto,
        };
        command.validate()?;
        Ok(command)
    }
    pub fn validate(&self) -> Result<(), SealAttemptError> {
        for (name, value) in [
            ("workspace_instance_id", &self.workspace_instance_id),
            ("work_ref", &self.work_ref),
            ("request_id", &self.request_id),
        ] {
            if value.is_empty() {
                return Err(SealAttemptError::context(format!(
                    "{name} 는 비어 있지 않은 문자열이어야 한다"
                )));
            }
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkExecutionSummary {
    pub qualification_profile_id: String,
    pub template_application_id: String,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SealAttemptErrorKind {
    RouteResolution,
    Authorization,
    ExecutionQualificationContext,
    UnsupportedLocalImplementation,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealAttemptError {
    pub kind: SealAttemptErrorKind,
    pub detail: String,
    pub cause_code: Option<String>,
}
impl SealAttemptError {
    pub fn context(detail: impl Into<String>) -> Self {
        Self {
            kind: SealAttemptErrorKind::ExecutionQualificationContext,
            detail: detail.into(),
            cause_code: None,
        }
    }
    fn unsupported(detail: impl Into<String>) -> Self {
        Self {
            kind: SealAttemptErrorKind::UnsupportedLocalImplementation,
            detail: detail.into(),
            cause_code: None,
        }
    }
    pub fn context_code(detail: impl Into<String>, code: impl Into<String>) -> Self {
        Self {
            kind: SealAttemptErrorKind::ExecutionQualificationContext,
            detail: detail.into(),
            cause_code: Some(code.into()),
        }
    }
}
impl fmt::Display for SealAttemptError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for SealAttemptError {}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}
pub fn require_exact_selector_consistency(
    command: &SealExecutionPlanCommand,
    policy: &ResolvedSealPolicy,
) -> Result<(), SealAttemptError> {
    command.validate()?;
    if command.requested_execution_base_kind != policy.execution_base_kind {
        return Err(SealAttemptError::context(
            "resolved policy 의 execution_base_kind 가 요청과 불일치",
        ));
    }
    for (selector, actual, what) in [
        (
            &command.requested_execution_semantic_contract,
            policy.execution_semantic_contract_id.as_str(),
            "execution_semantic_contract",
        ),
        (
            &command.requested_plan_schema,
            policy.plan_schema_version.as_str(),
            "plan_schema",
        ),
        (
            &command.requested_canonical_encoding,
            policy.canonical_encoding_version.as_str(),
            "canonical_encoding",
        ),
    ] {
        if let RequestedVersionSelector::Exact(requested) = selector
            && requested != actual
        {
            return Err(SealAttemptError::context(format!(
                "resolved policy 의 {what} 가 EXACT 요청과 불일치"
            )));
        }
    }
    if !SUPPORTED_PLAN_SCHEMAS.contains(&policy.plan_schema_version.as_str()) {
        return Err(SealAttemptError::unsupported(format!(
            "미지원 plan schema(latest fallback 없음): {}",
            repr(&policy.plan_schema_version)
        )));
    }
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION {
        return Err(SealAttemptError::unsupported(format!(
            "미지원 canonical encoding: {}",
            repr(&policy.canonical_encoding_version)
        )));
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlanCandidate {
    pub qualification_profile_id: String,
    pub template_application_id: String,
    pub resolved_seal_policy: ResolvedSealPolicy,
    pub execution_basis_digest: String,
    pub plan_payload: Box<SealedExecutionPlanSemanticPayload>,
    pub capture_evidence: DurableSealCaptureEvidence,
    pub captured_execution_input_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BlockedCandidate {
    pub qualification_profile_id: String,
    pub template_application_id: String,
    pub resolved_seal_policy: ResolvedSealPolicy,
    pub normalized_blockers: Vec<String>,
    pub capture_evidence: DurableSealCaptureEvidence,
    pub captured_execution_input_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CandidateCompilation {
    Plan(Box<PlanCandidate>),
    Blocked(Box<BlockedCandidate>),
}
impl CandidateCompilation {
    fn policy(&self) -> &ResolvedSealPolicy {
        match self {
            Self::Plan(item) => &item.resolved_seal_policy,
            Self::Blocked(item) => &item.resolved_seal_policy,
        }
    }
}
fn config_version_ref(selection: &crate::slot_selection_input::SlotSelectionInput) -> String {
    use crate::slot_selection_input::SlotSelectionInput;
    match selection {
        SlotSelectionInput::Slotted(item) => item.source_configuration_version.to_string(),
        SlotSelectionInput::Slotless(item) => item
            .source_configuration_version
            .map_or_else(|| "SLOTLESS_NO_CONFIGURATION".into(), |v| v.to_string()),
    }
}
pub fn complete_capture_evidence(
    captured: &CapturedExecutionInput,
) -> Result<DurableSealCaptureEvidence, SealAttemptError> {
    if captured.captured_execution_input_digest.is_empty() {
        return Err(SealAttemptError::context(
            "complete capture 에 captured_execution_input_digest 가 없다",
        ));
    }
    let evidence = DurableSealCaptureEvidence::Complete {
        semantic_projection: captured
            .captured_execution_input_semantic_projection
            .clone(),
        semantic_digest: captured.captured_execution_input_digest.clone(),
        provenance: CaptureEvidenceProvenance {
            field_binding_authority_revision: captured
                .field_binding
                .field_binding_authority_revision
                .clone(),
            source_configuration_version: config_version_ref(&captured.selection),
            captured_at: captured.captured_at.clone(),
        },
    };
    encode_durable_capture_evidence(&evidence).map_err(|e| SealAttemptError::context(e.detail))?;
    Ok(evidence)
}
pub fn require_exact_selector_consistency_for_compile(
    policy: &ResolvedSealPolicy,
) -> Result<(), SealAttemptError> {
    if !SUPPORTED_PLAN_SCHEMAS.contains(&policy.plan_schema_version.as_str()) {
        return Err(SealAttemptError::unsupported(format!(
            "미지원 plan schema: {}",
            repr(&policy.plan_schema_version)
        )));
    }
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION {
        return Err(SealAttemptError::unsupported(format!(
            "미지원 canonical encoding: {}",
            repr(&policy.canonical_encoding_version)
        )));
    }
    Ok(())
}
fn kernel_attempt(error: SemanticKernelContextError) -> SealAttemptError {
    SealAttemptError::context_code(
        format!(
            "compile context error({}): {}",
            error.cause_code, error.detail
        ),
        error.cause_code,
    )
}
pub fn compile_candidate(
    captured: &CapturedExecutionInput,
) -> Result<CandidateCompilation, SealAttemptError> {
    let policy = &captured.resolved_seal_policy;
    require_exact_selector_consistency_for_compile(policy)?;
    let fingerprint = composition_fingerprint(
        &policy.composition_contract_id,
        &policy.native_primitive_contract_id,
    )
    .map_err(|e| {
        SealAttemptError::unsupported(format!(
            "미지원 composition/native primitive contract: {}",
            e.detail
        ))
    })?;
    if fingerprint != policy.composition_theorem_evidence_manifest_digest {
        return Err(SealAttemptError::context_code(
            "composition fingerprint 가 resolved policy 와 불일치",
            COMPOSITION_POLICY_IDENTITY_MISMATCH,
        ));
    }
    let value = compile_sealed_plan_from_snapshot(captured).map_err(kernel_attempt)?;
    let evidence = complete_capture_evidence(captured)?;
    let digest = captured.captured_execution_input_digest.clone();
    let qualification = &captured.template.qualification;
    let applied = &captured.template.applied;
    match value {
        KernelResult::Blocked(block) => {
            Ok(CandidateCompilation::Blocked(Box::new(BlockedCandidate {
                qualification_profile_id: block.qualification_profile_id,
                template_application_id: block.template_application_id,
                resolved_seal_policy: policy.clone(),
                normalized_blockers: block.normalized_blockers,
                capture_evidence: evidence,
                captured_execution_input_digest: digest,
            })))
        }
        KernelResult::Plan(plan) => {
            let basis_digest = execution_basis_digest(&plan.execution_basis)
                .map_err(|e| SealAttemptError::context(e.detail))?;
            Ok(CandidateCompilation::Plan(Box::new(PlanCandidate {
                qualification_profile_id: qualification.qualification_profile_id.clone(),
                template_application_id: applied.template_application_id.clone(),
                resolved_seal_policy: policy.clone(),
                execution_basis_digest: basis_digest,
                plan_payload: plan,
                capture_evidence: evidence,
                captured_execution_input_digest: digest,
            })))
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CaptureGateClassification {
    Complete(Box<CapturedExecutionInput>),
    Terminal {
        outcome: SealTerminalOutcome,
        evidence: Box<DurableSealCaptureEvidence>,
    },
}
fn policy_block_terminal(
    block: &CapturedExecutionPolicyBlock,
    policy: &ResolvedSealPolicy,
) -> Result<CaptureGateClassification, SealAttemptError> {
    let projection = serde_json::json!({"policy_block":{
        "policy_code":block.policy_code,
        "qualification_profile_id":block.qualification_profile_id,
        "observed_policy_version":block.observed_policy_version,
        "policy_observation_digest":block.policy_observation_digest,
        "execution_base_kind":policy.execution_base_kind,
    }});
    let digest = canonical_execution_digest(&projection)
        .map_err(|e| SealAttemptError::context(e.to_string()))?;
    let evidence = DurableSealCaptureEvidence::Attempt {
        semantic_projection: projection,
        semantic_digest: digest.clone(),
        normalized_blockers: vec![block.policy_code.clone()],
        provenance: CaptureEvidenceProvenance {
            field_binding_authority_revision: "unresolved".into(),
            source_configuration_version: "unresolved".into(),
            captured_at: block.observed_at.clone(),
        },
    };
    encode_durable_capture_evidence(&evidence).map_err(|e| SealAttemptError::context(e.detail))?;
    Ok(CaptureGateClassification::Terminal {
        outcome: SealTerminalOutcome::PolicyBlocked(ExecutionPolicyBlocked {
            policy_code: block.policy_code.clone(),
            qualification_profile_id: block.qualification_profile_id.clone(),
            observed_policy_version: block.observed_policy_version.clone(),
            policy_observation_digest: block.policy_observation_digest.clone(),
            captured_attempt_digest: Some(digest),
        }),
        evidence: Box::new(evidence),
    })
}
fn capture_context_attempt(error: ExecutionCaptureContextError) -> SealAttemptError {
    if error.code == UNSUPPORTED_LOCAL_IMPLEMENTATION {
        SealAttemptError::unsupported(error.detail)
    } else {
        SealAttemptError::context_code(
            format!("capture context error({}): {}", error.code, error.detail),
            error.code,
        )
    }
}
fn require_policy_echo(
    result: &CaptureExecutionQualificationResult,
    policy: &ResolvedSealPolicy,
) -> Result<(), SealAttemptError> {
    let echoed = match result {
        CaptureExecutionQualificationResult::Complete(item) => Some(&item.resolved_seal_policy),
        CaptureExecutionQualificationResult::DomainBlocked(item) => {
            Some(&item.resolved_seal_policy)
        }
        _ => None,
    };
    if echoed.is_some_and(|echoed| echoed != policy) {
        return Err(SealAttemptError::context(
            "capture adapter 가 요청과 다른 resolved policy 를 echo 했다(fail-closed)",
        ));
    }
    Ok(())
}
fn domain_block_terminal(
    block: &CapturedExecutionDomainBlock,
) -> Result<CaptureGateClassification, SealAttemptError> {
    if block.captured_attempt_digest.is_empty() {
        return Err(SealAttemptError::context(
            "domain block 에 captured_attempt_digest 가 없다",
        ));
    }
    let revision = match &block.field_binding_observation {
        FieldBindingObservation::Captured(binding) => {
            binding.field_binding_authority_revision.clone()
        }
        FieldBindingObservation::DomainBlocked { .. } => "unresolved".into(),
    };
    let config_ref = match &block.selection_observation {
        SelectionObservation::Captured(selection) => config_version_ref(selection),
        SelectionObservation::DomainBlocked { .. } => "unresolved".into(),
    };
    let evidence = DurableSealCaptureEvidence::Attempt {
        semantic_projection: block.captured_attempt_semantic_projection.clone(),
        semantic_digest: block.captured_attempt_digest.clone(),
        normalized_blockers: block.normalized_blockers.clone(),
        provenance: CaptureEvidenceProvenance {
            field_binding_authority_revision: revision,
            source_configuration_version: config_ref,
            captured_at: block.captured_at.clone(),
        },
    };
    encode_durable_capture_evidence(&evidence).map_err(|e| SealAttemptError::context(e.detail))?;
    Ok(CaptureGateClassification::Terminal {
        outcome: SealTerminalOutcome::QualificationBlocked(ExecutionQualificationBlocked {
            capture_evidence_ref: block.captured_attempt_digest.clone(),
            normalized_blockers: block.normalized_blockers.clone(),
            captured_execution_input_digest: None,
            captured_attempt_digest: Some(block.captured_attempt_digest.clone()),
        }),
        evidence: Box::new(evidence),
    })
}
pub fn classify_capture_result(
    result: CaptureExecutionQualificationResult,
    policy: &ResolvedSealPolicy,
) -> Result<CaptureGateClassification, SealAttemptError> {
    require_policy_echo(&result, policy)?;
    match result {
        CaptureExecutionQualificationResult::Complete(item) => {
            Ok(CaptureGateClassification::Complete(item))
        }
        CaptureExecutionQualificationResult::DomainBlocked(item) => domain_block_terminal(&item),
        CaptureExecutionQualificationResult::PolicyBlocked(item) => {
            policy_block_terminal(&item, policy)
        }
        CaptureExecutionQualificationResult::ContextError(item) => {
            Err(capture_context_attempt(item))
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FinalVerdict {
    Publish(Box<PlanCandidate>),
    Ledger {
        outcome: SealTerminalOutcome,
        evidence: Box<DurableSealCaptureEvidence>,
    },
}
fn stale(candidate: PlanCandidate, reason: &str, summary: &WorkExecutionSummary) -> FinalVerdict {
    FinalVerdict::Ledger {
        outcome: SealTerminalOutcome::Stale(StaleExecutionBasis {
            captured_execution_input_digest: candidate.captured_execution_input_digest.clone(),
            candidate_execution_basis_digest: candidate.execution_basis_digest.clone(),
            stale_reason: reason.into(),
            observed_current_summary: Some(serde_json::json!({
                "qualification_profile_id":summary.qualification_profile_id,
                "template_application_id":summary.template_application_id,
            })),
        }),
        evidence: Box::new(candidate.capture_evidence),
    }
}
pub fn decide_final_verdict(
    candidate: CandidateCompilation,
    current_result: CaptureExecutionQualificationResult,
    current_compiled: Option<CandidateCompilation>,
    summary: &WorkExecutionSummary,
) -> Result<FinalVerdict, SealAttemptError> {
    if let CaptureExecutionQualificationResult::PolicyBlocked(block) = &current_result {
        let terminal = policy_block_terminal(block, candidate.policy())?;
        let CaptureGateClassification::Terminal { outcome, evidence } = terminal else {
            unreachable!()
        };
        return Ok(FinalVerdict::Ledger { outcome, evidence });
    }
    if let CaptureExecutionQualificationResult::ContextError(error) = current_result {
        return Err(capture_context_attempt(error));
    }
    require_policy_echo(&current_result, candidate.policy())?;
    if matches!(
        current_result,
        CaptureExecutionQualificationResult::DomainBlocked(_)
    ) {
        return match candidate {
            CandidateCompilation::Plan(item) => {
                Ok(stale(*item, CURRENT_BASIS_NOT_SEALABLE, summary))
            }
            CandidateCompilation::Blocked(_) => Err(SealAttemptError::context(
                "captured blocker 지만 current 가 seal 불가로 이동했다(재시도 가능)",
            )),
        };
    }
    let Some(current) = current_compiled else {
        return Err(SealAttemptError::context(
            "current complete capture 가 compile 되지 않았다",
        ));
    };
    compare_compiled_candidates(candidate, current, summary)
}

fn compare_compiled_candidates(
    candidate: CandidateCompilation,
    current: CandidateCompilation,
    summary: &WorkExecutionSummary,
) -> Result<FinalVerdict, SealAttemptError> {
    match (candidate, current) {
        (CandidateCompilation::Plan(item), CandidateCompilation::Plan(current)) => {
            if item.execution_basis_digest == current.execution_basis_digest {
                Ok(FinalVerdict::Publish(item))
            } else {
                Ok(stale(*item, DIGEST_MISMATCH, summary))
            }
        }
        (CandidateCompilation::Plan(item), CandidateCompilation::Blocked(_)) => {
            Ok(stale(*item, CURRENT_BASIS_NOT_SEALABLE, summary))
        }
        (CandidateCompilation::Blocked(item), CandidateCompilation::Blocked(current)) => {
            if item.captured_execution_input_digest != current.captured_execution_input_digest {
                return Err(SealAttemptError::context(
                    "captured blocker 의 semantic input 이 이동했다(재시도 가능)",
                ));
            }
            Ok(FinalVerdict::Ledger {
                outcome: SealTerminalOutcome::QualificationBlocked(ExecutionQualificationBlocked {
                    capture_evidence_ref: item.captured_execution_input_digest.clone(),
                    normalized_blockers: item.normalized_blockers.clone(),
                    captured_execution_input_digest: Some(
                        item.captured_execution_input_digest.clone(),
                    ),
                    captured_attempt_digest: None,
                }),
                evidence: Box::new(item.capture_evidence),
            })
        }
        (CandidateCompilation::Blocked(_), CandidateCompilation::Plan(_)) => {
            Err(SealAttemptError::context(
                "captured blocker 가 current 에서 sealable 로 이동했다(재시도 가능)",
            ))
        }
    }
}
pub fn sealed_outcome_for(candidate: PlanCandidate) -> ExecutionPlanSealed {
    ExecutionPlanSealed {
        execution_basis_digest: candidate.execution_basis_digest,
        plan_payload: Some(*candidate.plan_payload),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::execution_capture::{JudgeCapturedExecutionInput, judge_captured_execution};
    use crate::execution_semantic_kernel::{
        compute_execution_snapshot,
        tests::{authority, rebind},
    };
    use crate::shipping_seal_policy::resolve_shipping_policy;
    use crate::slot_selection_input::SlotSelectionInput;

    pub(crate) fn snapshot(option: &str, unbound: bool) -> CapturedExecutionInput {
        let mut input = authority("normal", option);
        if unbound {
            rebind(&mut input, true);
        }
        compute_execution_snapshot(&input).unwrap()
    }

    pub(crate) fn domain_block(selection_blocked: bool) -> CaptureExecutionQualificationResult {
        let input = authority("normal", "o1");
        judge_captured_execution(JudgeCapturedExecutionInput {
            workspace_instance_id: input.workspace_instance_id,
            work_authority_id: input.work_authority_id,
            expected_template_application_id: input.expected_template_application_id,
            expected_profile_id: input.expected_profile_id,
            resolved_seal_policy: input.resolved_seal_policy,
            template: input.template,
            selection_observation: if selection_blocked {
                SelectionObservation::DomainBlocked {
                    blocker_code: "SLOT_CONFIGURATION_INCOMPLETE".into(),
                    detail: "incomplete".into(),
                }
            } else {
                SelectionObservation::Captured(input.selection)
            },
            field_binding_observation: if selection_blocked {
                FieldBindingObservation::Captured(Box::new(input.field_binding))
            } else {
                FieldBindingObservation::DomainBlocked {
                    blocker_code: "ACTIVE_FIELD_UNBOUND".into(),
                    detail: "unbound".into(),
                }
            },
            captured_at: input.captured_at,
            policy_block: None,
        })
    }

    fn summary(input: &CapturedExecutionInput) -> WorkExecutionSummary {
        WorkExecutionSummary {
            qualification_profile_id: input
                .template
                .qualification
                .qualification_profile_id
                .clone(),
            template_application_id: input.template.applied.template_application_id.clone(),
        }
    }

    #[test]
    fn final_gate_compares_effective_basis_and_never_rebases_blocked_candidates() {
        let initial = snapshot("o1", false);
        let candidate = compile_candidate(&initial).unwrap();
        let exact = summary(&initial);
        let mut detached = authority("normal", "o1");
        let SlotSelectionInput::Slotted(selection) = &mut detached.selection else {
            unreachable!()
        };
        selection.declared_selection_digest = "sha256:detached-only".into();
        selection.source_configuration_version += 1;
        let detached = compute_execution_snapshot(&detached).unwrap();
        let different = snapshot("o2", false);
        let unbound = snapshot("o2", true);
        for (current, expected) in [
            (&initial, None),
            (&detached, None),
            (&different, Some(DIGEST_MISMATCH)),
            (&unbound, Some(CURRENT_BASIS_NOT_SEALABLE)),
        ] {
            let verdict = decide_final_verdict(
                candidate.clone(),
                CaptureExecutionQualificationResult::Complete(Box::new(current.clone())),
                Some(compile_candidate(current).unwrap()),
                &exact,
            )
            .unwrap();
            match (verdict, expected) {
                (FinalVerdict::Publish(result), None) => {
                    let CandidateCompilation::Plan(original) = &candidate else {
                        unreachable!()
                    };
                    assert_eq!(&result, original);
                    assert_eq!(
                        sealed_outcome_for(*result).plan_payload.as_ref(),
                        Some(original.plan_payload.as_ref())
                    );
                }
                (
                    FinalVerdict::Ledger {
                        outcome: SealTerminalOutcome::Stale(stale),
                        ..
                    },
                    Some(reason),
                ) => {
                    assert_eq!(stale.stale_reason, reason);
                    assert_eq!(
                        stale.captured_execution_input_digest,
                        initial.captured_execution_input_digest
                    );
                    assert_eq!(
                        stale.observed_current_summary.unwrap()["template_application_id"],
                        exact.template_application_id
                    );
                }
                _ => panic!("wrong final verdict"),
            }
        }
        let blocked = compile_candidate(&unbound).unwrap();
        let unchanged = decide_final_verdict(
            blocked.clone(),
            CaptureExecutionQualificationResult::Complete(Box::new(unbound.clone())),
            Some(blocked.clone()),
            &exact,
        )
        .unwrap();
        let FinalVerdict::Ledger {
            outcome: SealTerminalOutcome::QualificationBlocked(outcome),
            ..
        } = unchanged
        else {
            panic!("unchanged blocker")
        };
        assert_eq!(outcome.normalized_blockers, ["ACTIVE_FIELD_UNBOUND"]);
        assert_eq!(
            outcome.captured_execution_input_digest,
            Some(unbound.captured_execution_input_digest)
        );
        let mut changed_block = blocked.clone();
        let CandidateCompilation::Blocked(item) = &mut changed_block else {
            unreachable!()
        };
        item.captured_execution_input_digest = "sha256:changed".into();
        for current in [Some(changed_block), Some(candidate.clone()), None] {
            assert!(
                decide_final_verdict(
                    blocked.clone(),
                    CaptureExecutionQualificationResult::Complete(Box::new(initial.clone())),
                    current,
                    &exact
                )
                .is_err()
            );
        }
        assert!(decide_final_verdict(blocked, domain_block(true), None, &exact).is_err());
        let FinalVerdict::Ledger {
            outcome: SealTerminalOutcome::Stale(stale),
            ..
        } = decide_final_verdict(candidate, domain_block(true), None, &exact).unwrap()
        else {
            panic!("must be stale")
        };
        assert_eq!(stale.stale_reason, CURRENT_BASIS_NOT_SEALABLE);
    }

    #[test]
    fn capture_evidence_preserves_provenance_and_refuses_missing_digest_or_policy_echo() {
        let input = snapshot("o1", false);
        let policy = &input.resolved_seal_policy;
        let complete = complete_capture_evidence(&input).unwrap();
        let DurableSealCaptureEvidence::Complete {
            semantic_digest,
            provenance,
            ..
        } = complete
        else {
            unreachable!()
        };
        assert_eq!(semantic_digest, input.captured_execution_input_digest);
        assert_eq!(provenance.source_configuration_version, "3");
        assert_eq!(
            provenance.field_binding_authority_revision,
            input.field_binding.field_binding_authority_revision
        );
        let mut broken = input.clone();
        broken.captured_execution_input_digest.clear();
        assert!(complete_capture_evidence(&broken).is_err());
        let mut wrong_policy = policy.clone();
        wrong_policy.policy_resolution_version = "tampered".into();
        assert!(
            classify_capture_result(
                CaptureExecutionQualificationResult::Complete(Box::new(input.clone())),
                &wrong_policy
            )
            .is_err()
        );
        for selection_blocked in [false, true] {
            let block = domain_block(selection_blocked);
            assert!(classify_capture_result(block.clone(), &wrong_policy).is_err());
            let CaptureGateClassification::Terminal { outcome, evidence } =
                classify_capture_result(block.clone(), policy).unwrap()
            else {
                panic!("domain terminal")
            };
            let SealTerminalOutcome::QualificationBlocked(outcome) = outcome else {
                panic!("domain outcome")
            };
            let DurableSealCaptureEvidence::Attempt {
                provenance,
                semantic_digest,
                ..
            } = *evidence
            else {
                panic!("attempt evidence")
            };
            assert_eq!(outcome.captured_attempt_digest, Some(semantic_digest));
            assert_eq!(
                provenance.source_configuration_version == "unresolved",
                selection_blocked
            );
            assert_eq!(
                provenance.field_binding_authority_revision == "unresolved",
                !selection_blocked
            );
            let CaptureExecutionQualificationResult::DomainBlocked(mut broken) = block else {
                unreachable!()
            };
            broken.captured_attempt_digest.clear();
            assert!(
                classify_capture_result(
                    CaptureExecutionQualificationResult::DomainBlocked(broken),
                    policy
                )
                .is_err()
            );
        }
    }

    #[test]
    fn selectors_compile_and_final_context_failures_keep_their_error_class() {
        let input = snapshot("o1", false);
        let exact = summary(&input);
        let policy = &input.resolved_seal_policy;
        for axis in 0..4 {
            let mut request = SealExecutionPlanCommand::new("ws-1", "work-1", "r").unwrap();
            match axis {
                0 => request.requested_execution_base_kind = "other".into(),
                1 => {
                    request.requested_execution_semantic_contract =
                        RequestedVersionSelector::exact("other").unwrap()
                }
                2 => {
                    request.requested_plan_schema =
                        RequestedVersionSelector::exact("other").unwrap()
                }
                _ => {
                    request.requested_canonical_encoding =
                        RequestedVersionSelector::exact("other").unwrap()
                }
            }
            assert_eq!(
                require_exact_selector_consistency(&request, policy)
                    .unwrap_err()
                    .kind,
                SealAttemptErrorKind::ExecutionQualificationContext
            );
        }
        for (axis, expected) in [
            (0, SealAttemptErrorKind::UnsupportedLocalImplementation),
            (1, SealAttemptErrorKind::UnsupportedLocalImplementation),
            (2, SealAttemptErrorKind::UnsupportedLocalImplementation),
            (3, SealAttemptErrorKind::ExecutionQualificationContext),
            (4, SealAttemptErrorKind::ExecutionQualificationContext),
        ] {
            let mut broken = input.clone();
            match axis {
                0 => broken.resolved_seal_policy.plan_schema_version = "unknown".into(),
                1 => broken.resolved_seal_policy.canonical_encoding_version = "unknown".into(),
                2 => broken.resolved_seal_policy.composition_contract_id = "unknown".into(),
                3 => {
                    broken
                        .resolved_seal_policy
                        .composition_theorem_evidence_manifest_digest = "wrong".into()
                }
                _ => {
                    let SlotSelectionInput::Slotted(selection) = &mut broken.selection else {
                        unreachable!()
                    };
                    selection.template_structure_digest = "wrong".into();
                }
            }
            assert_eq!(
                compile_candidate(&broken).unwrap_err().kind,
                expected,
                "axis {axis}"
            );
        }
        for (code, expected) in [
            (
                UNSUPPORTED_LOCAL_IMPLEMENTATION,
                SealAttemptErrorKind::UnsupportedLocalImplementation,
            ),
            (
                "SELECTION_CONTRACT_INTEGRITY_ERROR",
                SealAttemptErrorKind::ExecutionQualificationContext,
            ),
        ] {
            let current =
                CaptureExecutionQualificationResult::ContextError(ExecutionCaptureContextError {
                    code: code.into(),
                    detail: "context".into(),
                });
            assert_eq!(
                classify_capture_result(current.clone(), policy)
                    .unwrap_err()
                    .kind,
                expected
            );
            assert_eq!(
                decide_final_verdict(compile_candidate(&input).unwrap(), current, None, &exact)
                    .unwrap_err()
                    .kind,
                expected
            );
        }
        let mut tampered = input.clone();
        tampered.resolved_seal_policy.policy_resolution_version = "tampered".into();
        assert!(
            decide_final_verdict(
                compile_candidate(&input).unwrap(),
                CaptureExecutionQualificationResult::Complete(Box::new(tampered)),
                Some(compile_candidate(&input).unwrap()),
                &exact
            )
            .is_err()
        );
    }

    #[test]
    fn policy_revocation_precedes_current_compilation_and_exact_selector_mismatch_refuses() {
        let mut request = SealExecutionPlanCommand::new("workspace", "work", "request").unwrap();
        let summary = WorkExecutionSummary {
            qualification_profile_id: "hwpx-template-qualification-v4".into(),
            template_application_id: "application".into(),
        };
        let policy = resolve_shipping_policy(&request, &summary);
        request.requested_plan_schema = RequestedVersionSelector::exact("future/v3").unwrap();
        let mismatch = require_exact_selector_consistency(&request, &policy).unwrap_err();
        assert_eq!(
            mismatch.detail,
            "resolved policy 의 plan_schema 가 EXACT 요청과 불일치"
        );
        let candidate = CandidateCompilation::Blocked(Box::new(BlockedCandidate {
            qualification_profile_id: summary.qualification_profile_id.clone(),
            template_application_id: summary.template_application_id.clone(),
            resolved_seal_policy: policy.clone(),
            normalized_blockers: vec!["MISSING_BINDING".into()],
            capture_evidence: DurableSealCaptureEvidence::Complete {
                semantic_projection: serde_json::json!({}),
                semantic_digest: "sha256:captured".into(),
                provenance: CaptureEvidenceProvenance {
                    field_binding_authority_revision: "1".into(),
                    source_configuration_version: "1".into(),
                    captured_at: "2026-01-01T00:00:00".into(),
                },
            },
            captured_execution_input_digest: "sha256:captured".into(),
        }));
        let result = decide_final_verdict(
            candidate,
            CaptureExecutionQualificationResult::PolicyBlocked(CapturedExecutionPolicyBlock {
                policy_code: "POLICY_REVOKED".into(),
                observed_at: "2026-01-01T00:00:01".into(),
                qualification_profile_id: Some(summary.qualification_profile_id.clone()),
                observed_policy_version: Some("policy/v2".into()),
                policy_observation_digest: Some("sha256:policy".into()),
                captured_attempt_digest: None,
            }),
            None,
            &summary,
        )
        .unwrap();
        let FinalVerdict::Ledger {
            outcome: SealTerminalOutcome::PolicyBlocked(outcome),
            evidence: _,
        } = result
        else {
            panic!("revocation must be terminal");
        };
        assert_eq!(outcome.policy_code, "POLICY_REVOKED");
        assert!(outcome.captured_attempt_digest.is_some());
    }
}
