//! Data-zone filter state: ordered column predicates and saved-preset dimensions.

use crate::data_source::Record;
use crate::filter_primitives::{
    KIND_AMOUNT, KIND_DATE, KIND_TEXT, PRESET_UNREADABLE, RangeClause, RangeCondition, cell_text,
    range_condition_from_payload, valid_range_operand,
};
use crate::format_engine::{ParsedDateTime, ParsedNumber, parse_dt, parse_number};
use crate::jamo::{jamo_contains, jamo_find};
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use indexmap::IndexMap;
use num_bigint::BigInt;
use regex::Regex;
use serde_json::{Map, Value, json};
use std::cmp::Ordering;
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::str::FromStr;
use std::sync::OnceLock;

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
    pub fn clone_state(&self) -> Result<Self, FilterError> {
        let mut copy = self.blank_copy();
        copy.apply_state(&self.export_state())?;
        Ok(copy)
    }
    pub fn adhoc_state(&self) -> Value {
        let columns = self
            .cols
            .iter()
            .filter(|(_, condition)| condition.active())
            .map(|(name, condition)| (name.clone(), condition.to_value()))
            .collect::<Map<_, _>>();
        let mut pruned = self.pruned.iter().cloned().collect::<Vec<_>>();
        pruned.sort();
        json!({"search":self.search,"pruned":pruned,"columns":columns})
    }
    pub fn export_state(&self) -> Value {
        let mut state = self.adhoc_state();
        if !self.active_presets.is_empty() {
            state["active_presets"] = json!(self.active_presets);
        }
        state
    }

    pub fn presets(&self) -> Vec<Value> {
        self.presets
            .iter()
            .map(|(name, state)| json!({"name":name,"state":state}))
            .collect()
    }
    pub fn active_presets(&self) -> Vec<String> {
        self.active_presets.clone()
    }
    pub fn set_presets(
        &mut self,
        presets: &[Value],
        renamed: &HashMap<String, String>,
    ) -> Result<Vec<String>, FilterError> {
        let mut table = IndexMap::new();
        for entry in presets {
            let entry = entry.as_object().ok_or_else(|| fail(PRESET_UNREADABLE))?;
            let name = entry.get("name").map(value_text).unwrap_or_default();
            let name = python_trim(&name);
            if name.is_empty() {
                return Err(fail(PRESET_NAME_EMPTY));
            }
            if table.contains_key(name) {
                return Err(fail(PRESET_NAME_TAKEN));
            }
            let state = entry
                .get("state")
                .filter(|value| value.is_object())
                .cloned()
                .unwrap_or_else(|| json!({}));
            table.insert(name.to_owned(), state);
        }
        self.presets = table;
        let mut dropped = vec![];
        let mut kept = vec![];
        for name in &self.active_presets {
            let next = renamed.get(name).cloned().unwrap_or_else(|| name.clone());
            if self.presets.contains_key(&next) && self.preset_status(&next).0 {
                kept.push(next);
            } else {
                dropped.push(next);
            }
        }
        self.active_presets = kept;
        Ok(dropped)
    }
    fn install_group(&self, state: &Value) -> Result<(ConditionGroup, Vec<String>), FilterError> {
        let mut scratch = Self::new(self.columns.clone(), self.kinds.clone());
        let (_, dropped) = scratch.apply_state(state)?;
        let cols = scratch
            .cols
            .into_iter()
            .filter(|(_, condition)| condition.active())
            .collect();
        Ok((
            ConditionGroup {
                cols,
                search: scratch.search,
                pruned: scratch.pruned,
            },
            dropped,
        ))
    }
    fn group(&self, name: &str) -> Result<ConditionGroup, FilterError> {
        let state = self
            .presets
            .get(name)
            .ok_or_else(|| fail(format!("저장한 필터를 찾을 수 없습니다: {name}")))?;
        self.install_group(state).map(|(group, _)| group)
    }
    pub fn preset_status(&self, name: &str) -> (bool, String) {
        let Some(state) = self.presets.get(name) else {
            return (false, format!("저장한 필터를 찾을 수 없습니다: {name}"));
        };
        if state.get("active_presets").is_some() {
            return (false, PRESET_UNREADABLE.into());
        }
        let Ok((group, dropped)) = self.install_group(state) else {
            return (false, PRESET_UNREADABLE.into());
        };
        let missing = dropped
            .iter()
            .filter(|item| !item.ends_with("(범위)"))
            .cloned()
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return (
                false,
                format!(
                    "이 필터의 열이 지금 데이터에 없습니다: {}",
                    missing.join(", ")
                ),
            );
        }
        if !dropped.is_empty() {
            let columns = dropped
                .iter()
                .map(|item| item.strip_suffix("(범위)").unwrap_or(item))
                .collect::<Vec<_>>();
            return (
                false,
                format!(
                    "이 필터의 범위 조건을 지금 데이터 열에 적용할 수 없습니다: {}",
                    columns.join(", ")
                ),
            );
        }
        if group.cols.is_empty() && group.search.is_empty() {
            return (false, PRESET_STATE_EMPTY.into());
        }
        (true, String::new())
    }
    pub fn activate_preset(&mut self, name: &str) -> Result<(), FilterError> {
        let (usable, reason) = self.preset_status(name);
        if !usable {
            return Err(fail(reason));
        }
        if !self.active_presets.iter().any(|active| active == name) {
            self.active_presets.push(name.into());
        }
        Ok(())
    }
    pub fn deactivate_preset(&mut self, name: &str) -> Result<(), FilterError> {
        if !self.presets.contains_key(name) {
            return Err(fail(format!("저장한 필터를 찾을 수 없습니다: {name}")));
        }
        self.active_presets.retain(|active| active != name);
        Ok(())
    }
    pub fn toggle_preset(&mut self, name: &str) -> Result<bool, FilterError> {
        if self.active_presets.iter().any(|active| active == name) {
            self.deactivate_preset(name)?;
            Ok(false)
        } else {
            self.activate_preset(name)?;
            Ok(true)
        }
    }
    pub fn normalize_preset_state(
        &self,
        state: &Value,
        allow_empty: bool,
    ) -> Result<Value, FilterError> {
        let raw = state.as_object().ok_or_else(|| fail(PRESET_UNREADABLE))?;
        if raw.contains_key("active_presets") {
            return Err(fail(PRESET_UNREADABLE));
        }
        let empty_columns = Map::new();
        let columns = raw
            .get("columns")
            .filter(|value| !value.is_null())
            .map(Value::as_object)
            .unwrap_or(Some(&empty_columns))
            .ok_or_else(|| fail(PRESET_UNREADABLE))?;
        let search = raw
            .get("search")
            .filter(|value| !value.is_null())
            .map(Value::as_str)
            .unwrap_or(Some(""))
            .ok_or_else(|| fail(PRESET_UNREADABLE))?;
        let pruned = raw
            .get("pruned")
            .filter(|value| !value.is_null())
            .map(Value::as_array)
            .unwrap_or(None);
        if raw
            .get("pruned")
            .is_some_and(|value| !value.is_null() && pruned.is_none())
        {
            return Err(fail(PRESET_UNREADABLE));
        }
        let missing = columns
            .keys()
            .filter(|name| !self.cols.contains_key(*name))
            .cloned()
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Err(in_column(
                format!(
                    "이 필터의 열이 지금 데이터에 없습니다: {}",
                    missing.join(", ")
                ),
                &missing[0],
            ));
        }
        let mut scratch = Self::new(self.columns.clone(), self.kinds.clone());
        for (column, raw_condition) in columns {
            let condition = raw_condition
                .as_object()
                .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
            if let Some(values) = condition.get("values").filter(|value| !value.is_null()) {
                let values = values
                    .as_array()
                    .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
                scratch.set_values(column, Some(values.iter().map(value_text).collect()))?;
            }
            let text = condition
                .get("text")
                .filter(|value| !value.is_null())
                .map(Value::as_str)
                .unwrap_or(Some(""))
                .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
            scratch.set_text(column, text)?;
            if let Some(range) = condition.get("range").filter(|value| !value.is_null()) {
                let range = range
                    .as_object()
                    .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
                let parsed = range_condition_from_payload(
                    range.get("first"),
                    range.get("second"),
                    range.get("joiner").and_then(Value::as_str),
                )
                .map_err(|message| in_column(message, column))?;
                scratch
                    .set_range(column, parsed)
                    .map_err(|error| in_column(error.message, column))?;
            }
        }
        scratch.set_search(search);
        if !scratch.search.is_empty()
            && let Some(pruned) = pruned
        {
            scratch.pruned = pruned
                .iter()
                .map(value_text)
                .filter(|name| scratch.cols.contains_key(name))
                .collect();
        }
        if !allow_empty && !scratch.has_adhoc() {
            return Err(fail(PRESET_STATE_EMPTY));
        }
        Ok(scratch.adhoc_state())
    }
    fn new_name(&self, name: &str) -> Result<String, FilterError> {
        let name = python_trim(name);
        if name.is_empty() {
            return Err(fail(PRESET_NAME_EMPTY));
        }
        if self.presets.contains_key(name) {
            return Err(fail(PRESET_NAME_TAKEN));
        }
        Ok(name.into())
    }
    pub fn name_state(&self, state: &Value) -> Result<String, FilterError> {
        let normalized = self.normalize_preset_state(state, true)?;
        let (group, _) = self.install_group(&normalized)?;
        let mut parts = vec![];
        for column in &self.columns {
            if let Some(condition) = group.cols.get(column) {
                parts.extend(short_condition(column, condition));
            }
        }
        if !group.search.is_empty() {
            parts.push(format!("검색 '{}'", group.search));
        }
        Ok(parts.join(" · "))
    }
    pub fn count_state(&self, state: &Value, records: &[Record]) -> Result<usize, FilterError> {
        let normalized = self.normalize_preset_state(state, true)?;
        let (group, _) = self.install_group(&normalized)?;
        Ok(self.group_rows(&group, records)?.len())
    }
    pub fn create_preset(
        &mut self,
        name: &str,
        state: &Value,
        from_adhoc: bool,
    ) -> Result<String, FilterError> {
        let saved = self.normalize_preset_state(state, false)?;
        let candidate = if python_trim(name).is_empty() {
            self.name_state(&saved)?
        } else {
            name.into()
        };
        let name = self.new_name(&candidate)?;
        self.presets.insert(name.clone(), saved);
        if from_adhoc {
            self.clear_adhoc();
        }
        self.active_presets.push(name.clone());
        Ok(name)
    }
    pub fn update_preset(
        &mut self,
        name: &str,
        new_name: &str,
        state: &Value,
    ) -> Result<String, FilterError> {
        if !self.presets.contains_key(name) {
            return Err(fail(format!("저장한 필터를 찾을 수 없습니다: {name}")));
        }
        let saved = self.normalize_preset_state(state, false)?;
        let candidate = if python_trim(new_name).is_empty() {
            self.name_state(&saved)?
        } else {
            python_trim(new_name).into()
        };
        let candidate = if candidate == name {
            candidate
        } else {
            self.new_name(&candidate)?
        };
        let mut replacement = IndexMap::new();
        for (key, value) in &self.presets {
            replacement.insert(
                if key == name {
                    candidate.clone()
                } else {
                    key.clone()
                },
                if key == name {
                    saved.clone()
                } else {
                    value.clone()
                },
            );
        }
        self.presets = replacement;
        for active in &mut self.active_presets {
            if active == name {
                *active = candidate.clone();
            }
        }
        Ok(candidate)
    }
    pub fn delete_preset(&mut self, name: &str) -> Result<(), FilterError> {
        if self.presets.shift_remove(name).is_none() {
            return Err(fail(format!("저장한 필터를 찾을 수 없습니다: {name}")));
        }
        self.active_presets.retain(|active| active != name);
        Ok(())
    }
    pub fn preset_columns(&self, name: &str) -> Result<HashSet<String>, FilterError> {
        let state = self
            .presets
            .get(name)
            .ok_or_else(|| fail(format!("저장한 필터를 찾을 수 없습니다: {name}")))?;
        let mut result = HashSet::new();
        if let Some(columns) = state.get("columns").and_then(Value::as_object) {
            for (column, condition) in columns {
                if condition.as_object().is_some_and(|condition| {
                    condition
                        .get("values")
                        .is_some_and(|value| !value.is_null())
                        || condition
                            .get("text")
                            .and_then(Value::as_str)
                            .is_some_and(|text| !python_trim(text).is_empty())
                        || condition.get("range").is_some_and(|value| !value.is_null())
                }) {
                    result.insert(column.clone());
                }
            }
        }
        Ok(result)
    }
    pub fn preset_dimension(&self, name: &str) -> Result<HashSet<String>, FilterError> {
        let mut result = self.preset_columns(name)?;
        let state = self.presets.get(name).expect("known preset");
        if state
            .get("search")
            .and_then(Value::as_str)
            .is_some_and(|search| !python_trim(search).is_empty())
        {
            result.insert(SEARCH_DIMENSION.into());
        }
        Ok(result)
    }
    fn grouped_names(&self, names: &[String]) -> Result<Vec<Vec<String>>, FilterError> {
        let mut groups: IndexMap<Vec<String>, Vec<String>> = IndexMap::new();
        for name in names {
            let mut key = self.preset_dimension(name)?.into_iter().collect::<Vec<_>>();
            key.sort();
            if key.is_empty() {
                key.push(format!("\0{name}"));
            }
            groups.entry(key).or_default().push(name.clone());
        }
        Ok(groups.into_values().collect())
    }
    pub fn preset_groups(&self) -> Result<Vec<Vec<String>>, FilterError> {
        self.grouped_names(&self.presets.keys().cloned().collect::<Vec<_>>())
    }
    pub fn active_preset_groups(&self) -> Result<Vec<Vec<String>>, FilterError> {
        self.grouped_names(&self.active_presets)
    }
    pub fn dimension_label(&self, name: &str) -> Result<String, FilterError> {
        let dimension = self.preset_dimension(name)?;
        let mut ordered = self
            .columns
            .iter()
            .filter(|column| dimension.contains(*column))
            .cloned()
            .collect::<Vec<_>>();
        let mut extra = dimension
            .iter()
            .filter(|column| {
                !self.cols.contains_key(*column) && column.as_str() != SEARCH_DIMENSION
            })
            .cloned()
            .collect::<Vec<_>>();
        extra.sort();
        ordered.extend(extra);
        if dimension.contains(SEARCH_DIMENSION) {
            ordered.push("검색".into());
        }
        Ok(ordered.join("·"))
    }
    pub fn dimension_key(&self, name: &str) -> Result<String, FilterError> {
        let dimension = self.preset_dimension(name)?;
        let mut parts = dimension
            .iter()
            .filter(|column| column.as_str() != SEARCH_DIMENSION)
            .cloned()
            .collect::<Vec<_>>();
        parts.sort();
        if dimension.contains(SEARCH_DIMENSION) {
            parts.push("검색".into());
        }
        Ok(parts.join("·"))
    }
    fn group_label(names: &[String]) -> String {
        format!(
            "필터 {}",
            names
                .iter()
                .map(|name| format!("'{name}'"))
                .collect::<Vec<_>>()
                .join(" 또는 ")
        )
    }
    pub fn column_constraints(&self, column: &str) -> Result<Vec<String>, FilterError> {
        self.require(column)?;
        let mut parts = vec![];
        for names in self.active_preset_groups()? {
            if self.preset_columns(&names[0])?.contains(column) {
                parts.push(Self::group_label(&names));
            }
        }
        parts.extend(describe_condition(column, &self.cols[column]));
        Ok(parts)
    }
    pub fn preset_description(
        &self,
        name: &str,
        records: &[Record],
    ) -> Result<String, FilterError> {
        let group = self.group(name)?;
        let mut parts = vec![];
        for column in &self.columns {
            if let Some(condition) = group.cols.get(column) {
                parts.extend(describe_condition(column, condition));
            }
        }
        if !group.search.is_empty() {
            let mut passing = Vec::new();
            for record in records {
                if self.conds_pass(&group.cols, record, None)? {
                    passing.push(record);
                }
            }
            parts.push(search_part(
                &group.search,
                &self.search_branches(&group.search, &group.pruned, &passing),
            ));
        }
        Ok(parts.join(" · "))
    }

    /// Install a transferred definition and name every condition that could not be installed.
    /// As in Python, callers install into a blank model when they need replacement semantics.
    pub fn apply_state(
        &mut self,
        state: &Value,
    ) -> Result<(Vec<String>, Vec<String>), FilterError> {
        let state = state.as_object().ok_or_else(|| fail(PRESET_UNREADABLE))?;
        let mut installed = vec![];
        let mut dropped = vec![];
        if let Some(columns) = state.get("columns").filter(|value| !value.is_null()) {
            let columns = columns.as_object().ok_or_else(|| fail(PRESET_UNREADABLE))?;
            for (column, raw) in columns {
                if !self.cols.contains_key(column) {
                    dropped.push(column.clone());
                    continue;
                }
                let raw = raw
                    .as_object()
                    .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
                let mut got_any = false;
                if let Some(values) = raw.get("values").filter(|value| !value.is_null()) {
                    let values = values
                        .as_array()
                        .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
                    self.set_values(column, Some(values.iter().map(value_text).collect()))?;
                    got_any = true;
                }
                if let Some(text) = raw
                    .get("text")
                    .and_then(Value::as_str)
                    .filter(|value| !value.is_empty())
                {
                    self.set_text(column, text)?;
                    got_any = true;
                }
                if let Some(range) = raw.get("range").filter(|value| !value.is_null()) {
                    let range = range
                        .as_object()
                        .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
                    let first = range
                        .get("first")
                        .ok_or_else(|| in_column(PRESET_UNREADABLE, column))?;
                    let second = range.get("second");
                    let parsed = range_condition_from_payload(
                        Some(first),
                        second,
                        range.get("joiner").and_then(Value::as_str),
                    )
                    .map_err(|message| in_column(message, column))?;
                    match self.set_range(column, parsed) {
                        Ok(()) => got_any = true,
                        Err(_) => dropped.push(format!("{column}(범위)")),
                    }
                }
                if got_any {
                    installed.push(column.clone());
                }
            }
        }
        let search = state.get("search").map(value_text).unwrap_or_default();
        let search = python_trim(&search);
        if !search.is_empty() {
            self.search = search.into();
            if let Some(pruned) = state.get("pruned").and_then(Value::as_array) {
                self.pruned = pruned
                    .iter()
                    .map(value_text)
                    .filter(|column| self.cols.contains_key(column))
                    .collect();
            }
        }
        if let Some(names) = state.get("active_presets").and_then(Value::as_array) {
            for name in names {
                let name = value_text(name);
                let label = format!("필터 '{name}'");
                if self.activate_preset(&name).is_err() {
                    dropped.push(label);
                } else {
                    installed.push(label);
                }
            }
        }
        Ok((installed, dropped))
    }

    fn conds_pass(
        &self,
        conds: &IndexMap<String, ColumnCondition>,
        record: &Record,
        except_values: Option<&str>,
    ) -> Result<bool, FilterError> {
        for (column, condition) in conds {
            if !condition.active() {
                continue;
            }
            let cell = cell_text(record, column);
            if condition
                .values
                .as_ref()
                .is_some_and(|values| !values.iter().any(|value| value == cell))
                && except_values != Some(column)
            {
                return Ok(false);
            }
            if !condition.text.is_empty() && !jamo_contains(cell, &condition.text) {
                return Ok(false);
            }
            if let Some(range) = &condition.range
                && !range_pass(self.kind(column)?, range, cell)?
            {
                return Ok(false);
            }
        }
        Ok(true)
    }
    pub fn col_pass(
        &self,
        record: &Record,
        except_values: Option<&str>,
    ) -> Result<bool, FilterError> {
        self.conds_pass(&self.cols, record, except_values)
    }
    fn search_branches(
        &self,
        search: &str,
        pruned: &HashSet<String>,
        passing: &[&Record],
    ) -> Vec<String> {
        self.columns
            .iter()
            .filter(|column| self.kinds.get(*column).map_or(KIND_TEXT, String::as_str) == KIND_TEXT)
            .filter(|column| !pruned.contains(*column))
            .filter(|column| {
                passing
                    .iter()
                    .any(|record| jamo_contains(cell_text(record, column), search))
            })
            .cloned()
            .collect()
    }
    fn group_rows(
        &self,
        group: &ConditionGroup,
        records: &[Record],
    ) -> Result<HashSet<usize>, FilterError> {
        let mut rows = vec![];
        for (index, record) in records.iter().enumerate() {
            if self.conds_pass(&group.cols, record, None)? {
                rows.push(index);
            }
        }
        if group.search.is_empty() {
            return Ok(rows.into_iter().collect());
        }
        let passing = rows
            .iter()
            .map(|index| &records[*index])
            .collect::<Vec<_>>();
        let branches = self.search_branches(&group.search, &group.pruned, &passing);
        Ok(rows
            .into_iter()
            .filter(|index| {
                branches
                    .iter()
                    .any(|branch| jamo_contains(cell_text(&records[*index], branch), &group.search))
            })
            .collect())
    }
    pub fn view<'a>(&'a self, records: &'a [Record]) -> Result<FilterView<'a>, FilterError> {
        FilterView::new(self, records)
    }
    pub fn visible_indices(&self, records: &[Record]) -> Result<Vec<usize>, FilterError> {
        self.view(records)?.visible_indices()
    }
    pub fn column_values(
        &self,
        column: &str,
        records: &[Record],
    ) -> Result<Vec<String>, FilterError> {
        self.view(records)?.column_values(column)
    }
    pub fn describe_parts(&self, records: &[Record]) -> Result<Vec<String>, FilterError> {
        Ok(self.view(records)?.describe_parts())
    }
    pub fn describe(&self, records: &[Record]) -> Result<String, FilterError> {
        Ok(self.view(records)?.describe())
    }
    pub fn group_branches(&self, records: &[Record]) -> Result<Vec<String>, FilterError> {
        Ok(self.view(records)?.branches.clone())
    }
    pub fn stratified_sample(
        &self,
        indices: &[usize],
        records: &[Record],
        limit: usize,
    ) -> Result<Vec<usize>, FilterError> {
        Ok(self.view(records)?.stratified_sample(indices, limit))
    }
    pub fn segments(
        &self,
        column: &str,
        value: &str,
        records: &[Record],
    ) -> Result<Vec<(String, bool)>, FilterError> {
        self.view(records)?.segments(column, value)
    }
}

