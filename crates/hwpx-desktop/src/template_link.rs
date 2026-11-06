//! Job template path/key reconciliation at the mutable library-root boundary.

use crate::single_instance::{normalize_windows_path, resolved_home};
use std::io;
use std::path::{Component, Path, PathBuf};

fn known_media(path: &Path) -> bool {
    path.extension().is_some_and(|extension| {
        extension.eq_ignore_ascii_case("hwpx") || extension.eq_ignore_ascii_case("txt")
    })
}

fn lexical_normal(path: &Path) -> PathBuf {
    let mut result = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => {
                if result.file_name().is_some_and(|name| name == "..")
                    || (!result.pop() && !path.is_absolute())
                {
                    result.push("..");
                }
            }
            Component::CurDir => {}
            other => result.push(other.as_os_str()),
        }
    }
    result
}

fn safe_key(key: &str) -> io::Result<()> {
    let path = Path::new(key);
    if path.is_absolute()
        || path.components().any(|part| {
            matches!(
                part,
                Component::Prefix(_) | Component::RootDir | Component::ParentDir
            )
        })
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "작업 필드 'template_key' 는 라이브러리 루트 상대경로여야 하는데 {key:?} 입니다"
            ),
        ));
    }
    Ok(())
}

/// A failed promotion remains an absolute stored path; basename matching is never attempted.
pub fn library_key_for(template_path: &Path, root: &Path) -> String {
    library_key_with_identity(template_path, root, |left, right| {
        normalize_windows_path(&resolved_home(left))
            .ok()
            .zip(normalize_windows_path(&resolved_home(right)).ok())
            .is_some_and(|(left, right)| left.to_lowercase() == right.to_lowercase())
    })
}

fn library_key_with_identity(
    template_path: &Path,
    root: &Path,
    same_identity: impl FnOnce(&Path, &Path) -> bool,
) -> String {
    if !known_media(template_path) {
        return String::new();
    }
    let root_normal = lexical_normal(root);
    let path_normal = lexical_normal(template_path);
    let root_parts: Vec<_> = root_normal.components().collect();
    let path_parts: Vec<_> = path_normal.components().collect();
    if path_parts.len() <= root_parts.len()
        || !root_parts.iter().zip(&path_parts).all(|(left, right)| {
            left.as_os_str()
                .to_str()
                .zip(right.as_os_str().to_str())
                .is_some_and(|(left, right)| left.to_lowercase() == right.to_lowercase())
        })
    {
        return String::new();
    }
    let relative: PathBuf = path_parts[root_parts.len()..]
        .iter()
        .map(|component| component.as_os_str())
        .collect();
    let Some(key) = relative.to_str().map(|path| path.replace('\\', "/")) else {
        return String::new();
    };
    if key.is_empty() || safe_key(&key).is_err() {
        return String::new();
    }
    if (path_normal != template_path || root_normal != root)
        && !same_identity(&root_normal.join(&relative), template_path)
    {
        return String::new();
    }
    key
}

pub fn resolve_library_key(key: &str, root: &Path) -> io::Result<Option<PathBuf>> {
    if key.is_empty() {
        return Ok(None);
    }
    safe_key(key)?;
    if !known_media(Path::new(key)) {
        return Ok(None);
    }
    Ok(Some(root.join(key)))
}

fn former_root_of(template_path: &Path, key: &str) -> Option<PathBuf> {
    if template_path.as_os_str().is_empty() || key.is_empty() {
        return None;
    }
    let normal = lexical_normal(template_path);
    let tail: Vec<_> = Path::new(key)
        .components()
        .map(|part| part.as_os_str().to_string_lossy().to_lowercase())
        .collect();
    let parts: Vec<_> = normal.components().collect();
    if tail.len() > parts.len() {
        return None;
    }
    if parts[parts.len() - tail.len()..]
        .iter()
        .map(|part| part.as_os_str().to_string_lossy().to_lowercase())
        .ne(tail.iter().cloned())
    {
        return None;
    }
    let mut root = normal;
    for _ in 0..tail.len() {
        root.pop();
    }
    Some(root)
}

