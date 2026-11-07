//! Native ordinary field pairs within supported paragraph lanes.

use crate::text_model::HP_NS;
use crate::xml_dom::{Content, NodeId, XmlDocument};
use std::collections::{HashMap, HashSet};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum FieldDiagnosticKind {
    UnmatchedBegin,
    OrphanEnd,
    AmbiguousEnd,
    NestedField,
    NonNativeFieldControl,
    UnsupportedControlShape,
    UnsupportedTraversalLane,
    ParagraphCrossing,
    UnsupportedContainerCrossing,
}

impl FieldDiagnosticKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::UnmatchedBegin => "unmatched-begin",
            Self::OrphanEnd => "orphan-end",
            Self::AmbiguousEnd => "ambiguous-end",
            Self::NestedField => "nested-field",
            Self::NonNativeFieldControl => "non-native-field-control",
            Self::UnsupportedControlShape => "unsupported-control-shape",
            Self::UnsupportedTraversalLane => "unsupported-traversal-lane",
            Self::ParagraphCrossing => "paragraph-crossing",
            Self::UnsupportedContainerCrossing => "unsupported-container-crossing",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldDiagnostic {
    pub entry: String,
    pub kind: FieldDiagnosticKind,
    pub order: usize,
    pub detail: String,
}

impl std::fmt::Display for FieldDiagnostic {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "{}: {} at element {}",
            self.entry,
            self.kind.as_str(),
            self.order
        )?;
        if !self.detail.is_empty() {
            write!(formatter, " ({})", self.detail)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub(crate) struct FieldOccurrence {
    pub raw_name: Option<String>,
    pub field_type: Option<String>,
    pub begin_order: usize,
    pub end_order: usize,
    pub begin: NodeId,
    pub end: NodeId,
    pub paragraph: NodeId,
    pub begin_ctrl: NodeId,
    pub end_ctrl: NodeId,
    pub begin_run: NodeId,
    pub end_run: NodeId,
    pub texts: Vec<NodeId>,
}

#[derive(Clone, Debug)]
pub(crate) struct FieldResolution {
    pub occurrences: Vec<FieldOccurrence>,
    pub diagnostics: Vec<FieldDiagnostic>,
}

#[derive(Clone, Copy)]
struct Position {
    ctrl: NodeId,
    run: NodeId,
    paragraph: NodeId,
    container: NodeId,
}

fn native(doc: &XmlDocument, id: NodeId, local: &str) -> bool {
    doc.node(id).name.is(HP_NS, local)
}

pub(crate) fn paragraph_container(
    doc: &XmlDocument,
    paragraph: NodeId,
    root: NodeId,
) -> Option<NodeId> {
    let parent = doc.parent(paragraph)?;
    if parent == root {
        return Some(root);
    }
    if !native(doc, parent, "subList") {
        return None;
    }
    let owner = doc.parent(parent)?;
    let table = if native(doc, owner, "tc") {
        let row = doc.parent(owner)?;
        if !native(doc, row, "tr") {
            return None;
        }
        doc.parent(row)?
    } else if native(doc, owner, "caption") {
        doc.parent(owner)?
    } else {
        return None;
    };
    if !native(doc, table, "tbl") {
        return None;
    }
    let run = doc.parent(table)?;
    let outer = doc.parent(run)?;
    if native(doc, run, "run")
        && native(doc, outer, "p")
        && paragraph_container(doc, outer, root).is_some()
    {
        Some(parent)
    } else {
        None
    }
}

fn position(
    doc: &XmlDocument,
    marker: NodeId,
    root: NodeId,
) -> Result<Position, FieldDiagnosticKind> {
    let ctrl = doc
        .parent(marker)
        .ok_or(FieldDiagnosticKind::UnsupportedControlShape)?;
    let run = doc
        .parent(ctrl)
        .ok_or(FieldDiagnosticKind::UnsupportedControlShape)?;
    let paragraph = doc
        .parent(run)
        .ok_or(FieldDiagnosticKind::UnsupportedControlShape)?;
    if !native(doc, ctrl, "ctrl") || !native(doc, run, "run") || !native(doc, paragraph, "p") {
        return Err(FieldDiagnosticKind::UnsupportedControlShape);
    }
    let container = paragraph_container(doc, paragraph, root)
        .ok_or(FieldDiagnosticKind::UnsupportedTraversalLane)?;
    Ok(Position {
        ctrl,
        run,
        paragraph,
        container,
    })
}

#[derive(Default)]
struct Diagnostics {
    items: Vec<FieldDiagnostic>,
    seen: HashSet<(FieldDiagnosticKind, usize, String)>,
}
fn report(
    diagnostics: &mut Diagnostics,
    entry: &str,
    kind: FieldDiagnosticKind,
    order: usize,
    detail: String,
) {
    if diagnostics.seen.insert((kind, order, detail.clone())) {
        diagnostics.items.push(FieldDiagnostic {
            entry: entry.to_owned(),
            kind,
            order,
            detail,
        });
    }
}

struct Markers<'a> {
    begins: Vec<NodeId>,
    ends: Vec<NodeId>,
    positions: HashMap<NodeId, Position>,
    bookmark_ids: HashSet<&'a str>,
}

