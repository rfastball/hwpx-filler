//! Selection preset value and integrity codec; template structure remains authoritative.

use crate::slot_selection::{
    SlotSelectionSet, declared_selection_digest, decode_selection_set, encode_selection_set,
};
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fmt;

pub const PRESET_SCHEMA_VERSION: &str = "selection-preset/v1";
const PRESET_FIELDS: [&str; 6] = [
    "schema_version",
    "name",
    "selection_set",
    "declared_selection_digest",
    "provenance",
    "created_at",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PresetError(pub String);
impl fmt::Display for PresetError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for PresetError {}
fn fail(detail: impl Into<String>) -> PresetError {
    PresetError(detail.into())
}
fn repr(value: &Value) -> String {
    python_repr(value)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SelectionPreset {
    pub name: String,
    pub selection_set: SlotSelectionSet,
    /// Sorted by key, preserving immutable value semantics.
    pub provenance: Vec<(String, String)>,
    pub created_at: String,
}
impl SelectionPreset {
    pub fn new(
        name: impl Into<String>,
        selection_set: SlotSelectionSet,
        provenance: Vec<(String, String)>,
        created_at: impl Into<String>,
    ) -> Result<Self, PresetError> {
        let mut result = Self {
            name: name.into(),
            selection_set,
            provenance,
            created_at: created_at.into(),
        };
        result.validate()?;
        result.provenance.sort();
        Ok(result)
    }
    pub fn validate(&self) -> Result<(), PresetError> {
        if self.name.is_empty() {
            return Err(fail("name 는 비어 있지 않은 문자열이어야 한다"));
        }
        if self.created_at.is_empty() {
            return Err(fail("created_at 는 비어 있지 않은 문자열이어야 한다"));
        }
        self.selection_set
            .validate()
            .map_err(|error| fail(format!("selection set 복원 실패: {error}")))?;
        if self.selection_set.selections.is_empty() {
            return Err(fail("selection_set 은 비어 있을 수 없다"));
        }
        let mut seen = HashSet::new();
        for (key, _) in &self.provenance {
            if key.is_empty() {
                return Err(fail("provenance 키는 비어 있지 않은 문자열이어야 한다"));
            }
            if !seen.insert(key.as_str()) {
                return Err(fail(format!(
                    "provenance 키 중복: {}",
                    repr(&Value::String(key.clone()))
                )));
            }
        }
        Ok(())
    }
    pub fn provenance_map(&self) -> Map<String, Value> {
        self.provenance
            .iter()
            .map(|(key, value)| (key.clone(), Value::String(value.clone())))
            .collect()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CorruptPresetEntry {
    pub file_name: String,
    pub error: String,
}

pub fn encode_preset(preset: &SelectionPreset) -> Result<Value, PresetError> {
    preset.validate()?;
    let mut out = Map::new();
    out.insert(
        "schema_version".into(),
        Value::String(PRESET_SCHEMA_VERSION.into()),
    );
    out.insert("name".into(), Value::String(preset.name.clone()));
    out.insert(
        "selection_set".into(),
        encode_selection_set(&preset.selection_set).map_err(|error| fail(error.to_string()))?,
    );
    out.insert(
        "declared_selection_digest".into(),
        Value::String(
            declared_selection_digest(&preset.selection_set)
                .map_err(|error| fail(error.to_string()))?,
        ),
    );
    out.insert("provenance".into(), Value::Object(preset.provenance_map()));
    out.insert(
        "created_at".into(),
        Value::String(preset.created_at.clone()),
    );
    Ok(Value::Object(out))
}
pub fn decode_preset(raw: &Value) -> Result<SelectionPreset, PresetError> {
    let data = raw
        .as_object()
        .ok_or_else(|| fail("preset 표현이 malformed"))?;
    let schema = data.get("schema_version").unwrap_or(&Value::Null);
    if schema != PRESET_SCHEMA_VERSION {
        return Err(fail(format!("미상 preset schema_version {}", repr(schema))));
    }
    let mut unknown: Vec<_> = data
        .keys()
        .filter(|key| !PRESET_FIELDS.contains(&key.as_str()))
        .cloned()
        .collect();
    unknown.sort();
    if !unknown.is_empty() {
        return Err(fail(format!(
            "미지 preset 필드: {}",
            repr(&Value::Array(
                unknown.into_iter().map(Value::String).collect()
            ))
        )));
    }
    let set = decode_selection_set(data.get("selection_set").unwrap_or(&Value::Null))
        .map_err(|error| fail(format!("selection set 복원 실패: {error}")))?;
    let actual_digest = declared_selection_digest(&set).map_err(|error| fail(error.to_string()))?;
    if data.get("declared_selection_digest") != Some(&Value::String(actual_digest)) {
        return Err(fail(
            "저장된 selection digest 가 복원 selection 과 불일치(손상·드리프트)",
        ));
    }
    let name = nonempty(data.get("name"), "name")?;
    let created_at = nonempty(data.get("created_at"), "created_at")?;
    let provenance = data
        .get("provenance")
        .and_then(Value::as_object)
        .ok_or_else(|| fail("provenance 는 평평한 문자열 매핑이어야 한다"))?;
    let mut pairs = Vec::new();
    for (key, value) in provenance {
        if key.is_empty() {
            return Err(fail("provenance 키는 비어 있지 않은 문자열이어야 한다"));
        }
        let value = value.as_str().ok_or_else(|| {
            fail(format!(
                "provenance 값은 문자열이어야 한다: {}",
                repr(&Value::String(key.clone()))
            ))
        })?;
        pairs.push((key.clone(), value.into()));
    }
    SelectionPreset::new(name, set, pairs, created_at)
}
fn nonempty(value: Option<&Value>, what: &str) -> Result<String, PresetError> {
    value
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| fail(format!("{what} 는 비어 있지 않은 문자열이어야 한다")))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::slot_selection::SlotSelection;

    #[test]
    fn preset_integrity_rejects_tampered_selection_and_extra_structure() {
        use serde_json::json;
        let set = SlotSelectionSet::new(vec![SlotSelection::new("s", vec!["a".into()]).unwrap()])
            .unwrap();
        let preset = SelectionPreset::new(
            "선택",
            set,
            vec![("source".into(), "work".into())],
            "2026-01-01",
        )
        .unwrap();
        let encoded = encode_preset(&preset).unwrap();
        assert_eq!(decode_preset(&encoded).unwrap(), preset);
        let mut tampered = encoded.clone();
        tampered["selection_set"]["selections"][0]["selected_option_ids"][0] =
            Value::String("b".into());
        assert!(decode_preset(&tampered).unwrap_err().0.contains("digest"));
        let mut extra = encoded.clone();
        extra["slot_structure"] = Value::Array(Vec::new());
        assert!(decode_preset(&extra).is_err());
        assert_eq!(
            encoded
                .as_object()
                .unwrap()
                .keys()
                .cloned()
                .collect::<HashSet<_>>(),
            PRESET_FIELDS.into_iter().map(str::to_owned).collect()
        );
        assert_eq!(
            encoded["selection_set"]["selections"][0],
            json!({"slot_id":"s", "selected_option_ids":["a"]})
        );
        let make =
            |pairs| SelectionPreset::new("선택", preset.selection_set.clone(), pairs, "2026-01-01");
        let first = make(vec![("a".into(), "1".into()), ("b".into(), "2".into())]).unwrap();
        assert_eq!(
            first,
            make(vec![("b".into(), "2".into()), ("a".into(), "1".into())]).unwrap()
        );
        let mut copied = first.provenance_map();
        copied.insert("a".into(), json!("changed"));
        assert_eq!(first.provenance_map()["a"], "1");
        assert!(make(vec![]).unwrap().provenance_map().is_empty());
        for invalid in [
            vec![("".into(), "value".into())],
            vec![("a".into(), "1".into()), ("a".into(), "2".into())],
        ] {
            assert!(make(invalid).is_err());
        }
        for field in PRESET_FIELDS {
            let mut missing = encoded.clone();
            missing.as_object_mut().unwrap().remove(field);
            assert!(decode_preset(&missing).is_err(), "missing {field}");
        }
        for (field, value) in [
            ("schema_version", json!("selection-preset/v99")),
            ("name", json!("")),
            ("name", Value::Null),
            ("created_at", json!("")),
            ("created_at", json!(42)),
            ("selection_set", json!({"selections":"invalid"})),
            ("provenance", json!("invalid")),
            ("provenance", json!({"nested":{}})),
            ("provenance", json!({"list":[]})),
            ("provenance", json!({"number":1})),
            ("provenance", json!({"":"value"})),
        ] {
            let mut invalid = encoded.clone();
            invalid[field] = value;
            assert!(decode_preset(&invalid).is_err(), "invalid {field}");
        }
        assert!(decode_preset(&json!([])).is_err());
        for invalid in [
            SelectionPreset {
                name: String::new(),
                ..preset.clone()
            },
            SelectionPreset {
                created_at: String::new(),
                ..preset.clone()
            },
            SelectionPreset {
                selection_set: SlotSelectionSet::default(),
                ..preset.clone()
            },
        ] {
            assert!(encode_preset(&invalid).is_err());
        }
    }
}
