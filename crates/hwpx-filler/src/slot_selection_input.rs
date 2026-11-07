//! Pure capture of current slot selections for an exact template application.

use crate::slot_configuration_context::SlotConfigurationContext;
use crate::slot_reconciliation::resolve_slot_configuration;
use crate::slot_selection::{SlotSelectionSet, digest_selection_set};
use crate::work_slot_configuration::WorkSlotConfigurationDraft;
use std::fmt;

pub const STALE_CONFIGURATION: &str = "STALE_CONFIGURATION";
pub const SLOT_CONFIGURATION_INCOMPLETE: &str = "SLOT_CONFIGURATION_INCOMPLETE";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotSelectionCaptureError {
    pub code: String,
    pub message: String,
}
impl fmt::Display for SlotSelectionCaptureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for SlotSelectionCaptureError {}
fn fail(code: &str, message: impl Into<String>) -> SlotSelectionCaptureError {
    SlotSelectionCaptureError {
        code: code.into(),
        message: message.into(),
    }
}
fn optional_version(value: Option<u64>) -> String {
    value.map_or_else(|| "None".into(), |version| version.to_string())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotlessSelectionContext {
    pub work_id: String,
    pub template_application_id: String,
    pub selection_semantic_contract_id: String,
    pub structure_projection_schema_version: String,
    pub template_structure_digest: String,
    pub source_configuration_version: Option<u64>,
    pub declared_selection_digest: Option<String>,
    pub captured_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotConfigurationSnapshot {
    pub work_id: String,
    pub template_application_id: String,
    pub source_configuration_version: u64,
    pub selection_semantic_contract_id: String,
    pub structure_projection_schema_version: String,
    pub effective_selections: SlotSelectionSet,
    pub effective_selection_digest: String,
    pub declared_selection_digest: String,
    pub template_structure_digest: String,
    pub captured_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SlotSelectionInput {
    Slotless(SlotlessSelectionContext),
    Slotted(SlotConfigurationSnapshot),
}
impl SlotSelectionInput {
    pub fn selection_semantic_contract_id(&self) -> &str {
        match self {
            Self::Slotless(item) => &item.selection_semantic_contract_id,
            Self::Slotted(item) => &item.selection_semantic_contract_id,
        }
    }
}

/// `expected_configuration_presence` is an optional compare-and-swap observation.
/// A slot-bearing incomplete selection is refused, while a 0-slot structure carries
/// explicit slotless evidence even when detached declarations are present.
pub fn plan_capture(
    context: &SlotConfigurationContext,
    config: Option<&WorkSlotConfigurationDraft>,
    captured_at: &str,
    expected_configuration_presence: Option<bool>,
    expected_configuration_version: Option<u64>,
) -> Result<SlotSelectionInput, SlotSelectionCaptureError> {
    let actual_version = config.map(|item| item.version);
    match expected_configuration_presence {
        Some(true) if config.is_none() || actual_version != expected_configuration_version => {
            return Err(fail(
                STALE_CONFIGURATION,
                format!(
                    "expected present version {}, current {}",
                    optional_version(expected_configuration_version),
                    optional_version(actual_version)
                ),
            ));
        }
        Some(false) if config.is_some() => {
            return Err(fail(
                STALE_CONFIGURATION,
                "expected absent Configuration but one now exists",
            ));
        }
        _ => {}
    }
    let empty = SlotSelectionSet::default();
    let selections = config.map_or(&empty, |item| &item.selections);
    let resolution = resolve_slot_configuration(
        selections,
        &context.template_structure,
        &context.selection_semantic_contract,
    )
    .map_err(|e| fail(e.0.as_str(), e.0.clone()))?;
    let digest = |set: &SlotSelectionSet| {
        digest_selection_set(&context.selection_semantic_contract_id, set)
            .map_err(|e| fail(e.kind.code(), e.detail))
    };
    if context.template_structure.slots.is_empty() {
        return Ok(SlotSelectionInput::Slotless(SlotlessSelectionContext {
            work_id: context.work_id.clone(),
            template_application_id: context.template_application_id.clone(),
            selection_semantic_contract_id: context.selection_semantic_contract_id.clone(),
            structure_projection_schema_version: context
                .structure_projection_schema_version
                .clone(),
            template_structure_digest: context.template_structure_digest.clone(),
            source_configuration_version: actual_version,
            declared_selection_digest: if config.is_some() {
                Some(digest(selections)?)
            } else {
                None
            },
            captured_at: captured_at.into(),
        }));
    }
    let Some(config) = config else {
        return Err(fail(
            SLOT_CONFIGURATION_INCOMPLETE,
            "current selection 이 complete 하지 않아 snapshot 을 만들지 않는다",
        ));
    };
    if !resolution.slot_selections_complete {
        return Err(fail(
            SLOT_CONFIGURATION_INCOMPLETE,
            "current selection 이 complete 하지 않아 snapshot 을 만들지 않는다",
        ));
    }
    Ok(SlotSelectionInput::Slotted(SlotConfigurationSnapshot {
        work_id: context.work_id.clone(),
        template_application_id: context.template_application_id.clone(),
        source_configuration_version: config.version,
        selection_semantic_contract_id: context.selection_semantic_contract_id.clone(),
        structure_projection_schema_version: context.structure_projection_schema_version.clone(),
        effective_selection_digest: digest(&resolution.effective_selections)?,
        effective_selections: resolution.effective_selections,
        declared_selection_digest: digest(selections)?,
        template_structure_digest: context.template_structure_digest.clone(),
        captured_at: captured_at.into(),
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{TemplateOption, TemplateSlot, TemplateStructure};
    use crate::slot_selection::{
        SelectionSemanticBindingKey, SlotSelection, default_selection_semantic_registry,
    };
    use crate::work_slot_configuration::EMPTY;

    fn context(slotted: bool) -> SlotConfigurationContext {
        let registry = default_selection_semantic_registry();
        let contract = registry
            .resolve(&SelectionSemanticBindingKey {
                qualification_profile_id: "hwpx-template-qualification-v4".into(),
                structure_projection_schema_version: "hwpx-structure-projection-v4".into(),
            })
            .unwrap()
            .clone();
        SlotConfigurationContext {
            workspace_instance_id: "ws".into(),
            work_id: "w".into(),
            template_application_id: "a".into(),
            template_lineage_id: "line".into(),
            application_epoch: 1,
            pass_evidence_id: "e".into(),
            revision_id: "r".into(),
            qualification_profile_id: "hwpx-template-qualification-v4".into(),
            structure_projection_schema_version: "hwpx-structure-projection-v4".into(),
            template_structure: TemplateStructure {
                root_fields: vec![],
                slots: if slotted {
                    vec![TemplateSlot {
                        id: "s".into(),
                        shared_fields: vec![],
                        label: None,
                        options: vec![TemplateOption {
                            id: "o".into(),
                            fields: vec![],
                            label: None,
                        }],
                    }]
                } else {
                    vec![]
                },
            },
            template_structure_digest: "sha256:structure".into(),
            selection_semantic_contract_id: contract.contract_id.clone(),
            selection_semantic_contract: contract,
        }
    }
    fn config() -> WorkSlotConfigurationDraft {
        WorkSlotConfigurationDraft {
            work_id: "w".into(),
            base_template_application_id: "a".into(),
            version: 1,
            selections: SlotSelectionSet::new(vec![
                SlotSelection::new("s", vec!["o".into()]).unwrap(),
            ])
            .unwrap(),
            origin: EMPTY.into(),
            reconciled_from_application_id: None,
            reconciled_from_version: None,
            reconciled_from_declared_selection_digest: None,
            created_at: "now".into(),
            updated_at: "now".into(),
        }
    }
    #[test]
    fn slotless_detached_and_complete_snapshot_respect_cas() {
        let draft = config();
        let slotless =
            plan_capture(&context(false), Some(&draft), "now", Some(true), Some(1)).unwrap();
        let SlotSelectionInput::Slotless(slotless) = slotless else {
            panic!("slotless required")
        };
        assert_eq!(
            slotless.declared_selection_digest,
            Some(digest_selection_set("slot-selection/v1", &draft.selections).unwrap())
        );
        assert_eq!(slotless.source_configuration_version, Some(1));
        let slotted =
            plan_capture(&context(true), Some(&draft), "now", Some(true), Some(1)).unwrap();
        let SlotSelectionInput::Slotted(slotted) = slotted else {
            panic!("slotted required")
        };
        assert_eq!(slotted.effective_selections, draft.selections);
        assert_eq!(
            slotted.effective_selection_digest,
            slotted.declared_selection_digest
        );
        assert_eq!(
            plan_capture(&context(true), None, "now", None, None)
                .unwrap_err()
                .code,
            SLOT_CONFIGURATION_INCOMPLETE
        );
        assert_eq!(
            plan_capture(&context(false), Some(&draft), "now", Some(false), None)
                .unwrap_err()
                .code,
            STALE_CONFIGURATION
        );
        for (present, expected, actual) in [
            (Some(true), None, None),
            (Some(true), Some(1), None),
            (Some(true), None, Some(&draft)),
            (Some(true), Some(2), Some(&draft)),
            (Some(false), None, Some(&draft)),
        ] {
            let error =
                plan_capture(&context(false), actual, "now", present, expected).unwrap_err();
            assert_eq!(error.code, STALE_CONFIGURATION);
            assert!(!error.to_string().is_empty());
        }
        let empty_input =
            plan_capture(&context(false), None, "captured", Some(false), None).unwrap();
        assert_eq!(
            empty_input.selection_semantic_contract_id(),
            "slot-selection/v1"
        );
        let SlotSelectionInput::Slotless(empty_input) = empty_input else {
            panic!("slotless required")
        };
        assert_eq!(
            empty_input,
            SlotlessSelectionContext {
                work_id: "w".into(),
                template_application_id: "a".into(),
                selection_semantic_contract_id: "slot-selection/v1".into(),
                structure_projection_schema_version: "hwpx-structure-projection-v4".into(),
                template_structure_digest: "sha256:structure".into(),
                source_configuration_version: None,
                declared_selection_digest: None,
                captured_at: "captured".into(),
            }
        );
        for selections in [
            SlotSelectionSet::default(),
            SlotSelectionSet::new(vec![SlotSelection::new("s", vec!["gone".into()]).unwrap()])
                .unwrap(),
        ] {
            let incomplete = WorkSlotConfigurationDraft {
                selections,
                ..draft.clone()
            };
            assert_eq!(
                plan_capture(&context(true), Some(&incomplete), "now", None, None)
                    .unwrap_err()
                    .code,
                SLOT_CONFIGURATION_INCOMPLETE
            );
        }
        let mut detached = draft.clone();
        detached
            .selections
            .selections
            .push(SlotSelection::new("gone", vec!["x".into()]).unwrap());
        let snapshot =
            plan_capture(&context(true), Some(&detached), "captured", None, None).unwrap();
        assert_eq!(
            snapshot.selection_semantic_contract_id(),
            "slot-selection/v1"
        );
        let SlotSelectionInput::Slotted(snapshot) = snapshot else {
            panic!("snapshot required")
        };
        assert_eq!(
            snapshot.effective_selection_digest,
            slotted.effective_selection_digest
        );
        assert_ne!(
            snapshot.declared_selection_digest,
            slotted.declared_selection_digest
        );
        assert_eq!(
            snapshot.declared_selection_digest,
            digest_selection_set("slot-selection/v1", &detached.selections).unwrap()
        );
        detached.version += 1;
        detached.selections = SlotSelectionSet::default();
        assert_eq!(snapshot.source_configuration_version, 1);
        assert_eq!(snapshot.effective_selections, draft.selections);
        assert_eq!(snapshot.captured_at, "captured");
        assert_eq!(snapshot.template_structure_digest, "sha256:structure");
        assert_eq!(snapshot.template_application_id, "a");
        assert_eq!(snapshot.work_id, "w");
        assert_eq!(
            snapshot.structure_projection_schema_version,
            "hwpx-structure-projection-v4"
        );
        let mut two_slots = context(true);
        let mut other = two_slots.template_structure.slots[0].clone();
        other.id = "other".into();
        two_slots.template_structure.slots.push(other);
        let mut both = draft.clone();
        both.selections
            .selections
            .push(SlotSelection::new("other", vec!["o".into()]).unwrap());
        let forward = plan_capture(&two_slots, Some(&both), "now", None, None).unwrap();
        both.selections.selections.reverse();
        let reverse = plan_capture(&two_slots, Some(&both), "now", None, None).unwrap();
        assert_eq!(forward, reverse);
    }
}
