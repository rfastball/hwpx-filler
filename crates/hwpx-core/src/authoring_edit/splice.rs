//! Tree projection for one token replacement: copy the covered runs into
//! before/inside/after slices and bracket the inside slice with Field boundary
//! runs. Which parts survive a slice is decided by [`Window`] alone.

use super::{Layout, Piece, TokenEditError, TokenFieldEdit, distinct, invalid, local, t_value};
use super::{elements, slice_chars};
use crate::native_admission::{copy_run_attributes, native_element};
use crate::xml_dom::{Content, NodeId, XmlDocument};

/// Keep decision for the character window `[lo, hi)`. Width-one parts survive
/// inside the window; zero-width parts at an edge survive only when that edge is kept.
#[derive(Clone, Copy)]
struct Window {
    lo: usize,
    hi: usize,
    keep_lo: bool,
    keep_hi: bool,
}

impl Window {
    fn outer(lo: usize, hi: usize) -> Self {
        Self {
            lo,
            hi,
            keep_lo: true,
            keep_hi: true,
        }
    }
    fn inner(lo: usize, hi: usize) -> Self {
        Self {
            lo,
            hi,
            keep_lo: false,
            keep_hi: false,
        }
    }
    fn wide(self, pos: usize) -> bool {
        self.lo <= pos && pos < self.hi
    }
    fn zero(self, pos: usize) -> bool {
        if self.lo < pos && pos < self.hi {
            true
        } else if pos == self.lo {
            self.keep_lo
        } else if pos == self.hi {
            self.keep_hi
        } else {
            false
        }
    }
    fn element(self, pos: usize, width: usize) -> bool {
        if width == 0 {
            self.zero(pos)
        } else {
            self.wide(pos)
        }
    }
    fn kept_chars(self, value: &str, pos: usize) -> String {
        value
            .chars()
            .enumerate()
            .filter(|(offset, _)| self.wide(pos + offset))
            .map(|(_, ch)| ch)
            .collect()
    }
}

fn append(doc: &mut XmlDocument, parent: NodeId, part: Content) {
    if let Content::Element(child) = part {
        doc.node_mut(child).parent = Some(parent);
        doc.node_mut(parent).children.push(Content::Element(child));
    } else {
        doc.node_mut(parent).children.push(part);
    }
}
fn clone_empty(doc: &mut XmlDocument, source: NodeId) -> NodeId {
    let node = doc.node(source).clone();
    let clone = doc.new_element(node.name, node.attributes);
    doc.node_mut(clone).namespaces = node.namespaces;
    clone
}
fn inline_width(doc: &XmlDocument, child: NodeId) -> usize {
    usize::from(matches!(local(doc, child), "tab" | "lineBreak"))
}
fn blank(parts: &[Content]) -> bool {
    parts.iter().all(
        |part| matches!(part, Content::Text(value) | Content::CData(value) if value.is_empty()),
    )
}
fn has_markup(doc: &XmlDocument, id: NodeId) -> bool {
    doc.node(id).children.iter().any(|part| {
        matches!(
            part,
            Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
        )
    })
}
/// Extend the trailing text child, or start one; kept characters of one source
/// part are contiguous, so this equals appending them one at a time.
fn push_text(doc: &mut XmlDocument, out: NodeId, kept: String) {
    if kept.is_empty() {
        return;
    }
    if let Some(Content::Text(last)) = doc.node_mut(out).children.last_mut() {
        last.push_str(&kept);
    } else {
        append(doc, out, Content::Text(kept));
    }
}
/// Copy the text tail that follows `parts[at - 1]` when it is kept, and return
/// the index of the first non-text part.
fn copy_tail(
    doc: &mut XmlDocument,
    out: NodeId,
    parts: &[Content],
    mut at: usize,
    keep: bool,
) -> usize {
    while let Some(Content::Text(value) | Content::CData(value)) = parts.get(at) {
        if keep {
            append(doc, out, Content::Text(value.clone()));
        }
        at += 1;
    }
    at
}

fn clip_t(doc: &mut XmlDocument, text: NodeId, base: usize, window: Window) -> Option<NodeId> {
    let parts = doc.node(text).children.clone();
    if blank(&parts) {
        return window.zero(base).then(|| clone_empty(doc, text));
    }
    let out = clone_empty(doc, text);
    let mut pos = base;
    for part in parts {
        match part {
            Content::Text(value) | Content::CData(value) => {
                push_text(doc, out, window.kept_chars(&value, pos));
                pos += value.chars().count();
            }
            Content::Element(child) => {
                let width = inline_width(doc, child);
                if window.element(pos, width) {
                    let copy = doc.clone_subtree(child);
                    append(doc, out, Content::Element(copy));
                }
                pos += width;
            }
            other @ (Content::Comment(_) | Content::ProcessingInstruction(_)) => {
                if window.zero(pos) {
                    append(doc, out, other);
                }
            }
        }
    }
    (!doc.node(out).children.is_empty()).then_some(out)
}

