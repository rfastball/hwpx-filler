//! One-shot host composition for CLI generation using the managed execution kernels.

use crate::current_execution_preparation::{
    CurrentRecordPreparation, capture_selected_records, delivery_blocker_phrase,
    prepare_current_delivery, prepare_current_records,
};
use crate::job_registry::JobRegistry;
use crate::managed_generation_service::{
    ManagedGenerationInput, ManagedGenerationResult, run_managed_generation,
};
use crate::seal_execution_service::{SealExecutionResponse, SealExecutionService};
use crate::template_change_coordinator::TemplateChangeCoordinator;
use hwpx_filler::data_source::Record;
use hwpx_filler::execution_contract_set::SealedExecutionPlanSemanticPayload;
use hwpx_filler::fresh_execution_observation::FreshExecutionObservation;
use hwpx_filler::generation_delivery::{
    CurrentResolvedDelivery, DeliveryPlanResult, WRITE_OVERWRITE,
};
use hwpx_filler::job::Job;
use hwpx_filler::mapping::MappingProfile;
use hwpx_filler::run_delivery_intent::RunDeliveryIntent;
use hwpx_filler::stored_execution_plan::SealTerminalOutcome;
use std::fs;
use std::path::Path;
use std::sync::Arc;

pub const HEADLESS_WORK_NAME: &str = "cli-run";
pub const TEMPLATE_INITIALIZATION: &str = "TEMPLATE_INITIALIZATION";
pub const EXECUTION_NOT_SEALABLE: &str = "EXECUTION_NOT_SEALABLE";
pub const RECORD_VALIDATION: &str = "RECORD_VALIDATION";
pub const DELIVERY_PLAN: &str = "DELIVERY_PLAN";

pub struct HeadlessRefused {
    pub stage: &'static str,
    pub code: String,
    pub details: Vec<String>,
}
pub struct HeadlessNeedsOverwrite {
    pub conflict_names: Vec<String>,
}
pub struct HeadlessExecuted {
    pub outcome: ManagedGenerationResult,
    pub work_authority_id: String,
    pub execution_basis_digest: String,
    pub plan_payload: SealedExecutionPlanSemanticPayload,
    pub resolved_delivery: CurrentResolvedDelivery,
    pub validated_at: String,
}
pub enum HeadlessGenerationResult {
    Refused(HeadlessRefused),
    NeedsOverwrite(HeadlessNeedsOverwrite),
    Executed(Box<HeadlessExecuted>),
}

pub struct HeadlessInput<'a> {
    pub workspace: &'a Path,
    pub template_path: &'a Path,
    pub mapping: &'a MappingProfile,
    pub filename_pattern: &'a str,
    pub records: &'a [Record],
    pub source_schema_keys: &'a [String],
    pub output_directory: &'a Path,
    pub overwrite: bool,
    pub clock: Arc<dyn Fn() -> String + Send + Sync>,
}

fn refused(
    stage: &'static str,
    code: impl Into<String>,
    details: Vec<String>,
) -> HeadlessGenerationResult {
    HeadlessGenerationResult::Refused(HeadlessRefused {
        stage,
        code: code.into(),
        details,
    })
}

fn seal_refusal(
    service: &SealExecutionService,
    mapping: &MappingProfile,
    fresh: &FreshExecutionObservation,
) -> Result<HeadlessGenerationResult, String> {
    let mut details = match fresh {
        FreshExecutionObservation::WorkBlocked(item) => item.normalized_blockers_or_policy.clone(),
        _ => Vec::new(),
    };
    let mapped = mapping
        .mappings
        .iter()
        .map(|item| item.template_field.as_str())
        .collect::<std::collections::HashSet<_>>();
    if let Some(active) = service
        .current_active_field_ids(HEADLESS_WORK_NAME)
        .map_err(|error| error.to_string())?
    {
        let pending = active
            .iter()
            .filter(|field| !mapped.contains(field.as_str()))
            .map(String::as_str)
            .collect::<Vec<_>>();
        if !pending.is_empty() {
            details.push(format!("연결이 필요한 필드: {}", pending.join(", ")));
        }
    }
    let code = match fresh {
        FreshExecutionObservation::WorkBlocked(item) => item.current_sealability.clone(),
        FreshExecutionObservation::ContextError(item) => item.code.clone(),
        FreshExecutionObservation::Sealed(_) => "SEALED_PLAN_PAYLOAD_MISSING".into(),
    };
    Ok(refused(EXECUTION_NOT_SEALABLE, code, details))
}

