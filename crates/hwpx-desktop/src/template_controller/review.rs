//! Template review: per-media detail reading and the lint summary line.

use super::*;
use hwpx_filler::template_library_state::TemplateRow;

/// TXT detail from the template's placeholder fields, or the read failure.
pub(super) fn txt_review_detail(row: &TemplateRow, path: &str, target: &Path) -> Value {
    match read_template(target).and_then(|bytes| {
        String::from_utf8(bytes)
            .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))
    }) {
        Ok(content) => template_txt_detail(&row.name, path, &template_fields(&content), ""),
        Err(error) => template_txt_detail(&row.name, path, &[], &error.to_string()),
    }
}

/// HWPX detail and the package it was read from, or the read failure without a package.
pub(super) fn hwpx_review_detail(
    row: &TemplateRow,
    path: &str,
    target: &Path,
) -> (Value, Option<HwpxPackage>) {
    match read_package(target) {
        Ok(package) => (
            template_hwpx_detail(&row.name, path, &package)
                .unwrap_or_else(|error| failed_detail(row, path, &error)),
            Some(package),
        ),
        Err(error) => (failed_detail(row, path, &error.to_string()), None),
    }
}

/// The lint result line and its level for a readable HWPX template.
pub(super) fn lint_summary(
    target: &Path,
    package: &HwpxPackage,
) -> Result<(String, &'static str), GraphError> {
    let report = lint_template(package, None, DEFAULT_SIMILARITY_THRESHOLD)?;
    if report.findings.is_empty() {
        return Ok((
            format!(
                "검토 {}: 이슈 없음.",
                target.file_name().unwrap().to_string_lossy()
            ),
            "ok",
        ));
    }
    let mut lines = vec![format!(
        "검토 결과 {}:",
        target.file_name().unwrap().to_string_lossy()
    )];
    for finding in report.findings {
        let severity = match finding.severity.as_str() {
            "warning" => "경고",
            "info" => "정보",
            "error" => "오류",
            _ => &finding.severity,
        };
        lines.push(format!("[{severity}] {}", finding.message));
    }
    let level = if lines.iter().any(|line| line.starts_with("[오류]")) {
        "danger"
    } else {
        "warn"
    };
    Ok((lines.join("\n"), level))
}
