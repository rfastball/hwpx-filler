//! Tutorial entry, resume, restart, and exit around the practice workspace switch.

use super::*;

impl OnboardingController {
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
        let keeps_home = self.keeps_practice_home(&graph, action, scenario)?;
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

    /// Whether the transition resumes the lesson whose record already owns the cached home.
    fn keeps_practice_home(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        action: &str,
        scenario: Option<&str>,
    ) -> Result<bool, GraphError> {
        if action == "restart" {
            return Ok(false);
        }
        let Some(home) = graph.cached_practice_home()? else {
            return Ok(false);
        };
        let state = self.state()?;
        let lesson_id = if action == "resume" {
            state.progress.selected.as_deref()
        } else {
            scenario
        };
        Ok(lesson_id.is_some_and(|id| {
            let checkpoint = state.progress.checkpoint(id);
            let resumable = action == "resume"
                || crate::tutorial_lessons::lesson(id)
                    .is_some_and(|lesson| checkpoint > 0 && checkpoint < lesson.beats.len());
            resumable
                && state
                    .progress
                    .records
                    .get(id)
                    .and_then(|entry| entry.pointer("/context/home"))
                    .and_then(Value::as_str)
                    == home.to_str()
        }))
    }

    pub(super) fn transition(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
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
            Self::enter_resume(graph, state, &id)?;
        } else if action != "restart" && self.resumable_home(state, &id).is_some() {
            self.enter_resumable(graph, state, &id)?;
        } else {
            self.enter_fresh(graph, state, action, &id)?;
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

    /// Resume re-enters the selected lesson's recorded home once its resources are ready.
    fn enter_resume(
        graph: &LiveGraph<RuntimeResources>,
        state: &mut OnboardingState,
        id: &str,
    ) -> Result<(), GraphError> {
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
        state.progress.select(id)?;
        Ok(())
    }

    /// A lesson stopped midway re-enters its own still-present home.
    fn enter_resumable(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        state: &mut OnboardingState,
        id: &str,
    ) -> Result<(), GraphError> {
        state.progress.select(id)?;
        let home = self
            .resumable_home(state, id)
            .ok_or("연습 파일을 먼저 준비하세요.")?;
        graph.enter_practice(home)?;
        Ok(())
    }

    /// Start or restart seeds a fresh practice home, switches into it, and sweeps old homes.
    fn enter_fresh(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        state: &mut OnboardingState,
        action: &str,
        id: &str,
    ) -> Result<(), GraphError> {
        if action != "restart" {
            state.progress.select(id)?;
        }
        state.progress.restart(id)?;
        let (derived, name, _sheet) = derived_for(id);
        let mut seeded = state.workspace.seed(id, derived, name)?;
        let seeded_context = seed_before_switch(id, &mut seeded)?;
        state
            .progress
            .context_mut()
            .ok_or("과정을 고르세요.")?
            .extend(seeded_context);
        graph.enter_practice(seeded.home.clone())?;
        if let Err(error) = self.after_switch(graph, id, state) {
            let _ = graph.leave_practice();
            return Err(error);
        }
        state.workspace.sweep(id, &seeded.home);
        Ok(())
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
        restore_original_screen(graph, original)
            .unwrap_or_else(|_| ("library".into(), "돌아갈 화면을 확인할 수 없습니다.".into()))
    }

    fn rewind_on_entry(
        &self,
        graph: &LiveGraph<RuntimeResources>,
        state: &mut OnboardingState,
    ) -> Result<(), GraphError> {
        let Some(beat) = state.progress.beat() else {
            return Ok(());
        };
        if beat.screen.as_deref() == Some("authoring") && !authoring_entry_valid(graph, state)? {
            let first = authoring_restart_beat(state);
            state.progress.rewind(first);
            return Ok(());
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

/// On entry, an authoring beat needs the lesson's TXT open as both source and save target.
fn authoring_entry_valid(
    graph: &LiveGraph<RuntimeResources>,
    state: &OnboardingState,
) -> Result<bool, GraphError> {
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
    Ok(opened
        .as_ref()
        .zip(path.as_ref())
        .is_some_and(|(opened, path)| {
            opened["media"] == "txt"
                && opened["source_path"] == *path
                && opened["save_path"] == *path
        }))
}

/// Restores the screen captured before practice; an unreadable capture is an error.
fn restore_original_screen(
    graph: &LiveGraph<RuntimeResources>,
    original: &Value,
) -> Result<(String, String), GraphError> {
    let resources = graph.active_resources()?;
    let screen = original["screen"]
        .as_str()
        .ok_or("돌아갈 화면을 확인할 수 없습니다.")?
        .to_owned();
    match screen.as_str() {
        "editor" => Ok((restore_editor(&resources, original)?, String::new())),
        "authoring" => {
            if let Some(id) = original["authoring_id"]
                .as_str()
                .filter(|id| !id.is_empty())
            {
                resources
                    .authoring
                    .dispatch("activate", &json!({"session_id":id}))?;
            }
            Ok((screen, String::new()))
        }
        "workbench" => restore_workbench(&resources, original),
        _ => Ok((screen, String::new())),
    }
}

/// Reopens the captured editor work, or falls back to the job screen or the library.
fn restore_editor(resources: &RuntimeResources, original: &Value) -> Result<String, GraphError> {
    if let Some(name) = original["editor_job"]
        .as_str()
        .filter(|name| !name.is_empty())
    {
        resources.editor.load_job(name)?;
        return Ok("editor".into());
    }
    Ok(if resources.job.selected_job_name()?.is_empty() {
        "library"
    } else {
        "job"
    }
    .into())
}

/// Reopens the workbench on the captured source row when it still exists.
fn restore_workbench(
    resources: &RuntimeResources,
    original: &Value,
) -> Result<(String, String), GraphError> {
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
    Ok(("workbench".into(), String::new()))
}
