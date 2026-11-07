//! filename-pattern/v1 parsing, rendering and Windows-safe batch names.

use crate::format_engine::format_datetime_direct;
use crate::python_casefold::python_casefold;
use crate::text_render::python_repr;
use chrono::NaiveDateTime;
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fmt;
use std::sync::LazyLock;

pub const OUTPUT_NAME_PATTERN_INVALID: &str = "OUTPUT_NAME_PATTERN_INVALID";
pub const OUTPUT_PATH_ESCAPE_DETECTED: &str = "OUTPUT_PATH_ESCAPE_DETECTED";
pub const OUTPUT_EXTENSION: &str = ".hwpx";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputNameError {
    pub code: Option<&'static str>,
    pub detail: String,
}
impl fmt::Display for OutputNameError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for OutputNameError {}
fn pattern_error(detail: impl Into<String>) -> OutputNameError {
    OutputNameError {
        code: Some(OUTPUT_NAME_PATTERN_INVALID),
        detail: detail.into(),
    }
}
fn path_error(detail: impl Into<String>) -> OutputNameError {
    OutputNameError {
        code: Some(OUTPUT_PATH_ESCAPE_DETECTED),
        detail: detail.into(),
    }
}
fn runtime_error(detail: impl Into<String>) -> OutputNameError {
    OutputNameError {
        code: None,
        detail: detail.into(),
    }
}
fn repr(value: &str) -> String {
    python_repr(&Value::String(value.into()))
}

fn clean_char(ch: char) -> bool {
    matches!(
        ch,
        '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|' | '\r' | '\n' | '\t'
    )
}
fn forbidden_char(ch: char) -> bool {
    matches!(ch, '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|') || (ch as u32) < 32
}
pub fn clean_filename(name: &str) -> String {
    name.chars()
        .map(|ch| if clean_char(ch) { '_' } else { ch })
        .collect()
}
pub fn has_forbidden_filename_char(name: &str) -> bool {
    name.chars().any(forbidden_char)
}

