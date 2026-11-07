//! Bookmarked paragraph extent admission without mutating source content.

use super::*;

#[derive(Clone, Debug)]
pub(crate) struct BookmarkRemovalPlan {
    pub blockers: Vec<BookmarkRemovalBlocker>,
    pub protected_markers: Vec<NodeId>,
    pub removed_begins: Vec<NodeId>,
}
pub(crate) struct BookmarkPlanPolicy {
    pub topology_usable: bool,
    pub metadata_usable: bool,
    pub field_pairing_usable: bool,
    pub reject_whole_section: bool,
    pub reject_section_definition: bool,
}
fn bookmark_block(
    kind: BookmarkRemovalBlockerKind,
    message: impl Into<String>,
) -> BookmarkRemovalBlocker {
    BookmarkRemovalBlocker {
        kind,
        detail: vec![message.into()],
    }
}
pub(crate) fn boundary_paragraph(doc: &XmlDocument, marker: NodeId) -> Option<NodeId> {
    let ctrl = doc.parent(marker)?;
    let run = doc.parent(ctrl)?;
    let paragraph = doc.parent(run)?;
    (native(doc, ctrl, "ctrl")
        && native(doc, run, "run")
        && native(doc, paragraph, "p")
        && doc.parent(paragraph) == Some(doc.root))
    .then_some(paragraph)
}
pub(crate) fn top_level_index(doc: &XmlDocument, node: NodeId) -> Option<usize> {
    let mut current = node;
    while let Some(parent) = doc.parent(current) {
        if parent == doc.root {
            return top_level_items(doc)
                .iter()
                .position(|child| *child == Some(current));
        }
        current = parent;
    }
    None
}
pub(crate) fn top_level_items(doc: &XmlDocument) -> Vec<Option<NodeId>> {
    doc.node(doc.root)
        .children
        .iter()
        .filter_map(|part| match part {
            Content::Element(id) => Some(Some(*id)),
            Content::Comment(_) | Content::ProcessingInstruction(_) => Some(None),
            Content::Text(_) | Content::CData(_) => None,
        })
        .collect()
}
fn inside_children(doc: &XmlDocument, node: NodeId, start: usize, stop: usize) -> bool {
    top_level_index(doc, node).is_some_and(|at| start <= at && at <= stop)
}
fn bookmark_boundary_ctrl(doc: &XmlDocument, id: NodeId) -> bool {
    if !native(doc, id, "ctrl") {
        return false;
    }
    let children: Vec<_> = doc
        .node(id)
        .children
        .iter()
        .filter(|part| {
            matches!(
                part,
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
            )
        })
        .collect();
    !children.is_empty()
        && children.iter().all(|part| match part {
            Content::Element(child) => {
                native(doc, *child, "fieldEnd")
                    || (native(doc, *child, "fieldBegin")
                        && doc.attr(*child, "type") == Some("BOOKMARK"))
            }
            _ => false,
        })
}
fn has_payload(doc: &XmlDocument, id: NodeId) -> bool {
    if native(doc, id, "linesegarray") {
        return false;
    }
    if native(doc, id, "t") {
        return !doc.iter_text(id).is_empty()
            || doc.node(id).children.iter().any(|part| {
                matches!(
                    part,
                    Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
                )
            });
    }
    if native(doc, id, "run") {
        return doc.node(id).children.iter().any(|part| match part {
            Content::Text(text) | Content::CData(text) => !text.trim().is_empty(),
            Content::Element(child) => has_payload(doc, *child),
            Content::Comment(_) | Content::ProcessingInstruction(_) => true,
        });
    }
    !bookmark_boundary_ctrl(doc, id)
}
fn payload_outside(doc: &XmlDocument, marker: NodeId, paragraph: NodeId, preceding: bool) -> bool {
    let mut current = marker;
    while current != paragraph {
        let Some(parent) = doc.parent(current) else {
            return true;
        };
        let Some(at) = doc
            .node(parent)
            .children
            .iter()
            .position(|part| matches!(part, Content::Element(id) if *id == current))
        else {
            return true;
        };
        let side = if preceding {
            &doc.node(parent).children[..at]
        } else {
            &doc.node(parent).children[at + 1..]
        };
        if side.iter().any(|part| match part {
            Content::Text(text) | Content::CData(text) => !text.trim().is_empty(),
            Content::Element(id) => has_payload(doc, *id),
            Content::Comment(_) | Content::ProcessingInstruction(_) => true,
        }) {
            return true;
        }
        current = parent;
    }
    false
}

