//! Compare-and-write binding for an imported Job whose data contract passed.

use crate::job_registry::{JobRegistry, StoreError};
use hwpx_filler::job::Job;
use std::fmt;

#[derive(Debug)]
pub enum ContractBindingError {
    Refused,
    Store(StoreError),
}
impl fmt::Display for ContractBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Refused => formatter.write_str("판정한 작업의 데이터 결속이 바뀌었습니다."),
            Self::Store(error) => write!(formatter, "{error}"),
        }
    }
}
impl std::error::Error for ContractBindingError {}
impl From<StoreError> for ContractBindingError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

/// The writer lease rereads the Job before writing; stale contract judgments never bind.
pub fn bind_contract_data(
    registry: &JobRegistry,
    judged: &Job,
    binding: (&str, &str, u64, &str),
) -> Result<Job, ContractBindingError> {
    if judged.data_contract.is_none() || binding.0.is_empty() {
        return Err(ContractBindingError::Refused);
    }
    let expected = registry.content_fingerprint(judged)?;
    let result = registry.transaction(|session| {
        let mut current = session.load(&judged.name)?;
        if current.has_data_binding()
            || current.data_contract != judged.data_contract
            || registry.content_fingerprint(&current)? != expected
        {
            return Ok(None);
        }
        current.data_path = binding.0.into();
        current.data_sheet = binding.1.into();
        current.data_header_row = binding.2;
        current.data_kind = binding.3.into();
        session.save(&mut current, false)?;
        Ok(Some(current))
    })?;
    result.ok_or(ContractBindingError::Refused)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::data_contract::DataContract;
    use std::fs;
    use std::path::Path;

    #[test]
    fn contract_binding_writes_once_and_refuses_a_stale_judgment() {
        let sandbox = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!(
                "hwpx-contract-binding-{}",
                uuid::Uuid::new_v4().simple()
            ));
        let templates = sandbox.join("templates");
        fs::create_dir_all(&templates).unwrap();
        let registry = JobRegistry::new(sandbox.join("jobs"), move || templates.clone()).unwrap();
        let mut job = Job {
            name: "Imported".into(),
            template_path: "C:/outside/template.hwpx".into(),
            data_contract: Some(DataContract { fields: vec![] }),
            ..Job::default()
        };
        registry.save(&mut job, false).unwrap();
        let judged = registry.load("Imported").unwrap();
        registry
            .mutate("Imported", |job| job.filename_pattern = "changed".into())
            .unwrap();
        let edited = fs::read(registry.path_for("Imported")).unwrap();
        assert!(matches!(
            bind_contract_data(&registry, &judged, ("C:/data.csv", "", 1, "")),
            Err(ContractBindingError::Refused)
        ));
        assert_eq!(fs::read(registry.path_for("Imported")).unwrap(), edited);
        let judged = registry.load("Imported").unwrap();
        let bound = bind_contract_data(&registry, &judged, ("C:/data.csv", "", 1, "")).unwrap();
        assert_eq!(bound.data_binding(), ("C:/data.csv", "", 1, ""));
        assert_eq!(bound.binding_revision, judged.binding_revision);
        let before = fs::read(registry.path_for("Imported")).unwrap();
        assert!(matches!(
            bind_contract_data(&registry, &judged, ("C:/other.csv", "", 1, "")),
            Err(ContractBindingError::Refused)
        ));
        assert_eq!(fs::read(registry.path_for("Imported")).unwrap(), before);
        assert_invalid_binding_preserves_job(&registry, &before);
        fs::remove_dir_all(sandbox).unwrap();
    }

    fn assert_invalid_binding_preserves_job(registry: &JobRegistry, before: &[u8]) {
        let mut judged = registry.load("Imported").unwrap();
        judged.data_contract = None;
        assert!(matches!(
            bind_contract_data(registry, &judged, ("C:/data.csv", "", 1, "")),
            Err(ContractBindingError::Refused)
        ));
        judged.data_contract = Some(DataContract { fields: vec![] });
        assert!(matches!(
            bind_contract_data(registry, &judged, ("", "", 1, "")),
            Err(ContractBindingError::Refused)
        ));
        assert_eq!(fs::read(registry.path_for("Imported")).unwrap(), before);
        registry
            .mutate("Imported", |job| {
                job.data_path.clear();
                job.data_contract = None;
            })
            .unwrap();
        let changed = fs::read(registry.path_for("Imported")).unwrap();
        assert!(matches!(
            bind_contract_data(registry, &judged, ("C:/data.csv", "", 1, "")),
            Err(ContractBindingError::Refused)
        ));
        assert_eq!(fs::read(registry.path_for("Imported")).unwrap(), changed);
        fs::write(registry.path_for("Imported"), b"broken job").unwrap();
        let error = bind_contract_data(registry, &judged, ("C:/data.csv", "", 1, "")).unwrap_err();
        assert!(matches!(error, ContractBindingError::Store(_)));
        assert!(!error.to_string().is_empty());
        assert_eq!(
            fs::read(registry.path_for("Imported")).unwrap(),
            b"broken job"
        );
    }
}
