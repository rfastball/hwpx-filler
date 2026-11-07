//! Store-backed, two-gate sealing of the current Work execution basis.

use crate::candidate_store::FileCandidateObjectStore;
use crate::job_registry::JobRegistry;
use crate::per_work_fence::PerWorkFence;
use crate::qualification_store::FileQualificationObjectStore;
use crate::work_configuration_store::{
    ConfigurationStoreErrorKind, WorkSlotConfigurationStore, WorkspaceMetadataStore,
};
use crate::work_template_store::AtomicWorkTemplateStateStore;
use hwpx_filler::document_creation_workbench::InputRequirement;
use hwpx_filler::execution_capture::{
    CaptureExecutionQualificationResult, CapturedExecutionPolicyBlock,
    CapturedTemplateExecutionInput, ExactTemplateQualificationContext, FieldBindingObservation,
    JudgeCapturedExecutionInput, QualificationProfileSemanticPayload, ResolvedSealPolicy,
    SelectionObservation, judge_captured_execution,
};
use hwpx_filler::execution_compilation::project_active_fields;
use hwpx_filler::execution_structure::{
    content_digest, decode_execution_structure, template_structure_digest,
};
use hwpx_filler::field_binding_input::{
    CurrentApplicationFieldStructure, review_field_binding_for_current_application,
};
use hwpx_filler::fresh_execution_observation::{
    ExecutionObservationContextError, FreshExecutionObservation,
};
use hwpx_filler::job_binding_projection::job_binding_input;
use hwpx_filler::runtime_capability::{
    ShippingRuntimeCapabilities, admitted_runtime_conformance_registry,
};
use hwpx_filler::seal_execution_plan::{
    CandidateCompilation, CaptureGateClassification, FinalVerdict, SealAttemptError,
    SealAttemptErrorKind, SealExecutionPlanCommand, WorkExecutionSummary, classify_capture_result,
    compile_candidate, decide_final_verdict, require_exact_selector_consistency,
    sealed_outcome_for,
};
use hwpx_filler::seal_execution_product::{RuntimeConformanceBinding, observe_current_capture};
use hwpx_filler::shipping_seal_policy::resolve_shipping_policy;
use hwpx_filler::slot_configuration_context::{
    ContextErrorKind, ContextPorts, resolve_exact_applied_template_input,
    resolve_slot_configuration_context,
};
use hwpx_filler::slot_selection_input::{SlotSelectionInput, plan_capture};
use hwpx_filler::stored_execution_plan::SealTerminalOutcome;
use hwpx_filler::stored_work_configuration::StoredWorkConfiguration;
use hwpx_filler::text_render::python_repr;
use serde_json::Value;
use serde_json::json;
use std::collections::HashSet;
use std::path::Path;

const CAPTURE_CONTEXT_ERROR: &str = "EXECUTION_CAPTURE_CONTEXT_ERROR";
const OBSERVATION_CONTEXT_ERROR: &str = "EXECUTION_OBSERVATION_CONTEXT_ERROR";

pub struct SealExecutionResponse {
    pub terminal_outcome: SealTerminalOutcome,
    pub work_authority_id: String,
    pub fresh_observation: FreshExecutionObservation,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BindingReviewProjection {
    pub active_field_ids: Vec<String>,
    pub input_requirements: Vec<InputRequirement>,
}

/// Read-only authority facts for a managed start gate. This accessor never mints an ID.
pub struct ManagedRunContext<'s, 'a> {
    service: &'s SealExecutionService<'a>,
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub runtime_capability_manifest_digest: String,
    command: SealExecutionPlanCommand,
}
impl ManagedRunContext<'_, '_> {
    pub fn runtime_registry(
        &self,
    ) -> &hwpx_filler::execution_composition::RuntimeMaterializerConformanceRegistry {
        &self.service.runtime.registry
    }
    /// The caller holds `PerWorkFence`; the reader must not acquire it again.
    pub fn observe_current_basis_digest(&self) -> Option<String> {
        self.service
            .observe_current_basis_digest(&self.command, &self.work_authority_id)
    }
}

/// Owns store readers; Work fences are held only for exact capture and final reread.
pub struct SealExecutionService<'a> {
    jobs: &'a JobRegistry,
    works: AtomicWorkTemplateStateStore,
    configurations: WorkSlotConfigurationStore,
    candidates: FileCandidateObjectStore,
    qualifications: FileQualificationObjectStore,
    workspace: WorkspaceMetadataStore,
    runtime: ShippingRuntimeCapabilities,
    clock: Box<dyn Fn() -> String + Send + Sync + 'a>,
}

