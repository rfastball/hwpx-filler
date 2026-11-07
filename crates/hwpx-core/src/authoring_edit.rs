//! Guarded, pure-byte replacement of one authoring token with a native Field.

mod splice;

use crate::lineseg::serialize_modified_section;
use crate::text_extract::{decimal_digit, read_inline_text};
use crate::text_model::HP_NS;
use crate::xml_dom::{Content, NodeId, XmlDocument, XmlError, parse_xml};
use crate::xml_view::path_for_doc;
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenEditError(pub String);
impl fmt::Display for TokenEditError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TokenEditError {}
impl From<XmlError> for TokenEditError {
    fn from(value: XmlError) -> Self {
        Self(value.0)
    }
}
fn invalid(message: impl Into<String>) -> TokenEditError {
    TokenEditError(message.into())
}

pub struct TokenFieldEdit<'a> {
    pub paragraph_path: &'a str,
    pub start: usize,
    pub end: usize,
    pub literal: &'a str,
    pub name: &'a str,
}

#[derive(Clone)]
struct Piece {
    start: usize,
    end: usize,
    run: NodeId,
    simple: bool,
    child_index: usize,
}
struct Layout {
    text: String,
    pieces: Vec<Piece>,
    events: Vec<usize>,
    run_base: HashMap<NodeId, usize>,
}
fn native(doc: &XmlDocument, id: NodeId, local: &str) -> bool {
    doc.node(id).name.is(HP_NS, local)
}
pub(crate) fn document_text(doc: &XmlDocument) -> (String, Vec<String>) {
    let mut text = String::new();
    let mut unmodelled = Vec::new();
    for id in doc.descendants(doc.root) {
        match doc.node(id).name.local.as_str() {
            "t" => {
                let part = read_inline_text(doc, id);
                text.push_str(&part.text);
                unmodelled.extend(part.unmodelled);
            }
            "tab" | "lineBreak"
                if doc
                    .parent(id)
                    .is_some_and(|parent| local(doc, parent) == "run") =>
            {
                text.push(if local(doc, id) == "tab" { '\t' } else { '\n' });
            }
            _ => {}
        }
    }
    (text, unmodelled)
}
fn elements(doc: &XmlDocument, id: NodeId) -> impl Iterator<Item = NodeId> + '_ {
    doc.elements(id)
}
fn child_nodes(doc: &XmlDocument, id: NodeId) -> impl Iterator<Item = Option<NodeId>> + '_ {
    doc.node(id).children.iter().filter_map(|part| match part {
        Content::Element(child) => Some(Some(*child)),
        Content::Comment(_) | Content::ProcessingInstruction(_) => Some(None),
        Content::Text(_) | Content::CData(_) => None,
    })
}
fn local(doc: &XmlDocument, id: NodeId) -> &str {
    &doc.node(id).name.local
}
fn simple_text(doc: &XmlDocument, run: NodeId) -> bool {
    let mut texts = Vec::new();
    let mut controls = 0;
    let mut others = 0;
    for child in elements(doc, run) {
        match local(doc, child) {
            "t" => texts.push(child),
            "ctrl" => controls += 1,
            _ => others += 1,
        }
    }
    texts.len() == 1
        && controls == 0
        && others == 0
        && doc
            .node(texts[0])
            .children
            .iter()
            .all(|part| matches!(part, Content::Text(_) | Content::CData(_)))
}
fn t_value(doc: &XmlDocument, text: NodeId) -> (String, Vec<usize>) {
    let mut value = String::new();
    let mut events = Vec::new();
    let mut length = 0;
    for part in &doc.node(text).children {
        match part {
            Content::Text(text) | Content::CData(text) => {
                value.push_str(text);
                length += text.chars().count();
            }
            Content::Element(child) => {
                events.push(length);
                match local(doc, *child) {
                    "tab" => {
                        value.push('\t');
                        length += 1;
                    }
                    "lineBreak" => {
                        value.push('\n');
                        length += 1;
                    }
                    _ => {}
                }
            }
            Content::Comment(_) | Content::ProcessingInstruction(_) => events.push(length),
        }
    }
    (value, events)
}
fn layout(doc: &XmlDocument, paragraph: NodeId) -> Layout {
    let mut result = Layout {
        text: String::new(),
        pieces: Vec::new(),
        events: Vec::new(),
        run_base: HashMap::new(),
    };
    let mut depth = 0i32;
    let mut length = 0usize;
    for (child_index, child) in child_nodes(doc, paragraph).enumerate() {
        let Some(run) = child else { continue };
        if local(doc, run) != "run" {
            continue;
        }
        let simple = simple_text(doc, run);
        result.run_base.insert(run, length);
        for item in child_nodes(doc, run) {
            let Some(node) = item else {
                if depth == 0 {
                    result.events.push(length);
                }
                continue;
            };
            match local(doc, node) {
                "ctrl" => {
                    let mut boundary = false;
                    for control in elements(doc, node) {
                        match local(doc, control) {
                            "fieldBegin" => {
                                depth += 1;
                                boundary = true;
                            }
                            "fieldEnd" => {
                                depth = (depth - 1).max(0);
                                boundary = true;
                            }
                            _ => {}
                        }
                    }
                    if depth == 0 && !boundary {
                        result.events.push(length);
                    }
                }
                "t" if depth == 0 => {
                    let start = length;
                    let (value, events) = t_value(doc, node);
                    length += value.chars().count();
                    result.text.push_str(&value);
                    result.pieces.push(Piece {
                        start,
                        end: length,
                        run,
                        simple,
                        child_index,
                    });
                    result
                        .events
                        .extend(events.into_iter().map(|at| start + at));
                }
                "tab" | "lineBreak" if depth == 0 => {
                    result.events.push(length);
                    result.text.push(if local(doc, node) == "tab" {
                        '\t'
                    } else {
                        '\n'
                    });
                    length += 1;
                }
                _ if depth == 0 => result.events.push(length),
                _ => {}
            }
        }
    }
    result
}

