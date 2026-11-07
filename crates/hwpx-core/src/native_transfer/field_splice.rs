//! Field paste stages: admit the source occurrence and the simple target run,
//! assemble the replacement runs, swap them in, and commit only a candidate
//! whose Field pairing still resolves.

use super::{
    FieldPasteRequest, NativeTransferError, child_element, fail, import_subtree, native,
    native_run, set_attr,
};
use crate::field_occurrence::{FieldOccurrence, FieldResolution, resolve_field_occurrences};
use crate::lineseg::serialize_modified_section;
use crate::package::HwpxPackage;
use crate::xml_dom::{Content, NodeId, XmlDocument, parse_xml};

/// The requested source occurrence, still paired, still named, still at the requested ID.
pub(super) fn source_occurrence<'r>(
    source_doc: &XmlDocument,
    resolved: &'r FieldResolution,
    request: &FieldPasteRequest<'_>,
) -> Result<&'r FieldOccurrence, NativeTransferError> {
    if !resolved.diagnostics.is_empty() {
        return Err(fail("source-pairing", "source Field pairing is unusable"));
    }
    let occurrence = resolved
        .occurrences
        .get(request.source_ordinal)
        .ok_or_else(|| fail("source-ordinal", "source Field ordinal missing"))?;
    if source_doc.attr(occurrence.begin, "id") != request.source_pairing_id {
        return Err(fail(
            "source-pairing-changed",
            "source Field pairing changed",
        ));
    }
    if occurrence
        .raw_name
        .as_deref()
        .is_none_or(|name| name.trim().is_empty())
    {
        return Err(fail("source-name", "source Field name missing"));
    }
    Ok(occurrence)
}

/// The single run and plain text node of a simple target paragraph.
pub(super) struct TargetSlot {
    pub paragraph: NodeId,
    pub run: NodeId,
    pub text: NodeId,
}
pub(super) fn target_slot(
    candidate: &XmlDocument,
    request: &FieldPasteRequest<'_>,
) -> Result<TargetSlot, NativeTransferError> {
    let paragraphs = candidate
        .elements(candidate.root)
        .filter(|id| native(candidate, *id, "p"))
        .collect::<Vec<_>>();
    let paragraph = *paragraphs
        .get(request.target_paragraph)
        .ok_or_else(|| fail("target-paragraph", "target paragraph missing"))?;
    if request.start > request.end {
        return Err(fail("target-range", "invalid target range"));
    }
    let runs = candidate
        .elements(paragraph)
        .filter(|id| native(candidate, *id, "run"))
        .collect::<Vec<_>>();
    let run = if runs.len() == 1 {
        runs[0]
    } else {
        return Err(fail("target-complex", "target paragraph is complex"));
    };
    let text = child_element(candidate, run, "t")
        .ok_or_else(|| fail("target-complex", "target paragraph is complex"))?;
    if candidate.node(text).children.iter().any(|part| {
        matches!(
            part,
            Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
        )
    }) {
        return Err(fail("target-complex", "target paragraph is complex"));
    }
    Ok(TargetSlot {
        paragraph,
        run,
        text,
    })
}

/// Target text split at byte offsets `left..right` of `original`.
pub(super) struct TargetCut<'a> {
    pub run: NodeId,
    pub original: &'a str,
    pub left: usize,
    pub right: usize,
}
/// One native control side copied from the source occurrence.
struct ControlSide {
    run: NodeId,
    ctrl: NodeId,
    marker: &'static str,
    pairing_key: &'static str,
    invalid: &'static str,
}

