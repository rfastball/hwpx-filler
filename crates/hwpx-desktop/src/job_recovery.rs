//! Read-only recovery coordinates for current record validation issues.

use super::*;
use hwpx_filler::fresh_execution_observation::FreshExecutionObservation;
use hwpx_filler::workbench_execution_status::CURRENT;

const STALE_TARGET: &str =
    "데이터가 다시 불러와져 문제 위치를 복원할 수 없습니다. 현재 데이터에서 다시 확인해 주세요.";

fn record_coordinate_current(state: &JobState, target: &Value) -> bool {
    let Some(index) = target.get("model_index").and_then(Value::as_u64) else {
        return false;
    };
    let Some(generation) = target.get("snapshot_generation").and_then(Value::as_u64) else {
        return false;
    };
    let Some(index) = usize::try_from(index).ok() else {
        return false;
    };
    let Some(generation) = usize::try_from(generation).ok() else {
        return false;
    };
    generation == state.data.snapshot_generation as usize
        && state.data.selected_indices().contains(&index)
        && target.get("record_identity").and_then(Value::as_str)
            == Some(format!("current-record/{generation}/{index}").as_str())
}

fn target_is_current(state: &JobState, target: &Value) -> bool {
    let Some((work_ref, plan)) = state.record_preparation_plan.as_ref() else {
        return false;
    };
    let Some(FreshExecutionObservation::Sealed(sealed)) = state.fresh_observation.as_ref() else {
        return false;
    };
    state.orchestration == CURRENT
        && state
            .seated
            .as_ref()
            .is_some_and(|seat| seat.job.name == *work_ref)
        && record_coordinate_current(state, target)
        && sealed.sealed_plan_value == *plan
}

fn target_location(
    index: usize,
    field: &str,
    kind: &str,
    columns: &[String],
    hidden: &HashSet<String>,
    visible: &[usize],
) -> Result<Value, JobControllerError> {
    let column = columns.iter().position(|column| column == field);
    if kind == "cell" && column.is_none() {
        return Err(error("문제 데이터의 항목 위치를 복원할 수 없습니다."));
    }
    if kind == "cell" && hidden.contains(field) {
        return Err(error(
            "문제 항목이 숨겨져 있습니다. 열을 다시 표시한 뒤 이동해 주세요.",
        ));
    }
    if !visible.contains(&index) {
        return Err(error(
            "문제 행이 현재 검색 결과에 없습니다. 검색 조건을 해제해 주세요.",
        ));
    }
    let row = format!("jobRow-{index}");
    if kind == "row" {
        return Ok(json!({"ok":true,"element_id":row,"fallback_element_id":row}));
    }
    Ok(
        json!({"ok":true,"element_id":format!("jobCell-{index}-{}",column.expect("checked column")),"fallback_element_id":row}),
    )
}

impl JobController {
    pub(super) fn recover_record_issue(
        &self,
        payload: &Value,
    ) -> Result<Value, JobControllerError> {
        let target = payload
            .get("target")
            .ok_or_else(|| error("문제 위치 정보가 올바르지 않습니다."))?;
        if !target.is_object() {
            return Err(error("문제 위치 정보가 올바르지 않습니다."));
        }
        let state = self.state()?;
        if state.record_preparation_plan.is_none() {
            return Err(error(
                "현재 데이터 확인 결과가 없습니다. 다시 확인해 주세요.",
            ));
        }
        let targets = state
            .panel_snapshot
            .pointer("/workbench_observation/record_validation/issues")
            .and_then(Value::as_array)
            .ok_or_else(|| error(STALE_TARGET))?;
        if !targets
            .iter()
            .any(|issue| issue.get("recovery_target") == Some(target))
            || !target_is_current(&state, target)
        {
            return Err(error(STALE_TARGET));
        }
        let index = target["model_index"]
            .as_u64()
            .expect("validated model index") as usize;
        let field = target["field_id"].as_str().expect("validated field ID");
        let kind = target["target_kind"]
            .as_str()
            .expect("validated target kind");
        let columns = state
            .data
            .filter
            .as_ref()
            .map_or_else(Vec::new, |filter| filter.columns());
        let visible = state
            .data
            .filter
            .as_ref()
            .map(|filter| filter.visible_indices(&state.data.records))
            .transpose()
            .map_err(|failure| error(failure.message))?
            .unwrap_or_default();
        target_location(
            index,
            field,
            kind,
            &columns,
            &state.data.hidden_columns,
            &visible,
        )
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn current_issue_targets_point_at_visible_rows_or_cells_and_refuse_unreachable_sites() {
        let columns = vec!["name".into(), "amount".into()];
        let visible = [1];
        assert_eq!(
            target_location(1, "name", "cell", &columns, &HashSet::new(), &visible).unwrap(),
            json!({"ok":true,"element_id":"jobCell-1-0","fallback_element_id":"jobRow-1"})
        );
        assert_eq!(
            target_location(1, "missing", "row", &columns, &HashSet::new(), &visible).unwrap(),
            json!({"ok":true,"element_id":"jobRow-1","fallback_element_id":"jobRow-1"})
        );
        assert!(
            target_location(1, "missing", "cell", &columns, &HashSet::new(), &visible)
                .unwrap_err()
                .message
                .contains("항목 위치")
        );
        assert!(
            target_location(
                1,
                "name",
                "cell",
                &columns,
                &HashSet::from(["name".into()]),
                &visible
            )
            .unwrap_err()
            .message
            .contains("숨겨져")
        );
        assert!(
            target_location(1, "name", "cell", &columns, &HashSet::new(), &[])
                .unwrap_err()
                .message
                .contains("검색 결과")
        );
    }
}
