//! Product source-kind routing over the existing Rust DataSource adapters.

#[cfg(feature = "native-data")]
use crate::data_excel::ExcelDataSource;
#[cfg(feature = "native-data")]
use crate::data_pclm::PclmDataSource;
use crate::data_pipeline::PipelineSource;
use crate::data_source::{
    CONTRACT_LIST_FILE_EXTENSIONS, DataSource, DataSourceError, InlineDataSource, Record,
    SUPPORTED_DATA_FILE_EXTENSIONS,
};
use crate::dataset_reference::DatasetReference;
use crate::nara::{NaraFetcher, NaraStdDataSource};
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::path::Path;
#[cfg(not(feature = "native-data"))]
use unavailable::{ExcelDataSource, PclmDataSource};

fn fail(detail: impl Into<String>) -> DataSourceError {
    DataSourceError(detail.into())
}

/// `native-data` 를 끈 빌드(wasm32)의 자리 — 같은 이름으로 불리고 언제나 오류로 답한다.
#[cfg(not(feature = "native-data"))]
#[allow(clippy::new_ret_no_self)] // 부르는 쪽이 진짜 어댑터와 같은 이름 · 같은 꼴로 부른다.
mod unavailable {
    use super::fail;
    use crate::data_source::{DataSourceError, InlineDataSource};

    pub struct ExcelDataSource;
    impl ExcelDataSource {
        pub fn new<P, S>(
            _path: P,
            _sheet: S,
            _header_row: usize,
        ) -> Result<InlineDataSource, DataSourceError> {
            Err(fail("이 빌드에는 엑셀 읽기가 없습니다."))
        }
    }

    pub struct PclmDataSource;
    impl PclmDataSource {
        pub fn new<P, V>(_path: P, _view: V) -> Result<InlineDataSource, DataSourceError> {
            Err(fail("이 빌드에는 계약목록 읽기가 없습니다."))
        }
    }
}
fn text<'a>(
    opts: &'a Map<String, Value>,
    key: &str,
    default: Option<&'a str>,
) -> Result<&'a str, DataSourceError> {
    match opts.get(key) {
        Some(Value::String(value)) => Ok(value),
        None => default.ok_or_else(|| fail(format!("{key} 가 없습니다."))),
        _ => Err(fail(format!("{key} 는 문자열이어야 합니다."))),
    }
}
fn header_row(opts: &Map<String, Value>) -> Result<usize, DataSourceError> {
    match opts.get("header_row") {
        None => Ok(1),
        Some(value) if !value.is_boolean() => value
            .as_u64()
            .and_then(|v| usize::try_from(v).ok())
            .filter(|v| *v >= 1)
            .ok_or_else(|| fail("header_row는 1 이상의 정수여야 합니다.")),
        _ => Err(fail("header_row는 1 이상의 정수여야 합니다.")),
    }
}
fn only_keys(opts: &Map<String, Value>, allowed: &[&str]) -> Result<(), DataSourceError> {
    if let Some(key) = opts.keys().find(|key| !allowed.contains(&key.as_str())) {
        return Err(fail(format!("미지원 데이터 소스 옵션: {key}")));
    }
    Ok(())
}
pub fn is_contract_list_file(path: &Path) -> bool {
    path.extension().is_some_and(|extension| {
        CONTRACT_LIST_FILE_EXTENSIONS
            .iter()
            .any(|supported| extension.eq_ignore_ascii_case(&supported[1..]))
    })
}
pub fn source_for_path(
    path: &Path,
    sheet: Option<&str>,
    header_row: usize,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| format!(".{}", extension.to_lowercase()))
        .unwrap_or_default();
    if SUPPORTED_DATA_FILE_EXTENSIONS.contains(&extension.as_str()) {
        return Ok(Box::new(ExcelDataSource::new(
            path,
            sheet.map(str::to_owned),
            header_row,
        )?));
    }
    Err(fail(format!(
        "지원하지 않는 데이터 파일 형식입니다: {}",
        if extension.is_empty() {
            "(확장자 없음)"
        } else {
            &extension
        }
    )))
}
/// Restore a durable four-part work binding without inferring its source kind.
pub fn source_for_binding(
    path: &str,
    sheet: &str,
    header_row: Option<usize>,
    kind: &str,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    if path.is_empty() {
        return Err(fail("데이터 참조에 경로가 없습니다."));
    }
    match kind {
        "pclm" => Ok(Box::new(PclmDataSource::new(path, sheet)?)),
        "" => source_for_path(
            Path::new(path),
            (!sheet.is_empty()).then_some(sheet),
            header_row.filter(|row| *row > 0).unwrap_or(1),
        ),
        _ => Err(fail(format!(
            "'{kind}' 데이터 결속은 파일로 복원할 수 없습니다."
        ))),
    }
}

