//! Seal or verify the source-checkout web artifact without a Python runtime.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

use hwpx_artifact::reconcile;
use hwpx_artifact::webview_retry;
use hwpx_artifact::{VerifiedArtifact, resolve_source, seal_repository, verify_packaged};
use serde::Serialize;
use serde_json::{Value, json};
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

struct Args {
    repo: PathBuf,
    bundle: Option<PathBuf>,
    node: Option<PathBuf>,
    npm: Option<PathBuf>,
    vite: Option<PathBuf>,
    verify: bool,
    json_out: Option<PathBuf>,
    expect_identity: Option<PathBuf>,
    reconcile: bool,
    copies: Vec<(String, PathBuf)>,
    build_metadata: Option<PathBuf>,
    expected: Option<String>,
    selfcheck_evidence: Option<PathBuf>,
    classify_webview: Option<PathBuf>,
}

fn next_path(args: &mut impl Iterator<Item = OsString>, option: &str) -> Result<PathBuf, String> {
    let value = args
        .next()
        .ok_or_else(|| format!("{option} requires a path"))?;
    if value.is_empty() || value.to_string_lossy().starts_with("--") {
        return Err(format!("{option} requires a path"));
    }
    Ok(PathBuf::from(value))
}

fn next_copy(args: &mut impl Iterator<Item = OsString>) -> Result<(String, PathBuf), String> {
    let value = args.next().ok_or("--copy 는 NAME=PATH 형식입니다")?;
    let text = value
        .to_str()
        .ok_or("--copy 는 Unicode NAME=PATH 형식입니다")?;
    let (name, path) = text
        .split_once('=')
        .ok_or("--copy 는 NAME=PATH 형식입니다")?;
    if name.is_empty() || path.is_empty() {
        return Err("--copy 는 NAME=PATH 형식입니다".into());
    }
    Ok((name.to_owned(), PathBuf::from(path)))
}

impl Args {
    fn accept_source(
        &mut self,
        flag: &str,
        args: &mut impl Iterator<Item = OsString>,
    ) -> Result<bool, String> {
        match flag {
            "--repo-root" => self.repo = next_path(args, flag)?,
            "--node-command" => self.node = Some(next_path(args, flag)?),
            "--npm-command" => self.npm = Some(next_path(args, flag)?),
            "--vite-command" => self.vite = Some(next_path(args, flag)?),
            _ => return Ok(false),
        }
        Ok(true)
    }

    fn accept_artifact(
        &mut self,
        flag: &str,
        args: &mut impl Iterator<Item = OsString>,
    ) -> Result<bool, String> {
        match flag {
            "--bundle-root" => self.bundle = Some(next_path(args, flag)?),
            "--verify" => self.verify = true,
            "--json-out" => self.json_out = Some(next_path(args, flag)?),
            "--expect-identity" => self.expect_identity = Some(next_path(args, flag)?),
            "--selfcheck-evidence" => self.selfcheck_evidence = Some(next_path(args, flag)?),
            "--classify-webview" => self.classify_webview = Some(next_path(args, flag)?),
            _ => return Ok(false),
        }
        Ok(true)
    }

    fn accept_reconcile(
        &mut self,
        flag: &str,
        args: &mut impl Iterator<Item = OsString>,
    ) -> Result<bool, String> {
        match flag {
            "--reconcile" => self.reconcile = true,
            "--copy" => self.copies.push(next_copy(args)?),
            "--build-metadata" => self.build_metadata = Some(next_path(args, flag)?),
            "--expect" => {
                let names = args
                    .next()
                    .ok_or("--expect 에는 사본 이름이 하나 이상 필요합니다")?;
                self.expected = Some(
                    names
                        .into_string()
                        .map_err(|_| "--expect 에는 Unicode 사본 이름이 필요합니다")?,
                );
            }
            _ => return Ok(false),
        }
        Ok(true)
    }

    fn has_tool_overrides(&self) -> bool {
        self.node.is_some() || self.npm.is_some() || self.vite.is_some()
    }

    fn has_copy_options(&self) -> bool {
        !self.copies.is_empty() || self.build_metadata.is_some() || self.expected.is_some()
    }

    fn shared_mode_options(&self) -> bool {
        self.verify
            || self.bundle.is_some()
            || self.reconcile
            || self.has_copy_options()
            || self.has_tool_overrides()
    }

    fn validate_seal_bundle(&self) -> Result<(), String> {
        if self.verify && self.has_tool_overrides() {
            return Err("tool command overrides cannot be used with --verify".into());
        }
        if self.bundle.is_some()
            && (self.verify || self.expect_identity.is_some() || self.has_tool_overrides())
        {
            return Err("--bundle-root cannot be combined with seal or tool options".into());
        }
        Ok(())
    }

