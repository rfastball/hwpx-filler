//! One managed Job run: freeze the selected world, validate, deliver and adopt evidence.

use super::run_result::{ProjectionInput, project};
use super::*;
use crate::managed_generation_service::{
    ManagedGenerationInput, ManagedGenerationResult, run_managed_generation,
};
use hwpx_filler::execution_contract_set::{execution_basis_digest, plan_semantic_digest};
use hwpx_filler::fresh_execution_observation::FreshExecutionObservation;
use hwpx_filler::generation_delivery::{DeliveryPlanResult, WRITE_OVERWRITE};
use hwpx_filler::job::rules_fingerprints;
use hwpx_filler::job_presentation::filename_source_columns;
use hwpx_filler::output_folder_default::{OutputFolderResolution, resolve_output_folder};
use hwpx_filler::run_delivery_intent::RunDeliveryIntent;
use serde_json::{Value, json};
use std::fs;

struct RunSnapshot {
    seat: SeatedJob,
    data: MountedData,
    output_folder: OutputFolderResolution,
    fresh: Option<FreshExecutionObservation>,
    orchestration: String,
    confirmed_delivery: Option<Arc<hwpx_panel::PreparedDelivery>>,
}

#[derive(Clone, PartialEq, Eq)]
pub(super) struct OverwriteBasis {
    work_ref: String,
    data_key: String,
    snapshot_generation: u64,
    zone_epoch: u64,
    selected_indices: Vec<usize>,
    execution_basis: String,
    filename_pattern: String,
    mapping: hwpx_filler::mapping::MappingProfile,
    output_directory: String,
}

fn refusal(message: impl Into<String>) -> Value {
    json!({"ok":false,"error":message.into(),"level":"warn"})
}

fn overwrite_refusal() -> Value {
    refusal("생성 대상이 바뀌어 덮어쓰기 확인을 다시 받아야 합니다. 문서 만들기를 다시 실행하세요.")
}

fn with_token(mut result: Value, run_token: &str) -> Value {
    result
        .as_object_mut()
        .expect("Job run result object")
        .insert("run_token".into(), Value::String(run_token.into()));
    result
}

fn iso(at: chrono::NaiveDateTime) -> String {
    at.format("%Y-%m-%dT%H:%M:%S").to_string()
}

impl JobController {
    fn overwrite_pin_key(
        &self,
        seat: &SeatedJob,
        data: &MountedData,
        basis: &str,
        output_directory: &str,
    ) -> OverwriteBasis {
        OverwriteBasis {
            work_ref: seat.job.name.clone(),
            data_key: data.data_key.clone(),
            snapshot_generation: data.snapshot_generation,
            zone_epoch: data.zone_epoch,
            selected_indices: data.selected_indices(),
            execution_basis: basis.into(),
            filename_pattern: seat.job.filename_pattern.clone(),
            mapping: seat.job.mapping.clone(),
            output_directory: output_directory.into(),
        }
    }

