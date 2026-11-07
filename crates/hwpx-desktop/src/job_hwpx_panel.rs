//! HWPX Job panel from a captured session and fresh backend authorities.

use super::*;
use crate::current_execution_preparation::{
    CurrentRecordPreparation, capture_selected_records, delivery_blocker_phrase,
    prepare_current_delivery, prepare_current_records,
};
use crate::workbench_observation_product::{WorkbenchFacts, WorkbenchObservationProduct};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::document_creation_workbench::{
    DeliveryPreviewBlocker, DeliveryPreviewSummary, PlannedDocumentSummary, RecordRecoveryTarget,
    RecordValidationAdvisory, RecordValidationIssue, RecordValidationSummary,
    WorkbenchContextIntegrity,
};
use hwpx_filler::fresh_execution_observation::FreshExecutionObservation;
use hwpx_filler::generation::blank_marker;
use hwpx_filler::generation_delivery::DeliveryPlanResult;
use hwpx_filler::job_presentation::{filename_source_columns, record_rows};
use hwpx_filler::output_folder_default::OutputFolderResolution;
use hwpx_filler::output_name_audit::audit_output_names;
use hwpx_filler::record_validation::MISSING_VALUE_MARKED;
use hwpx_filler::review_state::{review_notice_text, review_requirement};
use hwpx_filler::run_delivery_intent::RunDeliveryIntent;
use hwpx_filler::run_request::RunRequest;
use hwpx_filler::run_state::{RunRefreshInput, refresh_run};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};

use super::panel::PanelContext;

pub(super) struct PreparedRecords {
    work_ref: String,
    generation: u64,
    indices: Vec<usize>,
    pub(super) plan: hwpx_filler::execution_contract_set::SealedExecutionPlanSemanticPayload,
    pub(super) value: CurrentRecordPreparation,
}
pub(super) struct PreparedDelivery {
    pub(super) records: Arc<PreparedRecords>,
    binding: hwpx_filler::field_binding_input::FieldBindingInput,
    pattern: String,
    intent: RunDeliveryIntent,
    allow_missing: bool,
    pub(super) captured_at: chrono::NaiveDateTime,
    pub(super) result:
        DeliveryPlanResult<hwpx_filler::generation_delivery::CurrentResolvedDelivery>,
}

impl JobController {
    pub(super) fn prepared_records(
        &self,
        work_ref: &str,
        data: &MountedData,
        plan: &hwpx_filler::execution_contract_set::SealedExecutionPlanSemanticPayload,
        at: chrono::NaiveDateTime,
    ) -> Result<Arc<PreparedRecords>, String> {
        let indices = data.selected_indices();
        if let Some(cached) = &self.state().map_err(|e| e.to_string())?.prepared_records
            && cached.work_ref == work_ref
            && cached.generation == data.snapshot_generation
            && cached.indices == indices
            && &cached.plan == plan
        {
            return Ok(cached.clone());
        }
        let raw = capture_selected_records(
            &data.records,
            &indices,
            &data.fields,
            data.snapshot_generation as usize,
            &at.format("%Y-%m-%dT%H:%M:%S").to_string(),
        )?;
        let value = prepare_current_records(
            plan,
            data.snapshot_generation as usize,
            raw,
            &indices,
            &data.fields,
        )
        .map_err(|e| e.detail)?;
        let cached = Arc::new(PreparedRecords {
            work_ref: work_ref.into(),
            generation: data.snapshot_generation,
            indices,
            plan: plan.clone(),
            value,
        });
        let mut state = self.state().map_err(|e| e.to_string())?;
        state.prepared_records = Some(cached.clone());
        state.prepared_delivery = None;
        Ok(cached)
    }

