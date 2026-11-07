//! Durable Job v2 model and pure rule/revision decisions.

use crate::data_contract::{DataContract, decode_data_contract, encode_data_contract};
use crate::mapping::{FieldMapping, MappingProfile};
use crate::text_render::python_repr;
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fmt;

pub const DEFAULT_FILENAME_PATTERN: &str = "공고서-{{date}}-{{seq:001}}";
pub const MISSING_MARKER: &str = "〘미입력·{field}〙";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JobError(pub String);
impl fmt::Display for JobError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for JobError {}
fn fail(detail: impl Into<String>) -> JobError {
    JobError(detail.into())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Job {
    pub name: String,
    pub template_path: String,
    pub mapping: MappingProfile,
    pub filename_pattern: String,
    pub version: u8,
    pub last_run_at: String,
    pub favorited_at: String,
    pub tags: Map<String, Value>,
    pub group: String,
    pub authority_id: String,
    pub data_path: String,
    pub data_sheet: String,
    pub data_header_row: u64,
    pub data_kind: String,
    pub reviewed_rules: Map<String, Value>,
    pub template_revision: u64,
    pub binding_revision: u64,
    pub previous_rules: Value,
    pub data_contract: Option<DataContract>,
}

impl Default for Job {
    fn default() -> Self {
        Self {
            name: String::new(),
            template_path: String::new(),
            mapping: MappingProfile::new("", Vec::new(), Map::new())
                .expect("empty profile is valid"),
            filename_pattern: DEFAULT_FILENAME_PATTERN.into(),
            version: 2,
            last_run_at: String::new(),
            favorited_at: String::new(),
            tags: Map::new(),
            group: String::new(),
            authority_id: String::new(),
            data_path: String::new(),
            data_sheet: String::new(),
            data_header_row: 0,
            data_kind: String::new(),
            reviewed_rules: Map::new(),
            template_revision: 1,
            binding_revision: 1,
            previous_rules: Value::Object(Map::new()),
            data_contract: None,
        }
    }
}
impl Job {
    pub fn media(&self) -> &'static str {
        template_media(&self.template_path)
    }
    pub fn work_mode(&self) -> &'static str {
        work_mode(&self.template_path)
    }
    pub fn template_fields(&self) -> Vec<String> {
        self.mapping.template_fields()
    }
    pub fn source_keys(&self) -> Vec<String> {
        let mut seen = HashSet::new();
        self.mapping
            .mappings
            .iter()
            .filter_map(|mapping| {
                if mapping.source.is_empty() || !seen.insert(mapping.source.as_str()) {
                    None
                } else {
                    Some(mapping.source.clone())
                }
            })
            .collect()
    }
    pub fn has_data_binding(&self) -> bool {
        !self.data_path.is_empty()
    }
    pub fn data_binding(&self) -> (&str, &str, u64, &str) {
        (
            &self.data_path,
            &self.data_sheet,
            self.data_header_row,
            &self.data_kind,
        )
    }
    pub fn data_binding_label(&self) -> String {
        if !self.has_data_binding() {
            return String::new();
        }
        let name = self
            .data_path
            .rsplit(['/', '\\'])
            .next()
            .unwrap_or(&self.data_path);
        if self.data_sheet.is_empty() {
            name.into()
        } else {
            format!("{name} · {}", self.data_sheet)
        }
    }
}

pub fn template_media(template_path: &str) -> &'static str {
    let lowered = template_path.to_lowercase();
    if lowered.ends_with(".hwpx") {
        "hwpx"
    } else if lowered.ends_with(".txt") {
        "txt"
    } else {
        ""
    }
}
pub fn work_mode(template_path: &str) -> &'static str {
    match template_media(template_path) {
        "hwpx" => "hwpx_generate",
        "txt" => "text_review_copy",
        _ => "unsupported",
    }
}

