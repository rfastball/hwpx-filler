//! Backend facts that can complete the current tutorial beat after a product command returns.

use crate::job_data_session::MountedData;
use crate::onboarding_state::OnboardingState;
use crate::workspace_runtime::RuntimeResources;
use crate::workspace_switch::{GraphError, ScreenController};
use serde_json::{Map, Value};
use std::path::Path;

fn yes() -> Option<Map<String, Value>> {
    Some(Map::new())
}

fn asset(state: &OnboardingState, name: &str) -> String {
    state
        .progress
        .context()
        .and_then(|context| context.get("assets"))
        .and_then(|assets| assets.get(name))
        .and_then(|entry| entry.get("path"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned()
}

fn context_string<'a>(state: &'a OnboardingState, key: &str) -> &'a str {
    state
        .progress
        .context()
        .and_then(|context| context.get(key))
        .and_then(Value::as_str)
        .unwrap_or("")
}

fn row<'a>(editor: &'a Value, field: &str) -> Option<(usize, &'a Value)> {
    editor["rows"]
        .as_array()?
        .iter()
        .enumerate()
        .find(|(_, row)| row["template_field"] == field)
}

fn editor_inputs(state: &OnboardingState, editor: &Value) -> bool {
    match state.progress.selected.as_deref() {
        Some("first_hwpx") => {
            editor["template_path"] == asset(state, "물품 구매입찰 공고.hwpx")
                && editor["data_path"] == asset(state, "공고목록.xlsx")
                && editor["data_sheet"] == "공고"
        }
        Some("contract_txt") => {
            editor["template_path"] == asset(state, "낙찰자 선정 및 계약체결 안내.txt")
                && editor["data_path"] == asset(state, "공고목록.xlsx")
                && editor["data_sheet"] == "계약"
        }
        _ => {
            !context_string(state, "job_name").is_empty()
                && editor["editing_origin"] == context_string(state, "job_name")
        }
    }
}

fn row_matches(row: Option<&Value>, source: &str, kind: &str, fmt: Option<&str>) -> bool {
    row.is_some_and(|row| {
        row["confirmed"] == true
            && (source.is_empty() || row["source"] == source)
            && (kind.is_empty() || row["type"] == kind)
            && fmt.is_none_or(|fmt| row["fmt"] == fmt)
    })
}

fn filled_const(row: &Value) -> bool {
    row["type"] == "const" && filled_const_text(row)
}

/// Every mapping row the purchase-notice save lesson asks the learner to confirm.
fn notice_rows_complete(editor: &Value) -> bool {
    let confirmed = |name: &str, source: &str, kind: &str, fmt: Option<&str>| {
        row_matches(row(editor, name).map(|(_, row)| row), source, kind, fmt)
    };
    confirmed("낙찰자결정방법", "낙찰방법", "", None)
        && confirmed("담당자 전화번호", "담당자전화", "", None)
        && ["계약담당자", "계약담당 전화번호", "계약담당 팩스번호"]
            .iter()
            .all(|name| {
                confirmed(name, "", "const", None)
                    && row(editor, name).is_some_and(|(_, row)| filled_const_text(row))
            })
        && ["입찰개시일시", "입찰마감일시", "개찰일시", "등록마감일시"]
            .iter()
            .all(|name| confirmed(name, "", "date", Some("datetime")))
        && confirmed("게시일", "게시일시", "date", Some("ym"))
}

fn filled_const_text(row: &Value) -> bool {
    row["const"]
        .as_str()
        .is_some_and(|value| !value.trim().is_empty())
}

fn purchase_sliced(editor: &Value, inputs: bool) -> bool {
    inputs
        && row(editor, "군품명").is_some_and(|(_, row)| {
            row["source"] == "군품명" && !row["slice"].is_null() && row["preview"] == "드릴"
        })
}

fn purchase_slice_event(
    state: &OnboardingState,
    event: &str,
    action: &str,
    result: &Value,
    editor: &Value,
    inputs: bool,
) -> bool {
    let sliced = purchase_sliced(editor, inputs);
    match event {
        "purchase_slice_set" => action == "set_slice" && sliced,
        "purchase_slice_confirmed" => {
            action == "set_confirmed"
                && sliced
                && row(editor, "군품명").is_some_and(|(_, row)| row["confirmed"] == true)
        }
        _ => {
            action == "save"
                && result["ok"] == true
                && sliced
                && editor["template_path"] == asset(state, "계약방법 결정 및 구매추진 안내.txt")
        }
    }
}

