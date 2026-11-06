//! Durable workspace identity and per-Work configuration CAS over checked envelopes.

use crate::atomic_file::{write_bytes_atomic, write_bytes_atomic_exclusive};
use crate::directory_lock::DirectoryLock;
use crate::single_instance::resolved_home;
use hwpx_filler::execution_structure::content_digest;
use hwpx_filler::stored_work_configuration::{
    STORE_SCHEMA_VERSION, StoredWorkConfiguration, decode_stored, encode_stored,
};
use serde_json::{Map, Value};
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

const WORKSPACE_SCHEMA_VERSION: &str = "workspace-metadata-v1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConfigurationStoreErrorKind {
    InvalidId,
    NotFound,
    Exists,
    Conflict,
    Corrupt,
    UnsupportedSchema,
    Io,
}
#[derive(Debug)]
pub struct ConfigurationStoreError {
    pub kind: ConfigurationStoreErrorKind,
    pub detail: String,
}
impl fmt::Display for ConfigurationStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for ConfigurationStoreError {}
impl From<io::Error> for ConfigurationStoreError {
    fn from(error: io::Error) -> Self {
        Self {
            kind: ConfigurationStoreErrorKind::Io,
            detail: error.to_string(),
        }
    }
}
fn fail(kind: ConfigurationStoreErrorKind, detail: impl Into<String>) -> ConfigurationStoreError {
    ConfigurationStoreError {
        kind,
        detail: detail.into(),
    }
}
fn work_path(root: &Path, work_id: &str) -> Result<PathBuf, ConfigurationStoreError> {
    if work_id.is_empty()
        || !work_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    {
        return Err(fail(
            ConfigurationStoreErrorKind::InvalidId,
            format!("저장할 수 없는 work_id {work_id:?}"),
        ));
    }
    Ok(root.join(format!("{work_id}.json")))
}
fn read_content(path: &Path) -> Result<Value, ConfigurationStoreError> {
    let bytes = fs::read(path).map_err(|error| {
        if error.kind() == io::ErrorKind::NotFound {
            fail(
                ConfigurationStoreErrorKind::NotFound,
                format!("{} 없음", path.display()),
            )
        } else {
            error.into()
        }
    })?;
    let envelope: Value = serde_json::from_slice(&bytes).map_err(|_| {
        fail(
            ConfigurationStoreErrorKind::Corrupt,
            format!("{} JSON 파싱 실패(손상)", path.display()),
        )
    })?;
    let object = envelope
        .as_object()
        .ok_or_else(|| fail(ConfigurationStoreErrorKind::Corrupt, "envelope 형식 손상"))?;
    let content = object
        .get("content")
        .filter(|value| value.is_object())
        .ok_or_else(|| fail(ConfigurationStoreErrorKind::Corrupt, "content 형식 손상"))?;
    if object.get("digest").and_then(Value::as_str) != Some(content_digest(content).as_str()) {
        return Err(fail(ConfigurationStoreErrorKind::Corrupt, "digest 손상"));
    }
    Ok(content.clone())
}
fn enveloped_bytes(content: Value) -> Result<Vec<u8>, ConfigurationStoreError> {
    if !content.is_object() {
        return Err(fail(
            ConfigurationStoreErrorKind::Corrupt,
            "content 형식 손상",
        ));
    }
    let mut envelope = Map::new();
    envelope.insert("digest".into(), Value::String(content_digest(&content)));
    envelope.insert("content".into(), content);
    serde_json::to_vec_pretty(&Value::Object(envelope))
        .map_err(|error| fail(ConfigurationStoreErrorKind::Corrupt, error.to_string()))
}

