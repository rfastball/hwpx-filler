//! In-memory TXT materialization with staged structure checks.

use crate::execution_contract_set::{
    PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION, SealedExecutionPlanSemanticPayload,
};
use crate::execution_structure::ExecutionTemplateStructure;
use crate::materialization_conformance::{
    ConformanceExecutionError, ConformanceResult, FIELD_TEXT_MISMATCH, MARKER_CLEANUP_VIOLATION,
    NativePlanView, OCCURRENCE_COUNT_MISMATCH, PRESERVED_CONTENT_LOST, REMOVAL_INCOMPLETE,
    REPARSE_FAILED, SOURCE_CANDIDATE_MUTATED, STRUCTURE_BYTES_INCONSISTENT, failure, pass,
};
use crate::text_render::{SEG_LITERAL, iter_field_token_matches, python_repr, render_segments};
use crate::text_structure::{
    TextStructureScan, drop_lines, marker_lines, scan_text_structure, unselected_option_lines,
};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};

pub const TXT_CONFORMANCE_CONTRACT_ID: &str = "txt-materialization-conformance/v1";
type OptionKeys = HashSet<(String, String)>;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InMemoryTxtMaterialization {
    pub output_bytes: Vec<u8>,
    pub stage_facts: BTreeMap<String, usize>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TxtExecutionOutcome {
    Materialized(InMemoryTxtMaterialization),
    Failure(ConformanceResult),
}
fn error(message: impl Into<String>) -> ConformanceExecutionError {
    ConformanceExecutionError(message.into())
}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}
pub fn decode_txt<'a>(raw: &'a [u8], what: &str) -> Result<&'a str, ConformanceExecutionError> {
    std::str::from_utf8(raw).map_err(|invalid| {
        let reason = if invalid.error_len().is_none() {
            "unexpected end of data"
        } else {
            "invalid start byte"
        };
        error(format!(
            "{what} 를 UTF-8 로 읽을 수 없다({reason}, 위치 {})",
            invalid.valid_up_to()
        ))
    })
}
fn op_code(op: &Value) -> Result<&str, ConformanceExecutionError> {
    let code = op
        .get("op")
        .and_then(Value::as_str)
        .ok_or_else(|| error(format!("operation 에 op code 가 없다: {}", python_repr(op))))?;
    if !matches!(code, PLAN_APPLY_FIELD_BINDING | PLAN_REMOVE_OPTION) {
        return Err(error(format!("미지원 operation code: {}", repr(code))));
    }
    Ok(code)
}
fn authorized(
    ordered_operations: &[Value],
    structure: &ExecutionTemplateStructure,
) -> (OptionKeys, OptionKeys) {
    let declared = structure
        .option_regions
        .iter()
        .map(|item| (item.slot_id.clone(), item.option_id.clone()))
        .collect::<HashSet<_>>();
    let targets = ordered_operations
        .iter()
        .filter(|op| op["op"] == PLAN_REMOVE_OPTION)
        .filter_map(|op| {
            Some((
                op["slot_id"].as_str()?.to_owned(),
                op["option_id"].as_str()?.to_owned(),
            ))
        })
        .collect::<HashSet<_>>();
    let remaining = declared.difference(&targets).cloned().collect();
    (targets, remaining)
}
fn observed_options(scan: &crate::text_structure::TextStructureScan) -> HashSet<(String, String)> {
    scan.slots
        .iter()
        .flat_map(|slot| {
            slot.options
                .iter()
                .map(|option| (slot.id.clone(), option.id.clone()))
        })
        .collect()
}
fn names(text: &str) -> Vec<String> {
    iter_field_token_matches(text)
        .into_iter()
        .map(|item| crate::structure_scan::python_trim(item.body).to_owned())
        .collect()
}
fn sorted_pairs(items: &HashSet<(String, String)>) -> String {
    let mut items = items
        .iter()
        .map(|(slot, option)| format!("({}, {})", repr(slot), repr(option)))
        .collect::<Vec<_>>();
    items.sort();
    format!("[{}]", items.join(", "))
}
fn sorted_names(items: &HashSet<String>) -> String {
    let mut items = items.iter().map(|item| repr(item)).collect::<Vec<_>>();
    items.sort();
    format!("[{}]", items.join(", "))
}
pub fn verify_txt_structure_bytes_consistency(
    candidate_bytes: &[u8],
    structure: &ExecutionTemplateStructure,
) -> ConformanceResult {
    let text = match decode_txt(candidate_bytes, "candidate") {
        Ok(text) => text,
        Err(error) => return failure(STRUCTURE_BYTES_INCONSISTENT, error.to_string()),
    };
    let scan = scan_text_structure(text);
    if !scan.diagnostics.is_empty() {
        return failure(
            STRUCTURE_BYTES_INCONSISTENT,
            format!(
                "candidate 스캔이 구간 표기 진단을 낸다: {}",
                scan.diagnostics
                    .iter()
                    .map(|item| item.message.as_str())
                    .collect::<Vec<_>>()
                    .join("; ")
            ),
        );
    }
    let bytes_options = observed_options(&scan);
    let struct_options = structure
        .option_regions
        .iter()
        .map(|item| (item.slot_id.clone(), item.option_id.clone()))
        .collect::<HashSet<_>>();
    if bytes_options != struct_options {
        return failure(
            STRUCTURE_BYTES_INCONSISTENT,
            format!(
                "structure Option id {} 가 bytes {} 와 불일치",
                sorted_pairs(&struct_options),
                sorted_pairs(&bytes_options)
            ),
        );
    }
    let bytes_fields = names(text).into_iter().collect::<HashSet<_>>();
    let struct_fields = structure
        .field_occurrences
        .iter()
        .map(|item| item.field_id.clone())
        .collect::<HashSet<_>>();
    if bytes_fields != struct_fields {
        return failure(
            STRUCTURE_BYTES_INCONSISTENT,
            format!(
                "structure Field 투영이 bytes 와 불일치: structure-only={}, bytes-only={}",
                sorted_names(&struct_fields.difference(&bytes_fields).cloned().collect()),
                sorted_names(&bytes_fields.difference(&struct_fields).cloned().collect())
            ),
        );
    }
    ConformanceResult::Pass {
        output_digest: String::new(),
        notes: Vec::new(),
    }
}

