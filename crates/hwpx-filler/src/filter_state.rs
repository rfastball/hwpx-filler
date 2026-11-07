//! Data-zone filter state: ordered column predicates and saved-preset dimensions.

mod describe;
mod dimensions;
mod matching;
mod presets;
mod transfer;
mod view;

pub use view::{AdhocChip, FilterView};

use crate::data_source::Record;
use crate::filter_primitives::{
    KIND_AMOUNT, KIND_DATE, KIND_TEXT, RangeCondition, valid_range_operand,
};
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use indexmap::IndexMap;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const SEARCH_DIMENSION: &str = "__search__";
const PRESET_NAME_EMPTY: &str = "이름을 비울 수 없습니다.";
const PRESET_NAME_TAKEN: &str = "같은 이름의 필터가 있습니다.";
const PRESET_STATE_EMPTY: &str = "저장할 조건이 없습니다.";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FilterError {
    pub message: String,
    pub column: String,
}
impl fmt::Display for FilterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}
impl std::error::Error for FilterError {}
fn fail(message: impl Into<String>) -> FilterError {
    FilterError {
        message: message.into(),
        column: String::new(),
    }
}
fn in_column(message: impl Into<String>, column: &str) -> FilterError {
    FilterError {
        message: message.into(),
        column: column.into(),
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct ColumnCondition {
    values: Option<Vec<String>>,
    text: String,
    range: Option<RangeCondition>,
}
impl ColumnCondition {
    fn active(&self) -> bool {
        self.values.is_some() || !self.text.is_empty() || self.range.is_some()
    }
    fn to_value(&self) -> Value {
        let range = self.range.as_ref().map(|range| {
            json!({
                "first":{"op":range.first.op,"operand":range.first.operand},
                "second":range.second.as_ref().map(|clause| json!({"op":clause.op,"operand":clause.operand})),
                "joiner":range.joiner,
            })
        });
        json!({"text":self.text,"values":self.values,"range":range})
    }
}
#[derive(Clone, Debug)]
struct ConditionGroup {
    cols: IndexMap<String, ColumnCondition>,
    search: String,
    pruned: HashSet<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FilterModel {
    columns: Vec<String>,
    kinds: HashMap<String, String>,
    cols: IndexMap<String, ColumnCondition>,
    search: String,
    pruned: HashSet<String>,
    presets: IndexMap<String, Value>,
    active_presets: Vec<String>,
}
impl FilterModel {
    pub fn new(columns: Vec<String>, kinds: HashMap<String, String>) -> Self {
        let cols = columns
            .iter()
            .map(|name| (name.clone(), ColumnCondition::default()))
            .collect();
        Self {
            columns,
            kinds,
            cols,
            search: String::new(),
            pruned: HashSet::new(),
            presets: IndexMap::new(),
            active_presets: vec![],
        }
    }
    fn require(&self, column: &str) -> Result<(), FilterError> {
        if self.cols.contains_key(column) {
            Ok(())
        } else {
            Err(fail(format!(
                "알 수 없는 열: {}",
                python_repr(&Value::String(column.into()))
            )))
        }
    }
    pub fn columns(&self) -> Vec<String> {
        self.columns.clone()
    }
    pub fn kind(&self, column: &str) -> Result<&str, FilterError> {
        self.require(column)?;
        Ok(self.kinds.get(column).map_or(KIND_TEXT, String::as_str))
    }
    pub fn is_active(&self) -> bool {
        self.has_adhoc() || !self.active_presets.is_empty()
    }
    pub fn has_adhoc(&self) -> bool {
        !self.search.is_empty() || self.cols.values().any(ColumnCondition::active)
    }
    pub fn has_condition(&self, column: &str) -> Result<bool, FilterError> {
        self.require(column)?;
        Ok(self.cols[column].active())
    }
    pub fn column_state(&self, column: &str) -> Result<Value, FilterError> {
        self.require(column)?;
        Ok(self.cols[column].to_value())
    }
    pub fn search_text(&self) -> &str {
        &self.search
    }
    pub fn set_values(
        &mut self,
        column: &str,
        values: Option<Vec<String>>,
    ) -> Result<(), FilterError> {
        self.require(column)?;
        self.cols.get_mut(column).expect("validated column").values = values.map(|values| {
            let mut seen = HashSet::new();
            values
                .into_iter()
                .filter(|value| seen.insert(value.clone()))
                .collect()
        });
        Ok(())
    }
    pub fn set_text(&mut self, column: &str, text: &str) -> Result<(), FilterError> {
        self.require(column)?;
        self.cols.get_mut(column).expect("validated column").text = python_trim(text).into();
        Ok(())
    }
    pub fn set_range(
        &mut self,
        column: &str,
        condition: Option<RangeCondition>,
    ) -> Result<(), FilterError> {
        self.require(column)?;
        let Some(range) = condition else {
            self.cols.get_mut(column).expect("validated column").range = None;
            return Ok(());
        };
        let kind = self.kind(column)?;
        if !matches!(kind, KIND_AMOUNT | KIND_DATE) {
            return Err(fail(format!(
                "범위 조건은 일자·금액 열 전용입니다: {} 은(는) 텍스트 열",
                python_repr(&Value::String(column.into()))
            )));
        }
        for clause in std::iter::once(&range.first).chain(range.second.iter()) {
            if !matches!(clause.op.as_str(), "eq" | "ne" | "gt" | "ge" | "lt" | "le") {
                return Err(fail(format!(
                    "알 수 없는 비교 연산자: {}",
                    python_repr(&Value::String(clause.op.clone()))
                )));
            }
            if !valid_range_operand(kind, &clause.operand) {
                let (noun, example) = if kind == KIND_AMOUNT {
                    ("금액", "100,000,000")
                } else {
                    ("날짜", "2026-07-15")
                };
                return Err(fail(format!(
                    "'{}' 을(를) {noun}(으)로 읽을 수 없습니다. 숫자 형태로 입력하세요(예: {example}).",
                    clause.operand
                )));
            }
        }
        if !matches!(range.joiner.as_str(), "and" | "or") {
            return Err(fail(format!(
                "조건 연결 방식을 알 수 없습니다: {}",
                python_repr(&Value::String(range.joiner))
            )));
        }
        self.cols.get_mut(column).expect("validated column").range = Some(range);
        Ok(())
    }
    pub fn set_search(&mut self, text: &str) {
        self.search = python_trim(text).into();
        self.pruned.clear();
    }
    pub fn prune_branch(&mut self, column: &str, records: &[Record]) -> Result<(), FilterError> {
        self.require(column)?;
        self.pruned.insert(column.into());
        if !self.search.is_empty() && self.view(records)?.branches.is_empty() {
            self.search.clear();
            self.pruned.clear();
        }
        Ok(())
    }
    pub fn clear_column(&mut self, column: &str) -> Result<(), FilterError> {
        self.require(column)?;
        self.cols.insert(column.into(), ColumnCondition::default());
        Ok(())
    }
    fn clear_adhoc(&mut self) {
        self.cols = self
            .columns
            .iter()
            .map(|name| (name.clone(), ColumnCondition::default()))
            .collect();
        self.search.clear();
        self.pruned.clear();
    }
    pub fn clear(&mut self) {
        self.clear_adhoc();
        self.active_presets.clear();
    }
    pub fn blank_copy(&self) -> Self {
        let mut copy = Self::new(self.columns.clone(), self.kinds.clone());
        copy.presets = self.presets.clone();
        copy
    }
}
fn value_text(value: &Value) -> String {
    match value {
        Value::String(value) => value.clone(),
        _ => python_repr(value),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::filter_primitives::{PRESET_UNREADABLE, RangeClause, sniff_column_kinds};

    fn records() -> Vec<Record> {
        [
            ("청사 청소", "95,000,000", "2026-03-02"),
            ("전산 유지보수", "150,000,000", "2026-08-14"),
            ("공용차량 임차", "230,000,000", "2026-05-20"),
            ("사무용품", "50,000,000", "2026-09-01"),
            ("방역 용역", "219,999,999", "2026-06-30"),
        ]
        .into_iter()
        .map(|(name, price, day)| {
            let mut record = Record::new();
            record.insert("공고명".into(), name.into());
            record.insert("추정가격".into(), price.into());
            record.insert("계약일자".into(), day.into());
            record
        })
        .collect()
    }

    fn search_records() -> Vec<Record> {
        [
            (
                "행정도시 청사 이전",
                "행복도시건설청",
                "2026-07-20",
                "1,000,000원",
                "",
            ),
            (
                "물품 구매",
                "세종청사관리소",
                "2026-07-25",
                "2,500,000원",
                "행복도시 납품",
            ),
            (
                "닭고기 급식 납품",
                "행복도시건설청",
                "2026-08-01",
                "500,000원",
                "",
            ),
            ("사무용품", "조달청", "2026-08-10", "3,000,000원", "긴급"),
        ]
        .into_iter()
        .map(|(name, agency, day, amount, note)| {
            [
                ("공고명".into(), name.into()),
                ("수요기관".into(), agency.into()),
                ("마감일".into(), day.into()),
                ("금액".into(), amount.into()),
                ("비고".into(), note.into()),
            ]
            .into()
        })
        .collect()
    }

    fn search_model(rows: &[Record]) -> FilterModel {
        FilterModel::new(
            rows[0].keys().cloned().collect(),
            sniff_column_kinds(rows, &HashMap::new()),
        )
    }
    #[test]
    fn saved_dimensions_and_ad_hoc_filter_restate_the_same_visible_rows() {
        let records = records();
        let columns = records[0].keys().cloned().collect();
        let kinds = sniff_column_kinds(&records, &HashMap::new());
        let mut model = FilterModel::new(columns, kinds);
        let small =
            json!({"columns":{"추정가격":{"range":{"first":{"op":"lt","operand":"100,000,000"}}}}});
        let medium = json!({"columns":{"추정가격":{"range":{"first":{"op":"ge","operand":"100,000,000"},"second":{"op":"lt","operand":"220,000,000"},"joiner":"and"}}}});
        let first_half = json!({"columns":{"계약일자":{"range":{"first":{"op":"ge","operand":"2026-01-01"},"second":{"op":"le","operand":"2026-06-30"},"joiner":"and"}}}});
        model.create_preset("소기업", &small, false).unwrap();
        model.deactivate_preset("소기업").unwrap();
        model.create_preset(" 중소기업 ", &medium, false).unwrap();
        model.deactivate_preset("중소기업").unwrap();
        model.create_preset("상반기", &first_half, false).unwrap();
        model.deactivate_preset("상반기").unwrap();
        model.activate_preset("소기업").unwrap();
        model.activate_preset("중소기업").unwrap();
        assert_eq!(model.visible_indices(&records).unwrap(), vec![0, 1, 3, 4]);
        assert_eq!(
            model.describe(&records).unwrap(),
            "필터 '소기업' 또는 '중소기업'"
        );
        model.activate_preset("상반기").unwrap();
        assert_eq!(model.visible_indices(&records).unwrap(), vec![0, 4]);
        assert_eq!(
            model.active_preset_groups().unwrap(),
            vec![
                vec!["소기업".to_string(), "중소기업".to_string()],
                vec!["상반기".to_string()]
            ]
        );
        model.set_text("공고명", "방역").unwrap();
        assert_eq!(model.visible_indices(&records).unwrap(), vec![4]);
        assert_eq!(
            model
                .view(&records)
                .unwrap()
                .column_values("공고명")
                .unwrap(),
            vec!["방역 용역"]
        );
        let state = model.export_state();
        let mut copy = model.blank_copy();
        copy.apply_state(&state).unwrap();
        assert_eq!(copy.visible_indices(&records).unwrap(), vec![4]);
    }

    #[test]
    fn search_branches_follow_visible_rows_and_pruning_lives_with_the_search() {
        let rows = search_records();
        let mut model = search_model(&rows);
        model.set_search("행복도");
        assert_eq!(model.group_branches(&rows).unwrap(), ["수요기관", "비고"]);
        assert_eq!(model.visible_indices(&rows).unwrap(), [0, 1, 2]);

        model
            .set_values("수요기관", Some(vec!["행복도시건설청".into()]))
            .unwrap();
        assert_eq!(model.group_branches(&rows).unwrap(), ["수요기관"]);
        model.set_values("수요기관", None).unwrap();
        model.prune_branch("비고", &rows).unwrap();
        model.set_text("공고명", "닭").unwrap();
        assert_eq!(model.group_branches(&rows).unwrap(), ["수요기관"]);
        assert_eq!(model.export_state()["pruned"], json!(["비고"]));
        model.set_text("공고명", "").unwrap();
        model.set_search("행복도시");
        assert!(
            model
                .group_branches(&rows)
                .unwrap()
                .contains(&"비고".into())
        );

        model.set_search("긴급");
        assert_eq!(model.group_branches(&rows).unwrap(), ["비고"]);
        assert_eq!(model.visible_indices(&rows).unwrap(), [3]);
        assert!(!model.has_condition("비고").unwrap());
        assert!(
            model
                .describe(&rows)
                .unwrap()
                .contains("(비고) 포함 '긴급'")
        );
        model.prune_branch("비고", &rows).unwrap();
        assert!(model.search_text().is_empty());
        assert!(!model.is_active());
        assert_eq!(model.visible_indices(&rows).unwrap(), [0, 1, 2, 3]);
    }

    #[test]
    fn range_admission_refuses_ambiguous_inputs_without_losing_the_previous_filter() {
        let rows = search_records();
        let mut model = search_model(&rows);
        let between = RangeCondition {
            first: RangeClause {
                op: "ge".into(),
                operand: "1,000,000".into(),
            },
            second: Some(RangeClause {
                op: "le".into(),
                operand: "2,500,000".into(),
            }),
            joiner: "and".into(),
        };
        model.set_range("금액", Some(between)).unwrap();
        assert_eq!(model.visible_indices(&rows).unwrap(), [0, 1]);
        let before = model.export_state();
        for (column, op, operand, expected) in [
            ("금액", "ge", "1억", "읽을 수 없습니다"),
            ("금액", "ge", "많이", "읽을 수 없습니다"),
            ("마감일", "le", "제2026-15호", "읽을 수 없습니다"),
            ("마감일", "ge", "다음주", "읽을 수 없습니다"),
            ("금액", "like", "1", "비교 연산자"),
            ("공고명", "ge", "1", "일자·금액 열 전용"),
        ] {
            let error = model
                .set_range(
                    column,
                    Some(RangeCondition {
                        first: RangeClause {
                            op: op.into(),
                            operand: operand.into(),
                        },
                        second: None,
                        joiner: "and".into(),
                    }),
                )
                .unwrap_err();
            assert!(error.message.contains(expected), "{error}");
            assert_eq!(model.export_state(), before);
        }
        let joiner = model
            .set_range(
                "금액",
                Some(RangeCondition {
                    first: RangeClause {
                        op: "ge".into(),
                        operand: "1".into(),
                    },
                    second: Some(RangeClause {
                        op: "le".into(),
                        operand: "2".into(),
                    }),
                    joiner: "xor".into(),
                }),
            )
            .unwrap_err();
        assert!(joiner.message.contains("조건 연결 방식"));
        assert_eq!(model.export_state(), before);
        let mut restored = model.blank_copy();
        restored.apply_state(&before).unwrap();
        assert_eq!(restored.export_state(), before);
        assert_eq!(restored.visible_indices(&rows).unwrap(), [0, 1]);
        let timed: Vec<Record> = ["2026-07-15 14:00", "2026-07-16 09:00"]
            .into_iter()
            .map(|value| [("마감".into(), value.into())].into())
            .collect();
        let mut dates = FilterModel::new(
            vec!["마감".into()],
            HashMap::from([("마감".into(), KIND_DATE.into())]),
        );
        for (operand, visible) in [("2026-07-15", vec![0]), ("2026-07-15 13:00", vec![])] {
            dates
                .set_range(
                    "마감",
                    Some(RangeCondition {
                        first: RangeClause {
                            op: "le".into(),
                            operand: operand.into(),
                        },
                        second: None,
                        joiner: "and".into(),
                    }),
                )
                .unwrap();
            assert_eq!(dates.visible_indices(&timed).unwrap(), visible);
        }
        let unreadable: Vec<Record> = ["1000", "미정", ""]
            .into_iter()
            .map(|value| [("c".into(), value.into())].into())
            .collect();
        let mut amount = FilterModel::new(
            vec!["c".into()],
            HashMap::from([("c".into(), KIND_AMOUNT.into())]),
        );
        amount
            .set_range(
                "c",
                Some(RangeCondition {
                    first: RangeClause {
                        op: "ne".into(),
                        operand: "9999".into(),
                    },
                    second: None,
                    joiner: "and".into(),
                }),
            )
            .unwrap();
        assert_eq!(amount.visible_indices(&unreadable).unwrap(), [0]);
    }

    #[test]
    fn checklist_keeps_reenable_values_but_respects_text_range_and_other_columns() {
        let rows = search_records();
        let mut model = search_model(&rows);
        model
            .set_values("수요기관", Some(vec!["조달청".into()]))
            .unwrap();
        assert_eq!(
            model.column_values("수요기관", &rows).unwrap(),
            ["행복도시건설청", "세종청사관리소", "조달청"]
        );
        model
            .set_values("수요기관", Some(vec!["행복도시건설청".into()]))
            .unwrap();
        assert_eq!(model.column_values("비고", &rows).unwrap(), [""]);
        model.set_values("수요기관", None).unwrap();
        assert_eq!(
            model.column_values("비고", &rows).unwrap(),
            ["행복도시 납품", "긴급", ""]
        );

        model.set_text("공고명", "납품").unwrap();
        model.set_values("공고명", Some(vec![])).unwrap();
        assert!(model.visible_indices(&rows).unwrap().is_empty());
        assert_eq!(
            model.column_values("공고명", &rows).unwrap(),
            ["닭고기 급식 납품"]
        );
        model
            .set_values("공고명", Some(vec!["닭고기 급식 납품".into()]))
            .unwrap();
        assert_eq!(model.visible_indices(&rows).unwrap(), [2]);
        model.clear_column("공고명").unwrap();
        model
            .set_range(
                "금액",
                Some(RangeCondition {
                    first: RangeClause {
                        op: "ge".into(),
                        operand: "2,000,000".into(),
                    },
                    second: None,
                    joiner: "and".into(),
                }),
            )
            .unwrap();
        assert_eq!(
            model.column_values("금액", &rows).unwrap(),
            ["2,500,000원", "3,000,000원"]
        );

        model.clear();
        model.set_text("수요기관", "건설청").unwrap();
        model.set_search("행복도");
        assert_eq!(
            model
                .view(&rows)
                .unwrap()
                .segments("수요기관", "행복도시건설청")
                .unwrap(),
            [("행복도".into(), true), ("시건설청".into(), false)]
        );
        assert_eq!(
            model
                .view(&rows)
                .unwrap()
                .segments("마감일", "2026-07-20")
                .unwrap(),
            [("2026-07-20".into(), false)]
        );
        assert!(
            model
                .view(&rows)
                .unwrap()
                .segments("비고", "")
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn preset_transfer_preserves_names_and_refuses_incompatible_or_corrupt_definitions() {
        let rows = records();
        let columns = rows[0].keys().cloned().collect();
        let kinds = sniff_column_kinds(&rows, &HashMap::new());
        let mut model = FilterModel::new(columns, kinds);
        let small =
            json!({"columns":{"추정가격":{"range":{"first":{"op":"lt","operand":"100,000,000"}}}}});
        let medium = json!({"columns":{"추정가격":{"range":{"first":{"op":"ge","operand":"100,000,000"},"second":{"op":"lt","operand":"220,000,000"},"joiner":"and"}}}});
        assert!(
            model
                .create_preset("빈 필터", &json!({"columns":{}}), false)
                .is_err()
        );
        model.create_preset("소기업", &small, false).unwrap();
        model.create_preset("중소기업", &medium, false).unwrap();
        assert!(model.create_preset("소기업", &small, false).is_err());
        model.activate_preset("소기업").unwrap();
        model.activate_preset("중소기업").unwrap();
        let state = model.export_state();
        assert_eq!(state["active_presets"], json!(["소기업", "중소기업"]));
        assert!(state.get("presets").is_none());
        let copied = model.clone_state().unwrap();
        assert_eq!(copied.export_state(), state);
        assert_eq!(copied.presets(), model.presets());

        let mut without_definitions = FilterModel::new(model.columns(), HashMap::new());
        let (installed, dropped) = without_definitions.apply_state(&state).unwrap();
        assert!(installed.is_empty());
        assert_eq!(dropped, ["필터 '소기업'", "필터 '중소기업'"]);
        let mut restored = model.blank_copy();
        let (_, dropped) = restored.apply_state(&state).unwrap();
        assert!(dropped.is_empty());
        assert_eq!(
            restored.visible_indices(&rows).unwrap(),
            model.visible_indices(&rows).unwrap()
        );
        assert_eq!(
            model
                .set_presets(
                    &model
                        .presets()
                        .into_iter()
                        .filter(|item| item["name"] == "중소기업")
                        .collect::<Vec<_>>(),
                    &HashMap::new()
                )
                .unwrap(),
            ["소기업"]
        );
        assert_eq!(model.active_presets(), ["중소기업"]);

        let mut wrong_columns = FilterModel::new(vec!["공고명".into()], HashMap::new());
        wrong_columns
            .set_presets(&restored.presets(), &HashMap::new())
            .unwrap();
        let (usable, reason) = wrong_columns.preset_status("소기업");
        assert!(!usable);
        assert!(reason.contains("추정가격"));
        assert!(wrong_columns.activate_preset("소기업").is_err());
        let corrupt = json!({"name":"망가짐","state":{"columns":["추정가격"]}});
        wrong_columns
            .set_presets(&[corrupt], &HashMap::new())
            .unwrap();
        assert_eq!(
            wrong_columns.preset_status("망가짐"),
            (false, PRESET_UNREADABLE.into())
        );
        let duplicate = json!({"name":" 중소기업 ","state":{}});
        let second = restored.presets()[1].clone();
        assert!(
            restored
                .set_presets(&[second, duplicate], &HashMap::new())
                .is_err()
        );
        assert!(
            restored
                .normalize_preset_state(&json!({"active_presets":["소기업"]}), false)
                .is_err()
        );
        assert_eq!(
            restored
                .normalize_preset_state(&json!({"columns":{"지역":{"values":["세종"]}}}), false)
                .unwrap_err()
                .column,
            "지역"
        );
        assert_eq!(restored.normalize_preset_state(&json!({"columns":{"추정가격":{"range":{"first":{"op":"lt","operand":"1억"}}}}}), false).unwrap_err().column, "추정가격");
        assert!(
            restored
                .normalize_preset_state(&json!({"columns":{}}), false)
                .is_err()
        );
    }

    #[test]
    fn sniffing_and_search_sampling_keep_code_columns_and_minor_branches_visible() {
        let rows = search_records();
        let kinds = sniff_column_kinds(&rows, &HashMap::new());
        assert_eq!(kinds["금액"], KIND_AMOUNT);
        assert_eq!(kinds["마감일"], KIND_DATE);
        for values in [
            ["1차", "2차"],
            ["A-1", "B-2"],
            ["3층", "5층"],
            ["1억", "2억"],
            ["", ""],
        ] {
            let records: Vec<Record> = values
                .into_iter()
                .map(|value| [("c".into(), value.into())].into())
                .collect();
            assert_eq!(
                sniff_column_kinds(&records, &HashMap::new())["c"],
                KIND_TEXT
            );
        }
        let numbers: Vec<Record> = ["1000", "2000"]
            .into_iter()
            .map(|value| [("c".into(), value.into())].into())
            .collect();
        assert_eq!(
            sniff_column_kinds(&numbers, &HashMap::from([("c".into(), KIND_TEXT.into())]))["c"],
            KIND_TEXT
        );

        let mut samples: Vec<Record> = (0..10)
            .map(|index| {
                [
                    ("공고명".into(), format!("행복도시 사업 {index}")),
                    ("비고".into(), String::new()),
                ]
                .into()
            })
            .collect();
        samples.push(
            [
                ("공고명".into(), "무관".into()),
                ("비고".into(), "행복도시 납품".into()),
            ]
            .into(),
        );
        let mut model = FilterModel::new(vec!["공고명".into(), "비고".into()], HashMap::new());
        model.set_search("행복도시");
        let indices = model.visible_indices(&samples).unwrap();
        assert_eq!(
            model
                .stratified_sample(&indices, &samples, 3)
                .unwrap()
                .len(),
            3
        );
        assert!(
            model
                .stratified_sample(&indices, &samples, 3)
                .unwrap()
                .contains(&10)
        );
        model.set_search("없는말");
        assert!(model.visible_indices(&samples).unwrap().is_empty());
        assert_eq!(
            model.describe_parts(&samples).unwrap(),
            ["검색 '없는말' (매치 없음)"]
        );
    }

    #[test]
    fn preset_edit_keeps_order_activation_and_changes_dimension_without_stale_rows() {
        let rows = records();
        let mut model = FilterModel::new(
            rows[0].keys().cloned().collect(),
            sniff_column_kinds(&rows, &HashMap::new()),
        );
        let small =
            json!({"columns":{"추정가격":{"range":{"first":{"op":"lt","operand":"100,000,000"}}}}});
        let medium = json!({"columns":{"추정가격":{"range":{"first":{"op":"ge","operand":"100,000,000"},"second":{"op":"lt","operand":"220,000,000"},"joiner":"and"}}}});
        let first_half = json!({"columns":{"계약일자":{"range":{"first":{"op":"ge","operand":"2026-01-01"},"second":{"op":"le","operand":"2026-06-30"},"joiner":"and"}}}});
        assert_eq!(model.name_state(&small).unwrap(), "추정가격 < 100,000,000");
        assert_eq!(model.count_state(&small, &rows).unwrap(), 2);
        assert_eq!(
            model.create_preset("", &small, false).unwrap(),
            "추정가격 < 100,000,000"
        );
        model.deactivate_preset("추정가격 < 100,000,000").unwrap();
        model.set_text("공고명", "전산").unwrap();
        assert_eq!(model.count_state(&medium, &rows).unwrap(), 2);
        assert_eq!(
            model.create_preset("중소기업", &medium, false).unwrap(),
            "중소기업"
        );
        assert_eq!(model.visible_indices(&rows).unwrap(), [1]);
        assert_eq!(
            model.update_preset("중소기업", "중소", &medium).unwrap(),
            "중소"
        );
        assert_eq!(
            model
                .presets()
                .iter()
                .map(|item| item["name"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["추정가격 < 100,000,000", "중소"]
        );
        assert_eq!(model.active_presets(), ["중소"]);
        assert!(
            model
                .update_preset("중소", "추정가격 < 100,000,000", &medium)
                .is_err()
        );
        assert!(model.update_preset("없음", "없음", &medium).is_err());
        model.set_text("공고명", "").unwrap();
        model.update_preset("중소", "중소", &first_half).unwrap();
        assert_eq!(
            model.preset_dimension("중소").unwrap(),
            HashSet::from(["계약일자".into()])
        );
        assert_eq!(model.visible_indices(&rows).unwrap(), [0, 2, 4]);
        model.delete_preset("중소").unwrap();
        assert!(model.active_presets().is_empty());
        assert_eq!(model.visible_indices(&rows).unwrap(), [0, 1, 2, 3, 4]);

        model
            .set_range(
                "추정가격",
                Some(RangeCondition {
                    first: RangeClause {
                        op: "lt".into(),
                        operand: "100,000,000".into(),
                    },
                    second: None,
                    joiner: "and".into(),
                }),
            )
            .unwrap();
        let before = model.visible_indices(&rows).unwrap();
        let draft = model.adhoc_state();
        model.create_preset("소기업", &draft, true).unwrap();
        assert!(!model.has_adhoc());
        assert_eq!(model.visible_indices(&rows).unwrap(), before);
        assert_eq!(model.active_presets(), ["소기업"]);
    }
}