pub struct WorkspaceMetadataStore {
    root: PathBuf,
    lock: DirectoryLock,
}
impl WorkspaceMetadataStore {
    pub fn new(root: impl Into<PathBuf>) -> Result<Self, ConfigurationStoreError> {
        let root = resolved_home(&root.into());
        let lock = DirectoryLock::new(&root)?;
        Ok(Self { root, lock })
    }
    fn path(&self) -> PathBuf {
        self.root.join("workspace.json")
    }
    pub fn read(&self) -> Result<Option<String>, ConfigurationStoreError> {
        let path = self.path();
        let content = match read_content(&path) {
            Ok(content) => content,
            Err(error) if error.kind == ConfigurationStoreErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error),
        };
        if content["schema_version"] != WORKSPACE_SCHEMA_VERSION {
            return Err(fail(
                ConfigurationStoreErrorKind::UnsupportedSchema,
                "workspace metadata schema 미상",
            ));
        }
        let id = content
            .get("workspace_instance_id")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty())
            .ok_or_else(|| {
                fail(
                    ConfigurationStoreErrorKind::Corrupt,
                    "workspace_instance_id 부재·형식 손상",
                )
            })?;
        Ok(Some(id.into()))
    }
    pub fn get_or_create(&self, now: &str) -> Result<String, ConfigurationStoreError> {
        self.get_or_create_with(now, || uuid::Uuid::new_v4().simple().to_string())
    }
    fn get_or_create_with(
        &self,
        now: &str,
        mint: impl FnOnce() -> String,
    ) -> Result<String, ConfigurationStoreError> {
        self.lock.with(|| {
            if let Some(id) = self.read()? {
                return Ok(id);
            }
            let id = mint();
            if id.is_empty() {
                return Err(fail(
                    ConfigurationStoreErrorKind::InvalidId,
                    "minted workspace_instance_id 가 비었다",
                ));
            }
            let mut content = Map::new();
            content.insert(
                "schema_version".into(),
                Value::String(WORKSPACE_SCHEMA_VERSION.into()),
            );
            content.insert("workspace_instance_id".into(), Value::String(id.clone()));
            content.insert("created_at".into(), Value::String(now.into()));
            fs::create_dir_all(&self.root)?;
            write_bytes_atomic_exclusive(&self.path(), &enveloped_bytes(Value::Object(content))?)?;
            Ok(id)
        })
    }
}

