//! File-atomic per-Work template aggregate store.

use crate::atomic_file::{write_bytes_atomic, write_bytes_atomic_exclusive};
use crate::directory_lock::DirectoryLock;
use crate::single_instance::resolved_home;
use hwpx_filler::work_template_state::{
    WorkTemplateStateAggregate, decode_aggregate, encode_aggregate,
};
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WorkStoreErrorKind {
    InvalidId,
    NotFound,
    Exists,
    Corrupt,
    Conflict,
    Io,
}
#[derive(Debug)]
pub struct WorkStoreError {
    pub kind: WorkStoreErrorKind,
    pub detail: String,
}
impl fmt::Display for WorkStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for WorkStoreError {}
impl From<io::Error> for WorkStoreError {
    fn from(error: io::Error) -> Self {
        Self {
            kind: WorkStoreErrorKind::Io,
            detail: error.to_string(),
        }
    }
}
fn fail(kind: WorkStoreErrorKind, detail: impl Into<String>) -> WorkStoreError {
    WorkStoreError {
        kind,
        detail: detail.into(),
    }
}
fn path_for(root: &Path, work_id: &str) -> Result<PathBuf, WorkStoreError> {
    if work_id.is_empty()
        || !work_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    {
        return Err(fail(
            WorkStoreErrorKind::InvalidId,
            format!("저장할 수 없는 work_id {work_id:?}"),
        ));
    }
    Ok(root.join(format!("{work_id}.json")))
}

