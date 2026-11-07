//! Product meaning over snapshot-bound native BOOKMARK observations.

use crate::slot::{Slot, SlotOption};
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use hwpx_core::bookmark_region::{BookmarkRegion, resolve_bookmark_topology};
use hwpx_core::package::HwpxPackage;
use hwpx_core::structural_boundary::{
    BoundaryEvent, BoundaryPairRef, ContentEntryKind, StructuralBoundaryScan,
    StructuralDiagnosticKind, scan_structural_boundaries,
};
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::fmt;

mod bookmark_scope;
use bookmark_scope::{BookmarkWalk, duplicate_id_diagnostics};

pub const PRODUCT_KIND_SLOT: &str = "slot";
pub const PRODUCT_KIND_OPTION: &str = "slot_option";
pub const NATIVE_NAME: &str = "#hf";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProductClassification {
    NonProduct,
    KnownProduct,
    InvalidProduct,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProductScopeRole {
    None,
    Slot,
    Option,
    InvalidProduct,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateDiagnostic {
    pub kind: String,
    pub message: String,
}

#[derive(Clone, Debug)]
pub struct ProductScopeObservation {
    pub pair: BoundaryPairRef,
    pub entry: String,
    pub classification: ProductClassification,
    pub scope_role: ProductScopeRole,
    pub scope_usable: bool,
    pub kind: Option<String>,
    pub product_id: Option<String>,
    pub owning_slot_pair: Option<BoundaryPairRef>,
    pub product_label: Option<String>,
}

#[derive(Clone, Debug)]
pub struct ProductBookmarkInspection {
    pub observations: Vec<ProductScopeObservation>,
    pub diagnostics: Vec<TemplateDiagnostic>,
    projection_pairs: HashSet<BoundaryPairRef>,
}

#[derive(Clone, Debug)]
pub struct SlotSnapshot {
    pub slots: Vec<Slot>,
    pub diagnostics: Vec<TemplateDiagnostic>,
    pub slot_regions: HashMap<String, BookmarkRegion>,
    pub option_regions: HashMap<(String, String), BookmarkRegion>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProductInspectionError(pub String);
impl fmt::Display for ProductInspectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ProductInspectionError {}

fn diagnostic(kind: &str, entry: &str, name: Option<&str>, detail: &str) -> TemplateDiagnostic {
    TemplateDiagnostic {
        kind: kind.into(),
        message: format!("{entry}: BOOKMARK {}: {detail}", py_repr(name)),
    }
}

fn py_repr(value: Option<&str>) -> String {
    match value {
        None => "None".into(),
        Some(value) => python_repr(&Value::String(value.into())),
    }
}

fn py_value_repr(value: Option<&Value>) -> String {
    value.map_or_else(|| "None".into(), python_repr)
}

fn require_text(value: &str, field: &str) -> Result<(), ProductInspectionError> {
    if python_trim(value).is_empty() {
        return Err(ProductInspectionError(format!(
            "{field} must be a non-empty string"
        )));
    }
    Ok(())
}

fn serialize_metatag(
    kind: &str,
    identifier: &str,
    label: Option<&str>,
) -> Result<String, ProductInspectionError> {
    let mut body = Map::new();
    body.insert("kind".into(), Value::String(kind.into()));
    body.insert("id".into(), Value::String(identifier.into()));
    if let Some(label) = label {
        require_text(label, &format!("{kind} label"))?;
        body.insert("label".into(), Value::String(label.into()));
    }
    let mut root = Map::new();
    root.insert("hwpxFiller".into(), Value::Object(body));
    root.insert("name".into(), Value::String(NATIVE_NAME.into()));
    serde_json::to_string(&Value::Object(root))
        .map_err(|error| ProductInspectionError(error.to_string()))
}

pub fn serialize_slot_metatag(slot: &Slot) -> Result<String, ProductInspectionError> {
    require_text(&slot.id, "Slot id")?;
    serialize_metatag(PRODUCT_KIND_SLOT, &slot.id, slot.label.as_deref())
}

pub fn serialize_slot_option_metatag(
    option: &SlotOption,
) -> Result<String, ProductInspectionError> {
    require_text(&option.id, "Slot Option id")?;
    serialize_metatag(PRODUCT_KIND_OPTION, &option.id, option.label.as_deref())
}

struct ParsedProduct {
    classification: ProductClassification,
    kind: Option<String>,
    id: Option<String>,
    label: Option<String>,
}
impl ParsedProduct {
    fn invalid() -> Self {
        Self {
            classification: ProductClassification::InvalidProduct,
            kind: None,
            id: None,
            label: None,
        }
    }
}

fn element_products(
    entry: &str,
    name: Option<&str>,
    meta_tags: &[String],
    diagnostics: &mut Vec<TemplateDiagnostic>,
) -> (Vec<Value>, bool, bool) {
    let mut parsed = Vec::new();
    let mut malformed = false;
    let mut product_signal = false;
    for raw in meta_tags {
        let value: Value = match serde_json::from_str(raw) {
            Ok(value) => value,
            Err(_) => {
                diagnostics.push(diagnostic(
                    "malformed-json",
                    entry,
                    name,
                    "invalid MetaTag JSON",
                ));
                malformed = true;
                continue;
            }
        };
        let Some(object) = value.as_object() else {
            continue;
        };
        if !object.contains_key("hwpxFiller") {
            if object.get("name").and_then(Value::as_str) == Some(NATIVE_NAME) {
                product_signal = true;
                diagnostics.push(diagnostic(
                    "invalid-product-payload",
                    entry,
                    name,
                    "canonical product MetaTag has no hwpxFiller object",
                ));
            }
            continue;
        }
        product_signal = true;
        parsed.push(value);
    }
    (parsed, malformed, product_signal)
}

fn attribute_product(
    entry: &str,
    name: Option<&str>,
    meta_tag_attribute: Option<&str>,
    diagnostics: &mut Vec<TemplateDiagnostic>,
) -> (Option<Value>, bool, bool) {
    let mut malformed = false;
    let mut product_signal = false;
    let mut attribute_product = None;
    if let Some(raw) = meta_tag_attribute.filter(|raw| !raw.is_empty()) {
        match serde_json::from_str::<Value>(raw) {
            Err(_) => {
                diagnostics.push(diagnostic(
                    "malformed-json",
                    entry,
                    name,
                    "invalid fieldBegin@metaTag JSON",
                ));
                malformed = true;
            }
            Ok(value) => {
                if let Some(object) = value.as_object() {
                    let has_body = object.contains_key("hwpxFiller");
                    let native = object.get("name").and_then(Value::as_str) == Some(NATIVE_NAME);
                    if has_body || native {
                        product_signal = true;
                        diagnostics.push(diagnostic(
                            "unsupported-carrier",
                            entry,
                            name,
                            "product metadata cannot use fieldBegin@metaTag",
                        ));
                    }
                    if native && !has_body {
                        diagnostics.push(diagnostic(
                            "invalid-product-payload",
                            entry,
                            name,
                            "fieldBegin@metaTag has no hwpxFiller object",
                        ));
                    }
                    if has_body {
                        attribute_product = Some(value);
                    }
                }
            }
        }
    }
    (attribute_product, malformed, product_signal)
}

fn decode_product(
    root: Value,
    unsupported_carrier: bool,
    entry: &str,
    name: Option<&str>,
    diagnostics: &mut Vec<TemplateDiagnostic>,
) -> ParsedProduct {
    let object = root.as_object().unwrap();
    let Some(body) = object.get("hwpxFiller").and_then(Value::as_object) else {
        diagnostics.push(diagnostic(
            "invalid-product-payload",
            entry,
            name,
            "hwpxFiller must be an object",
        ));
        return ParsedProduct::invalid();
    };
    let kind = body.get("kind").and_then(Value::as_str);
    if !matches!(kind, Some(PRODUCT_KIND_SLOT | PRODUCT_KIND_OPTION)) {
        diagnostics.push(diagnostic(
            "unknown-kind",
            entry,
            name,
            &format!("unknown kind {}", py_value_repr(body.get("kind"))),
        ));
        return ParsedProduct::invalid();
    }
    let kind = kind.unwrap().to_owned();
    let identifier = body.get("id").and_then(Value::as_str);
    if identifier.is_none_or(|id| python_trim(id).is_empty()) {
        diagnostics.push(diagnostic(
            "invalid-id",
            entry,
            name,
            "id must be a non-empty string",
        ));
        return ParsedProduct {
            classification: ProductClassification::KnownProduct,
            kind: Some(kind),
            id: None,
            label: None,
        };
    }
    let mut label = None;
    if let Some(value) = body.get("label") {
        if let Some(text) = value.as_str().filter(|text| !python_trim(text).is_empty()) {
            label = Some(text.to_owned());
        } else {
            diagnostics.push(diagnostic(
                "invalid-label",
                entry,
                name,
                "label must be a non-empty string when present",
            ));
        }
    }
    let native_name = object.get("name").and_then(Value::as_str);
    if native_name != Some(NATIVE_NAME) {
        diagnostics.push(diagnostic(
            "native-name-mismatch",
            entry,
            name,
            &format!(
                "name must be '#hf', got {}",
                py_value_repr(object.get("name"))
            ),
        ));
    }
    ParsedProduct {
        classification: ProductClassification::KnownProduct,
        kind: Some(kind),
        id: (!unsupported_carrier).then(|| identifier.unwrap().to_owned()),
        label: (!unsupported_carrier).then_some(label).flatten(),
    }
}

fn product_tag(
    entry: &str,
    name: Option<&str>,
    meta_tags: &[String],
    meta_tag_attribute: Option<&str>,
    diagnostics: &mut Vec<TemplateDiagnostic>,
) -> ParsedProduct {
    let (mut parsed, malformed_element, element_signal) =
        element_products(entry, name, meta_tags, diagnostics);
    let (attribute_product, malformed_attribute, attribute_signal) =
        attribute_product(entry, name, meta_tag_attribute, diagnostics);
    let malformed = malformed_element || malformed_attribute;
    let product_signal = element_signal || attribute_signal;
    if parsed.len() > 1 {
        diagnostics.push(diagnostic(
            "conflicting-product-metatag",
            entry,
            name,
            "multiple product MetaTags",
        ));
        return ParsedProduct::invalid();
    }
    let unsupported_carrier = parsed.is_empty() && attribute_product.is_some();
    let root = parsed.pop().or(attribute_product);
    let Some(root) = root else {
        return ParsedProduct {
            classification: if product_signal || malformed {
                ProductClassification::InvalidProduct
            } else {
                ProductClassification::NonProduct
            },
            kind: None,
            id: None,
            label: None,
        };
    };
    decode_product(root, unsupported_carrier, entry, name, diagnostics)
}

fn field_diagnostic(kind: StructuralDiagnosticKind) -> bool {
    kind.as_str().starts_with("field-")
}

fn validate_pair_lifecycle(scan: &StructuralBoundaryScan) -> Result<(), ProductInspectionError> {
    let mut opened: HashMap<BoundaryPairRef, (&str, bool)> = HashMap::new();
    let mut closed = HashSet::new();
    for entry in &scan.entries {
        for event in &entry.events {
            match event {
                BoundaryEvent::FieldBegin { pair, .. }
                | BoundaryEvent::BookmarkBegin { pair, .. } => {
                    if opened.contains_key(pair) || closed.contains(pair) {
                        return Err(ProductInspectionError(format!(
                            "{}: boundary pair reused",
                            entry.entry
                        )));
                    }
                    opened.insert(
                        pair.clone(),
                        (
                            &entry.entry,
                            matches!(event, BoundaryEvent::BookmarkBegin { .. }),
                        ),
                    );
                }
                BoundaryEvent::FieldEnd { pair, .. } | BoundaryEvent::BookmarkEnd { pair, .. } => {
                    let begin = opened.remove(pair);
                    if begin
                        != Some((
                            entry.entry.as_str(),
                            matches!(event, BoundaryEvent::BookmarkEnd { .. }),
                        ))
                    {
                        return Err(ProductInspectionError(format!(
                            "{}: boundary pair end contradicts begin",
                            entry.entry
                        )));
                    }
                    closed.insert(pair.clone());
                }
            }
        }
    }
    if !opened.is_empty() {
        return Err(ProductInspectionError(
            "Structural boundary scan ended with open pairs".into(),
        ));
    }
    Ok(())
}

fn translate_structural_diagnostics(scan: &StructuralBoundaryScan) -> Vec<TemplateDiagnostic> {
    scan.diagnostics
        .iter()
        .filter(|item| !field_diagnostic(item.kind))
        .map(|item| {
            let kind = if item.kind == StructuralDiagnosticKind::BookmarkCrossing {
                "crossing-range"
            } else {
                "bookmark-resolve-failed"
            };
            let location = item.entry.as_deref().unwrap_or("package");
            let detail = if item.detail.is_empty() {
                String::new()
            } else {
                format!(": {}", item.detail)
            };
            TemplateDiagnostic {
                kind: kind.into(),
                message: format!("{location}: {}{detail}", item.kind.as_str()),
            }
        })
        .collect()
}

pub fn inspect_product_bookmarks(
    scan: &StructuralBoundaryScan,
) -> Result<ProductBookmarkInspection, ProductInspectionError> {
    validate_pair_lifecycle(scan)?;
    let mut diagnostics = translate_structural_diagnostics(scan);
    let structural_product_entries: HashSet<_> = scan
        .diagnostics
        .iter()
        .filter(|item| !field_diagnostic(item.kind))
        .filter_map(|item| item.entry.as_deref())
        .collect();
    let unattributed_metatag_entries: HashSet<_> = scan
        .diagnostics
        .iter()
        .filter(|item| {
            matches!(
                item.kind,
                StructuralDiagnosticKind::NonNativeMetatag
                    | StructuralDiagnosticKind::InvalidMetatagShape
            )
        })
        .filter_map(|item| item.entry.as_deref())
        .collect();
    let projection_pairs: HashSet<_> = scan
        .entries
        .iter()
        .filter(|entry| {
            entry.kind == ContentEntryKind::Section
                && entry.bookmark_topology_usable
                && !unattributed_metatag_entries.contains(entry.entry.as_str())
        })
        .flat_map(|entry| entry.events.iter())
        .filter_map(|event| match event {
            BoundaryEvent::BookmarkBegin { pair, .. } => Some(pair.clone()),
            _ => None,
        })
        .collect();
    for entry in &scan.entries {
        if !entry.bookmark_topology_usable
            && !structural_product_entries.contains(entry.entry.as_str())
        {
            diagnostics.push(TemplateDiagnostic {
                kind: "bookmark-resolve-failed".into(),
                message: format!("{}: bookmark topology is unusable", entry.entry),
            });
        }
    }
    let mut walk = BookmarkWalk {
        unattributed_metatag_entries: &unattributed_metatag_entries,
        names: HashMap::new(),
        observations: Vec::new(),
        diagnostics,
    };
    for entry in &scan.entries {
        walk.entry(entry)?;
    }
    let BookmarkWalk {
        names,
        observations,
        mut diagnostics,
        ..
    } = walk;
    diagnostics.extend(duplicate_id_diagnostics(
        &observations,
        &names,
        &projection_pairs,
    ));
    Ok(ProductBookmarkInspection {
        observations,
        diagnostics,
        projection_pairs,
    })
}

fn project_slots(inspection: &ProductBookmarkInspection) -> Vec<Slot> {
    let mut options: HashMap<BoundaryPairRef, Vec<(String, Option<String>)>> = HashMap::new();
    for item in &inspection.observations {
        if let (Some(id), Some(owner)) = (&item.product_id, &item.owning_slot_pair)
            && item.classification == ProductClassification::KnownProduct
            && item.kind.as_deref() == Some(PRODUCT_KIND_OPTION)
            && inspection.projection_pairs.contains(&item.pair)
        {
            options
                .entry(owner.clone())
                .or_default()
                .push((id.clone(), item.product_label.clone()));
        }
    }
    inspection
        .observations
        .iter()
        .filter(|item| {
            item.classification == ProductClassification::KnownProduct
                && item.kind.as_deref() == Some(PRODUCT_KIND_SLOT)
                && item.product_id.is_some()
                && inspection.projection_pairs.contains(&item.pair)
        })
        .map(|item| Slot {
            id: item.product_id.clone().unwrap(),
            label: item.product_label.clone(),
            options: options
                .remove(&item.pair)
                .unwrap_or_default()
                .into_iter()
                .enumerate()
                .map(|(order, (id, label))| SlotOption { id, order, label })
                .collect(),
        })
        .collect()
}

fn match_region_handles(
    scan: &StructuralBoundaryScan,
    regions: Vec<BookmarkRegion>,
) -> Result<HashMap<BoundaryPairRef, BookmarkRegion>, ProductInspectionError> {
    let section_begins: Vec<_> = scan
        .entries
        .iter()
        .filter(|entry| entry.kind == ContentEntryKind::Section)
        .flat_map(|entry| {
            entry.events.iter().filter_map(|event| match event {
                BoundaryEvent::BookmarkBegin { .. } => Some((entry.entry.as_str(), event)),
                _ => None,
            })
        })
        .collect();
    if section_begins.len() != regions.len() {
        return Err(ProductInspectionError(
            "Structural scan and BOOKMARK mutation resolver disagree".into(),
        ));
    }
    let mut pair_regions = HashMap::new();
    for ((entry, event), region) in section_begins.into_iter().zip(regions) {
        let BoundaryEvent::BookmarkBegin {
            pair,
            bookmark_name,
            meta_tags,
            meta_tag_attribute,
            ..
        } = event
        else {
            unreachable!()
        };
        if entry != region.section
            || bookmark_name != &region.name
            || meta_tags != &region.meta_tags
            || meta_tag_attribute != &region.meta_tag_attribute
        {
            return Err(ProductInspectionError(
                "Structural scan and BOOKMARK mutation resolver order disagree".into(),
            ));
        }
        pair_regions.insert(pair.clone(), region);
    }
    Ok(pair_regions)
}

pub fn inspect_slot_regions(package: &HwpxPackage) -> Result<SlotSnapshot, ProductInspectionError> {
    let scan = scan_structural_boundaries(package);
    let inspection = inspect_product_bookmarks(&scan)?;
    let slots = project_slots(&inspection);
    if !inspection.diagnostics.is_empty() {
        return Ok(SlotSnapshot {
            slots,
            diagnostics: inspection.diagnostics,
            slot_regions: HashMap::new(),
            option_regions: HashMap::new(),
        });
    }
    let regions = match resolve_bookmark_topology(package) {
        Ok(regions) => regions,
        Err(error) => {
            return Ok(SlotSnapshot {
                slots,
                diagnostics: vec![TemplateDiagnostic {
                    kind: "bookmark-resolve-failed".into(),
                    message: error.to_string(),
                }],
                slot_regions: HashMap::new(),
                option_regions: HashMap::new(),
            });
        }
    };
    let pair_regions = match_region_handles(&scan, regions)?;
    let by_pair: HashMap<_, _> = inspection
        .observations
        .iter()
        .map(|item| (item.pair.clone(), item))
        .collect();
    let mut slot_regions = HashMap::new();
    let mut option_regions = HashMap::new();
    for item in &inspection.observations {
        if item.classification != ProductClassification::KnownProduct
            || item.product_id.is_none()
            || item.scope_role == ProductScopeRole::InvalidProduct
        {
            continue;
        }
        let region = pair_regions.get(&item.pair).ok_or_else(|| {
            ProductInspectionError(format!(
                "Product pair in {:?} has no mutation handle",
                item.entry
            ))
        })?;
        if item.kind.as_deref() == Some(PRODUCT_KIND_SLOT) {
            slot_regions.insert(item.product_id.clone().unwrap(), region.clone());
        } else if let Some(owner_pair) = &item.owning_slot_pair {
            let owner = by_pair.get(owner_pair).ok_or_else(|| {
                ProductInspectionError("Option owning Slot pair is absent".into())
            })?;
            let owner_id = owner.product_id.clone().ok_or_else(|| {
                ProductInspectionError("Option owning Slot pair is absent".into())
            })?;
            option_regions.insert((owner_id, item.product_id.clone().unwrap()), region.clone());
        }
    }
    Ok(SlotSnapshot {
        slots,
        diagnostics: Vec::new(),
        slot_regions,
        option_regions,
    })
}

pub fn inspect_slots(
    package: &HwpxPackage,
) -> Result<(Vec<Slot>, Vec<TemplateDiagnostic>), ProductInspectionError> {
    let snapshot = inspect_slot_regions(package)?;
    Ok((snapshot.slots, snapshot.diagnostics))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::bookmark_region::{append_bookmark_metatag, create_bookmark_region};
    use hwpx_core::package::PackageEntry;
    use hwpx_core::package::PackageLimits;
    use hwpx_core::text_model::HP_NS;
    use serde_json::json;
    use std::collections::BTreeSet;

    const SECTION: &str = "Contents/section0.xml";

    fn package(body: &str) -> HwpxPackage {
        HwpxPackage { entries: vec![
            PackageEntry { name: "mimetype".into(), data: b"application/hwp+zip".to_vec(), stored: true },
            PackageEntry { name: SECTION.into(), data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>").into_bytes(), stored: false },
        ] }
    }

    fn escaped(raw: &str) -> String {
        raw.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('"', "&quot;")
    }

    fn tagged_package(tags: &[String], attribute: Option<&str>) -> HwpxPackage {
        let attribute = attribute
            .map(|raw| format!(" metaTag=\"{}\"", escaped(raw)))
            .unwrap_or_default();
        let tags = tags
            .iter()
            .map(|raw| format!("<hp:metaTag>{}</hp:metaTag>", escaped(raw)))
            .collect::<String>();
        package(&format!(
            "<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' type='BOOKMARK' name='S'{attribute}>{tags}</hp:fieldBegin></hp:ctrl><hp:t>본문</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p>"
        ))
    }

    fn diagnostic_kinds(items: &[TemplateDiagnostic]) -> BTreeSet<&str> {
        items.iter().map(|item| item.kind.as_str()).collect()
    }

    fn slots_value(slots: &[Slot]) -> Value {
        Value::Array(slots.iter().map(|slot| json!({
            "id":slot.id, "label":slot.label,
            "options":slot.options.iter().map(|option| json!({"id":option.id,"label":option.label,"order":option.order})).collect::<Vec<_>>()
        })).collect())
    }

    #[test]
    fn metadata_diagnostics_preserve_known_roles_without_inventing_product_identity() {
        let canonical = json!({"hwpxFiller":{"kind":"slot","id":"slot"},"name":"#hf"});
        let malformed = "{".to_owned();
        let attribute = canonical.to_string();
        let cases = [
            (vec![malformed.clone()], None, vec!["malformed-json"]),
            (
                vec![json!({"hwpxFiller":[]}).to_string()],
                None,
                vec!["invalid-product-payload"],
            ),
            (
                vec![json!({"name":"#hf"}).to_string()],
                None,
                vec!["invalid-product-payload"],
            ),
            (
                vec![json!({"hwpxFiller":{"kind":[],"id":"slot"},"name":"#hf"}).to_string()],
                None,
                vec!["unknown-kind"],
            ),
            (
                vec![json!({"hwpxFiller":{"kind":"slot","id":""},"name":"#hf"}).to_string()],
                None,
                vec!["invalid-id"],
            ),
            (
                vec![json!({"hwpxFiller":{"kind":"slot","id":3},"name":"#hf"}).to_string()],
                None,
                vec!["invalid-id"],
            ),
            (
                vec![
                    json!({"hwpxFiller":{"kind":"slot","id":"slot","label":[]},"name":"#hf"})
                        .to_string(),
                ],
                None,
                vec!["invalid-label"],
            ),
            (
                vec![json!({"hwpxFiller":{"kind":"slot","id":"slot"},"name":"#wrong"}).to_string()],
                None,
                vec!["native-name-mismatch"],
            ),
            (
                vec![],
                Some(attribute.as_str()),
                vec!["unsupported-carrier"],
            ),
            (
                vec![],
                Some("{\"name\":\"#hf\"}"),
                vec!["unsupported-carrier", "invalid-product-payload"],
            ),
            (vec![], Some("{\"vendor\":1}"), vec![]),
            (vec![], Some("{"), vec!["malformed-json"]),
            (
                vec![canonical.to_string(), canonical.to_string()],
                None,
                vec!["conflicting-product-metatag"],
            ),
            (
                vec![malformed, canonical.to_string()],
                None,
                vec!["malformed-json"],
            ),
            (
                vec![canonical.to_string()],
                Some(attribute.as_str()),
                vec!["unsupported-carrier"],
            ),
            (
                vec![
                    json!(["vendor"]).to_string(),
                    json!({"vendor":{"future":true}}).to_string(),
                    canonical.to_string(),
                ],
                None,
                vec![],
            ),
        ];
        for (tags, attribute, expected) in cases {
            let package = tagged_package(&tags, attribute);
            let before = package.clone();
            let inspection =
                inspect_product_bookmarks(&scan_structural_boundaries(&package)).unwrap();
            assert_eq!(
                diagnostic_kinds(&inspection.diagnostics),
                expected.into_iter().collect(),
                "{tags:?} {attribute:?}"
            );
            let observation = &inspection.observations[0];
            if observation.kind.as_deref() == Some("slot") {
                assert_eq!(
                    observation.classification,
                    ProductClassification::KnownProduct
                );
                assert_eq!(observation.scope_role, ProductScopeRole::Slot);
                assert!(observation.scope_usable);
                let expected_id = if tags.is_empty()
                    || inspection
                        .diagnostics
                        .iter()
                        .any(|item| item.kind == "invalid-id")
                {
                    None
                } else {
                    Some("slot")
                };
                assert_eq!(observation.product_id.as_deref(), expected_id);
                let slots = inspect_slots(&package).unwrap().0;
                assert_eq!(slots.len(), usize::from(expected_id.is_some()));
            }
            assert_eq!(package, before);
        }
        assert_canonical_serializers();
    }

    fn assert_canonical_serializers() {
        let slot = Slot {
            id: "slot-1".into(),
            label: Some("추가 지급 안내".into()),
            options: vec![],
        };
        let option = SlotOption {
            id: "option-1".into(),
            order: 0,
            label: Some("성과급 안내".into()),
        };
        for (raw, expected) in [
            (
                serialize_slot_metatag(&slot).unwrap(),
                json!({"hwpxFiller":{"kind":"slot","id":"slot-1","label":"추가 지급 안내"},"name":"#hf"}),
            ),
            (
                serialize_slot_option_metatag(&option).unwrap(),
                json!({"hwpxFiller":{"kind":"slot_option","id":"option-1","label":"성과급 안내"},"name":"#hf"}),
            ),
        ] {
            assert!(raw.ends_with("\"name\":\"#hf\"}"));
            assert_eq!(serde_json::from_str::<Value>(&raw).unwrap(), expected);
        }
        for invalid in ["", " \u{1c} "] {
            assert!(
                serialize_slot_metatag(&Slot {
                    id: invalid.into(),
                    ..slot.clone()
                })
                .is_err()
            );
            assert!(
                serialize_slot_option_metatag(&SlotOption {
                    id: invalid.into(),
                    ..option.clone()
                })
                .is_err()
            );
            assert!(
                serialize_slot_metatag(&Slot {
                    label: Some(invalid.into()),
                    ..slot.clone()
                })
                .is_err()
            );
            assert!(
                serialize_slot_option_metatag(&SlotOption {
                    label: Some(invalid.into()),
                    ..option.clone()
                })
                .is_err()
            );
        }
    }

    #[test]
    fn invalid_native_topologies_keep_diagnostics_partial_projection_and_mutation_barriers() {
        let cases: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/product_scope_cases.json"
        ))
        .unwrap();
        for case in cases["cases"].as_array().unwrap() {
            let mut package = if let Some(corpus) = case["corpus"].as_str() {
                let bytes = std::fs::read(
                    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                        .join("../../tests/corpus")
                        .join(corpus),
                )
                .unwrap();
                HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap()
            } else {
                package("")
            };
            for (name, xml) in case["entries"].as_object().unwrap() {
                let data = xml.as_str().unwrap().as_bytes().to_vec();
                if let Some(entry) = package.entries.iter_mut().find(|entry| &entry.name == name) {
                    entry.data = data;
                } else {
                    package.entries.push(PackageEntry {
                        name: name.clone(),
                        data,
                        stored: false,
                    });
                }
            }
            let before = package.clone();
            let (slots, diagnostics) = inspect_slots(&package).unwrap();
            assert_eq!(slots_value(&slots), case["slots"], "{}", case["name"]);
            assert_eq!(
                diagnostic_kinds(&diagnostics),
                case["diagnostics"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|item| item.as_str().unwrap())
                    .collect(),
                "{}",
                case["name"]
            );
            assert!(
                crate::hwpx_structure_ops::remove_slot(&mut package, "missing")
                    .unwrap_err()
                    .0
                    .contains("blocked by diagnostics")
            );
            assert_eq!(package, before);
            if let Some(expected) = case.get("observations") {
                let inspection =
                    inspect_product_bookmarks(&scan_structural_boundaries(&package)).unwrap();
                assert_eq!(
                    observation_values(&inspection.observations),
                    *expected,
                    "{}",
                    case["name"]
                );
            }
            if case["name"].as_str().unwrap().starts_with("duplicate-") {
                let inspection =
                    inspect_product_bookmarks(&scan_structural_boundaries(&package)).unwrap();
                let kind = if case["name"] == "duplicate-slot" {
                    PRODUCT_KIND_SLOT
                } else {
                    PRODUCT_KIND_OPTION
                };
                let duplicates: Vec<_> = inspection
                    .observations
                    .iter()
                    .filter(|item| item.kind.as_deref() == Some(kind))
                    .collect();
                assert_eq!(duplicates.len(), 2);
                assert_eq!(duplicates[0].product_id, duplicates[1].product_id);
                assert_ne!(duplicates[0].pair, duplicates[1].pair);
            }
        }
    }

    fn observation_values(items: &[ProductScopeObservation]) -> Value {
        Value::Array(items.iter().map(|item| json!({
            "classification":match item.classification {
                ProductClassification::NonProduct => "non_product",
                ProductClassification::KnownProduct => "known_product",
                ProductClassification::InvalidProduct => "invalid_product",
            },
            "role":match item.scope_role {
                ProductScopeRole::None => "none",
                ProductScopeRole::Slot => "slot",
                ProductScopeRole::Option => "option",
                ProductScopeRole::InvalidProduct => "invalid_product",
            },
            "usable":item.scope_usable,"kind":item.kind,"id":item.product_id,
            "owner":item.owning_slot_pair.as_ref().and_then(|pair| items.iter().position(|owner| &owner.pair==pair)),
        })).collect())
    }

    fn native(corpus: &str) -> HwpxPackage {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus")
            .join(corpus);
        HwpxPackage::from_bytes(&std::fs::read(path).unwrap(), PackageLimits::default()).unwrap()
    }

    #[test]
    fn hancom_resaved_nested_product_regions_keep_slot_identity() {
        let source = native("metatag_s1/N1-nested-kernel.hwpx");
        let saved = native("metatag_s1/N1-resaved.hwpx");
        let (slots, diagnostics) = inspect_slots(&source).unwrap();
        assert!(diagnostics.is_empty());
        assert_eq!(inspect_slots(&saved).unwrap(), (slots.clone(), vec![]));
        assert_eq!(slots.len(), 1);
        assert_eq!(slots[0].id, "계약방식");
        assert_eq!(
            slots[0]
                .options
                .iter()
                .map(|option| option.id.as_str())
                .collect::<Vec<_>>(),
            ["일반경쟁", "수의계약"]
        );
        let before = resolve_bookmark_topology(&source).unwrap();
        let after = resolve_bookmark_topology(&saved).unwrap();
        assert_eq!(before.len(), 3);
        assert_eq!(
            before
                .iter()
                .map(|region| region.name.as_deref().unwrap())
                .collect::<Vec<_>>(),
            ["계약방식", "계약방식/일반경쟁", "계약방식/수의계약"]
        );
        assert_eq!(
            before
                .iter()
                .map(|region| (region.start_paragraph, region.end_paragraph))
                .collect::<Vec<_>>(),
            [(5, 6), (5, 5), (6, 6)]
        );
        assert!(before[0].parent.is_none());
        assert!(before[1..].iter().all(|region| {
            region
                .parent
                .as_ref()
                .and_then(|parent| parent.name.as_deref())
                == Some("계약방식")
        }));
        assert_eq!(
            before
                .iter()
                .map(|region| &region.meta_tags)
                .collect::<Vec<_>>(),
            after
                .iter()
                .map(|region| &region.meta_tags)
                .collect::<Vec<_>>()
        );
        assert!(
            before
                .iter()
                .all(|region| region.meta_tag_attribute.is_none())
        );
        assert!(
            after
                .iter()
                .all(|region| region.meta_tag_attribute.as_deref() == Some(""))
        );
    }

    fn add_tag(package: &mut HwpxPackage, name: &str, payload: &str) {
        let region = resolve_bookmark_topology(package)
            .unwrap()
            .into_iter()
            .find(|region| region.name.as_deref() == Some(name))
            .unwrap();
        append_bookmark_metatag(package, &region, payload).unwrap();
    }

    fn plain_ancestor() -> HwpxPackage {
        let body = ["A", "B", "C", "D", "E", "OUT"]
            .iter()
            .map(|text| format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"))
            .collect::<String>();
        let mut package = package(&body);
        let slot = create_bookmark_region(&mut package, SECTION, 0, 4, "SLOT", None).unwrap();
        let plain =
            create_bookmark_region(&mut package, SECTION, 1, 3, "PLAIN", Some(&slot)).unwrap();
        create_bookmark_region(&mut package, SECTION, 2, 2, "OPTION", Some(&plain)).unwrap();
        package
    }

    #[test]
    fn native_parent_shapes_keep_slot_local_identity_and_reindex_options_after_removal() {
        for (corpus, owner, children) in [
            ("", "SLOT", vec!["OPTION"]),
            (
                "structural_range_s0/R5-nested.hwpx",
                "S0_SLOT",
                vec!["S0_OPT_A", "S0_OPT_B"],
            ),
            (
                "structural_range_s0/G/G1-coincident-start.hwpx",
                "S0_OPT_A",
                vec!["S0_SLOT"],
            ),
            (
                "structural_range_s0/G/G2-coincident-end.hwpx",
                "S0_SLOT",
                vec!["S0_OPT_B"],
            ),
            (
                "structural_range_s0/G/G3-same-range.hwpx",
                "S0_SLOT",
                vec!["S0_OPT_X"],
            ),
        ] {
            let mut package = if corpus.is_empty() {
                plain_ancestor()
            } else {
                native(corpus)
            };
            let untouched: Vec<_> = package
                .entries
                .iter()
                .filter(|entry| entry.name != SECTION)
                .cloned()
                .collect();
            let slot = Slot {
                id: "slot".into(),
                label: Some("슬롯 라벨".into()),
                options: children
                    .iter()
                    .enumerate()
                    .map(|(order, name)| SlotOption {
                        id: (*name).into(),
                        order,
                        label: Some(format!("{name} 라벨")),
                    })
                    .collect(),
            };
            add_tag(&mut package, owner, "[\"vendor\"]");
            add_tag(&mut package, owner, "{\"vendor\":{\"future\":true}}");
            add_tag(&mut package, owner, &serialize_slot_metatag(&slot).unwrap());
            for (name, option) in children.iter().zip(&slot.options) {
                add_tag(
                    &mut package,
                    name,
                    &serialize_slot_option_metatag(option).unwrap(),
                );
            }
            assert_eq!(
                inspect_slots(&package).unwrap(),
                (vec![slot.clone()], vec![]),
                "{corpus}"
            );
            let reread =
                HwpxPackage::from_bytes(&package.to_bytes().unwrap(), PackageLimits::default())
                    .unwrap();
            assert_eq!(
                inspect_slots(&reread).unwrap(),
                (vec![slot.clone()], vec![])
            );
            assert_eq!(
                package
                    .entries
                    .iter()
                    .filter(|entry| entry.name != SECTION)
                    .cloned()
                    .collect::<Vec<_>>(),
                untouched
            );
            for target in &children {
                let mut removed = package.clone();
                crate::hwpx_structure_ops::remove_slot_option(&mut removed, "slot", target)
                    .unwrap();
                let mut expected = slot.clone();
                expected.options.retain(|option| &option.id != target);
                for (order, option) in expected.options.iter_mut().enumerate() {
                    option.order = order;
                }
                assert_eq!(
                    inspect_slots(&removed).unwrap(),
                    (vec![expected.clone()], vec![])
                );
                let reread =
                    HwpxPackage::from_bytes(&removed.to_bytes().unwrap(), PackageLimits::default())
                        .unwrap();
                assert_eq!(inspect_slots(&reread).unwrap(), (vec![expected], vec![]));
            }
        }
        assert_slot_local_membership();
        assert_option_order_after_removal();
        assert_canonical_resave();
    }

    fn assert_canonical_resave() {
        let canonical = native("slots/canonical.hwpx");
        let resaved = native("slots/canonical-resaved.hwpx");
        assert_ne!(canonical, resaved);
        let expected = inspect_slots(&canonical).unwrap();
        assert!(expected.1.is_empty());
        assert_eq!(expected.0.len(), 1);
        assert_eq!(expected.0[0].options.len(), 2);
        for (package, edited_text) in [(&canonical, "AAA"), (&resaved, "AAX")] {
            let section = &package
                .entries
                .iter()
                .find(|entry| entry.name == SECTION)
                .unwrap()
                .data;
            assert!(String::from_utf8_lossy(section).contains(edited_text));
        }
        assert_eq!(inspect_slots(&resaved).unwrap(), expected);
        let mut generated = native("structural_range_s0/R5-nested.hwpx");
        add_tag(
            &mut generated,
            "S0_SLOT",
            &serialize_slot_metatag(&expected.0[0]).unwrap(),
        );
        for (name, option) in ["S0_OPT_A", "S0_OPT_B"].iter().zip(&expected.0[0].options) {
            add_tag(
                &mut generated,
                name,
                &serialize_slot_option_metatag(option).unwrap(),
            );
        }
        assert_eq!(inspect_slots(&generated).unwrap(), expected);
        for package in [&canonical, &resaved, &generated] {
            assert!(
                crate::schema::extract_schema(package)
                    .unwrap()
                    .field_names()
                    .is_empty()
            );
        }
    }

    #[test]
    fn contradictory_pair_lifecycles_and_mutation_handles_are_rejected() {
        let package = plain_ancestor();
        let original = scan_structural_boundaries(&package);
        let regions = resolve_bookmark_topology(&package).unwrap();
        assert!(match_region_handles(&original, regions.clone()).is_ok());
        let mut reversed = regions.clone();
        reversed.reverse();
        assert!(
            match_region_handles(&original, reversed)
                .unwrap_err()
                .0
                .contains("order disagree")
        );
        assert!(
            match_region_handles(&original, vec![])
                .unwrap_err()
                .0
                .contains("resolver disagree")
        );
        for violation in ["open", "reuse", "wrong-end", "non-lifo"] {
            let mut scan = original.clone();
            let events = &mut scan.entries[0].events;
            let expected = match violation {
                "open" => {
                    events.pop();
                    "open pairs"
                }
                "reuse" => {
                    events.insert(1, events[0].clone());
                    "pair reused"
                }
                "wrong-end" => {
                    let last = events.last_mut().unwrap();
                    *last = BoundaryEvent::FieldEnd {
                        pair: last.pair().clone(),
                        order: last.order(),
                    };
                    "end contradicts begin"
                }
                "non-lifo" => {
                    let end = events.len() - 1;
                    events.swap(end, end - 1);
                    "end contradicts usable topology"
                }
                _ => unreachable!(),
            };
            assert!(
                inspect_product_bookmarks(&scan)
                    .unwrap_err()
                    .0
                    .contains(expected)
            );
        }
        let option = SlotOption {
            id: "option".into(),
            label: None,
            order: 0,
        };
        let mut scan = scan_structural_boundaries(&tagged_package(
            &[serialize_slot_option_metatag(&option).unwrap()],
            None,
        ));
        scan.entries[0].field_pairing_usable = false;
        scan.entries[0].bookmark_topology_usable = false;
        scan.diagnostics
            .push(hwpx_core::structural_boundary::StructuralDiagnostic {
                entry: Some(SECTION.into()),
                kind: StructuralDiagnosticKind::FieldOrphanEnd,
                order: None,
                detail: String::new(),
            });
        let inspection = inspect_product_bookmarks(&scan).unwrap();
        assert_eq!(
            diagnostic_kinds(&inspection.diagnostics),
            BTreeSet::from(["bookmark-resolve-failed"])
        );
        assert_eq!(
            inspection.observations[0].scope_role,
            ProductScopeRole::InvalidProduct
        );
        assert!(!inspection.observations[0].scope_usable);
        assert!(inspection.observations[0].owning_slot_pair.is_none());
    }

    fn assert_option_order_after_removal() {
        let body = [
            "{{#항목 slot 슬롯 라벨}}",
            "{{#선택 a A 라벨}}",
            "A",
            "{{/선택}}",
            "{{#선택 b B 라벨}}",
            "B",
            "{{/선택}}",
            "{{#선택 c C 라벨}}",
            "C",
            "{{/선택}}",
            "{{/항목}}",
            "OUT",
        ]
        .iter()
        .map(|text| format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"))
        .collect::<String>();
        let mut original = package(&body);
        assert!(
            crate::hwpx_structure_ops::compile_structure(&mut original)
                .unwrap()
                .modified
        );
        let before = inspect_slots(&original).unwrap().0;
        for target in ["a", "b", "c"] {
            let mut package = original.clone();
            crate::hwpx_structure_ops::remove_slot_option(&mut package, "slot", target).unwrap();
            let mut expected = before.clone();
            expected[0].options.retain(|option| option.id != target);
            for (order, option) in expected[0].options.iter_mut().enumerate() {
                option.order = order;
            }
            assert_eq!(inspect_slots(&package).unwrap(), (expected.clone(), vec![]));
            let reread =
                HwpxPackage::from_bytes(&package.to_bytes().unwrap(), PackageLimits::default())
                    .unwrap();
            assert_eq!(inspect_slots(&reread).unwrap(), (expected, vec![]));
        }
    }

    fn assert_slot_local_membership() {
        let body = [
            "{{#항목 z_slot}}",
            "{{#선택 same}}",
            "B",
            "{{/선택}}",
            "{{/항목}}",
            "{{#항목 a_slot}}",
            "{{#선택 same}}",
            "E",
            "{{/선택}}",
            "{{/항목}}",
            "OUT",
        ]
        .iter()
        .map(|text| format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"))
        .collect::<String>();
        let mut package = package(&body);
        assert!(
            crate::hwpx_structure_ops::compile_structure(&mut package)
                .unwrap()
                .modified
        );
        let plain = create_bookmark_region(&mut package, SECTION, 2, 2, "PLAIN", None).unwrap();
        append_bookmark_metatag(&mut package, &plain, "{\"vendor\":1}").unwrap();
        let scan = scan_structural_boundaries(&package);
        let inspection = inspect_product_bookmarks(&scan).unwrap();
        assert!(inspection.diagnostics.is_empty());
        let begins: Vec<_> = scan
            .entries
            .iter()
            .flat_map(|entry| &entry.events)
            .filter(|event| matches!(event, BoundaryEvent::BookmarkBegin { .. }))
            .map(BoundaryEvent::pair)
            .collect();
        assert_eq!(
            inspection
                .observations
                .iter()
                .map(|item| &item.pair)
                .collect::<Vec<_>>(),
            begins
        );
        let [z_slot, z_option, a_slot, a_option, plain] = inspection.observations.as_slice() else {
            panic!("missing native observations")
        };
        assert_eq!(z_option.owning_slot_pair.as_ref(), Some(&z_slot.pair));
        assert_eq!(a_option.owning_slot_pair.as_ref(), Some(&a_slot.pair));
        assert_ne!(z_option.owning_slot_pair, a_option.owning_slot_pair);
        assert_eq!(plain.classification, ProductClassification::NonProduct);
        assert_eq!(plain.scope_role, ProductScopeRole::None);
        assert!(plain.owning_slot_pair.is_none());
        let slots = inspect_slots(&package).unwrap().0;
        assert_eq!(
            slots
                .iter()
                .map(|slot| slot.id.as_str())
                .collect::<Vec<_>>(),
            ["z_slot", "a_slot"]
        );
        assert_eq!(slots[0].options, slots[1].options);
        crate::hwpx_structure_ops::remove_slot_option(&mut package, "z_slot", "same").unwrap();
        let after = inspect_slots(&package).unwrap().0;
        assert!(after[0].options.is_empty());
        assert_eq!(after[1], slots[1]);
        crate::hwpx_structure_ops::remove_slot(&mut package, "z_slot").unwrap();
        assert_eq!(inspect_slots(&package).unwrap().0, slots[1..]);
        assert!(
            resolve_bookmark_topology(&package)
                .unwrap()
                .iter()
                .any(|region| region.name.as_deref() == Some("PLAIN"))
        );
    }

    #[test]
    fn projects_nested_slot_and_option_and_reports_bad_metatag_without_editing() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>A</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>B</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>C</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let section = "Contents/section0.xml";
        let slot = Slot {
            id: "s".into(),
            label: Some("제목".into()),
            options: vec![],
        };
        let outer = create_bookmark_region(&mut package, section, 0, 2, "S", None).unwrap();
        append_bookmark_metatag(
            &mut package,
            &outer,
            &serialize_slot_metatag(&slot).unwrap(),
        )
        .unwrap();
        let outer = resolve_bookmark_topology(&package).unwrap().remove(0);
        let option = SlotOption {
            id: "o".into(),
            order: 0,
            label: None,
        };
        let inner = create_bookmark_region(&mut package, section, 1, 1, "O", Some(&outer)).unwrap();
        append_bookmark_metatag(
            &mut package,
            &inner,
            &serialize_slot_option_metatag(&option).unwrap(),
        )
        .unwrap();
        let before = package.clone();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert_eq!(package, before);
        assert!(snapshot.diagnostics.is_empty());
        assert_eq!(snapshot.slots.len(), 1);
        assert_eq!(snapshot.slots[0].id, "s");
        assert_eq!(snapshot.slots[0].options, [option]);
        assert!(snapshot.slot_regions.contains_key("s"));
        assert!(
            snapshot
                .option_regions
                .contains_key(&("s".into(), "o".into()))
        );

        let inner = resolve_bookmark_topology(&package).unwrap().remove(1);
        append_bookmark_metatag(&mut package, &inner, "not-json").unwrap();
        let bad = inspect_slot_regions(&package).unwrap();
        assert!(
            bad.diagnostics
                .iter()
                .any(|item| item.kind == "malformed-json")
        );
        assert!(bad.slot_regions.is_empty());

        // An option in a different XML entry cannot inherit a Slot from this entry.
        let mut separate_entry = before.clone();
        let section = "Contents/section1.xml";
        separate_entry.entries.push(PackageEntry {
            name: section.into(),
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>별도 본문</hp:t></hp:run></hp:p></hs:sec>").into_bytes(),
            stored: false,
        });
        let orphan =
            create_bookmark_region(&mut separate_entry, section, 0, 0, "orphan", None).unwrap();
        append_bookmark_metatag(
            &mut separate_entry,
            &orphan,
            &serialize_slot_option_metatag(&SlotOption {
                id: "separate".into(),
                order: 0,
                label: None,
            })
            .unwrap(),
        )
        .unwrap();
        let snapshot = inspect_slot_regions(&separate_entry).unwrap();
        assert!(
            snapshot
                .diagnostics
                .iter()
                .any(|item| item.kind == "orphan-option")
        );
        assert!(snapshot.slot_regions.is_empty() && snapshot.option_regions.is_empty());
        let before = separate_entry.clone();
        assert!(crate::hwpx_structure_ops::decompile_slot(&mut separate_entry, "s").is_err());
        assert_eq!(separate_entry, before);
    }
}