fn prepare_records(
    plan: &SealedExecutionPlanSemanticPayload,
    records: &[Record],
    source_schema_keys: &[String],
    captured_at: &str,
) -> Result<CurrentRecordPreparation, HeadlessGenerationResult> {
    let indices = (0..records.len()).collect::<Vec<_>>();
    let snapshots = capture_selected_records(records, &indices, source_schema_keys, 0, captured_at)
        .map_err(|detail| {
            refused(
                RECORD_VALIDATION,
                "CURRENT_RECORD_CAPTURE_FAILED",
                vec![detail],
            )
        })?;
    if snapshots.is_empty() {
        return Err(refused(
            RECORD_VALIDATION,
            "CURRENT_RECORD_CAPTURE_FAILED",
            vec!["데이터 레코드가 없습니다.".into()],
        ));
    }
    let prepared = prepare_current_records(plan, 0, snapshots, &indices, source_schema_keys)
        .map_err(|error| refused(RECORD_VALIDATION, error.code, vec![error.detail]))?;
    if !prepared.issues.is_empty() {
        return Err(refused(
            RECORD_VALIDATION,
            "RECORD_VALIDATION_BLOCKED",
            prepared
                .issues
                .iter()
                .map(|issue| {
                    format!(
                        "{} {}: {}",
                        issue.record_display_locator, issue.field_display_label, issue.message
                    )
                })
                .collect(),
        ));
    }
    Ok(prepared)
}

fn delivery_result(
    result: DeliveryPlanResult<CurrentResolvedDelivery>,
) -> Result<CurrentResolvedDelivery, HeadlessGenerationResult> {
    match result {
        DeliveryPlanResult::Ready(value) => Ok(value),
        DeliveryPlanResult::ContextError(error) => {
            Err(refused(DELIVERY_PLAN, error.code, vec![error.detail]))
        }
        DeliveryPlanResult::Blocked(blockers) => {
            let code = blockers
                .first()
                .map_or("DELIVERY_PLAN_BLOCKED", |item| item.code.as_str());
            let details = blockers
                .iter()
                .map(|item| {
                    let mut parts = vec![delivery_blocker_phrase(&item.code).to_owned()];
                    if let Some(path) = &item.conflicting_relative_path {
                        parts.push(path.clone());
                    }
                    if !item.detail.is_empty() {
                        parts.push(format!("({})", item.detail));
                    }
                    parts.join(" ")
                })
                .collect();
            Err(refused(DELIVERY_PLAN, code, details))
        }
    }
}

fn pending_overwrite(
    delivery: &CurrentResolvedDelivery,
    authorized: bool,
) -> Option<HeadlessNeedsOverwrite> {
    let conflict_names = delivery
        .ordered_items
        .iter()
        .filter(|item| item.collision_disposition == WRITE_OVERWRITE)
        .map(|item| item.resolved_output_relative_path.clone())
        .collect::<Vec<_>>();
    (!authorized && !conflict_names.is_empty()).then_some(HeadlessNeedsOverwrite { conflict_names })
}

/// Caller owns and later deletes `workspace`; only delivered files survive it.
pub fn run_headless_generation(
    input: HeadlessInput<'_>,
) -> Result<HeadlessGenerationResult, String> {
    let workspace = input.workspace;
    let template_path = input.template_path;
    let mapping = input.mapping;
    let filename_pattern = input.filename_pattern;
    let clock = &input.clock;
    let template = fs::canonicalize(template_path).map_err(|error| error.to_string())?;
    let template_root = workspace.join("templates");
    let jobs = Arc::new(
        JobRegistry::new(workspace.join("jobs"), move || template_root.clone())
            .map_err(|error| error.to_string())?,
    );
    let mut job = Job {
        name: HEADLESS_WORK_NAME.into(),
        template_path: template.to_string_lossy().into_owned(),
        mapping: mapping.clone(),
        filename_pattern: filename_pattern.into(),
        ..Job::default()
    };
    jobs.save(&mut job, false)
        .map_err(|error| error.to_string())?;
    let authority = workspace.join("authority");
    let coordinator = TemplateChangeCoordinator::new(&authority, jobs.clone(), {
        let clock = clock.clone();
        move || clock()
    })
    .map_err(|error| error.to_string())?;
    let bootstrap = coordinator
        .ensure_bootstrapped(HEADLESS_WORK_NAME)
        .map_err(|error| error.to_string())?;
    if bootstrap.get("ok").and_then(|value| value.as_bool()) != Some(true)
        || bootstrap
            .get("bootstrapped")
            .and_then(|value| value.as_bool())
            != Some(true)
    {
        return Ok(refused(
            TEMPLATE_INITIALIZATION,
            bootstrap
                .get("reason")
                .and_then(|value| value.as_str())
                .filter(|reason| !reason.is_empty())
                .unwrap_or("initialization_required"),
            Vec::new(),
        ));
    }
    let service = SealExecutionService::new(&authority, &jobs, {
        let clock = clock.clone();
        move || clock()
    })
    .map_err(|error| error.to_string())?;
    let response = service
        .seal(
            HEADLESS_WORK_NAME,
            &uuid::Uuid::new_v4().simple().to_string(),
        )
        .map_err(|error| error.to_string())?;
    finish_sealed_generation(input, &authority, &service, response)
}

