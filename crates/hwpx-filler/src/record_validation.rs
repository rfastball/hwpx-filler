//! Plan-bound immutable record validation. Values are logical Unicode text, not XML.

use crate::canonical_execution_encoding::{
    CANONICAL_ENCODING_VERSION, canonical_execution_bytes, canonical_execution_digest,
};
use crate::execution_contract_set::{
    SealedExecutionPlanSemanticPayload, execution_basis_digest, plan_semantic_digest,
    verify_sealed_plan_integrity,
};
use crate::field_binding::{
    BINDING_VALUE_VERSION, DOCUMENT_CONTENT_VALUE_POLICY_VERSION, EXACT_BLANK_POLICY,
    SOURCE_SCHEMA_VERSION, WHITESPACE_PRESERVE_EXACT, WHITESPACE_STRIP_LEADING_TRAILING,
    parse_runtime_clock, render_runtime_date, render_value_format, require_runtime_date_format,
    require_text_slice, resolve_document_value_policy,
};
use crate::fields::python_whitespace;
use crate::job::MISSING_MARKER;
use crate::raw_data_record::{
    CanonicalSourceValue, RAW_RECORD_CONTRACT_ID, RECORD_REVIEW_CONTRACT_ID,
    RECORD_REVIEW_EXAMINED, RawDataRecordSnapshot, RecordReviewEvidence,
    verify_raw_record_snapshot, verify_record_review_evidence_integrity,
};
use crate::text_render::python_repr;
use crate::text_slice::apply_text_slice;
use serde_json::{Value, json};
use std::collections::HashSet;
use std::fmt;

