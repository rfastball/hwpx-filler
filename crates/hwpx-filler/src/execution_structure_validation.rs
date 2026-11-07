//! Validation of occurrence coverage and encoded structure invariants.

use super::*;

type ProductIndex = (
    HashSet<String>,
    HashMap<String, HashSet<String>>,
    HashMap<OptionRegionRef, HashSet<String>>,
);
pub(super) fn product_index(
    product: &TemplateStructure,
) -> Result<ProductIndex, ExecutionStructureError> {
    let root = product.root_fields.iter().cloned().collect();
    let mut shared = HashMap::new();
    let mut options = HashMap::new();
    for slot in &product.slots {
        if shared
            .insert(
                slot.id.clone(),
                slot.shared_fields.iter().cloned().collect(),
            )
            .is_some()
        {
            return Err(integrity(format!("product Slot id 중복: {:?}", slot.id)));
        }
        for option in &slot.options {
            let key = OptionRegionRef {
                slot_id: slot.id.clone(),
                option_id: option.id.clone(),
            };
            if options
                .insert(key.clone(), option.fields.iter().cloned().collect())
                .is_some()
            {
                return Err(integrity(format!(
                    "Slot {:?} 안 Option id 중복: {:?}",
                    slot.id, option.id
                )));
            }
        }
    }
    Ok((root, shared, options))
}

pub(super) fn validate_content_entries(
    entries: &[ContentEntry],
) -> Result<HashSet<String>, ExecutionStructureError> {
    let mut ids = HashSet::new();
    for entry in entries {
        require_text(&entry.content_entry_id, "content_entry_id")?;
        require_text(&entry.envelope_class, "envelope_class")?;
        if !ids.insert(entry.content_entry_id.clone()) {
            return Err(integrity(format!(
                "content_entry_id 중복: {:?}",
                entry.content_entry_id
            )));
        }
        for key in ENVELOPE_CAPABILITY_KEYS {
            if !entry.envelope_capability_facts.contains_key(key) {
                return Err(envelope_missing(format!(
                    "content entry {} 에 envelope fact {} 부재",
                    quoted(&entry.content_entry_id),
                    quoted(key)
                )));
            }
        }
    }
    Ok(ids)
}

#[derive(Default)]
struct OccurrenceCoverage {
    root: HashSet<String>,
    shared: HashSet<(String, String)>,
    option: HashSet<(OptionRegionRef, String)>,
}

fn validate_occurrence_fields(
    occ: &FieldOccurrence,
    entries: &HashSet<String>,
) -> Result<(), ExecutionStructureError> {
    for (value, what) in [
        (&occ.field_id, "field_id"),
        (&occ.content_entry_id, "occurrence.content_entry_id"),
        (&occ.native_value_target_class, "native_value_target_class"),
    ] {
        require_text(value, what)?;
    }
    if occ.occurrence_ordinal < 0 {
        return Err(integrity(format!(
            "occurrence_ordinal 이 음수/비정수: {}",
            occ.occurrence_ordinal
        )));
    }
    if occ.resolver_contract_id.is_empty() {
        return Err(resolver_missing(format!(
            "Field {} occurrence 에 resolver_contract_id 부재",
            quoted(&occ.field_id)
        )));
    }
    if !entries.contains(&occ.content_entry_id) {
        return Err(envelope_missing(format!(
            "occurrence 가 미선언 content entry 참조: {}",
            quoted(&occ.content_entry_id)
        )));
    }
    Ok(())
}

fn validate_occurrence_owner(
    occ: &FieldOccurrence,
    root: &HashSet<String>,
    shared: &HashMap<String, HashSet<String>>,
    options: &HashMap<OptionRegionRef, HashSet<String>>,
    covered: &mut OccurrenceCoverage,
) -> Result<(), ExecutionStructureError> {
    match occ.owner_kind.as_str() {
        "ROOT" => {
            validate_root_owner(occ, root)?;
            covered.root.insert(occ.field_id.clone());
        }
        "SLOT_SHARED" => {
            let slot = validate_shared_owner(occ, shared)?;
            covered.shared.insert((slot.clone(), occ.field_id.clone()));
        }
        "OPTION" => {
            let key = validate_option_owner(occ, options)?;
            covered.option.insert((key, occ.field_id.clone()));
        }
        _ => {
            return Err(integrity(format!(
                "owner_kind 가 ROOT/SLOT_SHARED/OPTION 밖: {}",
                quoted(&occ.owner_kind)
            )));
        }
    }
    Ok(())
}

