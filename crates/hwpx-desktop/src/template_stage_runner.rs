//! Durable capture and qualification stages for a pinned template preparation.

use crate::candidate_store::{FileCandidateObjectStore, ObjectFileError, ObjectFileErrorKind};
use crate::captured_file::FileTemplateSourceReader;
use crate::per_work_fence::PerWorkFence;
use crate::qualification_store::FileQualificationObjectStore;
use crate::work_template_store::{
    AtomicWorkTemplateStateStore, WorkStoreError, WorkStoreErrorKind,
};
use hwpx_filler::candidate_revision::{
    CandidateCaptureRequest, CandidateRevisionResult, MutableSourceBinding, TemplateLineage,
    capture_candidate_revision,
};
use hwpx_filler::execution_structure::{
    QualificationProfileManifest, StructureProjection, execution_pass_projection,
    is_supported_execution_projection,
};
use hwpx_filler::prepare_orchestration::{
    APPLY_ALREADY_APPLIED, APPLY_APPLIED, APPLY_APPLIED_THEN_ADVANCED, APPLY_CONFLICT,
    APPLY_INTEGRITY_ERROR, APPLY_REJECTED, APPLY_SUPERSEDED, ApplyOutcome, CaptureCheckpoint,
    derive_stage_ids, find_application, find_change, find_preparation, plan_admission_ready,
    plan_admission_terminal, plan_apply, plan_capture_checkpoint, plan_change_status,
    plan_qualification_checkpoint, plan_recovery,
};
use hwpx_filler::qualification_evidence::{
    BuildRecordsInput, ERROR, QualificationAttempt, QualificationEvidence, QualificationResult,
    build_records,
};
use hwpx_filler::template_qualification::{
    QualifiedCandidate, qualification_profile_id, qualify_exact,
};
use hwpx_filler::work_template_state::{
    CHANGE_APPLIED, CHANGE_CONFLICTED, CHANGE_PREPARED, CHANGE_REJECTED, CHANGE_SUPERSEDED,
    DocumentWork, INITIALIZATION, PREP_BASE_CHANGED, PREP_CAPTURING, PREP_NO_CHANGE,
    PREP_PROFILE_REVOKED, PREP_QUALIFYING, PREP_READY, PREP_SOURCE_BINDING_CHANGED,
    PREP_SUPERSEDED, PreparedTemplateChange, SCHEMA_VERSION, TemplateChangePreparation,
    WorkTemplateApplication, WorkTemplateStateAggregate,
};
use serde_json::{Map, Value};
use std::fmt;

#[derive(Debug)]
pub struct StageError(pub String);
impl fmt::Display for StageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for StageError {}
fn fail(detail: impl Into<String>) -> StageError {
    StageError(detail.into())
}
fn store_error(detail: impl Into<String>) -> WorkStoreError {
    WorkStoreError {
        kind: WorkStoreErrorKind::Conflict,
        detail: detail.into(),
    }
}
fn integrity_read<T>(read: Result<T, ObjectFileError>) -> Result<Option<T>, WorkStoreError> {
    match read {
        Ok(value) => Ok(Some(value)),
        Err(error)
            if [ObjectFileErrorKind::NotFound, ObjectFileErrorKind::Corrupt]
                .contains(&error.kind) =>
        {
            Ok(None)
        }
        Err(error) => Err(store_error(error.detail)),
    }
}

fn apply_evidence_matches(
    prep: &TemplateChangePreparation,
    evidence: &QualificationEvidence,
    attempt: &QualificationAttempt,
) -> bool {
    evidence.result == "PASS"
        && evidence.structure_projection.is_some()
        && attempt.outcome == "PASS"
        && attempt.evidence_id.as_deref() == Some(evidence.evidence_id.as_str())
        && evidence.attempt_id == attempt.attempt_id
        && Some(attempt.attempt_id.as_str()) == prep.attempt_id.as_deref()
        && Some(evidence.revision_id.as_str()) == prep.revision_id.as_deref()
        && evidence.qualification_profile_id == prep.qualification_profile_id
}

fn prior_apply_outcome(
    aggregate: &WorkTemplateStateAggregate,
    change: &PreparedTemplateChange,
) -> Result<Option<ApplyOutcome>, WorkStoreError> {
    if change.status == CHANGE_APPLIED {
        return Ok(Some(ApplyOutcome {
            result: if aggregate.work.current_template_application_id
                == change
                    .resulting_application_id
                    .as_deref()
                    .unwrap_or_default()
            {
                APPLY_ALREADY_APPLIED
            } else {
                APPLY_APPLIED_THEN_ADVANCED
            }
            .into(),
            resulting_application_id: change.resulting_application_id.clone(),
        }));
    }
    let result = match change.status.as_str() {
        CHANGE_PREPARED => return Ok(None),
        CHANGE_SUPERSEDED => APPLY_SUPERSEDED,
        CHANGE_CONFLICTED => APPLY_CONFLICT,
        CHANGE_REJECTED => APPLY_REJECTED,
        _ => return Err(store_error("미상 Prepared Change status")),
    };
    Ok(Some(ApplyOutcome {
        result: result.into(),
        resulting_application_id: None,
    }))
}

fn qualification_projection(
    qualified: &QualifiedCandidate,
    manifest: &QualificationProfileManifest,
) -> Result<Option<StructureProjection>, StageError> {
    if !is_supported_execution_projection(&manifest.projection_schema_version)
        || !matches!(qualified.result, QualificationResult::Passed { .. })
    {
        return Ok(None);
    }
    let structure = qualified.execution_structure.as_ref().ok_or_else(|| {
        fail(format!(
            "Profile 이 {} 를 pin 했는데 inspection 이 composition-ready structure 를 내지 않았다",
            manifest.projection_schema_version
        ))
    })?;
    execution_pass_projection(structure)
        .map(Some)
        .map_err(|error| fail(error.to_string()))
}

pub struct TemplateStageRunner<'a> {
    pub works: &'a AtomicWorkTemplateStateStore,
    pub candidates: &'a mut FileCandidateObjectStore,
    pub qualifications: &'a FileQualificationObjectStore,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdmissionResult {
    pub change: Option<PreparedTemplateChange>,
    pub aggregate: WorkTemplateStateAggregate,
}

pub struct CaptureInput<'a> {
    pub work_id: &'a str,
    pub preparation_id: &'a str,
    pub lineage: &'a TemplateLineage,
    pub binding: &'a MutableSourceBinding,
    pub captured_at: &'a str,
    pub created_at: &'a str,
}
pub struct QualificationInput<'a> {
    pub work_id: &'a str,
    pub preparation_id: &'a str,
    pub media: &'a str,
    pub engine_metadata: &'a Map<String, Value>,
    pub started_at: &'a str,
    pub completed_at: &'a str,
    pub qualified_at: &'a str,
}
pub struct ApplyInput<'a> {
    pub workspace_id: &'a str,
    pub work_id: &'a str,
    pub change_id: &'a str,
    pub actor: &'a str,
    pub new_application_id: &'a str,
    pub applied_at: &'a str,
}
pub const BOOTSTRAP_OK: &str = "BOOTSTRAP_OK";
pub const TEMPLATE_INITIALIZATION_REQUIRED: &str = "TEMPLATE_INITIALIZATION_REQUIRED";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BootstrapOutcome {
    pub result: String,
    pub aggregate: Option<WorkTemplateStateAggregate>,
    pub reason: Option<String>,
}
pub struct BootstrapInput<'a> {
    pub work_id: &'a str,
    pub request_id: &'a str,
    pub lineage: &'a TemplateLineage,
    pub binding: &'a MutableSourceBinding,
    pub profile_id: &'a str,
    pub application_id: &'a str,
    pub engine_metadata: &'a Map<String, Value>,
    pub actor: &'a str,
    pub at: &'a str,
}

