//! Classify a stored selection preset against the current exact template structure.

use crate::preset::SelectionPreset;
use crate::slot_command::{CHANGED, NO_CHANGE};
use crate::slot_configuration_context::SlotConfigurationContext;
use crate::slot_reconciliation::{RESOLVED, SLOT_REMOVED, resolve_slot_configuration};
use crate::slot_selection::{SlotSelection, SlotSelectionSet};
use crate::structure_scan::python_trim;
use crate::work_slot_configuration::{
    WorkSlotConfigurationDraft, apply_selections, has_declared_selection,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BrokenSelection {
    pub slot_id: String,
    pub selected_option_ids: Vec<String>,
    pub clearable: bool,
    pub status: String,
}

pub struct PresetFit {
    pub applied: SlotSelectionSet,
    pub broken: Vec<BrokenSelection>,
    pub fully_applicable: bool,
}

pub fn fit_preset(
    context: &SlotConfigurationContext,
    proposed: &SlotSelectionSet,
) -> Result<PresetFit, String> {
    let resolution = resolve_slot_configuration(
        proposed,
        &context.template_structure,
        &context.selection_semantic_contract,
    )
    .map_err(|error| error.to_string())?;
    let declared: std::collections::HashSet<_> = proposed
        .selections
        .iter()
        .map(|selection| selection.slot_id.as_str())
        .collect();
    let applied = resolution
        .slots
        .iter()
        .filter(|slot| declared.contains(slot.slot_id.as_str()) && slot.status == RESOLVED)
        .map(|slot| SlotSelection::new(&slot.slot_id, slot.effective_option_ids.clone()))
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())?;
    let applied = SlotSelectionSet::new(applied).map_err(|error| error.to_string())?;
    let mut broken = Vec::new();
    for slot in &resolution.slots {
        if declared.contains(slot.slot_id.as_str()) && slot.status != RESOLVED {
            broken.push(BrokenSelection {
                slot_id: slot.slot_id.clone(),
                selected_option_ids: slot.declared_option_ids.clone(),
                clearable: false,
                status: slot.status.clone(),
            });
        }
    }
    for item in &resolution.detached_selections {
        broken.push(BrokenSelection {
            slot_id: item.slot_id.clone(),
            selected_option_ids: item.option_ids.clone(),
            clearable: false,
            status: SLOT_REMOVED.into(),
        });
    }
    Ok(PresetFit {
        fully_applicable: broken.is_empty()
            && applied.selections.len() == proposed.selections.len(),
        applied,
        broken,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PresetSaveRejection {
    pub code: &'static str,
    pub detail: String,
}

pub fn plan_preset_save(
    config: Option<&WorkSlotConfigurationDraft>,
    name: &str,
    application_id: &str,
    contract_id: &str,
    now: &str,
) -> Result<SelectionPreset, PresetSaveRejection> {
    if !has_declared_selection(config) {
        return Err(PresetSaveRejection {
            code: "PRESET_EMPTY_SELECTION",
            detail: "저장할 선택이 없습니다(선택 0건).".into(),
        });
    }
    if name.chars().any(char::is_control) {
        return Err(PresetSaveRejection {
            code: "PRESET_INVALID_NAME",
            detail: "프리셋 이름에는 제어 문자를 사용할 수 없습니다.".into(),
        });
    }
    let trimmed = python_trim(name);
    if trimmed.is_empty() {
        return Err(PresetSaveRejection {
            code: "PRESET_INVALID_NAME",
            detail: "이름을 입력하세요.".into(),
        });
    }
    SelectionPreset::new(
        trimmed,
        config.expect("declared selection").selections.clone(),
        vec![
            ("template_application_id".into(), application_id.into()),
            ("selection_contract_id".into(), contract_id.into()),
        ],
        now,
    )
    .map_err(|e| PresetSaveRejection {
        code: "PRESET_INVALID_NAME",
        detail: e.to_string(),
    })
}

pub struct PresetApplyDecision {
    pub outcome_code: &'static str,
    pub changed: bool,
    pub new_config: Option<WorkSlotConfigurationDraft>,
    pub source_version: u64,
    pub resulting_version: u64,
    pub applied_slot_ids: Vec<String>,
    pub broken: Vec<BrokenSelection>,
}

pub fn decide_apply_preset(
    context: &SlotConfigurationContext,
    config: &WorkSlotConfigurationDraft,
    proposed: &SlotSelectionSet,
    now: &str,
) -> Result<PresetApplyDecision, String> {
    let fit = fit_preset(context, proposed)?;
    let mut merged = config.selections.selections.clone();
    for applied in &fit.applied.selections {
        if let Some(existing) = merged
            .iter_mut()
            .find(|item| item.slot_id == applied.slot_id)
        {
            *existing = applied.clone();
        } else {
            merged.push(applied.clone());
        }
    }
    let new_selections = SlotSelectionSet::new(merged).map_err(|e| e.to_string())?;
    let updated = apply_selections(config, new_selections, now).map_err(|e| e.to_string())?;
    let changed = updated.version != config.version;
    Ok(PresetApplyDecision {
        outcome_code: if changed { CHANGED } else { NO_CHANGE },
        changed,
        new_config: changed.then_some(updated.clone()),
        source_version: config.version,
        resulting_version: updated.version,
        applied_slot_ids: fit
            .applied
            .selections
            .iter()
            .map(|item| item.slot_id.clone())
            .collect(),
        broken: fit.broken,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{TemplateOption, TemplateSlot, TemplateStructure};
    use crate::slot_configuration_projection::tests::context;
    use crate::slot_selection::default_selection_semantic_registry;
    use crate::work_slot_configuration::create_empty;

    fn selections(pairs: &[(&str, &[&str])]) -> SlotSelectionSet {
        SlotSelectionSet::new(
            pairs
                .iter()
                .map(|(slot, options)| {
                    SlotSelection::new(*slot, options.iter().map(|id| (*id).into()).collect())
                        .unwrap()
                })
                .collect(),
        )
        .unwrap()
    }

    #[test]
    fn partial_preset_reports_every_broken_choice_and_preserves_unmentioned_choices() {
        let context = context(
            TemplateStructure {
                root_fields: vec![],
                slots: ["s1", "s2", "s3"]
                    .into_iter()
                    .map(|id| TemplateSlot {
                        id: id.into(),
                        label: None,
                        shared_fields: vec![],
                        options: if id == "s3" {
                            vec![]
                        } else {
                            ["o1", "o2"]
                                .into_iter()
                                .map(|id| TemplateOption {
                                    id: id.into(),
                                    label: None,
                                    fields: vec![],
                                })
                                .collect()
                        },
                    })
                    .collect(),
            },
            default_selection_semantic_registry()
                .get("slot-selection/v1")
                .unwrap()
                .clone(),
        );
        let empty = create_empty("w1", "A1", "t0").unwrap();
        let current = apply_selections(&empty, selections(&[("s2", &["o2"])]), "t1").unwrap();
        for (proposed, expected_applied, expected_broken) in [
            (selections(&[("s1", &["o1"])]), vec!["s1"], vec![]),
            (
                selections(&[("s1", &["o1"]), ("s2", &["o1"])]),
                vec!["s1", "s2"],
                vec![],
            ),
            (
                selections(&[("s1", &["o1"]), ("s2", &["gone"]), ("s9", &["z"])]),
                vec!["s1"],
                vec![("s2", "SELECTED_OPTION_REMOVED"), ("s9", "SLOT_REMOVED")],
            ),
            (
                selections(&[("s1", &["o1", "o2"]), ("s3", &["z"])]),
                vec![],
                vec![
                    ("s1", "CARDINALITY_VIOLATION"),
                    ("s3", "NO_AVAILABLE_OPTIONS"),
                ],
            ),
            (selections(&[]), vec![], vec![]),
        ] {
            let fit = fit_preset(&context, &proposed).unwrap();
            assert_eq!(fit.fully_applicable, expected_broken.is_empty());
            let decision = decide_apply_preset(&context, &current, &proposed, "t2").unwrap();
            assert_eq!(decision.applied_slot_ids, expected_applied);
            assert_eq!(decision.broken, fit.broken);
            assert_eq!(
                decision
                    .broken
                    .iter()
                    .map(|b| (b.slot_id.as_str(), b.status.as_str()))
                    .collect::<Vec<_>>(),
                expected_broken
            );
            assert!(decision.broken.iter().all(|b| !b.clearable));
            if expected_applied.is_empty() {
                assert_eq!(
                    (decision.outcome_code, decision.changed),
                    (NO_CHANGE, false)
                );
                assert!(decision.new_config.is_none());
                assert_eq!(decision.source_version, decision.resulting_version);
                continue;
            }
            assert_eq!((decision.outcome_code, decision.changed), (CHANGED, true));
            assert_eq!(
                (decision.source_version, decision.resulting_version),
                (2, 3)
            );
            let updated = decision.new_config.unwrap();
            let s2 = if expected_applied.contains(&"s2") {
                "o1"
            } else {
                "o2"
            };
            assert_eq!(
                updated.selections,
                selections(&[("s2", &[s2]), ("s1", &["o1"])])
            );
            let repeated = decide_apply_preset(&context, &updated, &proposed, "t3").unwrap();
            assert_eq!(
                (repeated.outcome_code, repeated.changed),
                (NO_CHANGE, false)
            );
            assert!(repeated.new_config.is_none());
            assert_eq!(repeated.broken, fit.broken);
        }
    }

    #[test]
    fn save_preserves_declared_values_and_provenance_but_refuses_empty_or_invalid_names() {
        let empty = create_empty("w1", "A1", "t0").unwrap();
        for config in [None, Some(&empty)] {
            assert_eq!(
                plan_preset_save(config, "name", "A1", "contract", "t1")
                    .unwrap_err()
                    .code,
                "PRESET_EMPTY_SELECTION"
            );
        }
        let chosen = apply_selections(&empty, selections(&[("gone", &["unknown"])]), "t1").unwrap();
        let saved = plan_preset_save(Some(&chosen), "　 표준  ", "A1", "contract", "t2").unwrap();
        assert_eq!(saved.name, "표준");
        assert_eq!(saved.selection_set, chosen.selections);
        assert_eq!(saved.created_at, "t2");
        assert_eq!(
            saved.provenance_map(),
            serde_json::json!({
                "template_application_id":"A1", "selection_contract_id":"contract"
            })
            .as_object()
            .unwrap()
            .clone()
        );
        for name in ["", "　 ", "표\n준", "표\0준", "표\u{7f}준"] {
            let rejection =
                plan_preset_save(Some(&chosen), name, "A1", "contract", "t2").unwrap_err();
            assert_eq!(rejection.code, "PRESET_INVALID_NAME");
            assert!(!rejection.detail.is_empty());
        }
    }
}
