//! Managed materialization: short authority pins, long in-memory work, then atomic delivery.

use crate::artifact_observation::{ArtifactObservation, observe_delivered_artifact};
use crate::atomic_file::{write_bytes_atomic, write_bytes_atomic_exclusive};
use crate::candidate_store::FileCandidateObjectStore;
use crate::per_work_fence::PerWorkFence;
use crate::qualification_store::FileQualificationObjectStore;
use crate::seal_execution_service::{ManagedRunContext, SealExecutionService};
use crate::work_template_store::AtomicWorkTemplateStateStore;
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::execution_composition::{
    NATIVE_PRIMITIVE_CONTRACT_ID, TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
};
use hwpx_filler::execution_contract_set::{
    SealedExecutionPlanSemanticPayload, execution_basis_digest,
};
use hwpx_filler::execution_structure::decode_execution_structure;
use hwpx_filler::fields::FillNote;
use hwpx_filler::generation_delivery::{
    CurrentResolvedDelivery, PATH_OCCUPANCY_OBSERVATION_MISMATCH, WRITE_ADD_SUFFIX, WRITE_NEW,
    WRITE_OVERWRITE, evaluate_managed_run_admission,
};
use hwpx_filler::hwpx_structure::scan_structure;
use hwpx_filler::materialization_runner::{
    MaterializationInput, MaterializationOutcome, MaterializedDocumentBytes, materialize_hwpx,
    materialize_txt,
};
use hwpx_filler::raw_data_record::{
    CanonicalSourceValue, RawDataRecordSnapshot, RawRecordCaptureProvenance,
    build_raw_record_snapshot,
};
use hwpx_filler::record_validation::{
    ValidateDataRecordResult, ValidatedDataRecord, validate_data_record_against_plan,
    validate_data_records_against_plan,
};
use hwpx_filler::stored_execution_plan::{
    CURRENT_BASIS_NOT_SEALABLE, DIGEST_MISMATCH, SealTerminalOutcome,
};
use hwpx_filler::text_render::python_repr;
use serde_json::{Map, Value};
use std::fmt;
use std::io;
use std::path::{Component, Path, PathBuf};

const RECORD_VALIDATION_BLOCKED: &str = "RECORD_VALIDATION_BLOCKED";
const STRUCTURE_NOTATION_UNCOMPILED: &str = "STRUCTURE_NOTATION_UNCOMPILED";
const APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR: &str = "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR";
const DELIVERY_WRITE_FAILED: &str = "DELIVERY_WRITE_FAILED";

