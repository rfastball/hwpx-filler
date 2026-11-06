//! Pure active-Work decisions over an already observed Job and data mount.

use crate::job::Job;
use crate::work_candidates::{data_binding_matches, rank_available};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkDataBinding {
    pub action: &'static str,
    pub path: String,
    pub sheet: String,
    pub header_row: u64,
    pub kind: String,
    pub notice: String,
    pub discards: bool,
}
impl WorkDataBinding {
    fn action(action: &'static str) -> Self {
        Self {
            action,
            path: String::new(),
            sheet: String::new(),
            header_row: 0,
            kind: String::new(),
            notice: String::new(),
            discards: false,
        }
    }
}

/// `reference_missing` is a host observation of the bound path, never guessed from its shape.
pub fn data_binding_mount(
    job: &Job,
    current: (&str, &str, u64, &str),
    reference_missing: bool,
    discards: bool,
) -> WorkDataBinding {
    if !job.has_data_binding() {
        let mut result = WorkDataBinding::action("none");
        result.notice = format!(
            "'{}' 작업에는 연결된 데이터가 없습니다. 데이터를 고른 뒤 편집기에서 저장하면 다음부터 이 작업과 함께 열립니다.",
            job.name
        );
        return result;
    }
    if data_binding_matches(job, current.0, current.1, current.2, current.3) {
        return WorkDataBinding::action("current");
    }
    if reference_missing {
        let mut result = WorkDataBinding::action("missing");
        result.notice = format!(
            "이 작업에 연결된 데이터 파일을 찾을 수 없습니다: {}. 데이터를 다시 고른 뒤 작업을 저장하세요.",
            job.data_path
        );
        return result;
    }
    WorkDataBinding {
        action: "mount",
        path: job.data_path.clone(),
        sheet: job.data_sheet.clone(),
        header_row: job.data_header_row,
        kind: job.data_kind.clone(),
        notice: String::new(),
        discards,
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActiveWorkContext {
    pub active_name: String,
    pub template_application_ref: Option<String>,
    pub exact_context_restorable: bool,
    pub bound_to_current_data: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DataTransitionReconciliation {
    pub context: ActiveWorkContext,
    pub release: bool,
    pub warning: String,
}

/// The caller has already restored the Job and its exact Application identity.
pub fn reconcile_data_transition(
    context: ActiveWorkContext,
    restore_failed: bool,
    active_job_present: bool,
) -> DataTransitionReconciliation {
    let release = !(context.active_name.is_empty()
        || context.exact_context_restorable && context.bound_to_current_data);
    let warning = if restore_failed {
        "이전 문서 작업을 다시 확인할 수 없어 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
    } else if active_job_present && !context.exact_context_restorable {
        "이전 문서 작업이 같은 작업인지 확인할 수 없어 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
    } else if active_job_present && !context.bound_to_current_data {
        "이전 문서 작업은 다른 데이터에 연결돼 있어 선택을 해제했습니다. 아래 후보를 선택하거나 「문서 작업」에서 그 작업을 여세요."
    } else {
        ""
    };
    DataTransitionReconciliation {
        context,
        release,
        warning: warning.into(),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PreferredWorkDecision {
    pub name: String,
    pub action: &'static str,
    pub reason: &'static str,
}
pub fn request_preferred(
    job: &Job,
    all_jobs: &[Job],
    present_fields: Option<&[String]>,
) -> PreferredWorkDecision {
    if job.has_data_binding() {
        return PreferredWorkDecision {
            name: job.name.clone(),
            action: "select",
            reason: "",
        };
    }
    let Some(fields) = present_fields else {
        return PreferredWorkDecision {
            name: job.name.clone(),
            action: "store",
            reason: "no_binding",
        };
    };
    let available = rank_available(all_jobs, fields)
        .iter()
        .any(|item| item.name == job.name);
    PreferredWorkDecision {
        name: job.name.clone(),
        action: if available { "select" } else { "store" },
        reason: if available { "" } else { "incompatible" },
    }
}

pub fn preferred_notice(
    preferred: &str,
    active: &str,
    all_jobs: Option<&[Job]>,
    present_fields: &[String],
) -> Option<(String, &'static str)> {
    if preferred.is_empty() {
        return None;
    }
    let Some(jobs) = all_jobs else {
        return Some((
            format!(
                "「문서 작업」에서 고른 '{preferred}' 작업을 다시 확인할 수 없습니다. 아래 후보에서 문서 작업을 다시 선택하세요."
            ),
            "warn",
        ));
    };
    if !jobs.iter().any(|job| job.name == preferred) {
        return Some((
            format!("「문서 작업」에서 고른 '{preferred}' 작업이 더는 없습니다."),
            "warn",
        ));
    }
    let suffix = "'문서 작업'에서 직접 선택하세요.";
    if active.is_empty()
        && rank_available(jobs, present_fields)
            .iter()
            .any(|item| item.name == preferred)
    {
        return Some((
            format!("이전에 고른 '{preferred}' 작업을 이 데이터로 쓸 수 있습니다. {suffix}"),
            "ok",
        ));
    }
    if !active.is_empty() {
        return Some((
            format!(
                "'{active}' 작업이 이미 열려 있어 '{preferred}' 으로 바꾸지 않았습니다. {suffix}"
            ),
            "warn",
        ));
    }
    Some((
        format!(
            "「문서 작업」에서 고른 '{preferred}' 은(는) 이 데이터와 구조가 맞지 않습니다. 필요한 열을 갖춘 데이터를 고르거나 편집기에서 연결을 고치세요."
        ),
        "warn",
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn transition_keeps_only_exact_context_on_same_bound_data() {
        let job = Job {
            name: "계약".into(),
            template_path: "a.hwpx".into(),
            data_path: "a.xlsx".into(),
            data_sheet: "Sheet1".into(),
            data_header_row: 2,
            ..Job::default()
        };
        assert_eq!(
            data_binding_mount(&job, ("a.xlsx", "Sheet1", 2, ""), false, true).action,
            "current"
        );
        assert_eq!(
            data_binding_mount(&job, ("a.xlsx", "Other", 2, ""), false, true).action,
            "mount"
        );
        let exact = ActiveWorkContext {
            active_name: job.name.clone(),
            template_application_ref: Some("app".into()),
            exact_context_restorable: true,
            bound_to_current_data: true,
        };
        assert!(!reconcile_data_transition(exact.clone(), false, true).release);
        let different_data = ActiveWorkContext {
            bound_to_current_data: false,
            ..exact
        };
        let decision = reconcile_data_transition(different_data, false, true);
        assert!(decision.release);
        assert!(decision.warning.contains("다른 데이터"));
        assert_eq!(
            request_preferred(&job, std::slice::from_ref(&job), None).action,
            "select"
        );
    }
}
