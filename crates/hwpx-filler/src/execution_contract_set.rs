//! Canonical contract-set and durable capture evidence identity.

use crate::canonical_execution_encoding::canonical_execution_digest;
use crate::execution_capture::QualificationProfileSemanticPayload;
use crate::execution_capture::{EffectiveSelectionBasis, ExactTemplateExecutionBasis};
use crate::execution_compilation::{
    EffectiveFieldBindingBasis, active_binding_digest, encode_value_expression,
    required_source_key_set_digest,
};
use crate::execution_composition::{CompositionErrorKind, composition_fingerprint};
use crate::text_render::python_repr;
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::fmt;

pub const CONTRACT_SET_SCHEMA_VERSION: &str = "execution-contract-set/v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContractSetErrorKind {
    Integrity,
    UnsupportedComposition,
    UnsupportedNativePrimitive,
    QualificationProfileManifestIntegrity,
    DurableCaptureEvidenceIntegrity,
    BasisIntegrity,
    PlanIntegrity,
    UnsupportedPlanSchema,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContractSetError {
    pub kind: ContractSetErrorKind,
    pub detail: String,
}
impl fmt::Display for ContractSetError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for ContractSetError {}
fn fail(kind: ContractSetErrorKind, detail: impl Into<String>) -> ContractSetError {
    ContractSetError {
        kind,
        detail: detail.into(),
    }
}
fn integrity(detail: impl Into<String>) -> ContractSetError {
    fail(ContractSetErrorKind::Integrity, detail)
}
fn evidence_error(detail: impl Into<String>) -> ContractSetError {
    fail(
        ContractSetErrorKind::DurableCaptureEvidenceIntegrity,
        detail,
    )
}
fn basis_error(detail: impl Into<String>) -> ContractSetError {
    fail(ContractSetErrorKind::BasisIntegrity, detail)
}
fn plan_error(detail: impl Into<String>) -> ContractSetError {
    fail(ContractSetErrorKind::PlanIntegrity, detail)
}
fn digest(value: &Value, kind: ContractSetErrorKind) -> Result<String, ContractSetError> {
    canonical_execution_digest(value).map_err(|e| fail(kind, e.to_string()))
}
fn repr(value: &Value) -> String {
    python_repr(value)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContractRoles {
    pub slot_selection_contract_id: String,
    pub field_binding_contract_id: String,
    pub source_schema_contract_id: String,
    pub raw_record_contract_id: String,
    pub execution_semantic_contract_id: String,
    pub binding_value_contract_id: String,
    pub document_value_resolution_contract_id: String,
    pub record_validation_contract_id: String,
    pub record_review_contract_id: String,
    pub composition_contract_id: String,
    pub native_primitive_contract_id: String,
    pub materialization_base_contract_id: String,
    pub materialization_contract_id: String,
    pub composition_theorem_evidence_manifest_digest: String,
}
impl ContractRoles {
    fn pairs(&self) -> [(&'static str, &str); 14] {
        [
            (
                "slot_selection_contract_id",
                &self.slot_selection_contract_id,
            ),
            ("field_binding_contract_id", &self.field_binding_contract_id),
            ("source_schema_contract_id", &self.source_schema_contract_id),
            ("raw_record_contract_id", &self.raw_record_contract_id),
            (
                "execution_semantic_contract_id",
                &self.execution_semantic_contract_id,
            ),
            ("binding_value_contract_id", &self.binding_value_contract_id),
            (
                "document_value_resolution_contract_id",
                &self.document_value_resolution_contract_id,
            ),
            (
                "record_validation_contract_id",
                &self.record_validation_contract_id,
            ),
            ("record_review_contract_id", &self.record_review_contract_id),
            ("composition_contract_id", &self.composition_contract_id),
            (
                "native_primitive_contract_id",
                &self.native_primitive_contract_id,
            ),
            (
                "materialization_base_contract_id",
                &self.materialization_base_contract_id,
            ),
            (
                "materialization_contract_id",
                &self.materialization_contract_id,
            ),
            (
                "composition_theorem_evidence_manifest_digest",
                &self.composition_theorem_evidence_manifest_digest,
            ),
        ]
    }
    fn validate(&self) -> Result<(), ContractSetError> {
        for (name, value) in self.pairs() {
            if value.is_empty() {
                return Err(integrity(format!(
                    "{name} 는 비어 있지 않은 문자열이어야 한다"
                )));
            }
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionContractSet {
    pub roles: ContractRoles,
    pub contract_set_schema_version: String,
    pub contract_set_manifest_digest: String,
}
pub fn encode_execution_contract_set(contracts: &ExecutionContractSet) -> Value {
    let mut payload = Map::new();
    for (name, value) in contracts.roles.pairs() {
        payload.insert(name.into(), Value::String(value.into()));
    }
    payload.insert(
        "contract_set_schema_version".into(),
        Value::String(contracts.contract_set_schema_version.clone()),
    );
    Value::Object(payload)
}
pub fn contract_set_manifest_digest(
    contracts: &ExecutionContractSet,
) -> Result<String, ContractSetError> {
    digest(
        &encode_execution_contract_set(contracts),
        ContractSetErrorKind::Integrity,
    )
}
impl ExecutionContractSet {
    pub fn validate(&self) -> Result<(), ContractSetError> {
        self.roles.validate()?;
        if self.contract_set_schema_version != CONTRACT_SET_SCHEMA_VERSION {
            return Err(integrity(format!(
                "미지원 contract set schema: {}",
                repr(&Value::String(self.contract_set_schema_version.clone()))
            )));
        }
        if contract_set_manifest_digest(self)? != self.contract_set_manifest_digest {
            return Err(integrity(
                "contract_set_manifest_digest 가 canonical recompute 와 불일치",
            ));
        }
        Ok(())
    }
}
pub fn build_execution_contract_set(
    roles: ContractRoles,
) -> Result<ExecutionContractSet, ContractSetError> {
    if roles.materialization_base_contract_id
        != crate::execution_capture::MATERIALIZATION_BASE_CONTRACT_ID
    {
        return Err(integrity(format!(
            "materialization base contract 가 admitted base 가 아니다(latest fallback 없음): {}",
            repr(&Value::String(
                roles.materialization_base_contract_id.clone()
            ))
        )));
    }
    let expected = composition_fingerprint(
        &roles.composition_contract_id,
        &roles.native_primitive_contract_id,
    )
    .map_err(|e| {
        fail(
            match e.kind {
                CompositionErrorKind::UnsupportedComposition => {
                    ContractSetErrorKind::UnsupportedComposition
                }
                CompositionErrorKind::UnsupportedNativePrimitive => {
                    ContractSetErrorKind::UnsupportedNativePrimitive
                }
            },
            e.detail,
        )
    })?;
    if roles.composition_theorem_evidence_manifest_digest != expected {
        return Err(integrity(
            "composition fingerprint 가 supported contract pair 와 불일치",
        ));
    }
    roles.validate()?;
    let mut result = ExecutionContractSet {
        roles,
        contract_set_schema_version: CONTRACT_SET_SCHEMA_VERSION.into(),
        contract_set_manifest_digest: String::new(),
    };
    result.contract_set_manifest_digest = contract_set_manifest_digest(&result)?;
    result.validate()?;
    Ok(result)
}

pub fn encode_qualification_profile_semantic(
    payload: &QualificationProfileSemanticPayload,
) -> Value {
    json!({
        "qualification_profile_id":payload.qualification_profile_id,
        "media":payload.media,
        "adapter_contract_version":payload.adapter_contract_version,
        "product_rule_version":payload.product_rule_version,
        "operation_alphabet_version":payload.operation_alphabet_version,
        "projection_schema_version":payload.projection_schema_version,
        "manifest_payload":payload.manifest_payload,
    })
}
pub fn qualification_profile_semantic_digest(
    payload: &QualificationProfileSemanticPayload,
) -> Result<String, ContractSetError> {
    payload.validate().map_err(|e| {
        fail(
            ContractSetErrorKind::QualificationProfileManifestIntegrity,
            e.0,
        )
    })?;
    digest(
        &encode_qualification_profile_semantic(payload),
        ContractSetErrorKind::QualificationProfileManifestIntegrity,
    )
}
pub fn require_consistent_qualification_profile(
    known: &HashMap<String, String>,
    payload: &QualificationProfileSemanticPayload,
) -> Result<String, ContractSetError> {
    let actual = qualification_profile_semantic_digest(payload)?;
    if known
        .get(&payload.qualification_profile_id)
        .is_some_and(|prior| prior != &actual)
    {
        return Err(fail(
            ContractSetErrorKind::QualificationProfileManifestIntegrity,
            format!(
                "qualification profile {} 의 semantic payload 가 이전 관찰과 불일치(같은 ID 의미 수정 금지)",
                repr(&Value::String(payload.qualification_profile_id.clone()))
            ),
        ));
    }
    Ok(actual)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CaptureEvidenceProvenance {
    pub field_binding_authority_revision: String,
    pub source_configuration_version: String,
    pub captured_at: String,
}
impl CaptureEvidenceProvenance {
    fn validate(&self) -> Result<(), ContractSetError> {
        for (name, value) in [
            (
                "field_binding_authority_revision",
                &self.field_binding_authority_revision,
            ),
            (
                "source_configuration_version",
                &self.source_configuration_version,
            ),
            ("captured_at", &self.captured_at),
        ] {
            if value.is_empty() {
                return Err(evidence_error(format!(
                    "provenance.{name} 는 비어 있지 않은 문자열이어야 한다"
                )));
            }
        }
        Ok(())
    }
    fn encode(&self) -> Value {
        json!({
            "field_binding_authority_revision":self.field_binding_authority_revision,
            "source_configuration_version":self.source_configuration_version,
            "captured_at":self.captured_at,
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DurableSealCaptureEvidence {
    Complete {
        semantic_projection: Value,
        semantic_digest: String,
        provenance: CaptureEvidenceProvenance,
    },
    Attempt {
        semantic_projection: Value,
        semantic_digest: String,
        normalized_blockers: Vec<String>,
        provenance: CaptureEvidenceProvenance,
    },
}
pub fn encode_durable_capture_evidence(
    evidence: &DurableSealCaptureEvidence,
) -> Result<Value, ContractSetError> {
    let (kind, projection, stored, provenance, blockers) = match evidence {
        DurableSealCaptureEvidence::Complete {
            semantic_projection,
            semantic_digest,
            provenance,
        } => (
            "COMPLETE",
            semantic_projection,
            semantic_digest,
            provenance,
            None,
        ),
        DurableSealCaptureEvidence::Attempt {
            semantic_projection,
            semantic_digest,
            normalized_blockers,
            provenance,
        } => (
            "ATTEMPT",
            semantic_projection,
            semantic_digest,
            provenance,
            Some(normalized_blockers),
        ),
    };
    provenance.validate()?;
    if !projection.is_object() {
        return Err(evidence_error("capture evidence 형식 불량"));
    }
    if digest(
        projection,
        ContractSetErrorKind::DurableCaptureEvidenceIntegrity,
    )? != *stored
    {
        return Err(evidence_error(if kind == "COMPLETE" {
            "captured_execution_input_digest 가 semantic projection 과 불일치"
        } else {
            "captured_attempt_digest 가 semantic projection 과 불일치"
        }));
    }
    let mut result = Map::new();
    result.insert("kind".into(), Value::String(kind.into()));
    result.insert("semantic_projection".into(), projection.clone());
    result.insert("semantic_digest".into(), Value::String(stored.clone()));
    result.insert("provenance".into(), provenance.encode());
    if let Some(blockers) = blockers {
        result.insert("normalized_blockers".into(), json!(blockers));
    }
    Ok(Value::Object(result))
}
pub fn decode_durable_capture_evidence(
    value: &Value,
) -> Result<DurableSealCaptureEvidence, ContractSetError> {
    let data = value
        .as_object()
        .ok_or_else(|| evidence_error("capture evidence 가 매핑이 아니다"))?;
    let projection = data
        .get("semantic_projection")
        .filter(|value| value.is_object())
        .ok_or_else(|| evidence_error("capture evidence 형식 불량"))?
        .clone();
    let stored = data
        .get("semantic_digest")
        .and_then(Value::as_str)
        .ok_or_else(|| evidence_error("capture evidence 형식 불량"))?;
    if digest(
        &projection,
        ContractSetErrorKind::DurableCaptureEvidenceIntegrity,
    )? != stored
    {
        return Err(evidence_error("semantic digest 재계산 불일치"));
    }
    let provenance_value = data
        .get("provenance")
        .and_then(Value::as_object)
        .ok_or_else(|| evidence_error("provenance 가 매핑이 아니다"))?;
    let get = |key: &str| -> Result<String, ContractSetError> {
        provenance_value
            .get(key)
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
            .ok_or_else(|| {
                evidence_error(format!(
                    "provenance.{key} 는 비어 있지 않은 문자열이어야 한다"
                ))
            })
    };
    let provenance = CaptureEvidenceProvenance {
        field_binding_authority_revision: get("field_binding_authority_revision")?,
        source_configuration_version: get("source_configuration_version")?,
        captured_at: get("captured_at")?,
    };
    match data.get("kind") {
        Some(Value::String(kind)) if kind == "COMPLETE" => {
            Ok(DurableSealCaptureEvidence::Complete {
                semantic_projection: projection,
                semantic_digest: stored.into(),
                provenance,
            })
        }
        Some(Value::String(kind)) if kind == "ATTEMPT" => {
            let blockers = data
                .get("normalized_blockers")
                .and_then(Value::as_array)
                .ok_or_else(|| evidence_error("normalized_blockers 형식 불량"))?;
            let blockers = blockers
                .iter()
                .map(|blocker| {
                    blocker
                        .as_str()
                        .map(str::to_owned)
                        .ok_or_else(|| evidence_error("normalized_blockers 형식 불량"))
                })
                .collect::<Result<Vec<_>, _>>()?;
            Ok(DurableSealCaptureEvidence::Attempt {
                semantic_projection: projection,
                semantic_digest: stored.into(),
                normalized_blockers: blockers,
                provenance,
            })
        }
        other => Err(evidence_error(format!(
            "미지원 capture evidence kind: {}",
            repr(other.unwrap_or(&Value::Null))
        ))),
    }
}

pub const PLAN_APPLY_FIELD_BINDING: &str = "APPLY_FIELD_BINDING";
pub const PLAN_REMOVE_OPTION: &str = "REMOVE_OPTION";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionBasis {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub qualification_profile_semantic_digest: String,
    pub template: ExactTemplateExecutionBasis,
    pub contracts: ExecutionContractSet,
    pub selection: EffectiveSelectionBasis,
    pub field_binding: EffectiveFieldBindingBasis,
}
pub fn encode_effective_selection(item: &EffectiveSelectionBasis) -> Value {
    json!({"slot_mode":item.slot_mode,
        "selection_semantic_contract_id":item.selection_semantic_contract_id,
        "template_structure_digest":item.template_structure_digest,
        "effective_selection_digest":item.effective_selection_digest})
}
pub fn encode_effective_field_binding(item: &EffectiveFieldBindingBasis) -> Value {
    let mut keys = item.required_source_keys.clone();
    keys.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    json!({"active_binding_digest":item.active_binding_digest,
        "required_source_keys":keys,
        "required_source_key_set_digest":item.required_source_key_set_digest})
}
pub fn encode_execution_basis(basis: &ExecutionBasis) -> Value {
    json!({"workspace_instance_id":basis.workspace_instance_id,
        "work_authority_id":basis.work_authority_id,
        "qualification_profile_semantic_digest":basis.qualification_profile_semantic_digest,
        "template":{
            "execution_base_kind":basis.template.execution_base_kind,
            "materialization_base_contract_id":basis.template.materialization_base_contract_id,
            "work_authority_id":basis.template.work_authority_id,
            "template_application_id":basis.template.template_application_id,
            "exact_content_digest":basis.template.exact_content_digest},
        "contracts":encode_execution_contract_set(&basis.contracts),
        "contract_set_manifest_digest":basis.contracts.contract_set_manifest_digest,
        "selection":encode_effective_selection(&basis.selection),
        "field_binding":encode_effective_field_binding(&basis.field_binding)})
}
pub fn execution_basis_digest(basis: &ExecutionBasis) -> Result<String, ContractSetError> {
    digest(
        &encode_execution_basis(basis),
        ContractSetErrorKind::BasisIntegrity,
    )
}
pub fn verify_execution_basis_integrity(basis: &ExecutionBasis) -> Result<(), ContractSetError> {
    basis.contracts.validate()?;
    if basis.work_authority_id != basis.template.work_authority_id
        || basis.work_authority_id != basis.selection.work_id
    {
        return Err(basis_error(
            "work authority id 가 basis·template·selection 에서 불일치(cross-work Plan)",
        ));
    }
    if basis.template.template_application_id != basis.selection.template_application_id {
        return Err(basis_error(
            "template application id 가 template·selection 에서 불일치",
        ));
    }
    let active = active_binding_digest(&basis.field_binding.effective_active_binding_rules)
        .map_err(|e| basis_error(e.0))?;
    if basis.field_binding.active_binding_digest != active {
        return Err(basis_error("active_binding_digest 재계산 불일치"));
    }
    let source = required_source_key_set_digest(&basis.field_binding.required_source_keys)
        .map_err(|e| basis_error(e.0))?;
    if basis.field_binding.required_source_key_set_digest != source {
        return Err(basis_error("required_source_key_set_digest 재계산 불일치"));
    }
    Ok(())
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealedExecutionPlanSemanticPayload {
    pub plan_schema_version: String,
    pub canonical_encoding_version: String,
    pub execution_basis: ExecutionBasis,
    pub active_field_requirements: Vec<Value>,
    pub ordered_operations: Vec<Value>,
}
pub fn encode_sealed_plan(
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<Value, ContractSetError> {
    Ok(json!({"plan_schema_version":plan.plan_schema_version,
        "canonical_encoding_version":plan.canonical_encoding_version,
        "execution_basis":encode_execution_basis(&plan.execution_basis),
        "execution_basis_digest":execution_basis_digest(&plan.execution_basis)?,
        "active_field_requirements":plan.active_field_requirements,
        "ordered_operations":plan.ordered_operations}))
}
pub fn plan_semantic_digest(
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<String, ContractSetError> {
    digest(
        &encode_sealed_plan(plan)?,
        ContractSetErrorKind::PlanIntegrity,
    )
}
pub fn canonicalize_execution_operations(
    requirements: &[Value],
    ops: &[Value],
) -> (Vec<Value>, Vec<Value>) {
    let rank: HashMap<_, _> = ops
        .iter()
        .filter(|op| op.get("op") == Some(&json!(PLAN_APPLY_FIELD_BINDING)))
        .filter_map(|op| op.get("field_id").and_then(Value::as_str))
        .enumerate()
        .map(|(i, field)| (field.to_owned(), i))
        .collect();
    let mut reqs = requirements.to_vec();
    reqs.sort_by_key(|item| {
        item.get("field_id")
            .and_then(Value::as_str)
            .and_then(|field| rank.get(field))
            .copied()
            .unwrap_or(rank.len())
    });
    (reqs, ops.to_vec())
}
pub fn build_sealed_plan(
    execution_basis: ExecutionBasis,
    requirements: &[Value],
    ops: &[Value],
    schema: &str,
    encoding_version: &str,
) -> Result<SealedExecutionPlanSemanticPayload, ContractSetError> {
    crate::canonical_execution_encoding::require_supported_encoding(encoding_version).map_err(
        |_| {
            plan_error(format!(
                "미지원 canonical encoding version: {}",
                repr(&Value::String(encoding_version.into()))
            ))
        },
    )?;
    if schema.is_empty() {
        return Err(plan_error(
            "plan_schema_version 는 비어 있지 않은 문자열이어야 한다",
        ));
    }
    let (requirements, ops) = canonicalize_execution_operations(requirements, ops);
    Ok(SealedExecutionPlanSemanticPayload {
        plan_schema_version: schema.into(),
        canonical_encoding_version: encoding_version.into(),
        execution_basis,
        active_field_requirements: requirements,
        ordered_operations: ops,
    })
}
fn field_id<'a>(entry: &'a Value, what: &str) -> Result<&'a str, ContractSetError> {
    entry
        .get("field_id")
        .and_then(Value::as_str)
        .filter(|field| !field.is_empty())
        .ok_or_else(|| plan_error(format!("{what} 에 field_id 가 없다")))
}
/// Rejects duplicate field ids within either list, and a mismatch between the
/// two (differing set or order), before any rule-level check runs.
fn verify_field_sets_match(
    req_fields: &[&str],
    apply_fields: &[&str],
) -> Result<(), ContractSetError> {
    if req_fields
        .iter()
        .collect::<std::collections::HashSet<_>>()
        .len()
        != req_fields.len()
    {
        return Err(plan_error("active field requirement field 중복"));
    }
    if apply_fields
        .iter()
        .collect::<std::collections::HashSet<_>>()
        .len()
        != apply_fields.len()
    {
        return Err(plan_error("APPLY_FIELD_BINDING field 중복"));
    }
    if req_fields != apply_fields {
        return Err(plan_error(
            "requirement ↔ APPLY_FIELD_BINDING 순서/집합 불일치",
        ));
    }
    Ok(())
}
/// Confirms each active field requirement's recorded value expression still
/// matches the effective binding rule computed for that field.
fn verify_requirement_bindings(
    requirements: &[Value],
    rules: &HashMap<&str, Value>,
) -> Result<(), ContractSetError> {
    for req in requirements {
        let field = field_id(req, "active field requirement")?;
        let expected = rules.get(field).ok_or_else(|| {
            plan_error(format!(
                "requirement {} 에 대응하는 effective binding rule 이 없다",
                repr(&Value::String(field.into()))
            ))
        })?;
        if req.get("value_expression") != Some(expected) {
            return Err(plan_error(format!(
                "requirement {} 의 value_expression 이 effective binding rule 과 불일치",
                repr(&Value::String(field.into()))
            )));
        }
    }
    Ok(())
}
/// Validates one ordered operation against canonical operation order:
/// `REMOVE_OPTION` entries must all precede the single `APPLY_FIELD_BINDING`,
/// and must carry non-empty `slot_id`/`option_id`.
fn verify_operation_order(op: &Value, seen_apply: &mut bool) -> Result<(), ContractSetError> {
    match op.get("op").and_then(Value::as_str) {
        Some(PLAN_APPLY_FIELD_BINDING) => *seen_apply = true,
        Some(PLAN_REMOVE_OPTION) => {
            if *seen_apply {
                return Err(plan_error(
                    "operation order 비canonical: REMOVE_OPTION 이 APPLY_FIELD_BINDING 뒤에 온다",
                ));
            }
            for name in ["slot_id", "option_id"] {
                if op
                    .get(name)
                    .and_then(Value::as_str)
                    .is_none_or(str::is_empty)
                {
                    return Err(plan_error(format!(
                        "REMOVE_OPTION 에 {name} 가 없다/비어 있다"
                    )));
                }
            }
        }
        _ => {
            return Err(plan_error(format!(
                "미지원 operation code: {}",
                repr(op.get("op").unwrap_or(&Value::Null))
            )));
        }
    }
    Ok(())
}
pub fn verify_sealed_plan_integrity(
    plan: &SealedExecutionPlanSemanticPayload,
    supported_schemas: &[String],
) -> Result<(), ContractSetError> {
    if !supported_schemas.contains(&plan.plan_schema_version) {
        return Err(fail(
            ContractSetErrorKind::UnsupportedPlanSchema,
            format!(
                "미지원 plan schema(latest fallback 없음): {}",
                repr(&Value::String(plan.plan_schema_version.clone()))
            ),
        ));
    }
    crate::canonical_execution_encoding::require_supported_encoding(
        &plan.canonical_encoding_version,
    )
    .map_err(|_| {
        plan_error(format!(
            "미지원 canonical encoding version: {}",
            repr(&Value::String(plan.canonical_encoding_version.clone()))
        ))
    })?;
    verify_execution_basis_integrity(&plan.execution_basis)?;
    let req_fields = plan
        .active_field_requirements
        .iter()
        .map(|item| field_id(item, "active field requirement"))
        .collect::<Result<Vec<_>, _>>()?;
    let apply_fields = plan
        .ordered_operations
        .iter()
        .filter(|item| item.get("op") == Some(&json!(PLAN_APPLY_FIELD_BINDING)))
        .map(|item| field_id(item, "APPLY_FIELD_BINDING operation"))
        .collect::<Result<Vec<_>, _>>()?;
    verify_field_sets_match(&req_fields, &apply_fields)?;
    let rules: HashMap<_, _> = plan
        .execution_basis
        .field_binding
        .effective_active_binding_rules
        .iter()
        .map(|rule| {
            (
                rule.field_id.as_str(),
                encode_value_expression(&rule.value_expression),
            )
        })
        .collect();
    verify_requirement_bindings(&plan.active_field_requirements, &rules)?;
    let mut seen_apply = false;
    for op in &plan.ordered_operations {
        verify_operation_order(op, &mut seen_apply)?;
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_compilation::{ActiveFieldValueExpression, EffectiveFieldBindingRule};
    use crate::execution_composition::{
        COMPOSITION_CONTRACT_ID, COMPOSITION_FINGERPRINT_HWPX, NATIVE_PRIMITIVE_CONTRACT_ID,
    };
    #[test]
    fn closed_contract_and_capture_evidence_recompute() {
        let roles = ContractRoles {
            slot_selection_contract_id: "slot-selection/v1".into(),
            field_binding_contract_id: "field-binding/v1".into(),
            source_schema_contract_id: "source-schema/v1".into(),
            raw_record_contract_id: "raw/v1".into(),
            execution_semantic_contract_id: "exec/v1".into(),
            binding_value_contract_id: "binding/v1".into(),
            document_value_resolution_contract_id: "document/v1".into(),
            record_validation_contract_id: "record/v1".into(),
            record_review_contract_id: "review/v1".into(),
            composition_contract_id: COMPOSITION_CONTRACT_ID.into(),
            native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID.into(),
            materialization_base_contract_id:
                crate::execution_capture::MATERIALIZATION_BASE_CONTRACT_ID.into(),
            materialization_contract_id: "materialization/v1".into(),
            composition_theorem_evidence_manifest_digest: COMPOSITION_FINGERPRINT_HWPX.into(),
        };
        let contracts = build_execution_contract_set(roles.clone()).unwrap();
        contracts.validate().unwrap();
        assert_eq!(
            contracts.contract_set_manifest_digest,
            contract_set_manifest_digest(&contracts).unwrap()
        );
        let mut tampered = contracts.clone();
        tampered.roles.raw_record_contract_id = "changed".into();
        assert_eq!(
            tampered.validate().unwrap_err().kind,
            ContractSetErrorKind::Integrity
        );
        let mut unsupported = roles.clone();
        unsupported.native_primitive_contract_id = "future".into();
        assert!(build_execution_contract_set(unsupported).is_err());
        let mut wrong_base = roles.clone();
        wrong_base.materialization_base_contract_id = "wrong-base/v1".into();
        assert_eq!(
            build_execution_contract_set(wrong_base).unwrap_err().kind,
            ContractSetErrorKind::Integrity
        );
        let mut forged_theorem = roles.clone();
        forged_theorem.composition_theorem_evidence_manifest_digest = "sha256:forged".into();
        assert_eq!(
            build_execution_contract_set(forged_theorem)
                .unwrap_err()
                .kind,
            ContractSetErrorKind::Integrity
        );
        let mut empty_role = roles.clone();
        empty_role.raw_record_contract_id.clear();
        assert_eq!(
            build_execution_contract_set(empty_role).unwrap_err().kind,
            ContractSetErrorKind::Integrity
        );
        let mut different_role = roles;
        different_role.materialization_contract_id = "materialization/v2".into();
        assert_ne!(
            contracts.contract_set_manifest_digest,
            build_execution_contract_set(different_role)
                .unwrap()
                .contract_set_manifest_digest
        );
        let mut bad_schema = contracts.clone();
        bad_schema.contract_set_schema_version = "execution-contract-set/v9".into();
        assert_eq!(
            bad_schema.validate().unwrap_err().kind,
            ContractSetErrorKind::Integrity
        );
        let profile = QualificationProfileSemanticPayload {
            qualification_profile_id: "qualification/v1".into(),
            media: "hwpx".into(),
            adapter_contract_version: "adapter/v1".into(),
            product_rule_version: "product/v1".into(),
            operation_alphabet_version: "operations/v1".into(),
            projection_schema_version: "projection/v1".into(),
            manifest_payload: json!({"rule":"v1"}),
        };
        let profile_digest = qualification_profile_semantic_digest(&profile).unwrap();
        assert_eq!(
            require_consistent_qualification_profile(&HashMap::new(), &profile).unwrap(),
            profile_digest
        );
        let known = HashMap::from([(
            profile.qualification_profile_id.clone(),
            profile_digest.clone(),
        )]);
        assert_eq!(
            require_consistent_qualification_profile(&known, &profile).unwrap(),
            profile_digest
        );
        let mut changed_profile = profile;
        changed_profile.manifest_payload = json!({"rule":"v2"});
        assert_ne!(
            qualification_profile_semantic_digest(&changed_profile).unwrap(),
            profile_digest
        );
        assert_eq!(
            require_consistent_qualification_profile(&known, &changed_profile)
                .unwrap_err()
                .kind,
            ContractSetErrorKind::QualificationProfileManifestIntegrity
        );
        let projection = json!({"workspace_instance_id":"ws","work_authority_id":"w"});
        let stored = digest(
            &projection,
            ContractSetErrorKind::DurableCaptureEvidenceIntegrity,
        )
        .unwrap();
        let evidence = DurableSealCaptureEvidence::Complete {
            semantic_projection: projection,
            semantic_digest: stored,
            provenance: CaptureEvidenceProvenance {
                field_binding_authority_revision: "rev".into(),
                source_configuration_version: "1".into(),
                captured_at: "now".into(),
            },
        };
        let encoded = encode_durable_capture_evidence(&evidence).unwrap();
        assert_eq!(decode_durable_capture_evidence(&encoded).unwrap(), evidence);
        let mut forged = encoded;
        forged["semantic_projection"]["work_authority_id"] = json!("other");
        assert_eq!(
            decode_durable_capture_evidence(&forged).unwrap_err().kind,
            ContractSetErrorKind::DurableCaptureEvidenceIntegrity
        );
        let projection =
            json!({"workspace_instance_id":"ws","blocked":"SLOT_CONFIGURATION_INCOMPLETE"});
        let attempt = DurableSealCaptureEvidence::Attempt {
            semantic_digest: digest(
                &projection,
                ContractSetErrorKind::DurableCaptureEvidenceIntegrity,
            )
            .unwrap(),
            semantic_projection: projection,
            normalized_blockers: vec!["SLOT_CONFIGURATION_INCOMPLETE".into()],
            provenance: CaptureEvidenceProvenance {
                field_binding_authority_revision: "rev".into(),
                source_configuration_version: "1".into(),
                captured_at: "now".into(),
            },
        };
        let encoded_attempt = encode_durable_capture_evidence(&attempt).unwrap();
        assert_eq!(
            decode_durable_capture_evidence(&encoded_attempt).unwrap(),
            attempt
        );
        let mut forged = encoded_attempt.clone();
        forged["semantic_digest"] = json!("sha256:tampered");
        assert_eq!(
            decode_durable_capture_evidence(&forged).unwrap_err().kind,
            ContractSetErrorKind::DurableCaptureEvidenceIntegrity
        );
        for bad in [json!("not-a-list"), json!([1])] {
            let mut forged = encoded_attempt.clone();
            forged["normalized_blockers"] = bad;
            assert_eq!(
                decode_durable_capture_evidence(&forged).unwrap_err().kind,
                ContractSetErrorKind::DurableCaptureEvidenceIntegrity
            );
        }
        for bad in [json!(null), json!(123), json!({"bad":1})] {
            let mut forged = encoded_attempt.clone();
            forged["provenance"]["captured_at"] = bad;
            assert_eq!(
                decode_durable_capture_evidence(&forged).unwrap_err().kind,
                ContractSetErrorKind::DurableCaptureEvidenceIntegrity
            );
        }
        let mut forged = encoded_attempt;
        forged["kind"] = json!("MYSTERY");
        assert_eq!(
            decode_durable_capture_evidence(&forged).unwrap_err().kind,
            ContractSetErrorKind::DurableCaptureEvidenceIntegrity
        );
    }
    #[test]
    fn plan_recomputes_nested_identity_and_rejects_unknown_schema() {
        let roles = ContractRoles {
            slot_selection_contract_id: "slot-selection/v1".into(),
            field_binding_contract_id: "binding/v1".into(),
            source_schema_contract_id: "source/v1".into(),
            raw_record_contract_id: "raw/v1".into(),
            execution_semantic_contract_id: "execution/v1".into(),
            binding_value_contract_id: "value/v1".into(),
            document_value_resolution_contract_id: "document/v1".into(),
            record_validation_contract_id: "validation/v1".into(),
            record_review_contract_id: "review/v1".into(),
            composition_contract_id: COMPOSITION_CONTRACT_ID.into(),
            native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID.into(),
            materialization_base_contract_id:
                crate::execution_capture::MATERIALIZATION_BASE_CONTRACT_ID.into(),
            materialization_contract_id: "materialization/v1".into(),
            composition_theorem_evidence_manifest_digest: COMPOSITION_FINGERPRINT_HWPX.into(),
        };
        let binding = EffectiveFieldBindingBasis {
            effective_active_binding_rules: vec![],
            active_binding_digest: active_binding_digest(&[]).unwrap(),
            required_source_keys: vec![],
            required_source_key_set_digest: required_source_key_set_digest(&[]).unwrap(),
        };
        let basis = ExecutionBasis {
            workspace_instance_id: "ws".into(),
            work_authority_id: "w".into(),
            qualification_profile_semantic_digest: "sha256:profile".into(),
            template: ExactTemplateExecutionBasis {
                execution_base_kind: "APPLIED_TEMPLATE_CANDIDATE".into(),
                materialization_base_contract_id:
                    crate::execution_capture::MATERIALIZATION_BASE_CONTRACT_ID.into(),
                work_authority_id: "w".into(),
                template_application_id: "app".into(),
                exact_content_digest: "sha256:template".into(),
                canonical_blob_reference: "blob://private".into(),
            },
            contracts: build_execution_contract_set(roles).unwrap(),
            selection: EffectiveSelectionBasis {
                slot_mode: "SLOTLESS".into(),
                work_id: "w".into(),
                template_application_id: "app".into(),
                selection_semantic_contract_id: "slot-selection/v1".into(),
                template_structure_digest: "sha256:structure".into(),
                effective_selection_digest: None,
                declared_selection_digest: None,
            },
            field_binding: binding,
        };
        let plan = build_sealed_plan(
            basis,
            &[],
            &[],
            "plan/v1",
            crate::canonical_execution_encoding::CANONICAL_ENCODING_VERSION,
        )
        .unwrap();
        verify_sealed_plan_integrity(&plan, &["plan/v1".into()]).unwrap();
        let digest = plan_semantic_digest(&plan).unwrap();
        let mut different_address = plan.clone();
        different_address
            .execution_basis
            .template
            .canonical_blob_reference = "blob://other".into();
        assert_eq!(digest, plan_semantic_digest(&different_address).unwrap());
        let mut different_schema = plan.clone();
        different_schema.plan_schema_version = "plan/v2".into();
        assert_ne!(digest, plan_semantic_digest(&different_schema).unwrap());
        let mut different_qualification = plan.clone();
        different_qualification
            .execution_basis
            .qualification_profile_semantic_digest = "sha256:other".into();
        assert_ne!(
            digest,
            plan_semantic_digest(&different_qualification).unwrap()
        );
        let mut different_declared = plan.clone();
        different_declared
            .execution_basis
            .selection
            .declared_selection_digest = Some("sha256:other".into());
        assert_eq!(digest, plan_semantic_digest(&different_declared).unwrap());
        let mut source_keys = plan.clone();
        source_keys
            .execution_basis
            .field_binding
            .required_source_keys = vec!["addr".into(), "name".into()];
        source_keys
            .execution_basis
            .field_binding
            .required_source_key_set_digest = required_source_key_set_digest(
            &source_keys
                .execution_basis
                .field_binding
                .required_source_keys,
        )
        .unwrap();
        let mut reversed_keys = source_keys.clone();
        reversed_keys
            .execution_basis
            .field_binding
            .required_source_keys
            .reverse();
        assert_eq!(
            execution_basis_digest(&source_keys.execution_basis).unwrap(),
            execution_basis_digest(&reversed_keys.execution_basis).unwrap()
        );
        assert_eq!(
            verify_sealed_plan_integrity(&plan, &["future/v1".into()])
                .unwrap_err()
                .kind,
            ContractSetErrorKind::UnsupportedPlanSchema
        );
        let mut forged = plan.clone();
        forged.execution_basis.field_binding.active_binding_digest = "sha256:wrong".into();
        assert_eq!(
            verify_sealed_plan_integrity(&forged, &["plan/v1".into()])
                .unwrap_err()
                .kind,
            ContractSetErrorKind::BasisIntegrity
        );
        let mut malformed = plan;
        malformed.ordered_operations =
            vec![json!({"op":"REMOVE_OPTION","slot_id":"s","option_id":""})];
        assert_eq!(
            verify_sealed_plan_integrity(&malformed, &["plan/v1".into()])
                .unwrap_err()
                .kind,
            ContractSetErrorKind::PlanIntegrity
        );
        let rule = EffectiveFieldBindingRule {
            field_id: "f".into(),
            binding_kind: "INTENTIONAL_BLANK".into(),
            value_expression: ActiveFieldValueExpression::IntentionalBlank {
                exact_blank_policy: "WRITE_EMPTY_TEXT_PRESERVE_FIELD".into(),
            },
        };
        let mut valid = malformed;
        valid
            .execution_basis
            .field_binding
            .effective_active_binding_rules = vec![rule.clone()];
        valid.execution_basis.field_binding.active_binding_digest =
            active_binding_digest(std::slice::from_ref(&rule)).unwrap();
        valid.active_field_requirements = vec![
            json!({"field_id":"f","value_expression":encode_value_expression(&rule.value_expression)}),
        ];
        valid.ordered_operations = vec![
            json!({"op":"REMOVE_OPTION","slot_id":"s","option_id":"o"}),
            json!({"op":"APPLY_FIELD_BINDING","field_id":"f"}),
        ];
        verify_sealed_plan_integrity(&valid, &["plan/v1".into()]).unwrap();
        let mut input_requirements = valid.active_field_requirements.clone();
        let plan_from_input = build_sealed_plan(
            valid.execution_basis.clone(),
            &input_requirements,
            &valid.ordered_operations,
            "plan/v1",
            crate::canonical_execution_encoding::CANONICAL_ENCODING_VERSION,
        )
        .unwrap();
        let frozen_digest = plan_semantic_digest(&plan_from_input).unwrap();
        input_requirements[0]["value_expression"]["exact_blank_policy"] = json!("forged");
        assert_eq!(
            plan_semantic_digest(&plan_from_input).unwrap(),
            frozen_digest
        );
        for (ops, reqs) in [
            (
                vec![
                    json!({"op":"APPLY_FIELD_BINDING","field_id":"f"}),
                    json!({"op":"REMOVE_OPTION","slot_id":"s","option_id":"o"}),
                ],
                valid.active_field_requirements.clone(),
            ),
            (vec![json!({"op":"MYSTERY"})], vec![]),
            (
                vec![
                    json!({"op":"APPLY_FIELD_BINDING","field_id":"f"}),
                    json!({"op":"APPLY_FIELD_BINDING","field_id":"f"}),
                ],
                valid.active_field_requirements.clone(),
            ),
            (vec![json!({"op":"APPLY_FIELD_BINDING"})], vec![]),
            (
                vec![
                    json!({"op":"REMOVE_OPTION","slot_id":"s"}),
                    json!({"op":"APPLY_FIELD_BINDING","field_id":"f"}),
                ],
                valid.active_field_requirements.clone(),
            ),
            (vec![], valid.active_field_requirements.clone()),
        ] {
            let mut altered = valid.clone();
            altered.ordered_operations = ops;
            altered.active_field_requirements = reqs;
            assert_eq!(
                verify_sealed_plan_integrity(&altered, &["plan/v1".into()])
                    .unwrap_err()
                    .kind,
                ContractSetErrorKind::PlanIntegrity
            );
        }
        let mut forged = valid.clone();
        forged.active_field_requirements[0]["value_expression"]["exact_blank_policy"] =
            json!("forged");
        assert_eq!(
            verify_sealed_plan_integrity(&forged, &["plan/v1".into()])
                .unwrap_err()
                .kind,
            ContractSetErrorKind::PlanIntegrity
        );
        let mut forged = valid.clone();
        forged.active_field_requirements[0]["field_id"] = json!("ghost");
        forged.ordered_operations[1]["field_id"] = json!("ghost");
        assert_eq!(
            verify_sealed_plan_integrity(&forged, &["plan/v1".into()])
                .unwrap_err()
                .kind,
            ContractSetErrorKind::PlanIntegrity
        );
        let mut forged = valid.clone();
        forged.execution_basis.selection.work_id = "other-work".into();
        assert_eq!(
            verify_sealed_plan_integrity(&forged, &["plan/v1".into()])
                .unwrap_err()
                .kind,
            ContractSetErrorKind::BasisIntegrity
        );
    }
}