impl<'a> SealExecutionService<'a> {
    /// Read the exact current application and Binding review without minting an authority ID.
    /// An incomplete slot selection has no current review yet.
    pub fn current_binding_review(
        &self,
        work_ref: &str,
    ) -> Result<Option<BindingReviewProjection>, SealAttemptError> {
        let job = self
            .jobs
            .load(work_ref)
            .map_err(|error| SealAttemptError::context(error.to_string()))?;
        if job.authority_id.is_empty() {
            return Ok(None);
        }
        let Some(workspace_id) = self
            .workspace
            .read()
            .map_err(|error| SealAttemptError::context(error.to_string()))?
        else {
            return Ok(None);
        };
        PerWorkFence::with(&workspace_id, &job.authority_id, || {
            let aggregate = self
                .works
                .load(&job.authority_id)
                .map_err(|error| SealAttemptError::context(error.to_string()))?;
            let application_id = &aggregate.work.current_template_application_id;
            resolve_exact_applied_template_input(self.ports(), &job.authority_id, application_id)
                .map_err(|error| {
                SealAttemptError::context_code(error.detail, context_code(error.kind))
            })?;
            let context = resolve_slot_configuration_context(
                self.ports(),
                &workspace_id,
                &job.authority_id,
                Some(application_id),
                None,
            )
            .map_err(|error| {
                SealAttemptError::context_code(error.detail, context_code(error.kind))
            })?;
            let evidence = self
                .qualifications
                .get_evidence(&context.pass_evidence_id)
                .map_err(|error| SealAttemptError::context(error.to_string()))?;
            let Some(projection) = evidence.structure_projection else {
                return Ok(None);
            };
            let structure = decode_execution_structure(&projection.payload)
                .map_err(|error| SealAttemptError::context_code(error.to_string(), error.code))?;
            let stored = self
                .load_configuration(&workspace_id, &job.authority_id)
                .map_err(SealAttemptError::context)?;
            let draft = stored.as_ref().and_then(|item| {
                item.configurations
                    .configurations
                    .iter()
                    .find(|item| item.base_template_application_id == *application_id)
            });
            let now = (self.clock)();
            let selection = match plan_capture(&context, draft, &now, None, None) {
                Ok(value) => value,
                Err(_) => return Ok(None),
            };
            let selected = match selection {
                SlotSelectionInput::Slotless(_) => HashSet::new(),
                SlotSelectionInput::Slotted(value) => value
                    .effective_selections
                    .selections
                    .iter()
                    .flat_map(|item| {
                        item.selected_option_ids
                            .iter()
                            .map(|option| (item.slot_id.clone(), option.clone()))
                    })
                    .collect(),
            };
            let active_field_ids = project_active_fields(&structure, &selected)
                .0
                .active_logical_field_order;
            let active = active_field_ids.iter().collect::<HashSet<_>>();
            let mut seen = HashSet::new();
            let inactive_field_ids = structure
                .field_occurrences
                .iter()
                .filter(|occurrence| {
                    !active.contains(&occurrence.field_id)
                        && seen.insert(occurrence.field_id.as_str())
                })
                .map(|occurrence| occurrence.field_id.clone())
                .collect();
            let binding = job_binding_input(&job, &workspace_id, application_id, &now)
                .map_err(|error| SealAttemptError::context_code(error.to_string(), error.code()))?;
            let review = review_field_binding_for_current_application(
                &binding,
                &CurrentApplicationFieldStructure {
                    application_id: application_id.clone(),
                    active_field_ids: active_field_ids.clone(),
                    inactive_field_ids,
                    source_schema_keys: binding.source_schema_keys.clone(),
                },
            );
            Ok(Some(BindingReviewProjection {
                active_field_ids,
                input_requirements: review
                    .classifications
                    .iter()
                    .map(|item| InputRequirement {
                        field_id: item.field_id.clone(),
                        display_label: item.field_id.clone(),
                        binding_state: item.category.into(),
                        exact_target: format!("binding/{}", item.field_id),
                    })
                    .collect(),
            }))
        })
        .map_err(|error| SealAttemptError::context(error.to_string()))?
    }

