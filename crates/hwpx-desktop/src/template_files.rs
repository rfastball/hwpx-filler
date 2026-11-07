//! Filesystem import boundary for the user-selected template library.

use crate::atomic_file::{move_exclusive, write_bytes_atomic_exclusive};
use crate::directory_lock::DirectoryLock;
use hwpx_filler::copy_name::{first_free, numbered_file_name};
use std::fs::{self, FileTimes, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use uuid::Uuid;

pub struct TemplateFileStore {
    root: Arc<dyn Fn() -> PathBuf + Send + Sync>,
}
impl TemplateFileStore {
    pub fn new(root: impl Fn() -> PathBuf + Send + Sync + 'static) -> Self {
        Self {
            root: Arc::new(root),
        }
    }
    pub fn root(&self) -> PathBuf {
        (self.root)()
    }
    fn media_root(&self, suffix_or_media: &str) -> io::Result<PathBuf> {
        if matches!(suffix_or_media, ".hwpx" | "hwpx" | ".txt" | "txt") {
            Ok(self.root())
        } else {
            Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "가져올 수 있는 형식은 .hwpx 또는 .txt 입니다.",
            ))
        }
    }
    fn destination(root: &Path, name: &str) -> PathBuf {
        root.join(first_free(
            |number| numbered_file_name(name, number),
            |candidate| root.join(candidate).exists(),
        ))
    }
    fn valid_name(name: &str) -> io::Result<&str> {
        if Path::new(name).file_name().and_then(|part| part.to_str()) != Some(name)
            || name.chars().any(|letter| "\\/:*?\"<>|\0".contains(letter))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "unsafe template filename",
            ));
        }
        Ok(name)
    }
    pub fn copy_into_library(&self, source: &Path) -> io::Result<PathBuf> {
        let suffix = source
            .extension()
            .and_then(|part| part.to_str())
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "가져올 수 있는 형식은 .hwpx 또는 .txt 입니다.",
                )
            })?
            .to_ascii_lowercase();
        let root = self.media_root(&suffix)?;
        let name = source
            .file_name()
            .and_then(|part| part.to_str())
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "template filename is not Unicode",
                )
            })?;
        Self::valid_name(name)?;
        let lock = DirectoryLock::new(&root)?;
        lock.with(|| {
            fs::create_dir_all(&root)?;
            let target = Self::destination(&root, name);
            copy_exclusive(source, &target)?;
            Ok(target)
        })
    }
    pub fn add_bytes(&self, name: &str, bytes: &[u8]) -> io::Result<PathBuf> {
        let name = Self::valid_name(name)?;
        let suffix = Path::new(name)
            .extension()
            .and_then(|part| part.to_str())
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "가져올 수 있는 형식은 .hwpx 또는 .txt 입니다.",
                )
            })?
            .to_ascii_lowercase();
        let root = self.media_root(&suffix)?;
        let lock = DirectoryLock::new(&root)?;
        lock.with(|| {
            fs::create_dir_all(&root)?;
            let target = Self::destination(&root, name);
            write_bytes_atomic_exclusive(&target, bytes)?;
            Ok(target)
        })
    }
    pub fn source_file_exists(path: &Path) -> bool {
        path.is_file()
    }
    pub fn remove(&self, media: &str, path: &Path) -> io::Result<()> {
        let root = self.media_root(media)?;
        if path.parent() != Some(root.as_path()) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "template path is outside library",
            ));
        }
        let lock = DirectoryLock::new(&root)?;
        lock.with(|| fs::remove_file(path))
    }
}

fn copy_exclusive(source: &Path, target: &Path) -> io::Result<()> {
    let parent = target.parent().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "template target has no parent")
    })?;
    let temporary = parent.join(format!(".hwpx-import-{}.tmp", Uuid::new_v4().simple()));
    let mut owned = false;
    let result = (|| {
        let mut input = fs::File::open(source)?;
        let metadata = input.metadata()?;
        let mut output = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        owned = true;
        io::copy(&mut input, &mut output)?;
        output.flush()?;
        let mut times = FileTimes::new();
        if let Ok(accessed) = metadata.accessed() {
            times = times.set_accessed(accessed);
        }
        if let Ok(modified) = metadata.modified() {
            times = times.set_modified(modified);
        }
        output.set_times(times)?;
        drop(output);
        fs::set_permissions(&temporary, metadata.permissions())?;
        move_exclusive(&temporary, target)
    })();
    if let Err(error) = result {
        if owned && let Err(cleanup) = remove_owned_temporary(&temporary) {
            return Err(io::Error::other(format!(
                "{error}; 임시 파일 정리 실패: {cleanup}"
            )));
        }
        return Err(error);
    }
    Ok(())
}

