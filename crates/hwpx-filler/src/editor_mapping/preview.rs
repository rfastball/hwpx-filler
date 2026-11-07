//! Read-only projections of the editor rows: counts, previews and unused-column suggestions.

use super::{EditorMappingError, EditorMappingModel, fail};
use crate::mapping::SUGGEST_THRESHOLD;
use crate::schema_drift::similarity;
use chrono::NaiveDateTime;
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};

impl EditorMappingModel {
    pub fn declared_empty_fields(&self) -> Vec<String> {
        self.rows
            .iter()
            .filter(|row| row.confirmed && row.is_declared_empty())
            .map(|row| row.template_field.clone())
            .collect()
    }
    pub fn emits_any_value(&self) -> bool {
        self.rows
            .iter()
            .any(|row| row.confirmed && row.has_content())
    }
    pub fn counts(&self) -> (usize, usize, usize, usize) {
        let suggested = self
            .rows
            .iter()
            .filter(|row| row.status() == "suggested")
            .count();
        let needs = self
            .rows
            .iter()
            .filter(|row| matches!(row.status(), "edited" | "needs_source"))
            .count();
        let constant = self
            .rows
            .iter()
            .filter(|row| row.field_type == "const")
            .count();
        let confirmed = self.rows.iter().filter(|row| row.confirmed).count();
        (suggested, needs, constant, confirmed)
    }
    pub fn unused_source_fields(&self) -> Vec<String> {
        let used: HashSet<_> = self
            .rows
            .iter()
            .filter(|row| !row.source.is_empty())
            .map(|row| row.source.as_str())
            .collect();
        self.source_fields
            .iter()
            .filter(|source| !used.contains(source.as_str()))
            .cloned()
            .collect()
    }
    pub fn preview(
        &self,
        record: &Map<String, Value>,
        now: Option<NaiveDateTime>,
    ) -> Result<Map<String, Value>, EditorMappingError> {
        self.rows
            .iter()
            .map(|row| {
                let value = row
                    .to_mapping()?
                    .value_for(record, now)
                    .map_err(|error| fail(error.to_string()))?;
                Ok((row.template_field.clone(), Value::String(value)))
            })
            .collect()
    }
    pub fn preview_empties(
        &self,
        record: &Map<String, Value>,
        now: Option<NaiveDateTime>,
    ) -> Result<Vec<String>, EditorMappingError> {
        let mut out = Vec::new();
        for row in &self.rows {
            if row.has_content()
                && row
                    .to_mapping()?
                    .value_for(record, now)
                    .map_err(|error| fail(error.to_string()))?
                    .is_empty()
            {
                out.push(row.template_field.clone())
            }
        }
        Ok(out)
    }
    pub fn preview_counts(
        &self,
        record: &Map<String, Value>,
        now: Option<NaiveDateTime>,
    ) -> Result<(usize, usize, usize), EditorMappingError> {
        let empty = self.preview_empties(record, now)?.len();
        let content = self.rows.iter().filter(|row| row.has_content()).count();
        Ok((content - empty, empty, self.rows.len() - content))
    }
    pub fn name_token_values(
        &self,
        record: &Map<String, Value>,
        now: Option<NaiveDateTime>,
    ) -> Map<String, Value> {
        self.rows
            .iter()
            .filter(|row| row.has_content())
            .map(|row| {
                let value = row
                    .to_mapping()
                    .and_then(|mapping| {
                        mapping
                            .value_for(record, now)
                            .map_err(|error| fail(error.to_string()))
                    })
                    .unwrap_or_default();
                (row.template_field.clone(), Value::String(value))
            })
            .collect()
    }
    pub fn suggestions(&self) -> HashMap<String, String> {
        let used: HashSet<_> = self
            .rows
            .iter()
            .filter(|row| !row.source.is_empty())
            .map(|row| row.source.as_str())
            .collect();
        let mut out = HashMap::new();
        for row in &self.rows {
            if !row.source.is_empty() {
                continue;
            }
            let mut best = None;
            let mut score = 0.0;
            for column in &self.source_fields {
                if used.contains(column.as_str()) {
                    continue;
                }
                let current = similarity(
                    &row.template_field,
                    self.aliases.get(column).unwrap_or(column),
                );
                if current > score {
                    best = Some(column);
                    score = current
                }
            }
            if score >= SUGGEST_THRESHOLD
                && let Some(column) = best
            {
                out.insert(row.template_field.clone(), column.clone());
            }
        }
        out
    }
}
