//! Tutorial-only persistence and isolated lesson homes.

use crate::atomic_file::write_bytes_atomic;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use uuid::Uuid;
use zip::{ZipArchive, ZipWriter, write::SimpleFileOptions};

pub const ORIGINALS: [&str; 4] = [
    "물품 구매입찰 공고.hwpx",
    "낙찰자 선정 및 계약체결 안내.txt",
    "계약방법 결정 및 구매추진 안내.txt",
    "공고목록.xlsx",
];
pub const DATA_NAME: &str = "공고목록.xlsx";
pub const MODIFIED_REASON: &str = "연습 파일이 수정됐습니다. 현재 파일을 보존합니다.";
const MISSING: &str = "연습 파일이 없거나 이동했습니다.";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PracticeEntry {
    pub name: String,
    pub path: String,
    pub sha256: String,
    pub batch: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub derived: Option<String>,
}

#[derive(Clone, Debug)]
pub struct SeededLesson {
    pub home: PathBuf,
    pub batch: String,
    pub assets: Vec<PracticeEntry>,
    pub derived_entry: Option<PracticeEntry>,
}

impl SeededLesson {
    pub fn as_value(&self) -> Value {
        let mut assets = serde_json::Map::new();
        for entry in &self.assets {
            assets.insert(entry.name.clone(), json!(entry));
        }
        json!({"home": self.home.to_string_lossy(), "batch": self.batch,
               "assets": assets, "derived_entry": self.derived_entry})
    }
}

pub struct TutorialWorkspace {
    pub root: PathBuf,
    pub assets: PathBuf,
    alert: Arc<dyn Fn(String) + Send + Sync>,
}

impl TutorialWorkspace {
    pub fn new(
        root: PathBuf,
        assets: PathBuf,
        alert: impl Fn(String) + Send + Sync + 'static,
    ) -> Self {
        Self {
            root,
            assets,
            alert: Arc::new(alert),
        }
    }

    pub fn first_launch_candidate(home: &Path) -> bool {
        match fs::read_dir(home) {
            Ok(mut entries) => entries.next().is_none(),
            Err(error) if error.kind() == io::ErrorKind::NotFound => true,
            Err(_) => false,
        }
    }

    pub fn load_progress(&self) -> Value {
        match fs::read_to_string(self.root.join("progress.json")) {
            Ok(raw) => match serde_json::from_str::<Value>(&raw) {
                Ok(value) if value.is_object() => value,
                Ok(_) => json!({}),
                Err(error) => {
                    (self.alert)(format!(
                        "튜토리얼 학습 기록 판독 실패 — 처음 상태로 엽니다: {error}"
                    ));
                    json!({})
                }
            },
            Err(error) if error.kind() == io::ErrorKind::NotFound => json!({}),
            Err(error) => {
                (self.alert)(format!(
                    "튜토리얼 학습 기록 판독 실패 — 처음 상태로 엽니다: {error}"
                ));
                json!({})
            }
        }
    }

    pub fn save_progress(
        &self,
        value: &Value,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        if !value.is_object() || value.get("version") != Some(&json!(1)) {
            return Err("학습 기록 형식이 올바르지 않습니다.".into());
        }
        fs::create_dir_all(&self.root)?;
        write_bytes_atomic(
            &self.root.join("progress.json"),
            serde_json::to_string_pretty(value)?.as_bytes(),
        )?;
        Ok(())
    }

    pub fn load_entry_visible(&self) -> bool {
        match fs::read_to_string(self.root.join("entry.json")) {
            Ok(raw) => match serde_json::from_str::<Value>(&raw) {
                Ok(value) => {
                    if let Some(visible) = value.get("visible").and_then(Value::as_bool) {
                        visible
                    } else {
                        (self.alert)(format!(
                            "튜토리얼 버튼 표시 설정 판독 실패 — 표시로 엽니다: {value}"
                        ));
                        true
                    }
                }
                Err(error) => {
                    (self.alert)(format!(
                        "튜토리얼 버튼 표시 설정 판독 실패 — 표시로 엽니다: {error}"
                    ));
                    true
                }
            },
            Err(error) if error.kind() == io::ErrorKind::NotFound => true,
            Err(error) => {
                (self.alert)(format!(
                    "튜토리얼 버튼 표시 설정 판독 실패 — 표시로 엽니다: {error}"
                ));
                true
            }
        }
    }

    pub fn save_entry_visible(&self, visible: bool) -> io::Result<()> {
        fs::create_dir_all(&self.root)?;
        write_bytes_atomic(
            &self.root.join("entry.json"),
            serde_json::to_string(&json!({"visible": visible}))
                .expect("boolean JSON")
                .as_bytes(),
        )
    }

