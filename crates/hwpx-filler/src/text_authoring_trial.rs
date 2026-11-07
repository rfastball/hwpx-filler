//! TXT authoring preview through native two-stage materialization and postconditions.

use crate::execution_composition::TXT_NATIVE_PRIMITIVE_CONTRACT_ID;
use crate::execution_contract_set::{PLAN_APPLY_FIELD_BINDING, PLAN_REMOVE_OPTION};
use crate::materialization_conformance::{ConformanceResult, NativePlanView};
use crate::structure_scan::python_trim;
use crate::text_materialization_conformance::{
    TxtExecutionOutcome, apply_txt_execution_operations_in_memory,
    verify_txt_materialization_postconditions_parts, verify_txt_structure_bytes_consistency,
};
use crate::text_render::{SEG_LITERAL, render_segments};
use crate::text_structure::{
    TextStructureScan, drop_lines, marker_lines, scan_text_structure, unselected_option_lines,
};
use crate::text_template_inspection::inspect_txt_qualification;
use crate::txt_authoring::{trial, trial_document_values};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxtTrialError(pub String);
impl fmt::Display for TxtTrialError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TxtTrialError {}
fn fail(message: impl Into<String>) -> TxtTrialError {
    TxtTrialError(message.into())
}
fn failed(result: ConformanceResult, prefix: &str) -> Result<(), TxtTrialError> {
    match result {
        ConformanceResult::Failure { detail, .. } => Err(fail(format!("{prefix}: {detail}"))),
        ConformanceResult::Pass { .. } => Ok(()),
    }
}

/// Every optioned slot needs a valid trial choice, and every chosen slot must exist.
fn validate_slot_selection(
    scan: &TextStructureScan,
    selected: &Map<String, Value>,
) -> Result<(), TxtTrialError> {
    let mut known = HashSet::new();
    for slot in &scan.slots {
        known.insert(slot.id.as_str());
        let choice = selected.get(&slot.id).and_then(Value::as_str);
        if !slot.options.is_empty()
            && !slot
                .options
                .iter()
                .any(|option| Some(option.id.as_str()) == choice)
        {
            return Err(fail(format!(
                "'{}' 항목의 시험 선택을 지정하세요.",
                slot.id
            )));
        }
    }
    if selected.keys().any(|key| !known.contains(key.as_str())) {
        return Err(fail("존재하지 않는 항목 선택이 있습니다."));
    }
    Ok(())
}

/// Field names in first-seen order with how many active segments use each.
fn segment_field_counts(active: &str) -> Vec<(String, usize)> {
    let (segments, _) = render_segments(active, &HashMap::new());
    let mut counts = Vec::<(String, usize)>::new();
    for segment in segments {
        if segment.kind == SEG_LITERAL {
            continue;
        }
        let name = python_trim(&segment.name);
        if let Some((_, count)) = counts.iter_mut().find(|(existing, _)| existing == name) {
            *count += 1;
        } else {
            counts.push((name.into(), 1));
        }
    }
    counts
}

