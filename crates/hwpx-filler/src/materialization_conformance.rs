//! In-memory HWPX materialization and reopened native postconditions.

use crate::execution_contract_set::{
    PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION, SealedExecutionPlanSemanticPayload,
};
use crate::execution_structure::ExecutionTemplateStructure;
use crate::fields::{
    FieldDocument, FillNote, field_xml_names, is_fill_target_field_type, normalize_field_id,
    try_fill_simple_batch,
};
use crate::hwpx_product_inspection::inspect_slots;
use crate::hwpx_structure_ops::remove_slot_option;
use crate::text_render::python_repr;
use hwpx_core::bookmark_region::{BookmarkRegion, resolve_bookmark_topology};
use hwpx_core::native_admission::{canonical_field_value, scan_entry_field_begins};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_core::structural_boundary::scan_structural_boundaries;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;

pub const STRUCTURE_BYTES_INCONSISTENT: &str = "STRUCTURE_BYTES_INCONSISTENT";
pub const REPARSE_FAILED: &str = "REPARSE_FAILED";
pub const REMOVAL_INCOMPLETE: &str = "REMOVAL_INCOMPLETE";
pub const PRESERVED_CONTENT_LOST: &str = "PRESERVED_CONTENT_LOST";
pub const FIELD_TEXT_MISMATCH: &str = "FIELD_TEXT_MISMATCH";
pub const OCCURRENCE_COUNT_MISMATCH: &str = "OCCURRENCE_COUNT_MISMATCH";
pub const MARKER_CLEANUP_VIOLATION: &str = "MARKER_CLEANUP_VIOLATION";
pub const PROTECTED_STRUCTURE_LOSS: &str = "PROTECTED_STRUCTURE_LOSS";
pub const SOURCE_CANDIDATE_MUTATED: &str = "SOURCE_CANDIDATE_MUTATED";
pub const CONFORMANCE_CONTRACT_ID: &str = "hwpx-materialization-conformance/v1";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConformanceExecutionError(pub String);
impl fmt::Display for ConformanceExecutionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ConformanceExecutionError {}
fn execution_error(message: impl Into<String>) -> ConformanceExecutionError {
    ConformanceExecutionError(message.into())
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ConformanceResult {
    Pass {
        output_digest: String,
        notes: Vec<FillNote>,
    },
    Failure {
        code: &'static str,
        detail: String,
    },
}
pub(crate) fn failure(code: &'static str, detail: impl Into<String>) -> ConformanceResult {
    ConformanceResult::Failure {
        code,
        detail: detail.into(),
    }
}
pub(crate) fn pass(output_bytes: &[u8], notes: Vec<FillNote>) -> ConformanceResult {
    ConformanceResult::Pass {
        output_digest: digest(output_bytes),
        notes,
    }
}
pub(crate) fn digest(bytes: &[u8]) -> String {
    let hex: String = Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    format!("sha256:{hex}")
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InMemoryMaterialization {
    pub output_bytes: Vec<u8>,
    pub notes: Vec<FillNote>,
}
fn op_code(op: &Value) -> Result<&str, ConformanceExecutionError> {
    op.get("op").and_then(Value::as_str).ok_or_else(|| {
        execution_error(format!("operation 에 op code 가 없다: {}", python_repr(op)))
    })
}
fn op_field(op: &Value) -> Result<&str, ConformanceExecutionError> {
    op.get("field_id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            execution_error(format!(
                "APPLY_FIELD_BINDING 에 field_id 가 없다: {}",
                python_repr(op)
            ))
        })
}
fn op_option(op: &Value) -> Result<(&str, &str), ConformanceExecutionError> {
    let Some(slot) = op.get("slot_id").and_then(Value::as_str) else {
        return Err(execution_error(format!(
            "REMOVE_OPTION operand 형식 불량: {}",
            python_repr(op)
        )));
    };
    let Some(option) = op.get("option_id").and_then(Value::as_str) else {
        return Err(execution_error(format!(
            "REMOVE_OPTION operand 형식 불량: {}",
            python_repr(op)
        )));
    };
    Ok((slot, option))
}
fn clean_candidate(candidate_bytes: &[u8]) -> Result<HwpxPackage, ConformanceExecutionError> {
    HwpxPackage::from_bytes(candidate_bytes, PackageLimits::default())
        .map_err(|error| execution_error(error.to_string()))
}

