//! Exact product field-binding contract, value policy, and versioned canonical framing.

use crate::format_engine;
use crate::text_render::python_repr;
use crate::text_slice::{TextSlice, apply_text_slice, keys as slice_keys, text_slice_from_payload};
use chrono::NaiveDateTime;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fmt;

pub const FIELD_BINDING_SEMANTIC_VERSION: &str = "field-binding/v5";
pub const FIELD_BINDING_SEMANTIC_VERSION_V4: &str = "field-binding/v4";
pub const FIELD_BINDING_SEMANTIC_VERSION_V3: &str = "field-binding/v3";
pub const FIELD_BINDING_SEMANTIC_VERSION_V2: &str = "field-binding/v2";
pub const SOURCE_SCHEMA_VERSION: &str = "source-schema/v2";
pub const BINDING_VALUE_VERSION: &str = "binding-value/v2";
pub const DOCUMENT_CONTENT_VALUE_POLICY_VERSION: &str = "document-content-value/v2";
pub const SOURCE: &str = "SOURCE";
pub const CONSTANT: &str = "CONSTANT";
pub const INTENTIONAL_BLANK: &str = "INTENTIONAL_BLANK";
pub const RUNTIME_DATE: &str = "RUNTIME_DATE";
pub const EXACT_BLANK_POLICY: &str = "WRITE_EMPTY_TEXT_PRESERVE_FIELD";
pub const WHITESPACE_PRESERVE_EXACT: &str = "PRESERVE_EXACT";
pub const WHITESPACE_STRIP_LEADING_TRAILING: &str = "STRIP_LEADING_TRAILING";
pub const ESCAPING_NATIVE_MATERIALIZER: &str = "NATIVE_MATERIALIZER";
pub const ESCAPING_PLAINTEXT_MATERIALIZER: &str = "PLAINTEXT_MATERIALIZER";
pub const FORMAT_KIND_TEXT: &str = "text";
pub const FORMAT_KIND_DATE: &str = "date";
pub const FORMAT_KIND_AMOUNT: &str = "amount";
pub const VALUE_KIND_TEXT: &str = "TEXT";
pub const VALUE_KIND_NULL: &str = "NULL";
pub const RUNTIME_CLOCK_TEXT_FORMAT: &str = "%Y-%m-%d %H:%M";
const BINDING_MAGIC: &[u8; 8] = b"HFBIND1\0";
const SCHEMA_MAGIC: &[u8; 8] = b"HFSSC1\0\0";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FieldBindingErrorKind {
    InputIntegrity,
    SourceSchemaDuplicateKey,
    UnsupportedContract,
    UnsupportedDocumentValuePolicy,
    UnsupportedValueFormat,
    UnsupportedTextSlice,
    RuntimeClockUnavailable,
}
impl FieldBindingErrorKind {
    pub fn code(self) -> &'static str {
        match self {
            Self::InputIntegrity => "FIELD_BINDING_INPUT_INTEGRITY_ERROR",
            Self::SourceSchemaDuplicateKey => "SOURCE_SCHEMA_DUPLICATE_KEY",
            Self::UnsupportedContract => "UNSUPPORTED_FIELD_BINDING_CONTRACT",
            Self::UnsupportedDocumentValuePolicy => "UNSUPPORTED_DOCUMENT_VALUE_POLICY",
            Self::UnsupportedValueFormat => "UNSUPPORTED_VALUE_FORMAT",
            Self::UnsupportedTextSlice => "UNSUPPORTED_TEXT_SLICE",
            Self::RuntimeClockUnavailable => "RUNTIME_CLOCK_UNAVAILABLE",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldBindingError {
    pub kind: FieldBindingErrorKind,
    pub message: String,
}
impl FieldBindingError {
    pub fn code(&self) -> &'static str {
        self.kind.code()
    }
}
impl fmt::Display for FieldBindingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for FieldBindingError {}
fn error(kind: FieldBindingErrorKind, message: impl Into<String>) -> FieldBindingError {
    FieldBindingError {
        kind,
        message: message.into(),
    }
}
fn integrity(message: impl Into<String>) -> FieldBindingError {
    error(FieldBindingErrorKind::InputIntegrity, message)
}
fn policy_error(message: impl Into<String>) -> FieldBindingError {
    error(
        FieldBindingErrorKind::UnsupportedDocumentValuePolicy,
        message,
    )
}
fn value_format_error(message: impl Into<String>) -> FieldBindingError {
    error(FieldBindingErrorKind::UnsupportedValueFormat, message)
}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExactText {
    pub text: String,
}
impl ExactText {
    pub fn new(text: impl Into<String>) -> Self {
        Self { text: text.into() }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DocumentContentValuePolicy {
    pub policy_id: String,
    pub line_break_policy: String,
    pub whitespace_policy: String,
    pub escaping_responsibility: String,
    pub native_text_write_policy: String,
}

fn policy(id: &str, whitespace: &str, escaping: &str, write: &str) -> DocumentContentValuePolicy {
    DocumentContentValuePolicy {
        policy_id: id.into(),
        line_break_policy: "PRESERVE_LOGICAL_LINE_BREAKS".into(),
        whitespace_policy: whitespace.into(),
        escaping_responsibility: escaping.into(),
        native_text_write_policy: write.into(),
    }
}
pub fn resolve_document_value_policy(
    id: &str,
) -> Result<DocumentContentValuePolicy, FieldBindingError> {
    let (whitespace, escaping, write) = match id {
        "document-content-value/v1" => (
            WHITESPACE_PRESERVE_EXACT,
            ESCAPING_NATIVE_MATERIALIZER,
            "WRITE_LOGICAL_TEXT_NODE",
        ),
        "document-content-value/legacy-strip-v1" => (
            WHITESPACE_STRIP_LEADING_TRAILING,
            ESCAPING_NATIVE_MATERIALIZER,
            "WRITE_LOGICAL_TEXT_NODE",
        ),
        "document-content-value/txt-v1" => (
            WHITESPACE_PRESERVE_EXACT,
            ESCAPING_PLAINTEXT_MATERIALIZER,
            "WRITE_PLAINTEXT_SPAN",
        ),
        "document-content-value/txt-legacy-strip-v1" => (
            WHITESPACE_STRIP_LEADING_TRAILING,
            ESCAPING_PLAINTEXT_MATERIALIZER,
            "WRITE_PLAINTEXT_SPAN",
        ),
        _ => return Err(policy_error(format!("미지원 문서 값 정책: {}", repr(id)))),
    };
    Ok(policy(id, whitespace, escaping, write))
}
pub fn txt_document_value_policy(
    id: &str,
) -> Result<DocumentContentValuePolicy, FieldBindingError> {
    match id {
        "document-content-value/v1" => {
            resolve_document_value_policy("document-content-value/txt-v1")
        }
        "document-content-value/legacy-strip-v1" => {
            resolve_document_value_policy("document-content-value/txt-legacy-strip-v1")
        }
        _ => {
            let policy = resolve_document_value_policy(id)?;
            if policy.escaping_responsibility != ESCAPING_PLAINTEXT_MATERIALIZER {
                return Err(policy_error(format!(
                    "TXT 짝이 없는 문서 값 정책: {}",
                    repr(id)
                )));
            }
            Ok(policy)
        }
    }
}
pub fn require_registered_document_value_policy(
    policy: &DocumentContentValuePolicy,
) -> Result<DocumentContentValuePolicy, FieldBindingError> {
    let registered = resolve_document_value_policy(&policy.policy_id)?;
    if *policy != registered {
        return Err(policy_error(format!(
            "등록된 policy_id 의 동작 필드를 변경했다: {}",
            repr(&policy.policy_id)
        )));
    }
    Ok(registered)
}

pub fn require_value_format(
    kind: Option<&str>,
    code: Option<&str>,
) -> Result<(), FieldBindingError> {
    if let Some(kind) = kind {
        if ![FORMAT_KIND_TEXT, FORMAT_KIND_DATE, FORMAT_KIND_AMOUNT].contains(&kind) {
            return Err(value_format_error(format!(
                "미지원 표시형 kind: {}",
                repr(kind)
            )));
        }
        let Some(code) = code else {
            return Err(value_format_error(format!(
                "표시형 {} 의 format code 는 문자열이어야 한다(빈 문자열 = 기본)",
                repr(kind)
            )));
        };
        if kind == FORMAT_KIND_TEXT && code.is_empty() {
            return Err(value_format_error(
                "text 기본 표시형은 (None, None) 으로 적는다(같은 뜻의 두 번째 모양 금지)",
            ));
        }
    } else if code.is_some_and(|code| !code.is_empty()) {
        return Err(value_format_error(format!(
            "표시형 kind 없이 format code 만 있다: {}",
            repr(code.unwrap_or_default())
        )));
    }
    Ok(())
}
pub fn render_value_format(
    kind: Option<&str>,
    code: Option<&str>,
    text: &str,
) -> Result<String, FieldBindingError> {
    require_value_format(kind, code)?;
    Ok(kind.map_or_else(
        || text.into(),
        |kind| format_engine::render(kind, code.unwrap_or(""), text),
    ))
}
pub fn require_text_slice(value: Option<&Value>) -> Result<Option<TextSlice>, FieldBindingError> {
    text_slice_from_payload(value)
        .map_err(|err| error(FieldBindingErrorKind::UnsupportedTextSlice, err.0))
}
pub fn render_source_value(
    kind: Option<&str>,
    code: Option<&str>,
    slice: Option<&TextSlice>,
    text: &str,
) -> Result<String, FieldBindingError> {
    require_value_format(kind, code)?;
    render_value_format(kind, code, &apply_text_slice(slice, text))
}
pub fn require_runtime_date_format(
    kind: Option<&str>,
    code: Option<&str>,
) -> Result<(), FieldBindingError> {
    if kind != Some(FORMAT_KIND_DATE) {
        return Err(value_format_error(format!(
            "실행 시각 값의 표시형은 date 여야 한다: {}",
            kind.map_or_else(|| "None".into(), repr)
        )));
    }
    require_value_format(kind, code)
}
mod runtime_clock;

pub use runtime_clock::parse_runtime_clock;

pub fn render_runtime_date(code: &str, now: NaiveDateTime) -> Result<String, FieldBindingError> {
    require_runtime_date_format(Some(FORMAT_KIND_DATE), Some(code))?;
    Ok(format_engine::render(
        FORMAT_KIND_DATE,
        code,
        &now.format(RUNTIME_CLOCK_TEXT_FORMAT).to_string(),
    ))
}

pub fn require_field_binding_contract(id: &str) -> Result<&str, FieldBindingError> {
    if [
        FIELD_BINDING_SEMANTIC_VERSION,
        FIELD_BINDING_SEMANTIC_VERSION_V4,
        FIELD_BINDING_SEMANTIC_VERSION_V3,
        FIELD_BINDING_SEMANTIC_VERSION_V2,
    ]
    .contains(&id)
    {
        Ok(id)
    } else {
        Err(error(
            FieldBindingErrorKind::UnsupportedContract,
            format!("미지원 field-binding contract: {}", repr(id)),
        ))
    }
}
pub fn is_current_field_binding_contract(id: &str) -> bool {
    id == FIELD_BINDING_SEMANTIC_VERSION
}
pub fn require_current_field_binding_contract(id: &str) -> Result<&str, FieldBindingError> {
    require_field_binding_contract(id)?;
    if is_current_field_binding_contract(id) {
        Ok(id)
    } else {
        Err(error(
            FieldBindingErrorKind::UnsupportedContract,
            format!(
                "실행 입력은 현재 field-binding contract 여야 한다: {}",
                repr(id)
            ),
        ))
    }
}
pub fn require_source_schema_contract(id: &str) -> Result<&str, FieldBindingError> {
    if id == SOURCE_SCHEMA_VERSION {
        Ok(id)
    } else {
        Err(error(
            FieldBindingErrorKind::UnsupportedContract,
            format!("미지원 source-schema contract: {}", repr(id)),
        ))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldBindingRule {
    pub field_id: String,
    pub binding_kind: String,
    pub document_content_value_policy: DocumentContentValuePolicy,
    pub source_key: Option<String>,
    pub format_code: Option<String>,
    pub canonical_constant_value: Option<ExactText>,
    pub format_kind: Option<String>,
    pub text_slice: Option<TextSlice>,
}
impl FieldBindingRule {
    fn validate_format_slots(&self) -> Result<(), FieldBindingError> {
        if self.format_kind.is_some() {
            if ![SOURCE, RUNTIME_DATE].contains(&self.binding_kind.as_str()) {
                return Err(integrity(format!(
                    "표시형은 SOURCE·RUNTIME_DATE 규칙에만 선다: {}",
                    repr(&self.binding_kind)
                )));
            }
            require_value_format(self.format_kind.as_deref(), self.format_code.as_deref())
                .map_err(|err| integrity(err.message))?;
        }
        if self.text_slice.is_some() && self.binding_kind != SOURCE {
            return Err(integrity(format!(
                "가공은 SOURCE 규칙에만 선다: {}",
                repr(&self.binding_kind)
            )));
        }
        Ok(())
    }

    fn validate_runtime_date(&self) -> Result<(), FieldBindingError> {
        if self.source_key.is_some() || self.canonical_constant_value.is_some() {
            return Err(integrity(
                "RUNTIME_DATE 규칙은 source/constant 를 가질 수 없다(kind 합성 금지)",
            ));
        }
        require_runtime_date_format(self.format_kind.as_deref(), self.format_code.as_deref())
            .map_err(|err| integrity(err.message))?;
        if self.document_content_value_policy.whitespace_policy != WHITESPACE_PRESERVE_EXACT {
            return Err(integrity(
                "RUNTIME_DATE 규칙의 값 정책은 공백을 보존해야 한다(소스 텍스트가 아니다)",
            ));
        }
        Ok(())
    }

    fn validate_contract(&self) -> Result<(), FieldBindingError> {
        if self.field_id.is_empty() {
            return Err(integrity("field_id 는 비어 있을 수 없다"));
        }
        if ![SOURCE, CONSTANT, INTENTIONAL_BLANK, RUNTIME_DATE]
            .contains(&self.binding_kind.as_str())
        {
            return Err(integrity(format!(
                "미지원 binding_kind: {}",
                repr(&self.binding_kind)
            )));
        }
        require_registered_document_value_policy(&self.document_content_value_policy).map(|_| ())
    }

    pub fn validate(&self) -> Result<(), FieldBindingError> {
        self.validate_contract()?;
        self.validate_format_slots()?;
        match self.binding_kind.as_str() {
            SOURCE => {
                if self.source_key.is_none() {
                    return Err(integrity("source_key 는 문자열이어야 한다"));
                }
                if self.canonical_constant_value.is_some() {
                    return Err(integrity(
                        "SOURCE 규칙은 constant 값을 가질 수 없다(kind 합성 금지)",
                    ));
                }
            }
            CONSTANT => {
                if self.canonical_constant_value.is_none() {
                    return Err(integrity("CONSTANT 규칙은 canonical 값이 필요하다"));
                }
                if self.source_key.is_some() {
                    return Err(integrity(
                        "CONSTANT 규칙은 source_key 를 가질 수 없다(kind 합성 금지)",
                    ));
                }
            }
            RUNTIME_DATE => self.validate_runtime_date()?,
            _ => {
                if self.source_key.is_some() || self.canonical_constant_value.is_some() {
                    return Err(integrity(
                        "INTENTIONAL_BLANK 규칙은 source/constant 를 가질 수 없다(kind 합성 금지)",
                    ));
                }
            }
        }
        Ok(())
    }
}

pub fn require_single_rule_per_field(
    rules: &[FieldBindingRule],
) -> Result<Vec<FieldBindingRule>, FieldBindingError> {
    let mut seen = HashSet::new();
    for rule in rules {
        rule.validate()?;
        if !seen.insert(&rule.field_id) {
            return Err(integrity(format!(
                "한 Field 에 규칙이 둘 이상이다(exclusivity 위반): {}",
                repr(&rule.field_id)
            )));
        }
    }
    Ok(rules.to_vec())
}
pub fn validate_source_schema_keys(keys: &[String]) -> Result<Vec<String>, FieldBindingError> {
    let mut seen = HashSet::new();
    for key in keys {
        if !seen.insert(key) {
            return Err(error(
                FieldBindingErrorKind::SourceSchemaDuplicateKey,
                format!("source schema 중복 exact key: {}", repr(key)),
            ));
        }
    }
    Ok(keys.to_vec())
}

fn write_u32(out: &mut Vec<u8>, value: usize) -> Result<(), FieldBindingError> {
    let value = u32::try_from(value).map_err(|_| integrity("canonical count 가 u32 범위 초과"))?;
    out.extend(value.to_be_bytes());
    Ok(())
}
fn write_text(out: &mut Vec<u8>, text: &str) -> Result<(), FieldBindingError> {
    let bytes = text.as_bytes();
    let length =
        u32::try_from(bytes.len()).map_err(|_| integrity("canonical text 가 u32 범위 초과"))?;
    out.extend(length.to_be_bytes());
    out.extend(bytes);
    Ok(())
}
fn write_optional_text(out: &mut Vec<u8>, text: Option<&str>) -> Result<(), FieldBindingError> {
    if let Some(text) = text {
        out.push(1);
        write_text(out, text)
    } else {
        out.push(0);
        Ok(())
    }
}
fn write_slice_v4(out: &mut Vec<u8>, slice: Option<&TextSlice>) -> Result<(), FieldBindingError> {
    let Some(slice) = slice else {
        out.push(0);
        return Ok(());
    };
    if !slice.is_v4_expressible() {
        return Err(integrity(format!(
            "{FIELD_BINDING_SEMANTIC_VERSION_V4} 판에는 이 가공이 없다: {}",
            python_repr(&slice.to_dict())
        )));
    }
    out.push(1);
    write_text(out, slice.mode())?;
    if slice.mode() == "chars" {
        write_text(
            out,
            &slice.start.as_ref().expect("validated slice").to_string(),
        )?;
        write_optional_text(
            out,
            slice.length.as_ref().map(ToString::to_string).as_deref(),
        )?;
    } else {
        write_text(out, slice.delimiter.as_deref().expect("validated slice"))?;
        write_text(
            out,
            &slice.index.as_ref().expect("validated slice").to_string(),
        )?;
    }
    Ok(())
}
fn write_slice_v5(out: &mut Vec<u8>, slice: Option<&TextSlice>) -> Result<(), FieldBindingError> {
    let Some(slice) = slice else {
        out.push(0);
        return Ok(());
    };
    out.push(1);
    write_text(out, slice.mode())?;
    for key in slice_keys(slice.mode()).expect("validated slice mode") {
        write_optional_text(out, slice.slot_value(key).as_deref())?;
    }
    if slice.missable() {
        write_text(out, slice.on_missing())?;
    }
    Ok(())
}
fn encode_rule(rule: &FieldBindingRule, contract_id: &str) -> Result<Vec<u8>, FieldBindingError> {
    if rule.text_slice.is_some()
        && ![
            FIELD_BINDING_SEMANTIC_VERSION_V4,
            FIELD_BINDING_SEMANTIC_VERSION,
        ]
        .contains(&contract_id)
    {
        return Err(integrity(format!(
            "{contract_id} 판에는 가공이 없다: {}",
            repr(&rule.field_id)
        )));
    }
    if rule.binding_kind == RUNTIME_DATE
        && ![
            FIELD_BINDING_SEMANTIC_VERSION_V4,
            FIELD_BINDING_SEMANTIC_VERSION,
        ]
        .contains(&contract_id)
    {
        return Err(integrity(format!(
            "{contract_id} 판에는 실행 시각 규칙이 없다: {}",
            repr(&rule.field_id)
        )));
    }
    let mut out = Vec::new();
    write_text(&mut out, &rule.field_id)?;
    write_text(&mut out, &rule.binding_kind)?;
    write_text(&mut out, &rule.document_content_value_policy.policy_id)?;
    write_optional_text(&mut out, rule.source_key.as_deref())?;
    if contract_id == FIELD_BINDING_SEMANTIC_VERSION_V2 {
        if rule.format_kind.is_some() {
            return Err(integrity(format!(
                "field-binding/v2 판에는 표시형 kind 가 없다: {}",
                repr(&rule.field_id)
            )));
        }
        write_optional_text(&mut out, rule.format_code.as_deref())?;
    } else {
        require_value_format(rule.format_kind.as_deref(), rule.format_code.as_deref()).map_err(
            |err| {
                integrity(format!(
                    "{} 의 표시형이 {contract_id} 모양이 아니다: {err}",
                    repr(&rule.field_id)
                ))
            },
        )?;
        write_optional_text(&mut out, rule.format_kind.as_deref())?;
        write_optional_text(
            &mut out,
            rule.format_kind.as_ref().and(rule.format_code.as_deref()),
        )?;
    }
    write_optional_text(
        &mut out,
        rule.canonical_constant_value
            .as_ref()
            .map(|value| value.text.as_str()),
    )?;
    match contract_id {
        FIELD_BINDING_SEMANTIC_VERSION_V4 => write_slice_v4(&mut out, rule.text_slice.as_ref())?,
        FIELD_BINDING_SEMANTIC_VERSION => write_slice_v5(&mut out, rule.text_slice.as_ref())?,
        _ => {}
    }
    Ok(out)
}
pub fn canonicalize_binding_rules(
    rules: &[FieldBindingRule],
    contract_id: &str,
) -> Result<Vec<u8>, FieldBindingError> {
    require_field_binding_contract(contract_id)?;
    let mut ordered = require_single_rule_per_field(rules)?;
    ordered.sort_by(|a, b| a.field_id.as_bytes().cmp(b.field_id.as_bytes()));
    let mut out = BINDING_MAGIC.to_vec();
    write_text(&mut out, contract_id)?;
    write_u32(&mut out, ordered.len())?;
    for rule in &ordered {
        let encoded = encode_rule(rule, contract_id)?;
        write_u32(&mut out, encoded.len())?;
        out.extend(encoded);
    }
    Ok(out)
}
pub fn digest_binding_rules(
    rules: &[FieldBindingRule],
    contract_id: &str,
) -> Result<String, FieldBindingError> {
    Ok(hex_digest(&canonicalize_binding_rules(rules, contract_id)?))
}
pub fn canonicalize_source_schema(keys: &[String]) -> Result<Vec<u8>, FieldBindingError> {
    let mut ordered = validate_source_schema_keys(keys)?;
    ordered.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
    let mut out = SCHEMA_MAGIC.to_vec();
    write_text(&mut out, SOURCE_SCHEMA_VERSION)?;
    write_u32(&mut out, ordered.len())?;
    for key in ordered {
        write_text(&mut out, &key)?;
    }
    Ok(out)
}
pub fn digest_source_schema(keys: &[String]) -> Result<String, FieldBindingError> {
    Ok(hex_digest(&canonicalize_source_schema(keys)?))
}

fn hex_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut text = String::from("sha256:");
    for byte in digest {
        text.push_str(&format!("{byte:02x}"));
    }
    text
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn frozen_v2_digest_and_v5_slice_identity_match_python_oracle() {
        let exact = resolve_document_value_policy("document-content-value/v1").unwrap();
        let strip =
            resolve_document_value_policy("document-content-value/legacy-strip-v1").unwrap();
        let rules = vec![
            FieldBindingRule {
                field_id: "계약금액".into(),
                binding_kind: SOURCE.into(),
                document_content_value_policy: strip,
                source_key: Some("계약금액".into()),
                format_code: Some("{:,}".into()),
                canonical_constant_value: None,
                format_kind: None,
                text_slice: None,
            },
            FieldBindingRule {
                field_id: "사업명".into(),
                binding_kind: SOURCE.into(),
                document_content_value_policy: exact.clone(),
                source_key: Some("사업명".into()),
                format_code: None,
                canonical_constant_value: None,
                format_kind: None,
                text_slice: None,
            },
            FieldBindingRule {
                field_id: "고정".into(),
                binding_kind: CONSTANT.into(),
                document_content_value_policy: exact.clone(),
                source_key: None,
                format_code: None,
                canonical_constant_value: Some(ExactText::new("값")),
                format_kind: None,
                text_slice: None,
            },
        ];
        assert_eq!(
            digest_binding_rules(&rules, FIELD_BINDING_SEMANTIC_VERSION_V2).unwrap(),
            "sha256:cfa259678c366512012cc2f9de78ec98eb99f5b5a680b5d13313f5669e3bb4e1"
        );
        assert_eq!(
            digest_binding_rules(
                &rules.iter().rev().cloned().collect::<Vec<_>>(),
                FIELD_BINDING_SEMANTIC_VERSION_V2
            )
            .unwrap(),
            digest_binding_rules(&rules, FIELD_BINDING_SEMANTIC_VERSION_V2).unwrap()
        );
        let plain = rules[1].clone();
        let mut amount = plain.clone();
        amount.format_kind = Some("amount".into());
        amount.format_code = Some(String::new());
        assert_ne!(
            digest_binding_rules(std::slice::from_ref(&plain), FIELD_BINDING_SEMANTIC_VERSION)
                .unwrap(),
            digest_binding_rules(&[amount.clone()], FIELD_BINDING_SEMANTIC_VERSION).unwrap()
        );
        assert!(
            canonicalize_binding_rules(&[amount.clone()], FIELD_BINDING_SEMANTIC_VERSION_V3)
                .unwrap()
                .windows(16)
                .any(|part| part == b"field-binding/v3")
        );
        assert!(
            canonicalize_binding_rules(&[amount.clone()], FIELD_BINDING_SEMANTIC_VERSION_V2)
                .is_err()
        );
        let mut no_format_alias = plain.clone();
        no_format_alias.format_code = Some(String::new());
        assert_eq!(
            digest_binding_rules(&[no_format_alias], FIELD_BINDING_SEMANTIC_VERSION).unwrap(),
            digest_binding_rules(&[plain], FIELD_BINDING_SEMANTIC_VERSION).unwrap()
        );
        let mut missing_kind = amount;
        missing_kind.format_kind = None;
        missing_kind.format_code = Some("{:,}".into());
        assert!(
            canonicalize_binding_rules(&[missing_kind], FIELD_BINDING_SEMANTIC_VERSION).is_err()
        );
        let mut sliced = rules[1].clone();
        sliced.text_slice = Some(
            TextSlice::from_dict(&json!({"mode":"before","delimiter":"-","on_missing":"keep"}))
                .unwrap(),
        );
        for obsolete in [
            FIELD_BINDING_SEMANTIC_VERSION_V2,
            FIELD_BINDING_SEMANTIC_VERSION_V3,
        ] {
            assert!(digest_binding_rules(&[sliced.clone()], obsolete).is_err());
        }
        assert!(
            canonicalize_binding_rules(&[sliced.clone()], FIELD_BINDING_SEMANTIC_VERSION_V4)
                .is_err()
        );
        assert!(canonicalize_binding_rules(&[sliced], FIELD_BINDING_SEMANTIC_VERSION).is_ok());
        let old_slice =
            TextSlice::from_dict(&json!({"mode":"split","delimiter":"-","index":1})).unwrap();
        let mut legacy = rules[1].clone();
        legacy.text_slice = Some(old_slice);
        assert!(canonicalize_binding_rules(&[legacy], FIELD_BINDING_SEMANTIC_VERSION_V4).is_ok());
        for contract in [
            FIELD_BINDING_SEMANTIC_VERSION_V2,
            FIELD_BINDING_SEMANTIC_VERSION_V3,
            FIELD_BINDING_SEMANTIC_VERSION_V4,
            FIELD_BINDING_SEMANTIC_VERSION,
        ] {
            assert_eq!(require_field_binding_contract(contract).unwrap(), contract);
            assert_eq!(
                is_current_field_binding_contract(contract),
                contract == FIELD_BINDING_SEMANTIC_VERSION
            );
        }
        let mut invalid = rules[2].clone();
        invalid.text_slice =
            Some(TextSlice::from_dict(&json!({"mode":"chars","start":1})).unwrap());
        assert!(invalid.validate().unwrap_err().message.contains("SOURCE"));
        invalid.text_slice = None;
        invalid.format_kind = Some("amount".into());
        invalid.format_code = Some(String::new());
        assert!(invalid.validate().unwrap_err().message.contains("SOURCE"));
        for obsolete in [
            FIELD_BINDING_SEMANTIC_VERSION_V2,
            FIELD_BINDING_SEMANTIC_VERSION_V3,
            FIELD_BINDING_SEMANTIC_VERSION_V4,
        ] {
            assert!(require_current_field_binding_contract(obsolete).is_err());
        }
        assert!(require_current_field_binding_contract(FIELD_BINDING_SEMANTIC_VERSION).is_ok());
    }

    #[test]
    fn policy_and_runtime_date_fail_closed_with_readable_value() {
        let mut policy = resolve_document_value_policy("document-content-value/v1").unwrap();
        policy.whitespace_policy = WHITESPACE_STRIP_LEADING_TRAILING.into();
        assert_eq!(
            require_registered_document_value_policy(&policy)
                .unwrap_err()
                .code(),
            "UNSUPPORTED_DOCUMENT_VALUE_POLICY"
        );
        assert_eq!(
            render_source_value(Some("amount"), Some("{:,}"), None, "1500").unwrap(),
            "1,500"
        );
        for (kind, code) in [
            (None, None),
            (Some("amount"), Some("")),
            (Some("amount"), Some("{:,}")),
            (Some("date"), Some("kor")),
            (Some("text"), Some("phone")),
        ] {
            require_value_format(kind, code).unwrap();
        }
        for (kind, code) in [
            (None, Some("{:,}")),
            (Some("today"), Some("")),
            (Some("currency"), Some("{:,}")),
            (Some("amount"), None),
            (Some("text"), Some("")),
        ] {
            assert!(require_value_format(kind, code).is_err());
        }
        for (kind, code, raw, expected) in [
            ("amount", "", "24750000", "24,750,000원"),
            ("amount", "{:,}", "24750000", "24,750,000"),
            ("amount", "{:,.2f}", "1500", "1,500.00"),
            ("amount", "", "미정", "미정"),
            ("date", "", "2026-07-17", "2026. 7. 17."),
            ("date", "kor", "2026-06-15 09:00", "2026년 6월 15일 09:00"),
            ("date", "%H:%M", "1400", "14:00"),
            ("text", "phone", "01012345678", "010-1234-5678"),
            ("text", "biz", "1234567890", "123-45-67890"),
        ] {
            assert_eq!(
                render_value_format(Some(kind), Some(code), raw).unwrap(),
                expected,
                "{kind}:{code}"
            );
        }
        assert_eq!(render_value_format(None, None, " 원문 ").unwrap(), " 원문 ");
        assert_eq!(
            render_value_format(None, Some(""), " 원문 ").unwrap(),
            " 원문 "
        );
        assert!(render_value_format(Some("currency"), Some(""), "1500").is_err());
        let amount_slice =
            TextSlice::from_dict(&json!({"mode":"split","delimiter":"원","index":1})).unwrap();
        assert_eq!(
            render_source_value(
                Some("amount"),
                Some(""),
                Some(&amount_slice),
                "170,309,180원 (VAT 포함)"
            )
            .unwrap(),
            "170,309,180원"
        );
        assert_eq!(
            render_source_value(None, None, None, " 원문 ").unwrap(),
            " 원문 "
        );
        assert_eq!(
            render_source_value(Some("text"), Some(""), None, "x")
                .unwrap_err()
                .code(),
            "UNSUPPORTED_VALUE_FORMAT"
        );
        let now = parse_runtime_clock(Some("2026-06-15T18:04:00+09:00")).unwrap();
        assert_eq!(
            render_runtime_date("kor", now).unwrap(),
            "2026년 6월 15일 18:04"
        );
        assert_eq!(
            parse_runtime_clock(None).unwrap_err().code(),
            "RUNTIME_CLOCK_UNAVAILABLE"
        );
        let clocks: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/runtime_clock.json"))
                .unwrap();
        for case in clocks.as_array().unwrap() {
            let source = case["source"].as_str().unwrap();
            let result = parse_runtime_clock(Some(source));
            if let Some(expected) = case["expected"].as_str() {
                let clock = result.unwrap_or_else(|error| panic!("{source}: {error}"));
                assert_eq!(
                    clock.format("%Y-%m-%dT%H:%M:%S%.6f").to_string(),
                    expected,
                    "{source}"
                );
            } else {
                assert!(result.is_err(), "invalid runtime clock accepted: {source}");
            }
        }
    }

    #[test]
    fn runtime_date_rules_reject_source_slots_and_frozen_versions() {
        let rule = FieldBindingRule {
            field_id: "작성일".into(),
            binding_kind: RUNTIME_DATE.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: None,
            canonical_constant_value: None,
            text_slice: None,
            format_kind: Some("date".into()),
            format_code: Some("kor".into()),
        };
        rule.validate().unwrap();
        for version in [
            FIELD_BINDING_SEMANTIC_VERSION_V4,
            FIELD_BINDING_SEMANTIC_VERSION,
        ] {
            let bytes = canonicalize_binding_rules(std::slice::from_ref(&rule), version).unwrap();
            assert_eq!(
                bytes
                    .windows(RUNTIME_DATE.len())
                    .filter(|part| *part == RUNTIME_DATE.as_bytes())
                    .count(),
                1
            );
        }
        for version in [
            FIELD_BINDING_SEMANTIC_VERSION_V2,
            FIELD_BINDING_SEMANTIC_VERSION_V3,
        ] {
            assert!(canonicalize_binding_rules(std::slice::from_ref(&rule), version).is_err());
        }
        for (slot, reason) in [
            ("source", "source/constant"),
            ("constant", "source/constant"),
            ("slice", "가공"),
            ("missing_format", "date"),
            ("amount", "date"),
            ("text", "date"),
            ("missing_code", "문자열"),
            ("strip", "공백"),
        ] {
            let mut changed = rule.clone();
            match slot {
                "source" => changed.source_key = Some("작성일".into()),
                "constant" => changed.canonical_constant_value = Some(ExactText::new("2026-06-15")),
                "slice" => {
                    changed.text_slice =
                        Some(TextSlice::from_dict(&json!({"mode":"chars","start":1})).unwrap())
                }
                "missing_format" => {
                    changed.format_kind = None;
                    changed.format_code = None;
                }
                "amount" => {
                    changed.format_kind = Some("amount".into());
                    changed.format_code = Some("".into());
                }
                "text" => {
                    changed.format_kind = Some("text".into());
                    changed.format_code = Some("phone".into());
                }
                "missing_code" => changed.format_code = None,
                _ => {
                    changed.document_content_value_policy =
                        resolve_document_value_policy("document-content-value/legacy-strip-v1")
                            .unwrap()
                }
            }
            let error = changed.validate().unwrap_err();
            assert_eq!(error.code(), "FIELD_BINDING_INPUT_INTEGRITY_ERROR");
            assert!(error.message.contains(reason), "{slot}: {error}");
        }
        let mut txt = rule.clone();
        txt.document_content_value_policy =
            resolve_document_value_policy("document-content-value/txt-v1").unwrap();
        txt.validate().unwrap();
        let digest = |rules: &[FieldBindingRule]| {
            digest_binding_rules(rules, FIELD_BINDING_SEMANTIC_VERSION).unwrap()
        };
        let mut source = rule.clone();
        source.binding_kind = SOURCE.into();
        source.source_key = Some("".into());
        assert_ne!(
            digest(std::slice::from_ref(&rule)),
            digest(std::slice::from_ref(&source))
        );
        source.field_id = "이름".into();
        assert_eq!(
            digest(&[rule.clone(), source.clone()]),
            digest(&[source, rule.clone()])
        );
        let mut default_format = rule.clone();
        default_format.format_code = Some("".into());
        assert_ne!(digest(&[rule]), digest(&[default_format]));
        for invalid in [None, Some(""), Some("어제")] {
            assert_eq!(
                parse_runtime_clock(invalid).unwrap_err().code(),
                "RUNTIME_CLOCK_UNAVAILABLE"
            );
        }
    }

    #[test]
    fn exact_schema_and_binding_shapes_keep_distinct_authorities() {
        let keys = ["b".into(), "a".into(), " a ".into()];
        assert_eq!(validate_source_schema_keys(&keys).unwrap(), keys);
        assert_eq!(
            digest_source_schema(&keys).unwrap(),
            "sha256:2e61462f0d010210ec0607a683ff6ba67db5e0a7965e93c9a7b01d32672d52a9"
        );
        assert_eq!(
            digest_source_schema(&["a".into(), "b".into(), " a ".into()]).unwrap(),
            digest_source_schema(&keys).unwrap()
        );
        assert_ne!(
            digest_source_schema(&["A".into()]).unwrap(),
            digest_source_schema(&["a".into()]).unwrap()
        );
        assert_eq!(
            validate_source_schema_keys(&["a".into(), "a".into()])
                .unwrap_err()
                .code(),
            "SOURCE_SCHEMA_DUPLICATE_KEY"
        );

        let policy = resolve_document_value_policy("document-content-value/v1").unwrap();
        let source = FieldBindingRule {
            field_id: "f".into(),
            binding_kind: SOURCE.into(),
            document_content_value_policy: policy.clone(),
            source_key: Some("k".into()),
            format_code: None,
            canonical_constant_value: None,
            format_kind: None,
            text_slice: None,
        };
        let mut conflicting = source.clone();
        conflicting.canonical_constant_value = Some(ExactText::new("v"));
        assert_eq!(
            conflicting.validate().unwrap_err().code(),
            "FIELD_BINDING_INPUT_INTEGRITY_ERROR"
        );
        let mut conflicting = source.clone();
        conflicting.binding_kind = CONSTANT.into();
        assert!(conflicting.validate().is_err());
        let mut conflicting = source.clone();
        conflicting.binding_kind = "MIXED".into();
        assert!(conflicting.validate().is_err());
        let mut conflicting = source.clone();
        conflicting.field_id.clear();
        assert!(conflicting.validate().is_err());
        assert!(require_single_rule_per_field(&[source.clone(), source.clone()]).is_err());

        let constant = FieldBindingRule {
            field_id: "f".into(),
            binding_kind: CONSTANT.into(),
            document_content_value_policy: policy.clone(),
            source_key: None,
            format_code: None,
            canonical_constant_value: Some(ExactText::new("")),
            format_kind: None,
            text_slice: None,
        };
        let mut blank = constant.clone();
        blank.binding_kind = INTENTIONAL_BLANK.into();
        blank.canonical_constant_value = None;
        assert_eq!(
            digest_binding_rules(&[constant], FIELD_BINDING_SEMANTIC_VERSION).unwrap(),
            "sha256:0db8f12796c37c7d52e75f9db76db42952fed56c88acab4f08f366d347ebb791"
        );
        assert_eq!(
            digest_binding_rules(&[blank], FIELD_BINDING_SEMANTIC_VERSION).unwrap(),
            "sha256:180cefaa968d738a19ece9e216ac70aedc4d58dffa23b39898d8354aa2f7777b"
        );
        assert_ne!(ExactText::new("é"), ExactText::new("e\u{301}"));
        assert_eq!(ExactText::new("  x ").text, "  x ");

        let mut sliced = source;
        sliced.text_slice = Some(
            TextSlice::from_dict(&json!({"mode":"split","delimiter":", ","index":-1})).unwrap(),
        );
        assert_eq!(
            digest_binding_rules(&[sliced.clone()], FIELD_BINDING_SEMANTIC_VERSION_V4).unwrap(),
            "sha256:cdf8785a6e09eeb0754d419417c417c196998b5b7359be486a978ea8a847dd44"
        );
        assert_eq!(
            digest_binding_rules(&[sliced], FIELD_BINDING_SEMANTIC_VERSION).unwrap(),
            "sha256:168652516794d1c4d861e1853f7ca94020627c1caa30ad7fe0160a9010034851"
        );
    }

    #[test]
    fn txt_policy_pair_preserves_logical_value_and_rejects_unknown_policy() {
        for hwpx_id in [
            "document-content-value/v1",
            "document-content-value/legacy-strip-v1",
        ] {
            let hwpx = resolve_document_value_policy(hwpx_id).unwrap();
            let txt = txt_document_value_policy(hwpx_id).unwrap();
            assert_eq!(txt.whitespace_policy, hwpx.whitespace_policy);
            assert_eq!(txt.line_break_policy, hwpx.line_break_policy);
            assert_eq!(hwpx.escaping_responsibility, ESCAPING_NATIVE_MATERIALIZER);
            assert_eq!(txt.escaping_responsibility, ESCAPING_PLAINTEXT_MATERIALIZER);
            assert_eq!(txt_document_value_policy(&txt.policy_id).unwrap(), txt);
        }
        assert_eq!(
            txt_document_value_policy("document-content-value/v9")
                .unwrap_err()
                .code(),
            "UNSUPPORTED_DOCUMENT_VALUE_POLICY"
        );
        assert!(require_source_schema_contract(SOURCE_SCHEMA_VERSION).is_ok());
        assert!(require_source_schema_contract("source-schema/v1").is_err());
        assert_eq!(EXACT_BLANK_POLICY, "WRITE_EMPTY_TEXT_PRESERVE_FIELD");
    }
}
