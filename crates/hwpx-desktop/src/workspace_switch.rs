//! User/practice graph lifetime and push gating. Product rules remain in each controller.

use crate::locations::Locations;
use crate::product_api::{ApiError, DeliveryOutcome};
use serde_json::{Value, json};
use std::error::Error;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

pub type GraphError = Box<dyn Error + Send + Sync>;
pub type PushResult = Result<Option<DeliveryOutcome>, ApiError>;
type PushSink = dyn Fn(&str, &Value) -> PushResult + Send + Sync;

/// Every controller explicitly declares whether it participates in the close guard.
pub trait ScreenController: Send + Sync {
    fn initial(&self) -> Result<Value, GraphError>;
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError>;
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError>;
    fn close_flush_required(&self) -> Result<bool, GraphError> {
        Ok(false)
    }
}

#[derive(Clone)]
pub struct PushGate {
    token: u64,
    active: Arc<AtomicU64>,
    publication: Arc<Mutex<()>>,
    sink: Arc<PushSink>,
}
impl PushGate {
    pub fn push(&self, screen: &str, snapshot: &Value) -> PushResult {
        let _publication = self.publication.lock().map_err(|_| ApiError {
            code: "adapter-internal".into(),
            detail: "화면 전달 잠금이 손상됐습니다.".into(),
            event: None,
        })?;
        if self.active.load(Ordering::SeqCst) != self.token {
            return Ok(None);
        }
        (self.sink)(screen, snapshot)
    }
}

pub struct WorkspaceGraph<R> {
    pub home: Option<PathBuf>,
    pub controllers: Vec<(String, Arc<dyn ScreenController>)>,
    pub resources: R,
    token: u64,
}
impl<R> WorkspaceGraph<R> {
    pub fn new(
        home: Option<PathBuf>,
        controllers: Vec<(String, Arc<dyn ScreenController>)>,
        resources: R,
        token: u64,
    ) -> Self {
        Self {
            home,
            controllers,
            resources,
            token,
        }
    }
    pub fn controller(&self, screen: &str) -> Option<&Arc<dyn ScreenController>> {
        self.controllers
            .iter()
            .find(|(name, _)| name == screen)
            .map(|(_, controller)| controller)
    }
}

type GraphBuilder<R> =
    dyn Fn(Option<&Path>, PushGate, u64) -> Result<WorkspaceGraph<R>, GraphError> + Send + Sync;

