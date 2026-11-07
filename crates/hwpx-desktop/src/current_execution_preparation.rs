//! Shared host observations for current record and delivery preparation.

use hwpx_filler::data_source::Record;
use hwpx_filler::execution_contract_set::SealedExecutionPlanSemanticPayload;
use hwpx_filler::field_binding_input::FieldBindingInput;
use hwpx_filler::generation_delivery::{
    CurrentDeliveryInput, CurrentResolvedDelivery, DeliveryPlanContextError, DeliveryPlanResult,
    FILENAME_PATTERN_CONTRACT_ID, NON_REGULAR, PathOccupancyEntry, PathOccupancyObservation,
    REGULAR_FILE, build_delivery_binding_basis, resolve_current_generation_delivery,
};
use hwpx_filler::python_casefold::python_casefold;
use hwpx_filler::raw_data_record::{
    CanonicalSourceValue, RawDataRecordSnapshot, RawRecordCaptureProvenance,
    build_raw_record_snapshot,
};
use hwpx_filler::record_validation::{
    RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED, RECORD_REQUIRED_VALUE_MISSING,
    RECORD_VALUE_FORMAT_INVALID, ValidateDataRecordResult, ValidatedDataRecord,
    marked_missing_fields, validate_data_records_against_plan,
};
use hwpx_filler::run_delivery_intent::RunDeliveryIntent;
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordValidationIssue {
    pub record_identity: String,
    pub record_display_locator: String,
    pub field_id: String,
    pub field_display_label: String,
    /// Source column used by the recovery target; distinct from the plan field ID.
    pub recovery_field_id: String,
    pub message: String,
    pub model_index: usize,
    pub snapshot_generation: usize,
    pub target_kind: &'static str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordPreparationError {
    pub code: String,
    pub detail: String,
}

pub struct CurrentRecordPreparation {
    pub raw_records: Vec<RawDataRecordSnapshot>,
    pub validated_records: Vec<ValidatedDataRecord>,
    pub issues: Vec<RecordValidationIssue>,
    pub blocked_count: usize,
    pub marked_counts: Vec<(String, usize)>,
}

pub fn capture_selected_records(
    rows: &[Record],
    ordered_model_indices: &[usize],
    source_schema_keys: &[String],
    snapshot_generation: usize,
    captured_at: &str,
) -> Result<Vec<RawDataRecordSnapshot>, String> {
    ordered_model_indices
        .iter()
        .map(|index| {
            let row = rows
                .get(*index)
                .ok_or("선택한 데이터 위치를 확인할 수 없습니다.")?;
            build_raw_record_snapshot(
                source_schema_keys,
                row.iter()
                    .map(|(key, value)| (key.clone(), CanonicalSourceValue::Text(value.clone())))
                    .collect(),
                &format!("current-record/{snapshot_generation}/{index}"),
                RawRecordCaptureProvenance {
                    source_adapter_contract_id: "job-current-record-capture/v1".into(),
                    captured_at: captured_at.into(),
                    source_observation_ref: Some(format!("job-snapshot/{snapshot_generation}")),
                },
            )
            .map_err(|error| error.to_string())
        })
        .collect()
}

fn record_source_key(requirements: &[Value], field: &str) -> Result<String, String> {
    requirements
        .iter()
        .find_map(|item| {
            (item.get("field_id")?.as_str()? == field)
                .then(|| {
                    item.get("value_expression")?
                        .get("source_key")?
                        .as_str()
                        .filter(|value| !value.is_empty())
                })
                .flatten()
        })
        .map(str::to_owned)
        .ok_or("문제 데이터의 원본 항목을 확인할 수 없습니다.".into())
}