    pub fn current_active_field_ids(
        &self,
        work_ref: &str,
    ) -> Result<Option<Vec<String>>, SealAttemptError> {
        self.current_binding_review(work_ref)
            .map(|review| review.map(|item| item.active_field_ids))
    }
    /// Workbench media is observed before its internal seal attempt, as in the product command.
    pub fn job_media(&self, work_ref: &str) -> Result<&'static str, SealAttemptError> {
        self.jobs
            .load(work_ref)
            .map(|job| job.media())
            .map_err(|error| SealAttemptError::context(error.to_string()))
    }

    /// A missing Work aggregate is the initialization refusal, not a generic seal failure.
    pub fn missing_work_detail(&self, work_ref: &str) -> Result<Option<String>, SealAttemptError> {
        let job = self
            .jobs
            .load(work_ref)
            .map_err(|error| SealAttemptError::context(error.to_string()))?;
        if job.authority_id.is_empty() {
            return Ok(Some("work aggregate 없음".into()));
        }
        self.works
            .exists(&job.authority_id)
            .map(|exists| (!exists).then(|| format!("work {} aggregate 없음", job.authority_id)))
            .map_err(|error| SealAttemptError::context(error.to_string()))
    }
    pub fn new(
        authority_root: &Path,
        jobs: &'a JobRegistry,
        clock: impl Fn() -> String + Send + Sync + 'a,
    ) -> Result<Self, SealAttemptError> {
        let context =
            |error: Box<dyn std::error::Error>| SealAttemptError::context(error.to_string());
        Ok(Self {
            jobs,
            works: AtomicWorkTemplateStateStore::new(authority_root.join("works"))
                .map_err(|error| context(Box::new(error)))?,
            configurations: WorkSlotConfigurationStore::new(authority_root.join("slot_configs"))
                .map_err(|error| context(Box::new(error)))?,
            candidates: FileCandidateObjectStore::new(authority_root.join("candidates")),
            qualifications: FileQualificationObjectStore::new(authority_root.join("qualification")),
            workspace: WorkspaceMetadataStore::new(authority_root)
                .map_err(|error| context(Box::new(error)))?,
            runtime: admitted_runtime_conformance_registry().map_err(SealAttemptError::context)?,
            clock: Box::new(clock),
        })
    }

    pub fn managed_run_context(
        &self,
        work_ref: &str,
        media: &str,
    ) -> Result<Option<ManagedRunContext<'_, 'a>>, SealAttemptError> {
        let job = self
            .jobs
            .load(work_ref)
            .map_err(|error| SealAttemptError::context(error.to_string()))?;
        if job.authority_id.is_empty() {
            return Ok(None);
        }
        let Some(workspace_id) = self
            .workspace
            .read()
            .map_err(|error| SealAttemptError::context(error.to_string()))?
        else {
            return Ok(None);
        };
        let command = SealExecutionPlanCommand::new(&workspace_id, work_ref, "managed-basis-read")?;
        let manifest = if media == "txt" {
            &self.runtime.txt
        } else {
            &self.runtime.hwpx
        };
        Ok(Some(ManagedRunContext {
            service: self,
            workspace_instance_id: workspace_id,
            work_authority_id: job.authority_id,
            runtime_capability_manifest_digest: manifest.runtime_capability_manifest_digest.clone(),
            command,
        }))
    }

    fn ports(
        &self,
    ) -> ContextPorts<
        '_,
        AtomicWorkTemplateStateStore,
        FileQualificationObjectStore,
        FileCandidateObjectStore,
    > {
        ContextPorts {
            work_state: &self.works,
            qualification: &self.qualifications,
            candidate: &self.candidates,
        }
    }

    fn route(&self, work_ref: &str) -> Result<String, SealAttemptError> {
        let unavailable = || SealAttemptError {
            kind: SealAttemptErrorKind::RouteResolution,
            detail: format!(
                "work {} 접근 불가",
                python_repr(&Value::String(work_ref.into()))
            ),
            cause_code: None,
        };
        let job = self.jobs.load(work_ref).map_err(|_| unavailable())?;
        if !job.authority_id.is_empty() {
            return Ok(job.authority_id);
        }
        let id = uuid::Uuid::new_v4().simple().to_string();
        let assigned = self
            .jobs
            .assign_authority_id(work_ref, &id)
            .map_err(|_| unavailable())?;
        if assigned.authority_id.is_empty() {
            return Err(unavailable());
        }
        Ok(assigned.authority_id)
    }

    fn summary(&self, work_id: &str) -> Result<WorkExecutionSummary, SealAttemptError> {
        let aggregate = self
            .works
            .load(work_id)
            .map_err(|error| SealAttemptError::context(error.to_string()))?;
        let current = &aggregate.work.current_template_application_id;
        let application = aggregate
            .applications
            .iter()
            .find(|item| item.application_id == *current)
            .ok_or_else(|| {
                SealAttemptError::context(format!(
                    "current application {} 이 applications 에 없다",
                    python_repr(&Value::String(current.clone()))
                ))
            })?;
        let evidence = self
            .qualifications
            .get_evidence(&application.pass_evidence_id)
            .map_err(|error| SealAttemptError::context(error.to_string()))?;
        Ok(WorkExecutionSummary {
            qualification_profile_id: evidence.qualification_profile_id,
            template_application_id: current.clone(),
        })
    }

    fn load_configuration(
        &self,
        workspace_id: &str,
        work_id: &str,
    ) -> Result<Option<StoredWorkConfiguration>, String> {
        let stored = match self.configurations.load(work_id) {
            Ok(stored) => stored,
            Err(error) if error.kind == ConfigurationStoreErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.to_string()),
        };
        if stored.workspace_instance_id != workspace_id {
            return Err("저장 workspace 가 current workspace 와 다르다".into());
        }
        Ok(Some(stored))
    }

    fn capture(
        &self,
        command: &SealExecutionPlanCommand,
        work_id: &str,
        application_id: &str,
        profile_id: &str,
        policy: &ResolvedSealPolicy,
    ) -> CaptureExecutionQualificationResult {
        let now = (self.clock)();
        let inner = || -> Result<_, (String, String)> {
            let revocation = self
                .qualifications
                .get_revocation(profile_id)
                .map_err(|error| (CAPTURE_CONTEXT_ERROR.into(), error.to_string()))?;
            if let Some(item) = revocation {
                return Ok(Some(CaptureExecutionQualificationResult::PolicyBlocked(
                    CapturedExecutionPolicyBlock {
                        policy_code: "QUALIFICATION_PROFILE_REVOKED".into(),
                        observed_at: now.clone(),
                        qualification_profile_id: Some(item.qualification_profile_id.clone()),
                        observed_policy_version: None,
                        policy_observation_digest: Some(content_digest(&json!({
                            "qualification_profile_id": item.qualification_profile_id,
                            "reason": item.reason,
                            "authority": item.authority,
                            "revoked_at": item.revoked_at,
                        }))),
                        captured_attempt_digest: None,
                    },
                )));
            }
            let applied =
                resolve_exact_applied_template_input(self.ports(), work_id, application_id)
                    .map_err(|error| (context_code(error.kind).into(), error.detail))?;
            let context = resolve_slot_configuration_context(
                self.ports(),
                &command.workspace_instance_id,
                work_id,
                Some(application_id),
                None,
            )
            .map_err(|error| (context_code(error.kind).into(), error.detail))?;
            let evidence = self
                .qualifications
                .get_evidence(&context.pass_evidence_id)
                .map_err(|error| (CAPTURE_CONTEXT_ERROR.into(), error.to_string()))?;
            let projection = evidence.structure_projection.ok_or_else(|| {
                (
                    CAPTURE_CONTEXT_ERROR.into(),
                    "PASS Evidence 에 structure projection 부재".into(),
                )
            })?;
            let structure = decode_execution_structure(&projection.payload)
                .map_err(|error| (CAPTURE_CONTEXT_ERROR.into(), error.to_string()))?;
            let manifest = self
                .qualifications
                .get_manifest(&context.qualification_profile_id)
                .map_err(|error| (CAPTURE_CONTEXT_ERROR.into(), error.to_string()))?;
            let semantic_payload = QualificationProfileSemanticPayload {
                qualification_profile_id: manifest.qualification_profile_id,
                media: manifest.media,
                adapter_contract_version: manifest.adapter_contract_version,
                product_rule_version: manifest.product_rule_version,
                operation_alphabet_version: manifest.operation_alphabet_version,
                projection_schema_version: manifest.projection_schema_version,
                manifest_payload: manifest.manifest_payload,
            };
            let template = CapturedTemplateExecutionInput {
                workspace_instance_id: command.workspace_instance_id.clone(),
                work_authority_id: work_id.into(),
                applied,
                qualification: ExactTemplateQualificationContext {
                    pass_evidence_id: context.pass_evidence_id.clone(),
                    qualification_profile_id: context.qualification_profile_id.clone(),
                    qualification_profile_semantic_payload: semantic_payload,
                    structure_projection_schema_version: context
                        .structure_projection_schema_version
                        .clone(),
                    template_structure_digest: template_structure_digest(&structure),
                    execution_structure: structure,
                    composition_profile_state: "SEALED".into(),
                    revision_id: context.revision_id.clone(),
                    qualification_profile_semantic_digest: None,
                },
                captured_at: now.clone(),
            };
            let stored = self
                .load_configuration(&command.workspace_instance_id, work_id)
                .map_err(|detail| (CAPTURE_CONTEXT_ERROR.into(), detail))?;
            let draft = stored.as_ref().and_then(|item| {
                item.configurations
                    .configurations
                    .iter()
                    .find(|item| item.base_template_application_id == application_id)
            });
            let selection = match plan_capture(&context, draft, &now, None, None) {
                Ok(item) => SelectionObservation::Captured(item),
                Err(error) => SelectionObservation::DomainBlocked {
                    blocker_code: error.code,
                    detail: error.message,
                },
            };
            let job = self
                .jobs
                .load(&command.work_ref)
                .map_err(|error| (CAPTURE_CONTEXT_ERROR.into(), error.to_string()))?;
            if job.authority_id != work_id {
                return Err((
                    CAPTURE_CONTEXT_ERROR.into(),
                    "Field Binding capture 의 Work identity 가 이동했습니다".into(),
                ));
            }
            let binding =
                job_binding_input(&job, &command.workspace_instance_id, application_id, &now)
                    .map_err(|error| (CAPTURE_CONTEXT_ERROR.into(), error.to_string()))?;
            Ok(Some(judge_captured_execution(
                JudgeCapturedExecutionInput {
                    workspace_instance_id: command.workspace_instance_id.clone(),
                    work_authority_id: work_id.into(),
                    expected_template_application_id: application_id.into(),
                    expected_profile_id: profile_id.into(),
                    resolved_seal_policy: policy.clone(),
                    template,
                    selection_observation: selection,
                    field_binding_observation: FieldBindingObservation::Captured(Box::new(binding)),
                    captured_at: now,
                    policy_block: None,
                },
            )))
        };
        match inner() {
            Ok(Some(result)) => result,
            Ok(None) => unreachable!("capture always returns a result"),
            Err((code, detail)) => CaptureExecutionQualificationResult::ContextError(
                hwpx_filler::execution_capture::ExecutionCaptureContextError { code, detail },
            ),
        }
    }

    fn capture_gate(
        &self,
        command: &SealExecutionPlanCommand,
        work_id: &str,
    ) -> Result<
        (
            WorkExecutionSummary,
            ResolvedSealPolicy,
            CaptureGateClassification,
        ),
        SealAttemptError,
    > {
        let summary = self.summary(work_id)?;
        let policy = resolve_shipping_policy(command, &summary);
        require_exact_selector_consistency(command, &policy)?;
        let captured = self.capture(
            command,
            work_id,
            &summary.template_application_id,
            &summary.qualification_profile_id,
            &policy,
        );
        let classified = classify_capture_result(captured, &policy)?;
        Ok((summary, policy, classified))
    }

    pub fn seal(
        &self,
        work_ref: &str,
        request_id: &str,
    ) -> Result<SealExecutionResponse, SealAttemptError> {
        self.seal_with_compiler(work_ref, request_id, compile_candidate)
    }

    fn seal_with_compiler(
        &self,
        work_ref: &str,
        request_id: &str,
        mut compile: impl FnMut(
            &hwpx_filler::execution_capture::CapturedExecutionInput,
        ) -> Result<CandidateCompilation, SealAttemptError>,
    ) -> Result<SealExecutionResponse, SealAttemptError> {
        let now = (self.clock)();
        let workspace_id = self
            .workspace
            .get_or_create(&now)
            .map_err(|error| SealAttemptError::context(error.to_string()))?;
        let command = SealExecutionPlanCommand::new(&workspace_id, work_ref, request_id)?;
        let work_id = self.route(work_ref)?;
        let initial = PerWorkFence::with(&workspace_id, &work_id, || {
            self.capture_gate(&command, &work_id)
        })
        .map_err(|error| SealAttemptError::context(error.to_string()))??;
        let terminal = match initial.2 {
            CaptureGateClassification::Terminal { outcome, .. } => outcome,
            CaptureGateClassification::Complete(captured) => {
                let candidate = compile(&captured)?;
                PerWorkFence::with(&workspace_id, &work_id, || {
                    let summary = self.summary(&work_id)?;
                    let current = self.capture(
                        &command,
                        &work_id,
                        &summary.template_application_id,
                        candidate_profile_id(&candidate),
                        candidate_policy(&candidate),
                    );
                    let current_compiled = match &current {
                        CaptureExecutionQualificationResult::Complete(item) => Some(compile(item)?),
                        _ => None,
                    };
                    match decide_final_verdict(candidate, current, current_compiled, &summary)? {
                        FinalVerdict::Publish(item) => Ok(SealTerminalOutcome::Sealed(Box::new(
                            sealed_outcome_for(*item),
                        ))),
                        FinalVerdict::Ledger { outcome, .. } => Ok(outcome),
                    }
                })
                .map_err(|error| SealAttemptError::context(error.to_string()))??
            }
        };
        let fresh = match PerWorkFence::with(
            &workspace_id,
            &work_id,
            || -> Result<_, SealAttemptError> {
                let summary = self.summary(&work_id)?;
                let policy = resolve_shipping_policy(&command, &summary);
                let current = self.capture(
                    &command,
                    &work_id,
                    &summary.template_application_id,
                    &summary.qualification_profile_id,
                    &policy,
                );
                Ok(observe_current_capture(
                    &work_id,
                    &summary,
                    &policy,
                    current,
                    &(self.clock)(),
                    &RuntimeConformanceBinding {
                        registry: &self.runtime.registry,
                        primary_manifest: &self.runtime.hwpx,
                        additional_manifests: std::slice::from_ref(&self.runtime.txt),
                    },
                ))
            },
        ) {
            Ok(Ok(observation)) => observation,
            Ok(Err(error)) => observation_error(error.detail),
            Err(error) => observation_error(error.to_string()),
        };
        Ok(SealExecutionResponse {
            terminal_outcome: terminal,
            work_authority_id: work_id,
            fresh_observation: fresh,
        })
    }

    /// Called while the outer Work fence is already held by the start gate.
    pub fn observe_current_basis_digest(
        &self,
        command: &SealExecutionPlanCommand,
        work_id: &str,
    ) -> Option<String> {
        let (_, _, capture) = self.capture_gate(command, work_id).ok()?;
        let CaptureGateClassification::Complete(captured) = capture else {
            return None;
        };
        match compile_candidate(&captured).ok()? {
            CandidateCompilation::Plan(item) => Some(item.execution_basis_digest),
            CandidateCompilation::Blocked(_) => None,
        }
    }
}