/// Execute the sealed operation order over a fresh package made from exact Candidate bytes.
pub fn apply_execution_plan_in_memory(
    candidate_bytes: &[u8],
    plan: &SealedExecutionPlanSemanticPayload,
    document_values: &HashMap<String, String>,
) -> Result<InMemoryMaterialization, ConformanceExecutionError> {
    apply_execution_operations_in_memory(candidate_bytes, &plan.ordered_operations, document_values)
}

pub(crate) fn apply_execution_operations_in_memory(
    candidate_bytes: &[u8],
    ordered_operations: &[Value],
    document_values: &HashMap<String, String>,
) -> Result<InMemoryMaterialization, ConformanceExecutionError> {
    let mut package = clean_candidate(candidate_bytes)?;
    let mut notes = Vec::new();
    let mut batch_attempted = false;
    for (at, op) in ordered_operations.iter().enumerate() {
        if !batch_attempted
            && op.get("op").and_then(Value::as_str) == Some(PLAN_APPLY_FIELD_BINDING)
        {
            batch_attempted = true;
            let requests = ordered_operations[at..]
                .iter()
                .map(|item| {
                    (item.get("op").and_then(Value::as_str) == Some(PLAN_APPLY_FIELD_BINDING))
                        .then(|| {
                            let field = item.get("field_id")?.as_str()?;
                            Some((field.to_owned(), document_values.get(field)?.clone()))
                        })
                        .flatten()
                })
                .collect::<Option<Vec<_>>>();
            if let Some(requests) = requests
                && try_fill_simple_batch(&mut package, &requests)
            {
                break;
            }
        }
        match op_code(op)? {
            PLAN_REMOVE_OPTION => {
                let (slot, option) = op_option(op)?;
                remove_slot_option(&mut package, slot, option)
                    .map_err(|error| execution_error(error.to_string()))?;
            }
            PLAN_APPLY_FIELD_BINDING => {
                let field = op_field(op)?;
                let value = document_values.get(field).ok_or_else(|| {
                    execution_error(format!(
                        "Active Field {} 에 대응하는 VDR document value 가 없다",
                        python_repr(&Value::String(field.into()))
                    ))
                })?;
                let names = field_xml_names(&package)
                    .map_err(|error| execution_error(error.to_string()))?;
                let mut wrote = false;
                for name in names {
                    let mut doc = FieldDocument::new(&mut package, &name)
                        .map_err(|error| execution_error(error.to_string()))?;
                    if doc
                        .set_field(field, value)
                        .map_err(|error| execution_error(error.to_string()))?
                    {
                        wrote = true;
                    }
                    for note in doc.notes() {
                        if !notes.contains(note) {
                            notes.push(note.clone());
                        }
                    }
                }
                if !wrote {
                    return Err(execution_error(format!(
                        "Active Field {} 를 candidate 의 어느 content entry 에도 쓸 수 없다",
                        python_repr(&Value::String(field.into()))
                    )));
                }
            }
            code => {
                return Err(execution_error(format!(
                    "미지원 operation code: {}",
                    python_repr(&Value::String(code.into()))
                )));
            }
        }
    }
    Ok(InMemoryMaterialization {
        output_bytes: package
            .to_bytes()
            .map_err(|error| execution_error(error.to_string()))?,
        notes,
    })
}