fn validate_root_owner(
    occ: &FieldOccurrence,
    root: &HashSet<String>,
) -> Result<(), ExecutionStructureError> {
    if occ.owner_slot_id.is_some() || occ.owner_option_id.is_some() {
        return Err(integrity("ROOT occurrence 는 owner ref 가 없다"));
    }
    if !root.contains(&occ.field_id) {
        return Err(integrity(format!(
            "root Field {} 가 product structure 에 없다",
            quoted(&occ.field_id)
        )));
    }
    Ok(())
}
fn validate_shared_owner<'a>(
    occ: &'a FieldOccurrence,
    shared: &HashMap<String, HashSet<String>>,
) -> Result<&'a String, ExecutionStructureError> {
    if occ.owner_slot_id.is_none() || occ.owner_option_id.is_some() {
        return Err(integrity("SLOT_SHARED occurrence 는 slot ref 만 갖는다"));
    }
    let slot = occ.owner_slot_id.as_ref().unwrap();
    if !shared
        .get(slot)
        .is_some_and(|fields| fields.contains(&occ.field_id))
    {
        return Err(integrity(format!(
            "shared Field {} 가 Slot {} 에 없다",
            quoted(&occ.field_id),
            quoted(slot)
        )));
    }
    Ok(slot)
}
fn validate_option_owner(
    occ: &FieldOccurrence,
    options: &HashMap<OptionRegionRef, HashSet<String>>,
) -> Result<OptionRegionRef, ExecutionStructureError> {
    if occ.owner_slot_id.is_none() || occ.owner_option_id.is_none() {
        return Err(integrity(
            "OPTION occurrence 는 slot·option ref 를 모두 갖는다",
        ));
    }
    let key = OptionRegionRef {
        slot_id: occ.owner_slot_id.clone().unwrap(),
        option_id: occ.owner_option_id.clone().unwrap(),
    };
    if !options
        .get(&key)
        .is_some_and(|fields| fields.contains(&occ.field_id))
    {
        return Err(integrity(format!(
            "option Field {} 가 {} 에 없다",
            quoted(&occ.field_id),
            option_key(&key)
        )));
    }
    Ok(key)
}

fn validate_ordinals(by_field: HashMap<&str, Vec<i64>>) -> Result<(), ExecutionStructureError> {
    for (field, mut ordinals) in by_field {
        ordinals.sort();
        let actual: HashSet<_> = ordinals.iter().copied().collect();
        if actual.len() != ordinals.len() {
            return Err(integrity(format!(
                "Field {} occurrence ordinal 중복: {}",
                quoted(field),
                python_repr(&json!(ordinals))
            )));
        }
        if actual != (0..ordinals.len() as i64).collect() {
            return Err(occurrence_missing(format!(
                "Field {} occurrence ordinal 이 0..n-1 이 아니다: {}",
                quoted(field),
                python_repr(&json!(ordinals))
            )));
        }
    }
    Ok(())
}

