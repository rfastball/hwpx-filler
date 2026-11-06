//! Value-free, versioned statistics for a transferred job's data bindings.

use crate::mapping::FieldMapping;
use crate::text_render::python_repr;
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
use std::fmt;

pub const DATA_CONTRACT_SCHEMA: &str = "data-contract/v1";
pub const SHAPES: [&str; 4] = ["empty", "number", "date", "text"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DataContractError(pub String);
impl fmt::Display for DataContractError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for DataContractError {}
fn fail(detail: impl Into<String>) -> DataContractError {
    DataContractError(detail.into())
}
fn python_type(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(number) if number.to_string().contains(['.', 'e', 'E']) => "float",
        Value::Number(_) => "int",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldContract {
    pub field: String,
    pub column: String,
    pub binding: String,
    pub rows: u64,
    pub blanks: u64,
    pub failures: u64,
    pub shape: String,
    pub length: Option<(u64, u64)>,
}
impl FieldContract {
    pub fn validate(&self) -> Result<(), DataContractError> {
        if self.field.is_empty() || self.column.is_empty() {
            return Err(fail(
                "데이터 계약의 field·column 는 비어 있지 않은 문자열이어야 합니다",
            ));
        }
        let digest = self.binding.strip_prefix("sha256:").ok_or_else(|| {
            fail(format!(
                "데이터 계약의 binding 지문 모양이 아닙니다: {}",
                python_repr(&Value::String(self.binding.clone()))
            ))
        })?;
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(fail(format!(
                "데이터 계약의 binding 지문 모양이 아닙니다: {}",
                python_repr(&Value::String(self.binding.clone()))
            )));
        }
        if self.rows == 0 {
            return Err(fail("데이터 계약의 rows 는 1 이상이어야 합니다"));
        }
        if self.blanks > self.rows || self.failures > self.rows - self.blanks {
            return Err(fail("데이터 계약의 blanks·failures 합이 rows 보다 큽니다"));
        }
        if !SHAPES.contains(&self.shape.as_str()) {
            return Err(fail(format!(
                "모르는 값 모양 등급: {} (지원: ('empty', 'number', 'date', 'text'))",
                python_repr(&Value::String(self.shape.clone()))
            )));
        }
        match (self.shape.as_str(), self.length) {
            ("empty", None) => (),
            ("empty", Some(_)) => {
                return Err(fail("값이 없는(empty) 항목에는 길이 범위가 없어야 합니다"));
            }
            (_, None) => {
                return Err(fail(
                    "데이터 계약의 length 는 [최소, 최대] 두 정수여야 합니다",
                ));
            }
            (_, Some((low, high))) if low > high => {
                return Err(fail("데이터 계약의 length 최소가 최대보다 큽니다"));
            }
            _ => (),
        }
        Ok(())
    }
    pub fn filled(&self) -> u64 {
        self.rows - self.blanks
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DataContract {
    pub fields: Vec<FieldContract>,
}
impl DataContract {
    pub fn validate(&self) -> Result<(), DataContractError> {
        let mut names = HashSet::new();
        for field in &self.fields {
            field.validate()?;
            if !names.insert(field.field.as_str()) {
                return Err(fail("데이터 계약에 같은 필드가 두 번 있습니다"));
            }
        }
        Ok(())
    }
    pub fn entry_for(&self, name: &str) -> Option<&FieldContract> {
        self.fields.iter().find(|field| field.field == name)
    }
}

fn sorted(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let sorted: BTreeMap<_, _> = map
                .into_iter()
                .map(|(key, value)| (key, sorted(value)))
                .collect();
            Value::Object(sorted.into_iter().collect())
        }
        Value::Array(items) => Value::Array(items.into_iter().map(sorted).collect()),
        value => value,
    }
}

/// SHA-256 of the field's complete binding JSON with `template_field` omitted.
pub fn binding_fingerprint(mapping: &FieldMapping) -> String {
    let mut payload = mapping.to_dict();
    payload
        .as_object_mut()
        .expect("FieldMapping::to_dict is an object")
        .remove("template_field");
    let body = serde_json::to_string(&sorted(payload)).expect("FieldMapping JSON is serializable");
    let digest = Sha256::digest(body.as_bytes());
    let mut result = String::from("sha256:");
    for byte in digest {
        fmt::Write::write_fmt(&mut result, format_args!("{byte:02x}")).expect("String write");
    }
    result
}

pub fn encode_data_contract(contract: &DataContract) -> Result<Value, DataContractError> {
    contract.validate()?;
    let fields = contract
        .fields
        .iter()
        .map(|field| {
            let mut item = Map::new();
            item.insert("field".into(), Value::String(field.field.clone()));
            item.insert("column".into(), Value::String(field.column.clone()));
            item.insert("binding".into(), Value::String(field.binding.clone()));
            item.insert("rows".into(), Value::Number(Number::from(field.rows)));
            item.insert("blanks".into(), Value::Number(Number::from(field.blanks)));
            item.insert(
                "failures".into(),
                Value::Number(Number::from(field.failures)),
            );
            item.insert("shape".into(), Value::String(field.shape.clone()));
            item.insert(
                "length".into(),
                field.length.map_or(Value::Null, |(low, high)| {
                    Value::Array(vec![Value::from(low), Value::from(high)])
                }),
            );
            Value::Object(item)
        })
        .collect();
    let mut out = Map::new();
    out.insert("schema".into(), Value::String(DATA_CONTRACT_SCHEMA.into()));
    out.insert("fields".into(), Value::Array(fields));
    Ok(Value::Object(out))
}

fn count(value: &Value, what: &str) -> Result<u64, DataContractError> {
    value.as_u64().ok_or_else(|| {
        fail(format!(
            "데이터 계약의 {what} 는 0 이상의 정수여야 합니다: {}",
            python_repr(value)
        ))
    })
}
fn object<'a>(value: &'a Value, detail: &str) -> Result<&'a Map<String, Value>, DataContractError> {
    value.as_object().ok_or_else(|| fail(detail))
}
fn string(item: &Map<String, Value>, key: &str) -> Result<String, DataContractError> {
    item.get(key)
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| {
            fail(format!(
                "데이터 계약의 {key} 는 비어 있지 않은 문자열이어야 합니다"
            ))
        })
}
fn keys_exact(
    item: &Map<String, Value>,
    expected: &[&str],
    detail: &str,
) -> Result<(), DataContractError> {
    let expected: HashSet<_> = expected.iter().copied().collect();
    let actual: HashSet<_> = item.keys().map(String::as_str).collect();
    if actual == expected {
        Ok(())
    } else {
        let mut delta: Vec<_> = actual.symmetric_difference(&expected).copied().collect();
        delta.sort_unstable();
        Err(fail(format!(
            "{detail}: {}",
            python_repr(&Value::Array(
                delta
                    .into_iter()
                    .map(|key| Value::String(key.into()))
                    .collect()
            ))
        )))
    }
}

