//! Job-facing opaque template check/apply service over durable Work authority.

use crate::applied_template_asset::AppliedTemplateAsset;
use crate::atomic_file::write_bytes_atomic;
use crate::candidate_store::{FileCandidateObjectStore, ObjectFileErrorKind};
use crate::job_registry::JobRegistry;
use crate::qualification_store::FileQualificationObjectStore;
use crate::template_stage_runner::{
    ApplyInput, BOOTSTRAP_OK, BootstrapInput, CaptureInput, QualificationInput, StageError,
    TemplateStageRunner,
};
use crate::work_configuration_store::WorkspaceMetadataStore;
use crate::work_template_store::{
    AtomicWorkTemplateStateStore, WorkStoreError, WorkStoreErrorKind,
};
use hwpx_filler::candidate_revision::{MutableSourceBinding, TemplateLineage};
use hwpx_filler::job::Job;
use hwpx_filler::prepare_orchestration::{
    find_application, find_change, find_preparation, in_flight_preparations,
};
use hwpx_filler::prepare_template_change::{
    PrepareIntent, PreparePins, find_preparation_by_request, plan_prepare,
};
use hwpx_filler::template_change_product::{
    CAPABILITY_INITIALIZATION_REQUIRED, CAPABILITY_UNSUPPORTED_MEDIA, preparation_view,
    product_apply_status, template_change_zone_actionable,
};
use hwpx_filler::template_qualification::{
    qualification_profile_id, shipping_qualification_manifest,
};
use hwpx_filler::work_template_state::{
    PREP_CAPTURING, PREP_QUALIFYING, TemplateChangePreparation, WorkTemplateStateAggregate,
};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::UNIX_EPOCH;

pub const LOCAL_ACTOR: &str = "local-user";
#[derive(Debug)]
pub struct TemplateChangeError(pub String);
impl fmt::Display for TemplateChangeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TemplateChangeError {}
fn fail(text: impl Into<String>) -> TemplateChangeError {
    TemplateChangeError(text.into())
}
fn store_fail(text: impl Into<String>) -> WorkStoreError {
    WorkStoreError {
        kind: WorkStoreErrorKind::Conflict,
        detail: text.into(),
    }
}
fn new_token() -> String {
    uuid::Uuid::new_v4().simple().to_string()
}

#[derive(Default)]
struct SessionState {
    prep_tokens: HashMap<(String, String), String>,
    change_tokens: HashMap<(String, String), String>,
    token_change: HashMap<String, (String, String)>,
    recovered: HashSet<String>,
}
pub struct TemplateChangeCoordinator {
    root: PathBuf,
    jobs: Arc<JobRegistry>,
    works: AtomicWorkTemplateStateStore,
    candidates: Mutex<FileCandidateObjectStore>,
    qualifications: FileQualificationObjectStore,
    workspace: WorkspaceMetadataStore,
    applied: AppliedTemplateAsset,
    session_id: String,
    session: Mutex<SessionState>,
    failures: Mutex<()>,
    clock: Box<dyn Fn() -> String + Send + Sync>,
}
impl TemplateChangeCoordinator {
    pub fn authority_root(&self) -> &Path {
        &self.root
    }