#[derive(Debug)]
pub struct ManagedGenerationError(pub String);
impl fmt::Display for ManagedGenerationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ManagedGenerationError {}
fn error(detail: impl Into<String>) -> ManagedGenerationError {
    ManagedGenerationError(detail.into())
}
fn repr(text: &str) -> String {
    python_repr(&Value::String(text.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DeliveredDocument {
    pub item_ordinal: usize,
    pub record_identity: String,
    pub relative_path: String,
    pub absolute_path: PathBuf,
    pub collision_disposition: String,
    pub output_digest: String,
    pub execution_notes: Vec<FillNote>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ManagedGenerationResult {
    Refused {
        code: String,
        detail: String,
        failed_item_ordinal: Option<usize>,
    },
    Cancelled {
        attempted: usize,
        total: usize,
    },
    Aborted {
        code: String,
        detail: String,
        failed_item_ordinal: usize,
        delivered: Vec<DeliveredDocument>,
    },
    ReadBackFailed {
        code: String,
        detail: String,
        failed_item_ordinal: usize,
        delivered: Vec<DeliveredDocument>,
    },
    Completed {
        output_directory: PathBuf,
        delivered: Vec<DeliveredDocument>,
    },
}

#[derive(Debug)]
pub enum UnpublishedTxtResult {
    Materialized(MaterializedDocumentBytes),
    Refused { code: String, detail: String },
}

/// Workbench copy uses the same authority pin and native TXT materializer without delivery.
pub fn materialize_one_unpublished_txt(
    authority_root: &Path,
    seal_service: &SealExecutionService<'_>,
    work_ref: &str,
    copy_token: &str,
    source_record: &Map<String, Value>,
    captured_clock: &str,
) -> Result<UnpublishedTxtResult, ManagedGenerationError> {
    if let Some(refusal) = txt_admission(seal_service, work_ref)? {
        return Ok(refusal);
    }
    let sealed = seal_service
        .seal(work_ref, copy_token)
        .map_err(|item| error(item.to_string()))?;
    let plan = match txt_sealed_plan(sealed.terminal_outcome) {
        Ok(plan) => plan,
        Err(refusal) => return Ok(refusal),
    };
    let context = seal_service
        .managed_run_context(work_ref, "txt")
        .map_err(|item| error(item.to_string()))?;
    materialize_sealed_txt(
        authority_root,
        context.as_ref(),
        &plan,
        source_record,
        captured_clock,
    )
}

fn materialize_sealed_txt(
    authority_root: &Path,
    context: Option<&ManagedRunContext<'_, '_>>,
    plan: &SealedExecutionPlanSemanticPayload,
    source_record: &Map<String, Value>,
    captured_clock: &str,
) -> Result<UnpublishedTxtResult, ManagedGenerationError> {
    let Some(context) = context else {
        return Ok(UnpublishedTxtResult::Refused {
            code: "TEMPLATE_INITIALIZATION_REQUIRED".into(),
            detail: "이 작업의 실행 권위를 확인할 수 없습니다.".into(),
        });
    };
    let record = match txt_record(plan, source_record, captured_clock) {
        Ok(record) => record,
        Err(refusal) => return Ok(refusal),
    };
    let input = match start_gate(context, plan, &record)? {
        StartGate::Ready(input) => input,
        StartGate::Refused { code, detail } => {
            return Ok(UnpublishedTxtResult::Refused { code, detail });
        }
    };
    let candidates = FileCandidateObjectStore::new(authority_root.join("candidates"));
    let works = AtomicWorkTemplateStateStore::new(authority_root.join("works"))
        .map_err(|item| error(item.to_string()))?;
    let qualifications = FileQualificationObjectStore::new(authority_root.join("qualification"));
    match materialization_result(materialize_native(
        &input,
        true,
        &candidates,
        &works,
        &qualifications,
    )?)? {
        Ok(item) => Ok(UnpublishedTxtResult::Materialized(item)),
        Err((code, detail)) => Ok(UnpublishedTxtResult::Refused { code, detail }),
    }
}
fn txt_admission(
    seal_service: &SealExecutionService<'_>,
    work_ref: &str,
) -> Result<Option<UnpublishedTxtResult>, ManagedGenerationError> {
    if seal_service
        .job_media(work_ref)
        .map_err(|item| error(item.to_string()))?
        != "txt"
    {
        return Ok(Some(UnpublishedTxtResult::Refused {
            code: "TXT_MEDIA_REQUIRED".into(),
            detail: "TXT 작업이 아닙니다.".into(),
        }));
    }
    if let Some(detail) = seal_service
        .missing_work_detail(work_ref)
        .map_err(|item| error(item.to_string()))?
    {
        return Ok(Some(UnpublishedTxtResult::Refused {
            code: "TEMPLATE_INITIALIZATION_REQUIRED".into(),
            detail: format!("이 작업의 템플릿 확인이 아직 끝나지 않았습니다({detail})."),
        }));
    }
    Ok(None)
}

fn txt_sealed_plan(
    terminal: SealTerminalOutcome,
) -> Result<SealedExecutionPlanSemanticPayload, UnpublishedTxtResult> {
    match terminal {
        SealTerminalOutcome::Sealed(item) => match item.plan_payload {
            Some(plan) => Ok(plan),
            None => Err(UnpublishedTxtResult::Refused {
                code: "EXECUTION_PLAN_NOT_SEALED".into(),
                detail: "봉인 결과에 실행 payload 가 없습니다.".into(),
            }),
        },
        SealTerminalOutcome::QualificationBlocked(item) => Err(UnpublishedTxtResult::Refused {
            code: "EXECUTION_PLAN_NOT_SEALED".into(),
            detail: if item.normalized_blockers.is_empty() {
                "실행 계획을 봉인할 수 없습니다.".into()
            } else {
                format!(
                    "실행 계획을 봉인할 수 없습니다: {}",
                    item.normalized_blockers.join(", ")
                )
            },
        }),
        SealTerminalOutcome::PolicyBlocked(item) => Err(UnpublishedTxtResult::Refused {
            code: "EXECUTION_PLAN_NOT_SEALED".into(),
            detail: format!("실행 계획을 봉인할 수 없습니다: {}", item.policy_code),
        }),
        SealTerminalOutcome::Stale(item) => Err(UnpublishedTxtResult::Refused {
            code: "EXECUTION_PLAN_NOT_SEALED".into(),
            detail: format!("실행 기준이 그사이 바뀌었습니다: {}", item.stale_reason),
        }),
    }
}

fn txt_record(
    plan: &SealedExecutionPlanSemanticPayload,
    source_record: &Map<String, Value>,
    captured_clock: &str,
) -> Result<ValidatedDataRecord, UnpublishedTxtResult> {
    let keys: Vec<_> = source_record.keys().cloned().collect();
    let values = source_record
        .iter()
        .map(|(key, value)| {
            (
                key.clone(),
                match value {
                    Value::Null => CanonicalSourceValue::Null,
                    Value::String(text) => CanonicalSourceValue::Text(text.clone()),
                    other => {
                        CanonicalSourceValue::Text(hwpx_filler::text_render::python_repr(other))
                    }
                },
            )
        })
        .collect();
    let snapshot = match build_raw_record_snapshot(
        &keys,
        values,
        &format!("workbench-record/{captured_clock}/{}", keys.len()),
        RawRecordCaptureProvenance {
            source_adapter_contract_id: "workbench-record-capture/v1".into(),
            captured_at: captured_clock.into(),
            source_observation_ref: Some("workbench-session".into()),
        },
    ) {
        Ok(item) => item,
        Err(item) => {
            return Err(UnpublishedTxtResult::Refused {
                code: "RECORD_CAPTURE_FAILED".into(),
                detail: item.to_string(),
            });
        }
    };
    match validate_data_record_against_plan(
        plan,
        &snapshot,
        None,
        false,
        captured_clock,
        Some(captured_clock),
    ) {
        ValidateDataRecordResult::Validated(item) => Ok(*item),
        ValidateDataRecordResult::Blocked(blockers) => {
            let mut codes: Vec<_> = blockers.into_iter().map(|item| item.code).collect();
            codes.sort();
            codes.dedup();
            Err(UnpublishedTxtResult::Refused {
                code: RECORD_VALIDATION_BLOCKED.into(),
                detail: format!("이 레코드의 검증이 닫히지 않았습니다: {}", codes.join(", ")),
            })
        }
        ValidateDataRecordResult::ContextError(item) => Err(UnpublishedTxtResult::Refused {
            code: item.code,
            detail: item.detail,
        }),
    }
}

fn refused(
    code: impl Into<String>,
    detail: impl Into<String>,
    ordinal: Option<usize>,
) -> ManagedGenerationResult {
    ManagedGenerationResult::Refused {
        code: code.into(),
        detail: detail.into(),
        failed_item_ordinal: ordinal,
    }
}

enum StartGate<'a> {
    Ready(MaterializationInput<'a>),
    Refused { code: String, detail: String },
}

pub struct ManagedGenerationInput<'a, 's, 'j> {
    pub authority_root: &'a Path,
    pub context: &'a ManagedRunContext<'s, 'j>,
    pub plan: &'a SealedExecutionPlanSemanticPayload,
    pub snapshots: &'a [RawDataRecordSnapshot],
    pub resolved: &'a CurrentResolvedDelivery,
    pub validated_at: &'a str,
}

/// Runs one already resolved delivery. No file is written until every record materializes.
pub fn run_managed_generation(
    input: ManagedGenerationInput<'_, '_, '_>,
    cancel_requested: impl Fn() -> bool,
    mut on_progress: impl FnMut(usize, usize),
) -> Result<ManagedGenerationResult, ManagedGenerationError> {
    let ManagedGenerationInput {
        authority_root,
        context,
        plan,
        snapshots,
        resolved,
        validated_at,
    } = input;
    let records = match validate_records(
        plan,
        snapshots,
        validated_at,
        &resolved.captured_delivery_clock,
    ) {
        Ok(records) => records,
        Err(refusal) => return Ok(refusal),
    };
    let candidates = FileCandidateObjectStore::new(authority_root.join("candidates"));
    let works = AtomicWorkTemplateStateStore::new(authority_root.join("works"))
        .map_err(|item| error(item.to_string()))?;
    let qualifications = FileQualificationObjectStore::new(authority_root.join("qualification"));
    let wanted_blob = &plan.execution_basis.template.exact_content_digest;
    let source = candidates
        .get_blob(wanted_blob)
        .map_err(|item| error(item.to_string()))?;
    let primitive = &plan
        .execution_basis
        .contracts
        .roles
        .native_primitive_contract_id;
    let is_txt = primitive == TXT_NATIVE_PRIMITIVE_CONTRACT_ID;
    if primitive == NATIVE_PRIMITIVE_CONTRACT_ID
        && let Err(refusal) = check_candidate_notation(&source.exact_bytes)
    {
        return Ok(refusal);
    }
    let mut outcomes = Vec::with_capacity(records.len());
    let total = records.len();
    for (ordinal, record) in records.iter().enumerate() {
        if cancel_requested() {
            return Ok(ManagedGenerationResult::Cancelled {
                attempted: ordinal,
                total,
            });
        }
        let gate = start_gate(context, plan, record)?;
        match gate {
            StartGate::Refused { code, detail } => outcomes.push(Err((code, detail))),
            StartGate::Ready(input) => {
                let materialized =
                    materialize_native(&input, is_txt, &candidates, &works, &qualifications)?;
                outcomes.push(materialization_result(materialized)?);
            }
        }
        on_progress(ordinal + 1, total);
    }
    deliver(resolved, outcomes, is_txt)
}

type DeliveryOutcome = Result<MaterializedDocumentBytes, (String, String)>;

fn materialization_result(
    outcome: MaterializationOutcome,
) -> Result<DeliveryOutcome, ManagedGenerationError> {
    match outcome {
        MaterializationOutcome::Materialized(item) => Ok(Ok(item)),
        MaterializationOutcome::Failure(
            hwpx_filler::materialization_conformance::ConformanceResult::Failure { code, detail },
        ) => Ok(Err((code.into(), detail))),
        MaterializationOutcome::Failure(_) => Err(error("materialization failure shape invalid")),
    }
}

fn validate_records(
    plan: &SealedExecutionPlanSemanticPayload,
    snapshots: &[RawDataRecordSnapshot],
    validated_at: &str,
    captured_clock: &str,
) -> Result<Vec<ValidatedDataRecord>, ManagedGenerationResult> {
    let mut records = Vec::with_capacity(snapshots.len());
    for (ordinal, result) in
        validate_data_records_against_plan(plan, snapshots, validated_at, Some(captured_clock))
            .into_iter()
            .enumerate()
    {
        match result {
            ValidateDataRecordResult::Validated(record) => records.push(*record),
            ValidateDataRecordResult::Blocked(blockers) => {
                let mut codes: Vec<_> = blockers.iter().map(|item| item.code.clone()).collect();
                codes.sort();
                codes.dedup();
                return Err(refused(
                    RECORD_VALIDATION_BLOCKED,
                    format!(
                        "record {ordinal} 의 검증이 닫히지 않았다: {}",
                        codes.join(", ")
                    ),
                    None,
                ));
            }
            ValidateDataRecordResult::ContextError(item) => {
                return Err(refused(item.code, item.detail, None));
            }
        }
    }
    Ok(records)
}

fn check_candidate_notation(bytes: &[u8]) -> Result<(), ManagedGenerationResult> {
    let unreadable = |detail: String| {
        refused(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            format!("실행할 Candidate bytes 를 읽을 수 없어 구간 표기를 확인하지 못했다: {detail}"),
            None,
        )
    };
    let package = HwpxPackage::from_bytes(bytes, PackageLimits::default())
        .map_err(|item| unreadable(item.to_string()))?;
    let marker_n = scan_structure(&package)
        .map_err(|item| unreadable(item.to_string()))?
        .summary
        .markers;
    if marker_n > 0 {
        return Err(refused(
            STRUCTURE_NOTATION_UNCOMPILED,
            format!("실행할 템플릿에 미변환 구간 표기가 {marker_n}건 남아 있다"),
            None,
        ));
    }
    Ok(())
}

fn materialize_native(
    input: &MaterializationInput<'_>,
    is_txt: bool,
    candidates: &FileCandidateObjectStore,
    works: &AtomicWorkTemplateStateStore,
    qualifications: &FileQualificationObjectStore,
) -> Result<MaterializationOutcome, ManagedGenerationError> {
    let candidate = |digest: &str| {
        candidates
            .get_blob(digest)
            .map(|blob| blob.exact_bytes.as_ref().to_vec())
            .map_err(|item| item.to_string())
    };
    let structure = |plan: &SealedExecutionPlanSemanticPayload| {
        let work = works
            .load(&plan.execution_basis.work_authority_id)
            .map_err(|item| item.to_string())?;
        let app_id = &plan.execution_basis.template.template_application_id;
        let application = work
            .applications
            .iter()
            .find(|item| item.application_id == *app_id)
            .ok_or_else(|| {
                format!(
                    "Plan 의 Application {} 이 Work aggregate 에 없다",
                    repr(app_id)
                )
            })?;
        let evidence = qualifications
            .get_evidence(&application.pass_evidence_id)
            .map_err(|item| item.to_string())?;
        let projection = evidence.structure_projection.ok_or_else(|| {
            format!(
                "PASS Evidence {} 에 structure projection 부재",
                repr(&application.pass_evidence_id)
            )
        })?;
        decode_execution_structure(&projection.payload).map_err(|item| item.to_string())
    };
    let materialized = if is_txt {
        materialize_txt(input, candidate, structure)
    } else {
        materialize_hwpx(input, candidate, structure)
    }
    .map_err(|item| error(item.to_string()))?;
    Ok(materialized)
}

fn start_gate<'a>(
    context: &ManagedRunContext<'_, '_>,
    plan: &'a SealedExecutionPlanSemanticPayload,
    record: &'a ValidatedDataRecord,
) -> Result<StartGate<'a>, ManagedGenerationError> {
    PerWorkFence::with(
        &context.workspace_instance_id,
        &context.work_authority_id,
        || pin_current_start(context, plan, record),
    )
    .map_err(|item| error(item.to_string()))?
}

fn pin_current_start<'a>(
    context: &ManagedRunContext<'_, '_>,
    plan: &'a SealedExecutionPlanSemanticPayload,
    record: &'a ValidatedDataRecord,
) -> Result<StartGate<'a>, ManagedGenerationError> {
    let input = MaterializationInput::new(plan, record).map_err(|item| error(item.to_string()))?;
    let basis = &plan.execution_basis;
    if basis.work_authority_id != context.work_authority_id
        || basis.workspace_instance_id != context.workspace_instance_id
    {
        return Err(error(format!(
            "Plan 의 Work identity ({}, {}) 가 start 요청과 불일치",
            repr(&basis.workspace_instance_id),
            repr(&basis.work_authority_id)
        )));
    }
    let Some(current) = context.observe_current_basis_digest() else {
        return Ok(StartGate::Refused {
            code: CURRENT_BASIS_NOT_SEALABLE.into(),
            detail: "current Work 의 execution basis 를 관찰할 수 없다 — 시작하지 않는다".into(),
        });
    };
    let pinned = execution_basis_digest(basis).map_err(|item| error(item.to_string()))?;
    if current != pinned {
        return Ok(StartGate::Refused {
            code: DIGEST_MISMATCH.into(),
            detail: format!(
                "current basis {current} 가 Plan 의 basis {pinned} 와 불일치(stale Plan)"
            ),
        });
    }
    let admission = evaluate_managed_run_admission(
        context.runtime_registry(),
        plan,
        &context.runtime_capability_manifest_digest,
    );
    if !admission.materialization_startable {
        return Ok(StartGate::Refused {
            code: admission.status,
            detail: "runtime materializer conformance 가 admit 되지 않았다 — 시작하지 않는다"
                .into(),
        });
    }
    Ok(StartGate::Ready(input))
}

