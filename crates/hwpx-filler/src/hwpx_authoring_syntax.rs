//! Read-only projection of HWPX meaning into the TXT template grammar.

use crate::fields::{is_fill_target_field_type, normalize_field_id};
use crate::hwpx_authoring_reading::{element_children, is_hp};
use crate::hwpx_product_inspection::inspect_slot_regions;
use crate::hwpx_structure::{begin_marker_text, end_marker_text};
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

const NOTE_TABLE: &str = "표 안의 문단은 소속된 본문 문단 줄에 이어서 표시됩니다.";
const NOTE_BROKEN: &str = "구조 오류가 있어 항목·선택 경계를 표기하지 않았습니다.";
const NOTE_UNWRITABLE_ID: &str = "구간 표기로 되쓸 수 없는 식별자가 있어 해당 경계를 생략했습니다.";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SyntaxViewError(pub String);
impl fmt::Display for SyntaxViewError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for SyntaxViewError {}
fn err(error: impl fmt::Display) -> SyntaxViewError {
    SyntaxViewError(error.to_string())
}

fn first_text(view: &XmlView, id: NodeId) -> String {
    let mut text = String::new();
    if let Some(node) = view.node(id) {
        for child in &node.children {
            match child {
                Content::Text(value) | Content::CData(value) => text.push_str(value),
                _ => break,
            }
        }
    }
    text
}

pub fn syntax_view_hwpx(package: &HwpxPackage) -> Result<Value, SyntaxViewError> {
    let snapshot = inspect_slot_regions(package).map_err(err)?;
    let mut begins: HashMap<(String, usize), Vec<String>> = HashMap::new();
    let mut ends: HashMap<(String, usize), Vec<String>> = HashMap::new();
    let mut notes = Vec::new();
    if !snapshot.diagnostics.is_empty() {
        notes.push(NOTE_BROKEN.to_owned());
    } else {
        for slot in &snapshot.slots {
            let mut members = Vec::new();
            if let Some(region) = snapshot.slot_regions.get(&slot.id) {
                members.push(("slot", slot.id.as_str(), slot.label.as_deref(), region));
            }
            for option in &slot.options {
                if let Some(region) = snapshot
                    .option_regions
                    .get(&(slot.id.clone(), option.id.clone()))
                {
                    members.push((
                        "option",
                        option.id.as_str(),
                        option.label.as_deref(),
                        region,
                    ));
                }
            }
            for (kind, id, label, region) in members {
                let Ok(opening) = begin_marker_text(kind, id, label) else {
                    if !notes.iter().any(|note| note == NOTE_UNWRITABLE_ID) {
                        notes.push(NOTE_UNWRITABLE_ID.into());
                    }
                    continue;
                };
                begins
                    .entry((region.section.clone(), region.start_paragraph))
                    .or_default()
                    .push(opening);
                ends.entry((region.section.clone(), region.end_paragraph))
                    .or_default()
                    .insert(0, end_marker_text(kind).map_err(err)?);
            }
        }
    }
    let mut sections = Vec::new();
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .ok_or_else(|| SyntaxViewError(format!("missing content entry: {entry}")))?;
        let view = XmlView::parse(&source.data).map_err(err)?;
        let scan = view.field_occurrences(entry);
        let mut named = HashMap::new();
        let mut hidden = HashSet::new();
        for field in &scan.fields {
            if !is_fill_target_field_type(field.field_type.as_deref()) {
                continue;
            }
            if let Some(name) = field.raw_name.as_deref().and_then(normalize_field_id) {
                named.insert(field.begin, name);
                hidden.extend(field.texts.iter().copied());
            }
        }
        let mut lines = Vec::new();
        for (index, paragraph) in element_children(&view, view.root())
            .filter(|id| is_hp(&view, *id, "p"))
            .enumerate()
        {
            if view
                .descendants(paragraph)
                .unwrap_or_default()
                .into_iter()
                .any(|id| is_hp(&view, id, "tbl"))
                && !notes.iter().any(|note| note == NOTE_TABLE)
            {
                notes.push(NOTE_TABLE.into());
            }
            lines.extend(
                begins
                    .remove(&(entry.to_owned(), index))
                    .unwrap_or_default(),
            );
            let mut body = String::new();
            for id in view.descendants(paragraph).unwrap_or_default() {
                if let Some(name) = named.get(&id) {
                    body.push_str(&format!("{{{{{name}}}}}"));
                } else if is_hp(&view, id, "t") && !hidden.contains(&id) {
                    body.push_str(&first_text(&view, id));
                }
            }
            lines.push(body);
            lines.extend(ends.remove(&(entry.to_owned(), index)).unwrap_or_default());
        }
        sections.push(json!({"entry":entry,"text":lines.join("\n")}));
    }
    Ok(json!({"sections":sections,"note":if notes.is_empty(){None}else{Some(notes.join(" "))}}))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::syntax_view_hwpx;
    use hwpx_core::package::{HwpxPackage, PackageEntry};
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn field_and_nested_table_text_project_without_changing_entry() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='F'/></hp:ctrl></hp:run><hp:run><hp:t>old</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl><hp:t> 앞 </hp:t><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let before = package.clone();
        let view = syntax_view_hwpx(&package).unwrap();
        assert_eq!(view["sections"][0]["text"], "{{F}} 앞 셀");
        assert_eq!(
            view["note"],
            "표 안의 문단은 소속된 본문 문단 줄에 이어서 표시됩니다."
        );
        assert_eq!(package, before);
    }
}