fn options(package: &HwpxPackage) -> Result<HashSet<(String, String)>, String> {
    let (slots, diagnostics) = inspect_slots(package).map_err(|error| error.to_string())?;
    if !diagnostics.is_empty() {
        return Err(diagnostics
            .iter()
            .map(|item| item.message.as_str())
            .collect::<Vec<_>>()
            .join("; "));
    }
    Ok(slots
        .into_iter()
        .flat_map(|slot| {
            slot.options
                .into_iter()
                .map(move |option| (slot.id.clone(), option.id))
        })
        .collect())
}
fn field_values(
    package: &HwpxPackage,
) -> Result<Vec<(String, hwpx_core::text_extract::InlineText)>, String> {
    let names = field_xml_names(package).map_err(|error| error.to_string())?;
    let mut values = Vec::new();
    for name in names {
        let observed =
            scan_entry_field_begins(package, &name).map_err(|error| error.to_string())?;
        if !observed.pairing_usable() {
            return Err(format!(
                "unusable field pairing in {name}: {:?}",
                observed.diagnostics
            ));
        }
        for field in observed.fields {
            if is_fill_target_field_type(field.field_type.as_deref())
                && let Some(id) = field.raw_name.as_deref().and_then(normalize_field_id)
            {
                values.push((id, field.value));
            }
        }
    }
    Ok(values)
}
fn option_refs(structure: &ExecutionTemplateStructure) -> HashSet<(String, String)> {
    structure
        .option_regions
        .iter()
        .map(|item| (item.slot_id.clone(), item.option_id.clone()))
        .collect()
}
fn sorted_pairs(items: &HashSet<(String, String)>) -> String {
    let mut items = items
        .iter()
        .map(|(slot, option)| {
            format!(
                "({}, {})",
                python_repr(&Value::String(slot.clone())),
                python_repr(&Value::String(option.clone()))
            )
        })
        .collect::<Vec<_>>();
    items.sort();
    format!("[{}]", items.join(", "))
}
fn sorted_names(items: &HashSet<String>) -> String {
    let mut items = items
        .iter()
        .map(|item| python_repr(&Value::String(item.clone())))
        .collect::<Vec<_>>();
    items.sort();
    format!("[{}]", items.join(", "))
}

/// P7: the authored structure must describe exactly the Candidate's options and Fields.
pub fn verify_structure_bytes_consistency(
    candidate_bytes: &[u8],
    structure: &ExecutionTemplateStructure,
) -> ConformanceResult {
    let package = match HwpxPackage::from_bytes(candidate_bytes, PackageLimits::default()) {
        Ok(package) => package,
        Err(error) => {
            return failure(
                STRUCTURE_BYTES_INCONSISTENT,
                format!("candidate 재파싱 실패: {error}"),
            );
        }
    };
    let bytes_options = match options(&package) {
        Ok(options) => options,
        Err(detail) => {
            return failure(
                STRUCTURE_BYTES_INCONSISTENT,
                format!("candidate inspect 가 blocking diagnostics 를 낸다: {detail}"),
            );
        }
    };
    let struct_options = option_refs(structure);
    if bytes_options != struct_options {
        return failure(
            STRUCTURE_BYTES_INCONSISTENT,
            format!(
                "structure Option id {} 가 bytes {} 와 불일치",
                sorted_pairs(&struct_options),
                sorted_pairs(&bytes_options)
            ),
        );
    }
    let bytes_fields = match field_values(&package) {
        Ok(values) => values.into_iter().map(|(id, _)| id).collect::<HashSet<_>>(),
        Err(detail) => {
            return failure(
                STRUCTURE_BYTES_INCONSISTENT,
                format!("candidate 재파싱 실패: {detail}"),
            );
        }
    };
    let struct_fields = structure
        .field_occurrences
        .iter()
        .map(|item| item.field_id.clone())
        .collect::<HashSet<_>>();
    if struct_fields != bytes_fields {
        return failure(
            STRUCTURE_BYTES_INCONSISTENT,
            format!(
                "structure Field 투영이 bytes 와 불일치: structure-only={}, bytes-only={}",
                sorted_names(&struct_fields.difference(&bytes_fields).cloned().collect()),
                sorted_names(&bytes_fields.difference(&struct_fields).cloned().collect())
            ),
        );
    }
    ConformanceResult::Pass {
        output_digest: String::new(),
        notes: Vec::new(),
    }
}

