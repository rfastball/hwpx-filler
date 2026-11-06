//! Enforce the existing exact-package floors against production-only LLVM coverage JSON.

use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

#[path = "check_rust_coverage/xml.rs"]
mod xml;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    #[serde(default)]
    unmatched_allow: Vec<String>,
    packages: BTreeMap<String, Floor>,
    #[serde(default)]
    rust: RustExceptions,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Floor {
    path: String,
    #[serde(default)]
    rust_files: Vec<String>,
    line: f64,
    branch: f64,
}

#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
struct RustExceptions {
    unmeasured_allow: Vec<String>,
}

#[derive(Default)]
struct Counts {
    lines: u64,
    covered_lines: u64,
    branches: u64,
    covered_branches: u64,
}

// These contain only module exports or data struct declarations, so LLVM emits no file record.
// A newly missing executable source still fails; this list is intentionally exact.
const NON_EXECUTABLE_SOURCE: [&str; 4] = [
    "crates/hwpx-core/src/lib.rs",
    "crates/hwpx-filler/src/lib.rs",
    "crates/hwpx-filler/src/slot.rs",
    "crates/hwpx-desktop/src/lib.rs",
];

fn source_files(root: &Path) -> Result<BTreeSet<String>, Box<dyn Error>> {
    fn walk(dir: &Path, root: &Path, result: &mut BTreeSet<String>) -> Result<(), Box<dyn Error>> {
        for entry in fs::read_dir(dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                walk(&path, root, result)?;
            } else if path.extension().is_some_and(|ext| ext == "rs") {
                result.insert(relative(root, &path)?);
            }
        }
        Ok(())
    }
    let mut result = BTreeSet::new();
    for entry in fs::read_dir(root.join("crates"))? {
        let crate_dir = entry?.path();
        if !crate_dir.join("Cargo.toml").is_file() {
            continue;
        }
        walk(&crate_dir.join("src"), root, &mut result)?;
        if crate_dir.join("build.rs").is_file() {
            result.insert(relative(root, &crate_dir.join("build.rs"))?);
        }
    }
    Ok(result)
}

fn relative(root: &Path, path: &Path) -> Result<String, Box<dyn Error>> {
    Ok(path
        .strip_prefix(root)?
        .to_string_lossy()
        .replace('\\', "/"))
}

fn assignments(
    policy: &Policy,
    sources: &BTreeSet<String>,
) -> Result<BTreeMap<String, String>, Box<dyn Error>> {
    if policy.packages.is_empty() || !policy.unmatched_allow.iter().all(|path| !path.is_empty()) {
        return Err("coverage policy package/legacy allowlist is malformed".into());
    }
    let mut assigned = BTreeMap::new();
    for (name, floor) in &policy.packages {
        if floor.path.is_empty()
            || floor.rust_files.is_empty()
            || !floor.line.is_finite()
            || !floor.branch.is_finite()
            || floor.line <= 0.0
            || floor.branch <= 0.0
            || floor.line > 100.0
            || floor.branch > 100.0
        {
            return Err(format!("{name}: missing or invalid package floor").into());
        }
        for file in &floor.rust_files {
            if assigned.insert(file.clone(), name.clone()).is_some() {
                return Err(format!("{file}: duplicate Rust coverage assignment").into());
            }
        }
    }
    for file in &policy.rust.unmeasured_allow {
        if assigned
            .insert(file.clone(), "<native gate>".into())
            .is_some()
        {
            return Err(format!("{file}: measured and exempted simultaneously").into());
        }
    }
    let assigned_files = assigned.keys().cloned().collect::<BTreeSet<_>>();
    let missing = sources.difference(&assigned_files).collect::<Vec<_>>();
    let stale = assigned_files.difference(sources).collect::<Vec<_>>();
    if !missing.is_empty() || !stale.is_empty() {
        return Err(
            format!("Rust coverage inventory drift: missing={missing:?}; stale={stale:?}").into(),
        );
    }
    Ok(assigned)
}

fn measured_counts(
    report: &Value,
    root: &Path,
) -> Result<BTreeMap<String, Counts>, Box<dyn Error>> {
    let files = report["data"]
        .as_array()
        .ok_or("LLVM report has no data")?
        .first()
        .ok_or("LLVM report has no run")?["files"]
        .as_array()
        .ok_or("LLVM report has no files")?;
    let root_prefix = format!("{}/", root.to_string_lossy().replace('\\', "/"));
    let mut result = BTreeMap::new();
    for file in files {
        let filename = file["filename"]
            .as_str()
            .ok_or("LLVM report file has no name")?
            .replace('\\', "/");
        let Some(relative) = filename.strip_prefix(&root_prefix) else {
            continue;
        };
        if !relative.starts_with("crates/") || !relative.ends_with(".rs") {
            continue;
        }
        let count = |kind: &str, key: &str| -> Result<u64, Box<dyn Error>> {
            Ok(file["summary"][kind][key]
                .as_u64()
                .ok_or_else(|| format!("{relative}: missing {kind}.{key}"))?)
        };
        let counts = Counts {
            lines: count("lines", "count")?,
            covered_lines: count("lines", "covered")?,
            branches: count("branches", "count")?,
            covered_branches: count("branches", "covered")?,
        };
        if counts.covered_lines > counts.lines
            || counts.covered_branches > counts.branches
            || result.insert(relative.into(), counts).is_some()
        {
            return Err(format!("{relative}: invalid or duplicate LLVM evidence").into());
        }
    }
    Ok(result)
}