/// Read one durable pool reference as a single four-part binding observation.
pub fn binding_for_reference(item: &DatasetReference) -> (String, String, u64, String) {
    let text = |key: &str| {
        item.opts
            .get(key)
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned()
    };
    if item.kind == "pclm" {
        return (text("db"), text("view"), 0, "pclm".into());
    }
    let path = if item.kind == "excel" {
        text("path")
    } else {
        String::new()
    };
    let header_row = if path.is_empty() {
        0
    } else {
        item.opts
            .get("header_row")
            .filter(|v| !v.is_boolean())
            .and_then(Value::as_u64)
            .filter(|v| *v > 0)
            .unwrap_or(0)
    };
    (path, text("sheet"), header_row, String::new())
}
fn inline_source(opts: &Map<String, Value>) -> Result<Box<dyn DataSource>, DataSourceError> {
    only_keys(opts, &["records"])?;
    let rows = opts
        .get("records")
        .and_then(Value::as_array)
        .ok_or_else(|| fail("records 는 목록이어야 합니다."))?;
    let mut records = Vec::with_capacity(rows.len());
    for row in rows {
        let row = row
            .as_object()
            .ok_or_else(|| fail("inline record 는 사전이어야 합니다."))?;
        let mut record = Record::new();
        for (key, value) in row {
            let value = value
                .as_str()
                .ok_or_else(|| fail("inline record 값은 문자열이어야 합니다."))?;
            record.insert(key.clone(), value.into());
        }
        records.push(record);
    }
    Ok(Box::new(InlineDataSource::new(records)))
}
fn source_from_parts(
    kind: &str,
    opts: &Map<String, Value>,
    depth: usize,
    nara_access: Option<(&str, &NaraFetcher)>,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    if depth > 32 {
        return Err(fail("파이프라인 소스 중첩이 너무 깊습니다."));
    }
    match kind {
        "excel" => excel_source(opts),
        "pclm" => pclm_source(opts),
        "inline" => inline_source(opts),
        "pipeline" => pipeline_source(opts, depth, nara_access),
        "nara" => nara_source(opts, nara_access),
        _ => Err(fail(format!(
            "알 수 없는 데이터 소스 종류입니다: {}",
            python_repr(&Value::String(kind.into()))
        ))),
    }
}

fn excel_source(opts: &Map<String, Value>) -> Result<Box<dyn DataSource>, DataSourceError> {
    only_keys(opts, &["path", "sheet", "header_row", "sheets"])?;
    let path = text(opts, "path", None)?;
    let sheet = match opts.get("sheet") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => Some(s.as_str()),
        _ => return Err(fail("sheet 는 문자열이어야 합니다.")),
    };
    source_for_path(Path::new(path), sheet, header_row(opts)?)
}

fn pclm_source(opts: &Map<String, Value>) -> Result<Box<dyn DataSource>, DataSourceError> {
    only_keys(opts, &["db", "view", "sheets"])?;
    let db = text(opts, "db", Some(""))?;
    let view = text(opts, "view", None)?;
    Ok(Box::new(PclmDataSource::new(db, view)?))
}

