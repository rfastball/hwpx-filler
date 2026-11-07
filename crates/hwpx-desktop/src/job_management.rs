//! Cross-screen Job commands: registry changes, remount, and TXT handoff.

use super::*;
use crate::job_registry::StoreError;
use crate::template_change_coordinator::LOCAL_ACTOR;
use hwpx_filler::job::rules_fingerprints;
use hwpx_filler::work_candidates::workbench_entry_gate;
use std::io;

fn confirmed_missing(result: Result<Job, StoreError>) -> bool {
    matches!(result, Err(StoreError::Io(failure)) if failure.kind() == io::ErrorKind::NotFound)
}

/// Prefixes the newly re-mounted data's label with its source kind, matching the
/// wording `remount_data` already showed the user per source.
fn remounted_data_label(mounted: &MountedData) -> String {
    match mounted.source_kind.as_str() {
        "file" => format!("파일: {}", mounted.label),
        "pool" => format!("등록 데이터: {}", mounted.label),
        "pclm" => format!("계약 목록: {}", mounted.label),
        _ => mounted.label.clone(),
    }
}

impl JobController {
    pub fn relink_template(
        &self,
        name: &str,
        path: &str,
        confirm: bool,
    ) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let mut result = crate::library_controller::LibraryController::relink_job_template(
            &self.registry,
            self.generation.is_active(),
            name,
            path,
            confirm,
        )
        .map_err(error)?;
        if result.get("relinked").and_then(Value::as_bool) == Some(true) {
            let active = self.selected_job_name()? == name;
            if active {
                self.select_job(name)?;
            }
            result.as_object_mut().expect("relink result object").insert("restated".into(),
                Value::String(if active {
                    "템플릿을 다시 연결했습니다. 작업을 다시 불러왔으니 데이터와 저장 폴더 선택을 확인하세요."
                } else { "템플릿을 다시 연결했습니다." }.into()));
        }
        Ok(result)
    }

    pub fn refresh_jobs(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let name = self.selected_job_name()?;
        if name.is_empty() {
            return Ok(Value::Null);
        }
        let (jobs, _) = match self.registry.list_jobs_with_corruption() {
            Ok(value) => value,
            Err(_) => {
                return Ok(json!({"notice":"문서 작업 목록을 읽지 못했습니다. 다시 시도하세요."}));
            }
        };
        if !jobs.iter().any(|job| job.name == name) {
            if !confirmed_missing(self.registry.load(&name)) {
                return Ok(json!({"notice":"문서 작업 목록을 읽지 못했습니다. 다시 시도하세요."}));
            }
            self.select_job("")?;
            return Ok(
                json!({"notice":format!("'{name}' 작업이 다른 화면에서 삭제되어 열어 둔 실행 세션을 닫았습니다.")}),
            );
        }
        let fresh = self.registry.load(&name).map_err(error)?;
        let mut state = self.state()?;
        if let Some(seat) = state.seated.as_mut()
            && seat.job.name == name
            && seat.job != fresh
        {
            let rules_changed = rules_fingerprints(&seat.job) != rules_fingerprints(&fresh);
            seat.job = fresh;
            if rules_changed {
                state.invalidate_results();
            }
        }
        Ok(Value::Null)
    }

    /// Re-mounts a `pclm` data source: rebinds it under the same mutation that clears
    /// the last-failed state and restores the active selection, then remembers it as
    /// the current data source and pushes a snapshot, in the same order as before.
    fn remount_pclm_data(&self, data: &MountedData) -> Result<(), JobControllerError> {
        let mounted = self
            .generation
            .with_mutation("데이터를 바꾸세요", || {
                let mut state = self.state()?;
                state
                    .data
                    .mount_binding(&self.pool, &data.path, &data.sheet, data.header_row, "pclm")
                    .map_err(error)?;
                state.last_failed.clear();
                self.restore_active_after_data_change(&mut state);
                Ok(())
            })
            .map_err(error)?;
        let result = mounted.and_then(|()| self.remember_current_data_source());
        let pushed = self.push_snapshot();
        result.and(pushed)
    }
    pub fn remount_data(&self, confirm: bool) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let data = self.data()?;
        if data.source_kind.is_empty() {
            return Ok(
                json!({"ok":false,"error":"다시 읽을 데이터가 없습니다. 데이터를 먼저 고르세요."}),
            );
        }
        let selected = data.selection.selected_count();
        if selected > 0 && !confirm {
            return Ok(json!({"ok":true,"needs_confirm":true,
                "confirm_text":format!("데이터를 다시 읽으면 지금 고른 {selected}건의 선택과 필터 초안이 초기화됩니다.")}));
        }
        let result = match data.source_kind.as_str() {
            "pool" => self.load_pool(&data.pool_key, Some(&data.sheet)),
            "file" => self.load_data_path(
                Path::new(&data.path),
                (!data.sheet.is_empty()).then_some(data.sheet.as_str()),
                usize::try_from(data.header_row).map_err(error)?,
            ),
            "pclm" => self.remount_pclm_data(&data),
            _ => Err(error("알 수 없는 데이터 소스 종류")),
        };
        match result {
            Ok(()) => {
                let mounted = self.data()?;
                Ok(json!({"ok":true,"label":remounted_data_label(&mounted)}))
            }
            Err(failure) => {
                Ok(json!({"ok":false,"error":format!("데이터를 다시 읽지 못했습니다. {failure}")}))
            }
        }
    }

    pub fn toggle_favorite(&self, name: &str, value: bool) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        match self.registry.set_favorite(name, value, None) {
            Ok(_) => Ok(json!({"ok":true})),
            Err(StoreError::Io(failure)) if failure.kind() == io::ErrorKind::NotFound => Ok(
                json!({"ok":false,"error":format!("'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {failure}")}),
            ),
            Err(StoreError::Invalid(failure)) => Ok(
                json!({"ok":false,"error":format!("'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {failure}")}),
            ),
            Err(failure) => Err(error(failure)),
        }
    }

    pub fn rename_job(&self, name: &str, new_name: &str) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let cleaned = hwpx_filler::structure_scan::python_trim(new_name);
        if let Err(failure) = self.registry.rename(name, cleaned) {
            return match failure {
                StoreError::Invalid(_) | StoreError::Collision(_) => {
                    Ok(json!({"ok":false,"error":failure.to_string()}))
                }
                other => Err(error(other)),
            };
        }
        let mut state = self.state()?;
        if let Some(seat) = state.seated.as_mut()
            && seat.job.name == name
        {
            seat.job.name = cleaned.to_owned();
            state.fresh_observation = None;
            state.orchestration = hwpx_filler::workbench_execution_status::NO_EVIDENCE.into();
            state.overwrite_pin = None;
        }
        if state.last_run_job == name {
            state.last_run_job = cleaned.to_owned();
        }
        Ok(json!({"ok":true}))
    }

    pub fn apply_template_change(&self, token: &str) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let work = self.selected_job_name()?;
        if work.is_empty() {
            return Err(error("먼저 작업을 선택하세요"));
        }
        let result = self
            .generation
            .with_mutation("템플릿 변경사항을 적용하세요", || {
                self.change
                    .apply_for_seated_context(&work, token, LOCAL_ACTOR)
                    .map_err(error)
            })
            .map_err(error)??;
        let (response, application_id) = result;
        if response.get("is_current").and_then(Value::as_bool) == Some(true) {
            if let Some(seat) = self.state()?.seated.as_mut()
                && seat.job.name == work
            {
                seat.application_id = Some(application_id);
            }
            self.state()?.fresh_observation = None;
            self.resolve_execution()?;
        } else if response.get("status").and_then(Value::as_str) == Some("applied_then_advanced") {
            self.select_job("")?;
        }
        Ok(response)
    }

    pub fn session_guard_for(&self, name: &str) -> Result<Option<Value>, JobControllerError> {
        let state = self.state()?;
        if name.is_empty()
            || state
                .seated
                .as_ref()
                .is_none_or(|seat| seat.job.name != name)
        {
            return Ok(None);
        }
        let guard = state
            .data
            .selection_guard(&state.last_generated.iter().copied().collect(), None)
            .map_err(error)?;
        if guard.get("armed").and_then(Value::as_bool) != Some(true) {
            return Ok(None);
        }
        let mut result = guard
            .as_object()
            .cloned()
            .ok_or_else(|| error("guard 형식 오류"))?;
        result.insert("screen".into(), Value::String("job".into()));
        Ok(Some(Value::Object(result)))
    }

    pub fn open_workbench(&self) -> Result<Value, JobControllerError> {
        let _session = self.session()?;
        let (name, data, media) = {
            let state = self.state()?;
            (
                state
                    .seated
                    .as_ref()
                    .map_or_else(String::new, |seat| seat.job.name.clone()),
                state.data.clone(),
                state.seated.as_ref().map_or("", |seat| seat.job.media()),
            )
        };
        if media != "txt" || name.is_empty() {
            return Ok(json!({"ok":false,"error":"TXT 검토·복사 작업이 아닙니다."}));
        }
        self.raise_if_generating_before_swap("작업대를 여세요")?;
        if data.range_draft.is_some() {
            return Ok(
                json!({"ok":false,"error":"범위 편집을 먼저 적용하거나 취소한 뒤 작업대를 여세요."}),
            );
        }
        let gate = workbench_entry_gate(
            !data.source_kind.is_empty(),
            data.selection.selected_count(),
            true,
        );
        if !gate.enabled {
            return Ok(json!({"ok":false,"error":gate.text}));
        }
        let open = self
            .workbench_open
            .as_ref()
            .ok_or_else(|| error("작업대 컨트롤러가 배선되지 않았습니다."))?;
        let job = match self.registry.load(&name) {
            Ok(job) => job,
            Err(failure) => {
                return Ok(
                    json!({"ok":false,"error":format!("작업 '{name}' 을(를) 읽을 수 없습니다: {failure}")}),
                );
            }
        };
        if job.media() != "txt" {
            return Ok(json!({"ok":false,"error":"TXT 검토·복사 작업이 아닙니다."}));
        }
        let indices = data.selected_indices();
        let rows = indices
            .iter()
            .map(|index| {
                (
                    *index,
                    data.records[*index]
                        .iter()
                        .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                        .collect::<Map<_, _>>(),
                )
            })
            .collect::<Vec<_>>();
        if let Err(failure) = open(job, rows) {
            return Ok(
                json!({"ok":false,"error":format!("템플릿을 읽을 수 없습니다: {failure}. 템플릿을 다시 연결한 뒤 진행하세요.")}),
            );
        }
        Ok(json!({"ok":true,"count":indices.len()}))
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{Job, StoreError, confirmed_missing};
    use std::io;

    #[test]
    fn only_confirmed_absence_can_close_the_selected_job() {
        assert!(!confirmed_missing(Ok(Job::default())));
        for kind in [
            io::ErrorKind::NotFound,
            io::ErrorKind::PermissionDenied,
            io::ErrorKind::InvalidData,
            io::ErrorKind::Other,
        ] {
            assert_eq!(
                confirmed_missing(Err(StoreError::Io(io::Error::new(kind, "read failed")))),
                kind == io::ErrorKind::NotFound
            );
        }
        assert!(!confirmed_missing(Err(StoreError::Codec(
            hwpx_filler::job::JobError("corrupt".into())
        ))));
    }
}
