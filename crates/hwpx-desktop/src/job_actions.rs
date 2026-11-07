//! Job-screen action routing. The mounted data and product services own all decisions.

use super::*;
use crate::slot_configuration_product::{SlotConfigurationProduct, SlotProductError};
use crate::template_change_coordinator::LOCAL_ACTOR;
use hwpx_core::text_extract::decimal_digit;
use hwpx_filler::text_render::{python_str, python_truthy};
use std::sync::Arc;

fn string<'a>(payload: &'a Value, key: &str) -> &'a str {
    payload.get(key).and_then(Value::as_str).unwrap_or("")
}
fn truth(value: Option<&Value>) -> bool {
    value.is_some_and(python_truthy)
}
fn coerced(payload: &Value, key: &str) -> String {
    payload.get(key).map_or_else(String::new, python_str)
}
fn python_index(value: &Value) -> Result<isize, JobControllerError> {
    match value {
        Value::Bool(value) => Ok(if *value { 1 } else { 0 }),
        Value::Number(number) => number
            .as_i64()
            .or_else(|| {
                number
                    .as_f64()
                    .filter(|n| n.is_finite())
                    .map(|n| n.trunc() as i64)
            })
            .and_then(|n| isize::try_from(n).ok())
            .ok_or_else(|| error("index 가 정수가 아닙니다.")),
        Value::String(raw) => {
            let raw = hwpx_filler::structure_scan::python_trim(raw);
            let (negative, digits) = if let Some(rest) = raw.strip_prefix('-') {
                (true, rest)
            } else {
                (false, raw.strip_prefix('+').unwrap_or(raw))
            };
            if digits.is_empty() {
                return Err(error("index 가 정수가 아닙니다."));
            }
            let mut number = 0isize;
            for ch in digits.chars() {
                let digit =
                    decimal_digit(ch).ok_or_else(|| error("index 가 정수가 아닙니다."))? as isize;
                number = number
                    .checked_mul(10)
                    .and_then(|n| n.checked_add(digit))
                    .ok_or_else(|| error("index 범위가 너무 큽니다."))?;
            }
            Ok(if negative { -number } else { number })
        }
        _ => Err(error("index 가 정수가 아닙니다.")),
    }
}
fn inline(result: Result<Value, impl ToString>) -> Value {
    result.unwrap_or_else(|error| json!({"ok":false,"error":error.to_string()}))
}
fn slot_error(error: SlotProductError) -> JobControllerError {
    JobControllerError {
        message: error.detail,
        code: error.code,
    }
}

impl JobController {
    fn slot_product(&self) -> SlotConfigurationProduct {
        let clock = Arc::clone(&self.clock);
        SlotConfigurationProduct::new(
            self.change.authority_root(),
            Arc::clone(&self.registry),
            move || clock().format("%Y-%m-%dT%H:%M:%S").to_string(),
        )
    }

    fn selected_work(&self) -> Result<String, JobControllerError> {
        Ok(self
            .state()?
            .seated
            .as_ref()
            .map_or_else(String::new, |seat| seat.job.name.clone()))
    }

    fn slot_mutation(
        &self,
        then_do: &str,
        action: &str,
        payload: &Value,
    ) -> Result<Value, JobControllerError> {
        let work = self.selected_work()?;
        self.generation
            .with_mutation(then_do, || -> Result<Value, JobControllerError> {
                let product = self.slot_product();
                let response = match action {
                    "select_slot_option" => product.select_slot_option(
                        &work,
                        string(payload, "configuration_token"),
                        string(payload, "slot_id"),
                        string(payload, "option_id"),
                        string(payload, "request_id"),
                    ),
                    "apply_selection_preset" => product.apply_selection_preset(
                        &work,
                        string(payload, "configuration_token"),
                        string(payload, "preset_key"),
                    ),
                    _ => unreachable!("only durable slot mutations"),
                }
                .map_err(slot_error)?;
                if response
                    .pointer("/mutation_outcome/changed")
                    .and_then(Value::as_bool)
                    == Some(true)
                    && self.selected_work()? == work
                {
                    self.resolve_execution()?;
                }
                Ok(response)
            })
            .map_err(error)?
    }

