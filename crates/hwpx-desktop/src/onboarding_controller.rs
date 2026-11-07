//! One durable tutorial state shared by user and isolated practice graphs.

use crate::legacy_practice::LegacyPractice;
use crate::live_graph::{LiveGraph, ProductObserver};
use crate::onboarding_state::OnboardingState;
use crate::tutorial_seed::{derived_for, seed_before_switch};
use crate::tutorial_workspace::TutorialWorkspace;
use crate::workspace_runtime::RuntimeResources;
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, OnceLock, Weak};

pub struct OnboardingController {
    state: Mutex<OnboardingState>,
    alert: Arc<dyn Fn(String) + Send + Sync>,
    push: Mutex<(Option<PushGate>, Option<PushGate>)>,
    graph: OnceLock<Weak<LiveGraph<RuntimeResources>>>,
    legacy_cleanup: OnceLock<LegacyPractice>,
}

impl OnboardingController {
    pub fn new(
        root: PathBuf,
        assets: PathBuf,
        first_launch: bool,
        alert: impl Fn(String) + Send + Sync + 'static,
    ) -> Self {
        let alert: Arc<dyn Fn(String) + Send + Sync> = Arc::new(alert);
        Self {
            state: Mutex::new(OnboardingState::new(
                TutorialWorkspace::new(root, assets, {
                    let alert = alert.clone();
                    move |message| alert(message)
                }),
                first_launch,
            )),
            alert,
            push: Mutex::new((None, None)),
            graph: OnceLock::new(),
            legacy_cleanup: OnceLock::new(),
        }
    }