    pub fn seed_originals(&self, lesson_id: &str) -> io::Result<SeededLesson> {
        self.seed(lesson_id, "", "")
    }

    /// Confirms `lesson_id`, the derived-data shape, and that every bundled original
    /// asset is still present, before `seed` reserves a home and starts copying.
    fn validate_seed_request(
        &self,
        lesson_id: &str,
        derived: &str,
        derived_name: &str,
    ) -> io::Result<()> {
        if crate::tutorial_lessons::lesson(lesson_id).is_none() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "unknown lesson",
            ));
        }
        if !matches!(derived, "" | "blank" | "replacement")
            || derived.is_empty() != derived_name.is_empty()
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "알 수 없는 연습 데이터 종류입니다.",
            ));
        }
        if !derived.is_empty()
            && (Path::new(derived_name)
                .file_name()
                .and_then(|value| value.to_str())
                != Some(derived_name)
                || !derived_name.ends_with(".xlsx")
                || derived_name == DATA_NAME)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "연습 데이터 이름을 확인할 수 없습니다.",
            ));
        }
        let missing: Vec<_> = ORIGINALS
            .iter()
            .filter(|name| !self.assets.join(name).is_file())
            .copied()
            .collect();
        if !missing.is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                format!("동봉 예제를 찾을 수 없습니다: {}", missing.join(", ")),
            ));
        }
        Ok(())
    }
    /// Retries a fresh random batch id until an unused lesson-home directory is
    /// reserved, or gives up after 8 collisions.
    fn reserve_lesson_home(lesson_root: &Path) -> io::Result<(String, PathBuf)> {
        (0..8)
            .find_map(|_| {
                let batch = Uuid::new_v4().simple().to_string()[..10].to_owned();
                match reserve_home(lesson_root, &batch) {
                    Ok(home) => Some(Ok((batch, home))),
                    Err(error) if error.kind() == io::ErrorKind::AlreadyExists => None,
                    Err(error) => Some(Err(error)),
                }
            })
            .unwrap_or_else(|| {
                Err(io::Error::new(
                    io::ErrorKind::AlreadyExists,
                    "연습 회차 홈을 만들 수 없습니다.",
                ))
            })
    }
    pub fn seed(
        &self,
        lesson_id: &str,
        derived: &str,
        derived_name: &str,
    ) -> io::Result<SeededLesson> {
        self.validate_seed_request(lesson_id, derived, derived_name)?;
        let lesson_root = self.root.join("lessons").join(lesson_id);
        fs::create_dir_all(&lesson_root)?;
        let (batch, home) = Self::reserve_lesson_home(&lesson_root)?;
        let placed: io::Result<Vec<PracticeEntry>> = ORIGINALS
            .iter()
            .map(|name| self.place(&home, name, name, &batch))
            .collect();
        let built = placed.and_then(|assets| {
            let extra = if derived.is_empty() {
                None
            } else {
                let mut entry = self.place(&home, DATA_NAME, derived_name, &batch)?;
                if derived == "blank" {
                    blank_deposit_cells(Path::new(&entry.path))?;
                    entry.sha256 = fingerprint(Path::new(&entry.path))?;
                }
                entry.derived = Some(derived.to_owned());
                Some(entry)
            };
            Ok((assets, extra))
        });
        let (assets, derived_entry) = match built {
            Ok(built) => built,
            Err(error) => {
                let _ = fs::remove_dir_all(&home);
                return Err(error);
            }
        };
        Ok(SeededLesson {
            home,
            batch,
            assets,
            derived_entry,
        })
    }

    fn place(
        &self,
        home: &Path,
        name: &str,
        target: &str,
        batch: &str,
    ) -> io::Result<PracticeEntry> {
        let folder = home.join(if name.ends_with(".xlsx") {
            "data"
        } else {
            "templates"
        });
        fs::create_dir_all(&folder)?;
        let path = folder.join(target);
        let mut reader = fs::File::open(self.assets.join(name))?;
        let mut writer = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        io::copy(&mut reader, &mut writer)?;
        let sha256 = fingerprint(&path)?;
        Ok(PracticeEntry {
            name: name.to_owned(),
            path: path.to_string_lossy().into_owned(),
            sha256,
            batch: batch.to_owned(),
            derived: None,
        })
    }

    pub fn validate(&self, entry: &PracticeEntry, home: &Path) -> (bool, &'static str) {
        if !ORIGINALS.contains(&entry.name.as_str()) {
            return (false, "연습 파일 경로를 확인할 수 없습니다.");
        }
        let path = Path::new(&entry.path);
        if fs::symlink_metadata(path).is_ok_and(|meta| meta.file_type().is_symlink()) {
            return (false, "연습 파일 경로를 확인할 수 없습니다.");
        }
        let folder = home.join(if entry.name.ends_with(".xlsx") {
            "data"
        } else {
            "templates"
        });
        let (Ok(actual), Ok(expected)) = (path.canonicalize(), folder.canonicalize()) else {
            return (false, MISSING);
        };
        if actual.parent() != Some(expected.as_path()) {
            return (false, "연습 파일이 다른 위치를 가리킵니다.");
        }
        match fingerprint(path) {
            Ok(digest) if digest == entry.sha256 => (true, ""),
            Ok(_) => (false, MODIFIED_REASON),
            Err(_) => (false, MISSING),
        }
    }

    pub fn is_lesson_home(&self, lesson_id: &str, home: &Path) -> bool {
        if crate::tutorial_lessons::lesson(lesson_id).is_none() {
            return false;
        }
        let expected = self.root.join("lessons").join(lesson_id);
        match (
            home.canonicalize(),
            expected.canonicalize(),
            self.root.canonicalize(),
        ) {
            (Ok(home), Ok(expected), Ok(root)) => {
                expected.starts_with(root) && home.parent() == Some(expected.as_path())
            }
            _ => false,
        }
    }

    pub fn sweep(&self, lesson_id: &str, keep: &Path) {
        if !self.is_lesson_home(lesson_id, keep) {
            return;
        }
        let lessons = self.root.join("lessons").join(lesson_id);
        let Ok(keep) = keep.canonicalize() else {
            return;
        };
        let Ok(children) = fs::read_dir(&lessons) else {
            return;
        };
        for child in children.flatten() {
            let path = child.path();
            let batch = child.file_name().to_string_lossy().into_owned();
            if batch.len() != 10 || !batch.bytes().all(|byte| byte.is_ascii_hexdigit()) {
                continue;
            }
            let Ok(meta) = fs::symlink_metadata(&path) else {
                continue;
            };
            if !meta.is_dir() || meta.file_type().is_symlink() {
                continue;
            }
            if path.canonicalize().ok().as_deref() != Some(keep.as_path()) {
                let _ = fs::remove_dir_all(path);
            }
        }
    }
}

