//! Current-value seal outcomes. No durable plan publication or replay is implied.

use crate::execution_contract_set::SealedExecutionPlanSemanticPayload;
use crate::text_render::python_repr;
use serde_json::Value;
use std::fmt;

pub const DIGEST_MISMATCH: &str = "DIGEST_MISMATCH";
pub const CURRENT_BASIS_NOT_SEALABLE: &str = "CURRENT_BASIS_NOT_SEALABLE";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionPlanOutcomeError(pub String);
impl fmt::Display for ExecutionPlanOutcomeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ExecutionPlanOutcomeError {}
fn require_nonempty(value: &str, what: &str) -> Result<(), ExecutionPlanOutcomeError> {
    if value.is_empty() {
        return Err(ExecutionPlanOutcomeError(format!(
            "{what} 는 비어 있지 않은 문자열이어야 한다"
        )));
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RequestedVersionSelector {
    Auto,
    Exact(String),
}
impl RequestedVersionSelector {
    pub fn exact(value: impl Into<String>) -> Result<Self, ExecutionPlanOutcomeError> {
        let value = value.into();
        require_nonempty(&value, "RequestedExact.value")?;
        Ok(Self::Exact(value))
    }
    pub fn selected<'a>(&'a self, default: &'a str) -> &'a str {
        match self {
            Self::Auto => default,
            Self::Exact(value) => value,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionPlanSealed {
    pub execution_basis_digest: String,
    pub plan_payload: Option<SealedExecutionPlanSemanticPayload>,
}
impl ExecutionPlanSealed {
    pub fn validate(&self) -> Result<(), ExecutionPlanOutcomeError> {
        require_nonempty(&self.execution_basis_digest, "execution_basis_digest")
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionQualificationBlocked {
    pub capture_evidence_ref: String,
    pub normalized_blockers: Vec<String>,
    pub captured_execution_input_digest: Option<String>,
    pub captured_attempt_digest: Option<String>,
}
impl ExecutionQualificationBlocked {
    pub fn validate(&self) -> Result<(), ExecutionPlanOutcomeError> {
        require_nonempty(&self.capture_evidence_ref, "capture_evidence_ref")?;
        if self.normalized_blockers.iter().any(String::is_empty) {
            return Err(ExecutionPlanOutcomeError(
                "normalized_blockers 형식 불량".into(),
            ));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionPolicyBlocked {
    pub policy_code: String,
    pub qualification_profile_id: Option<String>,
    pub observed_policy_version: Option<String>,
    pub policy_observation_digest: Option<String>,
    pub captured_attempt_digest: Option<String>,
}
impl ExecutionPolicyBlocked {
    pub fn validate(&self) -> Result<(), ExecutionPlanOutcomeError> {
        require_nonempty(&self.policy_code, "policy_code")
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StaleExecutionBasis {
    pub captured_execution_input_digest: String,
    pub candidate_execution_basis_digest: String,
    pub stale_reason: String,
    pub observed_current_summary: Option<Value>,
}
impl StaleExecutionBasis {
    pub fn validate(&self) -> Result<(), ExecutionPlanOutcomeError> {
        require_nonempty(
            &self.captured_execution_input_digest,
            "captured_execution_input_digest",
        )?;
        require_nonempty(
            &self.candidate_execution_basis_digest,
            "candidate_execution_basis_digest",
        )?;
        if !matches!(
            self.stale_reason.as_str(),
            DIGEST_MISMATCH | CURRENT_BASIS_NOT_SEALABLE
        ) {
            return Err(ExecutionPlanOutcomeError(format!(
                "stale_reason 미상: {}",
                python_repr(&Value::String(self.stale_reason.clone()))
            )));
        }
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SealTerminalOutcome {
    Sealed(Box<ExecutionPlanSealed>),
    QualificationBlocked(ExecutionQualificationBlocked),
    PolicyBlocked(ExecutionPolicyBlocked),
    Stale(StaleExecutionBasis),
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn exact_intent_and_terminal_vocabulary_are_closed() {
        assert_ne!(
            RequestedVersionSelector::Auto,
            RequestedVersionSelector::exact("v1").unwrap()
        );
        assert_eq!(
            RequestedVersionSelector::exact("").unwrap_err().to_string(),
            "RequestedExact.value 는 비어 있지 않은 문자열이어야 한다"
        );
        assert_eq!(
            RequestedVersionSelector::Auto.selected("shipping/v1"),
            "shipping/v1"
        );
        assert_eq!(
            RequestedVersionSelector::exact("older/v1")
                .unwrap()
                .selected("shipping/v1"),
            "older/v1"
        );
        let sealed = ExecutionPlanSealed {
            execution_basis_digest: "sha256:basis".into(),
            plan_payload: None,
        };
        sealed.validate().unwrap();
        assert!(
            ExecutionPlanSealed {
                execution_basis_digest: String::new(),
                ..sealed
            }
            .validate()
            .is_err()
        );
        let blocked = ExecutionQualificationBlocked {
            capture_evidence_ref: "sha256:evidence".into(),
            normalized_blockers: vec!["ACTIVE_FIELD_UNBOUND".into()],
            captured_execution_input_digest: None,
            captured_attempt_digest: None,
        };
        blocked.validate().unwrap();
        let mut invalid_blocked = blocked.clone();
        invalid_blocked.capture_evidence_ref.clear();
        assert!(invalid_blocked.validate().is_err());
        invalid_blocked = blocked;
        invalid_blocked.normalized_blockers = vec![String::new()];
        assert!(invalid_blocked.validate().is_err());
        let policy = ExecutionPolicyBlocked {
            policy_code: "QUALIFICATION_PROFILE_REVOKED".into(),
            qualification_profile_id: None,
            observed_policy_version: None,
            policy_observation_digest: None,
            captured_attempt_digest: None,
        };
        policy.validate().unwrap();
        assert_eq!(policy.qualification_profile_id, None);
        assert!(
            ExecutionPolicyBlocked {
                policy_code: String::new(),
                ..policy
            }
            .validate()
            .is_err()
        );
        let valid_stale = StaleExecutionBasis {
            captured_execution_input_digest: "sha256:input".into(),
            candidate_execution_basis_digest: "sha256:basis".into(),
            stale_reason: DIGEST_MISMATCH.into(),
            observed_current_summary: None,
        };
        valid_stale.validate().unwrap();
        assert!(
            StaleExecutionBasis {
                captured_execution_input_digest: String::new(),
                ..valid_stale
            }
            .validate()
            .is_err()
        );
        let stale = StaleExecutionBasis {
            captured_execution_input_digest: "a".into(),
            candidate_execution_basis_digest: "b".into(),
            stale_reason: "latest".into(),
            observed_current_summary: None,
        };
        assert_eq!(
            stale.validate().unwrap_err().to_string(),
            "stale_reason 미상: 'latest'"
        );
    }
}