fn context_code(kind: ContextErrorKind) -> &'static str {
    match kind {
        ContextErrorKind::TemplateInitializationRequired => "TEMPLATE_INITIALIZATION_REQUIRED",
        ContextErrorKind::StaleTemplateApplication => "STALE_TEMPLATE_APPLICATION",
        ContextErrorKind::UnsupportedTemplateStructureProjection => {
            "UNSUPPORTED_TEMPLATE_STRUCTURE_PROJECTION"
        }
        ContextErrorKind::TemplateStructureIntegrity => "TEMPLATE_STRUCTURE_INTEGRITY_ERROR",
        ContextErrorKind::AppliedTemplateContentIntegrity => {
            "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"
        }
        ContextErrorKind::CrossWork => "CROSS_WORK_CONTEXT",
        ContextErrorKind::Read | ContextErrorKind::UnsupportedSelectionContract => {
            CAPTURE_CONTEXT_ERROR
        }
    }
}
fn candidate_profile_id(candidate: &CandidateCompilation) -> &str {
    match candidate {
        CandidateCompilation::Plan(item) => &item.qualification_profile_id,
        CandidateCompilation::Blocked(item) => &item.qualification_profile_id,
    }
}
fn candidate_policy(candidate: &CandidateCompilation) -> &ResolvedSealPolicy {
    match candidate {
        CandidateCompilation::Plan(item) => &item.resolved_seal_policy,
        CandidateCompilation::Blocked(item) => &item.resolved_seal_policy,
    }
}
fn observation_error(detail: String) -> FreshExecutionObservation {
    FreshExecutionObservation::ContextError(ExecutionObservationContextError {
        code: OBSERVATION_CONTEXT_ERROR.into(),
        detail,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::managed_generation_service::tests::RunFixture;
    use hwpx_filler::execution_contract_set::execution_basis_digest;
    use hwpx_filler::job::Job;
    use hwpx_filler::qualification_evidence::QualificationProfileRevocation;
    use std::fs;

    #[test]
    fn final_reread_observes_changes_after_unfenced_compile_and_keeps_candidate_policy() {
        use crate::per_work_fence::tests::{assert_held, assert_released};
        use crate::slot_configuration_product::{SlotConfigurationProduct, tests::advance};
        for axis in 0..4 {
            let fixture = RunFixture::txt();
            fixture.choose("o1");
            let service =
                SealExecutionService::new(&fixture.authority, &fixture.jobs, || "now".into())
                    .unwrap();
            let job = fixture.jobs.load("생성").unwrap();
            let workspace = service.workspace.read().unwrap().unwrap();
            let mut compile_calls = 0;
            let mut original_policy = None;
            let response = service
                .seal_with_compiler("생성", "race", |input| {
                    compile_calls += 1;
                    let compiled = compile_candidate(input)?;
                    if compile_calls == 1 {
                        assert_released(&workspace, &job.authority_id);
                        original_policy = Some(input.resolved_seal_policy.clone());
                        match axis {
                            0 => fixture.choose("o2"),
                            1 => {
                                fixture
                                    .jobs
                                    .mutate("생성", |job| job.mapping.mappings.clear())
                                    .unwrap();
                            }
                            2 => {
                                let mut bytes = fs::read(&job.template_path).unwrap();
                                bytes.extend_from_slice(b"\nnew revision\n");
                                advance(&fixture, &bytes);
                                let slots = SlotConfigurationProduct::new(
                                    &fixture.authority,
                                    fixture.jobs.clone(),
                                    || "now".into(),
                                );
                                slots.open_slot_configuration("생성").unwrap();
                                fixture.choose("o1");
                            }
                            _ => service
                                .qualifications
                                .put_revocation(&QualificationProfileRevocation {
                                    qualification_profile_id: input
                                        .template
                                        .qualification
                                        .qualification_profile_id
                                        .clone(),
                                    reason: "policy".into(),
                                    authority: "admin".into(),
                                    revoked_at: "now".into(),
                                })
                                .unwrap(),
                        }
                    } else {
                        assert_held(&workspace, &job.authority_id);
                        assert_eq!(Some(&input.resolved_seal_policy), original_policy.as_ref());
                    }
                    Ok(compiled)
                })
                .unwrap();
            assert_released(&workspace, &job.authority_id);
            assert_eq!(response.work_authority_id, job.authority_id);
            if axis == 3 {
                assert_eq!(compile_calls, 1);
                let SealTerminalOutcome::PolicyBlocked(block) = response.terminal_outcome else {
                    panic!("revocation precedence")
                };
                assert_eq!(block.policy_code, "QUALIFICATION_PROFILE_REVOKED");
            } else {
                assert_eq!(compile_calls, 2, "axis {axis}");
                let SealTerminalOutcome::Stale(stale) = response.terminal_outcome else {
                    panic!("axis {axis} must be stale")
                };
                assert_eq!(
                    stale.stale_reason,
                    if axis == 1 {
                        "CURRENT_BASIS_NOT_SEALABLE"
                    } else {
                        "DIGEST_MISMATCH"
                    }
                );
                if axis == 2 {
                    let old = job.authority_id.clone();
                    let current = service.summary(&old).unwrap();
                    assert_eq!(
                        stale.observed_current_summary.unwrap()["template_application_id"],
                        current.template_application_id
                    );
                }
            }
            match (axis, response.fresh_observation) {
                (0 | 2, FreshExecutionObservation::Sealed(observation)) => {
                    assert_eq!(observation.materialization_readiness(), "READY")
                }
                (1, FreshExecutionObservation::WorkBlocked(observation)) => {
                    assert_eq!(observation.current_sealability, "DOMAIN_BLOCKED")
                }
                (3, FreshExecutionObservation::WorkBlocked(observation)) => {
                    assert_eq!(observation.current_sealability, "POLICY_BLOCKED")
                }
                _ => panic!("fresh observation must describe current authority"),
            }
        }
    }

    #[test]
    fn observation_failure_preserves_success_and_does_not_reroute_the_command() {
        for rename in [false, true] {
            let fixture = RunFixture::txt();
            fixture.choose("o1");
            let service =
                SealExecutionService::new(&fixture.authority, &fixture.jobs, || "now".into())
                    .unwrap();
            let work = fixture.jobs.load("생성").unwrap().authority_id;
            let mut calls = 0;
            let response = service
                .seal_with_compiler("생성", "observe", |input| {
                    calls += 1;
                    let compiled = compile_candidate(input)?;
                    if calls == 2 {
                        if rename {
                            fixture.jobs.rename("생성", "renamed").unwrap();
                        } else {
                            fs::write(
                                fixture.authority.join("works").join(format!("{work}.json")),
                                b"corrupt",
                            )
                            .unwrap();
                        }
                    }
                    Ok(compiled)
                })
                .unwrap();
            assert_eq!(calls, 2);
            assert_eq!(response.work_authority_id, work);
            let SealTerminalOutcome::Sealed(sealed) = response.terminal_outcome else {
                panic!("observation erased success")
            };
            assert!(sealed.plan_payload.is_some());
            if rename {
                let FreshExecutionObservation::WorkBlocked(observation) =
                    response.fresh_observation
                else {
                    panic!("capture context")
                };
                assert_eq!(observation.current_sealability, "CONTEXT_ERROR");
                assert_eq!(observation.work_authority_ref, work);
                assert_eq!(
                    service.seal("생성", "observe").err().unwrap().kind,
                    SealAttemptErrorKind::RouteResolution
                );
                assert!(matches!(
                    service.seal("renamed", "observe").unwrap().terminal_outcome,
                    SealTerminalOutcome::Sealed(_)
                ));
            } else {
                let FreshExecutionObservation::ContextError(error) = response.fresh_observation
                else {
                    panic!("read context")
                };
                assert_eq!(error.code, OBSERVATION_CONTEXT_ERROR);
            }
        }
    }

    #[test]
    fn saved_mapping_roundtrip_recomputes_ready_plan_and_preserves_inactive_bindings() {
        let fixture = RunFixture::txt();
        let service =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || "t0".into()).unwrap();
        assert!(service.current_binding_review("생성").unwrap().is_none());
        let incomplete = service.seal("생성", "no-selection").unwrap();
        let SealTerminalOutcome::QualificationBlocked(block) = incomplete.terminal_outcome else {
            panic!("missing selection accepted")
        };
        assert!(
            block
                .normalized_blockers
                .iter()
                .any(|b| b == "SLOT_CONFIGURATION_INCOMPLETE")
        );
        let original_job = fixture.jobs.load("생성").unwrap();
        let original_bytes = fs::read(fixture.jobs.path_for("생성")).unwrap();
        let mut first_basis = None;
        for option in ["o1", "o2", "o1"] {
            fixture.choose(option);
            let review = service.current_binding_review("생성").unwrap().unwrap();
            let (active, inactive) = if option == "o1" {
                ("선택", "제외")
            } else {
                ("제외", "선택")
            };
            assert_eq!(review.active_field_ids, ["성명", active]);
            assert_eq!(
                service.current_active_field_ids("생성").unwrap().unwrap(),
                review.active_field_ids
            );
            for item in review.input_requirements {
                assert_eq!(
                    item.binding_state,
                    if item.field_id == inactive {
                        "INACTIVE_ONLY"
                    } else {
                        "PRESERVED"
                    }
                );
                assert!(!item.action_required());
                assert_eq!(item.exact_target, format!("binding/{}", item.field_id));
            }
            let result = service.seal("생성", "same-request-recomputed").unwrap();
            assert_eq!(result.work_authority_id, original_job.authority_id);
            let SealTerminalOutcome::Sealed(sealed) = result.terminal_outcome else {
                panic!("expected sealed")
            };
            let payload = sealed.plan_payload.as_ref().unwrap();
            assert_eq!(
                execution_basis_digest(&payload.execution_basis).unwrap(),
                sealed.execution_basis_digest
            );
            let FreshExecutionObservation::Sealed(observed) = result.fresh_observation else {
                panic!("expected observation")
            };
            assert_eq!(&observed.sealed_plan_value, payload);
            assert_eq!(observed.runtime_policy_admission.state, "ADMITTED");
            assert!(observed.runtime_policy_admission.reasons.is_empty());
            assert_eq!(observed.materialization_readiness(), "READY");
            let context = service.managed_run_context("생성", "txt").unwrap().unwrap();
            assert_eq!(context.work_authority_id, original_job.authority_id);
            assert!(
                context
                    .runtime_capability_manifest_digest
                    .starts_with("sha256:")
            );
            let current = PerWorkFence::with(
                &context.workspace_instance_id,
                &context.work_authority_id,
                || context.observe_current_basis_digest(),
            )
            .unwrap();
            assert_eq!(current.as_ref(), Some(&sealed.execution_basis_digest));
            if let Some(first) = &first_basis {
                assert_eq!(first == &sealed.execution_basis_digest, option == "o1");
            } else {
                first_basis = Some(sealed.execution_basis_digest);
            }
        }
        assert_eq!(
            fs::read(fixture.jobs.path_for("생성")).unwrap(),
            original_bytes
        );
        assert!(!fixture.authority.join("field_bindings").exists());
        let mut job = original_job;
        job.mapping.mappings.clear();
        fixture.jobs.save(&mut job, true).unwrap();
        let review = service.current_binding_review("생성").unwrap().unwrap();
        assert_eq!(review.active_field_ids, ["성명", "선택"]);
        assert!(
            review
                .input_requirements
                .iter()
                .all(|r| r.binding_state == "NEW_ACTIVE_FIELD" && r.action_required())
        );
        let response = service.seal("생성", "unbound").unwrap();
        assert!(matches!(
            response.terminal_outcome,
            SealTerminalOutcome::QualificationBlocked(_)
        ));
        let FreshExecutionObservation::WorkBlocked(observed) = response.fresh_observation else {
            panic!("expected current block")
        };
        assert_eq!(observed.current_sealability, "DOMAIN_BLOCKED");
        let context = service.managed_run_context("생성", "txt").unwrap().unwrap();
        assert!(
            PerWorkFence::with(
                &context.workspace_instance_id,
                &context.work_authority_id,
                || context.observe_current_basis_digest()
            )
            .unwrap()
            .is_none()
        );
    }

    #[test]
    fn capture_and_binding_review_reject_foreign_workspace_without_changing_stored_choices() {
        let fixture = RunFixture::txt();
        fixture.choose("o1");
        let service =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || "t0".into()).unwrap();
        let job = fixture.jobs.load("생성").unwrap();
        let workspace = service.workspace.read().unwrap().unwrap();
        let command = SealExecutionPlanCommand::new(&workspace, "생성", "capture").unwrap();
        let summary = service.summary(&job.authority_id).unwrap();
        let policy = resolve_shipping_policy(&command, &summary);
        let capture = |application: &str| {
            PerWorkFence::with(&workspace, &job.authority_id, || {
                service.capture(
                    &command,
                    &job.authority_id,
                    application,
                    &summary.qualification_profile_id,
                    &policy,
                )
            })
            .unwrap()
        };
        assert!(matches!(
            capture(&summary.template_application_id),
            CaptureExecutionQualificationResult::Complete(_)
        ));
        let mut moved = job.clone();
        moved.authority_id = "other-work".into();
        fixture.jobs.save(&mut moved, true).unwrap();
        let CaptureExecutionQualificationResult::ContextError(error) =
            capture(&summary.template_application_id)
        else {
            panic!("moved route accepted")
        };
        assert!(error.detail.contains("Work identity"));
        let mut restored = job.clone();
        fixture.jobs.save(&mut restored, true).unwrap();
        assert!(service.current_binding_review("생성").unwrap().is_some());
        assert!(matches!(
            capture("stale-application"),
            CaptureExecutionQualificationResult::ContextError(_)
        ));
        let path = fixture
            .authority
            .join("slot_configs")
            .join(format!("{}.json", job.authority_id));
        let original = fs::read(&path).unwrap();
        let mut envelope: Value = serde_json::from_slice(&original).unwrap();
        envelope["content"]["workspace_instance_id"] = json!("another-workspace");
        envelope["digest"] = json!(content_digest(&envelope["content"]));
        let foreign = serde_json::to_vec(&envelope).unwrap();
        fs::write(&path, &foreign).unwrap();
        let CaptureExecutionQualificationResult::ContextError(error) =
            capture(&summary.template_application_id)
        else {
            panic!("foreign workspace reached execution capture")
        };
        assert_eq!(error.code, CAPTURE_CONTEXT_ERROR);
        assert!(error.detail.contains("workspace"));
        assert!(service.current_binding_review("생성").is_err());
        assert_eq!(fs::read(&path).unwrap(), foreign);
        fs::write(&path, &original).unwrap();
        assert!(matches!(
            capture(&summary.template_application_id),
            CaptureExecutionQualificationResult::Complete(_)
        ));
        let mut other_application = serde_json::from_slice::<Value>(&original).unwrap();
        other_application["content"]["configurations"]["configurations"][0]["base_template_application_id"] =
            json!("other-application");
        other_application["digest"] = json!(content_digest(&other_application["content"]));
        let other_bytes = serde_json::to_vec(&other_application).unwrap();
        fs::write(&path, &other_bytes).unwrap();
        assert!(matches!(
            capture(&summary.template_application_id),
            CaptureExecutionQualificationResult::DomainBlocked(_)
        ));
        assert_eq!(fs::read(&path).unwrap(), other_bytes);
        fs::write(&path, &original).unwrap();

        let aggregate = service.works.load(&job.authority_id).unwrap();
        let evidence = &aggregate
            .applications
            .iter()
            .find(|a| a.application_id == summary.template_application_id)
            .unwrap()
            .pass_evidence_id;
        let evidence_path = service
            .qualifications
            .object_path("evidence", evidence)
            .unwrap();
        let evidence_bytes = fs::read(&evidence_path).unwrap();
        fs::write(&evidence_path, b"corrupt").unwrap();
        assert!(service.summary(&job.authority_id).is_err());
        assert!(matches!(
            capture(&summary.template_application_id),
            CaptureExecutionQualificationResult::ContextError(_)
        ));
        assert_eq!(fs::read(&evidence_path).unwrap(), b"corrupt");
        fs::write(&evidence_path, evidence_bytes).unwrap();

        service
            .qualifications
            .put_revocation(&QualificationProfileRevocation {
                qualification_profile_id: summary.qualification_profile_id.clone(),
                reason: "policy".into(),
                authority: "admin".into(),
                revoked_at: "t0".into(),
            })
            .unwrap();
        let CaptureExecutionQualificationResult::PolicyBlocked(block) =
            capture(&summary.template_application_id)
        else {
            panic!("revoked profile accepted")
        };
        assert_eq!(block.policy_code, "QUALIFICATION_PROFILE_REVOKED");
        assert_eq!(
            block.qualification_profile_id.as_ref(),
            Some(&summary.qualification_profile_id)
        );
        assert!(
            block
                .policy_observation_digest
                .unwrap()
                .starts_with("sha256:")
        );
        let response = service.seal("생성", "revoked").unwrap();
        assert!(matches!(
            response.terminal_outcome,
            SealTerminalOutcome::PolicyBlocked(_)
        ));
        let FreshExecutionObservation::WorkBlocked(observed) = response.fresh_observation else {
            panic!("revoked current observation")
        };
        assert_eq!(observed.current_sealability, "POLICY_BLOCKED");
    }

    #[test]
    fn missing_job_is_a_route_refusal_before_any_capture() {
        let root = std::env::current_dir()
            .unwrap()
            .join(".cache")
            .join(format!("seal-service-{}", uuid::Uuid::new_v4()));
        let template_root = root.join("templates");
        let registry = JobRegistry::new(root.join("jobs"), move || template_root.clone()).unwrap();
        let service =
            SealExecutionService::new(&root, &registry, || "2026-11-05T12:00:00".into()).unwrap();
        let mut draft = Job {
            name: "draft".into(),
            template_path: "managed.hwpx".into(),
            ..Job::default()
        };
        registry.save(&mut draft, false).unwrap();
        assert!(service.workspace.read().unwrap().is_none());
        assert!(service.summary("absent").is_err());
        let command = SealExecutionPlanCommand::new("workspace", "draft", "missing").unwrap();
        let policy = resolve_shipping_policy(
            &command,
            &WorkExecutionSummary {
                qualification_profile_id: "hwpx-template-qualification-v4".into(),
                template_application_id: "app".into(),
            },
        );
        assert!(matches!(
            service.capture(
                &command,
                "absent",
                "app",
                "hwpx-template-qualification-v4",
                &policy
            ),
            CaptureExecutionQualificationResult::ContextError(_)
        ));
        assert!(service.current_binding_review("draft").unwrap().is_none());
        assert!(
            service
                .managed_run_context("draft", "hwpx")
                .unwrap()
                .is_none()
        );
        assert!(registry.load("draft").unwrap().authority_id.is_empty());
        assert!(service.workspace.read().unwrap().is_none());
        let error = service.seal("없는 작업", "request").err().unwrap();
        assert_eq!(error.kind, SealAttemptErrorKind::RouteResolution, "{error}");
        assert_eq!(error.detail, "work '없는 작업' 접근 불가");
        let _ = std::fs::remove_dir_all(root);
    }
}
