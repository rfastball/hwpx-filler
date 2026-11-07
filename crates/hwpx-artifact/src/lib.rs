//! The single producer and verifier for the shipped Vite web artifact seal.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

pub mod reconcile;
pub mod webview_retry;

mod native_notices;
mod source_files;
mod studio;
mod toolchain;

pub use native_notices::{REQUIRED_NOTICE_FILES, verify_notice_files};
use source_files::*;
use studio::*;
use toolchain::*;

use regex::Regex;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs::{self, Metadata};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

pub const SEAL_FILENAME: &str = "web-artifact-seal.json";
pub const VITE_MANIFEST_PATH: &str = ".vite/manifest.json";
const STUDIO_SOURCE: &str = "vendor/rhwp/studio-runtime.json";
const STUDIO_OUTPUT: &str = "rhwp/studio-runtime.json";
const RHWP_COMMIT: &str = "680111ec7bea2fe11110de18c3676ba5a1cf7847";
const SOURCE_CONFIG: &[&str] = &[
    ".node-version",
    ".npmrc",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.mjs",
    "scripts/build_rhwp.ps1",
];
const TEXT_SUFFIXES: &[&str] = &["cjs", "css", "htm", "html", "js", "json", "map", "mjs"];
const ASSET_SUFFIXES: &[&str] = &["css", "js", "svg", "woff2"];
const INERT_URLS: &[&str] = &[
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/XML/1998/namespace",
    "http://www.w3.org/1998/Math/MathML",
    "http://www.w3.org/TR/REC-html40",
    "https://code.haverbeke.berlin/marijn/style-mod#documentation",
    "https://developer.mozilla.org/en-US/docs/Web/CSS/direction",
    "https://developer.mozilla.org/en-US/docs/Web/CSS/white-space",
    "https://developer.mozilla.org/en-US/docs/Web/CSS/position#sticky",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/codePointAt",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/fromCodePoint",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/normalize",
    "https://en.wikipedia.org/wiki/Input_method",
    "https://en.wikipedia.org/wiki/Operational_transformation",
    "https://en.wikipedia.org/wiki/Tree_traversal#Pre-order,_NLR",
    "https://codemirror.net/docs/ref/#language.syntaxTree",
    "https://code.haverbeke.berlin/codemirror/dev/issues",
    "https://lezer.codemirror.net",
    "https://lezer.codemirror.net/",
    "https://lezer.codemirror.net/docs/ref#common.Input",
];
const INERT_PREFIXES: &[&str] = &[
    "https://react.dev/errors/",
    "https://codemirror.net/6/docs/ref/",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Violation(pub String);
impl fmt::Display for Violation {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Violation {}
type Result<T> = std::result::Result<T, Violation>;
fn fail(message: impl Into<String>) -> Violation {
    Violation(message.into())
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct FileRecord {
    pub path: String,
    pub size: u64,
    pub sha256: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Toolchain {
    pub node: String,
    pub npm: String,
    pub vite: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedArtifact {
    pub root: PathBuf,
    pub index_path: PathBuf,
    pub artifact_id: String,
    pub tree_sha256: String,
    pub source_commit: String,
}
impl VerifiedArtifact {
    /// Own the exact verified output bytes before a WebView can request them.
    /// File mutations after this returns cannot change what the host serves.
    pub fn snapshot_bytes(&self) -> Result<BTreeMap<String, Vec<u8>>> {
        let seal = load_seal(&self.root.join(SEAL_FILENAME))?;
        if seal.artifact_id != self.artifact_id {
            return Err(fail("web artifact identity changed before snapshot"));
        }
        verify_output_tree(&self.root, &seal)?;
        let mut files = BTreeMap::new();
        for record in &seal.output_files {
            let bytes = read_bytes(&self.root.join(&record.path), "web output")?;
            if bytes.len() as u64 != record.size || sha256(&bytes) != record.sha256 {
                return Err(fail(format!(
                    "web output changed during snapshot: {}",
                    record.path
                )));
            }
            files.insert(record.path.clone(), bytes);
        }
        verify_output_tree(&self.root, &seal)?;
        Ok(files)
    }
}
#[derive(Clone, Debug)]
struct Seal {
    artifact_id: String,
    source_commit: String,
    source_input_sha256: String,
    source_files: Vec<FileRecord>,
    package_lock: FileRecord,
    toolchain: Toolchain,
    vite_manifest: FileRecord,
    tree_sha256: String,
    output_files: Vec<FileRecord>,
}
impl Seal {
    fn core_document(&self) -> Value {
        json!({
            "schema": 1,
            "source": {"commit": self.source_commit, "input_sha256": self.source_input_sha256, "files": self.source_files},
            "package_lock": self.package_lock,
            "toolchain": self.toolchain,
            "vite_manifest": self.vite_manifest,
            "output": {"tree_sha256": self.tree_sha256, "files": self.output_files},
        })
    }
    fn document(&self) -> Value {
        let mut value = self.core_document();
        value
            .as_object_mut()
            .expect("seal object")
            .insert("artifact_id".into(), json!(self.artifact_id));
        value
    }
}

fn sha256(payload: &[u8]) -> String {
    use fmt::Write as _;
    let mut out = String::with_capacity(64);
    for byte in Sha256::digest(payload) {
        write!(&mut out, "{byte:02x}").expect("hex write");
    }
    out
}
fn sorted_value(value: &Value) -> Value {
    match value {
        Value::Array(items) => Value::Array(items.iter().map(sorted_value).collect()),
        Value::Object(object) => {
            let mut pairs: Vec<_> = object.iter().collect();
            pairs.sort_by(|left, right| left.0.cmp(right.0));
            let mut sorted = serde_json::Map::new();
            for (key, item) in pairs {
                sorted.insert(key.clone(), sorted_value(item));
            }
            Value::Object(sorted)
        }
        _ => value.clone(),
    }
}
fn canonical_sha256(value: &Value) -> Result<String> {
    serde_json::to_vec(&sorted_value(value))
        .map(|bytes| sha256(&bytes))
        .map_err(|err| fail(err.to_string()))
}
fn records_sha256(records: &[FileRecord]) -> Result<String> {
    canonical_sha256(&json!(records))
}
fn exact_semver(value: &Value, role: &str) -> Result<String> {
    let Some(text) = value.as_str() else {
        return Err(fail(format!("{role} must be an exact semantic version")));
    };
    let parts: Vec<_> = text.split('.').collect();
    if parts.len() != 3
        || parts
            .iter()
            .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
    {
        return Err(fail(format!("{role} must be an exact semantic version")));
    }
    Ok(text.to_owned())
}
fn declared_toolchain(repo: &Path) -> Result<Toolchain> {
    let node_pin = fs::read_to_string(repo.join(".node-version"))
        .map_err(|_| fail("Node pin cannot be read: .node-version"))?;
    let node = exact_semver(
        &json!(node_pin.trim().strip_prefix('v').unwrap_or(node_pin.trim())),
        ".node-version",
    )?;
    let package = json_object(&repo.join("package.json"), "package.json")?;
    let npm = package
        .get("packageManager")
        .and_then(Value::as_str)
        .and_then(|value| value.strip_prefix("npm@"))
        .ok_or_else(|| fail("package.json packageManager must pin npm exactly"))?;
    let npm = exact_semver(&json!(npm), "package.json packageManager")?;
    let vite = package
        .get("devDependencies")
        .and_then(Value::as_object)
        .ok_or_else(|| fail("package.json devDependencies is missing"))?
        .get("vite")
        .cloned()
        .unwrap_or(Value::Null);
    let vite = exact_semver(&vite, "package.json devDependencies.vite")?;
    let lock = json_object(&repo.join("package-lock.json"), "package-lock.json")?;
    let locked_vite = lock
        .get("packages")
        .and_then(Value::as_object)
        .and_then(|packages| packages.get(""))
        .and_then(Value::as_object)
        .and_then(|root| root.get("devDependencies"))
        .and_then(Value::as_object)
        .and_then(|deps| deps.get("vite"))
        .and_then(Value::as_str);
    if locked_vite != Some(vite.as_str()) {
        return Err(fail(
            "package-lock.json root devDependencies.vite does not match package.json",
        ));
    }
    Ok(Toolchain { node, npm, vite })
}

fn parse_record(value: &Value, role: &str) -> Result<FileRecord> {
    let object = value
        .as_object()
        .ok_or_else(|| fail(format!("web artifact seal has invalid file record: {role}")))?;
    exact_keys(object, &["path", "size", "sha256"], role)?;
    let path = object["path"]
        .as_str()
        .ok_or_else(|| fail(format!("web artifact seal has invalid path: {role}")))?;
    validate_relative_path(path, role)?;
    let size = object["size"]
        .as_u64()
        .ok_or_else(|| fail(format!("web artifact seal has invalid size: {role}")))?;
    Ok(FileRecord {
        path: path.to_owned(),
        size,
        sha256: digest(&object["sha256"], &format!("{role}.sha256"))?,
    })
}
fn parse_records(value: &Value, role: &str) -> Result<Vec<FileRecord>> {
    let items = value
        .as_array()
        .filter(|items| !items.is_empty())
        .ok_or_else(|| fail(format!("web artifact seal has invalid file list: {role}")))?;
    let records: Vec<_> = items
        .iter()
        .enumerate()
        .map(|(index, item)| parse_record(item, &format!("{role}[{index}]")))
        .collect::<Result<_>>()?;
    let paths: Vec<_> = records.iter().map(|record| record.path.as_str()).collect();
    if paths.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(fail(format!(
            "web artifact seal file list is not unique and sorted: {role}"
        )));
    }
    Ok(records)
}
fn load_seal(path: &Path) -> Result<Seal> {
    let document = json_object(path, "web artifact seal")?;
    exact_keys(
        &document,
        &[
            "schema",
            "artifact_id",
            "source",
            "package_lock",
            "toolchain",
            "vite_manifest",
            "output",
        ],
        "root",
    )?;
    if document["schema"].as_u64() != Some(1) {
        return Err(fail("unsupported web artifact seal schema"));
    }
    let source = document["source"]
        .as_object()
        .ok_or_else(|| fail("web artifact seal has invalid sections"))?;
    let toolchain = document["toolchain"]
        .as_object()
        .ok_or_else(|| fail("web artifact seal has invalid sections"))?;
    let output = document["output"]
        .as_object()
        .ok_or_else(|| fail("web artifact seal has invalid sections"))?;
    exact_keys(source, &["commit", "input_sha256", "files"], "source")?;
    exact_keys(toolchain, &["node", "npm", "vite"], "toolchain")?;
    exact_keys(output, &["tree_sha256", "files"], "output")?;
    let commit = source["commit"]
        .as_str()
        .filter(|s| {
            s.len() == 40
                && s.bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
        .ok_or_else(|| fail("web artifact seal has invalid source commit"))?;
    let seal = Seal {
        artifact_id: digest(&document["artifact_id"], "artifact_id")?,
        source_commit: commit.to_owned(),
        source_input_sha256: digest(&source["input_sha256"], "source.input_sha256")?,
        source_files: parse_records(&source["files"], "source.files")?,
        package_lock: parse_record(&document["package_lock"], "package_lock")?,
        toolchain: Toolchain {
            node: exact_semver(&toolchain["node"], "seal toolchain.node")?,
            npm: exact_semver(&toolchain["npm"], "seal toolchain.npm")?,
            vite: exact_semver(&toolchain["vite"], "seal toolchain.vite")?,
        },
        vite_manifest: parse_record(&document["vite_manifest"], "vite_manifest")?,
        tree_sha256: digest(&output["tree_sha256"], "output.tree_sha256")?,
        output_files: parse_records(&output["files"], "output.files")?,
    };
    if records_sha256(&seal.source_files)? != seal.source_input_sha256 {
        return Err(fail(
            "source input digest in web artifact seal is inconsistent",
        ));
    }
    if *find_record(
        &seal.source_files,
        "package-lock.json",
        "package-lock input",
    )? != seal.package_lock
    {
        return Err(fail(
            "package-lock digest in web artifact seal is inconsistent",
        ));
    }
    if records_sha256(&seal.output_files)? != seal.tree_sha256 {
        return Err(fail(
            "output tree digest in web artifact seal is inconsistent",
        ));
    }
    if *find_record(&seal.output_files, VITE_MANIFEST_PATH, "Vite manifest")? != seal.vite_manifest
    {
        return Err(fail(
            "Vite manifest digest in web artifact seal is inconsistent",
        ));
    }
    if canonical_sha256(&seal.core_document())? != seal.artifact_id {
        return Err(fail("web artifact ID mismatch"));
    }
    Ok(seal)
}

fn seal_candidates(root: &Path) -> Result<Vec<PathBuf>> {
    let mut stack = vec![root.to_path_buf()];
    let mut found = Vec::new();
    while let Some(dir) = stack.pop() {
        let entries = fs::read_dir(&dir).map_err(|_| {
            fail(format!(
                "web artifact directory cannot be scanned: {}",
                root.display()
            ))
        })?;
        for entry in entries {
            let entry = entry.map_err(|_| {
                fail(format!(
                    "web artifact directory cannot be scanned: {}",
                    root.display()
                ))
            })?;
            let path = entry.path();
            let metadata = fs::symlink_metadata(&path).map_err(|_| {
                fail(format!(
                    "web artifact directory cannot be scanned: {}",
                    root.display()
                ))
            })?;
            if path.file_name().is_some_and(|name| name == SEAL_FILENAME)
                && (metadata.is_file() || is_link(&metadata))
            {
                found.push(path);
            } else if metadata.is_dir() && !is_link(&metadata) {
                stack.push(path);
            }
        }
    }
    found.sort();
    Ok(found)
}
fn verify_output_tree(root: &Path, seal: &Seal) -> Result<()> {
    let manifest_path = root.join(VITE_MANIFEST_PATH);
    if !manifest_path.is_file()
        || is_link(&fs::symlink_metadata(&manifest_path).map_err(|_| {
            fail(format!(
                "Vite manifest missing: {}",
                manifest_path.display()
            ))
        })?)
    {
        return Err(fail(format!(
            "Vite manifest missing: {}",
            manifest_path.display()
        )));
    }
    let actual = output_records(root)?;
    let expected: BTreeMap<_, _> = seal
        .output_files
        .iter()
        .map(|item| (&item.path, item))
        .collect();
    let observed: BTreeMap<_, _> = actual.iter().map(|item| (&item.path, item)).collect();
    let missing: Vec<_> = expected
        .keys()
        .filter(|path| !observed.contains_key(*path))
        .map(|path| path.as_str())
        .collect();
    if !missing.is_empty() {
        return Err(fail(format!(
            "listed web artifact file missing: {}",
            missing.join(", ")
        )));
    }
    let extra: Vec<_> = observed
        .keys()
        .filter(|path| !expected.contains_key(*path))
        .map(|path| path.as_str())
        .collect();
    if !extra.is_empty() {
        return Err(fail(format!(
            "extra stale web artifact file: {}",
            extra.join(", ")
        )));
    }
    let mutated: Vec<_> = expected
        .iter()
        .filter(|(path, record)| observed.get(*path) != Some(record))
        .map(|(path, _)| path.as_str())
        .collect();
    if !mutated.is_empty() {
        return Err(fail(format!(
            "web artifact byte digest mismatch: {}",
            mutated.join(", ")
        )));
    }
    if records_sha256(&actual)? != seal.tree_sha256 {
        return Err(fail("web artifact tree digest mismatch"));
    }
    let studio = studio_output_closure(root, &actual)?;
    validate_output_composition(&actual, &studio)?;
    validate_vite_manifest(&manifest_path)?;
    validate_output_references(root, &actual)?;
    Ok(())
}
fn verify_source_state(repo: &Path, seal: &Seal) -> Result<()> {
    let commit = current_git_commit(repo)?;
    if commit != seal.source_commit {
        return Err(fail(format!(
            "source commit mismatch: sealed={} current={commit}",
            seal.source_commit
        )));
    }
    let declared = declared_toolchain(repo)?;
    if declared != seal.toolchain {
        return Err(fail(format!(
            "sealed toolchain does not match current exact pins: sealed={:?} declared={declared:?}",
            seal.toolchain
        )));
    }
    let lock = file_record(&repo.join("package-lock.json"), repo, "package-lock input")?;
    if lock != seal.package_lock {
        return Err(fail("package-lock input stale"));
    }
    let actual = source_records(repo)?;
    if actual != seal.source_files || records_sha256(&actual)? != seal.source_input_sha256 {
        return Err(fail("frontend/config source input stale"));
    }
    assert_studio_source_pin(&actual, &seal.output_files)
}
fn verify_artifact(root: &Path, repo: Option<&Path>) -> Result<VerifiedArtifact> {
    if !root.is_dir() {
        return Err(fail(format!(
            "web artifact directory missing: {}",
            root.display()
        )));
    }
    let seal_path = root.join(SEAL_FILENAME);
    let candidates = seal_candidates(root)?;
    let seal_metadata = fs::symlink_metadata(&seal_path);
    if !seal_metadata
        .as_ref()
        .is_ok_and(|meta| meta.is_file() && !is_link(meta))
    {
        return Err(fail(format!(
            "web artifact seal missing: {}",
            seal_path.display()
        )));
    }
    if candidates != [seal_path.clone()] {
        return Err(fail(format!(
            "web artifact must contain exactly one root seal: {}",
            candidates
                .iter()
                .map(|path| path.display().to_string())
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }
    let seal = load_seal(&seal_path)?;
    verify_output_tree(root, &seal)?;
    if let Some(repo) = repo {
        verify_source_state(repo, &seal)?;
    }
    let index = root.join("index.html");
    let index_meta = fs::symlink_metadata(&index);
    if !index_meta
        .as_ref()
        .is_ok_and(|meta| meta.is_file() && !is_link(meta))
    {
        return Err(fail(format!(
            "web artifact index missing: {}",
            index.display()
        )));
    }
    Ok(VerifiedArtifact {
        root: root.to_path_buf(),
        index_path: index,
        artifact_id: seal.artifact_id,
        tree_sha256: seal.tree_sha256,
        source_commit: seal.source_commit,
    })
}
pub fn resolve_source(repo: &Path) -> Result<VerifiedArtifact> {
    let repo = fs::canonicalize(repo).map_err(|_| {
        fail(format!(
            "repository root cannot be read: {}",
            repo.display()
        ))
    })?;
    let root = fs::canonicalize(repo.join("build/web")).map_err(|_| {
        fail(format!(
            "web artifact directory missing: {}",
            repo.join("build/web").display()
        ))
    })?;
    verify_artifact(&root, Some(&repo))
}
pub fn resolve_frozen(frozen: &Path) -> Result<VerifiedArtifact> {
    let root = fs::canonicalize(frozen.join("web")).map_err(|_| {
        fail(format!(
            "web artifact directory missing: {}",
            frozen.join("web").display()
        ))
    })?;
    verify_artifact(&root, None)
}

pub fn verify_packaged(repo: &Path, bundle: &Path) -> Result<(VerifiedArtifact, VerifiedArtifact)> {
    let source = resolve_source(repo)?;
    let bundled = resolve_frozen(bundle)?;
    if source.artifact_id != bundled.artifact_id || source.tree_sha256 != bundled.tree_sha256 {
        return Err(fail(
            "source and bundled web artifacts do not have the same identity",
        ));
    }
    verify_notice_files(bundle)?;
    let notices = json_object(&bundle.join("native-notices.json"), "native notices")?;
    if notices.get("artifact_id").and_then(Value::as_str) != Some(source.artifact_id.as_str())
        || notices.get("tree_sha256").and_then(Value::as_str) != Some(source.tree_sha256.as_str())
        || notices.get("cargo_lock_sha256").and_then(Value::as_str)
            != Some(sha256(&read_bytes(&repo.join("Cargo.lock"), "Cargo lock")?).as_str())
    {
        return Err(fail(
            "native notice identity differs from source artifact or Cargo.lock",
        ));
    }
    Ok((source, bundled))
}

pub fn seal_repository(
    repo: &Path,
    node: Option<&Path>,
    npm: Option<&Path>,
    vite: Option<&Path>,
) -> Result<VerifiedArtifact> {
    let repo = fs::canonicalize(repo).map_err(|_| {
        fail(format!(
            "repository root cannot be read: {}",
            repo.display()
        ))
    })?;
    let root = fs::canonicalize(repo.join("build/web")).map_err(|_| {
        fail(format!(
            "web artifact directory missing: {}",
            repo.join("build/web").display()
        ))
    })?;
    assert_source_inputs_clean(&repo)?;
    let source_commit = current_git_commit(&repo)?;
    let source_files = source_records(&repo)?;
    let package_lock =
        find_record(&source_files, "package-lock.json", "package-lock input")?.clone();
    let toolchain = detect_toolchain(&repo, node, npm, vite)?;
    let temporary = root.join(format!(".{SEAL_FILENAME}.tmp"));
    if fs::symlink_metadata(&temporary).is_ok() {
        return Err(fail(format!(
            "stale seal temporary file exists: {}",
            temporary.display()
        )));
    }
    let output_files = output_records(&root)?;
    assert_studio_source_pin(&source_files, &output_files)?;
    let index = root.join("index.html");
    let index_meta = fs::symlink_metadata(&index);
    if !index_meta
        .as_ref()
        .is_ok_and(|meta| meta.is_file() && !is_link(meta))
    {
        return Err(fail(format!(
            "web artifact index missing: {}",
            index.display()
        )));
    }
    let manifest = root.join(VITE_MANIFEST_PATH);
    let manifest_meta = fs::symlink_metadata(&manifest);
    if !manifest_meta
        .as_ref()
        .is_ok_and(|meta| meta.is_file() && !is_link(meta))
    {
        return Err(fail(format!(
            "Vite manifest missing: {}",
            manifest.display()
        )));
    }
    let studio = studio_output_closure(&root, &output_files)?;
    validate_output_composition(&output_files, &studio)?;
    validate_vite_manifest(&manifest)?;
    validate_output_references(&root, &output_files)?;
    let vite_manifest = find_record(&output_files, VITE_MANIFEST_PATH, "Vite manifest")?.clone();
    let mut seal = Seal {
        artifact_id: String::new(),
        source_commit,
        source_input_sha256: records_sha256(&source_files)?,
        source_files,
        package_lock,
        toolchain,
        vite_manifest,
        tree_sha256: records_sha256(&output_files)?,
        output_files,
    };
    seal.artifact_id = canonical_sha256(&seal.core_document())?;
    let seal_path = root.join(SEAL_FILENAME);
    if fs::symlink_metadata(&seal_path).is_ok_and(|meta| is_link(&meta)) {
        return Err(fail(format!(
            "web artifact seal cannot be a link: {}",
            seal_path.display()
        )));
    }
    let mut bytes = serde_json::to_string_pretty(&sorted_value(&seal.document()))
        .map_err(|_| fail("web artifact seal cannot be encoded"))?;
    bytes.push('\n');
    if cfg!(windows) {
        bytes = bytes.replace('\n', "\r\n");
    }
    fs::write(&temporary, bytes).map_err(|_| {
        fail(format!(
            "web artifact seal cannot be written: {}",
            seal_path.display()
        ))
    })?;
    if fs::rename(&temporary, &seal_path).is_err() {
        let _ = fs::remove_file(&temporary);
        return Err(fail(format!(
            "web artifact seal cannot be written: {}",
            seal_path.display()
        )));
    }
    verify_artifact(&root, Some(&repo))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        FileRecord, REQUIRED_NOTICE_FILES, RHWP_COMMIT, SEAL_FILENAME, Seal, Toolchain,
        VITE_MANIFEST_PATH, canonical_sha256, dirty_paths, find_record, output_records,
        records_sha256, resolve_frozen, resolve_source, seal_repository, sha256, sorted_value,
        validate_relative_path, verify_notice_files,
    };
    use serde_json::json;
    use std::fs;
    use std::path::Path;
    use std::process::Command;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn canonical_digest_is_independent_of_map_iteration_order() {
        assert_eq!(
            dirty_paths(" M frontend/css/tokens.css\n?? frontend/new.js\n"),
            ["frontend/css/tokens.css", "frontend/new.js"]
        );
        let value = json!({"b": 2, "a": {"d": 4, "c": 3}});
        assert_eq!(
            sorted_value(&value).to_string(),
            r#"{"a":{"c":3,"d":4},"b":2}"#
        );
        assert_eq!(
            canonical_sha256(&value).unwrap(),
            "c461c47a913352f1a21e3f2ea49e1fd34754c0dc12cb7366e4636d5e186c6c6e"
        );
        for unsafe_path in [
            "",
            "/index.html",
            "../index.html",
            "assets//main.js",
            "assets/./main.js",
            "C:/main.js",
            "assets\\main.js",
        ] {
            assert!(
                validate_relative_path(unsafe_path, "test").is_err(),
                "{unsafe_path}"
            );
        }
        validate_relative_path("assets/main.js", "test").unwrap();
    }

    #[test]
    fn required_packaged_notices_are_checked_as_one_closed_set() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let bundle = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../target")
            .join(format!("hwpx-notices-{}-{stamp}", std::process::id()));
        for name in REQUIRED_NOTICE_FILES {
            let path = bundle.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            if *name != "native-notices.json" {
                fs::write(path, b"notice").unwrap();
            }
        }
        let dynamic = [
            "THIRD_PARTY_NOTICES",
            "licenses/rust/example/LICENSE",
            "licenses/npm/example/LICENSE",
            "licenses/microsoft/WebView2-SDK-LICENSE.txt",
        ];
        for name in dynamic {
            let path = bundle.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, b"notice").unwrap();
        }
        let files = dynamic
            .iter()
            .map(|path| json!({"path": path, "sha256": sha256(b"notice")}))
            .collect::<Vec<_>>();
        fs::write(
            bundle.join("native-notices.json"),
            serde_json::to_vec(&json!({"schema_version": 1, "files": files})).unwrap(),
        )
        .unwrap();
        verify_notice_files(&bundle).unwrap();
        for name in REQUIRED_NOTICE_FILES {
            let path = bundle.join(name);
            fs::remove_file(&path).unwrap();
            assert!(
                verify_notice_files(&bundle)
                    .unwrap_err()
                    .to_string()
                    .contains(name)
            );
            if *name == "native-notices.json" {
                fs::write(
                    path,
                    serde_json::to_vec(&json!({"schema_version": 1, "files": files})).unwrap(),
                )
                .unwrap();
            } else {
                fs::write(path, b"notice").unwrap();
            }
        }
        fs::write(bundle.join("licenses/rust/example/LICENSE"), b"altered").unwrap();
        assert!(verify_notice_files(&bundle).is_err());
        fs::write(bundle.join("licenses/rust/example/LICENSE"), b"notice").unwrap();
        fs::write(bundle.join("licenses/rust/extra"), b"unlisted").unwrap();
        assert!(verify_notice_files(&bundle).is_err());
        fs::remove_dir_all(bundle).unwrap();
    }

    fn reseal(web: &Path, seal: &mut Seal) {
        let files = output_records(web).unwrap();
        seal.vite_manifest = find_record(&files, VITE_MANIFEST_PATH, "Vite manifest")
            .unwrap()
            .clone();
        seal.tree_sha256 = records_sha256(&files).unwrap();
        seal.output_files = files;
        seal.artifact_id = canonical_sha256(&seal.core_document()).unwrap();
        fs::write(
            web.join(SEAL_FILENAME),
            serde_json::to_vec(&seal.document()).unwrap(),
        )
        .unwrap();
    }

    fn write_web_fixture(web: &Path) {
        for directory in [".vite", "assets", "rhwp/studio"] {
            fs::create_dir_all(web.join(directory)).unwrap();
        }
        fs::write(web.join("index.html"), "<html></html>").unwrap();
        fs::write(
            web.join(VITE_MANIFEST_PATH),
            "{\"main\":{\"file\":\"assets/main.js\"}}",
        )
        .unwrap();
        fs::write(web.join("assets/main.js"), "console.log(1);").unwrap();
        let studio = "<html></html>";
        fs::write(web.join("rhwp/studio/index.html"), studio).unwrap();
        fs::write(web.join("rhwp/studio-runtime.json"), serde_json::to_vec(&json!({
            "schema": 1, "source_commit": RHWP_COMMIT,
            "files": [{"path": "studio/index.html", "size": studio.len(), "sha256": sha256(studio.as_bytes())}]
        })).unwrap()).unwrap();
    }

    fn rejects<T: std::fmt::Debug>(result: super::Result<T>, expected: &str) {
        let message = result.unwrap_err().to_string();
        assert!(
            message.contains(expected),
            "expected {expected:?}, got {message:?}"
        );
    }

    fn assert_frozen_seal_failures(frozen: &Path, seal: &Seal) {
        let web = frozen.join("web");
        let seal_path = web.join(SEAL_FILENAME);
        for (relative, message) in [
            (SEAL_FILENAME, "web artifact seal missing"),
            (VITE_MANIFEST_PATH, "Vite manifest missing"),
            (
                "assets/main.js",
                "listed web artifact file missing: assets/main.js",
            ),
        ] {
            let path = web.join(relative);
            let bytes = fs::read(&path).unwrap();
            fs::remove_file(&path).unwrap();
            rejects(resolve_frozen(frozen), message);
            fs::write(path, bytes).unwrap();
        }
        let nested = web.join("assets").join(SEAL_FILENAME);
        fs::write(&nested, "{}").unwrap();
        rejects(resolve_frozen(frozen), "exactly one root seal");
        fs::remove_file(nested).unwrap();

        let pristine = fs::read(&seal_path).unwrap();
        for (pointer, value, message) in [
            ("/schema", json!(2), "unsupported web artifact seal schema"),
            ("/source", json!(null), "invalid sections"),
            ("/source/commit", json!("main"), "invalid source commit"),
            (
                "/artifact_id",
                json!("0".repeat(64)),
                "web artifact ID mismatch",
            ),
            (
                "/source/input_sha256",
                json!("0".repeat(64)),
                "source input digest in web artifact seal is inconsistent",
            ),
            (
                "/package_lock/sha256",
                json!("0".repeat(64)),
                "package-lock digest in web artifact seal is inconsistent",
            ),
            (
                "/output/tree_sha256",
                json!("0".repeat(64)),
                "output tree digest in web artifact seal is inconsistent",
            ),
            (
                "/vite_manifest/sha256",
                json!("0".repeat(64)),
                "Vite manifest digest in web artifact seal is inconsistent",
            ),
            (
                "/output/files/0/path",
                json!("../outside.js"),
                "path is unsafe",
            ),
            ("/output/files/0/size", json!(-1), "invalid size"),
            ("/output/files/0/sha256", json!("oops"), "invalid digest"),
            ("/output/files", json!([]), "invalid file list"),
            ("/toolchain/node", json!("^1.2.3"), "exact semantic version"),
        ] {
            let mut document = seal.document();
            *document.pointer_mut(pointer).unwrap() = value;
            fs::write(&seal_path, serde_json::to_vec(&document).unwrap()).unwrap();
            rejects(resolve_frozen(frozen), message);
        }
        let mut document = seal.document();
        document["output"]["files"]
            .as_array_mut()
            .unwrap()
            .reverse();
        fs::write(&seal_path, serde_json::to_vec(&document).unwrap()).unwrap();
        rejects(resolve_frozen(frozen), "not unique and sorted");
        document = seal.document();
        document["unexpected"] = json!(true);
        fs::write(&seal_path, serde_json::to_vec(&document).unwrap()).unwrap();
        rejects(resolve_frozen(frozen), "invalid fields: root");
        fs::write(&seal_path, b"{").unwrap();
        rejects(resolve_frozen(frozen), "invalid JSON");
        fs::write(&seal_path, pristine).unwrap();

        for intruder in [
            "assets/main.ts",
            "assets/vite.config.mjs",
            "assets/main.js.map",
            "assets/deep/nested.js",
            "package.json",
        ] {
            let path = web.join(intruder);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(&path, "{}").unwrap();
            reseal(&web, &mut seal.clone());
            rejects(
                resolve_frozen(frozen),
                &format!("shipped-composition closure: {intruder}"),
            );
            fs::remove_file(path).unwrap();
        }
        reseal(&web, &mut seal.clone());
        resolve_frozen(frozen).unwrap();
    }

    fn fixture_git(repo: &Path, args: &[&str]) {
        let output = Command::new("git")
            .arg("-C")
            .arg(repo)
            .args([
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.hooksPath=empty-hooks",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Artifact fixture",
                "-c",
                "user.email=artifact@example.invalid",
            ])
            .args(args)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "git {args:?}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    fn version_command(repo: &Path, name: &str, version: &str) -> std::path::PathBuf {
        let path = repo.join(format!(
            "{name}.{}",
            if cfg!(windows) { "cmd" } else { "sh" }
        ));
        let text = if cfg!(windows) {
            format!("@echo off\r\necho {version}\r\n")
        } else {
            format!("#!/bin/sh\nprintf '%s\\n' '{version}'\n")
        };
        fs::write(&path, text).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        }
        path
    }

    #[test]
    fn producer_seals_clean_sources_and_refuses_stale_or_unshippable_inputs() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let repo =
            std::env::temp_dir().join(format!("hwpx-source-seal-{}-{stamp}", std::process::id()));
        let web = repo.join("build/web");
        write_web_fixture(&web);
        for (path, content) in [
            ("frontend/src/main.js", "console.log(1);"),
            (".node-version", "24.18.1\n"),
            (".npmrc", "engine-strict=true\n"),
            (
                "package.json",
                r#"{"packageManager":"npm@11.16.0","devDependencies":{"vite":"8.1.5"}}"#,
            ),
            (
                "package-lock.json",
                r#"{"lockfileVersion":3,"packages":{"":{"devDependencies":{"vite":"8.1.5"}}}}"#,
            ),
            ("tsconfig.json", r#"{"compilerOptions":{"strict":true}}"#),
            (
                "vite.config.mjs",
                "export default {base:'./',build:{manifest:true}};",
            ),
            ("scripts/build_rhwp.ps1", "# fixture build\n"),
            ("vendor/rhwp/patches/authoring.patch", "fixture patch\n"),
        ] {
            let path = repo.join(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, content).unwrap();
        }
        fs::write(
            repo.join("vendor/rhwp/source.json"),
            json!({"commit": RHWP_COMMIT}).to_string(),
        )
        .unwrap();
        fs::copy(
            web.join("rhwp/studio-runtime.json"),
            repo.join("vendor/rhwp/studio-runtime.json"),
        )
        .unwrap();
        fixture_git(&repo, &["init", "--template=", "--initial-branch=fixture"]);
        fixture_git(
            &repo,
            &[
                "add",
                "frontend",
                "vendor",
                ".node-version",
                ".npmrc",
                "package.json",
                "package-lock.json",
                "tsconfig.json",
                "vite.config.mjs",
                "scripts",
            ],
        );
        fixture_git(&repo, &["commit", "-m", "fixture"]);
        let node = version_command(&repo, "node", "v24.18.1");
        let npm = version_command(&repo, "npm", "11.16.0");
        let vite = version_command(&repo, "vite", "vite/8.1.5 win32-x64");
        let produce = || seal_repository(&repo, Some(&node), Some(&npm), Some(&vite));

        assert_producer_output_refusals(&web, &produce);
        let first = produce().unwrap();
        let seal_path = web.join(SEAL_FILENAME);
        let first_bytes = fs::read(&seal_path).unwrap();
        let seal = super::load_seal(&seal_path).unwrap();
        assert_eq!(
            seal.source_commit,
            super::current_git_commit(&repo).unwrap()
        );
        assert_eq!(
            seal.toolchain,
            Toolchain {
                node: "24.18.1".into(),
                npm: "11.16.0".into(),
                vite: "8.1.5".into()
            }
        );
        assert_eq!(
            seal.source_files
                .iter()
                .map(|record| record.path.as_str())
                .collect::<Vec<_>>(),
            [
                ".node-version",
                ".npmrc",
                "frontend/src/main.js",
                "package-lock.json",
                "package.json",
                "scripts/build_rhwp.ps1",
                "tsconfig.json",
                "vendor/rhwp/patches/authoring.patch",
                "vendor/rhwp/source.json",
                "vendor/rhwp/studio-runtime.json",
                "vite.config.mjs"
            ]
        );
        assert!(
            !seal
                .output_files
                .iter()
                .any(|record| record.path == SEAL_FILENAME)
        );
        assert_eq!(produce().unwrap(), first);
        assert_eq!(fs::read(&seal_path).unwrap(), first_bytes);
        let frozen = resolve_frozen(&repo.join("build")).unwrap();
        assert_eq!(frozen, resolve_source(&repo).unwrap());
        assert_eq!(
            frozen.snapshot_bytes().unwrap()["assets/main.js"],
            b"console.log(1);"
        );

        for relative in [
            "frontend/src/main.js",
            "vite.config.mjs",
            "tsconfig.json",
            "package-lock.json",
        ] {
            let path = repo.join(relative);
            let before = fs::read(&path).unwrap();
            let mut changed = before.clone();
            changed.push(b'\n');
            fs::write(&path, changed).unwrap();
            rejects(
                resolve_source(&repo),
                if relative == "package-lock.json" {
                    "package-lock input stale"
                } else {
                    "frontend/config source input stale"
                },
            );
            let dirty = produce().unwrap_err().to_string();
            assert!(
                dirty.contains("dirty source tree") && dirty.contains(relative),
                "{dirty}"
            );
            assert_eq!(fs::read(&seal_path).unwrap(), first_bytes);
            fs::write(path, before).unwrap();
        }
        fs::write(repo.join("frontend/new.ts"), "new source").unwrap();
        rejects(produce(), "frontend/new.ts");
        fs::remove_file(repo.join("frontend/new.ts")).unwrap();
        assert_source_pin_failures(&repo, &web, &seal);
        version_command(&repo, "node", "v25.6.0");
        rejects(produce(), "actual web toolchain does not match exact pins");
        version_command(&repo, "node", "not a version");
        rejects(produce(), "Node version command failed");
        version_command(&repo, "node", "v24.18.1");
        fs::write(web.join(format!(".{SEAL_FILENAME}.tmp")), "stale").unwrap();
        rejects(produce(), "stale seal temporary file exists");
        fs::remove_file(web.join(format!(".{SEAL_FILENAME}.tmp"))).unwrap();
        assert_eq!(fs::read(&seal_path).unwrap(), first_bytes);
        fixture_git(&repo, &["commit", "--allow-empty", "-m", "new revision"]);
        rejects(resolve_source(&repo), "source commit mismatch");
        assert_eq!(resolve_frozen(&repo.join("build")).unwrap(), frozen);
        // Git marks loose objects read-only on Windows.
        #[cfg(windows)]
        #[allow(clippy::permissions_set_readonly_false)]
        for directory in fs::read_dir(repo.join(".git/objects")).unwrap() {
            for entry in fs::read_dir(directory.unwrap().path()).unwrap() {
                let path = entry.unwrap().path();
                let mut permissions = fs::metadata(&path).unwrap().permissions();
                permissions.set_readonly(false);
                fs::set_permissions(path, permissions).unwrap();
            }
        }
        fs::remove_dir_all(repo).unwrap();
    }

    fn assert_source_pin_failures(repo: &Path, web: &Path, seal: &Seal) {
        let seal_bytes = fs::read(web.join(SEAL_FILENAME)).unwrap();
        let package_path = repo.join("package.json");
        let package = fs::read(&package_path).unwrap();
        let mut declared: serde_json::Value = serde_json::from_slice(&package).unwrap();
        declared["devDependencies"]["vite"] = json!("^8.1.5");
        fs::write(&package_path, declared.to_string()).unwrap();
        rejects(super::declared_toolchain(repo), "exact semantic version");
        fs::write(package_path, package).unwrap();
        let mut changed = seal.clone();
        changed.toolchain.node = "23.0.0".into();
        reseal(web, &mut changed);
        rejects(
            resolve_source(repo),
            "sealed toolchain does not match current exact pins",
        );
        fs::write(web.join(SEAL_FILENAME), seal_bytes).unwrap();

        let source_pin = repo.join("vendor/rhwp/studio-runtime.json");
        let original = fs::read(&source_pin).unwrap();
        let mut changed = original.clone();
        changed.push(b' ');
        fs::write(&source_pin, changed).unwrap();
        rejects(
            super::assert_studio_source_pin(
                &super::source_records(repo).unwrap(),
                &seal.output_files,
            ),
            "differs from tracked source pin",
        );
        fs::write(source_pin, original).unwrap();
    }

    fn assert_producer_output_refusals(
        web: &Path,
        produce: &impl Fn() -> super::Result<super::VerifiedArtifact>,
    ) {
        for (relative, content, message) in [
            (
                "assets/main.js.map",
                "{}",
                "shipped-composition closure: assets/main.js.map",
            ),
            (
                "rhwp/studio/surprise.js",
                "surprise",
                "differs from pinned runtime manifest",
            ),
            (
                "index.html",
                "<script src='/assets/main.js'>",
                "forbidden absolute /assets URL",
            ),
            (
                "index.html",
                "<script src='file:///tmp/main.js'>",
                "forbidden file: URL",
            ),
            (
                "index.html",
                "<script src='https://cdn.example/main.js'>",
                "forbidden external HTTP(S)",
            ),
            (
                "index.html",
                "<img src='https://react.dev/errors/418'>",
                "forbidden external HTTP(S)",
            ),
            (
                "index.html",
                "<script src='http://www.w3.org/2000/svg'>",
                "forbidden external HTTP(S)",
            ),
            (
                "index.html",
                "<script src='/@vite/client'>",
                "forbidden Vite dev client",
            ),
            (
                "assets/main.js",
                "const ns='http://www.w3.org/2000/svg.evil.example/x.js';",
                "forbidden external HTTP(S)",
            ),
            (
                "assets/main.js",
                "const doc='https://react.dev/errors-evil';",
                "forbidden external HTTP(S)",
            ),
            (
                "assets/main.js",
                "const cdn='https://cdn.example/x.js';",
                "forbidden external HTTP(S)",
            ),
            (VITE_MANIFEST_PATH, "{}", "Vite manifest is empty"),
        ] {
            let path = web.join(relative);
            let before = fs::read(&path).ok();
            fs::write(&path, content).unwrap();
            rejects(produce(), message);
            assert!(
                !web.join(SEAL_FILENAME).exists(),
                "producer wrote a seal before refusing {relative}"
            );
            if let Some(before) = before {
                fs::write(path, before).unwrap();
            } else {
                fs::remove_file(path).unwrap();
            }
        }
        for path in ["assets/style.css", "assets/mark.svg", "assets/font.woff2"] {
            fs::write(web.join(path), "fixture").unwrap();
        }
        let pin = web.join("rhwp/studio-runtime.json");
        let original = fs::read(&pin).unwrap();
        let mut altered = original.clone();
        altered.push(b' ');
        fs::write(&pin, altered).unwrap();
        rejects(produce(), "differs from tracked source pin");
        assert!(!web.join(SEAL_FILENAME).exists());
        fs::write(pin, original).unwrap();
        fs::write(
            web.join("assets/main.js"),
            concat!(
                "createElementNS('http://www.w3.org/2000/svg');",
                "createElementNS('http://www.w3.org/1999/xlink');",
                "createElementNS('http://www.w3.org/XML/1998/namespace');",
                "createElementNS('http://www.w3.org/1998/Math/MathML');",
                "const help='https://react.dev/errors/'+code;"
            ),
        )
        .unwrap();
        produce().unwrap();
        fs::write(web.join("assets/main.js"), "console.log(1);").unwrap();
    }

    #[test]
    fn frozen_verifier_rejects_mutated_or_extra_output_without_source_tools() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let frozen =
            std::env::temp_dir().join(format!("hwpx-artifact-{}-{stamp}", std::process::id()));
        let web = frozen.join("web");
        rejects(resolve_frozen(&frozen), "web artifact directory missing");
        write_web_fixture(&web);
        let files = output_records(&web).unwrap();
        let package_lock = FileRecord {
            path: "package-lock.json".into(),
            size: 0,
            sha256: sha256(b""),
        };
        let source_files = vec![package_lock.clone()];
        let mut seal = Seal {
            artifact_id: String::new(),
            source_commit: "a".repeat(40),
            source_input_sha256: records_sha256(&source_files).unwrap(),
            source_files,
            package_lock,
            toolchain: Toolchain {
                node: "1.2.3".into(),
                npm: "4.5.6".into(),
                vite: "7.8.9".into(),
            },
            vite_manifest: find_record(&files, VITE_MANIFEST_PATH, "Vite manifest")
                .unwrap()
                .clone(),
            tree_sha256: records_sha256(&files).unwrap(),
            output_files: files,
        };
        reseal(&web, &mut seal);
        assert_eq!(
            resolve_frozen(&frozen).unwrap().artifact_id,
            seal.artifact_id
        );
        let snapshot = resolve_frozen(&frozen).unwrap().snapshot_bytes().unwrap();
        assert_eq!(&snapshot["assets/main.js"], b"console.log(1);");
        assert_frozen_seal_failures(&frozen, &seal);
        fs::write(web.join("assets/main.js"), "console.log(2);").unwrap();
        assert!(
            resolve_frozen(&frozen)
                .unwrap_err()
                .to_string()
                .contains("digest mismatch")
        );
        fs::write(web.join("assets/main.js"), "console.log(1);").unwrap();
        fs::write(web.join("assets/extra.js"), "extra").unwrap();
        assert!(
            resolve_frozen(&frozen)
                .unwrap_err()
                .to_string()
                .contains("extra stale")
        );
        fs::remove_file(web.join("assets/extra.js")).unwrap();
        fs::write(
            web.join("index.html"),
            "<script src=\"https://cdn.example/app.js\"></script>",
        )
        .unwrap();
        reseal(&web, &mut seal);
        assert!(
            resolve_frozen(&frozen)
                .unwrap_err()
                .to_string()
                .contains("forbidden external HTTP(S)")
        );
        fs::write(web.join("index.html"), "<html></html>").unwrap();
        let broken_studio = "<link href=\"missing.css\">";
        fs::write(web.join("rhwp/studio/index.html"), broken_studio).unwrap();
        fs::write(web.join("rhwp/studio-runtime.json"), serde_json::to_vec(&json!({
            "schema": 1, "source_commit": RHWP_COMMIT,
            "files": [{"path": "studio/index.html", "size": broken_studio.len(), "sha256": sha256(broken_studio.as_bytes())}]
        })).unwrap()).unwrap();
        reseal(&web, &mut seal);
        assert!(
            resolve_frozen(&frozen)
                .unwrap_err()
                .to_string()
                .contains("static resource is missing")
        );
        fs::remove_dir_all(frozen).unwrap();
    }
}
