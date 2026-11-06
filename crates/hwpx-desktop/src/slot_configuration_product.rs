//! Route-bound current slot view assembled from one fenced authority snapshot.

use crate::candidate_store::FileCandidateObjectStore;
use crate::job_registry::JobRegistry;
use crate::per_work_fence::PerWorkFence;
use crate::preset_registry::{PresetRegistry, PresetStoreError};
use crate::qualification_store::FileQualificationObjectStore;
use crate::slot_configuration_runner::{CommandOutcome, run_apply_preset, run_command, run_ensure};
use crate::slot_token::{Claims, actor_binding_digest, load_or_create_secret, open, sign};
use crate::work_configuration_store::{WorkSlotConfigurationStore, WorkspaceMetadataStore};
use crate::work_template_store::{AtomicWorkTemplateStateStore, WorkStoreErrorKind};
use hwpx_filler::job::Job;
use hwpx_filler::preset::SelectionPreset;
use hwpx_filler::preset_fit::fit_preset;
use hwpx_filler::preset_fit::plan_preset_save;
use hwpx_filler::slot_command::{ConfigurationCommandContext, SELECT};
use hwpx_filler::slot_configuration_context::{
    ContextErrorKind, ContextPorts, SlotConfigurationContext, resolve_slot_configuration_context,
};
use hwpx_filler::slot_configuration_projection::{
    CONTEXT_ERROR, project_context_error, project_current_slot_configuration,
};
use hwpx_filler::slot_reconciliation::{
    ReconciliationApplication, SlotConfigurationResolution, find_nearest_predecessor_configuration,
    resolve_slot_configuration,
};
use hwpx_filler::slot_selection::{SlotSelectionSet, semantic_selection_equal};
use hwpx_filler::work_slot_configuration::WorkSlotConfigurationDraft;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Arc;

const LOAD_MESSAGE: &str = "포함할 내용을 불러오지 못했습니다. 다시 불러오세요.";
const CONTEXT_FALLBACK: &str =
    "포함할 내용을 불러오지 못했습니다. 문서 작업을 다시 열고 템플릿을 확인하세요.";
type PresetRows = (Vec<Value>, Vec<Value>, Option<String>);

#[derive(Debug)]
pub struct SlotProductError {
    pub code: Option<&'static str>,
    pub detail: String,
}
impl SlotProductError {
    fn coded(code: &'static str, detail: impl Into<String>) -> Self {
        Self {
            code: Some(code),
            detail: detail.into(),
        }
    }
}
impl From<String> for SlotProductError {
    fn from(detail: String) -> Self {
        Self { code: None, detail }
    }
}
impl From<&str> for SlotProductError {
    fn from(detail: &str) -> Self {
        Self::from(detail.to_owned())
    }
}
impl fmt::Display for SlotProductError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for SlotProductError {}

pub struct SlotRead {
    pub zone: Value,
    pub resolution: Option<SlotConfigurationResolution>,
}
struct CurrentRead {
    view: Value,
    resolution: Option<SlotConfigurationResolution>,
    context_error: bool,
    application_id: Option<String>,
}

pub struct SlotConfigurationProduct {
    root: PathBuf,
    jobs: Arc<JobRegistry>,
    clock: Box<dyn Fn() -> String + Send + Sync>,
}

impl SlotConfigurationProduct {
    pub fn new(
        root: &Path,
        jobs: Arc<JobRegistry>,
        clock: impl Fn() -> String + Send + Sync + 'static,
    ) -> Self {
        Self {
            root: root.into(),
            jobs,
            clock: Box::new(clock),
        }
    }

    pub fn blank_zone() -> Value {
        json!({"supported":false,"initialized":false,"mutation_outcome":null,
            "current_view":null,"refresh_required":false,"error":null})
    }

    pub fn blank_presets_zone() -> Value {
        json!({"supported":false,"items":[],"corrupt":[],"list_actionable":false,
            "save_actionable":false,"applied_key":null})
    }

    fn route(&self, work_ref: &str) -> Result<(String, String), SlotProductError> {
        let job = self.jobs.load(work_ref).map_err(|_| {
            SlotProductError::coded(
                "AUTHORIZATION_FAILURE",
                format!("work {work_ref:?} 접근 불가"),
            )
        })?;
        let work_id = if job.authority_id.is_empty() {
            self.jobs
                .assign_authority_id(work_ref, &format!("w-{}", uuid::Uuid::new_v4().simple()))
                .map_err(|e| e.to_string())?
                .authority_id
        } else {
            job.authority_id
        };
        if work_id.is_empty() {
            return Err("Work authority id 부재".into());
        }
        let workspace = WorkspaceMetadataStore::new(&self.root)
            .and_then(|store| store.get_or_create(&(self.clock)()))
            .map_err(|e| e.to_string())?;
        Ok((work_id, workspace))
    }

    fn verify_token(
        &self,
        token: &str,
        workspace: &str,
        work_id: &str,
    ) -> Result<Claims, SlotProductError> {
        let secret = load_or_create_secret(&self.root).map_err(|_| {
            SlotProductError::coded("INVALID_CONFIGURATION_TOKEN", "token secret 손상")
        })?;
        let claims = open(token, &secret)
            .map_err(|error| SlotProductError::coded(error.code, error.detail))?;
        if claims.actor_binding_digest != actor_binding_digest("local-user", workspace)? {
            return Err(SlotProductError::coded(
                "TOKEN_ACTOR_BINDING_MISMATCH",
                "token actor binding 불일치",
            ));
        }
        if claims.workspace_instance_id != workspace {
            return Err(SlotProductError::coded(
                "CROSS_WORKSPACE_CONFIGURATION_TOKEN",
                "token workspace 불일치",
            ));
        }
        if claims.work_authority_id != work_id {
            return Err(SlotProductError::coded(
                "CROSS_WORK_CONFIGURATION_TOKEN",
                "token Work 가 route Work 와 다르다",
            ));
        }
        Ok(claims)
    }

    fn respond(
        &self,
        workspace: &str,
        work_id: &str,
        outcome: Option<&CommandOutcome>,
        token_app: Option<&str>,
    ) -> Result<Value, String> {
        let current =
            PerWorkFence::with(workspace, work_id, || self.read_fenced(workspace, work_id))
                .map_err(|e| e.to_string())??;
        let refresh_required = current.context_error
            || token_app.is_some_and(|app| current.application_id.as_deref() != Some(app))
            || outcome.is_some_and(|outcome| {
                current.application_id.as_deref() != Some(outcome.application_id.as_str())
            });
        let mutation = outcome.map(|outcome| {
            json!({
                "outcome_code":outcome.outcome_code,
                "changed":outcome.changed,
                "outcome_replayed":outcome.replayed,
                "request_relation":if matches!(outcome.outcome_code.as_str(),
                    "STALE_TEMPLATE_APPLICATION" | "STALE_CONFIGURATION") {
                    outcome.outcome_code.as_str()
                } else { "CURRENT" },
            })
        });
        Ok(
            json!({"mutation_outcome":mutation,"current_view":current.view,
            "refresh_required":refresh_required}),
        )
    }

    fn ensure_response(
        &self,
        work_ref: &str,
        token: Option<&str>,
    ) -> Result<Value, SlotProductError> {
        let (work_id, workspace) = self.route(work_ref)?;
        let token_app = token
            .map(|token| self.verify_token(token, &workspace, &work_id))
            .transpose()?
            .map(|claims| claims.template_application_id);
        match run_ensure(&self.root, &workspace, &work_id, &(self.clock)()) {
            Ok(outcome) => {
                Ok(self.respond(&workspace, &work_id, Some(&outcome), token_app.as_deref())?)
            }
            Err(error) => {
                let current = PerWorkFence::with(&workspace, &work_id, || {
                    self.read_fenced(&workspace, &work_id)
                })
                .map_err(|e| e.to_string())??;
                if current.context_error {
                    Ok(json!({"mutation_outcome":null,"current_view":current.view,
                        "refresh_required":true}))
                } else {
                    Err(error.into())
                }
            }
        }
    }

