//! Pure slot-selection/v1 value language and canonical identity.

use crate::text_render::python_repr;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fmt;

pub const SELECTION_SET_SCHEMA_VERSION: &str = "slot-selection-set/v1";
pub const CANONICAL_ENCODING_VERSION: &str = "slot-selection-canonical/v1";
pub const EXACTLY_ONE: &str = "EXACTLY_ONE";
pub const SATISFIED: &str = "SATISFIED";
pub const MISSING_REQUIRED_SELECTION: &str = "MISSING_REQUIRED_SELECTION";
pub const CARDINALITY_VIOLATION: &str = "CARDINALITY_VIOLATION";
pub const NO_AVAILABLE_OPTIONS: &str = "NO_AVAILABLE_OPTIONS";
const MAGIC: &[u8; 8] = b"HFPSEL1\0";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SelectionErrorKind {
    Invalid,
    CanonicalEncoding,
    UnsupportedContract,
    ContractIntegrity,
    UnsupportedPolicy,
}
impl SelectionErrorKind {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "INVALID_SELECTION_SET",
            Self::CanonicalEncoding => "CANONICAL_SELECTION_ENCODING_ERROR",
            Self::UnsupportedContract => "UNSUPPORTED_SELECTION_SEMANTIC_CONTRACT",
            Self::ContractIntegrity => "SELECTION_CONTRACT_INTEGRITY_ERROR",
            Self::UnsupportedPolicy => "UNSUPPORTED_SELECTION_POLICY",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SelectionError {
    pub kind: SelectionErrorKind,
    pub detail: String,
}
impl fmt::Display for SelectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for SelectionError {}
fn error(kind: SelectionErrorKind, detail: impl Into<String>) -> SelectionError {
    SelectionError {
        kind,
        detail: detail.into(),
    }
}
fn repr(text: &str) -> String {
    python_repr(&Value::String(text.into()))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SlotSelection {
    pub slot_id: String,
    pub selected_option_ids: Vec<String>,
}
impl SlotSelection {
    pub fn new(
        slot_id: impl Into<String>,
        selected_option_ids: Vec<String>,
    ) -> Result<Self, SelectionError> {
        let result = Self {
            slot_id: slot_id.into(),
            selected_option_ids,
        };
        result.validate()?;
        Ok(result)
    }
    pub fn validate(&self) -> Result<(), SelectionError> {
        if self.slot_id.is_empty() {
            return Err(error(
                SelectionErrorKind::Invalid,
                "slot_id 는 비어 있지 않은 문자열이어야 한다",
            ));
        }
        if self.selected_option_ids.is_empty() {
            return Err(error(
                SelectionErrorKind::Invalid,
                "selected_option_ids 는 비어 있을 수 없다",
            ));
        }
        let mut seen = HashSet::new();
        for option in &self.selected_option_ids {
            if option.is_empty() {
                return Err(error(
                    SelectionErrorKind::Invalid,
                    "option_id 는 비어 있지 않은 문자열이어야 한다",
                ));
            }
            if !seen.insert(option.as_str()) {
                return Err(error(
                    SelectionErrorKind::Invalid,
                    format!("한 entry 안에서 option ID 중복: {}", repr(option)),
                ));
            }
        }
        Ok(())
    }
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SlotSelectionSet {
    pub selections: Vec<SlotSelection>,
}
impl SlotSelectionSet {
    pub fn new(selections: Vec<SlotSelection>) -> Result<Self, SelectionError> {
        let result = Self { selections };
        result.validate()?;
        Ok(result)
    }
    pub fn validate(&self) -> Result<(), SelectionError> {
        let mut seen = HashSet::new();
        for selection in &self.selections {
            selection.validate()?;
            if !seen.insert(selection.slot_id.as_str()) {
                return Err(error(
                    SelectionErrorKind::Invalid,
                    format!("같은 slot_id entry 중복: {}", repr(&selection.slot_id)),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SelectionSemanticContractManifest {
    pub contract_id: String,
    pub selection_set_schema_version: String,
    pub canonical_encoding_version: String,
    pub default_selection_policy: String,
    pub supported_selection_policies: Vec<String>,
    pub created_semantics_version: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct SelectionSemanticBindingKey {
    pub qualification_profile_id: String,
    pub structure_projection_schema_version: String,
}
#[derive(Clone, Debug)]
pub struct SelectionSemanticContractRegistry {
    by_key: HashMap<SelectionSemanticBindingKey, String>,
    by_id: HashMap<String, SelectionSemanticContractManifest>,
}
impl SelectionSemanticContractRegistry {
    pub fn new(
        bindings: impl IntoIterator<
            Item = (
                SelectionSemanticBindingKey,
                SelectionSemanticContractManifest,
            ),
        >,
    ) -> Result<Self, SelectionError> {
        let mut result = Self {
            by_key: HashMap::new(),
            by_id: HashMap::new(),
        };
        for (key, manifest) in bindings {
            if !manifest
                .supported_selection_policies
                .contains(&manifest.default_selection_policy)
            {
                return Err(error(
                    SelectionErrorKind::ContractIntegrity,
                    format!("default policy 가 supported 밖: {}", manifest.contract_id),
                ));
            }
            if result
                .by_id
                .get(&manifest.contract_id)
                .is_some_and(|existing| existing != &manifest)
            {
                return Err(error(
                    SelectionErrorKind::ContractIntegrity,
                    format!(
                        "같은 contract ID 의 다른 manifest: {}",
                        manifest.contract_id
                    ),
                ));
            }
            if result
                .by_key
                .get(&key)
                .is_some_and(|existing| existing != &manifest.contract_id)
            {
                return Err(error(
                    SelectionErrorKind::ContractIntegrity,
                    "같은 binding key 를 다른 contract 로 재매핑",
                ));
            }
            result.by_key.insert(key, manifest.contract_id.clone());
            result.by_id.insert(manifest.contract_id.clone(), manifest);
        }
        Ok(result)
    }
    pub fn resolve(
        &self,
        key: &SelectionSemanticBindingKey,
    ) -> Result<&SelectionSemanticContractManifest, SelectionError> {
        let Some(id) = self.by_key.get(key) else {
            return Err(error(
                SelectionErrorKind::UnsupportedContract,
                format!("미지원 selection semantic binding: {key:?}"),
            ));
        };
        Ok(&self.by_id[id])
    }
    pub fn get(&self, id: &str) -> Result<&SelectionSemanticContractManifest, SelectionError> {
        self.by_id.get(id).ok_or_else(|| {
            error(
                SelectionErrorKind::UnsupportedContract,
                format!("미지원 selection semantic contract: {id}"),
            )
        })
    }
}
pub fn default_selection_semantic_registry() -> SelectionSemanticContractRegistry {
    let manifest = SelectionSemanticContractManifest {
        contract_id: "slot-selection/v1".into(),
        selection_set_schema_version: SELECTION_SET_SCHEMA_VERSION.into(),
        canonical_encoding_version: CANONICAL_ENCODING_VERSION.into(),
        default_selection_policy: EXACTLY_ONE.into(),
        supported_selection_policies: vec![EXACTLY_ONE.into()],
        created_semantics_version: "s4-selection-semantics/v1".into(),
    };
    SelectionSemanticContractRegistry::new([
        (
            SelectionSemanticBindingKey {
                qualification_profile_id: "hwpx-template-qualification-v4".into(),
                structure_projection_schema_version: "hwpx-structure-projection-v4".into(),
            },
            manifest.clone(),
        ),
        (
            SelectionSemanticBindingKey {
                qualification_profile_id: "txt-template-qualification-v1".into(),
                structure_projection_schema_version: "txt-structure-projection-v1".into(),
            },
            manifest,
        ),
    ])
    .expect("static registry is coherent")
}
pub fn resolve_selection_policy(
    contract: &SelectionSemanticContractManifest,
    declared: Option<&str>,
) -> Result<String, SelectionError> {
    let Some(declared) = declared else {
        return Ok(contract.default_selection_policy.clone());
    };
    if !contract
        .supported_selection_policies
        .iter()
        .any(|value| value == declared)
    {
        return Err(error(
            SelectionErrorKind::UnsupportedPolicy,
            format!(
                "contract {} 미지원 정책: {}",
                contract.contract_id,
                repr(declared)
            ),
        ));
    }
    Ok(declared.into())
}
pub fn evaluate_slot(
    policy: &str,
    available_option_count: usize,
    selected_option_count: usize,
) -> Result<&'static str, SelectionError> {
    if policy != EXACTLY_ONE {
        return Err(error(
            SelectionErrorKind::UnsupportedPolicy,
            format!("미지원 정책: {}", repr(policy)),
        ));
    }
    Ok(if available_option_count == 0 {
        NO_AVAILABLE_OPTIONS
    } else if selected_option_count == 0 {
        MISSING_REQUIRED_SELECTION
    } else if selected_option_count == 1 {
        SATISFIED
    } else {
        CARDINALITY_VIOLATION
    })
}

fn write_u32(out: &mut Vec<u8>, len: usize, what: &str) -> Result<(), SelectionError> {
    let number = u32::try_from(len).map_err(|_| {
        error(
            SelectionErrorKind::CanonicalEncoding,
            format!("{what} 가 u32 범위 초과"),
        )
    })?;
    out.extend_from_slice(&number.to_be_bytes());
    Ok(())
}
fn write_text(out: &mut Vec<u8>, text: &str) -> Result<(), SelectionError> {
    write_u32(out, text.len(), "UTF-8 byte length")?;
    out.extend_from_slice(text.as_bytes());
    Ok(())
}
pub fn canonicalize_selection_set(
    contract_id: &str,
    set: &SlotSelectionSet,
) -> Result<Vec<u8>, SelectionError> {
    if contract_id.is_empty() {
        return Err(error(
            SelectionErrorKind::Invalid,
            "contract_id 는 비어 있지 않은 문자열이어야 한다",
        ));
    }
    set.validate()?;
    let mut out = MAGIC.to_vec();
    write_text(&mut out, SELECTION_SET_SCHEMA_VERSION)?;
    write_text(&mut out, contract_id)?;
    write_u32(&mut out, set.selections.len(), "count")?;
    let mut selections: Vec<_> = set.selections.iter().collect();
    selections.sort_by(|a, b| a.slot_id.as_bytes().cmp(b.slot_id.as_bytes()));
    for selection in selections {
        write_text(&mut out, &selection.slot_id)?;
        write_u32(&mut out, selection.selected_option_ids.len(), "count")?;
        let mut options: Vec<_> = selection.selected_option_ids.iter().collect();
        options.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
        for option in options {
            write_text(&mut out, option)?;
        }
    }
    Ok(out)
}
pub fn digest_selection_set(
    contract_id: &str,
    set: &SlotSelectionSet,
) -> Result<String, SelectionError> {
    let bytes = canonicalize_selection_set(contract_id, set)?;
    let hash = Sha256::digest(&bytes);
    let mut result = String::from("sha256:");
    for byte in hash {
        fmt::Write::write_fmt(&mut result, format_args!("{byte:02x}")).expect("String write");
    }
    Ok(result)
}
pub fn semantic_selection_equal(
    left: &SlotSelectionSet,
    right: &SlotSelectionSet,
) -> Result<bool, SelectionError> {
    Ok(
        canonicalize_selection_set(SELECTION_SET_SCHEMA_VERSION, left)?
            == canonicalize_selection_set(SELECTION_SET_SCHEMA_VERSION, right)?,
    )
}
pub fn declared_selection_digest(set: &SlotSelectionSet) -> Result<String, SelectionError> {
    digest_selection_set(SELECTION_SET_SCHEMA_VERSION, set)
}
pub fn encode_selection_set(set: &SlotSelectionSet) -> Result<Value, SelectionError> {
    set.validate()?;
    let selections = set
        .selections
        .iter()
        .map(|selection| {
            let mut item = Map::new();
            item.insert("slot_id".into(), Value::String(selection.slot_id.clone()));
            item.insert(
                "selected_option_ids".into(),
                Value::Array(
                    selection
                        .selected_option_ids
                        .iter()
                        .cloned()
                        .map(Value::String)
                        .collect(),
                ),
            );
            Value::Object(item)
        })
        .collect();
    let mut out = Map::new();
    out.insert("selections".into(), Value::Array(selections));
    Ok(Value::Object(out))
}
pub fn decode_selection_set(raw: &Value) -> Result<SlotSelectionSet, SelectionError> {
    let Some(selections) = raw
        .as_object()
        .and_then(|data| data.get("selections"))
        .and_then(Value::as_array)
    else {
        return Err(error(
            SelectionErrorKind::Invalid,
            "selection set 표현이 malformed",
        ));
    };
    let mut out = Vec::with_capacity(selections.len());
    for entry in selections {
        let Some(data) = entry.as_object() else {
            return Err(error(
                SelectionErrorKind::Invalid,
                "selection entry 가 malformed",
            ));
        };
        let Some(options) = data.get("selected_option_ids").and_then(Value::as_array) else {
            return Err(error(
                SelectionErrorKind::Invalid,
                "selected_option_ids 는 리스트여야 한다",
            ));
        };
        let slot_id = data
            .get("slot_id")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| {
                error(
                    SelectionErrorKind::Invalid,
                    "slot_id 는 비어 있지 않은 문자열이어야 한다",
                )
            })?;
        let mut selected = Vec::new();
        for option in options {
            let option = option
                .as_str()
                .filter(|value| !value.is_empty())
                .ok_or_else(|| {
                    error(
                        SelectionErrorKind::Invalid,
                        "option_id 는 비어 있지 않은 문자열이어야 한다",
                    )
                })?;
            selected.push(option.into());
        }
        out.push(SlotSelection::new(slot_id, selected)?);
    }
    SlotSelectionSet::new(out)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn existing_shared_golden_vectors_keep_canonical_bytes_and_digest() {
        let golden = include_str!("../../../tests/fixtures/slot_selection_v1_golden.json");
        let frozen_bytes = Sha256::digest(golden.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        assert_eq!(
            frozen_bytes,
            "f2ac6b526ece7635a1c907151ba2ffe9026a264ac7a8f00f7792902a249bc023"
        );
        let fixture: Value = serde_json::from_str(golden).unwrap();
        assert_eq!(CANONICAL_ENCODING_VERSION, "slot-selection-canonical/v1");
        assert_eq!(SELECTION_SET_SCHEMA_VERSION, "slot-selection-set/v1");
        for vector in fixture["vectors"].as_array().unwrap() {
            let selections = vector["selections"]
                .as_array()
                .unwrap()
                .iter()
                .map(|item| {
                    SlotSelection::new(
                        item[0].as_str().unwrap(),
                        item[1]
                            .as_array()
                            .unwrap()
                            .iter()
                            .map(|value| value.as_str().unwrap().to_owned())
                            .collect(),
                    )
                    .unwrap()
                })
                .collect();
            let set = SlotSelectionSet::new(selections).unwrap();
            let bytes =
                canonicalize_selection_set(fixture["contract_id"].as_str().unwrap(), &set).unwrap();
            assert_eq!(
                bytes
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect::<String>(),
                vector["canonical_hex"]
            );
            assert_eq!(
                digest_selection_set(fixture["contract_id"].as_str().unwrap(), &set).unwrap(),
                vector["digest"]
            );
            assert_eq!(
                decode_selection_set(&encode_selection_set(&set).unwrap()).unwrap(),
                set
            );
        }
    }

    #[test]
    fn registry_and_exactly_one_policy_refuse_unknown_semantics() {
        let registry = default_selection_semantic_registry();
        let hwpx_key = SelectionSemanticBindingKey {
            qualification_profile_id: "hwpx-template-qualification-v4".into(),
            structure_projection_schema_version: "hwpx-structure-projection-v4".into(),
        };
        let txt_key = SelectionSemanticBindingKey {
            qualification_profile_id: "txt-template-qualification-v1".into(),
            structure_projection_schema_version: "txt-structure-projection-v1".into(),
        };
        let manifest = registry.resolve(&hwpx_key).unwrap();
        assert_eq!(registry.resolve(&txt_key).unwrap(), manifest);
        assert_eq!(manifest.contract_id, "slot-selection/v1");
        assert_eq!(
            resolve_selection_policy(manifest, None).unwrap(),
            EXACTLY_ONE
        );
        assert_eq!(
            resolve_selection_policy(manifest, Some("ZERO_OR_ONE"))
                .unwrap_err()
                .kind,
            SelectionErrorKind::UnsupportedPolicy
        );
        assert_eq!(
            registry
                .resolve(&SelectionSemanticBindingKey {
                    qualification_profile_id: "unknown".into(),
                    structure_projection_schema_version: "unknown".into(),
                })
                .unwrap_err()
                .kind,
            SelectionErrorKind::UnsupportedContract
        );
        assert_eq!(
            registry.get("slot-selection/v2").unwrap_err().kind,
            SelectionErrorKind::UnsupportedContract
        );
        let mut unsupported_default = manifest.clone();
        unsupported_default.supported_selection_policies.clear();
        assert_eq!(
            SelectionSemanticContractRegistry::new([(hwpx_key.clone(), unsupported_default)])
                .unwrap_err()
                .kind,
            SelectionErrorKind::ContractIntegrity
        );
        let mut same_key_different_contract = manifest.clone();
        same_key_different_contract.contract_id = "slot-selection/v2".into();
        assert_eq!(
            SelectionSemanticContractRegistry::new([
                (hwpx_key.clone(), manifest.clone()),
                (hwpx_key.clone(), same_key_different_contract),
            ])
            .unwrap_err()
            .kind,
            SelectionErrorKind::ContractIntegrity
        );
        let mut same_contract_different_body = manifest.clone();
        same_contract_different_body.created_semantics_version = "changed".into();
        assert_eq!(
            SelectionSemanticContractRegistry::new([
                (hwpx_key, manifest.clone()),
                (txt_key, same_contract_different_body),
            ])
            .unwrap_err()
            .kind,
            SelectionErrorKind::ContractIntegrity
        );
        for (available, selected, expected) in [
            (0, 0, NO_AVAILABLE_OPTIONS),
            (0, 1, NO_AVAILABLE_OPTIONS),
            (3, 0, MISSING_REQUIRED_SELECTION),
            (3, 1, SATISFIED),
            (3, 2, CARDINALITY_VIOLATION),
        ] {
            assert_eq!(
                evaluate_slot(EXACTLY_ONE, available, selected).unwrap(),
                expected
            );
        }
        assert_eq!(
            evaluate_slot("MANY", 3, 2).unwrap_err().kind,
            SelectionErrorKind::UnsupportedPolicy
        );
    }

    #[test]
    fn malformed_selection_is_loud_and_semantic_identity_preserves_unicode() {
        for (slot, options) in [
            ("", vec!["o".into()]),
            ("s", vec![]),
            ("s", vec!["".into()]),
            ("s", vec!["o".into(), "o".into()]),
        ] {
            assert_eq!(
                SlotSelection::new(slot, options).unwrap_err().kind,
                SelectionErrorKind::Invalid
            );
        }
        let first = SlotSelection::new("s", vec!["a".into(), "b".into()]).unwrap();
        let reordered = SlotSelection::new("s", vec!["b".into(), "a".into()]).unwrap();
        assert_eq!(
            SlotSelectionSet::new(vec![first.clone(), reordered.clone()])
                .unwrap_err()
                .kind,
            SelectionErrorKind::Invalid
        );
        let a = SlotSelectionSet::new(vec![first]).unwrap();
        let b = SlotSelectionSet::new(vec![reordered]).unwrap();
        assert!(semantic_selection_equal(&a, &b).unwrap());
        assert_eq!(
            declared_selection_digest(&a).unwrap(),
            declared_selection_digest(&b).unwrap()
        );
        assert_eq!(
            decode_selection_set(&encode_selection_set(&a).unwrap()).unwrap(),
            a
        );
        for malformed in [
            json!({"selections":"not a list"}),
            json!({"selections":["not an entry"]}),
            json!({"selections":[{"slot_id":"s","selected_option_ids":"o"}]}),
        ] {
            assert_eq!(
                decode_selection_set(&malformed).unwrap_err().kind,
                SelectionErrorKind::Invalid
            );
        }
        let nfc = SlotSelectionSet::new(vec![SlotSelection::new("가", vec!["o".into()]).unwrap()])
            .unwrap();
        let nfd = SlotSelectionSet::new(vec![SlotSelection::new("가", vec!["o".into()]).unwrap()])
            .unwrap();
        assert!(!semantic_selection_equal(&nfc, &nfd).unwrap());
        assert_eq!(
            write_u32(&mut Vec::new(), u32::MAX as usize + 1, "count")
                .unwrap_err()
                .kind,
            SelectionErrorKind::CanonicalEncoding
        );
    }
}
