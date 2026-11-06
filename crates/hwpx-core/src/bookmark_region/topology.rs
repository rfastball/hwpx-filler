//! Native BOOKMARK topology and snapshot validation.

use super::*;

fn object_metatags(
    doc: &XmlDocument,
    begin: NodeId,
    entry: &str,
) -> Result<Vec<String>, NativeAdmissionError> {
    let mut values = Vec::new();
    for child in doc.elements(begin) {
        if doc.node(child).name.local != "metaTag" {
            continue;
        }
        if !native(doc, child, "metaTag") {
            return Err(error(format!(
                "{entry}: object-local metaTag uses a non-native namespace"
            )));
        }
        if doc.node(child).children.iter().any(|part| {
            matches!(
                part,
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
            )
        }) {
            return Err(error(format!(
                "{entry}: object-local hp:metaTag must contain text only"
            )));
        }
        values.push(doc.direct_text(child));
    }
    Ok(values)
}
pub(super) fn parse_sections_with_override(
    package: &HwpxPackage,
    replacement: Option<(&str, &[u8])>,
) -> Result<Vec<Section>, NativeAdmissionError> {
    let mut sections = Vec::new();
    for name in section_xml_names(package) {
        let source = if let Some((_, data)) = replacement.filter(|(entry, _)| *entry == name) {
            data
        } else {
            package_entry(package, name)?
        };
        sections.push(parse_section(name, source)?);
    }
    Ok(sections)
}

fn parse_section(name: &str, source: &[u8]) -> Result<Section, NativeAdmissionError> {
    let doc = parse_xml(source)?;
    if !doc
        .node(doc.root)
        .name
        .is(crate::structural_boundary::HS_NS, "sec")
    {
        return Err(error(format!("{name}: section root is not native hs:sec")));
    }
    let nodes = doc.descendants(doc.root);
    let order = nodes.iter().enumerate().map(|(at, id)| (*id, at)).collect();
    let paragraphs = doc
        .elements(doc.root)
        .filter(|id| native(&doc, *id, "p"))
        .collect();
    let mut section = Section {
        entry: name.to_owned(),
        doc,
        nodes,
        order,
        paragraphs,
        begins: HashMap::new(),
        ends: HashMap::new(),
        bookmark_begins: Vec::new(),
        snapshot: digest(source),
    };
    for id in section.nodes.clone() {
        index_marker(&mut section, id)?;
    }
    Ok(section)
}

fn index_marker(section: &mut Section, id: NodeId) -> Result<(), NativeAdmissionError> {
    let doc = &section.doc;
    let name = &section.entry;
    let local = doc.node(id).name.local.as_str();
    if local == "fieldBegin"
        && doc.attr(id, "type") == Some("BOOKMARK")
        && !native(doc, id, "fieldBegin")
    {
        return Err(error(format!(
            "{name}: BOOKMARK fieldBegin uses a non-native namespace"
        )));
    }
    if native(doc, id, "fieldBegin") {
        if doc.attr(id, "type") == Some("BOOKMARK") {
            section.bookmark_begins.push(id);
            if doc.attr(id, "id").is_none_or(str::is_empty) {
                return Err(error(format!("{name}: BOOKMARK fieldBegin has no id")));
            }
        }
        if let Some(pair_id) = doc.attr(id, "id").filter(|s| !s.is_empty()) {
            section
                .begins
                .entry(pair_id.to_owned())
                .or_default()
                .push(id);
        }
    } else if native(doc, id, "fieldEnd")
        && let Some(reference) = doc.attr(id, "beginIDRef").filter(|s| !s.is_empty())
    {
        section
            .ends
            .entry(reference.to_owned())
            .or_default()
            .push(id);
    }
    Ok(())
}

pub(super) fn resolve_with_override(
    package: &HwpxPackage,
    replacement: Option<(&str, &[u8])>,
    require_removable: bool,
) -> Result<(Vec<Section>, Vec<ResolvedRegion>), NativeAdmissionError> {
    let sections = parse_sections_with_override(package, replacement)?;
    let mut all = Vec::new();
    for (section_index, section) in sections.iter().enumerate() {
        let mut regions = section
            .bookmark_begins
            .iter()
            .map(|begin| resolve_pair(section, section_index, *begin))
            .collect::<Result<Vec<_>, _>>()?;
        assign_parents(&mut regions, &section.entry)?;
        if require_removable {
            validate_removals(section, &regions)?;
        }
        all.extend(regions);
    }
    Ok((sections, all))
}

