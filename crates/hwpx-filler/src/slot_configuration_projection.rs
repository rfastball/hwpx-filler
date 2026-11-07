//! JSON-safe read model for an exact current slot resolution.

use crate::execution_structure::TemplateSlot;
use crate::slot_configuration_context::SlotConfigurationContext;
use crate::slot_reconciliation::{
    RESOLVED, ReconciliationSourceDelta, SELECTED_OPTION_REMOVED, SLOT_REMOVED,
    SlotConfigurationResolution, SlotDiagnostic, SlotResolution,
};
use crate::slot_selection::{
    CARDINALITY_VIOLATION, MISSING_REQUIRED_SELECTION, NO_AVAILABLE_OPTIONS,
};
use crate::work_slot_configuration::{WorkSlotConfigurationDraft, has_declared_selection};
use serde_json::{Value, json};
use std::collections::HashSet;

pub const CURRENT: &str = "CURRENT";
pub const CONTEXT_ERROR: &str = "CONTEXT_ERROR";
pub const NOT_APPLICABLE: &str = "NOT_APPLICABLE";
pub const NEEDS_SELECTION: &str = "NEEDS_SELECTION";
pub const HAS_BROKEN_SELECTIONS: &str = "HAS_BROKEN_SELECTIONS";
pub const SLOT_SELECTIONS_COMPLETE: &str = "SLOT_SELECTIONS_COMPLETE";
const UNSUPPORTED_SELECTION_POLICY: &str = "UNSUPPORTED_SELECTION_POLICY";

fn broken(status: &str) -> bool {
    matches!(
        status,
        SELECTED_OPTION_REMOVED
            | CARDINALITY_VIOLATION
            | NO_AVAILABLE_OPTIONS
            | UNSUPPORTED_SELECTION_POLICY
    )
}

fn blocking(status: &str) -> bool {
    broken(status) || status == MISSING_REQUIRED_SELECTION
}

fn display(label: Option<&str>, id: &str) -> String {
    label.map_or_else(|| format!("라벨 미지정 (ID: {id})"), str::to_owned)
}

pub fn project_context_error(code: &str, detail: Option<&str>) -> Value {
    json!({
        "view_status": CONTEXT_ERROR,
        "configuration_status": NOT_APPLICABLE,
        "context_error": code,
        "context_error_detail": detail,
        "configuration_present": false,
        "configuration_version": null,
        "summary": null,
        "slots": [],
        "detached_selections": [],
        "reconciliation_changes": null,
        "blocking_items": [],
        "informational_changes": [],
        "zone_actionable": false,
        "savable_selection": false,
        "retained_selections": [],
    })
}

fn project_retained_selections(
    context: &SlotConfigurationContext,
    resolution: &SlotConfigurationResolution,
    retained: Option<&SlotConfigurationResolution>,
) -> Vec<Value> {
    let answered: HashSet<&str> = resolution
        .slots
        .iter()
        .filter(|slot| !slot.effective_option_ids.is_empty())
        .map(|slot| slot.slot_id.as_str())
        .collect();
    let mut retained_selections = Vec::new();
    if let Some(previous) = retained {
        for slot in &previous.slots {
            if slot.declared_option_ids.is_empty() || answered.contains(slot.slot_id.as_str()) {
                continue;
            }
            let label = context
                .template_structure
                .slots
                .iter()
                .find(|item| item.id == slot.slot_id)
                .map(|item| display(item.label.as_deref(), &item.id));
            let fate = if matches!(
                slot.status.as_str(),
                NO_AVAILABLE_OPTIONS | UNSUPPORTED_SELECTION_POLICY
            ) {
                slot.status.as_str()
            } else if slot
                .diagnostics
                .iter()
                .any(|item| item.kind == SELECTED_OPTION_REMOVED)
            {
                SELECTED_OPTION_REMOVED
            } else {
                RESOLVED
            };
            retained_selections.push(json!({"slot_id":slot.slot_id,
                "slot_display_text":label,"option_ids":slot.declared_option_ids,"fate":fate}));
        }
        for item in &previous.detached_selections {
            retained_selections.push(json!({"slot_id":item.slot_id,
                "slot_display_text":null,"option_ids":item.option_ids,"fate":SLOT_REMOVED}));
        }
    }
    retained_selections
}

