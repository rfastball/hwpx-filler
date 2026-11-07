//! Durable S4 configuration value and first-seen request ledger. Filesystem CAS lives in desktop.

use crate::text_render::python_repr;
use crate::work_slot_configuration::{
    WorkSlotConfigurationAggregate, decode_aggregate, empty_aggregate, encode_aggregate,
};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fmt;

pub const STORE_SCHEMA_VERSION: &str = "work-slot-configuration-store-v1";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredConfigurationError(pub String);
impl fmt::Display for StoredConfigurationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for StoredConfigurationError {}
fn fail(detail: impl Into<String>) -> StoredConfigurationError {
    StoredConfigurationError(detail.into())
}
fn nonempty(value: &str, label: &str) -> Result<(), StoredConfigurationError> {
    if value.is_empty() {
        Err(fail(format!("{label} 는 비어 있지 않은 문자열이어야 한다")))
    } else {
        Ok(())
    }
}
fn text(data: &Map<String, Value>, key: &str) -> Result<String, StoredConfigurationError> {
    let value = data.get(key).and_then(Value::as_str).unwrap_or("");
    nonempty(value, key)?;
    Ok(value.into())
}
fn optional_positive(
    value: Option<&Value>,
    key: &str,
) -> Result<Option<u64>, StoredConfigurationError> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(value) if !value.is_boolean() => value
            .as_u64()
            .filter(|n| *n >= 1)
            .map(Some)
            .ok_or_else(|| fail(format!("{key} 은 1 이상 정수이거나 None 이어야 한다"))),
        _ => Err(fail(format!("{key} 은 1 이상 정수이거나 None 이어야 한다"))),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TerminalOutcome {
    pub application_id: String,
    pub outcome_code: String,
    pub changed: bool,
    pub source_configuration_version: Option<u64>,
    pub resulting_configuration_version: Option<u64>,
}
impl TerminalOutcome {
    pub fn validate(&self) -> Result<(), StoredConfigurationError> {
        nonempty(&self.application_id, "application_id")?;
        nonempty(&self.outcome_code, "outcome_code")?;
        for (label, value) in [
            (
                "source_configuration_version",
                self.source_configuration_version,
            ),
            (
                "resulting_configuration_version",
                self.resulting_configuration_version,
            ),
        ] {
            if value == Some(0) {
                return Err(fail(format!(
                    "{label} 은 1 이상 정수이거나 None 이어야 한다"
                )));
            }
        }
        Ok(())
    }
    fn to_dict(&self) -> Value {
        serde_json::json!({"application_id":self.application_id,"outcome_code":self.outcome_code,
            "changed":self.changed,"source_configuration_version":self.source_configuration_version,
            "resulting_configuration_version":self.resulting_configuration_version})
    }
    fn from_dict(value: &Value) -> Result<Self, StoredConfigurationError> {
        let data = value
            .as_object()
            .ok_or_else(|| fail("terminal_outcome 표현이 malformed"))?;
        let changed = data
            .get("changed")
            .and_then(Value::as_bool)
            .ok_or_else(|| fail("changed 는 bool 이어야 한다"))?;
        let outcome = Self {
            application_id: text(data, "application_id")?,
            outcome_code: text(data, "outcome_code")?,
            changed,
            source_configuration_version: optional_positive(
                data.get("source_configuration_version"),
                "source_configuration_version",
            )?,
            resulting_configuration_version: optional_positive(
                data.get("resulting_configuration_version"),
                "resulting_configuration_version",
            )?,
        };
        outcome.validate()?;
        Ok(outcome)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IdempotencyRecord {
    pub request_id: String,
    pub fingerprint_schema_version: String,
    pub command_fingerprint: String,
    pub terminal_outcome: TerminalOutcome,
    pub request_actor_binding_digest: String,
    pub recorded_at: String,
}
impl IdempotencyRecord {
    pub fn validate(&self) -> Result<(), StoredConfigurationError> {
        for (label, value) in [
            ("request_id", &self.request_id),
            (
                "fingerprint_schema_version",
                &self.fingerprint_schema_version,
            ),
            ("command_fingerprint", &self.command_fingerprint),
            (
                "request_actor_binding_digest",
                &self.request_actor_binding_digest,
            ),
            ("recorded_at", &self.recorded_at),
        ] {
            nonempty(value, label)?;
        }
        self.terminal_outcome.validate()
    }
    fn to_dict(&self) -> Value {
        serde_json::json!({"request_id":self.request_id,"fingerprint_schema_version":self.fingerprint_schema_version,
            "command_fingerprint":self.command_fingerprint,"terminal_outcome":self.terminal_outcome.to_dict(),
            "request_actor_binding_digest":self.request_actor_binding_digest,"recorded_at":self.recorded_at})
    }
    fn from_dict(value: &Value) -> Result<Self, StoredConfigurationError> {
        let data = value
            .as_object()
            .ok_or_else(|| fail("idempotency record 표현이 malformed"))?;
        let record = Self {
            request_id: text(data, "request_id")?,
            fingerprint_schema_version: text(data, "fingerprint_schema_version")?,
            command_fingerprint: text(data, "command_fingerprint")?,
            terminal_outcome: TerminalOutcome::from_dict(
                data.get("terminal_outcome").unwrap_or(&Value::Null),
            )?,
            request_actor_binding_digest: text(data, "request_actor_binding_digest")?,
            recorded_at: text(data, "recorded_at")?,
        };
        record.validate()?;
        Ok(record)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredWorkConfiguration {
    pub schema_version: String,
    pub aggregate_version: u64,
    pub workspace_instance_id: String,
    pub configurations: WorkSlotConfigurationAggregate,
    pub processed_requests: Vec<IdempotencyRecord>,
}
impl StoredWorkConfiguration {
    pub fn validate(&self) -> Result<(), StoredConfigurationError> {
        if self.schema_version != STORE_SCHEMA_VERSION {
            return Err(fail(format!(
                "미상 store schema_version {}",
                python_repr(&Value::String(self.schema_version.clone()))
            )));
        }
        if self.aggregate_version < 1 {
            return Err(fail("aggregate_version 은 1 이상이다"));
        }
        nonempty(&self.workspace_instance_id, "workspace_instance_id")?;
        self.configurations.validate().map_err(|e| fail(e.0))?;
        let mut seen = HashSet::new();
        for record in &self.processed_requests {
            record.validate()?;
            if !seen.insert(record.request_id.as_str()) {
                return Err(fail(format!(
                    "request_id 당 record 는 최대 하나: {}",
                    record.request_id
                )));
            }
        }
        Ok(())
    }
    pub fn work_id(&self) -> &str {
        &self.configurations.work_id
    }
}

pub fn empty_stored(
    workspace_instance_id: &str,
    work_id: &str,
) -> Result<StoredWorkConfiguration, StoredConfigurationError> {
    let item = StoredWorkConfiguration {
        schema_version: STORE_SCHEMA_VERSION.into(),
        aggregate_version: 1,
        workspace_instance_id: workspace_instance_id.into(),
        configurations: empty_aggregate(work_id).map_err(|e| fail(e.0))?,
        processed_requests: Vec::new(),
    };
    item.validate()?;
    Ok(item)
}

pub fn find_request<'a>(
    stored: &'a StoredWorkConfiguration,
    request_id: &str,
) -> Option<&'a IdempotencyRecord> {
    stored
        .processed_requests
        .iter()
        .find(|record| record.request_id == request_id)
}

pub fn append_request(
    stored: &StoredWorkConfiguration,
    record: IdempotencyRecord,
) -> Result<StoredWorkConfiguration, StoredConfigurationError> {
    stored.validate()?;
    record.validate()?;
    if let Some(existing) = find_request(stored, &record.request_id) {
        if existing.fingerprint_schema_version == record.fingerprint_schema_version
            && existing.command_fingerprint == record.command_fingerprint
        {
            return Ok(stored.clone());
        }
        return Err(fail(format!(
            "request {} 가 다른 fingerprint 로 재사용됨",
            record.request_id
        )));
    }
    let mut updated = stored.clone();
    updated.processed_requests.push(record);
    updated.validate()?;
    Ok(updated)
}

pub fn encode_stored(stored: &StoredWorkConfiguration) -> Result<Value, StoredConfigurationError> {
    stored.validate()?;
    Ok(
        serde_json::json!({"schema_version":stored.schema_version,"aggregate_version":stored.aggregate_version,
        "workspace_instance_id":stored.workspace_instance_id,
        "configurations":encode_aggregate(&stored.configurations).map_err(|e| fail(e.0))?,
        "processed_requests":stored.processed_requests.iter().map(IdempotencyRecord::to_dict).collect::<Vec<_>>() }),
    )
}

pub fn decode_stored(value: &Value) -> Result<StoredWorkConfiguration, StoredConfigurationError> {
    let data = value
        .as_object()
        .ok_or_else(|| fail("stored aggregate 표현이 malformed"))?;
    let requests = data
        .get("processed_requests")
        .and_then(Value::as_array)
        .ok_or_else(|| fail("processed_requests 는 리스트여야 한다"))?;
    let configs = data
        .get("configurations")
        .filter(|v| v.is_object())
        .ok_or_else(|| fail("configurations 표현이 malformed"))?;
    let schema = data.get("schema_version").unwrap_or(&Value::Null);
    let schema = schema
        .as_str()
        .ok_or_else(|| fail(format!("미상 store schema_version {}", python_repr(schema))))?;
    let version = data
        .get("aggregate_version")
        .filter(|v| !v.is_boolean())
        .and_then(Value::as_u64)
        .ok_or_else(|| fail("aggregate_version 은 정수여야 한다"))?;
    let item = StoredWorkConfiguration {
        schema_version: schema.into(),
        aggregate_version: version,
        workspace_instance_id: text(data, "workspace_instance_id")?,
        configurations: decode_aggregate(configs).map_err(|e| fail(e.0))?,
        processed_requests: requests
            .iter()
            .map(IdempotencyRecord::from_dict)
            .collect::<Result<_, _>>()?,
    };
    item.validate()?;
    Ok(item)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::work_slot_configuration::create_empty;
    use serde_json::json;
    #[test]
    fn first_seen_request_survives_roundtrip_and_rejects_changed_fingerprint() {
        let empty = empty_stored("workspace", "work").unwrap();
        let record = IdempotencyRecord {
            request_id: "request".into(),
            fingerprint_schema_version: "v1".into(),
            command_fingerprint: "sha256:a".into(),
            terminal_outcome: TerminalOutcome {
                application_id: "app".into(),
                outcome_code: "NO_CHANGE".into(),
                changed: false,
                source_configuration_version: Some(1),
                resulting_configuration_version: Some(1),
            },
            request_actor_binding_digest: "sha256:b".into(),
            recorded_at: "now".into(),
        };
        let once = append_request(&empty, record.clone()).unwrap();
        assert_eq!(once.aggregate_version, 1);
        assert_eq!(append_request(&once, record.clone()).unwrap(), once);
        let mut conflicting = record.clone();
        conflicting.command_fingerprint = "sha256:other".into();
        assert!(append_request(&once, conflicting).is_err());
        let encoded = encode_stored(&once).unwrap();
        assert_eq!(decode_stored(&encoded).unwrap(), once);
        assert_eq!(find_request(&once, "request"), Some(&record));
        assert!(find_request(&once, "absent").is_none());
        let mut conflicting = record.clone();
        conflicting.fingerprint_schema_version = "v2".into();
        assert!(append_request(&once, conflicting).is_err());
        let mut replay = record.clone();
        replay.terminal_outcome.outcome_code = "APPLIED".into();
        replay.recorded_at = "later".into();
        assert_eq!(append_request(&once, replay).unwrap(), once);
        let mut with_config = once.clone();
        with_config
            .configurations
            .configurations
            .push(create_empty("work", "app", "now").unwrap());
        assert_eq!(
            decode_stored(&encode_stored(&with_config).unwrap()).unwrap(),
            with_config
        );
        let mut none_versions = record.terminal_outcome.clone();
        none_versions.source_configuration_version = None;
        none_versions.resulting_configuration_version = None;
        assert_eq!(
            TerminalOutcome::from_dict(&none_versions.to_dict()).unwrap(),
            none_versions
        );
        let mut duplicate = once.clone();
        duplicate.processed_requests.push(record.clone());
        assert!(duplicate.validate().is_err());
        for (pointer, value) in [
            ("", json!("not-object")),
            ("/schema_version", json!("unknown")),
            ("/aggregate_version", json!(0)),
            ("/aggregate_version", json!(true)),
            ("/aggregate_version", json!(1.5)),
            ("/workspace_instance_id", json!("")),
            ("/configurations", json!("not-object")),
            ("/processed_requests", json!("not-list")),
            ("/processed_requests/0", json!("not-record")),
            (
                "/processed_requests/0/terminal_outcome",
                json!("not-outcome"),
            ),
        ] {
            let mut broken = encoded.clone();
            *broken.pointer_mut(pointer).unwrap() = value;
            assert!(decode_stored(&broken).is_err(), "{pointer}");
        }
        for key in [
            "request_id",
            "fingerprint_schema_version",
            "command_fingerprint",
            "request_actor_binding_digest",
            "recorded_at",
        ] {
            let mut broken = encoded.clone();
            broken["processed_requests"][0][key] = json!("");
            assert!(decode_stored(&broken).is_err(), "{key}");
        }
        for (key, value) in [
            ("application_id", json!("")),
            ("outcome_code", json!("")),
            ("changed", json!("yes")),
            ("source_configuration_version", json!(0)),
            ("source_configuration_version", json!(true)),
            ("resulting_configuration_version", json!(0)),
            ("resulting_configuration_version", json!(true)),
        ] {
            let mut broken = encoded.clone();
            broken["processed_requests"][0]["terminal_outcome"][key] = value;
            assert!(decode_stored(&broken).is_err(), "{key}");
        }
    }
}
