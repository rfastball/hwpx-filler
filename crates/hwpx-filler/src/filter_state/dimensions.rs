//! Saved-preset dimensions: which columns a preset constrains and how groups are labelled.

use super::describe::{describe_condition, search_part};
use super::{FilterError, FilterModel, SEARCH_DIMENSION, fail};
use crate::data_source::Record;
use crate::structure_scan::python_trim;
use indexmap::IndexMap;
use serde_json::Value;
use std::collections::HashSet;

impl FilterModel {
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
    pub(super) fn group_label(names: &[String]) -> String {
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
}