fn pipeline_source(
    opts: &Map<String, Value>,
    depth: usize,
    nara_access: Option<(&str, &NaraFetcher)>,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    only_keys(opts, &["sources", "steps"])?;
    let sources: &[Value] = match opts.get("sources") {
        None => &[],
        Some(Value::Array(sources)) => sources,
        _ => return Err(fail("sources 는 목록이어야 합니다.")),
    };
    let mut resolved = Vec::with_capacity(sources.len());
    for source in sources {
        let source = source
            .as_object()
            .ok_or_else(|| fail("파이프라인 하위 참조가 사전이 아닙니다."))?;
        let kind = source.get("kind").and_then(Value::as_str).unwrap_or("");
        let empty = Map::new();
        let opts = source
            .get("opts")
            .and_then(Value::as_object)
            .unwrap_or(&empty);
        resolved.push(source_from_parts(kind, opts, depth + 1, nara_access)?);
    }
    let steps: &[Value] = match opts.get("steps") {
        None => &[],
        Some(Value::Array(steps)) => steps,
        _ => return Err(fail("steps 는 목록이어야 합니다.")),
    };
    let steps = steps
        .iter()
        .map(|step| {
            step.as_object()
                .cloned()
                .ok_or_else(|| fail("조립 스텝은 사전이어야 합니다."))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Box::new(PipelineSource::new(resolved, steps)))
}

fn nara_source(
    opts: &Map<String, Value>,
    nara_access: Option<(&str, &NaraFetcher)>,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    let Some((service_key, fetcher)) = nara_access.filter(|(key, _)| !key.is_empty()) else {
        return Err(fail(
            "나라장터 데이터셋을 복원하려면 서비스키가 필요합니다 — 풀 항목엔 키가 저장되지 않습니다. 먼저 키를 등록하세요.",
        ));
    };
    only_keys(opts, &["bgn_dt", "end_dt", "num_rows", "page_no"])?;
    let positive = |name: &str, default: u64| -> Result<u64, DataSourceError> {
        match opts.get(name) {
            None => Ok(default),
            Some(value) if !value.is_boolean() => value
                .as_u64()
                .filter(|number| *number > 0)
                .ok_or_else(|| fail(format!("{name}는 1 이상 정수여야 합니다."))),
            _ => Err(fail(format!("{name}는 1 이상 정수여야 합니다."))),
        }
    };
    Ok(Box::new(NaraStdDataSource::new(
        service_key,
        text(opts, "bgn_dt", None)?,
        text(opts, "end_dt", None)?,
        positive("num_rows", 100)?,
        positive("page_no", 1)?,
        fetcher.clone(),
    )))
}
pub fn source_from_pool_item(
    item: &DatasetReference,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    item.validate().map_err(|error| fail(error.to_string()))?;
    source_from_parts(&item.kind, &item.opts, 0, None)
}
/// Whether restoring this reference (including pipeline children) needs the runtime secret.
pub fn requires_nara_key(item: &DatasetReference) -> bool {
    fn contains(kind: &str, opts: &Map<String, Value>, depth: usize) -> bool {
        if kind == "nara" {
            return true;
        }
        if kind != "pipeline" || depth > 32 {
            return false;
        }
        opts.get("sources")
            .and_then(Value::as_array)
            .is_some_and(|sources| {
                sources.iter().any(|source| {
                    let Some(source) = source.as_object() else {
                        return false;
                    };
                    let Some(child) = source.get("opts").and_then(Value::as_object) else {
                        return false;
                    };
                    contains(
                        source.get("kind").and_then(Value::as_str).unwrap_or(""),
                        child,
                        depth + 1,
                    )
                })
            })
    }
    contains(&item.kind, &item.opts, 0)
}
/// Reopen a durable Nara reference (including nested pipeline references) with a key supplied
/// only for this invocation. Neither the key nor fetched records enter DatasetReference.
pub fn source_from_pool_item_with_nara(
    item: &DatasetReference,
    service_key: &str,
    fetcher: &NaraFetcher,
) -> Result<Box<dyn DataSource>, DataSourceError> {
    item.validate().map_err(|error| fail(error.to_string()))?;
    source_from_parts(&item.kind, &item.opts, 0, Some((service_key, fetcher)))
}
/// Reopen the referenced source once and surface the real schema or its read failure.
pub fn fields_for_dataset_reference(
    item: &DatasetReference,
) -> Result<Vec<String>, DataSourceError> {
    source_from_pool_item(item)?.fields()
}

#[cfg(all(test, feature = "native-data"))]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    fn assert_file_extension_policy() {
        assert_eq!(SUPPORTED_DATA_FILE_EXTENSIONS, [".xlsx", ".xlsm", ".csv"]);
        assert_eq!(CONTRACT_LIST_FILE_EXTENSIONS, [".db", ".pclm"]);
        for extension in SUPPORTED_DATA_FILE_EXTENSIONS {
            for extension in [extension.to_owned(), extension.to_uppercase()] {
                let path = format!("data{extension}");
                assert!(source_for_path(Path::new(&path), None, 1).is_ok(), "{path}");
                assert!(!is_contract_list_file(Path::new(&path)), "{path}");
            }
        }
        for extension in CONTRACT_LIST_FILE_EXTENSIONS {
            for extension in [extension.to_owned(), extension.to_uppercase()] {
                let path = format!("data{extension}");
                assert!(is_contract_list_file(Path::new(&path)), "{path}");
                assert!(
                    source_for_path(Path::new(&path), None, 1).is_err(),
                    "{path}"
                );
            }
        }
        for extension in [".xls", ".hwp", ".hwpx", ".txt", ""] {
            let path = format!("data{extension}");
            assert!(
                source_for_path(Path::new(&path), None, 1).is_err(),
                "{path}"
            );
            assert!(!is_contract_list_file(Path::new(&path)), "{path}");
        }
    }

    #[test]
    fn pool_factory_reads_real_sheet_and_recursive_inline_pipeline() {
        assert_file_extension_policy();
        let missing = DatasetReference::new(
            "엑셀",
            "excel",
            json!({"path":"/nope.xlsx"}).as_object().unwrap().clone(),
        )
        .unwrap();
        let mut deferred = source_from_pool_item(&missing).unwrap();
        assert!(deferred.records().is_err());
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/multi_sheet.xlsx");
        let item = DatasetReference::new(
            "sheet",
            "excel",
            serde_json::from_value(json!({"path":path,"sheet":"낙찰현황"})).unwrap(),
        )
        .unwrap();
        assert_eq!(
            fields_for_dataset_reference(&item).unwrap(),
            ["업체명", "낙찰금액", "계약일"]
        );
        let mut selected_sheet = source_for_path(&path, Some("낙찰현황"), 1).unwrap();
        assert_eq!(selected_sheet.records().unwrap().len(), 3);
        assert_eq!(selected_sheet.records().unwrap()[0]["업체명"], "가나상사");
        let mut first_sheet = source_for_path(&path, None, 1).unwrap();
        assert_eq!(first_sheet.fields().unwrap(), ["공고명", "추정가격"]);
        assert_eq!(first_sheet.records().unwrap().len(), 2);
        assert_eq!(crate::data_excel::ambiguous_sheets(&path).unwrap().len(), 2);
        let csv = std::env::temp_dir().join(format!("hwpx-factory-{}.csv", std::process::id()));
        std::fs::write(&csv, "\u{feff}공고명,추정가격\n전산장비,1000\n").unwrap();
        let mut csv_source = source_for_path(&csv, None, 1).unwrap();
        assert_eq!(csv_source.fields().unwrap(), ["공고명", "추정가격"]);
        assert_eq!(csv_source.records().unwrap()[0]["추정가격"], "1000");
        assert!(crate::data_excel::sheet_overview(&csv).unwrap().is_empty());
        assert!(
            crate::data_excel::ambiguous_sheets(&csv)
                .unwrap()
                .is_empty()
        );
        std::fs::remove_file(csv).unwrap();
        assert!(
            source_for_path(Path::new("bad.pdf"), None, 1)
                .err()
                .unwrap()
                .0
                .contains(".pdf")
        );
        let pipeline = DatasetReference::new(
            "pipe",
            "pipeline",
            serde_json::from_value(
                json!({"sources":[{"kind":"inline","opts":{"records":[{"공고명":"장비"}]}}]}),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(fields_for_dataset_reference(&pipeline).unwrap(), ["공고명"]);
        let mut pipeline_source = source_from_pool_item(&pipeline).unwrap();
        assert_eq!(pipeline_source.records().unwrap()[0]["공고명"], "장비");
        let inline = DatasetReference::new(
            "manual",
            "inline",
            serde_json::from_value(json!({"records":[{"공고명":"전산장비","추정가격":"1000"}]}))
                .unwrap(),
        )
        .unwrap();
        let mut inline_source = source_from_pool_item(&inline).unwrap();
        assert_eq!(inline_source.fields().unwrap(), ["공고명", "추정가격"]);
        assert!(inline_source.field_labels().is_empty());
        let mut returned = inline_source.records().unwrap();
        returned[0].insert("공고명".into(), "변조".into());
        assert_eq!(inline_source.records().unwrap()[0]["공고명"], "전산장비");
        let nara = DatasetReference::new(
            "나라",
            "nara",
            serde_json::from_value(json!({
                "bgn_dt":"202606010000", "end_dt":"202606302359", "num_rows":50
            }))
            .unwrap(),
        )
        .unwrap();
        assert!(source_from_pool_item(&nara).is_err());
        let live = include_bytes!("../../../tests/fixtures/nara_std_response.json").to_vec();
        let fetcher: NaraFetcher = std::sync::Arc::new(move |url| {
            assert!(url.contains("ServiceKey=DUMMY"), "{url}");
            assert!(url.contains("numOfRows=50"), "{url}");
            Ok(live.clone())
        });
        assert_eq!(
            source_from_pool_item_with_nara(&nara, "DUMMY", &fetcher)
                .unwrap()
                .records()
                .unwrap()
                .len(),
            2
        );
        let nested = DatasetReference::new(
            "조립",
            "pipeline",
            serde_json::from_value(json!({
                "sources":[{"kind":"nara","opts":nara.opts}]
            }))
            .unwrap(),
        )
        .unwrap();
        assert_eq!(
            source_from_pool_item_with_nara(&nested, "DUMMY", &fetcher)
                .unwrap()
                .records()
                .unwrap()
                .len(),
            2
        );
        assert!(requires_nara_key(&nested));
        assert!(!requires_nara_key(&pipeline));
        assert!(
            source_from_pool_item(&nested)
                .err()
                .unwrap()
                .0
                .contains("서비스키")
        );
        let restored = source_from_pool_item_with_nara(&nested, "DUMMY", &fetcher).unwrap();
        assert_eq!(restored.field_labels()["bidNtceNm"], "공고명");
        assert_eq!(restored.field_labels()["presmptPrce"], "추정가격");
        assert!(source_for_path(Path::new("bad.pdf"), None, 1).is_err());
        assert_eq!(
            source_for_binding("", "", Some(1), "")
                .err()
                .unwrap()
                .to_string(),
            "데이터 참조에 경로가 없습니다."
        );
        assert_eq!(
            source_for_binding("file.xlsx", "", Some(1), "unknown")
                .err()
                .unwrap()
                .to_string(),
            "'unknown' 데이터 결속은 파일로 복원할 수 없습니다."
        );
        assert_malformed_references_are_refused();
    }

    fn assert_malformed_references_are_refused() {
        for (kind, opts, message) in [
            (
                "excel",
                json!({"path":"input.csv","extra":1}),
                "미지원 데이터 소스 옵션",
            ),
            ("excel", json!({}), "path 가 없습니다"),
            ("excel", json!({"path":3}), "path 는 문자열"),
            (
                "excel",
                json!({"path":"input.csv","header_row":true}),
                "header_row는 1 이상의 정수",
            ),
            (
                "excel",
                json!({"path":"input.csv","header_row":0}),
                "header_row는 1 이상의 정수",
            ),
            ("inline", json!({"records":{}}), "records 는 목록"),
            ("inline", json!({"records":[1]}), "record 는 사전"),
            (
                "inline",
                json!({"records":[{"id":1}]}),
                "record 값은 문자열",
            ),
            ("pipeline", json!({"sources":{}}), "sources 는 목록"),
            ("pipeline", json!({"sources":[null]}), "하위 참조가 사전"),
            (
                "pipeline",
                json!({"sources":[{"kind":"ghost"}]}),
                "알 수 없는 데이터 소스 종류",
            ),
            ("pipeline", json!({"steps":{}}), "steps 는 목록"),
            ("pipeline", json!({"steps":[1]}), "조립 스텝은 사전"),
        ] {
            let item =
                DatasetReference::new("잘못된 참조", kind, serde_json::from_value(opts).unwrap())
                    .unwrap();
            let error = source_from_pool_item(&item)
                .err()
                .expect("invalid reference accepted")
                .0;
            assert!(error.contains(message), "{kind}: {error}");
        }
        let mut nested = json!({"kind":"inline","opts":{"records":[]}});
        for _ in 0..34 {
            nested = json!({"kind":"pipeline","opts":{"sources":[nested]}});
        }
        let item = DatasetReference::new(
            "중첩",
            "pipeline",
            nested["opts"].as_object().unwrap().clone(),
        )
        .unwrap();
        assert!(
            source_from_pool_item(&item)
                .err()
                .unwrap()
                .0
                .contains("중첩이 너무 깊습니다")
        );
        assert!(!requires_nara_key(&item));
    }
}