fn value_text(value: &Value) -> String {
    match value {
        Value::String(value) => value.clone(),
        _ => python_repr(value),
    }
}
fn number_rational(value: ParsedNumber) -> Option<(BigInt, i32)> {
    match value {
        ParsedNumber::Integer(text) => BigInt::from_str(&text).ok().map(|number| (number, 0)),
        ParsedNumber::Float(number) if number.is_finite() => {
            let bits = number.to_bits();
            let exponent = ((bits >> 52) & 0x7ff) as i32;
            let mantissa = bits & ((1u64 << 52) - 1);
            let (mantissa, exponent) = if exponent == 0 {
                (mantissa, -1074)
            } else {
                (mantissa | (1u64 << 52), exponent - 1075)
            };
            let mut integer = BigInt::from(mantissa);
            if bits >> 63 == 1 {
                integer = -integer;
            }
            Some((integer, exponent))
        }
        _ => None,
    }
}
fn compare_number(left: ParsedNumber, right: ParsedNumber) -> Option<Ordering> {
    let (mut left, left_exp) = number_rational(left)?;
    let (mut right, right_exp) = number_rational(right)?;
    if left_exp > right_exp {
        left <<= (left_exp - right_exp) as usize;
    }
    if right_exp > left_exp {
        right <<= (right_exp - left_exp) as usize;
    }
    Some(left.cmp(&right))
}
fn compare_date(left: ParsedDateTime, right: ParsedDateTime, with_time: bool) -> Ordering {
    let left_date = (left.year, left.month, left.day);
    let right_date = (right.year, right.month, right.day);
    left_date.cmp(&right_date).then_with(|| {
        if with_time {
            (left.hour, left.minute).cmp(&(right.hour, right.minute))
        } else {
            Ordering::Equal
        }
    })
}
fn time_form() -> &'static Regex {
    static TIME: OnceLock<Regex> = OnceLock::new();
    TIME.get_or_init(|| Regex::new(r"\d{1,2}:\d{2}").expect("static time grammar"))
}
fn clause_pass(kind: &str, clause: &RangeClause, cell: &str) -> Result<bool, FilterError> {
    let compared = if kind == KIND_AMOUNT {
        let Some(cell) = parse_number(cell) else {
            return Ok(false);
        };
        let operand = parse_number(&clause.operand).ok_or_else(|| {
            fail(format!(
                "범위 값 {} 을(를) 해석할 수 없습니다",
                python_repr(&Value::String(clause.operand.clone()))
            ))
        })?;
        compare_number(cell, operand).ok_or_else(|| fail("범위 숫자를 비교할 수 없습니다"))?
    } else {
        let Some(cell) = parse_dt(cell) else {
            return Ok(false);
        };
        let operand = parse_dt(&clause.operand).ok_or_else(|| {
            fail(format!(
                "범위 값 {} 을(를) 해석할 수 없습니다",
                python_repr(&Value::String(clause.operand.clone()))
            ))
        })?;
        compare_date(cell, operand, time_form().is_match(&clause.operand))
    };
    Ok(match clause.op.as_str() {
        "eq" => compared == Ordering::Equal,
        "ne" => compared != Ordering::Equal,
        "gt" => compared == Ordering::Greater,
        "ge" => compared != Ordering::Less,
        "lt" => compared == Ordering::Less,
        "le" => compared != Ordering::Greater,
        _ => return Err(fail("알 수 없는 비교 연산자")),
    })
}
fn range_pass(kind: &str, condition: &RangeCondition, cell: &str) -> Result<bool, FilterError> {
    let first = clause_pass(kind, &condition.first, cell)?;
    let Some(second) = &condition.second else {
        return Ok(first);
    };
    let second = clause_pass(kind, second, cell)?;
    Ok(if condition.joiner == "and" {
        first && second
    } else {
        first || second
    })
}