    /// Run token belongs to this invocation, including all refusal and overwrite branches.
    pub fn generate(
        &self,
        confirm_overwrite: bool,
        run_token: &str,
    ) -> Result<Value, JobControllerError> {
        // Admit and freeze inputs under the session gate. Native delivery runs after release;
        // the generation gate then refuses state-changing transitions and permits cancellation.
        let session = self.session()?;
        let token = run_token.to_owned();
        let observed = {
            let state = self.state()?;
            let Some(seat) = state.seated.clone() else {
                return Ok(with_token(refusal("먼저 작업을 선택하세요."), &token));
            };
            if state.data.range_draft.is_some() {
                return Ok(with_token(
                    refusal("범위 편집기가 열려 있습니다. 변경을 적용하거나 취소한 뒤 생성하세요."),
                    &token,
                ));
            }
            (
                seat,
                state.data.clone(),
                state.remembered_output_directory.clone(),
                state.fresh_observation.clone(),
                state.orchestration.clone(),
            )
        };
        let Some(lease) = self.generation.begin().map_err(error)? else {
            return Ok(with_token(
                refusal("이미 문서를 생성하고 있습니다."),
                &token,
            ));
        };
        let (seat, data, remembered, fresh, orchestration) = observed;
        let basis = fresh
            .as_ref()
            .and_then(|fresh| match fresh {
                FreshExecutionObservation::Sealed(sealed) => {
                    execution_basis_digest(&sealed.sealed_plan_value.execution_basis).ok()
                }
                _ => None,
            })
            .unwrap_or_default();
        let output_folder = resolve_output_folder(
            &remembered,
            !remembered.is_empty() && Path::new(&remembered).is_dir(),
            &seat.job.template_path,
        );
        let key = self.overwrite_pin_key(&seat, &data, &basis, &output_folder.directory);
        let confirmed_delivery = {
            let mut state = self.state()?;
            let previous = state.overwrite_pin.take();
            if confirm_overwrite {
                match previous {
                    Some((prior_key, delivery)) if prior_key == key => Some(delivery),
                    _ => {
                        drop(lease);
                        return Ok(with_token(overwrite_refusal(), &token));
                    }
                }
            } else {
                None
            }
        };
        let snapshot = RunSnapshot {
            seat,
            data,
            output_folder,
            fresh,
            orchestration,
            confirmed_delivery,
        };
        drop(session);
        let outcome = self.generate_with_lease(&snapshot, confirm_overwrite, &key, &token);
        let _session = self.session()?;
        lease.finish();
        let result = outcome?;
        if result.get("ok").and_then(Value::as_bool) == Some(true) {
            self.push_snapshot()?;
        }
        Ok(with_token(result, &token))
    }

    /// Pre-generation staleness/readiness guard chain: media/authority admission, the
    /// panel's create-action gate, then the sealed-plan freshness checks (present,
    /// current orchestration, matching overwrite basis). Each guard is an independent
    /// refusal reason, checked in the same order as before; failure or unknown
    /// staleness must never fall through to generation; only after every guard passes
    /// does this hand off to `generate_after_guard`.
    fn generate_with_lease(
        &self,
        snapshot: &RunSnapshot,
        confirm_overwrite: bool,
        overwrite_key: &OverwriteBasis,
        run_token: &str,
    ) -> Result<Value, JobControllerError> {
        let job = &snapshot.seat.job;
        if job.media() != "hwpx" {
            return Ok(refusal("현재 환경에서는 문서를 만들 수 없습니다"));
        }
        if job.authority_id.is_empty() {
            return Ok(refusal(
                "이 템플릿을 문서 작업으로 초기화할 수 없어 생성할 수 없습니다. 템플릿 파일을 확인하세요.",
            ));
        }
        let panel = self.refresh_panel()?;
        let action = &panel["workbench_observation"]["create_action"];
        if action.get("enabled").and_then(Value::as_bool) != Some(true) {
            return Ok(refusal(
                action
                    .get("disabled_reason")
                    .and_then(Value::as_str)
                    .filter(|message| !message.is_empty())
                    .unwrap_or("필요한 준비를 먼저 완료해 주세요"),
            ));
        }
        self.state()?.last_run_job = job.name.clone();
        let Some(FreshExecutionObservation::Sealed(sealed)) = snapshot.fresh.as_ref() else {
            return Ok(refusal(
                "실행 준비가 현재 확인 상태와 달라 생성하지 않았습니다. 변경사항을 다시 확인해 주세요.",
            ));
        };
        if snapshot.orchestration != hwpx_filler::workbench_execution_status::CURRENT {
            return Ok(refusal(
                "실행 준비가 현재 확인 상태와 달라 생성하지 않았습니다. 변경사항을 다시 확인해 주세요.",
            ));
        }
        let plan = &sealed.sealed_plan_value;
        let current_basis = execution_basis_digest(&plan.execution_basis).map_err(error)?;
        if &self.overwrite_pin_key(
            &snapshot.seat,
            &snapshot.data,
            &current_basis,
            &snapshot.output_folder.directory,
        ) != overwrite_key
        {
            return Ok(refusal(
                "실행 준비가 현재 확인 상태와 달라 생성하지 않았습니다. 변경사항을 다시 확인해 주세요.",
            ));
        }
        self.generate_after_guard(
            snapshot,
            confirm_overwrite,
            overwrite_key,
            run_token,
            sealed,
        )
    }

