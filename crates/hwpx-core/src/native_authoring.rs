//! Guarded byte edits for native authoring Field controls.

use crate::authoring_edit::{add_one, document_text, max_numeric_id};
use crate::field_occurrence::resolve_field_occurrences;
use crate::lineseg::serialize_modified_section;
use crate::native_admission::native_element;
use crate::text_model::HP_NS;
use crate::xml_dom::{Attribute, Content, Name, NodeId, XmlDocument, XmlError, parse_xml};
use crate::xml_view::path_for_doc;
use std::collections::HashSet;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeAuthoringError(pub String);
impl fmt::Display for NativeAuthoringError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for NativeAuthoringError {}
impl From<XmlError> for NativeAuthoringError {
    fn from(value: XmlError) -> Self {
        Self(value.0)
    }
}

pub struct CreateFieldEdit<'a> {
    pub paragraph_path: &'a str,
    pub start: usize,
    pub end: usize,
    pub name: &'a str,
}

pub enum FieldElementChange<'a> {
    Rename(&'a str),
    Unset(&'a str),
}

pub struct FieldOccurrenceEdit<'a> {
    pub ordinal: usize,
    pub pairing_id: Option<&'a str>,
    pub change: FieldElementChange<'a>,
}

#[derive(Clone)]
struct Site {
    node: NodeId,
    start: usize,
    end: usize,
}

fn invalid(message: impl Into<String>) -> NativeAuthoringError {
    NativeAuthoringError(message.into())
}
fn native(doc: &XmlDocument, id: NodeId, local: &str) -> bool {
    doc.node(id).name.is(HP_NS, local)
}
fn text(doc: &XmlDocument, id: NodeId) -> String {
    doc.node(id)
        .children
        .iter()
        .filter_map(|part| match part {
            Content::Text(text) | Content::CData(text) => Some(text.as_str()),
            _ => None,
        })
        .collect()
}
fn element_children(doc: &XmlDocument, id: NodeId) -> impl Iterator<Item = NodeId> + '_ {
    doc.elements(id)
}
fn simple_field_content(doc: &XmlDocument, paragraph: NodeId) -> bool {
    for run in element_children(doc, paragraph).filter(|id| native(doc, *id, "run")) {
        for part in &doc.node(run).children {
            match part {
                Content::Element(id) if native(doc, *id, "t") || native(doc, *id, "ctrl") => {}
                Content::Text(_) | Content::CData(_) => {}
                _ => return false,
            }
        }
    }
    for ctrl in doc.descendants(paragraph) {
        if !native(doc, ctrl, "ctrl") {
            continue;
        }
        for part in &doc.node(ctrl).children {
            match part {
                Content::Element(id)
                    if native(doc, *id, "fieldBegin") || native(doc, *id, "fieldEnd") => {}
                Content::Text(_) | Content::CData(_) => {}
                _ => return false,
            }
        }
    }
    true
}
fn field_span(
    doc: &XmlDocument,
    paragraph: NodeId,
    begin: NodeId,
    end: NodeId,
) -> Option<(usize, usize)> {
    if !simple_field_content(doc, paragraph) {
        return None;
    }
    let mut at = 0;
    let (mut low, mut high) = (None, None);
    for id in doc.descendants(paragraph) {
        if id == begin {
            low = Some(at);
        } else if id == end {
            high = Some(at);
        } else if native(doc, id, "t") {
            at += text(doc, id).chars().count();
        }
    }
    let (low, high) = (low?, high?);
    (low <= high).then_some((low, high))
}

