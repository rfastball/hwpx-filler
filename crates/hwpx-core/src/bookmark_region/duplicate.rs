//! Closed BOOKMARK block duplication and identity rebasing.

use super::*;
use crate::authoring_edit::add_one;
use crate::text_extract::decimal_digit;

pub struct BookmarkCloneNames<'a> {
    pub name: &'a str,
    pub metatag: Option<(usize, &'a str)>,
    pub child_prefix: Option<(&'a str, &'a str)>,
}

fn next_clone_id(package: &HwpxPackage) -> Result<String, NativeAdmissionError> {
    let mut maximum = "0".to_owned();
    for entry in &package.entries {
        if !entry.name.to_lowercase().ends_with(".xml") {
            continue;
        }
        let doc = parse_xml(&entry.data)?;
        for id in doc.descendants(doc.root) {
            for key in ["id", "fieldid"] {
                let Some(value) = doc.attr(id, key) else {
                    continue;
                };
                if value.is_empty() || !value.chars().all(|ch| decimal_digit(ch).is_some()) {
                    continue;
                }
                let digits: String = value
                    .chars()
                    .map(|ch| char::from(b'0' + decimal_digit(ch).unwrap() as u8))
                    .collect();
                let normalized = digits.trim_start_matches('0');
                let normalized = if normalized.is_empty() {
                    "0"
                } else {
                    normalized
                };
                if (normalized.len(), normalized) > (maximum.len(), maximum.as_str()) {
                    maximum = normalized.to_owned();
                }
            }
        }
    }
    add_one(&mut maximum);
    Ok(maximum)
}

fn cloneable_control(doc: &XmlDocument, item: NodeId) -> Result<(), NativeAdmissionError> {
    if native(doc, item, "t")
        && doc
            .node(item)
            .children
            .iter()
            .all(|child| matches!(child, Content::Text(_) | Content::CData(_)))
    {
        return Ok(());
    }
    if !native(doc, item, "ctrl") {
        return Err(error("이 영역에 복제할 수 없는 제어 요소가 있습니다."));
    }
    let children: Vec<_> = doc.elements(item).collect();
    if children.len() != 1
        || doc.node(item).children.iter().any(|child| {
            matches!(
                child,
                Content::Comment(_) | Content::ProcessingInstruction(_)
            )
        })
    {
        return Err(error("이 영역에 복제할 수 없는 제어 요소가 있습니다."));
    }
    let marker = children[0];
    if !native(doc, marker, "fieldBegin") && !native(doc, marker, "fieldEnd") {
        return Err(error("이 영역에 복제할 수 없는 제어 요소가 있습니다."));
    }
    if native(doc, marker, "fieldBegin")
        && doc
            .elements(marker)
            .any(|child| !native(doc, child, "metaTag"))
    {
        return Err(error("알 수 없는 필드 메타데이터는 복제할 수 없습니다."));
    }
    Ok(())
}

fn cloneable_run(doc: &XmlDocument, run: NodeId) -> Result<(), NativeAdmissionError> {
    for child in &doc.node(run).children {
        let Content::Element(item) = child else {
            if matches!(
                child,
                Content::Comment(_) | Content::ProcessingInstruction(_)
            ) {
                return Err(error("이 영역에 복제할 수 없는 제어 요소가 있습니다."));
            }
            continue;
        };
        cloneable_control(doc, *item)?;
    }
    Ok(())
}

fn cloneable(doc: &XmlDocument, block: &[NodeId]) -> Result<(), NativeAdmissionError> {
    for paragraph in block {
        for part in &doc.node(*paragraph).children {
            let Content::Element(run) = part else {
                if matches!(
                    part,
                    Content::Comment(_) | Content::ProcessingInstruction(_)
                ) {
                    return Err(error("이 영역에 복제할 수 없는 문서 요소가 있습니다."));
                }
                continue;
            };
            if native(doc, *run, "lineSegArray") {
                continue;
            }
            if !native(doc, *run, "run") {
                return Err(error("이 영역에 복제할 수 없는 문서 요소가 있습니다."));
            }
            cloneable_run(doc, *run)?;
        }
    }
    Ok(())
}

fn internal_pairs(doc: &XmlDocument, block: &[NodeId]) -> HashSet<String> {
    let mut begins = HashSet::new();
    let mut ends = HashSet::new();
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            if native(doc, id, "fieldBegin") {
                if let Some(value) = doc.attr(id, "id") {
                    begins.insert(value.to_owned());
                }
            } else if native(doc, id, "fieldEnd")
                && let Some(value) = doc.attr(id, "beginIDRef")
            {
                ends.insert(value.to_owned());
            }
        }
    }
    begins.intersection(&ends).cloned().collect()
}

