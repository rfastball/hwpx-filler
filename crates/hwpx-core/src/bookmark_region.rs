//! Snapshot-bound native BOOKMARK regions and transactional section edits.

use crate::field_occurrence::resolve_field_occurrences;
use crate::lineseg::serialize_modified_section;
use crate::native_admission::{
    BookmarkPlanPolicy, NativeAdmissionError, boundary_paragraph, build_native_admission_index,
    content_index, native_element, plan_bookmark_removal, top_level_index, top_level_items,
};
use crate::package::HwpxPackage;
use crate::structural_boundary::{BookmarkPair, ContentEntryKind, NativeEntryDetail, digest};
use crate::text_extract::section_xml_names;
use crate::text_model::HP_NS;
use crate::xml_dom::{Attribute, Content, Name, NodeId, XmlDocument, parse_xml};
use std::collections::{BTreeMap, HashMap, HashSet};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BookmarkRegion {
    pub name: Option<String>,
    pub section: String,
    pub start_paragraph: usize,
    pub end_paragraph: usize,
    pub parent: Option<Box<BookmarkRegion>>,
    pub meta_tags: Vec<String>,
    pub meta_tag_attribute: Option<String>,
    pairing_id: String,
    section_sha256: [u8; 32],
}
impl BookmarkRegion {
    /// The native marker identity observed in this snapshot-bound region.
    pub fn pairing_id(&self) -> &str {
        &self.pairing_id
    }
}
#[derive(Clone, Debug)]
struct Section {
    entry: String,
    doc: XmlDocument,
    nodes: Vec<NodeId>,
    order: HashMap<NodeId, usize>,
    paragraphs: Vec<NodeId>,
    begins: HashMap<String, Vec<NodeId>>,
    ends: HashMap<String, Vec<NodeId>>,
    bookmark_begins: Vec<NodeId>,
    snapshot: [u8; 32],
}
#[derive(Clone, Debug)]
struct ResolvedRegion {
    region: BookmarkRegion,
    section_index: usize,
    begin: NodeId,
    end: NodeId,
    start_child: usize,
    end_child: usize,
    begin_order: usize,
    end_order: usize,
}
fn error(message: impl Into<String>) -> NativeAdmissionError {
    NativeAdmissionError(message.into())
}
fn native(doc: &XmlDocument, id: NodeId, local: &str) -> bool {
    doc.node(id).name.is(HP_NS, local)
}
fn package_entry<'a>(
    package: &'a HwpxPackage,
    name: &str,
) -> Result<&'a [u8], NativeAdmissionError> {
    package
        .entries
        .iter()
        .find(|item| item.name == name)
        .map(|item| item.data.as_slice())
        .ok_or_else(|| error(format!("HWPX section was not found: {name:?}")))
}
fn replace_entry(
    package: &mut HwpxPackage,
    name: &str,
    data: Vec<u8>,
) -> Result<(), NativeAdmissionError> {
    let entry = package
        .entries
        .iter_mut()
        .find(|item| item.name == name)
        .ok_or_else(|| error("HWPX section was not found"))?;
    entry.data = data;
    Ok(())
}
mod topology;
use topology::{candidate, fresh, native_detail, parse_sections_with_override, resolve, shape};
pub use topology::{resolve_bookmark_regions, resolve_bookmark_topology};

fn validate_extent(
    section: &Section,
    regions: &[ResolvedRegion],
    target: &ResolvedRegion,
    reject_whole: bool,
    reject_definition: bool,
) -> Result<crate::native_admission::BookmarkRemovalPlan, NativeAdmissionError> {
    let own: Vec<_> = regions
        .iter()
        .filter(|item| item.section_index == target.section_index)
        .cloned()
        .collect();
    let fields = resolve_field_occurrences(&section.entry, &section.doc);
    let detail = native_detail(section, &own, &fields.occurrences);
    let index = build_native_admission_index(&detail);
    let pair = BookmarkPair {
        begin: target.begin,
        end: target.end,
        name: target.region.name.clone(),
        meta_tags: target.region.meta_tags.clone(),
        meta_tag_attribute: target.region.meta_tag_attribute.clone(),
    };
    let plan = plan_bookmark_removal(
        &detail,
        &index,
        &pair,
        BookmarkPlanPolicy {
            topology_usable: true,
            metadata_usable: true,
            field_pairing_usable: fields.diagnostics.is_empty(),
            reject_whole_section: reject_whole,
            reject_section_definition: reject_definition,
        },
    );
    check_removal_plan(&plan, &fields.diagnostics)?;
    Ok(plan)
}

fn check_removal_plan(
    plan: &crate::native_admission::BookmarkRemovalPlan,
    diagnostics: &[crate::field_occurrence::FieldDiagnostic],
) -> Result<(), NativeAdmissionError> {
    if plan.blockers.is_empty() {
        return Ok(());
    }
    let messages = plan
        .blockers
        .iter()
        .map(|blocker| {
            if blocker.kind
                == crate::native_admission::BookmarkRemovalBlockerKind::FieldPairingUnusable
            {
                diagnostics
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join("; ")
            } else {
                blocker.detail.join(" ")
            }
        })
        .collect::<Vec<_>>();
    Err(error(messages.join("; ")))
}
fn direct_runs(doc: &XmlDocument, paragraph: NodeId) -> Vec<NodeId> {
    doc.elements(paragraph)
        .filter(|id| native(doc, *id, "run"))
        .collect()
}

mod create;
pub use create::create_bookmark_region;

fn removable_paragraph(
    selected: &Section,
    paragraph_index: usize,
) -> Result<NodeId, NativeAdmissionError> {
    let section = &selected.entry;
    if paragraph_index >= selected.paragraphs.len() {
        return Err(error("invalid paragraph index"));
    }
    if selected.paragraphs.len() == 1 {
        return Err(error(format!(
            "{section}: removing the paragraph would leave none"
        )));
    }
    let target = selected.paragraphs[paragraph_index];
    for id in selected.doc.descendants(target) {
        if matches!(
            selected.doc.node(id).name.local.as_str(),
            "fieldBegin" | "fieldEnd" | "secPr" | "colPr"
        ) {
            return Err(error(format!(
                "{section}: paragraph {paragraph_index} carries {} and cannot be removed",
                selected.doc.node(id).name.local
            )));
        }
    }
    Ok(target)
}

pub fn remove_top_level_paragraph(
    package: &mut HwpxPackage,
    section: &str,
    paragraph_index: usize,
) -> Result<(), NativeAdmissionError> {
    let (sections, current) = resolve(package, false)?;
    let selected = sections
        .iter()
        .find(|item| item.entry == section)
        .ok_or_else(|| error(format!("HWPX section was not found: {section:?}")))?;
    let target = removable_paragraph(selected, paragraph_index)?;
    let mut wanted = shape(&current, true);
    for item in &current {
        let region = &item.region;
        if region.section != section {
            continue;
        }
        let position = wanted
            .get_mut(&(region.section.clone(), region.pairing_id.clone()))
            .unwrap();
        if let Some((start, end)) = &mut position.positions {
            if paragraph_index < *start {
                *start -= 1;
            }
            if paragraph_index <= *end {
                *end -= 1;
            }
        }
    }
    let mut doc = selected.doc.clone();
    doc.remove_element_with_tail(target)?;
    let (data, after) = candidate(package, section, doc)?;
    if shape(&after, true) != wanted {
        return Err(error("top-level paragraph removal postcondition failed"));
    }
    replace_entry(package, section, data)
}