fn marker_positions(
    entry: &str,
    doc: &XmlDocument,
    markers: impl Iterator<Item = NodeId>,
    order: &HashMap<NodeId, usize>,
    positions: &mut HashMap<NodeId, Position>,
    diagnostics: &mut Diagnostics,
) -> Vec<NodeId> {
    let mut valid = Vec::new();
    for marker in markers {
        let located = if doc.node(marker).name.namespace != HP_NS {
            Err(FieldDiagnosticKind::NonNativeFieldControl)
        } else {
            position(doc, marker, doc.root)
        };
        match located {
            Ok(pos) => {
                positions.insert(marker, pos);
                valid.push(marker);
            }
            Err(kind) => report(diagnostics, entry, kind, order[&marker], String::new()),
        }
    }
    valid
}

fn index_markers<'a>(
    entry: &str,
    doc: &'a XmlDocument,
    nodes: &[NodeId],
    order: &HashMap<NodeId, usize>,
    diagnostics: &mut Diagnostics,
) -> Markers<'a> {
    let begins: Vec<_> = nodes
        .iter()
        .copied()
        .filter(|id| {
            doc.node(*id).name.local == "fieldBegin" && doc.attr(*id, "type") != Some("BOOKMARK")
        })
        .collect();
    let ordinary_ids: HashSet<_> = begins
        .iter()
        .filter_map(|id| doc.attr(*id, "id"))
        .filter(|id| !id.is_empty())
        .collect();
    let bookmark_ids: HashSet<_> = nodes
        .iter()
        .filter(|id| {
            doc.node(**id).name.local == "fieldBegin" && doc.attr(**id, "type") == Some("BOOKMARK")
        })
        .filter_map(|id| doc.attr(*id, "id"))
        .filter(|id| !id.is_empty())
        .collect();
    let mut positions = HashMap::new();
    let valid_begins = marker_positions(
        entry,
        doc,
        begins.iter().copied(),
        order,
        &mut positions,
        diagnostics,
    );
    let ends = nodes
        .iter()
        .copied()
        .filter(|id| doc.node(*id).name.local == "fieldEnd")
        .filter(|end| {
            !doc.attr(*end, "beginIDRef")
                .is_some_and(|id| bookmark_ids.contains(id) && !ordinary_ids.contains(id))
        });
    let valid_ends = marker_positions(entry, doc, ends, order, &mut positions, diagnostics);
    Markers {
        begins: valid_begins,
        ends: valid_ends,
        positions,
        bookmark_ids,
    }
}

fn markers_by_attribute<'a>(
    doc: &'a XmlDocument,
    markers: &[NodeId],
    attribute: &str,
) -> HashMap<&'a str, Vec<NodeId>> {
    let mut grouped = HashMap::<_, Vec<_>>::new();
    for id in markers {
        if let Some(key) = doc.attr(*id, attribute).filter(|s| !s.is_empty()) {
            grouped.entry(key).or_default().push(*id);
        }
    }
    grouped
}

