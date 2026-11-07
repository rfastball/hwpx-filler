//! Product field policy over the snapshot-bound HWPX format kernel.

use hwpx_core::native_admission::{
    EntryFieldScan, FieldFillEffect, FieldFillEffectKind, apply_field_fill, canonical_field_value,
    inspect_native_capabilities, scan_entry_field_begins, try_apply_simple_field_fill_batch,
};
use hwpx_core::package::HwpxPackage;
use hwpx_core::structural_boundary::{
    BoundaryEvent, BoundaryPairRef, StructuralBoundaryScan, StructuralDiagnosticKind,
    scan_structural_boundaries,
};
use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldError(pub String);

impl fmt::Display for FieldError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl Error for FieldError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FillNoteKind {
    InlineStripped,
    SlotSynthesized,
    OccurrenceUnfillable,
}

impl FillNoteKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::InlineStripped => "inline_stripped",
            Self::SlotSynthesized => "slot_synthesized",
            Self::OccurrenceUnfillable => "occurrence_unfillable",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FillNote {
    pub field: String,
    pub kind: FillNoteKind,
    pub detail: Vec<String>,
}

fn fail(message: impl Into<String>) -> FieldError {
    FieldError(message.into())
}

pub(crate) fn python_whitespace(ch: char) -> bool {
    ch.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&ch)
}

/// Collapse Python `str.split()` whitespace without changing other characters.
pub fn collapse_field_id(raw: &str) -> Option<String> {
    let collapsed = raw
        .split(python_whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    (!collapsed.is_empty()).then_some(collapsed)
}

/// Remove one enclosing token layer, after collapsing whitespace.
pub fn normalize_field_id(raw: &str) -> Option<String> {
    let collapsed = collapse_field_id(raw)?;
    if collapsed.starts_with("{{") && collapsed.ends_with("}}") {
        collapse_field_id(&collapsed[2..collapsed.len() - 2])
    } else {
        Some(collapsed)
    }
}

pub fn is_fill_target_field_type(field_type: Option<&str>) -> bool {
    field_type != Some("HYPERLINK")
}

#[derive(Clone)]
struct Candidate {
    ordinal: usize,
    pair: BoundaryPairRef,
    raw_name: Option<String>,
    field_type: Option<String>,
}

impl Candidate {
    fn field_id(&self) -> Option<String> {
        product_id(self.raw_name.as_deref(), self.field_type.as_deref())
    }
}

fn product_id(raw_name: Option<&str>, field_type: Option<&str>) -> Option<String> {
    is_fill_target_field_type(field_type)
        .then(|| raw_name.and_then(normalize_field_id))
        .flatten()
}

fn observe_entry(package: &HwpxPackage, entry: &str) -> Result<EntryFieldScan, FieldError> {
    let observed =
        scan_entry_field_begins(package, entry).map_err(|error| fail(error.to_string()))?;
    if !observed.pairing_usable() {
        return Err(fail(format!(
            "unusable field pairing in {entry}: {:?}",
            observed.diagnostics
        )));
    }
    Ok(observed)
}

fn observed_ids(observed: &EntryFieldScan) -> impl Iterator<Item = String> + '_ {
    observed
        .fields
        .iter()
        .filter_map(|field| product_id(field.raw_name.as_deref(), field.field_type.as_deref()))
}

fn candidates(scan: &StructuralBoundaryScan, entry: Option<&str>) -> Vec<Candidate> {
    let mut result = Vec::new();
    for part in &scan.entries {
        if entry.is_some_and(|wanted| wanted != part.entry) {
            continue;
        }
        let mut ordinal = 0;
        for event in &part.events {
            if let BoundaryEvent::FieldBegin {
                pair,
                raw_name,
                field_type,
                ..
            } = event
            {
                result.push(Candidate {
                    ordinal,
                    pair: pair.clone(),
                    raw_name: raw_name.clone(),
                    field_type: field_type.clone(),
                });
                ordinal += 1;
            }
        }
    }
    result
}

fn pairing_ok(scan: &StructuralBoundaryScan, entry: &str) -> Result<(), FieldError> {
    let part = scan
        .entries
        .iter()
        .find(|part| part.entry == entry)
        .ok_or_else(|| fail(format!("missing or unsupported content XML entry: {entry}")))?;
    if part.field_pairing_usable {
        return Ok(());
    }
    let details: Vec<_> = scan
        .diagnostics
        .iter()
        .filter(|item| item.entry.as_deref() == Some(entry))
        .map(|item| item.kind.as_str())
        .collect();
    Err(fail(format!(
        "unusable field pairing in {entry}: {}",
        details.join(", ")
    )))
}

fn scan_entry(package: &HwpxPackage, entry: &str) -> Result<StructuralBoundaryScan, FieldError> {
    let scan = scan_structural_boundaries(package);
    pairing_ok(&scan, entry)?;
    Ok(scan)
}

