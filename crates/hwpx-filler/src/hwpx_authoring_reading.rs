//! Shared read-only coordinates for native HWPX authoring commands.

use crate::fields::{is_fill_target_field_type, normalize_field_id, python_whitespace};
use hwpx_core::native_admission::{EntryFieldObservation, EntryFieldScan};
use hwpx_core::text_model::HP_NS;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use serde::Serialize;
use std::collections::{HashMap, HashSet};

const CONTROL_TAGS: &[&str] = &[
    "tbl",
    "pic",
    "container",
    "rect",
    "ellipse",
    "line",
    "connectLine",
    "arc",
    "polygon",
    "curve",
    "compose",
    "dutmal",
    "equation",
    "btn",
    "checkBtn",
    "radioBtn",
    "comboBox",
    "edit",
    "chart",
    "ole",
];
const CTRL_CHILD_TAGS: &[&str] = &[
    "colPr",
    "header",
    "footer",
    "footNote",
    "endNote",
    "autoNum",
    "indexmark",
    "fieldBegin",
    "pageHiding",
    "pageNumCtrl",
    "pageNum",
    "bookmark",
    "newNum",
];
pub const REASON_CONTROL_BEFORE: &str =
    "고른 범위 앞이나 안에 제어 요소가 있어 문자 위치를 확정할 수 없습니다.";
pub const REASON_FIELD_OVERLAP: &str = "고른 범위에 기존 필드가 포함되어 있습니다.";
pub const PARAGRAPH_UNRESOLVED: &str = "고른 문단의 위치를 확정할 수 없습니다.";

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CellStep {
    pub parent_paragraph: usize,
    pub control: usize,
    pub cell: usize,
    pub paragraph: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParagraphPosition {
    pub paragraph: Option<usize>,
    pub cell_path: Option<Vec<CellStep>>,
}

#[derive(Clone, Debug)]
pub struct ParagraphPiece {
    pub text: String,
    pub field: Option<NodeId>,
    pub name: Option<String>,
}

#[derive(Clone, Debug)]
pub struct TextSite {
    pub node: NodeId,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug)]
pub struct ParagraphSites {
    pub sites: Vec<TextSite>,
    pub hazards: Vec<usize>,
    pub text: String,
}

pub fn is_hp(view: &XmlView, id: NodeId, local: &str) -> bool {
    view.node(id).is_some_and(|node| node.name.is(HP_NS, local))
}

pub fn element_children(view: &XmlView, parent: NodeId) -> impl Iterator<Item = NodeId> + '_ {
    view.node(parent).into_iter().flat_map(|node| {
        node.children.iter().filter_map(|part| match part {
            Content::Element(id) => Some(*id),
            _ => None,
        })
    })
}

/// lxml's `.text`, not all text descendants or subsequent child tails.
pub fn leading_text(view: &XmlView, id: NodeId) -> String {
    let mut text = String::new();
    if let Some(node) = view.node(id) {
        for part in &node.children {
            match part {
                Content::Text(value) | Content::CData(value) => text.push_str(value),
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_) => {
                    break;
                }
            }
        }
    }
    text
}

pub fn top_paragraphs(view: &XmlView) -> Vec<NodeId> {
    element_children(view, view.root())
        .filter(|id| is_hp(view, *id, "p"))
        .collect()
}

pub fn paragraph_body(view: &XmlView, paragraph: NodeId) -> String {
    let mut text = String::new();
    for run in element_children(view, paragraph).filter(|id| is_hp(view, *id, "run")) {
        for child in element_children(view, run).filter(|id| is_hp(view, *id, "t")) {
            text.push_str(&leading_text(view, child));
        }
    }
    text
}

fn control_count(view: &XmlView, id: NodeId) -> usize {
    let Some(node) = view.node(id) else { return 0 };
    if node.name.namespace != HP_NS {
        return 0;
    }
    let local = node.name.local.as_str();
    if CONTROL_TAGS.contains(&local) {
        return 1;
    }
    match local {
        "switch" => usize::from(
            view.descendants(id)
                .unwrap_or_default()
                .into_iter()
                .any(|child| is_hp(view, child, "chart") || is_hp(view, child, "ole")),
        ),
        "secPr" => {
            1 + usize::from(element_children(view, id).any(|child| is_hp(view, child, "colPr")))
        }
        "ctrl" => element_children(view, id)
            .filter(|child| {
                let Some(name) = view.node(*child).map(|item| &item.name) else {
                    return false;
                };
                name.namespace == HP_NS
                    && (CTRL_CHILD_TAGS.contains(&name.local.as_str())
                        || (name.local == "hiddenComment"
                            && !view.node(*child).unwrap().children.is_empty()))
            })
            .count(),
        _ => 0,
    }
}