pub(crate) fn plan_bookmark_removal(
    detail: &NativeEntryDetail,
    index: &NativeAdmissionIndex,
    target: &crate::structural_boundary::BookmarkPair,
    policy: BookmarkPlanPolicy,
) -> BookmarkRemovalPlan {
    let doc = &detail.doc;
    let entry = &detail.entry;
    let mut blockers = bookmark_preconditions(detail, &policy);
    if !blockers.is_empty() {
        return BookmarkRemovalPlan {
            blockers,
            protected_markers: Vec::new(),
            removed_begins: Vec::new(),
        };
    }
    let (Some(start_p), Some(stop_p)) = (
        boundary_paragraph(doc, target.begin),
        boundary_paragraph(doc, target.end),
    ) else {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::UnsupportedBoundary,
            format!("{entry}: BOOKMARK boundary is not native ctrl/run/top-level-p content"),
        ));
        return BookmarkRemovalPlan {
            blockers,
            protected_markers: Vec::new(),
            removed_begins: Vec::new(),
        };
    };
    let start = top_level_index(doc, start_p).unwrap();
    let stop = top_level_index(doc, stop_p).unwrap();
    let extent_start = index.top_level_spans[&start_p].0;
    let extent_end = index.top_level_spans[&stop_p].1;
    let (removed_begins, protected_markers, collateral) =
        related_bookmarks(detail, index, target, start, stop);
    if !collateral.is_empty() {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::CollateralBookmark,
            format!(
                "{entry}: removing BOOKMARK would cut BOOKMARK markers outside it: {}",
                collateral.join(", ")
            ),
        ));
    }
    if payload_outside(doc, target.begin, start_p, true) {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::PartialParagraphBegin,
            format!("{entry}: partial-paragraph BOOKMARK begin is unsupported"),
        ));
    }
    if payload_outside(doc, target.end, stop_p, false) {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::PartialParagraphEnd,
            format!("{entry}: partial-paragraph BOOKMARK end is unsupported"),
        ));
    }
    if index.top_level_nonparagraph_prefix[stop + 1] != index.top_level_nonparagraph_prefix[start] {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::NonParagraphExtent,
            format!("{entry}: non-paragraph section child in BOOKMARK extent is unsupported"),
        ));
    }
    blockers.extend(section_blockers(
        entry,
        index,
        start..=stop,
        extent_start..=extent_end,
        &policy,
        protected_markers.is_empty(),
    ));
    if !policy.field_pairing_usable {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::FieldPairingUnusable,
            format!("{entry}: ordinary Field pairing is unusable"),
        ));
    } else {
        blockers.extend(field_intersections(
            detail,
            index,
            start,
            stop,
            extent_start,
            extent_end,
        ));
        blockers.extend(protected_intersections(
            detail,
            index,
            start,
            stop,
            extent_start,
            extent_end,
        ));
    }
    blockers.dedup();
    BookmarkRemovalPlan {
        blockers,
        protected_markers,
        removed_begins,
    }
}

fn related_bookmarks(
    detail: &NativeEntryDetail,
    index: &NativeAdmissionIndex,
    target: &crate::structural_boundary::BookmarkPair,
    start: usize,
    stop: usize,
) -> (Vec<NodeId>, Vec<NodeId>, Vec<String>) {
    let doc = &detail.doc;
    let target_start = index.order[&target.begin];
    let target_end = index.order[&target.end];
    let removed: Vec<_> = detail
        .bookmarks
        .iter()
        .map(|(_, pair)| pair)
        .filter(|pair| {
            target_start <= index.order[&pair.begin] && index.order[&pair.end] <= target_end
        })
        .collect();
    let ancestors: Vec<_> = detail
        .bookmarks
        .iter()
        .map(|(_, pair)| pair)
        .filter(|pair| {
            index.order[&pair.begin] < target_start && target_end < index.order[&pair.end]
        })
        .collect();
    let removed_begins: Vec<_> = removed.iter().map(|pair| pair.begin).collect();
    let protected_markers: Vec<_> = ancestors
        .iter()
        .flat_map(|pair| [pair.begin, pair.end])
        .filter(|id| inside_children(doc, *id, start, stop))
        .collect();
    let collateral: Vec<_> = detail
        .bookmarks
        .iter()
        .map(|(_, pair)| pair)
        .filter(|pair| {
            !removed.iter().any(|item| item.begin == pair.begin)
                && !ancestors.iter().any(|item| item.begin == pair.begin)
        })
        .filter(|pair| {
            inside_children(doc, pair.begin, start, stop)
                || inside_children(doc, pair.end, start, stop)
        })
        .map(|pair| {
            pair.name
                .as_deref()
                .map_or_else(|| "None".into(), python_string_repr)
        })
        .collect();
    (removed_begins, protected_markers, collateral)
}

