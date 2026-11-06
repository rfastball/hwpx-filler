//! Shipping defaults resolve raw AUTO/EXACT intent without a store or clock.

use crate::canonical_execution_encoding::CANONICAL_ENCODING_VERSION;
use crate::execution_capture::{MATERIALIZATION_BASE_CONTRACT_ID, ResolvedSealPolicy};
use crate::execution_compilation::EXECUTION_SEMANTICS_CONTRACT;
use crate::execution_composition::{
    COMPOSITION_CONTRACT_ID, COMPOSITION_FINGERPRINT_HWPX, COMPOSITION_FINGERPRINT_TXT,
    NATIVE_PRIMITIVE_CONTRACT_ID, TXT_COMPOSITION_CONTRACT_ID, TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
};
use crate::execution_structure::TXT_EXECUTION_QUALIFICATION_PROFILE_ID;
use crate::field_binding::{BINDING_VALUE_VERSION, DOCUMENT_CONTENT_VALUE_POLICY_VERSION};
use crate::raw_data_record::{RAW_RECORD_CONTRACT_ID, RECORD_REVIEW_CONTRACT_ID};
use crate::seal_execution_plan::{
    SUPPORTED_PLAN_SCHEMAS, SealExecutionPlanCommand, WorkExecutionSummary,
};

pub const SHIPPING_POLICY_RESOLUTION_VERSION: &str = "policy/v1";
pub const SHIPPING_PLAN_SCHEMA_VERSION: &str = SUPPORTED_PLAN_SCHEMAS[0];
pub const SHIPPING_MATERIALIZATION_CONTRACT_ID: &str = "materialization/v1";
pub const RECORD_VALIDATION_CONTRACT_ID: &str = "record-validation/v1";

pub fn resolve_shipping_policy(
    command: &SealExecutionPlanCommand,
    observed: &WorkExecutionSummary,
) -> ResolvedSealPolicy {
    let (composition, primitive, fingerprint) =
        if observed.qualification_profile_id == TXT_EXECUTION_QUALIFICATION_PROFILE_ID {
            (
                TXT_COMPOSITION_CONTRACT_ID,
                TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                COMPOSITION_FINGERPRINT_TXT,
            )
        } else {
            (
                COMPOSITION_CONTRACT_ID,
                NATIVE_PRIMITIVE_CONTRACT_ID,
                COMPOSITION_FINGERPRINT_HWPX,
            )
        };
    ResolvedSealPolicy {
        policy_resolution_version: SHIPPING_POLICY_RESOLUTION_VERSION.into(),
        execution_base_kind: command.requested_execution_base_kind.clone(),
        execution_semantic_contract_id: command
            .requested_execution_semantic_contract
            .selected(EXECUTION_SEMANTICS_CONTRACT)
            .into(),
        binding_value_contract_id: BINDING_VALUE_VERSION.into(),
        raw_record_contract_id: RAW_RECORD_CONTRACT_ID.into(),
        document_value_resolution_contract_id: DOCUMENT_CONTENT_VALUE_POLICY_VERSION.into(),
        record_validation_contract_id: RECORD_VALIDATION_CONTRACT_ID.into(),
        record_review_contract_id: RECORD_REVIEW_CONTRACT_ID.into(),
        composition_contract_id: composition.into(),
        native_primitive_contract_id: primitive.into(),
        materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
        composition_theorem_evidence_manifest_digest: fingerprint.into(),
        materialization_contract_id: SHIPPING_MATERIALIZATION_CONTRACT_ID.into(),
        plan_schema_version: command
            .requested_plan_schema
            .selected(SHIPPING_PLAN_SCHEMA_VERSION)
            .into(),
        canonical_encoding_version: command
            .requested_canonical_encoding
            .selected(CANONICAL_ENCODING_VERSION)
            .into(),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::stored_execution_plan::RequestedVersionSelector;

    #[test]
    fn shipping_policy_uses_only_profile_media_and_exact_selectors() {
        let mut command = SealExecutionPlanCommand::new("workspace", "work", "request").unwrap();
        command.requested_plan_schema = RequestedVersionSelector::exact("future/v3").unwrap();
        command.requested_execution_semantic_contract =
            RequestedVersionSelector::exact("custom-exec/v9").unwrap();
        command.requested_canonical_encoding =
            RequestedVersionSelector::exact("custom-encoding/v9").unwrap();
        let hwpx = resolve_shipping_policy(
            &command,
            &WorkExecutionSummary {
                qualification_profile_id: "hwpx-template-qualification-v4".into(),
                template_application_id: "a".into(),
            },
        );
        let txt = resolve_shipping_policy(
            &command,
            &WorkExecutionSummary {
                qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into(),
                template_application_id: "a".into(),
            },
        );
        assert_eq!(hwpx.plan_schema_version, "future/v3");
        assert_eq!(hwpx.execution_semantic_contract_id, "custom-exec/v9");
        assert_eq!(txt.execution_semantic_contract_id, "custom-exec/v9");
        assert_eq!(hwpx.canonical_encoding_version, "custom-encoding/v9");
        assert_eq!(txt.canonical_encoding_version, "custom-encoding/v9");
        assert_eq!(txt.plan_schema_version, "future/v3");
        assert_eq!(hwpx.composition_contract_id, COMPOSITION_CONTRACT_ID);
        assert_eq!(txt.composition_contract_id, TXT_COMPOSITION_CONTRACT_ID);
        assert_eq!(
            txt.composition_theorem_evidence_manifest_digest,
            COMPOSITION_FINGERPRINT_TXT
        );
    }
}