fn validate_crossing_field(
    doc: &XmlDocument,
    id: NodeId,
    internal: &HashSet<String>,
    current: &[ResolvedRegion],
) -> Result<(), NativeAdmissionError> {
    let crossing = if native(doc, id, "fieldBegin") {
        !internal.contains(doc.attr(id, "id").unwrap_or(""))
            && doc.attr(id, "type") != Some("BOOKMARK")
    } else if native(doc, id, "fieldEnd") {
        let key = doc.attr(id, "beginIDRef").unwrap_or("");
        !internal.contains(key) && !current.iter().any(|item| item.region.pairing_id == key)
    } else {
        false
    };
    if crossing {
        return Err(error("문단을 가로지르는 필드는 복제할 수 없습니다."));
    }
    Ok(())
}

fn closed_pairs(
    doc: &XmlDocument,
    block: &[NodeId],
    target: &str,
    current: &[ResolvedRegion],
) -> Result<HashSet<String>, NativeAdmissionError> {
    cloneable(doc, block)?;
    let internal = internal_pairs(doc, block);
    if !internal.contains(target) {
        return Err(error("영역 경계를 문단 단위로 복제할 수 없습니다."));
    }
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            validate_crossing_field(doc, id, &internal, current)?;
        }
    }
    Ok(internal)
}

fn paragraph_tail(doc: &XmlDocument, id: NodeId) -> Result<Vec<Content>, NativeAdmissionError> {
    let index = content_index(doc, doc.root, id)? + 1;
    Ok(doc.node(doc.root).children[index..]
        .iter()
        .take_while(|part| matches!(part, Content::Text(_) | Content::CData(_)))
        .cloned()
        .collect())
}

fn remove_external_markers(
    doc: &mut XmlDocument,
    clones: &[NodeId],
    internal: &HashSet<String>,
) -> Result<(), NativeAdmissionError> {
    for paragraph in clones {
        let controls: Vec<_> = doc
            .descendants(*paragraph)
            .into_iter()
            .filter(|id| {
                (native(doc, *id, "fieldBegin")
                    && !internal.contains(doc.attr(*id, "id").unwrap_or("")))
                    || (native(doc, *id, "fieldEnd")
                        && !internal.contains(doc.attr(*id, "beginIDRef").unwrap_or("")))
            })
            .collect();
        for marker in controls {
            let ctrl = doc
                .parent(marker)
                .ok_or_else(|| error("detached cloned control"))?;
            doc.remove_element_with_tail(ctrl)?;
        }
    }
    Ok(())
}

fn allocate_clone_ids(
    package: &HwpxPackage,
    doc: &XmlDocument,
    clones: &[NodeId],
) -> Result<HashMap<String, String>, NativeAdmissionError> {
    let mut next = next_clone_id(package)?;
    let mut id_map = HashMap::new();
    for paragraph in clones {
        for id in doc.descendants(*paragraph) {
            for key in ["id", "fieldid"] {
                if let Some(value) = doc.attr(id, key)
                    && !id_map.contains_key(value)
                {
                    id_map.insert(value.to_owned(), next.clone());
                    add_one(&mut next);
                }
            }
        }
    }
    Ok(id_map)
}

fn rename_clone(
    doc: &mut XmlDocument,
    id: NodeId,
    is_target: bool,
    names: &BookmarkCloneNames<'_>,
) -> Result<(), NativeAdmissionError> {
    if !native(doc, id, "fieldBegin") || doc.attr(id, "type") != Some("BOOKMARK") {
        return Ok(());
    }
    if is_target {
        set_plain_attribute(doc, id, "name", names.name);
        if let Some((index, payload)) = names.metatag {
            let tag = doc
                .elements(id)
                .filter(|child| native(doc, *child, "metaTag"))
                .nth(index)
                .ok_or_else(|| error("BOOKMARK MetaTag index out of range"))?;
            doc.node_mut(tag).children = vec![Content::Text(payload.to_owned())];
        }
    } else if let Some((old, new)) = names.child_prefix
        && let Some(name) = doc.attr(id, "name").and_then(|name| name.strip_prefix(old))
    {
        let renamed = format!("{new}{name}");
        set_plain_attribute(doc, id, "name", &renamed);
    }
    Ok(())
}

fn rebase_clones(
    doc: &mut XmlDocument,
    clones: &[NodeId],
    id_map: &HashMap<String, String>,
    target: &str,
    names: &BookmarkCloneNames<'_>,
) -> Result<(), NativeAdmissionError> {
    for paragraph in clones {
        for id in doc.descendants(*paragraph) {
            let original_id = doc.attr(id, "id").map(str::to_owned);
            for key in ["id", "fieldid", "beginIDRef", "endIDRef"] {
                if let Some(value) = doc
                    .attr(id, key)
                    .and_then(|value| id_map.get(value))
                    .cloned()
                {
                    set_plain_attribute(doc, id, key, &value);
                }
            }
            rename_clone(doc, id, original_id.as_deref() == Some(target), names)?;
        }
    }
    Ok(())
}

