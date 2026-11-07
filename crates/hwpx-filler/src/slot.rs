#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotOption {
    pub id: String,
    pub order: usize,
    pub label: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Slot {
    pub id: String,
    pub options: Vec<SlotOption>,
    pub label: Option<String>,
}
