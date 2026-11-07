//! Saved-preset registry: install, activate, normalize, name and edit saved filters.

use super::describe::short_condition;
use super::{
    ConditionGroup, FilterError, FilterModel, PRESET_NAME_EMPTY, PRESET_NAME_TAKEN,
    PRESET_STATE_EMPTY, fail, in_column, value_text,
};
use crate::data_source::Record;
use crate::filter_primitives::{PRESET_UNREADABLE, range_condition_from_payload};
use crate::structure_scan::python_trim;
use indexmap::IndexMap;
use serde_json::{Map, Value, json};
use std::collections::HashMap;

impl FilterModel {
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
    pub(super) fn install_group(
        &self,
        state: &Value,
    ) -> Result<(ConditionGroup, Vec<String>), FilterError> {
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
    pub(super) fn group(&self, name: &str) -> Result<ConditionGroup, FilterError> {
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
            normalize_column(&mut scratch, column, raw_condition)?;
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
}

/// Validate one saved column condition and install it into the scratch model.
fn normalize_column(
    scratch: &mut FilterModel,
    column: &str,
    raw_condition: &Value,
) -> Result<(), FilterError> {
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
    Ok(())
}
