//! Durable dataset pointer slots. Records and secrets never enter this registry.

use crate::atomic_file::write_bytes_atomic;
use crate::directory_lock::DirectoryLock;
pub use hwpx_filler::dataset_pool::CorruptDatasetEntry;
use hwpx_filler::dataset_pool::{DatasetPoolRow, PoolView};
use hwpx_filler::dataset_reference::{
    DatasetReference, DatasetReferenceError, excel_identity, pclm_identity, reference_identity,
    reference_sheets,
};
use serde_json::Value;
use std::error::Error;
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use uuid::Uuid;

mod commands;
pub use commands::{DatasetPoolCommands, ExcelRelink};

const SUFFIX: &str = ".dataset.json";

#[derive(Debug)]
pub enum PoolError {
    Io(io::Error),
    Codec(DatasetReferenceError),
    Invalid(String),
    Stale(String),
}
impl fmt::Display for PoolError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::Codec(error) => write!(f, "{error}"),
            Self::Invalid(detail) => f.write_str(detail),
            Self::Stale(detail) => f.write_str(detail),
        }
    }
}
impl Error for PoolError {}
impl From<io::Error> for PoolError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}
impl From<DatasetReferenceError> for PoolError {
    fn from(error: DatasetReferenceError) -> Self {
        Self::Codec(error)
    }
}

pub type DatasetEntries = Vec<(String, DatasetReference)>;
pub type DatasetScan = (DatasetEntries, Vec<CorruptDatasetEntry>);

pub struct DatasetPoolRegistry {
    directory: PathBuf,
    lock: DirectoryLock,
}
impl DatasetPoolRegistry {
    pub fn new(directory: PathBuf) -> io::Result<Self> {
        let lock = DirectoryLock::new(&directory)?;
        Ok(Self { directory, lock })
    }
    pub fn commands(&self) -> DatasetPoolCommands<'_> {
        DatasetPoolCommands { registry: self }
    }
    pub fn directory(&self) -> &Path {
        &self.directory
    }
    pub fn slot_path(&self, key: &str) -> Result<PathBuf, PoolError> {
        if key.is_empty()
            || key == "."
            || key == ".."
            || key.chars().any(|letter| "\\/:*?\"<>|\0".contains(letter))
        {
            return Err(PoolError::Invalid(format!(
                "올바른 등록 데이터 키가 아닙니다: {key:?}"
            )));
        }
        Ok(self.directory.join(format!("{key}{SUFFIX}")))
    }
    fn load_at(path: &Path) -> Result<DatasetReference, PoolError> {
        if fs::symlink_metadata(path)?.file_type().is_symlink() {
            return Err(PoolError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "dataset slot is a link",
            )));
        }
        let raw = fs::read(path)?;
        let value: serde_json::Value = serde_json::from_slice(&raw)
            .map_err(|error| PoolError::Io(io::Error::new(io::ErrorKind::InvalidData, error)))?;
        Ok(DatasetReference::from_dict(&value)?)
    }
    fn write_at(&self, key: &str, item: &DatasetReference) -> Result<(), PoolError> {
        item.validate()?;
        fs::create_dir_all(&self.directory)?;
        let bytes = serde_json::to_vec_pretty(&item.to_dict())
            .map_err(|error| PoolError::Io(io::Error::new(io::ErrorKind::InvalidData, error)))?;
        write_bytes_atomic(&self.slot_path(key)?, &bytes)?;
        Ok(())
    }
    pub fn load(&self, key: &str) -> Result<DatasetReference, PoolError> {
        Self::load_at(&self.slot_path(key)?)
    }
    pub fn exists(&self, key: &str) -> Result<bool, PoolError> {
        Ok(self.slot_path(key)?.exists())
    }
    fn scan(&self, isolated: bool, status: Option<&str>) -> Result<DatasetScan, PoolError> {
        if !self.directory.exists() {
            return Ok((Vec::new(), Vec::new()));
        }
        let mut paths = fs::read_dir(&self.directory)?
            .map(|entry| entry.map(|entry| entry.path()))
            .collect::<Result<Vec<_>, _>>()?;
        paths.sort();
        let mut entries = Vec::new();
        let mut corrupted = Vec::new();
        for path in paths {
            let file_name = path
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| {
                    PoolError::Io(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "dataset slot name is not Unicode",
                    ))
                })?;
            let Some(key) = file_name.strip_suffix(SUFFIX) else {
                continue;
            };
            match Self::load_at(&path) {
                Ok(item) => {
                    if status.is_none_or(|wanted| item.status == wanted) {
                        entries.push((key.to_owned(), item));
                    }
                }
                Err(error) if isolated => corrupted.push(CorruptDatasetEntry {
                    file_name: file_name.into(),
                    error: error.to_string(),
                }),
                Err(error) => return Err(error),
            }
        }
        entries.sort_by(|a, b| a.1.name.cmp(&b.1.name).then_with(|| a.0.cmp(&b.0)));
        Ok((entries, corrupted))
    }
    pub fn list_entries(
        &self,
        status: Option<&str>,
    ) -> Result<Vec<(String, DatasetReference)>, PoolError> {
        Ok(self.scan(false, status)?.0)
    }
    pub fn list_references(&self, status: Option<&str>) -> Result<DatasetScan, PoolError> {
        self.scan(true, status)
    }
    pub fn project_view(&self) -> Result<PoolView, PoolError> {
        let (entries, corrupt) = self.list_references(None)?;
        let rows = entries
            .iter()
            .map(|(key, item)| {
                let path = match item.kind.as_str() {
                    "excel" => item.opts.get("path"),
                    "pclm" => item.opts.get("db"),
                    _ => None,
                }
                .and_then(Value::as_str)
                .unwrap_or("");
                DatasetPoolRow::from_item(key, item, !path.is_empty() && !Path::new(path).exists())
            })
            .collect::<Result<Vec<_>, _>>()?;
        Ok(PoolView::project(rows, &entries, corrupt)?)
    }
    pub fn find_identity_raw(
        &self,
        identity: &str,
    ) -> Result<Option<(String, DatasetReference)>, PoolError> {
        let mut members = Vec::new();
        for (key, item) in self.scan(true, None)?.0 {
            if reference_identity(&item).as_deref() == Some(identity) {
                return Ok(Some((key, item)));
            }
            if matches!(item.kind.as_str(), "excel" | "pclm") {
                let path_key = if item.kind == "pclm" { "db" } else { "path" };
                let path = item
                    .opts
                    .get(path_key)
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("");
                let matches_sheet = reference_sheets(&item)?.iter().any(|sheet| {
                    if item.kind == "pclm" {
                        pclm_identity(path, sheet) == identity
                    } else {
                        excel_identity(path, Some(sheet)) == identity
                    }
                });
                if matches_sheet {
                    members.push((key, item));
                }
            }
        }
        Ok(if members.len() == 1 {
            members.pop()
        } else {
            None
        })
    }
    pub fn find_identity(
        &self,
        path: &str,
        sheet: Option<&str>,
    ) -> Result<Option<(String, DatasetReference)>, PoolError> {
        self.find_identity_raw(&excel_identity(path, sheet))
    }
    pub fn add(&self, item: &DatasetReference) -> Result<String, PoolError> {
        add_with_key(self, item, || {
            Uuid::new_v4().simple().to_string()[..16].to_owned()
        })
    }
    pub fn save_at(&self, key: &str, item: &DatasetReference) -> Result<(), PoolError> {
        self.lock.with(|| self.write_at(key, item))
    }
    pub fn mutate(
        &self,
        key: &str,
        change: impl FnOnce(&mut DatasetReference) -> Result<(), PoolError>,
    ) -> Result<DatasetReference, PoolError> {
        self.lock.with(|| {
            let mut item = self.load(key)?;
            change(&mut item)?;
            self.write_at(key, &item)?;
            Ok(item)
        })
    }
    pub fn delete(&self, key: &str) -> Result<(), PoolError> {
        self.lock.with(|| {
            let path = self.slot_path(key)?;
            match fs::remove_file(path) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
                Err(error) => Err(PoolError::Io(error)),
            }
        })
    }
}

