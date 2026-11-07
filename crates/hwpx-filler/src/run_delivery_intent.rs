//! Session-scoped output directory and collision intent.

use crate::text_render::python_repr;
use serde_json::Value;
use std::fmt;

pub const COLLISION_POLICIES: [&str; 3] = ["ADD_SUFFIX", "FAIL", "OVERWRITE_EXPLICIT"];
pub const DEFAULT_COLLISION_POLICY: &str = "OVERWRITE_EXPLICIT";
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunDeliveryIntent {
    pub output_directory: String,
    pub collision_policy: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunDeliveryIntentError(pub String);
impl fmt::Display for RunDeliveryIntentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for RunDeliveryIntentError {}
impl RunDeliveryIntent {
    pub fn new(output_directory: impl Into<String>) -> Result<Self, RunDeliveryIntentError> {
        let item = Self {
            output_directory: output_directory.into(),
            collision_policy: DEFAULT_COLLISION_POLICY.into(),
        };
        item.validate()?;
        Ok(item)
    }
    pub fn validate(&self) -> Result<(), RunDeliveryIntentError> {
        if self.output_directory.is_empty() {
            return Err(RunDeliveryIntentError(
                "output_directory 는 비어 있지 않은 문자열이어야 한다".into(),
            ));
        }
        if !COLLISION_POLICIES.contains(&self.collision_policy.as_str()) {
            return Err(RunDeliveryIntentError(format!(
                "미지원 collision policy: {}",
                python_repr(&Value::String(self.collision_policy.clone()))
            )));
        }
        Ok(())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    #[test]
    fn intent_keeps_session_default_and_refuses_unknown_collision_policy() {
        let mut intent = RunDeliveryIntent::new("C:/out").unwrap();
        assert_eq!(intent.collision_policy, "OVERWRITE_EXPLICIT");
        assert!(COLLISION_POLICIES.contains(&intent.collision_policy.as_str()));
        assert!(RunDeliveryIntent::new("").is_err());
        intent.collision_policy = "latest".into();
        assert_eq!(
            intent.validate().unwrap_err().to_string(),
            "미지원 collision policy: 'latest'"
        );
    }
}