fn cut_piece(candidate: &mut XmlDocument, run: NodeId, text: &str) -> NodeId {
    let piece = candidate.clone_subtree(run);
    let t = child_element(candidate, piece, "t").unwrap();
    candidate.node_mut(t).children = vec![Content::Text(text.into())];
    piece
}
fn imported_control(
    candidate: &mut XmlDocument,
    source_doc: &XmlDocument,
    side: &ControlSide,
    (next, second): &(String, String),
) -> Result<NodeId, NativeTransferError> {
    let run = native_run(candidate, source_doc, side.run);
    let ctrl = import_subtree(candidate, source_doc, side.ctrl);
    let marker = child_element(candidate, ctrl, side.marker)
        .ok_or_else(|| fail("source-control", side.invalid))?;
    set_attr(candidate, marker, side.pairing_key, next);
    set_attr(candidate, marker, "fieldid", second);
    candidate
        .insert_element(run, 0, ctrl)
        .map_err(|error| fail("write", error.to_string()))?;
    Ok(run)
}
fn value_run(
    candidate: &mut XmlDocument,
    source_doc: &XmlDocument,
    text: NodeId,
) -> Result<NodeId, NativeTransferError> {
    let source_run = source_doc
        .parent(text)
        .ok_or_else(|| fail("source-control", "missing source text run"))?;
    let fresh = native_run(candidate, source_doc, source_run);
    let cloned = import_subtree(candidate, source_doc, text);
    candidate
        .insert_element(fresh, 0, cloned)
        .map_err(|error| fail("write", error.to_string()))?;
    Ok(fresh)
}
/// prefix, optional begin control, copied value runs, optional end control, suffix.
pub(super) fn replacement_runs(
    candidate: &mut XmlDocument,
    source_doc: &XmlDocument,
    occurrence: &FieldOccurrence,
    texts: Vec<NodeId>,
    cut: &TargetCut<'_>,
    ids: Option<&(String, String)>,
) -> Result<Vec<NodeId>, NativeTransferError> {
    let mut new_runs = Vec::new();
    if cut.left != 0 {
        new_runs.push(cut_piece(candidate, cut.run, &cut.original[..cut.left]));
    }
    if let Some(ids) = ids {
        let begin = ControlSide {
            run: occurrence.begin_run,
            ctrl: occurrence.begin_ctrl,
            marker: "fieldBegin",
            pairing_key: "id",
            invalid: "invalid begin control",
        };
        new_runs.push(imported_control(candidate, source_doc, &begin, ids)?);
    }
    for text in texts {
        new_runs.push(value_run(candidate, source_doc, text)?);
    }
    if let Some(ids) = ids {
        let end = ControlSide {
            run: occurrence.end_run,
            ctrl: occurrence.end_ctrl,
            marker: "fieldEnd",
            pairing_key: "beginIDRef",
            invalid: "invalid end control",
        };
        new_runs.push(imported_control(candidate, source_doc, &end, ids)?);
    }
    if cut.right < cut.original.len() {
        new_runs.push(cut_piece(candidate, cut.run, &cut.original[cut.right..]));
    }
    Ok(new_runs)
}

pub(super) fn swap_run(
    candidate: &mut XmlDocument,
    paragraph: NodeId,
    run: NodeId,
    new_runs: Vec<NodeId>,
) -> Result<(), NativeTransferError> {
    let position = candidate
        .node(paragraph)
        .children
        .iter()
        .position(|part| matches!(part, Content::Element(id) if *id == run))
        .ok_or_else(|| fail("write", "target run detached"))?;
    candidate
        .remove_element_with_tail(run)
        .map_err(|error| fail("write", error.to_string()))?;
    for (offset, fresh) in new_runs.into_iter().enumerate() {
        candidate
            .insert_element(paragraph, position + offset, fresh)
            .map_err(|error| fail("write", error.to_string()))?;
    }
    Ok(())
}

pub(super) fn commit_paired(
    target: &mut HwpxPackage,
    entry: &str,
    candidate: &mut XmlDocument,
) -> Result<(), NativeTransferError> {
    let bytes =
        serialize_modified_section(candidate).map_err(|error| fail("write", error.to_string()))?;
    let checked = parse_xml(&bytes).map_err(|error| fail("write", error.to_string()))?;
    if !resolve_field_occurrences(entry, &checked)
        .diagnostics
        .is_empty()
    {
        return Err(fail(
            "target-pairing",
            "target Field pairing became unusable",
        ));
    }
    let slot = target
        .entries
        .iter_mut()
        .find(|item| item.name == entry)
        .ok_or_else(|| fail("missing-entry", "target entry disappeared"))?;
    slot.data = bytes;
    Ok(())
}
