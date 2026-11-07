//! Native HWPX authoring search and selection readback.

use crate::authoring::paragraph_model_text;
use crate::fields::normalize_field_id;
use crate::hwpx_authoring_analysis::analyze_hwpx;
use crate::hwpx_authoring_reading::{
    CellStep, PARAGRAPH_UNRESOLVED, ParagraphPosition, body_hit_context, body_hit_parts, field_marks,
    field_range_refusal, is_hp, paragraph_body, paragraph_pieces, paragraph_position,
    paragraph_sites, root_anchor, selected_paragraph, top_paragraphs,
};
use crate::hwpx_product_inspection::inspect_slot_regions;
pub use crate::python_casefold::python_casefold;
use crate::schema::extract_schema;
use crate::structure_scan::python_trim;
use hwpx_core::package::HwpxPackage;
use hwpx_core::structural_boundary::python_string_repr;
use hwpx_core::xml_view::{NodeId, XmlView};
use regex::RegexBuilder;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringSearchError(pub String);
impl fmt::Display for AuthoringSearchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringSearchError {}

fn source<'a>(package: &'a HwpxPackage, entry: &str) -> Result<&'a [u8], AuthoringSearchError> {
    package
        .entries
        .iter()
        .find(|item| item.name == entry)
        .map(|item| item.data.as_slice())
        .ok_or_else(|| AuthoringSearchError(format!("missing content entry: {entry}")))
}

fn field_hits(package: &HwpxPackage, query: &str) -> Result<Vec<Value>, AuthoringSearchError> {
    let analysis =
        analyze_hwpx(package).map_err(|error| AuthoringSearchError(error.to_string()))?;
    let needle = python_casefold(query);
    let mut hits = Vec::new();
    for field in analysis["fields"].as_array().unwrap() {
        let name = field["name"].as_str().unwrap();
        if !python_casefold(name).contains(&needle) {
            continue;
        }
        for occurrence in field["occurrences"].as_array().unwrap() {
            let mut hit = occurrence.clone();
            let object = hit.as_object_mut().unwrap();
            object.insert("kind".into(), json!("field"));
            object.insert("name".into(), json!(name));
            hits.push(hit);
        }
    }
    Ok(hits)
}

fn structure_hits(package: &HwpxPackage, query: &str) -> Result<Vec<Value>, AuthoringSearchError> {
    let snapshot =
        inspect_slot_regions(package).map_err(|error| AuthoringSearchError(error.to_string()))?;
    let needle = python_casefold(query);
    let mut hits = Vec::new();
    for slot in &snapshot.slots {
        let region = snapshot
            .slot_regions
            .get(&slot.id)
            .ok_or_else(|| AuthoringSearchError(python_string_repr(&slot.id)))?;
        if python_casefold(&format!(
            "{} {}",
            slot.id,
            slot.label.as_deref().unwrap_or("")
        ))
        .contains(&needle)
        {
            hits.push(json!({"kind": "slot", "slot_id": slot.id,
                "label": slot.label.as_deref().unwrap_or(&slot.id), "entry": region.section,
                "start_paragraph": region.start_paragraph, "end_paragraph": region.end_paragraph}));
        }
        for option in &slot.options {
            let region = snapshot
                .option_regions
                .get(&(slot.id.clone(), option.id.clone()))
                .ok_or_else(|| {
                    AuthoringSearchError(format!(
                        "({}, {})",
                        python_string_repr(&slot.id),
                        python_string_repr(&option.id)
                    ))
                })?;
            if python_casefold(&format!(
                "{} {}",
                option.id,
                option.label.as_deref().unwrap_or("")
            ))
            .contains(&needle)
            {
                hits.push(json!({"kind": "option", "slot_id": slot.id, "option_id": option.id,
                    "label": option.label.as_deref().unwrap_or(&option.id), "entry": region.section,
                    "start_paragraph": region.start_paragraph, "end_paragraph": region.end_paragraph}));
            }
        }
    }
    Ok(hits)
}

