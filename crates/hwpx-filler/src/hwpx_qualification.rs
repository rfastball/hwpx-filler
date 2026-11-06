//! One-pass read-only HWPX qualification from native structural observations.

use crate::execution_structure::{
    ContentEntry, ENVELOPE_CAPABILITY_KEYS, ExecutionStructureInput, ExecutionTemplateStructure,
    FieldOccurrence, LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA, OptionRegionObservation,
    RESOLVER_STABILITY_KEYS, SlotRegionObservation, TemplateOption, TemplateSlot,
    TemplateStructure, build_execution_structure,
};
use crate::fields::{is_fill_target_field_type, normalize_field_id};
use crate::hwpx_product_inspection::{
    ProductBookmarkInspection, ProductClassification, ProductScopeObservation, ProductScopeRole,
    inspect_product_bookmarks,
};
use crate::text_render::python_repr;
use hwpx_core::native_admission::{
    BookmarkRemovalBlocker, BookmarkRemovalObservation, FieldFillBlocker, FieldFillObservation,
    inspect_native_capabilities,
};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_core::structural_boundary::{
    BoundaryEvent, BoundaryPairRef, ContentEntryKind, StructuralBoundaryScan,
    StructuralDiagnosticKind, StructuralEntryScan, scan_structural_boundaries,
};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QualificationDiagnostic {
    pub kind: String,
    pub message: String,
}
#[derive(Clone, Debug)]
pub struct QualificationInspection {
    pub structure: Option<TemplateStructure>,
    pub diagnostics: Vec<QualificationDiagnostic>,
    pub execution_structure: Option<ExecutionTemplateStructure>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum QualificationInspectError {
    Contract(String),
    Inspection(String),
}
impl fmt::Display for QualificationInspectError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Contract(detail) | Self::Inspection(detail) => f.write_str(detail),
        }
    }
}
impl std::error::Error for QualificationInspectError {}
fn contract(message: impl Into<String>) -> QualificationInspectError {
    QualificationInspectError::Contract(message.into())
}
fn diagnostic(kind: &str, message: String) -> QualificationDiagnostic {
    QualificationDiagnostic {
        kind: kind.into(),
        message,
    }
}
fn repr(value: Option<&str>) -> String {
    value.map_or_else(
        || "None".into(),
        |name| python_repr(&Value::String(name.into())),
    )
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Owner {
    Root,
    Slot(BoundaryPairRef),
    Option(BoundaryPairRef),
    Unresolved,
}
fn owner(
    topology: bool,
    invalid_depth: usize,
    slot: &Option<BoundaryPairRef>,
    option: &Option<BoundaryPairRef>,
) -> Owner {
    if !topology || invalid_depth != 0 {
        Owner::Unresolved
    } else if let Some(pair) = option {
        Owner::Option(pair.clone())
    } else if let Some(pair) = slot {
        Owner::Slot(pair.clone())
    } else {
        Owner::Root
    }
}
struct OpenField {
    pair: BoundaryPairRef,
    raw_name: Option<String>,
    field_id: Option<String>,
    owner: Owner,
    fill: FieldFillObservation,
    structural_order: i64,
    fill_target: bool,
    ordinal: usize,
    text_preview: String,
    product_boundary_opened: bool,
}
fn fill_blockers(blockers: &[FieldFillBlocker]) -> String {
    blockers
        .iter()
        .map(|item| {
            let mut text = item.kind.as_str().to_owned();
            if !item.detail.is_empty() {
                text.push_str(": ");
                text.push_str(&item.detail.join(", "));
            }
            text
        })
        .collect::<Vec<_>>()
        .join("; ")
}
fn removal_blockers(blockers: &[BookmarkRemovalBlocker]) -> String {
    blockers
        .iter()
        .map(|item| {
            let mut text = item.kind.as_str().to_owned();
            if !item.detail.is_empty() {
                text.push_str(": ");
                text.push_str(&item.detail.join(", "));
            }
            text
        })
        .collect::<Vec<_>>()
        .join("; ")
}
fn field_diagnostic(kind: StructuralDiagnosticKind) -> bool {
    kind.as_str().starts_with("field-")
}
fn product_consistent(item: &ProductScopeObservation, diagnostics_present: bool) -> bool {
    match item.scope_role {
        ProductScopeRole::InvalidProduct => invalid_product_consistent(item, diagnostics_present),
        ProductScopeRole::None => {
            item.scope_usable
                && item.classification == ProductClassification::NonProduct
                && item.kind.is_none()
                && item.product_id.is_none()
                && item.owning_slot_pair.is_none()
        }
        ProductScopeRole::Slot => {
            usable_product_consistent(item, "slot", false, diagnostics_present)
        }
        ProductScopeRole::Option => {
            usable_product_consistent(item, "slot_option", true, diagnostics_present)
        }
    }
}

fn invalid_product_consistent(item: &ProductScopeObservation, diagnostics_present: bool) -> bool {
    let identity_valid = if item.classification == ProductClassification::KnownProduct {
        matches!(item.kind.as_deref(), Some("slot" | "slot_option"))
    } else {
        item.kind.is_none() && item.product_id.is_none()
    };
    !item.scope_usable
        && diagnostics_present
        && identity_valid
        && (item.owning_slot_pair.is_none()
            || (item.classification == ProductClassification::KnownProduct
                && item.kind.as_deref() == Some("slot_option")))
}

fn usable_product_consistent(
    item: &ProductScopeObservation,
    kind: &str,
    needs_owner: bool,
    diagnostics_present: bool,
) -> bool {
    item.scope_usable
        && item.classification == ProductClassification::KnownProduct
        && item.kind.as_deref() == Some(kind)
        && item.owning_slot_pair.is_some() == needs_owner
        && (item.product_id.is_some() || diagnostics_present)
}

#[derive(Default)]
struct EntryScope {
    slot: Option<BoundaryPairRef>,
    option: Option<BoundaryPairRef>,
    invalid_depth: usize,
    open: Option<OpenField>,
    field_ordinal: usize,
}

impl EntryScope {
    fn ensure_closed(&self, entry: &str) -> Result<(), QualificationInspectError> {
        if self.open.is_some()
            || self.slot.is_some()
            || self.option.is_some()
            || self.invalid_depth != 0
        {
            return Err(contract(format!(
                "{entry}: analyzer ended with impossible state"
            )));
        }
        Ok(())
    }
}

struct Qualifier<'a> {
    scan: &'a StructuralBoundaryScan,
    products: &'a ProductBookmarkInspection,
    fills: &'a [FieldFillObservation],
    removals: &'a [BookmarkRemovalObservation],
    fill_at: usize,
    removal_at: usize,
    product_at: usize,
    diagnostics: Vec<QualificationDiagnostic>,
    root_fields: Vec<String>,
    slots: Vec<BoundaryPairRef>,
    options: HashMap<BoundaryPairRef, Vec<BoundaryPairRef>>,
    shared_fields: HashMap<BoundaryPairRef, Vec<String>>,
    option_fields: HashMap<BoundaryPairRef, Vec<String>>,
    slot_spans: HashMap<BoundaryPairRef, (i64, i64, String)>,
    option_spans: HashMap<BoundaryPairRef, (i64, i64, String)>,
    occurrences: Vec<(String, Owner, String, i64)>,
    kinds: HashMap<String, ContentEntryKind>,
}
impl<'a> Qualifier<'a> {
    fn new(
        scan: &'a StructuralBoundaryScan,
        products: &'a ProductBookmarkInspection,
        fills: &'a [FieldFillObservation],
        removals: &'a [BookmarkRemovalObservation],
    ) -> Result<Self, QualificationInspectError> {
        if products
            .observations
            .iter()
            .any(|item| !product_consistent(item, !products.diagnostics.is_empty()))
        {
            return Err(contract("product scope observation conflicts"));
        }
        let mut diagnostics = products
            .diagnostics
            .iter()
            .map(|item| diagnostic(&item.kind, item.message.clone()))
            .collect::<Vec<_>>();
        diagnostics.extend(
            scan.diagnostics
                .iter()
                .filter(|item| field_diagnostic(item.kind))
                .map(|item| {
                    diagnostic(
                        item.kind.as_str(),
                        format!(
                            "{}: {}",
                            item.entry.as_deref().unwrap_or("None"),
                            item.kind.as_str()
                        ),
                    )
                }),
        );
        Ok(Self {
            scan,
            products,
            fills,
            removals,
            fill_at: 0,
            removal_at: 0,
            product_at: 0,
            diagnostics,
            root_fields: Vec::new(),
            slots: Vec::new(),
            options: HashMap::new(),
            shared_fields: HashMap::new(),
            option_fields: HashMap::new(),
            slot_spans: HashMap::new(),
            option_spans: HashMap::new(),
            occurrences: Vec::new(),
            kinds: HashMap::new(),
        })
    }
    fn fill(
        &mut self,
        pair: &BoundaryPairRef,
        entry: &str,
    ) -> Result<FieldFillObservation, QualificationInspectError> {
        let item = self
            .fills
            .get(self.fill_at)
            .filter(|item| &item.pair == pair)
            .ok_or_else(|| contract(format!("{entry}: Field fill observation order mismatch")))?
            .clone();
        self.fill_at += 1;
        Ok(item)
    }
    fn removal(
        &mut self,
        pair: &BoundaryPairRef,
        entry: &str,
    ) -> Result<BookmarkRemovalObservation, QualificationInspectError> {
        let item = self
            .removals
            .get(self.removal_at)
            .filter(|item| &item.pair == pair)
            .ok_or_else(|| {
                contract(format!(
                    "{entry}: BOOKMARK removal observation order mismatch"
                ))
            })?
            .clone();
        self.removal_at += 1;
        Ok(item)
    }
    fn product(
        &mut self,
        pair: &BoundaryPairRef,
        entry: &str,
    ) -> Result<ProductScopeObservation, QualificationInspectError> {
        let item = self
            .products
            .observations
            .get(self.product_at)
            .filter(|item| &item.pair == pair)
            .ok_or_else(|| contract(format!("{entry}: product scope observation order mismatch")))?
            .clone();
        self.product_at += 1;
        if item.entry != entry {
            return Err(contract("product scope entry mismatch"));
        }
        Ok(item)
    }
    fn inspect(mut self) -> Result<QualificationInspection, QualificationInspectError> {
        let mut order = 0_i64;
        for entry in &self.scan.entries {
            self.inspect_entry(entry, &mut order)?;
        }
        if self.fill_at != self.fills.len() {
            return Err(contract("extra Field fill observation"));
        }
        if self.removal_at != self.removals.len() {
            return Err(contract("extra BOOKMARK removal observation"));
        }
        if self.product_at != self.products.observations.len() {
            return Err(contract("extra product scope observation"));
        }
        if !self.diagnostics.is_empty() {
            return Ok(QualificationInspection {
                structure: None,
                diagnostics: self.diagnostics,
                execution_structure: None,
            });
        }
        self.passed()
    }
    fn inspect_entry(
        &mut self,
        entry: &StructuralEntryScan,
        order: &mut i64,
    ) -> Result<(), QualificationInspectError> {
        let mut scope = EntryScope::default();
        self.kinds.insert(entry.entry.clone(), entry.kind);
        for event in &entry.events {
            *order += 1;
            match event {
                BoundaryEvent::FieldBegin {
                    pair,
                    raw_name,
                    field_type,
                    text_preview,
                    ..
                } => {
                    let fill = self.fill(pair, &entry.entry)?;
                    if scope.open.is_some() {
                        return Err(contract(format!(
                            "{}: Field began while another Field was open",
                            entry.entry
                        )));
                    }
                    scope.field_ordinal += 1;
                    scope.open = Some(OpenField {
                        pair: pair.clone(),
                        raw_name: raw_name.clone(),
                        field_id: raw_name.as_deref().and_then(normalize_field_id),
                        owner: owner(
                            entry.bookmark_topology_usable,
                            scope.invalid_depth,
                            &scope.slot,
                            &scope.option,
                        ),
                        fill,
                        structural_order: *order,
                        fill_target: is_fill_target_field_type(field_type.as_deref()),
                        ordinal: scope.field_ordinal,
                        text_preview: text_preview.clone(),
                        product_boundary_opened: false,
                    });
                }
                BoundaryEvent::FieldEnd { pair, .. } => {
                    self.finish_field(entry, &mut scope, pair)?
                }
                BoundaryEvent::BookmarkBegin { pair, .. } => {
                    self.begin_bookmark(entry, &mut scope, pair, *order)?
                }
                BoundaryEvent::BookmarkEnd { pair, .. } => {
                    self.end_bookmark(entry, &mut scope, pair, *order)?
                }
            }
        }
        scope.ensure_closed(&entry.entry)
    }
    fn finish_field(
        &mut self,
        entry: &StructuralEntryScan,
        scope: &mut EntryScope,
        pair: &BoundaryPairRef,
    ) -> Result<(), QualificationInspectError> {
        let field = scope
            .open
            .take()
            .filter(|item| &item.pair == pair)
            .ok_or_else(|| {
                contract(format!("{}: Field end contradicts open Field", entry.entry))
            })?;
        let current = owner(
            entry.bookmark_topology_usable,
            scope.invalid_depth,
            &scope.slot,
            &scope.option,
        );
        let label = repr(field.field_id.as_deref().or(field.raw_name.as_deref()));
        let (kind, message) = if field.owner == Owner::Unresolved || current == Owner::Unresolved {
            (
                "unresolved-field-owner",
                format!("{}: Field {label} owner is unresolved", entry.entry),
            )
        } else if field.owner != current {
            (
                "field-crosses-selection-boundary",
                format!(
                    "{}: Field {label} crosses a selection boundary",
                    entry.entry
                ),
            )
        } else if field.product_boundary_opened {
            (
                "field-contains-selection-boundary",
                format!(
                    "{}: Field {label} contains a selection boundary",
                    entry.entry
                ),
            )
        } else if !field.fill_target {
            return Ok(());
        } else if field.field_id.is_none() {
            let mut where_text = format!("{}번째 필드", field.ordinal);
            if !field.text_preview.is_empty() {
                where_text.push_str(&format!(" '{}'", field.text_preview));
            }
            (
                "invalid-field-id",
                format!(
                    "{}: {where_text}에 이름이 없습니다. 한글에서 그 누름틀에 이름을 지정하거나 필드를 지우세요.",
                    entry.entry
                ),
            )
        } else if !field.fill.fillable() {
            (
                "field-not-fillable",
                format!(
                    "{}: Field {label}: {}",
                    entry.entry,
                    fill_blockers(&field.fill.blockers)
                ),
            )
        } else {
            return self.record_field(entry, field);
        };
        self.diagnostics.push(diagnostic(kind, message));
        Ok(())
    }
    fn record_field(
        &mut self,
        entry: &StructuralEntryScan,
        field: OpenField,
    ) -> Result<(), QualificationInspectError> {
        let id = field
            .field_id
            .ok_or_else(|| contract("missing PASS field id"))?;
        match &field.owner {
            Owner::Root => self.root_fields.push(id.clone()),
            Owner::Slot(pair) => self
                .shared_fields
                .get_mut(pair)
                .ok_or_else(|| contract("missing Slot field owner"))?
                .push(id.clone()),
            Owner::Option(pair) => self
                .option_fields
                .get_mut(pair)
                .ok_or_else(|| contract("missing Option field owner"))?
                .push(id.clone()),
            Owner::Unresolved => unreachable!(),
        }
        self.occurrences
            .push((id, field.owner, entry.entry.clone(), field.structural_order));
        Ok(())
    }
    fn begin_bookmark(
        &mut self,
        entry: &StructuralEntryScan,
        scope: &mut EntryScope,
        pair: &BoundaryPairRef,
        order: i64,
    ) -> Result<(), QualificationInspectError> {
        let product = self.product(pair, &entry.entry)?;
        let removal = self.removal(pair, &entry.entry)?;
        if product.classification == ProductClassification::KnownProduct
            && matches!(product.kind.as_deref(), Some("slot" | "slot_option"))
            && !removal.removable()
        {
            self.diagnostics.push(diagnostic(
                "product-selection-not-removable",
                format!(
                    "{}: {} {}: {}",
                    entry.entry,
                    product.kind.as_deref().unwrap(),
                    repr(product.product_id.as_deref()),
                    removal_blockers(&removal.blockers)
                ),
            ));
        }
        if !entry.bookmark_topology_usable {
            return Ok(());
        }
        if let Some(field) = scope.open.as_mut()
            && product.scope_role != ProductScopeRole::None
        {
            field.product_boundary_opened = true;
        }
        if scope.invalid_depth != 0 && product.scope_role != ProductScopeRole::InvalidProduct {
            return Err(contract(format!(
                "{}: usable product scope inside invalid scope",
                entry.entry
            )));
        }
        self.enter_product_scope(entry, scope, pair, order, &product)
    }
    fn enter_product_scope(
        &mut self,
        entry: &StructuralEntryScan,
        scope: &mut EntryScope,
        pair: &BoundaryPairRef,
        order: i64,
        product: &ProductScopeObservation,
    ) -> Result<(), QualificationInspectError> {
        match product.scope_role {
            ProductScopeRole::None => {}
            ProductScopeRole::InvalidProduct => {
                if product
                    .owning_slot_pair
                    .as_ref()
                    .is_some_and(|pair| scope.slot.as_ref() != Some(pair))
                {
                    return Err(contract(format!(
                        "{}: invalid product owning Slot contradicts current Slot",
                        entry.entry
                    )));
                }
                scope.invalid_depth += 1;
            }
            ProductScopeRole::Slot => {
                if scope.slot.is_some() || scope.option.is_some() {
                    return Err(contract(format!(
                        "{}: Slot begin contradicts current scope",
                        entry.entry
                    )));
                }
                scope.slot = Some(pair.clone());
                self.slots.push(pair.clone());
                self.shared_fields.insert(pair.clone(), Vec::new());
                self.slot_spans
                    .insert(pair.clone(), (order, -1, entry.entry.clone()));
            }
            ProductScopeRole::Option => {
                if scope.slot.as_ref() != product.owning_slot_pair.as_ref()
                    || scope.option.is_some()
                {
                    return Err(contract(format!(
                        "{}: Option owning Slot contradicts current Slot",
                        entry.entry
                    )));
                }
                scope.option = Some(pair.clone());
                self.options
                    .entry(scope.slot.as_ref().unwrap().clone())
                    .or_default()
                    .push(pair.clone());
                self.option_fields.insert(pair.clone(), Vec::new());
                self.option_spans
                    .insert(pair.clone(), (order, -1, entry.entry.clone()));
            }
        }
        Ok(())
    }
    fn end_bookmark(
        &mut self,
        entry: &StructuralEntryScan,
        scope: &mut EntryScope,
        pair: &BoundaryPairRef,
        order: i64,
    ) -> Result<(), QualificationInspectError> {
        if !entry.bookmark_topology_usable {
            return Ok(());
        }
        if scope.invalid_depth != 0 {
            scope.invalid_depth -= 1;
            return Ok(());
        }
        if scope.option.as_ref() == Some(pair) {
            self.option_spans
                .get_mut(pair)
                .ok_or_else(|| contract("missing Option span"))?
                .1 = order;
            scope.option = None;
        } else if scope.slot.as_ref() == Some(pair) {
            if scope.option.is_some() {
                return Err(contract(format!(
                    "{}: Slot end contradicts current scope",
                    entry.entry
                )));
            }
            self.slot_spans
                .get_mut(pair)
                .ok_or_else(|| contract("missing Slot span"))?
                .1 = order;
            scope.slot = None;
        }
        Ok(())
    }
    fn observation(
        &self,
        pair: &BoundaryPairRef,
    ) -> Result<&ProductScopeObservation, QualificationInspectError> {
        self.products
            .observations
            .iter()
            .find(|item| &item.pair == pair)
            .ok_or_else(|| contract("missing product observation"))
    }
    fn execution_occurrences(
        &self,
        slot_ids: &HashMap<BoundaryPairRef, String>,
        option_ids: &HashMap<BoundaryPairRef, (String, String)>,
    ) -> Result<Vec<FieldOccurrence>, QualificationInspectError> {
        let mut seen = HashMap::<String, i64>::new();
        let mut occurrences = Vec::new();
        for (id, owner, entry, order) in &self.occurrences {
            let ordinal = seen.entry(id.clone()).or_default();
            let (kind, slot, option) = match owner {
                Owner::Root => ("ROOT", None, None),
                Owner::Slot(pair) => ("SLOT_SHARED", Some(slot_ids[pair].clone()), None),
                Owner::Option(pair) => (
                    "OPTION",
                    Some(option_ids[pair].0.clone()),
                    Some(option_ids[pair].1.clone()),
                ),
                Owner::Unresolved => return Err(contract("unresolved PASS owner")),
            };
            occurrences.push(FieldOccurrence {
                field_id: id.clone(),
                occurrence_ordinal: *ordinal,
                owner_kind: kind.into(),
                owner_slot_id: slot,
                owner_option_id: option,
                content_entry_id: entry.clone(),
                structural_order: *order,
                native_value_target_class: "hwpx-field-value/v1".into(),
                resolver_contract_id: "hwpx-field-resolver/v1".into(),
            });
            *ordinal += 1;
        }
        Ok(occurrences)
    }
    fn passed(self) -> Result<QualificationInspection, QualificationInspectError> {
        let mut slots = Vec::new();
        for pair in &self.slots {
            let item = self.observation(pair)?;
            let mut options = Vec::new();
            for child in self.options.get(pair).into_iter().flatten() {
                let row = self.observation(child)?;
                options.push(TemplateOption {
                    id: row
                        .product_id
                        .clone()
                        .ok_or_else(|| contract("missing Option id"))?,
                    fields: self.option_fields.get(child).cloned().unwrap_or_default(),
                    label: row.product_label.clone(),
                });
            }
            slots.push(TemplateSlot {
                id: item
                    .product_id
                    .clone()
                    .ok_or_else(|| contract("missing Slot id"))?,
                shared_fields: self.shared_fields.get(pair).cloned().unwrap_or_default(),
                options,
                label: item.product_label.clone(),
            });
        }
        let structure = TemplateStructure {
            root_fields: self.root_fields.clone(),
            slots,
        };
        let slot_ids: HashMap<_, _> = self
            .slots
            .iter()
            .map(|pair| {
                Ok((
                    pair.clone(),
                    self.observation(pair)?.product_id.clone().unwrap(),
                ))
            })
            .collect::<Result<_, QualificationInspectError>>()?;
        let mut option_ids = HashMap::new();
        for (owner, children) in &self.options {
            for pair in children {
                option_ids.insert(
                    pair.clone(),
                    (
                        slot_ids[owner].clone(),
                        self.observation(pair)?.product_id.clone().unwrap(),
                    ),
                );
            }
        }
        let mut slot_regions = self
            .slot_spans
            .iter()
            .map(|(pair, (begin, end, entry))| SlotRegionObservation {
                slot_id: slot_ids[pair].clone(),
                content_entry_id: entry.clone(),
                begin_order: *begin,
                end_order: *end,
            })
            .collect::<Vec<_>>();
        slot_regions.sort_by_key(|item| item.begin_order);
        let mut option_regions = self
            .option_spans
            .iter()
            .map(|(pair, (begin, end, entry))| OptionRegionObservation {
                slot_id: option_ids[pair].0.clone(),
                option_id: option_ids[pair].1.clone(),
                content_entry_id: entry.clone(),
                begin_order: *begin,
                end_order: *end,
                removal_capability_ref: "remove-option/v1".into(),
            })
            .collect::<Vec<_>>();
        option_regions.sort_by_key(|item| item.begin_order);
        let occurrences = self.execution_occurrences(&slot_ids, &option_ids)?;
        let mut referenced = BTreeSet::new();
        referenced.extend(occurrences.iter().map(|item| item.content_entry_id.clone()));
        referenced.extend(
            slot_regions
                .iter()
                .map(|item| item.content_entry_id.clone()),
        );
        referenced.extend(
            option_regions
                .iter()
                .map(|item| item.content_entry_id.clone()),
        );
        let content_entries = referenced
            .into_iter()
            .map(|entry| {
                let kind = match self.kinds[&entry] {
                    ContentEntryKind::Section => "section",
                    ContentEntryKind::Header => "header",
                    ContentEntryKind::Footer => "footer",
                };
                ContentEntry {
                    content_entry_id: entry,
                    envelope_class: format!("{kind}-body/v1"),
                    envelope_capability_facts: ENVELOPE_CAPABILITY_KEYS
                        .into_iter()
                        .map(|key| (key.into(), true))
                        .collect(),
                }
            })
            .collect();
        // Every blocker is a FAIL diagnostic above. A PASS therefore has no blocker in any
        // resolver or envelope fact group; these true values are derived from that invariant.
        let resolver_stability_facts: BTreeMap<_, _> = RESOLVER_STABILITY_KEYS
            .into_iter()
            .map(|key| (key.into(), true))
            .collect();
        let execution_structure = build_execution_structure(ExecutionStructureInput {
            product_structure: structure.clone(),
            occurrences,
            slot_regions,
            option_regions,
            content_entries,
            resolver_stability_facts,
            admitted_relation_profile: "unadmitted".into(),
            projection_schema_version: LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA.into(),
        })
        .map_err(|error| QualificationInspectError::Inspection(error.to_string()))?;
        Ok(QualificationInspection {
            structure: Some(structure),
            diagnostics: Vec::new(),
            execution_structure: Some(execution_structure),
        })
    }
}

