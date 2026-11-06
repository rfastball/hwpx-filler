//! Work-package receiving-side facts and confirmed, reversible installation.

use crate::job_registry::{JobRegistry, StoreError};
use crate::preset_registry::PresetRegistry;
use crate::template_files::TemplateFileStore;
use crate::work_package_io::{WorkPackageContents, read_work_package};
use hwpx_filler::python_casefold::python_casefold;
use hwpx_filler::work_package::{PackagedTemplate, WorkPackageError};
use hwpx_filler::work_package_plan::{
    ImportPlan, ReceivingSide, TEMPLATE_REUSE, imported_job, plan_import,
};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Debug)]
pub enum InstallError {
    Stale(ImportPlan),
    Failed(WorkPackageError),
}
impl std::fmt::Display for InstallError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Stale(_) => f.write_str("불러오기 계획이 확인 뒤 바뀌었습니다"),
            Self::Failed(error) => write!(f, "{error}"),
        }
    }
}
impl std::error::Error for InstallError {}
impl From<WorkPackageError> for InstallError {
    fn from(error: WorkPackageError) -> Self {
        Self::Failed(error)
    }
}
fn fail(error: impl std::fmt::Display) -> WorkPackageError {
    WorkPackageError(error.to_string())
}

fn candidate_files(root: &Path) -> Result<Vec<PathBuf>, WorkPackageError> {
    if !root.is_dir() {
        return Ok(Vec::new());
    }
    let mut paths = Vec::new();
    let mut stack = vec![root.to_owned()];
    while let Some(directory) = stack.pop() {
        let entries = fs::read_dir(&directory).map_err(fail)?;
        for entry in entries {
            let entry = entry.map_err(fail)?;
            let kind = entry.file_type().map_err(fail)?;
            if kind.is_dir() {
                stack.push(entry.path());
            } else if kind.is_file() || kind.is_symlink() {
                paths.push(entry.path());
            }
            if paths.len() + stack.len() > 1_000_000 {
                return Err(fail("서식 폴더의 파일이 너무 많습니다"));
            }
        }
    }
    paths.sort();
    Ok(paths)
}

fn existing_templates(
    root: &Path,
    templates: &[PackagedTemplate],
) -> Result<HashMap<String, String>, WorkPackageError> {
    let mut wanted: HashMap<(&str, u64), HashSet<&str>> = HashMap::new();
    for template in templates {
        wanted
            .entry((&template.media, template.size))
            .or_default()
            .insert(&template.digest);
    }
    let mut found = HashMap::new();
    for path in candidate_files(root)? {
        if let Some(digest) = matching_template_digest(&path, &wanted)
            && let Some(path) = path.to_str()
        {
            found.entry(digest).or_insert_with(|| path.to_owned());
        }
    }
    Ok(found)
}

fn matching_template_digest(
    path: &Path,
    wanted: &HashMap<(&str, u64), HashSet<&str>>,
) -> Option<String> {
    let media = path.extension()?.to_str()?.to_ascii_lowercase();
    let metadata = fs::metadata(path).ok()?;
    if !metadata.is_file() {
        return None;
    }
    let expected = wanted.get(&(media.as_str(), metadata.len()))?;
    let file = fs::File::open(path).ok()?;
    let mut bytes = Vec::new();
    if file
        .take(metadata.len() + 1)
        .read_to_end(&mut bytes)
        .is_err()
        || bytes.len() as u64 != metadata.len()
    {
        return None;
    }
    let digest = Sha256::digest(&bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    expected.contains(digest.as_str()).then_some(digest)
}

struct ReceivingFacts<'a> {
    jobs: &'a JobRegistry,
    root: PathBuf,
    presets: HashSet<String>,
    existing: HashMap<String, String>,
}
impl<'a> ReceivingFacts<'a> {
    fn new(
        jobs: &'a JobRegistry,
        presets: &PresetRegistry,
        root: PathBuf,
        templates: &[PackagedTemplate],
    ) -> Result<Self, WorkPackageError> {
        let presets = presets
            .list_presets()
            .map_err(fail)?
            .0
            .into_iter()
            .map(|(_, preset)| preset.name)
            .collect();
        let existing = existing_templates(&root, templates)?;
        Ok(Self {
            jobs,
            root,
            presets,
            existing,
        })
    }
}
impl ReceivingSide for ReceivingFacts<'_> {
    fn job_taken(&self, name: &str) -> bool {
        self.jobs.exists(name)
    }
    fn job_key(&self, name: &str) -> String {
        let slot = self.jobs.path_for(name);
        python_casefold(
            slot.file_name()
                .and_then(|part| part.to_str())
                .expect("slot derives from UTF-8 name"),
        )
    }
    fn preset_taken(&self, name: &str) -> bool {
        self.presets.contains(name)
    }
    fn file_taken(&self, name: &str) -> bool {
        self.root.join(name).exists()
    }
    fn existing_template(&self, template: &PackagedTemplate) -> Option<String> {
        self.existing.get(&template.digest).cloned()
    }
}

