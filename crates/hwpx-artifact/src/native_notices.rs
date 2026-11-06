use super::*;

pub const REQUIRED_NOTICE_FILES: &[&str] = &[
    "LICENSE",
    "THIRD_PARTY_NOTICES",
    "licenses/rhwp/LICENSE.txt",
    "licenses/rhwp/THIRD_PARTY_LICENSES.txt",
    "licenses/rhwp/FONTS.txt",
    "licenses/rhwp/SourceHanSerifK-OFL.txt",
    "licenses/rhwp/canvaskit-wasm-LICENSE.txt",
    "licenses/pretendard/OFL.txt",
    "licenses/microsoft/WebView2-SDK-LICENSE.txt",
    "native-notices.json",
];

fn expected_native_notices(bundle: &Path) -> Result<BTreeMap<String, String>> {
    let manifest = json_object(&bundle.join("native-notices.json"), "native notices")?;
    if manifest.get("schema_version").and_then(Value::as_u64) != Some(1) {
        return Err(fail("native notices schema is invalid"));
    }
    let files = manifest
        .get("files")
        .and_then(Value::as_array)
        .filter(|files| !files.is_empty())
        .ok_or_else(|| fail("native notices file list is missing"))?;
    let mut expected = BTreeMap::new();
    for entry in files {
        let object = entry
            .as_object()
            .ok_or_else(|| fail("native notice record is invalid"))?;
        let path = object
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(|| fail("native notice path is invalid"))?;
        validate_relative_path(path, "native notice")?;
        if path != "THIRD_PARTY_NOTICES"
            && !["licenses/rust/", "licenses/npm/", "licenses/microsoft/"]
                .iter()
                .any(|prefix| path.starts_with(prefix))
        {
            return Err(fail(format!(
                "native notice path is outside closure: {path}"
            )));
        }
        let sha = object
            .get("sha256")
            .and_then(Value::as_str)
            .filter(|sha| sha.len() == 64 && sha.bytes().all(|byte| byte.is_ascii_hexdigit()))
            .ok_or_else(|| fail(format!("native notice digest is invalid: {path}")))?;
        if expected.insert(path.to_owned(), sha.to_owned()).is_some() {
            return Err(fail(format!("native notice is duplicated: {path}")));
        }
    }
    Ok(expected)
}

fn actual_native_notices(bundle: &Path) -> Result<BTreeMap<String, String>> {
    let mut records = vec![file_record(
        &bundle.join("THIRD_PARTY_NOTICES"),
        bundle,
        "native notice",
    )?];
    for directory in ["licenses/rust", "licenses/npm", "licenses/microsoft"] {
        let root = bundle.join(directory);
        let metadata = fs::symlink_metadata(&root).map_err(|_| {
            fail(format!(
                "native notice directory missing: {}",
                root.display()
            ))
        })?;
        if is_link(&metadata) || !metadata.is_dir() {
            return Err(fail(format!(
                "native notice directory is unsafe: {}",
                root.display()
            )));
        }
        records.extend(tree_records(&root, bundle, "native notice", &[])?);
    }
    Ok(records
        .into_iter()
        .map(|record| (record.path, record.sha256))
        .collect())
}

pub fn verify_notice_files(bundle: &Path) -> Result<()> {
    let missing = REQUIRED_NOTICE_FILES
        .iter()
        .copied()
        .filter(|name| !bundle.join(name).is_file())
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(fail(format!(
            "bundle is missing required notice files: {}",
            missing.join(", ")
        )));
    }
    if expected_native_notices(bundle)? != actual_native_notices(bundle)? {
        return Err(fail(
            "native notice file closure or digest differs from manifest",
        ));
    }
    Ok(())
}