fn run(policy_path: &Path, report_path: &Path) -> Result<(), Box<dyn Error>> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or("crate has no workspace parent")?
        .parent()
        .ok_or("workspace has no parent")?
        .to_path_buf();
    let policy: Policy = toml::from_str(&fs::read_to_string(policy_path)?)?;
    let sources = source_files(&root)?;
    let assigned = assignments(&policy, &sources)?;
    let report: Value = serde_json::from_slice(&fs::read(report_path)?)?;
    let mut measured = measured_counts(&report, &root)?;
    let mut failed = Vec::new();
    for (name, floor) in &policy.packages {
        let mut total = Counts::default();
        for file in &floor.rust_files {
            let count = match measured.remove(file) {
                Some(count) => count,
                None if NON_EXECUTABLE_SOURCE.contains(&file.as_str()) => {
                    let source = fs::read_to_string(root.join(file))?;
                    if source.contains("fn ")
                        || source.contains("impl ")
                        || source.contains("macro_rules!")
                        || source.contains("static ")
                        || source.contains("const ")
                    {
                        return Err(format!(
                            "{name}: {file} acquired executable code without LLVM evidence"
                        )
                        .into());
                    }
                    continue;
                }
                None => return Err(format!("{name}: no LLVM evidence for {file}").into()),
            };
            total.lines += count.lines;
            total.covered_lines += count.covered_lines;
            total.branches += count.branches;
            total.covered_branches += count.covered_branches;
        }
        if total.lines == 0 || total.branches == 0 {
            return Err(format!("{name}: empty line or branch evidence").into());
        }
        let line = 100.0 * total.covered_lines as f64 / total.lines as f64;
        let branch = 100.0 * total.covered_branches as f64 / total.branches as f64;
        println!(
            "{name}: lines {line:.1}% (floor {}%), branches {branch:.1}% (floor {}%)",
            floor.line, floor.branch
        );
        if line < floor.line || branch < floor.branch {
            failed.push(name.as_str());
        }
    }
    for file in measured.keys() {
        if !assigned.contains_key(file) {
            return Err(format!("{file}: LLVM source outside Rust coverage inventory").into());
        }
    }
    if !failed.is_empty() {
        return Err(format!(
            "Rust package coverage below existing floors: {}",
            failed.join(", ")
        )
        .into());
    }
    Ok(())
}

