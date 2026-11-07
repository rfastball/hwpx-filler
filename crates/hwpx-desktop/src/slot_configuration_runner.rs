//! Durable first-seen select command under the shared Work fence.

use crate::candidate_store::FileCandidateObjectStore;
use crate::per_work_fence::PerWorkFence;
use crate::qualification_store::FileQualificationObjectStore;
use crate::work_configuration_store::WorkSlotConfigurationStore;
use crate::work_template_store::AtomicWorkTemplateStateStore;
use hwpx_filler::execution_structure::decode_execution_structure;
use hwpx_filler::preset::SelectionPreset;
use hwpx_filler::preset_fit::{BrokenSelection, decide_apply_preset};
use hwpx_filler::qualification_evidence::PASS;
use hwpx_filler::selection_compatibility::ChainApplicationFacts;
use hwpx_filler::slot_command::{
    CHANGED, CLEAR, ConfigurationCommandContext, FINGERPRINT_SCHEMA_VERSION, NO_CHANGE, SELECT,
    STALE_CONFIGURATION, STALE_TEMPLATE_APPLICATION, command_fingerprint, decide_clear,
    decide_select,
};
use hwpx_filler::slot_configuration_context::{
    ContextErrorKind, ContextPorts, SlotConfigurationContext, resolve_slot_configuration_context,
};
use hwpx_filler::slot_reconciliation::{ReconciliationApplication, plan_successor_reconciliation};
use hwpx_filler::slot_selection::{
    SelectionSemanticBindingKey, default_selection_semantic_registry, resolve_selection_policy,
};
use hwpx_filler::stored_work_configuration::{
    IdempotencyRecord, StoredWorkConfiguration, TerminalOutcome, empty_stored, find_request,
};
use hwpx_filler::work_slot_configuration::{
    WorkSlotConfigurationDraft, create_empty, create_reconciled,
};
use hwpx_filler::work_template_state::WorkTemplateStateAggregate;
use std::collections::HashMap;
use std::path::Path;

#[derive(Clone, Debug)]
pub struct CommandOutcome {
    pub outcome_code: String,
    pub changed: bool,
    pub application_id: String,
    pub source_version: Option<u64>,
    pub resulting_version: Option<u64>,
    pub replayed: bool,
}
pub struct ApplyOutcome {
    pub outcome: CommandOutcome,
    pub applied_slot_ids: Vec<String>,
    pub broken: Vec<BrokenSelection>,
}
#[derive(Debug)]
pub struct ApplyError {
    pub context_kind: Option<ContextErrorKind>,
    pub detail: String,
}
impl From<String> for ApplyError {
    fn from(detail: String) -> Self {
        Self {
            context_kind: None,
            detail,
        }
    }
}
impl From<&str> for ApplyError {
    fn from(detail: &str) -> Self {
        Self::from(detail.to_owned())
    }
}
impl CommandOutcome {
    fn from_record(record: &IdempotencyRecord, replayed: bool) -> Self {
        let terminal = &record.terminal_outcome;
        Self {
            outcome_code: terminal.outcome_code.clone(),
            changed: terminal.changed,
            application_id: terminal.application_id.clone(),
            source_version: terminal.source_configuration_version,
            resulting_version: terminal.resulting_configuration_version,
            replayed,
        }
    }
}

