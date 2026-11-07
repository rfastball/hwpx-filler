//! Lesson prerequisites written into the isolated practice home before graph assembly.

use crate::dataset_registry::DatasetPoolRegistry;
use crate::job_registry::JobRegistry;
use crate::tutorial_workspace::{DATA_NAME, SeededLesson, fingerprint};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::dataset_reference::{DatasetReference, FilterPreset};
use hwpx_filler::job::Job;
use hwpx_filler::mapping::{FieldMapping, MappingProfile};
use hwpx_filler::schema::{extract_schema, infer_type};
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::error::Error;
use std::fs;
use std::path::Path;

type SeedError = Box<dyn Error + Send + Sync>;
const HWPX_NAME: &str = "물품 구매입찰 공고.hwpx";
const TXT_NAME: &str = "낙찰자 선정 및 계약체결 안내.txt";
const PURCHASE_NAME: &str = "계약방법 결정 및 구매추진 안내.txt";

pub fn derived_for(lesson: &str) -> (&'static str, &'static str, &'static str) {
    match lesson {
        "replace_data" => ("replacement", "공고목록(새 판).xlsx", "공고"),
        "blank_values" => ("blank", "공고목록(빈 칸).xlsx", "계약"),
        _ => ("", "", ""),
    }
}

pub fn seed_before_switch(
    lesson: &str,
    seeded: &mut SeededLesson,
) -> Result<Map<String, Value>, SeedError> {
    let mut context = seeded.as_value().as_object().expect("seed object").clone();
    if let Some(entry) = &seeded.derived_entry {
        context.insert("derived_data_path".into(), json!(entry.path));
        context.insert("derived_sheet".into(), json!(derived_for(lesson).2));
    } else {
        context.remove("derived_entry");
    }
    if lesson == "option_apply" {
        rewrite_option_txt(seeded, &mut context)?;
    }
    if let Some((name, template, derived, sheet)) = job_for(lesson) {
        let template_path = asset_path(&context, template)?;
        let data_path = if derived {
            context
                .get("derived_data_path")
                .and_then(Value::as_str)
                .ok_or("연습 파일을 먼저 준비하세요.")?
                .to_owned()
        } else {
            asset_path(&context, DATA_NAME)?
        };
        let fields = template_fields(Path::new(&template_path), template.ends_with(".txt"))?;
        let mut job = Job {
            name: name.into(),
            template_path,
            mapping: seed_mapping(&fields, derived)?,
            filename_pattern: if template.ends_with(".txt") {
                ""
            } else {
                "구매입찰공고-{{입찰공고번호}}"
            }
            .into(),
            data_path,
            data_sheet: sheet.into(),
            ..Job::default()
        };
        let home = seeded.home.clone();
        JobRegistry::new(home.join("jobs"), move || home.join("templates"))?
            .save(&mut job, false)?;
        context.insert("job_name".into(), json!(name));
        context.insert("seeded".into(), Value::Bool(true));
        context.insert("seed_notice".into(), json!(format!("이 과정용 연습 작업 '{name}'을 준비했습니다. 다른 과정의 완료 기록은 바꾸지 않습니다.")));
    }
    if matches!(lesson, "first_hwpx" | "contract_txt") {
        let data_path = asset_path(&context, DATA_NAME)?;
        let pool = DatasetPoolRegistry::new(seeded.home.join("datasets"))?;
        let mut keys = Map::new();
        for sheet in ["공고", "계약"] {
            let opts = json!({"path":data_path,"sheet":sheet,"header_row":1})
                .as_object()
                .expect("opts object")
                .clone();
            let mut reference = DatasetReference::new("공고목록", "excel", opts)?;
            if lesson == "first_hwpx" && sheet == "공고" {
                reference.filters.push(FilterPreset {
                    name: "소상공인".into(),
                    state: json!({"columns":{"메모":{"text":"소상공인"}}})
                        .as_object()
                        .expect("filter object")
                        .clone(),
                });
            }
            keys.insert(sheet.into(), json!(pool.add(&reference)?));
        }
        context.insert("pool_keys".into(), Value::Object(keys));
    }
    Ok(context)
}

fn job_for(lesson: &str) -> Option<(&'static str, &'static str, bool, &'static str)> {
    match lesson {
        "replace_data" => Some(("공고서 작업", HWPX_NAME, false, "공고")),
        "purchase_txt" => Some(("구매추진 안내 작업", PURCHASE_NAME, false, "공고")),
        "blank_values" => Some(("계약 안내 작업(빈 칸)", TXT_NAME, true, "계약")),
        "change_apply" => Some(("계약 안내 작업", TXT_NAME, false, "계약")),
        _ => None,
    }
}

fn asset_path(context: &Map<String, Value>, name: &str) -> Result<String, SeedError> {
    context
        .get("assets")
        .and_then(|value| value.get(name))
        .and_then(|value| value.get("path"))
        .and_then(Value::as_str)
        .filter(|path| !path.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| "연습 파일을 먼저 준비하세요.".into())
}

