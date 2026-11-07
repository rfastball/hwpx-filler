//! Bundled tutorial assets, manifest ownership, and reversible installation effects.

use crate::atomic_file::{write_bytes_atomic, write_bytes_atomic_exclusive};
use crate::dataset_registry::{DatasetPoolRegistry, PoolError};
use crate::settings_store::{mutate, read_with_alert};
use crate::single_instance::resolved_home;
use crate::template_files::TemplateFileStore;
use crate::template_root::TemplateRoot;
use hwpx_filler::dataset_reference::DatasetReference;
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

pub type ExampleError = Box<dyn Error + Send + Sync>;
const HWPX: [&str; 3] = ["계약체결안내.hwpx", "구매추진안내.hwpx", "공고서_연습.hwpx"];
const TXT: [&str; 2] = ["계약안내_기안.txt", "오류연습_보증금.txt"];
const DATA: [&str; 2] = ["계약목록.csv", "계약목록_2.csv"];
const GROUP: &str = "예제";

pub struct ExamplePack {
    pub assets: PathBuf,
    pub data_dir: PathBuf,
    pub settings_path: PathBuf,
    pub root: Arc<TemplateRoot>,
    pub files: Arc<TemplateFileStore>,
    pub pools: Arc<DatasetPoolRegistry>,
    pub alert: Arc<dyn Fn(&str) + Send + Sync>,
}

