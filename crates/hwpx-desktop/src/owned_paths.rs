//! Exact path allowlist for host copy, reveal, and open commands.

use crate::dataset_registry::DatasetPoolRegistry;
use crate::job_registry::JobRegistry;
use crate::workspace_switch::GraphError;
use std::collections::HashSet;
use std::path::{Component, Path, PathBuf};

fn normalized(path: &str, base_dir: &Path) -> Result<String, GraphError> {
    let input = Path::new(path);
    let absolute = std::path::absolute(if input.is_absolute() {
        input.to_path_buf()
    } else {
        base_dir.join(input)
    })?;
    let mut clean = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                clean.pop();
            }
            other => clean.push(other.as_os_str()),
        }
    }
    let text = clean.to_str().ok_or("경로가 Unicode가 아닙니다.")?;
    Ok(text.replace('/', "\\").to_lowercase())
}

pub fn collect_owned_paths(
    jobs: &JobRegistry,
    datasets: &DatasetPoolRegistry,
    session_paths: &[String],
    base_dir: &Path,
) -> Result<HashSet<String>, GraphError> {
    let mut owned = HashSet::new();
    for job in jobs.list_jobs_with_corruption()?.0 {
        if !job.template_path.is_empty() {
            owned.insert(normalized(&job.template_path, base_dir)?);
        }
    }
    for (_, item) in datasets.list_references(None)?.0 {
        for key in ["path", "db"] {
            if let Some(path) = item.opts.get(key).and_then(|value| value.as_str())
                && !path.is_empty()
            {
                owned.insert(normalized(path, base_dir)?);
            }
        }
    }
    for path in session_paths {
        if !path.is_empty() {
            owned.insert(normalized(path, base_dir)?);
        }
    }
    Ok(owned)
}

pub fn validate_owned_path<'a>(
    raw: &'a str,
    owned: &HashSet<String>,
    base_dir: &Path,
) -> Result<&'a str, GraphError> {
    if raw.is_empty() {
        return Err("경로가 비어 있습니다.".into());
    }
    if !owned.contains(&normalized(raw, base_dir)?) {
        return Err("이 경로는 앱이 추적하는 참조가 아니라 열 수 없습니다.".into());
    }
    Ok(raw)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{collect_owned_paths, normalized, validate_owned_path};
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::job_registry::JobRegistry;
    use hwpx_filler::dataset_reference::DatasetReference;
    use hwpx_filler::job::Job;
    use serde_json::json;
    use std::collections::HashSet;
    use std::fs;
    use std::path::Path;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn owned_path_is_exact_after_windows_lexical_normalization() {
        let base = Path::new("C:/Documents/Narumi");
        let owned = HashSet::from([normalized("Templates/Contract.hwpx", base).unwrap()]);
        assert_eq!(
            validate_owned_path("templates/../Templates/CONTRACT.hwpx", &owned, base).unwrap(),
            "templates/../Templates/CONTRACT.hwpx"
        );
        assert!(validate_owned_path("Templates/other.hwpx", &owned, base).is_err());
        assert!(validate_owned_path("", &owned, base).is_err());
    }

    #[test]
    fn collector_includes_job_and_pool_db_but_isolates_corruption() {
        let repo = fs::canonicalize(Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")).unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = repo.join(format!(".cache/owned-paths-{}-{stamp}", std::process::id()));
        fs::create_dir_all(root.join("templates")).unwrap();
        let template = root.join("templates/contract.txt");
        fs::write(&template, "{{name}}").unwrap();
        let template_root = root.join("templates");
        let jobs = JobRegistry::new(root.join("jobs"), move || template_root.clone()).unwrap();
        let mut job = Job {
            name: "Contract".into(),
            template_path: template.to_string_lossy().into_owned(),
            ..Job::default()
        };
        jobs.save(&mut job, false).unwrap();
        let datasets = DatasetPoolRegistry::new(root.join("datasets")).unwrap();
        let database = root.join("reference.db");
        let opts = json!({"db":database.to_string_lossy(),"view":"contracts"});
        let reference =
            DatasetReference::new("DB", "pclm", opts.as_object().unwrap().clone()).unwrap();
        datasets.add(&reference).unwrap();
        fs::write(root.join("datasets/broken.dataset.json"), b"{broken").unwrap();
        let session = vec![root.join("current.txt").to_string_lossy().into_owned()];
        let owned = collect_owned_paths(&jobs, &datasets, &session, &repo).unwrap();
        for path in [&template, &database, &root.join("current.txt")] {
            validate_owned_path(path.to_str().unwrap(), &owned, &repo).unwrap();
        }
        assert!(
            validate_owned_path(root.join("untracked.txt").to_str().unwrap(), &owned, &repo)
                .is_err()
        );
        assert!(root.starts_with(&repo));
        fs::remove_dir_all(&root).unwrap();
    }
}