fn crossing_kind(begin: Position, end: Position) -> Option<FieldDiagnosticKind> {
    if begin.paragraph == end.paragraph {
        None
    } else if begin.container == end.container {
        Some(FieldDiagnosticKind::ParagraphCrossing)
    } else {
        Some(FieldDiagnosticKind::UnsupportedContainerCrossing)
    }
}

fn blocked_references(
    entry: &str,
    doc: &XmlDocument,
    markers: &Markers<'_>,
    order: &HashMap<NodeId, usize>,
    diagnostics: &mut Diagnostics,
) -> HashSet<NodeId> {
    let begins_by_id = markers_by_attribute(doc, &markers.begins, "id");
    let ends_by_ref = markers_by_attribute(doc, &markers.ends, "beginIDRef");
    let mut blocked = HashSet::new();
    for (reference, ends) in ends_by_ref {
        let matching = begins_by_id
            .get(reference)
            .map(Vec::as_slice)
            .unwrap_or(&[]);
        if markers.bookmark_ids.contains(reference) || matching.len() > 1 || ends.len() > 1 {
            report(
                diagnostics,
                entry,
                FieldDiagnosticKind::AmbiguousEnd,
                order[&ends[0]],
                format!("beginIDRef={reference:?}"),
            );
            blocked.extend(matching.iter().copied());
            blocked.extend(ends);
        } else if let [begin] = matching {
            let end = ends[0];
            if let Some(kind) = crossing_kind(markers.positions[begin], markers.positions[&end]) {
                report(
                    diagnostics,
                    entry,
                    kind,
                    order[&end],
                    format!("beginIDRef={reference:?}"),
                );
                blocked.insert(*begin);
                blocked.insert(end);
            }
        }
    }
    blocked
}

fn paragraph_lanes(
    markers: &Markers<'_>,
    blocked: &HashSet<NodeId>,
    order: &HashMap<NodeId, usize>,
) -> Vec<Vec<(bool, NodeId)>> {
    let mut lanes = HashMap::<_, Vec<_>>::new();
    for (is_begin, id) in markers
        .begins
        .iter()
        .map(|id| (true, *id))
        .chain(markers.ends.iter().map(|id| (false, *id)))
    {
        if !blocked.contains(&id) {
            lanes
                .entry(markers.positions[&id].paragraph)
                .or_default()
                .push((is_begin, id));
        }
    }
    let mut lanes: Vec<_> = lanes.into_values().collect();
    for lane in &mut lanes {
        lane.sort_by_key(|(_, id)| order[id]);
    }
    lanes.sort_by_key(|lane| order[&lane[0].1]);
    lanes
}

fn supported_run_lane(doc: &XmlDocument, begin: Position, end: Position) -> bool {
    let children = &doc.node(begin.paragraph).children;
    let start = children
        .iter()
        .position(|part| matches!(part, Content::Element(child) if *child == begin.run))
        .unwrap_or(0);
    let stop = children
        .iter()
        .position(|part| matches!(part, Content::Element(child) if *child == end.run))
        .unwrap_or(start);
    !children[start..=stop].iter().any(|part| match part {
        Content::Element(child) => !native(doc, *child, "run"),
        Content::Comment(_) | Content::ProcessingInstruction(_) => true,
        Content::Text(_) | Content::CData(_) => false,
    })
}