    pub(super) fn prepared_delivery(
        &self,
        records: Arc<PreparedRecords>,
        binding: &hwpx_filler::field_binding_input::FieldBindingInput,
        pattern: &str,
        intent: &RunDeliveryIntent,
        allow_missing: bool,
        at: chrono::NaiveDateTime,
    ) -> Result<Arc<PreparedDelivery>, JobControllerError> {
        if let Some(cached) = &self.state()?.prepared_delivery
            && Arc::ptr_eq(&cached.records, &records)
            && &cached.binding == binding
            && cached.pattern == pattern
            && &cached.intent == intent
            && cached.allow_missing == allow_missing
        {
            return Ok(cached.clone());
        }
        let result = prepare_current_delivery(
            &records.plan,
            &records.value,
            binding,
            pattern,
            intent,
            &at.format("%Y-%m-%dT%H:%M:%S").to_string(),
            allow_missing,
        );
        let cached = Arc::new(PreparedDelivery {
            records,
            binding: binding.clone(),
            pattern: pattern.into(),
            intent: intent.clone(),
            allow_missing,
            captured_at: at,
            result,
        });
        self.state()?.prepared_delivery = Some(cached.clone());
        Ok(cached)
    }
}

pub(super) fn fields_from_template(path: &str) -> Result<Vec<String>, String> {
    let bytes = crate::library_observation::read_template(Path::new(path))
        .map_err(|error| error.to_string())?;
    let package = HwpxPackage::from_bytes(&bytes, PackageLimits::default())
        .map_err(|error| error.to_string())?;
    hwpx_filler::fields::required_fields(&package).map_err(|error| error.to_string())
}

fn record_summary(prepared: &CurrentRecordPreparation) -> RecordValidationSummary {
    RecordValidationSummary {
        has_blocking_issues: !prepared.issues.is_empty(),
        issue_count: prepared.issues.len(),
        validated_count: prepared.validated_records.len(),
        blocked_count: prepared.blocked_count,
        issues: prepared
            .issues
            .iter()
            .map(|issue| RecordValidationIssue {
                record_identity: issue.record_identity.clone(),
                record_display_locator: issue.record_display_locator.clone(),
                field_id: issue.field_id.clone(),
                field_display_label: issue.field_display_label.clone(),
                message: issue.message.clone(),
                recovery_target: RecordRecoveryTarget {
                    snapshot_generation: issue.snapshot_generation,
                    record_identity: issue.record_identity.clone(),
                    model_index: issue.model_index,
                    field_id: issue.recovery_field_id.clone(),
                    target_kind: issue.target_kind.into(),
                },
            })
            .collect(),
        advisories: prepared
            .marked_counts
            .iter()
            .map(|(field, count)| RecordValidationAdvisory {
                code: MISSING_VALUE_MARKED.into(),
                field_id: field.clone(),
                marked_record_count: *count,
            })
            .collect(),
    }
}

fn unresolved_delivery(code: &str, message: &str) -> DeliveryPreviewSummary {
    DeliveryPreviewSummary {
        blockers: vec![DeliveryPreviewBlocker {
            code: code.into(),
            message: message.into(),
            item_ordinal: None,
            field_id: None,
            conflicting_relative_path: None,
        }],
        ..DeliveryPreviewSummary::default()
    }
}

fn delivery_summary(
    result: DeliveryPlanResult<hwpx_filler::generation_delivery::CurrentResolvedDelivery>,
) -> (DeliveryPreviewSummary, Option<WorkbenchContextIntegrity>) {
    match result {
        DeliveryPlanResult::Ready(resolved) => {
            let planned_documents = resolved
                .ordered_items
                .into_iter()
                .map(|item| PlannedDocumentSummary {
                    record_identity: item.record_identity,
                    item_ordinal: item.item_ordinal,
                    relative_path: item.resolved_output_relative_path,
                    collision_disposition: item.collision_disposition,
                })
                .collect::<Vec<_>>();
            let planned_output_names = planned_documents
                .iter()
                .map(|item| item.relative_path.clone())
                .collect();
            (
                DeliveryPreviewSummary {
                    resolvable: true,
                    planned_output_names,
                    planned_documents,
                    blockers: vec![],
                },
                None,
            )
        }
        DeliveryPlanResult::Blocked(items) => (
            DeliveryPreviewSummary {
                blockers: items
                    .into_iter()
                    .map(|item| DeliveryPreviewBlocker {
                        message: delivery_blocker_phrase(&item.code).into(),
                        code: item.code,
                        item_ordinal: item.item_ordinal,
                        field_id: item.field_id,
                        conflicting_relative_path: item.conflicting_relative_path,
                    })
                    .collect(),
                ..DeliveryPreviewSummary::default()
            },
            None,
        ),
        DeliveryPlanResult::ContextError(item) => (
            DeliveryPreviewSummary::default(),
            Some(WorkbenchContextIntegrity {
                restore_failure: true,
                code: item.code,
                detail: item.detail,
            }),
        ),
    }
}