pub fn trial_txt_authoring(
    content: &str,
    values: &Map<String, Value>,
    selected: &Map<String, Value>,
) -> Result<Value, TxtTrialError> {
    let source = content.as_bytes();
    let inspection = inspect_txt_qualification(source).map_err(|error| fail(error.to_string()))?;
    let structure = inspection
        .execution_structure
        .ok_or_else(|| fail("구조 오류를 수정한 뒤 결과를 시험하세요."))?;
    let scan = scan_text_structure(content);
    validate_slot_selection(&scan, selected)?;
    let removals = scan
        .slots
        .iter()
        .flat_map(|slot| {
            slot.options
                .iter()
                .filter(|option| selected.get(&slot.id).and_then(Value::as_str) != Some(&option.id))
                .map(|option| json!({"op":PLAN_REMOVE_OPTION,"slot_id":slot.id,"option_id":option.id}))
        })
        .collect::<Vec<_>>();
    let chosen = selected
        .iter()
        .filter_map(|(slot, option)| {
            option
                .as_str()
                .map(|option| (slot.clone(), HashSet::from([option.to_owned()])))
        })
        .collect::<HashMap<_, _>>();
    let mut hidden = marker_lines(&scan);
    hidden.extend(unselected_option_lines(&scan, &chosen));
    let active = drop_lines(content, &hidden);
    let counts = segment_field_counts(&active);
    let names = counts
        .iter()
        .map(|(name, _)| name.clone())
        .collect::<Vec<_>>();
    let (logical, _) = trial_document_values(&names, values);
    let document_values = logical
        .into_iter()
        .filter_map(|(name, value)| value.as_str().map(|text| (name, text.to_owned())))
        .collect::<HashMap<_, _>>();
    let mut operations = removals;
    operations.extend(
        counts
            .iter()
            .map(|(name, _)| json!({"op":PLAN_APPLY_FIELD_BINDING,"field_id":name})),
    );
    let requirements = counts
        .iter()
        .map(|(name, count)| json!({"field_id":name,"expected_active_occurrence_count":count}))
        .collect::<Vec<_>>();
    let plan = NativePlanView {
        native_primitive_contract_id: TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
        ordered_operations: &operations,
        active_field_requirements: &requirements,
    };
    failed(
        verify_txt_structure_bytes_consistency(source, &structure),
        "결과 시험을 시작할 수 없습니다",
    )?;
    let materialized =
        apply_txt_execution_operations_in_memory(source, &operations, &structure, &document_values)
            .map_err(|error| fail(error.to_string()))?;
    let materialized = match materialized {
        TxtExecutionOutcome::Materialized(output) => output,
        TxtExecutionOutcome::Failure(ConformanceResult::Failure { detail, .. }) => {
            return Err(fail(format!("결과 시험에 실패했습니다: {detail}")));
        }
        TxtExecutionOutcome::Failure(_) => unreachable!(),
    };
    failed(
        verify_txt_materialization_postconditions_parts(
            source,
            &materialized.output_bytes,
            plan,
            &structure,
            &document_values,
            Some(&materialized.stage_facts),
        )
        .map_err(|error| fail(error.to_string()))?,
        "결과 시험 검증에 실패했습니다",
    )?;
    let output =
        std::str::from_utf8(&materialized.output_bytes).map_err(|error| fail(error.to_string()))?;
    trial(content, values, selected, output).map_err(|error| fail(error.to_string()))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn trial_keeps_astral_source_output_offsets_and_marks_missing_values() {
        let values = Map::from_iter([("F".into(), json!("🟢"))]);
        let rendered = trial_txt_authoring("😀 {{F}}\n", &values, &Map::new()).unwrap();
        assert_eq!(rendered["text"], "😀 🟢\n");
        assert_eq!(
            rendered["occurrences"],
            json!([{"name":"F","source_start":3,
            "source_end":8,"output_start":3,"output_end":5,"value":"🟢"}])
        );

        let blank = trial_txt_authoring(
            "{{이름}}·{{값}}\n",
            &Map::from_iter([("값".into(), json!("1"))]),
            &Map::new(),
        )
        .unwrap();
        assert_eq!(
            blank["report"],
            json!({"missing_fields":[],"empty_fields":["이름"]})
        );
        assert_eq!(blank["occurrences"][0]["value"], "〘미입력·이름〙");
        assert!(
            blank["text"]
                .as_str()
                .unwrap()
                .contains("〘미입력·이름〙·1")
        );
        let choice = "{{#항목 s 표시}}\n{{#선택 a 가}}\n가\n{{/선택}}\n{{/항목}}\n";
        assert!(
            trial_txt_authoring(choice, &Map::new(), &Map::new())
                .unwrap_err()
                .0
                .contains("시험 선택")
        );
    }
}
