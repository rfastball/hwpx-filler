//! Job JSON slots, corruption isolation, and transaction-scoped writer ownership.

use crate::atomic_file::{move_exclusive, write_bytes_atomic};
use crate::job_writer_lease::{JobWriterLease, OwnershipError};
use crate::template_link::{library_key_for, resolve_template_link};
use chrono::{Local, Timelike};
use hwpx_filler::job::{Job, JobError, advance_revisions, decode_job, encode_job, template_media};
use hwpx_filler::text_render::python_repr;
use serde_json::{Map, Value};
use std::error::Error;
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

mod groups;
mod lifecycle;

const SUFFIX: &str = ".job.json";
const TRASH_RETENTION: Duration = Duration::from_secs(30 * 24 * 60 * 60);
static NEXT_TRASH: AtomicU64 = AtomicU64::new(0);

#[derive(Debug)]
pub enum StoreError {
    Io(io::Error),
    Codec(JobError),
    Ownership(OwnershipError),
    Collision(String),
    Invalid(String),
    CrossMedia {
        old_path: String,
        new_media: &'static str,
    },
}
impl fmt::Display for StoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "{error}"),
            Self::Codec(error) => write!(formatter, "{error}"),
            Self::Ownership(error) => write!(formatter, "{error}"),
            Self::Collision(detail) => formatter.write_str(detail),
            Self::Invalid(detail) => formatter.write_str(detail),
            Self::CrossMedia {
                old_path,
                new_media,
            } => write!(
                formatter,
                "매체 교차 재연결 거절: {} → {}",
                python_repr(&Value::String(old_path.clone())),
                python_repr(&Value::String((*new_media).into()))
            ),
        }
    }
}
impl Error for StoreError {}
impl From<io::Error> for StoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}
impl From<JobError> for StoreError {
    fn from(error: JobError) -> Self {
        Self::Codec(error)
    }
}
impl From<OwnershipError> for StoreError {
    fn from(error: OwnershipError) -> Self {
        Self::Ownership(error)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CorruptJobEntry {
    pub file_name: String,
    pub token: String,
    pub error: String,
}

#[derive(Clone, Debug)]
pub struct DeletedJobSlot {
    original: PathBuf,
    trashed: PathBuf,
}

fn slug(name: &str) -> String {
    let slug = name
        .chars()
        .map(|letter| {
            if "\\/:*?\"<>|\r\n\t".contains(letter) {
                '_'
            } else {
                letter
            }
        })
        .collect::<String>();
    let slug = slug.trim();
    if slug.is_empty() {
        "unnamed".into()
    } else {
        slug.into()
    }
}

pub struct JobRegistry {
    directory: PathBuf,
    template_root: Arc<dyn Fn() -> PathBuf + Send + Sync>,
    lease: JobWriterLease,
}
impl JobRegistry {
    pub fn new(
        directory: PathBuf,
        template_root: impl Fn() -> PathBuf + Send + Sync + 'static,
    ) -> io::Result<Self> {
        let lease = JobWriterLease::new(&directory)?;
        Ok(Self {
            directory,
            template_root: Arc::new(template_root),
            lease,
        })
    }
    pub fn directory(&self) -> &Path {
        &self.directory
    }
    pub(crate) fn configured_template_root(&self) -> PathBuf {
        (self.template_root)()
    }
    pub fn path_for(&self, name: &str) -> PathBuf {
        self.directory.join(format!("{}{SUFFIX}", slug(name)))
    }
    fn load_at(&self, path: &Path, root: &Path) -> Result<Job, StoreError> {
        if fs::symlink_metadata(path)?.file_type().is_symlink() {
            return Err(StoreError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "job slot is a link",
            )));
        }
        let text = fs::read_to_string(path)?;
        let value: serde_json::Value = serde_json::from_str(&text)
            .map_err(|error| StoreError::Io(io::Error::new(io::ErrorKind::InvalidData, error)))?;
        let key = value
            .get("template_key")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("");
        let mut job = decode_job(&value)?;
        let resolved =
            resolve_template_link(Path::new(&job.template_path), key, root, &job.authority_id)?;
        job.template_path = resolved
            .to_str()
            .ok_or_else(|| {
                StoreError::Io(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "template path is not Unicode",
                ))
            })?
            .into();
        Ok(job)
    }
    pub fn load(&self, name: &str) -> Result<Job, StoreError> {
        if name.is_empty() {
            return Err(StoreError::Invalid("이름이 비어 있습니다".into()));
        }
        self.load_at(&self.path_for(name), &(self.template_root)())
    }
    pub fn exists(&self, name: &str) -> bool {
        self.path_for(name).exists()
    }
    pub fn list_jobs_with_corruption(
        &self,
    ) -> Result<(Vec<Job>, Vec<CorruptJobEntry>), StoreError> {
        self.list_at(&(self.template_root)())
    }
    fn list_at(&self, root: &Path) -> Result<(Vec<Job>, Vec<CorruptJobEntry>), StoreError> {
        if !self.directory.exists() {
            return Ok((Vec::new(), Vec::new()));
        }
        let mut paths = Vec::new();
        for entry in fs::read_dir(&self.directory)? {
            let path = entry?.path();
            let name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| {
                    StoreError::Io(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "job slot name is not Unicode",
                    ))
                })?;
            if name.ends_with(SUFFIX) {
                paths.push(path);
            }
        }
        paths.sort();
        let mut jobs = Vec::new();
        let mut corrupted = Vec::new();
        for path in paths {
            match self.load_at(&path, root) {
                Ok(job) => jobs.push(job),
                Err(error) => corrupted.push(CorruptJobEntry {
                    file_name: path
                        .file_name()
                        .and_then(|name| name.to_str())
                        .expect("validated slot name")
                        .into(),
                    token: path
                        .to_str()
                        .ok_or_else(|| {
                            StoreError::Io(io::Error::new(
                                io::ErrorKind::InvalidData,
                                "job slot path is not Unicode",
                            ))
                        })?
                        .into(),
                    error: error.to_string(),
                }),
            }
        }
        jobs.sort_by(|left, right| left.name.cmp(&right.name));
        Ok((jobs, corrupted))
    }
    pub fn names(&self) -> Result<Vec<String>, StoreError> {
        Ok(self
            .list_jobs_with_corruption()?
            .0
            .into_iter()
            .map(|job| job.name)
            .collect())
    }

    /// The transaction owns one process lease and one root snapshot for all operations.
    pub fn transaction<T>(
        &self,
        work: impl FnOnce(&JobWriteSession<'_>) -> Result<T, StoreError>,
    ) -> Result<T, StoreError> {
        self.lease.with_write_lock(|| {
            let root = (self.template_root)();
            work(&JobWriteSession {
                registry: self,
                root,
            })
        })?
    }
    pub fn save(&self, job: &mut Job, allow_overwrite: bool) -> Result<(), StoreError> {
        self.transaction(|session| session.save(job, allow_overwrite))
    }
    pub fn mutate(&self, name: &str, change: impl FnOnce(&mut Job)) -> Result<Job, StoreError> {
        self.transaction(|session| {
            let mut job = session.load(name)?;
            change(&mut job);
            session.save(&mut job, false)?;
            Ok(job)
        })
    }
    pub fn stamp_last_run(
        &self,
        name: &str,
        when: &str,
        rules: Option<&Map<String, Value>>,
    ) -> Result<Job, StoreError> {
        self.mutate(name, |job| {
            job.last_run_at = when.into();
            if let Some(rules) = rules {
                job.reviewed_rules = rules.clone();
            }
        })
    }
    pub fn assign_authority_id(&self, name: &str, authority_id: &str) -> Result<Job, StoreError> {
        self.mutate(name, |job| {
            if job.authority_id.is_empty() {
                job.authority_id = authority_id.into();
            }
        })
    }
    pub fn release_authority_id(&self, name: &str, authority_id: &str) -> Result<Job, StoreError> {
        self.mutate(name, |job| {
            if job.authority_id == authority_id {
                job.authority_id.clear();
            }
        })
    }
    pub fn set_tags(&self, name: &str, tags: &Map<String, Value>) -> Result<Job, StoreError> {
        self.mutate(name, |job| job.tags = tags.clone())
    }
    pub fn set_favorite(
        &self,
        name: &str,
        favorited: bool,
        when: Option<&str>,
    ) -> Result<Job, StoreError> {
        self.mutate(name, |job| {
            if favorited {
                if job.favorited_at.is_empty() {
                    job.favorited_at = when.map(str::to_owned).unwrap_or_else(local_iso_time);
                }
            } else {
                job.favorited_at.clear();
            }
        })
    }
    pub fn relink_template(
        &self,
        name: &str,
        path: &str,
        expected: Option<(&str, &str)>,
    ) -> Result<Job, StoreError> {
        let new_media = template_media(path);
        self.transaction(|session| {
            let mut job = session.load(name)?;
            if expected.is_some_and(|(authority, old_path)| {
                job.authority_id != authority || job.template_path != old_path
            }) {
                return Err(StoreError::Invalid(
                    "문서 작업의 템플릿 연결이 변경되었습니다".into(),
                ));
            }
            let current = template_media(&job.template_path);
            if matches!(current, "hwpx" | "txt") && current != new_media {
                return Err(StoreError::CrossMedia {
                    old_path: job.template_path,
                    new_media,
                });
            }
            if !matches!(current, "hwpx" | "txt") {
                job.last_run_at.clear();
            }
            job.template_path = path.into();
            session.save(&mut job, false)?;
            Ok(job)
        })
    }
    pub fn content_fingerprint(&self, job: &Job) -> Result<String, StoreError> {
        let key = library_key_for(Path::new(&job.template_path), &(self.template_root)());
        Ok(hwpx_filler::job::content_fingerprint(job, &key)?)
    }
}