fn control_index(view: &XmlView, owner: NodeId, table: NodeId) -> Option<usize> {
    let mut counted = 0;
    let mut found = None;
    for run in element_children(view, owner).filter(|id| is_hp(view, *id, "run")) {
        for child in element_children(view, run) {
            if child == table {
                found = Some(counted);
            }
            counted += control_count(view, child);
        }
    }
    found
}

fn ancestor_chain(view: &XmlView, node: NodeId) -> Option<[NodeId; 7]> {
    let mut chain = [node; 7];
    for (index, local) in ["subList", "tc", "tr", "tbl", "run", "p"]
        .iter()
        .enumerate()
    {
        let parent = view.parent(chain[index])?;
        if !is_hp(view, parent, local) {
            return None;
        }
        chain[index + 1] = parent;
    }
    Some(chain)
}

fn cell_step(view: &XmlView, node: NodeId) -> Option<(NodeId, CellStep)> {
    let chain = ancestor_chain(view, node)?;
    let (sublist, cell, table, owner) = (chain[1], chain[2], chain[4], chain[6]);
    let cells: Vec<_> = view
        .descendants(table)?
        .into_iter()
        .filter(|id| is_hp(view, *id, "tc"))
        .filter(|id| {
            let mut parent = view.parent(*id);
            while let Some(ancestor) = parent {
                if is_hp(view, ancestor, "tbl") {
                    return ancestor == table;
                }
                parent = view.parent(ancestor);
            }
            false
        })
        .collect();
    Some((
        owner,
        CellStep {
            parent_paragraph: 0,
            control: control_index(view, owner, table)?,
            cell: cells.iter().position(|id| *id == cell)?,
            paragraph: element_children(view, sublist)
                .filter(|id| is_hp(view, *id, "p"))
                .position(|id| id == node)?,
        },
    ))
}

pub fn cell_path(view: &XmlView, paragraph: NodeId) -> Option<Vec<CellStep>> {
    let mut steps = Vec::new();
    let mut node = paragraph;
    while view.parent(node) != Some(view.root()) {
        let (owner, step) = cell_step(view, node)?;
        steps.push(step);
        node = owner;
    }
    if steps.is_empty() {
        return None;
    }
    steps.reverse();
    steps[0].parent_paragraph = top_paragraphs(view).iter().position(|id| *id == node)?;
    for index in 1..steps.len() {
        steps[index].parent_paragraph = steps[index - 1].paragraph;
    }
    Some(steps)
}

pub fn root_anchor(view: &XmlView, paragraph: NodeId) -> Option<usize> {
    let paragraphs = top_paragraphs(view);
    let mut parent = view.parent(paragraph);
    while let Some(id) = parent {
        if is_hp(view, id, "p")
            && let Some(index) = paragraphs.iter().position(|item| *item == id)
        {
            return Some(index);
        }
        parent = view.parent(id);
    }
    None
}

pub fn paragraph_position(view: &XmlView, paragraph: NodeId) -> ParagraphPosition {
    if let Some(index) = top_paragraphs(view).iter().position(|id| *id == paragraph) {
        return ParagraphPosition {
            paragraph: Some(index),
            cell_path: None,
        };
    }
    let path = cell_path(view, paragraph);
    ParagraphPosition {
        paragraph: path
            .as_ref()
            .and_then(|steps| steps.last().map(|step| step.paragraph)),
        cell_path: path,
    }
}

pub fn selected_paragraph(
    view: &XmlView,
    paragraph_index: usize,
    path: Option<&[CellStep]>,
) -> Result<NodeId, &'static str> {
    let paragraphs = top_paragraphs(view);
    let Some(path) = path else {
        return paragraphs
            .get(paragraph_index)
            .copied()
            .ok_or("고른 문단이 문서 영역 밖에 있습니다.");
    };
    if path.is_empty()
        || path
            .last()
            .is_none_or(|step| step.paragraph != paragraph_index)
    {
        return Err(PARAGRAPH_UNRESOLVED);
    }
    let Some(owner) = paragraphs.get(path[0].parent_paragraph) else {
        return Err(PARAGRAPH_UNRESOLVED);
    };
    let candidates: Vec<_> = view
        .descendants(*owner)
        .unwrap_or_default()
        .into_iter()
        .filter(|id| is_hp(view, *id, "p") && cell_path(view, *id).as_deref() == Some(path))
        .collect();
    if candidates.len() == 1 {
        Ok(candidates[0])
    } else {
        Err(PARAGRAPH_UNRESOLVED)
    }
}