pub fn literal_ignorecase_ranges(
    source: &str,
    query: &str,
) -> Result<Vec<(usize, usize)>, AuthoringSearchError> {
    let mut literal = String::new();
    for ch in query.chars() {
        match ch {
            'i' | 'I' | 'İ' | 'ı' => literal.push_str("[iIİı]"),
            's' | 'S' | 'ſ' => literal.push_str("[sSſ]"),
            'k' | 'K' | 'K' => literal.push_str("[kKK]"),
            _ => literal.push_str(&regex::escape(&ch.to_string())),
        }
    }
    let pattern = RegexBuilder::new(&literal)
        .case_insensitive(true)
        .build()
        .map_err(|error| AuthoringSearchError(error.to_string()))?;
    Ok(pattern
        .find_iter(source)
        .map(|found| (found.start(), found.end()))
        .collect())
}

fn text_hits(package: &HwpxPackage, query: &str) -> Result<Vec<Value>, AuthoringSearchError> {
    let mut hits = Vec::new();
    for entry in package.content_xml_names() {
        let view = XmlView::parse(source(package, entry)?)
            .map_err(|error| AuthoringSearchError(error.to_string()))?;
        let marks = field_marks(&view.field_occurrences(entry));
        for paragraph in view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| is_hp(&view, *id, "p"))
        {
            let position = paragraph_position(&view, paragraph);
            let body = paragraph_body(&view, paragraph);
            let path = view.path(paragraph).unwrap();
            let pieces = paragraph_pieces(&view, paragraph, &marks);
            let mut seen = HashSet::new();
            for (begin, finish) in literal_ignorecase_ranges(&body, query)? {
                let start = body[..begin].chars().count();
                let end = body[..finish].chars().count();
                let context = body_hit_context(&pieces, start, end);
                if !seen.insert(context.clone()) {
                    continue;
                }
                let mut hit = json!({"entry": entry, "paragraph": position.paragraph,
                    "paragraph_path": path, "start": start, "end": end,
                    "kind": "text", "context": context});
                if let Some(path) = &position.cell_path {
                    hit.as_object_mut()
                        .unwrap()
                        .insert("cell_path".into(), json!(path));
                }
                hits.push(hit);
            }
        }
    }
    Ok(hits)
}

pub fn search_hwpx(
    package: &HwpxPackage,
    query: &str,
    kind: &str,
) -> Result<Value, AuthoringSearchError> {
    if query.is_empty() {
        return Err(AuthoringSearchError("검색어를 입력하세요.".into()));
    }
    let hits = match kind {
        "text" => text_hits(package, query)?,
        "field" => field_hits(package, query)?,
        "structure" => structure_hits(package, query)?,
        _ => return Err(AuthoringSearchError("검색 종류를 확인하세요.".into())),
    };
    Ok(json!({"hits": hits}))
}

pub(crate) fn index(value: Option<&Value>) -> Option<usize> {
    value?
        .as_u64()
        .and_then(|number| usize::try_from(number).ok())
}

pub(crate) fn selection_path(selection: &Value) -> Option<Vec<CellStep>> {
    let array = selection.get("cell_path")?.as_array()?;
    array
        .iter()
        .map(|step| {
            let map = step.as_object()?;
            if map.len() != 4 {
                return None;
            }
            Some(CellStep {
                parent_paragraph: index(map.get("parent_paragraph"))?,
                control: index(map.get("control"))?,
                cell: index(map.get("cell"))?,
                paragraph: index(map.get("paragraph"))?,
            })
        })
        .collect()
}

fn selection_frame<'a>(
    package: &'a HwpxPackage,
    selection: &Value,
) -> Option<(&'a str, usize, usize, usize, usize)> {
    let entry = selection.get("entry")?.as_str()?;
    let source = package.entries.iter().find(|item| item.name == entry)?;
    let first = index(
        selection
            .get("start_paragraph")
            .or_else(|| selection.get("paragraph")),
    )?;
    let last = index(
        selection
            .get("end_paragraph")
            .or_else(|| selection.get("start_paragraph"))
            .or_else(|| selection.get("paragraph")),
    )?;
    let start = index(selection.get("start"))?;
    let end = index(selection.get("end"))?;
    (first == last && end > start).then_some((source.name.as_str(), first, last, start, end))
}

