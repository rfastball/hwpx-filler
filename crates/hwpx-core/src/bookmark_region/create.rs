//! Creation of a native BOOKMARK with topology postconditions.

use super::*;

fn requested_parent<'a>(
    current: &'a [ResolvedRegion],
    section: &str,
    start_paragraph: usize,
    end_paragraph: usize,
    parent: Option<&BookmarkRegion>,
) -> Result<Option<&'a ResolvedRegion>, NativeAdmissionError> {
    let parent_region = if let Some(parent) = parent {
        Some(
            current
                .iter()
                .find(|item| item.region == *parent)
                .ok_or_else(|| {
                    error("parent BOOKMARK is not present in current package snapshot")
                })?,
        )
    } else {
        None
    };
    if let Some(parent) = parent_region
        && (parent.region.section != section
            || !(parent.region.start_paragraph <= start_paragraph
                && end_paragraph <= parent.region.end_paragraph))
    {
        return Err(error(
            "BOOKMARK range must be contained by its requested parent",
        ));
    }
    Ok(parent_region)
}

pub fn create_bookmark_region(
    package: &mut HwpxPackage,
    section: &str,
    start_paragraph: usize,
    end_paragraph: usize,
    name: &str,
    parent: Option<&BookmarkRegion>,
) -> Result<BookmarkRegion, NativeAdmissionError> {
    if name.trim().is_empty() {
        return Err(error("BOOKMARK name must be a non-empty string"));
    }
    let (sections, current) = resolve(package, false)?;
    let parent_region =
        requested_parent(&current, section, start_paragraph, end_paragraph, parent)?;
    let section_index = sections
        .iter()
        .position(|item| item.entry == section)
        .ok_or_else(|| error(format!("HWPX section was not found: {section:?}")))?;
    let selected = &sections[section_index];
    if start_paragraph > end_paragraph || end_paragraph >= selected.paragraphs.len() {
        return Err(error("invalid BOOKMARK paragraph range"));
    }
    let first = selected.paragraphs[start_paragraph];
    let last = selected.paragraphs[end_paragraph];
    let start_runs = direct_runs(&selected.doc, first);
    let end_runs = direct_runs(&selected.doc, last);
    if start_runs.is_empty() || end_runs.is_empty() {
        return Err(error(
            "BOOKMARK boundary paragraphs must contain a direct native hp:run",
        ));
    }
    let used: HashSet<_> = sections
        .iter()
        .flat_map(|item| item.begins.keys().chain(item.ends.keys()))
        .map(String::as_str)
        .collect();
    let pairing_id = (1_600_000_001u64..)
        .map(|id| id.to_string())
        .find(|id| !used.contains(id.as_str()))
        .unwrap();
    let mut doc = selected.doc.clone();
    let begin_ctrl = native_element(&mut doc, "ctrl", &[]);
    let begin = native_element(
        &mut doc,
        "fieldBegin",
        &[("id", &pairing_id), ("type", "BOOKMARK"), ("name", name)],
    );
    doc.insert_element(begin_ctrl, 0, begin)?;
    let end_ctrl = native_element(&mut doc, "ctrl", &[]);
    let end = native_element(&mut doc, "fieldEnd", &[("beginIDRef", &pairing_id)]);
    doc.insert_element(end_ctrl, 0, end)?;
    insert_begin(
        &mut doc,
        begin_ctrl,
        start_runs[0],
        parent_region.filter(|item| item.region.start_paragraph == start_paragraph),
    )?;
    insert_end(
        &mut doc,
        end_ctrl,
        *end_runs.last().unwrap(),
        parent_region.filter(|item| item.region.end_paragraph == end_paragraph),
    )?;
    let (data, after) = candidate(package, section, doc)?;
    let created = after
        .iter()
        .find(|item| item.region.section == section && item.region.pairing_id == pairing_id)
        .ok_or_else(|| error("created BOOKMARK does not match requested native topology"))?;
    validate_created_range(created, parent_region, start_paragraph, end_paragraph)?;
    let after_sections = parse_sections_with_override(package, Some((section, &data)))?;
    validate_extent(
        &after_sections[created.section_index],
        &after,
        created,
        false,
        false,
    )?;
    let mut unchanged = shape(&after, true);
    unchanged.remove(&(section.to_owned(), pairing_id));
    if unchanged != shape(&current, true) {
        return Err(error("creating BOOKMARK changed existing native topology"));
    }
    let result = created.region.clone();
    replace_entry(package, section, data)?;
    Ok(result)
}

fn insert_begin(
    doc: &mut XmlDocument,
    control: NodeId,
    first_run: NodeId,
    parent: Option<&ResolvedRegion>,
) -> Result<(), NativeAdmissionError> {
    if let Some(parent) = parent {
        let parent_ctrl = doc
            .parent(parent.begin)
            .ok_or_else(|| error("detached parent BOOKMARK begin"))?;
        let parent_run = doc
            .parent(parent_ctrl)
            .ok_or_else(|| error("detached parent BOOKMARK run"))?;
        let at = content_index(doc, parent_run, parent_ctrl)? + 1;
        doc.insert_element(parent_run, at, control)?;
    } else {
        doc.insert_element(first_run, 0, control)?;
    }
    Ok(())
}

fn insert_end(
    doc: &mut XmlDocument,
    control: NodeId,
    last_run: NodeId,
    parent: Option<&ResolvedRegion>,
) -> Result<(), NativeAdmissionError> {
    if let Some(parent) = parent {
        let parent_ctrl = doc
            .parent(parent.end)
            .ok_or_else(|| error("detached parent BOOKMARK end"))?;
        let parent_run = doc
            .parent(parent_ctrl)
            .ok_or_else(|| error("detached parent BOOKMARK run"))?;
        let at = content_index(doc, parent_run, parent_ctrl)?;
        doc.insert_element(parent_run, at, control)?;
    } else {
        let at = doc.node(last_run).children.len();
        doc.insert_element(last_run, at, control)?;
    }
    Ok(())
}

fn validate_created_range(
    created: &ResolvedRegion,
    parent_region: Option<&ResolvedRegion>,
    start_paragraph: usize,
    end_paragraph: usize,
) -> Result<(), NativeAdmissionError> {
    let wanted_parent = parent_region.map(|item| {
        (
            item.region.section.as_str(),
            item.region.pairing_id.as_str(),
        )
    });
    let actual_parent = created
        .region
        .parent
        .as_ref()
        .map(|item| (item.section.as_str(), item.pairing_id.as_str()));
    if created.region.start_paragraph != start_paragraph
        || created.region.end_paragraph != end_paragraph
        || actual_parent != wanted_parent
    {
        return Err(error(
            "created BOOKMARK does not match requested native topology",
        ));
    }
    Ok(())
}