pub fn simple_field_content(view: &XmlView, paragraph: NodeId) -> bool {
    for run in element_children(view, paragraph).filter(|id| is_hp(view, *id, "run")) {
        for part in &view.node(run).unwrap().children {
            let Content::Element(child) = part else {
                if matches!(
                    part,
                    Content::Comment(_) | Content::ProcessingInstruction(_)
                ) {
                    return false;
                }
                continue;
            };
            if !is_hp(view, *child, "t") && !is_hp(view, *child, "ctrl") {
                return false;
            }
        }
    }
    for control in view.descendants(paragraph).unwrap_or_default() {
        if is_hp(view, control, "ctrl")
            && view
                .node(control)
                .unwrap()
                .children
                .iter()
                .any(|part| match part {
                    Content::Element(child) => {
                        !is_hp(view, *child, "fieldBegin") && !is_hp(view, *child, "fieldEnd")
                    }
                    Content::Comment(_) | Content::ProcessingInstruction(_) => true,
                    Content::Text(_) | Content::CData(_) => false,
                })
        {
            return false;
        }
    }
    true
}

pub fn simple_field_span(view: &XmlView, field: &EntryFieldObservation) -> Option<(usize, usize)> {
    if !simple_field_content(view, field.paragraph) {
        return None;
    }
    let mut offset = 0;
    let (mut start, mut end) = (None, None);
    for id in view.descendants(field.paragraph)? {
        if id == field.begin {
            start = Some(offset);
        } else if id == field.end {
            end = Some(offset);
        } else if is_hp(view, id, "t") {
            offset += leading_text(view, id).chars().count();
        }
    }
    let (start, end) = (start?, end?);
    (start <= end).then_some((start, end))
}

pub fn field_marks(scan: &EntryFieldScan) -> HashMap<NodeId, (NodeId, Option<String>)> {
    let mut marks = HashMap::new();
    for field in &scan.fields {
        let name = field.raw_name.as_deref().and_then(normalize_field_id);
        if let Some(name) = name.filter(|_| is_fill_target_field_type(field.field_type.as_deref()))
        {
            marks.insert(field.begin, (field.begin, Some(name)));
            marks.insert(field.end, (field.begin, None));
        }
    }
    marks
}

pub fn paragraph_pieces(
    view: &XmlView,
    paragraph: NodeId,
    marks: &HashMap<NodeId, (NodeId, Option<String>)>,
) -> Vec<ParagraphPiece> {
    let mut pieces = Vec::new();
    let mut current: Option<(NodeId, String)> = None;
    for id in view.descendants(paragraph).unwrap_or_default() {
        if let Some((key, name)) = marks.get(&id) {
            current = name.as_ref().map(|name| (*key, name.clone()));
            if let Some((key, name)) = &current {
                pieces.push(ParagraphPiece {
                    text: String::new(),
                    field: Some(*key),
                    name: Some(name.clone()),
                });
            }
        } else if is_hp(view, id, "t") {
            let Some(run) = view.parent(id) else { continue };
            if !is_hp(view, run, "run") || view.parent(run) != Some(paragraph) {
                continue;
            }
            pieces.push(ParagraphPiece {
                text: leading_text(view, id),
                field: current.as_ref().map(|(key, _)| *key),
                name: current.as_ref().map(|(_, name)| name.clone()),
            });
        }
    }
    pieces
}

pub fn render_pieces(pieces: &[ParagraphPiece]) -> String {
    let mut text = String::new();
    let mut last = None;
    for piece in pieces {
        match piece.field {
            None => text.push_str(&piece.text),
            Some(key) if last != Some(key) => {
                text.push('[');
                text.push_str(piece.name.as_deref().unwrap_or_default());
                text.push(']');
            }
            Some(_) => {}
        }
        last = piece.field;
    }
    text
}

fn collapse_context_space(text: &str) -> String {
    let mut out = String::new();
    let mut in_space = false;
    for ch in text.chars() {
        if python_whitespace(ch) {
            if !in_space {
                out.push(' ');
            }
            in_space = true;
        } else {
            out.push(ch);
            in_space = false;
        }
    }
    out
}

pub fn occurrence_context_parts(
    before: &str,
    focus: &str,
    after: &str,
) -> (String, String, String) {
    const SPAN: usize = 12;
    let (before, after) = (
        collapse_context_space(before),
        collapse_context_space(after),
    );
    let lead: String = before
        .chars()
        .rev()
        .take(SPAN)
        .collect::<String>()
        .chars()
        .rev()
        .collect();
    let trail: String = after.chars().take(SPAN).collect();
    (
        format!(
            "{}{}",
            if before.chars().count() > SPAN {
                "…"
            } else {
                ""
            },
            lead
        ),
        focus.into(),
        format!(
            "{}{}",
            trail,
            if after.chars().count() > SPAN {
                "…"
            } else {
                ""
            }
        ),
    )
}

