//! Job-screen command state. Screen projection and dispatch consume this single session.

use crate::contract_data_binding::{ContractBindingError, bind_contract_data};
use crate::dataset_registry::DatasetPoolRegistry;
use crate::generation_gate::GenerationGate;
use crate::job_data_session::MountedData;
use crate::job_registry::JobRegistry;
use crate::settings_store;
use crate::template_change_coordinator::TemplateChangeCoordinator;
use crate::workspace_switch::GraphError;
use crate::workspace_switch::PushGate;
use hwpx_filler::active_work_state::{
    ActiveWorkContext, data_binding_mount, preferred_notice, reconcile_data_transition,
    request_preferred,
};
use hwpx_filler::data_contract_check::judge_job_contract;
use hwpx_filler::filter_primitives::{KIND_AMOUNT, KIND_DATE, KIND_TEXT, sniff_column_kinds};
use hwpx_filler::filter_state::FilterModel;
use hwpx_filler::job::Job;
use hwpx_filler::work_candidates::data_binding_matches;
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

#[path = "job_actions.rs"]
mod actions;
#[path = "job_artifact.rs"]
mod artifact;
#[path = "job_data_change.rs"]
mod data_change;
#[path = "job_execution.rs"]
mod execution;
#[path = "job_generation.rs"]
mod generation_run;
#[path = "job_hwpx_panel.rs"]
mod hwpx_panel;
#[path = "job_ledger.rs"]
mod ledger;
#[path = "job_management.rs"]
mod management;
#[path = "job_panel.rs"]
mod panel;
#[path = "job_recovery.rs"]
mod recovery;
#[path = "job_remembered.rs"]
mod remembered;
#[path = "job_run_result.rs"]
mod run_result;
#[path = "job_screen.rs"]
mod screen;
#[path = "job_selection.rs"]
mod selection;
#[path = "job_session_gate.rs"]
mod session_gate;

#[derive(Debug)]
pub struct JobControllerError {
    pub message: String,
    pub code: Option<&'static str>,
}
impl fmt::Display for JobControllerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for JobControllerError {}
fn error(detail: impl ToString) -> JobControllerError {
    JobControllerError {
        message: detail.to_string(),
        code: None,
    }
}

#[derive(Clone)]
struct SeatedJob {
    job: Job,
    application_id: Option<String>,
}
struct JobState {
    data: MountedData,
    seated: Option<SeatedJob>,
    preferred: String,
    browse_tab: String,
    browse_query: String,
    remembered_output_directory: String,
    remembered_data_source: Option<Value>,
    boot_data_restored: bool,
    panel_snapshot: Value,
    delivered: Vec<crate::managed_generation_service::DeliveredDocument>,
    artifact_view: Value,
    last_run_job: String,
    last_generated: Vec<usize>,
    last_failed: Vec<usize>,
    overwrite_pin: Option<(
        generation_run::OverwriteBasis,
        Arc<hwpx_panel::PreparedDelivery>,
    )>,
    prepared_records: Option<Arc<hwpx_panel::PreparedRecords>>,
    prepared_delivery: Option<Arc<hwpx_panel::PreparedDelivery>>,
    historical_outcome: Option<hwpx_filler::document_creation_workbench::HistoricalOutcomeSummary>,
    fresh_observation: Option<hwpx_filler::fresh_execution_observation::FreshExecutionObservation>,
    record_preparation_plan: Option<(
        String,
        hwpx_filler::execution_contract_set::SealedExecutionPlanSemanticPayload,
    )>,
    orchestration: String,
    compiled_templates: HashSet<PathBuf>,
}

impl JobState {
    fn invalidate_results(&mut self) {
        self.last_generated.clear();
        self.delivered.clear();
        self.artifact_view = artifact::closed_view();
        self.overwrite_pin = None;
        self.prepared_records = None;
        self.prepared_delivery = None;
    }
}

type Alert = dyn Fn(&str) + Send + Sync;
type WorkbenchOpen =
    dyn Fn(Job, Vec<(usize, Map<String, Value>)>) -> Result<(), GraphError> + Send + Sync;
