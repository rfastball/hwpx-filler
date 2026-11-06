//! Read coverage.py evidence until the remaining compatibility suite is retired.
//! Remove this adapter with that suite; the LLVM checker remains the native gate.

use super::{Counts, Floor, Policy};
use hwpx_core::xml_view::{Content, XmlView};
use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt::Write as _;
use std::fs;

pub(super) struct ResultRow<'a> {
    name: &'a str,
    floor: &'a Floor,
    counts: Counts,
    missing_lines: BTreeMap<String, Vec<u64>>,
    missing_branches: BTreeMap<String, Vec<u64>>,
}

impl ResultRow<'_> {
    fn line_rate(&self) -> f64 {
        100.0 * self.counts.covered_lines as f64 / self.counts.lines as f64
    }
    fn branch_rate(&self) -> f64 {
        100.0 * self.counts.covered_branches as f64 / self.counts.branches as f64
    }
    pub(super) fn passed(&self) -> bool {
        self.line_rate() >= self.floor.line && self.branch_rate() >= self.floor.branch
    }
}

fn normalize(path: &str) -> String {
    let path = path.replace('\\', "/");
    path.strip_prefix("src/")
        .unwrap_or(&path)
        .trim_end_matches('/')
        .into()
}

fn rows(policy: &Policy) -> Result<BTreeMap<String, ResultRow<'_>>, Box<dyn Error>> {
    if policy.packages.is_empty() {
        return Err("coverage floor policy has no [packages.*] entries".into());
    }
    let mut rows = BTreeMap::new();
    for (name, floor) in &policy.packages {
        let path = normalize(&floor.path);
        if path.is_empty() || rows.contains_key(&path) {
            return Err(format!("duplicate or empty package path: {path:?}").into());
        }
        if !(0.0..=100.0).contains(&floor.line) || !(0.0..=100.0).contains(&floor.branch) {
            return Err(format!("floor outside 0..100: {name}").into());
        }
        if name == "hwpxfiller.host.native" || path == "hwpxfiller/host/native" {
            return Err("hwpxfiller.host.native must use the separate native scenario gate".into());
        }
        rows.insert(
            path,
            ResultRow {
                name,
                floor,
                counts: Counts::default(),
                missing_lines: BTreeMap::new(),
                missing_branches: BTreeMap::new(),
            },
        );
    }
    Ok(rows)
}

fn branch_counts(text: Option<&str>) -> Result<(u64, u64), Box<dyn Error>> {
    let text = text.ok_or("branch line lacks coverage.py condition counts")?;
    let counts = text
        .split_once('(')
        .and_then(|(_, rest)| rest.split_once(')'))
        .map(|(counts, _)| counts)
        .ok_or("branch line lacks coverage.py condition counts")?;
    let (covered, total) = counts
        .split_once('/')
        .ok_or("branch line lacks coverage.py condition counts")?;
    let (covered, total) = (covered.trim().parse::<u64>()?, total.trim().parse::<u64>()?);
    if covered > total {
        return Err("invalid branch evidence: covered exceeds total".into());
    }
    Ok((covered, total))
}

fn record_line(
    view: &XmlView,
    line: hwpx_core::xml_view::NodeId,
    filename: &str,
    row: &mut ResultRow<'_>,
) -> Result<(), Box<dyn Error>> {
    let number = view
        .attr(line, "number")
        .ok_or_else(|| format!("invalid line evidence in {filename}"))?
        .parse::<u64>()?;
    let hits = view.attr(line, "hits").unwrap_or("0").parse::<u64>()?;
    row.counts.lines += 1;
    if hits > 0 {
        row.counts.covered_lines += 1;
    } else {
        row.missing_lines
            .entry(filename.into())
            .or_default()
            .push(number);
    }
    if view.attr(line, "branch") == Some("true") {
        let (covered, total) = branch_counts(view.attr(line, "condition-coverage"))?;
        row.counts.branches += total;
        row.counts.covered_branches += covered;
        if covered < total {
            row.missing_branches
                .entry(filename.into())
                .or_default()
                .push(number);
        }
    }
    Ok(())
}

fn record_class(
    view: &XmlView,
    class: hwpx_core::xml_view::NodeId,
    filename: &str,
    row: &mut ResultRow<'_>,
) -> Result<(), Box<dyn Error>> {
    for part in &view.node(class).unwrap().children {
        let Content::Element(lines) = part else {
            continue;
        };
        if !view.node(*lines).unwrap().name.is("", "lines") {
            continue;
        }
        for part in &view.node(*lines).unwrap().children {
            let Content::Element(line) = part else {
                continue;
            };
            if view.node(*line).unwrap().name.is("", "line") {
                record_line(view, *line, filename, row)?;
            }
        }
    }
    Ok(())
}