pub fn record_issue(
    plan: &SealedExecutionPlanSemanticPayload,
    blocker_code: &str,
    blocker_field_id: Option<&str>,
    generation: usize,
    model_index: usize,
    record_identity: &str,
    columns: &[String],
) -> Result<RecordValidationIssue, String> {
    let field_id = blocker_field_id.ok_or("문제 데이터의 필드를 확인할 수 없습니다.")?;
    let message = match blocker_code {
        RECORD_REQUIRED_VALUE_MISSING => "이 항목에 연결한 데이터 열이 없습니다.",
        RECORD_VALUE_FORMAT_INVALID => "값 형식이 올바르지 않습니다.",
        RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED => "이 값을 문서 내용으로 해석할 수 없습니다.",
        _ => return Err("데이터 문제를 사용자 문안으로 표시할 수 없습니다.".into()),
    };
    let source_key = record_source_key(&plan.active_field_requirements, field_id)?;
    Ok(RecordValidationIssue {
        record_identity: record_identity.into(),
        record_display_locator: format!("데이터 {}행", model_index + 1),
        field_id: field_id.into(),
        field_display_label: source_key.clone(),
        recovery_field_id: source_key.clone(),
        message: message.into(),
        model_index,
        snapshot_generation: generation,
        target_kind: if columns.contains(&source_key) {
            "cell"
        } else {
            "row"
        },
    })
}

/// Folds one validated record's marked-missing fields into the running per-field
/// counts, preserving first-seen field order.
fn accumulate_marked_fields(
    value: &ValidatedDataRecord,
    marked_indices: &mut HashMap<String, usize>,
    marked_counts: &mut Vec<(String, usize)>,
) {
    for field in marked_missing_fields(&value.validation_provenance) {
        if let Some(index) = marked_indices.get(&field) {
            marked_counts[*index].1 += 1;
        } else {
            marked_indices.insert(field.clone(), marked_counts.len());
            marked_counts.push((field, 1));
        }
    }
}

pub fn prepare_current_records(
    plan: &SealedExecutionPlanSemanticPayload,
    snapshot_generation: usize,
    raw_records: Vec<RawDataRecordSnapshot>,
    ordered_model_indices: &[usize],
    columns: &[String],
) -> Result<CurrentRecordPreparation, RecordPreparationError> {
    if raw_records.is_empty() || raw_records.len() != ordered_model_indices.len() {
        return Err(RecordPreparationError {
            code: "CURRENT_RECORD_CAPTURE_FAILED".into(),
            detail: "선택한 데이터 위치를 확인할 수 없습니다.".into(),
        });
    }
    let mut validated_records = Vec::new();
    let mut issues = Vec::new();
    let mut blocked_count = 0;
    let mut marked_counts = Vec::<(String, usize)>::new();
    let mut marked_indices = HashMap::<String, usize>::new();
    let captured_at = raw_records[0].capture_provenance.captured_at.as_str();
    let results =
        validate_data_records_against_plan(plan, &raw_records, captured_at, Some(captured_at));
    if results.len() != raw_records.len() {
        return Err(RecordPreparationError {
            code: "CURRENT_RECORD_CAPTURE_FAILED".into(),
            detail: "데이터 검증 건수가 선택 건수와 일치하지 않습니다.".into(),
        });
    }
    for ((model_index, raw), result) in ordered_model_indices.iter().zip(&raw_records).zip(results)
    {
        match result {
            ValidateDataRecordResult::Validated(value) => {
                accumulate_marked_fields(&value, &mut marked_indices, &mut marked_counts);
                validated_records.push(*value);
            }
            ValidateDataRecordResult::ContextError(error) => {
                return Err(RecordPreparationError {
                    code: error.code,
                    detail: error.detail,
                });
            }
            ValidateDataRecordResult::Blocked(blockers) => {
                blocked_count += 1;
                for blocker in blockers {
                    let issue = record_issue(
                        plan,
                        &blocker.code,
                        blocker.field_id.as_deref(),
                        snapshot_generation,
                        *model_index,
                        &raw.record_identity,
                        columns,
                    )
                    .map_err(|detail| RecordPreparationError {
                        code: "CURRENT_RECORD_CAPTURE_FAILED".into(),
                        detail,
                    })?;
                    issues.push(issue);
                }
            }
        }
    }
    Ok(CurrentRecordPreparation {
        raw_records,
        validated_records,
        issues,
        blocked_count,
        marked_counts,
    })
}