fn string(data: &Map<String, Value>, key: &str, default: &str) -> Result<String, JobError> {
    match data.get(key) {
        None => Ok(default.into()),
        Some(Value::String(value)) => Ok(value.clone()),
        Some(value) => Err(fail(format!(
            "작업 필드 '{key}' 는 문자열이어야 하는데 {} 입니다",
            python_type(value)
        ))),
    }
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
fn unsigned(
    data: &Map<String, Value>,
    key: &str,
    default: u64,
    minimum: u64,
) -> Result<u64, JobError> {
    match data.get(key) {
        None => Ok(default),
        Some(Value::Number(value)) => {
            let decimal = value.to_string();
            if !decimal.contains(['.', 'e', 'E']) && decimal.starts_with('-') {
                return Err(fail(format!(
                    "작업 필드 '{key}' 는 {minimum} 이상이어야 하는데 {decimal} 입니다"
                )));
            }
            let Some(number) = value.as_u64() else {
                return Err(fail(format!(
                    "작업 필드 '{key}' 는 정수여야 하는데 {} 입니다",
                    python_type(&Value::Number(value.clone()))
                )));
            };
            if number < minimum {
                return Err(fail(format!(
                    "작업 필드 '{key}' 는 {minimum} 이상이어야 하는데 {number} 입니다"
                )));
            }
            Ok(number)
        }
        Some(value) => Err(fail(format!(
            "작업 필드 '{key}' 는 정수여야 하는데 {} 입니다",
            python_type(value)
        ))),
    }
}
fn string_map(value: Option<&Value>, key: &str) -> Result<Map<String, Value>, JobError> {
    let Some(value) = value else {
        return Ok(Map::new());
    };
    let Some(map) = value.as_object() else {
        return Err(fail(format!(
            "'{key}' 는 사전이어야 하는데 {} 입니다",
            python_type(value)
        )));
    };
    if map.values().any(|value| !value.is_string()) {
        let values = if key == "tags" {
            "축·값"
        } else {
            "대상·지문"
        };
        return Err(fail(format!(
            "'{key}' 의 {values}은 모두 문자열이어야 합니다"
        )));
    }
    Ok(map.clone())
}

fn check_previous_rules(raw: &Value) -> Result<Value, JobError> {
    let Some(map) = raw.as_object() else {
        return Err(fail(format!(
            "'previous_rules' 는 사전이어야 하는데 {} 입니다",
            python_type(raw)
        )));
    };
    if map.is_empty() {
        return Ok(Value::Object(Map::new()));
    }
    let empty = Value::Object(Map::new());
    let fields = map
        .get("fields")
        .unwrap_or(&empty)
        .as_object()
        .ok_or_else(|| fail("'previous_rules.fields' 는 사전이어야 합니다"))?;
    let mut out_fields = Map::new();
    const AXES: [&str; 6] = ["source", "type", "const", "blank", "fmt", "slice"];
    for (name, axes) in fields {
        let Some(axes) = axes.as_object() else {
            return Err(fail(
                "'previous_rules.fields' 의 항목은 필드이름→축사전이어야 합니다",
            ));
        };
        if axes.len() != AXES.len()
            || AXES
                .iter()
                .any(|axis| !axes.get(*axis).is_some_and(Value::is_string))
        {
            return Err(fail(format!(
                "'previous_rules.fields[{name}]' 의 축은 ['source', 'type', 'const', 'blank', 'fmt', 'slice'] 문자열이어야 합니다"
            )));
        }
        out_fields.insert(name.clone(), Value::Object(axes.clone()));
    }
    let template =
        map.get("template")
            .unwrap_or(&Value::Null)
            .as_str()
            .or(if map.contains_key("template") {
                None
            } else {
                Some("")
            });
    let filename =
        map.get("filename")
            .unwrap_or(&Value::Null)
            .as_str()
            .or(if map.contains_key("filename") {
                None
            } else {
                Some("")
            });
    let (Some(template), Some(filename)) = (template, filename) else {
        return Err(fail(
            "'previous_rules' 의 template·filename 은 문자열이어야 합니다",
        ));
    };
    let mut result = Map::new();
    result.insert("template".into(), Value::String(template.into()));
    result.insert("filename".into(), Value::String(filename.into()));
    result.insert("fields".into(), Value::Object(out_fields));
    Ok(Value::Object(result))
}

/// Encode the stable v2 JSON shape. The desktop registry supplies the root-relative library key.
pub fn encode_job(job: &Job, template_key: &str) -> Result<Value, JobError> {
    if job.version != 2 {
        return Err(fail(format!("지원하지 않는 작업 버전: {}", job.version)));
    }
    let mut out = Map::new();
    out.insert("version".into(), Value::from(2));
    out.insert("name".into(), Value::String(job.name.clone()));
    out.insert(
        "template_path".into(),
        Value::String(job.template_path.clone()),
    );
    out.insert("template_key".into(), Value::String(template_key.into()));
    out.insert(
        "filename_pattern".into(),
        Value::String(job.filename_pattern.clone()),
    );
    out.insert("mapping".into(), job.mapping.to_dict());
    out.insert("data_path".into(), Value::String(job.data_path.clone()));
    out.insert("data_sheet".into(), Value::String(job.data_sheet.clone()));
    out.insert("data_header_row".into(), Value::from(job.data_header_row));
    out.insert("data_kind".into(), Value::String(job.data_kind.clone()));
    out.insert("last_run_at".into(), Value::String(job.last_run_at.clone()));
    out.insert(
        "favorited_at".into(),
        Value::String(job.favorited_at.clone()),
    );
    out.insert("tags".into(), Value::Object(job.tags.clone()));
    out.insert("group".into(), Value::String(job.group.clone()));
    out.insert(
        "authority_id".into(),
        Value::String(job.authority_id.clone()),
    );
    out.insert(
        "reviewed_rules".into(),
        Value::Object(job.reviewed_rules.clone()),
    );
    out.insert(
        "template_revision".into(),
        Value::from(job.template_revision),
    );
    out.insert("binding_revision".into(), Value::from(job.binding_revision));
    out.insert(
        "previous_rules".into(),
        check_previous_rules(&job.previous_rules)?,
    );
    if let Some(contract) = &job.data_contract {
        out.insert(
            "data_contract".into(),
            encode_data_contract(contract).map_err(|error| fail(error.0))?,
        );
    }
    Ok(Value::Object(out))
}

/// Decode stored paths literally; the desktop registry applies the configured template-root resolver.
pub fn decode_job(raw: &Value) -> Result<Job, JobError> {
    let data = raw
        .as_object()
        .ok_or_else(|| fail("작업은 사전이어야 합니다"))?;
    if data.get("version") != Some(&Value::from(2)) {
        return Err(fail(format!(
            "지원하지 않는 작업 버전: {}",
            data.get("version").map_or("None".into(), python_repr)
        )));
    }
    let mapping = MappingProfile::from_dict(data.get("mapping").ok_or_else(|| fail("'mapping'"))?)
        .map_err(|error| fail(error.0))?;
    // The host resolves the link; its serialized type is still part of the durable contract.
    string(data, "template_key", "")?;
    let previous_rules = check_previous_rules(
        data.get("previous_rules")
            .unwrap_or(&Value::Object(Map::new())),
    )?;
    Ok(Job {
        name: string(data, "name", "")?,
        template_path: string(data, "template_path", "")?,
        mapping,
        filename_pattern: string(data, "filename_pattern", DEFAULT_FILENAME_PATTERN)?,
        version: 2,
        last_run_at: string(data, "last_run_at", "")?,
        favorited_at: string(data, "favorited_at", "")?,
        tags: string_map(data.get("tags"), "tags")?,
        group: string(data, "group", "")?,
        authority_id: string(data, "authority_id", "")?,
        data_path: string(data, "data_path", "")?,
        data_sheet: string(data, "data_sheet", "")?,
        data_header_row: unsigned(data, "data_header_row", 0, 0)?,
        data_kind: string(data, "data_kind", "")?,
        reviewed_rules: string_map(data.get("reviewed_rules"), "reviewed_rules")?,
        template_revision: unsigned(data, "template_revision", 1, 1)?,
        binding_revision: unsigned(data, "binding_revision", 1, 1)?,
        previous_rules,
        data_contract: data
            .get("data_contract")
            .map(decode_data_contract)
            .transpose()
            .map_err(|error| fail(error.0))?,
    })
}

pub(crate) fn sorted_json(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<_> = map.keys().collect();
            keys.sort();
            let items: Vec<_> = keys
                .into_iter()
                .map(|key| {
                    format!(
                        "{}: {}",
                        serde_json::to_string(key).expect("string"),
                        sorted_json(&map[key])
                    )
                })
                .collect();
            format!("{{{}}}", items.join(", "))
        }
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(sorted_json).collect::<Vec<_>>().join(", ")
        ),
        value => serde_json::to_string(value).expect("JSON value"),
    }
}
/// Stable stale-save fingerprint of fields the editor would overwrite.
/// The host passes its root-derived template key, using the same value as durable encoding.
pub fn content_fingerprint(job: &Job, template_key: &str) -> Result<String, JobError> {
    let mut encoded = encode_job(job, template_key)?;
    let data = encoded.as_object_mut().expect("Job codec returns object");
    for key in [
        "tags",
        "last_run_at",
        "favorited_at",
        "group",
        "authority_id",
        "reviewed_rules",
        "template_revision",
        "binding_revision",
        "previous_rules",
        "data_contract",
    ] {
        data.remove(key);
    }
    Ok(sorted_json(&encoded))
}
pub fn slice_axis_value(mapping: &FieldMapping) -> String {
    mapping
        .slice
        .as_ref()
        .map_or_else(String::new, |slice| sorted_json(&slice.to_dict()))
}
pub fn rules_values(job: &Job) -> Value {
    let mut fields = Map::new();
    for mapping in &job.mapping.mappings {
        let mut axes = Map::new();
        axes.insert("source".into(), Value::String(mapping.source.clone()));
        axes.insert("type".into(), Value::String(mapping.field_type.clone()));
        axes.insert("const".into(), Value::String(mapping.constant.clone()));
        axes.insert("blank".into(), Value::String(String::new()));
        axes.insert("fmt".into(), Value::String(mapping.fmt.clone()));
        axes.insert("slice".into(), Value::String(slice_axis_value(mapping)));
        fields.insert(mapping.template_field.clone(), Value::Object(axes));
    }
    let mut out = Map::new();
    out.insert("template".into(), Value::String(job.template_path.clone()));
    out.insert(
        "filename".into(),
        Value::String(job.filename_pattern.clone()),
    );
    out.insert("fields".into(), Value::Object(fields));
    Value::Object(out)
}
pub fn rules_fingerprints(job: &Job) -> Map<String, Value> {
    let values = rules_values(job);
    let mut out = Map::new();
    out.insert("template".into(), values["template"].clone());
    out.insert("filename".into(), values["filename"].clone());
    for (name, axes) in values["fields"].as_object().expect("rules fields") {
        let strings: Vec<_> = ["source", "type", "const", "blank"]
            .into_iter()
            .map(|key| axes[key].as_str().expect("axis string"))
            .collect();
        let mut source = strings.join("\x1f");
        let slice = axes["slice"].as_str().expect("slice axis");
        if !slice.is_empty() {
            source.push('\x1f');
            source.push_str(slice);
        }
        out.insert(format!("field:{name}:source"), Value::String(source));
        out.insert(format!("field:{name}:format"), axes["fmt"].clone());
    }
    out
}