pub fn apply_txt_execution_plan_in_memory(
    candidate_bytes: &[u8],
    plan: &SealedExecutionPlanSemanticPayload,
    structure: &ExecutionTemplateStructure,
    document_values: &HashMap<String, String>,
) -> Result<TxtExecutionOutcome, ConformanceExecutionError> {
    apply_txt_execution_operations_in_memory(
        candidate_bytes,
        &plan.ordered_operations,
        structure,
        document_values,
    )
}
pub(crate) fn apply_txt_execution_operations_in_memory(
    candidate_bytes: &[u8],
    ordered_operations: &[Value],
    structure: &ExecutionTemplateStructure,
    document_values: &HashMap<String, String>,
) -> Result<TxtExecutionOutcome, ConformanceExecutionError> {
    let mut apply_fields = Vec::new();
    for op in ordered_operations {
        if op_code(op)? == PLAN_APPLY_FIELD_BINDING {
            let field = op["field_id"].as_str().ok_or_else(|| {
                error(format!(
                    "APPLY_FIELD_BINDING 에 field_id 가 없다: {}",
                    python_repr(op)
                ))
            })?;
            apply_fields.push(field);
        }
    }
    for field in apply_fields {
        if !document_values.contains_key(field) {
            return Err(error(format!(
                "Active Field {} 에 대응하는 VDR document value 가 없다",
                repr(field)
            )));
        }
    }
    let text = decode_txt(candidate_bytes, "candidate")?;
    let scan = scan_text_structure(text);
    if !scan.diagnostics.is_empty() {
        return Ok(TxtExecutionOutcome::Failure(failure(
            REPARSE_FAILED,
            format!(
                "candidate 스캔이 구간 표기 진단을 낸다: {}",
                scan.diagnostics
                    .iter()
                    .map(|item| item.message.as_str())
                    .collect::<Vec<_>>()
                    .join("; ")
            ),
        )));
    }
    let (removal_targets, authorized) = authorized(ordered_operations, structure);
    let mut selected = HashMap::<String, HashSet<String>>::new();
    for (slot, option) in &authorized {
        selected
            .entry(slot.clone())
            .or_default()
            .insert(option.clone());
    }
    let removed = unselected_option_lines(&scan, &selected);
    let stage1 = drop_lines(text, &removed);
    let stage1_scan = scan_text_structure(&stage1);
    if let Some(failure) = verify_removed_options(&stage1_scan, &removal_targets, &authorized) {
        return Ok(TxtExecutionOutcome::Failure(failure));
    }
    let marker = marker_lines(&stage1_scan);
    let stage2 = drop_lines(&stage1, &marker);
    let stage2_scan = scan_text_structure(&stage2);
    if let Some(failure) = verify_cleaned_markers(&stage2_scan) {
        return Ok(TxtExecutionOutcome::Failure(failure));
    }
    let values = document_values
        .iter()
        .map(|(key, value)| (key.clone(), Value::String(value.clone())))
        .collect::<HashMap<_, _>>();
    let (segments, _) = render_segments(&stage2, &values);
    let written = segments
        .iter()
        .filter(|segment| segment.kind != SEG_LITERAL)
        .count();
    let output = segments
        .into_iter()
        .map(|segment| segment.text)
        .collect::<String>();
    Ok(TxtExecutionOutcome::Materialized(
        InMemoryTxtMaterialization {
            output_bytes: output.into_bytes(),
            stage_facts: BTreeMap::from([
                ("removed_options".into(), removal_targets.len()),
                ("removed_lines".into(), removed.len()),
                ("cleaned_marker_lines".into(), marker.len()),
                ("written_field_occurrences".into(), written),
            ]),
        },
    ))
}

