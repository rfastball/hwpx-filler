//! Product scope of each BOOKMARK while walking an entry's boundary events, and the
//! duplicate-id checks over the resulting observations.

use super::{
    PRODUCT_KIND_OPTION, PRODUCT_KIND_SLOT, ParsedProduct, ProductClassification,
    ProductInspectionError, ProductScopeObservation, ProductScopeRole, TemplateDiagnostic,
    diagnostic, product_tag, py_repr,
};
use hwpx_core::structural_boundary::{
    BoundaryEvent, BoundaryPairRef, ContentEntryKind, StructuralEntryScan,
};
use std::collections::{HashMap, HashSet};

#[derive(Clone)]
struct OpenBookmark {
    pair: BoundaryPairRef,
    kind: Option<String>,
    scope_usable: bool,
}

/// A product bookmark's surroundings: its entry, name, and enclosing product bookmarks.
struct Placement<'a> {
    entry: &'a StructuralEntryScan,
    name: Option<&'a str>,
    slot_ancestors: Vec<BoundaryPairRef>,
    option_ancestors: Vec<BoundaryPairRef>,
}

impl Placement<'_> {
    fn report(&self, diagnostics: &mut Vec<TemplateDiagnostic>, kind: &str, detail: &str) {
        diagnostics.push(diagnostic(kind, &self.entry.entry, self.name, detail));
    }
}

/// An Option is usable only with exactly one Slot ancestor and no Option ancestor.
fn option_usable(at: &Placement, diagnostics: &mut Vec<TemplateDiagnostic>) -> bool {
    let mut usable = true;
    if !at.option_ancestors.is_empty() {
        at.report(diagnostics, "nested-option", "Option is inside another Option");
        usable = false;
    }
    if at.slot_ancestors.is_empty() {
        at.report(diagnostics, "orphan-option", "Option has no product Slot ancestor");
        usable = false;
    } else if at.slot_ancestors.len() > 1 {
        at.report(
            diagnostics,
            "ambiguous-membership",
            "Option has more than one product Slot ancestor",
        );
        usable = false;
    }
    usable
}

/// The role of a known product: section entries only, Slots never nested in Slots.
fn known_product_scope(
    at: &Placement,
    kind: Option<&str>,
    diagnostics: &mut Vec<TemplateDiagnostic>,
) -> (ProductScopeRole, bool) {
    if at.entry.kind != ContentEntryKind::Section {
        at.report(
            diagnostics,
            "unsupported-product-entry",
            "product Slot/Option is supported only in section entries",
        );
        return (ProductScopeRole::InvalidProduct, false);
    }
    if kind == Some(PRODUCT_KIND_SLOT) {
        if at.slot_ancestors.is_empty() {
            return (ProductScopeRole::Slot, true);
        }
        at.report(diagnostics, "nested-slot", "Slot is inside another Slot");
        return (ProductScopeRole::InvalidProduct, false);
    }
    if option_usable(at, diagnostics) {
        (ProductScopeRole::Option, true)
    } else {
        (ProductScopeRole::InvalidProduct, false)
    }
}

fn ancestors(open: &[OpenBookmark], kind: &str) -> Vec<BoundaryPairRef> {
    open.iter()
        .filter(|item| item.kind.as_deref() == Some(kind))
        .map(|item| item.pair.clone())
        .collect()
}

/// The scope role, usability, and owning Slot of a product bookmark opened inside
/// `open`; any unusable enclosing scope makes it invalid.
fn classify_scope(
    entry: &StructuralEntryScan,
    name: Option<&str>,
    product: &ParsedProduct,
    open: &[OpenBookmark],
    diagnostics: &mut Vec<TemplateDiagnostic>,
) -> (ProductScopeRole, bool, Option<BoundaryPairRef>) {
    let scope_blocked = open.iter().any(|item| !item.scope_usable);
    let at = Placement {
        entry,
        name,
        slot_ancestors: ancestors(open, PRODUCT_KIND_SLOT),
        option_ancestors: ancestors(open, PRODUCT_KIND_OPTION),
    };
    let owning_slot = (!scope_blocked
        && product.kind.as_deref() == Some(PRODUCT_KIND_OPTION)
        && at.slot_ancestors.len() == 1)
        .then(|| at.slot_ancestors[0].clone());
    let (role, usable) = match product.classification {
        ProductClassification::InvalidProduct => (ProductScopeRole::InvalidProduct, false),
        ProductClassification::KnownProduct => {
            known_product_scope(&at, product.kind.as_deref(), diagnostics)
        }
        ProductClassification::NonProduct => (ProductScopeRole::None, true),
    };
    if scope_blocked {
        return (ProductScopeRole::InvalidProduct, false, None);
    }
    (role, usable, owning_slot)
}