fn delivery_targets(
    resolved: &CurrentResolvedDelivery,
) -> Result<(PathBuf, Vec<PathBuf>), ManagedGenerationError> {
    let root = lexical_absolute(Path::new(&resolved.output_directory))
        .map_err(|item| error(item.to_string()))?;
    let mut targets = Vec::with_capacity(resolved.ordered_items.len());
    for item in &resolved.ordered_items {
        let relative = &item.resolved_output_relative_path;
        let target =
            lexical_absolute(&root.join(relative)).map_err(|item| error(item.to_string()))?;
        if !strictly_within(&root, &target) {
            return Err(error(format!(
                "item {} 의 경로가 output directory 밖을 가리킨다: {}",
                item.item_ordinal,
                repr(relative)
            )));
        }
        if ![WRITE_NEW, WRITE_ADD_SUFFIX, WRITE_OVERWRITE]
            .contains(&item.collision_disposition.as_str())
        {
            return Err(error(format!(
                "미지원 collision disposition: {}",
                repr(&item.collision_disposition)
            )));
        }
        targets.push(target);
    }
    Ok((root, targets))
}

fn lexical_absolute(path: &Path) -> io::Result<PathBuf> {
    let absolute = std::path::absolute(path)?;
    let mut clean = PathBuf::new();
    for part in absolute.components() {
        match part {
            Component::Prefix(_) | Component::RootDir | Component::Normal(_) => {
                clean.push(part.as_os_str())
            }
            Component::CurDir => {}
            Component::ParentDir => {
                clean.pop();
            }
        }
    }
    Ok(clean)
}

fn strictly_within(root: &Path, target: &Path) -> bool {
    let root_parts: Vec<_> = root
        .components()
        .map(|part| part.as_os_str().to_string_lossy().to_lowercase())
        .collect();
    let target_parts: Vec<_> = target
        .components()
        .map(|part| part.as_os_str().to_string_lossy().to_lowercase())
        .collect();
    target_parts.len() > root_parts.len() && target_parts.starts_with(&root_parts)
}