fn value_label(value: &str) -> &str {
    if value.is_empty() { "(빈값)" } else { value }
}
fn op_label(op: &str) -> &str {
    match op {
        "eq" => "=",
        "ne" => "≠",
        "gt" => ">",
        "ge" => "≥",
        "lt" => "<",
        "le" => "≤",
        _ => "?",
    }
}
fn joiner_label(joiner: &str) -> &str {
    if joiner == "and" { "∧" } else { "∨" }
}
fn describe_condition(column: &str, condition: &ColumnCondition) -> Vec<String> {
    let mut parts = vec![];
    if let Some(values) = &condition.values {
        if values.len() == 1 {
            parts.push(format!("{column} = {}", value_label(&values[0])));
        } else {
            parts.push(format!(
                "{column} ∈ {{{}}}",
                values
                    .iter()
                    .map(|value| value_label(value))
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
    }
    if !condition.text.is_empty() {
        parts.push(format!("{column} 포함 '{}'", condition.text));
    }
    if let Some(range) = &condition.range {
        let mut text = format!(
            "{column} {} '{}'",
            op_label(&range.first.op),
            range.first.operand
        );
        if let Some(second) = &range.second {
            text.push_str(&format!(
                " {} {} '{}'",
                joiner_label(&range.joiner),
                op_label(&second.op),
                second.operand
            ));
        }
        parts.push(text);
    }
    parts
}
fn short_condition(column: &str, condition: &ColumnCondition) -> Vec<String> {
    let mut parts = vec![];
    if let Some(values) = &condition.values {
        let values = values
            .iter()
            .map(|value| value_label(value))
            .collect::<Vec<_>>();
        match values.len() {
            0 => parts.push(format!("{column} ∈ {{}}")),
            1 => parts.push(format!("{column} {}", values[0])),
            count => parts.push(format!("{column} {} 외 {}개", values[0], count - 1)),
        }
    }
    if !condition.text.is_empty() {
        parts.push(format!("{column} 포함 '{}'", condition.text));
    }
    if let Some(range) = &condition.range {
        if range.joiner == "and"
            && range.first.op == "ge"
            && range
                .second
                .as_ref()
                .is_some_and(|second| second.op == "lt")
        {
            let second = range.second.as_ref().expect("checked second");
            parts.push(format!(
                "{column} {}~{}",
                range.first.operand, second.operand
            ));
        } else {
            let mut text = format!(
                "{column} {} {}",
                op_label(&range.first.op),
                range.first.operand
            );
            if let Some(second) = &range.second {
                text.push_str(&format!(
                    " {} {} {}",
                    joiner_label(&range.joiner),
                    op_label(&second.op),
                    second.operand
                ));
            }
            parts.push(text);
        }
    }
    parts
}
fn search_part(search: &str, branches: &[String]) -> String {
    if branches.is_empty() {
        format!("검색 '{search}' (매치 없음)")
    } else {
        format!("({}) 포함 '{search}'", branches.join(" ∨ "))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdhocChip {
    pub column: String,
    pub text: String,
    pub parts: Vec<String>,
}

pub struct FilterView<'a> {
    model: &'a FilterModel,
    records: &'a [Record],
    preset_pass: Option<HashSet<usize>>,
    preset_groups: Vec<Vec<String>>,
    pub branches: Vec<String>,
}

impl<'a> FilterView<'a> {
    fn new(model: &'a FilterModel, records: &'a [Record]) -> Result<Self, FilterError> {
        let preset_groups = model.active_preset_groups()?;
        let mut preset_pass: Option<HashSet<usize>> = None;
        for names in &preset_groups {
            let mut union = HashSet::new();
            for name in names {
                union.extend(model.group_rows(&model.group(name)?, records)?);
            }
            preset_pass = Some(match preset_pass {
                None => union,
                Some(passing) => passing.intersection(&union).copied().collect(),
            });
        }
        let mut passing = vec![];
        for (index, record) in records.iter().enumerate() {
            if preset_pass.as_ref().is_none_or(|set| set.contains(&index))
                && model.col_pass(record, None)?
            {
                passing.push(record);
            }
        }
        let branches = if model.search.is_empty() {
            vec![]
        } else {
            model.search_branches(&model.search, &model.pruned, &passing)
        };
        Ok(Self {
            model,
            records,
            preset_pass,
            preset_groups,
            branches,
        })
    }
    fn preset_ok(&self, index: usize) -> bool {
        self.preset_pass
            .as_ref()
            .is_none_or(|passing| passing.contains(&index))
    }
    fn group_pass(&self, record: &Record) -> bool {
        if self.model.search.is_empty() {
            return true;
        }
        self.branches
            .iter()
            .any(|branch| jamo_contains(cell_text(record, branch), &self.model.search))
    }
    pub fn visible_indices(&self) -> Result<Vec<usize>, FilterError> {
        let mut visible = vec![];
        for (index, record) in self.records.iter().enumerate() {
            if self.preset_ok(index)
                && self.model.col_pass(record, None)?
                && self.group_pass(record)
            {
                visible.push(index);
            }
        }
        Ok(visible)
    }
    pub fn column_values(&self, column: &str) -> Result<Vec<String>, FilterError> {
        self.model.require(column)?;
        let mut values = vec![];
        let mut seen = HashSet::new();
        let mut has_empty = false;
        for (index, record) in self.records.iter().enumerate() {
            if !(self.preset_ok(index)
                && self.model.col_pass(record, Some(column))?
                && self.group_pass(record))
            {
                continue;
            }
            let value = cell_text(record, column);
            if value.is_empty() {
                has_empty = true;
            } else if seen.insert(value) {
                values.push(value.into());
            }
        }
        if has_empty {
            values.push(String::new());
        }
        Ok(values)
    }
    pub fn preset_parts(&self) -> Vec<String> {
        self.preset_groups
            .iter()
            .map(|names| FilterModel::group_label(names))
            .collect()
    }
    pub fn adhoc_chips(&self) -> Vec<AdhocChip> {
        let mut chips = vec![];
        for column in &self.model.columns {
            let parts = describe_condition(column, &self.model.cols[column]);
            if !parts.is_empty() {
                chips.push(AdhocChip {
                    column: column.clone(),
                    text: parts.join(" · "),
                    parts,
                });
            }
        }
        if !self.model.search.is_empty() {
            let part = search_part(&self.model.search, &self.branches);
            chips.push(AdhocChip {
                column: String::new(),
                text: part.clone(),
                parts: vec![part],
            });
        }
        chips
    }
    pub fn adhoc_parts(&self) -> Vec<String> {
        self.adhoc_chips()
            .into_iter()
            .flat_map(|chip| chip.parts)
            .collect()
    }
    pub fn describe_parts(&self) -> Vec<String> {
        let mut parts = self.preset_parts();
        parts.extend(self.adhoc_parts());
        parts
    }
    pub fn describe(&self) -> String {
        self.describe_parts().join(" · ")
    }
    pub fn stratified_sample(&self, indices: &[usize], limit: usize) -> Vec<usize> {
        if limit == 0 {
            return vec![];
        }
        if self.model.search.is_empty() || self.branches.is_empty() {
            return indices.iter().take(limit).copied().collect();
        }
        let mut picked = vec![];
        for branch in &self.branches {
            for &index in indices {
                if picked.contains(&index) || index >= self.records.len() {
                    continue;
                }
                if jamo_contains(cell_text(&self.records[index], branch), &self.model.search) {
                    picked.push(index);
                    break;
                }
            }
        }
        for &index in indices {
            if picked.len() >= limit {
                break;
            }
            if !picked.contains(&index) {
                picked.push(index);
            }
        }
        picked.sort_unstable();
        picked
    }
    pub fn segments(&self, column: &str, value: &str) -> Result<Vec<(String, bool)>, FilterError> {
        self.model.require(column)?;
        let mut terms = vec![];
        if !self.model.search.is_empty() && self.branches.iter().any(|branch| branch == column) {
            terms.push(self.model.search.as_str());
        }
        let column_text = &self.model.cols[column].text;
        if !column_text.is_empty() {
            terms.push(column_text);
        }
        for term in terms {
            if let Some((start, end)) = jamo_find(value, term) {
                let boundaries = value
                    .char_indices()
                    .map(|(index, _)| index)
                    .chain(std::iter::once(value.len()))
                    .collect::<Vec<_>>();
                let parts = [
                    (value[..boundaries[start]].to_owned(), false),
                    (value[boundaries[start]..boundaries[end]].to_owned(), true),
                    (value[boundaries[end]..].to_owned(), false),
                ];
                return Ok(parts
                    .into_iter()
                    .filter(|(text, _)| !text.is_empty())
                    .collect());
            }
        }
        Ok(if value.is_empty() {
            vec![]
        } else {
            vec![(value.into(), false)]
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::filter_primitives::sniff_column_kinds;

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
