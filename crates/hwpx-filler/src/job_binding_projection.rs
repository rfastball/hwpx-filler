//! Project every durable Job mapping rule into the exact execution Binding contract.

use crate::field_binding::{
    CONSTANT, ExactText, FieldBindingError, FieldBindingErrorKind, FieldBindingRule, RUNTIME_DATE,
    SOURCE, resolve_document_value_policy, txt_document_value_policy,
};
use crate::field_binding_input::{FieldBindingInput, build_field_binding_input};
use crate::job::Job;
use crate::mapping::{MappingProfile, TYPES};
use crate::raw_data_record::RAW_RECORD_CONTRACT_ID;
use crate::text_render::python_repr;
use serde_json::Value;
use std::collections::HashSet;

pub fn source_schema_keys(mapping: &MappingProfile) -> Vec<String> {
    let mut seen = HashSet::new();
    mapping
        .mappings
        .iter()
        .filter(|item| ["text", "date", "amount"].contains(&item.field_type.as_str()))
        .filter(|item| seen.insert(item.source.as_str()))
        .map(|item| item.source.clone())
        .collect()
}

pub fn mapping_rules(job: &Job) -> Result<Vec<FieldBindingRule>, FieldBindingError> {
    let policy = |id| {
        if job.media() == "txt" {
            txt_document_value_policy(id)
        } else {
            resolve_document_value_policy(id)
        }
    };
    let mut rules = Vec::with_capacity(job.mapping.mappings.len());
    for item in &job.mapping.mappings {
        let (kind, policy_id, source_key, constant, format_kind, format_code) =
            match item.field_type.as_str() {
                "const" => (
                    CONSTANT,
                    "document-content-value/v1",
                    None,
                    Some(ExactText::new(&item.constant)),
                    None,
                    None,
                ),
                "today" => (
                    RUNTIME_DATE,
                    "document-content-value/v1",
                    None,
                    None,
                    Some("date".to_owned()),
                    Some(item.fmt.clone()),
                ),
                "text" | "date" | "amount" => {
                    let kind = if item.field_type == "text" && item.fmt.is_empty() {
                        None
                    } else {
                        Some(item.field_type.clone())
                    };
                    let code = kind.as_ref().map(|_| item.fmt.clone());
                    (
                        SOURCE,
                        "document-content-value/legacy-strip-v1",
                        Some(item.source.clone()),
                        None,
                        kind,
                        code,
                    )
                }
                _ => {
                    return Err(FieldBindingError {
                        kind: FieldBindingErrorKind::InputIntegrity,
                        message: format!(
                            "지원하지 않는 유형: {} (지원: ({}))",
                            python_repr(&Value::String(item.field_type.clone())),
                            TYPES
                                .iter()
                                .map(|item| format!("'{item}'"))
                                .collect::<Vec<_>>()
                                .join(", ")
                        ),
                    });
                }
            };
        rules.push(FieldBindingRule {
            field_id: item.template_field.clone(),
            binding_kind: kind.into(),
            document_content_value_policy: policy(policy_id)?,
            source_key,
            format_code,
            canonical_constant_value: constant,
            format_kind,
            text_slice: if kind == SOURCE {
                item.slice.clone()
            } else {
                None
            },
        });
    }
    Ok(rules)
}

pub fn job_binding_input(
    job: &Job,
    workspace_id: &str,
    application_id: &str,
    captured_at: &str,
) -> Result<FieldBindingInput, FieldBindingError> {
    build_field_binding_input(
        workspace_id,
        &job.authority_id,
        application_id,
        mapping_rules(job)?,
        source_schema_keys(&job.mapping),
        RAW_RECORD_CONTRACT_ID,
        captured_at,
    )
    .map_err(|e| FieldBindingError {
        kind: e.kind,
        message: e.detail,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::mapping::FieldMapping;
    use crate::text_slice::TextSlice;
    use serde_json::Map;

    #[test]
    fn all_mapping_rules_keep_source_order_and_media_specific_write_policy() {
        let now = crate::field_binding::parse_runtime_clock(Some("2026-06-15T18:04:00")).unwrap();
        assert_eq!(
            crate::format_engine::presets("today"),
            crate::format_engine::presets("date")
        );
        for (_, code) in crate::format_engine::presets("today") {
            let mapping = FieldMapping::new("작성일", "", "today", "", code, None).unwrap();
            let job = Job {
                template_path: "template.hwpx".into(),
                mapping: MappingProfile::new("", vec![mapping.clone()], Map::new()).unwrap(),
                ..Job::default()
            };
            let rules = mapping_rules(&job).unwrap();
            assert_eq!(rules.len(), 1);
            let rule = &rules[0];
            rule.validate().unwrap();
            assert_eq!(rule.binding_kind, RUNTIME_DATE);
            assert_eq!(rule.format_kind.as_deref(), Some("date"));
            assert_eq!(rule.format_code.as_deref(), Some(code));
            assert!(
                rule.source_key.is_none()
                    && rule.canonical_constant_value.is_none()
                    && rule.text_slice.is_none()
            );
            let expected = crate::field_binding::render_runtime_date(code, now).unwrap();
            assert_eq!(
                crate::mapping::apply_transform("today", "", "", code, Some(now), None).unwrap(),
                expected
            );
            assert_eq!(mapping.value_for(&Map::new(), Some(now)).unwrap(), expected);
        }
        let mut job = Job {
            authority_id: "work".into(),
            mapping: MappingProfile::new(
                "",
                vec![
                    FieldMapping::new("a", "z", "text", "", "", None).unwrap(),
                    FieldMapping::new("b", "z", "date", "", "%Y", None).unwrap(),
                    FieldMapping::new("c", "y", "amount", "", "{:,}", None).unwrap(),
                    FieldMapping::new("d", "", "const", "literal", "", None).unwrap(),
                    FieldMapping::new("e", "", "today", "", "%Y", None).unwrap(),
                ],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        assert_eq!(source_schema_keys(&job.mapping), ["z", "y"]);
        let hwpx = mapping_rules(&job).unwrap();
        assert_eq!(hwpx.len(), 5);
        assert_eq!(hwpx[0].format_kind, None);
        assert_eq!(hwpx[1].format_kind.as_deref(), Some("date"));
        assert_eq!(
            hwpx.iter()
                .map(|rule| (rule.format_kind.as_deref(), rule.format_code.as_deref()))
                .collect::<Vec<_>>(),
            [
                (None, None),
                (Some("date"), Some("%Y")),
                (Some("amount"), Some("{:,}")),
                (None, None),
                (Some("date"), Some("%Y")),
            ]
        );
        let split =
            TextSlice::from_dict(&serde_json::json!({"mode":"split","delimiter":"-","index":1}))
                .unwrap();
        job.mapping.mappings[0].slice = Some(split.clone());
        assert_eq!(mapping_rules(&job).unwrap()[0].text_slice, Some(split));
        assert_eq!(
            hwpx[3].canonical_constant_value.as_ref().unwrap().text,
            "literal"
        );
        job.template_path = "template.txt".into();
        let txt = mapping_rules(&job).unwrap();
        assert_eq!(
            txt[0].document_content_value_policy.policy_id,
            "document-content-value/txt-legacy-strip-v1"
        );
        assert_eq!(
            txt[3].document_content_value_policy.policy_id,
            "document-content-value/txt-v1"
        );
        job.mapping.mappings[0].field_type = "currency".into();
        assert!(
            mapping_rules(&job)
                .unwrap_err()
                .message
                .contains("지원하지 않는 유형")
        );
    }
}
