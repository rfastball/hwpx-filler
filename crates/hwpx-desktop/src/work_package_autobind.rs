//! Receiving-side data observations and guarded binding after package installation.

use crate::contract_data_binding::bind_contract_data;
use crate::dataset_registry::DatasetPoolRegistry;
use crate::job_registry::JobRegistry;
use hwpx_filler::data_factory::{binding_for_reference, source_for_binding};
use hwpx_filler::dataset_reference::{excel_identity, reference_for_sheet, reference_sheets};
use hwpx_filler::work_package_plan::{DataBinding, DataReading, choose_import_binding};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::path::Path;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AutobindOutcome {
    pub name: String,
    pub status: &'static str,
}

fn registered_bindings(pool: &DatasetPoolRegistry) -> Result<Vec<DataBinding>, String> {
    let mut found = Vec::new();
    let mut seen = HashSet::new();
    for (_, item) in pool
        .list_references(Some("active"))
        .map_err(|e| e.to_string())?
        .0
    {
        if item.kind != "excel" && item.kind != "pclm" {
            continue;
        }
        let sheets = reference_sheets(&item).map_err(|e| e.to_string())?;
        let sheets = if sheets.is_empty() {
            vec![None]
        } else {
            sheets.iter().map(|name| Some(name.as_str())).collect()
        };
        for sheet in sheets {
            let selected = reference_for_sheet(&item, sheet).map_err(|e| e.to_string())?;
            let (path, sheet, header_row, kind) = binding_for_reference(&selected);
            if path.is_empty() || !Path::new(&path).exists() {
                continue;
            }
            if seen.insert((
                kind.clone(),
                excel_identity(&path, Some(&sheet)),
                header_row,
            )) {
                found.push(DataBinding {
                    path,
                    sheet,
                    header_row,
                    kind,
                });
            }
        }
    }
    Ok(found)
}

fn read_binding(binding: DataBinding) -> DataReading {
    let opened = usize::try_from(binding.header_row).ok().and_then(|row| {
        source_for_binding(&binding.path, &binding.sheet, Some(row), &binding.kind).ok()
    });
    let mut reading = DataReading {
        binding,
        columns: None,
        records: Vec::new(),
    };
    if let Some(mut source) = opened
        && let Ok(records) = source.records()
        && let Ok(columns) = source.fields()
    {
        reading.columns = Some(columns);
        reading.records = records
            .into_iter()
            .map(|record| {
                record
                    .into_iter()
                    .map(|(key, value)| (key, Value::String(value)))
                    .collect::<Map<_, _>>()
            })
            .collect();
    }
    reading
}

fn bind_all(
    registry: &JobRegistry,
    pool: &DatasetPoolRegistry,
    names: &[String],
) -> Result<Vec<AutobindOutcome>, String> {
    let jobs = names
        .iter()
        .map(|name| registry.load(name).map_err(|e| e.to_string()))
        .collect::<Result<Vec<_>, _>>()?;
    if jobs.iter().all(|job| job.data_contract.is_none()) {
        return Ok(jobs
            .into_iter()
            .map(|job| AutobindOutcome {
                name: job.name,
                status: "no_contract",
            })
            .collect());
    }
    let readings = registered_bindings(pool)?
        .into_iter()
        .map(read_binding)
        .collect::<Vec<_>>();
    Ok(jobs
        .into_iter()
        .map(|job| {
            let (status, binding) = choose_import_binding(&job, &readings);
            let status = if let Some(binding) = binding {
                if bind_contract_data(
                    registry,
                    &job,
                    (
                        &binding.path,
                        &binding.sheet,
                        binding.header_row,
                        &binding.kind,
                    ),
                )
                .is_ok()
                {
                    "bound"
                } else {
                    "refused"
                }
            } else {
                status
            };
            AutobindOutcome {
                name: job.name,
                status,
            }
        })
        .collect())
}

