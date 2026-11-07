//! Mapping profiles in and out of the editor, and data-contract confirmation of carried rows.

use super::{EditorMappingError, EditorMappingModel, EditorRow, fail};
use crate::data_contract::{DataContract, binding_fingerprint};
use crate::data_contract_check::{contract_target, judge_job_binding};
use crate::mapping::MappingProfile;
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};

impl EditorMappingModel {
    pub fn to_profile(&self, name: &str) -> Result<MappingProfile, EditorMappingError> {
        let rows = self
            .rows
            .iter()
            .filter(|row| row.confirmed)
            .map(EditorRow::to_mapping)
            .collect::<Result<Vec<_>, _>>()?;
        MappingProfile::new(name, rows, Map::new()).map_err(|error| fail(error.to_string()))
    }
    pub fn live_profile(&self, name: &str) -> Result<MappingProfile, EditorMappingError> {
        let rows = self
            .rows
            .iter()
            .filter(|row| row.has_content())
            .map(EditorRow::to_mapping)
            .collect::<Result<Vec<_>, _>>()?;
        MappingProfile::new(name, rows, Map::new()).map_err(|error| fail(error.to_string()))
    }
    pub fn carry_profile(&self, name: &str) -> Result<MappingProfile, EditorMappingError> {
        let rows = self
            .rows
            .iter()
            .filter(|row| {
                !row.is_system_owned()
                    && (row.confirmed || row.has_content())
                    && !row.auto_confirmed_exact
            })
            .map(EditorRow::to_mapping)
            .collect::<Result<Vec<_>, _>>()?;
        MappingProfile::new(name, rows, Map::new()).map_err(|error| fail(error.to_string()))
    }
    pub fn apply_profile(
        &mut self,
        profile: &MappingProfile,
        require_source: bool,
        confirm: bool,
    ) -> usize {
        let available: HashSet<_> = self.source_fields.iter().collect();
        let by_field: HashMap<_, _> = profile
            .mappings
            .iter()
            .map(|item| (&item.template_field, item))
            .collect();
        let mut applied = 0;
        for row in &mut self.rows {
            let Some(mapping) = by_field.get(&row.template_field) else {
                continue;
            };
            row.source = mapping.source.clone();
            row.field_type = mapping.field_type.clone();
            row.constant = mapping.constant.clone();
            row.fmt = mapping.fmt.clone();
            row.slice = mapping.slice.clone();
            row.touched = true;
            row.auto_confirmed_exact = false;
            row.manual_unconfirmed = false;
            let missing =
                require_source && !row.source.is_empty() && !available.contains(&row.source);
            row.confirmed = confirm && !missing;
            if !missing {
                applied += 1
            }
        }
        applied
    }
    pub fn apply_data_contract(
        &mut self,
        contract: &DataContract,
        saved: &MappingProfile,
        records: &[Map<String, Value>],
    ) -> usize {
        let mut confirmed = 0;
        for row in &mut self.rows {
            if !row.touched || row.manual_unconfirmed {
                continue;
            }
            let Ok(mapping) = row.to_mapping() else {
                continue;
            };
            let verdict =
                judge_job_binding(contract, saved, &mapping, &self.source_fields, records);
            if verdict.as_ref().is_some_and(|verdict| verdict.passed) {
                row.confirmed = true;
                confirmed += 1
            }
            row.contract_verdict = verdict;
        }
        confirmed
    }
    pub fn reset_stakes(
        &self,
        contract: Option<&DataContract>,
        saved: Option<&MappingProfile>,
        rejudge: bool,
    ) -> usize {
        let carried = self
            .rows
            .iter()
            .filter(|row| {
                !row.is_system_owned()
                    && (row.confirmed || row.has_content())
                    && !row.auto_confirmed_exact
            })
            .collect::<Vec<_>>();
        let (Some(contract), Some(saved)) = (contract, saved) else {
            return carried.len();
        };
        if !rejudge {
            return carried.len();
        }
        let rejudged: HashSet<_> = self
            .rows
            .iter()
            .filter(|row| !row.manual_unconfirmed)
            .filter_map(|row| {
                let mapping = row.to_mapping().ok()?;
                if contract_target(&mapping) {
                    let entry = contract.entry_for(&mapping.template_field)?;
                    (entry.binding == binding_fingerprint(&mapping))
                        .then_some(mapping.template_field)
                } else {
                    saved
                        .mappings
                        .iter()
                        .find(|old| old.template_field == mapping.template_field)
                        .filter(|old| binding_fingerprint(old) == binding_fingerprint(&mapping))
                        .map(|_| mapping.template_field)
                }
            })
            .collect();
        carried
            .iter()
            .filter(|row| !rejudged.contains(&row.template_field))
            .count()
    }
}
