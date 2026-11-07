//! App-owned editable template link backed by the exact current Candidate blob.

use crate::atomic_file::write_bytes_atomic;
use crate::candidate_store::FileCandidateObjectStore;
use crate::job_registry::JobRegistry;
use crate::qualification_store::FileQualificationObjectStore;
use crate::work_template_store::AtomicWorkTemplateStateStore;
use hwpx_filler::job::Job;
use hwpx_filler::slot_configuration_context::{
    ContextPorts, ExactAppliedTemplateInput, resolve_exact_applied_template_input,
};
use sha2::{Digest, Sha256};
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(Debug)]
pub struct AppliedAssetError(pub String);
impl fmt::Display for AppliedAssetError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AppliedAssetError {}
fn fail(message: impl Into<String>) -> AppliedAssetError {
    AppliedAssetError(message.into())
}

pub struct AppliedTemplateAsset {
    root: PathBuf,
    jobs: Arc<JobRegistry>,
    works: AtomicWorkTemplateStateStore,
    candidates: FileCandidateObjectStore,
    qualifications: FileQualificationObjectStore,
}
impl AppliedTemplateAsset {
    pub fn new(root: &Path, jobs: Arc<JobRegistry>) -> Result<Self, AppliedAssetError> {
        Ok(Self {
            root: root.into(),
            jobs,
            works: AtomicWorkTemplateStateStore::new(root.join("works"))
                .map_err(|e| fail(e.detail))?,
            candidates: FileCandidateObjectStore::new(root.join("candidates")),
            qualifications: FileQualificationObjectStore::new(root.join("qualification")),
        })
    }
    pub fn path(&self, work_id: &str, template_path: &str) -> Result<PathBuf, AppliedAssetError> {
        let name = Path::new(template_path)
            .file_name()
            .ok_or_else(|| fail("템플릿 파일 이름이 없습니다"))?;
        let digest = Sha256::digest(work_id.as_bytes());
        let hex = digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        Ok(self.root.join("applied").join(hex).join(name))
    }
    fn current_exact(&self, job: &Job) -> Result<ExactAppliedTemplateInput, AppliedAssetError> {
        let aggregate = self
            .works
            .load(&job.authority_id)
            .map_err(|e| fail(e.detail))?;
        let exact = resolve_exact_applied_template_input(
            ContextPorts {
                work_state: &self.works,
                qualification: &self.qualifications,
                candidate: &self.candidates,
            },
            &job.authority_id,
            &aggregate.work.current_template_application_id,
        )
        .map_err(|e| fail(e.to_string()))?;
        if exact.media != job.media() {
            return Err(fail("적용된 템플릿의 형식을 확인할 수 없습니다"));
        }
        Ok(exact)
    }
    fn exact_bytes(&self, exact: &ExactAppliedTemplateInput) -> Result<Vec<u8>, AppliedAssetError> {
        let blob = self
            .candidates
            .get_blob(&exact.exact_content_digest)
            .map_err(|e| fail(e.detail))?;
        if blob.media != exact.media {
            return Err(fail("적용된 템플릿의 형식을 확인할 수 없습니다"));
        }
        Ok(blob.exact_bytes.as_ref().to_vec())
    }
    pub fn current_bytes(&self, job: &Job) -> Result<Option<Vec<u8>>, AppliedAssetError> {
        if job.authority_id.is_empty()
            || !self
                .works
                .exists(&job.authority_id)
                .map_err(|e| fail(e.detail))?
        {
            return Ok(None);
        }
        self.exact_bytes(&self.current_exact(job)?).map(Some)
    }
    /// Restore existing Work links from their applied bytes at startup. A Work
    /// already pointing at its app-owned path remains selectable for a loud retry
    /// if its candidate authority is corrupt.
    pub fn migrate(&self) -> Result<(), AppliedAssetError> {
        let (jobs, _) = self
            .jobs
            .list_jobs_with_corruption()
            .map_err(|e| fail(e.to_string()))?;
        for job in jobs {
            if job.authority_id.is_empty()
                || !self
                    .works
                    .exists(&job.authority_id)
                    .map_err(|e| fail(e.detail))?
            {
                continue;
            }
            if let Err(error) = self.adopt(&job.name, false) {
                let current = self.jobs.load(&job.name).map_err(|e| fail(e.to_string()))?;
                if current.template_path
                    != self
                        .path(&current.authority_id, &current.template_path)?
                        .to_string_lossy()
                {
                    return Err(error);
                }
            }
        }
        Ok(())
    }
    /// Resolves the applied exact content for `job`, relinking to its app-owned path first
    /// when the Work link failed and the job is not yet pointed at it (unlinked).
    fn exact_or_relink(
        &self,
        job: &Job,
        job_name: &str,
        path: &Path,
        linked: bool,
    ) -> Result<ExactAppliedTemplateInput, AppliedAssetError> {
        match self.current_exact(job) {
            Ok(exact) => Ok(exact),
            Err(error) => {
                if !linked {
                    self.jobs
                        .relink_template(
                            job_name,
                            &path.to_string_lossy(),
                            Some((&job.authority_id, &job.template_path)),
                        )
                        .map_err(|e| fail(e.to_string()))?;
                }
                Err(error)
            }
        }
    }
    fn write_template_bytes(path: &Path, bytes: &[u8]) -> Result<(), AppliedAssetError> {
        fs::create_dir_all(
            path.parent()
                .ok_or_else(|| fail("적용 파일 부모 경로 부재"))?,
        )
        .map_err(|e| fail(e.to_string()))?;
        write_bytes_atomic(path, bytes).map_err(|e| fail(e.to_string()))
    }
    /// Finishes `adopt`: relinks an unlinked job (its error, if any, takes priority over
    /// a prior write failure) and otherwise surfaces the write result.
    fn finish_adopt(
        &self,
        job: Job,
        job_name: &str,
        path: &Path,
        linked: bool,
        write: Result<(), AppliedAssetError>,
    ) -> Result<Job, AppliedAssetError> {
        if !linked {
            let relink = self
                .jobs
                .relink_template(
                    job_name,
                    &path.to_string_lossy(),
                    Some((&job.authority_id, &job.template_path)),
                )
                .map_err(|e| fail(e.to_string()));
            if let Err(error) = write {
                relink?;
                return Err(error);
            }
            return relink;
        }
        write?;
        Ok(job)
    }
    pub fn adopt(&self, job_name: &str, replace: bool) -> Result<Job, AppliedAssetError> {
        let job = self.jobs.load(job_name).map_err(|e| fail(e.to_string()))?;
        if job.authority_id.is_empty()
            || !self
                .works
                .exists(&job.authority_id)
                .map_err(|e| fail(e.detail))?
        {
            return Ok(job);
        }
        let path = self.path(&job.authority_id, &job.template_path)?;
        let linked = job.template_path == path.to_string_lossy();
        let exact = self.exact_or_relink(&job, job_name, &path, linked)?;
        let write = match classify_write_need(&path, linked, replace) {
            WriteNeed::MissingWhileLinked => Err(fail(format!(
                "적용된 템플릿 파일을 찾을 수 없습니다: {}",
                path.display()
            ))),
            WriteNeed::Write => {
                let bytes = self.exact_bytes(&exact)?;
                Self::write_template_bytes(&path, &bytes)
            }
            WriteNeed::NoneNeeded => Ok(()),
        };
        self.finish_adopt(job, job_name, &path, linked, write)
    }
}

/// What `adopt` must do about the app-owned applied template file, decided without
/// performing any I/O.
enum WriteNeed {
    /// The job is linked to its app-owned path but the file is missing there.
    MissingWhileLinked,
    /// The file needs to be (re)written, either because a replace was requested on an
    /// unlinked job or because the app-owned file does not exist yet.
    Write,
    /// The existing app-owned file already satisfies the request.
    NoneNeeded,
}

fn classify_write_need(path: &Path, linked: bool, replace: bool) -> WriteNeed {
    if linked && !path.is_file() {
        WriteNeed::MissingWhileLinked
    } else if (replace && !linked) || !path.is_file() {
        WriteNeed::Write
    } else {
        WriteNeed::NoneNeeded
    }
}
