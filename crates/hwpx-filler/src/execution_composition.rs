//! Closed composition/primitive pair identity. Structural premise admission is a separate gate.

use crate::execution_structure::{
    ExecutionTemplateStructure, content_digest, is_supported_execution_projection,
    template_structure_digest,
};
use crate::text_render::python_repr;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fmt;

pub const COMPOSITION_CONTRACT_ID: &str = "hwpx-composition/v1";
pub const NATIVE_PRIMITIVE_CONTRACT_ID: &str = "hwpx-native-primitive/v1";
pub const TXT_COMPOSITION_CONTRACT_ID: &str = "txt-composition/v1";
pub const TXT_NATIVE_PRIMITIVE_CONTRACT_ID: &str = "txt-line-primitive/v1";
pub const COMPOSITION_FINGERPRINT_HWPX: &str =
    "sha256:783dae86f3541de41ecb3789da2509dff2436ee82be01a703d4c89697d7647dd";
pub const COMPOSITION_FINGERPRINT_TXT: &str =
    "sha256:1b8cb932f7f03cba1ed1082e7c86c1e1a1d324e74b031e3df9e9e595beb8cf04";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CompositionErrorKind {
    UnsupportedComposition,
    UnsupportedNativePrimitive,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompositionError {
    pub kind: CompositionErrorKind,
    pub detail: String,
}
impl fmt::Display for CompositionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for CompositionError {}
fn repr(text: &str) -> String {
    python_repr(&Value::String(text.into()))
}
fn pair_repr(pair: &(String, String)) -> String {
    format!("({}, {})", repr(&pair.0), repr(&pair.1))
}
fn pair_pair_repr(pair: &((String, String), (String, String))) -> String {
    format!("({}, {})", pair_repr(&pair.0), pair_repr(&pair.1))
}
fn missing_relation_pairs_repr<'a>(
    pairs: impl IntoIterator<Item = &'a ((String, String), (String, String))>,
) -> String {
    let parts: Vec<_> = pairs
        .into_iter()
        .map(|pair| {
            format!(
                "frozenset({{{}, {}}})",
                pair_repr(&pair.0),
                pair_repr(&pair.1)
            )
        })
        .collect();
    format!("[{}]", parts.join(", "))
}
fn occurrence_list_repr(items: impl IntoIterator<Item = (String, i64)>) -> String {
    let parts: Vec<_> = items
        .into_iter()
        .map(|(field, ordinal)| format!("({}, {ordinal})", repr(&field)))
        .collect();
    format!("[{}]", parts.join(", "))
}

pub fn composition_fingerprint(
    composition: &str,
    primitive: &str,
) -> Result<&'static str, CompositionError> {
    let (expected, digest) = match composition {
        COMPOSITION_CONTRACT_ID => (NATIVE_PRIMITIVE_CONTRACT_ID, COMPOSITION_FINGERPRINT_HWPX),
        TXT_COMPOSITION_CONTRACT_ID => (
            TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
            COMPOSITION_FINGERPRINT_TXT,
        ),
        _ => {
            return Err(CompositionError {
                kind: CompositionErrorKind::UnsupportedComposition,
                detail: format!("미지원 composition contract: {}", repr(composition)),
            });
        }
    };
    if primitive != expected {
        return Err(CompositionError {
            kind: CompositionErrorKind::UnsupportedNativePrimitive,
            detail: format!("미지원 native primitive contract: {}", repr(primitive)),
        });
    }
    Ok(digest)
}

