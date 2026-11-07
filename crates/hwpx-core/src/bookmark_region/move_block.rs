//! Relocation of closed BOOKMARK paragraph blocks.

use super::*;

/// Relocate whole top-level paragraphs containing a closed native BOOKMARK
/// block. The native pair identities and parent relationships must survive.
pub fn move_bookmark_block(
    package: &mut HwpxPackage,
    handle: &BookmarkRegion,
    destination: usize,
) -> Result<(), NativeAdmissionError> {
    let (sections, current, at) = fresh(package, handle)?;
    let region = &current[at];
    let section = &sections[region.section_index];
    let lo = handle.start_paragraph;
    let hi = handle.end_paragraph + 1;
    if destination > section.paragraphs.len() || (lo..=hi).contains(&destination) {
        return Err(error("invalid BOOKMARK block destination"));
    }
    let block = &section.paragraphs[lo..hi];
    require_closed_block(&section.doc, block)?;
    let mut doc = section.doc.clone();
    let detached = detach_paragraphs(&mut doc, block)?;
    let remaining: Vec<_> = doc
        .elements(doc.root)
        .filter(|id| native(&doc, *id, "p"))
        .collect();
    let adjusted = if destination < lo {
        destination
    } else {
        destination - block.len()
    };
    let index = if adjusted < remaining.len() {
        content_index(&doc, doc.root, remaining[adjusted])?
    } else {
        let last = *remaining
            .last()
            .ok_or_else(|| error("missing remaining BOOKMARK paragraph"))?;
        let mut after = content_index(&doc, doc.root, last)? + 1;
        while matches!(
            doc.node(doc.root).children.get(after),
            Some(Content::Text(_) | Content::CData(_))
        ) {
            after += 1;
        }
        after
    };
    let mut insertion = index;
    for (paragraph, tails) in detached {
        doc.insert_element(doc.root, insertion, paragraph)?;
        insertion += 1;
        for tail in tails {
            doc.node_mut(doc.root).children.insert(insertion, tail);
            insertion += 1;
        }
    }
    let (data, after) = candidate(package, &handle.section, doc)?;
    if shape(&after, false) != shape(&current, false) {
        return Err(error("이동하면 기존 책갈피 소속이 달라집니다."));
    }
    replace_entry(package, &handle.section, data)
}

fn require_closed_block(doc: &XmlDocument, block: &[NodeId]) -> Result<(), NativeAdmissionError> {
    let mut begins = HashSet::new();
    let mut ends = HashSet::new();
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            if native(doc, id, "fieldBegin") {
                if let Some(value) = doc.attr(id, "id").filter(|value| !value.is_empty()) {
                    begins.insert(value.to_owned());
                }
            } else if native(doc, id, "fieldEnd")
                && let Some(value) = doc.attr(id, "beginIDRef").filter(|value| !value.is_empty())
            {
                ends.insert(value.to_owned());
            }
        }
    }
    if begins != ends {
        return Err(error(
            "다른 영역이나 필드 경계가 걸친 문단은 이동할 수 없습니다.",
        ));
    }
    Ok(())
}

fn detach_paragraphs(
    doc: &mut XmlDocument,
    block: &[NodeId],
) -> Result<Vec<(NodeId, Vec<Content>)>, NativeAdmissionError> {
    let mut detached = Vec::new();
    for paragraph in block {
        let index = content_index(doc, doc.root, *paragraph)?;
        let children = &mut doc.node_mut(doc.root).children;
        let mut end = index + 1;
        while matches!(
            children.get(end),
            Some(Content::Text(_) | Content::CData(_))
        ) {
            end += 1;
        }
        let mut parts: Vec<_> = children.drain(index..end).collect();
        parts.remove(0);
        doc.node_mut(*paragraph).parent = None;
        detached.push((*paragraph, parts));
    }
    Ok(detached)
}