    pub fn open_slot_configuration(&self, work_ref: &str) -> Result<Value, SlotProductError> {
        self.ensure_response(work_ref, None)
    }

    pub fn refresh_slot_configuration(
        &self,
        work_ref: &str,
        configuration_token: Option<&str>,
    ) -> Result<Value, SlotProductError> {
        self.ensure_response(work_ref, configuration_token)
    }

    pub fn save_selection_preset(
        &self,
        work_ref: &str,
        token: &str,
        name: &str,
        confirmed_overwrite_key: Option<&str>,
    ) -> Result<Value, SlotProductError> {
        let (work_id, workspace) = self.route(work_ref)?;
        let claims = self.verify_token(token, &workspace, &work_id)?;
        let preset = PerWorkFence::with(&workspace, &work_id, || {
            capture_selection_preset(
                &self.root,
                &workspace,
                &work_id,
                &claims,
                name,
                &(self.clock)(),
            )
        })
        .map_err(|e| e.to_string())?;
        let preset = match preset {
            Ok(preset) => preset,
            Err((Some(code), detail)) => {
                return Ok(json!({"status":"REJECTED","code":code,
                "saved_key":null,"existing_key":null,"existing_created_at":null,"detail":detail}));
            }
            Err((None, error)) => return Err(error.into()),
        };
        let registry = self.preset_registry()?;
        let saved = if let Some(expected_key) = confirmed_overwrite_key {
            registry.save_confirmed(expected_key, &preset)
        } else {
            if let Some(existing) = registry
                .find_name(&preset.name)
                .map_err(|e| e.to_string())?
            {
                return Ok(needs_confirm(&preset, Some(existing), ""));
            }
            registry.add(&preset)
        };
        match saved {
            Ok(key) => Ok(saved_preset(&key)),
            Err(PresetStoreError::Invalid(detail)) => {
                let existing = registry
                    .find_name(&preset.name)
                    .map_err(|e| e.to_string())?;
                Ok(needs_confirm(&preset, existing, &detail))
            }
            Err(error) => Err(error.to_string().into()),
        }
    }

    pub fn apply_selection_preset(
        &self,
        work_ref: &str,
        token: &str,
        preset_key: &str,
    ) -> Result<Value, SlotProductError> {
        let (work_id, workspace) = self.route(work_ref)?;
        let claims = self.verify_token(token, &workspace, &work_id)?;
        let registry = self.preset_registry()?;
        let preset = match registry.load(preset_key) {
            Ok(preset) => preset,
            Err(PresetStoreError::Invalid(detail)) => {
                return Ok(rejected_apply("PRESET_NOT_FOUND", &detail));
            }
            Err(PresetStoreError::Codec(error)) => {
                return Ok(rejected_apply("PRESET_ENTRY_CORRUPT", &error.to_string()));
            }
            Err(PresetStoreError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                let path = registry.slot_path(preset_key).map_err(|e| e.to_string())?;
                let detail = format!(
                    "[Errno 2] No such file or directory: {}",
                    hwpx_filler::text_render::python_repr(&json!(path.to_string_lossy()))
                );
                return Ok(rejected_apply("PRESET_NOT_FOUND", &detail));
            }
            Err(PresetStoreError::Io(error)) if error.kind() == std::io::ErrorKind::InvalidData => {
                return Ok(rejected_apply("PRESET_ENTRY_CORRUPT", &error.to_string()));
            }
            Err(error) => return Err(error.to_string().into()),
        };
        let command = ConfigurationCommandContext {
            workspace_instance_id: workspace.clone(),
            expected_work_authority_id: work_id.clone(),
            token_work_authority_id: claims.work_authority_id.clone(),
            token_template_application_id: claims.template_application_id.clone(),
            token_selection_contract_id: claims.selection_semantic_contract_id.clone(),
            token_configuration_presence: claims.configuration_presence,
            token_configuration_version: claims.configuration_version,
            actor_binding_digest: claims.actor_binding_digest.clone(),
        };
        let applied = match run_apply_preset(&self.root, &command, &preset, &(self.clock)()) {
            Ok(applied) => applied,
            Err(error) if error.context_kind.is_some() => {
                let (code, message) =
                    context_error(&error.context_kind.expect("checked context kind"));
                return Ok(rejected_apply(code, message));
            }
            Err(error) => return Err(error.detail.into()),
        };
        let mut base = self.respond(
            &workspace,
            &work_id,
            Some(&applied.outcome),
            Some(&claims.template_application_id),
        )?;
        let broken: Vec<_> = applied
            .broken
            .iter()
            .map(|item| {
                json!({
                    "slot_id":item.slot_id,"selected_option_ids":item.selected_option_ids,
                    "clearable":item.clearable,"status":item.status,
                })
            })
            .collect();
        let object = base.as_object_mut().ok_or("slot response 형식 오류")?;
        object.insert("applied_slot_ids".into(), json!(applied.applied_slot_ids));
        object.insert("broken".into(), json!(broken));
        object.insert(
            "applied_count".into(),
            json!(applied.applied_slot_ids.len()),
        );
        object.insert("broken_count".into(), json!(broken.len()));
        object.insert("rejection_code".into(), Value::Null);
        object.insert("rejection_detail".into(), Value::Null);
        Ok(base)
    }

    fn preset_registry(&self) -> Result<PresetRegistry, String> {
        PresetRegistry::new(self.root.parent().unwrap_or(&self.root).join("presets"))
            .map_err(|e| e.to_string())
    }

    pub fn select_slot_option(
        &self,
        work_ref: &str,
        token: &str,
        slot_id: &str,
        option_id: &str,
        request_id: &str,
    ) -> Result<Value, SlotProductError> {
        let (work_id, workspace) = self.route(work_ref)?;
        let claims = self.verify_token(token, &workspace, &work_id)?;
        let command = ConfigurationCommandContext {
            workspace_instance_id: workspace.clone(),
            expected_work_authority_id: work_id.clone(),
            token_work_authority_id: claims.work_authority_id.clone(),
            token_template_application_id: claims.template_application_id.clone(),
            token_selection_contract_id: claims.selection_semantic_contract_id.clone(),
            token_configuration_presence: claims.configuration_presence,
            token_configuration_version: claims.configuration_version,
            actor_binding_digest: claims.actor_binding_digest.clone(),
        };
        let outcome = run_command(
            &self.root,
            &command,
            request_id,
            SELECT,
            slot_id,
            Some(option_id),
            &(self.clock)(),
        )?;
        Ok(self.respond(
            &workspace,
            &work_id,
            Some(&outcome),
            Some(&claims.template_application_id),
        )?)
    }

    pub fn presets_zone(
        &self,
        work_ref: &str,
        job: Option<&Job>,
        template_missing: bool,
        savable_selection: bool,
    ) -> Value {
        let blank = Self::blank_presets_zone();
        let Some(job) = job else { return blank };
        if work_ref.is_empty() || template_missing || !matches!(job.media(), "hwpx" | "txt") {
            return blank;
        }
        match self.list_presets(job) {
            Ok((items, corrupt, applied_key)) => json!({
                "supported":true,"error":null,"items":items,"corrupt":corrupt,
                "corrupt_code":"PRESET_ENTRY_CORRUPT",
                "list_actionable":!items.is_empty() || !corrupt.is_empty(),
                "save_actionable":savable_selection,"applied_key":applied_key,
            }),
            Err(_) => json!({
                "supported":true,"items":[],"corrupt":[],"list_actionable":true,
                "save_actionable":savable_selection,"applied_key":null,
                "error":{"code":"PRESET_LIST_UNAVAILABLE","message":LOAD_MESSAGE,
                    "action":{"key":"refresh","label":"다시 불러오기"}},
            }),
        }
    }