pub fn decode_data_contract(raw: &Value) -> Result<DataContract, DataContractError> {
    let out = object(
        raw,
        &format!(
            "데이터 계약은 사전이어야 하는데 {} 입니다",
            python_type(raw)
        ),
    )?;
    keys_exact(out, &["schema", "fields"], "데이터 계약의 키가 다릅니다")?;
    if out["schema"] != DATA_CONTRACT_SCHEMA {
        return Err(fail(format!(
            "지원하지 않는 데이터 계약: {}",
            python_repr(&out["schema"])
        )));
    }
    let entries = out["fields"]
        .as_array()
        .ok_or_else(|| fail("데이터 계약의 fields 는 목록이어야 합니다"))?;
    let mut fields = Vec::with_capacity(entries.len());
    for entry in entries {
        let item = object(entry, "데이터 계약의 항목은 사전이어야 합니다")?;
        keys_exact(
            item,
            &[
                "field", "column", "binding", "rows", "blanks", "failures", "shape", "length",
            ],
            "데이터 계약 항목의 키가 다릅니다",
        )?;
        let length = match &item["length"] {
            Value::Null => None,
            Value::Array(items) if items.len() == 2 => {
                Some((count(&items[0], "length")?, count(&items[1], "length")?))
            }
            _ => {
                return Err(fail(
                    "데이터 계약의 length 는 [최소, 최대] 두 정수여야 합니다",
                ));
            }
        };
        let binding = &item["binding"];
        let binding = binding
            .as_str()
            .filter(|value| {
                value.starts_with("sha256:")
                    && value.len() == 71
                    && value[7..]
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            .ok_or_else(|| {
                fail(format!(
                    "데이터 계약의 binding 지문 모양이 아닙니다: {}",
                    python_repr(binding)
                ))
            })?;
        let shape = &item["shape"];
        let shape = shape
            .as_str()
            .filter(|value| SHAPES.contains(value))
            .ok_or_else(|| {
                fail(format!(
                    "모르는 값 모양 등급: {} (지원: ('empty', 'number', 'date', 'text'))",
                    python_repr(shape)
                ))
            })?;
        fields.push(FieldContract {
            field: string(item, "field")?,
            column: string(item, "column")?,
            binding: binding.into(),
            rows: count(&item["rows"], "rows")?,
            blanks: count(&item["blanks"], "blanks")?,
            failures: count(&item["failures"], "failures")?,
            shape: shape.into(),
            length,
        });
    }
    let result = DataContract { fields };
    result.validate()?;
    Ok(result)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn codec_rejects_unknown_or_value_bearing_fields() {
        let mapping = FieldMapping::new("이름", "원천", "text", "", "", None).unwrap();
        let entry = FieldContract {
            field: "이름".into(),
            column: "원천".into(),
            binding: binding_fingerprint(&mapping),
            rows: 3,
            blanks: 1,
            failures: 0,
            shape: "text".into(),
            length: Some((1, 5)),
        };
        let contract = DataContract {
            fields: vec![entry],
        };
        let encoded = encode_data_contract(&contract).unwrap();
        assert_eq!(decode_data_contract(&encoded).unwrap(), contract);
        let mut tampered = encoded;
        tampered["fields"][0]["sample"] = Value::String("private value".into());
        assert!(decode_data_contract(&tampered).is_err());
    }

    #[test]
    fn durable_contract_codec_refuses_shape_skew_and_duplicate_or_value_bearing_fields() {
        let mapping = FieldMapping::new("공고명", "name", "text", "", "", None).unwrap();
        let contract = DataContract {
            fields: vec![FieldContract {
                field: "공고명".into(),
                column: "name".into(),
                binding: binding_fingerprint(&mapping),
                rows: 3,
                blanks: 1,
                failures: 0,
                shape: "text".into(),
                length: Some((4, 7)),
            }],
        };
        let encoded = encode_data_contract(&contract).unwrap();
        assert_eq!(decode_data_contract(&encoded).unwrap(), contract);
        assert!(!encoded.to_string().contains("전산장비 구매"));
        for (pointer, replacement) in [
            ("/schema", json!("data-contract/v9")),
            ("/fields/0/rows", json!(true)),
            ("/fields/0/blanks", json!(-1)),
            ("/fields/0/shape", json!("phone")),
            ("/fields/0/length", json!([7, 4])),
            ("/fields/0/binding", json!("md5:abc")),
            ("/fields/0/column", json!("")),
        ] {
            let mut damaged = encoded.clone();
            *damaged.pointer_mut(pointer).unwrap() = replacement;
            assert!(decode_data_contract(&damaged).is_err(), "{pointer}");
        }
        let mut leaked = encoded.clone();
        leaked["fields"][0]["sample"] = json!("전산장비 구매");
        assert!(decode_data_contract(&leaked).is_err());
        let mut duplicate = encoded.clone();
        duplicate["fields"]
            .as_array_mut()
            .unwrap()
            .push(encoded["fields"][0].clone());
        assert!(
            decode_data_contract(&duplicate)
                .unwrap_err()
                .0
                .contains("두 번")
        );
        let mut impossible_empty = encoded;
        impossible_empty["fields"][0]["shape"] = json!("empty");
        assert!(decode_data_contract(&impossible_empty).is_err());
    }
}
