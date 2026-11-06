//! Pure import plan over receiving-side facts. No file or registry effects live here.

use crate::copy_name::{device_safe_file_name, first_free, numbered_file_name, numbered_label};
use crate::data_contract::{DataContract, decode_data_contract, encode_data_contract};
use crate::data_contract_check::{judge_job_contract, profile_data_contract};
use crate::job::{Job, sorted_json};
use crate::preset::SelectionPreset;
use crate::python_casefold::python_casefold;
use crate::slot_selection::SlotSelectionSet;
use crate::text_render::python_repr;
use crate::work_package::{
    PackagedJob, PackagedTemplate, WorkPackageError, WorkPackageManifest, encode_work_package,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};

pub const TEMPLATE_REUSE: &str = "reuse";
pub const TEMPLATE_NEW: &str = "new";

pub trait ReceivingSide {
    fn job_taken(&self, name: &str) -> bool;
    fn job_key(&self, name: &str) -> String;
    fn preset_taken(&self, name: &str) -> bool;
    fn file_taken(&self, file_name: &str) -> bool;
    fn existing_template(&self, template: &PackagedTemplate) -> Option<String>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlannedTemplate {
    pub template: PackagedTemplate,
    pub action: String,
    /// Existing path for reuse, new basename for installation.
    pub target: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlannedJob {
    pub source: PackagedJob,
    pub final_name: String,
    pub contract: Option<DataContract>,
}
impl PlannedJob {
    pub fn renamed(&self) -> bool {
        self.final_name != self.source.name
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlannedPreset {
    pub job_name: String,
    pub original_name: String,
    pub preset: SelectionPreset,
}
impl PlannedPreset {
    pub fn renamed(&self) -> bool {
        self.preset.name != self.original_name
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ImportPlan {
    pub templates: Vec<PlannedTemplate>,
    pub jobs: Vec<PlannedJob>,
    pub presets: Vec<PlannedPreset>,
    pub basis: String,
}
impl ImportPlan {
    pub fn template_for(&self, digest: &str) -> Option<&PlannedTemplate> {
        self.templates
            .iter()
            .find(|item| item.template.digest == digest)
    }
}

pub fn plan_view(plan: &ImportPlan) -> Value {
    let label = |action: &str| {
        if action == TEMPLATE_NEW {
            "새로 추가"
        } else {
            "이미 있는 파일 사용"
        }
    };
    let renamed = |name: &str| format!("‘{name}’ 이름으로 불러옵니다");
    json!({
        "title": format!("작업 {}개를 불러옵니다", plan.jobs.len()),
        "jobs": plan.jobs.iter().map(|item| {
            let template = plan.template_for(&item.source.template_digest)
                .expect("validated plan template");
            json!({
                "name": item.source.name, "final_name": item.final_name,
                "note": if item.renamed() { renamed(&item.final_name) } else { String::new() },
                "template": template.template.display_name,
                "template_label": label(&template.action),
                "has_contract": item.contract.is_some(),
            })
        }).collect::<Vec<_>>(),
        "templates": plan.templates.iter().map(|item| json!({
            "display_name": item.template.display_name, "action": item.action,
            "label": label(&item.action), "target": item.target,
        })).collect::<Vec<_>>(),
        "presets": plan.presets.iter().map(|item| json!({
            "name": item.original_name, "final_name": item.preset.name,
            "job": item.job_name,
            "note": if item.renamed() { renamed(&item.preset.name) } else { String::new() },
        })).collect::<Vec<_>>(),
        "data_notice": "데이터는 들어 있지 않습니다.",
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DataBinding {
    pub path: String,
    pub sheet: String,
    pub header_row: u64,
    pub kind: String,
}
pub struct DataReading {
    pub binding: DataBinding,
    pub columns: Option<Vec<String>>,
    pub records: Vec<serde_json::Map<String, Value>>,
}
pub fn choose_import_binding(
    job: &Job,
    readings: &[DataReading],
) -> (&'static str, Option<DataBinding>) {
    let Some(contract) = &job.data_contract else {
        return ("no_contract", None);
    };
    if readings.iter().any(|reading| reading.columns.is_none()) {
        return ("unreadable", None);
    }
    let matches = readings
        .iter()
        .filter(|reading| {
            judge_job_contract(
                contract,
                &job.mapping,
                reading.columns.as_deref().unwrap_or(&[]),
                &reading.records,
            )
            .passed
        })
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [only] => ("bound", Some(only.binding.clone())),
        [] => ("no_match", None),
        _ => ("ambiguous", None),
    }
}

pub fn plan_import(
    manifest: &WorkPackageManifest,
    side: &impl ReceivingSide,
) -> Result<ImportPlan, WorkPackageError> {
    manifest.validate()?;
    let mut templates = Vec::new();
    let mut claimed_files = HashSet::new();
    for template in &manifest.templates {
        if let Some(existing) = side.existing_template(template) {
            templates.push(PlannedTemplate {
                template: template.clone(),
                action: TEMPLATE_REUSE.into(),
                target: existing,
            });
            continue;
        }
        let base = device_safe_file_name(&template.display_name);
        let target = first_free(
            |number| numbered_file_name(&base, number),
            |candidate| {
                side.file_taken(candidate) || claimed_files.contains(&python_casefold(candidate))
            },
        );
        claimed_files.insert(python_casefold(&target));
        templates.push(PlannedTemplate {
            template: template.clone(),
            action: TEMPLATE_NEW.into(),
            target,
        });
    }
    let mut jobs = Vec::new();
    let mut claimed_jobs = HashSet::new();
    for job in &manifest.jobs {
        let final_name = first_free(
            |number| numbered_label(&job.name, number),
            |candidate| {
                side.job_taken(candidate) || claimed_jobs.contains(&side.job_key(candidate))
            },
        );
        claimed_jobs.insert(side.job_key(&final_name));
        let contract = job
            .data_contract
            .as_ref()
            .map(|raw| {
                decode_data_contract(&Value::Object(raw.clone())).map_err(|error| {
                    WorkPackageError(format!(
                        "작업 {}의 데이터 계약을 읽을 수 없습니다: {error}",
                        python_repr(&Value::String(job.name.clone()))
                    ))
                })
            })
            .transpose()?;
        jobs.push(PlannedJob {
            source: job.clone(),
            final_name,
            contract,
        });
    }
    let mut presets = Vec::new();
    let mut claimed_presets = HashSet::new();
    for job in &jobs {
        for preset in &job.source.selection_presets {
            let name = first_free(
                |number| numbered_label(&preset.name, number),
                |candidate| side.preset_taken(candidate) || claimed_presets.contains(candidate),
            );
            claimed_presets.insert(name.clone());
            let mut copy = preset.clone();
            copy.name = name;
            copy.provenance.clear();
            presets.push(PlannedPreset {
                job_name: job.final_name.clone(),
                original_name: preset.name.clone(),
                preset: copy,
            });
        }
    }
    let payload = json!({
        "package": encode_work_package(manifest)?,
        "templates": templates.iter().map(|item| json!([item.template.digest, item.action, item.target])).collect::<Vec<_>>(),
        "jobs": jobs.iter().map(|item| item.final_name.clone()).collect::<Vec<_>>(),
        "presets": presets.iter().map(|item| json!([item.job_name, item.preset.name])).collect::<Vec<_>>(),
    });
    let basis = Sha256::digest(sorted_json(&payload).as_bytes())
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(ImportPlan {
        templates,
        jobs,
        presets,
        basis,
    })
}

pub fn imported_job(planned: &PlannedJob, template_path: &str) -> Job {
    Job {
        name: planned.final_name.clone(),
        template_path: template_path.into(),
        mapping: planned.source.mapping.clone(),
        filename_pattern: planned.source.filename_pattern.clone(),
        data_contract: planned.contract.clone(),
        ..Job::default()
    }
}

/// Read-only sources for a portable package. A missing template skips that job;
/// unavailable bound data keeps the job but requires a human export confirmation.
pub trait ExportSources {
    fn template_bytes(&self, job: &Job) -> Result<Vec<u8>, String>;
    fn declared_selection(&self, job: &Job) -> Result<Option<SlotSelectionSet>, String>;
    fn records(&self, job: &Job) -> Result<Vec<serde_json::Map<String, Value>>, String>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkPackageDraft {
    pub manifest: WorkPackageManifest,
    pub templates: HashMap<String, Vec<u8>>,
    pub without_contract: Vec<String>,
    pub skipped: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DraftError {
    NothingToExport { skipped: Vec<String> },
    Invalid(WorkPackageError),
}
impl std::fmt::Display for DraftError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NothingToExport { skipped } => f.write_str(&skipped.join(", ")),
            Self::Invalid(error) => write!(f, "{error}"),
        }
    }
}
impl std::error::Error for DraftError {}
impl From<WorkPackageError> for DraftError {
    fn from(error: WorkPackageError) -> Self {
        Self::Invalid(error)
    }
}

pub fn draft_work_package(
    jobs: &[Job],
    sources: &impl ExportSources,
    created_at: &str,
) -> Result<WorkPackageDraft, DraftError> {
    let mut declared = Vec::new();
    let mut blobs = HashMap::new();
    let mut packaged = Vec::new();
    let mut without = Vec::new();
    let mut skipped = Vec::new();
    for job in jobs {
        let Ok(blob) = sources.template_bytes(job) else {
            skipped.push(job.name.clone());
            continue;
        };
        let digest = Sha256::digest(&blob)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        if !blobs.contains_key(&digest) {
            declared.push(PackagedTemplate {
                digest: digest.clone(),
                media: job.media().into(),
                display_name: job
                    .template_path
                    .rsplit(['/', '\\'])
                    .next()
                    .unwrap_or("")
                    .into(),
                size: blob.len() as u64,
            });
            blobs.insert(digest.clone(), blob);
        }
        let contract = if !job.has_data_binding() {
            None
        } else {
            match sources.records(job) {
                Err(_) => None,
                Ok(records) => {
                    let contract = profile_data_contract(&job.mapping, &records)
                        .map_err(|error| WorkPackageError(error.to_string()))?;
                    let value = encode_data_contract(&contract)
                        .map_err(|error| WorkPackageError(error.to_string()))?;
                    Some(value.as_object().expect("encoded contract object").clone())
                }
            }
        };
        if contract.is_none() {
            without.push(job.name.clone());
        }
        let selection_presets = sources
            .declared_selection(job)
            .map_err(WorkPackageError)?
            .map(|selection_set| {
                SelectionPreset::new(
                    job.name.clone(),
                    selection_set,
                    Vec::new(),
                    created_at.to_owned(),
                )
                .map_err(|error| WorkPackageError(error.to_string()))
            })
            .transpose()?
            .into_iter()
            .collect();
        let mut mapping = job.mapping.clone();
        mapping.provenance.clear();
        packaged.push(PackagedJob {
            name: job.name.clone(),
            media: job.media().into(),
            template_digest: digest,
            mapping,
            filename_pattern: job.filename_pattern.clone(),
            selection_presets,
            data_contract: contract,
        });
    }
    if packaged.is_empty() {
        return Err(DraftError::NothingToExport { skipped });
    }
    let manifest = WorkPackageManifest {
        created_at: created_at.into(),
        templates: declared,
        jobs: packaged,
    };
    manifest.validate()?;
    Ok(WorkPackageDraft {
        manifest,
        templates: blobs,
        without_contract: without,
        skipped,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{
        DataBinding, DataReading, ExportSources, ReceivingSide, TEMPLATE_NEW,
        choose_import_binding, draft_work_package, imported_job, plan_import, plan_view,
    };
    use crate::data_contract_check::profile_data_contract;
    use crate::job::Job;
    use crate::mapping::{FieldMapping, MappingProfile};
    use crate::python_casefold::python_casefold;
    use crate::slot_selection::SlotSelectionSet;
    use crate::work_package::{PackagedJob, PackagedTemplate, WorkPackageManifest};
    use serde_json::{Map, Value};
    use std::collections::{HashMap, HashSet};

    #[derive(Default)]
    struct Side {
        jobs: HashSet<String>,
        presets: HashSet<String>,
        files: HashSet<String>,
        existing: HashMap<String, String>,
    }
    impl ReceivingSide for Side {
        fn job_taken(&self, name: &str) -> bool {
            self.jobs.contains(name)
        }
        fn job_key(&self, name: &str) -> String {
            python_casefold(name)
        }
        fn preset_taken(&self, name: &str) -> bool {
            self.presets.contains(name)
        }
        fn file_taken(&self, name: &str) -> bool {
            self.files
                .iter()
                .any(|file| python_casefold(file) == python_casefold(name))
        }
        fn existing_template(&self, template: &PackagedTemplate) -> Option<String> {
            self.existing.get(&template.digest).cloned()
        }
    }
    struct Sources;
    impl ExportSources for Sources {
        fn template_bytes(&self, job: &Job) -> Result<Vec<u8>, String> {
            if job.name == "빠짐" {
                Err("unreadable".into())
            } else {
                Ok(b"hwpx template bytes".to_vec())
            }
        }
        fn declared_selection(&self, _: &Job) -> Result<Option<SlotSelectionSet>, String> {
            Ok(None)
        }
        fn records(&self, _: &Job) -> Result<Vec<Map<String, Value>>, String> {
            Err("unavailable".into())
        }
    }

    #[test]
    fn import_autobind_requires_one_readable_matching_source() {
        let mapping = MappingProfile::new(
            "",
            vec![FieldMapping::new("금액", "열", "amount", "", "", None).unwrap()],
            Map::new(),
        )
        .unwrap();
        let record = serde_json::from_str::<Map<String, Value>>(r#"{"열":"1000"}"#).unwrap();
        let contract = profile_data_contract(&mapping, std::slice::from_ref(&record)).unwrap();
        let mut job = Job {
            mapping,
            data_contract: Some(contract),
            ..Job::default()
        };
        let reading = |path: &str, columns: Option<Vec<String>>| DataReading {
            binding: DataBinding {
                path: path.into(),
                sheet: "".into(),
                header_row: 0,
                kind: "".into(),
            },
            columns,
            records: vec![record.clone()],
        };
        assert_eq!(
            choose_import_binding(&job, &[reading("a", Some(vec!["열".into()]))]).0,
            "bound"
        );
        assert_eq!(
            choose_import_binding(&job, &[reading("a", Some(vec!["다른열".into()]))]).0,
            "no_match"
        );
        let mut bad = reading("bad", Some(vec!["열".into()]));
        bad.records[0]["열"] = serde_json::json!("미정");
        assert_eq!(
            choose_import_binding(&job, std::slice::from_ref(&bad)).0,
            "no_match"
        );
        let (status, binding) =
            choose_import_binding(&job, &[reading("a", Some(vec!["열".into()])), bad]);
        assert_eq!(status, "bound");
        assert_eq!(binding.unwrap().path, "a");
        assert_eq!(
            choose_import_binding(
                &job,
                &[
                    reading("a", Some(vec!["열".into()])),
                    reading("b", Some(vec!["열".into()]))
                ]
            )
            .0,
            "ambiguous"
        );
        assert_eq!(
            choose_import_binding(
                &job,
                &[reading("a", Some(vec!["열".into()])), reading("b", None)]
            )
            .0,
            "unreadable"
        );
        job.data_contract = None;
        assert_eq!(choose_import_binding(&job, &[]).0, "no_contract");
    }

    fn manifest() -> WorkPackageManifest {
        let digest = "2c948b4583dcfc704de8e8b6afd2c9ccf65043b4ea5b0743be1bd945ef6c4d40";
        WorkPackageManifest {
            created_at: "2026-10-15T09:00:00".into(),
            templates: vec![PackagedTemplate {
                digest: digest.into(),
                media: "hwpx".into(),
                display_name: "공고서.hwpx".into(),
                size: 19,
            }],
            jobs: vec![PackagedJob {
                name: "계약".into(),
                media: "hwpx".into(),
                template_digest: digest.into(),
                mapping: MappingProfile::new(
                    "",
                    vec![FieldMapping::new("건명", "공고명", "text", "", "", None).unwrap()],
                    Map::new(),
                )
                .unwrap(),
                filename_pattern: "공고-{{seq:001}}".into(),
                selection_presets: Vec::new(),
                data_contract: None,
            }],
        }
    }

    #[test]
    fn import_plan_basis_and_new_job_match_python_oracle() {
        let manifest = manifest();
        let plan = plan_import(&manifest, &Side::default()).unwrap();
        let view = plan_view(&plan);
        assert_eq!(view["jobs"][0]["template_label"], "새로 추가");
        assert_eq!(view["jobs"][0]["has_contract"], false);
        assert_eq!(view["data_notice"], "데이터는 들어 있지 않습니다.");
        assert_eq!(
            plan.basis,
            "5fd3f97d91842be586db1f2e3267ffe50586b81a5bcfff0f4a46886e3a6bf262"
        );
        assert_eq!(
            (
                plan.templates[0].action.as_str(),
                plan.templates[0].target.as_str()
            ),
            (TEMPLATE_NEW, "공고서.hwpx")
        );
        let mut job = imported_job(&plan.jobs[0], "C:/서식/공고서.hwpx");
        assert_eq!(
            (
                job.name.as_str(),
                job.template_path.as_str(),
                job.data_path.as_str(),
                job.authority_id.as_str()
            ),
            ("계약", "C:/서식/공고서.hwpx", "", "")
        );
        assert!(job.reviewed_rules.is_empty());
        assert_eq!(job.previous_rules, serde_json::json!({}));
        assert_eq!(job.template_revision, 1);
        job.mapping.name = "changed copy".into();
        assert_eq!(plan.jobs[0].source.mapping.name, "");
        let jobs = ["가", "나", "빠짐"].map(|name| Job {
            name: name.into(),
            template_path: "C:/공고서.hwpx".into(),
            mapping: manifest.jobs[0].mapping.clone(),
            ..Job::default()
        });
        let draft = draft_work_package(&jobs, &Sources, "2026-10-15T09:00:00").unwrap();
        assert_eq!(draft.manifest.templates.len(), 1);
        assert_eq!(
            draft
                .manifest
                .jobs
                .iter()
                .map(|job| job.name.as_str())
                .collect::<Vec<_>>(),
            ["가", "나"]
        );
        assert_eq!(draft.without_contract, ["가", "나"]);
        assert_eq!(draft.skipped, ["빠짐"]);
        assert_eq!(
            draft_work_package(&jobs[2..], &Sources, "2026-10-15T09:00:00").unwrap_err(),
            super::DraftError::NothingToExport {
                skipped: vec!["빠짐".into()]
            }
        );
        assert_eq!(
            draft_work_package(&[], &Sources, "2026-10-15T09:00:00").unwrap_err(),
            super::DraftError::NothingToExport {
                skipped: Vec::new()
            }
        );
    }

    fn selection() -> SlotSelectionSet {
        SlotSelectionSet::new(vec![
            crate::slot_selection::SlotSelection::new("s1", vec!["o1".into()]).unwrap(),
        ])
        .unwrap()
    }

    #[test]
    fn import_collisions_are_renamed_and_receiving_changes_invalidate_confirmation() {
        let mut manifest = manifest();
        manifest.jobs[0].selection_presets.push(
            crate::preset::SelectionPreset::new(
                "계약",
                selection(),
                Vec::new(),
                manifest.created_at.clone(),
            )
            .unwrap(),
        );
        let mut another = manifest.jobs[0].clone();
        another.name = "기안".into();
        manifest.jobs.push(another);
        let empty = Side::default();
        let initial = plan_import(&manifest, &empty).unwrap();
        assert_eq!(plan_import(&manifest, &empty).unwrap().basis, initial.basis);
        let mut side = Side {
            jobs: ["계약".into(), "계약 (2)".into()].into(),
            presets: ["계약".into()].into(),
            ..Side::default()
        };
        let renamed = plan_import(&manifest, &side).unwrap();
        assert_ne!(renamed.basis, initial.basis);
        side.existing.insert(
            manifest.templates[0].digest.clone(),
            "C:/서식/공고서.hwpx".into(),
        );
        let reused = plan_import(&manifest, &side).unwrap();
        assert_ne!(reused.basis, renamed.basis);
        assert_eq!(
            (reused.jobs[0].final_name.as_str(), reused.jobs[0].renamed()),
            ("계약 (3)", true)
        );
        assert_eq!(
            (reused.jobs[1].final_name.as_str(), reused.jobs[1].renamed()),
            ("기안", false)
        );
        assert_eq!(
            (
                reused.presets[0].job_name.as_str(),
                reused.presets[0].preset.name.as_str()
            ),
            ("계약 (3)", "계약 (2)")
        );
        assert_eq!(reused.presets[1].preset.name, "계약 (3)");
        assert!(
            reused
                .presets
                .iter()
                .all(|preset| preset.renamed() && preset.preset.provenance.is_empty())
        );
        assert_eq!(
            (
                reused.templates[0].action.as_str(),
                reused.templates[0].target.as_str()
            ),
            (super::TEMPLATE_REUSE, "C:/서식/공고서.hwpx")
        );
        let view = plan_view(&reused);
        assert_eq!(view["jobs"][0]["note"], "‘계약 (3)’ 이름으로 불러옵니다");
        assert_eq!(view["templates"][0]["label"], "이미 있는 파일 사용");
        assert!(reused.template_for("missing").is_none());
        manifest.jobs[0].data_contract = Some(
            serde_json::json!({"schema":"data-contract/v9","fields":[]})
                .as_object()
                .unwrap()
                .clone(),
        );
        assert!(
            plan_import(&manifest, &side)
                .unwrap_err()
                .0
                .contains("데이터 계약을 읽을 수 없습니다")
        );
        assert_device_safe_plan();
    }

    fn assert_device_safe_plan() {
        use crate::copy_name::{device_safe_file_name, numbered_file_name, numbered_label};
        for (base, number, expected) in [
            ("계약.안내.hwpx", 2, "계약.안내 (2).hwpx"),
            ("확장자없음", 2, "확장자없음 (2)"),
            (".hidden", 2, ".hidden (2)"),
        ] {
            assert_eq!(numbered_file_name(base, number), expected);
        }
        assert_eq!(numbered_label("계약", 1), "계약");
        assert_eq!(numbered_label("계약", 3), "계약 (3)");
        for (name, expected) in [
            ("CON.hwpx", "CON_.hwpx"),
            ("lpt1.backup.txt", "lpt1_.backup.txt"),
            ("CONTRACT.hwpx", "CONTRACT.hwpx"),
            ("NUL", "NUL_"),
        ] {
            assert_eq!(device_safe_file_name(name), expected);
        }
        let mut manifest = manifest();
        manifest.templates[0].display_name = "CON.hwpx".into();
        let mut template = manifest.templates[0].clone();
        template.digest = "b".repeat(64);
        template.display_name = "con.hwpx".into();
        let mut job = manifest.jobs[0].clone();
        job.name = "계약 (2)".into();
        job.template_digest.clone_from(&template.digest);
        manifest.templates.push(template);
        manifest.jobs.push(job);
        let side = Side {
            files: ["CON_.hwpx".into()].into(),
            jobs: ["계약".into()].into(),
            ..Side::default()
        };
        let plan = plan_import(&manifest, &side).unwrap();
        assert_eq!(
            plan.templates
                .iter()
                .map(|template| template.target.as_str())
                .collect::<Vec<_>>(),
            ["CON_ (2).hwpx", "con_ (3).hwpx"]
        );
        assert_eq!(
            plan.jobs
                .iter()
                .map(|job| job.final_name.as_str())
                .collect::<Vec<_>>(),
            ["계약 (2)", "계약 (2) (2)"]
        );
    }

    #[test]
    fn export_copies_strip_provenance_without_leaking_data_or_mutating_sources() {
        struct Readable;
        impl ExportSources for Readable {
            fn template_bytes(&self, job: &Job) -> Result<Vec<u8>, String> {
                Sources.template_bytes(job)
            }
            fn declared_selection(&self, _: &Job) -> Result<Option<SlotSelectionSet>, String> {
                Ok(Some(selection()))
            }
            fn records(&self, _: &Job) -> Result<Vec<Map<String, Value>>, String> {
                Ok(vec![
                    serde_json::from_value(serde_json::json!({"공고명":"전산장비"})).unwrap(),
                ])
            }
        }
        let jobs = ["가", "나"].map(|name| Job {
            name: name.into(),
            template_path: "C:\\홈\\template_authority\\applied\\x\\공고서.hwpx".into(),
            data_path: "C:/데이터/보낸쪽데이터.xlsx".into(),
            mapping: MappingProfile::new(
                "공고",
                vec![
                    FieldMapping::new("건명", "공고명", "text", "", "", None).unwrap(),
                    FieldMapping::new("담당", "", "const", "홍길동", "", None).unwrap(),
                ],
                serde_json::from_value(serde_json::json!({"dataset":"보낸쪽데이터.xlsx"})).unwrap(),
            )
            .unwrap(),
            ..Job::default()
        });
        let before = jobs.clone();
        let draft = draft_work_package(&jobs, &Readable, "2026-10-15T09:00:00").unwrap();
        assert_eq!(jobs, before);
        assert!(draft.without_contract.is_empty() && draft.skipped.is_empty());
        assert_eq!(draft.manifest.templates.len(), 1);
        assert_eq!(draft.manifest.templates[0].display_name, "공고서.hwpx");
        assert_eq!(draft.templates.len(), 1);
        assert_eq!(
            draft.templates[&draft.manifest.templates[0].digest],
            b"hwpx template bytes"
        );
        for (packaged, source) in draft.manifest.jobs.iter().zip(&jobs) {
            assert_eq!(packaged.mapping.mappings, source.mapping.mappings);
            assert!(packaged.mapping.provenance.is_empty());
            assert_eq!(packaged.selection_presets[0].name, source.name);
            assert!(packaged.selection_presets[0].provenance.is_empty());
            assert_eq!(packaged.selection_presets[0].selection_set, selection());
            assert!(packaged.data_contract.is_some());
            assert!(
                !serde_json::to_string(&packaged.data_contract)
                    .unwrap()
                    .contains("전산장비")
            );
        }
        let unavailable = draft_work_package(&jobs, &Sources, "2026-10-15T09:00:00").unwrap();
        assert_eq!(unavailable.without_contract, ["가", "나"]);
        assert!(
            unavailable
                .manifest
                .jobs
                .iter()
                .all(|job| job.data_contract.is_none() && job.selection_presets.is_empty())
        );
    }
}