    fn list_presets(&self, job: &Job) -> Result<PresetRows, String> {
        let preset_dir = self.root.parent().unwrap_or(&self.root).join("presets");
        let registry = PresetRegistry::new(preset_dir).map_err(|e| e.to_string())?;
        let (entries, corrupt) = registry.list_presets().map_err(|e| e.to_string())?;
        let corrupt: Vec<_> = corrupt
            .iter()
            .map(|item| {
                json!({
                    "file_name":item.file_name,"error":item.error,
                })
            })
            .collect();
        let (context, current) = self.preset_context(job)?;
        let mut items = Vec::new();
        let mut applied_key = None;
        if let Some(context) = context {
            for (key, preset) in entries {
                let fit = fit_preset(&context, &preset.selection_set)?;
                if !fit.fully_applicable {
                    continue;
                }
                if applied_key.is_none()
                    && let Some(config) = &current
                    && !config.selections.selections.is_empty()
                    && semantic_selection_equal(&config.selections, &fit.applied)
                        .map_err(|error| error.to_string())?
                {
                    applied_key = Some(key.clone());
                }
                items.push(json!({"key":key,"name":preset.name,"created_at":preset.created_at}));
            }
        }
        Ok((items, corrupt, applied_key))
    }

    fn preset_context(
        &self,
        job: &Job,
    ) -> Result<
        (
            Option<SlotConfigurationContext>,
            Option<WorkSlotConfigurationDraft>,
        ),
        String,
    > {
        if job.authority_id.is_empty() {
            return Ok((None, None));
        }
        (|| -> Result<_, String> {
            let workspace = WorkspaceMetadataStore::new(&self.root)
                .and_then(|store| store.get_or_create(&(self.clock)()))
                .map_err(|error| error.to_string())?;
            let works = AtomicWorkTemplateStateStore::new(self.root.join("works"))
                .map_err(|error| error.to_string())?;
            let qualifications = FileQualificationObjectStore::new(self.root.join("qualification"));
            let candidates = FileCandidateObjectStore::new(self.root.join("candidates"));
            let context = match resolve_slot_configuration_context(
                ContextPorts {
                    work_state: &works,
                    qualification: &qualifications,
                    candidate: &candidates,
                },
                &workspace,
                &job.authority_id,
                None,
                None,
            ) {
                Ok(context) => context,
                Err(_) => return Ok((None, None)),
            };
            let configs = WorkSlotConfigurationStore::new(self.root.join("slot_configs"))
                .map_err(|error| error.to_string())?;
            let current = if configs
                .exists(&job.authority_id)
                .map_err(|error| error.to_string())?
            {
                let stored = configs
                    .load(&job.authority_id)
                    .map_err(|error| error.to_string())?;
                if stored.workspace_instance_id != workspace {
                    return Err("저장 workspace 가 current workspace 와 다르다".into());
                }
                stored
                    .configurations
                    .configurations
                    .into_iter()
                    .find(|item| {
                        item.base_template_application_id == context.template_application_id
                    })
            } else {
                None
            };
            Ok((Some(context), current))
        })()
    }

    pub fn zone(
        &self,
        work_ref: &str,
        job: Option<&Job>,
        template_missing: bool,
    ) -> Result<SlotRead, String> {
        let blank = Self::blank_zone();
        let Some(job) = job else {
            return Ok(SlotRead {
                zone: blank,
                resolution: None,
            });
        };
        if work_ref.is_empty() || template_missing || !matches!(job.media(), "hwpx" | "txt") {
            return Ok(SlotRead {
                zone: blank,
                resolution: None,
            });
        }
        if job.authority_id.is_empty() {
            return Ok(SlotRead {
                zone: json!({"supported":true,"initialized":false,
                "mutation_outcome":null,"current_view":null,"refresh_required":false,"error":null}),
                resolution: None,
            });
        }
        // Authorization is independent of any HMAC token and precedes context loading.
        let routed = self
            .jobs
            .load(work_ref)
            .map_err(|_| format!("work {work_ref:?} 접근 불가"))?;
        if routed.authority_id != job.authority_id || routed.name != job.name {
            return Err("route Work 와 주입 Job 이 불일치".into());
        }
        match self.read_current(&job.authority_id) {
            Ok(current) => Ok(SlotRead {
                zone: json!({"supported":true,"initialized":true,
                    "mutation_outcome":null,"current_view":current.view,
                    "refresh_required":current.context_error,"error":null}),
                resolution: current.resolution,
            }),
            Err(_) => Ok(SlotRead {
                zone: json!({"supported":true,"initialized":false,
                    "mutation_outcome":null,"current_view":null,
                    "refresh_required":false,
                    "error":{"code":"SLOT_CONFIGURATION_READ_ERROR","message":LOAD_MESSAGE,
                        "action":{"key":"refresh","label":"다시 불러오기"}}}),
                resolution: None,
            }),
        }
    }

    fn read_current(&self, work_id: &str) -> Result<CurrentRead, String> {
        let workspace = WorkspaceMetadataStore::new(&self.root)
            .and_then(|store| store.get_or_create(&(self.clock)()))
            .map_err(|error| error.to_string())?;
        PerWorkFence::with(&workspace, work_id, || {
            self.read_fenced(&workspace, work_id)
        })
        .map_err(|error| error.to_string())?
    }

    fn read_fenced(&self, workspace: &str, work_id: &str) -> Result<CurrentRead, String> {
        let works = AtomicWorkTemplateStateStore::new(self.root.join("works"))
            .map_err(|e| e.to_string())?;
        let qualifications = FileQualificationObjectStore::new(self.root.join("qualification"));
        let candidates = FileCandidateObjectStore::new(self.root.join("candidates"));
        let configs = WorkSlotConfigurationStore::new(self.root.join("slot_configs"))
            .map_err(|e| e.to_string())?;
        let context = resolve_slot_configuration_context(
            ContextPorts {
                work_state: &works,
                qualification: &qualifications,
                candidate: &candidates,
            },
            workspace,
            work_id,
            None,
            None,
        );
        let context = match context {
            Ok(context) => context,
            Err(error) => {
                let (code, message) = context_error(&error.kind);
                let projection = project_context_error(code, None);
                return Ok(CurrentRead {
                    view: current_view(&projection, None, Some(message)),
                    resolution: None,
                    context_error: true,
                    application_id: None,
                });
            }
        };
        let stored = if configs.exists(work_id).map_err(|e| e.to_string())? {
            let stored = configs.load(work_id).map_err(|e| e.to_string())?;
            if stored.workspace_instance_id != workspace {
                return Err("저장 workspace 가 current workspace 와 다르다".into());
            }
            stored.configurations.configurations
        } else {
            vec![]
        };
        let current = stored
            .iter()
            .find(|item| item.base_template_application_id == context.template_application_id);
        let selections =
            current.map_or_else(SlotSelectionSet::default, |item| item.selections.clone());
        let resolution = resolve_slot_configuration(
            &selections,
            &context.template_structure,
            &context.selection_semantic_contract,
        )
        .map_err(|error| error.to_string())?;
        let retained = retained_fate(&works, &context, &stored)?;
        let projection = project_current_slot_configuration(
            &context,
            current,
            &resolution,
            None,
            retained.as_ref(),
        )?;
        let version = current
            .map(|item| u32::try_from(item.version).map_err(|_| "token u32 값이 범위 초과"))
            .transpose()?;
        let secret = load_or_create_secret(&self.root)?;
        let token = sign(
            &Claims {
                workspace_instance_id: workspace.into(),
                work_authority_id: work_id.into(),
                template_application_id: context.template_application_id.clone(),
                selection_semantic_contract_id: context.selection_semantic_contract_id.clone(),
                configuration_presence: current.is_some(),
                configuration_version: version,
                actor_binding_digest: actor_binding_digest("local-user", workspace)?,
                issued_at: (self.clock)(),
            },
            &secret,
        )?;
        Ok(CurrentRead {
            view: current_view(&projection, Some(&token), None),
            resolution: Some(resolution),
            context_error: false,
            application_id: Some(context.template_application_id),
        })
    }
}