fn validate_coverage(
    root: &HashSet<String>,
    shared: &HashMap<String, HashSet<String>>,
    options: &HashMap<OptionRegionRef, HashSet<String>>,
    covered: &OccurrenceCoverage,
) -> Result<(), ExecutionStructureError> {
    let mut missing = Vec::new();
    missing.extend(
        root.iter()
            .filter(|field| !covered.root.contains(*field))
            .map(|field| format!("root:{field}")),
    );
    for (slot, fields) in shared {
        missing.extend(
            fields
                .iter()
                .filter(|field| !covered.shared.contains(&(slot.clone(), (*field).clone())))
                .map(|field| format!("shared:{slot}/{field}")),
        );
    }
    for (option, fields) in options {
        missing.extend(
            fields
                .iter()
                .filter(|field| !covered.option.contains(&(option.clone(), (*field).clone())))
                .map(|field| format!("option:{}/{}/{}", option.slot_id, option.option_id, field)),
        );
    }
    if !missing.is_empty() {
        missing.sort();
        return Err(occurrence_missing(format!(
            "occurrence 가 없는 product Field: {}",
            python_repr(&json!(missing))
        )));
    }
    Ok(())
}

pub(super) fn validate_occurrences(
    occurrences: &[FieldOccurrence],
    product: &TemplateStructure,
    entries: &HashSet<String>,
) -> Result<(), ExecutionStructureError> {
    let (root, shared, options) = product_index(product)?;
    let mut covered = OccurrenceCoverage::default();
    let mut by_field: HashMap<&str, Vec<i64>> = HashMap::new();
    let mut orders = HashSet::new();
    for occ in occurrences {
        validate_occurrence_fields(occ, entries)?;
        validate_occurrence_owner(occ, &root, &shared, &options, &mut covered)?;
        if !orders.insert(occ.structural_order) {
            return Err(integrity(format!(
                "structural_order 중복: {}",
                occ.structural_order
            )));
        }
        by_field
            .entry(&occ.field_id)
            .or_default()
            .push(occ.occurrence_ordinal);
    }
    validate_ordinals(by_field)?;
    validate_coverage(&root, &shared, &options, &covered)?;
    Ok(())
}

type StoredSpans<'a> = BTreeMap<OptionRegionRef, (&'a str, (i64, i64))>;

fn validate_stored_resolver_facts(
    facts: &BTreeMap<String, bool>,
) -> Result<(), ExecutionStructureError> {
    for key in RESOLVER_STABILITY_KEYS {
        if !facts.contains_key(key) {
            return Err(resolver_missing(format!(
                "resolver stability fact {key:?} 부재"
            )));
        }
    }
    Ok(())
}

fn collect_stored_spans<'a>(
    structure: &'a ExecutionTemplateStructure,
    options: &HashMap<OptionRegionRef, HashSet<String>>,
    entry_ids: &HashSet<String>,
) -> Result<StoredSpans<'a>, ExecutionStructureError> {
    let mut spans = BTreeMap::new();
    for region in &structure.option_regions {
        if region
            .owner_relation_facts
            .iter()
            .chain(&region.retained_content_relation_facts)
            .any(|fact| !fact.is_object())
        {
            return Err(integrity(format!(
                "{} payload 형식 불일치",
                structure.projection_schema_version
            )));
        }
        let key = OptionRegionRef {
            slot_id: region.slot_id.clone(),
            option_id: region.option_id.clone(),
        };
        if !options.contains_key(&key) || spans.contains_key(&key) {
            return Err(integrity(format!(
                "Option region product 참조 또는 중복 오류: {key:?}"
            )));
        }
        require_span(
            region.begin_order,
            region.end_order,
            &format!("Option {key:?} region"),
        )?;
        if !entry_ids.contains(&region.content_entry_id) {
            return Err(envelope_missing(format!(
                "Option region 이 미선언 content entry 참조: {:?}",
                region.content_entry_id
            )));
        }
        require_text(&region.removal_capability_ref, "removal_capability_ref")?;
        let owner_entry = region.owner_relation_facts.iter().find(|fact| {
            fact.get("relation").and_then(Value::as_str) == Some("target_owner_content_entry")
        });
        if owner_entry
            .and_then(|fact| fact.get("content_entry_id"))
            .and_then(Value::as_str)
            != Some(&region.content_entry_id)
        {
            return Err(integrity(format!(
                "Option ({},{}) owner content-entry fact 불일치",
                quoted(&region.slot_id),
                quoted(&region.option_id)
            )));
        }
        let slot_fact = region
            .owner_relation_facts
            .iter()
            .find(|fact| fact.get("relation").and_then(Value::as_str) == Some("target_owner_slot"));
        if !slot_fact
            .and_then(|fact| fact.get("coincidence"))
            .and_then(Value::as_str)
            .is_some_and(|value| {
                matches!(value, "SAME_SPAN" | "SAME_START" | "SAME_END" | "INTERIOR")
            })
        {
            return Err(integrity(format!(
                "Option ({},{}) owner slot fact 불량",
                quoted(&region.slot_id),
                quoted(&region.option_id)
            )));
        }
        spans.insert(
            key,
            (
                region.content_entry_id.as_str(),
                (region.begin_order, region.end_order),
            ),
        );
    }
    if spans.len() != options.len() {
        return Err(relation_missing("Option region 이 없는 Option"));
    }
    Ok(spans)
}