struct Ports {
    works: AtomicWorkTemplateStateStore,
    qualifications: FileQualificationObjectStore,
    candidates: FileCandidateObjectStore,
    configs: WorkSlotConfigurationStore,
}
impl Ports {
    fn new(root: &Path) -> Result<Self, String> {
        Ok(Self {
            works: AtomicWorkTemplateStateStore::new(root.join("works"))
                .map_err(|e| e.to_string())?,
            qualifications: FileQualificationObjectStore::new(root.join("qualification")),
            candidates: FileCandidateObjectStore::new(root.join("candidates")),
            configs: WorkSlotConfigurationStore::new(root.join("slot_configs"))
                .map_err(|e| e.to_string())?,
        })
    }
    fn context(
        &self,
        claim: &ConfigurationCommandContext,
    ) -> Result<SlotConfigurationContext, hwpx_filler::slot_configuration_context::ContextError>
    {
        resolve_slot_configuration_context(
            ContextPorts {
                work_state: &self.works,
                qualification: &self.qualifications,
                candidate: &self.candidates,
            },
            &claim.workspace_instance_id,
            &claim.expected_work_authority_id,
            Some(&claim.token_template_application_id),
            None,
        )
    }
    fn existing(
        &self,
        claim: &ConfigurationCommandContext,
    ) -> Result<Option<StoredWorkConfiguration>, String> {
        if !self
            .configs
            .exists(&claim.expected_work_authority_id)
            .map_err(|e| e.to_string())?
        {
            return Ok(None);
        }
        let stored = self
            .configs
            .load(&claim.expected_work_authority_id)
            .map_err(|e| e.to_string())?;
        if stored.workspace_instance_id != claim.workspace_instance_id {
            return Err("저장 workspace 가 token workspace 와 다르다".into());
        }
        Ok(Some(stored))
    }
    fn chain_facts(
        &self,
        aggregate: &WorkTemplateStateAggregate,
    ) -> HashMap<String, ChainApplicationFacts> {
        aggregate
            .applications
            .iter()
            .map(|application| {
                let unknown = || ChainApplicationFacts {
                    execution_structure: None,
                    selection_contract_id: None,
                    selection_policy: None,
                    applied_content_digest: None,
                };
                let facts = (|| {
                    let evidence = self
                        .qualifications
                        .get_evidence(&application.pass_evidence_id)
                        .ok()?;
                    if evidence.result != PASS {
                        return None;
                    }
                    let projection = evidence.structure_projection.as_ref()?;
                    let structure = decode_execution_structure(&projection.payload).ok()?;
                    let registry = default_selection_semantic_registry();
                    let contract = registry
                        .resolve(&SelectionSemanticBindingKey {
                            qualification_profile_id: evidence.qualification_profile_id.clone(),
                            structure_projection_schema_version: projection
                                .projection_schema_version
                                .clone(),
                        })
                        .ok()?;
                    let policy = resolve_selection_policy(contract, None).ok()?;
                    let digest = self
                        .candidates
                        .get_revision(&evidence.revision_id)
                        .ok()?
                        .exact_content_digest;
                    Some(ChainApplicationFacts {
                        execution_structure: Some(structure),
                        selection_contract_id: Some(contract.contract_id.clone()),
                        selection_policy: Some(policy),
                        applied_content_digest: Some(digest),
                    })
                })()
                .unwrap_or_else(unknown);
                (application.application_id.clone(), facts)
            })
            .collect()
    }
    fn plan_config(
        &self,
        context: &SlotConfigurationContext,
        stored: Option<&StoredWorkConfiguration>,
        now: &str,
    ) -> Result<Option<WorkSlotConfigurationDraft>, String> {
        let aggregate = self
            .works
            .load(&context.work_id)
            .map_err(|e| e.to_string())?;
        let applications = aggregate
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
        let configurations = stored.map_or_else(HashMap::new, |stored| {
            stored
                .configurations
                .configurations
                .iter()
                .map(|item| (item.base_template_application_id.clone(), item.clone()))
                .collect()
        });
        let plan = plan_successor_reconciliation(
            &context.template_application_id,
            &context.template_structure,
            &context.selection_semantic_contract,
            &applications,
            &configurations,
            &self.chain_facts(&aggregate),
        )
        .map_err(|e| e.to_string())?;
        if !plan.should_create_configuration {
            return Ok(None);
        }
        match plan.source_application_id.as_deref() {
            Some(source) => Ok(Some(
                create_reconciled(
                    &context.work_id,
                    &context.template_application_id,
                    plan.initial_selections,
                    source,
                    plan.source_configuration_version
                        .ok_or("reconciliation source version 부재")?,
                    plan.source_declared_selection_digest
                        .as_deref()
                        .ok_or("reconciliation source digest 부재")?,
                    now,
                )
                .map_err(|e| e.to_string())?,
            )),
            None => Ok(Some(
                create_empty(&context.work_id, &context.template_application_id, now)
                    .map_err(|e| e.to_string())?,
            )),
        }
    }
    fn commit(
        &self,
        claim: &ConfigurationCommandContext,
        stored: Option<&StoredWorkConfiguration>,
        config: Option<WorkSlotConfigurationDraft>,
        record: Option<IdempotencyRecord>,
    ) -> Result<(), String> {
        let mut next = match stored {
            Some(value) => value.clone(),
            None => empty_stored(
                &claim.workspace_instance_id,
                &claim.expected_work_authority_id,
            )
            .map_err(|e| e.to_string())?,
        };
        if let Some(config) = config {
            next.configurations.configurations.retain(|item| {
                item.base_template_application_id != config.base_template_application_id
            });
            next.configurations.configurations.push(config);
        }
        if let Some(record) = record {
            next.processed_requests.push(record);
        }
        next.validate().map_err(|e| e.to_string())?;
        match stored {
            Some(previous) => {
                next.aggregate_version = previous
                    .aggregate_version
                    .checked_add(1)
                    .ok_or("aggregate version overflow")?;
                self.configs
                    .update(
                        &claim.expected_work_authority_id,
                        previous.aggregate_version,
                        |_| Ok(next.clone()),
                    )
                    .map_err(|e| e.to_string())?;
            }
            None => self.configs.create(&next).map_err(|e| e.to_string())?,
        }
        Ok(())
    }

