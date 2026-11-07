//! Immutable qualification attempt/evidence records and historical projection codecs.

use crate::execution_structure::{
    QualificationProfileManifest, StructureProjection, TemplateStructure, content_digest,
};
use crate::text_render::python_repr;
use serde_json::{Map, Value, json};
use std::fmt;

pub const PASS: &str = "PASS";
pub const FAIL: &str = "FAIL";
pub const ERROR: &str = "ERROR";
const LABEL_PROJECTION_SCHEMA: &str = "hwpx-structure-projection-v3";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QualificationEvidenceErrorKind {
    Invalid,
    ProfileIdentityMismatch,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationEvidenceError {
    pub kind: QualificationEvidenceErrorKind,
    pub detail: String,
}
impl fmt::Display for QualificationEvidenceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for QualificationEvidenceError {}
fn fail(detail: impl Into<String>) -> QualificationEvidenceError {
    QualificationEvidenceError {
        kind: QualificationEvidenceErrorKind::Invalid,
        detail: detail.into(),
    }
}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

pub fn verify_projection(
    projection: &StructureProjection,
) -> Result<(), QualificationEvidenceError> {
    if projection.payload_digest != content_digest(&projection.payload) {
        return Err(fail("structure projection payload_digest 불일치"));
    }
    Ok(())
}
/// Flat historical product projection; composition-ready v2/v4/TXT callers supply their own projection.
pub fn project_structure(
    structure: &TemplateStructure,
    schema: &str,
) -> Result<StructureProjection, QualificationEvidenceError> {
    let include_labels = schema == LABEL_PROJECTION_SCHEMA;
    if !include_labels
        && structure.slots.iter().any(|slot| {
            slot.label.is_some() || slot.options.iter().any(|option| option.label.is_some())
        })
    {
        return Err(fail(
            "label-bearing structure requires a label-bearing projection schema (hwpx-structure-projection-v3)",
        ));
    }
    let slots: Vec<_> = structure
        .slots
        .iter()
        .map(|slot| {
            let options: Vec<_> = slot
                .options
                .iter()
                .map(|option| {
                    let mut item = Map::new();
                    item.insert("id".into(), Value::String(option.id.clone()));
                    item.insert("fields".into(), json!(option.fields));
                    if include_labels {
                        item.insert(
                            "label".into(),
                            option.label.clone().map_or(Value::Null, Value::String),
                        );
                    }
                    Value::Object(item)
                })
                .collect();
            let mut item = Map::new();
            item.insert("id".into(), Value::String(slot.id.clone()));
            item.insert("shared_fields".into(), json!(slot.shared_fields));
            item.insert("options".into(), Value::Array(options));
            if include_labels {
                item.insert(
                    "label".into(),
                    slot.label.clone().map_or(Value::Null, Value::String),
                );
            }
            Value::Object(item)
        })
        .collect();
    let payload = json!({"root_fields":structure.root_fields,"slots":slots});
    Ok(StructureProjection {
        projection_schema_version: schema.into(),
        payload_digest: content_digest(&payload),
        payload,
    })
}
pub fn verify_manifest(
    manifest: &QualificationProfileManifest,
) -> Result<(), QualificationEvidenceError> {
    if manifest.manifest_digest != content_digest(&manifest.manifest_payload) {
        return Err(fail("manifest_digest 가 manifest_payload 와 불일치"));
    }
    Ok(())
}
pub struct ManifestInput<'a> {
    pub qualification_profile_id: &'a str,
    pub media: &'a str,
    pub adapter_contract_version: &'a str,
    pub product_rule_version: &'a str,
    pub operation_alphabet_version: &'a str,
    pub projection_schema_version: &'a str,
    pub manifest_payload: &'a Value,
    pub created_at: &'a str,
}
pub fn build_manifest(input: ManifestInput<'_>) -> QualificationProfileManifest {
    QualificationProfileManifest {
        qualification_profile_id: input.qualification_profile_id.into(),
        media: input.media.into(),
        adapter_contract_version: input.adapter_contract_version.into(),
        product_rule_version: input.product_rule_version.into(),
        operation_alphabet_version: input.operation_alphabet_version.into(),
        projection_schema_version: input.projection_schema_version.into(),
        manifest_payload: input.manifest_payload.clone(),
        manifest_digest: content_digest(input.manifest_payload),
        created_at: input.created_at.into(),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationProfileRevocation {
    pub qualification_profile_id: String,
    pub reason: String,
    pub authority: String,
    pub revoked_at: String,
}
pub fn verify_runtime_profile(
    manifest: &QualificationProfileManifest,
    runtime_profile_id: &str,
) -> Result<(), QualificationEvidenceError> {
    if manifest.qualification_profile_id != runtime_profile_id {
        return Err(QualificationEvidenceError {
            kind: QualificationEvidenceErrorKind::ProfileIdentityMismatch,
            detail: format!(
                "runtime profile {} != manifest {}",
                repr(runtime_profile_id),
                repr(&manifest.qualification_profile_id)
            ),
        });
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationAttempt {
    pub attempt_id: String,
    pub preparation_id: String,
    pub revision_id: String,
    pub qualification_profile_id: String,
    pub outcome: String,
    pub evidence_id: Option<String>,
    pub error_code: Option<String>,
    pub started_at: String,
    pub completed_at: String,
}
impl QualificationAttempt {
    pub fn validate(&self) -> Result<(), QualificationEvidenceError> {
        match self.outcome.as_str() {
            ERROR => {
                if self.evidence_id.is_some() {
                    return Err(fail("ERROR Attempt 는 Evidence 를 갖지 않는다"));
                }
                if self.error_code.as_deref().is_none_or(str::is_empty) {
                    return Err(fail("ERROR Attempt 는 error_code 가 필수다"));
                }
            }
            PASS | FAIL => {
                if self.evidence_id.is_none() {
                    return Err(fail(format!(
                        "{} Attempt 는 Evidence 가 필수다",
                        self.outcome
                    )));
                }
                if self.error_code.is_some() {
                    return Err(fail(format!(
                        "{} Attempt 에 error_code 가 있으면 안 된다",
                        self.outcome
                    )));
                }
            }
            _ => return Err(fail(format!("미상 outcome {}", repr(&self.outcome)))),
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationEvidence {
    pub evidence_id: String,
    pub attempt_id: String,
    pub revision_id: String,
    pub qualification_profile_id: String,
    pub result: String,
    pub structure_projection: Option<StructureProjection>,
    pub diagnostics: Vec<Map<String, Value>>,
    pub engine_metadata: Map<String, Value>,
    pub qualified_at: String,
}
impl QualificationEvidence {
    pub fn validate(&self) -> Result<(), QualificationEvidenceError> {
        match self.result.as_str() {
            PASS => {
                let projection = self
                    .structure_projection
                    .as_ref()
                    .ok_or_else(|| fail("PASS Evidence 는 structure projection 이 필수다"))?;
                verify_projection(projection)?;
                if !self.diagnostics.is_empty() {
                    return Err(fail("PASS Evidence 에 diagnostics 가 있으면 안 된다"));
                }
            }
            FAIL => {
                if self.structure_projection.is_some() {
                    return Err(fail("FAIL Evidence 에 structure 가 있으면 안 된다"));
                }
                if self.diagnostics.is_empty() {
                    return Err(fail("FAIL Evidence 는 diagnostics 가 1개 이상이다"));
                }
            }
            _ => {
                return Err(fail(format!(
                    "Evidence result 는 PASS|FAIL 뿐 ({})",
                    repr(&self.result)
                )));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationDiagnostic {
    pub kind: String,
    pub message: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum QualificationResult {
    Passed {
        revision_id: String,
        qualification_profile_id: String,
        structure: TemplateStructure,
    },
    Failed {
        revision_id: String,
        qualification_profile_id: String,
        diagnostics: Vec<QualificationDiagnostic>,
    },
    AttemptErrored {
        revision_id: String,
        qualification_profile_id: String,
        error_code: String,
    },
}
pub struct BuildRecordsInput<'a> {
    pub attempt_id: &'a str,
    pub preparation_id: &'a str,
    pub evidence_id: &'a str,
    pub projection_schema_version: &'a str,
    pub engine_metadata: &'a Map<String, Value>,
    pub started_at: &'a str,
    pub completed_at: &'a str,
    pub qualified_at: &'a str,
    pub structure_projection: Option<StructureProjection>,
}
fn verify_supplied_projection(
    result: &QualificationResult,
    input: &BuildRecordsInput<'_>,
) -> Result<(), QualificationEvidenceError> {
    if input.structure_projection.is_some() && !matches!(result, QualificationResult::Passed { .. })
    {
        return Err(fail(
            "PASS 아닌 결과에는 structure projection 을 실을 수 없다",
        ));
    }
    if let Some(projection) = &input.structure_projection {
        verify_projection(projection)?;
        if projection.projection_schema_version != input.projection_schema_version {
            return Err(fail(format!(
                "공급된 projection schema 가 pin 과 불일치: {} != {}",
                repr(&projection.projection_schema_version),
                repr(input.projection_schema_version)
            )));
        }
    }
    Ok(())
}
pub fn build_records(
    result: &QualificationResult,
    input: BuildRecordsInput<'_>,
) -> Result<(QualificationAttempt, Option<QualificationEvidence>), QualificationEvidenceError> {
    verify_supplied_projection(result, &input)?;
    let (revision_id, profile_id, outcome, evidence) = match result {
        QualificationResult::AttemptErrored {
            revision_id,
            qualification_profile_id,
            ..
        } => (revision_id, qualification_profile_id, ERROR, None),
        QualificationResult::Passed {
            revision_id,
            qualification_profile_id,
            structure,
        } => {
            let projection = match input.structure_projection {
                Some(projection) => projection,
                None => project_structure(structure, input.projection_schema_version)?,
            };
            let evidence = QualificationEvidence {
                evidence_id: input.evidence_id.into(),
                attempt_id: input.attempt_id.into(),
                revision_id: revision_id.clone(),
                qualification_profile_id: qualification_profile_id.clone(),
                result: PASS.into(),
                structure_projection: Some(projection),
                diagnostics: vec![],
                engine_metadata: input.engine_metadata.clone(),
                qualified_at: input.qualified_at.into(),
            };
            evidence.validate()?;
            (revision_id, qualification_profile_id, PASS, Some(evidence))
        }
        QualificationResult::Failed {
            revision_id,
            qualification_profile_id,
            diagnostics,
        } => {
            let diagnostics = diagnostics
                .iter()
                .map(|diagnostic| {
                    serde_json::from_value(
                        json!({"kind":diagnostic.kind,"message":diagnostic.message}),
                    )
                    .expect("object")
                })
                .collect();
            let evidence = QualificationEvidence {
                evidence_id: input.evidence_id.into(),
                attempt_id: input.attempt_id.into(),
                revision_id: revision_id.clone(),
                qualification_profile_id: qualification_profile_id.clone(),
                result: FAIL.into(),
                structure_projection: None,
                diagnostics,
                engine_metadata: input.engine_metadata.clone(),
                qualified_at: input.qualified_at.into(),
            };
            evidence.validate()?;
            (revision_id, qualification_profile_id, FAIL, Some(evidence))
        }
    };
    let attempt = QualificationAttempt {
        attempt_id: input.attempt_id.into(),
        preparation_id: input.preparation_id.into(),
        revision_id: revision_id.clone(),
        qualification_profile_id: profile_id.clone(),
        outcome: outcome.into(),
        evidence_id: evidence
            .as_ref()
            .map(|evidence| evidence.evidence_id.clone()),
        error_code: if let QualificationResult::AttemptErrored { error_code, .. } = result {
            Some(error_code.clone())
        } else {
            None
        },
        started_at: input.started_at.into(),
        completed_at: input.completed_at.into(),
    };
    attempt.validate()?;
    Ok((attempt, evidence))
}
pub fn validate_evidence_binding(
    attempt: &QualificationAttempt,
    evidence: &QualificationEvidence,
) -> Result<(), QualificationEvidenceError> {
    attempt.validate()?;
    evidence.validate()?;
    if evidence.attempt_id != attempt.attempt_id {
        return Err(fail("Evidence.attempt_id 가 Attempt 와 불일치"));
    }
    if attempt.evidence_id.as_deref() != Some(evidence.evidence_id.as_str()) {
        return Err(fail("Attempt.evidence_id 가 Evidence 와 불일치"));
    }
    if evidence.revision_id != attempt.revision_id {
        return Err(fail("Evidence revision 이 Attempt 와 불일치"));
    }
    if evidence.qualification_profile_id != attempt.qualification_profile_id {
        return Err(fail("Evidence profile 이 Attempt 와 불일치"));
    }
    if evidence.result != attempt.outcome {
        return Err(fail("Evidence result 가 Attempt outcome 과 불일치"));
    }
    Ok(())
}

fn object(value: &Value) -> Result<&Map<String, Value>, QualificationEvidenceError> {
    value
        .as_object()
        .ok_or_else(|| fail("영속 객체는 사전이어야 한다"))
}
fn field<'a>(
    data: &'a Map<String, Value>,
    key: &str,
) -> Result<&'a Value, QualificationEvidenceError> {
    data.get(key).ok_or_else(|| fail(format!("{key} 누락")))
}
fn string(data: &Map<String, Value>, key: &str) -> Result<String, QualificationEvidenceError> {
    field(data, key)?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| fail(format!("{key} 는 문자열이어야 한다")))
}
fn optional_string(
    data: &Map<String, Value>,
    key: &str,
) -> Result<Option<String>, QualificationEvidenceError> {
    match field(data, key)? {
        Value::Null => Ok(None),
        Value::String(value) => Ok(Some(value.clone())),
        _ => Err(fail(format!("{key} 는 문자열 또는 null 이어야 한다"))),
    }
}
pub fn encode_manifest(manifest: &QualificationProfileManifest) -> Value {
    json!({"qualification_profile_id":manifest.qualification_profile_id,"media":manifest.media,"adapter_contract_version":manifest.adapter_contract_version,"product_rule_version":manifest.product_rule_version,"operation_alphabet_version":manifest.operation_alphabet_version,"projection_schema_version":manifest.projection_schema_version,"manifest_payload":manifest.manifest_payload,"manifest_digest":manifest.manifest_digest,"created_at":manifest.created_at})
}
pub fn decode_manifest(
    value: &Value,
) -> Result<QualificationProfileManifest, QualificationEvidenceError> {
    let data = object(value)?;
    let manifest = QualificationProfileManifest {
        qualification_profile_id: string(data, "qualification_profile_id")?,
        media: string(data, "media")?,
        adapter_contract_version: string(data, "adapter_contract_version")?,
        product_rule_version: string(data, "product_rule_version")?,
        operation_alphabet_version: string(data, "operation_alphabet_version")?,
        projection_schema_version: string(data, "projection_schema_version")?,
        manifest_payload: field(data, "manifest_payload")?.clone(),
        manifest_digest: string(data, "manifest_digest")?,
        created_at: string(data, "created_at")?,
    };
    verify_manifest(&manifest)?;
    Ok(manifest)
}
pub fn encode_revocation(item: &QualificationProfileRevocation) -> Value {
    json!({"qualification_profile_id":item.qualification_profile_id,"reason":item.reason,"authority":item.authority,"revoked_at":item.revoked_at})
}
pub fn decode_revocation(
    value: &Value,
) -> Result<QualificationProfileRevocation, QualificationEvidenceError> {
    let data = object(value)?;
    Ok(QualificationProfileRevocation {
        qualification_profile_id: string(data, "qualification_profile_id")?,
        reason: string(data, "reason")?,
        authority: string(data, "authority")?,
        revoked_at: string(data, "revoked_at")?,
    })
}
pub fn encode_attempt(item: &QualificationAttempt) -> Value {
    json!({"attempt_id":item.attempt_id,"preparation_id":item.preparation_id,"revision_id":item.revision_id,"qualification_profile_id":item.qualification_profile_id,"outcome":item.outcome,"evidence_id":item.evidence_id,"error_code":item.error_code,"started_at":item.started_at,"completed_at":item.completed_at})
}
pub fn decode_attempt(value: &Value) -> Result<QualificationAttempt, QualificationEvidenceError> {
    let data = object(value)?;
    let item = QualificationAttempt {
        attempt_id: string(data, "attempt_id")?,
        preparation_id: string(data, "preparation_id")?,
        revision_id: string(data, "revision_id")?,
        qualification_profile_id: string(data, "qualification_profile_id")?,
        outcome: string(data, "outcome")?,
        evidence_id: optional_string(data, "evidence_id")?,
        error_code: optional_string(data, "error_code")?,
        started_at: string(data, "started_at")?,
        completed_at: string(data, "completed_at")?,
    };
    item.validate()?;
    Ok(item)
}
pub fn encode_evidence(item: &QualificationEvidence) -> Value {
    json!({"evidence_id":item.evidence_id,"attempt_id":item.attempt_id,"revision_id":item.revision_id,"qualification_profile_id":item.qualification_profile_id,"result":item.result,"structure_projection":item.structure_projection.as_ref().map(|p|json!({"projection_schema_version":p.projection_schema_version,"payload":p.payload,"payload_digest":p.payload_digest})),"diagnostics":item.diagnostics,"engine_metadata":item.engine_metadata,"qualified_at":item.qualified_at})
}
pub fn decode_evidence(value: &Value) -> Result<QualificationEvidence, QualificationEvidenceError> {
    let data = object(value)?;
    let projection = match field(data, "structure_projection")? {
        Value::Null => None,
        value => {
            let data = object(value)?;
            let projection = StructureProjection {
                projection_schema_version: string(data, "projection_schema_version")?,
                payload: field(data, "payload")?.clone(),
                payload_digest: string(data, "payload_digest")?,
            };
            verify_projection(&projection)?;
            Some(projection)
        }
    };
    let diagnostics = field(data, "diagnostics")?
        .as_array()
        .ok_or_else(|| fail("diagnostics 는 목록이어야 한다"))?
        .iter()
        .map(|value| object(value).cloned())
        .collect::<Result<Vec<_>, _>>()?;
    let item = QualificationEvidence {
        evidence_id: string(data, "evidence_id")?,
        attempt_id: string(data, "attempt_id")?,
        revision_id: string(data, "revision_id")?,
        qualification_profile_id: string(data, "qualification_profile_id")?,
        result: string(data, "result")?,
        structure_projection: projection,
        diagnostics,
        engine_metadata: object(field(data, "engine_metadata")?)?.clone(),
        qualified_at: string(data, "qualified_at")?,
    };
    item.validate()?;
    Ok(item)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{TemplateOption, TemplateSlot};

    fn records(
        result: &QualificationResult,
        projection: Option<StructureProjection>,
    ) -> Result<(QualificationAttempt, Option<QualificationEvidence>), QualificationEvidenceError>
    {
        build_records(
            result,
            BuildRecordsInput {
                attempt_id: "a",
                preparation_id: "p",
                evidence_id: "e",
                projection_schema_version: "proj-v1",
                engine_metadata: &Map::from_iter([("engine".into(), json!({"version":1}))]),
                started_at: "t0",
                completed_at: "t1",
                qualified_at: "t2",
                structure_projection: projection,
            },
        )
    }

    #[test]
    fn records_preserve_outcomes_pins_and_reject_invalid_evidence() {
        let structure = TemplateStructure {
            root_fields: vec!["title".into()],
            slots: vec![TemplateSlot {
                id: "notice".into(),
                shared_fields: vec!["date".into()],
                label: None,
                options: vec![TemplateOption {
                    id: "A".into(),
                    fields: vec!["amount".into()],
                    label: None,
                }],
            }],
        };
        let passed = QualificationResult::Passed {
            revision_id: "r".into(),
            qualification_profile_id: "profile".into(),
            structure: structure.clone(),
        };
        let failed = QualificationResult::Failed {
            revision_id: "r".into(),
            qualification_profile_id: "profile".into(),
            diagnostics: vec![QualificationDiagnostic {
                kind: "invalid".into(),
                message: "broken".into(),
            }],
        };
        let errored = QualificationResult::AttemptErrored {
            revision_id: "r".into(),
            qualification_profile_id: "profile".into(),
            error_code: "reader-error".into(),
        };
        let projection = project_structure(&structure, "proj-v1").unwrap();
        assert_eq!(
            projection.payload,
            json!({"root_fields":["title"],"slots":[{"id":"notice","shared_fields":["date"],"options":[{"id":"A","fields":["amount"]}]}]})
        );
        for (result, outcome) in [(&passed, PASS), (&failed, FAIL), (&errored, ERROR)] {
            let (attempt, evidence) = records(result, None).unwrap();
            assert_eq!(
                attempt,
                QualificationAttempt {
                    attempt_id: "a".into(),
                    preparation_id: "p".into(),
                    revision_id: "r".into(),
                    qualification_profile_id: "profile".into(),
                    outcome: outcome.into(),
                    evidence_id: (outcome != ERROR).then(|| "e".into()),
                    error_code: (outcome == ERROR).then(|| "reader-error".into()),
                    started_at: "t0".into(),
                    completed_at: "t1".into(),
                }
            );
            assert_eq!(decode_attempt(&encode_attempt(&attempt)).unwrap(), attempt);
            if let Some(evidence) = evidence {
                validate_evidence_binding(&attempt, &evidence).unwrap();
                assert_eq!(evidence.result, outcome);
                assert_eq!(evidence.qualified_at, "t2");
                assert_eq!(evidence.engine_metadata["engine"], json!({"version":1}));
                assert_eq!(
                    evidence.structure_projection,
                    (outcome == PASS).then(|| projection.clone())
                );
                assert_eq!(
                    evidence.diagnostics,
                    if outcome == FAIL {
                        vec![
                            serde_json::from_value(json!({"kind":"invalid","message":"broken"}))
                                .unwrap(),
                        ]
                    } else {
                        vec![]
                    }
                );
                assert_eq!(
                    decode_evidence(&encode_evidence(&evidence)).unwrap(),
                    evidence
                );
            } else {
                assert_eq!(outcome, ERROR);
            }
        }
        assert!(records(&failed, Some(projection.clone())).is_err());
        assert!(records(&errored, Some(projection.clone())).is_err());
        assert_eq!(
            records(&passed, Some(projection.clone())).unwrap(),
            records(&passed, None).unwrap()
        );
        let mut wrong = projection.clone();
        wrong.projection_schema_version = "other".into();
        assert!(
            records(&passed, Some(wrong))
                .unwrap_err()
                .detail
                .contains("schema")
        );
        let mut wrong = projection;
        wrong.payload["root_fields"] = json!(["changed"]);
        assert!(
            records(&passed, Some(wrong))
                .unwrap_err()
                .detail
                .contains("payload_digest")
        );

        let (attempt, evidence) = records(&passed, None).unwrap();
        let evidence = evidence.unwrap();
        for (key, value) in [
            ("result", json!("ERROR")),
            ("structure_projection", Value::Null),
            ("diagnostics", json!([{"kind":"bad"}])),
        ] {
            let mut encoded = encode_evidence(&evidence);
            encoded[key] = value;
            assert!(decode_evidence(&encoded).is_err(), "{key}");
        }
        let (_, failed_evidence) = records(&failed, None).unwrap();
        for (key, value) in [
            ("diagnostics", json!([])),
            (
                "structure_projection",
                encode_evidence(&evidence)["structure_projection"].clone(),
            ),
        ] {
            let mut encoded = encode_evidence(&failed_evidence.clone().unwrap());
            encoded[key] = value;
            assert!(decode_evidence(&encoded).is_err(), "FAIL {key}");
        }
        for (outcome, id, code) in [
            (ERROR, Some("e"), Some("error")),
            (ERROR, None, None),
            (ERROR, None, Some("")),
            (PASS, None, None),
            (PASS, Some("e"), Some("error")),
            (FAIL, None, None),
            (FAIL, Some("e"), Some("error")),
            ("unknown", None, None),
        ] {
            let mut broken = attempt.clone();
            broken.outcome = outcome.into();
            broken.evidence_id = id.map(str::to_owned);
            broken.error_code = code.map(str::to_owned);
            assert!(
                decode_attempt(&encode_attempt(&broken)).is_err(),
                "{broken:?}"
            );
        }
        for key in [
            "attempt_id",
            "evidence_id",
            "revision_id",
            "qualification_profile_id",
        ] {
            let mut encoded = encode_evidence(&evidence);
            encoded[key] = json!("other");
            let mismatched = decode_evidence(&encoded).unwrap();
            assert!(
                validate_evidence_binding(&attempt, &mismatched).is_err(),
                "{key}"
            );
        }
        assert!(validate_evidence_binding(&attempt, &failed_evidence.unwrap()).is_err());
        let mut labeled = structure;
        labeled.slots[0].options[0].label = Some("계약서".into());
        assert!(project_structure(&labeled, "proj-v1").is_err());
        labeled.slots[0].label = Some("첨부".into());
        let labeled = project_structure(&labeled, LABEL_PROJECTION_SCHEMA).unwrap();
        assert_eq!(labeled.payload["slots"][0]["label"], "첨부");
        assert_eq!(labeled.payload["slots"][0]["options"][0]["label"], "계약서");
    }

    #[test]
    fn immutable_payloads_and_codecs_reject_damaged_records() {
        let mut payload = json!({"rules":["x"]});
        let manifest = build_manifest(ManifestInput {
            qualification_profile_id: "profile",
            media: "hwpx",
            adapter_contract_version: "a1",
            product_rule_version: "r1",
            operation_alphabet_version: "o1",
            projection_schema_version: "proj-v1",
            manifest_payload: &payload,
            created_at: "t0",
        });
        payload["rules"][0] = json!("mutated");
        assert_eq!(manifest.manifest_payload, json!({"rules":["x"]}));
        verify_runtime_profile(&manifest, "profile").unwrap();
        assert_eq!(
            verify_runtime_profile(&manifest, "other").unwrap_err().kind,
            QualificationEvidenceErrorKind::ProfileIdentityMismatch
        );
        let revocation = QualificationProfileRevocation {
            qualification_profile_id: "profile".into(),
            reason: "superseded".into(),
            authority: "owner".into(),
            revoked_at: "t3".into(),
        };
        let result = QualificationResult::Passed {
            revision_id: "r".into(),
            qualification_profile_id: "profile".into(),
            structure: TemplateStructure::default(),
        };
        let mut metadata = Map::from_iter([("engine".into(), json!({"version":1}))]);
        let (_, evidence) = build_records(
            &result,
            BuildRecordsInput {
                attempt_id: "a",
                preparation_id: "p",
                evidence_id: "e",
                projection_schema_version: "proj-v1",
                engine_metadata: &metadata,
                started_at: "t0",
                completed_at: "t1",
                qualified_at: "t2",
                structure_projection: None,
            },
        )
        .unwrap();
        metadata["engine"]["version"] = json!(2);
        assert_eq!(
            evidence.as_ref().unwrap().engine_metadata["engine"]["version"],
            1
        );
        let (attempt, _) = records(&result, None).unwrap();
        type Decoder = fn(&Value) -> Result<(), QualificationEvidenceError>;
        let codecs: [(Value, Decoder); 4] = [
            (encode_manifest(&manifest), |v| {
                decode_manifest(v).map(|_| ())
            }),
            (encode_revocation(&revocation), |v| {
                decode_revocation(v).map(|_| ())
            }),
            (encode_attempt(&attempt), |v| decode_attempt(v).map(|_| ())),
            (encode_evidence(&evidence.unwrap()), |v| {
                decode_evidence(v).map(|_| ())
            }),
        ];
        assert_eq!(
            decode_manifest(&encode_manifest(&manifest)).unwrap(),
            manifest
        );
        assert_eq!(
            decode_revocation(&encode_revocation(&revocation)).unwrap(),
            revocation
        );
        for (encoded, decode) in codecs {
            decode(&encoded).unwrap();
            assert!(decode(&Value::Null).is_err());
            for key in encoded.as_object().unwrap().keys() {
                let mut missing = encoded.clone();
                missing.as_object_mut().unwrap().remove(key);
                assert!(
                    decode(&missing).unwrap_err().detail.contains("누락"),
                    "{key}"
                );
                if key == "manifest_payload" {
                    continue;
                }
                let mut wrong_type = encoded.clone();
                wrong_type[key] = json!(42);
                assert!(decode(&wrong_type).is_err(), "{key}");
            }
        }
        let mut corrupt = encode_manifest(&manifest);
        corrupt["manifest_payload"] = payload;
        assert!(
            decode_manifest(&corrupt)
                .unwrap_err()
                .detail
                .contains("manifest_digest")
        );
        let (_, evidence) = records(&result, None).unwrap();
        for key in ["projection_schema_version", "payload", "payload_digest"] {
            let mut corrupt = encode_evidence(&evidence.clone().unwrap());
            corrupt["structure_projection"]
                .as_object_mut()
                .unwrap()
                .remove(key);
            assert!(decode_evidence(&corrupt).is_err(), "{key}");
        }
    }
}