    /// Continues `generate_with_lease` once every pre-generation guard has passed:
    /// records/binding readiness, then the actual delivery resolution and managed run.
    fn generate_after_guard(
        &self,
        snapshot: &RunSnapshot,
        confirm_overwrite: bool,
        overwrite_key: &OverwriteBasis,
        run_token: &str,
        sealed: &hwpx_filler::fresh_execution_observation::CurrentSealedPlanObservation,
    ) -> Result<Value, JobControllerError> {
        let job = &snapshot.seat.job;
        let plan = &sealed.sealed_plan_value;
        let now = snapshot
            .confirmed_delivery
            .as_ref()
            .map_or_else(|| (self.clock)(), |delivery| delivery.captured_at);
        let indices = snapshot.data.selected_indices();
        let records = self
            .prepared_records(&job.name, &snapshot.data, plan, now)
            .map_err(error)?;
        let prepared = &records.value;
        if !prepared.issues.is_empty() {
            return Ok(refusal(
                "이 레코드의 검증이 닫히지 않았습니다. 먼저 데이터 문제를 확인하세요.",
            ));
        }
        let Some(binding) = sealed.current_field_binding.as_ref() else {
            return Ok(refusal(
                "현재 파일 이름에 사용할 항목 연결을 복원할 수 없습니다.",
            ));
        };
        let folder = &snapshot.output_folder;
        let intent = RunDeliveryIntent::new(&folder.directory).map_err(error)?;
        let delivery = self.prepared_delivery(
            records.clone(),
            binding,
            &job.filename_pattern,
            &intent,
            folder.source != "remembered",
            now,
        )?;
        if snapshot
            .confirmed_delivery
            .as_ref()
            .is_some_and(|confirmed| !Arc::ptr_eq(confirmed, &delivery))
        {
            return Ok(overwrite_refusal());
        }
        let now = delivery.captured_at;
        let timestamp = iso(now);
        let resolved = match delivery.result.clone() {
            DeliveryPlanResult::Ready(value) => value,
            DeliveryPlanResult::Blocked(items) => {
                return Ok(refusal(items.first().map_or(
                    "필요한 준비를 먼저 완료해 주세요",
                    |item| item.detail.as_str(),
                )));
            }
            DeliveryPlanResult::ContextError(item) => return Ok(refusal(item.detail)),
        };
        let conflicts = resolved
            .ordered_items
            .iter()
            .filter(|item| item.collision_disposition == WRITE_OVERWRITE)
            .map(|item| {
                Path::new(&item.resolved_output_relative_path)
                    .file_name()
                    .map_or(item.resolved_output_relative_path.clone(), |leaf| {
                        leaf.to_string_lossy().into_owned()
                    })
            })
            .collect::<Vec<_>>();
        if !conflicts.is_empty() && !confirm_overwrite {
            self.state()?.overwrite_pin = Some((overwrite_key.clone(), delivery.clone()));
            let total = indices.len();
            return Ok(json!({"ok":false,"needs_overwrite":true,"total":total,
                "overwrite_count":conflicts.len(),"new_count":total.saturating_sub(conflicts.len()),
                "conflict_names":conflicts.iter().take(10).collect::<Vec<_>>(),
                "conflict_more":conflicts.len().saturating_sub(10)}));
        }
        if fs::create_dir_all(&folder.directory).is_err() {
            return Ok(refusal(
                "저장 폴더를 만들 수 없습니다. 다른 폴더를 선택하세요.",
            ));
        }
        let service = self.seal_service()?;
        let context = service
            .managed_run_context(&job.name, "hwpx")
            .map_err(error)?
            .ok_or_else(|| error("현재 환경에서는 문서를 만들 수 없습니다"))?;
        (self.progress_sink)(
            json!({"progress":{"done":0,"total":indices.len(),"run_token":run_token}}),
        );
        let outcome = run_managed_generation(
            ManagedGenerationInput {
                authority_root: self.change.authority_root(),
                context: &context,
                plan,
                snapshots: &prepared.raw_records,
                resolved: &resolved,
                validated_at: &timestamp,
            },
            || self.generation.is_cancel_requested(),
            |done, total| {
                (self.progress_sink)(
                    json!({"progress":{"done":done,"total":total,"run_token":run_token}}),
                );
            },
        )
        .map_err(error)?;
        self.finish_run(snapshot, &delivery, &resolved, &context, outcome)
    }

