//! Strict UTF-8 TXT qualification and composition-ready structure projection.

use crate::execution_composition::{
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID, resolve_native_primitive_contract,
};
use crate::execution_structure::{
    ContentEntry, ExecutionStructureInput, ExecutionTemplateStructure, FieldOccurrence,
    OptionRegionObservation, SlotRegionObservation, TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
    TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, TemplateOption, TemplateSlot, TemplateStructure,
    build_execution_structure,
};
use crate::hwpx_qualification::{
    QualificationDiagnostic, QualificationInspectError, QualificationInspection,
};
use crate::qualification_evidence::{ManifestInput, build_manifest};
use crate::structure_scan::{PLACEMENT_OPTION, PLACEMENT_SLOT, python_trim};
use crate::text_render::iter_field_token_matches;
use crate::text_structure::{TextStructureScan, scan_text_structure, splitlines};
use serde_json::json;
use std::collections::{BTreeMap, HashMap};

pub const TXT_ENCODING_DIAGNOSTIC_KIND: &str = "txt_encoding";
pub const TXT_CONTENT_ENTRY_ID: &str = "text";
pub const TXT_LINE_SEQUENCE_ENVELOPE_CLASS: &str = "txt-line-sequence";
pub const TXT_FIELD_TOKEN_TARGET_CLASS: &str = "txt-line-token";
pub const TXT_ADMITTED_RELATION_PROFILE: &str = "txt-line-disjoint-removal/v1";