/// Walks every entry's BOOKMARK events, recording each bookmark's name and scope.
pub(super) struct BookmarkWalk<'s> {
    pub(super) unattributed_metatag_entries: &'s HashSet<&'s str>,
    pub(super) names: HashMap<BoundaryPairRef, Option<String>>,
    pub(super) observations: Vec<ProductScopeObservation>,
    pub(super) diagnostics: Vec<TemplateDiagnostic>,
}

impl BookmarkWalk<'_> {
    pub(super) fn entry(&mut self, entry: &StructuralEntryScan) -> Result<(), ProductInspectionError> {
        let mut open = Vec::new();
        for event in &entry.events {
            match event {
                BoundaryEvent::BookmarkBegin {
                    pair,
                    bookmark_name,
                    meta_tags,
                    meta_tag_attribute,
                    ..
                } => {
                    self.names.insert(pair.clone(), bookmark_name.clone());
                    let product = product_tag(
                        &entry.entry,
                        bookmark_name.as_deref(),
                        meta_tags,
                        meta_tag_attribute.as_deref(),
                        &mut self.diagnostics,
                    );
                    self.begin(entry, &mut open, pair, bookmark_name.as_deref(), product);
                }
                BoundaryEvent::BookmarkEnd { pair, .. } if entry.bookmark_topology_usable => {
                    if open.last().is_none_or(|item: &OpenBookmark| item.pair != *pair) {
                        return Err(ProductInspectionError(format!(
                            "{}: BOOKMARK end contradicts usable topology",
                            entry.entry
                        )));
                    }
                    open.pop();
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn begin(
        &mut self,
        entry: &StructuralEntryScan,
        open: &mut Vec<OpenBookmark>,
        pair: &BoundaryPairRef,
        name: Option<&str>,
        product: ParsedProduct,
    ) {
        let trusted = entry.bookmark_topology_usable
            && !self
                .unattributed_metatag_entries
                .contains(entry.entry.as_str());
        let (role, usable, owning_slot) = if trusted {
            classify_scope(entry, name, &product, open, &mut self.diagnostics)
        } else {
            (ProductScopeRole::InvalidProduct, false, None)
        };
        self.observations.push(ProductScopeObservation {
            pair: pair.clone(),
            entry: entry.entry.clone(),
            classification: product.classification,
            scope_role: role,
            scope_usable: usable,
            kind: product.kind.clone(),
            product_id: product.id,
            owning_slot_pair: owning_slot,
            product_label: product.label,
        });
        if entry.bookmark_topology_usable {
            open.push(OpenBookmark {
                pair: pair.clone(),
                kind: if trusted { product.kind } else { None },
                scope_usable: usable,
            });
        }
    }
}

/// Duplicate Slot ids, and duplicate Option ids within one Slot, among projected products.
pub(super) fn duplicate_id_diagnostics(
    observations: &[ProductScopeObservation],
    names: &HashMap<BoundaryPairRef, Option<String>>,
    projection_pairs: &HashSet<BoundaryPairRef>,
) -> Vec<TemplateDiagnostic> {
    let by_pair: HashMap<_, _> = observations
        .iter()
        .map(|item| (item.pair.clone(), item))
        .collect();
    let mut diagnostics = Vec::new();
    let mut seen_slot_ids = HashSet::new();
    let mut seen_option_ids: HashMap<BoundaryPairRef, HashSet<String>> = HashMap::new();
    for item in observations {
        let Some(id) = item
            .product_id
            .as_deref()
            .filter(|_| item.classification == ProductClassification::KnownProduct)
            .filter(|_| projection_pairs.contains(&item.pair))
        else {
            continue;
        };
        let name = names.get(&item.pair).and_then(|name| name.as_deref());
        if item.kind.as_deref() == Some(PRODUCT_KIND_SLOT) {
            if !seen_slot_ids.insert(id.to_owned()) {
                diagnostics.push(diagnostic(
                    "duplicate-slot-id",
                    &item.entry,
                    name,
                    &format!("duplicate Slot id {}", py_repr(Some(id))),
                ));
            }
        } else if let Some(owner_pair) = &item.owning_slot_pair
            && !seen_option_ids
                .entry(owner_pair.clone())
                .or_default()
                .insert(id.to_owned())
        {
            diagnostics.push(diagnostic(
                "duplicate-option-id",
                &item.entry,
                name,
                &format!(
                    "duplicate Option id {} in Slot {}",
                    py_repr(Some(id)),
                    py_repr(by_pair[owner_pair].product_id.as_deref())
                ),
            ));
        }
    }
    diagnostics
}