fn clip_run(doc: &mut XmlDocument, run: NodeId, base: usize, window: Window) -> Option<NodeId> {
    let parts = doc.node(run).children.clone();
    let out = clone_empty(doc, run);
    let mut pos = base;
    let mut at = 0;
    while at < parts.len() {
        let keep = match &parts[at] {
            Content::Element(child) if local(doc, *child) == "t" => {
                if let Some(piece) = clip_t(doc, *child, pos, window) {
                    append(doc, out, Content::Element(piece));
                }
                pos += t_value(doc, *child).0.chars().count();
                false
            }
            Content::Element(child) => {
                let width = inline_width(doc, *child);
                let keep = window.element(pos, width);
                if keep {
                    let copy = doc.clone_subtree(*child);
                    append(doc, out, Content::Element(copy));
                }
                pos += width;
                keep
            }
            other @ (Content::Comment(_) | Content::ProcessingInstruction(_)) => {
                let keep = window.zero(pos);
                if keep {
                    append(doc, out, other.clone());
                }
                keep
            }
            Content::Text(_) | Content::CData(_) => false,
        };
        at = copy_tail(doc, out, &parts, at + 1, keep);
    }
    has_markup(doc, out).then_some(out)
}
fn clip_runs(
    doc: &mut XmlDocument,
    layout: &Layout,
    runs: &[NodeId],
    window: Window,
) -> Vec<NodeId> {
    runs.iter()
        .filter_map(|run| clip_run(doc, *run, layout.run_base[run], window))
        .collect()
}

fn text_run(doc: &mut XmlDocument, source: NodeId, value: &str) -> NodeId {
    let run = native_element(doc, "run", &[]);
    copy_run_attributes(doc, source, run);
    let text = native_element(doc, "t", &[]);
    append(doc, text, Content::Text(value.to_owned()));
    append(doc, run, Content::Element(text));
    run
}
fn simple_slices(doc: &mut XmlDocument, pieces: &[&Piece], lo: usize, hi: usize) -> Vec<NodeId> {
    let mut out = Vec::new();
    for piece in pieces {
        let start = piece.start.max(lo);
        let end = piece.end.min(hi);
        if start >= end {
            continue;
        }
        let text = elements(doc, piece.run)
            .find(|id| local(doc, *id) == "t")
            .unwrap();
        let source = t_value(doc, text).0;
        let part = slice_chars(&source, start - piece.start, end - piece.start);
        out.push(text_run(doc, piece.run, &part));
    }
    out
}

/// Field identity shared by the begin and end boundary runs.
struct Marks<'a> {
    first: NodeId,
    last: NodeId,
    name: &'a str,
    begin_id: &'a str,
    field_id: &'a str,
}
fn boundary_run(doc: &mut XmlDocument, marks: &Marks<'_>, begin: bool) -> NodeId {
    let run = native_element(doc, "run", &[]);
    let source = if begin { marks.first } else { marks.last };
    copy_run_attributes(doc, source, run);
    let ctrl = native_element(doc, "ctrl", &[]);
    let marker = if begin {
        native_element(
            doc,
            "fieldBegin",
            &[
                ("id", marks.begin_id),
                ("type", "CLICK_HERE"),
                ("name", marks.name),
                ("editable", "1"),
                ("dirty", "1"),
                ("zorder", "-1"),
                ("fieldid", marks.field_id),
                ("metaTag", ""),
            ],
        )
    } else {
        native_element(
            doc,
            "fieldEnd",
            &[("beginIDRef", marks.begin_id), ("fieldid", marks.field_id)],
        )
    };
    append(doc, ctrl, Content::Element(marker));
    append(doc, run, Content::Element(ctrl));
    run
}
/// before-slice, begin run, inside-slice, end run, after-slice — in arena order.
fn bracket(
    doc: &mut XmlDocument,
    edit: &TokenFieldEdit<'_>,
    marks: &Marks<'_>,
    mut slice: impl FnMut(&mut XmlDocument, Window) -> Vec<NodeId>,
) -> Vec<NodeId> {
    let mut created = slice(doc, Window::outer(0, edit.start));
    created.push(boundary_run(doc, marks, true));
    created.extend(slice(doc, Window::inner(edit.start, edit.end)));
    created.push(boundary_run(doc, marks, false));
    created.extend(slice(doc, Window::outer(edit.end, usize::MAX)));
    created
}

pub(super) fn replacement(
    doc: &mut XmlDocument,
    layout: &Layout,
    covered: &[&Piece],
    edit: &TokenFieldEdit<'_>,
    begin_id: &str,
    field_id: &str,
) -> Result<(), TokenEditError> {
    let runs = distinct(covered.iter().map(|piece| piece.run));
    let marks = Marks {
        first: runs[0],
        last: *runs.last().unwrap(),
        name: edit.name,
        begin_id,
        field_id,
    };
    let paragraph = doc
        .parent(marks.first)
        .ok_or_else(|| invalid("detached token run"))?;
    let index = doc
        .node(paragraph)
        .children
        .iter()
        .position(|part| matches!(part, Content::Element(id) if *id == marks.first))
        .ok_or_else(|| invalid("detached token run"))?;
    let created = if covered.iter().all(|piece| piece.simple) {
        bracket(doc, edit, &marks, |doc, window| {
            simple_slices(doc, covered, window.lo, window.hi)
        })
    } else {
        bracket(doc, edit, &marks, |doc, window| {
            clip_runs(doc, layout, &runs, window)
        })
    };
    for run in runs {
        doc.remove_element_with_tail(run)?;
    }
    for (offset, run) in created.into_iter().enumerate() {
        doc.insert_element(paragraph, index + offset, run)?;
    }
    Ok(())
}
