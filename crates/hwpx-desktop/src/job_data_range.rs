//! Draft and committed row ranges, including edits from older mounted snapshots.

use crate::job_data_session::{JobDataError, MountedData, fail};
use hwpx_filler::filter_state::FilterModel;
use hwpx_filler::record_range::{RecordRange, RecordRangeDraft};
use hwpx_filler::selection_state::SelectionModel;
use serde_json::{Value, json};

impl MountedData {
    pub fn committed_range(&self) -> RecordRange {
        RecordRange {
            selection: self.selection.clone(),
            filter: self.filter.clone(),
            view_order: self.view_order.clone(),
        }
    }
    pub fn open_range_draft(&mut self) -> Result<(), JobDataError> {
        if self.source_kind.is_empty() || self.records.is_empty() {
            return Err(fail("데이터를 먼저 선택하세요."));
        }
        if self.range_draft.is_none() {
            let range = self
                .committed_range()
                .copy()
                .map_err(|error| fail(error.message))?;
            self.range_draft = Some(RecordRangeDraft {
                base_fingerprint: range.fingerprint(),
                range,
                snapshot_generation: self.snapshot_generation,
                selected_only: false,
            });
            self.zone_epoch += 1;
        }
        Ok(())
    }
    pub fn apply_range_draft(&mut self) -> Result<(), JobDataError> {
        let draft = self
            .range_draft
            .as_ref()
            .ok_or_else(|| fail("범위 편집기가 열려 있지 않습니다."))?;
        if draft.snapshot_generation != self.snapshot_generation {
            return Err(fail(
                "데이터가 바뀌어 편집하던 범위를 적용할 수 없습니다. 지금 데이터에서 다시 고르세요.",
            ));
        }
        let draft = self.range_draft.take().expect("checked open draft");
        self.selection = draft.range.selection;
        self.filter = draft.range.filter;
        self.view_order = draft.range.view_order;
        self.zone_epoch += 1;
        Ok(())
    }
    pub fn cancel_range_draft(&mut self) {
        self.range_draft = None;
        self.zone_epoch += 1;
    }
    pub fn range_draft_payload(&self) -> Value {
        match &self.range_draft {
            None => {
                json!({"open":false,"dirty":false,"sel_count":0,"selected_only":false,"view_order":self.view_order})
            }
            Some(draft) => {
                json!({"open":true,"dirty":draft.is_dirty(),"sel_count":draft.range.selection.selected_count(),"selected_only":draft.selected_only,"view_order":draft.range.view_order})
            }
        }
    }
    /// An edit from an older mounted-data or range-draft world cannot mutate this one.
    pub fn is_stale_edit(&self, action: &str, payload: &Value) -> bool {
        if !matches!(
            action,
            "toggle_record"
                | "select_range"
                | "set_all"
                | "set_none"
                | "filter_search"
                | "filter_col_text"
                | "filter_col_values"
                | "filter_col_range"
                | "filter_prune"
                | "filter_clear"
                | "filter_clear_col"
                | "filter_reapply"
                | "create_filter_preset"
                | "update_filter_preset"
                | "toggle_filter_preset"
                | "delete_filter_preset"
                | "hide_column"
                | "unhide_columns"
                | "set_view_order"
        ) {
            return false;
        }
        let Some(value) = payload.get("epoch") else {
            return false;
        };
        let epoch = match value {
            Value::Bool(value) => Some(u64::from(*value)),
            Value::Number(value) => value.as_u64().or_else(|| {
                value
                    .as_f64()
                    .filter(|number| number.is_finite() && number.trunc() >= 0.0)
                    .and_then(|number| u64::try_from(number.trunc() as i128).ok())
            }),
            Value::String(value) => hwpx_filler::structure_scan::python_trim(value)
                .parse::<u64>()
                .ok(),
            _ => None,
        };
        epoch != Some(self.zone_epoch)
    }
    pub fn set_selected_only(&mut self, value: bool) -> Result<(), JobDataError> {
        let draft = self
            .range_draft
            .as_mut()
            .ok_or_else(|| fail("범위 편집기가 열려 있지 않습니다."))?;
        draft.selected_only = value;
        Ok(())
    }
    pub fn set_view_order(&mut self, value: &str) -> Result<(), JobDataError> {
        if !matches!(value, "sourceDesc" | "sourceAsc") {
            return Err(fail(format!(
                "알 수 없는 표시순서: {}",
                hwpx_filler::text_render::python_repr(&Value::String(value.into()))
            )));
        }
        if let Some(draft) = &mut self.range_draft {
            draft.range.view_order = value.into();
        } else {
            self.view_order = value.into();
        }
        Ok(())
    }
    pub(crate) fn zone_selection_mut(&mut self) -> &mut SelectionModel {
        match &mut self.range_draft {
            Some(draft) => &mut draft.range.selection,
            None => &mut self.selection,
        }
    }
    pub(crate) fn zone_filter(&self) -> Result<&FilterModel, JobDataError> {
        self.range_draft
            .as_ref()
            .map_or(self.filter.as_ref(), |draft| draft.range.filter.as_ref())
            .ok_or_else(|| fail("데이터를 먼저 선택하세요."))
    }
    pub fn zone_filter_mut(&mut self) -> Result<&mut FilterModel, JobDataError> {
        self.range_draft
            .as_mut()
            .map_or(self.filter.as_mut(), |draft| draft.range.filter.as_mut())
            .ok_or_else(|| fail("데이터를 먼저 선택하세요."))
    }
    pub fn zone_indices(&self) -> Vec<usize> {
        let (selection, order) = match &self.range_draft {
            Some(draft) => (&draft.range.selection, draft.range.view_order.as_str()),
            None => (&self.selection, self.view_order.as_str()),
        };
        let mut indices = selection.selected_indices();
        if order == "sourceDesc" {
            indices.reverse();
        }
        indices
    }
    pub fn zone_selected_count(&self) -> usize {
        self.range_draft
            .as_ref()
            .map_or(self.selection.selected_count(), |draft| {
                draft.range.selection.selected_count()
            })
    }
}
