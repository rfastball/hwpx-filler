//! Immutable Job panel observation; never writes durable authority during rendering.

use super::*;
use crate::dataset_registry::PoolError;
use crate::slot_configuration_product::{SlotConfigurationProduct, SlotRead};
use crate::template_inventory::discover_paths;
use hwpx_filler::dataset_pool::DatasetPoolRow;
use hwpx_filler::dataset_reference::excel_identity;
use hwpx_filler::job_presentation::{
    browse_payload, candidate_payload, record_rows, session_data_row,
};
use hwpx_filler::output_folder_default::resolve_output_folder;
use hwpx_filler::work_candidates::{prework_gate, unsupported_media_gate, workbench_entry_gate};
use std::collections::{HashMap, HashSet};

fn source_label(source: &str, label: &str) -> Result<String, JobControllerError> {
    match source {
        "" => Ok(String::new()),
        "file" => Ok(format!("파일: {label}")),
        "pool" => Ok(format!("등록 데이터: {label}")),
        "pclm" => Ok(format!("계약 목록: {label}")),
        other => Err(error(format!(
            "알 수 없는 데이터 소스 종류: {}",
            hwpx_filler::text_render::python_repr(&Value::String(other.into()))
        ))),
    }
}
fn blank_change() -> Value {
    json!({"supported":false,"reason":"unsupported_media","checkable":false,"actionable":false,"diagnostics":[],"epoch":null,"preparation":null})
}
fn blank_slot() -> Value {
    json!({"supported":false,"initialized":false,"mutation_outcome":null,"current_view":null,"refresh_required":false,"error":null})
}
fn blank_presets() -> Value {
    json!({"supported":false,"items":[],"corrupt":[],"list_actionable":false,"save_actionable":false,"applied_key":null})
}
fn blank_review() -> Value {
    json!({"required":false,"risk":"","targets":[],"first_run":false,"unknown_baseline":false,"structure_changed":false})
}

pub(super) struct PanelContext {
    pub(super) data: MountedData,
    pub(super) seated: Option<SeatedJob>,
    browse_tab: String,
    browse_query: String,
    pub(super) remembered: String,
    artifact_view: Value,
    last_run_job: String,
    pub(super) last_generated: Vec<usize>,
    pub(super) fresh_observation:
        Option<hwpx_filler::fresh_execution_observation::FreshExecutionObservation>,
    pub(super) orchestration: String,
    pub(super) historical_outcome:
        Option<hwpx_filler::document_creation_workbench::HistoricalOutcomeSummary>,
}

