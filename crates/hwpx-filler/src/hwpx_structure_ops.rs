//! Guarded product Slot mutations over the native BOOKMARK format kernel.

use crate::fields::collapse_field_id;
use crate::hwpx_product_inspection::{
    SlotSnapshot, inspect_slot_regions, inspect_slots, serialize_slot_metatag,
    serialize_slot_option_metatag,
};
use crate::hwpx_structure::{
    StructurePlacement, StructureScan, begin_marker_text, end_marker_text, scan_structure,
};
use crate::slot::{Slot, SlotOption};
use crate::structure_scan::python_trim;
use hwpx_core::bookmark_region::{
    BookmarkRegion, append_bookmark_metatag, create_bookmark_region, remove_bookmark_region,
    remove_top_level_paragraph, replace_bookmark_metatag, resolve_bookmark_topology,
    unwrap_bookmark_region,
};
use hwpx_core::marker_edit::insert_marker_paragraphs;
use hwpx_core::package::HwpxPackage;
use hwpx_core::structural_boundary::python_string_repr;
use hwpx_core::text_extract::section_xml_names;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fmt;

mod preflight;
use preflight::structure_preflight;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureOpsError(pub String);
impl fmt::Display for StructureOpsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for StructureOpsError {}

fn error(message: impl Into<String>) -> StructureOpsError {
    StructureOpsError(message.into())
}

fn require_text<'a>(value: &'a str, field: &str) -> Result<&'a str, StructureOpsError> {
    if python_trim(value).is_empty() {
        Err(error(format!("{field} must be a non-empty string")))
    } else {
        Ok(value)
    }
}

fn snapshot(package: &HwpxPackage) -> Result<SlotSnapshot, StructureOpsError> {
    let snapshot = inspect_slot_regions(package).map_err(|item| error(item.to_string()))?;
    if !snapshot.diagnostics.is_empty() {
        let details = snapshot
            .diagnostics
            .iter()
            .map(|item| format!("{}: {}", item.kind, item.message))
            .collect::<Vec<_>>()
            .join("; ");
        return Err(error(format!(
            "Slot mutation blocked by diagnostics: {details}"
        )));
    }
    Ok(snapshot)
}

fn restore_on_failure<T>(
    package: &mut HwpxPackage,
    action: impl FnOnce(&mut HwpxPackage) -> Result<T, StructureOpsError>,
) -> Result<T, StructureOpsError> {
    // Native operations mutate XML entries only. Keep unrelated binary assets borrowed.
    let names = package.content_xml_names();
    let backup: Vec<_> = package
        .entries
        .iter()
        .enumerate()
        .filter(|(_, entry)| names.contains(&entry.name.as_str()))
        .map(|(at, entry)| (at, entry.data.clone()))
        .collect();
    match action(package) {
        Ok(value) => Ok(value),
        Err(error) => {
            for (at, data) in backup {
                package.entries[at].data = data;
            }
            Err(error)
        }
    }
}

fn require_slots(
    package: &HwpxPackage,
    expected: &[Slot],
    what: &str,
) -> Result<(), StructureOpsError> {
    let (actual, diagnostics) = inspect_slots(package).map_err(|item| error(item.to_string()))?;
    if !diagnostics.is_empty() || actual != expected {
        return Err(error(format!(
            "{what} postcondition failed: expected {expected:?}, got {actual:?} with {diagnostics:?}"
        )));
    }
    Ok(())
}

pub fn remove_slot(package: &mut HwpxPackage, slot_id: &str) -> Result<(), StructureOpsError> {
    let identifier = require_text(slot_id, "Slot id")?;
    let snapshot = snapshot(package)?;
    let region = snapshot.slot_regions.get(identifier).ok_or_else(|| {
        error(format!(
            "Slot {} was not found",
            python_string_repr(identifier)
        ))
    })?;
    let expected: Vec<_> = snapshot
        .slots
        .iter()
        .filter(|slot| slot.id != identifier)
        .cloned()
        .collect();
    restore_on_failure(package, |package| {
        remove_bookmark_region(package, region).map_err(|item| error(item.to_string()))?;
        require_slots(package, &expected, "Slot removal")
    })
}

pub fn remove_slot_option(
    package: &mut HwpxPackage,
    slot_id: &str,
    option_id: &str,
) -> Result<(), StructureOpsError> {
    let owner_id = require_text(slot_id, "Slot id")?;
    let target_id = require_text(option_id, "Slot Option id")?;
    let snapshot = snapshot(package)?;
    let region = snapshot
        .option_regions
        .get(&(owner_id.to_owned(), target_id.to_owned()))
        .ok_or_else(|| {
            error(format!(
                "Option {} was not found in Slot {}",
                python_string_repr(target_id),
                python_string_repr(owner_id)
            ))
        })?;
    let expected: Vec<_> = snapshot
        .slots
        .iter()
        .map(|slot| {
            if slot.id != owner_id {
                return slot.clone();
            }
            let options = slot
                .options
                .iter()
                .filter(|item| item.id != target_id)
                .enumerate()
                .map(|(order, option)| SlotOption {
                    id: option.id.clone(),
                    order,
                    label: option.label.clone(),
                })
                .collect();
            Slot {
                id: slot.id.clone(),
                label: slot.label.clone(),
                options,
            }
        })
        .collect();
    restore_on_failure(package, |package| {
        remove_bookmark_region(package, region).map_err(|item| error(item.to_string()))?;
        require_slots(package, &expected, "Slot removal")
    })
}

pub(crate) fn product_metatag_index(region: &BookmarkRegion) -> Result<usize, StructureOpsError> {
    let matches: Vec<_> = region
        .meta_tags
        .iter()
        .enumerate()
        .filter_map(|(at, raw)| {
            let value: serde_json::Value = serde_json::from_str(raw).ok()?;
            value.as_object()?.contains_key("hwpxFiller").then_some(at)
        })
        .collect();
    if matches.len() != 1 {
        return Err(error(format!(
            "product MetaTag is not uniquely addressable: {:?} ({})",
            region.name,
            matches.len()
        )));
    }
    Ok(matches[0])
}