/// The preview shows at least one date row and one amount row.
fn typed_rows(editor: &Value) -> bool {
    let rows = editor["rows"].as_array();
    rows.is_some_and(|rows| rows.iter().any(|row| row["type"] == "date"))
        && rows.is_some_and(|rows| rows.iter().any(|row| row["type"] == "amount"))
}

fn editor_event(
    state: &OnboardingState,
    event: &str,
    action: &str,
    payload: &Value,
    result: &Value,
    editor: &Value,
) -> Option<Map<String, Value>> {
    if result["ok"] == false {
        return None;
    }
    let beat = state.progress.beat()?;
    let field = beat.arg.as_str();
    let inputs = editor_inputs(state, editor);
    let target = row(editor, field);
    let selected_index = payload["index"].as_u64().map(|index| index as usize);
    let targeted = target.is_some_and(|(index, _)| selected_index == Some(index));
    let has_target = target.map(|(_, row)| row);
    let matched = match event {
        "new_job_opened" => {
            action == "new_session"
                && editor["template_path"] == ""
                && editor["editing_origin"] == ""
        }
        "template_selected" => {
            action == "use_library_template"
                && editor["template_path"] == asset(state, "물품 구매입찰 공고.hwpx")
        }
        "contract_template_selected" => {
            action == "use_library_template"
                && editor["template_path"] == asset(state, "낙찰자 선정 및 계약체결 안내.txt")
        }
        "notice_data_selected" => {
            matches!(
                action,
                "use_pool_data" | "load_data_sheet" | "use_library_template"
            ) && editor["template_path"] == asset(state, "물품 구매입찰 공고.hwpx")
                && editor["data_path"] == asset(state, "공고목록.xlsx")
                && editor["data_sheet"] == "공고"
        }
        "contract_inputs_selected" => {
            matches!(
                action,
                "use_pool_data" | "load_data_sheet" | "use_library_template"
            ) && editor["template_path"] == asset(state, "낙찰자 선정 및 계약체결 안내.txt")
                && editor["data_path"] == asset(state, "공고목록.xlsx")
                && editor["data_sheet"] == "계약"
        }
        "editor_section_binding" | "editor_section_filename" | "editor_section_template" => {
            action == "goto_section"
                && editor["section"] == payload["section"]
                && editor["section"]
                    == match event {
                        "editor_section_binding" => "binding",
                        "editor_section_filename" => "filename",
                        _ => "template",
                    }
                && inputs
        }
        "notice_row_confirmed" => {
            action == "set_confirmed"
                && inputs
                && row_matches(
                    row(editor, "낙찰자결정방법").map(|(_, row)| row),
                    "낙찰방법",
                    "",
                    None,
                )
        }
        "notice_mapping_confirmed" => {
            matches!(action, "set_confirmed" | "confirm_suggested")
                && inputs
                && row_matches(
                    row(editor, "낙찰자결정방법").map(|(_, row)| row),
                    "낙찰방법",
                    "",
                    None,
                )
                && row_matches(
                    row(editor, "담당자 전화번호").map(|(_, row)| row),
                    "담당자전화",
                    "",
                    None,
                )
        }
        "notice_constant_mode_set" => {
            action == "set_display"
                && inputs
                && targeted
                && has_target.is_some_and(|row| row["type"] == "const")
        }
        "notice_constant_value_set" => {
            action == "set_const" && inputs && targeted && has_target.is_some_and(filled_const)
        }
        "notice_constant_confirmed" => {
            action == "set_confirmed"
                && inputs
                && targeted
                && has_target.is_some_and(|row| filled_const(row) && row["confirmed"] == true)
        }
        "notice_date_source_set" => {
            action == "set_source"
                && inputs
                && row(editor, "게시일").is_some_and(|(_, row)| row["source"] == "게시일시")
        }
        "notice_date_format_set" => {
            action == "set_display"
                && inputs
                && row(editor, "게시일")
                    .is_some_and(|(_, row)| row["type"] == "date" && row["fmt"] == "ym")
        }
        "notice_date_confirmed" => {
            action == "set_confirmed"
                && inputs
                && row_matches(
                    row(editor, "게시일").map(|(_, row)| row),
                    "게시일시",
                    "date",
                    Some("ym"),
                )
        }
        "notice_datetime_set" => {
            action == "set_display"
                && inputs
                && targeted
                && has_target.is_some_and(|row| row["type"] == "date" && row["fmt"] == "datetime")
        }
        "notice_datetime_confirmed" => {
            action == "set_confirmed"
                && inputs
                && targeted
                && has_target.is_some_and(|row| {
                    row["type"] == "date" && row["fmt"] == "datetime" && row["confirmed"] == true
                })
        }
        "notice_pattern_set" => {
            action == "set_pattern"
                && inputs
                && editor["pattern"] == "구매입찰공고-{{입찰공고번호}}"
        }
        "notice_job_saved" => {
            action == "save"
                && result["ok"] == true
                && editor["template_path"] == asset(state, "물품 구매입찰 공고.hwpx")
                && editor["pattern"] == "구매입찰공고-{{입찰공고번호}}"
                && notice_rows_complete(editor)
        }
        "contract_source_chosen" => {
            action == "set_source"
                && inputs
                && row(editor, "대표계약업체").is_some_and(|(_, row)| row["source"] == "계약상대자")
        }
        "contract_mapping_set" => {
            action == "set_confirmed"
                && inputs
                && row_matches(
                    row(editor, "대표계약업체").map(|(_, row)| row),
                    "계약상대자",
                    "",
                    None,
                )
        }
        "contract_currency_set" => {
            action == "set_display"
                && inputs
                && row(editor, "계약보증금")
                    .is_some_and(|(_, row)| row["type"] == "amount" && row["fmt"] == "")
        }
        "contract_amount_confirmed" => {
            action == "set_confirmed"
                && inputs
                && row_matches(
                    row(editor, "계약보증금").map(|(_, row)| row),
                    "",
                    "amount",
                    None,
                )
        }
        "contract_job_saved" => {
            action == "save"
                && result["ok"] == true
                && editor["template_path"] == asset(state, "낙찰자 선정 및 계약체결 안내.txt")
                && row_matches(
                    row(editor, "대표계약업체").map(|(_, row)| row),
                    "계약상대자",
                    "",
                    None,
                )
                && row_matches(
                    row(editor, "계약보증금").map(|(_, row)| row),
                    "",
                    "amount",
                    Some(""),
                )
        }
        "slice_popover_opened" => action == "preview_slice" && inputs && targeted,
        "purchase_slice_set" | "purchase_slice_confirmed" | "purchase_job_saved" => {
            purchase_slice_event(state, event, action, result, editor, inputs)
        }
        "purchase_formats_checked" => action == "step_preview" && inputs && typed_rows(editor),
        "editor_job_opened" => action == "open_job_in_editor" && inputs,
        "data_browse_started" => action == "mapping_reset_stakes" && inputs,
        "data_file_picked" => {
            action == "pick_data_file"
                && inputs
                && result["needs_sheet"] == true
                && payload["path"] == context_string(state, "derived_data_path")
        }
        "derived_data_selected" => {
            matches!(action, "load_data_sheet" | "use_pool_data")
                && inputs
                && editor["data_path"] == context_string(state, "derived_data_path")
                && editor["data_sheet"] == context_string(state, "derived_sheet")
        }
        "resuggest_asked" => {
            action == "mapping_reset_stakes"
                && inputs
                && editor["section"] == "binding"
                && editor["data_path"] == context_string(state, "derived_data_path")
        }
        "rows_resuggested" => {
            action == "resuggest_all"
                && inputs
                && result["resuggested"].as_u64().is_some_and(|n| n > 0)
        }
        "rebind_rows_confirmed" => {
            action == "confirm_suggested"
                && inputs
                && editor["data_path"] == context_string(state, "derived_data_path")
                && editor["rows"].as_array().is_some_and(|rows| {
                    !rows.is_empty() && rows.iter().all(|row| row["confirmed"] == true)
                })
        }
        _ => false,
    };
    if !matched {
        return None;
    }
    let mut context = Map::new();
    if matches!(
        event,
        "notice_job_saved" | "contract_job_saved" | "purchase_job_saved"
    ) {
        context.insert("job_name".into(), editor["name"].clone());
    }
    Some(context)
}

