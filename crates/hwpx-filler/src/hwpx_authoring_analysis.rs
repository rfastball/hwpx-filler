//! Product projection of native HWPX field and structure observations.

use crate::fields::{is_fill_target_field_type, normalize_field_id, python_whitespace};
use crate::hwpx_authoring_reading::{
    cell_path, field_marks, is_hp, native_occurrence_context, paragraph_body, root_anchor,
    simple_field_span, top_paragraphs,
};
use crate::hwpx_product_inspection::{SlotSnapshot, inspect_slot_regions};
use crate::hwpx_structure::scan_structure;
use crate::structure_scan::{CONTEXT_MAX, iter_structure_markers, python_trim};
use hwpx_core::bookmark_region::BookmarkRegion;
use hwpx_core::native_admission::EntryFieldObservation;
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use serde_json::{Value, json};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringAnalysisError(pub String);
impl fmt::Display for AuthoringAnalysisError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringAnalysisError {}

fn iter_text(view: &XmlView, id: NodeId, out: &mut String) {
    for part in &view.node(id).unwrap().children {
        match part {
            Content::Element(child) => iter_text(view, *child, out),
            Content::Text(text) | Content::CData(text) => out.push_str(text),
            Content::Comment(_) | Content::ProcessingInstruction(_) => {}
        }
    }
}

fn raw_field_text(view: &XmlView, field: &EntryFieldObservation) -> String {
    let mut raw = String::new();
    for id in &field.texts {
        iter_text(view, *id, &mut raw);
    }
    raw
}

fn field_row(
    view: &XmlView,
    entry: &str,
    ordinal: usize,
    field: &EntryFieldObservation,
    name: &str,
    reliable: bool,
    marks: &std::collections::HashMap<NodeId, (NodeId, Option<String>)>,
) -> Result<Value, AuthoringAnalysisError> {
    let paragraphs = top_paragraphs(view);
    let mut paragraph = Value::Null;
    let mut anchor = Value::Null;
    let mut position = serde_json::Map::new();
    if let Some(index) = paragraphs.iter().position(|id| *id == field.paragraph) {
        paragraph = json!(index);
        anchor = json!(index);
        if let Some((start, end)) = simple_field_span(view, field) {
            position.insert("start".into(), json!(start));
            position.insert("end".into(), json!(end));
        }
    } else if let Some(path) = cell_path(view, field.paragraph) {
        paragraph = json!(path.last().unwrap().paragraph);
        anchor = json!(path[0].parent_paragraph);
        position.insert("cell_path".into(), json!(path));
        if let Some((start, end)) = simple_field_span(view, field) {
            position.insert("start".into(), json!(start));
            position.insert("end".into(), json!(end));
        }
    } else if let Some(index) = root_anchor(view, field.paragraph) {
        anchor = json!(index);
    }
    let begin = view
        .fragment_xml(field.begin)
        .map_err(|error| AuthoringAnalysisError(error.to_string()))?
        .ok_or_else(|| AuthoringAnalysisError("missing field begin".into()))?;
    let end = view
        .fragment_xml(field.end)
        .map_err(|error| AuthoringAnalysisError(error.to_string()))?
        .ok_or_else(|| AuthoringAnalysisError("missing field end".into()))?;
    let mut paragraph_text = String::new();
    iter_text(view, field.paragraph, &mut paragraph_text);
    let paragraph_text: String = paragraph_text.chars().take(120).collect();
    let mut row = json!({
        "entry": entry,
        "occurrence": ordinal,
        "pairing_id": view.attr(field.begin, "id"),
        "paragraph": paragraph,
        "anchor_paragraph": anchor,
        "paragraph_path": view.path(field.paragraph),
        "reliable": reliable,
        "context": native_occurrence_context(view, field, name, marks),
        "raw": { "begin_xml": begin, "end_xml": end, "value": raw_field_text(view, field), "text": paragraph_text }
    });
    row.as_object_mut().unwrap().extend(position);
    Ok(row)
}

