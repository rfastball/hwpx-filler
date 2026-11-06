//! Deterministic HWPX text projection and explicit unknown-structure ledger.

use serde::Serialize;
use serde_json::Number;
use std::collections::BTreeMap;

pub const HP_NS: &str = "http://www.hancom.co.kr/hwpml/2011/paragraph";
pub const HC_NS: &str = "http://www.hancom.co.kr/hwpml/2011/core";

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Document {
    pub sections: Vec<Section>,
    pub headers: Vec<Section>,
    pub footers: Vec<Section>,
    pub unhandled: BTreeMap<String, usize>,
    pub unhandled_examples: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Section {
    pub blocks: Vec<Block>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "type")]
pub enum Block {
    #[serde(rename = "paragraph")]
    Paragraph { text: String, fields: Vec<String> },
    #[serde(rename = "table")]
    Table { rows: Vec<Vec<Cell>> },
    #[serde(rename = "textbox")]
    TextBox { blocks: Vec<Block> },
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Cell {
    pub blocks: Vec<Block>,
    pub span: BTreeMap<String, Number>,
    pub addr: BTreeMap<String, Number>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct CoverageLedger {
    pub counts: BTreeMap<String, usize>,
    pub examples: BTreeMap<String, String>,
    pub failure: Option<String>,
}

impl CoverageLedger {
    pub fn record(&mut self, tag: &str, path: String) {
        *self.counts.entry(tag.to_owned()).or_default() += 1;
        self.examples.entry(tag.to_owned()).or_insert(path);
    }
}