    fn validate_mode(&self) -> Result<(), String> {
        self.validate_seal_bundle()?;
        if self.classify_webview.is_some() {
            if self.has_classify_conflicts() {
                return Err("--classify-webview takes only its evidence path".into());
            }
        } else if self.selfcheck_evidence.is_some() {
            if self.expect_identity.is_none() || self.shared_mode_options() {
                return Err(
                    "--selfcheck-evidence requires --expect-identity and no other mode".into(),
                );
            }
        } else if self.reconcile {
            self.validate_reconcile()?;
        } else if self.has_copy_options() {
            return Err("--copy, --build-metadata, and --expect require --reconcile".into());
        }
        Ok(())
    }

    fn has_classify_conflicts(&self) -> bool {
        self.shared_mode_options()
            || self.selfcheck_evidence.is_some()
            || self.expect_identity.is_some()
            || self.json_out.is_some()
    }

    fn validate_reconcile(&self) -> Result<(), String> {
        if self.verify
            || self.bundle.is_some()
            || self.expect_identity.is_some()
            || self.has_tool_overrides()
        {
            return Err("--reconcile cannot be combined with seal or verify options".into());
        }
        if self
            .expected
            .as_deref()
            .is_none_or(|names| names.split(',').all(|name| name.trim().is_empty()))
        {
            return Err("--expect 에는 사본 이름이 하나 이상 필요합니다".into());
        }
        Ok(())
    }
}

fn parse_args(
    mut args: impl Iterator<Item = OsString>,
    repo: PathBuf,
) -> Result<Option<Args>, String> {
    let mut parsed = Args {
        repo,
        bundle: None,
        node: None,
        npm: None,
        vite: None,
        verify: false,
        json_out: None,
        expect_identity: None,
        reconcile: false,
        copies: Vec::new(),
        build_metadata: None,
        expected: None,
        selfcheck_evidence: None,
        classify_webview: None,
    };
    while let Some(arg) = args.next() {
        let flag = arg
            .to_str()
            .ok_or_else(|| "unrecognized non-Unicode option".to_owned())?;
        if matches!(flag, "--help" | "-h") {
            return Ok(None);
        }
        if !(parsed.accept_source(flag, &mut args)?
            || parsed.accept_artifact(flag, &mut args)?
            || parsed.accept_reconcile(flag, &mut args)?)
        {
            return Err(format!("unrecognized argument: {flag}"));
        }
    }
    parsed.validate_mode()?;
    Ok(Some(parsed))
}

fn parse() -> Result<Option<Args>, String> {
    parse_args(
        std::env::args_os().skip(1),
        std::env::current_dir().map_err(|error| error.to_string())?,
    )
}

#[derive(Serialize)]
struct Identity<'a> {
    schema: u8,
    artifact_id: &'a str,
    tree_sha256: &'a str,
    source_commit: &'a str,
}

fn identity(artifact: &VerifiedArtifact) -> Identity<'_> {
    Identity {
        schema: 1,
        artifact_id: &artifact.artifact_id,
        tree_sha256: &artifact.tree_sha256,
        source_commit: &artifact.source_commit,
    }
}

fn printable_root(path: &Path) -> String {
    let raw = path.display().to_string();
    if let Some(unc) = raw.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{unc}")
    } else if let Some(local) = raw.strip_prefix(r"\\?\") {
        local.to_owned()
    } else {
        raw
    }
}

fn expect_identity(actual: &Value, path: &Path) -> Result<(), String> {
    let mut bytes = fs::read(path).map_err(|error| error.to_string())?;
    if bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
        bytes.drain(..3);
    }
    let expected: Value = serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    if expected.get("schema") != Some(&json!(1)) {
        return Err(format!(
            "identity schema mismatch: expected=1 actual={:?} ({})",
            expected.get("schema"),
            path.display()
        ));
    }
    let differences: Vec<_> = ["artifact_id", "tree_sha256", "source_commit"]
        .iter()
        .filter(|field| expected.get(**field) != actual.get(**field))
        .map(|field| {
            format!(
                "{field}: producer={:?} local={:?}",
                expected.get(*field),
                actual.get(*field)
            )
        })
        .collect();
    if !differences.is_empty() {
        return Err(format!(
            "web artifact identity mismatch — {}",
            differences.join(" · ")
        ));
    }
    Ok(())
}

