//! Pure slot command fingerprint and select-one/clear decisions.

use crate::slot_configuration_context::SlotConfigurationContext;
use crate::slot_selection::{
    EXACTLY_ONE, SlotSelection, SlotSelectionSet, resolve_selection_policy,
};
use crate::work_slot_configuration::{WorkSlotConfigurationDraft, apply_selections};
use sha2::{Digest, Sha256};
use std::fmt::Write;

pub const FINGERPRINT_SCHEMA_VERSION: &str = "slot-configuration-command-fingerprint/v1";
pub const SELECT: &str = "SELECT";
pub const CLEAR: &str = "CLEAR";
pub const CHANGED: &str = "CHANGED";
pub const NO_CHANGE: &str = "NO_CHANGE";
pub const STALE_TEMPLATE_APPLICATION: &str = "STALE_TEMPLATE_APPLICATION";
pub const STALE_CONFIGURATION: &str = "STALE_CONFIGURATION";
pub const UNKNOWN_SLOT: &str = "UNKNOWN_SLOT";
pub const UNKNOWN_OPTION: &str = "UNKNOWN_OPTION";
pub const NO_AVAILABLE_OPTIONS: &str = "NO_AVAILABLE_OPTIONS";
pub const UNSUPPORTED_SELECTION_POLICY: &str = "UNSUPPORTED_SELECTION_POLICY";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConfigurationCommandContext {
    pub workspace_instance_id: String,
    pub expected_work_authority_id: String,
    pub token_work_authority_id: String,
    pub token_template_application_id: String,
    pub token_selection_contract_id: String,
    pub token_configuration_presence: bool,
    pub token_configuration_version: Option<u32>,
    pub actor_binding_digest: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Decision {
    pub outcome_code: &'static str,
    pub changed: bool,
    pub new_config: Option<WorkSlotConfigurationDraft>,
    pub source_version: u64,
    pub resulting_version: u64,
}

fn text(out: &mut Vec<u8>, value: &str) -> Result<(), String> {
    let len = u32::try_from(value.len()).map_err(|_| "fingerprint text 가 u32 범위 초과")?;
    out.extend_from_slice(&len.to_be_bytes());
    out.extend_from_slice(value.as_bytes());
    Ok(())
}

pub fn command_fingerprint(
    kind: &str,
    context: &ConfigurationCommandContext,
    slot_id: &str,
    option_id: Option<&str>,
) -> Result<String, String> {
    let mut out = b"HFPCMD1\0".to_vec();
    for value in [
        FINGERPRINT_SCHEMA_VERSION,
        kind,
        &context.workspace_instance_id,
        &context.expected_work_authority_id,
        &context.token_work_authority_id,
        &context.token_template_application_id,
    ] {
        text(&mut out, value)?;
    }
    out.push(u8::from(context.token_configuration_presence));
    match context.token_configuration_version {
        Some(version) => {
            out.push(1);
            out.extend_from_slice(&version.to_be_bytes());
        }
        None => out.push(0),
    }
    text(&mut out, &context.token_selection_contract_id)?;
    text(&mut out, slot_id)?;
    match option_id {
        Some(option) => {
            out.push(1);
            text(&mut out, option)?;
        }
        None => out.push(0),
    }
    text(&mut out, &context.actor_binding_digest)?;
    let mut digest = String::from("sha256:");
    for byte in Sha256::digest(&out) {
        write!(&mut digest, "{byte:02x}").expect("String write");
    }
    Ok(digest)
}

fn with_slot(
    selections: &SlotSelectionSet,
    slot_id: &str,
    option_id: Option<&str>,
) -> Result<SlotSelectionSet, String> {
    let mut entries: Vec<_> = selections
        .selections
        .iter()
        .filter(|entry| entry.slot_id != slot_id)
        .cloned()
        .collect();
    if let Some(option_id) = option_id {
        entries
            .push(SlotSelection::new(slot_id, vec![option_id.into()]).map_err(|e| e.to_string())?);
    }
    SlotSelectionSet::new(entries).map_err(|e| e.to_string())
}

fn unchanged(code: &'static str, version: u64) -> Decision {
    Decision {
        outcome_code: code,
        changed: false,
        new_config: None,
        source_version: version,
        resulting_version: version,
    }
}

pub fn decide_select(
    context: &SlotConfigurationContext,
    config: &WorkSlotConfigurationDraft,
    slot_id: &str,
    option_id: &str,
    now: &str,
) -> Result<Decision, String> {
    let version = config.version;
    let Some(slot) = context
        .template_structure
        .slots
        .iter()
        .find(|slot| slot.id == slot_id)
    else {
        return Ok(unchanged(UNKNOWN_SLOT, version));
    };
    if resolve_selection_policy(&context.selection_semantic_contract, None)
        .map_err(|error| error.to_string())?
        != EXACTLY_ONE
    {
        return Ok(unchanged(UNSUPPORTED_SELECTION_POLICY, version));
    }
    if slot.options.is_empty() {
        return Ok(unchanged(NO_AVAILABLE_OPTIONS, version));
    }
    if !slot.options.iter().any(|option| option.id == option_id) {
        return Ok(unchanged(UNKNOWN_OPTION, version));
    }
    let updated = apply_selections(
        config,
        with_slot(&config.selections, slot_id, Some(option_id))?,
        now,
    )
    .map_err(|error| error.to_string())?;
    let changed = updated.version != version;
    Ok(Decision {
        outcome_code: if changed { CHANGED } else { NO_CHANGE },
        changed,
        new_config: changed.then_some(updated.clone()),
        source_version: version,
        resulting_version: updated.version,
    })
}

pub fn decide_clear(
    context: &SlotConfigurationContext,
    config: &WorkSlotConfigurationDraft,
    slot_id: &str,
    now: &str,
) -> Result<Decision, String> {
    let version = config.version;
    let present = config
        .selections
        .selections
        .iter()
        .any(|entry| entry.slot_id == slot_id);
    if !present
        && !context
            .template_structure
            .slots
            .iter()
            .any(|slot| slot.id == slot_id)
    {
        return Ok(unchanged(UNKNOWN_SLOT, version));
    }
    if !present {
        return Ok(unchanged(NO_CHANGE, version));
    }
    let updated = apply_selections(config, with_slot(&config.selections, slot_id, None)?, now)
        .map_err(|error| error.to_string())?;
    let changed = updated.version != version;
    Ok(Decision {
        outcome_code: if changed { CHANGED } else { NO_CHANGE },
        changed,
        new_config: changed.then_some(updated.clone()),
        source_version: version,
        resulting_version: updated.version,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn semantic_fingerprint_matches_existing_command_oracle() {
        let context = ConfigurationCommandContext {
            workspace_instance_id: "ws".into(),
            expected_work_authority_id: "work".into(),
            token_work_authority_id: "work".into(),
            token_template_application_id: "app".into(),
            token_selection_contract_id: "slot-selection/v1".into(),
            token_configuration_presence: true,
            token_configuration_version: Some(7),
            actor_binding_digest: "sha256:actor".into(),
        };
        assert_eq!(
            command_fingerprint(SELECT, &context, "slot", Some("option")).unwrap(),
            "sha256:f338054ac374dd74b1957729e85632e3dfd1f616aef94eb806a8bed2ec6149ae"
        );
        let base = command_fingerprint(SELECT, &context, "slot", Some("option")).unwrap();
        assert_eq!(
            command_fingerprint(SELECT, &context.clone(), "slot", Some("option")).unwrap(),
            base
        );
        for axis in [
            "workspace",
            "work",
            "token-work",
            "application",
            "contract",
            "presence",
            "version",
            "actor",
        ] {
            let mut changed = context.clone();
            match axis {
                "workspace" => changed.workspace_instance_id = "other".into(),
                "work" => changed.expected_work_authority_id = "other".into(),
                "token-work" => changed.token_work_authority_id = "other".into(),
                "application" => changed.token_template_application_id = "other".into(),
                "contract" => changed.token_selection_contract_id = "other".into(),
                "presence" => changed.token_configuration_presence = false,
                "version" => changed.token_configuration_version = Some(99),
                "actor" => changed.actor_binding_digest = "other".into(),
                _ => unreachable!(),
            }
            assert_ne!(
                command_fingerprint(SELECT, &changed, "slot", Some("option")).unwrap(),
                base,
                "{axis}"
            );
        }
        let alternatives = [
            (CLEAR, "slot", None),
            (SELECT, "slot", Some("other")),
            (SELECT, "other", Some("option")),
            (SELECT, "slot", Some("")),
            (SELECT, "slot", None),
        ];
        let mut distinct = std::collections::HashSet::from([base]);
        for (kind, slot, option) in alternatives {
            assert!(distinct.insert(command_fingerprint(kind, &context, slot, option).unwrap()));
        }
    }

    #[test]
    fn select_and_clear_preserve_other_entries_and_report_exact_version_changes() {
        use crate::execution_structure::{TemplateOption, TemplateSlot, TemplateStructure};
        use crate::slot_selection::default_selection_semantic_registry;
        use crate::work_slot_configuration::create_empty;
        let contract = default_selection_semantic_registry()
            .get("slot-selection/v1")
            .unwrap()
            .clone();
        let mut context = SlotConfigurationContext {
            workspace_instance_id: "ws".into(),
            work_id: "work".into(),
            template_application_id: "app".into(),
            template_lineage_id: "lineage".into(),
            application_epoch: 1,
            pass_evidence_id: "evidence".into(),
            revision_id: "revision".into(),
            qualification_profile_id: "profile".into(),
            structure_projection_schema_version: "schema".into(),
            template_structure: TemplateStructure {
                root_fields: vec![],
                slots: ["s1", "s2"]
                    .into_iter()
                    .map(|id| TemplateSlot {
                        id: id.into(),
                        shared_fields: vec![],
                        label: None,
                        options: ["o1", "o2"]
                            .into_iter()
                            .map(|id| TemplateOption {
                                id: id.into(),
                                fields: vec![],
                                label: None,
                            })
                            .collect(),
                    })
                    .collect(),
            },
            template_structure_digest: "digest".into(),
            selection_semantic_contract_id: contract.contract_id.clone(),
            selection_semantic_contract: contract,
        };
        let empty = create_empty("work", "app", "t0").unwrap();
        for (slot, option, code) in [
            ("missing", "o1", UNKNOWN_SLOT),
            ("s1", "missing", UNKNOWN_OPTION),
        ] {
            assert_eq!(
                decide_select(&context, &empty, slot, option, "t1").unwrap(),
                unchanged(code, 1)
            );
        }
        assert_eq!(
            decide_clear(&context, &empty, "missing", "t1").unwrap(),
            unchanged(UNKNOWN_SLOT, 1)
        );
        assert_eq!(
            decide_clear(&context, &empty, "s1", "t1").unwrap(),
            unchanged(NO_CHANGE, 1)
        );
        let first = decide_select(&context, &empty, "s1", "o1", "t1").unwrap();
        assert_eq!(
            (
                first.outcome_code,
                first.changed,
                first.source_version,
                first.resulting_version
            ),
            (CHANGED, true, 1, 2)
        );
        let chosen = first.new_config.unwrap();
        assert_eq!(
            decide_select(&context, &chosen, "s1", "o1", "t2").unwrap(),
            unchanged(NO_CHANGE, 2)
        );
        assert_eq!(
            decide_clear(&context, &chosen, "s2", "t2").unwrap(),
            unchanged(NO_CHANGE, 2)
        );
        let both = decide_select(&context, &chosen, "s2", "o2", "t2")
            .unwrap()
            .new_config
            .unwrap();
        let cleared = decide_clear(&context, &both, "s1", "t3").unwrap();
        assert_eq!(
            (
                cleared.outcome_code,
                cleared.changed,
                cleared.source_version,
                cleared.resulting_version
            ),
            (CHANGED, true, 3, 4)
        );
        assert_eq!(
            cleared.new_config.unwrap().selections.selections,
            vec![SlotSelection::new("s2", vec!["o2".into()]).unwrap()]
        );
        let mut detached = chosen.clone();
        detached.selections.selections[0].slot_id = "gone".into();
        assert!(
            decide_clear(&context, &detached, "gone", "t3")
                .unwrap()
                .new_config
                .unwrap()
                .is_empty()
        );
        context.template_structure.slots[0].options.clear();
        assert_eq!(
            decide_select(&context, &empty, "s1", "o1", "t1").unwrap(),
            unchanged(NO_AVAILABLE_OPTIONS, 1)
        );
        context.selection_semantic_contract.default_selection_policy = "MANY".into();
        assert_eq!(
            decide_select(&context, &empty, "s1", "o1", "t1").unwrap(),
            unchanged(UNSUPPORTED_SELECTION_POLICY, 1)
        );
    }
}
