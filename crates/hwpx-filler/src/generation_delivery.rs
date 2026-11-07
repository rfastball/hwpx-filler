//! Current generation delivery binding and output resolution over a sealed Plan.

use crate::canonical_execution_encoding::canonical_execution_digest;
use crate::execution_composition::{
    RuntimeConformanceQuery, RuntimeMaterializerConformanceRegistry,
};
use crate::execution_contract_set::{
    SealedExecutionPlanSemanticPayload, execution_basis_digest, plan_semantic_digest,
};
use crate::field_binding::{
    CONSTANT, FieldBindingRule, RUNTIME_DATE, SOURCE, WHITESPACE_PRESERVE_EXACT,
    WHITESPACE_STRIP_LEADING_TRAILING, parse_runtime_clock, render_runtime_date,
    render_source_value, require_runtime_date_format, require_single_rule_per_field,
    resolve_document_value_policy,
};
use crate::fields::python_whitespace;
use crate::output_name::{
    OUTPUT_NAME_PATTERN_INVALID, PatternToken, collision_key, dedupe_output_names,
    guard_output_name, parse_filename_pattern, pattern_field_token_ids, render_output_name,
};
use crate::raw_data_record::{
    CanonicalSourceValue, RawDataRecordSnapshot, verify_raw_record_snapshot,
};
use crate::record_validation::{
    DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID, ValidatedDataRecord, check_validated_record_for_delivery,
};
use crate::run_delivery_intent::{COLLISION_POLICIES, RunDeliveryIntent};
use crate::text_render::python_repr;
use chrono::NaiveDateTime;
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const FILENAME_PATTERN_CONTRACT_ID: &str = "filename-pattern/v1";
pub const DELIVERY_BINDING_BASIS_SCHEMA: &str = "generation-delivery-binding-basis/v3";
pub const OUTPUT_NAME_TOKEN_UNRESOLVED: &str = "OUTPUT_NAME_TOKEN_UNRESOLVED";
pub const OUTPUT_NAME_BINDING_AMBIGUOUS: &str = "OUTPUT_NAME_BINDING_AMBIGUOUS";
pub const OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED: &str = "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED";
pub const OUTPUT_PATH_NON_REGULAR_CONFLICT: &str = "OUTPUT_PATH_NON_REGULAR_CONFLICT";
pub const GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR: &str =
    "GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR";
pub const UNSUPPORTED_FILENAME_PATTERN_CONTRACT: &str = "UNSUPPORTED_FILENAME_PATTERN_CONTRACT";
pub const UNSUPPORTED_OVERWRITE_POLICY: &str = "UNSUPPORTED_OVERWRITE_POLICY";
pub const DELIVERY_BINDING_BASIS_INTEGRITY_ERROR: &str = "DELIVERY_BINDING_BASIS_INTEGRITY_ERROR";
pub const RAW_VALIDATED_RECORD_MISMATCH: &str = "RAW_VALIDATED_RECORD_MISMATCH";
pub const CURRENT_RECORD_VALIDATION_BASIS_MISMATCH: &str =
    "CURRENT_RECORD_VALIDATION_BASIS_MISMATCH";
pub const PATH_OCCUPANCY_OBSERVATION_MISMATCH: &str = "PATH_OCCUPANCY_OBSERVATION_MISMATCH";
pub const UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT: &str =
    "UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT";
