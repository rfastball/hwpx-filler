//! Pure relabeling of existing execution verdicts into seven workbench status codes.

use crate::fresh_execution_observation::{ADMISSION_CONTEXT_ERROR, RuntimePolicyAdmission};

pub const NO_EVIDENCE: &str = "NO_EVIDENCE";
pub const CHECKING: &str = "CHECKING";
pub const CURRENT: &str = "CURRENT";
pub const STALE: &str = "STALE";
pub const DOMAIN_BLOCKED: &str = "DOMAIN_BLOCKED";
pub const POLICY_BLOCKED: &str = "POLICY_BLOCKED";
pub const CONTEXT_ERROR: &str = "CONTEXT_ERROR";

pub const WORKBENCH_EXECUTION_STATUS_CODES: [&str; 7] = [
    NO_EVIDENCE,
    CHECKING,
    CURRENT,
    STALE,
    DOMAIN_BLOCKED,
    POLICY_BLOCKED,
    CONTEXT_ERROR,
];

pub fn workbench_execution_status_phrase(code: &str) -> Option<&'static str> {
    match code {
        NO_EVIDENCE => Some("현재 설정을 확인해야 합니다"),
        CHECKING => Some("현재 설정을 확인하고 있습니다"),
        CURRENT => Some("현재 설정이 반영됐습니다"),
        STALE => Some("설정이 바뀌어 다시 확인해야 합니다"),
        DOMAIN_BLOCKED => Some("확인할 항목이 있습니다"),
        POLICY_BLOCKED => Some("현재 이 구성으로 실행을 준비할 수 없습니다"),
        CONTEXT_ERROR => Some("현재 실행 상태를 확인할 수 없습니다"),
        _ => None,
    }
}

/// This does not reconsider admission, sealability, or currentness.
pub fn derive_workbench_execution_status(
    orchestration: &str,
    admission: Option<&RuntimePolicyAdmission>,
    current_work_sealability: Option<&str>,
) -> &'static str {
    if admission.is_some_and(|item| item.state == ADMISSION_CONTEXT_ERROR)
        || current_work_sealability == Some(CONTEXT_ERROR)
    {
        CONTEXT_ERROR
    } else if orchestration == CHECKING {
        CHECKING
    } else if current_work_sealability == Some(DOMAIN_BLOCKED) {
        DOMAIN_BLOCKED
    } else if current_work_sealability == Some(POLICY_BLOCKED) {
        POLICY_BLOCKED
    } else if orchestration == STALE {
        STALE
    } else if orchestration == CURRENT {
        CURRENT
    } else {
        NO_EVIDENCE
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn already_decided_verdicts_keep_precedence_and_phrase() {
        let context = RuntimePolicyAdmission {
            state: CONTEXT_ERROR.into(),
            reasons: vec![],
        };
        let not_admitted = RuntimePolicyAdmission {
            state: crate::fresh_execution_observation::NOT_ADMITTED.into(),
            reasons: vec!["MATERIALIZATION_CONTRACT_NOT_ADMITTED".into()],
        };
        let cases = [
            (NO_EVIDENCE, None, None, NO_EVIDENCE),
            (CHECKING, None, None, CHECKING),
            (CHECKING, None, Some(CONTEXT_ERROR), CONTEXT_ERROR),
            (CURRENT, Some(&not_admitted), None, CURRENT),
            (NO_EVIDENCE, None, Some(DOMAIN_BLOCKED), DOMAIN_BLOCKED),
            (NO_EVIDENCE, None, Some(POLICY_BLOCKED), POLICY_BLOCKED),
            (CURRENT, None, Some(CONTEXT_ERROR), CONTEXT_ERROR),
            (
                CHECKING,
                Some(&context),
                Some(DOMAIN_BLOCKED),
                CONTEXT_ERROR,
            ),
            (CHECKING, None, Some(DOMAIN_BLOCKED), CHECKING),
            (STALE, None, Some(DOMAIN_BLOCKED), DOMAIN_BLOCKED),
            (CURRENT, None, Some(POLICY_BLOCKED), POLICY_BLOCKED),
            (STALE, None, None, STALE),
            (CURRENT, None, None, CURRENT),
            ("unknown", None, None, NO_EVIDENCE),
        ];
        for (orchestration, admission, sealability, expected) in cases {
            assert_eq!(
                derive_workbench_execution_status(orchestration, admission, sealability),
                expected
            );
            assert!(workbench_execution_status_phrase(expected).is_some());
        }
        assert_eq!(
            WORKBENCH_EXECUTION_STATUS_CODES,
            [
                "NO_EVIDENCE",
                "CHECKING",
                "CURRENT",
                "STALE",
                "DOMAIN_BLOCKED",
                "POLICY_BLOCKED",
                "CONTEXT_ERROR"
            ]
        );
        assert_eq!(workbench_execution_status_phrase("unknown"), None);
    }
}