/// Stage 1 of `prepare_hwpx_panel`'s projection pipeline: the blank-field scan, the
/// review requirement and its notice text, and the mapped records that feed
/// `refresh_run` — skipped (empty) when nothing is selected, same as before.
/// `(blanks, review, notice, mapped)`.
type BlanksReviewNoticeMapped = (
    Vec<String>,
    hwpx_filler::review_state::ReviewRequirement,
    String,
    Vec<serde_json::Map<String, Value>>,
);

fn blanks_review_notice_and_mapped(
    job: &Job,
    data: &MountedData,
    indices: &[usize],
    now: chrono::NaiveDateTime,
) -> Result<BlanksReviewNoticeMapped, JobControllerError> {
    let request = RunRequest {
        job,
        records: &data.records,
        selected_indices: indices,
    };
    let blanks = if indices.is_empty() {
        vec![]
    } else {
        request.blank_fields(Some(now)).map_err(error)?
    };
    let review = review_requirement(job, &blanks);
    let notice = review_notice_text(&review);
    let mapped = if indices.is_empty() {
        vec![]
    } else {
        request
            .mapped_records(blank_marker(&blanks), Some(now))
            .map_err(error)?
    };
    Ok((blanks, review, notice, mapped))
}

/// Stage 2: the zone's own mapped records (recomputed only when a range draft
/// narrows the zone to something other than the full selection) and the matching
/// output-name audit (reused from `status.audit` when the zone equals the
/// selection, recomputed otherwise) — same conditions and order as before.
#[allow(clippy::too_many_arguments)]
fn zone_mapped_and_audit(
    job: &Job,
    data: &MountedData,
    now: chrono::NaiveDateTime,
    folder: &OutputFolderResolution,
    zone_indices: &[usize],
    indices: &[usize],
    mapped: Vec<serde_json::Map<String, Value>>,
    status_audit: &hwpx_filler::output_name_audit::OutputNameAudit,
) -> Result<hwpx_filler::output_name_audit::OutputNameAudit, JobControllerError> {
    let zone_mapped = if data.range_draft.is_some() && !zone_indices.is_empty() {
        let zone_request = RunRequest {
            job,
            records: &data.records,
            selected_indices: zone_indices,
        };
        let zone_blanks = zone_request.blank_fields(Some(now)).map_err(error)?;
        zone_request
            .mapped_records(blank_marker(&zone_blanks), Some(now))
            .map_err(error)?
    } else {
        mapped
    };
    let audit = if zone_indices == indices {
        status_audit.clone()
    } else {
        audit_output_names(
            &job.filename_pattern,
            &zone_mapped,
            &folder.directory,
            Some(now),
            None,
        )
    };
    Ok(audit)
}

/// Stage 3: the display-ordered rows (reversed for a `"sourceDesc"` view order),
/// their zone sections, and the manual-selection guard — same checks, same order.
fn rows_zone_and_guard(
    job: &Job,
    data: &MountedData,
    zone_indices: &[usize],
    audit_names: Vec<String>,
    last_generated: &[usize],
) -> Result<
    (
        Vec<Value>,
        crate::job_data_projection::DataZoneProjection,
        Value,
    ),
    JobControllerError,