impl TemplateStageRunner<'_> {
    /// The first application is committed only after the exact candidate and a
    /// complete PASS attempt/evidence have been persisted and rechecked.
    pub fn bootstrap(
        &mut self,
        input: BootstrapInput<'_>,
        resolve_generation: impl Fn(&DocumentWork) -> Result<u64, StageError>,
    ) -> Result<BootstrapOutcome, StageError> {
        let BootstrapInput {
            work_id,
            request_id,
            lineage,
            binding,
            profile_id,
            application_id,
            engine_metadata,
            actor,
            at,
        } = input;
        if self.works.exists(work_id).map_err(|e| fail(e.detail))? {
            return Ok(BootstrapOutcome {
                result: BOOTSTRAP_OK.into(),
                aggregate: Some(self.works.load(work_id).map_err(|e| fail(e.detail))?),
                reason: None,
            });
        }
        let ids = derive_stage_ids(work_id, request_id);
        let work = DocumentWork {
            work_id: work_id.into(),
            template_lineage_id: lineage.template_lineage_id.clone(),
            current_template_application_id: application_id.into(),
            current_template_preparation_id: None,
            prepare_seq: 0,
        };
        let mut reader = FileTemplateSourceReader::new(|_| {
            resolve_generation(&work).map_err(|error| {
                hwpx_filler::candidate_revision::SourceCaptureError { reason: error.0 }
            })
        });
        let captured = capture_candidate_revision(
            &CandidateCaptureRequest {
                lineage,
                binding,
                preparation_id: request_id,
                observation_id: &ids.observation_id,
                revision_id: &ids.revision_id,
                captured_at: at,
                created_at: at,
            },
            &mut reader,
            self.candidates,
        )
        .map_err(|e| fail(e.0))?;
        let created = match captured {
            CandidateRevisionResult::Created(created) => created,
            CandidateRevisionResult::CaptureError(error) => {
                return Ok(BootstrapOutcome {
                    result: TEMPLATE_INITIALIZATION_REQUIRED.into(),
                    aggregate: None,
                    reason: Some(error.reason),
                });
            }
        };
        let manifest = self
            .qualifications
            .get_manifest(profile_id)
            .map_err(|e| fail(e.detail))?;
        let qualified = qualify_exact(&ids.revision_id, &binding.media, &created.blob.exact_bytes)
            .ok_or_else(|| fail("지원하지 않는 qualification media"))?;
        if qualification_profile_id(&binding.media) != Some(profile_id) {
            return Err(fail("bootstrap qualification profile 이 media 와 불일치"));
        }
        let projection = qualification_projection(&qualified, &manifest)?;
        let (attempt, evidence) = build_records(
            &qualified.result,
            BuildRecordsInput {
                attempt_id: &ids.attempt_id,
                preparation_id: request_id,
                evidence_id: &ids.evidence_id,
                projection_schema_version: &manifest.projection_schema_version,
                engine_metadata,
                started_at: at,
                completed_at: at,
                qualified_at: at,
                structure_projection: projection,
            },
        )
        .map_err(|e| fail(e.detail))?;
        self.qualifications
            .put_attempt(&attempt)
            .map_err(|e| fail(e.detail))?;
        if let Some(evidence) = &evidence {
            self.qualifications
                .put_evidence(evidence)
                .map_err(|e| fail(e.detail))?;
        }
        if let Some(reason) =
            self.bootstrap_refusal(&attempt, &manifest, &created.revision.media)?
        {
            return Ok(BootstrapOutcome {
                result: TEMPLATE_INITIALIZATION_REQUIRED.into(),
                aggregate: None,
                reason: Some(reason),
            });
        }
        let evidence = evidence.ok_or_else(|| fail("PASS Attempt 에 Evidence 부재"))?;
        if evidence.result != "PASS" || evidence.revision_id != ids.revision_id {
            return Err(fail("bootstrap PASS Evidence 결속 불일치"));
        }
        self.initialize_work(work, &evidence.evidence_id, actor, at)
    }

    fn bootstrap_refusal(
        &self,
        attempt: &QualificationAttempt,
        manifest: &QualificationProfileManifest,
        candidate_media: &str,
    ) -> Result<Option<String>, StageError> {
        Ok(if attempt.outcome != "PASS" {
            Some(attempt.outcome.clone())
        } else if self
            .qualifications
            .is_revoked(&attempt.qualification_profile_id)
            .map_err(|e| fail(e.detail))?
        {
            Some("PROFILE_REVOKED".into())
        } else if manifest.media != candidate_media {
            Some("MEDIA_MISMATCH".into())
        } else {
            None
        })
    }

    fn initialize_work(
        &self,
        work: DocumentWork,
        evidence_id: &str,
        actor: &str,
        at: &str,
    ) -> Result<BootstrapOutcome, StageError> {
        let reread = self
            .qualifications
            .get_evidence(evidence_id)
            .map_err(|e| fail(e.detail))?;
        if reread.result != "PASS" {
            return Err(fail("bootstrap PASS Evidence 결속 불일치"));
        }
        let revision = self
            .candidates
            .get_revision(&reread.revision_id)
            .map_err(|e| fail(e.detail))?;
        if revision.template_lineage_id != work.template_lineage_id {
            return Err(fail("bootstrap Evidence revision lineage 불일치"));
        }
        self.qualifications
            .get_manifest(&reread.qualification_profile_id)
            .map_err(|e| fail(e.detail))?;
        let work_id = work.work_id.clone();
        let application_id = work.current_template_application_id.clone();
        let aggregate = WorkTemplateStateAggregate {
            schema_version: SCHEMA_VERSION.into(),
            aggregate_version: 1,
            work,
            applications: vec![WorkTemplateApplication {
                application_id,
                work_id: work_id.clone(),
                application_epoch: 1,
                pass_evidence_id: evidence_id.into(),
                previous_application_id: None,
                origin: INITIALIZATION.into(),
                prepared_change_id: None,
                actor: actor.into(),
                applied_at: at.into(),
            }],
            preparations: vec![],
            prepared_changes: vec![],
        };
        match self.works.create(&aggregate) {
            Ok(()) => Ok(BootstrapOutcome {
                result: BOOTSTRAP_OK.into(),
                aggregate: Some(aggregate),
                reason: None,
            }),
            Err(error) if error.kind == WorkStoreErrorKind::Exists => Ok(BootstrapOutcome {
                result: BOOTSTRAP_OK.into(),
                aggregate: Some(self.works.load(&work_id).map_err(|e| fail(e.detail))?),
                reason: None,
            }),
            Err(error) => Err(fail(error.detail)),
        }
    }

    /// The reader is invoked at most once for a CAPTURING preparation. The Work update
    /// rechecks the generation while holding the store writer lease.
    pub fn capture(
        &mut self,
        input: CaptureInput<'_>,
        resolve_generation: impl Fn(&DocumentWork) -> Result<u64, StageError>,
    ) -> Result<TemplateChangePreparation, StageError> {
        let CaptureInput {
            work_id,
            preparation_id,
            lineage,
            binding,
            captured_at,
            created_at,
        } = input;
        let aggregate = self.works.load(work_id).map_err(|e| fail(e.detail))?;
        let preparation = find_preparation(&aggregate, preparation_id).map_err(|e| fail(e.0))?;
        if preparation.status != PREP_CAPTURING {
            return Ok(preparation.clone());
        }
        if binding.source_binding_id != preparation.source_binding_id
            || i64::try_from(binding.generation).ok() != Some(preparation.source_binding_generation)
            || lineage.template_lineage_id != aggregate.work.template_lineage_id
        {
            return Err(fail(format!(
                "capture 입력이 Preparation {preparation_id} 의 pin 과 불일치"
            )));
        }
        let ids = derive_stage_ids(work_id, preparation_id);
        let mut reader = FileTemplateSourceReader::new(|_| {
            resolve_generation(&aggregate.work).map_err(|error| {
                hwpx_filler::candidate_revision::SourceCaptureError { reason: error.0 }
            })
        });
        let captured = capture_candidate_revision(
            &CandidateCaptureRequest {
                lineage,
                binding,
                preparation_id,
                observation_id: &ids.observation_id,
                revision_id: &ids.revision_id,
                captured_at,
                created_at,
            },
            &mut reader,
            self.candidates,
        )
        .map_err(|e| fail(e.0))?;
        let reason = match &captured {
            CandidateRevisionResult::Created(_) => None,
            CandidateRevisionResult::CaptureError(error) => Some(error.reason.as_str()),
        };
        self.works
            .update(work_id, |current| {
                let pinned =
                    find_preparation(current, preparation_id).map_err(|e| store_error(e.0))?;
                let observed_generation =
                    resolve_generation(&current.work).map_err(|e| store_error(e.0))?;
                plan_capture_checkpoint(
                    current,
                    preparation_id,
                    CaptureCheckpoint {
                        observation_id: &ids.observation_id,
                        revision_id: &ids.revision_id,
                        capture_failed: reason.is_some(),
                        capture_error_reason: reason,
                        binding_changed: i64::try_from(observed_generation).ok()
                            != Some(pinned.source_binding_generation),
                        completed_at: captured_at,
                    },
                )
                .map_err(|e| store_error(e.0))
            })
            .map_err(|e| fail(e.detail))?;
        let current = self.works.load(work_id).map_err(|e| fail(e.detail))?;
        find_preparation(&current, preparation_id)
            .cloned()
            .map_err(|e| fail(e.0))
    }

    /// The manifest pin selects the projection schema; Attempt and Evidence are
    /// persisted before Work references either object.
    pub fn qualify(
        &self,
        input: QualificationInput<'_>,
    ) -> Result<TemplateChangePreparation, StageError> {
        let QualificationInput {
            work_id,
            preparation_id,
            media,
            engine_metadata,
            started_at,
            completed_at,
            qualified_at,
        } = input;
        let current = self.works.load(work_id).map_err(|e| fail(e.detail))?;
        let prep = find_preparation(&current, preparation_id).map_err(|e| fail(e.0))?;
        if prep.status != PREP_QUALIFYING || prep.attempt_id.is_some() {
            return Ok(prep.clone());
        }
        if qualification_profile_id(media) != Some(prep.qualification_profile_id.as_str()) {
            return Err(fail(format!(
                "qualification profile 이 Preparation {preparation_id} 의 pin 과 불일치"
            )));
        }
        let revision_id = prep.revision_id.as_deref().ok_or_else(|| {
            fail(format!(
                "qualification: Preparation {preparation_id} 에 revision pin 이 없습니다"
            ))
        })?;
        let manifest = self
            .qualifications
            .get_manifest(&prep.qualification_profile_id)
            .map_err(|e| fail(e.detail))?;
        if manifest.media != media {
            return Err(fail(
                "qualification manifest media 가 Preparation media 와 불일치",
            ));
        }
        let revision = self
            .candidates
            .get_revision(revision_id)
            .map_err(|e| fail(e.detail))?;
        let blob = self
            .candidates
            .get_blob(&revision.exact_content_digest)
            .map_err(|e| fail(e.detail))?;
        if revision.media != media || blob.media != media {
            return Err(fail("Candidate media 가 Qualification media 와 불일치"));
        }
        let qualified = qualify_exact(revision_id, media, &blob.exact_bytes)
            .ok_or_else(|| fail("지원하지 않는 qualification media"))?;
        let projection = qualification_projection(&qualified, &manifest)?;
        let ids = derive_stage_ids(work_id, preparation_id);
        let (attempt, evidence) = build_records(
            &qualified.result,
            BuildRecordsInput {
                attempt_id: &ids.attempt_id,
                preparation_id,
                evidence_id: &ids.evidence_id,
                projection_schema_version: &manifest.projection_schema_version,
                engine_metadata,
                started_at,
                completed_at,
                qualified_at,
                structure_projection: projection,
            },
        )
        .map_err(|e| fail(e.detail))?;
        self.qualifications
            .put_attempt(&attempt)
            .map_err(|e| fail(e.detail))?;
        if let Some(evidence) = &evidence {
            self.qualifications
                .put_evidence(evidence)
                .map_err(|e| fail(e.detail))?;
        }
        self.works
            .update(work_id, |current| {
                plan_qualification_checkpoint(
                    current,
                    preparation_id,
                    &attempt.outcome,
                    &attempt.attempt_id,
                    evidence.as_ref().map(|item| item.evidence_id.as_str()),
                    completed_at,
                )
                .map_err(|e| store_error(e.0))
            })
            .map_err(|e| fail(e.detail))?;
        let current = self.works.load(work_id).map_err(|e| fail(e.detail))?;
        find_preparation(&current, preparation_id)
            .cloned()
            .map_err(|e| fail(e.0))
    }

    pub fn recover(
        &self,
        work_id: &str,
        preparation_id: &str,
        completed_at: &str,
    ) -> Result<TemplateChangePreparation, StageError> {
        let ids = derive_stage_ids(work_id, preparation_id);
        let attempt = self.recovery_attempt(&ids.attempt_id)?;
        self.works
            .update(work_id, |current| {
                plan_recovery(
                    current,
                    preparation_id,
                    attempt.as_ref().map(|item| item.outcome.as_str()),
                    attempt.as_ref().map(|item| item.attempt_id.as_str()),
                    attempt
                        .as_ref()
                        .and_then(|item| item.evidence_id.as_deref()),
                    completed_at,
                )
                .map_err(|e| store_error(e.0))
            })
            .map_err(|e| fail(e.detail))?;
        let current = self.works.load(work_id).map_err(|e| fail(e.detail))?;
        find_preparation(&current, preparation_id)
            .cloned()
            .map_err(|e| fail(e.0))
    }

    fn recovery_attempt(
        &self,
        attempt_id: &str,
    ) -> Result<Option<QualificationAttempt>, StageError> {
        let attempt = match self.qualifications.get_attempt(attempt_id) {
            Ok(attempt) => attempt,
            Err(error) if error.kind == ObjectFileErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(fail(error.detail)),
        };
        if attempt.outcome == ERROR {
            return Ok(Some(attempt));
        }
        let Some(id) = &attempt.evidence_id else {
            return Ok(None);
        };
        match self.qualifications.get_evidence(id) {
            Ok(_) => Ok(Some(attempt)),
            Err(error) if error.kind == ObjectFileErrorKind::NotFound => Ok(None),
            Err(error) => Err(fail(error.detail)),
        }
    }

    /// Compare the exact PASS target with the current operational revision while
    /// the Work writer lease is held; stale facts become terminal preparations.
    pub fn admit(
        &self,
        work_id: &str,
        preparation_id: &str,
        resolve_binding: impl Fn(&DocumentWork) -> Result<(String, i64), StageError>,
        prepared_change_id: &str,
        prepared_at: &str,
    ) -> Result<AdmissionResult, StageError> {
        let aggregate = self
            .works
            .update(work_id, |current| {
                let prep =
                    find_preparation(current, preparation_id).map_err(|e| store_error(e.0))?;
                if prep.status == PREP_READY {
                    let id = prep.prepared_change_id.as_deref().ok_or_else(|| {
                        store_error(format!(
                            "admission: READY Preparation {preparation_id} 에 change id 가 없습니다"
                        ))
                    })?;
                    find_change(current, id).map_err(|e| store_error(e.0))?;
                    return Ok(current.clone());
                }
                if prep.status != PREP_QUALIFYING || prep.attempt_id.is_none() {
                    return Ok(current.clone());
                }
                let terminal = self.admission_terminal(current, prep, &resolve_binding)?;
                if let Some(status) = terminal {
                    plan_admission_terminal(current, preparation_id, status, prepared_at)
                        .map_err(|e| store_error(e.0))
                } else {
                    let evidence_id = prep.evidence_id.as_deref().ok_or_else(|| {
                        store_error(format!(
                            "admission: Preparation {preparation_id} 에 PASS evidence 가 없습니다"
                        ))
                    })?;
                    plan_admission_ready(
                        current,
                        preparation_id,
                        prepared_change_id,
                        evidence_id,
                        prepared_at,
                    )
                    .map_err(|e| store_error(e.0))
                }
            })
            .map_err(|e| fail(e.detail))?;
        let prep = find_preparation(&aggregate, preparation_id).map_err(|e| fail(e.0))?;
        let change = match prep.prepared_change_id.as_deref() {
            Some(id) if prep.status == PREP_READY => {
                Some(find_change(&aggregate, id).map_err(|e| fail(e.0))?.clone())
            }
            _ => None,
        };
        Ok(AdmissionResult { change, aggregate })
    }

    fn admission_terminal(
        &self,
        current: &WorkTemplateStateAggregate,
        prep: &TemplateChangePreparation,
        resolve_binding: &impl Fn(&DocumentWork) -> Result<(String, i64), StageError>,
    ) -> Result<Option<&'static str>, WorkStoreError> {
        Ok(
            if current.work.current_template_preparation_id.as_deref()
                != Some(prep.preparation_id.as_str())
            {
                Some(PREP_SUPERSEDED)
            } else if current.work.current_template_application_id != prep.base_application_id {
                Some(PREP_BASE_CHANGED)
            } else if resolve_binding(&current.work).map_err(|e| store_error(e.0))?
                != (
                    prep.source_binding_id.clone(),
                    prep.source_binding_generation,
                )
            {
                Some(PREP_SOURCE_BINDING_CHANGED)
            } else if self
                .qualifications
                .is_revoked(&prep.qualification_profile_id)
                .map_err(|e| store_error(e.detail))?
            {
                Some(PREP_PROFILE_REVOKED)
            } else if self.admission_matches_current(current, prep)? {
                Some(PREP_NO_CHANGE)
            } else {
                None
            },
        )
    }

    fn admission_matches_current(
        &self,
        current: &WorkTemplateStateAggregate,
        prep: &TemplateChangePreparation,
    ) -> Result<bool, WorkStoreError> {
        let preparation_id = &prep.preparation_id;
        let id = prep.evidence_id.as_deref().ok_or_else(|| {
            store_error(format!(
                "admission: Preparation {preparation_id} 에 PASS evidence 가 없습니다"
            ))
        })?;
        let evidence = self
            .qualifications
            .get_evidence(id)
            .map_err(|e| store_error(e.detail))?;
        if evidence.result != "PASS"
            || evidence.attempt_id != prep.attempt_id.as_deref().unwrap_or_default()
            || evidence.revision_id != prep.revision_id.as_deref().unwrap_or_default()
            || evidence.qualification_profile_id != prep.qualification_profile_id
            || evidence.structure_projection.is_none()
        {
            return Err(store_error(format!(
                "admission: PASS Evidence 가 Preparation {preparation_id} pin 과 불일치"
            )));
        }
        let app = find_application(current, &current.work.current_template_application_id)
            .map_err(|e| store_error(e.0))?;
        let old = self
            .qualifications
            .get_evidence(&app.pass_evidence_id)
            .map_err(|e| store_error(e.detail))?;
        let target = self
            .candidates
            .get_revision(&evidence.revision_id)
            .map_err(|e| store_error(e.detail))?;
        let previous = self
            .candidates
            .get_revision(&old.revision_id)
            .map_err(|e| store_error(e.detail))?;
        Ok((
            target.template_lineage_id,
            target.media,
            target.exact_content_digest,
            evidence.qualification_profile_id,
        ) == (
            previous.template_lineage_id,
            previous.media,
            previous.exact_content_digest,
            old.qualification_profile_id,
        ))
    }

    fn apply_evidence(
        &self,
        prep: &TemplateChangePreparation,
        change: &PreparedTemplateChange,
    ) -> Result<Option<QualificationEvidence>, WorkStoreError> {
        let Some(evidence) = integrity_read(
            self.qualifications
                .get_evidence(&change.target_pass_evidence_id),
        )?
        else {
            return Ok(None);
        };
        let Some(attempt_id) = prep.attempt_id.as_deref() else {
            return Ok(None);
        };
        let Some(attempt) = integrity_read(self.qualifications.get_attempt(attempt_id))? else {
            return Ok(None);
        };
        Ok(apply_evidence_matches(prep, &evidence, &attempt).then_some(evidence))
    }

    fn apply_integrity(
        &self,
        aggregate: &WorkTemplateStateAggregate,
        prep: &TemplateChangePreparation,
        change: &PreparedTemplateChange,
    ) -> Result<bool, WorkStoreError> {
        let Some(evidence) = self.apply_evidence(prep, change)? else {
            return Ok(false);
        };
        let Some(revision) = integrity_read(self.candidates.get_revision(&evidence.revision_id))?
        else {
            return Ok(false);
        };
        if integrity_read(self.candidates.get_blob(&revision.exact_content_digest))?.is_none() {
            return Ok(false);
        }
        let Some(manifest) = integrity_read(
            self.qualifications
                .get_manifest(&prep.qualification_profile_id),
        )?
        else {
            return Ok(false);
        };
        let current = find_application(aggregate, &aggregate.work.current_template_application_id)
            .map_err(|e| store_error(e.0))?;
        let Some(current_evidence) =
            integrity_read(self.qualifications.get_evidence(&current.pass_evidence_id))?
        else {
            return Ok(false);
        };
        let Some(current_revision) =
            integrity_read(self.candidates.get_revision(&current_evidence.revision_id))?
        else {
            return Ok(false);
        };
        Ok(
            revision.template_lineage_id == aggregate.work.template_lineage_id
                && manifest.media == revision.media
                && revision.media == current_revision.media,
        )
    }

    /// Status-first application under the shared Work fence. The returned aggregate
    /// is reloaded before releasing that fence, so view and outcome stay paired.
    pub fn apply(
        &self,
        input: ApplyInput<'_>,
        authorize: impl Fn(&DocumentWork, &str) -> Result<(), StageError>,
    ) -> Result<(ApplyOutcome, WorkTemplateStateAggregate), StageError> {
        let ApplyInput {
            workspace_id,
            work_id,
            change_id,
            actor,
            new_application_id,
            applied_at,
        } = input;
        PerWorkFence::with(workspace_id, work_id, || {
            let mut outcome = None;
            self.works
                .update(work_id, |aggregate| {
                    let change = find_change(aggregate, change_id).map_err(|e| store_error(e.0))?;
                    authorize(&aggregate.work, actor).map_err(|e| store_error(e.0))?;
                    if let Some(prior) = prior_apply_outcome(aggregate, change)? {
                        outcome = Some(prior);
                        return Ok(aggregate.clone());
                    }
                    let prep = find_preparation(aggregate, &change.preparation_id)
                        .map_err(|e| store_error(e.0))?;
                    let conflict = if aggregate.work.current_template_preparation_id.as_deref()
                        != Some(prep.preparation_id.as_str())
                        || prep.status != PREP_READY
                        || prep.prepared_change_id.as_deref() != Some(change_id)
                    {
                        Some((CHANGE_SUPERSEDED, APPLY_SUPERSEDED))
                    } else if aggregate.work.current_template_application_id
                        != change.base_application_id
                    {
                        Some((CHANGE_CONFLICTED, APPLY_CONFLICT))
                    } else if self
                        .qualifications
                        .is_revoked(&prep.qualification_profile_id)
                        .map_err(|e| store_error(e.detail))?
                    {
                        Some((CHANGE_REJECTED, APPLY_REJECTED))
                    } else {
                        None
                    };
                    if let Some((status, result)) = conflict {
                        outcome = Some(ApplyOutcome {
                            result: result.into(),
                            resulting_application_id: None,
                        });
                        return plan_change_status(aggregate, change_id, status)
                            .map_err(|e| store_error(e.0));
                    }
                    if !self.apply_integrity(aggregate, prep, change)? {
                        outcome = Some(ApplyOutcome {
                            result: APPLY_INTEGRITY_ERROR.into(),
                            resulting_application_id: None,
                        });
                        return Ok(aggregate.clone());
                    }
                    outcome = Some(ApplyOutcome {
                        result: APPLY_APPLIED.into(),
                        resulting_application_id: Some(new_application_id.into()),
                    });
                    plan_apply(aggregate, change, new_application_id, actor, applied_at)
                        .map_err(|e| store_error(e.0))
                })
                .map_err(|e| fail(e.detail))?;
            let aggregate = self.works.load(work_id).map_err(|e| fail(e.detail))?;
            Ok((outcome.expect("all apply branches set outcome"), aggregate))
        })
        .map_err(|e| fail(e.0))?
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::execution_structure::TXT_EXECUTION_QUALIFICATION_PROFILE_ID;
    use hwpx_filler::prepare_template_change::{PrepareIntent, PreparePins, plan_prepare};
    use hwpx_filler::qualification_evidence::QualificationProfileRevocation;
    use hwpx_filler::text_template_inspection::txt_qualification_manifest;
    use hwpx_filler::work_template_state::{
        PREP_CAPTURE_ERROR, PREP_INTERRUPTED, PREP_QUALIFICATION_ERROR, PREP_QUALIFICATION_FAILED,
    };
    use serde_json::json;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct StageFixture {
        root: PathBuf,
        works: AtomicWorkTemplateStateStore,
        candidates: FileCandidateObjectStore,
        qualifications: FileQualificationObjectStore,
        binding: MutableSourceBinding,
        lineage: TemplateLineage,
    }

    impl StageFixture {
        fn new() -> Self {
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(format!(
                "../../.cache/template-stage-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            fs::create_dir_all(&root).unwrap();
            let source = root.join("template.txt");
            fs::write(&source, b"Hello {{name}}\n").unwrap();
            let works = AtomicWorkTemplateStateStore::new(root.join("works")).unwrap();
            let candidates = FileCandidateObjectStore::new(root.join("candidates"));
            let qualifications = FileQualificationObjectStore::new(root.join("qualification"));
            qualifications
                .put_manifest(&txt_qualification_manifest("t0"))
                .unwrap();
            let binding = MutableSourceBinding {
                source_binding_id: "w.binding".into(),
                media: "txt".into(),
                host_reference: source.to_string_lossy().into(),
                display_metadata: Map::new(),
                generation: 1,
            };
            let lineage = TemplateLineage {
                template_lineage_id: "w.lineage".into(),
                media: "txt".into(),
                mutable_source_binding_id: binding.source_binding_id.clone(),
                source_binding_generation: 1,
                updated_at: "t0".into(),
            };
            Self {
                root,
                works,
                candidates,
                qualifications,
                binding,
                lineage,
            }
        }

        fn runner(&mut self) -> TemplateStageRunner<'_> {
            TemplateStageRunner {
                works: &self.works,
                candidates: &mut self.candidates,
                qualifications: &self.qualifications,
            }
        }

        fn bootstrap(&mut self) {
            let binding = self.binding.clone();
            let lineage = self.lineage.clone();
            let result = self
                .runner()
                .bootstrap(
                    BootstrapInput {
                        work_id: "w",
                        request_id: "boot-r",
                        lineage: &lineage,
                        binding: &binding,
                        profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
                        application_id: "w.boot-r.app",
                        engine_metadata: &Map::new(),
                        actor: "local-user",
                        at: "t0",
                    },
                    |_| Ok(1),
                )
                .unwrap();
            assert_eq!(result.result, BOOTSTRAP_OK);
        }

        fn prepare(&self, request: &str, prep: &str) {
            self.works
                .update("w", |current| {
                    plan_prepare(
                        current,
                        PrepareIntent {
                            prepare_request_id: request,
                            preparation_id: prep,
                            pins: &PreparePins {
                                source_binding_id: self.binding.source_binding_id.clone(),
                                source_binding_generation: 1,
                                qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID
                                    .into(),
                            },
                            execution_session_id: "session",
                            started_at: "t1",
                        },
                    )
                    .map(|plan| plan.aggregate)
                    .map_err(|e| store_error(e.0))
                })
                .unwrap();
        }

        fn checkpoint(&mut self, bytes: &[u8]) {
            self.bootstrap();
            fs::write(&self.binding.host_reference, bytes).unwrap();
            self.prepare("change-request", "prep");
            self.capture(|_| Ok(1)).unwrap();
            self.qualify("txt").unwrap();
        }

        fn capture(
            &mut self,
            resolve: impl Fn(&DocumentWork) -> Result<u64, StageError>,
        ) -> Result<TemplateChangePreparation, StageError> {
            let binding = self.binding.clone();
            let lineage = self.lineage.clone();
            self.runner().capture(
                CaptureInput {
                    work_id: "w",
                    preparation_id: "prep",
                    lineage: &lineage,
                    binding: &binding,
                    captured_at: "t2",
                    created_at: "t2",
                },
                resolve,
            )
        }

        fn qualify(&mut self, media: &str) -> Result<TemplateChangePreparation, StageError> {
            self.runner().qualify(QualificationInput {
                work_id: "w",
                preparation_id: "prep",
                media,
                engine_metadata: &Map::new(),
                started_at: "t3",
                completed_at: "t3",
                qualified_at: "t3",
            })
        }

        fn admit(&mut self) -> Result<AdmissionResult, StageError> {
            self.runner()
                .admit("w", "prep", |_| Ok(("w.binding".into(), 1)), "change", "t4")
        }

        fn apply(
            &mut self,
            application: &str,
        ) -> Result<(ApplyOutcome, WorkTemplateStateAggregate), StageError> {
            let workspace = self.root.to_string_lossy().into_owned();
            let result = self.runner().apply(
                ApplyInput {
                    workspace_id: &workspace,
                    work_id: "w",
                    change_id: "change",
                    actor: "local-user",
                    new_application_id: application,
                    applied_at: "t5",
                },
                |work, actor| {
                    assert_eq!(actor, "local-user");
                    crate::per_work_fence::tests::assert_held(&workspace, &work.work_id);
                    Ok(())
                },
            );
            crate::per_work_fence::tests::assert_released(&workspace, "w");
            result
        }

        fn mutate(
            &self,
            change: impl FnOnce(&mut WorkTemplateStateAggregate),
        ) -> WorkTemplateStateAggregate {
            self.works
                .update("w", |current| {
                    let mut next = current.clone();
                    change(&mut next);
                    next.aggregate_version = current.aggregate_version + 1;
                    Ok(next)
                })
                .unwrap()
        }
    }

    impl Drop for StageFixture {
        fn drop(&mut self) {
            let root = self.root.canonicalize().unwrap();
            let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../..")
                .canonicalize()
                .unwrap();
            assert!(root.starts_with(workspace.join(".cache")));
            assert!(
                root.file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("template-stage-")
            );
            fs::remove_dir_all(root).unwrap();
        }
    }

    fn advance_application(state: &mut WorkTemplateStateAggregate) {
        let mut next = state.applications.last().unwrap().clone();
        next.application_id = "advanced".into();
        next.application_epoch += 1;
        next.previous_application_id = Some(state.work.current_template_application_id.clone());
        next.origin = hwpx_filler::work_template_state::PREPARED_CHANGE.into();
        next.prepared_change_id = Some("other-change".into());
        state.work.current_template_application_id = next.application_id.clone();
        state.applications.push(next);
    }

    fn revoke(fixture: &StageFixture) -> PathBuf {
        fixture
            .qualifications
            .put_revocation(&QualificationProfileRevocation {
                qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into(),
                reason: "compromised".into(),
                authority: "admin".into(),
                revoked_at: "t4".into(),
            })
            .unwrap();
        fixture
            .qualifications
            .object_path("revocations", TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
            .unwrap()
    }

    fn rewrite_object(path: &std::path::Path, change: impl FnOnce(&mut Value)) {
        let mut envelope: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        change(&mut envelope["content"]);
        envelope["digest"] = json!(hwpx_filler::execution_structure::content_digest(
            &envelope["content"]
        ));
        fs::write(path, serde_json::to_vec(&envelope).unwrap()).unwrap();
    }

    #[test]
    fn bootstrap_refusals_persist_attempts_without_creating_a_false_application() {
        for (case, reason) in [
            ("capture", "MISSING"),
            ("fail", "FAIL"),
            ("revoked", "PROFILE_REVOKED"),
            ("media", "MEDIA_MISMATCH"),
        ] {
            let mut fixture = StageFixture::new();
            match case {
                "fail" => fs::write(&fixture.binding.host_reference, "{{#항목 첨부}}\n").unwrap(),
                "revoked" => {
                    revoke(&fixture);
                }
                "media" => rewrite_object(
                    &fixture
                        .qualifications
                        .object_path("manifests", TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
                        .unwrap(),
                    |manifest| manifest["media"] = json!("hwpx"),
                ),
                _ => (),
            }
            let binding = fixture.binding.clone();
            let lineage = fixture.lineage.clone();
            let outcome = fixture
                .runner()
                .bootstrap(
                    BootstrapInput {
                        work_id: "w",
                        request_id: "boot-r",
                        lineage: &lineage,
                        binding: &binding,
                        profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
                        application_id: "w.boot-r.app",
                        engine_metadata: &Map::new(),
                        actor: "local-user",
                        at: "t0",
                    },
                    |_| {
                        if case == "capture" {
                            Err(fail("MISSING"))
                        } else {
                            Ok(1)
                        }
                    },
                )
                .unwrap();
            assert_eq!(outcome.result, TEMPLATE_INITIALIZATION_REQUIRED, "{case}");
            assert_eq!(outcome.reason.as_deref(), Some(reason));
            assert_eq!(outcome.aggregate, None);
            assert!(!fixture.works.exists("w").unwrap());
            if case == "fail" {
                assert_eq!(
                    fixture
                        .qualifications
                        .get_evidence(&derive_stage_ids("w", "boot-r").evidence_id)
                        .unwrap()
                        .result,
                    "FAIL"
                );
            }
        }
        let mut fixture = StageFixture::new();
        let (attempt, evidence) = build_records(
            &QualificationResult::AttemptErrored {
                revision_id: "rev".into(),
                qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into(),
                error_code: "inspection-error".into(),
            },
            BuildRecordsInput {
                attempt_id: "attempt",
                preparation_id: "boot-r",
                evidence_id: "unused",
                projection_schema_version: "unused",
                engine_metadata: &Map::new(),
                started_at: "t0",
                completed_at: "t0",
                qualified_at: "t0",
                structure_projection: None,
            },
        )
        .unwrap();
        assert!(evidence.is_none());
        fixture.qualifications.put_attempt(&attempt).unwrap();
        assert_eq!(
            fixture
                .runner()
                .bootstrap_refusal(&attempt, &txt_qualification_manifest("t0"), "txt")
                .unwrap()
                .as_deref(),
            Some("ERROR")
        );
        assert!(!fixture.works.exists("w").unwrap());
        assert_eq!(
            fixture
                .qualifications
                .get_evidence("unused")
                .unwrap_err()
                .kind,
            ObjectFileErrorKind::NotFound
        );
    }

    #[test]
    fn initialization_rechecks_durable_pass_references_before_creating_work() {
        let mut fixture = StageFixture::new();
        fixture.bootstrap();
        let original = fixture.works.load("w").unwrap();
        let mut work = original.work.clone();
        work.work_id = "other".into();
        work.current_template_application_id = "other-app".into();
        let ids = derive_stage_ids("w", "boot-r");
        assert!(
            fixture
                .runner()
                .initialize_work(work.clone(), "missing", "local-user", "t1")
                .is_err()
        );
        assert!(!fixture.works.exists("other").unwrap());
        let paths = [
            fixture
                .qualifications
                .object_path("evidence", &ids.evidence_id)
                .unwrap(),
            fixture
                .candidates
                .object_path("revisions", &ids.revision_id)
                .unwrap(),
            fixture
                .qualifications
                .object_path("manifests", TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
                .unwrap(),
        ];
        for path in &paths {
            let bytes = fs::read(path).unwrap();
            fs::remove_file(path).unwrap();
            assert!(
                fixture
                    .runner()
                    .initialize_work(work.clone(), &ids.evidence_id, "local-user", "t1")
                    .is_err(),
                "{path:?}"
            );
            assert!(!fixture.works.exists("other").unwrap());
            fs::write(path, bytes).unwrap();
        }
        let bytes = fs::read(&paths[0]).unwrap();
        rewrite_object(&paths[0], |evidence| {
            evidence["result"] = json!("FAIL");
            evidence["structure_projection"] = Value::Null;
            evidence["diagnostics"] = json!([{"kind":"invalid","message":"invalid template"}]);
        });
        assert_eq!(
            fixture
                .qualifications
                .get_evidence(&ids.evidence_id)
                .unwrap()
                .result,
            "FAIL"
        );
        assert!(
            fixture
                .runner()
                .initialize_work(work.clone(), &ids.evidence_id, "local-user", "t1")
                .unwrap_err()
                .0
                .contains("PASS Evidence")
        );
        assert!(!fixture.works.exists("other").unwrap());
        fs::write(&paths[0], bytes).unwrap();
        work.template_lineage_id = "other-lineage".into();
        assert!(
            fixture
                .runner()
                .initialize_work(work, &ids.evidence_id, "local-user", "t1")
                .unwrap_err()
                .0
                .contains("lineage 불일치")
        );
        assert!(!fixture.works.exists("other").unwrap());
        assert_eq!(fixture.works.load("w").unwrap(), original);
    }

    #[test]
    fn capture_and_qualification_pin_exact_source_and_reject_repeated_or_stale_workers() {
        let mut fixture = StageFixture::new();
        fixture.bootstrap();
        fixture.prepare("change-request", "prep");
        let before = fixture.works.load("w").unwrap();
        let binding = MutableSourceBinding {
            source_binding_id: "other".into(),
            ..fixture.binding.clone()
        };
        let lineage = TemplateLineage {
            mutable_source_binding_id: "other".into(),
            ..fixture.lineage.clone()
        };
        assert!(
            fixture
                .runner()
                .capture(
                    CaptureInput {
                        work_id: "w",
                        preparation_id: "prep",
                        binding: &binding,
                        lineage: &lineage,
                        captured_at: "t2",
                        created_at: "t2"
                    },
                    |_| panic!("foreign source was read")
                )
                .unwrap_err()
                .0
                .contains("pin 과 불일치")
        );
        assert_eq!(fixture.works.load("w").unwrap(), before);
        let captured = fixture.capture(|_| Ok(1)).unwrap();
        let ids = derive_stage_ids("w", "prep");
        assert_eq!(captured.status, PREP_QUALIFYING);
        assert_eq!(
            captured.revision_id.as_deref(),
            Some(ids.revision_id.as_str())
        );
        assert_eq!(
            captured.observation_id.as_deref(),
            Some(ids.observation_id.as_str())
        );
        fixture.candidates.get_revision(&ids.revision_id).unwrap();
        assert_eq!(
            fixture
                .capture(|_| panic!("duplicate capture reread source"))
                .unwrap(),
            captured
        );
        assert!(
            fixture
                .qualify("hwpx")
                .unwrap_err()
                .0
                .contains("pin 과 불일치")
        );
        let qualified = fixture.qualify("txt").unwrap();
        assert_eq!(qualified.status, PREP_QUALIFYING);
        assert_eq!(
            qualified.attempt_id.as_deref(),
            Some(ids.attempt_id.as_str())
        );
        assert_eq!(
            qualified.evidence_id.as_deref(),
            Some(ids.evidence_id.as_str())
        );
        let evidence = fixture
            .qualifications
            .get_evidence(&ids.evidence_id)
            .unwrap();
        let manifest = fixture
            .qualifications
            .get_manifest(TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
            .unwrap();
        assert_eq!(
            evidence
                .structure_projection
                .unwrap()
                .projection_schema_version,
            manifest.projection_schema_version
        );
        let path = fixture
            .qualifications
            .object_path("manifests", TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
            .unwrap();
        let bytes = fs::read(&path).unwrap();
        fs::remove_file(&path).unwrap();
        assert_eq!(
            fixture.qualify("unrecognized").unwrap(),
            qualified,
            "completed checkpoint reran qualification"
        );
        fs::write(path, bytes).unwrap();
        fixture.prepare("new-request", "new-prep");
        assert_eq!(
            fixture
                .capture(|_| panic!("superseded capture"))
                .unwrap()
                .status,
            PREP_SUPERSEDED
        );
        assert_eq!(fixture.qualify("txt").unwrap().status, PREP_SUPERSEDED);
        assert_eq!(
            fixture
                .works
                .load("w")
                .unwrap()
                .work
                .current_template_preparation_id
                .as_deref(),
            Some("new-prep")
        );
    }

    #[test]
    fn capture_errors_and_orphan_objects_do_not_become_qualified_after_restart() {
        let mut fixture = StageFixture::new();
        fixture.bootstrap();
        fixture.prepare("change-request", "prep");
        let capturing = fixture.works.load("w").unwrap();
        assert_eq!(
            fixture.runner().recover("w", "prep", "t9").unwrap().status,
            PREP_INTERRUPTED
        );
        fixture.mutate(|state| *state = capturing.clone());
        fixture.capture(|_| Ok(1)).unwrap();
        let qualifying = fixture.works.load("w").unwrap();
        // Simulate the crash before the durable revision was attached to the Work.
        fixture.mutate(|state| *state = capturing.clone());
        assert_eq!(
            fixture.runner().recover("w", "prep", "t9").unwrap().status,
            PREP_INTERRUPTED
        );
        fixture.mutate(|state| *state = qualifying);
        assert_eq!(
            fixture.runner().recover("w", "prep", "t9").unwrap().status,
            PREP_INTERRUPTED
        );
        fixture.mutate(|state| *state = capturing.clone());
        assert_eq!(
            fixture.capture(|_| Ok(2)).unwrap().status,
            PREP_SOURCE_BINDING_CHANGED
        );
        fixture.mutate(|state| *state = capturing);
        fs::remove_file(&fixture.binding.host_reference).unwrap();
        let failure = fixture.capture(|_| Ok(1)).unwrap();
        assert_eq!(failure.status, PREP_CAPTURE_ERROR);
        assert_eq!(failure.diagnostics[0]["reason"], "SOURCE_CAPTURE_ERROR");
        assert_eq!(fixture.qualify("txt").unwrap(), failure);
        assert_eq!(
            fixture.runner().recover("w", "prep", "t9").unwrap(),
            failure
        );
        assert_eq!(
            fixture
                .qualifications
                .get_attempt(&derive_stage_ids("w", "prep").attempt_id)
                .unwrap_err()
                .kind,
            ObjectFileErrorKind::NotFound
        );
    }

    #[test]
    fn recovery_uses_only_complete_durable_attempts_and_propagates_corruption() {
        for (outcome, expected) in [
            ("PASS", PREP_QUALIFYING),
            ("FAIL", PREP_QUALIFICATION_FAILED),
            ("ERROR", PREP_QUALIFICATION_ERROR),
        ] {
            let mut fixture = StageFixture::new();
            fixture.bootstrap();
            fixture.prepare("change-request", "prep");
            let bytes: &[u8] = if outcome == "FAIL" {
                "{{#항목 첨부}}\n".as_bytes()
            } else {
                b"Changed {{name}}\n"
            };
            fs::write(&fixture.binding.host_reference, bytes).unwrap();
            fixture.capture(|_| Ok(1)).unwrap();
            let checkpoint = fixture.works.load("w").unwrap();
            let ids = derive_stage_ids("w", "prep");
            if outcome == "ERROR" {
                let (attempt, evidence) = build_records(
                    &QualificationResult::AttemptErrored {
                        revision_id: ids.revision_id.clone(),
                        qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into(),
                        error_code: "INSPECTION_ERROR".into(),
                    },
                    BuildRecordsInput {
                        attempt_id: &ids.attempt_id,
                        preparation_id: "prep",
                        evidence_id: &ids.evidence_id,
                        projection_schema_version: "unused",
                        engine_metadata: &Map::new(),
                        started_at: "t3",
                        completed_at: "t3",
                        qualified_at: "t3",
                        structure_projection: None,
                    },
                )
                .unwrap();
                assert!(evidence.is_none());
                fixture.qualifications.put_attempt(&attempt).unwrap();
            } else {
                assert_eq!(fixture.qualify("txt").unwrap().status, expected);
            }
            fixture.mutate(|state| *state = checkpoint.clone());
            fs::remove_file(&fixture.binding.host_reference).unwrap();
            let recovered = fixture.runner().recover("w", "prep", "t9").unwrap();
            assert_eq!(recovered.status, expected, "{outcome}");
            assert_eq!(
                recovered.attempt_id.as_deref(),
                Some(ids.attempt_id.as_str())
            );
            if outcome == "ERROR" {
                assert_eq!(recovered.evidence_id, None);
                assert_eq!(
                    fixture
                        .qualifications
                        .get_evidence(&ids.evidence_id)
                        .unwrap_err()
                        .kind,
                    ObjectFileErrorKind::NotFound
                );
            } else {
                assert_eq!(
                    recovered.evidence_id.as_deref(),
                    Some(ids.evidence_id.as_str())
                );
                let path = fixture
                    .qualifications
                    .object_path("evidence", &ids.evidence_id)
                    .unwrap();
                let evidence_bytes = fs::read(&path).unwrap();
                let before = fixture.mutate(|state| *state = checkpoint.clone());
                fs::write(&path, b"{").unwrap();
                assert!(fixture.runner().recover("w", "prep", "t9").is_err());
                assert_eq!(fixture.works.load("w").unwrap(), before);
                fs::remove_file(&path).unwrap();
                let interrupted = fixture.runner().recover("w", "prep", "t9").unwrap();
                assert_eq!(interrupted.status, PREP_INTERRUPTED);
                assert_eq!(interrupted.evidence_id, None);
                fs::write(path, evidence_bytes).unwrap();
            }
            let before = fixture.mutate(|state| *state = checkpoint);
            let path = fixture
                .qualifications
                .object_path("attempts", &ids.attempt_id)
                .unwrap();
            fs::write(path, b"{").unwrap();
            assert!(fixture.runner().recover("w", "prep", "t9").is_err());
            assert_eq!(fixture.works.load("w").unwrap(), before);
        }
    }

    #[test]
    fn apply_conflicts_preserve_current_application_and_replay_terminal_outcomes() {
        let mut fixture = StageFixture::new();
        fixture.checkpoint(b"Revised {{name}}\n");
        let ready = fixture.admit().unwrap().aggregate;
        for (case, expected, status) in [
            ("advanced", APPLY_CONFLICT, CHANGE_CONFLICTED),
            ("cleared", APPLY_SUPERSEDED, CHANGE_SUPERSEDED),
            ("newer", APPLY_SUPERSEDED, CHANGE_SUPERSEDED),
            ("revoked", APPLY_REJECTED, CHANGE_REJECTED),
        ] {
            fixture.mutate(|state| *state = ready.clone());
            let mut revocation = None;
            match case {
                "advanced" => {
                    fixture.mutate(advance_application);
                }
                "cleared" => {
                    fixture.mutate(|state| state.work.current_template_preparation_id = None);
                }
                "newer" => fixture.prepare("new-request", "new-prep"),
                _ => revocation = Some(revoke(&fixture)),
            }
            let before = fixture.works.load("w").unwrap();
            let (outcome, after) = fixture.apply("unused").unwrap();
            assert_eq!(outcome.result, expected, "{case}");
            assert_eq!(outcome.resulting_application_id, None);
            assert_eq!(
                after.work.current_template_application_id,
                before.work.current_template_application_id
            );
            assert_eq!(after.applications, before.applications);
            assert_eq!(find_change(&after, "change").unwrap().status, status);
            let (replay, unchanged) = fixture.apply("another-unused").unwrap();
            assert_eq!(replay, outcome);
            assert_eq!(unchanged, after);
            if let Some(path) = revocation {
                fs::remove_file(path).unwrap();
            }
        }
        fixture.mutate(|state| *state = ready.clone());
        fixture.apply("next-app").unwrap();
        let advanced = fixture.mutate(advance_application);
        let (outcome, after) = fixture.apply("unused").unwrap();
        assert_eq!(outcome.result, APPLY_APPLIED_THEN_ADVANCED);
        assert_eq!(
            outcome.resulting_application_id.as_deref(),
            Some("next-app")
        );
        assert_eq!(after, advanced);
    }

    #[test]
    fn apply_refuses_missing_corrupt_or_mismatched_exact_evidence_without_changing_work() {
        let mut fixture = StageFixture::new();
        fixture.checkpoint(b"Revised {{name}}\n");
        let ready = fixture.admit().unwrap().aggregate;
        let ids = derive_stage_ids("w", "prep");
        let old_ids = derive_stage_ids("w", "boot-r");
        let revision = fixture.candidates.get_revision(&ids.revision_id).unwrap();
        let blob_key = revision
            .exact_content_digest
            .split(':')
            .next_back()
            .unwrap();
        let paths = [
            fixture
                .qualifications
                .object_path("evidence", &ids.evidence_id)
                .unwrap(),
            fixture
                .qualifications
                .object_path("attempts", &ids.attempt_id)
                .unwrap(),
            fixture
                .qualifications
                .object_path("manifests", TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
                .unwrap(),
            fixture
                .qualifications
                .object_path("evidence", &old_ids.evidence_id)
                .unwrap(),
            fixture
                .candidates
                .object_path("revisions", &ids.revision_id)
                .unwrap(),
            fixture
                .candidates
                .object_path("revisions", &old_ids.revision_id)
                .unwrap(),
            fixture.candidates.object_path("blobs", blob_key).unwrap(),
        ];
        for path in &paths {
            let original = fs::read(path).unwrap();
            for corrupt in [false, true] {
                if corrupt {
                    fs::write(path, b"{").unwrap();
                } else {
                    fs::remove_file(path).unwrap();
                }
                let (outcome, after) = fixture.apply("unused").unwrap();
                assert_eq!(
                    outcome.result, APPLY_INTEGRITY_ERROR,
                    "{path:?}, corrupt={corrupt}"
                );
                assert_eq!(outcome.resulting_application_id, None);
                assert_eq!(after, ready);
                assert_eq!(fixture.works.load("w").unwrap(), ready);
                fs::write(path, &original).unwrap();
            }
        }
        for evidence in ["absent", old_ids.evidence_id.as_str()] {
            let before = fixture.mutate(|state| {
                state.prepared_changes[0].target_pass_evidence_id = evidence.into()
            });
            let (outcome, after) = fixture.apply("unused").unwrap();
            assert_eq!(outcome.result, APPLY_INTEGRITY_ERROR);
            assert_eq!(after, before);
        }
        fixture.mutate(|state| *state = ready.clone());
        let before = fixture.works.load("w").unwrap();
        let original_manifest = fs::read(&paths[2]).unwrap();
        rewrite_object(&paths[2], |manifest| manifest["media"] = json!("hwpx"));
        assert_eq!(
            fixture
                .qualifications
                .get_manifest(TXT_EXECUTION_QUALIFICATION_PROFILE_ID)
                .unwrap()
                .media,
            "hwpx"
        );
        assert_eq!(
            fixture.apply("unused").unwrap().0.result,
            APPLY_INTEGRITY_ERROR
        );
        assert_eq!(fixture.works.load("w").unwrap(), before);
        fs::write(&paths[2], original_manifest).unwrap();
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(0)
                .open(&paths[0])
                .unwrap();
            assert!(
                fixture.apply("unused").is_err(),
                "I/O failure must propagate, not become a successful status"
            );
            assert_eq!(fixture.works.load("w").unwrap(), before);
            drop(held);
        }
    }

    #[test]
    fn admission_uses_exact_identity_and_returns_ready_once_or_no_change() {
        let mut fixture = StageFixture::new();
        fixture.checkpoint(b"Hello {{name}}\n");
        let checkpoint = fixture.works.load("w").unwrap();
        let unchanged = fixture.admit().unwrap();
        assert!(unchanged.change.is_none());
        assert_eq!(unchanged.aggregate.preparations[0].status, PREP_NO_CHANGE);
        assert!(unchanged.aggregate.prepared_changes.is_empty());
        fixture.mutate(|state| *state = checkpoint);
        let old_id = derive_stage_ids("w", "boot-r").evidence_id;
        let old_path = fixture
            .qualifications
            .object_path("evidence", &old_id)
            .unwrap();
        rewrite_object(&old_path, |evidence| {
            evidence["qualification_profile_id"] = json!("older-profile")
        });
        assert_eq!(
            fixture
                .qualifications
                .get_evidence(&old_id)
                .unwrap()
                .qualification_profile_id,
            "older-profile"
        );
        let ready = fixture.admit().unwrap();
        assert_eq!(ready.change.as_ref().unwrap().status, CHANGE_PREPARED);
        assert_eq!(
            ready.change.as_ref().unwrap().base_application_id,
            "w.boot-r.app"
        );
        assert_eq!(ready.aggregate.preparations[0].status, PREP_READY);
        assert_eq!(
            ready.aggregate.preparations[0]
                .prepared_change_id
                .as_deref(),
            Some("change")
        );
        let repeated = fixture
            .runner()
            .admit(
                "w",
                "prep",
                |_| panic!("replay resolved new binding"),
                "unused",
                "later",
            )
            .unwrap();
        assert_eq!(repeated, ready);
    }

    #[test]
    fn admission_stale_pins_are_terminal_and_foreign_evidence_never_creates_a_change() {
        let mut fixture = StageFixture::new();
        fixture.checkpoint(b"Revised {{name}}\n");
        let checkpoint = fixture.works.load("w").unwrap();
        for (case, status) in [
            ("cleared", PREP_SUPERSEDED),
            ("newer", PREP_SUPERSEDED),
            ("advanced", PREP_BASE_CHANGED),
            ("binding", PREP_SOURCE_BINDING_CHANGED),
            ("revoked", PREP_PROFILE_REVOKED),
        ] {
            fixture.mutate(|state| *state = checkpoint.clone());
            let mut revocation = None;
            match case {
                "cleared" => {
                    fixture.mutate(|state| state.work.current_template_preparation_id = None);
                }
                "newer" => fixture.prepare("new-request", "new-prep"),
                "advanced" => {
                    fixture.mutate(advance_application);
                }
                "revoked" => revocation = Some(revoke(&fixture)),
                _ => (),
            }
            let before = fixture.works.load("w").unwrap();
            let generation = if case == "binding" { 2 } else { 1 };
            let result = fixture
                .runner()
                .admit(
                    "w",
                    "prep",
                    |_| Ok(("w.binding".into(), generation)),
                    "change",
                    "t4",
                )
                .unwrap();
            assert!(result.change.is_none(), "{case}");
            assert_eq!(result.aggregate.preparations[0].status, status, "{case}");
            assert!(result.aggregate.prepared_changes.is_empty());
            assert_eq!(result.aggregate.applications, before.applications);
            if let Some(path) = revocation {
                fs::remove_file(path).unwrap();
            }
        }
        fixture.mutate(|state| *state = checkpoint.clone());
        let ids = derive_stage_ids("w", "prep");
        let mut attempt = fixture.qualifications.get_attempt(&ids.attempt_id).unwrap();
        let mut evidence = fixture
            .qualifications
            .get_evidence(&ids.evidence_id)
            .unwrap();
        attempt.attempt_id = "other-attempt".into();
        attempt.evidence_id = Some("other-evidence".into());
        evidence.attempt_id = attempt.attempt_id.clone();
        evidence.evidence_id = "other-evidence".into();
        fixture.qualifications.put_attempt(&attempt).unwrap();
        fixture.qualifications.put_evidence(&evidence).unwrap();
        for evidence in [
            derive_stage_ids("w", "boot-r").evidence_id,
            "other-evidence".into(),
        ] {
            let before =
                fixture.mutate(|state| state.preparations[0].evidence_id = Some(evidence.clone()));
            assert!(fixture.admit().unwrap_err().0.contains("admission"));
            assert_eq!(fixture.works.load("w").unwrap(), before);
        }
        for state in [PREP_CAPTURING, PREP_QUALIFYING] {
            let before = fixture.mutate(|current| {
                *current = checkpoint.clone();
                current.preparations[0].status = state.into();
                current.preparations[0].attempt_id = None;
            });
            let result = fixture
                .runner()
                .admit(
                    "w",
                    "prep",
                    |_| panic!("incomplete checkpoint resolved binding"),
                    "change",
                    "t4",
                )
                .unwrap();
            assert!(result.change.is_none());
            assert_eq!(result.aggregate, before);
        }
    }

    #[test]
    fn bootstrap_persists_complete_pass_before_work_and_refuses_invalid_bytes() {
        let mut fixture = StageFixture::new();
        let StageFixture {
            root,
            works,
            candidates,
            qualifications,
            binding,
            lineage,
        } = &mut fixture;
        let source = PathBuf::from(&binding.host_reference);
        let mut runner = TemplateStageRunner {
            works,
            candidates,
            qualifications,
        };
        let metadata = Map::new();
        let input = || BootstrapInput {
            work_id: "w",
            request_id: "boot-r",
            lineage,
            binding,
            profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
            application_id: "w.boot-r.app",
            engine_metadata: &metadata,
            actor: "local-user",
            at: "t0",
        };
        let first = runner.bootstrap(input(), |_| Ok(1)).unwrap();
        assert_eq!(first.result, BOOTSTRAP_OK);
        assert_eq!(works.load("w").unwrap().applications.len(), 1);
        let mut other = first.aggregate.clone().unwrap();
        other.work.work_id = "other".into();
        other.applications[0].work_id = "other".into();
        other.applications[0].application_id = "other-app".into();
        other.work.current_template_application_id = "other-app".into();
        works.create(&other).unwrap();
        assert!(
            runner
                .bootstrap(input(), |_| Err(fail("reader should not run")))
                .unwrap()
                .aggregate
                .is_some()
        );
        let initial = first.aggregate.unwrap();
        let app = &initial.applications[0];
        assert_eq!(app.origin, INITIALIZATION);
        assert_eq!(app.application_epoch, 1);
        assert_eq!(app.previous_application_id, None);
        assert_eq!(app.prepared_change_id, None);
        // A winner commits after the initial exists check, while this caller captures.
        fs::remove_file(root.join("works/w.json")).unwrap();
        let seated = std::sync::atomic::AtomicBool::new(false);
        let collided = runner
            .bootstrap(input(), |_| {
                if !seated.swap(true, std::sync::atomic::Ordering::SeqCst) {
                    works.create(&initial).unwrap();
                }
                Ok(1)
            })
            .unwrap();
        assert_eq!(collided.aggregate.as_ref(), Some(&initial));
        assert_eq!(works.load("w").unwrap(), initial);
        fs::write(&source, b"Revised {{name}}\n").unwrap();
        works
            .update("w", |current| {
                plan_prepare(
                    current,
                    PrepareIntent {
                        prepare_request_id: "change-request",
                        preparation_id: "prep",
                        pins: &PreparePins {
                            source_binding_id: binding.source_binding_id.clone(),
                            source_binding_generation: 1,
                            qualification_profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID.into(),
                        },
                        execution_session_id: "session",
                        started_at: "t1",
                    },
                )
                .map(|plan| plan.aggregate)
                .map_err(|e| store_error(e.0))
            })
            .unwrap();
        assert_eq!(
            runner
                .capture(
                    CaptureInput {
                        work_id: "w",
                        preparation_id: "prep",
                        lineage,
                        binding,
                        captured_at: "t2",
                        created_at: "t2",
                    },
                    |_| Ok(1)
                )
                .unwrap()
                .status,
            PREP_QUALIFYING
        );
        runner
            .qualify(QualificationInput {
                work_id: "w",
                preparation_id: "prep",
                media: "txt",
                engine_metadata: &metadata,
                started_at: "t3",
                completed_at: "t3",
                qualified_at: "t3",
            })
            .unwrap();
        let ready = runner
            .admit(
                "w",
                "prep",
                |_| Ok((binding.source_binding_id.clone(), 1)),
                "change",
                "t4",
            )
            .unwrap();
        assert_eq!(ready.change.unwrap().status, CHANGE_PREPARED);
        let workspace = root.to_string_lossy();
        let apply_input = || ApplyInput {
            workspace_id: &workspace,
            work_id: "w",
            change_id: "change",
            actor: "local-user",
            new_application_id: "next-app",
            applied_at: "t5",
        };
        let authorize = |work: &DocumentWork, actor: &str| {
            assert_eq!(work.work_id, "w");
            assert_eq!(actor, "local-user");
            crate::per_work_fence::tests::assert_held(&workspace, "w");
            Ok(())
        };
        let refused = runner
            .apply(apply_input(), |work, actor| {
                authorize(work, actor)?;
                Err(fail("permission denied"))
            })
            .unwrap_err();
        assert_eq!(refused.0, "permission denied");
        assert_eq!(works.load("w").unwrap(), ready.aggregate);
        crate::per_work_fence::tests::assert_released(&workspace, "w");
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let path = root.join("works/w.json");
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(1 | 2)
                .open(&path)
                .unwrap();
            assert!(runner.apply(apply_input(), authorize).is_err());
            assert_eq!(works.load("w").unwrap(), ready.aggregate);
            crate::per_work_fence::tests::assert_released(&workspace, "w");
            drop(held);
        }
        let (applied, current) = runner.apply(apply_input(), authorize).unwrap();
        assert_eq!(applied.result, APPLY_APPLIED);
        assert_eq!(
            applied.resulting_application_id.as_deref(),
            Some("next-app")
        );
        assert_eq!(current.work.current_template_application_id, "next-app");
        let application = find_application(&current, "next-app").unwrap();
        assert_eq!(application.application_epoch, 2);
        assert_eq!(
            application.previous_application_id.as_deref(),
            Some("w.boot-r.app")
        );
        assert_eq!(
            application.origin,
            hwpx_filler::work_template_state::PREPARED_CHANGE
        );
        assert_eq!(application.prepared_change_id.as_deref(), Some("change"));
        assert_eq!(application.actor, "local-user");
        assert_eq!(application.applied_at, "t5");
        let change = find_change(&current, "change").unwrap();
        assert_eq!(change.status, CHANGE_APPLIED);
        assert_eq!(change.resulting_application_id.as_deref(), Some("next-app"));
        assert_eq!(application.pass_evidence_id, change.target_pass_evidence_id);
        assert_eq!(current, works.load("w").unwrap());
        assert_eq!(works.load("other").unwrap(), other);
        crate::per_work_fence::tests::assert_released(&workspace, "w");
        let (repeated, unchanged) = runner
            .apply(
                ApplyInput {
                    new_application_id: "unused",
                    ..apply_input()
                },
                authorize,
            )
            .unwrap();
        assert_eq!(repeated.result, APPLY_ALREADY_APPLIED);
        assert_eq!(unchanged, current);
        crate::per_work_fence::tests::assert_released(&workspace, "w");
        fs::write(&source, [0xff, 0xfe]).unwrap();
        let invalid_binding = MutableSourceBinding {
            source_binding_id: "bad.binding".into(),
            ..binding.clone()
        };
        let invalid_lineage = TemplateLineage {
            template_lineage_id: "bad.lineage".into(),
            mutable_source_binding_id: invalid_binding.source_binding_id.clone(),
            ..lineage.clone()
        };
        let invalid = runner
            .bootstrap(
                BootstrapInput {
                    work_id: "bad",
                    request_id: "boot-invalid",
                    lineage: &invalid_lineage,
                    binding: &invalid_binding,
                    profile_id: TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
                    application_id: "bad.app",
                    engine_metadata: &metadata,
                    actor: "local-user",
                    at: "t1",
                },
                |_| Ok(1),
            )
            .unwrap();
        assert_eq!(invalid.result, TEMPLATE_INITIALIZATION_REQUIRED);
        assert!(!works.exists("bad").unwrap());
    }
}
