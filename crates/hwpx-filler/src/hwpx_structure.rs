//! HWPX paragraph adapter for the shared product structure grammar.

use crate::authoring::{paragraph_context, paragraph_model_text, scan_tokens};
use crate::fields::{normalize_field_id, python_whitespace};
use crate::slot::Slot;
use crate::structure_scan::{
    CONTEXT_MAX, OPTION_KEYWORD, PLACEMENT_OPTION, PLACEMENT_SLOT, RangePlacement, SLOT_KEYWORD,
    StructureDiagnostic, StructureDiagnosticKind, StructureReader, StructureSummary,
    iter_structure_markers, python_trim,
};
use hwpx_core::package::HwpxPackage;
use hwpx_core::text_model::HP_NS;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructurePlacement {
    pub entry: String,
    pub kind: &'static str,
    pub slot_id: String,
    pub option_id: Option<String>,
    pub begin_marker_index: usize,
    pub end_marker_index: usize,
    pub content_start: usize,
    pub content_end: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureScan {
    pub slots: Vec<Slot>,
    pub diagnostics: Vec<StructureDiagnostic>,
    pub summary: StructureSummary,
    pub placements: Vec<StructurePlacement>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureError(pub String);
impl fmt::Display for StructureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for StructureError {}

fn local(view: &XmlView, id: NodeId) -> &str {
    &view.node(id).unwrap().name.local
}

fn in_table(view: &XmlView, paragraph: NodeId) -> bool {
    let mut current = view.parent(paragraph);
    while let Some(id) = current {
        if local(view, id) == "tbl" {
            return true;
        }
        current = view.parent(id);
    }
    false
}

fn marker_has_object(view: &XmlView, paragraph: NodeId) -> bool {
    view.node(paragraph).unwrap().children.iter().any(|part| {
        let Content::Element(child) = part else {
            return matches!(
                part,
                Content::Comment(_) | Content::ProcessingInstruction(_)
            );
        };
        let node = view.node(*child).unwrap();
        if node.name.namespace == HP_NS && node.name.local == "linesegarray" {
            return false;
        }
        if !node.name.is(HP_NS, "run") {
            return true;
        }
        let mut descendants = vec![*child];
        while let Some(id) = descendants.pop() {
            for part in &view.node(id).unwrap().children {
                match part {
                    Content::Element(next) => {
                        let name = &view.node(*next).unwrap().name;
                        if !name.namespace.eq(HP_NS)
                            || !matches!(name.local.as_str(), "t" | "tab" | "lineBreak")
                        {
                            return true;
                        }
                        descendants.push(*next);
                    }
                    Content::Comment(_) | Content::ProcessingInstruction(_) => return true,
                    Content::Text(_) | Content::CData(_) => {}
                }
            }
        }
        false
    })
}

fn read_paragraph(
    reader: &mut StructureReader,
    view: &XmlView,
    paragraph: NodeId,
    entry: &str,
    top_index: Option<usize>,
) {
    reader.position(entry, top_index);
    let text = paragraph_model_text(view, paragraph);
    let mut context = paragraph_context(view, paragraph);
    let markers = iter_structure_markers(&text);
    reader.note_markers(markers.len());
    if !markers.is_empty() && context.is_empty() {
        context = python_trim(markers[0].source)
            .chars()
            .take(CONTEXT_MAX)
            .collect();
    }
    if markers.is_empty() {
        if top_index.is_some() {
            reader.count_content();
        }
        return;
    }
    if top_index.is_none() {
        let (kind, message) = if in_table(view, paragraph) {
            (
                StructureDiagnosticKind::MarkerInTable,
                "표 셀 안에는 구간 마커를 둘 수 없습니다 — 본문 직계 문단으로 옮기세요.",
            )
        } else {
            (
                StructureDiagnosticKind::MarkerNotTopLevel,
                "본문 직계가 아닌 문단(글상자·중첩 구조 안)의 구간 마커는 인정되지 않습니다.",
            )
        };
        reader.note(kind, message.into(), &context, None);
        return;
    }
    if markers.len() > 1 {
        reader.note(
            StructureDiagnosticKind::MarkerNotAlone,
            "한 문단에 구간 마커가 2개 이상입니다 — 마커는 문단을 단독으로 차지해야 합니다.".into(),
            &context,
            None,
        );
        return;
    }
    let marker = &markers[0];
    if !python_trim(&format!("{}{}", &text[..marker.start], &text[marker.end..])).is_empty() {
        reader.note(
            StructureDiagnosticKind::MarkerNotAlone,
            "구간 마커가 다른 텍스트와 같은 문단에 있습니다 — 마커는 문단을 단독으로 차지해야 합니다."
                .into(),
            &context,
            None,
        );
        reader.settle_refused(marker.body, &context);
        return;
    }
    if marker_has_object(view, paragraph) {
        reader.note(
            StructureDiagnosticKind::MarkerNotAlone,
            "구간 마커가 표·그림 같은 개체와 같은 문단에 있습니다 — 마커를 개체 다음 줄(별도 문단)로 옮기세요."
                .into(),
            &context,
            None,
        );
        reader.settle_refused(marker.body, &context);
        return;
    }
    reader.read_marker(marker.body, &context);
}

fn placement(entry: &str, range: RangePlacement) -> StructurePlacement {
    StructurePlacement {
        entry: entry.into(),
        kind: range.kind,
        slot_id: range.slot_id,
        option_id: range.option_id,
        begin_marker_index: range.begin_index,
        end_marker_index: range.end_index,
        content_start: range.content_start,
        content_end: range.content_end,
    }
}

pub fn scan_structure(package: &HwpxPackage) -> Result<StructureScan, StructureError> {
    let mut reader = StructureReader::new("문서가");
    let mut placements = Vec::new();
    for entry in package.content_xml_names() {
        let old_placements = reader.placements.len();
        let bytes = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .ok_or_else(|| StructureError(format!("content XML 을 찾을 수 없습니다: {entry}")))?;
        let view =
            XmlView::parse(&bytes.data).map_err(|error| StructureError(error.to_string()))?;
        let root = view.root();
        let mut top_index = 0;
        for paragraph in view
            .descendants(root)
            .unwrap()
            .into_iter()
            .filter(|id| view.node(*id).unwrap().name.is(HP_NS, "p"))
        {
            let top_level = view.parent(paragraph) == Some(root);
            read_paragraph(
                &mut reader,
                &view,
                paragraph,
                entry,
                top_level.then_some(top_index),
            );
            if top_level {
                top_index += 1;
            }
        }
        reader.close_entry();
        placements.extend(
            reader.placements[old_placements..]
                .iter()
                .cloned()
                .map(|range| placement(entry, range)),
        );
    }
    let fields = scan_tokens(package)
        .map_err(|error| StructureError(error.to_string()))?
        .into_iter()
        .filter(|site| site.compilable)
        .count();
    let slots = reader.slots;
    let summary = StructureSummary {
        slots: slots.len(),
        options: slots.iter().map(|slot| slot.options.len()).sum(),
        fields,
        markers: reader.markers,
    };
    Ok(StructureScan {
        slots,
        diagnostics: reader.diagnostics,
        summary,
        placements,
    })
}

fn keyword(kind: &str) -> Result<&'static str, StructureError> {
    match kind {
        PLACEMENT_SLOT => Ok(SLOT_KEYWORD),
        PLACEMENT_OPTION => Ok(OPTION_KEYWORD),
        _ => Err(StructureError(format!(
            "알 수 없는 구간 종류입니다: {kind:?}"
        ))),
    }
}

pub fn marker_identifier(raw: &str) -> Result<String, StructureError> {
    let ident = normalize_field_id(raw)
        .ok_or_else(|| StructureError("구간 id 가 비어 있습니다.".into()))?;
    if ident.chars().any(python_whitespace) || ident.contains("{{") || ident.contains("}}") {
        return Err(StructureError(format!(
            "구간 표기로 되쓸 수 없는 id 입니다: {ident:?}"
        )));
    }
    Ok(ident)
}

pub fn marker_label(raw: Option<&str>) -> Result<String, StructureError> {
    let Some(value) = raw else {
        return Ok(String::new());
    };
    if python_trim(value).is_empty() {
        return Ok(String::new());
    }
    let collapsed = value
        .split(python_whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    if collapsed != value || value.contains("{{") || value.contains("}}") {
        return Err(StructureError(format!(
            "구간 표기로 되쓸 수 없는 label 입니다: {value:?}"
        )));
    }
    Ok(value.into())
}

pub fn begin_marker_text(
    kind: &str,
    identifier: &str,
    label: Option<&str>,
) -> Result<String, StructureError> {
    let keyword = keyword(kind)?;
    let ident = marker_identifier(identifier)?;
    let tail = marker_label(label)?;
    Ok(if tail.is_empty() {
        format!("{{{{#{keyword} {ident}}}}}")
    } else {
        format!("{{{{#{keyword} {ident} {tail}}}}}")
    })
}

pub fn end_marker_text(kind: &str) -> Result<String, StructureError> {
    Ok(format!("{{{{/{}}}}}", keyword(kind)?))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::PackageEntry;
    use serde_json::{Value, json};

    fn assert_scan_fixtures() {
        let fixtures: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/structure_scan.json"))
                .unwrap();
        for case in fixtures["hwpx"].as_array().unwrap() {
            let package = HwpxPackage {
                entries: case["sources"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|source| PackageEntry {
                        name: source["name"].as_str().unwrap().into(),
                        data: source["xml"].as_str().unwrap().as_bytes().to_vec(),
                        stored: source["name"] == "mimetype",
                    })
                    .collect(),
            };
            let before = package.clone();
            let scan = scan_structure(&package).unwrap();
            let actual = json!({
                "slots": scan.slots.iter().map(|slot| json!({
                    "id":slot.id, "label":slot.label.as_deref().unwrap_or(""),
                    "options":slot.options.iter().enumerate().map(|(order, option)| {
                        assert_eq!(option.order, order);
                        json!({"id":option.id, "label":option.label.as_deref().unwrap_or("")})
                    }).collect::<Vec<_>>()
                })).collect::<Vec<_>>(),
                "diagnostics":scan.diagnostics.iter().map(StructureDiagnostic::to_dict).collect::<Vec<_>>(),
                "summary":scan.summary.to_dict(),
                "placements":scan.placements.iter().map(|place| json!({
                    "entry":place.entry, "kind":place.kind, "slot_id":place.slot_id, "option_id":place.option_id,
                    "begin_marker_index":place.begin_marker_index, "end_marker_index":place.end_marker_index,
                    "content_start":place.content_start, "content_end":place.content_end,
                })).collect::<Vec<_>>(),
            });
            assert_eq!(actual, case["scan"], "{}", case["id"]);
            let tokens = scan_tokens(&package).unwrap();
            assert_eq!(json!(tokens.iter().map(|token| json!({"name":token.name, "compilable":token.compilable, "reason":token.reason})).collect::<Vec<_>>()), case["tokens"], "{}", case["id"]);
            assert_eq!(package, before);
        }
    }

    #[test]
    fn scans_nested_placement_and_reports_object_covered_marker_without_mutation() {
        assert_scan_fixtures();
        let p = |text: &str| format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>");
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{}{}{}{}{}{}</hs:sec>",
            p("{{#항목 s 제목}}"),
            p("{{#선택 o 선택}}"),
            p("본문"),
            p("{{/선택}}"),
            p("{{/항목}}"),
            "<hp:p><hp:run><hp:t>{{#항목 bad}}</hp:t><hp:tbl/></hp:run></hp:p>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let before = package.clone();
        let scan = scan_structure(&package).unwrap();
        assert_eq!(package, before);
        assert_eq!(scan.slots.len(), 1);
        assert_eq!(scan.slots[0].id, "s");
        assert_eq!(scan.slots[0].options[0].id, "o");
        assert_eq!(scan.summary.markers, 5);
        assert_eq!(scan.placements.len(), 2);
        assert_eq!(scan.placements[0].kind, PLACEMENT_SLOT);
        assert_eq!(scan.placements[0].content_start, 2);
        assert_eq!(scan.placements[1].kind, PLACEMENT_OPTION);
        assert_eq!(scan.placements[1].content_start, 2);
        assert_eq!(scan.diagnostics.len(), 1);
        assert_eq!(
            scan.diagnostics[0].kind,
            StructureDiagnosticKind::MarkerNotAlone
        );
        assert_eq!(
            begin_marker_text(PLACEMENT_SLOT, "s", Some("제목")).unwrap(),
            "{{#항목 s 제목}}"
        );
        assert_eq!(end_marker_text(PLACEMENT_OPTION).unwrap(), "{{/선택}}");
        assert_eq!(end_marker_text(PLACEMENT_SLOT).unwrap(), "{{/항목}}");
        assert_eq!(
            begin_marker_text(PLACEMENT_SLOT, "특약", None).unwrap(),
            "{{#항목 특약}}"
        );
        assert_eq!(
            begin_marker_text(PLACEMENT_OPTION, "지체상금", Some("")).unwrap(),
            "{{#선택 지체상금}}"
        );
        for identifier in ["특약 A", "특약{{", "특약}}", "", "   "] {
            assert!(begin_marker_text(PLACEMENT_SLOT, identifier, None).is_err());
        }
        for label in ["두  칸", "닫는}}괄호", "여는{{괄호"] {
            assert!(
                begin_marker_text(PLACEMENT_SLOT, "특약", Some(label))
                    .unwrap_err()
                    .0
                    .contains("label")
            );
        }
        assert!(
            end_marker_text("field")
                .unwrap_err()
                .0
                .contains("구간 종류")
        );
    }
}
