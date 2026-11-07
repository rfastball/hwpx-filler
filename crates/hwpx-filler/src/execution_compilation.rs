//! Record-independent qualification and deterministic execution operation compilation.

use crate::canonical_execution_encoding::canonical_execution_digest;
use crate::execution_capture::{
    CapturedExecutionInput, EffectiveSelectionBasis, ExactTemplateExecutionBasis,
    build_exact_execution_basis, project_effective_selection,
};
use crate::execution_composition::{
    CompositionPremiseVerificationResult, CompositionPremisesPassed,
};
use crate::execution_structure::{ExecutionTemplateStructure, FieldOccurrence};
use crate::field_binding::{CONSTANT, EXACT_BLANK_POLICY, FieldBindingRule, RUNTIME_DATE, SOURCE};
use crate::slot_selection_input::SlotSelectionInput;
use crate::text_render::python_repr;
use crate::text_slice::TextSlice;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const EXECUTION_SEMANTICS_CONTRACT: &str = "execution-semantics/v1";
pub const OPERATION_ALPHABET_VERSION: &str = "execution-operation-alphabet/v1";
pub const ACTIVE_FIELD_UNBOUND: &str = "ACTIVE_FIELD_UNBOUND";
pub const REQUIRED_SOURCE_KEY_MISSING: &str = "REQUIRED_SOURCE_KEY_MISSING";
pub const SLOT_CONFIGURATION_INCOMPLETE: &str = "SLOT_CONFIGURATION_INCOMPLETE";
pub const COMPOSITION_PREMISES_NOT_PASSED: &str = "COMPOSITION_PREMISES_NOT_PASSED";
pub const COMPOSITION_STRUCTURE_MISMATCH: &str = "COMPOSITION_STRUCTURE_MISMATCH";
pub const COMPOSITION_POLICY_IDENTITY_MISMATCH: &str = "COMPOSITION_POLICY_IDENTITY_MISMATCH";
pub const SELECTION_CONTRACT_INTEGRITY_ERROR: &str = "SELECTION_CONTRACT_INTEGRITY_ERROR";
pub const SELECTION_STRUCTURE_DIGEST_MISMATCH: &str = "SELECTION_STRUCTURE_DIGEST_MISMATCH";
pub const SLOT_MODE_MISMATCH: &str = "SLOT_MODE_MISMATCH";
pub const UNKNOWN_SELECTION_TARGET: &str = "UNKNOWN_SELECTION_TARGET";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionCompilationError(pub String);
impl fmt::Display for ExecutionCompilationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ExecutionCompilationError {}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ActiveFieldValueExpression {
    FromSource {
        source_key: String,
        format_code: Option<String>,
        document_content_value_policy_id: String,
        format_kind: Option<String>,
        text_slice: Option<Box<TextSlice>>,
    },
    ConstantValue {
        text: String,
        format_code: Option<String>,
        document_content_value_policy_id: String,
    },
    IntentionalBlank {
        exact_blank_policy: String,
    },
    RuntimeDate {
        format_code: String,
        document_content_value_policy_id: String,
        format_kind: String,
    },
}
pub fn value_expression(rule: &FieldBindingRule) -> ActiveFieldValueExpression {
    let policy_id = rule.document_content_value_policy.policy_id.clone();
    match rule.binding_kind.as_str() {
        SOURCE => ActiveFieldValueExpression::FromSource {
            source_key: rule.source_key.clone().expect("validated SOURCE"),
            format_code: rule.format_code.clone(),
            document_content_value_policy_id: policy_id,
            format_kind: rule.format_kind.clone(),
            text_slice: rule.text_slice.clone().map(Box::new),
        },
        CONSTANT => ActiveFieldValueExpression::ConstantValue {
            text: rule
                .canonical_constant_value
                .as_ref()
                .expect("validated CONSTANT")
                .text
                .clone(),
            format_code: rule.format_code.clone(),
            document_content_value_policy_id: policy_id,
        },
        RUNTIME_DATE => ActiveFieldValueExpression::RuntimeDate {
            format_code: rule.format_code.clone().expect("validated RUNTIME_DATE"),
            document_content_value_policy_id: policy_id,
            format_kind: rule.format_kind.clone().expect("validated RUNTIME_DATE"),
        },
        _ => ActiveFieldValueExpression::IntentionalBlank {
            exact_blank_policy: EXACT_BLANK_POLICY.into(),
        },
    }
}
pub fn encode_value_expression(value: &ActiveFieldValueExpression) -> Value {
    match value {
        ActiveFieldValueExpression::FromSource {
            source_key,
            format_code,
            document_content_value_policy_id,
            format_kind,
            text_slice,
        } => {
            let mut result = json!({"kind":"FROM_SOURCE","source_key":source_key,
                "format_kind":format_kind,"format_code":format_code,
                "document_content_value_policy_id":document_content_value_policy_id});
            if let Some(slice) = text_slice {
                result["text_slice"] = slice.to_dict();
            }
            result
        }
        ActiveFieldValueExpression::ConstantValue {
            text,
            format_code,
            document_content_value_policy_id,
        } => json!({"kind":"CONSTANT","canonical_value":{"kind":"TEXT","text":text},
                "format_code":format_code,"document_content_value_policy_id":document_content_value_policy_id}),
        ActiveFieldValueExpression::IntentionalBlank { exact_blank_policy } => {
            json!({"kind":"INTENTIONAL_BLANK","exact_blank_policy":exact_blank_policy})
        }
        ActiveFieldValueExpression::RuntimeDate {
            format_code,
            document_content_value_policy_id,
            format_kind,
        } => json!({"kind":"RUNTIME_DATE","format_kind":format_kind,"format_code":format_code,
                "document_content_value_policy_id":document_content_value_policy_id}),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveFieldProjection {
    pub active_field_sequence: Vec<String>,
    pub active_logical_field_order: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveFieldRequirement {
    pub field_id: String,
    pub expected_active_occurrence_count: usize,
    pub value_expression: ActiveFieldValueExpression,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ExecutionOperation {
    RemoveOption { slot_id: String, option_id: String },
    ApplyFieldBinding { field_id: String },
}
pub fn encode_operation(op: &ExecutionOperation) -> Value {
    match op {
        ExecutionOperation::RemoveOption { slot_id, option_id } => {
            json!({"op":"REMOVE_OPTION","slot_id":slot_id,"option_id":option_id})
        }
        ExecutionOperation::ApplyFieldBinding { field_id } => {
            json!({"op":"APPLY_FIELD_BINDING","field_id":field_id})
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EffectiveFieldBindingRule {
    pub field_id: String,
    pub binding_kind: String,
    pub value_expression: ActiveFieldValueExpression,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EffectiveFieldBindingBasis {
    pub effective_active_binding_rules: Vec<EffectiveFieldBindingRule>,
    pub active_binding_digest: String,
    pub required_source_keys: Vec<String>,
    pub required_source_key_set_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompositionVerificationRef {
    pub composition_contract_id: String,
    pub native_primitive_contract_id: String,
    pub template_structure_digest: String,
    pub theorem_evidence_manifest_digest: String,
    pub premise_verification_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationBlocker {
    pub code: String,
    pub field_id: Option<String>,
    pub detail: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionQualificationBlocked {
    pub normalized_blockers: Vec<QualificationBlocker>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionCompilationContextError {
    pub code: String,
    pub detail: String,
}
impl ExecutionCompilationContextError {
    fn new(code: &str, detail: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            detail: detail.into(),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualifiedExecutionCompilation {
    pub exact_template_execution_basis: ExactTemplateExecutionBasis,
    pub effective_selection_basis: EffectiveSelectionBasis,
    pub effective_field_binding_basis: EffectiveFieldBindingBasis,
    pub composition_verification_ref: CompositionVerificationRef,
    pub active_field_projection: ActiveFieldProjection,
    pub active_field_requirements: Vec<ActiveFieldRequirement>,
    pub ordered_operations: Vec<ExecutionOperation>,
    pub execution_basis_semantic_payload: Value,
    pub execution_basis_semantic_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum QualifyAndCompileExecutionResult {
    Qualified(Box<QualifiedExecutionCompilation>),
    Blocked(ExecutionQualificationBlocked),
    ContextError(ExecutionCompilationContextError),
}
fn context(code: &str, detail: impl Into<String>) -> QualifyAndCompileExecutionResult {
    QualifyAndCompileExecutionResult::ContextError(ExecutionCompilationContextError::new(
        code, detail,
    ))
}

pub fn active_binding_digest(
    rules: &[EffectiveFieldBindingRule],
) -> Result<String, ExecutionCompilationError> {
    let mut payload:Vec<_>=rules.iter().map(|r|json!({"field_id":r.field_id,
        "binding_kind":r.binding_kind,"value_expression":encode_value_expression(&r.value_expression)})).collect();
    payload.sort_by(|a, b| a["field_id"].as_str().cmp(&b["field_id"].as_str()));
    canonical_execution_digest(&json!(payload))
        .map_err(|e| ExecutionCompilationError(e.to_string()))
}
pub fn required_source_key_set_digest(
    keys: &[String],
) -> Result<String, ExecutionCompilationError> {
    let mut keys = keys.to_vec();
    keys.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    canonical_execution_digest(&json!(keys)).map_err(|e| ExecutionCompilationError(e.to_string()))
}
pub fn project_active_fields(
    structure: &ExecutionTemplateStructure,
    selected: &HashSet<(String, String)>,
) -> (ActiveFieldProjection, HashMap<String, usize>) {
    let mut active: Vec<&FieldOccurrence> = structure
        .field_occurrences
        .iter()
        .filter(|occ| {
            occ.owner_kind == "ROOT"
                || occ.owner_kind == "SLOT_SHARED"
                || selected.contains(&(
                    occ.owner_slot_id.clone().unwrap_or_default(),
                    occ.owner_option_id.clone().unwrap_or_default(),
                ))
        })
        .collect();
    active.sort_by_key(|occ| occ.structural_order);
    let sequence: Vec<String> = active.iter().map(|occ| occ.field_id.clone()).collect();
    let mut logical = Vec::new();
    let mut seen = HashSet::new();
    let mut counts = HashMap::new();
    for field in &sequence {
        *counts.entry(field.clone()).or_insert(0) += 1;
        if seen.insert(field.clone()) {
            logical.push(field.clone());
        }
    }
    (
        ActiveFieldProjection {
            active_field_sequence: sequence,
            active_logical_field_order: logical,
        },
        counts,
    )
}
pub fn verify_requirement_operation_bijection(
    requirements: &[ActiveFieldRequirement],
    ops: &[ExecutionOperation],
) -> Result<(), ExecutionCompilationError> {
    let req: Vec<_> = requirements.iter().map(|r| r.field_id.as_str()).collect();
    let apply: Vec<_> = ops
        .iter()
        .filter_map(|op| match op {
            ExecutionOperation::ApplyFieldBinding { field_id } => Some(field_id.as_str()),
            _ => None,
        })
        .collect();
    if req.iter().collect::<HashSet<_>>().len() != req.len() {
        return Err(ExecutionCompilationError("requirement field 중복".into()));
    }
    if apply.iter().collect::<HashSet<_>>().len() != apply.len() {
        return Err(ExecutionCompilationError(
            "ApplyFieldBinding field 중복".into(),
        ));
    }
    if req != apply {
        return Err(ExecutionCompilationError(
            "requirement ↔ ApplyFieldBinding bijection 위반(집합·순서 불일치)".into(),
        ));
    }
    Ok(())
}

fn blocker_priority(code: &str) -> usize {
    [
        ACTIVE_FIELD_UNBOUND,
        "ACTIVE_FIELD_BINDING_AMBIGUOUS",
        "ACTIVE_FIELD_BINDING_CONFLICT",
        REQUIRED_SOURCE_KEY_MISSING,
        "UNSUPPORTED_FIELD_BINDING_RULE",
        "UNSUPPORTED_DOCUMENT_VALUE_POLICY",
        SLOT_CONFIGURATION_INCOMPLETE,
        "NEEDS_CONFIGURATION_REVIEW",
        "NEEDS_CONFIGURATION",
    ]
    .iter()
    .position(|item| *item == code)
    .unwrap_or(9)
}
fn normalize_blockers(blockers: Vec<QualificationBlocker>) -> Vec<QualificationBlocker> {
    let mut seen = HashSet::new();
    let mut unique: Vec<_> = blockers
        .into_iter()
        .filter(|b| seen.insert((b.code.clone(), b.field_id.clone())))
        .collect();
    unique.sort_by(|a, b| {
        blocker_priority(&a.code)
            .cmp(&blocker_priority(&b.code))
            .then(
                a.field_id
                    .as_deref()
                    .unwrap_or("")
                    .cmp(b.field_id.as_deref().unwrap_or("")),
            )
            .then(a.detail.cmp(&b.detail))
    });
    unique
}
type SelectionResolution = (HashSet<(String, String)>, Vec<QualificationBlocker>);
fn resolve_selected(
    structure: &ExecutionTemplateStructure,
    selection: &SlotSelectionInput,
) -> Result<SelectionResolution, ExecutionCompilationContextError> {
    let SlotSelectionInput::Slotted(selection) = selection else {
        return Ok((HashSet::new(), vec![]));
    };
    let slot_ids: HashSet<_> = structure
        .product_structure
        .slots
        .iter()
        .map(|slot| slot.id.as_str())
        .collect();
    let option_ids: HashSet<_> = structure
        .product_structure
        .slots
        .iter()
        .flat_map(|slot| {
            slot.options
                .iter()
                .map(|opt| (slot.id.as_str(), opt.id.as_str()))
        })
        .collect();
    let mut selected_by_slot = HashMap::new();
    for sel in &selection.effective_selections.selections {
        if !slot_ids.contains(sel.slot_id.as_str()) {
            return Err(ExecutionCompilationContextError {
                code: UNKNOWN_SELECTION_TARGET.into(),
                detail: format!(
                    "selection 이 Structure 밖 Slot 을 참조: {}",
                    repr(&sel.slot_id)
                ),
            });
        }
        for option in &sel.selected_option_ids {
            if !option_ids.contains(&(sel.slot_id.as_str(), option.as_str())) {
                return Err(ExecutionCompilationContextError {
                    code: UNKNOWN_SELECTION_TARGET.into(),
                    detail: format!(
                        "selection 이 Structure 밖 Option 을 참조: ({}, {})",
                        repr(&sel.slot_id),
                        repr(option)
                    ),
                });
            }
        }
        selected_by_slot.insert(sel.slot_id.as_str(), &sel.selected_option_ids);
    }
    let mut selected = HashSet::new();
    let mut blockers = Vec::new();
    for slot in &structure.product_structure.slots {
        match selected_by_slot.get(slot.id.as_str()) {
            Some(options) if options.len() == 1 => {
                selected.insert((slot.id.clone(), options[0].clone()));
            }
            _ => blockers.push(QualificationBlocker {
                code: SLOT_CONFIGURATION_INCOMPLETE.into(),
                field_id: None,
                detail: format!(
                    "Slot {} 에 selected Option 이 정확히 하나가 아니다",
                    repr(&slot.id)
                ),
            }),
        }
    }
    Ok((selected, blockers))
}
fn semantic_payload(
    captured: &CapturedExecutionInput,
    slot_mode: &str,
    selected: &[(String, String)],
    basis: &EffectiveFieldBindingBasis,
    requirements: &[ActiveFieldRequirement],
    ops: &[ExecutionOperation],
    proof: &CompositionVerificationRef,
) -> Value {
    let applied = &captured.template.applied;
    let qual = &captured.template.qualification;
    let policy = &captured.resolved_seal_policy;
    let mut rules: Vec<_> = basis
        .effective_active_binding_rules
        .iter()
        .map(|r| {
            json!({"field_id":r.field_id,"binding_kind":r.binding_kind,
            "value_expression":encode_value_expression(&r.value_expression)})
        })
        .collect();
    rules.sort_by(|a, b| a["field_id"].as_str().cmp(&b["field_id"].as_str()));
    let mut requirements:Vec<_>=requirements.iter().map(|r|
        json!({"field_id":r.field_id,"expected_active_occurrence_count":r.expected_active_occurrence_count,
            "value_expression":encode_value_expression(&r.value_expression)})).collect();
    requirements.sort_by(|a, b| a["field_id"].as_str().cmp(&b["field_id"].as_str()));
    let selections: Vec<_> = selected
        .iter()
        .map(|(slot, option)| json!({"slot_id":slot,"selected_option_id":option}))
        .collect();
    json!({
        "execution_semantics_contract":EXECUTION_SEMANTICS_CONTRACT,
        "operation_alphabet_version":OPERATION_ALPHABET_VERSION,
        "exact_template_execution_basis":{
            "execution_base_kind":policy.execution_base_kind,
            "materialization_base_contract_id":policy.materialization_base_contract_id,
            "work_authority_id":captured.work_authority_id,
            "template_application_id":applied.template_application_id,
            "template_lineage_id":applied.template_lineage_id,
            "revision_id":applied.revision_id,"media":applied.media,
            "exact_content_digest":applied.exact_content_digest,
            "pass_evidence_id":qual.pass_evidence_id,
            "qualification_profile_id":qual.qualification_profile_id,
            "structure_projection_schema_version":qual.structure_projection_schema_version,
            "template_structure_digest":qual.template_structure_digest,
        },
        "effective_selection":{"slot_mode":slot_mode,"selections":selections},
        "effective_field_binding":{
            "active_binding_digest":basis.active_binding_digest,
            "required_source_keys":basis.required_source_keys,
            "required_source_key_set_digest":basis.required_source_key_set_digest,
            "active_binding_rules":rules,
        },
        "active_field_requirements":requirements,
        "ordered_operations":ops.iter().map(encode_operation).collect::<Vec<_>>(),
        "composition_verification_ref":{
            "composition_contract_id":proof.composition_contract_id,
            "native_primitive_contract_id":proof.native_primitive_contract_id,
            "template_structure_digest":proof.template_structure_digest,
            "theorem_evidence_manifest_digest":proof.theorem_evidence_manifest_digest,
            "premise_verification_digest":proof.premise_verification_digest,
        }
    })
}
fn verify_composition_binding<'a>(
    captured: &CapturedExecutionInput,
    composition: &'a CompositionPremiseVerificationResult,
) -> Result<&'a CompositionPremisesPassed, ExecutionCompilationContextError> {
    let structure_digest = &captured.template.qualification.template_structure_digest;
    let proof = match composition {
        CompositionPremiseVerificationResult::Passed(proof) => proof,
        CompositionPremiseVerificationResult::Blocked(block) => {
            return Err(ExecutionCompilationContextError::new(
                COMPOSITION_PREMISES_NOT_PASSED,
                format!(
                    "composition premise 미증명(CompositionPremisesBlocked, premise={}): {}",
                    block.premise_id, block.reason
                ),
            ));
        }
        CompositionPremiseVerificationResult::ContextError(error) => {
            return Err(ExecutionCompilationContextError::new(
                COMPOSITION_PREMISES_NOT_PASSED,
                format!(
                    "composition premise 미증명(CompositionPremiseContextError, premise={}): {}",
                    error.premise_id.as_deref().unwrap_or("None"),
                    error.reason
                ),
            ));
        }
    };
    if proof.template_structure_digest != *structure_digest {
        return Err(ExecutionCompilationContextError::new(
            COMPOSITION_STRUCTURE_MISMATCH,
            "composition premise 가 이 template structure 와 다른 digest 에 결속됨",
        ));
    }
    let policy = &captured.resolved_seal_policy;
    if proof.composition_contract_id != policy.composition_contract_id
        || proof.native_primitive_contract_id != policy.native_primitive_contract_id
        || proof.theorem_evidence_manifest_digest
            != policy.composition_theorem_evidence_manifest_digest
    {
        return Err(ExecutionCompilationContextError::new(
            COMPOSITION_POLICY_IDENTITY_MISMATCH,
            "composition proof 의 contract/native-primitive/fingerprint identity 가 admitted resolved_seal_policy 와 불일치",
        ));
    }
    Ok(proof)
}

fn verified_selection_basis(
    captured: &CapturedExecutionInput,
) -> Result<EffectiveSelectionBasis, ExecutionCompilationContextError> {
    let structure = &captured.template.qualification.execution_structure;
    let structure_digest = &captured.template.qualification.template_structure_digest;
    let selection_basis = match project_effective_selection(&captured.selection) {
        Ok(basis) => basis,
        Err(error) => {
            return Err(ExecutionCompilationContextError::new(
                SELECTION_CONTRACT_INTEGRITY_ERROR,
                error.0,
            ));
        }
    };
    if selection_basis.template_structure_digest != *structure_digest {
        return Err(ExecutionCompilationContextError::new(
            SELECTION_STRUCTURE_DIGEST_MISMATCH,
            "selection 의 template_structure_digest 가 qualification structure 와 불일치",
        ));
    }
    let has_slots = !structure.product_structure.slots.is_empty();
    if has_slots && matches!(captured.selection, SlotSelectionInput::Slotless(_)) {
        return Err(ExecutionCompilationContextError::new(
            SLOT_MODE_MISMATCH,
            "SLOTLESS selection 이 slot 있는 structure 와 결합됨",
        ));
    }
    if !has_slots && matches!(captured.selection, SlotSelectionInput::Slotted(_)) {
        return Err(ExecutionCompilationContextError::new(
            SLOT_MODE_MISMATCH,
            "SLOTTED selection 이 slot 0 structure 와 결합됨",
        ));
    }
    Ok(selection_basis)
}

struct FieldQualification {
    requirements: Vec<ActiveFieldRequirement>,
    effective_rules: Vec<EffectiveFieldBindingRule>,
    required_keys: HashSet<String>,
    blockers: Vec<QualificationBlocker>,
}

fn qualify_active_fields(
    captured: &CapturedExecutionInput,
    projection: &ActiveFieldProjection,
    counts: &HashMap<String, usize>,
    slot_blockers: Vec<QualificationBlocker>,
) -> FieldQualification {
    let rules_by_field: HashMap<_, _> = captured
        .field_binding
        .binding_rules
        .iter()
        .map(|r| (r.field_id.as_str(), r))
        .collect();
    let schema_keys: HashSet<_> = captured
        .field_binding
        .source_schema_keys
        .iter()
        .map(String::as_str)
        .collect();
    let mut requirements = Vec::new();
    let mut effective_rules = Vec::new();
    let mut required_keys = HashSet::new();
    let mut blockers = slot_blockers;
    for field in &projection.active_logical_field_order {
        let Some(rule) = rules_by_field.get(field.as_str()) else {
            blockers.push(QualificationBlocker {
                code: ACTIVE_FIELD_UNBOUND.into(),
                field_id: Some(field.clone()),
                detail: format!("Active Field {} 에 effective binding 이 없다", repr(field)),
            });
            continue;
        };
        let value = value_expression(rule);
        if let ActiveFieldValueExpression::FromSource { source_key, .. } = &value {
            if !schema_keys.contains(source_key.as_str()) {
                blockers.push(QualificationBlocker {
                    code: REQUIRED_SOURCE_KEY_MISSING.into(),
                    field_id: Some(field.clone()),
                    detail: format!("source_key {} 가 source schema 에 없다", repr(source_key)),
                });
                continue;
            }
            required_keys.insert(source_key.clone());
        }
        requirements.push(ActiveFieldRequirement {
            field_id: field.clone(),
            expected_active_occurrence_count: counts[field],
            value_expression: value.clone(),
        });
        effective_rules.push(EffectiveFieldBindingRule {
            field_id: field.clone(),
            binding_kind: rule.binding_kind.clone(),
            value_expression: value,
        });
    }
    FieldQualification {
        requirements,
        effective_rules,
        required_keys,
        blockers,
    }
}

fn ordered_operations(
    structure: &ExecutionTemplateStructure,
    selected: &HashSet<(String, String)>,
    projection: &ActiveFieldProjection,
) -> Vec<ExecutionOperation> {
    let slot_index: HashMap<_, _> = structure
        .product_structure
        .slots
        .iter()
        .enumerate()
        .map(|(i, slot)| (slot.id.as_str(), i))
        .collect();
    let option_index: HashMap<_, _> = structure
        .product_structure
        .slots
        .iter()
        .flat_map(|slot| {
            slot.options
                .iter()
                .enumerate()
                .map(|(i, opt)| ((slot.id.as_str(), opt.id.as_str()), i))
        })
        .collect();
    let mut removed: Vec<_> = structure
        .option_regions
        .iter()
        .filter(|r| !selected.contains(&(r.slot_id.clone(), r.option_id.clone())))
        .collect();
    removed.sort_by_key(|r| {
        (
            slot_index[&r.slot_id.as_str()],
            option_index[&(r.slot_id.as_str(), r.option_id.as_str())],
        )
    });
    let mut ops: Vec<_> = removed
        .iter()
        .map(|r| ExecutionOperation::RemoveOption {
            slot_id: r.slot_id.clone(),
            option_id: r.option_id.clone(),
        })
        .collect();
    ops.extend(projection.active_logical_field_order.iter().map(|field| {
        ExecutionOperation::ApplyFieldBinding {
            field_id: field.clone(),
        }
    }));
    ops
}

pub fn qualify_and_compile_execution(
    captured: &CapturedExecutionInput,
    composition: &CompositionPremiseVerificationResult,
) -> QualifyAndCompileExecutionResult {
    let structure = &captured.template.qualification.execution_structure;
    let proof = match verify_composition_binding(captured, composition) {
        Ok(proof) => proof,
        Err(error) => return QualifyAndCompileExecutionResult::ContextError(error),
    };
    let selection_basis = match verified_selection_basis(captured) {
        Ok(basis) => basis,
        Err(error) => return QualifyAndCompileExecutionResult::ContextError(error),
    };
    let (selected, slot_blockers) = match resolve_selected(structure, &captured.selection) {
        Ok(result) => result,
        Err(error) => return QualifyAndCompileExecutionResult::ContextError(error),
    };
    let (projection, counts) = project_active_fields(structure, &selected);
    let fields = qualify_active_fields(captured, &projection, &counts, slot_blockers);
    if !fields.blockers.is_empty() {
        return QualifyAndCompileExecutionResult::Blocked(ExecutionQualificationBlocked {
            normalized_blockers: normalize_blockers(fields.blockers),
        });
    }
    compile_qualified(
        captured,
        proof,
        selection_basis,
        selected,
        projection,
        fields,
    )
}

fn compile_qualified(
    captured: &CapturedExecutionInput,
    proof: &CompositionPremisesPassed,
    selection_basis: EffectiveSelectionBasis,
    selected: HashSet<(String, String)>,
    projection: ActiveFieldProjection,
    fields: FieldQualification,
) -> QualifyAndCompileExecutionResult {
    let structure = &captured.template.qualification.execution_structure;
    let policy = &captured.resolved_seal_policy;
    let FieldQualification {
        requirements,
        effective_rules,
        required_keys,
        ..
    } = fields;
    let ops = ordered_operations(structure, &selected, &projection);
    if let Err(error) = verify_requirement_operation_bijection(&requirements, &ops) {
        return context(SELECTION_CONTRACT_INTEGRITY_ERROR, error.0);
    }
    let mut required_source_keys: Vec<_> = required_keys.into_iter().collect();
    required_source_keys.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    let active_digest = match active_binding_digest(&effective_rules) {
        Ok(value) => value,
        Err(error) => return context(SELECTION_CONTRACT_INTEGRITY_ERROR, error.0),
    };
    let source_digest = match required_source_key_set_digest(&required_source_keys) {
        Ok(value) => value,
        Err(error) => return context(SELECTION_CONTRACT_INTEGRITY_ERROR, error.0),
    };
    let binding_basis = EffectiveFieldBindingBasis {
        effective_active_binding_rules: effective_rules,
        active_binding_digest: active_digest,
        required_source_keys,
        required_source_key_set_digest: source_digest,
    };
    let proof_ref = CompositionVerificationRef {
        composition_contract_id: proof.composition_contract_id.clone(),
        native_primitive_contract_id: proof.native_primitive_contract_id.clone(),
        template_structure_digest: proof.template_structure_digest.clone(),
        theorem_evidence_manifest_digest: proof.theorem_evidence_manifest_digest.clone(),
        premise_verification_digest: proof.premise_verification_digest.clone(),
    };
    let mut selected_pairs: Vec<_> = selected.into_iter().collect();
    selected_pairs.sort();
    let payload = semantic_payload(
        captured,
        &selection_basis.slot_mode,
        &selected_pairs,
        &binding_basis,
        &requirements,
        &ops,
        &proof_ref,
    );
    let digest = match canonical_execution_digest(&payload) {
        Ok(value) => value,
        Err(error) => return context(SELECTION_CONTRACT_INTEGRITY_ERROR, error.to_string()),
    };
    let exact = match build_exact_execution_basis(&captured.template, policy) {
        Ok(value) => value,
        Err(error) => return context(SELECTION_CONTRACT_INTEGRITY_ERROR, error.0),
    };
    QualifyAndCompileExecutionResult::Qualified(Box::new(QualifiedExecutionCompilation {
        exact_template_execution_basis: exact,
        effective_selection_basis: selection_basis,
        effective_field_binding_basis: binding_basis,
        composition_verification_ref: proof_ref,
        active_field_projection: projection,
        active_field_requirements: requirements,
        ordered_operations: ops,
        execution_basis_semantic_payload: payload,
        execution_basis_semantic_digest: digest,
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::execution_capture::{
        APPLIED_TEMPLATE_CANDIDATE, CapturedTemplateExecutionInput,
        ExactTemplateQualificationContext, MATERIALIZATION_BASE_CONTRACT_ID,
        QualificationProfileSemanticPayload, ResolvedSealPolicy,
    };
    use crate::execution_composition::{
        COMPOSITION_CONTRACT_ID, COMPOSITION_FINGERPRINT_HWPX, CompositionPremiseContextError,
        CompositionPremisesBlocked, NATIVE_PRIMITIVE_CONTRACT_ID, admit_composition_premises,
        resolve_native_primitive_contract,
    };
    use crate::execution_structure::{decode_execution_structure, template_structure_digest};
    use crate::field_binding::{ExactText, INTENTIONAL_BLANK, resolve_document_value_policy};
    use crate::field_binding_input::build_field_binding_input;
    use crate::slot_configuration_context::ExactAppliedTemplateInput;
    use crate::slot_selection::{SlotSelection, SlotSelectionSet, digest_selection_set};
    use crate::slot_selection_input::{SlotConfigurationSnapshot, SlotlessSelectionContext};

    const AT: &str = "2026-08-16T00:00:00Z";
    pub(crate) fn fixtures() -> Value {
        serde_json::from_str(include_str!(
            "../../../tests/fixtures/execution_compilation.json"
        ))
        .unwrap()
    }
    fn rules() -> Vec<FieldBindingRule> {
        [
            ("성명", SOURCE, Some("이름"), None, Some("")),
            ("주소", CONSTANT, None, Some("서울"), None),
            ("항목", INTENTIONAL_BLANK, None, None, None),
            ("금액", SOURCE, Some("금액열"), None, None),
        ]
        .into_iter()
        .map(|(field, kind, source, constant, format)| FieldBindingRule {
            field_id: field.into(),
            binding_kind: kind.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: source.map(str::to_owned),
            canonical_constant_value: constant.map(ExactText::new),
            format_code: format.map(str::to_owned),
            format_kind: None,
            text_slice: None,
        })
        .collect()
    }
    pub(crate) fn captured(
        structure: ExecutionTemplateStructure,
        selected: &[(&str, &str)],
    ) -> CapturedExecutionInput {
        let digest = template_structure_digest(&structure);
        let schema = structure.projection_schema_version.clone();
        let selections = SlotSelectionSet::new(
            selected
                .iter()
                .map(|(s, o)| SlotSelection::new(*s, vec![(*o).into()]).unwrap())
                .collect(),
        )
        .unwrap();
        let selection = if structure.product_structure.slots.is_empty() {
            SlotSelectionInput::Slotless(SlotlessSelectionContext {
                work_id: "work-1".into(),
                template_application_id: "app-1".into(),
                selection_semantic_contract_id: "slot-selection/v1".into(),
                structure_projection_schema_version: schema.clone(),
                template_structure_digest: digest.clone(),
                source_configuration_version: None,
                declared_selection_digest: None,
                captured_at: AT.into(),
            })
        } else {
            let selection_digest = digest_selection_set("slot-selection/v1", &selections).unwrap();
            SlotSelectionInput::Slotted(SlotConfigurationSnapshot {
                work_id: "work-1".into(),
                template_application_id: "app-1".into(),
                source_configuration_version: 3,
                selection_semantic_contract_id: "slot-selection/v1".into(),
                structure_projection_schema_version: schema.clone(),
                template_structure_digest: digest.clone(),
                effective_selections: selections,
                effective_selection_digest: selection_digest.clone(),
                declared_selection_digest: selection_digest,
                captured_at: AT.into(),
            })
        };
        CapturedExecutionInput {
            workspace_instance_id: "ws-1".into(),
            work_authority_id: "work-1".into(),
            template: CapturedTemplateExecutionInput {
                workspace_instance_id: "ws-1".into(),
                work_authority_id: "work-1".into(),
                applied: ExactAppliedTemplateInput {
                    work_id: "work-1".into(),
                    template_application_id: "app-1".into(),
                    revision_id: "rev-1".into(),
                    media: "hwpx".into(),
                    template_lineage_id: "lin-1".into(),
                    exact_content_digest: "sha256:cccc".into(),
                    canonical_blob_reference: "blob://x".into(),
                },
                qualification: ExactTemplateQualificationContext {
                    pass_evidence_id: "ev-1".into(),
                    qualification_profile_id: "hwpx-template-qualification-v2".into(),
                    qualification_profile_semantic_payload: QualificationProfileSemanticPayload {
                        qualification_profile_id: "hwpx-template-qualification-v2".into(),
                        media: "hwpx".into(),
                        adapter_contract_version: "a/1".into(),
                        product_rule_version: "p/1".into(),
                        operation_alphabet_version: "o/1".into(),
                        projection_schema_version: schema.clone(),
                        manifest_payload: json!({"k":"v"}),
                    },
                    structure_projection_schema_version: schema,
                    template_structure_digest: digest,
                    execution_structure: structure,
                    composition_profile_state: "SEALED".into(),
                    revision_id: "rev-1".into(),
                    qualification_profile_semantic_digest: None,
                },
                captured_at: AT.into(),
            },
            selection,
            field_binding: build_field_binding_input(
                "ws-1",
                "work-1",
                "app-1",
                rules(),
                vec!["이름".into(), "금액열".into(), "unused".into()],
                "rr/1",
                AT,
            )
            .unwrap(),
            resolved_seal_policy: ResolvedSealPolicy {
                policy_resolution_version: "pol/1".into(),
                execution_base_kind: APPLIED_TEMPLATE_CANDIDATE.into(),
                execution_semantic_contract_id: "exec/1".into(),
                binding_value_contract_id: "bind/1".into(),
                raw_record_contract_id: "rr/1".into(),
                document_value_resolution_contract_id: "dvr/1".into(),
                record_validation_contract_id: "rv/1".into(),
                record_review_contract_id: "review/1".into(),
                composition_contract_id: COMPOSITION_CONTRACT_ID.into(),
                native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID.into(),
                materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
                composition_theorem_evidence_manifest_digest: COMPOSITION_FINGERPRINT_HWPX.into(),
                materialization_contract_id: "mat/1".into(),
                plan_schema_version: "plan/1".into(),
                canonical_encoding_version: "enc/1".into(),
            },
            captured_execution_input_semantic_projection: json!({}),
            captured_at: AT.into(),
            captured_execution_input_digest: String::new(),
        }
    }
    fn proof(captured: &CapturedExecutionInput) -> CompositionPremiseVerificationResult {
        admit_composition_premises(
            &captured.template.qualification.execution_structure,
            &resolve_native_primitive_contract(NATIVE_PRIMITIVE_CONTRACT_ID).unwrap(),
            COMPOSITION_CONTRACT_ID,
        )
    }
    fn compile(captured: &CapturedExecutionInput) -> QualifiedExecutionCompilation {
        let result = qualify_and_compile_execution(captured, &proof(captured));
        let QualifyAndCompileExecutionResult::Qualified(result) = result else {
            panic!("{result:?}")
        };
        *result
    }

    #[test]
    fn complete_compilation_matches_independent_payloads_digests_and_field_order() {
        let fixtures = fixtures();
        for (name, structure_name, selected) in [
            ("normal", "normal", vec![("s1", "o1")]),
            ("selected_o2", "normal", vec![("s1", "o2")]),
            ("slotless", "slotless", vec![]),
            ("two_slots", "two_slots", vec![("sA", "a1"), ("sB", "b1")]),
            ("active_change", "normal", vec![("s1", "o1")]),
        ] {
            let mut input = captured(
                decode_execution_structure(&fixtures["structures"][structure_name]).unwrap(),
                &selected,
            );
            if name == "active_change" {
                input
                    .field_binding
                    .binding_rules
                    .iter_mut()
                    .find(|r| r.field_id == "성명")
                    .unwrap()
                    .source_key = Some("금액열".into());
            }
            let result = compile(&input);
            let expected = &fixtures["qualified"][name];
            assert_eq!(
                result.execution_basis_semantic_payload, expected["payload"],
                "{name}"
            );
            assert_eq!(
                result.execution_basis_semantic_digest,
                expected["digest"].as_str().unwrap(),
                "{name}"
            );
            assert_eq!(
                json!(result.active_field_projection.active_field_sequence),
                expected["active_field_sequence"]
            );
            assert_eq!(
                json!(result.active_field_projection.active_logical_field_order),
                expected["active_logical_field_order"]
            );
            verify_requirement_operation_bijection(
                &result.active_field_requirements,
                &result.ordered_operations,
            )
            .unwrap();
            let before = result.execution_basis_semantic_payload.clone();
            input
                .template
                .qualification
                .execution_structure
                .field_occurrences
                .clear();
            assert_eq!(result.execution_basis_semantic_payload, before);
        }
    }

    #[test]
    fn proof_selection_and_mode_mismatches_never_produce_operations() {
        let fixtures = fixtures();
        let original = captured(
            decode_execution_structure(&fixtures["structures"]["normal"]).unwrap(),
            &[("s1", "o1")],
        );
        for (axis, expected) in [
            ("composition", COMPOSITION_POLICY_IDENTITY_MISMATCH),
            ("primitive", COMPOSITION_POLICY_IDENTITY_MISMATCH),
            ("theorem", COMPOSITION_POLICY_IDENTITY_MISMATCH),
            ("proof_structure", COMPOSITION_STRUCTURE_MISMATCH),
            ("selection_structure", SELECTION_STRUCTURE_DIGEST_MISMATCH),
            ("selection_digest", SELECTION_CONTRACT_INTEGRITY_ERROR),
            ("slot", UNKNOWN_SELECTION_TARGET),
            ("option", UNKNOWN_SELECTION_TARGET),
            ("slotless_mode", SLOT_MODE_MISMATCH),
            ("slotted_mode", SLOT_MODE_MISMATCH),
            ("blocked", COMPOSITION_PREMISES_NOT_PASSED),
            ("context", COMPOSITION_PREMISES_NOT_PASSED),
        ] {
            let mut input = original.clone();
            let mut composition = proof(&input);
            match axis {
                "composition" => {
                    input.resolved_seal_policy.composition_contract_id = "other".into()
                }
                "primitive" => {
                    input.resolved_seal_policy.native_primitive_contract_id = "other".into()
                }
                "theorem" => {
                    input
                        .resolved_seal_policy
                        .composition_theorem_evidence_manifest_digest = "other".into()
                }
                "proof_structure" => {
                    if let CompositionPremiseVerificationResult::Passed(ref mut p) = composition {
                        p.template_structure_digest = "other".into();
                    }
                }
                "blocked" => {
                    composition =
                        CompositionPremiseVerificationResult::Blocked(CompositionPremisesBlocked {
                            code: "FAILED".into(),
                            premise_id: "C1".into(),
                            reason: "same span".into(),
                        })
                }
                "context" => {
                    composition = CompositionPremiseVerificationResult::ContextError(
                        CompositionPremiseContextError {
                            code: "UNKNOWN".into(),
                            premise_id: Some("C3".into()),
                            reason: "missing fact".into(),
                        },
                    )
                }
                "slotless_mode" => {
                    let mut slotless = captured(
                        decode_execution_structure(&fixtures["structures"]["slotless"]).unwrap(),
                        &[],
                    );
                    if let SlotSelectionInput::Slotless(ref mut s) = slotless.selection {
                        s.template_structure_digest = input
                            .template
                            .qualification
                            .template_structure_digest
                            .clone();
                    }
                    input.selection = slotless.selection;
                }
                "slotted_mode" => {
                    input.template = captured(
                        decode_execution_structure(&fixtures["structures"]["slotless"]).unwrap(),
                        &[],
                    )
                    .template;
                    if let SlotSelectionInput::Slotted(ref mut s) = input.selection {
                        s.template_structure_digest = input
                            .template
                            .qualification
                            .template_structure_digest
                            .clone();
                    }
                    composition = proof(&input);
                }
                _ => {
                    if let SlotSelectionInput::Slotted(ref mut s) = input.selection {
                        match axis {
                            "selection_structure" => s.template_structure_digest = "other".into(),
                            "selection_digest" => s.effective_selection_digest = "other".into(),
                            "slot" | "option" => {
                                if axis == "slot" {
                                    s.effective_selections.selections[0].slot_id = "other".into();
                                } else {
                                    s.effective_selections.selections[0].selected_option_ids =
                                        vec!["other".into()];
                                }
                                s.effective_selection_digest = digest_selection_set(
                                    "slot-selection/v1",
                                    &s.effective_selections,
                                )
                                .unwrap();
                            }
                            _ => unreachable!(),
                        }
                    }
                }
            }
            let result = qualify_and_compile_execution(&input, &composition);
            let QualifyAndCompileExecutionResult::ContextError(error) = result else {
                panic!("{axis}: {result:?}")
            };
            assert_eq!(error.code, expected, "{axis}");
        }
    }

    #[test]
    fn incomplete_slots_or_active_bindings_block_but_inactive_changes_do_not_change_basis() {
        let fixtures = fixtures();
        let original = captured(
            decode_execution_structure(&fixtures["structures"]["normal"]).unwrap(),
            &[("s1", "o1")],
        );
        let baseline = compile(&original);
        for axis in ["detached", "version", "unused_key", "inactive", "order"] {
            let mut input = original.clone();
            match axis {
                "detached" | "version" => {
                    if let SlotSelectionInput::Slotted(ref mut s) = input.selection {
                        if axis == "detached" {
                            s.declared_selection_digest = "sha256:other-declarations".into();
                        } else {
                            s.source_configuration_version += 99;
                        }
                    }
                }
                "unused_key" => input.field_binding.source_schema_keys.push("extra".into()),
                "inactive" => {
                    input
                        .field_binding
                        .binding_rules
                        .iter_mut()
                        .find(|r| r.field_id == "금액")
                        .unwrap()
                        .source_key = Some("missing-inactive-key".into())
                }
                "order" => {
                    input.field_binding.binding_rules.reverse();
                    input.field_binding.source_schema_keys.reverse();
                }
                _ => unreachable!(),
            }
            let result = compile(&input);
            assert_eq!(
                result.execution_basis_semantic_digest, baseline.execution_basis_semantic_digest,
                "{axis}"
            );
            assert_eq!(result.ordered_operations, baseline.ordered_operations);
        }
        for (axis, expected) in [
            ("slot", SLOT_CONFIGURATION_INCOMPLETE),
            ("binding", ACTIVE_FIELD_UNBOUND),
            ("source", REQUIRED_SOURCE_KEY_MISSING),
        ] {
            let mut input = original.clone();
            match axis {
                "slot" => {
                    if let SlotSelectionInput::Slotted(ref mut s) = input.selection {
                        s.effective_selections = SlotSelectionSet::default();
                        s.effective_selection_digest =
                            digest_selection_set("slot-selection/v1", &s.effective_selections)
                                .unwrap();
                    }
                }
                "binding" => input
                    .field_binding
                    .binding_rules
                    .retain(|r| r.field_id != "주소"),
                "source" => input
                    .field_binding
                    .source_schema_keys
                    .retain(|key| key != "이름"),
                _ => unreachable!(),
            }
            let result = qualify_and_compile_execution(&input, &proof(&input));
            let QualifyAndCompileExecutionResult::Blocked(blocked) = result else {
                panic!("{axis}: {result:?}")
            };
            assert_eq!(blocked.normalized_blockers.len(), 1);
            assert_eq!(blocked.normalized_blockers[0].code, expected);
        }
        let req = baseline.active_field_requirements[0].clone();
        for (reqs, ops) in [
            (
                vec![req.clone()],
                vec![ExecutionOperation::ApplyFieldBinding {
                    field_id: "wrong".into(),
                }],
            ),
            (
                vec![req.clone()],
                vec![
                    ExecutionOperation::ApplyFieldBinding {
                        field_id: req.field_id.clone()
                    };
                    2
                ],
            ),
            (
                vec![req.clone(); 2],
                vec![ExecutionOperation::ApplyFieldBinding {
                    field_id: req.field_id.clone(),
                }],
            ),
        ] {
            assert!(verify_requirement_operation_bijection(&reqs, &ops).is_err());
        }
    }
}
