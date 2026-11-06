//! Digest-bound, in-memory production materialization for HWPX and TXT.

use crate::execution_composition::TXT_NATIVE_PRIMITIVE_CONTRACT_ID;
use crate::execution_contract_set::{SealedExecutionPlanSemanticPayload, plan_semantic_digest};
use crate::execution_structure::{ExecutionTemplateStructure, template_structure_digest};
use crate::field_binding::{
    ESCAPING_NATIVE_MATERIALIZER, ESCAPING_PLAINTEXT_MATERIALIZER, resolve_document_value_policy,
};
use crate::fields::FillNote;
use crate::materialization_conformance::{
    ConformanceResult, NativePlanView, apply_execution_operations_in_memory,
    apply_execution_plan_in_memory, digest, verify_materialization_postconditions,
    verify_materialization_postconditions_parts, verify_structure_bytes_consistency,
};
use crate::record_validation::{ValidatedDataRecord, verify_validated_record_completeness};
use crate::text_materialization_conformance::{
    TxtExecutionOutcome, apply_txt_execution_plan_in_memory,
    verify_txt_materialization_postconditions, verify_txt_structure_bytes_consistency,
};
use crate::text_render::python_repr;
use serde_json::Value;
use std::collections::HashMap;
use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RunnerErrorKind {
    InvalidRecord,
    EscapingResponsibility,
    ValuePolicy,
    UnsupportedNativePrimitive,
    Procurement,
    Execution,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunnerError {
    pub kind: RunnerErrorKind,
    pub detail: String,
}
impl fmt::Display for RunnerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for RunnerError {}
fn error(kind: RunnerErrorKind, detail: impl Into<String>) -> RunnerError {
    RunnerError {
        kind,
        detail: detail.into(),
    }
}
fn repr(text: &str) -> String {
    python_repr(&Value::String(text.into()))
}

pub struct MaterializationInput<'a> {
    plan: &'a SealedExecutionPlanSemanticPayload,
    record: &'a ValidatedDataRecord,
    plan_ref: String,
}
impl<'a> MaterializationInput<'a> {
    pub fn new(
        plan: &'a SealedExecutionPlanSemanticPayload,
        record: &'a ValidatedDataRecord,
    ) -> Result<Self, RunnerError> {
        verify_validated_record_completeness(record, plan)
            .map_err(|e| error(RunnerErrorKind::InvalidRecord, e.to_string()))?;
        let plan_ref = plan_semantic_digest(plan)
            .map_err(|e| error(RunnerErrorKind::InvalidRecord, e.to_string()))?;
        Ok(Self {
            plan,
            record,
            plan_ref,
        })
    }
    pub fn plan(&self) -> &SealedExecutionPlanSemanticPayload {
        self.plan
    }
    pub fn record(&self) -> &ValidatedDataRecord {
        self.record
    }
    pub fn sealed_execution_plan_ref(&self) -> &str {
        &self.plan_ref
    }
    pub fn validated_record_ref(&self) -> &str {
        &self.record.validated_record_digest
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MaterializedDocumentBytes {
    pub plan_semantic_digest: String,
    pub validated_record_ref: String,
    pub output_bytes: Vec<u8>,
    pub output_digest: String,
    pub execution_notes: Vec<FillNote>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MaterializationOutcome {
    Materialized(MaterializedDocumentBytes),
    Failure(ConformanceResult),
}
fn finish(
    input: &MaterializationInput<'_>,
    output_bytes: Vec<u8>,
    verdict: ConformanceResult,
) -> MaterializationOutcome {
    match verdict {
        ConformanceResult::Failure { .. } => MaterializationOutcome::Failure(verdict),
        ConformanceResult::Pass {
            output_digest,
            notes,
        } => MaterializationOutcome::Materialized(MaterializedDocumentBytes {
            plan_semantic_digest: input.plan_ref.clone(),
            validated_record_ref: input.record.validated_record_digest.clone(),
            output_bytes,
            output_digest,
            execution_notes: notes,
        }),
    }
}
fn escaping_gate(
    plan: &SealedExecutionPlanSemanticPayload,
    wanted: &str,
) -> Result<(), RunnerError> {
    for requirement in &plan.active_field_requirements {
        let field = python_repr(requirement.get("field_id").unwrap_or(&Value::Null));
        let Some(expression) = requirement
            .get("value_expression")
            .and_then(Value::as_object)
        else {
            return Err(error(
                RunnerErrorKind::EscapingResponsibility,
                format!("requirement {field} 에 value_expression 이 없다"),
            ));
        };
        if expression.get("kind").and_then(Value::as_str) == Some("INTENTIONAL_BLANK") {
            continue;
        }
        let policy_id = expression
            .get("document_content_value_policy_id")
            .and_then(Value::as_str)
            .unwrap_or("None");
        let policy = resolve_document_value_policy(policy_id)
            .map_err(|e| error(RunnerErrorKind::ValuePolicy, e.to_string()))?;
        if policy.escaping_responsibility != wanted {
            let owner = if wanted == ESCAPING_PLAINTEXT_MATERIALIZER {
                "TXT materializer"
            } else {
                "이 materializer"
            };
            return Err(error(
                RunnerErrorKind::EscapingResponsibility,
                format!(
                    "값 정책 {} 의 escaping 책임 {} 는 {owner} 소유가 아니다",
                    repr(&policy.policy_id),
                    repr(&policy.escaping_responsibility)
                ),
            ));
        }
    }
    Ok(())
}
pub fn require_native_materializer_escaping(
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<(), RunnerError> {
    escaping_gate(plan, ESCAPING_NATIVE_MATERIALIZER)
}
pub fn require_plaintext_materializer_escaping(
    plan: &SealedExecutionPlanSemanticPayload,
) -> Result<(), RunnerError> {
    escaping_gate(plan, ESCAPING_PLAINTEXT_MATERIALIZER)
}
fn procure<C, S>(
    input: &MaterializationInput<'_>,
    candidate_blob_resolver: &C,
    structure_resolver: &S,
) -> Result<(Vec<u8>, ExecutionTemplateStructure), RunnerError>
where
    C: Fn(&str) -> Result<Vec<u8>, String>,
    S: Fn(&SealedExecutionPlanSemanticPayload) -> Result<ExecutionTemplateStructure, String>,
{
    let wanted_blob = &input.plan.execution_basis.template.exact_content_digest;
    let candidate =
        candidate_blob_resolver(wanted_blob).map_err(|e| error(RunnerErrorKind::Procurement, e))?;
    if digest(&candidate) != *wanted_blob {
        return Err(error(
            RunnerErrorKind::Procurement,
            format!("조달한 candidate bytes 의 digest 가 Plan 과 불일치: 기대 {wanted_blob}"),
        ));
    }
    let wanted_structure = &input
        .plan
        .execution_basis
        .selection
        .template_structure_digest;
    let structure =
        structure_resolver(input.plan).map_err(|e| error(RunnerErrorKind::Procurement, e))?;
    if template_structure_digest(&structure) != *wanted_structure {
        return Err(error(
            RunnerErrorKind::Procurement,
            format!("조달한 structure 의 digest 가 Plan 과 불일치: 기대 {wanted_structure}"),
        ));
    }
    Ok((candidate, structure))
}
fn document_values(
    input: &MaterializationInput<'_>,
) -> Result<HashMap<String, String>, RunnerError> {
    Ok(input
        .record
        .document_values_in_order()
        .map_err(|e| error(RunnerErrorKind::InvalidRecord, e.to_string()))?
        .into_iter()
        .collect())
}

pub fn materialize_hwpx<C, S>(
    input: &MaterializationInput<'_>,
    candidate_blob_resolver: C,
    structure_resolver: S,
) -> Result<MaterializationOutcome, RunnerError>
where
    C: Fn(&str) -> Result<Vec<u8>, String>,
    S: Fn(&SealedExecutionPlanSemanticPayload) -> Result<ExecutionTemplateStructure, String>,
{
    require_native_materializer_escaping(input.plan)?;
    let (candidate, structure) = procure(input, &candidate_blob_resolver, &structure_resolver)?;
    let precheck = verify_structure_bytes_consistency(&candidate, &structure);
    if matches!(precheck, ConformanceResult::Failure { .. }) {
        return Ok(MaterializationOutcome::Failure(precheck));
    }
    let values = document_values(input)?;
    let applied = apply_execution_plan_in_memory(&candidate, input.plan, &values)
        .map_err(|e| error(RunnerErrorKind::Execution, e.to_string()))?;
    let verdict = verify_materialization_postconditions(
        &candidate,
        &applied.output_bytes,
        input.plan,
        &structure,
        &values,
        &applied.notes,
    )
    .map_err(|e| error(RunnerErrorKind::Execution, e.to_string()))?;
    Ok(finish(input, applied.output_bytes, verdict))
}

pub fn materialize_txt<C, S>(
    input: &MaterializationInput<'_>,
    candidate_blob_resolver: C,
    structure_resolver: S,
) -> Result<MaterializationOutcome, RunnerError>
where
    C: Fn(&str) -> Result<Vec<u8>, String>,
    S: Fn(&SealedExecutionPlanSemanticPayload) -> Result<ExecutionTemplateStructure, String>,
{
    let native = &input
        .plan
        .execution_basis
        .contracts
        .roles
        .native_primitive_contract_id;
    if native != TXT_NATIVE_PRIMITIVE_CONTRACT_ID {
        return Err(error(
            RunnerErrorKind::UnsupportedNativePrimitive,
            format!(
                "TXT materializer 가 실행할 수 없는 native primitive contract: {}",
                repr(native)
            ),
        ));
    }
    require_plaintext_materializer_escaping(input.plan)?;
    let (candidate, structure) = procure(input, &candidate_blob_resolver, &structure_resolver)?;
    let precheck = verify_txt_structure_bytes_consistency(&candidate, &structure);
    if matches!(precheck, ConformanceResult::Failure { .. }) {
        return Ok(MaterializationOutcome::Failure(precheck));
    }
    let values = document_values(input)?;
    let applied = apply_txt_execution_plan_in_memory(&candidate, input.plan, &structure, &values)
        .map_err(|e| error(RunnerErrorKind::Execution, e.to_string()))?;
    let applied = match applied {
        TxtExecutionOutcome::Materialized(applied) => applied,
        TxtExecutionOutcome::Failure(result) => return Ok(MaterializationOutcome::Failure(result)),
    };
    let verdict = verify_txt_materialization_postconditions(
        &candidate,
        &applied.output_bytes,
        input.plan,
        &structure,
        &values,
        Some(&applied.stage_facts),
    )
    .map_err(|e| error(RunnerErrorKind::Execution, e.to_string()))?;
    Ok(finish(input, applied.output_bytes, verdict))
}

/// Authoring preview uses the production HWPX executor and verifier without claiming a sealed Plan.
pub fn materialize_authoring_trial(
    source_bytes: &[u8],
    structure: &ExecutionTemplateStructure,
    ordered_operations: &[Value],
    active_field_requirements: &[Value],
    document_values: &HashMap<String, String>,
) -> Result<MaterializationOutcome, RunnerError> {
    let precheck = verify_structure_bytes_consistency(source_bytes, structure);
    if matches!(precheck, ConformanceResult::Failure { .. }) {
        return Ok(MaterializationOutcome::Failure(precheck));
    }
    let applied =
        apply_execution_operations_in_memory(source_bytes, ordered_operations, document_values)
            .map_err(|e| error(RunnerErrorKind::Execution, e.to_string()))?;
    let verdict = verify_materialization_postconditions_parts(
        source_bytes,
        &applied.output_bytes,
        NativePlanView {
            native_primitive_contract_id:
                crate::execution_composition::NATIVE_PRIMITIVE_CONTRACT_ID,
            ordered_operations,
            active_field_requirements,
        },
        structure,
        document_values,
        &applied.notes,
    )
    .map_err(|e| error(RunnerErrorKind::Execution, e.to_string()))?;
    Ok(match verdict {
        ConformanceResult::Failure { .. } => MaterializationOutcome::Failure(verdict),
        ConformanceResult::Pass {
            output_digest,
            notes,
        } => MaterializationOutcome::Materialized(MaterializedDocumentBytes {
            plan_semantic_digest: String::new(),
            validated_record_ref: String::new(),
            output_bytes: applied.output_bytes,
            output_digest,
            execution_notes: notes,
        }),
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_capture::{EffectiveSelectionBasis, ExactTemplateExecutionBasis};
    use crate::execution_compilation::EffectiveFieldBindingBasis;
    use crate::execution_contract_set::{ContractRoles, ExecutionBasis, ExecutionContractSet};
    use crate::record_validation::ValidationProvenance;
    use crate::text_template_inspection::inspect_txt_qualification;
    use hwpx_core::package::{HwpxPackage, MIMETYPE_VALUE, PackageEntry};
    use serde_json::json;

    fn case() -> (
        SealedExecutionPlanSemanticPayload,
        ValidatedDataRecord,
        ExecutionTemplateStructure,
    ) {
        let source = b"plain\n";
        let structure = inspect_txt_qualification(source)
            .unwrap()
            .execution_structure
            .unwrap();
        let roles = ContractRoles {
            slot_selection_contract_id: String::new(),
            field_binding_contract_id: String::new(),
            source_schema_contract_id: String::new(),
            raw_record_contract_id: String::new(),
            execution_semantic_contract_id: String::new(),
            binding_value_contract_id: String::new(),
            document_value_resolution_contract_id: String::new(),
            record_validation_contract_id: String::new(),
            record_review_contract_id: String::new(),
            composition_contract_id: String::new(),
            native_primitive_contract_id: TXT_NATIVE_PRIMITIVE_CONTRACT_ID.into(),
            materialization_base_contract_id: String::new(),
            materialization_contract_id: String::new(),
            composition_theorem_evidence_manifest_digest: String::new(),
        };
        let plan = SealedExecutionPlanSemanticPayload {
            plan_schema_version: String::new(),
            canonical_encoding_version: String::new(),
            execution_basis: ExecutionBasis {
                workspace_instance_id: String::new(),
                work_authority_id: String::new(),
                qualification_profile_semantic_digest: String::new(),
                template: ExactTemplateExecutionBasis {
                    execution_base_kind: String::new(),
                    materialization_base_contract_id: String::new(),
                    work_authority_id: String::new(),
                    template_application_id: String::new(),
                    exact_content_digest: digest(source),
                    canonical_blob_reference: String::new(),
                },
                contracts: ExecutionContractSet {
                    roles,
                    contract_set_schema_version: String::new(),
                    contract_set_manifest_digest: String::new(),
                },
                selection: EffectiveSelectionBasis {
                    slot_mode: String::new(),
                    work_id: String::new(),
                    template_application_id: String::new(),
                    selection_semantic_contract_id: String::new(),
                    template_structure_digest: template_structure_digest(&structure),
                    effective_selection_digest: None,
                    declared_selection_digest: None,
                },
                field_binding: EffectiveFieldBindingBasis {
                    effective_active_binding_rules: Vec::new(),
                    active_binding_digest: String::new(),
                    required_source_keys: Vec::new(),
                    required_source_key_set_digest: String::new(),
                },
            },
            active_field_requirements: Vec::new(),
            ordered_operations: Vec::new(),
        };
        let record = ValidatedDataRecord {
            validated_record_digest: "record-ref".into(),
            semantic_payload_encoded: json!({"resolved_requirement_values":[]}),
            validation_provenance: ValidationProvenance {
                validation_facts: Vec::new(),
                record_review_evidence_refs: Vec::new(),
                validated_at: String::new(),
                source_value_provenance: Vec::new(),
            },
        };
        (plan, record, structure)
    }

    #[test]
    fn txt_runner_separates_procurement_failure_and_qualified_bytes() {
        let (mut plan, record, structure) = case();
        let input = MaterializationInput {
            plan: &plan,
            record: &record,
            plan_ref: "plan-ref".into(),
        };
        let result = materialize_txt(
            &input,
            |_| Ok(b"other\n".to_vec()),
            |_| Ok(structure.clone()),
        );
        assert_eq!(result.unwrap_err().kind, RunnerErrorKind::Procurement);
        let outcome = materialize_txt(
            &input,
            |_| Ok(b"plain\n".to_vec()),
            |_| Ok(structure.clone()),
        )
        .unwrap();
        let MaterializationOutcome::Materialized(bytes) = outcome else {
            panic!("valid candidate must yield bytes");
        };
        assert_eq!(bytes.output_bytes, b"plain\n");
        assert_eq!(bytes.output_digest, digest(&bytes.output_bytes));
        assert_eq!(bytes.plan_semantic_digest, "plan-ref");
        assert_eq!(bytes.validated_record_ref, "record-ref");
        assert!(bytes.execution_notes.is_empty());

        let failed = ConformanceResult::Failure {
            code: "REPARSE_FAILED",
            detail: "주입".into(),
        };
        assert_eq!(
            finish(&input, b"untrusted".to_vec(), failed.clone()),
            MaterializationOutcome::Failure(failed)
        );

        plan.active_field_requirements = vec![json!({"field_id":"F",
            "expected_active_occurrence_count":1,
            "value_expression":{"kind":"INTENTIONAL_BLANK"}})];
        let input = MaterializationInput {
            plan: &plan,
            record: &record,
            plan_ref: "plan-ref".into(),
        };
        let outcome = materialize_txt(
            &input,
            |_| Ok(b"plain\n".to_vec()),
            |_| Ok(structure.clone()),
        )
        .unwrap();
        assert!(matches!(
            outcome,
            MaterializationOutcome::Failure(ConformanceResult::Failure {
                code: crate::materialization_conformance::OCCURRENCE_COUNT_MISMATCH,
                ..
            })
        ));
    }

    #[test]
    fn txt_runner_checks_media_escaping_and_both_procurement_digests_before_execution() {
        let (plan, record, structure) = case();
        let run = |plan: &SealedExecutionPlanSemanticPayload,
                   record: &ValidatedDataRecord,
                   bytes: &[u8],
                   structure: &ExecutionTemplateStructure| {
            materialize_txt(
                &MaterializationInput {
                    plan,
                    record,
                    plan_ref: "plan-ref".into(),
                },
                |_| Ok(bytes.to_vec()),
                |_| Ok(structure.clone()),
            )
        };
        let field = |policy: &str| {
            json!({"field_id":"F", "expected_active_occurrence_count":1,
            "value_expression":{"kind":"FROM_SOURCE", "source_key":"column", "document_content_value_policy_id":policy}})
        };
        for (native, requirement, expected) in [
            (
                "hwpx-native-primitive/v1",
                None,
                RunnerErrorKind::UnsupportedNativePrimitive,
            ),
            (
                TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                Some(field("document-content-value/v1")),
                RunnerErrorKind::EscapingResponsibility,
            ),
            (
                TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                Some(json!({"field_id":"F"})),
                RunnerErrorKind::EscapingResponsibility,
            ),
            (
                TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                Some(field("unknown")),
                RunnerErrorKind::ValuePolicy,
            ),
        ] {
            let mut plan = plan.clone();
            plan.execution_basis
                .contracts
                .roles
                .native_primitive_contract_id = native.into();
            plan.active_field_requirements = requirement.into_iter().collect();
            let result = materialize_txt(
                &MaterializationInput {
                    plan: &plan,
                    record: &record,
                    plan_ref: "plan-ref".into(),
                },
                |_| panic!("invalid contract read candidate"),
                |_| panic!("invalid contract read structure"),
            );
            assert_eq!(result.unwrap_err().kind, expected);
        }
        let mut changed = plan.clone();
        changed.execution_basis.selection.template_structure_digest = "sha256:other".into();
        assert_eq!(
            run(&changed, &record, b"plain\n", &structure)
                .unwrap_err()
                .kind,
            RunnerErrorKind::Procurement
        );
        let input = MaterializationInput {
            plan: &plan,
            record: &record,
            plan_ref: "plan-ref".into(),
        };
        let missing = materialize_txt(
            &input,
            |_| Err("blob unavailable".into()),
            |_| panic!("blob failure read structure"),
        )
        .unwrap_err();
        assert_eq!(missing.kind, RunnerErrorKind::Procurement);
        assert_eq!(missing.detail, "blob unavailable");
        let missing = materialize_txt(
            &input,
            |_| Ok(b"plain\n".to_vec()),
            |_| Err("structure unavailable".into()),
        )
        .unwrap_err();
        assert_eq!(missing.kind, RunnerErrorKind::Procurement);
        assert_eq!(missing.detail, "structure unavailable");

        let source = b"name: {{F}}\n";
        let projected = inspect_txt_qualification(source)
            .unwrap()
            .execution_structure
            .unwrap();
        changed.execution_basis.selection.template_structure_digest =
            template_structure_digest(&projected);
        let MaterializationOutcome::Failure(ConformanceResult::Failure { code, .. }) =
            run(&changed, &record, b"plain\n", &projected).unwrap()
        else {
            panic!("inconsistent structure accepted")
        };
        assert_eq!(code, "STRUCTURE_BYTES_INCONSISTENT");
        changed.execution_basis.template.exact_content_digest = digest(source);
        changed.active_field_requirements = vec![field("document-content-value/txt-v1")];
        changed.ordered_operations = vec![json!({"op":"APPLY_FIELD_BINDING", "field_id":"F"})];
        let mut record = record;
        for (value, expression) in [
            ("<>&한글", field("document-content-value/txt-v1")),
            (
                "",
                json!({"field_id":"F", "expected_active_occurrence_count":1,"value_expression":{"kind":"INTENTIONAL_BLANK"}}),
            ),
        ] {
            changed.active_field_requirements = vec![expression];
            record.semantic_payload_encoded =
                json!({"resolved_requirement_values":[{"field_id":"F","document_value":value}]});
            let MaterializationOutcome::Materialized(bytes) =
                run(&changed, &record, source, &projected).unwrap()
            else {
                panic!("valid TXT refused")
            };
            assert_eq!(bytes.output_bytes, format!("name: {value}\n").as_bytes());
            assert_eq!(bytes.output_digest, digest(&bytes.output_bytes));
        }
        record.semantic_payload_encoded = json!({"resolved_requirement_values":null});
        assert_eq!(
            run(&changed, &record, source, &projected).unwrap_err().kind,
            RunnerErrorKind::InvalidRecord
        );
        record.semantic_payload_encoded = json!({"resolved_requirement_values":[]});
        assert_eq!(
            run(&changed, &record, source, &projected).unwrap_err().kind,
            RunnerErrorKind::Execution
        );
    }

    #[test]
    fn hwpx_runner_rechecks_procured_bytes_and_structure_before_execution() {
        let package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "mimetype".into(),
                    data: MIMETYPE_VALUE.to_vec(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: b"<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'><hp:p><hp:run><hp:ctrl><hp:fieldBegin name='F'/></hp:ctrl><hp:t>old</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p></hs:sec>".to_vec(),
                    stored: false,
                },
            ],
        };
        let source = package.to_bytes().unwrap();
        let structure = crate::hwpx_qualification::inspect_hwpx_qualification(&source)
            .unwrap()
            .execution_structure
            .unwrap();
        let (mut plan, record, _) = case();
        plan.execution_basis
            .contracts
            .roles
            .native_primitive_contract_id =
            crate::execution_composition::NATIVE_PRIMITIVE_CONTRACT_ID.into();
        plan.execution_basis.template.exact_content_digest = digest(&source);
        plan.execution_basis.selection.template_structure_digest =
            template_structure_digest(&structure);
        let input = MaterializationInput {
            plan: &plan,
            record: &record,
            plan_ref: "sealed-plan".into(),
        };
        let run = |bytes: &[u8], observed: &ExecutionTemplateStructure| {
            materialize_hwpx(&input, |_| Ok(bytes.to_vec()), |_| Ok(observed.clone()))
        };
        let original = source.clone();
        let MaterializationOutcome::Materialized(output) = run(&source, &structure).unwrap() else {
            panic!("qualified HWPX candidate refused")
        };
        assert_eq!(source, original);
        assert_eq!(output.output_bytes, source);
        assert_eq!(output.output_digest, digest(&source));
        assert_eq!(output.plan_semantic_digest, "sealed-plan");
        assert_eq!(output.validated_record_ref, record.validated_record_digest);
        assert_eq!(
            run(b"different", &structure).unwrap_err().kind,
            RunnerErrorKind::Procurement
        );
        let mut altered = structure.clone();
        altered.field_occurrences[0].field_id = "wrong".into();
        assert_eq!(
            run(&source, &altered).unwrap_err().kind,
            RunnerErrorKind::Procurement
        );
        let mut lying_plan = plan.clone();
        lying_plan
            .execution_basis
            .selection
            .template_structure_digest = template_structure_digest(&altered);
        let lying_input = MaterializationInput {
            plan: &lying_plan,
            record: &record,
            plan_ref: "sealed-plan".into(),
        };
        assert!(matches!(
            materialize_hwpx(
                &lying_input,
                |_| Ok(source.clone()),
                |_| Ok(altered.clone()),
            )
            .unwrap(),
            MaterializationOutcome::Failure(ConformanceResult::Failure {
                code: crate::materialization_conformance::STRUCTURE_BYTES_INCONSISTENT,
                ..
            })
        ));
    }
}