pub fn selected_context_hwpx(
    package: &HwpxPackage,
    selection: &Value,
) -> Result<Option<(String, String)>, AuthoringSearchError> {
    let Some((entry, first, _, start, end)) = selection_frame(package, selection) else {
        return Ok(None);
    };
    let view = XmlView::parse(source(package, entry)?)
        .map_err(|error| AuthoringSearchError(error.to_string()))?;
    let path = selection_path(selection);
    if selection.get("cell_path").is_some_and(Value::is_array) && path.is_none() {
        return Ok(None);
    }
    let paragraph = match selected_paragraph(&view, first, path.as_deref()) {
        Ok(paragraph) => paragraph,
        Err(_) => return Ok(None),
    };
    let scan = view.field_occurrences(entry);
    let sites = paragraph_sites(&view, paragraph, &scan);
    if field_range_refusal(&view, paragraph, &scan, &sites, start, end).is_some() {
        return Ok(None);
    }
    let before: String = sites.text.chars().take(start).collect();
    let focus: String = sites.text.chars().skip(start).take(end - start).collect();
    Ok(Some((before, focus)))
}

fn utf16_len(text: &str) -> usize {
    text.encode_utf16().count()
}

fn with_cell_path(mut location: Value, cell_path: Option<&Value>) -> Value {
    if let Some(cell_path) = cell_path {
        location
            .as_object_mut()
            .unwrap()
            .insert("cell_path".into(), json!(cell_path));
    }
    location
}

pub fn same_text_hwpx(
    package: &HwpxPackage,
    selection: &Value,
) -> Result<Vec<Value>, AuthoringSearchError> {
    let Some((_, phrase)) = selected_context_hwpx(package, selection)? else {
        return Ok(Vec::new());
    };
    if python_trim(&phrase).is_empty() {
        return Ok(Vec::new());
    }
    let chosen_entry = selection.get("entry").and_then(Value::as_str).unwrap();
    let chosen_index = index(
        selection
            .get("start_paragraph")
            .or_else(|| selection.get("paragraph")),
    )
    .unwrap();
    let chosen_start = index(selection.get("start")).unwrap();
    let chosen_end = index(selection.get("end")).unwrap();
    let path = selection_path(selection);
    let mut hits = Vec::new();
    for entry in package.content_xml_names() {
        let view = XmlView::parse(source(package, entry)?)
            .map_err(|error| AuthoringSearchError(error.to_string()))?;
        let selected = (entry == chosen_entry)
            .then(|| selected_paragraph(&view, chosen_index, path.as_deref()).ok())
            .flatten();
        let scan = view.field_occurrences(entry);
        let marks = field_marks(&scan);
        let top = top_paragraphs(&view);
        for paragraph in view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| is_hp(&view, *id, "p"))
        {
            let position = paragraph_position(&view, paragraph);
            let path = view.path(paragraph).unwrap();
            let anchor = top
                .iter()
                .position(|id| *id == paragraph)
                .or_else(|| root_anchor(&view, paragraph));
            let body = paragraph_body(&view, paragraph);
            let pieces = paragraph_pieces(&view, paragraph, &marks);
            let sites = paragraph_sites(&view, paragraph, &scan);
            for (byte, _) in body.match_indices(&phrase) {
                let start = body[..byte].chars().count();
                let end = start + phrase.chars().count();
                if selected == Some(paragraph) && start < chosen_end && chosen_start < end {
                    continue;
                }
                let parts = body_hit_parts(&pieces, start, end);
                let context = format!("{}{}{}", parts.0, parts.1, parts.2);
                let lead = utf16_len(&parts.0);
                let reason = position.paragraph.map_or(Some(PARAGRAPH_UNRESOLVED), |_| {
                    field_range_refusal(&view, paragraph, &scan, &sites, start, end)
                });
                let location = with_cell_path(
                    json!({"entry": entry, "paragraph": position.paragraph,
                        "paragraph_path": path, "start": start, "end": end}),
                    position.cell_path.as_ref().map(|cell_path| json!(cell_path)).as_ref(),
                );
                hits.push(
                    json!({"location": location, "anchor": anchor, "context": context,
                    "focus": {"start": lead, "end": lead + utf16_len(&parts.1)},
                    "enabled": reason.is_none(), "reason": reason}),
                );
            }
        }
    }
    Ok(hits)
}