/// Installation stays successful when a receiving-side observation or binding fails.
pub fn bind_imported(
    registry: &JobRegistry,
    pool: &DatasetPoolRegistry,
    names: &[String],
) -> Vec<AutobindOutcome> {
    bind_all(registry, pool, names).unwrap_or_else(|_| {
        names
            .iter()
            .cloned()
            .map(|name| AutobindOutcome {
                name,
                status: "refused",
            })
            .collect()
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{bind_imported, read_binding, registered_bindings};
    use crate::dataset_registry::DatasetPoolRegistry;
    use crate::job_registry::JobRegistry;
    use hwpx_filler::data_contract_check::profile_data_contract;
    use hwpx_filler::dataset_reference::DatasetReference;
    use hwpx_filler::job::Job;
    use hwpx_filler::mapping::{FieldMapping, MappingProfile};
    use serde_json::{Map, Value, json};
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn registered_data_binds_only_one_readable_source_with_matching_values() {
        let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = workspace.join(format!(
            ".cache/package-autobind-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        assert!(root.canonicalize().unwrap().starts_with(&workspace));
        let template = root.join("template.txt");
        fs::write(&template, "{{건명}}").unwrap();
        let data = root.join("data.csv");
        fs::write(&data, "열\n1000\n").unwrap();
        let jobs = JobRegistry::new(root.join("jobs"), {
            let root = root.clone();
            move || root.clone()
        })
        .unwrap();
        let pool = DatasetPoolRegistry::new(root.join("datasets")).unwrap();
        let mapping = MappingProfile::new(
            "",
            vec![FieldMapping::new("금액", "열", "amount", "", "", None).unwrap()],
            Map::new(),
        )
        .unwrap();
        let record = serde_json::from_value::<Map<String, Value>>(json!({"열":"1000"})).unwrap();
        let mut job = Job {
            name: "가져옴".into(),
            template_path: template.to_str().unwrap().into(),
            mapping,
            ..Job::default()
        };
        job.data_contract = Some(profile_data_contract(&job.mapping, &[record]).unwrap());
        jobs.save(&mut job, false).unwrap();
        let item = DatasetReference::new(
            "원본",
            "excel",
            serde_json::from_value(json!({"path":data,"sheet":"","header_row":1})).unwrap(),
        )
        .unwrap();
        let names = vec!["가져옴".into()];
        let before = fs::read(jobs.path_for("가져옴")).unwrap();
        assert_eq!(bind_imported(&jobs, &pool, &names)[0].status, "no_match");
        let first_key = pool.add(&item).unwrap();
        let other = root.join("other.csv");
        fs::write(&other, "열\n2000\n").unwrap();
        pool.add(
            &DatasetReference::new(
                "다른 원본",
                "excel",
                json!({"path":other,"sheet":"","header_row":1})
                    .as_object()
                    .unwrap()
                    .clone(),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(registered_bindings(&pool).unwrap().len(), 2);
        assert_eq!(bind_imported(&jobs, &pool, &names)[0].status, "ambiguous");
        fs::write(&other, "열\n미정\n").unwrap();
        pool.delete(&first_key).unwrap();
        assert_eq!(bind_imported(&jobs, &pool, &names)[0].status, "no_match");
        pool.add(&item).unwrap();
        let broken = root.join("broken.xlsx");
        fs::write(&broken, b"not a workbook").unwrap();
        let broken_key = pool
            .add(
                &DatasetReference::new(
                    "읽을 수 없음",
                    "excel",
                    json!({"path":broken,"sheet":"","header_row":1})
                        .as_object()
                        .unwrap()
                        .clone(),
                )
                .unwrap(),
            )
            .unwrap();
        assert_eq!(bind_imported(&jobs, &pool, &names)[0].status, "unreadable");
        assert_eq!(fs::read(jobs.path_for("가져옴")).unwrap(), before);
        pool.delete(&broken_key).unwrap();
        assert_eq!(bind_imported(&jobs, &pool, &names)[0].status, "bound");
        let bound = jobs.load("가져옴").unwrap();
        assert_eq!(bound.data_binding(), (data.to_str().unwrap(), "", 1, ""));
        assert_eq!(
            (
                bound.template_revision,
                bound.binding_revision,
                &bound.reviewed_rules
            ),
            (
                job.template_revision,
                job.binding_revision,
                &job.reviewed_rules
            )
        );
        assert_eq!(bind_imported(&jobs, &pool, &names)[0].status, "refused");
        assert_eq!(jobs.load("가져옴").unwrap(), bound);
        assert_eq!(
            bind_imported(&jobs, &pool, &["missing".into()])[0].status,
            "refused"
        );
        assert_unreadable_registry_preserves_jobs(&root, &jobs);
        assert_registered_sheet_candidates(&root);
        let root = root.canonicalize().unwrap();
        assert!(root.starts_with(&workspace));
        fs::remove_dir_all(root).unwrap();
    }

    fn assert_unreadable_registry_preserves_jobs(root: &std::path::Path, jobs: &JobRegistry) {
        let location = root.join("unreadable-pool");
        fs::write(&location, b"not a directory").unwrap();
        let pool = DatasetPoolRegistry::new(location).unwrap();
        assert!(registered_bindings(&pool).is_err());
        let before = fs::read(jobs.path_for("가져옴")).unwrap();
        assert_eq!(
            bind_imported(jobs, &pool, &["가져옴".into()])[0].status,
            "refused"
        );
        assert_eq!(fs::read(jobs.path_for("가져옴")).unwrap(), before);
        let mut plain = Job {
            name: "일반".into(),
            ..Job::default()
        };
        jobs.save(&mut plain, false).unwrap();
        assert_eq!(
            bind_imported(jobs, &pool, &["일반".into()])[0].status,
            "no_contract"
        );
        assert!(jobs.load("일반").unwrap().data_path.is_empty());
        let binding = hwpx_filler::work_package_plan::DataBinding {
            path: root.join("missing.csv").to_str().unwrap().into(),
            sheet: String::new(),
            header_row: 0,
            kind: String::new(),
        };
        let unknown = read_binding(binding.clone());
        assert_eq!(unknown.binding, binding);
        assert!(unknown.columns.is_none() && unknown.records.is_empty());
    }

    fn assert_registered_sheet_candidates(root: &std::path::Path) {
        let pool = DatasetPoolRegistry::new(root.join("sheet-pool")).unwrap();
        let book = root.join("sheets.xlsx");
        fs::write(&book, b"").unwrap();
        let register = |name: &str, kind: &str, opts: Value| {
            pool.add(&DatasetReference::new(name, kind, opts.as_object().unwrap().clone()).unwrap())
                .unwrap()
        };
        register(
            "책",
            "excel",
            json!({"path":book,"sheet":"가","sheets":["가","나"]}),
        );
        let duplicate = DatasetReference::new(
            "같은 책",
            "excel",
            json!({"path":book,"sheet":"나"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
        assert!(pool.add(&duplicate).is_err());
        fs::write(
            pool.slot_path("legacy-duplicate").unwrap(),
            serde_json::to_vec(&duplicate.to_dict()).unwrap(),
        )
        .unwrap();
        let broken = register("깨진 선언", "excel", json!({"path":book,"sheet":"다"}));
        let path = pool.slot_path(&broken).unwrap();
        let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        value["opts"]["sheets"] = json!(["가"]);
        fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        register(
            "없는 파일",
            "excel",
            json!({"path":root.join("absent.csv")}),
        );
        let archived = register("보관", "excel", json!({"path":book,"sheet":"보관"}));
        pool.commands().archive(&archived).unwrap();
        register("나라", "nara", json!({}));
        let mut found = registered_bindings(&pool)
            .unwrap()
            .into_iter()
            .map(|binding| {
                assert_eq!(binding.path, book.to_str().unwrap());
                assert_eq!(binding.header_row, 0);
                assert!(binding.kind.is_empty());
                binding.sheet
            })
            .collect::<Vec<_>>();
        found.sort();
        assert_eq!(found, ["가", "나"]);
    }
}