pub fn observe_path_occupancy(
    intent: &RunDeliveryIntent,
    observed_at: &str,
    allow_missing: bool,
) -> Result<PathOccupancyObservation, String> {
    let path = Path::new(&intent.output_directory);
    if !path.is_absolute() {
        return Err("저장 폴더는 전체 경로여야 합니다.".into());
    }
    let mut occupied_entries = Vec::new();
    match fs::read_dir(path) {
        Ok(entries) => {
            for result in entries {
                let entry = result.map_err(|_| "저장 폴더의 현재 파일 목록을 읽을 수 없습니다.")?;
                let name = entry.file_name().to_string_lossy().into_owned();
                let kind = match fs::symlink_metadata(entry.path()) {
                    Ok(metadata) if metadata.file_type().is_file() => REGULAR_FILE,
                    Ok(_) => NON_REGULAR,
                    Err(_) => return Err("저장 폴더의 현재 파일 목록을 읽을 수 없습니다.".into()),
                };
                occupied_entries.push(PathOccupancyEntry {
                    relative_name: name,
                    kind: kind.into(),
                });
            }
        }
        Err(error) if allow_missing && error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err("저장 폴더의 현재 파일 목록을 읽을 수 없습니다.".into()),
    }
    occupied_entries.sort_by_key(|entry| python_casefold(&entry.relative_name));
    Ok(PathOccupancyObservation {
        output_directory: intent.output_directory.clone(),
        occupied_entries,
        observed_at: observed_at.into(),
    })
}

pub fn delivery_blocker_phrase(code: &str) -> &'static str {
    match code {
        "OUTPUT_NAME_TOKEN_UNRESOLVED" => "파일 이름에 사용할 값을 확인할 수 없습니다.",
        "OUTPUT_NAME_BINDING_AMBIGUOUS" => {
            "파일 이름에 사용할 항목 연결을 하나로 확인할 수 없습니다."
        }
        "OUTPUT_NAME_PATTERN_INVALID" => "파일 이름 규칙이 올바르지 않습니다.",
        "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED" => "같은 이름의 파일이 있습니다:",
        "OUTPUT_PATH_NON_REGULAR_CONFLICT" => {
            "같은 이름의 폴더나 바로가기 등이 있어 덮어쓸 수 없습니다:"
        }
        _ => "생성 예정 문서 이름을 확인할 수 없습니다.",
    }
}