fn project_blocking_items(resolution: &SlotConfigurationResolution) -> Vec<Value> {
    let mut blocking_items = Vec::new();
    for slot in &resolution.slots {
        if blocking(&slot.status) {
            blocking_items
                .push(json!({"slot_id":slot.slot_id,"kind":slot.status,"option_id":null}));
        }
        for diagnostic in &slot.diagnostics {
            blocking_items.push(json!({"slot_id":slot.slot_id,
                "kind":diagnostic.kind,"option_id":diagnostic.option_id}));
        }
    }
    blocking_items
}

fn slot_settled(
    status: &str,
    effective: &[String],
    diagnostics: &[SlotDiagnostic],
    has_retained_note: bool,
) -> bool {
    !blocking(status)
        && status == RESOLVED
        && diagnostics.is_empty()
        && !has_retained_note
        && !effective.is_empty()
}

fn project_slot(structure: &TemplateSlot, slot: &SlotResolution, has_retained_note: bool) -> Value {
    let declared: HashSet<&str> = slot
        .declared_option_ids
        .iter()
        .map(String::as_str)
        .collect();
    let effective: HashSet<&str> = slot
        .effective_option_ids
        .iter()
        .map(String::as_str)
        .collect();
    let options: Vec<_> = structure
        .options
        .iter()
        .map(|option| {
            json!({
                "option_id":option.id,
                "display_text":display(option.label.as_deref(), &option.id),
                "selected":declared.contains(option.id.as_str()),
                "effective":effective.contains(option.id.as_str()),
                "structurally_associated_field_ids":option.fields,
            })
        })
        .collect();
    let settled = slot_settled(
        &slot.status,
        &slot.effective_option_ids,
        &slot.diagnostics,
        has_retained_note,
    );
    json!({
        "slot_id":slot.slot_id,
        "display_text":display(structure.label.as_deref(), &structure.id),
        "selection_policy":slot.policy,
        "status":slot.status,
        "declared_option_ids":slot.declared_option_ids,
        "effective_option_ids":slot.effective_option_ids,
        "options":options,
        "shared_field_ids":structure.shared_fields,
        "diagnostics":slot.diagnostics.iter().map(|item| json!({"kind":item.kind,"option_id":item.option_id})).collect::<Vec<_>>(),
        "settled":settled,
    })
}

fn configuration_status(resolution: &SlotConfigurationResolution) -> &'static str {
    if !resolution.applicable {
        NOT_APPLICABLE
    } else if resolution.slot_selections_complete {
        SLOT_SELECTIONS_COMPLETE
    } else if resolution.blocking_kinds.iter().any(|item| broken(item)) {
        HAS_BROKEN_SELECTIONS
    } else {
        NEEDS_SELECTION
    }
}

fn content_selection_zone_actionable(has_slots: bool, status: &str) -> bool {
    has_slots || matches!(status, NEEDS_SELECTION | HAS_BROKEN_SELECTIONS)
}

