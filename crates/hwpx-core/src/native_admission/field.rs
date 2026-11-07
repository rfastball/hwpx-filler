//! Field replacement effects and blockers over the shared entry index.

use super::*;

pub(super) fn effect(kind: FieldFillEffectKind, detail: Vec<String>) -> FieldFillEffect {
    FieldFillEffect { kind, detail }
}
fn blocker(kind: FieldFillBlockerKind, detail: Vec<String>) -> FieldFillBlocker {
    FieldFillBlocker { kind, detail }
}
fn removed_inline(doc: &XmlDocument, occurrence: &FieldOccurrence) -> HashSet<NodeId> {
    occurrence
        .texts
        .iter()
        .flat_map(|text| doc.elements(*text))
        .flat_map(|child| doc.descendants(child))
        .collect()
}
pub(crate) fn plan_field_fill(
    doc: &XmlDocument,
    index: &NativeAdmissionIndex,
    occurrence: &FieldOccurrence,
    pairing_usable: bool,
) -> (Vec<FieldFillEffect>, Vec<FieldFillBlocker>) {
    let removed = removed_inline(doc, occurrence);
    let mut blockers = Vec::new();
    if !pairing_usable {
        blockers.push(blocker(
            FieldFillBlockerKind::FieldPairingUnusable,
            Vec::new(),
        ));
    }
    if occurrence.texts.is_empty() && occurrence.begin_ctrl == occurrence.end_ctrl {
        blockers.push(blocker(FieldFillBlockerKind::NoValuePosition, Vec::new()));
    }
    let safe_removed = removable_ranges(index, &removed, &mut blockers);
    let mut unpaired: Vec<_> = index
        .unpaired
        .iter()
        .filter(|id| {
            unpaired_intersects(
                index,
                doc,
                **id,
                occurrence.begin_order,
                occurrence.end_order,
            )
        })
        .map(|id| node_name(doc, *id))
        .collect();
    unpaired.sort();
    unpaired.dedup();
    if !unpaired.is_empty() {
        blockers.push(blocker(
            FieldFillBlockerKind::UnpairedProtectedRange,
            unpaired,
        ));
    }
    let mut unsupported: Vec<_> = index
        .unsupported_inline
        .iter()
        .filter(|(id, _)| removed.contains(id) || occurrence.texts.contains(id))
        .map(|(_, name)| name.clone())
        .collect();
    unsupported.sort();
    unsupported.dedup();
    if !unsupported.is_empty() {
        blockers.push(blocker(
            FieldFillBlockerKind::UnsupportedInlineObject,
            unsupported,
        ));
    }
    let effects = fill_effects(doc, occurrence, safe_removed);
    blockers.dedup();
    (effects, blockers)
}

fn removable_ranges(
    index: &NativeAdmissionIndex,
    removed: &HashSet<NodeId>,
    blockers: &mut Vec<FieldFillBlocker>,
) -> HashSet<NodeId> {
    let mut safe_removed = HashSet::new();
    for range in &index.ranges {
        let begin = removed.contains(&range.begin);
        let end = removed.contains(&range.end);
        if begin != end {
            blockers.push(blocker(
                FieldFillBlockerKind::ProtectedRangeCrossing,
                vec![range.begin_name.clone(), range.end_name.clone()],
            ));
        } else if begin {
            safe_removed.insert(range.begin);
            safe_removed.insert(range.end);
        }
    }
    safe_removed
}

fn fill_effects(
    doc: &XmlDocument,
    occurrence: &FieldOccurrence,
    safe_removed: HashSet<NodeId>,
) -> Vec<FieldFillEffect> {
    let mut effects = Vec::new();
    if occurrence.texts.is_empty() && occurrence.begin_ctrl != occurrence.end_ctrl {
        effects.push(effect(FieldFillEffectKind::SynthesizeSlot, Vec::new()));
    }
    if !safe_removed.is_empty() {
        let mut names: Vec<_> = safe_removed
            .into_iter()
            .map(|id| node_name(doc, id))
            .collect();
        names.sort();
        names.dedup();
        effects.push(effect(FieldFillEffectKind::RemoveInline, names));
    }
    if occurrence.texts.len() > 1 {
        effects.push(effect(FieldFillEffectKind::NormalizeFragments, Vec::new()));
    }
    effects
}
