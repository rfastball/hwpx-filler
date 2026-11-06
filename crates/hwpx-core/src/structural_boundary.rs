//! Read-only, snapshot-bound native Field and BOOKMARK projection.

use crate::field_occurrence::{
    FieldDiagnosticKind, FieldOccurrence, paragraph_container, resolve_field_occurrences,
};
use crate::package::HwpxPackage;
use crate::text_extract::{numbered_content_suffix, read_field_text};
use crate::text_model::HP_NS;
use crate::xml_dom::{Content, NodeId, XmlDocument, parse_xml};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

/// Python-compatible string representation used in diagnostic details.
pub fn python_string_repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(quote);
    for ch in value.chars() {
        push_repr_character(&mut out, ch, quote);
    }
    out.push(quote);
    out
}

fn control_repr(ch: char) -> String {
    let n = ch as u32;
    if n <= 0xff {
        format!("\\x{n:02x}")
    } else if n <= 0xffff {
        format!("\\u{n:04x}")
    } else {
        format!("\\U{n:08x}")
    }
}

fn push_repr_character(out: &mut String, ch: char, quote: char) {
    match ch {
        '\\' => out.push_str("\\\\"),
        '\n' => out.push_str("\\n"),
        '\r' => out.push_str("\\r"),
        '\t' => out.push_str("\\t"),
        c if c == quote => {
            out.push('\\');
            out.push(c);
        }
        c if c.is_control() || (c.is_whitespace() && c != ' ') => {
            out.push_str(&control_repr(c));
        }
        c => out.push(c),
    }
}

fn optional_name_repr(value: Option<&str>) -> String {
    value.map_or_else(|| "None".into(), python_string_repr)
}

pub const HS_NS: &str = "http://www.hancom.co.kr/hwpml/2011/section";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContentEntryKind {
    Section,
    Header,
    Footer,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StructuralDiagnosticKind {
    MissingSectionEntry,
    UnsupportedContentEntry,
    MalformedXml,
    InvalidEntryRoot,
    InvalidContentEnvelope,
    NonNativeBoundary,
    UnsupportedBookmarkControlShape,
    UnsupportedBookmarkTraversalLane,
    BookmarkBeginMissingId,
    BookmarkDuplicateBeginId,
    BookmarkMissingEnd,
    BookmarkAmbiguousEnd,
    BookmarkEndPrecedesBegin,
    BookmarkCrossing,
    NonNativeMetatag,
    InvalidMetatagShape,
    FieldUnmatchedBegin,
    FieldOrphanEnd,
    FieldAmbiguousEnd,
    FieldNested,
    FieldNonNativeControl,
    FieldUnsupportedControlShape,
    FieldUnsupportedTraversalLane,
    FieldParagraphCrossing,
    FieldUnsupportedContainerCrossing,
}

impl StructuralDiagnosticKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::MissingSectionEntry => "missing-section-entry",
            Self::UnsupportedContentEntry => "unsupported-content-entry",
            Self::MalformedXml => "malformed-xml",
            Self::InvalidEntryRoot => "invalid-entry-root",
            Self::InvalidContentEnvelope => "invalid-content-envelope",
            Self::NonNativeBoundary => "non-native-boundary",
            Self::UnsupportedBookmarkControlShape => "unsupported-bookmark-control-shape",
            Self::UnsupportedBookmarkTraversalLane => "unsupported-bookmark-traversal-lane",
            Self::BookmarkBeginMissingId => "bookmark-begin-missing-id",
            Self::BookmarkDuplicateBeginId => "bookmark-duplicate-begin-id",
            Self::BookmarkMissingEnd => "bookmark-missing-end",
            Self::BookmarkAmbiguousEnd => "bookmark-ambiguous-end",
            Self::BookmarkEndPrecedesBegin => "bookmark-end-precedes-begin",
            Self::BookmarkCrossing => "bookmark-crossing",
            Self::NonNativeMetatag => "non-native-metatag",
            Self::InvalidMetatagShape => "invalid-metatag-shape",
            Self::FieldUnmatchedBegin => "field-unmatched-begin",
            Self::FieldOrphanEnd => "field-orphan-end",
            Self::FieldAmbiguousEnd => "field-ambiguous-end",
            Self::FieldNested => "field-nested",
            Self::FieldNonNativeControl => "field-non-native-control",
            Self::FieldUnsupportedControlShape => "field-unsupported-control-shape",
            Self::FieldUnsupportedTraversalLane => "field-unsupported-traversal-lane",
            Self::FieldParagraphCrossing => "field-paragraph-crossing",
            Self::FieldUnsupportedContainerCrossing => "field-unsupported-container-crossing",
        }
    }
}

