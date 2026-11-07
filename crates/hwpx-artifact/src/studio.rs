use super::*;

pub(super) fn regex(pattern: &str) -> Regex {
    Regex::new(pattern).expect("fixed seal pattern")
}

fn resolve_studio_reference(relative: &str, value: &str) -> Result<String> {
    let path = value
        .split('?')
        .next()
        .unwrap_or(value)
        .split('#')
        .next()
        .unwrap_or(value);
    if let Some(path) = path.strip_prefix("/rhwp/studio/") {
        return Ok(format!("rhwp/studio/{path}"));
    }
    if path.starts_with('/') || path.contains(':') || path.starts_with("//") {
        return Err(fail(format!(
            "rhwp Studio has non-local static resource: {relative} ({value})"
        )));
    }
    let mut parts: Vec<&str> = relative
        .rsplit_once('/')
        .map_or(Vec::new(), |(dir, _)| dir.split('/').collect());
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            _ => parts.push(part),
        }
    }
    Ok(parts.join("/"))
}

pub(super) fn studio_local_references(root: &Path, available: &BTreeSet<String>) -> Result<()> {
    let html = regex(r#"(?i)\b(?:src|href)\s*=\s*["']([^"']+)["']"#);
    let css = regex(r#"(?i)\burl\(\s*["']?([^"')]+)"#);
    for relative in available {
        let pattern = if relative.ends_with(".html") {
            &html
        } else if relative.ends_with(".css") {
            &css
        } else {
            continue;
        };
        let source = fs::read_to_string(root.join(relative)).map_err(|_| {
            fail(format!(
                "rhwp Studio static resource cannot be read: {relative}"
            ))
        })?;
        for capture in pattern.captures_iter(&source) {
            let value = capture.get(1).expect("one capture").as_str().trim();
            if value.is_empty()
                || value.starts_with('#')
                || value.starts_with("data:")
                || value.starts_with("blob:")
            {
                continue;
            }
            let resolved = resolve_studio_reference(relative, value)?;
            if !available.contains(&resolved) {
                return Err(fail(format!(
                    "rhwp Studio static resource is missing: {relative} ({value})"
                )));
            }
        }
    }
    Ok(())
}
pub(super) fn studio_output_closure(
    root: &Path,
    records: &[FileRecord],
) -> Result<BTreeSet<String>> {
    let manifest = json_object(&root.join(STUDIO_OUTPUT), "rhwp Studio manifest")?;
    if exact_keys(
        &manifest,
        &["schema", "source_commit", "files"],
        "rhwp Studio manifest",
    )
    .is_err()
        || manifest.get("schema").and_then(Value::as_i64) != Some(1)
    {
        return Err(fail("rhwp Studio manifest has invalid fields"));
    }
    if manifest.get("source_commit").and_then(Value::as_str) != Some(RHWP_COMMIT) {
        return Err(fail("rhwp Studio manifest has unexpected upstream commit"));
    }
    let files = manifest
        .get("files")
        .and_then(Value::as_array)
        .filter(|files| !files.is_empty())
        .ok_or_else(|| fail("rhwp Studio manifest has no files"))?;
    let mut expected = BTreeMap::new();
    let mut listed = Vec::new();
    for item in files {
        let (full, size, hash) = studio_manifest_entry(item)?;
        if expected.insert(full.clone(), (size, hash)).is_some() {
            return Err(fail("rhwp Studio manifest has invalid file entry"));
        }
        listed.push(full);
    }
    let mut sorted = listed.clone();
    sorted.sort();
    if listed != sorted || !expected.contains_key("rhwp/studio/index.html") {
        return Err(fail(
            "rhwp Studio manifest file list is incomplete or unsorted",
        ));
    }
    let actual: BTreeMap<_, _> = records
        .iter()
        .filter(|record| record.path.starts_with("rhwp/studio/"))
        .map(|record| (record.path.clone(), (record.size, record.sha256.clone())))
        .collect();
    if actual != expected {
        return Err(fail(
            "rhwp Studio output differs from pinned runtime manifest",
        ));
    }
    let available: BTreeSet<_> = expected
        .into_keys()
        .chain([STUDIO_OUTPUT.to_owned()])
        .collect();
    studio_local_references(root, &available)?;
    Ok(available)
}

fn studio_manifest_entry(item: &Value) -> Result<(String, u64, String)> {
    let item = item
        .as_object()
        .ok_or_else(|| fail("rhwp Studio manifest has invalid file entry"))?;
    if exact_keys(item, &["path", "size", "sha256"], "rhwp Studio manifest").is_err() {
        return Err(fail("rhwp Studio manifest has invalid file entry"));
    }
    let path = item
        .get("path")
        .and_then(Value::as_str)
        .ok_or_else(|| fail("rhwp Studio manifest has invalid path"))?;
    validate_relative_path(path, "rhwp Studio manifest")?;
    if !path.starts_with("studio/") || path.to_ascii_lowercase().ends_with(".map") {
        return Err(fail("rhwp Studio manifest has forbidden path"));
    }
    let size = item
        .get("size")
        .and_then(Value::as_u64)
        .ok_or_else(|| fail("rhwp Studio manifest has invalid file entry"))?;
    let hash = digest(
        item.get("sha256").expect("exact keys"),
        "rhwp Studio manifest sha256",
    )?;
    Ok((format!("rhwp/{path}"), size, hash))
}
pub(super) fn assert_studio_source_pin(source: &[FileRecord], output: &[FileRecord]) -> Result<()> {
    let a = find_record(source, STUDIO_SOURCE, "rhwp Studio source pin")?;
    let b = find_record(output, STUDIO_OUTPUT, "rhwp Studio output pin")?;
    if (a.size, &a.sha256) != (b.size, &b.sha256) {
        return Err(fail(
            "rhwp Studio output manifest differs from tracked source pin",
        ));
    }
    Ok(())
}

pub(super) fn validate_output_composition(
    records: &[FileRecord],
    studio_allowed: &BTreeSet<String>,
) -> Result<()> {
    let mut offenders = Vec::new();
    for record in records {
        let path = record.path.as_str();
        if matches!(path, "index.html" | VITE_MANIFEST_PATH) || studio_allowed.contains(path) {
            continue;
        }
        let (parent, filename) = path.rsplit_once('/').unwrap_or(("", path));
        let suffix = filename
            .rsplit_once('.')
            .map(|(_, suffix)| suffix.to_ascii_lowercase());
        if parent != "assets"
            || !suffix
                .as_deref()
                .is_some_and(|suffix| ASSET_SUFFIXES.contains(&suffix))
        {
            offenders.push(path);
        }
    }
    if !offenders.is_empty() {
        return Err(fail(format!(
            "web artifact ships a file outside the shipped-composition closure: {}",
            offenders.join(", ")
        )));
    }
    Ok(())
}
pub(super) fn validate_vite_manifest(path: &Path) -> Result<()> {
    if json_object(path, "Vite manifest")?.is_empty() {
        return Err(fail(format!("Vite manifest is empty: {}", path.display())));
    }
    Ok(())
}
pub(super) fn validate_output_references(root: &Path, records: &[FileRecord]) -> Result<()> {
    let vite_client = regex(r"(?i)(?:/@vite/client|@vite/client)");
    let absolute_assets = regex(r#"(?i)(?:["'`(=:\s]|url\(\s*)/assets(?:/|["'`)\s?#])"#);
    let file_url = regex(r"(?i)\bfile:(?://(?:/|[a-z0-9])|/[a-z0-9]|\\)");
    let external = regex(r#"(?i)\bhttps?://[^\s"'`<>()\\]*"#);
    for record in records {
        let suffix = record
            .path
            .rsplit_once('.')
            .map_or("", |(_, ext)| ext)
            .to_ascii_lowercase();
        if !TEXT_SUFFIXES.contains(&suffix.as_str()) {
            continue;
        }
        let text = fs::read_to_string(root.join(&record.path)).map_err(|_| {
            fail(format!(
                "text web artifact is not valid UTF-8: {}",
                record.path
            ))
        })?;
        for (label, pattern) in [
            ("Vite dev client", &vite_client),
            ("absolute /assets URL", &absolute_assets),
            ("file: URL", &file_url),
        ] {
            if pattern.is_match(&text) {
                return Err(fail(format!(
                    "forbidden {label} in web artifact: {}",
                    record.path
                )));
            }
        }
        for token in external.find_iter(&text).map(|found| found.as_str()) {
            let inert = suffix == "js"
                && (INERT_URLS.contains(&token)
                    || INERT_PREFIXES
                        .iter()
                        .any(|prefix| token.starts_with(prefix)));
            if !inert {
                return Err(fail(format!(
                    "forbidden external HTTP(S) resource in web artifact: {} ({token})",
                    record.path
                )));
            }
        }
    }
    Ok(())
}
