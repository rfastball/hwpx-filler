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

#[path = "onboarding_observation.rs"]
mod observation;
#[path = "onboarding_transition.rs"]
mod transition;

/// The first beat an authoring lesson restarts from when its practice template is not open.
fn authoring_restart_beat(state: &OnboardingState) -> &'static str {
    if state.progress.selected.as_deref() == Some("change_apply") {
        "pick_job"
    } else {
        "open_list"
    }
}

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
