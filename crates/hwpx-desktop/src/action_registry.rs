//! Exact browser dispatch vocabulary. Payload values remain with the product controller.

use serde::Deserialize;
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::sync::OnceLock;

#[derive(Debug, Deserialize)]
pub struct PayloadSchema {
    required: Vec<String>,
    optional: Vec<String>,
}

type Registry = BTreeMap<String, BTreeMap<String, PayloadSchema>>;

fn registry() -> &'static Registry {
    static REGISTRY: OnceLock<Registry> = OnceLock::new();
    REGISTRY.get_or_init(|| {
        serde_json::from_str(include_str!("action_registry.json"))
            .expect("embedded action registry must be valid")
    })
}

pub fn schema(screen: &str, action: &str) -> Option<&'static PayloadSchema> {
    registry().get(screen)?.get(action)
}

#[derive(Debug, PartialEq, Eq)]
pub enum DispatchError {
    UnknownScreen(String),
    UnknownAction {
        screen: String,
        action: String,
    },
    PayloadNotObject {
        screen: String,
        action: String,
        kind: &'static str,
    },
    SchemaMismatch {
        screen: String,
        action: String,
        missing: Vec<String>,
        unexpected: Vec<String>,
    },
}

fn repr(text: &str) -> String {
    format!("'{text}'")
}
fn repr_list(items: &[String]) -> String {
    format!(
        "[{}]",
        items
            .iter()
            .map(|item| repr(item))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

impl fmt::Display for DispatchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownScreen(screen) => write!(f, "등록되지 않은 화면: {}", repr(screen)),
            Self::UnknownAction { screen, action } => {
                write!(f, "등록되지 않은 {} 액션: {}", repr(screen), repr(action))
            }
            Self::PayloadNotObject {
                screen,
                action,
                kind,
            } => {
                write!(
                    f,
                    "{}/{} payload는 객체여야 합니다: {kind}",
                    repr(screen),
                    repr(action)
                )
            }
            Self::SchemaMismatch {
                screen,
                action,
                missing,
                unexpected,
            } => {
                write!(
                    f,
                    "{}/{} payload 스키마 불일치: ",
                    repr(screen),
                    repr(action)
                )?;
                if !missing.is_empty() {
                    write!(f, "필수 키 누락={}", repr_list(missing))?;
                }
                if !missing.is_empty() && !unexpected.is_empty() {
                    write!(f, ", ")?;
                }
                if !unexpected.is_empty() {
                    write!(f, "미등록 키={}", repr_list(unexpected))?;
                }
                Ok(())
            }
        }
    }
}
impl std::error::Error for DispatchError {}

fn json_kind(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(number) if number.is_i64() || number.is_u64() => "int",
        Value::Number(_) => "float",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

pub fn validate_dispatch<'a>(
    screen: &str,
    action: &str,
    payload: &'a Value,
) -> Result<&'a Map<String, Value>, DispatchError> {
    let actions = registry()
        .get(screen)
        .ok_or_else(|| DispatchError::UnknownScreen(screen.into()))?;
    let schema = actions
        .get(action)
        .ok_or_else(|| DispatchError::UnknownAction {
            screen: screen.into(),
            action: action.into(),
        })?;
    let object = payload
        .as_object()
        .ok_or_else(|| DispatchError::PayloadNotObject {
            screen: screen.into(),
            action: action.into(),
            kind: json_kind(payload),
        })?;
    let keys: BTreeSet<_> = object.keys().map(String::as_str).collect();
    let missing: Vec<_> = schema
        .required
        .iter()
        .filter(|key| !keys.contains(key.as_str()))
        .cloned()
        .collect();
    let unexpected: Vec<_> = keys
        .into_iter()
        .filter(|key| {
            !schema
                .required
                .iter()
                .chain(&schema.optional)
                .any(|allowed| allowed == *key)
        })
        .map(str::to_owned)
        .collect();
    if !missing.is_empty() || !unexpected.is_empty() {
        return Err(DispatchError::SchemaMismatch {
            screen: screen.into(),
            action: action.into(),
            missing,
            unexpected,
        });
    }
    Ok(object)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{DispatchError, schema, validate_dispatch};
    use serde_json::json;

    #[test]
    fn browser_dispatch_rejects_unknown_and_malformed_actions_before_controller() {
        assert!(schema("tutorial", "observe_ui").is_some());
        assert_eq!(
            validate_dispatch("missing", "new", &json!({})).unwrap_err(),
            DispatchError::UnknownScreen("missing".into())
        );
        assert!(matches!(
            validate_dispatch("authoring", "missing", &json!({})),
            Err(DispatchError::UnknownAction { .. })
        ));
        assert!(matches!(
            validate_dispatch("authoring", "new", &json!(null)),
            Err(DispatchError::PayloadNotObject {
                kind: "NoneType",
                ..
            })
        ));
        assert!(
            validate_dispatch(
                "authoring",
                "new",
                &json!({"media": "hwpx", "content": "x"})
            )
            .is_ok()
        );
        let error = validate_dispatch("authoring", "new", &json!({"typo": 1})).unwrap_err();
        assert!(
            matches!(error, DispatchError::SchemaMismatch { missing, unexpected, .. } if missing == ["media"] && unexpected == ["typo"])
        );
    }
}