pub fn native_occurrence_context(
    view: &XmlView,
    field: &EntryFieldObservation,
    name: &str,
    marks: &HashMap<NodeId, (NodeId, Option<String>)>,
) -> String {
    let pieces = paragraph_pieces(view, field.paragraph, marks);
    let own: Vec<_> = pieces
        .iter()
        .enumerate()
        .filter(|(_, piece)| piece.field == Some(field.begin))
        .map(|(index, _)| index)
        .collect();
    let Some(first) = own.first() else {
        return format!("[{name}]");
    };
    let last = *own.last().unwrap();
    let (lead, focus, trail) = occurrence_context_parts(
        &render_pieces(&pieces[..*first]),
        &format!("[{name}]"),
        &render_pieces(&pieces[last + 1..]),
    );
    format!("{lead}{focus}{trail}")
}

fn char_slice(text: &str, start: usize, end: usize) -> String {
    text.chars()
        .skip(start)
        .take(end.saturating_sub(start))
        .collect()
}

pub fn body_hit_parts(
    pieces: &[ParagraphPiece],
    start: usize,
    end: usize,
) -> (String, String, String) {
    let mut spans = Vec::with_capacity(pieces.len());
    let mut offset = 0;
    for piece in pieces {
        let next = offset + piece.text.chars().count();
        spans.push((offset, next, piece));
        offset = next;
    }
    let hit: HashSet<_> = spans
        .iter()
        .filter(|(lo, hi, piece)| piece.field.is_some() && *lo < end && start < *hi)
        .filter_map(|(_, _, piece)| piece.field)
        .collect();
    let inside: Vec<_> = spans
        .iter()
        .filter(|(_, _, piece)| piece.field.is_some_and(|key| hit.contains(&key)))
        .collect();
    let (start, end) = if let (Some(first), Some(last)) = (inside.first(), inside.last()) {
        (start.min(first.0), end.max(last.1))
    } else {
        (start, end)
    };
    let (mut before, mut focus, mut after) = (Vec::new(), Vec::new(), Vec::new());
    for (lo, hi, piece) in spans {
        if let Some(key) = piece.field {
            let side = if hit.contains(&key) {
                &mut focus
            } else if hi <= start {
                &mut before
            } else if lo >= end {
                &mut after
            } else {
                &mut focus
            };
            side.push(piece.clone());
        } else {
            before.push(ParagraphPiece {
                text: char_slice(&piece.text, 0, start.clamp(lo, hi) - lo),
                field: None,
                name: None,
            });
            focus.push(ParagraphPiece {
                text: char_slice(
                    &piece.text,
                    start.saturating_sub(lo),
                    end.clamp(lo, hi) - lo,
                ),
                field: None,
                name: None,
            });
            after.push(ParagraphPiece {
                text: char_slice(&piece.text, end.saturating_sub(lo), hi - lo),
                field: None,
                name: None,
            });
        }
    }
    occurrence_context_parts(
        &render_pieces(&before),
        &render_pieces(&focus),
        &render_pieces(&after),
    )
}

pub fn body_hit_context(pieces: &[ParagraphPiece], start: usize, end: usize) -> String {
    let (before, focus, after) = body_hit_parts(pieces, start, end);
    format!("{before}{focus}{after}")
}

fn editable_fields<'a>(
    view: &XmlView,
    paragraph: NodeId,
    scan: &'a EntryFieldScan,
) -> Vec<&'a EntryFieldObservation> {
    if !scan.pairing_usable() || !simple_field_content(view, paragraph) {
        return Vec::new();
    }
    scan.fields
        .iter()
        .filter(|field| {
            field.paragraph == paragraph && is_fill_target_field_type(field.field_type.as_deref())
        })
        .collect()
}

