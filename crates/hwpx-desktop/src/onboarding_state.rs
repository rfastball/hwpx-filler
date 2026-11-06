//! Persisted guidance actions; practice graph transitions are orchestrated separately.

use crate::job_registry::JobRegistry;
use crate::tutorial_lessons::{LessonProgress, is_ui_press_event};
use crate::tutorial_workspace::{
    MODIFIED_REASON, ORIGINALS, PracticeEntry, TutorialWorkspace, fingerprint,
};
use serde_json::{Value, json};
use std::error::Error;
use std::path::Path;
use uuid::Uuid;

pub type OnboardingError = Box<dyn Error + Send + Sync>;

pub struct OnboardingState {
    pub progress: LessonProgress,
    pub workspace: TutorialWorkspace,
    pub recovery: Option<String>,
    pub return_context: Option<Value>,
    pending: Option<PendingTransition>,
}

struct PendingTransition {
    token: String,
    action: String,
    scenario: Option<String>,
    basis: Value,
    context: Option<Value>,
}

impl OnboardingState {
    pub fn file_picker_hint(&self, kind: &str, screen: &str) -> String {
        if self.return_context.is_none() || !self.progress.active || !self.resources().0 {
            return String::new();
        }
        let Some(beat) = self.progress.beat() else {
            return String::new();
        };
        if !screen.is_empty() && beat.screen.as_deref() != Some(screen) {
            return String::new();
        }
        if kind == "data" && beat.event.as_deref() == Some("data_file_picked") {
            return self
                .progress
                .context()
                .and_then(|context| context.get("derived_data_path"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
        }
        String::new()
    }

    pub fn product_token(&self) -> Value {
        let selected = self.progress.selected.as_deref();
        let batch = selected
            .and_then(|_| self.progress.context())
            .and_then(|context| context.get("batch"));
        json!([
            selected,
            batch,
            selected.map_or(0, |id| self.progress.checkpoint(id))
        ])
    }

    pub fn accepts_product_token(&self, token: &Value) -> bool {
        self.progress.active && self.progress.beat().is_some() && self.product_token() == *token
    }

    pub fn new(workspace: TutorialWorkspace, first_launch: bool) -> Self {
        let raw = workspace.load_progress();
        let mut progress = LessonProgress::new(&raw, first_launch);
        progress.entry_visible = workspace.load_entry_visible();
        Self {
            progress,
            workspace,
            recovery: None,
            return_context: None,
            pending: None,
        }
    }

    /// `basis`, `loss`, and `return_context` must come from active backend controllers.
    pub fn preflight(
        &mut self,
        payload: &Value,
        basis: Value,
        loss: String,
        return_context: Option<Value>,
    ) -> Result<Value, OnboardingError> {
        self.pending = None;
        let screen = payload
            .get("screen")
            .and_then(Value::as_str)
            .ok_or("돌아갈 화면을 확인할 수 없습니다.")?;
        let action = payload
            .get("action")
            .and_then(Value::as_str)
            .ok_or("튜토리얼 전환을 다시 시도하세요.")?;
        if !matches!(
            screen,
            "job" | "library" | "editor" | "workbench" | "authoring"
        ) {
            return Err("돌아갈 화면을 확인할 수 없습니다.".into());
        }
        if !matches!(
            action,
            "start" | "select" | "restart" | "resume" | "exit" | "navigate"
        ) {
            return Err("튜토리얼 전환을 다시 시도하세요.".into());
        }
        let scenario = payload.get("scenario_id").and_then(Value::as_str);
        if payload
            .get("scenario_id")
            .is_some_and(|value| !value.is_null())
            && scenario.is_none_or(|id| crate::tutorial_lessons::lesson(id).is_none())
        {
            return Err("과정을 다시 고르세요.".into());
        }
        let destination = if action == "navigate" {
            match payload.get("destination_screen") {
                None => "job",
                Some(Value::String(value)) => value,
                Some(_) => return Err("돌아갈 화면을 확인할 수 없습니다.".into()),
            }
        } else {
            "job"
        };
        if !matches!(
            destination,
            "job" | "library" | "editor" | "workbench" | "authoring"
        ) {
            return Err("돌아갈 화면을 확인할 수 없습니다.".into());
        }
        let token = Uuid::new_v4().simple().to_string();
        if action != "navigate" {
            self.pending = Some(PendingTransition {
                token: token.clone(),
                action: action.into(),
                scenario: scenario.map(str::to_owned),
                basis,
                context: if self.return_context.is_none() {
                    return_context
                } else {
                    None
                },
            });
        }
        Ok(json!({"ok":true, "transition_token":token,
                  "needs_confirm":!loss.is_empty(), "target_screen":destination,
                  "confirm_text":loss}))
    }

    /// Verify that a confirmation is still tied to the current work/data generation.
    pub fn transition_context(
        &mut self,
        action: &str,
        payload: &Value,
        current_basis: &Value,
        current_loss: &str,
        captured_return: Option<Value>,
    ) -> Result<Option<Value>, OnboardingError> {
        let token = match payload.get("transition_token") {
            None | Some(Value::Null) => None,
            Some(Value::String(token)) => Some(token.as_str()),
            Some(_) => return Err("튜토리얼 전환을 다시 시도하세요.".into()),
        };
        let Some(token) = token else {
            if !current_loss.is_empty() {
                return Err(current_loss.to_owned().into());
            }
            return Ok(if self.return_context.is_none() {
                captured_return
            } else {
                None
            });
        };
        let pending = self
            .pending
            .as_ref()
            .ok_or("튜토리얼 전환을 다시 시도하세요.")?;
        if pending.token != token
            || pending.action != action
            || pending.scenario.as_deref() != payload.get("scenario_id").and_then(Value::as_str)
            || pending.basis != *current_basis
        {
            return Err("튜토리얼 전환을 다시 시도하세요.".into());
        }
        Ok(self.pending.take().and_then(|value| value.context))
    }

    pub fn persist(&self) -> Result<(), OnboardingError> {
        self.workspace.save_progress(&self.progress.progress())
    }

    /// An actual authoring save may change the practice TXT without invalidating its lesson.
    /// `session_source` is read from the backend's active authoring session.
    pub fn note_practice_save(
        &mut self,
        screen: &str,
        action: &str,
        result: &Value,
        session_source: Option<&Path>,
    ) -> Result<bool, OnboardingError> {
        if !matches!(
            self.progress.selected.as_deref(),
            Some("field_trial" | "option_apply" | "change_apply")
        ) || screen != "authoring"
            || !matches!(action, "save" | "save_authoring_document")
            || result.get("ok") != Some(&Value::Bool(true))
        {
            return Ok(false);
        }
        let Some(path) = result.get("path").and_then(Value::as_str) else {
            return Ok(false);
        };
        let expected = self
            .progress
            .context()
            .and_then(|context| context.get("assets"))
            .and_then(|assets| assets.get("낙찰자 선정 및 계약체결 안내.txt"))
            .and_then(|entry| entry.get("path"))
            .and_then(Value::as_str);
        if expected != Some(path) || session_source != Some(Path::new(path)) {
            return Ok(false);
        }
        let digest = fingerprint(Path::new(path))?;
        let context = self.progress.context_mut().ok_or("과정을 고르세요.")?;
        let saved = context
            .entry("saved_fingerprints")
            .or_insert_with(|| json!({}));
        if !saved.is_object() {
            *saved = json!({});
        }
        saved[path] = Value::String(digest);
        Ok(true)
    }

    pub fn dispatch_progress(
        &mut self,
        action: &str,
        payload: &Value,
    ) -> Result<bool, OnboardingError> {
        let changed = match action {
            "later" => {
                self.progress.later();
                true
            }
            "pause" | "skip" => {
                self.progress.pause();
                true
            }
            "next" => {
                self.progress.next_step()?;
                self.finish_blank_values();
                true
            }
            "observe_ui" => self.observe_ui(payload),
            "observe_ui_closed" => self.observe_ui_closed(payload),
            "reset_progress" => {
                if payload.get("confirm") != Some(&Value::Bool(true)) {
                    return Err("모든 학습 기록을 지울지 확인하세요.".into());
                }
                let entry_visible = self.progress.entry_visible;
                self.progress =
                    LessonProgress::new(&json!({"version": 1, "invite_seen": true}), false);
                self.progress.entry_visible = entry_visible;
                self.recovery = None;
                true
            }
            "set_entry_visible" => {
                let visible = payload
                    .get("visible")
                    .and_then(Value::as_bool)
                    .ok_or("튜토리얼 버튼 표시 값이 올바르지 않습니다.")?;
                self.workspace.save_entry_visible(visible)?;
                self.progress.entry_visible = visible;
                return Ok(true);
            }
            _ => {
                return Err(format!(
                    "알 수 없는 tutorial 액션: {}",
                    hwpx_filler::text_render::python_repr(&json!(action))
                )
                .into());
            }
        };
        self.persist()?;
        Ok(changed)
    }

    fn reported_event(&self, payload: &Value) -> Option<&str> {
        let id = self.progress.selected.as_deref()?;
        let beat = self.progress.beat()?;
        if !self.progress.active
            || payload.get("scenario_id").and_then(Value::as_str) != Some(id)
            || payload.get("checkpoint").and_then(Value::as_u64)
                != Some(self.progress.checkpoint(id) as u64)
            || payload.get("anchor") != Some(&json!(beat.target))
        {
            return None;
        }
        beat.event.as_deref()
    }

    fn observe_ui(&mut self, payload: &Value) -> bool {
        let Some(event) = self.reported_event(payload).map(str::to_owned) else {
            return false;
        };
        is_ui_press_event(&event) && self.progress.observed(&event, None)
    }

    fn observe_ui_closed(&mut self, payload: &Value) -> bool {
        if self.reported_event(payload).is_none() {
            return false;
        }
        let Some(beat) = self.progress.beat() else {
            return false;
        };
        if beat.target.as_deref() != Some("menu-item") {
            return false;
        }
        let Some(id) = self.progress.selected.as_deref() else {
            return false;
        };
        let index = self.progress.checkpoint(id);
        if index == 0 {
            return false;
        }
        let previous = crate::tutorial_lessons::lesson(id)
            .and_then(|lesson| lesson.beats.get(index - 1))
            .map(|beat| beat.id.clone());
        previous.is_some_and(|id| self.progress.rewind(&id))
    }

    fn finish_blank_values(&mut self) {
        if self.progress.selected.as_deref() != Some("blank_values") {
            return;
        }
        let Some(record) = self.progress.records.get("blank_values") else {
            return;
        };
        if record.get("completed") != Some(&Value::Bool(true)) {
            return;
        }
        self.progress.result = Some(json!({
            "screen": "workbench", "target": "txt-review",
            "title": "빈 값 확인 완료",
            "body": "〈빈 값〉 표식과 비움 확정을 확인했습니다.",
            "count": 1, "documents": [],
            "next_scenario_id": "field_trial"
        }));
    }

    pub fn observation_failed(&mut self, detail: &str) -> Result<(), OnboardingError> {
        self.progress.pause();
        self.recovery = Some(format!(
            "안내 진행을 확인하지 못했습니다: {detail}. 작업 결과는 보존됐습니다. 튜토리얼에서 다시 확인하세요."
        ));
        self.persist()
    }

    pub fn resources(&self) -> (bool, String) {
        let Some(lesson_id) = self.progress.selected.as_deref() else {
            return (false, "과정을 고르세요.".into());
        };
        let not_ready = || {
            (
                false,
                "연습 파일이 준비되지 않았습니다. 예제로 시작하세요.".into(),
            )
        };
        let Some(context) = self.progress.context() else {
            return not_ready();
        };
        let Some(home) = context.get("home").and_then(Value::as_str) else {
            return not_ready();
        };
        if !self.workspace.is_lesson_home(lesson_id, Path::new(home)) {
            return not_ready();
        }
        let Some(assets) = context.get("assets").and_then(Value::as_object) else {
            return not_ready();
        };
        if assets.len() != ORIGINALS.len()
            || ORIGINALS.iter().any(|name| !assets.contains_key(*name))
        {
            return not_ready();
        }
        let saved = context.get("saved_fingerprints").and_then(Value::as_object);
        for raw in assets.values() {
            let Ok(entry) = serde_json::from_value::<PracticeEntry>(raw.clone()) else {
                return (false, "연습 파일 상태를 확인할 수 없습니다.".into());
            };
            let (valid, reason) = self.workspace.validate(&entry, Path::new(home));
            if !valid {
                if reason == MODIFIED_REASON
                    && saved
                        .and_then(|v| v.get(&entry.path))
                        .and_then(Value::as_str)
                        .is_some_and(|digest| {
                            fingerprint(Path::new(&entry.path))
                                .is_ok_and(|current| current == digest)
                        })
                {
                    continue;
                }
                return (false, reason.into());
            }
        }
        if let Some(name) = context
            .get("job_name")
            .and_then(Value::as_str)
            .filter(|v| !v.is_empty())
        {
            let home_path = Path::new(home);
            let job_ready = JobRegistry::new(home_path.join("jobs"), {
                let templates = home_path.join("templates");
                move || templates.clone()
            })
            .and_then(|registry| registry.load(name).map_err(std::io::Error::other))
            .is_ok_and(|job| job.name == name);
            if !job_ready {
                return not_ready();
            }
        }
        match context.get("derived_entry") {
            None | Some(Value::Null) => (true, "연습 파일 4건이 준비됐습니다.".into()),
            Some(raw) if raw.is_object() => {
                let Ok(entry) = serde_json::from_value::<PracticeEntry>(raw.clone()) else {
                    return (false, "연습 파일 상태를 확인할 수 없습니다.".into());
                };
                let (valid, reason) = self.workspace.validate(&entry, Path::new(home));
                if valid {
                    (true, "연습 파일 4건이 준비됐습니다.".into())
                } else {
                    (false, reason.into())
                }
            }
            Some(_) => (false, "다른 연습 데이터 기록을 확인할 수 없습니다.".into()),
        }
    }

    pub fn snapshot(&mut self) -> Value {
        let (ready, summary) = self.resources();
        let mut snapshot = self.progress.snapshot();
        let context = self.progress.context();
        let mut files = Vec::new();
        if let Some(entries) = context
            .and_then(|ctx| ctx.get("assets"))
            .and_then(Value::as_object)
        {
            for (name, entry) in entries {
                files.push(json!({"name": name,
                    "path": entry.get("path").and_then(Value::as_str).unwrap_or(""),
                    "kind": if name.ends_with(".xlsx") { "data" } else { "template" }}));
            }
        }
        if let Some(derived) = context
            .and_then(|ctx| ctx.get("derived_entry"))
            .filter(|v| v.is_object())
        {
            files.push(json!({"name": "추가 연습 데이터",
                "path": derived.get("path").and_then(Value::as_str).unwrap_or(""), "kind": "data"}));
        }
        let notice = context
            .and_then(|ctx| ctx.get("seed_notice"))
            .and_then(Value::as_str)
            .unwrap_or("");
        snapshot["resources"] = json!({"ready": ready,
            "summary": format!("{summary} {notice}").trim(), "files": files});
        let reason = self.recovery.as_deref().or_else(|| {
            if ready || self.progress.selected.is_none() {
                None
            } else {
                Some(summary.as_str())
            }
        });
        snapshot["recovery"] = reason.map_or(
            Value::Null,
            |body| json!({"title":"연습 파일을 확인하세요","body":body}),
        );
        let active_practice = self.return_context.is_some();
        snapshot["practice"] = json!({"active":active_practice,
            "return_screen":self.return_context.as_ref().and_then(|value|value.get("screen"))});
        snapshot["entry"]["visible"] = Value::Bool(self.progress.entry_visible || active_practice);
        if let Some(beat) = snapshot.get_mut("beat").filter(|v| v.is_object())
            && let Some(arg) = beat
                .get("arg")
                .and_then(Value::as_str)
                .and_then(|v| v.strip_prefix("pool:"))
        {
            let replacement = context
                .and_then(|ctx| ctx.get("pool_keys"))
                .and_then(|v| v.get(arg))
                .cloned()
                .unwrap_or_else(|| json!(""));
            beat["arg"] = replacement;
        }
        snapshot
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::OnboardingState;
    use crate::tutorial_workspace::TutorialWorkspace;
    use serde_json::json;
    use std::path::Path;
    use uuid::Uuid;

    #[test]
    fn stale_ui_report_cannot_advance_and_entry_toggle_survives_reset() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/tutorial-state")
            .join(Uuid::new_v4().to_string());
        let workspace = TutorialWorkspace::new(
            root.clone(),
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/tutorial"),
            |_| {},
        );
        let mut state = OnboardingState::new(workspace, true);
        state.progress.select("first_hwpx").unwrap();
        state.dispatch_progress("next", &json!({})).unwrap();
        assert_eq!(state.progress.checkpoint("first_hwpx"), 1);
        state
            .dispatch_progress(
                "observe_ui",
                &json!({"scenario_id":"first_hwpx","checkpoint":0,"anchor":"new-job"}),
            )
            .unwrap();
        assert_eq!(state.progress.checkpoint("first_hwpx"), 1);
        state
            .dispatch_progress("set_entry_visible", &json!({"visible":false}))
            .unwrap();
        state
            .dispatch_progress("reset_progress", &json!({"confirm":true}))
            .unwrap();
        assert_eq!(state.snapshot()["entry"]["visible"], false);
        state.progress.select("first_hwpx").unwrap();
        let seeded = state.workspace.seed_originals("first_hwpx").unwrap();
        state
            .progress
            .context_mut()
            .unwrap()
            .extend(seeded.as_value().as_object().unwrap().clone());
        assert_eq!(state.snapshot()["resources"]["ready"], true);
        std::fs::write(&seeded.assets[0].path, b"tampered").unwrap();
        assert_eq!(state.snapshot()["resources"]["ready"], false);
        let payload = json!({"screen":"job","action":"select","scenario_id":"first_hwpx"});
        let guard = state
            .preflight(
                &payload,
                json!({"generation":1}),
                "확인".into(),
                Some(json!({"screen":"job"})),
            )
            .unwrap();
        assert_eq!(guard["needs_confirm"], true);
        let confirmation =
            json!({"scenario_id":"first_hwpx","transition_token":guard["transition_token"]});
        assert!(
            state
                .transition_context("select", &confirmation, &json!({"generation":2}), "", None)
                .is_err()
        );
        assert_eq!(
            state
                .transition_context("select", &confirmation, &json!({"generation":1}), "", None)
                .unwrap(),
            Some(json!({"screen":"job"}))
        );
        state.progress.select("field_trial").unwrap();
        let seeded = state.workspace.seed_originals("field_trial").unwrap();
        state
            .progress
            .context_mut()
            .unwrap()
            .extend(seeded.as_value().as_object().unwrap().clone());
        let txt = seeded
            .assets
            .iter()
            .find(|entry| entry.name == "낙찰자 선정 및 계약체결 안내.txt")
            .unwrap();
        std::fs::write(&txt.path, b"saved authoring edit").unwrap();
        assert_eq!(state.snapshot()["resources"]["ready"], false);
        assert!(
            !state
                .note_practice_save(
                    "authoring",
                    "save",
                    &json!({"ok":true,"path":txt.path}),
                    Some(Path::new("C:/wrong"))
                )
                .unwrap()
        );
        assert!(
            state
                .note_practice_save(
                    "authoring",
                    "save",
                    &json!({"ok":true,"path":txt.path}),
                    Some(Path::new(&txt.path))
                )
                .unwrap()
        );
        assert_eq!(state.snapshot()["resources"]["ready"], true);
        state.progress.select("replace_data").unwrap();
        let seeded = state.workspace.seed_originals("replace_data").unwrap();
        state
            .progress
            .context_mut()
            .unwrap()
            .extend(seeded.as_value().as_object().unwrap().clone());
        let suggested = seeded.home.join("공고목록(새 판).xlsx");
        state.progress.context_mut().unwrap().insert(
            "derived_data_path".into(),
            json!(suggested.to_string_lossy()),
        );
        state.return_context = Some(json!({"screen":"editor"}));
        let picker_step = crate::tutorial_lessons::lesson("replace_data")
            .unwrap()
            .beats
            .iter()
            .position(|beat| beat.event.as_deref() == Some("data_file_picked"))
            .unwrap();
        state.progress.records.get_mut("replace_data").unwrap()["checkpoint"] = json!(picker_step);
        assert_eq!(
            state.file_picker_hint("data", "editor"),
            suggested.to_string_lossy()
        );
        assert_eq!(state.file_picker_hint("data", "job"), "");
        assert_eq!(state.file_picker_hint("template", "editor"), "");
        state.return_context = None;
        assert_eq!(state.file_picker_hint("data", "editor"), "");
        let current_token = state.product_token();
        assert!(state.accepts_product_token(&current_token));
        assert!(!state.accepts_product_token(&json!(["replace_data", null, picker_step + 1])));
        state.observation_failed("disk read failed").unwrap();
        assert!(!state.accepts_product_token(&current_token));
        assert_eq!(state.progress.checkpoint("replace_data"), picker_step);
        assert!(
            state.snapshot()["recovery"]["body"]
                .as_str()
                .unwrap()
                .contains("disk read failed")
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