fn chosen(job: &Value, slot_label: &str, option_label: &str) -> bool {
    job.pointer("/slot_configuration/current_view/projection/slots")
        .and_then(Value::as_array)
        .is_some_and(|slots| {
            slots.iter().any(|slot| {
                slot["display_text"] == slot_label
                    && slot["options"].as_array().is_some_and(|options| {
                        options.iter().any(|option| {
                            option["display_text"] == option_label
                                && option["selected"] == true
                                && option["effective"] == true
                        })
                    })
            })
        })
}

fn practice_bench(
    resources: &RuntimeResources,
    job_name: &str,
) -> Result<Option<Value>, GraphError> {
    let bench = resources.workbench.initial()?;
    Ok((bench["open"] == true && bench["job_name"] == job_name).then_some(bench))
}

fn generated_documents(resources: &RuntimeResources) -> Result<Vec<Value>, GraphError> {
    let mut documents = Vec::new();
    for ordinal in 0..3 {
        let Some(document) = resources.job.delivered_artifact(ordinal)? else {
            return Ok(Vec::new());
        };
        let name = document
            .absolute_path
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .unwrap_or_default();
        documents
            .push(serde_json::json!({"name":name,"path":document.absolute_path,"kind":"hwpx"}));
    }
    Ok(documents)
}

