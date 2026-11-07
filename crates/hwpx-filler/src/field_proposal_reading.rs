//! Read document paragraphs at the same offsets used by native field creation.

use crate::field_induction::{CellRef, ParagraphText};
use crate::hwpx_authoring_reading::{field_marks, is_hp, paragraph_position, paragraph_sites};
use crate::text_structure::scan_text_token_spans;
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use serde_json::{Value, json};
use std::fmt;

#[derive(Clone, Debug)]
pub struct ProposalReadingError(pub String);
impl fmt::Display for ProposalReadingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ProposalReadingError {}

fn text_of_t(view: &XmlView, id: NodeId) -> String {
    let mut text = String::new();
    if let Some(node) = view.node(id) {
        for part in &node.children {
            match part {
                Content::Text(value) | Content::CData(value) => text.push_str(value),
                Content::Element(child) if is_hp(view, *child, "tab") => text.push('\t'),
                Content::Element(child) if is_hp(view, *child, "lineBreak") => text.push('\n'),
                _ => {}
            }
        }
    }
    text
}
fn walk(
    view: &XmlView,
    paragraph: NodeId,
    marks: &std::collections::HashMap<NodeId, (NodeId, Option<String>)>,
) -> (String, Vec<(usize, usize)>) {
    let mut text = String::new();
    let mut edges = Vec::new();
    let mut length = 0;
    for run in view
        .node(paragraph)
        .into_iter()
        .flat_map(|node| node.children.iter())
        .filter_map(|part| match part {
            Content::Element(id) if is_hp(view, *id, "run") => Some(*id),
            _ => None,
        })
    {
        for child in view
            .node(run)
            .into_iter()
            .flat_map(|node| node.children.iter())
            .filter_map(|part| match part {
                Content::Element(id) => Some(*id),
                _ => None,
            })
        {
            if is_hp(view, child, "t") {
                let value = text_of_t(view, child);
                length += value.chars().count();
                text.push_str(&value);
            } else if is_hp(view, child, "ctrl") {
                for node in view.descendants(child).unwrap_or_default() {
                    if let Some((_, name)) = marks.get(&node) {
                        edges.push((length, name.is_some()));
                    }
                }
            }
        }
    }
    let mut spans = Vec::new();
    let mut inside = None;
    for (at, begin) in edges {
        if !begin && let Some(start) = inside {
            spans.push((start, at));
        }
        inside = begin.then_some(at);
    }
    (text, spans)
}
fn cell_ref(
    entry: &str,
    view: &XmlView,
    paragraph: NodeId,
) -> Result<Option<CellRef>, ProposalReadingError> {
    let Some(sublist) = view.parent(paragraph) else {
        return Ok(None);
    };
    let Some(cell) = view.parent(sublist) else {
        return Ok(None);
    };
    if !is_hp(view, cell, "tc") {
        return Ok(None);
    }
    let mut ancestor = view.parent(cell);
    let mut table = None;
    while let Some(id) = ancestor {
        if is_hp(view, id, "tbl") {
            table = Some(id);
            break;
        }
        ancestor = view.parent(id);
    }
    let Some(table) = table else {
        return Err(ProposalReadingError("table cell has no table".into()));
    };
    let address = view
        .node(cell)
        .into_iter()
        .flat_map(|node| node.children.iter())
        .filter_map(|part| match part {
            Content::Element(id) if is_hp(view, *id, "cellAddr") => Some(*id),
            _ => None,
        })
        .next();
    let span = view
        .node(cell)
        .into_iter()
        .flat_map(|node| node.children.iter())
        .filter_map(|part| match part {
            Content::Element(id) if is_hp(view, *id, "cellSpan") => Some(*id),
            _ => None,
        })
        .next();
    let parse = |id: NodeId, key: &str, default: i64| -> Result<i64, ProposalReadingError> {
        view.attr(id, key).map_or(Ok(default), |raw| {
            raw.parse()
                .map_err(|_| ProposalReadingError(format!("invalid {key} cell coordinate")))
        })
    };
    let (row, col) = if let Some(address) = address {
        (parse(address, "rowAddr", 0)?, parse(address, "colAddr", 0)?)
    } else {
        (-1, -1)
    };
    let (row_span, col_span) = if let Some(span) = span {
        (parse(span, "rowSpan", 1)?, parse(span, "colSpan", 1)?)
    } else {
        (1, 1)
    };
    Ok(Some(CellRef {
        table: format!("{entry}|{}", view.path(table).unwrap_or_default()),
        row,
        col,
        row_span,
        col_span,
    }))
}
pub fn read_hwpx(
    package: &HwpxPackage,
) -> Result<(Vec<ParagraphText>, Vec<Value>), ProposalReadingError> {
    let mut paragraphs = Vec::new();
    let mut places = Vec::new();
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .ok_or_else(|| ProposalReadingError(format!("missing entry {entry}")))?;
        let view = XmlView::parse(&source.data)
            .map_err(|error| ProposalReadingError(error.to_string()))?;
        let scan = view.field_occurrences(entry);
        let marks = field_marks(&scan);
        for paragraph in view
            .descendants(view.root())
            .unwrap_or_default()
            .into_iter()
            .filter(|id| is_hp(&view, *id, "p"))
        {
            let position = paragraph_position(&view, paragraph);
            let (text, field_spans) = walk(&view, paragraph, &marks);
            let sites = paragraph_sites(&view, paragraph, &scan);
            let editable_end = if position.paragraph.is_none() {
                0
            } else {
                sites
                    .hazards
                    .iter()
                    .copied()
                    .min()
                    .unwrap_or(text.chars().count() + 1)
            };
            let key = format!("{entry}|{}", view.path(paragraph).unwrap_or_default());
            paragraphs.push(ParagraphText {
                key,
                text,
                editable_end,
                field_spans,
                cell: cell_ref(entry, &view, paragraph)?,
            });
            places.push(json!({"entry":entry,"paragraph":position.paragraph,"cell_path":position.cell_path}));
        }
    }
    Ok((paragraphs, places))
}
pub fn read_txt(text: &str) -> (Vec<ParagraphText>, Vec<Value>) {
    let tokens: Vec<_> = scan_text_token_spans(text, None)
        .into_iter()
        .map(|span| (span.start, span.end))
        .collect();
    let mut paragraphs = Vec::new();
    let mut places = Vec::new();
    let mut offset = 0;
    for (index, line) in text.split('\n').enumerate() {
        let length = line.chars().count();
        let end = offset + length;
        let spans = tokens
            .iter()
            .filter(|(lo, hi)| *lo < end && offset < *hi)
            .map(|(lo, hi)| (lo.max(&offset) - offset, hi.min(&end) - offset))
            .collect();
        paragraphs.push(ParagraphText {
            key: format!("L{index}"),
            text: line.into(),
            editable_end: length + 1,
            field_spans: spans,
            cell: None,
        });
        places.push(json!({"offset":offset}));
        offset = end + 1;
    }
    (paragraphs, places)
}
pub fn spot_location(media: &str, source: &str, place: &Value, start: usize, end: usize) -> Value {
    if media == "txt" {
        let base = place["offset"].as_u64().unwrap_or(0) as usize;
        let utf16 = |offset: usize| {
            source
                .chars()
                .take(offset)
                .map(char::len_utf16)
                .sum::<usize>()
        };
        json!({"start":utf16(base+start),"end":utf16(base+end)})
    } else {
        let mut location =
            json!({"entry":place["entry"],"paragraph":place["paragraph"],"start":start,"end":end});
        if let Some(cell_path) = place.get("cell_path").filter(|value| !value.is_null()) {
            location["cell_path"] = cell_path.clone();
        }
        location
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::field_induction_proposal::propose;
    use crate::hwpx_authoring_fields::create_field;
    use hwpx_core::package::PackageEntry;

    #[test]
    fn proposal_reader_preserves_utf16_sites_and_excludes_existing_meaning() {
        let source = "😀 보안 장비\n{{#항목 가 가}}\n수요기관: {{기존}} 조달청\n{{/항목}}\n";
        let (paragraphs, places) = read_txt(source);
        assert_eq!(paragraphs[0].text, "😀 보안 장비");
        assert_eq!(paragraphs[1].field_spans, vec![(0, 11)]);
        assert_eq!(paragraphs[2].field_spans, vec![(6, 12)]);
        assert_eq!(
            spot_location("txt", source, &places[0], 2, 7),
            json!({"start":3,"end":8})
        );

        const HP: &str = "http://www.hancom.co.kr/hwpml/2011/paragraph";
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP}'><hp:p><hp:run><hp:secPr/><hp:t>공고명: 장비</hp:t></hp:run></hp:p><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>제한경쟁</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let (paragraphs, places) = read_hwpx(&package).unwrap();
        assert_eq!(paragraphs[0].editable_end, 0);
        assert_eq!(
            paragraphs[2].cell.as_ref().map(|cell| (cell.row, cell.col)),
            Some((-1, -1))
        );
        assert_eq!(places[2]["cell_path"][0]["cell"], 0);
        let location = spot_location("hwpx", "", &places[2], 0, 4);
        assert_eq!(location["cell_path"], places[2]["cell_path"]);
        let original = package.clone();
        let mut created = package.clone();
        let mut command = location;
        command["name"] = json!("계약방법");
        assert_eq!(create_field(&mut created, &command).unwrap(), "제한경쟁");
        let (created_paragraphs, _) = read_hwpx(&created).unwrap();
        assert_eq!(created_paragraphs[2].field_spans, vec![(0, 4)]);
        let values = vec![("계약방법".into(), Some("제한경쟁".into()))];
        let columns = vec!["계약방법".into()];
        assert_eq!(
            propose(&created_paragraphs, &values, &columns, &[], &[], &[]).count("proposal"),
            0
        );
        assert_eq!(package, original);

        let boxed = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP}'><hp:p><hp:run><hp:rect><hp:drawText><hp:subList><hp:p><hp:run><hp:t>공고명: 장비</hp:t></hp:run></hp:p></hp:subList></hp:drawText></hp:rect></hp:run></hp:p></hs:sec>"
        );
        let boxed_package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: boxed.into_bytes(),
                stored: false,
            }],
        };
        let (paragraphs, places) = read_hwpx(&boxed_package).unwrap();
        assert_eq!(paragraphs.len(), 2);
        assert!(
            paragraphs
                .iter()
                .all(|paragraph| paragraph.editable_end == 0)
        );
        assert_eq!(paragraphs[1].text, "공고명: 장비");
        let values = vec![("공고명".into(), Some("장비".into()))];
        let columns = vec!["공고명".into()];
        assert_eq!(
            propose(&paragraphs, &values, &columns, &[], &[], &[]).count("proposal"),
            0
        );
        assert_eq!(
            places[1],
            json!({"entry":"Contents/section0.xml","paragraph":null,"cell_path":null})
        );
    }

    #[test]
    fn every_offered_site_is_accepted_by_the_native_field_coordinate_contract() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{}'><hp:p><hp:run><hp:t>공고명: 장비</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>수요기관: 조달청</hp:t></hp:run></hp:p></hs:sec>",
            hwpx_core::text_model::HP_NS
        );
        let source = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let (paragraphs, places) = read_hwpx(&source).unwrap();
        let values = vec![
            ("공고명".into(), Some("장비".into())),
            ("수요기관".into(), Some("조달청".into())),
        ];
        let columns = vec!["공고명".into(), "수요기관".into()];
        let proposal = propose(&paragraphs, &values, &columns, &[], &[], &[]);
        assert_eq!(proposal.count("proposal"), 2);
        for group in proposal
            .groups
            .iter()
            .filter(|group| group.kind == "proposal")
        {
            for spot in &group.spots {
                let mut command =
                    spot_location("hwpx", "", &places[spot.paragraph], spot.start, spot.end);
                command["name"] = json!(group.name);
                let mut disposable = source.clone();
                assert_eq!(create_field(&mut disposable, &command).unwrap(), spot.text);
            }
        }
        assert_eq!(read_hwpx(&source).unwrap().0, paragraphs);
    }
}
