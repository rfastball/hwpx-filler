//! Confirmation state and system re-suggestion of editor rows.

use super::{EditorMappingError, EditorMappingModel, fail};
use crate::mapping::{SUGGEST_THRESHOLD, suggest_mappings};
use crate::schema_drift::similarity;
use std::collections::HashSet;

impl EditorMappingModel {
    pub fn set_confirmed(
        &mut self,
        index: usize,
        confirmed: bool,
    ) -> Result<bool, EditorMappingError> {
        let row = self.row_mut(index)?;
        let confirmed_empty = confirmed && !row.confirmed && row.is_declared_empty();
        row.confirmed = confirmed;
        row.auto_confirmed_exact = false;
        row.contract_verdict = None;
        if !confirmed {
            row.touched = true
        }
        row.manual_unconfirmed = !confirmed;
        Ok(confirmed_empty)
    }
    pub fn unconfirm_all(&mut self) -> Vec<(usize, bool, bool, bool)> {
        let undo = self
            .rows
            .iter()
            .enumerate()
            .filter(|(_, row)| row.confirmed)
            .map(|(index, row)| {
                (
                    index,
                    row.touched,
                    row.auto_confirmed_exact,
                    row.manual_unconfirmed,
                )
            })
            .collect();
        for row in &mut self.rows {
            if row.confirmed {
                row.touched = true;
                row.manual_unconfirmed = true
            }
            row.confirmed = false;
            row.auto_confirmed_exact = false;
        }
        undo
    }
    pub fn restore_confirmed(&mut self, undo: &[(usize, bool, bool, bool)]) -> usize {
        let mut restored = 0;
        for (index, touched, exact, manual) in undo {
            if let Some(row) = self.rows.get_mut(*index) {
                row.confirmed = true;
                row.touched = *touched;
                row.auto_confirmed_exact = *exact;
                row.manual_unconfirmed = *manual;
                restored += 1;
            }
        }
        restored
    }
    pub fn confirm_suggested(&mut self) -> usize {
        let mut count = 0;
        for row in &mut self.rows {
            if row.is_system_owned() && row.has_content() {
                row.confirmed = true;
                count += 1
            }
        }
        count
    }
    pub fn resuggest_row(
        &mut self,
        index: usize,
        sources: &[String],
    ) -> Result<(), EditorMappingError> {
        let aliases = self.aliases.clone();
        let row = self.row_mut(index)?;
        if !row.is_system_owned() {
            return Ok(());
        }
        let proposed = suggest_mappings(
            std::slice::from_ref(&row.template_field),
            sources,
            &aliases,
            SUGGEST_THRESHOLD,
        )
        .into_iter()
        .next();
        if let Some(draft) = proposed {
            row.source = draft.source;
            let exact = row.template_field == row.source;
            row.suggestion_score = if exact {
                1.0
            } else {
                similarity(
                    &row.template_field,
                    aliases.get(&row.source).unwrap_or(&row.source),
                )
            };
            row.confirmed = exact && !row.manual_unconfirmed;
            row.auto_confirmed_exact = row.confirmed;
        } else {
            row.source.clear();
            row.suggestion_score = 0.0;
            row.confirmed = false;
            row.auto_confirmed_exact = false
        }
        Ok(())
    }
    pub fn revert_to_auto(&mut self, index: usize) -> Result<(), EditorMappingError> {
        if self.rows.get(index).is_some_and(|row| row.confirmed) {
            return Err(fail(
                "확정한 행은 되돌릴 수 없습니다. 확정을 먼저 해제하세요.",
            ));
        }
        self.row_mut(index)?.reset_to_system();
        Ok(())
    }
    pub fn resuggest_all(&mut self) -> Result<(usize, usize), EditorMappingError> {
        let targets = (0..self.rows.len())
            .filter(|index| !self.rows[*index].confirmed)
            .collect::<Vec<_>>();
        for index in &targets {
            self.row_mut(*index)?.reset_to_system();
            let sources = self.source_fields.clone();
            self.resuggest_row(*index, &sources)?
        }
        Ok((targets.len(), self.rows.len() - targets.len()))
    }
    pub fn apply_active_sources(
        &mut self,
        active: &[String],
        vocabulary: Option<&[String]>,
    ) -> Result<Vec<String>, EditorMappingError> {
        let active_set: HashSet<_> = active.iter().collect();
        let vocab = vocabulary.map(|names| names.iter().collect::<HashSet<_>>());
        for index in 0..self.rows.len() {
            if self.rows[index].is_system_owned() {
                self.resuggest_row(index, active)?
            }
        }
        let mut demoted = Vec::new();
        for row in &mut self.rows {
            if !row.is_system_owned()
                && !row.source.is_empty()
                && !active_set.contains(&row.source)
                && vocab.as_ref().is_none_or(|set| set.contains(&row.source))
            {
                let manual = row.manual_unconfirmed;
                row.reset_to_system();
                if manual {
                    row.manual_unconfirmed = true;
                    row.touched = true
                }
                demoted.push(row.template_field.clone());
            }
        }
        Ok(demoted)
    }
}