fn extend_parent(
    doc: &mut XmlDocument,
    clones: &[NodeId],
    owner: &ResolvedRegion,
    destination: usize,
) -> Result<(), NativeAdmissionError> {
    if destination == owner.region.end_paragraph + 1 {
        let ctrl = doc
            .parent(owner.end)
            .ok_or_else(|| error("detached parent BOOKMARK end"))?;
        doc.remove_element(ctrl)?;
        let last = *clones.last().ok_or_else(|| error("empty clone block"))?;
        let run = *direct_runs(doc, last)
            .last()
            .ok_or_else(|| error("missing cloned final run"))?;
        let index = doc.node(run).children.len();
        doc.insert_element(run, index, ctrl)?;
    } else if destination == owner.region.start_paragraph {
        let ctrl = doc
            .parent(owner.begin)
            .ok_or_else(|| error("detached parent BOOKMARK begin"))?;
        doc.remove_element(ctrl)?;
        let first = *clones.first().ok_or_else(|| error("empty clone block"))?;
        let run = *direct_runs(doc, first)
            .first()
            .ok_or_else(|| error("missing cloned first run"))?;
        doc.insert_element(run, 0, ctrl)?;
    }
    Ok(())
}

fn insertion_index(
    doc: &XmlDocument,
    paragraphs: &[NodeId],
    destination: usize,
) -> Result<usize, NativeAdmissionError> {
    if destination < paragraphs.len() {
        content_index(doc, doc.root, paragraphs[destination])
    } else {
        let last = *paragraphs
            .last()
            .ok_or_else(|| error("missing section paragraph"))?;
        let mut after = content_index(doc, doc.root, last)? + 1;
        while matches!(
            doc.node(doc.root).children.get(after),
            Some(Content::Text(_) | Content::CData(_))
        ) {
            after += 1;
        }
        Ok(after)
    }
}

fn insert_clones(
    doc: &mut XmlDocument,
    clones: Vec<NodeId>,
    tails: Vec<Vec<Content>>,
    mut insertion: usize,
) -> Result<(), NativeAdmissionError> {
    for (paragraph, tail) in clones.into_iter().zip(tails) {
        doc.insert_element(doc.root, insertion, paragraph)?;
        insertion += 1;
        for part in tail {
            doc.node_mut(doc.root).children.insert(insertion, part);
            insertion += 1;
        }
    }
    Ok(())
}

fn validate_duplicate(
    current: &[ResolvedRegion],
    after: &[ResolvedRegion],
    section: &str,
    new_target_id: &str,
    name: &str,
) -> Result<(), NativeAdmissionError> {
    let old = shape(current, false);
    let all = shape(after, false);
    if old.iter().any(|(key, value)| all.get(key) != Some(value))
        || after
            .iter()
            .filter(|item| {
                item.region.section == section
                    && item.region.pairing_id == new_target_id
                    && item.region.name.as_deref() == Some(name)
            })
            .count()
            != 1
    {
        return Err(error("BOOKMARK duplicate postcondition failed"));
    }
    Ok(())
}

/// Duplicate a closed top-level native block. Product metadata is passed as
/// inert text; this routine only controls XML IDs, pair topology and rollback.
pub fn duplicate_bookmark_block(
    package: &mut HwpxPackage,
    handle: &BookmarkRegion,
    destination: usize,
    names: BookmarkCloneNames<'_>,
) -> Result<(), NativeAdmissionError> {
    let (sections, current, at) = fresh(package, handle)?;
    let region = &current[at];
    let section = &sections[region.section_index];
    if destination > section.paragraphs.len() {
        return Err(error("invalid BOOKMARK duplicate destination"));
    }
    let block = &section.paragraphs[handle.start_paragraph..=handle.end_paragraph];
    let internal = closed_pairs(&section.doc, block, &handle.pairing_id, &current)?;
    let mut doc = section.doc.clone();
    let clones: Vec<_> = block.iter().map(|id| doc.clone_subtree(*id)).collect();
    let tails = block
        .iter()
        .map(|id| paragraph_tail(&section.doc, *id))
        .collect::<Result<_, _>>()?;
    remove_external_markers(&mut doc, &clones, &internal)?;
    let id_map = allocate_clone_ids(package, &doc, &clones)?;
    let new_target_id = id_map
        .get(&handle.pairing_id)
        .ok_or_else(|| error("missing cloned BOOKMARK ID"))?;
    rebase_clones(&mut doc, &clones, &id_map, &handle.pairing_id, &names)?;
    if let Some(parent) = region.region.parent.as_ref()
        && let Some(owner) = current.iter().find(|item| {
            item.region.section == parent.section && item.region.pairing_id == parent.pairing_id
        })
    {
        extend_parent(&mut doc, &clones, owner, destination)?;
    }
    let index = insertion_index(&doc, &section.paragraphs, destination)?;
    insert_clones(&mut doc, clones, tails, index)?;
    let (data, after) = candidate(package, &handle.section, doc)?;
    validate_duplicate(&current, &after, &handle.section, new_target_id, names.name)?;
    replace_entry(package, &handle.section, data)
}