    /// Dispatches one screen action against the currently mounted generation/epoch.
    ///
    /// Every arm is a single call: job-level actions go to `act_*` methods and data-zone
    /// actions run through [`Self::on_data`], which holds the state lock and refuses stale
    /// zone edits before the `data_*` handler runs.
    pub fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, JobControllerError> {
        let _session = if action == "cancel_generation" {
            None
        } else {
            Some(self.session()?)
        };
        match action {
            "artifact_open" => self.act_artifact_open(payload),
            "artifact_close" => self.artifact_close(),
            "artifact_content" => self.artifact_content(),
            "recover_record_issue" => self.recover_record_issue(payload),
            "resolve_execution" => self.resolve_execution(),
            "refresh_observation" => self.act_refresh_observation(),
            "refresh" => self.refresh_jobs(),
            "open_workbench" => self.open_workbench(),
            "remount_data" => self.remount_data(truth(payload.get("confirm"))),
            "toggle_favorite" => {
                self.toggle_favorite(string(payload, "name"), truth(payload.get("value")))
            }
            "rename_job" => self.rename_job(string(payload, "name"), string(payload, "new")),
            "template_apply" => self.apply_template_change(string(payload, "change_token")),
            "relink_template" => self.relink_template(
                string(payload, "name"),
                string(payload, "path"),
                truth(payload.get("confirm")),
            ),
            "template_check" => self.act_template_check(payload),
            "open_slot_configuration" => self.act_open_slot_configuration(),
            "refresh_slot_configuration" => self.act_refresh_slot_configuration(payload),
            "select_slot_option" => self.slot_mutation("포함할 내용을 바꾸세요", action, payload),
            "apply_selection_preset" => self.slot_mutation("프리셋을 적용하세요", action, payload),
            "save_selection_preset" => self.act_save_selection_preset(payload),
            "load_pool" => self.act_load_pool(payload),
            "select_job" => self.act_select_job(payload),
            "prefer_work" => self.prefer_work(&coerced(payload, "name")),
            "browse_tab" => self.act_browse(Some(&coerced(payload, "tab")), None),
            "browse_query" => self.act_browse(None, Some(&coerced(payload, "text"))),
            "cancel_generation" => self.act_cancel_generation(),
            "select_failed" => self.act_select_failed(),
            "set_all" => self.on_data(action, payload, data_set_all),
            "set_none" => self.on_data(action, payload, data_set_none),
            "toggle_record" => self.on_data(action, payload, data_toggle_record),
            "select_range" => self.on_data(action, payload, data_select_range),
            "set_view_order" => self.on_data(action, payload, data_set_view_order),
            "range_draft_open" => self.on_data(action, payload, data_range_draft_open),
            "range_draft_apply" => self.on_data(action, payload, data_range_draft_apply),
            "range_draft_cancel" => self.on_data(action, payload, data_range_draft_cancel),
            "set_selected_only" => self.on_data(action, payload, data_set_selected_only),
            "filter_search" => self.on_data(action, payload, data_filter_search),
            "filter_col_text" => self.on_data(action, payload, data_filter_col_text),
            "filter_col_values" => self.on_data(action, payload, data_filter_col_values),
            "filter_col_range" => self.on_data(action, payload, data_filter_col_range),
            "filter_prune" => self.on_data(action, payload, data_filter_prune),
            "filter_clear" => self.on_data(action, payload, data_filter_clear),
            "filter_clear_col" => self.on_data(action, payload, data_filter_clear_col),
            "filter_panel" => self.on_data(action, payload, data_filter_panel),
            "count_filter_state" => self.on_data(action, payload, data_count_filter_state),
            "filter_reapply" => self.on_data(action, payload, data_filter_reapply),
            "create_filter_preset" => self.on_data(action, payload, data_create_filter_preset),
            "update_filter_preset" => self.on_data(action, payload, data_update_filter_preset),
            "toggle_filter_preset" => self.on_data(action, payload, data_toggle_filter_preset),
            "delete_filter_preset" => self.on_data(action, payload, data_delete_filter_preset),
            "hide_column" => self.on_data(action, payload, data_hide_column),
            "unhide_columns" => self.on_data(action, payload, data_unhide_columns),
            "dismiss_data_notice" => self.on_data(action, payload, data_dismiss_notice),
            "guard_state" => self.on_data(action, payload, data_guard_state),
            "list_filter_columns" => self.on_data(action, payload, data_list_filter_columns),
            _ => self.on_data(action, payload, |_, _, _| Err(unknown_action(action))),
        }
    }

    /// Runs one data-zone action under the state lock; a stale zone edit is answered with
    /// the current epoch before `handler` runs, exactly as for every data action.
    fn on_data(
        &self,
        action: &str,
        payload: &Value,
        handler: impl FnOnce(&Self, &mut MountedData, &Value) -> Result<Value, JobControllerError>,
    ) -> Result<Value, JobControllerError> {
        let mut state = self.state()?;
        let data = &mut state.data;
        if data.is_stale_edit(action, payload) {
            return Ok(json!({"stale":true,"epoch":data.zone_epoch}));
        }
        handler(self, data, payload)
    }

    fn act_artifact_open(&self, payload: &Value) -> Result<Value, JobControllerError> {
        let ordinal = python_index(
            payload
                .get("ordinal")
                .ok_or_else(|| error("ordinal 가 필요합니다."))?,
        )?;
        self.artifact_open(ordinal)
    }

