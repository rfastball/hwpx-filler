//! Read-only admission before compiling product structure markers.

use super::{
    StructureCompileRefusal, StructureCompileRefusalKind, StructureOpsError, created_names, error,
    placement_name, refusal,
};
use crate::hwpx_product_inspection::inspect_slots;
use crate::hwpx_structure::StructureScan;
use hwpx_core::bookmark_region::resolve_bookmark_topology;
use hwpx_core::native_admission::{BookmarkRemovalBlockerKind, inspect_native_capabilities};
use hwpx_core::package::HwpxPackage;
use hwpx_core::structural_boundary::scan_structural_boundaries;
use hwpx_core::text_extract::section_xml_names;
use std::collections::HashSet;

fn append_unique(refusals: &mut Vec<StructureCompileRefusal>, item: StructureCompileRefusal) {
    if !refusals.contains(&item) {
        refusals.push(item);
    }
}

fn native_refusals(
    package: &HwpxPackage,
    scan: &StructureScan,
) -> Result<Vec<StructureCompileRefusal>, StructureOpsError> {
    let mut refusals = Vec::new();
    let sections: HashSet<_> = section_xml_names(package).into_iter().collect();
    for placement in &scan.placements {
        if !sections.contains(placement.entry.as_str()) {
            refusals.push(refusal(
                StructureCompileRefusalKind::UnsupportedEntry,
                &placement.entry,
                format!(
                    "「{}」 범위가 본문 섹션이 아닌 {} 에 있습니다 — 구간은 본문 섹션에서만 만들 수 있습니다.",
                    placement.slot_id, placement.entry
                ),
            ));
        }
    }
    let boundary = scan_structural_boundaries(package);
    let capabilities =
        inspect_native_capabilities(package, &boundary).map_err(|item| error(item.to_string()))?;
    for entry in &boundary.entries {
        if !entry.field_pairing_usable {
            refusals.push(refusal(
                StructureCompileRefusalKind::NativeBlocker,
                "field-pairing-unusable",
                format!("{}: 기존 누름틀 짝짓기를 신뢰할 수 없습니다.", entry.entry),
            ));
        }
        if !entry.bookmark_topology_usable {
            refusals.push(refusal(
                StructureCompileRefusalKind::NativeBlocker,
                "bookmark-topology-unusable",
                format!("{}: 기존 BOOKMARK 계층을 신뢰할 수 없습니다.", entry.entry),
            ));
        }
    }
    for removal in &capabilities.bookmark_removals {
        for blocker in &removal.blockers {
            if matches!(
                blocker.kind,
                BookmarkRemovalBlockerKind::UnsupportedEntry
                    | BookmarkRemovalBlockerKind::BookmarkTopologyUnusable
                    | BookmarkRemovalBlockerKind::BookmarkMetadataUnusable
                    | BookmarkRemovalBlockerKind::FieldPairingUnusable
            ) {
                refusals.push(refusal(
                    StructureCompileRefusalKind::NativeBlocker,
                    blocker.kind.as_str(),
                    if blocker.detail.is_empty() {
                        blocker.kind.as_str().into()
                    } else {
                        blocker.detail.join("; ")
                    },
                ));
            }
        }
    }
    Ok(refusals)
}

fn product_refusals(
    package: &HwpxPackage,
    scan: &StructureScan,
) -> Result<Vec<StructureCompileRefusal>, StructureOpsError> {
    let mut refusals = Vec::new();
    let (existing, diagnostics) = inspect_slots(package).map_err(|item| error(item.to_string()))?;
    for item in diagnostics {
        refusals.push(refusal(
            StructureCompileRefusalKind::ExistingProduct,
            &item.kind,
            item.message,
        ));
    }
    let taken: HashSet<_> = existing.iter().map(|slot| slot.id.as_str()).collect();
    for slot in &scan.slots {
        if taken.contains(slot.id.as_str()) {
            refusals.push(refusal(
                StructureCompileRefusalKind::ExistingProduct,
                "duplicate-slot-id",
                format!(
                    "'{}' 항목이 이미 누름틀 구조로 들어 있습니다. 표기의 id 를 바꾸거나 기존 항목을 먼저 지우세요.",
                    slot.id
                ),
            ));
        }
    }
    Ok(refusals)
}

fn region_refusals(
    package: &HwpxPackage,
    scan: &StructureScan,
) -> Result<Vec<StructureCompileRefusal>, StructureOpsError> {
    let mut refusals = Vec::new();
    let wanted = created_names(scan);
    let existing_regions =
        resolve_bookmark_topology(package).map_err(|item| error(item.to_string()))?;
    for region in &existing_regions {
        if region
            .name
            .as_ref()
            .is_some_and(|name| wanted.contains(&(region.section.clone(), name.clone())))
        {
            refusals.push(refusal(
                StructureCompileRefusalKind::NameCollision,
                region.name.as_deref().unwrap(),
                format!(
                    "{}: 「{}」 이름의 책갈피가 이미 있습니다 — 선언 id 를 바꾸거나 기존 책갈피를 지우세요.",
                    region.section, region.name.as_deref().unwrap()
                ),
            ));
        }
    }
    for placement in &scan.placements {
        let name = placement_name(placement);
        for region in &existing_regions {
            if region.section != placement.entry
                || region.start_paragraph > placement.content_end
                || region.end_paragraph < placement.content_start
            {
                continue;
            }
            let label = region.name.as_deref().unwrap_or("(이름 없음)");
            refusals.push(refusal(
                StructureCompileRefusalKind::ExistingRegionOverlap,
                region.name.as_deref().unwrap_or(""),
                format!(
                    "'{name}' 범위가 기존 '{label}' 책갈피와 겹칩니다. 그 책갈피를 범위 밖으로 옮기거나 지운 뒤 다시 변환하세요."
                ),
            ));
        }
    }
    Ok(refusals)
}

pub(super) fn structure_preflight(
    package: &HwpxPackage,
    scan: &StructureScan,
) -> Result<Vec<StructureCompileRefusal>, StructureOpsError> {
    let mut refusals = native_refusals(package, scan)?;
    if refusals.is_empty() {
        refusals = product_refusals(package, scan)?;
        if !refusals.is_empty() {
            return Ok(refusals);
        }
        refusals = region_refusals(package, scan)?;
    }
    let mut unique = Vec::new();
    for item in refusals {
        append_unique(&mut unique, item);
    }
    Ok(unique)
}