#[derive(Clone, Debug)]
pub struct RemovalPlan {
    pub templates: Vec<(String, PathBuf, String)>,
    pub data_files: Vec<PathBuf>,
    pub pool_keys: Vec<String>,
    pub group: String,
}
pub struct InstallResult {
    pub templates: usize,
    pub data_files: usize,
    pub pool_keys: usize,
    pub renamed: Vec<String>,
}
pub struct RemoveResult {
    pub removed: Vec<PathBuf>,
    pub data_removed: usize,
    pub unpinned: usize,
    pub kept_pins: Vec<String>,
    pub missing: Vec<String>,
}
impl ExamplePack {
    fn settings(&self) -> Result<Map<String, Value>, ExampleError> {
        Ok(read_with_alert(&self.settings_path, |message| {
            (self.alert)(message)
        })?)
    }
    pub fn manifest(&self) -> Result<Option<Value>, ExampleError> {
        let settings = self.settings()?;
        let manifest = settings
            .get("tutorial")
            .and_then(Value::as_object)
            .and_then(|tutorial| tutorial.get("manifest"))
            .and_then(Value::as_object);
        Ok(manifest.and_then(|manifest| {
            let templates = manifest.get("templates")?.as_array()?;
            templates
                .iter()
                .all(|entry| {
                    entry
                        .as_object()
                        .is_some_and(|entry| entry.get("path").is_some_and(Value::is_string))
                })
                .then(|| Value::Object(manifest.clone()))
        }))
    }
    pub fn installed(&self) -> Result<bool, ExampleError> {
        Ok(self.manifest()?.is_some())
    }
    pub fn confirm_text(&self) -> Result<String, ExampleError> {
        let root = self.root.path();
        let mut lines = vec![
            format!(
                "동봉 예제를 설치합니다. 지금 홈에 다음 {}건을 씁니다.",
                HWPX.len() + TXT.len() + DATA.len()
            ),
            String::new(),
            format!("· HWPX 서식 {}건 → {}", HWPX.len(), root.display()),
            format!("· TXT 기안 {}건 → {}", TXT.len(), root.display()),
            format!(
                "· 예제 데이터 {}건 → {} (데이터 풀에 고정)",
                DATA.len(),
                self.data_dir.display()
            ),
        ];
        if self.installed()? {
            lines.push("이미 설치돼 있어 지난 설치분을 덮어쓰고 처음 상태로 되돌립니다.".into());
        }
        Ok(lines.join("\n"))
    }
    fn asset_plan(&self) -> Result<Vec<(&'static str, PathBuf)>, ExampleError> {
        let plan = HWPX
            .iter()
            .map(|name| ("hwpx", self.assets.join("templates").join(name)))
            .chain(
                TXT.iter()
                    .map(|name| ("txt", self.assets.join("text_templates").join(name))),
            )
            .chain(
                DATA.iter()
                    .map(|name| ("data", self.assets.join("data").join(name))),
            )
            .collect::<Vec<_>>();
        let missing = plan
            .iter()
            .filter(|(_, path)| !path.is_file())
            .map(|(_, path)| path.display().to_string())
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Err(format!("동봉 예제 자산을 찾지 못했습니다: {}", missing.join(", ")).into());
        }
        Ok(plan)
    }
    fn save_manifest(
        &self,
        templates: Vec<Value>,
        data_files: Vec<String>,
        pool_keys: Vec<String>,
    ) -> Result<(), ExampleError> {
        mutate(&self.settings_path, |settings| {
            let mut tutorial = settings
                .get("tutorial")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            tutorial.insert("manifest".into(),json!({"group":GROUP,"templates":templates,"data_files":data_files,"pool_keys":pool_keys}));
            settings.insert("tutorial".into(), Value::Object(tutorial));
        })?;
        Ok(())
    }
    pub(crate) fn group_settings(&self) -> crate::template_groups::GroupSettings {
        let alert = self.alert.clone();
        crate::template_groups::GroupSettings::new(self.settings_path.clone(), move |message| {
            alert(message)
        })
    }
    fn set_group(&self, media: &str, key: &str) -> Result<(), ExampleError> {
        self.group_settings()
            .update_template_state(media, |groups, _| {
                groups.insert(key.into(), GROUP.into());
            })?;
        Ok(())
    }
    fn disband_group(&self, media: &str, group: &str) -> Result<(), ExampleError> {
        self.group_settings()
            .update_template_state(media, |groups, collapsed| {
                groups.retain(|_, value| value != group);
                collapsed.remove(group);
            })?;
        Ok(())
    }
    pub fn install(&self) -> Result<InstallResult, ExampleError> {
        let plan = self.asset_plan()?;
        let root = self.root.path();
        let prior = self.manifest()?.unwrap_or(Value::Null);
        let mut owned = HashSet::new();
        if let Some(templates) = prior.get("templates").and_then(Value::as_array) {
            owned.extend(
                templates
                    .iter()
                    .filter_map(|entry| entry.get("path").and_then(Value::as_str))
                    .map(str::to_owned),
            );
        }
        let prior_data = prior
            .get("data_files")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        for (index, value) in prior_data.iter().enumerate() {
            if let Some(name) = DATA.get(index) {
                let path = Path::new(
                    value
                        .as_str()
                        .ok_or("설치 기재의 데이터 파일 목록이 올바르지 않습니다.")?,
                );
                require_inside(&self.data_dir, path, "예제 데이터")?;
                let expected = self.data_dir.join(name);
                if !owned_data_name(&expected, path) {
                    return Err("설치 기재의 데이터 파일 목록이 올바르지 않습니다.".into());
                }
            }
        }
        let mut templates = Vec::new();
        let mut data_files = Vec::new();
        let mut pool_keys = Vec::new();
        let mut renamed = Vec::new();
        for (media, source) in plan {
            let name = source.file_name().ok_or("example asset name missing")?;
            if media == "data" {
                fs::create_dir_all(&self.data_dir)?;
                let expected = self.data_dir.join(name);
                let previous = prior_data
                    .get(data_files.len())
                    .and_then(Value::as_str)
                    .map(Path::new);
                let destination = copy_owned_or_numbered(&source, &expected, previous)?;
                if destination != expected {
                    renamed.push(format!(
                        "'{}' → '{}'",
                        name.to_string_lossy(),
                        destination.file_name().unwrap().to_string_lossy()
                    ));
                }
                let path = destination
                    .to_str()
                    .ok_or("example data path is not Unicode")?;
                data_files.push(path.to_owned());
                let key = match self.pools.find_identity(path, None)? {
                    Some((key, item)) => {
                        if item.status != "active" {
                            self.pools.commands().activate(&key)?;
                        }
                        key
                    }
                    None => {
                        let mut opts = Map::new();
                        opts.insert("path".into(), json!(path));
                        let item = DatasetReference::new(
                            destination.file_stem().unwrap().to_string_lossy(),
                            "excel",
                            opts,
                        )?;
                        self.pools.add(&item)?
                    }
                };
                pool_keys.push(key);
            } else {
                let expected = root.join(name);
                let destination = if expected.exists()
                    && owned.contains(
                        expected
                            .to_str()
                            .ok_or("example template path is not Unicode")?,
                    ) {
                    write_bytes_atomic(&expected, &fs::read(&source)?)?;
                    expected.clone()
                } else {
                    self.files.copy_into_library(&source)?
                };
                if destination.file_name() != Some(name) {
                    renamed.push(format!(
                        "'{}' → '{}'",
                        name.to_string_lossy(),
                        destination.file_name().unwrap().to_string_lossy()
                    ));
                }
                let key = destination
                    .strip_prefix(&root)?
                    .to_string_lossy()
                    .replace('\\', "/");
                self.set_group(media, &key)?;
                templates.push(json!({"media":media,"path":destination.to_str().ok_or("example template path is not Unicode")?,"key":key}));
            }
        }
        let result = InstallResult {
            templates: templates.len(),
            data_files: data_files.len(),
            pool_keys: pool_keys.len(),
            renamed,
        };
        self.save_manifest(templates, data_files, pool_keys)?;
        Ok(result)
    }
    pub fn removal_plan(&self) -> Result<Option<RemovalPlan>, ExampleError> {
        let Some(manifest) = self.manifest()? else {
            return Ok(None);
        };
        let root = self.root.path();
        let mut templates = Vec::new();
        for entry in manifest["templates"]
            .as_array()
            .ok_or("설치 manifest 의 템플릿 기재가 올바르지 않습니다")?
        {
            let media = entry.get("media").and_then(Value::as_str).unwrap_or("");
            if !matches!(media, "hwpx" | "txt") {
                return Err(format!(
                    "설치 기재의 템플릿 매체를 알 수 없습니다: {}",
                    serde_json::to_string(media)?
                )
                .into());
            }
            let path = PathBuf::from(
                entry
                    .get("path")
                    .and_then(Value::as_str)
                    .ok_or("설치 manifest 의 템플릿 기재가 올바르지 않습니다")?,
            );
            require_inside(&root, &path, "템플릿")?;
            templates.push((
                media.into(),
                path,
                entry
                    .get("key")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .into(),
            ));
        }
        let data_files = manifest
            .get("data_files")
            .and_then(Value::as_array)
            .ok_or("설치 기재의 데이터 파일 목록이 올바르지 않습니다.")?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(PathBuf::from)
                    .ok_or("설치 기재의 데이터 파일 목록이 올바르지 않습니다.")
            })
            .collect::<Result<Vec<_>, _>>()?;
        for path in &data_files {
            require_inside(&self.data_dir, path, "예제 데이터")?;
        }
        let pool_keys = manifest
            .get("pool_keys")
            .and_then(Value::as_array)
            .ok_or("설치 기재의 풀 등록 키 목록이 올바르지 않습니다.")?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or("설치 기재의 풀 등록 키 목록이 올바르지 않습니다.")
            })
            .collect::<Result<Vec<_>, _>>()?;
        let group = manifest
            .get("group")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or("설치 기재의 그룹 이름이 비어 있습니다.")?
            .to_owned();
        Ok(Some(RemovalPlan {
            templates,
            data_files,
            pool_keys,
            group,
        }))
    }
    pub fn remove_confirm_text(plan: &RemovalPlan) -> String {
        [format!("설치한 예제 {}건을 걷습니다.",plan.templates.len()+plan.data_files.len()),String::new(),
            format!("· 템플릿 {}건 — 라이브러리에서 걷습니다",plan.templates.len()),
            format!("· 예제 데이터 {}건 — 파일을 지웁니다",plan.data_files.len()),
            format!("· 데이터 풀 고정 {}건 — 해제합니다",plan.pool_keys.len()),String::new(),
            "설치할 때 기재한 것만 걷습니다. 예제를 고쳐 다른 이름으로 저장한 것은 그대로 남습니다.".into(),
            "되돌리기는 다시 설치하기입니다 — 걷은 것을 하나씩 되살리는 길은 없습니다.".into()].join("\n")
    }
    pub fn remove(&self) -> Result<RemoveResult, ExampleError> {
        let plan = self.removal_plan()?.ok_or("설치된 예제가 없습니다.")?;
        let mut result = RemoveResult {
            removed: Vec::new(),
            data_removed: 0,
            unpinned: 0,
            kept_pins: Vec::new(),
            missing: Vec::new(),
        };
        for (media, path, _) in &plan.templates {
            if !path.is_file() {
                result
                    .missing
                    .push(path.file_name().unwrap().to_string_lossy().into());
                continue;
            }
            self.files.remove(media, path)?;
            result.removed.push(path.clone());
        }
        for path in &plan.data_files {
            if !path.is_file() {
                result
                    .missing
                    .push(path.file_name().unwrap().to_string_lossy().into());
                continue;
            }
            fs::remove_file(path)?;
            result.data_removed += 1;
        }
        let targets = plan
            .data_files
            .iter()
            .filter_map(|path| path.to_str())
            .collect::<HashSet<_>>();
        for key in &plan.pool_keys {
            if !self.pools.exists(key)? {
                continue;
            }
            let item = match self.pools.load(key) {
                Ok(item) => item,
                Err(PoolError::Codec(_) | PoolError::Invalid(_)) => {
                    result.kept_pins.push(key.clone());
                    continue;
                }
                Err(PoolError::Io(error)) if error.kind() == std::io::ErrorKind::InvalidData => {
                    result.kept_pins.push(key.clone());
                    continue;
                }
                Err(error) => return Err(error.into()),
            };
            if !item
                .opts
                .get("path")
                .and_then(Value::as_str)
                .is_some_and(|path| targets.contains(path))
            {
                result.kept_pins.push(item.name);
                continue;
            }
            self.pools.delete(key)?;
            result.unpinned += 1;
        }
        for media in ["hwpx", "txt"] {
            self.disband_group(media, &plan.group)?;
        }
        self.clear_manifest()?;
        Ok(result)
    }

    fn clear_manifest(&self) -> Result<(), ExampleError> {
        mutate(&self.settings_path, |settings| {
            if let Some(tutorial) = settings.get("tutorial").and_then(Value::as_object) {
                let mut tutorial = tutorial.clone();
                tutorial.remove("manifest");
                settings.insert("tutorial".into(), Value::Object(tutorial));
            }
        })?;
        Ok(())
    }
}

