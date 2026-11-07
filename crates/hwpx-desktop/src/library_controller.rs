//! Native library screen read path and first-row correlation.

use crate::action_registry::validate_dispatch;
use crate::dataset_registry::DatasetPoolRegistry;
use crate::job_registry::{DeletedJobSlot, JobRegistry, StoreError};
use crate::library_observation::{
    dataset_display_name, editable_applied_template_path, read_first_row, read_library,
    read_template, selected_snapshot, template_display_name, unselected_snapshot,
};
use crate::locations::Locations;
use crate::preset_registry::PresetRegistry;
use crate::template_files::TemplateFileStore;
use crate::work_package_autobind::bind_imported;
use crate::work_package_install::{InstallError, WorkPackageInstaller};
use crate::work_package_io::write_work_package;
use crate::work_package_sources::WorkPackageSources;
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use chrono::Local;
use hwpx_filler::home_state::{LibraryLens, StructureDrift, work_mode_label};
use hwpx_filler::job::{Job, template_media, work_mode};
use hwpx_filler::library_detail::{FirstRowRead, PairingCache};
use hwpx_filler::text_render::python_repr;
use hwpx_filler::work_package_plan::{DraftError, draft_work_package, plan_view};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::UNIX_EPOCH;

mod relink;
mod work_package;

#[derive(Clone, Hash, PartialEq, Eq)]
struct BindingKey {
    name: String,
    path: String,
    sheet: String,
    header_row: u64,
    kind: String,
    stamp: Option<(u128, u64)>,
}
impl BindingKey {
    fn of(job: &Job) -> Option<Self> {
        if !job.has_data_binding() {
            return None;
        }
        let stamp = fs::metadata(&job.data_path).ok().map(|info| {
            (
                info.modified()
                    .ok()
                    .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
                    .map_or(0, |age| age.as_nanos()),
                info.len(),
            )
        });
        Some(Self {
            name: job.name.clone(),
            path: job.data_path.clone(),
            sheet: job.data_sheet.clone(),
            header_row: job.data_header_row,
            kind: job.data_kind.clone(),
            stamp,
        })
    }
}

#[derive(Default)]
struct LibraryState {
    lens: LibraryLens,
    selected: String,
    active_key: Option<BindingKey>,
    first_rows: HashMap<BindingKey, FirstRowRead>,
    inflight: HashSet<BindingKey>,
    deleted_job_slot: Option<DeletedJobSlot>,
    pairing: PairingCache,
}
impl LibraryState {
    fn select(&mut self, name: String) {
        self.selected = name;
        self.first_rows.retain(|_, read| read.state != "error");
    }

    fn begin_first_row(&mut self, key: &BindingKey) -> bool {
        !self.first_rows.contains_key(key) && self.inflight.insert(key.clone())
    }

    fn complete_first_row(&mut self, key: BindingKey, result: FirstRowRead) -> bool {
        self.inflight.remove(&key);
        let selected = self.active_key.as_ref() == Some(&key);
        self.first_rows.insert(key, result);
        selected
    }
}

type SessionGuard = dyn Fn(&str) -> Result<Option<Value>, GraphError> + Send + Sync;
type GenerationActivity = dyn Fn() -> bool + Send + Sync;

pub struct LibraryStores {
    pub jobs: Arc<JobRegistry>,
    pub datasets: Arc<DatasetPoolRegistry>,
    pub presets: Arc<PresetRegistry>,
    pub template_files: Arc<TemplateFileStore>,
}

