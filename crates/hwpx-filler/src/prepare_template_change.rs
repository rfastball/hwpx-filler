//! Idempotent prepare intent with server-side pins and latest-intent supersession.

use crate::work_template_state::*;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PreparePins {
    pub source_binding_id: String,
    pub source_binding_generation: i64,
    pub qualification_profile_id: String,
}
pub struct PrepareIntent<'a> {
    pub prepare_request_id: &'a str,
    pub pins: &'a PreparePins,
    pub preparation_id: &'a str,
    pub execution_session_id: &'a str,
    pub started_at: &'a str,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PreparePlan {
    pub aggregate: WorkTemplateStateAggregate,
    pub preparation: TemplateChangePreparation,
}
pub fn find_preparation_by_request<'a>(
    aggregate: &'a WorkTemplateStateAggregate,
    request_id: &str,
) -> Option<&'a TemplateChangePreparation> {
    aggregate
        .preparations
        .iter()
        .find(|prep| prep.prepare_request_id == request_id)
}
pub fn plan_prepare(
    aggregate: &WorkTemplateStateAggregate,
    intent: PrepareIntent<'_>,
) -> Result<PreparePlan, WorkTemplateStateError> {
    if let Some(existing) = find_preparation_by_request(aggregate, intent.prepare_request_id) {
        return Ok(PreparePlan {
            aggregate: aggregate.clone(),
            preparation: existing.clone(),
        });
    }
    let mut out = aggregate.clone();
    let prior = out.work.current_template_preparation_id.clone();
    if let Some(prior) = prior {
        let mut superseded_change_ids = Vec::new();
        for prep in &mut out.preparations {
            if prep.preparation_id == prior
                && [PREP_CAPTURING, PREP_QUALIFYING, PREP_READY].contains(&prep.status.as_str())
            {
                prep.status = PREP_SUPERSEDED.into();
                if let Some(id) = &prep.prepared_change_id {
                    superseded_change_ids.push(id.clone());
                }
            }
        }
        for change in &mut out.prepared_changes {
            if change.status == CHANGE_PREPARED
                && superseded_change_ids.contains(&change.prepared_change_id)
            {
                change.status = CHANGE_SUPERSEDED.into();
            }
        }
    }
    let sequence = out
        .work
        .prepare_seq
        .checked_add(1)
        .ok_or_else(|| WorkTemplateStateError("prepare_seq 범위 초과".into()))?;
    let prep = TemplateChangePreparation {
        preparation_id: intent.preparation_id.into(),
        work_id: out.work.work_id.clone(),
        prepare_request_id: intent.prepare_request_id.into(),
        prepare_seq: sequence,
        base_application_id: out.work.current_template_application_id.clone(),
        source_binding_id: intent.pins.source_binding_id.clone(),
        source_binding_generation: intent.pins.source_binding_generation,
        qualification_profile_id: intent.pins.qualification_profile_id.clone(),
        execution_session_id: intent.execution_session_id.into(),
        status: PREP_CAPTURING.into(),
        started_at: intent.started_at.into(),
        observation_id: None,
        revision_id: None,
        attempt_id: None,
        evidence_id: None,
        prepared_change_id: None,
        diagnostics: Vec::new(),
        completed_at: None,
    };
    out.work.prepare_seq = sequence;
    out.work.current_template_preparation_id = Some(intent.preparation_id.into());
    out.preparations.push(prep.clone());
    out.aggregate_version += 1;
    out.validate()?;
    Ok(PreparePlan {
        aggregate: out,
        preparation: prep,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn repeated_intent_is_idempotent_and_new_intent_supersedes_prior() {
        let original = WorkTemplateStateAggregate {
            schema_version: SCHEMA_VERSION.into(),
            aggregate_version: 1,
            work: DocumentWork {
                work_id: "w".into(),
                template_lineage_id: "line".into(),
                current_template_application_id: "a".into(),
                current_template_preparation_id: None,
                prepare_seq: 0,
            },
            applications: vec![WorkTemplateApplication {
                application_id: "a".into(),
                work_id: "w".into(),
                application_epoch: 1,
                pass_evidence_id: "ev".into(),
                previous_application_id: None,
                origin: INITIALIZATION.into(),
                prepared_change_id: None,
                actor: "actor".into(),
                applied_at: "t".into(),
            }],
            preparations: Vec::new(),
            prepared_changes: Vec::new(),
        };
        let pins = PreparePins {
            source_binding_id: "binding".into(),
            source_binding_generation: 3,
            qualification_profile_id: "profile".into(),
        };
        let intent = |request, prep| PrepareIntent {
            prepare_request_id: request,
            pins: &pins,
            preparation_id: prep,
            execution_session_id: "session",
            started_at: "t1",
        };
        let first = plan_prepare(&original, intent("r1", "p1")).unwrap();
        assert_eq!(first.preparation.base_application_id, "a");
        assert_eq!(first.preparation.source_binding_generation, 3);
        assert_eq!(first.preparation.source_binding_id, "binding");
        assert_eq!(first.preparation.qualification_profile_id, "profile");
        assert_eq!(first.aggregate.work.prepare_seq, 1);
        assert_eq!(first.aggregate.aggregate_version, 2);
        assert_eq!(first.aggregate.applications, original.applications);
        assert_eq!(
            plan_prepare(&first.aggregate, intent("r1", "unused"))
                .unwrap()
                .aggregate,
            first.aggregate
        );
        let second = plan_prepare(&first.aggregate, intent("r2", "p2")).unwrap();
        assert_eq!(second.aggregate.aggregate_version, 3);
        assert_eq!(second.aggregate.work.prepare_seq, 2);
        assert_eq!(second.aggregate.applications, original.applications);
        assert_eq!(second.aggregate.preparations[0].status, PREP_SUPERSEDED);
        assert_eq!(second.aggregate.preparations[1].status, PREP_CAPTURING);
        assert_eq!(
            second
                .aggregate
                .work
                .current_template_preparation_id
                .as_deref(),
            Some("p2")
        );
        for (status, change_status, expected_prep, expected_change) in [
            (
                PREP_QUALIFYING,
                CHANGE_PREPARED,
                PREP_SUPERSEDED,
                CHANGE_SUPERSEDED,
            ),
            (
                PREP_READY,
                CHANGE_PREPARED,
                PREP_SUPERSEDED,
                CHANGE_SUPERSEDED,
            ),
            (PREP_APPLIED, CHANGE_APPLIED, PREP_APPLIED, CHANGE_APPLIED),
            (
                PREP_READY,
                CHANGE_REJECTED,
                PREP_SUPERSEDED,
                CHANGE_REJECTED,
            ),
        ] {
            let mut previous = first.aggregate.clone();
            previous.preparations[0].status = status.into();
            previous.preparations[0].prepared_change_id = Some("change".into());
            previous.prepared_changes.push(PreparedTemplateChange {
                prepared_change_id: "change".into(),
                preparation_id: "p1".into(),
                work_id: "w".into(),
                base_application_id: "a".into(),
                target_pass_evidence_id: "ev".into(),
                status: change_status.into(),
                prepared_at: "t1".into(),
                resulting_application_id: None,
                applied_at: None,
            });
            let next = plan_prepare(&previous, intent("r2", "p2")).unwrap();
            assert_eq!(
                next.aggregate.preparations[0].status, expected_prep,
                "{status}"
            );
            assert_eq!(
                next.aggregate.prepared_changes[0].status, expected_change,
                "{status}"
            );
            assert_eq!(next.aggregate.applications, original.applications);
        }
        let mut exhausted = first.aggregate.clone();
        exhausted.work.prepare_seq = i64::MAX;
        assert_eq!(
            plan_prepare(&exhausted, intent("r2", "p2")).unwrap_err().0,
            "prepare_seq 범위 초과"
        );
        assert_eq!(
            plan_prepare(&exhausted, intent("r1", "unused"))
                .unwrap()
                .aggregate,
            exhausted
        );
    }
}
