//! Filter-state transfer: export the current definition and install a transferred one.

use super::{FilterError, FilterModel, fail, in_column, value_text};
use crate::filter_primitives::{PRESET_UNREADABLE, range_condition_from_payload};
use crate::structure_scan::python_trim;
use serde_json::{Map, Value, json};

impl FilterModel {
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
    /// Install one known column's transferred condition; a range the column cannot hold is
    /// named in `dropped`. Returns whether any part of the condition was installed.
    fn install_column(
        &mut self,
        column: &str,
        raw: &Value,
        dropped: &mut Vec<String>,
    ) -> Result<bool, FilterError> {
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
        Ok(got_any)
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
                if self.install_column(column, raw, &mut dropped)? {
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
}