/// Where a stray token's problem points: its top paragraph or root anchor, if any.
fn token_location(view: &XmlView, entry: &str, paragraph: NodeId, position: &ParagraphPosition) -> Value {
    let location = if let Some(index) = position.paragraph {
        json!({"entry": entry, "paragraph": index})
    } else if let Some(anchor) = root_anchor(view, paragraph) {
        json!({"entry": entry, "paragraph": anchor})
    } else {
        return Value::Null;
    };
    let cell_path = position.cell_path.is_some().then(|| json!(position.cell_path));
    with_cell_path(location, cell_path.as_ref())
}

/// The token's character range when it can be compiled in place: inside the editable
/// text, before any control, and with the same leading text as the paragraph model.
fn compilable_token_range(
    view: &XmlView,
    entry: &str,
    paragraph: NodeId,
    token: (isize, isize),
) -> Option<(usize, usize)> {
    let scan = view.field_occurrences(entry);
    let sites = paragraph_sites(view, paragraph, &scan);
    let end = usize::try_from(token.1).unwrap_or(usize::MAX);
    let start = usize::try_from(token.0).unwrap_or(usize::MAX);
    let model = paragraph_model_text(view, paragraph);
    (start < end
        && end <= sites.text.chars().count()
        && !sites.sites.is_empty()
        && !sites.hazards.iter().any(|at| *at <= end)
        && sites.text.chars().take(end).eq(model.chars().take(end)))
    .then_some((start, end))
}