> {
    let planned = zone_indices
        .iter()
        .copied()
        .zip(audit_names)
        .collect::<HashMap<_, _>>();
    let mut order = (0..data.records.len()).collect::<Vec<_>>();
    let view_order = data
        .range_draft
        .as_ref()
        .map_or(data.view_order.as_str(), |draft| {
            draft.range.view_order.as_str()
        });
    if view_order == "sourceDesc" {
        order.reverse();
    }
    let source_columns = filename_source_columns(job, &data.fields);
    let rows = record_rows(
        &data.records,
        &order,
        zone_indices,
        &planned,
        &source_columns,
    )
    .map_err(error)?;
    let by_index = rows
        .iter()
        .filter_map(|row| {
            row.get("index")?
                .as_u64()
                .map(|index| (index as usize, row.clone()))
        })
        .collect::<HashMap<_, _>>();
    if by_index.len() != data.records.len() {
        return Err(error("행 표시 좌표가 데이터와 일치하지 않습니다."));
    }
    let zone = data
        .zone_sections(zone_indices, |index| by_index[&index].clone())
        .map_err(error)?;
    let settled = last_generated.iter().copied().collect::<HashSet<_>>();
    let guard = data
        .selection_guard(&settled, Some(&zone.filter_visible))
        .map_err(error)?;
    Ok((rows, zone, guard))
}

fn template_missing(path: &str) -> bool {
    path.is_empty() || !Path::new(path).exists()
}

fn conn_label(missing: bool) -> &'static str {
    if missing { "템플릿 없음" } else { "" }
}

/// The preflight line shown under the panel: an affirmative "ready" line (only when
/// the create action is actually enabled) followed by any notices, once the
/// preflight itself reports no issues; otherwise the preflight's own text.
fn preflight_display_text(
    preflight: &hwpx_filler::run_state::PreflightResult,
    create_enabled: bool,
) -> String {
    if preflight.level == "ok" {
        let mut text = if create_enabled {
            vec!["검증 완료. 생성할 수 있습니다.".to_owned()]
        } else {
            vec![]
        };
        text.extend(preflight.notices.clone());
        text.join("\n")
    } else {
        preflight.text.clone()
    }
}

/// What `panel_record_and_delivery`'s first half found, carried into its second half
/// (`panel_delivery_from_prepared`) as one argument to stay under clippy's
/// argument-count limit without changing any value's meaning.
struct RecordPrepStage {
    intent: Option<RunDeliveryIntent>,
    summary: RecordValidationSummary,
    prepared: Option<Arc<PreparedRecords>>,
}

impl JobController {
    fn panel_binding_review(
        &self,
        context: &PanelContext,
        work_ref: &str,
        integrity: &mut Option<WorkbenchContextIntegrity>,
    ) -> Result<Option<crate::seal_execution_service::BindingReviewProjection>, JobControllerError>
    {
        if !matches!(
            context.fresh_observation,
            Some(FreshExecutionObservation::WorkBlocked(_))
        ) {
            return Ok(None);
        }
        binding_review_or_context_error(
            self.seal_service()?.current_binding_review(work_ref),
            integrity,
        )
    }

    /// Guard chain, part 1: resolves the delivery intent and (when orchestration is
    /// current and something is selected) prepares current records. On success hands
    /// off directly to `panel_delivery_from_prepared` for the rest of the chain
    /// (rather than returning what it found, which would pull that function's own
    /// branches back into this one for the complexity count); every refusal returns
    /// the same 4-tuple shape so no extra dispatch is needed either way.
    fn panel_record_and_delivery(
        &self,
        context: &PanelContext,
        job: &Job,
        folder: &OutputFolderResolution,
        now: chrono::NaiveDateTime,
    ) -> (
        RecordValidationSummary,
        DeliveryPreviewSummary,
        Option<WorkbenchContextIntegrity>,
        Option<RunDeliveryIntent>,
    ) {
        let intent = (!folder.directory.is_empty())
            .then(|| RunDeliveryIntent::new(&folder.directory))
            .transpose();
        let intent = match intent {
            Ok(value) => value,
            Err(error) => {
                return (
                    RecordValidationSummary::default(),
                    DeliveryPreviewSummary::default(),
                    Some(WorkbenchContextIntegrity {
                        restore_failure: true,
                        code: "RUN_DELIVERY_INTENT_INVALID".into(),
                        detail: error.to_string(),
                    }),
                    None,
                );
            }
        };
        let selected = context.data.selected_indices();
        let mut summary = RecordValidationSummary::default();
        let mut prepared = None;
        let fresh = context.fresh_observation.as_ref();
        if context.orchestration == hwpx_filler::workbench_execution_status::CURRENT
            && let Some(FreshExecutionObservation::Sealed(sealed)) = fresh
            && !selected.is_empty()
        {
            let result =
                self.prepared_records(&job.name, &context.data, &sealed.sealed_plan_value, now);
            match result {
                Ok(value) => {
                    summary = record_summary(&value.value);
                    prepared = Some(value);
                }
                Err(detail) => {
                    return (
                        summary,
                        DeliveryPreviewSummary::default(),
                        Some(WorkbenchContextIntegrity {
                            restore_failure: true,
                            code: "CURRENT_RECORD_CAPTURE_STALE".into(),
                            detail,
                        }),
                        intent,
                    );
                }
            }
        }
        self.panel_delivery_from_prepared(
            context,
            job,
            folder,
            now,
            RecordPrepStage {
                intent,
                summary,
                prepared,
            },
        )
    }