fn finish_sealed_generation(
    input: HeadlessInput<'_>,
    authority: &Path,
    service: &SealExecutionService<'_>,
    response: SealExecutionResponse,
) -> Result<HeadlessGenerationResult, String> {
    let HeadlessInput {
        mapping,
        filename_pattern,
        records,
        source_schema_keys,
        output_directory,
        overwrite,
        clock,
        ..
    } = input;
    let (fresh, terminal) = (&response.fresh_observation, &response.terminal_outcome);
    let (observed, sealed) = match (fresh, terminal) {
        (FreshExecutionObservation::Sealed(observed), SealTerminalOutcome::Sealed(sealed)) => {
            (observed, sealed)
        }
        _ => return seal_refusal(service, mapping, fresh),
    };
    let Some(plan) = sealed.plan_payload.clone() else {
        return Ok(refused(
            EXECUTION_NOT_SEALABLE,
            "SEALED_PLAN_PAYLOAD_MISSING",
            Vec::new(),
        ));
    };
    let captured_at = clock();
    let prepared = match prepare_records(&plan, records, source_schema_keys, &captured_at) {
        Ok(value) => value,
        Err(result) => return Ok(result),
    };
    let Some(binding) = observed.current_field_binding.as_ref() else {
        return Ok(refused(
            DELIVERY_PLAN,
            "CURRENT_DELIVERY_BINDING_CONTEXT_MISSING",
            Vec::new(),
        ));
    };
    let output = std::path::absolute(output_directory).map_err(|error| error.to_string())?;
    let intent =
        RunDeliveryIntent::new(output.to_string_lossy()).map_err(|error| error.to_string())?;
    let delivery = match delivery_result(prepare_current_delivery(
        &plan,
        &prepared,
        binding,
        filename_pattern,
        &intent,
        &captured_at,
        true,
    )) {
        Ok(value) => value,
        Err(result) => return Ok(result),
    };
    if let Some(request) = pending_overwrite(&delivery, overwrite) {
        return Ok(HeadlessGenerationResult::NeedsOverwrite(request));
    }
    let Some(context) = service
        .managed_run_context(HEADLESS_WORK_NAME, "hwpx")
        .map_err(|error| error.to_string())?
    else {
        return Ok(refused(
            EXECUTION_NOT_SEALABLE,
            "MANAGED_RUN_CONTEXT_UNAVAILABLE",
            Vec::new(),
        ));
    };
    fs::create_dir_all(&output).map_err(|error| error.to_string())?;
    let outcome = run_managed_generation(
        ManagedGenerationInput {
            authority_root: authority,
            context: &context,
            plan: &plan,
            snapshots: &prepared.raw_records,
            resolved: &delivery,
            validated_at: &captured_at,
        },
        || false,
        |_, _| {},
    )
    .map_err(|error| error.to_string())?;
    Ok(HeadlessGenerationResult::Executed(Box::new(
        HeadlessExecuted {
            outcome,
            work_authority_id: response.work_authority_id,
            execution_basis_digest: sealed.execution_basis_digest.clone(),
            plan_payload: plan,
            resolved_delivery: delivery,
            validated_at: captured_at,
        },
    )))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::{HwpxPackage, MIMETYPE_VALUE, PackageEntry, PackageLimits};
    use hwpx_filler::fields::{field_xml_names, read_fields, required_fields};
    use hwpx_filler::mapping::FieldMapping;
    use serde_json::Map;

    fn field_part(label: &str, name: &str, value: &str) -> Vec<u8> {
        format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph' data-preserve='{label}'><hp:p><hp:run><hp:t>{label} 계약명: </hp:t></hp:run><hp:run><hp:ctrl><hp:fieldBegin name='{name}'/></hp:ctrl></hp:run><hp:run><hp:t>{value}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p><hp:p><hp:run><hp:t>{label} 의미 보존</hp:t></hp:run></hp:p></hs:sec>").into_bytes()
    }

    fn part_package() -> HwpxPackage {
        HwpxPackage {
            entries: [
                ("mimetype", MIMETYPE_VALUE.to_vec()),
                ("Contents/footer0.xml", field_part("꼬리말", "공통", "꼬리말 구값")),
                ("Contents/header0.xml", field_part("머리말", "공통", "머리말 구값")),
                ("Contents/section1.xml", field_part("본문2", "유지필드", "유지값")),
                ("Contents/section0.xml", field_part("본문", "공통", "본문 구값")),
                ("Contents/header.xml", b"<hh:head xmlns:hh='http://www.hancom.co.kr/hwpml/2011/head' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'><hp:refList data-preserve='style'/></hh:head>".to_vec()),
                ("BinData/keep.bin", b"\0unchanged\xff".to_vec()),
            ].into_iter().map(|(name, data)| PackageEntry {
                name: name.into(), data, stored: name == "mimetype",
            }).collect(),
        }
    }

    fn fill_parts(root: &Path, package: &HwpxPackage) -> HeadlessGenerationResult {
        fs::create_dir_all(root).unwrap();
        let template = root.join("template.hwpx");
        let bytes = package.to_bytes().unwrap();
        fs::write(&template, &bytes).unwrap();
        let mapping = MappingProfile::new(
            "",
            ["공통", "유지필드"]
                .map(|name| FieldMapping::new(name, name, "text", "", "", None).unwrap())
                .to_vec(),
            Map::new(),
        )
        .unwrap();
        let result = run_headless_generation(HeadlessInput {
            workspace: &root.join("workspace"),
            template_path: &template,
            mapping: &mapping,
            filename_pattern: "doc-{{seq:001}}",
            records: &[Record::from_iter([
                ("공통".into(), "새 계약값".into()),
                ("유지필드".into(), "유지값".into()),
            ])],
            source_schema_keys: &["공통".into(), "유지필드".into()],
            output_directory: &root.join("out"),
            overwrite: false,
            clock: Arc::new(|| "2026-11-05T12:00:00".into()),
        })
        .unwrap();
        assert!(
            fs::read(&template).unwrap() == bytes,
            "generation changed source template"
        );
        result
    }

    #[test]
    fn managed_fill_preserves_body_header_footer_and_refuses_unsupported_parts_before_write() {
        let root = std::env::current_dir()
            .unwrap()
            .join(".cache")
            .join(format!("headless-parts-{}", uuid::Uuid::new_v4()));
        let package = part_package();
        assert_eq!(
            field_xml_names(&package).unwrap(),
            [
                "Contents/section0.xml",
                "Contents/section1.xml",
                "Contents/header0.xml",
                "Contents/footer0.xml"
            ]
        );
        assert_eq!(required_fields(&package).unwrap(), ["공통", "유지필드"]);
        assert_eq!(
            read_fields(&package).unwrap(),
            [
                ("공통".into(), "본문 구값".into()),
                ("유지필드".into(), "유지값".into())
            ]
        );
        let result = fill_parts(&root.join("valid"), &package);
        let HeadlessGenerationResult::Executed(executed) = result else {
            panic!("supported content parts must generate a document");
        };
        let ManagedGenerationResult::Completed { delivered, .. } = executed.outcome else {
            panic!("supported content parts must pass readback");
        };
        assert_eq!(delivered.len(), 1);
        let output = HwpxPackage::from_bytes(
            &fs::read(&delivered[0].absolute_path).unwrap(),
            PackageLimits::default(),
        )
        .unwrap();
        for source in &package.entries {
            let after = output
                .entries
                .iter()
                .find(|entry| entry.name == source.name)
                .unwrap();
            if [
                "Contents/section0.xml",
                "Contents/header0.xml",
                "Contents/footer0.xml",
            ]
            .contains(&source.name.as_str())
            {
                let part = HwpxPackage {
                    entries: vec![after.clone()],
                };
                assert_eq!(
                    read_fields(&part).unwrap(),
                    [("공통".into(), "새 계약값".into())]
                );
                let xml = hwpx_core::xml_view::XmlView::parse(&after.data).unwrap();
                let label = xml.attr(xml.root(), "data-preserve").unwrap();
                let extracted = hwpx_core::text_extract::extract_document(&part, None).unwrap();
                assert!(
                    hwpx_core::text_extract::full_text(&extracted)
                        .contains(&format!("{label} 의미 보존"))
                );
            } else {
                assert!(
                    after.data == source.data,
                    "unrelated part changed: {}",
                    source.name
                );
            }
        }
        let mut unknown = package.clone();
        let header = &mut unknown.entries[2];
        header.data = String::from_utf8(header.data.clone())
            .unwrap()
            .replace(
                "</hs:sec>",
                "<hp:futureHeader data-contract='unsupported'/></hs:sec>",
            )
            .into_bytes();
        let extracted = hwpx_core::text_extract::extract_document(&unknown, None).unwrap();
        assert_eq!(
            extracted.unhandled,
            std::collections::BTreeMap::from([("futureHeader".into(), 1)])
        );
        assert!(extracted.unhandled_examples["futureHeader"].contains("header0"));
        let unsupported = HwpxPackage {
            entries: vec![
                package.entries[0].clone(),
                PackageEntry {
                    name: "Contents/headerCustom.xml".into(),
                    data: field_part("미지원 머리말", "공통", "구값"),
                    stored: false,
                },
            ],
        };
        let result = fill_parts(&root.join("unsupported"), &unsupported);
        let HeadlessGenerationResult::Refused(refusal) = result else {
            panic!("unsupported field part must be refused before generation");
        };
        assert_eq!(refusal.stage, TEMPLATE_INITIALIZATION);
        assert!(!root.join("unsupported/out").exists());
        for (case, replacement) in [
            ("unmatched", ""),
            ("degenerate", "<hp:fieldBegin name='공통'/><hp:fieldEnd/>"),
        ] {
            let mut broken = package.clone();
            let entry = &mut broken.entries[3];
            entry.data = if case == "unmatched" {
                String::from_utf8(entry.data.clone())
                    .unwrap()
                    .replace("<hp:fieldEnd/>", "")
                    .into_bytes()
            } else {
                format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'><hp:p><hp:run><hp:ctrl>{replacement}</hp:ctrl></hp:run></hp:p></hs:sec>").into_bytes()
            };
            let result = fill_parts(&root.join(case), &broken);
            assert!(
                matches!(result, HeadlessGenerationResult::Refused(ref refusal) if refusal.stage == TEMPLATE_INITIALIZATION),
                "{case}"
            );
            assert!(!root.join(case).join("out").exists());
        }
        use hwpx_filler::fields::{FillNote, FillNoteKind};
        for (case, old, kind, detail) in [
            ("empty", "", FillNoteKind::SlotSynthesized, vec![]),
            (
                "inline",
                "OLD<hp:markpenBegin/>X<hp:markpenEnd/>",
                FillNoteKind::InlineStripped,
                vec!["markpenBegin".into(), "markpenEnd".into()],
            ),
        ] {
            let mut noted = package.clone();
            // Keep this occurrence in one part, so the delivery note must name it exactly once.
            noted.entries = vec![
                package.entries[0].clone(),
                package.entries[3].clone(),
                package.entries[4].clone(),
            ];
            noted.entries[2].data = field_part("본문", "공통", old);
            if case == "empty" {
                noted.entries[2].data = String::from_utf8(noted.entries[2].data.clone())
                    .unwrap()
                    .replace("<hp:run><hp:t></hp:t></hp:run>", "")
                    .into_bytes();
            }
            let HeadlessGenerationResult::Executed(executed) = fill_parts(&root.join(case), &noted)
            else {
                panic!("{case} must generate");
            };
            let ManagedGenerationResult::Completed { delivered, .. } = executed.outcome else {
                panic!("{case} must deliver");
            };
            assert_eq!(
                delivered[0].execution_notes,
                [FillNote {
                    field: "공통".into(),
                    kind,
                    detail
                }]
            );
            let output = HwpxPackage::from_bytes(
                &fs::read(&delivered[0].absolute_path).unwrap(),
                PackageLimits::default(),
            )
            .unwrap();
            assert!(
                read_fields(&output)
                    .unwrap()
                    .contains(&("공통".into(), "새 계약값".into()))
            );
        }
        fs::remove_dir_all(root).unwrap();
    }

    fn corpus_run(
        root: &Path,
        template: &Path,
        mapping: &MappingProfile,
        records: &[Record],
        pattern: &str,
        overwrite: bool,
    ) -> HeadlessGenerationResult {
        let mut keys = Vec::new();
        for record in records {
            for key in record.keys() {
                if !keys.contains(key) {
                    keys.push(key.clone());
                }
            }
        }
        run_headless_generation(HeadlessInput {
            workspace: &root.join(uuid::Uuid::new_v4().to_string()),
            template_path: template,
            mapping,
            filename_pattern: pattern,
            records,
            source_schema_keys: &keys,
            output_directory: &root.join("out"),
            overwrite,
            clock: Arc::new(|| "2026-11-05T12:00:00".into()),
        })
        .unwrap()
    }

    fn completed(
        result: HeadlessGenerationResult,
    ) -> Vec<crate::managed_generation_service::DeliveredDocument> {
        let HeadlessGenerationResult::Executed(executed) = result else {
            panic!("expected generation to execute");
        };
        let ManagedGenerationResult::Completed { delivered, .. } = executed.outcome else {
            panic!("expected generation to complete: {:?}", executed.outcome);
        };
        delivered
    }

    #[test]
    fn real_template_generation_strips_stale_layout_without_changing_other_parts() {
        let root = std::env::current_dir()
            .unwrap()
            .join(".cache")
            .join(format!("headless-layout-{}", uuid::Uuid::new_v4()));
        let template = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/real/bid_notice_limited_under100m.hwpx");
        let source_bytes = fs::read(&template).unwrap();
        let source = HwpxPackage::from_bytes(&source_bytes, PackageLimits::default()).unwrap();
        let fields = required_fields(&source).unwrap();
        assert!(!fields.is_empty());
        let mapping = MappingProfile::new(
            "",
            fields
                .iter()
                .map(|field| FieldMapping::new(field, field, "text", "", "", None).unwrap())
                .collect(),
            Map::new(),
        )
        .unwrap();
        let records = ["새값"].map(|value| {
            fields
                .iter()
                .map(|field| (field.clone(), value.into()))
                .collect()
        });
        let delivered = completed(corpus_run(
            &root,
            &template,
            &mapping,
            &records,
            "doc-{{seq:001}}",
            false,
        ));
        assert_eq!(
            delivered
                .iter()
                .map(|doc| doc.relative_path.as_str())
                .collect::<Vec<_>>(),
            ["doc-001.hwpx"]
        );
        let before = delivered
            .iter()
            .map(|doc| fs::read(&doc.absolute_path).unwrap())
            .collect::<Vec<_>>();
        let output = HwpxPackage::from_bytes(&before[0], PackageLimits::default()).unwrap();
        let mut stale_count = 0;
        let mut changed = 0;
        for entry in &source.entries {
            let after = output
                .entries
                .iter()
                .find(|after| after.name == entry.name)
                .unwrap();
            if entry.data != after.data {
                assert!(entry.name.starts_with("Contents/section") && entry.name.ends_with(".xml"));
                stale_count += String::from_utf8_lossy(&entry.data)
                    .matches("linesegarray")
                    .count();
                assert!(!String::from_utf8_lossy(&after.data).contains("linesegarray"));
                changed += 1;
            }
        }
        assert!(changed > 0 && stale_count > 0);
        assert_eq!(fs::read(&template).unwrap(), source_bytes);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn nara_corpus_preserves_missing_dates_declared_empty_and_duplicate_notice_files() {
        let root = std::env::current_dir()
            .unwrap()
            .join(".cache")
            .join(format!("headless-nara-{}", uuid::Uuid::new_v4()));
        let corpus = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus");
        let template = corpus.join("scenario/templates/입찰공고서.hwpx");
        let source =
            HwpxPackage::from_bytes(&fs::read(&template).unwrap(), PackageLimits::default())
                .unwrap();
        let source_fields: std::collections::HashMap<_, _> =
            read_fields(&source).unwrap().into_iter().collect();
        let mut mapping = MappingProfile::from_dict(
            &serde_json::from_slice(
                &fs::read(corpus.join("scenario/data/나라장터_매핑.json")).unwrap(),
            )
            .unwrap(),
        )
        .unwrap();
        let mapped = mapping.template_fields();
        let empty = required_fields(&source)
            .unwrap()
            .into_iter()
            .filter(|field| !mapped.contains(field))
            .collect::<Vec<_>>();
        assert!(!empty.is_empty());
        for field in &empty {
            assert!(
                !source_fields[field].is_empty(),
                "positive control: template had a hint for {field}"
            );
            mapping
                .mappings
                .push(FieldMapping::new(field, "", "const", "", "", None).unwrap());
        }
        let all =
            hwpx_filler::nara::parse(&fs::read(corpus.join("nara_mulpum/mulpum.json")).unwrap())
                .unwrap();
        let records = ["R26BK01621756", "R26BK01610529"].map(|number| {
            all.iter()
                .find(|record| record["bidNtceNo"] == number)
                .unwrap()
                .clone()
        });
        assert_eq!(records[0]["bidNtceNm"], records[1]["bidNtceNm"]);
        let delivered = completed(corpus_run(
            &root,
            &template,
            &mapping,
            &records,
            "공고서-{{공고명}}",
            false,
        ));
        assert_eq!(delivered.len(), 2);
        let names = delivered
            .iter()
            .map(|doc| doc.relative_path.clone())
            .collect::<Vec<_>>();
        assert_ne!(names[0], names[1]);
        assert!(names[1].ends_with("_1.hwpx"));
        let before = delivered
            .iter()
            .map(|doc| fs::read(&doc.absolute_path).unwrap())
            .collect::<Vec<_>>();
        let generated = HwpxPackage::from_bytes(&before[0], PackageLimits::default()).unwrap();
        let fields: std::collections::HashMap<_, _> =
            read_fields(&generated).unwrap().into_iter().collect();
        for field in [
            "입찰개시일자",
            "입찰개시시각",
            "입찰마감일자",
            "입찰마감시각",
        ] {
            assert_eq!(
                fields[field],
                hwpx_filler::job::MISSING_MARKER.replace("{field}", field)
            );
        }
        for field in empty {
            assert_eq!(
                fields[&field], "",
                "declared empty must clear {field}, without a missing marker"
            );
        }
        let HeadlessGenerationResult::NeedsOverwrite(asked) = corpus_run(
            &root,
            &template,
            &mapping,
            &records,
            "공고서-{{공고명}}",
            false,
        ) else {
            panic!("second run must ask before overwriting");
        };
        assert_eq!(asked.conflict_names, names);
        for (doc, bytes) in delivered.iter().zip(before) {
            assert_eq!(fs::read(&doc.absolute_path).unwrap(), bytes);
        }
        let delivered = completed(corpus_run(
            &root,
            &template,
            &mapping,
            &records,
            "공고서-{{공고명}}",
            true,
        ));
        assert_eq!(delivered.len(), 2);
        assert!(
            delivered
                .iter()
                .all(|doc| doc.collision_disposition == WRITE_OVERWRITE)
        );
        let records = hwpx_filler::nara::parse(
            &fs::read(corpus.join("scenario/data/나라장터_응답.json")).unwrap(),
        )
        .unwrap();
        let delivered = completed(corpus_run(
            &root.join("formatted"),
            &template,
            &mapping,
            &records,
            "공고서-{{입찰공고번호}}",
            false,
        ));
        assert_eq!(delivered.len(), 2);
        assert_eq!(delivered[0].relative_path, "공고서-R26BK00450011.hwpx");
        let generated = HwpxPackage::from_bytes(
            &fs::read(&delivered[0].absolute_path).unwrap(),
            PackageLimits::default(),
        )
        .unwrap();
        let fields: std::collections::HashMap<_, _> =
            read_fields(&generated).unwrap().into_iter().collect();
        for (field, expected) in [
            ("공고명", "친환경 선박용 소화장비 구매"),
            ("추정가격", "45,000,000원"),
            ("개찰일자", "2026. 7. 22."),
            ("개찰시각", "10:00"),
            ("입찰개시일자", "2026. 7. 15."),
            ("입찰개시시각", "09:00"),
            ("입찰마감일자", "2026. 7. 21."),
            ("입찰마감시각", "17:00"),
            ("낙찰자결정방법", "적격심사"),
            ("세부품명", ""),
        ] {
            assert_eq!(fields[field], expected, "{field}");
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn procurement_records_fill_full_and_subset_templates_without_extra_fields() {
        let root = std::env::current_dir()
            .unwrap()
            .join(".cache")
            .join(format!("headless-procurement-{}", uuid::Uuid::new_v4()));
        let corpus = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus/scenario");
        let records =
            hwpx_filler::data_factory::source_for_path(&corpus.join("data/조달_한글.csv"), None, 1)
                .unwrap()
                .records()
                .unwrap();
        assert_eq!(records.len(), 3);
        for (name, count, pattern) in [
            ("입찰공고서", 25, "입찰공고서-{{입찰공고번호}}"),
            ("구매요청서", 10, "구매요청서-{{seq:001}}"),
        ] {
            let template = corpus.join(format!("templates/{name}.hwpx"));
            let source =
                HwpxPackage::from_bytes(&fs::read(&template).unwrap(), PackageLimits::default())
                    .unwrap();
            let fields = required_fields(&source).unwrap();
            assert_eq!(fields.len(), count);
            assert_eq!(fields.contains(&"계약방법".into()), name == "입찰공고서");
            let mapping = MappingProfile::new(
                "",
                fields
                    .iter()
                    .map(|field| FieldMapping::new(field, field, "text", "", "", None).unwrap())
                    .collect(),
                Map::new(),
            )
            .unwrap();
            let delivered = completed(corpus_run(
                &root.join(name),
                &template,
                &mapping,
                &records,
                pattern,
                false,
            ));
            assert_eq!(delivered.len(), 3);
            for (index, (doc, record)) in delivered.iter().zip(&records).enumerate() {
                let suffix = if name == "입찰공고서" {
                    record["입찰공고번호"].clone()
                } else {
                    format!("{:03}", index + 1)
                };
                assert_eq!(doc.relative_path, format!("{name}-{suffix}.hwpx"));
                let generated = HwpxPackage::from_bytes(
                    &fs::read(&doc.absolute_path).unwrap(),
                    PackageLimits::default(),
                )
                .unwrap();
                let actual: std::collections::HashMap<_, _> =
                    read_fields(&generated).unwrap().into_iter().collect();
                let expected = fields
                    .iter()
                    .map(|field| (field.clone(), record[field].clone()))
                    .collect();
                assert_eq!(actual, expected);
                assert_eq!(actual["세부품명"], record["세부품명"]);
            }
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn sealed_generation_preserves_refusal_phases_and_never_partially_writes() {
        let root = std::env::current_dir()
            .expect("repository working directory")
            .join(".cache")
            .join(format!("headless-binding-{}", uuid::Uuid::new_v4()));
        let template = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/real/form_purchase_v1.hwpx");
        let mapping = MappingProfile::new("", Vec::new(), Map::new()).unwrap();
        let clock: Arc<dyn Fn() -> String + Send + Sync> =
            Arc::new(|| "2026-11-05T12:00:00".into());
        let result = run_headless_generation(HeadlessInput {
            workspace: &root,
            template_path: &template,
            mapping: &mapping,
            filename_pattern: "out.hwpx",
            records: &[Record::from_iter([("irrelevant".into(), "value".into())])],
            source_schema_keys: &["irrelevant".into()],
            output_directory: &root.join("out"),
            overwrite: false,
            clock,
        })
        .expect("seal refusal remains an observed outcome");
        let HeadlessGenerationResult::Refused(refusal) = result else {
            panic!("missing active binding cannot produce a document");
        };
        assert_eq!(refusal.stage, EXECUTION_NOT_SEALABLE);
        assert!(
            refusal
                .details
                .iter()
                .any(|detail| detail == "연결이 필요한 필드: 진행상태"),
            "{:?}",
            refusal.details
        );
        let template_root = root.join("templates");
        let jobs = JobRegistry::new(root.join("jobs"), move || template_root.clone()).unwrap();
        let service = SealExecutionService::new(&root.join("authority"), &jobs, || {
            "2026-11-05T12:00:00".into()
        })
        .unwrap();
        let review = service
            .current_binding_review(HEADLESS_WORK_NAME)
            .unwrap()
            .expect("bootstrapped application has a current review");
        assert_eq!(review.active_field_ids, ["진행상태"]);
        assert_eq!(review.input_requirements.len(), 1);
        assert_eq!(
            review.input_requirements[0].binding_state,
            "NEW_ACTIVE_FIELD"
        );
        assert_eq!(
            review.input_requirements[0].exact_target,
            "binding/진행상태"
        );
        let mapping = MappingProfile::new(
            "",
            vec![FieldMapping::new("진행상태", "값", "text", "", "", None).unwrap()],
            Map::new(),
        )
        .unwrap();
        let mut job = jobs.load(HEADLESS_WORK_NAME).unwrap();
        job.mapping = mapping.clone();
        jobs.save(&mut job, true).unwrap();
        let sealed = service
            .seal(HEADLESS_WORK_NAME, "refusal-boundaries")
            .unwrap();
        assert!(matches!(
            sealed.terminal_outcome,
            SealTerminalOutcome::Sealed(_)
        ));
        let records = [Record::from_iter([("값".into(), "완료".into())])];
        let keys = ["값".into()];
        let output = root.join("out");
        let input = || HeadlessInput {
            workspace: &root,
            template_path: &template,
            mapping: &mapping,
            filename_pattern: "doc-{{seq:001}}",
            records: &records,
            source_schema_keys: &keys,
            output_directory: &output,
            overwrite: false,
            clock: Arc::new(|| "2026-11-05T12:00:00".into()),
        };
        let response = || SealExecutionResponse {
            terminal_outcome: sealed.terminal_outcome.clone(),
            work_authority_id: sealed.work_authority_id.clone(),
            fresh_observation: sealed.fresh_observation.clone(),
        };
        for (stage, code) in [
            (EXECUTION_NOT_SEALABLE, "SEALED_PLAN_PAYLOAD_MISSING"),
            (DELIVERY_PLAN, "CURRENT_DELIVERY_BINDING_CONTEXT_MISSING"),
            (EXECUTION_NOT_SEALABLE, "MANAGED_RUN_CONTEXT_UNAVAILABLE"),
        ] {
            let mut response = response();
            match code {
                "SEALED_PLAN_PAYLOAD_MISSING" => {
                    let SealTerminalOutcome::Sealed(value) = &mut response.terminal_outcome else {
                        unreachable!();
                    };
                    value.plan_payload = None;
                }
                "CURRENT_DELIVERY_BINDING_CONTEXT_MISSING" => {
                    let FreshExecutionObservation::Sealed(value) = &mut response.fresh_observation
                    else {
                        unreachable!();
                    };
                    value.current_field_binding = None;
                }
                _ => {
                    job.authority_id.clear();
                    jobs.save(&mut job, true).unwrap();
                }
            }
            let result =
                finish_sealed_generation(input(), &root.join("authority"), &service, response)
                    .unwrap_or_else(|error| panic!("{code} must be a refusal, got {error}"));
            let HeadlessGenerationResult::Refused(refusal) = result else {
                panic!("{code} must prevent generation");
            };
            assert_eq!((refusal.stage, refusal.code.as_str()), (stage, code));
            assert!(refusal.details.is_empty());
            assert!(!output.exists(), "{code} created the delivery directory");
        }
        job.authority_id = sealed.work_authority_id.clone();
        jobs.save(&mut job, true).unwrap();
        use hwpx_filler::fresh_execution_observation::{
            CurrentWorkExecutionObservation, ExecutionObservationContextError,
        };
        for (observation, code, details) in [
            (
                FreshExecutionObservation::WorkBlocked(CurrentWorkExecutionObservation {
                    work_authority_ref: sealed.work_authority_id.clone(),
                    current_sealability: "POLICY_BLOCKED".into(),
                    observed_at: "2026-11-05T12:00:00".into(),
                    current_template_application_ref: None,
                    normalized_blockers_or_policy: vec!["SOME_POLICY_CODE".into()],
                }),
                "POLICY_BLOCKED",
                vec!["SOME_POLICY_CODE"],
            ),
            (
                FreshExecutionObservation::ContextError(ExecutionObservationContextError {
                    code: "OBSERVATION_FAILED".into(),
                    detail: "broken context".into(),
                }),
                "OBSERVATION_FAILED",
                vec![],
            ),
        ] {
            let mut response = response();
            response.fresh_observation = observation;
            let result =
                finish_sealed_generation(input(), &root.join("authority"), &service, response)
                    .unwrap();
            let HeadlessGenerationResult::Refused(refusal) = result else {
                panic!("{code} must prevent generation");
            };
            assert_eq!(
                (refusal.stage, refusal.code.as_str()),
                (EXECUTION_NOT_SEALABLE, code)
            );
            assert_eq!(
                refusal.details, details,
                "a fully bound field is not pending"
            );
            assert!(!output.exists());
        }
        let invalid_records = [records[0].clone(), Record::new()];
        for (rows, code) in [
            (&invalid_records[..], "RECORD_VALIDATION_BLOCKED"),
            (&[][..], "CURRENT_RECORD_CAPTURE_FAILED"),
        ] {
            let mut input = input();
            input.records = rows;
            let result =
                finish_sealed_generation(input, &root.join("authority"), &service, response())
                    .unwrap();
            let HeadlessGenerationResult::Refused(refusal) = result else {
                panic!("{code} must validate every row before writing");
            };
            assert_eq!(
                (refusal.stage, refusal.code.as_str()),
                (RECORD_VALIDATION, code)
            );
            assert!(!refusal.details.is_empty());
            assert!(!output.exists());
        }
        let mut corrupt = response();
        let SealTerminalOutcome::Sealed(value) = &mut corrupt.terminal_outcome else {
            unreachable!();
        };
        value
            .plan_payload
            .as_mut()
            .unwrap()
            .execution_basis
            .field_binding
            .active_binding_digest = "sha256:wrong".into();
        let result =
            finish_sealed_generation(input(), &root.join("authority"), &service, corrupt).unwrap();
        let HeadlessGenerationResult::Refused(refusal) = result else {
            panic!("corrupt plan must remain a record-preparation refusal");
        };
        assert_eq!(
            (refusal.stage, refusal.code.as_str()),
            (RECORD_VALIDATION, "PLAN_INTEGRITY_ERROR")
        );
        assert_eq!(refusal.details, ["active_binding_digest 재계산 불일치"]);
        assert!(!output.exists());
        let _ = fs::remove_dir_all(root);
    }
}
