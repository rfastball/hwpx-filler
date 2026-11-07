//! Bookmark block paste stages: locate the target gap, insert the cloned
//! paragraphs with their source text tails, and commit with topology rollback.

use super::{NativeTransferError, fail, paragraph_tail};
use crate::bookmark_region::resolve_bookmark_topology;
use crate::package::HwpxPackage;
use crate::xml_dom::{Content, NodeId, XmlDocument};

/// Root child index before paragraph `destination`, or after the last
/// paragraph and its text tail when `destination` is the paragraph count.
pub(super) fn insertion_point(
    candidate: &XmlDocument,
    paragraphs: &[NodeId],
    destination: usize,
) -> Result<usize, NativeTransferError> {
    let children = &candidate.node(candidate.root).children;
    let found = if destination < paragraphs.len() {
        let before = paragraphs[destination];
        children
            .iter()
            .position(|part| matches!(part, Content::Element(id) if *id == before))
    } else {
        let last = *paragraphs.last().unwrap();
        children
            .iter()
            .position(|part| matches!(part, Content::Element(id) if *id == last))
            .map(|at| {
                at + 1
                    + children[at + 1..]
                        .iter()
                        .take_while(|part| matches!(part, Content::Text(_) | Content::CData(_)))
                        .count()
            })
    };
    found.ok_or_else(|| fail("target-boundary", "target paragraph detached"))
}

pub(super) fn insert_block(
    candidate: &mut XmlDocument,
    source_doc: &XmlDocument,
    block: &[NodeId],
    clones: Vec<NodeId>,
    insertion: usize,
) -> Result<(), NativeTransferError> {
    let mut at = insertion;
    for (source_paragraph, clone) in block.iter().zip(clones) {
        candidate
            .insert_element(candidate.root, at, clone)
            .map_err(|error| fail("write", error.to_string()))?;
        at += 1;
        for tail in paragraph_tail(source_doc, *source_paragraph) {
            candidate.node_mut(candidate.root).children.insert(at, tail);
            at += 1;
        }
    }
    Ok(())
}

/// Store `bytes`, then restore the previous entry when the package topology no longer resolves.
pub(super) fn commit_with_rollback(
    target: &mut HwpxPackage,
    entry: &str,
    bytes: Vec<u8>,
) -> Result<(), NativeTransferError> {
    let slot = target
        .entries
        .iter_mut()
        .find(|item| item.name == entry)
        .ok_or_else(|| fail("missing-entry", "target entry disappeared"))?;
    let previous = std::mem::replace(&mut slot.data, bytes);
    if let Err(error) = resolve_bookmark_topology(target) {
        target
            .entries
            .iter_mut()
            .find(|item| item.name == entry)
            .unwrap()
            .data = previous;
        return Err(fail("target-topology", error.to_string()));
    }
    Ok(())
}