pub const PASS: &str = "PASS";
pub const OK: &str = "OK";
pub const FAILED: &str = "FAILED";
pub const INCOMPLETE: &str = "INCOMPLETE";
pub const PREMISE_IDS: [&str; 10] = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"];
pub fn classify_target_target_admission(relation: &str) -> &'static str {
    match relation {
        "DISJOINT" | "TOUCHING" => OK,
        "CONTAINS" | "CONTAINED" | "SAME_SPAN" | "CROSSING" => FAILED,
        _ => INCOMPLETE,
    }
}
pub fn is_owner_coincidence_admitted(
    coincidence: &str,
    marker: bool,
    boundary: bool,
) -> &'static str {
    match coincidence {
        "INTERIOR" => OK,
        "SAME_SPAN" | "SAME_START" | "SAME_END" => {
            if marker && boundary {
                OK
            } else {
                FAILED
            }
        }
        _ => INCOMPLETE,
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativePrimitiveContractManifest {
    pub native_primitive_contract_id: String,
    pub option_resolver_contract_id: String,
    pub option_removal_contract_id: String,
    pub field_resolver_contract_id: String,
    pub field_write_contract_id: String,
    pub envelope_postcondition_contract_id: String,
    pub intentional_blank_write_contract_id: String,
    pub primitive_semantics_version: String,
}
pub fn resolve_native_primitive_contract(
    id: &str,
) -> Result<NativePrimitiveContractManifest, CompositionError> {
    let (option_resolver, option_removal, field_resolver, field_write, envelope, blank) = match id {
        NATIVE_PRIMITIVE_CONTRACT_ID => (
            "hwpx-option-resolver/v1",
            "remove-option/v1",
            "hwpx-field-resolver/v1",
            "hwpx-field-write/v1",
            "hwpx-envelope-postcondition/v1",
            "hwpx-intentional-blank/v1",
        ),
        TXT_NATIVE_PRIMITIVE_CONTRACT_ID => (
            "txt-option-resolver/v1",
            "txt-remove-option-lines/v1",
            "txt-field-token-resolver/v1",
            "txt-plaintext-write/v1",
            "txt-line-envelope-postcondition/v1",
            "txt-intentional-blank/v1",
        ),
        _ => {
            return Err(CompositionError {
                kind: CompositionErrorKind::UnsupportedNativePrimitive,
                detail: format!(
                    "미지원 native primitive contract(latest fallback 없음): {}",
                    repr(id)
                ),
            });
        }
    };
    Ok(NativePrimitiveContractManifest {
        native_primitive_contract_id: id.into(),
        option_resolver_contract_id: option_resolver.into(),
        option_removal_contract_id: option_removal.into(),
        field_resolver_contract_id: field_resolver.into(),
        field_write_contract_id: field_write.into(),
        envelope_postcondition_contract_id: envelope.into(),
        intentional_blank_write_contract_id: blank.into(),
        primitive_semantics_version: "1".into(),
    })
}
pub fn encode_native_primitive_contract(item: &NativePrimitiveContractManifest) -> Value {
    json!({"native_primitive_contract_id":item.native_primitive_contract_id,
        "option_resolver_contract_id":item.option_resolver_contract_id,
        "option_removal_contract_id":item.option_removal_contract_id,
        "field_resolver_contract_id":item.field_resolver_contract_id,
        "field_write_contract_id":item.field_write_contract_id,
        "envelope_postcondition_contract_id":item.envelope_postcondition_contract_id,
        "intentional_blank_write_contract_id":item.intentional_blank_write_contract_id,
        "primitive_semantics_version":item.primitive_semantics_version})
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeMaterializerConformanceManifest {
    pub runtime_capability_manifest_digest: String,
    pub materialization_contract_id: String,
    pub materialization_base_contract_id: String,
    pub native_primitive_contract_id: String,
    pub admitted_composition_contract_ids: Vec<String>,
    pub supported_plan_schema_versions: Vec<String>,
    pub supported_canonical_encoding_versions: Vec<String>,
    pub conformance_status: String,
}
pub fn runtime_conformance_digest(m: &RuntimeMaterializerConformanceManifest) -> String {
    let sorted = |items: &Vec<String>| {
        let mut items = items.clone();
        items.sort();
        items
    };
    content_digest(
        &json!({"runtime_capability_manifest_digest":m.runtime_capability_manifest_digest,
        "materialization_contract_id":m.materialization_contract_id,
        "materialization_base_contract_id":m.materialization_base_contract_id,
        "native_primitive_contract_id":m.native_primitive_contract_id,
        "admitted_composition_contract_ids":sorted(&m.admitted_composition_contract_ids),
        "supported_plan_schema_versions":sorted(&m.supported_plan_schema_versions),
        "supported_canonical_encoding_versions":sorted(&m.supported_canonical_encoding_versions),
        "conformance_status":m.conformance_status}),
    )
}
#[derive(Default)]
pub struct RuntimeMaterializerConformanceRegistry {
    admitted: Vec<RuntimeMaterializerConformanceManifest>,
}
pub struct RuntimeConformanceQuery<'a> {
    pub runtime_capability_manifest_digest: &'a str,
    pub materialization_contract_id: &'a str,
    pub materialization_base_contract_id: &'a str,
    pub native_primitive_contract_id: &'a str,
    pub composition_contract_id: &'a str,
    pub plan_schema_version: &'a str,
    pub canonical_encoding_version: &'a str,
}
impl RuntimeMaterializerConformanceRegistry {
    pub fn register(
        &mut self,
        m: RuntimeMaterializerConformanceManifest,
    ) -> Result<(), CompositionError> {
        if m.conformance_status != PASS {
            return Err(CompositionError {
                kind: CompositionErrorKind::UnsupportedNativePrimitive,
                detail: format!(
                    "PASS 아닌 conformance 는 등록 불가: {}",
                    repr(&m.conformance_status)
                ),
            });
        }
        self.admitted.push(m);
        Ok(())
    }
    pub fn is_admitted(&self, q: &RuntimeConformanceQuery<'_>) -> bool {
        self.admitted.iter().any(|m| {
            m.runtime_capability_manifest_digest == q.runtime_capability_manifest_digest
                && m.materialization_contract_id == q.materialization_contract_id
                && m.materialization_base_contract_id == q.materialization_base_contract_id
                && m.native_primitive_contract_id == q.native_primitive_contract_id
                && m.admitted_composition_contract_ids
                    .iter()
                    .any(|id| id == q.composition_contract_id)
                && m.supported_plan_schema_versions
                    .iter()
                    .any(|id| id == q.plan_schema_version)
                && m.supported_canonical_encoding_versions
                    .iter()
                    .any(|id| id == q.canonical_encoding_version)
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PremiseOutcome {
    pub status: &'static str,
    pub reason: String,
}
fn outcome(status: &'static str, reason: impl Into<String>) -> PremiseOutcome {
    PremiseOutcome {
        status,
        reason: reason.into(),
    }
}
fn ok() -> PremiseOutcome {
    outcome(OK, "")
}
fn bool_fact(facts: &BTreeMap<String, bool>, key: &str) -> PremiseOutcome {
    match facts.get(key) {
        Some(true) => ok(),
        Some(false) => outcome(FAILED, format!("{key}=False")),
        None => outcome(INCOMPLETE, format!("{key} fact 부재/비-bool")),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompositionPremisesPassed {
    pub composition_contract_id: String,
    pub native_primitive_contract_id: String,
    pub template_structure_digest: String,
    pub theorem_evidence_manifest_digest: String,
    pub verified_premise_facts: Value,
    pub premise_verification_digest: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompositionPremisesBlocked {
    pub code: String,
    pub premise_id: String,
    pub reason: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CompositionPremiseContextError {
    pub code: String,
    pub premise_id: Option<String>,
    pub reason: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CompositionPremiseVerificationResult {
    Passed(CompositionPremisesPassed),
    Blocked(CompositionPremisesBlocked),
    ContextError(CompositionPremiseContextError),
}

fn c1(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    let mut seen = HashSet::new();
    for r in &s.option_regions {
        if !seen.insert((&r.slot_id, &r.option_id)) {
            return outcome(FAILED, "RemoveOption target 이 서로 다른 Option 이 아니다");
        }
    }
    ok()
}
fn c2(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    let refs: BTreeSet<_> = s
        .option_regions
        .iter()
        .map(|r| (r.slot_id.clone(), r.option_id.clone()))
        .collect();
    let ordered: Vec<_> = refs.iter().cloned().collect();
    let mut expected = BTreeSet::new();
    for i in 0..ordered.len() {
        for j in i + 1..ordered.len() {
            expected.insert((ordered[i].clone(), ordered[j].clone()));
        }
    }
    let mut seen = BTreeSet::new();
    for rel in &s.removal_target_relations {
        let left = (
            rel.left_option_ref.slot_id.clone(),
            rel.left_option_ref.option_id.clone(),
        );
        let right = (
            rel.right_option_ref.slot_id.clone(),
            rel.right_option_ref.option_id.clone(),
        );
        if !refs.contains(&left) || !refs.contains(&right) || left == right {
            return outcome(
                INCOMPLETE,
                format!(
                    "relation 이 존재하지 않는/동일 Option 을 참조: {}·{}",
                    pair_repr(&left),
                    pair_repr(&right)
                ),
            );
        }
        let pair = if left < right {
            (left, right)
        } else {
            (right, left)
        };
        if !seen.insert(pair.clone()) {
            return outcome(
                INCOMPLETE,
                format!("중복 relation fact: {}", pair_pair_repr(&pair)),
            );
        }
        match classify_target_target_admission(&rel.relation) {
            INCOMPLETE => {
                return outcome(
                    INCOMPLETE,
                    format!("미지 relation 어휘: {}", repr(&rel.relation)),
                );
            }
            FAILED => {
                return outcome(
                    FAILED,
                    format!(
                        "admit 불가 relation {} @ {}",
                        rel.relation,
                        pair_pair_repr(&pair)
                    ),
                );
            }
            _ => {}
        }
    }
    if seen != expected {
        return outcome(
            INCOMPLETE,
            format!(
                "target-target pair 집합 불완전: 누락 {}",
                missing_relation_pairs_repr(expected.difference(&seen))
            ),
        );
    }
    ok()
}
fn c3(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    bool_fact(
        &s.global_composition_facts.resolver_stability_facts,
        "remaining_target_resolvable_after_removal",
    )
}
fn c4(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    let entries: HashMap<_, _> = s
        .content_entries
        .iter()
        .map(|e| (e.content_entry_id.as_str(), &e.envelope_capability_facts))
        .collect();
    for region in &s.option_regions {
        let fact = region
            .owner_relation_facts
            .iter()
            .find(|f| f.get("relation") == Some(&json!("target_owner_slot")));
        let Some(coincidence) = fact
            .and_then(|f| f.get("coincidence"))
            .and_then(Value::as_str)
        else {
            return outcome(
                INCOMPLETE,
                format!("owner coincidence fact 부재 @ {}", region.option_id),
            );
        };
        let Some(envelope) = entries.get(region.content_entry_id.as_str()) else {
            return outcome(
                INCOMPLETE,
                format!("region content entry envelope 부재 @ {}", region.option_id),
            );
        };
        let (Some(marker), Some(boundary)) = (
            envelope.get("preserves_owner_marker"),
            envelope.get("coincident_boundary_admissible"),
        ) else {
            return outcome(
                INCOMPLETE,
                format!("owner envelope fact 부재 @ {}", region.option_id),
            );
        };
        match is_owner_coincidence_admitted(coincidence, *marker, *boundary) {
            INCOMPLETE => {
                return outcome(
                    INCOMPLETE,
                    format!("미지 coincidence 어휘 @ {}", region.option_id),
                );
            }
            FAILED => {
                return outcome(
                    FAILED,
                    format!("owner coincidence admit 불가 @ {}", region.option_id),
                );
            }
            _ => {}
        }
    }
    ok()
}
fn c5(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    for slot in &s.product_structure.slots {
        if slot.options.is_empty() {
            return outcome(
                FAILED,
                format!("Slot {} 이 selected Option 을 유지 못 한다", repr(&slot.id)),
            );
        }
    }
    ok()
}
fn c6(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    for region in &s.option_regions {
        let expected: BTreeSet<_> = s
            .field_occurrences
            .iter()
            .filter(|occ| {
                !(occ.owner_kind == "OPTION"
                    && occ.owner_slot_id.as_deref() == Some(&region.slot_id)
                    && occ.owner_option_id.as_deref() == Some(&region.option_id))
            })
            .map(|occ| (occ.field_id.clone(), occ.occurrence_ordinal))
            .collect();
        let mut positions = BTreeMap::new();
        for fact in &region.retained_content_relation_facts {
            let Some(field) = fact.get("field_id").and_then(Value::as_str) else {
                return outcome(
                    INCOMPLETE,
                    format!(
                        "retained fact 의 occurrence 식별자 부재 @ {}",
                        region.option_id
                    ),
                );
            };
            let Some(ordinal) = fact.get("occurrence_ordinal").and_then(Value::as_i64) else {
                return outcome(
                    INCOMPLETE,
                    format!(
                        "retained fact 의 occurrence 식별자 부재 @ {}",
                        region.option_id
                    ),
                );
            };
            let position = fact.get("position").and_then(Value::as_str);
            if !matches!(position, Some("BEFORE" | "INSIDE" | "AFTER")) {
                return outcome(
                    INCOMPLETE,
                    format!(
                        "retained position 어휘 밖({}) @ {}",
                        fact.get("position").map_or("None".into(), python_repr),
                        region.option_id
                    ),
                );
            }
            positions.insert((field.into(), ordinal), position.unwrap_or_default());
        }
        let actual: BTreeSet<_> = positions.keys().cloned().collect();
        if actual != expected {
            return outcome(
                INCOMPLETE,
                format!(
                    "retained 집합 불완전 @ {}: 누락 {}·잉여 {}",
                    region.option_id,
                    occurrence_list_repr(expected.difference(&actual).cloned()),
                    occurrence_list_repr(actual.difference(&expected).cloned())
                ),
            );
        }
        for ((field, _), position) in positions {
            if position == "INSIDE" {
                return outcome(
                    FAILED,
                    format!(
                        "retained content {} 가 removal target 안 @ {}",
                        repr(&field),
                        region.option_id
                    ),
                );
            }
        }
    }
    ok()
}
fn c7(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    let premise = bool_fact(
        &s.global_composition_facts.resolver_stability_facts,
        "active_field_resolvable_after_removal",
    );
    if premise.status != OK {
        return premise;
    }
    for occ in &s.field_occurrences {
        if occ.native_value_target_class.is_empty() || occ.resolver_contract_id.is_empty() {
            return outcome(
                INCOMPLETE,
                format!(
                    "Active Field {} value target/resolver fact 부재",
                    repr(&occ.field_id)
                ),
            );
        }
    }
    ok()
}
fn c8(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    bool_fact(
        &s.global_composition_facts.resolver_stability_facts,
        "field_write_preserves_identity",
    )
}
fn c9(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    let mut by_field: BTreeMap<&str, Vec<i64>> = BTreeMap::new();
    for occ in &s.field_occurrences {
        by_field
            .entry(&occ.field_id)
            .or_default()
            .push(occ.occurrence_ordinal);
    }
    for (field, ordinals) in by_field {
        let actual: BTreeSet<_> = ordinals.iter().copied().collect();
        let expected: BTreeSet<_> = (0..ordinals.len() as i64).collect();
        if actual != expected {
            return outcome(
                INCOMPLETE,
                format!(
                    "Field {} occurrence identity 가 canonical 하지 않다",
                    repr(field)
                ),
            );
        }
    }
    ok()
}
fn c10(s: &ExecutionTemplateStructure) -> PremiseOutcome {
    let affected: BTreeSet<_> = s
        .option_regions
        .iter()
        .map(|r| r.content_entry_id.as_str())
        .chain(
            s.field_occurrences
                .iter()
                .map(|o| o.content_entry_id.as_str()),
        )
        .collect();
    let entries: HashMap<_, _> = s
        .content_entries
        .iter()
        .map(|e| (e.content_entry_id.as_str(), &e.envelope_capability_facts))
        .collect();
    for entry in affected {
        let Some(facts) = entries.get(entry) else {
            return outcome(
                INCOMPLETE,
                format!("affected content entry envelope 부재: {entry}"),
            );
        };
        for key in ["retains_admissible_envelope", "handles_empty_edges"] {
            match facts.get(key) {
                Some(true) => {}
                Some(false) => return outcome(FAILED, format!("{entry} 가 {key} 를 유지 못 한다")),
                None => return outcome(INCOMPLETE, format!("{entry} envelope fact {key} 부재")),
            }
        }
    }
    ok()
}
pub fn evaluate_composition_premises(
    s: &ExecutionTemplateStructure,
) -> BTreeMap<&'static str, PremiseOutcome> {
    BTreeMap::from([
        ("C1", c1(s)),
        ("C2", c2(s)),
        ("C3", c3(s)),
        ("C4", c4(s)),
        ("C5", c5(s)),
        ("C6", c6(s)),
        ("C7", c7(s)),
        ("C8", c8(s)),
        ("C9", c9(s)),
        ("C10", c10(s)),
    ])
}
fn context_error(
    code: &str,
    premise: Option<&str>,
    reason: impl Into<String>,
) -> CompositionPremiseVerificationResult {
    CompositionPremiseVerificationResult::ContextError(CompositionPremiseContextError {
        code: code.into(),
        premise_id: premise.map(str::to_owned),
        reason: reason.into(),
    })
}
fn verified_premise_facts(
    s: &ExecutionTemplateStructure,
    outcomes: &BTreeMap<&'static str, PremiseOutcome>,
) -> Value {
    let mut counts = BTreeMap::<String, usize>::new();
    for rel in &s.removal_target_relations {
        *counts.entry(rel.relation.clone()).or_default() += 1;
    }
    let mut owners = BTreeMap::from([
        ("ROOT".to_owned(), 0usize),
        ("SLOT_SHARED".to_owned(), 0usize),
        ("OPTION".to_owned(), 0usize),
    ]);
    for occ in &s.field_occurrences {
        *owners.entry(occ.owner_kind.clone()).or_default() += 1;
    }
    let proven: BTreeMap<_, _> = PREMISE_IDS
        .iter()
        .map(|id| (*id, outcomes[id].status))
        .collect();
    json!({"premises_proven":proven,"crossing_free":s.global_composition_facts.crossing_free,
        "target_target_relation_counts":counts,
        "attested_target_target_relations":["DISJOINT","TOUCHING"],
        "occurrence_owner_kind_counts":owners,
        "removal_target_count":s.option_regions.len()})
}
pub fn admit_composition_premises(
    s: &ExecutionTemplateStructure,
    primitive: &NativePrimitiveContractManifest,
    composition: &str,
) -> CompositionPremiseVerificationResult {
    if !is_supported_execution_projection(&s.projection_schema_version) {
        return context_error(
            "UNSUPPORTED_EXECUTION_STRUCTURE_PROJECTION",
            None,
            format!(
                "미지원 execution structure projection schema: {}",
                repr(&s.projection_schema_version)
            ),
        );
    }
    let expected_pair = match composition {
        COMPOSITION_CONTRACT_ID => NATIVE_PRIMITIVE_CONTRACT_ID,
        TXT_COMPOSITION_CONTRACT_ID => TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
        _ => {
            return context_error(
                "UNSUPPORTED_COMPOSITION_CONTRACT",
                None,
                format!("미지원 composition contract: {}", repr(composition)),
            );
        }
    };
    if primitive.native_primitive_contract_id != expected_pair {
        return context_error(
            "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT",
            None,
            format!(
                "미지원 native primitive contract: {}",
                repr(&primitive.native_primitive_contract_id)
            ),
        );
    }
    let canonical = resolve_native_primitive_contract(expected_pair).expect("static primitive");
    if primitive != &canonical {
        return context_error(
            "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT",
            None,
            "native primitive contract 가 등록된 canonical 과 불일치(같은 ID 의미 수정 금지)",
        );
    }
    for occ in &s.field_occurrences {
        if occ.resolver_contract_id != primitive.field_resolver_contract_id {
            return context_error(
                "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT",
                Some("C7"),
                format!(
                    "Field {} resolver {} 가 native primitive field resolver {} 와 불일치",
                    repr(&occ.field_id),
                    repr(&occ.resolver_contract_id),
                    repr(&primitive.field_resolver_contract_id)
                ),
            );
        }
    }
    for region in &s.option_regions {
        if region.removal_capability_ref != primitive.option_removal_contract_id {
            return context_error(
                "UNSUPPORTED_NATIVE_PRIMITIVE_CONTRACT",
                Some("C2"),
                format!(
                    "Option {} removal {} 가 native primitive removal {} 와 불일치",
                    repr(&region.option_id),
                    repr(&region.removal_capability_ref),
                    repr(&primitive.option_removal_contract_id)
                ),
            );
        }
    }
    let outcomes = evaluate_composition_premises(s);
    for id in PREMISE_IDS {
        let verdict = &outcomes[id];
        if verdict.status == INCOMPLETE {
            return context_error(
                "EXECUTION_COMPOSITION_PREMISE_INCOMPLETE",
                Some(id),
                &verdict.reason,
            );
        }
    }
    for id in PREMISE_IDS {
        let verdict = &outcomes[id];
        if verdict.status == FAILED {
            return CompositionPremiseVerificationResult::Blocked(CompositionPremisesBlocked {
                code: "EXECUTION_COMPOSITION_PREMISE_FAILED".into(),
                premise_id: id.into(),
                reason: verdict.reason.clone(),
            });
        }
    }
    let facts = verified_premise_facts(s, &outcomes);
    let structure_digest = template_structure_digest(s);
    let fingerprint = composition_fingerprint(composition, &primitive.native_primitive_contract_id)
        .expect("checked pair");
    let digest = content_digest(&json!({"composition_contract_id":composition,
        "native_primitive_contract_id":primitive.native_primitive_contract_id,
        "template_structure_digest":structure_digest,
        "theorem_evidence_manifest_digest":fingerprint,
        "verified_premise_facts":facts}));
    CompositionPremiseVerificationResult::Passed(CompositionPremisesPassed {
        composition_contract_id: composition.into(),
        native_primitive_contract_id: primitive.native_primitive_contract_id.clone(),
        template_structure_digest: structure_digest,
        theorem_evidence_manifest_digest: fingerprint.into(),
        verified_premise_facts: facts,
        premise_verification_digest: digest,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::execution_structure::{
        ContentEntry, FieldOccurrence, GlobalCompositionFacts, OptionRegion, OptionRegionRef,
        RemovalTargetRelation, TemplateSlot, TemplateStructure,
    };
    #[test]
    fn closed_pair_and_field_premises_gate_static_admission() {
        let mut capabilities = BTreeMap::new();
        capabilities.insert("retains_admissible_envelope".into(), true);
        capabilities.insert("handles_empty_edges".into(), true);
        capabilities.insert("preserves_owner_marker".into(), true);
        capabilities.insert("coincident_boundary_admissible".into(), true);
        let facts = BTreeMap::from([
            ("remaining_target_resolvable_after_removal".into(), true),
            ("active_field_resolvable_after_removal".into(), true),
            ("field_write_preserves_identity".into(), true),
        ]);
        let mut structure = ExecutionTemplateStructure {
            projection_schema_version: "hwpx-structure-projection-v2".into(),
            product_structure: TemplateStructure {
                root_fields: vec!["f".into()],
                slots: vec![],
            },
            field_occurrences: vec![FieldOccurrence {
                field_id: "f".into(),
                occurrence_ordinal: 0,
                owner_kind: "ROOT".into(),
                owner_slot_id: None,
                owner_option_id: None,
                content_entry_id: "e".into(),
                structural_order: 0,
                native_value_target_class: "text".into(),
                resolver_contract_id: "hwpx-field-resolver/v1".into(),
            }],
            option_regions: vec![],
            removal_target_relations: vec![],
            content_entries: vec![ContentEntry {
                content_entry_id: "e".into(),
                envelope_class: "para".into(),
                envelope_capability_facts: capabilities,
            }],
            global_composition_facts: GlobalCompositionFacts {
                crossing_free: true,
                resolver_stability_facts: facts,
                admitted_relation_profile: "rel/v1".into(),
            },
        };
        let primitive = resolve_native_primitive_contract(NATIVE_PRIMITIVE_CONTRACT_ID).unwrap();
        let CompositionPremiseVerificationResult::Passed(pass) =
            admit_composition_premises(&structure, &primitive, COMPOSITION_CONTRACT_ID)
        else {
            panic!("valid field premise must pass")
        };
        assert_eq!(pass.verified_premise_facts["premises_proven"]["C10"], "OK");
        assert_eq!(
            pass.theorem_evidence_manifest_digest,
            COMPOSITION_FINGERPRINT_HWPX
        );
        structure
            .global_composition_facts
            .resolver_stability_facts
            .insert("field_write_preserves_identity".into(), false);
        let CompositionPremiseVerificationResult::Blocked(blocked) =
            admit_composition_premises(&structure, &primitive, COMPOSITION_CONTRACT_ID)
        else {
            panic!("false C8 must block")
        };
        assert_eq!(blocked.premise_id, "C8");
        structure
            .global_composition_facts
            .resolver_stability_facts
            .insert("field_write_preserves_identity".into(), true);
        structure
            .global_composition_facts
            .resolver_stability_facts
            .insert("active_field_resolvable_after_removal".into(), false);
        let CompositionPremiseVerificationResult::Blocked(blocked) =
            admit_composition_premises(&structure, &primitive, COMPOSITION_CONTRACT_ID)
        else {
            panic!("unresolvable active field must block")
        };
        assert_eq!(blocked.premise_id, "C7");
        structure
            .global_composition_facts
            .resolver_stability_facts
            .insert("active_field_resolvable_after_removal".into(), true);
        structure.content_entries[0]
            .envelope_capability_facts
            .insert("retains_admissible_envelope".into(), false);
        let CompositionPremiseVerificationResult::Blocked(blocked) =
            admit_composition_premises(&structure, &primitive, COMPOSITION_CONTRACT_ID)
        else {
            panic!("lost native envelope must block")
        };
        assert_eq!(blocked.premise_id, "C10");
        let wrong = resolve_native_primitive_contract(TXT_NATIVE_PRIMITIVE_CONTRACT_ID).unwrap();
        assert!(matches!(
            admit_composition_premises(&structure, &wrong, COMPOSITION_CONTRACT_ID),
            CompositionPremiseVerificationResult::ContextError(_)
        ));
    }

    #[test]
    fn relation_facts_must_cover_each_distinct_removal_target_pair_once() {
        let option = |id: &str| OptionRegion {
            slot_id: "s".into(),
            option_id: id.into(),
            content_entry_id: "e".into(),
            begin_order: 0,
            end_order: 1,
            owner_relation_facts: vec![],
            retained_content_relation_facts: vec![],
            removal_capability_ref: "remove-option/v1".into(),
        };
        let mut structure = ExecutionTemplateStructure {
            projection_schema_version: "hwpx-structure-projection-v2".into(),
            product_structure: TemplateStructure::default(),
            field_occurrences: vec![],
            option_regions: vec![option("one"), option("two")],
            removal_target_relations: vec![],
            content_entries: vec![],
            global_composition_facts: GlobalCompositionFacts {
                crossing_free: true,
                resolver_stability_facts: BTreeMap::new(),
                admitted_relation_profile: "rel/v1".into(),
            },
        };
        let status = |structure: &ExecutionTemplateStructure, premise: &str| {
            evaluate_composition_premises(structure)[premise].status
        };
        assert_eq!(status(&structure, "C2"), INCOMPLETE);
        let relation = RemovalTargetRelation {
            left_option_ref: OptionRegionRef {
                slot_id: "s".into(),
                option_id: "one".into(),
            },
            right_option_ref: OptionRegionRef {
                slot_id: "s".into(),
                option_id: "two".into(),
            },
            relation: "DISJOINT".into(),
        };
        structure.removal_target_relations.push(relation.clone());
        assert_eq!(status(&structure, "C2"), OK);
        structure.removal_target_relations.push(relation);
        assert_eq!(status(&structure, "C2"), INCOMPLETE);
        structure.removal_target_relations.pop();
        structure.removal_target_relations[0].relation = "CROSSING".into();
        assert_eq!(status(&structure, "C2"), FAILED);
        structure.removal_target_relations[0].relation = "UNKNOWN".into();
        assert_eq!(status(&structure, "C2"), INCOMPLETE);
        assert_eq!(status(&structure, "C4"), INCOMPLETE);
        structure.content_entries.push(ContentEntry {
            content_entry_id: "e".into(),
            envelope_class: "section".into(),
            envelope_capability_facts: BTreeMap::from([
                ("preserves_owner_marker".into(), false),
                ("coincident_boundary_admissible".into(), true),
            ]),
        });
        for region in &mut structure.option_regions {
            region.owner_relation_facts = vec![json!({
                "relation": "target_owner_slot",
                "coincidence": "SAME_SPAN"
            })];
        }
        assert_eq!(status(&structure, "C4"), FAILED);
        structure.content_entries[0]
            .envelope_capability_facts
            .insert("preserves_owner_marker".into(), true);
        assert_eq!(status(&structure, "C4"), OK);
        structure.product_structure.slots.push(TemplateSlot {
            id: "s".into(),
            shared_fields: vec![],
            options: vec![],
            label: None,
        });
        assert_eq!(status(&structure, "C5"), FAILED);
        structure.field_occurrences.push(FieldOccurrence {
            field_id: "f".into(),
            occurrence_ordinal: 0,
            owner_kind: "ROOT".into(),
            owner_slot_id: None,
            owner_option_id: None,
            content_entry_id: "e".into(),
            structural_order: 0,
            native_value_target_class: "text".into(),
            resolver_contract_id: "hwpx-field-resolver/v1".into(),
        });
        assert_eq!(status(&structure, "C6"), INCOMPLETE);
        for region in &mut structure.option_regions {
            region.retained_content_relation_facts = vec![json!({
                "field_id": "f",
                "occurrence_ordinal": 0,
                "position": "INSIDE"
            })];
        }
        assert_eq!(status(&structure, "C6"), FAILED);
        structure.option_regions.push(option("one"));
        assert_eq!(status(&structure, "C1"), FAILED);
    }

    #[test]
    fn runtime_conformance_requires_all_axes_and_pass_status() {
        let manifest = RuntimeMaterializerConformanceManifest {
            runtime_capability_manifest_digest: "sha256:runtime".into(),
            materialization_contract_id: "materialization/v1".into(),
            materialization_base_contract_id: "base/v1".into(),
            native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID.into(),
            admitted_composition_contract_ids: vec![COMPOSITION_CONTRACT_ID.into()],
            supported_plan_schema_versions: vec!["plan/v1".into()],
            supported_canonical_encoding_versions: vec!["encoding/v1".into()],
            conformance_status: PASS.into(),
        };
        let query = RuntimeConformanceQuery {
            runtime_capability_manifest_digest: "sha256:runtime",
            materialization_contract_id: "materialization/v1",
            materialization_base_contract_id: "base/v1",
            native_primitive_contract_id: NATIVE_PRIMITIVE_CONTRACT_ID,
            composition_contract_id: COMPOSITION_CONTRACT_ID,
            plan_schema_version: "plan/v1",
            canonical_encoding_version: "encoding/v1",
        };
        let mut registry = RuntimeMaterializerConformanceRegistry::default();
        assert!(!registry.is_admitted(&query));
        let mut failed = manifest.clone();
        failed.conformance_status = FAILED.into();
        assert!(registry.register(failed).is_err());
        registry.register(manifest.clone()).unwrap();
        assert!(registry.is_admitted(&query));
        assert!(!registry.is_admitted(&RuntimeConformanceQuery {
            runtime_capability_manifest_digest: "sha256:other",
            ..query
        }));
        assert!(!registry.is_admitted(&RuntimeConformanceQuery {
            native_primitive_contract_id: TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
            ..query
        }));
        assert!(!registry.is_admitted(&RuntimeConformanceQuery {
            plan_schema_version: "plan/v2",
            ..query
        }));
        let mut reordered = manifest;
        reordered
            .supported_plan_schema_versions
            .push("plan/v0".into());
        let digest = runtime_conformance_digest(&reordered);
        reordered.supported_plan_schema_versions.reverse();
        assert_eq!(runtime_conformance_digest(&reordered), digest);
    }
}