fn verify_removed_options(
    scan: &TextStructureScan,
    removal_targets: &OptionKeys,
    authorized: &OptionKeys,
) -> Option<ConformanceResult> {
    if !scan.diagnostics.is_empty() {
        return Some(failure(
            REPARSE_FAILED,
            format!(
                "제거 뒤 재스캔이 진단을 낸다: {}",
                scan.diagnostics
                    .iter()
                    .map(|item| item.message.as_str())
                    .collect::<Vec<_>>()
                    .join("; ")
            ),
        ));
    }
    let remaining = observed_options(scan);
    let still = remaining
        .intersection(removal_targets)
        .cloned()
        .collect::<HashSet<_>>();
    if !still.is_empty() {
        return Some(failure(
            REMOVAL_INCOMPLETE,
            format!(
                "removal target 이 제거 뒤에도 잔존: {}",
                sorted_pairs(&still)
            ),
        ));
    }
    let lost = authorized
        .difference(&remaining)
        .cloned()
        .collect::<HashSet<_>>();
    if !lost.is_empty() {
        return Some(failure(
            PRESERVED_CONTENT_LOST,
            format!(
                "target 아닌 Option 이 제거 뒤 소실: {}",
                sorted_pairs(&lost)
            ),
        ));
    }
    if remaining != *authorized {
        return Some(failure(
            REMOVAL_INCOMPLETE,
            format!(
                "남은 Option {} 가 authorized {} 와 불일치",
                sorted_pairs(&remaining),
                sorted_pairs(authorized)
            ),
        ));
    }
    None
}

fn verify_cleaned_markers(scan: &TextStructureScan) -> Option<ConformanceResult> {
    if scan.summary.markers != 0 {
        return Some(failure(
            MARKER_CLEANUP_VIOLATION,
            format!(
                "마커 소거 뒤에도 구간 마커가 {}건 남았다",
                scan.summary.markers
            ),
        ));
    }
    None
}