fn finish_result(
    state: &mut OnboardingState,
    title: &str,
    body: &str,
    screen: &str,
    target: &str,
    documents: &[Value],
    count: usize,
) {
    let mut result = serde_json::json!({"screen":screen,"target":target,"title":title,"body":body,"count":count,"documents":documents});
    if let Some(selected) = state.progress.selected.as_deref()
        && let Some(index) = crate::tutorial_lessons::LESSONS
            .iter()
            .position(|lesson| lesson.id == selected)
        && let Some(next) = crate::tutorial_lessons::LESSONS.get(index + 1)
    {
        result["next_scenario_id"] = Value::String(next.id.clone());
    }
    state.progress.result = Some(result);
}

fn derived_reopened(
    state: &mut OnboardingState,
    on_job: bool,
    action: &str,
    data: &MountedData,
) -> bool {
    let done = on_job
        && matches!(action, "select_job" | "prefer_work")
        && data.path == context_string(state, "derived_data_path")
        && data.sheet == context_string(state, "derived_sheet");
    if done {
        finish_result(
            state,
            "새 데이터 연결 완료",
            "저장한 작업을 다시 열어 새 파일과 시트를 확인했습니다.",
            "job",
            "data-label",
            &[],
            1,
        );
    }
    done
}

/// The active filter shows exactly the first three rows.
fn first_three_visible(data: &MountedData) -> bool {
    data.filter.as_ref().is_some_and(|filter| {
        filter.visible_indices(&data.records).is_ok_and(|indices| {
            indices
                .into_iter()
                .collect::<std::collections::HashSet<_>>()
                == [0, 1, 2].into_iter().collect()
        })
    })
}

/// Records the three generated documents when each carries its row's notice number.
fn record_generated(
    state: &mut OnboardingState,
    resources: &RuntimeResources,
    data: &MountedData,
) -> Result<bool, GraphError> {
    let documents = generated_documents(resources)?;
    let named = [0, 1, 2].iter().all(|index| {
        let id = data.records[*index]
            .get("입찰공고번호")
            .cloned()
            .unwrap_or_default();
        documents
            .iter()
            .any(|doc| doc["name"].as_str().is_some_and(|name| name.contains(&id)))
    });
    if named && documents.len() == 3 {
        state
            .progress
            .context_mut()
            .ok_or("튜토리얼 문맥이 없습니다.")?
            .insert("generated".into(), Value::Array(documents));
        return Ok(true);
    }
    Ok(false)
}

