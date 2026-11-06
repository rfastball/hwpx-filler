//! Current Work classification after an exact capture; store and fence remain host responsibilities.

use crate::execution_capture::{
    APPLIED_TEMPLATE_CANDIDATE, CaptureExecutionQualificationResult, ResolvedSealPolicy,
};
use crate::execution_composition::{
    RuntimeConformanceQuery, RuntimeMaterializerConformanceManifest,
    RuntimeMaterializerConformanceRegistry,
};
use crate::execution_contract_set::SealedExecutionPlanSemanticPayload;
use crate::execution_semantic_kernel::{KernelResult, compile_sealed_plan_from_snapshot};
use crate::fresh_execution_observation::{
    CurrentSealedPlanObservation, CurrentWorkExecutionObservation, DOMAIN_BLOCKED,
    FreshExecutionObservation, POLICY_BLOCKED, RuntimeAdmissionFacts, SEALABILITY_CONTEXT_ERROR,
    decide_runtime_policy_admission,
};
use crate::seal_execution_plan::WorkExecutionSummary;

pub struct RuntimeConformanceBinding<'a> {
    pub registry: &'a RuntimeMaterializerConformanceRegistry,
    pub primary_manifest: &'a RuntimeMaterializerConformanceManifest,
    pub additional_manifests: &'a [RuntimeMaterializerConformanceManifest],
}
impl RuntimeConformanceBinding<'_> {
    fn manifest_for(&self, primitive: &str) -> &RuntimeMaterializerConformanceManifest {
        std::iter::once(self.primary_manifest)
            .chain(self.additional_manifests.iter())
            .find(|manifest| manifest.native_primitive_contract_id == primitive)
            .unwrap_or(self.primary_manifest)
    }
}

pub fn observe_current_capture(
    work_id: &str,
    exact: &WorkExecutionSummary,
    policy: &ResolvedSealPolicy,
    current: CaptureExecutionQualificationResult,
    observed_at: &str,
    runtime: &RuntimeConformanceBinding<'_>,
) -> FreshExecutionObservation {
    let blocked = |sealability: &str, blockers: Vec<String>| {
        FreshExecutionObservation::WorkBlocked(CurrentWorkExecutionObservation {
            work_authority_ref: work_id.into(),
            current_sealability: sealability.into(),
            observed_at: observed_at.into(),
            current_template_application_ref: Some(exact.template_application_id.clone()),
            normalized_blockers_or_policy: blockers,
        })
    };
    let captured = match current {
        CaptureExecutionQualificationResult::ContextError(_) => {
            return blocked(SEALABILITY_CONTEXT_ERROR, Vec::new());
        }
        CaptureExecutionQualificationResult::PolicyBlocked(item) => {
            return blocked(POLICY_BLOCKED, vec![item.policy_code]);
        }
        CaptureExecutionQualificationResult::DomainBlocked(item) => {
            return blocked(DOMAIN_BLOCKED, item.normalized_blockers.clone());
        }
        CaptureExecutionQualificationResult::Complete(item) => item,
    };
    let field_binding = captured.field_binding.clone();
    let value = match compile_sealed_plan_from_snapshot(&captured) {
        Err(_) => return blocked(SEALABILITY_CONTEXT_ERROR, Vec::new()),
        Ok(KernelResult::Blocked(item)) => {
            return blocked(DOMAIN_BLOCKED, item.normalized_blockers);
        }
        Ok(KernelResult::Plan(value)) => value,
    };
    FreshExecutionObservation::Sealed(Box::new(observe_sealable(
        policy,
        *value,
        field_binding,
        observed_at,
        runtime,
    )))
}

