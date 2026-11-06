//! Pure exact execution capture: immutable claims, cross-reference judgment and result algebra.

use crate::canonical_execution_encoding::canonical_execution_digest;
use crate::execution_structure::{ExecutionTemplateStructure, template_structure_digest};
use crate::field_binding_input::FieldBindingInput;
use crate::slot_configuration_context::ExactAppliedTemplateInput;
use crate::slot_selection::digest_selection_set;
use crate::slot_selection_input::SlotSelectionInput;
use crate::text_render::python_repr;
use serde_json::{Value, json};
use std::fmt;

pub const APPLIED_TEMPLATE_CANDIDATE: &str = "APPLIED_TEMPLATE_CANDIDATE";
pub const MATERIALIZATION_BASE_CONTRACT_ID: &str = "applied-template-candidate-base/v1";
pub const EXECUTION_SELECTION_SEMANTICS_CONTRACT: &str = "execution-semantics/v1";
pub const SLOTLESS: &str = "SLOTLESS";
pub const SLOTTED: &str = "SLOTTED";
pub const APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR: &str =
    "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR";
pub const QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR: &str =
    "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR";
pub const SELECTION_CONTRACT_INTEGRITY_ERROR: &str = "SELECTION_CONTRACT_INTEGRITY_ERROR";
pub const FIELD_BINDING_INPUT_INTEGRITY_ERROR: &str = "FIELD_BINDING_INPUT_INTEGRITY_ERROR";
pub const UNSUPPORTED_LOCAL_IMPLEMENTATION: &str = "UNSUPPORTED_LOCAL_IMPLEMENTATION";
pub const EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR: &str =
    "EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionCaptureIntegrityError(pub String);
