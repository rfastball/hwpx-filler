//! Read-only SQLite contract-list source. Sheets are the database's own views and tables.

use crate::data_source::{DataSource, DataSourceError, Record};
use crate::text_render::python_repr;
use indexmap::IndexMap;
use rusqlite::{Connection, OpenFlags, types::ValueRef};
use serde_json::Value;
use std::path::{Path, PathBuf};

fn fail(message: impl Into<String>) -> DataSourceError {
    DataSourceError(message.into())
}
fn db_path(path: impl Into<PathBuf>) -> Result<PathBuf, DataSourceError> {
    let path = path.into();
    if path.as_os_str().is_empty() {
        return Err(fail("데이터 참조에 경로가 없습니다."));
    }
    Ok(path)
}
fn connect(path: &Path) -> Result<Connection, DataSourceError> {
    if !path.exists() {
        return Err(fail(format!(
            "pclm 자료를 찾지 못했습니다: {}",
            path.display()
        )));
    }
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|err| {
        fail(format!(
            "pclm 자료를 열지 못했습니다: {} ({err})",
            path.display()
        ))
    })
}
fn sheets_of(connection: &Connection, db: &Path) -> Result<Vec<String>, DataSourceError> {
    let mut statement = connection
        .prepare(
            "SELECT type, name FROM sqlite_master WHERE type IN ('view', 'table') ORDER BY rowid",
        )
        .map_err(|err| {
            fail(format!(
                "pclm 자료를 열지 못했습니다: {} ({err})",
                db.display()
            ))
        })?;
    let rows = statement
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })
        .map_err(|err| {
            fail(format!(
                "pclm 자료를 열지 못했습니다: {} ({err})",
                db.display()
            ))
        })?;
    let mut views = Vec::new();
    let mut tables = Vec::new();
    for row in rows {
        let (kind, name) = row.map_err(|err| {
            fail(format!(
                "pclm 자료를 열지 못했습니다: {} ({err})",
                db.display()
            ))
        })?;
        if name.to_ascii_lowercase().starts_with("sqlite_") {
            continue;
        }
        if kind == "view" {
            views.push(name);
        } else {
            tables.push(name);
        }
    }
    views.extend(tables);
    Ok(views)
}
pub fn list_sqlite_sheets(db: impl Into<PathBuf>) -> Result<Vec<String>, DataSourceError> {
    let path = db_path(db)?;
    let connection = connect(&path)?;
    sheets_of(&connection, &path)
}
pub fn registered_workfile_sheets(
    path: impl Into<PathBuf>,
    dataset_id: &str,
) -> Result<Vec<String>, DataSourceError> {
    let db = db_path(path)?;
    let connection = connect(&db)?;
    let identity = connection
        .query_row(
            "SELECT role, dataset_id FROM pclm_file WHERE singleton = 1",
            [],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
        )
        .map_err(|err| {
            fail(format!(
                "pclm 자료를 열지 못했습니다: {} ({err})",
                db.display()
            ))
        })?;
    let sheets = sheets_of(&connection, &db)?;
    let selected = ["v_통합", "v_접수", "v_공고", "v_계약"];
    if identity != ("work".into(), dataset_id.into())
        || selected
            .iter()
            .any(|name| !sheets.iter().any(|sheet| sheet == name))
    {
        return Err(fail(format!(
            "pclm 자료를 열지 못했습니다: {}",
            db.display()
        )));
    }
    Ok(selected.iter().map(|item| (*item).into()).collect())
}
fn quote(name: &str) -> String {
    format!("\"{}\"", name.replace('"', "\"\""))
}
fn bytes_repr(bytes: &[u8]) -> String {
    let quote = if bytes.contains(&b'\'') && !bytes.contains(&b'"') {
        '"'
    } else {
        '\''
    };
    let mut text = format!("b{quote}");
    for byte in bytes {
        match byte {
            b'\\' => text.push_str("\\\\"),
            byte if char::from(*byte) == quote => {
                text.push('\\');
                text.push(quote);
            }
            10 => text.push_str("\\n"),
            13 => text.push_str("\\r"),
            9 => text.push_str("\\t"),
            32..=126 => text.push(char::from(*byte)),
            _ => text.push_str(&format!("\\x{byte:02x}")),
        }
    }
    text.push(quote);
    text
}
fn value_text(value: ValueRef<'_>) -> Result<String, DataSourceError> {
    Ok(match value {
        ValueRef::Null => String::new(),
        ValueRef::Integer(value) => value.to_string(),
        ValueRef::Real(value) if value.is_nan() => "nan".into(),
        ValueRef::Real(value) if value == f64::INFINITY => "inf".into(),
        ValueRef::Real(value) if value == f64::NEG_INFINITY => "-inf".into(),
        ValueRef::Real(value) => python_repr(&Value::from(value)),
        ValueRef::Text(value) => std::str::from_utf8(value)
            .map_err(|err| fail(format!("SQLite TEXT UTF-8 오류: {err}")))?
            .into(),
        ValueRef::Blob(value) => bytes_repr(value),
    })
}