    fn planned_configuration(
        &self,
        context: &SlotConfigurationContext,
        stored: Option<&StoredWorkConfiguration>,
        current: Option<&WorkSlotConfigurationDraft>,
        now: &str,
    ) -> Result<
        (
            Option<WorkSlotConfigurationDraft>,
            WorkSlotConfigurationDraft,
        ),
        String,
    > {
        let planned = match current {
            Some(current) => Some(current.clone()),
            None => self.plan_config(context, stored, now)?,
        };
        let transient = match &planned {
            Some(config) => config.clone(),
            None => create_empty(&context.work_id, &context.template_application_id, now)
                .map_err(|e| e.to_string())?,
        };
        Ok((planned, transient))
    }
}

fn configuration_matches_claim(
    claim: &ConfigurationCommandContext,
    current: Option<&WorkSlotConfigurationDraft>,
) -> bool {
    if claim.token_configuration_presence {
        current.is_some_and(|item| {
            Some(item.version) == claim.token_configuration_version.map(u64::from)
        })
    } else {
        current.is_none()
    }
}

fn replay_request(
    stored: Option<&StoredWorkConfiguration>,
    request_id: &str,
    fingerprint: &str,
) -> Result<Option<CommandOutcome>, String> {
    let Some(existing) = stored.and_then(|stored| find_request(stored, request_id)) else {
        return Ok(None);
    };
    if existing.command_fingerprint != fingerprint
        || existing.fingerprint_schema_version != FINGERPRINT_SCHEMA_VERSION
    {
        return Err(format!(
            "request {request_id} 가 다른 fingerprint 로 재사용됨"
        ));
    }
    Ok(Some(CommandOutcome::from_record(existing, true)))
}

fn decide_command(
    context: &SlotConfigurationContext,
    config: &WorkSlotConfigurationDraft,
    kind: &str,
    slot_id: &str,
    option_id: Option<&str>,
    now: &str,
) -> Result<hwpx_filler::slot_command::Decision, String> {
    match kind {
        SELECT => decide_select(
            context,
            config,
            slot_id,
            option_id.ok_or("SELECT option 부재")?,
            now,
        ),
        CLEAR => decide_clear(context, config, slot_id, now),
        _ => Err("미지원 slot command".into()),
    }
}

fn record(
    claim: &ConfigurationCommandContext,
    request_id: &str,
    fingerprint: &str,
    terminal_outcome: TerminalOutcome,
    now: &str,
) -> IdempotencyRecord {
    IdempotencyRecord {
        request_id: request_id.into(),
        fingerprint_schema_version: FINGERPRINT_SCHEMA_VERSION.into(),
        command_fingerprint: fingerprint.into(),
        terminal_outcome,
        request_actor_binding_digest: claim.actor_binding_digest.clone(),
        recorded_at: now.into(),
    }
}

fn terminal(
    claim: &ConfigurationCommandContext,
    code: &str,
    changed: bool,
    source: Option<u64>,
    resulting: Option<u64>,
) -> TerminalOutcome {
    TerminalOutcome {
        application_id: claim.token_template_application_id.clone(),
        outcome_code: code.into(),
        changed,
        source_configuration_version: source,
        resulting_configuration_version: resulting,
    }
}

