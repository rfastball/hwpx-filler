//! Composition of admitted structure observations into a durable projection.

use super::*;

type SlotRegionMap = HashMap<String, (String, (i64, i64))>;
type OptionRegionMap<'a> = BTreeMap<OptionRegionRef, &'a OptionRegionObservation>;

fn validate_resolver_facts(facts: &BTreeMap<String, bool>) -> Result<(), ExecutionStructureError> {
    for key in RESOLVER_STABILITY_KEYS {
        if !facts.contains_key(key) {
            return Err(resolver_missing(format!(
                "resolver stability fact {} 부재",
                quoted(key)
            )));
        }
    }
    Ok(())
}

fn collect_slot_regions(
    regions: &[SlotRegionObservation],
    shared: &HashMap<String, HashSet<String>>,
    entries: &HashSet<String>,
) -> Result<SlotRegionMap, ExecutionStructureError> {
    let mut slots = HashMap::new();
    for region in regions {
        if !shared.contains_key(&region.slot_id) {
            return Err(integrity(format!(
                "Slot region 이 product 밖 Slot 참조: {:?}",
                region.slot_id
            )));
        }
        if slots.contains_key(&region.slot_id) {
            return Err(integrity(format!("Slot region 중복: {:?}", region.slot_id)));
        }
        require_span(
            region.begin_order,
            region.end_order,
            &format!("Slot {:?} region", region.slot_id),
        )?;
        if !entries.contains(&region.content_entry_id) {
            return Err(envelope_missing(format!(
                "Slot region 이 미선언 content entry 참조: {:?}",
                region.content_entry_id
            )));
        }
        slots.insert(
            region.slot_id.clone(),
            (
                region.content_entry_id.clone(),
                (region.begin_order, region.end_order),
            ),
        );
    }
    if slots.len() != shared.len() {
        return Err(relation_missing("Slot region 이 없는 Slot"));
    }
    Ok(slots)
}

fn collect_option_regions<'a>(
    observed: &'a [OptionRegionObservation],
    options: &HashMap<OptionRegionRef, HashSet<String>>,
    slots: &SlotRegionMap,
    entries: &HashSet<String>,
) -> Result<OptionRegionMap<'a>, ExecutionStructureError> {
    let mut regions = BTreeMap::new();
    for region in observed {
        let key = OptionRegionRef {
            slot_id: region.slot_id.clone(),
            option_id: region.option_id.clone(),
        };
        if !options.contains_key(&key) {
            return Err(integrity(format!(
                "Option region 이 product 밖 Option 참조: {}",
                option_key(&key)
            )));
        }
        if regions.contains_key(&key) {
            return Err(integrity(format!(
                "Option region 중복: {}",
                option_key(&key)
            )));
        }
        require_span(
            region.begin_order,
            region.end_order,
            &format!("Option {} region", option_key(&key)),
        )?;
        if !entries.contains(&region.content_entry_id) {
            return Err(envelope_missing(format!(
                "Option region 이 미선언 content entry 참조: {:?}",
                region.content_entry_id
            )));
        }
        require_text(&region.removal_capability_ref, "removal_capability_ref")?;
        let Some((slot_entry, slot_span)) = slots.get(&region.slot_id) else {
            return Err(relation_missing("Option owning Slot region missing"));
        };
        if region.begin_order < slot_span.0 || region.end_order > slot_span.1 {
            return Err(integrity(format!(
                "Option {} region 이 owning Slot span 밖으로 벗어난다",
                option_key(&key)
            )));
        }
        if &region.content_entry_id != slot_entry {
            return Err(integrity(format!(
                "Option {} region 의 content entry 가 owning Slot 과 불일치",
                option_key(&key)
            )));
        }
        regions.insert(key, region);
    }
    if regions.len() != options.len() {
        let mut missing: Vec<_> = options
            .keys()
            .filter(|key| !regions.contains_key(*key))
            .map(option_key)
            .collect();
        missing.sort();
        return Err(relation_missing(format!(
            "Option region 이 없는 Option: [{}]",
            missing.join(", ")
        )));
    }
    Ok(regions)
}

