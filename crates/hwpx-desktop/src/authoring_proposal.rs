//! Actual pool-backed data port for the authoring proposal panel.

use crate::dataset_registry::DatasetPoolRegistry;
use crate::nara_source::source_from_pool_reference_live;
use hwpx_filler::data_excel::ambiguous_sheet_error;
use hwpx_filler::dataset_reference::reference_for_sheet;
use hwpx_filler::field_proposal::{LoadedRows, normalize_rows};
use serde_json::{Map, Value, json};
use std::path::Path;
use std::sync::Arc;

const FROZEN_NARA: &str =
    "나라장터 소스는 현재 웹에서 지원되지 않습니다. 파일 또는 엑셀 참조 등록 데이터를 사용하세요.";
const MISSING: &str = "등록 데이터를 찾을 수 없습니다(이미 삭제된 항목).";

fn pipeline_has_nara(opts: &Map<String, Value>) -> bool {
    let mut pending: Vec<_> = opts
        .get("sources")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .collect();
    while let Some(source) = pending.pop() {
        let Some(source) = source.as_object() else {
            continue;
        };
        match source.get("kind").and_then(Value::as_str) {
            Some("nara") => return true,
            Some("pipeline") => pending.extend(
                source
                    .get("opts")
                    .and_then(Value::as_object)
                    .and_then(|opts| opts.get("sources"))
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten(),
            ),
            _ => {}
        }
    }
    false
}

#[derive(Clone)]
pub struct ProposalData {
    registry: Arc<DatasetPoolRegistry>,
    current: Arc<CurrentPoolSource>,
}
type CurrentPoolSource = dyn Fn() -> Result<Option<(String, Option<String>)>, String> + Send + Sync;
impl ProposalData {
    pub fn new(
        registry: Arc<DatasetPoolRegistry>,
        current: impl Fn() -> Result<Option<(String, Option<String>)>, String> + Send + Sync + 'static,
    ) -> Self {
        Self {
            registry,
            current: Arc::new(current),
        }
    }
    pub fn current(&self) -> Result<Option<(String, Option<String>)>, String> {
        (self.current)()
    }
    pub fn datasets(&self) -> Result<Vec<Value>, String> {
        let (items, _) = self
            .registry
            .list_references(Some("active"))
            .map_err(|error| error.to_string())?;
        Ok(items
            .into_iter()
            .map(|(key, item)| json!({"key":key,"name":item.name}))
            .collect())
    }
    pub fn load(&self, key: &str, sheet: Option<&str>) -> LoadedRows {
        match self.load_inner(key, sheet) {
            Ok(value) => value,
            Err(error) => LoadedRows {
                error,
                ..LoadedRows::default()
            },
        }
    }
    fn load_inner(&self, key: &str, sheet: Option<&str>) -> Result<LoadedRows, String> {
        let item = self.registry.load(key).map_err(|_| MISSING.to_owned())?;
        if item.kind == "nara" || item.kind == "pipeline" && pipeline_has_nara(&item.opts) {
            return Err(FROZEN_NARA.into());
        }
        if item.kind == "excel"
            && item
                .opts
                .get("sheet")
                .is_none_or(|value| value.as_str().is_none_or(str::is_empty))
        {
            let path = item.opts.get("path").and_then(Value::as_str).unwrap_or("");
            let prefix = format!(
                "등록 데이터 '{}' 에 시트가 지정되지 않았습니다. ",
                item.name
            );
            if let Some(error) = ambiguous_sheet_error(Path::new(path), &prefix) {
                return Err(error);
            }
        }
        let selected = reference_for_sheet(&item, sheet).map_err(|error| error.to_string())?;
        let mut source = source_from_pool_reference_live(&selected)
            .map_err(|error| format!("등록 데이터를 불러올 수 없습니다: {error}"))?;
        let records = source
            .records()
            .map_err(|error| format!("등록 데이터를 불러올 수 없습니다: {error}"))?;
        if records.is_empty() {
            return Err("데이터에 행이 없습니다.".into());
        }
        let rows = records
            .iter()
            .map(|record| {
                record
                    .iter()
                    .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                    .collect()
            })
            .collect::<Vec<Map<String, Value>>>();
        Ok(normalize_rows(&selected.name, &rows))
    }
}