pub fn resolve_template_link(
    stored_path: &Path,
    key: &str,
    root: &Path,
    authority_id: &str,
) -> io::Result<PathBuf> {
    if !authority_id.is_empty() || (!stored_path.as_os_str().is_empty() && stored_path.exists()) {
        return Ok(stored_path.to_path_buf());
    }
    let former_root = former_root_of(stored_path, key);
    if former_root.as_ref().is_none_or(|old| !old.is_dir())
        && let Some(resolved) = resolve_library_key(key, root)?
    {
        return Ok(resolved);
    }
    Ok(stored_path.to_path_buf())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        library_key_for, library_key_with_identity, resolve_library_key, resolve_template_link,
    };
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn live_absolute_and_missing_file_do_not_rebind_but_missing_root_can() {
        assert_eq!(
            library_key_for(Path::new("C:/ROOT/Sub/A.hwpx"), Path::new("c:/root")),
            "Sub/A.hwpx"
        );
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/hwpx-template-link-{}-{stamp}",
            std::process::id()
        ));
        let old = sandbox.join("old");
        let new = sandbox.join("new");
        fs::create_dir_all(old.join("sub")).unwrap();
        fs::create_dir_all(new.join("sub")).unwrap();
        let source = old.join("sub/a.hwpx");
        let decoy = new.join("sub/a.hwpx");
        fs::write(&source, b"old").unwrap();
        fs::write(&decoy, b"new").unwrap();
        let key = library_key_for(&source, &old);
        assert_eq!(key, "sub/a.hwpx");
        for (name, expected) in [
            ("조달/공고서.hwpx", "조달/공고서.hwpx"),
            ("안내문.TxT", "안내문.TxT"),
            ("a.docx", ""),
            ("", ""),
        ] {
            assert_eq!(library_key_for(&old.join(name), &old), expected);
        }
        assert_eq!(
            resolve_template_link(&source, &key, &new, "").unwrap(),
            source
        );
        fs::remove_file(&source).unwrap();
        assert_eq!(
            resolve_template_link(&source, &key, &new, "").unwrap(),
            source
        );
        assert_eq!(
            resolve_template_link(&source, &key, &new, "authority").unwrap(),
            source
        );
        fs::remove_dir_all(&old).unwrap();
        assert_eq!(
            resolve_template_link(&source, &key, &new, "authority").unwrap(),
            source
        );
        assert_eq!(
            resolve_template_link(&source, &key, &new, "").unwrap(),
            decoy
        );
        for invalid in [
            "C:/훔친/x.hwpx",
            "C:x.hwpx",
            "/x.hwpx",
            "../../x.hwpx",
            "조달/../../x.hwpx",
            r"\\srv\x.hwpx",
        ] {
            assert!(
                resolve_template_link(Path::new(""), invalid, &new, "").is_err(),
                "{invalid}"
            );
        }
        for unknown in ["", "조달/공고서.docx"] {
            assert_eq!(resolve_library_key(unknown, &new).unwrap(), None);
            assert_eq!(
                resolve_template_link(&source, unknown, &new, "").unwrap(),
                source
            );
        }
        assert_eq!(
            resolve_template_link(Path::new("stale.hwpx"), &key, &new, "").unwrap(),
            decoy
        );
        assert_eq!(
            resolve_library_key("missing.txt", &new).unwrap(),
            Some(new.join("missing.txt"))
        );
        assert_eq!(library_key_for(&sandbox.join("outside/a.hwpx"), &new), "");
        fs::remove_dir_all(sandbox).unwrap();
    }

    #[test]
    fn lexical_promotion_requires_the_same_file_and_cannot_escape_the_root() {
        let root = Path::new("C:/library");
        let noisy = root.join("조달/link/../공고서.hwpx");
        let expected = root.join("조달/공고서.hwpx");
        assert_eq!(library_key_for(&noisy, root), "조달/공고서.hwpx");
        assert_eq!(
            library_key_with_identity(&noisy, root, |candidate, original| {
                assert_eq!(candidate, expected);
                assert_eq!(original, noisy);
                false
            }),
            ""
        );
        assert_eq!(
            library_key_for(&expected, &root.join("sub/..")),
            "조달/공고서.hwpx"
        );
        for outside in ["../outside/a.hwpx", "sub/../../a.hwpx"] {
            assert_eq!(library_key_for(&root.join(outside), root), "");
        }
        assert_eq!(
            library_key_with_identity(&expected, root, |_, _| panic!(
                "unchanged paths need no identity probe"
            )),
            "조달/공고서.hwpx"
        );
    }
}