impl fmt::Display for ExecutionCaptureIntegrityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ExecutionCaptureIntegrityError {}
fn fail(message: impl Into<String>) -> ExecutionCaptureIntegrityError {
    ExecutionCaptureIntegrityError(message.into())
}
fn nonempty(value: &str, name: &str) -> Result<(), ExecutionCaptureIntegrityError> {
    if value.is_empty() {
        Err(fail(format!("{name} 는 비어 있지 않은 문자열이어야 한다")))
    } else {
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkRouteRef {
    pub workspace_instance_id: String,
    pub work_ref: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationProfileSemanticPayload {
    pub qualification_profile_id: String,
    pub media: String,
    pub adapter_contract_version: String,
    pub product_rule_version: String,
    pub operation_alphabet_version: String,
    pub projection_schema_version: String,
    pub manifest_payload: Value,
}
impl QualificationProfileSemanticPayload {
    pub fn validate(&self) -> Result<(), ExecutionCaptureIntegrityError> {
        for (name, value) in [
            ("qualification_profile_id", &self.qualification_profile_id),
            ("media", &self.media),
            ("adapter_contract_version", &self.adapter_contract_version),
            ("product_rule_version", &self.product_rule_version),
            (
                "operation_alphabet_version",
                &self.operation_alphabet_version,
            ),
            ("projection_schema_version", &self.projection_schema_version),
        ] {
            nonempty(value, name)?;
        }
        if !self.manifest_payload.is_object() {
            return Err(fail("manifest_payload 는 사전이어야 한다"));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExactTemplateQualificationContext {
    pub pass_evidence_id: String,
    pub qualification_profile_id: String,
    pub qualification_profile_semantic_payload: QualificationProfileSemanticPayload,
    pub structure_projection_schema_version: String,
    pub template_structure_digest: String,
    pub execution_structure: ExecutionTemplateStructure,
    pub composition_profile_state: String,
    pub revision_id: String,
    pub qualification_profile_semantic_digest: Option<String>,
}
impl ExactTemplateQualificationContext {
    pub fn validate(&self) -> Result<(), ExecutionCaptureIntegrityError> {
        for (name, value) in [
            ("pass_evidence_id", &self.pass_evidence_id),
            ("qualification_profile_id", &self.qualification_profile_id),
            (
                "structure_projection_schema_version",
                &self.structure_projection_schema_version,
            ),
            ("template_structure_digest", &self.template_structure_digest),
            ("composition_profile_state", &self.composition_profile_state),
            ("revision_id", &self.revision_id),
        ] {
            nonempty(value, name)?;
        }
        self.qualification_profile_semantic_payload.validate()?;
        let payload = &self.qualification_profile_semantic_payload;
        if payload.qualification_profile_id != self.qualification_profile_id {
            return Err(fail(
                "semantic payload 의 profile id 가 qualification_profile_id 와 불일치",
            ));
        }
        if payload.projection_schema_version != self.structure_projection_schema_version {
            return Err(fail(
                "semantic payload 의 projection schema 가 context 와 불일치",
            ));
        }
        if self.execution_structure.projection_schema_version
            != self.structure_projection_schema_version
        {
            return Err(fail(
                "execution_structure schema 가 context 선언 schema 와 불일치",
            ));
        }
        if template_structure_digest(&self.execution_structure) != self.template_structure_digest {
            return Err(fail(
                "template_structure_digest 가 execution_structure recompute 와 불일치",
            ));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedTemplateExecutionInput {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub applied: ExactAppliedTemplateInput,
    pub qualification: ExactTemplateQualificationContext,
    pub captured_at: String,
}
impl CapturedTemplateExecutionInput {
    pub fn validate(&self) -> Result<(), ExecutionCaptureIntegrityError> {
        nonempty(&self.workspace_instance_id, "workspace_instance_id")?;
        nonempty(&self.work_authority_id, "work_authority_id")?;
        nonempty(&self.captured_at, "captured_at")?;
        self.qualification.validate()?;
        if self.work_authority_id != self.applied.work_id {
            return Err(fail("work_authority_id 가 applied.work_id 와 불일치"));
        }
        if self
            .qualification
            .qualification_profile_semantic_payload
            .media
            != self.applied.media
        {
            return Err(fail(
                "qualification semantic payload media 가 applied media 와 불일치",
            ));
        }
        if self.qualification.revision_id != self.applied.revision_id {
            return Err(fail(
                "qualification revision_id 가 applied.revision_id 와 불일치",
            ));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedSealPolicy {
    pub policy_resolution_version: String,
    pub execution_base_kind: String,
    pub execution_semantic_contract_id: String,
    pub binding_value_contract_id: String,
    pub raw_record_contract_id: String,
    pub document_value_resolution_contract_id: String,
    pub record_validation_contract_id: String,
    pub record_review_contract_id: String,
    pub composition_contract_id: String,
    pub native_primitive_contract_id: String,
    pub materialization_base_contract_id: String,
    pub composition_theorem_evidence_manifest_digest: String,
    pub materialization_contract_id: String,
    pub plan_schema_version: String,
    pub canonical_encoding_version: String,
}
impl ResolvedSealPolicy {
    pub fn validate(&self) -> Result<(), ExecutionCaptureIntegrityError> {
        for (name, value) in [
            ("policy_resolution_version", &self.policy_resolution_version),
            ("execution_base_kind", &self.execution_base_kind),
            (
                "execution_semantic_contract_id",
                &self.execution_semantic_contract_id,
            ),
            ("binding_value_contract_id", &self.binding_value_contract_id),
            ("raw_record_contract_id", &self.raw_record_contract_id),
            (
                "document_value_resolution_contract_id",
                &self.document_value_resolution_contract_id,
            ),
            (
                "record_validation_contract_id",
                &self.record_validation_contract_id,
            ),
            ("record_review_contract_id", &self.record_review_contract_id),
            ("composition_contract_id", &self.composition_contract_id),
            (
                "native_primitive_contract_id",
                &self.native_primitive_contract_id,
            ),
            (
                "materialization_base_contract_id",
                &self.materialization_base_contract_id,
            ),
            (
                "composition_theorem_evidence_manifest_digest",
                &self.composition_theorem_evidence_manifest_digest,
            ),
            (
                "materialization_contract_id",
                &self.materialization_contract_id,
            ),
            ("plan_schema_version", &self.plan_schema_version),
            (
                "canonical_encoding_version",
                &self.canonical_encoding_version,
            ),
        ] {
            nonempty(value, name)?;
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExactTemplateExecutionBasis {
    pub execution_base_kind: String,
    pub materialization_base_contract_id: String,
    pub work_authority_id: String,
    pub template_application_id: String,
    pub exact_content_digest: String,
    pub canonical_blob_reference: String,
}
pub fn build_exact_execution_basis(
    template: &CapturedTemplateExecutionInput,
    policy: &ResolvedSealPolicy,
) -> Result<ExactTemplateExecutionBasis, ExecutionCaptureIntegrityError> {
    if policy.execution_base_kind != APPLIED_TEMPLATE_CANDIDATE {
        return Err(fail(format!(
            "S5 v1 admitted base 는 APPLIED_TEMPLATE_CANDIDATE 뿐: {}",
            python_repr(&Value::String(policy.execution_base_kind.clone()))
        )));
    }
    if policy.materialization_base_contract_id != MATERIALIZATION_BASE_CONTRACT_ID {
        return Err(fail(format!(
            "materialization base contract 가 {} 가 아니다",
            python_repr(&Value::String(MATERIALIZATION_BASE_CONTRACT_ID.into()))
        )));
    }
    Ok(ExactTemplateExecutionBasis {
        execution_base_kind: APPLIED_TEMPLATE_CANDIDATE.into(),
        materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
        work_authority_id: template.work_authority_id.clone(),
        template_application_id: template.applied.template_application_id.clone(),
        exact_content_digest: template.applied.exact_content_digest.clone(),
        canonical_blob_reference: template.applied.canonical_blob_reference.clone(),
    })
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EffectiveSelectionBasis {
    pub slot_mode: String,
    pub work_id: String,
    pub template_application_id: String,
    pub selection_semantic_contract_id: String,
    pub template_structure_digest: String,
    pub effective_selection_digest: Option<String>,
    pub declared_selection_digest: Option<String>,
}
pub fn project_effective_selection(
    selection: &SlotSelectionInput,
) -> Result<EffectiveSelectionBasis, ExecutionCaptureIntegrityError> {
    match selection {
        SlotSelectionInput::Slotless(item) => Ok(EffectiveSelectionBasis {
            slot_mode: SLOTLESS.into(),
            work_id: item.work_id.clone(),
            template_application_id: item.template_application_id.clone(),
            selection_semantic_contract_id: item.selection_semantic_contract_id.clone(),
            template_structure_digest: item.template_structure_digest.clone(),
            effective_selection_digest: None,
            declared_selection_digest: item.declared_selection_digest.clone(),
        }),
        SlotSelectionInput::Slotted(item) => {
            let recomputed = digest_selection_set(
                &item.selection_semantic_contract_id,
                &item.effective_selections,
            )
            .map_err(|e| fail(e.detail))?;
            if recomputed != item.effective_selection_digest {
                return Err(fail(
                    "effective_selection_digest 가 effective_selections recompute 와 불일치",
                ));
            }
            Ok(EffectiveSelectionBasis {
                slot_mode: SLOTTED.into(),
                work_id: item.work_id.clone(),
                template_application_id: item.template_application_id.clone(),
                selection_semantic_contract_id: item.selection_semantic_contract_id.clone(),
                template_structure_digest: item.template_structure_digest.clone(),
                effective_selection_digest: Some(item.effective_selection_digest.clone()),
                declared_selection_digest: Some(item.declared_selection_digest.clone()),
            })
        }
    }
}

pub fn semantic_projection_digest(
    projection: &Value,
) -> Result<String, ExecutionCaptureIntegrityError> {
    canonical_execution_digest(projection).map_err(|e| fail(e.to_string()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SelectionObservation {
    Captured(SlotSelectionInput),
    DomainBlocked {
        blocker_code: String,
        detail: String,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FieldBindingObservation {
    Captured(Box<FieldBindingInput>),
    DomainBlocked {
        blocker_code: String,
        detail: String,
    },
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedExecutionInput {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub template: CapturedTemplateExecutionInput,
    pub selection: SlotSelectionInput,
    pub field_binding: FieldBindingInput,
    pub resolved_seal_policy: ResolvedSealPolicy,
    pub captured_execution_input_semantic_projection: Value,
    pub captured_at: String,
    pub captured_execution_input_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedExecutionDomainBlock {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub template_observation: CapturedTemplateExecutionInput,
    pub selection_observation: SelectionObservation,
    pub field_binding_observation: FieldBindingObservation,
    pub resolved_seal_policy: ResolvedSealPolicy,
    pub normalized_blockers: Vec<String>,
    pub captured_attempt_semantic_projection: Value,
    pub captured_at: String,
    pub captured_attempt_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapturedExecutionPolicyBlock {
    pub policy_code: String,
    pub observed_at: String,
    pub qualification_profile_id: Option<String>,
    pub observed_policy_version: Option<String>,
    pub policy_observation_digest: Option<String>,
    pub captured_attempt_digest: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionCaptureContextError {
    pub code: String,
    pub detail: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CaptureExecutionQualificationResult {
    Complete(Box<CapturedExecutionInput>),
    DomainBlocked(Box<CapturedExecutionDomainBlock>),
    PolicyBlocked(CapturedExecutionPolicyBlock),
    ContextError(ExecutionCaptureContextError),
}
fn context(code: &str, detail: impl Into<String>) -> CaptureExecutionQualificationResult {
    CaptureExecutionQualificationResult::ContextError(ExecutionCaptureContextError {
        code: code.into(),
        detail: detail.into(),
    })
}
fn selection_basis_json(basis: &EffectiveSelectionBasis) -> Value {
    json!({
        "selection_projection_contract":EXECUTION_SELECTION_SEMANTICS_CONTRACT,
        "slot_mode":basis.slot_mode,
        "work_id":basis.work_id,
        "template_application_id":basis.template_application_id,
        "selection_semantic_contract_id":basis.selection_semantic_contract_id,
        "template_structure_digest":basis.template_structure_digest,
        "effective_selection_digest":basis.effective_selection_digest,
        "declared_selection_digest":basis.declared_selection_digest,
    })
}
fn binding_json(binding: &FieldBindingInput) -> Value {
    json!({
        "base_template_application_id":binding.base_template_application_id,
        "field_binding_semantic_contract_id":binding.field_binding_semantic_contract_id,
        "source_schema_contract_id":binding.source_schema_contract_id,
        "raw_record_contract_id":binding.raw_record_contract_id,
        "canonical_binding_digest":binding.canonical_binding_digest,
        "canonical_source_schema_digest":binding.canonical_source_schema_digest,
    })
}
fn policy_json(policy: &ResolvedSealPolicy) -> Value {
    json!({
        "policy_resolution_version":policy.policy_resolution_version,
        "execution_base_kind":policy.execution_base_kind,
        "execution_semantic_contract_id":policy.execution_semantic_contract_id,
        "binding_value_contract_id":policy.binding_value_contract_id,
        "raw_record_contract_id":policy.raw_record_contract_id,
        "document_value_resolution_contract_id":policy.document_value_resolution_contract_id,
        "record_validation_contract_id":policy.record_validation_contract_id,
        "record_review_contract_id":policy.record_review_contract_id,
        "composition_contract_id":policy.composition_contract_id,
        "native_primitive_contract_id":policy.native_primitive_contract_id,
        "materialization_base_contract_id":policy.materialization_base_contract_id,
        "composition_theorem_evidence_manifest_digest":policy.composition_theorem_evidence_manifest_digest,
        "materialization_contract_id":policy.materialization_contract_id,
        "plan_schema_version":policy.plan_schema_version,
        "canonical_encoding_version":policy.canonical_encoding_version,
    })
}
fn template_json(template: &CapturedTemplateExecutionInput) -> (Value, Value) {
    let applied = &template.applied;
    let qual = &template.qualification;
    let payload = &qual.qualification_profile_semantic_payload;
    (
        json!({
            "work_id":applied.work_id,
            "template_application_id":applied.template_application_id,
            "revision_id":applied.revision_id,
            "media":applied.media,
            "template_lineage_id":applied.template_lineage_id,
            "exact_content_digest":applied.exact_content_digest,
        }),
        json!({
            "pass_evidence_id":qual.pass_evidence_id,
            "qualification_profile_id":qual.qualification_profile_id,
            "structure_projection_schema_version":qual.structure_projection_schema_version,
            "template_structure_digest":qual.template_structure_digest,
            "composition_profile_state":qual.composition_profile_state,
            "qualification_profile_semantic_payload":{
                "qualification_profile_id":payload.qualification_profile_id,
                "media":payload.media,
                "adapter_contract_version":payload.adapter_contract_version,
                "product_rule_version":payload.product_rule_version,
                "operation_alphabet_version":payload.operation_alphabet_version,
                "projection_schema_version":payload.projection_schema_version,
                "manifest_payload":payload.manifest_payload,
            }
        }),
    )
}
fn semantic_projection(
    template: &CapturedTemplateExecutionInput,
    policy: &ResolvedSealPolicy,
    selection: Value,
    binding: Value,
) -> Value {
    let (applied, qualification) = template_json(template);
    json!({
        "workspace_instance_id":template.workspace_instance_id,
        "work_authority_id":template.work_authority_id,
        "applied":applied,
        "qualification":qualification,
        "selection":selection,
        "field_binding":binding,
        "resolved_seal_policy":policy_json(policy),
        "execution_base_kind":policy.execution_base_kind,
    })
}
pub fn build_captured_execution_semantic_projection(
    template: &CapturedTemplateExecutionInput,
    selection: &SlotSelectionInput,
    field_binding: &FieldBindingInput,
    policy: &ResolvedSealPolicy,
) -> Result<Value, ExecutionCaptureIntegrityError> {
    Ok(semantic_projection(
        template,
        policy,
        selection_basis_json(&project_effective_selection(selection)?),
        binding_json(field_binding),
    ))
}
pub fn build_captured_attempt_semantic_projection(
    template: &CapturedTemplateExecutionInput,
    policy: &ResolvedSealPolicy,
    selection: &SelectionObservation,
    binding: &FieldBindingObservation,
) -> Result<Value, ExecutionCaptureIntegrityError> {
    let selection = match selection {
        SelectionObservation::Captured(item) => {
            selection_basis_json(&project_effective_selection(item)?)
        }
        SelectionObservation::DomainBlocked { blocker_code, .. } => json!({"blocked":blocker_code}),
    };
    let binding = match binding {
        FieldBindingObservation::Captured(item) => binding_json(item),
        FieldBindingObservation::DomainBlocked { blocker_code, .. } => {
            json!({"blocked":blocker_code})
        }
    };
    Ok(semantic_projection(template, policy, selection, binding))
}

pub struct JudgeCapturedExecutionInput {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub expected_template_application_id: String,
    pub expected_profile_id: String,
    pub resolved_seal_policy: ResolvedSealPolicy,
    pub template: CapturedTemplateExecutionInput,
    pub selection_observation: SelectionObservation,
    pub field_binding_observation: FieldBindingObservation,
    pub captured_at: String,
    pub policy_block: Option<CapturedExecutionPolicyBlock>,
}
pub fn judge_captured_execution(
    input: JudgeCapturedExecutionInput,
) -> CaptureExecutionQualificationResult {
    let JudgeCapturedExecutionInput {
        workspace_instance_id,
        work_authority_id,
        expected_template_application_id,
        expected_profile_id,
        resolved_seal_policy: policy,
        template,
        selection_observation,
        field_binding_observation,
        captured_at,
        policy_block,
    } = input;
    if let Err(error) = template.validate() {
        return context(APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR, error.0);
    }
    if let Err(error) = policy.validate() {
        return context(EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR, error.0);
    }
    if policy.execution_base_kind != APPLIED_TEMPLATE_CANDIDATE {
        return context(
            UNSUPPORTED_LOCAL_IMPLEMENTATION,
            format!(
                "미지원 execution base kind: {}",
                python_repr(&Value::String(policy.execution_base_kind.clone()))
            ),
        );
    }
    if policy.materialization_base_contract_id != MATERIALIZATION_BASE_CONTRACT_ID {
        return context(
            EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR,
            "materialization base contract 가 applied-template-candidate-base/v1 이 아니다",
        );
    }
    if let Some(block) = policy_block {
        if block
            .qualification_profile_id
            .as_ref()
            .is_some_and(|profile| profile != &expected_profile_id)
        {
            return context(
                QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR,
                "policy block 의 qualification_profile_id 가 요청 profile 과 불일치",
            );
        }
        return CaptureExecutionQualificationResult::PolicyBlocked(block);
    }
    if template.workspace_instance_id != workspace_instance_id {
        return context(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "template workspace 가 요청 workspace 와 불일치",
        );
    }
    if template.work_authority_id != work_authority_id {
        return context(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "template work authority 가 요청 WorkAuthorityId 와 불일치",
        );
    }
    if template.applied.template_application_id != expected_template_application_id {
        return context(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "applied Application 이 expected_template_application_id 와 불일치",
        );
    }
    if template.qualification.qualification_profile_id != expected_profile_id {
        return context(
            QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR,
            "qualification profile 이 expected_profile_id 와 불일치",
        );
    }
    if let FieldBindingObservation::Captured(binding) = &field_binding_observation {
        if let Err(error) = binding.validate() {
            return context(FIELD_BINDING_INPUT_INTEGRITY_ERROR, error.to_string());
        }
        for (actual, expected, detail) in [
            (
                &binding.workspace_instance_id,
                &template.workspace_instance_id,
                "field binding workspace 가 template 과 불일치",
            ),
            (
                &binding.work_authority_id,
                &template.work_authority_id,
                "field binding work authority 가 template 과 불일치",
            ),
            (
                &binding.base_template_application_id,
                &template.applied.template_application_id,
                "field binding base Application 이 template 과 불일치",
            ),
        ] {
            if actual != expected {
                return context(FIELD_BINDING_INPUT_INTEGRITY_ERROR, detail);
            }
        }
    }
    if let SelectionObservation::Captured(selection) = &selection_observation {
        let basis = match project_effective_selection(selection) {
            Ok(basis) => basis,
            Err(error) => return context(SELECTION_CONTRACT_INTEGRITY_ERROR, error.0),
        };
        for (actual, expected, detail) in [
            (
                &basis.work_id,
                &template.work_authority_id,
                "selection work_id 가 template WorkAuthorityId 와 불일치",
            ),
            (
                &basis.template_application_id,
                &template.applied.template_application_id,
                "selection Application 이 template 과 불일치",
            ),
            (
                match selection {
                    SlotSelectionInput::Slotless(item) => &item.structure_projection_schema_version,
                    SlotSelectionInput::Slotted(item) => &item.structure_projection_schema_version,
                },
                &template.qualification.structure_projection_schema_version,
                "selection structure schema 가 qualification context 와 불일치",
            ),
            (
                &basis.template_structure_digest,
                &template.qualification.template_structure_digest,
                "selection template_structure_digest 가 qualification context 와 불일치",
            ),
        ] {
            if actual != expected {
                return context(SELECTION_CONTRACT_INTEGRITY_ERROR, detail);
            }
        }
    }
    let mut blockers = Vec::new();
    if let SelectionObservation::DomainBlocked { blocker_code, .. } = &selection_observation {
        blockers.push(blocker_code.clone());
    }
    if let FieldBindingObservation::DomainBlocked { blocker_code, .. } = &field_binding_observation
    {
        blockers.push(blocker_code.clone());
    }
    if !blockers.is_empty() {
        let projection = match build_captured_attempt_semantic_projection(
            &template,
            &policy,
            &selection_observation,
            &field_binding_observation,
        ) {
            Ok(projection) => projection,
            Err(error) => return context(EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR, error.0),
        };
        let digest = match semantic_projection_digest(&projection) {
            Ok(digest) => digest,
            Err(error) => return context(EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR, error.0),
        };
        return CaptureExecutionQualificationResult::DomainBlocked(Box::new(
            CapturedExecutionDomainBlock {
                workspace_instance_id,
                work_authority_id,
                template_observation: template,
                selection_observation,
                field_binding_observation,
                resolved_seal_policy: policy,
                normalized_blockers: blockers,
                captured_attempt_semantic_projection: projection,
                captured_at,
                captured_attempt_digest: digest,
            },
        ));
    }
    let SelectionObservation::Captured(selection) = selection_observation else {
        unreachable!()
    };
    let FieldBindingObservation::Captured(binding) = field_binding_observation else {
        unreachable!()
    };
    if let Err(error) = build_exact_execution_basis(&template, &policy) {
        return context(EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR, error.0);
    }
    let projection = match build_captured_execution_semantic_projection(
        &template, &selection, &binding, &policy,
    ) {
        Ok(projection) => projection,
        Err(error) => return context(EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR, error.0),
    };
    let digest = match semantic_projection_digest(&projection) {
        Ok(digest) => digest,
        Err(error) => return context(EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR, error.0),
    };
    CaptureExecutionQualificationResult::Complete(Box::new(CapturedExecutionInput {
        workspace_instance_id,
        work_authority_id,
        template,
        selection,
        field_binding: *binding,
        resolved_seal_policy: policy,
        captured_execution_input_semantic_projection: projection,
        captured_at,
        captured_execution_input_digest: digest,
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{
        EXECUTION_STRUCTURE_PROJECTION_SCHEMA, GlobalCompositionFacts, TemplateStructure,
    };
    use crate::field_binding_input::build_field_binding_input;
    use crate::slot_selection_input::SlotlessSelectionContext;
    use std::collections::BTreeMap;

    fn input() -> JudgeCapturedExecutionInput {
        let structure = ExecutionTemplateStructure {
            projection_schema_version: EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
            product_structure: TemplateStructure::default(),
            field_occurrences: vec![],
            option_regions: vec![],
            removal_target_relations: vec![],
            content_entries: vec![],
            global_composition_facts: GlobalCompositionFacts {
                crossing_free: true,
                resolver_stability_facts: BTreeMap::new(),
                admitted_relation_profile: "rel/1".into(),
            },
        };
        let digest = template_structure_digest(&structure);
        let payload = QualificationProfileSemanticPayload {
            qualification_profile_id: "p".into(),
            media: "hwpx".into(),
            adapter_contract_version: "a".into(),
            product_rule_version: "r".into(),
            operation_alphabet_version: "o".into(),
            projection_schema_version: EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
            manifest_payload: json!({"k":"v"}),
        };
        let template = CapturedTemplateExecutionInput {
            workspace_instance_id: "ws".into(),
            work_authority_id: "w".into(),
            applied: ExactAppliedTemplateInput {
                work_id: "w".into(),
                template_application_id: "app".into(),
                revision_id: "rev".into(),
                media: "hwpx".into(),
                template_lineage_id: "line".into(),
                exact_content_digest: "sha256:content".into(),
                canonical_blob_reference: "blob://private".into(),
            },
            qualification: ExactTemplateQualificationContext {
                pass_evidence_id: "ev".into(),
                qualification_profile_id: "p".into(),
                qualification_profile_semantic_payload: payload,
                structure_projection_schema_version: EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
                template_structure_digest: digest.clone(),
                execution_structure: structure,
                composition_profile_state: "SEALED".into(),
                revision_id: "rev".into(),
                qualification_profile_semantic_digest: None,
            },
            captured_at: "t1".into(),
        };
        let selection = SlotSelectionInput::Slotless(SlotlessSelectionContext {
            work_id: "w".into(),
            template_application_id: "app".into(),
            selection_semantic_contract_id: "slot-selection/v1".into(),
            structure_projection_schema_version: EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
            template_structure_digest: digest,
            source_configuration_version: None,
            declared_selection_digest: None,
            captured_at: "t1".into(),
        });
        let field_binding =
            build_field_binding_input("ws", "w", "app", vec![], vec![], "rr/1", "t1").unwrap();
        let policy = ResolvedSealPolicy {
            policy_resolution_version: "pol/1".into(),
            execution_base_kind: APPLIED_TEMPLATE_CANDIDATE.into(),
            execution_semantic_contract_id: "exec/1".into(),
            binding_value_contract_id: "bind/1".into(),
            raw_record_contract_id: "rr/1".into(),
            document_value_resolution_contract_id: "dvr/1".into(),
            record_validation_contract_id: "rv/1".into(),
            record_review_contract_id: "review/1".into(),
            composition_contract_id: "comp/1".into(),
            native_primitive_contract_id: "nat/1".into(),
            materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
            composition_theorem_evidence_manifest_digest: "sha256:theorem".into(),
            materialization_contract_id: "mat/1".into(),
            plan_schema_version: "plan/1".into(),
            canonical_encoding_version: "execution-canonical/v1".into(),
        };
        JudgeCapturedExecutionInput {
            workspace_instance_id: "ws".into(),
            work_authority_id: "w".into(),
            expected_template_application_id: "app".into(),
            expected_profile_id: "p".into(),
            resolved_seal_policy: policy,
            template,
            selection_observation: SelectionObservation::Captured(selection),
            field_binding_observation: FieldBindingObservation::Captured(Box::new(field_binding)),
            captured_at: "t1".into(),
            policy_block: None,
        }
    }
    fn active_root_input() -> JudgeCapturedExecutionInput {
        use crate::execution_structure::FieldOccurrence;

        let mut active = input();
        let structure = &mut active.template.qualification.execution_structure;
        structure.product_structure.root_fields.push("f".into());
        structure.field_occurrences.push(FieldOccurrence {
            field_id: "f".into(),
            occurrence_ordinal: 0,
            owner_kind: "ROOT".into(),
            owner_slot_id: None,
            owner_option_id: None,
            content_entry_id: "e".into(),
            structural_order: 0,
            native_value_target_class: "text".into(),
            resolver_contract_id: "res/1".into(),
        });
        let digest = template_structure_digest(structure);
        active.template.qualification.template_structure_digest = digest.clone();
        if let SelectionObservation::Captured(SlotSelectionInput::Slotless(ref mut selection)) =
            active.selection_observation
        {
            selection.template_structure_digest = digest;
        }
        active
    }
    #[test]
    fn exact_capture_digest_and_outcome_partition() {
        let CaptureExecutionQualificationResult::Complete(complete) =
            judge_captured_execution(input())
        else {
            panic!("complete capture expected")
        };
        assert_eq!(
            semantic_projection_digest(&complete.captured_execution_input_semantic_projection)
                .unwrap(),
            complete.captured_execution_input_digest
        );
        assert!(
            complete.captured_execution_input_semantic_projection["applied"]
                .get("canonical_blob_reference")
                .is_none()
        );
        let mut changed = input();
        changed.captured_at = "later".into();
        changed.template.captured_at = "later".into();
        let CaptureExecutionQualificationResult::Complete(later) =
            judge_captured_execution(changed)
        else {
            panic!("complete capture expected")
        };
        assert_eq!(
            complete.captured_execution_input_digest,
            later.captured_execution_input_digest
        );
        let mut blocked = input();
        blocked.selection_observation = SelectionObservation::DomainBlocked {
            blocker_code: "SLOT_CONFIGURATION_INCOMPLETE".into(),
            detail: "missing".into(),
        };
        let CaptureExecutionQualificationResult::DomainBlocked(blocked) =
            judge_captured_execution(blocked)
        else {
            panic!("domain block expected")
        };
        assert_eq!(
            blocked.normalized_blockers,
            vec!["SLOT_CONFIGURATION_INCOMPLETE"]
        );
        assert_eq!(
            semantic_projection_digest(&blocked.captured_attempt_semantic_projection).unwrap(),
            blocked.captured_attempt_digest
        );
        let mut wrong = input();
        wrong.work_authority_id = "another".into();
        let CaptureExecutionQualificationResult::ContextError(wrong) =
            judge_captured_execution(wrong)
        else {
            panic!("context error expected")
        };
        assert_eq!(wrong.code, APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR);
        let mut policy = input();
        policy.policy_block = Some(CapturedExecutionPolicyBlock {
            policy_code: "QUALIFICATION_PROFILE_REVOKED".into(),
            observed_at: "t1".into(),
            qualification_profile_id: Some("p".into()),
            observed_policy_version: None,
            policy_observation_digest: None,
            captured_attempt_digest: None,
        });
        assert!(matches!(
            judge_captured_execution(policy),
            CaptureExecutionQualificationResult::PolicyBlocked(_)
        ));
        let context_code = |input| {
            let CaptureExecutionQualificationResult::ContextError(error) =
                judge_captured_execution(input)
            else {
                panic!("mismatched authority admitted")
            };
            error.code
        };
        let mut wrong_workspace = input();
        wrong_workspace.workspace_instance_id = "other".into();
        assert_eq!(
            context_code(wrong_workspace),
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR
        );
        let mut wrong_application = input();
        wrong_application.expected_template_application_id = "other".into();
        assert_eq!(
            context_code(wrong_application),
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR
        );
        let mut wrong_profile = input();
        wrong_profile.expected_profile_id = "other".into();
        assert_eq!(
            context_code(wrong_profile),
            QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR
        );
        let mut wrong_binding = input();
        if let FieldBindingObservation::Captured(ref mut binding) =
            wrong_binding.field_binding_observation
        {
            binding.work_authority_id = "other".into();
        }
        assert_eq!(
            context_code(wrong_binding),
            FIELD_BINDING_INPUT_INTEGRITY_ERROR
        );
        let mut wrong_selection = input();
        if let SelectionObservation::Captured(SlotSelectionInput::Slotless(ref mut selection)) =
            wrong_selection.selection_observation
        {
            selection.template_application_id = "other".into();
        }
        assert_eq!(
            context_code(wrong_selection),
            SELECTION_CONTRACT_INTEGRITY_ERROR
        );
        let mut wrong_structure = input();
        if let SelectionObservation::Captured(SlotSelectionInput::Slotless(ref mut selection)) =
            wrong_structure.selection_observation
        {
            selection.template_structure_digest = "sha256:other".into();
        }
        assert_eq!(
            context_code(wrong_structure),
            SELECTION_CONTRACT_INTEGRITY_ERROR
        );
        let mut both_blocked = input();
        both_blocked.selection_observation = SelectionObservation::DomainBlocked {
            blocker_code: "SLOT_CONFIGURATION_INCOMPLETE".into(),
            detail: "missing".into(),
        };
        both_blocked.field_binding_observation = FieldBindingObservation::DomainBlocked {
            blocker_code: "FIELD_BINDING_INCOMPLETE".into(),
            detail: "missing".into(),
        };
        let CaptureExecutionQualificationResult::DomainBlocked(both) =
            judge_captured_execution(both_blocked)
        else {
            panic!("two domain blockers admitted")
        };
        assert_eq!(
            both.normalized_blockers,
            ["SLOT_CONFIGURATION_INCOMPLETE", "FIELD_BINDING_INCOMPLETE"]
        );
        assert_eq!(
            semantic_projection_digest(&both.captured_attempt_semantic_projection).unwrap(),
            both.captured_attempt_digest
        );
        let mut mismatched_policy_block = input();
        mismatched_policy_block.policy_block = Some(CapturedExecutionPolicyBlock {
            policy_code: "QUALIFICATION_PROFILE_REVOKED".into(),
            observed_at: "t1".into(),
            qualification_profile_id: Some("other".into()),
            observed_policy_version: None,
            policy_observation_digest: None,
            captured_attempt_digest: None,
        });
        assert_eq!(
            context_code(mismatched_policy_block),
            QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR
        );
    }
    #[test]
    fn compilation_requires_active_binding_and_exact_proof() {
        use crate::execution_compilation::{
            ACTIVE_FIELD_UNBOUND, COMPOSITION_STRUCTURE_MISMATCH, QualifyAndCompileExecutionResult,
            qualify_and_compile_execution,
        };
        use crate::execution_composition::{
            CompositionPremiseVerificationResult, CompositionPremisesPassed,
        };
        let CaptureExecutionQualificationResult::Complete(empty) =
            judge_captured_execution(input())
        else {
            panic!("complete capture expected")
        };
        let mut proof = CompositionPremiseVerificationResult::Passed(CompositionPremisesPassed {
            composition_contract_id: "comp/1".into(),
            native_primitive_contract_id: "nat/1".into(),
            template_structure_digest: empty
                .template
                .qualification
                .template_structure_digest
                .clone(),
            theorem_evidence_manifest_digest: "sha256:theorem".into(),
            verified_premise_facts: json!({}),
            premise_verification_digest: "sha256:proof".into(),
        });
        let QualifyAndCompileExecutionResult::Qualified(qualified) =
            qualify_and_compile_execution(&empty, &proof)
        else {
            panic!("empty slotless template qualifies")
        };
        assert!(qualified.ordered_operations.is_empty());
        if let CompositionPremiseVerificationResult::Passed(ref mut item) = proof {
            item.template_structure_digest = "sha256:wrong".into();
        }
        let QualifyAndCompileExecutionResult::ContextError(error) =
            qualify_and_compile_execution(&empty, &proof)
        else {
            panic!("wrong proof must be rejected")
        };
        assert_eq!(error.code, COMPOSITION_STRUCTURE_MISMATCH);
        let active_input = active_root_input();
        let digest = active_input
            .template
            .qualification
            .template_structure_digest
            .clone();
        let CaptureExecutionQualificationResult::Complete(active) =
            judge_captured_execution(active_input)
        else {
            panic!("capture should leave active binding qualification to compiler")
        };
        if let CompositionPremiseVerificationResult::Passed(ref mut item) = proof {
            item.template_structure_digest = digest;
        }
        let QualifyAndCompileExecutionResult::Blocked(blocked) =
            qualify_and_compile_execution(&active, &proof)
        else {
            panic!("unbound active field must block")
        };
        assert_eq!(blocked.normalized_blockers[0].code, ACTIVE_FIELD_UNBOUND);
    }

    #[test]
    fn compilation_emits_bound_field_and_blocks_missing_source_schema() {
        use crate::execution_compilation::{
            ExecutionOperation, QualifyAndCompileExecutionResult, REQUIRED_SOURCE_KEY_MISSING,
            encode_value_expression, qualify_and_compile_execution,
        };
        use crate::execution_composition::{
            CompositionPremiseVerificationResult, CompositionPremisesPassed,
        };
        use crate::field_binding::{FieldBindingRule, SOURCE, resolve_document_value_policy};

        let source_rule = FieldBindingRule {
            field_id: "f".into(),
            binding_kind: SOURCE.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: Some("name".into()),
            format_code: None,
            canonical_constant_value: None,
            format_kind: None,
            text_slice: None,
        };
        let proof_for = |digest: &str| {
            CompositionPremiseVerificationResult::Passed(CompositionPremisesPassed {
                composition_contract_id: "comp/1".into(),
                native_primitive_contract_id: "nat/1".into(),
                template_structure_digest: digest.into(),
                theorem_evidence_manifest_digest: "sha256:theorem".into(),
                verified_premise_facts: json!({}),
                premise_verification_digest: "sha256:proof".into(),
            })
        };
        let captured_with = |schema_keys: Vec<String>, inactive_key: &str| {
            let mut active = active_root_input();
            let mut inactive_rule = source_rule.clone();
            inactive_rule.field_id = "inactive".into();
            inactive_rule.source_key = Some(inactive_key.into());
            let binding = build_field_binding_input(
                "ws",
                "w",
                "app",
                vec![source_rule.clone(), inactive_rule],
                schema_keys,
                "rr/1",
                "t1",
            )
            .unwrap();
            active.field_binding_observation = FieldBindingObservation::Captured(Box::new(binding));
            let CaptureExecutionQualificationResult::Complete(captured) =
                judge_captured_execution(active)
            else {
                panic!("valid active field capture expected")
            };
            captured
        };
        let captured = captured_with(vec!["name".into()], "missing-inactive");
        let proof = proof_for(&captured.template.qualification.template_structure_digest);
        let QualifyAndCompileExecutionResult::Qualified(qualified) =
            qualify_and_compile_execution(&captured, &proof)
        else {
            panic!("active SOURCE field should compile")
        };
        assert_eq!(qualified.active_field_requirements.len(), 1);
        assert_eq!(qualified.active_field_requirements[0].field_id, "f");
        assert_eq!(
            qualified.effective_field_binding_basis.required_source_keys,
            ["name"]
        );
        assert_eq!(
            qualified.ordered_operations,
            [ExecutionOperation::ApplyFieldBinding {
                field_id: "f".into()
            }]
        );
        let expression =
            encode_value_expression(&qualified.active_field_requirements[0].value_expression);
        assert_eq!(expression["kind"], "FROM_SOURCE");
        assert_eq!(expression["source_key"], "name");
        assert!(expression.get("value_type").is_none());
        let changed_inactive = captured_with(vec!["name".into()], "another-missing-inactive");
        let QualifyAndCompileExecutionResult::Qualified(same_basis) =
            qualify_and_compile_execution(&changed_inactive, &proof)
        else {
            panic!("inactive binding should not block")
        };
        assert_eq!(
            qualified.execution_basis_semantic_digest,
            same_basis.execution_basis_semantic_digest
        );

        let missing = captured_with(vec!["other".into()], "missing-inactive");
        let QualifyAndCompileExecutionResult::Blocked(blocked) =
            qualify_and_compile_execution(&missing, &proof)
        else {
            panic!("missing required source column should block")
        };
        assert_eq!(
            blocked.normalized_blockers[0].code,
            REQUIRED_SOURCE_KEY_MISSING
        );
        assert_eq!(
            blocked.normalized_blockers[0].field_id.as_deref(),
            Some("f")
        );
    }

    #[test]
    fn active_field_projection_counts_repeated_root_and_selected_option_only() {
        use crate::execution_compilation::project_active_fields;
        use crate::execution_structure::FieldOccurrence;
        use std::collections::HashSet;

        let mut structure = active_root_input()
            .template
            .qualification
            .execution_structure;
        let mut repeated = structure.field_occurrences[0].clone();
        repeated.occurrence_ordinal = 1;
        repeated.structural_order = 30;
        let option = |field: &str, option: &str, order| FieldOccurrence {
            field_id: field.into(),
            occurrence_ordinal: 0,
            owner_kind: "OPTION".into(),
            owner_slot_id: Some("s".into()),
            owner_option_id: Some(option.into()),
            content_entry_id: "e".into(),
            structural_order: order,
            native_value_target_class: "text".into(),
            resolver_contract_id: "res/1".into(),
        };
        structure.field_occurrences = vec![
            repeated,
            option("chosen", "one", 20),
            option("hidden", "two", 10),
            structure.field_occurrences[0].clone(),
        ];
        let selected = HashSet::from([("s".into(), "one".into())]);
        let (projection, counts) = project_active_fields(&structure, &selected);
        assert_eq!(projection.active_field_sequence, ["f", "chosen", "f"]);
        assert_eq!(projection.active_logical_field_order, ["f", "chosen"]);
        assert_eq!(counts["f"], 2);
        assert!(!counts.contains_key("hidden"));
        let alternate = HashSet::from([("s".into(), "two".into())]);
        let (projection, _) = project_active_fields(&structure, &alternate);
        assert_eq!(projection.active_logical_field_order, ["f", "hidden"]);
    }
}