    fn state(&self) -> Result<MutexGuard<'_, OnboardingState>, GraphError> {
        Ok(self.state.lock().map_err(|_| "tutorial state poisoned")?)
    }

    pub fn bind_push(&self, gate: PushGate, practice: bool) {
        if let Ok(mut push) = self.push.lock() {
            if practice {
                push.1 = Some(gate)
            } else {
                push.0 = Some(gate)
            }
        }
    }

    pub fn bind_legacy_cleanup(&self, cleanup: LegacyPractice) -> Result<(), GraphError> {
        self.legacy_cleanup
            .set(cleanup)
            .map_err(|_| "legacy tutorial cleanup already bound".into())
    }

    fn legacy_cleanup(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let cleanup = self
            .legacy_cleanup
            .get()
            .ok_or("legacy tutorial cleanup unavailable")?;
        if action == "cleanup_preview" {
            return cleanup.cleanup_preview();
        }
        let token = payload["token"]
            .as_str()
            .ok_or("연습 파일 정리 토큰이 올바르지 않습니다.")?;
        let result = cleanup.cleanup(token)?;
        let mut state = self.state()?;
        let snapshot = self.snapshot(&mut state)?;
        drop(state);
        self.emit(&snapshot)?;
        Ok(result)
    }

    pub fn bind_graph(
        self: &Arc<Self>,
        graph: &Arc<LiveGraph<RuntimeResources>>,
    ) -> Result<(), GraphError> {
        self.graph
            .set(Arc::downgrade(graph))
            .map_err(|_| "tutorial graph already bound")?;
        graph.bind_observer(self.clone())
    }

    fn graph(&self) -> Result<Arc<LiveGraph<RuntimeResources>>, GraphError> {
        self.graph
            .get()
            .and_then(Weak::upgrade)
            .ok_or_else(|| "tutorial graph unavailable".into())
    }

    fn emit(&self, snapshot: &Value) -> Result<(), GraphError> {
        let push = self.push.lock().map_err(|_| "tutorial push poisoned")?;
        for gate in [&push.0, &push.1].into_iter().flatten() {
            gate.push("tutorial", snapshot)?;
        }
        Ok(())
    }

    fn snapshot(&self, state: &mut OnboardingState) -> Result<Value, GraphError> {
        let mut snapshot = state.snapshot();
        let event = state.progress.beat().and_then(|beat| beat.event.as_deref());
        if let Some(
            event @ ("field_range_selected"
            | "item_range_selected"
            | "include_range_selected"
            | "omit_range_selected"),
        ) = event
            && let Some(graph) = self.graph.get().and_then(Weak::upgrade)
        {
            let resources = graph.active_resources()?;
            snapshot["beat"]["range"] =
                crate::onboarding_match_authoring::guide_range(state, &resources, event)?
                    .unwrap_or(Value::Null);
        }
        Ok(snapshot)
    }

    fn observation_token(&self) -> Result<Value, GraphError> {
        Ok(self.state()?.product_token())
    }

    /// Suggest the current practice asset without restricting the native picker.
    pub fn file_picker_hint(&self, kind: &str, screen: &str) -> Result<String, GraphError> {
        Ok(self.state()?.file_picker_hint(kind, screen))
    }

    fn rewind_unmet_inputs(
        &self,
        state: &mut OnboardingState,
        resources: &RuntimeResources,
    ) -> Result<bool, GraphError> {
        let Some(beat) = state.progress.beat() else {
            return Ok(false);
        };
        if beat.screen.as_deref() == Some("authoring")
            && !crate::onboarding_match_authoring::practice_template_open(state, resources)?
        {
            let first = if state.progress.selected.as_deref() == Some("change_apply") {
                "pick_job"
            } else {
                "open_list"
            };
            return Ok(state.progress.rewind(first));
        }
        let expected = match state.progress.selected.as_deref() {
            Some("first_hwpx") => ("물품 구매입찰 공고.hwpx", "공고"),
            Some("contract_txt") => ("낙찰자 선정 및 계약체결 안내.txt", "계약"),
            _ => return Ok(false),
        };
        if beat.screen.as_deref() != Some("editor") {
            return Ok(false);
        }
        let context = state.progress.context().ok_or("연습 기록이 없습니다.")?;
        let asset = |name: &str| {
            context
                .get("assets")
                .and_then(|assets| assets.get(name))
                .and_then(|entry| entry.get("path"))
                .and_then(Value::as_str)
                .unwrap_or("")
        };
        let editor = resources.editor.snapshot()?;
        if editor["template_path"] != asset(expected.0) {
            return Ok(state.progress.rewind("template"));
        }
        if editor["data_path"] != asset("공고목록.xlsx") || editor["data_sheet"] != expected.1 {
            return Ok(state.progress.rewind("data"));
        }
        Ok(false)
    }

    fn observe_product(
        &self,
        token: &Value,
        screen: &str,
        action: &str,
        payload: &Value,
        result: &Value,
    ) -> Result<(), GraphError> {
        let mut state = self.state()?;
        if !state.accepts_product_token(token) {
            return Ok(());
        }
        let graph = self.graph()?;
        let resources = graph.active_resources()?;
        if result.get("ok") == Some(&Value::Bool(false))
            || result.get("needs_confirm") == Some(&Value::Bool(true))
            || result.get("needs_overwrite") == Some(&Value::Bool(true))
        {
            return Ok(());
        }
        let source = resources
            .authoring
            .active_facts()?
            .and_then(|facts| facts["source_path"].as_str().map(PathBuf::from));
        state.note_practice_save(screen, action, result, source.as_deref())?;
        let (ready, reason) = state.resources();
        if !ready {
            state.recovery = Some(reason);
            state.progress.pause();
            state.persist()?;
            let snapshot = self.snapshot(&mut state)?;
            drop(state);
            self.emit(&snapshot)?;
            return Ok(());
        }
        let before = state.progress.context().cloned();
        let rewound = self.rewind_unmet_inputs(&mut state, &resources)?;
        let Some(event) = state.progress.beat().and_then(|beat| beat.event.clone()) else {
            return Ok(());
        };
        if crate::tutorial_lessons::is_ui_press_event(&event) {
            if rewound {
                state.persist()?;
                let snapshot = self.snapshot(&mut state)?;
                drop(state);
                self.emit(&snapshot)?;
            }
            return Ok(());
        }
        let context = crate::onboarding_product::match_event(
            &mut state, &resources, &event, screen, action, payload, result,
        )?;
        let advanced = context
            .as_ref()
            .is_some_and(|context| state.progress.observed(&event, Some(context)))
            || rewound;
        let context_changed = state.progress.context() != before.as_ref();
        if advanced || context_changed {
            state.persist()?;
        }
        if advanced
            || context_changed
            || matches!(
                action,
                "use_library_template"
                    | "select_job"
                    | "prefer_work"
                    | "toggle_record"
                    | "set_all"
                    | "set_none"
            )
        {
            let snapshot = self.snapshot(&mut state)?;
            drop(state);
            self.emit(&snapshot)?;
        }
        Ok(())
    }

    fn capture_return(
        &self,
        screen: &str,
        resources: &RuntimeResources,
    ) -> Result<Value, GraphError> {
        let editor = resources.editor.selected_job_name()?.unwrap_or_default();
        let authoring = resources
            .authoring
            .active_facts()?
            .and_then(|value| value["id"].as_str().map(str::to_owned))
            .unwrap_or_default();
        let row = resources.workbench.initial()?["card"]["source_row"].clone();
        Ok(
            json!({"screen":screen,"editor_job":editor,"authoring_id":authoring,"workbench_row":row}),
        )
    }

    fn loss(
        &self,
        screen: &str,
        action: &str,
        scenario: Option<&str>,
    ) -> Result<String, GraphError> {
        let graph = self.graph()?;
        let mut lines = Vec::new();
        if screen == "editor" && graph.active_resources()?.editor.has_unsaved_work()? {
            lines.push("저장하지 않은 작업 편집 내용이 사라집니다. 계속할까요?".to_owned())
        }
        let keeps_home = if action != "restart" {
            if let Some(home) = graph.cached_practice_home()? {
                let state = self.state()?;
                let lesson_id = if action == "resume" {
                    state.progress.selected.as_deref()
                } else {
                    scenario
                };
                lesson_id.is_some_and(|id| {
                    let checkpoint = state.progress.checkpoint(id);
                    let resumable = action == "resume"
                        || crate::tutorial_lessons::lesson(id).is_some_and(|lesson| {
                            checkpoint > 0 && checkpoint < lesson.beats.len()
                        });
                    resumable
                        && state
                            .progress
                            .records
                            .get(id)
                            .and_then(|entry| entry.pointer("/context/home"))
                            .and_then(Value::as_str)
                            == home.to_str()
                })
            } else {
                false
            }
        } else {
            false
        };
        if matches!(action, "start" | "select" | "restart" | "resume") && !keeps_home {
            let reasons = graph.practice_close_reasons()?;
            if !reasons.is_empty() {
                lines.push(format!(
                    "지금 연습의 다음 진행 상태가 사라집니다:\n\n• {}",
                    reasons.join("\n• ")
                ))
            }
        }
        Ok(lines.join("\n\n"))
    }

    fn transition(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let graph = self.graph()?;
        let resources = graph.active_resources()?;
        resources
            .job
            .with_transition_lease(|| self.transition_guarded(&graph, &resources, action, payload))
            .map_err(|error| -> GraphError { error.into() })?
    }

    fn transition_guarded(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        resources: &RuntimeResources,
        action: &str,
        payload: &Value,
    ) -> Result<Value, GraphError> {
        resources
            .job
            .raise_if_generating_before_swap("튜토리얼을 전환하세요")?;
        let basis = resources.job.transition_basis()?;
        if action == "preflight" {
            let screen = payload["screen"].as_str().unwrap_or("");
            let operation = payload["action"].as_str().unwrap_or("");
            let return_context = self.capture_return(screen, resources)?;
            let loss = self.loss(screen, operation, payload["scenario_id"].as_str())?;
            return self
                .state()?
                .preflight(payload, basis, loss, Some(return_context));
        }
        let loss = self.loss("editor", action, payload["scenario_id"].as_str())?;
        let return_context = self.capture_return("job", resources)?;
        let mut state = self.state()?;
        let previous = state.progress.clone();
        let prior_return = state.return_context.clone();
        let context =
            state.transition_context(action, payload, &basis, &loss, Some(return_context))?;
        let result = if action == "exit" {
            state.progress.pause();
            if state.return_context.is_some() {
                if let Err(error) = graph.leave_practice() {
                    state.recovery = Some(format!(
                        "원래 작업으로 돌아오지 못했습니다: {error}. 연습 종료를 다시 시도하세요."
                    ));
                    Ok(json!({"ok":false,"error":state.recovery,"screen":"library"}))
                } else {
                    let original = state.return_context.take();
                    state.recovery = None;
                    state.progress.result = None;
                    let (screen, notice) = self.restore_screen(graph, original.as_ref());
                    Ok(json!({"ok":true,"screen":screen,"notice":notice}))
                }
            } else {
                Ok(json!({"ok":true,"screen":"job","notice":""}))
            }
        } else {
            self.enter(graph, &mut state, action, payload, context)
        };
        match result {
            Ok(result) => {
                state.persist()?;
                let snapshot = self.snapshot(&mut state)?;
                drop(state);
                self.emit(&snapshot)?;
                Ok(result)
            }
            Err(error) => {
                state.progress = previous;
                state.return_context = prior_return;
                state.persist()?;
                Err(error)
            }
        }
    }

    fn enter(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        state: &mut OnboardingState,
        action: &str,
        payload: &Value,
        context: Option<Value>,
    ) -> Result<Value, GraphError> {
        let id = if action == "resume" {
            state.progress.selected.clone().ok_or("과정을 고르세요.")?
        } else {
            payload["scenario_id"]
                .as_str()
                .ok_or("과정을 다시 고르세요.")?
                .into()
        };
        if action == "resume" {
            let (ready, reason) = state.resources();
            if !ready {
                state.recovery = Some(reason.clone());
                return Err(reason.into());
            }
            let home = state
                .progress
                .context()
                .and_then(|ctx| ctx.get("home"))
                .and_then(Value::as_str)
                .ok_or("연습 파일을 먼저 준비하세요.")?;
            graph.enter_practice(PathBuf::from(home))?;
            state.progress.select(&id)?;
        } else if action != "restart" && self.resumable_home(state, &id).is_some() {
            state.progress.select(&id)?;
            let home = self
                .resumable_home(state, &id)
                .ok_or("연습 파일을 먼저 준비하세요.")?;
            graph.enter_practice(home)?;
        } else {
            if action != "restart" {
                state.progress.select(&id)?;
            }
            state.progress.restart(&id)?;
            let (derived, name, _sheet) = derived_for(&id);
            let mut seeded = state.workspace.seed(&id, derived, name)?;
            let seeded_context = seed_before_switch(&id, &mut seeded)?;
            state
                .progress
                .context_mut()
                .ok_or("과정을 고르세요.")?
                .extend(seeded_context);
            graph.enter_practice(seeded.home.clone())?;
            if let Err(error) = self.after_switch(graph, &id, state) {
                let _ = graph.leave_practice();
                return Err(error);
            }
            state.workspace.sweep(&id, &seeded.home);
        }
        if context.is_some() && graph.practice_home()?.is_some() {
            state.return_context = context
        }
        let (ready, reason) = state.resources();
        state.recovery = (!ready).then_some(reason);
        if !ready {
            state.progress.pause();
        }
        self.rewind_on_entry(graph, state)?;
        let beat = state.snapshot()["beat"].clone();
        let screen = beat["entry_screen"]
            .as_str()
            .or_else(|| beat["screen"].as_str())
            .unwrap_or("job");
        Ok(json!({"ok":true,"screen":screen}))
    }

    fn resumable_home(&self, state: &OnboardingState, id: &str) -> Option<PathBuf> {
        let checkpoint = state.progress.checkpoint(id);
        let lesson = crate::tutorial_lessons::lesson(id)?;
        if checkpoint == 0 || checkpoint >= lesson.beats.len() {
            return None;
        }
        let home = PathBuf::from(
            state
                .progress
                .records
                .get(id)?
                .pointer("/context/home")?
                .as_str()?,
        );
        home.is_dir().then_some(home)
    }

    fn restore_screen(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        original: Option<&Value>,
    ) -> (String, String) {
        let Some(original) = original else {
            return ("job".into(), String::new());
        };
        let restored = (|| -> Result<(String, String), GraphError> {
            let resources = graph.active_resources()?;
            let mut screen = original["screen"]
                .as_str()
                .ok_or("돌아갈 화면을 확인할 수 없습니다.")?
                .to_owned();
            match screen.as_str() {
                "editor" => {
                    if let Some(name) = original["editor_job"]
                        .as_str()
                        .filter(|name| !name.is_empty())
                    {
                        resources.editor.load_job(name)?;
                    } else {
                        screen = if resources.job.selected_job_name()?.is_empty() {
                            "library"
                        } else {
                            "job"
                        }
                        .into();
                    }
                }
                "authoring" => {
                    if let Some(id) = original["authoring_id"]
                        .as_str()
                        .filter(|id| !id.is_empty())
                    {
                        resources
                            .authoring
                            .dispatch("activate", &json!({"session_id":id}))?;
                    }
                }
                "workbench" => {
                    let opened = resources.job.dispatch("open_workbench", &json!({}))?;
                    if opened["ok"] != true {
                        return Ok(("job".into(), opened["error"].as_str().unwrap_or("").into()));
                    }
                    let card = resources.workbench.initial()?["card"].clone();
                    if let Some(row) = original.get("workbench_row")
                        && let Some(index) = card["index_map"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .find(|item| item["row"] == *row)
                            .and_then(|item| item["index"].as_u64())
                    {
                        resources
                            .workbench
                            .dispatch("set_current", &json!({"index":index}))?;
                    }
                }
                _ => (),
            }
            Ok((screen, String::new()))
        })();
        restored.unwrap_or_else(|_| ("library".into(), "돌아갈 화면을 확인할 수 없습니다.".into()))
    }

    fn rewind_on_entry(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        state: &mut OnboardingState,
    ) -> Result<(), GraphError> {
        let Some(beat) = state.progress.beat() else {
            return Ok(());
        };
        if beat.screen.as_deref() == Some("authoring") {
            let resources = graph.active_resources()?;
            let opened = resources.authoring.active_facts()?;
            let path = if state.progress.selected.as_deref() == Some("change_apply") {
                let name = state
                    .progress
                    .context()
                    .and_then(|ctx| ctx.get("job_name"))
                    .and_then(Value::as_str)
                    .unwrap_or("");
                resources.jobs.load(name).ok().map(|job| job.template_path)
            } else {
                state
                    .progress
                    .context()
                    .and_then(|ctx| ctx.get("assets"))
                    .and_then(|assets| assets.get("낙찰자 선정 및 계약체결 안내.txt"))
                    .and_then(|entry| entry.get("path"))
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            };
            let valid = opened
                .as_ref()
                .zip(path.as_ref())
                .is_some_and(|(opened, path)| {
                    opened["media"] == "txt"
                        && opened["source_path"] == *path
                        && opened["save_path"] == *path
                });
            if !valid {
                let first = if state.progress.selected.as_deref() == Some("change_apply") {
                    "pick_job"
                } else {
                    "open_list"
                };
                state.progress.rewind(first);
                return Ok(());
            }
        }
        if beat.target.as_deref() == Some("menu-item") {
            let id = state.progress.selected.as_deref().unwrap_or("");
            let checkpoint = state.progress.checkpoint(id);
            if checkpoint > 0
                && let Some(previous) = crate::tutorial_lessons::lesson(id)
                    .and_then(|lesson| lesson.beats.get(checkpoint - 1))
            {
                state.progress.rewind(&previous.id);
            }
        }
        Ok(())
    }

    fn after_switch(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        id: &str,
        state: &OnboardingState,
    ) -> Result<(), GraphError> {
        let resources = graph.active_resources()?;
        let name = state
            .progress
            .context()
            .and_then(|context| context.get("job_name"))
            .and_then(Value::as_str);
        if id == "purchase_txt" {
            resources
                .editor
                .load_job(name.ok_or("연습 작업이 없습니다.")?)?;
        }
        if id == "change_apply" {
            let name = name.ok_or("연습 작업이 없습니다.")?;
            resources
                .job
                .dispatch("prefer_work", &json!({"name":name}))?;
            let job = resources.jobs.load(name)?;
            let applied_root = resources
                .jobs
                .directory()
                .parent()
                .ok_or("연습 작업 경로가 없습니다.")?
                .join("template_authority/applied");
            let path = PathBuf::from(&job.template_path);
            if !path.starts_with(&applied_root) {
                return Err("연습에 적용된 TXT 경로를 확인할 수 없습니다.".into());
            }
            let raw = fs::read_to_string(&path)?
                .replace("\r\n", "\n")
                .replace('\r', "\n");
            let line = raw
                .lines()
                .find(|line| line.starts_with("3. "))
                .ok_or("연습 문단을 찾을 수 없습니다.")?;
            let block="{{#항목 예산재배정 예산재배정}}\n{{#선택 안내포함 안내포함}}\n{paragraph}\n{{/선택}}\n{{#선택 안내생략 안내생략}}\n\n{{/선택}}\n{{/항목}}".replace("{paragraph}",line);
            let rewritten = raw.replacen(line, &block, 1);
            let written = rewritten.replace('\n', if cfg!(windows) { "\r\n" } else { "\n" });
            crate::atomic_file::write_bytes_atomic(&path, written.as_bytes())?;
        }
        graph.refresh()?;
        Ok(())
    }
}