#[derive(Clone)]
struct Token {
    name: String,
    start: i64,
    line: usize,
}
fn tokens(text: &str, line_starts: &[i64]) -> Vec<Token> {
    let mut result = Vec::new();
    let mut previous_byte = 0;
    let mut previous_char = 0;
    for found in iter_field_token_matches(text) {
        previous_char += text[previous_byte..found.start].chars().count();
        previous_byte = found.start;
        let start = previous_char as i64;
        let line = line_starts
            .partition_point(|offset| *offset <= start)
            .saturating_sub(1);
        result.push(Token {
            name: python_trim(found.body).into(),
            start,
            line,
        });
    }
    result
}
fn owner_at(line: usize, scan: &TextStructureScan) -> (Option<&str>, Option<&str>) {
    if let Some(place) = scan.placements.iter().find(|place| {
        place.kind == PLACEMENT_OPTION && place.content_start <= line && line <= place.content_end
    }) {
        return (Some(&place.slot_id), place.option_id.as_deref());
    }
    if let Some(place) = scan.placements.iter().find(|place| {
        place.kind == PLACEMENT_SLOT && place.content_start <= line && line <= place.content_end
    }) {
        return (Some(&place.slot_id), None);
    }
    (None, None)
}
fn add_unique(target: &mut Vec<String>, name: &str) {
    if !target.iter().any(|item| item == name) {
        target.push(name.into());
    }
}
fn product_structure(scan: &TextStructureScan, tokens: &[Token]) -> TemplateStructure {
    let mut root = Vec::new();
    let mut shared: HashMap<&str, Vec<String>> = scan
        .slots
        .iter()
        .map(|slot| (slot.id.as_str(), Vec::new()))
        .collect();
    let mut options: HashMap<(&str, &str), Vec<String>> = scan
        .slots
        .iter()
        .flat_map(|slot| {
            slot.options
                .iter()
                .map(move |option| ((slot.id.as_str(), option.id.as_str()), Vec::new()))
        })
        .collect();
    for token in tokens {
        match owner_at(token.line, scan) {
            (None, _) => add_unique(&mut root, &token.name),
            (Some(slot), None) => {
                add_unique(shared.get_mut(slot).expect("known slot"), &token.name)
            }
            (Some(slot), Some(option)) => {
                add_unique(
                    options.get_mut(&(slot, option)).expect("known option"),
                    &token.name,
                );
            }
        }
    }
    TemplateStructure {
        root_fields: root,
        slots: scan
            .slots
            .iter()
            .map(|slot| TemplateSlot {
                id: slot.id.clone(),
                shared_fields: shared.remove(slot.id.as_str()).unwrap_or_default(),
                options: slot
                    .options
                    .iter()
                    .map(|option| TemplateOption {
                        id: option.id.clone(),
                        fields: options
                            .remove(&(slot.id.as_str(), option.id.as_str()))
                            .unwrap_or_default(),
                        label: option.label.clone(),
                    })
                    .collect(),
                label: slot.label.clone(),
            })
            .collect(),
    }
}
fn projection(
    scan: &TextStructureScan,
    product: TemplateStructure,
    tokens: &[Token],
    bounds: &[(i64, i64)],
) -> Result<ExecutionTemplateStructure, QualificationInspectError> {
    let primitive = resolve_native_primitive_contract(TXT_NATIVE_PRIMITIVE_CONTRACT_ID)
        .map_err(|error| QualificationInspectError::Inspection(error.to_string()))?;
    let mut ordinals = HashMap::<&str, i64>::new();
    let occurrences = tokens
        .iter()
        .map(|token| {
            let (slot, option) = owner_at(token.line, scan);
            let ordinal = ordinals.entry(&token.name).or_default();
            let item = FieldOccurrence {
                field_id: token.name.clone(),
                occurrence_ordinal: *ordinal,
                owner_kind: match (slot, option) {
                    (None, _) => "ROOT",
                    (Some(_), None) => "SLOT_SHARED",
                    (Some(_), Some(_)) => "OPTION",
                }
                .into(),
                owner_slot_id: slot.map(str::to_owned),
                owner_option_id: option.map(str::to_owned),
                content_entry_id: TXT_CONTENT_ENTRY_ID.into(),
                structural_order: token.start,
                native_value_target_class: TXT_FIELD_TOKEN_TARGET_CLASS.into(),
                resolver_contract_id: primitive.field_resolver_contract_id.clone(),
            };
            *ordinal += 1;
            item
        })
        .collect();
    let slot_regions = scan
        .placements
        .iter()
        .filter(|place| place.kind == PLACEMENT_SLOT)
        .map(|place| SlotRegionObservation {
            slot_id: place.slot_id.clone(),
            content_entry_id: TXT_CONTENT_ENTRY_ID.into(),
            begin_order: bounds[place.begin_marker_line].0,
            end_order: bounds[place.end_marker_line].1,
        })
        .collect();
    let option_regions = scan
        .placements
        .iter()
        .filter(|place| place.kind == PLACEMENT_OPTION)
        .map(|place| OptionRegionObservation {
            slot_id: place.slot_id.clone(),
            option_id: place.option_id.clone().unwrap_or_default(),
            content_entry_id: TXT_CONTENT_ENTRY_ID.into(),
            begin_order: bounds[place.begin_marker_line].0,
            end_order: bounds[place.end_marker_line].1,
            removal_capability_ref: primitive.option_removal_contract_id.clone(),
        })
        .collect();
    let facts = [
        "retains_admissible_envelope",
        "handles_empty_edges",
        "preserves_owner_marker",
        "coincident_boundary_admissible",
    ]
    .into_iter()
    .map(|key| (key.into(), true))
    .collect::<BTreeMap<String, bool>>();
    let stability = [
        "remaining_target_resolvable_after_removal",
        "active_field_resolvable_after_removal",
        "field_write_preserves_identity",
    ]
    .into_iter()
    .map(|key| (key.into(), true))
    .collect();
    build_execution_structure(ExecutionStructureInput {
        product_structure: product,
        occurrences,
        slot_regions,
        option_regions,
        content_entries: vec![ContentEntry {
            content_entry_id: TXT_CONTENT_ENTRY_ID.into(),
            envelope_class: TXT_LINE_SEQUENCE_ENVELOPE_CLASS.into(),
            envelope_capability_facts: facts,
        }],
        resolver_stability_facts: stability,
        admitted_relation_profile: TXT_ADMITTED_RELATION_PROFILE.into(),
        projection_schema_version: TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
    })
    .map_err(|error| QualificationInspectError::Inspection(error.to_string()))
}