pub(super) fn evaluate<'a>(
    source: &[u8],
    policy: &'a Policy,
) -> Result<Vec<ResultRow<'a>>, Box<dyn Error>> {
    let mut results = rows(policy)?;
    let allowed: BTreeSet<_> = policy
        .unmatched_allow
        .iter()
        .map(|path| normalize(path))
        .collect();
    let mut unmatched = BTreeSet::new();
    let view = XmlView::parse(source)?;
    for class in view.descendants(view.root()).unwrap() {
        if !view.node(class).unwrap().name.is("", "class") {
            continue;
        }
        let Some(filename) = view.attr(class, "filename").filter(|name| !name.is_empty()) else {
            continue;
        };
        let normalized = normalize(filename.replace('\\', "/").trim_start_matches(['.', '/']));
        let parent = normalized
            .rsplit_once('/')
            .map_or(".", |(parent, _)| parent);
        let Some(row) = results.get_mut(parent) else {
            if !allowed.contains(parent) {
                unmatched.insert(parent.to_owned());
            }
            continue;
        };
        record_class(&view, class, filename, row)?;
    }
    if !unmatched.is_empty() {
        return Err(format!(
            "source packages without a configured floor (add [packages.*] or unmatched_allow): {}",
            unmatched.into_iter().collect::<Vec<_>>().join(", ")
        )
        .into());
    }
    for row in results.values() {
        if row.counts.lines == 0 {
            return Err(format!("no coverage evidence for package {}", row.name).into());
        }
        if row.counts.branches == 0 {
            return Err(format!("no branch evidence for package {}", row.name).into());
        }
    }
    Ok(results.into_values().collect())
}

fn locations(items: &BTreeMap<String, Vec<u64>>) -> String {
    let mut values: Vec<_> = items
        .iter()
        .flat_map(|(file, lines)| lines.iter().map(move |line| format!("{file}:{line}")))
        .collect();
    if values.is_empty() {
        return "none".into();
    }
    if values.len() > 80 {
        let remaining = values.len() - 80;
        values.truncate(80);
        values.push(format!("… and {remaining} more"));
    }
    values.join(", ")
}

pub(super) fn render(results: &[ResultRow<'_>]) -> String {
    let mut output = "# Package coverage gate\n\nOnly files directly in each package are counted; subpackages are separate surfaces.\n\n| Package | Line | Floor | Branch | Floor | Result |\n|---|---:|---:|---:|---:|:---:|\n".to_owned();
    for row in results {
        writeln!(
            output,
            "| `{}` | {:.2}% ({}/{}) | {}% | {:.2}% ({}/{}) | {}% | {} |",
            row.name,
            row.line_rate(),
            row.counts.covered_lines,
            row.counts.lines,
            row.floor.line,
            row.branch_rate(),
            row.counts.covered_branches,
            row.counts.branches,
            row.floor.branch,
            if row.passed() { "PASS" } else { "FAIL" }
        )
        .unwrap();
    }
    if results.iter().any(|row| !row.passed()) {
        output.push_str("\n## Regressions\n");
        for row in results.iter().filter(|row| !row.passed()) {
            writeln!(
                output,
                "\n### `{}`\n\n- Missing lines: {}\n- Partial/missing branch lines: {}",
                row.name,
                locations(&row.missing_lines),
                locations(&row.missing_branches)
            )
            .unwrap();
        }
    }
    output
}

fn run(args: &[String]) -> Result<i32, Box<dyn Error>> {
    if args.len() != 2 && !(args.len() == 4 && args[2] == "--markdown-output") {
        return Err("usage: check_rust_coverage --coverage-xml POLICY.toml COVERAGE.xml [--markdown-output REPORT.md]".into());
    }
    let policy: Policy = toml::from_str(&fs::read_to_string(&args[0])?)?;
    let source = fs::read(&args[1])?;
    let results = evaluate(&source, &policy)?;
    let report = render(&results);
    if let Some(path) = args.get(3) {
        fs::write(path, &report)?;
    }
    print!("{report}");
    Ok(i32::from(!results.iter().all(ResultRow::passed)))
}

pub(super) fn main(args: &[String]) -> i32 {
    match run(args) {
        Ok(code) => code,
        Err(error) => {
            eprintln!("coverage gate error: {error}");
            2
        }
    }
}
