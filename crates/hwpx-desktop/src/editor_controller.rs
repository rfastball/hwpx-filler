//! Native editor screen over a single mutable mapping session.

use crate::action_registry::validate_dispatch;
use crate::dataset_registry::DatasetPoolRegistry;
use crate::dataset_registry::PoolError;
use crate::editor_intake::read_template_intake;
use crate::editor_projection::{self, EditorSnapshotFacts};
use crate::generation_gate::GenerationGate;
use crate::job_registry::{JobRegistry, StoreError};
use crate::library_observation::read_template;
use crate::library_observation::template_display_name;
use crate::nara_source::source_from_pool_reference_live;
use crate::template_inventory::discover_paths;
use crate::template_root::TemplateRoot;
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use chrono::{Local, NaiveDateTime};
use hwpx_filler::data_factory::{binding_for_reference, source_for_binding, source_for_path};
use hwpx_filler::dataset_pool::DatasetPoolRow;
use hwpx_filler::dataset_reference::{
    excel_identity, pclm_identity, reference_for_sheet, reference_sheets,
};
use hwpx_filler::editor_mapping::EditorMappingModel;
use hwpx_filler::editor_save_policy::{build_provenance, derive_job_name, validate_save};
use hwpx_filler::editor_session_state::{
    EditorSessionState, SECTION_BINDING, SECTION_FILENAME, SECTION_TEMPLATE, SECTIONS,
    editor_context, restore_report_lines,
};
use hwpx_filler::editor_slice::slice_query;
use hwpx_filler::job::{Job, template_media};
use hwpx_filler::job_binding_projection::mapping_rules;
use hwpx_filler::mapping_state::profile_source_vocabulary;
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};

mod actions;
mod facts;
mod restore;
mod save;
mod session;

type Clock = dyn Fn() -> NaiveDateTime + Send + Sync;
type BindingPending = dyn Fn(&str) -> Result<bool, GraphError> + Send + Sync;
type AfterMappingSaved = dyn Fn(&str) -> Result<(), GraphError> + Send + Sync;
type SavedNotification = dyn Fn(&Job) -> Result<(), GraphError> + Send + Sync;
type OutputDirectory = dyn Fn() -> Result<String, GraphError> + Send + Sync;

struct LoadedEditorData {
    path: String,
    sheet: String,
    header_row: u64,
    kind: String,
    fields: Vec<String>,
    records: Vec<Map<String, Value>>,
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod reconcile_tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    #[test]
    fn template_reconcile_reloads_txt_schema_and_drops_stale_rows() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("reconcile-{}", uuid::Uuid::new_v4()));
        let (editor, _, _, _graph) = tests::fixture(&root);
        let template = root.join("text_templates/기안.txt");
        let other = root.join("text_templates/남의.txt");
        let data = root.join("data.csv");
        fs::write(&template, "수신: {{수신}}\n").unwrap();
        fs::write(&other, "남의 {{필드}}\n").unwrap();
        fs::write(&data, "수신\n홍길동\n").unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        editor.load_data_path(&data, None, 1).unwrap();
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        let index = editor.snapshot().unwrap()["rows"][0]["index"].clone();
        editor
            .dispatch("set_const", &json!({"index":index,"const":"총무과"}))
            .unwrap();
        editor
            .dispatch("set_confirmed", &json!({"index":index,"confirmed":true}))
            .unwrap();
        let before = editor.snapshot().unwrap();
        editor
            .reconcile_template_mutation("mutated", &other)
            .unwrap();
        assert_eq!(editor.snapshot().unwrap(), before);
        assert!(
            editor
                .reconcile_template_mutation("moved", &template)
                .is_err()
        );

        fs::write(&template, "수신: {{수신}}\n담당: {{담당}}\n").unwrap();
        editor
            .reconcile_template_mutation("mutated", &template)
            .unwrap();
        let grown = editor.snapshot().unwrap();
        assert_eq!(
            grown["rows"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| item["template_field"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["수신", "담당"]
        );
        assert_eq!(grown["rows"][0]["const"], "총무과");
        assert_eq!(grown["rows"][0]["confirmed"], false);
        assert_eq!(grown["notice"]["level"], "warn");

        fs::write(&template, "토큰 없는 안내문\n").unwrap();
        editor
            .reconcile_template_mutation("mutated", &template)
            .unwrap();
        let raw = editor.snapshot().unwrap();
        assert_eq!(raw["rows"], json!([]));
        assert_ne!(raw["raw_block"], "");
        assert_eq!(raw["notice"]["level"], "danger");
        fs::remove_dir_all(root).unwrap();
    }
}

pub struct EditorController {
    jobs: Arc<JobRegistry>,
    templates: Arc<TemplateRoot>,
    datasets: Arc<DatasetPoolRegistry>,
    push: PushGate,
    clock: Arc<Clock>,
    generation_gate: Option<Arc<GenerationGate>>,
    binding_pending: Option<Arc<BindingPending>>,
    after_mapping_saved: Option<Arc<AfterMappingSaved>>,
    saved_notification: Option<Arc<SavedNotification>>,
    output_directory: Option<Arc<OutputDirectory>>,
    state: Mutex<EditorSessionState>,
    prepared: Mutex<Value>,
    push_serial: Mutex<()>,
}

impl EditorController {
    pub fn new(
        jobs: Arc<JobRegistry>,
        templates: Arc<TemplateRoot>,
        datasets: Arc<DatasetPoolRegistry>,
        push: PushGate,
    ) -> Result<Self, GraphError> {
        Self::with_clock(jobs, templates, datasets, push, || {
            Local::now().naive_local()
        })
    }
    pub fn with_clock(
        jobs: Arc<JobRegistry>,
        templates: Arc<TemplateRoot>,
        datasets: Arc<DatasetPoolRegistry>,
        push: PushGate,
        clock: impl Fn() -> NaiveDateTime + Send + Sync + 'static,
    ) -> Result<Self, GraphError> {
        let controller = Self {
            jobs,
            templates,
            datasets,
            push,
            clock: Arc::new(clock),
            generation_gate: None,
            binding_pending: None,
            after_mapping_saved: None,
            saved_notification: None,
            output_directory: None,
            state: Mutex::new(EditorSessionState::default()),
            prepared: Mutex::new(Value::Null),
            push_serial: Mutex::new(()),
        };
        controller.refresh_panel()?;
        Ok(controller)
    }
    /// The graph must inject the same held generation fence used by managed runs.
    pub fn with_generation_gate(mut self, gate: Arc<GenerationGate>) -> Self {
        self.generation_gate = Some(gate);
        self
    }
    pub fn with_binding_pending(
        mut self,
        probe: impl Fn(&str) -> Result<bool, GraphError> + Send + Sync + 'static,
    ) -> Self {
        self.binding_pending = Some(Arc::new(probe));
        self
    }
    pub fn with_after_mapping_saved(
        mut self,
        callback: impl Fn(&str) -> Result<(), GraphError> + Send + Sync + 'static,
    ) -> Self {
        self.after_mapping_saved = Some(Arc::new(callback));
        self
    }
    pub fn with_saved_notification(
        mut self,
        callback: impl Fn(&Job) -> Result<(), GraphError> + Send + Sync + 'static,
    ) -> Self {
        self.saved_notification = Some(Arc::new(callback));
        self
    }
    pub fn with_output_directory(
        mut self,
        read: impl Fn() -> Result<String, GraphError> + Send + Sync + 'static,
    ) -> Self {
        self.output_directory = Some(Arc::new(read));
        self
    }
    fn state(&self) -> Result<MutexGuard<'_, EditorSessionState>, GraphError> {
        Ok(self.state.lock().map_err(|_| "editor session poisoned")?)
    }
    pub fn snapshot(&self) -> Result<Value, GraphError> {
        Ok(self
            .prepared
            .lock()
            .map_err(|_| "editor projection poisoned")?
            .clone())
    }
    pub fn refresh_panel(&self) -> Result<(), GraphError> {
        let state = self.state()?;
        let facts = self.facts(&state)?;
        let value = editor_projection::snapshot(&state, &facts)?;
        *self
            .prepared
            .lock()
            .map_err(|_| "editor projection poisoned")? = value;
        Ok(())
    }
    pub fn has_unsaved_work(&self) -> Result<bool, GraphError> {
        Ok(self.state()?.has_unsaved_work())
    }
    pub fn selected_job_name(&self) -> Result<Option<String>, GraphError> {
        Ok(self.state()?.base.as_ref().map(|job| job.name.clone()))
    }
    pub fn selected_template_path(&self) -> Result<String, GraphError> {
        Ok(self.state()?.template_path.clone())
    }
    pub fn selected_data_path(&self) -> Result<String, GraphError> {
        Ok(self.state()?.data_path.clone())
    }
    pub fn owned_session_paths(&self) -> Result<(String, String), GraphError> {
        let state = self.state()?;
        Ok((state.template_path.clone(), state.data_path.clone()))
    }
    fn push_snapshot(&self) -> Result<(), GraphError> {
        let _serial = self
            .push_serial
            .lock()
            .map_err(|_| "editor push poisoned")?;
        self.refresh_panel()?;
        self.push.push("editor", &self.snapshot()?)?;
        Ok(())
    }
}