fn deliver(
    resolved: &CurrentResolvedDelivery,
    outcomes: Vec<DeliveryOutcome>,
    is_txt: bool,
) -> Result<ManagedGenerationResult, ManagedGenerationError> {
    if outcomes.len() != resolved.ordered_items.len() {
        return Err(error(format!(
            "outcome {}개가 delivery item {}개와 불일치",
            outcomes.len(),
            resolved.ordered_items.len()
        )));
    }
    let (root, targets) = delivery_targets(resolved)?;
    for (item, outcome) in resolved.ordered_items.iter().zip(&outcomes) {
        if let Err((code, detail)) = outcome {
            return Ok(refused(
                code.clone(),
                format!(
                    "item {}({}) 의 materialization 이 닫히지 않아 아무것도 쓰지 않았다: {detail}",
                    item.item_ordinal,
                    repr(&item.resolved_output_relative_path)
                ),
                Some(item.item_ordinal),
            ));
        }
    }
    let mut delivered = Vec::with_capacity(outcomes.len());
    for ((item, outcome), target) in resolved.ordered_items.iter().zip(outcomes).zip(targets) {
        let Ok(bytes) = outcome else {
            unreachable!("preflight checked all outcomes")
        };
        let write = if item.collision_disposition == WRITE_OVERWRITE {
            write_bytes_atomic(&target, &bytes.output_bytes)
        } else {
            write_bytes_atomic_exclusive(&target, &bytes.output_bytes)
        };
        if let Err(item_error) = write {
            let (code, detail) = if item_error.kind() == io::ErrorKind::AlreadyExists {
                (
                    PATH_OCCUPANCY_OBSERVATION_MISMATCH,
                    format!(
                        "item {} 의 대상 {} 이 관찰 이후 생겼다 — 기존 파일을 파괴하지 않고 멈췄다",
                        item.item_ordinal,
                        repr(&item.resolved_output_relative_path)
                    ),
                )
            } else {
                (DELIVERY_WRITE_FAILED, item_error.to_string())
            };
            return Ok(ManagedGenerationResult::Aborted {
                code: code.into(),
                detail,
                failed_item_ordinal: item.item_ordinal,
                delivered,
            });
        }
        delivered.push(DeliveredDocument {
            item_ordinal: item.item_ordinal,
            record_identity: item.record_identity.clone(),
            relative_path: item.resolved_output_relative_path.clone(),
            absolute_path: target,
            collision_disposition: item.collision_disposition.clone(),
            output_digest: bytes.output_digest,
            execution_notes: bytes.execution_notes,
        });
    }
    read_back_delivered(root, delivered, is_txt)
}