fn validate_option_occurrences(
    occurrences: &[FieldOccurrence],
    regions: &OptionRegionMap<'_>,
) -> Result<(), ExecutionStructureError> {
    for occ in occurrences {
        if occ.owner_kind != "OPTION" {
            continue;
        }
        let key = OptionRegionRef {
            slot_id: occ.owner_slot_id.clone().unwrap(),
            option_id: occ.owner_option_id.clone().unwrap(),
        };
        let Some(region) = regions.get(&key) else {
            return Err(integrity(format!(
                "OPTION occurrence {:?} 의 region 부재",
                occ.field_id
            )));
        };
        if occ.content_entry_id != region.content_entry_id {
            return Err(integrity(format!(
                "OPTION occurrence {} 의 content entry 가 region 과 불일치",
                quoted(&occ.field_id)
            )));
        }
        if occ.structural_order < region.begin_order || occ.structural_order > region.end_order {
            return Err(integrity(format!(
                "OPTION occurrence {} structural_order 가 region span 밖",
                quoted(&occ.field_id)
            )));
        }
    }
    Ok(())
}

fn build_relations(regions: &OptionRegionMap<'_>) -> Vec<RemovalTargetRelation> {
    let keys: Vec<_> = regions.keys().cloned().collect();
    let mut relations = Vec::new();
    for (index, left) in keys.iter().enumerate() {
        for right in &keys[index + 1..] {
            let a = regions[left];
            let b = regions[right];
            relations.push(RemovalTargetRelation {
                left_option_ref: left.clone(),
                right_option_ref: right.clone(),
                relation: classify_span_relation(
                    (a.begin_order, a.end_order),
                    (b.begin_order, b.end_order),
                )
                .into(),
            });
        }
    }
    relations
}

pub fn build_execution_structure(
    mut input: ExecutionStructureInput,
) -> Result<ExecutionTemplateStructure, ExecutionStructureError> {
    require_schema(&input.projection_schema_version)?;
    if !labels_required(&input.projection_schema_version) && has_labels(&input.product_structure) {
        return Err(integrity(format!(
            "label-bearing product structure 는 {LABELED_EXECUTION_STRUCTURE_PROJECTION_SCHEMA} 가 필요하다"
        )));
    }
    let entries = validate_content_entries(&input.content_entries)?;
    validate_occurrences(&input.occurrences, &input.product_structure, &entries)?;
    validate_resolver_facts(&input.resolver_stability_facts)?;
    require_text(
        &input.admitted_relation_profile,
        "admitted_relation_profile",
    )?;
    let (_, shared, options) = product_index(&input.product_structure)?;
    let slots = collect_slot_regions(&input.slot_regions, &shared, &entries)?;
    let regions = collect_option_regions(&input.option_regions, &options, &slots, &entries)?;
    validate_option_occurrences(&input.occurrences, &regions)?;
    let relations = build_relations(&regions);
    let crossing_free = relations
        .iter()
        .all(|relation| relation.relation != "CROSSING");
    input.occurrences.sort_by_key(|occ| occ.structural_order);
    input
        .content_entries
        .sort_by(|a, b| a.content_entry_id.cmp(&b.content_entry_id));
    let option_regions = regions.into_iter().map(|(key,region)| {
        let slot = &slots[&key.slot_id];
        OptionRegion {
            slot_id:key.slot_id.clone(), option_id:key.option_id.clone(), content_entry_id:region.content_entry_id.clone(),
            begin_order:region.begin_order, end_order:region.end_order,
            owner_relation_facts:vec![json!({"relation":"target_owner_slot","slot_id":key.slot_id,"coincidence":owner_coincidence((region.begin_order,region.end_order),slot.1)}),json!({"relation":"target_owner_content_entry","content_entry_id":region.content_entry_id})],
            retained_content_relation_facts:input.occurrences.iter().filter(|occ| !(occ.owner_kind == "OPTION" && occ.owner_slot_id.as_deref() == Some(&key.slot_id) && occ.owner_option_id.as_deref() == Some(&key.option_id))).map(|occ| json!({"field_id":occ.field_id,"occurrence_ordinal":occ.occurrence_ordinal,"owner_kind":occ.owner_kind,"position":point_position(occ.structural_order,(region.begin_order,region.end_order))})).collect(),
            removal_capability_ref:region.removal_capability_ref.clone(),
        }
    }).collect();
    Ok(ExecutionTemplateStructure {
        projection_schema_version: input.projection_schema_version,
        product_structure: input.product_structure,
        field_occurrences: input.occurrences,
        option_regions,
        removal_target_relations: relations,
        content_entries: input.content_entries,
        global_composition_facts: GlobalCompositionFacts {
            crossing_free,
            resolver_stability_facts: input.resolver_stability_facts,
            admitted_relation_profile: input.admitted_relation_profile,
        },
    })
}