/// Group every fill-target field by normalized product name in content entry order.
pub fn fields(package: &HwpxPackage) -> Result<Vec<Value>, AuthoringAnalysisError> {
    let mut groups: Vec<(String, Vec<Value>)> = Vec::new();
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .ok_or_else(|| AuthoringAnalysisError(format!("missing content entry: {entry}")))?;
        let view = XmlView::parse(&source.data)
            .map_err(|error| AuthoringAnalysisError(error.to_string()))?;
        let scan = view.field_occurrences(entry);
        let marks = field_marks(&scan);
        for (ordinal, field) in scan.fields.iter().enumerate() {
            if !is_fill_target_field_type(field.field_type.as_deref()) {
                continue;
            }
            let Some(name) = field.raw_name.as_deref().and_then(normalize_field_id) else {
                continue;
            };
            let row = field_row(
                &view,
                entry,
                ordinal,
                field,
                &name,
                scan.pairing_usable(),
                &marks,
            )?;
            if let Some((_, rows)) = groups.iter_mut().find(|(id, _)| id == &name) {
                rows.push(row);
            } else {
                groups.push((name, vec![row]));
            }
        }
    }
    Ok(groups
        .into_iter()
        .map(|(name, occurrences)| json!({"name": name, "count": occurrences.len(), "occurrences": occurrences}))
        .collect())
}

fn navigate(location: &Value) -> Value {
    json!({"label": "원문으로 이동", "kind": "navigate", "location": location})
}

fn field_location(view: &XmlView, node: NodeId, entry: &str) -> Option<Value> {
    let mut parent = view.parent(node);
    let paragraph = loop {
        let id = parent?;
        if is_hp(view, id, "p") {
            break id;
        }
        parent = view.parent(id);
    };
    if let Some(index) = top_paragraphs(view).iter().position(|id| *id == paragraph) {
        return Some(json!({"entry": entry, "paragraph": index}));
    }
    let path = cell_path(view, paragraph)?;
    Some(json!({"entry": entry, "paragraph": path.last()?.paragraph, "cell_path": path}))
}

fn field_diagnostic_message(kind: &str) -> (&'static str, &'static str) {
    match kind {
        "unmatched-begin" => ("닫는 필드 경계가 없습니다.", "structure"),
        "orphan-end" => ("여는 필드 경계가 없습니다.", "structure"),
        "ambiguous-end" => ("어느 필드의 닫는 경계인지 확정할 수 없습니다.", "structure"),
        "nested-field" => ("필드가 다른 필드 안에 겹쳐 있습니다.", "structure"),
        "non-native-field-control" => ("지원하지 않는 필드 제어 요소가 있습니다.", "compatibility"),
        "unsupported-control-shape" => (
            "필드 제어 요소의 구조를 확인할 수 없습니다.",
            "compatibility",
        ),
        "unsupported-traversal-lane" => (
            "필드가 편집 가능한 본문 위치에 있지 않습니다.",
            "compatibility",
        ),
        "paragraph-crossing" => ("필드 경계가 여러 문단에 걸쳐 있습니다.", "structure"),
        "unsupported-container-crossing" => (
            "필드 경계가 서로 다른 문서 영역에 걸쳐 있습니다.",
            "compatibility",
        ),
        _ => ("필드 구조를 확인하세요.", "structure"),
    }
}