fn read_back_delivered(
    root: PathBuf,
    delivered: Vec<DeliveredDocument>,
    is_txt: bool,
) -> Result<ManagedGenerationResult, ManagedGenerationError> {
    for doc in &delivered {
        if let ArtifactObservation::Refused { code, detail } =
            observe_delivered_artifact(&doc.absolute_path, &doc.output_digest, is_txt)
                .map_err(|item| error(item.to_string()))?
        {
            return Ok(ManagedGenerationResult::ReadBackFailed {
                code: code.into(),
                detail,
                failed_item_ordinal: doc.item_ordinal,
                delivered,
            });
        }
    }
    Ok(ManagedGenerationResult::Completed {
        output_directory: root,
        delivered,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use crate::current_execution_preparation::capture_selected_records;
    use crate::job_registry::JobRegistry;
    use crate::slot_configuration_product::SlotConfigurationProduct;
    use crate::template_change_coordinator::TemplateChangeCoordinator;
    use hwpx_core::package::{MIMETYPE_VALUE, PackageEntry};
    use hwpx_filler::candidate_revision::{ContentBlob, blob_digest};
    use hwpx_filler::data_source::Record;
    use hwpx_filler::fields::read_fields;
    use hwpx_filler::generation_delivery::CurrentResolvedDeliveryItem;
    use hwpx_filler::job::Job;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use std::cell::Cell;
    use std::fs;
    use std::sync::Arc;

    const AT: &str = "2026-11-05T12:00:00";

    pub(crate) struct RunFixture {
        pub(crate) root: PathBuf,
        pub(crate) authority: PathBuf,
        pub(crate) jobs: Arc<JobRegistry>,
    }

    fn slot_package(notation: &str) -> Vec<u8> {
        let body = r##"<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="성명"/></hp:ctrl><hp:t>기존</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>
<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="SLOT"><hp:metaTag>{"hwpxFiller":{"kind":"slot","id":"s1","label":"항목"},"name":"#hf"}</hp:metaTag></hp:fieldBegin></hp:ctrl></hp:run></hp:p>
<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="2" type="BOOKMARK" name="OPT1"><hp:metaTag>{"hwpxFiller":{"kind":"slot_option","id":"o1","label":"선택 항목"},"name":"#hf"}</hp:metaTag></hp:fieldBegin></hp:ctrl><hp:ctrl><hp:fieldBegin name="선택"/></hp:ctrl><hp:t>기존</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl><hp:ctrl><hp:fieldEnd beginIDRef="2"/></hp:ctrl></hp:run></hp:p>
<hp:p><hp:run><hp:ctrl><hp:fieldBegin id="3" type="BOOKMARK" name="OPT2"><hp:metaTag>{"hwpxFiller":{"kind":"slot_option","id":"o2","label":"제외 항목"},"name":"#hf"}</hp:metaTag></hp:fieldBegin></hp:ctrl><hp:ctrl><hp:fieldBegin name="제외"/></hp:ctrl><hp:t>기존</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl><hp:ctrl><hp:fieldEnd beginIDRef="3"/></hp:ctrl></hp:run></hp:p>
<hp:p><hp:run><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run></hp:p>"##;
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'>{body}{notation}</hs:sec>"
        );
        HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "mimetype".into(),
                    data: MIMETYPE_VALUE.to_vec(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
            ],
        }
        .to_bytes()
        .unwrap()
    }

    fn output_root() -> PathBuf {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("managed-generation-{}", uuid::Uuid::new_v4()));
        let root = std::path::absolute(root).unwrap();
        fs::create_dir_all(root.join("out")).unwrap();
        root
    }

    fn clean_output_root(path: &Path) {
        let cache = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .canonicalize()
            .unwrap();
        let root = path.canonicalize().unwrap();
        assert!(
            root.starts_with(cache)
                && root
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("managed-generation-")
        );
        fs::remove_dir_all(root).unwrap();
    }

    fn delivery_at(root: &Path) -> CurrentResolvedDelivery {
        CurrentResolvedDelivery {
            exact_pattern: "공고서-{{seq:001}}".into(),
            captured_delivery_clock: AT.into(),
            output_directory: root.join("out").to_string_lossy().into_owned(),
            collision_policy: "ADD_SUFFIX".into(),
            ordered_items: (0..2)
                .map(|ordinal| CurrentResolvedDeliveryItem {
                    record_identity: format!("current-record/0/{ordinal}"),
                    item_ordinal: ordinal,
                    resolved_output_relative_path: format!("공고서-00{}.hwpx", ordinal + 1),
                    collision_disposition: WRITE_NEW.into(),
                    resolved_token_values: vec![],
                })
                .collect(),
        }
    }

    impl RunFixture {
        fn new() -> Self {
            let fixture = Self::with_template("hwpx", &slot_package(""));
            fixture.choose("o1");
            fixture
        }

        pub(crate) fn txt() -> Self {
            Self::with_template(
                "txt",
                concat!(
                    "성명:    {{성명}}\n",
                    "{{#항목 s1 첨부}}\n",
                    "담당: {{성명}}\n",
                    "{{#선택 o1 계약서}}\n",
                    "계약서 {{선택}}\n",
                    "{{/선택}}\n",
                    "{{#선택 o2 견적서}}\n",
                    "견적서 {{제외}}\n",
                    "{{/선택}}\n",
                    "{{/항목}}\n",
                    "끝.\n",
                )
                .as_bytes(),
            )
        }

        pub(crate) fn with_template(media: &str, bytes: &[u8]) -> Self {
            let root = output_root();
            let template = root.join(format!("template.{media}"));
            fs::write(&template, bytes).unwrap();
            let jobs = Arc::new(
                JobRegistry::new(root.join("jobs"), {
                    let templates = root.join("templates");
                    move || templates.clone()
                })
                .unwrap(),
            );
            let mut job = Job {
                name: "생성".into(),
                template_path: template.to_string_lossy().into_owned(),
                mapping: MappingProfile::new(
                    "",
                    ["성명", "선택", "제외"]
                        .into_iter()
                        .map(|field| FieldMapping::new(field, "열", "text", "", "", None).unwrap())
                        .collect(),
                    Map::new(),
                )
                .unwrap(),
                ..Job::default()
            };
            jobs.save(&mut job, false).unwrap();
            let authority = root.join("authority");
            let coordinator =
                TemplateChangeCoordinator::new(&authority, jobs.clone(), || AT.into()).unwrap();
            let initialized = coordinator.ensure_bootstrapped("생성").unwrap();
            assert_eq!(initialized["ok"], true, "{initialized}");
            Self {
                root,
                authority,
                jobs,
            }
        }

        pub(crate) fn choose(&self, option: &str) {
            let selections =
                SlotConfigurationProduct::new(&self.authority, self.jobs.clone(), || AT.into());
            let opened = selections.open_slot_configuration("생성").unwrap();
            let token = opened["current_view"]["new_configuration_token"]
                .as_str()
                .unwrap();
            let selected = selections
                .select_slot_option(
                    "생성",
                    token,
                    "s1",
                    option,
                    &format!("select-{}", uuid::Uuid::new_v4()),
                )
                .unwrap();
            assert_eq!(
                selected["mutation_outcome"]["outcome_code"], "CHANGED",
                "{selected}"
            );
        }

        fn plan(&self, service: &SealExecutionService<'_>) -> SealedExecutionPlanSemanticPayload {
            let response = service.seal("생성", "seal").unwrap();
            let SealTerminalOutcome::Sealed(sealed) = response.terminal_outcome else {
                panic!("fixture plan not sealed")
            };
            sealed.plan_payload.unwrap()
        }

        fn rows(&self) -> Vec<RawDataRecordSnapshot> {
            let rows =
                ["홍길동", "김철수"].map(|name| Record::from_iter([("열".into(), name.into())]));
            capture_selected_records(&rows, &[0, 1], &["열".into()], 0, AT).unwrap()
        }

        fn assert_unwritten(&self) {
            assert_eq!(fs::read_dir(self.root.join("out")).unwrap().count(), 0);
        }
    }

    impl Drop for RunFixture {
        fn drop(&mut self) {
            clean_output_root(&self.root);
        }
    }

    #[test]
    fn unpublished_txt_seals_current_selection_and_preserves_refusal_reasons() {
        let fixture = RunFixture::txt();
        let service =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || AT.into()).unwrap();
        let source = serde_json::json!({"열":"홍길동", "unused":null});
        let render = |record: &Value| {
            materialize_one_unpublished_txt(
                &fixture.authority,
                &service,
                "생성",
                &uuid::Uuid::new_v4().to_string(),
                record.as_object().unwrap(),
                AT,
            )
            .unwrap()
        };
        let assert_refused = |result: UnpublishedTxtResult, expected: &str, reason: &str| {
            let UnpublishedTxtResult::Refused { code, detail } = result else {
                panic!("{result:?}")
            };
            assert_eq!(code, expected);
            assert!(detail.contains(reason), "{detail}");
        };
        assert_refused(
            render(&source),
            "EXECUTION_PLAN_NOT_SEALED",
            "SLOT_CONFIGURATION_INCOMPLETE",
        );
        for (option, expected) in [("o2", "견적서"), ("o1", "계약서")] {
            fixture.choose(option);
            let UnpublishedTxtResult::Materialized(bytes) = render(&source) else {
                panic!("not materialized")
            };
            assert_eq!(
                String::from_utf8(bytes.output_bytes.clone()).unwrap(),
                format!("성명:    홍길동\n담당: 홍길동\n{expected} 홍길동\n끝.\n")
            );
            assert_eq!(bytes.output_digest, blob_digest(&bytes.output_bytes));
        }
        for (value, expected) in [
            (serde_json::json!(12), "12"),
            (serde_json::json!(true), "True"),
            (serde_json::json!("1,000,000"), "1,000,000"),
            (serde_json::json!(null), "〘미입력·성명〙"),
        ] {
            let UnpublishedTxtResult::Materialized(bytes) =
                render(&serde_json::json!({"열":value}))
            else {
                panic!("not materialized")
            };
            assert!(
                String::from_utf8(bytes.output_bytes)
                    .unwrap()
                    .contains(expected)
            );
        }
        assert_refused(
            render(&serde_json::json!({"other":"value"})),
            RECORD_VALIDATION_BLOCKED,
            "RECORD_REQUIRED_VALUE_MISSING",
        );
        let mut plan = fixture.plan(&service);
        assert_refused(
            materialize_sealed_txt(&fixture.authority, None, &plan, &Map::new(), AT).unwrap(),
            "TEMPLATE_INITIALIZATION_REQUIRED",
            "실행 권위",
        );
        let context = service.managed_run_context("생성", "txt").unwrap().unwrap();
        plan.execution_basis.qualification_profile_semantic_digest = "sha256:stale".into();
        assert_refused(
            materialize_sealed_txt(
                &fixture.authority,
                Some(&context),
                &plan,
                source.as_object().unwrap(),
                AT,
            )
            .unwrap(),
            DIGEST_MISMATCH,
            "stale Plan",
        );
        assert_refused(
            render(&serde_json::json!({"열":"{{unknown}}"})),
            "FIELD_TEXT_MISMATCH",
            "미치환 필드 토큰",
        );
        let mut job = fixture.jobs.load("생성").unwrap();
        let complete = job.clone();
        job.mapping
            .mappings
            .retain(|field| field.template_field != "선택");
        fixture.jobs.save(&mut job, true).unwrap();
        assert_refused(
            render(&source),
            "EXECUTION_PLAN_NOT_SEALED",
            "ACTIVE_FIELD_UNBOUND",
        );
        job = complete;
        job.authority_id.clear();
        fixture.jobs.save(&mut job, true).unwrap();
        assert_refused(
            render(&source),
            "TEMPLATE_INITIALIZATION_REQUIRED",
            "템플릿 확인",
        );
        job.template_path = fixture
            .root
            .join("invalid.hwpx")
            .to_string_lossy()
            .into_owned();
        fixture.jobs.save(&mut job, true).unwrap();
        assert_refused(render(&source), "TXT_MEDIA_REQUIRED", "TXT 작업");
        fixture.assert_unwritten();
    }

    #[test]
    fn txt_seal_refusals_restate_policy_staleness_and_missing_payload() {
        use hwpx_filler::stored_execution_plan::{
            ExecutionPlanSealed, ExecutionPolicyBlocked, ExecutionQualificationBlocked,
            StaleExecutionBasis,
        };
        let blocked = ExecutionQualificationBlocked {
            capture_evidence_ref: "evidence".into(),
            normalized_blockers: vec![],
            captured_execution_input_digest: None,
            captured_attempt_digest: None,
        };
        let cases = [
            (
                SealTerminalOutcome::QualificationBlocked(blocked.clone()),
                "실행 계획을 봉인할 수 없습니다.",
            ),
            (
                SealTerminalOutcome::QualificationBlocked(ExecutionQualificationBlocked {
                    normalized_blockers: vec!["구성".into()],
                    ..blocked
                }),
                "실행 계획을 봉인할 수 없습니다: 구성",
            ),
            (
                SealTerminalOutcome::PolicyBlocked(ExecutionPolicyBlocked {
                    policy_code: "정책".into(),
                    qualification_profile_id: None,
                    observed_policy_version: None,
                    policy_observation_digest: None,
                    captured_attempt_digest: None,
                }),
                "실행 계획을 봉인할 수 없습니다: 정책",
            ),
            (
                SealTerminalOutcome::Stale(StaleExecutionBasis {
                    captured_execution_input_digest: "input".into(),
                    candidate_execution_basis_digest: "basis".into(),
                    stale_reason: DIGEST_MISMATCH.into(),
                    observed_current_summary: None,
                }),
                "실행 기준이 그사이 바뀌었습니다: DIGEST_MISMATCH",
            ),
            (
                SealTerminalOutcome::Sealed(Box::new(ExecutionPlanSealed {
                    execution_basis_digest: "basis".into(),
                    plan_payload: None,
                })),
                "봉인 결과에 실행 payload 가 없습니다.",
            ),
        ];
        for (terminal, expected) in cases {
            let Err(UnpublishedTxtResult::Refused { code, detail }) = txt_sealed_plan(terminal)
            else {
                panic!("seal refusal became a plan")
            };
            assert_eq!(code, "EXECUTION_PLAN_NOT_SEALED");
            assert_eq!(detail, expected);
        }
    }

    #[test]
    fn slot_bearing_run_materializes_each_record_and_preserves_progress_and_digests() {
        let fixture = RunFixture::new();
        let service =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || AT.into()).unwrap();
        let plan = fixture.plan(&service);
        let context = service
            .managed_run_context("생성", "hwpx")
            .unwrap()
            .unwrap();
        let mut progress = vec![];
        let result = run_managed_generation(
            ManagedGenerationInput {
                authority_root: &fixture.authority,
                context: &context,
                plan: &plan,
                snapshots: &fixture.rows(),
                resolved: &delivery_at(&fixture.root),
                validated_at: AT,
            },
            || false,
            |done, total| progress.push((done, total)),
        )
        .unwrap();
        let ManagedGenerationResult::Completed { delivered, .. } = result else {
            panic!("{result:?}")
        };
        assert_eq!(progress, [(1, 2), (2, 2)]);
        assert_eq!(delivered.len(), 2);
        for (document, name) in delivered.iter().zip(["홍길동", "김철수"]) {
            let bytes = fs::read(&document.absolute_path).unwrap();
            assert_eq!(document.output_digest, blob_digest(&bytes));
            let package = HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap();
            assert_eq!(
                read_fields(&package).unwrap(),
                [("성명".into(), name.into()), ("선택".into(), name.into())]
            );
        }
        assert_ne!(delivered[0].output_digest, delivered[1].output_digest);
    }

    #[test]
    fn applied_hwpx_evidence_drives_option_labels_and_binding_review() {
        use hwpx_filler::execution_structure::{
            LABELED_EXECUTION_QUALIFICATION_PROFILE_ID,
            LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, content_digest,
            decode_execution_structure,
        };
        let fixture = RunFixture::with_template("hwpx", &slot_package(""));
        let job = fixture.jobs.load("생성").unwrap();
        let works = AtomicWorkTemplateStateStore::new(fixture.authority.join("works")).unwrap();
        let aggregate = works.load(&job.authority_id).unwrap();
        let application = aggregate
            .applications
            .iter()
            .find(|item| item.application_id == aggregate.work.current_template_application_id)
            .unwrap();
        let evidence = FileQualificationObjectStore::new(fixture.authority.join("qualification"))
            .get_evidence(&application.pass_evidence_id)
            .unwrap();
        assert_eq!(evidence.result, "PASS");
        assert_eq!(
            evidence.qualification_profile_id,
            LABELED_EXECUTION_QUALIFICATION_PROFILE_ID
        );
        let projection = evidence.structure_projection.unwrap();
        assert_eq!(
            projection.projection_schema_version,
            LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA
        );
        assert_eq!(
            projection.payload_digest,
            content_digest(&projection.payload)
        );
        let structure = decode_execution_structure(&projection.payload).unwrap();
        assert_eq!(structure.product_structure.root_fields, ["성명"]);
        assert_eq!(
            structure.product_structure.slots[0].label.as_deref(),
            Some("항목")
        );
        assert_eq!(
            structure.product_structure.slots[0]
                .options
                .iter()
                .map(|item| (item.id.as_str(), item.label.as_deref()))
                .collect::<Vec<_>>(),
            [("o1", Some("선택 항목")), ("o2", Some("제외 항목"))]
        );
        assert!(structure.global_composition_facts.crossing_free);
        assert_eq!(structure.field_occurrences.len(), 3);
        let seal =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || AT.into()).unwrap();
        assert!(seal.current_binding_review("생성").unwrap().is_none());
        for (option, active) in [("o1", "선택"), ("o2", "제외")] {
            fixture.choose(option);
            let review = seal.current_binding_review("생성").unwrap().unwrap();
            assert_eq!(review.active_field_ids, ["성명", active]);
            assert_eq!(
                review
                    .input_requirements
                    .iter()
                    .filter(|item| item.binding_state != "INACTIVE_ONLY")
                    .map(|item| item.field_id.as_str())
                    .collect::<Vec<_>>(),
                ["성명", active]
            );
            assert!(matches!(
                seal.seal("생성", option).unwrap().terminal_outcome,
                SealTerminalOutcome::Sealed(_)
            ));
        }
        let plan = fixture.plan(&seal);
        let context = seal.managed_run_context("생성", "hwpx").unwrap().unwrap();
        let snapshots = fixture.rows();
        let mut delivery = delivery_at(&fixture.root);
        delivery.ordered_items.truncate(1);
        let result = run_managed_generation(
            ManagedGenerationInput {
                authority_root: &fixture.authority,
                context: &context,
                plan: &plan,
                snapshots: &snapshots[..1],
                resolved: &delivery,
                validated_at: AT,
            },
            || false,
            |_, _| {},
        )
        .unwrap();
        let ManagedGenerationResult::Completed { delivered, .. } = result else {
            panic!("selected second option did not materialize: {result:?}")
        };
        let generated = fs::read(&delivered[0].absolute_path).unwrap();
        let package = HwpxPackage::from_bytes(&generated, PackageLimits::default()).unwrap();
        assert_eq!(
            read_fields(&package).unwrap(),
            [
                ("성명".into(), "홍길동".into()),
                ("제외".into(), "홍길동".into())
            ]
        );
    }

    #[test]
    fn start_gate_pins_current_authority_and_releases_its_fence_on_every_exit() {
        use crate::per_work_fence::tests::assert_released;
        let fixture = RunFixture::new();
        let service =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || AT.into()).unwrap();
        let plan = fixture.plan(&service);
        let mut context = service
            .managed_run_context("생성", "hwpx")
            .unwrap()
            .unwrap();
        let records = validate_records(&plan, &fixture.rows(), AT, AT).unwrap();
        let released = |context: &ManagedRunContext<'_, '_>| {
            assert_released(&context.workspace_instance_id, &context.work_authority_id)
        };
        let StartGate::Ready(input) = start_gate(&context, &plan, &records[0]).unwrap() else {
            panic!("current start refused")
        };
        released(&context);
        let candidates = FileCandidateObjectStore::new(fixture.authority.join("candidates"));
        let works = AtomicWorkTemplateStateStore::new(fixture.authority.join("works")).unwrap();
        let qualifications =
            FileQualificationObjectStore::new(fixture.authority.join("qualification"));
        assert!(matches!(
            materialize_native(&input, false, &candidates, &works, &qualifications).unwrap(),
            MaterializationOutcome::Materialized(_)
        ));
        fixture.assert_unwritten();

        let mut corrupt = records[0].clone();
        corrupt.validated_record_digest = "sha256:wrong".into();
        assert!(start_gate(&context, &plan, &corrupt).is_err());
        released(&context);
        let work_id = context.work_authority_id.clone();
        let workspace_id = context.workspace_instance_id.clone();
        for identity in ["work", "workspace"] {
            if identity == "work" {
                context.work_authority_id = "another-work".into();
            } else {
                context.workspace_instance_id = "another-workspace".into();
            }
            assert!(start_gate(&context, &plan, &records[0]).is_err());
            released(&context);
            context.work_authority_id = work_id.clone();
            context.workspace_instance_id = workspace_id.clone();
        }
        let manifest = context.runtime_capability_manifest_digest.clone();
        context.runtime_capability_manifest_digest = "sha256:unadmitted".into();
        let StartGate::Refused { code, .. } = start_gate(&context, &plan, &records[0]).unwrap()
        else {
            panic!("unadmitted runtime started")
        };
        assert_eq!(
            code,
            hwpx_filler::generation_delivery::MANAGED_RUN_CONSTRUCTION_ONLY
        );
        released(&context);
        context.runtime_capability_manifest_digest = manifest;
        let mut stale = plan.clone();
        stale.execution_basis.qualification_profile_semantic_digest = "sha256:other-profile".into();
        let stale_records = validate_records(&stale, &fixture.rows(), AT, AT).unwrap();
        let StartGate::Refused { code, .. } =
            start_gate(&context, &stale, &stale_records[0]).unwrap()
        else {
            panic!("stale plan started")
        };
        assert_eq!(code, DIGEST_MISMATCH);
        released(&context);
        fixture.jobs.delete("생성").unwrap();
        let StartGate::Refused { code, .. } = start_gate(&context, &plan, &records[0]).unwrap()
        else {
            panic!("unobservable authority started")
        };
        assert_eq!(code, CURRENT_BASIS_NOT_SEALABLE);
        released(&context);
        fixture.assert_unwritten();
    }

    #[test]
    fn managed_preflight_cancel_stale_and_candidate_failures_leave_output_empty() {
        let fixture = RunFixture::new();
        let service =
            SealExecutionService::new(&fixture.authority, &fixture.jobs, || AT.into()).unwrap();
        let plan = fixture.plan(&service);
        let context = service
            .managed_run_context("생성", "hwpx")
            .unwrap()
            .unwrap();
        let rows = fixture.rows();
        let delivery = delivery_at(&fixture.root);
        let run = |plan: &SealedExecutionPlanSemanticPayload,
                   rows: &[RawDataRecordSnapshot],
                   cancel: &dyn Fn() -> bool| {
            run_managed_generation(
                ManagedGenerationInput {
                    authority_root: &fixture.authority,
                    context: &context,
                    plan,
                    snapshots: rows,
                    resolved: &delivery,
                    validated_at: AT,
                },
                cancel,
                |_, _| {},
            )
        };
        let calls = Cell::new(0);
        let result = run(&plan, &rows, &|| {
            let at = calls.get();
            calls.set(at + 1);
            at == 1
        })
        .unwrap();
        assert_eq!(
            result,
            ManagedGenerationResult::Cancelled {
                attempted: 1,
                total: 2
            }
        );
        fixture.assert_unwritten();
        let missing =
            build_raw_record_snapshot(&[], vec![], "missing", rows[0].capture_provenance.clone())
                .unwrap();
        let mut corrupt = rows[0].clone();
        corrupt.raw_record_digest = "sha256:forged".into();
        for (row, expected) in [
            (missing, RECORD_VALIDATION_BLOCKED),
            (corrupt, "RAW_RECORD_INTEGRITY_ERROR"),
        ] {
            let result = run(&plan, &[row], &|| false).unwrap();
            let ManagedGenerationResult::Refused { code, .. } = result else {
                panic!("{result:?}")
            };
            assert_eq!(code, expected);
            fixture.assert_unwritten();
        }
        let mut stale = plan.clone();
        stale.execution_basis.qualification_profile_semantic_digest = "sha256:stale".into();
        let result = run(&stale, &rows, &|| false).unwrap();
        let ManagedGenerationResult::Refused {
            code,
            failed_item_ordinal,
            ..
        } = result
        else {
            panic!("{result:?}")
        };
        assert_eq!(code, DIGEST_MISMATCH);
        assert_eq!(failed_item_ordinal, Some(0));
        fixture.assert_unwritten();
        let mut foreign = plan.clone();
        foreign.execution_basis.template.exact_content_digest =
            format!("sha256:{}", "f".repeat(64));
        assert!(run(&foreign, &rows, &|| false).is_err());
        fixture.assert_unwritten();
        let store = FileCandidateObjectStore::new(fixture.authority.join("candidates"));
        for (bytes, expected) in [
            (
                b"not a ZIP".to_vec(),
                APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            ),
            (
                slot_package(
                    "<hp:p><hp:run><hp:t>{{#항목 특약 특약 사항}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>{{/항목}}</hp:t></hp:run></hp:p>",
                ),
                STRUCTURE_NOTATION_UNCOMPILED,
            ),
        ] {
            let blob = ContentBlob::new(
                blob_digest(&bytes),
                "hwpx".into(),
                bytes.clone().into(),
                bytes.len(),
                "sha256".into(),
            )
            .unwrap();
            store.put_blob(&blob).unwrap();
            let mut changed = plan.clone();
            changed.execution_basis.template.exact_content_digest = blob.digest;
            let result = run(&changed, &rows, &|| false).unwrap();
            let ManagedGenerationResult::Refused { code, detail, .. } = result else {
                panic!("{result:?}")
            };
            assert_eq!(code, expected);
            if expected == STRUCTURE_NOTATION_UNCOMPILED {
                assert!(detail.contains("2건"));
            }
            fixture.assert_unwritten();
        }
    }

    #[test]
    fn readback_failure_keeps_delivered_files_and_reports_the_first_failed_ordinal() {
        let root = output_root();
        let delivery = delivery_at(&root);
        let bytes = slot_package("");
        let materialized = |digest: String| {
            Ok(MaterializedDocumentBytes {
                plan_semantic_digest: "plan".into(),
                validated_record_ref: "record".into(),
                output_bytes: bytes.clone(),
                output_digest: digest,
                execution_notes: vec![],
            })
        };
        let result = deliver(
            &delivery,
            vec![
                materialized(blob_digest(&bytes)),
                materialized("sha256:changed".into()),
            ],
            false,
        )
        .unwrap();
        let ManagedGenerationResult::ReadBackFailed {
            code,
            failed_item_ordinal,
            delivered,
            ..
        } = result
        else {
            panic!("{result:?}")
        };
        assert_eq!(code, "ARTIFACT_DIGEST_MISMATCH");
        assert_eq!(failed_item_ordinal, 1);
        assert_eq!(
            delivered
                .iter()
                .map(|item| item.relative_path.as_str())
                .collect::<Vec<_>>(),
            ["공고서-001.hwpx", "공고서-002.hwpx"]
        );
        for document in &delivered {
            assert_eq!(fs::read(&document.absolute_path).unwrap(), bytes);
            let ArtifactObservation::Observed(exact) =
                observe_delivered_artifact(&document.absolute_path, &blob_digest(&bytes), false)
                    .unwrap()
            else {
                panic!("valid file refused")
            };
            assert_eq!(exact, bytes);
        }
        let path = &delivered[1].absolute_path;
        for case in ["missing", "tampered", "broken-zip"] {
            let mut records = delivered.clone();
            let mut changed = bytes.clone();
            match case {
                "missing" => {
                    fs::remove_file(path).unwrap();
                }
                "tampered" => {
                    *changed.last_mut().unwrap() ^= 0xff;
                    fs::write(path, &changed).unwrap();
                }
                _ => {
                    changed = b"PK\x03\x04 not an OCF package".to_vec();
                    fs::write(path, &changed).unwrap();
                }
            }
            records[1].output_digest = blob_digest(if case == "broken-zip" {
                &changed
            } else {
                &bytes
            });
            let result = read_back_delivered(root.join("out"), records.clone(), false).unwrap();
            let ManagedGenerationResult::ReadBackFailed {
                code,
                detail,
                failed_item_ordinal,
                delivered: retained,
            } = result
            else {
                panic!("{result:?}")
            };
            assert_eq!(failed_item_ordinal, 1);
            assert_eq!(retained, records);
            assert!(detail.contains(&path.display().to_string()));
            assert_eq!(
                code,
                match case {
                    "missing" => "ARTIFACT_FILE_MISSING",
                    "tampered" => "ARTIFACT_DIGEST_MISMATCH",
                    _ => "ARTIFACT_REPARSE_FAILED",
                }
            );
            if case == "tampered" {
                assert!(detail.contains(&blob_digest(&bytes)));
                assert!(detail.contains(&blob_digest(&changed)));
            }
        }
        for (text, valid) in [(b"\xff".as_slice(), false), ("문서\n".as_bytes(), true)] {
            fs::write(path, text).unwrap();
            let observed = observe_delivered_artifact(path, &blob_digest(text), true).unwrap();
            match observed {
                ArtifactObservation::Observed(exact) => {
                    assert!(valid);
                    assert_eq!(exact, text);
                }
                ArtifactObservation::Refused { code, .. } => {
                    assert!(!valid);
                    assert_eq!(code, "ARTIFACT_REPARSE_FAILED");
                }
            }
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let locked = fs::OpenOptions::new()
                .read(true)
                .share_mode(0)
                .open(path)
                .unwrap();
            assert!(
                observe_delivered_artifact(path, "digest", true).is_err(),
                "locked file must not become missing or successful"
            );
            drop(locked);
        }
        clean_output_root(&root);
    }

    #[test]
    fn delivery_path_preflight_refuses_escape_before_any_write() {
        let item = |name: &str| CurrentResolvedDeliveryItem {
            record_identity: "record".into(),
            item_ordinal: 0,
            resolved_output_relative_path: name.into(),
            collision_disposition: WRITE_NEW.into(),
            resolved_token_values: vec![],
        };
        let mut delivery = CurrentResolvedDelivery {
            exact_pattern: "{{name}}".into(),
            captured_delivery_clock: "2026-11-05T12:00:00".into(),
            output_directory: ".cache/managed-output".into(),
            collision_policy: "FAIL".into(),
            ordered_items: vec![item("../escape.hwpx")],
        };
        assert!(
            delivery_targets(&delivery)
                .unwrap_err()
                .to_string()
                .contains("밖을 가리킨다")
        );
        delivery.ordered_items = vec![item("C:/escape.hwpx")];
        assert!(delivery_targets(&delivery).is_err());
        delivery.ordered_items = vec![item("nested/inside.hwpx")];
        assert!(delivery_targets(&delivery).is_ok());
        let absolute_inside = std::path::absolute(".cache/managed-output/inside.hwpx").unwrap();
        delivery.ordered_items = vec![item(&absolute_inside.to_string_lossy())];
        assert!(delivery_targets(&delivery).is_ok());

        let root = output_root();
        delivery.output_directory = root.join("out").to_string_lossy().into_owned();
        for path in ["../escape.hwpx", "..\\escape.hwpx", "Z:\\outside.hwpx", ""] {
            delivery.ordered_items = vec![item("valid.hwpx"), item(path)];
            assert!(
                deliver(
                    &delivery,
                    vec![Ok(document(b"first")), Ok(document(b"second"))],
                    true
                )
                .is_err(),
                "{path}"
            );
            assert_eq!(fs::read_dir(root.join("out")).unwrap().count(), 0);
        }
        delivery.ordered_items = vec![item("valid.hwpx")];
        assert!(deliver(&delivery, vec![], true).is_err());
        delivery.ordered_items[0].collision_disposition = "WRITE_IF_ABSENT".into();
        assert!(deliver(&delivery, vec![Ok(document(b"first"))], true).is_err());
        delivery.ordered_items = vec![item("first.hwpx"), item("second.hwpx")];
        delivery.ordered_items[1].item_ordinal = 1;
        fs::write(root.join("out/keep.hwpx"), b"KEEP").unwrap();
        for code in ["REMOVAL_INCOMPLETE", DIGEST_MISMATCH] {
            let result = deliver(
                &delivery,
                vec![Ok(document(b"first")), Err((code.into(), "reason".into()))],
                true,
            )
            .unwrap();
            let ManagedGenerationResult::Refused {
                code: actual,
                failed_item_ordinal,
                ..
            } = result
            else {
                panic!("{result:?}")
            };
            assert_eq!(actual, code);
            assert_eq!(failed_item_ordinal, Some(1));
            assert_eq!(fs::read_dir(root.join("out")).unwrap().count(), 1);
            assert_eq!(fs::read(root.join("out/keep.hwpx")).unwrap(), b"KEEP");
        }
        clean_output_root(&root);
    }

    fn document(bytes: &[u8]) -> MaterializedDocumentBytes {
        MaterializedDocumentBytes {
            plan_semantic_digest: "plan".into(),
            validated_record_ref: "record".into(),
            output_bytes: bytes.to_vec(),
            output_digest: blob_digest(bytes),
            execution_notes: vec![],
        }
    }

    #[test]
    fn delivery_dispositions_preserve_existing_files_and_report_partial_os_failures() {
        let root = output_root();
        let mut delivery = delivery_at(&root);
        let mut third = delivery.ordered_items[1].clone();
        third.item_ordinal = 2;
        third.record_identity = "third".into();
        third.resolved_output_relative_path = "overwrite.txt".into();
        third.collision_disposition = WRITE_OVERWRITE.into();
        delivery.ordered_items.push(third);
        delivery.ordered_items[1].collision_disposition = WRITE_ADD_SUFFIX.into();
        fs::write(root.join("out/overwrite.txt"), b"OLD").unwrap();
        let note = FillNote {
            field: "빈칸".into(),
            kind: hwpx_filler::fields::FillNoteKind::SlotSynthesized,
            detail: vec![],
        };
        let mut first = document(b"first");
        first.execution_notes.push(note.clone());
        let result = deliver(
            &delivery,
            vec![Ok(first), Ok(document(b"second")), Ok(document(b"third"))],
            true,
        )
        .unwrap();
        let ManagedGenerationResult::Completed { delivered, .. } = result else {
            panic!("{result:?}")
        };
        assert_eq!(delivered[0].execution_notes, [note]);
        assert_eq!(delivered[0].record_identity, "current-record/0/0");
        assert_eq!(
            delivered
                .iter()
                .map(|doc| doc.item_ordinal)
                .collect::<Vec<_>>(),
            [0, 1, 2]
        );
        for (doc, expected) in delivered
            .iter()
            .zip([b"first".as_slice(), b"second", b"third"])
        {
            assert_eq!(fs::read(&doc.absolute_path).unwrap(), expected);
            assert_eq!(doc.output_digest, blob_digest(expected));
        }

        for (case, disposition, expected_code) in [
            ("new-race", WRITE_NEW, PATH_OCCUPANCY_OBSERVATION_MISMATCH),
            (
                "suffix-race",
                WRITE_ADD_SUFFIX,
                PATH_OCCUPANCY_OBSERVATION_MISMATCH,
            ),
            ("os-failure", WRITE_NEW, DELIVERY_WRITE_FAILED),
        ] {
            let out = root.join(case);
            fs::create_dir_all(&out).unwrap();
            delivery.output_directory = out.to_string_lossy().into_owned();
            delivery.ordered_items[0].resolved_output_relative_path = "first.txt".into();
            delivery.ordered_items[1].resolved_output_relative_path = if case == "os-failure" {
                "parent/second.txt"
            } else {
                "second.txt"
            }
            .into();
            delivery.ordered_items[1].collision_disposition = disposition.into();
            delivery.ordered_items[2].resolved_output_relative_path = "third.txt".into();
            let obstacle = out.join(if case == "os-failure" {
                "parent"
            } else {
                "second.txt"
            });
            fs::write(&obstacle, b"KEEP").unwrap();
            let result = deliver(
                &delivery,
                vec![
                    Ok(document(b"first")),
                    Ok(document(b"second")),
                    Ok(document(b"third")),
                ],
                true,
            )
            .unwrap();
            let ManagedGenerationResult::Aborted {
                code,
                detail,
                failed_item_ordinal,
                delivered,
            } = result
            else {
                panic!("{result:?}")
            };
            assert_eq!(code, expected_code);
            assert!(!detail.is_empty());
            assert_eq!(failed_item_ordinal, 1);
            assert_eq!(delivered.len(), 1);
            assert_eq!(fs::read(&delivered[0].absolute_path).unwrap(), b"first");
            assert_eq!(fs::read(&obstacle).unwrap(), b"KEEP");
            assert!(!out.join("third.txt").exists());
            assert_eq!(fs::read_dir(&out).unwrap().count(), 2);
        }
        clean_output_root(&root);
    }
}