/// Observe one immutable TXT candidate; invalid encoding and marker topology yield diagnostics.
pub fn inspect_txt_qualification(
    canonical_bytes: &[u8],
) -> Result<QualificationInspection, QualificationInspectError> {
    let text = match std::str::from_utf8(canonical_bytes) {
        Ok(text) => text,
        Err(error) => {
            let reason = if error.error_len().is_none() {
                "unexpected end of data"
            } else {
                "invalid start byte"
            };
            return Ok(QualificationInspection {
                structure: None,
                diagnostics: vec![QualificationDiagnostic {
                    kind: TXT_ENCODING_DIAGNOSTIC_KIND.into(),
                    message: format!(
                        "템플릿을 UTF-8 로 읽을 수 없습니다({reason}, 위치 {}) — 파일을 UTF-8 로 다시 저장한 뒤 확인하세요.",
                        error.valid_up_to()
                    ),
                }],
                execution_structure: None,
            });
        }
    };
    let scan = scan_text_structure(text);
    if !scan.diagnostics.is_empty() {
        return Ok(QualificationInspection {
            structure: None,
            diagnostics: scan
                .diagnostics
                .iter()
                .map(|item| QualificationDiagnostic {
                    kind: item.kind.as_str().into(),
                    message: item.message.clone(),
                })
                .collect(),
            execution_structure: None,
        });
    }
    let lines = splitlines(text);
    let bounds = lines
        .iter()
        .map(|line| {
            (
                line.start_char as i64,
                (line.start_char + line.whole.chars().count() - 1) as i64,
            )
        })
        .collect::<Vec<_>>();
    let starts = bounds.iter().map(|item| item.0).collect::<Vec<_>>();
    let tokens = tokens(text, &starts);
    let product = product_structure(&scan, &tokens);
    let execution = projection(&scan, product.clone(), &tokens, &bounds)?;
    Ok(QualificationInspection {
        structure: Some(product),
        diagnostics: Vec::new(),
        execution_structure: Some(execution),
    })
}