fn remove_owned_temporary(path: &Path) -> io::Result<()> {
    let metadata = match fs::metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    if metadata.permissions().readonly() {
        make_writable(path, &metadata)?;
    }
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

#[cfg_attr(windows, allow(clippy::permissions_set_readonly_false))]
fn make_writable(path: &Path, metadata: &fs::Metadata) -> io::Result<()> {
    let mut permissions = metadata.permissions();
    #[cfg(windows)]
    permissions.set_readonly(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        permissions.set_mode(permissions.mode() | 0o200);
    }
    fs::set_permissions(path, permissions)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{TemplateFileStore, copy_exclusive, make_writable};
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn template_import_uses_shared_root_and_never_replaces_a_prior_name() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-template-files-{}-{stamp}",
            std::process::id()
        ));
        let root = sandbox.join("library");
        let source = sandbox.join("공고서.hwpx");
        fs::create_dir_all(&sandbox).unwrap();
        fs::write(&source, b"source").unwrap();
        assert!(TemplateFileStore::source_file_exists(&source));
        assert!(!TemplateFileStore::source_file_exists(&sandbox));
        assert!(!TemplateFileStore::source_file_exists(
            &sandbox.join("missing.hwpx")
        ));
        let store = TemplateFileStore::new({
            let root = root.clone();
            move || root.clone()
        });
        let first = store.add_bytes("공고서.hwpx", b"prior").unwrap();
        let second = store.copy_into_library(&source).unwrap();
        assert_eq!(second.file_name().unwrap(), "공고서 (2).hwpx");
        assert_eq!(fs::read(&first).unwrap(), b"prior");
        assert_eq!(fs::read(&second).unwrap(), b"source");
        let third = store.add_bytes("공고서.hwpx", b"package").unwrap();
        assert_eq!(third.file_name().unwrap(), "공고서 (3).hwpx");
        assert_eq!(fs::read(third).unwrap(), b"package");
        assert_eq!(fs::read(first).unwrap(), b"prior");
        assert_eq!(fs::read(&second).unwrap(), b"source");
        assert_eq!(
            fs::metadata(&source).unwrap().modified().unwrap(),
            fs::metadata(&second).unwrap().modified().unwrap()
        );
        assert!(store.add_bytes("../escape.hwpx", b"bad").is_err());
        assert!(store.add_bytes("bad.docx", b"bad").is_err());
        let txt = sandbox.join("협조전.TXT");
        fs::write(&txt, "원본").unwrap();
        let copied = store.copy_into_library(&txt).unwrap();
        assert_eq!(copied, root.join("협조전.TXT"));
        fs::write(&txt, "외부 수정").unwrap();
        let copied_again = store.copy_into_library(&txt).unwrap();
        assert_eq!(copied_again, root.join("협조전 (2).TXT"));
        assert_eq!(fs::read_to_string(&copied).unwrap(), "원본");
        assert_eq!(fs::read_to_string(&copied_again).unwrap(), "외부 수정");
        for name in ["x.pdf", "no-extension", "missing.hwpx"] {
            assert!(store.copy_into_library(&sandbox.join(name)).is_err());
            assert!(!root.join(name).exists());
        }
        let collision = root.join("collision.hwpx");
        fs::write(&collision, b"existing").unwrap();
        let mut permissions = fs::metadata(&source).unwrap().permissions();
        permissions.set_readonly(true);
        fs::set_permissions(&source, permissions).unwrap();
        assert!(copy_exclusive(&source, &collision).is_err());
        assert_eq!(fs::read(&collision).unwrap(), b"existing");
        assert_eq!(
            fs::read_dir(&root)
                .unwrap()
                .filter(|entry| {
                    entry
                        .as_ref()
                        .unwrap()
                        .file_name()
                        .to_string_lossy()
                        .starts_with(".hwpx-import-")
                })
                .count(),
            0
        );
        make_writable(&source, &fs::metadata(&source).unwrap()).unwrap();
        assert!(
            sandbox.canonicalize().unwrap().starts_with(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../..")
                    .canonicalize()
                    .unwrap()
            )
        );
        fs::remove_dir_all(sandbox).unwrap();
    }
}
