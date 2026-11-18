//! Read-only package export facts from exact applied authority and current data.

use crate::candidate_store::FileCandidateObjectStore;
use crate::qualification_store::FileQualificationObjectStore;
use crate::work_configuration_store::WorkSlotConfigurationStore;
use crate::work_template_store::{AtomicWorkTemplateStateStore, WorkStoreErrorKind};
use hwpx_filler::candidate_revision::TemplateRevision;
use hwpx_filler::data_factory::source_for_binding;
use hwpx_filler::execution_structure::QualificationProfileManifest;
use hwpx_filler::job::Job;
use hwpx_filler::qualification_evidence::QualificationEvidence;
use hwpx_filler::slot_configuration_context::{
    AppliedCandidateReadPort, ContextPorts, QualificationReadPort, WorkTemplateStateReadPort,
    resolve_exact_applied_template_input,
};
use hwpx_filler::slot_selection::SlotSelectionSet;
use hwpx_filler::text_render::python_repr;
use hwpx_filler::work_package_plan::ExportSources;
use hwpx_filler::work_slot_configuration::has_declared_selection;
use hwpx_filler::work_template_state::WorkTemplateStateAggregate;
use serde_json::{Map, Value};
use std::fs;
use std::path::{Path, PathBuf};

impl WorkTemplateStateReadPort for AtomicWorkTemplateStateStore {
    fn load(&self, work_id: &str) -> Result<Option<WorkTemplateStateAggregate>, String> {
        match AtomicWorkTemplateStateStore::load(self, work_id) {
            Ok(state) => Ok(Some(state)),
            Err(error) if error.kind == WorkStoreErrorKind::NotFound => Ok(None),
            Err(error) => Err(error.to_string()),
        }
    }
}
impl QualificationReadPort for FileQualificationObjectStore {
    fn get_evidence(&self, id: &str) -> Result<QualificationEvidence, String> {
        FileQualificationObjectStore::get_evidence(self, id).map_err(|error| error.to_string())
    }
    fn get_manifest(&self, id: &str) -> Result<QualificationProfileManifest, String> {
        FileQualificationObjectStore::get_manifest(self, id).map_err(|error| error.to_string())
    }
}
impl AppliedCandidateReadPort for FileCandidateObjectStore {
    fn get_revision(&self, id: &str) -> Result<TemplateRevision, String> {
        FileCandidateObjectStore::get_revision(self, id).map_err(|error| error.to_string())
    }
    fn has_blob(&self, digest: &str) -> Result<bool, String> {
        FileCandidateObjectStore::has_blob(self, digest).map_err(|error| error.to_string())
    }
}