fn capture_selection_preset(
    root: &Path,
    workspace: &str,
    work_id: &str,
    claims: &Claims,
    name: &str,
    now: &str,
) -> Result<SelectionPreset, (Option<&'static str>, String)> {
    let works =
        AtomicWorkTemplateStateStore::new(root.join("works")).map_err(|e| (None, e.to_string()))?;
    let qualifications = FileQualificationObjectStore::new(root.join("qualification"));
    let candidates = FileCandidateObjectStore::new(root.join("candidates"));
    let context = resolve_slot_configuration_context(
        ContextPorts {
            work_state: &works,
            qualification: &qualifications,
            candidate: &candidates,
        },
        workspace,
        work_id,
        Some(&claims.template_application_id),
        None,
    )
    .map_err(|error| {
        let (code, message) = context_error(&error.kind);
        (Some(code), message.to_owned())
    })?;
    if context.selection_semantic_contract_id != claims.selection_semantic_contract_id {
        return Err((None, "token contract claim 이 current 와 다르다".into()));
    }
    let configs = WorkSlotConfigurationStore::new(root.join("slot_configs"))
        .map_err(|e| (None, e.to_string()))?;
    let config = if configs.exists(work_id).map_err(|e| (None, e.to_string()))? {
        let stored = configs.load(work_id).map_err(|e| (None, e.to_string()))?;
        if stored.workspace_instance_id != workspace {
            return Err((None, "저장 workspace 가 current workspace 와 다르다".into()));
        }
        stored
            .configurations
            .configurations
            .into_iter()
            .find(|item| item.base_template_application_id == context.template_application_id)
    } else {
        None
    };
    plan_preset_save(
        config.as_ref(),
        name,
        &context.template_application_id,
        &context.selection_semantic_contract_id,
        now,
    )
    .map_err(|error| (Some(error.code), error.detail))
}

fn current_view(projection: &Value, token: Option<&str>, context_message: Option<&str>) -> Value {
    json!({
        "view_status":projection["view_status"],
        "configuration_status":projection["configuration_status"],
        "context_error":projection["context_error"],
        "context_error_message":context_message,
        "new_configuration_token":token,
        "projection":if projection["view_status"] == CONTEXT_ERROR { Value::Null } else { projection.clone() },
        "blocking_items":projection["blocking_items"],
        "informational_changes":projection["informational_changes"],
    })
}

fn saved_preset(key: &str) -> Value {
    json!({"status":"SAVED","code":null,"saved_key":key,"existing_key":null,
        "existing_created_at":null,"detail":null})
}
fn rejected_apply(code: &str, detail: &str) -> Value {
    json!({"mutation_outcome":null,"current_view":null,"refresh_required":false,
        "applied_slot_ids":[],"broken":[],"applied_count":0,"broken_count":0,
        "rejection_code":code,"rejection_detail":detail})
}
fn needs_confirm(
    preset: &SelectionPreset,
    existing: Option<(String, SelectionPreset)>,
    detail: &str,
) -> Value {
    let existing_key = existing.as_ref().map(|item| item.0.as_str());
    let created = existing.as_ref().map(|item| item.1.created_at.as_str());
    let detail = if detail.is_empty() {
        format!("같은 이름의 프리셋이 이미 있습니다: {}", preset.name)
    } else {
        detail.to_owned()
    };
    json!({"status":"NEEDS_CONFIRM","code":"PRESET_NAME_CONFLICT",
        "saved_key":null,"existing_key":existing_key,"existing_created_at":created,"detail":detail})
}

fn context_error(kind: &ContextErrorKind) -> (&'static str, &'static str) {
    match kind {
        ContextErrorKind::TemplateInitializationRequired => (
            "TEMPLATE_INITIALIZATION_REQUIRED",
            "템플릿 확인이 끝나지 않아 포함할 내용을 불러오지 못했습니다. 템플릿을 확인하세요.",
        ),
        ContextErrorKind::StaleTemplateApplication => (
            "STALE_TEMPLATE_APPLICATION",
            "템플릿이 바뀌어 포함할 내용을 불러오지 못했습니다. 템플릿을 다시 확인하세요.",
        ),
        ContextErrorKind::UnsupportedTemplateStructureProjection => (
            "UNSUPPORTED_TEMPLATE_STRUCTURE_PROJECTION",
            "이 템플릿 구조에서는 포함할 내용을 선택할 수 없습니다. 다른 템플릿을 적용하세요.",
        ),
        ContextErrorKind::TemplateStructureIntegrity => (
            "TEMPLATE_STRUCTURE_INTEGRITY_ERROR",
            "템플릿 구조를 확인할 수 없어 포함할 내용을 불러오지 못했습니다. 템플릿을 다시 확인하세요.",
        ),
        ContextErrorKind::AppliedTemplateContentIntegrity => (
            "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR",
            "적용된 템플릿 파일을 확인할 수 없어 포함할 내용을 불러오지 못했습니다. 템플릿을 다시 확인하세요.",
        ),
        ContextErrorKind::CrossWork => (
            "CROSS_WORK_CONTEXT",
            "현재 문서 작업과 템플릿이 맞지 않아 포함할 내용을 불러오지 못했습니다. 문서 작업을 다시 연 뒤 템플릿을 확인하세요.",
        ),
        _ => ("SLOT_CONFIGURATION_CONTEXT_ERROR", CONTEXT_FALLBACK),
    }
}