pub fn run_command(
    root: &Path,
    claim: &ConfigurationCommandContext,
    request_id: &str,
    kind: &str,
    slot_id: &str,
    option_id: Option<&str>,
    now: &str,
) -> Result<CommandOutcome, String> {
    if claim.expected_work_authority_id != claim.token_work_authority_id {
        return Err("route Work 와 token Work 가 다르다".into());
    }
    PerWorkFence::with(
        &claim.workspace_instance_id,
        &claim.expected_work_authority_id,
        || {
            let ports = Ports::new(root)?;
            let fingerprint = command_fingerprint(kind, claim, slot_id, option_id)?;
            let stored = ports.existing(claim)?;
            if let Some(outcome) = replay_request(stored.as_ref(), request_id, &fingerprint)? {
                return Ok(outcome);
            }
            let context = match ports.context(claim) {
                Ok(context) => Some(context),
                Err(error) if error.kind == ContextErrorKind::StaleTemplateApplication => None,
                Err(error) => return Err(error.to_string()),
            };
            let outcome = if let Some(context) = context {
                if context.selection_semantic_contract_id != claim.token_selection_contract_id {
                    return Err("token contract claim 이 current 와 다르다".into());
                }
                let current = stored.as_ref().and_then(|stored| {
                    stored.configurations.configurations.iter().find(|item| {
                        item.base_template_application_id == context.template_application_id
                    })
                });
                if !configuration_matches_claim(claim, current) {
                    let version = current.map(|item| item.version);
                    record(
                        claim,
                        request_id,
                        &fingerprint,
                        terminal(claim, STALE_CONFIGURATION, false, version, version),
                        now,
                    )
                } else {
                    let (planned, transient) =
                        ports.planned_configuration(&context, stored.as_ref(), current, now)?;
                    let decision =
                        decide_command(&context, &transient, kind, slot_id, option_id, now)?;
                    let committed = decision
                        .new_config
                        .or_else(|| if current.is_none() { planned } else { None });
                    let terminal = record(
                        claim,
                        request_id,
                        &fingerprint,
                        terminal(
                            claim,
                            decision.outcome_code,
                            decision.changed,
                            Some(decision.source_version),
                            Some(decision.resulting_version),
                        ),
                        now,
                    );
                    ports.commit(claim, stored.as_ref(), committed, Some(terminal.clone()))?;
                    return Ok(CommandOutcome::from_record(&terminal, false));
                }
            } else {
                let version = claim.token_configuration_version.map(u64::from);
                record(
                    claim,
                    request_id,
                    &fingerprint,
                    terminal(claim, STALE_TEMPLATE_APPLICATION, false, version, version),
                    now,
                )
            };
            ports.commit(claim, stored.as_ref(), None, Some(outcome.clone()))?;
            Ok(CommandOutcome::from_record(&outcome, false))
        },
    )
    .map_err(|e| e.to_string())?
}

/// Explicit open/refresh materializes a successor only when the reconciliation plan permits it.
pub fn run_ensure(
    root: &Path,
    workspace: &str,
    work_id: &str,
    now: &str,
) -> Result<CommandOutcome, String> {
    PerWorkFence::with(workspace, work_id, || {
        let ports = Ports::new(root)?;
        let context = resolve_slot_configuration_context(
            ContextPorts {
                work_state: &ports.works,
                qualification: &ports.qualifications,
                candidate: &ports.candidates,
            },
            workspace,
            work_id,
            None,
            None,
        )
        .map_err(|error| error.to_string())?;
        let claim = ConfigurationCommandContext {
            workspace_instance_id: workspace.into(),
            expected_work_authority_id: work_id.into(),
            token_work_authority_id: work_id.into(),
            token_template_application_id: context.template_application_id.clone(),
            token_selection_contract_id: context.selection_semantic_contract_id.clone(),
            token_configuration_presence: false,
            token_configuration_version: None,
            actor_binding_digest: String::new(),
        };
        let stored = ports.existing(&claim)?;
        if let Some(pre) =
            stored.as_ref().and_then(|stored| {
                stored.configurations.configurations.iter().find(|item| {
                    item.base_template_application_id == context.template_application_id
                })
            })
        {
            return Ok(CommandOutcome {
                outcome_code: NO_CHANGE.into(),
                changed: false,
                application_id: context.template_application_id,
                source_version: Some(pre.version),
                resulting_version: Some(pre.version),
                replayed: false,
            });
        }
        let planned = ports.plan_config(&context, stored.as_ref(), now)?;
        if let Some(config) = planned {
            let version = config.version;
            ports.commit(&claim, stored.as_ref(), Some(config), None)?;
            return Ok(CommandOutcome {
                outcome_code: CHANGED.into(),
                changed: true,
                application_id: context.template_application_id,
                source_version: None,
                resulting_version: Some(version),
                replayed: false,
            });
        }
        Ok(CommandOutcome {
            outcome_code: NO_CHANGE.into(),
            changed: false,
            application_id: context.template_application_id,
            source_version: None,
            resulting_version: None,
            replayed: false,
        })
    })
    .map_err(|error| error.to_string())?
}