#[derive(Default)]
struct Created {
    files: Vec<PathBuf>,
    jobs: Vec<String>,
    presets: Vec<String>,
}

pub struct WorkPackageInstaller<'a> {
    pub jobs: &'a JobRegistry,
    pub files: &'a TemplateFileStore,
    pub presets: &'a PresetRegistry,
    pub template_root: Box<dyn Fn() -> PathBuf + 'a>,
}
impl WorkPackageInstaller<'_> {
    pub fn inspect(
        &self,
        path: &Path,
    ) -> Result<(WorkPackageContents, ImportPlan), WorkPackageError> {
        let contents = read_work_package(path)?;
        let side = ReceivingFacts::new(
            self.jobs,
            self.presets,
            (self.template_root)(),
            &contents.manifest.templates,
        )?;
        let plan = plan_import(&contents.manifest, &side)?;
        Ok((contents, plan))
    }
    pub fn commit(&self, path: &Path, basis: &str) -> Result<ImportPlan, InstallError> {
        let (contents, plan) = self.inspect(path)?;
        if plan.basis != basis {
            return Err(InstallError::Stale(plan));
        }
        let mut made = Created::default();
        let install = (|| -> Result<(), WorkPackageError> {
            let mut template_paths = HashMap::new();
            for item in &plan.templates {
                let path = if item.action == TEMPLATE_REUSE {
                    PathBuf::from(&item.target)
                } else {
                    let bytes = &contents.templates[&item.template.digest];
                    let path = self.files.add_bytes(&item.target, bytes).map_err(fail)?;
                    made.files.push(path.clone());
                    path
                };
                template_paths.insert(item.template.digest.clone(), path);
            }
            self.jobs
                .transaction(|session| {
                    for item in &plan.jobs {
                        if self.jobs.exists(&item.final_name) {
                            return Err(StoreError::Collision(format!(
                                "같은 이름의 작업이 이미 있습니다: {}",
                                item.final_name
                            )));
                        }
                        let path = &template_paths[&item.source.template_digest];
                        let path = path.to_str().ok_or_else(|| {
                            StoreError::Invalid(
                                "템플릿 경로를 Unicode 문자열로 나타낼 수 없습니다".into(),
                            )
                        })?;
                        let mut job = imported_job(item, path);
                        session.save(&mut job, false)?;
                        made.jobs.push(item.final_name.clone());
                    }
                    Ok(())
                })
                .map_err(fail)?;
            for item in &plan.presets {
                made.presets
                    .push(self.presets.add(&item.preset).map_err(fail)?);
            }
            Ok(())
        })();
        if let Err(error) = install {
            return Err(self.failed_install(error, &made));
        }
        Ok(plan)
    }
    fn failed_install(&self, error: WorkPackageError, made: &Created) -> InstallError {
        let leftovers = self.rollback(made);
        if leftovers.is_empty() {
            InstallError::Failed(error)
        } else {
            InstallError::Failed(fail(format!(
                "{error} (되돌리지 못한 항목: {})",
                leftovers.join(", ")
            )))
        }
    }
    fn rollback(&self, made: &Created) -> Vec<String> {
        let mut leftovers = Vec::new();
        for key in made.presets.iter().rev() {
            if self.presets.delete(key).is_err() {
                leftovers.push(key.clone());
            }
        }
        leftovers.extend(self.rollback_jobs(&made.jobs));
        for path in made.files.iter().rev() {
            if let Err(error) = fs::remove_file(path)
                && error.kind() != std::io::ErrorKind::NotFound
            {
                leftovers.push(path.display().to_string());
            }
        }
        leftovers
    }
    fn rollback_jobs(&self, names: &[String]) -> Vec<String> {
        let mut leftovers = Vec::new();
        if !names.is_empty()
            && self
                .jobs
                .transaction(|_| {
                    for name in names.iter().rev() {
                        let path = self.jobs.path_for(name);
                        if let Err(error) = fs::remove_file(&path)
                            && error.kind() != std::io::ErrorKind::NotFound
                        {
                            leftovers.push(name.clone());
                        }
                    }
                    Ok(())
                })
                .is_err()
        {
            leftovers.extend(names.iter().rev().cloned());
        }
        leftovers
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{InstallError, WorkPackageInstaller};
    use crate::job_registry::JobRegistry;
    use crate::preset_registry::PresetRegistry;
    use crate::template_files::TemplateFileStore;
    use crate::work_package_io::build_work_package_bytes;
    use hwpx_filler::mapping::MappingProfile;
    use hwpx_filler::work_package::{PackagedJob, PackagedTemplate, WorkPackageManifest};
    use serde_json::Map;
    use sha2::{Digest, Sha256};
    use std::collections::HashMap;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn preset(name: &str) -> hwpx_filler::preset::SelectionPreset {
        use hwpx_filler::slot_selection::{SlotSelection, SlotSelectionSet};
        hwpx_filler::preset::SelectionPreset::new(
            name,
            SlotSelectionSet::new(vec![SlotSelection::new("s1", vec!["o1".into()]).unwrap()])
                .unwrap(),
            Vec::new(),
            "now",
        )
        .unwrap()
    }

    fn package_with_presets(root: &std::path::Path) -> PathBuf {
        let bytes = b"template".to_vec();
        let digest = Sha256::digest(&bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let manifest = WorkPackageManifest {
            created_at: "now".into(),
            templates: vec![PackagedTemplate {
                digest: digest.clone(),
                media: "txt".into(),
                display_name: "공고.txt".into(),
                size: bytes.len() as u64,
            }],
            jobs: ["가", "나"]
                .into_iter()
                .map(|name| PackagedJob {
                    name: name.into(),
                    media: "txt".into(),
                    template_digest: digest.clone(),
                    mapping: MappingProfile::new("", Vec::new(), Map::new()).unwrap(),
                    filename_pattern: "공고".into(),
                    selection_presets: vec![preset(name)],
                    data_contract: None,
                })
                .collect(),
        };
        let package = root.join("presets.narumi");
        fs::write(
            &package,
            build_work_package_bytes(&manifest, &HashMap::from([(digest, bytes)])).unwrap(),
        )
        .unwrap();
        package
    }

    #[test]
    fn late_failure_and_failed_rollback_preserve_foreign_items() {
        use hwpx_filler::job::Job;
        let workspace = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let root = workspace.join(format!(".cache/package-rollback-{}", uuid::Uuid::new_v4()));
        let templates = root.join("templates");
        fs::create_dir_all(&templates).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        fs::write(templates.join("keep.txt"), b"foreign").unwrap();
        let jobs = Arc::new(
            JobRegistry::new(root.join("jobs"), {
                let templates = templates.clone();
                move || templates.clone()
            })
            .unwrap(),
        );
        let presets = Arc::new(PresetRegistry::new(root.join("presets")).unwrap());
        let mut existing = Job {
            name: "기존".into(),
            template_path: "C:/foreign.txt".into(),
            ..Job::default()
        };
        jobs.save(&mut existing, false).unwrap();
        let before = fs::read(jobs.path_for("기존")).unwrap();
        let package = package_with_presets(&root);
        // Introduce a preset collision after inspection, during the first template add.
        let files = TemplateFileStore::new({
            let templates = templates.clone();
            let presets = presets.clone();
            let calls = AtomicUsize::new(0);
            move || {
                if calls.fetch_add(1, Ordering::SeqCst) == 0 {
                    presets.add(&preset("나")).unwrap();
                }
                templates.clone()
            }
        });
        let installer = WorkPackageInstaller {
            jobs: &jobs,
            files: &files,
            presets: &presets,
            template_root: Box::new({
                let templates = templates.clone();
                move || templates.clone()
            }),
        };
        let (_, plan) = installer.inspect(&package).unwrap();
        let error = installer.commit(&package, &plan.basis).unwrap_err();
        assert_eq!(error.to_string(), "같은 이름의 프리셋이 이미 있습니다: 나");
        assert_eq!(jobs.names().unwrap(), ["기존"]);
        assert_eq!(fs::read(jobs.path_for("기존")).unwrap(), before);
        assert_eq!(fs::read(templates.join("keep.txt")).unwrap(), b"foreign");
        assert!(!templates.join("공고.txt").exists());
        assert_eq!(
            presets
                .list_entries()
                .unwrap()
                .iter()
                .map(|(_, preset)| preset.name.as_str())
                .collect::<Vec<_>>(),
            ["나"]
        );
        assert_job_race_is_not_overwritten(&package, &templates, &jobs, &presets);
        #[cfg(windows)]
        assert_locked_rollback_reports_leftovers(&installer, &templates);
        #[cfg(windows)]
        assert_scan_reuses_only_matching_readable_templates(&root);
        fs::remove_dir_all(&root).unwrap();
    }

    fn assert_job_race_is_not_overwritten(
        package: &std::path::Path,
        templates: &std::path::Path,
        jobs: &Arc<JobRegistry>,
        presets: &PresetRegistry,
    ) {
        use hwpx_filler::job::Job;
        let files = TemplateFileStore::new({
            let templates = templates.to_owned();
            let jobs = jobs.clone();
            let calls = AtomicUsize::new(0);
            move || {
                if calls.fetch_add(1, Ordering::SeqCst) == 0 {
                    let mut foreign = Job {
                        name: "가".into(),
                        template_path: "C:/foreign.txt".into(),
                        ..Job::default()
                    };
                    jobs.save(&mut foreign, false).unwrap();
                }
                templates.clone()
            }
        });
        let installer = WorkPackageInstaller {
            jobs,
            files: &files,
            presets,
            template_root: Box::new(|| templates.to_owned()),
        };
        let (_, plan) = installer.inspect(package).unwrap();
        assert_eq!(
            installer
                .commit(package, &plan.basis)
                .unwrap_err()
                .to_string(),
            "같은 이름의 작업이 이미 있습니다: 가"
        );
        assert_eq!(jobs.load("가").unwrap().template_path, "C:/foreign.txt");
        assert!(!jobs.exists("나"));
        assert!(!templates.join("공고.txt").exists());
    }

    #[cfg(windows)]
    fn assert_locked_rollback_reports_leftovers(
        installer: &WorkPackageInstaller<'_>,
        templates: &std::path::Path,
    ) {
        use hwpx_filler::job::Job;
        use std::os::windows::fs::OpenOptionsExt;
        let jobs = installer.jobs;
        let mut owned = Job {
            name: "owned".into(),
            ..Job::default()
        };
        jobs.save(&mut owned, false).unwrap();
        let key = installer.presets.add(&preset("owned")).unwrap();
        let file = templates.join("owned.txt");
        fs::write(&file, b"owned").unwrap();
        let paths = [
            jobs.path_for("owned"),
            installer.presets.slot_path(&key).unwrap(),
            file.clone(),
        ];
        let locks: Vec<_> = paths
            .iter()
            .map(|path| {
                fs::OpenOptions::new()
                    .read(true)
                    .share_mode(1)
                    .open(path)
                    .unwrap()
            })
            .collect();
        let made = super::Created {
            files: vec![templates.join("already-gone.txt"), file.clone()],
            jobs: vec!["already-gone".into(), "owned".into()],
            presets: vec!["already-gone".into(), key.clone()],
        };
        let error =
            installer.failed_install(super::fail("같은 이름의 프리셋이 이미 있습니다: 나"), &made);
        assert_eq!(
            error.to_string(),
            format!(
                "같은 이름의 프리셋이 이미 있습니다: 나 (되돌리지 못한 항목: {key}, owned, {})",
                file.display()
            )
        );
        assert!(paths.iter().all(|path| path.exists()));
        drop(locks);
        assert!(installer.rollback(&made).is_empty());
        assert!(paths.iter().all(|path| !path.exists()));
        assert_eq!(jobs.load("가").unwrap().template_path, "C:/foreign.txt");
        assert!(jobs.exists("기존"));
        assert_eq!(fs::read(templates.join("keep.txt")).unwrap(), b"foreign");
        assert!(installer.presets.find_name("나").unwrap().is_some());
    }

    #[cfg(windows)]
    fn assert_scan_reuses_only_matching_readable_templates(root: &std::path::Path) {
        use std::os::windows::fs::OpenOptionsExt;
        let root = root.join("scan");
        fs::create_dir_all(root.join("하위")).unwrap();
        fs::create_dir_all(root.join("폴더.txt")).unwrap();
        let bytes = "공고명: {{공고명}}\n".as_bytes();
        for name in [
            "가-locked.txt",
            "같음.TXT",
            "하위/또같음.txt",
            "같은크기.hwpx",
            "메모.md",
            "확장자없음",
        ] {
            fs::write(root.join(name), bytes).unwrap();
        }
        fs::write(root.join("다른크기.txt"), b"different size").unwrap();
        fs::write(root.join("가-wrong.txt"), vec![b'x'; bytes.len()]).unwrap();
        let locked = fs::OpenOptions::new()
            .read(true)
            .share_mode(0)
            .open(root.join("가-locked.txt"))
            .unwrap();
        let digest = Sha256::digest(bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let template = PackagedTemplate {
            digest: digest.clone(),
            media: "txt".into(),
            display_name: "공고.txt".into(),
            size: bytes.len() as u64,
        };
        assert_eq!(
            super::existing_templates(&root, std::slice::from_ref(&template)).unwrap(),
            HashMap::from([(digest, root.join("같음.TXT").to_str().unwrap().into())])
        );
        assert!(
            super::existing_templates(&root.join("missing"), &[template])
                .unwrap()
                .is_empty()
        );
        drop(locked);
    }

    #[test]
    fn inspect_is_read_only_and_confirmed_import_rechecks_basis() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let root = workspace.join(format!(
            ".cache/work-package-install-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let template_root = root.join("templates");
        let job_root = root.join("jobs");
        let template_bytes = b"example template".to_vec();
        let digest = Sha256::digest(&template_bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let manifest = WorkPackageManifest {
            created_at: "2026-11-05T12:00:00".into(),
            templates: vec![PackagedTemplate {
                digest: digest.clone(),
                media: "txt".into(),
                display_name: "예시.txt".into(),
                size: template_bytes.len() as u64,
            }],
            jobs: vec![PackagedJob {
                name: "계약".into(),
                media: "txt".into(),
                template_digest: digest.clone(),
                mapping: MappingProfile::new("", Vec::new(), Map::new()).unwrap(),
                filename_pattern: "계약".into(),
                selection_presets: Vec::new(),
                data_contract: None,
            }],
        };
        let package = root.join("package.narumi");
        fs::write(
            &package,
            build_work_package_bytes(
                &manifest,
                &HashMap::from([(digest, template_bytes.clone())]),
            )
            .unwrap(),
        )
        .unwrap();
        let jobs = JobRegistry::new(job_root, {
            let root = template_root.clone();
            move || root.clone()
        })
        .unwrap();
        let files = TemplateFileStore::new({
            let root = template_root.clone();
            move || root.clone()
        });
        let presets = PresetRegistry::new(root.join("presets")).unwrap();
        let installer = WorkPackageInstaller {
            jobs: &jobs,
            files: &files,
            presets: &presets,
            template_root: Box::new({
                let root = template_root.clone();
                move || root.clone()
            }),
        };
        let (_, plan) = installer.inspect(&package).unwrap();
        assert!(!jobs.exists("계약") && !template_root.exists());
        assert!(matches!(
            installer.commit(&package, "stale"),
            Err(InstallError::Stale(_))
        ));
        assert!(!jobs.exists("계약") && !template_root.exists());
        installer.commit(&package, &plan.basis).unwrap();
        let imported = jobs.load("계약").unwrap();
        assert_eq!(fs::read(&imported.template_path).unwrap(), template_bytes);
        assert!(imported.data_path.is_empty() && imported.authority_id.is_empty());
        let (_, changed) = installer.inspect(&package).unwrap();
        assert_ne!(changed.basis, plan.basis);
        assert!(matches!(
            installer.commit(&package, &plan.basis),
            Err(InstallError::Stale(_))
        ));

        // A changing host template root fails after the first exclusive add;
        // rollback removes that new file and leaves every preexisting job intact.
        let failed_root = root.join("failed-templates");
        let blocked_root = root.join("not-a-directory");
        fs::write(&blocked_root, b"owned").unwrap();
        let payloads = [b"first".to_vec(), b"second".to_vec()];
        let digests = payloads
            .iter()
            .map(|bytes| {
                Sha256::digest(bytes)
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect::<String>()
            })
            .collect::<Vec<_>>();
        let failed_manifest = WorkPackageManifest {
            created_at: "2026-11-05T12:00:00".into(),
            templates: (0..2)
                .map(|index| PackagedTemplate {
                    digest: digests[index].clone(),
                    media: "txt".into(),
                    display_name: format!("{index}.txt"),
                    size: payloads[index].len() as u64,
                })
                .collect(),
            jobs: (0..2)
                .map(|index| PackagedJob {
                    name: format!("신규{index}"),
                    media: "txt".into(),
                    template_digest: digests[index].clone(),
                    mapping: MappingProfile::new("", Vec::new(), Map::new()).unwrap(),
                    filename_pattern: "계약".into(),
                    selection_presets: Vec::new(),
                    data_contract: None,
                })
                .collect(),
        };
        let failed_package = root.join("failed.narumi");
        fs::write(
            &failed_package,
            build_work_package_bytes(
                &failed_manifest,
                &digests.iter().cloned().zip(payloads).collect(),
            )
            .unwrap(),
        )
        .unwrap();
        let opens = Arc::new(AtomicUsize::new(0));
        let changing_files = TemplateFileStore::new({
            let good = failed_root.clone();
            let bad = blocked_root.clone();
            let opens = opens.clone();
            move || {
                if opens.fetch_add(1, Ordering::SeqCst) == 0 {
                    good.clone()
                } else {
                    bad.clone()
                }
            }
        });
        let failing = WorkPackageInstaller {
            jobs: &jobs,
            files: &changing_files,
            presets: &presets,
            template_root: Box::new({
                let root = failed_root.clone();
                move || root.clone()
            }),
        };
        let (_, failed_plan) = failing.inspect(&failed_package).unwrap();
        assert!(matches!(
            failing.commit(&failed_package, &failed_plan.basis),
            Err(InstallError::Failed(_))
        ));
        assert!(fs::read_dir(&failed_root).unwrap().next().is_none());
        assert!(!jobs.exists("신규0") && !jobs.exists("신규1") && jobs.exists("계약"));
        fs::remove_dir_all(&root).unwrap();
    }
}