fn local_iso_time() -> String {
    let now = Local::now();
    let mut value = now.format("%Y-%m-%dT%H:%M:%S").to_string();
    let micros = now.nanosecond() / 1_000;
    if micros != 0 {
        value.push_str(&format!(".{micros:06}"));
    }
    value
}

fn reject_linked_directory(path: &Path) -> io::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "deleted job directory is a link",
            ));
        }
    }
    #[cfg(not(windows))]
    if metadata.file_type().is_symlink() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "deleted job directory is a link",
        ));
    }
    if !metadata.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "deleted job directory is not a directory",
        ));
    }
    Ok(())
}

fn purge_trash(trash: &Path) {
    let cutoff = SystemTime::now()
        .checked_sub(TRASH_RETENTION)
        .unwrap_or(UNIX_EPOCH);
    if let Ok(entries) = fs::read_dir(trash) {
        for entry in entries.flatten() {
            let path = entry.path();
            if !path
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.ends_with(SUFFIX))
            {
                continue;
            }
            if path
                .metadata()
                .and_then(|metadata| metadata.modified())
                .is_ok_and(|time| time < cutoff)
            {
                let _ = fs::remove_file(path);
            }
        }
    }
}

pub struct JobWriteSession<'a> {
    registry: &'a JobRegistry,
    root: PathBuf,
}
impl JobWriteSession<'_> {
    pub fn load(&self, name: &str) -> Result<Job, StoreError> {
        if name.is_empty() {
            return Err(StoreError::Invalid("이름이 비어 있습니다".into()));
        }
        self.registry
            .load_at(&self.registry.path_for(name), &self.root)
    }
    pub fn list_jobs_with_corruption(
        &self,
    ) -> Result<(Vec<Job>, Vec<CorruptJobEntry>), StoreError> {
        self.registry.list_at(&self.root)
    }
    pub fn save(&self, job: &mut Job, allow_overwrite: bool) -> Result<(), StoreError> {
        fs::create_dir_all(&self.registry.directory)?;
        let path = self.registry.path_for(&job.name);
        let previous = if path.exists() {
            match self.registry.load_at(&path, &self.root) {
                Ok(existing) => {
                    if !allow_overwrite && existing.name != job.name {
                        return Err(StoreError::Collision(format!(
                            "작업 '{}' 과 기존 작업 '{}' 이 같은 파일({})로 매핑됩니다. 저장하면 '{}' 이 소실됩니다.",
                            job.name,
                            existing.name,
                            path.file_name().unwrap_or_default().to_string_lossy(),
                            existing.name
                        )));
                    }
                    Some(existing)
                }
                Err(_) if !allow_overwrite => {
                    return Err(StoreError::Collision(format!(
                        "작업 '{}' 저장 대상 파일 {} 이 이미 있으나 손상돼 소유 작업을(를) 확인할 수 없습니다.",
                        job.name,
                        path.file_name().unwrap_or_default().to_string_lossy()
                    )));
                }
                Err(_) => None,
            }
        } else {
            None
        };
        advance_revisions(job, previous.as_ref())?;
        let key = library_key_for(Path::new(&job.template_path), &self.root);
        let encoded = encode_job(job, &key)?;
        let bytes = serde_json::to_vec_pretty(&encoded)
            .map_err(|error| StoreError::Io(io::Error::new(io::ErrorKind::InvalidData, error)))?;
        write_bytes_atomic(&path, &bytes)?;
        Ok(())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{CorruptJobEntry, JobRegistry, StoreError};
    use hwpx_filler::job::Job;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use serde_json::{Map, Value, json};
    use std::fs;
    use std::path::Path;
    use std::sync::{Arc, mpsc};
    use std::thread;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};

    fn assert_review_baseline(registry: &JobRegistry) {
        use hwpx_filler::job::rules_fingerprints;
        use hwpx_filler::review_state::review_requirement;
        let mut ran = Job {
            name: "검토 기준".into(),
            filename_pattern: "실행한 규칙".into(),
            ..Job::default()
        };
        registry.save(&mut ran, false).unwrap();
        assert!(review_requirement(&registry.load(&ran.name).unwrap(), &[]).first_run);
        let unknown = registry.stamp_last_run(&ran.name, "unknown", None).unwrap();
        assert!(unknown.reviewed_rules.is_empty());
        assert!(review_requirement(&unknown, &[]).unknown_baseline);
        let ran_rules = rules_fingerprints(&ran);
        registry
            .stamp_last_run(&ran.name, "completed", Some(&ran_rules))
            .unwrap();
        let completed = registry.load(&ran.name).unwrap();
        assert_eq!(completed.last_run_at, "completed");
        assert!(!review_requirement(&completed, &[]).required());
        let mut edited = completed;
        edited.filename_pattern = "다음 실행 규칙".into();
        registry.save(&mut edited, false).unwrap();
        registry
            .stamp_last_run(&ran.name, "old run completed", Some(&ran_rules))
            .unwrap();
        let after = registry.load(&ran.name).unwrap();
        assert_eq!(after.last_run_at, "old run completed");
        assert_eq!(after.reviewed_rules, ran_rules);
        assert_eq!(after.filename_pattern, "다음 실행 규칙");
        assert!(review_requirement(&after, &[]).required());
        registry
            .stamp_last_run(&ran.name, "unknown run", None)
            .unwrap();
        assert_eq!(registry.load(&ran.name).unwrap().reviewed_rules, ran_rules);
        registry.delete(&ran.name).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn second_process_writer_refuses_before_changing_job_files() {
        use std::os::windows::process::CommandExt;
        use std::process::Command;

        if let Some(root) = std::env::var_os("HWPX_JOB_WRITER_PROBE_ROOT") {
            let locations = crate::locations::Locations::from_env().unwrap();
            assert_eq!(locations.home(), Path::new(&root));
            assert_eq!(locations.jobs(), Path::new(&root).join("jobs"));
            let registry = JobRegistry::new(Path::new(&root).to_path_buf(), || {
                Path::new("C:/templates").to_path_buf()
            })
            .unwrap();
            let mut intruder = Job {
                name: "intruder".into(),
                template_path: "intruder.hwpx".into(),
                ..Job::default()
            };
            let code = match registry.save(&mut intruder, false) {
                Ok(()) => 0,
                Err(StoreError::Ownership(_)) => 21,
                Err(_) => 22,
            };
            std::process::exit(code);
        }

        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-job-process-{}-{stamp}",
            std::process::id()
        ));
        let directory = sandbox.join("jobs");
        let owner = JobRegistry::new(directory.clone(), || "C:/templates".into()).unwrap();
        let mut existing = Job {
            name: "existing".into(),
            template_path: "owner.hwpx".into(),
            ..Job::default()
        };
        owner.save(&mut existing, false).unwrap();
        let before = fs::read(owner.path_for("existing")).unwrap();
        let child = |path: &Path| {
            Command::new(std::env::current_exe().unwrap())
                .creation_flags(0x0800_0000)
                .arg("--exact")
                .arg("job_registry::tests::second_process_writer_refuses_before_changing_job_files")
                .env("HWPX_JOB_WRITER_PROBE_ROOT", path)
                .env("HWPXFILLER_HOME", path)
                .output()
                .unwrap()
        };
        let denied = child(&directory);
        assert_eq!(denied.status.code(), Some(21), "{denied:?}");
        assert_eq!(fs::read(owner.path_for("existing")).unwrap(), before);
        assert!(!owner.path_for("intruder").exists());
        let alias = child(&directory.join(".").join("child").join(".."));
        assert_eq!(alias.status.code(), Some(21), "{alias:?}");
        let independent = child(&sandbox.join("other"));
        assert_eq!(independent.status.code(), Some(0), "{independent:?}");
        drop(owner);
        let released = child(&directory);
        assert_eq!(released.status.code(), Some(0), "{released:?}");
        fs::remove_dir_all(sandbox).unwrap();
    }

    fn assert_save_contract(registry: &JobRegistry, job: &mut Job) {
        assert!(!registry.exists(&job.name));
        assert!(registry.load(&job.name).is_err());
        assert!(registry.names().unwrap().is_empty());
        registry.delete("missing").unwrap();
        assert!(registry.soft_delete("missing").is_err());
        for version in [0, 1, 3] {
            job.version = version;
            assert!(registry.save(job, false).is_err());
            assert!(!registry.path_for(&job.name).exists());
        }
        job.version = 2;
        registry.save(job, false).unwrap();
        let before = fs::read(registry.path_for(&job.name)).unwrap();
        for version in [0, 1, 3] {
            job.version = version;
            assert!(registry.save(job, true).is_err());
            assert_eq!(fs::read(registry.path_for(&job.name)).unwrap(), before);
            assert_eq!(registry.load(&job.name).unwrap().version, 2);
        }
        job.version = 2;
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let _locked = fs::OpenOptions::new()
                .read(true)
                .share_mode(1)
                .open(registry.path_for(&job.name))
                .unwrap();
            let mut edited = job.clone();
            edited.filename_pattern = "must not replace a locked file".into();
            assert!(registry.save(&mut edited, true).is_err());
            assert_eq!(fs::read(registry.path_for(&job.name)).unwrap(), before);
        }
        let loaded = registry.load(&job.name).unwrap();
        assert_eq!(
            Value::Object(
                loaded
                    .mapping
                    .apply(
                        &serde_json::from_value(json!({"price":"21326800"})).unwrap(),
                        None
                    )
                    .unwrap()
            ),
            json!({"추정가격":"21,326,800"})
        );
    }

    fn assert_corruption_contract(registry: &JobRegistry, valid: &Job) -> CorruptJobEntry {
        let path = registry.path_for("broken");
        let mut tagged = hwpx_filler::job::encode_job(valid, "").unwrap();
        tagged["tags"] = json!({"금액구간":123});
        let mut timed = hwpx_filler::job::encode_job(valid, "").unwrap();
        timed["last_run_at"] = json!(1720000000);
        let mut replacement = Job {
            name: "broken".into(),
            ..Job::default()
        };
        for bytes in [
            b"not json".to_vec(),
            b"[1,2,3]".to_vec(),
            serde_json::to_vec(&tagged).unwrap(),
            serde_json::to_vec(&timed).unwrap(),
        ] {
            fs::write(&path, &bytes).unwrap();
            assert!(matches!(
                registry.save(&mut replacement, false),
                Err(StoreError::Collision(_))
            ));
            assert_eq!(fs::read(&path).unwrap(), bytes);
            let (jobs, corrupted) = registry.list_jobs_with_corruption().unwrap();
            assert_eq!(jobs.len(), 1);
            assert_eq!(jobs[0].name, valid.name);
            assert_eq!(registry.names().unwrap(), std::slice::from_ref(&valid.name));
            assert_eq!(corrupted.len(), 1);
            assert_eq!(corrupted[0].file_name, "broken.job.json");
            assert_eq!(Path::new(&corrupted[0].token), path);
            assert!(!corrupted[0].error.is_empty());
        }
        let corrupted = registry.list_jobs_with_corruption().unwrap().1.remove(0);
        registry.save(&mut replacement, true).unwrap();
        let recovered = registry.load("broken").unwrap();
        assert_eq!(
            (recovered.template_revision, recovered.binding_revision),
            (1, 1)
        );
        assert_eq!(recovered.previous_rules, json!({}));
        let recovered_bytes = fs::read(&path).unwrap();
        assert!(registry.remove_corrupt_entry(&corrupted.token).is_err());
        assert_eq!(fs::read(&path).unwrap(), recovered_bytes);
        assert_eq!(
            registry.names().unwrap(),
            [valid.name.clone(), "broken".into()]
        );
        fs::write(&path, b"not json").unwrap();
        corrupted
    }

    fn assert_revision_history(registry: &JobRegistry, original: &Job) {
        let mut job = original.clone();
        job.name = "revision".into();
        registry.save(&mut job, false).unwrap();
        registry.save(&mut job, false).unwrap();
        let loaded = registry.load(&job.name).unwrap();
        assert_eq!((loaded.template_revision, loaded.binding_revision), (1, 1));
        assert_eq!(loaded.previous_rules, json!({}));
        job.mapping.mappings[0].source = "new-price".into();
        registry.save(&mut job, true).unwrap();
        let loaded = registry.load(&job.name).unwrap();
        assert_eq!((loaded.template_revision, loaded.binding_revision), (1, 2));
        assert_eq!(
            loaded.previous_rules["fields"]["추정가격"]["source"],
            "price"
        );
        job.template_path = "C:/other/new.hwpx".into();
        registry.save(&mut job, true).unwrap();
        let loaded = registry.load(&job.name).unwrap();
        assert_eq!((loaded.template_revision, loaded.binding_revision), (2, 2));
        assert_eq!(loaded.previous_rules["template"], original.template_path);
        assert_eq!(
            loaded.previous_rules["fields"]["추정가격"]["source"],
            "price"
        );
        registry.set_favorite(&job.name, true, None).unwrap();
        let first = registry.load(&job.name).unwrap().favorited_at;
        let second = registry
            .set_favorite(&original.name, true, None)
            .unwrap()
            .favorited_at;
        assert!(first < second);
        registry.set_favorite(&original.name, false, None).unwrap();
        registry.set_group(&job.name, "metadata").unwrap();
        let stamped = registry.stamp_last_run(&job.name, "now", None).unwrap();
        assert_eq!(
            (stamped.template_revision, stamped.binding_revision),
            (2, 2)
        );
        assert_eq!(stamped.previous_rules, loaded.previous_rules);
        assert!(!stamped.favorited_at.is_empty());
        registry.rename(&job.name, "other-revision").unwrap();
        assert_eq!(
            registry.load("other-revision").unwrap().previous_rules,
            loaded.previous_rules
        );
        registry.delete("other-revision").unwrap();
        assert!(registry.load("other-revision").is_err());
    }

    fn assert_trash_retention(registry: &JobRegistry) {
        let mut job = Job {
            name: "retention".into(),
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let trash = registry.directory().join(".trash");
        fs::create_dir_all(&trash).unwrap();
        let stale = trash.join("old.job.json");
        let locked = trash.join("locked.job.json");
        let unrelated = trash.join("old.txt");
        let recent = trash.join("recent.job.json");
        let old_time = SystemTime::now() - Duration::from_secs(31 * 24 * 60 * 60);
        for path in [&stale, &locked, &unrelated] {
            let file = fs::File::create(path).unwrap();
            file.set_modified(old_time).unwrap();
        }
        fs::write(&recent, b"recent").unwrap();
        #[cfg(windows)]
        let held = {
            use std::os::windows::fs::OpenOptionsExt;
            fs::OpenOptions::new()
                .read(true)
                .share_mode(1)
                .open(&locked)
                .unwrap()
        };
        let slot = registry.soft_delete(&job.name).unwrap();
        assert_eq!(slot.trashed.parent(), Some(trash.as_path()));
        assert!(slot.trashed.is_file());
        assert!(!stale.exists());
        assert!(unrelated.exists());
        assert_eq!(fs::read(&recent).unwrap(), b"recent");
        #[cfg(windows)]
        {
            assert!(locked.exists());
            drop(held);
        }
        assert_eq!(registry.restore_soft_deleted(&slot).unwrap(), job.name);
        let slot = registry.soft_delete(&job.name).unwrap();
        assert!(!locked.exists());
        fs::remove_file(&slot.trashed).unwrap();
        assert_eq!(
            registry
                .restore_soft_deleted(&slot)
                .unwrap_err()
                .to_string(),
            "되돌릴 작업 파일을 찾을 수 없습니다."
        );
    }

    fn assert_concurrent_edits(registry: &Arc<JobRegistry>) {
        let mut job = Job {
            name: "concurrent".into(),
            filename_pattern: "original".into(),
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let (started_tx, started_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();
        let template_root = registry.template_root.clone();
        let editing =
            JobRegistry::new(registry.directory.clone(), move || template_root()).unwrap();
        let worker = registry
            .transaction(|session| {
                let mut loaded = session.load(&job.name)?;
                let handle = thread::spawn(move || {
                    started_tx.send(()).unwrap();
                    done_tx
                        .send(
                            editing
                                .mutate("concurrent", |job| job.filename_pattern = "edited".into()),
                        )
                        .unwrap();
                });
                started_rx.recv().unwrap();
                assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
                loaded.last_run_at = "stamped".into();
                session.save(&mut loaded, false)?;
                Ok(handle)
            })
            .unwrap();
        let edited = done_rx
            .recv_timeout(Duration::from_secs(3))
            .unwrap()
            .unwrap();
        worker.join().unwrap();
        assert_eq!(edited.last_run_at, "stamped");
        assert_eq!(edited.filename_pattern, "edited");
        assert_eq!(registry.load("concurrent").unwrap(), edited);
        registry.delete("concurrent").unwrap();
    }

    fn assert_relink_contract(registry: &JobRegistry) {
        let mut job = Job {
            name: "relink".into(),
            template_path: "old.docx".into(),
            last_run_at: "old-run".into(),
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let mut tags = serde_json::from_value(json!({"지역":"본청"})).unwrap();
        registry.set_tags(&job.name, &tags).unwrap();
        tags.insert("지역".into(), json!("대전"));
        assert_eq!(registry.load(&job.name).unwrap().tags["지역"], "본청");
        let changed = registry
            .relink_template(&job.name, "new.hwpx", None)
            .unwrap();
        assert_eq!(changed.template_path, "new.hwpx");
        assert_eq!(changed.last_run_at, "");
        let bytes = fs::read(registry.path_for(&job.name)).unwrap();
        match registry
            .relink_template(&job.name, "draft.txt", None)
            .unwrap_err()
        {
            StoreError::CrossMedia {
                old_path,
                new_media,
            } => {
                assert_eq!(old_path, "new.hwpx");
                assert_eq!(new_media, "txt");
            }
            other => panic!("unexpected relink refusal: {other}"),
        }
        assert_eq!(fs::read(registry.path_for(&job.name)).unwrap(), bytes);
        assert_eq!(
            registry
                .relink_template(&job.name, "another.hwpx", None)
                .unwrap()
                .template_path,
            "another.hwpx"
        );
        registry.delete(&job.name).unwrap();
    }

    fn stored_files(directory: &Path) -> std::collections::BTreeMap<std::path::PathBuf, Vec<u8>> {
        [directory.to_path_buf(), directory.join(".trash")]
            .into_iter()
            .flat_map(|root| fs::read_dir(root).unwrap())
            .map(|entry| {
                let path = entry.unwrap().path();
                let bytes = if path.is_file() {
                    fs::read(&path).unwrap()
                } else {
                    b"directory".to_vec()
                };
                (path, bytes)
            })
            .collect()
    }

    fn outside_transaction_writes(block: &syn::Block) -> Vec<String> {
        use syn::visit::{self, Visit};
        #[derive(Default)]
        struct Writes(Vec<String>);
        impl<'ast> Visit<'ast> for Writes {
            fn visit_expr_method_call(&mut self, node: &'ast syn::ExprMethodCall) {
                if (node.method == "transaction" || node.method == "mutate")
                    && matches!(node.receiver.as_ref(), syn::Expr::Path(path) if path.path.is_ident("self"))
                {
                    return;
                }
                visit::visit_expr_method_call(self, node);
            }
            fn visit_expr_call(&mut self, node: &'ast syn::ExprCall) {
                if let syn::Expr::Path(path) = node.func.as_ref() {
                    let name = path
                        .path
                        .segments
                        .iter()
                        .map(|part| part.ident.to_string())
                        .collect::<Vec<_>>()
                        .join("::");
                    if name.starts_with("fs::")
                        || ["move_exclusive", "write_bytes_atomic", "purge_trash"]
                            .contains(&name.as_str())
                    {
                        self.0.push(name);
                    }
                }
                visit::visit_expr_call(self, node);
            }
        }
        let mut writes = Writes::default();
        writes.visit_block(block);
        writes.0
    }

    fn public_registry_methods(readers: &[&str]) -> std::collections::BTreeSet<String> {
        let sources = [
            include_str!("job_registry.rs"),
            include_str!("job_registry/groups.rs"),
            include_str!("job_registry/lifecycle.rs"),
        ];
        let items = sources
            .into_iter()
            .flat_map(|source| syn::parse_file(source).unwrap().items);
        let mut names = std::collections::BTreeSet::new();
        for item in items {
            let syn::Item::Impl(implementation) = item else {
                continue;
            };
            let syn::Type::Path(owner) = implementation.self_ty.as_ref() else {
                continue;
            };
            if !owner.path.is_ident("JobRegistry") {
                continue;
            }
            for member in implementation.items {
                if let syn::ImplItem::Fn(method) = member
                    && matches!(method.vis, syn::Visibility::Public(_))
                {
                    let name = method.sig.ident.to_string();
                    if !readers.contains(&name.as_str()) {
                        assert!(
                            outside_transaction_writes(&method.block).is_empty(),
                            "filesystem operation escaped the writer transaction: {name}"
                        );
                    }
                    names.insert(name);
                }
            }
        }
        names
    }

    #[cfg(windows)]
    #[test]
    fn every_public_writer_requires_ownership_before_changing_stored_files() {
        use crate::single_instance::{Acquisition, acquire_named};

        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-job-writers-{}",
            uuid::Uuid::new_v4().simple()
        ));
        let directory = sandbox.join("jobs");
        let registry = JobRegistry::new(directory.clone(), || "C:/library".into()).unwrap();
        for name in ["A", "removed"] {
            let mut job = Job {
                name: name.into(),
                template_path: "a.hwpx".into(),
                group: "G".into(),
                authority_id: "owned".into(),
                ..Job::default()
            };
            registry.save(&mut job, false).unwrap();
        }
        let deleted = registry.soft_delete("removed").unwrap();
        let broken = registry.path_for("broken");
        fs::write(&broken, b"invalid json").unwrap();
        let before = stored_files(&directory);
        drop(registry);
        let _owner = match acquire_named(&crate::job_writer_lease::mutex_name(&directory).unwrap())
            .unwrap()
        {
            Acquisition::Primary(owner) => owner,
            Acquisition::Existing => panic!("fresh directory unexpectedly owned"),
        };
        let registry = JobRegistry::new(directory.clone(), || "C:/library".into()).unwrap();
        let mut added = Job {
            name: "new".into(),
            ..Job::default()
        };
        let tags = serde_json::from_value(json!({"지역":"본청"})).unwrap();
        let writes = [
            ("transaction", registry.transaction(|_| Ok(()))),
            ("save", registry.save(&mut added, false)),
            (
                "mutate",
                registry
                    .mutate("A", |job| job.filename_pattern = "changed".into())
                    .map(drop),
            ),
            (
                "stamp_last_run",
                registry.stamp_last_run("A", "now", None).map(drop),
            ),
            (
                "assign_authority_id",
                registry.assign_authority_id("A", "another").map(drop),
            ),
            (
                "release_authority_id",
                registry.release_authority_id("A", "owned").map(drop),
            ),
            ("set_tags", registry.set_tags("A", &tags).map(drop)),
            (
                "set_favorite",
                registry.set_favorite("A", true, None).map(drop),
            ),
            (
                "relink_template",
                registry.relink_template("A", "new.hwpx", None).map(drop),
            ),
            ("clone_job", registry.clone_job("A").map(drop)),
            ("rename", registry.rename("A", "renamed")),
            ("delete", registry.delete("A")),
            ("soft_delete", registry.soft_delete("A").map(drop)),
            (
                "restore_soft_deleted",
                registry.restore_soft_deleted(&deleted).map(drop),
            ),
            ("set_group", registry.set_group("A", "H")),
            (
                "update_group_members",
                registry.update_group_members("G", "H").map(drop),
            ),
            ("rename_group", registry.rename_group("G", "H").map(drop)),
            ("disband_group", registry.disband_group("G").map(drop)),
            (
                "remove_corrupt_entry",
                registry.remove_corrupt_entry(broken.to_str().unwrap()),
            ),
        ];
        let readers = [
            "new",
            "directory",
            "path_for",
            "load",
            "exists",
            "list_jobs_with_corruption",
            "names",
            "groups",
            "content_fingerprint",
        ];
        let classified = readers
            .into_iter()
            .chain(writes.iter().map(|(name, _)| *name))
            .map(str::to_owned)
            .collect();
        assert_eq!(
            public_registry_methods(&readers),
            classified,
            "unclassified public registry method"
        );
        let unguarded = syn::parse_str("{ fs::remove_file(path)?; }").unwrap();
        assert_eq!(outside_transaction_writes(&unguarded), ["fs::remove_file"]);
        for (name, result) in writes {
            assert!(
                matches!(result, Err(StoreError::Ownership(_))),
                "{name}: {result:?}"
            );
        }
        assert_eq!(stored_files(&directory), before);
        assert_eq!(registry.names().unwrap(), ["A"]);
        assert_eq!(registry.load("A").unwrap().authority_id, "owned");
        fs::remove_dir_all(sandbox).unwrap();
    }

    #[test]
    fn transaction_preserves_revision_and_collision_and_isolates_corruption() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-job-registry-{}-{stamp}",
            std::process::id()
        ));
        let root = sandbox.join("templates");
        fs::create_dir_all(&root).unwrap();
        let registry =
            Arc::new(JobRegistry::new(sandbox.join("jobs"), move || root.clone()).unwrap());
        let mut job = Job {
            name: "a/b".into(),
            template_path: "C:/outside/a.hwpx".into(),
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("추정가격", "price", "amount", "", "{:,}", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            tags: serde_json::from_value(json!({"부서":"계약"})).unwrap(),
            ..Job::default()
        };
        assert_save_contract(&registry, &mut job);
        assert_revision_history(&registry, &job);
        assert_trash_retention(&registry);
        assert_concurrent_edits(&registry);
        assert_relink_contract(&registry);
        assert_review_baseline(&registry);
        registry
            .transaction(|session| {
                let mut loaded = session.load("a/b")?;
                loaded.filename_pattern = "renamed".into();
                session.save(&mut loaded, false)?;
                Ok(())
            })
            .unwrap();
        assert_eq!(registry.load("a/b").unwrap().binding_revision, 2);
        let prior_stamp = registry.load("a/b").unwrap();
        assert_eq!(
            registry
                .assign_authority_id("a/b", "first")
                .unwrap()
                .authority_id,
            "first"
        );
        assert_eq!(
            registry
                .assign_authority_id("a/b", "other")
                .unwrap()
                .authority_id,
            "first"
        );
        assert_eq!(
            registry
                .release_authority_id("a/b", "other")
                .unwrap()
                .authority_id,
            "first"
        );
        assert_eq!(
            registry
                .release_authority_id("a/b", "first")
                .unwrap()
                .authority_id,
            ""
        );
        let rules = serde_json::from_value(serde_json::json!({"field": "v1"})).unwrap();
        let stamped = registry
            .stamp_last_run("a/b", "2026-11-05T10:11:12", Some(&rules))
            .unwrap();
        assert_eq!(stamped.last_run_at, "2026-11-05T10:11:12");
        assert_eq!(stamped.reviewed_rules, rules);
        let mut expected = prior_stamp;
        expected.last_run_at = stamped.last_run_at.clone();
        expected.reviewed_rules = rules.clone();
        assert_eq!(stamped, expected);
        assert_eq!(
            registry
                .set_favorite("a/b", true, Some("2026-11-05T10:12:13"))
                .unwrap()
                .favorited_at,
            "2026-11-05T10:12:13"
        );
        assert_eq!(
            registry
                .set_favorite("a/b", true, Some("later"))
                .unwrap()
                .favorited_at,
            "2026-11-05T10:12:13"
        );
        assert_eq!(
            registry
                .set_favorite("a/b", false, None)
                .unwrap()
                .favorited_at,
            ""
        );
        assert!(
            registry
                .relink_template(
                    "a/b",
                    "C:/other/other.hwpx",
                    Some(("", "C:/other/stale.hwpx"))
                )
                .is_err()
        );
        assert!(matches!(
            registry.relink_template("a/b", "C:/other/new.txt", None),
            Err(StoreError::CrossMedia { .. })
        ));
        assert_eq!(
            registry.load("a/b").unwrap().template_path,
            "C:/outside/a.hwpx"
        );
        let mut collision = Job {
            name: "a_b".into(),
            ..Job::default()
        };
        assert!(matches!(
            registry.save(&mut collision, false),
            Err(StoreError::Collision(_))
        ));
        let corrupted = assert_corruption_contract(&registry, &job);
        assert_eq!(registry.load("a/b").unwrap().name, "a/b");
        registry.rename("a/b", "a_b").unwrap();
        assert_eq!(registry.load("a_b").unwrap().binding_revision, 2);
        assert_eq!(
            registry.load("a_b").unwrap().previous_rules["filename"],
            hwpx_filler::job::DEFAULT_FILENAME_PATTERN
        );
        registry.rename("a_b", "a/b").unwrap();
        let before = fs::read(registry.path_for("a/b")).unwrap();
        registry.rename("a/b", "a/b").unwrap();
        assert_eq!(fs::read(registry.path_for("a/b")).unwrap(), before);
        registry.set_group("a/b", " first ").unwrap();
        registry
            .set_favorite("a/b", true, Some("first favorite"))
            .unwrap();
        let copy = registry.clone_job("a/b").unwrap();
        assert_eq!(copy, "a/b (복사본)");
        let cloned = registry.load(&copy).unwrap();
        assert_eq!(cloned.last_run_at, "");
        assert_eq!(cloned.favorited_at, "");
        assert_eq!(cloned.authority_id, "");
        assert!(cloned.reviewed_rules.is_empty());
        assert!(hwpx_filler::review_state::review_requirement(&cloned, &[]).first_run);
        assert_eq!((cloned.template_revision, cloned.binding_revision), (1, 1));
        assert_eq!(cloned.previous_rules, json!({}));
        assert_eq!(cloned.group, "first");
        assert_eq!(cloned.mapping, job.mapping);
        registry.set_group(&copy, "first").unwrap();
        assert_eq!(registry.groups().unwrap(), ["first"]);
        assert_eq!(registry.rename_group("first", "second").unwrap(), 2);
        assert!(registry.rename_group("second", "  ").is_err());
        for name in ["  ", "a/b"] {
            assert!(registry.rename(&copy, name).is_err());
            assert_eq!(registry.load(&copy).unwrap().name, copy);
            assert_eq!(registry.load("a/b").unwrap().name, "a/b");
        }
        registry.rename(&copy, "copy").unwrap();
        assert!(!registry.exists(&copy));
        assert_eq!(registry.load("copy").unwrap().group, "second");
        registry.set_group("copy", "third").unwrap();
        assert_eq!(registry.rename_group("third", "second").unwrap(), 1);
        assert_eq!(registry.groups().unwrap(), ["second"]);
        assert_eq!(registry.disband_group("second").unwrap(), 2);
        assert!(registry.groups().unwrap().is_empty());
        assert_eq!(registry.load("a/b").unwrap().group, "");
        assert_eq!(registry.load("copy").unwrap().group, "");
        assert!(registry.disband_group("").is_err());
        let slot = registry.soft_delete("copy").unwrap();
        assert!(!registry.exists("copy"));
        let removed_bytes = fs::read(&slot.trashed).unwrap();
        let mut replacement = Job {
            name: "copy".into(),
            template_path: "new.hwpx".into(),
            ..Job::default()
        };
        registry.save(&mut replacement, false).unwrap();
        assert!(
            registry
                .restore_soft_deleted(&slot)
                .unwrap_err()
                .to_string()
                .contains("같은 이름의 작업이 이미 있어")
        );
        assert_eq!(registry.load("copy").unwrap().template_path, "new.hwpx");
        assert_eq!(fs::read(&slot.trashed).unwrap(), removed_bytes);
        registry.delete("copy").unwrap();
        assert_eq!(registry.restore_soft_deleted(&slot).unwrap(), "copy");
        assert!(registry.restore_soft_deleted(&slot).is_err());
        assert!(registry.remove_corrupt_entry("outside").is_err());
        registry.remove_corrupt_entry(&corrupted.token).unwrap();
        assert!(!registry.directory().join("broken.job.json").exists());
        let copies = (0..4)
            .map(|_| {
                let registry = registry.clone();
                thread::spawn(move || registry.clone_job("a/b").unwrap())
            })
            .collect::<Vec<_>>();
        let names = copies
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect::<std::collections::HashSet<_>>();
        assert_eq!(names.len(), 4);
        for name in names {
            assert_eq!(registry.load(&name).unwrap().name, name);
        }

        // The public delete waits until an in-flight stamp transaction releases its writer lease.
        let (started_tx, started_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();
        let deleting = registry.clone();
        let deleter = registry
            .transaction(|session| {
                let mut stamped = session.load("a/b")?;
                let handle = thread::spawn(move || {
                    started_tx.send(()).unwrap();
                    done_tx.send(deleting.delete("a/b")).unwrap();
                });
                started_rx.recv().unwrap();
                assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
                stamped.last_run_at = "2026-11-05T10:13:14".into();
                session.save(&mut stamped, false)?;
                Ok(handle)
            })
            .unwrap();
        deleter.join().unwrap();
        done_rx.recv().unwrap().unwrap();
        assert!(!registry.exists("a/b"));
        assert!(registry.stamp_last_run("a/b", "later", None).is_err());
        assert!(!registry.exists("a/b"));
        fs::remove_dir_all(sandbox).unwrap();
    }

    #[test]
    fn template_links_survive_home_moves_without_rebinding_or_rewriting_reads() {
        use std::sync::RwLock;
        use std::sync::atomic::{AtomicUsize, Ordering};

        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-job-links-{}-{stamp}",
            std::process::id()
        ));
        let home = sandbox.join("home-A");
        let root = home.join("templates");
        fs::create_dir_all(root.join("조달")).unwrap();
        let source = root.join("조달/공고서.hwpx");
        fs::write(&source, b"original").unwrap();
        let selected_root = Arc::new(RwLock::new(root.clone()));
        let reads = Arc::new(AtomicUsize::new(0));
        let registry = JobRegistry::new(home.join("jobs"), {
            let selected_root = selected_root.clone();
            let reads = reads.clone();
            move || {
                reads.fetch_add(1, Ordering::Relaxed);
                selected_root.read().unwrap().clone()
            }
        })
        .unwrap();
        let mut job = Job {
            name: "a".into(),
            template_path: source.to_str().unwrap().into(),
            ..Job::default()
        };
        for _ in 0..2 {
            reads.store(0, Ordering::Relaxed);
            registry.save(&mut job, false).unwrap();
            assert_eq!(reads.load(Ordering::Relaxed), 1);
        }
        let baseline = hwpx_filler::job::rules_fingerprints(&job);
        registry
            .stamp_last_run("a", "completed", Some(&baseline))
            .unwrap();
        assert!(
            !hwpx_filler::review_state::review_requirement(&registry.load("a").unwrap(), &[])
                .required()
        );
        let before = fs::read(registry.path_for("a")).unwrap();
        let stored: Value = serde_json::from_slice(&before).unwrap();
        assert_eq!(stored["template_key"], "조달/공고서.hwpx");
        assert_eq!(stored["template_path"], source.to_str().unwrap());
        let other = sandbox.join("other");
        fs::create_dir_all(other.join("조달")).unwrap();
        fs::write(other.join("조달/공고서.hwpx"), b"decoy").unwrap();
        *selected_root.write().unwrap() = other;
        assert_eq!(registry.load("a").unwrap().template_path, job.template_path);
        fs::remove_file(&source).unwrap();
        assert_eq!(registry.load("a").unwrap().template_path, job.template_path);
        assert_eq!(registry.list_jobs_with_corruption().unwrap().0.len(), 1);
        assert_eq!(fs::read(registry.path_for("a")).unwrap(), before);
        fs::write(&source, b"original").unwrap();
        *selected_root.write().unwrap() = root.clone();
        let noisy = root.join("조달/sub/../공고서.hwpx");
        let mut normalized = Job {
            name: "normalized".into(),
            template_path: noisy.to_str().unwrap().into(),
            ..Job::default()
        };
        registry.save(&mut normalized, false).unwrap();
        let normalized_bytes = fs::read(registry.path_for("normalized")).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&normalized_bytes).unwrap()["template_key"],
            "조달/공고서.hwpx"
        );
        assert!(registry.load("normalized").is_ok());
        let outside = sandbox.join("outside/공고서.hwpx");
        let mut external = Job {
            name: "outside".into(),
            template_path: outside.to_str().unwrap().into(),
            ..Job::default()
        };
        registry.save(&mut external, false).unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&fs::read(registry.path_for("outside")).unwrap())
                .unwrap()["template_key"],
            ""
        );
        drop(registry);

        let moved = sandbox.join("home-B");
        fs::rename(&home, &moved).unwrap();
        let moved_root = moved.join("templates");
        let registry = JobRegistry::new(moved.join("jobs"), move || moved_root.clone()).unwrap();
        let restored = registry.load("a").unwrap();
        let requirement = hwpx_filler::review_state::review_requirement(&restored, &[]);
        assert!(!requirement.required() && requirement.structure_changed);
        assert_eq!(restored.reviewed_rules, baseline);
        assert_eq!(
            restored.reviewed_rules["template"],
            source.to_str().unwrap()
        );
        assert_eq!(
            Path::new(&restored.template_path),
            moved.join("templates/조달/공고서.hwpx")
        );
        assert_eq!(
            hwpx_filler::job::template_media(&restored.template_path),
            "hwpx"
        );
        assert_eq!(
            registry.load("outside").unwrap().template_path,
            external.template_path
        );
        assert_eq!(
            Path::new(&registry.load("normalized").unwrap().template_path),
            moved.join("templates/조달/공고서.hwpx")
        );
        assert!(registry.list_jobs_with_corruption().unwrap().1.is_empty());
        assert_eq!(fs::read(registry.path_for("a")).unwrap(), before);
        assert_eq!(
            fs::read(registry.path_for("normalized")).unwrap(),
            normalized_bytes
        );
        let mut corrupt = stored.clone();
        corrupt["template_path"] = json!("");
        for key in [
            json!("C:/훔친/x.hwpx"),
            json!("/x.hwpx"),
            json!("../../x.hwpx"),
            json!("조달/../../x.hwpx"),
            json!(r"\\srv\x.hwpx"),
            json!(7),
        ] {
            corrupt["template_key"] = key;
            fs::write(
                registry.path_for("a"),
                serde_json::to_vec(&corrupt).unwrap(),
            )
            .unwrap();
            assert!(registry.load("a").is_err());
            let (jobs, corruptions) = registry.list_jobs_with_corruption().unwrap();
            assert_eq!(jobs.len(), 2);
            assert_eq!(corruptions.len(), 1);
            assert_eq!(corruptions[0].file_name, "a.job.json");
            assert!(corruptions[0].error.contains("template_key"));
        }
        fs::remove_dir_all(sandbox).unwrap();
    }

    #[test]
    fn stored_json_matches_python_v2_bytes_with_non_ascii_and_ordered_tags() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-job-bytes-{}-{stamp}",
            std::process::id()
        ));
        let registry = JobRegistry::new(sandbox.join("jobs"), || "C:/library".into()).unwrap();
        let mut job = Job {
            name: "테스트".into(),
            template_path: "C:/other/서식.hwpx".into(),
            group: "내 그룹".into(),
            ..Job::default()
        };
        job.tags.insert("용도".into(), "계약".into());
        job.tags.insert("상태".into(), "검토".into());
        registry.save(&mut job, false).unwrap();
        // Python encode_job + json.dumps(ensure_ascii=False, indent=2), with the same Job.
        assert_eq!(
            fs::read(registry.path_for("테스트")).unwrap(),
            include_bytes!("../tests/fixtures/job-store-v2.json")
        );
        fs::remove_dir_all(sandbox).unwrap();
    }
}
