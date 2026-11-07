//! Snapshot-local committed selection/filter/order and isolated edit draft.

use crate::filter_state::{FilterError, FilterModel};
use crate::job::sorted_json;
use crate::selection_state::SelectionModel;
use serde_json::json;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordRange {
    pub selection: SelectionModel,
    pub filter: Option<FilterModel>,
    pub view_order: String,
}
impl RecordRange {
    /// Clone declared filter state through its transfer codec, without copying view caches.
    pub fn copy(&self) -> Result<Self, FilterError> {
        Ok(Self {
            selection: self.selection.clone(),
            filter: self
                .filter
                .as_ref()
                .map(FilterModel::clone_state)
                .transpose()?,
            view_order: self.view_order.clone(),
        })
    }
    pub fn fingerprint(&self) -> String {
        sorted_json(&json!({
            "selected": self.selection.selected_indices(),
            "filter": self.filter.as_ref().map(FilterModel::export_state),
            "order": self.view_order,
        }))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordRangeDraft {
    pub range: RecordRange,
    pub snapshot_generation: u64,
    pub base_fingerprint: String,
    pub selected_only: bool,
}
impl RecordRangeDraft {
    pub fn is_dirty(&self) -> bool {
        self.range.fingerprint() != self.base_fingerprint
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn draft_isolated_from_committed_selection_filter_and_order() {
        let mut selection = SelectionModel::new(3, false);
        selection.toggle(1, Some(true)).unwrap();
        let mut filter = FilterModel::new(vec!["name".into()], HashMap::new());
        filter.set_text("name", "행복").unwrap();
        let committed = RecordRange {
            selection,
            filter: Some(filter),
            view_order: "sourceDesc".into(),
        };
        let range = committed.copy().unwrap();
        let mut draft = RecordRangeDraft {
            base_fingerprint: range.fingerprint(),
            range,
            snapshot_generation: 7,
            selected_only: false,
        };
        assert!(!draft.is_dirty());
        draft.range.selection.toggle(2, Some(true)).unwrap();
        assert!(draft.is_dirty());
        assert_eq!(committed.selection.selected_indices(), vec![1]);
        let mut order_only = committed.copy().unwrap();
        order_only.view_order = "sourceAsc".into();
        assert_ne!(order_only.fingerprint(), committed.fingerprint());
    }
}