pub fn rename_slot_label(
    package: &mut HwpxPackage,
    slot_id: &str,
    new_label: Option<&str>,
) -> Result<(), StructureOpsError> {
    let identifier = require_text(slot_id, "Slot id")?;
    let label = new_label.and_then(collapse_field_id);
    let snapshot = snapshot(package)?;
    let region = snapshot.slot_regions.get(identifier).ok_or_else(|| {
        error(format!(
            "Slot {} was not found",
            python_string_repr(identifier)
        ))
    })?;
    let index = product_metatag_index(region)?;
    let expected: Vec<_> = snapshot
        .slots
        .iter()
        .map(|slot| {
            if slot.id == identifier {
                Slot {
                    id: slot.id.clone(),
                    options: slot.options.clone(),
                    label: label.clone(),
                }
            } else {
                slot.clone()
            }
        })
        .collect();
    let payload =
        serialize_slot_metatag(expected.iter().find(|slot| slot.id == identifier).unwrap())
            .map_err(|item| error(item.to_string()))?;
    restore_on_failure(package, |package| {
        replace_bookmark_metatag(package, region, index, &payload)
            .map_err(|item| error(item.to_string()))?;
        require_slots(package, &expected, "Slot rename")
    })
}

type RegionIdentity = (String, Option<String>, Vec<String>, Option<String>);

fn region_identity(region: &BookmarkRegion) -> RegionIdentity {
    (
        region.section.clone(),
        region.name.clone(),
        region.meta_tags.clone(),
        region.meta_tag_attribute.clone(),
    )
}

fn region_counts(regions: &[BookmarkRegion]) -> HashMap<RegionIdentity, usize> {
    let mut counts = HashMap::new();
    for region in regions {
        *counts.entry(region_identity(region)).or_insert(0) += 1;
    }
    counts
}

fn subtract_regions(
    mut all: HashMap<RegionIdentity, usize>,
    removed: &[BookmarkRegion],
) -> HashMap<RegionIdentity, usize> {
    for region in removed {
        let identity = region_identity(region);
        if let Some(count) = all.get_mut(&identity) {
            *count -= 1;
            if *count == 0 {
                all.remove(&identity);
            }
        }
    }
    all
}

fn relocate_region(
    package: &HwpxPackage,
    region: &BookmarkRegion,
) -> Result<BookmarkRegion, StructureOpsError> {
    let regions = resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?;
    let matches: Vec<_> = regions
        .into_iter()
        .filter(|item| {
            item.section == region.section
                && item.name == region.name
                && item.start_paragraph == region.start_paragraph
                && item.end_paragraph == region.end_paragraph
                && item.meta_tags == region.meta_tags
        })
        .collect();
    if matches.len() != 1 {
        return Err(error(format!(
            "BOOKMARK is not uniquely resolvable: {:?} ({})",
            region.name,
            matches.len()
        )));
    }
    Ok(matches.into_iter().next().unwrap())
}

fn sorted_notation(mut slots: Vec<Slot>) -> Vec<Slot> {
    slots.sort_by(|a, b| a.id.cmp(&b.id));
    slots
}

fn require_notation(
    package: &HwpxPackage,
    expected: Vec<Slot>,
    what: &str,
) -> Result<(), StructureOpsError> {
    let residue = scan_structure(package).map_err(|item| error(item.to_string()))?;
    if !residue.diagnostics.is_empty()
        || sorted_notation(residue.slots) != sorted_notation(expected)
    {
        return Err(error(format!("{what} postcondition (notation) failed")));
    }
    Ok(())
}

fn require_preserved_regions(
    package: &HwpxPackage,
    before: HashMap<RegionIdentity, usize>,
    removed: &[BookmarkRegion],
    what: &str,
) -> Result<(), StructureOpsError> {
    let after =
        region_counts(&resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?);
    if after != subtract_regions(before, removed) {
        return Err(error(format!(
            "{what} postcondition (pre-existing regions) failed"
        )));
    }
    Ok(())
}

pub fn decompile_slot(package: &mut HwpxPackage, slot_id: &str) -> Result<(), StructureOpsError> {
    let identifier = require_text(slot_id, "Slot id")?;
    let snapshot = snapshot(package)?;
    let region = snapshot
        .slot_regions
        .get(identifier)
        .ok_or_else(|| {
            error(format!(
                "Slot {} was not found",
                python_string_repr(identifier)
            ))
        })?
        .clone();
    let slot = snapshot
        .slots
        .iter()
        .find(|item| item.id == identifier)
        .unwrap()
        .clone();
    let options: Vec<_> = slot
        .options
        .iter()
        .map(|option| {
            snapshot
                .option_regions
                .get(&(identifier.to_owned(), option.id.clone()))
                .cloned()
                .map(|region| (option.clone(), region))
                .ok_or_else(|| error("Slot Option region was not found"))
        })
        .collect::<Result<_, _>>()?;
    if options
        .iter()
        .any(|(option, item)| item.section != region.section && !option.id.is_empty())
    {
        return Err(error(format!(
            "Slot {} option lives in another entry",
            python_string_repr(identifier)
        )));
    }
    let mut markers = vec![(
        region.start_paragraph,
        begin_marker_text("slot", &slot.id, slot.label.as_deref())
            .map_err(|item| error(item.to_string()))?,
    )];
    for (option, option_region) in &options {
        markers.push((
            option_region.start_paragraph,
            begin_marker_text("option", &option.id, option.label.as_deref())
                .map_err(|item| error(item.to_string()))?,
        ));
        markers.push((
            option_region.end_paragraph + 1,
            end_marker_text("option").map_err(|item| error(item.to_string()))?,
        ));
    }
    markers.push((
        region.end_paragraph + 1,
        end_marker_text("slot").map_err(|item| error(item.to_string()))?,
    ));
    let expected: Vec<_> = snapshot
        .slots
        .iter()
        .filter(|item| item.id != identifier)
        .cloned()
        .collect();
    let before =
        region_counts(&resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?);
    let removed: Vec<_> = std::iter::once(region.clone())
        .chain(options.iter().map(|(_, item)| item.clone()))
        .collect();
    let before_notation = scan_structure(package)
        .map_err(|item| error(item.to_string()))?
        .slots;
    restore_on_failure(package, |package| {
        for (_, option_region) in &options {
            let current = relocate_region(package, option_region)?;
            unwrap_bookmark_region(package, &current).map_err(|item| error(item.to_string()))?;
        }
        let current = relocate_region(package, &region)?;
        unwrap_bookmark_region(package, &current).map_err(|item| error(item.to_string()))?;
        let target = package
            .entries
            .iter_mut()
            .find(|item| item.name == region.section)
            .ok_or_else(|| error("content XML was not found"))?;
        target.data = insert_marker_paragraphs(&target.data, &markers)
            .map_err(|item| error(format!("{}: {item}", region.section)))?;

        let mut expected_notation = before_notation.clone();
        expected_notation.push(slot.clone());
        require_notation(package, expected_notation, "Slot decompile")?;
        require_slots(package, &expected, "Slot decompile")?;
        require_preserved_regions(package, before, &removed, "Slot decompile")
    })
}