/// Called under the registry's write lease before replacing a durable Job slot.
pub fn advance_revisions(job: &mut Job, previous: Option<&Job>) -> Result<(), JobError> {
    let Some(previous) = previous else {
        return Ok(());
    };
    let old = rules_values(previous);
    let new = rules_values(job);
    let template_changed = old["template"] != new["template"];
    let binding_changed = old["filename"] != new["filename"] || old["fields"] != new["fields"];
    job.template_revision = previous
        .template_revision
        .checked_add(u64::from(template_changed))
        .ok_or_else(|| fail("template_revision 범위를 초과했습니다"))?;
    job.binding_revision = previous
        .binding_revision
        .checked_add(u64::from(binding_changed))
        .ok_or_else(|| fail("binding_revision 범위를 초과했습니다"))?;
    if !(template_changed || binding_changed) {
        job.previous_rules = previous.previous_rules.clone();
        return Ok(());
    }
    let mut kept = check_previous_rules(&previous.previous_rules)?;
    if kept.as_object().is_some_and(Map::is_empty) {
        kept = serde_json::json!({"template":"", "filename":"", "fields":{}});
    }
    if template_changed {
        kept["template"] = old["template"].clone();
    }
    if binding_changed {
        kept["filename"] = old["filename"].clone();
        kept["fields"] = old["fields"].clone();
    }
    job.previous_rules = kept;
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::text_slice::TextSlice;
    use serde_json::json;

    fn mapped_job() -> Job {
        Job {
            name: "입찰공고서".into(),
            template_path: "C:/templates/a.hwpx".into(),
            filename_pattern: "공고서-{{공고명}}".into(),
            mapping: MappingProfile::new(
                "p",
                vec![
                    FieldMapping::new("공고명", "bidNtceNm", "text", "", "", None).unwrap(),
                    FieldMapping::new("추정가격", "presmptPrce", "amount", "", "{:,}", None)
                        .unwrap(),
                ],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        }
    }

    #[test]
    fn stored_job_preserves_mapping_metadata_and_legacy_defaults_without_inference() {
        let mut job = mapped_job();
        job.last_run_at = "2026-07-10T12:34:56".into();
        job.favorited_at = "2026-07-26T09:00:00".into();
        job.group = "2026 상반기".into();
        job.authority_id = "first-authority".into();
        job.tags = serde_json::from_value(json!({"금액구간":"1억미만","목적물":"물품"})).unwrap();
        job.reviewed_rules = serde_json::from_value(json!({"template":"old"})).unwrap();
        job.template_revision = 3;
        job.binding_revision = 7;
        job.previous_rules = rules_values(&mapped_job());
        job.data_path = "C:/data/2026-08.xlsx".into();
        job.data_sheet = "낙찰".into();
        job.data_header_row = 3;
        job.data_kind = "pclm".into();
        let mut encoded = encode_job(&job, "a.hwpx").unwrap();
        let back = decode_job(&encoded).unwrap();
        assert_eq!(back, job);
        assert_eq!(
            back.data_binding(),
            ("C:/data/2026-08.xlsx", "낙찰", 3, "pclm")
        );
        assert!(back.has_data_binding());
        assert_eq!(back.data_binding_label(), "2026-08.xlsx · 낙찰");
        assert_eq!(back.template_fields(), ["공고명", "추정가격"]);
        assert_eq!(back.source_keys(), ["bidNtceNm", "presmptPrce"]);
        let record =
            serde_json::from_value(json!({"bidNtceNm":"테스트","presmptPrce":"21326800"})).unwrap();
        assert_eq!(
            Value::Object(back.mapping.apply(&record, None).unwrap()),
            json!({"공고명":"테스트","추정가격":"21,326,800"})
        );
        encoded["tags"]["목적물"] = json!("공사");
        assert_eq!(back.tags["목적물"], "물품");
        for key in [
            "data_path",
            "data_sheet",
            "data_header_row",
            "data_kind",
            "tags",
            "reviewed_rules",
            "previous_rules",
            "template_revision",
            "binding_revision",
            "filename_pattern",
        ] {
            encoded.as_object_mut().unwrap().remove(key);
        }
        let legacy = decode_job(&encoded).unwrap();
        assert_eq!(legacy.data_binding(), ("", "", 0, ""));
        assert!(!legacy.has_data_binding());
        assert_eq!(legacy.data_binding_label(), "");
        assert_eq!(legacy.previous_rules, json!({}));
        assert!(legacy.tags.is_empty() && legacy.reviewed_rules.is_empty());
        assert_eq!((legacy.template_revision, legacy.binding_revision), (1, 1));
        assert_eq!(legacy.filename_pattern, DEFAULT_FILENAME_PATTERN);
        assert!(crate::output_name::pattern_field_tokens(DEFAULT_FILENAME_PATTERN).is_empty());
        let empty = Job::default();
        assert!(
            empty.mapping.mappings.is_empty()
                && empty.template_fields().is_empty()
                && empty.source_keys().is_empty()
        );
        assert_eq!(
            decode_job(&encode_job(&empty, "").unwrap())
                .unwrap()
                .filename_pattern,
            DEFAULT_FILENAME_PATTERN
        );
        let mut keys = mapped_job();
        keys.mapping
            .mappings
            .push(FieldMapping::new("다른 공고", "bidNtceNm", "text", "", "", None).unwrap());
        keys.mapping
            .mappings
            .push(FieldMapping::new("비고", "", "const", "", "", None).unwrap());
        assert_eq!(keys.source_keys(), ["bidNtceNm", "presmptPrce"]);
        for (path, media, mode) in [
            ("/x/a.hwpx", "hwpx", "hwpx_generate"),
            ("/x/a.HWPX", "hwpx", "hwpx_generate"),
            ("draft.TxT", "txt", "text_review_copy"),
            ("", "", "unsupported"),
            ("/x/a.hwpx.bak", "", "unsupported"),
            ("/x/a.docx", "", "unsupported"),
            ("/x/a", "", "unsupported"),
        ] {
            let job = Job {
                template_path: path.into(),
                ..Job::default()
            };
            assert_eq!((job.media(), job.work_mode()), (media, mode), "{path}");
            let encoded = encode_job(&job, "").unwrap();
            assert!(encoded.get("media").is_none() && encoded.get("work_mode").is_none());
        }
    }

    #[test]
    fn durable_corruption_is_rejected_instead_of_defaulting_or_losing_history() {
        let valid = encode_job(&mapped_job(), "a.hwpx").unwrap();
        for version in [
            Value::Null,
            json!(1),
            json!(3),
            json!(true),
            json!("2"),
            json!(2.0),
        ] {
            let mut raw = valid.clone();
            raw["version"] = version;
            assert!(
                decode_job(&raw)
                    .unwrap_err()
                    .0
                    .starts_with("지원하지 않는 작업 버전:")
            );
        }
        let mut raw = valid.clone();
        raw.as_object_mut().unwrap().remove("version");
        assert_eq!(
            decode_job(&raw).unwrap_err().0,
            "지원하지 않는 작업 버전: None"
        );
        raw = valid.clone();
        raw.as_object_mut().unwrap().remove("mapping");
        assert_eq!(decode_job(&raw).unwrap_err().0, "'mapping'");
        assert_eq!(
            decode_job(&Value::Null).unwrap_err().0,
            "작업은 사전이어야 합니다"
        );
        for field in [
            "name",
            "template_path",
            "template_key",
            "filename_pattern",
            "last_run_at",
            "favorited_at",
            "group",
            "authority_id",
            "data_path",
            "data_sheet",
            "data_kind",
        ] {
            let mut raw = valid.clone();
            raw[field] = json!(5);
            assert_eq!(
                decode_job(&raw).unwrap_err().0,
                format!("작업 필드 '{field}' 는 문자열이어야 하는데 int 입니다")
            );
        }
        for field in ["tags", "reviewed_rules"] {
            for invalid in [Value::Null, json!(["key"]), json!({"key":123})] {
                let mut raw = valid.clone();
                raw[field] = invalid;
                assert!(decode_job(&raw).unwrap_err().0.contains(field));
            }
        }
        for field in ["data_header_row", "template_revision", "binding_revision"] {
            for invalid in [json!(-1), json!("2"), json!(1.0), json!(true), Value::Null] {
                let mut raw = valid.clone();
                raw[field] = invalid;
                assert!(decode_job(&raw).unwrap_err().0.contains(field));
            }
            let mut raw = valid.clone();
            raw[field] = json!(0);
            assert_eq!(decode_job(&raw).is_ok(), field == "data_header_row");
        }
        let rules = rules_values(&mapped_job());
        let mut missing_axis = rules.clone();
        missing_axis["fields"]["공고명"]
            .as_object_mut()
            .unwrap()
            .remove("slice");
        let mut wrong_axis = rules.clone();
        wrong_axis["fields"]["공고명"]["fmt"] = json!(3);
        let mut bad_template = rules.clone();
        bad_template["template"] = json!(3);
        let mut bad_filename = rules.clone();
        bad_filename["filename"] = Value::Null;
        for invalid in [
            Value::Null,
            json!([]),
            json!(""),
            json!(0),
            json!(3),
            json!({"fields":[]}),
            json!({"fields":{"공고명":"축아님"}}),
            missing_axis,
            wrong_axis,
            bad_template,
            bad_filename,
        ] {
            let mut raw = valid.clone();
            raw["previous_rules"] = invalid.clone();
            assert!(
                decode_job(&raw).unwrap_err().0.contains("previous_rules"),
                "{invalid}"
            );
            let mut job = mapped_job();
            job.previous_rules = invalid;
            assert!(encode_job(&job, "a.hwpx").is_err());
        }
        raw = valid;
        raw["previous_rules"] = rules.clone();
        assert_eq!(decode_job(&raw).unwrap().previous_rules, rules);
    }

    #[test]
    fn durable_round_trip_and_axis_specific_revision() {
        let old = Job {
            name: "공고".into(),
            template_path: "C:/templates/a.hwpx".into(),
            ..Job::default()
        };
        let encoded = encode_job(&old, "a.hwpx").unwrap();
        assert_eq!(encoded["template_key"], "a.hwpx");
        assert_eq!(decode_job(&encoded).unwrap(), old);
        let mut changed = old.clone();
        changed.filename_pattern = "{{date}}".into();
        advance_revisions(&mut changed, Some(&old)).unwrap();
        assert_eq!(
            (changed.template_revision, changed.binding_revision),
            (1, 2)
        );
        assert_eq!(changed.previous_rules["filename"], DEFAULT_FILENAME_PATTERN);
        assert_eq!(changed.previous_rules["template"], "");
        assert_eq!(template_media("A.TXT"), "txt");

        let mut rebound = old.clone();
        rebound.data_path = "C:/data/other.xlsx".into();
        rebound.data_sheet = "공고".into();
        rebound.data_header_row = 2;
        rebound.data_kind = "excel".into();
        assert_ne!(
            content_fingerprint(&rebound, "a.hwpx").unwrap(),
            content_fingerprint(&old, "a.hwpx").unwrap()
        );
        assert_eq!(rules_fingerprints(&rebound), rules_fingerprints(&old));
        advance_revisions(&mut rebound, Some(&old)).unwrap();
        assert_eq!(
            (rebound.template_revision, rebound.binding_revision),
            (1, 1)
        );

        let mut metadata = old.clone();
        metadata.group = "즐겨찾기".into();
        metadata.last_run_at = "2026-11-05T18:04:03".into();
        metadata.favorited_at = "2026-07-26T09:00:00".into();
        metadata.tags.insert("물품".into(), json!("의약품"));
        metadata.authority_id = "authority".into();
        metadata
            .reviewed_rules
            .insert("template".into(), json!("fp"));
        metadata.template_revision = 5;
        metadata.binding_revision = 9;
        metadata.previous_rules = rules_values(&old);
        assert_eq!(
            content_fingerprint(&metadata, "a.hwpx").unwrap(),
            content_fingerprint(&old, "a.hwpx").unwrap()
        );
        let mut template_change = old.clone();
        template_change.template_path = "C:/templates/b.hwpx".into();
        advance_revisions(&mut template_change, Some(&old)).unwrap();
        assert_eq!(
            (
                template_change.template_revision,
                template_change.binding_revision
            ),
            (2, 1)
        );
        assert_eq!(
            template_change.previous_rules["template"],
            old.template_path
        );

        let mut corrupt = encoded;
        corrupt["data_header_row"] = Value::String("2".into());
        assert!(decode_job(&corrupt).is_err());
        corrupt["data_header_row"] = Value::from(0);
        corrupt["version"] = Value::from(3);
        assert!(decode_job(&corrupt).is_err());

        let original = mapped_job();
        let rules = rules_values(&original);
        let fingerprints = rules_fingerprints(&original);
        let mut formatted = original.clone();
        formatted.mapping.mappings[0].fmt = "천단위".into();
        let formatted_fingerprints = rules_fingerprints(&formatted);
        assert_eq!(
            formatted_fingerprints["field:공고명:source"],
            fingerprints["field:공고명:source"]
        );
        assert_ne!(
            formatted_fingerprints["field:공고명:format"],
            fingerprints["field:공고명:format"]
        );
        let mut split = original.clone();
        split.mapping.mappings[0].source = "가".into();
        split.mapping.mappings[0].constant = "나".into();
        let mut embedded = original.clone();
        embedded.mapping.mappings[0].source = "가\u{1f}나".into();
        assert_ne!(
            rules_fingerprints(&split)["field:공고명:source"],
            rules_fingerprints(&embedded)["field:공고명:source"]
        );
        assert_eq!(rules["template"], fingerprints["template"]);
        assert_eq!(rules["filename"], fingerprints["filename"]);
        for (name, axes) in rules["fields"].as_object().unwrap() {
            assert_eq!(axes["fmt"], fingerprints[&format!("field:{name}:format")]);
            assert!(
                fingerprints[&format!("field:{name}:source")]
                    .as_str()
                    .unwrap()
                    .contains(axes["source"].as_str().unwrap())
            );
        }
        let mut unchanged = original.clone();
        advance_revisions(&mut unchanged, Some(&original)).unwrap();
        assert_eq!(unchanged.previous_rules, json!({}));
        let mut rebound = original.clone();
        rebound.mapping.mappings[0].source = "B열".into();
        advance_revisions(&mut rebound, Some(&original)).unwrap();
        assert_eq!(
            (rebound.template_revision, rebound.binding_revision),
            (1, 2)
        );
        assert_eq!(
            rebound.previous_rules["fields"]["공고명"]["source"],
            "bidNtceNm"
        );
        let mut moved = rebound.clone();
        moved.template_path = "C:/templates/b.hwpx".into();
        advance_revisions(&mut moved, Some(&rebound)).unwrap();
        assert_eq!((moved.template_revision, moved.binding_revision), (2, 2));
        assert_eq!(moved.previous_rules["template"], original.template_path);
        assert_eq!(
            moved.previous_rules["fields"],
            rebound.previous_rules["fields"]
        );
        let mut stamped = moved.clone();
        stamped.last_run_at = "2026-11-05T18:04:03".into();
        advance_revisions(&mut stamped, Some(&moved)).unwrap();
        assert_eq!(
            (stamped.template_revision, stamped.binding_revision),
            (2, 2)
        );
        assert_eq!(stamped.previous_rules, moved.previous_rules);
    }

    #[test]
    fn slice_changes_only_source_rule_and_advances_binding_revision() {
        let plain = Job {
            mapping: MappingProfile::new(
                "",
                vec![FieldMapping::new("공고번호", "입찰공고번호", "text", "", "", None).unwrap()],
                Map::new(),
            )
            .unwrap(),
            ..Job::default()
        };
        assert_eq!(
            rules_fingerprints(&plain)["field:공고번호:source"],
            "입찰공고번호\x1ftext\x1f\x1f"
        );
        assert_eq!(rules_values(&plain)["fields"]["공고번호"]["slice"], "");
        let mut sliced = plain.clone();
        sliced.mapping.mappings[0].slice =
            Some(TextSlice::from_dict(&json!({"mode":"split","delimiter":"-","index":1})).unwrap());
        assert_ne!(
            rules_fingerprints(&sliced)["field:공고번호:source"],
            rules_fingerprints(&plain)["field:공고번호:source"]
        );
        assert_eq!(
            rules_fingerprints(&sliced)["field:공고번호:format"],
            rules_fingerprints(&plain)["field:공고번호:format"]
        );
        assert_eq!(
            rules_values(&sliced)["fields"]["공고번호"]["slice"],
            "{\"delimiter\": \"-\", \"index\": 1, \"mode\": \"split\"}"
        );
        advance_revisions(&mut sliced, Some(&plain)).unwrap();
        assert_eq!(sliced.binding_revision, plain.binding_revision + 1);
        assert_eq!(sliced.previous_rules["fields"]["공고번호"]["slice"], "");
    }
}