impl ScreenController for OnboardingController {
    fn initial(&self) -> Result<Value, GraphError> {
        let mut state = self.state()?;
        self.snapshot(&mut state)
    }

    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        if matches!(action, "cleanup_preview" | "cleanup") {
            return self.legacy_cleanup(action, payload);
        }
        if matches!(
            action,
            "preflight" | "start" | "select" | "restart" | "resume" | "exit"
        ) {
            return self.transition(action, payload);
        }
        let mut state = self.state()?;
        state.dispatch_progress(action, payload)?;
        let snapshot = self.snapshot(&mut state)?;
        drop(state);
        self.emit(&snapshot)?;
        Ok(json!(null))
    }

    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        Ok(None)
    }
}

impl ProductObserver for OnboardingController {
    fn token(&self) -> Value {
        self.observation_token().unwrap_or(Value::Null)
    }

    fn returned(&self, token: &Value, screen: &str, action: &str, payload: &Value, result: &Value) {
        if screen == "tutorial" || token.is_null() {
            return;
        }
        if let Err(error) = self.observe_product(token, screen, action, payload, result) {
            (self.alert)(format!("튜토리얼 제품 관찰 실패: {error}"));
            if let Ok(mut state) = self.state() {
                if let Err(recovery) = state.observation_failed(&error.to_string()) {
                    (self.alert)(format!("튜토리얼 복구 상태 저장 실패: {recovery}"));
                }
                let snapshot = match self.snapshot(&mut state) {
                    Ok(snapshot) => snapshot,
                    Err(error) => {
                        (self.alert)(format!("튜토리얼 복구 상태 관찰 실패: {error}"));
                        return;
                    }
                };
                drop(state);
                if let Err(push) = self.emit(&snapshot) {
                    (self.alert)(format!("튜토리얼 복구 상태 전달 실패: {push}"));
                }
            }
        }
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::OnboardingController;
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::job_registry::JobRegistry;
    use crate::legacy_practice::LegacyPractice;
    use crate::live_graph::ProductObserver;
    use crate::workspace_switch::ScreenController;
    use serde_json::json;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn cleanup_actions_use_the_bound_user_stores_and_require_current_preview() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/onboarding-cleanup-owner")
            .join(uuid::Uuid::new_v4().to_string());
        let home = root.join("home");
        let templates = home.join("templates");
        std::fs::create_dir_all(&templates).unwrap();
        let settings = home.join("settings.json");
        std::fs::write(
            &settings,
            serde_json::to_vec(&json!({"tutorial":{"practice":{"version":1,"entries":[]}}}))
                .unwrap(),
        )
        .unwrap();
        let template_root = templates.clone();
        let jobs =
            Arc::new(JobRegistry::new(home.join("jobs"), move || template_root.clone()).unwrap());
        let pools = Arc::new(DatasetPoolRegistry::new(home.join("datasets")).unwrap());
        let controller = OnboardingController::new(
            home.join("tutorial_workspace"),
            root.join("unused-assets"),
            false,
            |_| {},
        );
        controller
            .bind_legacy_cleanup(
                LegacyPractice::new(templates, &home, settings, jobs, pools, |_| {}).unwrap(),
            )
            .unwrap();
        let preview = controller.dispatch("cleanup_preview", &json!({})).unwrap();
        assert_eq!(preview["rows"], json!([]));
        assert!(
            controller
                .dispatch("cleanup", &json!({"token":"stale"}))
                .is_err()
        );
        let result = controller
            .dispatch("cleanup", &json!({"token":preview["token"]}))
            .unwrap();
        assert_eq!(result, json!({"removed":0,"preserved":0}));
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stale_return_is_ignored_and_observer_failure_records_recovery() {
        let alerts = Arc::new(AtomicUsize::new(0));
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/onboarding-observer-owner")
            .join(uuid::Uuid::new_v4().to_string());
        std::fs::create_dir_all(&root).unwrap();
        let controller = OnboardingController::new(root.clone(), std::env::temp_dir(), false, {
            let alerts = alerts.clone();
            move |_| {
                alerts.fetch_add(1, Ordering::SeqCst);
            }
        });
        controller.returned(
            &json!(["replace_data", null, 4]),
            "editor",
            "save",
            &json!({}),
            &json!({"ok":true}),
        );
        assert_eq!(alerts.load(Ordering::SeqCst), 0);
        assert!(controller.state().unwrap().recovery.is_none());

        let token = {
            let mut state = controller.state().unwrap();
            state.progress.select("replace_data").unwrap();
            state.product_token()
        };
        let committed = json!({"ok":true,"path":"saved.xlsx"});
        controller.returned(&token, "editor", "save", &json!({}), &committed);
        assert_eq!(committed["path"], "saved.xlsx");
        assert_eq!(alerts.load(Ordering::SeqCst), 1);
        let state = controller.state().unwrap();
        assert!(!state.progress.active);
        assert_eq!(state.progress.checkpoint("replace_data"), 0);
        assert!(
            state
                .recovery
                .as_deref()
                .unwrap()
                .contains("tutorial graph unavailable")
        );
        drop(state);
        drop(controller);
        std::fs::remove_dir_all(root).unwrap();
    }
}
