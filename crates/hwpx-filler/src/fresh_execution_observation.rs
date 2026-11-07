//! Current sealed execution value and runtime admission facts. No historical Plan lookup.

use crate::execution_contract_set::SealedExecutionPlanSemanticPayload;
use crate::field_binding_input::FieldBindingInput;

pub const ADMITTED: &str = "ADMITTED";
pub const NOT_ADMITTED: &str = "NOT_ADMITTED";
pub const ADMISSION_CONTEXT_ERROR: &str = "CONTEXT_ERROR";
pub const EXECUTION_BASE_NOT_ADMITTED: &str = "EXECUTION_BASE_NOT_ADMITTED";
pub const MATERIALIZATION_CONTRACT_NOT_ADMITTED: &str = "MATERIALIZATION_CONTRACT_NOT_ADMITTED";
pub const EXECUTION_EVIDENCE_NOT_OBSERVED: &str = "EXECUTION_EVIDENCE_NOT_OBSERVED";
pub const PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME: &str = "PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME";
pub const CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME: &str =
    "CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME";
pub const RUNTIME_CAPABILITY_CONTEXT_ERROR: &str = "RUNTIME_CAPABILITY_CONTEXT_ERROR";
pub const READY: &str = "READY";
pub const NOT_READY: &str = "NOT_READY";
pub const DOMAIN_BLOCKED: &str = "DOMAIN_BLOCKED";
pub const POLICY_BLOCKED: &str = "POLICY_BLOCKED";
pub const SEALABILITY_CONTEXT_ERROR: &str = "CONTEXT_ERROR";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeAdmissionFacts {
    pub execution_base_kind_admitted: bool,
    pub plan_schema_supported_by_runtime: bool,
    pub canonical_encoding_supported_by_runtime: bool,
    pub materializer_conformance: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimePolicyAdmission {
    pub state: String,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CurrentSealedPlanObservation {
    pub sealed_plan_value: SealedExecutionPlanSemanticPayload,
    pub runtime_policy_admission: RuntimePolicyAdmission,
    pub observed_at: String,
    pub current_field_binding: Option<FieldBindingInput>,
}
impl CurrentSealedPlanObservation {
    pub fn materialization_readiness(&self) -> &'static str {
        decide_materialization_readiness(&self.runtime_policy_admission)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CurrentWorkExecutionObservation {
    pub work_authority_ref: String,
    pub current_sealability: String,
    pub observed_at: String,
    pub current_template_application_ref: Option<String>,
    pub normalized_blockers_or_policy: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionObservationContextError {
    pub code: String,
    pub detail: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FreshExecutionObservation {
    Sealed(Box<CurrentSealedPlanObservation>),
    WorkBlocked(CurrentWorkExecutionObservation),
    ContextError(ExecutionObservationContextError),
}

pub fn decide_runtime_policy_admission(facts: &RuntimeAdmissionFacts) -> RuntimePolicyAdmission {
    if facts.materializer_conformance == ADMISSION_CONTEXT_ERROR {
        return RuntimePolicyAdmission {
            state: ADMISSION_CONTEXT_ERROR.into(),
            reasons: vec![RUNTIME_CAPABILITY_CONTEXT_ERROR.into()],
        };
    }
    let mut reasons = Vec::new();
    if !facts.execution_base_kind_admitted {
        reasons.push(EXECUTION_BASE_NOT_ADMITTED.into());
    }
    if !facts.plan_schema_supported_by_runtime {
        reasons.push(PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME.into());
    }
    if !facts.canonical_encoding_supported_by_runtime {
        reasons.push(CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME.into());
    }
    if facts.materializer_conformance != ADMITTED {
        reasons.push(MATERIALIZATION_CONTRACT_NOT_ADMITTED.into());
    }
    RuntimePolicyAdmission {
        state: if reasons.is_empty() {
            ADMITTED
        } else {
            NOT_ADMITTED
        }
        .into(),
        reasons,
    }
}

pub fn decide_materialization_readiness(admission: &RuntimePolicyAdmission) -> &'static str {
    if admission.state == ADMITTED {
        READY
    } else {
        NOT_READY
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn runtime_context_precedes_and_other_refusals_accumulate_in_order() {
        let mut facts = RuntimeAdmissionFacts {
            execution_base_kind_admitted: false,
            plan_schema_supported_by_runtime: false,
            canonical_encoding_supported_by_runtime: false,
            materializer_conformance: ADMISSION_CONTEXT_ERROR.into(),
        };
        let context = decide_runtime_policy_admission(&facts);
        assert_eq!(context.reasons, [RUNTIME_CAPABILITY_CONTEXT_ERROR]);
        assert_eq!(decide_materialization_readiness(&context), NOT_READY);
        facts.materializer_conformance = NOT_ADMITTED.into();
        let refused = decide_runtime_policy_admission(&facts);
        assert_eq!(
            refused.reasons,
            [
                EXECUTION_BASE_NOT_ADMITTED,
                PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME,
                CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME,
                MATERIALIZATION_CONTRACT_NOT_ADMITTED
            ]
        );
        facts.execution_base_kind_admitted = true;
        facts.plan_schema_supported_by_runtime = true;
        facts.canonical_encoding_supported_by_runtime = true;
        facts.materializer_conformance = ADMITTED.into();
        assert_eq!(
            decide_materialization_readiness(&decide_runtime_policy_admission(&facts)),
            READY
        );
    }
}
