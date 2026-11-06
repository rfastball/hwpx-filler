//! Immutable raw source-row snapshot and review evidence identities.

use crate::canonical_execution_encoding::{
    CANONICAL_ENCODING_VERSION, canonical_execution_bytes, canonical_execution_digest,
};
use crate::field_binding::{
    SOURCE_SCHEMA_VERSION, VALUE_KIND_NULL, VALUE_KIND_TEXT, digest_source_schema,
};
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::fmt;

pub const RAW_RECORD_SCHEMA_VERSION: &str = "raw-data-record/v1";
pub const RAW_RECORD_CONTRACT_ID: &str = "raw-record/v1";
pub const RECORD_REVIEW_CONTRACT_ID: &str = "record-review/v1";
pub const RECORD_REVIEW_BASIS_SCHEMA: &str = "record-review-basis/v1";
pub const RECORD_REVIEW_EXAMINED: &str = "EXAMINED";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RawRecordErrorKind {
    Integrity,
    DuplicateKey,
    SourceSchemaDuplicateKey,
    ReviewIntegrity,
}
impl RawRecordErrorKind {
    pub fn code(self) -> &'static str {
        match self {
            Self::Integrity => "RAW_RECORD_INTEGRITY_ERROR",
            Self::DuplicateKey => "RAW_RECORD_DUPLICATE_KEY",
            Self::SourceSchemaDuplicateKey => "SOURCE_SCHEMA_DUPLICATE_KEY",
            Self::ReviewIntegrity => "RECORD_REVIEW_EVIDENCE_INTEGRITY_ERROR",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RawRecordError {
    pub kind: RawRecordErrorKind,
    pub detail: String,
}
impl fmt::Display for RawRecordError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for RawRecordError {}
fn err(kind: RawRecordErrorKind, detail: impl Into<String>) -> RawRecordError {
    RawRecordError {
        kind,
        detail: detail.into(),
    }
}
fn integrity(detail: impl Into<String>) -> RawRecordError {
    err(RawRecordErrorKind::Integrity, detail)
}
fn require_text(value: &str, what: &str, allow_empty: bool) -> Result<(), RawRecordError> {
    if !allow_empty && value.is_empty() {
        return Err(integrity(format!("{what} 는 비어 있을 수 없다")));
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CanonicalSourceValue {
    Text(String),
    Null,
}
pub fn encode_source_value(value: &CanonicalSourceValue) -> Value {
    let mut out = Map::new();
    match value {
        CanonicalSourceValue::Text(text) => {
            out.insert("kind".into(), Value::String(VALUE_KIND_TEXT.into()));
            out.insert("text".into(), Value::String(text.clone()));
        }
        CanonicalSourceValue::Null => {
            out.insert("kind".into(), Value::String(VALUE_KIND_NULL.into()));
        }
    }
    Value::Object(out)
}
pub fn decode_source_value(tagged: &Value) -> Result<CanonicalSourceValue, RawRecordError> {
    let data = tagged
        .as_object()
        .ok_or_else(|| integrity("source value 표현이 사전이 아니다"))?;
    let kind = data.get("kind").unwrap_or(&Value::Null);
    if kind == VALUE_KIND_NULL {
        return Ok(CanonicalSourceValue::Null);
    }
    if kind != VALUE_KIND_TEXT {
        return Err(integrity(format!(
            "미지원 source 값 kind: {}",
            python_repr(kind)
        )));
    }
    let Some(text) = data.get("text").and_then(Value::as_str) else {
        return Err(integrity(
            "source value decode 실패: text 는 문자열이어야 한다",
        ));
    };
    Ok(CanonicalSourceValue::Text(text.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RawRecordCaptureProvenance {
    pub source_adapter_contract_id: String,
    pub captured_at: String,
    pub source_observation_ref: Option<String>,
}
impl RawRecordCaptureProvenance {
    pub fn validate(&self) -> Result<(), RawRecordError> {
        require_text(
            &self.source_adapter_contract_id,
            "source_adapter_contract_id",
            false,
        )?;
        require_text(&self.captured_at, "captured_at", false)?;
        if let Some(value) = &self.source_observation_ref {
            require_text(value, "source_observation_ref", false)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RawDataRecordSnapshot {
    pub raw_record_digest: String,
    pub record_identity: String,
    pub source_schema_digest: String,
    semantic_payload_encoded: Value,
    pub capture_provenance: RawRecordCaptureProvenance,
    values: HashMap<String, CanonicalSourceValue>,
}
impl RawDataRecordSnapshot {
    pub fn semantic_payload_encoded(&self) -> &Value {
        &self.semantic_payload_encoded
    }
    pub fn canonical_payload_bytes(&self) -> Result<Vec<u8>, RawRecordError> {
        canonical_execution_bytes(&self.semantic_payload_encoded)
            .map_err(|error| integrity(error.to_string()))
    }
    pub fn has_key(&self, source_key: &str) -> bool {
        self.values.contains_key(source_key)
    }
    /// `None` means MISSING; `Some(Null)` means an explicit source NULL.
    pub fn value_for(&self, source_key: &str) -> Option<&CanonicalSourceValue> {
        self.values.get(source_key)
    }
}

pub fn build_raw_record_snapshot(
    source_schema_keys: &[String],
    source_values: Vec<(String, CanonicalSourceValue)>,
    record_identity: &str,
    capture_provenance: RawRecordCaptureProvenance,
) -> Result<RawDataRecordSnapshot, RawRecordError> {
    require_text(record_identity, "record_identity", false)?;
    capture_provenance.validate()?;
    let mut values = HashMap::new();
    for (key, value) in source_values {
        // Empty source keys are legal in the v1 exact-key stream.
        if values.insert(key.clone(), value).is_some() {
            return Err(err(
                RawRecordErrorKind::DuplicateKey,
                format!(
                    "raw record 중복 exact source key: {}",
                    python_repr(&Value::String(key))
                ),
            ));
        }
    }
    let source_schema_digest = digest_source_schema(source_schema_keys).map_err(|error| {
        if error.kind.code() == RawRecordErrorKind::SourceSchemaDuplicateKey.code() {
            err(
                RawRecordErrorKind::SourceSchemaDuplicateKey,
                error.to_string(),
            )
        } else {
            integrity(error.to_string())
        }
    })?;
    let mut ordered: Vec<_> = values.iter().collect();
    ordered.sort_by(|(left, _), (right, _)| left.as_bytes().cmp(right.as_bytes()));
    let source_values: Vec<Value> = ordered
        .into_iter()
        .map(|(key, value)| {
            let mut item = Map::new();
            item.insert("source_key".into(), Value::String(key.clone()));
            item.insert("tagged_value".into(), encode_source_value(value));
            Value::Object(item)
        })
        .collect();
    let mut payload = Map::new();
    payload.insert(
        "raw_record_schema_version".into(),
        Value::String(RAW_RECORD_SCHEMA_VERSION.into()),
    );
    payload.insert(
        "canonical_encoding_version".into(),
        Value::String(CANONICAL_ENCODING_VERSION.into()),
    );
    payload.insert(
        "source_schema_contract_id".into(),
        Value::String(SOURCE_SCHEMA_VERSION.into()),
    );
    payload.insert(
        "raw_record_contract_id".into(),
        Value::String(RAW_RECORD_CONTRACT_ID.into()),
    );
    payload.insert(
        "record_identity".into(),
        Value::String(record_identity.into()),
    );
    payload.insert(
        "source_schema_digest".into(),
        Value::String(source_schema_digest.clone()),
    );
    payload.insert("source_values".into(), Value::Array(source_values));
    let semantic_payload_encoded = Value::Object(payload);
    let raw_record_digest = canonical_execution_digest(&semantic_payload_encoded)
        .map_err(|error| integrity(error.to_string()))?;
    Ok(RawDataRecordSnapshot {
        raw_record_digest,
        record_identity: record_identity.into(),
        source_schema_digest,
        semantic_payload_encoded,
        capture_provenance,
        values,
    })
}

pub fn verify_raw_record_snapshot(snapshot: &RawDataRecordSnapshot) -> Result<(), RawRecordError> {
    let payload = snapshot.semantic_payload_encoded();
    let digest =
        canonical_execution_digest(payload).map_err(|error| integrity(error.to_string()))?;
    if digest != snapshot.raw_record_digest {
        return Err(integrity(
            "raw record snapshot 의 canonical digest 가 content-address 와 불일치",
        ));
    }
    if payload["record_identity"] != snapshot.record_identity {
        return Err(integrity(
            "snapshot.record_identity 가 sealed payload 와 불일치",
        ));
    }
    if payload["source_schema_digest"] != snapshot.source_schema_digest {
        return Err(integrity(
            "snapshot.source_schema_digest 가 sealed payload 와 불일치",
        ));
    }
    let entries = payload["source_values"]
        .as_array()
        .ok_or_else(|| integrity("sealed payload 의 source_values 형식 불량"))?;
    let mut rebuilt = HashMap::new();
    for entry in entries {
        let key = entry
            .get("source_key")
            .and_then(Value::as_str)
            .ok_or_else(|| integrity("sealed payload 의 source_key 형식 불량"))?;
        let tagged = entry
            .get("tagged_value")
            .ok_or_else(|| integrity("sealed payload 의 tagged_value 누락"))?;
        if rebuilt
            .insert(key.into(), decode_source_value(tagged)?)
            .is_some()
        {
            return Err(integrity("sealed payload 의 source_values 에 중복 key"));
        }
    }
    if snapshot.values != rebuilt {
        return Err(integrity(
            "snapshot._values 가 sealed payload 에서 재구성한 lookup 과 불일치(divergent restore)",
        ));
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordReviewEvidence {
    pub workspace_instance_id: String,
    pub work_authority_id: String,
    pub plan_semantic_digest: String,
    pub raw_record_digest: String,
    pub record_identity: String,
    pub record_review_contract_id: String,
    pub review_policy_basis: String,
    pub review_basis_digest: String,
    pub actor_binding: String,
    pub reviewed_at: String,
}
impl RecordReviewEvidence {
    pub fn validate(&self) -> Result<(), RawRecordError> {
        for (name, value) in [
            ("workspace_instance_id", &self.workspace_instance_id),
            ("work_authority_id", &self.work_authority_id),
            ("plan_semantic_digest", &self.plan_semantic_digest),
            ("raw_record_digest", &self.raw_record_digest),
            ("record_identity", &self.record_identity),
            ("record_review_contract_id", &self.record_review_contract_id),
            ("review_policy_basis", &self.review_policy_basis),
            ("review_basis_digest", &self.review_basis_digest),
            ("actor_binding", &self.actor_binding),
            ("reviewed_at", &self.reviewed_at),
        ] {
            require_text(value, name, false)?;
        }
        Ok(())
    }
}
fn review_basis_payload(
    plan: &str,
    raw: &str,
    identity: &str,
    contract: &str,
    policy: &str,
) -> Value {
    let mut payload = Map::new();
    payload.insert(
        "record_review_basis_schema".into(),
        Value::String(RECORD_REVIEW_BASIS_SCHEMA.into()),
    );
    payload.insert("plan_semantic_digest".into(), Value::String(plan.into()));
    payload.insert("raw_record_digest".into(), Value::String(raw.into()));
    payload.insert("record_identity".into(), Value::String(identity.into()));
    payload.insert(
        "record_review_contract_id".into(),
        Value::String(contract.into()),
    );
    payload.insert("review_policy_basis".into(), Value::String(policy.into()));
    Value::Object(payload)
}
pub fn compute_review_basis_digest(
    plan: &str,
    raw: &str,
    identity: &str,
    contract: &str,
    policy: &str,
) -> Result<String, RawRecordError> {
    canonical_execution_digest(&review_basis_payload(plan, raw, identity, contract, policy))
        .map_err(|error| integrity(error.to_string()))
}
pub fn build_record_review_evidence(
    mut evidence: RecordReviewEvidence,
) -> Result<RecordReviewEvidence, RawRecordError> {
    evidence.review_basis_digest = compute_review_basis_digest(
        &evidence.plan_semantic_digest,
        &evidence.raw_record_digest,
        &evidence.record_identity,
        &evidence.record_review_contract_id,
        &evidence.review_policy_basis,
    )?;
    evidence.validate()?;
    Ok(evidence)
}
pub fn verify_record_review_evidence_integrity(
    evidence: &RecordReviewEvidence,
) -> Result<(), RawRecordError> {
    evidence.validate()?;
    let recomputed = compute_review_basis_digest(
        &evidence.plan_semantic_digest,
        &evidence.raw_record_digest,
        &evidence.record_identity,
        &evidence.record_review_contract_id,
        &evidence.review_policy_basis,
    )?;
    if recomputed != evidence.review_basis_digest {
        return Err(err(
            RawRecordErrorKind::ReviewIntegrity,
            "review_basis_digest 재계산 불일치(tampered evidence)",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    fn provenance() -> RawRecordCaptureProvenance {
        RawRecordCaptureProvenance {
            source_adapter_contract_id: "excel-adapter/v1".into(),
            captured_at: "2026-01-01T00:00:00+09:00".into(),
            source_observation_ref: None,
        }
    }

    #[test]
    fn source_codec_keeps_exact_unicode_and_rejects_legacy_or_malformed_values() {
        for text in [
            "  spaced \t ",
            "é",
            "e\u{301}",
            "",
            "2026.8.31",
            "1,000,000",
        ] {
            let value = CanonicalSourceValue::Text(text.into());
            let encoded = encode_source_value(&value);
            assert_eq!(encoded, json!({"kind": "TEXT", "text": text}));
            assert_eq!(decode_source_value(&encoded).unwrap(), value);
        }
        assert_eq!(
            encode_source_value(&CanonicalSourceValue::Null),
            json!({"kind": "NULL"})
        );
        assert_eq!(
            decode_source_value(&json!({"kind": "NULL"})).unwrap(),
            CanonicalSourceValue::Null
        );
        for invalid in [
            json!({"value_type": "EXACT_TEXT", "literal": "x"}),
            json!({"value_type": "DECIMAL", "literal": "1.50"}),
            json!({"value_type": "NULL"}),
            json!({"kind": "EXACT_TEXT", "text": "x"}),
            json!({"kind": "DECIMAL", "literal": "1.50"}),
            json!({"kind": "MONEY", "text": "1"}),
            json!({"kind": "TEXT", "text": 1}),
            json!({"kind": "TEXT"}),
            json!({}),
            json!(null),
            json!("untyped value"),
        ] {
            assert_eq!(
                decode_source_value(&invalid).unwrap_err().kind,
                RawRecordErrorKind::Integrity,
                "{invalid}"
            );
        }
        assert!(serde_json::from_str::<Value>(r#"{"kind":"TEXT","text":"\ud800"}"#).is_err());
        let snapshot = |text: &str| {
            build_raw_record_snapshot(
                &["a".into()],
                vec![("a".into(), CanonicalSourceValue::Text(text.into()))],
                "rec-1",
                provenance(),
            )
            .unwrap()
        };
        assert_ne!(
            snapshot("é").raw_record_digest,
            snapshot("e\u{301}").raw_record_digest
        );
        assert_eq!(
            snapshot("  spaced \t ").value_for("a"),
            Some(&CanonicalSourceValue::Text("  spaced \t ".into()))
        );
    }

    fn evidence() -> RecordReviewEvidence {
        build_record_review_evidence(RecordReviewEvidence {
            workspace_instance_id: "ws-1".into(),
            work_authority_id: "work-1".into(),
            plan_semantic_digest: "sha256:plan".into(),
            raw_record_digest: "sha256:raw".into(),
            record_identity: "rec-1".into(),
            record_review_contract_id: RECORD_REVIEW_CONTRACT_ID.into(),
            review_policy_basis: RECORD_REVIEW_EXAMINED.into(),
            review_basis_digest: String::new(),
            actor_binding: "user:alice".into(),
            reviewed_at: "2026-01-01T00:00:00+09:00".into(),
        })
        .unwrap()
    }

    #[test]
    fn review_basis_binds_content_and_policy_but_not_actor_or_time() {
        let original = evidence();
        verify_record_review_evidence_integrity(&original).unwrap();
        assert_eq!(
            original.review_basis_digest,
            compute_review_basis_digest(
                "sha256:plan",
                "sha256:raw",
                "rec-1",
                RECORD_REVIEW_CONTRACT_ID,
                RECORD_REVIEW_EXAMINED
            )
            .unwrap()
        );
        let mut metadata = original.clone();
        metadata.actor_binding = "user:bob".into();
        metadata.reviewed_at = "2027-07-07T07:07:07+09:00".into();
        let metadata = build_record_review_evidence(metadata).unwrap();
        assert_eq!(original.review_basis_digest, metadata.review_basis_digest);
        for slot in ["plan", "raw", "identity", "contract", "policy"] {
            let mut changed = original.clone();
            let value = match slot {
                "plan" => &mut changed.plan_semantic_digest,
                "raw" => &mut changed.raw_record_digest,
                "identity" => &mut changed.record_identity,
                "contract" => &mut changed.record_review_contract_id,
                _ => &mut changed.review_policy_basis,
            };
            *value = "changed".into();
            assert_eq!(
                verify_record_review_evidence_integrity(&changed)
                    .unwrap_err()
                    .kind,
                RawRecordErrorKind::ReviewIntegrity,
                "{slot}"
            );
            assert_ne!(
                build_record_review_evidence(changed)
                    .unwrap()
                    .review_basis_digest,
                original.review_basis_digest
            );
        }
        let mut invalid = original;
        invalid.actor_binding.clear();
        assert!(verify_record_review_evidence_integrity(&invalid).is_err());
    }

    #[test]
    fn frozen_row_distinguishes_missing_null_empty_and_space_before_digest() {
        let source_provenance = RawRecordCaptureProvenance {
            source_adapter_contract_id: "excel-adapter/v1".into(),
            captured_at: "2026-01-01".into(),
            source_observation_ref: None,
        };
        let pairs = vec![
            ("space".into(), CanonicalSourceValue::Text(" ".into())),
            ("null".into(), CanonicalSourceValue::Null),
            ("empty".into(), CanonicalSourceValue::Text("".into())),
        ];
        let keys = vec!["space".into(), "null".into(), "empty".into()];
        let snapshot =
            build_raw_record_snapshot(&keys, pairs.clone(), "rec-1", source_provenance.clone())
                .unwrap();
        assert_eq!(snapshot.value_for("absent"), None);
        assert!(!snapshot.has_key("absent"));
        assert!(snapshot.has_key("null"));
        assert_eq!(
            snapshot.value_for("null"),
            Some(&CanonicalSourceValue::Null)
        );
        assert_eq!(
            snapshot.value_for("empty"),
            Some(&CanonicalSourceValue::Text(String::new()))
        );
        assert_eq!(
            snapshot.value_for("space"),
            Some(&CanonicalSourceValue::Text(" ".into()))
        );
        verify_raw_record_snapshot(&snapshot).unwrap();
        let mut changed_identity = snapshot.clone();
        changed_identity.record_identity = "different-row".into();
        assert_eq!(
            verify_raw_record_snapshot(&changed_identity)
                .unwrap_err()
                .kind,
            RawRecordErrorKind::Integrity
        );
        let mut changed_digest = snapshot.clone();
        changed_digest.raw_record_digest = "forged".into();
        assert_eq!(
            verify_raw_record_snapshot(&changed_digest)
                .unwrap_err()
                .kind,
            RawRecordErrorKind::Integrity
        );
        let reversed = build_raw_record_snapshot(
            &keys,
            pairs.into_iter().rev().collect(),
            "rec-1",
            source_provenance,
        )
        .unwrap();
        assert_eq!(snapshot.raw_record_digest, reversed.raw_record_digest);
        assert_eq!(
            snapshot.canonical_payload_bytes().unwrap(),
            reversed.canonical_payload_bytes().unwrap()
        );
        let mut changed_values = snapshot.clone();
        changed_values.values.insert(
            "space".into(),
            CanonicalSourceValue::Text("TAMPERED".into()),
        );
        assert_eq!(
            verify_raw_record_snapshot(&changed_values)
                .unwrap_err()
                .kind,
            RawRecordErrorKind::Integrity
        );
        let mut changed_schema = snapshot.clone();
        changed_schema.source_schema_digest = "changed".into();
        assert!(verify_raw_record_snapshot(&changed_schema).is_err());
        let pairs = ["z", "Z", "a", "name", "Name", "name "]
            .map(|key| (key.into(), CanonicalSourceValue::Text(key.into())))
            .to_vec();
        let keys = pairs
            .iter()
            .map(|(key, _): &(String, _)| key.clone())
            .collect::<Vec<_>>();
        let exact = build_raw_record_snapshot(&keys, pairs.clone(), "rec-1", provenance()).unwrap();
        assert_eq!(
            exact.semantic_payload_encoded()["source_values"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| item["source_key"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["Name", "Z", "a", "name", "name ", "z"]
        );
        let other_identity =
            build_raw_record_snapshot(&keys, pairs.clone(), "rec-2", provenance()).unwrap();
        assert_ne!(exact.raw_record_digest, other_identity.raw_record_digest);
        assert!(build_raw_record_snapshot(&keys, pairs.clone(), "", provenance()).is_err());
        let other_provenance = RawRecordCaptureProvenance {
            source_adapter_contract_id: "csv-adapter/v1".into(),
            captured_at: "2027-12-31T23:59:59+09:00".into(),
            source_observation_ref: Some("obs://x".into()),
        };
        let recaptured =
            build_raw_record_snapshot(&keys, pairs, "rec-1", other_provenance).unwrap();
        assert_eq!(exact.raw_record_digest, recaptured.raw_record_digest);
        let duplicate = build_raw_record_snapshot(
            &keys,
            vec![
                ("x".into(), CanonicalSourceValue::Null),
                ("x".into(), CanonicalSourceValue::Text("v".into())),
            ],
            "rec-1",
            reversed.capture_provenance.clone(),
        )
        .unwrap_err();
        assert_eq!(duplicate.kind, RawRecordErrorKind::DuplicateKey);
        let duplicate_schema = build_raw_record_snapshot(
            &["x".into(), "x".into()],
            vec![],
            "rec-1",
            reversed.capture_provenance.clone(),
        )
        .unwrap_err();
        assert_eq!(
            duplicate_schema.kind,
            RawRecordErrorKind::SourceSchemaDuplicateKey
        );
    }
}