fn resolve_pair(
    section: &Section,
    section_index: usize,
    begin: NodeId,
) -> Result<ResolvedRegion, NativeAdmissionError> {
    let doc = &section.doc;
    let begin = &begin;
    let pair_id = doc.attr(*begin, "id").expect("validated bookmark id");
    let begins = &section.begins[pair_id];
    if begins.len() != 1 {
        return Err(error(format!(
            "{}: duplicate fieldBegin id {pair_id:?}",
            section.entry
        )));
    }
    let ends = section.ends.get(pair_id).map(Vec::as_slice).unwrap_or(&[]);
    if ends.is_empty() {
        return Err(error(format!(
            "{}: BOOKMARK begin id {pair_id:?} has no fieldEnd",
            section.entry
        )));
    }
    let [end] = ends else {
        return Err(error(format!(
            "{}: ambiguous BOOKMARK fieldEnd reference {pair_id:?}",
            section.entry
        )));
    };
    let begin_order = section.order[begin];
    let end_order = section.order[end];
    if end_order <= begin_order {
        return Err(error(format!(
            "{}: BOOKMARK end precedes begin",
            section.entry
        )));
    }
    let start = boundary_paragraph(doc, *begin).ok_or_else(|| {
        error(format!(
            "{}: BOOKMARK boundary is not native ctrl/run/top-level-p content",
            section.entry
        ))
    })?;
    let stop = boundary_paragraph(doc, *end).ok_or_else(|| {
        error(format!(
            "{}: BOOKMARK boundary is not native ctrl/run/top-level-p content",
            section.entry
        ))
    })?;
    let start_child = top_level_index(doc, start).unwrap();
    let end_child = top_level_index(doc, stop).unwrap();
    let start_paragraph = section
        .paragraphs
        .iter()
        .position(|id| *id == start)
        .unwrap();
    let end_paragraph = section
        .paragraphs
        .iter()
        .position(|id| *id == stop)
        .unwrap();
    Ok(ResolvedRegion {
        region: BookmarkRegion {
            name: doc.attr(*begin, "name").map(str::to_owned),
            section: section.entry.clone(),
            start_paragraph,
            end_paragraph,
            parent: None,
            meta_tags: object_metatags(doc, *begin, &section.entry)?,
            meta_tag_attribute: doc.attr(*begin, "metaTag").map(str::to_owned),
            pairing_id: pair_id.to_owned(),
            section_sha256: section.snapshot,
        },
        section_index,
        begin: *begin,
        end: *end,
        start_child,
        end_child,
        begin_order,
        end_order,
    })
}

fn assign_parents(regions: &mut [ResolvedRegion], entry: &str) -> Result<(), NativeAdmissionError> {
    regions.sort_by_key(|item| item.begin_order);
    let mut opened: Vec<usize> = Vec::new();
    for at in 0..regions.len() {
        while opened
            .last()
            .is_some_and(|last| regions[*last].end_order < regions[at].begin_order)
        {
            opened.pop();
        }
        if let Some(parent) = opened.last().copied() {
            if regions[at].end_order > regions[parent].end_order {
                return Err(error(format!(
                    "{entry}: crossing BOOKMARK regions are unsupported"
                )));
            }
            regions[at].region.parent = Some(Box::new(regions[parent].region.clone()));
        }
        opened.push(at);
    }
    Ok(())
}

fn validate_removals(
    section: &Section,
    regions: &[ResolvedRegion],
) -> Result<(), NativeAdmissionError> {
    let doc = &section.doc;
    let fields = resolve_field_occurrences(&section.entry, doc);
    let detail = native_detail(section, regions, &fields.occurrences);
    let index = build_native_admission_index(&detail);
    for item in regions {
        let pair = BookmarkPair {
            begin: item.begin,
            end: item.end,
            name: item.region.name.clone(),
            meta_tags: item.region.meta_tags.clone(),
            meta_tag_attribute: item.region.meta_tag_attribute.clone(),
        };
        let plan = plan_bookmark_removal(
            &detail,
            &index,
            &pair,
            BookmarkPlanPolicy {
                topology_usable: true,
                metadata_usable: true,
                field_pairing_usable: fields.diagnostics.is_empty(),
                reject_whole_section: true,
                reject_section_definition: true,
            },
        );
        check_removal_plan(&plan, &fields.diagnostics)?;
    }
    Ok(())
}

