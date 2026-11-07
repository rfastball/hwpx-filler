//! Pair-local native admission and transactional field mutation.

use crate::field_occurrence::{FieldDiagnostic, FieldOccurrence, resolve_field_occurrences};
use crate::lineseg::serialize_modified_section;
use crate::package::HwpxPackage;
use crate::structural_boundary::{
    BoundaryPairRef, ContentEntryKind, NativeEntryDetail, StructuralBoundaryScan,
    StructuralDiagnosticKind, digest, python_string_repr,
};
use crate::text_extract::{InlineText, read_field_text};
use crate::text_model::HP_NS;
use crate::xml_dom::{Attribute, Content, Name, NodeId, XmlDocument, XmlError, parse_xml};
use std::collections::{HashMap, HashSet};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeAdmissionError(pub String);
impl std::fmt::Display for NativeAdmissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for NativeAdmissionError {}
impl From<XmlError> for NativeAdmissionError {
    fn from(value: XmlError) -> Self {
        Self(value.0)
    }
}
fn error(message: impl Into<String>) -> NativeAdmissionError {
    NativeAdmissionError(message.into())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FieldFillEffectKind {
    SynthesizeSlot,
    RemoveInline,
    NormalizeFragments,
}
impl FieldFillEffectKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::SynthesizeSlot => "synthesize-slot",
            Self::RemoveInline => "remove-inline",
            Self::NormalizeFragments => "normalize-fragments",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FieldFillBlockerKind {
    FieldPairingUnusable,
    NoValuePosition,
    ProtectedRangeCrossing,
    UnpairedProtectedRange,
    UnsupportedInlineObject,
}
impl FieldFillBlockerKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::FieldPairingUnusable => "field-pairing-unusable",
            Self::NoValuePosition => "no-value-position",
            Self::ProtectedRangeCrossing => "protected-range-crossing",
            Self::UnpairedProtectedRange => "unpaired-protected-range",
            Self::UnsupportedInlineObject => "unsupported-inline-object",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldFillEffect {
    pub kind: FieldFillEffectKind,
    pub detail: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldFillBlocker {
    pub kind: FieldFillBlockerKind,
    pub detail: Vec<String>,
}
#[derive(Clone, Debug)]
pub struct FieldFillObservation {
    pub pair: BoundaryPairRef,
    pub supported_effects: Vec<FieldFillEffect>,
    pub blockers: Vec<FieldFillBlocker>,
}
impl FieldFillObservation {
    pub fn fillable(&self) -> bool {
        self.blockers.is_empty()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BookmarkRemovalBlockerKind {
    UnsupportedEntry,
    BookmarkTopologyUnusable,
    BookmarkMetadataUnusable,
    UnsupportedBoundary,
    PartialParagraphBegin,
    PartialParagraphEnd,
    NonParagraphExtent,
    CollateralBookmark,
    WholeSection,
    SectionDefinition,
    FieldPairingUnusable,
    FieldIntersection,
    FieldEnclosesTarget,
    ProtectedRangeCrossing,
    UnpairedProtectedRange,
}
impl BookmarkRemovalBlockerKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::UnsupportedEntry => "unsupported-entry",
            Self::BookmarkTopologyUnusable => "bookmark-topology-unusable",
            Self::BookmarkMetadataUnusable => "bookmark-metadata-unusable",
            Self::UnsupportedBoundary => "unsupported-boundary",
            Self::PartialParagraphBegin => "partial-paragraph-begin",
            Self::PartialParagraphEnd => "partial-paragraph-end",
            Self::NonParagraphExtent => "non-paragraph-extent",
            Self::CollateralBookmark => "collateral-bookmark",
            Self::WholeSection => "whole-section",
            Self::SectionDefinition => "section-definition",
            Self::FieldPairingUnusable => "field-pairing-unusable",
            Self::FieldIntersection => "field-intersection",
            Self::FieldEnclosesTarget => "field-encloses-target",
            Self::ProtectedRangeCrossing => "protected-range-crossing",
            Self::UnpairedProtectedRange => "unpaired-protected-range",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BookmarkRemovalBlocker {
    pub kind: BookmarkRemovalBlockerKind,
    pub detail: Vec<String>,
}
#[derive(Clone, Debug)]
pub struct BookmarkRemovalObservation {
    pub pair: BoundaryPairRef,
    pub blockers: Vec<BookmarkRemovalBlocker>,
}
impl BookmarkRemovalObservation {
    pub fn removable(&self) -> bool {
        self.blockers.is_empty()
    }
}
#[derive(Clone, Debug)]
pub struct NativeCapabilityInspection {
    pub field_fills: Vec<FieldFillObservation>,
    pub bookmark_removals: Vec<BookmarkRemovalObservation>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldFillMutation {
    pub filled: bool,
    pub modified: bool,
    pub structure_changed: bool,
    pub effects: Vec<FieldFillEffect>,
    pub blockers: Vec<FieldFillBlocker>,
}

mod field;
use field::effect;
pub(crate) use field::plan_field_fill;
mod index;
pub(crate) use index::{NativeAdmissionIndex, build_native_admission_index};
mod bookmark;
pub(crate) use bookmark::{
    BookmarkPlanPolicy, BookmarkRemovalPlan, boundary_paragraph, plan_bookmark_removal,
    top_level_index, top_level_items,
};

fn native(doc: &XmlDocument, id: NodeId, local: &str) -> bool {
    doc.node(id).name.is(HP_NS, local)
}
fn node_name(doc: &XmlDocument, id: NodeId) -> String {
    doc.node(id).name.local.clone()
}
fn unpaired_intersects(
    index: &NativeAdmissionIndex,
    doc: &XmlDocument,
    id: NodeId,
    start: usize,
    end: usize,
) -> bool {
    let order = index.order[&id];
    let local = &doc.node(id).name.local;
    (start <= order && order <= end)
        || (local.ends_with("Begin") && order < start)
        || (local.ends_with("End") && order > end)
}

fn verify_sources(
    package: &HwpxPackage,
    scan: &StructuralBoundaryScan,
) -> Result<(), NativeAdmissionError> {
    let names: Vec<_> = package
        .entries
        .iter()
        .map(|item| item.name.clone())
        .collect();
    if names != scan.package_entry_names {
        return Err(error("stale structural scan entry roster"));
    }
    for (name, hash) in &scan.source_manifest {
        let source = package
            .entries
            .iter()
            .find(|item| &item.name == name)
            .ok_or_else(|| error("stale structural scan entry"))?;
        if digest(&source.data) != *hash {
            return Err(error(format!("stale structural scan for {name}")));
        }
    }
    Ok(())
}

pub(crate) fn verify_scan<'a>(
    package: &HwpxPackage,
    scan: &'a StructuralBoundaryScan,
) -> Result<&'a [NativeEntryDetail], NativeAdmissionError> {
    if scan.entries != scan.expected_entries || scan.diagnostics != scan.expected_diagnostics {
        return Err(error("structural scan evidence mismatch"));
    }
    verify_sources(package, scan)?;
    let fatal: HashSet<_> = scan
        .diagnostics
        .iter()
        .filter(|d| {
            matches!(
                d.kind,
                StructuralDiagnosticKind::MalformedXml
                    | StructuralDiagnosticKind::InvalidEntryRoot
                    | StructuralDiagnosticKind::InvalidContentEnvelope
            )
        })
        .filter_map(|d| d.entry.as_deref())
        .collect();
    if scan.native_entries.len() + fatal.len() != scan.entries.len() {
        return Err(error("public/private scan entry mismatch"));
    }
    let mut seen = HashSet::new();
    for (public, detail) in scan
        .entries
        .iter()
        .filter(|entry| !fatal.contains(entry.entry.as_str()))
        .zip(&scan.native_entries)
    {
        if public.entry != detail.entry || public.kind != detail.kind {
            return Err(error("public/private scan entry mismatch"));
        }
        if !seen.insert(public.entry.as_str()) {
            return Err(error("duplicate public scan entry"));
        }
        let source = package
            .entries
            .iter()
            .find(|item| item.name == detail.entry)
            .ok_or_else(|| error("stale native entry"))?;
        if digest(&source.data) != detail.source_sha256 {
            return Err(error("stale native entry"));
        }
        verify_pair_registry(public, detail)?;
    }
    Ok(&scan.native_entries)
}

fn verify_pair_registry(
    public: &crate::structural_boundary::StructuralEntryScan,
    detail: &NativeEntryDetail,
) -> Result<(), NativeAdmissionError> {
    let public_pairs: HashSet<_> = public
        .events
        .iter()
        .map(|event| event.pair().clone())
        .collect();
    let native_pairs: HashSet<_> = detail
        .fields
        .iter()
        .map(|(pair, _)| pair.clone())
        .chain(detail.bookmarks.iter().map(|(pair, _)| pair.clone()))
        .collect();
    if public_pairs != native_pairs || public.events.len() != native_pairs.len() * 2 {
        return Err(error("native boundary pair registry mismatch"));
    }
    Ok(())
}

/// Read the complete value of one ordinary Field in the supplied package snapshot.
pub fn read_field_value(
    package: &HwpxPackage,
    scan: &StructuralBoundaryScan,
    pair: &BoundaryPairRef,
) -> Result<InlineText, NativeAdmissionError> {
    let details = verify_scan(package, scan)?;
    for detail in details {
        if let Some((_, occurrence)) = detail.fields.iter().find(|(found, _)| found == pair) {
            return Ok(read_field_text(&detail.doc, &occurrence.texts));
        }
    }
    Err(error("field pair is not part of this scan"))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EntryFieldObservation {
    pub raw_name: Option<String>,
    pub field_type: Option<String>,
    pub value: InlineText,
    /// Parse-local node ID; it can be dereferenced only in the view that produced it.
    pub paragraph: NodeId,
    pub begin: NodeId,
    pub end: NodeId,
    pub begin_ctrl: NodeId,
    pub end_ctrl: NodeId,
    pub begin_order: usize,
    pub end_order: usize,
    pub texts: Vec<NodeId>,
}

#[derive(Clone, Debug)]
pub struct EntryFieldScan {
    pub fields: Vec<EntryFieldObservation>,
    pub diagnostics: Vec<FieldDiagnostic>,
}

impl EntryFieldScan {
    pub fn pairing_usable(&self) -> bool {
        self.diagnostics.is_empty()
    }
}

/// Inspect ordinary Fields in any named XML entry, including unnumbered content parts.
pub fn scan_entry_field_begins(
    package: &HwpxPackage,
    entry: &str,
) -> Result<EntryFieldScan, NativeAdmissionError> {
    let source = package
        .entries
        .iter()
        .find(|item| item.name == entry)
        .ok_or_else(|| error(format!("missing package entry: {entry}")))?;
    let doc = parse_xml(&source.data)?;
    Ok(observe_field_doc(entry, &doc))
}

pub(crate) fn observe_field_doc(entry: &str, doc: &XmlDocument) -> EntryFieldScan {
    let resolved = resolve_field_occurrences(entry, doc);
    EntryFieldScan {
        fields: resolved
            .occurrences
            .into_iter()
            .map(|occurrence| EntryFieldObservation {
                raw_name: occurrence.raw_name,
                field_type: occurrence.field_type,
                value: read_field_text(doc, &occurrence.texts),
                paragraph: occurrence.paragraph,
                begin: occurrence.begin,
                end: occurrence.end,
                begin_ctrl: occurrence.begin_ctrl,
                end_ctrl: occurrence.end_ctrl,
                begin_order: occurrence.begin_order,
                end_order: occurrence.end_order,
                texts: occurrence.texts,
            })
            .collect(),
        diagnostics: resolved.diagnostics,
    }
}

pub(crate) fn native_element(doc: &mut XmlDocument, local: &str, attrs: &[(&str, &str)]) -> NodeId {
    let name = Name {
        raw: format!("hp:{local}"),
        namespace: HP_NS.to_owned(),
        local: local.to_owned(),
    };
    let attributes = attrs
        .iter()
        .map(|(key, value)| Attribute {
            name: Name {
                raw: (*key).to_owned(),
                namespace: String::new(),
                local: (*key).to_owned(),
            },
            value: (*value).to_owned(),
        })
        .collect();
    let id = doc.new_element(name, attributes);
    // Each new element binds its own native prefix, even under alternate or rebound source prefixes.
    doc.node_mut(id)
        .namespaces
        .push(("hp".to_owned(), HP_NS.to_owned()));
    id
}

pub(crate) fn copy_run_attributes(doc: &mut XmlDocument, source: NodeId, target: NodeId) {
    const XML_NS: &str = "http://www.w3.org/XML/1998/namespace";
    let mut attributes = doc.node(source).attributes.clone();
    for (at, attribute) in attributes.iter_mut().enumerate() {
        if attribute.name.namespace.is_empty() {
            attribute.name.raw = attribute.name.local.clone();
        } else if attribute.name.namespace == XML_NS {
            attribute.name.raw = format!("xml:{}", attribute.name.local);
        } else {
            let prefix = format!("hfattr{at}");
            attribute.name.raw = format!("{prefix}:{}", attribute.name.local);
            doc.node_mut(target)
                .namespaces
                .push((prefix, attribute.name.namespace.clone()));
        }
    }
    doc.node_mut(target).attributes = attributes;
}

/// Normalize a candidate Field value before a multi-occurrence transaction begins.
pub fn canonical_field_value(value: &str) -> Result<String, NativeAdmissionError> {
    let value = value.replace("\r\n", "\n").replace('\r', "\n");
    let mut bad: Vec<_> = value
        .chars()
        .filter(|ch| {
            *ch != '\t'
                && *ch != '\n'
                && (ch.is_control() || matches!(*ch, '\u{fffe}' | '\u{ffff}'))
        })
        .map(|ch| format!("U+{:04X}", ch as u32))
        .collect();
    bad.sort();
    bad.dedup();
    if !bad.is_empty() {
        return Err(error(format!(
            "필드 값에 문서 본문에 쓸 수 없는 제어 문자가 있습니다: {}",
            bad.join(", ")
        )));
    }
    Ok(value)
}

fn write_field_text(
    doc: &mut XmlDocument,
    text: NodeId,
    value: &str,
) -> Result<(), NativeAdmissionError> {
    let mut contents = Vec::new();
    let mut pending = String::new();
    for ch in value.chars() {
        let local = match ch {
            '\t' => Some("tab"),
            '\n' => Some("lineBreak"),
            ' ' => Some("fwSpace"),
            _ => None,
        };
        if let Some(local) = local {
            if !pending.is_empty() {
                contents.push(Content::Text(std::mem::take(&mut pending)));
            }
            let attrs: &[(&str, &str)] = if local == "tab" {
                &[("width", "0"), ("leader", "0"), ("type", "1")]
            } else {
                &[]
            };
            let id = native_element(doc, local, attrs);
            doc.node_mut(id).parent = Some(text);
            contents.push(Content::Element(id));
        } else {
            pending.push(ch);
        }
    }
    if !pending.is_empty() || contents.is_empty() {
        contents.push(Content::Text(pending));
    }
    doc.node_mut(text).children = contents;
    Ok(())
}

pub(crate) fn content_index(
    doc: &XmlDocument,
    parent: NodeId,
    child: NodeId,
) -> Result<usize, NativeAdmissionError> {
    doc.node(parent)
        .children
        .iter()
        .position(|part| matches!(part, Content::Element(id) if *id == child))
        .ok_or_else(|| error("detached XML node"))
}

pub fn apply_field_fill(
    package: &mut HwpxPackage,
    scan: &StructuralBoundaryScan,
    pair: &BoundaryPairRef,
    new_value: &str,
) -> Result<FieldFillMutation, NativeAdmissionError> {
    let value = canonical_field_value(new_value)?;
    let details = verify_scan(package, scan)?;
    let (detail, occurrence, pairing_usable) = details
        .iter()
        .find_map(|detail| {
            detail
                .fields
                .iter()
                .find(|(found, _)| found == pair)
                .map(|(_, occurrence)| {
                    let usable = scan
                        .entries
                        .iter()
                        .find(|entry| entry.entry == detail.entry)
                        .is_some_and(|entry| entry.field_pairing_usable);
                    (detail, occurrence, usable)
                })
        })
        .ok_or_else(|| error("field pair is not part of this scan"))?;
    let old = read_field_text(&detail.doc, &occurrence.texts);
    if !occurrence.texts.is_empty() && old.exact() && old.text == value {
        return Ok(FieldFillMutation {
            filled: true,
            modified: false,
            structure_changed: false,
            effects: Vec::new(),
            blockers: Vec::new(),
        });
    }
    let index = build_native_admission_index(detail);
    let (effects, blockers) = plan_field_fill(&detail.doc, &index, occurrence, pairing_usable);
    if !blockers.is_empty() {
        return Ok(FieldFillMutation {
            filled: false,
            modified: false,
            structure_changed: false,
            effects: Vec::new(),
            blockers,
        });
    }
    let mut candidate = detail.doc.clone();
    let mut texts = occurrence.texts.clone();
    let mut performed = Vec::new();
    let mut structure_changed = false;
    if texts.is_empty() {
        let slot = native_element(&mut candidate, "t", &[]);
        if occurrence.begin_run == occurrence.end_run {
            let at = content_index(&candidate, occurrence.begin_run, occurrence.end_ctrl)?;
            candidate.insert_element(occurrence.begin_run, at, slot)?;
        } else {
            let run = native_element(&mut candidate, "run", &[]);
            copy_run_attributes(&mut candidate, occurrence.begin_run, run);
            candidate.insert_element(run, 0, slot)?;
            let at = content_index(&candidate, occurrence.paragraph, occurrence.end_run)?;
            candidate.insert_element(occurrence.paragraph, at, run)?;
        }
        texts.push(slot);
        structure_changed = true;
        performed.push(effect(FieldFillEffectKind::SynthesizeSlot, Vec::new()));
    }
    let had_inline = texts.iter().any(|text| {
        candidate
            .node(*text)
            .children
            .iter()
            .any(|part| matches!(part, Content::Element(_)))
    });
    write_field_text(&mut candidate, texts[0], &value)?;
    for text in texts.iter().skip(1) {
        candidate.node_mut(*text).children.clear();
    }
    if had_inline {
        performed.extend(
            effects
                .iter()
                .filter(|item| item.kind == FieldFillEffectKind::RemoveInline)
                .cloned(),
        );
    }
    if texts.len() > 1 {
        performed.push(effect(FieldFillEffectKind::NormalizeFragments, Vec::new()));
    }
    let data = serialize_modified_section(&mut candidate)?;
    let ordinal = detail
        .fields
        .iter()
        .position(|(found, _)| found == pair)
        .ok_or_else(|| error("field pair is not part of this scan"))?;
    verify_field_candidate(detail, &data, std::iter::once((ordinal, value.as_str())))?;
    let entry = package
        .entries
        .iter_mut()
        .find(|item| item.name == detail.entry)
        .ok_or_else(|| error("stale native entry"))?;
    entry.data = data;
    Ok(FieldFillMutation {
        filled: true,
        modified: true,
        structure_changed,
        effects: performed,
        blockers: Vec::new(),
    })
}

fn verify_field_candidate<'a>(
    detail: &NativeEntryDetail,
    data: &[u8],
    expected: impl IntoIterator<Item = (usize, &'a str)>,
) -> Result<(), NativeAdmissionError> {
    let reparsed = parse_xml(data)?;
    let after = resolve_field_occurrences(&detail.entry, &reparsed);
    if !after.diagnostics.is_empty() || after.occurrences.len() != detail.fields.len() {
        return Err(error("field fill candidate pairing postcondition failed"));
    }
    if detail
        .fields
        .iter()
        .zip(&after.occurrences)
        .any(|((_, before), after)| {
            before.raw_name != after.raw_name
                || before.field_type != after.field_type
                || detail.doc.attr(before.begin, "id") != reparsed.attr(after.begin, "id")
                || detail.doc.attr(before.end, "beginIDRef")
                    != reparsed.attr(after.end, "beginIDRef")
        })
    {
        return Err(error("field fill candidate changed another pair"));
    }
    if expected.into_iter().any(|(ordinal, value)| {
        let readback = read_field_text(&reparsed, &after.occurrences[ordinal].texts);
        !readback.exact() || readback.text != value
    }) {
        return Err(error("field fill readback postcondition failed"));
    }
    Ok(())
}

/// Fast path for independent ordinary Field text replacements in one native entry.
///
/// `None` means at least one request needs the regular pair-local admission path. In
/// that case the package is untouched. The fast path accepts only existing plain
/// text slots, so it cannot synthesize nodes or remove protected inline content.
pub fn try_apply_simple_field_fill_batch(
    package: &mut HwpxPackage,
    scan: &StructuralBoundaryScan,
    entry: &str,
    requests: &[(BoundaryPairRef, String)],
) -> Result<Option<()>, NativeAdmissionError> {
    if requests.is_empty() {
        return Ok(Some(()));
    }
    let data = {
        let details = verify_scan(package, scan)?;
        let detail = details
            .iter()
            .find(|item| item.entry == entry)
            .ok_or_else(|| error("stale native entry"))?;
        let pairing_usable = scan
            .entries
            .iter()
            .find(|item| item.entry == entry)
            .is_some_and(|item| item.field_pairing_usable);
        let index = build_native_admission_index(detail);
        let mut seen = HashSet::new();
        let mut candidate = detail.doc.clone();
        let mut changed = false;
        let mut expected = Vec::with_capacity(requests.len());
        for (pair, raw) in requests {
            if !seen.insert(pair) {
                return Ok(None);
            }
            let value = canonical_field_value(raw)?;
            let Some((ordinal, slot, old)) =
                simple_field_request(detail, &index, &candidate, pair, &value, pairing_usable)
            else {
                return Ok(None);
            };
            if old != value {
                write_field_text(&mut candidate, slot, &value)?;
                changed = true;
            }
            expected.push((ordinal, value));
        }
        if !changed {
            return Ok(Some(()));
        }
        let data = serialize_modified_section(&mut candidate)?;
        verify_field_candidate(
            detail,
            &data,
            expected
                .iter()
                .map(|(ordinal, value)| (*ordinal, value.as_str())),
        )?;
        data
    };
    let target = package
        .entries
        .iter_mut()
        .find(|item| item.name == entry)
        .ok_or_else(|| error("stale native entry"))?;
    target.data = data;
    Ok(Some(()))
}

fn simple_field_request(
    detail: &NativeEntryDetail,
    index: &NativeAdmissionIndex,
    candidate: &XmlDocument,
    pair: &BoundaryPairRef,
    value: &str,
    pairing_usable: bool,
) -> Option<(usize, NodeId, String)> {
    if value.contains(['\t', '\n']) {
        return None;
    }
    let (ordinal, (_, occurrence)) = detail
        .fields
        .iter()
        .enumerate()
        .find(|(_, (found, _))| found == pair)?;
    if occurrence.texts.len() != 1
        || !candidate
            .node(occurrence.texts[0])
            .children
            .iter()
            .all(|part| matches!(part, Content::Text(_)))
    {
        return None;
    }
    let old = read_field_text(&detail.doc, &occurrence.texts);
    if !old.exact() {
        return None;
    }
    let (effects, blockers) = plan_field_fill(&detail.doc, index, occurrence, pairing_usable);
    if !effects.is_empty() || !blockers.is_empty() {
        return None;
    }
    Some((ordinal, occurrence.texts[0], old.text))
}

pub fn inspect_native_capabilities(
    package: &HwpxPackage,
    scan: &StructuralBoundaryScan,
) -> Result<NativeCapabilityInspection, NativeAdmissionError> {
    let details = verify_scan(package, scan)?;
    let mut field_fills = Vec::new();
    let mut bookmark_removals = Vec::new();
    for detail in details {
        let public = scan
            .entries
            .iter()
            .find(|item| item.entry == detail.entry)
            .ok_or_else(|| error("public/private scan entry mismatch"))?;
        let metadata_usable = !scan.diagnostics.iter().any(|item| {
            item.entry.as_deref() == Some(&detail.entry)
                && matches!(
                    item.kind,
                    StructuralDiagnosticKind::NonNativeMetatag
                        | StructuralDiagnosticKind::InvalidMetatagShape
                )
        });
        let index = build_native_admission_index(detail);
        for (pair, occurrence) in &detail.fields {
            let (supported_effects, blockers) =
                plan_field_fill(&detail.doc, &index, occurrence, public.field_pairing_usable);
            field_fills.push(FieldFillObservation {
                pair: pair.clone(),
                supported_effects,
                blockers,
            });
        }
        for (pair, bookmark) in &detail.bookmarks {
            let plan = plan_bookmark_removal(
                detail,
                &index,
                bookmark,
                BookmarkPlanPolicy {
                    topology_usable: public.bookmark_topology_usable,
                    metadata_usable,
                    field_pairing_usable: public.field_pairing_usable,
                    reject_whole_section: true,
                    reject_section_definition: true,
                },
            );
            bookmark_removals.push(BookmarkRemovalObservation {
                pair: pair.clone(),
                blockers: plan.blockers,
            });
        }
    }
    Ok(NativeCapabilityInspection {
        field_fills,
        bookmark_removals,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::package::PackageEntry;
    use crate::structural_boundary::scan_structural_boundaries;
    use serde_json::{Value, json};

    fn package(entry: &str, xml: &str) -> HwpxPackage {
        HwpxPackage {
            entries: vec![PackageEntry {
                name: entry.to_owned(),
                data: xml.as_bytes().to_vec(),
                stored: false,
            }],
        }
    }

    fn body_package(body: &str) -> HwpxPackage {
        package(
            "Contents/section0.xml",
            &format!(
                "<hs:sec xmlns:hs='{}' xmlns:hp='{HP_NS}'>{body}</hs:sec>",
                crate::structural_boundary::HS_NS
            ),
        )
    }

    fn paragraph(body: &str) -> String {
        format!("<hp:p><hp:run>{body}</hp:run></hp:p>")
    }

    fn bookmark(value: &str) -> String {
        format!(
            "<hp:ctrl><hp:fieldBegin id='1' type='BOOKMARK' name='B'/></hp:ctrl><hp:t>{value}</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl>"
        )
    }
    fn effects(items: &[FieldFillEffect]) -> Value {
        json!(
            items
                .iter()
                .map(|item| json!({"kind":item.kind.as_str(),"detail":item.detail}))
                .collect::<Vec<_>>()
        )
    }
    fn blockers(items: &[FieldFillBlocker]) -> Value {
        json!(
            items
                .iter()
                .map(|item| json!({"kind":item.kind.as_str(),"detail":item.detail}))
                .collect::<Vec<_>>()
        )
    }

    #[test]
    fn python_admission_and_fill_oracle() {
        let fixture: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/hwpx_xml_compat.json"))
                .unwrap();
        for case in fixture["cases"].as_array().unwrap() {
            let entry = case["entry"].as_str().unwrap();
            let xml = case["xml"].as_str().unwrap();
            let initial = package(entry, xml);
            let scan = scan_structural_boundaries(&initial);
            let inspection = inspect_native_capabilities(&initial, &scan).unwrap();
            let expected = &case["expected"]["admission"];
            assert_eq!(
                inspection.field_fills.len(),
                expected["fields"].as_array().unwrap().len(),
                "{}",
                case["id"]
            );
            assert_eq!(
                inspection.bookmark_removals.len(),
                expected["bookmarks"].as_array().unwrap().len(),
                "{}",
                case["id"]
            );
            for (at, observation) in inspection.field_fills.iter().enumerate() {
                assert_eq!(
                    effects(&observation.supported_effects),
                    expected["fields"][at]["effects"],
                    "{}",
                    case["id"]
                );
                assert_eq!(
                    blockers(&observation.blockers),
                    expected["fields"][at]["blockers"],
                    "{}",
                    case["id"]
                );
            }
            for (at, observation) in inspection.bookmark_removals.iter().enumerate() {
                let actual = json!(
                    observation
                        .blockers
                        .iter()
                        .map(|item| json!({"kind":item.kind.as_str(),"detail":item.detail}))
                        .collect::<Vec<_>>()
                );
                assert_eq!(
                    actual, expected["bookmarks"][at]["blockers"],
                    "{}",
                    case["id"]
                );
            }
            for fill in case["expected"]["fills"].as_array().into_iter().flatten() {
                let mut candidate = package(entry, xml);
                let scan = scan_structural_boundaries(&candidate);
                let pair = scan.native_entries[0].fields[0].0.clone();
                let before = candidate.clone();
                let result = apply_field_fill(
                    &mut candidate,
                    &scan,
                    &pair,
                    fill["value"].as_str().unwrap(),
                )
                .unwrap();
                assert_eq!(json!(result.filled), fill["filled"], "{}", case["id"]);
                assert_eq!(json!(result.modified), fill["modified"], "{}", case["id"]);
                assert_eq!(
                    json!(result.structure_changed),
                    fill["structure_changed"],
                    "{}",
                    case["id"]
                );
                assert_eq!(effects(&result.effects), fill["effects"], "{}", case["id"]);
                assert_eq!(
                    blockers(&result.blockers),
                    fill["blockers"],
                    "{}",
                    case["id"]
                );
                assert_eq!(
                    json!(candidate == before),
                    fill["xml_tree_unchanged"],
                    "{}",
                    case["id"]
                );
                let doc = parse_xml(&candidate.entries[0].data).unwrap();
                let fields = crate::field_occurrence::resolve_field_occurrences(entry, &doc);
                let read = read_field_text(&doc, &fields.occurrences[0].texts);
                assert_eq!(json!(read.text), fill["after_field_text"], "{}", case["id"]);
                let texts: Vec<_> = doc
                    .descendants(doc.root)
                    .into_iter()
                    .filter(|id| doc.node(*id).name.is(HP_NS, "t"))
                    .collect();
                let direct: Vec<_> = texts.iter().map(|id| doc.direct_text(*id)).collect();
                assert_eq!(json!(direct), fill["after_text_nodes"], "{}", case["id"]);
                let children: Vec<_> = texts
                    .iter()
                    .map(|id| {
                        doc.elements(*id)
                            .map(|child| doc.node(child).name.clark())
                            .collect::<Vec<_>>()
                    })
                    .collect();
                assert_eq!(
                    json!(children),
                    fill["after_inline_children"],
                    "{}",
                    case["id"]
                );
            }
        }
    }

    #[test]
    fn repeated_field_identity_and_alternate_prefix_slot() {
        let ns = crate::structural_boundary::HS_NS;
        let one = "<x:run><x:ctrl><x:fieldBegin id='1' name='same' type='CLICK_HERE'/></x:ctrl><x:t>FIRST</x:t><x:ctrl><x:fieldEnd beginIDRef='1'/></x:ctrl></x:run>";
        let two = "<x:run><x:ctrl><x:fieldBegin id='2' name='same' type='CLICK_HERE'/></x:ctrl><x:t>SECOND</x:t><x:ctrl><x:fieldEnd beginIDRef='2'/></x:ctrl></x:run>";
        let xml = format!("<s:sec xmlns:s='{ns}' xmlns:x='{HP_NS}'><x:p>{one}{two}</x:p></s:sec>");
        let mut package = self::package("Contents/section0.xml", &xml);
        let original = package.clone();
        let first_scan = scan_structural_boundaries(&original);
        let requests = vec![
            (
                first_scan.native_entries[0].fields[0].0.clone(),
                "A&B".into(),
            ),
            (
                first_scan.native_entries[0].fields[1].0.clone(),
                "B<2".into(),
            ),
        ];
        let mut batch = original.clone();
        assert!(
            try_apply_simple_field_fill_batch(
                &mut batch,
                &first_scan,
                "Contents/section0.xml",
                &requests,
            )
            .unwrap()
            .is_some()
        );
        let mut sequential = original.clone();
        for (at, value) in ["A&B", "B<2"].iter().enumerate() {
            let scan = scan_structural_boundaries(&sequential);
            let pair = scan.native_entries[0].fields[at].0.clone();
            apply_field_fill(&mut sequential, &scan, &pair, value).unwrap();
        }
        assert_eq!(batch.entries[0].data, sequential.entries[0].data);
        let mut fallback = original.clone();
        assert!(
            try_apply_simple_field_fill_batch(
                &mut fallback,
                &first_scan,
                "Contents/section0.xml",
                &[(requests[0].0.clone(), "line\nbreak".into())],
            )
            .unwrap()
            .is_none()
        );
        assert_eq!(fallback, original);
        let scan = scan_structural_boundaries(&package);
        let second = scan.native_entries[0].fields[1].0.clone();
        let result = apply_field_fill(&mut package, &scan, &second, "CHANGED").unwrap();
        assert!(result.filled && result.modified);
        let doc = parse_xml(&package.entries[0].data).unwrap();
        let fields =
            crate::field_occurrence::resolve_field_occurrences("Contents/section0.xml", &doc);
        assert_eq!(
            fields
                .occurrences
                .iter()
                .map(|item| read_field_text(&doc, &item.texts).text)
                .collect::<Vec<_>>(),
            vec!["FIRST", "CHANGED"]
        );

        for (binding, attribute, uri) in [
            ("xmlns:q='urn:style'", "q:attr='v'", "urn:style"),
            ("xmlns:hp='urn:other'", "hp:custom='v'", "urn:other"),
        ] {
            let xml = format!(
                "<s:sec xmlns:s='{ns}' xmlns:x='{HP_NS}'><x:p><x:run {binding} {attribute}><x:ctrl><x:fieldBegin id='3' name='slot' type='CLICK_HERE'/></x:ctrl></x:run><x:run><x:ctrl><x:fieldEnd beginIDRef='3'/></x:ctrl></x:run></x:p></s:sec>"
            );
            let mut package = self::package("Contents/section0.xml", &xml);
            let scan = scan_structural_boundaries(&package);
            let pair = scan.native_entries[0].fields[0].0.clone();
            assert!(
                apply_field_fill(&mut package, &scan, &pair, "NEW")
                    .unwrap()
                    .structure_changed
            );
            let doc = parse_xml(&package.entries[0].data).unwrap();
            let copied = doc
                .descendants(doc.root)
                .into_iter()
                .find(|id| {
                    native(&doc, *id, "run")
                        && doc
                            .node(*id)
                            .attributes
                            .iter()
                            .any(|attr| attr.name.namespace == uri)
                        && doc.elements(*id).any(|child| native(&doc, child, "t"))
                })
                .unwrap();
            assert_eq!(doc.node(copied).attributes[0].value, "v");
        }
    }

    #[test]
    fn protected_and_unknown_field_content_refuses_observation_and_write_identically() {
        for (prefix, value, expected) in [
            (
                "",
                "OLD<hp:markpenBegin/>X",
                FieldFillBlockerKind::UnpairedProtectedRange,
            ),
            (
                "",
                "OLD<hp:insertBegin Id='7'/><hp:insertEnd Id='7'/>",
                FieldFillBlockerKind::UnpairedProtectedRange,
            ),
            (
                "",
                "OLD<hp:outer><hp:inner/></hp:outer>",
                FieldFillBlockerKind::UnsupportedInlineObject,
            ),
            (
                "<hp:t><hp:markpenBegin/>BEFORE</hp:t>",
                "OLD",
                FieldFillBlockerKind::UnpairedProtectedRange,
            ),
        ] {
            let field = format!(
                "{prefix}<hp:ctrl><hp:fieldBegin name='F'/></hp:ctrl><hp:t>{value}</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>"
            );
            let mut package = body_package(&(paragraph(&field) + &paragraph("<hp:t>OUT</hp:t>")));
            let before = package.clone();
            let scan = scan_structural_boundaries(&package);
            let inspection = inspect_native_capabilities(&package, &scan).unwrap();
            let observed = &inspection.field_fills[0];
            assert!(!observed.fillable());
            assert!(observed.blockers.iter().any(|item| item.kind == expected));
            let result = apply_field_fill(&mut package, &scan, &observed.pair, "NEW").unwrap();
            assert!(!result.filled && !result.modified && !result.structure_changed);
            assert_eq!(result.blockers, observed.blockers);
            assert_eq!(package, before);
        }
    }

    #[test]
    fn bookmark_admission_and_removal_preserve_protected_content_and_invalid_metadata() {
        use crate::bookmark_region::{remove_bookmark_region, resolve_bookmark_topology};
        for (prefix, value, expected) in [
            ("", "IN<hp:markpenBegin/>X<hp:markpenEnd/>", None),
            (
                "",
                "IN<hp:markpenBegin/>",
                Some(BookmarkRemovalBlockerKind::UnpairedProtectedRange),
            ),
            (
                "<hp:p><hp:run><hp:t><hp:markpenBegin/>BEFORE</hp:t></hp:run></hp:p>",
                "IN",
                Some(BookmarkRemovalBlockerKind::UnpairedProtectedRange),
            ),
        ] {
            let mut package = body_package(
                &(prefix.to_owned()
                    + &paragraph(&bookmark(value))
                    + &paragraph("<hp:t>OUT</hp:t>")),
            );
            let before = package.clone();
            let scan = scan_structural_boundaries(&package);
            let inspected = inspect_native_capabilities(&package, &scan).unwrap();
            let observed = &inspected.bookmark_removals[0];
            assert_eq!(observed.removable(), expected.is_none());
            let target = resolve_bookmark_topology(&package).unwrap().remove(0);
            let removed = remove_bookmark_region(&mut package, &target);
            if let Some(kind) = expected {
                assert!(observed.blockers.iter().any(|item| item.kind == kind));
                assert!(
                    removed
                        .unwrap_err()
                        .to_string()
                        .contains("unpaired protected range")
                );
                assert_eq!(package, before);
            } else {
                removed.unwrap();
                let xml = String::from_utf8_lossy(&package.entries[0].data);
                assert!(xml.contains("OUT") && !xml.contains("markpen"));
            }
        }
        let malformed = bookmark("IN").replace(
            "name='B'/>",
            "name='B'><x:metaTag xmlns:x='urn:foreign'>bad</x:metaTag></hp:fieldBegin>",
        );
        let package = body_package(&(paragraph(&malformed) + &paragraph("<hp:t>OUT</hp:t>")));
        let mut scan = scan_structural_boundaries(&package);
        let inspected = inspect_native_capabilities(&package, &scan).unwrap();
        assert!(!inspected.bookmark_removals[0].removable());
        assert!(
            inspected.bookmark_removals[0]
                .blockers
                .iter()
                .any(|item| item.kind == BookmarkRemovalBlockerKind::BookmarkMetadataUnusable)
        );
        assert!(
            resolve_bookmark_topology(&package)
                .unwrap_err()
                .to_string()
                .contains("non-native namespace")
        );
        scan.diagnostics.clear();
        assert!(
            inspect_native_capabilities(&package, &scan)
                .unwrap_err()
                .to_string()
                .contains("evidence mismatch")
        );
    }

    #[test]
    fn entry_index_serves_multiple_pairs_without_rewalking_source_nodes() {
        let field = "<hp:ctrl><hp:fieldBegin name='F'/></hp:ctrl><hp:t>OLD</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>";
        let body = paragraph("<hp:t>OUT</hp:t>")
            + &paragraph(&bookmark("A"))
            + &paragraph(field)
            + &paragraph(&bookmark("B").replace("'1'", "'2'"))
            + &paragraph("<hp:t>TAIL</hp:t>");
        let package = body_package(&body);
        let scan = scan_structural_boundaries(&package);
        let observed = inspect_native_capabilities(&package, &scan).unwrap();
        assert_eq!(observed.bookmark_removals.len(), 2);
        let mut detail = scan.native_entries[0].clone();
        let index = build_native_admission_index(&detail);
        detail.nodes.clear();
        for ((_, field), expected) in detail.fields.iter().zip(&observed.field_fills) {
            let (effects, blockers) = plan_field_fill(&detail.doc, &index, field, true);
            assert_eq!(effects, expected.supported_effects);
            assert_eq!(blockers, expected.blockers);
        }
        for ((_, bookmark), expected) in detail.bookmarks.iter().zip(&observed.bookmark_removals) {
            let plan = plan_bookmark_removal(
                &detail,
                &index,
                bookmark,
                BookmarkPlanPolicy {
                    topology_usable: true,
                    metadata_usable: true,
                    field_pairing_usable: true,
                    reject_whole_section: true,
                    reject_section_definition: true,
                },
            );
            assert_eq!(plan.blockers, expected.blockers);
            assert_eq!(plan.removed_begins, [bookmark.begin]);
        }
    }

    #[test]
    fn mixed_comment_rewrite_blocks_but_exact_noop_preserves_bytes() {
        let ns = crate::structural_boundary::HS_NS;
        for text in ["OLD<!--retain-->", "OLD<hp:tab><!--retain--></hp:tab>"] {
            let xml = format!(
                "<hs:sec xmlns:hs='{ns}' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='x'/></hp:ctrl><hp:t>{text}</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>"
            );
            let mut package = package("Contents/section0.xml", &xml);
            let scan = scan_structural_boundaries(&package);
            let pair = scan.native_entries[0].fields[0].0.clone();
            let value = read_field_value(&package, &scan, &pair).unwrap();
            assert_eq!(value.text, "OLD");
            assert_eq!(value.unmodelled.is_empty(), text == "OLD<!--retain-->");
            let before = package.clone();
            let changed = apply_field_fill(&mut package, &scan, &pair, "NEW").unwrap();
            assert_eq!(
                changed.blockers[0].kind,
                FieldFillBlockerKind::UnsupportedInlineObject
            );
            assert_eq!(package, before);
            if text == "OLD<!--retain-->" {
                let same = apply_field_fill(&mut package, &scan, &pair, "OLD").unwrap();
                assert!(same.filled && !same.modified && same.blockers.is_empty());
                assert_eq!(package, before);
            }
        }
        let fixture: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/hwpx_xml_compat.json"))
                .unwrap();
        let case = fixture["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|case| case["id"] == "protected_range_crossing")
            .unwrap();
        let mut package = package(
            case["entry"].as_str().unwrap(),
            case["xml"].as_str().unwrap(),
        );
        let scan = scan_structural_boundaries(&package);
        let pair = scan.native_entries[0].fields[0].0.clone();
        let before = package.clone();
        let same = apply_field_fill(&mut package, &scan, &pair, "OLD").unwrap();
        assert!(same.filled && !same.modified && same.blockers.is_empty());
        assert_eq!(package, before);
    }

    #[test]
    fn scan_snapshot_and_pair_identity_are_required() {
        let fixture: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/hwpx_xml_compat.json"))
                .unwrap();
        let case = &fixture["cases"][0];
        let mut original = package(
            case["entry"].as_str().unwrap(),
            &case["xml"]
                .as_str()
                .unwrap()
                .replace("</hs:sec>", &(paragraph(&bookmark("IN")) + "</hs:sec>")),
        );
        original.entries.push(PackageEntry {
            name: "Contents/header.xml".into(),
            data: b"<style/>".to_vec(),
            stored: false,
        });
        let scan = scan_structural_boundaries(&original);
        let pair = scan.native_entries[0].fields[0].0.clone();
        assert!(read_field_value(&original, &scan, &pair).is_ok());
        let before = original.clone();
        let inspected = inspect_native_capabilities(&original, &scan).unwrap();
        assert_eq!(inspected.field_fills.len(), 1);
        assert_eq!(inspected.field_fills[0].pair, pair);
        assert!(inspected.field_fills[0].fillable());
        assert_eq!(inspected.bookmark_removals.len(), 1);
        assert_eq!(
            inspected.bookmark_removals[0].pair,
            scan.native_entries[0].bookmarks[0].0
        );
        assert!(inspected.bookmark_removals[0].removable());
        assert_eq!(original, before);

        let mut cases = Vec::new();
        let mut changed_bytes = original.clone();
        changed_bytes.entries[0].data.push(b' ');
        cases.push((changed_bytes, scan.clone(), pair.clone()));
        let mut changed_style = original.clone();
        changed_style.entries[1].data = b"<style>changed</style>".to_vec();
        cases.push((changed_style, scan.clone(), pair.clone()));
        let mut changed_roster = original.clone();
        changed_roster.entries.push(PackageEntry {
            name: "other.bin".into(),
            data: vec![1],
            stored: true,
        });
        cases.push((changed_roster, scan.clone(), pair.clone()));
        let mut changed_events = scan.clone();
        if let crate::structural_boundary::BoundaryEvent::FieldBegin { raw_name, .. } =
            &mut changed_events.entries[0].events[0]
        {
            *raw_name = Some("OTHER".into());
        } else {
            panic!("fixture must start with ordinary field");
        }
        cases.push((original.clone(), changed_events, pair.clone()));
        let mut changed_diagnostics = scan.clone();
        changed_diagnostics
            .diagnostics
            .push(crate::structural_boundary::StructuralDiagnostic {
                entry: None,
                kind: StructuralDiagnosticKind::MissingSectionEntry,
                order: None,
                detail: String::new(),
            });
        cases.push((original.clone(), changed_diagnostics, pair.clone()));
        let mut detached = scan.clone();
        detached.native_entries.clear();
        cases.push((original.clone(), detached, pair.clone()));
        for (package, evidence, _) in &cases {
            assert!(inspect_native_capabilities(package, evidence).is_err());
        }
        let foreign = scan_structural_boundaries(&original).native_entries[0].fields[0]
            .0
            .clone();
        cases.push((original.clone(), scan.clone(), foreign));
        for (mut package, evidence, token) in cases {
            let before = package.clone();
            assert!(read_field_value(&package, &evidence, &token).is_err());
            assert!(apply_field_fill(&mut package, &evidence, &token, "NEW").is_err());
            assert_eq!(package, before);
        }
        let long_text = "A".repeat(64);
        let xml = format!(
            "<hs:sec xmlns:hs='{}' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='long'/></hp:ctrl><hp:t>{long_text}</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>",
            crate::structural_boundary::HS_NS
        );
        let package = self::package("Contents/section0.xml", &xml);
        let scan = scan_structural_boundaries(&package);
        let pair = &scan.native_entries[0].fields[0].0;
        let value = read_field_value(&package, &scan, pair).unwrap();
        assert_eq!(value.text, long_text);
        assert!(value.unmodelled.is_empty());
    }

    #[test]
    fn entry_field_observation_keeps_unsupported_part_policy_outside_core() {
        let xml = format!(
            "<hs:sec xmlns:hs='{}' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' type='HYPERLINK' name=''/></hp:ctrl><hp:t>URL</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl><hp:ctrl><hp:fieldBegin id='2' type='CLICK_HERE' name='input'/></hp:ctrl><hp:t>VALUE</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='2'/></hp:ctrl></hp:run></hp:p></hs:sec>",
            crate::structural_boundary::HS_NS
        );
        let entry = "Contents/Header.XML";
        let package = self::package(entry, &xml);
        let observed = scan_entry_field_begins(&package, entry).unwrap();
        assert!(observed.pairing_usable());
        assert_eq!(observed.fields.len(), 2);
        assert_eq!(observed.fields[0].field_type.as_deref(), Some("HYPERLINK"));
        assert_eq!(observed.fields[0].raw_name.as_deref(), Some(""));
        assert_eq!(observed.fields[0].value.text, "URL");
        assert_eq!(observed.fields[1].field_type.as_deref(), Some("CLICK_HERE"));
        assert_eq!(observed.fields[1].raw_name.as_deref(), Some("input"));
        assert_eq!(observed.fields[1].value.text, "VALUE");
        assert!(observed.fields.iter().all(|field| field.value.exact()));
        let atypical = self::package(
            "Contents/section0.xml",
            &xml.replace("</hs:sec>", "<hp:other/></hs:sec>"),
        );
        assert!(
            scan_structural_boundaries(&atypical)
                .diagnostics
                .iter()
                .any(|item| item.kind == StructuralDiagnosticKind::InvalidContentEnvelope)
        );
        let observed = scan_entry_field_begins(&atypical, "Contents/section0.xml").unwrap();
        assert!(observed.pairing_usable());
        assert_eq!(observed.fields[1].value.text, "VALUE");
        assert!(scan_entry_field_begins(&package, "Contents/missing.xml").is_err());
        let orphan = self::package(entry, &xml.replace("beginIDRef='2'", "beginIDRef='9'"));
        let observed = scan_entry_field_begins(&orphan, entry).unwrap();
        assert!(!observed.pairing_usable());
        assert!(!observed.diagnostics.is_empty());
    }

    #[test]
    fn field_value_codec_roundtrips_inline_controls_and_rejects_forbidden_values() {
        let xml = format!(
            "<hs:sec xmlns:hs='{}' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='x'/></hp:ctrl><hp:t>OLD</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>",
            crate::structural_boundary::HS_NS
        );
        let mut package = package("Contents/section0.xml", &xml);
        let scan = scan_structural_boundaries(&package);
        let pair = scan.native_entries[0].fields[0].0.clone();
        apply_field_fill(&mut package, &scan, &pair, "A\tB\r\nC\rD E").unwrap();
        let doc = parse_xml(&package.entries[0].data).unwrap();
        let field =
            crate::field_occurrence::resolve_field_occurrences("Contents/section0.xml", &doc);
        assert_eq!(
            read_field_text(&doc, &field.occurrences[0].texts).text,
            "A\tB\nC\nD E"
        );
        let text = field.occurrences[0].texts[0];
        let inline: Vec<_> = doc
            .elements(text)
            .map(|id| doc.node(id).name.local.as_str())
            .collect();
        assert_eq!(inline, vec!["tab", "lineBreak", "lineBreak", "fwSpace"]);
        let tab = doc.elements(text).next().unwrap();
        assert_eq!(doc.attr(tab, "width"), Some("0"));
        assert_eq!(doc.attr(tab, "leader"), Some("0"));
        assert_eq!(doc.attr(tab, "type"), Some("1"));
        assert_eq!(canonical_field_value("A\r\nB\rC").unwrap(), "A\nB\nC");

        for value in [
            "\t",
            "\n\n",
            "\t머리",
            "꼬리\n",
            "a\t\tb",
            " ",
            "",
            "평문",
            "a\n\tb ",
            "탭\t줄\n고정 묶음 하이픈\u{ad}기호 &<>",
        ] {
            assert_eq!(canonical_field_value(value).unwrap(), value);
            let mut doc = parse_xml(format!("<hp:t xmlns:hp='{HP_NS}'/>").as_bytes()).unwrap();
            let root = doc.root;
            write_field_text(&mut doc, root, value).unwrap();
            let read = crate::text_extract::read_inline_text(&doc, root);
            assert!(read.exact());
            assert_eq!(read.text, value);
            let reopened = parse_xml(&doc.to_modified_bytes().unwrap()).unwrap();
            assert_eq!(
                crate::text_extract::read_inline_text(&reopened, reopened.root),
                read
            );
        }
        for (forbidden, points) in [
            ("a\u{b}b", "U+000B"),
            ("\0", "U+0000"),
            ("\u{1}", "U+0001"),
            ("x\u{7f}\u{85}", "U+007F, U+0085"),
            ("\u{1f}\u{c}\u{1f}", "U+000C, U+001F"),
            ("\u{fffe}", "U+FFFE"),
            ("\u{ffff}", "U+FFFF"),
        ] {
            assert_eq!(
                canonical_field_value(forbidden).unwrap_err().to_string(),
                format!("필드 값에 문서 본문에 쓸 수 없는 제어 문자가 있습니다: {points}")
            );
            let mut package = self::package("Contents/section0.xml", &xml);
            let scan = scan_structural_boundaries(&package);
            let pair = scan.native_entries[0].fields[0].0.clone();
            let before = package.clone();
            assert!(apply_field_fill(&mut package, &scan, &pair, forbidden).is_err());
            assert_eq!(package, before);
        }
    }
}
