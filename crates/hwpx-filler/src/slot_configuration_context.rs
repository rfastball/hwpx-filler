//! Resolve a current Work application to its exact historical qualification chain.
//! This module only reads injected immutable records; it never reparses a source template.

use crate::candidate_revision::TemplateRevision;
use crate::execution_structure::{
    LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, QualificationProfileManifest,
    TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, TemplateStructure,
};
use crate::qualification_evidence::{PASS, QualificationEvidence};
use crate::slot_selection::{
    SelectionSemanticBindingKey, SelectionSemanticContractManifest,
    SelectionSemanticContractRegistry, default_selection_semantic_registry,
};
use crate::work_template_state::WorkTemplateStateAggregate;
use serde_json::Value;
use std::fmt;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContextErrorKind {
    Read,
    TemplateInitializationRequired,
    StaleTemplateApplication,
    UnsupportedTemplateStructureProjection,
    TemplateStructureIntegrity,
    AppliedTemplateContentIntegrity,
    CrossWork,
    UnsupportedSelectionContract,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContextError {
    pub kind: ContextErrorKind,
    pub detail: String,
}
impl fmt::Display for ContextError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for ContextError {}
fn error(kind: ContextErrorKind, detail: impl Into<String>) -> ContextError {
    ContextError {
        kind,
        detail: detail.into(),
    }
}
fn integrity(detail: impl Into<String>) -> ContextError {
    error(ContextErrorKind::TemplateStructureIntegrity, detail)
}

pub trait WorkTemplateStateReadPort {
    fn load(&self, work_id: &str) -> Result<Option<WorkTemplateStateAggregate>, String>;
}
pub trait QualificationReadPort {
    fn get_evidence(&self, id: &str) -> Result<QualificationEvidence, String>;
    fn get_manifest(&self, id: &str) -> Result<QualificationProfileManifest, String>;
}
pub trait AppliedCandidateReadPort {
    fn get_revision(&self, id: &str) -> Result<TemplateRevision, String>;
    fn has_blob(&self, digest: &str) -> Result<bool, String>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotConfigurationContext {
    pub workspace_instance_id: String,
    pub work_id: String,
    pub template_application_id: String,
    pub template_lineage_id: String,
    pub application_epoch: i64,
    pub pass_evidence_id: String,
    pub revision_id: String,
    pub qualification_profile_id: String,
    pub structure_projection_schema_version: String,
    pub template_structure: TemplateStructure,
    pub template_structure_digest: String,
    pub selection_semantic_contract_id: String,
    pub selection_semantic_contract: SelectionSemanticContractManifest,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExactAppliedTemplateInput {
    pub work_id: String,
    pub template_application_id: String,
    pub revision_id: String,
    pub media: String,
    pub template_lineage_id: String,
    pub exact_content_digest: String,
    pub canonical_blob_reference: String,
}

struct VerifiedChain {
    aggregate: WorkTemplateStateAggregate,
    application_id: String,
    application_epoch: i64,
    evidence: QualificationEvidence,
    revision: TemplateRevision,
}
fn chain(
    state: &impl WorkTemplateStateReadPort,
    qualification: &impl QualificationReadPort,
    candidate: &impl AppliedCandidateReadPort,
    expected_work_id: &str,
    expected_application_id: Option<&str>,
) -> Result<VerifiedChain, ContextError> {
    let aggregate = state
        .load(expected_work_id)
        .map_err(|e| error(ContextErrorKind::Read, e))?
        .ok_or_else(|| {
            error(
                ContextErrorKind::TemplateInitializationRequired,
                format!("work {expected_work_id} 는 template application 이 없다"),
            )
        })?;
    let work = &aggregate.work;
    if work.work_id != expected_work_id {
        return Err(error(
            ContextErrorKind::CrossWork,
            "aggregate work_id 가 요청 WorkAuthorityId 와 불일치",
        ));
    }
    let current = work.current_template_application_id.clone();
    if current.is_empty() {
        return Err(error(
            ContextErrorKind::TemplateInitializationRequired,
            "current template application 부재",
        ));
    }
    if expected_application_id.is_some_and(|expected| expected != current) {
        return Err(error(
            ContextErrorKind::StaleTemplateApplication,
            format!(
                "요청 Application {} 는 current({current}) 가 아니다",
                expected_application_id.unwrap_or_default()
            ),
        ));
    }
    let application = aggregate
        .applications
        .iter()
        .find(|app| app.application_id == current)
        .ok_or_else(|| integrity("current pointer 가 applications 에 없다"))?;
    if application.work_id != expected_work_id {
        return Err(error(
            ContextErrorKind::CrossWork,
            "Application.work_id 가 요청 WorkAuthorityId 와 불일치",
        ));
    }
    let application_epoch = application.application_epoch;
    let evidence = qualification
        .get_evidence(&application.pass_evidence_id)
        .map_err(|e| error(ContextErrorKind::Read, e))?;
    if evidence.evidence_id != application.pass_evidence_id {
        return Err(integrity("Evidence id 가 Application 참조와 불일치"));
    }
    if evidence.result != PASS {
        return Err(integrity(
            "current Application 의 Evidence 가 PASS 가 아니다",
        ));
    }
    let projection = evidence
        .structure_projection
        .as_ref()
        .ok_or_else(|| integrity("PASS Evidence 에 structure projection 부재"))?;
    let revision = candidate
        .get_revision(&evidence.revision_id)
        .map_err(|e| error(ContextErrorKind::Read, e))?;
    if revision.revision_id != evidence.revision_id {
        return Err(integrity("Revision id 가 Evidence 참조와 불일치"));
    }
    if revision.template_lineage_id != work.template_lineage_id {
        return Err(integrity("Revision lineage 가 Work lineage 와 불일치"));
    }
    let manifest = qualification
        .get_manifest(&evidence.qualification_profile_id)
        .map_err(|e| error(ContextErrorKind::Read, e))?;
    if manifest.qualification_profile_id != evidence.qualification_profile_id {
        return Err(integrity("Manifest profile 이 Evidence 와 불일치"));
    }
    if manifest.media != revision.media {
        return Err(integrity("Manifest media 가 Revision media 와 불일치"));
    }
    if manifest.projection_schema_version != projection.projection_schema_version {
        return Err(integrity(
            "Manifest projection schema 가 Evidence projection schema 와 불일치",
        ));
    }
    Ok(VerifiedChain {
        aggregate,
        application_id: current,
        application_epoch,
        evidence,
        revision,
    })
}

pub fn decode_product_structure(
    schema: &str,
    payload: &Value,
) -> Result<TemplateStructure, ContextError> {
    if ![
        LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    ]
    .contains(&schema)
    {
        return Err(error(
            ContextErrorKind::UnsupportedTemplateStructureProjection,
            format!("미지원 structure projection schema: {schema}"),
        ));
    }
    let product = payload
        .get("product_structure")
        .and_then(Value::as_object)
        .ok_or_else(|| {
            integrity(if schema == TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA {
                "txt-v1 projection payload 에 product_structure 매핑이 없다"
            } else {
                "v4 projection payload 에 product_structure 매핑이 없다"
            })
        })?;
    // Typed deserialization keeps missing labels/fields and wrong list/scalar shapes closed.
    serde_json::from_value(Value::Object(product.clone())).map_err(|_| {
        integrity(format!(
            "structure projection payload 가 {schema} 형식과 불일치"
        ))
    })
}

pub struct ContextPorts<'a, W, Q, C> {
    pub work_state: &'a W,
    pub qualification: &'a Q,
    pub candidate: &'a C,
}
pub fn resolve_slot_configuration_context<W, Q, C>(
    ports: ContextPorts<'_, W, Q, C>,
    workspace_instance_id: &str,
    expected_work_id: &str,
    expected_application_id: Option<&str>,
    registry: Option<&SelectionSemanticContractRegistry>,
) -> Result<SlotConfigurationContext, ContextError>
where
    W: WorkTemplateStateReadPort,
    Q: QualificationReadPort,
    C: AppliedCandidateReadPort,
{
    let chain = chain(
        ports.work_state,
        ports.qualification,
        ports.candidate,
        expected_work_id,
        expected_application_id,
    )?;
    let projection = chain
        .evidence
        .structure_projection
        .as_ref()
        .expect("PASS chain has projection");
    let schema = &projection.projection_schema_version;
    let structure = decode_product_structure(schema, &projection.payload)?;
    let fallback = default_selection_semantic_registry();
    let registry = registry.unwrap_or(&fallback);
    let key = SelectionSemanticBindingKey {
        qualification_profile_id: chain.evidence.qualification_profile_id.clone(),
        structure_projection_schema_version: schema.clone(),
    };
    let contract = registry
        .resolve(&key)
        .map_err(|e| error(ContextErrorKind::UnsupportedSelectionContract, e.detail))?
        .clone();
    Ok(SlotConfigurationContext {
        workspace_instance_id: workspace_instance_id.into(),
        work_id: chain.aggregate.work.work_id.clone(),
        template_application_id: chain.application_id,
        template_lineage_id: chain.aggregate.work.template_lineage_id.clone(),
        application_epoch: chain.application_epoch,
        pass_evidence_id: chain.evidence.evidence_id.clone(),
        revision_id: chain.evidence.revision_id.clone(),
        qualification_profile_id: chain.evidence.qualification_profile_id.clone(),
        structure_projection_schema_version: schema.clone(),
        template_structure: structure,
        template_structure_digest: projection.payload_digest.clone(),
        selection_semantic_contract_id: contract.contract_id.clone(),
        selection_semantic_contract: contract,
    })
}
pub fn resolve_exact_applied_template_input<W, Q, C>(
    ports: ContextPorts<'_, W, Q, C>,
    expected_work_id: &str,
    expected_application_id: &str,
) -> Result<ExactAppliedTemplateInput, ContextError>
where
    W: WorkTemplateStateReadPort,
    Q: QualificationReadPort,
    C: AppliedCandidateReadPort,
{
    let chain = chain(
        ports.work_state,
        ports.qualification,
        ports.candidate,
        expected_work_id,
        Some(expected_application_id),
    )?;
    if !ports
        .candidate
        .has_blob(&chain.revision.exact_content_digest)
        .map_err(|e| error(ContextErrorKind::Read, e))?
    {
        return Err(error(
            ContextErrorKind::AppliedTemplateContentIntegrity,
            format!(
                "applied Candidate blob 부재: {}",
                chain.revision.exact_content_digest
            ),
        ));
    }
    let digest = chain.revision.exact_content_digest;
    Ok(ExactAppliedTemplateInput {
        work_id: chain.aggregate.work.work_id.clone(),
        template_application_id: chain.application_id,
        revision_id: chain.revision.revision_id,
        media: chain.revision.media,
        template_lineage_id: chain.revision.template_lineage_id,
        canonical_blob_reference: digest.clone(),
        exact_content_digest: digest,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{StructureProjection, content_digest};
    use crate::qualification_evidence::{ManifestInput, build_manifest, project_structure};
    use crate::work_template_state::{
        DocumentWork, INITIALIZATION, SCHEMA_VERSION, WorkTemplateApplication,
    };
    use serde_json::json;

    #[derive(Clone)]
    struct Memory {
        aggregate: Option<WorkTemplateStateAggregate>,
        evidence: QualificationEvidence,
        manifest: QualificationProfileManifest,
        revision: TemplateRevision,
        blob: bool,
    }
    impl WorkTemplateStateReadPort for Memory {
        fn load(&self, _: &str) -> Result<Option<WorkTemplateStateAggregate>, String> {
            Ok(self.aggregate.clone())
        }
    }
    impl QualificationReadPort for Memory {
        fn get_evidence(&self, _: &str) -> Result<QualificationEvidence, String> {
            Ok(self.evidence.clone())
        }
        fn get_manifest(&self, _: &str) -> Result<QualificationProfileManifest, String> {
            Ok(self.manifest.clone())
        }
    }
    impl AppliedCandidateReadPort for Memory {
        fn get_revision(&self, _: &str) -> Result<TemplateRevision, String> {
            Ok(self.revision.clone())
        }
        fn has_blob(&self, _: &str) -> Result<bool, String> {
            Ok(self.blob)
        }
    }
    fn memory() -> Memory {
        let product = TemplateStructure::default();
        let flat = project_structure(&product, "hwpx-structure-projection-v3").unwrap();
        let payload = json!({"product_structure":flat.payload});
        let projection = StructureProjection {
            projection_schema_version: LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
            payload_digest: content_digest(&payload),
            payload,
        };
        let manifest_payload = json!({"x":1});
        Memory {
            aggregate: Some(WorkTemplateStateAggregate {
                schema_version: SCHEMA_VERSION.into(),
                aggregate_version: 1,
                work: DocumentWork {
                    work_id: "w1".into(),
                    template_lineage_id: "L1".into(),
                    current_template_application_id: "A1".into(),
                    current_template_preparation_id: None,
                    prepare_seq: 0,
                },
                applications: vec![WorkTemplateApplication {
                    application_id: "A1".into(),
                    work_id: "w1".into(),
                    application_epoch: 1,
                    pass_evidence_id: "E1".into(),
                    previous_application_id: None,
                    origin: INITIALIZATION.into(),
                    prepared_change_id: None,
                    actor: "tester".into(),
                    applied_at: "now".into(),
                }],
                preparations: vec![],
                prepared_changes: vec![],
            }),
            evidence: QualificationEvidence {
                evidence_id: "E1".into(),
                attempt_id: "AT1".into(),
                revision_id: "R1".into(),
                qualification_profile_id: "hwpx-template-qualification-v4".into(),
                result: PASS.into(),
                structure_projection: Some(projection),
                diagnostics: vec![],
                engine_metadata: Default::default(),
                qualified_at: "now".into(),
            },
            manifest: build_manifest(ManifestInput {
                qualification_profile_id: "hwpx-template-qualification-v4",
                media: "hwpx",
                adapter_contract_version: "a",
                product_rule_version: "p",
                operation_alphabet_version: "op",
                projection_schema_version: LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
                manifest_payload: &manifest_payload,
                created_at: "now",
            }),
            revision: TemplateRevision {
                revision_id: "R1".into(),
                template_lineage_id: "L1".into(),
                media: "hwpx".into(),
                exact_content_digest: "sha256:blob1".into(),
                origin_capture_observation_id: "O1".into(),
                created_at: "now".into(),
            },
            blob: true,
        }
    }
    fn ports(memory: &Memory) -> ContextPorts<'_, Memory, Memory, Memory> {
        ContextPorts {
            work_state: memory,
            qualification: memory,
            candidate: memory,
        }
    }
    #[test]
    fn exact_chain_and_fail_closed_boundaries() {
        let mut source = memory();
        let context =
            resolve_slot_configuration_context(ports(&source), "ws", "w1", Some("A1"), None)
                .unwrap();
        assert_eq!(context.selection_semantic_contract_id, "slot-selection/v1");
        assert_eq!(
            context.template_structure_digest,
            source
                .evidence
                .structure_projection
                .as_ref()
                .unwrap()
                .payload_digest
        );
        let applied = resolve_exact_applied_template_input(ports(&source), "w1", "A1").unwrap();
        assert_eq!(applied.canonical_blob_reference, "sha256:blob1");
        source.revision.template_lineage_id = "other".into();
        assert_eq!(
            resolve_exact_applied_template_input(ports(&source), "w1", "A1")
                .unwrap_err()
                .kind,
            ContextErrorKind::TemplateStructureIntegrity
        );
        source.revision.template_lineage_id = "L1".into();
        source.blob = false;
        assert_eq!(
            resolve_exact_applied_template_input(ports(&source), "w1", "A1")
                .unwrap_err()
                .kind,
            ContextErrorKind::AppliedTemplateContentIntegrity
        );
        source
            .evidence
            .structure_projection
            .as_mut()
            .unwrap()
            .projection_schema_version = "unknown-v9".into();
        source.manifest.projection_schema_version = "unknown-v9".into();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::UnsupportedTemplateStructureProjection
        );
    }

    #[test]
    fn missing_stale_and_cross_work_chains_never_resolve_to_current() {
        let mut source = memory();
        source.aggregate = None;
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::TemplateInitializationRequired
        );
        let mut source = memory();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", Some("A0"), None)
                .unwrap_err()
                .kind,
            ContextErrorKind::StaleTemplateApplication
        );
        source.aggregate.as_mut().unwrap().work.work_id = "other".into();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::CrossWork
        );
        let mut source = memory();
        source.evidence.result = "FAIL".into();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::TemplateStructureIntegrity
        );
        source.evidence.result = PASS.into();
        source.revision.revision_id = "R2".into();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::TemplateStructureIntegrity
        );
        source.revision.revision_id = "R1".into();
        source.manifest.media = "txt".into();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::TemplateStructureIntegrity
        );
    }

    #[test]
    fn txt_profile_resolves_only_with_its_projection_schema() {
        use crate::execution_structure::{
            TXT_EXECUTION_QUALIFICATION_PROFILE_ID, TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        };
        let mut source = memory();
        source.evidence.qualification_profile_id = TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into();
        source.manifest.qualification_profile_id = TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into();
        source.manifest.media = "txt".into();
        source.manifest.projection_schema_version =
            TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into();
        source.revision.media = "txt".into();
        source
            .evidence
            .structure_projection
            .as_mut()
            .unwrap()
            .projection_schema_version = TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into();
        let context =
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None).unwrap();
        assert_eq!(
            context.qualification_profile_id,
            TXT_EXECUTION_QUALIFICATION_PROFILE_ID
        );
        assert_eq!(
            context.structure_projection_schema_version,
            TXT_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
        );
        source.manifest.projection_schema_version =
            LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into();
        assert_eq!(
            resolve_slot_configuration_context(ports(&source), "ws", "w1", None, None)
                .unwrap_err()
                .kind,
            ContextErrorKind::TemplateStructureIntegrity
        );
    }
}