    fn act_refresh_observation(&self) -> Result<Value, JobControllerError> {
        self.refresh_execution_observation()?;
        Ok(json!({"ok":true}))
    }

    fn act_template_check(&self, payload: &Value) -> Result<Value, JobControllerError> {
        let work = self.selected_work()?;
        if work.is_empty() {
            return Err(error("먼저 작업을 선택하세요"));
        }
        let (result, restored, application_id) = self
            .change
            .check_for_seated_context(&work, string(payload, "request_id"), LOCAL_ACTOR)
            .map_err(error)?;
        if result.get("reason").and_then(Value::as_str) == Some("work_context_changed") {
            self.select_job("")?;
            let mut result = result;
            result.as_object_mut().expect("check result object").insert(
                "error".into(),
                Value::String(
                    "문서 작업이 변경되어 선택을 해제했습니다. 문서 작업을 다시 선택하세요.".into(),
                ),
            );
            return Ok(result);
        }
        if result.get("ok").and_then(Value::as_bool) == Some(true) {
            self.adopt_checked_seat(&work, restored, application_id)?;
        }
        Ok(result)
    }

    /// After a successful template check, re-seats the still-selected work with the
    /// restored job and application id when the seat is not yet bound to both.
    fn adopt_checked_seat(
        &self,
        work: &str,
        restored: Option<Job>,
        application_id: Option<String>,
    ) -> Result<(), JobControllerError> {
        let mut state = self.state()?;
        if let Some(seat) = state.seated.as_mut()
            && seat.job.name == work
            && (seat.application_id.is_none() || seat.job.authority_id.is_empty())
        {
            if let Some(job) = restored {
                seat.job = job;
            }
            seat.application_id = application_id;
        }
        Ok(())
    }

    fn act_open_slot_configuration(&self) -> Result<Value, JobControllerError> {
        self.slot_product()
            .open_slot_configuration(&self.selected_work()?)
            .map_err(slot_error)
    }

    fn act_refresh_slot_configuration(&self, payload: &Value) -> Result<Value, JobControllerError> {
        self.slot_product()
            .refresh_slot_configuration(
                &self.selected_work()?,
                payload.get("configuration_token").and_then(Value::as_str),
            )
            .map_err(slot_error)
    }

    fn act_save_selection_preset(&self, payload: &Value) -> Result<Value, JobControllerError> {
        self.slot_product()
            .save_selection_preset(
                &self.selected_work()?,
                string(payload, "configuration_token"),
                string(payload, "name"),
                payload
                    .get("confirmed_overwrite_key")
                    .and_then(Value::as_str),
            )
            .map_err(slot_error)
    }

    fn act_load_pool(&self, payload: &Value) -> Result<Value, JobControllerError> {
        let key = string(payload, "key");
        let sheet = payload.get("sheet").and_then(Value::as_str);
        Ok(match self.load_pool(key, sheet) {
            Ok(()) => {
                json!({"ok":true,"label":format!("등록 데이터: {}",self.state()?.data.label)})
            }
            Err(failure) => json!({"ok":false,"error":failure.message}),
        })
    }

    fn act_select_job(&self, payload: &Value) -> Result<Value, JobControllerError> {
        self.select_job(string(payload, "name"))?;
        Ok(Value::Null)
    }

    fn act_browse(
        &self,
        tab: Option<&str>,
        query: Option<&str>,
    ) -> Result<Value, JobControllerError> {
        self.browse(tab, query)?;
        Ok(Value::Null)
    }

    fn act_cancel_generation(&self) -> Result<Value, JobControllerError> {
        self.generation.request_cancel();
        Ok(json!({"ok":true}))
    }

    fn act_select_failed(&self) -> Result<Value, JobControllerError> {
        let mut state = self.state()?;
        if state.data.range_draft.is_some() {
            return Err(error(
                "범위 편집기를 닫은 뒤에 실패분을 선택할 수 있습니다.",
            ));
        }
        let indices = state
            .last_failed
            .iter()
            .copied()
            .filter(|index| *index < state.data.records.len())
            .collect::<Vec<_>>();
        if !indices.is_empty() {
            state.data.selection.set_none();
            for index in &indices {
                state
                    .data
                    .selection
                    .toggle(*index as isize, Some(true))
                    .map_err(error)?;
            }
        }
        Ok(json!({"selected":indices.len()}))
    }
}

fn unknown_action(action: &str) -> JobControllerError {
    error(format!(
        "알 수 없는 작업 화면 액션: {}",
        hwpx_filler::text_render::python_repr(&Value::String(action.into()))
    ))
}

type DataResult = Result<Value, JobControllerError>;