impl JobController {
    pub(super) fn configuration_zones(
        &self,
        job: &Job,
        missing: bool,
    ) -> Result<(Value, SlotRead, Value), JobControllerError> {
        let change = self
            .change
            .zone(&job.name, job.media(), missing)
            .map_err(error)?;
        let clock = Arc::clone(&self.clock);
        let product = SlotConfigurationProduct::new(
            self.change.authority_root(),
            Arc::clone(&self.registry),
            move || clock().format("%Y-%m-%dT%H:%M:%S").to_string(),
        );
        let slot = product.zone(&job.name, Some(job), missing).map_err(error)?;
        let savable = slot
            .zone
            .pointer("/current_view/projection/savable_selection")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let presets = product.presets_zone(&job.name, Some(job), missing, savable);
        Ok((change, slot, presets))
    }
    pub fn snapshot(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        Ok(self.state()?.panel_snapshot.clone())
    }
    pub fn refresh_panel(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let context = {
            let mut state = self.state()?;
            if state.orchestration != hwpx_filler::workbench_execution_status::CURRENT {
                state.prepared_records = None;
                state.prepared_delivery = None;
            }
            PanelContext {
                data: state.data.clone(),
                seated: state.seated.clone(),
                browse_tab: state.browse_tab.clone(),
                browse_query: state.browse_query.clone(),
                remembered: state.remembered_output_directory.clone(),
                artifact_view: state.artifact_view.clone(),
                last_run_job: state.last_run_job.clone(),
                last_generated: state.last_generated.clone(),
                fresh_observation: state.fresh_observation.clone(),
                orchestration: state.orchestration.clone(),
                historical_outcome: state.historical_outcome.clone(),
            }
        };
        let projected = self.prepare_panel(&context)?;
        let record_preparation_plan = if context.orchestration
            == hwpx_filler::workbench_execution_status::CURRENT
            && !context.data.selected_indices().is_empty()
            && projected
                .pointer("/workbench_observation/record_validation/issues")
                .and_then(Value::as_array)
                .is_some()
        {
            match context.fresh_observation.as_ref() {
                Some(
                    hwpx_filler::fresh_execution_observation::FreshExecutionObservation::Sealed(
                        sealed,
                    ),
                ) => Some((
                    context
                        .seated
                        .as_ref()
                        .map_or_else(String::new, |seat| seat.job.name.clone()),
                    sealed.sealed_plan_value.clone(),
                )),
                _ => None,
            }
        } else {
            None
        };
        let mut state = self.state()?;
        state.panel_snapshot = projected.clone();
        state.record_preparation_plan = record_preparation_plan;
        Ok(projected)
    }
    fn sheet_tabs(&self, data: &MountedData) -> Result<Value, JobControllerError> {
        if data.pool_key.is_empty() || data.path.is_empty() {
            return Ok(json!([]));
        }
        let item = match self.pool.load(&data.pool_key) {
            Ok(item) => item,
            Err(PoolError::Io(failure)) if failure.kind() == std::io::ErrorKind::NotFound => {
                return Ok(json!([]));
            }
            Err(failure) => {
                return Ok(
                    json!([{"key":data.pool_key,"sheet":data.sheet,"active":true,
                "selectable":false,"reason":format!("⚠ 손상된 등록 데이터: {}.dataset.json — {failure}",data.pool_key),"damaged":true}]),
                );
            }
        };
        let missing = !data.path.is_empty() && !Path::new(&data.path).exists();
        let row = DatasetPoolRow::from_item(&data.pool_key, &item, missing).map_err(error)?;
        if item.kind
            != if data.kind.is_empty() {
                "excel"
            } else {
                &data.kind
            }
            || excel_identity(&row.locate_path, None) != excel_identity(&data.path, None)
        {
            return Ok(json!([]));
        }
        let reason = row.select_block_reason();
        Ok(json!(
            row.sheets
                .iter()
                .filter(|sheet| !sheet.is_empty())
                .map(|sheet| json!({
            "key":data.pool_key,"sheet":sheet,"active":sheet==&data.sheet,
            "selectable":reason.is_empty(),"reason":reason}))
                .collect::<Vec<_>>()
        ))
    }
    fn prepare_panel(&self, context: &PanelContext) -> Result<Value, JobControllerError> {
        let data = &context.data;
        let seated = context.seated.as_ref();
        let browse_tab = context.browse_tab.as_str();
        let browse_query = context.browse_query.as_str();
        let remembered = context.remembered.as_str();
        let artifact_view = &context.artifact_view;
        let last_run_job = context.last_run_job.as_str();
        let last_generated = context.last_generated.as_slice();
        let (jobs, registry_warning) = match self.registry.list_jobs_with_corruption() {
            Ok((jobs, _)) => (jobs, None),
            Err(_) => (
                Vec::new(),
                Some("문서 작업 목록을 다시 확인할 수 없습니다. 잠시 뒤 다시 시도하세요."),
            ),
        };
        let active_name = seated.map_or("", |item| item.job.name.as_str());
        let fields = (!data.records.is_empty()).then_some(data.fields.as_slice());
        let txt_template_count = if registry_warning.is_none()
            && fields.is_some()
            && !jobs.iter().any(|job| job.media() == "txt")
        {
            discover_paths(&self.registry.configured_template_root())
                .map_err(error)?
                .into_iter()
                .filter(|path| {
                    path.extension()
                        .is_some_and(|ext| ext.eq_ignore_ascii_case("txt"))
                })
                .take(1)
                .count()
        } else {
            0
        };
        let bound = jobs
            .iter()
            .filter(|job| {
                data_binding_matches(job, &data.path, &data.sheet, data.header_row, &data.kind)
                    || Self::contract_fit(job, data).is_some_and(|(passed, _)| passed)
            })
            .cloned()
            .collect::<Vec<_>>();
        let missing_by_path = bound
            .iter()
            .map(|job| {
                (
                    job.template_path.clone(),
                    job.template_path.is_empty() || !Path::new(&job.template_path).exists(),
                )
            })
            .collect::<HashMap<_, _>>();
        let candidates = candidate_payload(
            &jobs,
            &bound,
            fields,
            active_name,
            txt_template_count,
            &missing_by_path,
        )
        .map_err(error)?;
        let browse = browse_payload(&bound, fields, browse_tab, browse_query);
        let (_, new_work_blocked) = data.new_work_handoff();
        let template_path = seated.map_or("", |item| item.job.template_path.as_str());
        let is_txt = seated.is_some_and(|item| item.job.media() == "txt");
        let folder = resolve_output_folder(
            remembered,
            !remembered.is_empty() && Path::new(remembered).is_dir(),
            if is_txt { "" } else { template_path },
        );
        let output_folder = json!({"directory":folder.directory,"source":folder.source,"source_label":folder.source_label(),"notice":folder.notice});
        let run_action = if is_txt {
            json!({"key":"workbench","label":format!("검토·복사 시작 · {}건",data.selection.selected_count())})
        } else {
            json!({"key":"generate","label":"이 작업으로 문서 생성"})
        };
        let selection_key = data
            .selected_indices()
            .iter()
            .map(usize::to_string)
            .collect::<Vec<_>>()
            .join(",");
        let notice = if data.notice_text.is_empty() && registry_warning.is_none() {
            Value::Null
        } else {
            let text = [
                (!data.notice_text.is_empty()).then_some(data.notice_text.as_str()),
                registry_warning,
            ]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .join(" ");
            json!({"level":if registry_warning.is_some(){"warn"}else{data.notice_level.as_str()},"text":text})
        };
        let data_row = if data.source_kind.is_empty() {
            Value::Null
        } else {
            session_data_row(
                &data.label,
                &data.kind,
                &data.path,
                &data.sheet,
                data.header_row,
                data.records.len(),
            )
        };
        let mut base = json!({
            "job_name":active_name,"managed_hwpx":false,"last_run_job":last_run_job,"has_job":!active_name.is_empty(),
            "job_data_unbound":seated.is_some_and(|item|!item.job.has_data_binding()),"run_action":run_action,
            "guard":{},"out_dir":folder.directory,"output_folder":output_folder,
            "view_order":data.view_order,"zone_selected_count":data.zone_selected_count(),"zone_epoch":data.zone_epoch,
            "selection_key":selection_key,"data_mount":data.snapshot_generation,"data_label":data.label,
            "data_source_label":source_label(&data.source_kind,&data.label)?,"data_target":data.data_target(),"data_row":data_row,
            "data_pool_key":data.pool_key,"data_sheet_tabs":self.sheet_tabs(data)?,"data_notice":notice,
            "artifact_view":artifact_view,"new_work":{"can":new_work_blocked.is_empty(),"reason":new_work_blocked},
            "candidates":candidates,"browse":browse,"range_draft":data.range_draft_payload(),
            "template_change":blank_change(),"slot_configuration":blank_slot(),"content_presets":blank_presets(),
        });
        if seated.is_some_and(|item| item.job.media() == "hwpx") {
            return self.prepare_hwpx_panel(context, base, &folder);
        }
        let zone_indices = data.zone_indices();
        let mut display_order = (0..data.records.len()).collect::<Vec<_>>();
        let order = data
            .range_draft
            .as_ref()
            .map_or(data.view_order.as_str(), |draft| {
                draft.range.view_order.as_str()
            });
        if order == "sourceDesc" {
            display_order.reverse();
        }
        let rows = record_rows(
            &data.records,
            &display_order,
            &zone_indices,
            &HashMap::new(),
            &[],
        )
        .map_err(error)?;
        let lead = rows
            .iter()
            .filter_map(|row| {
                row.get("index")
                    .and_then(Value::as_u64)
                    .map(|index| (index as usize, row.clone()))
            })
            .collect::<HashMap<_, _>>();
        if lead.len() != data.records.len() {
            return Err(error("행 표시 좌표가 데이터와 일치하지 않습니다."));
        }
        let zone = data
            .zone_sections(&zone_indices, |index| {
                lead.get(&index)
                    .cloned()
                    .expect("validated row coordinates")
            })
            .map_err(error)?;
        let guard = data
            .selection_guard(
                &last_generated.iter().copied().collect::<HashSet<_>>(),
                Some(&zone.filter_visible),
            )
            .map_err(error)?;
        let missing =
            seated.is_some() && (template_path.is_empty() || !Path::new(template_path).exists());
        let gate = if is_txt {
            workbench_entry_gate(
                !data.source_kind.is_empty(),
                data.selection.selected_count(),
                !missing,
            )
        } else if seated.is_some() {
            unsupported_media_gate()
        } else {
            prework_gate(
                !data.source_kind.is_empty(),
                data.selection.selected_count(),
                candidates["top"]
                    .as_array()
                    .is_some_and(|items| !items.is_empty()),
            )
        };
        let gate = json!({"enabled":gate.enabled,"level":gate.level,"text":gate.text,"reason":gate.reason});
        let template_name = Path::new(template_path)
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_default();
        let additional = json!({
            "template_name":template_name,"template_path":template_path,"template_missing":missing,"conn_label":if missing{"템플릿 없음"}else{""},
            "filename_pattern":"","has_data":!data.source_kind.is_empty(),"record_count":data.records.len(),"selected_count":data.selection.selected_count(),
            "records":rows,"filter":zone.filter,"table":zone.table,"guard":guard,
            "preflight":{"level":"","text":""},"blank_fields":[],"drift":[],"name_tokens":[],"gate":gate,"review":blank_review(),
        });
        base.as_object_mut()
            .expect("base object")
            .extend(additional.as_object().expect("additional object").clone());
        if is_txt && let Some(seat) = seated {
            let (change, slot, presets) = self.configuration_zones(&seat.job, missing)?;
            let object = base.as_object_mut().expect("base object");
            object.insert("template_change".into(), change);
            object.insert("slot_configuration".into(), slot.zone);
            object.insert("content_presets".into(), presets);
        }
        Ok(base)
    }
}