fn retained_fate(
    works: &AtomicWorkTemplateStateStore,
    context: &SlotConfigurationContext,
    stored: &[WorkSlotConfigurationDraft],
) -> Result<Option<SlotConfigurationResolution>, String> {
    if !stored
        .iter()
        .any(|item| item.base_template_application_id != context.template_application_id)
    {
        return Ok(None);
    }
    let aggregate = match works.load(&context.work_id) {
        Ok(aggregate) => aggregate,
        Err(error) if error.kind == WorkStoreErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    let applications: HashMap<_, _> = aggregate
        .applications
        .iter()
        .map(|item| {
            (
                item.application_id.clone(),
                ReconciliationApplication {
                    application_id: item.application_id.clone(),
                    previous_application_id: item.previous_application_id.clone(),
                    application_epoch: item.application_epoch,
                    work_id: item.work_id.clone(),
                    template_lineage_id: aggregate.work.template_lineage_id.clone(),
                },
            )
        })
        .collect();
    let configurations: HashMap<_, _> = stored
        .iter()
        .map(|item| (item.base_template_application_id.clone(), item.clone()))
        .collect();
    let Ok(Some(source)) = find_nearest_predecessor_configuration(
        &context.template_application_id,
        &applications,
        &configurations,
    ) else {
        return Ok(None);
    };
    if source.selections.selections.is_empty() {
        return Ok(None);
    }
    resolve_slot_configuration(
        &source.selections,
        &context.template_structure,
        &context.selection_semantic_contract,
    )
    .map(Some)
    .map_err(|error| error.to_string())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::managed_generation_service::tests::RunFixture;
    use crate::template_change_coordinator::TemplateChangeCoordinator;
    use hwpx_filler::slot_selection::SlotSelection;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn product(fixture: &RunFixture) -> SlotConfigurationProduct {
        SlotConfigurationProduct::new(&fixture.authority, fixture.jobs.clone(), || {
            "2026-11-05T09:00:00".into()
        })
    }

    fn token(response: &Value) -> &str {
        response["current_view"]["new_configuration_token"]
            .as_str()
            .unwrap()
    }

    fn passive(product: &SlotConfigurationProduct, fixture: &RunFixture) -> Value {
        product
            .zone("생성", Some(&fixture.jobs.load("생성").unwrap()), false)
            .unwrap()
            .zone
    }

    fn durable_files(root: &Path) -> std::collections::BTreeMap<PathBuf, Vec<u8>> {
        fn visit(
            root: &Path,
            path: &Path,
            files: &mut std::collections::BTreeMap<PathBuf, Vec<u8>>,
        ) {
            if !path.exists() {
                return;
            }
            for entry in fs::read_dir(path).unwrap() {
                let entry = entry.unwrap();
                if entry.file_type().unwrap().is_dir() {
                    visit(root, &entry.path(), files);
                } else {
                    files.insert(
                        entry.path().strip_prefix(root).unwrap().to_owned(),
                        fs::read(entry.path()).unwrap(),
                    );
                }
            }
        }
        let mut files = std::collections::BTreeMap::new();
        visit(root, root, &mut files);
        files
    }

    pub(crate) fn advance(fixture: &RunFixture, bytes: &[u8]) {
        let job = fixture.jobs.load("생성").unwrap();
        fs::write(&job.template_path, bytes).unwrap();
        let coordinator =
            TemplateChangeCoordinator::new(&fixture.authority, fixture.jobs.clone(), || {
                "2026-11-05T09:01:00".into()
            })
            .unwrap();
        let checked = coordinator.check("생성", "successor").unwrap();
        assert_eq!(checked["preparation"]["status"], "ready", "{checked}");
        let applied = coordinator
            .apply(
                "생성",
                checked["preparation"]["change_token"].as_str().unwrap(),
            )
            .unwrap();
        assert_eq!(applied["status"], "applied", "{applied}");
    }

    #[test]
    fn token_binding_authorization_and_stale_configuration_cannot_mutate_current_choices() {
        let fixture = RunFixture::txt();
        let product = product(&fixture);
        let initial = product.open_slot_configuration("생성").unwrap();
        assert_eq!(initial["current_view"]["view_status"], "CURRENT");
        assert_eq!(initial["refresh_required"], false);
        let secret = load_or_create_secret(&fixture.authority).unwrap();
        let claims = open(token(&initial), &secret).unwrap();
        let before = durable_files(&fixture.authority);
        for (axis, code) in [
            ("work", "CROSS_WORK_CONFIGURATION_TOKEN"),
            ("workspace", "CROSS_WORKSPACE_CONFIGURATION_TOKEN"),
            ("actor", "TOKEN_ACTOR_BINDING_MISMATCH"),
        ] {
            let mut forged = claims.clone();
            match axis {
                "work" => forged.work_authority_id = "other".into(),
                "workspace" => forged.workspace_instance_id = "other".into(),
                "actor" => forged.actor_binding_digest = "sha256:other".into(),
                _ => unreachable!(),
            }
            let signed = sign(&forged, &secret).unwrap();
            assert_eq!(
                product
                    .select_slot_option("생성", &signed, "s1", "o1", "rejected")
                    .unwrap_err()
                    .code,
                Some(code)
            );
            assert_eq!(durable_files(&fixture.authority), before, "{axis}");
        }
        assert_eq!(
            product
                .select_slot_option("생성", "hfslot1.tampered.sig", "s1", "o1", "rejected")
                .unwrap_err()
                .code,
            Some("INVALID_CONFIGURATION_TOKEN")
        );
        assert_eq!(
            product
                .select_slot_option("missing", token(&initial), "s1", "o1", "rejected")
                .unwrap_err()
                .code,
            Some("AUTHORIZATION_FAILURE")
        );
        assert_eq!(
            product.open_slot_configuration("missing").unwrap_err().code,
            Some("AUTHORIZATION_FAILURE")
        );
        assert_eq!(durable_files(&fixture.authority), before);
        let secret_path = fixture.authority.join("slot_token_secret.json");
        let saved_secret = fs::read(&secret_path).unwrap();
        fs::write(&secret_path, b"{corrupt").unwrap();
        let damaged = durable_files(&fixture.authority);
        assert_eq!(
            product
                .select_slot_option("생성", token(&initial), "s1", "o1", "rejected")
                .unwrap_err()
                .code,
            Some("INVALID_CONFIGURATION_TOKEN")
        );
        assert_eq!(durable_files(&fixture.authority), damaged);
        let unreadable = passive(&product, &fixture);
        assert_eq!(unreadable["error"]["code"], "SLOT_CONFIGURATION_READ_ERROR");
        assert!(unreadable["current_view"].is_null());
        fs::write(&secret_path, saved_secret).unwrap();
        assert_eq!(passive(&product, &fixture)["error"], Value::Null);

        let first = product
            .select_slot_option("생성", token(&initial), "s1", "o1", "r1")
            .unwrap();
        assert_eq!(first["mutation_outcome"]["outcome_code"], "CHANGED");
        let first_claims = open(token(&first), &secret).unwrap();
        let first_view = &first["current_view"]["projection"];
        assert_eq!(
            first_claims.configuration_presence,
            first_view["configuration_present"].as_bool().unwrap()
        );
        assert_eq!(
            first_claims.configuration_version.map(u64::from),
            first_view["configuration_version"].as_u64()
        );
        assert_eq!(
            first_claims.template_application_id,
            claims.template_application_id
        );
        let second = product
            .select_slot_option("생성", token(&first), "s1", "o2", "r2")
            .unwrap();
        assert_eq!(second["mutation_outcome"]["changed"], true);
        let stale = product
            .select_slot_option("생성", token(&first), "s1", "o1", "r3")
            .unwrap();
        assert_eq!(
            stale["mutation_outcome"]["outcome_code"],
            "STALE_CONFIGURATION"
        );
        assert_eq!(
            stale["mutation_outcome"]["request_relation"],
            "STALE_CONFIGURATION"
        );
        assert_eq!(stale["mutation_outcome"]["changed"], false);
        assert_eq!(
            stale["current_view"]["projection"],
            second["current_view"]["projection"]
        );
        let replay = product
            .select_slot_option("생성", token(&initial), "s1", "o1", "r1")
            .unwrap();
        assert_eq!(replay["mutation_outcome"]["outcome_code"], "CHANGED");
        assert_eq!(replay["mutation_outcome"]["outcome_replayed"], true);
        assert_eq!(
            replay["current_view"]["projection"],
            second["current_view"]["projection"]
        );

        let job = fixture.jobs.load("생성").unwrap();
        let mut bytes = fs::read(&job.template_path).unwrap();
        bytes.extend_from_slice(b"Changed\n");
        advance(&fixture, &bytes);
        let stale = product
            .select_slot_option("생성", token(&second), "s1", "o1", "r4")
            .unwrap();
        assert_eq!(
            stale["mutation_outcome"]["outcome_code"],
            "STALE_TEMPLATE_APPLICATION"
        );
        assert_eq!(
            stale["mutation_outcome"]["request_relation"],
            "STALE_TEMPLATE_APPLICATION"
        );
        assert_eq!(stale["mutation_outcome"]["changed"], false);
        assert_eq!(stale["refresh_required"], true);
        assert_eq!(stale["current_view"]["view_status"], "CURRENT");
        let new_claims = open(token(&stale), &secret).unwrap();
        assert_ne!(
            new_claims.template_application_id,
            claims.template_application_id
        );
        let fresh = product
            .select_slot_option("생성", token(&stale), "s1", "o1", "r5")
            .unwrap();
        assert_eq!(fresh["mutation_outcome"]["changed"], true);
        fixture.jobs.delete("생성").unwrap();
        assert_eq!(
            product
                .select_slot_option("생성", token(&fresh), "s1", "o2", "r6")
                .unwrap_err()
                .code,
            Some("AUTHORIZATION_FAILURE")
        );
        let mut replacement = Job {
            name: "생성".into(),
            template_path: job.template_path,
            ..Job::default()
        };
        fixture.jobs.save(&mut replacement, false).unwrap();
        assert_eq!(
            product
                .select_slot_option("생성", token(&fresh), "s1", "o2", "r6")
                .unwrap_err()
                .code,
            Some("CROSS_WORK_CONFIGURATION_TOKEN")
        );
    }

    #[test]
    fn successor_retained_choices_survive_passive_reads_open_and_partial_reselection() {
        let original = concat!(
            "{{성명}}\n",
            "{{#항목 s1 공고 상세}}\n",
            "{{#선택 o1 유지}}\nA\n{{/선택}}\n",
            "{{#선택 o2 제거}}\nB\n{{/선택}}\n{{/항목}}\n",
            "{{#항목 s2 부가 안내}}\n{{#선택 o3 안내}}\nC\n{{/선택}}\n{{/항목}}\n"
        );
        let successor =
            "{{성명}}\n{{#항목 s1 공고 상세}}\n{{#선택 o1 유지}}\nChanged\n{{/선택}}\n{{/항목}}\n";
        for (selected, fate) in [("o1", "RESOLVED"), ("o2", "SELECTED_OPTION_REMOVED")] {
            let fixture = RunFixture::with_template("txt", original.as_bytes());
            let product = product(&fixture);
            let opened = product.open_slot_configuration("생성").unwrap();
            let first = product
                .select_slot_option("생성", token(&opened), "s1", selected, "r1")
                .unwrap();
            let chosen = product
                .select_slot_option("생성", token(&first), "s2", "o3", "r2")
                .unwrap();
            assert_eq!(
                chosen["current_view"]["projection"]["retained_selections"],
                json!([])
            );
            advance(&fixture, successor.as_bytes());
            let before = durable_files(&fixture.root);
            assert!(!before.is_empty());
            let read = passive(&product, &fixture);
            let projection = &read["current_view"]["projection"];
            assert_eq!(projection["configuration_status"], "NEEDS_SELECTION");
            assert_eq!(
                projection["retained_selections"],
                json!([
                    {"slot_id":"s1", "slot_display_text":"공고 상세", "option_ids":[selected], "fate":fate},
                    {"slot_id":"s2", "slot_display_text":null, "option_ids":["o3"], "fate":"SLOT_REMOVED"},
                ])
            );
            assert_eq!(projection["slots"].as_array().unwrap().len(), 1);
            assert_eq!(projection["slots"][0]["effective_option_ids"], json!([]));
            assert_eq!(projection["slots"][0]["settled"], false);
            for _ in 0..3 {
                assert_eq!(
                    passive(&product, &fixture)["current_view"]["projection"],
                    *projection
                );
            }
            assert_eq!(durable_files(&fixture.root), before);
            let work_id = fixture.jobs.load("생성").unwrap().authority_id;
            let workspace = WorkspaceMetadataStore::new(&fixture.authority)
                .unwrap()
                .read()
                .unwrap()
                .unwrap();
            let works = AtomicWorkTemplateStateStore::new(fixture.authority.join("works")).unwrap();
            let qualifications =
                FileQualificationObjectStore::new(fixture.authority.join("qualification"));
            let candidates = FileCandidateObjectStore::new(fixture.authority.join("candidates"));
            let context = resolve_slot_configuration_context(
                ContextPorts {
                    work_state: &works,
                    qualification: &qualifications,
                    candidate: &candidates,
                },
                &workspace,
                &work_id,
                None,
                None,
            )
            .unwrap();
            let stored = WorkSlotConfigurationStore::new(fixture.authority.join("slot_configs"))
                .unwrap()
                .load(&work_id)
                .unwrap()
                .configurations
                .configurations;
            assert!(retained_fate(&works, &context, &stored).unwrap().is_some());
            let work_path = fixture
                .authority
                .join("works")
                .join(format!("{work_id}.json"));
            let saved_work = fs::read(&work_path).unwrap();
            fs::write(&work_path, b"{corrupt").unwrap();
            assert!(retained_fate(&works, &context, &stored).is_err());
            assert_eq!(fs::read(&work_path).unwrap(), b"{corrupt");
            fs::write(&work_path, saved_work).unwrap();
            #[cfg(windows)]
            {
                use std::os::windows::fs::OpenOptionsExt;
                let held = fs::OpenOptions::new()
                    .read(true)
                    .share_mode(0)
                    .open(&work_path)
                    .unwrap();
                assert!(retained_fate(&works, &context, &stored).is_err());
                drop(held);
            }
            assert_eq!(durable_files(&fixture.root), before);
            let opened = product.open_slot_configuration("생성").unwrap();
            assert_ne!(durable_files(&fixture.root), before);
            assert_eq!(
                opened["current_view"]["projection"]["retained_selections"],
                projection["retained_selections"]
            );
            assert_eq!(
                passive(&product, &fixture)["current_view"]["projection"],
                opened["current_view"]["projection"]
            );
            let answered = product
                .select_slot_option("생성", token(&opened), "s1", "o1", "r3")
                .unwrap();
            assert_eq!(answered["mutation_outcome"]["changed"], true);
            assert_eq!(
                answered["current_view"]["projection"]["retained_selections"],
                json!([
                    {"slot_id":"s2", "slot_display_text":null, "option_ids":["o3"], "fate":"SLOT_REMOVED"},
                ])
            );
            assert_eq!(
                answered["current_view"]["projection"]["slots"][0]["settled"],
                true
            );
        }
    }

    #[test]
    fn preset_save_confirms_exact_target_and_apply_checks_current_authority() {
        let fixture = RunFixture::txt();
        let product = product(&fixture);
        let opened = product.open_slot_configuration("생성").unwrap();
        let rejected = product
            .save_selection_preset("생성", token(&opened), "표준", None)
            .unwrap();
        assert_eq!(rejected["status"], "REJECTED");
        assert_eq!(rejected["code"], "PRESET_EMPTY_SELECTION");
        assert!(rejected["saved_key"].is_null());
        let selected = product
            .select_slot_option("생성", token(&opened), "s1", "o1", "one")
            .unwrap();
        let saved = product
            .save_selection_preset("생성", token(&selected), " 표준 ", None)
            .unwrap();
        let key = saved["saved_key"].as_str().unwrap().to_owned();
        assert_eq!(saved, saved_preset(&key));
        let registry = product.preset_registry().unwrap();
        let preset = registry.load(&key).unwrap();
        assert_eq!(
            preset.selection_set.selections[0].selected_option_ids,
            ["o1"]
        );
        let claims = open(
            token(&selected),
            &load_or_create_secret(&fixture.authority).unwrap(),
        )
        .unwrap();
        assert_eq!(
            preset.provenance_map(),
            json!({
                "template_application_id": claims.template_application_id,
                "selection_contract_id": "slot-selection/v1"
            })
            .as_object()
            .unwrap()
            .clone()
        );
        let before = durable_files(&fixture.root);
        let conflict = product
            .save_selection_preset("생성", token(&selected), "표준", None)
            .unwrap();
        assert_eq!(conflict["status"], "NEEDS_CONFIRM");
        assert_eq!(conflict["code"], "PRESET_NAME_CONFLICT");
        assert_eq!(conflict["existing_key"], key);
        assert_eq!(conflict["existing_created_at"], preset.created_at);
        assert!(conflict["saved_key"].is_null());
        assert_eq!(durable_files(&fixture.root), before);

        let second = product
            .select_slot_option("생성", token(&selected), "s1", "o2", "two")
            .unwrap();
        let before = durable_files(&fixture.root);
        let stale = product
            .apply_selection_preset("생성", token(&selected), &key)
            .unwrap();
        assert_eq!(
            stale["mutation_outcome"]["outcome_code"],
            "STALE_CONFIGURATION"
        );
        assert_eq!(stale["applied_count"], 0);
        assert_eq!(durable_files(&fixture.root), before);
        let restored = product
            .apply_selection_preset("생성", token(&second), &key)
            .unwrap();
        assert_eq!(restored["mutation_outcome"]["outcome_code"], "CHANGED");
        assert_eq!(restored["applied_slot_ids"], json!(["s1"]));
        assert_eq!(restored["broken_count"], 0);
        assert_eq!(
            restored["current_view"]["configuration_status"],
            "SLOT_SELECTIONS_COMPLETE"
        );
        let again = product
            .apply_selection_preset("생성", token(&restored), &key)
            .unwrap();
        assert_eq!(again["mutation_outcome"]["outcome_code"], "NO_CHANGE");
        let second = product
            .select_slot_option("생성", token(&again), "s1", "o2", "three")
            .unwrap();
        let overwritten = product
            .save_selection_preset("생성", token(&second), "표준", Some(&key))
            .unwrap();
        assert_eq!(overwritten, saved_preset(&key));
        assert_eq!(
            registry.load(&key).unwrap().selection_set.selections[0].selected_option_ids,
            ["o2"]
        );
        registry.delete(&key).unwrap();
        let replacement = registry.add(&preset).unwrap();
        let before = durable_files(&fixture.root);
        let conflict = product
            .save_selection_preset("생성", token(&second), "표준", Some(&key))
            .unwrap();
        assert_eq!(conflict["status"], "NEEDS_CONFIRM");
        assert_eq!(conflict["existing_key"], replacement);
        assert_eq!(durable_files(&fixture.root), before);
        registry.delete(&replacement).unwrap();
        let saved = product
            .save_selection_preset("생성", token(&second), "표준", Some(&key))
            .unwrap();
        let new_key = saved["saved_key"].as_str().unwrap();
        assert_eq!(saved["status"], "SAVED");
        assert_ne!(new_key, key);

        let secret = load_or_create_secret(&fixture.authority).unwrap();
        for mismatch in ["work", "contract"] {
            let mut bad = open(token(&second), &secret).unwrap();
            if mismatch == "work" {
                bad.work_authority_id = "foreign".into();
            } else {
                bad.selection_semantic_contract_id = "other-contract".into();
            }
            let forged = sign(&bad, &secret).unwrap();
            let before = durable_files(&fixture.root);
            assert!(
                product
                    .save_selection_preset("생성", &forged, "forbidden", None)
                    .is_err()
            );
            assert!(
                product
                    .apply_selection_preset("생성", &forged, new_key)
                    .is_err()
            );
            assert_eq!(durable_files(&fixture.root), before);
        }
        for missing in ["absent", "../escape"] {
            let before = durable_files(&fixture.root);
            let result = product
                .apply_selection_preset("생성", token(&second), missing)
                .unwrap();
            assert_eq!(result["rejection_code"], "PRESET_NOT_FOUND");
            assert!(result["mutation_outcome"].is_null());
            assert!(result["current_view"].is_null());
            assert_eq!(durable_files(&fixture.root), before);
        }
        let path = fixture.jobs.load("생성").unwrap().template_path;
        let mut bytes = fs::read(path).unwrap();
        bytes.extend_from_slice(b"\nnew ending");
        advance(&fixture, &bytes);
        let before = durable_files(&fixture.root);
        let stale = product
            .apply_selection_preset("생성", token(&second), new_key)
            .unwrap();
        assert_eq!(
            stale["mutation_outcome"]["outcome_code"],
            "STALE_TEMPLATE_APPLICATION"
        );
        assert_eq!(stale["applied_count"], 0);
        let refused = product
            .save_selection_preset("생성", token(&second), "old", None)
            .unwrap();
        assert_eq!(refused["code"], "STALE_TEMPLATE_APPLICATION");
        assert_eq!(durable_files(&fixture.root), before);
    }

    #[test]
    fn preset_list_filters_incompatible_entries_and_marks_only_current_matching_content() {
        let fixture = RunFixture::txt();
        let product = product(&fixture);
        let job = fixture.jobs.load("생성").unwrap();
        let opened = product.open_slot_configuration("생성").unwrap();
        let registry = product.preset_registry().unwrap();
        let empty = product.presets_zone("생성", Some(&job), false, false);
        assert_eq!(
            (
                empty["list_actionable"].clone(),
                empty["save_actionable"].clone()
            ),
            (json!(false), json!(false))
        );
        assert!(empty["applied_key"].is_null());
        let mut keys = Vec::new();
        for (name, choices) in [
            ("나중", vec![("s1", "o1")]),
            ("가장먼저", vec![("s1", "o1")]),
            ("다른슬롯", vec![("s1", "o1"), ("gone", "x")]),
            ("다른옵션", vec![("s1", "gone")]),
        ] {
            let preset = SelectionPreset::new(
                name,
                SlotSelectionSet::new(
                    choices
                        .into_iter()
                        .map(|(s, o)| SlotSelection::new(s, vec![o.into()]).unwrap())
                        .collect(),
                )
                .unwrap(),
                vec![],
                "t0",
            )
            .unwrap();
            keys.push(registry.add(&preset).unwrap());
        }
        fs::write(registry.slot_path("broken").unwrap(), b"{broken").unwrap();
        let before = durable_files(&fixture.root);
        let zone = product.presets_zone("생성", Some(&job), false, false);
        assert_eq!(
            zone["items"]
                .as_array()
                .unwrap()
                .iter()
                .map(|i| i["name"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["가장먼저", "나중"]
        );
        assert_eq!(zone["corrupt"].as_array().unwrap().len(), 1);
        assert_eq!(zone["list_actionable"], true);
        assert!(zone["applied_key"].is_null());
        assert_eq!(durable_files(&fixture.root), before);
        let selected = product
            .select_slot_option("생성", token(&opened), "s1", "o1", "one")
            .unwrap();
        let zone = product.presets_zone("생성", Some(&job), false, true);
        assert_eq!(zone["applied_key"], keys[1]);
        assert_eq!(zone["save_actionable"], true);
        product
            .select_slot_option("생성", token(&selected), "s1", "o2", "two")
            .unwrap();
        assert!(product.presets_zone("생성", Some(&job), false, true)["applied_key"].is_null());
        let mut no_context = job.clone();
        no_context.authority_id.clear();
        let zone = product.presets_zone("생성", Some(&no_context), false, false);
        assert_eq!(zone["items"], json!([]));
        assert_eq!(zone["corrupt"].as_array().unwrap().len(), 1);
        assert!(zone["applied_key"].is_null());
        for key in keys {
            registry.delete(&key).unwrap();
        }
        let zone = product.presets_zone("생성", Some(&job), false, true);
        assert_eq!(zone["items"], json!([]));
        assert_eq!(zone["list_actionable"], true);
        assert!(zone["applied_key"].is_null());
        let preset_dir = fixture.root.join("presets");
        let held_dir = fixture.root.join("presets-held");
        fs::rename(&preset_dir, &held_dir).unwrap();
        fs::write(&preset_dir, b"not a directory").unwrap();
        let unavailable = product.presets_zone("생성", Some(&job), false, true);
        assert_eq!(unavailable["error"]["code"], "PRESET_LIST_UNAVAILABLE");
        assert_eq!(unavailable["error"]["action"]["key"], "refresh");
        assert_eq!(unavailable["list_actionable"], true);
        fs::remove_file(&preset_dir).unwrap();
        fs::rename(&held_dir, &preset_dir).unwrap();
    }

    #[test]
    fn slotless_work_keeps_read_passive_and_replays_unknown_target() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/slot-product-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(root.join("templates")).unwrap();
        let template = root.join("templates/template.txt");
        fs::write(&template, b"Hello {{name}}\n").unwrap();
        let jobs = Arc::new(
            JobRegistry::new(root.join("jobs"), {
                let templates = root.join("templates");
                move || templates.clone()
            })
            .unwrap(),
        );
        let mut job = Job {
            name: "Example".into(),
            template_path: template.to_string_lossy().into(),
            ..Job::default()
        };
        jobs.save(&mut job, false).unwrap();
        let authority = root.join("template_authority");
        let product = SlotConfigurationProduct::new(&authority, jobs.clone(), || {
            "2026-11-05T09:00:00".into()
        });
        let uninitialized = product.open_slot_configuration("Example").unwrap();
        assert_eq!(
            uninitialized["current_view"]["view_status"],
            "CONTEXT_ERROR"
        );
        assert_eq!(
            uninitialized["current_view"]["context_error"],
            "TEMPLATE_INITIALIZATION_REQUIRED"
        );
        assert_eq!(
            uninitialized["current_view"]["context_error_message"],
            "템플릿 확인이 끝나지 않아 포함할 내용을 불러오지 못했습니다. 템플릿을 확인하세요."
        );
        assert!(uninitialized["current_view"]["new_configuration_token"].is_null());
        assert_eq!(uninitialized["refresh_required"], true);
        let job = jobs.load("Example").unwrap();
        let passive = product.zone("Example", Some(&job), false).unwrap();
        assert_eq!(passive.zone["current_view"], uninitialized["current_view"]);
        assert!(product.zone("missing", Some(&job), false).is_err());
        let mut foreign = job.clone();
        foreign.authority_id = "foreign".into();
        assert!(product.zone("Example", Some(&foreign), false).is_err());
        for (kind, code) in [
            (
                ContextErrorKind::TemplateInitializationRequired,
                "TEMPLATE_INITIALIZATION_REQUIRED",
            ),
            (
                ContextErrorKind::StaleTemplateApplication,
                "STALE_TEMPLATE_APPLICATION",
            ),
            (
                ContextErrorKind::UnsupportedTemplateStructureProjection,
                "UNSUPPORTED_TEMPLATE_STRUCTURE_PROJECTION",
            ),
            (
                ContextErrorKind::TemplateStructureIntegrity,
                "TEMPLATE_STRUCTURE_INTEGRITY_ERROR",
            ),
            (
                ContextErrorKind::AppliedTemplateContentIntegrity,
                "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR",
            ),
            (ContextErrorKind::CrossWork, "CROSS_WORK_CONTEXT"),
        ] {
            let (actual_code, message) = context_error(&kind);
            assert_eq!(actual_code, code);
            assert!(!message.contains(code));
            assert_ne!(message, CONTEXT_FALLBACK);
        }
        assert_eq!(context_error(&ContextErrorKind::Read).1, CONTEXT_FALLBACK);
        let coordinator = TemplateChangeCoordinator::new(&authority, jobs.clone(), || {
            "2026-11-05T09:00:00".into()
        })
        .unwrap();
        assert_eq!(
            coordinator.ensure_bootstrapped("Example").unwrap()["ok"],
            true
        );
        let job = jobs.load("Example").unwrap();
        let read = product.zone("Example", Some(&job), false).unwrap();
        assert_eq!(
            read.zone["current_view"]["configuration_status"],
            "NOT_APPLICABLE"
        );
        assert!(
            !authority
                .join("slot_configs")
                .join(format!("{}.json", job.authority_id))
                .exists()
        );
        let opened = product.open_slot_configuration("Example").unwrap();
        assert_eq!(opened["current_view"], read.zone["current_view"]);
        assert_eq!(opened["mutation_outcome"]["outcome_code"], "NO_CHANGE");
        assert_eq!(
            opened["current_view"]["configuration_status"],
            "NOT_APPLICABLE"
        );
        assert!(
            !authority
                .join("slot_configs")
                .join(format!("{}.json", job.authority_id))
                .exists()
        );
        let token = read.zone["current_view"]["new_configuration_token"]
            .as_str()
            .unwrap();
        let empty_preset = product
            .save_selection_preset("Example", token, "First", None)
            .unwrap();
        assert_eq!(empty_preset["code"], "PRESET_EMPTY_SELECTION");
        let absent = product
            .apply_selection_preset("Example", token, "absent")
            .unwrap();
        assert_eq!(absent["rejection_code"], "PRESET_NOT_FOUND");
        assert_eq!(
            absent["rejection_detail"],
            format!(
                "[Errno 2] No such file or directory: {}",
                hwpx_filler::text_render::python_repr(&json!(
                    root.join("presets")
                        .join("absent.preset.json")
                        .to_string_lossy()
                ))
            )
        );
        let preset = SelectionPreset::new(
            "Retained",
            SlotSelectionSet::new(vec![
                SlotSelection::new("missing", vec!["x".into()]).unwrap(),
            ])
            .unwrap(),
            vec![],
            "2026-11-05T09:00:00",
        )
        .unwrap();
        let registry = PresetRegistry::new(root.join("presets")).unwrap();
        let preset_key = registry.add(&preset).unwrap();
        let proposed = product
            .apply_selection_preset("Example", token, &preset_key)
            .unwrap();
        assert_eq!(proposed["mutation_outcome"]["outcome_code"], "NO_CHANGE");
        assert_eq!(proposed["broken_count"], 1);
        assert_eq!(proposed["broken"][0]["status"], "SLOT_REMOVED");
        fs::write(registry.slot_path("corrupt").unwrap(), b"{broken").unwrap();
        let corrupt = product
            .apply_selection_preset("Example", token, "corrupt")
            .unwrap();
        assert_eq!(corrupt["rejection_code"], "PRESET_ENTRY_CORRUPT");
        let first = product
            .select_slot_option("Example", token, "missing", "x", "request-1")
            .unwrap();
        assert_eq!(first["mutation_outcome"]["outcome_code"], "UNKNOWN_SLOT");
        let replay = product
            .select_slot_option("Example", token, "missing", "x", "request-1")
            .unwrap();
        assert_eq!(replay["mutation_outcome"]["outcome_replayed"], true);
        let stored = WorkSlotConfigurationStore::new(authority.join("slot_configs"))
            .unwrap()
            .load(&job.authority_id)
            .unwrap();
        assert!(stored.configurations.configurations.is_empty());
        assert_eq!(stored.processed_requests.len(), 1);
        assert_eq!(stored.processed_requests[0].request_id, "request-1");
        assert!(
            product
                .select_slot_option("Example", token, "missing", "other", "request-1")
                .is_err()
        );
        let root = root.canonicalize().unwrap();
        let cache = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .canonicalize()
            .unwrap();
        assert!(root.starts_with(cache));
        assert!(
            root.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("slot-product-")
        );
        fs::remove_dir_all(root).unwrap();
    }
}