    pub fn new(
        root: &Path,
        jobs: Arc<JobRegistry>,
        clock: impl Fn() -> String + Send + Sync + 'static,
    ) -> Result<Self, TemplateChangeError> {
        let applied = AppliedTemplateAsset::new(root, jobs.clone()).map_err(|e| fail(e.0))?;
        applied.migrate().map_err(|e| fail(e.0))?;
        Ok(Self {
            root: root.into(),
            works: AtomicWorkTemplateStateStore::new(root.join("works"))
                .map_err(|e| fail(e.detail))?,
            candidates: Mutex::new(FileCandidateObjectStore::new(root.join("candidates"))),
            qualifications: FileQualificationObjectStore::new(root.join("qualification")),
            workspace: WorkspaceMetadataStore::new(root).map_err(|e| fail(e.to_string()))?,
            applied,
            jobs,
            session_id: format!("s-{}", new_token()),
            session: Mutex::new(SessionState::default()),
            failures: Mutex::new(()),
            clock: Box::new(clock),
        })
    }
    fn now(&self) -> String {
        (self.clock)()
    }
    fn candidate_lock(
        &self,
    ) -> Result<std::sync::MutexGuard<'_, FileCandidateObjectStore>, TemplateChangeError> {
        self.candidates
            .lock()
            .map_err(|_| fail("Candidate store lock poisoned"))
    }
    fn job(&self, name: &str) -> Result<Job, TemplateChangeError> {
        self.jobs.load(name).map_err(|e| fail(e.to_string()))
    }
    fn manifest(&self) -> Result<(), TemplateChangeError> {
        for media in ["hwpx", "txt"] {
            let id = qualification_profile_id(media).expect("listed media");
            match self.qualifications.get_manifest(id) {
                Ok(_) => {}
                Err(error) if error.kind == ObjectFileErrorKind::NotFound => {
                    let value =
                        shipping_qualification_manifest(media, &self.now()).expect("listed media");
                    self.qualifications
                        .put_manifest(&value)
                        .map_err(|e| fail(e.detail))?;
                }
                Err(error) => return Err(fail(error.detail)),
            }
        }
        Ok(())
    }
    fn binding(&self, work_id: &str, job: &Job) -> MutableSourceBinding {
        MutableSourceBinding {
            source_binding_id: format!("{work_id}.binding"),
            media: job.media().into(),
            host_reference: job.template_path.clone(),
            display_metadata: Map::new(),
            generation: job.binding_revision,
        }
    }
    fn lineage(&self, work_id: &str, binding: &MutableSourceBinding) -> TemplateLineage {
        TemplateLineage {
            template_lineage_id: format!("{work_id}.lineage"),
            media: binding.media.clone(),
            mutable_source_binding_id: binding.source_binding_id.clone(),
            source_binding_generation: binding.generation,
            updated_at: self.now(),
        }
    }
    fn signature(path: &str) -> Option<Value> {
        let meta = fs::metadata(path).ok()?;
        let modified = meta
            .modified()
            .ok()?
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_nanos();
        Some(json!([modified, meta.len()]))
    }
    fn failures_path(&self) -> PathBuf {
        self.root.join("init_failures.json")
    }
    fn failures(&self) -> Result<Map<String, Value>, TemplateChangeError> {
        let _guard = self
            .failures
            .lock()
            .map_err(|_| fail("failure record lock poisoned"))?;
        self.read_failures()
    }
    fn read_failures(&self) -> Result<Map<String, Value>, TemplateChangeError> {
        let bytes = match fs::read(self.failures_path()) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Map::new()),
            Err(error) => return Err(fail(error.to_string())),
        };
        serde_json::from_slice::<Map<String, Value>>(&bytes).map_err(|e| fail(e.to_string()))
    }
    fn record_failure(&self, name: &str, entry: Option<Value>) -> Result<(), TemplateChangeError> {
        let _guard = self
            .failures
            .lock()
            .map_err(|_| fail("failure record lock poisoned"))?;
        let mut failures = self.read_failures()?;
        match entry {
            Some(value) => {
                failures.insert(name.into(), value);
            }
            None => {
                if failures.remove(name).is_none() {
                    return Ok(());
                }
            }
        }
        fs::create_dir_all(&self.root).map_err(|e| fail(e.to_string()))?;
        let bytes = serde_json::to_vec(&failures).map_err(|e| fail(e.to_string()))?;
        write_bytes_atomic(&self.failures_path(), &bytes).map_err(|e| fail(e.to_string()))
    }
    fn recover(&self, work_id: &str) -> Result<(), TemplateChangeError> {
        if !self.works.exists(work_id).map_err(|e| fail(e.detail))? {
            return Ok(());
        }
        let mut session = self
            .session
            .lock()
            .map_err(|_| fail("session lock poisoned"))?;
        if session.recovered.contains(work_id) {
            return Ok(());
        }
        let aggregate = self.works.load(work_id).map_err(|e| fail(e.detail))?;
        let old = in_flight_preparations(&aggregate, &self.session_id)
            .into_iter()
            .map(|item| item.preparation_id.clone())
            .collect::<Vec<_>>();
        let mut candidates = self.candidate_lock()?;
        let runner = TemplateStageRunner {
            works: &self.works,
            candidates: &mut candidates,
            qualifications: &self.qualifications,
        };
        for id in old {
            runner
                .recover(work_id, &id, &self.now())
                .map_err(|e| fail(e.0))?;
        }
        session.recovered.insert(work_id.into());
        Ok(())
    }
    fn token(&self, work_id: &str, id: &str, change: bool) -> Result<String, TemplateChangeError> {
        let mut state = self
            .session
            .lock()
            .map_err(|_| fail("session lock poisoned"))?;
        let key = (work_id.to_owned(), id.to_owned());
        if change {
            if let Some(value) = state.change_tokens.get(&key) {
                return Ok(value.clone());
            }
            let token = new_token();
            state.change_tokens.insert(key.clone(), token.clone());
            state.token_change.insert(token.clone(), key);
            Ok(token)
        } else {
            Ok(state
                .prep_tokens
                .entry(key)
                .or_insert_with(new_token)
                .clone())
        }
    }
    fn diagnostics(
        &self,
        prep: &TemplateChangePreparation,
    ) -> Result<Vec<(String, String)>, TemplateChangeError> {
        let mut result = prep
            .diagnostics
            .iter()
            .map(|entry| {
                (
                    entry
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .into(),
                    String::new(),
                )
            })
            .collect::<Vec<_>>();
        if let Some(id) = &prep.evidence_id {
            match self.qualifications.get_evidence(id) {
                Ok(evidence) => result.extend(evidence.diagnostics.iter().map(|entry| {
                    (
                        entry
                            .get("kind")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .into(),
                        entry
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .into(),
                    )
                })),
                Err(error) if error.kind == ObjectFileErrorKind::NotFound => {}
                Err(error) => return Err(fail(error.detail)),
            }
        }
        Ok(result)
    }
    fn view(
        &self,
        aggregate: &WorkTemplateStateAggregate,
        work_id: &str,
        prep: &TemplateChangePreparation,
    ) -> Result<Value, TemplateChangeError> {
        let (status, token) = match prep.prepared_change_id.as_deref() {
            Some(id) => {
                let change = find_change(aggregate, id).map_err(|e| fail(e.0))?;
                (
                    Some(change.status.as_str()),
                    Some(self.token(work_id, id, true)?),
                )
            }
            None => (None, None),
        };
        preparation_view(
            prep,
            status,
            &self.token(work_id, &prep.preparation_id, false)?,
            token.as_deref(),
            &self.diagnostics(prep)?,
        )
        .map_err(fail)
    }

    fn seat_bootstrap(
        &self,
        name: &str,
        request_id: &str,
    ) -> Result<Option<(String, Job)>, TemplateChangeError> {
        self.manifest()?;
        let before = self.job(name)?;
        let minted = format!("w-{}", new_token());
        let bound = if before.authority_id.is_empty() {
            self.jobs
                .assign_authority_id(name, &minted)
                .map_err(|e| fail(e.to_string()))?
                .authority_id
        } else {
            before.authority_id
        };
        if bound.is_empty() {
            return Err(fail("문서 작업 권위를 다시 확인할 수 없습니다"));
        }
        let issued_now = bound == minted;
        let job = self.job(name)?;
        if job.authority_id != bound {
            return Err(fail("문서 작업 권위를 다시 확인할 수 없습니다"));
        }
        self.recover(&bound)?;
        if !self.works.exists(&bound).map_err(|e| fail(e.detail))? {
            let binding = self.binding(&bound, &job);
            let lineage = self.lineage(&bound, &binding);
            let mut candidates = self.candidate_lock()?;
            let mut runner = TemplateStageRunner {
                works: &self.works,
                candidates: &mut candidates,
                qualifications: &self.qualifications,
            };
            let boot_id = format!("boot-{request_id}");
            let result = runner
                .bootstrap(
                    BootstrapInput {
                        work_id: &bound,
                        request_id: &boot_id,
                        lineage: &lineage,
                        binding: &binding,
                        profile_id: qualification_profile_id(job.media())
                            .ok_or_else(|| fail("지원하지 않는 템플릿 형식"))?,
                        application_id: &format!("{bound}.{boot_id}.app"),
                        engine_metadata: &Map::from_iter([(
                            "engine".into(),
                            Value::String("hwpxfiller".into()),
                        )]),
                        actor: LOCAL_ACTOR,
                        at: &self.now(),
                    },
                    |_| {
                        Ok(self
                            .job(name)
                            .map_err(|e| StageError(e.0))?
                            .binding_revision)
                    },
                )
                .map_err(|e| fail(e.0))?;
            if result.result != BOOTSTRAP_OK {
                if issued_now {
                    self.jobs
                        .release_authority_id(name, &bound)
                        .map_err(|e| fail(e.to_string()))?;
                }
                let mut diagnostics =
                    vec![json!({"kind":result.reason.unwrap_or_default(),"message":""})];
                let id = format!("{bound}.{boot_id}.ev");
                match self.qualifications.get_evidence(&id) {
                    Ok(evidence) => {
                        diagnostics.extend(evidence.diagnostics.into_iter().map(Value::Object))
                    }
                    Err(error) if error.kind == ObjectFileErrorKind::NotFound => {}
                    Err(error) => return Err(fail(error.detail)),
                }
                self.record_failure(
                    name,
                    Some(json!({"signature":Self::signature(&job.template_path),
                    "diagnostics":diagnostics})),
                )?;
                return Ok(None);
            }
        }
        self.record_failure(name, None)?;
        let adopted = self.applied.adopt(name, false).map_err(|e| fail(e.0))?;
        Ok(Some((bound, adopted)))
    }

    fn current_view(
        &self,
        aggregate: &WorkTemplateStateAggregate,
        work_id: &str,
    ) -> Result<Option<Value>, TemplateChangeError> {
        let Some(id) = aggregate.work.current_template_preparation_id.as_deref() else {
            return Ok(None);
        };
        let prep = find_preparation(aggregate, id).map_err(|e| fail(e.0))?;
        self.view(aggregate, work_id, prep).map(Some)
    }

    pub fn current_application_id(
        &self,
        work_id: Option<&str>,
    ) -> Result<Option<String>, TemplateChangeError> {
        let Some(id) = work_id else { return Ok(None) };
        if !self.works.exists(id).map_err(|e| fail(e.detail))? {
            return Ok(None);
        }
        self.recover(id)?;
        Ok(Some(
            self.works
                .load(id)
                .map_err(|e| fail(e.detail))?
                .work
                .current_template_application_id,
        ))
    }

    pub fn zone(
        &self,
        name: &str,
        media: &str,
        template_missing: bool,
    ) -> Result<Value, TemplateChangeError> {
        if !matches!(media, "hwpx" | "txt") || template_missing {
            return Ok(
                json!({"supported":false,"reason":CAPABILITY_UNSUPPORTED_MEDIA,
                "checkable":false,"actionable":false,"diagnostics":[],"epoch":null,"preparation":null}),
            );
        }
        let job = self.job(name)?;
        if let Some(failure) = self.failures()?.get(name).cloned() {
            if Self::signature(&job.template_path) == failure.get("signature").cloned() {
                return Ok(
                    json!({"supported":true,"reason":CAPABILITY_INITIALIZATION_REQUIRED,
                    "checkable":false,"actionable":true,"diagnostics":failure["diagnostics"],
                    "epoch":null,"preparation":null}),
                );
            }
            self.record_failure(name, None)?;
        }
        let mut epoch = None;
        let mut preparation = None;
        if !job.authority_id.is_empty()
            && self
                .works
                .exists(&job.authority_id)
                .map_err(|e| fail(e.detail))?
        {
            self.recover(&job.authority_id)?;
            let aggregate = self
                .works
                .load(&job.authority_id)
                .map_err(|e| fail(e.detail))?;
            epoch = Some(
                find_application(&aggregate, &aggregate.work.current_template_application_id)
                    .map_err(|e| fail(e.0))?
                    .application_epoch,
            );
            preparation = self.current_view(&aggregate, &job.authority_id)?;
        }
        let status = preparation
            .as_ref()
            .and_then(|item| item.get("status"))
            .and_then(Value::as_str);
        Ok(json!({"supported":true,"reason":"","checkable":true,
            "actionable":template_change_zone_actionable(true,"",status),
            "diagnostics":[],"epoch":epoch,"preparation":preparation}))
    }

    pub fn get_current_template_change_preparation(
        &self,
        name: &str,
    ) -> Result<Option<Value>, TemplateChangeError> {
        let job = self.job(name)?;
        if job.authority_id.is_empty()
            || !self
                .works
                .exists(&job.authority_id)
                .map_err(|e| fail(e.detail))?
        {
            return Ok(None);
        }
        self.recover(&job.authority_id)?;
        self.current_view(
            &self
                .works
                .load(&job.authority_id)
                .map_err(|e| fail(e.detail))?,
            &job.authority_id,
        )
    }

    /// Selecting a Job completes the same prepare/admission path as a manual
    /// check. This is a command entry, never part of snapshot rendering.
    pub fn ensure_bootstrapped(&self, name: &str) -> Result<Value, TemplateChangeError> {
        let job = self.job(name)?;
        if qualification_profile_id(job.media()).is_none() {
            return Ok(
                json!({"ok":true,"bootstrapped":false,"reason":CAPABILITY_UNSUPPORTED_MEDIA}),
            );
        }
        if !job.authority_id.is_empty()
            && self
                .works
                .exists(&job.authority_id)
                .map_err(|e| fail(e.detail))?
        {
            self.applied.adopt(name, false).map_err(|e| fail(e.0))?;
            return Ok(json!({"ok":true,"bootstrapped":false,"reason":""}));
        }
        let signature = Self::signature(&job.template_path);
        if job.template_path.is_empty() || signature.is_none() {
            return Ok(
                json!({"ok":true,"bootstrapped":false,"reason":CAPABILITY_UNSUPPORTED_MEDIA}),
            );
        }
        if self
            .failures()?
            .get(name)
            .is_some_and(|entry| entry.get("signature") == signature.as_ref())
        {
            return Ok(
                json!({"ok":false,"bootstrapped":false,"reason":CAPABILITY_INITIALIZATION_REQUIRED}),
            );
        }
        let result = self.check(name, &format!("auto-{}", new_token()))?;
        if result.get("ok") != Some(&Value::Bool(true)) {
            return Ok(json!({"ok":false,"bootstrapped":false,
                "reason":result.get("reason").and_then(Value::as_str).unwrap_or(CAPABILITY_INITIALIZATION_REQUIRED)}));
        }
        Ok(json!({"ok":true,"bootstrapped":true,"reason":""}))
    }

    pub fn check(&self, name: &str, request_id: &str) -> Result<Value, TemplateChangeError> {
        self.check_for_seated_context(name, request_id, LOCAL_ACTOR)
            .map(|item| item.0)
    }

    pub fn check_for_seated_context(
        &self,
        name: &str,
        request_id: &str,
        actor: &str,
    ) -> Result<(Value, Option<Job>, Option<String>), TemplateChangeError> {
        if request_id.is_empty()
            || request_id.len() > 64
            || !request_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        {
            return Err(fail(format!("잘못된 확인 요청 키 {:?}", request_id)));
        }
        let first = self.job(name)?;
        let Some(profile_id) = qualification_profile_id(first.media()) else {
            return Err(fail(format!(
                "지원하지 않는 템플릿 형식이라 변경사항 확인을(를) 지원하지 않습니다(형식={})",
                if first.media().is_empty() {
                    "미상"
                } else {
                    first.media()
                }
            )));
        };
        if actor != LOCAL_ACTOR {
            return Err(fail(format!(
                "actor {:?} 는 이 Work 에 접근할 수 없습니다",
                actor
            )));
        }
        let Some((work_id, job)) = self.seat_bootstrap(name, request_id)? else {
            return Ok((
                json!({"ok":false,"reason":CAPABILITY_INITIALIZATION_REQUIRED}),
                None,
                None,
            ));
        };
        let binding = self.binding(&work_id, &job);
        let prep_id = format!("p-{request_id}");
        let now = self.now();
        let aggregate = self
            .works
            .update(&work_id, |current| {
                if find_preparation_by_request(current, request_id).is_some() {
                    return Ok(current.clone());
                }
                let pins = PreparePins {
                    source_binding_id: binding.source_binding_id.clone(),
                    source_binding_generation: i64::try_from(binding.generation)
                        .map_err(|_| store_fail("binding_revision 범위 초과"))?,
                    qualification_profile_id: profile_id.into(),
                };
                plan_prepare(
                    current,
                    PrepareIntent {
                        prepare_request_id: request_id,
                        pins: &pins,
                        preparation_id: &prep_id,
                        execution_session_id: &self.session_id,
                        started_at: &now,
                    },
                )
                .map(|plan| plan.aggregate)
                .map_err(|e| store_fail(e.0))
            })
            .map_err(|e| fail(e.detail))?;
        let mut prep = find_preparation_by_request(&aggregate, request_id)
            .ok_or_else(|| fail("새 Preparation 이 durable aggregate 에 없습니다"))?
            .clone();
        let mut candidates = self.candidate_lock()?;
        let mut runner = TemplateStageRunner {
            works: &self.works,
            candidates: &mut candidates,
            qualifications: &self.qualifications,
        };
        if prep.status == PREP_CAPTURING {
            let initial = self.job(name)?;
            let pinned = MutableSourceBinding {
                source_binding_id: prep.source_binding_id.clone(),
                media: initial.media().into(),
                host_reference: initial.template_path,
                display_metadata: Map::new(),
                generation: u64::try_from(prep.source_binding_generation)
                    .map_err(|_| fail("Preparation generation 범위 오류"))?,
            };
            let lineage = self.lineage(&work_id, &pinned);
            prep = runner
                .capture(
                    CaptureInput {
                        work_id: &work_id,
                        preparation_id: &prep.preparation_id,
                        lineage: &lineage,
                        binding: &pinned,
                        captured_at: &self.now(),
                        created_at: &self.now(),
                    },
                    |_| {
                        Ok(self
                            .job(name)
                            .map_err(|e| StageError(e.0))?
                            .binding_revision)
                    },
                )
                .map_err(|e| fail(e.0))?;
        }
        if prep.status == PREP_QUALIFYING {
            prep = runner
                .qualify(QualificationInput {
                    work_id: &work_id,
                    preparation_id: &prep.preparation_id,
                    media: job.media(),
                    engine_metadata: &Map::from_iter([(
                        "engine".into(),
                        Value::String("hwpxfiller".into()),
                    )]),
                    started_at: &self.now(),
                    completed_at: &self.now(),
                    qualified_at: &self.now(),
                })
                .map_err(|e| fail(e.0))?;
        }
        let mut final_job = None;
        let aggregate = if prep.status == PREP_QUALIFYING && prep.attempt_id.is_some() {
            let observed = std::cell::RefCell::new(None);
            let admitted = runner
                .admit(
                    &work_id,
                    &prep.preparation_id,
                    |_| {
                        let fresh = self.job(name).map_err(|e| StageError(e.0))?;
                        let generation = i64::try_from(fresh.binding_revision)
                            .map_err(|_| StageError("binding_revision 범위 초과".into()))?;
                        *observed.borrow_mut() = Some(fresh);
                        Ok((format!("{work_id}.binding"), generation))
                    },
                    &format!("{}-chg", prep.preparation_id),
                    &self.now(),
                )
                .map_err(|e| fail(e.0))?;
            final_job = observed.into_inner();
            admitted.aggregate
        } else {
            self.works.load(&work_id).map_err(|e| fail(e.detail))?
        };
        prep = find_preparation(&aggregate, &prep.preparation_id)
            .map_err(|e| fail(e.0))?
            .clone();
        if final_job
            .as_ref()
            .is_some_and(|item: &Job| item.authority_id != work_id)
        {
            return Ok((
                json!({"ok":false,"reason":"work_context_changed"}),
                None,
                None,
            ));
        }
        let view = self.view(&aggregate, &work_id, &prep)?;
        let application_id = aggregate.work.current_template_application_id;
        Ok((
            json!({"ok":true,"preparation":view}),
            final_job,
            Some(application_id),
        ))
    }

    pub fn apply(&self, name: &str, token: &str) -> Result<Value, TemplateChangeError> {
        self.apply_for_seated_context(name, token, LOCAL_ACTOR)
            .map(|item| item.0)
    }
    pub fn apply_for_seated_context(
        &self,
        name: &str,
        token: &str,
        actor: &str,
    ) -> Result<(Value, String), TemplateChangeError> {
        let (token_work, change_id) =
            {
                let state = self
                    .session
                    .lock()
                    .map_err(|_| fail("session lock poisoned"))?;
                state.token_change.get(token).cloned().ok_or_else(|| {
                    fail("적용 대상이 유효하지 않습니다 — 변경사항을 다시 확인하세요")
                })?
            };
        let job = self.job(name)?;
        if job.authority_id != token_work {
            return Err(fail("이 변경사항은 현재 작업의 것이 아닙니다"));
        }
        self.manifest()?;
        let now = self.now();
        let workspace_id = self
            .workspace
            .get_or_create(&now)
            .map_err(|e| fail(e.to_string()))?;
        let mut candidates = self.candidate_lock()?;
        let runner = TemplateStageRunner {
            works: &self.works,
            candidates: &mut candidates,
            qualifications: &self.qualifications,
        };
        let (outcome, aggregate) = runner
            .apply(
                ApplyInput {
                    workspace_id: &workspace_id,
                    work_id: &token_work,
                    change_id: &change_id,
                    actor,
                    new_application_id: &format!("{change_id}-app"),
                    applied_at: &now,
                },
                |_, actor| {
                    if actor == LOCAL_ACTOR {
                        Ok(())
                    } else {
                        Err(StageError(format!(
                            "actor {:?} 는 이 Work 에 접근할 수 없습니다",
                            actor
                        )))
                    }
                },
            )
            .map_err(|e| fail(e.0))?;
        if outcome.result == "INTEGRITY_ERROR" {
            return Err(fail(
                "적용 무결성 확인에 실패했습니다 — 저장된 확인 결과를 신뢰할 수 없습니다",
            ));
        }
        let current = find_application(&aggregate, &aggregate.work.current_template_application_id)
            .map_err(|e| fail(e.0))?;
        if outcome.result == "APPLIED"
            && outcome.resulting_application_id.as_deref() == Some(&current.application_id)
        {
            self.applied.adopt(name, true).map_err(|e| fail(e.0))?;
        }
        let status = product_apply_status(&outcome.result).map_err(fail)?;
        let response = json!({"status":status,"current_template_application_epoch":current.application_epoch,
            "is_current":outcome.resulting_application_id.as_deref()==Some(aggregate.work.current_template_application_id.as_str())});
        Ok((response, current.application_id.clone()))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn assert_unsupported_media_fails_closed(
        templates: &Path,
        registry: &Arc<JobRegistry>,
        coordinator: &TemplateChangeCoordinator,
    ) {
        let unsupported = templates.join("unsupported.docx");
        fs::write(&unsupported, b"not a template").unwrap();
        let mut job = Job {
            name: "Unsupported".into(),
            template_path: unsupported.to_string_lossy().into(),
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let zone = coordinator.zone("Unsupported", "", false).unwrap();
        assert_eq!(zone["reason"], CAPABILITY_UNSUPPORTED_MEDIA);
        assert_eq!(zone["supported"], false);
        assert!(coordinator.check("Unsupported", "r1").is_err());
        assert!(
            registry
                .load("Unsupported")
                .unwrap()
                .authority_id
                .is_empty()
        );
        let mut missing = Job {
            name: "Missing".into(),
            template_path: templates.join("missing.txt").to_string_lossy().into(),
            ..Job::default()
        };
        registry.save(&mut missing, false).unwrap();
        let bootstrap = coordinator.ensure_bootstrapped("Missing").unwrap();
        assert_eq!(bootstrap["ok"], true);
        assert_eq!(bootstrap["bootstrapped"], false);
        assert!(registry.load("Missing").unwrap().authority_id.is_empty());
    }

    fn assert_owned_copy_migration_isolates_missing_link(
        root: &Path,
        registry: &Arc<JobRegistry>,
        first_source: &Path,
        second_source: &Path,
    ) {
        let first = registry.load("First").unwrap();
        let second = registry.load("Second").unwrap();
        let first_owned = PathBuf::from(&first.template_path);
        let second_owned = PathBuf::from(&second.template_path);
        let expected = fs::read(&second_owned).unwrap();
        registry
            .relink_template("Second", &second_source.to_string_lossy(), None)
            .unwrap();
        fs::remove_file(&first_owned).unwrap();
        fs::remove_file(&second_owned).unwrap();
        fs::remove_file(second_source).unwrap();
        let restarted =
            TemplateChangeCoordinator::new(root, registry.clone(), || "t11".into()).unwrap();
        assert_eq!(
            registry.load("First").unwrap().template_path,
            first_owned.to_string_lossy().as_ref()
        );
        assert!(!first_owned.exists());
        assert_eq!(fs::read(first_source).unwrap(), b"external original");
        assert_eq!(
            registry.load("Second").unwrap().template_path,
            second_owned.to_string_lossy().as_ref()
        );
        assert_eq!(fs::read(&second_owned).unwrap(), expected);
        assert!(restarted.ensure_bootstrapped("First").is_err());
    }

    #[test]
    fn check_and_apply_keep_tokens_scoped_to_the_durable_work() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/template-change-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let templates = root.join("templates");
        fs::create_dir_all(&templates).unwrap();
        let first = templates.join("first.txt");
        let second = templates.join("second.txt");
        let damaged = templates.join("damaged.txt");
        fs::write(&first, b"Hello {{name}}\n").unwrap();
        fs::write(&second, b"Other {{name}}\n").unwrap();
        fs::write(&damaged, [0xff, 0xfe]).unwrap();
        let registry = Arc::new(
            JobRegistry::new(root.join("jobs"), {
                let templates = templates.clone();
                move || templates.clone()
            })
            .unwrap(),
        );
        for (name, path) in [
            ("First", &first),
            ("Second", &second),
            ("Damaged", &damaged),
        ] {
            let mut job = Job {
                name: name.into(),
                template_path: path.to_string_lossy().into(),
                ..Job::default()
            };
            registry.save(&mut job, false).unwrap();
        }
        let coordinator = TemplateChangeCoordinator::new(&root, registry.clone(), || {
            "2026-11-05T09:00:00".into()
        })
        .unwrap();
        assert_unsupported_media_fails_closed(&templates, &registry, &coordinator);
        assert!(
            coordinator
                .check_for_seated_context("First", "denied", "other-user")
                .is_err()
        );
        assert!(registry.load("First").unwrap().authority_id.is_empty());
        assert!(!root.join("works").exists());
        let first_check = coordinator.check("First", "r1").unwrap();
        assert_eq!(first_check["ok"], true);
        assert_eq!(first_check["preparation"]["status"], "no_change");
        let linked = registry.load("First").unwrap();
        assert!(!linked.authority_id.is_empty());
        let owned = PathBuf::from(&linked.template_path);
        assert_ne!(owned, first);
        assert_eq!(owned.file_name(), first.file_name());
        assert_eq!(fs::read(&owned).unwrap(), fs::read(&first).unwrap());
        fs::write(&first, b"external original").unwrap();
        assert_eq!(
            coordinator.check("First", "source-only-change").unwrap()["preparation"]["status"],
            "no_change"
        );
        assert_eq!(fs::read(&owned).unwrap(), b"Hello {{name}}\n");
        let original = coordinator.works.load(&linked.authority_id).unwrap();
        assert!(
            coordinator
                .check_for_seated_context("First", "denied", "other-user")
                .is_err()
        );
        assert_eq!(
            coordinator.works.load(&linked.authority_id).unwrap(),
            original
        );
        fs::write(&linked.template_path, b"Changed {{name}}\n").unwrap();
        let second_check = coordinator.check("First", "r2").unwrap();
        assert_eq!(second_check["preparation"]["status"], "ready");
        let token = second_check["preparation"]["change_token"]
            .as_str()
            .unwrap();
        coordinator.check("Second", "r3").unwrap();
        assert!(
            coordinator
                .apply("Second", token)
                .unwrap_err()
                .0
                .contains("현재 작업")
        );
        let newer = coordinator.check("First", "r2-new").unwrap();
        assert_eq!(newer["preparation"]["status"], "ready");
        assert_eq!(
            coordinator.apply("First", token).unwrap()["status"],
            "superseded"
        );
        assert_eq!(coordinator.zone("First", "txt", false).unwrap()["epoch"], 1);
        let reissued = TemplateChangeCoordinator::new(&root, registry.clone(), || {
            "2026-11-05T09:00:30".into()
        })
        .unwrap();
        let ready = reissued.zone("First", "txt", false).unwrap();
        assert_eq!(ready["preparation"]["status"], "ready");
        let ready_token = ready["preparation"]["change_token"].as_str().unwrap();
        assert_eq!(
            reissued.apply("First", ready_token).unwrap()["status"],
            "applied"
        );
        assert_eq!(
            coordinator
                .apply(
                    "First",
                    newer["preparation"]["change_token"].as_str().unwrap()
                )
                .unwrap()["status"],
            "already_applied"
        );
        let restarted = TemplateChangeCoordinator::new(&root, registry.clone(), || {
            "2026-11-05T09:01:00".into()
        })
        .unwrap();
        assert_eq!(
            restarted.zone("First", "txt", false).unwrap()["preparation"]["status"],
            "applied"
        );
        assert!(restarted.apply("First", token).is_err());
        let before = coordinator.works.load(&linked.authority_id).unwrap();
        let barrier = std::sync::Barrier::new(2);
        let run = || {
            barrier.wait();
            coordinator.check("First", "concurrent").unwrap()
        };
        std::thread::scope(|scope| {
            let first = scope.spawn(run);
            let second = scope.spawn(run);
            assert_eq!(first.join().unwrap(), second.join().unwrap());
        });
        let after = coordinator.works.load(&linked.authority_id).unwrap();
        assert_eq!(after.work.prepare_seq, before.work.prepare_seq + 1);
        assert_eq!(after.preparations.len(), before.preparations.len() + 1);
        assert_eq!(after.applications, before.applications);
        registry
            .mutate("First", |job| job.binding_revision = u64::MAX)
            .unwrap();
        assert_eq!(
            coordinator.check("First", "concurrent").unwrap()["ok"],
            true
        );
        assert_eq!(coordinator.works.load(&linked.authority_id).unwrap(), after);
        registry
            .mutate("First", |job| {
                job.binding_revision = linked.binding_revision
            })
            .unwrap();
        assert_eq!(coordinator.check("Damaged", "r4").unwrap()["ok"], false);
        assert!(registry.load("Damaged").unwrap().authority_id.is_empty());
        assert_eq!(
            coordinator.zone("Damaged", "txt", false).unwrap()["reason"],
            CAPABILITY_INITIALIZATION_REQUIRED
        );
        assert_eq!(
            coordinator.ensure_bootstrapped("Damaged").unwrap()["ok"],
            false
        );
        let failed_restart =
            TemplateChangeCoordinator::new(&root, registry.clone(), || "t8".into()).unwrap();
        let failed_zone = failed_restart.zone("Damaged", "txt", false).unwrap();
        assert_eq!(failed_zone["checkable"], false);
        assert!(!failed_zone["diagnostics"].as_array().unwrap().is_empty());
        assert_eq!(
            failed_restart.ensure_bootstrapped("Damaged").unwrap()["bootstrapped"],
            false
        );
        assert!(registry.load("Damaged").unwrap().authority_id.is_empty());
        fs::write(&damaged, b"Repaired {{name}}\n").unwrap();
        assert_eq!(
            coordinator.ensure_bootstrapped("Damaged").unwrap()["ok"],
            true
        );
        assert!(!registry.load("Damaged").unwrap().authority_id.is_empty());
        let damaged_owned = registry.load("Damaged").unwrap().template_path;
        fs::write(&damaged_owned, [0xff, 0xfe]).unwrap();
        let encoding = coordinator.check("Damaged", "r5").unwrap();
        assert_eq!(encoding["preparation"]["status"], "invalid");
        assert!(encoding["preparation"]["change_token"].is_null());
        assert!(
            encoding["preparation"]["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|item| item["kind"] == "txt_encoding")
        );
        assert_eq!(
            coordinator.zone("Damaged", "txt", false).unwrap()["epoch"],
            1
        );
        fs::write(&damaged_owned, "{{#항목 s1 첨부}}\n내용 {{name}}\n").unwrap();
        let structure = coordinator.check("Damaged", "r6").unwrap();
        assert_eq!(structure["preparation"]["status"], "invalid");
        assert!(
            structure["preparation"]["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .any(|item| item["kind"] == "unbalanced_marker")
        );
        let same_session =
            TemplateChangeCoordinator::new(&root, registry.clone(), || "t9".into()).unwrap();
        let pending = same_session
            .works
            .update(&linked.authority_id, |current| {
                plan_prepare(
                    current,
                    PrepareIntent {
                        prepare_request_id: "pending-request",
                        preparation_id: "pending",
                        pins: &PreparePins {
                            source_binding_id: format!("{}.binding", linked.authority_id),
                            source_binding_generation: linked.binding_revision as i64,
                            qualification_profile_id: qualification_profile_id("txt")
                                .unwrap()
                                .into(),
                        },
                        execution_session_id: &same_session.session_id,
                        started_at: "t9",
                    },
                )
                .map(|plan| plan.aggregate)
                .map_err(|error| store_fail(error.0))
            })
            .unwrap();
        same_session.recover(&linked.authority_id).unwrap();
        assert_eq!(
            same_session.works.load(&linked.authority_id).unwrap(),
            pending
        );
        let next_session =
            TemplateChangeCoordinator::new(&root, registry.clone(), || "t10".into()).unwrap();
        next_session.recover(&linked.authority_id).unwrap();
        let recovered = next_session.works.load(&linked.authority_id).unwrap();
        assert_eq!(
            find_preparation(&recovered, "pending").unwrap().status,
            hwpx_filler::work_template_state::PREP_INTERRUPTED
        );
        assert_eq!(recovered.applications, pending.applications);
        assert_owned_copy_migration_isolates_missing_link(&root, &registry, &first, &second);
        fs::remove_dir_all(root).unwrap();
    }
}