    /// Guard chain, part 2: continues `panel_record_and_delivery` once records (if
    /// applicable) are prepared — intent presence, blocking issues, record
    /// preparation presence, the sealed plan (re-checked, since the first half only
    /// required it when preparing records), and the field binding — then resolves and
    /// summarizes the delivery. Same checks, same order as before the split.
    fn panel_delivery_from_prepared(
        &self,
        context: &PanelContext,
        job: &Job,
        folder: &OutputFolderResolution,
        now: chrono::NaiveDateTime,
        RecordPrepStage {
            intent,
            summary,
            prepared,
        }: RecordPrepStage,
    ) -> (
        RecordValidationSummary,
        DeliveryPreviewSummary,
        Option<WorkbenchContextIntegrity>,
        Option<RunDeliveryIntent>,
    ) {
        let Some(intent_ref) = intent.as_ref() else {
            return (
                summary,
                unresolved_delivery("OUTPUT_DIRECTORY_REQUIRED", "저장 폴더를 선택하세요."),
                None,
                intent,
            );
        };
        if summary.has_blocking_issues {
            return (
                summary,
                unresolved_delivery(
                    "RECORD_VALIDATION_REQUIRED",
                    "먼저 데이터 문제를 확인하세요.",
                ),
                None,
                intent,
            );
        }
        let Some(prepared) = prepared else {
            return (
                summary,
                unresolved_delivery(
                    "CURRENT_RECORD_PREPARATION_REQUIRED",
                    "생성할 데이터를 먼저 선택하세요.",
                ),
                None,
                intent,
            );
        };
        let Some(FreshExecutionObservation::Sealed(sealed)) = context.fresh_observation.as_ref()
        else {
            return (
                summary,
                unresolved_delivery("CURRENT_EXECUTION_REQUIRED", "현재 설정을 먼저 확인하세요."),
                None,
                intent,
            );
        };
        let Some(binding) = sealed.current_field_binding.as_ref() else {
            return (
                summary,
                DeliveryPreviewSummary::default(),
                Some(WorkbenchContextIntegrity {
                    restore_failure: true,
                    code: "CURRENT_DELIVERY_BINDING_CONTEXT_MISSING".into(),
                    detail: "현재 파일 이름에 사용할 항목 연결을 복원할 수 없습니다.".into(),
                }),
                intent,
            );
        };
        let cached = self.prepared_delivery(
            prepared,
            binding,
            &job.filename_pattern,
            intent_ref,
            folder.source != "remembered",
            now,
        );
        let result = match cached {
            Ok(cached) => cached.result.clone(),
            Err(error) => {
                return (
                    summary,
                    DeliveryPreviewSummary::default(),
                    Some(WorkbenchContextIntegrity {
                        restore_failure: true,
                        code: "CURRENT_DELIVERY_CONTEXT_ERROR".into(),
                        detail: error.to_string(),
                    }),
                    intent,
                );
            }
        };
        let (delivery, failure) = delivery_summary(result);
        (summary, delivery, failure, intent)
    }

