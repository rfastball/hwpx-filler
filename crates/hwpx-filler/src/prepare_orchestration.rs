//! Pure, versioned preparation checkpoints and atomic application transitions.

use crate::qualification_evidence::{ERROR, FAIL, PASS};
use crate::text_render::python_repr;
use crate::work_template_state::*;
use serde_json::{Map, Value};

pub const APPLY_APPLIED: &str = "APPLIED";
pub const APPLY_ALREADY_APPLIED: &str = "ALREADY_APPLIED";
pub const APPLY_APPLIED_THEN_ADVANCED: &str = "APPLIED_THEN_ADVANCED";
pub const APPLY_SUPERSEDED: &str = "SUPERSEDED";
pub const APPLY_CONFLICT: &str = "CONFLICT";
pub const APPLY_REJECTED: &str = "REJECTED";
pub const APPLY_INTEGRITY_ERROR: &str = "INTEGRITY_ERROR";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DerivedStageIds {
    pub observation_id: String,
    pub revision_id: String,
    pub attempt_id: String,
    pub evidence_id: String,
}
pub fn derive_stage_ids(work_id: &str, preparation_id: &str) -> DerivedStageIds {
    let prefix = format!("{work_id}.{preparation_id}");
    DerivedStageIds {
        observation_id: format!("{prefix}.obs"),
        revision_id: format!("{prefix}.rev"),
        attempt_id: format!("{prefix}.att"),
        evidence_id: format!("{prefix}.ev"),
    }
}
fn fail(detail: impl Into<String>) -> WorkTemplateStateError {
    WorkTemplateStateError(detail.into())
}
pub fn find_preparation<'a>(
    aggregate: &'a WorkTemplateStateAggregate,
    id: &str,
) -> Result<&'a TemplateChangePreparation, WorkTemplateStateError> {
    aggregate
        .preparations
        .iter()
        .find(|item| item.preparation_id == id)
        .ok_or_else(|| fail(format!("preparation {id} 없음")))
}
pub fn find_application<'a>(
    aggregate: &'a WorkTemplateStateAggregate,
    id: &str,
) -> Result<&'a WorkTemplateApplication, WorkTemplateStateError> {
    aggregate
        .applications
        .iter()
        .find(|item| item.application_id == id)
        .ok_or_else(|| fail(format!("application {id} 없음")))
}
pub fn find_change<'a>(
    aggregate: &'a WorkTemplateStateAggregate,
    id: &str,
) -> Result<&'a PreparedTemplateChange, WorkTemplateStateError> {
    aggregate
        .prepared_changes
        .iter()
        .find(|item| item.prepared_change_id == id)
        .ok_or_else(|| fail(format!("prepared change {id} 없음")))
}
pub fn in_flight_preparations<'a>(
    aggregate: &'a WorkTemplateStateAggregate,
    session: &str,
) -> Vec<&'a TemplateChangePreparation> {
    aggregate
        .preparations
        .iter()
        .filter(|item| {
            [PREP_CAPTURING, PREP_QUALIFYING].contains(&item.status.as_str())
                && item.execution_session_id != session
        })
        .collect()
}
fn update_preparation(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    change: impl FnOnce(&mut TemplateChangePreparation),
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    let mut out = aggregate.clone();
    let prep = out
        .preparations
        .iter_mut()
        .find(|item| item.preparation_id == id)
        .ok_or_else(|| fail(format!("preparation {id} 없음")))?;
    change(prep);
    out.aggregate_version += 1;
    out.validate()?;
    Ok(out)
}
pub struct CaptureCheckpoint<'a> {
    pub observation_id: &'a str,
    pub revision_id: &'a str,
    pub capture_failed: bool,
    pub capture_error_reason: Option<&'a str>,
    pub binding_changed: bool,
    pub completed_at: &'a str,
}
pub fn plan_capture_checkpoint(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    checkpoint: CaptureCheckpoint<'_>,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    let CaptureCheckpoint {
        observation_id,
        revision_id,
        capture_failed,
        capture_error_reason,
        binding_changed,
        completed_at,
    } = checkpoint;
    if find_preparation(aggregate, id)?.status != PREP_CAPTURING {
        return Ok(aggregate.clone());
    }
    update_preparation(aggregate, id, |prep| {
        if binding_changed {
            prep.status = PREP_SOURCE_BINDING_CHANGED.into();
            prep.completed_at = Some(completed_at.into());
        } else if capture_failed {
            prep.status = PREP_CAPTURE_ERROR.into();
            prep.completed_at = Some(completed_at.into());
            let mut diagnostic = Map::new();
            diagnostic.insert("stage".into(), Value::String("capture".into()));
            diagnostic.insert(
                "reason".into(),
                Value::String(
                    capture_error_reason
                        .filter(|s| !s.is_empty())
                        .unwrap_or("UNKNOWN")
                        .into(),
                ),
            );
            prep.diagnostics = vec![diagnostic];
        } else {
            prep.observation_id = Some(observation_id.into());
            prep.revision_id = Some(revision_id.into());
            prep.status = PREP_QUALIFYING.into();
        }
    })
}
fn attempt_outcome(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    outcome: &str,
    attempt_id: &str,
    evidence_id: Option<&str>,
    completed_at: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    if ![PASS, FAIL, ERROR].contains(&outcome) {
        return Err(fail(format!(
            "미상 attempt outcome {}",
            python_repr(&Value::String(outcome.into()))
        )));
    }
    update_preparation(aggregate, id, |prep| {
        prep.attempt_id = Some(attempt_id.into());
        match outcome {
            PASS => {
                prep.evidence_id = evidence_id.map(str::to_owned);
                prep.status = PREP_QUALIFYING.into();
            }
            FAIL => {
                prep.evidence_id = evidence_id.map(str::to_owned);
                prep.status = PREP_QUALIFICATION_FAILED.into();
                prep.completed_at = Some(completed_at.into());
            }
            ERROR => {
                prep.status = PREP_QUALIFICATION_ERROR.into();
                prep.completed_at = Some(completed_at.into());
            }
            _ => unreachable!(),
        }
    })
}
pub fn plan_qualification_checkpoint(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    outcome: &str,
    attempt_id: &str,
    evidence_id: Option<&str>,
    completed_at: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    if find_preparation(aggregate, id)?.status != PREP_QUALIFYING {
        return Ok(aggregate.clone());
    }
    attempt_outcome(
        aggregate,
        id,
        outcome,
        attempt_id,
        evidence_id,
        completed_at,
    )
}
pub fn plan_recovery(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    attempt_outcome_value: Option<&str>,
    attempt_id: Option<&str>,
    evidence_id: Option<&str>,
    completed_at: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    if ![PREP_CAPTURING, PREP_QUALIFYING]
        .contains(&find_preparation(aggregate, id)?.status.as_str())
    {
        return Ok(aggregate.clone());
    }
    let Some(outcome) = attempt_outcome_value else {
        return update_preparation(aggregate, id, |prep| {
            prep.status = PREP_INTERRUPTED.into();
            prep.completed_at = Some(completed_at.into());
        });
    };
    let attempt_id = attempt_id.ok_or_else(|| fail("attempt outcome 에 attempt_id 부재"))?;
    attempt_outcome(
        aggregate,
        id,
        outcome,
        attempt_id,
        evidence_id,
        completed_at,
    )
}
pub fn plan_admission_terminal(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    status: &str,
    completed_at: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    update_preparation(aggregate, id, |prep| {
        prep.status = status.into();
        prep.completed_at = Some(completed_at.into());
    })
}
pub fn plan_admission_ready(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    change_id: &str,
    evidence_id: &str,
    prepared_at: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    let prep = find_preparation(aggregate, id)?;
    let change = PreparedTemplateChange {
        prepared_change_id: change_id.into(),
        preparation_id: id.into(),
        work_id: prep.work_id.clone(),
        base_application_id: aggregate.work.current_template_application_id.clone(),
        target_pass_evidence_id: evidence_id.into(),
        status: CHANGE_PREPARED.into(),
        prepared_at: prepared_at.into(),
        resulting_application_id: None,
        applied_at: None,
    };
    let mut out = aggregate.clone();
    let target = out
        .preparations
        .iter_mut()
        .find(|item| item.preparation_id == id)
        .expect("found above");
    target.status = PREP_READY.into();
    target.prepared_change_id = Some(change_id.into());
    target.completed_at = Some(prepared_at.into());
    out.prepared_changes.push(change);
    out.aggregate_version += 1;
    out.validate()?;
    Ok(out)
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ApplyOutcome {
    pub result: String,
    pub resulting_application_id: Option<String>,
}
pub fn plan_change_status(
    aggregate: &WorkTemplateStateAggregate,
    id: &str,
    status: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    let mut out = aggregate.clone();
    if let Some(change) = out
        .prepared_changes
        .iter_mut()
        .find(|item| item.prepared_change_id == id)
    {
        change.status = status.into();
    }
    out.aggregate_version += 1;
    out.validate()?;
    Ok(out)
}
pub fn plan_apply(
    aggregate: &WorkTemplateStateAggregate,
    change: &PreparedTemplateChange,
    new_application_id: &str,
    actor: &str,
    applied_at: &str,
) -> Result<WorkTemplateStateAggregate, WorkTemplateStateError> {
    let current = find_application(aggregate, &aggregate.work.current_template_application_id)?;
    let application = WorkTemplateApplication {
        application_id: new_application_id.into(),
        work_id: change.work_id.clone(),
        application_epoch: current.application_epoch + 1,
        pass_evidence_id: change.target_pass_evidence_id.clone(),
        previous_application_id: Some(current.application_id.clone()),
        origin: PREPARED_CHANGE.into(),
        prepared_change_id: Some(change.prepared_change_id.clone()),
        actor: actor.into(),
        applied_at: applied_at.into(),
    };
    let mut out = aggregate.clone();
    if let Some(target) = out
        .prepared_changes
        .iter_mut()
        .find(|item| item.prepared_change_id == change.prepared_change_id)
    {
        target.status = CHANGE_APPLIED.into();
        target.resulting_application_id = Some(new_application_id.into());
        target.applied_at = Some(applied_at.into());
    }
    out.applications.push(application);
    out.work.current_template_application_id = new_application_id.into();
    out.aggregate_version += 1;
    out.validate()?;
    Ok(out)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn capture_checkpoint_is_once_and_recovery_does_not_recapture() {
        let aggregate = WorkTemplateStateAggregate {
            schema_version: SCHEMA_VERSION.into(),
            aggregate_version: 1,
            work: DocumentWork {
                work_id: "w".into(),
                template_lineage_id: "line".into(),
                current_template_application_id: "a1".into(),
                current_template_preparation_id: Some("p1".into()),
                prepare_seq: 1,
            },
            applications: vec![WorkTemplateApplication {
                application_id: "a1".into(),
                work_id: "w".into(),
                application_epoch: 1,
                pass_evidence_id: "e".into(),
                previous_application_id: None,
                origin: INITIALIZATION.into(),
                prepared_change_id: None,
                actor: "local".into(),
                applied_at: "t0".into(),
            }],
            preparations: vec![TemplateChangePreparation {
                preparation_id: "p1".into(),
                work_id: "w".into(),
                prepare_request_id: "req".into(),
                prepare_seq: 1,
                base_application_id: "a1".into(),
                source_binding_id: "b".into(),
                source_binding_generation: 1,
                qualification_profile_id: "q".into(),
                execution_session_id: "old".into(),
                status: PREP_CAPTURING.into(),
                started_at: "t1".into(),
                observation_id: None,
                revision_id: None,
                attempt_id: None,
                evidence_id: None,
                prepared_change_id: None,
                diagnostics: Vec::new(),
                completed_at: None,
            }],
            prepared_changes: Vec::new(),
        };
        aggregate.validate().unwrap();
        let ids = derive_stage_ids("w", "p1");
        assert_eq!(ids.revision_id, "w.p1.rev");
        let other = derive_stage_ids("other", "p1");
        assert_ne!(ids.revision_id, other.revision_id);
        assert_ne!(ids.attempt_id, other.attempt_id);
        assert!(in_flight_preparations(&aggregate, "old").is_empty());
        assert_eq!(in_flight_preparations(&aggregate, "new").len(), 1);
        assert!(
            find_preparation(&aggregate, "ghost")
                .unwrap_err()
                .0
                .contains("preparation ghost 없음")
        );
        assert_eq!(
            plan_qualification_checkpoint(
                &aggregate,
                "p1",
                PASS,
                &ids.attempt_id,
                Some(&ids.evidence_id),
                "t3"
            )
            .unwrap(),
            aggregate
        );
        for failed in [false, true] {
            let changed = plan_capture_checkpoint(
                &aggregate,
                "p1",
                CaptureCheckpoint {
                    observation_id: &ids.observation_id,
                    revision_id: &ids.revision_id,
                    capture_failed: failed,
                    capture_error_reason: Some("SOURCE_GONE"),
                    binding_changed: true,
                    completed_at: "t2",
                },
            )
            .unwrap();
            assert_eq!(changed.preparations[0].status, PREP_SOURCE_BINDING_CHANGED);
        }
        let advanced = plan_capture_checkpoint(
            &aggregate,
            "p1",
            CaptureCheckpoint {
                observation_id: &ids.observation_id,
                revision_id: &ids.revision_id,
                capture_failed: false,
                capture_error_reason: None,
                binding_changed: false,
                completed_at: "t2",
            },
        )
        .unwrap();
        assert_eq!(advanced.aggregate_version, 2);
        assert_eq!(
            find_preparation(&advanced, "p1").unwrap().status,
            PREP_QUALIFYING
        );
        for (outcome, status) in [
            (PASS, PREP_QUALIFYING),
            (FAIL, PREP_QUALIFICATION_FAILED),
            (ERROR, PREP_QUALIFICATION_ERROR),
        ] {
            let evidence = if outcome == ERROR {
                None
            } else {
                Some(ids.evidence_id.as_str())
            };
            let next = plan_qualification_checkpoint(
                &advanced,
                "p1",
                outcome,
                &ids.attempt_id,
                evidence,
                "t3",
            )
            .unwrap();
            assert_eq!(next.preparations[0].status, status);
            assert_eq!(
                next.preparations[0].attempt_id.as_deref(),
                Some(ids.attempt_id.as_str())
            );
            assert_eq!(next.preparations[0].evidence_id.as_deref(), evidence);
        }
        assert_eq!(
            plan_capture_checkpoint(
                &advanced,
                "p1",
                CaptureCheckpoint {
                    observation_id: "other",
                    revision_id: "other",
                    capture_failed: true,
                    capture_error_reason: None,
                    binding_changed: false,
                    completed_at: "t3"
                }
            )
            .unwrap(),
            advanced
        );
        let interrupted = plan_recovery(&advanced, "p1", None, None, None, "t4").unwrap();
        assert_eq!(
            find_preparation(&interrupted, "p1").unwrap().status,
            PREP_INTERRUPTED
        );
        assert_eq!(
            plan_recovery(
                &interrupted,
                "p1",
                Some(PASS),
                Some(&ids.attempt_id),
                Some(&ids.evidence_id),
                "t5"
            )
            .unwrap(),
            interrupted
        );
    }
}