enum MetaEdit<'a> {
    Append(&'a str),
    Replace(usize, &'a str),
    Remove(usize),
}
fn edit_metatag(
    package: &mut HwpxPackage,
    handle: &BookmarkRegion,
    edit: MetaEdit<'_>,
) -> Result<(), NativeAdmissionError> {
    let (sections, current, at) = fresh(package, handle)?;
    let target = &current[at];
    let section = &sections[target.section_index];
    let mut doc = section.doc.clone();
    let children: Vec<_> = doc
        .elements(target.begin)
        .filter(|id| native(&doc, *id, "metaTag"))
        .collect();
    let mut expected = handle.meta_tags.clone();
    match edit {
        MetaEdit::Append(payload) => {
            let id = native_element(&mut doc, "metaTag", &[]);
            doc.node_mut(id)
                .children
                .push(Content::Text(payload.to_owned()));
            let position = doc.node(target.begin).children.len();
            doc.insert_element(target.begin, position, id)?;
            expected.push(payload.to_owned());
        }
        MetaEdit::Replace(index, payload) => {
            let id = *children
                .get(index)
                .ok_or_else(|| error(format!("hp:metaTag index out of range: {index}")))?;
            doc.node_mut(id).children = vec![Content::Text(payload.to_owned())];
            expected[index] = payload.to_owned();
        }
        MetaEdit::Remove(index) => {
            let id = *children
                .get(index)
                .ok_or_else(|| error(format!("hp:metaTag index out of range: {index}")))?;
            doc.remove_element_with_tail(id)?;
            expected.remove(index);
        }
    }
    let mut wanted = shape(&current, true);
    wanted
        .get_mut(&(handle.section.clone(), handle.pairing_id.clone()))
        .unwrap()
        .meta_tags = expected;
    let (data, after) = candidate(package, &handle.section, doc)?;
    if shape(&after, true) != wanted {
        return Err(error("BOOKMARK MetaTag mutation postcondition failed"));
    }
    replace_entry(package, &handle.section, data)
}
pub fn append_bookmark_metatag(
    package: &mut HwpxPackage,
    region: &BookmarkRegion,
    payload: &str,
) -> Result<(), NativeAdmissionError> {
    edit_metatag(package, region, MetaEdit::Append(payload))
}
pub fn replace_bookmark_metatag(
    package: &mut HwpxPackage,
    region: &BookmarkRegion,
    index: usize,
    payload: &str,
) -> Result<(), NativeAdmissionError> {
    edit_metatag(package, region, MetaEdit::Replace(index, payload))
}
pub fn remove_bookmark_metatag(
    package: &mut HwpxPackage,
    region: &BookmarkRegion,
    index: usize,
) -> Result<(), NativeAdmissionError> {
    edit_metatag(package, region, MetaEdit::Remove(index))
}

/// One native BOOKMARK rename within a single source snapshot.
pub struct BookmarkRename<'a> {
    pub region: &'a BookmarkRegion,
    pub name: &'a str,
    pub metatag: Option<(usize, &'a str)>,
}

fn set_plain_attribute(doc: &mut XmlDocument, id: NodeId, key: &str, value: &str) {
    if let Some(attribute) = doc
        .node_mut(id)
        .attributes
        .iter_mut()
        .find(|attribute| attribute.name.namespace.is_empty() && attribute.name.local == key)
    {
        attribute.value = value.to_owned();
    } else {
        doc.node_mut(id).attributes.push(Attribute {
            name: Name {
                raw: key.to_owned(),
                namespace: String::new(),
                local: key.to_owned(),
            },
            value: value.to_owned(),
        });
    }
}

/// Apply related BOOKMARK name and MetaTag edits together. Every handle must
/// belong to the same current snapshot and entry; the candidate is resolved
/// before the package is changed.
pub fn rename_bookmark_regions(
    package: &mut HwpxPackage,
    edits: &[BookmarkRename<'_>],
) -> Result<(), NativeAdmissionError> {
    if edits.is_empty() {
        return Ok(());
    }
    let (sections, current) = resolve(package, false)?;
    let entry = &edits[0].region.section;
    let section = sections
        .iter()
        .find(|section| &section.entry == entry)
        .ok_or_else(|| error("BOOKMARK section is missing"))?;
    let mut doc = section.doc.clone();
    let mut expected = shape(&current, true);
    let mut seen = HashSet::new();
    for edit in edits {
        if &edit.region.section != entry || !seen.insert(edit.region.pairing_id.as_str()) {
            return Err(error(
                "BOOKMARK rename entries must be unique and in one section",
            ));
        }
        let region = current
            .iter()
            .find(|item| item.region == *edit.region)
            .ok_or_else(|| error("BOOKMARK handle is stale; resolve again"))?;
        set_plain_attribute(&mut doc, region.begin, "name", edit.name);
        let wanted = expected
            .get_mut(&(entry.clone(), edit.region.pairing_id.clone()))
            .ok_or_else(|| error("BOOKMARK rename target is missing"))?;
        wanted.name = Some(edit.name.to_owned());
        if let Some((index, payload)) = edit.metatag {
            let tags: Vec<_> = doc
                .elements(region.begin)
                .filter(|id| native(&doc, *id, "metaTag"))
                .collect();
            let tag = *tags
                .get(index)
                .ok_or_else(|| error("BOOKMARK MetaTag index out of range"))?;
            doc.node_mut(tag).children = vec![Content::Text(payload.to_owned())];
            *wanted
                .meta_tags
                .get_mut(index)
                .ok_or_else(|| error("BOOKMARK MetaTag index out of range"))? = payload.to_owned();
        }
    }
    let (data, after) = candidate(package, entry, doc)?;
    if shape(&after, true) != expected {
        return Err(error("BOOKMARK rename postcondition failed"));
    }
    replace_entry(package, entry, data)
}

/// Move a native BOOKMARK pair to top-level paragraph boundaries while
/// retaining all other regions and their parent relationships.
pub fn adjust_bookmark_region(
    package: &mut HwpxPackage,
    handle: &BookmarkRegion,
    start: usize,
    end: usize,
) -> Result<(), NativeAdmissionError> {
    let (sections, current, at) = fresh(package, handle)?;
    let region = &current[at];
    let section = &sections[region.section_index];
    if start > end || end >= section.paragraphs.len() {
        return Err(error("invalid BOOKMARK paragraph range"));
    }
    let first_runs = direct_runs(&section.doc, section.paragraphs[start]);
    let last_runs = direct_runs(&section.doc, section.paragraphs[end]);
    if first_runs.is_empty() || last_runs.is_empty() {
        return Err(error(
            "BOOKMARK boundary paragraphs must contain a direct native hp:run",
        ));
    }
    let mut doc = section.doc.clone();
    let begin_ctrl = doc
        .parent(region.begin)
        .ok_or_else(|| error("detached BOOKMARK begin"))?;
    let end_ctrl = doc
        .parent(region.end)
        .ok_or_else(|| error("detached BOOKMARK end"))?;
    doc.remove_element_with_tail(begin_ctrl)?;
    doc.remove_element_with_tail(end_ctrl)?;
    let parent = region.region.parent.as_ref().and_then(|parent| {
        current.iter().find(|item| {
            item.region.pairing_id == parent.pairing_id && item.region.section == parent.section
        })
    });
    if let Some(owner) = parent.filter(|owner| owner.region.start_paragraph == start) {
        let control = doc
            .parent(owner.begin)
            .ok_or_else(|| error("detached parent BOOKMARK begin"))?;
        let run = doc
            .parent(control)
            .ok_or_else(|| error("detached parent BOOKMARK run"))?;
        let index = content_index(&doc, run, control)? + 1;
        doc.insert_element(run, index, begin_ctrl)?;
    } else {
        doc.insert_element(first_runs[0], 0, begin_ctrl)?;
    }
    if let Some(owner) = parent.filter(|owner| owner.region.end_paragraph == end) {
        let control = doc
            .parent(owner.end)
            .ok_or_else(|| error("detached parent BOOKMARK end"))?;
        let run = doc
            .parent(control)
            .ok_or_else(|| error("detached parent BOOKMARK run"))?;
        let index = content_index(&doc, run, control)?;
        doc.insert_element(run, index, end_ctrl)?;
    } else {
        let run = *last_runs
            .last()
            .ok_or_else(|| error("missing final BOOKMARK run"))?;
        let index = doc.node(run).children.len();
        doc.insert_element(run, index, end_ctrl)?;
    }
    let mut expected = shape(&current, true);
    expected
        .get_mut(&(handle.section.clone(), handle.pairing_id.clone()))
        .ok_or_else(|| error("BOOKMARK move target is missing"))?
        .positions = Some((start, end));
    let (data, after) = candidate(package, &handle.section, doc)?;
    if shape(&after, true) != expected {
        return Err(error("BOOKMARK move postcondition failed"));
    }
    replace_entry(package, &handle.section, data)
}

mod move_block;
pub use move_block::move_bookmark_block;

mod duplicate;
pub use duplicate::{BookmarkCloneNames, duplicate_bookmark_block};

fn remove_marker(doc: &mut XmlDocument, marker: NodeId) -> Result<(), NativeAdmissionError> {
    let ctrl = doc
        .parent(marker)
        .ok_or_else(|| error("detached BOOKMARK marker"))?;
    let run = doc
        .parent(ctrl)
        .ok_or_else(|| error("detached BOOKMARK control"))?;
    doc.remove_element(marker)?;
    let empty_ctrl = !doc.node(ctrl).children.iter().any(|part| {
        matches!(
            part,
            Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
        )
    }) && doc.direct_text(ctrl).trim().is_empty();
    if empty_ctrl {
        let at = content_index(doc, run, ctrl)?;
        let carry = doc.node(ctrl).children.clone();
        doc.remove_element(ctrl)?;
        for (offset, part) in carry.into_iter().enumerate() {
            doc.node_mut(run).children.insert(at + offset, part);
        }
    }
    Ok(())
}

pub fn unwrap_bookmark_region(
    package: &mut HwpxPackage,
    handle: &BookmarkRegion,
) -> Result<(), NativeAdmissionError> {
    let (sections, current, at) = fresh(package, handle)?;
    let target = &current[at];
    let key = (handle.section.clone(), handle.pairing_id.clone());
    let mut wanted = shape(&current, true);
    wanted.remove(&key);
    let promoted = handle
        .parent
        .as_ref()
        .map(|item| (item.section.clone(), item.pairing_id.clone()));
    for item in &current {
        if item.region.parent.as_ref().is_some_and(|parent| {
            parent.section == handle.section && parent.pairing_id == handle.pairing_id
        }) {
            wanted
                .get_mut(&(item.region.section.clone(), item.region.pairing_id.clone()))
                .unwrap()
                .parent = promoted.clone();
        }
    }
    let mut doc = sections[target.section_index].doc.clone();
    remove_marker(&mut doc, target.begin)?;
    remove_marker(&mut doc, target.end)?;
    let (data, after) = candidate(package, &handle.section, doc)?;
    if shape(&after, true) != wanted {
        return Err(error("BOOKMARK unwrap postcondition failed"));
    }
    replace_entry(package, &handle.section, data)
}

fn prune_to_markers(doc: &mut XmlDocument, paragraph: NodeId, markers: &HashSet<NodeId>) {
    let mut keep = markers.clone();
    for marker in markers {
        let mut current = doc.parent(*marker);
        while let Some(id) = current {
            if id == paragraph {
                break;
            }
            keep.insert(id);
            current = doc.parent(id);
        }
    }
    fn prune(doc: &mut XmlDocument, id: NodeId, keep: &HashSet<NodeId>, markers: &HashSet<NodeId>) {
        let children = doc.node(id).children.clone();
        let mut retained = Vec::new();
        for part in children {
            if let Content::Element(child) = part {
                if keep.contains(&child) {
                    if !markers.contains(&child) {
                        prune(doc, child, keep, markers);
                    }
                    retained.push(Content::Element(child));
                } else {
                    doc.node_mut(child).parent = None;
                }
            }
        }
        doc.node_mut(id).children = retained;
    }
    prune(doc, paragraph, &keep, markers);
}

pub fn remove_bookmark_region(
    package: &mut HwpxPackage,
    handle: &BookmarkRegion,
) -> Result<(), NativeAdmissionError> {
    let (sections, current, at) = fresh(package, handle)?;
    let target = &current[at];
    let section = &sections[target.section_index];
    let plan = validate_extent(section, &current, target, true, true)?;
    let removed: HashSet<_> = plan.removed_begins.iter().copied().collect();
    let mut wanted = shape(&current, false);
    for item in &current {
        if item.region.section == handle.section && removed.contains(&item.begin) {
            wanted.remove(&(item.region.section.clone(), item.region.pairing_id.clone()));
        }
    }
    let mut doc = section.doc.clone();
    let children = top_level_items(&doc);
    for child in children[target.start_child..=target.end_child]
        .iter()
        .copied()
    {
        let child = child.ok_or_else(|| error("non-paragraph section child in BOOKMARK extent"))?;
        let markers: HashSet<_> = plan
            .protected_markers
            .iter()
            .copied()
            .filter(|marker| boundary_paragraph(&doc, *marker) == Some(child))
            .collect();
        if markers.is_empty() {
            doc.remove_element_with_tail(child)?;
        } else {
            prune_to_markers(&mut doc, child, &markers);
        }
    }
    let (data, after) = candidate(package, &handle.section, doc)?;
    if shape(&after, false) != wanted {
        return Err(error("BOOKMARK content removal postcondition failed"));
    }
    replace_entry(package, &handle.section, data)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::package::{PackageEntry, PackageLimits};
    use serde_json::Value;

    const SECTION: &str = "Contents/section0.xml";

    fn package_with_sections(sections: &[(&str, &str)]) -> HwpxPackage {
        let mut entries = vec![PackageEntry {
            name: crate::package::MIMETYPE_NAME.into(),
            data: crate::package::MIMETYPE_VALUE.into(),
            stored: true,
        }];
        entries.extend(sections.iter().map(|(name, xml)| PackageEntry {
            name: (*name).into(),
            data: xml.as_bytes().to_vec(),
            stored: false,
        }));
        HwpxPackage { entries }
    }

    fn body_package(body: &str) -> HwpxPackage {
        package_with_sections(&[(
            SECTION,
            &format!(
                "<hs:sec xmlns:hs='{}' xmlns:hp='{HP_NS}'>{body}</hs:sec>",
                crate::structural_boundary::HS_NS
            ),
        )])
    }

    fn paragraph(body: &str) -> String {
        format!("<hp:p><hp:run>{body}</hp:run></hp:p>")
    }

    fn begin(id: &str, name: &str) -> String {
        format!("<hp:ctrl><hp:fieldBegin id='{id}' type='BOOKMARK' name='{name}'/></hp:ctrl>")
    }

    fn end(id: &str) -> String {
        format!("<hp:ctrl><hp:fieldEnd beginIDRef='{id}'/></hp:ctrl>")
    }

    fn reparsed(package: &HwpxPackage) -> HwpxPackage {
        HwpxPackage::from_bytes(&package.to_bytes().unwrap(), PackageLimits::default()).unwrap()
    }

    fn spans(package: &HwpxPackage) -> Vec<(String, usize, usize, Option<String>)> {
        resolve_bookmark_topology(package)
            .unwrap()
            .into_iter()
            .map(|item| {
                (
                    item.name.unwrap(),
                    item.start_paragraph,
                    item.end_paragraph,
                    item.parent.and_then(|parent| parent.name),
                )
            })
            .collect()
    }

    fn assert_error(result: Result<(), NativeAdmissionError>, message: &str) {
        let actual = result.unwrap_err().to_string();
        assert!(
            actual.contains(message),
            "expected {message:?}, got {actual:?}"
        );
    }

    fn two_sections(first: &str, second: &str) -> HwpxPackage {
        let mut package = body_package(first);
        package.entries.push(PackageEntry {
            name: "Contents/section1.xml".into(),
            data: package_entry(&body_package(second), SECTION)
                .unwrap()
                .to_vec(),
            stored: false,
        });
        package
    }

    fn assert_spans(package: &HwpxPackage, expected: &[(&str, usize, usize, Option<&str>)]) {
        assert_eq!(
            spans(package),
            expected
                .iter()
                .map(|(name, start, end, parent)| (
                    (*name).into(),
                    *start,
                    *end,
                    parent.map(str::to_owned)
                ))
                .collect::<Vec<_>>()
        );
    }

    fn assert_paired(package: &HwpxPackage) {
        let markers = projection(package).1;
        let begins = markers
            .iter()
            .filter(|(kind, _)| kind == "begin")
            .map(|(_, id)| id)
            .collect::<HashSet<_>>();
        let ends = markers
            .iter()
            .filter(|(kind, _)| kind == "end")
            .map(|(_, id)| id)
            .collect::<HashSet<_>>();
        assert_eq!(begins, ends);
    }

    fn section_shape(package: &HwpxPackage) -> String {
        let doc = parse_xml(package_entry(package, SECTION).unwrap()).unwrap();
        paragraph_shape(&doc, doc.root)
    }

    fn marker_positions(package: &HwpxPackage) -> Vec<(usize, String, Option<String>)> {
        let doc = parse_xml(package_entry(package, SECTION).unwrap()).unwrap();
        let mut positions = Vec::new();
        for (index, paragraph) in doc
            .elements(doc.root)
            .filter(|id| native(&doc, *id, "p"))
            .enumerate()
        {
            for id in doc.descendants(paragraph) {
                if native(&doc, id, "fieldBegin") || native(&doc, id, "fieldEnd") {
                    positions.push((
                        index,
                        doc.node(id).name.clark(),
                        doc.attr(id, "name").map(str::to_owned),
                    ));
                }
            }
        }
        positions
    }

    fn assert_clean(package: &HwpxPackage) {
        let doc = parse_xml(package_entry(package, SECTION).unwrap()).unwrap();
        for id in doc.descendants(doc.root) {
            assert!(!native(&doc, id, "linesegarray"));
            if native(&doc, id, "p") || native(&doc, id, "run") {
                assert!(!doc.node(id).children.is_empty());
            }
        }
    }

    fn retained_paragraphs(package: &HwpxPackage, texts: &[&str]) -> Vec<String> {
        let doc = parse_xml(package_entry(package, SECTION).unwrap()).unwrap();
        doc.elements(doc.root)
            .filter(|id| native(&doc, *id, "p"))
            .filter(|id| texts.contains(&doc.iter_text(*id).as_str()))
            .map(|id| paragraph_shape(&doc, id))
            .collect()
    }

    fn metatag_fixture(name: &str) -> HwpxPackage {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/metatag_s1")
            .join(name);
        HwpxPackage::from_bytes(&std::fs::read(path).unwrap(), PackageLimits::default()).unwrap()
    }
    fn semantic_carriers(package: &HwpxPackage) -> Vec<(String, String)> {
        let mut found = Vec::new();
        for entry in &package.entries {
            if !entry.name.ends_with(".xml") {
                continue;
            }
            let doc = parse_xml(&entry.data).unwrap();
            for id in doc.descendants(doc.root) {
                let node = doc.node(id);
                if node.name.local == "metaTag" {
                    let raw = doc.direct_text(id);
                    if raw.starts_with('{') {
                        let owner = doc.node(doc.parent(id).unwrap()).name.local.as_str();
                        let normalized = serde_json::from_str::<Value>(&raw).unwrap().to_string();
                        found.push((format!("{}:{owner}#text", entry.name), normalized));
                    }
                }
                for attribute in &node.attributes {
                    if matches!(attribute.name.local.as_str(), "metaTag" | "metatag")
                        && attribute.value.starts_with('{')
                    {
                        let normalized = serde_json::from_str::<Value>(&attribute.value)
                            .unwrap()
                            .to_string();
                        found.push((
                            format!(
                                "{}:{}@{}",
                                entry.name, node.name.local, attribute.name.local
                            ),
                            normalized,
                        ));
                    }
                }
            }
        }
        found.sort();
        found
    }

    #[test]
    fn hancom_carrier_corpus_keeps_supported_tags_and_drops_unsupported_storage() {
        let authored = semantic_carriers(&metatag_fixture("M1-hancom-authored.hwpx"));
        assert_eq!(authored.len(), 5);
        assert_eq!(
            authored,
            semantic_carriers(&metatag_fixture("M1-resaved.hwpx"))
        );
        assert_eq!(
            authored,
            semantic_carriers(&metatag_fixture("M3-no-sharp.hwpx"))
        );
        let names: Vec<_> = authored
            .iter()
            .map(|(carrier, payload)| {
                (
                    carrier.as_str(),
                    serde_json::from_str::<Value>(payload).unwrap()["name"]
                        .as_str()
                        .unwrap()
                        .to_owned(),
                )
            })
            .collect();
        assert_eq!(
            names,
            [
                ("Contents/header.xml:head#text", "#hf_test_doc".into()),
                (
                    "Contents/section0.xml:fieldBegin#text",
                    "#hf_test_field".into()
                ),
                (
                    "Contents/section0.xml:polygon#text",
                    "#hf_test_shape".into()
                ),
                (
                    "Contents/section0.xml:subList@metatag",
                    "#hf_test_cell".into()
                ),
                ("Contents/section0.xml:tbl#text", "#hf_test_table".into()),
            ]
        );
        let renamed = semantic_carriers(&metatag_fixture("M2-renamed.hwpx"));
        assert_eq!(
            renamed
                .iter()
                .filter(|item| !item.0.contains("fieldBegin"))
                .collect::<Vec<_>>(),
            authored
                .iter()
                .filter(|item| !item.0.contains("fieldBegin"))
                .collect::<Vec<_>>()
        );
        assert!(
            renamed
                .iter()
                .any(|(carrier, payload)| carrier.contains("fieldBegin")
                    && payload.contains("#hf_slot_test"))
        );

        let g1 = semantic_carriers(&metatag_fixture("G1-element-carriers.hwpx"));
        assert_eq!(g1.len(), 4);
        assert_eq!(g1, semantic_carriers(&metatag_fixture("G1-resaved.hwpx")));
        let g2 = semantic_carriers(&metatag_fixture("G2-attribute-carriers.hwpx"));
        assert_eq!(g2.len(), 3);
        assert_eq!(
            g2.iter()
                .map(|(carrier, _)| carrier
                    .rsplit_once('@')
                    .map(|(_, kind)| kind)
                    .unwrap_or("#text"))
                .collect::<std::collections::HashSet<_>>(),
            ["metaTag", "metatag", "#text"].into_iter().collect()
        );
        for (_, raw) in &g2 {
            let payload: Value = serde_json::from_str(raw).unwrap();
            let body = &payload["hwpxFiller"];
            assert_eq!(body["quoted"], "he said \"yes\" & <no>");
            assert_eq!(body["label"], "추가 지급 안내");
            assert_eq!(body["spaced"], "  leading and trailing  ");
            assert_eq!(body["long"].as_str().unwrap().chars().count(), 512);
        }
        let g2_saved = semantic_carriers(&metatag_fixture("G2-resaved.hwpx"));
        assert_eq!(g2_saved.len(), 2);
        assert_eq!(
            g2_saved,
            g2.into_iter()
                .filter(|(carrier, _)| !carrier.ends_with("fieldBegin@metaTag"))
                .collect::<Vec<_>>()
        );
        let source = metatag_fixture("G3-package-carriers.hwpx");
        let saved = metatag_fixture("G3-resaved.hwpx");
        for name in [
            "Contents/hwpxfiller-s1-declared.json",
            "Contents/hwpxfiller-s1-undeclared.json",
        ] {
            assert!(source.entries.iter().any(|entry| entry.name == name));
            assert!(!saved.entries.iter().any(|entry| entry.name == name));
        }
        let source_catalog = source
            .entries
            .iter()
            .find(|entry| entry.name == "Contents/content.hpf")
            .unwrap();
        let saved_catalog = saved
            .entries
            .iter()
            .find(|entry| entry.name == "Contents/content.hpf")
            .unwrap();
        assert!(String::from_utf8_lossy(&source_catalog.data).contains("hwpxFiller:s1probe"));
        assert!(!String::from_utf8_lossy(&saved_catalog.data).contains("hwpxFiller:s1probe"));
    }

    #[test]
    fn native_corpus_topology_keeps_document_order_and_containment() {
        for (name, expected) in [
            ("R0-plain.hwpx", vec![]),
            ("R2-block-bookmark.hwpx", vec![("S0_BLOCK", 1, 3, None)]),
            (
                "D6-generated-minimal.hwpx",
                vec![("S0_GENERATED", 1, 3, None)],
            ),
            (
                "D6-generated-resaved.hwpx",
                vec![("S0_GENERATED", 1, 3, None)],
            ),
            ("R3-table-crossing.hwpx", vec![("S0_TABLE", 1, 3, None)]),
            (
                "R4-adjacent.hwpx",
                vec![("S0_LEFT", 1, 1, None), ("S0_RIGHT", 2, 2, None)],
            ),
            (
                "R5-nested-resaved.hwpx",
                vec![
                    ("S0_SLOT", 1, 4, None),
                    ("S0_OPT_A", 2, 2, Some("S0_SLOT")),
                    ("S0_OPT_B", 3, 3, Some("S0_SLOT")),
                ],
            ),
            (
                "G/G1-coincident-start.hwpx",
                vec![
                    ("S0_OPT_A", 1, 4, None),
                    ("S0_SLOT", 1, 1, Some("S0_OPT_A")),
                ],
            ),
            (
                "G/G1-resaved.hwpx",
                vec![
                    ("S0_OPT_A", 1, 4, None),
                    ("S0_SLOT", 1, 1, Some("S0_OPT_A")),
                ],
            ),
            (
                "G/G2-coincident-end.hwpx",
                vec![("S0_SLOT", 1, 4, None), ("S0_OPT_B", 4, 4, Some("S0_SLOT"))],
            ),
            (
                "G/G3-same-range.hwpx",
                vec![("S0_SLOT", 1, 4, None), ("S0_OPT_X", 1, 4, Some("S0_SLOT"))],
            ),
        ] {
            let package = fixture(name);
            assert_spans(&package, &expected);
            let regions = resolve_bookmark_regions(&package).unwrap();
            assert_eq!(
                resolve_bookmark_regions(&reparsed(&package)).unwrap(),
                regions,
                "{name}"
            );
        }
        for name in [
            "H/H1-crossing.hwpx",
            "H/H1-resaved.hwpx",
            "H/H2-reverse-order.hwpx",
        ] {
            let package = fixture(name);
            assert_spans(
                &package,
                &[("S0_LEFT", 1, 4, None), ("S0_RIGHT", 2, 3, Some("S0_LEFT"))],
            );
            assert_paired(&package);
        }
        let removed = fixture("H/H3-overlap-deleted.hwpx");
        assert_spans(&removed, &[("S0_LEFT", 1, 2, None)]);
        assert_paired(&removed);
        let point = fixture("R1-point-bookmark.hwpx");
        let section = point
            .entries
            .iter()
            .find(|entry| entry.name == "Contents/section0.xml")
            .unwrap();
        let doc = crate::xml_dom::parse_xml(&section.data).unwrap();
        let names: Vec<_> = doc
            .descendants(doc.root)
            .into_iter()
            .filter(|id| doc.node(*id).name.local == "bookmark")
            .map(|id| doc.attr(id, "name").unwrap().to_owned())
            .collect();
        assert_eq!(names, ["S0_POINT"]);
        assert!(resolve_bookmark_regions(&point).unwrap().is_empty());
    }

    #[test]
    fn unwrap_promotes_children_and_preserves_content_at_coincident_boundaries() {
        for (filename, target, expected) in [
            (
                "R5-nested.hwpx",
                "S0_OPT_A",
                vec![("S0_SLOT", None), ("S0_OPT_B", Some("S0_SLOT"))],
            ),
            (
                "R5-nested.hwpx",
                "S0_SLOT",
                vec![("S0_OPT_A", None), ("S0_OPT_B", None)],
            ),
            (
                "G/G1-coincident-start.hwpx",
                "S0_SLOT",
                vec![("S0_OPT_A", None)],
            ),
            (
                "G/G2-coincident-end.hwpx",
                "S0_OPT_B",
                vec![("S0_SLOT", None)],
            ),
            ("G/G3-same-range.hwpx", "S0_OPT_X", vec![("S0_SLOT", None)]),
        ] {
            let mut package = fixture(filename);
            let text = projection(&package).0;
            let stale = named(&package, target);
            unwrap_bookmark_region(&mut package, &stale).unwrap();
            let regions = resolve_bookmark_topology(&package).unwrap();
            assert_eq!(
                regions
                    .iter()
                    .map(|item| (
                        item.name.as_deref().unwrap(),
                        item.parent
                            .as_ref()
                            .and_then(|parent| parent.name.as_deref())
                    ))
                    .collect::<Vec<_>>(),
                expected
            );
            assert_eq!(projection(&package).0, text);
            assert_eq!(
                resolve_bookmark_topology(&reparsed(&package)).unwrap(),
                regions
            );
            let before = package.clone();
            assert_error(
                unwrap_bookmark_region(&mut package, &stale),
                "current package snapshot",
            );
            assert_eq!(package, before);
        }
    }

    #[test]
    fn coincident_content_removal_preserves_only_parent_markers() {
        for (filename, inner, outer, text) in [
            (
                "G/G1-coincident-start.hwpx",
                "S0_SLOT",
                "S0_OPT_A",
                vec!["AAA", "", "CCC", "DDD", "EEE"],
            ),
            (
                "G/G2-coincident-end.hwpx",
                "S0_OPT_B",
                "S0_SLOT",
                vec!["AAA", "BBB", "CCC", "DDD", ""],
            ),
            (
                "G/G3-same-range.hwpx",
                "S0_OPT_X",
                "S0_SLOT",
                vec!["AAA", "", ""],
            ),
        ] {
            let mut package = fixture(filename);
            let handle = named(&package, inner);
            remove_bookmark_region(&mut package, &handle).unwrap();
            assert_eq!(projection(&package).0, text);
            assert_eq!(
                resolve_bookmark_regions(&package)
                    .unwrap()
                    .iter()
                    .map(|item| item.name.as_deref().unwrap())
                    .collect::<Vec<_>>(),
                [outer]
            );
            assert_eq!(projection(&package).1.len(), 2);
            assert_paired(&package);
            assert_eq!(
                resolve_bookmark_regions(&reparsed(&package)).unwrap(),
                resolve_bookmark_regions(&package).unwrap()
            );
            let mut complete = fixture(filename);
            let handle = named(&complete, outer);
            remove_bookmark_region(&mut complete, &handle).unwrap();
            assert_eq!(projection(&complete).0, ["AAA"]);
            assert!(projection(&complete).1.is_empty());
        }
    }

    #[test]
    fn adjacent_removals_preserve_survivors_and_commute_after_reparse() {
        let mut final_shapes = Vec::new();
        for (first, second, text) in [
            ("S0_LEFT", "S0_RIGHT", "RIGHT"),
            ("S0_RIGHT", "S0_LEFT", "LEFT"),
        ] {
            let mut package = fixture("R4-adjacent.hwpx");
            let before = package.clone();
            let handle = named(&package, first);
            remove_bookmark_region(&mut package, &handle).unwrap();
            assert_eq!(projection(&package).0, ["AAA", text, "EEE"]);
            assert_eq!(
                retained_paragraphs(&package, &["AAA", text, "EEE"]),
                retained_paragraphs(&before, &["AAA", text, "EEE"])
            );
            assert_clean(&package);
            assert_eq!(
                resolve_bookmark_regions(&package).unwrap()[0]
                    .name
                    .as_deref(),
                Some(second)
            );
            let stable = package.clone();
            assert_error(
                remove_bookmark_region(&mut package, &handle),
                "current package snapshot",
            );
            assert_eq!(package, stable);
            let mut package = reparsed(&package);
            let survivor = named(&package, second);
            remove_bookmark_region(&mut package, &survivor).unwrap();
            assert_eq!(projection(&package).0, ["AAA", "EEE"]);
            assert_eq!(
                retained_paragraphs(&package, &["AAA", "EEE"]),
                retained_paragraphs(&before, &["AAA", "EEE"])
            );
            assert_clean(&package);
            assert!(resolve_bookmark_regions(&package).unwrap().is_empty());
            for entry in &before.entries {
                if entry.name != SECTION {
                    assert_eq!(package_entry(&package, &entry.name).unwrap(), entry.data);
                }
            }
            assert_eq!(section_shape(&reparsed(&package)), section_shape(&package));
            final_shapes.push(package_entry(&package, SECTION).unwrap().to_vec());
        }
        assert_eq!(final_shapes[0], final_shapes[1]);
        let mut package = fixture("R2-block-bookmark.hwpx");
        let stale = named(&package, "S0_BLOCK");
        let entry = package
            .entries
            .iter_mut()
            .find(|entry| entry.name == SECTION)
            .unwrap();
        entry.data = String::from_utf8(entry.data.clone())
            .unwrap()
            .replace("CCC", "CXC")
            .into_bytes();
        let before = package.clone();
        assert_error(
            remove_bookmark_region(&mut package, &stale),
            "current package snapshot",
        );
        assert_eq!(package, before);
    }

    #[test]
    fn field_and_protected_range_admission_is_local_to_the_section_and_extent() {
        for content in [
            "<hp:ctrl><hp:fieldBegin type='CLICK_HERE' name='ordinary'/></hp:ctrl><hp:t>FIELD</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>",
            "<hp:t><hp:insertBegin Id='2' TcId='3'/>IN<hp:insertEnd Id='2' TcId='3'/></hp:t>",
            "<hp:t><hp:deleteBegin Id='4' TcId='5'/>IN<hp:deleteEnd Id='4' TcId='5'/></hp:t>",
        ] {
            let mut package = body_package(
                &(paragraph(&(begin("1", "A") + content + &end("1")))
                    + &paragraph("<hp:t>OUT</hp:t>")),
            );
            let handle = resolve_bookmark_regions(&package).unwrap().remove(0);
            remove_bookmark_region(&mut package, &handle).unwrap();
            assert_eq!(projection(&package).0, ["OUT"]);
        }
        let ordinary = body_package(&paragraph(
            "<hp:ctrl><hp:fieldBegin name='ordinary'/></hp:ctrl><hp:t>A</hp:t><hp:ctrl><hp:fieldEnd/></hp:ctrl>",
        ));
        assert!(resolve_bookmark_regions(&ordinary).unwrap().is_empty());
        let first = paragraph(&(begin("7", "A") + "<hp:t>A</hp:t>" + &end("7")))
            + &paragraph("<hp:t>OUT</hp:t>");
        let second = paragraph(&(begin("7", "B") + "<hp:t>B</hp:t>" + &end("7")))
            + &paragraph("<hp:t>OUT</hp:t>");
        let package = two_sections(&first, &second);
        assert_eq!(
            resolve_bookmark_regions(&package)
                .unwrap()
                .iter()
                .map(|item| item.name.as_deref().unwrap())
                .collect::<Vec<_>>(),
            ["A", "B"]
        );
        let package = two_sections(
            &first,
            &(paragraph(&end("7")) + &paragraph("<hp:t>OUT</hp:t>")),
        );
        assert_eq!(resolve_bookmark_regions(&package).unwrap().len(), 1);

        let field_begin =
            "<hp:ctrl><hp:fieldBegin id='7' type='CLICK_HERE' name='FIELD'/></hp:ctrl>";
        let first = paragraph(&format!("{field_begin}<hp:t>OUT</hp:t>"))
            + &paragraph(&(begin("1", "TARGET") + "<hp:t>IN</hp:t>"))
            + &paragraph(&("<hp:t>IN2</hp:t>".to_owned() + &end("1")))
            + &paragraph(&("<hp:t>OUT2</hp:t>".to_owned() + &end("7")))
            + &paragraph("<hp:t>TAIL</hp:t>");
        let mut package = two_sections(&first, &second);
        let target = named(&package, "TARGET");
        let before = package.clone();
        assert_error(
            remove_bookmark_region(&mut package, &target),
            "paragraph-crossing",
        );
        assert_eq!(package, before);

        let mut package = body_package(
            &(paragraph(&(begin("1", "A") + "<hp:t>IN</hp:t>" + &end("1")))
                + &paragraph("<hp:ctrl><hp:fieldEnd/></hp:ctrl><hp:t>OUT</hp:t>")),
        );
        assert_error(resolve_bookmark_regions(&package).map(|_| ()), "orphan-end");
        let before = package.clone();
        let target = named(&package, "A");
        assert_error(remove_bookmark_region(&mut package, &target), "orphan-end");
        assert_eq!(package, before);
    }

    #[test]
    fn nested_and_sibling_topology_does_not_exempt_real_boundary_text() {
        let body = paragraph("<hp:t>OUT</hp:t>")
            + &paragraph(&(begin("1", "OUTER") + "<hp:t>A</hp:t>"))
            + &paragraph(&(begin("2", "MID") + "<hp:t>B</hp:t>"))
            + &paragraph(&(begin("3", "INNER") + "<hp:t>C</hp:t>" + &end("3")))
            + &paragraph(&("<hp:t>D</hp:t>".to_owned() + &end("2")))
            + &paragraph(&("<hp:t>E</hp:t>".to_owned() + &end("1")))
            + &paragraph("<hp:t>OUT2</hp:t>");
        let package = body_package(&body);
        assert_eq!(resolve_bookmark_regions(&package).unwrap().len(), 3);
        assert_spans(
            &package,
            &[
                ("OUTER", 1, 5, None),
                ("MID", 2, 4, Some("OUTER")),
                ("INNER", 3, 3, Some("MID")),
            ],
        );
        let partial = body_package(
            &(paragraph(
                &(begin("1", "OUTER")
                    + "<hp:t>prefix</hp:t>"
                    + &begin("2", "INNER")
                    + "<hp:t>A</hp:t>"
                    + &end("2")
                    + &end("1")),
            ) + &paragraph("<hp:t>OUT</hp:t>")),
        );
        assert_eq!(resolve_bookmark_topology(&partial).unwrap().len(), 2);
        assert_error(
            resolve_bookmark_regions(&partial).map(|_| ()),
            "partial-paragraph BOOKMARK begin",
        );
        let mut siblings = body_package(
            &(paragraph(&(begin("1", "A") + "<hp:t>A</hp:t>"))
                + &paragraph(&(begin("2", "A1") + "<hp:t>B</hp:t>" + &end("2")))
                + &paragraph(&("<hp:t>C</hp:t>".to_owned() + &end("1")))
                + &paragraph(&(begin("3", "B") + "<hp:t>D</hp:t>" + &end("3")))
                + &paragraph("<hp:t>OUT</hp:t>")),
        );
        assert_spans(
            &siblings,
            &[
                ("A", 0, 2, None),
                ("A1", 1, 1, Some("A")),
                ("B", 3, 3, None),
            ],
        );
        let handle = named(&siblings, "B");
        remove_bookmark_region(&mut siblings, &handle).unwrap();
        assert_eq!(projection(&siblings).0, ["A", "B", "C", "OUT"]);
    }

    #[test]
    fn content_removal_refuses_neighbour_markers_and_section_definitions_atomically() {
        let mut package = body_package(
            &(paragraph("<hp:t>OUT</hp:t>")
                + &paragraph(&(begin("1", "A") + "<hp:t>A</hp:t>"))
                + &paragraph(&(end("1") + &begin("2", "B")))
                + &paragraph(&("<hp:t>B</hp:t>".to_owned() + &end("2")))
                + &paragraph("<hp:t>OUT2</hp:t>")),
        );
        let handle = named(&package, "A");
        let before = package.clone();
        assert_error(
            remove_bookmark_region(&mut package, &handle),
            "would cut BOOKMARK markers outside it",
        );
        assert_eq!(package, before);
        for nested in [false, true] {
            let mut package = fixture("R0-plain.hwpx");
            let stop = usize::from(nested);
            let outer =
                create_bookmark_region(&mut package, SECTION, 0, stop, "OUTER", None).unwrap();
            let handle = if nested {
                create_bookmark_region(&mut package, SECTION, 0, stop, "INNER", Some(&outer))
                    .unwrap()
            } else {
                outer
            };
            let before = package.clone();
            assert_error(
                remove_bookmark_region(&mut package, &handle),
                "would delete section definition",
            );
            assert_eq!(package, before);
        }
    }

    fn marker_package() -> HwpxPackage {
        two_sections(
            &(paragraph("<hp:t>A</hp:t>")
                + &paragraph(&(begin("1", "OUTER") + "<hp:t>B</hp:t>"))
                + &paragraph(&(begin("2", "INNER") + "<hp:t>C</hp:t>" + &end("2")))
                + &paragraph("<hp:t>D</hp:t><!--layout hint-->")
                + &paragraph(&("<hp:t>E</hp:t>".to_owned() + &end("1")))
                + &paragraph(&(begin("3", "AFTER") + "<hp:t>F</hp:t>" + &end("3")))),
            &paragraph(&(begin("4", "OTHER") + "<hp:t>G</hp:t>" + &end("4"))),
        )
    }

    #[test]
    fn paragraph_removal_shifts_only_affected_positions_and_preserves_metadata() {
        let mut package = marker_package();
        let other = package_entry(&package, "Contents/section1.xml")
            .unwrap()
            .to_vec();
        let inner = named(&package, "INNER");
        append_bookmark_metatag(&mut package, &inner, "payload").unwrap();
        remove_top_level_paragraph(&mut package, SECTION, 3).unwrap();
        assert_eq!(projection(&package).0, ["A", "B", "C", "E", "F"]);
        assert_spans(
            &package,
            &[
                ("OUTER", 1, 3, None),
                ("INNER", 2, 2, Some("OUTER")),
                ("AFTER", 4, 4, None),
                ("OTHER", 0, 0, None),
            ],
        );
        remove_top_level_paragraph(&mut package, SECTION, 0).unwrap();
        assert_eq!(projection(&package).0, ["B", "C", "E", "F"]);
        assert_spans(
            &package,
            &[
                ("OUTER", 0, 2, None),
                ("INNER", 1, 1, Some("OUTER")),
                ("AFTER", 3, 3, None),
                ("OTHER", 0, 0, None),
            ],
        );
        assert_eq!(named(&package, "INNER").meta_tags, ["payload"]);
        assert_eq!(
            package_entry(&package, "Contents/section1.xml").unwrap(),
            other
        );
    }

    #[test]
    fn paragraph_removal_refuses_boundary_controls_last_paragraph_and_invalid_addresses() {
        for (mut package, section, index, message) in [
            (marker_package(), SECTION, 1, "fieldBegin"),
            (marker_package(), SECTION, 4, "fieldEnd"),
            (
                body_package(&(paragraph("<hp:secPr/>") + &paragraph("<hp:t>B</hp:t>"))),
                SECTION,
                0,
                "secPr",
            ),
            (
                body_package(&paragraph("<hp:t>ONLY</hp:t>")),
                SECTION,
                0,
                "leave none",
            ),
            (marker_package(), SECTION, 6, "invalid paragraph index"),
            (marker_package(), "missing.xml", 0, "section was not found"),
        ] {
            let before = package.clone();
            assert_error(
                remove_top_level_paragraph(&mut package, section, index),
                message,
            );
            assert_eq!(package, before);
        }
    }

    fn boundary_tokens(package: &HwpxPackage, paragraph: usize) -> Vec<String> {
        let doc = parse_xml(package_entry(package, SECTION).unwrap()).unwrap();
        let paragraph = doc
            .elements(doc.root)
            .filter(|id| native(&doc, *id, "p"))
            .nth(paragraph)
            .unwrap();
        direct_runs(&doc, paragraph)
            .into_iter()
            .flat_map(|run| doc.elements(run))
            .filter_map(|id| {
                let node = doc.node(id);
                if native(&doc, id, "t") && node.children.is_empty() {
                    return None;
                }
                if native(&doc, id, "ctrl") {
                    Some(format!(
                        "ctrl:{}",
                        doc.elements(id)
                            .map(|child| format!(
                                "{}:{}",
                                doc.node(child).name.local,
                                doc.attr(child, "type").unwrap_or("")
                            ))
                            .collect::<Vec<_>>()
                            .join(",")
                    ))
                } else {
                    Some(node.name.local.clone())
                }
            })
            .collect()
    }

    #[test]
    fn native_trailing_table_and_empty_field_boundaries_survive_recreation_and_deletion() {
        for (file, start, stop) in [
            ("I/I1-table-only-end.hwpx", 1, 2),
            ("I/I2-space-table-end.hwpx", 20, 36),
            ("I/I3-single-space-table.hwpx", 36, 36),
            ("I/I4-empty-field-end.hwpx", 20, 34),
        ] {
            let mut package = fixture(file);
            assert_spans(&package, &[("S0_END", start, stop, None)]);
            assert_eq!(resolve_bookmark_regions(&package).unwrap().len(), 1);
            let tokens = boundary_tokens(&package, stop);
            assert_eq!(tokens.last().unwrap(), "ctrl:fieldEnd:");
            assert!(matches!(
                tokens[tokens.len() - 2].as_str(),
                "tbl" | "ctrl:fieldEnd:"
            ));
            let mut recreated = package.clone();
            let target = named(&recreated, "S0_END");
            unwrap_bookmark_region(&mut recreated, &target).unwrap();
            create_bookmark_region(&mut recreated, SECTION, start, stop, "S0_END", None).unwrap();
            for index in [start, stop] {
                assert_eq!(
                    boundary_tokens(&recreated, index),
                    boundary_tokens(&package, index),
                    "{file}, paragraph {index}"
                );
            }
            let target = named(&package, "S0_END");
            remove_bookmark_region(&mut package, &target).unwrap();
            assert_paired(&package);
        }
        let expected = [
            ("s", 20, 36, None),
            ("s/o1", 20, 24, Some("s")),
            ("s/o2", 25, 35, Some("s")),
            ("s/o3", 36, 36, Some("s")),
        ];
        let mut package = fixture("I/I5-generated-options.hwpx");
        assert_spans(&package, &expected);
        assert_spans(&fixture("I/I5-resaved.hwpx"), &expected);
        let target = named(&package, "s/o2");
        remove_bookmark_region(&mut package, &target).unwrap();
        let native = fixture("I/I6-delete-option.hwpx");
        assert_eq!(projection(&package), projection(&native));
        assert_eq!(marker_positions(&package), marker_positions(&native));
        assert_eq!(spans(&package), spans(&native));
        assert_spans(
            &package,
            &[
                ("s", 20, 25, None),
                ("s/o1", 20, 24, Some("s")),
                ("s/o3", 25, 25, Some("s")),
            ],
        );
    }

    fn simple() -> HwpxPackage {
        let xml = format!(
            "<hs:sec xmlns:hs='{}' xmlns:hp='{}'><hp:p><hp:run><hp:t>OUT</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>A</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>B</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>C</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>OUT2</hp:t></hp:run></hp:p></hs:sec>",
            crate::structural_boundary::HS_NS,
            HP_NS
        );
        HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".to_owned(),
                data: xml.into_bytes(),
                stored: false,
            }],
        }
    }
    fn fixture(name: &str) -> HwpxPackage {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/structural_range_s0")
            .join(name);
        let bytes = std::fs::read(path).unwrap();
        HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap()
    }
    fn named(package: &HwpxPackage, name: &str) -> BookmarkRegion {
        resolve_bookmark_topology(package)
            .unwrap()
            .into_iter()
            .find(|item| item.name.as_deref() == Some(name))
            .unwrap()
    }
    fn projection(package: &HwpxPackage) -> (Vec<String>, Vec<(String, String)>) {
        let bytes = package_entry(package, "Contents/section0.xml").unwrap();
        let doc = parse_xml(bytes).unwrap();
        let paragraphs = doc
            .elements(doc.root)
            .filter(|id| native(&doc, *id, "p"))
            .map(|id| {
                doc.descendants(id)
                    .into_iter()
                    .filter(|child| native(&doc, *child, "t"))
                    .map(|child| doc.iter_text(child))
                    .collect()
            })
            .collect();
        let markers = doc
            .descendants(doc.root)
            .into_iter()
            .filter_map(|id| {
                if native(&doc, id, "fieldBegin") {
                    Some((
                        "begin".to_owned(),
                        doc.attr(id, "id").unwrap_or("").to_owned(),
                    ))
                } else if native(&doc, id, "fieldEnd") {
                    Some((
                        "end".to_owned(),
                        doc.attr(id, "beginIDRef").unwrap_or("").to_owned(),
                    ))
                } else {
                    None
                }
            })
            .collect();
        (paragraphs, markers)
    }

    #[test]
    fn malformed_bookmark_topology_and_unsafe_extents_fail_closed() {
        #[derive(serde::Deserialize)]
        struct Case {
            message: String,
            sections: BTreeMap<String, String>,
        }
        let cases: Vec<Case> = serde_json::from_str(include_str!(
            "../../../tests/fixtures/bookmark_region_refusals.json"
        ))
        .unwrap();
        let mut mismatches = Vec::new();
        for (index, case) in cases.into_iter().enumerate() {
            let sections = case
                .sections
                .iter()
                .map(|(name, xml)| (name.as_str(), xml.as_str()))
                .collect::<Vec<_>>();
            let package = package_with_sections(&sections);
            let original = package.clone();
            let result = resolve_bookmark_regions(&package);
            match result {
                Err(error) if error.to_string().contains(&case.message) => {}
                other => mismatches.push(format!(
                    "case {index}: expected {}: {other:?}",
                    case.message
                )),
            }
            assert_eq!(package, original);
            if let Ok(regions) = resolve_bookmark_topology(&package) {
                for region in regions {
                    let mut copy = package.clone();
                    assert!(
                        remove_bookmark_region(&mut copy, &region).is_err(),
                        "unsafe removal case {index}"
                    );
                    assert_eq!(copy, package);
                }
            }
        }
        assert!(mismatches.is_empty(), "{}", mismatches.join("\n"));
    }

    #[test]
    fn creation_keeps_native_content_and_rejects_stale_crossing_or_reparenting_requests() {
        let mut package = fixture("R0-plain.hwpx");
        let original = projection(&package).0;
        let created =
            create_bookmark_region(&mut package, SECTION, 1, 3, "S0_GENERATED", None).unwrap();
        assert_eq!(projection(&package).0, original);
        assert_eq!(
            resolve_bookmark_regions(&reparsed(&package)).unwrap(),
            std::slice::from_ref(&created)
        );
        let expected = fixture("D6-generated-minimal.hwpx");
        let actual_doc = parse_xml(package_entry(&package, SECTION).unwrap()).unwrap();
        let expected_doc = parse_xml(package_entry(&expected, SECTION).unwrap()).unwrap();
        assert_eq!(
            paragraph_shape(&actual_doc, actual_doc.root),
            paragraph_shape(&expected_doc, expected_doc.root)
        );
        let mut repeated = fixture("R0-plain.hwpx");
        create_bookmark_region(&mut repeated, SECTION, 1, 3, "S0_GENERATED", None).unwrap();
        assert_eq!(package.to_bytes().unwrap(), repeated.to_bytes().unwrap());
        create_bookmark_region(&mut package, SECTION, 4, 4, "SECOND", None).unwrap();
        assert_eq!(
            projection(&package)
                .1
                .into_iter()
                .filter(|(kind, _)| kind == "begin")
                .map(|(_, id)| id)
                .collect::<Vec<_>>(),
            ["1600000001", "1600000002"]
        );

        let mut package = fixture("R0-plain.hwpx");
        let outer = create_bookmark_region(&mut package, SECTION, 1, 3, "OUTER", None).unwrap();
        let before = package.clone();
        assert_error(
            create_bookmark_region(&mut package, SECTION, 2, 4, "CROSSING", None).map(|_| ()),
            "crossing BOOKMARK",
        );
        assert_eq!(package, before);
        append_bookmark_metatag(&mut package, &outer, "changed").unwrap();
        let before = package.clone();
        assert_error(
            create_bookmark_region(&mut package, SECTION, 2, 2, "STALE", Some(&outer)).map(|_| ()),
            "current package snapshot",
        );
        assert_eq!(package, before);
        let fresh = named(&package, "OUTER");
        for (section, start, stop, name, parent) in [
            (SECTION, 3, 2, "X", None),
            (SECTION, 0, 99, "X", None),
            (SECTION, 1, 1, " ", None),
            ("missing.xml", 0, 0, "X", None),
            ("Contents/section1.xml", 1, 1, "X", Some(&fresh)),
            (SECTION, 0, 0, "X", Some(&fresh)),
        ] {
            assert!(
                create_bookmark_region(&mut package, section, start, stop, name, parent).is_err()
            );
            assert_eq!(package, before);
        }
        let mut no_run = body_package(
            "<hp:p><hp:t>OUT</hp:t></hp:p><hp:p><hp:run><hp:t>TAIL</hp:t></hp:run></hp:p>",
        );
        let before = no_run.clone();
        assert_error(
            create_bookmark_region(&mut no_run, SECTION, 0, 0, "X", None).map(|_| ()),
            "direct native hp:run",
        );
        assert_eq!(no_run, before);
        let mut package = fixture("R0-plain.hwpx");
        create_bookmark_region(&mut package, SECTION, 1, 1, "EXISTING", None).unwrap();
        let before = package.clone();
        assert_error(
            create_bookmark_region(&mut package, SECTION, 1, 3, "NEW_TOP", None).map(|_| ()),
            "changed existing native topology",
        );
        assert_eq!(package, before);
    }

    #[test]
    fn nested_creation_allows_shared_boundaries_without_changing_text_or_parentage() {
        for (start, stop) in [(2, 2), (1, 1), (3, 3), (1, 3)] {
            let mut package = fixture("R0-plain.hwpx");
            let before = projection(&package).0;
            let outer = create_bookmark_region(&mut package, SECTION, 1, 3, "OUTER", None).unwrap();
            let inner =
                create_bookmark_region(&mut package, SECTION, start, stop, "INNER", Some(&outer))
                    .unwrap();
            let regions = resolve_bookmark_regions(&package).unwrap();
            assert_eq!(regions[1], inner);
            assert_eq!(regions[1].parent.as_deref(), Some(&regions[0]));
            assert_eq!(
                spans(&package),
                [
                    ("OUTER".into(), 1, 3, None),
                    ("INNER".into(), start, stop, Some("OUTER".into()))
                ]
            );
            assert_eq!(projection(&package).0, before);
            assert_eq!(
                resolve_bookmark_regions(&reparsed(&package)).unwrap(),
                regions
            );
        }
    }

    #[test]
    fn opaque_metatags_preserve_order_legacy_attribute_and_reject_stale_edits() {
        let content = format!(
            "<hp:ctrl><hp:fieldBegin id='1' type='BOOKMARK' name='A' metaTag='legacy'><hp:parameters/><hp:metaTag>{{\"future\": [1, 2]}}</hp:metaTag><hp:metaTag>not-json</hp:metaTag></hp:fieldBegin></hp:ctrl><hp:t>A</hp:t>{}",
            end("1")
        );
        let mut package = body_package(&(paragraph(&content) + &paragraph("<hp:t>OUT</hp:t>")));
        let handle = named(&package, "A");
        assert_eq!(handle.meta_tags, ["{\"future\": [1, 2]}", "not-json"]);
        assert_eq!(handle.meta_tag_attribute.as_deref(), Some("legacy"));
        let payload = "{\"한글\": \"그대로\"}";
        append_bookmark_metatag(&mut package, &handle, payload).unwrap();
        let before = package.clone();
        assert_error(
            append_bookmark_metatag(&mut package, &handle, "stale"),
            "current package snapshot",
        );
        assert_eq!(package, before);
        let mut package = reparsed(&package);
        let handle = named(&package, "A");
        assert_eq!(
            handle.meta_tags,
            ["{\"future\": [1, 2]}", "not-json", payload]
        );
        replace_bookmark_metatag(&mut package, &handle, 1, "replacement").unwrap();
        assert_error(
            remove_bookmark_metatag(&mut package, &handle, 0),
            "current package snapshot",
        );
        let handle = named(&package, "A");
        remove_bookmark_metatag(&mut package, &handle, 0).unwrap();
        let handle = named(&package, "A");
        assert_eq!(handle.meta_tags, ["replacement", payload]);
        assert_eq!(handle.meta_tag_attribute.as_deref(), Some("legacy"));
        assert_eq!(
            resolve_bookmark_regions(&reparsed(&package)).unwrap(),
            std::slice::from_ref(&handle)
        );
        let before = package.clone();
        assert_error(
            replace_bookmark_metatag(&mut package, &handle, 9, "missing"),
            "out of range",
        );
        assert_error(
            remove_bookmark_metatag(&mut package, &handle, 9),
            "out of range",
        );
        assert_eq!(package, before);
    }
    fn paragraph_shape(doc: &XmlDocument, id: NodeId) -> String {
        let node = doc.node(id);
        if native(doc, id, "linesegarray") {
            return String::new();
        }
        let mut value = format!(
            "<{} {:?}>",
            node.name.clark(),
            node.attributes
                .iter()
                .map(|item| (item.name.clark(), &item.value))
                .collect::<Vec<_>>()
        );
        for part in &node.children {
            match part {
                Content::Element(child) => value.push_str(&paragraph_shape(doc, *child)),
                Content::Text(text) | Content::CData(text) => value.push_str(&format!("{text:?}")),
                Content::Comment(text) => value.push_str(&format!("<!--{text}-->")),
                Content::ProcessingInstruction(text) => value.push_str(&format!("<?{text}?>")),
            }
        }
        value.push_str("</>");
        value
    }

    #[test]
    fn hancom_nested_bookmark_remove_and_unwrap() {
        let original = fixture("R5-nested.hwpx");
        let regions = resolve_bookmark_regions(&original).unwrap();
        assert_eq!(
            regions
                .iter()
                .map(|item| (
                    item.name.as_deref(),
                    item.start_paragraph,
                    item.end_paragraph
                ))
                .collect::<Vec<_>>(),
            vec![
                (Some("S0_SLOT"), 1, 4),
                (Some("S0_OPT_A"), 2, 2),
                (Some("S0_OPT_B"), 3, 3)
            ]
        );
        for (name, expected, unwrap) in [
            ("S0_OPT_A", "F/F1-delete-inner-paragraph.hwpx", false),
            ("S0_SLOT", "F/F2-delete-outer-range.hwpx", false),
            ("S0_OPT_A", "F/F5-remove-inner-bookmark.hwpx", true),
            ("S0_SLOT", "F/F6-remove-outer-bookmark.hwpx", true),
        ] {
            let mut package = original.clone();
            let handle = named(&package, name);
            if unwrap {
                unwrap_bookmark_region(&mut package, &handle).unwrap();
            } else {
                remove_bookmark_region(&mut package, &handle).unwrap();
            }
            let native = fixture(expected);
            assert_eq!(
                projection(&package),
                projection(&native),
                "{name} {expected}"
            );
            assert_eq!(spans(&package), spans(&native), "{name} {expected}");
            assert_eq!(marker_positions(&package), marker_positions(&native));
            if unwrap {
                // Hancom drops empty text elements when unwrapping; they carry no content.
                let empty_text = format!("<{{{HP_NS}}}t []></>");
                assert_eq!(
                    section_shape(&package).replace(&empty_text, ""),
                    section_shape(&native).replace(&empty_text, ""),
                    "{name} {expected}"
                );
            } else {
                assert_clean(&package);
            }
            assert_eq!(section_shape(&reparsed(&package)), section_shape(&package));
        }
        for file in [
            "F/F1-delete-inner-paragraph.hwpx",
            "F/F2-delete-outer-range.hwpx",
            "F/F3-delete-outer-start.hwpx",
            "F/F4-delete-outer-end.hwpx",
            "F/F5-remove-inner-bookmark.hwpx",
            "F/F6-remove-outer-bookmark.hwpx",
        ] {
            let package = fixture(file);
            assert_paired(&package);
            if file.contains("F3-") || file.contains("F4-") || file.contains("F6-") {
                let regions = resolve_bookmark_regions(&package).unwrap();
                assert_eq!(
                    regions
                        .iter()
                        .map(|item| item.name.as_deref())
                        .collect::<Vec<_>>(),
                    [Some("S0_OPT_A"), Some("S0_OPT_B")]
                );
                assert!(regions.iter().all(|item| item.parent.is_none()));
            }
        }
    }

    #[test]
    fn region_removal_preserves_unrelated_assets_paragraphs_and_serialization() {
        for (filename, bookmark) in [
            ("R2-block-bookmark.hwpx", "S0_BLOCK"),
            ("R3-table-crossing.hwpx", "S0_TABLE"),
        ] {
            let mut package = fixture(filename);
            let before = package.clone();
            let before_doc =
                parse_xml(package_entry(&package, "Contents/section0.xml").unwrap()).unwrap();
            let outside: Vec<_> = before_doc
                .elements(before_doc.root)
                .filter(|id| native(&before_doc, *id, "p"))
                .filter(|id| matches!(before_doc.iter_text(*id).as_str(), "AAA" | "EEE"))
                .map(|id| paragraph_shape(&before_doc, id))
                .collect();
            let target = named(&package, bookmark);
            remove_bookmark_region(&mut package, &target).unwrap();
            assert_eq!(projection(&package).0, vec!["AAA", "EEE"]);
            let after_doc =
                parse_xml(package_entry(&package, "Contents/section0.xml").unwrap()).unwrap();
            let retained: Vec<_> = after_doc
                .elements(after_doc.root)
                .map(|id| paragraph_shape(&after_doc, id))
                .collect();
            assert_eq!(retained, outside);
            assert!(
                !after_doc
                    .descendants(after_doc.root)
                    .iter()
                    .any(|id| native(&after_doc, *id, "tbl"))
            );
            for (old, new) in before.entries.iter().zip(&package.entries) {
                if old.name != "Contents/section0.xml" {
                    assert_eq!(old, new);
                }
            }
            assert!(projection(&package).1.is_empty());
            assert!(
                resolve_bookmark_regions(&reparsed(&package))
                    .unwrap()
                    .is_empty()
            );
            let mut repeated = fixture(filename);
            let target = named(&repeated, bookmark);
            remove_bookmark_region(&mut repeated, &target).unwrap();
            assert_eq!(package.to_bytes().unwrap(), repeated.to_bytes().unwrap());
            assert_clean(&package);
        }
    }

    #[test]
    fn root_comment_blocks_extent_and_deleted_paragraph_takes_its_tail() {
        let mut package = simple();
        let handle =
            create_bookmark_region(&mut package, "Contents/section0.xml", 1, 3, "B", None).unwrap();
        let entry = package
            .entries
            .iter_mut()
            .find(|item| item.name == "Contents/section0.xml")
            .unwrap();
        let xml = String::from_utf8(entry.data.clone()).unwrap();
        entry.data = xml
            .replacen("</hp:p><hp:p>", "</hp:p><!--outside--><hp:p>", 2)
            .into_bytes();
        let current = named(&package, "B");
        let before = package.clone();
        assert!(remove_bookmark_region(&mut package, &current).is_err());
        assert_eq!(package, before);
        assert!(remove_bookmark_region(&mut package, &handle).is_err());

        let mut package = simple();
        let entry = &mut package.entries[0];
        let xml = String::from_utf8(entry.data.clone()).unwrap();
        entry.data = xml
            .replacen("</hp:p><hp:p>", "</hp:p>TAIL<hp:p>", 1)
            .into_bytes();
        remove_top_level_paragraph(&mut package, "Contents/section0.xml", 0).unwrap();
        assert!(!String::from_utf8_lossy(&package.entries[0].data).contains("TAIL"));
    }
}