fn is_extra_digit(ch: char) -> bool {
    const RANGES: &[(u32, u32)] = &[
        (0xB2, 0xB3),
        (0xB9, 0xB9),
        (0x1369, 0x1371),
        (0x19DA, 0x19DA),
        (0x2070, 0x2070),
        (0x2074, 0x2079),
        (0x2080, 0x2089),
        (0x2460, 0x2468),
        (0x2474, 0x247C),
        (0x2488, 0x2490),
        (0x24EA, 0x24EA),
        (0x24F5, 0x24FD),
        (0x24FF, 0x24FF),
        (0x2776, 0x277E),
        (0x2780, 0x2788),
        (0x278A, 0x2792),
        (0x10A40, 0x10A43),
        (0x10E60, 0x10E68),
        (0x11052, 0x1105A),
        (0x1F100, 0x1F10A),
    ];
    RANGES
        .iter()
        .any(|(start, end)| (*start..=*end).contains(&(ch as u32)))
}
/// Normalized ASCII digits of one numeric ID attribute; `None` when the value
/// is not numeric at all, an error when it is numeric but not a plain integer.
fn decimal_id(key: &str, value: &str) -> Result<Option<String>, TokenEditError> {
    let digits = value.trim_start_matches('-');
    if digits.is_empty()
        || !digits
            .chars()
            .all(|ch| decimal_digit(ch).is_some() || is_extra_digit(ch))
    {
        return Ok(None);
    }
    if value.starts_with("--") || digits.chars().any(is_extra_digit) {
        return Err(invalid(format!("invalid integer ID attribute: {key}")));
    }
    let ascii: String = digits
        .chars()
        .map(|ch| char::from(b'0' + decimal_digit(ch).unwrap() as u8))
        .collect();
    let number = ascii.trim_start_matches('0');
    Ok(Some(
        if number.is_empty() { "0" } else { number }.to_owned(),
    ))
}
pub(crate) fn max_numeric_id(doc: &XmlDocument) -> Result<String, TokenEditError> {
    let mut max = "0".to_owned();
    for id in doc.descendants(doc.root) {
        for key in ["id", "fieldid", "beginIDRef", "instId", "endIDRef"] {
            let Some(value) = doc.attr(id, key) else {
                continue;
            };
            let Some(number) = decimal_id(key, value)? else {
                continue;
            };
            if (number.len(), number.as_str()) > (max.len(), max.as_str()) {
                max = number;
            }
        }
    }
    Ok(max)
}
pub(crate) fn add_one(value: &mut String) {
    let mut digits = value.as_bytes().to_vec();
    for digit in digits.iter_mut().rev() {
        if *digit < b'9' {
            *digit += 1;
            *value = String::from_utf8(digits).unwrap();
            return;
        }
        *digit = b'0';
    }
    digits.insert(0, b'1');
    *value = String::from_utf8(digits).unwrap();
}

