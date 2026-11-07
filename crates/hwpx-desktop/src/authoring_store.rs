//! Durable authoring documents, trial cases, and last workspace positions.

use crate::atomic_file::{write_bytes_atomic, write_bytes_atomic_exclusive};
use crate::directory_lock::DirectoryLock;
use crate::single_instance::{normalize_windows_path, resolved_home};
use hwpx_filler::python_casefold::python_casefold;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub const WORKSPACE_INVALID: &str = "작업 위치 기록의 내용이 올바르지 않습니다.";

#[derive(Debug)]
pub enum AuthoringStoreError {
    Io(io::Error),
    Invalid(String),
    ExternalChanged { fingerprint: Option<String> },
}
impl fmt::Display for AuthoringStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::Invalid(message) => f.write_str(message),
            Self::ExternalChanged { .. } => f.write_str("파일이 편집 중 외부에서 변경되었습니다."),
        }
    }
}
impl std::error::Error for AuthoringStoreError {}
impl From<io::Error> for AuthoringStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}
fn invalid(message: impl Into<String>) -> AuthoringStoreError {
    AuthoringStoreError::Invalid(message.into())
}
fn digest(data: &[u8]) -> String {
    Sha256::digest(data)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
fn read_json(path: &Path) -> Result<Value, AuthoringStoreError> {
    let bytes = fs::read(path)?;
    serde_json::from_slice(&bytes).map_err(|error| invalid(error.to_string()))
}
fn json_bytes(value: &Value, pretty: bool) -> Result<Vec<u8>, AuthoringStoreError> {
    if pretty {
        serde_json::to_vec_pretty(value)
    } else {
        serde_json::to_vec(value)
    }
    .map_err(|error| invalid(error.to_string()))
}

#[derive(Clone, Debug)]
pub struct AuthoringStore {
    directory: PathBuf,
}
impl AuthoringStore {
    pub fn new(directory: PathBuf) -> Self {
        Self { directory }
    }
    pub fn directory(&self) -> &Path {
        &self.directory
    }
    pub fn key(path: &Path) -> Result<String, AuthoringStoreError> {
        let resolved = normalize_windows_path(&resolved_home(path))?;
        Ok(digest(python_casefold(&resolved).as_bytes()))
    }
    fn path(&self, kind: &str, key: &str) -> PathBuf {
        self.directory.join(kind).join(format!("{key}.json"))
    }
    pub fn read_document(&self, path: &Path) -> Result<(Vec<u8>, String), AuthoringStoreError> {
        let bytes = fs::read(path)?;
        let fingerprint = digest(&bytes);
        Ok((bytes, fingerprint))
    }
    pub fn current_fingerprint(&self, path: &Path) -> Result<Option<String>, AuthoringStoreError> {
        if !path.is_file() {
            return Ok(None);
        }
        Ok(Some(digest(&fs::read(path)?)))
    }
    pub fn save_document(
        &self,
        path: &Path,
        bytes: &[u8],
        expected: Option<&str>,
    ) -> Result<String, AuthoringStoreError> {
        let parent = path.parent().unwrap_or(Path::new("."));
        let lock = DirectoryLock::new(parent)?;
        lock.with(|| {
            let actual = self.current_fingerprint(path)?;
            if actual.as_deref() != expected {
                return Err(AuthoringStoreError::ExternalChanged {
                    fingerprint: actual,
                });
            }
            fs::create_dir_all(parent)?;
            if expected.is_none() {
                write_bytes_atomic_exclusive(path, bytes)?;
            } else {
                write_bytes_atomic(path, bytes)?;
            }
            Ok(digest(bytes))
        })
    }
    pub fn read_cases(&self, key: &str) -> Result<Vec<Value>, AuthoringStoreError> {
        let target = self.path("cases", key);
        if !target.is_file() {
            return Ok(Vec::new());
        }
        Self::import_cases(&target)
    }
    pub fn write_cases(&self, key: &str, cases: &[Value]) -> Result<(), AuthoringStoreError> {
        let target = self.path("cases", key);
        fs::create_dir_all(target.parent().unwrap_or(Path::new(".")))?;
        write_bytes_atomic(
            &target,
            &json_bytes(&json!({"version":1,"cases":cases}), false)?,
        )?;
        Ok(())
    }
    pub fn read_workspace(&self, key: &str) -> Result<Option<Value>, AuthoringStoreError> {
        let target = self.path("workspace", key);
        if !target.is_file() {
            return Ok(None);
        }
        let record = read_json(&target)?;
        if !record.is_object() || record.get("version").and_then(Value::as_i64) != Some(1) {
            return Err(invalid("지원하지 않는 작업 위치 기록 형식입니다."));
        }
        if !record.get("fingerprint").is_some_and(Value::is_string)
            || !record.get("mode").is_some_and(Value::is_string)
            || !record
                .get("selection")
                .is_none_or(|value| value.is_null() || value.is_object())
        {
            return Err(invalid(WORKSPACE_INVALID));
        }
        Ok(Some(record))
    }
    pub fn write_workspace(
        &self,
        key: &str,
        fingerprint: &str,
        mode: &str,
        selection: Option<&Value>,
    ) -> Result<(), AuthoringStoreError> {
        let target = self.path("workspace", key);
        fs::create_dir_all(target.parent().unwrap_or(Path::new(".")))?;
        write_bytes_atomic(
            &target,
            &json_bytes(
                &json!({"version":1,"fingerprint":fingerprint,
                "mode":mode,"selection":selection}),
                false,
            )?,
        )?;
        Ok(())
    }
    pub fn export_cases(path: &Path, cases: &[Value]) -> Result<(), AuthoringStoreError> {
        write_bytes_atomic_exclusive(
            path,
            &json_bytes(&json!({"version":1,"cases":cases}), true)?,
        )?;
        Ok(())
    }
    pub fn import_cases(path: &Path) -> Result<Vec<Value>, AuthoringStoreError> {
        let record = read_json(path)?;
        if !record.is_object()
            || record.get("version").and_then(Value::as_i64) != Some(1)
            || !record.get("cases").is_some_and(Value::is_array)
        {
            return Err(invalid("지원하지 않는 시험 케이스 형식입니다."));
        }
        Ok(record["cases"].as_array().expect("validated").clone())
    }
    pub fn export_result(path: &Path, bytes: &[u8]) -> Result<(), AuthoringStoreError> {
        write_bytes_atomic_exclusive(path, bytes)?;
        Ok(())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{AuthoringStore, AuthoringStoreError, WORKSPACE_INVALID};
    use serde_json::json;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn document_cas_and_workspace_shape_preserve_observed_state() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../target/authoring-store-tests")
            .join(format!("{}-{stamp}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let store = AuthoringStore::new(root.join("state"));
        let document = root.join("document.txt");
        let first = store.save_document(&document, b"first", None).unwrap();
        fs::write(&document, b"external").unwrap();
        let error = store
            .save_document(&document, b"second", Some(&first))
            .unwrap_err();
        assert!(matches!(error, AuthoringStoreError::ExternalChanged { .. }));
        assert_eq!(fs::read(&document).unwrap(), b"external");

        store
            .write_workspace("item", &first, "text", Some(&json!({"start": 1})))
            .unwrap();
        assert_eq!(
            store.read_workspace("item").unwrap().unwrap()["selection"]["start"],
            1
        );
        fs::write(
            root.join("state/workspace/item.json"),
            br#"{"version":1,"fingerprint":"x","mode":"text","selection":42}"#,
        )
        .unwrap();
        assert_eq!(
            store.read_workspace("item").unwrap_err().to_string(),
            WORKSPACE_INVALID
        );
        let cases = vec![json!({"name":"검토","values":{"이름":"홍길동"}})];
        assert!(store.read_cases("item").unwrap().is_empty());
        store.write_cases("item", &cases).unwrap();
        assert_eq!(store.read_cases("item").unwrap(), cases);
        let exported = root.join("cases.json");
        AuthoringStore::export_cases(&exported, &cases).unwrap();
        assert_eq!(AuthoringStore::import_cases(&exported).unwrap(), cases);
        assert!(AuthoringStore::export_cases(&exported, &[]).is_err());
        assert_eq!(AuthoringStore::import_cases(&exported).unwrap(), cases);
        fs::write(&exported, br#"{"version":2,"cases":[]}"#).unwrap();
        assert!(
            AuthoringStore::import_cases(&exported)
                .unwrap_err()
                .to_string()
                .contains("지원하지 않는")
        );
        fs::write(root.join("state/cases/item.json"), br#"{"version":1}"#).unwrap();
        assert!(store.read_cases("item").is_err());
        for invalid in [
            br#"{"version":2,"fingerprint":"f","mode":"text","selection":null}"#.as_slice(),
            br#"[]"#,
            br#"{"version":1,"fingerprint":3,"mode":"text","selection":null}"#,
            br#"{"version":1,"fingerprint":"f","mode":null,"selection":null}"#,
            br#"{"version":1,"fingerprint":"f","mode":"text","selection":[1]}"#,
            br#"{"#,
        ] {
            fs::write(root.join("state/workspace/item.json"), invalid).unwrap();
            assert!(store.read_workspace("item").is_err());
        }
        let result = root.join("result.hwpx");
        fs::write(&result, b"previous").unwrap();
        assert!(AuthoringStore::export_result(&result, b"new").is_err());
        assert_eq!(fs::read(&result).unwrap(), b"previous");
        fs::remove_dir_all(root).unwrap();
    }
}