fn data_set_all(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    Ok(json!({"added":data.set_all().map_err(error)?}))
}

fn data_set_none(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.set_none();
    Ok(Value::Null)
}

fn data_toggle_record(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    let index = python_index(
        payload
            .get("index")
            .ok_or_else(|| error("index 가 필요합니다."))?,
    )?;
    data.toggle(index, Some(truth(payload.get("value"))))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_select_range(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    let indices = payload
        .get("indices")
        .and_then(Value::as_array)
        .ok_or_else(|| error("indices 가 필요합니다."))?;
    let selected = truth(payload.get("value"));
    for value in indices {
        data.toggle(python_index(value)?, Some(selected))
            .map_err(error)?;
    }
    Ok(Value::Null)
}

fn data_set_view_order(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.set_view_order(&coerced(payload, "value"))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_range_draft_open(ctl: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    ctl.generation
        .raise_if_generating("범위를 편집하세요", false)
        .map_err(error)?;
    data.open_range_draft().map_err(error)?;
    Ok(json!({"ok":true,"epoch":data.zone_epoch}))
}

fn data_range_draft_apply(ctl: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    ctl.generation
        .raise_if_generating("적용하세요", false)
        .map_err(error)?;
    data.apply_range_draft().map_err(error)?;
    Ok(json!({"ok":true}))
}

fn data_range_draft_cancel(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.cancel_range_draft();
    Ok(json!({"ok":true}))
}

fn data_set_selected_only(
    _: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    data.set_selected_only(truth(payload.get("value")))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_search(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.set_filter_search(&coerced(payload, "text"))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_col_text(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.set_filter_text(string(payload, "column"), &coerced(payload, "text"))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_col_values(
    _: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    let values = payload
        .get("values")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .map(|item| match item {
                    Value::String(s) => s.clone(),
                    _ => hwpx_filler::text_render::python_repr(item),
                })
                .collect()
        });
    data.set_filter_values(string(payload, "column"), values)
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_col_range(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.set_filter_range(
        string(payload, "column"),
        payload.get("first"),
        payload.get("second"),
        payload.get("joiner").and_then(Value::as_str),
    )
    .map_err(error)
}

fn data_filter_prune(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.prune_filter(string(payload, "column"))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_clear(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.clear_filter().map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_clear_col(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.clear_filter_column(string(payload, "column"))
        .map_err(error)?;
    Ok(Value::Null)
}

fn data_filter_panel(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.filter_panel(string(payload, "column")).map_err(error)
}

fn data_count_filter_state(
    _: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    Ok(inline(data.count_filter_state(
        payload.get("state").unwrap_or(&Value::Null),
    )))
}

fn data_filter_reapply(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.reapply_filter().map_err(error)
}

fn data_create_filter_preset(
    ctl: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    Ok(inline(
        data.create_filter_preset(
            &ctl.pool,
            &coerced(payload, "name"),
            payload.get("state").unwrap_or(&Value::Null),
            truth(payload.get("from_adhoc")),
        )
        .map(|name| json!({"ok":true,"name":name})),
    ))
}

fn data_update_filter_preset(
    ctl: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    Ok(inline(
        data.update_filter_preset(
            &ctl.pool,
            &coerced(payload, "name"),
            &coerced(payload, "new_name"),
            payload.get("state").unwrap_or(&Value::Null),
        )
        .map(|name| json!({"ok":true,"name":name})),
    ))
}

fn data_toggle_filter_preset(
    _: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    Ok(inline(
        data.zone_filter_mut()
            .and_then(|filter| {
                filter
                    .toggle_preset(&coerced(payload, "name"))
                    .map_err(|error| crate::job_data_session::fail(error.message))
            })
            .map(|active| json!({"ok":true,"active":active})),
    ))
}

fn data_delete_filter_preset(
    ctl: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    Ok(inline(
        data.delete_filter_preset(&ctl.pool, &coerced(payload, "name"))
            .map(|()| json!({"ok":true})),
    ))
}

fn data_hide_column(_: &JobController, data: &mut MountedData, payload: &Value) -> DataResult {
    data.hide_column(string(payload, "column")).map_err(error)?;
    Ok(Value::Null)
}

fn data_unhide_columns(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.unhide_columns();
    Ok(Value::Null)
}

fn data_dismiss_notice(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.notice_text.clear();
    data.notice_level.clear();
    Ok(Value::Null)
}

fn data_guard_state(_: &JobController, data: &mut MountedData, _: &Value) -> DataResult {
    data.selection_guard(&Default::default(), None)
        .map_err(error)
}

fn data_list_filter_columns(
    _: &JobController,
    data: &mut MountedData,
    payload: &Value,
) -> DataResult {
    data.list_filter_columns(string(payload, "query"))
        .map_err(error)
}