fn main() {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    if args.first().is_some_and(|arg| arg == "--coverage-xml") {
        std::process::exit(xml::main(&args[1..]));
    }
    if args.len() != 2 {
        eprintln!("usage: check_rust_coverage POLICY.toml LLVM.json");
        std::process::exit(2);
    }
    if let Err(error) = run(Path::new(&args[0]), Path::new(&args[1])) {
        eprintln!("Rust coverage gate: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const XML: &str = r#"<coverage><packages><package><classes>
      <class filename="src/hwpxcore/api.py"><lines>
        <line number="10" hits="1" branch="true" condition-coverage="50% (1/2)"/>
        <line number="11" hits="0"/>
      </lines></class>
      <class filename="src/hwpxfiller/host/native/dialogs.py"><lines>
        <line number="20" hits="0" branch="true" condition-coverage="0% (0/8)"/>
      </lines></class>
    </classes></package></packages></coverage>"#;

    fn xml_policy() -> Policy {
        toml::from_str("unmatched_allow = ['src/hwpxfiller/host/native']\n[packages.hwpxcore]\npath = 'src/hwpxcore'\nline = 50\nbranch = 50\n").unwrap()
    }

    #[test]
    fn xml_exact_package_gate_reports_regressions_without_hiding_missing_evidence() {
        let mut policy = xml_policy();
        let rows = xml::evaluate(XML.as_bytes(), &policy).unwrap();
        assert_eq!(rows.len(), 1);
        assert!(rows[0].passed());
        let report = xml::render(&rows);
        assert!(report.contains("50.00% (1/2) | 50% | 50.00% (1/2) | 50% | PASS"));
        policy.packages.get_mut("hwpxcore").unwrap().line = 80.0;
        policy.packages.get_mut("hwpxcore").unwrap().branch = 80.0;
        let rows = xml::evaluate(XML.as_bytes(), &policy).unwrap();
        assert!(!rows[0].passed());
        let report = xml::render(&rows);
        assert!(report.contains("FAIL"));
        assert!(report.contains("Missing lines: src/hwpxcore/api.py:11"));
        assert!(report.contains("branch lines: src/hwpxcore/api.py:10"));
        for (source, phrase) in [
            (
                "<coverage><packages/></coverage>".into(),
                "no coverage evidence",
            ),
            (XML.replace(" branch=\"true\"", ""), "no branch evidence"),
            (
                XML.replace(" condition-coverage=\"50% (1/2)\"", ""),
                "condition counts",
            ),
            (
                XML.replace("50% (1/2)", "150% (3/2)"),
                "invalid branch evidence",
            ),
        ] {
            assert!(
                xml::evaluate(source.as_bytes(), &policy)
                    .err()
                    .unwrap()
                    .to_string()
                    .contains(phrase)
            );
        }
        assert!(xml::evaluate(b"<coverage>", &policy).is_err());
        policy.unmatched_allow.clear();
        assert!(
            xml::evaluate(XML.as_bytes(), &policy)
                .err()
                .unwrap()
                .to_string()
                .contains("without a configured floor")
        );
        policy
            .unmatched_allow
            .push("src/hwpxfiller/host/native".into());
        let floor = policy.packages.get_mut("hwpxcore").unwrap();
        floor.path = "src/hwpxfiller/host/native".into();
        assert!(
            xml::evaluate(XML.as_bytes(), &policy)
                .err()
                .unwrap()
                .to_string()
                .contains("separate native scenario")
        );
        let policy: Policy = toml::from_str(include_str!(
            "../../../tests/contracts/package-coverage-floors.toml"
        ))
        .unwrap();
        assert_eq!(
            policy
                .packages
                .keys()
                .map(String::as_str)
                .collect::<BTreeSet<_>>(),
            BTreeSet::from([
                "hwpxcore",
                "hwpxfiller",
                "hwpxfiller.application",
                "hwpxfiller.data",
                "hwpxfiller.domain",
                "hwpxfiller.domain.field_induction",
                "hwpxfiller.external",
                "hwpxfiller.host",
                "hwpxfiller.viewmodel",
                "hwpxfiller.webapp",
            ])
        );
        assert_eq!(policy.unmatched_allow, ["src/hwpxfiller/host/native"]);
    }

    #[test]
    fn xml_command_writes_report_and_keeps_failure_distinct_from_missing_input() {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let root = repo.join(format!(".cache/xml-coverage-owner-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let policy = root.join("policy.toml");
        let coverage = root.join("coverage.xml");
        let report = root.join("report.md");
        fs::write(&policy, "unmatched_allow = ['src/hwpxfiller/host/native']\n[packages.hwpxcore]\npath = 'src/hwpxcore'\nline = 80\nbranch = 80\n").unwrap();
        fs::write(&coverage, XML).unwrap();
        let args = vec![
            policy.to_str().unwrap().into(),
            coverage.to_str().unwrap().into(),
            "--markdown-output".into(),
            report.to_str().unwrap().into(),
        ];
        assert_eq!(xml::main(&args), 1);
        assert!(fs::read_to_string(&report).unwrap().contains("FAIL"));
        fs::write(
            &policy,
            fs::read_to_string(&policy).unwrap().replace("80", "50"),
        )
        .unwrap();
        assert_eq!(xml::main(&args), 0);
        assert!(fs::read_to_string(&report).unwrap().contains("PASS"));
        fs::remove_file(coverage).unwrap();
        assert_eq!(xml::main(&args), 2);
        assert_eq!(xml::main(&[]), 2);
        assert!(root.canonicalize().unwrap().starts_with(&repo));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejects_duplicate_and_missing_source_assignments() {
        let policy: Policy = toml::from_str(
            "unmatched_allow = []\n[packages.one]\npath = 'old'\nrust_files = ['crates/a/src/lib.rs']\nline = 90\nbranch = 80\n[rust]\nunmeasured_allow = []\n",
        ).unwrap();
        let mut sources = BTreeSet::from(["crates/a/src/lib.rs".into()]);
        assert!(assignments(&policy, &sources).is_ok());
        sources.insert("crates/a/src/new.rs".into());
        assert!(assignments(&policy, &sources).is_err());
        assert!(toml::from_str::<Policy>(
            "unmatched_allow = []\n[packages.one]\npath = 'old'\nrust_files = ['x']\nline = 90\n[rust]\nbranch = 80\nunmeasured_allow = []\n",
        ).is_err());
    }
}
