//! Cleanup of practice copies left in the user home by older app versions.

use crate::dataset_registry::DatasetPoolRegistry;
use crate::directory_lock::DirectoryLock;
use crate::job_registry::JobRegistry;
use crate::job_writer_lease::JobWriterLease;
use crate::settings_store::{mutate, read_with_alert};
use crate::single_instance::{normalize_windows_path, resolved_home};
use crate::tutorial_workspace::{ORIGINALS, fingerprint};
use hwpx_filler::text_render::python_repr;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::error::Error;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Arc;

pub type CleanupError = Box<dyn Error + Send + Sync>;
const UNREADABLE: &str = "읽을 수 없는 작업이나 등록 데이터가 있어 연습 파일 정리를 중단했습니다.";
const CHANGED: &str = "연습 파일 상태가 바뀌었습니다. 정리 내용을 다시 확인하세요.";
const MISSING: &str = "연습 파일이 없거나 이동했습니다.";

fn preview_token(rows: &[Value]) -> String {
    let representation = python_repr(&Value::Array(rows.to_vec()));
    let digest = Sha256::digest(representation.as_bytes());
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub struct LegacyPractice {
    pub template_root: PathBuf,
    pub data_root: PathBuf,
    pub settings_path: PathBuf,
    jobs: Arc<JobRegistry>,
    pools: Arc<DatasetPoolRegistry>,
    job_lease: JobWriterLease,
    pool_lock: DirectoryLock,
    alert: Arc<dyn Fn(&str) + Send + Sync>,
}

#[derive(Clone, Copy)]
enum Action {
    Keep,
    Unlink,
    Forget,
}

impl LegacyPractice {
    pub fn new(
        template_root: PathBuf,
        home: &Path,
        settings_path: PathBuf,
        jobs: Arc<JobRegistry>,
        pools: Arc<DatasetPoolRegistry>,
        alert: impl Fn(&str) + Send + Sync + 'static,
    ) -> io::Result<Self> {
        let job_lease = JobWriterLease::new(jobs.directory())?;
        let pool_lock = DirectoryLock::new(pools.directory())?;
        Ok(Self {
            template_root,
            data_root: home.join("tutorial_practice"),
            settings_path,
            jobs,
            pools,
            job_lease,
            pool_lock,
            alert: Arc::new(alert),
        })
    }

    fn manifest(&self) -> Result<Value, CleanupError> {
        let settings = read_with_alert(&self.settings_path, |message| (self.alert)(message))?;
        let manifest = settings
            .get("tutorial")
            .and_then(|value| value.get("practice"))
            .filter(|value| value.is_object())
            .cloned()
            .unwrap_or_else(|| json!({"version":1,"entries":[]}));
        if manifest.get("version") != Some(&json!(1))
            || !manifest.get("entries").is_some_and(Value::is_array)
        {
            return Err("연습 파일 기록을 읽을 수 없습니다. 파일 정리를 중단했습니다.".into());
        }
        Ok(manifest)
    }

    fn path_key(path: &Path) -> Result<String, CleanupError> {
        Ok(normalize_windows_path(&resolved_home(path))?.to_lowercase())
    }

    fn referenced(&self) -> Result<HashMap<String, &'static str>, CleanupError> {
        let (jobs, bad_jobs) = self.jobs.list_jobs_with_corruption()?;
        let (pool, bad_pool) = self.pools.list_references(None)?;
        if !bad_jobs.is_empty() || !bad_pool.is_empty() {
            return Err(UNREADABLE.into());
        }
        let mut paths = HashMap::new();
        for (_, item) in pool {
            for key in ["path", "db"] {
                if let Some(raw) = item
                    .opts
                    .get(key)
                    .and_then(Value::as_str)
                    .filter(|v| !v.is_empty())
                {
                    paths.insert(Self::path_key(Path::new(raw))?, "등록 데이터가 참조합니다.");
                }
            }
        }
        for job in jobs {
            for raw in [&job.template_path, &job.data_path] {
                if !raw.is_empty() {
                    paths.insert(Self::path_key(Path::new(raw))?, "저장한 작업이 참조합니다.");
                }
            }
        }
        Ok(paths)
    }

    fn validate(&self, entry: &Value) -> (bool, &'static str) {
        let checked = (|| -> Option<(bool, &'static str)> {
            let name = entry.get("name")?.as_str()?;
            let raw = entry.get("path")?.as_str()?;
            let digest = entry.get("sha256")?.as_str()?;
            let path = Path::new(raw);
            let root = if name.ends_with(".xlsx") {
                &self.data_root
            } else {
                &self.template_root
            };
            if !ORIGINALS.contains(&name) || !path.starts_with(root) {
                return Some((false, "연습 파일 경로를 확인할 수 없습니다."));
            }
            let meta = match fs::symlink_metadata(path) {
                Ok(meta) => meta,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    return Some((false, MISSING));
                }
                Err(_) => return None,
            };
            if meta.file_type().is_symlink() {
                return Some((false, "연습 파일 경로를 확인할 수 없습니다."));
            }
            if Self::path_key(path.parent()?).ok()? != Self::path_key(root).ok()? {
                return Some((false, "연습 파일이 다른 위치를 가리킵니다."));
            }
            if !meta.is_file() {
                return Some((false, MISSING));
            }
            let actual = fingerprint(path).ok()?;
            Some(if actual == digest {
                (true, "")
            } else {
                (false, "연습 파일이 수정됐습니다. 현재 파일을 보존합니다.")
            })
        })();
        checked.unwrap_or((false, "연습 파일 상태를 확인할 수 없습니다."))
    }

    fn vanished(&self, entry: &Value) -> bool {
        let Some(name) = entry.get("name").and_then(Value::as_str) else {
            return false;
        };
        let Some(batch) = entry
            .get("batch")
            .and_then(Value::as_str)
            .filter(|v| !v.is_empty())
        else {
            return false;
        };
        let Some(raw) = entry.get("path").and_then(Value::as_str) else {
            return false;
        };
        if !ORIGINALS.contains(&name) {
            return false;
        }
        let root = if name.ends_with(".xlsx") {
            &self.data_root
        } else {
            &self.template_root
        };
        let original = Path::new(name);
        let Some(stem) = original.file_stem().and_then(|v| v.to_str()) else {
            return false;
        };
        let Some(ext) = original.extension().and_then(|v| v.to_str()) else {
            return false;
        };
        let expected = root.join(format!("{stem} (연습 {batch}).{ext}"));
        if Path::new(raw) != expected {
            return false;
        }
        matches!(fs::symlink_metadata(raw), Err(error) if error.kind() == io::ErrorKind::NotFound)
    }

    fn scan(&self) -> Result<(Value, Value, Vec<Action>), CleanupError> {
        let references = self.referenced()?;
        let manifest = self.manifest()?;
        let mut rows = Vec::new();
        let mut actions = Vec::new();
        for entry in manifest["entries"].as_array().expect("validated array") {
            if !entry.is_object() {
                return Err("연습 파일 기록이 손상됐습니다. 정리를 중단했습니다.".into());
            }
            let (mut ready, mut reason) = self.validate(entry);
            let mut action = if ready { Action::Unlink } else { Action::Keep };
            if !ready && self.vanished(entry) {
                ready = true;
                reason = MISSING;
                action = Action::Forget;
            }
            let raw = entry.get("path").and_then(Value::as_str).unwrap_or("");
            if ready && let Some(protected) = references.get(&Self::path_key(Path::new(raw))?) {
                ready = false;
                reason = protected;
                action = Action::Keep;
            }
            rows.push(
                json!({"name":entry.get("name").cloned().unwrap_or_else(||json!("")),
                "path":raw,"delete":ready,"reason":reason}),
            );
            actions.push(action);
        }
        let token = preview_token(&rows);
        let count = rows.iter().filter(|row| row["delete"] == true).count();
        Ok((
            json!({"token":token,"rows":rows,"delete_count":count}),
            manifest,
            actions,
        ))
    }

    pub fn cleanup_preview(&self) -> Result<Value, CleanupError> {
        Ok(self.scan()?.0)
    }

    pub fn cleanup(&self, token: &str) -> Result<Value, CleanupError> {
        self.job_lease
            .with_write_lock(|| self.pool_lock.with(|| self.cleanup_locked(token)))?
    }

    fn cleanup_locked(&self, token: &str) -> Result<Value, CleanupError> {
        self.cleanup_locked_with(token, |path| fs::remove_file(path))
    }

    /// Validates each `Action::Unlink` entry still matches its on-disk state, then
    /// collects the non-`Keep` entries' `(path, unlink)` pairs in manifest order.
    fn plan_cleanup_targets<'a>(
        &self,
        manifest: &'a Value,
        actions: Vec<Action>,
    ) -> Result<Vec<(&'a str, bool)>, CleanupError> {
        let mut targets = Vec::new();
        for (entry, action) in manifest["entries"]
            .as_array()
            .expect("validated array")
            .iter()
            .zip(actions)
        {
            if matches!(action, Action::Unlink) && !self.validate(entry).0 {
                return Err(CHANGED.into());
            }
            if !matches!(action, Action::Keep) {
                targets.push((
                    entry["path"].as_str().expect("validated path"),
                    matches!(action, Action::Unlink),
                ));
            }
        }
        Ok(targets)
    }
    /// Deletes each `unlink` target in order (stopping at the first delete failure)
    /// and, if anything was removed, persists the retained manifest before surfacing
    /// that failure — preserving the original delete-then-persist-then-fail order.
    fn delete_and_persist(
        &self,
        manifest: &Value,
        targets: Vec<(&str, bool)>,
        mut remove: impl FnMut(&Path) -> io::Result<()>,
    ) -> Result<Vec<String>, CleanupError> {
        let mut removed = Vec::new();
        let mut failure = None;
        for (path, unlink) in targets {
            if unlink && let Err(error) = remove(Path::new(path)) {
                failure = Some(error);
                break;
            }
            removed.push(path.to_owned());
        }
        if !removed.is_empty() {
            let retained = manifest["entries"]
                .as_array()
                .expect("validated array")
                .iter()
                .filter(|entry| !removed.iter().any(|path| entry["path"] == *path))
                .cloned()
                .collect::<Vec<_>>();
            let save = mutate(&self.settings_path, |settings| {
                let tutorial = settings.entry("tutorial").or_insert_with(|| json!({}));
                if !tutorial.is_object() {
                    *tutorial = json!({});
                }
                tutorial["practice"] = json!({"version":1,"entries":retained});
            });
            if let Some(error) = failure {
                return Err(error.into());
            }
            save?;
        } else if let Some(error) = failure {
            return Err(error.into());
        }
        Ok(removed)
    }
    fn cleanup_locked_with(
        &self,
        token: &str,
        remove: impl FnMut(&Path) -> io::Result<()>,
    ) -> Result<Value, CleanupError> {
        let (preview, manifest, actions) = self.scan()?;
        if preview["token"] != token {
            return Err(CHANGED.into());
        }
        let targets = self.plan_cleanup_targets(&manifest, actions)?;
        let removed = self.delete_and_persist(&manifest, targets, remove)?;
        Ok(json!({"removed":removed.len(),
            "preserved":preview["rows"].as_array().expect("rows array").len()-removed.len()}))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{LegacyPractice, preview_token};
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::job_registry::JobRegistry;
    use crate::tutorial_workspace::fingerprint;
    use hwpx_filler::dataset_reference::DatasetReference;
    use serde_json::json;
    use std::fs;
    use std::path::Path;
    use std::sync::Arc;
    use uuid::Uuid;

    #[test]
    fn cleanup_preserves_references_and_rechecks_before_deleting_old_copies() {
        assert_eq!(
            preview_token(&[json!({"name":"x","path":"C:\\a","delete":true,"reason":""})]),
            "a49482a25a841d145d4db2680bf9e063076e775815065eecd46591cba6b2d7be"
        );
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/legacy-practice")
            .join(Uuid::new_v4().to_string());
        let templates = root.join("templates");
        let home = root.join("home");
        fs::create_dir_all(&templates).unwrap();
        fs::create_dir_all(&home).unwrap();
        let template_root = templates.clone();
        let jobs =
            Arc::new(JobRegistry::new(root.join("jobs"), move || template_root.clone()).unwrap());
        let pools = Arc::new(DatasetPoolRegistry::new(root.join("pool")).unwrap());
        let settings = home.join("settings.json");
        let practice = LegacyPractice::new(
            templates.clone(),
            &home,
            settings.clone(),
            jobs.clone(),
            pools.clone(),
            |_| {},
        )
        .unwrap();
        let name = "낙찰자 선정 및 계약체결 안내.txt";
        let path = templates.join("낙찰자 선정 및 계약체결 안내 (연습 abc).txt");
        fs::write(&path, b"original").unwrap();
        let entry =
            json!({"name":name,"batch":"abc","path":path,"sha256":fingerprint(&path).unwrap()});
        fs::write(
            &settings,
            serde_json::to_vec(&json!({"tutorial":{"practice":{"version":1,"entries":[entry]}}}))
                .unwrap(),
        )
        .unwrap();
        let preview = practice.cleanup_preview().unwrap();
        assert_eq!(preview["delete_count"], 1);
        let valid_settings = fs::read(&settings).unwrap();
        fs::write(
            &settings,
            serde_json::to_vec(&json!({"tutorial":{"practice":{"version":99,"entries":[]}}}))
                .unwrap(),
        )
        .unwrap();
        assert!(practice.cleanup_preview().is_err());
        assert_eq!(fs::read(&path).unwrap(), b"original");
        fs::write(&settings, valid_settings).unwrap();
        fs::create_dir_all(pools.directory()).unwrap();
        fs::write(pools.directory().join("broken.dataset.json"), b"{").unwrap();
        assert!(
            practice
                .cleanup_preview()
                .unwrap_err()
                .to_string()
                .contains("등록 데이터")
        );
        assert_eq!(fs::read(&path).unwrap(), b"original");
        fs::remove_file(pools.directory().join("broken.dataset.json")).unwrap();
        fs::write(&path, b"user edit").unwrap();
        assert!(
            practice
                .cleanup(preview["token"].as_str().unwrap())
                .is_err()
        );
        assert_eq!(fs::read(&path).unwrap(), b"user edit");
        fs::write(&path, b"original").unwrap();
        fs::create_dir_all(jobs.directory()).unwrap();
        fs::write(jobs.directory().join("damaged.job.json"), b"{").unwrap();
        assert!(
            practice
                .cleanup_preview()
                .unwrap_err()
                .to_string()
                .contains("읽을 수 없는 작업")
        );
        fs::remove_file(jobs.directory().join("damaged.job.json")).unwrap();
        let reference = DatasetReference::new(
            "보존",
            "excel",
            json!({"path":path,"sheet":"공고","header_row":1})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        let pool_key = pools.add(&reference).unwrap();
        let protected = practice.cleanup_preview().unwrap();
        assert_eq!(protected["rows"][0]["reason"], "등록 데이터가 참조합니다.");
        assert_eq!(protected["delete_count"], 0);
        pools.delete(&pool_key).unwrap();
        let preview = practice.cleanup_preview().unwrap();
        assert_eq!(
            practice
                .cleanup(preview["token"].as_str().unwrap())
                .unwrap()["removed"],
            1
        );
        assert!(!path.exists());
        assert_eq!(practice.cleanup_preview().unwrap()["rows"], json!([]));
        let second = templates.join("물품 구매입찰 공고 (연습 abc).hwpx");
        fs::write(&path, b"original").unwrap();
        fs::write(&second, b"second").unwrap();
        let entries = [(&path, name), (&second, "물품 구매입찰 공고.hwpx")].map(|(path, name)| {
            json!({"name":name,"batch":"abc","path":path,
                    "sha256":fingerprint(path).unwrap()})
        });
        fs::write(
            &settings,
            serde_json::to_vec(&json!({"tutorial":{"practice":{"version":1,"entries":entries}}}))
                .unwrap(),
        )
        .unwrap();
        let preview = practice.cleanup_preview().unwrap();
        let mut calls = 0;
        assert!(
            practice
                .cleanup_locked_with(preview["token"].as_str().unwrap(), |target| {
                    calls += 1;
                    if calls == 2 {
                        return Err(std::io::Error::new(
                            std::io::ErrorKind::PermissionDenied,
                            "busy",
                        ));
                    }
                    fs::remove_file(target)
                })
                .is_err()
        );
        assert!(!path.exists());
        assert!(second.exists());
        assert_eq!(
            practice.cleanup_preview().unwrap()["rows"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        fs::remove_dir_all(root).unwrap();
    }
}