pub struct WorkspaceSwitch<R> {
    user: WorkspaceGraph<R>,
    practice: Option<WorkspaceGraph<R>>,
    active_is_practice: bool,
    active_token: Arc<AtomicU64>,
    publication: Arc<Mutex<()>>,
    next_token: u64,
    builder: Box<GraphBuilder<R>>,
    sink: Arc<PushSink>,
    locations: Locations,
}
impl<R> WorkspaceSwitch<R> {
    pub fn new(
        mut locations: Locations,
        sink: impl Fn(&str, &Value) -> PushResult + Send + Sync + 'static,
        builder: impl Fn(Option<&Path>, PushGate, u64) -> Result<WorkspaceGraph<R>, GraphError>
        + Send
        + Sync
        + 'static,
    ) -> Result<Self, GraphError> {
        locations.activate_workspace(None);
        let active_token = Arc::new(AtomicU64::new(1));
        let publication = Arc::new(Mutex::new(()));
        let sink: Arc<PushSink> = Arc::new(sink);
        let gate = PushGate {
            token: 1,
            active: active_token.clone(),
            publication: publication.clone(),
            sink: sink.clone(),
        };
        let user = builder(None, gate, 1)?;
        if user.home.is_some() || user.token != 1 {
            return Err("user graph identity mismatch".into());
        }
        Ok(Self {
            user,
            practice: None,
            active_is_practice: false,
            active_token,
            publication,
            next_token: 2,
            builder: Box::new(builder),
            sink,
            locations,
        })
    }
    pub fn active(&self) -> &WorkspaceGraph<R> {
        if self.active_is_practice {
            self.practice.as_ref().expect("active practice")
        } else {
            &self.user
        }
    }
    pub fn locations(&self) -> &Locations {
        &self.locations
    }
    pub fn practice_home(&self) -> Option<&Path> {
        self.active().home.as_deref()
    }
    pub fn cached_practice_home(&self) -> Option<&Path> {
        self.practice.as_ref()?.home.as_deref()
    }
    pub fn practice_close_reasons(&self) -> Result<Vec<String>, GraphError> {
        let mut reasons = Vec::new();
        if let Some(practice) = &self.practice {
            for (_, controller) in &practice.controllers {
                if let Some(reason) = controller.close_guard_reason()? {
                    reasons.push(reason)
                }
            }
        }
        Ok(reasons)
    }
    pub fn enter(&mut self, home: PathBuf) -> Result<(), GraphError> {
        if self
            .practice
            .as_ref()
            .is_some_and(|graph| graph.home.as_ref() == Some(&home))
        {
            return self.activate(true);
        }
        let previous = self.active().home.clone();
        let token = self.next_token;
        self.next_token = self
            .next_token
            .checked_add(1)
            .ok_or("workspace token exhausted")?;
        self.locations.activate_workspace(Some(home.clone()));
        let gate = PushGate {
            token,
            active: self.active_token.clone(),
            publication: self.publication.clone(),
            sink: self.sink.clone(),
        };
        let graph = match (self.builder)(Some(&home), gate, token) {
            Ok(graph) if graph.home.as_ref() == Some(&home) && graph.token == token => graph,
            Ok(_) => {
                self.locations.activate_workspace(previous);
                return Err("practice graph identity mismatch".into());
            }
            Err(error) => {
                self.locations.activate_workspace(previous);
                return Err(error);
            }
        };
        self.practice = Some(graph);
        self.activate(true)
    }
    pub fn leave(&mut self) -> Result<(), GraphError> {
        self.activate(false)
    }
    fn activate(&mut self, practice: bool) -> Result<(), GraphError> {
        self.active_is_practice = practice;
        let home = self.active().home.clone();
        let token = self.active().token;
        self.locations.activate_workspace(home);
        {
            let _publication = self
                .publication
                .lock()
                .map_err(|_| "화면 전달 잠금이 손상됐습니다.")?;
            self.active_token.store(token, Ordering::SeqCst);
        }
        self.refresh()
    }
    pub fn refresh(&self) -> Result<(), GraphError> {
        for (screen, controller) in &self.active().controllers {
            if screen != "tutorial" {
                let snapshot = controller.initial()?;
                (self.sink)(screen, &snapshot)?;
            }
        }
        Ok(())
    }
    pub fn close_guard_state(&self) -> Result<Value, GraphError> {
        let mut seen: Vec<&Arc<dyn ScreenController>> = Vec::new();
        let mut reasons = Vec::new();
        for graph in [
            Some(self.active()),
            Some(&self.user),
            self.practice.as_ref(),
        ]
        .into_iter()
        .flatten()
        {
            for (_, controller) in &graph.controllers {
                if seen.iter().any(|known| Arc::ptr_eq(known, controller)) {
                    continue;
                }
                seen.push(controller);
                if let Some(reason) = controller.close_guard_reason()? {
                    reasons.push(reason);
                }
            }
        }
        Ok(json!({"armed": !reasons.is_empty(), "reasons": reasons}))
    }
    pub fn close_flush_required(&self) -> Result<bool, GraphError> {
        for (_, controller) in &self.active().controllers {
            if controller.close_flush_required()? {
                return Ok(true);
            }
        }
        Ok(false)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{GraphError, PushGate, ScreenController, WorkspaceGraph, WorkspaceSwitch};
    use crate::locations::Locations;
    use serde_json::{Value, json};
    use std::path::{Path, PathBuf};
    use std::sync::{Arc, Mutex};

    struct Screen(String);
    impl ScreenController for Screen {
        fn initial(&self) -> Result<Value, GraphError> {
            Ok(json!({"screen": self.0}))
        }
        fn dispatch(&self, _action: &str, _payload: &Value) -> Result<Value, GraphError> {
            Ok(Value::Null)
        }
        fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
            Ok(Some(self.0.clone()))
        }
    }
    #[test]
    fn switch_keeps_user_state_gates_inactive_push_and_restores_after_failed_build() {
        let pushes = Arc::new(Mutex::new(Vec::new()));
        let observed = pushes.clone();
        let gates: Arc<Mutex<Vec<PushGate>>> = Arc::new(Mutex::new(Vec::new()));
        let captured = gates.clone();
        let user = Arc::new(Screen("user".into()));
        let same_user = user.clone();
        let mut workspaces = WorkspaceSwitch::new(
            Locations::new(Path::new("C:/User"), None),
            move |screen, snapshot| {
                observed
                    .lock()
                    .unwrap()
                    .push((screen.to_owned(), snapshot.clone()));
                Ok(None)
            },
            move |home, gate, token| {
                captured.lock().unwrap().push(gate);
                if home == Some(Path::new("C:/broken")) {
                    return Err("build failed".into());
                }
                let controller: Arc<dyn ScreenController> = match home {
                    Some(_) => Arc::new(Screen("practice".into())),
                    None => same_user.clone(),
                };
                Ok(WorkspaceGraph::new(
                    home.map(PathBuf::from),
                    vec![("job".into(), controller)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        assert!(workspaces.enter(PathBuf::from("C:/broken")).is_err());
        assert_eq!(
            workspaces.locations().workspace_home(),
            workspaces.locations().home()
        );
        workspaces.enter(PathBuf::from("C:/practice")).unwrap();
        assert_eq!(workspaces.practice_home(), Some(Path::new("C:/practice")));
        assert_eq!(
            workspaces.close_guard_state().unwrap()["reasons"],
            json!(["practice", "user"])
        );
        assert!(
            gates.lock().unwrap()[0]
                .push("job", &json!({}))
                .unwrap()
                .is_none()
        );
        workspaces.leave().unwrap();
        assert_eq!(workspaces.practice_home(), None);
        assert!(gates.lock().unwrap()[0].push("job", &json!({})).is_ok());
        assert_eq!(pushes.lock().unwrap().len(), 3);
    }

    #[test]
    fn held_old_push_finishes_before_practice_refresh() {
        use std::sync::mpsc;
        use std::time::Duration;

        let events = Arc::new(Mutex::new(Vec::new()));
        let observed = events.clone();
        let gates = Arc::new(Mutex::new(Vec::<PushGate>::new()));
        let captured = gates.clone();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let release_rx = Arc::new(Mutex::new(release_rx));
        let (practice_tx, practice_rx) = mpsc::channel();
        let (built_tx, built_rx) = mpsc::channel();
        let workspaces = WorkspaceSwitch::new(
            Locations::new(Path::new("C:/User"), None),
            move |_, snapshot| {
                if snapshot == &json!({"late":"old"}) {
                    entered_tx.send(()).unwrap();
                    release_rx.lock().unwrap().recv().unwrap();
                }
                observed.lock().unwrap().push(snapshot.clone());
                if snapshot == &json!({"screen":"practice"}) {
                    practice_tx.send(()).unwrap();
                }
                Ok(None)
            },
            move |home, gate, token| {
                captured.lock().unwrap().push(gate);
                if home.is_some() {
                    built_tx.send(()).unwrap();
                }
                let label = if home.is_some() { "practice" } else { "user" };
                Ok(WorkspaceGraph::new(
                    home.map(PathBuf::from),
                    vec![("job".into(), Arc::new(Screen(label.into())))],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let old_gate = gates.lock().unwrap()[0].clone();
        let old = std::thread::spawn(move || old_gate.push("job", &json!({"late":"old"})).unwrap());
        entered_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        let switched = std::thread::spawn(move || {
            let mut workspaces = workspaces;
            workspaces.enter(PathBuf::from("C:/practice")).unwrap();
        });
        built_rx.recv_timeout(Duration::from_secs(1)).unwrap();
        assert!(practice_rx.recv_timeout(Duration::from_millis(30)).is_err());
        release_tx.send(()).unwrap();
        old.join().unwrap();
        switched.join().unwrap();
        assert_eq!(
            events.lock().unwrap().as_slice(),
            &[json!({"late":"old"}), json!({"screen":"practice"}),]
        );
    }
}