    fn finish_run(
        &self,
        snapshot: &RunSnapshot,
        delivery: &hwpx_panel::PreparedDelivery,
        resolved: &hwpx_filler::generation_delivery::CurrentResolvedDelivery,
        context: &crate::seal_execution_service::ManagedRunContext,
        outcome: ManagedGenerationResult,
    ) -> Result<Value, JobControllerError> {
        let job = &snapshot.seat.job;
        let plan = &delivery.records.plan;
        let prepared = &delivery.records.value;
        let indices = snapshot.data.selected_indices();
        let timestamp = iso(delivery.captured_at);
        let current_basis = execution_basis_digest(&plan.execution_basis).map_err(error)?;
        let revisions = json!({"template":job.template_revision,"binding":job.binding_revision});
        let mut record_note = String::new();
        let stamped = if matches!(outcome, ManagedGenerationResult::Completed { .. }) {
            let rules = rules_fingerprints(job);
            match self
                .registry
                .stamp_last_run(&job.name, &iso((self.clock)()), Some(&rules))
            {
                Ok(stamped) => Some(stamped),
                Err(failure) => {
                    record_note =
                        format!(" 문서는 만들어졌지만 실행 기록 저장에 실패했습니다({failure}).");
                    None
                }
            }
        } else {
            None
        };
        let ledger_note = if matches!(
            outcome,
            ManagedGenerationResult::Completed { .. }
                | ManagedGenerationResult::Aborted { .. }
                | ManagedGenerationResult::ReadBackFailed { .. }
        ) {
            let digest = plan_semantic_digest(plan).map_err(error)?;
            match super::ledger::write_delivery_ledger(
                Path::new(&resolved.output_directory),
                &timestamp,
                &context.work_authority_id,
                &current_basis,
                &digest,
                &outcome,
            ) {
                Ok(_) => String::new(),
                Err(failure) => {
                    format!(" 문서는 만들어졌지만 실행 기록 저장에 실패했습니다({failure}).")
                }
            }
        } else {
            String::new()
        };
        let note = if ledger_note.is_empty() {
            &record_note
        } else {
            &ledger_note
        };
        let names = resolved
            .ordered_items
            .iter()
            .map(|item| item.resolved_output_relative_path.clone())
            .collect::<Vec<_>>();
        let marked = prepared
            .marked_counts
            .iter()
            .map(|(field, _)| field.clone())
            .collect::<Vec<_>>();
        let sources = filename_source_columns(job, &snapshot.data.fields);
        let projection = project(ProjectionInput {
            outcome: &outcome,
            output_directory: &resolved.output_directory,
            resolved_names: &names,
            indices: &indices,
            records: &snapshot.data.records,
            filename_sources: &sources,
            marked_fields: &marked,
            revisions,
            ledger_note: note,
        });
        let mut state = self.state()?;
        Ok(adopt_run_projection(
            &mut state, projection, stamped, timestamp,
        ))
    }
}

