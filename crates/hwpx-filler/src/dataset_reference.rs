//! Pure durable dataset reference values, sheet selection and identity.

use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fmt;
use std::path::{Component, Path, PathBuf};

pub const STATUS_ACTIVE: &str = "active";
pub const STATUS_ARCHIVED: &str = "archived";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DatasetReferenceError(pub String);
impl fmt::Display for DatasetReferenceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for DatasetReferenceError {}
fn fail(detail: impl Into<String>) -> DatasetReferenceError {
    DatasetReferenceError(detail.into())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FilterPreset {
    pub name: String,
    pub state: Map<String, Value>,
}
impl FilterPreset {
    pub fn to_dict(&self) -> Value {
        let mut out = Map::new();
        out.insert("name".into(), Value::String(self.name.clone()));
        out.insert("state".into(), Value::Object(self.state.clone()));
        Value::Object(out)
    }
}
pub fn filter_presets_shape(raw: &Value) -> Result<Vec<FilterPreset>, DatasetReferenceError> {
    let entries = raw
        .as_array()
        .ok_or_else(|| fail("저장한 필터 목록 형식이 올바르지 않습니다."))?;
    let mut seen = HashSet::new();
    let mut result = Vec::with_capacity(entries.len());
    for entry in entries {
        let data = entry
            .as_object()
            .ok_or_else(|| fail("저장한 필터 항목 형식이 올바르지 않습니다."))?;
        let name = data
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| !python_trim(name).is_empty())
            .ok_or_else(|| fail("저장한 필터 항목 형식이 올바르지 않습니다."))?;
        let state = data
            .get("state")
            .and_then(Value::as_object)
            .ok_or_else(|| fail("저장한 필터 항목 형식이 올바르지 않습니다."))?;
        if !seen.insert(name) {
            return Err(fail(format!("저장한 필터 이름이 겹칩니다: {name}")));
        }
        result.push(FilterPreset {
            name: name.into(),
            state: state.clone(),
        });
    }
    Ok(result)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DatasetReference {
    pub name: String,
    pub kind: String,
    pub opts: Map<String, Value>,
    pub status: String,
    pub created_at: String,
    pub note: String,
    pub version: Value,
    pub filters: Vec<FilterPreset>,
    pub sheet_filters: Map<String, Value>,
}
impl DatasetReference {
    pub fn new(
        name: impl Into<String>,
        kind: impl Into<String>,
        opts: Map<String, Value>,
    ) -> Result<Self, DatasetReferenceError> {
        let result = Self {
            name: name.into(),
            kind: kind.into(),
            opts,
            status: STATUS_ACTIVE.into(),
            created_at: String::new(),
            note: String::new(),
            version: Value::from(1),
            filters: Vec::new(),
            sheet_filters: Map::new(),
        };
        result.validate()?;
        Ok(result)
    }
    pub fn validate(&self) -> Result<(), DatasetReferenceError> {
        if ![STATUS_ACTIVE, STATUS_ARCHIVED].contains(&self.status.as_str()) {
            return Err(fail(format!(
                "알 수 없는 데이터셋 상태입니다: {}",
                python_repr(&Value::String(self.status.clone()))
            )));
        }
        reference_sheets(self)?;
        for (name, presets) in &self.sheet_filters {
            if name.is_empty() {
                return Err(fail("시트별 필터 형식이 올바르지 않습니다."));
            }
            filter_presets_shape(presets)?;
        }
        let mut seen = HashSet::new();
        for preset in &self.filters {
            if python_trim(&preset.name).is_empty() || !seen.insert(&preset.name) {
                return Err(fail("저장한 필터 항목 형식이 올바르지 않습니다."));
            }
        }
        Ok(())
    }
    pub fn archive(&mut self) {
        self.status = STATUS_ARCHIVED.into();
    }
    pub fn activate(&mut self) {
        self.status = STATUS_ACTIVE.into();
    }
    pub fn is_active(&self) -> bool {
        self.status == STATUS_ACTIVE
    }
    pub fn to_dict(&self) -> Value {
        let mut out = Map::new();
        out.insert("version".into(), self.version.clone());
        out.insert("name".into(), Value::String(self.name.clone()));
        out.insert("kind".into(), Value::String(self.kind.clone()));
        out.insert("opts".into(), Value::Object(self.opts.clone()));
        out.insert("status".into(), Value::String(self.status.clone()));
        out.insert("created_at".into(), Value::String(self.created_at.clone()));
        out.insert("note".into(), Value::String(self.note.clone()));
        if !self.filters.is_empty() {
            out.insert(
                "filters".into(),
                Value::Array(self.filters.iter().map(FilterPreset::to_dict).collect()),
            );
        }
        if !self.sheet_filters.is_empty() {
            out.insert(
                "sheet_filters".into(),
                Value::Object(self.sheet_filters.clone()),
            );
        }
        Value::Object(out)
    }
    pub fn from_dict(raw: &Value) -> Result<Self, DatasetReferenceError> {
        let data = raw
            .as_object()
            .ok_or_else(|| fail("등록 데이터 참조 형식이 올바르지 않습니다."))?;
        let opts = data.get("opts").map_or_else(
            || Ok(Map::new()),
            |value| {
                value
                    .as_object()
                    .cloned()
                    .ok_or_else(|| fail("등록 데이터 참조 형식이 올바르지 않습니다."))
            },
        )?;
        let status = data.get("status").unwrap_or(&Value::Null);
        let status = if data.contains_key("status") {
            status
                .as_str()
                .ok_or_else(|| {
                    fail(format!(
                        "알 수 없는 데이터셋 상태입니다: {}",
                        python_repr(status)
                    ))
                })?
                .to_owned()
        } else {
            STATUS_ACTIVE.into()
        };
        let filters =
            filter_presets_shape(data.get("filters").unwrap_or(&Value::Array(Vec::new())))?;
        let sheet_filters = data.get("sheet_filters").map_or_else(
            || Ok(Map::new()),
            |value| {
                value
                    .as_object()
                    .cloned()
                    .ok_or_else(|| fail("시트별 필터 형식이 올바르지 않습니다."))
            },
        )?;
        let result = Self {
            name: value_string(data, "name")?,
            kind: value_string(data, "kind")?,
            opts,
            status,
            created_at: value_string(data, "created_at")?,
            note: value_string(data, "note")?,
            version: data.get("version").cloned().unwrap_or(Value::from(1)),
            filters,
            sheet_filters,
        };
        result.validate()?;
        Ok(result)
    }
}
fn value_string(data: &Map<String, Value>, key: &str) -> Result<String, DatasetReferenceError> {
    match data.get(key) {
        None => Ok(String::new()),
        Some(Value::String(value)) => Ok(value.clone()),
        _ => Err(fail(format!(
            "등록 데이터 참조의 {key} 형식이 올바르지 않습니다."
        ))),
    }
}

pub fn reference_sheets(item: &DatasetReference) -> Result<Vec<String>, DatasetReferenceError> {
    let raw = if item.kind == "excel" {
        item.opts.get("sheet")
    } else {
        item.opts.get("view")
    };
    let default = raw.and_then(Value::as_str).filter(|name| !name.is_empty());
    if !["excel", "pclm"].contains(&item.kind.as_str()) || !item.opts.contains_key("sheets") {
        return Ok(default.into_iter().map(str::to_owned).collect());
    }
    let sheets = item.opts["sheets"]
        .as_array()
        .ok_or_else(|| fail("등록할 시트와 기본 시트를 확인하세요."))?;
    if sheets.is_empty() {
        return Err(fail("등록할 시트와 기본 시트를 확인하세요."));
    }
    let mut seen = HashSet::new();
    let mut result = Vec::with_capacity(sheets.len());
    for sheet in sheets {
        let sheet = sheet
            .as_str()
            .filter(|name| !name.is_empty())
            .ok_or_else(|| fail("등록할 시트와 기본 시트를 확인하세요."))?;
        if !seen.insert(sheet) {
            return Err(fail("등록할 시트와 기본 시트를 확인하세요."));
        }
        result.push(sheet.into());
    }
    if !default.is_some_and(|name| seen.contains(name)) {
        return Err(fail("등록할 시트와 기본 시트를 확인하세요."));
    }
    Ok(result)
}
pub fn filters_for_sheet(
    item: &DatasetReference,
    sheet: Option<&str>,
) -> Result<Vec<FilterPreset>, DatasetReferenceError> {
    let default = item
        .opts
        .get(if item.kind == "excel" {
            "sheet"
        } else {
            "view"
        })
        .and_then(Value::as_str)
        .unwrap_or("");
    if sheet.is_none_or(|sheet| sheet == default)
        || !["excel", "pclm"].contains(&item.kind.as_str())
    {
        return Ok(item.filters.clone());
    }
    let sheet = sheet.expect("checked Some above");
    if !reference_sheets(item)?.iter().any(|name| name == sheet) {
        return Err(fail("등록된 시트를 선택하세요."));
    }
    let raw = item
        .sheet_filters
        .get(sheet)
        .cloned()
        .unwrap_or_else(|| Value::Array(Vec::new()));
    filter_presets_shape(&raw)
}
pub fn reference_for_sheet(
    item: &DatasetReference,
    sheet: Option<&str>,
) -> Result<DatasetReference, DatasetReferenceError> {
    let mut selected = item.clone();
    let Some(sheet) = sheet else {
        return Ok(selected);
    };
    if sheet.is_empty() && reference_sheets(item)?.is_empty() {
        return Ok(selected);
    }
    if !reference_sheets(item)?.iter().any(|name| name == sheet) {
        return Err(fail("등록된 시트를 선택하세요."));
    }
    selected.filters = filters_for_sheet(item, Some(sheet))?;
    selected.opts.insert(
        if item.kind == "excel" {
            "sheet"
        } else {
            "view"
        }
        .into(),
        Value::String(sheet.into()),
    );
    Ok(selected)
}
pub fn excel_reference_opts(
    path: &str,
    sheet: Option<&str>,
    sheets: Option<&[String]>,
) -> Result<Map<String, Value>, DatasetReferenceError> {
    let mut opts = Map::new();
    opts.insert("path".into(), Value::String(path.into()));
    if let Some(sheet) = sheet.filter(|sheet| !sheet.is_empty()) {
        opts.insert("sheet".into(), Value::String(sheet.into()));
    }
    if let Some(sheets) = sheets {
        opts.insert(
            "sheets".into(),
            Value::Array(sheets.iter().cloned().map(Value::String).collect()),
        );
    }
    DatasetReference::new("", "excel", opts.clone())?;
    Ok(opts)
}

fn normcase_abspath(path: &str) -> String {
    // Use lexical absolute normalization: identities must not depend on file existence.
    let lexical = if path.is_empty() { "." } else { path };
    let absolute =
        std::path::absolute(Path::new(lexical)).unwrap_or_else(|_| PathBuf::from(lexical));
    let mut normalized = PathBuf::new();
    for part in absolute.components() {
        match part {
            Component::CurDir => (),
            Component::ParentDir => {
                normalized.pop();
            }
            _ => normalized.push(part.as_os_str()),
        }
    }
    normalized
        .to_string_lossy()
        .replace('/', "\\")
        .to_lowercase()
}
pub fn excel_identity(path: &str, sheet: Option<&str>) -> String {
    format!("{}\x1f{}", normcase_abspath(path), sheet.unwrap_or(""))
}
pub fn pclm_identity(db: &str, view: &str) -> String {
    format!("pclm\x1f{}", excel_identity(db, Some(view)))
}
pub fn resolve_pclm_db(db: &str) -> Result<String, DatasetReferenceError> {
    if db.is_empty() {
        return Err(fail("파일 경로가 비어 있습니다."));
    }
    Ok(std::path::absolute(Path::new(db))
        .map_err(|error| fail(error.to_string()))?
        .to_string_lossy()
        .into_owned())
}
pub fn reference_identity(item: &DatasetReference) -> Option<String> {
    match item.kind.as_str() {
        "excel" => {
            let path = item
                .opts
                .get("path")?
                .as_str()
                .filter(|path| !path.is_empty())?;
            Some(excel_identity(
                path,
                item.opts.get("sheet").and_then(Value::as_str),
            ))
        }
        "pclm" => {
            let db = item.opts.get("db")?.as_str().filter(|db| !db.is_empty())?;
            let view = item.opts.get("view")?.as_str()?;
            Some(pclm_identity(db, view))
        }
        _ => None,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn sheet_selection_is_a_copy_and_filter_shapes_fail_closed() {
        assert_legacy_values_and_identity();
        let opts =
            excel_reference_opts("C:/data/a.xlsx", Some("A"), Some(&["A".into(), "B".into()]))
                .unwrap();
        let mut item = DatasetReference::new("자료", "excel", opts).unwrap();
        item.filters =
            filter_presets_shape(&serde_json::json!([{"name":"기본","state":{"x":1}}])).unwrap();
        item.sheet_filters
            .insert("B".into(), serde_json::json!([{"name":"별도","state":{}}]));
        let selected = reference_for_sheet(&item, Some("B")).unwrap();
        assert_eq!(selected.opts["sheet"], "B");
        assert_eq!(selected.filters[0].name, "별도");
        assert_eq!(item.opts["sheet"], "A");
        assert_eq!(item.filters[0].name, "기본");
        assert_eq!(DatasetReference::from_dict(&item.to_dict()).unwrap(), item);
        assert!(excel_reference_opts("x", Some("A"), Some(&["A".into(), "A".into()])).is_err());
        for invalid in [
            serde_json::json!(null),
            serde_json::json!([null]),
            serde_json::json!([{"name":"","state":{}}]),
            serde_json::json!([{"name":" \t","state":{}}]),
            serde_json::json!([{"name":"x","state":[]}]),
            serde_json::json!([{"name":"x","state":{}},{"name":"x","state":{}}]),
        ] {
            assert!(filter_presets_shape(&invalid).is_err(), "{invalid}");
        }
        let mut duplicate = item.clone();
        duplicate.filters.push(duplicate.filters[0].clone());
        assert!(duplicate.validate().is_err());
        assert!(reference_for_sheet(&item, Some("missing")).is_err());
        assert!(filters_for_sheet(&item, Some("missing")).is_err());
    }

    fn assert_legacy_values_and_identity() {
        use serde_json::json;
        let legacy = json!({"name":"구", "kind":"excel"});
        let mut item = DatasetReference::from_dict(&legacy).unwrap();
        assert!(item.opts.is_empty() && item.filters.is_empty() && item.note.is_empty());
        assert!(item.is_active());
        item.archive();
        assert_eq!(item.status, STATUS_ARCHIVED);
        assert!(!item.is_active());
        item.activate();
        assert!(item.is_active());
        assert!(item.to_dict().get("filters").is_none());
        for (field, value) in [
            ("status", json!("bogus")),
            ("status", Value::Null),
            ("opts", json!([])),
            ("name", json!(1)),
            ("sheet_filters", json!([])),
            ("sheet_filters", json!({"":[]})),
        ] {
            let mut invalid = legacy.clone();
            invalid[field] = value;
            assert!(DatasetReference::from_dict(&invalid).is_err(), "{invalid}");
        }
        assert!(DatasetReference::from_dict(&json!([])).is_err());
        let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("data.xlsx");
        let path = path.to_str().unwrap();
        assert_eq!(
            excel_identity(path, None),
            excel_identity(&path.to_uppercase(), None)
        );
        assert_ne!(
            excel_identity(path, None),
            excel_identity(path, Some("1월"))
        );
        assert_ne!(
            excel_identity(path, Some("1월")),
            excel_identity(path, Some("2월"))
        );
        assert_eq!(
            pclm_identity(path, "v_통합"),
            pclm_identity(&path.to_uppercase(), "v_통합")
        );
        assert_ne!(pclm_identity(path, "v_통합"), pclm_identity(path, "v_계약"));
        assert_ne!(
            pclm_identity(path, "v_통합"),
            excel_identity(path, Some("v_통합"))
        );
        assert_eq!(
            pclm_identity("sub/../pclm.db", "v_공고"),
            pclm_identity("pclm.db", "v_공고")
        );
        for (kind, opts, expected) in [
            (
                "excel",
                json!({"path":path}),
                Some(excel_identity(path, None)),
            ),
            (
                "pclm",
                json!({"db":path,"view":"v_통합"}),
                Some(pclm_identity(path, "v_통합")),
            ),
            ("nara", json!({}), None),
            ("pipeline", json!({}), None),
            ("excel", json!({}), None),
            ("excel", json!({"path":3}), None),
            ("pclm", json!({"db":3,"view":"v_통합"}), None),
            ("pclm", json!({"db":path,"view":3}), None),
            ("pclm", json!({"db":"","view":"v_통합"}), None),
            ("pclm", json!({"view":"v_통합"}), None),
        ] {
            let item =
                DatasetReference::new("자료", kind, opts.as_object().unwrap().clone()).unwrap();
            assert_eq!(reference_identity(&item), expected);
        }
    }
}
