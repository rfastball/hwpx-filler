//! The one live route from host IPC to the active workspace's controllers.

use crate::action_registry::validate_dispatch;
use crate::workspace_switch::{GraphError, WorkspaceSwitch};
use serde_json::Value;
use std::path::Path;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};

/// Observes completed product commands using the lesson position captured before execution.
/// The observer owns its recovery path; it cannot turn a committed product result into failure.
pub trait ProductObserver: Send + Sync {
    fn token(&self) -> Value;
    fn returned(&self, token: &Value, screen: &str, action: &str, payload: &Value, result: &Value);
}

pub struct LiveGraph<R> {
    switch: Mutex<WorkspaceSwitch<R>>,
    observer: OnceLock<Arc<dyn ProductObserver>>,
}

impl<R> LiveGraph<R> {
    pub fn new(workspaces: WorkspaceSwitch<R>) -> Self {
        Self {
            switch: Mutex::new(workspaces),
            observer: OnceLock::new(),
        }
    }

    pub fn bind_observer(&self, observer: Arc<dyn ProductObserver>) -> Result<(), GraphError> {
        self.observer
            .set(observer)
            .map_err(|_| "tutorial observer already bound".into())
    }

    pub fn product_token(&self) -> Option<Value> {
        self.observer.get().map(|observer| observer.token())
    }

    pub fn returned_product(
        &self,
        token: Option<&Value>,
        screen: &str,
        action: &str,
        payload: &Value,
        result: &Value,
    ) {
        if let (Some(observer), Some(token)) = (self.observer.get(), token) {
            observer.returned(token, screen, action, payload, result);
        }
    }

    pub fn observe_direct<T>(
        &self,
        screen: &str,
        action: &str,
        payload: &Value,
        work: impl FnOnce() -> Result<T, GraphError>,
        projection: impl FnOnce(&T) -> Value,
    ) -> Result<T, GraphError> {
        let token = self.observer.get().map(|observer| observer.token());
        let result = work()?;
        if let (Some(observer), Some(token)) = (self.observer.get(), token.as_ref()) {
            observer.returned(token, screen, action, payload, &projection(&result));
        }
        Ok(result)
    }

    fn active(&self) -> Result<MutexGuard<'_, WorkspaceSwitch<R>>, GraphError> {
        Ok(self
            .switch
            .lock()
            .map_err(|_| "workspace graph lock poisoned")?)
    }

    pub fn initial(&self, screen: &str) -> Result<Value, GraphError> {
        let controller = self
            .active()?
            .active()
            .controller(screen)
            .ok_or_else(|| format!("등록되지 않은 화면: '{screen}'"))?
            .clone();
        controller.initial()
    }

    pub fn dispatch(
        &self,
        screen: &str,
        action: &str,
        payload: &Value,
    ) -> Result<Value, GraphError> {
        validate_dispatch(screen, action, payload)?;
        let controller = self
            .active()?
            .active()
            .controller(screen)
            .ok_or_else(|| format!("등록되지 않은 화면: '{screen}'"))?
            .clone();
        self.observe_direct(
            screen,
            action,
            payload,
            || controller.dispatch(action, payload),
            Value::clone,
        )
    }

    pub fn enter_practice(&self, home: PathBuf) -> Result<(), GraphError> {
        self.active()?.enter(home)
    }

    pub fn leave_practice(&self) -> Result<(), GraphError> {
        self.active()?.leave()
    }
    pub fn refresh(&self) -> Result<(), GraphError> {
        self.active()?.refresh()
    }
    pub fn practice_home(&self) -> Result<Option<PathBuf>, GraphError> {
        Ok(self.active()?.practice_home().map(Path::to_path_buf))
    }
    pub fn cached_practice_home(&self) -> Result<Option<PathBuf>, GraphError> {
        Ok(self.active()?.cached_practice_home().map(Path::to_path_buf))
    }
    pub fn practice_close_reasons(&self) -> Result<Vec<String>, GraphError> {
        self.active()?.practice_close_reasons()
    }

    pub fn close_guard_state(&self) -> Result<Value, GraphError> {
        self.active()?.close_guard_state()
    }

    pub fn close_flush_required(&self) -> Result<bool, GraphError> {
        self.active()?.close_flush_required()
    }

    pub fn active_resources(&self) -> Result<R, GraphError>
    where
        R: Clone,
    {
        Ok(self.active()?.active().resources.clone())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::LiveGraph;
    use crate::locations::Locations;
    use crate::workspace_switch::{GraphError, ScreenController, WorkspaceGraph, WorkspaceSwitch};
    use serde_json::{Value, json};
    use std::path::Path;
    use std::sync::Arc;

    struct Screen(&'static str);
    impl ScreenController for Screen {
        fn initial(&self) -> Result<Value, GraphError> {
            Ok(json!({"home":self.0}))
        }
        fn dispatch(&self, _: &str, _: &Value) -> Result<Value, GraphError> {
            Ok(json!({"home":self.0}))
        }
        fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
            Ok(None)
        }
    }

    #[test]
    fn dispatch_validates_before_routing_and_switches_only_to_active_workspace() {
        let switch = WorkspaceSwitch::new(
            Locations::new(Path::new("C:/User"), None),
            |_, _| Ok(None),
            |home, _, token| {
                let label = if home.is_some() { "practice" } else { "user" };
                Ok(WorkspaceGraph::new(
                    home.map(Path::to_path_buf),
                    vec![("job".into(), Arc::new(Screen(label)))],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let graph = LiveGraph::new(switch);
        assert_eq!(
            graph.dispatch("job", "artifact_close", &json!({})).unwrap(),
            json!({"home":"user"})
        );
        assert!(graph.dispatch("job", "unknown", &json!({})).is_err());
        graph.enter_practice("C:/practice".into()).unwrap();
        assert_eq!(graph.initial("job").unwrap(), json!({"home":"practice"}));
        graph.leave_practice().unwrap();
        assert_eq!(graph.initial("job").unwrap(), json!({"home":"user"}));
    }
}
