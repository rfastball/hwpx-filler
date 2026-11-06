//! Pure editor save gate and provenance. The host owns leases and file replacement.

use crate::editor_mapping::EditorMappingModel;
use crate::job::template_media;
use crate::mapping::MappingProfile;
use crate::output_name::pattern_field_tokens;
use crate::schema::TemplateSchema;
use chrono::NaiveDateTime;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::path::Path;

pub struct SaveVerdict {
    pub block_reason: String,
    pub blocked_field: &'static str,
    pub profile: Option<MappingProfile>,
}

pub fn derive_job_name(template: &str, data: &str) -> String {
    match (template.trim(), data.trim()) {
        ("", data) => data.into(),
        (template, "") => template.into(),
        (template, data) => format!("{template} · {data}"),
    }
}
impl SaveVerdict {
    fn blocked(reason: impl Into<String>, field: &'static str) -> Self {
        Self {
            block_reason: reason.into(),
            blocked_field: field,
            profile: None,
        }
    }
    pub fn ok(&self) -> bool {
        self.block_reason.is_empty()
    }
}

fn schema_matches(model: &EditorMappingModel, schema: Option<&TemplateSchema>) -> bool {
    schema.is_none_or(|schema| {
        let model_fields = model
            .rows
            .iter()
            .map(|row| row.template_field.as_str())
            .collect::<HashSet<_>>();
        let schema_fields = schema
            .fields
            .iter()
            .map(|field| field.name.as_str())
            .collect::<HashSet<_>>();
        model_fields == schema_fields
    })
}

fn filename_block(
    profile: &MappingProfile,
    pattern: &str,
    template_path: &str,
) -> Option<SaveVerdict> {
    if template_media(template_path) == "txt" {
        return None;
    }
    let covered: HashSet<_> = profile.cover_fields().into_iter().collect();
    let empty: HashSet<_> = profile.declared_empty_fields().into_iter().collect();
    let unresolved = pattern_field_tokens(pattern)
        .into_iter()
        .filter(|field| !covered.contains(field) || empty.contains(field))
        .collect::<Vec<_>>();
    if unresolved.is_empty() {
        return None;
    }
    let listed = unresolved
        .iter()
        .map(|field| format!("{{{{{field}}}}}"))
        .collect::<Vec<_>>()
        .join(", ");
    Some(SaveVerdict::blocked(
        format!(
            "파일명 패턴의 {listed} 에 채울 값이 없습니다. 매핑에서 그 항목을 연결하거나 패턴에서 지운 뒤 저장하세요."
        ),
        "pattern",
    ))
}

