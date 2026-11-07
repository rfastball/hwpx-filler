//! Facts for one managed generation run; execution and delivery live elsewhere.

use crate::job::{Job, MISSING_MARKER, rules_fingerprints};
use serde_json::{Map, Value};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};

pub fn blank_marker(blanks: &[String]) -> &'static str {
    if blanks.is_empty() {
        ""
    } else {
        MISSING_MARKER
    }
}
pub fn run_status(succeeded: usize, total: usize, cancelled: bool) -> &'static str {
    if cancelled {
        "partiallyCompleted"
    } else if total > 0 && succeeded >= total {
        "completed"
    } else if succeeded > 0 {
        "partiallyCompleted"
    } else {
        "failed"
    }
}
pub fn run_completed(cancelled: bool, failed: usize) -> bool {
    !cancelled && failed == 0
}

#[derive(Clone, Debug)]
pub struct GenerationRun {
    pub job_name: String,
    pub revisions: Map<String, Value>,
    pub rules: Option<Map<String, Value>>,
    pub token: String,
    cancel: Arc<AtomicBool>,
}
impl GenerationRun {
    pub fn request_cancel(&self) {
        self.cancel.store(true, Ordering::Release);
    }
    pub fn is_cancelled(&self) -> bool {
        self.cancel.load(Ordering::Acquire)
    }
}
pub fn start_run(job: Option<&Job>, job_name: &str, token: &str) -> GenerationRun {
    let mut revisions = Map::new();
    let (job_name, rules) = if let Some(job) = job {
        revisions.insert("template".into(), Value::from(job.template_revision));
        revisions.insert("binding".into(), Value::from(job.binding_revision));
        (
            if job_name.is_empty() {
                job.name.clone()
            } else {
                job_name.into()
            },
            Some(rules_fingerprints(job)),
        )
    } else {
        (job_name.into(), None)
    };
    GenerationRun {
        job_name,
        revisions,
        rules,
        token: token.into(),
        cancel: Arc::new(AtomicBool::new(false)),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn cancellation_and_run_identity_do_not_follow_later_job_edits() {
        assert_eq!(blank_marker(&[]), "");
        assert_eq!(blank_marker(&["담당자".into()]), MISSING_MARKER);
        let mut job = Job {
            name: "원본".into(),
            ..Job::default()
        };
        let run = start_run(Some(&job), "", "token");
        assert_eq!(run.token, "token");
        assert_eq!(run.revisions["binding"], 1);
        assert_eq!(run.rules, Some(rules_fingerprints(&job)));
        let anonymous = start_run(None, "", "");
        assert_eq!(anonymous.job_name, "");
        assert!(anonymous.revisions.is_empty());
        assert!(anonymous.rules.is_none());
        job.template_revision = 9;
        job.name = "바뀜".into();
        assert_eq!(run.job_name, "원본");
        assert_eq!(run.revisions["template"], 1);
        assert_eq!(run_status(2, 2, false), "completed");
        assert_eq!(run_status(1, 2, false), "partiallyCompleted");
        assert_eq!(run_status(0, 2, false), "failed");
        assert_eq!(run_status(0, 3, true), "partiallyCompleted");
        assert!(run_completed(false, 0));
        assert!(!run_completed(false, 1));
        assert!(!run_completed(true, 0));
        assert!(!run.is_cancelled());
        run.request_cancel();
        assert!(run.is_cancelled());
    }
}