impl ScreenController for EditorController {
    fn initial(&self) -> Result<Value, GraphError> {
        self.refresh_panel()?;
        self.snapshot()
    }
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        validate_dispatch("editor", action, payload)?;
        let result = self.dispatch_inner(action, payload)?;
        if !["preview_slice", "propose_slice"].contains(&action) {
            self.push_snapshot()?;
        }
        Ok(result)
    }
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        Ok(self
            .has_unsaved_work()?
            .then(|| "편집 중인 작업의 저장하지 않은 변경이 있습니다.".into()))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::locations::Locations;
    use crate::shell_settings::ShellSettings;
    use crate::workspace_switch::{WorkspaceGraph, WorkspaceSwitch};
    use hwpx_filler::data_contract_check::profile_data_contract;
    use hwpx_filler::dataset_reference::DatasetReference;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use std::fs;
    use std::path::PathBuf;
    use std::sync::Condvar;
    use std::time::{Duration, Instant};
    use std::time::{SystemTime, UNIX_EPOCH};

    pub(super) fn fixture(
        root: &Path,
    ) -> (
        Arc<EditorController>,
        Arc<JobRegistry>,
        Arc<DatasetPoolRegistry>,
        WorkspaceSwitch<()>,
    ) {
        let templates_dir = root.join("text_templates");
        fs::create_dir_all(&templates_dir).unwrap();
        let templates = Arc::new(
            TemplateRoot::new(
                Arc::new(ShellSettings::new(root.join("settings.json"), |_| {})),
                templates_dir.clone(),
            )
            .unwrap(),
        );
        let jobs =
            Arc::new(JobRegistry::new(root.join("jobs"), move || templates_dir.clone()).unwrap());
        let datasets = Arc::new(DatasetPoolRegistry::new(root.join("datasets")).unwrap());
        let capture = Arc::new(Mutex::new(None));
        let saved = capture.clone();
        let for_jobs = jobs.clone();
        let for_templates = templates.clone();
        let for_datasets = datasets.clone();
        let graph = WorkspaceSwitch::new(
            Locations::new(root, None),
            |_, _| Ok(None),
            move |home, push, token| {
                let editor = Arc::new(
                    EditorController::with_clock(
                        for_jobs.clone(),
                        for_templates.clone(),
                        for_datasets.clone(),
                        push,
                        || {
                            chrono::NaiveDate::from_ymd_opt(2026, 10, 15)
                                .unwrap()
                                .and_hms_opt(9, 0, 0)
                                .unwrap()
                        },
                    )?
                    .with_generation_gate(Arc::new(GenerationGate::new())),
                );
                *saved.lock().unwrap() = Some(editor.clone());
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("editor".into(), editor as Arc<dyn ScreenController>)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let editor = capture.lock().unwrap().as_ref().unwrap().clone();
        (editor, jobs, datasets, graph)
    }

    fn row<'a>(snapshot: &'a Value, name: &str) -> &'a Value {
        snapshot["rows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["template_field"] == name)
            .unwrap()
    }

    #[test]
    fn section_discard_keeps_name_and_data_until_whole_session_discard() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("discard-{}", uuid::Uuid::new_v4()));
        let (editor, _, _, _graph) = fixture(&root);
        let template = root.join("text_templates/기안.txt");
        let data = root.join("data.csv");
        let other = root.join("other.csv");
        fs::write(&template, "{{이름}}\n").unwrap();
        fs::write(&data, "이름\n홍길동\n").unwrap();
        fs::write(&other, "이름\n김철수\n").unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        editor.load_data_path(&data, None, 1).unwrap();
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        editor
            .dispatch("set_name", &json!({"name":"원래이름"}))
            .unwrap();
        assert_eq!(editor.dispatch("save", &json!({})).unwrap()["ok"], true);
        assert!(!editor.has_unsaved_work().unwrap());
        editor
            .dispatch("set_name", &json!({"name":"고친 이름"}))
            .unwrap();
        assert_eq!(editor.snapshot().unwrap()["dirty_sections"], json!([]));
        assert_eq!(editor.snapshot().unwrap()["dirty"], true);
        editor
            .dispatch("set_pattern", &json!({"pattern":"바꾼-{{seq}}"}))
            .unwrap();
        assert_eq!(
            editor.snapshot().unwrap()["dirty_sections"],
            json!(["filename"])
        );
        editor
            .dispatch("discard_patch", &json!({"section":"filename"}))
            .unwrap();
        assert_eq!(editor.snapshot().unwrap()["name"], "고친 이름");
        assert_eq!(
            editor.snapshot().unwrap()["pattern"],
            Job::default().filename_pattern
        );
        assert!(editor.has_unsaved_work().unwrap());
        editor.load_data_path(&other, None, 1).unwrap();
        assert_eq!(
            editor.snapshot().unwrap()["data_path"],
            other.to_string_lossy().as_ref()
        );
        let index = row(&editor.snapshot().unwrap(), "이름")["index"].clone();
        editor
            .dispatch("set_confirmed", &json!({"index":index,"confirmed":false}))
            .unwrap();
        editor
            .dispatch("discard_patch", &json!({"section":"binding"}))
            .unwrap();
        assert_eq!(
            editor.snapshot().unwrap()["data_path"],
            other.to_string_lossy().as_ref()
        );
        assert_eq!(editor.snapshot().unwrap()["dirty_sections"], json!([]));
        assert!(editor.has_unsaved_work().unwrap());
        assert!(
            editor
                .dispatch("discard_patch", &json!({"section":"test"}))
                .is_err()
        );
        editor.dispatch("discard_patch", &json!({})).unwrap();
        let restored = editor.snapshot().unwrap();
        assert_eq!(restored["name"], "원래이름");
        assert_eq!(restored["data_path"], data.to_string_lossy().as_ref());
        assert_eq!(restored["dirty"], false);
        assert!(
            restored["notice"]["text"]
                .as_str()
                .unwrap()
                .contains("연결된 것으로 되돌렸습니다")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn save_landing_reports_unreadable_binding_without_losing_the_commit() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("landing-{}", uuid::Uuid::new_v4()));
        let (editor, jobs, _, _graph) = fixture(&root);
        let template = root.join("text_templates/기안.txt");
        let data = root.join("data.csv");
        fs::write(&template, "{{이름}}\n").unwrap();
        fs::write(&data, "이름\n홍길동\n").unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        editor.load_data_path(&data, None, 1).unwrap();
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        editor
            .dispatch("set_name", &json!({"name":"사라진데이터작업"}))
            .unwrap();
        fs::remove_file(&data).unwrap();
        let result = editor.dispatch("save", &json!({})).unwrap();
        assert_eq!(result["ok"], true, "{result}");
        assert_eq!(
            jobs.load("사라진데이터작업").unwrap().data_path,
            data.to_string_lossy()
        );
        let notice = editor.snapshot().unwrap()["notice"].clone();
        assert_eq!(notice["level"], "warn");
        assert!(notice["text"].as_str().unwrap().contains("저장했습니다"));
        assert!(
            notice["text"]
                .as_str()
                .unwrap()
                .contains("다시 읽지 못했습니다")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cached_snapshot_and_registered_names_share_one_session_basis() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("projection-{}", uuid::Uuid::new_v4()));
        let (editor, jobs, pool, _graph) = fixture(&root);
        let prepared = editor.snapshot().unwrap();
        editor.state().unwrap().source_fields.push("새 열".into());
        assert_eq!(editor.snapshot().unwrap(), prepared);
        editor.refresh_panel().unwrap();
        assert_eq!(
            editor.snapshot().unwrap()["source_fields"],
            json!(["새 열"])
        );
        editor.dispatch("new_session", &json!({})).unwrap();
        let nested = root.join("text_templates/온나라");
        fs::create_dir_all(&nested).unwrap();
        let template = nested.join("기안.txt");
        let data = root.join("data.csv");
        fs::write(&template, "{{이름}}\n").unwrap();
        fs::write(&data, "이름\n홍길동\n").unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        let picked = editor.snapshot().unwrap();
        assert_eq!(picked["template_name"], "온나라/기안");
        assert_eq!(picked["name"], "기안");
        assert_eq!(picked["job_name_is_derived"], true);
        assert_eq!(picked["output_folder"], Value::Null);
        assert!(!editor.has_unsaved_work().unwrap());
        let item = DatasetReference::new(
            "7월 발주",
            "excel",
            json!({"path":data}).as_object().unwrap().clone(),
        )
        .unwrap();
        let key = pool.add(&item).unwrap();
        assert_eq!(
            editor
                .dispatch("use_pool_data", &json!({"key":key}))
                .unwrap()["ok"],
            true
        );
        let mounted = editor.snapshot().unwrap();
        assert_eq!(mounted["data_name"], "7월 발주");
        assert_eq!(mounted["name"], "기안 · 7월 발주");
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        editor
            .dispatch("set_name", &json!({"name":"사람이 지은 이름"}))
            .unwrap();
        assert_eq!(editor.snapshot().unwrap()["job_name_is_derived"], false);
        assert_eq!(editor.dispatch("save", &json!({})).unwrap()["ok"], true);
        assert_eq!(
            jobs.load("사람이 지은 이름").unwrap().mapping.provenance["dataset"],
            "7월 발주"
        );
        editor.load_job("사람이 지은 이름").unwrap();
        assert_eq!(editor.snapshot().unwrap()["data_name"], "7월 발주");
        assert_eq!(editor.snapshot().unwrap()["name"], "사람이 지은 이름");
        assert_eq!(editor.snapshot().unwrap()["schema_drift"], "");
        jobs.mutate("사람이 지은 이름", |job| {
            job.mapping
                .provenance
                .insert("template_fields".into(), json!("옛 필드"));
        })
        .unwrap();
        editor.load_job("사람이 지은 이름").unwrap();
        assert!(
            editor.snapshot().unwrap()["schema_drift"]
                .as_str()
                .unwrap()
                .contains("매핑 재검토")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn resuggest_actions_preserve_confirmed_rows_and_count_discarded_manual_values() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("resuggest-{}", uuid::Uuid::new_v4()));
        let (editor, _, _, _graph) = fixture(&root);
        let template = root.join("text_templates/기안.txt");
        let first = root.join("first.csv");
        let second = root.join("second.csv");
        fs::write(&template, "{{가}} {{나}}").unwrap();
        fs::write(&first, "가,나\n첫째,둘째\n").unwrap();
        fs::write(&second, "가,나\n셋째,넷째\n").unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        editor.load_data_path(&first, None, 1).unwrap();
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        let snap = editor.snapshot().unwrap();
        assert_eq!(row(&snap, "가")["confirmed"], true);
        assert_eq!(row(&snap, "나")["confirmed"], true);
        let first_index = row(&snap, "가")["index"].clone();
        let second_index = row(&snap, "나")["index"].clone();
        editor
            .dispatch(
                "set_display",
                &json!({"index":first_index,"type":"const","fmt":""}),
            )
            .unwrap();
        editor
            .dispatch(
                "set_const",
                &json!({"index":first_index,"const":"직접 입력한 값"}),
            )
            .unwrap();
        let stakes = editor.dispatch("mapping_reset_stakes", &json!({})).unwrap();
        assert_eq!(stakes["resuggest_manual"], 1);
        assert_eq!(stakes["confirmed"], 1);
        editor.load_data_path(&second, None, 1).unwrap();
        let carried = editor.snapshot().unwrap();
        assert_eq!(row(&carried, "가")["const"], "직접 입력한 값");
        assert_eq!(row(&carried, "가")["confirmed"], false);
        assert!(
            editor
                .dispatch("revert_source", &json!({"index":second_index}))
                .is_err()
        );
        let refreshed = editor.dispatch("resuggest_all", &json!({})).unwrap();
        assert_eq!(refreshed, json!({"resuggested":1,"kept_confirmed":1}));
        let snap = editor.snapshot().unwrap();
        assert_eq!(row(&snap, "가")["const"], "");
        assert_eq!(row(&snap, "가")["touched"], false);
        assert_eq!(row(&snap, "나")["confirmed"], true);
        editor
            .dispatch(
                "set_source",
                &json!({"index":first_index,"source":"없는열"}),
            )
            .unwrap();
        editor
            .dispatch("revert_source", &json!({"index":first_index}))
            .unwrap();
        assert_eq!(row(&editor.snapshot().unwrap(), "가")["source"], "가");
        assert_eq!(row(&editor.snapshot().unwrap(), "나")["confirmed"], true);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn received_contract_data_rejudges_rows_and_preserves_the_contract_on_save() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("contract-{}", uuid::Uuid::new_v4()));
        let (editor, jobs, _, _graph) = fixture(&root);
        let template = root.join("text_templates/공고.txt");
        fs::write(&template, "{{건명}} {{금액}} {{계약일}} {{담당}}").unwrap();
        let mapping = MappingProfile::new(
            "",
            vec![
                FieldMapping::new("건명", "공고명", "text", "", "", None).unwrap(),
                FieldMapping::new("금액", "추정가격", "amount", "", "", None).unwrap(),
                FieldMapping::new("계약일", "계약일자", "date", "", "", None).unwrap(),
                FieldMapping::new("담당", "", "const", "홍길동", "", None).unwrap(),
            ],
            Map::new(),
        )
        .unwrap();
        let sender = [
            json!({"공고명":"전산장비 구매","추정가격":"24750000","계약일자":"2026-06-15"})
                .as_object()
                .unwrap()
                .clone(),
            json!({"공고명":"사무용품","추정가격":"1,200,000원","계약일자":"2026-07-01"})
                .as_object()
                .unwrap()
                .clone(),
        ];
        let contract = profile_data_contract(&mapping, &sender).unwrap();
        let mut job = Job {
            name: "받은작업".into(),
            template_path: template.to_string_lossy().into(),
            mapping: mapping.clone(),
            data_contract: Some(contract.clone()),
            ..Job::default()
        };
        jobs.save(&mut job, false).unwrap();
        let no_contract = Job {
            name: "무계약".into(),
            data_contract: None,
            ..job.clone()
        };
        let mut no_contract = no_contract;
        jobs.save(&mut no_contract, false).unwrap();
        editor.load_job("받은작업").unwrap();
        assert_eq!(
            editor
                .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
                .unwrap()["human"],
            0
        );
        assert_eq!(
            editor
                .dispatch("mapping_reset_stakes", &json!({"cause":"template"}))
                .unwrap()["human"],
            4
        );
        let csv = root.join("received.csv");
        fs::write(
            &csv,
            "공고명,추정가격,계약일자\n청소용역,5000000,2026-09-01\n경비,700000원,2026-10-02\n",
        )
        .unwrap();
        editor.load_data_path(&csv, None, 1).unwrap();
        let snap = editor.snapshot().unwrap();
        assert!(snap["is_complete"].as_bool().unwrap());
        assert_eq!(
            snap["notice"]["text"],
            "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 이월한 4개 행 중 4개 행은 꾸러미 조건과 일치해 자동확정했습니다."
        );
        for name in ["건명", "금액", "계약일", "담당"] {
            assert_eq!(row(&snap, name)["confirmed"], true);
            assert_eq!(
                row(&snap, name)["state_label"],
                "자동확정 · 꾸러미 조건 일치"
            );
            assert_eq!(row(&snap, name)["contract_reason"], "");
        }
        assert_eq!(
            editor
                .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
                .unwrap()["human"],
            0
        );
        let date_index = row(&snap, "계약일")["index"].clone();
        editor
            .dispatch(
                "set_display",
                &json!({"index":date_index,"type":"date","fmt":"kor"}),
            )
            .unwrap();
        assert_eq!(
            row(&editor.snapshot().unwrap(), "계약일")["state_label"],
            "확인 필요"
        );
        assert_eq!(
            editor
                .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
                .unwrap()["human"],
            1
        );
        let const_index = row(&snap, "담당")["index"].clone();
        editor
            .dispatch("set_const", &json!({"index":const_index,"const":"김철수"}))
            .unwrap();
        assert_eq!(
            editor
                .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
                .unwrap()["human"],
            2
        );
        let other = root.join("other.csv");
        fs::write(
            &other,
            "공고명,추정가격,계약일자\n시설공사,9000000,2026-11-11\n",
        )
        .unwrap();
        editor.load_data_path(&other, None, 1).unwrap();
        assert_eq!(
            row(&editor.snapshot().unwrap(), "계약일")["contract_reason"],
            "꾸러미와 연결이 다름"
        );
        editor.load_job("받은작업").unwrap();
        fs::write(
            &csv,
            "공고명,추정가격,계약일자\n청소용역,5000000,2026-09-01\n경비,700000,추후 협의\n",
        )
        .unwrap();
        editor.load_data_path(&csv, None, 1).unwrap();
        let snap = editor.snapshot().unwrap();
        assert_eq!(
            row(&snap, "계약일")["contract_reason"],
            "날짜로 읽히지 않는 값 1행"
        );
        assert_eq!(row(&snap, "계약일")["confirmed"], false);
        assert_eq!(row(&snap, "계약일")["state_label"], "확인 필요");
        assert_eq!(snap["is_complete"], false);
        assert!(
            snap["notice"]["text"]
                .as_str()
                .unwrap()
                .contains("이월한 4개 행 중 3개 행은")
        );
        let date_index = row(&snap, "계약일")["index"].clone();
        editor
            .dispatch(
                "set_confirmed",
                &json!({"index":date_index,"confirmed":true}),
            )
            .unwrap();
        let confirmed = editor.snapshot().unwrap();
        assert_eq!(row(&confirmed, "계약일")["contract_reason"], "");
        assert_eq!(row(&confirmed, "계약일")["state_label"], "확인");
        assert_eq!(editor.dispatch("save", &json!({})).unwrap()["ok"], true);
        let saved = jobs.load("받은작업").unwrap();
        assert_eq!(saved.data_contract, Some(contract));
        assert_eq!(saved.data_path, csv.to_string_lossy());
        assert_eq!(saved.binding_revision, 1);
        editor.load_job("받은작업").unwrap();
        let missing = root.join("missing.csv");
        fs::write(&missing, "공고명,추정가격\n청소용역,5000000\n").unwrap();
        editor.load_data_path(&missing, None, 1).unwrap();
        assert_eq!(
            row(&editor.snapshot().unwrap(), "계약일")["contract_reason"],
            "데이터에 없음"
        );
        editor.load_job("무계약").unwrap();
        assert_eq!(
            editor
                .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
                .unwrap()["human"],
            4
        );
        editor.load_data_path(&other, None, 1).unwrap();
        let snap = editor.snapshot().unwrap();
        assert_eq!(snap["is_complete"], false);
        assert!(
            snap["rows"]
                .as_array()
                .unwrap()
                .iter()
                .all(|row| row["confirmed"] == false && row["contract_reason"] == "")
        );
        assert_eq!(
            snap["notice"]["text"],
            "템플릿/데이터가 바뀌어 매핑 초안을 다시 만들었습니다. 직접 확인하거나 편집한 4개 행의 소스·유형·서식은 이월했습니다. 확인이 필요한 행을 다시 확정하세요."
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn registered_sheet_tabs_follow_the_chosen_binding_and_reject_stale_registrations() {
        for kind in ["excel", "pclm"] {
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../target/editor-controller-tests")
                .join(format!("sheet-{kind}-{}", uuid::Uuid::new_v4()));
            let (editor, jobs, pool, _graph) = fixture(&root);
            let template = root.join("text_templates/tabs.txt");
            fs::write(
                &template,
                if kind == "excel" {
                    "{{업체명}}"
                } else {
                    "{{계약건명}}"
                },
            )
            .unwrap();
            let (path, first, second, opts) = if kind == "excel" {
                let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../tests/fixtures/multi_sheet.xlsx");
                (
                    path.clone(),
                    "공고목록",
                    "낙찰현황",
                    json!({"path":path,"sheet":"공고목록","sheets":["공고목록","낙찰현황"]}),
                )
            } else {
                let path = root.join("pclm.db");
                let db = rusqlite::Connection::open(&path).unwrap();
                db.execute_batch(
                    "CREATE TABLE 계약 (계약건명 TEXT, 계약금액 TEXT);
                    INSERT INTO 계약 VALUES ('잔류항생제분석기', '170,309,180');
                    CREATE VIEW v_통합_v1 AS SELECT * FROM 계약;",
                )
                .unwrap();
                (
                    path.clone(),
                    "v_통합_v1",
                    "계약",
                    json!({"db":path,"view":"v_통합_v1","sheets":["v_통합_v1","계약"]}),
                )
            };
            let key = pool
                .add(
                    &DatasetReference::new("월별 공고", kind, opts.as_object().unwrap().clone())
                        .unwrap(),
                )
                .unwrap();
            editor
                .dispatch("use_library_template", &json!({"path":template}))
                .unwrap();
            assert_eq!(editor.snapshot().unwrap()["data_sheet_tabs"], json!([]));
            assert_eq!(
                editor
                    .dispatch("use_pool_data", &json!({"key":key}))
                    .unwrap()["ok"],
                true
            );
            let snap = editor.snapshot().unwrap();
            assert_eq!(snap["data_sheet_tabs"].as_array().unwrap().len(), 2);
            assert_eq!(snap["data_sheet_tabs"][0]["sheet"], first);
            assert_eq!(snap["data_sheet_tabs"][0]["active"], true);
            assert_eq!(snap["data_sheet_tabs"][1]["sheet"], second);
            assert_eq!(snap["data_sheet_tabs"][1]["selectable"], true);
            editor
                .dispatch("goto_section", &json!({"section":"binding"}))
                .unwrap();
            assert_eq!(
                editor
                    .dispatch("use_pool_data", &json!({"key":key,"sheet":second}))
                    .unwrap(),
                json!({"ok":true,"label":"월별 공고"})
            );
            let snap = editor.snapshot().unwrap();
            assert_eq!(snap["data_sheet"], second);
            assert_eq!(snap["data_sheet_tabs"][0]["active"], false);
            assert_eq!(snap["data_sheet_tabs"][1]["active"], true);
            if kind == "excel" {
                assert_eq!(
                    snap["source_fields"],
                    json!(["업체명", "낙찰금액", "계약일"])
                );
            }
            let before = editor.state().unwrap().clone();
            assert_eq!(
                editor
                    .dispatch("use_pool_data", &json!({"key":key,"sheet":"미등록"}))
                    .unwrap()["ok"],
                false
            );
            let after = editor.state().unwrap().clone();
            assert_eq!(after.data_sheet, before.data_sheet);
            assert_eq!(after.records, before.records);
            assert_eq!(after.model_key, before.model_key);
            for row in snap["rows"].as_array().unwrap() {
                let index = &row["index"];
                if row["confirmable"] == false {
                    editor
                        .dispatch(
                            "set_display",
                            &json!({"index":index,"type":"const","fmt":""}),
                        )
                        .unwrap();
                }
                editor
                    .dispatch("set_confirmed", &json!({"index":index,"confirmed":true}))
                    .unwrap();
            }
            editor
                .dispatch("set_name", &json!({"name":"시트작업"}))
                .unwrap();
            assert_eq!(editor.dispatch("save", &json!({})).unwrap()["ok"], true);
            assert_eq!(jobs.load("시트작업").unwrap().data_sheet, second);
            assert_eq!(
                pool.load(&key).unwrap().opts[if kind == "excel" { "sheet" } else { "view" }],
                first
            );
            editor.load_job("시트작업").unwrap();
            let reopened = editor.snapshot().unwrap();
            assert_eq!(reopened["data_pool_key"], "");
            assert_eq!(reopened["data_sheet"], second);
            assert_eq!(reopened["data_sheet_tabs"][0]["active"], false);
            assert_eq!(reopened["data_sheet_tabs"][1]["active"], true);
            assert_eq!(
                editor
                    .dispatch("use_pool_data", &json!({"key":key,"sheet":first}))
                    .unwrap()["ok"],
                true
            );
            assert!(editor.has_unsaved_work().unwrap());
            if kind == "excel" {
                let moved = root.join("moved.xlsx");
                fs::copy(&path, &moved).unwrap();
                pool.commands()
                    .relink_excel(
                        &key,
                        moved.to_str().unwrap(),
                        Some(first),
                        "",
                        "",
                        Some(&[first.into(), second.into()]),
                    )
                    .unwrap();
                editor.refresh_panel().unwrap();
                assert_eq!(editor.snapshot().unwrap()["data_sheet_tabs"], json!([]));
                let records = editor.state().unwrap().records.clone();
                fs::write(pool.slot_path(&key).unwrap(), "{broken json").unwrap();
                editor.refresh_panel().unwrap();
                let tabs = editor.snapshot().unwrap()["data_sheet_tabs"].clone();
                assert_eq!(tabs.as_array().unwrap().len(), 1);
                assert_eq!(tabs[0]["active"], true);
                assert_eq!(tabs[0]["selectable"], false);
                assert_eq!(tabs[0]["damaged"], true);
                assert!(
                    tabs[0]["reason"]
                        .as_str()
                        .unwrap()
                        .contains("손상된 등록 데이터")
                );
                assert_eq!(
                    editor
                        .dispatch("use_pool_data", &json!({"key":key,"sheet":second}))
                        .unwrap()["ok"],
                    false
                );
                assert_eq!(editor.state().unwrap().records.clone(), records);
                fs::remove_file(pool.slot_path(&key).unwrap()).unwrap();
                editor.refresh_panel().unwrap();
                assert_eq!(editor.snapshot().unwrap()["data_sheet_tabs"], json!([]));
            }
            fs::remove_dir_all(root).unwrap();
        }
    }

    #[test]
    fn delayed_editor_push_cannot_overwrite_a_newer_name() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("push-{}", uuid::Uuid::new_v4()));
        let templates_dir = root.join("templates");
        fs::create_dir_all(&templates_dir).unwrap();
        let templates = Arc::new(
            TemplateRoot::new(
                Arc::new(ShellSettings::new(root.join("settings.json"), |_| {})),
                templates_dir.clone(),
            )
            .unwrap(),
        );
        let jobs =
            Arc::new(JobRegistry::new(root.join("jobs"), move || templates_dir.clone()).unwrap());
        let datasets = Arc::new(DatasetPoolRegistry::new(root.join("datasets")).unwrap());
        let held = Arc::new((Mutex::new((false, false)), Condvar::new()));
        let delivered = Arc::new(Mutex::new(Vec::<String>::new()));
        let saved = Arc::new(Mutex::new(None::<Arc<EditorController>>));
        let gate = held.clone();
        let out = delivered.clone();
        let capture = saved.clone();
        let _graph = WorkspaceSwitch::new(
            Locations::new(&root, None),
            move |_, snapshot| {
                let name = snapshot["name"].as_str().unwrap_or("").to_owned();
                if name == "A" {
                    let (lock, ready) = &*gate;
                    let mut state = lock.lock().unwrap();
                    state.0 = true;
                    ready.notify_all();
                    while !state.1 {
                        state = ready.wait(state).unwrap();
                    }
                }
                out.lock().unwrap().push(name);
                Ok(None)
            },
            move |home, push, token| {
                let controller = Arc::new(EditorController::new(
                    jobs.clone(),
                    templates.clone(),
                    datasets.clone(),
                    push,
                )?);
                *capture.lock().unwrap() = Some(controller.clone());
                Ok(WorkspaceGraph::new(
                    home.map(PathBuf::from),
                    vec![("editor".into(), controller as Arc<dyn ScreenController>)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let editor = saved.lock().unwrap().as_ref().unwrap().clone();
        let first = {
            let editor = editor.clone();
            std::thread::spawn(move || editor.dispatch("set_name", &json!({"name":"A"})).unwrap())
        };
        let (lock, ready) = &*held;
        let state = lock.lock().unwrap();
        let (state, timeout) = ready
            .wait_timeout_while(state, Duration::from_secs(3), |state| !state.0)
            .unwrap();
        assert!(!timeout.timed_out(), "first push was not held");
        drop(state);
        let second = {
            let editor = editor.clone();
            std::thread::spawn(move || editor.dispatch("set_name", &json!({"name":"B"})).unwrap())
        };
        let deadline = Instant::now() + Duration::from_secs(3);
        while editor.state().unwrap().job_name != "B" {
            assert!(
                Instant::now() < deadline,
                "second editor mutation did not run"
            );
            std::thread::yield_now();
        }
        let mut state = lock.lock().unwrap();
        state.1 = true;
        ready.notify_all();
        drop(state);
        first.join().unwrap();
        second.join().unwrap();
        assert_eq!(*delivered.lock().unwrap(), ["A", "B"]);
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_session_data_row_preserves_source_kind(editor: &EditorController) {
        let mut state = editor.state().unwrap().clone();
        for (kind, sheet, header, subtitle, icon) in [
            ("", "", 0, "1행", "excel"),
            ("excel", "물품", 1, "시트: 물품 · 헤더 1행 · 1행", "excel"),
            ("pclm", "v_통합_v1", 0, "시트: v_통합_v1 · 1행", "pclm"),
            ("pclm", "v_구판", 1, "시트: v_구판 · 헤더 1행 · 1행", "pclm"),
            ("pipeline", "", 0, "1행", "other"),
            ("unknown-kind", "", 0, "1행", "other"),
            ("hwpx", "", 0, "1행", "hwpx"),
            ("txt", "", 0, "1행", "txt"),
            ("nara", "", 0, "1행", "nara"),
        ] {
            state.data_kind = kind.into();
            state.data_sheet = sheet.into();
            state.data_header_row = header;
            assert_eq!(
                editor.facts(&state).unwrap().data_row,
                json!({
                    "key":"session", "name":"data", "sub":subtitle, "reason":"", "warns":[],
                    "badge_label":"사용 중", "badge_level":"ok", "icon":icon,
                    "selectable":true, "path":state.data_path, "actions":[],
                }),
                "source kind: {kind}"
            );
        }
        state.data_path.clear();
        assert!(editor.facts(&state).unwrap().data_row.is_null());
    }

    #[test]
    fn backward_navigation_and_new_name_save_keep_identity_bound_history() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/editor-controller-tests")
            .join(format!("{}-{stamp}", std::process::id()));
        let templates_dir = root.join("templates");
        fs::create_dir_all(&templates_dir).unwrap();
        let template = templates_dir.join("기안.txt");
        let csv = root.join("data.csv");
        fs::write(&template, "{{이름}}\n").unwrap();
        fs::write(&csv, "이름\n홍길동\n").unwrap();
        let settings = Arc::new(ShellSettings::new(root.join("settings.json"), |_| {}));
        let templates = Arc::new(TemplateRoot::new(settings, templates_dir.clone()).unwrap());
        let jobs =
            Arc::new(JobRegistry::new(root.join("jobs"), move || templates_dir.clone()).unwrap());
        let datasets = Arc::new(DatasetPoolRegistry::new(root.join("datasets")).unwrap());
        let saved_controller: Arc<Mutex<Option<Arc<EditorController>>>> =
            Arc::new(Mutex::new(None));
        let invalidated = Arc::new(Mutex::new(Vec::<String>::new()));
        let capture = saved_controller.clone();
        let pushes = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let counted = pushes.clone();
        let graph = WorkspaceSwitch::new(
            Locations::new(&root, None),
            move |_, _| {
                counted.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                Ok(None)
            },
            {
                let jobs = jobs.clone();
                let invalidated = invalidated.clone();
                move |home, push, token| {
                    let observed = invalidated.clone();
                    let controller = Arc::new(
                        EditorController::with_clock(
                            jobs.clone(),
                            templates.clone(),
                            datasets.clone(),
                            push,
                            || {
                                chrono::NaiveDate::from_ymd_opt(2026, 11, 5)
                                    .unwrap()
                                    .and_hms_opt(9, 0, 0)
                                    .unwrap()
                            },
                        )?
                        .with_generation_gate(Arc::new(GenerationGate::new()))
                        .with_after_mapping_saved(move |name| {
                            observed.lock().unwrap().push(name.to_owned());
                            if name == "새이름" {
                                Err("observation failed".into())
                            } else {
                                Ok(())
                            }
                        })
                        .with_binding_pending(|name| Ok(name == "새이름")),
                    );
                    *capture.lock().unwrap() = Some(controller.clone());
                    Ok(WorkspaceGraph::new(
                        home.map(Path::to_path_buf),
                        vec![("editor".into(), controller as Arc<dyn ScreenController>)],
                        (),
                        token,
                    ))
                }
            },
        )
        .unwrap();
        let editor = saved_controller.lock().unwrap().as_ref().unwrap().clone();
        let screen = graph.active().controller("editor").unwrap();
        let pairing = editor.snapshot().unwrap()["pairing"].clone();
        assert_eq!(pairing["auto_count"], 0);
        assert_eq!(pairing["confirm_count"], 0);
        assert_eq!(
            screen
                .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
                .unwrap(),
            json!({"human":0,"resuggest_manual":0,"confirmed":0})
        );
        screen
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        editor.load_data_path(&csv, None, 1).unwrap();
        let pairing = editor.snapshot().unwrap()["pairing"].clone();
        assert_eq!(pairing["auto_count"], 1);
        assert_eq!(pairing["confirm_count"], 0);
        assert_eq!(pairing["basis"], "preview");
        assert_session_data_row_preserves_source_kind(&editor);
        screen
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        let before_invalid_index = editor.snapshot().unwrap();
        assert!(
            screen
                .dispatch("set_source", &json!({"index":"bad","source":"col:이름"}))
                .is_err()
        );
        assert!(
            screen
                .dispatch("preview_slice", &json!({"index":null}))
                .is_err()
        );
        assert_eq!(editor.snapshot().unwrap(), before_invalid_index);
        screen
            .dispatch("set_confirmed", &json!({"index":-1,"confirmed":false}))
            .unwrap();
        screen
            .dispatch("set_confirmed", &json!({"index":-1,"confirmed":true}))
            .unwrap();
        screen.dispatch("confirm_suggested", &json!({})).unwrap();
        let undone = screen.dispatch("unconfirm_all", &json!({})).unwrap();
        assert!(undone["undo_count"].as_u64().unwrap() > 0);
        screen
            .dispatch("mapping_reset_stakes", &json!({"cause":"data"}))
            .unwrap();
        let restored = screen.dispatch("restore_confirmed", &json!({})).unwrap();
        assert_eq!(restored["restored"], undone["undo_count"]);
        assert!(
            editor.snapshot().unwrap()["rows"][0]
                .get("source_label")
                .is_none()
        );
        screen
            .dispatch("goto_section", &json!({"section":"template"}))
            .unwrap();
        screen
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        screen
            .dispatch("set_name", &json!({"name":"원본"}))
            .unwrap();
        assert_eq!(screen.dispatch("save", &json!({})).unwrap()["ok"], true);
        jobs.set_group("원본", "조달").unwrap();
        jobs.set_favorite("원본", true, Some("2026-07-20T09:00:00"))
            .unwrap();
        jobs.stamp_last_run("원본", "2026-07-21T09:00:00", None)
            .unwrap();
        editor.load_job("원본").unwrap();
        screen
            .dispatch("set_name", &json!({"name":"새이름"}))
            .unwrap();
        let saved = screen.dispatch("save", &json!({})).unwrap();
        assert_eq!(saved["ok"], true);
        assert!(
            saved["warning"]
                .as_str()
                .unwrap()
                .contains("observation failed")
        );
        assert_eq!(
            editor.snapshot().unwrap()["binding_confirm"]["pending"],
            true
        );
        assert_eq!(*invalidated.lock().unwrap(), ["원본", "새이름"]);
        let renamed = jobs.load("새이름").unwrap();
        assert_eq!(renamed.group, "조달");
        assert!(renamed.last_run_at.is_empty());
        assert!(renamed.favorited_at.is_empty());
        assert_eq!(
            jobs.load("원본").unwrap().last_run_at,
            "2026-07-21T09:00:00"
        );
        fs::write(&template, "{{추가}}\n").unwrap();
        editor.load_job("원본").unwrap();
        let notice = editor.snapshot().unwrap()["notice"]["text"]
            .as_str()
            .unwrap()
            .to_owned();
        assert!(notice.contains("더는 없는 저장 필드 1개"));
        assert!(notice.contains("새로 생긴 필드 1개"));
        assert_entry_handoff_preserves_binding_and_target(&editor, &template, &csv);
        fs::write(&template, "{{이름}} {{후속}}\n").unwrap();
        editor
            .reconcile_template_mutation("mutated", &template)
            .unwrap();
        assert!(
            editor.snapshot().unwrap()["notice"]["text"]
                .as_str()
                .unwrap()
                .contains("세션을 다시 읽었습니다")
        );
        editor
            .reconcile_template_mutation("deleted", &template)
            .unwrap();
        assert_eq!(editor.snapshot().unwrap()["notice"]["level"], "danger");
        let unreadable = root.join("templates/bad.txt");
        fs::write(&unreadable, [0xff]).unwrap();
        assert_eq!(
            editor.adopt_imported_template(&unreadable).unwrap(),
            "bad.txt"
        );
        assert!(
            editor.snapshot().unwrap()["notice"]["text"]
                .as_str()
                .unwrap()
                .contains("UTF-8 아님")
        );
        assert!(editor.template_live(unreadable.to_str().unwrap()).unwrap());
        fs::remove_file(&unreadable).unwrap();
        assert!(!editor.template_live(unreadable.to_str().unwrap()).unwrap());
        assert_display_choices_reach_generated_document(&editor, &root);
        assert_generated_sections_match_legacy(&editor, &root);
        assert_sliced_values_reach_generated_document(&editor, &root, &pushes);
        assert_runtime_date_reaches_generated_document(&editor, &root);
        assert_partial_gate_controls_navigation(&editor, &root);
        assert_overwrite_names_the_stored_victim(&editor);
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_entry_handoff_preserves_binding_and_target(
        editor: &EditorController,
        template: &Path,
        csv: &Path,
    ) {
        let before = editor.snapshot().unwrap();
        assert!(
            editor
                .new_draft_with_data(
                    &json!({"path":csv}),
                    &json!({"entry_reason":"schema_new_field"}),
                )
                .is_err()
        );
        assert_eq!(editor.snapshot().unwrap(), before);
        editor
            .new_draft_with_data(
                &json!({"path":csv,"header_row":1}),
                &json!({"entry_reason":"document_browser_new_work","evidence":{"데이터":"data.csv"},
                "return_context":{"surface":"data"}}),
            )
            .unwrap();
        assert_eq!(editor.snapshot().unwrap()["section"], "template");
        assert_eq!(editor.snapshot().unwrap()["data_header_row"], 1);
        assert_eq!(editor.snapshot().unwrap()["source_fields"], json!(["이름"]));
        editor
            .dispatch("set_name", &json!({"name":"이전 초안 이름"}))
            .unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        let anchored = editor.snapshot().unwrap();
        assert_eq!(anchored["data_path"], csv.to_string_lossy().as_ref());
        assert_eq!(anchored["data_header_row"], 1);
        assert_eq!(anchored["source_fields"], json!(["이름"]));
        assert_eq!(
            anchored["context"]["entry_reason"],
            "document_browser_new_work"
        );
        assert_eq!(anchored["context"]["evidence"]["데이터"], "data.csv");
        assert_eq!(anchored["name"], "기안 · data");
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        assert_eq!(editor.snapshot().unwrap(), anchored);
        let before = editor.snapshot().unwrap();
        assert!(
            editor
                .load_job_with_context("원본", &json!({"target":"template/x"}), None,)
                .is_err()
        );
        assert_eq!(editor.snapshot().unwrap(), before);
        editor
            .load_job_with_context(
                "원본",
                &json!({"entry_reason":"run_failure","target":"binding/이름",
                "return_context":{"surface":"result"}}),
                Some(&json!({"path":csv,"header_row":1})),
            )
            .unwrap();
        assert_eq!(
            editor.snapshot().unwrap()["context"]["target"],
            "binding/이름"
        );
    }

    fn assert_overwrite_names_the_stored_victim(editor: &EditorController) {
        editor.load_job("contract-default").unwrap();
        let original = editor.jobs.load("contract-default").unwrap();
        for (name, victim) in [
            ("기존 작업", Some("기존 작업")),
            ("예산/2026", Some("예산_2026")),
            ("손상된 작업", None),
        ] {
            let path = editor.jobs.path_for(name);
            if let Some(victim) = victim {
                let mut job = original.clone();
                job.name = victim.into();
                editor.jobs.save(&mut job, false).unwrap();
            } else {
                fs::write(&path, b"broken JSON").unwrap();
            }
            let before = fs::read(&path).unwrap();
            editor.dispatch("set_name", &json!({"name":name})).unwrap();
            let refused = editor.dispatch("save", &json!({})).unwrap();
            assert_eq!(refused["needs_overwrite"], true);
            let text = refused["overwrite_text"].as_str().unwrap();
            assert!(text.contains(name));
            assert!(text.contains(victim.unwrap_or("손상")));
            assert_eq!(fs::read(&path).unwrap(), before);
            let wrong = editor
                .dispatch(
                    "save",
                    &json!({"confirm_overwrite":true, "confirmed_overwrite_text":"다른 대상"}),
                )
                .unwrap();
            assert_eq!(wrong["needs_overwrite"], true);
            assert_eq!(fs::read(&path).unwrap(), before);
        }
        editor
            .dispatch("set_name", &json!({"name":"contract-default"}))
            .unwrap();
        let self_update = editor.dispatch("save", &json!({})).unwrap();
        assert_eq!(self_update["ok"], true);
        assert!(self_update["needs_overwrite"].is_null());
        let template_root = editor.templates.path();
        let root = template_root.parent().unwrap();
        for extension in ["txt", "docx"] {
            let foreign = root.join(format!("외부.{extension}"));
            fs::write(&foreign, "{{이름}}").unwrap();
            let mut victim = original.clone();
            victim.name = format!("다른매체-{extension}");
            victim.template_path = foreign.to_string_lossy().into();
            editor.jobs.save(&mut victim, false).unwrap();
            let before = fs::read(editor.jobs.path_for(&victim.name)).unwrap();
            editor
                .dispatch("set_name", &json!({"name":victim.name}))
                .unwrap();
            let refused = editor.dispatch("save", &json!({})).unwrap();
            assert_eq!(refused["ok"], false);
            assert!(
                refused["block_reason"]
                    .as_str()
                    .unwrap()
                    .contains("형식이 다른")
            );
            assert_eq!(
                fs::read(editor.jobs.path_for(&victim.name)).unwrap(),
                before
            );
        }
        editor.load_job("contract-default").unwrap();
        editor
            .jobs
            .mutate("contract-default", |job| {
                job.filename_pattern = "외부-{{seq}}".into()
            })
            .unwrap();
        let stale = editor.dispatch("save", &json!({})).unwrap();
        assert_eq!(stale["needs_overwrite"], true);
        assert!(
            stale["overwrite_text"]
                .as_str()
                .unwrap()
                .contains("외부 변경")
        );
        fs::remove_file(editor.jobs.path_for("contract-default")).unwrap();
        let saved = editor
            .dispatch(
                "save",
                &json!({"confirm_overwrite":true,
            "confirmed_overwrite_text":stale["overwrite_text"]}),
            )
            .unwrap();
        assert_eq!(saved["ok"], true, "{saved}");
    }

    fn assert_partial_gate_controls_navigation(editor: &EditorController, root: &Path) {
        use hwpx_core::package::{HwpxPackage, PackageEntry};
        let csv = root.join("partial.csv");
        fs::write(&csv, "계약명\n값\n").unwrap();
        for structural in [false, true] {
            let extra = if structural { "{{#항목 특약}}" } else { "" };
            let xml = format!(
                r#"<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run><hp:run><hp:t>값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p><hp:p><hp:run><hp:t>{{{{미결}}}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>{extra}</hp:t></hp:run></hp:p></hs:sec>"#
            );
            let document = HwpxPackage {
                entries: vec![
                    PackageEntry {
                        name: "mimetype".into(),
                        data: b"application/hwp+zip".to_vec(),
                        stored: true,
                    },
                    PackageEntry {
                        name: "Contents/section0.xml".into(),
                        data: xml.into_bytes(),
                        stored: false,
                    },
                ],
            };
            let path = root
                .join("templates")
                .join(format!("partial-{structural}.hwpx"));
            fs::write(&path, document.to_bytes().unwrap()).unwrap();
            editor.adopt_imported_template(&path).unwrap();
            editor.load_data_path(&csv, None, 1).unwrap();
            let before = editor.snapshot().unwrap();
            assert_eq!(before["gate"]["unmet"], json!(["미결"]));
            assert_eq!(before["gate"]["acked"], false);
            assert!(
                editor
                    .dispatch("goto_section", &json!({"section":"binding"}))
                    .is_err()
            );
            editor.dispatch("ack_gate", &json!({})).unwrap();
            assert_eq!(editor.snapshot().unwrap()["gate"]["acked"], true);
            let advanced = editor.dispatch("goto_section", &json!({"section":"binding"}));
            assert_eq!(advanced.is_ok(), !structural);
        }
    }

    fn display_row(editor: &EditorController, field: &str, kind: &str, code: &str) -> Value {
        let row = editor.snapshot().unwrap()["rows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["template_field"] == field)
            .unwrap()
            .clone();
        assert_eq!(
            row["display_value"],
            format!("{kind}:{code}"),
            "{field}: {row}"
        );
        assert!(
            row["display_options"]
                .as_array()
                .unwrap()
                .iter()
                .flat_map(|group| group["options"].as_array().unwrap())
                .any(|option| option["value"] == row["display_value"]
                    && option["type"] == kind
                    && option["fmt"] == code)
        );
        row
    }

    fn assert_display_choices_reach_generated_document(editor: &EditorController, root: &Path) {
        use hwpx_core::package::{HwpxPackage, PackageEntry, PackageLimits};

        let samples = [
            ("text", "", "대한상사", "대한상사"),
            ("text", "phone", "01012345678", "010-1234-5678"),
            ("date", "", "2026/7/17 18:05", "2026. 7. 17."),
            ("date", "datetime", "2026/7/17 18:05", "2026. 7. 17. 18:05"),
            ("amount", "", "24750000", "24,750,000원"),
            ("amount", "{:,.2f}", "24750000", "24,750,000.00"),
            ("today", "", "", "2026. 11. 5."),
            ("today", "datetime", "", "2026. 11. 5. 09:00"),
        ];
        let fields = (0..samples.len())
            .map(|index| format!("항목{index}"))
            .collect::<Vec<_>>();
        let body = fields.iter().map(|name| format!(
            "<hp:p><hp:run><hp:ctrl><hp:fieldBegin name=\"{name}\"/></hp:ctrl></hp:run><hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
        )).collect::<String>();
        let xml = format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?><hs:sec xmlns:hs=\"http://www.hancom.co.kr/hwpml/2011/section\" xmlns:hp=\"http://www.hancom.co.kr/hwpml/2011/paragraph\">{body}</hs:sec>"
        );
        let template = editor.templates.path().join("표시형.hwpx");
        fs::write(
            &template,
            HwpxPackage {
                entries: vec![
                    PackageEntry {
                        name: "mimetype".into(),
                        data: b"application/hwp+zip".to_vec(),
                        stored: true,
                    },
                    PackageEntry {
                        name: "Contents/section0.xml".into(),
                        data: xml.into_bytes(),
                        stored: false,
                    },
                ],
            }
            .to_bytes()
            .unwrap(),
        )
        .unwrap();
        let csv = fields.join(",")
            + "\n"
            + &samples
                .iter()
                .map(|sample| sample.2)
                .collect::<Vec<_>>()
                .join(",")
            + "\n";
        let first = root.join("first.csv");
        let second = root.join("second.csv");
        fs::write(&first, &csv).unwrap();
        fs::write(&second, &csv).unwrap();
        editor.dispatch("new_session", &json!({})).unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":template}))
            .unwrap();
        editor.load_data_path(&first, None, 1).unwrap();
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        for (field, (kind, code, _, _)) in fields.iter().zip(samples) {
            let index = display_row(editor, field, "text", "")["index"].clone();
            editor
                .dispatch(
                    "set_display",
                    &json!({"index":index,"type":"amount","fmt":"{:,.2f}"}),
                )
                .unwrap();
            editor
                .dispatch(
                    "set_display",
                    &json!({"index":index,"type":kind,"fmt":code}),
                )
                .unwrap();
            display_row(editor, field, kind, code);
        }
        editor.load_data_path(&second, None, 1).unwrap();
        for (field, (kind, code, _, expected)) in fields.iter().zip(samples) {
            let row = display_row(editor, field, kind, code);
            assert_eq!(row["preview"], expected, "{field}");
            editor
                .dispatch(
                    "set_confirmed",
                    &json!({"index":row["index"],"confirmed":true}),
                )
                .unwrap();
        }
        editor.dispatch("confirm_suggested", &json!({})).unwrap();
        editor
            .dispatch("set_name", &json!({"name":"표시형"}))
            .unwrap();
        editor
            .dispatch(
                "set_pattern",
                &json!({"pattern":"문서-{{항목4}}-{{항목5}}"}),
            )
            .unwrap();
        let saved = editor.dispatch("save", &json!({})).unwrap();
        assert_eq!(saved["ok"], true, "{saved}");
        editor.load_job("표시형").unwrap();
        for (field, (kind, code, _, _)) in fields.iter().zip(samples) {
            display_row(editor, field, kind, code);
        }
        let controller = generation_controller(editor, root);
        controller.select_job("표시형").unwrap();
        controller.dispatch("set_all", &json!({})).unwrap();
        let output = root.join("display-output");
        fs::create_dir(&output).unwrap();
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let result = controller.generate(false, "display-formats").unwrap();
        assert_eq!(result["status"], "completed", "{result}");
        let bytes = fs::read(output.join("문서-24,750,000원-24,750,000.00.hwpx")).unwrap();
        let package = HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap();
        let values = hwpx_filler::fields::read_fields(&package).unwrap();
        for (field, (_, _, _, expected)) in fields.iter().zip(samples) {
            assert_eq!(
                values.iter().find(|(name, _)| name == field).unwrap().1,
                expected,
                "{field}"
            );
        }
    }

    fn generation_controller(
        editor: &EditorController,
        root: &Path,
    ) -> crate::job_controller::JobController {
        use crate::job_controller::JobController;
        use crate::template_change_coordinator::TemplateChangeCoordinator;

        let change = Arc::new(
            TemplateChangeCoordinator::new(&root.join("authority"), editor.jobs.clone(), || {
                "2026-11-05T09:00:00".into()
            })
            .unwrap(),
        );
        let now = (editor.clock)();
        JobController::new(
            editor.jobs.clone(),
            editor.datasets.clone(),
            change,
            editor.generation_gate.clone().unwrap(),
            root.join("settings.json"),
            Arc::new(|_| {}),
        )
        .with_clock(move || now)
    }

    fn assert_generated_sections_match_legacy(editor: &EditorController, root: &Path) {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let controller = generation_controller(editor, root);
        for (case, template, data, overrides, expected_text) in [
            (
                "contract-default",
                "계약체결안내.hwpx",
                "계약목록.csv",
                vec![],
                "24,750,000원",
            ),
            (
                "contract-formats",
                "계약체결안내.hwpx",
                "계약목록_2.csv",
                vec![
                    ("계약금액", "amount", "{:,}"),
                    ("납품조건", "date", "kor"),
                    ("공고번호", "text", "biz"),
                ],
                "41,200,000",
            ),
            (
                "purchase-default",
                "구매추진안내.hwpx",
                "계약목록.csv",
                vec![],
                "",
            ),
        ] {
            open_example(editor, template, data, false);
            save_example(editor, case);
            editor
                .jobs
                .mutate(case, |job| {
                    for mapping in &mut job.mapping.mappings {
                        if let Some((_, kind, fmt)) = overrides
                            .iter()
                            .find(|item| item.0 == mapping.template_field)
                        {
                            mapping.field_type = (*kind).into();
                            mapping.fmt = (*fmt).into();
                        }
                    }
                })
                .unwrap();
            controller.select_job(case).unwrap();
            controller.dispatch("set_all", &json!({})).unwrap();
            let panel = controller.refresh_panel().unwrap();
            assert_eq!(panel["managed_hwpx"], true);
            assert_eq!(
                panel["slot_configuration"]["current_view"]["projection"]["slots"],
                json!([])
            );
            let docs = generate_example(&controller, root, case);
            let golden = repo
                .join("tests/fixtures/slotless_section0_golden")
                .join(case);
            assert_eq!(docs.len(), fs::read_dir(&golden).unwrap().count(), "{case}");
            let mut combined = String::new();
            for (index, (_, body)) in docs.iter().enumerate() {
                let expected =
                    fs::read(golden.join(format!("{:03}.section0.xml", index + 1))).unwrap();
                assert!(
                    body == &expected,
                    "{case} {}: generated XML differs from legacy",
                    index + 1
                );
                combined.push_str(std::str::from_utf8(body).unwrap());
            }
            assert!(combined.contains(expected_text), "{case}: {expected_text}");
        }
    }

    fn open_example(editor: &EditorController, template: &str, data: &str, compile: bool) {
        let examples = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/onboarding");
        let path = editor.templates.path().join(template);
        fs::copy(examples.join("templates").join(template), &path).unwrap();
        if compile {
            let templates = crate::template_controller::TemplateController::new_live(
                editor.templates.clone(),
                Arc::new(crate::template_groups::GroupSettings::new(
                    editor
                        .templates
                        .path()
                        .parent()
                        .unwrap()
                        .join("settings.json"),
                    |_| {},
                )),
                editor.push.clone(),
                Arc::new(|_, _| Ok(())),
                Arc::new(|_| Ok(())),
            );
            let result = templates
                .dispatch("compile", &json!({"path":path,"confirm":true}))
                .unwrap();
            assert_eq!(result["mutated"], true, "{result}");
        }
        editor.dispatch("new_session", &json!({})).unwrap();
        editor
            .dispatch("use_library_template", &json!({"path":path}))
            .unwrap();
        editor
            .load_data_path(&examples.join("data").join(data), None, 1)
            .unwrap();
        editor
            .dispatch("goto_section", &json!({"section":"binding"}))
            .unwrap();
        editor.dispatch("confirm_suggested", &json!({})).unwrap();
    }

    fn save_example(editor: &EditorController, name: &str) {
        editor.dispatch("set_name", &json!({"name":name})).unwrap();
        let result = editor.dispatch("save", &json!({})).unwrap();
        assert_eq!(result, json!({"ok":true,"saved_name":name}));
    }

    fn generate_example(
        controller: &crate::job_controller::JobController,
        root: &Path,
        name: &str,
    ) -> Vec<(String, Vec<u8>)> {
        use hwpx_core::package::{HwpxPackage, PackageLimits};

        let output = root.join(name);
        fs::create_dir(&output).unwrap();
        controller
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        let result = controller.generate(false, name).unwrap();
        assert_eq!(result["status"], "completed", "{name}: {result}");
        let mut docs = fs::read_dir(output)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| {
                path.extension()
                    .is_some_and(|extension| extension == "hwpx")
            })
            .collect::<Vec<_>>();
        docs.sort();
        assert_eq!(
            docs.len(),
            controller.data().unwrap().records.len(),
            "{name}"
        );
        docs.into_iter()
            .map(|path| {
                let package =
                    HwpxPackage::from_bytes(&fs::read(&path).unwrap(), PackageLimits::default())
                        .unwrap();
                let section = package
                    .entries
                    .into_iter()
                    .find(|entry| entry.name == "Contents/section0.xml")
                    .unwrap()
                    .data;
                (path.file_name().unwrap().to_str().unwrap().into(), section)
            })
            .collect()
    }

    fn assert_slice_queries_do_not_publish_or_mutate(
        editor: &EditorController,
        pushes: &std::sync::atomic::AtomicUsize,
    ) {
        use std::sync::atomic::Ordering;
        let before = editor.snapshot().unwrap();
        let dirty = editor.has_unsaved_work().unwrap();
        assert!(!dirty);
        let row = before["rows"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["template_field"] == "공고번호")
            .unwrap();
        let index = &row["index"];
        let count = pushes.load(Ordering::Relaxed);
        let preview = editor
            .dispatch("preview_slice", &json!({"index":index,"sample":0}))
            .unwrap();
        assert_eq!(preview["ok"], true);
        assert_eq!(preview["sample"]["value"], "20260812-001");
        let proposal = editor
            .dispatch(
                "propose_slice",
                &json!({"index":index,"sample":0,"start":0,"end":8}),
            )
            .unwrap();
        assert_eq!(
            proposal["candidates"]
                .as_array()
                .unwrap()
                .iter()
                .map(|c| c["mode"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["before", "split", "head"]
        );
        assert!(
            editor
                .dispatch(
                    "set_slice",
                    &json!({"index":index,"slice":{"mode":"head","count":0}})
                )
                .is_err()
        );
        assert_eq!(editor.snapshot().unwrap(), before);
        assert_eq!(editor.has_unsaved_work().unwrap(), dirty);
        assert_eq!(pushes.load(Ordering::Relaxed), count);
        assert!(validate_dispatch("editor", "preview_slice", &json!({})).is_err());
        assert!(
            validate_dispatch(
                "editor",
                "propose_slice",
                &json!({"index":index,"sample":0,"end":8})
            )
            .is_err()
        );
        for action in ["preview_map_slice", "propose_map_slice", "set_map_slice"] {
            assert!(validate_dispatch("workbench", action, &json!({})).is_err());
        }
    }

    fn assert_sliced_values_reach_generated_document(
        editor: &EditorController,
        root: &Path,
        pushes: &std::sync::atomic::AtomicUsize,
    ) {
        for (case, spec, label) in [
            (
                "slice-split",
                json!({"mode":"split","delimiter":"-","index":1}),
                "‘-’로 나눈 조각 중 첫째",
            ),
            (
                "slice-before",
                json!({"mode":"before","delimiter":"-","on_missing":"keep"}),
                "‘-’ 앞까지",
            ),
        ] {
            open_example(editor, "계약체결안내.hwpx", "계약목록.csv", false);
            for (field, slice, kind) in [
                ("공고번호", spec.clone(), "text"),
                (
                    "계약금액",
                    json!({"mode":"chars","start":1,"length":3}),
                    "amount",
                ),
            ] {
                let row = display_row(editor, field, kind, "");
                assert_eq!(row["slice_enabled"], true);
                editor
                    .dispatch("set_slice", &json!({"index":row["index"],"slice":slice}))
                    .unwrap();
                editor
                    .dispatch(
                        "set_confirmed",
                        &json!({"index":row["index"],"confirmed":true}),
                    )
                    .unwrap();
            }
            let row = display_row(editor, "공고번호", "text", "");
            assert_eq!(row["preview"], "20260812");
            assert_eq!(row["slice_label"], label);
            editor
                .dispatch(
                    "set_pattern",
                    &json!({"pattern":"{{공고번호}}-{{seq:001}}"}),
                )
                .unwrap();
            save_example(editor, case);
            if case == "slice-before" {
                assert_slice_queries_do_not_publish_or_mutate(editor, pushes);
            }
            let saved = editor.jobs.load(case).unwrap();
            let number = saved
                .mapping
                .mappings
                .iter()
                .find(|field| field.template_field == "공고번호")
                .unwrap();
            assert_eq!(
                number.slice,
                Some(hwpx_filler::text_slice::TextSlice::from_dict(&spec).unwrap())
            );
            let controller = generation_controller(editor, root);
            controller.select_job(case).unwrap();
            controller.dispatch("set_all", &json!({})).unwrap();
            let docs = generate_example(&controller, root, case);
            assert_eq!(
                docs.iter()
                    .map(|(name, _)| name.as_str())
                    .collect::<Vec<_>>(),
                [
                    "20260812-001.hwpx",
                    "20260812-002.hwpx",
                    "20260812-003.hwpx"
                ]
            );
            for record in &controller.data().unwrap().records {
                let matched = docs
                    .iter()
                    .filter(|(_, body)| {
                        std::str::from_utf8(body)
                            .unwrap()
                            .contains(&format!(">{}<", record["수요기관"]))
                    })
                    .collect::<Vec<_>>();
                assert_eq!(matched.len(), 1);
                let text = std::str::from_utf8(&matched[0].1).unwrap();
                let values = record
                    .iter()
                    .map(|(key, value)| (key.clone(), json!(value)))
                    .collect();
                for field in saved.mapping.mappings.iter().filter(|field| {
                    ["공고번호", "계약금액"].contains(&field.template_field.as_str())
                }) {
                    assert!(field.slice.is_some());
                    assert!(
                        text.contains(&format!(">{}<", field.value_for(&values, None).unwrap())),
                        "{case}: {}",
                        field.template_field
                    );
                }
                assert!(!text.contains(&format!(">{}<", record["공고번호"])));
            }
        }
    }

    fn assert_runtime_date_reaches_generated_document(editor: &EditorController, root: &Path) {
        use std::sync::atomic::{AtomicUsize, Ordering};

        let now = chrono::NaiveDate::from_ymd_opt(2026, 6, 15)
            .unwrap()
            .and_hms_opt(18, 4, 0)
            .unwrap();
        for (case, template, compile, ticking) in [
            ("today-slotless", "계약체결안내.hwpx", false, false),
            ("today-slotted", "공고서_연습.hwpx", true, false),
            ("today-ticking", "계약체결안내.hwpx", false, true),
        ] {
            open_example(editor, template, "계약목록.csv", compile);
            let row = display_row(editor, "품명", "text", "");
            editor
                .dispatch(
                    "set_display",
                    &json!({"index":row["index"],"type":"today","fmt":"%Y.%m.%d"}),
                )
                .unwrap();
            editor
                .dispatch(
                    "set_confirmed",
                    &json!({"index":row["index"],"confirmed":true}),
                )
                .unwrap();
            editor
                .dispatch(
                    "set_pattern",
                    &json!({"pattern":"{{공고번호}}-{{품명}}-{{date:%Y%m%d}}"}),
                )
                .unwrap();
            save_example(editor, case);
            let saved = editor.jobs.load(case).unwrap();
            let today = saved
                .mapping
                .mappings
                .iter()
                .find(|field| field.template_field == "품명")
                .unwrap();
            assert_eq!((&*today.field_type, &*today.fmt), ("today", "%Y.%m.%d"));
            let ticks = AtomicUsize::new(0);
            let controller = generation_controller(editor, root).with_clock(move || {
                now + chrono::Duration::days(if ticking {
                    ticks.fetch_add(1, Ordering::SeqCst) as i64
                } else {
                    0
                })
            });
            controller.select_job(case).unwrap();
            controller.dispatch("set_all", &json!({})).unwrap();
            if compile {
                let mut view = controller
                    .dispatch("open_slot_configuration", &json!({}))
                    .unwrap()["current_view"]
                    .clone();
                let slots = view["projection"]["slots"].as_array().unwrap().clone();
                assert!(!slots.is_empty());
                for slot in slots {
                    if slot["effective_option_ids"].as_array().unwrap().is_empty() {
                        view = controller.dispatch("select_slot_option", &json!({
                            "configuration_token":view["new_configuration_token"], "slot_id":slot["slot_id"],
                            "option_id":slot["options"][0]["option_id"], "request_id":uuid::Uuid::new_v4().to_string(),
                        })).unwrap()["current_view"].clone();
                    }
                }
            }
            let records = controller.data().unwrap().records;
            for (index, (name, body)) in
                generate_example(&controller, root, case).iter().enumerate()
            {
                let parts = name
                    .strip_suffix(".hwpx")
                    .unwrap()
                    .split('-')
                    .collect::<Vec<_>>();
                assert_eq!(parts.len(), 4, "{name}");
                assert_eq!(parts[0], "20260812");
                assert_eq!(parts[1], format!("{:03}", index + 1));
                assert_eq!(parts[2].replace('.', ""), parts[3], "{name}");
                chrono::NaiveDate::parse_from_str(parts[2], "%Y.%m.%d").unwrap();
                if !ticking {
                    assert_eq!(parts[2], "2026.06.15");
                }
                let text = std::str::from_utf8(body).unwrap();
                assert!(text.contains(&format!(">{}<", parts[2])), "{name}");
                assert!(
                    !records
                        .iter()
                        .any(|record| text.contains(&format!(">{}<", record["품명"])))
                );
            }
        }
    }
}