pub const VALIDATED_RECORD_SCHEMA_VERSION: &str = "validated-record/v1";
pub const RECORD_VALIDATION_CONTRACT_ID: &str = "record-validation/v1";
pub const DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID: &str = DOCUMENT_CONTENT_VALUE_POLICY_VERSION;
pub const RECORD_REQUIRED_VALUE_MISSING: &str = "RECORD_REQUIRED_VALUE_MISSING";
pub const RECORD_VALUE_FORMAT_INVALID: &str = "RECORD_VALUE_FORMAT_INVALID";
pub const RECORD_REVIEW_REQUIRED: &str = "RECORD_REVIEW_REQUIRED";
pub const RECORD_REVIEW_EVIDENCE_STALE: &str = "RECORD_REVIEW_EVIDENCE_STALE";
pub const RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED: &str = "RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED";
pub const MISSING_VALUE_MARKED: &str = "MISSING_VALUE_MARKED";
pub const RAW_RECORD_INTEGRITY_ERROR: &str = "RAW_RECORD_INTEGRITY_ERROR";
pub const VALIDATED_RECORD_INTEGRITY_ERROR: &str = "VALIDATED_RECORD_INTEGRITY_ERROR";
pub const PLAN_INTEGRITY_ERROR: &str = "PLAN_INTEGRITY_ERROR";
pub const RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR: &str = "RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR";
pub const RUNTIME_CLOCK_UNAVAILABLE: &str = "RUNTIME_CLOCK_UNAVAILABLE";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedRecordIntegrityError(pub String);
impl fmt::Display for ValidatedRecordIntegrityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ValidatedRecordIntegrityError {}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordValidationBlocker {
    pub code: String,
    pub field_id: Option<String>,
    pub detail: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordValidationContextError {
    pub code: String,
    pub detail: String,
}
fn context_error(code: &str, detail: impl Into<String>) -> RecordValidationContextError {
    RecordValidationContextError {
        code: code.into(),
        detail: detail.into(),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidationProvenance {
    pub validation_facts: Vec<String>,
    pub record_review_evidence_refs: Vec<String>,
    pub validated_at: String,
    pub source_value_provenance: Vec<Value>,
}
pub fn marked_missing_fields(provenance: &ValidationProvenance) -> Vec<String> {
    let prefix = format!("{MISSING_VALUE_MARKED}:");
    provenance
        .validation_facts
        .iter()
        .filter_map(|fact| fact.strip_prefix(&prefix).map(str::to_owned))
        .collect()
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedDataRecord {
    pub validated_record_digest: String,
    pub semantic_payload_encoded: Value,
    pub validation_provenance: ValidationProvenance,
}
impl ValidatedDataRecord {
    pub fn canonical_payload_bytes(&self) -> Result<Vec<u8>, ValidatedRecordIntegrityError> {
        canonical_execution_bytes(&self.semantic_payload_encoded)
            .map_err(|e| ValidatedRecordIntegrityError(e.to_string()))
    }
    pub fn plan_semantic_digest(&self) -> Option<&str> {
        self.semantic_payload_encoded
            .get("plan_semantic_digest")
            .and_then(Value::as_str)
    }
    pub fn document_values_in_order(
        &self,
    ) -> Result<Vec<(String, String)>, ValidatedRecordIntegrityError> {
        let values = self
            .semantic_payload_encoded
            .get("resolved_requirement_values")
            .and_then(Value::as_array)
            .ok_or_else(|| {
                ValidatedRecordIntegrityError("VDR resolved_requirement_values 형식 불량".into())
            })?;
        values
            .iter()
            .map(|item| {
                let field = item
                    .get("field_id")
                    .and_then(Value::as_str)
                    .ok_or_else(|| {
                        ValidatedRecordIntegrityError("VDR field_id 형식 불량".into())
                    })?;
                let text = item
                    .get("document_value")
                    .and_then(Value::as_str)
                    .ok_or_else(|| {
                        ValidatedRecordIntegrityError("VDR document_value 형식 불량".into())
                    })?;
                Ok((field.into(), text.into()))
            })
            .collect()
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ValidateDataRecordResult {
    Validated(Box<ValidatedDataRecord>),
    Blocked(Vec<RecordValidationBlocker>),
    ContextError(RecordValidationContextError),
}
#[derive(Clone, Debug)]
struct ValidationContext<'a> {
    plan: &'a SealedExecutionPlanSemanticPayload,
    plan_digest: String,
    basis_digest: String,
    unsupported_contract: Option<RecordValidationContextError>,
}
fn prepare_context(
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<ValidationContext<'_>, RecordValidationContextError> {
    verify_sealed_plan_integrity(plan, &["hwpx-execution-plan/v2".into()])
        .map_err(|e| context_error(PLAN_INTEGRITY_ERROR, e.detail))?;
    let plan_digest =
        plan_semantic_digest(plan).map_err(|e| context_error(PLAN_INTEGRITY_ERROR, e.detail))?;
    let basis_digest = execution_basis_digest(&plan.execution_basis)
        .map_err(|e| context_error(PLAN_INTEGRITY_ERROR, e.detail))?;
    let roles = &plan.execution_basis.contracts.roles;
    let unsupported_contract = [
        (
            "raw_record_contract_id",
            roles.raw_record_contract_id.as_str(),
            RAW_RECORD_CONTRACT_ID,
            "UNSUPPORTED_RAW_RECORD_CONTRACT",
        ),
        (
            "source_schema_contract_id",
            roles.source_schema_contract_id.as_str(),
            SOURCE_SCHEMA_VERSION,
            "UNSUPPORTED_SOURCE_SCHEMA_CONTRACT",
        ),
        (
            "binding_value_contract_id",
            roles.binding_value_contract_id.as_str(),
            BINDING_VALUE_VERSION,
            "UNSUPPORTED_BINDING_VALUE_CONTRACT",
        ),
        (
            "record_validation_contract_id",
            roles.record_validation_contract_id.as_str(),
            RECORD_VALIDATION_CONTRACT_ID,
            "UNSUPPORTED_RECORD_VALIDATION_CONTRACT",
        ),
        (
            "record_review_contract_id",
            roles.record_review_contract_id.as_str(),
            RECORD_REVIEW_CONTRACT_ID,
            "UNSUPPORTED_RECORD_REVIEW_CONTRACT",
        ),
        (
            "document_value_resolution_contract_id",
            roles.document_value_resolution_contract_id.as_str(),
            DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
        ),
    ]
    .into_iter()
    .find_map(|(name, actual, expected, code)| {
        (actual != expected).then(|| {
            context_error(
                code,
                format!("미지원 {name}: {}", repr(&Value::String(actual.into()))),
            )
        })
    });
    Ok(ValidationContext {
        plan,
        plan_digest,
        basis_digest,
        unsupported_contract,
    })
}
fn repr(value: &Value) -> String {
    python_repr(value)
}
fn optional_str<'a>(
    ve: &'a Value,
    key: &str,
) -> Result<Option<&'a str>, RecordValidationContextError> {
    match ve.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => Ok(Some(s)),
        _ => Err(context_error(
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            format!("requirement 표시형 {key} 형식 불량"),
        )),
    }
}
fn policy_id(ve: &Value) -> String {
    let value = ve
        .get("document_content_value_policy_id")
        .unwrap_or(&Value::Null);
    value.as_str().map_or_else(|| repr(value), str::to_owned)
}
fn whitespace(text: &str, policy: &str) -> Result<String, RecordValidationContextError> {
    match policy {
        WHITESPACE_PRESERVE_EXACT => Ok(text.into()),
        WHITESPACE_STRIP_LEADING_TRAILING => Ok(text.trim_matches(python_whitespace).into()),
        _ => Err(context_error(
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            format!(
                "미지원 whitespace policy: {}",
                repr(&Value::String(policy.into()))
            ),
        )),
    }
}
fn resolved_policy(
    ve: &Value,
) -> Result<crate::field_binding::DocumentContentValuePolicy, RecordValidationContextError> {
    resolve_document_value_policy(&policy_id(ve))
        .map_err(|e| context_error("UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT", e.message))
}
fn no_fixed_format(ve: &Value) -> Result<(), RecordValidationContextError> {
    let format_code = ve.get("format_code").unwrap_or(&Value::Null);
    if (!format_code.is_null() && format_code != "")
        || ve.get("format_kind").is_some_and(|v| !v.is_null())
    {
        return Err(context_error(
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            format!(
                "고정값에는 표시형을 적용하지 않는다: {}/{}",
                repr(ve.get("format_kind").unwrap_or(&Value::Null)),
                repr(format_code)
            ),
        ));
    }
    if let Some(slice) = ve.get("text_slice").filter(|v| !v.is_null()) {
        return Err(context_error(
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            format!("고정값에는 가공을 적용하지 않는다: {}", repr(slice)),
        ));
    }
    Ok(())
}
fn render_source_format(
    ve: &Value,
    field: &str,
    text: &str,
) -> Result<String, RecordValidationContextError> {
    render_value_format(
        optional_str(ve, "format_kind")?,
        optional_str(ve, "format_code")?,
        text,
    )
    .map_err(|e| {
        context_error(
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            format!(
                "requirement {} 의 표시형을 해석할 수 없다: {}",
                repr(&Value::String(field.into())),
                e.message
            ),
        )
    })
}
fn slice_source_text(
    ve: &Value,
    field: &str,
    text: &str,
) -> Result<String, RecordValidationContextError> {
    let slice = require_text_slice(ve.get("text_slice")).map_err(|e| {
        context_error(
            "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            format!(
                "requirement {} 의 가공을 해석할 수 없다: {}",
                repr(&Value::String(field.into())),
                e.message
            ),
        )
    })?;
    Ok(apply_text_slice(slice.as_ref(), text))
}
pub fn missing_value_marker(field_id: &str) -> String {
    MISSING_MARKER.replace("{field}", field_id)
}
#[derive(Clone, Debug)]
struct ResolvedValue {
    text: String,
    marked: bool,
}
fn resolved(text: impl Into<String>) -> ResolvedValue {
    ResolvedValue {
        text: text.into(),
        marked: false,
    }
}
fn resolve_from_source(
    ve: &Value,
    field: &str,
    snapshot: &RawDataRecordSnapshot,
) -> Result<Result<ResolvedValue, RecordValidationBlocker>, RecordValidationContextError> {
    render_source_format(ve, field, "")?;
    slice_source_text(ve, field, "")?;
    let key = ve
        .get("source_key")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            context_error(
                PLAN_INTEGRITY_ERROR,
                format!(
                    "FROM_SOURCE requirement {} 의 source_key 형식 불량",
                    repr(&Value::String(field.into()))
                ),
            )
        })?;
    let policy = resolved_policy(ve)?;
    if !snapshot.has_key(key) {
        return Ok(Err(RecordValidationBlocker {
            code: RECORD_REQUIRED_VALUE_MISSING.into(),
            field_id: Some(field.into()),
            detail: format!(
                "required source key {} 가 raw record 에 없다(MISSING)",
                repr(&Value::String(key.into()))
            ),
        }));
    }
    let source = snapshot.value_for(key).expect("has_key");
    let text = match source {
        CanonicalSourceValue::Null => {
            return Ok(Ok(ResolvedValue {
                text: missing_value_marker(field),
                marked: true,
            }));
        }
        CanonicalSourceValue::Text(text) => text,
    };
    if text.trim_matches(python_whitespace).is_empty() {
        return Ok(Ok(ResolvedValue {
            text: missing_value_marker(field),
            marked: true,
        }));
    }
    let text = slice_source_text(ve, field, &whitespace(text, &policy.whitespace_policy)?)?;
    if text.trim_matches(python_whitespace).is_empty() {
        return Ok(Ok(ResolvedValue {
            text: missing_value_marker(field),
            marked: true,
        }));
    }
    Ok(Ok(resolved(render_source_format(ve, field, &text)?)))
}
fn resolve_requirement(
    requirement: &Value,
    snapshot: &RawDataRecordSnapshot,
    runtime_clock: Option<&str>,
) -> Result<Result<ResolvedValue, RecordValidationBlocker>, RecordValidationContextError> {
    let field = requirement
        .get("field_id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| context_error(PLAN_INTEGRITY_ERROR, "requirement 에 field_id 가 없다"))?;
    let ve = requirement
        .get("value_expression")
        .filter(|v| v.is_object())
        .ok_or_else(|| {
            context_error(
                PLAN_INTEGRITY_ERROR,
                format!(
                    "requirement {} 에 value_expression 이 없다",
                    repr(&Value::String(field.into()))
                ),
            )
        })?;
    match ve.get("kind").and_then(Value::as_str) {
        Some("FROM_SOURCE") => resolve_from_source(ve, field, snapshot),
        Some("CONSTANT") => {
            no_fixed_format(ve)?;
            let policy = resolved_policy(ve)?;
            let canonical = ve
                .get("canonical_value")
                .filter(|v| v.is_object())
                .ok_or_else(|| {
                    context_error(
                        PLAN_INTEGRITY_ERROR,
                        format!(
                            "CONSTANT requirement {} 에 canonical_value 가 없다",
                            repr(&Value::String(field.into()))
                        ),
                    )
                })?;
            let text = canonical
                .get("text")
                .and_then(Value::as_str)
                .filter(|_| canonical.get("kind") == Some(&json!("TEXT")))
                .ok_or_else(|| {
                    context_error(
                        PLAN_INTEGRITY_ERROR,
                        format!(
                            "CONSTANT requirement {} 의 canonical_value 형식 불량",
                            repr(&Value::String(field.into()))
                        ),
                    )
                })?;
            Ok(Ok(resolved(whitespace(text, &policy.whitespace_policy)?)))
        }
        Some("INTENTIONAL_BLANK") => {
            if ve.get("exact_blank_policy") != Some(&json!(EXACT_BLANK_POLICY)) {
                return Err(context_error(
                    "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
                    format!(
                        "requirement {} 의 미지원 blank policy: {}",
                        repr(&Value::String(field.into())),
                        repr(ve.get("exact_blank_policy").unwrap_or(&Value::Null))
                    ),
                ));
            }
            Ok(Ok(resolved("")))
        }
        Some("RUNTIME_DATE") => {
            if ["text_slice", "source_key", "canonical_value"]
                .iter()
                .any(|key| ve.get(*key).is_some_and(|v| !v.is_null()))
            {
                return Err(context_error(
                    "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
                    format!(
                        "실행 시각 값에는 데이터 열·고정값·가공이 없다: requirement {}",
                        repr(&Value::String(field.into()))
                    ),
                ));
            }
            let kind = optional_str(ve, "format_kind")?;
            let code = optional_str(ve, "format_code")?;
            require_runtime_date_format(kind, code).map_err(|e| {
                context_error(
                    "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
                    format!(
                        "requirement {} 의 실행 시각 표시형을 해석할 수 없다: {}",
                        repr(&Value::String(field.into())),
                        e.message
                    ),
                )
            })?;
            let policy = resolved_policy(ve)?;
            let now = parse_runtime_clock(runtime_clock).map_err(|e| {
                context_error(
                    RUNTIME_CLOCK_UNAVAILABLE,
                    format!(
                        "requirement {}: {}",
                        repr(&Value::String(field.into())),
                        e.message
                    ),
                )
            })?;
            let text = render_runtime_date(code.unwrap_or_default(), now).map_err(|e| {
                context_error("UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT", e.message)
            })?;
            Ok(Ok(resolved(whitespace(&text, &policy.whitespace_policy)?)))
        }
        other => Err(context_error(
            PLAN_INTEGRITY_ERROR,
            format!(
                "requirement {} 의 value_expression kind 미상: {}",
                repr(&Value::String(field.into())),
                repr(&other.map_or(Value::Null, |s| Value::String(s.into())))
            ),
        )),
    }
}
fn verify_snapshot(
    context: &ValidationContext<'_>,
    snapshot: &RawDataRecordSnapshot,
) -> Result<(), RecordValidationContextError> {
    verify_raw_record_snapshot(snapshot)
        .map_err(|e| context_error(RAW_RECORD_INTEGRITY_ERROR, e.detail))?;
    if let Some(unsupported) = &context.unsupported_contract {
        return Err(unsupported.clone());
    }
    let payload = snapshot.semantic_payload_encoded();
    let roles = &context.plan.execution_basis.contracts.roles;
    if payload.get("raw_record_contract_id") != Some(&json!(roles.raw_record_contract_id)) {
        return Err(context_error(
            "UNSUPPORTED_RAW_RECORD_CONTRACT",
            "snapshot 의 raw_record_contract_id 가 Plan 과 불일치",
        ));
    }
    if payload.get("source_schema_contract_id") != Some(&json!(roles.source_schema_contract_id)) {
        return Err(context_error(
            "UNSUPPORTED_SOURCE_SCHEMA_CONTRACT",
            "snapshot 의 source_schema_contract_id 가 Plan 과 불일치",
        ));
    }
    Ok(())
}
fn evaluate_review(
    context: &ValidationContext<'_>,
    snapshot: &RawDataRecordSnapshot,
    evidence: Option<&RecordReviewEvidence>,
    required: bool,
    blockers: &mut Vec<(isize, RecordValidationBlocker)>,
) -> Result<Option<String>, RecordValidationContextError> {
    let Some(evidence) = evidence else {
        if required {
            blockers.push((
                -1,
                RecordValidationBlocker {
                    code: RECORD_REVIEW_REQUIRED.into(),
                    field_id: None,
                    detail: "이 Plan 은 record review evidence 를 요구하는데 제공되지 않았다"
                        .into(),
                },
            ));
        }
        return Ok(None);
    };
    verify_record_review_evidence_integrity(evidence)
        .map_err(|e| context_error(RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR, e.detail))?;
    let basis = &context.plan.execution_basis;
    let roles = &basis.contracts.roles;
    let mismatch = evidence.plan_semantic_digest != context.plan_digest
        || evidence.raw_record_digest != snapshot.raw_record_digest
        || evidence.record_identity != snapshot.record_identity
        || evidence.record_review_contract_id != roles.record_review_contract_id
        || evidence.workspace_instance_id != basis.workspace_instance_id
        || evidence.work_authority_id != basis.work_authority_id;
    if mismatch {
        blockers.push((
            -1,
            RecordValidationBlocker {
                code: RECORD_REVIEW_EVIDENCE_STALE.into(),
                field_id: None,
                detail:
                    "review evidence 가 다른 Plan/raw record/identity/policy 에 결속돼 재사용 불가"
                        .into(),
            },
        ));
        return Ok(None);
    }
    if evidence.review_policy_basis != RECORD_REVIEW_EXAMINED {
        return Err(context_error(
            "UNSUPPORTED_RECORD_REVIEW_CONTRACT",
            format!(
                "미지원 review policy basis(examination 아님): {}",
                repr(&Value::String(evidence.review_policy_basis.clone()))
            ),
        ));
    }
    Ok(Some(evidence.review_basis_digest.clone()))
}
fn validate_one(
    context: &ValidationContext<'_>,
    snapshot: &RawDataRecordSnapshot,
    review_evidence: Option<&RecordReviewEvidence>,
    review_required: bool,
    validated_at: &str,
    runtime_clock: Option<&str>,
) -> Result<ValidateDataRecordResult, RecordValidationContextError> {
    verify_snapshot(context, snapshot)?;
    let mut blockers = Vec::new();
    let review_ref = evaluate_review(
        context,
        snapshot,
        review_evidence,
        review_required,
        &mut blockers,
    )?;
    let mut resolved_values = Vec::new();
    let mut marked = Vec::new();
    for (index, requirement) in context.plan.active_field_requirements.iter().enumerate() {
        let outcome = resolve_requirement(requirement, snapshot, runtime_clock)?;
        match outcome {
            Err(blocker) => blockers.push((index as isize, blocker)),
            Ok(value) => {
                let field = requirement["field_id"].as_str().unwrap_or_default();
                resolved_values.push(json!({"field_id":field,"document_value":value.text}));
                if value.marked {
                    marked.push(field.to_owned());
                }
            }
        }
    }
    if !blockers.is_empty() {
        blockers.sort_by(|a, b| {
            (
                a.0,
                a.1.code.as_str(),
                a.1.field_id.as_deref().unwrap_or(""),
            )
                .cmp(&(
                    b.0,
                    b.1.code.as_str(),
                    b.1.field_id.as_deref().unwrap_or(""),
                ))
        });
        return Ok(ValidateDataRecordResult::Blocked(
            blockers.into_iter().map(|(_, blocker)| blocker).collect(),
        ));
    }
    let payload = json!({
        "record_schema_version":VALIDATED_RECORD_SCHEMA_VERSION,
        "canonical_encoding_version":CANONICAL_ENCODING_VERSION,
        "plan_semantic_digest":context.plan_digest,
        "execution_basis_digest":context.basis_digest,
        "record_identity":snapshot.record_identity,
        "raw_record_digest":snapshot.raw_record_digest,
        "record_validation_contract_id":RECORD_VALIDATION_CONTRACT_ID,
        "document_value_resolution_contract_id":DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
        "resolved_requirement_values":resolved_values,
    });
    let digest = canonical_execution_digest(&payload)
        .map_err(|e| context_error(VALIDATED_RECORD_INTEGRITY_ERROR, e.to_string()))?;
    let mut facts = vec![format!("validated:{}", resolved_values.len())];
    facts.extend(
        marked
            .into_iter()
            .map(|field| format!("{MISSING_VALUE_MARKED}:{field}")),
    );
    let record = ValidatedDataRecord {
        validated_record_digest: digest,
        semantic_payload_encoded: payload,
        validation_provenance: ValidationProvenance {
            validation_facts: facts,
            record_review_evidence_refs: review_ref.into_iter().collect(),
            validated_at: validated_at.into(),
            source_value_provenance: Vec::new(),
        },
    };
    verify_completeness_with_digests(
        &record,
        context.plan,
        &context.plan_digest,
        &context.basis_digest,
    )
    .map_err(|e| context_error(VALIDATED_RECORD_INTEGRITY_ERROR, e.0))?;
    Ok(ValidateDataRecordResult::Validated(Box::new(record)))
}
pub fn validate_data_record_against_plan(
    plan: &SealedExecutionPlanSemanticPayload,
    snapshot: &RawDataRecordSnapshot,
    review_evidence: Option<&RecordReviewEvidence>,
    review_required: bool,
    validated_at: &str,
    runtime_clock: Option<&str>,
) -> ValidateDataRecordResult {
    let result = prepare_context(plan).and_then(|ctx| {
        validate_one(
            &ctx,
            snapshot,
            review_evidence,
            review_required,
            validated_at,
            runtime_clock,
        )
    });
    result.unwrap_or_else(ValidateDataRecordResult::ContextError)
}
pub fn validate_data_records_against_plan(
    plan: &SealedExecutionPlanSemanticPayload,
    snapshots: &[RawDataRecordSnapshot],
    validated_at: &str,
    runtime_clock: Option<&str>,
) -> Vec<ValidateDataRecordResult> {
    let context = match prepare_context(plan) {
        Ok(ctx) => ctx,
        Err(error) => {
            return snapshots
                .iter()
                .map(|_| ValidateDataRecordResult::ContextError(error.clone()))
                .collect();
        }
    };
    snapshots
        .iter()
        .map(|snapshot| {
            validate_one(&context, snapshot, None, false, validated_at, runtime_clock)
                .unwrap_or_else(ValidateDataRecordResult::ContextError)
        })
        .collect()
}
pub fn verify_validated_record_completeness(
    record: &ValidatedDataRecord,
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<(), ValidatedRecordIntegrityError> {
    let plan_digest =
        plan_semantic_digest(plan).map_err(|e| ValidatedRecordIntegrityError(e.detail))?;
    let basis_digest = execution_basis_digest(&plan.execution_basis)
        .map_err(|e| ValidatedRecordIntegrityError(e.detail))?;
    verify_completeness_with_digests(record, plan, &plan_digest, &basis_digest)
}
fn verify_completeness_with_digests(
    record: &ValidatedDataRecord,
    plan: &SealedExecutionPlanSemanticPayload,
    expected_plan: &str,
    expected_basis: &str,
) -> Result<(), ValidatedRecordIntegrityError> {
    let payload = &record.semantic_payload_encoded;
    let fail = |message: &str| ValidatedRecordIntegrityError(message.into());
    let digest = canonical_execution_digest(payload).map_err(|e| fail(&e.to_string()))?;
    if digest != record.validated_record_digest {
        return Err(fail(
            "validated record 의 canonical digest 가 content-address 와 불일치",
        ));
    }
    if payload.get("record_schema_version") != Some(&json!(VALIDATED_RECORD_SCHEMA_VERSION)) {
        return Err(ValidatedRecordIntegrityError(format!(
            "미지원 VDR record schema version: {}",
            repr(payload.get("record_schema_version").unwrap_or(&Value::Null))
        )));
    }
    if payload.get("canonical_encoding_version") != Some(&json!(CANONICAL_ENCODING_VERSION)) {
        return Err(ValidatedRecordIntegrityError(format!(
            "미지원 VDR canonical encoding version: {}",
            repr(
                payload
                    .get("canonical_encoding_version")
                    .unwrap_or(&Value::Null)
            )
        )));
    }
    if payload.get("plan_semantic_digest").and_then(Value::as_str) != Some(expected_plan) {
        return Err(fail("VDR plan_semantic_digest 가 Plan 과 불일치"));
    }
    if payload
        .get("execution_basis_digest")
        .and_then(Value::as_str)
        != Some(expected_basis)
    {
        return Err(fail("VDR execution_basis_digest 가 Plan 과 불일치"));
    }
    let roles = &plan.execution_basis.contracts.roles;
    if payload.get("record_validation_contract_id")
        != Some(&json!(roles.record_validation_contract_id))
    {
        return Err(fail("VDR record_validation_contract_id 가 Plan 과 불일치"));
    }
    if payload.get("document_value_resolution_contract_id")
        != Some(&json!(roles.document_value_resolution_contract_id))
    {
        return Err(fail(
            "VDR document_value_resolution_contract_id 가 Plan 과 불일치",
        ));
    }
    verify_requirement_values(payload, plan)
}

fn verify_requirement_values(
    payload: &Value,
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<(), ValidatedRecordIntegrityError> {
    let fail = |message: &str| ValidatedRecordIntegrityError(message.into());
    let plan_fields: Vec<_> = plan
        .active_field_requirements
        .iter()
        .filter_map(|r| r.get("field_id").and_then(Value::as_str))
        .collect();
    let values = payload
        .get("resolved_requirement_values")
        .and_then(Value::as_array)
        .ok_or_else(|| fail("VDR resolved_requirement_values 형식 불량"))?;
    let vdr_fields: Vec<_> = values
        .iter()
        .map(|v| v.get("field_id").and_then(Value::as_str).unwrap_or(""))
        .collect();
    let unique: HashSet<_> = vdr_fields.iter().copied().collect();
    if unique.len() != vdr_fields.len() {
        return Err(fail("VDR resolved_requirement_values 에 중복 field"));
    }
    if vdr_fields != plan_fields {
        return Err(fail(
            "VDR resolved_requirement_values sequence 가 Plan requirement sequence 와 불일치",
        ));
    }
    for value in values {
        if value
            .get("document_value")
            .and_then(Value::as_str)
            .is_none()
        {
            return Err(ValidatedRecordIntegrityError(format!(
                "document_value 가 logical text(str)가 아니다: field {}",
                repr(value.get("field_id").unwrap_or(&Value::Null))
            )));
        }
    }
    Ok(())
}
pub fn check_validated_record_for_delivery(
    record: &ValidatedDataRecord,
    plan: &SealedExecutionPlanSemanticPayload,
    snapshot: &RawDataRecordSnapshot,
    expected_plan: &str,
    expected_basis: &str,
) -> Result<Option<&'static str>, ValidatedRecordIntegrityError> {
    let payload = &record.semantic_payload_encoded;
    if payload.get("plan_semantic_digest").and_then(Value::as_str) != Some(expected_plan) {
        return Ok(Some("plan"));
    }
    if payload.get("record_identity").and_then(Value::as_str) != Some(&snapshot.record_identity)
        || payload.get("raw_record_digest").and_then(Value::as_str)
            != Some(&snapshot.raw_record_digest)
    {
        return Ok(Some("raw"));
    }
    verify_completeness_with_digests(record, plan, expected_plan, expected_basis)?;
    Ok(None)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::execution_capture::{
        EffectiveSelectionBasis, ExactTemplateExecutionBasis, MATERIALIZATION_BASE_CONTRACT_ID,
    };
    use crate::execution_compilation::{
        ActiveFieldValueExpression, EXECUTION_SEMANTICS_CONTRACT, EffectiveFieldBindingBasis,
        EffectiveFieldBindingRule, active_binding_digest, encode_value_expression,
        required_source_key_set_digest,
    };
    use crate::execution_composition::{
        COMPOSITION_CONTRACT_ID, COMPOSITION_FINGERPRINT_HWPX, NATIVE_PRIMITIVE_CONTRACT_ID,
    };
    use crate::execution_contract_set::{
        ContractRoles, ExecutionBasis, build_execution_contract_set, build_sealed_plan,
    };
    use crate::raw_data_record::{
        RawRecordCaptureProvenance, build_raw_record_snapshot, build_record_review_evidence,
    };
    use crate::shipping_seal_policy::{
        SHIPPING_MATERIALIZATION_CONTRACT_ID, SHIPPING_PLAN_SCHEMA_VERSION,
    };

    pub(crate) fn one_source_plan() -> SealedExecutionPlanSemanticPayload {
        let expression = ActiveFieldValueExpression::FromSource {
            source_key: "열".into(),
            format_code: None,
            document_content_value_policy_id: "document-content-value/v1".into(),
            format_kind: None,
            text_slice: None,
        };
        let rules = vec![EffectiveFieldBindingRule {
            field_id: "이름".into(),
            binding_kind: "SOURCE".into(),
            value_expression: expression.clone(),
        }];
        let roles = ContractRoles {
            slot_selection_contract_id: "slot-selection/v1".into(),
            field_binding_contract_id: crate::field_binding::FIELD_BINDING_SEMANTIC_VERSION.into(),
            source_schema_contract_id: SOURCE_SCHEMA_VERSION.into(),
            raw_record_contract_id: RAW_RECORD_CONTRACT_ID.into(),
            execution_semantic_contract_id: EXECUTION_SEMANTICS_CONTRACT.into(),
            binding_value_contract_id: BINDING_VALUE_VERSION.into(),
            document_value_resolution_contract_id: DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID.into(),
            record_validation_contract_id: RECORD_VALIDATION_CONTRACT_ID.into(),
            record_review_contract_id: RECORD_REVIEW_CONTRACT_ID.into(),
            composition_contract_id: COMPOSITION_CONTRACT_ID.into(),
            native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID.into(),
            materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
            materialization_contract_id: SHIPPING_MATERIALIZATION_CONTRACT_ID.into(),
            composition_theorem_evidence_manifest_digest: COMPOSITION_FINGERPRINT_HWPX.into(),
        };
        let basis = ExecutionBasis {
            workspace_instance_id: "workspace".into(),
            work_authority_id: "work".into(),
            qualification_profile_semantic_digest: "sha256:qualified".into(),
            template: ExactTemplateExecutionBasis {
                execution_base_kind: "APPLIED_TEMPLATE_CANDIDATE".into(),
                materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
                work_authority_id: "work".into(),
                template_application_id: "application".into(),
                exact_content_digest: "sha256:candidate".into(),
                canonical_blob_reference: "blob://candidate".into(),
            },
            contracts: build_execution_contract_set(roles).unwrap(),
            selection: EffectiveSelectionBasis {
                slot_mode: "SLOTLESS".into(),
                work_id: "work".into(),
                template_application_id: "application".into(),
                selection_semantic_contract_id: "slot-selection/v1".into(),
                template_structure_digest: "sha256:structure".into(),
                effective_selection_digest: None,
                declared_selection_digest: None,
            },
            field_binding: EffectiveFieldBindingBasis {
                effective_active_binding_rules: rules.clone(),
                active_binding_digest: active_binding_digest(&rules).unwrap(),
                required_source_keys: vec!["열".into()],
                required_source_key_set_digest: required_source_key_set_digest(&["열".into()])
                    .unwrap(),
            },
        };
        build_sealed_plan(
            basis,
            &[
                json!({"field_id":"이름","expected_active_occurrence_count":1,
                "value_expression":encode_value_expression(&expression)}),
            ],
            &[json!({"op":"APPLY_FIELD_BINDING","field_id":"이름"})],
            SHIPPING_PLAN_SCHEMA_VERSION,
            CANONICAL_ENCODING_VERSION,
        )
        .unwrap()
    }

    pub(crate) fn runtime_date_plan() -> SealedExecutionPlanSemanticPayload {
        let source = one_source_plan();
        let mut basis = source.execution_basis;
        let expression = ActiveFieldValueExpression::RuntimeDate {
            format_kind: "date".into(),
            format_code: "%Y-%m-%d".into(),
            document_content_value_policy_id: "document-content-value/v1".into(),
        };
        let binding = &mut basis.field_binding;
        binding
            .effective_active_binding_rules
            .push(EffectiveFieldBindingRule {
                field_id: "작성일".into(),
                binding_kind: "RUNTIME_DATE".into(),
                value_expression: expression.clone(),
            });
        binding.active_binding_digest =
            active_binding_digest(&binding.effective_active_binding_rules).unwrap();
        let mut requirements = source.active_field_requirements;
        requirements.push(json!({"field_id":"작성일","expected_active_occurrence_count":1,"value_expression":encode_value_expression(&expression)}));
        let mut operations = source.ordered_operations;
        operations.push(json!({"op":"APPLY_FIELD_BINDING","field_id":"작성일"}));
        build_sealed_plan(
            basis,
            &requirements,
            &operations,
            SHIPPING_PLAN_SCHEMA_VERSION,
            CANONICAL_ENCODING_VERSION,
        )
        .unwrap()
    }

    fn plan_with_rules(
        rules: Vec<EffectiveFieldBindingRule>,
    ) -> SealedExecutionPlanSemanticPayload {
        let mut basis = one_source_plan().execution_basis;
        let mut keys = rules
            .iter()
            .filter_map(|rule| match &rule.value_expression {
                ActiveFieldValueExpression::FromSource { source_key, .. } => {
                    Some(source_key.clone())
                }
                _ => None,
            })
            .collect::<Vec<_>>();
        keys.sort();
        keys.dedup();
        basis.field_binding = EffectiveFieldBindingBasis {
            active_binding_digest: active_binding_digest(&rules).unwrap(),
            required_source_key_set_digest: required_source_key_set_digest(&keys).unwrap(),
            required_source_keys: keys,
            effective_active_binding_rules: rules.clone(),
        };
        let requirements = rules
            .iter()
            .map(|rule| {
                json!({
                    "field_id":rule.field_id,"expected_active_occurrence_count":1,
                    "value_expression":encode_value_expression(&rule.value_expression)
                })
            })
            .collect::<Vec<_>>();
        let operations = rules
            .iter()
            .map(|rule| {
                json!({
                    "op":"APPLY_FIELD_BINDING","field_id":rule.field_id
                })
            })
            .collect::<Vec<_>>();
        build_sealed_plan(
            basis,
            &requirements,
            &operations,
            SHIPPING_PLAN_SCHEMA_VERSION,
            CANONICAL_ENCODING_VERSION,
        )
        .unwrap()
    }

    fn source_row(values: Vec<(&str, CanonicalSourceValue)>) -> RawDataRecordSnapshot {
        build_raw_record_snapshot(
            &values
                .iter()
                .map(|(key, _)| (*key).into())
                .collect::<Vec<_>>(),
            values
                .iter()
                .map(|(key, value)| ((*key).into(), value.clone()))
                .collect(),
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "2026-11-05T18:04:03".into(),
                source_observation_ref: None,
            },
        )
        .unwrap()
    }

    fn validated(
        plan: &SealedExecutionPlanSemanticPayload,
        row: &RawDataRecordSnapshot,
    ) -> ValidatedDataRecord {
        match validate_data_record_against_plan(plan, row, None, false, "now", None) {
            ValidateDataRecordResult::Validated(record) => *record,
            result => panic!("valid record refused: {result:?}"),
        }
    }

    #[test]
    fn requirement_order_keeps_exact_text_shared_sources_constants_and_blank_markers() {
        let source = one_source_plan()
            .execution_basis
            .field_binding
            .effective_active_binding_rules[0]
            .clone();
        let mut shared = source.clone();
        shared.field_id = "금액".into();
        let constant = |field: &str, policy: &str| EffectiveFieldBindingRule {
            field_id: field.into(),
            binding_kind: "CONSTANT".into(),
            value_expression: ActiveFieldValueExpression::ConstantValue {
                text: "  x  ".into(),
                format_code: None,
                document_content_value_policy_id: policy.into(),
            },
        };
        let plan = plan_with_rules(vec![
            source,
            shared,
            constant("상수", "document-content-value/v1"),
            constant("정리", "document-content-value/legacy-strip-v1"),
            EffectiveFieldBindingRule {
                field_id: "빈칸".into(),
                binding_kind: "INTENTIONAL_BLANK".into(),
                value_expression: ActiveFieldValueExpression::IntentionalBlank {
                    exact_blank_policy: EXACT_BLANK_POLICY.into(),
                },
            },
        ]);
        let plan_digest = plan_semantic_digest(&plan).unwrap();
        let mut previous = None;
        for text in [
            "a<b>&\"'",
            "  가 나  ",
            "1,500,000",
            "금 오백만원",
            "계약 후 90일 이내",
            "TRUE",
        ] {
            let row = source_row(vec![("열", CanonicalSourceValue::Text(text.into()))]);
            let result = validated(&plan, &row);
            assert_eq!(
                result.document_values_in_order().unwrap(),
                [
                    ("이름".into(), text.into()),
                    ("금액".into(), text.into()),
                    ("상수".into(), "  x  ".into()),
                    ("정리".into(), "x".into()),
                    ("빈칸".into(), "".into())
                ]
            );
            assert_eq!(result.plan_semantic_digest(), Some(plan_digest.as_str()));
            assert_ne!(previous.as_ref(), Some(&result.validated_record_digest));
            previous = Some(result.validated_record_digest.clone());
            verify_validated_record_completeness(&result, &plan).unwrap();
            let mut other_plan = plan.clone();
            other_plan
                .execution_basis
                .qualification_profile_semantic_digest = "other-profile".into();
            let other = validated(&other_plan, &row);
            assert_eq!(
                other.document_values_in_order(),
                result.document_values_in_order()
            );
            assert_ne!(
                other.validated_record_digest,
                result.validated_record_digest
            );
        }
        for value in [
            CanonicalSourceValue::Null,
            CanonicalSourceValue::Text("".into()),
            CanonicalSourceValue::Text(" ".into()),
            CanonicalSourceValue::Text("\t\n".into()),
        ] {
            let record = validated(&plan, &source_row(vec![("열", value)]));
            assert_eq!(
                marked_missing_fields(&record.validation_provenance),
                ["이름", "금액"]
            );
            let values = record.document_values_in_order().unwrap();
            assert_eq!(values[0].1, missing_value_marker("이름"));
            assert_eq!(values[1].1, missing_value_marker("금액"));
            assert_eq!(values[4].1, "");
            let payload = String::from_utf8(record.canonical_payload_bytes().unwrap()).unwrap();
            assert!(!payload.contains(MISSING_VALUE_MARKED));
            assert!(payload.contains(&missing_value_marker("이름")));
            assert_eq!(
                canonical_execution_digest(&record.semantic_payload_encoded).unwrap(),
                record.validated_record_digest
            );
        }
        let ValidateDataRecordResult::Blocked(blockers) =
            validate_data_record_against_plan(&plan, &source_row(vec![]), None, false, "now", None)
        else {
            panic!("missing column admitted")
        };
        assert_eq!(
            blockers
                .iter()
                .map(|b| (b.code.as_str(), b.field_id.as_deref()))
                .collect::<Vec<_>>(),
            [
                (RECORD_REQUIRED_VALUE_MISSING, Some("이름")),
                (RECORD_REQUIRED_VALUE_MISSING, Some("금액"))
            ]
        );
        let row = source_row(vec![("열", CanonicalSourceValue::Text("x".into()))]);
        let mut reordered = validated(&plan, &row);
        reordered.semantic_payload_encoded["resolved_requirement_values"]
            .as_array_mut()
            .unwrap()
            .swap(0, 1);
        reordered.validated_record_digest =
            canonical_execution_digest(&reordered.semantic_payload_encoded).unwrap();
        assert!(verify_validated_record_completeness(&reordered, &plan).is_err());
    }

    #[test]
    fn source_resolution_applies_whitespace_then_slice_then_format() {
        let cases = [
            (
                Some("amount"),
                Some(""),
                Value::Null,
                " 24750000 ",
                "24,750,000원",
            ),
            (
                Some("amount"),
                Some("{:,}"),
                Value::Null,
                "24750000",
                "24,750,000",
            ),
            (
                Some("date"),
                Some("kor"),
                Value::Null,
                "2026-06-15",
                "2026년 6월 15일",
            ),
            (
                Some("text"),
                Some("phone"),
                Value::Null,
                "01012345678",
                "010-1234-5678",
            ),
            (None, None, Value::Null, " 원문 ", "원문"),
            (
                None,
                None,
                json!({"mode":"split","delimiter":"-","index":1}),
                " R26BK09017075-000 ",
                "R26BK09017075",
            ),
            (
                None,
                None,
                json!({"mode":"chars","start":1,"length":3}),
                "R26TA0911050700",
                "R26",
            ),
            (
                None,
                None,
                json!({"mode":"split","delimiter":", ","index":-1}),
                "MPKPLA26910290, MPKPLA26910291",
                "MPKPLA26910291",
            ),
            (
                Some("amount"),
                Some(""),
                json!({"mode":"split","delimiter":"원","index":1}),
                "170,309,180원 (VAT 포함)",
                "170,309,180원",
            ),
            (
                None,
                None,
                json!({"mode":"before","delimiter":"-"}),
                "R26BK09017075-000",
                "R26BK09017075",
            ),
            (
                None,
                None,
                json!({"mode":"between","open":"(","close":")"}),
                "170,309,180원 (VAT 포함)",
                "VAT 포함",
            ),
            (
                None,
                None,
                json!({"mode":"remove","find":"(VAT 포함)"}),
                "170,309,180원 (VAT 포함)",
                "170,309,180원",
            ),
            (
                None,
                None,
                json!({"mode":"before","delimiter":"X","on_missing":"keep"}),
                "abc",
                "abc",
            ),
            (Some("amount"), Some(""), Value::Null, "  ", "〘미입력·값〙"),
        ];
        for (kind, code, slice, raw, expected) in cases {
            let expression = ActiveFieldValueExpression::FromSource {
                source_key: "열".into(),
                format_kind: kind.map(str::to_owned),
                format_code: code.map(str::to_owned),
                document_content_value_policy_id: "document-content-value/legacy-strip-v1".into(),
                text_slice: if slice.is_null() {
                    None
                } else {
                    Some(Box::new(
                        crate::text_slice::TextSlice::from_dict(&slice).unwrap(),
                    ))
                },
            };
            let encoded = encode_value_expression(&expression);
            assert_eq!(encoded.get("text_slice").is_none(), slice.is_null());
            let plan = plan_with_rules(vec![EffectiveFieldBindingRule {
                field_id: "값".into(),
                binding_kind: "SOURCE".into(),
                value_expression: expression,
            }]);
            let record = validated(
                &plan,
                &source_row(vec![("열", CanonicalSourceValue::Text(raw.into()))]),
            );
            assert_eq!(
                record.document_values_in_order().unwrap(),
                [("값".into(), expected.into())],
                "{raw} / {slice}"
            );
        }
    }

    #[test]
    fn malformed_resolution_contracts_fail_even_on_empty_values() {
        let source = encode_value_expression(
            &one_source_plan()
                .execution_basis
                .field_binding
                .effective_active_binding_rules[0]
                .value_expression,
        );
        let patches = [
            json!({"format_code":"UPPER"}),
            json!({"format_kind":"currency","format_code":""}),
            json!({"format_kind":"amount","format_code":null}),
            json!({"text_slice":{"mode":"regex","pattern":".*"}}),
            json!({"text_slice":{"mode":"split","delimiter":"","index":1}}),
            json!({"text_slice":{"mode":"chars","start":0}}),
        ];
        let mut expressions = patches
            .into_iter()
            .map(|patch| {
                let mut expression = source.clone();
                expression
                    .as_object_mut()
                    .unwrap()
                    .extend(patch.as_object().unwrap().clone());
                expression
            })
            .collect::<Vec<_>>();
        expressions.push(
            json!({"kind":"CONSTANT","canonical_value":{"kind":"TEXT","text":"x"},
            "format_code":null,"document_content_value_policy_id":"document-content-value/v1",
            "text_slice":{"mode":"chars","start":1}}),
        );
        expressions.push(json!({"kind":"INTENTIONAL_BLANK","exact_blank_policy":"CUSTOM"}));
        for expression in expressions {
            for raw in ["A-B", ""] {
                let row = source_row(vec![("열", CanonicalSourceValue::Text(raw.into()))]);
                let requirement = json!({"field_id":"이름","value_expression":expression});
                assert_eq!(
                    resolve_requirement(&requirement, &row, None)
                        .unwrap_err()
                        .code,
                    "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
                    "{requirement}"
                );
            }
        }
    }

    #[test]
    fn unknown_contracts_and_corrupted_plan_fail_before_document_resolution() {
        let row = source_row(vec![("열", CanonicalSourceValue::Text("원문".into()))]);
        for (role, expected) in [
            ("raw", "UNSUPPORTED_RAW_RECORD_CONTRACT"),
            ("source", "UNSUPPORTED_SOURCE_SCHEMA_CONTRACT"),
            ("binding", "UNSUPPORTED_BINDING_VALUE_CONTRACT"),
            ("validation", "UNSUPPORTED_RECORD_VALIDATION_CONTRACT"),
            ("review", "UNSUPPORTED_RECORD_REVIEW_CONTRACT"),
            (
                "resolution",
                "UNSUPPORTED_DOCUMENT_VALUE_RESOLUTION_CONTRACT",
            ),
        ] {
            let mut plan = one_source_plan();
            let mut roles = plan.execution_basis.contracts.roles.clone();
            let target = match role {
                "raw" => &mut roles.raw_record_contract_id,
                "source" => &mut roles.source_schema_contract_id,
                "binding" => &mut roles.binding_value_contract_id,
                "validation" => &mut roles.record_validation_contract_id,
                "review" => &mut roles.record_review_contract_id,
                _ => &mut roles.document_value_resolution_contract_id,
            };
            *target = "unknown/v999".into();
            plan.execution_basis.contracts = build_execution_contract_set(roles).unwrap();
            let mut corrupt = row.clone();
            corrupt.raw_record_digest = "sha256:forged".into();
            let results =
                validate_data_records_against_plan(&plan, &[corrupt, row.clone()], "now", None);
            for (result, code) in results.iter().zip([RAW_RECORD_INTEGRITY_ERROR, expected]) {
                let ValidateDataRecordResult::ContextError(error) = result else {
                    panic!("{result:?}")
                };
                assert_eq!(error.code, code, "{role}");
            }
        }
        let mut plans = [one_source_plan(), one_source_plan()];
        plans[0].plan_schema_version = "hwpx-execution-plan/v999".into();
        plans[1].execution_basis.field_binding.active_binding_digest = "sha256:wrong".into();
        for plan in plans {
            let ValidateDataRecordResult::ContextError(error) =
                validate_data_record_against_plan(&plan, &row, None, false, "now", None)
            else {
                panic!("corrupt plan admitted")
            };
            assert_eq!(error.code, PLAN_INTEGRITY_ERROR);
        }
    }

    #[test]
    fn runtime_dates_use_the_supplied_batch_clock_without_sealing_it_into_the_plan() {
        let plan = runtime_date_plan();
        assert_eq!(
            plan.active_field_requirements[1]["value_expression"],
            json!({"kind":"RUNTIME_DATE","format_kind":"date","format_code":"%Y-%m-%d","document_content_value_policy_id":"document-content-value/v1"})
        );
        assert!(
            !serde_json::to_string(&plan.active_field_requirements)
                .unwrap()
                .contains("2026")
        );
        let rows = ["r1", "r2"].map(|identity| {
            build_raw_record_snapshot(
                &["열".into()],
                vec![("열".into(), CanonicalSourceValue::Text("".into()))],
                identity,
                RawRecordCaptureProvenance {
                    source_adapter_contract_id: "excel/v1".into(),
                    captured_at: "2026-01-01T00:00:00".into(),
                    source_observation_ref: None,
                },
            )
            .unwrap()
        });
        for result in validate_data_records_against_plan(
            &plan,
            &rows,
            "2099-01-01T00:00:00",
            Some("2026-06-15T23:59:59"),
        ) {
            let ValidateDataRecordResult::Validated(record) = result else {
                panic!("runtime clock must render both rows");
            };
            assert_eq!(
                record.document_values_in_order().unwrap(),
                [
                    ("이름".into(), missing_value_marker("이름")),
                    ("작성일".into(), "2026-06-15".into())
                ]
            );
            assert_eq!(
                marked_missing_fields(&record.validation_provenance),
                ["이름"]
            );
        }
        for clock in [None, Some(""), Some("not-a-time")] {
            let ValidateDataRecordResult::ContextError(error) = validate_data_record_against_plan(
                &plan,
                &rows[0],
                None,
                false,
                "2099-01-01T00:00:00",
                clock,
            ) else {
                panic!("missing clock must not fall back to wall time");
            };
            assert_eq!(error.code, RUNTIME_CLOCK_UNAVAILABLE);
        }
        assert!(matches!(
            validate_data_record_against_plan(
                &one_source_plan(),
                &rows[0],
                None,
                false,
                "2099-01-01T00:00:00",
                None
            ),
            ValidateDataRecordResult::Validated(_)
        ));
        for mutation in [
            json!({"format_kind":"amount"}),
            json!({"format_kind":null}),
            json!({"format_code":null}),
            json!({"text_slice":{"mode":"chars","start":1}}),
            json!({"source_key":"열"}),
        ] {
            let mut forged = plan.clone();
            forged.active_field_requirements[1]["value_expression"]
                .as_object_mut()
                .unwrap()
                .extend(mutation.as_object().unwrap().clone());
            let ValidateDataRecordResult::ContextError(error) = validate_data_record_against_plan(
                &forged,
                &rows[0],
                None,
                false,
                "2099-01-01T00:00:00",
                Some("2026-06-15T23:59:59"),
            ) else {
                panic!("malformed runtime-date expression admitted");
            };
            assert_eq!(error.code, PLAN_INTEGRITY_ERROR);
        }
    }

    #[test]
    fn frozen_row_missing_null_and_intentional_blank_stay_distinct() {
        let snapshot = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Null)],
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "t1".into(),
                source_observation_ref: None,
            },
        )
        .unwrap();
        let source = json!({"field_id":"이름","value_expression":{
            "kind":"FROM_SOURCE","source_key":"열","format_kind":null,"format_code":null,
            "document_content_value_policy_id":"document-content-value/v1"}});
        let marked = resolve_requirement(&source, &snapshot, None)
            .unwrap()
            .unwrap();
        assert!(marked.marked);
        assert_eq!(marked.text, "〘미입력·이름〙");
        let absent = json!({"field_id":"이름","value_expression":{
            "kind":"FROM_SOURCE","source_key":"없는열","format_kind":null,"format_code":null,
            "document_content_value_policy_id":"document-content-value/v1"}});
        assert_eq!(
            resolve_requirement(&absent, &snapshot, None)
                .unwrap()
                .unwrap_err()
                .code,
            RECORD_REQUIRED_VALUE_MISSING
        );
        let blank = json!({"field_id":"이름","value_expression":{
            "kind":"INTENTIONAL_BLANK","exact_blank_policy":EXACT_BLANK_POLICY}});
        let intentional = resolve_requirement(&blank, &snapshot, None)
            .unwrap()
            .unwrap();
        assert_eq!(intentional.text, "");
        assert!(!intentional.marked);
        let exact_text = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text(" 본과 ".into()))],
            "row-2",
            snapshot.capture_provenance.clone(),
        )
        .unwrap();
        assert_eq!(
            resolve_requirement(&source, &exact_text, None)
                .unwrap()
                .unwrap()
                .text,
            " 본과 "
        );
        assert_eq!(
            marked_missing_fields(&ValidationProvenance {
                validation_facts: vec!["validated:1".into(), "MISSING_VALUE_MARKED:이름".into()],
                record_review_evidence_refs: vec![],
                validated_at: "t2".into(),
                source_value_provenance: vec![],
            }),
            ["이름"]
        );

        // Selecting nothing marks the field; `keep` preserves the source text.
        let unsliced = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text("구분자없음".into()))],
            "row-3",
            snapshot.capture_provenance.clone(),
        )
        .unwrap();
        let mut split = source.clone();
        split["value_expression"]["text_slice"] = json!({"mode":"split","delimiter":"-","index":2});
        let selected = resolve_requirement(&split, &unsliced, None)
            .unwrap()
            .unwrap();
        assert!(selected.marked);
        assert_eq!(selected.text, missing_value_marker("이름"));
        split["value_expression"]["text_slice"]["on_missing"] = json!("keep");
        let kept = resolve_requirement(&split, &unsliced, None)
            .unwrap()
            .unwrap();
        assert!(!kept.marked);
        assert_eq!(kept.text, "구분자없음");

        let runtime = json!({"field_id":"일자","value_expression":{
            "kind":"RUNTIME_DATE","format_kind":"date","format_code":"%Y-%m-%d",
            "document_content_value_policy_id":"document-content-value/v1"}});
        assert_eq!(
            resolve_requirement(&runtime, &snapshot, None)
                .unwrap_err()
                .code,
            RUNTIME_CLOCK_UNAVAILABLE
        );
        assert_eq!(
            resolve_requirement(&runtime, &snapshot, Some("2026-11-05T18:04:03"))
                .unwrap()
                .unwrap()
                .text,
            "2026-11-05"
        );
    }

    #[test]
    fn sealed_record_binds_plan_and_raw_snapshot_and_rejects_tampering() {
        let plan = one_source_plan();
        let provenance = RawRecordCaptureProvenance {
            source_adapter_contract_id: "excel/v1".into(),
            captured_at: "2026-11-05T18:04:03".into(),
            source_observation_ref: None,
        };
        let row = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text(" 원문 ".into()))],
            "row-1",
            provenance.clone(),
        )
        .unwrap();
        let ValidateDataRecordResult::Validated(validated) = validate_data_record_against_plan(
            &plan,
            &row,
            None,
            false,
            "2026-11-05T18:04:04",
            None,
        ) else {
            panic!("valid sealed record must pass");
        };
        assert_eq!(
            validated.document_values_in_order().unwrap(),
            vec![("이름".into(), " 원문 ".into())]
        );
        verify_validated_record_completeness(&validated, &plan).unwrap();

        let mut changed_plan = plan.clone();
        changed_plan.execution_basis.template.exact_content_digest = "sha256:other".into();
        assert!(verify_validated_record_completeness(&validated, &changed_plan).is_err());
        let mut forged = (*validated).clone();
        forged.semantic_payload_encoded["resolved_requirement_values"][0]["document_value"] =
            json!("변조");
        assert!(verify_validated_record_completeness(&forged, &plan).is_err());

        let missing = build_raw_record_snapshot(&[], vec![], "row-2", provenance).unwrap();
        let results = validate_data_records_against_plan(
            &plan,
            &[row.clone(), missing],
            "2026-11-05T18:04:04",
            None,
        );
        assert!(matches!(results[0], ValidateDataRecordResult::Validated(_)));
        let ValidateDataRecordResult::Blocked(blockers) = &results[1] else {
            panic!("missing source key must block only its row");
        };
        assert_eq!(blockers[0].code, RECORD_REQUIRED_VALUE_MISSING);
        let mut tampered_raw = row;
        tampered_raw.raw_record_digest = "sha256:forged".into();
        let ValidateDataRecordResult::ContextError(failure) = validate_data_record_against_plan(
            &plan,
            &tampered_raw,
            None,
            false,
            "2026-11-05T18:04:04",
            None,
        ) else {
            panic!("tampered source snapshot must fail closed");
        };
        assert_eq!(failure.code, RAW_RECORD_INTEGRITY_ERROR);
    }

    #[test]
    fn review_evidence_is_exact_to_plan_and_row_while_validation_time_is_provenance() {
        let plan = one_source_plan();
        let row = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text("원문".into()))],
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "2026-11-05T18:04:03".into(),
                source_observation_ref: None,
            },
        )
        .unwrap();
        let ValidateDataRecordResult::Blocked(blockers) =
            validate_data_record_against_plan(&plan, &row, None, true, "2026-11-05T18:04:04", None)
        else {
            panic!("review-required row was admitted")
        };
        assert_eq!(blockers[0].code, RECORD_REVIEW_REQUIRED);
        let evidence = build_record_review_evidence(RecordReviewEvidence {
            workspace_instance_id: plan.execution_basis.workspace_instance_id.clone(),
            work_authority_id: plan.execution_basis.work_authority_id.clone(),
            plan_semantic_digest: plan_semantic_digest(&plan).unwrap(),
            raw_record_digest: row.raw_record_digest.clone(),
            record_identity: row.record_identity.clone(),
            record_review_contract_id: plan
                .execution_basis
                .contracts
                .roles
                .record_review_contract_id
                .clone(),
            review_policy_basis: RECORD_REVIEW_EXAMINED.into(),
            review_basis_digest: String::new(),
            actor_binding: "reviewer".into(),
            reviewed_at: "2026-11-05T18:04:04".into(),
        })
        .unwrap();
        let validate = |at: &str, evidence: Option<&RecordReviewEvidence>| {
            validate_data_record_against_plan(&plan, &row, evidence, true, at, None)
        };
        let ValidateDataRecordResult::Validated(first) =
            validate("2026-11-05T18:04:04", Some(&evidence))
        else {
            panic!("exact review evidence refused")
        };
        let ValidateDataRecordResult::Validated(later) =
            validate("2026-11-05T18:05:00", Some(&evidence))
        else {
            panic!("revalidation refused")
        };
        assert_eq!(first.validated_record_digest, later.validated_record_digest);
        assert_eq!(
            first.validation_provenance.record_review_evidence_refs,
            std::slice::from_ref(&evidence.review_basis_digest)
        );
        assert_ne!(
            first.validation_provenance.validated_at,
            later.validation_provenance.validated_at
        );
        let mut stale = evidence.clone();
        stale.plan_semantic_digest = "sha256:other".into();
        stale = build_record_review_evidence(stale).unwrap();
        let ValidateDataRecordResult::Blocked(blockers) =
            validate("2026-11-05T18:04:04", Some(&stale))
        else {
            panic!("other Plan review evidence admitted")
        };
        assert_eq!(blockers[0].code, RECORD_REVIEW_EVIDENCE_STALE);
        let mut unreviewed = evidence.clone();
        unreviewed.review_policy_basis = "NOT_REVIEWED".into();
        let unreviewed = build_record_review_evidence(unreviewed).unwrap();
        let ValidateDataRecordResult::ContextError(error) = validate("now", Some(&unreviewed))
        else {
            panic!("unreviewed policy admitted")
        };
        assert_eq!(error.code, "UNSUPPORTED_RECORD_REVIEW_CONTRACT");
        let mut forged = evidence;
        forged.raw_record_digest = "sha256:forged".into();
        let ValidateDataRecordResult::ContextError(error) =
            validate("2026-11-05T18:04:04", Some(&forged))
        else {
            panic!("tampered review evidence admitted")
        };
        assert_eq!(error.code, RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR);
    }

    #[test]
    fn validated_record_rejects_forged_structure_even_with_recomputed_digest() {
        let plan = one_source_plan();
        let row = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text("원문".into()))],
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "2026-11-05T18:04:03".into(),
                source_observation_ref: None,
            },
        )
        .unwrap();
        let ValidateDataRecordResult::Validated(valid) = validate_data_record_against_plan(
            &plan,
            &row,
            None,
            false,
            "2026-11-05T18:04:04",
            None,
        ) else {
            panic!("valid row refused")
        };
        for altered_values in [
            json!([]),
            json!([
                {"field_id":"이름","document_value":"원문"},
                {"field_id":"이름","document_value":"원문"}
            ]),
            json!([{"field_id":"다른필드","document_value":"원문"}]),
            json!([{"field_id":"이름","document_value":null}]),
            json!([{"field_id":"이름","document_value":123}]),
            json!({}),
        ] {
            let mut forged = (*valid).clone();
            forged.semantic_payload_encoded["resolved_requirement_values"] = altered_values;
            forged.validated_record_digest =
                canonical_execution_digest(&forged.semantic_payload_encoded).unwrap();
            assert!(verify_validated_record_completeness(&forged, &plan).is_err());
        }
        for key in [
            "record_schema_version",
            "canonical_encoding_version",
            "plan_semantic_digest",
            "execution_basis_digest",
            "record_validation_contract_id",
            "document_value_resolution_contract_id",
        ] {
            let mut forged = (*valid).clone();
            forged.semantic_payload_encoded[key] = json!("unknown/v999");
            forged.validated_record_digest =
                canonical_execution_digest(&forged.semantic_payload_encoded).unwrap();
            assert!(
                verify_validated_record_completeness(&forged, &plan).is_err(),
                "{key}"
            );
        }
    }
}