pub fn verify_txt_materialization_postconditions(
    source_bytes: &[u8],
    output_bytes: &[u8],
    plan: &SealedExecutionPlanSemanticPayload,
    structure: &ExecutionTemplateStructure,
    document_values: &HashMap<String, String>,
    stage_facts: Option<&BTreeMap<String, usize>>,
) -> Result<ConformanceResult, ConformanceExecutionError> {
    verify_txt_materialization_postconditions_parts(
        source_bytes,
        output_bytes,
        NativePlanView {
            native_primitive_contract_id: &plan
                .execution_basis
                .contracts
                .roles
                .native_primitive_contract_id,
            ordered_operations: &plan.ordered_operations,
            active_field_requirements: &plan.active_field_requirements,
        },
        structure,
        document_values,
        stage_facts,
    )
}
pub(crate) fn verify_txt_materialization_postconditions_parts(
    source_bytes: &[u8],
    output_bytes: &[u8],
    plan: NativePlanView<'_>,
    structure: &ExecutionTemplateStructure,
    document_values: &HashMap<String, String>,
    stage_facts: Option<&BTreeMap<String, usize>>,
) -> Result<ConformanceResult, ConformanceExecutionError> {
    if plan.native_primitive_contract_id
        != crate::execution_composition::TXT_NATIVE_PRIMITIVE_CONTRACT_ID
    {
        return Err(error(format!(
            "미지원 native primitive contract(latest fallback 없음): {}",
            repr(plan.native_primitive_contract_id)
        )));
    }
    let source = match decode_txt(source_bytes, "source") {
        Ok(source) => source,
        Err(error) => return Ok(failure(SOURCE_CANDIDATE_MUTATED, error.to_string())),
    };
    if let Some(failure) = verify_source_after_execution(source, plan.ordered_operations, structure)
    {
        return Ok(failure);
    }
    let output = match decode_txt(output_bytes, "output") {
        Ok(output) => output,
        Err(error) => return Ok(failure(REPARSE_FAILED, error.to_string())),
    };
    if let Some(failure) = verify_output_syntax(output) {
        return Ok(failure);
    }
    if let Some(failure) = verify_field_values(
        output,
        plan.active_field_requirements,
        document_values,
        stage_facts,
    ) {
        return Ok(failure);
    }
    Ok(pass(output_bytes, Vec::new()))
}

fn verify_source_after_execution(
    source: &str,
    ordered_operations: &[Value],
    structure: &ExecutionTemplateStructure,
) -> Option<ConformanceResult> {
    let source_scan = scan_text_structure(source);
    if !source_scan.diagnostics.is_empty() {
        return Some(failure(
            SOURCE_CANDIDATE_MUTATED,
            "source 스캔이 구간 표기 진단을 낸다",
        ));
    }
    let (targets, _) = authorized(ordered_operations, structure);
    let source_options = observed_options(&source_scan);
    if !targets.is_subset(&source_options) {
        return Some(failure(
            SOURCE_CANDIDATE_MUTATED,
            format!(
                "removal target {} 가 source 에 없다(source 변형)",
                sorted_pairs(&targets.difference(&source_options).cloned().collect())
            ),
        ));
    }
    None
}

fn verify_output_syntax(output: &str) -> Option<ConformanceResult> {
    let scan = scan_text_structure(output);
    if !scan.diagnostics.is_empty() {
        return Some(failure(
            REPARSE_FAILED,
            format!(
                "output 재스캔이 진단을 낸다: {}",
                scan.diagnostics
                    .iter()
                    .map(|item| item.message.as_str())
                    .collect::<Vec<_>>()
                    .join("; ")
            ),
        ));
    }
    if scan.summary.markers != 0 {
        return Some(failure(
            MARKER_CLEANUP_VIOLATION,
            format!("output 에 구간 마커가 {}건 남았다", scan.summary.markers),
        ));
    }
    let leftover = names(output).into_iter().collect::<HashSet<_>>();
    if !leftover.is_empty() {
        return Some(failure(
            FIELD_TEXT_MISMATCH,
            format!(
                "output 에 미치환 필드 토큰이 남았다: {}",
                sorted_names(&leftover)
            ),
        ));
    }
    None
}