fn reserve_home(lesson_root: &Path, batch: &str) -> io::Result<PathBuf> {
    let home = lesson_root.join(batch);
    fs::create_dir(&home)?;
    Ok(home)
}

/// The bundled workbook has a fixed 계약 sheet. Remove that column's six data cells
/// while retaining every other worksheet entry and refusing a changed source layout.
fn blank_deposit_cells(path: &Path) -> io::Result<()> {
    let source = fs::read(path)?;
    let mut archive = ZipArchive::new(Cursor::new(&source)).map_err(io::Error::other)?;
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    let mut found_sheet = false;
    for index in 0..archive.len() {
        let mut entry = archive.by_index(index).map_err(io::Error::other)?;
        let name = entry.name().map_err(io::Error::other)?.into_owned();
        if entry.is_dir() {
            writer
                .add_directory(name, SimpleFileOptions::default())
                .map_err(io::Error::other)?;
            continue;
        }
        let mut bytes = Vec::new();
        entry.read_to_end(&mut bytes)?;
        if name == "xl/worksheets/sheet2.xml" {
            found_sheet = true;
            let mut xml = String::from_utf8(bytes).map_err(io::Error::other)?;
            if !xml.contains("r=\"K1\"") {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "연습 데이터 구조를 확인할 수 없습니다.",
                ));
            }
            for row in 2..=7 {
                let marker = format!("<c r=\"K{row}\"");
                let start = xml.find(&marker).ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        "연습 데이터 구조를 확인할 수 없습니다.",
                    )
                })?;
                let end = xml[start..].find("</c>").ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        "연습 데이터 구조를 확인할 수 없습니다.",
                    )
                })? + start
                    + 4;
                let style = xml[start..end]
                    .split_once(" s=\"")
                    .and_then(|(_, rest)| rest.split_once('"'))
                    .map(|(style, _)| style.to_owned())
                    .ok_or_else(|| {
                        io::Error::new(
                            io::ErrorKind::InvalidData,
                            "연습 데이터 셀 서식을 확인할 수 없습니다.",
                        )
                    })?;
                xml.replace_range(
                    start..end,
                    &format!("<c r=\"K{row}\" s=\"{style}\" t=\"n\"></c>"),
                );
            }
            bytes = xml.into_bytes();
        }
        writer
            .start_file(
                name,
                SimpleFileOptions::default().compression_method(entry.compression()),
            )
            .map_err(io::Error::other)?;
        writer.write_all(&bytes)?;
    }
    if !found_sheet {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "연습 데이터 구조를 확인할 수 없습니다.",
        ));
    }
    let complete = writer.finish().map_err(io::Error::other)?.into_inner();
    write_bytes_atomic(path, &complete)
}