pub fn prepare_current_delivery(
    plan: &SealedExecutionPlanSemanticPayload,
    records: &CurrentRecordPreparation,
    binding: &FieldBindingInput,
    exact_pattern: &str,
    intent: &RunDeliveryIntent,
    captured_delivery_clock: &str,
    allow_missing_output_directory: bool,
) -> DeliveryPlanResult<CurrentResolvedDelivery> {
    let active = plan
        .active_field_requirements
        .iter()
        .filter_map(|item| item.get("field_id")?.as_str().map(str::to_owned))
        .collect::<Vec<_>>();
    let basis = match build_delivery_binding_basis(
        &binding.base_template_application_id,
        &binding.field_binding_authority_revision,
        FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern,
        &active,
        &binding.binding_rules,
        &plan
            .execution_basis
            .contracts
            .roles
            .document_value_resolution_contract_id,
    ) {
        DeliveryPlanResult::Ready(value) => value,
        DeliveryPlanResult::Blocked(value) => return DeliveryPlanResult::Blocked(value),
        DeliveryPlanResult::ContextError(value) => return DeliveryPlanResult::ContextError(value),
    };
    let occupancy = match observe_path_occupancy(
        intent,
        captured_delivery_clock,
        allow_missing_output_directory,
    ) {
        Ok(value) => value,
        Err(detail) => {
            return DeliveryPlanResult::ContextError(DeliveryPlanContextError {
                code: "PATH_OCCUPANCY_OBSERVATION_FAILED".into(),
                detail,
            });
        }
    };
    resolve_current_generation_delivery(CurrentDeliveryInput {
        sealed_execution_plan: plan,
        ordered_validated_records: &records.validated_records,
        ordered_raw_snapshots: &records.raw_records,
        delivery_binding_basis: &basis,
        exact_pattern,
        captured_delivery_clock,
        run_delivery_intent: intent,
        path_occupancy: &occupancy,
        filename_pattern_contract_id: FILENAME_PATTERN_CONTRACT_ID,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
pub(crate) mod tests {
    use super::*;
    use serde_json::json;

    pub(crate) fn source_plan() -> SealedExecutionPlanSemanticPayload {
        use hwpx_filler::canonical_execution_encoding::CANONICAL_ENCODING_VERSION;
        use hwpx_filler::execution_capture::{
            EffectiveSelectionBasis, ExactTemplateExecutionBasis, MATERIALIZATION_BASE_CONTRACT_ID,
        };
        use hwpx_filler::execution_compilation::{
            ActiveFieldValueExpression, EXECUTION_SEMANTICS_CONTRACT, EffectiveFieldBindingBasis,
            EffectiveFieldBindingRule, active_binding_digest, encode_value_expression,
            required_source_key_set_digest,
        };
        use hwpx_filler::execution_composition::{
            COMPOSITION_CONTRACT_ID, COMPOSITION_FINGERPRINT_HWPX, NATIVE_PRIMITIVE_CONTRACT_ID,
        };
        use hwpx_filler::execution_contract_set::{
            ContractRoles, ExecutionBasis, build_execution_contract_set, build_sealed_plan,
        };
        use hwpx_filler::field_binding::{BINDING_VALUE_VERSION, SOURCE_SCHEMA_VERSION};
        use hwpx_filler::raw_data_record::{RAW_RECORD_CONTRACT_ID, RECORD_REVIEW_CONTRACT_ID};
        use hwpx_filler::record_validation::{
            DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID, RECORD_VALIDATION_CONTRACT_ID,
        };
        use hwpx_filler::shipping_seal_policy::{
            SHIPPING_MATERIALIZATION_CONTRACT_ID, SHIPPING_PLAN_SCHEMA_VERSION,
        };

        let expression = ActiveFieldValueExpression::FromSource {
            source_key: "열".into(),
            format_code: None,
            document_content_value_policy_id: "document-content-value/v1".into(),
            format_kind: None,
            text_slice: None,
        };
        let rules = vec![EffectiveFieldBindingRule {
            field_id: "이름".into(),
            binding_kind: "SOURCE".into(),
            value_expression: expression.clone(),
        }];
        let roles = ContractRoles {
            slot_selection_contract_id: "slot-selection/v1".into(),
            field_binding_contract_id: hwpx_filler::field_binding::FIELD_BINDING_SEMANTIC_VERSION
                .into(),
            source_schema_contract_id: SOURCE_SCHEMA_VERSION.into(),
            raw_record_contract_id: RAW_RECORD_CONTRACT_ID.into(),
            execution_semantic_contract_id: EXECUTION_SEMANTICS_CONTRACT.into(),
            binding_value_contract_id: BINDING_VALUE_VERSION.into(),
            document_value_resolution_contract_id: DOCUMENT_VALUE_RESOLUTION_CONTRACT_ID.into(),
            record_validation_contract_id: RECORD_VALIDATION_CONTRACT_ID.into(),
            record_review_contract_id: RECORD_REVIEW_CONTRACT_ID.into(),
            composition_contract_id: COMPOSITION_CONTRACT_ID.into(),
            native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID.into(),
            materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
            materialization_contract_id: SHIPPING_MATERIALIZATION_CONTRACT_ID.into(),
            composition_theorem_evidence_manifest_digest: COMPOSITION_FINGERPRINT_HWPX.into(),
        };
        let basis = ExecutionBasis {
            workspace_instance_id: "workspace".into(),
            work_authority_id: "work".into(),
            qualification_profile_semantic_digest: "sha256:qualified".into(),
            template: ExactTemplateExecutionBasis {
                execution_base_kind: "APPLIED_TEMPLATE_CANDIDATE".into(),
                materialization_base_contract_id: MATERIALIZATION_BASE_CONTRACT_ID.into(),
                work_authority_id: "work".into(),
                template_application_id: "application".into(),
                exact_content_digest: "sha256:candidate".into(),
                canonical_blob_reference: "blob://candidate".into(),
            },
            contracts: build_execution_contract_set(roles).unwrap(),
            selection: EffectiveSelectionBasis {
                slot_mode: "SLOTLESS".into(),
                work_id: "work".into(),
                template_application_id: "application".into(),
                selection_semantic_contract_id: "slot-selection/v1".into(),
                template_structure_digest: "sha256:structure".into(),
                effective_selection_digest: None,
                declared_selection_digest: None,
            },
            field_binding: EffectiveFieldBindingBasis {
                effective_active_binding_rules: rules.clone(),
                active_binding_digest: active_binding_digest(&rules).unwrap(),
                required_source_keys: vec!["열".into()],
                required_source_key_set_digest: required_source_key_set_digest(&["열".into()])
                    .unwrap(),
            },
        };
        build_sealed_plan(
            basis,
            &[
                json!({"field_id":"이름","expected_active_occurrence_count":1,
                "value_expression":encode_value_expression(&expression)}),
            ],
            &[json!({"op":"APPLY_FIELD_BINDING","field_id":"이름"})],
            SHIPPING_PLAN_SCHEMA_VERSION,
            CANONICAL_ENCODING_VERSION,
        )
        .unwrap()
    }

    #[test]
    fn selected_record_capture_keeps_model_order_and_source_identity() {
        let mut rows = vec![
            Record::from_iter([("이름".into(), "첫째".into())]),
            Record::from_iter([
                ("이름".into(), "둘째".into()),
                ("금액".into(), "1,500,000".into()),
                ("날짜".into(), "계약 후 90일 이내".into()),
            ]),
        ];
        let snapshots =
            capture_selected_records(&rows, &[1, 0], &["이름".into()], 7, "2026-11-05T00:00:00")
                .expect("two selected source records");
        assert_eq!(snapshots[0].record_identity, "current-record/7/1");
        assert_eq!(snapshots[1].record_identity, "current-record/7/0");
        rows[1].insert("이름".into(), "changed after capture".into());
        for (field, value) in [
            ("이름", "둘째"),
            ("금액", "1,500,000"),
            ("날짜", "계약 후 90일 이내"),
        ] {
            assert_eq!(
                snapshots[0].value_for(field),
                Some(&CanonicalSourceValue::Text(value.into()))
            );
        }
        assert_eq!(
            snapshots[0]
                .capture_provenance
                .source_observation_ref
                .as_deref(),
            Some("job-snapshot/7")
        );
        assert!(capture_selected_records(&rows, &[2], &["이름".into()], 7, "now").is_err());
        assert_eq!(
            record_source_key(
                &[
                    json!({"field_id":"다른항목","value_expression":{"source_key":"무관"}}),
                    json!({"field_id":"계약명","value_expression":{"source_key":""}}),
                    json!({"field_id":"계약명","value_expression":{"source_key":"이름열"}})
                ],
                "계약명"
            ),
            Ok("이름열".into())
        );
        assert!(
            record_source_key(
                &[json!({"field_id":"계약명","value_expression":{"source_key":5}})],
                "계약명"
            )
            .is_err()
        );
        for requirements in [
            vec![],
            vec![json!({"field_id":"계약명","value_expression":"not-a-mapping"})],
            vec![json!({"field_id":"계약명","value_expression":{"source_key":""}})],
        ] {
            assert!(record_source_key(&requirements, "계약명").is_err());
        }
        let plan = source_plan();
        for (code, field) in [
            (RECORD_REQUIRED_VALUE_MISSING, None),
            ("unknown", Some("이름")),
        ] {
            assert!(record_issue(&plan, code, field, 7, 1, "row-1", &[]).is_err());
        }
        for code in [
            RECORD_REQUIRED_VALUE_MISSING,
            RECORD_VALUE_FORMAT_INVALID,
            RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED,
        ] {
            for (columns, expected_kind) in [(vec![], "row"), (vec!["열".into()], "cell")] {
                let issue =
                    record_issue(&plan, code, Some("이름"), 7, 1, "row-1", &columns).unwrap();
                assert_eq!(issue.field_id, "이름");
                assert_eq!(issue.recovery_field_id, "열");
                assert_eq!(issue.field_display_label, "열");
                assert_eq!(issue.record_display_locator, "데이터 2행");
                assert_eq!(issue.target_kind, expected_kind);
                assert_eq!(issue.model_index, 1);
                assert_eq!(issue.snapshot_generation, 7);
            }
        }
        assert!(
            observe_path_occupancy(
                &RunDeliveryIntent::new("relative/out").unwrap(),
                "now",
                true
            )
            .is_err()
        );
    }

    #[test]
    fn current_records_keep_selection_order_and_project_only_recoverable_failures() {
        let plan = source_plan();
        let rows = vec![
            Record::from_iter([("열".into(), "첫째".into())]),
            Record::from_iter([("열".into(), "\t\n".into())]),
            Record::new(),
        ];
        let raw =
            capture_selected_records(&rows, &[1, 0, 2], &["열".into()], 7, "2026-11-05T00:00:00")
                .unwrap();
        let prepared =
            prepare_current_records(&plan, 7, raw.clone(), &[1, 0, 2], &["열".into()]).unwrap();
        assert_eq!(prepared.raw_records, raw);
        assert_eq!(prepared.blocked_count, 1);
        assert_eq!(prepared.marked_counts, [("이름".into(), 1)]);
        assert_eq!(
            prepared
                .validated_records
                .iter()
                .map(|r| r.semantic_payload_encoded["record_identity"]
                    .as_str()
                    .unwrap())
                .collect::<Vec<_>>(),
            ["current-record/7/1", "current-record/7/0"]
        );
        assert_eq!(prepared.issues.len(), 1);
        assert_eq!(prepared.issues[0].record_identity, "current-record/7/2");
        assert_eq!(prepared.issues[0].model_index, 2);
        assert_eq!(prepared.issues[0].recovery_field_id, "열");
        let mut corrupt = raw[0].clone();
        corrupt.raw_record_digest = "sha256:forged".into();
        let failure = prepare_current_records(&plan, 7, vec![corrupt], &[1], &[])
            .err()
            .unwrap();
        assert_eq!(
            failure.code,
            hwpx_filler::record_validation::RAW_RECORD_INTEGRITY_ERROR
        );
        for (raw, indices) in [(vec![], vec![]), (vec![raw[0].clone()], vec![])] {
            assert_eq!(
                prepare_current_records(&plan, 7, raw, &indices, &[])
                    .err()
                    .unwrap()
                    .code,
                "CURRENT_RECORD_CAPTURE_FAILED"
            );
        }
        let clean =
            prepare_current_records(&plan, 7, vec![raw[1].clone()], &[0], &["열".into()]).unwrap();
        assert!(clean.issues.is_empty());
        assert_eq!(clean.blocked_count, 0);
        assert!(clean.marked_counts.is_empty());
        assert_inactive_filename_uses_frozen_values(&plan);
    }

    fn assert_inactive_filename_uses_frozen_values(plan: &SealedExecutionPlanSemanticPayload) {
        use hwpx_filler::field_binding::{FieldBindingRule, SOURCE, resolve_document_value_policy};
        use hwpx_filler::field_binding_input::build_field_binding_input;
        use hwpx_filler::raw_data_record::RAW_RECORD_CONTRACT_ID;
        let rule = |field: &str, source: &str| FieldBindingRule {
            field_id: field.into(),
            binding_kind: SOURCE.into(),
            document_content_value_policy: resolve_document_value_policy(
                "document-content-value/v1",
            )
            .unwrap(),
            source_key: Some(source.into()),
            format_code: None,
            canonical_constant_value: None,
            format_kind: None,
            text_slice: None,
        };
        let binding = build_field_binding_input(
            "workspace",
            "work",
            "application",
            vec![rule("이름", "열"), rule("날짜", "date")],
            vec!["열".into(), "date".into()],
            RAW_RECORD_CONTRACT_ID,
            "2026-11-06T00:00:00",
        )
        .unwrap();
        let mut rows = vec![Record::from_iter([
            ("열".into(), "이름".into()),
            ("date".into(), "2026-08-20".into()),
        ])];
        let raw = capture_selected_records(
            &rows,
            &[0],
            &["열".into(), "date".into()],
            8,
            "2026-11-06T00:00:00",
        )
        .unwrap();
        let records = prepare_current_records(plan, 8, raw, &[0], &["열".into()]).unwrap();
        rows[0].insert("date".into(), "changed".into());
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!(
                "delivery-observation-{}",
                uuid::Uuid::new_v4().simple()
            ));
        let intent = RunDeliveryIntent::new(root.to_string_lossy().into_owned()).unwrap();
        let prepare = |allow_missing| {
            prepare_current_delivery(
                plan,
                &records,
                &binding,
                "{{날짜}}",
                &intent,
                "2026-11-06T00:00:00",
                allow_missing,
            )
        };
        let DeliveryPlanResult::Ready(delivery) = prepare(true) else {
            panic!("inactive filename should resolve")
        };
        assert_eq!(
            delivery.ordered_items[0].resolved_output_relative_path,
            "2026-08-20.hwpx"
        );
        assert!(
            !root.exists(),
            "observing a default output directory must not create it"
        );
        assert_occupancy_failure(prepare(false));
        fs::write(&root, b"existing non-directory").unwrap();
        assert_occupancy_failure(prepare(true));
        assert_eq!(fs::read(&root).unwrap(), b"existing non-directory");
        fs::remove_file(&root).unwrap();
        #[cfg(windows)]
        assert_broken_junction_is_not_followed(&root);
    }

    #[cfg(windows)]
    fn assert_broken_junction_is_not_followed(root: &Path) {
        use std::os::windows::{fs::OpenOptionsExt, io::AsRawHandle};
        use windows_sys::Win32::Storage::FileSystem::{
            FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAG_OPEN_REPARSE_POINT,
        };
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn DeviceIoControl(
                handle: *mut std::ffi::c_void,
                code: u32,
                input: *const u8,
                input_len: u32,
                output: *mut u8,
                output_len: u32,
                returned: *mut u32,
                overlapped: *mut std::ffi::c_void,
            ) -> i32;
        }
        fs::create_dir(root).unwrap();
        let target = root.join("target");
        let link = root.join("alias.hwpx");
        fs::create_dir(&target).unwrap();
        fs::create_dir(&link).unwrap();
        let target = fs::canonicalize(target).unwrap();
        let path = target.to_str().unwrap().strip_prefix(r"\\?\").unwrap();
        let substitute = format!(r"\??\{path}").encode_utf16().collect::<Vec<_>>();
        let print = path.encode_utf16().collect::<Vec<_>>();
        let names = substitute
            .iter()
            .copied()
            .chain([0])
            .chain(print.iter().copied())
            .chain([0]);
        let mut buffer = 0xa000_0003u32.to_le_bytes().to_vec();
        for word in [
            8 + (substitute.len() + print.len() + 2) * 2,
            0,
            0,
            substitute.len() * 2,
            (substitute.len() + 1) * 2,
            print.len() * 2,
        ] {
            buffer.extend_from_slice(&u16::try_from(word).unwrap().to_le_bytes());
        }
        for word in names {
            buffer.extend_from_slice(&word.to_le_bytes());
        }
        let handle = fs::OpenOptions::new()
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(&link)
            .unwrap();
        let mut returned = 0;
        // The owned directory handle and mount-point buffer live through this synchronous call.
        let success = unsafe {
            DeviceIoControl(
                handle.as_raw_handle(),
                0x0009_00a4,
                buffer.as_ptr(),
                buffer.len().try_into().unwrap(),
                std::ptr::null_mut(),
                0,
                &mut returned,
                std::ptr::null_mut(),
            )
        };
        assert_ne!(success, 0, "{}", std::io::Error::last_os_error());
        drop(handle);
        fs::remove_dir(target).unwrap();
        let observed = observe_path_occupancy(
            &RunDeliveryIntent::new(root.to_string_lossy().into_owned()).unwrap(),
            "2026-11-06T00:00:00",
            false,
        )
        .unwrap();
        assert_eq!(
            observed.occupied_entries,
            vec![PathOccupancyEntry {
                relative_name: "alias.hwpx".into(),
                kind: NON_REGULAR.into()
            }]
        );
        fs::remove_dir(link).unwrap();
        fs::remove_dir(root).unwrap();
    }

    fn assert_occupancy_failure(result: DeliveryPlanResult<CurrentResolvedDelivery>) {
        let DeliveryPlanResult::ContextError(failure) = result else {
            panic!("unreadable destination accepted")
        };
        assert_eq!(failure.code, "PATH_OCCUPANCY_OBSERVATION_FAILED");
        assert_eq!(
            failure.detail,
            "저장 폴더의 현재 파일 목록을 읽을 수 없습니다."
        );
    }
}
