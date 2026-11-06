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
    pub fn dispatch(&self, action: &str, payload: &Value) -> Result<Value, JobControllerError> {
        let _session = if action == "cancel_generation" {
            None
        } else {
            Some(self.session()?)
        };
        match action {
            "artifact_open" => {
                let ordinal = python_index(
                    payload
                        .get("ordinal")
                        .ok_or_else(|| error("ordinal 가 필요합니다."))?,
                )?;
                return self.artifact_open(ordinal);
            }
            "artifact_close" => return self.artifact_close(),
            "artifact_content" => return self.artifact_content(),
            "recover_record_issue" => return self.recover_record_issue(payload),
            "resolve_execution" => return self.resolve_execution(),
            "refresh_observation" => {
                self.refresh_execution_observation()?;
                return Ok(json!({"ok":true}));
            }
            "refresh" => return self.refresh_jobs(),
            "open_workbench" => return self.open_workbench(),
            "remount_data" => return self.remount_data(truth(payload.get("confirm"))),
            "toggle_favorite" => {
                return self.toggle_favorite(string(payload, "name"), truth(payload.get("value")));
            }
            "rename_job" => {
                return self.rename_job(string(payload, "name"), string(payload, "new"));
            }
            "template_apply" => return self.apply_template_change(string(payload, "change_token")),
            "relink_template" => {
                return self.relink_template(
                    string(payload, "name"),
                    string(payload, "path"),
                    truth(payload.get("confirm")),
                );
            }
            "template_check" => {
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
                    result.as_object_mut().expect("check result object").insert("error".into(),
                        Value::String("문서 작업이 변경되어 선택을 해제했습니다. 문서 작업을 다시 선택하세요.".into()));
                    return Ok(result);
                }
                if result.get("ok").and_then(Value::as_bool) == Some(true) {
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
                }
                return Ok(result);
            }
            "open_slot_configuration" => {
                return self
                    .slot_product()
                    .open_slot_configuration(&self.selected_work()?)
                    .map_err(slot_error);
            }
            "refresh_slot_configuration" => {
                return self
                    .slot_product()
                    .refresh_slot_configuration(
                        &self.selected_work()?,
                        payload.get("configuration_token").and_then(Value::as_str),
                    )
                    .map_err(slot_error);
            }
            "select_slot_option" => {
                return self.slot_mutation("포함할 내용을 바꾸세요", action, payload);
            }
            "apply_selection_preset" => {
                return self.slot_mutation("프리셋을 적용하세요", action, payload);
            }
            "save_selection_preset" => {
                return self
                    .slot_product()
                    .save_selection_preset(
                        &self.selected_work()?,
                        string(payload, "configuration_token"),
                        string(payload, "name"),
                        payload
                            .get("confirmed_overwrite_key")
                            .and_then(Value::as_str),
                    )
                    .map_err(slot_error);
            }
            "load_pool" => {
                let key = string(payload, "key");
                let sheet = payload.get("sheet").and_then(Value::as_str);
                return Ok(match self.load_pool(key, sheet) {
                    Ok(()) => {
                        json!({"ok":true,"label":format!("등록 데이터: {}",self.state()?.data.label)})
                    }
                    Err(failure) => json!({"ok":false,"error":failure.message}),
                });
            }
            "select_job" => {
                self.select_job(string(payload, "name"))?;
                return Ok(Value::Null);
            }
            "prefer_work" => return self.prefer_work(&coerced(payload, "name")),
            "browse_tab" => {
                self.browse(Some(&coerced(payload, "tab")), None)?;
                return Ok(Value::Null);
            }
            "browse_query" => {
                self.browse(None, Some(&coerced(payload, "text")))?;
                return Ok(Value::Null);
            }
            _ => (),
        }
        if action == "cancel_generation" {
            self.generation.request_cancel();
            return Ok(json!({"ok":true}));
        }
        if action == "select_failed" {
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
            return Ok(json!({"selected":indices.len()}));
        }
        let mut state = self.state()?;
        let data = &mut state.data;
        if data.is_stale_edit(action, payload) {
            return Ok(json!({"stale":true,"epoch":data.zone_epoch}));
        }
        match action {
            "set_all" => Ok(json!({"added":data.set_all().map_err(error)?})),
            "set_none" => {
                data.set_none();
                Ok(Value::Null)
            }
            "toggle_record" => {
                let index = python_index(
                    payload
                        .get("index")
                        .ok_or_else(|| error("index 가 필요합니다."))?,
                )?;
                data.toggle(index, Some(truth(payload.get("value"))))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "select_range" => {
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
            "set_view_order" => {
                data.set_view_order(&coerced(payload, "value"))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "range_draft_open" | "range_draft_apply" => {
                let verb = if action == "range_draft_open" {
                    "범위를 편집하세요"
                } else {
                    "적용하세요"
                };
                self.generation
                    .raise_if_generating(verb, false)
                    .map_err(error)?;
                if action == "range_draft_open" {
                    data.open_range_draft().map_err(error)?;
                    Ok(json!({"ok":true,"epoch":data.zone_epoch}))
                } else {
                    data.apply_range_draft().map_err(error)?;
                    Ok(json!({"ok":true}))
                }
            }
            "range_draft_cancel" => {
                data.cancel_range_draft();
                Ok(json!({"ok":true}))
            }
            "set_selected_only" => {
                data.set_selected_only(truth(payload.get("value")))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "filter_search" => {
                data.set_filter_search(&coerced(payload, "text"))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "filter_col_text" => {
                data.set_filter_text(string(payload, "column"), &coerced(payload, "text"))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "filter_col_values" => {
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
            "filter_col_range" => data
                .set_filter_range(
                    string(payload, "column"),
                    payload.get("first"),
                    payload.get("second"),
                    payload.get("joiner").and_then(Value::as_str),
                )
                .map_err(error),
            "filter_prune" => {
                data.prune_filter(string(payload, "column"))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "filter_clear" => {
                data.clear_filter().map_err(error)?;
                Ok(Value::Null)
            }
            "filter_clear_col" => {
                data.clear_filter_column(string(payload, "column"))
                    .map_err(error)?;
                Ok(Value::Null)
            }
            "filter_panel" => data.filter_panel(string(payload, "column")).map_err(error),
            "count_filter_state" => Ok(inline(
                data.count_filter_state(payload.get("state").unwrap_or(&Value::Null)),
            )),
            "filter_reapply" => data.reapply_filter().map_err(error),
            "create_filter_preset" => Ok(inline(
                data.create_filter_preset(
                    &self.pool,
                    &coerced(payload, "name"),
                    payload.get("state").unwrap_or(&Value::Null),
                    truth(payload.get("from_adhoc")),
                )
                .map(|name| json!({"ok":true,"name":name})),
            )),
            "update_filter_preset" => Ok(inline(
                data.update_filter_preset(
                    &self.pool,
                    &coerced(payload, "name"),
                    &coerced(payload, "new_name"),
                    payload.get("state").unwrap_or(&Value::Null),
                )
                .map(|name| json!({"ok":true,"name":name})),
            )),
            "toggle_filter_preset" => Ok(inline(
                data.zone_filter_mut()
                    .and_then(|filter| {
                        filter
                            .toggle_preset(&coerced(payload, "name"))
                            .map_err(|error| crate::job_data_session::fail(error.message))
                    })
                    .map(|active| json!({"ok":true,"active":active})),
            )),
            "delete_filter_preset" => Ok(inline(
                data.delete_filter_preset(&self.pool, &coerced(payload, "name"))
                    .map(|()| json!({"ok":true})),
            )),
            "hide_column" => {
                data.hide_column(string(payload, "column")).map_err(error)?;
                Ok(Value::Null)
            }
            "unhide_columns" => {
                data.unhide_columns();
                Ok(Value::Null)
            }
            "dismiss_data_notice" => {
                data.notice_text.clear();
                data.notice_level.clear();
                Ok(Value::Null)
            }
            "guard_state" => data
                .selection_guard(&Default::default(), None)
                .map_err(error),
            "list_filter_columns" => data
                .list_filter_columns(string(payload, "query"))
                .map_err(error),
            _ => Err(error(format!(
                "알 수 없는 작업 화면 액션: {}",
                hwpx_filler::text_render::python_repr(&Value::String(action.into()))
            ))),
        }
    }
}
