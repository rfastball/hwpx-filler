//! Native-free composition facts for a qualified template revision.

use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;

#[path = "execution_structure_build.rs"]
mod build;
#[path = "execution_structure_validation.rs"]
mod validation;
pub use build::build_execution_structure;
use validation::{
    product_index, validate_content_entries, validate_invariants, validate_occurrences,
};

pub const EXECUTION_STRUCTURE_PROJECTION_SCHEMA: &str = "hwpx-structure-projection-v2";
pub const LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA: &str = "hwpx-structure-projection-v4";
pub const TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA: &str = "txt-structure-projection-v1";
pub const EXECUTION_QUALIFICATION_PROFILE_ID: &str = "hwpx-template-qualification-v2";
pub const LABELED_EXECUTION_QUALIFICATION_PROFILE_ID: &str = "hwpx-template-qualification-v4";
pub const TXT_EXECUTION_QUALIFICATION_PROFILE_ID: &str = "txt-template-qualification-v1";
pub const ENVELOPE_CAPABILITY_KEYS: [&str; 4] = [
    "retains_admissible_envelope",
    "handles_empty_edges",
    "preserves_owner_marker",
    "coincident_boundary_admissible",
];
pub const RESOLVER_STABILITY_KEYS: [&str; 3] = [
    "remaining_target_resolvable_after_removal",
    "active_field_resolvable_after_removal",
    "field_write_preserves_identity",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionStructureError {
    pub code: &'static str,
    pub message: String,
}
impl fmt::Display for ExecutionStructureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for ExecutionStructureError {}
fn fail(code: &'static str, message: impl Into<String>) -> ExecutionStructureError {
    ExecutionStructureError {
        code,
        message: message.into(),
    }
}
fn integrity(message: impl Into<String>) -> ExecutionStructureError {
    fail("EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR", message)
}
fn quoted(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}
fn option_key(key: &OptionRegionRef) -> String {
    format!("({}, {})", quoted(&key.slot_id), quoted(&key.option_id))
}
fn occurrence_missing(message: impl Into<String>) -> ExecutionStructureError {
    fail("EXECUTION_STRUCTURE_OCCURRENCE_INCOMPLETE", message)
}
fn relation_missing(message: impl Into<String>) -> ExecutionStructureError {
    fail("EXECUTION_STRUCTURE_RELATION_INCOMPLETE", message)
}
fn envelope_missing(message: impl Into<String>) -> ExecutionStructureError {
    fail("EXECUTION_STRUCTURE_ENVELOPE_FACT_MISSING", message)
}
fn resolver_missing(message: impl Into<String>) -> ExecutionStructureError {
    fail("EXECUTION_STRUCTURE_RESOLVER_FACT_MISSING", message)
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TemplateOption {
    pub id: String,
    pub fields: Vec<String>,
    pub label: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TemplateSlot {
    pub id: String,
    pub shared_fields: Vec<String>,
    pub options: Vec<TemplateOption>,
    pub label: Option<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TemplateStructure {
    pub root_fields: Vec<String>,
    pub slots: Vec<TemplateSlot>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FieldOccurrence {
    pub field_id: String,
    pub occurrence_ordinal: i64,
    pub owner_kind: String,
    pub owner_slot_id: Option<String>,
    pub owner_option_id: Option<String>,
    pub content_entry_id: String,
    pub structural_order: i64,
    pub native_value_target_class: String,
    pub resolver_contract_id: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct OptionRegionRef {
    pub slot_id: String,
    pub option_id: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OptionRegion {
    pub slot_id: String,
    pub option_id: String,
    pub content_entry_id: String,
    pub begin_order: i64,
    pub end_order: i64,
    pub owner_relation_facts: Vec<Value>,
    pub retained_content_relation_facts: Vec<Value>,
    pub removal_capability_ref: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct RemovalTargetRelation {
    pub left_option_ref: OptionRegionRef,
    pub right_option_ref: OptionRegionRef,
    pub relation: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContentEntry {
    pub content_entry_id: String,
    pub envelope_class: String,
    pub envelope_capability_facts: BTreeMap<String, bool>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GlobalCompositionFacts {
    pub crossing_free: bool,
    pub resolver_stability_facts: BTreeMap<String, bool>,
    pub admitted_relation_profile: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionTemplateStructure {
    pub projection_schema_version: String,
    pub product_structure: TemplateStructure,
    pub field_occurrences: Vec<FieldOccurrence>,
    pub option_regions: Vec<OptionRegion>,
    pub removal_target_relations: Vec<RemovalTargetRelation>,
    pub content_entries: Vec<ContentEntry>,
    pub global_composition_facts: GlobalCompositionFacts,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotRegionObservation {
    pub slot_id: String,
    pub content_entry_id: String,
    pub begin_order: i64,
    pub end_order: i64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OptionRegionObservation {
    pub slot_id: String,
    pub option_id: String,
    pub content_entry_id: String,
    pub begin_order: i64,
    pub end_order: i64,
    pub removal_capability_ref: String,
}
#[derive(Clone, Debug)]
pub struct ExecutionStructureInput {
    pub product_structure: TemplateStructure,
    pub occurrences: Vec<FieldOccurrence>,
    pub slot_regions: Vec<SlotRegionObservation>,
    pub option_regions: Vec<OptionRegionObservation>,
    pub content_entries: Vec<ContentEntry>,
    pub resolver_stability_facts: BTreeMap<String, bool>,
    pub admitted_relation_profile: String,
    pub projection_schema_version: String,
}

pub fn is_supported_execution_projection(schema: &str) -> bool {
    matches!(
        schema,
        EXECUTION_STRUCTURE_PROJECTION_SCHEMA
            | LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
            | TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    )
}
fn labels_required(schema: &str) -> bool {
    matches!(
        schema,
        LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA | TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
    )
}
fn require_schema(schema: &str) -> Result<(), ExecutionStructureError> {
    if !is_supported_execution_projection(schema) {
        return Err(fail(
            "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION",
            format!(
                "미지원 execution structure projection schema: {}",
                quoted(schema)
            ),
        ));
    }
    Ok(())
}
fn has_labels(product: &TemplateStructure) -> bool {
    product.slots.iter().any(|slot| {
        slot.label.is_some() || slot.options.iter().any(|option| option.label.is_some())
    })
}
pub fn classify_span_relation(a: (i64, i64), b: (i64, i64)) -> &'static str {
    if a == b {
        return "SAME_SPAN";
    }
    let lo = a.0.max(b.0);
    let hi = a.1.min(b.1);
    if hi < lo {
        "DISJOINT"
    } else if hi == lo {
        "TOUCHING"
    } else if a.0 <= b.0 && b.1 <= a.1 {
        "CONTAINS"
    } else if b.0 <= a.0 && a.1 <= b.1 {
        "CONTAINED"
    } else {
        "CROSSING"
    }
}
fn owner_coincidence(option: (i64, i64), slot: (i64, i64)) -> &'static str {
    match (option.0 == slot.0, option.1 == slot.1) {
        (true, true) => "SAME_SPAN",
        (true, false) => "SAME_START",
        (false, true) => "SAME_END",
        (false, false) => "INTERIOR",
    }
}
fn point_position(order: i64, span: (i64, i64)) -> &'static str {
    if order < span.0 {
        "BEFORE"
    } else if order > span.1 {
        "AFTER"
    } else {
        "INSIDE"
    }
}
fn require_span(begin: i64, end: i64, what: &str) -> Result<(), ExecutionStructureError> {
    if begin >= end {
        return Err(integrity(format!(
            "{what} 의 order span 이 유효하지 않다: [{begin}, {end}]"
        )));
    }
    Ok(())
}
fn require_text(value: &str, what: &str) -> Result<(), ExecutionStructureError> {
    if value.is_empty() {
        return Err(integrity(format!(
            "{what} 는 비어 있지 않은 문자열이어야 한다"
        )));
    }
    Ok(())
}
fn product_payload(product: &TemplateStructure, labels: bool) -> Value {
    let slots: Vec<_> = product
        .slots
        .iter()
        .map(|slot| {
            let options: Vec<_> = slot
                .options
                .iter()
                .map(|option| {
                    let mut value = json!({"id":option.id,"fields":option.fields});
                    if labels {
                        value["label"] = json!(option.label);
                    }
                    value
                })
                .collect();
            let mut value =
                json!({"id":slot.id,"shared_fields":slot.shared_fields,"options":options});
            if labels {
                value["label"] = json!(slot.label);
            }
            value
        })
        .collect();
    json!({"root_fields":product.root_fields,"slots":slots})
}
pub fn encode_execution_structure(structure: &ExecutionTemplateStructure) -> Value {
    let mut ordered = structure.clone();
    ordered
        .field_occurrences
        .sort_by_key(|occurrence| occurrence.structural_order);
    ordered
        .option_regions
        .sort_by(|a, b| (&a.slot_id, &a.option_id).cmp(&(&b.slot_id, &b.option_id)));
    ordered.removal_target_relations.sort_by(|a, b| {
        (&a.left_option_ref, &a.right_option_ref).cmp(&(&b.left_option_ref, &b.right_option_ref))
    });
    ordered
        .content_entries
        .sort_by(|a, b| a.content_entry_id.cmp(&b.content_entry_id));
    let mut value = serde_json::to_value(&ordered).expect("execution structure is serializable");
    value["product_structure"] = product_payload(
        &structure.product_structure,
        labels_required(&structure.projection_schema_version),
    );
    value
}
fn canonical(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<_> = map.keys().collect();
            keys.sort();
            let mut sorted = Map::new();
            for key in keys {
                sorted.insert(key.clone(), canonical(&map[key]));
            }
            Value::Object(sorted)
        }
        Value::Array(values) => Value::Array(values.iter().map(canonical).collect()),
        _ => value.clone(),
    }
}
pub fn content_digest(payload: &Value) -> String {
    let bytes = serde_json::to_vec(&canonical(payload)).expect("JSON value is serializable");
    let digest = Sha256::digest(bytes);
    let mut result = String::from("sha256:");
    for byte in digest {
        result.push_str(&format!("{byte:02x}"));
    }
    result
}
pub fn template_structure_digest(structure: &ExecutionTemplateStructure) -> String {
    content_digest(&encode_execution_structure(structure))
}

pub fn decode_execution_structure(
    payload: &Value,
) -> Result<ExecutionTemplateStructure, ExecutionStructureError> {
    if !payload.is_object() {
        return Err(integrity("execution structure payload 가 매핑이 아니다"));
    }
    let schema = payload
        .get("projection_schema_version")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            fail(
                "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION",
                "미지원 execution structure projection schema",
            )
        })?;
    require_schema(schema)?;
    validate_payload_labels(payload, schema)?;
    let mut decoded = payload.clone();
    validate_relation_fact_payload(&decoded, schema)?;
    strip_legacy_labels(&mut decoded, schema);
    let structure: ExecutionTemplateStructure = serde_json::from_value(decoded)
        .map_err(|_| integrity(format!("{schema} payload 형식 불일치")))?;
    validate_invariants(&structure)?;
    Ok(structure)
}

fn validate_payload_labels(payload: &Value, schema: &str) -> Result<(), ExecutionStructureError> {
    if !labels_required(schema) {
        return Ok(());
    }
    let slots = payload
        .get("product_structure")
        .and_then(|value| value.get("slots"))
        .and_then(Value::as_array)
        .ok_or_else(|| integrity(format!("{schema} payload 형식 불일치")))?;
    for slot in slots {
        validate_label(slot, schema)?;
        let options = slot
            .get("options")
            .and_then(Value::as_array)
            .ok_or_else(|| integrity(format!("{schema} payload 형식 불일치")))?;
        for option in options {
            validate_label(option, schema)?;
        }
    }
    Ok(())
}
fn validate_label(value: &Value, schema: &str) -> Result<(), ExecutionStructureError> {
    let label = value
        .get("label")
        .ok_or_else(|| integrity(format!("{schema} payload 형식 불일치")))?;
    if label
        .as_str()
        .is_some_and(|value| python_trim(value).is_empty())
    {
        return Err(integrity(format!("{schema} payload 형식 불일치")));
    }
    Ok(())
}
fn validate_relation_fact_payload(
    payload: &Value,
    schema: &str,
) -> Result<(), ExecutionStructureError> {
    let regions = payload
        .get("option_regions")
        .and_then(Value::as_array)
        .ok_or_else(|| integrity(format!("{schema} payload 형식 불일치")))?;
    if regions.iter().any(|region| {
        ["owner_relation_facts", "retained_content_relation_facts"]
            .iter()
            .any(|key| {
                region
                    .get(*key)
                    .and_then(Value::as_array)
                    .is_none_or(|facts| facts.iter().any(|fact| !fact.is_object()))
            })
    }) {
        return Err(integrity(format!("{schema} payload 형식 불일치")));
    }
    Ok(())
}
fn strip_legacy_labels(decoded: &mut Value, schema: &str) {
    if labels_required(schema) {
        return;
    }
    if let Some(slots) = decoded
        .get_mut("product_structure")
        .and_then(|value| value.get_mut("slots"))
        .and_then(Value::as_array_mut)
    {
        for slot in slots {
            if let Some(map) = slot.as_object_mut() {
                map.remove("label");
                if let Some(options) = map.get_mut("options").and_then(Value::as_array_mut) {
                    for option in options {
                        if let Some(map) = option.as_object_mut() {
                            map.remove("label");
                        }
                    }
                }
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureProjection {
    pub projection_schema_version: String,
    pub payload: Value,
    pub payload_digest: String,
}
pub fn execution_pass_projection(
    structure: &ExecutionTemplateStructure,
) -> Result<StructureProjection, ExecutionStructureError> {
    require_schema(&structure.projection_schema_version)?;
    validate_invariants(structure)?;
    let payload = encode_execution_structure(structure);
    Ok(StructureProjection {
        projection_schema_version: structure.projection_schema_version.clone(),
        payload_digest: content_digest(&payload),
        payload,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationProfileManifest {
    pub qualification_profile_id: String,
    pub media: String,
    pub adapter_contract_version: String,
    pub product_rule_version: String,
    pub operation_alphabet_version: String,
    pub projection_schema_version: String,
    pub manifest_payload: Value,
    pub manifest_digest: String,
    pub created_at: String,
}
fn profile_schema(id: &str) -> Option<&'static str> {
    match id {
        EXECUTION_QUALIFICATION_PROFILE_ID => Some(EXECUTION_STRUCTURE_PROJECTION_SCHEMA),
        LABELED_EXECUTION_QUALIFICATION_PROFILE_ID => {
            Some(LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA)
        }
        TXT_EXECUTION_QUALIFICATION_PROFILE_ID => Some(TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA),
        _ => None,
    }
}
pub fn build_execution_manifest(
    qualification_profile_id: &str,
    media: &str,
    adapter_contract_version: &str,
    product_rule_version: &str,
    operation_alphabet_version: &str,
    manifest_payload: Value,
    created_at: &str,
) -> Result<QualificationProfileManifest, ExecutionStructureError> {
    for (name, value) in [
        ("media", media),
        ("adapter_contract_version", adapter_contract_version),
        ("product_rule_version", product_rule_version),
        ("operation_alphabet_version", operation_alphabet_version),
    ] {
        if value.is_empty() {
            return Err(fail(
                "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR",
                format!(
                    "composition-ready manifest 는 {} 가 비어 있을 수 없다",
                    quoted(name)
                ),
            ));
        }
    }
    if qualification_profile_id.is_empty() {
        return Err(fail(
            "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR",
            "qualification_profile_id 가 비어 있다",
        ));
    }
    if !manifest_payload.is_object() {
        return Err(fail(
            "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR",
            "manifest_payload 는 매핑이어야 한다",
        ));
    }
    Ok(QualificationProfileManifest {
        qualification_profile_id: qualification_profile_id.into(),
        media: media.into(),
        adapter_contract_version: adapter_contract_version.into(),
        product_rule_version: product_rule_version.into(),
        operation_alphabet_version: operation_alphabet_version.into(),
        projection_schema_version: profile_schema(qualification_profile_id)
            .unwrap_or(EXECUTION_STRUCTURE_PROJECTION_SCHEMA)
            .into(),
        manifest_digest: content_digest(&manifest_payload),
        manifest_payload,
        created_at: created_at.into(),
    })
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealedExecutionProfile {
    pub qualification_profile_id: String,
    pub projection_schema_version: String,
    pub template_structure_digest: String,
}
pub fn seal_execution_profile(
    manifest: &QualificationProfileManifest,
    projection: &StructureProjection,
) -> Result<SealedExecutionProfile, ExecutionStructureError> {
    let Some(schema) = profile_schema(&manifest.qualification_profile_id) else {
        return Err(fail(
            "EXECUTION_PROFILE_NOT_SEALABLE",
            format!(
                "미등록 profile id 는 seal 할 수 없다(latest fallback 없음): {}",
                quoted(&manifest.qualification_profile_id)
            ),
        ));
    };
    if manifest.projection_schema_version != schema
        || projection.projection_schema_version != schema
    {
        return Err(fail(
            "EXECUTION_PROFILE_NOT_SEALABLE",
            "projection schema 가 profile pair 와 다르다",
        ));
    }
    if manifest.manifest_digest != content_digest(&manifest.manifest_payload)
        || projection.payload_digest != content_digest(&projection.payload)
    {
        return Err(integrity("manifest 또는 projection digest 불일치"));
    }
    let structure = decode_execution_structure(&projection.payload)?;
    Ok(SealedExecutionProfile {
        qualification_profile_id: manifest.qualification_profile_id.clone(),
        projection_schema_version: schema.into(),
        template_structure_digest: template_structure_digest(&structure),
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn labeled_structure_roundtrips_and_rejects_forged_relation_facts() {
        let entry = ContentEntry {
            content_entry_id: "Contents/section0.xml".into(),
            envelope_class: "section".into(),
            envelope_capability_facts: ENVELOPE_CAPABILITY_KEYS
                .into_iter()
                .map(|key| (key.into(), true))
                .collect(),
        };
        let input = ExecutionStructureInput {
            product_structure: TemplateStructure {
                root_fields: vec!["root".into()],
                slots: vec![TemplateSlot {
                    id: "slot".into(),
                    shared_fields: vec![],
                    label: Some("항목".into()),
                    options: vec![TemplateOption {
                        id: "opt".into(),
                        fields: vec!["choice".into()],
                        label: Some("선택".into()),
                    }],
                }],
            },
            occurrences: vec![
                FieldOccurrence {
                    field_id: "root".into(),
                    occurrence_ordinal: 0,
                    owner_kind: "ROOT".into(),
                    owner_slot_id: None,
                    owner_option_id: None,
                    content_entry_id: entry.content_entry_id.clone(),
                    structural_order: 1,
                    native_value_target_class: "text".into(),
                    resolver_contract_id: "resolver-v1".into(),
                },
                FieldOccurrence {
                    field_id: "choice".into(),
                    occurrence_ordinal: 0,
                    owner_kind: "OPTION".into(),
                    owner_slot_id: Some("slot".into()),
                    owner_option_id: Some("opt".into()),
                    content_entry_id: entry.content_entry_id.clone(),
                    structural_order: 4,
                    native_value_target_class: "text".into(),
                    resolver_contract_id: "resolver-v1".into(),
                },
            ],
            slot_regions: vec![SlotRegionObservation {
                slot_id: "slot".into(),
                content_entry_id: entry.content_entry_id.clone(),
                begin_order: 2,
                end_order: 9,
            }],
            option_regions: vec![OptionRegionObservation {
                slot_id: "slot".into(),
                option_id: "opt".into(),
                content_entry_id: entry.content_entry_id.clone(),
                begin_order: 3,
                end_order: 7,
                removal_capability_ref: "remove-v1".into(),
            }],
            content_entries: vec![entry],
            resolver_stability_facts: RESOLVER_STABILITY_KEYS
                .into_iter()
                .map(|key| (key.into(), true))
                .collect(),
            admitted_relation_profile: "relations-v1".into(),
            projection_schema_version: LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
        };
        let structure = build_execution_structure(input.clone()).unwrap();
        let projection = execution_pass_projection(&structure).unwrap();
        assert_eq!(
            decode_execution_structure(&projection.payload).unwrap(),
            structure
        );
        assert_eq!(
            projection.payload_digest,
            template_structure_digest(&structure)
        );
        let manifest = build_execution_manifest(
            LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
            "hwpx",
            "adapter-v1",
            "product-v1",
            "operation-v1",
            json!({"purpose":"test"}),
            "2026-11-05",
        )
        .unwrap();
        assert_eq!(
            seal_execution_profile(&manifest, &projection)
                .unwrap()
                .template_structure_digest,
            template_structure_digest(&structure)
        );
        let mut malformed_fact = projection.payload.clone();
        malformed_fact["option_regions"][0]["owner_relation_facts"]
            .as_array_mut()
            .unwrap()
            .push(Value::Null);
        assert_eq!(
            decode_execution_structure(&malformed_fact)
                .unwrap_err()
                .code,
            "EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR"
        );
        let mut legacy = projection.payload.clone();
        legacy["projection_schema_version"] = json!(EXECUTION_STRUCTURE_PROJECTION_SCHEMA);
        let decoded = decode_execution_structure(&legacy).unwrap();
        assert_eq!(decoded.product_structure.slots[0].label, None);
        assert_eq!(decoded.product_structure.slots[0].options[0].label, None);
        let mut missing_label = projection.payload.clone();
        missing_label["product_structure"]["slots"][0]
            .as_object_mut()
            .unwrap()
            .remove("label");
        assert_eq!(
            decode_execution_structure(&missing_label).unwrap_err().code,
            "EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR"
        );
        let mut forged = projection.payload;
        forged["global_composition_facts"]["crossing_free"] = Value::Bool(false);
        assert_eq!(
            decode_execution_structure(&forged).unwrap_err().code,
            "EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR"
        );
        let mut missing_occurrence = input.clone();
        missing_occurrence.occurrences.pop();
        assert_eq!(
            build_execution_structure(missing_occurrence)
                .unwrap_err()
                .code,
            "EXECUTION_STRUCTURE_OCCURRENCE_INCOMPLETE"
        );
        let mut missing_relation = input.clone();
        missing_relation.option_regions.clear();
        assert_eq!(
            build_execution_structure(missing_relation)
                .unwrap_err()
                .code,
            "EXECUTION_STRUCTURE_RELATION_INCOMPLETE"
        );
        let mut outside_slot = input.clone();
        outside_slot.option_regions[0].begin_order = 1;
        assert_eq!(
            build_execution_structure(outside_slot).unwrap_err().code,
            "EXECUTION_STRUCTURE_PROJECTION_INTEGRITY_ERROR"
        );
        let mut missing_resolver = input.clone();
        missing_resolver
            .resolver_stability_facts
            .remove("field_write_preserves_identity");
        assert_eq!(
            build_execution_structure(missing_resolver)
                .unwrap_err()
                .code,
            "EXECUTION_STRUCTURE_RESOLVER_FACT_MISSING"
        );
        let mut forged = encode_execution_structure(&structure);
        forged["field_occurrences"][0]["structural_order"] = json!("zero");
        assert!(decode_execution_structure(&forged).is_err());
        let mut forged = encode_execution_structure(&structure);
        forged["projection_schema_version"] = json!("hwpx-structure-projection-v1");
        assert_eq!(
            decode_execution_structure(&forged).unwrap_err().code,
            "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION"
        );
    }
}
