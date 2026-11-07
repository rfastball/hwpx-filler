//! TXT structure scanning, line projection, and editor token coordinates.

use crate::slot::Slot;
use crate::structure_scan::{
    CONTEXT_MAX, OPTION_KEYWORD, PLACEMENT_OPTION, PLACEMENT_SLOT, SLOT_KEYWORD,
    StructureDiagnostic, StructureDiagnosticKind as K, StructureReader, StructureSummary,
    iter_structure_markers, python_trim, split_structure_marker, structure_marker_name,
};
use crate::text_render::{iter_field_token_matches, template_fields};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const TOKEN_SPAN_FIELD: &str = "field";
pub const TOKEN_SPAN_MARKER: &str = "marker";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextStructurePlacement {
    pub kind: &'static str,
    pub slot_id: String,
    pub option_id: Option<String>,
    pub begin_marker_line: usize,
    pub end_marker_line: usize,
    pub content_start: usize,
    pub content_end: usize,
}

impl TextStructurePlacement {
    pub fn to_dict(&self) -> Value {
        json!({"kind": self.kind, "slot_id": self.slot_id, "option_id": self.option_id,
            "begin_marker_line": self.begin_marker_line, "end_marker_line": self.end_marker_line,
            "content_start": self.content_start, "content_end": self.content_end})
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextStructureScan {
    pub slots: Vec<Slot>,
    pub diagnostics: Vec<StructureDiagnostic>,
    pub summary: StructureSummary,
    pub placements: Vec<TextStructurePlacement>,
}

impl TextStructureScan {
    pub fn to_dict(&self) -> Value {
        json!({
            "slots": self.slots.iter().map(|slot| json!({
                "id": slot.id, "label": slot.label.as_deref().unwrap_or(""),
                "options": slot.options.iter().map(|option| json!({
                    "id": option.id, "label": option.label.as_deref().unwrap_or("")
                })).collect::<Vec<_>>()
            })).collect::<Vec<_>>(),
            "diagnostics": self.diagnostics.iter().map(StructureDiagnostic::to_dict).collect::<Vec<_>>(),
            "summary": self.summary.to_dict(),
            "placements": self.placements.iter().map(TextStructurePlacement::to_dict).collect::<Vec<_>>(),
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextStructureProjectionError(pub String);

impl fmt::Display for TextStructureProjectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TextStructureProjectionError {}

#[derive(Clone, Copy)]
pub(crate) struct Line<'a> {
    pub content: &'a str,
    pub whole: &'a str,
    pub start_char: usize,
}

fn line_separator(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{000b}'
            | '\u{000c}'
            | '\u{001c}'
            | '\u{001d}'
            | '\u{001e}'
            | '\u{0085}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// Python `str.splitlines(keepends=True)` semantics, including Unicode line boundaries.
pub(crate) fn splitlines(text: &str) -> Vec<Line<'_>> {
    let mut lines = Vec::new();
    let mut start_byte = 0;
    let mut start_char = 0;
    let mut char_index = 0;
    let mut iter = text.char_indices().peekable();
    while let Some((offset, c)) = iter.next() {
        char_index += 1;
        if !line_separator(c) {
            continue;
        }
        let content_end = offset;
        let mut end = offset + c.len_utf8();
        if c == '\r' && iter.peek().is_some_and(|(_, next)| *next == '\n') {
            let (_, next) = iter.next().expect("peeked");
            end += next.len_utf8();
            char_index += 1;
        }
        lines.push(Line {
            content: &text[start_byte..content_end],
            whole: &text[start_byte..end],
            start_char,
        });
        start_byte = end;
        start_char = char_index;
    }
    if start_byte < text.len() {
        lines.push(Line {
            content: &text[start_byte..],
            whole: &text[start_byte..],
            start_char,
        });
    }
    lines
}

pub fn scan_text_structure(text: &str) -> TextStructureScan {
    let mut reader = StructureReader::new("파일이");
    for (index, line) in splitlines(text).iter().enumerate() {
        reader.position("", Some(index));
        let context: String = python_trim(line.content)
            .chars()
            .take(CONTEXT_MAX)
            .collect();
        let markers = iter_structure_markers(line.content);
        reader.note_markers(markers.len());
        if markers.is_empty() {
            reader.count_content();
        } else if markers.len() > 1 {
            reader.note(
                K::MarkerNotAlone,
                "한 줄에 구간 마커가 2개 이상입니다 — 마커는 줄을 단독으로 차지해야 합니다.".into(),
                &context,
                None,
            );
        } else {
            let m = &markers[0];
            let residual = format!("{}{}", &line.content[..m.start], &line.content[m.end..]);
            if !python_trim(&residual).is_empty() {
                reader.note(K::MarkerNotAlone,
                    "구간 마커가 다른 텍스트와 같은 줄에 있습니다 — 마커는 줄을 단독으로 차지해야 합니다.".into(),
                    &context, None);
            } else {
                reader.read_marker(m.body, &context);
            }
        }
    }
    reader.close_entry();
    let summary = StructureSummary {
        slots: reader.slots.len(),
        options: reader.slots.iter().map(|s| s.options.len()).sum(),
        fields: template_fields(text).len(),
        markers: reader.markers,
    };
    let placements = reader
        .placements
        .into_iter()
        .map(|p| TextStructurePlacement {
            kind: p.kind,
            slot_id: p.slot_id,
            option_id: p.option_id,
            begin_marker_line: p.begin_index,
            end_marker_line: p.end_index,
            content_start: p.content_start,
            content_end: p.content_end,
        })
        .collect();
    TextStructureScan {
        slots: reader.slots,
        diagnostics: reader.diagnostics,
        summary,
        placements,
    }
}

pub fn marker_lines(scan: &TextStructureScan) -> HashSet<usize> {
    scan.placements
        .iter()
        .flat_map(|p| [p.begin_marker_line, p.end_marker_line])
        .collect()
}

pub fn unselected_option_lines(
    scan: &TextStructureScan,
    selected: &HashMap<String, HashSet<String>>,
) -> HashSet<usize> {
    let mut lines = HashSet::new();
    for place in &scan.placements {
        if place.kind == PLACEMENT_OPTION
            && !selected
                .get(&place.slot_id)
                .is_some_and(|ids| place.option_id.as_ref().is_some_and(|id| ids.contains(id)))
        {
            lines.extend(place.begin_marker_line..=place.end_marker_line);
        }
    }
    lines
}

pub fn drop_lines(text: &str, lines: &HashSet<usize>) -> String {
    splitlines(text)
        .iter()
        .enumerate()
        .filter_map(|(index, line)| (!lines.contains(&index)).then_some(line.whole))
        .collect()
}

pub fn visible_lines(
    text: &str,
    scan: &TextStructureScan,
    selected: &HashMap<String, HashSet<String>>,
) -> Result<Vec<usize>, TextStructureProjectionError> {
    if !scan.diagnostics.is_empty() {
        return Err(TextStructureProjectionError(format!(
            "구간 표기 진단이 {}건 있어 선택을 반영할 수 없다",
            scan.diagnostics.len()
        )));
    }
    let mut hidden = marker_lines(scan);
    hidden.extend(unselected_option_lines(scan, selected));
    Ok((0..splitlines(text).len())
        .filter(|index| !hidden.contains(index))
        .collect())
}

pub fn project_selected_text(
    text: &str,
    scan: &TextStructureScan,
    selected: &HashMap<String, HashSet<String>>,
) -> Result<String, TextStructureProjectionError> {
    let lines = splitlines(text);
    Ok(visible_lines(text, scan, selected)?
        .iter()
        .map(|index| lines[*index].whole)
        .collect())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextTokenSpan {
    pub kind: &'static str,
    pub start: usize,
    pub end: usize,
    pub source: String,
    pub label: String,
    pub region: String,
    pub role: String,
    pub paired: bool,
}

impl TextTokenSpan {
    pub fn to_dict(&self) -> Value {
        if self.kind == TOKEN_SPAN_MARKER {
            json!({"kind": self.kind, "start": self.start, "end": self.end,
                "source": self.source, "label": self.label, "region": self.region,
                "role": self.role, "paired": self.paired})
        } else {
            json!({"kind": self.kind, "start": self.start, "end": self.end,
                "source": self.source, "label": self.label})
        }
    }
}

fn marker_spans(text: &str, scan: &TextStructureScan) -> Vec<TextTokenSpan> {
    let lines = splitlines(text);
    let mut starts = vec![0];
    starts.extend(
        lines
            .iter()
            .map(|line| line.start_char + line.whole.chars().count()),
    );
    let opens: HashMap<_, _> = scan
        .placements
        .iter()
        .map(|p| ((p.kind, p.begin_marker_line), p))
        .collect();
    let closes: HashMap<_, _> = scan
        .placements
        .iter()
        .map(|p| ((p.kind, p.end_marker_line), p))
        .collect();
    let mut named: HashMap<usize, String> = HashMap::new();
    let mut pending = Vec::new();
    for m in iter_structure_markers(text) {
        let (sigil, keyword, tail) = split_structure_marker(m.body);
        let region = match keyword.as_str() {
            SLOT_KEYWORD => PLACEMENT_SLOT,
            OPTION_KEYWORD => PLACEMENT_OPTION,
            _ => "",
        };
        let start = text[..m.start].chars().count();
        let line = starts
            .partition_point(|offset| *offset <= start)
            .saturating_sub(1);
        let role = if sigil == "#" { "open" } else { "close" };
        if role == "open" && !region.is_empty() {
            let (id, label) = structure_marker_name(&tail);
            named.insert(
                line,
                id.map_or(
                    String::new(),
                    |id| if label.is_empty() { id } else { label },
                ),
            );
        }
        pending.push((m, keyword, region, role, line));
    }
    pending
        .into_iter()
        .map(|(m, keyword, region, role, line)| {
            let (label, paired) = if role == "open" {
                (
                    named.get(&line).cloned().unwrap_or_default(),
                    opens.contains_key(&(region, line)),
                )
            } else {
                let place = closes.get(&(region, line));
                let label = place
                    .and_then(|p| named.get(&p.begin_marker_line))
                    .filter(|name| !name.is_empty())
                    .cloned()
                    .unwrap_or_else(|| {
                        if region.is_empty() {
                            String::new()
                        } else {
                            keyword
                        }
                    });
                (label, place.is_some())
            };
            TextTokenSpan {
                kind: TOKEN_SPAN_MARKER,
                start: text[..m.start].chars().count(),
                end: text[..m.end].chars().count(),
                source: m.source.into(),
                label,
                region: region.into(),
                role: role.into(),
                paired,
            }
        })
        .collect()
}

pub fn scan_text_token_spans(text: &str, scan: Option<&TextStructureScan>) -> Vec<TextTokenSpan> {
    let owned;
    let scan = if let Some(scan) = scan {
        scan
    } else {
        owned = scan_text_structure(text);
        &owned
    };
    let mut spans: Vec<_> = iter_field_token_matches(text)
        .into_iter()
        .map(|m| TextTokenSpan {
            kind: TOKEN_SPAN_FIELD,
            start: text[..m.start].chars().count(),
            end: text[..m.end].chars().count(),
            source: m.source.into(),
            label: python_trim(m.body).into(),
            region: String::new(),
            role: String::new(),
            paired: false,
        })
        .collect();
    spans.extend(marker_spans(text, scan));
    spans.sort_by_key(|span| span.start);
    spans
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    fn fixtures() -> Value {
        serde_json::from_str(include_str!("../../../tests/fixtures/structure_scan.json")).unwrap()
    }

    fn assert_scan_fixture(case: &Value) -> TextStructureScan {
        let text = case["text"].as_str().unwrap();
        let scan = scan_text_structure(text);
        assert_eq!(scan.to_dict(), case["scan"], "{}", case["id"]);
        for slot in &scan.slots {
            for (order, option) in slot.options.iter().enumerate() {
                assert_eq!(option.order, order);
            }
        }
        let spans = scan_text_token_spans(text, Some(&scan));
        assert_eq!(
            json!(spans.iter().map(TextTokenSpan::to_dict).collect::<Vec<_>>()),
            case["spans"],
            "{}",
            case["id"]
        );
        assert_eq!(spans, scan_text_token_spans(text, None));
        for span in &spans {
            assert_eq!(
                text.chars()
                    .skip(span.start)
                    .take(span.end - span.start)
                    .collect::<String>(),
                span.source
            );
        }
        assert!(spans.windows(2).all(|pair| pair[0].end <= pair[1].start));
        scan
    }

    fn assert_projection_fixture(case: &Value, scan: &TextStructureScan) {
        let text = case["text"].as_str().unwrap();
        for projection in case["projections"].as_array().unwrap() {
            let selected: HashMap<String, HashSet<String>> =
                serde_json::from_value(projection["selected"].clone()).unwrap();
            let visible = visible_lines(text, scan, &selected).unwrap();
            assert_eq!(json!(visible), projection["visible"], "{}", case["id"]);
            assert_eq!(
                project_selected_text(text, scan, &selected).unwrap(),
                projection["text"].as_str().unwrap()
            );
            let mut hidden = marker_lines(scan);
            hidden.extend(unselected_option_lines(scan, &selected));
            assert_eq!(visible.len() + hidden.len(), splitlines(text).len());
            assert!(visible.iter().all(|line| !hidden.contains(line)));
            if let Some(expected) = projection.get("stage1") {
                let stage1 = drop_lines(text, &unselected_option_lines(scan, &selected));
                assert_eq!(stage1, expected.as_str().unwrap());
                let rescan = scan_text_structure(&stage1);
                assert_eq!(rescan.to_dict(), projection["rescan"]);
                assert!(rescan.diagnostics.is_empty());
                assert!(rescan.summary.markers > 0);
                assert_eq!(
                    drop_lines(&stage1, &marker_lines(&rescan)),
                    projection["text"].as_str().unwrap()
                );
            }
        }
    }

    fn assert_same_declaration_across_media(text: &str) {
        use hwpx_core::package::{HwpxPackage, PackageEntry};
        let paragraphs = text
            .lines()
            .map(|line| format!("<hp:p><hp:run><hp:t>{line}</hp:t></hp:run></hp:p>"))
            .collect::<String>();
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'>{paragraphs}</hs:sec>",
            hwpx_core::text_model::HP_NS
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let text_scan = scan_text_structure(text);
        let hwpx_scan = crate::hwpx_structure::scan_structure(&package).unwrap();
        assert!(text_scan.diagnostics.is_empty() && hwpx_scan.diagnostics.is_empty());
        assert_eq!(text_scan.slots, hwpx_scan.slots);
        assert_eq!(text_scan.summary, hwpx_scan.summary);
        assert_eq!(hwpx_scan.placements[0].entry, "Contents/section0.xml");
        assert_eq!(
            text_scan.placements[0].begin_marker_line,
            hwpx_scan.placements[0].begin_marker_index
        );
    }

    #[test]
    fn scans_selects_and_preserves_crlf_with_codepoint_spans() {
        let fixture = fixtures();
        for case in fixture["text"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|case| case["scan"]["diagnostics"].as_array().unwrap().is_empty())
        {
            let scan = assert_scan_fixture(case);
            assert_projection_fixture(case, &scan);
        }
        assert_same_declaration_across_media(fixture["equivalent"].as_str().unwrap());
        let text = "서문\r\n{{#항목 특약}}\r\n{{#선택 가 이름표}}\r\n💡 {{필드}}\r\n{{/선택}}\r\n{{/항목}}\r\n꼬리";
        let scan = scan_text_structure(text);
        assert!(scan.diagnostics.is_empty(), "{:?}", scan.diagnostics);
        assert_eq!(
            scan.summary,
            StructureSummary {
                slots: 1,
                options: 1,
                fields: 1,
                markers: 4
            }
        );
        assert_eq!(
            scan.placements
                .iter()
                .map(|p| (
                    p.kind,
                    p.begin_marker_line,
                    p.end_marker_line,
                    p.content_start,
                    p.content_end
                ))
                .collect::<Vec<_>>(),
            [(PLACEMENT_SLOT, 1, 5, 3, 3), (PLACEMENT_OPTION, 2, 4, 3, 3)]
        );
        assert_eq!(
            project_selected_text(text, &scan, &HashMap::new()).unwrap(),
            "서문\r\n꼬리"
        );
        let selected = HashMap::from([("특약".into(), HashSet::from(["가".into()]))]);
        assert_eq!(
            project_selected_text(text, &scan, &selected).unwrap(),
            "서문\r\n💡 {{필드}}\r\n꼬리"
        );
        let spans = scan_text_token_spans(text, Some(&scan));
        assert_eq!(spans.len(), 5);
        assert_eq!(spans[2].kind, TOKEN_SPAN_FIELD);
        assert_eq!(spans[2].source, "{{필드}}");
        assert_eq!(
            text.chars()
                .skip(spans[2].start)
                .take(spans[2].end - spans[2].start)
                .collect::<String>(),
            spans[2].source
        );
        assert_eq!(spans[3].label, "이름표");
        assert!(spans[3].paired);
    }

    #[test]
    fn diagnostic_order_and_refusal_are_fail_closed() {
        for case in fixtures()["text"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|case| !case["scan"]["diagnostics"].as_array().unwrap().is_empty())
        {
            let scan = assert_scan_fixture(case);
            let text = case["text"].as_str().unwrap();
            assert!(visible_lines(text, &scan, &HashMap::new()).is_err());
            assert!(project_selected_text(text, &scan, &HashMap::new()).is_err());
        }
        assert_eq!(drop_lines("A\r\nB\u{2028}C", &HashSet::from([1])), "A\r\nC");
    }
}
