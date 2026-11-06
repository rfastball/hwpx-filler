//! Pure editor session state and the section patch boundary.

use crate::editor_mapping::EditorMappingModel;
use crate::job::{DEFAULT_FILENAME_PATTERN, Job, rules_values};
use crate::mapping::MappingProfile;
use crate::partial_gate::PartialGate;
use crate::schema::TemplateSchema;
use crate::text_render::python_repr;
use serde_json::{Map, Value, json};
use std::collections::HashSet;

pub fn restore_report_lines(
    job: &Job,
    model: &EditorMappingModel,
    handoff_failure: &str,
) -> Vec<String> {
    let row_fields: HashSet<_> = model
        .rows
        .iter()
        .map(|row| row.template_field.as_str())
        .collect();
    let saved_fields: HashSet<_> = job
        .mapping
        .mappings
        .iter()
        .map(|item| item.template_field.as_str())
        .collect();
    let dropped = job
        .mapping
        .mappings
        .iter()
        .filter(|item| !row_fields.contains(item.template_field.as_str()))
        .map(|item| item.template_field.as_str())
        .collect::<Vec<_>>();
    let fresh = model
        .rows
        .iter()
        .filter(|row| !row.confirmed && !saved_fields.contains(row.template_field.as_str()))
        .map(|row| row.template_field.as_str())
        .collect::<Vec<_>>();
    let detached = model
        .rows
        .iter()
        .filter(|row| !row.confirmed && saved_fields.contains(row.template_field.as_str()))
        .map(|row| row.template_field.as_str())
        .collect::<Vec<_>>();
    let mut lines = Vec::new();
    if !dropped.is_empty() {
        lines.push(format!(
            "템플릿에 더는 없는 저장 필드 {}개는 제외했습니다: {}",
            dropped.len(),
            dropped.join(", ")
        ));
    }
    if !fresh.is_empty() {
        lines.push(format!(
            "템플릿에 새로 생긴 필드 {}개는 확정이 필요합니다: {}",
            fresh.len(),
            fresh.join(", ")
        ));
    }
    if !detached.is_empty() {
        lines.push(format!(
            "불러온 데이터에 없는 열을 쓰던 필드 {}개는 확정이 필요합니다: {}",
            detached.len(),
            detached.join(", ")
        ));
    }
    if !handoff_failure.is_empty() {
        lines.push(format!(
            "연결된 데이터를 다시 읽지 못했습니다: {handoff_failure}"
        ));
    }
    lines
}

pub const SECTION_TEMPLATE: &str = "template";
pub const SECTION_BINDING: &str = "binding";
pub const SECTION_FILENAME: &str = "filename";
pub const SECTIONS: [&str; 3] = [SECTION_TEMPLATE, SECTION_BINDING, SECTION_FILENAME];

pub fn editor_context(work: &str, input: &Value) -> Result<Value, String> {
    let reason = input
        .get("entry_reason")
        .and_then(Value::as_str)
        .unwrap_or("voluntary");
    if ![
        "voluntary",
        "library",
        "schema_new_field",
        "schema_missing_field",
        "run_failure",
        "output_result",
        "workbench_result",
        "document_browser_repair",
        "document_browser_new_work",
    ]
    .contains(&reason)
    {
        return Err(format!(
            "알 수 없는 편집 진입 사유: {}",
            python_repr(&json!(reason))
        ));
    }
    let deferred = match reason {
        "schema_new_field" => Some("새 데이터 열 제안 표면이 아직 없다(계약 §7)"),
        "schema_missing_field" => Some("필수 누락 제안 표면이 아직 없다(계약 §7)"),
        _ => None,
    };
    if let Some(detail) = deferred {
        return Err(format!(
            "편집 진입 사유 '{reason}' 는 아직 배선되지 않았습니다({detail})."
        ));
    }
    let returned = input
        .get("return_context")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let surface = returned
        .get("surface")
        .and_then(Value::as_str)
        .unwrap_or("");
    if !surface.is_empty() && !["data", "result", "library", "documents"].contains(&surface) {
        return Err(format!(
            "알 수 없는 복귀 표면: {}",
            python_repr(&json!(surface))
        ));
    }
    let target = input.get("target").and_then(Value::as_str).unwrap_or("");
    if !target.is_empty()
        && target != "filename/filenamePattern"
        && target.strip_prefix("binding/").is_none_or(str::is_empty)
    {
        return Err(format!(
            "알 수 없는 deep-link target: {}",
            python_repr(&json!(target))
        ));
    }
    let evidence = input
        .get("evidence")
        .and_then(Value::as_object)
        .map(|items| {
            items
                .iter()
                .map(|(key, value)| {
                    (
                        key.clone(),
                        Value::String(
                            value
                                .as_str()
                                .map_or_else(|| python_repr(value), str::to_owned),
                        ),
                    )
                })
                .collect::<Map<_, _>>()
        })
        .unwrap_or_default();
    Ok(
        json!({"work":work,"entry_reason":reason,"evidence":evidence,"return_context":returned,"target":target}),
    )
}

