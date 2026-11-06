//! Same-directory complete-write then atomic replace, with a no-clobber variant.

use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

fn temp_path(path: &Path) -> io::Result<(std::path::PathBuf, fs::File)> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    for _ in 0..10 {
        let nonce = NEXT_TEMP.fetch_add(1, Ordering::Relaxed);
        let temp = parent.join(format!(".hwpx-{}-{nonce}.tmp", std::process::id()));
        match OpenOptions::new().write(true).create_new(true).open(&temp) {
            Ok(file) => return Ok((temp, file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "atomic temporary names exhausted",
    ))
}

fn write(path: &Path, bytes: &[u8], exclusive: bool) -> io::Result<()> {
    stage_then_publish(
        path,
        |file| file.write_all(bytes),
        |temp, target| {
            if exclusive {
                move_exclusive(temp, target)
            } else {
                fs::rename(temp, target)
            }
        },
    )
}

fn stage_then_publish(
    path: &Path,
    fill: impl FnOnce(&mut fs::File) -> io::Result<()>,
    publish: impl FnOnce(&Path, &Path) -> io::Result<()>,
) -> io::Result<()> {
    let (temp, mut file) = temp_path(path)?;
    let written = fill(&mut file);
    drop(file);
    let result = written.and_then(|_| publish(&temp, path));
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

pub fn write_bytes_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    write(path, bytes, false)
}

pub fn write_bytes_atomic_exclusive(path: &Path, bytes: &[u8]) -> io::Result<()> {
    write(path, bytes, true)
}

#[cfg(windows)]
pub(crate) fn move_exclusive(source: &Path, target: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::MoveFileExW;
    let wide = |path: &Path| -> io::Result<Vec<u16>> {
        // Canonicalize the existing parent, not the leaf: a target need not exist,
        // and moving a symlink must move the link rather than its referent. Windows
        // returns a verbatim absolute parent so Win32 accepts paths beyond MAX_PATH.
        let parent = path
            .parent()
            .filter(|part| !part.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let leaf = path.file_name().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "atomic path has no file name")
        })?;
        let native = fs::canonicalize(parent)?.join(leaf);
        let mut units: Vec<u16> = native.as_os_str().encode_wide().collect();
        if units.contains(&0) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "atomic path contains NUL",
            ));
        }
        units.push(0);
        Ok(units)
    };
    let source = wide(source)?;
    let target = wide(target)?;
    // No MOVEFILE_REPLACE_EXISTING flag: an intervening target creation refuses the write.
    if unsafe { MoveFileExW(source.as_ptr(), target.as_ptr(), 0) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(not(windows))]
pub(crate) fn move_exclusive(_source: &Path, _target: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "exclusive atomic write requires Windows",
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{write_bytes_atomic, write_bytes_atomic_exclusive};
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn replacement_and_exclusive_collision_preserve_prior_bytes() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-atomic-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        assert!(
            root.canonicalize().unwrap().starts_with(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../..")
                    .canonicalize()
                    .unwrap()
            )
        );
        let target = root.join("target.txt");
        write_bytes_atomic_exclusive(&target, b"first").unwrap();
        assert!(write_bytes_atomic_exclusive(&target, b"bad").is_err());
        assert_eq!(fs::read(&target).unwrap(), b"first");
        write_bytes_atomic(&target, b"second").unwrap();
        assert_eq!(fs::read(&target).unwrap(), b"second");
        assert_eq!(fs::read_dir(&root).unwrap().count(), 1);
        assert_failed_staging_and_publication(&root, &target);
        #[cfg(windows)]
        {
            let mut deep = root.clone();
            for index in 0..6 {
                deep.push(format!("long-branch-{index}-{}", "x".repeat(31)));
            }
            fs::create_dir_all(&deep).unwrap();
            let long_target = deep.join("candidate.json");
            assert!(long_target.to_string_lossy().len() > 260);
            write_bytes_atomic_exclusive(&long_target, b"candidate").unwrap();
            assert!(write_bytes_atomic_exclusive(&long_target, b"collision").is_err());
            assert_eq!(fs::read(&long_target).unwrap(), b"candidate");
            write_bytes_atomic(&long_target, b"replacement").unwrap();
            assert_eq!(fs::read(&long_target).unwrap(), b"replacement");
        }
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_failed_staging_and_publication(root: &Path, target: &Path) {
        use std::io::{self, Write};
        let original = "기존 durable 내용".as_bytes();
        write_bytes_atomic(target, original).unwrap();
        let error = super::stage_then_publish(
            target,
            |file| {
                file.write_all(b"partial")?;
                Err(io::Error::other("disk full"))
            },
            |_, _| panic!("failed writes must never be published"),
        )
        .unwrap_err();
        assert_eq!(error.to_string(), "disk full");
        assert_eq!(fs::read(target).unwrap(), original);
        assert_eq!(fs::read_dir(root).unwrap().count(), 1);
        for destination in [target.to_path_buf(), root.join("absent.txt")] {
            let error = super::stage_then_publish(
                &destination,
                |file| file.write_all(b"complete"),
                |temp, to| {
                    assert_eq!(to, destination);
                    assert_eq!(fs::read(temp).unwrap(), b"complete");
                    Err(io::Error::other("publish failed"))
                },
            )
            .unwrap_err();
            assert_eq!(error.to_string(), "publish failed");
            assert_eq!(fs::read(target).unwrap(), original);
            assert!(!root.join("absent.txt").exists());
            assert_eq!(fs::read_dir(root).unwrap().count(), 1);
        }
        write_bytes_atomic(target, "새 내용\0\u{1}PK".as_bytes()).unwrap();
        assert_eq!(fs::read(target).unwrap(), "새 내용\0\u{1}PK".as_bytes());
        assert_eq!(fs::read_dir(root).unwrap().count(), 1);
    }
}