pub struct WorkPackageSources {
    works: AtomicWorkTemplateStateStore,
    configs: WorkSlotConfigurationStore,
    candidates: FileCandidateObjectStore,
    qualifications: FileQualificationObjectStore,
}
impl WorkPackageSources {
    pub fn new(authority_root: &Path) -> Result<Self, String> {
        Ok(Self {
            works: AtomicWorkTemplateStateStore::new(authority_root.join("works"))
                .map_err(|e| e.to_string())?,
            configs: WorkSlotConfigurationStore::new(authority_root.join("slot_configs"))
                .map_err(|e| e.to_string())?,
            candidates: FileCandidateObjectStore::new(authority_root.join("candidates")),
            qualifications: FileQualificationObjectStore::new(authority_root.join("qualification")),
        })
    }
    fn applied_bytes(&self, job: &Job) -> Result<Option<Vec<u8>>, String> {
        let work_id = &job.authority_id;
        if work_id.is_empty() || !self.works.exists(work_id).map_err(|e| e.to_string())? {
            return Ok(None);
        }
        let state = self.works.load(work_id).map_err(|e| e.to_string())?;
        let exact = resolve_exact_applied_template_input(
            ContextPorts {
                work_state: &self.works,
                qualification: &self.qualifications,
                candidate: &self.candidates,
            },
            work_id,
            &state.work.current_template_application_id,
        )
        .map_err(|e| e.to_string())?;
        if exact.media != job.media() {
            return Err("적용된 템플릿의 형식을 확인할 수 없습니다".into());
        }
        let blob = self
            .candidates
            .get_blob(&exact.exact_content_digest)
            .map_err(|e| e.to_string())?;
        if blob.media != exact.media {
            return Err("적용된 템플릿의 형식을 확인할 수 없습니다".into());
        }
        Ok(Some(blob.exact_bytes.as_ref().to_vec()))
    }
}
impl ExportSources for WorkPackageSources {
    fn template_bytes(&self, job: &Job) -> Result<Vec<u8>, String> {
        if let Some(bytes) = self.applied_bytes(job)? {
            return Ok(bytes);
        }
        if job.template_path.is_empty() {
            return Err(format!(
                "작업 {}에 연결된 템플릿이 없습니다",
                python_repr(&Value::String(job.name.clone()))
            ));
        }
        fs::read(PathBuf::from(&job.template_path)).map_err(|e| {
            format!(
                "작업 {}의 템플릿 파일을 읽을 수 없습니다: {e}",
                python_repr(&Value::String(job.name.clone()))
            )
        })
    }
    fn declared_selection(&self, job: &Job) -> Result<Option<SlotSelectionSet>, String> {
        let work_id = &job.authority_id;
        if work_id.is_empty()
            || !self.works.exists(work_id).map_err(|e| e.to_string())?
            || !self.configs.exists(work_id).map_err(|e| e.to_string())?
        {
            return Ok(None);
        }
        let current = self
            .works
            .load(work_id)
            .map_err(|e| e.to_string())?
            .work
            .current_template_application_id;
        let stored = self.configs.load(work_id).map_err(|e| e.to_string())?;
        Ok(stored
            .configurations
            .configurations
            .iter()
            .find(|config| config.base_template_application_id == current)
            .filter(|config| has_declared_selection(Some(config)))
            .map(|config| config.selections.clone()))
    }
    fn records(&self, job: &Job) -> Result<Vec<Map<String, Value>>, String> {
        if !job.has_data_binding() {
            return Err(job.name.clone());
        }
        let row = usize::try_from(job.data_header_row).map_err(|_| job.name.clone())?;
        let records =
            source_for_binding(&job.data_path, &job.data_sheet, Some(row), &job.data_kind)
                .map_err(|_| job.name.clone())?
                .records()
                .map_err(|_| job.name.clone())?;
        Ok(records
            .into_iter()
            .map(|record| {
                record
                    .into_iter()
                    .map(|(key, value)| (key, Value::String(value)))
                    .collect()
            })
            .collect())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::WorkPackageSources;
    use crate::work_template_store::AtomicWorkTemplateStateStore;
    use hwpx_filler::job::Job;
    use hwpx_filler::work_package_plan::ExportSources;
    use hwpx_filler::work_template_state::{
        DocumentWork, INITIALIZATION, SCHEMA_VERSION, WorkTemplateApplication,
        WorkTemplateStateAggregate,
    };
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn applied_work_never_exports_unverified_editable_file() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = workspace.join(format!(
            ".cache/package-sources-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let template = root.join("editable.txt");
        fs::write(&template, b"unsaved edit").unwrap();
        let source = WorkPackageSources::new(&root.join("authority")).unwrap();
        let mut job = Job {
            name: "job".into(),
            template_path: template.to_str().unwrap().into(),
            ..Job::default()
        };
        assert_eq!(source.template_bytes(&job).unwrap(), b"unsaved edit");
        job.authority_id = "w".into();
        assert_eq!(source.template_bytes(&job).unwrap(), b"unsaved edit");
        let state = WorkTemplateStateAggregate {
            schema_version: SCHEMA_VERSION.into(),
            aggregate_version: 1,
            work: DocumentWork {
                work_id: "w".into(),
                template_lineage_id: "line".into(),
                current_template_application_id: "a1".into(),
                current_template_preparation_id: None,
                prepare_seq: 0,
            },
            applications: vec![WorkTemplateApplication {
                application_id: "a1".into(),
                work_id: "w".into(),
                application_epoch: 1,
                pass_evidence_id: "missing".into(),
                previous_application_id: None,
                origin: INITIALIZATION.into(),
                prepared_change_id: None,
                actor: "actor".into(),
                applied_at: "now".into(),
            }],
            preparations: vec![],
            prepared_changes: vec![],
        };
        AtomicWorkTemplateStateStore::new(root.join("authority/works"))
            .unwrap()
            .create(&state)
            .unwrap();
        assert!(source.template_bytes(&job).is_err());
        assert_unapplied_source_reads(&source, &root);
        assert_only_current_selection_travels(&source, &job, &root);
        let root = root.canonicalize().unwrap();
        assert!(root.starts_with(&workspace));
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_unapplied_source_reads(source: &WorkPackageSources, root: &std::path::Path) {
        let mut job = Job {
            name: "가".into(),
            ..Job::default()
        };
        assert_eq!(
            source.template_bytes(&job).unwrap_err(),
            "작업 '가'에 연결된 템플릿이 없습니다"
        );
        job.template_path = root.join("missing.txt").to_str().unwrap().into();
        assert!(
            source
                .template_bytes(&job)
                .unwrap_err()
                .starts_with("작업 '가'의 템플릿 파일을 읽을 수 없습니다:")
        );
        assert_eq!(source.records(&job).unwrap_err(), "가");
        assert_eq!(source.declared_selection(&job).unwrap(), None);
        job.authority_id = "missing".into();
        assert_eq!(source.declared_selection(&job).unwrap(), None);
        job.authority_id = "bad/id".into();
        assert!(source.declared_selection(&job).is_err());
        let data = root.join("records.csv");
        fs::write(&data, "공고명\n전산장비\n").unwrap();
        job.data_path = data.to_str().unwrap().into();
        job.data_header_row = 1;
        assert_eq!(
            source.records(&job).unwrap(),
            vec![
                serde_json::from_value::<serde_json::Map<String, serde_json::Value>>(
                    serde_json::json!({"공고명":"전산장비"})
                )
                .unwrap()
            ]
        );
        job.data_path = root.join("unreadable.csv").to_str().unwrap().into();
        assert_eq!(source.records(&job).unwrap_err(), "가");
    }

    fn assert_only_current_selection_travels(
        source: &WorkPackageSources,
        job: &Job,
        root: &std::path::Path,
    ) {
        use hwpx_filler::slot_selection::{SlotSelection, SlotSelectionSet};
        use hwpx_filler::stored_work_configuration::empty_stored;
        use hwpx_filler::work_slot_configuration::create_empty;
        assert_eq!(source.declared_selection(job).unwrap(), None);
        let selected =
            SlotSelectionSet::new(vec![SlotSelection::new("s1", vec!["o1".into()]).unwrap()])
                .unwrap();
        let mut other = create_empty("w", "other", "now").unwrap();
        other.selections = selected.clone();
        let empty = create_empty("w", "a1", "now").unwrap();
        let mut current = empty.clone();
        current.selections = selected.clone();
        source
            .configs
            .create(&empty_stored("workspace", "w").unwrap())
            .unwrap();
        for (index, (configurations, expected)) in [
            (vec![other.clone()], None),
            (vec![other.clone(), empty], None),
            (vec![other, current], Some(selected)),
        ]
        .into_iter()
        .enumerate()
        {
            source
                .configs
                .update("w", index as u64 + 1, |stored| {
                    let mut next = stored.clone();
                    next.aggregate_version += 1;
                    next.configurations.configurations = configurations;
                    Ok(next)
                })
                .unwrap();
            assert_eq!(source.declared_selection(job).unwrap(), expected);
        }
        fs::write(root.join("authority/slot_configs/w.json"), b"broken").unwrap();
        assert!(source.declared_selection(job).is_err());
    }
}
