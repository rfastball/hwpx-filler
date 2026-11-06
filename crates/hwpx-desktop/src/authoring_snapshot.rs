//! Snapshot projection for the active authoring sessions.

use super::*;

impl AuthoringController {
    pub(super) fn snapshot(&self, state: &mut AuthoringState) -> Result<Value, GraphError> {
        let (sessions, revisions, next) = (
            &mut state.sessions,
            &mut state.projection_revisions,
            &mut state.next_projection_revision,
        );
        revisions.retain(|(id, _), _| sessions.iter().any(|session| session.id == *id));
        let tabs: Vec<_> = sessions.iter_mut().map(|session| -> Result<Value,GraphError> {
            let problems = projected_problems(session)?;
            let path = if session.save_path.is_empty() { &session.source_path } else { &session.save_path };
            let name = if path.is_empty() { "새 템플릿" } else {
                Path::new(path).file_name().and_then(|name|name.to_str()).unwrap_or("새 템플릿")
            };
            let outline = projection::outline(session)?;
            let analysis_revision = projection_revision(revisions,next,&session.id,"analysis",session.revision);
            let mut outlined = outline.clone();
            outlined["revision"] = json!(analysis_revision);
            let trial_result = session.trial_result.as_ref().map(|result| {
                let mut projected = result.clone();
                projected["revision"] = json!(projection_revision(revisions,next,&session.id,"trial_result",session.trial_generation));
                projected
            });
            let (trial_state,trial_label,trial_message)=trial_summary(session);
            let compatibility = editing_compatibility(session);
            let key = schema_key(&session.analysis);
            let cases: Vec<_> = session.cases.iter().map(|case| {
                let mut view = case.clone();
                view["needs_review"] = json!(case.get("schema") != Some(&json!(key)));
                view
            }).collect();
            Ok(json!({"id":session.id,"media":session.media,"path":path,"save_path":session.save_path,
                "save_as_required":session.save_path.is_empty(),"name":name,"revision":session.revision,
                "dirty":session.dirty(),"cases_dirty":session.cases_dirty || session.trial_inputs_dirty(),
                "trial_inputs_dirty":session.trial_inputs_dirty(),"analysis":outlined,
                "values":session.values,"selected":session.selected,"cases":cases,
                "cases_error":session.cases_error,"trial_state":trial_state,
                "trial_state_label":trial_label,"trial_state_message":trial_message,
                "trial_result":trial_result,"trial_error":session.trial_error,
                "external_changed":session.external_changed,"rhwp_editable":session.rhwp_editable,
                "rhwp_diagnostics":session.rhwp_diagnostics,"compatibility":compatibility,
                "restore":state.restores.get(&session.id),"has_linked_jobs":self.has_linked_jobs(session)?,
                "readiness":projection::readiness(session,&problems),
                "document_commands":hwpx_filler::template_authoring::document_commands(&session.media,&session.analysis),
                "problems":problems,"trial_missing":projection::trial_missing(&outline,session),
                "trial_coverage":projection::trial_coverage(session),"proposal":self.proposal_view(session)?}))
        }).collect::<Result<_,_>>()?;
        Ok(json!({"tabs":tabs,"active_id":state.active_id}))
    }
}

fn trial_summary(session: &AuthoringSession) -> (&'static str, &'static str, &str) {
    let trial_state = if !session.trial_error.is_empty() {
        "failed"
    } else if session.trial_result.is_none() {
        "untried"
    } else if session.trial_stale() {
        "stale"
    } else if trial_report_failed(session) {
        "failed"
    } else {
        "current"
    };
    let (label, default_message) = match trial_state {
        "current" => ("현재 구성 통과", "현재 시험 구성 통과"),
        "stale" => (
            "마지막 시험 이후 변경됨",
            "마지막 시험 이후 문서 또는 입력이 바뀌었습니다.",
        ),
        "failed" => ("시험 실패", "시험 실패"),
        _ => ("시험 전", "아직 시험하지 않았습니다."),
    };
    let message = if trial_state == "failed" && !session.trial_error.is_empty() {
        session.trial_error.as_str()
    } else {
        default_message
    };
    (trial_state, label, message)
}

fn trial_report_failed(session: &AuthoringSession) -> bool {
    session.trial_result.as_ref().is_some_and(|result| {
        ["missing_fields", "errors"].iter().any(|key| {
            result["report"][*key]
                .as_array()
                .is_some_and(|rows| !rows.is_empty())
        })
    })
}

fn editing_compatibility(session: &AuthoringSession) -> Value {
    if session.media == "txt" {
        json!({"state":"not_applicable","editable":true,"message":null,"diagnostics":[]})
    } else if session.rhwp_editable == Some(true) {
        json!({"state":"editable","editable":true,"message":null,"diagnostics":[]})
    } else if session.rhwp_editable == Some(false) {
        json!({"state":"limited","editable":false,"message":"이 요소는 표시할 수 있지만 변경 후 보존을 확인할 수 없습니다. 원본을 유지한 채 확인하세요.","diagnostics":session.rhwp_diagnostics})
    } else {
        json!({"state":"checking","editable":false,"message":null,"diagnostics":[]})
    }
}