pub struct WorkSlotConfigurationStore {
    root: PathBuf,
    lock: DirectoryLock,
}
impl WorkSlotConfigurationStore {
    pub fn new(root: impl Into<PathBuf>) -> Result<Self, ConfigurationStoreError> {
        let root = resolved_home(&root.into());
        let lock = DirectoryLock::new(&root)?;
        Ok(Self { root, lock })
    }
    pub fn exists(&self, work_id: &str) -> Result<bool, ConfigurationStoreError> {
        Ok(work_path(&self.root, work_id)?.exists())
    }
    pub fn load(&self, work_id: &str) -> Result<StoredWorkConfiguration, ConfigurationStoreError> {
        let content = read_content(&work_path(&self.root, work_id)?)?;
        if content["schema_version"] != STORE_SCHEMA_VERSION {
            return Err(fail(
                ConfigurationStoreErrorKind::UnsupportedSchema,
                format!("work {work_id} S4 aggregate schema 미상"),
            ));
        }
        let stored = decode_stored(&content).map_err(|error| {
            fail(
                ConfigurationStoreErrorKind::Corrupt,
                format!("work {work_id} S4 aggregate 불변식 위반: {error}"),
            )
        })?;
        if stored.work_id() != work_id {
            return Err(fail(
                ConfigurationStoreErrorKind::Corrupt,
                format!("work {work_id} 파일이 다른 Work aggregate 를 담았다"),
            ));
        }
        Ok(stored)
    }
    pub fn create(&self, stored: &StoredWorkConfiguration) -> Result<(), ConfigurationStoreError> {
        if stored.aggregate_version != 1 {
            return Err(fail(
                ConfigurationStoreErrorKind::Conflict,
                "최초 aggregate commit 은 version 1 이어야 한다",
            ));
        }
        let path = work_path(&self.root, stored.work_id())?;
        let bytes = enveloped_bytes(
            encode_stored(stored)
                .map_err(|e| fail(ConfigurationStoreErrorKind::Corrupt, e.to_string()))?,
        )?;
        self.lock.with(|| {
            if path.exists() {
                return Err(fail(
                    ConfigurationStoreErrorKind::Exists,
                    "S4 aggregate 이미 존재",
                ));
            }
            fs::create_dir_all(&self.root)?;
            write_bytes_atomic_exclusive(&path, &bytes)?;
            Ok(())
        })
    }
    pub fn update(
        &self,
        work_id: &str,
        expected_version: u64,
        change: impl FnOnce(
            &StoredWorkConfiguration,
        ) -> Result<StoredWorkConfiguration, ConfigurationStoreError>,
    ) -> Result<StoredWorkConfiguration, ConfigurationStoreError> {
        self.lock.with(|| {
            let current = self.load(work_id)?;
            if current.aggregate_version != expected_version {
                return Err(fail(
                    ConfigurationStoreErrorKind::Conflict,
                    format!(
                        "work {work_id} CAS 실패: expected {expected_version}, current {}",
                        current.aggregate_version
                    ),
                ));
            }
            let next = change(&current)?;
            if next.work_id() != work_id
                || next.workspace_instance_id != current.workspace_instance_id
            {
                return Err(fail(
                    ConfigurationStoreErrorKind::Conflict,
                    "update 는 Work·workspace identity 를 바꿀 수 없다",
                ));
            }
            if Some(next.aggregate_version) != current.aggregate_version.checked_add(1) {
                return Err(fail(
                    ConfigurationStoreErrorKind::Conflict,
                    "commit 은 aggregate_version 을 정확히 1 올려야 한다",
                ));
            }
            if !next
                .processed_requests
                .starts_with(&current.processed_requests)
            {
                return Err(fail(
                    ConfigurationStoreErrorKind::Conflict,
                    "first-seen ledger 는 append-only 다(기존 기록 보존)",
                ));
            }
            let bytes = enveloped_bytes(
                encode_stored(&next)
                    .map_err(|e| fail(ConfigurationStoreErrorKind::Corrupt, e.to_string()))?,
            )?;
            write_bytes_atomic(&work_path(&self.root, work_id)?, &bytes)?;
            Ok(next)
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::stored_work_configuration::{
        IdempotencyRecord, TerminalOutcome, append_request, empty_stored, find_request,
    };
    use hwpx_filler::work_slot_configuration::create_empty;
    use serde_json::json;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn metadata_identity_and_s4_cas_refuse_corruption_without_replacing_prior_bytes() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = workspace.join(format!(
            ".cache/work-configuration-store-{}-{stamp}",
            std::process::id()
        ));
        let metadata = WorkspaceMetadataStore::new(root.join("metadata")).unwrap();
        assert_eq!(metadata.read().unwrap(), None);
        assert_eq!(
            metadata
                .get_or_create_with("now", String::new)
                .unwrap_err()
                .kind,
            ConfigurationStoreErrorKind::InvalidId
        );
        assert!(!metadata.path().exists());
        let id = metadata
            .get_or_create_with("2026-11-05", || "workspace-id".into())
            .unwrap();
        assert_eq!(id, "workspace-id");
        assert_eq!(
            metadata
                .get_or_create_with("later", || panic!("must not mint again"))
                .unwrap(),
            id
        );
        assert_eq!(
            WorkspaceMetadataStore::new(root.join("metadata"))
                .unwrap()
                .read()
                .unwrap(),
            Some(id.clone())
        );
        assert_ne!(
            WorkspaceMetadataStore::new(root.join("other"))
                .unwrap()
                .get_or_create("now")
                .unwrap(),
            id
        );
        let store = WorkSlotConfigurationStore::new(root.join("s4")).unwrap();
        assert_eq!(
            store.load("../escape").unwrap_err().kind,
            ConfigurationStoreErrorKind::InvalidId
        );
        assert_eq!(
            store.load("w").unwrap_err().kind,
            ConfigurationStoreErrorKind::NotFound
        );
        let initial = empty_stored(&id, "w").unwrap();
        let mut bad_initial = initial.clone();
        bad_initial.aggregate_version = 2;
        assert_eq!(
            store.create(&bad_initial).unwrap_err().kind,
            ConfigurationStoreErrorKind::Conflict
        );
        store.create(&initial).unwrap();
        assert!(store.exists("w").unwrap());
        assert_eq!(
            store.create(&initial).unwrap_err().kind,
            ConfigurationStoreErrorKind::Exists
        );
        assert_eq!(store.load("w").unwrap(), initial);
        let path = root.join("s4/w.json");
        let original = fs::read(&path).unwrap();
        assert_eq!(
            store.update("w", 2, |_| unreachable!()).unwrap_err().kind,
            ConfigurationStoreErrorKind::Conflict
        );
        assert_eq!(fs::read(&path).unwrap(), original);
        let updated = store
            .update("w", 1, |value| {
                let mut next = value.clone();
                next.aggregate_version = 2;
                Ok(next)
            })
            .unwrap();
        assert_eq!(store.load("w").unwrap(), updated);
        fs::write(root.join("s4/w.json.stale.tmp"), "{partial").unwrap();
        assert_eq!(store.load("w").unwrap(), updated);
        let record = IdempotencyRecord {
            request_id: "req1".into(),
            fingerprint_schema_version: "fp/v1".into(),
            command_fingerprint: "fp-a".into(),
            terminal_outcome: TerminalOutcome {
                application_id: "A18".into(),
                outcome_code: "APPLIED".into(),
                changed: true,
                source_configuration_version: Some(1),
                resulting_configuration_version: Some(2),
            },
            request_actor_binding_digest: "sha256:actor".into(),
            recorded_at: "now".into(),
        };
        let with_ledger = store
            .update("w", 2, |current| {
                let mut next = append_request(current, record.clone()).unwrap();
                next.aggregate_version += 1;
                Ok(next)
            })
            .unwrap();
        assert_eq!(
            find_request(&store.load("w").unwrap(), "req1"),
            Some(&record)
        );
        assert!(with_ledger.configurations.configurations.is_empty());
        let before = fs::read(&path).unwrap();
        for defect in [
            "workspace",
            "work",
            "unchanged-version",
            "skipped-version",
            "truncated-ledger",
            "rewritten-ledger",
            "invalid-config",
            "mutation-error",
        ] {
            let error = store
                .update("w", 3, |current| {
                    let mut next = current.clone();
                    next.aggregate_version += 1;
                    match defect {
                        "workspace" => next.workspace_instance_id = "foreign".into(),
                        "work" => next.configurations.work_id = "foreign".into(),
                        "unchanged-version" => next.aggregate_version = 3,
                        "skipped-version" => next.aggregate_version = 5,
                        "truncated-ledger" => next.processed_requests.clear(),
                        "rewritten-ledger" => {
                            next.processed_requests[0].command_fingerprint = "changed".into()
                        }
                        "invalid-config" => next
                            .configurations
                            .configurations
                            .push(create_empty("foreign", "app", "now").unwrap()),
                        "mutation-error" => {
                            return Err(fail(ConfigurationStoreErrorKind::Io, "mid-mutation"));
                        }
                        _ => unreachable!(),
                    }
                    Ok(next)
                })
                .unwrap_err();
            assert_eq!(
                error.kind,
                match defect {
                    "mutation-error" => ConfigurationStoreErrorKind::Io,
                    "invalid-config" => ConfigurationStoreErrorKind::Corrupt,
                    _ => ConfigurationStoreErrorKind::Conflict,
                },
                "{defect}"
            );
            assert_eq!(fs::read(&path).unwrap(), before, "{defect}");
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(1 | 2)
                .open(&path)
                .unwrap();
            assert_eq!(
                store
                    .update("w", 3, |current| {
                        let mut next = current.clone();
                        next.aggregate_version += 1;
                        Ok(next)
                    })
                    .unwrap_err()
                    .kind,
                ConfigurationStoreErrorKind::Io
            );
            assert_eq!(fs::read(&path).unwrap(), before);
            drop(held);
        }
        store
            .create(&empty_stored(&id, "other-work").unwrap())
            .unwrap();
        let other_before = fs::read(root.join("s4/other-work.json")).unwrap();
        let barrier = std::sync::Barrier::new(2);
        let aliased = WorkSlotConfigurationStore::new(root.join("sub/../s4")).unwrap();
        let outcomes = std::thread::scope(|scope| {
            let threads: Vec<_> = [&store, &aliased]
                .into_iter()
                .map(|writer| {
                    let barrier = &barrier;
                    scope.spawn(move || {
                        barrier.wait();
                        writer.update("w", 3, |current| {
                            let mut next = current.clone();
                            next.aggregate_version += 1;
                            next.configurations
                                .configurations
                                .push(create_empty("w", "app", "now").unwrap());
                            Ok(next)
                        })
                    })
                })
                .collect();
            threads
                .into_iter()
                .map(|t| t.join().unwrap())
                .collect::<Vec<_>>()
        });
        assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(
            outcomes
                .iter()
                .find_map(|result| result.as_ref().err())
                .unwrap()
                .kind,
            ConfigurationStoreErrorKind::Conflict
        );
        let current = store.load("w").unwrap();
        assert_eq!(current.aggregate_version, 4);
        assert_eq!(current.configurations.configurations.len(), 1);
        assert!(current.configurations.configurations[0].is_empty());
        assert_eq!(find_request(&current, "req1"), Some(&record));
        assert_eq!(
            fs::read(root.join("s4/other-work.json")).unwrap(),
            other_before
        );
        let before = fs::read(&path).unwrap();
        fs::write(&path, other_before).unwrap();
        assert_eq!(
            store.load("w").unwrap_err().kind,
            ConfigurationStoreErrorKind::Corrupt
        );
        for raw in [
            "{bad json",
            "[]",
            "\"a-string\"",
            "{\"digest\":\"x\",\"content\":\"not-an-object\"}",
        ] {
            fs::write(&path, raw).unwrap();
            assert_eq!(
                store.load("w").unwrap_err().kind,
                ConfigurationStoreErrorKind::Corrupt
            );
        }
        for (pointer, value, kind) in [
            (
                "/schema_version",
                json!("work-slot-configuration-store-v99"),
                ConfigurationStoreErrorKind::UnsupportedSchema,
            ),
            (
                "/aggregate_version",
                json!(0),
                ConfigurationStoreErrorKind::Corrupt,
            ),
            (
                "/configurations/configurations/0",
                json!({"no_selections_key":true}),
                ConfigurationStoreErrorKind::Corrupt,
            ),
        ] {
            let mut content = encode_stored(&current).unwrap();
            *content.pointer_mut(pointer).unwrap() = value;
            let damaged = enveloped_bytes(content).unwrap();
            fs::write(&path, &damaged).unwrap();
            assert_eq!(store.load("w").unwrap_err().kind, kind);
            assert_eq!(
                store
                    .update("w", 4, |_| panic!("corrupt state must not reach mutation"))
                    .unwrap_err()
                    .kind,
                kind
            );
            assert_eq!(fs::read(&path).unwrap(), damaged);
        }
        fs::write(&path, before).unwrap();
        let mut bytes = fs::read(&path).unwrap();
        let offset = bytes
            .windows(b"workspace-id".len())
            .position(|window| window == b"workspace-id")
            .unwrap();
        bytes[offset] = b'x';
        fs::write(&path, bytes).unwrap();
        assert_eq!(
            store.load("w").unwrap_err().kind,
            ConfigurationStoreErrorKind::Corrupt
        );
        let meta_path = metadata.path();
        let mut envelope: Value = serde_json::from_slice(&fs::read(&meta_path).unwrap()).unwrap();
        envelope["content"]["workspace_instance_id"] = json!("tampered");
        fs::write(&meta_path, serde_json::to_vec(&envelope).unwrap()).unwrap();
        assert_eq!(
            metadata.read().unwrap_err().kind,
            ConfigurationStoreErrorKind::Corrupt
        );
        for (content, kind) in [
            (
                json!({"schema_version":"unknown", "workspace_instance_id":"x"}),
                ConfigurationStoreErrorKind::UnsupportedSchema,
            ),
            (
                json!({"schema_version":WORKSPACE_SCHEMA_VERSION, "workspace_instance_id":""}),
                ConfigurationStoreErrorKind::Corrupt,
            ),
        ] {
            let damaged = enveloped_bytes(content).unwrap();
            fs::write(&meta_path, &damaged).unwrap();
            assert_eq!(
                metadata
                    .get_or_create_with("later", || panic!("do not replace damaged identity"))
                    .unwrap_err()
                    .kind,
                kind
            );
            assert_eq!(fs::read(&meta_path).unwrap(), damaged);
        }
        let root = root.canonicalize().unwrap();
        assert!(root.starts_with(&workspace));
        fs::remove_dir_all(root).unwrap();
    }
}