fn verify_field_values(
    output: &str,
    requirements: &[Value],
    document_values: &HashMap<String, String>,
    stage_facts: Option<&BTreeMap<String, usize>>,
) -> Option<ConformanceResult> {
    let expected = requirements
        .iter()
        .filter_map(|row| row["expected_active_occurrence_count"].as_u64())
        .sum::<u64>();
    if let Some(written) = stage_facts.and_then(|facts| facts.get("written_field_occurrences"))
        && *written != expected as usize
    {
        return Some(failure(
            OCCURRENCE_COUNT_MISMATCH,
            format!("치환한 Active Field 등장 {written} != 기대 {expected}"),
        ));
    }
    for (field, want) in document_values {
        let count = requirements
            .iter()
            .find(|row| row["field_id"] == *field)
            .and_then(|row| row["expected_active_occurrence_count"].as_u64())
            .unwrap_or(0);
        if count > 0 && !want.is_empty() && !output.contains(want) {
            return Some(failure(
                FIELD_TEXT_MISMATCH,
                format!("Active Field {} 의 값이 output 에 없다", repr(field)),
            ));
        }
    }
    None
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_composition::TXT_NATIVE_PRIMITIVE_CONTRACT_ID;
    use crate::text_template_inspection::inspect_txt_qualification;
    use serde_json::json;

    const BODY: &str = concat!(
        "수신: {{수신}}\n",
        "{{#항목 첨부 첨부 서류}}\n",
        "담당자: {{담당자}}\n",
        "{{#선택 계약서 계약서}}\n",
        "계약서를 첨부합니다. {{건명}}\n",
        "{{/선택}}\n",
        "{{#선택 견적서 견적서}}\n",
        "견적서를 첨부합니다.\n",
        "{{/선택}}\n",
        "{{/항목}}\n",
        "끝.\n",
    );
    const OUTPUT: &str = "수신: ○○청\n담당자: 홍길동\n견적서를 첨부합니다.\n끝.\n";
    const BROKEN: &str = "수신: {{수신}}\n{{#항목 첨부 첨부}}\n내용\n";

    struct Case {
        structure: ExecutionTemplateStructure,
        operations: Vec<Value>,
        requirements: Vec<Value>,
        values: HashMap<String, String>,
        native: &'static str,
    }
    impl Case {
        fn new() -> Self {
            Self {
                structure: inspect_txt_qualification(BODY.as_bytes())
                    .unwrap()
                    .execution_structure
                    .unwrap(),
                operations: vec![
                    json!({"op":"REMOVE_OPTION","slot_id":"첨부","option_id":"계약서"}),
                    json!({"op":"APPLY_FIELD_BINDING","field_id":"수신"}),
                    json!({"op":"APPLY_FIELD_BINDING","field_id":"담당자"}),
                ],
                requirements: ["수신", "담당자"]
                    .map(|name| json!({"field_id":name,"expected_active_occurrence_count":1}))
                    .into(),
                values: [("수신", "○○청"), ("담당자", "홍길동"), ("건명", "무언가")]
                    .map(|(key, value)| (key.into(), value.into()))
                    .into(),
                native: TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
            }
        }
        fn execute(&self, source: &[u8]) -> Result<TxtExecutionOutcome, ConformanceExecutionError> {
            apply_txt_execution_operations_in_memory(
                source,
                &self.operations,
                &self.structure,
                &self.values,
            )
        }
        fn verify(
            &self,
            source: &[u8],
            output: &[u8],
            facts: Option<&BTreeMap<String, usize>>,
        ) -> Result<ConformanceResult, ConformanceExecutionError> {
            verify_txt_materialization_postconditions_parts(
                source,
                output,
                NativePlanView {
                    native_primitive_contract_id: self.native,
                    ordered_operations: &self.operations,
                    active_field_requirements: &self.requirements,
                },
                &self.structure,
                &self.values,
                facts,
            )
        }
    }
    fn assert_failure(result: ConformanceResult, expected: &str, reason: &str) {
        let ConformanceResult::Failure { code, detail } = result else {
            panic!("invalid bytes passed: {result:?}")
        };
        assert_eq!(code, expected);
        assert!(detail.contains(reason), "{detail}");
    }

    #[test]
    fn execution_preserves_line_endings_and_qualifies_only_the_selected_content() {
        let case = Case::new();
        for ending in ["\n", "\r\n"] {
            let body = BODY.replace('\n', ending);
            assert!(matches!(
                verify_txt_structure_bytes_consistency(body.as_bytes(), &case.structure),
                ConformanceResult::Pass { .. }
            ));
            let TxtExecutionOutcome::Materialized(result) = case.execute(body.as_bytes()).unwrap()
            else {
                panic!("valid source refused")
            };
            assert_eq!(result.output_bytes, OUTPUT.replace('\n', ending).as_bytes());
            assert_eq!(result.stage_facts["removed_options"], 1);
            assert_eq!(result.stage_facts["removed_lines"], 3);
            assert_eq!(result.stage_facts["cleaned_marker_lines"], 4);
            assert_eq!(result.stage_facts["written_field_occurrences"], 2);
            assert_eq!(
                case.verify(
                    body.as_bytes(),
                    &result.output_bytes,
                    Some(&result.stage_facts)
                )
                .unwrap(),
                pass(&result.output_bytes, vec![])
            );
        }
    }

    #[test]
    fn intermediate_checks_distinguish_incomplete_removal_content_loss_and_surviving_markers() {
        let mut case = Case::new();
        let (targets, authorized) = authorized(&case.operations, &case.structure);
        let scan = scan_text_structure(BODY);
        assert_failure(
            verify_removed_options(&scan, &targets, &authorized).unwrap(),
            REMOVAL_INCOMPLETE,
            "계약서",
        );
        assert_failure(
            verify_removed_options(
                &scan_text_structure("수신: {{수신}}\n"),
                &targets,
                &authorized,
            )
            .unwrap(),
            PRESERVED_CONTENT_LOST,
            "견적서",
        );
        let broken = BODY.replace("{{#선택 계약서 계약서}}\n", "");
        assert_failure(
            verify_removed_options(&scan_text_structure(&broken), &targets, &authorized).unwrap(),
            REPARSE_FAILED,
            "제거 뒤 재스캔",
        );
        assert_failure(
            verify_removed_options(&scan, &HashSet::new(), &authorized).unwrap(),
            REMOVAL_INCOMPLETE,
            "남은 Option",
        );
        assert_failure(
            verify_cleaned_markers(&scan).unwrap(),
            MARKER_CLEANUP_VIOLATION,
            "마커 소거 뒤에도",
        );
        assert!(verify_cleaned_markers(&scan_text_structure(OUTPUT)).is_none());
        let selected = BODY.replace(
            "{{#선택 계약서 계약서}}\n계약서를 첨부합니다. {{건명}}\n{{/선택}}\n",
            "",
        );
        assert!(
            verify_removed_options(&scan_text_structure(&selected), &targets, &authorized)
                .is_none()
        );
        case.structure.option_regions[1].option_id = "absent".into();
        let TxtExecutionOutcome::Failure(result) = case.execute(BODY.as_bytes()).unwrap() else {
            panic!("executor ignored its intermediate refusal")
        };
        assert_failure(result, PRESERVED_CONTENT_LOST, "absent");
    }

    #[test]
    fn precheck_and_executor_reject_invalid_bytes_operations_and_missing_values() {
        let mut case = Case::new();
        for source in [
            vec![0xff],
            vec![0xe3],
            BROKEN.as_bytes().to_vec(),
            format!("{BODY}추가 {{{{추가필드}}}}\n").into_bytes(),
        ] {
            assert_failure(
                verify_txt_structure_bytes_consistency(&source, &case.structure),
                STRUCTURE_BYTES_INCONSISTENT,
                "",
            );
        }
        let empty_structure = inspect_txt_qualification(b"plain\n")
            .unwrap()
            .execution_structure
            .unwrap();
        assert_failure(
            verify_txt_structure_bytes_consistency(BODY.as_bytes(), &empty_structure),
            STRUCTURE_BYTES_INCONSISTENT,
            "Option id",
        );
        let TxtExecutionOutcome::Failure(result) = case.execute(BROKEN.as_bytes()).unwrap() else {
            panic!("broken source executed")
        };
        assert_failure(result, REPARSE_FAILED, "candidate 스캔");
        assert!(
            case.execute(&[0xe3])
                .unwrap_err()
                .to_string()
                .contains("unexpected end of data")
        );
        case.values.remove("담당자");
        assert!(
            case.execute(BODY.as_bytes())
                .unwrap_err()
                .to_string()
                .contains("대응하는 VDR document value 가 없다")
        );
        for (op, reason) in [
            (json!({"op":"REWRITE_EVERYTHING"}), "미지원 operation code"),
            (json!({"slot_id":"첨부"}), "op code 가 없다"),
            (json!({"op":"APPLY_FIELD_BINDING"}), "field_id 가 없다"),
        ] {
            case.operations = vec![op];
            assert!(
                case.execute(BODY.as_bytes())
                    .unwrap_err()
                    .to_string()
                    .contains(reason)
            );
        }
    }

    #[test]
    fn final_verifier_distinguishes_source_mutation_output_damage_counts_and_values() {
        let mut case = Case::new();
        for (source, output, code, detail) in [
            (
                vec![0xff],
                vec![],
                SOURCE_CANDIDATE_MUTATED,
                "source 를 UTF-8",
            ),
            (
                BROKEN.as_bytes().to_vec(),
                vec![],
                SOURCE_CANDIDATE_MUTATED,
                "source 스캔",
            ),
            (
                b"plain\n".to_vec(),
                b"plain\n".to_vec(),
                SOURCE_CANDIDATE_MUTATED,
                "source 변형",
            ),
            (
                BODY.as_bytes().to_vec(),
                vec![0xff],
                REPARSE_FAILED,
                "output 를 UTF-8",
            ),
            (
                BODY.as_bytes().to_vec(),
                BROKEN.as_bytes().to_vec(),
                REPARSE_FAILED,
                "output 재스캔",
            ),
            (
                BODY.as_bytes().to_vec(),
                "{{#항목 첨부 첨부}}\n내용\n{{/항목}}\n".as_bytes().to_vec(),
                MARKER_CLEANUP_VIOLATION,
                "output 에 구간 마커",
            ),
            (
                BODY.as_bytes().to_vec(),
                "수신: {{수신}}\n".as_bytes().to_vec(),
                FIELD_TEXT_MISMATCH,
                "미치환 필드 토큰",
            ),
        ] {
            assert_failure(case.verify(&source, &output, None).unwrap(), code, detail);
        }
        let facts = BTreeMap::from([("written_field_occurrences".into(), 2)]);
        case.requirements[0]["expected_active_occurrence_count"] = json!(3);
        assert_failure(
            case.verify(BODY.as_bytes(), OUTPUT.as_bytes(), Some(&facts))
                .unwrap(),
            OCCURRENCE_COUNT_MISMATCH,
            "등장 2 != 기대 4",
        );
        case.requirements[0]["expected_active_occurrence_count"] = json!(1);
        case.values.insert("수신".into(), "다른 값".into());
        assert_failure(
            case.verify(BODY.as_bytes(), OUTPUT.as_bytes(), Some(&facts))
                .unwrap(),
            FIELD_TEXT_MISMATCH,
            "Active Field '수신'",
        );
        case.values.insert("수신".into(), "".into());
        assert!(matches!(
            case.verify(BODY.as_bytes(), OUTPUT.as_bytes(), Some(&BTreeMap::new()))
                .unwrap(),
            ConformanceResult::Pass { .. }
        ));
        case.native = "hwpx-native-primitive/v1";
        assert!(
            case.verify(&[0xff], &[0xff], None)
                .unwrap_err()
                .to_string()
                .contains("미지원 native primitive contract")
        );
    }
}
