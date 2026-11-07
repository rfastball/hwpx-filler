//! Durable selection presets with slot identity and confirmed overwrite.

use crate::atomic_file::write_bytes_atomic;
use crate::directory_lock::DirectoryLock;
use hwpx_filler::preset::{
    CorruptPresetEntry, PresetError, SelectionPreset, decode_preset, encode_preset,
};
use std::error::Error;
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use uuid::Uuid;

const SUFFIX: &str = ".preset.json";
pub type PresetEntries = Vec<(String, SelectionPreset)>;
pub type PresetScan = (PresetEntries, Vec<CorruptPresetEntry>);

#[derive(Debug)]
pub enum PresetStoreError {
    Io(io::Error),
    Codec(PresetError),
    Invalid(String),
}
impl fmt::Display for PresetStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::Codec(error) => write!(f, "{error}"),
            Self::Invalid(detail) => f.write_str(detail),
        }
    }
}
impl Error for PresetStoreError {}
impl From<io::Error> for PresetStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}
impl From<PresetError> for PresetStoreError {
    fn from(error: PresetError) -> Self {
        Self::Codec(error)
    }
}

pub struct PresetRegistry {
    directory: PathBuf,
    lock: DirectoryLock,
}
impl PresetRegistry {
    pub fn new(directory: PathBuf) -> io::Result<Self> {
        let lock = DirectoryLock::new(&directory)?;
        Ok(Self { directory, lock })
    }
    pub fn slot_path(&self, key: &str) -> Result<PathBuf, PresetStoreError> {
        if key.is_empty()
            || matches!(key, "." | "..")
            || key.chars().any(|letter| "\\/:*?\"<>|\0".contains(letter))
        {
            return Err(PresetStoreError::Invalid(format!(
                "올바른 프리셋 키가 아닙니다: {key:?}"
            )));
        }
        Ok(self.directory.join(format!("{key}{SUFFIX}")))
    }
    fn load_at(path: &Path) -> Result<SelectionPreset, PresetStoreError> {
        if fs::symlink_metadata(path)?.file_type().is_symlink() {
            return Err(PresetStoreError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "preset slot is a link",
            )));
        }
        let bytes = fs::read(path)?;
        let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(|error| {
            PresetStoreError::Io(io::Error::new(io::ErrorKind::InvalidData, error))
        })?;
        Ok(decode_preset(&value)?)
    }
    fn write_at(&self, key: &str, preset: &SelectionPreset) -> Result<(), PresetStoreError> {
        fs::create_dir_all(&self.directory)?;
        let encoded = encode_preset(preset)?;
        let bytes = serde_json::to_vec_pretty(&encoded).map_err(|error| {
            PresetStoreError::Io(io::Error::new(io::ErrorKind::InvalidData, error))
        })?;
        write_bytes_atomic(&self.slot_path(key)?, &bytes)?;
        Ok(())
    }
    fn scan(&self, isolated: bool) -> Result<PresetScan, PresetStoreError> {
        if !self.directory.exists() {
            return Ok((Vec::new(), Vec::new()));
        }
        let mut paths = fs::read_dir(&self.directory)?
            .map(|entry| entry.map(|entry| entry.path()))
            .collect::<Result<Vec<_>, _>>()?;
        paths.sort();
        let mut entries: Vec<(String, SelectionPreset)> = Vec::new();
        let mut corrupted = Vec::new();
        for path in paths {
            let file_name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| {
                    PresetStoreError::Io(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "preset slot name is not Unicode",
                    ))
                })?;
            let Some(key) = file_name.strip_suffix(SUFFIX) else {
                continue;
            };
            match Self::load_at(&path) {
                Ok(preset) => entries.push((key.into(), preset)),
                Err(error) if isolated => corrupted.push(CorruptPresetEntry {
                    file_name: file_name.into(),
                    error: error.to_string(),
                }),
                Err(error) => return Err(error),
            }
        }
        entries.sort_by(|a, b| a.1.name.cmp(&b.1.name).then_with(|| a.0.cmp(&b.0)));
        Ok((entries, corrupted))
    }
    pub fn list_entries(&self) -> Result<Vec<(String, SelectionPreset)>, PresetStoreError> {
        Ok(self.scan(false)?.0)
    }
    pub fn list_presets(&self) -> Result<PresetScan, PresetStoreError> {
        self.scan(true)
    }
    fn find_name_isolated(
        &self,
        name: &str,
    ) -> Result<Option<(String, SelectionPreset)>, PresetStoreError> {
        Ok(self
            .scan(true)?
            .0
            .into_iter()
            .find(|(_, preset)| preset.name == name))
    }
    pub fn find_name(
        &self,
        name: &str,
    ) -> Result<Option<(String, SelectionPreset)>, PresetStoreError> {
        self.find_name_isolated(name)
    }
    pub fn load(&self, key: &str) -> Result<SelectionPreset, PresetStoreError> {
        Self::load_at(&self.slot_path(key)?)
    }
    pub fn exists(&self, key: &str) -> Result<bool, PresetStoreError> {
        Ok(self.slot_path(key)?.exists())
    }
    fn new_key(&self) -> Result<String, PresetStoreError> {
        self.new_key_with(|| Uuid::new_v4().simple().to_string()[..16].to_owned())
    }
    fn new_key_with(&self, mut mint: impl FnMut() -> String) -> Result<String, PresetStoreError> {
        for _ in 0..8 {
            let key = mint();
            if !self.slot_path(&key)?.exists() {
                return Ok(key);
            }
        }
        Err(PresetStoreError::Invalid(
            "빈 프리셋 슬롯 키를 발급하지 못했습니다.".into(),
        ))
    }
    pub fn add(&self, preset: &SelectionPreset) -> Result<String, PresetStoreError> {
        self.lock.with(|| {
            if self.find_name_isolated(&preset.name)?.is_some() {
                return Err(PresetStoreError::Invalid(format!(
                    "같은 이름의 프리셋이 이미 있습니다: {}",
                    preset.name
                )));
            }
            fs::create_dir_all(&self.directory)?;
            let key = self.new_key()?;
            self.write_at(&key, preset)?;
            Ok(key)
        })
    }
    fn save_at_unlocked(
        &self,
        key: &str,
        preset: &SelectionPreset,
    ) -> Result<(), PresetStoreError> {
        if self
            .find_name_isolated(&preset.name)?
            .is_some_and(|(taken, _)| taken != key)
        {
            return Err(PresetStoreError::Invalid(format!(
                "같은 이름의 프리셋이 이미 있습니다: {}",
                preset.name
            )));
        }
        self.write_at(key, preset)
    }
    pub fn save_at(&self, key: &str, preset: &SelectionPreset) -> Result<(), PresetStoreError> {
        self.lock.with(|| self.save_at_unlocked(key, preset))
    }
    pub fn save_confirmed(
        &self,
        expected_key: &str,
        preset: &SelectionPreset,
    ) -> Result<String, PresetStoreError> {
        self.lock
            .with(|| match self.find_name_isolated(&preset.name)? {
                Some((current, _)) if current != expected_key => Err(PresetStoreError::Invalid(
                    format!("확인 근거가 지금 상태와 다릅니다: {}", preset.name),
                )),
                Some((_current, _)) => {
                    self.save_at_unlocked(expected_key, preset)?;
                    Ok(expected_key.into())
                }
                None => {
                    fs::create_dir_all(&self.directory)?;
                    let key = self.new_key()?;
                    self.write_at(&key, preset)?;
                    Ok(key)
                }
            })
    }
    pub fn delete(&self, key: &str) -> Result<(), PresetStoreError> {
        self.lock
            .with(|| match fs::remove_file(self.slot_path(key)?) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
                Err(error) => Err(PresetStoreError::Io(error)),
            })
    }
    pub fn delete_loaded(&self, key: &str) -> Result<SelectionPreset, PresetStoreError> {
        self.lock.with(|| {
            let preset = self.load(key)?;
            fs::remove_file(self.slot_path(key)?)?;
            Ok(preset)
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::PresetRegistry;
    use hwpx_filler::preset::SelectionPreset;
    use hwpx_filler::slot_selection::{SlotSelection, SlotSelectionSet};
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn preset_slots_preserve_name_uniqueness_and_confirmed_target() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-preset-{}-{stamp}",
            std::process::id()
        ));
        let registry = PresetRegistry::new(sandbox.join("presets")).unwrap();
        assert!(registry.list_presets().unwrap().0.is_empty());
        assert!(registry.find_name("missing").unwrap().is_none());
        let selections = SlotSelectionSet::new(vec![
            SlotSelection::new("slot", vec!["option".into()]).unwrap(),
        ])
        .unwrap();
        let preset = SelectionPreset::new("선택", selections, vec![], "2026-11-05").unwrap();
        let key = registry.add(&preset).unwrap();
        assert_eq!(key.len(), 16);
        assert!(registry.add(&preset).is_err());
        for key in ["../outside", "a/b", "a\\b", "", ".", "..", "a:b", "a\0b"] {
            assert!(registry.slot_path(key).is_err());
        }
        assert_eq!(registry.save_confirmed(&key, &preset).unwrap(), key);
        assert!(registry.save_confirmed("stale", &preset).is_err());
        assert_eq!(registry.load(&key).unwrap(), preset);
        fs::write(sandbox.join("presets/broken.preset.json"), b"{").unwrap();
        assert!(registry.list_entries().is_err());
        let (entries, corrupt) = registry.list_presets().unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(corrupt.len(), 1);
        assert_eq!(
            registry.find_name("선택").unwrap(),
            Some((key.clone(), preset.clone()))
        );
        assert!(registry.find_name("missing").unwrap().is_none());
        let other = SelectionPreset {
            name: "대안".into(),
            ..preset.clone()
        };
        let other_key = registry.add(&other).unwrap();
        let other_bytes = fs::read(registry.slot_path(&other_key).unwrap()).unwrap();
        assert!(registry.save_at(&other_key, &preset).is_err());
        assert_eq!(
            fs::read(registry.slot_path(&other_key).unwrap()).unwrap(),
            other_bytes
        );
        registry.delete(&other_key).unwrap();
        registry.delete(&other_key).unwrap();
        let before = fs::read(registry.slot_path(&key).unwrap()).unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&before).unwrap(),
            hwpx_filler::preset::encode_preset(&preset).unwrap()
        );
        let mut keys = [key.clone(), "unused".into()].into_iter();
        assert_eq!(
            registry.new_key_with(|| keys.next().unwrap()).unwrap(),
            "unused"
        );
        let mut attempts = 0;
        assert!(
            registry
                .new_key_with(|| {
                    attempts += 1;
                    key.clone()
                })
                .is_err()
        );
        assert_eq!(attempts, 8);
        assert_eq!(fs::read(registry.slot_path(&key).unwrap()).unwrap(), before);
        let updated = SelectionPreset {
            created_at: "2026-11-06".into(),
            ..preset.clone()
        };
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(1 | 2)
                .open(registry.slot_path(&key).unwrap())
                .unwrap();
            assert!(registry.save_at(&key, &updated).is_err());
            drop(held);
            assert_eq!(fs::read(registry.slot_path(&key).unwrap()).unwrap(), before);
        }
        registry.save_at(&key, &updated).unwrap();
        assert_eq!(registry.load(&key).unwrap(), updated);
        registry.save_at(&key, &preset).unwrap();
        assert!(fs::read_dir(sandbox.join("presets")).unwrap().all(|entry| {
            !entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .ends_with(".tmp")
        }));
        let nested = PresetRegistry::new(sandbox.join("nested/presets")).unwrap();
        nested.save_at("first", &preset).unwrap();
        assert_eq!(nested.load("first").unwrap(), preset);
        assert_eq!(registry.delete_loaded(&key).unwrap(), preset);
        assert!(!registry.exists(&key).unwrap());
        assert!(registry.delete_loaded(&key).is_err());
        assert!(registry.delete_loaded("../outside").is_err());
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        let mut handles = Vec::new();
        for _ in 0..2 {
            let directory = sandbox.join("presets");
            let barrier = barrier.clone();
            let preset = preset.clone();
            handles.push(std::thread::spawn(move || {
                let registry = PresetRegistry::new(directory).unwrap();
                barrier.wait();
                registry.add(&preset)
            }));
        }
        assert_eq!(
            handles
                .into_iter()
                .map(|handle| handle.join().unwrap())
                .filter(Result::is_ok)
                .count(),
            1
        );
        assert_eq!(registry.list_presets().unwrap().0.len(), 1);
        let sandbox = sandbox.canonicalize().unwrap();
        assert!(
            sandbox.starts_with(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../../.cache")
                    .canonicalize()
                    .unwrap()
            )
        );
        fs::remove_dir_all(sandbox).unwrap();
    }
}