#[derive(Clone, Debug)]
pub struct EditorSessionState {
    pub context: Value,
    pub base: Option<Job>,
    pub section: String,
    pub template_path: String,
    pub schema: Option<TemplateSchema>,
    pub gate: Option<PartialGate>,
    pub gate_error: bool,
    pub raw_block: String,
    pub data_path: String,
    pub data_sheet: String,
    pub data_header_row: u64,
    pub data_kind: String,
    pub data_pool_key: String,
    pub source_fields: Vec<String>,
    pub records: Vec<Map<String, Value>>,
    pub model: Option<EditorMappingModel>,
    pub model_key: Option<Value>,
    pub preview_index: usize,
    pub job_name: String,
    pub job_name_is_derived: bool,
    pub derived_name_baseline: String,
    pub pattern: String,
    pub editing_origin: String,
    pub editing_fingerprint: String,
    pub loaded_provenance: Map<String, Value>,
    pub reload_failure: String,
    pub notice_text: String,
    pub notice_level: String,
    pub unconfirm_undo: Vec<(usize, bool, bool, bool)>,
    pub binding_confirm_pending: bool,
    pub entry_data: (String, String),
}

impl Default for EditorSessionState {
    fn default() -> Self {
        Self {
            context: json!({"work":"","entry_reason":"voluntary","evidence":{},"return_context":{},"target":""}),
            base: None,
            section: SECTION_TEMPLATE.into(),
            template_path: String::new(),
            schema: None,
            gate: None,
            gate_error: false,
            raw_block: String::new(),
            data_path: String::new(),
            data_sheet: String::new(),
            data_header_row: 0,
            data_kind: String::new(),
            data_pool_key: String::new(),
            source_fields: Vec::new(),
            records: Vec::new(),
            model: None,
            model_key: None,
            preview_index: 0,
            job_name: String::new(),
            job_name_is_derived: true,
            derived_name_baseline: String::new(),
            pattern: DEFAULT_FILENAME_PATTERN.into(),
            editing_origin: String::new(),
            editing_fingerprint: String::new(),
            loaded_provenance: Map::new(),
            reload_failure: String::new(),
            notice_text: String::new(),
            notice_level: "muted".into(),
            unconfirm_undo: Vec::new(),
            binding_confirm_pending: false,
            entry_data: (String::new(), String::new()),
        }
    }
}

pub fn section_changes(base: Option<&Job>, draft: &Job) -> Value {
    let Some(base) = base else {
        return json!({});
    };
    let old = rules_values(base);
    let new = rules_values(draft);
    let mut changes = Map::new();
    for (section, key) in [
        (SECTION_TEMPLATE, "template"),
        (SECTION_FILENAME, "filename"),
    ] {
        if old[key] != new[key] {
            changes.insert(section.into(), json!({"before":old[key],"after":new[key]}));
        }
    }
    let old_fields = old["fields"].as_object().expect("rules fields");
    let new_fields = new["fields"].as_object().expect("rules fields");
    let mut fields = Map::new();
    let mut seen = HashSet::new();
    for name in old_fields.keys().chain(new_fields.keys()) {
        if !seen.insert(name.as_str()) {
            continue;
        }
        let before = old_fields.get(name);
        let after = new_fields.get(name);
        if before != after {
            fields.insert(name.clone(), json!({"before":before,"after":after}));
        }
    }
    if !fields.is_empty() {
        changes.insert(SECTION_BINDING.into(), Value::Object(fields));
    }
    Value::Object(changes)
}

