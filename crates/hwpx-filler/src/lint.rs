//! Template hygiene findings over schema and authoring token observations.

use crate::authoring::scan_tokens;
use crate::fields::python_whitespace;
use crate::schema::extract_schema;
use crate::schema_drift::similarity;
use hwpx_core::package::HwpxPackage;
use serde::Serialize;
use std::fmt;

pub const DEFAULT_SIMILARITY_THRESHOLD: f64 = 0.8;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct LintFinding {
    pub kind: String,
    pub severity: String,
    pub message: String,
    pub fields: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct LintReport {
    pub findings: Vec<LintFinding>,
}

impl LintReport {
    pub fn has_issues(&self) -> bool {
        self.findings
            .iter()
            .any(|finding| finding.severity == "warning")
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LintError(pub String);
impl fmt::Display for LintError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for LintError {}

fn without_whitespace(name: &str) -> String {
    name.chars().filter(|ch| !python_whitespace(*ch)).collect()
}

pub fn near_duplicate_pairs(names: &[String]) -> Vec<(String, String)> {
    let mut pairs = Vec::new();
    for (at, first) in names.iter().enumerate() {
        for second in names.iter().skip(at + 1) {
            if first != second && without_whitespace(first) == without_whitespace(second) {
                pairs.push((first.clone(), second.clone()));
            }
        }
    }
    pairs
}

fn finding(kind: &str, message: String, fields: Vec<String>) -> LintFinding {
    LintFinding {
        kind: kind.to_owned(),
        severity: "warning".to_owned(),
        message,
        fields,
    }
}

fn vocabulary_findings(
    names: &[String],
    vocabulary: &[String],
    threshold: f64,
) -> Vec<LintFinding> {
    let mut findings = Vec::new();
    for name in names {
        if vocabulary.contains(name) {
            continue;
        }
        let mut best = None;
        let mut best_score = f64::NEG_INFINITY;
        for word in vocabulary {
            let score = similarity(name, word);
            if score > best_score {
                best = Some(word);
                best_score = score;
            }
        }
        let hint = if best_score >= threshold {
            format!(" (가까운 표준: '{}')", best.unwrap())
        } else {
            String::new()
        };
        findings.push(finding(
            "off_vocabulary",
            format!("표준 어휘 밖 필드명: '{name}'{hint}"),
            vec![name.clone()],
        ));
    }
    findings
}

pub fn lint_template(
    package: &HwpxPackage,
    vocabulary: Option<&[String]>,
    threshold: f64,
) -> Result<LintReport, LintError> {
    let schema = extract_schema(package).map_err(|error| LintError(error.to_string()))?;
    let names: Vec<_> = schema
        .fields
        .iter()
        .map(|field| field.name.clone())
        .collect();
    let mut findings = Vec::new();
    if names.is_empty() {
        findings.push(finding(
            "no_fields",
            "템플릿에 누름틀 필드가 없습니다.".to_owned(),
            Vec::new(),
        ));
    }
    for (first, second) in near_duplicate_pairs(&names) {
        findings.push(finding(
            "near_duplicate",
            format!("공백/표기만 다른 필드명: '{first}' vs '{second}'"),
            vec![first, second],
        ));
    }
    for site in scan_tokens(package).map_err(|error| LintError(error.to_string()))? {
        if site.compilable {
            findings.push(finding(
                "stray_token",
                format!("미치환 토큰(누름틀 변환 가능): {{{{{}}}}}", site.name),
                vec![site.name],
            ));
        } else {
            findings.push(finding(
                "split_token",
                format!("수동 처리 필요 토큰: {} ({})", site.name, site.reason),
                vec![site.name],
            ));
        }
    }
    if let Some(vocabulary) = vocabulary.filter(|items| !items.is_empty()) {
        findings.extend(vocabulary_findings(&names, vocabulary, threshold));
    }
    Ok(LintReport { findings })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::PackageEntry;

    fn package(body: &str) -> HwpxPackage {
        HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'>{body}</hs:sec>").into_bytes(),
                stored: false,
            }],
        }
    }

    fn field(name: &str) -> String {
        format!(
            "<hp:p><hp:run><hp:ctrl><hp:fieldBegin name='{name}'/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
        )
    }

    #[test]
    fn lint_distinguishes_substrings_empty_fields_split_tokens_and_vocabulary() {
        let vocabulary = ["계약명".into(), "사업예산".into()];
        for (body, vocab, kinds, hint) in [
            (field("세부품명") + &field("세부품명번호"), None, vec![], false),
            ("<hp:p><hp:run><hp:t>필드 없는 문단</hp:t></hp:run></hp:p>".into(), None, vec!["no_fields"], false),
            ("<hp:p><hp:run><hp:t>{{계약</hp:t></hp:run><hp:run><hp:t>명}}</hp:t></hp:run></hp:p>".into(), None, vec!["no_fields", "split_token"], false),
            (field("계약명세"), Some(vocabulary.as_slice()), vec!["off_vocabulary"], true),
            (field("계약명"), Some(vocabulary.as_slice()), vec![], false),
            (field("수량"), Some(vocabulary.as_slice()), vec!["off_vocabulary"], false),
            (field("수량"), Some([].as_slice()), vec![], false),
        ] {
            let package = package(&body);
            let before = package.clone();
            let report = lint_template(&package, vocab, DEFAULT_SIMILARITY_THRESHOLD).unwrap();
            assert_eq!(report.findings.iter().map(|item| item.kind.as_str()).collect::<Vec<_>>(), kinds, "{body}");
            assert_eq!(report.has_issues(), !kinds.is_empty());
            assert_eq!(report.findings.iter().any(|item| item.message.contains("가까운 표준: '계약명'")), hint);
            assert_eq!(package, before);
        }
    }

    #[test]
    fn lint_keeps_python_finding_order_and_does_not_mutate_source() {
        let xml = "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'><hp:p><hp:run><hp:ctrl><hp:fieldBegin name='계약명'/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p><hp:p><hp:run><hp:ctrl><hp:fieldBegin name='계약 명'/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p><hp:p><hp:run><hp:t>{{미치환}}</hp:t></hp:run></hp:p></hs:sec>";
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.as_bytes().to_vec(),
                stored: false,
            }],
        };
        let before = package.clone();
        let report = lint_template(
            &package,
            Some(&["계약명".into(), "계약명".into()]),
            DEFAULT_SIMILARITY_THRESHOLD,
        )
        .unwrap();
        assert_eq!(package, before);
        assert_eq!(
            report
                .findings
                .iter()
                .map(|item| item.kind.as_str())
                .collect::<Vec<_>>(),
            ["near_duplicate", "stray_token", "off_vocabulary"]
        );
        assert_eq!(report.findings[0].fields, ["계약명", "계약 명"]);
        assert!(report.findings[2].message.contains("가까운 표준: '계약명'"));
        assert!(report.has_issues());
    }
}