fn slice_chars(value: &str, lo: usize, hi: usize) -> String {
    value.chars().skip(lo).take(hi.saturating_sub(lo)).collect()
}
fn distinct<T: PartialEq>(items: impl Iterator<Item = T>) -> Vec<T> {
    let mut out = Vec::new();
    for item in items {
        if !out.contains(&item) {
            out.push(item);
        }
    }
    out
}

fn unique_paragraph(doc: &XmlDocument, path: &str) -> Result<NodeId, TokenEditError> {
    let paragraphs: Vec<_> = doc
        .descendants(doc.root)
        .into_iter()
        .filter(|id| native(doc, *id, "p") && path_for_doc(doc, *id) == path)
        .collect();
    if paragraphs.len() != 1 {
        return Err(invalid("token paragraph path is absent or ambiguous"));
    }
    Ok(paragraphs[0])
}
fn check_selection(layout: &Layout, edit: &TokenFieldEdit<'_>) -> Result<(), TokenEditError> {
    if edit.start >= edit.end
        || edit.end > layout.text.chars().count()
        || slice_chars(&layout.text, edit.start, edit.end) != edit.literal
    {
        return Err(invalid("token selection does not match source text"));
    }
    Ok(())
}
fn covered_pieces<'l>(
    layout: &'l Layout,
    edit: &TokenFieldEdit<'_>,
) -> Result<Vec<&'l Piece>, TokenEditError> {
    let covered: Vec<_> = layout
        .pieces
        .iter()
        .filter(|piece| piece.start < edit.end && piece.end > edit.start)
        .collect();
    if covered.is_empty()
        || layout
            .events
            .iter()
            .any(|at| edit.start <= *at && *at < edit.end)
    {
        return Err(invalid("token selection intersects unsupported content"));
    }
    Ok(covered)
}
fn ensure_safe_lane(doc: &XmlDocument, covered: &[&Piece]) -> Result<(), TokenEditError> {
    let runs = distinct(covered.iter().map(|piece| piece.run));
    let indexes = distinct(covered.iter().map(|piece| piece.child_index));
    let char_prs: HashSet<_> = runs
        .iter()
        .map(|run| doc.attr(*run, "charPrIDRef"))
        .collect();
    let same_format = runs.len() == 1 || (char_prs.len() == 1 && !char_prs.contains(&None));
    let contiguous = indexes.windows(2).all(|pair| pair[1] == pair[0] + 1);
    let has_field = runs.iter().any(|run| {
        doc.descendants(*run)
            .into_iter()
            .any(|id| native(doc, id, "fieldBegin") || native(doc, id, "fieldEnd"))
    });
    if !same_format || !contiguous || has_field {
        return Err(invalid("token selection is not a safe native Field lane"));
    }
    Ok(())
}

fn apply_one(
    doc: &mut XmlDocument,
    edit: &TokenFieldEdit<'_>,
    begin_id: &str,
    field_id: &str,
) -> Result<(), TokenEditError> {
    let paragraph = unique_paragraph(doc, edit.paragraph_path)?;
    let layout = layout(doc, paragraph);
    check_selection(&layout, edit)?;
    let covered = covered_pieces(&layout, edit)?;
    ensure_safe_lane(doc, &covered)?;
    splice::replacement(doc, &layout, &covered, edit, begin_id, field_id)
}