pub fn txt_qualification_manifest(
    created_at: &str,
) -> crate::execution_structure::QualificationProfileManifest {
    build_manifest(ManifestInput {
        qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
        media: "txt",
        adapter_contract_version: "txt-inspection-v1",
        product_rule_version: "txt-qualification-rules-v1",
        operation_alphabet_version: "txt-operations-v1",
        projection_schema_version: TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload: &json!({}),
        created_at,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_composition::{
        COMPOSITION_CONTRACT_ID, CompositionPremiseVerificationResult, TXT_COMPOSITION_CONTRACT_ID,
        admit_composition_premises,
    };
    use crate::execution_structure::{decode_execution_structure, execution_pass_projection};
    use crate::qualification_evidence::{QualificationResult, project_structure};
    use crate::template_qualification::{qualify_exact, shipping_qualification_manifest};

    const FULL: &str = concat!(
        "머리말 {{제목}}\r\n",
        "{{#항목 첨부 첨부 목록}}\n",
        "공유 {{담당자}}\n",
        "{{#선택 있음 붙임 있음}}\n",
        "붙임 {{파일명}} · {{담당자}}\n",
        "{{/선택}}\n",
        "{{#선택 없음 붙임 없음}}\n",
        "해당 없음\n",
        "{{/선택}}\n",
        "{{/항목}}\n",
        "꼬리 {{제목}} {{기관명}}\n",
    );

    #[test]
    fn strict_utf8_and_scalar_field_positions() {
        for bytes in [&[0xff][..], &[0xe3][..]] {
            let bad = inspect_txt_qualification(bytes).unwrap();
            assert!(bad.structure.is_none() && bad.execution_structure.is_none());
            assert_eq!(bad.diagnostics.len(), 1);
            assert_eq!(bad.diagnostics[0].kind, TXT_ENCODING_DIAGNOSTIC_KIND);
            assert!(bad.diagnostics[0].message.contains("UTF-8"));
        }

        let good = inspect_txt_qualification("😀 {{A}} {{B}}\n".as_bytes()).unwrap();
        assert!(good.diagnostics.is_empty());
        assert_eq!(good.structure.unwrap().root_fields, ["A", "B"]);
        let positions = good
            .execution_structure
            .unwrap()
            .field_occurrences
            .iter()
            .map(|field| field.structural_order)
            .collect::<Vec<_>>();
        assert_eq!(positions, [2, 8]);
        for (body, fields) in [
            ("", vec![]),
            (
                "{{공고명}} 건에 대해 {{담당자}} 가 알립니다.\n{{공고명}}\n",
                vec!["공고명", "담당자"],
            ),
        ] {
            let result = inspect_txt_qualification(body.as_bytes()).unwrap();
            assert!(result.diagnostics.is_empty());
            let product = result.structure.unwrap();
            assert_eq!(product.root_fields, fields);
            assert!(product.slots.is_empty());
            assert_eq!(
                result.execution_structure.unwrap().product_structure,
                product
            );
        }
    }

    #[test]
    fn txt_ownership_labels_and_occurrences_survive_qualification_and_durable_projection() {
        let qualified = qualify_exact("revision-1", "txt", FULL.as_bytes()).unwrap();
        let QualificationResult::Passed {
            revision_id,
            qualification_profile_id,
            structure,
        } = qualified.result
        else {
            panic!("valid template refused")
        };
        assert_eq!(revision_id, "revision-1");
        assert_eq!(
            qualification_profile_id,
            TXT_EXECUTION_QUALIFICATION_PROFILE_ID
        );
        assert_eq!(
            structure,
            TemplateStructure {
                root_fields: vec!["제목".into(), "기관명".into()],
                slots: vec![TemplateSlot {
                    id: "첨부".into(),
                    label: Some("첨부 목록".into()),
                    shared_fields: vec!["담당자".into()],
                    options: vec![
                        TemplateOption {
                            id: "있음".into(),
                            label: Some("붙임 있음".into()),
                            fields: vec!["파일명".into(), "담당자".into()]
                        },
                        TemplateOption {
                            id: "없음".into(),
                            label: Some("붙임 없음".into()),
                            fields: vec![]
                        },
                    ],
                }],
            }
        );
        let execution = qualified.execution_structure.unwrap();
        assert_eq!(execution.product_structure, structure);
        assert_eq!(
            execution.projection_schema_version,
            TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
        );
        let observations = execution
            .field_occurrences
            .iter()
            .map(|field| {
                (
                    field.field_id.as_str(),
                    field.occurrence_ordinal,
                    field.owner_kind.as_str(),
                    field.owner_slot_id.as_deref(),
                    field.owner_option_id.as_deref(),
                )
            })
            .collect::<Vec<_>>();
        assert_eq!(
            observations,
            [
                ("제목", 0, "ROOT", None, None),
                ("담당자", 0, "SLOT_SHARED", Some("첨부"), None),
                ("파일명", 0, "OPTION", Some("첨부"), Some("있음")),
                ("담당자", 1, "OPTION", Some("첨부"), Some("있음")),
                ("제목", 1, "ROOT", None, None),
                ("기관명", 0, "ROOT", None, None),
            ]
        );
        assert!(
            execution
                .field_occurrences
                .windows(2)
                .all(|pair| pair[0].structural_order < pair[1].structural_order)
        );
        assert_eq!(
            execution
                .option_regions
                .iter()
                .map(|region| (region.slot_id.as_str(), region.option_id.as_str()))
                .collect::<std::collections::HashSet<_>>(),
            [("첨부", "있음"), ("첨부", "없음")].into()
        );
        assert!(!execution.removal_target_relations.is_empty());
        assert!(
            execution
                .removal_target_relations
                .iter()
                .all(|relation| relation.relation == "DISJOINT")
        );
        assert!(execution.global_composition_facts.crossing_free);
        let primitive =
            resolve_native_primitive_contract(TXT_NATIVE_PRIMITIVE_CONTRACT_ID).unwrap();
        assert!(matches!(
            admit_composition_premises(&execution, &primitive, TXT_COMPOSITION_CONTRACT_ID),
            CompositionPremiseVerificationResult::Passed(_)
        ));
        assert!(matches!(
            admit_composition_premises(&execution, &primitive, COMPOSITION_CONTRACT_ID),
            CompositionPremiseVerificationResult::ContextError(_)
        ));
        let projection = execution_pass_projection(&execution).unwrap();
        let slots = &projection.payload["product_structure"]["slots"];
        assert_eq!(slots[0]["label"], "첨부 목록");
        assert_eq!(slots[0]["options"][0]["label"], "붙임 있음");
        assert_eq!(
            decode_execution_structure(&projection.payload).unwrap(),
            execution
        );
        assert!(project_structure(&structure, "hwpx-structure-projection-v1").is_err());
        let manifest = shipping_qualification_manifest("txt", "2026-08-24T09:00:00").unwrap();
        assert_eq!(manifest, txt_qualification_manifest("2026-08-24T09:00:00"));
        assert_eq!(
            manifest.qualification_profile_id,
            "txt-template-qualification-v1"
        );
        assert_eq!(
            manifest.projection_schema_version,
            "txt-structure-projection-v1"
        );
        assert_eq!(manifest.media, "txt");
        assert_eq!(manifest.created_at, "2026-08-24T09:00:00");
    }

    #[test]
    fn marker_diagnostics_replace_both_structures_and_keep_scanner_vocabulary() {
        for (body, expected) in [
            ("{{#항목 첨부}}\n내용\n", "unbalanced_marker"),
            ("{{#선택 있음}}\n내용\n{{/선택}}\n", "option_outside_slot"),
            ("{{#항목}}\n내용\n{{/항목}}\n", "empty_slot_id"),
            ("{{#항목 첨부}}\n{{/항목}}\n", "empty_range"),
            (
                "앞 {{#항목 첨부}} 뒤\n내용\n{{/항목}}\n",
                "marker_not_alone",
            ),
            ("{{#몰라 첨부}}\n내용\n", "unknown_keyword"),
        ] {
            let inspection = inspect_txt_qualification(body.as_bytes()).unwrap();
            assert!(inspection.structure.is_none() && inspection.execution_structure.is_none());
            assert!(
                inspection
                    .diagnostics
                    .iter()
                    .any(|item| item.kind == expected)
            );
            let expected_diagnostics = scan_text_structure(body)
                .diagnostics
                .into_iter()
                .map(|item| (item.kind.as_str().to_owned(), item.message))
                .collect::<Vec<_>>();
            assert_eq!(
                inspection
                    .diagnostics
                    .iter()
                    .map(|item| (item.kind.clone(), item.message.clone()))
                    .collect::<Vec<_>>(),
                expected_diagnostics
            );
            assert!(
                inspection
                    .diagnostics
                    .iter()
                    .all(|item| !item.message.is_empty())
            );
            let qualified = qualify_exact("broken", "txt", body.as_bytes()).unwrap();
            assert!(qualified.execution_structure.is_none());
            let QualificationResult::Failed {
                revision_id,
                qualification_profile_id,
                diagnostics,
            } = qualified.result
            else {
                panic!("broken template passed")
            };
            assert_eq!(revision_id, "broken");
            assert_eq!(
                qualification_profile_id,
                TXT_EXECUTION_QUALIFICATION_PROFILE_ID
            );
            assert_eq!(
                diagnostics
                    .iter()
                    .map(|item| (item.kind.clone(), item.message.clone()))
                    .collect::<Vec<_>>(),
                expected_diagnostics
            );
        }
    }
}