pub fn validate_save(
    model: Option<&EditorMappingModel>,
    name: &str,
    pattern: &str,
    data_path: &str,
    schema: Option<&TemplateSchema>,
    template_path: &str,
) -> SaveVerdict {
    let Some(model) = model.filter(|model| model.is_complete()) else {
        return SaveVerdict::blocked("모든 매핑 행을 확정해야 작업을 저장할 수 있습니다.", "");
    };
    if !schema_matches(model, schema) {
        return SaveVerdict::blocked(
            "매핑이 현재 템플릿 스키마와 일치하지 않습니다. 템플릿을 다시 로드한 뒤 저장하세요.",
            "",
        );
    }
    if data_path.is_empty() {
        return SaveVerdict::blocked(
            "데이터를 연결해야 작업을 저장할 수 있습니다. '고르기' 단계에서 데이터를 고르세요.",
            "data",
        );
    }
    if name.is_empty() {
        return SaveVerdict::blocked("'이름·저장' 단계에서 작업 이름을 입력하세요.", "name");
    }
    if template_media(template_path) != "txt" && pattern.is_empty() {
        return SaveVerdict::blocked(
            "'이름·저장' 단계에서 문서 파일 이름을 입력하세요.",
            "pattern",
        );
    }
    if !model.emits_any_value() {
        return SaveVerdict::blocked(
            "확정된 매핑이 전부 비움이라 채울 값이 없습니다. 소스를 지정한 뒤 저장하세요.",
            "",
        );
    }
    let Ok(profile) = model.to_profile(name) else {
        return SaveVerdict::blocked("매핑을 저장할 수 없습니다.", "");
    };
    if let Some(blocked) = filename_block(&profile, pattern, template_path) {
        return blocked;
    }
    SaveVerdict {
        block_reason: String::new(),
        blocked_field: "",
        profile: Some(profile),
    }
}
pub fn build_provenance(
    template_path: &str,
    schema: Option<&TemplateSchema>,
    profile: &MappingProfile,
    dataset_name: &str,
    loaded: &Map<String, Value>,
    now: NaiveDateTime,
) -> Map<String, Value> {
    let timestamp = now.format("%Y-%m-%dT%H:%M:%S").to_string();
    let mut out = Map::new();
    out.insert(
        "template".into(),
        Value::String(
            Path::new(template_path)
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("")
                .into(),
        ),
    );
    out.insert(
        "authored_at".into(),
        Value::String(
            loaded
                .get("authored_at")
                .and_then(Value::as_str)
                .filter(|text| !text.is_empty())
                .unwrap_or(&timestamp)
                .into(),
        ),
    );
    out.insert("updated_at".into(), Value::String(timestamp));
    if let Some(schema) = schema {
        out.insert(
            "template_fields".into(),
            Value::String(schema.field_names().join(" · ")),
        );
    }
    let sources = crate::mapping_state::profile_source_vocabulary(profile);
    if !sources.is_empty() {
        out.insert("source_keys".into(), Value::String(sources.join(" · ")));
    }
    if !dataset_name.is_empty() {
        out.insert("dataset".into(), Value::String(dataset_name.into()));
    }
    out
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    fn model(mappings: Value) -> EditorMappingModel {
        EditorMappingModel::from_profile(
            &MappingProfile::from_dict(&json!({"mappings":mappings})).unwrap(),
        )
    }

    #[test]
    fn save_gate_orders_repairs_and_keeps_declared_empty_distinct_from_no_value() {
        for (template, data, expected) in [
            ("공고서", "2026 하반기 계약", "공고서 · 2026 하반기 계약"),
            ("공고서", "", "공고서"),
            ("", "대장", "대장"),
            ("", "", ""),
            ("   ", "대장", "대장"),
            (" 공고서 ", " 대장 ", "공고서 · 대장"),
        ] {
            assert_eq!(derive_job_name(template, data), expected);
        }
        let content = model(json!([
            {"template_field":"공고명","source":"bidNtceNm"},
            {"template_field":"비고","type":"const"},
        ]));
        let mut unconfirmed = content.clone();
        unconfirmed.set_confirmed(1, false).unwrap();
        let void = model(json!([{"template_field":"허공"}]));
        for (mapping, name, pattern, data, field, message) in [
            (None, "작업", "doc", "data.csv", "", "모든 매핑 행"),
            (Some(&unconfirmed), "", "", "", "", "모든 매핑 행"),
            (Some(&void), "", "", "", "data", "데이터를 연결"),
            (Some(&void), "", "", "data.csv", "name", "작업 이름"),
            (
                Some(&void),
                "작업",
                "",
                "data.csv",
                "pattern",
                "문서 파일 이름",
            ),
            (Some(&void), "작업", "doc", "data.csv", "", "전부 비움"),
            (
                Some(&content),
                "작업",
                "doc-{{ID}}",
                "data.csv",
                "pattern",
                "{{ID}}",
            ),
            (
                Some(&content),
                "작업",
                "doc-{{비고}}",
                "data.csv",
                "pattern",
                "{{비고}}",
            ),
        ] {
            let verdict = validate_save(mapping, name, pattern, data, None, "a.hwpx");
            assert!(!verdict.ok() && verdict.profile.is_none(), "{message}");
            assert_eq!(verdict.blocked_field, field);
            assert!(
                verdict.block_reason.contains(message),
                "{}",
                verdict.block_reason
            );
        }
        let mismatch = validate_save(
            Some(&content),
            "작업",
            "doc",
            "data.csv",
            Some(&TemplateSchema::default()),
            "a.hwpx",
        );
        assert!(!mismatch.ok() && mismatch.blocked_field.is_empty());
        assert!(mismatch.block_reason.contains("스키마"));
        let empty = model(json!([
            {"template_field":"갑", "type":"const"}, {"template_field":"을", "type":"const"},
        ]));
        for (mapping, pattern, path) in [
            (&content, "doc-{{공고명}}", "a.hwpx"),
            (&empty, "doc-{{seq:001}}", "a.hwpx"),
            (&content, "", "a.txt"),
            (&content, "doc-{{ID}}", "a.txt"),
        ] {
            let verdict = validate_save(Some(mapping), "작업", pattern, "data.csv", None, path);
            assert!(verdict.ok(), "{}", verdict.block_reason);
            let profile = verdict.profile.unwrap();
            assert_eq!(profile.name, "작업");
            assert_eq!(profile.mappings.len(), 2);
        }
        for (name, data, mapping, field, reason) in [
            ("", "data.csv", &content, "name", "이름"),
            ("작업", "", &content, "data", "데이터"),
            ("작업", "data.csv", &void, "", "전부 비움"),
        ] {
            let verdict = validate_save(Some(mapping), name, "", data, None, "a.txt");
            assert!(!verdict.ok() && verdict.profile.is_none());
            assert_eq!(verdict.blocked_field, field);
            assert!(verdict.block_reason.contains(reason));
        }
    }
}