pub fn observe_sealable(
    policy: &ResolvedSealPolicy,
    value: SealedExecutionPlanSemanticPayload,
    current_field_binding: crate::field_binding_input::FieldBindingInput,
    observed_at: &str,
    runtime: &RuntimeConformanceBinding<'_>,
) -> CurrentSealedPlanObservation {
    let contracts = &value.execution_basis.contracts.roles;
    let manifest = runtime.manifest_for(&contracts.native_primitive_contract_id);
    let admitted = runtime.registry.is_admitted(&RuntimeConformanceQuery {
        runtime_capability_manifest_digest: &manifest.runtime_capability_manifest_digest,
        materialization_contract_id: &contracts.materialization_contract_id,
        materialization_base_contract_id: &contracts.materialization_base_contract_id,
        native_primitive_contract_id: &contracts.native_primitive_contract_id,
        composition_contract_id: &contracts.composition_contract_id,
        plan_schema_version: &value.plan_schema_version,
        canonical_encoding_version: &value.canonical_encoding_version,
    });
    let admission = decide_runtime_policy_admission(&RuntimeAdmissionFacts {
        execution_base_kind_admitted: policy.execution_base_kind == APPLIED_TEMPLATE_CANDIDATE,
        plan_schema_supported_by_runtime: manifest
            .supported_plan_schema_versions
            .contains(&value.plan_schema_version),
        canonical_encoding_supported_by_runtime: manifest
            .supported_canonical_encoding_versions
            .contains(&value.canonical_encoding_version),
        materializer_conformance: if admitted { "ADMITTED" } else { "NOT_ADMITTED" }.into(),
    });
    CurrentSealedPlanObservation {
        sealed_plan_value: value,
        runtime_policy_admission: admission,
        observed_at: observed_at.into(),
        current_field_binding: Some(current_field_binding),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_capture::{CapturedExecutionPolicyBlock, ExecutionCaptureContextError};
    use crate::runtime_capability::admitted_runtime_conformance_registry;
    use crate::seal_execution_plan::tests::{domain_block, snapshot};

    #[test]
    fn fresh_observation_recomputes_current_value_and_keeps_blocker_classes() {
        let runtime = admitted_runtime_conformance_registry().unwrap();
        let binding = RuntimeConformanceBinding {
            registry: &runtime.registry,
            primary_manifest: &runtime.hwpx,
            additional_manifests: &[runtime.txt],
        };
        let initial = snapshot("o1", false);
        let summary = WorkExecutionSummary {
            qualification_profile_id: initial
                .template
                .qualification
                .qualification_profile_id
                .clone(),
            template_application_id: "app-1".into(),
        };
        let policy = &initial.resolved_seal_policy;
        let observe = |current| {
            observe_current_capture(
                "work-1",
                &summary,
                policy,
                current,
                "observed-now",
                &binding,
            )
        };
        let mut plans = Vec::new();
        for option in ["o1", "o2"] {
            let captured = snapshot(option, false);
            let observed = observe(CaptureExecutionQualificationResult::Complete(Box::new(
                captured.clone(),
            )));
            let FreshExecutionObservation::Sealed(observed) = observed else {
                panic!("sealable observation")
            };
            assert_eq!(
                observed.current_field_binding.as_ref(),
                Some(&captured.field_binding)
            );
            assert_eq!(observed.observed_at, "observed-now");
            assert_eq!(observed.runtime_policy_admission.state, "ADMITTED");
            assert_eq!(observed.materialization_readiness(), "READY");
            plans.push(observed.sealed_plan_value);
        }
        assert_ne!(plans[0], plans[1]);
        assert_ne!(plans[0].ordered_operations, plans[1].ordered_operations);
        let mut unsupported = initial.clone();
        unsupported.resolved_seal_policy.plan_schema_version = "unknown".into();
        for (current, state, reasons) in [
            (
                domain_block(true),
                DOMAIN_BLOCKED,
                vec!["SLOT_CONFIGURATION_INCOMPLETE"],
            ),
            (
                domain_block(false),
                DOMAIN_BLOCKED,
                vec!["ACTIVE_FIELD_UNBOUND"],
            ),
            (
                CaptureExecutionQualificationResult::Complete(Box::new(snapshot("o2", true))),
                DOMAIN_BLOCKED,
                vec!["ACTIVE_FIELD_UNBOUND"],
            ),
            (
                CaptureExecutionQualificationResult::PolicyBlocked(CapturedExecutionPolicyBlock {
                    policy_code: "REVOKED".into(),
                    observed_at: "before".into(),
                    qualification_profile_id: Some(summary.qualification_profile_id.clone()),
                    observed_policy_version: None,
                    policy_observation_digest: None,
                    captured_attempt_digest: None,
                }),
                POLICY_BLOCKED,
                vec!["REVOKED"],
            ),
            (
                CaptureExecutionQualificationResult::ContextError(ExecutionCaptureContextError {
                    code: "CORRUPT".into(),
                    detail: "unreadable".into(),
                }),
                SEALABILITY_CONTEXT_ERROR,
                vec![],
            ),
            (
                CaptureExecutionQualificationResult::Complete(Box::new(unsupported)),
                SEALABILITY_CONTEXT_ERROR,
                vec![],
            ),
        ] {
            let FreshExecutionObservation::WorkBlocked(observed) = observe(current) else {
                panic!("{state}")
            };
            assert_eq!(observed.work_authority_ref, "work-1");
            assert_eq!(
                observed.current_template_application_ref.as_deref(),
                Some("app-1")
            );
            assert_eq!(observed.current_sealability, state);
            assert_eq!(observed.normalized_blockers_or_policy, reasons);
            assert_eq!(observed.observed_at, "observed-now");
        }
    }

    #[test]
    fn an_unregistered_or_incompatible_runtime_never_makes_a_plan_ready() {
        let runtime = admitted_runtime_conformance_registry().unwrap();
        let empty_registry = RuntimeMaterializerConformanceRegistry::default();
        let captured = snapshot("o1", false);
        let KernelResult::Plan(plan) = compile_sealed_plan_from_snapshot(&captured).unwrap() else {
            unreachable!()
        };
        for axis in 0..5 {
            let mut manifest = runtime.hwpx.clone();
            let mut policy = captured.resolved_seal_policy.clone();
            match axis {
                0 => {}
                1 => manifest.runtime_capability_manifest_digest = "unregistered".into(),
                2 => manifest.supported_plan_schema_versions.clear(),
                3 => manifest.supported_canonical_encoding_versions.clear(),
                _ => policy.execution_base_kind = "unknown".into(),
            }
            let binding = RuntimeConformanceBinding {
                registry: if axis == 0 {
                    &empty_registry
                } else {
                    &runtime.registry
                },
                primary_manifest: &manifest,
                additional_manifests: &[],
            };
            let observed = observe_sealable(
                &policy,
                *plan.clone(),
                captured.field_binding.clone(),
                "now",
                &binding,
            );
            assert_eq!(
                observed.runtime_policy_admission.state, "NOT_ADMITTED",
                "axis {axis}"
            );
            assert_eq!(observed.materialization_readiness(), "NOT_READY");
            assert_eq!(
                observed.runtime_policy_admission.reasons[0],
                match axis {
                    2 => "PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME",
                    3 => "CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME",
                    4 => "EXECUTION_BASE_NOT_ADMITTED",
                    _ => "MATERIALIZATION_CONTRACT_NOT_ADMITTED",
                }
            );
        }
    }
    #[test]
    fn runtime_manifest_is_selected_by_plan_primitive_without_cross_media_admission() {
        let primary = RuntimeMaterializerConformanceManifest {
            runtime_capability_manifest_digest: "hwpx-digest".into(),
            materialization_contract_id: "materialization/v1".into(),
            materialization_base_contract_id: "candidate/v1".into(),
            native_primitive_contract_id: "hwpx-native".into(),
            admitted_composition_contract_ids: vec!["hwpx-composition".into()],
            supported_plan_schema_versions: vec!["plan/v2".into()],
            supported_canonical_encoding_versions: vec!["canonical/v1".into()],
            conformance_status: "PASS".into(),
        };
        let txt = RuntimeMaterializerConformanceManifest {
            native_primitive_contract_id: "txt-native".into(),
            runtime_capability_manifest_digest: "txt-digest".into(),
            ..primary.clone()
        };
        let registry = RuntimeMaterializerConformanceRegistry::default();
        let binding = RuntimeConformanceBinding {
            registry: &registry,
            primary_manifest: &primary,
            additional_manifests: &[txt],
        };
        assert_eq!(
            binding
                .manifest_for("txt-native")
                .runtime_capability_manifest_digest,
            "txt-digest"
        );
        assert_eq!(
            binding
                .manifest_for("unknown")
                .runtime_capability_manifest_digest,
            "hwpx-digest"
        );
    }
}
