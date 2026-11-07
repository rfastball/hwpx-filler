//! Pure resolution of declared selections against an exact TemplateStructure.

use crate::execution_structure::TemplateStructure;
use crate::selection_compatibility::{
    AUTO_KEEP, ChainApplicationFacts, CompatibilityEvidence, SelectionCompatibilityFacts,
    classify_selection,
};
use crate::slot_selection::{
    CARDINALITY_VIOLATION, MISSING_REQUIRED_SELECTION, NO_AVAILABLE_OPTIONS, SATISFIED,
    SelectionSemanticContractManifest, SlotSelection, SlotSelectionSet, declared_selection_digest,
    evaluate_slot, resolve_selection_policy,
};
use crate::work_slot_configuration::{RECONCILED_FROM_PREDECESSOR, WorkSlotConfigurationDraft};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const RESOLVED: &str = "RESOLVED";
pub const SELECTED_OPTION_REMOVED: &str = "SELECTED_OPTION_REMOVED";
pub const UNSUPPORTED_SELECTION_POLICY: &str = "UNSUPPORTED_SELECTION_POLICY";
pub const SLOT_REMOVED: &str = "SLOT_REMOVED";
pub const NOT_APPLICABLE: &str = "NOT_APPLICABLE";
pub const COMPLETE: &str = "COMPLETE";
pub const BLOCKED: &str = "BLOCKED";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReconciliationError(pub String);
impl fmt::Display for ReconciliationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ReconciliationError {}
fn fail(detail: impl Into<String>) -> ReconciliationError {
    ReconciliationError(detail.into())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotDiagnostic {
    pub kind: String,
    pub option_id: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotResolution {
    pub slot_id: String,
    pub policy: Option<String>,
    pub declared_option_ids: Vec<String>,
    pub effective_option_ids: Vec<String>,
    pub status: String,
    pub available_option_ids: Vec<String>,
    pub diagnostics: Vec<SlotDiagnostic>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DetachedSelection {
    pub slot_id: String,
    pub option_ids: Vec<String>,
    pub kind: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotConfigurationResolution {
    pub applicable: bool,
    pub configuration_status: String,
    pub slots: Vec<SlotResolution>,
    pub effective_selections: SlotSelectionSet,
    pub detached_selections: Vec<DetachedSelection>,
    pub blocking_diagnostics: Vec<(String, String)>,
    pub blocking_kinds: Vec<String>,
    pub slot_selections_complete: bool,
}
fn resolve_one_slot(
    slot_id: &str,
    available: Vec<String>,
    declared: Vec<String>,
    contract: &SelectionSemanticContractManifest,
) -> SlotResolution {
    let available_set: HashSet<_> = available.iter().map(String::as_str).collect();
    let removed = declared
        .iter()
        .filter(|id| !available_set.contains(id.as_str()))
        .map(|id| SlotDiagnostic {
            kind: SELECTED_OPTION_REMOVED.into(),
            option_id: Some(id.clone()),
        })
        .collect();
    let policy = resolve_selection_policy(contract, None).ok();
    let card = policy
        .as_deref()
        .and_then(|policy| evaluate_slot(policy, available.len(), declared.len()).ok());
    let Some(card) = card else {
        return SlotResolution {
            slot_id: slot_id.into(),
            policy: None,
            declared_option_ids: declared,
            effective_option_ids: vec![],
            status: UNSUPPORTED_SELECTION_POLICY.into(),
            available_option_ids: available,
            diagnostics: removed,
        };
    };
    let status = match card {
        NO_AVAILABLE_OPTIONS => NO_AVAILABLE_OPTIONS,
        MISSING_REQUIRED_SELECTION => MISSING_REQUIRED_SELECTION,
        CARDINALITY_VIOLATION => CARDINALITY_VIOLATION,
        SATISFIED if available_set.contains(declared[0].as_str()) => RESOLVED,
        _ => SELECTED_OPTION_REMOVED,
    };
    let effective = if status == RESOLVED {
        vec![declared[0].clone()]
    } else {
        vec![]
    };
    SlotResolution {
        slot_id: slot_id.into(),
        policy,
        declared_option_ids: declared,
        effective_option_ids: effective,
        status: status.into(),
        available_option_ids: available,
        diagnostics: removed,
    }
}
/// Recalculate derived state from declared intent; removed slots retain detached intent.
pub fn resolve_slot_configuration(
    selections: &SlotSelectionSet,
    structure: &TemplateStructure,
    contract: &SelectionSemanticContractManifest,
) -> Result<SlotConfigurationResolution, ReconciliationError> {
    selections
        .validate()
        .map_err(|error| fail(error.to_string()))?;
    let declared: std::collections::HashMap<_, _> = selections
        .selections
        .iter()
        .map(|selection| {
            (
                selection.slot_id.as_str(),
                selection.selected_option_ids.clone(),
            )
        })
        .collect();
    let current: HashSet<_> = structure
        .slots
        .iter()
        .map(|slot| slot.id.as_str())
        .collect();
    let mut slots = Vec::with_capacity(structure.slots.len());
    for slot in &structure.slots {
        let available = slot
            .options
            .iter()
            .map(|option| option.id.clone())
            .collect();
        slots.push(resolve_one_slot(
            &slot.id,
            available,
            declared.get(slot.id.as_str()).cloned().unwrap_or_default(),
            contract,
        ));
    }
    let detached = selections
        .selections
        .iter()
        .filter(|selection| !current.contains(selection.slot_id.as_str()))
        .map(|selection| DetachedSelection {
            slot_id: selection.slot_id.clone(),
            option_ids: selection.selected_option_ids.clone(),
            kind: SLOT_REMOVED.into(),
        })
        .collect();
    let effective = SlotSelectionSet::new(
        slots
            .iter()
            .filter(|slot| slot.status == RESOLVED)
            .map(|slot| {
                SlotSelection::new(&slot.slot_id, slot.effective_option_ids.clone())
                    .map_err(|error| fail(error.to_string()))
            })
            .collect::<Result<Vec<_>, _>>()?,
    )
    .map_err(|error| fail(error.to_string()))?;
    let blocked = [
        MISSING_REQUIRED_SELECTION,
        SELECTED_OPTION_REMOVED,
        CARDINALITY_VIOLATION,
        NO_AVAILABLE_OPTIONS,
        UNSUPPORTED_SELECTION_POLICY,
    ];
    let blocking_diagnostics: Vec<_> = slots
        .iter()
        .filter(|slot| blocked.contains(&slot.status.as_str()))
        .map(|slot| (slot.slot_id.clone(), slot.status.clone()))
        .collect();
    let mut blocking_kinds = Vec::new();
    for (_, status) in &blocking_diagnostics {
        if !blocking_kinds.contains(status) {
            blocking_kinds.push(status.clone());
        }
    }
    let applicable = !structure.slots.is_empty();
    let slot_selections_complete = applicable && slots.iter().all(|slot| slot.status == RESOLVED);
    let configuration_status = if !applicable {
        NOT_APPLICABLE
    } else if slot_selections_complete {
        COMPLETE
    } else {
        BLOCKED
    };
    Ok(SlotConfigurationResolution {
        applicable,
        configuration_status: configuration_status.into(),
        slots,
        effective_selections: effective,
        detached_selections: detached,
        blocking_diagnostics,
        blocking_kinds,
        slot_selections_complete,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReconciliationApplication {
    pub application_id: String,
    pub previous_application_id: Option<String>,
    pub application_epoch: i64,
    pub work_id: String,
    pub template_lineage_id: String,
}
fn validate_provenance(
    config: &WorkSlotConfigurationDraft,
    configurations: &HashMap<String, WorkSlotConfigurationDraft>,
) -> Result<(), ReconciliationError> {
    config.validate().map_err(|error| fail(error.to_string()))?;
    if config.origin != RECONCILED_FROM_PREDECESSOR {
        return Ok(());
    }
    let source = config
        .reconciled_from_application_id
        .as_ref()
        .and_then(|id| configurations.get(id))
        .ok_or_else(|| fail("reconciled_from Configuration 이 aggregate 에 없다(유령 승계)"))?;
    if Some(source.version) != config.reconciled_from_version {
        return Err(fail("reconciled_from version 이 provenance 와 불일치"));
    }
    let digest =
        declared_selection_digest(&source.selections).map_err(|error| fail(error.to_string()))?;
    if config.reconciled_from_declared_selection_digest.as_deref() != Some(digest.as_str()) {
        return Err(fail("reconciled_from digest 가 provenance 와 불일치"));
    }
    Ok(())
}
/// Walk every previous link even after finding the nearest configuration.
pub fn find_nearest_predecessor_configuration<'a>(
    target_application_id: &str,
    applications: &HashMap<String, ReconciliationApplication>,
    configurations: &'a HashMap<String, WorkSlotConfigurationDraft>,
) -> Result<Option<&'a WorkSlotConfigurationDraft>, ReconciliationError> {
    let target = applications
        .get(target_application_id)
        .ok_or_else(|| fail(format!("target application {target_application_id} 부재")))?;
    let mut seen = HashSet::from([target.application_id.as_str()]);
    let mut current = target;
    let mut nearest = None;
    while let Some(previous_id) = current.previous_application_id.as_deref() {
        let previous = applications
            .get(previous_id)
            .ok_or_else(|| fail(format!("dangling previous_application_id: {previous_id}")))?;
        if !seen.insert(previous.application_id.as_str()) {
            return Err(fail(format!(
                "application chain cycle: {}",
                previous.application_id
            )));
        }
        if previous.work_id != target.work_id {
            return Err(fail("chain 이 다른 Work 를 가리킨다"));
        }
        if current.application_epoch.checked_sub(1) != Some(previous.application_epoch) {
            return Err(fail(
                "previous epoch 이 정확히 1 감소하지 않는다(skip·역행)",
            ));
        }
        if let Some(config) = configurations.get(previous_id) {
            validate_provenance(config, configurations)?;
            if nearest.is_none() {
                nearest = Some(config);
            }
        }
        current = previous;
    }
    Ok(nearest)
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReconciliationPlan {
    pub should_create_configuration: bool,
    pub initial_selections: SlotSelectionSet,
    pub source_application_id: Option<String>,
    pub source_configuration_version: Option<u64>,
    pub source_declared_selection_digest: Option<String>,
    pub resolution: SlotConfigurationResolution,
    pub compatibility_facts: Vec<SelectionCompatibilityFacts>,
}
fn ordered_chain(
    applications: &HashMap<String, ReconciliationApplication>,
    target: &str,
    source: &str,
) -> Vec<String> {
    let mut ids = vec![];
    let mut current = Some(target);
    while let Some(id) = current {
        ids.push(id.into());
        if id == source {
            break;
        }
        current = applications
            .get(id)
            .and_then(|app| app.previous_application_id.as_deref());
    }
    ids.reverse();
    ids
}
/// Successor plan retains only selections proven compatible across the exact chain.
pub fn plan_successor_reconciliation(
    target_application_id: &str,
    target_structure: &TemplateStructure,
    contract: &SelectionSemanticContractManifest,
    applications: &HashMap<String, ReconciliationApplication>,
    configurations: &HashMap<String, WorkSlotConfigurationDraft>,
    chain_facts: &HashMap<String, ChainApplicationFacts>,
) -> Result<ReconciliationPlan, ReconciliationError> {
    let target = applications
        .get(target_application_id)
        .ok_or_else(|| fail(format!("target application {target_application_id} 부재")))?;
    let source = find_nearest_predecessor_configuration(
        target_application_id,
        applications,
        configurations,
    )?;
    let mut compatibility_facts = vec![];
    let (
        initial_selections,
        source_application_id,
        source_configuration_version,
        source_declared_selection_digest,
    ) = if let Some(source) = source {
        let source_id = &source.base_template_application_id;
        let source_app = applications
            .get(source_id)
            .ok_or_else(|| fail(format!("source application {source_id} 부재")))?;
        let initial = if source_app.template_lineage_id == target.template_lineage_id {
            let chain_ids = ordered_chain(applications, target_application_id, source_id);
            let structures: Vec<_> = chain_ids
                .iter()
                .map(|id| {
                    chain_facts
                        .get(id)
                        .and_then(|facts| facts.execution_structure.as_ref())
                })
                .collect();
            let digests: Vec<_> = chain_ids
                .iter()
                .map(|id| {
                    chain_facts
                        .get(id)
                        .and_then(|facts| facts.applied_content_digest.as_deref())
                })
                .collect();
            let source_facts = chain_facts.get(source_id);
            let target_policy = resolve_selection_policy(contract, None)
                .map_err(|error| fail(error.to_string()))?;
            let mut kept = vec![];
            for selection in &source.selections.selections {
                let mut kept_options = vec![];
                for option_id in &selection.selected_option_ids {
                    let fact = classify_selection(
                        &selection.slot_id,
                        option_id,
                        CompatibilityEvidence {
                            chain_structures: &structures,
                            chain_content_digests: &digests,
                            source_contract_id: source_facts
                                .and_then(|facts| facts.selection_contract_id.as_deref()),
                            target_contract_id: &contract.contract_id,
                            source_policy: source_facts
                                .and_then(|facts| facts.selection_policy.as_deref()),
                            target_policy: &target_policy,
                        },
                    );
                    if fact.classification == AUTO_KEEP {
                        kept_options.push(option_id.clone());
                    }
                    compatibility_facts.push(fact);
                }
                if !kept_options.is_empty() {
                    kept.push(
                        SlotSelection::new(&selection.slot_id, kept_options)
                            .map_err(|error| fail(error.to_string()))?,
                    );
                }
            }
            SlotSelectionSet::new(kept).map_err(|error| fail(error.to_string()))?
        } else {
            SlotSelectionSet::default()
        };
        (
            initial,
            Some(source_id.clone()),
            Some(source.version),
            Some(
                declared_selection_digest(&source.selections)
                    .map_err(|error| fail(error.to_string()))?,
            ),
        )
    } else {
        (SlotSelectionSet::default(), None, None, None)
    };
    let resolution = resolve_slot_configuration(&initial_selections, target_structure, contract)?;
    let should_create_configuration =
        !target_structure.slots.is_empty() || !resolution.detached_selections.is_empty();
    Ok(ReconciliationPlan {
        should_create_configuration,
        initial_selections,
        source_application_id,
        source_configuration_version,
        source_declared_selection_digest,
        resolution,
        compatibility_facts,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReconciliationSourceDelta {
    pub source_application_id: String,
    pub source_configuration_version: u64,
    pub target_application_id: String,
    pub added_slot_ids: Vec<String>,
    pub removed_slot_ids: Vec<String>,
    pub added_option_refs: Vec<(String, String)>,
    pub removed_option_refs: Vec<(String, String)>,
    pub removed_selected_option_refs: Vec<(String, String)>,
    pub preserved_selection_refs: Vec<(String, String)>,
    pub slot_order_changed: bool,
    pub option_order_changes: Vec<String>,
}
fn slot_option_map(structure: &TemplateStructure) -> HashMap<String, Vec<String>> {
    structure
        .slots
        .iter()
        .map(|slot| {
            (
                slot.id.clone(),
                slot.options
                    .iter()
                    .map(|option| option.id.clone())
                    .collect(),
            )
        })
        .collect()
}
/// Deterministic difference from the nearest configured predecessor, not merely the previous hop.
pub fn derive_reconciliation_source_delta(
    source_application_id: &str,
    source_configuration_version: u64,
    source_selections: &SlotSelectionSet,
    source_structure: &TemplateStructure,
    target_application_id: &str,
    target_structure: &TemplateStructure,
) -> ReconciliationSourceDelta {
    let source = slot_option_map(source_structure);
    let target = slot_option_map(target_structure);
    let source_order: Vec<_> = source_structure
        .slots
        .iter()
        .map(|slot| slot.id.as_str())
        .collect();
    let target_order: Vec<_> = target_structure
        .slots
        .iter()
        .map(|slot| slot.id.as_str())
        .collect();
    let mut added_slot_ids: Vec<_> = target
        .keys()
        .filter(|id| !source.contains_key(*id))
        .cloned()
        .collect();
    added_slot_ids.sort();
    let mut removed_slot_ids: Vec<_> = source
        .keys()
        .filter(|id| !target.contains_key(*id))
        .cloned()
        .collect();
    removed_slot_ids.sort();
    let mut added_option_refs = vec![];
    let mut removed_option_refs = vec![];
    let mut option_order_changes = vec![];
    for id in &target_order {
        let (Some(source_options), Some(target_options)) = (source.get(*id), target.get(*id))
        else {
            continue;
        };
        for option in target_options {
            if !source_options.contains(option) {
                added_option_refs.push(((*id).into(), option.clone()));
            }
        }
        for option in source_options {
            if !target_options.contains(option) {
                removed_option_refs.push(((*id).into(), option.clone()));
            }
        }
        let source_set: HashSet<_> = source_options.iter().collect();
        let target_set: HashSet<_> = target_options.iter().collect();
        if source_set == target_set && source_options != target_options {
            option_order_changes.push((*id).into());
        }
    }
    added_option_refs.sort();
    removed_option_refs.sort();
    let selected: HashSet<_> = source_selections
        .selections
        .iter()
        .flat_map(|selection| {
            selection
                .selected_option_ids
                .iter()
                .map(|option| (selection.slot_id.clone(), option.clone()))
        })
        .collect();
    let mut removed_selected_option_refs: Vec<_> = selected
        .iter()
        .filter(|(slot, option)| {
            !target
                .get(slot)
                .is_some_and(|options| options.contains(option))
        })
        .cloned()
        .collect();
    let mut preserved_selection_refs: Vec<_> = selected
        .iter()
        .filter(|(slot, option)| {
            target
                .get(slot)
                .is_some_and(|options| options.contains(option))
        })
        .cloned()
        .collect();
    removed_selected_option_refs.sort();
    preserved_selection_refs.sort();
    let source_common: Vec<_> = source_order
        .iter()
        .filter(|id| target.contains_key(**id))
        .collect();
    let target_common: Vec<_> = target_order
        .iter()
        .filter(|id| source.contains_key(**id))
        .collect();
    ReconciliationSourceDelta {
        source_application_id: source_application_id.into(),
        source_configuration_version,
        target_application_id: target_application_id.into(),
        added_slot_ids,
        removed_slot_ids,
        added_option_refs,
        removed_option_refs,
        removed_selected_option_refs,
        preserved_selection_refs,
        slot_order_changed: source_common != target_common,
        option_order_changes,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{TemplateOption, TemplateSlot};
    use crate::slot_selection::{
        CANONICAL_ENCODING_VERSION, EXACTLY_ONE, SELECTION_SET_SCHEMA_VERSION,
    };
    fn contract() -> SelectionSemanticContractManifest {
        SelectionSemanticContractManifest {
            contract_id: "selection/v1".into(),
            selection_set_schema_version: SELECTION_SET_SCHEMA_VERSION.into(),
            canonical_encoding_version: CANONICAL_ENCODING_VERSION.into(),
            default_selection_policy: EXACTLY_ONE.into(),
            supported_selection_policies: vec![EXACTLY_ONE.into()],
            created_semantics_version: "v1".into(),
        }
    }
    #[test]
    fn removed_option_blocks_and_removed_slot_retains_intent() {
        let contract = contract();
        let structure = TemplateStructure {
            root_fields: vec![],
            slots: vec![TemplateSlot {
                id: "s".into(),
                shared_fields: vec![],
                options: vec![TemplateOption {
                    id: "new".into(),
                    fields: vec![],
                    label: None,
                }],
                label: None,
            }],
        };
        let selections = SlotSelectionSet::new(vec![
            SlotSelection::new("s", vec!["old".into()]).unwrap(),
            SlotSelection::new("gone", vec!["keep".into()]).unwrap(),
        ])
        .unwrap();
        let resolution = resolve_slot_configuration(&selections, &structure, &contract).unwrap();
        assert_eq!(resolution.configuration_status, BLOCKED);
        assert_eq!(resolution.slots[0].status, SELECTED_OPTION_REMOVED);
        assert_eq!(
            resolution.slots[0].diagnostics[0].option_id.as_deref(),
            Some("old")
        );
        assert_eq!(resolution.detached_selections[0].slot_id, "gone");
        assert!(resolution.effective_selections.selections.is_empty());
    }
    #[test]
    fn nearest_empty_tombstone_wins_and_chain_tail_corruption_refuses() {
        use crate::work_slot_configuration::{apply_selections, create_empty};
        let applications: HashMap<_, _> = [
            ("a1", None, 1),
            ("a2", Some("a1"), 2),
            ("a3", Some("a2"), 3),
        ]
        .into_iter()
        .map(|(id, previous, epoch)| {
            (
                id.into(),
                ReconciliationApplication {
                    application_id: id.into(),
                    previous_application_id: previous.map(str::to_owned),
                    application_epoch: epoch,
                    work_id: "w".into(),
                    template_lineage_id: "line".into(),
                },
            )
        })
        .collect();
        let old = apply_selections(
            &create_empty("w", "a1", "t1").unwrap(),
            SlotSelectionSet::new(vec![SlotSelection::new("s", vec!["o".into()]).unwrap()])
                .unwrap(),
            "t2",
        )
        .unwrap();
        let configs: HashMap<_, _> = [
            ("a1".into(), old),
            ("a2".into(), create_empty("w", "a2", "t3").unwrap()),
        ]
        .into();
        let structure = TemplateStructure {
            root_fields: vec![],
            slots: vec![TemplateSlot {
                id: "s".into(),
                shared_fields: vec![],
                options: vec![TemplateOption {
                    id: "o".into(),
                    fields: vec![],
                    label: None,
                }],
                label: None,
            }],
        };
        let plan = plan_successor_reconciliation(
            "a3",
            &structure,
            &contract(),
            &applications,
            &configs,
            &HashMap::new(),
        )
        .unwrap();
        assert_eq!(plan.source_application_id.as_deref(), Some("a2"));
        assert!(plan.initial_selections.selections.is_empty());
        assert_eq!(plan.resolution.slots[0].status, MISSING_REQUIRED_SELECTION);
        let mut corrupt = applications;
        corrupt.get_mut("a1").unwrap().previous_application_id = Some("a3".into());
        assert!(
            find_nearest_predecessor_configuration("a3", &corrupt, &configs)
                .unwrap_err()
                .0
                .contains("cycle")
        );
    }

    #[test]
    fn declared_intent_resolves_only_available_options_and_reappears() {
        let one_slot = |options: &[&str]| TemplateStructure {
            root_fields: vec![],
            slots: vec![TemplateSlot {
                id: "s".into(),
                shared_fields: vec![],
                options: options
                    .iter()
                    .map(|id| TemplateOption {
                        id: (*id).into(),
                        fields: vec![],
                        label: None,
                    })
                    .collect(),
                label: None,
            }],
        };
        let selected =
            SlotSelectionSet::new(vec![SlotSelection::new("s", vec!["old".into()]).unwrap()])
                .unwrap();
        let removed =
            resolve_slot_configuration(&selected, &one_slot(&["new"]), &contract()).unwrap();
        assert_eq!(removed.configuration_status, BLOCKED);
        assert_eq!(removed.slots[0].status, SELECTED_OPTION_REMOVED);
        assert!(removed.effective_selections.selections.is_empty());
        let returned =
            resolve_slot_configuration(&selected, &one_slot(&["old", "new"]), &contract()).unwrap();
        assert_eq!(returned.configuration_status, COMPLETE);
        assert_eq!(returned.effective_selections, selected);
        let detached =
            resolve_slot_configuration(&selected, &TemplateStructure::default(), &contract())
                .unwrap();
        assert_eq!(detached.configuration_status, NOT_APPLICABLE);
        assert_eq!(detached.detached_selections[0].option_ids, ["old"]);
        assert!(detached.blocking_kinds.is_empty());
        let cleared = resolve_slot_configuration(
            &SlotSelectionSet::default(),
            &one_slot(&["old"]),
            &contract(),
        )
        .unwrap();
        assert_eq!(cleared.slots[0].status, MISSING_REQUIRED_SELECTION);
    }

    #[test]
    fn source_delta_separates_removed_selection_from_option_reordering() {
        let slot = |id: &str, options: &[&str]| TemplateSlot {
            id: id.into(),
            shared_fields: vec![],
            options: options
                .iter()
                .map(|option| TemplateOption {
                    id: (*option).into(),
                    fields: vec![],
                    label: None,
                })
                .collect(),
            label: None,
        };
        let source = TemplateStructure {
            root_fields: vec![],
            slots: vec![slot("keep", &["A", "B"]), slot("drop", &["X"])],
        };
        let target = TemplateStructure {
            root_fields: vec![],
            slots: vec![slot("keep", &["B", "A"]), slot("new", &["N"])],
        };
        let selected = SlotSelectionSet::new(vec![
            SlotSelection::new("keep", vec!["A".into()]).unwrap(),
            SlotSelection::new("drop", vec!["X".into()]).unwrap(),
        ])
        .unwrap();
        let delta = derive_reconciliation_source_delta("a1", 4, &selected, &source, "a2", &target);
        assert_eq!(delta.source_configuration_version, 4);
        assert_eq!(delta.added_slot_ids, ["new"]);
        assert_eq!(delta.removed_slot_ids, ["drop"]);
        assert_eq!(
            delta.preserved_selection_refs,
            [("keep".into(), "A".into())]
        );
        assert_eq!(
            delta.removed_selected_option_refs,
            [("drop".into(), "X".into())]
        );
        assert_eq!(delta.option_order_changes, ["keep"]);
        assert!(delta.added_option_refs.is_empty());
        assert!(delta.removed_option_refs.is_empty());
    }
}