    /// Stage 4 of `prepare_hwpx_panel`'s projection pipeline: the workbench
    /// observation, `{"supported":false,"kind":null}` when the template file is
    /// missing, otherwise built from the record/delivery/binding-review facts — same
    /// branch and same fields as before.
    #[allow(clippy::too_many_arguments)]
    fn build_workbench(
        &self,
        context: &PanelContext,
        job: &Job,
        data: &MountedData,
        folder: &OutputFolderResolution,
        now: chrono::NaiveDateTime,
        missing: bool,
        indices: &[usize],
        slot_view: Option<hwpx_filler::slot_reconciliation::SlotConfigurationResolution>,
    ) -> Result<Value, JobControllerError> {
        if missing {
            return Ok(json!({"supported":false,"kind":null}));
        }
        let (record_validation, delivery, mut context_integrity, intent) =
            self.panel_record_and_delivery(context, job, folder, now);
        let binding_review =
            self.panel_binding_review(context, &job.name, &mut context_integrity)?;
        let facts = WorkbenchFacts {
            data_mounted: !data.source_kind.is_empty(),
            selected_record_count: indices.len(),
            total_record_count: data.records.len(),
            active_work_ref: Some(job.name.clone()),
            active_work_data_bound: job.has_data_binding(),
            slot_view,
            orchestration: context.orchestration.clone(),
            fresh_observation: context.fresh_observation.clone(),
            active_field_requirement_ids: binding_review
                .as_ref()
                .map_or_else(Vec::new, |item| item.active_field_ids.clone()),
            input_requirements: binding_review
                .map_or_else(Vec::new, |item| item.input_requirements),
            binding_review_needed: false,
            template_change_verdict: None,
            record_validation: Some(record_validation),
            delivery: Some(delivery),
            run_delivery_intent: intent,
            context_integrity,
            historical_outcome: context.historical_outcome.clone(),
        };
        let mut observation = WorkbenchObservationProduct::observe(facts).map_err(error)?;
        observation
            .as_object_mut()
            .ok_or_else(|| error("작업대 관찰 형식 오류"))?
            .insert("supported".into(), Value::Bool(true));
        Ok(observation)
    }

    pub(super) fn prepare_hwpx_panel(
        &self,
        context: &PanelContext,
        mut base: Value,
        folder: &OutputFolderResolution,
    ) -> Result<Value, JobControllerError> {
        let seat = context
            .seated
            .as_ref()
            .ok_or_else(|| error("문서 작업이 없습니다."))?;
        let job = &seat.job;
        let data = &context.data;
        let missing = template_missing(&job.template_path);
        let now = (self.clock)();
        let indices = data.selected_indices();
        let (blanks, review, notice, mapped) =
            blanks_review_notice_and_mapped(job, data, &indices, now)?;
        let status = refresh_run(RunRefreshInput {
            job,
            records: &data.records,
            selected_indices: &indices,
            data_mounted: !data.source_kind.is_empty(),
            out_dir: &folder.directory,
            now,
            template_fields: fields_from_template(&job.template_path),
            mapped: Some(&mapped),
            review_notice: Some(&notice),
        })
        .map_err(error)?;
        let zone_indices = data.zone_indices();
        let audit = zone_mapped_and_audit(
            job,
            data,
            now,
            folder,
            &zone_indices,
            &indices,
            mapped,
            &status.audit,
        )?;
        let (rows, zone, guard) = rows_zone_and_guard(
            job,
            data,
            &zone_indices,
            audit.names,
            &context.last_generated,
        )?;
        let (change, slot, presets) = self.configuration_zones(job, missing)?;
        let workbench = self.build_workbench(
            context,
            job,
            data,
            folder,
            now,
            missing,
            &indices,
            slot.resolution,
        )?;
        let action = workbench
            .get("create_action")
            .cloned()
            .unwrap_or(Value::Null);
        let create_enabled = action.get("enabled").and_then(Value::as_bool) == Some(true);
        let preflight_text = preflight_display_text(&status.preflight, create_enabled);
        let detail = json!({
            "managed_hwpx":!job.authority_id.is_empty(), "template_name":Path::new(&job.template_path).file_name().map_or("".into(),|name|name.to_string_lossy().into_owned()),
            "template_path":job.template_path,"template_missing":missing,"conn_label":conn_label(missing),
            "filename_pattern":job.filename_pattern,"has_data":!data.source_kind.is_empty(),
            "record_count":data.records.len(),"selected_count":data.selection.selected_count(),
            "records":rows,"filter":zone.filter,"table":zone.table,"guard":guard,
            "preflight":{"level":status.preflight.level,"text":preflight_text},
            "blank_fields":blanks,"drift":status.field_states.iter().filter(|item|item.state=="drift").map(|item|item.name.clone()).collect::<Vec<_>>(),
            "name_tokens":status.unresolved_name_tokens,
            "gate":{"enabled":create_enabled,"level":"","text":action.get("disabled_reason").and_then(Value::as_str).unwrap_or(""),"reason":""},
            "review":review.payload(),"rules_key":review.rules_key,
            "workbench_observation":workbench,
            "template_change":change,"slot_configuration":slot.zone,"content_presets":presets,
        });
        base.as_object_mut()
            .ok_or_else(|| error("작업 화면 형식 오류"))?
            .extend(
                detail
                    .as_object()
                    .ok_or_else(|| error("작업 화면 형식 오류"))?
                    .clone(),
            );
        Ok(base)
    }
}

