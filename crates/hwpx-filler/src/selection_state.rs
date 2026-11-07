//! Snapshot-local record selection in original source order.

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SelectionModel {
    selected: Vec<bool>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SelectionError(pub String);
impl std::fmt::Display for SelectionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for SelectionError {}
impl SelectionModel {
    pub fn new(count: usize, all_selected: bool) -> Self {
        Self {
            selected: vec![all_selected; count],
        }
    }
    pub fn len(&self) -> usize {
        self.selected.len()
    }
    pub fn is_empty(&self) -> bool {
        self.selected.is_empty()
    }
    pub fn set_all(&mut self) {
        self.selected.fill(true);
    }
    pub fn set_none(&mut self) {
        self.selected.fill(false);
    }
    fn position(&self, index: isize) -> Option<usize> {
        if index < 0 {
            self.selected.len().checked_sub(index.unsigned_abs())
        } else {
            usize::try_from(index)
                .ok()
                .filter(|at| *at < self.selected.len())
        }
    }
    pub fn toggle(&mut self, index: isize, value: Option<bool>) -> Result<(), SelectionError> {
        let at = self
            .position(index)
            .ok_or_else(|| SelectionError(format!("record index {index} out of range")))?;
        let chosen = &mut self.selected[at];
        *chosen = value.unwrap_or(!*chosen);
        Ok(())
    }
    pub fn is_selected(&self, index: isize) -> Result<bool, SelectionError> {
        self.position(index)
            .map(|at| self.selected[at])
            .ok_or_else(|| SelectionError(format!("record index {index} out of range")))
    }
    pub fn selected_indices(&self) -> Vec<usize> {
        self.selected
            .iter()
            .enumerate()
            .filter_map(|(index, selected)| selected.then_some(index))
            .collect()
    }
    pub fn selected_count(&self) -> usize {
        self.selected.iter().filter(|selected| **selected).count()
    }
    pub fn selected_records<T: Clone>(&self, records: &[T]) -> Result<Vec<T>, SelectionError> {
        self.selected_indices()
            .into_iter()
            .map(|index| {
                records
                    .get(index)
                    .cloned()
                    .ok_or_else(|| SelectionError(format!("record index {index} out of range")))
            })
            .collect()
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn selection_preserves_source_order_and_refuses_stale_indices() {
        let defaults = SelectionModel::new(3, true);
        assert_eq!(defaults.selected_indices(), vec![0, 1, 2]);
        assert_eq!(defaults.len(), 3);
        assert!(SelectionModel::new(0, true).is_empty());
        let mut selected = SelectionModel::new(3, false);
        selected.toggle(2, None).unwrap();
        selected.toggle(0, Some(true)).unwrap();
        assert!(selected.is_selected(-1).unwrap());
        assert_eq!(selected.selected_indices(), vec![0, 2]);
        assert_eq!(
            selected
                .selected_records(&["first", "middle", "last"])
                .unwrap(),
            vec!["first", "last"]
        );
        assert!(selected.selected_records(&["first"]).is_err());
        assert!(selected.toggle(3, None).is_err());
        selected.set_all();
        assert_eq!(selected.selected_count(), 3);
        selected.toggle(1, Some(false)).unwrap();
        assert!(!selected.is_selected(1).unwrap());
        selected.set_none();
        assert_eq!(selected.selected_count(), 0);
        assert!(
            selected
                .selected_records(&["first", "middle", "last"])
                .unwrap()
                .is_empty()
        );
    }
}