fn close_occurrence(
    doc: &XmlDocument,
    begin: NodeId,
    end: NodeId,
    order: &HashMap<NodeId, usize>,
    positions: &HashMap<NodeId, Position>,
) -> Result<FieldOccurrence, (FieldDiagnosticKind, String)> {
    let begin_id = doc.attr(begin, "id");
    let end_ref = doc.attr(end, "beginIDRef");
    if begin_id.is_none() != end_ref.is_none() || end_ref.is_some_and(|s| Some(s) != begin_id) {
        return Err((
            FieldDiagnosticKind::OrphanEnd,
            format!("beginIDRef={end_ref:?}"),
        ));
    }
    let first = positions[&begin];
    let last = positions[&end];
    if !supported_run_lane(doc, first, last) {
        return Err((FieldDiagnosticKind::UnsupportedTraversalLane, String::new()));
    }
    let texts = doc
        .elements(first.paragraph)
        .filter(|run| native(doc, *run, "run"))
        .flat_map(|run| doc.elements(run))
        .filter(|child| {
            native(doc, *child, "t") && order[child] > order[&begin] && order[child] < order[&end]
        })
        .collect();
    Ok(FieldOccurrence {
        raw_name: doc.attr(begin, "name").map(str::to_owned),
        field_type: doc.attr(begin, "type").map(str::to_owned),
        begin_order: order[&begin],
        end_order: order[&end],
        begin,
        end,
        paragraph: first.paragraph,
        begin_ctrl: first.ctrl,
        end_ctrl: last.ctrl,
        begin_run: first.run,
        end_run: last.run,
        texts,
    })
}

fn resolve_lane(
    entry: &str,
    doc: &XmlDocument,
    markers: Vec<(bool, NodeId)>,
    order: &HashMap<NodeId, usize>,
    positions: &HashMap<NodeId, Position>,
    diagnostics: &mut Diagnostics,
    occurrences: &mut Vec<FieldOccurrence>,
) {
    let mut opened = None;
    let mut poisoned = false;
    for (is_begin, id) in markers {
        if poisoned {
            break;
        }
        if is_begin {
            if opened.is_some() {
                report(
                    diagnostics,
                    entry,
                    FieldDiagnosticKind::NestedField,
                    order[&id],
                    String::new(),
                );
                poisoned = true;
                opened = None;
            } else {
                opened = Some(id);
            }
            continue;
        }
        let Some(begin) = opened else {
            report(
                diagnostics,
                entry,
                FieldDiagnosticKind::OrphanEnd,
                order[&id],
                String::new(),
            );
            poisoned = true;
            continue;
        };
        match close_occurrence(doc, begin, id, order, positions) {
            Ok(occurrence) => occurrences.push(occurrence),
            Err((kind, detail)) => {
                report(diagnostics, entry, kind, order[&id], detail);
                poisoned = true;
            }
        }
        opened = None;
    }
    if let Some(begin) = opened
        && !poisoned
    {
        report(
            diagnostics,
            entry,
            FieldDiagnosticKind::UnmatchedBegin,
            order[&begin],
            String::new(),
        );
    }
}

pub(crate) fn resolve_field_occurrences(entry: &str, doc: &XmlDocument) -> FieldResolution {
    let nodes = doc.descendants(doc.root);
    let order: HashMap<NodeId, usize> =
        nodes.iter().enumerate().map(|(at, id)| (*id, at)).collect();
    let mut diagnostics = Diagnostics::default();
    let markers = index_markers(entry, doc, &nodes, &order, &mut diagnostics);
    let blocked = blocked_references(entry, doc, &markers, &order, &mut diagnostics);
    let mut occurrences = Vec::new();
    for lane in paragraph_lanes(&markers, &blocked, &order) {
        resolve_lane(
            entry,
            doc,
            lane,
            &order,
            &markers.positions,
            &mut diagnostics,
            &mut occurrences,
        );
    }
    occurrences.sort_by_key(|item| item.begin_order);
    for pair in occurrences.windows(2) {
        if pair[1].begin_order < pair[0].end_order {
            report(
                &mut diagnostics,
                entry,
                FieldDiagnosticKind::NestedField,
                pair[1].begin_order,
                String::new(),
            );
        }
    }
    diagnostics.items.sort_by(|a, b| {
        a.order
            .cmp(&b.order)
            .then(a.kind.as_str().cmp(b.kind.as_str()))
            .then(a.detail.cmp(&b.detail))
    });
    if !diagnostics.items.is_empty() {
        occurrences.clear();
    }
    FieldResolution {
        occurrences,
        diagnostics: diagnostics.items,
    }
}