pub fn decompile_structure(package: &mut HwpxPackage) -> Result<Vec<Slot>, StructureOpsError> {
    let initial = snapshot(package)?;
    if initial.slots.is_empty() {
        return Ok(Vec::new());
    }
    let declared = initial.slots;
    let before =
        region_counts(&resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?);
    let removed: Vec<_> = initial
        .slot_regions
        .into_values()
        .chain(initial.option_regions.into_values())
        .collect();
    restore_on_failure(package, |package| {
        for slot in &declared {
            decompile_slot(package, &slot.id)?;
        }
        require_slots(package, &[], "Structure decompile")?;
        require_notation(package, declared.clone(), "structure decompile")?;
        require_preserved_regions(package, before, &removed, "structure decompile")?;
        Ok(declared)
    })
}

pub fn structure_region_name(slot_id: &str, option_id: Option<&str>) -> String {
    option_id.map_or_else(
        || slot_id.to_owned(),
        |option| format!("{slot_id}/{option}"),
    )
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StructureCompileRefusalKind {
    NotationDiagnostic,
    UnsupportedEntry,
    NativeBlocker,
    ExistingProduct,
    NameCollision,
    ExistingRegionOverlap,
}
impl StructureCompileRefusalKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NotationDiagnostic => "notation-diagnostic",
            Self::UnsupportedEntry => "unsupported-entry",
            Self::NativeBlocker => "native-blocker",
            Self::ExistingProduct => "existing-product",
            Self::NameCollision => "name-collision",
            Self::ExistingRegionOverlap => "existing-region-overlap",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureCompileRefusal {
    pub kind: StructureCompileRefusalKind,
    pub code: String,
    pub message: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureCompileReport {
    pub modified: bool,
    pub slots: Vec<Slot>,
    pub options: usize,
    pub refusal: Option<Vec<StructureCompileRefusal>>,
}

fn refusal(
    kind: StructureCompileRefusalKind,
    code: &str,
    message: String,
) -> StructureCompileRefusal {
    StructureCompileRefusal {
        kind,
        code: code.into(),
        message,
    }
}

fn created_names(scan: &StructureScan) -> HashSet<(String, String)> {
    scan.placements
        .iter()
        .map(|item| {
            (
                item.entry.clone(),
                structure_region_name(
                    &item.slot_id,
                    (item.kind == "option")
                        .then_some(item.option_id.as_deref())
                        .flatten(),
                ),
            )
        })
        .collect()
}

fn placement_name(placement: &StructurePlacement) -> String {
    structure_region_name(
        &placement.slot_id,
        (placement.kind == "option")
            .then_some(placement.option_id.as_deref())
            .flatten(),
    )
}

type RegionShape = (RegionIdentity, Option<RegionIdentity>);

fn non_product_region_shape(
    regions: &[BookmarkRegion],
    created: &HashSet<(String, String)>,
) -> HashMap<RegionShape, usize> {
    let mut shape = HashMap::new();
    for region in regions {
        if region
            .name
            .as_ref()
            .is_some_and(|name| created.contains(&(region.section.clone(), name.clone())))
        {
            continue;
        }
        let key = (
            region_identity(region),
            region.parent.as_deref().map(region_identity),
        );
        *shape.entry(key).or_insert(0) += 1;
    }
    shape
}

type Locator = (String, String, usize, usize);

fn locate_region(
    package: &HwpxPackage,
    locator: &Locator,
) -> Result<BookmarkRegion, StructureOpsError> {
    let matches: Vec<_> = resolve_bookmark_topology(package)
        .map_err(|item| error(item.to_string()))?
        .into_iter()
        .filter(|region| {
            region.section == locator.0
                && region.name.as_deref() == Some(locator.1.as_str())
                && region.start_paragraph == locator.2
                && region.end_paragraph == locator.3
        })
        .collect();
    if matches.len() != 1 {
        return Err(error(format!(
            "created BOOKMARK is not uniquely resolvable: {locator:?} ({})",
            matches.len()
        )));
    }
    Ok(matches.into_iter().next().unwrap())
}

fn create_structure_regions(
    package: &mut HwpxPackage,
    scan: &StructureScan,
) -> Result<(), StructureOpsError> {
    let by_slot: HashMap<_, _> = scan
        .slots
        .iter()
        .map(|slot| (slot.id.as_str(), slot))
        .collect();
    let mut slot_locators: HashMap<&str, Locator> = HashMap::new();
    let mut created = Vec::new();
    for placement in &scan.placements {
        let slot = by_slot
            .get(placement.slot_id.as_str())
            .ok_or_else(|| error("structure placement has no Slot"))?;
        let name = placement_name(placement);
        let (payload, parent) = if placement.kind == "option" {
            let option = slot
                .options
                .iter()
                .find(|item| Some(item.id.as_str()) == placement.option_id.as_deref())
                .ok_or_else(|| error("structure placement has no Option"))?;
            let parent_locator = slot_locators
                .get(placement.slot_id.as_str())
                .ok_or_else(|| error("Option placement precedes Slot"))?;
            (
                serialize_slot_option_metatag(option).map_err(|item| error(item.to_string()))?,
                Some(locate_region(package, parent_locator)?),
            )
        } else {
            (
                serialize_slot_metatag(slot).map_err(|item| error(item.to_string()))?,
                None,
            )
        };
        create_bookmark_region(
            package,
            &placement.entry,
            placement.content_start,
            placement.content_end,
            &name,
            parent.as_ref(),
        )
        .map_err(|item| error(item.to_string()))?;
        let locator = (
            placement.entry.clone(),
            name,
            placement.content_start,
            placement.content_end,
        );
        if placement.kind == "slot" {
            slot_locators.insert(&placement.slot_id, locator.clone());
        }
        created.push((locator, payload));
    }
    for (locator, payload) in created {
        let region = locate_region(package, &locator)?;
        append_bookmark_metatag(package, &region, &payload)
            .map_err(|item| error(item.to_string()))?;
    }
    let mut markers: BTreeMap<&str, BTreeSet<usize>> = BTreeMap::new();
    for placement in &scan.placements {
        let indexes = markers.entry(&placement.entry).or_default();
        indexes.insert(placement.begin_marker_index);
        indexes.insert(placement.end_marker_index);
    }
    for (entry, indexes) in markers {
        for index in indexes.into_iter().rev() {
            remove_top_level_paragraph(package, entry, index)
                .map_err(|item| error(item.to_string()))?;
        }
    }
    Ok(())
}

fn merged_slot_expectation(
    package: &HwpxPackage,
    scan: &StructureScan,
) -> Result<Vec<Slot>, StructureOpsError> {
    let order: HashMap<_, _> = section_xml_names(package)
        .into_iter()
        .enumerate()
        .map(|(at, entry)| (entry.to_owned(), at))
        .collect();
    let snapshot = snapshot(package)?;
    let mut placed = Vec::new();
    for slot in snapshot.slots {
        let region = &snapshot.slot_regions[&slot.id];
        placed.push((
            (order[&region.section], region.start_paragraph, 0usize),
            slot,
        ));
    }
    let starts: HashMap<_, _> = scan
        .placements
        .iter()
        .filter(|item| item.kind == "slot")
        .map(|item| {
            (
                item.slot_id.as_str(),
                (order[&item.entry], item.content_start),
            )
        })
        .collect();
    for slot in &scan.slots {
        let (entry_index, start) = starts[slot.id.as_str()];
        placed.push(((entry_index, start, 1), slot.clone()));
    }
    placed.sort_by_key(|(key, _)| *key);
    Ok(placed.into_iter().map(|(_, slot)| slot).collect())
}

fn require_compiled_structure(
    package: &HwpxPackage,
    expected: &[Slot],
    before: &HashMap<RegionShape, usize>,
    created: &HashSet<(String, String)>,
) -> Result<(), StructureOpsError> {
    require_slots(
        package,
        expected,
        "structure compile postcondition A (declared Slots)",
    )?;
    let residue = scan_structure(package).map_err(|item| error(item.to_string()))?;
    if !residue.slots.is_empty()
        || !residue.diagnostics.is_empty()
        || !residue.placements.is_empty()
    {
        return Err(error(
            "structure compile postcondition B (notation residue) failed",
        ));
    }
    let after = non_product_region_shape(
        &resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?,
        created,
    );
    if &after != before {
        return Err(error(
            "structure compile postcondition C (pre-existing regions) failed",
        ));
    }
    Ok(())
}

pub fn compile_structure(
    package: &mut HwpxPackage,
) -> Result<StructureCompileReport, StructureOpsError> {
    let scan = scan_structure(package).map_err(|item| error(item.to_string()))?;
    if !scan.diagnostics.is_empty() {
        return Ok(StructureCompileReport {
            modified: false,
            slots: Vec::new(),
            options: 0,
            refusal: Some(
                scan.diagnostics
                    .iter()
                    .map(|item| {
                        refusal(
                            StructureCompileRefusalKind::NotationDiagnostic,
                            item.kind.as_str(),
                            item.message.clone(),
                        )
                    })
                    .collect(),
            ),
        });
    }
    if scan.placements.is_empty() {
        return Ok(StructureCompileReport {
            modified: false,
            slots: Vec::new(),
            options: 0,
            refusal: None,
        });
    }
    let refusals = structure_preflight(package, &scan)?;
    if !refusals.is_empty() {
        return Ok(StructureCompileReport {
            modified: false,
            slots: Vec::new(),
            options: 0,
            refusal: Some(refusals),
        });
    }
    let created = created_names(&scan);
    let before = non_product_region_shape(
        &resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?,
        &HashSet::new(),
    );
    let expected = merged_slot_expectation(package, &scan)?;
    restore_on_failure(package, |package| {
        create_structure_regions(package, &scan)?;
        require_compiled_structure(package, &expected, &before, &created)
    })?;
    Ok(StructureCompileReport {
        modified: true,
        options: scan.slots.iter().map(|slot| slot.options.len()).sum(),
        slots: scan.slots,
        refusal: None,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::hwpx_product_inspection::{serialize_slot_metatag, serialize_slot_option_metatag};
    use hwpx_core::bookmark_region::{append_bookmark_metatag, create_bookmark_region};
    use hwpx_core::package::PackageEntry;
    use hwpx_core::package::PackageLimits;
    use hwpx_core::text_model::HP_NS;
    use hwpx_core::xml_view::XmlView;

    const SECTION: &str = "Contents/section0.xml";
    const NOTATION: &[&str] = &[
        "머리",
        "{{#항목 특약 특약 사항}}",
        "{{#선택 지체상금 지체상금 조항}}",
        "지체상금은 {{지체상금률}} 로 한다.",
        "{{/선택}}",
        "{{#선택 하자보수 하자보수 조항}}",
        "하자보수 기간은 {{하자기간}} 이다.",
        "{{/선택}}",
        "{{/항목}}",
        "{{#항목 부기 부기 사항}}",
        "부기: {{부기문}}",
        "{{/항목}}",
        "꼬리",
    ];

    fn notation_package() -> HwpxPackage {
        package_from_body(
            &NOTATION
                .iter()
                .map(|text| paragraph(text))
                .collect::<String>(),
        )
    }

    fn paragraph(text: &str) -> String {
        format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>")
    }

    fn package_from_body(body: &str) -> HwpxPackage {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>"
        );
        HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: SECTION.into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "BinData/image.png".into(),
                    data: vec![0, 255, 1],
                    stored: true,
                },
            ],
        }
    }

    fn simple_notation() -> String {
        ["{{#항목 특약}}", "본문", "{{/항목}}"]
            .map(paragraph)
            .join("")
    }

    fn bookmark(name: &str, meta: &str) -> String {
        let payload = if meta.is_empty() {
            String::new()
        } else {
            format!("<hp:metaTag>{meta}</hp:metaTag>")
        };
        format!(
            "<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='5' type='BOOKMARK' name='{name}'>{payload}</hp:fieldBegin></hp:ctrl><hp:t>남의 본문</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='5'/></hp:ctrl></hp:run></hp:p>"
        )
    }

    fn assert_refusal(mut package: HwpxPackage, expected: &[(StructureCompileRefusalKind, &str)]) {
        let before = package.clone();
        let report = compile_structure(&mut package).unwrap();
        assert!(!report.modified);
        assert!(report.slots.is_empty());
        assert_eq!(report.options, 0);
        let reasons = report.refusal.unwrap();
        assert_eq!(
            reasons
                .iter()
                .map(|item| (item.kind, item.code.as_str()))
                .collect::<Vec<_>>(),
            expected
        );
        assert!(reasons.iter().all(|item| !item.message.is_empty()));
        assert_eq!(package, before);
    }

    #[test]
    fn compile_preflight_refuses_invalid_structure_without_mutating_any_entry() {
        use StructureCompileRefusalKind as Kind;
        assert_refusal(
            package_from_body(&paragraph("{{#항목 특약}}")),
            &[(Kind::NotationDiagnostic, "unbalanced_marker")],
        );
        let notation = simple_notation();
        let orphan = "<hp:p><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='99'/></hp:ctrl><hp:t>x</hp:t></hp:run></hp:p>";
        assert_refusal(
            package_from_body(&format!("{notation}{orphan}")),
            &[
                (Kind::NativeBlocker, "field-pairing-unusable"),
                (Kind::NativeBlocker, "bookmark-topology-unusable"),
            ],
        );
        for (name, payload, kind, code) in [
            (
                "기존",
                "<hp:t>nested</hp:t>".to_owned(),
                Kind::NativeBlocker,
                "bookmark-metadata-unusable",
            ),
            (
                "기존",
                "not json".into(),
                Kind::ExistingProduct,
                "malformed-json",
            ),
            (
                "다른이름",
                serialize_slot_metatag(&Slot {
                    id: "특약".into(),
                    label: None,
                    options: vec![],
                })
                .unwrap(),
                Kind::ExistingProduct,
                "duplicate-slot-id",
            ),
            ("특약", String::new(), Kind::NameCollision, "특약"),
        ] {
            assert_refusal(
                package_from_body(&format!("{}{notation}", bookmark(name, &payload))),
                &[(kind, code)],
            );
        }
        let mut header = package_from_body(&notation);
        header.entries[0].name = "Contents/header0.xml".into();
        assert_refusal(header, &[(Kind::UnsupportedEntry, "Contents/header0.xml")]);

        let begin = "<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='5' type='BOOKMARK' name='기존'/></hp:ctrl><hp:t>머리</hp:t></hp:run></hp:p>";
        let end = "<hp:p><hp:run><hp:t>꼬리</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='5'/></hp:ctrl></hp:run></hp:p>";
        for body in [
            format!(
                "{}{}{}",
                paragraph("{{#항목 특약}}"),
                bookmark("기존", "{\"name\":\"#other\"}"),
                paragraph("{{/항목}}")
            ),
            format!("{begin}{notation}{end}"),
            format!(
                "{begin}{}{end}{}{}",
                paragraph("{{#항목 특약}}"),
                paragraph("본문"),
                paragraph("{{/항목}}")
            ),
        ] {
            let mut package = package_from_body(&body);
            assert_refusal(package.clone(), &[(Kind::ExistingRegionOverlap, "기존")]);
            let message = &compile_structure(&mut package).unwrap().refusal.unwrap()[0].message;
            assert!(message.contains("'특약' 범위가 기존 '기존' 책갈피와 겹칩니다"));
            for banned in ["BOOKMARK", "topology", "crossing", "—", "「", "」"] {
                assert!(!message.contains(banned));
            }
        }
    }

    #[test]
    fn compile_preserves_existing_products_in_document_order_and_ignores_unrelated_entries() {
        let existing = Slot {
            id: "기존".into(),
            label: None,
            options: vec![],
        };
        let declared = Slot {
            id: "특약".into(),
            label: None,
            options: vec![],
        };
        let old = bookmark("기존", &serialize_slot_metatag(&existing).unwrap());
        let new = simple_notation();
        for (body, expected) in [
            (
                format!("{old}{new}"),
                vec![existing.clone(), declared.clone()],
            ),
            (
                format!("{new}{old}"),
                vec![declared.clone(), existing.clone()],
            ),
        ] {
            let mut package = package_from_body(&body);
            let report = compile_structure(&mut package).unwrap();
            assert!(report.modified && report.refusal.is_none());
            assert_eq!(report.slots, std::slice::from_ref(&declared));
            assert_eq!(inspect_slots(&package).unwrap(), (expected, vec![]));
            let before = package.clone();
            assert_eq!(
                compile_structure(&mut package).unwrap(),
                StructureCompileReport {
                    modified: false,
                    slots: vec![],
                    options: 0,
                    refusal: None,
                }
            );
            assert_eq!(package, before);
        }
        let mut package = package_from_body(&new);
        let mut other = package_from_body(&format!(
            "{}{}",
            paragraph("머리"),
            bookmark("남의 섹션", "{\"name\":\"#other\"}")
        ))
        .entries
        .remove(0);
        other.name = "Contents/section1.xml".into();
        package.entries.push(other.clone());
        assert!(compile_structure(&mut package).unwrap().modified);
        assert_eq!(package.entries[2], other);
        assert_eq!(
            resolve_bookmark_topology(&package)
                .unwrap()
                .iter()
                .map(|region| (region.name.as_deref().unwrap(), region.section.as_str()))
                .collect::<Vec<_>>(),
            [("특약", SECTION), ("남의 섹션", "Contents/section1.xml")]
        );

        let partial = bookmark("기존", "").replacen("<hp:ctrl>", "<hp:t>앞</hp:t><hp:ctrl>", 1);
        let mut package = package_from_body(&format!("{partial}{new}"));
        assert!(compile_structure(&mut package).unwrap().modified);
        assert_eq!(inspect_slots(&package).unwrap(), (vec![declared], vec![]));
        assert!(texts(&package).join("").contains("앞남의 본문"));
    }

    #[test]
    fn compile_distinguishes_marker_whitespace_from_objects_and_keeps_body_tables() {
        for extra in [
            "<hp:tab/>",
            "<hp:lineBreak/>",
            "<hp:t><hp:lineBreak/></hp:t>",
        ] {
            let marker =
                paragraph("{{#항목 특약}}").replace("</hp:run>", &format!("{extra}</hp:run>"));
            let mut package = package_from_body(&format!(
                "{marker}{}{}",
                paragraph("본문"),
                paragraph("{{/항목}}")
            ));
            assert!(compile_structure(&mut package).unwrap().modified);
            assert_eq!(texts(&package), ["본문"]);
        }
        let mut package = package_from_body(&simple_notation().replacen(
            "</hp:p>",
            "<hp:linesegarray/></hp:p>",
            1,
        ));
        assert!(compile_structure(&mut package).unwrap().modified);
        for extra in [
            "<hp:pic marker='KEEP'/>",
            "<hp:ctrl><hp:bookmark marker='KEEP'/></hp:ctrl>",
        ] {
            let marker =
                paragraph("{{#항목 특약}}").replace("</hp:run>", &format!("{extra}</hp:run>"));
            assert_refusal(
                package_from_body(&format!(
                    "{marker}{}{}",
                    paragraph("본문"),
                    paragraph("{{/항목}}")
                )),
                &[
                    (
                        StructureCompileRefusalKind::NotationDiagnostic,
                        "marker_not_alone",
                    ),
                    (
                        StructureCompileRefusalKind::NotationDiagnostic,
                        "unbalanced_marker",
                    ),
                ],
            );
        }
        let table = "<hp:tbl rowCnt='1' colCnt='1'><hp:pos treatAsChar='1'/><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>표 내용</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>";
        let opening = ["{{#항목 특약}}", "{{#선택 가}}", "본문 가"]
            .map(paragraph)
            .join("");
        let closing = ["{{#선택 나}}", "본문 나", "{{/선택}}", "{{/항목}}"]
            .map(paragraph)
            .join("");
        let bad_close = format!(
            "<hp:p><hp:run><hp:t> </hp:t>{table}</hp:run><hp:run><hp:t>{{{{/선택}}}}</hp:t></hp:run></hp:p>"
        );
        for body in [
            format!("{opening}{bad_close}{closing}"),
            format!("{}{bad_close}", paragraph("본문")),
        ] {
            let package = package_from_body(&body);
            let diagnostics = scan_structure(&package).unwrap().diagnostics;
            assert_eq!(diagnostics.len(), 1);
            assert_eq!(diagnostics[0].context, "{{/선택}}");
            assert_eq!(diagnostics[0].entry, SECTION);
            assert_eq!(
                diagnostics[0].index,
                Some(if body.starts_with(&opening) { 3 } else { 1 })
            );
            assert!(
                diagnostics[0]
                    .message
                    .contains("마커를 개체 다음 줄(별도 문단)로 옮기세요")
            );
            assert_refusal(
                package,
                &[(
                    StructureCompileRefusalKind::NotationDiagnostic,
                    "marker_not_alone",
                )],
            );
        }
        let mut package = package_from_body(&format!(
            "{opening}<hp:p><hp:run>{table}</hp:run></hp:p>{}{closing}",
            paragraph("{{/선택}}")
        ));
        assert!(compile_structure(&mut package).unwrap().modified);
        assert_eq!(
            inspect_slots(&package).unwrap().0[0]
                .options
                .iter()
                .map(|option| (&*option.id, option.order))
                .collect::<Vec<_>>(),
            [("가", 0), ("나", 1)]
        );
        let xml = String::from_utf8(package.entries[0].data.clone()).unwrap();
        assert_eq!(xml.matches("<hp:tbl").count(), 1);
        assert!(xml.contains("표 내용"));
    }

    #[test]
    fn compile_postconditions_reject_declaration_notation_and_region_loss_atomically() {
        let mut package = notation_package();
        let scan = scan_structure(&package).unwrap();
        let created = created_names(&scan);
        for violation in ["A", "B", "C"] {
            let before = package.clone();
            let failure = restore_on_failure(&mut package, |package| {
                create_structure_regions(package, &scan)?;
                let mut expected = scan.slots.clone();
                let mut preserved = HashMap::new();
                match violation {
                    "A" => expected[0].id = "다른 항목".into(),
                    "B" => {
                        package.entries[0].data = insert_marker_paragraphs(
                            &package.entries[0].data,
                            &[(0, "{{/항목}}".into())],
                        )
                        .unwrap();
                    }
                    "C" => {
                        preserved.insert(
                            (
                                (SECTION.into(), Some("잃은 구간".into()), vec![], None),
                                None,
                            ),
                            1,
                        );
                    }
                    _ => unreachable!(),
                }
                require_compiled_structure(package, &expected, &preserved, &created)
            })
            .unwrap_err();
            assert!(
                failure.0.contains(&format!("postcondition {violation}")),
                "{failure}"
            );
            assert_eq!(package, before);
        }
        let mut package = package_from_body(&paragraph("본문"));
        let outer = create_bookmark_region(&mut package, SECTION, 0, 0, "SAME", None).unwrap();
        create_bookmark_region(&mut package, SECTION, 0, 0, "SAME", Some(&outer)).unwrap();
        let before = package.clone();
        assert!(
            locate_region(&package, &(SECTION.into(), "SAME".into(), 0, 0))
                .unwrap_err()
                .0
                .contains("not uniquely resolvable")
        );
        assert_eq!(package, before);
    }

    fn texts(package: &HwpxPackage) -> Vec<String> {
        let view = XmlView::parse(&package.entries[0].data).unwrap();
        view.descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| view.node(*id).unwrap().name.is(HP_NS, "t"))
            .map(|id| view.direct_text(id).unwrap())
            .collect()
    }

    fn topology(package: &HwpxPackage) -> Vec<(RegionIdentity, Option<String>, usize, usize)> {
        resolve_bookmark_topology(package)
            .unwrap()
            .iter()
            .map(|region| {
                (
                    region_identity(region),
                    region
                        .parent
                        .as_ref()
                        .and_then(|parent| parent.name.clone()),
                    region.start_paragraph,
                    region.end_paragraph,
                )
            })
            .collect()
    }

    #[test]
    fn multiple_slots_round_trip_with_order_content_and_foreign_bookmarks_intact() {
        assert_manual_compilation();
        let mut package = notation_package();
        let neighbour =
            create_bookmark_region(&mut package, SECTION, 0, 0, "남의구간", None).unwrap();
        append_bookmark_metatag(&mut package, &neighbour, "{\"name\":\"#other\"}").unwrap();
        let neighbour = resolve_bookmark_topology(&package).unwrap().remove(0);
        let declared = scan_structure(&package).unwrap().slots;
        let report = compile_structure(&mut package).unwrap();
        assert!(report.modified && report.refusal.is_none());
        assert_eq!(report.slots, declared);
        assert_eq!(report.options, 2);
        let reference = (
            inspect_slots(&package).unwrap(),
            topology(&package),
            texts(&package),
        );
        decompile_slot(&mut package, "특약").unwrap();
        assert_eq!(inspect_slots(&package).unwrap().0, declared[1..]);
        let scan = scan_structure(&package).unwrap();
        assert!(scan.diagnostics.is_empty());
        assert_eq!(scan.slots, declared[..1]);
        assert!(compile_structure(&mut package).unwrap().modified);
        assert_eq!(
            (
                inspect_slots(&package).unwrap(),
                topology(&package),
                texts(&package)
            ),
            reference
        );

        assert_eq!(decompile_structure(&mut package).unwrap(), declared);
        assert_eq!(inspect_slots(&package).unwrap(), (vec![], vec![]));
        assert_eq!(texts(&package), NOTATION);
        let neighbours = resolve_bookmark_topology(&package).unwrap();
        assert_eq!(neighbours.len(), 1);
        assert_eq!(region_identity(&neighbours[0]), region_identity(&neighbour));
        assert_eq!(scan_structure(&package).unwrap().slots, declared);
        let before_noop = package.clone();
        assert!(decompile_structure(&mut package).unwrap().is_empty());
        assert_eq!(package, before_noop);
        assert!(compile_structure(&mut package).unwrap().modified);
        assert_eq!(
            (
                inspect_slots(&package).unwrap(),
                topology(&package),
                texts(&package)
            ),
            reference
        );
        assert_eq!(package.entries[1], before_noop.entries[1]);

        remove_slot(&mut package, "부기").unwrap();
        assert_eq!(inspect_slots(&package).unwrap().0, declared[..1]);
        assert!(!texts(&package).join("").contains("부기:"));
    }

    fn assert_manual_compilation() {
        let mut compiled = notation_package();
        let expected = vec![
            Slot {
                id: "특약".into(),
                label: Some("특약 사항".into()),
                options: vec![
                    SlotOption {
                        id: "지체상금".into(),
                        order: 0,
                        label: Some("지체상금 조항".into()),
                    },
                    SlotOption {
                        id: "하자보수".into(),
                        order: 1,
                        label: Some("하자보수 조항".into()),
                    },
                ],
            },
            Slot {
                id: "부기".into(),
                label: Some("부기 사항".into()),
                options: vec![],
            },
        ];
        assert_eq!(compile_structure(&mut compiled).unwrap().slots, expected);
        let body = [
            "머리",
            "지체상금은 {{지체상금률}} 로 한다.",
            "하자보수 기간은 {{하자기간}} 이다.",
            "부기: {{부기문}}",
            "꼬리",
        ];
        assert_eq!(texts(&compiled), body);
        let mut manual = package_from_body(&body.map(paragraph).join(""));
        let slot = create_bookmark_region(&mut manual, SECTION, 1, 2, "특약", None).unwrap();
        append_bookmark_metatag(
            &mut manual,
            &slot,
            &serialize_slot_metatag(&expected[0]).unwrap(),
        )
        .unwrap();
        for option in &expected[0].options {
            let parent = resolve_bookmark_topology(&manual).unwrap().remove(0);
            let child = create_bookmark_region(
                &mut manual,
                SECTION,
                option.order + 1,
                option.order + 1,
                &format!("특약/{}", option.id),
                Some(&parent),
            )
            .unwrap();
            append_bookmark_metatag(
                &mut manual,
                &child,
                &serialize_slot_option_metatag(option).unwrap(),
            )
            .unwrap();
        }
        let slot = create_bookmark_region(&mut manual, SECTION, 3, 3, "부기", None).unwrap();
        append_bookmark_metatag(
            &mut manual,
            &slot,
            &serialize_slot_metatag(&expected[1]).unwrap(),
        )
        .unwrap();
        assert_eq!(inspect_slots(&compiled).unwrap(), (expected, vec![]));
        assert_eq!(topology(&compiled), topology(&manual));
        let scan = scan_structure(&compiled).unwrap();
        assert!(scan.slots.is_empty() && scan.diagnostics.is_empty() && scan.placements.is_empty());
    }

    #[test]
    fn label_changes_preserve_options_and_text_and_invalid_mutations_are_atomic() {
        let mut package = notation_package();
        compile_structure(&mut package).unwrap();
        let declared = inspect_slots(&package).unwrap().0;
        let content = texts(&package);
        for (label, expected) in [
            (Some("  계약   특약  "), Some("계약 특약")),
            (Some("   "), None),
            (None, None),
        ] {
            rename_slot_label(&mut package, "특약", label).unwrap();
            let slots = inspect_slots(&package).unwrap().0;
            assert_eq!(slots[0].label.as_deref(), expected);
            assert_eq!(slots[0].options, declared[0].options);
            assert_eq!(slots[1], declared[1]);
            assert_eq!(texts(&package), content);
            let payload = &snapshot(&package).unwrap().slot_regions["특약"].meta_tags[0];
            assert_eq!(payload, &serialize_slot_metatag(&slots[0]).unwrap());
        }
        for id in ["없는항목", "", "   "] {
            let before = package.clone();
            assert!(rename_slot_label(&mut package, id, Some("새 이름")).is_err());
            assert!(decompile_slot(&mut package, id).is_err());
            assert!(remove_slot(&mut package, id).is_err());
            assert!(remove_slot_option(&mut package, id, "지체상금").is_err());
            assert!(remove_slot_option(&mut package, "특약", id).is_err());
            assert_eq!(package, before);
        }
        let region = snapshot(&package).unwrap().slot_regions["특약"].clone();
        append_bookmark_metatag(&mut package, &region, "not json").unwrap();
        let before = package.clone();
        assert!(
            rename_slot_label(&mut package, "특약", Some("새 이름"))
                .unwrap_err()
                .0
                .contains("blocked by diagnostics")
        );
        assert!(decompile_structure(&mut package).is_err());
        assert_eq!(package, before);
    }

    #[test]
    fn decompile_failures_restore_earlier_slots_and_postconditions_reject_data_loss() {
        let mut package = notation_package();
        compile_structure(&mut package).unwrap();
        rename_slot_label(&mut package, "부기", Some("닫는}}괄호")).unwrap();
        let before = package.clone();
        assert!(
            decompile_structure(&mut package)
                .unwrap_err()
                .0
                .contains("label")
        );
        assert_eq!(package, before);
        assert!(scan_structure(&package).unwrap().slots.is_empty());

        rename_slot_label(&mut package, "부기", Some("부기 사항")).unwrap();
        decompile_slot(&mut package, "특약").unwrap();
        let before = package.clone();
        assert!(
            decompile_structure(&mut package)
                .unwrap_err()
                .0
                .contains("postcondition (notation)")
        );
        assert_eq!(package, before);

        compile_structure(&mut package).unwrap();
        let before = package.clone();
        let regions = region_counts(&resolve_bookmark_topology(&package).unwrap());
        let declared = inspect_slots(&package).unwrap().0;
        let failure = restore_on_failure(&mut package, |package| {
            decompile_structure(package)?;
            // A missing removal record must not bless loss of a pre-existing region.
            require_preserved_regions(package, regions, &[], "structure decompile")
        })
        .unwrap_err();
        assert!(failure.0.contains("pre-existing regions"));
        assert_eq!(package, before);
        let failure = restore_on_failure(&mut package, |package| {
            decompile_structure(package)?;
            let mut expected = declared;
            expected.push(Slot {
                id: "없는항목".into(),
                label: None,
                options: vec![],
            });
            require_notation(package, expected, "Slot decompile")
        })
        .unwrap_err();
        assert!(failure.0.contains("postcondition (notation)"));
        assert_eq!(package, before);
    }

    #[test]
    fn canonical_slot_rename_and_option_removal_keep_other_assets_and_failed_request_rolls_back() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/slots/canonical.hwpx");
        let bytes = std::fs::read(path).unwrap();
        let mut package = HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap();
        let binary_before: Vec<_> = package
            .entries
            .iter()
            .filter(|entry| !entry.name.ends_with(".xml"))
            .cloned()
            .collect();
        let original = snapshot(&package).unwrap();
        let first = original.slots.first().unwrap().clone();
        let option = first.options.first().unwrap().clone();
        let before_bad = package.clone();
        assert!(remove_slot(&mut package, "missing").is_err());
        assert_eq!(package, before_bad);

        rename_slot_label(&mut package, &first.id, Some("새  제목")).unwrap();
        assert_eq!(
            snapshot(&package).unwrap().slots[0].label.as_deref(),
            Some("새 제목")
        );
        remove_slot_option(&mut package, &first.id, &option.id).unwrap();
        let remaining = snapshot(&package).unwrap();
        assert_eq!(remaining.slots[0].id, first.id);
        assert_eq!(remaining.slots[0].options.len() + 1, first.options.len());
        let before_unrepresentable = package.clone();
        assert!(decompile_slot(&mut package, &first.id).is_err());
        assert_eq!(package, before_unrepresentable);
        let binary_after: Vec<_> = package
            .entries
            .iter()
            .filter(|entry| !entry.name.ends_with(".xml"))
            .cloned()
            .collect();
        assert_eq!(binary_before, binary_after);
    }

    #[test]
    fn decompile_slot_restores_notation_and_preserves_unrelated_content() {
        let section = "Contents/section0.xml";
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>A</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>B</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>C</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: section.into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let slot = Slot {
            id: "s".into(),
            label: None,
            options: vec![],
        };
        let option = SlotOption {
            id: "o".into(),
            order: 0,
            label: None,
        };
        let outer = create_bookmark_region(&mut package, section, 0, 2, "S", None).unwrap();
        append_bookmark_metatag(
            &mut package,
            &outer,
            &serialize_slot_metatag(&slot).unwrap(),
        )
        .unwrap();
        let outer = resolve_bookmark_topology(&package).unwrap().remove(0);
        let inner = create_bookmark_region(&mut package, section, 1, 1, "O", Some(&outer)).unwrap();
        append_bookmark_metatag(
            &mut package,
            &inner,
            &serialize_slot_option_metatag(&option).unwrap(),
        )
        .unwrap();

        decompile_slot(&mut package, "s").unwrap();
        assert!(inspect_slots(&package).unwrap().0.is_empty());
        let scan = scan_structure(&package).unwrap();
        assert!(scan.diagnostics.is_empty());
        assert_eq!(scan.slots.len(), 1);
        assert_eq!(scan.slots[0].id, "s");
        assert_eq!(scan.slots[0].options, std::slice::from_ref(&option));
        let text = String::from_utf8(package.entries[0].data.clone()).unwrap();
        assert!(text.contains("<hp:t>A</hp:t>"));
        assert!(text.contains("<hp:t>C</hp:t>"));

        let report = compile_structure(&mut package).unwrap();
        assert!(report.modified);
        assert_eq!(report.slots[0].id, "s");
        assert_eq!(report.options, 1);
        assert!(report.refusal.is_none());
        assert_eq!(inspect_slots(&package).unwrap().0[0].options, [option]);
        assert!(scan_structure(&package).unwrap().placements.is_empty());
    }
}