type RegionKey = (String, String);
type RegionShape = (
    Option<String>,
    Option<RegionKey>,
    Vec<String>,
    Option<String>,
);
fn region_key(region: &BookmarkRegion) -> RegionKey {
    (region.section.clone(), region.pairing_id().to_owned())
}
fn region_shape(region: &BookmarkRegion) -> RegionShape {
    (
        region.name.clone(),
        region.parent.as_deref().map(region_key),
        region.meta_tags.clone(),
        region.meta_tag_attribute.clone(),
    )
}
fn region_key_repr(key: &RegionKey) -> String {
    format!(
        "({}, {})",
        python_repr(&Value::String(key.0.clone())),
        python_repr(&Value::String(key.1.clone()))
    )
}
fn region_shape_repr(shape: &RegionShape) -> String {
    let optional = |value: &Option<String>| {
        value
            .as_ref()
            .map(|text| python_repr(&Value::String(text.clone())))
            .unwrap_or_else(|| "None".to_owned())
    };
    let parent = shape
        .1
        .as_ref()
        .map(region_key_repr)
        .unwrap_or_else(|| "None".to_owned());
    let tags = match shape.2.len() {
        0 => "()".to_owned(),
        1 => format!("({},)", python_repr(&Value::String(shape.2[0].clone()))),
        _ => format!(
            "({})",
            shape
                .2
                .iter()
                .map(|tag| python_repr(&Value::String(tag.clone())))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    };
    format!(
        "({}, {}, {}, {})",
        optional(&shape.0),
        parent,
        tags,
        optional(&shape.3)
    )
}
fn regions(package: &HwpxPackage) -> Result<BTreeMap<RegionKey, RegionShape>, String> {
    let rows = resolve_bookmark_topology(package).map_err(|error| error.to_string())?;
    Ok(rows
        .iter()
        .map(|region| (region_key(region), region_shape(region)))
        .collect())
}
fn protected_structure_loss(
    source_bytes: &[u8],
    output: &HwpxPackage,
    remove_ops: &[&Value],
) -> Result<Option<String>, String> {
    let mut reference = HwpxPackage::from_bytes(source_bytes, PackageLimits::default())
        .map_err(|error| error.to_string())?;
    for op in remove_ops {
        let slot = op["slot_id"].as_str().ok_or("missing slot_id")?;
        let option = op["option_id"].as_str().ok_or("missing option_id")?;
        remove_slot_option(&mut reference, slot, option).map_err(|error| error.to_string())?;
    }
    let expected = regions(&reference)?;
    let actual = regions(output)?;
    for (key, want) in expected {
        match actual.get(&key) {
            None => {
                return Ok(Some(format!(
                    "보호 BOOKMARK region 이 output 에서 소실: key={} shape={}",
                    region_key_repr(&key),
                    region_shape_repr(&want)
                )));
            }
            Some(got) if got != &want => {
                return Ok(Some(format!(
                    "보호 BOOKMARK region topology 변형: key={} {} != {}",
                    region_key_repr(&key),
                    region_shape_repr(&want),
                    region_shape_repr(got)
                )));
            }
            _ => {}
        }
    }
    Ok(None)
}

fn inspect_reopened_output(
    output: &HwpxPackage,
) -> Result<HashSet<(String, String)>, ConformanceResult> {
    // P0 checks XML syntax only. Pairing and marker diagnostics belong to P4.
    for part in scan_structural_boundaries(output).entries {
        let name = part.entry;
        let Some(entry) = output.entries.iter().find(|entry| entry.name == name) else {
            return Err(failure(
                REPARSE_FAILED,
                format!("output 재파싱 실패: missing entry {name}"),
            ));
        };
        if let Err(error) = hwpx_core::xml_view::XmlView::parse(&entry.data) {
            return Err(failure(
                REPARSE_FAILED,
                format!("output 재파싱 실패: {error}"),
            ));
        }
    }
    options(output).map_err(|detail| {
        failure(
            MARKER_CLEANUP_VIOLATION,
            format!("output inspect 가 blocking marker diagnostics 를 낸다: {detail}"),
        )
    })
}

pub(crate) struct NativePlanView<'a> {
    pub native_primitive_contract_id: &'a str,
    pub ordered_operations: &'a [Value],
    pub active_field_requirements: &'a [Value],
}