#[derive(Clone)]
pub struct LibraryController {
    jobs: Arc<JobRegistry>,
    datasets: Arc<DatasetPoolRegistry>,
    presets: Arc<PresetRegistry>,
    template_files: Arc<TemplateFileStore>,
    locations: Locations,
    examples_installed: bool,
    push: PushGate,
    session_guard: Arc<SessionGuard>,
    generation_active: Arc<GenerationActivity>,
    state: Arc<Mutex<LibraryState>>,
    push_order: Arc<Mutex<()>>,
}
impl LibraryController {
    pub fn new(
        stores: LibraryStores,
        locations: Locations,
        examples_installed: bool,
        push: PushGate,
        session_guard: Arc<SessionGuard>,
        generation_active: Arc<GenerationActivity>,
    ) -> Self {
        let LibraryStores {
            jobs,
            datasets,
            presets,
            template_files,
        } = stores;
        Self {
            jobs,
            datasets,
            presets,
            template_files,
            locations,
            examples_installed,
            push,
            session_guard,
            generation_active,
            state: Arc::new(Mutex::new(LibraryState::default())),
            push_order: Arc::new(Mutex::new(())),
        }
    }
    fn push_current(&self) -> Result<(), GraphError> {
        let _serial = self
            .push_order
            .lock()
            .map_err(|_| "library push order poisoned")?;
        self.push.push("library", &self.snapshot()?)?;
        Ok(())
    }
    fn truthy(value: Option<&Value>) -> bool {
        match value {
            None | Some(Value::Null | Value::Bool(false)) => false,
            Some(Value::Number(number)) => number.as_f64() != Some(0.0),
            Some(Value::String(value)) => !value.is_empty(),
            Some(Value::Array(value)) => !value.is_empty(),
            Some(Value::Object(value)) => !value.is_empty(),
            Some(Value::Bool(true)) => true,
        }
    }
    fn toggle_favorite(&self, payload: &Map<String, Value>) -> Value {
        let name = payload.get("name").and_then(Value::as_str).unwrap_or("");
        let value = Self::truthy(payload.get("value"));
        match self.jobs.set_favorite(name, value, None) {
            Ok(_) => json!({"ok":true}),
            Err(error) => json!({"ok":false, "error":format!(
                "'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {error}")}),
        }
    }
    fn clone_job(&self, payload: &Map<String, Value>) -> Value {
        let name = payload.get("name").and_then(Value::as_str).unwrap_or("");
        match self.jobs.clone_job(name) {
            Ok(cloned) => json!({"ok":true,"cloned":cloned}),
            Err(error) => json!({"ok":false,"error":format!("작업을 복제할 수 없습니다: {error}")}),
        }
    }
    fn delete_job(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let name = payload
            .get("name")
            .and_then(Value::as_str)
            .ok_or("job name required")?;
        if !Self::truthy(payload.get("confirm"))
            && let Some(guard) = (self.session_guard)(name)?
        {
            let mut result = json!({"needs_confirm":true,"name":name,"open_session":true});
            if let Some(fields) = guard.as_object() {
                result.as_object_mut().unwrap().extend(fields.clone());
            }
            return Ok(result);
        }
        let slot = self.jobs.soft_delete(name)?;
        let mut state = self.state()?;
        state.deleted_job_slot = Some(slot);
        if state.selected == name {
            state.selected.clear();
            state.active_key = None;
        }
        Ok(json!({"ok":true,"undo":true,"name":name}))
    }
    fn undo_delete_job(&self) -> Result<Value, GraphError> {
        let mut state = self.state()?;
        let Some(slot) = state.deleted_job_slot.as_ref() else {
            return Ok(json!({"ok":false,"error":"복원할 최근 작업이 없습니다."}));
        };
        let name = self.jobs.restore_soft_deleted(slot)?;
        state.deleted_job_slot = None;
        Ok(json!({"ok":true,"name":name}))
    }
    pub fn validate_corrupt_path(&self, raw: &str) -> Result<PathBuf, GraphError> {
        if !read_library(&self.jobs, &self.datasets)?
            .corrupt_jobs
            .iter()
            .any(|item| item.token == raw)
        {
            return Err("손상 작업 목록에 없는 경로입니다. 새로고침 후 다시 시도하세요.".into());
        }
        Ok(PathBuf::from(raw))
    }
    fn delete_corrupt(&self, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let path = payload
            .get("path")
            .and_then(Value::as_str)
            .ok_or("corrupt path required")?;
        self.validate_corrupt_path(path)?;
        if !Self::truthy(payload.get("confirm")) {
            return Ok(json!({"ok":true,"needs_confirm":true,"path":path,
                "confirm_text":format!("손상된 작업 파일을 삭제합니다(복구 불가):\n{path}\n내용을 확인하려면 먼저 '폴더 열기'로 살펴보세요.")}));
        }
        self.jobs.remove_corrupt_entry(path)?;
        Ok(json!({"ok":true}))
    }
    fn state(&self) -> Result<std::sync::MutexGuard<'_, LibraryState>, GraphError> {
        Ok(self.state.lock().map_err(|_| "library state poisoned")?)
    }
    fn snapshot(&self) -> Result<Value, GraphError> {
        let inventory = read_library(&self.jobs, &self.datasets)?;
        let (lens, selected) = {
            let state = self.state()?;
            (state.lens.clone(), state.selected.clone())
        };
        if selected.is_empty() {
            self.state()?.active_key = None;
            return Ok(unselected_snapshot(
                &inventory,
                &lens,
                self.examples_installed,
            ));
        }
        let Some(row) = inventory.rows.iter().find(|row| row.name == selected) else {
            self.state()?.active_key = None;
            return Ok(selected_snapshot(
                &inventory,
                &lens,
                self.examples_installed,
                &selected,
                None,
                None,
                "",
            ));
        };
        let Ok(job) = self.jobs.load(&selected) else {
            self.state()?.active_key = None;
            return Ok(selected_snapshot(
                &inventory,
                &lens,
                self.examples_installed,
                &selected,
                None,
                None,
                "",
            ));
        };
        let key = (!row.template_missing)
            .then(|| BindingKey::of(&job))
            .flatten();
        let cached = {
            let mut state = self.state()?;
            state.active_key = key.clone();
            key.as_ref()
                .and_then(|key| state.first_rows.get(key).cloned())
        };
        let template_name = template_display_name(&self.template_files.root(), &job.template_path);
        let data_name = dataset_display_name(&self.datasets, &job);
        let pairing = self
            .state()?
            .pairing
            .get(
                row,
                &job,
                &template_name,
                &data_name,
                cached.as_ref(),
                Local::now().naive_local(),
            )?
            .clone();
        let edit_path = editable_applied_template_path(&job, &self.locations);
        Ok(selected_snapshot(
            &inventory,
            &lens,
            self.examples_installed,
            &selected,
            Some(&job),
            Some(pairing),
            &edit_path,
        ))
    }
    fn ensure_first_row_read(&self) -> Result<(), GraphError> {
        let selected = self.state()?.selected.clone();
        if selected.is_empty() {
            return Ok(());
        }
        let job = match self.jobs.load(&selected) {
            Ok(job) => job,
            Err(_) => return Ok(()),
        };
        let key = match BindingKey::of(&job) {
            Some(key) => key,
            None => return Ok(()),
        };
        if !Path::new(&job.template_path).exists() {
            return Ok(());
        }
        if !self.state()?.begin_first_row(&key) {
            return Ok(());
        }
        let controller = self.clone();
        let worker_key = key.clone();
        let started = std::thread::Builder::new()
            .name("library-first-row".into())
            .spawn(move || {
                let result = read_first_row(&job);
                let should_push = controller
                    .state()
                    .is_ok_and(|mut state| state.complete_first_row(worker_key, result));
                if should_push {
                    let _ = controller.push_current();
                }
            });
        if let Err(error) = started {
            self.state()?.inflight.remove(&key);
            return Err(error.into());
        }
        Ok(())
    }
    fn update(&self, action: &str, payload: &Map<String, Value>) -> Result<Value, GraphError> {
        let as_python_text = |key: &str| {
            payload.get(key).map_or_else(String::new, |value| {
                value
                    .as_str()
                    .map_or_else(|| python_repr(value), str::to_owned)
            })
        };
        match action {
            "toggle_favorite" => return Ok(self.toggle_favorite(payload)),
            "clone_job" => return Ok(self.clone_job(payload)),
            "relink_template" => return self.relink_template(payload),
            "delete_job" => return self.delete_job(payload),
            "undo_delete_job" => return self.undo_delete_job(),
            "delete_corrupt" => return self.delete_corrupt(payload),
            "inspect_work_package" => return self.inspect_work_package(payload),
            "export_work_package" => return self.export_work_package(payload),
            "import_work_package" => return self.import_work_package(payload),
            "set_view" => self
                .state()?
                .lens
                .set_view(payload.get("view").and_then(Value::as_str).unwrap_or("")),
            "set_mode" => self
                .state()?
                .lens
                .set_mode(payload.get("mode").and_then(Value::as_str).unwrap_or("")),
            "set_query" => self.state()?.lens.query = as_python_text("text"),
            "clear_filters" => self.state()?.lens = LibraryLens::default(),
            "select_work" => {
                self.state()?.select(as_python_text("name"));
            }
            "refresh" => {
                if let Some(name) = payload
                    .get("select")
                    .and_then(Value::as_str)
                    .filter(|name| !name.is_empty())
                    && read_library(&self.jobs, &self.datasets)?
                        .rows
                        .iter()
                        .any(|row| row.name == name)
                {
                    self.state()?.selected = name.into();
                }
            }
            _ => return Err(format!("알 수 없는 library 액션: {action:?}").into()),
        }
        Ok(Value::Null)
    }
}
impl ScreenController for LibraryController {
    fn initial(&self) -> Result<Value, GraphError> {
        let snapshot = self.snapshot()?;
        self.ensure_first_row_read()?;
        Ok(snapshot)
    }
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let object = validate_dispatch("library", action, payload)?;
        let result = self.update(action, object)?;
        self.push_current()?;
        self.ensure_first_row_read()?;
        Ok(result)
    }
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        Ok(None)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{LibraryController, LibraryStores};
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::job_registry::JobRegistry;
    use crate::locations::Locations;
    use crate::preset_registry::PresetRegistry;
    use crate::template_files::TemplateFileStore;
    use crate::work_package_io::{build_work_package_bytes, read_work_package};
    use crate::workspace_switch::{WorkspaceGraph, WorkspaceSwitch};
    use hwpx_filler::job::Job;
    use hwpx_filler::work_package::{PackagedJob, PackagedTemplate, WorkPackageManifest};
    use serde_json::{Value, json};
    use sha2::{Digest, Sha256};
    use std::collections::HashMap;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::mpsc;
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    type PackageGraph = crate::live_graph::LiveGraph<crate::workspace_runtime::RuntimeResources>;

    fn assert_first_row_cache_correlation(template: &Path) {
        use super::{BindingKey, LibraryState};
        use hwpx_filler::library_detail::FirstRowRead;
        let path = template.with_file_name("cache-data.csv");
        fs::write(&path, "사업명\n처음\n").unwrap();
        let mut job = Job {
            name: "계약".into(),
            data_path: path.to_str().unwrap().into(),
            ..Job::default()
        };
        assert!(BindingKey::of(&Job::default()).is_none());
        let first = BindingKey::of(&job).unwrap();
        let mut state = LibraryState::default();
        state.select(job.name.clone());
        state.active_key = Some(first.clone());
        assert!(state.begin_first_row(&first));
        state.select(job.name.clone());
        assert!(
            !state.begin_first_row(&first),
            "reselection must not duplicate a worker"
        );
        state.active_key = None;
        let result = |status: &str| FirstRowRead {
            state: status.into(),
            reason: String::new(),
            record: Default::default(),
            headers: vec![],
            record_count: 0,
        };
        assert!(
            !state.complete_first_row(first.clone(), result("ready")),
            "a late result must not push onto another selection"
        );
        assert!(state.inflight.is_empty());
        state.active_key = Some(first.clone());
        assert!(
            !state.begin_first_row(&first),
            "returning to a selection reuses its cache"
        );
        job.name = "다른 계약".into();
        let second = BindingKey::of(&job).unwrap();
        assert!(first != second);
        state.active_key = Some(second.clone());
        assert!(state.begin_first_row(&second));
        assert!(state.complete_first_row(second.clone(), result("error")));
        assert!(
            !state.begin_first_row(&second),
            "a snapshot must not retry cached failures"
        );
        state.select(job.name.clone());
        assert!(
            state.first_rows.contains_key(&first),
            "successful reads survive explicit selection"
        );
        assert!(
            state.begin_first_row(&second),
            "explicit selection retries a failed read"
        );
        assert!(state.complete_first_row(second.clone(), result("ready")));
        fs::write(&path, "사업명\n외부에서 바뀐 값\n").unwrap();
        let changed = BindingKey::of(&job).unwrap();
        assert!(changed != second);
        assert!(state.begin_first_row(&changed));
        for changed_job in [
            Job {
                data_sheet: "다른 시트".into(),
                ..job.clone()
            },
            Job {
                data_header_row: 2,
                ..job.clone()
            },
            Job {
                data_kind: "pclm".into(),
                ..job.clone()
            },
        ] {
            assert!(BindingKey::of(&changed_job).unwrap() != changed);
        }
        fs::remove_file(path).unwrap();
        assert!(BindingKey::of(&job).unwrap() != changed);
    }

    fn assert_first_row_worker_refreshes(
        controller: &dyn crate::workspace_switch::ScreenController,
        jobs: &JobRegistry,
        template: &Path,
        snapshots: &mpsc::Receiver<Value>,
    ) {
        use hwpx_filler::mapping::FieldMapping;
        let data = template.with_file_name("live-data.csv");
        fs::write(&data, "사업명\n처음\n둘째\n").unwrap();
        let mut job = jobs.load("계약").unwrap();
        job.data_path = data.to_str().unwrap().into();
        job.data_header_row = 1;
        job.mapping.mappings =
            vec![FieldMapping::new("계약명", "사업명", "text", "", "", None).unwrap()];
        jobs.save(&mut job, true).unwrap();
        let wait_ready = |expected: &str| {
            loop {
                let snapshot = snapshots
                    .recv_timeout(Duration::from_secs(5))
                    .expect("first-row worker did not publish its result");
                let detail = &snapshot["detail"]["pairing_detail"];
                if snapshot["selected"] == "계약"
                    && detail["first_row"]["state"] == "ready"
                    && detail["rows"][0]["preview"] == expected
                {
                    assert!(snapshot["sections"].is_array() && snapshot["counts"].is_object());
                    assert_eq!(detail["rows"][0]["preview_kind"], "value");
                    break snapshot;
                }
            }
        };
        while snapshots.try_recv().is_ok() {}
        controller
            .dispatch("refresh", &json!({"select":"계약"}))
            .unwrap();
        let pending = snapshots.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(
            pending["detail"]["pairing_detail"]["first_row"]["state"],
            "pending"
        );
        let ready = wait_ready("처음");
        let detail = &ready["detail"]["pairing_detail"];
        assert_eq!(detail["first_row"]["record_count"], 2);
        assert_eq!(detail["card"]["template_name"], "replacement");
        assert_eq!(detail["card"]["data_name"], "live-data");
        assert_eq!(detail["card"]["counted"], true);
        assert_eq!(ready["detail"]["health_causes"], json!([]));
        fs::write(&data, "사업명\n외부에서 바뀐 값\n").unwrap();
        let pending = controller.initial().unwrap();
        assert_eq!(
            pending["detail"]["pairing_detail"]["first_row"]["state"],
            "pending"
        );
        wait_ready("외부에서 바뀐 값");
        fs::remove_file(&data).unwrap();
        controller.initial().unwrap();
        loop {
            let snapshot = snapshots.recv_timeout(Duration::from_secs(5)).unwrap();
            if snapshot["selected"] == "계약"
                && snapshot["detail"]["pairing_detail"]["first_row"]["state"] == "error"
            {
                assert!(
                    snapshot["detail"]["pairing_detail"]["first_row"]["reason"]
                        .as_str()
                        .unwrap()
                        .contains(data.to_str().unwrap())
                );
                assert_eq!(
                    snapshot["detail"]["pairing_detail"]["rows"][0]["preview_kind"],
                    "error"
                );
                break;
            }
        }
        fs::write(&data, "사업명\n복구한 값\n").unwrap();
        controller
            .dispatch("select_work", &json!({"name":"계약"}))
            .unwrap();
        wait_ready("복구한 값");
        assert_read_after_job_changes(controller, jobs, template, snapshots);
        assert_library_management(controller, jobs, template);
    }

    fn assert_library_management(
        controller: &dyn crate::workspace_switch::ScreenController,
        jobs: &JobRegistry,
        template: &Path,
    ) {
        controller.dispatch("clear_filters", &json!({})).unwrap();
        let snapshot = controller.initial().unwrap();
        assert_eq!(
            (
                snapshot["view"].as_str(),
                snapshot["mode"].as_str(),
                snapshot["query"].as_str()
            ),
            (Some("all"), Some("all"), Some(""))
        );
        for _ in 0..2 {
            assert_eq!(
                controller
                    .dispatch("toggle_favorite", &json!({"name":"계약","value":true}))
                    .unwrap(),
                json!({"ok":true})
            );
            assert!(!jobs.load("계약").unwrap().favorited_at.is_empty());
        }
        controller
            .dispatch("set_view", &json!({"view":"favorites"}))
            .unwrap();
        controller
            .dispatch("set_query", &json!({"text":"계약"}))
            .unwrap();
        controller
            .dispatch("set_mode", &json!({"mode":"hwpx"}))
            .unwrap();
        let filtered = controller.initial().unwrap();
        assert_eq!(
            (
                filtered["view"].as_str(),
                filtered["mode"].as_str(),
                filtered["query"].as_str()
            ),
            (Some("favorites"), Some("hwpx"), Some("계약"))
        );
        assert!(
            filtered["sections"][0]["rows"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        controller.dispatch("clear_filters", &json!({})).unwrap();
        for (action, payload, fragment) in [
            (
                "toggle_favorite",
                json!({"name":"없는작업","value":true}),
                "즐겨찾기를 바꾸지 못했습니다",
            ),
            (
                "clone_job",
                json!({"name":"없는작업"}),
                "복제할 수 없습니다",
            ),
        ] {
            let refused = controller.dispatch(action, &payload).unwrap();
            assert_eq!(refused["ok"], false);
            assert!(refused["error"].as_str().unwrap().contains(fragment));
        }
        let mut original = jobs.load("계약").unwrap();
        original.name = "관리검사".into();
        original.group = "조달".into();
        original.tags.insert("종류".into(), json!("계약"));
        original.last_run_at = "2026-07-09T15:42:00".into();
        jobs.save(&mut original, false).unwrap();
        for expected in [
            "관리검사 (복사본)",
            "관리검사 (복사본 2)",
            "관리검사 (복사본 3)",
        ] {
            assert_eq!(
                controller
                    .dispatch("clone_job", &json!({"name":"관리검사"}))
                    .unwrap()["cloned"],
                expected
            );
            let copy = jobs.load(expected).unwrap();
            assert_eq!(copy.mapping, original.mapping);
            assert_eq!(copy.filename_pattern, original.filename_pattern);
            assert_eq!(copy.tags, original.tags);
            assert!(copy.last_run_at.is_empty());
        }
        assert_eq!(
            jobs.load("관리검사").unwrap().last_run_at,
            original.last_run_at
        );
        let snapshot = controller.initial().unwrap();
        let sections = snapshot["sections"].as_array().unwrap();
        assert_eq!(sections.len(), 1);
        assert_eq!(sections[0]["headed"], false);
        assert_eq!(sections[0]["collapsed"], false);
        assert!(
            sections[0]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .any(|row| row["name"] == "관리검사 (복사본 3)")
        );
        for action in [
            "frobnicate",
            "toggle_group",
            "set_tags",
            "toggle_facet",
            "clear_facets",
            "set_group_by",
        ] {
            assert!(controller.dispatch(action, &json!({})).is_err());
        }
        assert_eq!(
            controller.dispatch("undo_delete_job", &json!({})).unwrap(),
            json!({"ok":false,"error":"복원할 최근 작업이 없습니다."})
        );
        let broken = jobs.path_for("broken");
        fs::write(&broken, "{ not json").unwrap();
        let before = fs::read(template).unwrap();
        assert!(
            controller
                .dispatch("delete_corrupt", &json!({"path":template,"confirm":true}))
                .is_err()
        );
        assert_eq!(fs::read(template).unwrap(), before);
        let confirmation = controller
            .dispatch("delete_corrupt", &json!({"path":broken}))
            .unwrap();
        assert_eq!(confirmation["needs_confirm"], true);
        assert!(
            confirmation["confirm_text"]
                .as_str()
                .unwrap()
                .contains("복구 불가")
        );
        assert_eq!(
            controller.initial().unwrap()["corrupt_rows"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            controller
                .dispatch("delete_corrupt", &json!({"path":broken,"confirm":true}))
                .unwrap(),
            json!({"ok":true})
        );
        assert!(!broken.exists());
        assert!(
            controller.initial().unwrap()["corrupt_rows"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert_hwpx_relink(controller, jobs, template);
    }

    fn assert_hwpx_relink(
        controller: &dyn crate::workspace_switch::ScreenController,
        jobs: &JobRegistry,
        txt: &Path,
    ) {
        let mut job = Job {
            name: "HWPX".into(),
            template_path: txt.with_file_name("missing.hwpx").to_str().unwrap().into(),
            ..Job::default()
        };
        jobs.save(&mut job, false).unwrap();
        let before = controller.initial().unwrap()["alerts"]["missing_template_count"]
            .as_u64()
            .unwrap();
        let refused = controller
            .dispatch(
                "relink_template",
                &json!({"name":"HWPX","path":txt,"confirm":true}),
            )
            .unwrap();
        assert_eq!(refused["ok"], false);
        assert!(refused["error"].as_str().unwrap().contains("삭제하고 새로"));
        let hwpx = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../examples/onboarding/templates/계약체결안내.hwpx")
            .canonicalize()
            .unwrap();
        assert_eq!(
            controller
                .dispatch("relink_template", &json!({"name":"HWPX","path":hwpx}))
                .unwrap()["needs_confirm"],
            true
        );
        let result = controller
            .dispatch(
                "relink_template",
                &json!({"name":"HWPX","path":hwpx,"confirm":true}),
            )
            .unwrap();
        assert_eq!(result["relinked"], true);
        assert!(!result["restated"].as_str().unwrap().is_empty());
        assert_eq!(
            controller.initial().unwrap()["alerts"]["missing_template_count"]
                .as_u64()
                .unwrap(),
            before - 1
        );
    }

    fn assert_read_after_job_changes(
        controller: &dyn crate::workspace_switch::ScreenController,
        jobs: &JobRegistry,
        template: &Path,
        snapshots: &mpsc::Receiver<Value>,
    ) {
        let wait_ready = |name: &str| loop {
            let snapshot = snapshots.recv_timeout(Duration::from_secs(5)).unwrap();
            if snapshot["selected"] == name
                && snapshot["detail"]["pairing_detail"]["first_row"]["state"] == "ready"
            {
                assert_eq!(
                    snapshot["detail"]["pairing_detail"]["rows"][0]["preview"],
                    "복구한 값"
                );
                break;
            }
        };
        jobs.rename("계약", "새 계약").unwrap();
        controller.dispatch("refresh", &json!({})).unwrap();
        assert_eq!(controller.initial().unwrap()["detail"], Value::Null);
        controller
            .dispatch("refresh", &json!({"select":"새 계약"}))
            .unwrap();
        wait_ready("새 계약");
        controller
            .dispatch("refresh", &json!({"select":"없는작업"}))
            .unwrap();
        assert_eq!(controller.initial().unwrap()["selected"], "새 계약");
        let cloned = controller
            .dispatch("clone_job", &json!({"name":"새 계약"}))
            .unwrap()["cloned"]
            .as_str()
            .unwrap()
            .to_owned();
        controller
            .dispatch("refresh", &json!({"select":cloned}))
            .unwrap();
        wait_ready(&cloned);
        controller
            .dispatch("delete_job", &json!({"name":cloned}))
            .unwrap();
        assert_eq!(controller.initial().unwrap()["selected"], "");
        controller.dispatch("undo_delete_job", &json!({})).unwrap();
        controller
            .dispatch("refresh", &json!({"select":cloned}))
            .unwrap();
        wait_ready(&cloned);
        assert_eq!(
            controller
                .dispatch(
                    "relink_template",
                    &json!({"name":cloned,"path":template,"confirm":true})
                )
                .unwrap()["relinked"],
            true
        );
        wait_ready(&cloned);
        assert_eq!(
            controller.initial().unwrap()["detail"]["template_path"],
            template.to_str().unwrap()
        );
        let drifted = controller.initial().unwrap();
        assert_eq!(drifted["detail"]["health"]["severity"], 2);
        assert_eq!(
            drifted["detail"]["health_causes"],
            json!([{"severity":2,"text":"템플릿 구조가 확정 매핑과 달라졌습니다."}])
        );
        let mut updated = jobs.load(&cloned).unwrap();
        updated.mapping.mappings.push(
            hwpx_filler::mapping::FieldMapping::new("새 필드", "사업명", "text", "", "", None)
                .unwrap(),
        );
        jobs.save(&mut updated, true).unwrap();
        controller.dispatch("refresh", &json!({})).unwrap();
        let matched = controller.initial().unwrap();
        assert_eq!(matched["detail"]["health_causes"], json!([]));
        assert_eq!(
            matched["detail"]["pairing_detail"]["rows"][1]["preview"],
            "복구한 값"
        );
        jobs.rename("새 계약", "계약").unwrap();
        controller
            .dispatch("refresh", &json!({"select":"계약"}))
            .unwrap();
        wait_ready("계약");
    }

    fn assert_clone_refresh_preserves_selection(
        controller: &dyn crate::workspace_switch::ScreenController,
        pushes: &Mutex<Vec<Value>>,
    ) {
        let cloned = controller
            .dispatch("clone_job", &json!({"name":"계약"}))
            .unwrap();
        assert_eq!(cloned["ok"], true);
        let before_refresh = pushes.lock().unwrap().len();
        controller.dispatch("refresh", &json!({})).unwrap();
        let refreshed = controller.initial().unwrap();
        assert_eq!(refreshed["selected"], "계약");
        assert_eq!(refreshed["counts"]["all"], 2);
        assert!(pushes.lock().unwrap().len() > before_refresh);
    }

    fn assert_query_preserves_selected_detail(
        controller: &dyn crate::workspace_switch::ScreenController,
        pushes: &Mutex<Vec<Value>>,
    ) {
        controller
            .dispatch("set_query", &json!({"text":"찾지 못함"}))
            .unwrap();
        let filtered = controller.initial().unwrap();
        assert!(
            filtered["sections"][0]["rows"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert_eq!(filtered["detail"]["name"], "계약");
        assert_eq!(filtered["detail"]["data_bound"], false);
        assert_eq!(filtered["detail"]["data_label"], "");
        assert_eq!(filtered["detail"]["data_path"], "");
        assert_eq!(pushes.lock().unwrap().len(), 2);
    }

    fn package_graph(home: &Path) -> Arc<PackageGraph> {
        use crate::generation_gate::GenerationGate;
        use crate::onboarding_controller::OnboardingController;
        use crate::workspace_runtime::RuntimeBuilder;
        let locations = Locations::new(
            Path::new("C:/unused"),
            Some(home.to_owned().into_os_string()),
        );
        let onboarding = Arc::new(OnboardingController::new(
            locations.tutorial_workspace_root(),
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/tutorial"),
            false,
            |message| panic!("package onboarding: {message}"),
        ));
        let builder = Arc::new(RuntimeBuilder {
            locations: locations.clone(),
            onboarding: onboarding.clone(),
            generation: Arc::new(GenerationGate::new()),
            alert: Arc::new(|message| panic!("package runtime: {message}")),
        });
        let switch = WorkspaceSwitch::new(
            locations,
            |_, _| Ok(None),
            move |home, push, token| builder.build(home, push, token),
        )
        .unwrap();
        let graph = Arc::new(PackageGraph::new(switch));
        onboarding.bind_graph(&graph).unwrap();
        graph
    }

    fn save_package_work(
        graph: &PackageGraph,
        name: &str,
        template: &Path,
        data: &Path,
        seat: bool,
    ) {
        graph.dispatch("editor", "new_session", &json!({})).unwrap();
        graph
            .dispatch("editor", "use_library_template", &json!({"path":template}))
            .unwrap();
        graph
            .active_resources()
            .unwrap()
            .editor
            .load_data_path(data, None, 0)
            .unwrap();
        graph
            .dispatch("editor", "goto_section", &json!({"section":"binding"}))
            .unwrap();
        graph
            .dispatch("editor", "confirm_suggested", &json!({}))
            .unwrap();
        graph
            .dispatch("editor", "set_name", &json!({"name":name}))
            .unwrap();
        let saved = graph.dispatch("editor", "save", &json!({})).unwrap();
        assert_eq!(saved, json!({"ok":true,"saved_name":name}));
        if seat {
            graph
                .dispatch("job", "select_job", &json!({"name":name}))
                .unwrap();
            assert!(
                !graph
                    .active_resources()
                    .unwrap()
                    .jobs
                    .load(name)
                    .unwrap()
                    .authority_id
                    .is_empty()
            );
        }
    }

    fn inspect_package(graph: &PackageGraph, path: &Path) -> Value {
        let result = graph
            .dispatch("library", "inspect_work_package", &json!({"path":path}))
            .unwrap();
        assert_eq!(result["ok"], true, "{result}");
        result
    }

    fn assert_runtime_library_guard(graph: &PackageGraph, name: &str) {
        graph.dispatch("job", "set_none", &json!({})).unwrap();
        graph
            .dispatch("job", "toggle_record", &json!({"index":0,"value":true}))
            .unwrap();
        let refused = graph
            .dispatch("library", "delete_job", &json!({"name":name}))
            .unwrap();
        assert_eq!(refused["needs_confirm"], true);
        assert_eq!(refused["open_session"], true);
        assert_eq!(refused["screen"], "job");
        assert!(graph.active_resources().unwrap().jobs.load(name).is_ok());
        graph.dispatch("job", "set_none", &json!({})).unwrap();
    }

    fn import_package(graph: &PackageGraph, path: &Path, basis: &Value) -> Value {
        graph
            .dispatch(
                "library",
                "import_work_package",
                &json!({"path":path,"basis":basis}),
            )
            .unwrap()
    }

    fn generate_package_work(graph: &PackageGraph, name: &str, output: &Path) {
        graph
            .dispatch("job", "select_job", &json!({"name":name}))
            .unwrap();
        graph.dispatch("job", "set_all", &json!({})).unwrap();
        fs::create_dir_all(output).unwrap();
        let resources = graph.active_resources().unwrap();
        resources
            .job
            .set_output_folder(output.to_str().unwrap())
            .unwrap();
        graph
            .dispatch("job", "resolve_execution", &json!({}))
            .unwrap();
        let result = resources.job.generate(false, "package-generation").unwrap();
        assert_eq!(result["ok"], true, "{result}");
        assert_eq!(result["succeeded"], 3, "{result}");
        assert_eq!(result["failed"], 0, "{result}");
        assert_eq!(
            fs::read_dir(output)
                .unwrap()
                .filter(|entry| entry
                    .as_ref()
                    .unwrap()
                    .path()
                    .extension()
                    .is_some_and(|extension| extension == "hwpx"))
                .count(),
            3
        );
        let job = resources.jobs.load(name).unwrap();
        assert!(!job.authority_id.is_empty());
        assert!(job.template_path.contains("template_authority"));
    }

    #[test]
    fn exported_package_crosses_homes_and_generates_with_registered_data_without_editor() {
        let workspace = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let root = workspace.join(format!(".cache/package-product-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let sender_home = root.join("sender");
        let sender = package_graph(&sender_home);
        let assets = workspace.join("examples/onboarding");
        let data = root.join("sender.csv");
        fs::copy(assets.join("data/계약목록.csv"), &data).unwrap();
        let template = sender
            .active_resources()
            .unwrap()
            .template_files
            .copy_into_library(&assets.join("templates/계약체결안내.hwpx"))
            .unwrap();
        for name in ["계약A", "계약B"] {
            save_package_work(&sender, name, &template, &data, true);
        }
        assert_runtime_library_guard(&sender, "계약B");
        let group_settings =
            crate::template_groups::GroupSettings::new(sender_home.join("settings.json"), |_| {});
        group_settings
            .update_template_state("hwpx", |groups, _| {
                groups.insert("계약체결안내.hwpx".into(), "유지".into());
                groups.insert("deleted.hwpx".into(), "삭제됨".into());
            })
            .unwrap();
        let snapshot = sender.initial("tpl").unwrap();
        assert!(
            snapshot["column"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .all(|row| row.get("group").is_none())
        );
        assert_eq!(
            group_settings.load_template_groups("hwpx").unwrap(),
            std::collections::BTreeMap::from([("계약체결안내.hwpx".into(), "유지".into())])
        );
        let archive = root.join("보낸작업.narumi");
        let exported = sender
            .dispatch(
                "library",
                "export_work_package",
                &json!({"path":archive,"names":["계약A","계약A","계약B"]}),
            )
            .unwrap();
        assert_eq!(
            exported,
            json!({"ok":true,"path":archive,"jobs":2,"templates":1,"skipped":[],"without_contract":[]})
        );
        let receiver = package_graph(&root.join("receiver"));
        let receiver_data = root.join("받은데이터.csv");
        fs::copy(&data, &receiver_data).unwrap();
        assert_eq!(
            receiver
                .dispatch(
                    "pool",
                    "register_excel",
                    &json!({"name":"우리 계약","path":receiver_data})
                )
                .unwrap()["ok"],
            true
        );
        let before_editor = receiver.initial("editor").unwrap();
        let inspected = inspect_package(&receiver, &archive);
        assert_eq!(inspected["view"]["title"], "작업 2개를 불러옵니다");
        assert_eq!(
            inspected["view"]["data_notice"],
            "데이터는 들어 있지 않습니다."
        );
        let imported = import_package(&receiver, &archive, &inspected["basis"]);
        assert_eq!(
            imported,
            json!({"ok":true,"imported":["계약A","계약B"],"bound":["계약A","계약B"],"outcomes":[{"name":"계약A","status":"bound"},{"name":"계약B","status":"bound"}],"message":""})
        );
        for (index, name) in ["계약A", "계약B"].into_iter().enumerate() {
            let job = receiver
                .active_resources()
                .unwrap()
                .jobs
                .load(name)
                .unwrap();
            assert_eq!(
                job.data_binding(),
                (receiver_data.to_str().unwrap(), "", 0, "")
            );
            assert_eq!((job.template_revision, job.binding_revision), (1, 1));
            assert!(job.authority_id.is_empty() && job.reviewed_rules.is_empty());
            if index == 0 {
                receiver
                    .dispatch("job", "select_job", &json!({"name":name}))
                    .unwrap();
                assert!(receiver.initial("job").unwrap()["data_notice"].is_null());
            }
            generate_package_work(&receiver, name, &root.join(format!("output-{index}")));
        }
        assert_bound_data_switch(&receiver, &data, &root);
        assert_eq!(receiver.initial("editor").unwrap(), before_editor);
        assert_package_reuses_the_configured_template_root(&receiver, &archive, &root);
        assert_unbound_package_can_use_later_data(&archive, &data, &root);
        assert_package_privacy_and_tamper_refusal(&receiver, &archive, &data, &root);
        assert_export_all_and_confirmations(&sender, &assets, &data, &root);
        drop(receiver);
        drop(sender);
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_package_reuses_the_configured_template_root(
        graph: &PackageGraph,
        archive: &Path,
        root: &Path,
    ) {
        let resources = graph.active_resources().unwrap();
        let package = read_work_package(archive).unwrap();
        let template = &package.manifest.templates[0];
        let configured = root.join("custom-templates");
        let nested = configured.join("하위");
        fs::create_dir_all(&nested).unwrap();
        let existing = nested.join("기존.hwpx");
        fs::write(&existing, &package.templates[&template.digest]).unwrap();
        let old_plan = inspect_package(graph, archive);
        resources
            .templates
            .set(configured.to_str().unwrap())
            .unwrap();
        let inspected = inspect_package(graph, archive);
        let before = resources.jobs.list_jobs_with_corruption().unwrap().0;
        assert_eq!(
            import_package(graph, archive, &old_plan["basis"]),
            json!({
                "ok":false,"stale":true,"basis":inspected["basis"],"view":inspected["view"]
            })
        );
        assert_eq!(
            resources.jobs.list_jobs_with_corruption().unwrap().0,
            before
        );
        assert_eq!(inspected["view"]["templates"][0]["action"], "reuse");
        assert_eq!(
            inspected["view"]["templates"][0]["target"],
            existing.to_str().unwrap()
        );
        let imported = import_package(graph, archive, &inspected["basis"]);
        assert_eq!(imported["imported"], json!(["계약A (2)", "계약B (2)"]));
        assert_eq!(
            resources.jobs.load("계약A (2)").unwrap().template_path,
            existing.to_str().unwrap()
        );
        assert_eq!(fs::read_dir(configured).unwrap().count(), 1);
    }

    fn register_package_data(graph: &PackageGraph, path: &Path, name: &str) -> String {
        let result = graph
            .dispatch("pool", "register_excel", &json!({"name":name,"path":path}))
            .unwrap();
        assert_eq!(result["ok"], true, "{result}");
        graph
            .active_resources()
            .unwrap()
            .datasets
            .list_entries(None)
            .unwrap()
            .into_iter()
            .find(|(_, item)| item.name == name)
            .unwrap()
            .0
    }

    fn assert_bound_data_switch(graph: &PackageGraph, data: &Path, root: &Path) {
        let other = root.join("다른데이터.csv");
        fs::copy(data, &other).unwrap();
        graph
            .active_resources()
            .unwrap()
            .job
            .load_data_path(&other, None, 0)
            .unwrap();
        graph.dispatch("job", "set_all", &json!({})).unwrap();
        graph
            .dispatch("job", "select_job", &json!({"name":"계약A"}))
            .unwrap();
        let snapshot = graph.initial("job").unwrap();
        assert_eq!(snapshot["selected_count"], 0);
        assert_eq!(
            snapshot["data_notice"]["text"],
            "이 작업에 연결된 데이터 '받은데이터.csv' 을(를) 불러왔습니다. 항목 선택은 초기화됐습니다."
        );
    }

    fn assert_unbound_package_can_use_later_data(archive: &Path, data: &Path, root: &Path) {
        let graph = package_graph(&root.join("unbound-receiver"));
        let before_editor = graph.initial("editor").unwrap();
        let empty = root.join("empty.narumi");
        assert_eq!(
            graph
                .dispatch(
                    "library",
                    "export_work_package",
                    &json!({"path":empty,"confirm":true})
                )
                .unwrap(),
            json!({
                "ok":false,"error":"작업 꾸러미를 만들 수 없습니다: 내보낼 수 있는 작업이 없습니다.","skipped":[]
            })
        );
        assert!(!empty.exists());
        let plan = inspect_package(&graph, archive);
        assert_eq!(
            import_package(&graph, archive, &plan["basis"]),
            json!({
                "ok":true,"imported":["계약A","계약B"],"bound":[],
                "outcomes":[{"name":"계약A","status":"no_match"},{"name":"계약B","status":"no_match"}],
                "message":"데이터 연결이 필요합니다."
            })
        );
        let bad = root.join("미정.csv");
        let text = fs::read_to_string(data).unwrap();
        let mut lines = text.lines();
        let header = lines.next().unwrap();
        let amount = header
            .split(',')
            .position(|column| column == "계약금액")
            .unwrap();
        let mut invalid = format!("{header}\n");
        for line in lines {
            let mut columns = line.split(',').collect::<Vec<_>>();
            columns[amount] = "미정";
            invalid.push_str(&format!("{}\n", columns.join(",")));
        }
        fs::write(&bad, invalid).unwrap();
        let key = register_package_data(&graph, &bad, "미정");
        assert_eq!(
            graph
                .dispatch("job", "load_pool", &json!({"key":key}))
                .unwrap()["ok"],
            true
        );
        assert_eq!(
            graph.initial("job").unwrap()["candidates"]["top"],
            json!([])
        );
        graph
            .dispatch("job", "select_job", &json!({"name":"계약A"}))
            .unwrap();
        let snapshot = graph.initial("job").unwrap();
        assert_eq!(snapshot["job_data_unbound"], true);
        assert!(
            snapshot["data_notice"]["text"]
                .as_str()
                .unwrap()
                .contains("꾸러미 조건과 다른 연결: 계약금액(금액으로 읽히지 않는 값 3행)"),
            "{snapshot}"
        );
        assert!(
            graph
                .active_resources()
                .unwrap()
                .jobs
                .load("계약A")
                .unwrap()
                .data_path
                .is_empty()
        );
        let key = register_package_data(&graph, data, "나중 데이터");
        graph
            .dispatch("job", "load_pool", &json!({"key":key}))
            .unwrap();
        let snapshot = graph.initial("job").unwrap();
        let mut names = snapshot["candidates"]["top"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["name"].as_str().unwrap())
            .collect::<Vec<_>>();
        names.sort();
        assert_eq!(names, ["계약A", "계약B"]);
        generate_package_work(&graph, "계약A", &root.join("later-output"));
        let jobs = &graph.active_resources().unwrap().jobs;
        assert_eq!(
            jobs.load("계약A").unwrap().data_binding(),
            (data.to_str().unwrap(), "", 0, "")
        );
        assert!(jobs.load("계약B").unwrap().data_path.is_empty());
        assert_eq!(graph.initial("editor").unwrap(), before_editor);
        let editor = &graph.active_resources().unwrap().editor;
        editor.load_job("계약B").unwrap();
        editor.load_data_path(data, None, 0).unwrap();
        let snapshot = graph.initial("editor").unwrap();
        let rows = snapshot["rows"].as_array().unwrap();
        assert!(!rows.is_empty());
        for row in rows {
            assert_eq!(row["confirmed"], true, "{row}");
            assert_eq!(row["state_label"], "자동확정 · 꾸러미 조건 일치");
        }
        assert_eq!(snapshot["is_complete"], true);
        assert_eq!(
            graph.dispatch("editor", "save", &json!({})).unwrap(),
            json!({"ok":true,"saved_name":"계약B"})
        );
        generate_package_work(&graph, "계약B", &root.join("editor-output"));
    }

    fn assert_package_privacy_and_tamper_refusal(
        graph: &PackageGraph,
        archive: &Path,
        data: &Path,
        root: &Path,
    ) {
        use std::io::{Read, Write};
        let mut source = zip::ZipArchive::new(fs::File::open(archive).unwrap()).unwrap();
        assert_eq!(source.len(), 2);
        let mut manifest = String::new();
        source
            .by_name("manifest.json")
            .unwrap()
            .read_to_string(&mut manifest)
            .unwrap();
        for forbidden in [
            "data_path",
            "authority_id",
            "reviewed_rules",
            "previous_rules",
            "last_run_at",
            "favorited_at",
            "template_revision",
            data.to_str().unwrap(),
            root.to_str().unwrap(),
            "sender.csv",
        ] {
            assert!(!manifest.contains(forbidden), "leaked {forbidden}");
        }
        let records =
            hwpx_filler::data_factory::source_for_binding(data.to_str().unwrap(), "", Some(0), "")
                .unwrap()
                .records()
                .unwrap();
        for record in records {
            for value in record.values().filter(|value| {
                value.chars().count() > 1 && !value.chars().all(|letter| letter.is_ascii_digit())
            }) {
                assert!(!manifest.contains(value), "leaked {value}");
            }
        }
        let tampered = root.join("tampered.narumi");
        let mut writer = zip::ZipWriter::new(fs::File::create(&tampered).unwrap());
        for index in 0..source.len() {
            let mut entry = source.by_index(index).unwrap();
            let mut bytes = Vec::new();
            entry.read_to_end(&mut bytes).unwrap();
            if entry.name().unwrap().starts_with("templates/") {
                *bytes.last_mut().unwrap() ^= 0xff;
            }
            writer
                .start_file(
                    entry.name().unwrap(),
                    zip::write::SimpleFileOptions::default(),
                )
                .unwrap();
            writer.write_all(&bytes).unwrap();
        }
        writer.finish().unwrap();
        let before = graph.initial("library").unwrap();
        for action in ["inspect_work_package", "import_work_package"] {
            let payload = if action == "import_work_package" {
                json!({"path":tampered,"basis":"0".repeat(64)})
            } else {
                json!({"path":tampered})
            };
            let result = graph.dispatch("library", action, &payload).unwrap();
            assert_eq!(result["ok"], false);
            let error = result["error"].as_str().unwrap();
            assert!(
                error.starts_with("작업 꾸러미를 읽을 수 없습니다: "),
                "{error}"
            );
            assert!(error.contains("digest"), "{error}");
            assert_eq!(graph.initial("library").unwrap(), before);
        }
    }

    fn assert_export_all_and_confirmations(
        sender: &PackageGraph,
        assets: &Path,
        data: &Path,
        root: &Path,
    ) {
        let files = &sender.active_resources().unwrap().template_files;
        let purchase = files
            .copy_into_library(&assets.join("templates/구매추진안내.hwpx"))
            .unwrap();
        let text = files
            .copy_into_library(&assets.join("text_templates/계약안내_기안.txt"))
            .unwrap();
        for (name, template) in [("구매안내", &purchase), ("기안A", &text), ("기안B", &text)]
        {
            save_package_work(sender, name, template, data, false);
        }
        assert_eq!(
            sender.initial("library").unwrap()["export_all_enabled"],
            true
        );
        let path = root.join("all.narumi");
        assert_eq!(
            sender
                .dispatch("library", "export_work_package", &json!({"path":path}))
                .unwrap(),
            json!({
                "ok":true,"path":path,"jobs":5,"templates":3,"skipped":[],"without_contract":[]
            })
        );
        let receiver = package_graph(&root.join("all-receiver"));
        assert_eq!(
            receiver.initial("library").unwrap()["export_all_enabled"],
            false
        );
        let plan = inspect_package(&receiver, &path);
        assert_eq!(plan["view"]["title"], "작업 5개를 불러옵니다");
        assert_eq!(plan["view"]["templates"].as_array().unwrap().len(), 3);
        let imported = import_package(&receiver, &path, &plan["basis"]);
        assert_eq!(imported["ok"], true);
        assert_eq!(
            imported["imported"],
            json!(["계약A", "계약B", "구매안내", "기안A", "기안B"])
        );
        let jobs = &receiver.active_resources().unwrap().jobs;
        assert!(
            jobs.list_jobs_with_corruption()
                .unwrap()
                .0
                .iter()
                .all(|job| job.data_path.is_empty())
        );
        let first = jobs.load("기안A").unwrap();
        assert_eq!(first.media(), "txt");
        assert_eq!(
            first.template_path,
            jobs.load("기안B").unwrap().template_path
        );
        assert_selection_preset_travels(sender, &receiver, assets, data, root);
        assert_export_refusals(sender, data, root);
    }

    fn assert_selection_preset_travels(
        sender: &PackageGraph,
        receiver: &PackageGraph,
        assets: &Path,
        data: &Path,
        root: &Path,
    ) {
        let template = sender
            .active_resources()
            .unwrap()
            .template_files
            .copy_into_library(&assets.join("templates/공고서_연습.hwpx"))
            .unwrap();
        assert_eq!(
            sender
                .dispatch("tpl", "compile", &json!({"path":template,"confirm":true}))
                .unwrap()["mutated"],
            true
        );
        save_package_work(sender, "공고작업", &template, data, true);
        let mut view = sender
            .dispatch("job", "open_slot_configuration", &json!({}))
            .unwrap()["current_view"]
            .clone();
        let slots = view["projection"]["slots"].as_array().unwrap().clone();
        for slot in slots {
            if slot["effective_option_ids"].as_array().unwrap().is_empty() {
                view = sender.dispatch("job", "select_slot_option", &json!({
                    "configuration_token":view["new_configuration_token"],"slot_id":slot["slot_id"],
                    "option_id":slot["options"][0]["option_id"],"request_id":uuid::Uuid::new_v4().simple().to_string()
                })).unwrap()["current_view"].clone();
            }
        }
        let path = root.join("selection.narumi");
        assert_eq!(
            sender
                .dispatch(
                    "library",
                    "export_work_package",
                    &json!({"path":path,"names":["공고작업"]})
                )
                .unwrap()["ok"],
            true
        );
        let package = read_work_package(&path).unwrap();
        let presets = &package.manifest.jobs[0].selection_presets;
        assert_eq!(presets.len(), 1);
        assert_eq!(presets[0].name, "공고작업");
        assert!(presets[0].provenance.is_empty());
        for expected in ["공고작업", "공고작업 (2)"] {
            let plan = inspect_package(receiver, &path);
            assert_eq!(plan["view"]["presets"][0]["final_name"], expected);
            assert_eq!(import_package(receiver, &path, &plan["basis"])["ok"], true);
        }
        let registry = PresetRegistry::new(root.join("all-receiver/presets")).unwrap();
        let mut names = registry
            .list_entries()
            .unwrap()
            .into_iter()
            .map(|(_, preset)| preset.name)
            .collect::<Vec<_>>();
        names.sort();
        assert_eq!(names, ["공고작업", "공고작업 (2)"]);
    }

    fn assert_export_refusals(sender: &PackageGraph, data: &Path, root: &Path) {
        let path = root.join("confirmed.narumi");
        let missing = sender
            .dispatch(
                "library",
                "export_work_package",
                &json!({"path":path,"names":["없는 작업"]}),
            )
            .unwrap();
        assert_eq!(missing["ok"], false);
        assert!(
            missing["error"]
                .as_str()
                .unwrap()
                .starts_with("작업 꾸러미를 만들 수 없습니다: ")
        );
        assert!(!path.exists());
        let jobs = &sender.active_resources().unwrap().jobs;
        let mut broken = jobs.load("구매안내").unwrap();
        broken.template_path = root.join("missing.hwpx").to_str().unwrap().into();
        jobs.save(&mut broken, false).unwrap();
        let names = json!(["계약A", "구매안내"]);
        let asked = sender
            .dispatch(
                "library",
                "export_work_package",
                &json!({"path":path,"names":names}),
            )
            .unwrap();
        let skipped = "템플릿을 읽을 수 없는 작업은 빠집니다: 구매안내";
        assert_eq!(
            asked,
            json!({"ok":true,"needs_confirm":true,"confirm_text":skipped,"skipped":["구매안내"],"without_contract":[]})
        );
        assert!(!path.exists());
        fs::remove_file(data).unwrap();
        let asked = sender
            .dispatch(
                "library",
                "export_work_package",
                &json!({"path":path,"names":names}),
            )
            .unwrap();
        assert_eq!(
            asked["confirm_text"],
            format!(
                "{skipped}\n\n데이터를 읽을 수 없어 확인 조건 없이 내보냅니다. 받는 쪽에서 연결을 직접 확정해야 합니다."
            )
        );
        assert_eq!(asked["without_contract"], json!(["계약A"]));
        assert!(!path.exists());
        let done = sender
            .dispatch(
                "library",
                "export_work_package",
                &json!({"path":path,"names":names,"confirm":true}),
            )
            .unwrap();
        assert_eq!(done["ok"], true);
        assert_eq!(done["jobs"], 1);
        let package = read_work_package(&path).unwrap();
        assert_eq!(package.manifest.jobs[0].name, "계약A");
        assert!(package.manifest.jobs[0].data_contract.is_none());
        let refused = root.join("nothing.narumi");
        assert_eq!(
            sender
                .dispatch(
                    "library",
                    "export_work_package",
                    &json!({"path":refused,"names":["구매안내"],"confirm":true})
                )
                .unwrap(),
            json!({
                "ok":false,"error":format!("작업 꾸러미를 만들 수 없습니다: 내보낼 수 있는 작업이 없습니다.\n{skipped}"),"skipped":["구매안내"]
            })
        );
        assert!(!refused.exists());
    }

    #[test]
    fn selected_library_snapshot_uses_actual_template_fields_without_changing_filter_identity() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = workspace.join(format!(
            ".cache/library-controller-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(root.join("templates")).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let template = root.join("templates/계약.txt");
        fs::write(&template, "계약: {{계약명}} / {{새 필드}}\n").unwrap();
        assert_first_row_cache_correlation(&template);
        let jobs = Arc::new(
            JobRegistry::new(root.join("jobs"), {
                let templates = root.join("templates");
                move || templates.clone()
            })
            .unwrap(),
        );
        let datasets = Arc::new(DatasetPoolRegistry::new(root.join("datasets")).unwrap());
        let presets = Arc::new(PresetRegistry::new(root.join("presets")).unwrap());
        let template_files = Arc::new(TemplateFileStore::new({
            let templates = root.join("templates");
            move || templates.clone()
        }));
        let mut job = Job {
            name: "계약".into(),
            template_path: template.to_str().unwrap().into(),
            ..Job::default()
        };
        jobs.save(&mut job, false).unwrap();
        let template_bytes = fs::read(&template).unwrap();
        let digest = Sha256::digest(&template_bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let package = WorkPackageManifest {
            created_at: "2026-11-05T12:00:00".into(),
            templates: vec![PackagedTemplate {
                digest: digest.clone(),
                media: "txt".into(),
                display_name: "계약.txt".into(),
                size: template_bytes.len() as u64,
            }],
            jobs: vec![PackagedJob {
                name: "계약".into(),
                media: "txt".into(),
                template_digest: digest.clone(),
                mapping: job.mapping.clone(),
                filename_pattern: job.filename_pattern.clone(),
                selection_presets: Vec::new(),
                data_contract: None,
            }],
        };
        let archive = root.join("package.narumi");
        fs::write(
            &archive,
            build_work_package_bytes(&package, &HashMap::from([(digest, template_bytes)])).unwrap(),
        )
        .unwrap();
        let pushes = Arc::new(Mutex::new(Vec::new()));
        let observed = pushes.clone();
        let pause_next = Arc::new(AtomicBool::new(false));
        let pause_sink = pause_next.clone();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let release_rx = Mutex::new(release_rx);
        let (snapshot_tx, snapshot_rx) = mpsc::channel();
        let observed_jobs = jobs.clone();
        let app = WorkspaceSwitch::new(
            Locations::new(
                Path::new("C:/Users/test"),
                Some(root.as_os_str().to_os_string()),
            ),
            move |screen, snapshot| {
                assert_eq!(screen, "library");
                if pause_sink.swap(false, Ordering::SeqCst) {
                    entered_tx.send(()).unwrap();
                    release_rx.lock().unwrap().recv().unwrap();
                }
                observed.lock().unwrap().push(snapshot.clone());
                snapshot_tx.send(snapshot.clone()).unwrap();
                Ok(None)
            },
            move |home, gate, token| {
                let controller = Arc::new(LibraryController::new(
                    LibraryStores {
                        jobs: jobs.clone(),
                        datasets: datasets.clone(),
                        presets: presets.clone(),
                        template_files: template_files.clone(),
                    },
                    Locations::new(
                        Path::new("C:/Users/test"),
                        Some(root.as_os_str().to_os_string()),
                    ),
                    false,
                    gate,
                    Arc::new(|name| Ok((name == "계약").then(|| json!({"screen":"job"})))),
                    Arc::new(|| false),
                ));
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("library".into(), controller)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = app.active().controller("library").unwrap();
        let initial = controller.initial().unwrap();
        assert_eq!(initial["selected"], "");
        controller
            .dispatch("select_work", &json!({"name":"계약"}))
            .unwrap();
        let selected = controller.initial().unwrap();
        assert_eq!(
            selected["detail"]["pairing_detail"]["rows"][0]["template_field"],
            "계약명"
        );
        assert_eq!(
            selected["detail"]["pairing_detail"]["rows"][1]["row_state"],
            "needs_source"
        );
        assert_query_preserves_selected_detail(controller.as_ref(), &pushes);
        assert_eq!(
            controller
                .dispatch("toggle_favorite", &json!({"name":"계약","value":true}))
                .unwrap()["ok"],
            true
        );
        assert_clone_refresh_preserves_selection(controller.as_ref(), &pushes);
        let guarded = controller
            .dispatch("delete_job", &json!({"name":"계약"}))
            .unwrap();
        assert_eq!(guarded["needs_confirm"], true);
        assert_eq!(guarded["screen"], "job");
        assert_eq!(controller.initial().unwrap()["detail"]["name"], "계약");
        assert_eq!(
            controller
                .dispatch("delete_job", &json!({"name":"계약","confirm":true}))
                .unwrap()["undo"],
            true
        );
        assert_eq!(controller.initial().unwrap()["selected"], "");
        assert_eq!(pushes.lock().unwrap().last().unwrap()["selected"], "");
        assert_eq!(
            controller.dispatch("undo_delete_job", &json!({})).unwrap()["name"],
            "계약"
        );
        let inspected = controller
            .dispatch(
                "inspect_work_package",
                &json!({"path":archive.to_str().unwrap()}),
            )
            .unwrap();
        assert_eq!(inspected["ok"], true);
        assert_eq!(inspected["view"]["title"], "작업 1개를 불러옵니다");
        assert_eq!(inspected["basis"].as_str().unwrap().len(), 64);
        let imported = controller
            .dispatch(
                "import_work_package",
                &json!({
                    "path":archive.to_str().unwrap(), "basis":inspected["basis"]
                }),
            )
            .unwrap();
        assert_eq!(imported["ok"], true);
        assert_eq!(imported["outcomes"][0]["status"], "no_contract");
        assert_eq!(imported["message"], "데이터 연결이 필요합니다.");
        assert_eq!(imported["imported"].as_array().unwrap().len(), 1);
        let exported_path = archive.with_file_name("exported.narumi");
        let export_payload = json!({"path":exported_path.to_str().unwrap(),"names":["계약"]});
        let preview = controller
            .dispatch("export_work_package", &export_payload)
            .unwrap();
        assert_eq!(preview["needs_confirm"], true);
        assert_eq!(preview["without_contract"], json!(["계약"]));
        assert!(!exported_path.exists());
        let exported = controller
            .dispatch(
                "export_work_package",
                &json!({
                    "path":exported_path.to_str().unwrap(),"names":["계약"],"confirm":true,
                }),
            )
            .unwrap();
        assert_eq!(exported["ok"], true);
        assert_eq!(
            read_work_package(&exported_path)
                .unwrap()
                .manifest
                .jobs
                .len(),
            1
        );
        let replacement = template.with_file_name("replacement.txt");
        fs::write(&replacement, "새 {{계약명}}").unwrap();
        let raw = template.with_file_name("raw.txt");
        fs::write(&raw, "토큰 없는 문서").unwrap();
        let missing = template.with_file_name("missing.txt");
        let missing_result = controller
            .dispatch(
                "relink_template",
                &json!({"name":"계약","path":missing.to_str().unwrap()}),
            )
            .unwrap();
        assert_eq!(missing_result["ok"], false);
        assert!(
            missing_result["error"].as_str().unwrap().contains(
                &hwpx_filler::text_render::python_repr(&json!(missing.to_string_lossy()))
            ),
            "actual={missing_result:?}"
        );
        assert_eq!(
            controller
                .dispatch(
                    "relink_template",
                    &json!({"name":"계약","path":"other.hwpx"})
                )
                .unwrap()["ok"],
            false
        );
        assert_eq!(
            controller
                .dispatch(
                    "relink_template",
                    &json!({"name":"계약","path":raw.to_str().unwrap()})
                )
                .unwrap()["ok"],
            false
        );
        let confirmation = controller
            .dispatch(
                "relink_template",
                &json!({
                    "name":"계약","path":replacement.to_str().unwrap(),
                }),
            )
            .unwrap();
        assert_eq!(confirmation["needs_confirm"], true);
        assert_eq!(
            controller
                .dispatch(
                    "relink_template",
                    &json!({
                        "name":"계약","path":replacement.to_str().unwrap(),"confirm":true,
                    })
                )
                .unwrap()["relinked"],
            true
        );
        controller
            .dispatch("select_work", &json!({"name":"계약"}))
            .unwrap();
        assert_eq!(
            controller.initial().unwrap()["detail"]["template_path"],
            replacement.to_str().unwrap()
        );
        controller
            .dispatch("select_work", &json!({"name":""}))
            .unwrap();
        let before = pushes.lock().unwrap().len();
        pause_next.store(true, Ordering::SeqCst);
        let first = controller.clone();
        let earlier = std::thread::spawn(move || {
            first
                .dispatch("set_query", &json!({"text":"earlier"}))
                .unwrap();
        });
        entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        let second = controller.clone();
        let later = std::thread::spawn(move || {
            second
                .dispatch("set_query", &json!({"text":"later"}))
                .unwrap();
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        while controller.initial().unwrap()["query"] != "later" {
            assert!(
                Instant::now() < deadline,
                "later library mutation did not land"
            );
            std::thread::yield_now();
        }
        release_tx.send(()).unwrap();
        earlier.join().unwrap();
        later.join().unwrap();
        let snapshots = pushes.lock().unwrap();
        assert_eq!(snapshots[before]["query"], "earlier");
        assert_eq!(snapshots[before + 1]["query"], "later");
        drop(snapshots);
        assert_first_row_worker_refreshes(
            controller.as_ref(),
            &observed_jobs,
            &template,
            &snapshot_rx,
        );
        drop(app);
        // The test owns this checked workspace subtree only.
        let root = workspace.join(format!(
            ".cache/library-controller-{}-{stamp}",
            std::process::id()
        ));
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        fs::remove_dir_all(root).unwrap();
    }
}