fn sites(doc: &XmlDocument, paragraph: NodeId) -> (Vec<Site>, Vec<usize>, String) {
    let resolution = resolve_field_occurrences("", doc);
    let boundaries: HashSet<_> =
        if resolution.diagnostics.is_empty() && simple_field_content(doc, paragraph) {
            resolution
                .occurrences
                .into_iter()
                .filter(|field| field.paragraph == paragraph)
                .flat_map(|field| [field.begin_ctrl, field.end_ctrl])
                .filter(|id| {
                    doc.node(*id)
                        .children
                        .iter()
                        .filter(|part| !matches!(part, Content::Text(_) | Content::CData(_)))
                        .count()
                        == 1
                })
                .collect()
        } else {
            HashSet::new()
        };
    let mut sites = Vec::new();
    let mut hazards = Vec::new();
    let mut joined = String::new();
    let mut length = 0;
    for run in element_children(doc, paragraph).filter(|id| native(doc, *id, "run")) {
        for part in &doc.node(run).children {
            match part {
                Content::Element(id)
                    if native(doc, *id, "t")
                        && doc
                            .node(*id)
                            .children
                            .iter()
                            .all(|part| matches!(part, Content::Text(_) | Content::CData(_))) =>
                {
                    let value = text(doc, *id);
                    let next = length + value.chars().count();
                    sites.push(Site {
                        node: *id,
                        start: length,
                        end: next,
                    });
                    joined.push_str(&value);
                    length = next;
                }
                Content::Element(id) if boundaries.contains(id) => {}
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_) => {
                    hazards.push(length)
                }
                Content::Text(_) | Content::CData(_) => {}
            }
        }
    }
    (sites, hazards, joined)
}

fn preflight(
    doc: &XmlDocument,
    paragraph: NodeId,
    edit: &CreateFieldEdit<'_>,
) -> Result<(), NativeAuthoringError> {
    let (sites, hazards, joined) = sites(doc, paragraph);
    if edit.start > edit.end || edit.end > joined.chars().count() {
        return Err(invalid("고른 문자 범위가 문단 밖에 있습니다."));
    }
    if sites.is_empty() {
        return Err(invalid("이 문단에는 편집 가능한 텍스트가 없습니다."));
    }
    if hazards.iter().any(|at| *at <= edit.end) {
        return Err(invalid(
            "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다.",
        ));
    }
    let resolution = resolve_field_occurrences("", doc);
    for field in resolution
        .occurrences
        .iter()
        .filter(|field| field.paragraph == paragraph)
    {
        if let Some((low, high)) = field_span(doc, paragraph, field.begin, field.end)
            && ((edit.start == edit.end && low <= edit.start && edit.start <= high)
                || (edit.start < edit.end && low < edit.end && edit.start < high))
        {
            return Err(invalid("고른 범위에 기존 필드가 포함되어 있습니다."));
        }
    }
    Ok(())
}

fn paragraph(doc: &XmlDocument, path: &str) -> Result<NodeId, NativeAuthoringError> {
    let found: Vec<_> = doc
        .descendants(doc.root)
        .into_iter()
        .filter(|id| native(doc, *id, "p") && path_for_doc(doc, *id) == path)
        .collect();
    if found.len() != 1 {
        return Err(invalid("고른 문단의 위치를 확정할 수 없습니다."));
    }
    Ok(found[0])
}

fn boundary(
    doc: &mut XmlDocument,
    name: &str,
    begin_id: &str,
    field_id: &str,
    beginning: bool,
) -> Result<NodeId, NativeAuthoringError> {
    let ctrl = native_element(doc, "ctrl", &[]);
    let marker = if beginning {
        native_element(
            doc,
            "fieldBegin",
            &[
                ("id", begin_id),
                ("type", "CLICK_HERE"),
                ("name", name),
                ("editable", "1"),
                ("dirty", "1"),
                ("zorder", "-1"),
                ("fieldid", field_id),
                ("metaTag", ""),
            ],
        )
    } else {
        native_element(
            doc,
            "fieldEnd",
            &[("beginIDRef", begin_id), ("fieldid", field_id)],
        )
    };
    doc.insert_element(ctrl, 0, marker)?;
    Ok(ctrl)
}