pub fn format_date_token(
    spec: Option<&str>,
    now: NaiveDateTime,
) -> Result<String, OutputNameError> {
    let mut format = spec
        .filter(|spec| !spec.is_empty())
        .unwrap_or("YYYYMMDD")
        .to_string();
    for (token, directive) in [
        ("YYYY", "%Y"),
        ("YY", "%y"),
        ("MM", "%m"),
        ("DD", "%d"),
        ("HH", "%H"),
        ("mm", "%M"),
        ("SS", "%S"),
    ] {
        format = format.replace(token, directive);
    }
    let text = format_datetime_direct(&format, now)
        .ok_or_else(|| runtime_error("Invalid format string"))?;
    Ok(clean_filename(&text))
}
pub fn format_seq_token(pad: Option<&str>, seq: i64) -> String {
    let width = pad.unwrap_or("").chars().count();
    if width == 0 {
        seq.to_string()
    } else {
        format!("{seq:0width$}")
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PatternToken {
    Literal(String),
    Date(Option<String>),
    Sequence(Option<String>),
    Field(String),
}
pub fn parse_filename_pattern(pattern: &Value) -> Result<Vec<PatternToken>, OutputNameError> {
    let Some(pattern) = pattern.as_str().filter(|value| !value.is_empty()) else {
        return Err(pattern_error("filename pattern 이 비어 있다"));
    };
    let mut tokens = Vec::new();
    let mut literal = String::new();
    let mut index = 0;
    while index < pattern.len() {
        let tail = &pattern[index..];
        if let Some(after_open) = tail.strip_prefix("{{") {
            let Some(close) = after_open.find("}}") else {
                return Err(pattern_error("닫히지 않은 '{{' token"));
            };
            let inner = &after_open[..close];
            if inner.is_empty() || inner.contains(['{', '}']) {
                return Err(pattern_error(format!(
                    "malformed token: {}",
                    repr(&tail[..close + 4])
                )));
            }
            if !literal.is_empty() {
                tokens.push(PatternToken::Literal(std::mem::take(&mut literal)));
            }
            let (head, spec) = inner
                .split_once(':')
                .map_or((inner, None), |(head, spec)| (head, Some(spec.to_owned())));
            tokens.push(match head {
                "date" => PatternToken::Date(spec),
                "seq" => PatternToken::Sequence(spec),
                _ => PatternToken::Field(inner.into()),
            });
            index += close + 4;
        } else {
            let ch = tail.chars().next().expect("nonempty tail");
            literal.push(ch);
            index += ch.len_utf8();
        }
    }
    if !literal.is_empty() {
        tokens.push(PatternToken::Literal(literal));
    }
    Ok(tokens)
}
pub fn pattern_field_token_ids(tokens: &[PatternToken]) -> Vec<String> {
    let mut seen = HashSet::new();
    tokens
        .iter()
        .filter_map(|token| match token {
            PatternToken::Field(id) if seen.insert(id.as_str()) => Some(id.clone()),
            _ => None,
        })
        .collect()
}
static FIELD_TOKEN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\{\{([^{}]+)\}\}").expect("field regex"));
static SEQ_TOKEN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\{\{seq(?::([^}]*))?\}\}").expect("seq regex"));
pub fn pattern_field_tokens(pattern: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    FIELD_TOKEN
        .captures_iter(pattern)
        .filter_map(|capture| {
            let name = capture.get(1)?.as_str();
            if matches!(name.split(':').next(), Some("date" | "seq")) || !seen.insert(name) {
                None
            } else {
                Some(name.into())
            }
        })
        .collect()
}
pub fn pattern_uses_seq(pattern: &str) -> bool {
    SEQ_TOKEN.is_match(pattern)
}
pub fn seq_token_pads(pattern: &str) -> Vec<Option<String>> {
    SEQ_TOKEN
        .captures_iter(pattern)
        .map(|capture| capture.get(1).map(|value| value.as_str().into()))
        .collect()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RenderedNamePart {
    pub kind: &'static str,
    pub field_id: Option<String>,
    pub text: String,
}
pub fn render_output_name(
    tokens: &[PatternToken],
    field_values: &Map<String, Value>,
    seq: i64,
    now: Option<NaiveDateTime>,
    keep_unresolved: bool,
) -> Result<(String, Vec<RenderedNamePart>), OutputNameError> {
    let mut name = String::new();
    let mut resolved = Vec::new();
    for token in tokens {
        match token {
            PatternToken::Literal(text) => name.push_str(text),
            PatternToken::Date(spec) => {
                let now =
                    now.ok_or_else(|| runtime_error("날짜 토큰에는 기준 시각이 필요합니다."))?;
                let text = format_date_token(spec.as_deref(), now)?;
                name.push_str(&text);
                resolved.push(RenderedNamePart {
                    kind: "DATE",
                    field_id: None,
                    text,
                });
            }
            PatternToken::Sequence(pad) => {
                let text = format_seq_token(pad.as_deref(), seq);
                name.push_str(&text);
                resolved.push(RenderedNamePart {
                    kind: "SEQ",
                    field_id: None,
                    text,
                });
            }
            PatternToken::Field(id) => {
                let Some(value) = field_values.get(id) else {
                    if keep_unresolved {
                        name.push_str(&format!("{{{{{id}}}}}"));
                        continue;
                    }
                    return Err(runtime_error(repr(id)));
                };
                let value = match value {
                    Value::String(value) => value.clone(),
                    value => python_repr(value),
                };
                let text = clean_filename(&value);
                name.push_str(&text);
                resolved.push(RenderedNamePart {
                    kind: "FIELD",
                    field_id: Some(id.clone()),
                    text,
                });
            }
        }
    }
    if !name.to_lowercase().ends_with(OUTPUT_EXTENSION) {
        name.push_str(OUTPUT_EXTENSION);
    }
    Ok((name, resolved))
}

pub fn is_reserved_device_name(name: &str) -> bool {
    let head = name
        .split('.')
        .next()
        .unwrap_or("")
        .trim_end_matches([' ', '.'])
        .to_uppercase();
    matches!(head.as_str(), "CON" | "PRN" | "AUX" | "NUL")
        || (head.len() == 4
            && (head.starts_with("COM") || head.starts_with("LPT"))
            && matches!(head.as_bytes()[3], b'1'..=b'9'))
}
pub fn guard_output_name(name: &str) -> Result<(), OutputNameError> {
    if has_forbidden_filename_char(name) {
        return Err(path_error(format!(
            "resolved path 에 경로 구분자/drive/금지문자: {}",
            repr(name)
        )));
    }
    if name == "." || name.starts_with("..") {
        return Err(path_error(format!(
            "resolved path 가 상위 경로 참조: {}",
            repr(name)
        )));
    }
    if name.ends_with(['.', ' ']) {
        return Err(path_error(format!(
            "resolved path 가 점·공백으로 끝난다: {}",
            repr(name)
        )));
    }
    let stem = if name.to_lowercase().ends_with(OUTPUT_EXTENSION) {
        &name[..name.len() - OUTPUT_EXTENSION.len()]
    } else {
        name
    };
    if stem.is_empty() {
        return Err(path_error("resolved path 의 stem 이 비어 있다"));
    }
    if is_reserved_device_name(name) {
        return Err(path_error(format!(
            "resolved path 가 Windows 예약 장치 이름이다: {}",
            repr(name)
        )));
    }
    Ok(())
}
pub fn collision_key(name: &str) -> String {
    python_casefold(name)
}
pub fn dedupe_output_names(base_names: &[String], occupied_names: &[String]) -> Vec<String> {
    let mut seen: HashSet<String> = occupied_names
        .iter()
        .map(|name| collision_key(name))
        .collect();
    let mut result = Vec::with_capacity(base_names.len());
    for name in base_names {
        if seen.insert(collision_key(name)) {
            result.push(name.clone());
            continue;
        }
        let split = name.len().saturating_sub(OUTPUT_EXTENSION.len());
        let (stem, ext) = name.split_at(split);
        let mut number = 1usize;
        loop {
            let candidate = format!("{stem}_{number}{ext}");
            if seen.insert(collision_key(&candidate)) {
                result.push(candidate);
                break;
            }
            number += 1;
        }
    }
    result
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use chrono::Timelike;
    use serde_json::json;

    #[test]
    fn reserved_and_field_tokens_render_before_windows_collision_guard() {
        let pattern =
            parse_filename_pattern(&Value::String("공고-{{date}}-{{seq:001}}-{{이름}}".into()))
                .unwrap();
        let now = chrono::NaiveDate::from_ymd_opt(2026, 11, 5)
            .unwrap()
            .and_hms_opt(1, 2, 3)
            .unwrap();
        let mut fields = Map::new();
        fields.insert("이름".into(), Value::String("A/B".into()));
        let (name, parts) = render_output_name(&pattern, &fields, 2, Some(now), false).unwrap();
        assert_eq!(name, "공고-20261105-002-A_B.hwpx");
        assert_eq!(
            parts.iter().map(|part| part.kind).collect::<Vec<_>>(),
            ["DATE", "SEQ", "FIELD"]
        );
        assert!(guard_output_name(&name).is_ok());
        assert_eq!(
            dedupe_output_names(&["Straße.hwpx".into(), "STRASSE.hwpx".into()], &[])[1],
            "STRASSE_1.hwpx"
        );
        assert_eq!(
            guard_output_name("CON.hwpx").unwrap_err().code,
            Some(OUTPUT_PATH_ESCAPE_DETECTED)
        );
        let precise = now.with_nanosecond(123_456_000).unwrap();
        assert_eq!(
            format_date_token(Some("%f_%#m_%X"), precise).unwrap(),
            "123456_11_01_02_03"
        );
        assert_eq!(
            format_date_token(Some("%c"), precise).unwrap(),
            "Thu Nov  5 01_02_03 2026"
        );
        assert_eq!(
            format_date_token(Some("%q"), precise).unwrap_err().code,
            None
        );
        assert_eq!(format_date_token(None, precise).unwrap(), "20261105");
        assert_eq!(format_seq_token(None, 7), "7");
        assert_eq!(format_seq_token(Some("001"), 7), "007");
        assert_eq!(
            clean_filename("a\\b/c:d*e?f\"g<h>i|j\r\n\tk"),
            "a_b_c_d_e_f_g_h_i_j___k"
        );
        let literal = parse_filename_pattern(&Value::String("a{b}c".into())).unwrap();
        assert_eq!(literal, [PatternToken::Literal("a{b}c".into())]);
        for malformed in ["", "{{이름", "a{{}}b", "{{a{b}}", "x-{{date"] {
            assert_eq!(
                parse_filename_pattern(&Value::String(malformed.into()))
                    .unwrap_err()
                    .code,
                Some(OUTPUT_NAME_PATTERN_INVALID)
            );
        }
        let unresolved = parse_filename_pattern(&Value::String("{{없음}}".into())).unwrap();
        assert!(render_output_name(&unresolved, &Map::new(), 1, Some(now), false).is_err());
        assert_eq!(
            render_output_name(&unresolved, &Map::new(), 1, Some(now), true)
                .unwrap()
                .0,
            "{{없음}}.hwpx"
        );
        let fields = json!({"ID":"A1", "개찰일시":"2026년 6월 15일"});
        for (pattern, expected) in [
            ("공고서-{{ID}}", "공고서-A1.hwpx"),
            ("x.HWPX", "x.HWPX"),
            ("{{ID}}-{{없음}}", "A1-{{없음}}.hwpx"),
            ("공고-{{개찰일시}}", "공고-2026년 6월 15일.hwpx"),
            ("{{date:MM-mm}}", "11-02.hwpx"),
            ("{{seq:00}}", "01.hwpx"),
        ] {
            let tokens = parse_filename_pattern(&json!(pattern)).unwrap();
            assert_eq!(
                render_output_name(&tokens, fields.as_object().unwrap(), 1, Some(now), true)
                    .unwrap()
                    .0,
                expected
            );
        }
        let dated = parse_filename_pattern(&json!("{{date}}")).unwrap();
        assert!(
            render_output_name(&dated, &Map::new(), 1, None, true)
                .unwrap_err()
                .to_string()
                .contains("기준 시각")
        );
        assert_eq!(
            pattern_field_tokens("{{공고명}}-{{date:YYYYMMDD}}-{{seq:001}}-{{공고명}}-{{ID}}"),
            ["공고명", "ID"]
        );
        for (pattern, sequence) in [
            ("고정이름", false),
            ("{{date}}", false),
            ("{{seq}}", true),
            ("{{seq:001}}", true),
        ] {
            assert!(pattern_field_tokens(pattern).is_empty());
            assert_eq!(pattern_uses_seq(pattern), sequence);
        }
    }

    #[test]
    fn windows_name_guard_and_batch_collisions_preserve_user_paths() {
        for name in [
            "../x.hwpx",
            "..x.hwpx",
            "..",
            ".",
            "a/b.hwpx",
            "a\\b.hwpx",
            "C:x.hwpx",
            "x:stream.hwpx",
            "a*b.hwpx",
            "a?b.hwpx",
            "a\"b.hwpx",
            "a<b.hwpx",
            "a>b.hwpx",
            "a|b.hwpx",
            "a\0b.hwpx",
            "a\u{1}b.hwpx",
            ".hwpx",
            ".HWPX",
            "name.",
            "name ",
            "name.hwpx.",
            "name.hwpx ",
            "CON",
            "con.hwpx",
            "Con.hwpx",
            "CON .hwpx",
            "con.backup.hwpx",
            "PRN.hwpx",
            "AUX.hwpx",
            "NUL.hwpx",
            "COM1.hwpx",
            "com9.hwpx",
            "LPT1.hwpx",
            "lpt9.hwpx",
        ] {
            assert_eq!(
                guard_output_name(name).unwrap_err().code,
                Some(OUTPUT_PATH_ESCAPE_DETECTED),
                "{name}"
            );
        }
        for name in [
            "보고서.hwpx",
            "CONSOLE.hwpx",
            "COM10.hwpx",
            "LPT0x.hwpx",
            "a.b.hwpx",
            "name..hwpx",
            "name .hwpx",
            "{{미해소}}.hwpx",
            "x.HWPX",
        ] {
            guard_output_name(name).unwrap();
        }
        assert_eq!(collision_key("Report.HWPX"), collision_key("report.hwpx"));
        assert_eq!(
            dedupe_output_names(&["A.hwpx".into(), "a.hwpx".into(), "b.hwpx".into()], &[]),
            ["A.hwpx", "a_1.hwpx", "b.hwpx"]
        );
        assert_eq!(
            dedupe_output_names(&["Report.hwpx".into()], &["REPORT.hwpx".into()]),
            ["Report_1.hwpx"]
        );
    }

    #[test]
    fn display_audit_uses_the_same_render_and_guard_for_batch_names() {
        use crate::output_name_audit::audit_output_names;
        let now = chrono::NaiveDate::from_ymd_opt(2026, 9, 30)
            .unwrap()
            .and_hms_opt(9, 0, 0)
            .unwrap();
        let cases = [
            (
                "{{ID}}",
                vec![
                    json!({"ID":"Report"}),
                    json!({"ID":"report"}),
                    json!({"ID":"B"}),
                ],
                vec!["Report.hwpx", "report_1.hwpx", "B.hwpx"],
            ),
            (
                "{{date:YYYYMMDD}}-{{seq:001}}-{{ID}}",
                vec![json!({"ID":"x/y"}), json!({"ID":"x/y"})],
                vec!["20260930-001-x_y.hwpx", "20260930-002-x_y.hwpx"],
            ),
            (
                "공고-{{ID}}.HWPX",
                vec![json!({"ID":"a"}), json!({"ID":"A"})],
                vec!["공고-a.HWPX", "공고-A_1.HWPX"],
            ),
            (
                "{{ID}}",
                vec![
                    json!({"ID":"doc_1"}),
                    json!({"ID":"doc"}),
                    json!({"ID":"doc"}),
                ],
                vec!["doc_1.hwpx", "doc.hwpx", "doc_2.hwpx"],
            ),
            (
                "doc-{{seq:001}}",
                vec![json!({}), json!({}), json!({})],
                vec!["doc-001.hwpx", "doc-002.hwpx", "doc-003.hwpx"],
            ),
        ];
        for (pattern, records, expected) in cases {
            let records: Vec<Map<String, Value>> = records
                .into_iter()
                .map(|record| record.as_object().unwrap().clone())
                .collect();
            let audit = audit_output_names(pattern, &records, "", Some(now), None);
            assert_eq!(audit.names, expected, "{pattern}");
            assert!(audit.refusal_code.is_empty());
        }
        for (pattern, value, expected) in [
            ("{{ID", "1", OUTPUT_NAME_PATTERN_INVALID),
            ("../{{ID}}", "1", OUTPUT_PATH_ESCAPE_DETECTED),
            ("{{ID}}", "CON", OUTPUT_PATH_ESCAPE_DETECTED),
            ("C:{{ID}}", "1", OUTPUT_PATH_ESCAPE_DETECTED),
            ("{{ID}}:stream", "1", OUTPUT_PATH_ESCAPE_DETECTED),
            ("con.hwpx", "1", OUTPUT_PATH_ESCAPE_DETECTED),
            ("{{ID}}", "", OUTPUT_PATH_ESCAPE_DETECTED),
        ] {
            let records = vec![json!({"ID":value}).as_object().unwrap().clone()];
            let audit = audit_output_names(pattern, &records, "", Some(now), None);
            assert_eq!(audit.refusal_code, expected);
            assert!(audit.names.is_empty() && audit.converged.is_empty());
        }
        let repeated =
            ["가", "가", "나", "가"].map(|name| json!({"이름":name}).as_object().unwrap().clone());
        let audit = audit_output_names("{{이름}}", &repeated, "", Some(now), None);
        assert_eq!(
            audit.names,
            ["가.hwpx", "가_1.hwpx", "나.hwpx", "가_2.hwpx"]
        );
        assert_eq!(audit.converged, [1, 3]);
        assert!(!audit.has_warning());
        assert!(
            audit_output_names("{{seq:001}}-{{이름}}", &repeated, "", Some(now), None)
                .converged
                .is_empty()
        );
        let case_only = ["Ab", "aB"].map(|name| json!({"이름":name}).as_object().unwrap().clone());
        assert_eq!(
            audit_output_names("{{이름}}", &case_only, "", Some(now), None).converged,
            [1]
        );
        let boundary = [247, 248].map(|length| {
            json!({"이름":"가".repeat(length)})
                .as_object()
                .unwrap()
                .clone()
        });
        let audit = audit_output_names("{{이름}}", &boundary, "C:/out", None, Some(260));
        assert_eq!(audit.too_long, [1]);
        assert!(audit.has_warning());
        assert!(
            audit_output_names("{{이름}}", &boundary, "", None, Some(260))
                .too_long
                .is_empty()
        );
        assert!(
            audit_output_names("{{이름}}", &boundary, "C:/out", None, Some(0))
                .too_long
                .is_empty()
        );
        assert_eq!(
            audit_output_names("{{이름}}", &boundary, "C:/out", None, None).too_long,
            if cfg!(windows) { vec![1] } else { vec![] }
        );
    }
}
