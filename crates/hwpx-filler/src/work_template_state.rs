//! Per-Work template application history, preparation state and durable v2 codec.

use crate::text_render::python_repr;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const SCHEMA_VERSION: &str = "work-template-state-v2";
pub const INITIALIZATION: &str = "INITIALIZATION";
pub const PREPARED_CHANGE: &str = "PREPARED_CHANGE";
pub const PREP_CAPTURING: &str = "CAPTURING";
pub const PREP_QUALIFYING: &str = "QUALIFYING";
pub const PREP_READY: &str = "READY";
pub const PREP_SUPERSEDED: &str = "SUPERSEDED";
pub const PREP_APPLIED: &str = "APPLIED";
pub const PREP_CONFLICTED: &str = "CONFLICTED";
pub const PREP_REJECTED: &str = "REJECTED";
pub const PREP_CAPTURE_ERROR: &str = "CAPTURE_ERROR";
pub const PREP_SOURCE_BINDING_CHANGED: &str = "SOURCE_BINDING_CHANGED";
pub const PREP_QUALIFICATION_FAILED: &str = "QUALIFICATION_FAILED";
pub const PREP_QUALIFICATION_ERROR: &str = "QUALIFICATION_ERROR";
pub const PREP_INTERRUPTED: &str = "INTERRUPTED";
pub const PREP_BASE_CHANGED: &str = "BASE_CHANGED";
pub const PREP_PROFILE_REVOKED: &str = "PROFILE_REVOKED";
pub const PREP_NO_CHANGE: &str = "NO_CHANGE";
pub const CHANGE_PREPARED: &str = "PREPARED";
pub const CHANGE_SUPERSEDED: &str = "SUPERSEDED";
pub const CHANGE_APPLIED: &str = "APPLIED";
pub const CHANGE_CONFLICTED: &str = "CONFLICTED";
pub const CHANGE_REJECTED: &str = "REJECTED";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkTemplateStateError(pub String);
impl fmt::Display for WorkTemplateStateError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for WorkTemplateStateError {}
fn fail(detail: impl Into<String>) -> WorkTemplateStateError {
    WorkTemplateStateError(detail.into())
}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentWork {
    pub work_id: String,
    pub template_lineage_id: String,
    pub current_template_application_id: String,
    pub current_template_preparation_id: Option<String>,
    pub prepare_seq: i64,
}
impl DocumentWork {
    pub fn validate(&self) -> Result<(), WorkTemplateStateError> {
        if self.prepare_seq < 0 {
            Err(fail("prepare_seq 는 음수일 수 없다"))
        } else {
            Ok(())
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkTemplateApplication {
    pub application_id: String,
    pub work_id: String,
    pub application_epoch: i64,
    pub pass_evidence_id: String,
    pub previous_application_id: Option<String>,
    pub origin: String,
    pub prepared_change_id: Option<String>,
    pub actor: String,
    pub applied_at: String,
}
impl WorkTemplateApplication {
    pub fn validate(&self) -> Result<(), WorkTemplateStateError> {
        if self.origin != INITIALIZATION && self.origin != PREPARED_CHANGE {
            return Err(fail(format!("미상 origin {}", repr(&self.origin))));
        }
        if self.application_epoch < 1 {
            return Err(fail("application_epoch 는 1 이상이다"));
        }
        if self.origin == INITIALIZATION {
            if self.previous_application_id.is_some() {
                return Err(fail("INITIALIZATION 은 previous 가 없어야 한다"));
            }
            if self.prepared_change_id.is_some() {
                return Err(fail("INITIALIZATION 은 prepared_change_id 를 갖지 않는다"));
            }
        } else {
            if self.prepared_change_id.is_none() {
                return Err(fail("PREPARED_CHANGE 는 prepared_change_id 가 필수다"));
            }
            if self.previous_application_id.is_none() {
                return Err(fail("PREPARED_CHANGE 는 previous 가 필수다"));
            }
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TemplateChangePreparation {
    pub preparation_id: String,
    pub work_id: String,
    pub prepare_request_id: String,
    pub prepare_seq: i64,
    pub base_application_id: String,
    pub source_binding_id: String,
    pub source_binding_generation: i64,
    pub qualification_profile_id: String,
    pub execution_session_id: String,
    pub status: String,
    pub started_at: String,
    pub observation_id: Option<String>,
    pub revision_id: Option<String>,
    pub attempt_id: Option<String>,
    pub evidence_id: Option<String>,
    pub prepared_change_id: Option<String>,
    pub diagnostics: Vec<Map<String, Value>>,
    pub completed_at: Option<String>,
}
impl TemplateChangePreparation {
    pub fn validate(&self) -> Result<(), WorkTemplateStateError> {
        let states = [
            PREP_CAPTURING,
            PREP_QUALIFYING,
            PREP_READY,
            PREP_SUPERSEDED,
            PREP_APPLIED,
            PREP_CONFLICTED,
            PREP_REJECTED,
            PREP_CAPTURE_ERROR,
            PREP_SOURCE_BINDING_CHANGED,
            PREP_QUALIFICATION_FAILED,
            PREP_QUALIFICATION_ERROR,
            PREP_INTERRUPTED,
            PREP_BASE_CHANGED,
            PREP_PROFILE_REVOKED,
            PREP_NO_CHANGE,
        ];
        if !states.contains(&self.status.as_str()) {
            return Err(fail(format!(
                "미상 preparation status {}",
                repr(&self.status)
            )));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PreparedTemplateChange {
    pub prepared_change_id: String,
    pub preparation_id: String,
    pub work_id: String,
    pub base_application_id: String,
    pub target_pass_evidence_id: String,
    pub status: String,
    pub prepared_at: String,
    pub resulting_application_id: Option<String>,
    pub applied_at: Option<String>,
}
impl PreparedTemplateChange {
    pub fn validate(&self) -> Result<(), WorkTemplateStateError> {
        if ![
            CHANGE_PREPARED,
            CHANGE_SUPERSEDED,
            CHANGE_APPLIED,
            CHANGE_CONFLICTED,
            CHANGE_REJECTED,
        ]
        .contains(&self.status.as_str())
        {
            return Err(fail(format!(
                "미상 prepared change status {}",
                repr(&self.status)
            )));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkTemplateStateAggregate {
    pub schema_version: String,
    pub aggregate_version: i64,
    pub work: DocumentWork,
    pub applications: Vec<WorkTemplateApplication>,
    pub preparations: Vec<TemplateChangePreparation>,
    pub prepared_changes: Vec<PreparedTemplateChange>,
}
impl WorkTemplateStateAggregate {
    pub fn validate(&self) -> Result<(), WorkTemplateStateError> {
        if self.schema_version != SCHEMA_VERSION {
            return Err(fail(format!(
                "미지원 schema_version {}",
                repr(&self.schema_version)
            )));
        }
        if self.aggregate_version < 1 {
            return Err(fail("aggregate_version 은 1 이상이다"));
        }
        self.work.validate()?;
        let index = self.application_index()?;
        self.validate_application_chain(&index)?;
        self.validate_preparation_ownership()?;
        self.validate_preparation_references()
    }

    fn application_index(&self) -> Result<HashMap<&str, i64>, WorkTemplateStateError> {
        let work_id = &self.work.work_id;
        let mut epochs = HashSet::new();
        let mut epoch_by_id = HashMap::new();
        let mut prepared_used = HashSet::new();
        for app in &self.applications {
            app.validate()?;
            if app.work_id != *work_id {
                return Err(fail(format!(
                    "application {} 가 다른 Work 에 속한다",
                    app.application_id
                )));
            }
            if epoch_by_id
                .insert(app.application_id.as_str(), app.application_epoch)
                .is_some()
            {
                return Err(fail(format!("application_id 중복 {}", app.application_id)));
            }
            if !epochs.insert(app.application_epoch) {
                return Err(fail(format!(
                    "application_epoch 중복 {}",
                    app.application_epoch
                )));
            }
            if let Some(id) = &app.prepared_change_id
                && !prepared_used.insert(id.as_str())
            {
                return Err(fail(format!("prepared_change_id {id} 에 Application 2개")));
            }
        }
        Ok(epoch_by_id)
    }

    fn validate_application_chain(
        &self,
        epoch_by_id: &HashMap<&str, i64>,
    ) -> Result<(), WorkTemplateStateError> {
        let Some(&current_epoch) =
            epoch_by_id.get(self.work.current_template_application_id.as_str())
        else {
            return Err(fail(
                "current pointer 가 dangling(존재하지 않는 Application)",
            ));
        };
        if epoch_by_id.values().max().copied() != Some(current_epoch) {
            return Err(fail(
                "current pointer 가 최신 Application(최고 epoch)이 아니다",
            ));
        }
        for app in &self.applications {
            if let Some(previous) = &app.previous_application_id
                && !epoch_by_id.contains_key(previous.as_str())
            {
                return Err(fail(format!("previous {previous} 가 dangling")));
            }
        }
        Ok(())
    }

    fn validate_preparation_ownership(&self) -> Result<(), WorkTemplateStateError> {
        let work_id = &self.work.work_id;
        for prep in &self.preparations {
            prep.validate()?;
            if prep.work_id != *work_id {
                return Err(fail("preparation/change 가 다른 Work 에 속한다"));
            }
        }
        for change in &self.prepared_changes {
            change.validate()?;
            if change.work_id != *work_id {
                return Err(fail("preparation/change 가 다른 Work 에 속한다"));
            }
        }
        Ok(())
    }

    fn validate_preparation_references(&self) -> Result<(), WorkTemplateStateError> {
        let mut prep_ids = HashSet::new();
        for prep in &self.preparations {
            if !prep_ids.insert(prep.preparation_id.as_str()) {
                return Err(fail(format!("preparation_id 중복 {}", prep.preparation_id)));
            }
        }
        let mut change_ids = HashSet::new();
        for change in &self.prepared_changes {
            if !change_ids.insert(change.prepared_change_id.as_str()) {
                return Err(fail(format!(
                    "prepared_change_id 중복 {}",
                    change.prepared_change_id
                )));
            }
        }
        if self
            .work
            .current_template_preparation_id
            .as_ref()
            .is_some_and(|id| !prep_ids.contains(id.as_str()))
        {
            return Err(fail("current preparation pointer 가 dangling"));
        }
        Ok(())
    }
}
pub fn encode_aggregate(
    aggregate: &WorkTemplateStateAggregate,
) -> Result<Value, WorkTemplateStateError> {
    aggregate.validate()?;
    serde_json::to_value(aggregate).map_err(|error| fail(error.to_string()))
}
fn require_keys(value: &Value, keys: &[&str]) -> Result<(), WorkTemplateStateError> {
    let data = value
        .as_object()
        .ok_or_else(|| fail("Work Template 저장 표현이 사전이 아니다"))?;
    for key in keys {
        if !data.contains_key(*key) {
            return Err(fail(format!("{key} 누락")));
        }
    }
    Ok(())
}
pub fn decode_aggregate(
    value: &Value,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    require_keys(
        value,
        &[
            "schema_version",
            "aggregate_version",
            "work",
            "applications",
            "preparations",
            "prepared_changes",
        ],
    )?;
    require_keys(
        &value["work"],
        &[
            "work_id",
            "template_lineage_id",
            "current_template_application_id",
            "current_template_preparation_id",
            "prepare_seq",
        ],
    )?;
    for app in value["applications"]
        .as_array()
        .ok_or_else(|| fail("applications 는 목록이어야 한다"))?
    {
        require_keys(
            app,
            &[
                "application_id",
                "work_id",
                "application_epoch",
                "pass_evidence_id",
                "previous_application_id",
                "origin",
                "prepared_change_id",
                "actor",
                "applied_at",
            ],
        )?;
        // Python's application invariant checks origin and forbidden references before
        // serializing their value types. Preserve those explicit refusal categories.
        let origin = &app["origin"];
        if origin != INITIALIZATION && origin != PREPARED_CHANGE {
            return Err(fail(format!("미상 origin {}", python_repr(origin))));
        }
        if origin == INITIALIZATION {
            if !app["previous_application_id"].is_null() {
                return Err(fail("INITIALIZATION 은 previous 가 없어야 한다"));
            }
            if !app["prepared_change_id"].is_null() {
                return Err(fail("INITIALIZATION 은 prepared_change_id 를 갖지 않는다"));
            }
        }
    }
    for prep in value["preparations"]
        .as_array()
        .ok_or_else(|| fail("preparations 는 목록이어야 한다"))?
    {
        require_keys(
            prep,
            &[
                "preparation_id",
                "work_id",
                "prepare_request_id",
                "prepare_seq",
                "base_application_id",
                "source_binding_id",
                "source_binding_generation",
                "qualification_profile_id",
                "execution_session_id",
                "status",
                "started_at",
                "observation_id",
                "revision_id",
                "attempt_id",
                "evidence_id",
                "prepared_change_id",
                "diagnostics",
                "completed_at",
            ],
        )?;
    }
    for change in value["prepared_changes"]
        .as_array()
        .ok_or_else(|| fail("prepared_changes 는 목록이어야 한다"))?
    {
        require_keys(
            change,
            &[
                "prepared_change_id",
                "preparation_id",
                "work_id",
                "base_application_id",
                "target_pass_evidence_id",
                "status",
                "prepared_at",
                "resulting_application_id",
                "applied_at",
            ],
        )?;
    }
    let aggregate: WorkTemplateStateAggregate =
        serde_json::from_value(value.clone()).map_err(|error| fail(error.to_string()))?;
    aggregate.validate()?;
    Ok(aggregate)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn current_is_highest_epoch_and_durable_codec_rejects_stale_pointer() {
        let application = WorkTemplateApplication {
            application_id: "a1".into(),
            work_id: "w".into(),
            application_epoch: 1,
            pass_evidence_id: "e".into(),
            previous_application_id: None,
            origin: INITIALIZATION.into(),
            prepared_change_id: None,
            actor: "actor".into(),
            applied_at: "t".into(),
        };
        let aggregate = WorkTemplateStateAggregate {
            schema_version: SCHEMA_VERSION.into(),
            aggregate_version: 1,
            work: DocumentWork {
                work_id: "w".into(),
                template_lineage_id: "line".into(),
                current_template_application_id: "a1".into(),
                current_template_preparation_id: None,
                prepare_seq: 0,
            },
            applications: vec![application],
            preparations: vec![],
            prepared_changes: vec![],
        };
        assert_eq!(
            decode_aggregate(&encode_aggregate(&aggregate).unwrap()).unwrap(),
            aggregate
        );
        let mut corrupt = aggregate.clone();
        corrupt.work.current_template_application_id = "absent".into();
        assert!(corrupt.validate().unwrap_err().0.contains("dangling"));
        let mut encoded = encode_aggregate(&aggregate).unwrap();
        encoded["work"]
            .as_object_mut()
            .unwrap()
            .remove("current_template_preparation_id");
        assert!(decode_aggregate(&encoded).is_err());
        let mut encoded = encode_aggregate(&aggregate).unwrap();
        encoded["applications"][0]["origin"] = serde_json::json!(0);
        assert_eq!(decode_aggregate(&encoded).unwrap_err().0, "미상 origin 0");
        encoded["applications"][0]["origin"] = serde_json::json!(INITIALIZATION);
        encoded["applications"][0]["previous_application_id"] = serde_json::json!(2);
        assert_eq!(
            decode_aggregate(&encoded).unwrap_err().0,
            "INITIALIZATION 은 previous 가 없어야 한다"
        );
        let mut full = encode_aggregate(&aggregate).unwrap();
        full["work"]["current_template_preparation_id"] = serde_json::json!("p1");
        full["preparations"] = serde_json::json!([{
            "preparation_id":"p1", "work_id":"w", "prepare_request_id":"request", "prepare_seq":1,
            "base_application_id":"a1", "source_binding_id":"binding", "source_binding_generation":1,
            "qualification_profile_id":"profile", "execution_session_id":"session", "status":"CAPTURING",
            "started_at":"t1", "observation_id":null, "revision_id":null, "attempt_id":null,
            "evidence_id":null, "prepared_change_id":null, "diagnostics":[], "completed_at":null
        }]);
        full["prepared_changes"] = serde_json::json!([{
            "prepared_change_id":"c1", "preparation_id":"p1", "work_id":"w", "base_application_id":"a1",
            "target_pass_evidence_id":"e", "status":"PREPARED", "prepared_at":"t1",
            "resulting_application_id":null, "applied_at":null
        }]);
        assert_eq!(
            encode_aggregate(&decode_aggregate(&full).unwrap()).unwrap(),
            full
        );
        for (pointer, value, reason) in [
            (
                "/schema_version",
                serde_json::json!("work-template-state-v1"),
                "schema_version",
            ),
            (
                "/schema_version",
                serde_json::json!("bogus"),
                "schema_version",
            ),
            (
                "/aggregate_version",
                serde_json::json!(0),
                "aggregate_version",
            ),
            ("/work/prepare_seq", serde_json::json!(-1), "prepare_seq"),
            (
                "/work/current_template_preparation_id",
                serde_json::json!("absent"),
                "current preparation pointer",
            ),
            (
                "/applications/0/application_epoch",
                serde_json::json!(0),
                "epoch",
            ),
            (
                "/applications/0/origin",
                serde_json::json!("unknown"),
                "미상 origin",
            ),
            (
                "/applications/0/prepared_change_id",
                serde_json::json!("c1"),
                "INITIALIZATION",
            ),
            (
                "/applications/0/work_id",
                serde_json::json!("other"),
                "다른 Work",
            ),
            (
                "/preparations/0/work_id",
                serde_json::json!("other"),
                "다른 Work",
            ),
            (
                "/prepared_changes/0/work_id",
                serde_json::json!("other"),
                "다른 Work",
            ),
            (
                "/preparations/0/status",
                serde_json::json!("unknown"),
                "preparation status",
            ),
            (
                "/prepared_changes/0/status",
                serde_json::json!("unknown"),
                "prepared change status",
            ),
        ] {
            let mut invalid = full.clone();
            *invalid.pointer_mut(pointer).unwrap() = value;
            assert!(
                decode_aggregate(&invalid).unwrap_err().0.contains(reason),
                "{pointer}"
            );
        }
        for (key, reason) in [
            ("applications", "application_id 중복"),
            ("preparations", "preparation_id 중복"),
            ("prepared_changes", "prepared_change_id 중복"),
        ] {
            let mut invalid = full.clone();
            let item = invalid[key][0].clone();
            invalid[key].as_array_mut().unwrap().push(item);
            assert!(
                decode_aggregate(&invalid).unwrap_err().0.contains(reason),
                "{key}"
            );
        }
        for parent in [
            "",
            "/work",
            "/applications/0",
            "/preparations/0",
            "/prepared_changes/0",
        ] {
            for key in full.pointer(parent).unwrap().as_object().unwrap().keys() {
                let mut missing = full.clone();
                missing
                    .pointer_mut(parent)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .remove(key);
                assert!(
                    decode_aggregate(&missing).unwrap_err().0.contains("누락"),
                    "{parent}/{key}"
                );
            }
        }
        let mut history = aggregate.clone();
        for (id, epoch, previous, change, evidence) in [
            ("a2", 2, "a1", "c1", "other-evidence"),
            ("a3", 3, "a2", "c2", "e"),
        ] {
            let mut application = history.applications[0].clone();
            application.application_id = id.into();
            application.application_epoch = epoch;
            application.previous_application_id = Some(previous.into());
            application.prepared_change_id = Some(change.into());
            application.origin = PREPARED_CHANGE.into();
            application.pass_evidence_id = evidence.into();
            history.applications.push(application);
            history.work.current_template_application_id = id.into();
        }
        assert_eq!(
            decode_aggregate(&encode_aggregate(&history).unwrap()).unwrap(),
            history
        );
        for (case, reason) in [
            ("epoch", "epoch 중복"),
            ("change", "Application 2개"),
            ("previous", "dangling"),
            ("current", "최고 epoch"),
            ("missing_change", "prepared_change_id"),
            ("missing_previous", "previous"),
        ] {
            let mut invalid = history.clone();
            match case {
                "epoch" => invalid.applications[2].application_epoch = 2,
                "change" => invalid.applications[2].prepared_change_id = Some("c1".into()),
                "previous" => {
                    invalid.applications[2].previous_application_id = Some("absent".into())
                }
                "current" => invalid.work.current_template_application_id = "a1".into(),
                "missing_change" => invalid.applications[2].prepared_change_id = None,
                _ => invalid.applications[2].previous_application_id = None,
            }
            assert!(invalid.validate().unwrap_err().0.contains(reason), "{case}");
        }
    }
}