fn char_slice(value: &str, start: usize, end: usize) -> String {
    value
        .chars()
        .skip(start)
        .take(end.saturating_sub(start))
        .collect()
}
fn insert_boundary(
    doc: &mut XmlDocument,
    paragraph: NodeId,
    offset: usize,
    ctrl: NodeId,
    beginning: bool,
) -> Result<(), NativeAuthoringError> {
    let (sites, _, _) = sites(doc, paragraph);
    let site = if beginning {
        sites
            .iter()
            .find(|site| site.start <= offset && offset < site.end)
            .or_else(|| sites.last())
    } else {
        sites
            .iter()
            .find(|site| site.start < offset && offset <= site.end)
            .or_else(|| sites.first())
    }
    .ok_or_else(|| invalid("이 문단에는 편집 가능한 텍스트가 없습니다."))?;
    let run = doc
        .parent(site.node)
        .ok_or_else(|| invalid("detached text node"))?;
    let index = doc
        .node(run)
        .children
        .iter()
        .position(|part| matches!(part, Content::Element(id) if *id == site.node))
        .ok_or_else(|| invalid("detached text node"))?;
    let inner = offset
        .checked_sub(site.start)
        .ok_or_else(|| invalid("field offset moved"))?;
    let value = text(doc, site.node);
    let length = value.chars().count();
    if inner == 0 {
        doc.insert_element(run, index, ctrl)?;
    } else if inner == length {
        let mut after = index + 1;
        while doc
            .node(run)
            .children
            .get(after)
            .is_some_and(|part| matches!(part, Content::Text(_) | Content::CData(_)))
        {
            after += 1;
        }
        doc.insert_element(run, after, ctrl)?;
    } else if inner < length {
        let suffix = doc.clone_subtree(site.node);
        doc.node_mut(site.node).children = vec![Content::Text(char_slice(&value, 0, inner))];
        doc.node_mut(suffix).children = vec![Content::Text(char_slice(&value, inner, length))];
        let mut tails = Vec::new();
        while doc
            .node(run)
            .children
            .get(index + 1)
            .is_some_and(|part| matches!(part, Content::Text(_) | Content::CData(_)))
        {
            tails.push(doc.node_mut(run).children.remove(index + 1));
        }
        doc.insert_element(run, index + 1, ctrl)?;
        doc.insert_element(run, index + 2, suffix)?;
        for (at, tail) in tails.into_iter().enumerate() {
            doc.node_mut(run).children.insert(index + 3 + at, tail);
        }
    } else {
        return Err(invalid("field offset moved"));
    }
    Ok(())
}