fn field_diagnostics(package: &HwpxPackage) -> Result<Vec<Value>, AuthoringAnalysisError> {
    let mut rows = Vec::new();
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .unwrap();
        let view = XmlView::parse(&source.data)
            .map_err(|error| AuthoringAnalysisError(error.to_string()))?;
        let scan = view.field_occurrences(entry);
        let nodes = view.descendants(view.root()).unwrap();
        for item in &scan.diagnostics {
            let kind = item.kind.as_str();
            let (message, category) = field_diagnostic_message(kind);
            let location = nodes
                .get(item.order)
                .and_then(|id| field_location(&view, *id, entry))
                .unwrap_or(Value::Null);
            let detail = format!(
                "{}: {} at element {}{}",
                entry,
                kind,
                item.order,
                if item.detail.is_empty() {
                    String::new()
                } else {
                    format!(" ({})", item.detail)
                }
            );
            rows.push(json!({"kind": kind, "message": message, "detail": detail,
                "entry": entry, "order": item.order, "severity": "error", "category": category,
                "target": null, "location": location, "actions": [navigate(&location)]}));
        }
        for (ordinal, field) in scan.fields.iter().enumerate() {
            if !is_fill_target_field_type(field.field_type.as_deref())
                || field
                    .raw_name
                    .as_deref()
                    .and_then(normalize_field_id)
                    .is_some()
            {
                continue;
            }
            let location = field_location(&view, field.begin, entry).unwrap_or(Value::Null);
            let command = json!({"type": "unset_field", "entry": entry, "occurrence": ordinal,
                "pairing_id": view.attr(field.begin, "id"), "text": raw_field_text(&view, field)});
            rows.push(json!({"kind": "invalid-field-id", "message": "필드 이름이 비어 있습니다.",
                "entry": entry, "order": field.begin_order, "severity": "error", "category": "structure",
                "target": null, "location": location,
                "actions": [navigate(&location), {"label": "필드 의미 해제", "kind": "command", "command": command}]}));
        }
    }
    Ok(rows)
}

pub(crate) fn region_location(region: Option<&BookmarkRegion>) -> Value {
    region.map_or(Value::Null, |region| {
        json!({"entry": region.section,
        "start_paragraph": region.start_paragraph, "end_paragraph": region.end_paragraph})
    })
}

fn region_raw(region: Option<&BookmarkRegion>) -> Value {
    region.map_or(Value::Null, |region| {
        json!({"bookmark_name": region.name,
        "meta_tags": region.meta_tags})
    })
}

fn slot_rows(snapshot: &SlotSnapshot) -> Vec<Value> {
    snapshot.slots.iter().map(|slot| {
        let options: Vec<_> = slot.options.iter().map(|option| {
            let region = snapshot.option_regions.get(&(slot.id.clone(), option.id.clone()));
            json!({"id": option.id, "label": option.label.as_deref().unwrap_or(""), "kind": "option",
                "slot_id": slot.id, "location": region_location(region), "raw": region_raw(region)})
        }).collect();
        let region = snapshot.slot_regions.get(&slot.id);
        json!({"id": slot.id, "label": slot.label.as_deref().unwrap_or(""), "kind": "slot",
            "location": region_location(region), "raw": region_raw(region), "options": options})
    }).collect()
}

fn bookmark_target(message: &str) -> Option<(&str, String)> {
    let (entry, rest) = message.split_once(": BOOKMARK ")?;
    let name = rest.strip_prefix('\'')?.split('\'').next()?.to_owned();
    Some((entry, name))
}

fn bookmark_location(
    package: &HwpxPackage,
    message: &str,
) -> Result<Value, AuthoringAnalysisError> {
    let Some((entry, name)) = bookmark_target(message) else {
        return Ok(Value::Null);
    };
    let Some(source) = package.entries.iter().find(|item| item.name == entry) else {
        return Ok(Value::Null);
    };
    let view =
        XmlView::parse(&source.data).map_err(|error| AuthoringAnalysisError(error.to_string()))?;
    let begins: Vec<_> = view
        .descendants(view.root())
        .unwrap()
        .into_iter()
        .filter(|id| {
            is_hp(&view, *id, "fieldBegin")
                && view.attr(*id, "type") == Some("BOOKMARK")
                && view.attr(*id, "name") == Some(name.as_str())
        })
        .collect();
    if begins.len() != 1 {
        return Ok(Value::Null);
    }
    let mut parent = view.parent(begins[0]);
    while let Some(id) = parent {
        if is_hp(&view, id, "p") {
            return Ok(top_paragraphs(&view)
                .iter()
                .position(|item| *item == id)
                .map_or(
                    Value::Null,
                    |index| json!({"entry": entry, "paragraph": index}),
                ));
        }
        parent = view.parent(id);
    }
    Ok(Value::Null)
}

