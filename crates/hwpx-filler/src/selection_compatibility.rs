//! Historical selection compatibility from exact structure and content evidence.

use crate::execution_structure::ExecutionTemplateStructure;
use crate::job::sorted_json;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashMap;

pub const AUTO_KEEP: &str = "AUTO_KEEP";
pub const REVIEW_REQUIRED: &str = "REVIEW_REQUIRED";
pub const DETACHED: &str = "DETACHED";
pub const PRESENT_MATCH: &str = "PRESENT_MATCH";
pub const FINGERPRINT_CHANGED: &str = "FINGERPRINT_CHANGED";
pub const REMOVED_IN_CHAIN: &str = "REMOVED_IN_CHAIN";
pub const EVIDENCE_MISSING: &str = "EVIDENCE_MISSING";
pub const POLICY_CHANGED: &str = "POLICY_CHANGED";
pub const CONTENT_UNVERIFIED: &str = "CONTENT_UNVERIFIED";
pub const CONTENT_DIGEST_CHANGED: &str = "CONTENT_DIGEST_CHANGED";
pub const DETACHED_ABSENT: &str = "DETACHED_ABSENT";
pub const FINGERPRINT_SCHEMA: &str = "selection-compatibility-fingerprint/v1";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SelectionCompatibilityFacts {
    pub slot_id: String,
    pub option_id: String,
    pub classification: String,
    pub source_fingerprint: Option<String>,
    pub target_fingerprint: Option<String>,
    pub reason: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChainApplicationFacts {
    pub execution_structure: Option<ExecutionTemplateStructure>,
    pub selection_contract_id: Option<String>,
    pub selection_policy: Option<String>,
    pub applied_content_digest: Option<String>,
}
fn option_present(structure: &ExecutionTemplateStructure, slot_id: &str, option_id: &str) -> bool {
    structure
        .product_structure
        .slots
        .iter()
        .any(|slot| slot.id == slot_id && slot.options.iter().any(|option| option.id == option_id))
}
/// Intrinsic region fingerprint; unrelated absolute structural shifts do not affect it.
pub fn option_compatibility_fingerprint(
    structure: &ExecutionTemplateStructure,
    slot_id: &str,
    option_id: &str,
) -> Option<String> {
    let region = structure
        .option_regions
        .iter()
        .find(|region| region.slot_id == slot_id && region.option_id == option_id)?;
    if region
        .owner_relation_facts
        .iter()
        .any(|fact| !fact.is_object())
    {
        return None;
    }
    let entries: HashMap<_, _> = structure
        .content_entries
        .iter()
        .map(|entry| (entry.content_entry_id.as_str(), entry))
        .collect();
    let region_entry = entries.get(region.content_entry_id.as_str());
    let owner_coincidence = region
        .owner_relation_facts
        .iter()
        .find(|fact| fact.get("relation") == Some(&Value::String("target_owner_slot".into())))
        .and_then(|fact| fact.get("coincidence"))
        .cloned();
    let mut owned: Vec<_> = structure
        .field_occurrences
        .iter()
        .filter(|occ| {
            occ.owner_kind == "OPTION"
                && occ.owner_slot_id.as_deref() == Some(slot_id)
                && occ.owner_option_id.as_deref() == Some(option_id)
        })
        .collect();
    owned.sort_by(|left, right| {
        (&left.field_id, left.occurrence_ordinal).cmp(&(&right.field_id, right.occurrence_ordinal))
    });
    let owned_fields:Vec<_>=owned.into_iter().map(|occ|json!({
        "field_id":occ.field_id,"occurrence_ordinal":occ.occurrence_ordinal,
        "relative_order":occ.structural_order-region.begin_order,
        "native_value_target_class":occ.native_value_target_class,
        "resolver_contract_id":occ.resolver_contract_id,
        "envelope_class":entries.get(occ.content_entry_id.as_str()).map(|entry|entry.envelope_class.as_str()),
    })).collect();
    let payload = json!({
        "schema":FINGERPRINT_SCHEMA,
        "region":{
            "span_length":region.end_order-region.begin_order,
            "owner_coincidence":owner_coincidence,
            "removal_capability_ref":region.removal_capability_ref,
            "envelope_class":region_entry.map(|entry|entry.envelope_class.as_str()),
            "envelope_capability_facts":region_entry.map(|entry|&entry.envelope_capability_facts),
        },
        "owned_fields":owned_fields,
    });
    let encoded = sorted_json(&payload);
    let digest = Sha256::digest(encoded.as_bytes());
    Some(format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    ))
}
fn facts(
    slot_id: &str,
    option_id: &str,
    classification: &str,
    source: Option<String>,
    target: Option<String>,
    reason: &str,
) -> SelectionCompatibilityFacts {
    SelectionCompatibilityFacts {
        slot_id: slot_id.into(),
        option_id: option_id.into(),
        classification: classification.into(),
        source_fingerprint: source,
        target_fingerprint: target,
        reason: reason.into(),
    }
}
/// Only byte-identical content and present, identical structure across every hop permit AUTO_KEEP.
pub struct CompatibilityEvidence<'a> {
    pub chain_structures: &'a [Option<&'a ExecutionTemplateStructure>],
    pub chain_content_digests: &'a [Option<&'a str>],
    pub source_contract_id: Option<&'a str>,
    pub target_contract_id: &'a str,
    pub source_policy: Option<&'a str>,
    pub target_policy: &'a str,
}
/// Stability of the option's structural fingerprint across every chain hop, or the
/// first reason it is not stable.
fn chain_fingerprint_reason(
    chain_structures: &[Option<&ExecutionTemplateStructure>],
    slot_id: &str,
    option_id: &str,
    target_fp: &str,
) -> Option<&'static str> {
    for structure in chain_structures {
        let Some(structure) = structure else {
            return Some(EVIDENCE_MISSING);
        };
        let Some(hop) = option_compatibility_fingerprint(structure, slot_id, option_id) else {
            return Some(REMOVED_IN_CHAIN);
        };
        if hop != target_fp {
            return Some(FINGERPRINT_CHANGED);
        }
    }
    None
}
/// Stability of the option's content digest across every chain hop (against the final
/// hop's digest), or the first reason it is not stable.
fn chain_content_reason(chain_content_digests: &[Option<&str>]) -> Option<&'static str> {
    let target_content = chain_content_digests.last().and_then(|item| *item);
    for digest in chain_content_digests {
        let (Some(digest), Some(target_content)) = (digest, target_content) else {
            return Some(CONTENT_UNVERIFIED);
        };
        if *digest != target_content {
            return Some(CONTENT_DIGEST_CHANGED);
        }
    }
    None
}
pub fn classify_selection(
    slot_id: &str,
    option_id: &str,
    evidence: CompatibilityEvidence<'_>,
) -> SelectionCompatibilityFacts {
    let CompatibilityEvidence {
        chain_structures,
        chain_content_digests,
        source_contract_id,
        target_contract_id,
        source_policy,
        target_policy,
    } = evidence;
    let source = chain_structures
        .first()
        .and_then(|item| *item)
        .and_then(|structure| option_compatibility_fingerprint(structure, slot_id, option_id));
    let result = |class: &str, target: Option<String>, reason: &str| {
        facts(slot_id, option_id, class, source.clone(), target, reason)
    };
    if chain_content_digests.len() != chain_structures.len() {
        return result(REVIEW_REQUIRED, None, CONTENT_UNVERIFIED);
    }
    let Some(target) = chain_structures.last().and_then(|item| *item) else {
        return result(REVIEW_REQUIRED, None, EVIDENCE_MISSING);
    };
    if !option_present(target, slot_id, option_id) {
        return result(DETACHED, None, DETACHED_ABSENT);
    }
    let Some(target_fp) = option_compatibility_fingerprint(target, slot_id, option_id) else {
        return result(REVIEW_REQUIRED, None, EVIDENCE_MISSING);
    };
    if source_contract_id != Some(target_contract_id) || source_policy != Some(target_policy) {
        return result(REVIEW_REQUIRED, Some(target_fp), POLICY_CHANGED);
    }
    if let Some(reason) = chain_fingerprint_reason(chain_structures, slot_id, option_id, &target_fp)
    {
        return result(REVIEW_REQUIRED, Some(target_fp), reason);
    }
    if let Some(reason) = chain_content_reason(chain_content_digests) {
        return result(REVIEW_REQUIRED, Some(target_fp), reason);
    }
    result(AUTO_KEEP, Some(target_fp), PRESENT_MATCH)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{
        ContentEntry, GlobalCompositionFacts, OptionRegion, TemplateOption, TemplateSlot,
        TemplateStructure,
    };
    use std::collections::BTreeMap;

    #[test]
    fn auto_keep_requires_structure_and_content_evidence_at_every_hop() {
        let structure = ExecutionTemplateStructure {
            projection_schema_version: "hwpx-structure-projection-v4".into(),
            product_structure: TemplateStructure {
                root_fields: vec![],
                slots: vec![TemplateSlot {
                    id: "s".into(),
                    shared_fields: vec![],
                    label: None,
                    options: vec![TemplateOption {
                        id: "o".into(),
                        fields: vec![],
                        label: None,
                    }],
                }],
            },
            field_occurrences: vec![],
            option_regions: vec![OptionRegion {
                slot_id: "s".into(),
                option_id: "o".into(),
                content_entry_id: "section0".into(),
                begin_order: 5,
                end_order: 10,
                owner_relation_facts: vec![],
                retained_content_relation_facts: vec![],
                removal_capability_ref: "native/v1".into(),
            }],
            removal_target_relations: vec![],
            content_entries: vec![ContentEntry {
                content_entry_id: "section0".into(),
                envelope_class: "section".into(),
                envelope_capability_facts: BTreeMap::new(),
            }],
            global_composition_facts: GlobalCompositionFacts {
                crossing_free: true,
                resolver_stability_facts: BTreeMap::new(),
                admitted_relation_profile: "native/v1".into(),
            },
        };
        let chain = [Some(&structure), Some(&structure)];
        let same = classify_selection(
            "s",
            "o",
            CompatibilityEvidence {
                chain_structures: &chain,
                chain_content_digests: &[Some("digest"), Some("digest")],
                source_contract_id: Some("contract"),
                target_contract_id: "contract",
                source_policy: Some("EXACTLY_ONE"),
                target_policy: "EXACTLY_ONE",
            },
        );
        assert_eq!(same.classification, AUTO_KEEP);
        assert!(same.source_fingerprint.is_some());
        assert_eq!(
            same.source_fingerprint.as_deref(),
            Some("sha256:12d6bcff2f87c6c0c7dca4e607abbef1cc3ae039e02392d4dcddea615c1c397f")
        );
        assert_eq!(same.source_fingerprint, same.target_fingerprint);
        let changed = classify_selection(
            "s",
            "o",
            CompatibilityEvidence {
                chain_structures: &chain,
                chain_content_digests: &[Some("old"), Some("new")],
                source_contract_id: Some("contract"),
                target_contract_id: "contract",
                source_policy: Some("EXACTLY_ONE"),
                target_policy: "EXACTLY_ONE",
            },
        );
        assert_eq!(changed.reason, CONTENT_DIGEST_CHANGED);
        let missing = classify_selection(
            "s",
            "o",
            CompatibilityEvidence {
                chain_structures: &[None, Some(&structure)],
                chain_content_digests: &[Some("digest"), Some("digest")],
                source_contract_id: Some("contract"),
                target_contract_id: "contract",
                source_policy: Some("EXACTLY_ONE"),
                target_policy: "EXACTLY_ONE",
            },
        );
        assert_eq!(missing.classification, REVIEW_REQUIRED);
        let mut malformed = structure.clone();
        malformed.option_regions[0]
            .owner_relation_facts
            .push(Value::from(1));
        let rejected = classify_selection(
            "s",
            "o",
            CompatibilityEvidence {
                chain_structures: &[Some(&malformed), Some(&malformed)],
                chain_content_digests: &[Some("digest"), Some("digest")],
                source_contract_id: Some("contract"),
                target_contract_id: "contract",
                source_policy: Some("EXACTLY_ONE"),
                target_policy: "EXACTLY_ONE",
            },
        );
        assert_eq!(rejected.classification, REVIEW_REQUIRED);

        let classify = |chain: &[Option<&ExecutionTemplateStructure>],
                        digests: &[Option<&str>],
                        source_contract: Option<&str>,
                        target_contract: &str,
                        source_policy: Option<&str>,
                        target_policy: &str| {
            classify_selection(
                "s",
                "o",
                CompatibilityEvidence {
                    chain_structures: chain,
                    chain_content_digests: digests,
                    source_contract_id: source_contract,
                    target_contract_id: target_contract,
                    source_policy,
                    target_policy,
                },
            )
        };
        let consistent = [Some("digest"), Some("digest")];
        assert_eq!(
            classify(
                &chain,
                &[Some("digest")],
                Some("contract"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            CONTENT_UNVERIFIED
        );
        assert_eq!(
            classify(
                &chain,
                &[Some("digest"), None],
                Some("contract"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            CONTENT_UNVERIFIED
        );
        assert_eq!(
            classify(
                &chain,
                &consistent,
                Some("old"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            POLICY_CHANGED
        );
        assert_eq!(
            classify(
                &chain,
                &consistent,
                Some("contract"),
                "contract",
                Some("MANY"),
                "EXACTLY_ONE"
            )
            .reason,
            POLICY_CHANGED
        );
        let mut changed_structure = structure.clone();
        changed_structure.option_regions[0].removal_capability_ref = "other/v1".into();
        assert_eq!(
            classify(
                &[Some(&structure), Some(&changed_structure)],
                &consistent,
                Some("contract"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            FINGERPRINT_CHANGED
        );
        let mut removed = structure.clone();
        removed.product_structure.slots[0].options.clear();
        removed.option_regions.clear();
        let detached = classify(
            &[Some(&structure), Some(&removed)],
            &consistent,
            Some("contract"),
            "contract",
            Some("EXACTLY_ONE"),
            "EXACTLY_ONE",
        );
        assert_eq!(
            (detached.classification.as_str(), detached.reason.as_str()),
            (DETACHED, DETACHED_ABSENT)
        );
        assert_eq!(
            classify(
                &[Some(&structure), Some(&removed), Some(&structure)],
                &[Some("digest"); 3],
                Some("contract"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            REMOVED_IN_CHAIN
        );
        assert_eq!(
            classify(
                &[Some(&structure), None, Some(&structure)],
                &[Some("digest"); 3],
                Some("contract"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            EVIDENCE_MISSING
        );
        assert_eq!(
            classify(
                &[],
                &[],
                Some("contract"),
                "contract",
                Some("EXACTLY_ONE"),
                "EXACTLY_ONE"
            )
            .reason,
            EVIDENCE_MISSING
        );
        let mut shifted = structure.clone();
        shifted.option_regions[0].begin_order += 10;
        shifted.option_regions[0].end_order += 10;
        shifted.product_structure.slots.push(TemplateSlot {
            id: "unrelated".into(),
            shared_fields: vec![],
            label: None,
            options: vec![],
        });
        assert_eq!(
            option_compatibility_fingerprint(&structure, "s", "o"),
            option_compatibility_fingerprint(&shifted, "s", "o")
        );
        assert!(option_compatibility_fingerprint(&structure, "s", "other").is_none());
    }
}
