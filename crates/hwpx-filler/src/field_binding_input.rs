//! Exact Field Binding capture DTO and current-application review facts.

use crate::field_binding::{
    FIELD_BINDING_SEMANTIC_VERSION, FieldBindingError, FieldBindingErrorKind, FieldBindingRule,
    SOURCE, SOURCE_SCHEMA_VERSION, canonicalize_binding_rules, digest_binding_rules,
    digest_source_schema, require_current_field_binding_contract, require_single_rule_per_field,
    require_source_schema_contract, validate_source_schema_keys,
};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fmt;

pub const PRESERVED: &str = "PRESERVED";
pub const BROKEN: &str = "BROKEN";
pub const NEW_ACTIVE_FIELD: &str = "NEW_ACTIVE_FIELD";
pub const INACTIVE_ONLY: &str = "INACTIVE_ONLY";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldBindingInputError {
    pub kind: FieldBindingErrorKind,
    pub detail: String,
}
impl fmt::Display for FieldBindingInputError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for FieldBindingInputError {}
impl From<FieldBindingError> for FieldBindingInputError {
    fn from(error: FieldBindingError) -> Self {
        Self {
            kind: error.kind,
            detail: error.to_string(),
        }
    }
}
fn fail(detail: impl Into<String>) -> FieldBindingInputError {
    FieldBindingInputError {
        kind: FieldBindingErrorKind::InputIntegrity,
        detail: detail.into(),
    }
}
fn nonempty(value: &str, what: &str) -> Result<(), FieldBindingInputError> {
    if value.is_empty() {
        Err(fail(format!("{what} 는 비어 있지 않은 문자열이어야 한다")))
    } else {
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldBindingInput {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub base_template_application_id: String,
    pub field_binding_authority_revision: String,
    pub field_binding_semantic_contract_id: String,
    pub source_schema_contract_id: String,
    pub raw_record_contract_id: String,
    pub binding_rules: Vec<FieldBindingRule>,
    pub source_schema_keys: Vec<String>,
    pub canonical_binding_digest: String,
    pub canonical_source_schema_digest: String,
    pub captured_at: String,
}
impl FieldBindingInput {
    pub fn validate(&self) -> Result<(), FieldBindingInputError> {
        for (name, value) in [
            ("workspace_instance_id", &self.workspace_instance_id),
            ("work_authority_id", &self.work_authority_id),
            (
                "base_template_application_id",
                &self.base_template_application_id,
            ),
            (
                "field_binding_authority_revision",
                &self.field_binding_authority_revision,
            ),
            ("raw_record_contract_id", &self.raw_record_contract_id),
            ("captured_at", &self.captured_at),
        ] {
            nonempty(value, name)?;
        }
        require_current_field_binding_contract(&self.field_binding_semantic_contract_id)
            .map_err(FieldBindingInputError::from)?;
        require_source_schema_contract(&self.source_schema_contract_id)
            .map_err(FieldBindingInputError::from)?;
        let rules = require_single_rule_per_field(&self.binding_rules)
            .map_err(FieldBindingInputError::from)?;
        let keys = validate_source_schema_keys(&self.source_schema_keys)
            .map_err(FieldBindingInputError::from)?;
        if canonicalize_binding_rules(&rules, &self.field_binding_semantic_contract_id)
            .map_err(FieldBindingInputError::from)?
            != canonicalize_binding_rules(
                &self.binding_rules,
                &self.field_binding_semantic_contract_id,
            )
            .map_err(FieldBindingInputError::from)?
        {
            return Err(fail("규칙 정규화 불일치"));
        }
        if digest_binding_rules(&rules, &self.field_binding_semantic_contract_id)
            .map_err(FieldBindingInputError::from)?
            != self.canonical_binding_digest
        {
            return Err(fail(
                "canonical_binding_digest 가 규칙과 불일치(payload/digest mismatch)",
            ));
        }
        if digest_source_schema(&keys).map_err(FieldBindingInputError::from)?
            != self.canonical_source_schema_digest
        {
            return Err(fail(
                "canonical_source_schema_digest 가 소스 스키마와 불일치",
            ));
        }
        if field_binding_authority_revision_identity(
            &self.work_authority_id,
            &self.base_template_application_id,
            &self.field_binding_semantic_contract_id,
            &self.source_schema_contract_id,
            &self.raw_record_contract_id,
            &self.canonical_binding_digest,
            &self.canonical_source_schema_digest,
        )? != self.field_binding_authority_revision
        {
            return Err(fail(
                "field_binding_authority_revision 이 내용 content-address 와 불일치",
            ));
        }
        Ok(())
    }
}
pub fn field_binding_authority_revision_identity(
    work: &str,
    application: &str,
    binding_contract: &str,
    schema_contract: &str,
    raw_contract: &str,
    binding_digest: &str,
    schema_digest: &str,
) -> Result<String, FieldBindingInputError> {
    let mut hasher = Sha256::new();
    for part in [
        work,
        application,
        binding_contract,
        schema_contract,
        raw_contract,
        binding_digest,
        schema_digest,
    ] {
        let bytes = part.as_bytes();
        let len = u32::try_from(bytes.len()).map_err(|_| {
            fail("field binding authority revision 의 text length 가 u32 범위 초과")
        })?;
        hasher.update(len.to_be_bytes());
        hasher.update(bytes);
    }
    let digest = hasher.finalize();
    let mut result = String::from("fbrev:sha256:");
    for byte in digest {
        fmt::Write::write_fmt(&mut result, format_args!("{byte:02x}")).expect("String write");
    }
    Ok(result)
}
pub fn build_field_binding_input(
    workspace: &str,
    work: &str,
    application: &str,
    binding_rules: Vec<FieldBindingRule>,
    source_schema_keys: Vec<String>,
    raw_contract: &str,
    captured_at: &str,
) -> Result<FieldBindingInput, FieldBindingInputError> {
    let binding_rules =
        require_single_rule_per_field(&binding_rules).map_err(FieldBindingInputError::from)?;
    let source_schema_keys =
        validate_source_schema_keys(&source_schema_keys).map_err(FieldBindingInputError::from)?;
    let canonical_binding_digest =
        digest_binding_rules(&binding_rules, FIELD_BINDING_SEMANTIC_VERSION)
            .map_err(FieldBindingInputError::from)?;
    let canonical_source_schema_digest =
        digest_source_schema(&source_schema_keys).map_err(FieldBindingInputError::from)?;
    let field_binding_authority_revision = field_binding_authority_revision_identity(
        work,
        application,
        FIELD_BINDING_SEMANTIC_VERSION,
        SOURCE_SCHEMA_VERSION,
        raw_contract,
        &canonical_binding_digest,
        &canonical_source_schema_digest,
    )?;
    let result = FieldBindingInput {
        workspace_instance_id: workspace.into(),
        work_authority_id: work.into(),
        base_template_application_id: application.into(),
        field_binding_authority_revision,
        field_binding_semantic_contract_id: FIELD_BINDING_SEMANTIC_VERSION.into(),
        source_schema_contract_id: SOURCE_SCHEMA_VERSION.into(),
        raw_record_contract_id: raw_contract.into(),
        binding_rules,
        source_schema_keys,
        canonical_binding_digest,
        canonical_source_schema_digest,
        captured_at: captured_at.into(),
    };
    result.validate()?;
    Ok(result)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CurrentApplicationFieldStructure {
    pub application_id: String,
    pub active_field_ids: Vec<String>,
    pub inactive_field_ids: Vec<String>,
    pub source_schema_keys: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldReviewClassification {
    pub field_id: String,
    pub category: &'static str,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldBindingApplicationReview {
    pub classifications: Vec<FieldReviewClassification>,
}
impl FieldBindingApplicationReview {
    pub fn broken_field_ids(&self) -> Vec<String> {
        self.classifications
            .iter()
            .filter(|item| item.category == BROKEN)
            .map(|item| item.field_id.clone())
            .collect()
    }
    pub fn inactive_only_field_ids(&self) -> Vec<String> {
        self.classifications
            .iter()
            .filter(|item| item.category == INACTIVE_ONLY)
            .map(|item| item.field_id.clone())
            .collect()
    }
}
pub fn review_field_binding_for_current_application(
    binding: &FieldBindingInput,
    structure: &CurrentApplicationFieldStructure,
) -> FieldBindingApplicationReview {
    let active: HashSet<&str> = structure
        .active_field_ids
        .iter()
        .map(String::as_str)
        .collect();
    let inactive: HashSet<&str> = structure
        .inactive_field_ids
        .iter()
        .map(String::as_str)
        .collect();
    let schema: HashSet<&str> = structure
        .source_schema_keys
        .iter()
        .map(String::as_str)
        .collect();
    let mut old = HashSet::new();
    let mut classifications = Vec::new();
    for rule in &binding.binding_rules {
        old.insert(rule.field_id.as_str());
        let category = if active.contains(rule.field_id.as_str()) {
            if rule.binding_kind == SOURCE
                && rule
                    .source_key
                    .as_deref()
                    .is_none_or(|key| !schema.contains(key))
            {
                BROKEN
            } else {
                PRESERVED
            }
        } else if inactive.contains(rule.field_id.as_str()) {
            INACTIVE_ONLY
        } else {
            BROKEN
        };
        classifications.push(FieldReviewClassification {
            field_id: rule.field_id.clone(),
            category,
        });
    }
    for field in &structure.active_field_ids {
        if !old.contains(field.as_str()) {
            classifications.push(FieldReviewClassification {
                field_id: field.clone(),
                category: NEW_ACTIVE_FIELD,
            });
        }
    }
    FieldBindingApplicationReview { classifications }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::field_binding::{FieldBindingRule, resolve_document_value_policy};
    #[test]
    fn captured_binding_revision_is_content_addressed_and_review_preserves_inactive() {
        let rule = FieldBindingRule {
            field_id: "a".into(),
            binding_kind: SOURCE.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: Some("col".into()),
            format_code: None,
            canonical_constant_value: None,
            format_kind: None,
            text_slice: None,
        };
        let input = build_field_binding_input(
            "workspace",
            "work",
            "application",
            vec![rule],
            vec!["col".into()],
            "raw-record/v1",
            "2026-01-01",
        )
        .unwrap();
        let mut later_capture = input.clone();
        later_capture.captured_at = "2026-01-02".into();
        later_capture.validate().unwrap();
        assert_eq!(
            later_capture.field_binding_authority_revision,
            input.field_binding_authority_revision
        );
        let next_application = build_field_binding_input(
            "workspace",
            "work",
            "next-application",
            input.binding_rules.clone(),
            input.source_schema_keys.clone(),
            "raw-record/v1",
            "2026-01-01",
        )
        .unwrap();
        assert_ne!(
            next_application.field_binding_authority_revision,
            input.field_binding_authority_revision
        );
        let mut stale = input.clone();
        stale.field_binding_authority_revision = "fbrev:sha256:deadbeef".into();
        assert_eq!(
            stale.validate().unwrap_err().kind,
            FieldBindingErrorKind::InputIntegrity
        );
        stale = input.clone();
        stale.canonical_binding_digest = "sha256:wrong".into();
        assert_eq!(
            stale.validate().unwrap_err().kind,
            FieldBindingErrorKind::InputIntegrity
        );
        stale = input.clone();
        stale.canonical_source_schema_digest = "sha256:wrong".into();
        assert!(stale.validate().is_err());
        stale = input.clone();
        stale.field_binding_semantic_contract_id = "field-binding/v1".into();
        assert_eq!(
            stale.validate().unwrap_err().kind,
            FieldBindingErrorKind::UnsupportedContract
        );
        stale = input.clone();
        stale.base_template_application_id.clear();
        assert_eq!(
            stale.validate().unwrap_err().kind,
            FieldBindingErrorKind::InputIntegrity
        );
        stale = input.clone();
        stale.source_schema_keys.push("col".into());
        assert_eq!(
            stale.validate().unwrap_err().kind,
            FieldBindingErrorKind::SourceSchemaDuplicateKey
        );
        let structure = CurrentApplicationFieldStructure {
            application_id: "application".into(),
            active_field_ids: vec!["new".into()],
            inactive_field_ids: vec!["a".into()],
            source_schema_keys: vec!["col".into()],
        };
        let review = review_field_binding_for_current_application(&input, &structure);
        assert_eq!(review.inactive_only_field_ids(), ["a"]);
        assert_eq!(review.classifications[1].category, NEW_ACTIVE_FIELD);

        let mut preserved = input.binding_rules[0].clone();
        preserved.field_id = "preserved".into();
        let mut removed = preserved.clone();
        removed.field_id = "removed".into();
        let mut moved_inactive = preserved.clone();
        moved_inactive.field_id = "moved_inactive".into();
        let mut source_gone = preserved.clone();
        source_gone.field_id = "source_gone".into();
        source_gone.source_key = Some("vanished_key".into());
        let current = build_field_binding_input(
            "workspace",
            "work",
            "A17",
            vec![preserved, removed, moved_inactive, source_gone],
            vec!["col".into(), "vanished_key".into()],
            "raw-record/v1",
            "2026-01-01",
        )
        .unwrap();
        let structure = CurrentApplicationFieldStructure {
            application_id: "A18".into(),
            active_field_ids: vec!["preserved".into(), "source_gone".into(), "brand_new".into()],
            inactive_field_ids: vec!["moved_inactive".into()],
            source_schema_keys: vec!["col".into()],
        };
        let review = review_field_binding_for_current_application(&current, &structure);
        let categories: std::collections::HashMap<_, _> = review
            .classifications
            .iter()
            .map(|item| (item.field_id.as_str(), item.category))
            .collect();
        assert_eq!(categories["preserved"], PRESERVED);
        assert_eq!(categories["removed"], BROKEN);
        assert_eq!(categories["moved_inactive"], INACTIVE_ONLY);
        assert_eq!(categories["source_gone"], BROKEN);
        assert_eq!(categories["brand_new"], NEW_ACTIVE_FIELD);
        assert_eq!(review.broken_field_ids(), ["removed", "source_gone"]);
        assert_eq!(review.inactive_only_field_ids(), ["moved_inactive"]);
    }
}