/// Insert native ordinary Field controls into existing text runs, validating all
/// original ranges before one private XML mutation and candidate readback.
pub fn create_field_ranges(
    source: &[u8],
    edits: &[CreateFieldEdit<'_>],
) -> Result<Vec<u8>, NativeAuthoringError> {
    if edits.is_empty() {
        return Ok(source.to_vec());
    }
    let mut doc = parse_xml(source)?;
    let before = document_text(&doc);
    let mut planned = Vec::new();
    for edit in edits {
        let paragraph = paragraph(&doc, edit.paragraph_path)?;
        preflight(&doc, paragraph, edit)?;
        planned.push((paragraph, edit));
    }
    for at in 0..planned.len() {
        for other in &planned[at + 1..] {
            let (first, edit) = &planned[at];
            if *first == other.0
                && (edit.start < other.1.end && other.1.start < edit.end
                    || (edit.start, edit.end) == (other.1.start, other.1.end))
            {
                return Err(invalid("고른 범위에 기존 필드가 포함되어 있습니다."));
            }
        }
    }
    planned.sort_by_key(|(_, edit)| std::cmp::Reverse(edit.start));
    let mut next = max_numeric_id(&doc).map_err(|error| invalid(error.to_string()))?;
    let mut generated = Vec::new();
    for (paragraph, edit) in planned {
        add_one(&mut next);
        let begin_id = next.clone();
        add_one(&mut next);
        let field_id = next.clone();
        let begin = boundary(&mut doc, edit.name, &begin_id, &field_id, true)?;
        let end = boundary(&mut doc, edit.name, &begin_id, &field_id, false)?;
        if edit.start == 0 && edit.end == 0 {
            insert_boundary(&mut doc, paragraph, edit.start, begin, true)?;
            insert_boundary(&mut doc, paragraph, edit.end, end, false)?;
        } else {
            insert_boundary(&mut doc, paragraph, edit.end, end, false)?;
            insert_boundary(&mut doc, paragraph, edit.start, begin, true)?;
        }
        generated.push((edit.name, begin_id, field_id));
    }
    let bytes = serialize_modified_section(&mut doc)?;
    let after = parse_xml(&bytes)?;
    if document_text(&after) != before {
        return Err(invalid("field creation changed surrounding text"));
    }
    let resolution = resolve_field_occurrences("", &after);
    if !resolution.diagnostics.is_empty() {
        return Err(invalid("field creation pairing postcondition failed"));
    }
    for (name, begin_id, field_id) in generated {
        if resolution
            .occurrences
            .iter()
            .filter(|field| {
                after.attr(field.begin, "id") == Some(&begin_id)
                    && after.attr(field.begin, "name") == Some(name)
                    && after.attr(field.begin, "type") == Some("CLICK_HERE")
                    && after.attr(field.end, "fieldid") == Some(&field_id)
            })
            .count()
            != 1
        {
            return Err(invalid("field creation postcondition failed"));
        }
    }
    Ok(bytes)
}

/// Change selected ordinary Field pairs in one XML entry. Ordinals and optional
/// pairing IDs are checked against the source snapshot before any mutation.
pub fn change_field_occurrences(
    source: &[u8],
    edits: &[FieldOccurrenceEdit<'_>],
) -> Result<Vec<u8>, NativeAuthoringError> {
    if edits.is_empty() {
        return Ok(source.to_vec());
    }
    let mut doc = parse_xml(source)?;
    let resolution = resolve_field_occurrences("", &doc);
    if !resolution.diagnostics.is_empty() {
        return Err(invalid("ordinary Field pairing is unusable"));
    }
    let mut seen = HashSet::new();
    for edit in edits {
        if !seen.insert(edit.ordinal) {
            return Err(invalid("duplicate Field edit ordinal"));
        }
        let field = resolution
            .occurrences
            .get(edit.ordinal)
            .ok_or_else(|| invalid("필드 사용 위치를 찾을 수 없습니다."))?;
        if edit
            .pairing_id
            .is_some_and(|expected| doc.attr(field.begin, "id") != Some(expected))
        {
            return Err(invalid(
                "고른 필드 사용 위치가 바뀌었습니다. 다시 고르세요.",
            ));
        }
        if matches!(edit.change, FieldElementChange::Unset(_)) {
            if field.texts.is_empty()
                || field.texts.iter().any(|id| {
                    doc.node(*id).children.iter().any(|part| {
                        matches!(
                            part,
                            Content::Element(_)
                                | Content::Comment(_)
                                | Content::ProcessingInstruction(_)
                        )
                    })
                })
            {
                return Err(invalid(
                    "이 필드에는 복합 요소가 있어 내용 보존을 확인할 수 없습니다.",
                ));
            }
            if field.begin_ctrl == field.end_ctrl {
                return Err(invalid("field controls share one container"));
            }
        }
    }
    let removed = edits
        .iter()
        .filter(|edit| matches!(edit.change, FieldElementChange::Unset(_)))
        .count();
    for edit in edits {
        let field = &resolution.occurrences[edit.ordinal];
        match &edit.change {
            FieldElementChange::Rename(name) => {
                let attrs = &mut doc.node_mut(field.begin).attributes;
                if let Some(attr) = attrs
                    .iter_mut()
                    .find(|attr| attr.name.namespace.is_empty() && attr.name.local == "name")
                {
                    attr.value = (*name).into();
                } else {
                    attrs.push(Attribute {
                        name: Name {
                            raw: "name".into(),
                            namespace: String::new(),
                            local: "name".into(),
                        },
                        value: (*name).into(),
                    });
                }
            }
            FieldElementChange::Unset(replacement) => {
                doc.node_mut(field.texts[0]).children = vec![Content::Text((*replacement).into())];
                for id in &field.texts[1..] {
                    doc.node_mut(*id).children.clear();
                }
                doc.remove_element_with_tail(field.begin_ctrl)?;
                doc.remove_element_with_tail(field.end_ctrl)?;
            }
        }
    }
    let bytes = serialize_modified_section(&mut doc)?;
    let after = parse_xml(&bytes)?;
    let observed = resolve_field_occurrences("", &after);
    if !observed.diagnostics.is_empty()
        || observed.occurrences.len() + removed != resolution.occurrences.len()
    {
        return Err(invalid("Field change postcondition failed"));
    }
    for edit in edits {
        if let FieldElementChange::Rename(name) = edit.change {
            let old = &resolution.occurrences[edit.ordinal];
            if !observed.occurrences.iter().any(|field| {
                after.attr(field.begin, "id") == doc.attr(old.begin, "id")
                    && after.attr(field.begin, "name") == Some(name)
            }) {
                return Err(invalid("Field rename postcondition failed"));
            }
        }
    }
    Ok(bytes)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn creates_two_fields_in_existing_run_and_preserves_text_tail() {
        let source = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run charPrIDRef='7'><hp:t>가나다</hp:t>꼬리<hp:t>XYZ</hp:t></hp:run></hp:p></hs:sec>"
        );
        let edits = [
            CreateFieldEdit {
                paragraph_path: "/hs:sec/hp:p",
                start: 1,
                end: 2,
                name: "첫째",
            },
            CreateFieldEdit {
                paragraph_path: "/hs:sec/hp:p",
                start: 3,
                end: 5,
                name: "둘째",
            },
        ];
        let output = create_field_ranges(source.as_bytes(), &edits).unwrap();
        let doc = parse_xml(&output).unwrap();
        let resolution = resolve_field_occurrences("Contents/section0.xml", &doc);
        assert!(resolution.diagnostics.is_empty());
        assert_eq!(resolution.occurrences.len(), 2);
        assert_eq!(
            resolution
                .occurrences
                .iter()
                .map(|field| doc.attr(field.begin, "name"))
                .collect::<Vec<_>>(),
            vec![Some("첫째"), Some("둘째")]
        );
        assert_eq!(document_text(&doc).0, "가나다XYZ");
        let run = doc
            .descendants(doc.root)
            .into_iter()
            .find(|id| native(&doc, *id, "run"))
            .unwrap();
        assert!(
            doc.node(run)
                .children
                .iter()
                .any(|part| matches!(part, Content::Text(text) if text == "꼬리"))
        );
        let bad = [CreateFieldEdit {
            paragraph_path: "/hs:sec/hp:p",
            start: 20,
            end: 21,
            name: "실패",
        }];
        assert!(create_field_ranges(source.as_bytes(), &bad).is_err());
    }

    #[test]
    fn rename_then_unset_keeps_body_and_rejects_complex_value() {
        let source = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='원본'/></hp:ctrl></hp:run><hp:run><hp:t>값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>"
        );
        let renamed = change_field_occurrences(
            source.as_bytes(),
            &[FieldOccurrenceEdit {
                ordinal: 0,
                pairing_id: Some("1"),
                change: FieldElementChange::Rename("변경"),
            }],
        )
        .unwrap();
        let renamed_doc = parse_xml(&renamed).unwrap();
        assert_eq!(
            resolve_field_occurrences("", &renamed_doc)
                .occurrences
                .len(),
            1
        );
        assert!(
            renamed
                .windows("변경".len())
                .any(|slice| slice == "변경".as_bytes())
        );
        let unset = change_field_occurrences(
            &renamed,
            &[FieldOccurrenceEdit {
                ordinal: 0,
                pairing_id: Some("1"),
                change: FieldElementChange::Unset("남긴 값"),
            }],
        )
        .unwrap();
        let doc = parse_xml(&unset).unwrap();
        assert!(resolve_field_occurrences("", &doc).occurrences.is_empty());
        assert_eq!(document_text(&doc).0, "남긴 값");
        let complex = source.replace("<hp:t>값</hp:t>", "<hp:t>값<hp:tab/></hp:t>");
        assert!(
            change_field_occurrences(
                complex.as_bytes(),
                &[FieldOccurrenceEdit {
                    ordinal: 0,
                    pairing_id: Some("1"),
                    change: FieldElementChange::Unset("손실"),
                }]
            )
            .is_err()
        );
    }
}