pub(super) fn resolve(
    package: &HwpxPackage,
    require_removable: bool,
) -> Result<(Vec<Section>, Vec<ResolvedRegion>), NativeAdmissionError> {
    resolve_with_override(package, None, require_removable)
}

pub(super) fn native_detail(
    section: &Section,
    regions: &[ResolvedRegion],
    fields: &[crate::field_occurrence::FieldOccurrence],
) -> NativeEntryDetail {
    NativeEntryDetail {
        entry: section.entry.clone(),
        kind: ContentEntryKind::Section,
        source_sha256: section.snapshot,
        doc: section.doc.clone(),
        nodes: section.nodes.clone(),
        order: section.order.clone(),
        fields: fields
            .iter()
            .cloned()
            .map(|item| {
                (
                    crate::structural_boundary::BoundaryPairRef::internal_new(),
                    item,
                )
            })
            .collect(),
        bookmarks: regions
            .iter()
            .map(|item| {
                (
                    crate::structural_boundary::BoundaryPairRef::internal_new(),
                    BookmarkPair {
                        begin: item.begin,
                        end: item.end,
                        name: item.region.name.clone(),
                        meta_tags: item.region.meta_tags.clone(),
                        meta_tag_attribute: item.region.meta_tag_attribute.clone(),
                    },
                )
            })
            .collect(),
    }
}

pub fn resolve_bookmark_topology(
    package: &HwpxPackage,
) -> Result<Vec<BookmarkRegion>, NativeAdmissionError> {
    Ok(resolve(package, false)?
        .1
        .into_iter()
        .map(|item| item.region)
        .collect())
}
pub fn resolve_bookmark_regions(
    package: &HwpxPackage,
) -> Result<Vec<BookmarkRegion>, NativeAdmissionError> {
    Ok(resolve(package, true)?
        .1
        .into_iter()
        .map(|item| item.region)
        .collect())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Shape {
    pub(super) name: Option<String>,
    pub(super) parent: Option<(String, String)>,
    pub(super) meta_tags: Vec<String>,
    meta_tag_attribute: Option<String>,
    pub(super) positions: Option<(usize, usize)>,
}
pub(super) fn shape(
    items: &[ResolvedRegion],
    positions: bool,
) -> BTreeMap<(String, String), Shape> {
    items
        .iter()
        .map(|item| {
            let region = &item.region;
            (
                (region.section.clone(), region.pairing_id.clone()),
                Shape {
                    name: region.name.clone(),
                    parent: region
                        .parent
                        .as_ref()
                        .map(|parent| (parent.section.clone(), parent.pairing_id.clone())),
                    meta_tags: region.meta_tags.clone(),
                    meta_tag_attribute: region.meta_tag_attribute.clone(),
                    positions: positions.then_some((region.start_paragraph, region.end_paragraph)),
                },
            )
        })
        .collect()
}
pub(super) fn fresh(
    package: &HwpxPackage,
    handle: &BookmarkRegion,
) -> Result<(Vec<Section>, Vec<ResolvedRegion>, usize), NativeAdmissionError> {
    let (sections, regions) = resolve(package, false)?;
    let mut matching = regions
        .iter()
        .enumerate()
        .filter(|(_, item)| item.region == *handle)
        .map(|(at, _)| at);
    let at = matching.next().ok_or_else(|| {
        error("BOOKMARK region is not present in the current package snapshot; resolve again")
    })?;
    if matching.next().is_some() {
        return Err(error("ambiguous BOOKMARK handle"));
    }
    Ok((sections, regions, at))
}
pub(super) fn candidate(
    package: &HwpxPackage,
    entry: &str,
    mut doc: XmlDocument,
) -> Result<(Vec<u8>, Vec<ResolvedRegion>), NativeAdmissionError> {
    let data = serialize_modified_section(&mut doc)?;
    let (_, regions) = resolve_with_override(package, Some((entry, &data)), false)?;
    Ok((data, regions))
}