fn rewrite_option_txt(
    seeded: &mut SeededLesson,
    context: &mut Map<String, Value>,
) -> Result<(), SeedError> {
    let entry = seeded
        .assets
        .iter_mut()
        .find(|entry| entry.name == TXT_NAME)
        .ok_or("연습 파일을 먼저 준비하세요.")?;
    let source = fs::read_to_string(&entry.path)?
        .replace("\r\n", "\n")
        .replace('\r', "\n");
    let mut rewritten = String::new();
    let mut changed = false;
    for line in source.split_inclusive('\n') {
        rewritten.push_str(line);
        if !changed && line.starts_with("3. ") {
            rewritten.push('\n');
            changed = true;
        }
    }
    if changed {
        fs::write(
            &entry.path,
            rewritten.replace('\n', if cfg!(windows) { "\r\n" } else { "\n" }),
        )?;
        entry.sha256 = fingerprint(Path::new(&entry.path))?;
        context["assets"][TXT_NAME] = json!(entry);
    }
    Ok(())
}

fn template_fields(path: &Path, is_txt: bool) -> Result<Vec<String>, SeedError> {
    if !is_txt {
        let bytes = fs::read(path)?;
        let package = HwpxPackage::from_bytes(&bytes, PackageLimits::default())?;
        return Ok(extract_schema(&package)?.field_names());
    }
    let content = fs::read_to_string(path)?;
    let mut fields = Vec::new();
    let mut seen = HashSet::new();
    for tail in content.split("{{").skip(1) {
        let Some((name, _)) = tail.split_once("}}") else {
            continue;
        };
        if name.is_empty() || name.chars().any(|ch| "{}#/".contains(ch)) || !seen.insert(name) {
            continue;
        }
        fields.push(name.to_owned());
    }
    Ok(fields)
}

fn seed_mapping(fields: &[String], blank_unit: bool) -> Result<MappingProfile, SeedError> {
    let mut mappings = Vec::with_capacity(fields.len());
    for field in fields {
        let constant = match field.as_str() {
            "계약담당자" => Some("홍길동"),
            "계약담당 전화번호" => Some("042-000-0000"),
            "계약담당 팩스번호" => Some("0505-000-0000"),
            "단위" if blank_unit => Some(""),
            _ => None,
        };
        if let Some(value) = constant {
            mappings.push(FieldMapping::new(field, "", "const", value, "", None)?);
            continue;
        }
        let kind = infer_type(field);
        let kind = if matches!(kind, "date" | "amount") {
            kind
        } else {
            "text"
        };
        let fmt = if field == "게시일" && kind == "date" {
            "ym"
        } else if kind == "date" && field.ends_with("일시") {
            "datetime"
        } else {
            ""
        };
        let source = match field.as_str() {
            "낙찰자결정방법" => "낙찰방법",
            "담당자 전화번호" => "담당자전화",
            "대표계약업체" => "계약상대자",
            "게시일" => "게시일시",
            _ => field,
        };
        mappings.push(FieldMapping::new(field, source, kind, "", fmt, None)?);
    }
    Ok(MappingProfile::new("", mappings, Map::new())?)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{derived_for, seed_before_switch};
    use crate::job_registry::JobRegistry;
    use crate::tutorial_workspace::TutorialWorkspace;
    use std::path::Path;
    use uuid::Uuid;

    #[test]
    fn lesson_seed_writes_real_job_and_pool_in_practice_home() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache/tutorial-seed")
            .join(Uuid::new_v4().to_string());
        let workspace = TutorialWorkspace::new(
            root.clone(),
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../examples/tutorial"),
            |_| {},
        );
        let mut first = workspace.seed_originals("first_hwpx").unwrap();
        let context = seed_before_switch("first_hwpx", &mut first).unwrap();
        assert_eq!(context["pool_keys"].as_object().unwrap().len(), 2);
        let (kind, name, _) = derived_for("blank_values");
        let mut blank = workspace.seed("blank_values", kind, name).unwrap();
        let context = seed_before_switch("blank_values", &mut blank).unwrap();
        let home = blank.home.clone();
        let registry = JobRegistry::new(home.join("jobs"), move || home.join("templates")).unwrap();
        let job = registry.load("계약 안내 작업(빈 칸)").unwrap();
        assert_eq!(
            job.data_path,
            context["derived_data_path"].as_str().unwrap()
        );
        assert!(
            job.mapping
                .mappings
                .iter()
                .any(|row| row.template_field == "단위" && row.is_declared_empty())
        );
        let mut option = workspace.seed_originals("option_apply").unwrap();
        let context = seed_before_switch("option_apply", &mut option).unwrap();
        let path = context["assets"]["낙찰자 선정 및 계약체결 안내.txt"]["path"]
            .as_str()
            .unwrap();
        let bytes = std::fs::read(path).unwrap();
        if cfg!(windows) {
            assert!(bytes.windows(2).any(|pair| pair == b"\r\n"));
            assert!(!bytes.windows(2).any(|pair| pair == b"\n\n"));
            assert_eq!(
                bytes.iter().filter(|byte| **byte == b'\r').count(),
                bytes.iter().filter(|byte| **byte == b'\n').count()
            );
        }
        std::fs::remove_dir_all(root).unwrap();
    }
}
