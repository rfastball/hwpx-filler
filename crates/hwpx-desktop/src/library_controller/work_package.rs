//! Work package inspect, export, and import actions.

use super::*;

impl LibraryController {
    pub(super) fn inspect_work_package(
        &self,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let path = payload
            .get("path")
            .and_then(Value::as_str)
            .filter(|path| !hwpx_filler::structure_scan::python_trim(path).is_empty())
            .ok_or("path 는 비어 있지 않은 파일 경로여야 한다")?;
        let installer = WorkPackageInstaller {
            jobs: &self.jobs,
            files: &self.template_files,
            presets: &self.presets,
            template_root: Box::new(|| self.template_files.root()),
        };
        Ok(match installer.inspect(Path::new(path)) {
            Ok((_, plan)) => json!({"ok":true,"basis":plan.basis,"view":plan_view(&plan)}),
            Err(error) => {
                json!({"ok":false,"error":format!("작업 꾸러미를 읽을 수 없습니다: {error}")})
            }
        })
    }
    pub(super) fn export_work_package(
        &self,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let path = payload
            .get("path")
            .and_then(Value::as_str)
            .filter(|path| !hwpx_filler::structure_scan::python_trim(path).is_empty())
            .ok_or("path 는 비어 있지 않은 파일 경로여야 한다")?;
        let result = (|| -> Result<Value, GraphError> {
            let jobs = package_jobs(&self.jobs, payload.get("names"))?;
            let sources = WorkPackageSources::new(&self.locations.template_authority())?;
            let now = Local::now().format("%Y-%m-%dT%H:%M:%S").to_string();
            let draft = match draft_work_package(&jobs, &sources, &now) {
                Ok(draft) => draft,
                Err(DraftError::NothingToExport { skipped }) => {
                    let mut error =
                        "작업 꾸러미를 만들 수 없습니다: 내보낼 수 있는 작업이 없습니다."
                            .to_owned();
                    if !skipped.is_empty() {
                        error.push_str(&format!(
                            "\n템플릿을 읽을 수 없는 작업은 빠집니다: {}",
                            skipped.join(", ")
                        ));
                    }
                    return Ok(json!({"ok":false,"error":error,"skipped":skipped}));
                }
                Err(error) => return Err(error.into()),
            };
            if (!draft.skipped.is_empty() || !draft.without_contract.is_empty())
                && !Self::truthy(payload.get("confirm"))
            {
                let mut lines = Vec::new();
                if !draft.skipped.is_empty() {
                    lines.push(format!(
                        "템플릿을 읽을 수 없는 작업은 빠집니다: {}",
                        draft.skipped.join(", ")
                    ));
                }
                if !draft.without_contract.is_empty() {
                    lines.push("데이터를 읽을 수 없어 확인 조건 없이 내보냅니다. 받는 쪽에서 연결을 직접 확정해야 합니다.".into());
                }
                return Ok(
                    json!({"ok":true,"needs_confirm":true,"confirm_text":lines.join("\n\n"),
                    "skipped":draft.skipped,"without_contract":draft.without_contract}),
                );
            }
            write_work_package(Path::new(path), &draft.manifest, &draft.templates)?;
            Ok(
                json!({"ok":true,"path":path,"jobs":draft.manifest.jobs.len(),
                "templates":draft.manifest.templates.len(),"skipped":draft.skipped,
                "without_contract":draft.without_contract}),
            )
        })();
        Ok(result.unwrap_or_else(|error| {
            json!({"ok":false,
            "error":format!("작업 꾸러미를 만들 수 없습니다: {error}")})
        }))
    }
    pub(super) fn import_work_package(
        &self,
        payload: &Map<String, Value>,
    ) -> Result<Value, GraphError> {
        let path = payload
            .get("path")
            .and_then(Value::as_str)
            .filter(|path| !hwpx_filler::structure_scan::python_trim(path).is_empty())
            .ok_or("path 는 비어 있지 않은 파일 경로여야 한다")?;
        let basis = payload
            .get("basis")
            .and_then(Value::as_str)
            .ok_or("basis 는 확인이 돌려준 문자열이어야 한다")?;
        let installer = WorkPackageInstaller {
            jobs: &self.jobs,
            files: &self.template_files,
            presets: &self.presets,
            template_root: Box::new(|| self.template_files.root()),
        };
        let plan = match installer.commit(Path::new(path), basis) {
            Ok(plan) => plan,
            Err(InstallError::Stale(plan)) => {
                return Ok(json!({"ok":false,"stale":true,
                "basis":plan.basis,"view":plan_view(&plan)}));
            }
            Err(error) => {
                return Ok(json!({"ok":false,
                "error":format!("작업 꾸러미를 읽을 수 없습니다: {error}")}));
            }
        };
        let names = plan
            .jobs
            .iter()
            .map(|item| item.final_name.clone())
            .collect::<Vec<_>>();
        let outcomes = bind_imported(&self.jobs, &self.datasets, &names);
        let bound = outcomes
            .iter()
            .filter(|item| item.status == "bound")
            .map(|item| item.name.clone())
            .collect::<Vec<_>>();
        let message = if bound.len() < outcomes.len() {
            "데이터 연결이 필요합니다."
        } else {
            ""
        };
        Ok(json!({"ok":true,"imported":names,"bound":bound,
            "outcomes":outcomes.iter().map(|item| json!({"name":item.name,"status":item.status})).collect::<Vec<_>>(),
            "message":message}))
    }
}

fn package_jobs(registry: &JobRegistry, names: Option<&Value>) -> Result<Vec<Job>, GraphError> {
    let Some(names) = names else {
        return Ok(registry.list_jobs_with_corruption()?.0);
    };
    let names = names
        .as_array()
        .ok_or("names 는 작업 이름 목록이어야 한다")?;
    let mut seen = HashSet::new();
    let mut jobs = Vec::new();
    for name in names {
        let name = name
            .as_str()
            .filter(|name| !name.is_empty())
            .ok_or("names 는 작업 이름 목록이어야 한다")?;
        if seen.insert(name) {
            jobs.push(registry.load(name)?);
        }
    }
    Ok(jobs)
}