fn require_inside(root: &Path, path: &Path, what: &str) -> Result<(), ExampleError> {
    let root = resolved_home(root);
    let target = resolved_home(path);
    if target == root || !target.starts_with(root) {
        return Err(format!(
            "설치 기재의 {what} 경로가 제자리를 벗어났습니다: {}",
            path.display()
        )
        .into());
    }
    Ok(())
}
fn copy_owned_or_numbered(
    source: &Path,
    expected: &Path,
    previous: Option<&Path>,
) -> Result<PathBuf, ExampleError> {
    let bytes = fs::read(source)?;
    if let Some(previous) = previous {
        if previous.exists() {
            write_bytes_atomic(previous, &bytes)?;
        } else {
            write_bytes_atomic_exclusive(previous, &bytes)?;
        }
        return Ok(previous.to_path_buf());
    }
    for number in 1..=10_000 {
        let candidate = if number == 1 {
            expected.to_path_buf()
        } else {
            let stem = expected
                .file_stem()
                .ok_or("example data filename missing")?
                .to_string_lossy();
            expected.with_file_name(format!("{stem} ({number}).csv"))
        };
        match write_bytes_atomic_exclusive(&candidate, &bytes) {
            Ok(()) => return Ok(candidate),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    Err(std::io::Error::from(std::io::ErrorKind::AlreadyExists).into())
}

fn owned_data_name(expected: &Path, previous: &Path) -> bool {
    if expected == previous {
        return true;
    }
    let Some(stem) = expected.file_stem().and_then(|stem| stem.to_str()) else {
        return false;
    };
    let Some(name) = previous.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    name.strip_prefix(&format!("{stem} ("))
        .and_then(|tail| tail.strip_suffix(").csv"))
        .and_then(|number| number.parse::<usize>().ok())
        .is_some_and(|number| number >= 2)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::ExamplePack;
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::shell_settings::ShellSettings;
    use crate::template_files::TemplateFileStore;
    use crate::template_root::TemplateRoot;
    use serde_json::Value;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::Arc;

    #[test]
    fn install_preserves_unowned_data_and_removes_only_manifest_entries() {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let sandbox = repo.join(format!(".cache/example-pack-owner-{}", std::process::id()));
        let template_dir = sandbox.join("templates");
        let data_dir = sandbox.join("example_data");
        fs::create_dir_all(&data_dir).unwrap();
        let original = data_dir.join("계약목록.csv");
        fs::write(&original, "user document\n").unwrap();
        let settings_path = sandbox.join("settings.json");
        fs::write(&settings_path, r#"{"tutorial":{"achieved":["kept"]}}"#).unwrap();
        let settings = Arc::new(ShellSettings::new(settings_path.clone(), |_| {}));
        let root = Arc::new(TemplateRoot::new(settings, template_dir).unwrap());
        let files = Arc::new(TemplateFileStore::new({
            let root = root.clone();
            move || root.path()
        }));
        let pools = Arc::new(DatasetPoolRegistry::new(sandbox.join("datasets")).unwrap());
        let pack = ExamplePack {
            assets: repo.join("examples/onboarding"),
            data_dir,
            settings_path: settings_path.clone(),
            root,
            files,
            pools,
            alert: Arc::new(|_| {}),
        };
        let done = pack.install().unwrap();
        assert_eq!((done.templates, done.data_files, done.pool_keys), (5, 2, 2));
        assert_eq!(fs::read_to_string(&original).unwrap(), "user document\n");
        let plan = pack.removal_plan().unwrap().unwrap();
        assert_eq!(plan.templates.len(), 5);
        assert!(plan.data_files.iter().all(|path| path != &original));
        let prior_data = plan.data_files.clone();
        let prior_keys = plan.pool_keys.clone();
        let again = pack.install().unwrap();
        assert_eq!(
            (again.templates, again.data_files, again.pool_keys),
            (5, 2, 2)
        );
        let plan = pack.removal_plan().unwrap().unwrap();
        assert_eq!(plan.data_files, prior_data);
        assert_eq!(plan.pool_keys, prior_keys);
        assert!(!pack.data_dir.join("계약목록 (3).csv").exists());
        let saved_settings = fs::read(&settings_path).unwrap();
        let mut escaped: Value = serde_json::from_slice(&saved_settings).unwrap();
        escaped["tutorial"]["manifest"]["templates"][0]["path"] =
            serde_json::json!(sandbox.join("outside.hwpx"));
        fs::write(&settings_path, serde_json::to_vec(&escaped).unwrap()).unwrap();
        assert!(pack.removal_plan().is_err());
        assert!(plan.templates[0].1.exists());
        fs::write(&settings_path, saved_settings).unwrap();
        let removed = pack.remove().unwrap();
        assert_eq!(
            (
                removed.removed.len(),
                removed.data_removed,
                removed.unpinned
            ),
            (5, 2, 2)
        );
        assert_eq!(fs::read_to_string(&original).unwrap(), "user document\n");
        let settings: Value = serde_json::from_slice(&fs::read(&settings_path).unwrap()).unwrap();
        assert_eq!(settings["tutorial"]["achieved"][0], "kept");
        assert!(settings["tutorial"].get("manifest").is_none());
        pack.clear_manifest().unwrap();
        assert_eq!(
            serde_json::from_slice::<Value>(&fs::read(&settings_path).unwrap()).unwrap(),
            settings
        );
        fs::write(&settings_path, r#"{"theme":"light"}"#).unwrap();
        for _ in 0..2 {
            pack.clear_manifest().unwrap();
            assert!(pack.manifest().unwrap().is_none());
            assert_eq!(
                serde_json::from_slice::<Value>(&fs::read(&settings_path).unwrap()).unwrap(),
                serde_json::json!({"theme":"light"})
            );
        }
        pack.install().unwrap();
        let corrupt_key = pack.removal_plan().unwrap().unwrap().pool_keys[0].clone();
        let corrupt_slot = pack.pools.slot_path(&corrupt_key).unwrap();
        fs::write(&corrupt_slot, b"{").unwrap();
        let removed = pack.remove().unwrap();
        assert_eq!(removed.unpinned, 1);
        assert_eq!(removed.kept_pins, [corrupt_key]);
        assert!(corrupt_slot.exists());
        assert!(pack.manifest().unwrap().is_none());
        assert_eq!(fs::read_to_string(&original).unwrap(), "user document\n");
        assert!(
            sandbox
                .canonicalize()
                .unwrap()
                .starts_with(repo.canonicalize().unwrap())
        );
        fs::remove_dir_all(sandbox).unwrap();
    }
}
