//! Shared ordered string-record contract for file, SQLite and assembled sources.

use indexmap::IndexMap;
use std::fmt;

pub const SUPPORTED_DATA_FILE_EXTENSIONS: [&str; 3] = [".xlsx", ".xlsm", ".csv"];
pub const CONTRACT_LIST_FILE_EXTENSIONS: [&str; 2] = [".db", ".pclm"];

pub type Record = IndexMap<String, String>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DataSourceError(pub String);
impl fmt::Display for DataSourceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for DataSourceError {}

pub trait DataSource {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError>;
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError>;
    fn field_labels(&self) -> IndexMap<String, String> {
        IndexMap::new()
    }
    fn source_pointer(&self) -> Option<String> {
        None
    }
}

pub struct InlineDataSource {
    records: Vec<Record>,
}
impl InlineDataSource {
    pub fn new(records: Vec<Record>) -> Self {
        Self { records }
    }
}
impl DataSource for InlineDataSource {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
        Ok(self.records.clone())
    }
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
        let mut seen = indexmap::IndexSet::new();
        for record in &self.records {
            seen.extend(record.keys().cloned());
        }
        Ok(seen.into_iter().collect())
    }
}
