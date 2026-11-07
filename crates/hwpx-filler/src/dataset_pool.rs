//! Pure dataset-pool confirmation and read-model projection.

use crate::dataset_reference::{
    DatasetReference, DatasetReferenceError, STATUS_ACTIVE, STATUS_ARCHIVED, reference_identity,
    reference_sheets,
};
use crate::job::sorted_json;
use crate::text_render::{python_str, python_truthy};
use serde_json::{Map, Value};
use sha1::{Digest, Sha1};
use std::collections::HashMap;
use std::path::Path;

/// Frozen registration seam: keep query metadata, never credentials or fetched records.
pub fn nara_reference(
    name: &str,
    bgn_dt: &str,
    end_dt: &str,
    num_rows: Option<i64>,
    page_no: Option<i64>,
    note: &str,
) -> Result<DatasetReference, DatasetReferenceError> {
    let name = crate::structure_scan::python_trim(name);
    if name.is_empty() {
        return Err(DatasetReferenceError("데이터셋 이름을 입력하세요.".into()));
    }
    if bgn_dt.is_empty() || end_dt.is_empty() {
        return Err(DatasetReferenceError(
            "조회 기간(시작·종료)을 입력하세요.".into(),
        ));
    }
    if let Some(error) = crate::nara::validate_range(bgn_dt, end_dt) {
        return Err(DatasetReferenceError(error));
    }
    let mut opts = Map::new();
    opts.insert("bgn_dt".into(), Value::String(bgn_dt.into()));
    opts.insert("end_dt".into(), Value::String(end_dt.into()));
    for (key, value) in [("num_rows", num_rows), ("page_no", page_no)] {
        if let Some(value) = value.filter(|value| *value != 0) {
            opts.insert(key.into(), Value::from(value));
        }
    }
    let mut item = DatasetReference::new(name, "nara", opts)?;
    item.note = note.into();
    Ok(item)
}

pub fn pool_icon_for_kind(kind: &str) -> &str {
    match kind {
        "hwpx" | "txt" | "excel" | "pclm" | "nara" => kind,
        _ => "other",
    }
}

pub const BOUND_FIELDS: [&str; 7] = [
    "key",
    "name",
    "kind",
    "identity",
    "reference",
    "note",
    "status",
];

/// The full item value used by confirmed mutations. A display summary loses opts.
pub fn bound_state(
    key: &str,
    item: &DatasetReference,
) -> Result<Map<String, Value>, DatasetReferenceError> {
    item.validate()?;
    let values = [
        key.to_owned(),
        item.name.clone(),
        item.kind.clone(),
        reference_identity(item).unwrap_or_default(),
        sorted_json(&Value::Object(item.opts.clone())),
        item.note.clone(),
        item.status.clone(),
    ];
    Ok(BOUND_FIELDS
        .into_iter()
        .zip(values)
        .map(|(key, value)| (key.into(), Value::String(value)))
        .collect())
}