fn scan_package(package: &HwpxPackage) -> Result<StructuralBoundaryScan, FieldError> {
    let scan = scan_structural_boundaries(package);
    let mut unsupported = Vec::new();
    for diagnostic in &scan.diagnostics {
        if diagnostic.kind != StructuralDiagnosticKind::UnsupportedContentEntry {
            continue;
        }
        let entry = diagnostic
            .entry
            .as_deref()
            .ok_or_else(|| fail("unsupported part without entry"))?;
        let observed = observe_entry(package, entry)?;
        if observed_ids(&observed).next().is_some() {
            unsupported.push(entry.to_owned());
        }
    }
    if !unsupported.is_empty() {
        unsupported.sort();
        return Err(fail(format!(
            "지원하지 않는 필드 XML 파트: {}",
            unsupported.join(", ")
        )));
    }
    for entry in &scan.entries {
        observe_entry(package, &entry.entry)?;
    }
    Ok(scan)
}

/// Supported field parts in section, header, footer and numeric order.
pub fn field_xml_names(package: &HwpxPackage) -> Result<Vec<String>, FieldError> {
    Ok(scan_package(package)?
        .entries
        .into_iter()
        .map(|entry| entry.entry)
        .collect())
}

/// Opportunistic native batch for independent plain text slots. A false result
/// leaves the package untouched so the regular per-occurrence path retains its
/// admission diagnostics and effects for complex XML.
/// Groups each request's matching occurrences by content entry, or `None` if
/// any requested field has no match anywhere in the package.
fn group_requests(
    scan: &StructuralBoundaryScan,
    requests: &[(String, String)],
) -> Option<HashMap<String, Vec<(BoundaryPairRef, String)>>> {
    let mut grouped = HashMap::<String, Vec<(BoundaryPairRef, String)>>::new();
    for (field, value) in requests {
        let mut found = false;
        for entry in &scan.entries {
            let matches = matching(candidates(scan, Some(&entry.entry)), field);
            if !matches.is_empty() {
                found = true;
                grouped
                    .entry(entry.entry.clone())
                    .or_default()
                    .extend(matches.into_iter().map(|item| (item.pair, value.clone())));
            }
        }
        if !found {
            return None;
        }
    }
    Some(grouped)
}
/// Trials the batch fill per entry and collects the resulting bytes, or
/// `None` if any entry's trial fill is rejected or disappears.
fn apply_grouped_updates(
    package: &HwpxPackage,
    scan: &StructuralBoundaryScan,
    grouped: &HashMap<String, Vec<(BoundaryPairRef, String)>>,
) -> Option<Vec<(String, Vec<u8>)>> {
    let mut updates = Vec::new();
    for entry in &scan.entries {
        let Some(fills) = grouped.get(&entry.entry) else {
            continue;
        };
        let mut trial = package.clone();
        if !matches!(
            try_apply_simple_field_fill_batch(&mut trial, scan, &entry.entry, fills),
            Ok(Some(()))
        ) {
            return None;
        }
        let bytes = trial
            .entries
            .iter()
            .find(|item| item.name == entry.entry)
            .map(|item| item.data.clone())?;
        updates.push((entry.entry.clone(), bytes));
    }
    Some(updates)
}
pub(crate) fn try_fill_simple_batch(
    package: &mut HwpxPackage,
    requests: &[(String, String)],
) -> bool {
    let Ok(scan) = scan_package(package) else {
        return false;
    };
    let Some(grouped) = group_requests(&scan, requests) else {
        return false;
    };
    let Some(updates) = apply_grouped_updates(package, &scan, &grouped) else {
        return false;
    };
    for (name, bytes) in updates {
        package
            .entries
            .iter_mut()
            .find(|item| item.name == name)
            .expect("scanned entry must remain in package")
            .data = bytes;
    }
    true
}

pub fn required_fields(package: &HwpxPackage) -> Result<Vec<String>, FieldError> {
    let scan = scan_package(package)?;
    let mut seen = HashSet::new();
    let mut names = Vec::new();
    for entry in &scan.entries {
        let observed = observe_entry(package, &entry.entry)?;
        names.extend(observed_ids(&observed).filter(|id| seen.insert(id.clone())));
    }
    Ok(names)
}

pub fn field_values(package: &HwpxPackage) -> Result<Vec<(String, String)>, FieldError> {
    let scan = scan_package(package)?;
    let mut values = Vec::new();
    for entry in &scan.entries {
        let observed = observe_entry(package, &entry.entry)?;
        values.extend(observed.fields.into_iter().filter_map(|field| {
            product_id(field.raw_name.as_deref(), field.field_type.as_deref())
                .map(|id| (id, field.value.text))
        }));
    }
    Ok(values)
}

/// First value wins when the same normalized ID occurs in several parts.
pub fn read_fields(package: &HwpxPackage) -> Result<Vec<(String, String)>, FieldError> {
    let mut seen = HashSet::new();
    Ok(field_values(package)?
        .into_iter()
        .filter(|(id, _)| seen.insert(id.clone()))
        .collect())
}

fn push_note(notes: &mut Vec<FillNote>, note: FillNote) {
    if !notes.contains(&note) {
        notes.push(note);
    }
}

fn note_from_effect(field: &str, effect: &FieldFillEffect) -> Option<FillNote> {
    let kind = match effect.kind {
        FieldFillEffectKind::RemoveInline => FillNoteKind::InlineStripped,
        FieldFillEffectKind::SynthesizeSlot => FillNoteKind::SlotSynthesized,
        FieldFillEffectKind::NormalizeFragments => return None,
    };
    Some(FillNote {
        field: field.to_owned(),
        kind,
        detail: effect.detail.clone(),
    })
}