fn binding_review_or_context_error(
    result: Result<
        Option<crate::seal_execution_service::BindingReviewProjection>,
        hwpx_filler::seal_execution_plan::SealAttemptError,
    >,
    integrity: &mut Option<WorkbenchContextIntegrity>,
) -> Result<Option<crate::seal_execution_service::BindingReviewProjection>, JobControllerError> {
    use hwpx_filler::seal_execution_plan::SealAttemptErrorKind;
    match result {
        Ok(review) => Ok(review),
        Err(failure) if failure.kind == SealAttemptErrorKind::ExecutionQualificationContext => {
            *integrity = Some(WorkbenchContextIntegrity {
                restore_failure: true,
                code: failure
                    .cause_code
                    .unwrap_or_else(|| "EXECUTION_CAPTURE_CONTEXT_ERROR".into()),
                detail: failure.detail,
            });
            Ok(None)
        }
        Err(failure) => Err(error(failure)),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::seal_execution_service::BindingReviewProjection;
    use hwpx_filler::seal_execution_plan::{SealAttemptError, SealAttemptErrorKind};

    #[test]
    fn binding_review_integrity_failures_stay_visible_and_other_errors_propagate() {
        let mut integrity = None;
        let review = BindingReviewProjection {
            active_field_ids: vec!["Name".into()],
            input_requirements: vec![],
        };
        for value in [None, Some(review)] {
            assert_eq!(
                binding_review_or_context_error(Ok(value.clone()), &mut integrity).unwrap(),
                value
            );
            assert!(integrity.is_none());
        }
        for code in [None, Some("EXECUTION_STRUCTURE_INTEGRITY_ERROR")] {
            let failure = SealAttemptError {
                kind: SealAttemptErrorKind::ExecutionQualificationContext,
                detail: "damaged binding projection".into(),
                cause_code: code.map(str::to_owned),
            };
            assert!(
                binding_review_or_context_error(Err(failure), &mut integrity)
                    .unwrap()
                    .is_none()
            );
            let projected = integrity.take().unwrap();
            assert!(projected.restore_failure);
            assert_eq!(
                projected.code,
                code.unwrap_or("EXECUTION_CAPTURE_CONTEXT_ERROR")
            );
            assert_eq!(projected.detail, "damaged binding projection");
        }
        for kind in [
            SealAttemptErrorKind::RouteResolution,
            SealAttemptErrorKind::Authorization,
            SealAttemptErrorKind::UnsupportedLocalImplementation,
        ] {
            let failure = SealAttemptError {
                kind,
                detail: "unexpected failure".into(),
                cause_code: None,
            };
            assert_eq!(
                binding_review_or_context_error(Err(failure), &mut integrity)
                    .unwrap_err()
                    .message,
                "unexpected failure"
            );
            assert!(integrity.is_none());
        }
    }
}
