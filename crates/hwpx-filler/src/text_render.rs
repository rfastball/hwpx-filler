//! Literal-preserving TXT field rendering. Formatting belongs to the mapping profile.

use crate::structure_scan::{TokenMatch, is_structure_sigil, python_trim, token_matches};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

pub const SEG_LITERAL: &str = "literal";
pub const SEG_FILL: &str = "fill";
pub const SEG_BLANK: &str = "blank";
pub const SEG_MISSING: &str = "missing";
pub const FULLWIDTH_SPACE: char = '　';

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RenderReport {
    pub missing_fields: Vec<String>,
    pub empty_fields: Vec<String>,
}

impl RenderReport {
    pub fn has_issues(&self) -> bool {
        !self.missing_fields.is_empty()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RenderSegment {
    pub text: String,
    pub kind: &'static str,
    pub name: String,
}

pub fn iter_field_token_matches(template: &str) -> Vec<TokenMatch<'_>> {
    token_matches(template, false)
        .into_iter()
        .filter(|m| !is_structure_sigil(m.body))
        .collect()
}

pub fn template_fields(template: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    iter_field_token_matches(template)
        .into_iter()
        .map(|m| python_trim(m.body).to_owned())
        .filter(|name| seen.insert(name.clone()))
        .collect()
}

use hwpx_core::structural_boundary::python_string_repr;

fn python_number(raw: &serde_json::Number) -> String {
    let text = raw.to_string();
    if !text.contains(['.', 'e', 'E']) {
        return if text == "-0" { "0".into() } else { text };
    }
    let Some(value) = raw.as_f64() else {
        return text;
    };
    let rendered = format!("{value:?}");
    if let Some((mantissa, exponent)) = rendered.split_once('e') {
        let exponent = exponent.parse::<i32>().unwrap_or(0);
        format!("{mantissa}e{exponent:+03}")
    } else {
        rendered
    }
}

pub fn python_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(v) => if *v { "True" } else { "False" }.into(),
        Value::String(v) => python_string_repr(v),
        Value::Number(v) => python_number(v),
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(python_repr).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(items) => format!(
            "{{{}}}",
            items
                .iter()
                .map(|(key, value)| format!("{}: {}", python_string_repr(key), python_repr(value)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

pub(crate) fn python_value(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(v) => v.clone(),
        _ => python_repr(value),
    }
}

/// Python `str(value)` for JSON-shaped command/metadata values.
pub fn python_str(value: &Value) -> String {
    match value {
        Value::String(value) => value.clone(),
        _ => python_repr(value),
    }
}

pub fn python_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.to_string().parse::<f64>() != Ok(0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn push_literal(segments: &mut Vec<RenderSegment>, chunk: &str) {
    if chunk.is_empty() {
        return;
    }
    if let Some(last) = segments.last_mut()
        && last.kind == SEG_LITERAL
    {
        last.text.push_str(chunk);
        return;
    }
    segments.push(RenderSegment {
        text: chunk.into(),
        kind: SEG_LITERAL,
        name: String::new(),
    });
}

pub fn render_segments(
    template: &str,
    record: &HashMap<String, Value>,
) -> (Vec<RenderSegment>, RenderReport) {
    let mut segments = Vec::new();
    let mut report = RenderReport::default();
    let mut missing = HashSet::new();
    let mut empty = HashSet::new();
    let mut last = 0;
    for m in iter_field_token_matches(template) {
        push_literal(&mut segments, &template[last..m.start]);
        last = m.end;
        let name = python_trim(m.body).to_owned();
        if let Some(raw) = record.get(&name) {
            let value = python_value(raw);
            if python_trim(&value).is_empty() {
                if empty.insert(name.clone()) {
                    report.empty_fields.push(name.clone());
                }
                segments.push(RenderSegment {
                    text: value,
                    kind: SEG_BLANK,
                    name,
                });
            } else {
                segments.push(RenderSegment {
                    text: value,
                    kind: SEG_FILL,
                    name,
                });
            }
        } else {
            if missing.insert(name.clone()) {
                report.missing_fields.push(name.clone());
            }
            segments.push(RenderSegment {
                text: m.source.into(),
                kind: SEG_MISSING,
                name,
            });
        }
    }
    push_literal(&mut segments, &template[last..]);
    (segments, report)
}

pub fn render_record(template: &str, record: &HashMap<String, Value>) -> (String, RenderReport) {
    let (segments, report) = render_segments(template, record);
    (segments.into_iter().map(|s| s.text).collect(), report)
}

pub fn has_space_run(text: &str) -> bool {
    text.as_bytes().windows(2).any(|pair| pair == b"  ")
}

pub fn align_fullwidth(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
    let mut spaces = 0;
    for c in text.chars() {
        if c == ' ' {
            spaces += 1;
            continue;
        }
        if spaces > 0 {
            for _ in 0..spaces / 2 {
                result.push(FULLWIDTH_SPACE);
            }
            if spaces % 2 == 1 {
                result.push(' ');
            }
            spaces = 0;
        }
        result.push(c);
    }
    for _ in 0..spaces / 2 {
        result.push(FULLWIDTH_SPACE);
    }
    if spaces % 2 == 1 {
        result.push(' ');
    }
    result
}

pub fn segments_have_space_run(segments: &[RenderSegment]) -> bool {
    segments
        .iter()
        .any(|s| s.kind == SEG_LITERAL && has_space_run(&s.text))
}

pub fn align_segments(segments: &[RenderSegment]) -> Vec<RenderSegment> {
    segments
        .iter()
        .map(|s| {
            if s.kind == SEG_LITERAL && !s.text.is_empty() {
                RenderSegment {
                    text: align_fullwidth(&s.text),
                    ..s.clone()
                }
            } else {
                s.clone()
            }
        })
        .collect()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    fn assert_segment_boundaries() {
        let record = HashMap::from([
            ("건명".into(), json!("복사용지 구매")),
            ("기한".into(), json!("")),
        ]);
        let template = "1. 건명: {{건명}}\n2. 기한: {{기한}}\n3. 담당: {{담당}}";
        let (segments, report) = render_segments(template, &record);
        assert_eq!(
            segments
                .iter()
                .map(|s| (s.kind, s.text.as_str(), s.name.as_str()))
                .collect::<Vec<_>>(),
            [
                (SEG_LITERAL, "1. 건명: ", ""),
                (SEG_FILL, "복사용지 구매", "건명"),
                (SEG_LITERAL, "\n2. 기한: ", ""),
                (SEG_BLANK, "", "기한"),
                (SEG_LITERAL, "\n3. 담당: ", ""),
                (SEG_MISSING, "{{담당}}", "담당"),
            ]
        );
        assert_eq!(report.missing_fields, ["담당"]);
        assert_eq!(report.empty_fields, ["기한"]);
        let (adjacent, report) = render_segments("{{건명}}{{기한}}{{기한}}", &record);
        assert_eq!(
            adjacent.iter().map(|s| s.kind).collect::<Vec<_>>(),
            [SEG_FILL, SEG_BLANK, SEG_BLANK]
        );
        assert_eq!(report.empty_fields, ["기한"]);
        assert!(!report.has_issues());
        assert_eq!(
            template_fields("{{건명}}{{기한}}{{건명}}"),
            ["건명", "기한"]
        );
        for literal in [
            "",
            "머리말만 있는 문장",
            "{{#선택 가}}\n{{/선택}}",
            "{{금액|amount}}",
        ] {
            let (segments, report) = render_segments(literal, &HashMap::new());
            assert!(template_fields(literal).is_empty());
            assert_eq!(segments.len(), usize::from(!literal.is_empty()));
            assert!(
                segments
                    .iter()
                    .all(|s| s.kind == SEG_LITERAL && s.text == literal && s.name.is_empty())
            );
            assert_eq!(report, RenderReport::default());
            assert_eq!(render_record(literal, &HashMap::new()).0, literal);
        }
        let marked = "{{#항목 특약 특약 사항}}\n본문 {{건명}}\n{{/항목}}";
        let (segments, report) = render_segments(marked, &record);
        assert_eq!(
            segments
                .iter()
                .map(|s| (s.kind, s.text.as_str()))
                .collect::<Vec<_>>(),
            [
                (SEG_LITERAL, "{{#항목 특약 특약 사항}}\n본문 "),
                (SEG_FILL, "복사용지 구매"),
                (SEG_LITERAL, "\n{{/항목}}"),
            ]
        );
        assert_eq!(report, RenderReport::default());
    }

    fn assert_alignment_preserves_data() {
        for (source, expected) in [
            ("건 명", "건 명"),
            ("건   명", "건　 명"),
            ("건    명", "건　　명"),
            ("  둘째 줄   ", "　둘째 줄　 "),
        ] {
            assert_eq!(align_fullwidth(source), expected);
            assert!(!has_space_run(expected));
        }
        for (template, has_alignment) in [
            ("규격: {{규격}}", false),
            ("규    격: {{규격}} / {{빈값}} / {{누락}}", true),
        ] {
            let values = HashMap::from([
                ("규격".into(), json!("12  345")),
                ("빈값".into(), json!("")),
            ]);
            let (segments, _) = render_segments(template, &values);
            assert_eq!(segments_have_space_run(&segments), has_alignment);
            let aligned = align_segments(&segments);
            assert!(!segments_have_space_run(&aligned));
            for (before, after) in segments.iter().zip(&aligned) {
                assert_eq!((before.kind, &before.name), (after.kind, &after.name));
                if before.kind != SEG_LITERAL {
                    assert_eq!(before, after);
                }
            }
            assert!(aligned.iter().any(|s| s.text == "12  345"));
        }
    }

    #[test]
    fn procurement_templates_keep_mapped_formats_and_report_unmapped_source_fields() {
        let draft = include_str!("../../../tests/corpus/scenario/text_templates/온나라기안.txt");
        let summary = include_str!("../../../tests/corpus/scenario/text_templates/게시요약.txt");
        let profile = crate::mapping::MappingProfile::from_dict(
            &serde_json::from_str(include_str!(
                "../../../tests/corpus/scenario/data/나라장터_매핑.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let records = crate::nara::parse(include_bytes!(
            "../../../tests/corpus/scenario/data/나라장터_응답.json"
        ))
        .unwrap();
        let raw = records[0]
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect();
        let mapped = profile.apply(&raw, None).unwrap().into_iter().collect();
        let (text, report) = render_record(draft, &mapped);
        assert!(report.missing_fields.is_empty());
        for phrase in [
            "[입찰공고 게시 요청] 친환경 선박용 소화장비 구매",
            "나. 추정가격 : 45,000,000원",
            "다. 입찰마감 : 2026. 7. 21. 17:00",
            "라. 개찰일시 : 2026. 7. 22. 10:00",
        ] {
            assert!(text.contains(phrase), "{phrase}");
        }
        let (text, report) = render_record(summary, &mapped);
        assert!(text.contains("[입찰공고] 친환경 선박용 소화장비 구매"));
        assert!(text.contains("일반경쟁 / 적격심사"));
        assert!(text.contains("{{입찰방법}}"));
        assert!(report.missing_fields.contains(&"입찰방법".into()));
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/scenario/data/조달_한글.csv");
        let records = crate::data_factory::source_for_path(&path, None, 1)
            .unwrap()
            .records()
            .unwrap();
        let raw = records[2]
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect();
        let (text, report) = render_record(summary, &raw);
        assert!(report.missing_fields.is_empty());
        for phrase in ["항만 CCTV 통합관제 장비 구매", "전자입찰", "108000000"] {
            assert!(text.contains(phrase), "{phrase}");
        }
    }

    #[test]
    fn rendering_preserves_literals_and_reports_ordered_distinct_fields() {
        assert_segment_boundaries();
        assert_alignment_preserves_data();
        let template =
            "{{#항목 특약}}\r\n건    명: {{건명}} / {{미정}} / {{미정}} / {{빈값}} / {{x|amount}}";
        let record = HashMap::from([
            ("건명".into(), json!("전산장비  구매")),
            ("빈값".into(), Value::Null),
        ]);
        assert_eq!(template_fields(template), ["건명", "미정", "빈값"]);
        let (segments, report) = render_segments(template, &record);
        assert_eq!(report.missing_fields, ["미정"]);
        assert_eq!(report.empty_fields, ["빈값"]);
        assert!(report.has_issues());
        let joined: String = segments.iter().map(|s| s.text.as_str()).collect();
        assert!(joined.contains("{{#항목 특약}}\r\n건    명: 전산장비  구매"));
        assert!(joined.ends_with("{{x|amount}}"));
        assert_eq!(render_record(template, &record).0, joined);
        assert!(segments_have_space_run(&segments));
        let aligned = align_segments(&segments);
        assert!(!segments_have_space_run(&aligned));
        assert!(
            aligned
                .iter()
                .any(|s| s.kind == SEG_FILL && s.text == "전산장비  구매")
        );
        let record = HashMap::from([("복합".into(), json!({"a": [true, null, "x"]}))]);
        assert_eq!(
            render_record("{{복합}}", &record).0,
            "{'a': [True, None, 'x']}"
        );
    }
}