fn precheck_for(
    package: &HwpxPackage,
    scan: &StructuralBoundaryScan,
    entry: Option<&str>,
) -> Result<Vec<FillNote>, FieldError> {
    let inspection =
        inspect_native_capabilities(package, scan).map_err(|error| fail(error.to_string()))?;
    let mut notes = Vec::new();
    for candidate in candidates(scan, entry) {
        let Some(field) = candidate.field_id() else {
            continue;
        };
        let observation = inspection
            .field_fills
            .iter()
            .find(|item| item.pair == candidate.pair)
            .ok_or_else(|| fail("field capability observation missing"))?;
        if !observation.blockers.is_empty() {
            push_note(
                &mut notes,
                FillNote {
                    field,
                    kind: FillNoteKind::OccurrenceUnfillable,
                    detail: Vec::new(),
                },
            );
            continue;
        }
        for effect in &observation.supported_effects {
            if let Some(note) = note_from_effect(&field, effect) {
                push_note(&mut notes, note);
            }
        }
    }
    Ok(notes)
}

pub fn fill_precheck(package: &HwpxPackage) -> Result<Vec<FillNote>, FieldError> {
    let scan = scan_package(package)?;
    for entry in &scan.entries {
        if observed_ids(&observe_entry(package, &entry.entry)?)
            .next()
            .is_some()
        {
            pairing_ok(&scan, &entry.entry)?;
        }
    }
    precheck_for(package, &scan, None)
}

fn requested_target(ids: &[String], requested: &str) -> Option<String> {
    let collapsed = collapse_field_id(requested)?;
    if ids.contains(&collapsed) {
        Some(collapsed)
    } else {
        normalize_field_id(requested)
    }
}

fn matching(items: Vec<Candidate>, requested: &str) -> Vec<Candidate> {
    let ids: Vec<_> = items.iter().filter_map(Candidate::field_id).collect();
    let Some(target) = requested_target(&ids, requested) else {
        return Vec::new();
    };
    items
        .into_iter()
        .filter(|item| item.field_id().as_deref() == Some(&target))
        .collect()
}

/// One content XML entry's product field view. Changes land in the borrowed package.
///
/// Inventory and exact reads accept any XML shape supported by the ordinary-field resolver.
/// Mutation requires the stricter native section envelope enforced by `hwpx-core`.
pub struct FieldDocument<'a> {
    package: &'a mut HwpxPackage,
    entry: String,
    modified: bool,
    notes: Vec<FillNote>,
}

impl<'a> FieldDocument<'a> {
    pub fn new(package: &'a mut HwpxPackage, entry: &str) -> Result<Self, FieldError> {
        observe_entry(package, entry)?;
        Ok(Self {
            package,
            entry: entry.to_owned(),
            modified: false,
            notes: Vec::new(),
        })
    }

    pub fn modified(&self) -> bool {
        self.modified
    }
    pub fn notes(&self) -> &[FillNote] {
        &self.notes
    }

    pub fn required_fields(&self) -> Result<Vec<String>, FieldError> {
        let observed = observe_entry(self.package, &self.entry)?;
        let mut seen = HashSet::new();
        Ok(observed_ids(&observed)
            .filter(|id| seen.insert(id.clone()))
            .collect())
    }

    pub fn field_values(&self) -> Result<Vec<(String, String)>, FieldError> {
        let observed = observe_entry(self.package, &self.entry)?;
        Ok(observed
            .fields
            .into_iter()
            .filter_map(|field| {
                product_id(field.raw_name.as_deref(), field.field_type.as_deref())
                    .map(|id| (id, field.value.text))
            })
            .collect())
    }

    pub fn read_field(&self, requested: &str) -> Result<Option<String>, FieldError> {
        let values = self.field_values()?;
        let ids: Vec<_> = values.iter().map(|(id, _)| id.clone()).collect();
        let Some(target) = requested_target(&ids, requested) else {
            return Ok(None);
        };
        Ok(values
            .into_iter()
            .find(|(id, _)| id == &target)
            .map(|(_, value)| value))
    }

    pub fn precheck(&self) -> Result<Vec<FillNote>, FieldError> {
        if self.required_fields()?.is_empty() {
            return Ok(Vec::new());
        }
        let scan = scan_entry(self.package, &self.entry)?;
        precheck_for(self.package, &scan, Some(&self.entry))
    }

    /// Re-locates one field occurrence by ordinal, verifies it is still the
    /// same occurrence, applies the fill, and records any resulting notes.
    /// Returns whether this occurrence was filled.
    fn fill_occurrence(
        &mut self,
        scan: &mut StructuralBoundaryScan,
        clean: &str,
        canonical: &str,
        index: usize,
        original: Candidate,
    ) -> Result<bool, FieldError> {
        if index > 0 {
            *scan = scan_entry(self.package, &self.entry)?;
        }
        let current = candidates(scan, Some(&self.entry))
            .into_iter()
            .find(|item| item.ordinal == original.ordinal)
            .ok_or_else(|| fail("field occurrence disappeared during fill"))?;
        if current.raw_name != original.raw_name || current.field_type != original.field_type {
            return Err(fail("field occurrence changed during fill"));
        }
        let mutation = apply_field_fill(self.package, scan, &current.pair, canonical)
            .map_err(|error| fail(error.to_string()))?;
        if mutation.filled {
            self.modified |= mutation.modified;
            for effect in &mutation.effects {
                if let Some(note) = note_from_effect(clean, effect) {
                    push_note(&mut self.notes, note);
                }
            }
        }
        Ok(mutation.filled)
    }

