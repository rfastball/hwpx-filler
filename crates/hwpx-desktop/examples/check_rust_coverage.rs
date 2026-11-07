//! Enforce the existing exact-package floors against production-only LLVM coverage JSON.
//!
//! `scripts/rust_coverage.ps1` produces the `llvm-cov export -summary-only` JSON with the test
//! modules compiled out of the measurement (`coverage(off)` under `--cfg coverage_nightly`).

use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    packages: BTreeMap<String, Floor>,
    #[serde(default)]
    rust: RustExceptions,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Floor {
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

#[derive(Clone, Copy, Default)]
struct Counts {
    lines: u64,
    covered_lines: u64,
    branches: u64,
    covered_branches: u64,
}

impl Counts {
    fn add(&mut self, other: Counts) {
        self.lines += other.lines;
        self.covered_lines += other.covered_lines;
        self.branches += other.branches;
        self.covered_branches += other.covered_branches;
    }
    fn line_rate(self) -> f64 {
        100.0 * self.covered_lines as f64 / self.lines as f64
    }
    fn branch_rate(self) -> f64 {
        100.0 * self.covered_branches as f64 / self.branches as f64
    }
    fn missed(self) -> u64 {
        (self.lines - self.covered_lines) + (self.branches - self.covered_branches)
    }
}

struct Row<'a> {
    name: &'a str,
    floor: &'a Floor,
    total: Counts,
    files: Vec<(&'a str, Counts)>,
}

impl Row<'_> {
    fn passed(&self) -> bool {
        self.total.line_rate() >= self.floor.line && self.total.branch_rate() >= self.floor.branch
    }
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

fn floor_is_invalid(floor: &Floor) -> bool {
    floor.rust_files.is_empty()
        || !floor.line.is_finite()
        || !floor.branch.is_finite()
        || floor.line <= 0.0
        || floor.branch <= 0.0
        || floor.line > 100.0
        || floor.branch > 100.0
}

fn assignments(
    policy: &Policy,
    sources: &BTreeSet<String>,
) -> Result<BTreeMap<String, String>, Box<dyn Error>> {
    if policy.packages.is_empty() {
        return Err("coverage policy has no [packages.*] entries".into());
    }
    let mut assigned = BTreeMap::new();
    for (name, floor) in &policy.packages {
        if floor_is_invalid(floor) {
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

/// Confirms a file with no LLVM record is still only module exports or data declarations.
/// Returns `Ok(None)` to keep skipping it, or an error once it has gained executable code.
fn check_non_executable_source(
    root: &Path,
    name: &str,
    file: &str,
) -> Result<Option<Counts>, Box<dyn Error>> {
    let source = fs::read_to_string(root.join(file))?;
    if source.contains("fn ")
        || source.contains("impl ")
        || source.contains("macro_rules!")
        || source.contains("static ")
        || source.contains("const ")
    {
        return Err(
            format!("{name}: {file} acquired executable code without LLVM evidence").into(),
        );
    }
    Ok(None)
}

fn evaluate<'a>(
    policy: &'a Policy,
    root: &Path,
    report: &Value,
) -> Result<Vec<Row<'a>>, Box<dyn Error>> {
    let assigned = assignments(policy, &source_files(root)?)?;
    let mut measured = measured_counts(report, root)?;
    let mut rows = Vec::new();
    for (name, floor) in &policy.packages {
        let mut row = Row {
            name,
            floor,
            total: Counts::default(),
            files: Vec::new(),
        };
        for file in &floor.rust_files {
            let count = match measured.remove(file) {
                Some(count) => Some(count),
                None if NON_EXECUTABLE_SOURCE.contains(&file.as_str()) => {
                    check_non_executable_source(root, name, file)?
                }
                None => return Err(format!("{name}: no LLVM evidence for {file}").into()),
            };
            let Some(count) = count else {
                continue;
            };
            row.total.add(count);
            row.files.push((file, count));
        }
        if row.total.lines == 0 || row.total.branches == 0 {
            return Err(format!("{name}: empty line or branch evidence").into());
        }
        rows.push(row);
    }
    if let Some(file) = measured.keys().find(|file| !assigned.contains_key(*file)) {
        return Err(format!("{file}: LLVM source outside Rust coverage inventory").into());
    }
    Ok(rows)
}

fn render(rows: &[Row<'_>]) -> String {
    let mut output = "# Package coverage gate\n\nProduction-only LLVM coverage of each package's `rust_files` (test modules excluded).\n\n| Package | Line | Floor | Branch | Floor | Result |\n|---|---:|---:|---:|---:|:---:|\n".to_owned();
    for row in rows {
        let total = row.total;
        writeln!(
            output,
            "| `{}` | {:.2}% ({}/{}) | {}% | {:.2}% ({}/{}) | {}% | {} |",
            row.name,
            total.line_rate(),
            total.covered_lines,
            total.lines,
            row.floor.line,
            total.branch_rate(),
            total.covered_branches,
            total.branches,
            row.floor.branch,
            if row.passed() { "PASS" } else { "FAIL" }
        )
        .unwrap();
    }
    if rows.iter().any(|row| !row.passed()) {
        output.push_str("\n## Regressions\n");
        for row in rows.iter().filter(|row| !row.passed()) {
            writeln!(
                output,
                "\n### `{}`\n\nFiles by missed lines + branches:\n\n| File | Missed lines | Missed branches | Line | Branch |\n|---|---:|---:|---:|---:|",
                row.name
            )
            .unwrap();
            let mut files = row
                .files
                .iter()
                .filter(|(_, count)| count.missed() > 0)
                .collect::<Vec<_>>();
            files.sort_by(|a, b| b.1.missed().cmp(&a.1.missed()).then(a.0.cmp(b.0)));
            for (file, count) in files {
                let branch = if count.branches == 0 {
                    "-".to_owned()
                } else {
                    format!("{:.1}%", count.branch_rate())
                };
                writeln!(
                    output,
                    "| `{file}` | {} | {} | {:.1}% | {branch} |",
                    count.lines - count.covered_lines,
                    count.branches - count.covered_branches,
                    count.line_rate(),
                )
                .unwrap();
            }
        }
    }
    output
}

/// Exit 0 when every floor holds, 1 when a floor is missed, 2 when evidence or inventory is invalid.
fn run(root: &Path, args: &[String]) -> Result<i32, Box<dyn Error>> {
    if args.len() != 2 && !(args.len() == 4 && args[2] == "--markdown-output") {
        return Err(
            "usage: check_rust_coverage POLICY.toml LLVM.json [--markdown-output REPORT.md]".into(),
        );
    }
    let policy: Policy = toml::from_str(&fs::read_to_string(&args[0])?)?;
    let report: Value = serde_json::from_slice(&fs::read(&args[1])?)?;
    let rows = evaluate(&policy, root, &report)?;
    let markdown = render(&rows);
    if let Some(path) = args.get(3) {
        fs::write(path, &markdown)?;
    }
    print!("{markdown}");
    let failed = rows
        .iter()
        .filter(|row| !row.passed())
        .map(|row| row.name)
        .collect::<Vec<_>>();
    if failed.is_empty() {
        return Ok(0);
    }
    eprintln!(
        "Rust package coverage below existing floors: {}",
        failed.join(", ")
    );
    Ok(1)
}

fn workspace_root() -> PathBuf {
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .and_then(Path::parent)
        .expect("hwpx-desktop sits two levels below the workspace root")
        .to_path_buf()
}

fn main() {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let code = match run(&workspace_root(), &args) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("Rust coverage gate: {error}");
            2
        }
    };
    std::process::exit(code);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(root: &Path, files: &[(&str, [u64; 4])]) -> String {
        let root = root.to_string_lossy().replace('\\', "/");
        let files = files
            .iter()
            .map(|(file, [lines, covered, branches, covered_branches])| {
                serde_json::json!({
                    "filename": format!("{root}/{file}"),
                    "summary": {
                        "lines": {"count": lines, "covered": covered},
                        "branches": {"count": branches, "covered": covered_branches},
                    },
                })
            })
            .collect::<Vec<_>>();
        serde_json::json!({"data": [{"files": files}]}).to_string()
    }

    #[test]
    fn rejects_duplicate_and_missing_source_assignments() {
        let policy: Policy = toml::from_str(
            "[packages.one]\nrust_files = ['crates/a/src/lib.rs']\nline = 90\nbranch = 80\n[rust]\nunmeasured_allow = []\n",
        ).unwrap();
        let mut sources = BTreeSet::from(["crates/a/src/lib.rs".into()]);
        assert!(assignments(&policy, &sources).is_ok());
        sources.insert("crates/a/src/new.rs".into());
        assert!(assignments(&policy, &sources).is_err());
        for broken in [
            // A floor key in the wrong table is a schema error, not a silently absent floor.
            "[packages.one]\nrust_files = ['x']\nline = 90\n[rust]\nbranch = 80\nunmeasured_allow = []\n",
            // The retired coverage.py keys must not come back unnoticed.
            "unmatched_allow = []\n[packages.one]\nrust_files = ['x']\nline = 90\nbranch = 80\n",
            "[packages.one]\npath = 'src/x'\nrust_files = ['x']\nline = 90\nbranch = 80\n",
        ] {
            assert!(toml::from_str::<Policy>(broken).is_err());
        }
        let duplicate: Policy = toml::from_str(
            "[packages.one]\nrust_files = ['crates/a/src/lib.rs']\nline = 90\nbranch = 80\n[rust]\nunmeasured_allow = ['crates/a/src/lib.rs']\n",
        ).unwrap();
        assert!(assignments(&duplicate, &sources).is_err());
        let zero: Policy =
            toml::from_str("[packages.one]\nrust_files = ['x']\nline = 0\nbranch = 80\n").unwrap();
        assert!(assignments(&zero, &sources).is_err());
    }

    #[test]
    fn ledger_covers_the_workspace_inventory_with_unchanged_package_keys() {
        let root = workspace_root();
        let policy: Policy = toml::from_str(include_str!(
            "../../../tests/contracts/package-coverage-floors.toml"
        ))
        .unwrap();
        assignments(&policy, &source_files(&root).unwrap()).unwrap();
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
    }

    #[test]
    fn command_reports_floor_misses_apart_from_invalid_evidence() {
        let root =
            workspace_root().join(format!(".cache/rust-coverage-owner-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(root.join("crates/a/src")).unwrap();
        fs::write(root.join("crates/a/Cargo.toml"), "").unwrap();
        fs::write(root.join("crates/a/src/lib.rs"), "pub fn a() {}\n").unwrap();
        fs::write(root.join("crates/a/src/b.rs"), "pub fn b() {}\n").unwrap();
        let policy = root.join("policy.toml");
        let llvm = root.join("llvm.json");
        let markdown = root.join("report.md");
        let args = [
            &policy,
            &llvm,
            &PathBuf::from("--markdown-output"),
            &markdown,
        ]
        .map(|path| path.to_string_lossy().into_owned());
        let write_policy = |line: u32| {
            fs::write(
                &policy,
                format!("[packages.one]\nrust_files = ['crates/a/src/lib.rs', 'crates/a/src/b.rs']\nline = {line}\nbranch = 50\n"),
            )
            .unwrap();
        };
        write_policy(75);
        let good = report(
            &root,
            &[
                ("crates/a/src/lib.rs", [4, 4, 2, 1]),
                ("crates/a/src/b.rs", [4, 2, 2, 1]),
            ],
        );
        fs::write(&llvm, &good).unwrap();
        assert_eq!(run(&root, &args).unwrap(), 0);
        let text = fs::read_to_string(&markdown).unwrap();
        assert!(text.contains("| `one` | 75.00% (6/8) | 75% | 50.00% (2/4) | 50% | PASS |"));
        assert!(!text.contains("Regressions"));
        write_policy(80);
        assert_eq!(run(&root, &args).unwrap(), 1);
        let text = fs::read_to_string(&markdown).unwrap();
        assert!(text.contains("FAIL"));
        assert!(text.contains("| `crates/a/src/b.rs` | 2 | 1 | 50.0% | 50.0% |"));
        assert!(
            text.find("crates/a/src/b.rs").unwrap() < text.find("crates/a/src/lib.rs").unwrap()
        );
        write_policy(75);
        for (evidence, phrase) in [
            (
                report(&root, &[("crates/a/src/lib.rs", [4, 4, 2, 1])]),
                "no LLVM evidence for crates/a/src/b.rs",
            ),
            (
                report(
                    &root,
                    &[
                        ("crates/a/src/lib.rs", [4, 4, 0, 0]),
                        ("crates/a/src/b.rs", [4, 2, 0, 0]),
                    ],
                ),
                "empty line or branch evidence",
            ),
            (
                report(
                    &root,
                    &[
                        ("crates/a/src/lib.rs", [4, 5, 2, 1]),
                        ("crates/a/src/b.rs", [4, 2, 2, 1]),
                    ],
                ),
                "invalid or duplicate LLVM evidence",
            ),
            (
                report(
                    &root,
                    &[
                        ("crates/a/src/lib.rs", [4, 4, 2, 1]),
                        ("crates/a/src/b.rs", [4, 2, 2, 1]),
                        ("crates/a/tests/it.rs", [1, 1, 0, 0]),
                    ],
                ),
                "outside Rust coverage inventory",
            ),
            ("{}".into(), "LLVM report has no data"),
        ] {
            fs::write(&llvm, evidence).unwrap();
            let error = run(&root, &args).unwrap_err().to_string();
            assert!(error.contains(phrase), "{error}");
        }
        fs::write(&llvm, &good).unwrap();
        fs::write(root.join("crates/a/src/new.rs"), "pub fn c() {}\n").unwrap();
        let error = run(&root, &args).unwrap_err().to_string();
        assert!(error.contains("inventory drift"), "{error}");
        assert!(
            run(&root, &args[..1])
                .unwrap_err()
                .to_string()
                .contains("usage")
        );
        fs::remove_dir_all(root).unwrap();
    }
}