/// All fields come from one verified context and its paired current resolution.
pub fn project_current_slot_configuration(
    context: &SlotConfigurationContext,
    configuration: Option<&WorkSlotConfigurationDraft>,
    resolution: &SlotConfigurationResolution,
    source_delta: Option<&ReconciliationSourceDelta>,
    retained: Option<&SlotConfigurationResolution>,
) -> Result<Value, String> {
    if context.template_structure.slots.len() != resolution.slots.len()
        || context
            .template_structure
            .slots
            .iter()
            .zip(&resolution.slots)
            .any(|(structure, resolved)| structure.id != resolved.slot_id)
    {
        return Err("Slot structure 와 resolution 순서가 불일치".into());
    }
    let retained_selections = project_retained_selections(context, resolution, retained);
    let noted: HashSet<&str> = retained_selections
        .iter()
        .filter(|item| item["fate"] != SLOT_REMOVED)
        .filter_map(|item| item["slot_id"].as_str())
        .collect();
    let slots: Vec<_> = context
        .template_structure
        .slots
        .iter()
        .zip(&resolution.slots)
        .map(|(structure, slot)| {
            project_slot(structure, slot, noted.contains(slot.slot_id.as_str()))
        })
        .collect();
    let missing = resolution
        .slots
        .iter()
        .filter(|slot| slot.status == MISSING_REQUIRED_SELECTION)
        .count();
    let broken_count = resolution
        .slots
        .iter()
        .filter(|slot| broken(&slot.status))
        .count();
    let blocking_items = project_blocking_items(resolution);
    let detached: Vec<_> = resolution
        .detached_selections
        .iter()
        .map(|item| {
            json!({
                "slot_id":item.slot_id,"selected_option_ids":item.option_ids,
                "clearable":true,"status":SLOT_REMOVED,
            })
        })
        .collect();
    let informational: Vec<_> = resolution
        .detached_selections
        .iter()
        .map(|item| {
            json!({
                "slot_id":item.slot_id,"kind":SLOT_REMOVED,"option_id":null,
            })
        })
        .collect();
    let status = configuration_status(resolution);
    let delta = source_delta.map(|delta| {
        json!({
            "source_application_id":delta.source_application_id,
            "source_configuration_version":delta.source_configuration_version,
            "target_application_id":delta.target_application_id,
            "added_slot_ids":delta.added_slot_ids,
            "removed_slot_ids":delta.removed_slot_ids,
            "added_option_refs":delta.added_option_refs,
            "removed_option_refs":delta.removed_option_refs,
            "removed_selected_option_refs":delta.removed_selected_option_refs,
            "preserved_selection_refs":delta.preserved_selection_refs,
            "slot_order_changed":delta.slot_order_changed,
            "option_order_changes":delta.option_order_changes,
        })
    });
    Ok(json!({
        "view_status":CURRENT,
        "configuration_status":status,
        "context_error":null,
        "context_error_detail":null,
        "configuration_present":configuration.is_some(),
        "configuration_version":configuration.map(|item| item.version),
        "summary":{"blocking_kinds":resolution.blocking_kinds,
            "missing_selection_count":missing,"broken_selection_count":broken_count,
            "detached_selection_count":detached.len(),
            "slot_selections_complete":resolution.slot_selections_complete},
        "slots":slots,
        "detached_selections":detached,
        "reconciliation_changes":delta,
        "blocking_items":blocking_items,
        "informational_changes":informational,
        "zone_actionable":content_selection_zone_actionable(!resolution.slots.is_empty(), status),
        "savable_selection":has_declared_selection(configuration),
        "retained_selections":retained_selections,
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::execution_structure::{TemplateOption, TemplateStructure};
    use crate::slot_reconciliation::{
        derive_reconciliation_source_delta, resolve_slot_configuration,
    };
    use crate::slot_selection::{
        SelectionSemanticContractManifest, SlotSelection, SlotSelectionSet, decode_selection_set,
        default_selection_semantic_registry,
    };
    use crate::work_slot_configuration::decode_aggregate;

    fn fixtures() -> Value {
        serde_json::from_str(include_str!(
            "../../../tests/fixtures/slot_configuration_projection.json"
        ))
        .unwrap()
    }

    fn manifest(data: &Value) -> SelectionSemanticContractManifest {
        SelectionSemanticContractManifest {
            contract_id: data["contract_id"].as_str().unwrap().into(),
            selection_set_schema_version: data["selection_set_schema_version"]
                .as_str()
                .unwrap()
                .into(),
            canonical_encoding_version: data["canonical_encoding_version"].as_str().unwrap().into(),
            default_selection_policy: data["default_selection_policy"].as_str().unwrap().into(),
            supported_selection_policies: serde_json::from_value(
                data["supported_selection_policies"].clone(),
            )
            .unwrap(),
            created_semantics_version: data["created_semantics_version"].as_str().unwrap().into(),
        }
    }

    pub(crate) fn context(
        structure: TemplateStructure,
        contract: SelectionSemanticContractManifest,
    ) -> SlotConfigurationContext {
        SlotConfigurationContext {
            workspace_instance_id: "ws".into(),
            work_id: "w1".into(),
            template_application_id: "A1".into(),
            template_lineage_id: "L1".into(),
            application_epoch: 1,
            pass_evidence_id: "E1".into(),
            revision_id: "R1".into(),
            qualification_profile_id: "P1".into(),
            structure_projection_schema_version: "hwpx-structure-projection-v4".into(),
            template_structure: structure,
            template_structure_digest: "sha256:d".into(),
            selection_semantic_contract_id: contract.contract_id.clone(),
            selection_semantic_contract: contract,
        }
    }

    fn resolution(data: &Value, structure: &TemplateStructure) -> SlotConfigurationResolution {
        resolve_slot_configuration(
            &decode_selection_set(&data["selections"]).unwrap(),
            structure,
            &manifest(&data["contract"]),
        )
        .unwrap()
    }

    #[test]
    fn current_and_error_views_match_complete_compatibility_results() {
        let fixtures = fixtures();
        for case in fixtures["current"].as_array().unwrap() {
            let input = &case["input"];
            let context = context(
                serde_json::from_value(input["structure"].clone()).unwrap(),
                manifest(&input["resolution"]["contract"]),
            );
            let structure = &context.template_structure;
            let resolved = resolution(&input["resolution"], structure);
            let retained =
                (!input["retained"].is_null()).then(|| resolution(&input["retained"], structure));
            let config = (!input["configuration"].is_null())
                .then(|| decode_aggregate(&input["configuration"]).unwrap());
            let delta = (!input["source_delta"].is_null()).then(|| {
                let data = &input["source_delta"];
                derive_reconciliation_source_delta(
                    data["source_application"].as_str().unwrap(),
                    data["source_version"].as_u64().unwrap(),
                    &decode_selection_set(&data["source_selections"]).unwrap(),
                    &serde_json::from_value(data["source_structure"].clone()).unwrap(),
                    data["target_application"].as_str().unwrap(),
                    structure,
                )
            });
            let actual = project_current_slot_configuration(
                &context,
                config.as_ref().map(|value| &value.configurations[0]),
                &resolved,
                delta.as_ref(),
                retained.as_ref(),
            )
            .unwrap();
            assert_eq!(actual, case["expected"], "{}", case["name"]);
            if !resolved.slots.is_empty() {
                let mut wrong = resolved.clone();
                wrong.slots.pop();
                assert!(
                    project_current_slot_configuration(&context, None, &wrong, None, None).is_err()
                );
                let mut wrong = resolved;
                wrong.slots[0].slot_id = "different".into();
                assert!(
                    project_current_slot_configuration(&context, None, &wrong, None, None).is_err()
                );
            }
        }
        for case in fixtures["errors"].as_array().unwrap() {
            let input = &case["input"];
            assert_eq!(
                project_context_error(
                    input["context_error_code"].as_str().unwrap(),
                    input["context_error_detail"].as_str()
                ),
                case["expected"],
                "{}",
                case["name"]
            );
        }
    }

    #[test]
    fn selection_instructions_and_unresolved_notes_remain_visible() {
        let fixtures = fixtures();
        for case in fixtures["settled"].as_array().unwrap() {
            let input = &case["input"];
            let effective: Vec<String> =
                serde_json::from_value(input["effective_option_ids"].clone()).unwrap();
            let diagnostics: Vec<_> = input["diagnostics"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| SlotDiagnostic {
                    kind: item["kind"].as_str().unwrap().into(),
                    option_id: item["option_id"].as_str().map(str::to_owned),
                })
                .collect();
            assert_eq!(
                slot_settled(
                    input["slot_status"].as_str().unwrap(),
                    &effective,
                    &diagnostics,
                    input["has_retained_note"].as_bool().unwrap()
                ),
                case["expected"].as_bool().unwrap(),
                "{}",
                case["name"]
            );
        }
        for case in fixtures["zone"].as_array().unwrap() {
            let input = &case["input"];
            assert_eq!(
                content_selection_zone_actionable(
                    !input["slots"].as_array().unwrap().is_empty(),
                    input["configuration_status"].as_str().unwrap()
                ),
                case["expected"].as_bool().unwrap()
            );
        }
        assert!(!slot_settled(
            RESOLVED,
            &["A".into()],
            &[SlotDiagnostic {
                kind: SELECTED_OPTION_REMOVED.into(),
                option_id: Some("Z".into())
            }],
            false
        ));
    }

    #[test]
    fn answering_one_slot_preserves_other_retained_choices_and_unselectable_fates() {
        let structure = TemplateStructure {
            root_fields: vec![],
            slots: ["one", "two"]
                .into_iter()
                .map(|id| TemplateSlot {
                    id: id.into(),
                    shared_fields: vec![],
                    label: Some(format!("label {id}")),
                    options: vec![TemplateOption {
                        id: "A".into(),
                        fields: vec![],
                        label: Some("현재 라벨".into()),
                    }],
                })
                .collect(),
        };
        let contract = default_selection_semantic_registry()
            .get("slot-selection/v1")
            .unwrap()
            .clone();
        let mut context = context(structure, contract);
        let selections = |ids: &[&str]| {
            SlotSelectionSet::new(
                ids.iter()
                    .map(|id| SlotSelection::new(*id, vec!["A".into()]).unwrap())
                    .collect(),
            )
            .unwrap()
        };
        let retained = resolve_slot_configuration(
            &selections(&["one", "two", "gone"]),
            &context.template_structure,
            &context.selection_semantic_contract,
        )
        .unwrap();
        let current = resolve_slot_configuration(
            &selections(&["one"]),
            &context.template_structure,
            &context.selection_semantic_contract,
        )
        .unwrap();
        let view =
            project_current_slot_configuration(&context, None, &current, None, Some(&retained))
                .unwrap();
        assert_eq!(
            view["retained_selections"],
            json!([
                {"slot_id":"two", "slot_display_text":"label two", "option_ids":["A"], "fate":"RESOLVED"},
                {"slot_id":"gone", "slot_display_text":null, "option_ids":["A"], "fate":"SLOT_REMOVED"},
            ])
        );
        assert_eq!(view["slots"][0]["settled"], true);
        assert_eq!(view["slots"][1]["settled"], false);
        assert_eq!(view["slots"][1]["effective_option_ids"], json!([]));
        for fate in [NO_AVAILABLE_OPTIONS, UNSUPPORTED_SELECTION_POLICY] {
            if fate == NO_AVAILABLE_OPTIONS {
                context.template_structure.slots[1].options.clear();
            } else {
                context.selection_semantic_contract.default_selection_policy = "MANY".into();
            }
            let retained = resolve_slot_configuration(
                &selections(&["two"]),
                &context.template_structure,
                &context.selection_semantic_contract,
            )
            .unwrap();
            let current = resolve_slot_configuration(
                &SlotSelectionSet::default(),
                &context.template_structure,
                &context.selection_semantic_contract,
            )
            .unwrap();
            let view =
                project_current_slot_configuration(&context, None, &current, None, Some(&retained))
                    .unwrap();
            assert_eq!(view["retained_selections"][0]["fate"], fate);
            assert_eq!(view["retained_selections"][0]["option_ids"], json!(["A"]));
        }
    }
}