    pub fn set_field(&mut self, requested: &str, value: &str) -> Result<bool, FieldError> {
        let fields = self.required_fields()?;
        let Some(target) = requested_target(&fields, requested) else {
            return Ok(false);
        };
        if !fields.contains(&target) {
            return Ok(false);
        }
        let mut scan = scan_entry(self.package, &self.entry)?;
        let targets = matching(candidates(&scan, Some(&self.entry)), requested);
        if targets.is_empty() {
            return Ok(false);
        }
        let clean = targets[0]
            .field_id()
            .ok_or_else(|| fail("matched field has no normalized ID"))?;
        let canonical = canonical_field_value(value).map_err(|error| fail(error.to_string()))?;
        let mut filled = false;
        let mut skipped = false;
        for (index, original) in targets.into_iter().enumerate() {
            if self.fill_occurrence(&mut scan, &clean, &canonical, index, original)? {
                filled = true;
            } else {
                skipped = true;
            }
        }
        if skipped {
            push_note(
                &mut self.notes,
                FillNote {
                    field: clean,
                    kind: FillNoteKind::OccurrenceUnfillable,
                    detail: Vec::new(),
                },
            );
        }
        Ok(filled)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::{MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};

    const SECTION: &str = "Contents/section0.xml";
    const HP: &str = "http://www.hancom.co.kr/hwpml/2011/paragraph";
    const HS: &str = "http://www.hancom.co.kr/hwpml/2011/section";

    fn field(name: &str, kind: Option<&str>, value: &str) -> String {
        let kind = kind.map_or(String::new(), |value| format!(" type='{value}'"));
        format!(
            "<hp:run><hp:ctrl><hp:fieldBegin name='{name}'{kind}/></hp:ctrl></hp:run><hp:run><hp:t>{value}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
        )
    }

    fn section(paragraphs: &[String]) -> Vec<u8> {
        format!(
            "<hs:sec xmlns:hs='{HS}' xmlns:hp='{HP}'>{}</hs:sec>",
            paragraphs
                .iter()
                .map(|body| format!("<hp:p>{body}</hp:p>"))
                .collect::<String>()
        )
        .into_bytes()
    }

    fn package(parts: &[(&str, Vec<u8>)]) -> HwpxPackage {
        let mut entries = vec![PackageEntry {
            name: MIMETYPE_NAME.into(),
            data: MIMETYPE_VALUE.to_vec(),
            stored: true,
        }];
        entries.extend(parts.iter().map(|(name, data)| PackageEntry {
            name: (*name).into(),
            data: data.clone(),
            stored: false,
        }));
        HwpxPackage { entries }
    }

    fn ordinary_fixture() -> serde_json::Value {
        serde_json::from_str(include_str!("../../../tests/fixtures/ordinary_fields.json")).unwrap()
    }

    #[test]
    fn ordinary_grammar_roundtrips_supported_lanes_and_refuses_malformed_pairs() {
        for case in ordinary_fixture()["grammar"].as_array().unwrap() {
            let name = case["name"].as_str().unwrap();
            let entry = case["entry"].as_str().unwrap();
            let mut package =
                package(&[(entry, case["xml"].as_str().unwrap().as_bytes().to_vec())]);
            let before = package.clone();
            let observed = scan_entry_field_begins(&package, entry).unwrap();
            if let Some(kind) = case["unsupported_kind"].as_str() {
                assert!(!observed.pairing_usable(), "{name}");
                assert!(observed.fields.is_empty(), "{name}");
                assert!(
                    observed
                        .diagnostics
                        .iter()
                        .any(|item| item.kind.as_str() == kind),
                    "{name}"
                );
                assert!(FieldDocument::new(&mut package, entry).is_err(), "{name}");
                assert!(crate::schema::extract_schema(&package).is_err(), "{name}");
                assert_eq!(package, before);
                continue;
            }
            assert!(observed.pairing_usable(), "{name}");
            assert_eq!(
                serde_json::json!(
                    observed
                        .fields
                        .iter()
                        .map(|field| &field.raw_name)
                        .collect::<Vec<_>>()
                ),
                case["raw_names"],
                "{name}"
            );
            let ids: Vec<_> = case["raw_names"]
                .as_array()
                .unwrap()
                .iter()
                .map(|raw| normalize_field_id(raw.as_str().unwrap()).unwrap())
                .collect();
            let mut doc = FieldDocument::new(&mut package, entry).unwrap();
            assert_eq!(doc.required_fields().unwrap(), ids, "{name}");
            let mut written = Vec::new();
            for (index, id) in ids.iter().enumerate() {
                assert!(doc.read_field(id).unwrap().is_some(), "{name}");
                if name == "multiple_runs_and_value_fragments" {
                    assert_eq!(
                        doc.read_field(id).unwrap().as_deref(),
                        Some("정보시스템 구축")
                    );
                }
                let value = format!("fixture-{name}-{index}");
                assert!(doc.set_field(id, &value).unwrap(), "{name}");
                assert_eq!(doc.read_field(id).unwrap().as_ref(), Some(&value), "{name}");
                written.push((id.clone(), value));
            }
            let reopened = HwpxPackage::from_bytes(
                &package.to_bytes().unwrap(),
                hwpx_core::package::PackageLimits::default(),
            )
            .unwrap();
            assert_eq!(read_fields(&reopened).unwrap(), written, "{name}");
        }
    }

    #[test]
    fn automatic_fields_stay_visible_to_core_and_outside_product_fill_targets() {
        let fixture = ordinary_fixture();
        let mut package = package(&[(
            SECTION,
            fixture["hyperlinks"].as_str().unwrap().as_bytes().to_vec(),
        )]);
        let before = package.clone();
        let observed = scan_entry_field_begins(&package, SECTION).unwrap();
        assert_eq!(
            observed
                .fields
                .iter()
                .map(|field| (field.raw_name.as_deref(), field.field_type.as_deref()))
                .collect::<Vec<_>>(),
            [
                (Some(""), Some("HYPERLINK")),
                (Some("링크1"), Some("HYPERLINK")),
                (Some("계약명"), None)
            ]
        );
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert_eq!(doc.required_fields().unwrap(), ["계약명"]);
        assert_eq!(
            doc.field_values().unwrap(),
            [("계약명".into(), "기존값".into())]
        );
        assert_eq!(doc.read_field("링크1").unwrap(), None);
        assert!(!doc.set_field("링크1", "overwrite").unwrap());
        assert!(doc.precheck().unwrap().is_empty());
        assert!(!doc.modified());
        assert_eq!(*doc.package, before);

        let mut package = self::package(&[(
            SECTION,
            fixture["bookmark_in_field"]
                .as_str()
                .unwrap()
                .as_bytes()
                .to_vec(),
        )]);
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert_eq!(doc.required_fields().unwrap(), ["계약명"]);
        assert_eq!(doc.read_field("구조").unwrap(), None);
        assert!(!doc.set_field("구조", "overwrite").unwrap());
        assert_eq!(
            doc.read_field("계약명").unwrap().as_deref(),
            Some("앞중간뒤")
        );
        assert!(doc.set_field("계약명", "새값").unwrap());
        assert_eq!(doc.read_field("계약명").unwrap().as_deref(), Some("새값"));
    }

    #[test]
    fn inline_values_distinguish_noop_rewrite_and_unfillable_content() {
        let xml = section(&[field(
            "F",
            None,
            "A<hp:tab width='1668' leader='0' type='1'/>B",
        )]);
        let mut package = package(&[(SECTION, xml.clone())]);
        assert_eq!(
            hwpx_core::text_extract::full_text(
                &hwpx_core::text_extract::extract_document(&package, None).unwrap()
            ),
            "A\tB"
        );
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert_eq!(doc.read_field("F").unwrap().as_deref(), Some("A\tB"));
        assert!(doc.set_field("F", "A\tB").unwrap());
        assert!(!doc.modified());
        assert_eq!(doc.package.entries[1].data, xml);
        assert!(doc.set_field("F", "AB").unwrap());
        assert!(doc.modified());
        assert!(doc.notes().is_empty());
        assert!(!String::from_utf8_lossy(&doc.package.entries[1].data).contains("hp:tab"));

        for (requested, canonical) in [
            ("가\t나\n다 라", "가\t나\n다 라"),
            ("줄1\r\n줄2\r줄3", "줄1\n줄2\n줄3"),
            ("가\t나", "가\t나"),
        ] {
            let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
            assert!(doc.set_field("F", requested).unwrap());
            assert!(doc.modified());
            assert!(doc.notes().is_empty());
            let saved = doc.package.to_bytes().unwrap();
            let mut reopened =
                HwpxPackage::from_bytes(&saved, hwpx_core::package::PackageLimits::default())
                    .unwrap();
            let before = reopened.clone();
            let mut same = FieldDocument::new(&mut reopened, SECTION).unwrap();
            assert_eq!(same.read_field("F").unwrap().as_deref(), Some(canonical));
            assert!(same.set_field("F", requested).unwrap());
            assert!(!same.modified());
            assert!(same.notes().is_empty());
            assert_eq!(*same.package, before);
        }

        for (inner, value, writable, kind) in [
            (
                "앞<x:unknown xmlns:x='urn:x'>x</x:unknown>뒤",
                "앞뒤",
                false,
                FillNoteKind::OccurrenceUnfillable,
            ),
            (
                "A<hp:insertBegin Id='1' TcId='2'/>B<hp:insertEnd Id='1' TcId='2'/>",
                "AB",
                true,
                FillNoteKind::InlineStripped,
            ),
        ] {
            let xml = section(&[field("F", None, inner)]);
            let mut package = self::package(&[(SECTION, xml.clone())]);
            let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
            assert_eq!(doc.read_field("F").unwrap().as_deref(), Some(value));
            assert_eq!(doc.set_field("F", value).unwrap(), writable);
            assert_eq!(doc.modified(), writable);
            assert_eq!(doc.notes().len(), 1);
            assert_eq!(doc.notes()[0].kind, kind);
            if writable {
                assert_eq!(doc.notes()[0].detail, ["insertBegin", "insertEnd"]);
                assert!(
                    !String::from_utf8_lossy(&doc.package.entries[1].data).contains("hp:insert")
                );
            } else {
                assert_eq!(doc.package.entries[1].data, xml);
                assert!(!doc.set_field("F", "changed").unwrap());
                assert!(!doc.modified());
                assert_eq!(doc.notes().len(), 1);
                assert_eq!(doc.package.entries[1].data, xml);
            }
        }
    }

    #[test]
    fn consecutive_empty_field_fills_preserve_prior_values_and_table_cells() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/inline_field_values.json"
        ))
        .unwrap();
        let body = fixture["empty_fields"].as_str().unwrap();
        let xml = format!("<hs:sec xmlns:hs='{HS}' xmlns:hp='{HP}'>{body}</hs:sec>").into_bytes();
        let mut package = package(&[(SECTION, xml)]);
        let values: Vec<(String, String)> = [
            ("가", "첫째"),
            ("나", "둘\t째"),
            ("다", "셋\n째"),
            ("라", "넷 째"),
        ]
        .into_iter()
        .map(|(name, value)| (name.into(), value.into()))
        .collect();
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        for (name, value) in &values {
            assert!(doc.set_field(name, value).unwrap());
            assert_eq!(doc.read_field(name).unwrap().as_ref(), Some(value));
        }
        assert_eq!(doc.field_values().unwrap(), values);
        assert_eq!(
            doc.notes(),
            values
                .iter()
                .map(|(name, _)| FillNote {
                    field: name.clone(),
                    kind: FillNoteKind::SlotSynthesized,
                    detail: vec![]
                })
                .collect::<Vec<_>>()
        );
        let mut reopened = HwpxPackage::from_bytes(
            &package.to_bytes().unwrap(),
            hwpx_core::package::PackageLimits::default(),
        )
        .unwrap();
        assert_eq!(read_fields(&reopened).unwrap(), values);
        assert_eq!(
            hwpx_core::text_extract::full_text(
                &hwpx_core::text_extract::extract_document(&reopened, None).unwrap()
            ),
            "첫째 사이 둘\t째\n셋\n째\n넷 째"
        );
        let before = reopened.clone();
        let mut again = FieldDocument::new(&mut reopened, SECTION).unwrap();
        for (name, value) in values {
            assert!(again.set_field(&name, &value).unwrap());
        }
        assert!(!again.modified());
        assert!(again.notes().is_empty());
        assert_eq!(*again.package, before);
    }

    #[test]
    fn part_order_hyperlink_filter_and_unsupported_part_policy() {
        let a = section(&[field("late", None, "10")]);
        let b = section(&[
            field("early", None, "2"),
            field("legacy", Some("FUTURE_TYPE"), "L"),
        ]);
        let c = section(&[field("header", None, "H")]);
        let d = section(&[field("footer", None, "F")]);
        let hyperlink = section(&[field("link", Some("HYPERLINK"), "URL")]);
        let doc_package = package(&[
            ("Contents/section10.xml", a),
            ("Contents/footer1.xml", d),
            ("Contents/section2.xml", b),
            ("Contents/header1.xml", c),
            ("Contents/header.xml", hyperlink),
        ]);
        assert_eq!(
            required_fields(&doc_package).unwrap(),
            ["early", "legacy", "late", "header", "footer"]
        );
        assert_eq!(
            read_fields(&doc_package).unwrap(),
            [
                ("early".into(), "2".into()),
                ("legacy".into(), "L".into()),
                ("late".into(), "10".into()),
                ("header".into(), "H".into()),
                ("footer".into(), "F".into()),
            ]
        );
        assert_eq!(
            field_xml_names(&doc_package).unwrap(),
            [
                "Contents/section2.xml",
                "Contents/section10.xml",
                "Contents/header1.xml",
                "Contents/footer1.xml"
            ]
        );
        let mut unsupported = doc_package;
        unsupported.entries.last_mut().unwrap().data = section(&[field("active", None, "x")]);
        assert!(
            required_fields(&unsupported)
                .unwrap_err()
                .0
                .contains("지원하지 않는 필드 XML 파트: Contents/header.xml")
        );
        let nested = "<hp:run><hp:ctrl><hp:fieldBegin name='A'/><hp:fieldBegin name='B'/><hp:fieldEnd/><hp:fieldEnd/></hp:ctrl></hp:run>";
        unsupported.entries.last_mut().unwrap().data =
            section(&[field("link", Some("HYPERLINK"), "URL")]);
        unsupported.entries[1].data = section(&[nested.into()]);
        assert!(
            required_fields(&unsupported)
                .unwrap_err()
                .0
                .contains("unusable field pairing")
        );

        let mut atypical = package(&[(SECTION, section(&[field("visible", None, "exact value")]))]);
        let source = String::from_utf8(atypical.entries[1].data.clone()).unwrap();
        atypical.entries[1].data = source
            .replace("</hs:sec>", "<hp:other/></hs:sec>")
            .into_bytes();
        assert_eq!(required_fields(&atypical).unwrap(), ["visible"]);
        assert_eq!(
            read_fields(&atypical).unwrap(),
            [("visible".into(), "exact value".into())]
        );
        let mut doc = FieldDocument::new(&mut atypical, SECTION).unwrap();
        assert_eq!(
            doc.read_field("visible").unwrap(),
            Some("exact value".into())
        );
        assert!(doc.set_field("visible", "changed").is_err());
        assert!(!doc.modified());
        let mut empty = package(&[(SECTION, format!("<hs:sec xmlns:hs='{HS}'/>").into_bytes())]);
        assert!(required_fields(&empty).unwrap().is_empty());
        assert!(fill_precheck(&empty).unwrap().is_empty());
        assert!(
            !FieldDocument::new(&mut empty, SECTION)
                .unwrap()
                .set_field("none", "value")
                .unwrap()
        );
    }

    #[test]
    fn canonical_aliases_blank_requests_and_long_field_text() {
        for (raw, expected) in [
            ("  계약명  ", Some("계약명")),
            ("담당자\t이름", Some("담당자 이름")),
            ("\u{a0}계약명\u{2003}", Some("계약명")),
            (" {{ 계약명 }} ", Some("계약명")),
            ("x{{계약명}}", Some("x{{계약명}}")),
            ("{{{{계약명}}}}", Some("{{계약명}}")),
            ("{{ }}", None),
            ("\u{2003}\t", None),
        ] {
            assert_eq!(normalize_field_id(raw).as_deref(), expected);
        }
        let long = "가".repeat(65);
        let xml = section(&[
            field("{{{{X}}}}", None, &long),
            field("X", None, "plain"),
            field("", None, "unnamed"),
            field("", Some("HYPERLINK"), "link"),
        ]);
        let mut package = package(&[(SECTION, xml)]);
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert_eq!(
            normalize_field_id("  {{ x{{계약명}}\u{00a0}A\tB }}  "),
            Some("x{{계약명}} A B".into())
        );
        assert_eq!(normalize_field_id("{{ }}"), None);
        assert_eq!(collapse_field_id("A\u{001c}B"), Some("A B".into()));
        assert_eq!(doc.required_fields().unwrap(), ["{{X}}", "X"]);
        assert_eq!(doc.read_field("{{X}}").unwrap(), Some(long.clone()));
        assert_eq!(doc.read_field("{{ }}").unwrap(), None);
        assert_eq!(doc.read_field("unknown").unwrap(), None);
        assert!(!doc.set_field("unknown", "unused").unwrap());
        assert!(!doc.set_field("{{ }}", "bad").unwrap());
        assert!(doc.set_field("{{X}}", "nested").unwrap());
        assert_eq!(doc.read_field("{{X}}").unwrap(), Some("nested".into()));
        assert_eq!(doc.read_field("X").unwrap(), Some("plain".into()));
        assert_eq!(
            doc.field_values().unwrap(),
            [
                ("{{X}}".into(), "nested".into()),
                ("X".into(), "plain".into())
            ]
        );
        assert!(doc.set_field("X", "{{X}}").unwrap());
        assert_eq!(doc.read_field("X").unwrap().as_deref(), Some("{{X}}"));

        let fixture = ordinary_fixture();
        let mut normalized = self::package(&[(
            SECTION,
            fixture["normalized_ids"]
                .as_str()
                .unwrap()
                .as_bytes()
                .to_vec(),
        )]);
        let mut doc = FieldDocument::new(&mut normalized, SECTION).unwrap();
        let expected = "x{{계약명}} \"A\" 'B'";
        let nested = "{{중첩}}";
        let requested = " {{ x{{계약명}}\u{a0}\"A\"\t'B' }} ";
        assert_eq!(doc.required_fields().unwrap(), [expected, nested]);
        assert_eq!(doc.read_field(requested).unwrap().as_deref(), Some("구값1"));
        assert!(doc.set_field(requested, "새값").unwrap());
        assert_eq!(doc.read_field(nested).unwrap().as_deref(), Some("중첩구값"));
        assert!(doc.set_field(nested, "중첩새값").unwrap());
        assert_eq!(
            doc.field_values().unwrap(),
            [
                (expected.into(), "새값".into()),
                (expected.into(), "새값".into()),
                (nested.into(), "중첩새값".into())
            ]
        );
        assert_eq!(
            read_fields(&normalized).unwrap(),
            [
                (expected.into(), "새값".into()),
                (nested.into(), "중첩새값".into())
            ]
        );
        let schema = crate::schema::extract_schema(&normalized).unwrap();
        assert_eq!(schema.field_names(), [expected, nested]);
        assert_eq!(schema.fields[0].occurrences, 2);
    }

    #[test]
    fn repeated_fill_notes_noop_and_layout_cache_boundary() {
        let marked = field("계약명", None, "A<hp:markpenBegin/>B<hp:markpenEnd/>")
            .replace("</hp:t>", "</hp:t><hp:t/>");
        let xml = section(&[
            format!("{marked}<hp:linesegarray/>"),
            marked,
            "<hp:run><hp:t>무관 문단</hp:t></hp:run><hp:linesegarray/>".into(),
        ]);
        let mut package = package(&[(SECTION, xml.clone())]);
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert_eq!(
            doc.precheck().unwrap(),
            [FillNote {
                field: "계약명".into(),
                kind: FillNoteKind::InlineStripped,
                detail: vec!["markpenBegin".into(), "markpenEnd".into()]
            }]
        );
        assert!(!doc.modified());
        assert!(doc.set_field("계약명", "AB").unwrap());
        assert!(!doc.modified());
        assert!(doc.notes().is_empty());
        assert_eq!(doc.package.entries[1].data, xml);
        assert!(doc.set_field("계약명", "bad\u{0001}").is_err());
        assert!(!doc.modified());
        assert!(doc.notes().is_empty());
        assert_eq!(doc.package.entries[1].data, xml);
        assert!(doc.set_field("계약명", "새값").unwrap());
        assert!(doc.modified());
        assert_eq!(
            doc.notes(),
            [FillNote {
                field: "계약명".into(),
                kind: FillNoteKind::InlineStripped,
                detail: vec!["markpenBegin".into(), "markpenEnd".into()]
            }]
        );
        assert!(!String::from_utf8_lossy(&doc.package.entries[1].data).contains("linesegarray"));
        assert!(String::from_utf8_lossy(&doc.package.entries[1].data).contains("무관 문단"));
        assert_eq!(
            doc.field_values().unwrap(),
            [
                ("계약명".into(), "새값".into()),
                ("계약명".into(), "새값".into())
            ]
        );
    }

    #[test]
    fn fragmented_values_keep_noop_bytes_and_remove_old_marker_tails() {
        for (inner, value, modified) in [
            (
                "정보</hp:t></hp:run><hp:run><hp:t>시스템",
                "정보시스템",
                false,
            ),
            (
                "V</hp:t></hp:run><hp:run><hp:t><hp:markpenBegin/>FRAG<hp:markpenEnd/>",
                "V",
                true,
            ),
        ] {
            let xml = section(&[field("계약명", None, inner)]);
            let mut package = package(&[(SECTION, xml.clone())]);
            let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
            assert!(doc.set_field("계약명", value).unwrap());
            assert_eq!(doc.read_field("계약명").unwrap().as_deref(), Some(value));
            assert_eq!(doc.modified(), modified);
            if modified {
                assert_eq!(doc.notes()[0].kind, FillNoteKind::InlineStripped);
                assert!(!String::from_utf8_lossy(&doc.package.entries[1].data).contains("FRAG"));
            } else {
                assert!(doc.notes().is_empty());
                assert_eq!(doc.package.entries[1].data, xml);
            }
        }
    }

    #[test]
    fn partially_unfillable_occurrence_is_reported_without_losing_success() {
        let normal = field("계약명", None, "old");
        let degenerate =
            "<hp:run><hp:ctrl><hp:fieldBegin name='계약명'/><hp:fieldEnd/></hp:ctrl></hp:run>";
        let empty = "<hp:run><hp:ctrl><hp:fieldBegin name='빈필드'/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>";
        let marker = field("마커", None, "A<hp:markpenBegin/><hp:markpenEnd/>");
        let xml = section(&[normal, degenerate.into(), empty.into(), marker]);
        let mut package = package(&[(SECTION, xml.clone())]);
        let repeated = self::package(&[(SECTION, xml.clone()), ("Contents/section1.xml", xml)]);
        let before = repeated.clone();
        let precheck = fill_precheck(&repeated).unwrap();
        assert_eq!(repeated, before);
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert_eq!(doc.precheck().unwrap(), precheck);
        assert_eq!(
            doc.precheck().unwrap(),
            [
                FillNote {
                    field: "계약명".into(),
                    kind: FillNoteKind::OccurrenceUnfillable,
                    detail: Vec::new()
                },
                FillNote {
                    field: "빈필드".into(),
                    kind: FillNoteKind::SlotSynthesized,
                    detail: Vec::new()
                },
                FillNote {
                    field: "마커".into(),
                    kind: FillNoteKind::InlineStripped,
                    detail: vec!["markpenBegin".into(), "markpenEnd".into()]
                }
            ]
        );
        assert!(doc.set_field("계약명", "new").unwrap());
        assert!(doc.modified());
        assert_eq!(doc.read_field("계약명").unwrap(), Some("new".into()));
        assert!(doc.set_field("빈필드", "created").unwrap());
        assert_eq!(doc.read_field("빈필드").unwrap(), Some("created".into()));
        assert!(doc.set_field("마커", "new-marker").unwrap());
        assert_eq!(doc.notes(), precheck);

        let mut package = self::package(&[(SECTION, section(&[degenerate.into()]))]);
        let before = package.clone();
        let mut doc = FieldDocument::new(&mut package, SECTION).unwrap();
        assert!(!doc.set_field("계약명", "cannot-fill").unwrap());
        assert!(!doc.modified());
        assert_eq!(
            doc.notes(),
            [FillNote {
                field: "계약명".into(),
                kind: FillNoteKind::OccurrenceUnfillable,
                detail: vec![]
            }]
        );
        assert_eq!(*doc.package, before);
    }
}