fn bookmark_preconditions(
    detail: &NativeEntryDetail,
    policy: &BookmarkPlanPolicy,
) -> Vec<BookmarkRemovalBlocker> {
    let entry = &detail.entry;
    let mut blockers = Vec::new();
    if detail.kind != ContentEntryKind::Section {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::UnsupportedEntry,
            format!("{entry}: BOOKMARK removal is supported only in section entries"),
        ));
    }
    if !policy.topology_usable {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::BookmarkTopologyUnusable,
            format!("{entry}: BOOKMARK topology is unusable"),
        ));
    }
    if !policy.metadata_usable {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::BookmarkMetadataUnusable,
            format!("{entry}: BOOKMARK metadata is unusable"),
        ));
    }
    blockers
}

fn field_intersections(
    detail: &NativeEntryDetail,
    index: &NativeAdmissionIndex,
    start: usize,
    stop: usize,
    extent_start: usize,
    extent_end: usize,
) -> Vec<BookmarkRemovalBlocker> {
    let doc = &detail.doc;
    let entry = &detail.entry;
    let mut blockers = Vec::new();
    for (_, field) in &detail.fields {
        let begin_inside = inside_children(doc, field.begin, start, stop);
        let end_inside = inside_children(doc, field.end, start, stop);
        if begin_inside != end_inside {
            blockers.push(bookmark_block(
                BookmarkRemovalBlockerKind::FieldIntersection,
                format!("{entry}: field pair intersects BOOKMARK extent"),
            ));
        } else if !begin_inside
            && index.order[&field.begin] < extent_start
            && index.order[&field.end] > extent_end
        {
            blockers.push(bookmark_block(
                BookmarkRemovalBlockerKind::FieldEnclosesTarget,
                format!("{entry}: field pair encloses BOOKMARK extent"),
            ));
        }
    }
    blockers
}

fn protected_intersections(
    detail: &NativeEntryDetail,
    index: &NativeAdmissionIndex,
    start: usize,
    stop: usize,
    extent_start: usize,
    extent_end: usize,
) -> Vec<BookmarkRemovalBlocker> {
    let doc = &detail.doc;
    let entry = &detail.entry;
    let mut blockers = Vec::new();
    for range in &index.ranges {
        let begin_inside = inside_children(doc, range.begin, start, stop);
        let end_inside = inside_children(doc, range.end, start, stop);
        let encloses =
            index.order[&range.begin] < extent_start && index.order[&range.end] > extent_end;
        if begin_inside != end_inside || encloses {
            blockers.push(bookmark_block(
                BookmarkRemovalBlockerKind::ProtectedRangeCrossing,
                format!(
                    "{entry}: {}/{} range intersects BOOKMARK extent",
                    range.begin_name, range.end_name
                ),
            ));
        }
    }
    let mut unpaired: Vec<_> = index
        .unpaired
        .iter()
        .filter(|id| unpaired_intersects(index, doc, **id, extent_start, extent_end))
        .map(|id| node_name(doc, *id))
        .collect();
    unpaired.sort();
    unpaired.dedup();
    if !unpaired.is_empty() {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::UnpairedProtectedRange,
            format!(
                "{entry}: unpaired protected range in BOOKMARK extent: {}",
                unpaired.join(", ")
            ),
        ));
    }
    blockers
}

fn section_blockers(
    entry: &str,
    index: &NativeAdmissionIndex,
    paragraphs: std::ops::RangeInclusive<usize>,
    orders: std::ops::RangeInclusive<usize>,
    policy: &BookmarkPlanPolicy,
    no_protected_markers: bool,
) -> Vec<BookmarkRemovalBlocker> {
    let (start, stop) = (*paragraphs.start(), *paragraphs.end());
    let (extent_start, extent_end) = (*orders.start(), *orders.end());
    let mut blockers = Vec::new();
    let paragraph_count = index.top_level_nonparagraph_prefix.len()
        - 1
        - index
            .top_level_nonparagraph_prefix
            .last()
            .copied()
            .unwrap_or(0);
    let removed_paragraphs = stop - start + 1
        - (index.top_level_nonparagraph_prefix[stop + 1]
            - index.top_level_nonparagraph_prefix[start]);
    if policy.reject_whole_section && paragraph_count == removed_paragraphs && no_protected_markers
    {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::WholeSection,
            format!("{entry}: removing BOOKMARK would leave no paragraph"),
        ));
    }
    if policy.reject_section_definition
        && index
            .section_definition_orders
            .iter()
            .any(|at| extent_start <= *at && *at <= extent_end)
    {
        blockers.push(bookmark_block(
            BookmarkRemovalBlockerKind::SectionDefinition,
            "BOOKMARK content removal would delete section definition",
        ));
    }
    blockers
}
