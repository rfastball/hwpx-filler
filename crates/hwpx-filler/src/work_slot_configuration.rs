//! Application-bound working selection values, version semantics and durable codec.

use crate::slot_selection::{
    SlotSelectionSet, declared_selection_digest, decode_selection_set, encode_selection_set,
    semantic_selection_equal,
};
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fmt;

pub const SCHEMA_VERSION: &str = "work-slot-configuration-v1";
pub const EMPTY: &str = "EMPTY";
pub const RECONCILED_FROM_PREDECESSOR: &str = "RECONCILED_FROM_PREDECESSOR";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkSlotConfigurationError(pub String);
impl fmt::Display for WorkSlotConfigurationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for WorkSlotConfigurationError {}
fn fail(detail: impl Into<String>) -> WorkSlotConfigurationError {
    WorkSlotConfigurationError(detail.into())
}
fn require_nonempty(value: &str, what: &str) -> Result<(), WorkSlotConfigurationError> {
    if value.is_empty() {
        Err(fail(format!("{what} 는 비어 있지 않은 문자열이어야 한다")))
    } else {
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkSlotConfigurationDraft {
    pub work_id: String,
    pub base_template_application_id: String,
    pub version: u64,
    pub selections: SlotSelectionSet,
    pub origin: String,
    pub reconciled_from_application_id: Option<String>,
    pub reconciled_from_version: Option<u64>,
    pub reconciled_from_declared_selection_digest: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}
impl WorkSlotConfigurationDraft {
    pub fn validate(&self) -> Result<(), WorkSlotConfigurationError> {
        for (name, value) in [
            ("work_id", &self.work_id),
            (
                "base_template_application_id",
                &self.base_template_application_id,
            ),
            ("created_at", &self.created_at),
            ("updated_at", &self.updated_at),
        ] {
            require_nonempty(value, name)?;
        }
        self.selections
            .validate()
            .map_err(|error| fail(error.to_string()))?;
        if self.version < 1 {
            return Err(fail("version 은 1 이상이다"));
        }
        self.validate_provenance()
    }
    fn validate_provenance(&self) -> Result<(), WorkSlotConfigurationError> {
        match self.origin.as_str() {
            EMPTY => {
                if self.reconciled_from_application_id.is_some()
                    || self.reconciled_from_version.is_some()
                    || self.reconciled_from_declared_selection_digest.is_some()
                {
                    return Err(fail(
                        "EMPTY origin 은 predecessor provenance 를 가질 수 없다",
                    ));
                }
            }
            RECONCILED_FROM_PREDECESSOR => {
                let Some(app) = self.reconciled_from_application_id.as_deref() else {
                    return Err(fail(
                        "RECONCILED origin 은 세 provenance 가 모두 있어야 한다",
                    ));
                };
                let Some(version) = self.reconciled_from_version else {
                    return Err(fail(
                        "RECONCILED origin 은 세 provenance 가 모두 있어야 한다",
                    ));
                };
                let Some(digest) = self.reconciled_from_declared_selection_digest.as_deref() else {
                    return Err(fail(
                        "RECONCILED origin 은 세 provenance 가 모두 있어야 한다",
                    ));
                };
                require_nonempty(app, "reconciled_from_application_id")?;
                require_nonempty(digest, "reconciled_from_declared_selection_digest")?;
                if version < 1 {
                    return Err(fail("reconciled_from_version 은 1 이상이다"));
                }
            }
            _ => {
                return Err(fail(format!(
                    "미상 origin {}",
                    python_repr(&Value::String(self.origin.clone()))
                )));
            }
        }
        Ok(())
    }
    pub fn is_empty(&self) -> bool {
        self.selections.selections.is_empty()
    }
}
pub fn create_empty(
    work: &str,
    application: &str,
    now: &str,
) -> Result<WorkSlotConfigurationDraft, WorkSlotConfigurationError> {
    let draft = WorkSlotConfigurationDraft {
        work_id: work.into(),
        base_template_application_id: application.into(),
        version: 1,
        selections: SlotSelectionSet::default(),
        origin: EMPTY.into(),
        reconciled_from_application_id: None,
        reconciled_from_version: None,
        reconciled_from_declared_selection_digest: None,
        created_at: now.into(),
        updated_at: now.into(),
    };
    draft.validate()?;
    Ok(draft)
}
pub fn create_reconciled(
    work: &str,
    application: &str,
    selections: SlotSelectionSet,
    source_application: &str,
    source_version: u64,
    source_digest: &str,
    now: &str,
) -> Result<WorkSlotConfigurationDraft, WorkSlotConfigurationError> {
    let draft = WorkSlotConfigurationDraft {
        work_id: work.into(),
        base_template_application_id: application.into(),
        version: 1,
        selections,
        origin: RECONCILED_FROM_PREDECESSOR.into(),
        reconciled_from_application_id: Some(source_application.into()),
        reconciled_from_version: Some(source_version),
        reconciled_from_declared_selection_digest: Some(source_digest.into()),
        created_at: now.into(),
        updated_at: now.into(),
    };
    draft.validate()?;
    Ok(draft)
}
pub fn apply_selections(
    draft: &WorkSlotConfigurationDraft,
    selections: SlotSelectionSet,
    now: &str,
) -> Result<WorkSlotConfigurationDraft, WorkSlotConfigurationError> {
    draft.validate()?;
    selections
        .validate()
        .map_err(|error| fail(error.to_string()))?;
    if semantic_selection_equal(&draft.selections, &selections)
        .map_err(|error| fail(error.to_string()))?
    {
        return Ok(draft.clone());
    }
    let mut changed = draft.clone();
    changed.selections = selections;
    changed.version = changed
        .version
        .checked_add(1)
        .ok_or_else(|| fail("version 범위를 초과했습니다"))?;
    changed.updated_at = now.into();
    changed.validate()?;
    Ok(changed)
}
pub fn has_declared_selection(config: Option<&WorkSlotConfigurationDraft>) -> bool {
    config.is_some_and(|config| !config.selections.selections.is_empty())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkSlotConfigurationAggregate {
    pub schema_version: String,
    pub work_id: String,
    pub configurations: Vec<WorkSlotConfigurationDraft>,
}
impl WorkSlotConfigurationAggregate {
    pub fn validate(&self) -> Result<(), WorkSlotConfigurationError> {
        if self.schema_version != SCHEMA_VERSION {
            return Err(fail(format!(
                "미상 schema_version {}",
                python_repr(&Value::String(self.schema_version.clone()))
            )));
        }
        require_nonempty(&self.work_id, "work_id")?;
        let mut seen = HashSet::new();
        for config in &self.configurations {
            config.validate()?;
            if config.work_id != self.work_id {
                return Err(fail(
                    "Configuration 의 work_id 가 aggregate owner 와 불일치",
                ));
            }
            if !seen.insert(config.base_template_application_id.as_str()) {
                return Err(fail("같은 Application 의 Configuration 중복"));
            }
        }
        Ok(())
    }
}
pub fn empty_aggregate(
    work: &str,
) -> Result<WorkSlotConfigurationAggregate, WorkSlotConfigurationError> {
    let aggregate = WorkSlotConfigurationAggregate {
        schema_version: SCHEMA_VERSION.into(),
        work_id: work.into(),
        configurations: Vec::new(),
    };
    aggregate.validate()?;
    Ok(aggregate)
}
fn encode_config(config: &WorkSlotConfigurationDraft) -> Result<Value, WorkSlotConfigurationError> {
    config.validate()?;
    let mut out = Map::new();
    out.insert("work_id".into(), Value::String(config.work_id.clone()));
    out.insert(
        "base_template_application_id".into(),
        Value::String(config.base_template_application_id.clone()),
    );
    out.insert("version".into(), Value::from(config.version));
    out.insert(
        "selections".into(),
        encode_selection_set(&config.selections).map_err(|error| fail(error.to_string()))?,
    );
    out.insert(
        "declared_selection_digest".into(),
        Value::String(
            declared_selection_digest(&config.selections)
                .map_err(|error| fail(error.to_string()))?,
        ),
    );
    out.insert("origin".into(), Value::String(config.origin.clone()));
    out.insert(
        "reconciled_from_application_id".into(),
        config
            .reconciled_from_application_id
            .clone()
            .map_or(Value::Null, Value::String),
    );
    out.insert(
        "reconciled_from_version".into(),
        config
            .reconciled_from_version
            .map_or(Value::Null, Value::from),
    );
    out.insert(
        "reconciled_from_declared_selection_digest".into(),
        config
            .reconciled_from_declared_selection_digest
            .clone()
            .map_or(Value::Null, Value::String),
    );
    out.insert(
        "created_at".into(),
        Value::String(config.created_at.clone()),
    );
    out.insert(
        "updated_at".into(),
        Value::String(config.updated_at.clone()),
    );
    Ok(Value::Object(out))
}
pub fn encode_aggregate(
    aggregate: &WorkSlotConfigurationAggregate,
) -> Result<Value, WorkSlotConfigurationError> {
    aggregate.validate()?;
    let mut out = Map::new();
    out.insert(
        "schema_version".into(),
        Value::String(aggregate.schema_version.clone()),
    );
    out.insert("work_id".into(), Value::String(aggregate.work_id.clone()));
    out.insert(
        "configurations".into(),
        Value::Array(
            aggregate
                .configurations
                .iter()
                .map(encode_config)
                .collect::<Result<_, _>>()?,
        ),
    );
    Ok(Value::Object(out))
}
fn text(data: &Map<String, Value>, key: &str) -> Result<String, WorkSlotConfigurationError> {
    data.get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| fail(format!("{key} 는 비어 있지 않은 문자열이어야 한다")))
}
fn optional_text(
    data: &Map<String, Value>,
    key: &str,
) -> Result<Option<String>, WorkSlotConfigurationError> {
    match data.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        _ => Err(fail(format!("{key} 는 비어 있지 않은 문자열이어야 한다"))),
    }
}
fn positive(data: &Map<String, Value>, key: &str) -> Result<u64, WorkSlotConfigurationError> {
    let value = data
        .get(key)
        .ok_or_else(|| fail(format!("{key} 은 정수여야 한다")))?;
    if value.is_boolean()
        || !value.is_number()
        || value.as_i64().is_none() && value.as_u64().is_none()
    {
        return Err(fail(format!("{key} 은 정수여야 한다")));
    }
    if value.as_i64().is_some_and(|number| number < 1) || value.as_u64() == Some(0) {
        return Err(fail(format!("{key} 은 1 이상이다")));
    }
    value
        .as_u64()
        .ok_or_else(|| fail(format!("{key} 은 정수여야 한다")))
}
fn decode_config(raw: &Value) -> Result<WorkSlotConfigurationDraft, WorkSlotConfigurationError> {
    let data = raw
        .as_object()
        .ok_or_else(|| fail("Configuration 표현이 malformed"))?;
    let selections = decode_selection_set(data.get("selections").unwrap_or(&Value::Null))
        .map_err(|error| fail(error.to_string()))?;
    let digest = declared_selection_digest(&selections).map_err(|error| fail(error.to_string()))?;
    if data.get("declared_selection_digest") != Some(&Value::String(digest)) {
        return Err(fail(
            "저장된 selection digest 가 복원 selection 과 불일치(손상·드리프트)",
        ));
    }
    let work_id = text(data, "work_id")?;
    let base_template_application_id = text(data, "base_template_application_id")?;
    let created_at = text(data, "created_at")?;
    let updated_at = text(data, "updated_at")?;
    let version = positive(data, "version")?;
    let raw_origin = data.get("origin").unwrap_or(&Value::Null);
    let origin = raw_origin.as_str().unwrap_or("");
    if origin != EMPTY && origin != RECONCILED_FROM_PREDECESSOR {
        return Err(fail(format!("미상 origin {}", python_repr(raw_origin))));
    }
    let provenance_keys = [
        "reconciled_from_application_id",
        "reconciled_from_version",
        "reconciled_from_declared_selection_digest",
    ];
    let present = |key: &str| data.get(key).is_some_and(|value| !value.is_null());
    if origin == EMPTY && provenance_keys.iter().any(|key| present(key)) {
        return Err(fail(
            "EMPTY origin 은 predecessor provenance 를 가질 수 없다",
        ));
    }
    if origin == RECONCILED_FROM_PREDECESSOR && provenance_keys.iter().any(|key| !present(key)) {
        return Err(fail(
            "RECONCILED origin 은 세 provenance 가 모두 있어야 한다",
        ));
    }
    let reconciled_from_application_id = optional_text(data, "reconciled_from_application_id")?;
    let reconciled_from_version = if origin == RECONCILED_FROM_PREDECESSOR {
        Some(positive(data, "reconciled_from_version")?)
    } else {
        None
    };
    let reconciled_from_declared_selection_digest =
        optional_text(data, "reconciled_from_declared_selection_digest")?;
    let draft = WorkSlotConfigurationDraft {
        work_id,
        base_template_application_id,
        version,
        selections,
        origin: origin.into(),
        reconciled_from_application_id,
        reconciled_from_version,
        reconciled_from_declared_selection_digest,
        created_at,
        updated_at,
    };
    draft.validate()?;
    Ok(draft)
}
pub fn decode_aggregate(
    raw: &Value,
) -> Result<WorkSlotConfigurationAggregate, WorkSlotConfigurationError> {
    let data = raw
        .as_object()
        .ok_or_else(|| fail("Configuration aggregate 표현이 malformed"))?;
    if data.get("schema_version") != Some(&Value::String(SCHEMA_VERSION.into())) {
        return Err(fail(format!(
            "미상 schema_version {}",
            python_repr(data.get("schema_version").unwrap_or(&Value::Null))
        )));
    }
    let configs = data
        .get("configurations")
        .and_then(Value::as_array)
        .ok_or_else(|| fail("configurations 는 목록이어야 한다"))?;
    let aggregate = WorkSlotConfigurationAggregate {
        schema_version: SCHEMA_VERSION.into(),
        work_id: text(data, "work_id")?,
        configurations: configs
            .iter()
            .map(decode_config)
            .collect::<Result<_, _>>()?,
    };
    aggregate.validate()?;
    Ok(aggregate)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::slot_selection::SlotSelection;
    use serde_json::json;
    #[test]
    fn reordered_same_selection_is_noop_and_codec_rejects_digest_tamper() {
        let empty = create_empty("work", "application", "t1").unwrap();
        assert!(empty.is_empty());
        assert_eq!(empty.version, 1);
        assert_eq!(empty.origin, EMPTY);
        assert_eq!(empty.reconciled_from_application_id, None);
        assert_eq!(empty.reconciled_from_version, None);
        assert_eq!(empty.reconciled_from_declared_selection_digest, None);
        assert!(!has_declared_selection(None));
        assert!(!has_declared_selection(Some(&empty)));
        assert_eq!(empty_aggregate("work").unwrap().configurations, vec![]);
        let set = SlotSelectionSet::new(vec![
            SlotSelection::new("slot", vec!["a".into(), "b".into()]).unwrap(),
        ])
        .unwrap();
        let changed = apply_selections(&empty, set.clone(), "t2").unwrap();
        assert_eq!(changed.version, 2);
        assert_eq!(
            (&changed.created_at, &changed.updated_at, &changed.origin),
            (&"t1".to_owned(), &"t2".to_owned(), &EMPTY.to_owned())
        );
        assert!(has_declared_selection(Some(&changed)));
        let reordered = SlotSelectionSet::new(vec![
            SlotSelection::new("slot", vec!["b".into(), "a".into()]).unwrap(),
        ])
        .unwrap();
        assert_eq!(
            apply_selections(&changed, reordered, "t3").unwrap(),
            changed
        );
        let aggregate = WorkSlotConfigurationAggregate {
            schema_version: SCHEMA_VERSION.into(),
            work_id: "work".into(),
            configurations: vec![changed],
        };
        let mut encoded = encode_aggregate(&aggregate).unwrap();
        assert_eq!(decode_aggregate(&encoded).unwrap(), aggregate);
        encoded["configurations"][0]["declared_selection_digest"] =
            Value::String("sha256:wrong".into());
        assert!(decode_aggregate(&encoded).unwrap_err().0.contains("digest"));
        let mut malformed = encode_aggregate(&aggregate).unwrap();
        malformed["configurations"][0]["reconciled_from_version"] = Value::Bool(false);
        assert_eq!(
            decode_aggregate(&malformed).unwrap_err().0,
            "EMPTY origin 은 predecessor provenance 를 가질 수 없다"
        );
        malformed["configurations"][0]["reconciled_from_version"] = Value::Null;
        malformed["configurations"][0]["version"] = Value::from(-1);
        assert_eq!(
            decode_aggregate(&malformed).unwrap_err().0,
            "version 은 1 이상이다"
        );
        let reconciled = create_reconciled(
            "work",
            "next",
            set.clone(),
            "application",
            3,
            &declared_selection_digest(&set).unwrap(),
            "t4",
        )
        .unwrap();
        assert_eq!(reconciled.version, 1);
        assert_eq!(reconciled.origin, RECONCILED_FROM_PREDECESSOR);
        assert_eq!(
            reconciled.reconciled_from_application_id.as_deref(),
            Some("application")
        );
        assert_eq!(reconciled.reconciled_from_version, Some(3));
        assert_eq!(
            reconciled
                .reconciled_from_declared_selection_digest
                .as_deref(),
            Some(declared_selection_digest(&set).unwrap().as_str())
        );
        let cleared = apply_selections(&reconciled, SlotSelectionSet::default(), "t5").unwrap();
        assert!(cleared.is_empty());
        let mut expected = reconciled.clone();
        expected.selections = SlotSelectionSet::default();
        expected.version = 2;
        expected.updated_at = "t5".into();
        assert_eq!(cleared, expected);
        let mut aggregate = empty_aggregate("work").unwrap();
        aggregate.configurations = vec![empty.clone(), cleared, reconciled.clone()];
        assert!(aggregate.validate().is_err());
        aggregate.configurations.pop();
        assert_eq!(
            decode_aggregate(&encode_aggregate(&aggregate).unwrap()).unwrap(),
            aggregate
        );
        aggregate.configurations[1].work_id = "foreign".into();
        assert!(aggregate.validate().is_err());
        aggregate.configurations.clear();
        aggregate.schema_version = "unknown".into();
        assert!(aggregate.validate().is_err());
        let mut max_version = empty.clone();
        max_version.version = u64::MAX;
        assert_eq!(
            apply_selections(&max_version, SlotSelectionSet::default(), "later").unwrap(),
            max_version
        );
        assert!(apply_selections(&max_version, set, "later").is_err());

        for (key, value) in [
            ("work_id", json!("")),
            ("base_template_application_id", json!("")),
            ("created_at", json!("")),
            ("updated_at", json!("")),
            ("origin", json!("MADE_UP")),
            ("selections", json!(42)),
            ("version", json!(0)),
            ("version", json!(1.5)),
            ("version", json!(true)),
            ("version", json!("1")),
        ] {
            let mut encoded = encode_config(&empty).unwrap();
            encoded[key] = value;
            assert!(decode_config(&encoded).is_err(), "{key}");
        }
        for key in [
            "reconciled_from_application_id",
            "reconciled_from_version",
            "reconciled_from_declared_selection_digest",
        ] {
            let mut broken = encode_config(&reconciled).unwrap();
            broken[key] = Value::Null;
            assert!(
                decode_config(&broken)
                    .unwrap_err()
                    .0
                    .contains("세 provenance"),
                "{key}"
            );
            let mut broken = encode_config(&empty).unwrap();
            broken[key] = json!(1);
            assert!(
                decode_config(&broken)
                    .unwrap_err()
                    .0
                    .contains("EMPTY origin"),
                "{key}"
            );
        }
        for value in [json!(0), json!(-1), json!(true), json!(1.5), json!("1")] {
            let mut broken = encode_config(&reconciled).unwrap();
            broken["reconciled_from_version"] = value;
            assert!(decode_config(&broken).is_err());
        }
        let encoded = encode_config(&reconciled).unwrap();
        let mut keys: Vec<_> = encoded
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            vec![
                "base_template_application_id",
                "created_at",
                "declared_selection_digest",
                "origin",
                "reconciled_from_application_id",
                "reconciled_from_declared_selection_digest",
                "reconciled_from_version",
                "selections",
                "updated_at",
                "version",
                "work_id"
            ]
        );
    }
}