pub fn paragraph_sites(view: &XmlView, paragraph: NodeId, scan: &EntryFieldScan) -> ParagraphSites {
    let boundaries: HashSet<_> = editable_fields(view, paragraph, scan)
        .into_iter()
        .flat_map(|field| [field.begin_ctrl, field.end_ctrl])
        .filter(|id| {
            view.node(*id).is_some_and(|node| {
                node.children
                    .iter()
                    .filter(|part| !matches!(part, Content::Text(_) | Content::CData(_)))
                    .count()
                    == 1
            })
        })
        .collect();
    let mut sites = Vec::new();
    let mut hazards = Vec::new();
    let mut text = String::new();
    let mut length = 0;
    for run in element_children(view, paragraph).filter(|id| is_hp(view, *id, "run")) {
        for part in &view.node(run).unwrap().children {
            let Content::Element(child) = part else {
                if matches!(
                    part,
                    Content::Comment(_) | Content::ProcessingInstruction(_)
                ) {
                    hazards.push(length);
                }
                continue;
            };
            let child = *child;
            if is_hp(view, child, "t")
                && view.node(child).is_some_and(|node| {
                    node.children
                        .iter()
                        .all(|part| matches!(part, Content::Text(_) | Content::CData(_)))
                })
            {
                let value = leading_text(view, child);
                let next = length + value.chars().count();
                sites.push(TextSite {
                    node: child,
                    start: length,
                    end: next,
                });
                text.push_str(&value);
                length = next;
            } else if !boundaries.contains(&child) {
                hazards.push(length);
            }
        }
    }
    ParagraphSites {
        sites,
        hazards,
        text,
    }
}

pub fn field_range_refusal(
    view: &XmlView,
    paragraph: NodeId,
    scan: &EntryFieldScan,
    sites: &ParagraphSites,
    start: usize,
    end: usize,
) -> Option<&'static str> {
    if start > end || end > sites.text.chars().count() {
        return Some("고른 문자 범위가 문단 밖에 있습니다.");
    }
    if sites.sites.is_empty() {
        return Some("이 문단에는 편집 가능한 텍스트가 없습니다.");
    }
    if sites.hazards.iter().any(|position| *position <= end) {
        return Some(REASON_CONTROL_BEFORE);
    }
    for field in editable_fields(view, paragraph, scan) {
        if let Some((low, high)) = simple_field_span(view, field)
            && ((start == end && low <= start && start <= high)
                || (start < end && low < end && start < high))
        {
            return Some(REASON_FIELD_OVERLAP);
        }
    }
    None
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn cell_coordinates_field_offsets_and_control_hazards_share_one_view() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:secPr><hp:colPr/></hp:secPr><hp:switch><hp:chart/></hp:switch><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>A</hp:t><hp:ctrl><hp:fieldBegin id='1' name='field'/></hp:ctrl></hp:run><hp:run><hp:t>B</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl><hp:t>C</hp:t><hp:pic/></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let view = XmlView::parse(xml.replace("<hp:pic/>", "").as_bytes()).unwrap();
        let paragraph = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .find(|id| {
                is_hp(&view, *id, "p")
                    && view
                        .parent(*id)
                        .is_some_and(|parent| is_hp(&view, parent, "subList"))
            })
            .unwrap();
        let path = cell_path(&view, paragraph).unwrap();
        assert_eq!(
            path,
            vec![CellStep {
                parent_paragraph: 0,
                control: 3,
                cell: 0,
                paragraph: 0
            }]
        );
        assert_eq!(selected_paragraph(&view, 0, Some(&path)), Ok(paragraph));
        assert_eq!(paragraph_body(&view, paragraph), "ABC");
        let scan = view.field_occurrences("Contents/section0.xml");
        assert!(scan.pairing_usable());
        assert_eq!(simple_field_span(&view, &scan.fields[0]), Some((1, 2)));
        let pieces = paragraph_pieces(&view, paragraph, &field_marks(&scan));
        assert_eq!(body_hit_context(&pieces, 1, 2), "A[field]C");
        let sites = paragraph_sites(&view, paragraph, &scan);
        assert_eq!(sites.text, "ABC");
        assert!(sites.hazards.is_empty());
        assert_eq!(
            field_range_refusal(&view, paragraph, &scan, &sites, 1, 1),
            Some(REASON_FIELD_OVERLAP)
        );
        let blocked = XmlView::parse(xml.as_bytes()).unwrap();
        let blocked_paragraph = blocked
            .descendants(blocked.root())
            .unwrap()
            .into_iter()
            .find(|id| {
                is_hp(&blocked, *id, "p")
                    && blocked
                        .parent(*id)
                        .is_some_and(|parent| is_hp(&blocked, parent, "subList"))
            })
            .unwrap();
        let blocked_scan = blocked.field_occurrences("Contents/section0.xml");
        let blocked_sites = paragraph_sites(&blocked, blocked_paragraph, &blocked_scan);
        assert_eq!(blocked_sites.hazards, vec![1, 2, 3]);
        assert_eq!(
            field_range_refusal(
                &blocked,
                blocked_paragraph,
                &blocked_scan,
                &blocked_sites,
                0,
                3
            ),
            Some(REASON_CONTROL_BEFORE)
        );
    }
}