/// The 16-character SHA-1 confirmation basis of key-ordered, recursively sorted states.
pub fn confirm_basis(states: &[Map<String, Value>]) -> String {
    let mut ordered = states.to_vec();
    ordered.sort_by(|left, right| {
        left.get("key")
            .and_then(Value::as_str)
            .cmp(&right.get("key").and_then(Value::as_str))
    });
    let json = sorted_json(&Value::Array(
        ordered.into_iter().map(Value::Object).collect(),
    ));
    let digest = Sha1::digest(json.as_bytes());
    digest[..8]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CorruptDatasetEntry {
    pub file_name: String,
    pub error: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PoolAction {
    pub key: String,
    pub label: String,
}
fn action(key: &str, label: &str) -> PoolAction {
    PoolAction {
        key: key.into(),
        label: label.into(),
    }
}
pub fn available_actions(status: &str) -> Vec<PoolAction> {
    match status {
        STATUS_ACTIVE => vec![action("archive", "보관"), action("delete", "삭제")],
        STATUS_ARCHIVED => vec![action("activate", "활성화"), action("delete", "삭제")],
        _ => vec![],
    }
}
fn kind_label(kind: &str) -> &str {
    match kind {
        "excel" => "엑셀/CSV",
        "nara" => "나라장터",
        "pclm" => "계약 목록",
        "pipeline" => "파이프라인",
        _ => kind,
    }
}
pub fn kind_transition_clause(item: &DatasetReference) -> String {
    if item.kind == "excel" {
        return String::new();
    }
    let label = kind_label(&item.kind);
    format!("\n종류도 {label} → 엑셀/CSV 참조로 바뀝니다(기존 {label} 참조 정보는 사라집니다).")
}
fn basename(value: &str) -> String {
    if value.is_empty() {
        "(경로 없음)".into()
    } else {
        Path::new(value)
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned()
    }
}
fn option_string(item: &DatasetReference, key: &str) -> String {
    item.opts.get(key).map_or_else(String::new, python_str)
}
/// Shared `excel`/`pclm` summary shape: a located-file label plus an optional sheet suffix.
fn file_reference_summary(label: &str, path: &str, sheets: &str) -> String {
    let mut text = format!("{label}: {}", basename(path));
    if !sheets.is_empty() {
        text.push_str(&format!(" · 시트 {sheets}"));
    }
    text
}
fn nara_reference_summary(item: &DatasetReference) -> String {
    let bgn = item
        .opts
        .get("bgn_dt")
        .map_or_else(|| "?".into(), python_str);
    let end = item
        .opts
        .get("end_dt")
        .map_or_else(|| "?".into(), python_str);
    let mut text = format!("기간 {bgn}~{end}");
    if let Some(rows) = item
        .opts
        .get("num_rows")
        .filter(|value| python_truthy(value))
    {
        text.push_str(&format!(" · {}건", python_str(rows)));
    }
    text
}
fn pipeline_reference_summary(item: &DatasetReference) -> Result<String, DatasetReferenceError> {
    let sources = item
        .opts
        .get("sources")
        .and_then(Value::as_array)
        .map_or(0, Vec::len);
    let steps = item.opts.get("steps").and_then(Value::as_array);
    let mut labels = Vec::new();
    if let Some(steps) = steps {
        for step in steps {
            let step = step.as_object().ok_or_else(|| {
                DatasetReferenceError("등록 데이터 참조 형식이 올바르지 않습니다.".into())
            })?;
            labels.push(step.get("op").map_or_else(|| "?".into(), python_str));
        }
    }
    let operations = if labels.is_empty() {
        "스텝 없음".into()
    } else {
        labels.join("+")
    };
    Ok(format!("조립: 소스 {sources}개 · {operations}"))
}
pub fn reference_summary(item: &DatasetReference) -> Result<String, DatasetReferenceError> {
    let sheets = reference_sheets(item)?.join(", ");
    Ok(match item.kind.as_str() {
        "excel" => file_reference_summary("파일", &option_string(item, "path"), &sheets),
        "pclm" => file_reference_summary("DB", &option_string(item, "db"), &sheets),
        "nara" => nara_reference_summary(item),
        "pipeline" => return pipeline_reference_summary(item),
        _ => "(알 수 없는 소스)".into(),
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DatasetPoolRow {
    pub key: String,
    pub name: String,
    pub kind: String,
    pub kind_label: String,
    pub status: String,
    pub badge_label: String,
    pub badge_level: String,
    pub reference: String,
    pub note: String,
    pub locate_path: String,
    pub sheet: String,
    pub sheets: Vec<String>,
    pub missing: bool,
}
impl DatasetPoolRow {
    /// `missing` is a host-observed file fact; `pclm` without a DB is always broken.
    pub fn from_item(
        key: &str,
        item: &DatasetReference,
        missing: bool,
    ) -> Result<Self, DatasetReferenceError> {
        item.validate()?;
        let locate_key = match item.kind.as_str() {
            "excel" => "path",
            "pclm" => "db",
            _ => "",
        };
        let locate_path = item
            .opts
            .get(locate_key)
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let sheet = if item.kind == "excel" {
            item.opts.get("sheet").and_then(Value::as_str).unwrap_or("")
        } else {
            ""
        }
        .to_owned();
        let badge_label = match item.status.as_str() {
            STATUS_ACTIVE => "활성",
            STATUS_ARCHIVED => "보관",
            _ => &item.status,
        }
        .to_owned();
        let badge_level = if item.status == STATUS_ACTIVE {
            "ok"
        } else {
            "muted"
        }
        .to_owned();
        Ok(Self {
            key: key.into(),
            name: item.name.clone(),
            kind: item.kind.clone(),
            kind_label: kind_label(&item.kind).into(),
            status: item.status.clone(),
            badge_label,
            badge_level,
            reference: reference_summary(item)?,
            note: item.note.clone(),
            locate_path: locate_path.clone(),
            sheet,
            sheets: reference_sheets(item)?,
            missing: (item.kind == "pclm" && locate_path.is_empty())
                || (!locate_path.is_empty() && missing),
        })
    }
    pub fn actions(&self) -> Vec<PoolAction> {
        let mut result = match self.kind.as_str() {
            "excel" => vec![action("relink", "다시 연결…")],
            "pclm" => vec![action("register_pclm", "사용할 시트 수정…")],
            _ => vec![],
        };
        result.extend(available_actions(&self.status));
        result
    }
    pub fn select_block_reason(&self) -> String {
        if self.kind != "excel" && self.kind != "pclm" {
            return format!(
                "{} 참조라 작업 데이터로 연결할 수 없습니다.",
                self.kind_label
            );
        }
        if self.status != STATUS_ACTIVE {
            return "보관한 항목입니다. '활성화' 뒤에 쓸 수 있습니다.".into();
        }
        if self.missing {
            if self.kind == "pclm" {
                "참조가 끊겼습니다. 계약 목록 DB 파일이 그 자리에 있는지 확인하세요.".into()
            } else {
                "참조가 끊겼습니다. '다시 연결' 뒤에 쓸 수 있습니다.".into()
            }
        } else {
            String::new()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PoolView {
    pub rows: Vec<DatasetPoolRow>,
    pub corrupted: Vec<CorruptDatasetEntry>,
    pub duplicate_keys: Vec<Vec<String>>,
}
impl PoolView {
    /// Caller passes rows projected from the same registry read as `entries`.
    pub fn project(
        rows: Vec<DatasetPoolRow>,
        entries: &[(String, DatasetReference)],
        corrupted: Vec<CorruptDatasetEntry>,
    ) -> Result<Self, DatasetReferenceError> {
        let mut groups: Vec<Vec<String>> = vec![];
        let mut indexes: HashMap<String, usize> = HashMap::new();
        for (key, item) in entries {
            item.validate()?;
            if let Some(identity) = reference_identity(item) {
                let index = *indexes.entry(identity).or_insert_with(|| {
                    groups.push(vec![]);
                    groups.len() - 1
                });
                groups[index].push(key.clone());
            }
        }
        let duplicate_keys = groups.into_iter().filter(|group| group.len() > 1).collect();
        Ok(Self {
            rows,
            corrupted,
            duplicate_keys,
        })
    }
    pub fn count_label(&self) -> String {
        if self.rows.is_empty() {
            String::new()
        } else {
            format!("{}개", self.rows.len())
        }
    }
    pub fn empty_hint(&self) -> &'static str {
        if self.rows.is_empty() {
            "고정한 데이터가 없습니다."
        } else {
            ""
        }
    }
}

/// One confirmed reference's detail projection. The host supplies the field read outcome.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DatasetDetail {
    pub key: String,
    pub name: String,
    pub kind: String,
    pub kind_label: String,
    pub status: String,
    pub badge_label: String,
    pub badge_level: String,
    pub path: String,
    pub sheet: String,
    pub sheets: Vec<String>,
    pub sheet_title: String,
    pub header_row: u64,
    pub note: String,
    pub columns: Vec<String>,
    pub error: String,
    pub actions: Vec<PoolAction>,
}
impl DatasetDetail {
    /// `columns` is the result of a single host source-open and fields read.
    pub fn from_item(
        row: &DatasetPoolRow,
        item: &DatasetReference,
        columns: Result<Vec<String>, String>,
    ) -> Result<Self, DatasetReferenceError> {
        item.validate()?;
        let (columns, error) = match columns {
            Ok(columns) => (columns, String::new()),
            Err(error) => (vec![], error),
        };
        let sheets = reference_sheets(item)?;
        let sheet = match item.kind.as_str() {
            "excel" => item.opts.get("sheet"),
            "pclm" => item.opts.get("view"),
            _ => None,
        }
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
        let header_row = item
            .opts
            .get("header_row")
            .filter(|value| !value.is_boolean())
            .and_then(Value::as_u64)
            .unwrap_or(0);
        Ok(Self {
            key: row.key.clone(),
            name: row.name.clone(),
            kind: row.kind.clone(),
            kind_label: row.kind_label.clone(),
            status: row.status.clone(),
            badge_label: row.badge_label.clone(),
            badge_level: row.badge_level.clone(),
            path: row.locate_path.clone(),
            sheet,
            sheet_title: sheets.join(", "),
            sheets,
            header_row,
            note: row.note.clone(),
            columns,
            error,
            actions: row.actions(),
        })
    }
    pub fn column_summary(&self) -> String {
        if !self.error.is_empty() {
            "열 목록을 읽지 못했습니다".into()
        } else if self.columns.is_empty() {
            "열이 없습니다.".into()
        } else {
            format!("열 {}개", self.columns.len())
        }
    }
    pub fn facts(&self) -> Vec<String> {
        let mut facts = vec![format!("종류 {}", self.kind_label)];
        if !self.sheet_title.is_empty() {
            facts.push(format!("시트: {}", self.sheet_title));
        }
        if self.header_row > 0 {
            facts.push(format!("헤더 {}행", self.header_row));
        }
        if !self.note.is_empty() {
            facts.push(format!("메모: {}", self.note));
        }
        facts
    }
    pub fn to_dict(&self) -> Value {
        let mut result = Map::new();
        for (key, value) in [
            ("key", &self.key),
            ("name", &self.name),
            ("kind", &self.kind),
            ("kind_label", &self.kind_label),
            ("status", &self.status),
            ("badge_label", &self.badge_label),
            ("badge_level", &self.badge_level),
            ("path", &self.path),
            ("sheet", &self.sheet),
            ("sheet_title", &self.sheet_title),
            ("note", &self.note),
            ("error", &self.error),
        ] {
            result.insert(key.into(), Value::String(value.clone()));
        }
        result.insert("sheets".into(), serde_json::json!(self.sheets));
        result.insert("header_row".into(), Value::from(self.header_row));
        result.insert("facts".into(), serde_json::json!(self.facts()));
        result.insert("column_count".into(), Value::from(self.columns.len()));
        result.insert(
            "column_summary".into(),
            Value::String(self.column_summary()),
        );
        result.insert("columns".into(), serde_json::json!(self.columns));
        result.insert(
            "actions".into(),
            Value::Array(
                self.actions
                    .iter()
                    .map(|action| serde_json::json!({"key":action.key,"label":action.label}))
                    .collect(),
            ),
        );
        Value::Object(result)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn confirmation_binds_full_opts_and_detail_keeps_read_error() {
        assert_pool_rows_and_details();
        let mut opts = Map::new();
        opts.insert("path".into(), Value::String("C:/a/report.xlsx".into()));
        opts.insert("sheet".into(), Value::String("Sheet 1".into()));
        opts.insert("header_row".into(), Value::from(2));
        let item = DatasetReference::new("report", "excel", opts).unwrap();
        let state = bound_state("slot", &item).unwrap();
        assert_eq!(state["key"], "slot");
        assert!(state["reference"].as_str().unwrap().contains("header_row"));
        let basis = confirm_basis(std::slice::from_ref(&state));
        assert_eq!(basis, "263a937031e58eb3");
        assert_eq!(basis, confirm_basis(&[state]));
        let python_state: Map<String, Value> = serde_json::from_value(json!({
            "key":"slot", "name":"report", "kind":"excel",
            "identity":"c:/a/report.xlsx|Sheet 1",
            "reference":"{\"header_row\": 2, \"path\": \"C:/a/report.xlsx\", \"sheet\": \"Sheet 1\"}",
            "note":"", "status":"active"
        })).unwrap();
        assert_eq!(confirm_basis(&[python_state]), "5ed448514a9796c1");
        let mut changed = item.clone();
        changed.opts.insert("header_row".into(), Value::from(3));
        assert_ne!(
            basis,
            confirm_basis(&[bound_state("slot", &changed).unwrap()])
        );

        let row = DatasetPoolRow::from_item("slot", &item, true).unwrap();
        assert!(row.missing);
        assert_eq!(row.actions()[0].key, "relink");
        let detail = DatasetDetail::from_item(&row, &item, Err("파일 없음".into())).unwrap();
        let value = detail.to_dict();
        assert_eq!(value["column_summary"], "열 목록을 읽지 못했습니다");
        assert_eq!(value["column_count"], json!(0));
        assert_eq!(value["error"], "파일 없음");
        let nara = DatasetReference::new(
            "period",
            "nara",
            serde_json::from_value(json!({"bgn_dt":null})).unwrap(),
        )
        .unwrap();
        assert_eq!(reference_summary(&nara).unwrap(), "기간 None~?");
        let pipeline = DatasetReference::new(
            "broken",
            "pipeline",
            serde_json::from_value(json!({"steps":[1]})).unwrap(),
        )
        .unwrap();
        assert!(reference_summary(&pipeline).is_err());
    }

    fn assert_pool_rows_and_details() {
        let empty = PoolView::project(vec![], &[], vec![]).unwrap();
        assert_eq!(empty.empty_hint(), "고정한 데이터가 없습니다.");
        assert_eq!(empty.count_label(), "");
        assert!(available_actions("typo").is_empty());
        for kind in ["hwpx", "txt", "excel", "pclm", "nara"] {
            assert_eq!(pool_icon_for_kind(kind), kind);
        }
        assert_eq!(pool_icon_for_kind("pipeline"), "other");
        assert_eq!(pool_icon_for_kind(""), "other");
        for (kind, opts, label, summary, path, sheet, verb) in [
            (
                "excel",
                json!({"path":"C:/data/report.xlsx","sheet":"낙찰현황"}),
                "엑셀/CSV",
                "파일: report.xlsx · 시트 낙찰현황",
                "C:/data/report.xlsx",
                "낙찰현황",
                "relink",
            ),
            (
                "pclm",
                json!({"db":"C:/data/pclm.db","view":"v_품목_v1","sheets":["v_품목_v1"]}),
                "계약 목록",
                "DB: pclm.db · 시트 v_품목_v1",
                "C:/data/pclm.db",
                "v_품목_v1",
                "register_pclm",
            ),
        ] {
            let mut item =
                DatasetReference::new("분기 자료", kind, opts.as_object().unwrap().clone())
                    .unwrap();
            item.note = "분기 집계".into();
            let row = DatasetPoolRow::from_item("slot", &item, false).unwrap();
            assert_eq!(row.kind_label, label);
            assert_eq!(row.reference, summary);
            assert_eq!(row.locate_path, path);
            assert_eq!(row.sheet, if kind == "excel" { sheet } else { "" });
            assert_eq!(row.note, item.note);
            assert!(!row.missing);
            assert!(row.select_block_reason().is_empty());
            assert_eq!(
                row.actions()
                    .iter()
                    .map(|a| a.key.as_str())
                    .collect::<Vec<_>>(),
                [verb, "archive", "delete"]
            );
            if kind == "excel" {
                assert_eq!(row.actions()[0].label, "다시 연결…");
            }
            let view =
                PoolView::project(vec![row.clone()], &[("slot".into(), item.clone())], vec![])
                    .unwrap();
            assert_eq!(view.count_label(), "1개");
            assert_eq!(view.empty_hint(), "");
            let detail =
                DatasetDetail::from_item(&row, &item, Ok(vec!["번호".into(), "업체명".into()]))
                    .unwrap();
            assert_eq!((&detail.key, &detail.name), (&row.key, &row.name));
            assert_eq!(
                (&detail.badge_label, &detail.badge_level),
                (&row.badge_label, &row.badge_level)
            );
            assert_eq!(detail.actions, row.actions());
            assert_eq!(detail.path, path);
            assert_eq!(detail.sheet, sheet);
            assert_eq!(detail.sheet_title, sheet);
            assert_eq!(
                detail.facts(),
                [
                    format!("종류 {label}"),
                    format!("시트: {sheet}"),
                    "메모: 분기 집계".into()
                ]
            );
            assert_eq!(detail.to_dict()["column_count"], 2);
            assert_eq!(detail.column_summary(), "열 2개");
            assert!(detail.error.is_empty());
            let no_columns = DatasetDetail::from_item(&row, &item, Ok(vec![])).unwrap();
            assert_eq!(no_columns.column_summary(), "열이 없습니다.");

            let missing = DatasetPoolRow::from_item("slot", &item, true).unwrap();
            let reason = missing.select_block_reason();
            assert!(missing.missing);
            assert!(reason.contains("참조가 끊겼습니다"));
            assert_eq!(reason.contains("다시 연결"), kind == "excel");
            if kind == "pclm" {
                assert!(reason.contains("계약 목록 DB 파일"));
                for opts in [json!({"view":sheet}), json!({"view":sheet,"db":""})] {
                    let placeless =
                        DatasetReference::new("자리 없음", kind, opts.as_object().unwrap().clone())
                            .unwrap();
                    let placeless = DatasetPoolRow::from_item("slot", &placeless, false).unwrap();
                    assert!(placeless.missing);
                    assert_eq!(placeless.select_block_reason(), reason);
                }
            }
            let broken =
                DatasetDetail::from_item(&missing, &item, Err("파일 없음".into())).unwrap();
            assert!(broken.columns.is_empty());
            assert_eq!(broken.column_summary(), "열 목록을 읽지 못했습니다");
            assert_eq!(broken.badge_label, "활성");
            assert_eq!(broken.actions, row.actions());
            item.status = STATUS_ARCHIVED.into();
            let archived = DatasetPoolRow::from_item("slot", &item, false).unwrap();
            assert!(archived.select_block_reason().contains("보관한 항목입니다"));
            assert!(archived.select_block_reason().contains("활성화"));
            assert_eq!(
                archived
                    .actions()
                    .iter()
                    .map(|a| a.key.as_str())
                    .collect::<Vec<_>>(),
                [verb, "activate", "delete"]
            );
        }
        for (kind, opts, label, summary) in [
            ("excel", json!({}), "엑셀/CSV", "파일: (경로 없음)"),
            (
                "미래소스",
                json!({"db":"/x.db"}),
                "미래소스",
                "(알 수 없는 소스)",
            ),
            ("nara", json!({}), "나라장터", "기간 ?~?"),
            (
                "pipeline",
                json!({"sources":[{"kind":"excel"},{"kind":"excel"}],"steps":[{"op":"merge"}]}),
                "파이프라인",
                "조립: 소스 2개 · merge",
            ),
        ] {
            let item =
                DatasetReference::new("자료", kind, opts.as_object().unwrap().clone()).unwrap();
            let row = DatasetPoolRow::from_item("slot", &item, true).unwrap();
            assert_eq!(row.kind_label, label);
            assert_eq!(row.reference, summary);
            assert!(row.locate_path.is_empty());
            assert!(!row.missing);
            if kind != "excel" {
                assert!(
                    row.select_block_reason()
                        .contains("작업 데이터로 연결할 수 없습니다")
                );
            }
        }
    }
}