pub(crate) fn fingerprint(path: &Path) -> io::Result<String> {
    let mut reader = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut block = vec![0u8; 64 * 1024];
    loop {
        let count = reader.read(&mut block)?;
        if count == 0 {
            break;
        }
        hasher.update(&block[..count]);
    }
    Ok(hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{ORIGINALS, TutorialWorkspace, reserve_home};
    use hwpx_filler::data_excel::ExcelDataSource;
    use hwpx_filler::data_source::DataSource;
    use serde_json::json;
    use std::fs;
    use std::io::Read;
    use std::path::Path;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use uuid::Uuid;

    #[test]
    fn seeded_files_are_isolated_and_modified_files_are_not_swept_as_current() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/tutorial-workspace")
            .join(Uuid::new_v4().to_string());
        let alerts = Arc::new(AtomicUsize::new(0));
        let observed = alerts.clone();
        let store = TutorialWorkspace::new(
            root.clone(),
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/tutorial"),
            move |_| {
                observed.fetch_add(1, Ordering::SeqCst);
            },
        );
        assert!(TutorialWorkspace::first_launch_candidate(&root));
        store
            .save_progress(&json!({"version": 1, "records": {}}))
            .unwrap();
        store.save_entry_visible(false).unwrap();
        assert_eq!(store.load_progress()["version"], 1);
        assert!(!store.load_entry_visible());
        for damaged in [
            "{",
            r#"{"visible":"no"}"#,
            r#"{"visible":0}"#,
            "{}",
            "false",
        ] {
            fs::write(root.join("entry.json"), damaged).unwrap();
            let before = alerts.load(Ordering::SeqCst);
            assert!(store.load_entry_visible());
            assert_eq!(alerts.load(Ordering::SeqCst), before + 1);
        }
        let missing_assets =
            TutorialWorkspace::new(root.join("missing-run"), root.join("absent-assets"), |_| {});
        assert!(missing_assets.seed_originals("first_hwpx").is_err());
        assert!(!missing_assets.root.join("lessons").exists());
        let occupied = root.join("lessons/first_hwpx/occupied");
        fs::create_dir_all(&occupied).unwrap();
        fs::write(occupied.join("keep.txt"), b"user bytes").unwrap();
        assert!(reserve_home(occupied.parent().unwrap(), "occupied").is_err());
        assert_eq!(fs::read(occupied.join("keep.txt")).unwrap(), b"user bytes");
        let first = store.seed_originals("first_hwpx").unwrap();
        assert_eq!(first.assets.len(), ORIGINALS.len());
        assert!(
            first
                .assets
                .iter()
                .all(|entry| store.validate(entry, &first.home).0)
        );
        let mut wrong = first.assets[0].clone();
        wrong.name = "unknown.hwpx".into();
        assert!(!store.validate(&wrong, &first.home).0);
        wrong = first.assets[0].clone();
        wrong.path = occupied.join("keep.txt").to_string_lossy().into_owned();
        assert!(!store.validate(&wrong, &first.home).0);
        wrong.path = first
            .home
            .join("templates/missing.hwpx")
            .to_string_lossy()
            .into_owned();
        assert!(!store.validate(&wrong, &first.home).0);
        let second = store.seed_originals("first_hwpx").unwrap();
        let blank = store
            .seed("blank_values", "blank", "공고목록(빈 칸).xlsx")
            .unwrap();
        let derived = blank.derived_entry.as_ref().unwrap();
        assert!(store.validate(derived, &blank.home).0);
        let mut workbook =
            zip::ZipArchive::new(std::fs::File::open(&derived.path).unwrap()).unwrap();
        let mut sheet = String::new();
        workbook
            .by_name("xl/worksheets/sheet2.xml")
            .unwrap()
            .read_to_string(&mut sheet)
            .unwrap();
        assert!(sheet.contains("r=\"K1\""));
        assert!(sheet.contains("<c r=\"K2\" s=\"2\" t=\"n\"></c>"));
        assert!(!sheet.contains("4,818,039"));
        let records = ExcelDataSource::new(&derived.path, Some("계약".into()), 1)
            .unwrap()
            .records()
            .unwrap();
        assert!(!records.is_empty());
        assert!(records.iter().all(|row| row["계약보증금"].is_empty()));
        store.sweep("first_hwpx", &second.home);
        assert!(!first.home.exists());
        assert_eq!(fs::read(occupied.join("keep.txt")).unwrap(), b"user bytes");
        store.sweep("../..", &second.home);
        assert!(second.home.exists());
        let changed = &second.assets[0];
        fs::write(&changed.path, b"changed").unwrap();
        assert!(!store.validate(changed, &second.home).0);
        fs::remove_dir_all(root).unwrap();
    }
}
