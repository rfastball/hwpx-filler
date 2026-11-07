//! Filter view: one evaluated pass of the model over records, and the model's view delegates.

use super::describe::{describe_condition, search_part};
use super::{FilterError, FilterModel};
use crate::data_source::Record;
use crate::filter_primitives::cell_text;
use crate::jamo::{jamo_contains, jamo_find};
use std::collections::HashSet;

impl FilterModel {
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
    /// The first not-yet-picked row of `indices` matching the search in each branch, in branch order.
    fn branch_representatives(&self, indices: &[usize]) -> Vec<usize> {
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
        picked
    }
    pub fn stratified_sample(&self, indices: &[usize], limit: usize) -> Vec<usize> {
        if limit == 0 {
            return vec![];
        }
        if self.model.search.is_empty() || self.branches.is_empty() {
            return indices.iter().take(limit).copied().collect();
        }
        let mut picked = self.branch_representatives(indices);
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
