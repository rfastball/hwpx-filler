//! Work-package manifest values and strict codec; archive bytes belong to the host.

use crate::mapping::MappingProfile;
use crate::preset::{SelectionPreset, decode_preset, encode_preset};
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::sync::OnceLock;

pub const SCHEMA_VERSION: &str = "work-package/v1";
const MANIFEST_FIELDS: [&str; 4] = ["schema_version", "created_at", "templates", "jobs"];
const TEMPLATE_FIELDS: [&str; 4] = ["digest", "media", "display_name", "size"];
const JOB_FIELDS: [&str; 7] = [
    "name",
    "media",
    "template_digest",
    "mapping",
    "filename_pattern",
    "selection_presets",
    "data_contract",
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkPackageError(pub String);
impl fmt::Display for WorkPackageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for WorkPackageError {}
fn fail(message: impl Into<String>) -> WorkPackageError {
    WorkPackageError(message.into())
}
fn repr(value: &Value) -> String {
    python_repr(value)
}
fn cc() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"\p{Cc}").expect("fixed Unicode category"))
}
fn control_or_format() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"\p{C}").expect("fixed Unicode category"))
}
fn text(value: &str, what: &str) -> Result<(), WorkPackageError> {
    if python_trim(value).is_empty() {
        return Err(fail(format!("{what}이(가) 비어 있습니다")));
    }
    if cc().is_match(value) {
        return Err(fail(format!("{what}에 제어 문자가 있습니다")));
    }
    Ok(())
}
fn digest(value: &str, what: &str) -> Result<(), WorkPackageError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(fail(format!(
            "{what}이(가) sha256 소문자 16진 64자가 아닙니다: {}",
            repr(&Value::String(value.into()))
        )));
    }
    Ok(())
}
fn media(value: &str) -> Result<(), WorkPackageError> {
    if ["hwpx", "txt"].contains(&value) {
        Ok(())
    } else {
        Err(fail(format!(
            "모르는 템플릿 형식: {}",
            repr(&Value::String(value.into()))
        )))
    }
}
fn record<'a>(
    value: &'a Value,
    fields: &[&str],
    optional: &[&str],
    what: &str,
) -> Result<&'a Map<String, Value>, WorkPackageError> {
    let map = value
        .as_object()
        .ok_or_else(|| fail(format!("{what}이(가) 객체가 아닙니다")))?;
    let mut unknown = map
        .keys()
        .filter(|key| !fields.contains(&key.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    unknown.sort();
    if !unknown.is_empty() {
        return Err(fail(format!(
            "{what}에 모르는 필드가 있습니다: {}",
            repr(&serde_json::json!(unknown))
        )));
    }
    let mut missing = fields
        .iter()
        .filter(|key| !optional.contains(key) && !map.contains_key(**key))
        .map(|key| (*key).to_owned())
        .collect::<Vec<_>>();
    missing.sort();
    if !missing.is_empty() {
        return Err(fail(format!(
            "{what}에 필드가 빠졌습니다: {}",
            repr(&serde_json::json!(missing))
        )));
    }
    Ok(map)
}
fn required_string<'a>(
    map: &'a Map<String, Value>,
    key: &str,
    what: &str,
) -> Result<&'a str, WorkPackageError> {
    map.get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| fail(format!("{what}이(가) 비어 있습니다")))
}
fn list<'a>(value: &'a Value, what: &str) -> Result<&'a [Value], WorkPackageError> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| fail(format!("{what}이(가) 목록이 아닙니다")))
}
fn duplicates(values: impl IntoIterator<Item = String>) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut repeated = HashSet::new();
    for value in values {
        if !seen.insert(value.clone()) {
            repeated.insert(value);
        }
    }
    let mut repeated = repeated.into_iter().collect::<Vec<_>>();
    repeated.sort();
    repeated
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PackagedTemplate {
    pub digest: String,
    pub media: String,
    pub display_name: String,
    pub size: u64,
}
impl PackagedTemplate {
    pub fn validate(&self) -> Result<(), WorkPackageError> {
        digest(&self.digest, "템플릿 digest")?;
        media(&self.media)?;
        if self.display_name.is_empty() || self.display_name.chars().count() > 255 {
            return Err(fail("템플릿 표시 이름의 길이가 맞지 않습니다"));
        }
        if control_or_format().is_match(&self.display_name) {
            return Err(fail(format!(
                "템플릿 표시 이름에 제어·서식 문자가 있습니다: {}",
                repr(&Value::String(self.display_name.clone()))
            )));
        }
        if self
            .display_name
            .chars()
            .any(|ch| "<>:\"/\\|?*".contains(ch))
        {
            return Err(fail(format!(
                "템플릿 표시 이름에 쓸 수 없는 문자가 있습니다: {}",
                repr(&Value::String(self.display_name.clone()))
            )));
        }
        let suffix = format!(".{}", self.media);
        let stem = self
            .display_name
            .get(..self.display_name.len().saturating_sub(suffix.len()))
            .unwrap_or("");
        if !self.display_name.to_lowercase().ends_with(&suffix)
            || stem.trim_matches([' ', '.']).is_empty()
        {
            return Err(fail(format!(
                "템플릿 표시 이름이 {} 파일 이름이 아닙니다: {}",
                self.media,
                repr(&Value::String(self.display_name.clone()))
            )));
        }
        if self.display_name != python_trim(&self.display_name) {
            return Err(fail(format!(
                "템플릿 표시 이름의 앞뒤가 공백입니다: {}",
                repr(&Value::String(self.display_name.clone()))
            )));
        }
        if self.size == 0 {
            return Err(fail("템플릿 크기가 양의 정수가 아닙니다: 0"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PackagedJob {
    pub name: String,
    pub media: String,
    pub template_digest: String,
    pub mapping: MappingProfile,
    pub filename_pattern: String,
    pub selection_presets: Vec<SelectionPreset>,
    pub data_contract: Option<Map<String, Value>>,
}
impl PackagedJob {
    pub fn validate(&self) -> Result<(), WorkPackageError> {
        text(&self.name, "작업 이름")?;
        media(&self.media)?;
        digest(&self.template_digest, "작업의 템플릿 digest")?;
        text(
            &self.filename_pattern,
            &format!(
                "작업 {}의 파일명 규칙",
                repr(&Value::String(self.name.clone()))
            ),
        )?;
        if !self.mapping.provenance.is_empty() {
            return Err(fail(format!(
                "작업 {}의 연결에 출처 메타가 남아 있습니다",
                repr(&Value::String(self.name.clone()))
            )));
        }
        for preset in &self.selection_presets {
            preset.validate().map_err(|error| fail(error.to_string()))?;
            if !preset.provenance.is_empty() {
                return Err(fail(format!(
                    "작업 {}의 선택 프리셋 {}에 출처 메타가 남아 있습니다",
                    repr(&Value::String(self.name.clone())),
                    repr(&Value::String(preset.name.clone()))
                )));
            }
        }
        let repeated = duplicates(
            self.selection_presets
                .iter()
                .map(|preset| preset.name.clone()),
        );
        if !repeated.is_empty() {
            return Err(fail(format!(
                "작업 {}의 선택 프리셋 이름이 겹칩니다: {}",
                repr(&Value::String(self.name.clone())),
                repr(&serde_json::json!(repeated))
            )));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkPackageManifest {
    pub created_at: String,
    pub templates: Vec<PackagedTemplate>,
    pub jobs: Vec<PackagedJob>,
}
impl WorkPackageManifest {
    pub fn validate(&self) -> Result<(), WorkPackageError> {
        text(&self.created_at, "created_at")?;
        for template in &self.templates {
            template.validate()?;
        }
        for job in &self.jobs {
            job.validate()?;
        }
        if self.jobs.is_empty() {
            return Err(fail("꾸러미에 작업이 없습니다"));
        }
        let repeated = duplicates(self.jobs.iter().map(|job| job.name.clone()));
        if !repeated.is_empty() {
            return Err(fail(format!(
                "작업 이름이 겹칩니다: {}",
                repr(&serde_json::json!(repeated))
            )));
        }
        if !duplicates(
            self.templates
                .iter()
                .map(|template| template.digest.clone()),
        )
        .is_empty()
        {
            return Err(fail("같은 템플릿이 두 번 선언됐습니다"));
        }
        let declared = self.template_by_digest();
        for job in &self.jobs {
            let Some(template) = declared.get(&job.template_digest) else {
                return Err(fail(format!(
                    "작업 {}의 템플릿이 꾸러미에 없습니다",
                    repr(&Value::String(job.name.clone()))
                )));
            };
            if template.media != job.media {
                return Err(fail(format!(
                    "작업 {}의 형식이 템플릿 형식과 다릅니다",
                    repr(&Value::String(job.name.clone()))
                )));
            }
        }
        let referenced = self
            .jobs
            .iter()
            .map(|job| job.template_digest.as_str())
            .collect::<HashSet<_>>();
        let mut unused = declared
            .keys()
            .filter(|digest| !referenced.contains(digest.as_str()))
            .cloned()
            .collect::<Vec<_>>();
        unused.sort();
        if !unused.is_empty() {
            return Err(fail(format!(
                "어느 작업도 쓰지 않는 템플릿이 있습니다: {}",
                repr(&serde_json::json!(unused))
            )));
        }
        Ok(())
    }
    pub fn template_by_digest(&self) -> HashMap<String, &PackagedTemplate> {
        self.templates
            .iter()
            .map(|template| (template.digest.clone(), template))
            .collect()
    }
}

pub fn encode_work_package(manifest: &WorkPackageManifest) -> Result<Value, WorkPackageError> {
    manifest.validate()?;
    let templates = manifest.templates.iter().map(|template| {
        serde_json::json!({"digest":template.digest,"media":template.media,"display_name":template.display_name,"size":template.size})
    }).collect::<Vec<_>>();
    let jobs = manifest
        .jobs
        .iter()
        .map(|job| -> Result<Value, WorkPackageError> {
            let presets = job
                .selection_presets
                .iter()
                .map(|preset| encode_preset(preset).map_err(|error| fail(error.to_string())))
                .collect::<Result<Vec<_>, _>>()?;
            let mut encoded = Map::new();
            encoded.insert("name".into(), Value::String(job.name.clone()));
            encoded.insert("media".into(), Value::String(job.media.clone()));
            encoded.insert(
                "template_digest".into(),
                Value::String(job.template_digest.clone()),
            );
            encoded.insert("mapping".into(), job.mapping.to_dict());
            encoded.insert(
                "filename_pattern".into(),
                Value::String(job.filename_pattern.clone()),
            );
            encoded.insert("selection_presets".into(), Value::Array(presets));
            encoded.insert(
                "data_contract".into(),
                job.data_contract.clone().map_or(Value::Null, Value::Object),
            );
            Ok(Value::Object(encoded))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let mut encoded = Map::new();
    encoded.insert(
        "schema_version".into(),
        Value::String(SCHEMA_VERSION.into()),
    );
    encoded.insert(
        "created_at".into(),
        Value::String(manifest.created_at.clone()),
    );
    encoded.insert("templates".into(), Value::Array(templates));
    encoded.insert("jobs".into(), Value::Array(jobs));
    Ok(Value::Object(encoded))
}

pub fn decode_work_package(value: &Value) -> Result<WorkPackageManifest, WorkPackageError> {
    let object = value
        .as_object()
        .ok_or_else(|| fail("꾸러미 manifest 가 객체가 아닙니다"))?;
    if object.get("schema_version") != Some(&Value::String(SCHEMA_VERSION.into())) {
        return Err(fail(format!(
            "모르는 꾸러미 버전: {}",
            repr(object.get("schema_version").unwrap_or(&Value::Null))
        )));
    }
    let object = record(value, &MANIFEST_FIELDS, &[], "꾸러미 manifest")?;
    let mut templates = Vec::new();
    for item in list(&object["templates"], "templates")? {
        let item = record(item, &TEMPLATE_FIELDS, &[], "템플릿 항목")?;
        let size = item["size"]
            .as_u64()
            .filter(|size| *size > 0)
            .ok_or_else(|| {
                fail(format!(
                    "템플릿 크기가 양의 정수가 아닙니다: {}",
                    repr(&item["size"])
                ))
            })?;
        templates.push(PackagedTemplate {
            digest: required_string(item, "digest", "템플릿 digest")?.into(),
            media: required_string(item, "media", "모르는 템플릿 형식")?.into(),
            display_name: required_string(item, "display_name", "템플릿 표시 이름")?.into(),
            size,
        });
    }
    let mut jobs = Vec::new();
    for item in list(&object["jobs"], "jobs")? {
        let item = record(item, &JOB_FIELDS, &["data_contract"], "작업 항목")?;
        let name = required_string(item, "name", "작업 이름")?.to_owned();
        let mapping_raw = &item["mapping"];
        if !mapping_raw.is_object() {
            return Err(fail(format!(
                "작업 {}의 연결이 객체가 아닙니다",
                repr(&Value::String(name))
            )));
        }
        let mapping = MappingProfile::from_dict(mapping_raw).map_err(|error| {
            fail(format!(
                "작업 {}의 연결을 읽을 수 없습니다: {error}",
                repr(&Value::String(name.clone()))
            ))
        })?;
        if mapping.to_dict() != *mapping_raw {
            return Err(fail(format!(
                "작업 {}의 연결 모양이 정규형이 아닙니다",
                repr(&Value::String(name.clone()))
            )));
        }
        let presets = list(&item["selection_presets"], "선택 프리셋")?
            .iter()
            .map(|raw| {
                decode_preset(raw).map_err(|error| {
                    fail(format!(
                        "작업 {}의 선택 프리셋을 읽을 수 없습니다: {error}",
                        repr(&Value::String(name.clone()))
                    ))
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let data_contract = match item.get("data_contract") {
            None | Some(Value::Null) => None,
            Some(Value::Object(contract)) => Some(contract.clone()),
            Some(_) => {
                return Err(fail(format!(
                    "작업 {}의 데이터 계약이 객체가 아닙니다",
                    repr(&Value::String(name.clone()))
                )));
            }
        };
        jobs.push(PackagedJob {
            name,
            media: required_string(item, "media", "모르는 템플릿 형식")?.into(),
            template_digest: required_string(item, "template_digest", "작업의 템플릿 digest")?
                .into(),
            mapping,
            filename_pattern: required_string(item, "filename_pattern", "파일명 규칙")?.into(),
            selection_presets: presets,
            data_contract,
        });
    }
    let result = WorkPackageManifest {
        created_at: required_string(object, "created_at", "created_at")?.into(),
        templates,
        jobs,
    };
    result.validate()?;
    Ok(result)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        PackagedJob, PackagedTemplate, WorkPackageManifest, decode_work_package,
        encode_work_package,
    };
    use crate::mapping::MappingProfile;
    use serde_json::{Map, Value, json};

    fn manifest() -> WorkPackageManifest {
        let digest = "a".repeat(64);
        WorkPackageManifest {
            created_at: "2026-11-05T12:00:00".into(),
            templates: vec![PackagedTemplate {
                digest: digest.clone(),
                media: "hwpx".into(),
                display_name: "계약.hwpx".into(),
                size: 3,
            }],
            jobs: vec![PackagedJob {
                name: "계약".into(),
                media: "hwpx".into(),
                template_digest: digest.clone(),
                mapping: MappingProfile::new("", Vec::new(), Map::new()).unwrap(),
                filename_pattern: "계약".into(),
                selection_presets: Vec::new(),
                data_contract: None,
            }],
        }
    }

    fn rejects(value: &Value, expected: &str) {
        let error = decode_work_package(value).unwrap_err();
        assert!(
            error.0.contains(expected),
            "{expected}: {error}; input={value}"
        );
    }

    fn rejects_at(base: &Value, path: &str, value: Value, expected: &str) {
        let mut changed = base.clone();
        *changed.pointer_mut(path).unwrap() = value;
        rejects(&changed, expected);
    }

    #[test]
    fn manifest_requires_exact_fields_and_never_exports_private_job_state() {
        let encoded = encode_work_package(&manifest()).unwrap();
        rejects(&json!([]), "객체가 아닙니다");
        for version in [Value::Null, json!("work-package/v2"), json!(1)] {
            rejects_at(&encoded, "/schema_version", version, "모르는 꾸러미 버전");
        }
        for (path, fields) in [
            ("", super::MANIFEST_FIELDS.as_slice()),
            ("/templates/0", super::TEMPLATE_FIELDS.as_slice()),
            ("/jobs/0", super::JOB_FIELDS.as_slice()),
        ] {
            let mut extra = encoded.clone();
            extra.pointer_mut(path).unwrap()["data_path"] = json!("C:/private.xlsx");
            rejects(&extra, "모르는 필드");
            for field in fields.iter().filter(|field| **field != "data_contract") {
                let mut missing = encoded.clone();
                missing
                    .pointer_mut(path)
                    .unwrap()
                    .as_object_mut()
                    .unwrap()
                    .remove(*field);
                rejects(
                    &missing,
                    if *field == "schema_version" {
                        "모르는 꾸러미 버전"
                    } else {
                        "빠졌습니다"
                    },
                );
            }
        }
        for field in [
            "data_sheet",
            "data_header_row",
            "data_kind",
            "authority_id",
            "reviewed_rules",
            "previous_rules",
            "template_revision",
            "binding_revision",
            "version",
            "favorited_at",
            "group",
            "tags",
            "last_run_at",
            "template_path",
            "filter_presets",
            "test_data",
        ] {
            let mut leaked = encoded.clone();
            leaked["jobs"][0][field] = json!("private");
            rejects(&leaked, "모르는 필드");
        }
        for path in ["/templates", "/jobs", "/jobs/0/selection_presets"] {
            for value in [json!({}), json!("list")] {
                rejects_at(&encoded, path, value, "목록이 아닙니다");
            }
        }
        for path in ["/templates/0", "/jobs/0"] {
            rejects_at(&encoded, path, json!(3), "객체가 아닙니다");
        }
    }

    #[test]
    fn manifest_validates_text_names_sizes_and_content_addresses() {
        let encoded = encode_work_package(&manifest()).unwrap();
        for path in ["/created_at", "/jobs/0/name", "/jobs/0/filename_pattern"] {
            for value in [json!(""), json!(" \u{1c}"), json!("가\n나"), json!(3)] {
                let mut changed = encoded.clone();
                *changed.pointer_mut(path).unwrap() = value;
                assert!(decode_work_package(&changed).is_err(), "{path}: {changed}");
            }
        }
        for value in [
            json!(""),
            json!("A".repeat(64)),
            json!("0".repeat(63)),
            json!("g".repeat(64)),
        ] {
            for path in ["/templates/0/digest", "/jobs/0/template_digest"] {
                rejects_at(&encoded, path, value.clone(), "sha256");
            }
        }
        for path in ["/templates/0/media", "/jobs/0/media"] {
            rejects_at(&encoded, path, json!("docx"), "모르는 템플릿 형식");
        }
        for size in [json!(0), json!(-1), json!(true), json!(1.5), json!("13")] {
            rejects_at(&encoded, "/templates/0/size", size, "크기");
        }
        for name in [
            "",
            "../계약.hwpx",
            "폴더/계약.hwpx",
            "폴더\\계약.hwpx",
            "C:계약.hwpx",
            "계약.txt",
            ".hwpx",
            " .hwpx",
            " 계약.hwpx",
            "계약\u{202e}xcod.hwpx",
            "계약\n서.hwpx",
        ] {
            rejects_at(
                &encoded,
                "/templates/0/display_name",
                json!(name),
                "표시 이름",
            );
        }
        rejects_at(
            &encoded,
            "/templates/0/display_name",
            json!(format!("{}.hwpx", "가".repeat(251))),
            "표시 이름",
        );
        let mut valid = manifest();
        valid.templates[0].display_name = format!("{}.HWPX", "가".repeat(250));
        assert_eq!(
            decode_work_package(&encode_work_package(&valid).unwrap()).unwrap(),
            valid
        );
        valid.templates[0].size = 0;
        assert!(encode_work_package(&valid).unwrap_err().0.contains("크기"));
    }

    fn preset() -> crate::preset::SelectionPreset {
        use crate::slot_selection::{SlotSelection, SlotSelectionSet};
        crate::preset::SelectionPreset::new(
            "표준",
            SlotSelectionSet::new(vec![SlotSelection::new("s1", vec!["o1".into()]).unwrap()])
                .unwrap(),
            Vec::new(),
            "2026-11-05T12:00:00",
        )
        .unwrap()
    }

    #[test]
    fn manifest_preserves_canonical_mapping_presets_and_owned_contract() {
        use crate::mapping::FieldMapping;
        let mut source = manifest();
        source.jobs[0].mapping = MappingProfile::new(
            "공고",
            vec![
                FieldMapping::new("공고명", "공고명", "text", "", "", None).unwrap(),
                FieldMapping::new("비고", "", "const", "", "", None).unwrap(),
            ],
            Map::new(),
        )
        .unwrap();
        source.jobs[0].selection_presets = vec![preset()];
        source.jobs[0].data_contract = Some(
            json!({"columns":{"a":{"n":1}}})
                .as_object()
                .unwrap()
                .clone(),
        );
        let encoded = encode_work_package(&source).unwrap();
        let decoded = decode_work_package(&encoded).unwrap();
        assert_eq!(decoded, source);
        source.jobs[0].data_contract.as_mut().unwrap()["columns"]["a"]["n"] = json!(2);
        assert_eq!(
            decoded.jobs[0].data_contract.as_ref().unwrap()["columns"]["a"]["n"],
            1
        );
        let mut absent = encoded.clone();
        absent["jobs"][0]
            .as_object_mut()
            .unwrap()
            .remove("data_contract");
        assert_eq!(
            decode_work_package(&absent).unwrap().jobs[0].data_contract,
            None
        );
        for value in [json!([]), json!("계약"), json!(3)] {
            rejects_at(&encoded, "/jobs/0/data_contract", value, "데이터 계약");
        }
        for value in [
            json!("연결"),
            json!({"mappings":[{"template_field":"a","type":"모름"}]}),
            json!({"mappings":[3]}),
        ] {
            rejects_at(&encoded, "/jobs/0/mapping", value, "연결");
        }
        let mut noncanonical = encoded.clone();
        noncanonical["jobs"][0]["mapping"]["mappings"][0]["alias"] = json!("x");
        rejects(&noncanonical, "정규형");
        noncanonical = encoded.clone();
        noncanonical["jobs"][0]["mapping"]["mappings"][0]
            .as_object_mut()
            .unwrap()
            .remove("fmt");
        rejects(&noncanonical, "정규형");
        rejects_at(
            &encoded,
            "/jobs/0/mapping/provenance",
            json!({"dataset":"private.xlsx"}),
            "출처 메타",
        );
        rejects_at(
            &encoded,
            "/jobs/0/selection_presets/0/provenance",
            json!({"template_application_id":"A1"}),
            "출처 메타",
        );
        rejects_at(
            &encoded,
            "/jobs/0/selection_presets/0/declared_selection_digest",
            json!("0".repeat(64)),
            "선택 프리셋을 읽을 수 없습니다",
        );
        let duplicated = json!([
            encoded["jobs"][0]["selection_presets"][0],
            encoded["jobs"][0]["selection_presets"][0]
        ]);
        rejects_at(
            &encoded,
            "/jobs/0/selection_presets",
            duplicated,
            "선택 프리셋 이름이 겹칩니다",
        );
        let mut invalid = decoded;
        invalid.jobs[0].selection_presets[0].name.clear();
        assert!(encode_work_package(&invalid).is_err());
    }

    #[test]
    fn shared_templates_roundtrip_but_inconsistent_references_fail() {
        let mut source = manifest();
        let mut second = source.jobs[0].clone();
        second.name = "같은 서식".into();
        source.jobs.push(second);
        let other = PackagedTemplate {
            digest: "b".repeat(64),
            media: "txt".into(),
            display_name: "기안.txt".into(),
            size: 12,
        };
        let mut third = source.jobs[0].clone();
        third.name = "기안".into();
        third.media.clone_from(&other.media);
        third.template_digest.clone_from(&other.digest);
        source.jobs.push(third);
        source.templates.push(other);
        let encoded = encode_work_package(&source).unwrap();
        assert_eq!(decode_work_package(&encoded).unwrap(), source);
        rejects_at(
            &encoded,
            "/jobs/1/name",
            json!("계약"),
            "작업 이름이 겹칩니다",
        );
        rejects_at(&encoded, "/jobs", json!([]), "작업이 없습니다");
        rejects_at(
            &encoded,
            "/jobs/0/template_digest",
            json!("c".repeat(64)),
            "템플릿이 꾸러미에 없습니다",
        );
        rejects_at(
            &encoded,
            "/jobs/0/media",
            json!("txt"),
            "형식이 템플릿 형식과 다릅니다",
        );
        rejects_at(
            &encoded,
            "/templates/1",
            encoded["templates"][0].clone(),
            "두 번 선언",
        );
        rejects_at(
            &encoded,
            "/jobs",
            json!([encoded["jobs"][0]]),
            "쓰지 않는 템플릿",
        );
    }

    #[test]
    fn manifest_encoding_field_order_is_stable() {
        let manifest = manifest();
        let digest = &manifest.templates[0].digest;
        let encoded = encode_work_package(&manifest).unwrap();
        assert_eq!(
            serde_json::to_string(&encoded).unwrap(),
            format!(
                "{{\"schema_version\":\"work-package/v1\",\"created_at\":\"2026-11-05T12:00:00\",\"templates\":[{{\"digest\":\"{digest}\",\"media\":\"hwpx\",\"display_name\":\"계약.hwpx\",\"size\":3}}],\"jobs\":[{{\"name\":\"계약\",\"media\":\"hwpx\",\"template_digest\":\"{digest}\",\"mapping\":{{\"name\":\"\",\"mappings\":[],\"provenance\":{{}}}},\"filename_pattern\":\"계약\",\"selection_presets\":[],\"data_contract\":null}}]}}"
            )
        );
        assert_eq!(decode_work_package(&encoded).unwrap(), manifest);
    }
}
