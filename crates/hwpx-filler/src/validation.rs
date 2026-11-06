//! Pure preflight of required template fields against selected data rows.

use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::collections::HashSet;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ValidationReport {
    pub missing_columns: Vec<String>,
    pub empty_valued: Vec<String>,
}

impl ValidationReport {
    pub fn has_issues(&self) -> bool {
        !self.missing_columns.is_empty() || !self.empty_valued.is_empty()
    }
}

/// The caller supplies ordered required fields and ordered selected records.
pub fn validate(required_fields: &[String], records: &[Map<String, Value>]) -> ValidationReport {
    let mut report = ValidationReport::default();
    if records.is_empty() {
        report.missing_columns = required_fields.to_vec();
        return report;
    }
    let all_keys: HashSet<&str> = records
        .iter()
        .flat_map(|record| record.keys().map(String::as_str))
        .collect();
    for field in required_fields {
        if !all_keys.contains(field.as_str()) {
            report.missing_columns.push(field.clone());
            continue;
        }
        if records.iter().any(|record| {
            let Some(value) = record.get(field) else {
                return true;
            };
            if value.is_null() {
                return true;
            }
            let text = match value {
                Value::String(text) => text.clone(),
                value => python_repr(value),
            };
            python_trim(&text).is_empty()
        }) {
            report.empty_valued.push(field.clone());
        }
    }
    report
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn missing_column_differs_from_present_but_blank_value() {
        let fields = vec!["a".into(), "b".into(), "c".into()];
        let records =
            vec![serde_json::from_str::<Map<String, Value>>(r#"{"a":"ok","b":"  "}"#).unwrap()];
        assert_eq!(
            validate(&fields, &records),
            ValidationReport {
                missing_columns: vec!["c".into()],
                empty_valued: vec!["b".into()],
            }
        );
        assert_eq!(validate(&fields, &[]).missing_columns, fields);
    }
}