pub fn run_apply_preset(
    root: &Path,
    claim: &ConfigurationCommandContext,
    preset: &SelectionPreset,
    now: &str,
) -> Result<ApplyOutcome, ApplyError> {
    if claim.expected_work_authority_id != claim.token_work_authority_id {
        return Err("route Work 와 token Work 가 다르다".into());
    }
    PerWorkFence::with(
        &claim.workspace_instance_id,
        &claim.expected_work_authority_id,
        || {
            let ports = Ports::new(root)?;
            let stored = ports.existing(claim)?;
            let context = match ports.context(claim) {
                Ok(context) => Some(context),
                Err(error) if error.kind == ContextErrorKind::StaleTemplateApplication => None,
                Err(error) => {
                    return Err(ApplyError {
                        context_kind: Some(error.kind),
                        detail: error.to_string(),
                    });
                }
            };
            let Some(context) = context else {
                let version = claim.token_configuration_version.map(u64::from);
                return Ok(ApplyOutcome {
                    outcome: CommandOutcome {
                        outcome_code: STALE_TEMPLATE_APPLICATION.into(),
                        changed: false,
                        application_id: claim.token_template_application_id.clone(),
                        source_version: version,
                        resulting_version: version,
                        replayed: false,
                    },
                    applied_slot_ids: vec![],
                    broken: vec![],
                });
            };
            if context.selection_semantic_contract_id != claim.token_selection_contract_id {
                return Err("token contract claim 이 current 와 다르다".into());
            }
            let current = stored.as_ref().and_then(|stored| {
                stored.configurations.configurations.iter().find(|item| {
                    item.base_template_application_id == context.template_application_id
                })
            });
            if !configuration_matches_claim(claim, current) {
                let version = current.map(|item| item.version);
                return Ok(ApplyOutcome {
                    outcome: CommandOutcome {
                        outcome_code: STALE_CONFIGURATION.into(),
                        changed: false,
                        application_id: context.template_application_id,
                        source_version: version,
                        resulting_version: version,
                        replayed: false,
                    },
                    applied_slot_ids: vec![],
                    broken: vec![],
                });
            }
            let (planned, transient) =
                ports.planned_configuration(&context, stored.as_ref(), current, now)?;
            let decision = decide_apply_preset(&context, &transient, &preset.selection_set, now)?;
            let committed = decision
                .new_config
                .or_else(|| if current.is_none() { planned } else { None });
            if let Some(config) = committed {
                ports.commit(claim, stored.as_ref(), Some(config), None)?;
            }
            Ok(ApplyOutcome {
                outcome: CommandOutcome {
                    outcome_code: decision.outcome_code.into(),
                    changed: decision.changed,
                    application_id: context.template_application_id,
                    source_version: Some(decision.source_version),
                    resulting_version: Some(decision.resulting_version),
                    replayed: false,
                },
                applied_slot_ids: decision.applied_slot_ids,
                broken: decision.broken,
            })
        },
    )
    .map_err(|e| ApplyError::from(e.to_string()))?
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::managed_generation_service::tests::RunFixture;
    use crate::slot_token::actor_binding_digest;
    use crate::work_configuration_store::WorkspaceMetadataStore;
    use hwpx_filler::slot_command::{UNKNOWN_OPTION, UNKNOWN_SLOT};
    use hwpx_filler::work_template_state::PREPARED_CHANGE;
    use std::fs;

    fn claim(fixture: &RunFixture) -> ConfigurationCommandContext {
        let job = fixture.jobs.load("생성").unwrap();
        let ports = Ports::new(&fixture.authority).unwrap();
        let work = ports.works.load(&job.authority_id).unwrap();
        let app = work.work.current_template_application_id;
        let workspace = WorkspaceMetadataStore::new(&fixture.authority)
            .unwrap()
            .get_or_create("t0")
            .unwrap();
        let stored = ports
            .configs
            .exists(&job.authority_id)
            .unwrap()
            .then(|| ports.configs.load(&job.authority_id).unwrap());
        let config = stored.as_ref().and_then(|stored| {
            stored
                .configurations
                .configurations
                .iter()
                .find(|config| config.base_template_application_id == app)
        });
        ConfigurationCommandContext {
            workspace_instance_id: workspace.clone(),
            expected_work_authority_id: job.authority_id.clone(),
            token_work_authority_id: job.authority_id,
            token_template_application_id: app,
            token_selection_contract_id: "slot-selection/v1".into(),
            token_configuration_presence: config.is_some(),
            token_configuration_version: config.map(|value| value.version.try_into().unwrap()),
            actor_binding_digest: actor_binding_digest("local-user", &workspace).unwrap(),
        }
    }

    #[test]
    fn ensure_clear_and_concurrent_replay_commit_once_and_preserve_rejected_state() {
        let fixture = RunFixture::txt();
        let initial = claim(&fixture);
        let ports = Ports::new(&fixture.authority).unwrap();
        let path = fixture
            .authority
            .join("slot_configs")
            .join(format!("{}.json", initial.expected_work_authority_id));
        for axis in ["work", "contract"] {
            let mut wrong = initial.clone();
            if axis == "work" {
                wrong.token_work_authority_id = "other".into();
            } else {
                wrong.token_selection_contract_id = "other".into();
            }
            assert!(
                run_command(
                    &fixture.authority,
                    &wrong,
                    "rejected",
                    SELECT,
                    "s1",
                    Some("o1"),
                    "t1"
                )
                .is_err()
            );
            assert!(!path.exists());
        }
        let ensured = run_ensure(
            &fixture.authority,
            &initial.workspace_instance_id,
            &initial.expected_work_authority_id,
            "t1",
        )
        .unwrap();
        assert_eq!(
            (
                ensured.outcome_code.as_str(),
                ensured.source_version,
                ensured.resulting_version
            ),
            (CHANGED, None, Some(1))
        );
        let before = fs::read(&path).unwrap();
        let unchanged = run_ensure(
            &fixture.authority,
            &initial.workspace_instance_id,
            &initial.expected_work_authority_id,
            "t2",
        )
        .unwrap();
        assert_eq!(unchanged.outcome_code, NO_CHANGE);
        assert!(!unchanged.changed);
        assert_eq!(fs::read(&path).unwrap(), before);
        for (id, kind, slot, option, code, version) in [
            ("select", SELECT, "s1", Some("o1"), CHANGED, 2),
            ("same", SELECT, "s1", Some("o1"), NO_CHANGE, 2),
            ("option", SELECT, "s1", Some("missing"), UNKNOWN_OPTION, 2),
            ("slot", SELECT, "missing", Some("o1"), UNKNOWN_SLOT, 2),
            ("clear", CLEAR, "s1", None, CHANGED, 3),
            ("clear-again", CLEAR, "s1", None, NO_CHANGE, 3),
            ("clear-missing", CLEAR, "missing", None, UNKNOWN_SLOT, 3),
        ] {
            let claim = claim(&fixture);
            let outcome =
                run_command(&fixture.authority, &claim, id, kind, slot, option, "t2").unwrap();
            assert_eq!(outcome.outcome_code, code, "{id}");
            assert_eq!(outcome.changed, code == CHANGED);
            assert_eq!(outcome.resulting_version, Some(version));
            let stored = ports
                .configs
                .load(&initial.expected_work_authority_id)
                .unwrap();
            assert_eq!(
                find_request(&stored, id)
                    .unwrap()
                    .terminal_outcome
                    .outcome_code,
                code
            );
            assert_eq!(stored.configurations.configurations.len(), 1);
        }
        assert!(
            ports
                .configs
                .load(&initial.expected_work_authority_id)
                .unwrap()
                .configurations
                .configurations[0]
                .is_empty()
        );
        let current = claim(&fixture);
        let before = fs::read(&path).unwrap();
        let mut wrong_workspace = current.clone();
        wrong_workspace.workspace_instance_id = "other".into();
        assert!(
            run_command(
                &fixture.authority,
                &wrong_workspace,
                "rejected",
                SELECT,
                "s1",
                Some("o2"),
                "t3"
            )
            .is_err()
        );
        for (kind, option) in [("UNKNOWN", Some("o2")), (SELECT, None)] {
            assert!(
                run_command(
                    &fixture.authority,
                    &current,
                    "rejected",
                    kind,
                    "s1",
                    option,
                    "t3"
                )
                .is_err()
            );
            assert_eq!(fs::read(&path).unwrap(), before);
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(1 | 2)
                .open(&path)
                .unwrap();
            assert!(
                run_command(
                    &fixture.authority,
                    &current,
                    "failed-write",
                    SELECT,
                    "s1",
                    Some("o2"),
                    "t3"
                )
                .is_err()
            );
            assert_eq!(fs::read(&path).unwrap(), before);
            drop(held);
        }
        let barrier = std::sync::Barrier::new(2);
        let run = || {
            barrier.wait();
            run_command(
                &fixture.authority,
                &current,
                "concurrent",
                SELECT,
                "s1",
                Some("o2"),
                "t3",
            )
            .unwrap()
        };
        let (first, second) = std::thread::scope(|scope| {
            let first = scope.spawn(run);
            let second = scope.spawn(run);
            (first.join().unwrap(), second.join().unwrap())
        });
        assert_eq!(first.outcome_code, CHANGED);
        assert_eq!(second.outcome_code, CHANGED);
        assert_ne!(first.replayed, second.replayed);
        assert_eq!(
            (first.source_version, first.resulting_version),
            (Some(3), Some(4))
        );
        let stored = ports
            .configs
            .load(&initial.expected_work_authority_id)
            .unwrap();
        assert_eq!(
            stored
                .processed_requests
                .iter()
                .filter(|record| record.request_id == "concurrent")
                .count(),
            1
        );
        assert!(find_request(&stored, "failed-write").is_none());
        let before = fs::read(&path).unwrap();
        assert!(
            run_command(
                &fixture.authority,
                &current,
                "concurrent",
                CLEAR,
                "s1",
                None,
                "t4"
            )
            .is_err()
        );
        assert_eq!(fs::read(&path).unwrap(), before);
    }

    #[test]
    fn exact_compatible_successor_keeps_choices_and_history_while_old_requests_replay() {
        let fixture = RunFixture::txt();
        let initial = claim(&fixture);
        let first = run_command(
            &fixture.authority,
            &initial,
            "first",
            SELECT,
            "s1",
            Some("o1"),
            "t1",
        )
        .unwrap();
        let ports = Ports::new(&fixture.authority).unwrap();
        let prior = ports
            .configs
            .load(&initial.expected_work_authority_id)
            .unwrap()
            .configurations
            .configurations[0]
            .clone();
        ports
            .works
            .update(&initial.expected_work_authority_id, |current| {
                let mut next = current.clone();
                // Identical durable evidence isolates successor reconciliation from media inspection.
                let mut application = next.applications.last().unwrap().clone();
                application.previous_application_id = Some(application.application_id.clone());
                application.application_id = "compatible-successor".into();
                application.application_epoch += 1;
                application.origin = PREPARED_CHANGE.into();
                application.prepared_change_id = Some("compatible-change".into());
                next.work.current_template_application_id = application.application_id.clone();
                next.applications.push(application);
                next.aggregate_version += 1;
                Ok(next)
            })
            .unwrap();
        let current = claim(&fixture);
        let ensured = run_ensure(
            &fixture.authority,
            &current.workspace_instance_id,
            &current.expected_work_authority_id,
            "t2",
        )
        .unwrap();
        assert_eq!(ensured.outcome_code, CHANGED);
        let stored = ports
            .configs
            .load(&initial.expected_work_authority_id)
            .unwrap();
        assert_eq!(stored.configurations.configurations[0], prior);
        let inherited = stored.configurations.configurations.last().unwrap();
        assert_eq!(inherited.selections, prior.selections);
        assert_eq!(
            inherited.reconciled_from_application_id.as_deref(),
            Some(prior.base_template_application_id.as_str())
        );
        assert_eq!(inherited.reconciled_from_version, Some(prior.version));
        let current = claim(&fixture);
        assert_eq!(
            run_command(
                &fixture.authority,
                &current,
                "clear-successor",
                CLEAR,
                "s1",
                None,
                "t3"
            )
            .unwrap()
            .outcome_code,
            CHANGED
        );
        let path = fixture
            .authority
            .join("slot_configs")
            .join(format!("{}.json", initial.expected_work_authority_id));
        let before = fs::read(&path).unwrap();
        let replay = run_command(
            &fixture.authority,
            &initial,
            "first",
            SELECT,
            "s1",
            Some("o1"),
            "later",
        )
        .unwrap();
        assert!(replay.replayed);
        assert_eq!(
            (
                replay.outcome_code,
                replay.application_id,
                replay.resulting_version
            ),
            (
                first.outcome_code,
                first.application_id,
                first.resulting_version
            )
        );
        assert_eq!(fs::read(&path).unwrap(), before);
        let stored = ports
            .configs
            .load(&initial.expected_work_authority_id)
            .unwrap();
        assert_eq!(stored.configurations.configurations[0], prior);
        assert!(stored.configurations.configurations[1].is_empty());
    }

    #[test]
    fn preset_apply_materializes_planned_config_and_never_commits_broken_choices_or_request_records()
     {
        use hwpx_filler::slot_selection::{SlotSelection, SlotSelectionSet};
        let fixture = RunFixture::txt();
        let ports = Ports::new(&fixture.authority).unwrap();
        let initial = claim(&fixture);
        let mut proposal = SelectionPreset::new(
            "혼합",
            SlotSelectionSet::new(vec![SlotSelection::new("gone", vec!["x".into()]).unwrap()])
                .unwrap(),
            vec![],
            "t0",
        )
        .unwrap();
        let rejected = run_apply_preset(&fixture.authority, &initial, &proposal, "t1").unwrap();
        assert_eq!(rejected.outcome.outcome_code, NO_CHANGE);
        assert!(rejected.applied_slot_ids.is_empty());
        assert_eq!(rejected.broken[0].status, "SLOT_REMOVED");
        let stored = ports
            .configs
            .load(&initial.expected_work_authority_id)
            .unwrap();
        assert_eq!(stored.configurations.configurations.len(), 1);
        assert_eq!(stored.configurations.configurations[0].version, 1);
        assert!(stored.configurations.configurations[0].is_empty());
        assert!(stored.processed_requests.is_empty());
        proposal
            .selection_set
            .selections
            .push(SlotSelection::new("s1", vec!["o1".into()]).unwrap());
        let result =
            run_apply_preset(&fixture.authority, &claim(&fixture), &proposal, "t2").unwrap();
        assert_eq!(result.outcome.outcome_code, CHANGED);
        assert_eq!(result.applied_slot_ids, ["s1"]);
        assert_eq!(result.broken[0].slot_id, "gone");
        let stored = ports
            .configs
            .load(&initial.expected_work_authority_id)
            .unwrap();
        assert_eq!(
            stored.configurations.configurations[0]
                .selections
                .selections,
            vec![SlotSelection::new("s1", vec!["o1".into()]).unwrap()]
        );
        assert!(stored.processed_requests.is_empty());
        let path = fixture
            .authority
            .join("slot_configs")
            .join(format!("{}.json", initial.expected_work_authority_id));
        let before = fs::read(&path).unwrap();
        let result =
            run_apply_preset(&fixture.authority, &claim(&fixture), &proposal, "t3").unwrap();
        assert_eq!(result.outcome.outcome_code, NO_CHANGE);
        assert_eq!(fs::read(&path).unwrap(), before);
        let result = run_apply_preset(&fixture.authority, &initial, &proposal, "t4").unwrap();
        assert_eq!(result.outcome.outcome_code, STALE_CONFIGURATION);
        assert_eq!(fs::read(&path).unwrap(), before);
    }
}