fn structure_context_location(
    package: &HwpxPackage,
    context: &str,
) -> Result<Value, AuthoringAnalysisError> {
    if context.is_empty() {
        return Ok(Value::Null);
    }
    let mut matches = Vec::new();
    for entry in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == entry)
            .unwrap();
        let view = XmlView::parse(&source.data)
            .map_err(|error| AuthoringAnalysisError(error.to_string()))?;
        for paragraph in view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| is_hp(&view, *id, "p"))
        {
            let text: String = python_trim(&paragraph_body(&view, paragraph))
                .chars()
                .take(CONTEXT_MAX)
                .collect();
            if text != context {
                continue;
            }
            if let Some(index) = top_paragraphs(&view).iter().position(|id| *id == paragraph) {
                matches.push(json!({"entry": entry, "paragraph": index}));
            } else if let Some(path) = cell_path(&view, paragraph) {
                matches.push(json!({"entry": entry, "paragraph": path.last().unwrap().paragraph, "cell_path": path}));
            }
        }
    }
    Ok(if matches.len() == 1 {
        matches.remove(0)
    } else {
        Value::Null
    })
}

fn marker_target(context: &str) -> Option<String> {
    let marker = iter_structure_markers(context).into_iter().next()?;
    let parts: Vec<_> = marker
        .body
        .split(python_whitespace)
        .filter(|part| !part.is_empty())
        .collect();
    (parts.len() > 1 && parts[0].starts_with('#')).then(|| parts[1].to_owned())
}

pub fn analyze_hwpx(package: &HwpxPackage) -> Result<Value, AuthoringAnalysisError> {
    let snapshot =
        inspect_slot_regions(package).map_err(|error| AuthoringAnalysisError(error.to_string()))?;
    let structure =
        scan_structure(package).map_err(|error| AuthoringAnalysisError(error.to_string()))?;
    let fields = fields(package)?;
    let mut diagnostics = Vec::new();
    for item in &snapshot.diagnostics {
        let location = bookmark_location(package, &item.message)?;
        let target = bookmark_target(&item.message).map(|(_, name)| name);
        diagnostics.push(json!({"kind": item.kind, "message": item.message, "severity": "error",
            "category": "structure", "target": target, "location": location, "actions": [navigate(&location)]}));
    }
    for item in &structure.diagnostics {
        let location = if let Some(index) = item.index.filter(|_| !item.entry.is_empty()) {
            json!({"entry": item.entry, "paragraph": index})
        } else {
            structure_context_location(package, &item.context)?
        };
        diagnostics.push(
            json!({"kind": item.kind.as_str(), "message": item.message, "context": item.context,
            "severity": "error", "category": "structure", "target": marker_target(&item.context),
            "location": location, "actions": [navigate(&location)]}),
        );
    }
    diagnostics.extend(field_diagnostics(package)?);
    let summary = json!({"slots": snapshot.slots.len(),
        "options": snapshot.slots.iter().map(|slot| slot.options.len()).sum::<usize>(),
        "fields": fields.iter().map(|field| field["count"].as_u64().unwrap_or(0)).sum::<u64>()});
    Ok(
        json!({"fields": fields, "slots": slot_rows(&snapshot), "diagnostics": diagnostics, "summary": summary}),
    )
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn one_field_projects_exact_value_position_and_standalone_raw_xml() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>A</hp:t><hp:ctrl><hp:fieldBegin id='1' name='{{{{고객}}}}' type='CLICK_HERE'/></hp:ctrl></hp:run><hp:run><hp:t>값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl><hp:t>Z</hp:t></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let rows = fields(&package).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["name"], "고객");
        assert_eq!(rows[0]["occurrences"][0]["start"], 1);
        assert_eq!(rows[0]["occurrences"][0]["end"], 2);
        assert_eq!(rows[0]["occurrences"][0]["raw"]["value"], "값");
        assert_eq!(rows[0]["occurrences"][0]["context"], "A[고객]Z");
        let fragment = rows[0]["occurrences"][0]["raw"]["begin_xml"]
            .as_str()
            .unwrap();
        XmlView::parse(fragment.as_bytes()).unwrap();
    }
}
