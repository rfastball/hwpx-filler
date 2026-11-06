//! Saved filter definitions and data-zone filter operations.

use crate::dataset_registry::{DatasetPoolRegistry, PoolError};
use crate::job_data_session::{JobDataError, MountedData, fail};
use hwpx_filler::dataset_reference::{excel_identity, filters_for_sheet, pclm_identity};
use hwpx_filler::filter_primitives::range_condition_from_payload;
use hwpx_filler::filter_state::FilterModel;
use serde_json::{Value, json};
use std::collections::HashMap;

impl MountedData {
    pub fn seed_presets(&mut self, registry: &DatasetPoolRegistry) -> Result<(), JobDataError> {
        let key = if !self.pool_key.is_empty() {
            self.pool_key.clone()
        } else if self.path.is_empty() {
            String::new()
        } else {
            let identity = if self.kind == "pclm" {
                pclm_identity(&self.path, &self.sheet)
            } else {
                excel_identity(&self.path, Some(&self.sheet))
            };
            match registry.find_identity_raw(&identity) {
                Ok(Some((key, _))) => key,
                Ok(None) | Err(PoolError::Codec(_) | PoolError::Invalid(_)) => String::new(),
                Err(PoolError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                    String::new()
                }
                Err(error) => return Err(fail(error.to_string())),
            }
        };
        if key.is_empty() {
            self.preset_key.clear();
            return Ok(());
        }
        let presets = match registry.load(&key) {
            Ok(item) => match filters_for_sheet(&item, Some(&self.sheet)) {
                Ok(presets) => presets,
                Err(_) => {
                    self.preset_key.clear();
                    return Ok(());
                }
            },
            Err(PoolError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
                self.preset_key.clear();
                return Ok(());
            }
            Err(PoolError::Codec(_) | PoolError::Invalid(_)) => {
                self.preset_key.clear();
                return Ok(());
            }
            Err(error) => return Err(fail(error.to_string())),
        };
        let definitions = presets
            .iter()
            .map(|preset| preset.to_dict())
            .collect::<Vec<_>>();
        let Some(filter) = &mut self.filter else {
            return Err(fail("데이터를 먼저 선택하세요."));
        };
        if filter.set_presets(&definitions, &HashMap::new()).is_err() {
            self.preset_key.clear();
            return Ok(());
        }
        self.preset_key = key;
        Ok(())
    }
    fn preset_trial(&self) -> Result<FilterModel, JobDataError> {
        if self.preset_key.is_empty() {
            return Err(fail("필터는 등록 데이터에만 저장할 수 있습니다."));
        }
        Ok(self.zone_filter()?.clone())
    }
    fn commit_presets(
        &mut self,
        registry: &DatasetPoolRegistry,
        trial: FilterModel,
        renamed: HashMap<String, String>,
    ) -> Result<(), JobDataError> {
        let definitions = trial.presets();
        let committed = if self.range_draft.is_some() {
            self.filter
                .as_ref()
                .map(|filter| {
                    let mut copy = filter.clone();
                    copy.set_presets(&definitions, &renamed)
                        .map_err(|error| fail(error.message))?;
                    Ok(copy)
                })
                .transpose()?
        } else {
            None
        };
        registry
            .commands()
            .set_filters(&self.preset_key, &json!(definitions), Some(&self.sheet))
            .map_err(|error| fail(error.to_string()))?;
        if let Some(draft) = &mut self.range_draft {
            draft.range.filter = Some(trial);
            self.filter = committed;
        } else {
            self.filter = Some(trial);
        }
        Ok(())
    }
    pub fn create_filter_preset(
        &mut self,
        registry: &DatasetPoolRegistry,
        name: &str,
        state: &Value,
        from_adhoc: bool,
    ) -> Result<String, JobDataError> {
        let mut trial = self.preset_trial()?;
        let saved = trial
            .create_preset(name, state, from_adhoc)
            .map_err(|error| fail(error.message))?;
        self.commit_presets(registry, trial, HashMap::new())?;
        Ok(saved)
    }
    pub fn update_filter_preset(
        &mut self,
        registry: &DatasetPoolRegistry,
        name: &str,
        new_name: &str,
        state: &Value,
    ) -> Result<String, JobDataError> {
        let mut trial = self.preset_trial()?;
        let saved = trial
            .update_preset(name, new_name, state)
            .map_err(|error| fail(error.message))?;
        self.commit_presets(
            registry,
            trial,
            HashMap::from([(name.into(), saved.clone())]),
        )?;
        Ok(saved)
    }
    pub fn delete_filter_preset(
        &mut self,
        registry: &DatasetPoolRegistry,
        name: &str,
    ) -> Result<(), JobDataError> {
        let mut trial = self.preset_trial()?;
        trial
            .delete_preset(name)
            .map_err(|error| fail(error.message))?;
        self.commit_presets(registry, trial, HashMap::new())
    }
    pub fn filter_view(&self) -> Result<(Vec<usize>, String), JobDataError> {
        let view = self
            .zone_filter()?
            .view(&self.records)
            .map_err(|error| fail(error.message))?;
        Ok((
            view.visible_indices()
                .map_err(|error| fail(error.message))?,
            view.describe(),
        ))
    }
    pub fn filter_panel(&self, column: &str) -> Result<Value, JobDataError> {
        let filter = self.zone_filter()?;
        let state = filter
            .column_state(column)
            .map_err(|error| fail(error.message))?;
        let kind = filter.kind(column).map_err(|error| fail(error.message))?;
        let options = filter
            .view(&self.records)
            .map_err(|error| fail(error.message))?
            .column_values(column)
            .map_err(|error| fail(error.message))?;
        Ok(json!({
            "column":column,"kind":kind,"text":state["text"],
            "checked":state["values"],"options":options,"range":state["range"],
            "can_hide":self.range_draft.is_none(),
        }))
    }
    pub fn set_filter_search(&mut self, text: &str) -> Result<(), JobDataError> {
        self.zone_filter_mut()?.set_search(text);
        Ok(())
    }
    pub fn set_filter_text(&mut self, column: &str, text: &str) -> Result<(), JobDataError> {
        self.zone_filter_mut()?
            .set_text(column, text)
            .map_err(|error| fail(error.message))
    }
    pub fn set_filter_values(
        &mut self,
        column: &str,
        values: Option<Vec<String>>,
    ) -> Result<(), JobDataError> {
        self.zone_filter_mut()?
            .set_values(column, values)
            .map_err(|error| fail(error.message))
    }
    /// The range builder's refusal is returned inline beside its input.
    pub fn set_filter_range(
        &mut self,
        column: &str,
        first: Option<&Value>,
        second: Option<&Value>,
        joiner: Option<&str>,
    ) -> Result<Value, JobDataError> {
        let parsed = match range_condition_from_payload(first, second, joiner) {
            Ok(parsed) => parsed,
            Err(message) => return Ok(json!({"ok":false,"error":message})),
        };
        match self.zone_filter_mut()?.set_range(column, parsed) {
            Ok(()) => Ok(json!({"ok":true})),
            Err(error) => Ok(json!({"ok":false,"error":error.message})),
        }
    }
    pub fn prune_filter(&mut self, column: &str) -> Result<(), JobDataError> {
        let records = &self.records;
        let filter = self
            .range_draft
            .as_mut()
            .map_or(self.filter.as_mut(), |draft| draft.range.filter.as_mut())
            .ok_or_else(|| fail("데이터를 먼저 선택하세요."))?;
        filter
            .prune_branch(column, records)
            .map_err(|error| fail(error.message))
    }
    pub fn clear_filter(&mut self) -> Result<(), JobDataError> {
        self.zone_filter_mut()?.clear();
        Ok(())
    }
    pub fn clear_filter_column(&mut self, column: &str) -> Result<(), JobDataError> {
        self.zone_filter_mut()?
            .clear_column(column)
            .map_err(|error| fail(error.message))
    }
    pub fn count_filter_state(&self, state: &Value) -> Result<Value, JobDataError> {
        let filter = self.zone_filter()?;
        let count = filter
            .count_state(state, &self.records)
            .map_err(|error| fail(error.message))?;
        let summary = filter
            .name_state(state)
            .map_err(|error| fail(error.message))?;
        Ok(json!({"ok":true,"count":count,"total":self.records.len(),"summary":summary}))
    }
    pub fn reapply_available(&self) -> bool {
        self.last_filter.as_ref().is_some_and(|slot| {
            !self.data_key.is_empty()
                && slot.source_key == self.data_key
                && self.zone_filter().is_ok_and(|filter| !filter.is_active())
        })
    }
    /// Restores the previous definition only on the same source and into a blank filter.
    pub fn reapply_filter(&mut self) -> Result<Value, JobDataError> {
        let current = self.zone_filter()?;
        if current.is_active() {
            return Err(fail("필터를 지운 뒤에 재적용할 수 있습니다."));
        }
        if !self.reapply_available() {
            return Err(fail("재적용할 직전 필터가 없습니다."));
        }
        let state = self
            .last_filter
            .as_ref()
            .expect("availability checked")
            .state
            .clone();
        let mut probe = current.blank_copy();
        let (installed, mut dropped) = probe
            .apply_state(&state)
            .map_err(|error| fail(error.message))?;
        if !probe.is_active() {
            return Ok(json!({
                "ok":false,
                "error":format!("직전 필터의 조건이 현재 데이터 열에 하나도 남지 않아 재적용하지 못했습니다: {}", dropped.join(", ")),
            }));
        }
        if !probe.search_text().is_empty()
            && probe
                .view(&self.records)
                .map_err(|error| fail(error.message))?
                .branches
                .is_empty()
        {
            let mut unpruned = current.blank_copy();
            let mut state_unpruned = state;
            state_unpruned["pruned"] = json!([]);
            unpruned
                .apply_state(&state_unpruned)
                .map_err(|error| fail(error.message))?;
            if !unpruned
                .view(&self.records)
                .map_err(|error| fail(error.message))?
                .branches
                .is_empty()
            {
                probe = unpruned;
                dropped.push("(검색 일부 조건은 열이 사라져 복원하지 못했습니다)".into());
            }
        }
        if let Some(draft) = &mut self.range_draft {
            draft.range.filter = Some(probe);
        } else {
            self.filter = Some(probe);
        }
        Ok(json!({"ok":true,"installed":installed,"dropped":dropped}))
    }
}
