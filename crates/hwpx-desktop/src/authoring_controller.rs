//! Native document-authoring screen state and revision-checked dispatch.

use crate::action_registry::validate_dispatch;
use crate::authoring_session::AuthoringSession;
use crate::authoring_store::{AuthoringStore, AuthoringStoreError};
use crate::dataset_registry::DatasetPoolRegistry;
use crate::job_registry::JobRegistry;
use crate::locations::Locations;
use crate::template_change_coordinator::TemplateChangeCoordinator;
use crate::workspace_switch::{GraphError, PushGate, ScreenController};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_core::xml_view::XmlView;
use hwpx_filler::authoring_transfer::{
    CapturedMeaning, PasteOutcome, TransferSource, TransferTarget, capture_document, paste_document,
};
use hwpx_filler::field_proposal::{
    FieldProposalState, all_command, drafts, empty_view, group_command, pick_column, proposal_view,
    toast_many, toast_one,
};
use hwpx_filler::field_proposal_reading::{read_hwpx, read_txt, spot_location};
use hwpx_filler::hwpx_authoring_analysis::analyze_hwpx;
use hwpx_filler::hwpx_authoring_availability::{
    available_commands_hwpx, available_target_commands_hwpx,
};
use hwpx_filler::hwpx_authoring_commands::apply_hwpx;
use hwpx_filler::hwpx_authoring_search::{literal_ignorecase_ranges, same_text_hwpx, search_hwpx};
use hwpx_filler::hwpx_authoring_syntax::syntax_view_hwpx;
use hwpx_filler::hwpx_authoring_trial::trial_hwpx;
use hwpx_filler::python_casefold::python_casefold;
use hwpx_filler::rhwp_preflight::compare_rhwp_roundtrip;
use hwpx_filler::template_authoring::rename_field_message;
use hwpx_filler::text_authoring_trial::trial_txt_authoring;
use hwpx_filler::txt_authoring;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use uuid::Uuid;

#[path = "authoring_edit_dispatch.rs"]
mod edit_dispatch;
#[path = "authoring_helpers.rs"]
mod helpers;
use helpers::*;
#[path = "authoring_linked_proposal.rs"]
mod linked_proposal;
#[path = "authoring_location.rs"]
mod location;
#[path = "authoring_projection.rs"]
mod projection;
#[path = "authoring_proposal.rs"]
mod proposal_data;
#[path = "authoring_proposal_dispatch.rs"]
mod proposal_dispatch;
#[path = "authoring_search_dispatch.rs"]
mod search_dispatch;
#[path = "authoring_session_dispatch.rs"]
mod session_dispatch;
#[path = "authoring_session_io.rs"]
mod session_io;
#[path = "authoring_snapshot.rs"]
mod snapshot;
#[path = "authoring_trial_dispatch.rs"]
mod trial_dispatch;
use proposal_data::ProposalData;