type FieldMarkers<'d> = HashMap<&'d str, Vec<NodeId>>;
fn field_markers(after: &XmlDocument) -> (FieldMarkers<'_>, FieldMarkers<'_>) {
    let mut begins: FieldMarkers<'_> = HashMap::new();
    let mut ends: FieldMarkers<'_> = HashMap::new();
    for id in after.descendants(after.root) {
        if native(after, id, "fieldBegin") {
            if let Some(key) = after.attr(id, "id") {
                begins.entry(key).or_default().push(id);
            }
        } else if native(after, id, "fieldEnd")
            && let Some(key) = after.attr(id, "beginIDRef")
        {
            ends.entry(key).or_default().push(id);
        }
    }
    (begins, ends)
}
/// Each generated pair must appear exactly once with its name, type and Field ID.
fn verify_generated_fields(
    after: &XmlDocument,
    generated: Vec<(&str, String, String)>,
) -> Result<(), TokenEditError> {
    let (begins, ends) = field_markers(after);
    for (name, begin_id, field_id) in generated {
        let begin = begins.get(begin_id.as_str());
        let end = ends.get(begin_id.as_str());
        if begin.is_none_or(|nodes| nodes.len() != 1)
            || end.is_none_or(|nodes| nodes.len() != 1)
            || after.attr(begin.unwrap()[0], "name") != Some(name)
            || after.attr(begin.unwrap()[0], "type") != Some("CLICK_HERE")
            || after.attr(end.unwrap()[0], "fieldid") != Some(field_id.as_str())
        {
            return Err(invalid("token compilation Field postcondition failed"));
        }
    }
    Ok(())
}