fn add_with_key(
    registry: &DatasetPoolRegistry,
    item: &DatasetReference,
    mut next_key: impl FnMut() -> String,
) -> Result<String, PoolError> {
    registry.lock.with(|| {
        if let Some(identity) = reference_identity(item)
            && let Some((_, found)) = registry.find_identity_raw(&identity)?
        {
            return Err(PoolError::Invalid(format!(
                "같은 데이터(경로·시트)가 이미 '{}' 으로 고정돼 있습니다.",
                found.name
            )));
        }
        fs::create_dir_all(&registry.directory)?;
        for _ in 0..8 {
            let key = next_key();
            if !registry.slot_path(&key)?.exists() {
                registry.write_at(&key, item)?;
                return Ok(key);
            }
        }
        Err(PoolError::Invalid(
            "빈 등록 데이터 슬롯 키를 발급하지 못했습니다.".into(),
        ))
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{DatasetPoolRegistry, ExcelRelink, PoolError};
    use hwpx_filler::dataset_pool::{bound_state, confirm_basis};
    use hwpx_filler::dataset_reference::{DatasetReference, STATUS_ACTIVE, STATUS_ARCHIVED};
    use serde_json::{Map, Value};
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn pool_slots_keep_identity_and_surface_corruption() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-pool-{}-{stamp}",
            std::process::id()
        ));
        let registry = DatasetPoolRegistry::new(sandbox.join("datasets")).unwrap();
        assert_legacy_slot_lifecycle(&sandbox);
        assert_sheet_filter_reload(&sandbox);
        assert_concurrent_slot_writers(&sandbox);
        assert_relink_identity_is_checked_inside_writer_gate(&sandbox);
        assert_add_and_save_share_writer_gate(&sandbox);
        assert_confirmed_commands_preserve_current_slots(&sandbox);
        assert_duplicate_commands_bind_the_whole_group(&sandbox);
        let mut opts = Map::new();
        opts.insert("path".into(), Value::String("C:/data/입력.csv".into()));
        let first = DatasetReference::new("첫 이름", "excel", opts.clone()).unwrap();
        let key = registry.add(&first).unwrap();
        assert_eq!(key.len(), 16);
        let same = DatasetReference::new("다른 이름", "excel", opts).unwrap();
        assert!(registry.add(&same).is_err());
        let mut sheet_opts = Map::new();
        let sheet_path = sandbox.join("sheets.xlsx").to_str().unwrap().to_owned();
        sheet_opts.insert("path".into(), Value::String(sheet_path.clone()));
        sheet_opts.insert("sheet".into(), Value::String("A".into()));
        sheet_opts.insert(
            "sheets".into(),
            Value::Array(vec![Value::String("A".into()), Value::String("B".into())]),
        );
        let sheet_item = DatasetReference::new("여러 시트", "excel", sheet_opts).unwrap();
        let sheet_key = registry.add(&sheet_item).unwrap();
        assert_eq!(
            registry
                .find_identity(&sheet_path, Some("B"))
                .unwrap()
                .unwrap()
                .0,
            sheet_key
        );
        for key in ["", ".", "..", "a/b", "a\\b", "../outside"] {
            assert!(registry.slot_path(key).is_err());
        }
        assert_eq!(
            registry.commands().archive(&key).unwrap().status,
            STATUS_ARCHIVED
        );
        assert_eq!(
            registry.commands().activate(&key).unwrap().status,
            STATUS_ACTIVE
        );
        registry.commands().relabel(&key, "바뀐 이름", "").unwrap();
        assert_eq!(registry.load(&key).unwrap().name, "바뀐 이름");
        registry.commands().archive(&key).unwrap();
        let relinked = registry
            .commands()
            .relink_excel(&key, "C:/data/new.csv", None, "", "", None)
            .unwrap();
        assert_eq!(relinked.status, STATUS_ARCHIVED);
        assert_eq!(relinked.name, "바뀐 이름");
        assert_eq!(relinked.opts["path"], "C:/data/new.csv");
        let relink_basis = confirm_basis(&[bound_state(&key, &relinked).unwrap()]);
        assert!(matches!(
            registry.commands().relink_confirmed(
                &key,
                &ExcelRelink {
                    path: "C:/data/other.csv",
                    sheet: None,
                    note: "",
                    name: "",
                    sheets: None
                },
                None
            ),
            Err(PoolError::Stale(_))
        ));
        assert_eq!(registry.load(&key).unwrap().opts["path"], "C:/data/new.csv");
        let (_, relabeled) = registry
            .commands()
            .relabel_confirmed(
                "C:/data/new.csv",
                None,
                "바뀐 이름",
                "메모",
                None,
                Some(&relink_basis),
            )
            .unwrap();
        assert_eq!(relabeled.note, "메모");
        registry.save_at("legacy", &sheet_item).unwrap();
        let basis = confirm_basis(&[
            bound_state(&sheet_key, &registry.load(&sheet_key).unwrap()).unwrap(),
            bound_state("legacy", &registry.load("legacy").unwrap()).unwrap(),
        ]);
        assert!(matches!(
            registry.commands().resolve_duplicates(&sheet_key, None),
            Err(PoolError::Stale(_))
        ));
        registry
            .commands()
            .relabel("legacy", "새 라벨", "")
            .unwrap();
        assert!(matches!(
            registry
                .commands()
                .resolve_duplicates(&sheet_key, Some(&basis)),
            Err(PoolError::Stale(_))
        ));
        assert!(registry.exists("legacy").unwrap());
        let fresh = confirm_basis(&[
            bound_state(&sheet_key, &registry.load(&sheet_key).unwrap()).unwrap(),
            bound_state("legacy", &registry.load("legacy").unwrap()).unwrap(),
        ]);
        assert_eq!(
            registry
                .commands()
                .resolve_duplicates(&sheet_key, Some(&fresh))
                .unwrap(),
            ("여러 시트".into(), 1)
        );
        let delete_basis =
            confirm_basis(&[bound_state(&key, &registry.load(&key).unwrap()).unwrap()]);
        assert!(matches!(
            registry.commands().delete_confirmed(&key, None),
            Err(PoolError::Stale(_))
        ));
        assert_eq!(
            registry
                .commands()
                .delete_confirmed(&key, Some(&delete_basis))
                .unwrap()
                .name,
            "바뀐 이름"
        );
        assert_pipeline_references_reload_without_saving_records(&registry, &sandbox);
        fs::write(sandbox.join("datasets/broken.dataset.json"), b"{").unwrap();
        assert!(registry.list_entries(None).is_err());
        let (entries, corrupt) = registry.list_references(None).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(corrupt.len(), 1);
        assert_eq!(corrupt[0].file_name, "broken.dataset.json");
        let view = registry.project_view().unwrap();
        assert_eq!(view.rows.len(), 1);
        assert_eq!(view.corrupted.len(), 1);
        assert_eq!(view.rows[0].name, "여러 시트");
        assert!(view.rows[0].missing);
        assert!(!registry.exists(&key).unwrap());
        fs::remove_dir_all(sandbox).unwrap();
    }

    fn assert_confirmed_commands_preserve_current_slots(sandbox: &Path) {
        use serde_json::json;
        let registry = DatasetPoolRegistry::new(sandbox.join("confirmed-commands")).unwrap();
        let mut first = DatasetReference::new(
            "A",
            "excel",
            json!({"path":"/a.xlsx"}).as_object().unwrap().clone(),
        )
        .unwrap();
        first.note = "6월분".into();
        let key = registry.add(&first).unwrap();
        let other = registry
            .add(
                &DatasetReference::new(
                    "B",
                    "excel",
                    json!({"path":"/b.xlsx"}).as_object().unwrap().clone(),
                )
                .unwrap(),
            )
            .unwrap();
        registry.commands().archive(&key).unwrap();
        let basis =
            |key: &str| confirm_basis(&[bound_state(key, &registry.load(key).unwrap()).unwrap()]);
        let original = basis(&key);
        let request = ExcelRelink {
            path: "/a2.xlsx",
            sheet: None,
            note: "",
            name: "",
            sheets: None,
        };
        let updated = registry
            .commands()
            .relink_confirmed(&key, &request, Some(&original))
            .unwrap();
        assert_eq!(updated.status, STATUS_ARCHIVED);
        assert_eq!(updated.note, "6월분");
        assert_eq!(updated.opts["path"], "/a2.xlsx");
        let theft = registry
            .commands()
            .relink_confirmed(&other, &request, Some(&basis(&other)))
            .unwrap_err();
        assert!(theft.to_string().contains("이미"));
        assert_eq!(registry.load(&other).unwrap().opts["path"], "/b.xlsx");
        for stale in [None, Some(original.as_str())] {
            assert!(matches!(
                registry.commands().relink_confirmed(&key, &request, stale),
                Err(PoolError::Stale(_))
            ));
            assert_eq!(registry.load(&key).unwrap(), updated);
        }
        let request = ExcelRelink {
            path: "/b.xlsx",
            sheet: Some("7월"),
            note: "월분 교체",
            name: "발주 7월",
            sheets: Some(&["7월".into(), "8월".into()]),
        };
        let updated = registry
            .commands()
            .relink_confirmed(&key, &request, Some(&basis(&key)))
            .unwrap();
        assert_eq!(updated.kind, "excel");
        assert_eq!(
            updated.opts,
            json!({"path":"/b.xlsx","sheet":"7월","sheets":["7월","8월"]})
                .as_object()
                .unwrap()
                .clone()
        );
        assert_eq!(
            (updated.name.as_str(), updated.note.as_str()),
            ("발주 7월", "월분 교체")
        );
        assert_eq!(
            registry
                .find_identity("/b.xlsx", Some("7월"))
                .unwrap()
                .unwrap()
                .0,
            key
        );
        let renamed = registry
            .commands()
            .relabel(&key, "발주 8월", "차월 재사용")
            .unwrap();
        assert_eq!(
            (renamed.name.as_str(), renamed.note.as_str()),
            ("발주 8월", "차월 재사용")
        );
        let before = basis(&key);
        let (_, changed) = registry
            .commands()
            .relabel_confirmed(
                "/b.xlsx",
                Some("8월"),
                "발주 8월",
                "",
                Some(&["8월".into(), "9월".into()]),
                Some(&before),
            )
            .unwrap();
        assert_eq!(
            changed.opts,
            json!({"path":"/b.xlsx","sheet":"8월","sheets":["8월","9월"]})
                .as_object()
                .unwrap()
                .clone()
        );
        assert_eq!(changed.note, "차월 재사용");
        for stale in [None, Some(before.as_str())] {
            assert!(matches!(
                registry.commands().relabel_confirmed(
                    "/b.xlsx",
                    Some("8월"),
                    "덮어쓰기",
                    "",
                    None,
                    stale
                ),
                Err(PoolError::Stale(_))
            ));
            assert!(matches!(
                registry.commands().delete_confirmed(&key, stale),
                Err(PoolError::Stale(_))
            ));
            assert_eq!(registry.load(&key).unwrap(), changed);
        }
        let fresh = basis(&key);
        assert_eq!(
            registry
                .commands()
                .delete_confirmed(&key, Some(&fresh))
                .unwrap(),
            changed
        );
        assert!(
            registry
                .commands()
                .delete_confirmed(&key, Some(&fresh))
                .is_err()
        );
        assert!(
            registry
                .commands()
                .relabel_confirmed("/b.xlsx", Some("8월"), "부활", "", None, Some(&fresh))
                .is_err()
        );
        assert!(
            registry
                .commands()
                .relink_excel(&key, "/new.xlsx", None, "", "", None)
                .is_err()
        );
        assert!(!registry.exists(&key).unwrap());
        registry.delete(&other).unwrap();
        assert!(registry.project_view().unwrap().rows.is_empty());
    }

    fn assert_duplicate_commands_bind_the_whole_group(sandbox: &Path) {
        use serde_json::json;
        for (kind, opts) in [
            ("excel", json!({"path":"/same.xlsx"})),
            ("pclm", json!({"db":"/same.db","view":"v_공고"})),
        ] {
            let registry =
                DatasetPoolRegistry::new(sandbox.join(format!("duplicates-{kind}"))).unwrap();
            for name in ["구판", "최신"] {
                registry
                    .save_at(
                        name,
                        &DatasetReference::new(name, kind, opts.as_object().unwrap().clone())
                            .unwrap(),
                    )
                    .unwrap();
            }
            let view = registry.project_view().unwrap();
            assert_eq!(view.duplicate_keys, [vec!["구판", "최신"]]);
            let basis = || {
                confirm_basis(
                    &registry
                        .list_entries(None)
                        .unwrap()
                        .iter()
                        .map(|(key, item)| bound_state(key, item).unwrap())
                        .collect::<Vec<_>>(),
                )
            };
            let before = basis();
            registry
                .commands()
                .relabel("구판", "남이 개명", "")
                .unwrap();
            assert!(matches!(
                registry
                    .commands()
                    .resolve_duplicates("최신", Some(&before)),
                Err(PoolError::Stale(_))
            ));
            assert_eq!(registry.list_entries(None).unwrap().len(), 2);
            let fresh = basis();
            assert_eq!(
                registry
                    .commands()
                    .resolve_duplicates("최신", Some(&fresh))
                    .unwrap(),
                ("최신".into(), 1)
            );
            let view = registry.project_view().unwrap();
            assert_eq!(view.rows.len(), 1);
            assert_eq!(view.rows[0].name, "최신");
            assert!(view.duplicate_keys.is_empty());
            assert!(
                registry
                    .commands()
                    .resolve_duplicates("최신", Some(&fresh))
                    .is_err()
            );
            assert!(registry.exists("최신").unwrap());
        }
    }

    fn assert_legacy_slot_lifecycle(sandbox: &Path) {
        use serde_json::json;
        let directory = sandbox.join("legacy");
        let registry = DatasetPoolRegistry::new(directory.clone()).unwrap();
        assert!(registry.list_entries(None).unwrap().is_empty());
        let legacy = "{\n  \"version\": 1,\n  \"name\": \"구\",\n  \"kind\": \"excel\",\n  \"opts\": {\n    \"path\": \"/d.xlsx\"\n  },\n  \"status\": \"active\",\n  \"created_at\": \"\",\n  \"note\": \"\"\n}";
        fs::create_dir_all(&directory).unwrap();
        let slot = registry.slot_path("7월 공고").unwrap();
        fs::write(&slot, legacy).unwrap();
        let item = registry.load("7월 공고").unwrap();
        assert!(item.filters.is_empty());
        registry.save_at("7월 공고", &item).unwrap();
        assert_eq!(fs::read_to_string(&slot).unwrap(), legacy);
        registry.save_at("공고 최신", &item).unwrap();
        assert_eq!(registry.list_entries(None).unwrap().len(), 2);
        registry.commands().archive("7월 공고").unwrap();
        assert_eq!(registry.list_entries(Some(STATUS_ACTIVE)).unwrap().len(), 1);
        registry.delete("7월 공고").unwrap();
        registry.delete("7월 공고").unwrap();
        registry.delete("공고 최신").unwrap();

        for (name, bgn, end, expected) in [
            (" \t", "202606010000", "202606302359", "이름"),
            ("공고", "", "202606302359", "조회 기간"),
            ("공고", "202606010000", "", "조회 기간"),
            ("공고", "202601010000", "202607010000", "1개월"),
            ("공고", "2026-06-01 00", "202606302359", ""),
        ] {
            assert!(
                registry
                    .commands()
                    .register_nara(name, bgn, end, None, None, "")
                    .unwrap_err()
                    .to_string()
                    .contains(expected)
            );
            assert!(registry.list_entries(None).unwrap().is_empty());
        }
        let mut nara = registry
            .commands()
            .register_nara(
                "  6월 공고  ",
                "202606010000",
                "202606302359",
                Some(100),
                Some(0),
                "6월분",
            )
            .unwrap();
        assert_eq!(nara.name, "6월 공고");
        assert_eq!(nara.note, "6월분");
        assert_eq!(
            nara.opts,
            json!({"bgn_dt":"202606010000","end_dt":"202606302359","num_rows":100})
                .as_object()
                .unwrap()
                .clone()
        );
        let nara_key = registry.list_entries(None).unwrap()[0].0.clone();
        nara.created_at = "2026-07-12T09:00:00".into();
        registry.save_at(&nara_key, &nara).unwrap();
        assert_eq!(registry.load(&nara_key).unwrap(), nara);
        let saved = fs::read_to_string(registry.slot_path(&nara_key).unwrap()).unwrap();
        assert_eq!(
            saved,
            serde_json::to_string_pretty(&nara.to_dict()).unwrap()
        );
        assert!(!saved.contains("ServiceKey") && !saved.contains("service_key"));
        registry.delete(&nara_key).unwrap();
        let defaults = registry
            .commands()
            .register_nara("기본", "202606010000", "202606302359", None, None, "")
            .unwrap();
        assert_eq!(defaults.opts.len(), 2);
        let key = registry.list_entries(None).unwrap()[0].0.clone();
        registry.delete(&key).unwrap();
        let paged = registry
            .commands()
            .register_nara("둘째", "202606010000", "202606302359", Some(0), Some(2), "")
            .unwrap();
        assert!(!paged.opts.contains_key("num_rows"));
        assert_eq!(paged.opts["page_no"], 2);
        let key = registry.list_entries(None).unwrap()[0].0.clone();
        registry.delete(&key).unwrap();

        let first = DatasetReference::new(
            "매출",
            "excel",
            json!({"path":"C:/d/A.xlsx"}).as_object().unwrap().clone(),
        )
        .unwrap();
        let key = registry.add(&first).unwrap();
        let other_registry = DatasetPoolRegistry::new(sandbox.join("other-slots")).unwrap();
        assert_ne!(key, other_registry.add(&first).unwrap());
        assert_eq!(
            registry
                .find_identity("C:\\d\\a.XLSX", None)
                .unwrap()
                .unwrap()
                .0,
            key
        );
        assert!(
            registry
                .find_identity("C:/d/A.xlsx", Some("물품"))
                .unwrap()
                .is_none()
        );
        registry
            .mutate(&key, |item| {
                item.opts.insert("path".into(), json!("C:/d/B.xlsx"));
                Ok(())
            })
            .unwrap();
        assert!(
            registry
                .find_identity("C:/d/A.xlsx", None)
                .unwrap()
                .is_none()
        );
        let again = registry.add(&first).unwrap();
        assert_ne!(again, key);
        assert_eq!(
            registry
                .find_identity("C:/d/A.xlsx", None)
                .unwrap()
                .unwrap()
                .0,
            again
        );
        assert_eq!(registry.load(&key).unwrap().opts["path"], "C:/d/B.xlsx");
        assert!(registry.add(&registry.load(&key).unwrap()).is_err());
        assert_eq!(
            registry
                .list_entries(None)
                .unwrap()
                .iter()
                .map(|(_, item)| item.name.as_str())
                .collect::<Vec<_>>(),
            ["매출", "매출"]
        );
        registry.commands().relabel(&again, "A", "").unwrap();
        registry.commands().relabel(&key, "B", "").unwrap();
        let mut attempts = 0;
        let exhausted = super::add_with_key(&registry, &nara, || {
            attempts += 1;
            key.clone()
        })
        .unwrap_err();
        assert_eq!(attempts, 8);
        assert!(exhausted.to_string().contains("발급하지"));
        assert_eq!(registry.load(&key).unwrap().name, "B");
        let mut attempts = 0;
        let allocated = super::add_with_key(&registry, &nara, || {
            attempts += 1;
            if attempts == 1 {
                key.clone()
            } else {
                "fresh-slot".into()
            }
        })
        .unwrap();
        assert_eq!(attempts, 2);
        assert_eq!(registry.load(&allocated).unwrap(), nara);
        registry.delete(&allocated).unwrap();
        assert_eq!(
            registry
                .list_entries(None)
                .unwrap()
                .iter()
                .map(|(key, _)| key.as_str())
                .collect::<Vec<_>>(),
            [again, key]
        );
    }

    fn assert_concurrent_slot_writers(sandbox: &Path) {
        use serde_json::json;
        use std::sync::mpsc;
        use std::time::Duration;
        let directory = sandbox.join("concurrent-writers");
        let updater = DatasetPoolRegistry::new(directory.clone()).unwrap();
        let peer = DatasetPoolRegistry::new(directory).unwrap();
        let item = DatasetReference::new(
            "공고",
            "excel",
            json!({"path":"/old.xlsx"}).as_object().unwrap().clone(),
        )
        .unwrap();
        for delete in [false, true] {
            let key = updater.add(&item).unwrap();
            let (entered_tx, entered_rx) = mpsc::channel();
            let (release_tx, release_rx) = mpsc::channel();
            let (started_tx, started_rx) = mpsc::channel();
            let (done_tx, done_rx) = mpsc::channel();
            std::thread::scope(|scope| {
                let writer = &updater;
                let slot = &key;
                let first = scope.spawn(move || {
                    writer.mutate(slot, |item| {
                        entered_tx.send(()).unwrap();
                        release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                        item.opts.insert("path".into(), json!("/new.xlsx"));
                        Ok(())
                    })
                });
                entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                let second = scope.spawn(|| {
                    started_tx.send(()).unwrap();
                    let result = if delete {
                        peer.delete(&key)
                    } else {
                        peer.commands().archive(&key).map(|_| ())
                    };
                    done_tx.send(result).unwrap();
                });
                started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                let waiting = done_rx.recv_timeout(Duration::from_millis(50));
                release_tx.send(()).unwrap();
                assert!(
                    matches!(waiting, Err(mpsc::RecvTimeoutError::Timeout)),
                    "peer writer bypassed the directory gate"
                );
                first.join().unwrap().unwrap();
                second.join().unwrap();
                done_rx
                    .recv_timeout(Duration::from_secs(5))
                    .unwrap()
                    .unwrap();
            });
            if delete {
                assert!(!updater.exists(&key).unwrap());
            } else {
                let saved = updater.load(&key).unwrap();
                assert_eq!(saved.opts["path"], "/new.xlsx");
                assert_eq!(saved.status, STATUS_ARCHIVED);
                updater.delete(&key).unwrap();
            }
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
            let key = updater.add(&item).unwrap();
            let path = updater.slot_path(&key).unwrap();
            let before = fs::read(&path).unwrap();
            // Permit the read in mutate, but refuse the final replacement.
            let held = fs::OpenOptions::new()
                .read(true)
                .share_mode(FILE_SHARE_READ)
                .open(&path)
                .unwrap();
            assert!(updater.commands().archive(&key).is_err());
            assert_eq!(fs::read(&path).unwrap(), before);
            assert_eq!(fs::read_dir(updater.directory()).unwrap().count(), 1);
            drop(held);
            updater.commands().archive(&key).unwrap();
            assert_eq!(updater.load(&key).unwrap().status, STATUS_ARCHIVED);
        }
    }

    fn assert_relink_identity_is_checked_inside_writer_gate(sandbox: &Path) {
        use serde_json::json;
        use std::sync::mpsc;
        use std::time::Duration;
        let directory = sandbox.join("relink-writer-gate");
        let registry = DatasetPoolRegistry::new(directory.clone()).unwrap();
        let peer = DatasetPoolRegistry::new(directory).unwrap();
        let item = |name, path| {
            DatasetReference::new(
                name,
                "excel",
                json!({"path":path}).as_object().unwrap().clone(),
            )
            .unwrap()
        };
        let first_key = registry.add(&item("A", "/a.xlsx")).unwrap();
        let second_item = item("B", "/b.xlsx");
        let second_key = registry.add(&second_item).unwrap();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let (started_tx, started_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();
        std::thread::scope(|scope| {
            let writer = &registry;
            let slot = &first_key;
            let first = scope.spawn(move || {
                writer.mutate(slot, |item| {
                    entered_tx.send(()).unwrap();
                    release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    item.opts.insert("path".into(), json!("/target.xlsx"));
                    Ok(())
                })
            });
            entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            let second = scope.spawn(|| {
                started_tx.send(()).unwrap();
                done_tx
                    .send(peer.commands().relink_excel(
                        &second_key,
                        "/target.xlsx",
                        None,
                        "",
                        "",
                        None,
                    ))
                    .unwrap();
            });
            started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            let waiting = done_rx.recv_timeout(Duration::from_millis(50));
            release_tx.send(()).unwrap();
            assert!(
                matches!(waiting, Err(mpsc::RecvTimeoutError::Timeout)),
                "relink bypassed the directory gate"
            );
            first.join().unwrap().unwrap();
            second.join().unwrap();
            let refusal = done_rx
                .recv_timeout(Duration::from_secs(5))
                .unwrap()
                .unwrap_err();
            assert!(matches!(refusal, PoolError::Invalid(_)));
            assert!(refusal.to_string().contains("이미"));
        });
        assert_eq!(
            registry
                .find_identity("/target.xlsx", None)
                .unwrap()
                .unwrap()
                .0,
            first_key
        );
        assert_eq!(registry.load(&second_key).unwrap(), second_item);
        assert!(registry.project_view().unwrap().duplicate_keys.is_empty());
    }

    fn assert_add_and_save_share_writer_gate(sandbox: &Path) {
        use std::sync::mpsc;
        use std::time::Duration;
        let directory = sandbox.join("add-writer-gate");
        let registry = DatasetPoolRegistry::new(directory.clone()).unwrap();
        let peer = DatasetPoolRegistry::new(directory).unwrap();
        let item = DatasetReference::new("소스", "inline", Map::new()).unwrap();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let (started_tx, started_rx) = mpsc::channel();
        let (done_tx, done_rx) = mpsc::channel();
        std::thread::scope(|scope| {
            let writer = &registry;
            let reference = &item;
            let first = scope.spawn(move || {
                super::add_with_key(writer, reference, || {
                    entered_tx.send(()).unwrap();
                    release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                    "generated".into()
                })
            });
            entered_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            let second = scope.spawn(|| {
                started_tx.send(()).unwrap();
                done_tx.send(peer.save_at("peer", &item)).unwrap();
            });
            started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            let waiting = done_rx.recv_timeout(Duration::from_millis(50));
            release_tx.send(()).unwrap();
            assert!(
                matches!(waiting, Err(mpsc::RecvTimeoutError::Timeout)),
                "add/save must share the writer gate"
            );
            assert_eq!(first.join().unwrap().unwrap(), "generated");
            second.join().unwrap();
            done_rx
                .recv_timeout(Duration::from_secs(5))
                .unwrap()
                .unwrap();
        });
        assert_eq!(registry.load("generated").unwrap(), item);
        assert_eq!(registry.load("peer").unwrap(), item);
    }

    fn assert_sheet_filter_reload(sandbox: &Path) {
        use hwpx_filler::dataset_reference::{
            excel_identity, filters_for_sheet, pclm_identity, reference_for_sheet, reference_sheets,
        };
        use serde_json::json;
        let small = json!({"name":"소기업","state":{"search":"","pruned":[],"columns":{"추정가격":{
            "text":"","values":null,"range":{"first":{"op":"lt","operand":"100,000,000"},"second":null,"joiner":"and"}
        }}}});
        for (kind, path_key, sheet_key) in [("excel", "path", "sheet"), ("pclm", "db", "view")] {
            let directory = sandbox.join(format!("filters-{kind}"));
            let registry = DatasetPoolRegistry::new(directory.clone()).unwrap();
            let item = DatasetReference::new(
                "월별 자료",
                kind,
                json!({path_key:"/d.xlsx",sheet_key:"1월","sheets":["1월","2월"]})
                    .as_object()
                    .unwrap()
                    .clone(),
            )
            .unwrap();
            let key = registry.add(&item).unwrap();
            let january = json!([small]);
            let february = json!([{"name":"2월 조건","state":{"search":"서울"}}]);
            registry
                .commands()
                .set_filters(&key, &january, Some("1월"))
                .unwrap();
            registry
                .commands()
                .set_filters(&key, &february, Some("2월"))
                .unwrap();
            let back = DatasetPoolRegistry::new(directory)
                .unwrap()
                .load(&key)
                .unwrap();
            assert_eq!(reference_sheets(&back).unwrap(), ["1월", "2월"]);
            assert_eq!(
                filters_for_sheet(&back, Some("1월")).unwrap()[0].to_dict(),
                small
            );
            let selected = reference_for_sheet(&back, Some("2월")).unwrap();
            assert_eq!(selected.opts[sheet_key], "2월");
            assert_eq!(selected.filters[0].to_dict(), february[0]);
            assert_eq!(back.opts[sheet_key], "1월");
            assert!(
                registry
                    .commands()
                    .set_filters(&key, &json!([]), Some("3월"))
                    .is_err()
            );
            assert!(reference_for_sheet(&back, Some("3월")).is_err());
            let basis = confirm_basis(&[bound_state(&key, &back).unwrap()]);
            let identity = if kind == "pclm" {
                pclm_identity("/d.xlsx", "2월")
            } else {
                excel_identity("/d.xlsx", Some("2월"))
            };
            assert_eq!(
                registry.find_identity_raw(&identity).unwrap().unwrap().0,
                key
            );
            let (_, changed) = registry
                .commands()
                .relabel_confirmed_raw(
                    &identity,
                    "월별 자료",
                    "",
                    Some(&["2월".into(), "1월".into()]),
                    Some(&basis),
                )
                .unwrap();
            let default = if kind == "pclm" { "1월" } else { "2월" };
            assert_eq!(changed.opts[sheet_key], default);
            assert_eq!(
                changed.filters[0].to_dict(),
                if kind == "pclm" {
                    small.clone()
                } else {
                    february[0].clone()
                }
            );
            assert_eq!(
                filters_for_sheet(&changed, Some("1월")).unwrap()[0].to_dict(),
                small
            );
            assert_eq!(
                filters_for_sheet(&changed, Some("2월")).unwrap()[0].to_dict(),
                february[0]
            );
            assert!(matches!(
                registry.commands().relabel_confirmed_raw(
                    &identity,
                    "덮어쓰기",
                    "",
                    Some(&["2월".into()]),
                    Some(&basis)
                ),
                Err(PoolError::Stale(_))
            ));
            assert_eq!(registry.load(&key).unwrap().name, "월별 자료");
            assert!(
                registry
                    .commands()
                    .set_filters("missing", &january, None)
                    .is_err()
            );
            assert!(!registry.exists("missing").unwrap());
            let mut corrupt = changed.to_dict();
            corrupt["filters"] = json!([{"name":"","state":{}}]);
            fs::write(
                registry.slot_path(&key).unwrap(),
                serde_json::to_vec(&corrupt).unwrap(),
            )
            .unwrap();
            let (entries, corrupt) = registry.list_references(None).unwrap();
            assert!(entries.is_empty());
            assert_eq!(corrupt.len(), 1);
        }
        assert_default_filter_lifecycle(sandbox, &small);
        assert_member_lookup(sandbox);
    }

    fn assert_default_filter_lifecycle(sandbox: &Path, small: &Value) {
        use hwpx_filler::dataset_reference::{filters_for_sheet, reference_for_sheet};
        use serde_json::json;
        let directory = sandbox.join("default-filters");
        let registry = DatasetPoolRegistry::new(directory.clone()).unwrap();
        let mut item = DatasetReference::new(
            "입찰",
            "excel",
            json!({"path":"/d.xlsx"}).as_object().unwrap().clone(),
        )
        .unwrap();
        item.note = "메모".into();
        let key = registry.add(&item).unwrap();
        let presets =
            json!([small, {"name":"중소기업","state":{"search":"","pruned":[],"columns":{}}}]);
        let updated = registry
            .commands()
            .set_filters(&key, &presets, Some(""))
            .unwrap();
        assert_eq!(
            reference_for_sheet(&updated, Some("")).unwrap().opts,
            item.opts
        );
        let reloaded = DatasetPoolRegistry::new(directory)
            .unwrap()
            .load(&key)
            .unwrap();
        assert_eq!(
            reloaded
                .filters
                .iter()
                .map(|preset| preset.to_dict())
                .collect::<Vec<_>>(),
            *presets.as_array().unwrap()
        );
        assert_eq!(
            (&reloaded.name, &reloaded.opts, &reloaded.note),
            (&item.name, &item.opts, &item.note)
        );
        registry.commands().archive(&key).unwrap();
        registry.commands().relabel(&key, "입찰(보관)", "").unwrap();
        let changed = registry
            .commands()
            .relink_excel(
                &key,
                "/d.xlsx",
                Some("기본"),
                "",
                "",
                Some(&["기본".into()]),
            )
            .unwrap();
        assert_eq!(
            filters_for_sheet(&changed, Some("기본")).unwrap(),
            updated.filters
        );
        registry
            .commands()
            .set_filters(&key, &json!([]), None)
            .unwrap();
        let raw = fs::read_to_string(registry.slot_path(&key).unwrap()).unwrap();
        assert!(!raw.contains("\"filters\""));
    }

    fn assert_member_lookup(sandbox: &Path) {
        use serde_json::json;
        let registry = DatasetPoolRegistry::new(sandbox.join("member-lookup")).unwrap();
        let first = registry
            .add(
                &DatasetReference::new(
                    "상반기",
                    "excel",
                    json!({"path":"/d.xlsx","sheet":"1월","sheets":["1월","2월"]})
                        .as_object()
                        .unwrap()
                        .clone(),
                )
                .unwrap(),
            )
            .unwrap();
        assert_eq!(
            registry
                .find_identity("/d.xlsx", Some("2월"))
                .unwrap()
                .unwrap()
                .0,
            first
        );
        registry
            .add(
                &DatasetReference::new(
                    "부분",
                    "excel",
                    json!({"path":"/d.xlsx","sheet":"3월","sheets":["3월","2월"]})
                        .as_object()
                        .unwrap()
                        .clone(),
                )
                .unwrap(),
            )
            .unwrap();
        assert!(
            registry
                .find_identity("/d.xlsx", Some("2월"))
                .unwrap()
                .is_none()
        );
        let legacy = registry
            .add(
                &DatasetReference::new(
                    "구판 2월",
                    "excel",
                    json!({"path":"/d.xlsx","sheet":"2월"})
                        .as_object()
                        .unwrap()
                        .clone(),
                )
                .unwrap(),
            )
            .unwrap();
        assert_eq!(
            registry
                .find_identity("/d.xlsx", Some("2월"))
                .unwrap()
                .unwrap()
                .0,
            legacy
        );
    }

    fn assert_pipeline_references_reload_without_saving_records(
        registry: &DatasetPoolRegistry,
        sandbox: &Path,
    ) {
        use hwpx_filler::data_factory::source_from_pool_item;
        use serde_json::json;
        let a = sandbox.join("a.csv");
        let b = sandbox.join("b.csv");
        fs::write(&a, "\u{feff}id,name\n1,A\n2,B\n").unwrap();
        fs::write(&b, "\u{feff}id,city\n1,서울\n2,부산\n").unwrap();
        let item = DatasetReference::new(
            "6월/조립",
            "pipeline",
            serde_json::from_value(json!({
                "sources":[{"kind":"excel","opts":{"path":a}},{"kind":"excel","opts":{"path":b}}],
                "steps":[{"op":"merge","source":1,"on":"id","how":"inner"}]
            }))
            .unwrap(),
        )
        .unwrap();
        let key = registry.add(&item).unwrap();
        let saved = fs::read_to_string(registry.slot_path(&key).unwrap()).unwrap();
        assert!(!saved.contains("서울") && !saved.contains("부산"));
        assert!(saved.contains("a.csv") && saved.contains("merge"));
        let restored = registry.load(&key).unwrap();
        assert_eq!(restored.to_dict(), item.to_dict());
        let mut source = source_from_pool_item(&restored).unwrap();
        let records = source.records().unwrap();
        assert_eq!(records.len(), 2);
        assert_eq!(records[0]["name"], "A");
        assert_eq!(records[0]["city"], "서울");
        assert_eq!(records[1]["city"], "부산");
        fs::write(&b, "id,city\n1,서울\n2,대전\n").unwrap();
        assert_eq!(source.records().unwrap(), records);
        assert_eq!(
            source_from_pool_item(&restored).unwrap().records().unwrap()[1]["city"],
            "대전"
        );
        let second = DatasetReference::new(
            "6월_조립",
            "pipeline",
            serde_json::from_value(json!({"sources":[],"steps":[]})).unwrap(),
        )
        .unwrap();
        let second_key = registry.add(&second).unwrap();
        assert_ne!(key, second_key);
        assert_eq!(registry.load(&key).unwrap().name, "6월/조립");
        assert_eq!(registry.load(&second_key).unwrap().name, "6월_조립");
        registry.delete(&key).unwrap();
        registry.delete(&second_key).unwrap();
    }
}