#[derive(Default)]
struct AuthoringState {
    sessions: Vec<AuthoringSession>,
    active_id: String,
    restores: HashMap<String, Value>,
    clipboard: Option<(String, CapturedMeaning)>,
    pushed: Option<String>,
    queued: Option<String>,
    next_push_order: u64,
    projection_revisions: HashMap<(String, &'static str), (u64, u64)>,
    next_projection_revision: u64,
}
fn projection_revision(
    revisions: &mut HashMap<(String, &'static str), (u64, u64)>,
    next: &mut u64,
    session_id: &str,
    part: &'static str,
    stamp: u64,
) -> u64 {
    let key = (session_id.to_owned(), part);
    if let Some((seen_stamp, revision)) = revisions.get(&key)
        && *seen_stamp == stamp
    {
        return *revision;
    }
    *next += 1;
    let revision = *next;
    revisions.insert(key, (stamp, revision));
    revision
}
impl AuthoringState {
    fn session(
        &self,
        payload: &Map<String, Value>,
        revision: bool,
    ) -> Result<&AuthoringSession, GraphError> {
        let id = payload
            .get("session_id")
            .and_then(Value::as_str)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        let session = self
            .sessions
            .iter()
            .find(|item| item.id == id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        if revision && payload.get("revision").and_then(Value::as_u64) != Some(session.revision) {
            return Err(fail(
                "문서가 변경되었습니다. 최신 상태에서 다시 시도하세요.",
            ));
        }
        Ok(session)
    }
    fn session_mut(
        &mut self,
        payload: &Map<String, Value>,
        revision: bool,
    ) -> Result<&mut AuthoringSession, GraphError> {
        let id = payload
            .get("session_id")
            .and_then(Value::as_str)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        let session = self
            .sessions
            .iter_mut()
            .find(|item| item.id == id)
            .ok_or("열려 있지 않은 문서 세션입니다.")?;
        if revision && payload.get("revision").and_then(Value::as_u64) != Some(session.revision) {
            return Err(fail(
                "문서가 변경되었습니다. 최신 상태에서 다시 시도하세요.",
            ));
        }
        Ok(session)
    }
}

type MutationSink = dyn Fn(&str, &Path) -> Result<(), GraphError> + Send + Sync;
type PushOrder = Arc<(Mutex<u64>, Condvar)>;

#[derive(Clone)]
pub struct AuthoringController {
    store: AuthoringStore,
    jobs: Arc<JobRegistry>,
    push: PushGate,
    state: Arc<Mutex<AuthoringState>>,
    push_order: PushOrder,
    proposal_data: Option<ProposalData>,
    template_change: Option<Arc<TemplateChangeCoordinator>>,
    mutation_sink: Option<Arc<MutationSink>>,
}
impl AuthoringController {
    pub fn new(locations: &Locations, jobs: Arc<JobRegistry>, push: PushGate) -> Self {
        Self {
            store: AuthoringStore::new(locations.authoring()),
            jobs,
            push,
            state: Arc::new(Mutex::new(AuthoringState::default())),
            push_order: Arc::new((Mutex::new(1), Condvar::new())),
            proposal_data: None,
            template_change: None,
            mutation_sink: None,
        }
    }

    fn publish_snapshot(
        &self,
        mut state: MutexGuard<'_, AuthoringState>,
    ) -> Result<(), GraphError> {
        let snapshot = self.snapshot(&mut state)?;
        let fingerprint = digest(&serde_json::to_vec(&snapshot)?);
        let send = state.pushed.as_deref() != Some(&fingerprint)
            || state.queued.as_deref() != Some(&fingerprint);
        if !send {
            return Ok(());
        }
        state.next_push_order += 1;
        let order = state.next_push_order;
        state.queued = Some(fingerprint.clone());
        drop(state);

        let (next, wake) = &*self.push_order;
        let mut turn = next
            .lock()
            .map_err(|_| fail("저작 상태 전달 순서를 확인할 수 없습니다."))?;
        while *turn != order {
            turn = wake
                .wait(turn)
                .map_err(|_| fail("저작 상태 전달 순서를 확인할 수 없습니다."))?;
        }
        drop(turn);
        let delivered = self.push.push("authoring", &snapshot);
        let accepted = delivered
            .as_ref()
            .ok()
            .and_then(Option::as_ref)
            .is_some_and(|outcome| outcome.ok);
        let marked = (|| -> Result<(), GraphError> {
            let mut state = self.state()?;
            if accepted {
                state.pushed = Some(fingerprint.clone());
            } else if state.queued.as_deref() == Some(&fingerprint) {
                state.queued = state.pushed.clone();
            }
            Ok(())
        })();
        let mut turn = next
            .lock()
            .map_err(|_| fail("저작 상태 전달 순서를 확인할 수 없습니다."))?;
        *turn += 1;
        wake.notify_all();
        delivered?;
        marked
    }
    pub fn with_proposal_data(
        mut self,
        registry: Arc<DatasetPoolRegistry>,
        current: impl Fn() -> Result<Option<(String, Option<String>)>, String> + Send + Sync + 'static,
    ) -> Self {
        self.proposal_data = Some(ProposalData::new(registry, current));
        self
    }
    pub fn with_template_change(mut self, coordinator: Arc<TemplateChangeCoordinator>) -> Self {
        self.template_change = Some(coordinator);
        self
    }
    pub fn with_mutation_sink(
        mut self,
        sink: impl Fn(&str, &Path) -> Result<(), GraphError> + Send + Sync + 'static,
    ) -> Self {
        self.mutation_sink = Some(Arc::new(sink));
        self
    }
    pub fn active_facts(&self) -> Result<Option<Value>, GraphError> {
        let state = self.state()?;
        let Some(session) = state
            .sessions
            .iter()
            .find(|item| item.id == state.active_id)
        else {
            return Ok(None);
        };
        let problems = projection::problems(session)?;
        let content = if session.media == "txt" {
            Some(String::from_utf8(session.content.clone())?)
        } else {
            None
        };
        Ok(Some(json!({
            "active_id":session.id,"media":session.media,"source_path":session.source_path,
            "save_path":session.save_path,"content":content,"analysis":session.analysis,
            "revision":session.revision,"trial_coverage":projection::trial_coverage(session),
            "trial_revision_coverage":session.trial_coverage_evidence.iter()
                .filter(|(_, (revision, _))| *revision == session.revision)
                .map(|((slot_id, option_id), _)| json!({"slot_id":slot_id,"option_id":option_id}))
                .collect::<Vec<_>>(),
            "values":session.values,"readiness":projection::readiness(session,&problems)
        })))
    }
    fn do_new(
        &self,
        state: &mut AuthoringState,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let media = payload.get("media").and_then(Value::as_str).unwrap_or("");
        if !matches!(media, "txt" | "hwpx") {
            return Err(fail("HWPX 또는 TXT 형식만 만들 수 있습니다."));
        }
        let content = unwire(media, payload.get("content").unwrap_or(&json!("")))?;
        let analysis = analyze(media, &content)?;
        let session = AuthoringSession::new(
            Uuid::new_v4().simple().to_string(),
            media.into(),
            content,
            analysis,
        );
        let result = Self::contents(&session)?;
        state.active_id = session.id.clone();
        state.sessions.push(session);
        Ok(result)
    }

    fn dispatch_inner(
        &self,
        state: &mut AuthoringState,
        action: &str,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        match action {
            "new" => self.do_new(state, payload),
            "impact"
            | "prepare_apply"
            | "apply_job"
            | "propose_fields"
            | "propose_make"
            | "propose_make_all"
            | "propose_dismiss"
            | "propose_off"
            | "propose_pick_column" => self.dispatch_linked_proposal(state, action, payload),
            "activate" | "content" | "update" => self.dispatch_session(state, action, payload),
            "trial_input" | "case_upsert" | "case_remove" | "save_cases" | "trial_fill_names"
            | "trial" => self.dispatch_trial(state, action, payload),
            "commands" | "search" | "same_text" | "syntax" | "locate" => {
                self.dispatch_location(state, action, payload)
            }
            "rhwp_roundtrip_preflight"
            | "rhwp_unverified"
            | "check_external"
            | "remember_view"
            | "external_content"
            | "reload"
            | "close"
            | "save" => self.dispatch_session(state, action, payload),
            "preview" | "copy" | "preview_paste" => self.dispatch_edit(state, action, payload),
            _ => Err(fail(format!("알 수 없는 authoring 액션: {action:?}"))),
        }
    }
}

impl ScreenController for AuthoringController {
    fn initial(&self) -> Result<Value, GraphError> {
        let mut state = self.state()?;
        self.snapshot(&mut state)
    }
    fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, GraphError> {
        let validated = validate_dispatch("authoring", action, payload)?;
        let mut state = self.state()?;
        let result = self.dispatch_inner(&mut state, action, validated)?;
        self.publish_snapshot(state)?;
        Ok(result)
    }
    fn close_guard_reason(&self) -> Result<Option<String>, GraphError> {
        let state = self.state()?;
        let documents = state.sessions.iter().filter(|item| item.dirty()).count();
        let cases = state
            .sessions
            .iter()
            .filter(|item| item.cases_dirty || item.trial_inputs_dirty())
            .count();
        Ok((documents > 0 || cases > 0)
            .then(|| format!("저작 작업대: 미저장 문서 {documents}개 · 시험 자료 {cases}개")))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::workspace_switch::{WorkspaceGraph, WorkspaceSwitch};
    use hwpx_filler::dataset_reference::DatasetReference;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    fn assert_revert_preview_update(
        controller: &dyn ScreenController,
        authoring: &AuthoringController,
        original: &[u8],
        first: &Value,
        txt_id: &str,
    ) {
        let mut filled = HwpxPackage::from_bytes(original, PackageLimits::default()).unwrap();
        let field_name = first["analysis"]["fields"][0]["name"].as_str().unwrap();
        let entry = first["analysis"]["fields"][0]["occurrences"][0]["entry"]
            .as_str()
            .unwrap()
            .to_owned();
        assert!(
            hwpx_filler::fields::FieldDocument::new(&mut filled, &entry)
                .unwrap()
                .set_field(field_name, "채운 값")
                .unwrap()
        );
        let opened = controller
            .dispatch(
                "new",
                &json!({"media":"hwpx","content":STANDARD.encode(filled.to_bytes().unwrap())}),
            )
            .unwrap();
        let filled_id = opened["session_id"].as_str().unwrap();
        authoring
            .state()
            .unwrap()
            .sessions
            .iter_mut()
            .find(|session| session.id == filled_id)
            .unwrap()
            .rhwp_editable = Some(true);
        let filled_tab = || -> Value {
            controller.initial().unwrap()["tabs"]
                .as_array()
                .unwrap()
                .iter()
                .find(|tab| tab["id"] == filled_id)
                .unwrap()
                .clone()
        };
        assert_eq!(filled_tab()["document_commands"][0]["enabled"], true);
        let plan = controller
            .dispatch(
                "preview",
                &json!({"session_id":filled_id,"revision":0,
            "command":{"type":"revert_template"}}),
            )
            .unwrap();
        assert_eq!(plan["confirm"], "button");
        assert_eq!(plan["message"], "사라지는 것: 필드 값 1개");
        assert_eq!(plan["body_changed"], true);
        assert_eq!(filled_tab()["revision"], 0);
        assert_eq!(filled_tab()["document_commands"][0]["enabled"], true);
        controller
            .dispatch(
                "update",
                &json!({"session_id":filled_id,"revision":0,"content":plan["content"]}),
            )
            .unwrap();
        assert_eq!(filled_tab()["revision"], 1);
        assert_eq!(
            filled_tab()["document_commands"],
            json!([{"type":"revert_template",
            "enabled":false,"reason":"되돌릴 필드 값이 없습니다.","alternative":null}])
        );
        let mut reverted = HwpxPackage::from_bytes(
            &STANDARD.decode(plan["content"].as_str().unwrap()).unwrap(),
            PackageLimits::default(),
        )
        .unwrap();
        assert_eq!(
            hwpx_filler::fields::FieldDocument::new(&mut reverted, &entry)
                .unwrap()
                .read_field(field_name)
                .unwrap(),
            Some(format!("{{{{{field_name}}}}}"))
        );
        let txt_tab = controller.initial().unwrap()["tabs"]
            .as_array()
            .unwrap()
            .iter()
            .find(|tab| tab["id"] == txt_id)
            .unwrap()
            .clone();
        assert_eq!(
            txt_tab["document_commands"],
            json!([{"type":"revert_template",
            "enabled":false,"reason":"되돌릴 필드 값이 없습니다.","alternative":null}])
        );
        let refusal = controller
            .dispatch(
                "preview",
                &json!({"session_id":txt_id,"revision":0,
            "command":{"type":"revert_template"}}),
            )
            .unwrap_err();
        assert!(refusal.to_string().contains("되돌릴 필드 값이 없습니다."));
    }

    fn assert_txt_session_fences(
        controller: &dyn ScreenController,
        authoring: &AuthoringController,
        root: &Path,
    ) {
        let source = root.join("crlf-session.txt");
        let original = "제목 😀\r\n이름: {{이름}}\r\n".as_bytes();
        fs::write(&source, original).unwrap();
        let opened = authoring.open_path(&source, true).unwrap();
        let id = opened["session_id"].as_str().unwrap();
        let normalized = "제목 😀\n이름: {{이름}}\n";
        assert_eq!(opened["content"], normalized);
        assert_eq!(opened["analysis"]["source_text"], normalized);
        let preview = controller
            .dispatch(
                "preview",
                &json!({"session_id":id,"revision":0,
            "command":{"type":"create_field","start":0,"end":2,"name":"제목"}}),
            )
            .unwrap();
        assert_eq!(preview["content"], "{{제목}} 😀\n이름: {{이름}}\n");
        assert_eq!(
            controller
                .dispatch("content", &json!({"session_id":id}))
                .unwrap()["content"],
            normalized
        );
        let updated = controller
            .dispatch(
                "update",
                &json!({"session_id":id,"revision":0,
            "content":preview["content"].as_str().unwrap().replace('\n', "\r\n")}),
            )
            .unwrap();
        assert_eq!(updated["revision"], 1);
        let before = controller
            .dispatch("content", &json!({"session_id":id}))
            .unwrap();
        assert!(
            controller
                .dispatch(
                    "update",
                    &json!({"session_id":id,"revision":0,
            "content":"stale"})
                )
                .is_err()
        );
        assert!(
            controller
                .dispatch(
                    "update",
                    &json!({"session_id":id,"revision":true,
            "content":"stale"})
                )
                .is_err()
        );
        assert_eq!(
            controller
                .dispatch("content", &json!({"session_id":id}))
                .unwrap(),
            before
        );
        assert_eq!(fs::read(&source).unwrap(), original);
        assert_eq!(
            controller
                .dispatch("save", &json!({"session_id":id,"revision":1}))
                .unwrap()["ok"],
            true
        );
        assert_eq!(
            fs::read(&source).unwrap(),
            "{{제목}} 😀\r\n이름: {{이름}}\r\n".as_bytes()
        );
        controller
            .dispatch(
                "trial_input",
                &json!({"session_id":id,"revision":1,
            "values":{"이름":"홍길동"},"selected":{}}),
            )
            .unwrap();
        assert_eq!(
            controller
                .dispatch("save_cases", &json!({"session_id":id}))
                .unwrap()["needs_case_name"],
            true
        );
        controller
            .dispatch(
                "case_upsert",
                &json!({"session_id":id,"revision":1,
            "name":"검토","values":{"이름":"홍길동"},"selected":{}}),
            )
            .unwrap();
        let guard = controller
            .dispatch("close", &json!({"session_id":id}))
            .unwrap();
        assert_eq!(guard["document_dirty"], false);
        assert_eq!(guard["cases_dirty"], true);
        assert_eq!(guard["trial_inputs_dirty"], false);
        assert_eq!(
            controller
                .dispatch("save_cases", &json!({"session_id":id}))
                .unwrap()["ok"],
            true
        );
        assert_eq!(
            controller
                .dispatch("close", &json!({"session_id":id}))
                .unwrap()["ok"],
            true
        );
        let reopened = authoring.open_path(&source, true).unwrap();
        let tab = controller.initial().unwrap()["tabs"]
            .as_array()
            .unwrap()
            .iter()
            .find(|tab| tab["id"] == reopened["session_id"])
            .unwrap()
            .clone();
        assert_eq!(tab["cases"][0]["values"]["이름"], "홍길동");
        let reopened_id = reopened["session_id"].as_str().unwrap();
        let current_bytes = fs::read(&source).unwrap();
        assert_eq!(
            controller
                .dispatch(
                    "remember_view",
                    &json!({"session_id":reopened_id,
            "revision":0,"mode":"structure","selection":{"start":0,"end":2}})
                )
                .unwrap()["stored"],
            true
        );
        assert_eq!(fs::read(&source).unwrap(), current_bytes);
        controller
            .dispatch("close", &json!({"session_id":reopened_id}))
            .unwrap();
        let restored = authoring.open_path(&source, true).unwrap();
        let restore = controller
            .dispatch("activate", &json!({"session_id":restored["session_id"]}))
            .unwrap();
        assert_eq!(restore["restore"]["state"], "restored");
        assert_eq!(restore["restore"]["selection"], json!({"start":0,"end":2}));
        controller
            .dispatch("close", &json!({"session_id":restored["session_id"]}))
            .unwrap();
        fs::write(&source, b"external").unwrap();
        let stale = authoring.open_path(&source, true).unwrap();
        let restore = controller
            .dispatch("activate", &json!({"session_id":stale["session_id"]}))
            .unwrap();
        assert_eq!(restore["restore"]["state"], "stale");
        assert!(restore["restore"]["selection"].is_null());
        let copy_source = controller
            .dispatch("new", &json!({"media":"txt","content":"{{이름}}"}))
            .unwrap();
        let paste_target = controller
            .dispatch("new", &json!({"media":"txt","content":"안녕 "}))
            .unwrap();
        let source_id = copy_source["session_id"].as_str().unwrap();
        let target_id = paste_target["session_id"].as_str().unwrap();
        let captured = controller
            .dispatch(
                "copy",
                &json!({"session_id":source_id,"revision":0,
            "selector":{"kind":"field","start":1}}),
            )
            .unwrap();
        let paste = |token: &Value| {
            controller.dispatch(
                "preview_paste",
                &json!({
            "session_id":target_id,"revision":0,"clipboard_token":token,
            "destination":{"start":3,"end":3},"with_meaning":true}),
            )
        };
        assert_eq!(
            paste(&captured["clipboard_token"]).unwrap()["content"],
            "안녕 {{이름}}"
        );
        let target_before = controller
            .dispatch("content", &json!({"session_id":target_id}))
            .unwrap();
        assert_eq!(target_before["content"], "안녕 ");
        controller
            .dispatch(
                "copy",
                &json!({"session_id":target_id,"revision":0,
            "selector":{"kind":"text","start":0,"end":2}}),
            )
            .unwrap();
        assert!(
            paste(&captured["clipboard_token"])
                .unwrap_err()
                .to_string()
                .contains("복사한 내용이 변경되었습니다")
        );
        assert_eq!(
            controller
                .dispatch("content", &json!({"session_id":target_id}))
                .unwrap(),
            target_before
        );
    }

    #[test]
    fn closing_a_tab_cannot_be_followed_by_an_older_open_push() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/authoring-controller-tests")
            .join(format!("push-order-{}-{stamp}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let template_root = root.join("templates");
        let jobs =
            Arc::new(JobRegistry::new(root.join("jobs"), move || template_root.clone()).unwrap());
        let locations = Locations::new(&root, None);
        let captured = Arc::new(Mutex::new(None::<Arc<AuthoringController>>));
        let capture = captured.clone();
        let entered = Arc::new((Mutex::new((false, true)), Condvar::new()));
        let pause = entered.clone();
        let history = Arc::new(Mutex::new(Vec::<usize>::new()));
        let deliveries = history.clone();
        let graph = WorkspaceSwitch::new(
            locations.clone(),
            move |_, snapshot| {
                let count = snapshot["tabs"].as_array().unwrap().len();
                if count == 1 {
                    let (lock, wake) = &*pause;
                    let mut state = lock.lock().unwrap();
                    if !state.1 {
                        state.0 = true;
                        wake.notify_all();
                        while !state.1 {
                            state = wake.wait(state).unwrap();
                        }
                    }
                }
                deliveries.lock().unwrap().push(count);
                Ok(Some(crate::product_api::DeliveryOutcome {
                    event: "snapshot".into(),
                    ok: true,
                    code: "ok".into(),
                    detail: String::new(),
                    result: None,
                }))
            },
            move |_, gate, token| {
                let authoring = Arc::new(AuthoringController::new(&locations, jobs.clone(), gate));
                *capture.lock().unwrap() = Some(authoring.clone());
                Ok(WorkspaceGraph::new(
                    None,
                    vec![("authoring".into(), authoring as Arc<dyn ScreenController>)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = graph.active().controller("authoring").unwrap().clone();
        // A (empty) was already delivered. Hold B (one tab), then return to A.
        // Comparing only with the last delivered fingerprint would incorrectly skip A.
        let first = controller
            .dispatch("new", &json!({"media":"txt","content":"먼저"}))
            .unwrap();
        controller
            .dispatch(
                "close",
                &json!({"session_id":first["session_id"],"force":true}),
            )
            .unwrap();
        history.lock().unwrap().clear();
        entered.0.lock().unwrap().1 = false;
        let open = std::thread::spawn({
            let controller = controller.clone();
            move || {
                controller
                    .dispatch("new", &json!({"media":"txt","content":"순서검증"}))
                    .unwrap();
            }
        });
        let (lock, wake) = &*entered;
        let mut state = lock.lock().unwrap();
        while !state.0 {
            let result = wake.wait_timeout(state, Duration::from_secs(5)).unwrap();
            assert!(
                !result.1.timed_out(),
                "the first push never entered the sink"
            );
            state = result.0;
        }
        drop(state);
        let session_id = captured
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .state()
            .unwrap()
            .active_id
            .clone();
        let close = std::thread::spawn({
            let controller = controller.clone();
            move || {
                controller
                    .dispatch("close", &json!({"session_id":session_id,"force":true}))
                    .unwrap();
            }
        });
        let deadline = Instant::now() + Duration::from_secs(5);
        while !captured
            .lock()
            .unwrap()
            .as_ref()
            .unwrap()
            .state()
            .unwrap()
            .sessions
            .is_empty()
        {
            assert!(
                Instant::now() < deadline,
                "close did not mutate while first push was held"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        let mut state = lock.lock().unwrap();
        state.1 = true;
        wake.notify_all();
        drop(state);
        open.join().unwrap();
        close.join().unwrap();
        assert_eq!(*history.lock().unwrap(), vec![1, 0]);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn new_document_keeps_unsaved_close_guard_and_trial_refusal_state() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/authoring-controller-tests")
            .join(format!("{}-{stamp}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let template_root = root.join("templates");
        let jobs =
            Arc::new(JobRegistry::new(root.join("jobs"), move || template_root.clone()).unwrap());
        let locations = Locations::new(&root, None);
        let csv = root.join("proposal.csv");
        fs::write(&csv, "이름,마감일\n김다온,2026-09-15\n").unwrap();
        let pool = Arc::new(DatasetPoolRegistry::new(root.join("pool")).unwrap());
        let mut opts = Map::new();
        opts.insert("path".into(), json!(csv.to_str().unwrap()));
        let key = pool
            .add(&DatasetReference::new("자료", "excel", opts).unwrap())
            .unwrap();
        let builder_locations = locations.clone();
        let mutations = Arc::new(Mutex::new(Vec::new()));
        let observed = mutations.clone();
        let concrete = Arc::new(Mutex::new(None::<Arc<AuthoringController>>));
        let captured = concrete.clone();
        let graph = WorkspaceSwitch::new(
            locations,
            |_screen, _snapshot| Ok(None),
            move |_home, gate, token| {
                let sink = observed.clone();
                let authoring = Arc::new(
                    AuthoringController::new(&builder_locations, jobs.clone(), gate)
                        .with_proposal_data(pool.clone(), || Ok(None))
                        .with_mutation_sink(move |kind, path| {
                            sink.lock()
                                .unwrap()
                                .push((kind.to_owned(), path.to_path_buf()));
                            Ok(())
                        }),
                );
                *captured.lock().unwrap() = Some(authoring.clone());
                let controller: Arc<dyn ScreenController> = authoring;
                Ok(WorkspaceGraph::new(
                    None,
                    vec![("authoring".into(), controller)],
                    (),
                    token,
                ))
            },
        )
        .unwrap();
        let controller = graph.active().controller("authoring").unwrap();
        let created = controller
            .dispatch(
                "new",
                &json!({"media":"txt","content":
            "{{#항목 S}}\n{{#선택 A}}\n본문\n{{/선택}}\n{{/항목}}\n이름: 김다온\n마감일: 2026-09-15"}),
            )
            .unwrap();
        let session_id = created["session_id"].as_str().unwrap();
        let tab = &controller.initial().unwrap()["tabs"][0];
        assert_eq!(tab["dirty"], true);
        assert!(controller.close_guard_reason().unwrap().is_some());
        let refused = controller
            .dispatch("trial", &json!({"session_id":session_id,"revision":0}))
            .unwrap();
        assert_eq!(refused["ok"], false);
        assert!(
            refused["message"]
                .as_str()
                .unwrap()
                .contains("시험 선택을 지정하세요")
        );
        let tab = &controller.initial().unwrap()["tabs"][0];
        assert_eq!(tab["trial_state"], "failed");
        assert_eq!(tab["trial_error"], refused["message"]);
        let proposed = controller
            .dispatch(
                "propose_fields",
                &json!({"session_id":session_id,"revision":0,"pool_key":key}),
            )
            .unwrap();
        assert_eq!(proposed["state"], "ready");
        assert_eq!(proposed["counts"]["proposal"], 2);
        let group_id = proposed["groups"][0]["id"].as_str().unwrap();
        let made = controller
            .dispatch(
                "propose_make",
                &json!({"session_id":session_id,"revision":0,"group_id":group_id}),
            )
            .unwrap();
        assert_eq!(made["command"]["type"], "create_field");
        assert!(made["content"].is_string());
        let all = controller
            .dispatch(
                "propose_make_all",
                &json!({"session_id":session_id,"revision":0}),
            )
            .unwrap();
        assert_eq!(all["command"]["type"], "create_fields");
        assert_eq!(all["affected"], 2);
        assert!(all["content"].as_str().unwrap().contains("{{마감일}}"));
        let dismissed = controller
            .dispatch(
                "propose_dismiss",
                &json!({"session_id":session_id,"revision":0,"group_id":group_id}),
            )
            .unwrap();
        assert_eq!(dismissed["groups"].as_array().unwrap().len(), 1);
        assert_eq!(
            controller
                .dispatch("propose_off", &json!({"session_id":session_id}))
                .unwrap()["ok"],
            true
        );
        assert!(controller.initial().unwrap()["tabs"][0]["proposal"].is_null());
        let target = root.join("saved.txt");
        let authoring = concrete.lock().unwrap().clone().unwrap();
        assert_eq!(
            authoring.save_to_path(session_id, 0, &target).unwrap()["ok"],
            true
        );
        assert_eq!(
            controller
                .dispatch("save", &json!({"session_id":session_id,"revision":0}))
                .unwrap()["ok"],
            true
        );
        assert_eq!(mutations.lock().unwrap().len(), 2);
        let expected = crate::single_instance::normalize_windows_path(
            &crate::single_instance::resolved_home(&target),
        )
        .unwrap();
        assert!(
            mutations
                .lock()
                .unwrap()
                .iter()
                .all(|(kind, path)| kind == "mutated"
                    && crate::single_instance::normalize_windows_path(path).unwrap() == expected)
        );
        let input_cases = root.join("cases.json");
        fs::write(
            &input_cases,
            br#"{"version":1,"cases":[{"name":"case","values":{},"selected":{}}]}"#,
        )
        .unwrap();
        let imported = authoring
            .import_cases_path(session_id, &input_cases)
            .unwrap();
        assert_eq!(imported["cases"][0]["name"], "case");
        assert!(imported["cases"][0]["needs_review"].is_boolean());
        assert!(controller.close_guard_reason().unwrap().is_some());
        let exported = root.join("export.json");
        assert_eq!(
            authoring.export_cases_path(session_id, &exported).unwrap()["ok"],
            true
        );
        assert_eq!(AuthoringStore::import_cases(&exported).unwrap().len(), 1);
        let trial_output = root.join("trial.txt");
        assert!(
            authoring
                .export_result_path(session_id, 0, &trial_output)
                .is_err()
        );
        assert!(!trial_output.exists());

        let original = fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/template_v1.hwpx"),
        )
        .unwrap();
        let changed = fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../../tests/corpus/structural_range_s0/R0-plain.hwpx"),
        )
        .unwrap();
        let source = root.join("mutable.hwpx");
        fs::write(&source, &original).unwrap();
        let opened = authoring.open_path(&source, true).unwrap();
        let hwpx_id = opened["session_id"].as_str().unwrap();
        let hwpx_tab = || -> Value {
            controller.initial().unwrap()["tabs"]
                .as_array()
                .unwrap()
                .iter()
                .find(|tab| tab["id"] == hwpx_id)
                .unwrap()
                .clone()
        };
        let first = hwpx_tab();
        assert!(first["problems"].as_array().unwrap().is_empty());
        assert_eq!(hwpx_tab()["analysis"], first["analysis"]);
        controller
            .dispatch(
                "rhwp_unverified",
                &json!({"session_id":hwpx_id,"revision":0,"detail":"보존 실패"}),
            )
            .unwrap();
        assert!(
            hwpx_tab()["problems"]
                .as_array()
                .unwrap()
                .iter()
                .any(|item| item["category"] == "compatibility")
        );
        let admitted = controller
            .dispatch(
                "rhwp_roundtrip_preflight",
                &json!({"session_id":hwpx_id,"revision":0,"content":STANDARD.encode(&original)}),
            )
            .unwrap();
        assert_eq!(admitted["editable"], true);
        assert!(
            !hwpx_tab()["problems"]
                .as_array()
                .unwrap()
                .iter()
                .any(|item| item["category"] == "compatibility")
        );
        controller
            .dispatch(
                "update",
                &json!({"session_id":hwpx_id,"revision":0,"content":STANDARD.encode(&changed)}),
            )
            .unwrap();
        let edited = hwpx_tab();
        assert_ne!(edited["analysis"]["fields"], first["analysis"]["fields"]);
        fs::write(&source, &original).unwrap();
        controller
            .dispatch(
                "reload",
                &json!({"session_id":hwpx_id,"revision":1,"force":true}),
            )
            .unwrap();
        let reloaded = hwpx_tab();
        assert_eq!(reloaded["analysis"]["fields"], first["analysis"]["fields"]);
        assert!(reloaded["rhwp_editable"].is_null());

        assert_revert_preview_update(
            controller.as_ref(),
            authoring.as_ref(),
            &original,
            &first,
            session_id,
        );
        assert_txt_session_fences(controller.as_ref(), authoring.as_ref(), &root);
        fs::remove_dir_all(root).unwrap();
    }
}