pub struct AtomicWorkTemplateStateStore {
    root: PathBuf,
    lock: DirectoryLock,
}
impl AtomicWorkTemplateStateStore {
    pub fn new(root: impl Into<PathBuf>) -> Result<Self, WorkStoreError> {
        let root = resolved_home(&root.into());
        let lock = DirectoryLock::new(&root)?;
        Ok(Self { root, lock })
    }
    pub fn exists(&self, work_id: &str) -> Result<bool, WorkStoreError> {
        Ok(path_for(&self.root, work_id)?.exists())
    }
    pub fn load(&self, work_id: &str) -> Result<WorkTemplateStateAggregate, WorkStoreError> {
        let path = path_for(&self.root, work_id)?;
        let bytes = fs::read(&path).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                fail(
                    WorkStoreErrorKind::NotFound,
                    format!("work {work_id} aggregate 없음"),
                )
            } else {
                error.into()
            }
        })?;
        let value = serde_json::from_slice(&bytes).map_err(|_| {
            fail(
                WorkStoreErrorKind::Corrupt,
                format!("work {work_id} aggregate 손상"),
            )
        })?;
        let aggregate = decode_aggregate(&value)
            .map_err(|error| fail(WorkStoreErrorKind::Corrupt, error.to_string()))?;
        if aggregate.work.work_id != work_id {
            return Err(fail(
                WorkStoreErrorKind::Corrupt,
                format!("work {work_id} 파일이 다른 Work aggregate 를 담았다"),
            ));
        }
        Ok(aggregate)
    }
    pub fn create(&self, aggregate: &WorkTemplateStateAggregate) -> Result<(), WorkStoreError> {
        let work_id = &aggregate.work.work_id;
        let path = path_for(&self.root, work_id)?;
        let value = encode_aggregate(aggregate)
            .map_err(|error| fail(WorkStoreErrorKind::Corrupt, error.to_string()))?;
        let bytes = serde_json::to_vec_pretty(&value)
            .map_err(|error| fail(WorkStoreErrorKind::Corrupt, error.to_string()))?;
        self.lock.with(|| {
            if path.exists() {
                return Err(fail(
                    WorkStoreErrorKind::Exists,
                    format!("work {work_id} 는 이미 존재한다"),
                ));
            }
            fs::create_dir_all(&self.root)?;
            write_bytes_atomic_exclusive(&path, &bytes)?;
            Ok(())
        })
    }
    /// The caller returns a complete replacement; an error or invalid version leaves disk unchanged.
    pub fn update(
        &self,
        work_id: &str,
        change: impl FnOnce(
            &WorkTemplateStateAggregate,
        ) -> Result<WorkTemplateStateAggregate, WorkStoreError>,
    ) -> Result<WorkTemplateStateAggregate, WorkStoreError> {
        self.lock.with(|| {
            let current = self.load(work_id)?;
            let replacement = change(&current)?;
            let before = encode_aggregate(&current)
                .map_err(|e| fail(WorkStoreErrorKind::Corrupt, e.to_string()))?;
            let after = encode_aggregate(&replacement)
                .map_err(|e| fail(WorkStoreErrorKind::Corrupt, e.to_string()))?;
            if after == before {
                return Ok(current);
            }
            if replacement.work.work_id != work_id
                || replacement.aggregate_version
                    != current.aggregate_version.checked_add(1).ok_or_else(|| {
                        fail(WorkStoreErrorKind::Conflict, "aggregate_version 넘침")
                    })?
            {
                return Err(fail(
                    WorkStoreErrorKind::Conflict,
                    "commit 은 같은 Work 의 aggregate_version 을 정확히 1 올려야 한다",
                ));
            }
            let bytes = serde_json::to_vec_pretty(&after)
                .map_err(|e| fail(WorkStoreErrorKind::Corrupt, e.to_string()))?;
            write_bytes_atomic(&path_for(&self.root, work_id)?, &bytes)?;
            Ok(replacement)
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{AtomicWorkTemplateStateStore, WorkStoreErrorKind};
    use hwpx_filler::work_template_state::{
        DocumentWork, INITIALIZATION, SCHEMA_VERSION, WorkTemplateApplication,
        WorkTemplateStateAggregate,
    };
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn create_once_update_and_corrupt_load_keep_prior_complete_bytes() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = workspace.join(format!(
            ".cache/work-template-store-{}-{stamp}",
            std::process::id()
        ));
        let store = AtomicWorkTemplateStateStore::new(&root).unwrap();
        let aggregate = WorkTemplateStateAggregate {
            schema_version: SCHEMA_VERSION.into(),
            aggregate_version: 1,
            work: DocumentWork {
                work_id: "w".into(),
                template_lineage_id: "line".into(),
                current_template_application_id: "a1".into(),
                current_template_preparation_id: None,
                prepare_seq: 0,
            },
            applications: vec![WorkTemplateApplication {
                application_id: "a1".into(),
                work_id: "w".into(),
                application_epoch: 1,
                pass_evidence_id: "e".into(),
                previous_application_id: None,
                origin: INITIALIZATION.into(),
                prepared_change_id: None,
                actor: "actor".into(),
                applied_at: "t".into(),
            }],
            preparations: vec![],
            prepared_changes: vec![],
        };
        assert_eq!(
            store.load("w").unwrap_err().kind,
            WorkStoreErrorKind::NotFound
        );
        store.create(&aggregate).unwrap();
        assert_eq!(
            store.create(&aggregate).unwrap_err().kind,
            WorkStoreErrorKind::Exists
        );
        let path = root.join("w.json");
        let original = fs::read(&path).unwrap();
        store.update("w", |value| Ok(value.clone())).unwrap();
        assert_eq!(fs::read(&path).unwrap(), original);
        assert_eq!(
            store
                .update("w", |value| {
                    let mut next = value.clone();
                    next.work.prepare_seq += 1;
                    Ok(next)
                })
                .unwrap_err()
                .kind,
            WorkStoreErrorKind::Conflict
        );
        assert_eq!(fs::read(&path).unwrap(), original);
        let updated = store
            .update("w", |value| {
                let mut next = value.clone();
                next.work.prepare_seq += 1;
                next.aggregate_version += 1;
                Ok(next)
            })
            .unwrap();
        assert_eq!(updated.aggregate_version, 2);
        assert_eq!(store.load("w").unwrap(), updated);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            // Allow reading the current Work, but deny replacement at the durable commit.
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(1 | 2)
                .open(&path)
                .unwrap();
            let bytes = fs::read(&path).unwrap();
            let error = store
                .update("w", |value| {
                    let mut next = value.clone();
                    next.work.prepare_seq += 1;
                    next.aggregate_version += 1;
                    Ok(next)
                })
                .unwrap_err();
            assert_eq!(error.kind, WorkStoreErrorKind::Io);
            assert_eq!(fs::read(&path).unwrap(), bytes);
            assert_eq!(store.load("w").unwrap(), updated);
            drop(held);
        }
        for id in ["", "../escape", "x/y"] {
            assert_eq!(
                store.load(id).unwrap_err().kind,
                WorkStoreErrorKind::InvalidId
            );
            assert_eq!(
                store
                    .update(id, |_| panic!("invalid work reached mutation"))
                    .unwrap_err()
                    .kind,
                WorkStoreErrorKind::InvalidId
            );
        }
        assert_eq!(
            store
                .update("missing", |_| panic!("missing work reached mutation"))
                .unwrap_err()
                .kind,
            WorkStoreErrorKind::NotFound
        );
        let original_bytes = fs::read(&path).unwrap();
        for version in [1, 2, 4] {
            assert_eq!(
                store
                    .update("w", |current| {
                        let mut next = current.clone();
                        next.aggregate_version = version;
                        next.work.prepare_seq += 1;
                        Ok(next)
                    })
                    .unwrap_err()
                    .kind,
                WorkStoreErrorKind::Conflict
            );
            assert_eq!(fs::read(&path).unwrap(), original_bytes);
        }
        let mut other = updated.clone();
        other.work.work_id = "other".into();
        other.applications[0].work_id = "other".into();
        assert_eq!(
            store
                .update("w", |_| {
                    let mut foreign = other.clone();
                    foreign.aggregate_version += 1;
                    Ok(foreign)
                })
                .unwrap_err()
                .kind,
            WorkStoreErrorKind::Conflict
        );
        assert_eq!(fs::read(&path).unwrap(), original_bytes);
        for schema in ["bogus", "work-template-state-v1"] {
            let mut value = hwpx_filler::work_template_state::encode_aggregate(&updated).unwrap();
            value["schema_version"] = serde_json::json!(schema);
            value["outbox_events"] =
                serde_json::json!([{"event_id":"pending","payload":{"value":1}}]);
            value["migration_provenance"] = serde_json::json!({"bootstrap_request_id":"old"});
            let bytes = serde_json::to_vec(&value).unwrap();
            fs::write(&path, &bytes).unwrap();
            assert_eq!(
                store
                    .update("w", |_| panic!("unsupported schema reached mutation"))
                    .unwrap_err()
                    .kind,
                WorkStoreErrorKind::Corrupt
            );
            assert_eq!(fs::read(&path).unwrap(), bytes);
        }
        fs::write(
            &path,
            serde_json::to_vec(
                &hwpx_filler::work_template_state::encode_aggregate(&other).unwrap(),
            )
            .unwrap(),
        )
        .unwrap();
        assert!(
            store
                .load("w")
                .unwrap_err()
                .detail
                .contains("다른 Work aggregate")
        );
        fs::write(&path, &original_bytes).unwrap();
        fs::write(root.join("w.json.stale.tmp"), b"partial write").unwrap();
        assert_eq!(store.load("w").unwrap(), updated);
        store.create(&other).unwrap();
        let barrier = std::sync::Barrier::new(2);
        let bump = || {
            barrier.wait();
            AtomicWorkTemplateStateStore::new(&root)
                .unwrap()
                .update("w", |current| {
                    let mut next = current.clone();
                    next.aggregate_version += 1;
                    next.work.prepare_seq += 1;
                    Ok(next)
                })
                .unwrap()
        };
        std::thread::scope(|scope| {
            let first = scope.spawn(bump);
            let second = scope.spawn(bump);
            first.join().unwrap();
            second.join().unwrap();
        });
        let current = store.load("w").unwrap();
        assert_eq!(current.aggregate_version, updated.aggregate_version + 2);
        assert_eq!(current.work.prepare_seq, updated.work.prepare_seq + 2);
        assert_eq!(store.load("other").unwrap(), other);
        fs::write(&path, b"{").unwrap();
        assert_eq!(
            store.load("w").unwrap_err().kind,
            WorkStoreErrorKind::Corrupt
        );
        let root = root.canonicalize().unwrap();
        assert!(root.starts_with(&workspace));
        fs::remove_dir_all(root).unwrap();
    }
}