impl From<FieldDiagnosticKind> for StructuralDiagnosticKind {
    fn from(kind: FieldDiagnosticKind) -> Self {
        match kind {
            FieldDiagnosticKind::UnmatchedBegin => Self::FieldUnmatchedBegin,
            FieldDiagnosticKind::OrphanEnd => Self::FieldOrphanEnd,
            FieldDiagnosticKind::AmbiguousEnd => Self::FieldAmbiguousEnd,
            FieldDiagnosticKind::NestedField => Self::FieldNested,
            FieldDiagnosticKind::NonNativeFieldControl => Self::FieldNonNativeControl,
            FieldDiagnosticKind::UnsupportedControlShape => Self::FieldUnsupportedControlShape,
            FieldDiagnosticKind::UnsupportedTraversalLane => Self::FieldUnsupportedTraversalLane,
            FieldDiagnosticKind::ParagraphCrossing => Self::FieldParagraphCrossing,
            FieldDiagnosticKind::UnsupportedContainerCrossing => {
                Self::FieldUnsupportedContainerCrossing
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructuralDiagnostic {
    pub entry: Option<String>,
    pub kind: StructuralDiagnosticKind,
    pub order: Option<usize>,
    pub detail: String,
}

#[derive(Clone, Debug)]
pub struct BoundaryPairRef(Arc<()>);
impl BoundaryPairRef {
    fn new() -> Self {
        Self(Arc::new(()))
    }
    pub(crate) fn internal_new() -> Self {
        Self::new()
    }
}
impl PartialEq for BoundaryPairRef {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }
}
impl Eq for BoundaryPairRef {}
impl std::hash::Hash for BoundaryPairRef {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        std::ptr::hash(Arc::as_ptr(&self.0), state);
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BoundaryEvent {
    FieldBegin {
        pair: BoundaryPairRef,
        raw_name: Option<String>,
        field_type: Option<String>,
        text_preview: String,
        order: usize,
    },
    FieldEnd {
        pair: BoundaryPairRef,
        order: usize,
    },
    BookmarkBegin {
        pair: BoundaryPairRef,
        bookmark_name: Option<String>,
        meta_tags: Vec<String>,
        meta_tag_attribute: Option<String>,
        order: usize,
    },
    BookmarkEnd {
        pair: BoundaryPairRef,
        order: usize,
    },
}
impl BoundaryEvent {
    pub fn pair(&self) -> &BoundaryPairRef {
        match self {
            Self::FieldBegin { pair, .. }
            | Self::FieldEnd { pair, .. }
            | Self::BookmarkBegin { pair, .. }
            | Self::BookmarkEnd { pair, .. } => pair,
        }
    }
    pub fn order(&self) -> usize {
        match self {
            Self::FieldBegin { order, .. }
            | Self::FieldEnd { order, .. }
            | Self::BookmarkBegin { order, .. }
            | Self::BookmarkEnd { order, .. } => *order,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructuralEntryScan {
    pub entry: String,
    pub kind: ContentEntryKind,
    pub events: Vec<BoundaryEvent>,
    pub field_pairing_usable: bool,
    pub bookmark_topology_usable: bool,
}

#[derive(Clone, Debug)]
pub struct StructuralBoundaryScan {
    pub entries: Vec<StructuralEntryScan>,
    pub diagnostics: Vec<StructuralDiagnostic>,
    pub(crate) expected_entries: Vec<StructuralEntryScan>,
    pub(crate) expected_diagnostics: Vec<StructuralDiagnostic>,
    pub(crate) native_entries: Vec<NativeEntryDetail>,
    pub(crate) source_manifest: Vec<(String, [u8; 32])>,
    pub(crate) package_entry_names: Vec<String>,
}

#[derive(Clone, Debug)]
pub(crate) struct BookmarkPair {
    pub begin: NodeId,
    pub end: NodeId,
    pub name: Option<String>,
    pub meta_tags: Vec<String>,
    pub meta_tag_attribute: Option<String>,
}

#[derive(Clone, Debug)]
pub(crate) struct NativeEntryDetail {
    pub entry: String,
    pub kind: ContentEntryKind,
    pub source_sha256: [u8; 32],
    pub doc: XmlDocument,
    pub nodes: Vec<NodeId>,
    pub order: HashMap<NodeId, usize>,
    pub fields: Vec<(BoundaryPairRef, FieldOccurrence)>,
    pub bookmarks: Vec<(BoundaryPairRef, BookmarkPair)>,
}

pub(crate) fn digest(source: &[u8]) -> [u8; 32] {
    Sha256::digest(source).into()
}

fn diagnostic(
    entry: Option<&str>,
    kind: StructuralDiagnosticKind,
    order: Option<usize>,
    detail: impl Into<String>,
) -> StructuralDiagnostic {
    StructuralDiagnostic {
        entry: entry.map(str::to_owned),
        kind,
        order,
        detail: detail.into(),
    }
}

fn entry_match(name: &str) -> Option<(ContentEntryKind, usize, String)> {
    for (prefix, kind, rank) in [
        ("section", ContentEntryKind::Section, 0),
        ("header", ContentEntryKind::Header, 1),
        ("footer", ContentEntryKind::Footer, 2),
    ] {
        if let Some(number) = numbered_content_suffix(name, prefix) {
            return Some((kind, rank, number));
        }
    }
    None
}

fn content_like(name: &str) -> bool {
    let base = name.rsplit('/').next().unwrap_or(name).to_ascii_lowercase();
    base.ends_with(".xml")
        && ["section", "header", "footer"]
            .iter()
            .any(|prefix| base.starts_with(prefix))
}

fn looks_boundary_bearing(source: &[u8]) -> bool {
    match parse_xml(source) {
        Ok(doc) => doc
            .descendants(doc.root)
            .into_iter()
            .any(|id| matches!(doc.node(id).name.local.as_str(), "fieldBegin" | "fieldEnd")),
        Err(_) => true,
    }
}

fn content_entries(
    package: &HwpxPackage,
) -> (Vec<(ContentEntryKind, String)>, Vec<StructuralDiagnostic>) {
    let mut supported = Vec::new();
    let mut diagnostics = Vec::new();
    for item in &package.entries {
        if let Some((kind, rank, number)) = entry_match(&item.name) {
            supported.push((rank, number, item.name.clone(), kind));
        } else if content_like(&item.name) && looks_boundary_bearing(&item.data) {
            diagnostics.push(diagnostic(
                Some(&item.name),
                StructuralDiagnosticKind::UnsupportedContentEntry,
                None,
                "",
            ));
        }
    }
    supported.sort_by(|a, b| (a.0, a.1.len(), &a.1, &a.2).cmp(&(b.0, b.1.len(), &b.1, &b.2)));
    diagnostics.sort_by(|a, b| a.entry.cmp(&b.entry));
    if !supported
        .iter()
        .any(|item| item.3 == ContentEntryKind::Section)
    {
        diagnostics.insert(
            0,
            diagnostic(
                None,
                StructuralDiagnosticKind::MissingSectionEntry,
                None,
                "",
            ),
        );
    }
    (
        supported
            .into_iter()
            .map(|(_, _, name, kind)| (kind, name))
            .collect(),
        diagnostics,
    )
}

fn marker_problem(doc: &XmlDocument, marker: NodeId) -> Option<StructuralDiagnosticKind> {
    let Some(ctrl) = doc.parent(marker) else {
        return Some(StructuralDiagnosticKind::UnsupportedBookmarkControlShape);
    };
    let Some(run) = doc.parent(ctrl) else {
        return Some(StructuralDiagnosticKind::UnsupportedBookmarkControlShape);
    };
    let Some(paragraph) = doc.parent(run) else {
        return Some(StructuralDiagnosticKind::UnsupportedBookmarkControlShape);
    };
    for (id, local) in [
        (marker, doc.node(marker).name.local.as_str()),
        (ctrl, "ctrl"),
        (run, "run"),
        (paragraph, "p"),
    ] {
        if doc.node(id).name.local != local {
            return Some(StructuralDiagnosticKind::UnsupportedBookmarkControlShape);
        }
        if !doc.node(id).name.is(HP_NS, local) {
            return Some(StructuralDiagnosticKind::NonNativeBoundary);
        }
    }
    if paragraph_container(doc, paragraph, doc.root).is_none() {
        Some(StructuralDiagnosticKind::UnsupportedBookmarkTraversalLane)
    } else {
        None
    }
}

struct BookmarkMarkers<'a> {
    begins: HashMap<&'a str, Vec<NodeId>>,
    ends: HashMap<&'a str, Vec<NodeId>>,
    bookmarks: Vec<NodeId>,
}

fn bookmark_markers<'a>(doc: &'a XmlDocument, nodes: &[NodeId]) -> BookmarkMarkers<'a> {
    let mut markers = BookmarkMarkers {
        begins: HashMap::new(),
        ends: HashMap::new(),
        bookmarks: Vec::new(),
    };
    for id in nodes.iter().copied() {
        let name = &doc.node(id).name;
        if name.local == "fieldBegin" {
            if name.is(HP_NS, "fieldBegin")
                && let Some(key) = doc.attr(id, "id").filter(|s| !s.is_empty())
            {
                markers.begins.entry(key).or_default().push(id);
            }
            if doc.attr(id, "type") == Some("BOOKMARK") {
                markers.bookmarks.push(id);
            }
        } else if name.local == "fieldEnd"
            && let Some(key) = doc.attr(id, "beginIDRef").filter(|s| !s.is_empty())
        {
            markers.ends.entry(key).or_default().push(id);
        }
    }
    markers
}

struct BookmarkDiagnostics<'a> {
    entry: &'a str,
    order: &'a HashMap<NodeId, usize>,
    items: Vec<StructuralDiagnostic>,
    usable: bool,
}

impl BookmarkDiagnostics<'_> {
    fn report(
        &mut self,
        kind: StructuralDiagnosticKind,
        node: NodeId,
        detail: String,
        topology: bool,
    ) {
        self.items.push(diagnostic(
            Some(self.entry),
            kind,
            Some(self.order[&node]),
            detail,
        ));
        if topology {
            self.usable = false;
        }
    }
}

fn unique_bookmark_end(
    doc: &XmlDocument,
    begin: NodeId,
    pair_id: &str,
    markers: &BookmarkMarkers<'_>,
    reports: &mut BookmarkDiagnostics<'_>,
) -> Option<NodeId> {
    let matches = markers.ends.get(pair_id).map(Vec::as_slice).unwrap_or(&[]);
    let mut native_ends = Vec::new();
    for id in matches.iter().copied() {
        if doc.node(id).name.is(HP_NS, "fieldEnd") {
            native_ends.push(id);
        } else {
            reports.report(
                StructuralDiagnosticKind::NonNativeBoundary,
                id,
                String::new(),
                true,
            );
        }
    }
    let [end] = native_ends.as_slice() else {
        let kind = if native_ends.is_empty() {
            StructuralDiagnosticKind::BookmarkMissingEnd
        } else {
            StructuralDiagnosticKind::BookmarkAmbiguousEnd
        };
        reports.report(
            kind,
            native_ends.first().copied().unwrap_or(begin),
            format!("id={}", python_string_repr(pair_id)),
            true,
        );
        return None;
    };
    Some(*end)
}

fn matching_bookmark_end(
    doc: &XmlDocument,
    begin: NodeId,
    markers: &BookmarkMarkers<'_>,
    reports: &mut BookmarkDiagnostics<'_>,
) -> Option<NodeId> {
    if let Some(kind) = marker_problem(doc, begin) {
        reports.report(kind, begin, String::new(), true);
        return None;
    }
    let Some(pair_id) = doc.attr(begin, "id").filter(|s| !s.is_empty()) else {
        reports.report(
            StructuralDiagnosticKind::BookmarkBeginMissingId,
            begin,
            String::new(),
            true,
        );
        return None;
    };
    if markers.begins.get(pair_id).map(Vec::len) != Some(1) {
        reports.report(
            StructuralDiagnosticKind::BookmarkDuplicateBeginId,
            begin,
            format!("id={}", python_string_repr(pair_id)),
            true,
        );
        return None;
    }
    let end = unique_bookmark_end(doc, begin, pair_id, markers, reports)?;
    if let Some(kind) = marker_problem(doc, end) {
        reports.report(kind, end, String::new(), true);
        return None;
    }
    if reports.order[&end] <= reports.order[&begin] {
        reports.report(
            StructuralDiagnosticKind::BookmarkEndPrecedesBegin,
            end,
            format!("id={}", python_string_repr(pair_id)),
            true,
        );
        return None;
    }
    Some(end)
}

fn bookmark_meta_tags(
    doc: &XmlDocument,
    begin: NodeId,
    reports: &mut BookmarkDiagnostics<'_>,
) -> Vec<String> {
    let mut tags = Vec::new();
    for child in doc.elements(begin) {
        if doc.node(child).name.local != "metaTag" {
            continue;
        }
        if !doc.node(child).name.is(HP_NS, "metaTag") {
            reports.report(
                StructuralDiagnosticKind::NonNativeMetatag,
                child,
                String::new(),
                false,
            );
        } else if doc.node(child).children.iter().any(|part| {
            matches!(
                part,
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
            )
        }) {
            reports.report(
                StructuralDiagnosticKind::InvalidMetatagShape,
                child,
                String::new(),
                false,
            );
        } else {
            tags.push(doc.direct_text(child));
        }
    }
    tags
}

fn check_bookmark_nesting(pairs: &[BookmarkPair], reports: &mut BookmarkDiagnostics<'_>) {
    let mut opened: Vec<&BookmarkPair> = Vec::new();
    for pair in pairs {
        while opened
            .last()
            .is_some_and(|last| reports.order[&last.end] < reports.order[&pair.begin])
        {
            opened.pop();
        }
        if let Some(last) = opened.last()
            && reports.order[&pair.end] > reports.order[&last.end]
        {
            reports.report(
                StructuralDiagnosticKind::BookmarkCrossing,
                pair.begin,
                format!(
                    "{}, {}",
                    optional_name_repr(last.name.as_deref()),
                    optional_name_repr(pair.name.as_deref())
                ),
                true,
            );
        }
        opened.push(pair);
    }
}

fn bookmark_pairs(
    entry: &str,
    doc: &XmlDocument,
    nodes: &[NodeId],
    order: &HashMap<NodeId, usize>,
) -> (Vec<BookmarkPair>, Vec<StructuralDiagnostic>, bool) {
    let markers = bookmark_markers(doc, nodes);
    let mut reports = BookmarkDiagnostics {
        entry,
        order,
        items: Vec::new(),
        usable: true,
    };
    let mut pairs = Vec::new();
    for begin in markers.bookmarks.iter().copied() {
        let Some(end) = matching_bookmark_end(doc, begin, &markers, &mut reports) else {
            continue;
        };
        pairs.push(BookmarkPair {
            begin,
            end,
            name: doc.attr(begin, "name").map(str::to_owned),
            meta_tags: bookmark_meta_tags(doc, begin, &mut reports),
            meta_tag_attribute: doc.attr(begin, "metaTag").map(str::to_owned),
        });
    }
    pairs.sort_by_key(|pair| order[&pair.begin]);
    check_bookmark_nesting(&pairs, &mut reports);
    sort_diagnostics(&mut reports.items);
    (pairs, reports.items, reports.usable)
}

fn sort_diagnostics(items: &mut [StructuralDiagnostic]) {
    items.sort_by(|a, b| {
        a.order
            .cmp(&b.order)
            .then(a.kind.as_str().cmp(b.kind.as_str()))
            .then(a.detail.cmp(&b.detail))
    });
}

fn failed_entry(
    entry: &str,
    kind: ContentEntryKind,
    failure: StructuralDiagnostic,
) -> (
    StructuralEntryScan,
    Vec<StructuralDiagnostic>,
    Option<NativeEntryDetail>,
) {
    (
        StructuralEntryScan {
            entry: entry.to_owned(),
            kind,
            events: Vec::new(),
            field_pairing_usable: false,
            bookmark_topology_usable: false,
        },
        vec![failure],
        None,
    )
}

fn scan_entry(
    entry: &str,
    kind: ContentEntryKind,
    source: &[u8],
) -> (
    StructuralEntryScan,
    Vec<StructuralDiagnostic>,
    Option<NativeEntryDetail>,
) {
    let doc = match parse_xml(source) {
        Ok(doc) => doc,
        Err(error) => {
            return failed_entry(
                entry,
                kind,
                diagnostic(
                    Some(entry),
                    StructuralDiagnosticKind::MalformedXml,
                    None,
                    error.0,
                ),
            );
        }
    };
    if !doc.node(doc.root).name.is(HS_NS, "sec") {
        return failed_entry(
            entry,
            kind,
            diagnostic(
                Some(entry),
                StructuralDiagnosticKind::InvalidEntryRoot,
                None,
                format!(
                    "expected {{{HS_NS}}}sec, got {}",
                    doc.node(doc.root).name.clark()
                ),
            ),
        );
    }
    let children: Vec<_> = doc.elements(doc.root).collect();
    if children.is_empty() || children.iter().any(|id| !doc.node(*id).name.is(HP_NS, "p")) {
        return failed_entry(
            entry,
            kind,
            diagnostic(
                Some(entry),
                StructuralDiagnosticKind::InvalidContentEnvelope,
                None,
                format!("expected one or more direct {{{HP_NS}}}p children"),
            ),
        );
    }
    let nodes = doc.descendants(doc.root);
    let order: HashMap<_, _> = nodes.iter().enumerate().map(|(at, id)| (*id, at)).collect();
    let fields = resolve_field_occurrences(entry, &doc);
    let mut diagnostics: Vec<_> = fields
        .diagnostics
        .iter()
        .map(|item| {
            diagnostic(
                Some(&item.entry),
                item.kind.into(),
                Some(item.order),
                item.detail.clone(),
            )
        })
        .collect();
    let (bookmarks, bookmark_diagnostics, mut bookmark_usable) =
        bookmark_pairs(entry, &doc, &nodes, &order);
    if has_unmatched_end(&doc, &nodes, &fields.occurrences) {
        bookmark_usable = false;
    }
    diagnostics.extend(bookmark_diagnostics);
    let mut events = Vec::new();
    let mut native_fields = Vec::new();
    let mut native_bookmarks = Vec::new();
    for occurrence in fields.occurrences {
        let pair = BoundaryPairRef::new();
        let value = read_field_text(&doc, &occurrence.texts).text;
        let preview = value.split_whitespace().collect::<Vec<_>>().join(" ");
        let preview = if preview.chars().count() > 40 {
            format!("{}…", preview.chars().take(40).collect::<String>())
        } else {
            preview
        };
        events.push(BoundaryEvent::FieldBegin {
            pair: pair.clone(),
            raw_name: occurrence.raw_name.clone(),
            field_type: occurrence.field_type.clone(),
            text_preview: preview,
            order: occurrence.begin_order,
        });
        events.push(BoundaryEvent::FieldEnd {
            pair: pair.clone(),
            order: occurrence.end_order,
        });
        native_fields.push((pair, occurrence));
    }
    for bookmark in bookmarks {
        let pair = BoundaryPairRef::new();
        events.push(BoundaryEvent::BookmarkBegin {
            pair: pair.clone(),
            bookmark_name: bookmark.name.clone(),
            meta_tags: bookmark.meta_tags.clone(),
            meta_tag_attribute: bookmark.meta_tag_attribute.clone(),
            order: order[&bookmark.begin],
        });
        events.push(BoundaryEvent::BookmarkEnd {
            pair: pair.clone(),
            order: order[&bookmark.end],
        });
        native_bookmarks.push((pair, bookmark));
    }
    events.sort_by_key(BoundaryEvent::order);
    sort_diagnostics(&mut diagnostics);
    (
        StructuralEntryScan {
            entry: entry.to_owned(),
            kind,
            events,
            field_pairing_usable: fields.diagnostics.is_empty(),
            bookmark_topology_usable: bookmark_usable,
        },
        diagnostics,
        Some(NativeEntryDetail {
            entry: entry.to_owned(),
            kind,
            source_sha256: digest(source),
            doc,
            nodes,
            order,
            fields: native_fields,
            bookmarks: native_bookmarks,
        }),
    )
}

fn has_unmatched_end(doc: &XmlDocument, nodes: &[NodeId], fields: &[FieldOccurrence]) -> bool {
    let ordinary_ends: HashSet<_> = fields.iter().map(|item| item.end).collect();
    let local_begin_ids: HashSet<_> = nodes
        .iter()
        .filter(|id| doc.node(**id).name.local == "fieldBegin")
        .filter_map(|id| doc.attr(*id, "id"))
        .collect();
    nodes.iter().any(|id| {
        doc.node(*id).name.local == "fieldEnd"
            && !ordinary_ends.contains(id)
            && !doc
                .attr(*id, "beginIDRef")
                .is_some_and(|reference| local_begin_ids.contains(reference))
    })
}

pub fn scan_structural_boundaries(package: &HwpxPackage) -> StructuralBoundaryScan {
    let (selected, mut diagnostics) = content_entries(package);
    let mut entries = Vec::new();
    let mut native_entries = Vec::new();
    for (kind, name) in selected {
        let source = &package
            .entries
            .iter()
            .find(|item| item.name == name)
            .expect("selected package entry")
            .data;
        let (scan, problems, native) = scan_entry(&name, kind, source);
        entries.push(scan);
        diagnostics.extend(problems);
        if let Some(native) = native {
            native_entries.push(native);
        }
    }
    let mut source_manifest: Vec<_> = package
        .entries
        .iter()
        .filter(|item| content_like(&item.name))
        .map(|item| (item.name.clone(), digest(&item.data)))
        .collect();
    source_manifest.sort_by(|a, b| a.0.cmp(&b.0));
    StructuralBoundaryScan {
        expected_entries: entries.clone(),
        expected_diagnostics: diagnostics.clone(),
        entries,
        diagnostics,
        native_entries,
        source_manifest,
        package_entry_names: package
            .entries
            .iter()
            .map(|item| item.name.clone())
            .collect(),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::package::PackageEntry;
    use serde_json::{Value, json};

    fn fixture_sources(case: &Value) -> HwpxPackage {
        HwpxPackage {
            entries: case["sources"]
                .as_array()
                .unwrap()
                .iter()
                .map(|source| {
                    let data = if let Some(xml) = source["xml"].as_str() {
                        xml.as_bytes().to_vec()
                    } else {
                        std::iter::once(0xfeff)
                            .chain(source["utf16"].as_str().unwrap().encode_utf16())
                            .flat_map(u16::to_le_bytes)
                            .collect()
                    };
                    PackageEntry {
                        name: source["name"].as_str().unwrap().into(),
                        data,
                        stored: false,
                    }
                })
                .collect(),
        }
    }

    fn event_projection(
        event: &BoundaryEvent,
        pairs: &mut HashMap<BoundaryPairRef, usize>,
    ) -> Value {
        let next = pairs.len();
        let pair = *pairs.entry(event.pair().clone()).or_insert(next);
        match event {
            BoundaryEvent::FieldBegin {
                raw_name,
                field_type,
                text_preview,
                ..
            } => {
                json!({"kind":"FieldBegin", "pair":pair, "raw_name":raw_name, "field_type":field_type, "text_preview":text_preview})
            }
            BoundaryEvent::FieldEnd { .. } => json!({"kind":"FieldEnd", "pair":pair}),
            BoundaryEvent::BookmarkBegin {
                bookmark_name,
                meta_tags,
                meta_tag_attribute,
                ..
            } => {
                json!({"kind":"BookmarkBegin", "pair":pair, "bookmark_name":bookmark_name, "meta_tags":meta_tags, "meta_tag_attribute":meta_tag_attribute})
            }
            BoundaryEvent::BookmarkEnd { .. } => json!({"kind":"BookmarkEnd", "pair":pair}),
        }
    }

    #[test]
    fn entry_order_pair_identity_and_typed_failures_are_local_to_each_source() {
        let cases: Vec<Value> = serde_json::from_str(include_str!(
            "../../../tests/fixtures/structural_boundary_cases.json"
        ))
        .unwrap();
        for case in cases {
            let package = fixture_sources(&case);
            let before = package.clone();
            let scan = scan_structural_boundaries(&package);
            let mut pairs = HashMap::new();
            let entries: Vec<_> = scan
                .entries
                .iter()
                .map(|entry| {
                    let kind = match entry.kind {
                        ContentEntryKind::Section => "section",
                        ContentEntryKind::Header => "header",
                        ContentEntryKind::Footer => "footer",
                    };
                    let events: Vec<_> = entry
                        .events
                        .iter()
                        .map(|event| event_projection(event, &mut pairs))
                        .collect();
                    json!({"entry":entry.entry, "kind":kind, "events":events,
                    "field_pairing_usable":entry.field_pairing_usable,
                    "bookmark_topology_usable":entry.bookmark_topology_usable})
                })
                .collect();
            let diagnostics: Vec<_> = scan.diagnostics.iter().map(|item|
                json!({"entry":item.entry, "kind":item.kind.as_str(), "order":item.order})).collect();
            assert_eq!(
                json!({"entries":entries, "diagnostics":diagnostics}),
                case["expected"],
                "{}",
                case["id"]
            );
            assert_eq!(package, before);
        }
    }

    #[test]
    fn python_scan_projection_oracle() {
        let fixture: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/hwpx_xml_compat.json"))
                .unwrap();
        for case in fixture["cases"].as_array().unwrap() {
            let entry = case["entry"].as_str().unwrap();
            let package = HwpxPackage {
                entries: vec![PackageEntry {
                    name: entry.to_owned(),
                    data: case["xml"].as_str().unwrap().as_bytes().to_vec(),
                    stored: false,
                }],
            };
            let scan = scan_structural_boundaries(&package);
            let selected = &scan.entries[0];
            let expected = &case["expected"]["scan"];
            assert_eq!(
                selected.field_pairing_usable, expected["field_pairing_usable"],
                "{}",
                case["id"]
            );
            assert_eq!(
                selected.bookmark_topology_usable, expected["bookmark_topology_usable"],
                "{}",
                case["id"]
            );
            let mut pair_ids = HashMap::new();
            let projected: Vec<_> = selected.events.iter().map(|event| {
                let next = pair_ids.len();
                let pair = *pair_ids.entry(event.pair().clone()).or_insert(next);
                let order = event.order();
                let qname = scan.native_entries[0].doc.node(scan.native_entries[0].nodes[order]).name.clark();
                match event {
                    BoundaryEvent::FieldBegin { raw_name, field_type, text_preview, .. } => json!({"kind":"FieldBegin","pair":pair,"order":order,"qname":qname,"raw_name":raw_name,"field_type":field_type,"text_preview":text_preview}),
                    BoundaryEvent::FieldEnd { .. } => json!({"kind":"FieldEnd","pair":pair,"order":order,"qname":qname}),
                    BoundaryEvent::BookmarkBegin { bookmark_name, meta_tags, .. } => json!({"kind":"BookmarkBegin","pair":pair,"order":order,"qname":qname,"name":bookmark_name,"meta_tags":meta_tags}),
                    BoundaryEvent::BookmarkEnd { .. } => json!({"kind":"BookmarkEnd","pair":pair,"order":order,"qname":qname}),
                }
            }).collect();
            assert_eq!(json!(projected), expected["events"], "{}", case["id"]);
            let diagnostics: Vec<_> = scan
                .diagnostics
                .iter()
                .map(|item| json!({"kind":item.kind.as_str(),"order":item.order}))
                .collect();
            assert_eq!(
                json!(diagnostics),
                expected["diagnostics"],
                "{}",
                case["id"]
            );
        }
    }

    #[test]
    fn mixed_child_nodes_preserve_native_boundary_diagnostics() {
        let prefix = format!("<hs:sec xmlns:hs='{HS_NS}' xmlns:hp='{HP_NS}'><hp:p>");
        let suffix = "</hp:p></hs:sec>";
        let cases = [
            (
                "<hp:run><hp:ctrl><hp:fieldBegin id='1'/></hp:ctrl></hp:run><!--lane--><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run>",
                StructuralDiagnosticKind::FieldUnsupportedTraversalLane,
            ),
            (
                "<hp:run><hp:ctrl><hp:fieldBegin id='1' type='BOOKMARK' name='B'><hp:metaTag><!--retain--></hp:metaTag></hp:fieldBegin></hp:ctrl><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run>",
                StructuralDiagnosticKind::InvalidMetatagShape,
            ),
            (
                "<hp:fieldBegin id='1' type='BOOKMARK' name='B'/><hp:fieldEnd beginIDRef='1'/>",
                StructuralDiagnosticKind::UnsupportedBookmarkControlShape,
            ),
        ];
        for (body, kind) in cases {
            let package = HwpxPackage {
                entries: vec![PackageEntry {
                    name: "Contents/section0.xml".to_owned(),
                    data: format!("{prefix}{body}{suffix}").into_bytes(),
                    stored: false,
                }],
            };
            let scan = scan_structural_boundaries(&package);
            assert!(
                scan.diagnostics.iter().any(|item| item.kind == kind),
                "{kind:?}"
            );
        }
        let xml = format!("{prefix}<hp:run/></hp:p></hs:sec>");
        let package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "Contents/section18446744073709551617.xml".to_owned(),
                    data: xml.as_bytes().to_vec(),
                    stored: false,
                },
                PackageEntry {
                    name: "Contents/section18446744073709551616.xml".to_owned(),
                    data: xml.into_bytes(),
                    stored: false,
                },
            ],
        };
        let scan = scan_structural_boundaries(&package);
        assert_eq!(
            scan.entries[0].entry,
            "Contents/section18446744073709551616.xml"
        );
        let xml = format!("<hs:sec xmlns:hs='{HS_NS}'/>");
        let package = HwpxPackage {
            entries: ["section１２.xml", "section9.xml", "section٠٣.XML"]
                .into_iter()
                .map(|name| PackageEntry {
                    name: format!("Contents/{name}"),
                    data: xml.as_bytes().to_vec(),
                    stored: false,
                })
                .collect(),
        };
        let expected = [
            "Contents/section٠٣.XML",
            "Contents/section9.xml",
            "Contents/section１２.xml",
        ];
        let scan = scan_structural_boundaries(&package);
        assert_eq!(
            scan.entries
                .iter()
                .map(|entry| entry.entry.as_str())
                .collect::<Vec<_>>(),
            expected
        );
        assert_eq!(crate::text_extract::section_xml_names(&package), expected);
    }
}