#[derive(Serialize)]
struct PackagedEvidence {
    artifact_id: String,
    tree_sha256: String,
    source_root: String,
    bundled_root: String,
    same_artifact: bool,
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut text = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    text.push('\n');
    if cfg!(windows) {
        text = text.replace('\n', "\r\n");
    }
    fs::write(path, text).map_err(|error| error.to_string())
}

fn print_evidence(value: &impl Serialize, path: Option<&Path>) -> Result<(), String> {
    if let Some(path) = path {
        write_json(path, value)?;
    }
    println!(
        "{}",
        serde_json::to_string(value).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn run_classify(path: &Path) -> Result<i32, String> {
    let verdict = webview_retry::classify_file(path)?;
    println!(
        "{}",
        serde_json::to_string(&verdict).map_err(|error| error.to_string())?
    );
    Ok(if verdict.verdict == "environment-boot-failure" {
        0
    } else {
        1
    })
}

fn run_selfcheck(args: &Args, selfcheck: &Path) -> Result<i32, String> {
    let expected = args
        .expect_identity
        .as_deref()
        .ok_or("--expect-identity is required")?;
    let evidence = reconcile::judge_selfcheck(selfcheck, expected)?;
    print_evidence(&evidence, args.json_out.as_deref())?;
    Ok(0)
}

fn run_reconcile(args: &Args) -> Result<i32, String> {
    let expected = args
        .expected
        .as_deref()
        .unwrap_or_default()
        .split(',')
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let evidence = reconcile::reconcile(&args.copies, args.build_metadata.as_deref(), &expected)?;
    print_evidence(&evidence, args.json_out.as_deref())?;
    Ok(0)
}

fn run_bundle(args: &Args, bundle: &Path) -> Result<i32, String> {
    let (source, bundled) =
        verify_packaged(&args.repo, bundle).map_err(|error| error.to_string())?;
    let evidence = PackagedEvidence {
        artifact_id: source.artifact_id,
        tree_sha256: source.tree_sha256,
        source_root: printable_root(&source.root),
        bundled_root: printable_root(&bundled.root),
        same_artifact: true,
    };
    print_evidence(&evidence, args.json_out.as_deref())?;
    Ok(0)
}

fn run_seal(args: &Args) -> Result<i32, String> {
    let artifact = if args.verify {
        resolve_source(&args.repo)
    } else {
        seal_repository(
            &args.repo,
            args.node.as_deref(),
            args.npm.as_deref(),
            args.vite.as_deref(),
        )
    }
    .map_err(|error| error.to_string())?;
    let value = identity(&artifact);
    if let Some(path) = args.expect_identity.as_deref() {
        expect_identity(
            &serde_json::to_value(&value).map_err(|error| error.to_string())?,
            path,
        )?;
    }
    if let Some(path) = args.json_out.as_deref() {
        write_json(path, &value)?;
    }
    println!("artifact_id={}", artifact.artifact_id);
    println!("tree_sha256={}", artifact.tree_sha256);
    println!("source_commit={}", artifact.source_commit);
    println!("root={}", printable_root(&artifact.root));
    Ok(0)
}

fn run() -> Result<i32, String> {
    let Some(args) = parse()? else {
        println!(
            "Usage: hwpx-artifact [--repo-root PATH] [--verify | --bundle-root PATH] [--reconcile --build-metadata PATH --copy NAME=PATH --expect NAMES] [--selfcheck-evidence PATH --expect-identity PATH] [--classify-webview PATH] [--json-out PATH] [--node-command PATH] [--npm-command PATH] [--vite-command PATH]"
        );
        println!(
            "Seal build/web with pinned tools, or verify its existing seal with --verify without invoking Node/npm/Vite."
        );
        return Ok(0);
    };
    if let Some(path) = args.classify_webview.as_deref() {
        run_classify(path)
    } else if let Some(path) = args.selfcheck_evidence.as_deref() {
        run_selfcheck(&args, path)
    } else if args.reconcile {
        run_reconcile(&args)
    } else if let Some(path) = args.bundle.as_deref() {
        run_bundle(&args, path)
    } else {
        run_seal(&args)
    }
}

fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(error) if std::env::args_os().any(|arg| arg == "--classify-webview") => {
            eprintln!("{error}");
            std::process::exit(2);
        }
        Err(error) => {
            if std::env::args_os().any(|arg| arg == "--selfcheck-evidence") {
                eprintln!("selfcheck identity check failed: {error}");
            } else if std::env::args_os().any(|arg| arg == "--reconcile") {
                eprintln!("shipped copy reconciliation failed: {error}");
            } else if std::env::args_os().any(|arg| arg == "--bundle-root") {
                eprintln!("packaged web verification failed: {error}");
            } else {
                eprintln!("web artifact seal failed: {error}");
            }
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{VerifiedArtifact, identity, parse_args};
    use serde_json::{Value, json};
    use std::ffi::OsString;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn identity_json_keeps_python_field_order_with_or_without_preserve_order() {
        let artifact = VerifiedArtifact {
            root: PathBuf::new(),
            index_path: PathBuf::new(),
            artifact_id: "a".into(),
            tree_sha256: "b".into(),
            source_commit: "c".into(),
        };
        assert_eq!(
            serde_json::to_string_pretty(&identity(&artifact)).unwrap(),
            "{\n  \"schema\": 1,\n  \"artifact_id\": \"a\",\n  \"tree_sha256\": \"b\",\n  \"source_commit\": \"c\"\n}"
        );
        assert_evidence_files_keep_identity_and_exit_status();
    }

    fn assert_evidence_files_keep_identity_and_exit_status() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("hwpx-artifact-cli-{}-{stamp}", std::process::id()));
        let expected = root.join("source.json");
        let actual = json!({"schema":1,"artifact_id":"a".repeat(64),"tree_sha256":"b".repeat(64),"source_commit":"c".repeat(40)});
        super::write_json(&expected, &actual).unwrap();
        super::expect_identity(&actual, &expected).unwrap();
        let mut bytes = vec![0xef, 0xbb, 0xbf];
        bytes.extend(fs::read(&expected).unwrap());
        fs::write(&expected, bytes).unwrap();
        super::expect_identity(&actual, &expected).unwrap();
        for field in ["artifact_id", "tree_sha256", "source_commit"] {
            let mut changed = actual.clone();
            changed[field] = json!("d".repeat(64));
            let error = super::expect_identity(&changed, &expected).unwrap_err();
            assert!(
                error.contains("identity mismatch") && error.contains(field),
                "{error}"
            );
        }
        super::write_json(&expected, &json!({"schema":2})).unwrap();
        assert!(
            super::expect_identity(&actual, &expected)
                .unwrap_err()
                .contains("identity schema mismatch")
        );
        fs::write(&expected, "{").unwrap();
        assert!(super::expect_identity(&actual, &expected).is_err());
        fs::remove_file(&expected).unwrap();
        assert!(super::expect_identity(&actual, &expected).is_err());
        super::write_json(&expected, &actual).unwrap();

        let output = root.join("result.json");
        let selfcheck = root.join("selfcheck.json");
        super::write_json(&selfcheck, &actual).unwrap();
        let args = parse_args(
            [
                OsString::from("--selfcheck-evidence"),
                selfcheck.clone().into_os_string(),
                OsString::from("--expect-identity"),
                expected.clone().into_os_string(),
                OsString::from("--json-out"),
                output.clone().into_os_string(),
            ]
            .into_iter(),
            root.clone(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(super::run_selfcheck(&args, &selfcheck).unwrap(), 0);
        let report: Value = serde_json::from_slice(&fs::read(&output).unwrap()).unwrap();
        assert_eq!(
            report,
            json!({
                "selfcheck_artifact_id": actual["artifact_id"],
                "selfcheck_tree_sha256": actual["tree_sha256"],
                "selfcheck_matches_bundled": true,
            })
        );
        let copies = format!("dist={}", selfcheck.display());
        let args = parse_args(
            [
                OsString::from("--reconcile"),
                OsString::from("--copy"),
                OsString::from(copies),
                OsString::from("--expect"),
                OsString::from(" dist, "),
                OsString::from("--json-out"),
                output.clone().into_os_string(),
            ]
            .into_iter(),
            root.clone(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(super::run_reconcile(&args).unwrap(), 0);
        let report: Value = serde_json::from_slice(&fs::read(&output).unwrap()).unwrap();
        assert_eq!(report["copies"], json!(["dist"]));
        assert_eq!(report["tree_sha256"], actual["tree_sha256"]);
        let before = fs::read(&output).unwrap();
        fs::write(&selfcheck, "{}").unwrap();
        assert!(super::run_reconcile(&args).is_err());
        assert_eq!(fs::read(&output).unwrap(), before);

        let boot = "[evaluate-failed] Main window failed to start";
        for (evidence, expected_code) in [
            (json!({"error":boot}), 0),
            (
                json!({"error":boot,"runtime":{"external_fetch_completed":true}}),
                1,
            ),
        ] {
            super::write_json(&selfcheck, &evidence).unwrap();
            assert_eq!(super::run_classify(&selfcheck).unwrap(), expected_code);
        }
        super::write_json(&selfcheck, &json!([])).unwrap();
        assert!(
            super::run_classify(&selfcheck)
                .unwrap_err()
                .contains("객체가 아니라")
        );
        fs::write(&selfcheck, "{").unwrap();
        assert!(super::run_classify(&selfcheck).is_err());
        fs::remove_file(&selfcheck).unwrap();
        assert!(super::run_classify(&selfcheck).is_err());
        assert!(super::write_json(&expected.join("blocked.json"), &actual).is_err());
        assert!(super::print_evidence(&actual, Some(&root)).is_err());
        super::print_evidence(&actual, None).unwrap();
        for (raw, normalized) in [
            (r"\\?\UNC\server\share", r"\\server\share"),
            (r"\\?\C:\bundle", r"C:\bundle"),
            ("relative/bundle", "relative/bundle"),
        ] {
            assert_eq!(super::printable_root(&PathBuf::from(raw)), normalized);
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn parser_keeps_distinct_artifact_modes_and_refuses_conflicts() {
        let parse = |words: &[&str]| {
            parse_args(
                words.iter().map(|word| OsString::from(*word)),
                PathBuf::from("repo"),
            )
        };
        let verify = parse(&["--verify", "--repo-root", "other"])
            .unwrap()
            .unwrap();
        assert!(verify.verify);
        assert_eq!(verify.repo, PathBuf::from("other"));
        assert!(parse(&["--help"]).unwrap().is_none());
        let tools = parse(&[
            "--node-command",
            "node",
            "--npm-command",
            "npm",
            "--vite-command",
            "vite",
        ])
        .unwrap()
        .unwrap();
        assert_eq!(tools.node, Some(PathBuf::from("node")));
        assert_eq!(tools.npm, Some(PathBuf::from("npm")));
        assert_eq!(tools.vite, Some(PathBuf::from("vite")));
        for (words, error) in [
            (vec!["--unknown"], "unrecognized argument"),
            (vec!["--repo-root"], "requires a path"),
            (vec!["--repo-root", ""], "requires a path"),
            (vec!["--json-out", "--verify"], "requires a path"),
            (vec!["--copy"], "NAME=PATH"),
            (vec!["--copy", "dist"], "NAME=PATH"),
            (vec!["--copy", "=path"], "NAME=PATH"),
            (vec!["--copy", "dist="], "NAME=PATH"),
            (vec!["--copy", "dist=path"], "require --reconcile"),
            (
                vec!["--bundle-root", "bundle", "--verify"],
                "cannot be combined",
            ),
            (vec!["--reconcile", "--verify"], "cannot be combined"),
            (vec!["--reconcile", "--expect"], "이름이 하나 이상 필요"),
            (
                vec!["--selfcheck-evidence", "file"],
                "requires --expect-identity",
            ),
            (
                vec![
                    "--selfcheck-evidence",
                    "file",
                    "--expect-identity",
                    "expected",
                    "--verify",
                ],
                "no other mode",
            ),
        ] {
            let actual = parse(&words).err().expect("invalid CLI accepted");
            assert!(actual.contains(error), "{words:?}: {actual}");
        }
        let bundle = parse(&["--bundle-root", "bundle"]).unwrap().unwrap();
        assert_eq!(bundle.bundle, Some(PathBuf::from("bundle")));
        let copy = parse(&[
            "--reconcile",
            "--build-metadata",
            "metadata",
            "--copy",
            "dist=a.json",
            "--expect",
            "source,dist",
        ])
        .unwrap()
        .unwrap();
        assert_eq!(copy.build_metadata, Some(PathBuf::from("metadata")));
        assert_eq!(
            parse(&["--verify", "--node-command", "node"])
                .err()
                .as_deref(),
            Some("tool command overrides cannot be used with --verify")
        );
        assert_eq!(
            parse(&["--reconcile", "--copy", "dist=a.json"])
                .err()
                .as_deref(),
            Some("--expect 에는 사본 이름이 하나 이상 필요합니다")
        );
        let reconcile = parse(&["--reconcile", "--copy", "dist=a.json", "--expect", "dist"])
            .unwrap()
            .unwrap();
        assert_eq!(reconcile.copies, [("dist".into(), PathBuf::from("a.json"))]);
        assert_eq!(
            parse(&[
                "--classify-webview",
                "receipt.json",
                "--json-out",
                "out.json"
            ])
            .err()
            .as_deref(),
            Some("--classify-webview takes only its evidence path")
        );
    }
}
