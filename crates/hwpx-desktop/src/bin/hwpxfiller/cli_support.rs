//! CLI argument classification and command-dispatch helpers factored out of
//! `hwpxfiller.rs` purely to keep its units under the complexity/statement budget.
//! No behavior lives here that didn't already live in the parent module.

use super::Command;
use hwpx_filler::authoring::{compile_document, scan_tokens};
use hwpx_filler::lint::{DEFAULT_SIMILARITY_THRESHOLD, lint_template};
use std::ffi::OsString;
use std::path::{Path, PathBuf};

pub(super) enum SchemaToken<'a> {
    PositionalMarker,
    Help,
    OutFlag,
    OutInline(&'a str),
    Unsupported,
    Positional,
}

/// Matches the flag-like forms of a `schema` argument, honoring `positional_only`.
/// Returns `None` when `arg` is not one of these (including once positional-only mode
/// is on, since every one of these requires `!positional_only`).
pub(super) fn classify_schema_flag(
    arg: &OsString,
    positional_only: bool,
) -> Option<SchemaToken<'_>> {
    if positional_only {
        return None;
    }
    if arg == "--" {
        return Some(SchemaToken::PositionalMarker);
    }
    if arg == "--help" || arg == "-h" {
        return Some(SchemaToken::Help);
    }
    if arg == "--out" {
        return Some(SchemaToken::OutFlag);
    }
    if let Some(path) = arg.to_str().and_then(|s| s.strip_prefix("--out=")) {
        return Some(SchemaToken::OutInline(path));
    }
    None
}

/// Decides whether a non-flag argument is the (single) template path or an
/// unsupported extra argument.
pub(super) fn classify_schema_positional(
    arg: &OsString,
    positional_only: bool,
    has_template: bool,
) -> SchemaToken<'_> {
    if (!positional_only && arg != "-" && arg.to_string_lossy().starts_with('-')) || has_template {
        SchemaToken::Unsupported
    } else {
        SchemaToken::Positional
    }
}

/// Prints the matching guidance and returns the exit code when `records` is empty or
/// `record_number` falls outside its 1-based range; `None` means the record is valid.
pub(super) fn validate_record_range(records_len: usize, record_number: usize) -> Option<u8> {
    if records_len == 0 {
        eprintln!("데이터에 레코드가 없습니다.");
        return Some(1);
    }
    if record_number == 0 || record_number > records_len {
        eprintln!("--record {record_number} 범위 밖(1..{records_len}).");
        return Some(1);
    }
    None
}

fn cmd_fieldize(template: &Path, out: Option<PathBuf>) -> Result<u8, String> {
    let mut package = super::read_package(template)?;
    if let Some(path) = out {
        let report = compile_document(&mut package, None).map_err(|err| err.to_string())?;
        for site in &report.skipped {
            eprintln!("  [건너뜀] {} — {}", site.name, site.reason);
        }
        if !report.modified {
            super::print_lines(["변환할 토큰이 없습니다(이미 누름틀이거나 토큰 없음).".into()])?;
            return Ok(0);
        }
        let bytes = package.to_bytes().map_err(|err| err.to_string())?;
        super::write_bytes_atomic(&path, &bytes)
            .map_err(|err| format!("파일을 읽거나 쓸 수 없습니다: {} — {err}", path.display()))?;
        super::print_lines([format!(
            "누름틀 변환 완료: 필드 {}개 -> {}",
            report.compiled.len(),
            path.display()
        )])?;
    } else {
        let sites = scan_tokens(&package).map_err(|err| err.to_string())?;
        let compilable: Vec<_> = sites.iter().filter(|site| site.compilable).collect();
        let skipped: Vec<_> = sites.iter().filter(|site| !site.compilable).collect();
        super::print_lines([format!(
            "[미리보기] 변환 가능 {}개 / 건너뜀 {}개",
            compilable.len(),
            skipped.len()
        )])?;
        for site in compilable {
            super::print_lines([format!("  + {}  ({})", site.name, site.context)])?;
        }
        for site in skipped {
            eprintln!("  ! {}  — {}", site.name, site.reason);
        }
        super::print_lines(["실제 변환하려면 --out <경로> 를 지정하세요.".into()])?;
    }
    Ok(0)
}

/// Handles the commands that need only the template/data paths they already carry,
/// with no further CLI-level routing: `Fieldize`, `Lint`, `RetiredDiff`, `Drift`, `Render`.
pub(super) fn run_tooling(command: Command) -> Result<u8, String> {
    match command {
        Command::Fieldize { template, out } => cmd_fieldize(&template, out),
        Command::Lint { template, vocab } => {
            let package = super::read_package(&template)?;
            let vocabulary = vocab.as_deref().map(super::read_vocabulary).transpose()?;
            let report = lint_template(
                &package,
                vocabulary.as_deref(),
                DEFAULT_SIMILARITY_THRESHOLD,
            )
            .map_err(|err| err.to_string())?;
            if report.findings.is_empty() {
                super::print_lines(["이슈 없음.".into()])?;
            } else {
                super::print_lines(report.findings.iter().map(|finding| {
                    format!(
                        "  [{}] {}: {}",
                        finding.severity, finding.kind, finding.message
                    )
                }))?;
            }
            Ok(u8::from(report.has_issues()))
        }
        Command::RetiredDiff => {
            eprintln!(
                "diff 는 별도 제품 hwpxdiff 입니다: hwpxdiff OLD.hwpx NEW.hwpx [--html out.html]\n  설치: https://github.com/rfastball/hwpx-diff"
            );
            Ok(2)
        }
        Command::Drift { old, new } => {
            super::print_lines(super::drift_lines(&old, &new)?).map(|()| 0)
        }
        Command::Render {
            template,
            data,
            profile,
            record,
            sheet,
            out,
            clip,
        } => super::render_text(
            &template,
            &data,
            profile.as_deref(),
            record,
            sheet.as_deref(),
            out.as_deref(),
            clip,
        ),
        _ => unreachable!("run already handled the other Command variants"),
    }
}
