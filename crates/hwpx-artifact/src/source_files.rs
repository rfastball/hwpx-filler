use super::*;

pub(super) fn read_bytes(path: &Path, role: &str) -> Result<Vec<u8>> {
    fs::read(path).map_err(|_| fail(format!("{role} cannot be read: {}", path.display())))
}
pub(super) fn json_object(path: &Path, role: &str) -> Result<serde_json::Map<String, Value>> {
    let bytes =
        fs::read(path).map_err(|_| fail(format!("{role} is invalid JSON: {}", path.display())))?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| fail(format!("{role} is invalid JSON: {}", path.display())))?;
    value
        .as_object()
        .cloned()
        .ok_or_else(|| fail(format!("{role} is not a JSON object: {}", path.display())))
}
pub(super) fn exact_keys(
    object: &serde_json::Map<String, Value>,
    keys: &[&str],
    role: &str,
) -> Result<()> {
    let actual: BTreeSet<_> = object.keys().map(String::as_str).collect();
    let expected: BTreeSet<_> = keys.iter().copied().collect();
    if actual != expected {
        Err(fail(format!(
            "web artifact seal has invalid fields: {role}"
        )))
    } else {
        Ok(())
    }
}
pub(super) fn digest(value: &Value, role: &str) -> Result<String> {
    let Some(text) = value.as_str() else {
        return Err(fail(format!(
            "web artifact seal has invalid digest: {role}"
        )));
    };
    if text.len() != 64
        || !text
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(fail(format!(
            "web artifact seal has invalid digest: {role}"
        )));
    }
    Ok(text.to_owned())
}
pub(super) fn validate_relative_path(value: &str, role: &str) -> Result<()> {
    let parts: Vec<_> = value.split('/').collect();
    if value.is_empty()
        || value.contains('\\')
        || value.starts_with('/')
        || parts
            .iter()
            .any(|part| part.is_empty() || *part == "." || *part == "..")
        || parts.first().is_some_and(|part| part.contains(':'))
    {
        return Err(fail(format!("{role} path is unsafe: {value:?}")));
    }
    Ok(())
}
pub(super) fn relative_path(path: &Path, root: &Path, role: &str) -> Result<String> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| fail(format!("{role} path is unsafe: {}", path.display())))?;
    let mut parts = Vec::new();
    for component in relative.components() {
        let text = component
            .as_os_str()
            .to_str()
            .ok_or_else(|| fail(format!("{role} path is not UTF-8: {}", path.display())))?;
        parts.push(text);
    }
    let name = parts.join("/");
    validate_relative_path(&name, role)?;
    Ok(name)
}
pub(super) fn is_link(metadata: &Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return true;
        }
    }
    false
}
pub(super) fn file_record(path: &Path, root: &Path, role: &str) -> Result<FileRecord> {
    let metadata = fs::symlink_metadata(path).map_err(|_| {
        fail(format!(
            "{role} file cannot be inspected: {}",
            path.display()
        ))
    })?;
    if is_link(&metadata) {
        return Err(fail(format!("{role} contains a link: {}", path.display())));
    }
    if !metadata.is_file() {
        return Err(fail(format!("{role} file missing: {}", path.display())));
    }
    Ok(FileRecord {
        path: relative_path(path, root, role)?,
        size: metadata.len(),
        sha256: sha256(&read_bytes(path, "web artifact file")?),
    })
}
pub(super) fn tree_records(
    root: &Path,
    base: &Path,
    role: &str,
    excluded: &[&str],
) -> Result<Vec<FileRecord>> {
    if !root.is_dir() {
        return Err(fail(format!(
            "{role} directory missing: {}",
            root.display()
        )));
    }
    let mut stack = vec![root.to_path_buf()];
    let mut records = Vec::new();
    while let Some(directory) = stack.pop() {
        let children = fs::read_dir(&directory).map_err(|_| {
            fail(format!(
                "{role} directory cannot be scanned: {}",
                directory.display()
            ))
        })?;
        for child in children {
            let child = child.map_err(|_| {
                fail(format!(
                    "{role} directory cannot be scanned: {}",
                    directory.display()
                ))
            })?;
            let path = child.path();
            let metadata = fs::symlink_metadata(&path).map_err(|_| {
                fail(format!(
                    "{role} file cannot be inspected: {}",
                    path.display()
                ))
            })?;
            if is_link(&metadata) {
                return Err(fail(format!("{role} contains a link: {}", path.display())));
            }
            if metadata.is_dir() {
                stack.push(path);
            } else if metadata.is_file()
                && !excluded.contains(&relative_path(&path, base, role)?.as_str())
            {
                records.push(file_record(&path, base, role)?);
            } else if !metadata.is_file() {
                return Err(fail(format!(
                    "{role} contains an unsupported file: {}",
                    path.display()
                )));
            }
        }
    }
    records.sort_by(|a, b| a.path.cmp(&b.path));
    if records.is_empty() {
        return Err(fail(format!(
            "{role} directory is empty: {}",
            root.display()
        )));
    }
    Ok(records)
}
pub(super) fn find_record<'a>(
    records: &'a [FileRecord],
    path: &str,
    role: &str,
) -> Result<&'a FileRecord> {
    let mut found = records.iter().filter(|record| record.path == path);
    let first = found
        .next()
        .ok_or_else(|| fail(format!("{role} record missing or duplicated: {path}")))?;
    if found.next().is_some() {
        return Err(fail(format!("{role} record missing or duplicated: {path}")));
    }
    Ok(first)
}

pub(super) fn source_records(repo: &Path) -> Result<Vec<FileRecord>> {
    let mut records = tree_records(&repo.join("frontend"), repo, "frontend source", &[])?;
    records.extend(tree_records(
        &repo.join("vendor/rhwp"),
        repo,
        "rhwp source",
        &[],
    )?);
    for relative in SOURCE_CONFIG {
        records.push(file_record(&repo.join(relative), repo, "web build input")?);
    }
    let paths: BTreeSet<_> = records.iter().map(|record| record.path.as_str()).collect();
    for expected in [
        "vendor/rhwp/source.json",
        "vendor/rhwp/patches/authoring.patch",
        STUDIO_SOURCE,
    ] {
        if !paths.contains(expected) {
            return Err(fail("rhwp pinned source or runtime manifest is missing"));
        }
    }
    let source_pin = json_object(&repo.join("vendor/rhwp/source.json"), "rhwp source pin")?;
    if source_pin.get("commit").and_then(Value::as_str) != Some(RHWP_COMMIT) {
        return Err(fail("rhwp source pin has unexpected upstream commit"));
    }
    records.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(records)
}
pub(super) fn output_records(root: &Path) -> Result<Vec<FileRecord>> {
    tree_records(root, root, "web artifact", &[SEAL_FILENAME])
}