type CompiledSink = dyn Fn(&Path) -> Result<(), JobControllerError> + Send + Sync;
type RegisteredData = dyn Fn() -> Result<Option<Value>, String> + Send + Sync;
pub struct JobController {
    registry: Arc<JobRegistry>,
    pool: Arc<DatasetPoolRegistry>,
    change: Arc<TemplateChangeCoordinator>,
    generation: Arc<GenerationGate>,
    settings_path: PathBuf,
    data_identity: String,
    clock: Arc<dyn Fn() -> chrono::NaiveDateTime + Send + Sync>,
    progress_sink: Arc<dyn Fn(Value) + Send + Sync>,
    push_gate: Option<PushGate>,
    workbench_open: Option<Arc<WorkbenchOpen>>,
    compiled_sink: Option<Arc<CompiledSink>>,
    registered_data: Option<Arc<RegisteredData>>,
    boot_restore_in_progress: AtomicBool,
    session_gate: session_gate::JobSessionGate,
    state: Mutex<JobState>,
}
impl JobController {
    pub fn new(
        registry: Arc<JobRegistry>,
        pool: Arc<DatasetPoolRegistry>,
        change: Arc<TemplateChangeCoordinator>,
        generation: Arc<GenerationGate>,
        settings_path: PathBuf,
        alert: Arc<Alert>,
    ) -> Self {
        let settings = settings_store::read_with_alert(&settings_path, |message| alert(message))
            .unwrap_or_else(|failure| {
                alert(&format!("설정 판독 실패: {failure}"));
                Map::new()
            });
        let remembered_output_directory = settings
            .get("last_output_directory")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let remembered_data_source = settings.get("last_data_source").cloned();
        Self {
            registry,
            pool,
            change,
            generation,
            settings_path,
            data_identity: uuid::Uuid::new_v4().simple().to_string(),
            clock: Arc::new(|| chrono::Local::now().naive_local()),
            progress_sink: Arc::new(|_| {}),
            push_gate: None,
            workbench_open: None,
            compiled_sink: None,
            registered_data: None,
            boot_restore_in_progress: AtomicBool::new(false),
            session_gate: session_gate::JobSessionGate::default(),
            state: Mutex::new(JobState {
                data: MountedData::default(),
                seated: None,
                preferred: String::new(),
                browse_tab: "available".into(),
                browse_query: String::new(),
                remembered_output_directory,
                remembered_data_source,
                boot_data_restored: false,
                panel_snapshot: json!({}),
                delivered: Vec::new(),
                artifact_view: json!({"open":false,"ordinal":-1,"filename":"","status":"","detail":""}),
                last_run_job: String::new(),
                last_generated: Vec::new(),
                last_failed: Vec::new(),
                overwrite_pin: None,
                prepared_records: None,
                prepared_delivery: None,
                historical_outcome: None,
                fresh_observation: None,
                record_preparation_plan: None,
                orchestration: hwpx_filler::workbench_execution_status::NO_EVIDENCE.into(),
                compiled_templates: HashSet::new(),
            }),
        }
    }
    /// Inject one clock for deterministic panel and delivery observations.
    pub fn with_clock(
        mut self,
        clock: impl Fn() -> chrono::NaiveDateTime + Send + Sync + 'static,
    ) -> Self {
        self.clock = Arc::new(clock);
        self
    }
    pub fn with_progress_sink(mut self, sink: impl Fn(Value) + Send + Sync + 'static) -> Self {
        self.progress_sink = Arc::new(sink);
        self
    }
    pub fn with_push_gate(mut self, gate: PushGate) -> Self {
        self.push_gate = Some(gate);
        self
    }
    pub fn with_workbench_open(
        mut self,
        open: impl Fn(Job, Vec<(usize, Map<String, Value>)>) -> Result<(), GraphError>
        + Send
        + Sync
        + 'static,
    ) -> Self {
        self.workbench_open = Some(Arc::new(open));
        self
    }
    pub fn with_template_compiled_sink(
        mut self,
        sink: impl Fn(&Path) -> Result<(), JobControllerError> + Send + Sync + 'static,
    ) -> Self {
        self.compiled_sink = Some(Arc::new(sink));
        self
    }
    /// User-home startup discovery. Practice workspace builders leave this callback unset.
    pub fn with_registered_data(
        mut self,
        discover: impl Fn() -> Result<Option<Value>, String> + Send + Sync + 'static,
    ) -> Self {
        self.registered_data = Some(Arc::new(discover));
        self
    }
    pub fn note_template_compiled(&self, path: &Path) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        self.state()?.compiled_templates.insert(path.to_path_buf());
        if let Some(sink) = &self.compiled_sink {
            sink(path)?;
        }
        Ok(())
    }
    pub fn was_template_compiled(&self, path: &Path) -> Result<bool, JobControllerError> {
        let _session = self.session()?;
        Ok(!path.as_os_str().is_empty() && self.state()?.compiled_templates.contains(path))
    }
    fn state(&self) -> Result<MutexGuard<'_, JobState>, JobControllerError> {
        self.state
            .lock()
            .map_err(|_| error("작업 화면 상태 잠금이 손상되었습니다."))
    }
    fn session(&self) -> Result<session_gate::JobSessionLease<'_>, JobControllerError> {
        self.session_gate.enter().map_err(error)
    }
    /// Serialize onboarding's preflight, seed, and workspace switch with Job entrypoints.
    /// The gate is reentrant because the switch may call back into `prefer_work`.
    pub fn with_transition_lease<T>(
        &self,
        work: impl FnOnce() -> T,
    ) -> Result<T, JobControllerError> {
        let _lease = self.session()?;
        Ok(work())
    }
    pub fn current_pool_source(
        &self,
    ) -> Result<Option<(String, Option<String>)>, JobControllerError> {
        let _session = self.session()?;
        Ok(self.state()?.data.current_pool_source())
    }
    pub fn raise_if_generating_before_swap(&self, then_do: &str) -> Result<(), JobControllerError> {
        self.generation
            .raise_if_generating(then_do, true)
            .map_err(error)
    }
    pub fn with_editor_save_guard<T>(
        &self,
        work: impl FnOnce() -> T,
    ) -> Result<Option<T>, JobControllerError> {
        self.generation.with_editor_save_guard(work).map_err(error)
    }
    pub fn remembered_output_directory(&self) -> Result<String, JobControllerError> {
        let _session = self.session()?;
        Ok(self.state()?.remembered_output_directory.clone())
    }
    pub fn set_output_folder(&self, path: &str) -> Result<(), JobControllerError> {
        let _session = self.session()?;
        if hwpx_filler::structure_scan::python_trim(path).is_empty() {
            return Err(error(format!(
                "유효하지 않은 저장 폴더 경로: {}",
                hwpx_filler::text_render::python_repr(&Value::String(path.into()))
            )));
        }
        {
            let mut state = self.state()?;
            state.prepared_delivery = None;
            state.overwrite_pin = None;
            state.remembered_output_directory = path.into();
        }
        let stored = settings_store::mutate(&self.settings_path, |settings| {
            settings.insert("last_output_directory".into(), Value::String(path.into()));
        })
        .map_err(error);
        let pushed = self.push_snapshot();
        stored?;
        pushed
    }
    pub fn data(&self) -> Result<MountedData, JobControllerError> {
        let _session = self.session()?;
        Ok(self.state()?.data.clone())
    }
    pub fn new_work_handoff(&self) -> Result<(Value, String), JobControllerError> {
        let _session = self.session()?;
        Ok(self.state()?.data.new_work_handoff())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::dataset_reference::{DatasetReference, FilterPreset};
    use hwpx_filler::fresh_execution_observation::{
        CurrentSealedPlanObservation, FreshExecutionObservation, RuntimePolicyAdmission,
    };
    use hwpx_filler::job::rules_fingerprints;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use std::fs;

    fn assert_compiled_template_identity(controller: &JobController, sandbox: &Path) {
        let compiled = sandbox.join("converted.hwpx");
        assert!(!controller.was_template_compiled(&compiled).unwrap());
        controller.note_template_compiled(&compiled).unwrap();
        assert!(controller.was_template_compiled(&compiled).unwrap());
        assert!(!controller.was_template_compiled(Path::new("")).unwrap());
    }

    fn assert_non_hwpx_generation_refuses(controller: &JobController) {
        let original = controller.state().unwrap().seated.clone().unwrap();
        for path in ["", "C:/draft.txt", "C:/unsupported.docx"] {
            controller
                .state()
                .unwrap()
                .seated
                .as_mut()
                .unwrap()
                .job
                .template_path = path.into();
            let refused = controller.generate(false, "wrong-media").unwrap();
            assert_eq!(refused["ok"], false);
            assert_eq!(refused["error"], "현재 환경에서는 문서를 만들 수 없습니다");
            assert_eq!(refused["run_token"], "wrong-media");
            assert!(controller.state().unwrap().delivered.is_empty());
        }
        controller.state().unwrap().seated = Some(original);
    }

    fn assert_refresh_preserves_unreadable_selection(
        controller: &JobController,
        registry: &JobRegistry,
    ) {
        let name = controller.selected_job_name().unwrap();
        assert!(!name.is_empty());
        let original = controller
            .state()
            .unwrap()
            .seated
            .as_ref()
            .unwrap()
            .job
            .clone();
        let data = controller.data().unwrap();
        let path = registry.path_for(&name);
        let bytes = fs::read(&path).unwrap();
        for directory in [false, true] {
            fs::remove_file(&path).unwrap();
            if directory {
                fs::create_dir(&path).unwrap();
            } else {
                fs::write(&path, b"broken JSON").unwrap();
            }
            assert_eq!(
                controller.refresh_jobs().unwrap()["notice"],
                "문서 작업 목록을 읽지 못했습니다. 다시 시도하세요."
            );
            assert_eq!(controller.selected_job_name().unwrap(), name);
            assert_eq!(
                controller.state().unwrap().seated.as_ref().unwrap().job,
                original
            );
            assert_eq!(
                controller.data().unwrap().selected_indices(),
                data.selected_indices()
            );
            assert_eq!(
                controller.data().unwrap().snapshot_generation,
                data.snapshot_generation
            );
            if directory {
                fs::remove_dir(&path).unwrap();
            }
            fs::write(&path, &bytes).unwrap();
        }
        assert_eq!(controller.refresh_jobs().unwrap(), Value::Null);
        fs::remove_file(&path).unwrap();
        assert!(
            controller.refresh_jobs().unwrap()["notice"]
                .as_str()
                .unwrap()
                .contains("삭제되어")
        );
        assert_eq!(controller.selected_job_name().unwrap(), "");
        assert_eq!(controller.data().unwrap().records, data.records);
        fs::write(&path, bytes).unwrap();
    }

    fn assert_managed_delivery(
        controller: &Arc<JobController>,
        registry: &JobRegistry,
        sandbox: &Path,
        csv: &Path,
        now: &Mutex<chrono::NaiveDateTime>,
    ) -> (PathBuf, PathBuf) {
        let managed_template = sandbox.join("managed.hwpx");
        let mut archive = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
        archive
            .start_file("mimetype", zip::write::SimpleFileOptions::default())
            .unwrap();
        std::io::Write::write_all(&mut archive, b"application/hwp+zip").unwrap();
        archive
            .start_file(
                "Contents/section0.xml",
                zip::write::SimpleFileOptions::default(),
            )
            .unwrap();
        std::io::Write::write_all(
            &mut archive,
            br#"<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:ctrl><hp:fieldBegin name="Name"/></hp:ctrl></hp:run><hp:run><hp:t>{{Name}}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>"#,
        )
        .unwrap();
        fs::write(&managed_template, archive.finish().unwrap().into_inner()).unwrap();
        let mut managed = Job {
            name: "Managed".into(),
            template_path: managed_template.to_string_lossy().into_owned(),
            data_path: csv.to_string_lossy().into_owned(),
            data_header_row: 0,
            filename_pattern: "{{date:%Y%m%d}}-doc-{{seq:001}}".into(),
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("Name", "name", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        managed.reviewed_rules = rules_fingerprints(&managed);
        registry.save(&mut managed, false).unwrap();
        controller.select_job("Managed").unwrap();
        assert_binding_review_uses_current_work_evidence(controller, registry);
        assert_execution_refresh_preserves_evidence_boundaries(controller, registry);
        assert_record_validation_reaches_current_recovery_targets(controller);
        controller.dispatch("set_all", &json!({})).unwrap();
        assert_output_folder_contract(controller, sandbox);
        let output = sandbox.join("results");
        fs::create_dir(&output).unwrap();
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let preview =
            controller.refresh_panel().unwrap()["workbench_observation"]["delivery"].clone();
        let records = controller
            .state()
            .unwrap()
            .prepared_records
            .clone()
            .unwrap();
        let delivery = controller
            .state()
            .unwrap()
            .prepared_delivery
            .clone()
            .unwrap();
        assert!(!preview.is_null());
        *now.lock().unwrap() += chrono::Duration::days(1);
        assert_eq!(
            controller.refresh_panel().unwrap()["workbench_observation"]["delivery"],
            preview
        );
        assert!(Arc::ptr_eq(
            &records,
            controller
                .state()
                .unwrap()
                .prepared_records
                .as_ref()
                .unwrap()
        ));
        assert!(Arc::ptr_eq(
            &delivery,
            controller
                .state()
                .unwrap()
                .prepared_delivery
                .as_ref()
                .unwrap()
        ));
        let delivered = controller.generate(false, "owner-run").unwrap();
        assert_eq!(delivered["status"], "completed", "{delivered}");
        assert_eq!(delivered["succeeded"], 2);
        assert!(delivered.get("needs_overwrite").is_none());
        assert!(controller.state().unwrap().overwrite_pin.is_none());
        assert_eq!(controller.snapshot().unwrap()["last_run_job"], "Managed");
        let planned_names = preview["planned_documents"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["relative_path"].as_str().unwrap())
            .collect::<Vec<_>>();
        let delivered_names = delivered["delivered"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["filename"].as_str().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(delivered_names, planned_names);
        let ledgers = fs::read_dir(&output)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| {
                path.file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("fill-ledger-")
            })
            .collect::<Vec<_>>();
        assert_eq!(ledgers.len(), 1);
        let ledger: Value = serde_json::from_slice(&fs::read(&ledgers[0]).unwrap()).unwrap();
        assert_eq!(ledger["outcome"], "DeliveryCompleted");
        assert_eq!(
            ledger["delivered"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| item["relative_path"].as_str().unwrap())
                .collect::<Vec<_>>(),
            delivered_names
        );
        let stamped = registry.load("Managed").unwrap();
        assert!(!stamped.last_run_at.is_empty());
        assert_eq!(stamped.reviewed_rules, rules_fingerprints(&stamped));
        let generated_values = (0..2)
            .map(|ordinal| {
                let document = controller.delivered_artifact(ordinal).unwrap().unwrap();
                assert!(
                    document.relative_path.starts_with("20261106-"),
                    "{}",
                    document.relative_path
                );
                let bytes = fs::read(document.absolute_path).unwrap();
                let parsed = hwpx_core::package::HwpxPackage::from_bytes(
                    &bytes,
                    hwpx_core::package::PackageLimits::default(),
                )
                .unwrap();
                hwpx_filler::fields::read_fields(&parsed)
                    .unwrap()
                    .into_iter()
                    .find(|(name, _)| name == "Name")
                    .map(|(_, value)| value)
                    .unwrap()
            })
            .collect::<Vec<_>>();
        assert_eq!(generated_values, ["second", "first"]);
        generation_run::tests::assert_run_evidence_survives_failures(controller, sandbox);
        assert!(!Arc::ptr_eq(
            &delivery,
            controller
                .state()
                .unwrap()
                .prepared_delivery
                .as_ref()
                .unwrap()
        ));
        let other_output = sandbox.join("other-results");
        fs::create_dir(&other_output).unwrap();
        controller
            .set_output_folder(other_output.to_str().unwrap())
            .unwrap();
        let retry = controller
            .state()
            .unwrap()
            .prepared_delivery
            .clone()
            .unwrap();
        fs::write(other_output.join("20261107-doc-001.hwpx"), b"occupied").unwrap();
        controller
            .set_output_folder(other_output.to_str().unwrap())
            .unwrap();
        assert!(!Arc::ptr_eq(
            &retry,
            controller
                .state()
                .unwrap()
                .prepared_delivery
                .as_ref()
                .unwrap()
        ));
        assert_eq!(
            controller.snapshot().unwrap()["workbench_observation"]["delivery"]["planned_documents"]
                [0]["collision_disposition"],
            "WRITE_OVERWRITE"
        );
        assert!(Arc::ptr_eq(
            &records,
            controller
                .state()
                .unwrap()
                .prepared_records
                .as_ref()
                .unwrap()
        ));
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let data = controller.data().unwrap();
        assert_overwrite_confirmation(controller, registry, &output, &other_output, now);
        let FreshExecutionObservation::Sealed(sealed) = controller
            .state()
            .unwrap()
            .fresh_observation
            .clone()
            .unwrap()
        else {
            panic!("current plan")
        };
        let mut moved = sealed.sealed_plan_value.clone();
        moved.execution_basis.qualification_profile_semantic_digest = "profile-moved".into();
        let revalidated = controller
            .prepared_records("Managed", &data, &moved, *now.lock().unwrap())
            .unwrap();
        assert!(!Arc::ptr_eq(&records, &revalidated));
        assert_template_apply_refreshes_execution(controller);
        (managed_template, output)
    }

    fn assert_template_apply_refreshes_execution(controller: &JobController) {
        let template = PathBuf::from(controller.registry.load("Managed").unwrap().template_path);
        let before = controller.state().unwrap().fresh_observation.clone();
        let original = fs::read(&template).unwrap();
        assert_eq!(
            hwpx_panel::fields_from_template(template.to_str().unwrap()).unwrap(),
            ["Name"]
        );
        let mut package = hwpx_core::package::HwpxPackage::from_bytes(
            &original,
            hwpx_core::package::PackageLimits::default(),
        )
        .unwrap();
        let mut changed_fields = package.clone();
        for entry in &mut changed_fields.entries {
            if entry.name == "Contents/section0.xml" {
                entry.data = String::from_utf8(entry.data.clone())
                    .unwrap()
                    .replace("name=\"Name\"", "name=\"New\"")
                    .into_bytes();
            }
        }
        fs::write(&template, changed_fields.to_bytes().unwrap()).unwrap();
        assert_eq!(
            hwpx_panel::fields_from_template(template.to_str().unwrap()).unwrap(),
            ["New"]
        );
        fs::write(&template, b"not a zip").unwrap();
        assert!(hwpx_panel::fields_from_template(template.to_str().unwrap()).is_err());
        fs::write(&template, &original).unwrap();
        let section = package
            .entries
            .iter_mut()
            .find(|entry| entry.name == "Contents/section0.xml")
            .unwrap();
        section.data = String::from_utf8(section.data.clone())
            .unwrap()
            .replace("{{Name}}", "Updated {{Name}}")
            .into_bytes();
        fs::write(&template, package.to_bytes().unwrap()).unwrap();
        let checked = controller
            .dispatch("template_check", &json!({"request_id":"replacement"}))
            .unwrap();
        assert_eq!(checked["preparation"]["status"], "ready", "{checked}");
        let applied = controller
            .dispatch(
                "template_apply",
                &json!({
                    "change_token":checked["preparation"]["change_token"]
                }),
            )
            .unwrap();
        assert_eq!(applied["status"], "applied", "{applied}");
        assert_eq!(applied["is_current"], true);
        assert_ne!(controller.state().unwrap().fresh_observation, before);
        assert_eq!(
            controller.refresh_panel().unwrap()["workbench_observation"]["execution_status_code"],
            "CURRENT"
        );
        fs::write(template, original).unwrap();
    }

    fn assert_binding_review_uses_current_work_evidence(
        controller: &JobController,
        registry: &JobRegistry,
    ) {
        let original = registry.load("Managed").unwrap();
        let fresh = controller.state().unwrap().fresh_observation.clone();
        assert!(matches!(fresh, Some(FreshExecutionObservation::Sealed(_))));
        registry
            .mutate("Managed", |job| job.mapping.mappings.clear())
            .unwrap();
        assert!(
            !controller.binding_confirm_pending("Managed").unwrap(),
            "a sealed observation must not expose a new binding confirmation"
        );
        controller.state().unwrap().fresh_observation = None;
        assert!(
            !controller.binding_confirm_pending("Managed").unwrap(),
            "no session evidence must not enable confirmation"
        );
        controller.resolve_execution().unwrap();
        let zone = controller.refresh_panel().unwrap()["workbench_observation"].clone();
        assert_ne!(zone["execution_status_code"], "CURRENT");
        assert_eq!(zone["materialization_readiness"], "NOT_READY");
        assert_ne!(zone["primary_action"], "CREATE_DOCUMENTS");
        assert!(
            zone["blockers"]
                .as_array()
                .unwrap()
                .contains(&json!("REVIEW_BINDING")),
            "{zone}"
        );
        assert!(controller.binding_confirm_pending("Managed").unwrap());
        assert!(!controller.binding_confirm_pending("Other").unwrap());
        controller.after_mapping_saved("Managed").unwrap();
        assert_eq!(controller.state().unwrap().orchestration, "STALE");
        assert!(matches!(
            controller.state().unwrap().fresh_observation,
            Some(FreshExecutionObservation::WorkBlocked(_))
        ));
        registry
            .mutate("Managed", |job| job.mapping = original.mapping.clone())
            .unwrap();
        assert_eq!(controller.after_mapping_saved("Other").unwrap(), json!({}));
        assert!(matches!(
            controller.state().unwrap().fresh_observation,
            Some(FreshExecutionObservation::WorkBlocked(_))
        ));
        assert_eq!(
            controller.after_mapping_saved("Managed").unwrap(),
            json!({})
        );
        let zone = controller.refresh_panel().unwrap()["workbench_observation"].clone();
        assert_eq!(zone["execution_status_code"], "CURRENT");
        assert_eq!(zone["admission"]["state"], "ADMITTED");
        assert_eq!(zone["materialization_readiness"], "READY");
        assert!(!controller.binding_confirm_pending("Managed").unwrap());
    }

    fn assert_execution_refresh_preserves_evidence_boundaries(
        controller: &JobController,
        registry: &JobRegistry,
    ) {
        {
            let mut state = controller.state().unwrap();
            state.fresh_observation = None;
            state.orchestration = "NO_EVIDENCE".into();
        }
        controller.refresh_execution_observation().unwrap();
        assert_eq!(controller.state().unwrap().orchestration, "NO_EVIDENCE");
        assert!(matches!(
            controller.state().unwrap().fresh_observation,
            Some(FreshExecutionObservation::Sealed(_))
        ));
        controller.resolve_execution().unwrap();
        let original = controller.state().unwrap().fresh_observation.clone();
        controller.select_job("Managed").unwrap();
        assert_eq!(controller.state().unwrap().fresh_observation, original);
        for action in ["resolve_execution", "refresh_observation"] {
            controller.dispatch(action, &json!({})).unwrap();
            assert_eq!(controller.state().unwrap().fresh_observation, original);
            assert_eq!(
                controller.snapshot().unwrap()["workbench_observation"]["execution_status_code"],
                "CURRENT"
            );
        }
        let path = registry.path_for("Managed");
        let stored = fs::read(&path).unwrap();
        fs::write(&path, b"broken job").unwrap();
        controller.refresh_execution_observation().unwrap();
        assert_eq!(controller.state().unwrap().orchestration, "CURRENT");
        let failed = controller.state().unwrap().fresh_observation.clone();
        assert!(matches!(
            failed,
            Some(FreshExecutionObservation::ContextError(_))
        ));
        assert!(!controller.binding_confirm_pending("Managed").unwrap());
        for _ in 0..2 {
            fs::write(&path, &stored).unwrap();
            let panel = controller.refresh_panel().unwrap();
            let zone = &panel["workbench_observation"];
            assert_eq!(zone["kind"], "context_error");
            assert_eq!(zone["execution_status_code"], "CONTEXT_ERROR");
            assert_eq!(zone["user_fixable"], false);
            assert_eq!(zone["create_action"]["enabled"], false);
            assert_eq!(zone["primary_action"], "RECOVER_CONTEXT");
            assert_eq!(zone["recover_action"]["enabled"], true);
            assert!(!zone["recover_action"]["label"].as_str().unwrap().is_empty());
            assert!(zone["recover_action"]["disabled_reason"].is_null());
            assert!(zone.get("execution_action").is_none());
            assert!(panel.get("output_folder").is_some());
            fs::write(&path, b"broken job").unwrap();
            controller.resolve_execution().unwrap();
            assert_eq!(controller.state().unwrap().orchestration, "STALE");
            assert!(matches!(
                controller.state().unwrap().fresh_observation,
                Some(FreshExecutionObservation::ContextError(_))
            ));
        }
        controller.state().unwrap().orchestration = "CHECKING".into();
        controller.resolve_execution().unwrap();
        assert_eq!(controller.state().unwrap().orchestration, "CHECKING");
        assert_eq!(controller.state().unwrap().fresh_observation, failed);
        fs::write(&path, stored).unwrap();
        controller.state().unwrap().orchestration = "STALE".into();
        crate::workspace_switch::ScreenController::dispatch(
            controller,
            "refresh_observation",
            &json!({}),
        )
        .unwrap();
        assert_eq!(
            controller.refresh_panel().unwrap()["workbench_observation"]["kind"],
            "observation"
        );
        assert_eq!(controller.state().unwrap().fresh_observation, original);
        controller.resolve_execution().unwrap();
        assert_eq!(controller.state().unwrap().fresh_observation, original);
        controller.select_job("Renamed").unwrap();
        assert!(controller.state().unwrap().fresh_observation.is_none());
        assert_eq!(controller.state().unwrap().orchestration, "NO_EVIDENCE");
        assert!(!controller.binding_confirm_pending("Renamed").unwrap());
        controller.select_job("Managed").unwrap();
        assert_eq!(controller.refresh_panel().unwrap()["managed_hwpx"], true);
        assert_eq!(controller.state().unwrap().fresh_observation, original);
    }

    fn set_validation_rows(controller: &JobController, records: Value, columns: &[&str]) {
        let mut state = controller.state().unwrap();
        state.data.records = records
            .as_array()
            .unwrap()
            .iter()
            .map(|record| {
                record
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(key, value)| (key.clone(), value.as_str().unwrap().into()))
                    .collect()
            })
            .collect();
        state.data.fields = columns.iter().map(|column| (*column).into()).collect();
        state.data.selection =
            hwpx_filler::selection_state::SelectionModel::new(state.data.records.len(), false);
        state.data.selection.set_all();
        state.data.filter = Some(hwpx_filler::filter_state::FilterModel::new(
            state.data.fields.clone(),
            Default::default(),
        ));
        state.data.range_draft = None;
        state.data.hidden_columns.clear();
        state.data.view_order = "sourceAsc".into();
        state.data.snapshot_generation += 1;
        state.data.zone_epoch += 1;
        state.orchestration = "CURRENT".into();
    }

    fn assert_record_validation_reaches_current_recovery_targets(controller: &JobController) {
        let saved = controller.data().unwrap();
        for (records, columns, index, kind, element) in [
            (
                json!([{"name":"normal"},{"other":"value"}]),
                vec!["name", "other"],
                1,
                "cell",
                "jobCell-1-0",
            ),
            (
                json!([{"other":"value"}]),
                vec!["other"],
                0,
                "row",
                "jobRow-0",
            ),
        ] {
            set_validation_rows(controller, records, &columns);
            let snapshot = controller.refresh_panel().unwrap();
            let zone = &snapshot["workbench_observation"];
            let validation = &zone["record_validation"];
            assert_eq!(validation["blocked_count"], 1, "{zone}");
            assert_eq!(zone["primary_action"], "REVIEW_RECORD_DATA");
            let issue = &validation["issues"][0];
            assert_eq!(issue["field_display_label"], "name");
            assert_eq!(issue["message"], "이 항목에 연결한 데이터 열이 없습니다.");
            let target = &issue["recovery_target"];
            assert_eq!(target["target_kind"], kind);
            assert_eq!(target["model_index"], index);
            assert_eq!(target["field_id"], "name");
            assert_eq!(
                controller
                    .dispatch("recover_record_issue", &json!({"target":target}))
                    .unwrap(),
                json!({
                    "ok":true,"element_id":element,"fallback_element_id":format!("jobRow-{index}")
                })
            );
            controller.state().unwrap().orchestration = "STALE".into();
            assert_eq!(
                controller.refresh_panel().unwrap()["workbench_observation"]["record_validation"]["issue_count"],
                0
            );
            assert!(
                controller
                    .dispatch("recover_record_issue", &json!({"target":target}))
                    .unwrap_err()
                    .message
                    .contains("현재 데이터 확인 결과가 없습니다")
            );
        }
        set_validation_rows(
            controller,
            json!([{"name":"normal"},{"name":" "}]),
            &["name"],
        );
        let snapshot = controller.refresh_panel().unwrap();
        let validation = &snapshot["workbench_observation"]["record_validation"];
        assert_eq!(validation["validated_count"], 2);
        assert_eq!(validation["blocked_count"], 0);
        assert_eq!(validation["issues"], json!([]));
        assert_eq!(validation["advisory_count"], 1);
        assert_eq!(
            validation["advisory_notice"],
            "빈 값 1칸이 있습니다. 문서에는 미입력 표식이 들어갑니다."
        );
        controller.dispatch("set_none", &json!({})).unwrap();
        let snapshot = controller.refresh_panel().unwrap();
        let action = &snapshot["workbench_observation"]["create_action"];
        assert_eq!(action["enabled"], false);
        let result = controller.generate(false, "unselected").unwrap();
        assert_eq!(result["ok"], false);
        assert_eq!(result["error"], action["disabled_reason"]);
        {
            let mut state = controller.state().unwrap();
            state.data = saved;
            state.prepared_records = None;
            state.prepared_delivery = None;
        }
        controller.refresh_panel().unwrap();
    }

    fn assert_overwrite_confirmation(
        controller: &JobController,
        registry: &JobRegistry,
        output: &Path,
        other_output: &Path,
        now: &Mutex<chrono::NaiveDateTime>,
    ) {
        let original = registry.load("Managed").unwrap();
        let day = now.lock().unwrap().format("%Y%m%d").to_string();
        let leaf = format!("{day}-doc-001.hwpx");
        fs::write(output.join(&leaf), b"original").unwrap();
        fs::write(other_output.join(&leaf), b"other").unwrap();
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let asked = controller.generate(false, "overwrite").unwrap();
        assert_eq!(asked["ok"], false);
        assert_eq!(asked["needs_overwrite"], true);
        assert_eq!(asked["run_token"], "overwrite");
        assert_eq!(asked["conflict_names"], json!([leaf]));
        assert_eq!(asked["total"], 2);
        assert_eq!(asked["overwrite_count"], 1);
        assert_eq!(asked["conflict_more"], 0);
        assert_eq!(asked["new_count"], 1);
        assert_eq!(fs::read(output.join(&leaf)).unwrap(), b"original");
        assert!(!output.join(format!("{day}-doc-002.hwpx")).exists());
        controller
            .set_output_folder(other_output.to_str().unwrap())
            .unwrap();
        let refused = controller.generate(true, "overwrite").unwrap();
        assert_eq!(refused["ok"], false, "{refused}");
        assert_eq!(fs::read(other_output.join(&leaf)).unwrap(), b"other");
        assert_eq!(registry.load("Managed").unwrap(), original);
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        assert_eq!(controller.generate(true, "unarmed").unwrap()["ok"], false);
        assert_eq!(fs::read(output.join(&leaf)).unwrap(), b"original");
        let fallback = Path::new(&original.template_path)
            .parent()
            .unwrap()
            .join("Results");
        fs::write(fallback.join(&leaf), b"fallback").unwrap();
        assert_eq!(
            controller.generate(false, "disappeared").unwrap()["needs_overwrite"],
            true
        );
        let moved = output.with_file_name("temporarily-moved-results");
        fs::rename(output, &moved).unwrap();
        let refused = controller.generate(true, "disappeared").unwrap();
        fs::rename(&moved, output).unwrap();
        assert_eq!(refused["ok"], false, "{refused}");
        assert_eq!(fs::read(fallback.join(&leaf)).unwrap(), b"fallback");
        assert_changed_filename_binding(controller, registry, output);
        assert_eq!(
            controller.generate(false, "selection").unwrap()["needs_overwrite"],
            true
        );
        controller
            .dispatch("toggle_record", &json!({"index":0,"value":false}))
            .unwrap();
        let refused = controller.generate(true, "selection").unwrap();
        assert_eq!(refused["ok"], false);
        assert_eq!(refused["level"], "warn");
        assert!(refused.get("needs_overwrite").is_none());
        assert!(controller.state().unwrap().overwrite_pin.is_none());
        assert_eq!(fs::read(output.join(&leaf)).unwrap(), b"original");
        controller.dispatch("set_all", &json!({})).unwrap();
        for change_pattern in [true, false] {
            assert_eq!(
                controller.generate(false, "changed-rule").unwrap()["needs_overwrite"],
                true
            );
            registry
                .mutate("Managed", |job| {
                    if change_pattern {
                        job.filename_pattern = "changed-{{seq:001}}".into();
                    } else {
                        job.mapping.mappings.push(
                            FieldMapping::new("Unused", "name", "text", "", "", None).unwrap(),
                        );
                    }
                })
                .unwrap();
            fs::write(output.join("changed-001.hwpx"), b"changed").unwrap();
            controller.refresh_jobs().unwrap();
            let refused = controller.generate(true, "changed-rule").unwrap();
            assert_eq!(refused["ok"], false, "{refused}");
            assert_eq!(
                fs::read(output.join("changed-001.hwpx")).unwrap(),
                b"changed"
            );
            assert_eq!(fs::read(output.join(&leaf)).unwrap(), b"original");
            registry
                .mutate("Managed", |job| {
                    job.filename_pattern = original.filename_pattern.clone();
                    job.mapping = original.mapping.clone();
                })
                .unwrap();
            controller.refresh_jobs().unwrap();
        }
        assert_eq!(
            controller.generate(false, "confirmed").unwrap()["needs_overwrite"],
            true
        );
        let delivery = controller
            .state()
            .unwrap()
            .prepared_delivery
            .clone()
            .unwrap();
        *now.lock().unwrap() += chrono::Duration::days(1);
        let result = controller.generate(true, "confirmed").unwrap();
        assert_eq!(result["status"], "completed", "{result}");
        assert_eq!(result["run_token"], "confirmed");
        assert_eq!(result["succeeded"], 2);
        assert!(controller.state().unwrap().overwrite_pin.is_none());
        assert!(!Arc::ptr_eq(
            &delivery,
            controller
                .state()
                .unwrap()
                .prepared_delivery
                .as_ref()
                .unwrap()
        ));
        for ordinal in 0..2 {
            let document = controller.delivered_artifact(ordinal).unwrap().unwrap();
            assert_eq!(
                document.relative_path,
                format!("{day}-doc-{:03}.hwpx", ordinal + 1)
            );
            assert!(fs::read(document.absolute_path).unwrap().starts_with(b"PK"));
        }
        assert_eq!(controller.generate(true, "replayed").unwrap()["ok"], false);
    }

    fn assert_output_folder_contract(controller: &Arc<JobController>, sandbox: &Path) {
        use crate::editor_controller::EditorController;
        use crate::shell_settings::ShellSettings;
        use crate::template_root::TemplateRoot;
        use crate::workspace_switch::{WorkspaceGraph, WorkspaceSwitch};

        controller
            .state()
            .unwrap()
            .remembered_output_directory
            .clear();
        let stored = controller.registry.load("Managed").unwrap();
        let default = Path::new(&stored.template_path)
            .parent()
            .unwrap()
            .join("Results");
        let panel = controller.refresh_panel().unwrap();
        assert_eq!(
            panel["output_folder"],
            json!({"directory":default,
            "source":"template_default","source_label":"기본값","notice":""})
        );
        let zone = &panel["workbench_observation"];
        assert!(zone.get("output_folder").is_none());
        assert_eq!(
            zone["run_delivery_intent"],
            json!({"output_directory":default,
            "collision_policy":"OVERWRITE_EXPLICIT"})
        );
        assert_eq!(zone["delivery"]["resolvable"], true);
        assert!(!default.exists());
        for action in ["set_delivery_collision", "refresh_delivery"] {
            assert!(controller.dispatch(action, &json!({})).is_err());
        }
        let delivered = controller.generate(false, "default-folder").unwrap();
        assert_eq!(delivered["status"], "completed", "{delivered}");
        assert!(default.is_dir());
        assert_eq!(
            controller
                .delivered_artifact(0)
                .unwrap()
                .unwrap()
                .absolute_path
                .canonicalize()
                .unwrap(),
            default
                .join("20261106-doc-001.hwpx")
                .canonicalize()
                .unwrap()
        );
        let picked = sandbox.join("고른-폴더");
        fs::create_dir(&picked).unwrap();
        controller.select_job("").unwrap();
        controller
            .set_output_folder(picked.to_str().unwrap())
            .unwrap();
        let folder = json!({"directory":picked,"source":"remembered",
            "source_label":"설정한 저장 폴더","notice":""});
        assert_eq!(controller.snapshot().unwrap()["output_folder"], folder);
        assert!(controller.set_output_folder(" \t ").is_err());
        assert_eq!(
            controller.remembered_output_directory().unwrap(),
            picked.to_string_lossy()
        );
        let saved: Value =
            serde_json::from_slice(&fs::read(&controller.settings_path).unwrap()).unwrap();
        assert_eq!(
            saved["last_output_directory"],
            picked.to_string_lossy().as_ref()
        );
        controller.select_job("Managed").unwrap();
        controller.dispatch("set_all", &json!({})).unwrap();
        let panel = controller.refresh_panel().unwrap();
        assert_eq!(panel["output_folder"], folder);
        assert_eq!(panel["out_dir"], picked.to_string_lossy().as_ref());
        assert_eq!(
            panel["workbench_observation"]["run_delivery_intent"]["output_directory"],
            panel["out_dir"],
            "{}",
            panel["workbench_observation"]
        );
        assert_delivery_occupancy(controller, &picked);
        let read = controller.clone();
        let templates = Arc::new(
            TemplateRoot::new(
                Arc::new(ShellSettings::new(controller.settings_path.clone(), |_| {})),
                sandbox.to_path_buf(),
            )
            .unwrap(),
        );
        let graph = WorkspaceSwitch::new(
            crate::locations::Locations::new(sandbox, None),
            |_, _| Ok(None),
            move |home, push, token| {
                let remembered = read.clone();
                let editor = EditorController::new(
                    read.registry.clone(),
                    templates.clone(),
                    read.pool.clone(),
                    push,
                )?
                .with_output_directory(move || {
                    remembered
                        .remembered_output_directory()
                        .map_err(|e| e.to_string().into())
                });
                editor.load_job("Managed")?;
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("editor".into(), Arc::new(editor))],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let editor = graph.active().controller("editor").unwrap();
        assert_eq!(editor.initial().unwrap()["output_folder"], folder);
        fs::remove_dir(&picked).unwrap();
        let missing = controller.refresh_panel().unwrap()["output_folder"].clone();
        assert_eq!(missing["directory"], default.to_string_lossy().as_ref());
        assert_eq!(missing["source"], "template_default");
        assert_eq!(
            missing["notice"],
            "설정한 저장 폴더를 찾을 수 없습니다. 기본 폴더로 되돌렸습니다."
        );
        assert_eq!(editor.initial().unwrap()["output_folder"], missing);
        controller.select_job("").unwrap();
        assert_eq!(
            controller.refresh_panel().unwrap()["output_folder"],
            json!({"directory":"",
            "source":"","source_label":"",
            "notice":"설정한 저장 폴더를 찾을 수 없습니다. 설정에서 저장 폴더를 선택하세요."})
        );
        controller.select_job("Managed").unwrap();
        controller.dispatch("set_all", &json!({})).unwrap();
    }

    fn assert_changed_filename_binding(
        controller: &JobController,
        registry: &JobRegistry,
        output: &Path,
    ) {
        let original = registry.load("Managed").unwrap();
        registry
            .mutate("Managed", |job| {
                job.filename_pattern = "bound-{{Unused}}-{{seq:001}}".into();
                job.mapping
                    .mappings
                    .push(FieldMapping::new("Unused", "", "const", "before", "", None).unwrap());
            })
            .unwrap();
        controller.refresh_jobs().unwrap();
        controller.after_mapping_saved("Managed").unwrap();
        for name in ["before", "after"] {
            fs::write(output.join(format!("bound-{name}-001.hwpx")), name).unwrap();
        }
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let asked = controller.generate(false, "binding-change").unwrap();
        assert_eq!(
            asked["conflict_names"],
            json!(["bound-before-001.hwpx"]),
            "{asked}"
        );
        registry
            .mutate("Managed", |job| {
                job.mapping.mappings.last_mut().unwrap().constant = "after".into();
            })
            .unwrap();
        controller.after_mapping_saved("Managed").unwrap();
        let result = controller.generate(true, "binding-change").unwrap();
        assert_eq!(result["ok"], false, "{result}");
        for name in ["before", "after"] {
            assert_eq!(
                fs::read(output.join(format!("bound-{name}-001.hwpx"))).unwrap(),
                name.as_bytes()
            );
        }
        registry
            .mutate("Managed", |job| {
                job.filename_pattern = original.filename_pattern.clone();
                job.mapping = original.mapping.clone();
            })
            .unwrap();
        controller.refresh_jobs().unwrap();
        controller.after_mapping_saved("Managed").unwrap();
    }

    fn assert_delivery_occupancy(controller: &JobController, output: &Path) {
        let conflict = output.join("20261106-doc-001.hwpx");
        fs::write(&conflict, b"existing").unwrap();
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let panel = controller.snapshot().unwrap();
        let zone = &panel["workbench_observation"];
        assert_eq!(zone["primary_action"], "CREATE_DOCUMENTS");
        let generation = controller.data().unwrap().snapshot_generation;
        assert_eq!(
            zone["delivery"],
            json!({"resolvable":true,"blockers":[],
            "planned_documents":[
                {"record_identity":format!("current-record/{generation}/1"), "item_ordinal":0,
                    "relative_path":"20261106-doc-001.hwpx","collision_disposition":"WRITE_OVERWRITE"},
                {"record_identity":format!("current-record/{generation}/0"), "item_ordinal":1,
                    "relative_path":"20261106-doc-002.hwpx","collision_disposition":"WRITE_NEW"}
            ]})
        );
        assert_eq!(fs::read_dir(output).unwrap().count(), 1);
        assert_eq!(fs::read(&conflict).unwrap(), b"existing");
        fs::remove_file(&conflict).unwrap();
        fs::create_dir(&conflict).unwrap();
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let panel = controller.snapshot().unwrap();
        let zone = &panel["workbench_observation"];
        assert_eq!(zone["primary_action"], "REVIEW_DELIVERY");
        assert_eq!(zone["delivery"]["resolvable"], false);
        let blocker = &zone["delivery"]["blockers"][0];
        assert_eq!(blocker["code"], "OUTPUT_PATH_NON_REGULAR_CONFLICT");
        assert_eq!(
            blocker["message"],
            "같은 이름의 폴더나 바로가기 등이 있어 덮어쓸 수 없습니다:"
        );
        assert_eq!(
            blocker["conflicting_relative_path"],
            "20261106-doc-001.hwpx"
        );
        let result = controller.generate(false, "directory-conflict").unwrap();
        assert_eq!(result["ok"], false);
        assert_eq!(result["error"], zone["create_action"]["disabled_reason"]);
        assert!(conflict.is_dir());
        assert_eq!(fs::read_dir(output).unwrap().count(), 1);
        fs::remove_dir(conflict).unwrap();
    }

    fn assert_restart_observation(controller: &JobController, csv: &Path, managed_template: &Path) {
        let registry = controller.registry.clone();
        let pool = controller.pool.clone();
        let change = controller.change.clone();
        let gate = controller.generation.clone();
        let settings_path = controller.settings_path.clone();
        let restarted = JobController::new(
            registry.clone(),
            pool.clone(),
            change.clone(),
            gate.clone(),
            settings_path.clone(),
            Arc::new(|_| {}),
        );
        assert_eq!(restarted.snapshot().unwrap(), json!({}));
        assert_eq!(restarted.initial().unwrap()["record_count"], 2);
        assert_eq!(restarted.initial().unwrap()["record_count"], 2);
        assert_eq!(
            restarted.snapshot().unwrap()["output_folder"],
            controller.snapshot().unwrap()["output_folder"]
        );
        let tutorial_data =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/tutorial/공고목록.xlsx");
        let mut reference = DatasetReference::new(
            "Saved filters",
            "excel",
            json!({"path":tutorial_data.to_string_lossy(),"sheet":"공고"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        reference.filters.push(FilterPreset {
            name: "소상공인".into(),
            state: json!({"columns":{"메모":{"text":"소상공인"}}})
                .as_object()
                .unwrap()
                .clone(),
        });
        pool.add(&reference).unwrap();
        let mut preset_job = Job {
            name: "Preset Hints".into(),
            template_path: managed_template.to_string_lossy().into_owned(),
            data_path: tutorial_data.to_string_lossy().into_owned(),
            data_sheet: "공고".into(),
            data_header_row: 1,
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("Name", "사업예산", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        preset_job.reviewed_rules = rules_fingerprints(&preset_job);
        registry.save(&mut preset_job, false).unwrap();
        controller.select_job("Preset Hints").unwrap();
        let filter = controller.data().unwrap().filter.unwrap();
        assert_eq!(filter.kind("사업예산").unwrap(), KIND_TEXT);
        assert_eq!(filter.presets()[0]["name"], "소상공인");
        assert_eq!(
            controller
                .dispatch("toggle_filter_preset", &json!({"name":"소상공인"}))
                .unwrap(),
            json!({"ok":true,"active":true})
        );
        assert_eq!(
            controller.dispatch("set_all", &json!({})).unwrap(),
            json!({"added":3})
        );
        fs::remove_file(csv).unwrap();
        let missing = JobController::new(
            registry,
            pool,
            change,
            gate,
            settings_path,
            Arc::new(|_| {}),
        );
        let failed = missing.initial().unwrap();
        assert_eq!(failed["record_count"], 0);
        assert!(
            failed["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains(&csv.to_string_lossy().to_string())
        );
        settings_store::mutate(&missing.settings_path, |settings| {
            settings.insert("last_output_directory".into(), json!(7));
        })
        .unwrap();
        let corrupt_key = JobController::new(
            missing.registry.clone(),
            missing.pool.clone(),
            missing.change.clone(),
            missing.generation.clone(),
            missing.settings_path.clone(),
            Arc::new(|_| {}),
        );
        assert_eq!(corrupt_key.remembered_output_directory().unwrap(), "");
        assert_eq!(
            corrupt_key.initial().unwrap()["output_folder"],
            json!({"directory":"","source":"","source_label":"","notice":""})
        );
    }

    fn assert_transition_lease(controller: &JobController) {
        // Onboarding may re-enter Job from the transition thread, while a concurrent
        // screen action must wait until the workspace switch finishes.
        std::thread::scope(|scope| {
            let (started_tx, started_rx) = std::sync::mpsc::channel();
            let (finished_tx, finished_rx) = std::sync::mpsc::channel();
            let controller_ref = &controller;
            controller
                .with_transition_lease(|| {
                    controller.browse(None, Some("transition")).unwrap();
                    scope.spawn(move || {
                        started_tx.send(()).unwrap();
                        controller_ref.browse(None, Some("later")).unwrap();
                        finished_tx.send(()).unwrap();
                    });
                    started_rx.recv().unwrap();
                    assert!(
                        finished_rx
                            .recv_timeout(std::time::Duration::from_millis(30))
                            .is_err()
                    );
                    assert_eq!(controller.state().unwrap().browse_query, "transition");
                })
                .unwrap();
            finished_rx
                .recv_timeout(std::time::Duration::from_secs(1))
                .unwrap();
            assert_eq!(controller.state().unwrap().browse_query, "later");
        });
    }

    #[test]
    fn job_selection_mounts_bound_data_and_generation_excludes_a_swap() {
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!(
                "hwpx-job-controller-{}",
                uuid::Uuid::new_v4().simple()
            ));
        let templates = sandbox.join("templates");
        fs::create_dir_all(&templates).unwrap();
        let csv = sandbox.join("records.csv");
        fs::write(&csv, "name\nfirst\nsecond\n").unwrap();
        let registry =
            Arc::new(JobRegistry::new(sandbox.join("jobs"), move || templates.clone()).unwrap());
        let mut job = Job {
            name: "Bound".into(),
            template_path: "C:/outside/unsupported.bin".into(),
            data_path: csv.to_string_lossy().into_owned(),
            data_header_row: 1,
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let pool = Arc::new(DatasetPoolRegistry::new(sandbox.join("datasets")).unwrap());
        let change = Arc::new(
            TemplateChangeCoordinator::new(&sandbox.join("authority"), registry.clone(), || {
                "2026-11-05T10:00:00".into()
            })
            .unwrap(),
        );
        let gate = Arc::new(GenerationGate::new());
        let settings_path = sandbox.join("settings.json");
        fs::write(&settings_path, r#"{"last_output_directory":"C:/saved"}"#).unwrap();
        let now = Arc::new(Mutex::new(
            chrono::NaiveDateTime::parse_from_str("2026-11-06T23:59:59", "%Y-%m-%dT%H:%M:%S")
                .unwrap(),
        ));
        let panel_clock = now.clone();
        let (push_gate, pushes) = artifact::tests::observation_push_gate(&sandbox);
        let controller = Arc::new(
            JobController::new(
                registry.clone(),
                pool.clone(),
                change.clone(),
                gate.clone(),
                settings_path.clone(),
                Arc::new(|_| {}),
            )
            .with_clock(move || *panel_clock.lock().unwrap())
            .with_push_gate(push_gate),
        );
        assert_compiled_template_identity(&controller, &sandbox);
        assert_eq!(
            controller.remembered_output_directory().unwrap(),
            "C:/saved"
        );
        fs::remove_file(&settings_path).unwrap();
        fs::create_dir(&settings_path).unwrap();
        assert!(controller.set_output_folder("C:/chosen").is_err());
        assert_eq!(
            controller.remembered_output_directory().unwrap(),
            "C:/chosen"
        );
        fs::remove_dir(&settings_path).unwrap();
        fs::write(&settings_path, r#"{"last_output_directory":"C:/saved"}"#).unwrap();
        assert_eq!(controller.snapshot().unwrap()["job_name"], "");
        assert_eq!(controller.snapshot().unwrap()["has_job"], false);
        assert!(controller.snapshot().unwrap()["workbench_observation"].is_null());
        assert_eq!(
            controller
                .dispatch("recover_record_issue", &json!({"target":null}))
                .unwrap_err()
                .message,
            "문제 위치 정보가 올바르지 않습니다."
        );
        assert_eq!(
            controller
                .dispatch("recover_record_issue", &json!({"target":{}}))
                .unwrap_err()
                .message,
            "현재 데이터 확인 결과가 없습니다. 다시 확인해 주세요."
        );
        controller.load_data_path(&csv, None, 0).unwrap();
        assert_eq!(controller.data().unwrap().header_row, 0);
        let panel = controller.refresh_panel().unwrap();
        assert_eq!(panel["job_name"], "");
        assert_eq!(panel["record_count"], 2);
        assert_eq!(panel["records"][0]["index"], 1);
        assert_eq!(panel["records"][0]["summary"], "second");
        assert_eq!(
            controller.dispatch("set_all", &json!({})).unwrap(),
            json!({"added":2})
        );
        assert_eq!(
            controller.dispatch("set_none", &json!({})).unwrap(),
            Value::Null
        );
        controller
            .dispatch("toggle_record", &json!({"index":"1","value":true}))
            .unwrap();
        assert_eq!(controller.data().unwrap().selection.selected_count(), 1);
        assert_eq!(
            controller.remount_data(false).unwrap()["needs_confirm"],
            true
        );
        assert_eq!(controller.data().unwrap().selection.selected_count(), 1);
        controller
            .dispatch("filter_search", &json!({"text":0}))
            .unwrap();
        assert_eq!(
            controller.data().unwrap().filter.unwrap().search_text(),
            "0"
        );
        controller.dispatch("set_none", &json!({})).unwrap();
        controller.select_job("Bound").unwrap();
        assert_eq!(controller.selected_job_name().unwrap(), "Bound");
        let cell_target;
        let row_target;
        {
            let mut state = controller.state().unwrap();
            state.data.selection.toggle(1, Some(true)).unwrap();
            let generation = state.data.snapshot_generation;
            cell_target = json!({"target_kind":"cell","snapshot_generation":generation,
                "record_identity":format!("current-record/{generation}/1"),"model_index":1,"field_id":"name"});
            row_target = json!({"target_kind":"row","snapshot_generation":generation,
                "record_identity":format!("current-record/{generation}/1"),"model_index":1,"field_id":"missing"});
            state.panel_snapshot = json!({"workbench_observation":{"record_validation":{"issues":[
                {"recovery_target":cell_target},{"recovery_target":row_target}
            ]}}});
            let plan = crate::current_execution_preparation::tests::source_plan();
            state.record_preparation_plan = Some(("Bound".into(), plan.clone()));
            state.fresh_observation = Some(FreshExecutionObservation::Sealed(Box::new(
                CurrentSealedPlanObservation {
                    sealed_plan_value: plan,
                    runtime_policy_admission: RuntimePolicyAdmission {
                        state: String::new(),
                        reasons: Vec::new(),
                    },
                    observed_at: String::new(),
                    current_field_binding: None,
                },
            )));
            state.orchestration = hwpx_filler::workbench_execution_status::CURRENT.into();
        }
        assert_eq!(
            controller
                .dispatch("recover_record_issue", &json!({"target":cell_target}))
                .unwrap(),
            json!({"ok":true,"element_id":"jobCell-1-0","fallback_element_id":"jobRow-1"})
        );
        assert_eq!(
            controller
                .dispatch("recover_record_issue", &json!({"target":row_target}))
                .unwrap(),
            json!({"ok":true,"element_id":"jobRow-1","fallback_element_id":"jobRow-1"})
        );
        controller.state().unwrap().data.snapshot_generation += 1;
        assert!(
            controller
                .dispatch("recover_record_issue", &json!({"target":cell_target}))
                .unwrap_err()
                .message
                .contains("다시 확인해 주세요")
        );
        controller.state().unwrap().data.snapshot_generation -= 1;
        controller
            .state()
            .unwrap()
            .data
            .hidden_columns
            .insert("name".into());
        assert!(
            controller
                .dispatch("recover_record_issue", &json!({"target":cell_target}))
                .unwrap_err()
                .message
                .contains("숨겨져")
        );
        controller.state().unwrap().data.hidden_columns.clear();
        controller
            .state()
            .unwrap()
            .data
            .filter
            .as_mut()
            .unwrap()
            .set_search("없는 행");
        assert!(
            controller
                .dispatch("recover_record_issue", &json!({"target":cell_target}))
                .unwrap_err()
                .message
                .contains("검색 결과")
        );
        {
            let mut state = controller.state().unwrap();
            state.data.selection.set_none();
            state.data.filter.as_mut().unwrap().set_search("");
            state.record_preparation_plan = None;
            state.fresh_observation = None;
            state.orchestration = hwpx_filler::workbench_execution_status::NO_EVIDENCE.into();
        }
        let data = controller.data().unwrap();
        assert_eq!(data.records.len(), 2);
        assert_eq!(data.selection.selected_count(), 0);
        assert_eq!(controller.transition_basis().unwrap()[2], 2);
        assert_non_hwpx_generation_refuses(&controller);
        assert_transition_lease(&controller);
        let run = gate.begin().unwrap().unwrap();
        assert_eq!(
            controller.select_job("").unwrap_err().to_string(),
            "문서 생성이 진행 중입니다. 끝난 뒤에 작업을 전환하세요."
        );
        assert_eq!(controller.with_editor_save_guard(|| 1).unwrap(), None);
        run.finish();
        assert_eq!(
            controller.rename_job("Bound", "Renamed").unwrap()["ok"],
            true
        );
        assert_eq!(controller.selected_job_name().unwrap(), "Renamed");
        assert!(registry.exists("Renamed"));
        controller.select_job("").unwrap();
        assert_eq!(controller.selected_job_name().unwrap(), "");
        assert_eq!(controller.data().unwrap().records.len(), 2);
        artifact::tests::assert_artifact_observation(&controller, &sandbox, &pushes);
        let (managed_template, output) =
            assert_managed_delivery(&controller, &registry, &sandbox, &csv, &now);
        assert_eq!(
            controller.rename_job("Managed", "Managed Renamed").unwrap()["ok"],
            true
        );
        let renamed = controller.refresh_panel().unwrap();
        assert_eq!(renamed["job_name"], "Managed Renamed");
        assert_eq!(
            renamed["workbench_observation"]["execution_status_code"],
            hwpx_filler::workbench_execution_status::NO_EVIDENCE
        );
        assert_eq!(
            controller.remount_data(false).unwrap()["needs_confirm"],
            true
        );
        fs::write(&csv, "name\n123\n456\n").unwrap();
        assert_eq!(controller.remount_data(true).unwrap()["ok"], true);
        assert_eq!(
            controller
                .data()
                .unwrap()
                .filter
                .as_ref()
                .unwrap()
                .kind("name")
                .unwrap(),
            KIND_TEXT
        );
        let delivered_before = std::fs::read_dir(&output)
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect::<std::collections::BTreeSet<_>>();
        let stale_run = controller.generate(false, "after-remount").unwrap();
        assert_eq!(stale_run["ok"], false);
        assert_eq!(
            std::fs::read_dir(&output)
                .unwrap()
                .map(|entry| entry.unwrap().file_name())
                .collect::<std::collections::BTreeSet<_>>(),
            delivered_before
        );
        let remembered: Value = serde_json::from_slice(&fs::read(&settings_path).unwrap()).unwrap();
        assert_eq!(remembered["last_data_source"]["header_row"], 0);
        assert_eq!(
            remembered["last_data_source"]["path"],
            csv.to_string_lossy().as_ref()
        );
        assert_remembered_mount_preserves_settings_and_reports_write_failure(&controller);
        assert_damaged_binding_keeps_recovery_visible(&controller, &registry, "Managed Renamed");
        assert_restart_observation(&controller, &csv, &managed_template);
        assert_refresh_preserves_unreadable_selection(&controller, &registry);
        fs::write(&csv, "name\nfirst\nsecond\n").unwrap();
        data_transitions::assert_mount_contracts(&controller, &registry, &sandbox, &csv);
        fs::remove_dir_all(sandbox).unwrap();
    }

    fn assert_remembered_mount_preserves_settings_and_reports_write_failure(
        controller: &JobController,
    ) {
        let original_data = controller.data().unwrap();
        let original_memory = controller.state().unwrap().remembered_data_source.clone();
        let original_bytes = fs::read(&controller.settings_path).unwrap();
        settings_store::mutate(&controller.settings_path, |settings| {
            settings.insert("theme".into(), json!("dark"));
        })
        .unwrap();
        for (source, path, sheet, header_row, pool_key) in [
            ("file", "C:/d/발주.xlsx", "7월", 2, ""),
            ("pool", "", "", 0, "slot-7"),
            ("pclm", "C:/d/pclm.db", "v_통합_v1", 0, ""),
        ] {
            {
                let mut state = controller.state().unwrap();
                state.data.source_kind = source.into();
                state.data.path = path.into();
                state.data.sheet = sheet.into();
                state.data.header_row = header_row;
                state.data.pool_key = pool_key.into();
            }
            controller.remember_current_data_source().unwrap();
            let stored =
                settings_store::read_with_alert(&controller.settings_path, |_| {}).unwrap();
            let expected = json!({"source":source,"path":path,"sheet":sheet,"header_row":header_row,"pool_key":pool_key});
            assert_eq!(stored["last_data_source"], expected);
            assert_eq!(stored["theme"], "dark");
            assert_eq!(
                controller.state().unwrap().remembered_data_source,
                Some(expected)
            );
        }
        let committed = controller.state().unwrap().remembered_data_source.clone();
        let committed_bytes = fs::read(&controller.settings_path).unwrap();
        controller.state().unwrap().data.source_kind.clear();
        controller.remember_current_data_source().unwrap();
        assert_eq!(
            fs::read(&controller.settings_path).unwrap(),
            committed_bytes
        );
        for (source, path, sheet, pool_key) in [
            ("registry", "p", "s", "k"),
            ("file", " \u{1c}\t", "", ""),
            ("pool", "", "", "  "),
            ("pclm", "p", "  ", ""),
            ("pclm", "  ", "s", ""),
        ] {
            {
                let mut state = controller.state().unwrap();
                state.data.source_kind = source.into();
                state.data.path = path.into();
                state.data.sheet = sheet.into();
                state.data.pool_key = pool_key.into();
            }
            assert!(
                controller.remember_current_data_source().is_err(),
                "{source}: {path:?}"
            );
            assert_eq!(
                fs::read(&controller.settings_path).unwrap(),
                committed_bytes
            );
            assert_eq!(
                controller.state().unwrap().remembered_data_source,
                committed
            );
        }
        let mounted = json!({"source":original_data.source_kind,"path":original_data.path,
            "sheet":original_data.sheet,"header_row":original_data.header_row,"pool_key":original_data.pool_key});
        controller.state().unwrap().data = original_data;
        fs::write(&controller.settings_path, [0xff]).unwrap();
        assert!(controller.remember_current_data_source().is_err());
        assert_eq!(
            controller.state().unwrap().remembered_data_source,
            Some(mounted)
        );
        assert_eq!(fs::read(&controller.settings_path).unwrap(), [0xff]);
        fs::write(&controller.settings_path, original_bytes).unwrap();
        controller.state().unwrap().remembered_data_source = original_memory;
    }

    fn assert_damaged_binding_keeps_recovery_visible(
        controller: &JobController,
        registry: &JobRegistry,
        work_ref: &str,
    ) {
        let original = registry.load(work_ref).unwrap().mapping;
        controller.dispatch("set_all", &json!({})).unwrap();
        registry
            .mutate(work_ref, |job| job.mapping.mappings.clear())
            .unwrap();
        controller.after_mapping_saved(work_ref).unwrap();
        let blocked = controller.refresh_panel().unwrap();
        assert_eq!(
            blocked["workbench_observation"]["primary_action"],
            "REVIEW_BINDING"
        );
        let mut duplicate = original.mappings[0].clone();
        duplicate.source = "another-column".into();
        registry
            .mutate(work_ref, |job| {
                job.mapping = original.clone();
                job.mapping.mappings.push(duplicate);
            })
            .unwrap();
        let error = controller
            .seal_service()
            .unwrap()
            .current_binding_review(work_ref)
            .unwrap_err();
        let panel = controller
            .refresh_panel()
            .expect("binding integrity failure must keep the panel usable");
        let zone = &panel["workbench_observation"];
        assert_eq!(zone["supported"], true);
        assert_eq!(zone["kind"], "context_error");
        assert_eq!(zone["code"], "FIELD_BINDING_INPUT_INTEGRITY_ERROR");
        assert_eq!(zone["detail"], error.detail);
        assert_eq!(zone["user_fixable"], false);
        assert_eq!(zone["primary_action"], "RECOVER_CONTEXT");
        assert_eq!(zone["create_action"]["enabled"], false);
        assert!(panel["output_folder"].is_object());
        assert!(zone.get("output_folder").is_none());
        registry
            .mutate(work_ref, |job| job.mapping = original)
            .unwrap();
        controller.after_mapping_saved(work_ref).unwrap();
        assert_ne!(
            controller.refresh_panel().unwrap()["workbench_observation"]["kind"],
            "context_error"
        );
    }

    #[test]
    fn registered_contract_source_restores_once_without_replacing_remembered_data() {
        use crate::registered_contract_data::registered_data_source;
        use std::sync::atomic::{AtomicUsize, Ordering};

        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("hwpx-registered-{}", uuid::Uuid::new_v4().simple()));
        fs::create_dir_all(&sandbox).unwrap();
        let db = sandbox.join("registered.pclm");
        let connection = rusqlite::Connection::open(&db).unwrap();
        connection
            .execute_batch(
                "CREATE TABLE pclm_file(singleton INTEGER, role TEXT, dataset_id TEXT);
                INSERT INTO pclm_file VALUES(1,'work','source-id');
                CREATE VIEW v_통합 AS SELECT 1 AS 항목;
                CREATE VIEW v_접수 AS SELECT 1 AS 항목;
                CREATE VIEW v_공고 AS SELECT 1 AS 항목;
                CREATE VIEW v_계약 AS SELECT 1 AS 항목;",
            )
            .unwrap();
        drop(connection);
        let located = crate::registered_contract_data::tests::assert_registered_workfile_pointer(
            &sandbox, &db,
        );

        let templates = sandbox.join("templates");
        let jobs =
            Arc::new(JobRegistry::new(sandbox.join("jobs"), move || templates.clone()).unwrap());
        let pool = Arc::new(DatasetPoolRegistry::new(sandbox.join("datasets")).unwrap());
        let change = Arc::new(
            TemplateChangeCoordinator::new(&sandbox.join("authority"), jobs.clone(), || {
                "2026-11-05T10:00:00".into()
            })
            .unwrap(),
        );
        let gate = Arc::new(GenerationGate::new());
        let calls = Arc::new(AtomicUsize::new(0));
        let source = {
            let pool = pool.clone();
            let located = located.clone();
            let calls = calls.clone();
            move || {
                calls.fetch_add(1, Ordering::SeqCst);
                registered_data_source(&pool, Some(located.clone()))
            }
        };
        let settings = sandbox.join("settings.json");
        let controller = JobController::new(
            jobs.clone(),
            pool.clone(),
            change.clone(),
            gate.clone(),
            settings.clone(),
            Arc::new(|_| {}),
        )
        .with_registered_data(source);
        let first = controller.initial().unwrap();
        assert_eq!(first["record_count"], 1);
        assert_eq!(controller.data().unwrap().source_kind, "pool");
        assert_eq!(controller.data().unwrap().sheet, "v_통합");
        assert_eq!(first["data_sheet_tabs"].as_array().unwrap().len(), 4);
        assert_eq!(first["data_sheet_tabs"][0]["active"], true);
        assert_eq!(first["data_sheet_tabs"][1]["active"], false);
        assert_eq!(pool.list_entries(None).unwrap().len(), 1);
        assert_eq!(
            registered_data_source(&pool, Some(located.clone()))
                .unwrap()
                .unwrap()["pool_key"],
            pool.list_entries(None).unwrap()[0].0,
        );
        controller.initial().unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), 1);

        let remembered =
            JobController::new(jobs, pool.clone(), change, gate, settings, Arc::new(|_| {}))
                .with_registered_data(|| Err("broken registered source".into()));
        let restored = remembered.initial().unwrap();
        assert_eq!(restored["record_count"], 1);
        assert!(
            restored["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("broken registered source")
        );
        let broken = JobController::new(
            remembered.registry.clone(),
            pool.clone(),
            remembered.change.clone(),
            remembered.generation.clone(),
            sandbox.join("empty-settings.json"),
            Arc::new(|_| {}),
        )
        .with_registered_data(|| Err("broken registered source".into()));
        let refused = broken.initial().unwrap();
        assert_eq!(refused["record_count"], 0);
        assert!(
            refused["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("broken registered source")
        );
        let key = pool.list_entries(None).unwrap()[0].0.clone();
        controller.load_pool(&key, Some("v_접수")).unwrap();
        let switched = controller.snapshot().unwrap();
        assert_eq!(switched["data_sheet_tabs"][1]["active"], true);
        assert_eq!(pool.load(&key).unwrap().opts["view"], "v_통합");
        assert!(controller.load_pool(&key, Some("미등록")).is_err());
        assert_eq!(controller.data().unwrap().sheet, "v_접수");
        pool.commands().archive(&key).unwrap();
        assert_eq!(registered_data_source(&pool, Some(located)).unwrap(), None);
        assert_eq!(pool.list_entries(None).unwrap().len(), 1);
        fs::remove_dir_all(sandbox).unwrap();
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod data_transitions {
    use super::*;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use std::fs;

    pub(super) fn assert_mount_contracts(
        controller: &JobController,
        registry: &JobRegistry,
        sandbox: &Path,
        csv: &Path,
    ) {
        assert_data_remount_keeps_only_the_exact_seated_work(controller, registry, csv);
        assert_preferred_work_is_restated_once_after_mount(controller, registry, sandbox, csv);
        assert_candidates_and_browse_share_the_bound_work_set(controller, registry, sandbox, csv);
    }

    fn assert_candidates_and_browse_share_the_bound_work_set(
        controller: &JobController,
        registry: &JobRegistry,
        sandbox: &Path,
        csv: &Path,
    ) {
        controller.load_data_path(csv, None, 1).unwrap();
        assert_eq!(controller.snapshot().unwrap()["candidates"]["txt_note"], "");
        let template = sandbox.join("templates/onboarding.txt");
        fs::write(&template, "{{name}}\n").unwrap();
        assert!(
            controller.refresh_panel().unwrap()["candidates"]["txt_note"]
                .as_str()
                .unwrap()
                .contains("＋ 새 작업")
        );
        let mut available = Job {
            name: "Available".into(),
            template_path: template.to_string_lossy().into_owned(),
            data_path: csv.to_string_lossy().into_owned(),
            data_header_row: 1,
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("name", "name", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        registry.save(&mut available, false).unwrap();
        let mut needs = available.clone();
        needs.name = "Needs".into();
        needs.mapping.mappings[0].source = "없는열".into();
        registry.save(&mut needs, false).unwrap();
        controller.load_data_path(csv, None, 1).unwrap();
        let snapshot = controller.snapshot().unwrap();
        assert_eq!(snapshot["candidates"]["txt_note"], "");
        assert_eq!(snapshot["candidates"]["top"][0]["name"], "Available");
        assert_eq!(snapshot["candidates"]["needs_count"], 1);
        controller
            .browse(Some("needs_action"), Some("Needs"))
            .unwrap();
        let browse = controller.refresh_panel().unwrap();
        assert_eq!(browse["browse"]["tab"], "needs_action");
        assert_eq!(browse["browse"]["rows"][0]["name"], "Needs");
        assert_eq!(browse["browse"]["rows"][0]["missing"], json!(["없는열"]));
        assert_eq!(browse["browse"]["available_count"], 1);
    }

    fn assert_data_remount_keeps_only_the_exact_seated_work(
        controller: &JobController,
        registry: &JobRegistry,
        csv: &Path,
    ) {
        controller.select_job("Managed Renamed").unwrap();
        controller.load_data_path(csv, None, 0).unwrap();
        assert_eq!(controller.selected_job_name().unwrap(), "Managed Renamed");
        controller
            .state()
            .unwrap()
            .seated
            .as_mut()
            .unwrap()
            .application_id = Some("stale".into());
        controller.load_data_path(csv, None, 0).unwrap();
        assert_eq!(controller.selected_job_name().unwrap(), "");
        assert!(
            controller.snapshot().unwrap()["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("같은 작업인지 확인할 수 없어")
        );
        controller.select_job("Managed Renamed").unwrap();
        registry
            .mutate("Managed Renamed", |job| {
                job.filename_pattern = "외부-{{seq:001}}".into();
            })
            .unwrap();
        controller.load_data_path(csv, None, 0).unwrap();
        assert_eq!(controller.selected_job_name().unwrap(), "");
        assert!(
            controller.snapshot().unwrap()["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("같은 작업인지 확인할 수 없어")
        );
    }

    fn assert_preferred_work_is_restated_once_after_mount(
        controller: &JobController,
        registry: &JobRegistry,
        sandbox: &Path,
        csv: &Path,
    ) {
        let template = sandbox.join("legacy.txt");
        fs::write(&template, "{{name}}\n").unwrap();
        let mut legacy = Job {
            name: "Legacy".into(),
            template_path: template.to_string_lossy().into_owned(),
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("name", "name", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        registry.save(&mut legacy, false).unwrap();
        controller.select_job("").unwrap();
        controller.state().unwrap().data = MountedData::default();
        assert_eq!(
            controller.prefer_work("Legacy").unwrap()["reason"],
            "no_binding"
        );
        controller.load_data_path(csv, None, 1).unwrap();
        let usable = controller.snapshot().unwrap();
        assert_eq!(usable["job_name"], "");
        assert_eq!(usable["data_notice"]["level"], "ok");
        assert!(
            usable["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("이 데이터로 쓸 수 있습니다")
        );
        assert_eq!(controller.state().unwrap().preferred, "");

        registry
            .mutate("Legacy", |job| {
                job.mapping.mappings[0].source = "없는열".into()
            })
            .unwrap();
        assert_eq!(
            controller.prefer_work("Legacy").unwrap()["reason"],
            "incompatible"
        );
        controller.load_data_path(csv, None, 1).unwrap();
        let incompatible = controller.snapshot().unwrap();
        assert_eq!(incompatible["job_name"], "");
        assert_eq!(incompatible["data_notice"]["level"], "warn");
        assert!(
            incompatible["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("구조가 맞지 않습니다")
        );
        assert_eq!(controller.state().unwrap().preferred, "");

        controller.select_job("Managed Renamed").unwrap();
        assert_eq!(
            controller.prefer_work("Legacy").unwrap()["reason"],
            "incompatible"
        );
        let matching = sandbox.join("matching.csv");
        fs::write(&matching, "없는열\n맞는 데이터\n").unwrap();
        controller.load_data_path(&matching, None, 1).unwrap();
        let combined = controller.snapshot().unwrap();
        assert_eq!(combined["job_name"], "");
        let text = combined["data_notice"]["text"].as_str().unwrap();
        assert!(text.contains("다른 데이터에 연결돼 있어"), "{text}");
        assert!(text.contains("이 데이터로 쓸 수 있습니다"), "{text}");
        assert_eq!(combined["data_notice"]["level"], "warn");
        assert_eq!(controller.state().unwrap().preferred, "");

        controller.state().unwrap().data = MountedData::default();
        assert_eq!(
            controller.prefer_work("Legacy").unwrap()["reason"],
            "no_binding"
        );
        let backup = sandbox.join("jobs-held");
        fs::rename(registry.directory(), &backup).unwrap();
        fs::write(registry.directory(), b"not a directory").unwrap();
        controller.load_data_path(csv, None, 1).unwrap();
        let unreadable = controller.snapshot().unwrap();
        assert_eq!(unreadable["record_count"], 2);
        assert_eq!(unreadable["data_notice"]["level"], "warn");
        let text = unreadable["data_notice"]["text"].as_str().unwrap();
        assert!(
            text.contains("고른 'Legacy' 작업을 다시 확인할 수 없습니다"),
            "{text}"
        );
        assert!(
            text.contains("문서 작업 목록을 다시 확인할 수 없습니다"),
            "{text}"
        );
        assert_eq!(controller.state().unwrap().preferred, "");
        fs::remove_file(registry.directory()).unwrap();
        fs::rename(&backup, registry.directory()).unwrap();
        let recovered = controller.refresh_panel().unwrap();
        assert!(
            !recovered["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("문서 작업 목록을 다시 확인할 수 없습니다")
        );

        controller.prefer_work("Legacy").unwrap();
        registry.delete("Legacy").unwrap();
        controller.load_data_path(csv, None, 1).unwrap();
        let removed = controller.snapshot().unwrap();
        assert_eq!(removed["job_name"], "");
        assert!(
            removed["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("더는 없습니다")
        );
        assert_eq!(controller.state().unwrap().preferred, "");
    }
}
