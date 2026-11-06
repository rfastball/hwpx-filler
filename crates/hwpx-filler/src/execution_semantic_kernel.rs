//! Pure exact authority to sealed execution plan. No store, clock or native mutation.

use crate::canonical_execution_encoding::CANONICAL_ENCODING_VERSION;
use crate::execution_capture::{
    CaptureExecutionQualificationResult, CapturedExecutionInput, CapturedTemplateExecutionInput,
    FieldBindingObservation, JudgeCapturedExecutionInput, ResolvedSealPolicy, SelectionObservation,
    judge_captured_execution,
};
use crate::execution_compilation::{
    COMPOSITION_POLICY_IDENTITY_MISMATCH, QualifiedExecutionCompilation,
    QualifyAndCompileExecutionResult, qualify_and_compile_execution,
};
use crate::execution_composition::{
    CompositionPremiseVerificationResult, admit_composition_premises, composition_fingerprint,
    resolve_native_primitive_contract,
};
use crate::execution_contract_set::{
    ContractRoles, ExecutionBasis, SealedExecutionPlanSemanticPayload,
    build_execution_contract_set, build_sealed_plan, qualification_profile_semantic_digest,
    verify_sealed_plan_integrity,
};
use crate::field_binding_input::FieldBindingInput;
use crate::seal_execution_plan::SUPPORTED_PLAN_SCHEMAS;
use crate::slot_selection_input::SlotSelectionInput;
use crate::text_render::python_repr;
use serde_json::Value;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticKernelContextError {
    pub detail: String,
    pub cause_code: String,
}
impl SemanticKernelContextError {
    fn new(detail: impl Into<String>, code: impl Into<String>) -> Self {
        Self {
            detail: detail.into(),
            cause_code: code.into(),
        }
    }
}
impl fmt::Display for SemanticKernelContextError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for SemanticKernelContextError {}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DurableExecutionAuthority {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub expected_template_application_id: String,
    pub expected_profile_id: String,
    pub resolved_seal_policy: ResolvedSealPolicy,
    pub template: CapturedTemplateExecutionInput,
    pub selection: SlotSelectionInput,
    pub field_binding: FieldBindingInput,
    pub captured_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealedExecutionPlanBlocked {
    pub qualification_profile_id: String,
    pub template_application_id: String,
    pub normalized_blockers: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum KernelResult {
    Plan(Box<SealedExecutionPlanSemanticPayload>),
    Blocked(SealedExecutionPlanBlocked),
}
pub fn compute_execution_snapshot(
    authority: &DurableExecutionAuthority,
) -> Result<CapturedExecutionInput, SemanticKernelContextError> {
    let result = judge_captured_execution(JudgeCapturedExecutionInput {
        workspace_instance_id: authority.workspace_instance_id.clone(),
        work_authority_id: authority.work_authority_id.clone(),
        expected_template_application_id: authority.expected_template_application_id.clone(),
        expected_profile_id: authority.expected_profile_id.clone(),
        resolved_seal_policy: authority.resolved_seal_policy.clone(),
        template: authority.template.clone(),
        selection_observation: SelectionObservation::Captured(authority.selection.clone()),
        field_binding_observation: FieldBindingObservation::Captured(Box::new(
            authority.field_binding.clone(),
        )),
        captured_at: authority.captured_at.clone(),
        policy_block: None,
    });
    match result {
        CaptureExecutionQualificationResult::Complete(snapshot) => Ok(*snapshot),
        CaptureExecutionQualificationResult::ContextError(error) => {
            Err(SemanticKernelContextError::new(
                format!(
                    "durable authority 로 execution snapshot 을 확정하지 못했다: {}",
                    error.detail
                ),
                error.code,
            ))
        }
        CaptureExecutionQualificationResult::DomainBlocked(_) => {
            Err(SemanticKernelContextError::new(
                "durable authority 로 execution snapshot 을 확정하지 못했다: CapturedExecutionDomainBlock",
                "",
            ))
        }
        CaptureExecutionQualificationResult::PolicyBlocked(error) => {
            Err(SemanticKernelContextError::new(
                "durable authority 로 execution snapshot 을 확정하지 못했다: CapturedExecutionPolicyBlock",
                error.policy_code,
            ))
        }
    }
}
fn build_execution_basis(
    captured: &CapturedExecutionInput,
    compiled: &QualifiedExecutionCompilation,
) -> Result<ExecutionBasis, SemanticKernelContextError> {
    let policy = &captured.resolved_seal_policy;
    let roles = ContractRoles {
        slot_selection_contract_id: captured.selection.selection_semantic_contract_id().into(),
        field_binding_contract_id: captured
            .field_binding
            .field_binding_semantic_contract_id
            .clone(),
        raw_record_contract_id: policy.raw_record_contract_id.clone(),
        source_schema_contract_id: captured.field_binding.source_schema_contract_id.clone(),
        execution_semantic_contract_id: policy.execution_semantic_contract_id.clone(),
        binding_value_contract_id: policy.binding_value_contract_id.clone(),
        record_validation_contract_id: policy.record_validation_contract_id.clone(),
        record_review_contract_id: policy.record_review_contract_id.clone(),
        document_value_resolution_contract_id: policy.document_value_resolution_contract_id.clone(),
        composition_contract_id: policy.composition_contract_id.clone(),
        native_primitive_contract_id: policy.native_primitive_contract_id.clone(),
        materialization_base_contract_id: policy.materialization_base_contract_id.clone(),
        materialization_contract_id: policy.materialization_contract_id.clone(),
        composition_theorem_evidence_manifest_digest: policy
            .composition_theorem_evidence_manifest_digest
            .clone(),
    };
    let contracts = build_execution_contract_set(roles)
        .map_err(|e| SemanticKernelContextError::new(e.detail, ""))?;
    let semantic_digest = qualification_profile_semantic_digest(
        &captured
            .template
            .qualification
            .qualification_profile_semantic_payload,
    )
    .map_err(|e| SemanticKernelContextError::new(e.detail, ""))?;
    Ok(ExecutionBasis {
        workspace_instance_id: captured.workspace_instance_id.clone(),
        work_authority_id: captured.work_authority_id.clone(),
        qualification_profile_semantic_digest: semantic_digest,
        template: compiled.exact_template_execution_basis.clone(),
        contracts,
        selection: compiled.effective_selection_basis.clone(),
        field_binding: compiled.effective_field_binding_basis.clone(),
    })
}
fn require_supported_plan_identity(
    policy: &ResolvedSealPolicy,
) -> Result<(), SemanticKernelContextError> {
    if !SUPPORTED_PLAN_SCHEMAS.contains(&policy.plan_schema_version.as_str()) {
        return Err(SemanticKernelContextError::new(
            format!("미지원 plan schema: {}", repr(&policy.plan_schema_version)),
            "",
        ));
    }
    if policy.canonical_encoding_version != CANONICAL_ENCODING_VERSION {
        return Err(SemanticKernelContextError::new(
            format!(
                "미지원 canonical encoding: {}",
                repr(&policy.canonical_encoding_version)
            ),
            "",
        ));
    }
    Ok(())
}
pub fn compile_sealed_plan_from_snapshot(
    captured: &CapturedExecutionInput,
) -> Result<KernelResult, SemanticKernelContextError> {
    let policy = &captured.resolved_seal_policy;
    let qualification = &captured.template.qualification;
    require_supported_plan_identity(policy)?;
    let primitive = resolve_native_primitive_contract(&policy.native_primitive_contract_id)
        .map_err(|e| SemanticKernelContextError::new(e.detail, format!("{:?}", e.kind)))?;
    let fingerprint = composition_fingerprint(
        &policy.composition_contract_id,
        &policy.native_primitive_contract_id,
    )
    .map_err(|e| SemanticKernelContextError::new(e.detail, format!("{:?}", e.kind)))?;
    if policy.composition_theorem_evidence_manifest_digest != fingerprint {
        return Err(SemanticKernelContextError::new(
            "composition fingerprint 가 resolved policy 와 불일치",
            COMPOSITION_POLICY_IDENTITY_MISMATCH,
        ));
    }
    let admitted = admit_composition_premises(
        &qualification.execution_structure,
        &primitive,
        &policy.composition_contract_id,
    );
    match &admitted {
        CompositionPremiseVerificationResult::Passed(_) => {}
        CompositionPremiseVerificationResult::Blocked(block) => {
            return Err(SemanticKernelContextError::new(
                format!(
                    "C1~C10 structural admission 실패(premise={}): {}",
                    block.premise_id, block.reason
                ),
                &block.code,
            ));
        }
        CompositionPremiseVerificationResult::ContextError(error) => {
            return Err(SemanticKernelContextError::new(
                format!(
                    "C1~C10 structural admission 실패(premise={}): {}",
                    error.premise_id.as_deref().unwrap_or("None"),
                    error.reason
                ),
                &error.code,
            ));
        }
    }
    let compiled = qualify_and_compile_execution(captured, &admitted);
    let compiled = match compiled {
        QualifyAndCompileExecutionResult::Qualified(compiled) => compiled,
        QualifyAndCompileExecutionResult::Blocked(block) => {
            return Ok(KernelResult::Blocked(SealedExecutionPlanBlocked {
                qualification_profile_id: qualification.qualification_profile_id.clone(),
                template_application_id: captured.template.applied.template_application_id.clone(),
                normalized_blockers: block
                    .normalized_blockers
                    .iter()
                    .map(|b| b.code.clone())
                    .collect(),
            }));
        }
        QualifyAndCompileExecutionResult::ContextError(error) => {
            return Err(SemanticKernelContextError::new(
                format!(
                    "execution compile context error({}): {}",
                    error.code, error.detail
                ),
                error.code,
            ));
        }
    };
    let payload = &compiled.execution_basis_semantic_payload;
    let requirements = payload
        .get("active_field_requirements")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            SemanticKernelContextError::new(
                "execution compile payload 의 active_field_requirements 형식 불량",
                "",
            )
        })?;
    let operations = payload
        .get("ordered_operations")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            SemanticKernelContextError::new(
                "execution compile payload 의 ordered_operations 형식 불량",
                "",
            )
        })?;
    let plan = build_sealed_plan(
        build_execution_basis(captured, &compiled)?,
        requirements,
        operations,
        &policy.plan_schema_version,
        &policy.canonical_encoding_version,
    )
    .map_err(|e| SemanticKernelContextError::new(e.detail, ""))?;
    let schemas: Vec<_> = SUPPORTED_PLAN_SCHEMAS.iter().map(|s| (*s).into()).collect();
    verify_sealed_plan_integrity(&plan, &schemas)
        .map_err(|e| SemanticKernelContextError::new(e.detail, ""))?;
    Ok(KernelResult::Plan(Box::new(plan)))
}
pub fn compute_sealed_execution_plan(
    authority: &DurableExecutionAuthority,
) -> Result<KernelResult, SemanticKernelContextError> {
    let snapshot = compute_execution_snapshot(authority)?;
    compile_sealed_plan_from_snapshot(&snapshot)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::execution_compilation::tests::{captured, fixtures};
    use crate::execution_contract_set::{
        encode_sealed_plan, execution_basis_digest, plan_semantic_digest,
    };
    use crate::execution_structure::decode_execution_structure;
    use crate::field_binding_input::build_field_binding_input;
    use crate::seal_execution_plan::{CandidateCompilation, compile_candidate};
    use crate::seal_execution_plan::{SealExecutionPlanCommand, WorkExecutionSummary};
    use crate::shipping_seal_policy::{SHIPPING_PLAN_SCHEMA_VERSION, resolve_shipping_policy};
    use crate::stored_execution_plan::RequestedVersionSelector;

    pub(crate) fn authority(name: &str, option: &str) -> DurableExecutionAuthority {
        let structure = decode_execution_structure(&fixtures()["structures"][name]).unwrap();
        let choices = if name == "slotless" {
            vec![]
        } else {
            vec![("s1", option)]
        };
        let input = captured(structure, &choices);
        let mut policy = input.resolved_seal_policy;
        policy.policy_resolution_version = "policy/v1".into();
        policy.execution_semantic_contract_id = "execution-semantics/v1".into();
        policy.binding_value_contract_id = "binding-value/v2".into();
        policy.raw_record_contract_id = "raw-record/v1".into();
        policy.document_value_resolution_contract_id = "document-content-value/v2".into();
        policy.record_validation_contract_id = "record-validation/v1".into();
        policy.record_review_contract_id = "record-review/v1".into();
        policy.materialization_contract_id = "materialization/v1".into();
        policy.plan_schema_version = "hwpx-execution-plan/v2".into();
        policy.canonical_encoding_version = CANONICAL_ENCODING_VERSION.into();
        DurableExecutionAuthority {
            workspace_instance_id: input.workspace_instance_id,
            work_authority_id: input.work_authority_id,
            expected_template_application_id: "app-1".into(),
            expected_profile_id: "hwpx-template-qualification-v2".into(),
            resolved_seal_policy: policy,
            template: input.template,
            selection: input.selection,
            field_binding: input.field_binding,
            captured_at: "2026-08-18T00:00:00Z".into(),
        }
    }

    pub(crate) fn rebind(authority: &mut DurableExecutionAuthority, remove: bool) {
        let mut rules = authority.field_binding.binding_rules.clone();
        if remove {
            rules.retain(|r| r.field_id != "금액");
        } else {
            rules
                .iter_mut()
                .find(|r| r.field_id == "성명")
                .unwrap()
                .source_key = Some("금액열".into());
        }
        authority.field_binding = build_field_binding_input(
            "ws-1",
            "work-1",
            "app-1",
            rules,
            vec!["이름".into(), "금액열".into(), "unused".into()],
            "rr/1",
            "2026-08-16T00:00:00Z",
        )
        .unwrap();
    }

    #[test]
    fn authority_recomputes_independent_plan_payloads_and_command_candidates() {
        let mut changed = authority("normal", "o1");
        rebind(&mut changed, false);
        let cases = [
            ("normal", authority("normal", "o1")),
            ("selected_o2", authority("normal", "o2")),
            ("slotless", authority("slotless", "")),
            ("active_change", changed),
        ];
        let expected = fixtures();
        for (name, input) in cases {
            let result = compute_sealed_execution_plan(&input).unwrap();
            let KernelResult::Plan(plan) = &result else {
                panic!("{name}: {result:?}")
            };
            assert_eq!(
                encode_sealed_plan(plan).unwrap(),
                expected["sealed_plans"][name]["payload"],
                "{name}"
            );
            assert_eq!(
                plan_semantic_digest(plan).unwrap(),
                expected["sealed_plans"][name]["digest"],
                "{name}"
            );
            assert_eq!(compute_sealed_execution_plan(&input).unwrap(), result);
            let snapshot = compute_execution_snapshot(&input).unwrap();
            let CandidateCompilation::Plan(candidate) = compile_candidate(&snapshot).unwrap()
            else {
                panic!("{name}")
            };
            assert_eq!(&candidate.plan_payload, plan);
            assert_eq!(
                candidate.execution_basis_digest,
                execution_basis_digest(&plan.execution_basis).unwrap()
            );
        }
    }

    #[test]
    fn invalid_authority_contracts_and_composition_never_produce_a_plan() {
        for axis in 0..9 {
            let mut input = authority("normal", "o1");
            let policy = &mut input.resolved_seal_policy;
            match axis {
                0 => policy.execution_base_kind = "bogus/base".into(),
                1 => policy.plan_schema_version = "bogus-plan/v9".into(),
                2 => policy.canonical_encoding_version = "bogus-enc/v9".into(),
                3 => policy.materialization_base_contract_id = "bogus-base/v9".into(),
                4 => policy.composition_theorem_evidence_manifest_digest = "wrong".into(),
                5 => policy.native_primitive_contract_id = "unknown".into(),
                6 => policy.composition_contract_id = "unknown".into(),
                7 => input.expected_template_application_id = "stale".into(),
                _ => input.workspace_instance_id = "foreign".into(),
            }
            assert!(
                compute_sealed_execution_plan(&input).is_err(),
                "axis {axis}"
            );
        }
        // Keep capture integrity valid so the structural admission itself owns this refusal.
        let mut structure =
            decode_execution_structure(&fixtures()["structures"]["normal"]).unwrap();
        for fact in structure
            .global_composition_facts
            .resolver_stability_facts
            .values_mut()
        {
            *fact = false;
        }
        structure.global_composition_facts.admitted_relation_profile = "unadmitted".into();
        let broken = captured(structure, &[("s1", "o1")]);
        let mut input = authority("normal", "o1");
        input.template = broken.template;
        input.selection = broken.selection;
        let snapshot = compute_execution_snapshot(&input).unwrap();
        let error = compile_sealed_plan_from_snapshot(&snapshot).unwrap_err();
        assert!(
            error.detail.contains("C1~C10 structural admission 실패"),
            "{error:?}"
        );
    }

    #[test]
    fn unbound_active_field_is_recoverable_block_with_matching_command_evidence() {
        let mut input = authority("normal", "o2");
        rebind(&mut input, true);
        let KernelResult::Blocked(block) = compute_sealed_execution_plan(&input).unwrap() else {
            panic!("unbound plan")
        };
        assert_eq!(block.normalized_blockers, ["ACTIVE_FIELD_UNBOUND"]);
        assert_eq!(block.template_application_id, "app-1");
        assert_eq!(block.qualification_profile_id, input.expected_profile_id);
        let snapshot = compute_execution_snapshot(&input).unwrap();
        let CandidateCompilation::Blocked(candidate) = compile_candidate(&snapshot).unwrap() else {
            panic!("unbound candidate")
        };
        assert_eq!(candidate.normalized_blockers, block.normalized_blockers);
        assert_eq!(
            candidate.captured_execution_input_digest,
            snapshot.captured_execution_input_digest
        );
    }

    #[test]
    fn unknown_plan_identity_never_falls_back_to_shipping() {
        let mut request = SealExecutionPlanCommand::new("w", "work", "r").unwrap();
        request.requested_plan_schema = RequestedVersionSelector::exact("future/v3").unwrap();
        let policy = resolve_shipping_policy(
            &request,
            &WorkExecutionSummary {
                qualification_profile_id: "hwpx-template-qualification-v4".into(),
                template_application_id: "a".into(),
            },
        );
        assert_ne!(policy.plan_schema_version, SHIPPING_PLAN_SCHEMA_VERSION);
        let error = require_supported_plan_identity(&policy).unwrap_err();
        assert_eq!(error.detail, "미지원 plan schema: 'future/v3'");
    }
}