fn validate_stored_option_occurrences(
    occurrences: &[FieldOccurrence],
    spans: &StoredSpans<'_>,
) -> Result<(), ExecutionStructureError> {
    for occurrence in occurrences {
        if occurrence.owner_kind != "OPTION" {
            continue;
        }
        let key = OptionRegionRef {
            slot_id: occurrence.owner_slot_id.clone().unwrap(),
            option_id: occurrence.owner_option_id.clone().unwrap(),
        };
        let Some((entry, span)) = spans.get(&key) else {
            return Err(integrity(format!(
                "OPTION occurrence {:?} 의 region 부재",
                occurrence.field_id
            )));
        };
        if occurrence.content_entry_id != *entry
            || occurrence.structural_order < span.0
            || occurrence.structural_order > span.1
        {
            return Err(integrity(format!(
                "OPTION occurrence {:?} structural_order 가 region span 밖",
                occurrence.field_id
            )));
        }
    }
    Ok(())
}

fn validate_stored_relations(
    structure: &ExecutionTemplateStructure,
    spans: &StoredSpans<'_>,
) -> Result<(), ExecutionStructureError> {
    let keys: Vec<_> = spans.keys().cloned().collect();
    let mut expected = HashSet::new();
    for (index, left) in keys.iter().enumerate() {
        for right in &keys[index + 1..] {
            let a = spans[left].1;
            let b = spans[right].1;
            expected.insert(RemovalTargetRelation {
                left_option_ref: left.clone(),
                right_option_ref: right.clone(),
                relation: classify_span_relation(a, b).into(),
            });
        }
    }
    let stored: HashSet<_> = structure.removal_target_relations.iter().cloned().collect();
    if stored != expected || stored.len() != structure.removal_target_relations.len() {
        return Err(relation_missing(
            "removal_target_relations 가 저장 span 재계산과 불일치",
        ));
    }
    if structure.global_composition_facts.crossing_free
        != expected.iter().all(|item| item.relation != "CROSSING")
    {
        return Err(integrity("crossing_free 가 relation 과 불일치"));
    }
    Ok(())
}

pub(super) fn validate_invariants(
    structure: &ExecutionTemplateStructure,
) -> Result<(), ExecutionStructureError> {
    require_schema(&structure.projection_schema_version)?;
    if !labels_required(&structure.projection_schema_version)
        && has_labels(&structure.product_structure)
    {
        return Err(integrity(format!(
            "{} 는 label 을 싣지 않는다",
            structure.projection_schema_version
        )));
    }
    let (_, _, options) = product_index(&structure.product_structure)?;
    let entry_ids = validate_content_entries(&structure.content_entries)?;
    validate_occurrences(
        &structure.field_occurrences,
        &structure.product_structure,
        &entry_ids,
    )?;
    validate_stored_resolver_facts(&structure.global_composition_facts.resolver_stability_facts)?;
    require_text(
        &structure.global_composition_facts.admitted_relation_profile,
        "admitted_relation_profile",
    )?;
    let spans = collect_stored_spans(structure, &options, &entry_ids)?;
    validate_stored_option_occurrences(&structure.field_occurrences, &spans)?;
    validate_stored_relations(structure, &spans)?;
    Ok(())
}