impl EditorSessionState {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    pub fn is_draft(&self) -> bool {
        self.base.is_none()
    }
    pub fn current_record(&self) -> Map<String, Value> {
        if self.records.is_empty() {
            Map::new()
        } else {
            self.records[self.preview_index % self.records.len()].clone()
        }
    }
    pub fn model_key_now(&self) -> Value {
        json!([
            self.template_path,
            self.data_path,
            self.data_sheet,
            self.data_header_row,
            self.source_fields
        ])
    }
    pub fn draft_job(&self) -> Job {
        let mut job = Job {
            template_path: self.template_path.clone(),
            filename_pattern: self.pattern.clone(),
            ..Job::default()
        };
        job.mapping = self
            .model
            .as_ref()
            .and_then(|model| model.to_profile("").ok())
            .unwrap_or_else(|| {
                MappingProfile::new("", Vec::new(), Map::new()).expect("empty profile")
            });
        job
    }
    pub fn pending_binding(&self) -> bool {
        self.model
            .as_ref()
            .is_some_and(|model| model.rows.iter().any(|row| row.touched && !row.confirmed))
    }
    pub fn changes(&self) -> Value {
        section_changes(self.base.as_ref(), &self.draft_job())
    }
    pub fn dirty_sections(&self) -> Vec<String> {
        let changes = self.changes();
        SECTIONS
            .into_iter()
            .filter(|section| {
                changes.get(*section).is_some()
                    || (*section == SECTION_BINDING && self.pending_binding())
            })
            .map(str::to_owned)
            .collect()
    }
    pub fn dirty_extras(&self) -> Vec<&'static str> {
        if self.base.is_none() {
            return Vec::new();
        }
        let base = self.base.as_ref().expect("checked above");
        let original_name = if self.job_name_is_derived {
            &self.derived_name_baseline
        } else {
            &base.name
        };
        [
            ("job_name", self.job_name != *original_name),
            ("data_path", self.data_path != self.entry_data.0),
            ("data_sheet", self.data_sheet != self.entry_data.1),
        ]
        .into_iter()
        .filter_map(|(key, changed)| changed.then_some(key))
        .collect()
    }
    pub fn has_unsaved_work(&self) -> bool {
        if self.base.is_some() {
            !self.dirty_sections().is_empty() || !self.dirty_extras().is_empty()
        } else {
            self.job_name != self.derived_name_baseline
                || self.data_path != self.entry_data.0
                || self.data_sheet != self.entry_data.1
                || self.model.is_some()
        }
    }
    pub fn blocking_section(&self, target: &str) -> Option<String> {
        if self.is_draft() {
            return None;
        }
        self.dirty_sections()
            .into_iter()
            .find(|section| section != target)
    }
    pub fn current_notice(&self) -> Value {
        if self.notice_text.is_empty() {
            Value::Null
        } else {
            json!({"text":self.notice_text,"level":self.notice_level})
        }
    }
    pub fn set_notice(&mut self, text: impl Into<String>, level: &str) {
        self.notice_text = text.into();
        self.notice_level = level.into();
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    fn job() -> Job {
        Job {
            name: "입찰공고서".into(),
            template_path: "t.hwpx".into(),
            filename_pattern: "공고서-{{공고명}}".into(),
            mapping: MappingProfile::from_dict(&json!({"mappings":[
                {"template_field":"공고명","source":"사업명"},
                {"template_field":"금액","source":"추정가격","type":"amount","fmt":"won"}
            ]}))
            .unwrap(),
            ..Job::default()
        }
    }

    #[test]
    fn entry_context_keeps_evidence_and_refuses_unwired_or_unknown_destinations() {
        for reason in [
            "voluntary",
            "library",
            "run_failure",
            "output_result",
            "workbench_result",
            "document_browser_repair",
            "document_browser_new_work",
        ] {
            let context = editor_context("입찰공고서", &json!({
                "entry_reason":reason, "evidence":{"지급일 표시형":"2026. 07. 25."},
                "return_context":{"surface":"result", "focus_target":"result-date"}, "target":"binding/공고명",
            })).unwrap();
            assert_eq!(context["work"], "입찰공고서");
            assert_eq!(context["entry_reason"], reason);
            assert_eq!(
                context["evidence"],
                json!({"지급일 표시형":"2026. 07. 25."})
            );
            assert_eq!(context["return_context"]["focus_target"], "result-date");
            assert_eq!(context["target"], "binding/공고명");
        }
        for reason in ["schema_new_field", "schema_missing_field"] {
            assert!(
                editor_context("작업", &json!({"entry_reason":reason}))
                    .unwrap_err()
                    .contains("배선되지 않았습니다")
            );
        }
        assert!(
            editor_context("작업", &json!({"entry_reason":"document_browser_whatever"}))
                .unwrap_err()
                .contains("진입 사유")
        );
        assert!(
            editor_context("작업", &json!({"return_context":{"surface":"어딘가"}}))
                .unwrap_err()
                .contains("복귀 표면")
        );
        for target in ["binding/", "template/x", "garbage", "filename/"] {
            assert!(
                editor_context("작업", &json!({"target":target}))
                    .unwrap_err()
                    .contains("deep-link target")
            );
        }
        assert_eq!(editor_context("", &json!({})).unwrap()["target"], "");
        assert_eq!(
            editor_context("", &json!({"target":"filename/filenamePattern"})).unwrap()["target"],
            "filename/filenamePattern"
        );
    }

    #[test]
    fn section_changes_keep_before_after_and_pending_edits_outside_saved_rules() {
        let base = job();
        assert_eq!(section_changes(Some(&base), &base), json!({}));
        assert_eq!(section_changes(None, &base), json!({}));
        let mut changed = base.clone();
        changed.filename_pattern += "-2";
        assert_eq!(
            section_changes(Some(&base), &changed),
            json!({"filename":{"before":"공고서-{{공고명}}", "after":"공고서-{{공고명}}-2"}})
        );
        changed = base.clone();
        changed.template_path = "other.hwpx".into();
        assert_eq!(
            section_changes(Some(&base), &changed),
            json!({"template":{"before":"t.hwpx", "after":"other.hwpx"}})
        );
        changed = base.clone();
        changed.mapping.mappings[0].fmt = "dateLongKo".into();
        let patch = section_changes(Some(&base), &changed);
        assert_eq!(patch.as_object().unwrap().len(), 1);
        assert_eq!(patch["binding"]["공고명"]["before"]["fmt"], "");
        assert_eq!(patch["binding"]["공고명"]["after"]["fmt"], "dateLongKo");
        changed = base.clone();
        changed.mapping.mappings.pop();
        let removed = section_changes(Some(&base), &changed);
        assert!(removed["binding"]["금액"]["after"].is_null());
        assert_eq!(removed["binding"]["금액"]["before"]["source"], "추정가격");
        assert!(section_changes(Some(&changed), &base)["binding"]["금액"]["before"].is_null());
        let mut state = EditorSessionState {
            template_path: base.template_path.clone(),
            pattern: base.filename_pattern.clone(),
            model: Some(EditorMappingModel::from_profile(&base.mapping)),
            base: Some(base.clone()),
            ..EditorSessionState::default()
        };
        assert!(state.dirty_sections().is_empty());
        state
            .model
            .as_mut()
            .unwrap()
            .set_manual(0, "수정한 값")
            .unwrap();
        assert!(state.pending_binding());
        assert_eq!(state.dirty_sections(), ["binding"]);
        assert_eq!(state.blocking_section("binding"), None);
        assert_eq!(state.blocking_section("filename"), Some("binding".into()));
        state.base = None;
        assert_eq!(state.changes(), json!({}));
        assert_eq!(state.blocking_section("filename"), None);
        assert!(state.has_unsaved_work());
        state.reset();
        assert!(!state.has_unsaved_work() && state.dirty_sections().is_empty());
    }
}