pub struct PclmDataSource {
    pub db: PathBuf,
    pub view: String,
    fields: Vec<String>,
    records: Vec<Record>,
    loaded: bool,
}
impl PclmDataSource {
    pub fn new(db: impl Into<PathBuf>, view: impl Into<String>) -> Result<Self, DataSourceError> {
        Ok(Self {
            db: db_path(db)?,
            view: view.into(),
            fields: Vec::new(),
            records: Vec::new(),
            loaded: false,
        })
    }
    fn load(&mut self) -> Result<(), DataSourceError> {
        if self.loaded {
            return Ok(());
        }
        let connection = connect(&self.db)?;
        let sheets = sheets_of(&connection, &self.db)?;
        if !sheets.contains(&self.view) {
            return Err(fail(format!(
                "pclm 이 약속한 뷰가 아닙니다: {}. 쓸 수 있는 뷰: {}",
                python_repr(&Value::String(self.view.clone())),
                sheets.join(", ")
            )));
        }
        let mut statement = connection.prepare(&format!("SELECT * FROM {}",quote(&self.view)))
            .map_err(|err| fail(format!("pclm 뷰를 읽지 못했습니다: {} ({err}). 계약 목록 앱을 한 번 열면 뷰가 다시 지어집니다.",self.view)))?;
        let fields: Vec<String> = statement
            .column_names()
            .map(|name| (*name).to_owned())
            .collect();
        let mut records = Vec::new();
        let mut cursor = statement.query([])
            .map_err(|err| fail(format!("pclm 뷰를 읽지 못했습니다: {} ({err}). 계약 목록 앱을 한 번 열면 뷰가 다시 지어집니다.",self.view)))?;
        while let Some(row) = cursor.next().map_err(|err| fail(format!("pclm 뷰를 읽지 못했습니다: {} ({err}). 계약 목록 앱을 한 번 열면 뷰가 다시 지어집니다.",self.view)))? {
            let mut record = Record::new();
            for (i,name) in fields.iter().enumerate() {
                let value = row.get_ref(i).map_err(|err| fail(err.to_string()))?;
                record.insert(name.clone(),value_text(value).map_err(|err| fail(format!(
                    "pclm 뷰를 읽지 못했습니다: {} ({}). 계약 목록 앱을 한 번 열면 뷰가 다시 지어집니다.",self.view,err.0
                )))?);
            }
            records.push(record);
        }
        self.fields = fields;
        self.records = records;
        self.loaded = true;
        Ok(())
    }
}
impl DataSource for PclmDataSource {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
        self.load()?;
        Ok(self.records.clone())
    }
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
        self.load()?;
        Ok(self.fields.clone())
    }
    fn field_labels(&self) -> IndexMap<String, String> {
        IndexMap::new()
    }
    fn source_pointer(&self) -> Option<String> {
        Some(format!("sqlite:{}#{}", self.db.display(), self.view))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn database_sheets_are_read_only_and_selected_by_actual_name() {
        let path =
            std::env::temp_dir().join(format!("hwpx-filler-pclm-{}.pclm", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; PRAGMA application_id=1346587725;
            CREATE TABLE 계약 (번호 INTEGER PRIMARY KEY AUTOINCREMENT, 상태 TEXT);
            INSERT INTO 계약 VALUES (1, NULL); CREATE VIEW \"v_\"\"통합\" AS SELECT * FROM 계약;
            CREATE TABLE 공고 (번호 TEXT PRIMARY KEY, 건명 TEXT);
            CREATE VIEW v_공고 AS SELECT * FROM 공고;").unwrap();
        assert!(PathBuf::from(format!("{}-wal", path.display())).exists());
        let sheets = list_sqlite_sheets(&path).unwrap();
        assert_eq!(sheets, vec!["v_\"통합", "v_공고", "계약", "공고"]);
        for sheet in &sheets {
            assert!(
                !PclmDataSource::new(&path, sheet)
                    .unwrap()
                    .fields()
                    .unwrap()
                    .is_empty()
            );
        }
        assert!(
            PclmDataSource::new(&path, "공고")
                .unwrap()
                .records()
                .unwrap()
                .is_empty()
        );
        let connection = connect(&path).unwrap();
        assert!(
            connection
                .execute("INSERT INTO 계약 VALUES (2,'변조')", [])
                .is_err()
        );
        drop(connection);
        let mut source = PclmDataSource::new(&path, "v_\"통합").unwrap();
        assert_eq!(source.fields().unwrap(), vec!["번호", "상태"]);
        assert_eq!(source.records().unwrap()[0]["상태"], "");
        assert!(source.field_labels().is_empty());
        assert_eq!(
            source.source_pointer(),
            Some(format!("sqlite:{}#v_\"통합", path.display()))
        );
        source.records().unwrap()[0].insert("상태".into(), "변조".into());
        source.fields().unwrap().push("변조".into());
        assert_eq!(source.records().unwrap()[0]["상태"], "");
        assert_eq!(source.fields().unwrap(), ["번호", "상태"]);
        for invalid in ["sqlite_master", "", "없는시트", "v_\"통합; DROP TABLE 계약"] {
            let message = PclmDataSource::new(&path, invalid)
                .unwrap()
                .records()
                .unwrap_err()
                .0;
            assert!(
                message.contains("약속한 뷰") && message.contains("계약"),
                "{message}"
            );
        }
        writable
            .execute("INSERT INTO 계약 VALUES (2, X'27')", [])
            .unwrap();
        assert_eq!(
            source.records().unwrap().len(),
            1,
            "loaded sources retain their snapshot"
        );
        let mut source = PclmDataSource::new(&path, "v_\"통합").unwrap();
        assert_eq!(source.records().unwrap()[1]["상태"], "b\"'\"");
        assert_factory_restore(&path);
        writable
            .execute_batch("CREATE VIEW 깨진면 AS SELECT * FROM 사라진표;")
            .unwrap();
        assert!(
            PclmDataSource::new(&path, "깨진면")
                .unwrap()
                .records()
                .unwrap_err()
                .0
                .contains("읽지 못했습니다")
        );
        writable
            .execute("INSERT INTO 계약 VALUES (3, CAST(X'FF' AS TEXT))", [])
            .unwrap();
        drop(writable);
        let mut source = PclmDataSource::new(&path, "v_\"통합").unwrap();
        let failure = source.records().unwrap_err().0;
        assert!(failure.contains("pclm 뷰를 읽지 못했습니다: v_\"통합"));
        assert!(failure.contains("계약 목록 앱을 한 번 열면"));
        assert!(source.fields().is_err());
        let writable = Connection::open(&path).unwrap();
        writable
            .execute("DELETE FROM 계약 WHERE 번호 = 3", [])
            .unwrap();
        drop(writable);
        let recovered = source.records().unwrap();
        assert_eq!(
            recovered.len(),
            2,
            "failed reads must not retain partial rows"
        );
        assert_eq!(recovered[0]["번호"], "1");
        assert_eq!(recovered[1]["번호"], "2");
        std::fs::remove_file(&path).unwrap();
        assert!(
            list_sqlite_sheets(&path)
                .unwrap_err()
                .0
                .contains("찾지 못했습니다")
        );
        assert!(
            PclmDataSource::new(&path, "계약")
                .unwrap()
                .records()
                .unwrap_err()
                .0
                .contains("찾지 못했습니다")
        );
        assert!(!path.exists());
        assert!(
            list_sqlite_sheets("")
                .unwrap_err()
                .0
                .contains("경로가 없습니다")
        );
        assert!(
            PclmDataSource::new("", "계약")
                .err()
                .unwrap()
                .0
                .contains("경로가 없습니다")
        );
        std::fs::write(&path, b"this is not a sqlite database").unwrap();
        assert!(
            list_sqlite_sheets(&path)
                .unwrap_err()
                .0
                .contains("열지 못했습니다")
        );
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn shared_fixture_writes_a_registered_workfile_shape() {
        use crate::pclm_fixture::{APPLICATION_ID, PclmFixture, WORK_VIEWS};
        let path = std::env::temp_dir().join(format!(
            "hwpx-filler-pclm-fixture-{}.pclm",
            std::process::id()
        ));
        PclmFixture::work("source-id")
            .view(
                "v_통합",
                &["공고명", "금\"액"],
                &[&["가", "1,000"], &["나", ""]],
            )
            .view("u_추가", &["항목"], &[])
            .write(&path);
        assert_eq!(
            registered_workfile_sheets(&path, "source-id").unwrap(),
            WORK_VIEWS
        );
        assert!(registered_workfile_sheets(&path, "other-id").is_err());
        let sheets = list_sqlite_sheets(&path).unwrap();
        assert_eq!(
            sheets[..5],
            ["v_통합", "v_접수", "v_공고", "v_계약", "u_추가"]
        );
        let mut source = PclmDataSource::new(&path, "v_통합").unwrap();
        assert_eq!(source.fields().unwrap(), ["공고명", "금\"액"]);
        let records = source.records().unwrap();
        assert_eq!(records[0]["금\"액"], "1,000");
        assert_eq!(records[1]["금\"액"], "");
        let mut default = PclmDataSource::new(&path, "v_계약").unwrap();
        assert_eq!(default.records().unwrap()[0]["항목"], "1");
        let id: u32 = connect(&path)
            .unwrap()
            .query_row("PRAGMA application_id", [], |row| row.get(0))
            .unwrap();
        assert_eq!(id, APPLICATION_ID);
        std::fs::remove_file(path).unwrap();
    }

    fn assert_factory_restore(path: &Path) {
        use crate::data_factory::{source_for_binding, source_from_pool_item};
        use crate::dataset_reference::DatasetReference;
        use serde_json::json;
        for view in ["v_\"통합", "계약"] {
            let item = DatasetReference::new(
                "목록",
                "pclm",
                serde_json::from_value(json!({"db":path,"view":view})).unwrap(),
            )
            .unwrap();
            let mut restored = source_from_pool_item(&item).unwrap();
            assert_eq!(restored.fields().unwrap(), ["번호", "상태"]);
            assert_eq!(restored.records().unwrap().len(), 2);
            assert_eq!(
                restored.source_pointer(),
                Some(format!("sqlite:{}#{view}", path.display()))
            );
            assert_eq!(
                source_for_binding(path.to_str().unwrap(), view, Some(0), "pclm")
                    .unwrap()
                    .records()
                    .unwrap(),
                restored.records().unwrap()
            );
        }
        for opts in [json!({"view":"계약"}), json!({"db":"","view":"계약"})] {
            let item =
                DatasetReference::new("빈 참조", "pclm", serde_json::from_value(opts).unwrap())
                    .unwrap();
            assert!(
                source_from_pool_item(&item)
                    .err()
                    .unwrap()
                    .0
                    .contains("경로가 없습니다")
            );
        }
    }

    #[test]
    fn directory_in_place_of_a_database_is_refused_as_unopenable() {
        let dir = std::env::temp_dir().join(format!("hwpx-filler-pclm-dir-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let opened = format!("pclm 자료를 열지 못했습니다: {} (", dir.display());
        let listed = list_sqlite_sheets(&dir).unwrap_err().0;
        assert!(listed.starts_with(&opened), "{listed}");
        let read = PclmDataSource::new(&dir, "계약")
            .unwrap()
            .records()
            .unwrap_err()
            .0;
        assert!(read.starts_with(&opened), "{read}");
        std::fs::remove_dir(dir).unwrap();
    }

    #[test]
    fn blob_values_read_as_python_bytes_literals() {
        let path =
            std::env::temp_dir().join(format!("hwpx-filler-pclm-blob-{}.pclm", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable
            .execute_batch(
                "CREATE TABLE 첨부 (번호 INTEGER, 값 BLOB);
            INSERT INTO 첨부 VALUES (1, X'5C0A0D09FF41'), (2, X'2722'), (3, X'22'), (4, X'');",
            )
            .unwrap();
        drop(writable);
        let values: Vec<String> = PclmDataSource::new(&path, "첨부")
            .unwrap()
            .records()
            .unwrap()
            .into_iter()
            .map(|record| record["값"].clone())
            .collect();
        assert_eq!(values, [r"b'\\\n\r\t\xffA'", r#"b'\'"'"#, r#"b'"'"#, "b''"]);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn real_values_read_as_python_floats_including_infinities() {
        let path =
            std::env::temp_dir().join(format!("hwpx-filler-pclm-real-{}.pclm", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable.execute_batch("CREATE VIEW 금액 AS SELECT 1.5 AS 가, 2.0 AS 나, 1e20 AS 다, 9e999 AS 라, -9e999 AS 마;").unwrap();
        drop(writable);
        let record = PclmDataSource::new(&path, "금액")
            .unwrap()
            .records()
            .unwrap()
            .remove(0);
        assert_eq!(
            record.values().map(String::as_str).collect::<Vec<_>>(),
            ["1.5", "2.0", "1e+20", "inf", "-inf"]
        );
        std::fs::remove_file(path).unwrap();
    }

    const WORKFILE_VIEWS: &str = "CREATE TABLE 원본 (번호 TEXT);
        CREATE VIEW v_계약 AS SELECT * FROM 원본; CREATE VIEW v_공고 AS SELECT * FROM 원본;
        CREATE VIEW v_접수 AS SELECT * FROM 원본; CREATE VIEW v_기타 AS SELECT * FROM 원본;";

    #[test]
    fn workfile_with_its_identity_and_four_views_lists_them_in_fixed_order() {
        let path =
            std::env::temp_dir().join(format!("hwpx-filler-pclm-work-{}.pclm", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable.execute_batch(WORKFILE_VIEWS).unwrap();
        writable
            .execute_batch(
                "CREATE TABLE pclm_file (singleton INTEGER, role TEXT, dataset_id TEXT);
            INSERT INTO pclm_file VALUES (1, 'work', 'ds-1');
            CREATE VIEW v_통합 AS SELECT * FROM 원본;",
            )
            .unwrap();
        drop(writable);
        assert_eq!(
            registered_workfile_sheets(&path, "ds-1").unwrap(),
            ["v_통합", "v_접수", "v_공고", "v_계약"]
        );
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn workfile_missing_a_required_view_is_refused() {
        let path = std::env::temp_dir().join(format!(
            "hwpx-filler-pclm-noview-{}.pclm",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable.execute_batch(WORKFILE_VIEWS).unwrap();
        writable
            .execute_batch(
                "CREATE TABLE pclm_file (singleton INTEGER, role TEXT, dataset_id TEXT);
            INSERT INTO pclm_file VALUES (1, 'work', 'ds-1');",
            )
            .unwrap();
        drop(writable);
        assert_eq!(
            registered_workfile_sheets(&path, "ds-1").unwrap_err().0,
            format!("pclm 자료를 열지 못했습니다: {}", path.display())
        );
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn workfile_identity_of_another_dataset_or_role_is_refused() {
        let path = std::env::temp_dir().join(format!(
            "hwpx-filler-pclm-other-{}.pclm",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable.execute_batch(WORKFILE_VIEWS).unwrap();
        writable
            .execute_batch(
                "CREATE TABLE pclm_file (singleton INTEGER, role TEXT, dataset_id TEXT);
            INSERT INTO pclm_file VALUES (1, 'work', 'ds-1');
            CREATE VIEW v_통합 AS SELECT * FROM 원본;",
            )
            .unwrap();
        let refused = format!("pclm 자료를 열지 못했습니다: {}", path.display());
        assert_eq!(
            registered_workfile_sheets(&path, "ds-2").unwrap_err().0,
            refused
        );
        writable
            .execute("UPDATE pclm_file SET role = 'list'", [])
            .unwrap();
        drop(writable);
        assert_eq!(
            registered_workfile_sheets(&path, "ds-1").unwrap_err().0,
            refused
        );
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn workfile_without_a_readable_identity_row_is_refused() {
        let path =
            std::env::temp_dir().join(format!("hwpx-filler-pclm-noid-{}.pclm", std::process::id()));
        let _ = std::fs::remove_file(&path);
        let writable = Connection::open(&path).unwrap();
        writable.execute_batch(WORKFILE_VIEWS).unwrap();
        writable
            .execute_batch("CREATE VIEW v_통합 AS SELECT * FROM 원본;")
            .unwrap();
        let opened = format!("pclm 자료를 열지 못했습니다: {} (", path.display());
        for setup in [
            "",
            "CREATE TABLE pclm_file (singleton INTEGER, role TEXT, dataset_id TEXT);",
            "INSERT INTO pclm_file VALUES (1, 'work', NULL);",
        ] {
            writable.execute_batch(setup).unwrap();
            let refused = registered_workfile_sheets(&path, "ds-1").unwrap_err().0;
            assert!(refused.starts_with(&opened), "{refused}");
        }
        drop(writable);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn workfile_lookup_without_a_file_is_refused() {
        let path =
            std::env::temp_dir().join(format!("hwpx-filler-pclm-gone-{}.pclm", std::process::id()));
        let _ = std::fs::remove_file(&path);
        assert_eq!(
            registered_workfile_sheets("", "ds-1").unwrap_err().0,
            "데이터 참조에 경로가 없습니다."
        );
        assert_eq!(
            registered_workfile_sheets(&path, "ds-1").unwrap_err().0,
            format!("pclm 자료를 찾지 못했습니다: {}", path.display())
        );
    }
}
