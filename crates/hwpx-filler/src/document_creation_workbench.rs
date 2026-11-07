//! Compose already judged Work, content, execution, record, and delivery facts.
//! No filesystem access, record validation, or new durable readiness authority lives here.

use crate::field_binding_input::{BROKEN, NEW_ACTIVE_FIELD};
use crate::fresh_execution_observation::{
    ADMISSION_CONTEXT_ERROR, CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME,
    EXECUTION_BASE_NOT_ADMITTED, EXECUTION_EVIDENCE_NOT_OBSERVED,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED, NOT_ADMITTED, PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME,
    RuntimePolicyAdmission, decide_materialization_readiness,
};
use crate::run_delivery_intent::RunDeliveryIntent;
use crate::workbench_execution_status::{CHECKING, CURRENT, STALE};
use serde::Serialize;

pub const BLOCKER_CODES: [&str; 16] = [
    "SELECT_DATA",
    "SELECT_RECORDS",
    "SELECT_WORK",
    "CONNECT_DATA",
    "REVIEW_TEMPLATE_CHANGE",
    "REPAIR_TEMPLATE",
    "CHOOSE_CONTENT",
    "REVIEW_BINDING",
    "REVIEW_RECORD_DATA",
    "REVIEW_DELIVERY",
    "EXECUTION_NO_EVIDENCE",
    "EXECUTION_CHECKING",
    "EXECUTION_STALE",
    "POLICY_BLOCKED",
    "RUNTIME_NOT_ADMITTED",
    "CONTEXT_ERROR",
];
pub const PRIMARY_ACTION_CODES: [&str; 14] = [
    "RECOVER_CONTEXT",
    "SELECT_DATA",
    "SELECT_RECORDS",
    "SELECT_WORK",
    "CONNECT_DATA",
    "REVIEW_TEMPLATE_CHANGE",
    "REPAIR_TEMPLATE",
    "CHOOSE_CONTENT",
    "REVIEW_BINDING",
    "RESOLVE_EXECUTION",
    "REVIEW_RECORD_DATA",
    "REVIEW_DELIVERY",
    "RESOLVE_RUNTIME_POLICY",
    "CREATE_DOCUMENTS",
];
const ACTION_CHAIN: [(&str, &str); 16] = [
    ("CONTEXT_ERROR", "RECOVER_CONTEXT"),
    ("SELECT_DATA", "SELECT_DATA"),
    ("SELECT_RECORDS", "SELECT_RECORDS"),
    ("SELECT_WORK", "SELECT_WORK"),
    ("CONNECT_DATA", "CONNECT_DATA"),
    ("REVIEW_TEMPLATE_CHANGE", "REVIEW_TEMPLATE_CHANGE"),
    ("REPAIR_TEMPLATE", "REPAIR_TEMPLATE"),
    ("CHOOSE_CONTENT", "CHOOSE_CONTENT"),
    ("REVIEW_BINDING", "REVIEW_BINDING"),
    ("EXECUTION_NO_EVIDENCE", "RESOLVE_EXECUTION"),
    ("EXECUTION_CHECKING", "RESOLVE_EXECUTION"),
    ("EXECUTION_STALE", "RESOLVE_EXECUTION"),
    ("REVIEW_RECORD_DATA", "REVIEW_RECORD_DATA"),
    ("REVIEW_DELIVERY", "REVIEW_DELIVERY"),
    ("POLICY_BLOCKED", "RESOLVE_RUNTIME_POLICY"),
    ("RUNTIME_NOT_ADMITTED", "RESOLVE_RUNTIME_POLICY"),
];
const ROUTES: [&str; 16] = [
    "job.data",
    "job.records",
    "library.work",
    "editor.data",
    "workbench.template_change",
    "editor.template",
    "workbench.content",
    "workbench.binding",
    "workbench.record_data",
    "workbench.delivery",
    "workbench.execution",
    "workbench.execution",
    "workbench.execution",
    "workbench.runtime_policy",
    "workbench.runtime_policy",
    "workbench.context_recovery",
];
const CHECKING_PHRASE: &str = "설정을 확인하고 있습니다";
const RUNTIME_DISABLED: &str = "현재 환경에서는 문서를 만들 수 없습니다";
const POLICY_DISABLED: &str = "정책상 지금은 문서를 만들 수 없습니다";
const PREPARATION_DISABLED: &str = "필요한 준비를 먼저 완료해 주세요";
const REPAIR_TEMPLATE_PHRASE: &str = "템플릿에 선택할 내용이 없습니다. 템플릿을 확인하세요.";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DataScopeSummary {
    pub mounted: bool,
    pub record_scope_required: bool,
    pub selected_record_count: usize,
    pub total_record_count: usize,
}
impl Default for DataScopeSummary {
    fn default() -> Self {
        Self {
            mounted: false,
            record_scope_required: true,
            selected_record_count: 0,
            total_record_count: 0,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContentSelectionSummary {
    pub selected_option_ids: Vec<String>,
    pub has_unselected_required_content: bool,
    pub requires_template_repair: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveWorkContext {
    pub active: bool,
    pub work_ref: Option<String>,
    pub template_application_ref: Option<String>,
    pub exact_context_restorable: bool,
    pub bound_to_current_data: bool,
    pub data_bound: bool,
    pub unique_candidate_available: bool,
    pub is_favorite: bool,
    pub recently_used: bool,
    pub preferred_work_id: Option<String>,
}
impl Default for ActiveWorkContext {
    fn default() -> Self {
        Self {
            active: false,
            work_ref: None,
            template_application_ref: None,
            exact_context_restorable: false,
            bound_to_current_data: false,
            data_bound: true,
            unique_candidate_available: false,
            is_favorite: false,
            recently_used: false,
            preferred_work_id: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveWorkTransitionDecision {
    pub disposition: &'static str,
    pub auto_activated_work_ref: Option<String>,
}

pub fn decide_active_work_after_data_transition(
    ctx: &ActiveWorkContext,
) -> ActiveWorkTransitionDecision {
    ActiveWorkTransitionDecision {
        disposition: if ctx.active && ctx.exact_context_restorable && ctx.bound_to_current_data {
            "KEEP"
        } else {
            "RELEASE"
        },
        auto_activated_work_ref: None,
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct InputRequirement {
    pub field_id: String,
    pub display_label: String,
    pub binding_state: String,
    pub exact_target: String,
}
impl InputRequirement {
    pub fn action_required(&self) -> bool {
        matches!(self.binding_state.as_str(), BROKEN | NEW_ACTIVE_FIELD)
    }
    fn validate(&self) -> Result<(), String> {
        if self.field_id.is_empty() || self.display_label.is_empty() {
            return Err("field_id/display_label must be non-empty".into());
        }
        if !matches!(
            self.binding_state.as_str(),
            "PRESERVED" | BROKEN | NEW_ACTIVE_FIELD | "INACTIVE_ONLY"
        ) {
            return Err(format!("unknown binding_state: {}", self.binding_state));
        }
        if self.exact_target != format!("binding/{}", self.field_id) {
            return Err("exact_target must identify the exact Binding field".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RecordRecoveryTarget {
    pub snapshot_generation: usize,
    pub record_identity: String,
    pub model_index: usize,
    pub field_id: String,
    pub target_kind: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RecordValidationIssue {
    pub record_identity: String,
    pub record_display_locator: String,
    pub field_id: String,
    pub field_display_label: String,
    pub message: String,
    pub recovery_target: RecordRecoveryTarget,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct RecordValidationAdvisory {
    pub code: String,
    pub field_id: String,
    pub marked_record_count: usize,
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RecordValidationSummary {
    pub has_blocking_issues: bool,
    pub issue_count: usize,
    pub validated_count: usize,
    pub blocked_count: usize,
    pub issues: Vec<RecordValidationIssue>,
    pub advisories: Vec<RecordValidationAdvisory>,
}
impl RecordValidationSummary {
    pub fn marked_value_count(&self) -> usize {
        self.advisories
            .iter()
            .map(|item| item.marked_record_count)
            .sum()
    }
    /// Issue/blocked/advisory counts are mutually consistent and never hollow.
    fn validate_count_consistency(&self) -> Result<(), String> {
        if !self.issues.is_empty() && self.issues.len() != self.issue_count {
            return Err("record validation issue count mismatch".into());
        }
        if !self.issues.is_empty() && (!self.has_blocking_issues || self.blocked_count == 0) {
            return Err("record validation issues require blocked records".into());
        }
        if self.has_blocking_issues && self.issue_count == 0 {
            return Err(
                "has_blocking_issues 면 issue_count 가 1 이상이어야 한다(hollow 금지)".into(),
            );
        }
        if !self.advisories.is_empty() && self.validated_count == 0 {
            return Err("advisory 는 통과한 record 에서만 선다(표식은 유효 값이다)".into());
        }
        Ok(())
    }
    fn issue_is_invalid(item: &RecordValidationIssue) -> bool {
        item.record_identity.is_empty()
            || item.record_display_locator.is_empty()
            || item.field_id.is_empty()
            || item.field_display_label.is_empty()
            || item.message.is_empty()
            || item.recovery_target.record_identity != item.record_identity
            || item.recovery_target.field_id.is_empty()
            || !matches!(item.recovery_target.target_kind.as_str(), "cell" | "row")
    }
    fn validate_issues(&self) -> Result<(), String> {
        for item in &self.issues {
            if Self::issue_is_invalid(item) {
                return Err("invalid record validation issue".into());
            }
        }
        Ok(())
    }
    fn validate_advisories(&self) -> Result<(), String> {
        if self.advisories.iter().any(|item| {
            item.code.is_empty() || item.field_id.is_empty() || item.marked_record_count == 0
        }) {
            return Err("advisory 는 근거 문서 수가 1 이상이어야 한다(hollow 금지)".into());
        }
        Ok(())
    }
    fn validate(&self) -> Result<(), String> {
        self.validate_count_consistency()?;
        self.validate_issues()?;
        self.validate_advisories()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PlannedDocumentSummary {
    pub record_identity: String,
    pub item_ordinal: usize,
    pub relative_path: String,
    pub collision_disposition: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct DeliveryPreviewBlocker {
    pub code: String,
    pub message: String,
    pub item_ordinal: Option<usize>,
    pub field_id: Option<String>,
    pub conflicting_relative_path: Option<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeliveryPreviewSummary {
    pub resolvable: bool,
    pub planned_output_names: Vec<String>,
    pub planned_documents: Vec<PlannedDocumentSummary>,
    pub blockers: Vec<DeliveryPreviewBlocker>,
}
impl DeliveryPreviewSummary {
    fn validate(&self) -> Result<(), String> {
        if self.resolvable && !self.blockers.is_empty() {
            return Err("resolvable delivery cannot have blockers".into());
        }
        if !self.planned_documents.is_empty()
            && self.planned_output_names
                != self
                    .planned_documents
                    .iter()
                    .map(|item| item.relative_path.clone())
                    .collect::<Vec<_>>()
        {
            return Err("planned delivery names and documents must match".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkbenchContextIntegrity {
    pub restore_failure: bool,
    pub code: String,
    pub detail: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct HistoricalOutcomeSummary {
    pub outcome_kind: String,
    pub observed_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct DeepLinkTarget {
    pub blocker_code: String,
    pub route: String,
}

#[derive(Clone, Debug)]
pub struct WorkbenchCompositionInput {
    pub data_scope: DataScopeSummary,
    pub content_selection: ContentSelectionSummary,
    pub active_work: ActiveWorkContext,
    pub admission: RuntimePolicyAdmission,
    pub orchestration: String,
    pub delivery: DeliveryPreviewSummary,
    pub record_validation: RecordValidationSummary,
    pub template_change_verdict: Option<String>,
    pub active_field_requirement_ids: Vec<String>,
    pub binding_review_needed: bool,
    pub input_requirements: Vec<InputRequirement>,
    pub run_delivery_intent: Option<RunDeliveryIntent>,
    pub context_integrity: Option<WorkbenchContextIntegrity>,
    pub historical_outcome: Option<HistoricalOutcomeSummary>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentCreationWorkbenchContextError {
    pub code: String,
    pub detail: String,
}
#[derive(Clone, Debug)]
pub struct DocumentCreationWorkbenchObservation {
    pub input: WorkbenchCompositionInput,
    pub materialization_readiness: &'static str,
    pub blockers: Vec<String>,
    pub primary_action: &'static str,
    pub disabled_reason: Option<&'static str>,
    pub deep_link_targets: Vec<DeepLinkTarget>,
    pub execution_status_phrase: &'static str,
}
impl DocumentCreationWorkbenchObservation {
    pub fn create_documents_enabled(&self) -> bool {
        self.primary_action == "CREATE_DOCUMENTS" && self.disabled_reason.is_none()
    }
    pub fn create_documents_disabled_reason(&self) -> Option<&'static str> {
        if self.create_documents_enabled() {
            return None;
        }
        if self.primary_action == "REPAIR_TEMPLATE" {
            return Some(REPAIR_TEMPLATE_PHRASE);
        }
        if self.input.admission.state == NOT_ADMITTED
            && !has_reason(&self.input.admission, EXECUTION_EVIDENCE_NOT_OBSERVED)
        {
            return Some(if has_runtime_reason(&self.input.admission) {
                RUNTIME_DISABLED
            } else {
                POLICY_DISABLED
            });
        }
        Some(PREPARATION_DISABLED)
    }
    pub fn resolve_execution_disabled_reason(&self) -> Option<&'static str> {
        (self.input.orchestration == CHECKING).then_some(CHECKING_PHRASE)
    }
}
#[derive(Clone, Debug)]
pub enum DocumentCreationWorkbenchResult {
    Observation(Box<DocumentCreationWorkbenchObservation>),
    ContextError(DocumentCreationWorkbenchContextError),
}

fn has_reason(admission: &RuntimePolicyAdmission, reason: &str) -> bool {
    admission.reasons.iter().any(|item| item == reason)
}
fn has_runtime_reason(admission: &RuntimePolicyAdmission) -> bool {
    [
        MATERIALIZATION_CONTRACT_NOT_ADMITTED,
        PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME,
        CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME,
    ]
    .iter()
    .any(|item| has_reason(admission, item))
}
pub fn binding_review_needed(
    blocker_signal: bool,
    input_requirements: &[InputRequirement],
) -> bool {
    blocker_signal
        || input_requirements
            .iter()
            .any(InputRequirement::action_required)
}

pub fn compose_blockers(input: &WorkbenchCompositionInput) -> Vec<String> {
    let mut present = Vec::new();
    if !input.data_scope.mounted {
        present.push("SELECT_DATA");
    } else if input.data_scope.record_scope_required && input.data_scope.selected_record_count == 0
    {
        present.push("SELECT_RECORDS");
    }
    if !input.active_work.active {
        present.push("SELECT_WORK");
    } else if !input.active_work.data_bound {
        present.push("CONNECT_DATA");
    }
    if matches!(
        input.template_change_verdict.as_deref(),
        Some("REVIEW_REQUIRED" | "DETACHED")
    ) {
        present.push("REVIEW_TEMPLATE_CHANGE");
    }
    if input.content_selection.requires_template_repair {
        present.push("REPAIR_TEMPLATE");
    }
    if input.content_selection.has_unselected_required_content {
        present.push("CHOOSE_CONTENT");
    }
    if binding_review_needed(input.binding_review_needed, &input.input_requirements) {
        present.push("REVIEW_BINDING");
    }
    if input.record_validation.has_blocking_issues {
        present.push("REVIEW_RECORD_DATA");
    }
    if !input.delivery.resolvable {
        present.push("REVIEW_DELIVERY");
    }
    if input.orchestration == CHECKING {
        present.push("EXECUTION_CHECKING");
    }
    if input.orchestration == STALE {
        present.push("EXECUTION_STALE");
    }
    if input.admission.state == NOT_ADMITTED {
        let policy = has_reason(&input.admission, EXECUTION_BASE_NOT_ADMITTED);
        let runtime = has_runtime_reason(&input.admission);
        if policy {
            present.push("POLICY_BLOCKED");
        }
        if runtime {
            present.push("RUNTIME_NOT_ADMITTED");
        }
        if has_reason(&input.admission, EXECUTION_EVIDENCE_NOT_OBSERVED) {
            present.push("EXECUTION_NO_EVIDENCE");
        } else if !policy && !runtime {
            present.push("RUNTIME_NOT_ADMITTED");
        }
    }
    BLOCKER_CODES
        .iter()
        .filter(|code| present.contains(code))
        .map(|code| (*code).to_owned())
        .collect()
}

pub fn compose_primary_action(blockers: &[String]) -> &'static str {
    for (blocker, action) in ACTION_CHAIN {
        if blockers.iter().any(|item| item == blocker) {
            return action;
        }
    }
    "CREATE_DOCUMENTS"
}

pub fn compose_document_creation_workbench(
    input: WorkbenchCompositionInput,
) -> Result<DocumentCreationWorkbenchResult, String> {
    if input.active_work.active
        && input
            .active_work
            .work_ref
            .as_deref()
            .is_none_or(str::is_empty)
    {
        return Err("active Work 는 비어 있지 않은 work_ref 가 필요하다".into());
    }
    input.record_validation.validate()?;
    input.delivery.validate()?;
    for item in &input.input_requirements {
        item.validate()?;
    }
    if let Some(integrity) = &input.context_integrity
        && integrity.restore_failure
    {
        if integrity.code.is_empty() || integrity.detail.is_empty() {
            return Err(
                "restore_failure 면 code·detail 이 필요하다(hollow context error 금지)".into(),
            );
        }
        return Ok(DocumentCreationWorkbenchResult::ContextError(
            DocumentCreationWorkbenchContextError {
                code: integrity.code.clone(),
                detail: integrity.detail.clone(),
            },
        ));
    }
    if input.admission.state == ADMISSION_CONTEXT_ERROR {
        return Ok(DocumentCreationWorkbenchResult::ContextError(
            DocumentCreationWorkbenchContextError {
                code: "EXECUTION_ADMISSION_CONTEXT_ERROR".into(),
                detail: if input.admission.reasons.is_empty() {
                    "실행 승인 판정을 복원할 수 없습니다".into()
                } else {
                    input.admission.reasons.join(", ")
                },
            },
        ));
    }
    let blockers = compose_blockers(&input);
    let primary_action = compose_primary_action(&blockers);
    let disabled_reason = if primary_action == "RESOLVE_RUNTIME_POLICY" {
        Some(if has_runtime_reason(&input.admission) {
            RUNTIME_DISABLED
        } else {
            POLICY_DISABLED
        })
    } else if primary_action == "RESOLVE_EXECUTION" && input.orchestration == CHECKING {
        Some(CHECKING_PHRASE)
    } else {
        None
    };
    let deep_link_targets = blockers
        .iter()
        .map(|code| {
            let index = BLOCKER_CODES
                .iter()
                .position(|item| *item == code)
                .expect("known blocker");
            DeepLinkTarget {
                blocker_code: code.clone(),
                route: ROUTES[index].into(),
            }
        })
        .collect();
    let execution_status_phrase = match input.orchestration.as_str() {
        CHECKING => CHECKING_PHRASE,
        STALE => "설정이 바뀌어 다시 확인해야 합니다",
        CURRENT => "현재 설정이 반영됐습니다",
        _ => "",
    };
    let materialization_readiness = decide_materialization_readiness(&input.admission);
    Ok(DocumentCreationWorkbenchResult::Observation(Box::new(
        DocumentCreationWorkbenchObservation {
            input,
            materialization_readiness,
            blockers,
            primary_action,
            disabled_reason,
            deep_link_targets,
            execution_status_phrase,
        },
    )))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::fresh_execution_observation::{ADMITTED, NOT_ADMITTED};

    fn clear() -> WorkbenchCompositionInput {
        WorkbenchCompositionInput {
            data_scope: DataScopeSummary {
                mounted: true,
                record_scope_required: true,
                selected_record_count: 1,
                total_record_count: 1,
            },
            content_selection: ContentSelectionSummary::default(),
            active_work: ActiveWorkContext {
                active: true,
                work_ref: Some("work".into()),
                data_bound: true,
                ..Default::default()
            },
            admission: RuntimePolicyAdmission {
                state: ADMITTED.into(),
                reasons: vec![],
            },
            orchestration: CURRENT.into(),
            delivery: DeliveryPreviewSummary {
                resolvable: true,
                ..Default::default()
            },
            record_validation: RecordValidationSummary::default(),
            template_change_verdict: None,
            active_field_requirement_ids: vec![],
            binding_review_needed: false,
            input_requirements: vec![],
            run_delivery_intent: None,
            context_integrity: None,
            historical_outcome: None,
        }
    }

    fn observed(input: WorkbenchCompositionInput) -> Box<DocumentCreationWorkbenchObservation> {
        match compose_document_creation_workbench(input).unwrap() {
            DocumentCreationWorkbenchResult::Observation(item) => item,
            DocumentCreationWorkbenchResult::ContextError(error) => panic!("unexpected {error:?}"),
        }
    }

    #[test]
    fn simultaneous_blockers_keep_display_order_and_one_priority_action() {
        assert_eq!(
            BLOCKER_CODES,
            [
                "SELECT_DATA",
                "SELECT_RECORDS",
                "SELECT_WORK",
                "CONNECT_DATA",
                "REVIEW_TEMPLATE_CHANGE",
                "REPAIR_TEMPLATE",
                "CHOOSE_CONTENT",
                "REVIEW_BINDING",
                "REVIEW_RECORD_DATA",
                "REVIEW_DELIVERY",
                "EXECUTION_NO_EVIDENCE",
                "EXECUTION_CHECKING",
                "EXECUTION_STALE",
                "POLICY_BLOCKED",
                "RUNTIME_NOT_ADMITTED",
                "CONTEXT_ERROR",
            ]
        );
        assert_eq!(
            PRIMARY_ACTION_CODES,
            [
                "RECOVER_CONTEXT",
                "SELECT_DATA",
                "SELECT_RECORDS",
                "SELECT_WORK",
                "CONNECT_DATA",
                "REVIEW_TEMPLATE_CHANGE",
                "REPAIR_TEMPLATE",
                "CHOOSE_CONTENT",
                "REVIEW_BINDING",
                "RESOLVE_EXECUTION",
                "REVIEW_RECORD_DATA",
                "REVIEW_DELIVERY",
                "RESOLVE_RUNTIME_POLICY",
                "CREATE_DOCUMENTS",
            ]
        );
        assert!(
            ACTION_CHAIN
                .iter()
                .all(|(_, action)| PRIMARY_ACTION_CODES.contains(action))
        );
        assert!(DataScopeSummary::default().record_scope_required);
        assert!(ActiveWorkContext::default().data_bound);
        let mut input = clear();
        input.data_scope.mounted = false;
        input.active_work.data_bound = false;
        input.content_selection.has_unselected_required_content = true;
        input.record_validation = RecordValidationSummary {
            has_blocking_issues: true,
            issue_count: 1,
            blocked_count: 1,
            ..Default::default()
        };
        input.delivery.resolvable = false;
        input.orchestration = CHECKING.into();
        input.admission = RuntimePolicyAdmission {
            state: NOT_ADMITTED.into(),
            reasons: vec![
                EXECUTION_BASE_NOT_ADMITTED.into(),
                EXECUTION_EVIDENCE_NOT_OBSERVED.into(),
            ],
        };
        let result = observed(input);
        assert_eq!(
            result.blockers,
            [
                "SELECT_DATA",
                "CONNECT_DATA",
                "CHOOSE_CONTENT",
                "REVIEW_RECORD_DATA",
                "REVIEW_DELIVERY",
                "EXECUTION_NO_EVIDENCE",
                "EXECUTION_CHECKING",
                "POLICY_BLOCKED",
            ]
        );
        assert_eq!(result.primary_action, "SELECT_DATA");
        assert_eq!(result.disabled_reason, None);
        assert_eq!(result.deep_link_targets[1].route, "editor.data");
        assert_eq!(
            result.resolve_execution_disabled_reason(),
            Some(CHECKING_PHRASE)
        );
    }

    #[test]
    fn content_and_binding_recovery_follow_current_facts() {
        let mut input = clear();
        input.content_selection.has_unselected_required_content = true;
        let choose = observed(input.clone());
        assert_eq!(choose.primary_action, "CHOOSE_CONTENT");
        assert_eq!(choose.deep_link_targets[0].route, "workbench.content");
        input.content_selection.has_unselected_required_content = false;
        input.content_selection.selected_option_ids = vec!["option-1".into()];
        input.binding_review_needed = true;
        let binding = observed(input.clone());
        assert_eq!(binding.blockers, ["REVIEW_BINDING"]);
        assert_eq!(binding.deep_link_targets[0].route, "workbench.binding");
        input.binding_review_needed = false;
        input.template_change_verdict = Some("AUTO_KEEP".into());
        assert!(observed(input.clone()).create_documents_enabled());
        for verdict in ["REVIEW_REQUIRED", "DETACHED"] {
            input.template_change_verdict = Some(verdict.into());
            assert_eq!(
                observed(input.clone()).primary_action,
                "REVIEW_TEMPLATE_CHANGE"
            );
        }
        input.template_change_verdict = None;
        input.content_selection.requires_template_repair = true;
        let repair = observed(input);
        assert_eq!(repair.blockers, ["REPAIR_TEMPLATE"]);
        assert_eq!(
            repair.create_documents_disabled_reason(),
            Some(REPAIR_TEMPLATE_PHRASE)
        );
    }

    #[test]
    fn unknown_evidence_is_recoverable_but_runtime_refusal_and_context_are_distinct() {
        let mut input = clear();
        input.admission = RuntimePolicyAdmission {
            state: NOT_ADMITTED.into(),
            reasons: vec![EXECUTION_EVIDENCE_NOT_OBSERVED.into()],
        };
        let absent = observed(input.clone());
        assert_eq!(absent.primary_action, "RESOLVE_EXECUTION");
        assert_eq!(absent.blockers, ["EXECUTION_NO_EVIDENCE"]);
        assert_eq!(absent.resolve_execution_disabled_reason(), None);
        assert_eq!(
            absent.create_documents_disabled_reason(),
            Some(PREPARATION_DISABLED)
        );
        for (reason, blocker, phrase) in [
            (
                PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME,
                "RUNTIME_NOT_ADMITTED",
                RUNTIME_DISABLED,
            ),
            (
                MATERIALIZATION_CONTRACT_NOT_ADMITTED,
                "RUNTIME_NOT_ADMITTED",
                RUNTIME_DISABLED,
            ),
            (
                EXECUTION_BASE_NOT_ADMITTED,
                "POLICY_BLOCKED",
                POLICY_DISABLED,
            ),
        ] {
            input.admission.reasons = vec![reason.into()];
            let refused = observed(input.clone());
            assert_eq!(refused.blockers, [blocker]);
            assert_eq!(refused.primary_action, "RESOLVE_RUNTIME_POLICY");
            assert_eq!(refused.disabled_reason, Some(phrase));
            assert_eq!(refused.create_documents_disabled_reason(), Some(phrase));
        }
        input.context_integrity = Some(WorkbenchContextIntegrity {
            restore_failure: true,
            code: "BROKEN".into(),
            detail: "corrupt".into(),
        });
        assert!(matches!(compose_document_creation_workbench(input),
            Ok(DocumentCreationWorkbenchResult::ContextError(DocumentCreationWorkbenchContextError { code, .. })) if code == "BROKEN"));
    }
}