pub fn stray_token_problems(package: &HwpxPackage) -> Result<Vec<Value>, AuthoringSearchError> {
    let schema =
        extract_schema(package).map_err(|error| AuthoringSearchError(error.to_string()))?;
    let mut views = HashMap::new();
    let mut problems = Vec::new();
    for site in schema.stray_sites {
        if !views.contains_key(&site.entry) {
            let view = XmlView::parse(source(package, &site.entry)?)
                .map_err(|error| AuthoringSearchError(error.to_string()))?;
            views.insert(site.entry.clone(), view);
        }
        let view = views.get(&site.entry).unwrap();
        let paragraph = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .find(|id| {
                is_hp(view, *id, "p") && view.path(*id).as_deref() == Some(&site.paragraph_path)
            })
            .ok_or_else(|| {
                AuthoringSearchError(format!("token paragraph missing: {}", site.paragraph_path))
            })?;
        let position = paragraph_position(view, paragraph);
        let mut location = token_location(view, &site.entry, paragraph, &position);
        let addressable =
            view.parent(paragraph) == Some(view.root()) || position.cell_path.is_some();
        if location != Value::Null
            && addressable
            && let Some((start, end)) =
                compilable_token_range(view, &site.entry, paragraph, (site.start, site.end))
        {
            let object = location.as_object_mut().unwrap();
            object.insert("start".into(), json!(start));
            object.insert("end".into(), json!(end));
        }
        let name = normalize_field_id(&site.name).unwrap_or(site.name);
        let command = json!({"type": "compile_token", "entry": site.entry,
            "paragraph_path": site.paragraph_path, "token_start": site.start, "name": name});
        problems.push(
            json!({"kind": "stray_token", "severity": "warning", "category": "authoring",
            "message": "평문으로 남은 필드 표기입니다.", "target": name, "location": location,
            "actions": [
                {"label": "원문으로 이동", "kind": "navigate", "location": location},
                {"label": "누름틀 변환", "kind": "command", "command": command}
            ]}),
        );
    }
    Ok(problems)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn casefold_field_and_scalar_text_search_share_native_coordinates() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>😀 café café i</hp:t></hp:run></hp:p><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='Straße'/></hp:ctrl></hp:run><hp:run><hp:t>값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let fields = search_hwpx(&package, "STRASSE", "field").unwrap();
        assert_eq!(fields["hits"].as_array().unwrap().len(), 1);
        assert_eq!(fields["hits"][0]["name"], "Straße");
        let text = search_hwpx(&package, "café", "text").unwrap();
        assert_eq!(text["hits"].as_array().unwrap().len(), 1);
        assert_eq!(text["hits"][0]["start"], 2);
        assert_eq!(
            search_hwpx(&package, "İ", "text").unwrap()["hits"][0]["start"],
            12
        );
        let peers = same_text_hwpx(
            &package,
            &json!({"entry": "Contents/section0.xml", "paragraph": 0, "start": 2, "end": 6}),
        )
        .unwrap();
        assert_eq!(peers.len(), 1);
        assert_eq!(peers[0]["location"]["start"], 7);
        assert_eq!(peers[0]["enabled"], true);
    }

    #[test]
    fn repeated_text_verdicts_distinguish_table_cells_from_unsafe_controls() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>○○시청</hp:t></hp:run></hp:p><hp:p><hp:run><hp:ctrl><hp:tab/></hp:ctrl><hp:t>표 ○○시청</hp:t></hp:run></hp:p><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀 ○○시청</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p><hp:p><hp:run><hp:rect><hp:drawText><hp:subList><hp:p><hp:run><hp:t>글상자 ○○시청</hp:t></hp:run></hp:p></hp:subList></hp:drawText></hp:rect></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let hits = same_text_hwpx(
            &package,
            &json!({"entry":"Contents/section0.xml",
            "paragraph":0,"start":0,"end":4}),
        )
        .unwrap();
        assert_eq!(hits.len(), 3);
        let tab = hits
            .iter()
            .find(|hit| hit["context"] == "표 ○○시청")
            .unwrap();
        assert_eq!(tab["enabled"], false);
        assert!(tab["reason"].as_str().unwrap().contains("제어 요소"));
        let cell = hits
            .iter()
            .find(|hit| hit["context"] == "셀 ○○시청")
            .unwrap();
        assert_eq!(cell["enabled"], true);
        assert_eq!(
            cell["location"]["cell_path"],
            json!([{"parent_paragraph":2,
            "control":0,"cell":0,"paragraph":0}])
        );
        let drawing = hits
            .iter()
            .find(|hit| hit["context"] == "글상자 ○○시청")
            .unwrap();
        assert_eq!(drawing["enabled"], false);
        assert!(drawing["location"]["paragraph"].is_null());
    }

    #[test]
    fn stray_token_locations_follow_editor_coordinates_only_when_safe() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>가 {{{{본문}}}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>x</hp:t><hp:tab/><hp:t>{{{{탭뒤}}}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>{{{{셀}}}}</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let problems = stray_token_problems(&package).unwrap();
        assert_eq!(
            problems
                .iter()
                .map(|item| item["target"].as_str().unwrap())
                .collect::<Vec<_>>(),
            vec!["본문", "탭뒤", "셀"]
        );
        assert_eq!(
            problems[0]["location"],
            json!({"entry":"Contents/section0.xml","paragraph":0,"start":2,"end":8})
        );
        assert_eq!(
            problems[1]["location"],
            json!({"entry":"Contents/section0.xml","paragraph":1})
        );
        assert_eq!(
            problems[2]["location"],
            json!({"entry":"Contents/section0.xml","paragraph":0,"start":0,"end":5,
                "cell_path":[{"parent_paragraph":2,"control":0,"cell":0,"paragraph":0}]})
        );
        assert!(
            problems
                .iter()
                .all(|item| item["actions"][1]["command"]["type"] == "compile_token")
        );
    }
}