pub const MANAGED_RUN_STARTABLE: &str = "MANAGED_RUN_STARTABLE_IN_S6";
pub const MANAGED_RUN_CONSTRUCTION_ONLY: &str = "MANAGED_RUN_CONSTRUCTION_ONLY_NOT_ADMITTED";
pub const WRITE_NEW: &str = "WRITE_NEW";
pub const WRITE_ADD_SUFFIX: &str = "WRITE_ADD_SUFFIX";
pub const WRITE_OVERWRITE: &str = "WRITE_OVERWRITE";
pub const REGULAR_FILE: &str = "REGULAR_FILE";
pub const NON_REGULAR: &str = "NON_REGULAR";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeliveryPlanBlocker {
    pub code: String,
    pub item_ordinal: Option<usize>,
    pub field_id: Option<String>,
    pub detail: String,
    pub conflicting_relative_path: Option<String>,
}
fn blocker(
    code: &str,
    ordinal: Option<usize>,
    field: Option<&str>,
    detail: impl Into<String>,
) -> DeliveryPlanBlocker {
    DeliveryPlanBlocker {
        code: code.into(),
        item_ordinal: ordinal,
        field_id: field.map(str::to_owned),
        detail: detail.into(),
        conflicting_relative_path: None,
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeliveryPlanContextError {
    pub code: String,
    pub detail: String,
}
fn context(code: &str, detail: impl Into<String>) -> DeliveryPlanContextError {
    DeliveryPlanContextError {
        code: code.into(),
        detail: detail.into(),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DeliveryPlanResult<T> {
    Ready(T),
    Blocked(Vec<DeliveryPlanBlocker>),
    ContextError(DeliveryPlanContextError),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeliveryBindingBasisIntegrityError(pub String);
impl fmt::Display for DeliveryBindingBasisIntegrityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for DeliveryBindingBasisIntegrityError {}
fn repr(value: &Value) -> String {
    python_repr(value)
}
fn repr_text(text: &str) -> String {
    repr(&Value::String(text.into()))
}
fn parse_pattern(
    pattern: &str,
    contract: &str,
) -> Result<Vec<PatternToken>, DeliveryPlanResult<()>> {
    if contract != FILENAME_PATTERN_CONTRACT_ID {
        return Err(DeliveryPlanResult::ContextError(context(
            UNSUPPORTED_FILENAME_PATTERN_CONTRACT,
            format!("미지원 filename pattern contract: {}", repr_text(contract)),
        )));
    }
    parse_filename_pattern(&Value::String(pattern.into())).map_err(|e| {
        DeliveryPlanResult::Blocked(vec![blocker(
            OUTPUT_NAME_PATTERN_INVALID,
            None,
            None,
            e.detail,
        )])
    })
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeliveryOutputNameRequirement {
    pub field_id: String,
    pub value_expression: Value,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GenerationDeliveryBindingBasis {
    pub base_template_application_id: String,
    pub field_binding_authority_revision: String,
    pub filename_pattern_contract_id: String,
    pub exact_pattern: String,
    pub document_value_resolution_contract_id: String,
    pub output_name_requirements: Vec<DeliveryOutputNameRequirement>,
    pub delivery_binding_basis_digest: String,
}
fn encode_delivery_value_expression(rule: &FieldBindingRule) -> Value {
    let policy = &rule.document_content_value_policy.policy_id;
    match rule.binding_kind.as_str() {
        SOURCE => {
            let mut value = json!({"kind":"FROM_SOURCE","source_key":rule.source_key,
                "format_kind":rule.format_kind,"format_code":rule.format_code,
                "document_content_value_policy_id":policy});
            if let Some(slice) = &rule.text_slice {
                value["text_slice"] = slice.to_dict();
            }
            value
        }
        CONSTANT => json!({"kind":"CONSTANT","canonical_value":{
            "kind":"TEXT","text":rule.canonical_constant_value.as_ref().map(|v|&v.text)},
            "format_code":rule.format_code,"document_content_value_policy_id":policy}),
        RUNTIME_DATE => json!({"kind":"RUNTIME_DATE","format_kind":rule.format_kind,
            "format_code":rule.format_code,"document_content_value_policy_id":policy}),
        _ => json!({"kind":"INTENTIONAL_BLANK","document_content_value_policy_id":policy}),
    }
}
fn basis_payload(basis: &GenerationDeliveryBindingBasis) -> Value {
    let mut requirements = basis.output_name_requirements.clone();
    requirements.sort_by(|a, b| a.field_id.as_bytes().cmp(b.field_id.as_bytes()));
    json!({"delivery_binding_basis_schema":DELIVERY_BINDING_BASIS_SCHEMA,
        "base_template_application_id":basis.base_template_application_id,
        "field_binding_authority_revision":basis.field_binding_authority_revision,
        "filename_pattern_contract_id":basis.filename_pattern_contract_id,
        "exact_pattern":basis.exact_pattern,
        "document_value_resolution_contract_id":basis.document_value_resolution_contract_id,
        "output_name_requirements":requirements.iter().map(|r|
            json!({"field_id":r.field_id,"value_expression":r.value_expression})).collect::<Vec<_>>()})
}
pub fn verify_delivery_binding_basis_integrity(
    basis: &GenerationDeliveryBindingBasis,
) -> Result<(), DeliveryBindingBasisIntegrityError> {
    let digest = canonical_execution_digest(&basis_payload(basis))
        .map_err(|e| DeliveryBindingBasisIntegrityError(e.to_string()))?;
    if digest != basis.delivery_binding_basis_digest {
        return Err(DeliveryBindingBasisIntegrityError(
            "delivery_binding_basis_digest 가 canonical recompute 와 불일치".into(),
        ));
    }
    Ok(())
}
/// Carry `parse_pattern`'s `Blocked`/`ContextError` outcomes to a different result type;
/// it never returns its placeholder `Ready(())`.
fn convert_pattern_result<T>(
    tokens: Result<Vec<PatternToken>, DeliveryPlanResult<()>>,
) -> Result<Vec<PatternToken>, DeliveryPlanResult<T>> {
    tokens.map_err(|err| match err {
        DeliveryPlanResult::Blocked(blockers) => DeliveryPlanResult::Blocked(blockers),
        DeliveryPlanResult::ContextError(error) => DeliveryPlanResult::ContextError(error),
        DeliveryPlanResult::Ready(()) => unreachable!(),
    })
}
/// Every filename-pattern token not already Active, either bound to a FieldBindingRule
/// (becomes an output-name requirement) or left as an unresolved-token blocker.
fn collect_output_name_requirements(
    tokens: &[PatternToken],
    active: &HashSet<&str>,
    by_field: &HashMap<&str, &FieldBindingRule>,
) -> (Vec<DeliveryOutputNameRequirement>, Vec<DeliveryPlanBlocker>) {
    let mut requirements = Vec::new();
    let mut blockers = Vec::new();
    for field in pattern_field_token_ids(tokens) {
        if active.contains(field.as_str()) {
            continue;
        }
        if let Some(rule) = by_field.get(field.as_str()) {
            requirements.push(DeliveryOutputNameRequirement {
                field_id: field,
                value_expression: encode_delivery_value_expression(rule),
            });
        } else {
            blockers.push(blocker(
                OUTPUT_NAME_TOKEN_UNRESOLVED,
                None,
                Some(&field),
                format!(
                    "filename token {} 에 대응하는 Active requirement·FieldBinding 규칙이 없다",
                    repr_text(&field)
                ),
            ));
        }
    }
    (requirements, blockers)
}
pub fn build_delivery_binding_basis(
    base_template_application_id: &str,
    field_binding_authority_revision: &str,
    filename_pattern_contract_id: &str,
    exact_pattern: &str,
    active_field_ids: &[String],
    binding_rules: &[FieldBindingRule],
    document_value_resolution_contract_id: &str,
) -> DeliveryPlanResult<GenerationDeliveryBindingBasis> {
    if document_value_resolution_contract_id != DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID {
        return DeliveryPlanResult::ContextError(context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            format!(
                "미지원 document value resolution contract: {}",
                repr_text(document_value_resolution_contract_id)
            ),
        ));
    }
    let tokens =
        match convert_pattern_result(parse_pattern(exact_pattern, filename_pattern_contract_id)) {
            Ok(tokens) => tokens,
            Err(result) => return result,
        };
    let ordered = match require_single_rule_per_field(binding_rules) {
        Ok(rules) => rules,
        Err(error) => {
            return DeliveryPlanResult::Blocked(vec![blocker(
                OUTPUT_NAME_BINDING_AMBIGUOUS,
                None,
                None,
                error.message,
            )]);
        }
    };
    let by_field: HashMap<_, _> = ordered
        .iter()
        .map(|rule| (rule.field_id.as_str(), rule))
        .collect();
    let active: HashSet<_> = active_field_ids.iter().map(String::as_str).collect();
    let (requirements, blockers) = collect_output_name_requirements(&tokens, &active, &by_field);
    if !blockers.is_empty() {
        return DeliveryPlanResult::Blocked(blockers);
    }
    let mut basis = GenerationDeliveryBindingBasis {
        base_template_application_id: base_template_application_id.into(),
        field_binding_authority_revision: field_binding_authority_revision.into(),
        filename_pattern_contract_id: filename_pattern_contract_id.into(),
        exact_pattern: exact_pattern.into(),
        document_value_resolution_contract_id: document_value_resolution_contract_id.into(),
        output_name_requirements: requirements,
        delivery_binding_basis_digest: String::new(),
    };
    basis.delivery_binding_basis_digest = match canonical_execution_digest(&basis_payload(&basis)) {
        Ok(digest) => digest,
        Err(error) => {
            return DeliveryPlanResult::ContextError(context(
                DELIVERY_BINDING_BASIS_INTEGRITY_ERROR,
                error.to_string(),
            ));
        }
    };
    DeliveryPlanResult::Ready(basis)
}

fn optional_str<'a>(
    expression: &'a Value,
    key: &str,
) -> Result<Option<&'a str>, DeliveryPlanContextError> {
    match expression.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => Ok(Some(s)),
        _ => Err(context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            format!("파일 이름 값의 {key} 형식 불량"),
        )),
    }
}
fn whitespace(text: &str, policy: &str) -> Result<String, DeliveryPlanContextError> {
    match policy {
        WHITESPACE_PRESERVE_EXACT => Ok(text.into()),
        WHITESPACE_STRIP_LEADING_TRAILING => Ok(text.trim_matches(python_whitespace).into()),
        _ => Err(context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            format!("미지원 whitespace policy: {}", repr_text(policy)),
        )),
    }
}
fn delivery_format(expression: &Value, text: &str) -> Result<String, DeliveryPlanContextError> {
    let kind = optional_str(expression, "format_kind")?;
    let code = optional_str(expression, "format_code")?;
    let slice =
        crate::field_binding::require_text_slice(expression.get("text_slice")).map_err(|e| {
            context(
                UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
                format!("파일 이름 값의 표시형·가공을 해석할 수 없다: {}", e.message),
            )
        })?;
    render_source_value(kind, code, slice.as_ref(), text).map_err(|e| {
        context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            format!("파일 이름 값의 표시형·가공을 해석할 수 없다: {}", e.message),
        )
    })
}
fn delivery_date(
    expression: &Value,
    clock: Option<NaiveDateTime>,
) -> Result<String, DeliveryPlanContextError> {
    if ["text_slice", "source_key", "canonical_value"]
        .iter()
        .any(|key| expression.get(*key).is_some_and(|v| !v.is_null()))
    {
        return Err(context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            "실행 시각 값에는 데이터 열·고정값·가공이 없다",
        ));
    }
    let kind = optional_str(expression, "format_kind")?;
    let code = optional_str(expression, "format_code")?;
    require_runtime_date_format(kind, code).map_err(|e| {
        context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            format!(
                "파일 이름 값의 실행 시각 표시형을 해석할 수 없다: {}",
                e.message
            ),
        )
    })?;
    let clock = clock.ok_or_else(|| {
        context(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            "실행 시각 토큰을 렌더할 captured_delivery_clock 이 없다",
        )
    })?;
    render_runtime_date(code.unwrap_or_default(), clock)
        .map_err(|e| context(UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT, e.message))
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DeliveryFieldValue {
    Text(String),
    Unresolved { code: String, detail: String },
}
fn resolve_constant_delivery_value(
    expression: &Value,
    policy: &crate::field_binding::DocumentContentValuePolicy,
) -> Result<DeliveryFieldValue, DeliveryPlanContextError> {
    let code = expression.get("format_code").unwrap_or(&Value::Null);
    let kind = expression.get("format_kind").unwrap_or(&Value::Null);
    let slice = expression.get("text_slice").unwrap_or(&Value::Null);
    if (!code.is_null() && code != "") || !kind.is_null() || !slice.is_null() {
        return Err(context(
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT,
            format!(
                "고정값에는 표시형·가공을 적용하지 않는다: {}/{}/{}",
                repr(kind),
                repr(code),
                repr(slice)
            ),
        ));
    }
    let canonical = expression
        .get("canonical_value")
        .filter(|v| v.is_object())
        .ok_or_else(|| {
            context(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                "CONSTANT requirement 에 canonical_value 가 없다",
            )
        })?;
    let text = canonical
        .get("text")
        .and_then(Value::as_str)
        .filter(|_| canonical.get("kind") == Some(&json!("TEXT")))
        .ok_or_else(|| {
            context(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                "CONSTANT requirement 의 canonical_value 형식 불량",
            )
        })?;
    Ok(DeliveryFieldValue::Text(whitespace(
        text,
        &policy.whitespace_policy,
    )?))
}
fn resolve_from_source_delivery_value(
    expression: &Value,
    snapshot: &RawDataRecordSnapshot,
    policy: &crate::field_binding::DocumentContentValuePolicy,
) -> Result<DeliveryFieldValue, DeliveryPlanContextError> {
    let key = expression
        .get("source_key")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            context(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                "FROM_SOURCE requirement 의 source_key 형식 불량",
            )
        })?;
    delivery_format(expression, "")?;
    match snapshot.value_for(key) {
        None => Ok(DeliveryFieldValue::Unresolved {
            code: OUTPUT_NAME_TOKEN_UNRESOLVED.into(),
            detail: format!("source key {} 가 raw record 에 없다", repr_text(key)),
        }),
        Some(CanonicalSourceValue::Null) => Ok(DeliveryFieldValue::Unresolved {
            code: OUTPUT_NAME_TOKEN_UNRESOLVED.into(),
            detail: format!("source key {} 가 explicit null", repr_text(key)),
        }),
        Some(CanonicalSourceValue::Text(text)) => Ok(DeliveryFieldValue::Text(delivery_format(
            expression,
            &whitespace(text, &policy.whitespace_policy)?,
        )?)),
    }
}
pub fn resolve_delivery_field_value(
    expression: &Value,
    snapshot: &RawDataRecordSnapshot,
    clock: Option<NaiveDateTime>,
) -> Result<DeliveryFieldValue, DeliveryPlanContextError> {
    let id = expression
        .get("document_content_value_policy_id")
        .unwrap_or(&Value::Null);
    let policy =
        resolve_document_value_policy(id.as_str().map_or_else(|| repr(id), str::to_owned).as_str())
            .map_err(|e| context(UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT, e.message))?;
    match expression.get("kind").and_then(Value::as_str) {
        Some("INTENTIONAL_BLANK") => Ok(DeliveryFieldValue::Unresolved {
            code: OUTPUT_NAME_TOKEN_UNRESOLVED.into(),
            detail: "INTENTIONAL_BLANK 은 filename token 으로 미해소".into(),
        }),
        Some("RUNTIME_DATE") => Ok(DeliveryFieldValue::Text(whitespace(
            &delivery_date(expression, clock)?,
            &policy.whitespace_policy,
        )?)),
        Some("CONSTANT") => resolve_constant_delivery_value(expression, &policy),
        Some("FROM_SOURCE") => resolve_from_source_delivery_value(expression, snapshot, &policy),
        _ => Err(context(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            format!(
                "미지원 delivery value expression kind: {}",
                repr(expression.get("kind").unwrap_or(&Value::Null))
            ),
        )),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedTokenValue {
    pub kind: String,
    pub field_id: Option<String>,
    pub value: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PathOccupancyEntry {
    pub relative_name: String,
    pub kind: String,
}
impl PathOccupancyEntry {
    pub fn validate(&self) -> Result<(), DeliveryPlanContextError> {
        if self.relative_name.is_empty()
            || ![REGULAR_FILE, NON_REGULAR].contains(&self.kind.as_str())
        {
            return Err(context(
                PATH_OCCUPANCY_OBSERVATION_MISMATCH,
                "path occupancy entry is invalid",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PathOccupancyObservation {
    pub output_directory: String,
    pub occupied_entries: Vec<PathOccupancyEntry>,
    pub observed_at: String,
}
impl PathOccupancyObservation {
    pub fn validate(&self) -> Result<(), DeliveryPlanContextError> {
        if self.output_directory.is_empty() || self.observed_at.is_empty() {
            return Err(context(
                PATH_OCCUPANCY_OBSERVATION_MISMATCH,
                "path occupancy observation context is required",
            ));
        }
        for entry in &self.occupied_entries {
            entry.validate()?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CurrentResolvedDeliveryItem {
    pub record_identity: String,
    pub item_ordinal: usize,
    pub resolved_output_relative_path: String,
    pub collision_disposition: String,
    pub resolved_token_values: Vec<ResolvedTokenValue>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CurrentResolvedDelivery {
    pub exact_pattern: String,
    pub captured_delivery_clock: String,
    pub output_directory: String,
    pub collision_policy: String,
    pub ordered_items: Vec<CurrentResolvedDeliveryItem>,
}

fn current_context(
    code: &str,
    detail: impl Into<String>,
) -> DeliveryPlanResult<CurrentResolvedDelivery> {
    DeliveryPlanResult::ContextError(context(code, detail))
}

fn token_blocker(ordinal: usize, field_id: &str, detail: impl Into<String>) -> DeliveryPlanBlocker {
    blocker(
        OUTPUT_NAME_TOKEN_UNRESOLVED,
        Some(ordinal),
        Some(field_id),
        detail,
    )
}

pub struct CurrentDeliveryInput<'a> {
    pub sealed_execution_plan: &'a SealedExecutionPlanSemanticPayload,
    pub ordered_validated_records: &'a [ValidatedDataRecord],
    pub ordered_raw_snapshots: &'a [RawDataRecordSnapshot],
    pub delivery_binding_basis: &'a GenerationDeliveryBindingBasis,
    pub exact_pattern: &'a str,
    pub captured_delivery_clock: &'a str,
    pub run_delivery_intent: &'a RunDeliveryIntent,
    pub path_occupancy: &'a PathOccupancyObservation,
    pub filename_pattern_contract_id: &'a str,
}

pub fn resolve_current_generation_delivery(
    input: CurrentDeliveryInput<'_>,
) -> DeliveryPlanResult<CurrentResolvedDelivery> {
    match resolve_current(input) {
        Ok(delivery) => DeliveryPlanResult::Ready(delivery),
        Err(other) => other,
    }
}

/// Bundled arguments for `validate_delivery_inputs` (kept under clippy's argument-count limit).
struct DeliveryInputCheck<'a> {
    contract: &'a str,
    intent: &'a RunDeliveryIntent,
    occupancy: &'a PathOccupancyObservation,
    basis: &'a GenerationDeliveryBindingBasis,
    exact_pattern: &'a str,
    plan: &'a SealedExecutionPlanSemanticPayload,
    snapshots_len: usize,
    records_len: usize,
}
/// Stage 1+2: filename-pattern contract, collision policy, and occupancy-observation checks,
/// then the delivery binding basis's self-digest and its binding to this Plan/pattern/input shape.
fn validate_delivery_inputs(
    check: DeliveryInputCheck<'_>,
) -> Result<(), DeliveryPlanResult<CurrentResolvedDelivery>> {
    let DeliveryInputCheck {
        contract,
        intent,
        occupancy,
        basis,
        exact_pattern,
        plan,
        snapshots_len,
        records_len,
    } = check;
    if contract != FILENAME_PATTERN_CONTRACT_ID {
        return Err(current_context(
            UNSUPPORTED_FILENAME_PATTERN_CONTRACT,
            format!("미지원 filename pattern contract: {}", repr_text(contract)),
        ));
    }
    if !COLLISION_POLICIES.contains(&intent.collision_policy.as_str()) {
        return Err(current_context(
            UNSUPPORTED_OVERWRITE_POLICY,
            format!(
                "미지원 collision policy: {}",
                repr_text(&intent.collision_policy)
            ),
        ));
    }
    occupancy
        .validate()
        .map_err(DeliveryPlanResult::ContextError)?;
    if occupancy.output_directory != intent.output_directory {
        return Err(current_context(
            PATH_OCCUPANCY_OBSERVATION_MISMATCH,
            "filesystem observation output directory 가 RunDeliveryIntent 와 불일치",
        ));
    }
    verify_delivery_binding_basis_integrity(basis)
        .map_err(|e| current_context(DELIVERY_BINDING_BASIS_INTEGRITY_ERROR, e.0))?;
    if basis.filename_pattern_contract_id != contract
        || basis.exact_pattern != exact_pattern
        || basis.base_template_application_id
            != plan.execution_basis.template.template_application_id
    {
        return Err(current_context(
            DELIVERY_BINDING_BASIS_INTEGRITY_ERROR,
            "delivery binding basis 가 current Plan/pattern 과 불일치",
        ));
    }
    if snapshots_len != records_len {
        return Err(current_context(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            "ordered raw snapshots 와 current validated records 개수 불일치",
        ));
    }
    Ok(())
}
/// Shared, borrowed-from-input context for resolving every record's filename tokens.
struct ResolutionContext<'a> {
    clock: NaiveDateTime,
    tokens: Vec<PatternToken>,
    inactive: HashMap<&'a str, &'a Value>,
    runtime: HashMap<&'a str, &'a Value>,
    expected_plan: String,
    expected_basis: String,
}
/// Parses the runtime clock and filename pattern, and precomputes the inactive/runtime
/// token maps plus the Plan/basis digests every record is checked against.
fn prepare_resolution_context<'a>(
    captured_delivery_clock: &str,
    exact_pattern: &str,
    basis: &'a GenerationDeliveryBindingBasis,
    plan: &'a SealedExecutionPlanSemanticPayload,
) -> Result<ResolutionContext<'a>, DeliveryPlanResult<CurrentResolvedDelivery>> {
    let clock = parse_runtime_clock(Some(captured_delivery_clock)).map_err(|_| {
        current_context(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            format!(
                "captured_delivery_clock 이 유효한 ISO 8601 이 아니다: {}",
                repr_text(captured_delivery_clock)
            ),
        )
    })?;
    let tokens = parse_filename_pattern(&Value::String(exact_pattern.into())).map_err(|e| {
        DeliveryPlanResult::Blocked(vec![blocker(
            OUTPUT_NAME_PATTERN_INVALID,
            None,
            None,
            e.detail,
        )])
    })?;
    let inactive: HashMap<_, _> = basis
        .output_name_requirements
        .iter()
        .map(|r| (r.field_id.as_str(), &r.value_expression))
        .collect();
    let runtime: HashMap<_, _> = plan
        .active_field_requirements
        .iter()
        .filter_map(|item| {
            let expression = item.get("value_expression")?;
            if expression.get("kind").and_then(Value::as_str) == Some("RUNTIME_DATE") {
                Some((item.get("field_id")?.as_str()?, expression))
            } else {
                None
            }
        })
        .collect();
    let expected_plan = plan_semantic_digest(plan)
        .map_err(|e| current_context(GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR, e.to_string()))?;
    let expected_basis = execution_basis_digest(&plan.execution_basis)
        .map_err(|e| current_context(GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR, e.to_string()))?;
    Ok(ResolutionContext {
        clock,
        tokens,
        inactive,
        runtime,
        expected_plan,
        expected_basis,
    })
}
/// One filename token's value for one record: a blocker when it is Unresolved or
/// resolves to empty text, otherwise it is inserted into `values` and `None` is returned.
fn resolve_token_field(
    field: &str,
    ordinal: usize,
    snapshot: &RawDataRecordSnapshot,
    active: &HashMap<String, String>,
    ctx: &ResolutionContext<'_>,
    values: &mut Map<String, Value>,
) -> Result<Option<DeliveryPlanBlocker>, DeliveryPlanResult<CurrentResolvedDelivery>> {
    let value = if let Some(expression) = ctx.runtime.get(field) {
        resolve_delivery_field_value(expression, snapshot, Some(ctx.clock))
    } else if let Some(text) = active.get(field) {
        Ok(DeliveryFieldValue::Text(text.clone()))
    } else if let Some(expression) = ctx.inactive.get(field) {
        resolve_delivery_field_value(expression, snapshot, Some(ctx.clock))
    } else {
        Ok(DeliveryFieldValue::Unresolved {
            code: OUTPUT_NAME_TOKEN_UNRESOLVED.into(),
            detail: format!(
                "filename token {} 이 Active 도 delivery basis 도 아니다",
                repr_text(field)
            ),
        })
    }
    .map_err(DeliveryPlanResult::ContextError)?;
    match value {
        DeliveryFieldValue::Unresolved { code, detail } => {
            Ok(Some(blocker(&code, Some(ordinal), Some(field), detail)))
        }
        DeliveryFieldValue::Text(text) if text.is_empty() => Ok(Some(token_blocker(
            ordinal,
            field,
            format!(
                "filename token {} 이 빈 logical text 로 해석됨",
                repr_text(field)
            ),
        ))),
        DeliveryFieldValue::Text(text) => {
            values.insert(field.to_owned(), Value::String(text));
            Ok(None)
        }
    }
}
/// Either this item's blockers (the batch keeps going), or its rendered base name and
/// resolved token values ready for path assignment.
enum RecordResolution {
    Blocked(Vec<DeliveryPlanBlocker>),
    Ready(String, Vec<ResolvedTokenValue>),
}
/// Verifies one record's raw-snapshot and VDR integrity, then resolves every filename
/// token and renders its base output name.
fn resolve_record_item(
    ordinal: usize,
    snapshot: &RawDataRecordSnapshot,
    record: &ValidatedDataRecord,
    plan: &SealedExecutionPlanSemanticPayload,
    ctx: &ResolutionContext<'_>,
) -> Result<RecordResolution, DeliveryPlanResult<CurrentResolvedDelivery>> {
    verify_raw_record_snapshot(snapshot).map_err(|e| {
        current_context(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            format!("item {ordinal} raw snapshot 무결성 실패: {e}"),
        )
    })?;
    if let Some(mismatch) = check_validated_record_for_delivery(
        record,
        plan,
        snapshot,
        &ctx.expected_plan,
        &ctx.expected_basis,
    )
    .map_err(|e| {
        current_context(
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
            format!("item {ordinal} VDR 완결성 실패: {e}"),
        )
    })? {
        return Err(current_context(
            if mismatch == "plan" {
                CURRENT_RECORD_VALIDATION_BASIS_MISMATCH
            } else {
                RAW_VALIDATED_RECORD_MISMATCH
            },
            format!("item {ordinal} VDR 결속 불일치: {mismatch}"),
        ));
    }
    let active: HashMap<_, _> = record
        .document_values_in_order()
        .map_err(|e| {
            current_context(
                GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                format!("item {ordinal} VDR 완결성 실패: {e}"),
            )
        })?
        .into_iter()
        .collect();
    let mut values = Map::new();
    let mut item_blockers = Vec::new();
    for field in pattern_field_token_ids(&ctx.tokens) {
        if let Some(item) =
            resolve_token_field(&field, ordinal, snapshot, &active, ctx, &mut values)?
        {
            item_blockers.push(item);
        }
    }
    if !item_blockers.is_empty() {
        return Ok(RecordResolution::Blocked(item_blockers));
    }
    let (name, parts) = render_output_name(
        &ctx.tokens,
        &values,
        ordinal as i64 + 1,
        Some(ctx.clock),
        false,
    )
    .map_err(|e| {
        current_context(
            e.code.unwrap_or(GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR),
            e.detail,
        )
    })?;
    guard_output_name(&name).map_err(|e| {
        current_context(
            e.code.unwrap_or(GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR),
            e.detail,
        )
    })?;
    Ok(RecordResolution::Ready(
        name,
        parts
            .into_iter()
            .map(|p| ResolvedTokenValue {
                kind: p.kind.into(),
                field_id: p.field_id,
                value: p.text,
            })
            .collect(),
    ))
}
/// Per-batch accumulators: cross-record blockers, each item's base name, and each item's
/// resolved token values.
type RecordResolutionBatch = (
    Vec<DeliveryPlanBlocker>,
    Vec<String>,
    Vec<Vec<ResolvedTokenValue>>,
);
/// Stage 3: resolves every record in order, accumulating blockers across the whole batch
/// rather than stopping at the first blocked item.
fn resolve_all_records(
    plan: &SealedExecutionPlanSemanticPayload,
    snapshots: &[RawDataRecordSnapshot],
    records: &[ValidatedDataRecord],
    ctx: &ResolutionContext<'_>,
) -> Result<RecordResolutionBatch, DeliveryPlanResult<CurrentResolvedDelivery>> {
    let mut blockers = Vec::new();
    let mut base_names = Vec::new();
    let mut token_values = Vec::new();
    for (ordinal, (snapshot, record)) in snapshots.iter().zip(records).enumerate() {
        match resolve_record_item(ordinal, snapshot, record, plan, ctx)? {
            RecordResolution::Blocked(item_blockers) => {
                blockers.extend(item_blockers);
                base_names.push(String::new());
                token_values.push(Vec::new());
            }
            RecordResolution::Ready(name, parts) => {
                base_names.push(name);
                token_values.push(parts);
            }
        }
    }
    Ok((blockers, base_names, token_values))
}
/// Stage 4: the occupied/folded/non-regular path sets, the deduped output paths
/// (suffix-deduped against existing occupancy only under `ADD_SUFFIX`), and the
/// collision-policy blockers for paths that land on occupied or non-regular entries.
fn resolve_paths_and_conflicts(
    intent: &RunDeliveryIntent,
    occupancy: &PathOccupancyObservation,
    base_names: &[String],
) -> (Vec<String>, HashSet<String>, Vec<DeliveryPlanBlocker>) {
    let occupied: Vec<String> = occupancy
        .occupied_entries
        .iter()
        .map(|e| e.relative_name.clone())
        .collect();
    let folded: HashSet<String> = occupied.iter().map(|n| collision_key(n)).collect();
    let non_regular: HashSet<String> = occupancy
        .occupied_entries
        .iter()
        .filter(|e| e.kind == NON_REGULAR)
        .map(|e| collision_key(&e.relative_name))
        .collect();
    let paths = if intent.collision_policy == "ADD_SUFFIX" {
        dedupe_output_names(base_names, &occupied)
    } else {
        dedupe_output_names(base_names, &[])
    };
    let conflicts = paths
        .iter()
        .enumerate()
        .filter_map(|(ordinal, path)| {
            let key = collision_key(path);
            if intent.collision_policy == "FAIL" && folded.contains(&key) {
                let code = if non_regular.contains(&key) {
                    OUTPUT_PATH_NON_REGULAR_CONFLICT
                } else {
                    OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED
                };
                let mut item = blocker(
                    code,
                    Some(ordinal),
                    None,
                    format!("existing output path: {path}"),
                );
                item.conflicting_relative_path = Some(path.clone());
                Some(item)
            } else if intent.collision_policy == "OVERWRITE_EXPLICIT" && non_regular.contains(&key)
            {
                let mut item = blocker(
                    OUTPUT_PATH_NON_REGULAR_CONFLICT,
                    Some(ordinal),
                    None,
                    format!("non-regular output path: {path}"),
                );
                item.conflicting_relative_path = Some(path.clone());
                Some(item)
            } else {
                None
            }
        })
        .collect();
    (paths, folded, conflicts)
}
/// Stage 5: assembles the final ordered items, including the per-item collision disposition.
fn assemble_items(
    records: &[ValidatedDataRecord],
    base_names: &[String],
    paths: &[String],
    token_values: Vec<Vec<ResolvedTokenValue>>,
    intent: &RunDeliveryIntent,
    folded: &HashSet<String>,
) -> Result<Vec<CurrentResolvedDeliveryItem>, DeliveryPlanResult<CurrentResolvedDelivery>> {
    let mut items = Vec::with_capacity(records.len());
    for (ordinal, ((record, base_name), (path, resolved_tokens))) in records
        .iter()
        .zip(base_names)
        .zip(paths.iter().zip(token_values))
        .enumerate()
    {
        guard_output_name(path).map_err(|e| {
            current_context(
                e.code.unwrap_or(GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR),
                e.detail,
            )
        })?;
        let disposition = if intent.collision_policy == "OVERWRITE_EXPLICIT"
            && folded.contains(&collision_key(path))
        {
            WRITE_OVERWRITE
        } else if intent.collision_policy == "ADD_SUFFIX" && path != base_name {
            WRITE_ADD_SUFFIX
        } else {
            WRITE_NEW
        };
        let identity = record
            .semantic_payload_encoded
            .get("record_identity")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                current_context(
                    GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR,
                    "VDR record_identity 형식 불량",
                )
            })?;
        items.push(CurrentResolvedDeliveryItem {
            record_identity: identity.into(),
            item_ordinal: ordinal,
            resolved_output_relative_path: path.clone(),
            collision_disposition: disposition.into(),
            resolved_token_values: resolved_tokens,
        });
    }
    Ok(items)
}
fn resolve_current(
    input: CurrentDeliveryInput<'_>,
) -> Result<CurrentResolvedDelivery, DeliveryPlanResult<CurrentResolvedDelivery>> {
    let CurrentDeliveryInput {
        sealed_execution_plan: plan,
        ordered_validated_records: records,
        ordered_raw_snapshots: snapshots,
        delivery_binding_basis: basis,
        exact_pattern,
        captured_delivery_clock,
        run_delivery_intent: intent,
        path_occupancy: occupancy,
        filename_pattern_contract_id: contract,
    } = input;
    validate_delivery_inputs(DeliveryInputCheck {
        contract,
        intent,
        occupancy,
        basis,
        exact_pattern,
        plan,
        snapshots_len: snapshots.len(),
        records_len: records.len(),
    })?;
    let ctx = prepare_resolution_context(captured_delivery_clock, exact_pattern, basis, plan)?;
    let (mut blockers, base_names, token_values) =
        resolve_all_records(plan, snapshots, records, &ctx)?;
    if !blockers.is_empty() {
        blockers.sort_by(|a, b| {
            (
                a.item_ordinal,
                a.code.as_str(),
                a.field_id.as_deref().unwrap_or(""),
            )
                .cmp(&(
                    b.item_ordinal,
                    b.code.as_str(),
                    b.field_id.as_deref().unwrap_or(""),
                ))
        });
        return Err(DeliveryPlanResult::Blocked(blockers));
    }
    let (paths, folded, conflicts) = resolve_paths_and_conflicts(intent, occupancy, &base_names);
    if !conflicts.is_empty() {
        return Err(DeliveryPlanResult::Blocked(conflicts));
    }
    Ok(CurrentResolvedDelivery {
        exact_pattern: exact_pattern.into(),
        captured_delivery_clock: captured_delivery_clock.into(),
        output_directory: intent.output_directory.clone(),
        collision_policy: intent.collision_policy.clone(),
        ordered_items: assemble_items(records, &base_names, &paths, token_values, intent, &folded)?,
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ManagedRunAdmission {
    pub construction_allowed: bool,
    pub materialization_startable: bool,
    pub status: String,
}

pub fn evaluate_managed_run_admission(
    runtime_registry: &RuntimeMaterializerConformanceRegistry,
    sealed_execution_plan: &SealedExecutionPlanSemanticPayload,
    runtime_capability_manifest_digest: &str,
) -> ManagedRunAdmission {
    let contracts = &sealed_execution_plan.execution_basis.contracts;
    let admitted = runtime_registry.is_admitted(&RuntimeConformanceQuery {
        runtime_capability_manifest_digest,
        materialization_contract_id: &contracts.roles.materialization_contract_id,
        materialization_base_contract_id: &contracts.roles.materialization_base_contract_id,
        native_primitive_contract_id: &contracts.roles.native_primitive_contract_id,
        composition_contract_id: &contracts.roles.composition_contract_id,
        plan_schema_version: &sealed_execution_plan.plan_schema_version,
        canonical_encoding_version: &sealed_execution_plan.canonical_encoding_version,
    });
    ManagedRunAdmission {
        construction_allowed: true,
        materialization_startable: admitted,
        status: if admitted {
            MANAGED_RUN_STARTABLE
        } else {
            MANAGED_RUN_CONSTRUCTION_ONLY
        }
        .into(),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::field_binding::resolve_document_value_policy;
    use crate::raw_data_record::{RawRecordCaptureProvenance, build_raw_record_snapshot};
    use crate::record_validation::{
        ValidateDataRecordResult, tests::one_source_plan, validate_data_record_against_plan,
    };
    use crate::run_delivery_intent::RunDeliveryIntent;

    #[test]
    fn inactive_basis_is_digest_bound_and_does_not_admit_missing_tokens() {
        let rule = FieldBindingRule {
            field_id: "부서".into(),
            binding_kind: SOURCE.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: Some("dept".into()),
            format_code: None,
            canonical_constant_value: None,
            format_kind: None,
            text_slice: None,
        };
        let built = build_delivery_binding_basis(
            "app-1",
            "rev-7",
            FILENAME_PATTERN_CONTRACT_ID,
            "{{부서}}",
            &[],
            &[rule],
            DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
        );
        let DeliveryPlanResult::Ready(mut basis) = built else {
            panic!("valid inactive binding refused")
        };
        assert_eq!(
            basis.output_name_requirements[0].value_expression["source_key"],
            "dept"
        );
        verify_delivery_binding_basis_integrity(&basis).unwrap();
        basis.field_binding_authority_revision = "rev-8".into();
        assert!(verify_delivery_binding_basis_integrity(&basis).is_err());

        let missing = build_delivery_binding_basis(
            "app-1",
            "rev-7",
            FILENAME_PATTERN_CONTRACT_ID,
            "{{없는필드}}",
            &[],
            &[],
            DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
        );
        let DeliveryPlanResult::Blocked(blockers) = missing else {
            panic!("unbound token admitted")
        };
        assert_eq!(blockers[0].code, OUTPUT_NAME_TOKEN_UNRESOLVED);

        let snapshot = build_raw_record_snapshot(
            &["dept".into()],
            vec![("dept".into(), CanonicalSourceValue::Text("본과".into()))],
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "2026-11-05T10:00:00".into(),
                source_observation_ref: None,
            },
        )
        .unwrap();
        let source = json!({"kind":"FROM_SOURCE","source_key":"dept",
            "document_content_value_policy_id":"document-content-value/v1"});
        assert_eq!(
            resolve_delivery_field_value(&source, &snapshot, None).unwrap(),
            DeliveryFieldValue::Text("본과".into())
        );
        let absent = json!({"kind":"FROM_SOURCE","source_key":"missing",
            "document_content_value_policy_id":"document-content-value/v1"});
        assert!(matches!(
            resolve_delivery_field_value(&absent, &snapshot, None).unwrap(),
            DeliveryFieldValue::Unresolved { code, .. } if code == OUTPUT_NAME_TOKEN_UNRESOLVED
        ));
        let null = build_raw_record_snapshot(
            &["dept".into()],
            vec![("dept".into(), CanonicalSourceValue::Null)],
            "row-2",
            snapshot.capture_provenance.clone(),
        )
        .unwrap();
        assert!(matches!(
            resolve_delivery_field_value(&source, &null, None).unwrap(),
            DeliveryFieldValue::Unresolved { code, .. } if code == OUTPUT_NAME_TOKEN_UNRESOLVED
        ));
        let constant = json!({"kind":"CONSTANT","canonical_value":{"kind":"TEXT","text":"고정"},
            "document_content_value_policy_id":"document-content-value/v1"});
        assert_eq!(
            resolve_delivery_field_value(&constant, &snapshot, None).unwrap(),
            DeliveryFieldValue::Text("고정".into())
        );
        let malformed = json!({"kind":"CONSTANT",
            "document_content_value_policy_id":"document-content-value/v1"});
        assert_eq!(
            resolve_delivery_field_value(&malformed, &snapshot, None)
                .unwrap_err()
                .code,
            GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR
        );
        let amount = build_raw_record_snapshot(
            &["dept".into()],
            vec![(
                "dept".into(),
                CanonicalSourceValue::Text("170,309,180원 (VAT 포함)".into()),
            )],
            "row-3",
            snapshot.capture_provenance.clone(),
        )
        .unwrap();
        let sliced_amount = json!({
            "kind":"FROM_SOURCE", "source_key":"dept", "format_kind":"amount",
            "format_code":"", "document_content_value_policy_id":"document-content-value/v1",
            "text_slice":{"mode":"split","delimiter":"원","index":1}
        });
        assert_eq!(
            resolve_delivery_field_value(&sliced_amount, &amount, None).unwrap(),
            DeliveryFieldValue::Text("170,309,180원".into())
        );
        let mut malformed_slice = sliced_amount;
        malformed_slice["text_slice"] = json!({"mode":"unknown"});
        assert_eq!(
            resolve_delivery_field_value(&malformed_slice, &amount, None)
                .unwrap_err()
                .code,
            UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT
        );
        for expression in [
            json!({"kind":"FROM_SOURCE","source_key":"dept","format_kind":"unknown",
                "document_content_value_policy_id":"document-content-value/v1"}),
            json!({"kind":"FROM_SOURCE","source_key":"dept","format_code":42,
                "document_content_value_policy_id":"document-content-value/v1"}),
            json!({"kind":"FROM_SOURCE","source_key":"dept",
                "document_content_value_policy_id":"unknown"}),
        ] {
            assert_eq!(
                resolve_delivery_field_value(&expression, &snapshot, None)
                    .unwrap_err()
                    .code,
                UNSUPPORTED_DELIVERY_VALUE_RESOLUTION_CONTRACT
            );
        }
        assert!(matches!(
            build_delivery_binding_basis(
                "app-1", "rev-7", "unknown", "{{부서}}", &[], &[],
                DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
            ),
            DeliveryPlanResult::ContextError(error)
                if error.code == UNSUPPORTED_FILENAME_PATTERN_CONTRACT
        ));
        assert!(matches!(
            build_delivery_binding_basis(
                "app-1", "rev-7", FILENAME_PATTERN_CONTRACT_ID, "{{부서", &[], &[],
                DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
            ),
            DeliveryPlanResult::Blocked(blockers)
                if blockers[0].code == OUTPUT_NAME_PATTERN_INVALID
        ));
    }

    #[test]
    fn active_and_inactive_runtime_tokens_share_delivery_clock_across_midnight() {
        let snapshot = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text("홍길동".into()))],
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "2026-06-15T09:00:00".into(),
                source_observation_ref: None,
            },
        )
        .unwrap();
        let inactive = FieldBindingRule {
            field_id: "나중".into(),
            binding_kind: RUNTIME_DATE.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: None,
            canonical_constant_value: None,
            text_slice: None,
            format_kind: Some("date".into()),
            format_code: Some("%Y.%m.%d".into()),
        };
        let expression = json!({"kind":"RUNTIME_DATE","format_kind":"date","format_code":"%Y.%m.%d","document_content_value_policy_id":"document-content-value/v1"});
        assert!(resolve_delivery_field_value(&expression, &snapshot, None).is_err());
        assert_eq!(
            resolve_delivery_field_value(
                &expression,
                &snapshot,
                Some(
                    crate::field_binding::parse_runtime_clock(Some("2026-06-15T18:04:00")).unwrap()
                )
            )
            .unwrap(),
            DeliveryFieldValue::Text("2026.06.15".into())
        );
        for (plan, pattern, expected, rules) in [
            (
                crate::record_validation::tests::runtime_date_plan(),
                "{{date:%Y%m%d}}-{{작성일}}-{{이름}}",
                "20260616-2026-06-16-홍길동.hwpx",
                vec![],
            ),
            (
                one_source_plan(),
                "{{이름}}-{{나중}}",
                "홍길동-2026.06.16.hwpx",
                vec![inactive],
            ),
        ] {
            let ValidateDataRecordResult::Validated(record) = validate_data_record_against_plan(
                &plan,
                &snapshot,
                None,
                false,
                "2026-06-15T23:59:59",
                Some("2026-06-15T23:59:59"),
            ) else {
                panic!("preview must validate before midnight");
            };
            let fields = plan
                .active_field_requirements
                .iter()
                .map(|item| item["field_id"].as_str().unwrap().to_owned())
                .collect::<Vec<_>>();
            let DeliveryPlanResult::Ready(basis) = build_delivery_binding_basis(
                "application",
                "revision",
                FILENAME_PATTERN_CONTRACT_ID,
                pattern,
                &fields,
                &rules,
                DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
            ) else {
                panic!("date token must form a binding basis");
            };
            if !rules.is_empty() {
                assert_eq!(basis.output_name_requirements.len(), 1);
                assert_eq!(
                    basis.output_name_requirements[0].value_expression,
                    expression
                );
            }
            let intent = RunDeliveryIntent::new("C:/out").unwrap();
            let occupancy = PathOccupancyObservation {
                output_directory: "C:/out".into(),
                occupied_entries: vec![],
                observed_at: "2026-06-16T00:00:01".into(),
            };
            let result = resolve_current_generation_delivery(CurrentDeliveryInput {
                sealed_execution_plan: &plan,
                ordered_validated_records: &[*record],
                ordered_raw_snapshots: std::slice::from_ref(&snapshot),
                delivery_binding_basis: &basis,
                exact_pattern: pattern,
                captured_delivery_clock: "2026-06-16T00:00:01",
                run_delivery_intent: &intent,
                path_occupancy: &occupancy,
                filename_pattern_contract_id: FILENAME_PATTERN_CONTRACT_ID,
            });
            let DeliveryPlanResult::Ready(delivery) = result else {
                panic!("delivery must resolve the new day's date");
            };
            assert_eq!(
                delivery.ordered_items[0].resolved_output_relative_path,
                expected
            );
        }
    }

    #[test]
    fn current_delivery_resolves_a_valid_record_and_refuses_occupied_or_forged_paths() {
        let plan = one_source_plan();
        let snapshot = build_raw_record_snapshot(
            &["열".into()],
            vec![("열".into(), CanonicalSourceValue::Text("홍길동".into()))],
            "row-1",
            RawRecordCaptureProvenance {
                source_adapter_contract_id: "excel/v1".into(),
                captured_at: "2026-11-05T18:04:03".into(),
                source_observation_ref: None,
            },
        )
        .unwrap();
        let ValidateDataRecordResult::Validated(record) = validate_data_record_against_plan(
            &plan,
            &snapshot,
            None,
            false,
            "2026-11-05T18:04:04",
            None,
        ) else {
            panic!("valid record must validate");
        };
        let records = vec![*record];
        let snapshots = vec![snapshot.clone()];
        let pattern = "공고-{{이름}}-{{seq:001}}";
        let DeliveryPlanResult::Ready(basis) = build_delivery_binding_basis(
            "application",
            "revision",
            FILENAME_PATTERN_CONTRACT_ID,
            pattern,
            &["이름".into()],
            &[],
            DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
        ) else {
            panic!("active token must form a delivery basis");
        };
        let mut intent = RunDeliveryIntent::new("C:/out").unwrap();
        let mut occupancy = PathOccupancyObservation {
            output_directory: "C:/out".into(),
            occupied_entries: vec![],
            observed_at: "2026-11-05T18:04:05".into(),
        };
        let resolve = |intent: &RunDeliveryIntent,
                       occupancy: &PathOccupancyObservation,
                       snapshots: &[RawDataRecordSnapshot]| {
            resolve_current_generation_delivery(CurrentDeliveryInput {
                sealed_execution_plan: &plan,
                ordered_validated_records: &records,
                ordered_raw_snapshots: snapshots,
                delivery_binding_basis: &basis,
                exact_pattern: pattern,
                captured_delivery_clock: "2026-11-05T18:04:03",
                run_delivery_intent: intent,
                path_occupancy: occupancy,
                filename_pattern_contract_id: FILENAME_PATTERN_CONTRACT_ID,
            })
        };
        let DeliveryPlanResult::Ready(current) = resolve(&intent, &occupancy, &snapshots) else {
            panic!("current delivery must resolve");
        };
        assert_eq!(
            current.ordered_items[0].resolved_output_relative_path,
            "공고-홍길동-001.hwpx"
        );
        assert_eq!(current.ordered_items[0].collision_disposition, WRITE_NEW);

        occupancy.occupied_entries.push(PathOccupancyEntry {
            relative_name: "공고-홍길동-001.hwpx".into(),
            kind: REGULAR_FILE.into(),
        });
        intent.collision_policy = "FAIL".into();
        let DeliveryPlanResult::Blocked(blockers) = resolve(&intent, &occupancy, &snapshots) else {
            panic!("occupied FAIL path must block");
        };
        assert_eq!(blockers[0].code, OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED);
        intent.collision_policy = "ADD_SUFFIX".into();
        let DeliveryPlanResult::Ready(current) = resolve(&intent, &occupancy, &snapshots) else {
            panic!("suffix policy must resolve without overwriting");
        };
        assert_eq!(
            current.ordered_items[0].resolved_output_relative_path,
            "공고-홍길동-001_1.hwpx"
        );
        assert_eq!(
            current.ordered_items[0].collision_disposition,
            WRITE_ADD_SUFFIX
        );
        intent.collision_policy = "OVERWRITE_EXPLICIT".into();
        let DeliveryPlanResult::Ready(current) = resolve(&intent, &occupancy, &snapshots) else {
            panic!("explicit overwrite of a regular file must be identified");
        };
        assert_eq!(
            current.ordered_items[0].collision_disposition,
            WRITE_OVERWRITE
        );
        occupancy.occupied_entries[0].kind = NON_REGULAR.into();
        let DeliveryPlanResult::Blocked(blockers) = resolve(&intent, &occupancy, &snapshots) else {
            panic!("non-regular output must never be overwritten");
        };
        assert_eq!(blockers[0].code, OUTPUT_PATH_NON_REGULAR_CONFLICT);

        let mut forged = snapshot;
        forged.raw_record_digest = "sha256:forged".into();
        let DeliveryPlanResult::ContextError(failure) = resolve(&intent, &occupancy, &[forged])
        else {
            panic!("forged raw snapshot must fail closed");
        };
        assert_eq!(failure.code, GENERATION_DELIVERY_PLAN_INTEGRITY_ERROR);
    }

    #[test]
    fn current_batch_deduplicates_case_insensitively_without_disk_and_refuses_stale_basis() {
        let plan = one_source_plan();
        let provenance = RawRecordCaptureProvenance {
            source_adapter_contract_id: "excel/v1".into(),
            captured_at: "2026-11-05T18:04:03".into(),
            source_observation_ref: None,
        };
        let mut snapshots = Vec::new();
        let mut records = Vec::new();
        for (identity, text) in [("row-1", "Report"), ("row-2", "report")] {
            let snapshot = build_raw_record_snapshot(
                &["열".into()],
                vec![("열".into(), CanonicalSourceValue::Text(text.into()))],
                identity,
                provenance.clone(),
            )
            .unwrap();
            let ValidateDataRecordResult::Validated(record) = validate_data_record_against_plan(
                &plan,
                &snapshot,
                None,
                false,
                "2026-11-05T18:04:04",
                None,
            ) else {
                panic!("valid source row refused")
            };
            snapshots.push(snapshot);
            records.push(*record);
        }
        let pattern = "{{이름}}";
        let DeliveryPlanResult::Ready(basis) = build_delivery_binding_basis(
            "application",
            "revision",
            FILENAME_PATTERN_CONTRACT_ID,
            pattern,
            &["이름".into()],
            &[],
            DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID,
        ) else {
            panic!("active token refused")
        };
        let mut intent = RunDeliveryIntent::new("C:/out").unwrap();
        intent.collision_policy = "ADD_SUFFIX".into();
        let occupancy = PathOccupancyObservation {
            output_directory: "C:/out".into(),
            occupied_entries: vec![],
            observed_at: "2026-11-05T18:04:05".into(),
        };
        let resolve = |basis: &GenerationDeliveryBindingBasis| {
            resolve_current_generation_delivery(CurrentDeliveryInput {
                sealed_execution_plan: &plan,
                ordered_validated_records: &records,
                ordered_raw_snapshots: &snapshots,
                delivery_binding_basis: basis,
                exact_pattern: pattern,
                captured_delivery_clock: "2026-11-05T18:04:03",
                run_delivery_intent: &intent,
                path_occupancy: &occupancy,
                filename_pattern_contract_id: FILENAME_PATTERN_CONTRACT_ID,
            })
        };
        let DeliveryPlanResult::Ready(delivery) = resolve(&basis) else {
            panic!("valid batch refused")
        };
        assert_eq!(
            delivery
                .ordered_items
                .iter()
                .map(|item| item.resolved_output_relative_path.as_str())
                .collect::<Vec<_>>(),
            ["Report.hwpx", "report_1.hwpx"]
        );
        assert_eq!(
            delivery
                .ordered_items
                .iter()
                .map(|item| item.collision_disposition.as_str())
                .collect::<Vec<_>>(),
            [WRITE_NEW, WRITE_ADD_SUFFIX]
        );
        let mut stale = basis;
        stale.field_binding_authority_revision = "other-revision".into();
        let DeliveryPlanResult::ContextError(error) = resolve(&stale) else {
            panic!("stale basis admitted")
        };
        assert_eq!(error.code, DELIVERY_BINDING_BASIS_INTEGRITY_ERROR);
    }
}