/// P0–P6: reopen actual output and independently check the sealed effects.
pub fn verify_materialization_postconditions(
    source_bytes: &[u8],
    output_bytes: &[u8],
    plan: &SealedExecutionPlanSemanticPayload,
    structure: &ExecutionTemplateStructure,
    document_values: &HashMap<String, String>,
    execution_notes: &[FillNote],
) -> Result<ConformanceResult, ConformanceExecutionError> {
    verify_materialization_postconditions_parts(
        source_bytes,
        output_bytes,
        NativePlanView {
            native_primitive_contract_id: &plan
                .execution_basis
                .contracts
                .roles
                .native_primitive_contract_id,
            ordered_operations: &plan.ordered_operations,
            active_field_requirements: &plan.active_field_requirements,
        },
        structure,
        document_values,
        execution_notes,
    )
}

pub(crate) fn verify_materialization_postconditions_parts(
    source_bytes: &[u8],
    output_bytes: &[u8],
    plan: NativePlanView<'_>,
    structure: &ExecutionTemplateStructure,
    document_values: &HashMap<String, String>,
    execution_notes: &[FillNote],
) -> Result<ConformanceResult, ConformanceExecutionError> {
    if plan.native_primitive_contract_id
        != crate::execution_composition::NATIVE_PRIMITIVE_CONTRACT_ID
    {
        return Err(execution_error(format!(
            "미지원 native primitive contract(latest fallback 없음): {}",
            python_repr(&Value::String(plan.native_primitive_contract_id.into()))
        )));
    }
    let remove_ops = plan
        .ordered_operations
        .iter()
        .filter(|op| op["op"] == PLAN_REMOVE_OPTION)
        .collect::<Vec<_>>();
    let removal_targets = remove_ops
        .iter()
        .filter_map(|op| {
            Some((
                op["slot_id"].as_str()?.to_owned(),
                op["option_id"].as_str()?.to_owned(),
            ))
        })
        .collect::<HashSet<_>>();
    let source = match HwpxPackage::from_bytes(source_bytes, PackageLimits::default()) {
        Ok(source) => source,
        Err(error) => {
            return Ok(failure(
                SOURCE_CANDIDATE_MUTATED,
                format!("source 재파싱 실패: {error}"),
            ));
        }
    };
    let source_options = match options(&source) {
        Ok(options) => options,
        Err(_) => {
            return Ok(failure(
                SOURCE_CANDIDATE_MUTATED,
                "source inspect 가 blocking diagnostics 를 낸다",
            ));
        }
    };
    if !removal_targets.is_subset(&source_options) {
        return Ok(failure(
            SOURCE_CANDIDATE_MUTATED,
            format!(
                "removal target {} 가 source 에 없다(source 변형)",
                sorted_pairs(
                    &removal_targets
                        .difference(&source_options)
                        .cloned()
                        .collect()
                )
            ),
        ));
    }
    let output = match HwpxPackage::from_bytes(output_bytes, PackageLimits::default()) {
        Ok(output) => output,
        Err(error) => {
            return Ok(failure(
                REPARSE_FAILED,
                format!("output 재파싱 실패: {error}"),
            ));
        }
    };
    let out_options = match inspect_reopened_output(&output) {
        Ok(options) => options,
        Err(result) => return Ok(result),
    };
    let field_values = match field_values(&output) {
        Ok(values) => values,
        Err(detail) => {
            return Ok(failure(
                REPARSE_FAILED,
                format!("output 재파싱 실패: {detail}"),
            ));
        }
    };
    let still = removal_targets
        .intersection(&out_options)
        .cloned()
        .collect::<HashSet<_>>();
    if !still.is_empty() {
        return Ok(failure(
            REMOVAL_INCOMPLETE,
            format!("removal target 이 output 에 잔존: {}", sorted_pairs(&still)),
        ));
    }
    let expected_remaining = source_options
        .difference(&removal_targets)
        .cloned()
        .collect::<HashSet<_>>();
    let lost = expected_remaining
        .difference(&out_options)
        .cloned()
        .collect::<HashSet<_>>();
    if !lost.is_empty() {
        return Ok(failure(
            PRESERVED_CONTENT_LOST,
            format!(
                "target 아닌 Option 이 output 에서 소실: {}",
                sorted_pairs(&lost)
            ),
        ));
    }
    let retained = structure
        .field_occurrences
        .iter()
        .filter(|occ| {
            !(occ.owner_kind == "OPTION"
                && occ
                    .owner_slot_id
                    .as_ref()
                    .zip(occ.owner_option_id.as_ref())
                    .is_some_and(|(slot, option)| {
                        removal_targets.contains(&(slot.clone(), option.clone()))
                    }))
        })
        .map(|occ| occ.field_id.clone())
        .collect::<HashSet<_>>();
    let present = field_values
        .iter()
        .map(|(id, _)| id.clone())
        .collect::<HashSet<_>>();
    let missing = retained
        .difference(&present)
        .cloned()
        .collect::<HashSet<_>>();
    if !missing.is_empty() {
        return Ok(failure(
            PRESERVED_CONTENT_LOST,
            format!(
                "제거 대상이 아닌 retained content 가 output 에서 소실: {}",
                sorted_names(&missing)
            ),
        ));
    }
    for requirement in plan.active_field_requirements {
        let Some(field) = requirement["field_id"].as_str() else {
            return Err(execution_error("Active Field requirement missing field_id"));
        };
        let Some(count) = requirement["expected_active_occurrence_count"].as_u64() else {
            return Err(execution_error("Active Field requirement missing count"));
        };
        let values = field_values
            .iter()
            .filter(|(id, _)| id == field)
            .map(|(_, value)| value)
            .collect::<Vec<_>>();
        if values.len() != count as usize {
            return Ok(failure(
                OCCURRENCE_COUNT_MISMATCH,
                format!(
                    "Active Field {} occurrence {} != 기대 {count}",
                    python_repr(&Value::String(field.into())),
                    values.len()
                ),
            ));
        }
        let Some(raw) = document_values.get(field) else {
            return Err(execution_error(format!(
                "Active Field {field} 에 대응하는 VDR document value 가 없다"
            )));
        };
        let want =
            canonical_field_value(raw).map_err(|error| execution_error(error.to_string()))?;
        for value in values {
            if !value.exact() {
                return Ok(failure(
                    FIELD_TEXT_MISMATCH,
                    format!(
                        "Active Field {} 에 판독하지 못한 인라인 요소 {:?} 가 남았다",
                        python_repr(&Value::String(field.into())),
                        value.unmodelled
                    ),
                ));
            }
            if value.text != want {
                return Ok(failure(
                    FIELD_TEXT_MISMATCH,
                    format!(
                        "Active Field {} text {} != 기대 {}",
                        python_repr(&Value::String(field.into())),
                        python_repr(&Value::String(value.text.clone())),
                        python_repr(&Value::String(want.clone()))
                    ),
                ));
            }
        }
    }
    match protected_structure_loss(source_bytes, &output, &remove_ops) {
        Ok(Some(detail)) => return Ok(failure(PROTECTED_STRUCTURE_LOSS, detail)),
        Err(detail) => return Ok(failure(REPARSE_FAILED, detail)),
        Ok(None) => {}
    }
    Ok(pass(output_bytes, execution_notes.to_vec()))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::PackageEntry;

    #[test]
    fn inline_values_are_verified_after_reopening_materialized_bytes() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/inline_field_values.json"
        ))
        .unwrap();
        let case = &fixture["materialization"];
        let package = HwpxPackage {
            entries: case["sources"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(name, text)| PackageEntry {
                    name: name.clone(),
                    data: text.as_str().unwrap().as_bytes().to_vec(),
                    stored: name == "mimetype",
                })
                .collect(),
        };
        let source = package.to_bytes().unwrap();
        let structure = crate::hwpx_qualification::inspect_hwpx_qualification(&source)
            .unwrap()
            .execution_structure
            .unwrap();
        let values: HashMap<String, String> =
            serde_json::from_value(case["values"].clone()).unwrap();
        let ops = case["ordered_operations"].as_array().unwrap();
        let output = apply_execution_operations_in_memory(&source, ops, &values).unwrap();
        let verify = |bytes: &[u8]| {
            verify_materialization_postconditions_parts(
                &source,
                bytes,
                NativePlanView {
                    native_primitive_contract_id: case["native_primitive_contract_id"]
                        .as_str()
                        .unwrap(),
                    ordered_operations: ops,
                    active_field_requirements: case["active_field_requirements"]
                        .as_array()
                        .unwrap(),
                },
                &structure,
                &values,
                &output.notes,
            )
            .unwrap()
        };
        assert!(matches!(
            verify(&output.output_bytes),
            ConformanceResult::Pass { .. }
        ));
        let reopened =
            HwpxPackage::from_bytes(&output.output_bytes, PackageLimits::default()).unwrap();
        assert_eq!(
            crate::fields::read_fields(&reopened).unwrap(),
            [
                ("본문".into(), "가\t나\n다 라".into()),
                ("줄".into(), "첫\n둘".into())
            ]
        );
        for tag in ["tab", "fwSpace"] {
            let mut tampered = reopened.clone();
            let section = tampered
                .entries
                .iter_mut()
                .find(|entry| entry.name == "Contents/section0.xml")
                .unwrap();
            let mut xml = String::from_utf8(section.data.clone()).unwrap();
            let start = xml.find(&format!("<hp:{tag} ")).unwrap();
            let end = start + xml[start..].find("/>").unwrap() + 2;
            if tag == "tab" {
                xml.replace_range(start..end, "");
            } else {
                xml.insert_str(end, "<hp:nbSpace/>");
            }
            section.data = xml.into_bytes();
            assert!(matches!(
                verify(&tampered.to_bytes().unwrap()),
                ConformanceResult::Failure {
                    code: FIELD_TEXT_MISMATCH,
                    ..
                }
            ));
        }

        let mut lying = structure.clone();
        lying.field_occurrences[0].field_id = "없음".into();
        assert!(matches!(
            verify_structure_bytes_consistency(&source, &lying),
            ConformanceResult::Failure {
                code: STRUCTURE_BYTES_INCONSISTENT,
                ..
            }
        ));
        assert!(matches!(
            verify(b"not a package"),
            ConformanceResult::Failure {
                code: REPARSE_FAILED,
                ..
            }
        ));
        assert!(matches!(
            verify_materialization_postconditions_parts(
                b"not a package",
                &output.output_bytes,
                NativePlanView {
                    native_primitive_contract_id: case["native_primitive_contract_id"]
                        .as_str()
                        .unwrap(),
                    ordered_operations: ops,
                    active_field_requirements: case["active_field_requirements"]
                        .as_array()
                        .unwrap(),
                },
                &structure,
                &values,
                &output.notes,
            )
            .unwrap(),
            ConformanceResult::Failure {
                code: SOURCE_CANDIDATE_MUTATED,
                ..
            }
        ));
        let mut erased = reopened.clone();
        erased
            .entries
            .iter_mut()
            .find(|entry| entry.name == "Contents/section0.xml")
            .unwrap()
            .data = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'><hp:p><hp:run><hp:t>plain</hp:t></hp:run></hp:p></hs:sec>",
            hwpx_core::text_model::HP_NS
        )
        .into_bytes();
        assert!(matches!(
            verify(&erased.to_bytes().unwrap()),
            ConformanceResult::Failure {
                code: PRESERVED_CONTENT_LOST,
                ..
            }
        ));
        let mut wrong_count = case["active_field_requirements"]
            .as_array()
            .unwrap()
            .clone();
        wrong_count[0]["expected_active_occurrence_count"] = 2.into();
        assert!(matches!(
            verify_materialization_postconditions_parts(
                &source,
                &output.output_bytes,
                NativePlanView {
                    native_primitive_contract_id: case["native_primitive_contract_id"]
                        .as_str()
                        .unwrap(),
                    ordered_operations: ops,
                    active_field_requirements: &wrong_count,
                },
                &structure,
                &values,
                &output.notes,
            )
            .unwrap(),
            ConformanceResult::Failure {
                code: OCCURRENCE_COUNT_MISMATCH,
                ..
            }
        ));
        let mut guarded = package.clone();
        let section = guarded
            .entries
            .iter_mut()
            .find(|entry| entry.name == "Contents/section0.xml")
            .unwrap();
        let xml = String::from_utf8(section.data.clone()).unwrap();
        section.data = xml.replacen(
            "<hp:p>",
            "<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='guard' type='BOOKMARK' name='guard'/></hp:ctrl><hp:t>protected</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='guard'/></hp:ctrl></hp:run></hp:p><hp:p>",
            1,
        ).into_bytes();
        let guarded_bytes = guarded.to_bytes().unwrap();
        let guarded_structure =
            crate::hwpx_qualification::inspect_hwpx_qualification(&guarded_bytes)
                .unwrap()
                .execution_structure
                .unwrap();
        assert!(matches!(
            verify_materialization_postconditions_parts(
                &guarded_bytes,
                &source,
                NativePlanView {
                    native_primitive_contract_id: case["native_primitive_contract_id"]
                        .as_str()
                        .unwrap(),
                    ordered_operations: &[],
                    active_field_requirements: &[],
                },
                &guarded_structure,
                &values,
                &[],
            )
            .unwrap(),
            ConformanceResult::Failure {
                code: PROTECTED_STRUCTURE_LOSS,
                ..
            }
        ));
    }

    #[test]
    fn reopened_output_separates_xml_syntax_from_marker_cleanup() {
        let section = |body: &str| {
            HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: format!(
                    "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'>{body}</hs:sec>",
                    hwpx_core::text_model::HP_NS
                )
                .into_bytes(),
                stored: false,
            }],
        }
        };
        let cases = [
            ("<hp:p>", REPARSE_FAILED),
            (
                "<hp:p><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>",
                MARKER_CLEANUP_VIOLATION,
            ),
        ];
        for (body, expected) in cases {
            let result = inspect_reopened_output(&section(body));
            assert!(
                matches!(result, Err(ConformanceResult::Failure { code, .. }) if code == expected)
            );
        }
    }

    #[test]
    fn retained_removal_target_is_reported_as_incomplete() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/hwpx_qualification.json"
        ))
        .unwrap();
        let entries = fixture["cases"][0]["entries"].as_object().unwrap();
        let package = HwpxPackage {
            entries: entries
                .iter()
                .map(|(name, value)| PackageEntry {
                    name: name.clone(),
                    data: value.as_str().unwrap().as_bytes().to_vec(),
                    stored: name == "mimetype",
                })
                .collect(),
        };
        let source = package.to_bytes().unwrap();
        let result = crate::hwpx_qualification::inspect_hwpx_qualification(&source).unwrap();
        assert!(result.diagnostics.is_empty(), "{:?}", result.diagnostics);
        let structure = result.execution_structure.unwrap();
        let operations =
            [serde_json::json!({"op":PLAN_REMOVE_OPTION,"slot_id":"slot","option_id":"a"})];
        assert!(matches!(
            verify_materialization_postconditions_parts(
                &source,
                &source,
                NativePlanView {
                    native_primitive_contract_id:
                        crate::execution_composition::NATIVE_PRIMITIVE_CONTRACT_ID,
                    ordered_operations: &operations,
                    active_field_requirements: &[],
                },
                &structure,
                &HashMap::new(),
                &[],
            )
            .unwrap(),
            ConformanceResult::Failure {
                code: REMOVAL_INCOMPLETE,
                ..
            }
        ));
    }
}
