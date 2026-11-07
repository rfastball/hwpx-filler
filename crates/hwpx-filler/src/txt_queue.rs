//! Session-local TXT review order and copy state. Records remain outside this model.

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxtQueue {
    selected: Vec<bool>,
    display_order: Vec<usize>,
    copied_order: Vec<usize>,
    current: Option<usize>,
}
impl TxtQueue {
    pub fn new(count: usize) -> Self {
        Self {
            selected: vec![true; count],
            display_order: (0..count).collect(),
            copied_order: Vec::new(),
            current: (count > 0).then_some(0),
        }
    }
    pub fn selected_count(&self) -> usize {
        self.selected.iter().filter(|value| **value).count()
    }
    pub fn copied_count(&self) -> usize {
        self.copied_order.len()
    }
    pub fn current(&self) -> Option<usize> {
        self.current
    }
    pub fn display_order(&self) -> &[usize] {
        &self.display_order
    }
    pub fn copied_tail(&self) -> &[usize] {
        &self.copied_order
    }
    pub fn is_copied(&self, index: usize) -> bool {
        self.copied_order.contains(&index)
    }
    pub fn uncopied(&self) -> Vec<usize> {
        self.display_order
            .iter()
            .copied()
            .filter(|index| !self.is_copied(*index))
            .collect()
    }
    pub fn is_complete(&self) -> bool {
        self.selected_count() > 0 && self.uncopied().is_empty()
    }
    pub fn select(&mut self, index: usize, selected: bool) {
        if let Some(value) = self.selected.get_mut(index) {
            *value = selected;
            self.reconcile();
        }
    }
    pub fn set_all(&mut self) {
        self.selected.fill(true);
        self.reconcile();
    }
    pub fn set_none(&mut self) {
        self.selected.fill(false);
        self.reconcile();
    }
    pub fn reconcile(&mut self) {
        self.copied_order
            .retain(|index| self.selected.get(*index) == Some(&true));
        self.display_order
            .retain(|index| self.selected.get(*index) == Some(&true));
        for index in 0..self.selected.len() {
            if self.selected[index] && !self.display_order.contains(&index) {
                self.display_order.push(index);
            }
        }
        self.normalize_current();
    }
    fn normalize_current(&mut self) {
        if self.display_order.is_empty() {
            self.current = None;
        } else if !self
            .current
            .is_some_and(|index| self.display_order.contains(&index))
        {
            self.current = self
                .uncopied()
                .first()
                .copied()
                .or_else(|| self.display_order.first().copied());
        }
    }
    pub fn set_current(&mut self, index: Option<usize>) {
        if index.is_none_or(|index| self.display_order.contains(&index)) {
            self.current = index;
        }
        self.normalize_current();
    }
    pub fn step(&mut self, delta: isize) {
        if self.display_order.is_empty() {
            return;
        }
        let Some(at) = self.current.and_then(|current| {
            self.display_order
                .iter()
                .position(|index| *index == current)
        }) else {
            self.normalize_current();
            return;
        };
        let next = at
            .saturating_add_signed(delta)
            .min(self.display_order.len() - 1);
        self.current = Some(self.display_order[next]);
    }
    /// Returns whether this row had already been copied; recopy moves only the copy-history tail.
    pub fn copy(&mut self, index: Option<usize>) -> bool {
        let Some(index) = index.or(self.current) else {
            return false;
        };
        if self.selected.get(index) != Some(&true) {
            return false;
        }
        let was = self.is_copied(index);
        self.copied_order.retain(|copied| *copied != index);
        self.copied_order.push(index);
        self.normalize_current();
        was
    }
    pub fn advance_to_next_uncopied(&mut self) {
        if let Some(index) = self.uncopied().first() {
            self.current = Some(*index);
        }
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::TxtQueue;
    #[test]
    fn fixed_display_order_survives_copy_recopy_and_selection_change() {
        let mut queue = TxtQueue::new(3);
        assert_eq!(queue.current(), Some(0));
        assert_eq!(queue.selected_count(), 3);
        assert_eq!(queue.uncopied(), [0, 1, 2]);
        assert!(!queue.copy(None));
        assert_eq!(queue.current(), Some(0));
        queue.step(-1);
        assert_eq!(queue.current(), Some(0));
        assert_eq!(queue.display_order(), &[0, 1, 2]);
        queue.advance_to_next_uncopied();
        assert_eq!(queue.current(), Some(1));
        queue.copy(None);
        queue.set_current(Some(0));
        assert!(queue.copy(None));
        assert_eq!(queue.copied_tail(), &[1, 0]);
        assert_eq!(queue.copied_count(), 2);
        assert_eq!(queue.display_order(), &[0, 1, 2]);
        queue.select(1, false);
        assert_eq!(queue.display_order(), &[0, 2]);
        queue.select(1, true);
        assert_eq!(queue.display_order(), &[0, 2, 1]);
        assert!(!queue.is_copied(1));
        queue.set_current(Some(2));
        queue.step(100);
        assert_eq!(queue.current(), Some(1));
        queue.step(isize::MIN);
        assert_eq!(queue.current(), Some(0));
        queue.step(1);
        assert_eq!(queue.current(), Some(2));
        queue.copy(Some(1));
        assert_eq!(queue.current(), Some(2));
        assert_eq!(queue.display_order(), &[0, 2, 1]);
        assert_eq!(queue.uncopied(), [2]);
        queue.set_current(Some(1));
        queue.advance_to_next_uncopied();
        assert_eq!(queue.current(), Some(2));
        queue.copy(None);
        assert!(queue.is_complete());
        queue.advance_to_next_uncopied();
        assert_eq!(queue.current(), Some(2));
        queue.select(2, false);
        assert_eq!(queue.current(), Some(0));
        assert!(!queue.is_copied(2));
        queue.select(2, true);
        assert_eq!(queue.display_order(), [0, 1, 2]);
        assert!(!queue.is_complete());
        assert_eq!(queue.uncopied(), [2]);
    }

    #[test]
    fn empty_invalid_and_batch_selection_preserve_membership_and_current_position() {
        let mut empty = TxtQueue::new(0);
        assert!(!empty.is_complete());
        assert!(!empty.copy(None));
        empty.step(1);
        empty.advance_to_next_uncopied();
        empty.select(0, true);
        empty.set_all();
        assert_eq!(empty.current(), None);
        assert!(empty.display_order().is_empty());

        let mut queue = TxtQueue::new(3);
        queue.set_none();
        assert_eq!(queue.current(), None);
        assert_eq!(queue.selected_count(), 0);
        assert!(queue.uncopied().is_empty());
        assert!(!queue.is_complete());
        assert!(!queue.copy(Some(1)));
        assert!(!queue.copy(Some(99)));
        assert_eq!(queue.copied_count(), 0);
        queue.select(99, true);
        assert!(queue.display_order().is_empty());
        queue.select(1, true);
        queue.set_current(Some(0));
        assert_eq!(queue.current(), Some(1));
        queue.select(0, true);
        assert_eq!(queue.display_order(), [1, 0]);
        queue.copy(None);
        queue.set_current(None);
        assert_eq!(queue.current(), Some(0));
        queue.copy(None);
        assert!(queue.is_complete());
        queue.set_none();
        assert!(queue.copied_tail().is_empty());
        assert_eq!(queue.current(), None);
        queue.select(2, true);
        queue.set_all();
        assert_eq!(queue.display_order(), [2, 0, 1]);
        queue.reconcile();
        assert_eq!(queue.display_order(), [2, 0, 1]);
        assert_eq!(queue.current(), Some(2));
    }
}