/// Compile verified depth-zero tokens in source order with one private XML arena.
/// Every input coordinate refers to the original paragraph text. Returned bytes
/// are validated as a whole; callers commit them only after success.
pub fn compile_field_tokens(
    source: &[u8],
    edits: &[TokenFieldEdit<'_>],
) -> Result<Vec<u8>, TokenEditError> {
    if edits.is_empty() {
        return Ok(source.to_vec());
    }
    let mut doc = parse_xml(source)?;
    let before_text = document_text(&doc);
    let mut next_id = max_numeric_id(&doc)?;
    let mut consumed: HashMap<&str, usize> = HashMap::new();
    let mut generated = Vec::with_capacity(edits.len());
    for edit in edits {
        let shift = *consumed.get(edit.paragraph_path).unwrap_or(&0);
        let start = edit
            .start
            .checked_sub(shift)
            .ok_or_else(|| invalid("token selection moved before paragraph start"))?;
        let end = edit
            .end
            .checked_sub(shift)
            .ok_or_else(|| invalid("token selection moved before paragraph start"))?;
        let current = TokenFieldEdit {
            paragraph_path: edit.paragraph_path,
            start,
            end,
            literal: edit.literal,
            name: edit.name,
        };
        add_one(&mut next_id);
        let begin_id = next_id.clone();
        add_one(&mut next_id);
        let field_id = next_id.clone();
        apply_one(&mut doc, &current, &begin_id, &field_id)?;
        *consumed.entry(edit.paragraph_path).or_default() += edit.literal.chars().count();
        generated.push((edit.name, begin_id, field_id));
    }
    let bytes = serialize_modified_section(&mut doc)?;
    let after = parse_xml(&bytes)?;
    if document_text(&after) != before_text {
        return Err(invalid("token compilation changed surrounding text"));
    }
    verify_generated_fields(&after, generated)?;
    Ok(bytes)
}

/// Compile one token via the same guarded batch path.
pub fn compile_field_token(
    source: &[u8],
    edit: &TokenFieldEdit<'_>,
) -> Result<Vec<u8>, TokenEditError> {
    compile_field_tokens(source, std::slice::from_ref(edit))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    const HS: &str = "http://www.hancom.co.kr/hwpml/2011/section";
    fn section(body: &str) -> Vec<u8> {
        format!("<hs:sec xmlns:hs='{HS}' xmlns:hp='{HP_NS}'><hp:p>{body}</hp:p></hs:sec>")
            .into_bytes()
    }
    fn edit<'a>(literal: &'a str, name: &'a str, start: usize) -> TokenFieldEdit<'a> {
        TokenFieldEdit {
            paragraph_path: "/hs:sec/hp:p",
            start,
            end: start + literal.chars().count(),
            literal,
            name,
        }
    }

    #[test]
    fn simple_and_composite_compile_keep_text_style_ids_and_zero_width_marker() {
        let source = section("<hp:run charPrIDRef='7'><hp:t>앞 {{계약명}} 뒤</hp:t></hp:run>");
        let bytes = compile_field_token(&source, &edit("{{계약명}}", "계약명", 2)).unwrap();
        let doc = parse_xml(&bytes).unwrap();
        assert_eq!(doc.iter_text(doc.root), "앞 {{계약명}} 뒤");
        let begin = doc
            .descendants(doc.root)
            .into_iter()
            .find(|id| native(&doc, *id, "fieldBegin"))
            .unwrap();
        let end = doc
            .descendants(doc.root)
            .into_iter()
            .find(|id| native(&doc, *id, "fieldEnd"))
            .unwrap();
        assert_eq!(doc.attr(begin, "name"), Some("계약명"));
        assert_eq!(doc.attr(begin, "type"), Some("CLICK_HERE"));
        assert_eq!(doc.attr(begin, "id"), doc.attr(end, "beginIDRef"));
        assert!(
            doc.descendants(doc.root)
                .into_iter()
                .filter(|id| native(&doc, *id, "run"))
                .all(|run| doc.attr(run, "charPrIDRef") == Some("7"))
        );

        let source = section(
            "<hp:run charPrIDRef='7' custom='left'><hp:t id='9000'>{{계약</hp:t></hp:run><hp:run charPrIDRef='7' custom='right'><hp:t>명}}</hp:t></hp:run>",
        );
        let bytes = compile_field_token(&source, &edit("{{계약명}}", "계약명", 0)).unwrap();
        let doc = parse_xml(&bytes).unwrap();
        let begin = doc
            .descendants(doc.root)
            .into_iter()
            .find(|id| native(&doc, *id, "fieldBegin"))
            .unwrap();
        assert_eq!(doc.attr(begin, "id"), Some("9001"));
        assert_eq!(doc.iter_text(doc.root), "{{계약명}}");
        let values: Vec<_> = doc
            .descendants(doc.root)
            .into_iter()
            .filter(|id| {
                native(&doc, *id, "run")
                    && elements(&doc, *id).any(|child| native(&doc, child, "t"))
            })
            .map(|run| {
                (
                    doc.attr(run, "custom").unwrap().to_owned(),
                    doc.iter_text(run),
                )
            })
            .collect();
        assert_eq!(
            values,
            [
                ("left".into(), "{{계약".into()),
                ("right".into(), "명}}".into())
            ]
        );

        let source = section(
            "<hp:run charPrIDRef='7'><hp:t marker='BEFORE'/><hp:t>{{계약명}}</hp:t><hp:t marker='AFTER'/></hp:run>",
        );
        let bytes = compile_field_token(&source, &edit("{{계약명}}", "계약명", 0)).unwrap();
        let doc = parse_xml(&bytes).unwrap();
        let ids = doc.descendants(doc.root);
        let marker = ids
            .iter()
            .position(|id| doc.attr(*id, "marker") == Some("BEFORE"))
            .unwrap();
        let begin = ids
            .iter()
            .position(|id| native(&doc, *id, "fieldBegin"))
            .unwrap();
        assert!(marker < begin);
        assert!(
            ids.iter()
                .any(|id| doc.attr(*id, "marker") == Some("AFTER"))
        );
    }

    #[test]
    fn unsafe_selection_refuses_without_returning_candidate_bytes() {
        let source = section("<hp:run charPrIDRef='7'><hp:t>{{계<hp:tab/>약}}</hp:t></hp:run>");
        assert!(compile_field_token(&source, &edit("{{계\t약}}", "계약", 0)).is_err());
        assert!(compile_field_token(&source, &edit("{{계약}}", "계약", 0)).is_err());
    }
}