fn notice_result_opened(
    state: &mut OnboardingState,
    on_job: bool,
    action: &str,
    result: &Value,
    job: &Value,
) -> bool {
    let generated = state
        .progress
        .context()
        .and_then(|ctx| ctx.get("generated"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let artifact = &job["artifact_view"];
    let observed = on_job
        && action == "artifact_open"
        && *result == serde_json::json!({"ok":true})
        && artifact["status"] == "observed"
        && !generated.is_empty()
        && generated.iter().any(|doc| {
            Path::new(doc["path"].as_str().unwrap_or("")).file_name()
                == Path::new(artifact["filename"].as_str().unwrap_or("")).file_name()
        });
    if observed {
        finish_result(
            state,
            "생성한 문서 3건",
            "결과 문서의 내용을 확인했습니다.",
            "job",
            "results",
            &generated,
            generated.len(),
        );
    }
    observed
}

fn copied_rows(state: &OnboardingState) -> Option<&Vec<Value>> {
    state
        .progress
        .context()
        .and_then(|ctx| ctx.get("copied_rows"))
        .and_then(Value::as_array)
}

/// The workbench shows a source row the learner has not copied yet.
fn uncopied_source_row(state: &OnboardingState, bench: &Value) -> bool {
    let row = &bench["card"]["source_row"];
    !row.is_null() && !copied_rows(state).is_some_and(|rows| rows.contains(row))
}

/// Adds the last copied row to the lesson context; returns whether enough rows are copied.
fn record_copy(
    state: &mut OnboardingState,
    bench: &Value,
    event: &str,
) -> Result<bool, GraphError> {
    let row = bench["card"]["last_copy"]["row"].clone();
    let mut copied = copied_rows(state).cloned().unwrap_or_default();
    if !row.is_null() && !copied.contains(&row) {
        copied.push(row);
    }
    copied.sort_by_key(|row| row.as_u64().unwrap_or(usize::MAX as u64));
    state
        .progress
        .context_mut()
        .ok_or("튜토리얼 문맥이 없습니다.")?
        .insert("copied_rows".into(), Value::Array(copied.clone()));
    let enough = copied.len() >= if event == "contract_two_copied" { 2 } else { 1 };
    if enough && event != "first_row_copied" {
        finish_result(
            state,
            "TXT 복사 완료",
            &format!("서로 다른 {}개 행을 복사했습니다.", copied.len()),
            "workbench",
            "wb-copy",
            &[],
            copied.len(),
        );
    }
    Ok(enough)
}

fn finish_option_review(state: &mut OnboardingState, reviewed: bool) -> bool {
    if reviewed {
        finish_result(
            state,
            "변경 적용 결과",
            "고른 안내 문단의 채운 내용을 확인했습니다.",
            "workbench",
            "txt-review",
            &[],
            1,
        );
    }
    reviewed
}

fn job_event(
    state: &mut OnboardingState,
    resources: &RuntimeResources,
    event: &str,
    screen: &str,
    action: &str,
    payload: &Value,
    result: &Value,
) -> Result<Option<Map<String, Value>>, GraphError> {
    let job_name = context_string(state, "job_name").to_owned();
    let same_job = !job_name.is_empty() && resources.job.selected_job_name()? == job_name;
    let on_job = screen == "job" && same_job;
    let data = resources.job.data()?;
    let job = resources.job.snapshot()?;
    let rows = data.selected_indices();
    let selected = rows
        .iter()
        .copied()
        .collect::<std::collections::HashSet<_>>();
    let three = selected == [0, 1, 2].into_iter().collect();
    let slot_choice = if state.progress.selected.as_deref() == Some("change_apply") {
        ("예산재배정", "안내포함")
    } else {
        ("입찰참가자격", "소기업·소상공인")
    };
    let matched = match event {
        "library_job_selected" => {
            screen == "library"
                && action == "select_work"
                && !job_name.is_empty()
                && payload["name"] == job_name
        }
        "job_opened" => on_job && matches!(action, "select_job" | "prefer_work"),
        "derived_reopened" => derived_reopened(state, on_job, action, &data),
        "notice_first_filtered" => {
            on_job
                && action == "toggle_filter_preset"
                && payload["name"] == "소상공인"
                && result["active"] == true
                && first_three_visible(&data)
        }
        "notice_first_rows" => {
            on_job
                && matches!(
                    action,
                    "toggle_record" | "select_range" | "set_all" | "range_draft_apply"
                )
                && three
        }
        "rows_selected" => {
            on_job
                && action == "set_all"
                && !data.records.is_empty()
                && rows.len() == data.records.len()
        }
        "slot_option_chosen" => {
            on_job && action == "select_slot_option" && chosen(&job, slot_choice.0, slot_choice.1)
        }
        "notice_first_options" => {
            on_job
                && action == "select_slot_option"
                && chosen(&job, slot_choice.0, slot_choice.1)
                && chosen(&job, "낙찰자 결정방법", "고시 미만")
        }
        "notice_first_generated" => {
            let ready = on_job
                && action == "generate"
                && result["succeeded"] == 3
                && three
                && data.path == asset(state, "공고목록.xlsx")
                && data.sheet == "공고"
                && resources.jobs.load(&job_name)?.filename_pattern
                    == "구매입찰공고-{{입찰공고번호}}"
                && chosen(&job, slot_choice.0, slot_choice.1)
                && chosen(&job, "낙찰자 결정방법", "고시 미만");
            ready && record_generated(state, resources, &data)?
        }
        "notice_result_opened" => notice_result_opened(state, on_job, action, result, &job),
        "txt_workbench_opened" => {
            action == "open_workbench"
                && result["ok"] == true
                && practice_bench(resources, &job_name)?.is_some()
        }
        "blank_observed" => {
            action == "open_workbench"
                && practice_bench(resources, &job_name)?.is_some_and(|bench| {
                    bench["card"]["empty_fields"]
                        .as_array()
                        .is_some_and(|fields| fields.contains(&Value::String("계약보증금".into())))
                })
        }
        "contract_two_reviewed" => {
            matches!(action, "step" | "set_current")
                && practice_bench(resources, &job_name)?
                    .is_some_and(|bench| uncopied_source_row(state, &bench))
        }
        "first_row_copied" | "contract_two_copied" | "purchase_copied" => {
            let Some(bench) = practice_bench(resources, &job_name)? else {
                return Ok(None);
            };
            action == "copy_clipboard"
                && result["copied"] == true
                && record_copy(state, &bench, event)?
        }
        "option_result_reviewed" => {
            let reviewed = action == "open_workbench"
                && same_job
                && state.progress.context().and_then(|ctx| ctx.get("applied"))
                    == Some(&Value::Bool(true))
                && chosen(&job, "예산재배정", "안내포함")
                && practice_bench(resources, &job_name)?.is_some_and(|bench| {
                    bench["card"]["text"]
                        .as_str()
                        .is_some_and(|text| text.contains("예산 재배정 여부"))
                });
            finish_option_review(state, reviewed)
        }
        _ => false,
    };
    Ok(matched.then(yes).flatten())
}

pub fn match_event(
    state: &mut OnboardingState,
    resources: &RuntimeResources,
    event: &str,
    screen: &str,
    action: &str,
    payload: &Value,
    result: &Value,
) -> Result<Option<Map<String, Value>>, GraphError> {
    if matches!(
        event,
        "practice_template_opened"
            | "field_range_selected"
            | "item_range_selected"
            | "include_range_selected"
            | "omit_range_selected"
            | "practice_field_created"
            | "practice_item_created"
            | "option_created"
            | "practice_options_created"
            | "field_trial_passed"
            | "trial_names_filled"
            | "option_trial_passed"
            | "practice_both_trials_passed"
            | "field_practice_saved"
            | "option_practice_saved"
            | "impact_tab_opened"
            | "prepare_apply_ready"
            | "option_change_applied"
    ) {
        return crate::onboarding_match_authoring::match_event(
            state, resources, event, screen, action, payload, result,
        );
    }
    if screen == "editor" || (event == "data_file_picked" && action == "pick_data_file") {
        let editor = resources.editor.snapshot()?;
        return Ok(editor_event(state, event, action, payload, result, &editor));
    }
    job_event(state, resources, event, screen, action, payload, result)
}