/// Inspect exact captured HWPX bytes once and project product plus native execution facts.
pub fn inspect_hwpx_qualification(
    bytes: &[u8],
) -> Result<QualificationInspection, QualificationInspectError> {
    let package = match HwpxPackage::from_bytes(bytes, PackageLimits::default()) {
        Ok(package) => package,
        Err(error) => {
            return Ok(QualificationInspection {
                structure: None,
                diagnostics: vec![diagnostic("invalid-hwpx-package", error.to_string())],
                execution_structure: None,
            });
        }
    };
    inspect_package_qualification(&package)
}
/// Same read-only projection for an already validated in-memory package.
pub fn inspect_package_qualification(
    package: &HwpxPackage,
) -> Result<QualificationInspection, QualificationInspectError> {
    let scan = scan_structural_boundaries(package);
    let products = inspect_product_bookmarks(&scan)
        .map_err(|error| QualificationInspectError::Inspection(error.to_string()))?;
    let capabilities = inspect_native_capabilities(package, &scan)
        .map_err(|error| QualificationInspectError::Inspection(error.to_string()))?;
    Qualifier::new(
        &scan,
        &products,
        &capabilities.field_fills,
        &capabilities.bookmark_removals,
    )?
    .inspect()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::encode_execution_structure;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;
    use serde_json::json;
    use sha2::{Digest, Sha256};

    fn python_json(value: &Value) -> String {
        match value {
            Value::Object(map) => {
                let mut keys: Vec<_> = map.keys().collect();
                keys.sort();
                format!(
                    "{{{}}}",
                    keys.into_iter()
                        .map(|key| {
                            format!(
                                "{}: {}",
                                serde_json::to_string(key).unwrap(),
                                python_json(&map[key])
                            )
                        })
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            }
            Value::Array(items) => format!(
                "[{}]",
                items.iter().map(python_json).collect::<Vec<_>>().join(", ")
            ),
            other => serde_json::to_string(other).unwrap(),
        }
    }

    #[test]
    fn shipping_qualification_behavior_is_frozen() {
        let bytes = include_bytes!("../../../tests/corpus/slots/canonical.hwpx");
        let inspection = inspect_hwpx_qualification(bytes).unwrap();
        assert!(inspection.diagnostics.is_empty());
        let structure = inspection.structure.unwrap();
        let execution = inspection.execution_structure.unwrap();
        let projection = json!({"structure":structure,"diagnostics":[],
            "execution_structure":encode_execution_structure(&execution)});
        let digest = Sha256::digest(python_json(&projection).as_bytes());
        let digest = digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        assert_eq!(
            digest,
            "1534fd3d203a59bdb560d0c74aedf6ffebf87bfdfc2c65d4b9991abdad8187e7"
        );
        assert_qualification_cases();
    }

    fn fixture_package(case: &Value) -> HwpxPackage {
        HwpxPackage {
            entries: case["entries"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(name, value)| PackageEntry {
                    name: name.clone(),
                    data: value.as_str().unwrap().as_bytes().to_vec(),
                    stored: name == "mimetype",
                })
                .collect(),
        }
    }

    fn assert_qualification_cases() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/hwpx_qualification.json"
        ))
        .unwrap();
        for case in fixture["cases"].as_array().unwrap() {
            let inspection = if let Some(invalid) = case["invalid_bytes"].as_str() {
                inspect_hwpx_qualification(invalid.as_bytes()).unwrap()
            } else {
                let package = fixture_package(case);
                let before = package.clone();
                let result = inspect_package_qualification(&package).unwrap();
                assert_eq!(package, before);
                let bytes = package.to_bytes().unwrap();
                let from_bytes = inspect_hwpx_qualification(&bytes).unwrap();
                assert_eq!(from_bytes.structure, result.structure);
                assert_eq!(from_bytes.diagnostics, result.diagnostics);
                result
            };
            assert_eq!(
                serde_json::to_value(&inspection.structure).unwrap(),
                case["structure"],
                "{}",
                case["name"]
            );
            let kinds: BTreeSet<_> = inspection
                .diagnostics
                .iter()
                .map(|item| item.kind.as_str())
                .collect();
            assert_eq!(
                kinds,
                case["diagnostics"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|item| item.as_str().unwrap())
                    .collect(),
                "{}",
                case["name"]
            );
            let execution = inspection
                .execution_structure
                .as_ref()
                .map(encode_execution_structure)
                .unwrap_or(Value::Null);
            assert_eq!(execution, case["execution_structure"], "{}", case["name"]);
            assert_eq!(
                inspection.structure.is_some(),
                inspection.diagnostics.is_empty()
            );
            if let Some(parts) = case["message_parts"].as_array() {
                assert_eq!(inspection.diagnostics.len(), 1);
                for part in parts {
                    assert!(
                        inspection.diagnostics[0]
                            .message
                            .contains(part.as_str().unwrap())
                    );
                }
            }
        }
    }

    #[test]
    fn inconsistent_observations_fail_as_contract_errors_without_partial_results() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/hwpx_qualification.json"
        ))
        .unwrap();
        let package = fixture_package(&fixture["cases"][0]);
        let original = scan_structural_boundaries(&package);
        let original_products = inspect_product_bookmarks(&original).unwrap();
        let native = inspect_native_capabilities(&package, &original).unwrap();
        let option_at = original_products
            .observations
            .iter()
            .position(|item| item.scope_role == ProductScopeRole::Option)
            .unwrap();
        let field_pair = native.field_fills[0].pair.clone();
        for (case, expected) in [
            ("missing-fill", "Field fill observation order mismatch"),
            ("extra-fill", "extra Field fill observation"),
            (
                "missing-removal",
                "BOOKMARK removal observation order mismatch",
            ),
            ("extra-removal", "extra BOOKMARK removal observation"),
            (
                "missing-product",
                "product scope observation order mismatch",
            ),
            ("extra-product", "extra product scope observation"),
            ("wrong-owner", "Option owning Slot contradicts current Slot"),
            ("wrong-entry", "product scope entry mismatch"),
            ("masked-slot", "product scope observation conflicts"),
            ("invalid-scope", "product scope observation conflicts"),
            ("future-kind", "product scope observation conflicts"),
            (
                "invalid-owner",
                "invalid product owning Slot contradicts current Slot",
            ),
            ("nested-slot", "Slot begin contradicts current scope"),
            ("blocked-outer", "usable product scope inside invalid scope"),
            ("wrong-field-end", "Field end contradicts open Field"),
            ("nested-field", "Field began while another Field was open"),
            ("orphan-field-end", "Field end contradicts open Field"),
            ("crossed-slot-end", "Slot end contradicts current scope"),
            ("unclosed-slot", "analyzer ended with impossible state"),
        ] {
            let mut scan = original.clone();
            let mut products = original_products.clone();
            let mut fills = native.field_fills.clone();
            let mut removals = native.bookmark_removals.clone();
            let events = &mut scan.entries[0].events;
            match case {
                "missing-fill" => fills.clear(),
                "extra-fill" => fills.push(fills.last().unwrap().clone()),
                "missing-removal" => removals.clear(),
                "extra-removal" => removals.push(removals.last().unwrap().clone()),
                "missing-product" => products.observations.clear(),
                "extra-product" => products
                    .observations
                    .push(products.observations.last().unwrap().clone()),
                "wrong-owner" => {
                    products.observations[option_at].owning_slot_pair = Some(field_pair.clone())
                }
                "wrong-entry" => products.observations[0].entry = "Contents/other.xml".into(),
                "masked-slot" => {
                    products.observations[0].classification = ProductClassification::NonProduct
                }
                "invalid-scope" => {
                    let item = &mut products.observations[0];
                    item.classification = ProductClassification::InvalidProduct;
                    item.scope_role = ProductScopeRole::InvalidProduct;
                    item.scope_usable = false;
                    item.kind = None;
                    item.product_id = None;
                }
                "future-kind" | "blocked-outer" => {
                    let item = &mut products.observations[0];
                    item.scope_role = ProductScopeRole::InvalidProduct;
                    item.scope_usable = false;
                    if case == "future-kind" {
                        item.kind = Some("future".into());
                    }
                    products
                        .diagnostics
                        .push(crate::hwpx_product_inspection::TemplateDiagnostic {
                            kind: "invalid-outer".into(),
                            message: "blocked".into(),
                        });
                }
                "invalid-owner" => {
                    let item = &mut products.observations[option_at];
                    item.scope_role = ProductScopeRole::InvalidProduct;
                    item.scope_usable = false;
                    item.owning_slot_pair = Some(field_pair.clone());
                    products
                        .diagnostics
                        .push(crate::hwpx_product_inspection::TemplateDiagnostic {
                            kind: "invalid-option".into(),
                            message: "blocked".into(),
                        });
                }
                "nested-slot" => {
                    let item = &mut products.observations[option_at];
                    item.scope_role = ProductScopeRole::Slot;
                    item.kind = Some("slot".into());
                    item.owning_slot_pair = None;
                }
                _ => corrupt_event_order(events, &mut fills, &original_products, case),
            }
            let failure = Qualifier::new(&scan, &products, &fills, &removals)
                .and_then(Qualifier::inspect)
                .unwrap_err();
            assert!(
                matches!(failure, QualificationInspectError::Contract(_)),
                "{case}: {failure}"
            );
            assert!(failure.to_string().contains(expected), "{case}: {failure}");
        }
    }

    fn corrupt_event_order(
        events: &mut Vec<BoundaryEvent>,
        fills: &mut Vec<FieldFillObservation>,
        products: &ProductBookmarkInspection,
        case: &str,
    ) {
        let slot_pair = products.observations[0].pair.clone();
        let option_pair = products
            .observations
            .iter()
            .find(|item| item.scope_role == ProductScopeRole::Option)
            .unwrap()
            .pair
            .clone();
        let field_pair = fills[0].pair.clone();
        match case {
            "wrong-field-end" => {
                let at = events
                    .iter()
                    .position(|event| matches!(event, BoundaryEvent::FieldEnd { .. }))
                    .unwrap();
                events[at] = BoundaryEvent::FieldEnd {
                    pair: slot_pair.clone(),
                    order: events[at].order(),
                };
            }
            "nested-field" => {
                let at = events
                    .iter()
                    .position(|event| matches!(event, BoundaryEvent::FieldBegin { .. }))
                    .unwrap();
                let later = events
                    .iter()
                    .skip(at + 1)
                    .find(|event| matches!(event, BoundaryEvent::FieldBegin { .. }))
                    .unwrap()
                    .clone();
                events.insert(at + 1, later);
                fills.insert(1, fills[1].clone());
            }
            "orphan-field-end" => events.insert(
                0,
                BoundaryEvent::FieldEnd {
                    pair: field_pair.clone(),
                    order: 0,
                },
            ),
            "crossed-slot-end" => {
                let outer = events.iter().position(|event| matches!(event, BoundaryEvent::BookmarkEnd { pair, .. } if pair == &slot_pair)).unwrap();
                let inner = events.iter().position(|event| matches!(event, BoundaryEvent::BookmarkEnd { pair, .. } if pair == &option_pair)).unwrap();
                events.swap(outer, inner);
            }
            "unclosed-slot" => {
                let last = events
                    .iter()
                    .rposition(|event| matches!(event, BoundaryEvent::BookmarkEnd { .. }))
                    .unwrap();
                events.remove(last);
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn hyperlink_is_not_a_fill_target_and_broken_field_fails_closed() {
        let section = |body: &str| {
            HwpxPackage { entries: vec![PackageEntry {
            name: "Contents/section0.xml".into(),
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run>{body}</hp:run></hp:p></hs:sec>").into_bytes(),
            stored: false,
        }] }
        };
        let hyperlink = section(
            "<hp:ctrl><hp:fieldBegin type='HYPERLINK' id='1'/></hp:ctrl><hp:t>링크</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl>",
        );
        let accepted = inspect_package_qualification(&hyperlink).unwrap();
        assert_eq!(
            accepted.structure.unwrap().root_fields,
            Vec::<String>::new()
        );
        assert!(accepted.diagnostics.is_empty());
        let broken = section(
            "<hp:ctrl><hp:fieldBegin type='CLICK_HERE' id='1' name='A'/></hp:ctrl><hp:t>값</hp:t>",
        );
        let refused = inspect_package_qualification(&broken).unwrap();
        assert!(refused.structure.is_none());
        assert!(refused.execution_structure.is_none());
        assert!(
            refused
                .diagnostics
                .iter()
                .any(|row| row.kind == "field-unmatched-begin")
        );
        let invalid = inspect_hwpx_qualification(b"not a ZIP").unwrap();
        assert_eq!(invalid.diagnostics[0].kind, "invalid-hwpx-package");
    }
}