fn adopt_run_projection(
    state: &mut JobState,
    projection: super::run_result::RunProjection,
    stamped: Option<Job>,
    timestamp: String,
) -> Value {
    // A delivery attempt changes the directory observation, even after partial failure.
    state.prepared_delivery = None;
    if let Some(delivered) = projection.delivered {
        state.delivered = delivered;
        state.artifact_view =
            json!({"open":false,"ordinal":-1,"filename":"","status":"","detail":""});
    }
    if let Some(indices) = projection.generated_indices {
        state.last_generated = indices;
    }
    if let Some(indices) = projection.failed_indices {
        state.last_failed = indices;
    }
    if projection.completed {
        state.historical_outcome = Some(
            hwpx_filler::document_creation_workbench::HistoricalOutcomeSummary {
                outcome_kind: "DOCUMENTS_DELIVERED".into(),
                observed_at: timestamp,
            },
        );
        if let Some(stamped) = stamped
            && state
                .seated
                .as_ref()
                .is_some_and(|current| current.job.name == stamped.name)
        {
            state.seated.as_mut().expect("checked above").job = stamped;
        }
    }
    projection.result
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(super) mod tests {
    use super::*;

    pub(in crate::job_controller) fn assert_run_evidence_survives_failures(
        controller: &JobController,
        sandbox: &Path,
    ) {
        let (snapshot, delivery, documents, history, generated, failed, artifact) = {
            let mut state = controller.state().unwrap();
            state.artifact_view = json!({"open":true,"ordinal":0,"status":"prior"});
            let snapshot = RunSnapshot {
                seat: state.seated.clone().unwrap(),
                data: state.data.clone(),
                output_folder: resolve_output_folder(
                    &state.remembered_output_directory,
                    true,
                    &state.seated.as_ref().unwrap().job.template_path,
                ),
                fresh: state.fresh_observation.clone(),
                orchestration: state.orchestration.clone(),
                confirmed_delivery: None,
            };
            (
                snapshot,
                state.prepared_delivery.clone().unwrap(),
                state.delivered.clone(),
                state.historical_outcome.clone(),
                state.last_generated.clone(),
                state.last_failed.clone(),
                state.artifact_view.clone(),
            )
        };
        let service = controller.seal_service().unwrap();
        let context = service
            .managed_run_context(&snapshot.seat.job.name, "hwpx")
            .unwrap()
            .unwrap();
        let DeliveryPlanResult::Ready(resolved) = &delivery.result else {
            panic!("ready delivery")
        };
        let out = Path::new(&resolved.output_directory);
        let ledgers = || {
            let mut paths = fs::read_dir(out)
                .unwrap()
                .map(|entry| entry.unwrap().path())
                .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
                .collect::<Vec<_>>();
            paths.sort();
            paths
        };
        let prior_ledgers = ledgers();
        assert_eq!(prior_ledgers.len(), 1);
        let prior_bytes = fs::read(&prior_ledgers[0]).unwrap();
        for outcome in [
            ManagedGenerationResult::Refused {
                code: "REFUSED".into(),
                detail: "거절됨".into(),
                failed_item_ordinal: None,
            },
            ManagedGenerationResult::Cancelled {
                attempted: 1,
                total: 2,
            },
        ] {
            let result = controller
                .finish_run(&snapshot, &delivery, resolved, &context, outcome)
                .unwrap();
            assert_eq!(result["level"], "warn");
            let state = controller.state().unwrap();
            assert_eq!(state.delivered, documents);
            assert_eq!(state.artifact_view, artifact);
            assert_eq!(state.last_generated, generated);
            assert_eq!(state.last_failed, failed);
            assert_eq!(state.historical_outcome, history);
            assert_eq!(ledgers(), prior_ledgers);
        }

        let result = controller
            .finish_run(
                &snapshot,
                &delivery,
                resolved,
                &context,
                ManagedGenerationResult::ReadBackFailed {
                    code: "ARTIFACT_DIGEST_MISMATCH".into(),
                    detail: "made document changed".into(),
                    failed_item_ordinal: 1,
                    delivered: documents.clone(),
                },
            )
            .unwrap();
        assert_eq!(result["status"], "partiallyCompleted");
        assert_delivery_rows(&result, &documents);
        assert_eq!(
            result["failures"][0]["index"],
            snapshot.data.selected_indices()[1]
        );
        assert_eq!(controller.state().unwrap().delivered, documents);
        assert_eq!(controller.state().unwrap().artifact_view["open"], false);
        assert_eq!(controller.state().unwrap().historical_outcome, history);
        let appended = ledgers()
            .into_iter()
            .find(|path| !prior_ledgers.contains(path))
            .unwrap();
        let evidence: Value = serde_json::from_slice(&fs::read(&appended).unwrap()).unwrap();
        assert_eq!(evidence["outcome"], "ManagedReadBackFailed");
        assert_eq!(evidence["aborted"]["failed_item_ordinal"], 1);
        assert_eq!(evidence["delivered"].as_array().unwrap().len(), 2);
        assert_eq!(evidence["work_authority_id"], context.work_authority_id);
        assert_eq!(fs::read(&prior_ledgers[0]).unwrap(), prior_bytes);

        let landed = vec![documents[0].clone()];
        let aborted = controller
            .finish_run(
                &snapshot,
                &delivery,
                resolved,
                &context,
                ManagedGenerationResult::Aborted {
                    code: "WRITE_FAILED".into(),
                    detail: "second document failed".into(),
                    failed_item_ordinal: 1,
                    delivered: landed.clone(),
                },
            )
            .unwrap();
        assert_delivery_rows(&aborted, &landed);
        assert_eq!(controller.state().unwrap().delivered, landed);
        assert!(controller.delivered_artifact(1).unwrap().is_none());

        // A real filesystem failure at the ledger boundary must preserve delivered evidence.
        let denied = sandbox.join("ledger-parent-is-a-file");
        fs::write(&denied, b"not a directory").unwrap();
        let mut invalid_destination = resolved.clone();
        invalid_destination.output_directory = denied.to_string_lossy().into_owned();
        let completed = || ManagedGenerationResult::Completed {
            output_directory: out.into(),
            delivered: documents.clone(),
        };
        let result = controller
            .finish_run(
                &snapshot,
                &delivery,
                &invalid_destination,
                &context,
                completed(),
            )
            .unwrap();
        assert_eq!(result["status"], "completed");
        assert_delivery_rows(&result, &documents);
        assert_eq!(result["succeeded"], 2);
        assert_eq!(result["level"], "danger");
        assert!(
            result["summary"]
                .as_str()
                .unwrap()
                .contains("실행 기록 저장에 실패했습니다(")
        );
        assert_eq!(fs::read(&denied).unwrap(), b"not a directory");
        {
            let state = controller.state().unwrap();
            assert_eq!(state.delivered, documents);
            assert_eq!(state.last_generated, snapshot.data.selected_indices());
            assert!(state.last_failed.is_empty());
            assert_eq!(state.artifact_view["open"], false);
            assert_eq!(
                state.historical_outcome.as_ref().unwrap().outcome_kind,
                "DOCUMENTS_DELIVERED"
            );
        }
        for document in &documents {
            assert!(document.absolute_path.is_file());
        }
        fs::remove_file(denied).unwrap();
        controller.refresh_panel().unwrap();
    }

    fn assert_delivery_rows(
        result: &Value,
        documents: &[crate::managed_generation_service::DeliveredDocument],
    ) {
        assert_eq!(
            result["delivered"].as_array().unwrap(),
            &documents
                .iter()
                .map(|doc| json!({
                    "ordinal":doc.item_ordinal, "filename":doc.relative_path,
                    "disposition":doc.collision_disposition, "path":doc.absolute_path,
                }))
                .collect::<Vec<_>>()
        );
    }
}
