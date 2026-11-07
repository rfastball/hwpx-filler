//! Opaque product status projection for preparation and application outcomes.

use crate::text_render::python_repr;
use crate::work_template_state::*;
use serde_json::{Value, json};

pub const CAPABILITY_UNSUPPORTED_MEDIA: &str = "unsupported_media";
pub const CAPABILITY_INITIALIZATION_REQUIRED: &str = "initialization_required";
pub const PRODUCT_PREPARATION_STATUSES: [&str; 12] = [
    "checking",
    "ready",
    "no_change",
    "invalid",
    "error",
    "interrupted",
    "source_changed",
    "changed_while_checking",
    "superseded",
    "applied",
    "conflict",
    "rejected",
];
pub const PRODUCT_APPLY_STATUSES: [&str; 6] = [
    "applied",
    "already_applied",
    "applied_then_advanced",
    "conflict",
    "superseded",
    "rejected",
];

fn repr(value: Option<&str>) -> String {
    value
        .map(|text| python_repr(&Value::String(text.into())))
        .unwrap_or_else(|| "None".into())
}
pub fn product_preparation_status(
    prep: &TemplateChangePreparation,
    change: Option<&str>,
) -> Result<&'static str, String> {
    let product = if prep.status == PREP_READY {
        let Some(change) = change else {
            return Err(format!(
                "READY Preparation {} 에 Change 상태가 없다",
                prep.preparation_id
            ));
        };
        match change {
            CHANGE_PREPARED => Some("ready"),
            CHANGE_APPLIED => Some("applied"),
            CHANGE_SUPERSEDED => Some("superseded"),
            CHANGE_CONFLICTED => Some("conflict"),
            CHANGE_REJECTED => Some("rejected"),
            _ => None,
        }
    } else {
        match prep.status.as_str() {
            PREP_CAPTURING | PREP_QUALIFYING => Some("checking"),
            PREP_SUPERSEDED => Some("superseded"),
            PREP_APPLIED => Some("applied"),
            PREP_CONFLICTED => Some("conflict"),
            PREP_REJECTED | PREP_PROFILE_REVOKED => Some("rejected"),
            PREP_CAPTURE_ERROR | PREP_QUALIFICATION_ERROR => Some("error"),
            PREP_SOURCE_BINDING_CHANGED => Some("source_changed"),
            PREP_QUALIFICATION_FAILED => Some("invalid"),
            PREP_INTERRUPTED => Some("interrupted"),
            PREP_BASE_CHANGED => Some("changed_while_checking"),
            PREP_NO_CHANGE => Some("no_change"),
            _ => None,
        }
    };
    product.ok_or_else(|| {
        format!(
            "투영표 밖 상태: prep={} change={}",
            repr(Some(&prep.status)),
            repr(change)
        )
    })
}

pub fn template_change_zone_actionable(
    supported: bool,
    reason: &str,
    preparation_status: Option<&str>,
) -> bool {
    supported
        && (reason == CAPABILITY_INITIALIZATION_REQUIRED
            || preparation_status.is_some_and(|status| {
                PRODUCT_PREPARATION_STATUSES.contains(&status)
                    && !["no_change", "applied", "invalid", "rejected"].contains(&status)
            }))
}

pub fn product_apply_status(outcome: &str) -> Result<&'static str, String> {
    match outcome {
        "APPLIED" => Ok("applied"),
        "ALREADY_APPLIED" => Ok("already_applied"),
        "APPLIED_THEN_ADVANCED" => Ok("applied_then_advanced"),
        "CONFLICT" => Ok("conflict"),
        "SUPERSEDED" => Ok("superseded"),
        "REJECTED" => Ok("rejected"),
        _ => Err(format!("투영표 밖 apply 결과: {}", repr(Some(outcome)))),
    }
}

/// The change token is emitted only while the preparation is ready to apply.
pub fn preparation_view(
    prep: &TemplateChangePreparation,
    change_status: Option<&str>,
    preparation_token: &str,
    change_token: Option<&str>,
    diagnostics: &[(String, String)],
) -> Result<Value, String> {
    let status = product_preparation_status(prep, change_status)?;
    Ok(json!({
        "preparation_token":preparation_token,
        "status":status,
        "change_token":if status == "ready" {change_token} else {None},
        "diagnostics":diagnostics.iter().map(|(kind,message)| json!({"kind":kind,"message":message})).collect::<Vec<_>>(),
        "prepared_at":prep.completed_at,
    }))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn ready_status_follows_change_and_never_leaks_stale_token() {
        let mut prep = TemplateChangePreparation {
            preparation_id: "p".into(),
            work_id: "w".into(),
            prepare_request_id: "r".into(),
            prepare_seq: 1,
            base_application_id: "a".into(),
            source_binding_id: "b".into(),
            source_binding_generation: 1,
            qualification_profile_id: "q".into(),
            execution_session_id: "s".into(),
            status: PREP_READY.into(),
            started_at: "t".into(),
            observation_id: None,
            revision_id: None,
            attempt_id: None,
            evidence_id: None,
            prepared_change_id: Some("c".into()),
            diagnostics: Vec::new(),
            completed_at: Some("done".into()),
        };
        assert_eq!(
            product_preparation_status(&prep, Some(CHANGE_APPLIED)).unwrap(),
            "applied"
        );
        assert_eq!(
            preparation_view(&prep, Some(CHANGE_APPLIED), "opaque", Some("stale"), &[]).unwrap()["change_token"],
            Value::Null
        );
        assert!(product_preparation_status(&prep, None).is_err());
        prep.status = PREP_NO_CHANGE.into();
        assert!(!template_change_zone_actionable(
            true,
            "",
            Some("no_change")
        ));
        assert!(template_change_zone_actionable(true, "", Some("ready")));
        assert!(product_apply_status("INTEGRITY_ERROR").is_err());
        for (internal, change, product) in [
            (PREP_CAPTURING, None, "checking"),
            (PREP_QUALIFYING, None, "checking"),
            (PREP_NO_CHANGE, None, "no_change"),
            (PREP_CAPTURE_ERROR, None, "error"),
            (PREP_QUALIFICATION_ERROR, None, "error"),
            (PREP_QUALIFICATION_FAILED, None, "invalid"),
            (PREP_INTERRUPTED, None, "interrupted"),
            (PREP_SOURCE_BINDING_CHANGED, None, "source_changed"),
            (PREP_BASE_CHANGED, None, "changed_while_checking"),
            (PREP_PROFILE_REVOKED, None, "rejected"),
            (PREP_SUPERSEDED, None, "superseded"),
            (PREP_READY, Some(CHANGE_PREPARED), "ready"),
            (PREP_READY, Some(CHANGE_APPLIED), "applied"),
            (PREP_READY, Some(CHANGE_SUPERSEDED), "superseded"),
            (PREP_READY, Some(CHANGE_CONFLICTED), "conflict"),
            (PREP_READY, Some(CHANGE_REJECTED), "rejected"),
        ] {
            prep.status = internal.into();
            assert_eq!(product_preparation_status(&prep, change).unwrap(), product);
            let view = preparation_view(&prep, change, "pt", Some("ct"), &[]).unwrap();
            assert_eq!(view["change_token"].is_string(), product == "ready");
        }
        prep.status = PREP_READY.into();
        assert!(product_preparation_status(&prep, Some("unknown")).is_err());
        for status in PRODUCT_PREPARATION_STATUSES {
            assert_eq!(
                template_change_zone_actionable(true, "", Some(status)),
                !["no_change", "applied", "invalid", "rejected"].contains(&status)
            );
        }
    }
}
