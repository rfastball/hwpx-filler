//! Practice TXT observations; selections are interpreted against the active backend document.

use crate::onboarding_state::OnboardingState;
use crate::workspace_runtime::RuntimeResources;
use crate::workspace_switch::GraphError;
use hwpx_filler::txt_authoring::from_utf16;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

fn practice_path(state: &OnboardingState, resources: &RuntimeResources) -> String {
    let context = state.progress.context();
    if state.progress.selected.as_deref() == Some("change_apply") {
        let (Some(name), Some(home)) = (
            context
                .and_then(|ctx| ctx.get("job_name"))
                .and_then(Value::as_str),
            context
                .and_then(|ctx| ctx.get("home"))
                .and_then(Value::as_str),
        ) else {
            return String::new();
        };
        let Ok(job) = resources.jobs.load(name) else {
            return String::new();
        };
        let path = PathBuf::from(&job.template_path);
        let root = Path::new(home).join("template_authority").join("applied");
        return match (path.canonicalize(), root.canonicalize()) {
            (Ok(path), Ok(root)) if path.starts_with(&root) => job.template_path,
            _ => String::new(),
        };
    }
    context
        .and_then(|ctx| ctx.get("assets"))
        .and_then(|assets| assets.get("낙찰자 선정 및 계약체결 안내.txt"))
        .and_then(|entry| entry.get("path"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned()
}

fn session(
    state: &OnboardingState,
    resources: &RuntimeResources,
    screen: &str,
    result: &Value,
) -> Result<Option<Value>, GraphError> {
    if screen != "authoring" || !result.is_object() || result["ok"] == false {
        return Ok(None);
    }
    let facts = resources.authoring.active_facts()?;
    Ok(facts.filter(|facts| {
        facts["media"] == "txt" && facts["source_path"] == practice_path(state, resources)
    }))
}

pub fn practice_template_open(
    state: &OnboardingState,
    resources: &RuntimeResources,
) -> Result<bool, GraphError> {
    let path = practice_path(state, resources);
    let facts = resources.authoring.active_facts()?;
    Ok(facts.is_some_and(|facts| {
        facts["media"] == "txt" && facts["source_path"] == path && facts["save_path"] == path
    }))
}

fn byte_at(text: &str, scalar: usize) -> usize {
    text.char_indices()
        .nth(scalar)
        .map_or(text.len(), |(byte, _)| byte)
}

fn slice(text: &str, start: usize, end: usize) -> &str {
    &text[byte_at(text, start)..byte_at(text, end)]
}

fn scalar_at(text: &str, byte: usize) -> usize {
    text[..byte].chars().count()
}

fn paragraph(text: &str) -> Option<(usize, usize)> {
    let begin = text.find("\n3. ")? + 1;
    let finish = begin + text[begin..].find('\n')?;
    Some((scalar_at(text, begin), scalar_at(text, finish)))
}

fn item_target(text: &str) -> Option<(usize, usize)> {
    let (begin, finish) = paragraph(text)?;
    (slice(text, finish, finish + 3) == "\n\n\n").then_some((begin, finish + 2))
}

fn include_target(text: &str) -> Option<(usize, usize)> {
    let (begin, finish) = paragraph(text)?;
    let before = slice(text, 0, begin.saturating_sub(1));
    before
        .rsplit('\n')
        .next()?
        .starts_with("{{#항목 예산재배정 ")
        .then_some((begin, finish))
}

fn omit_target(text: &str) -> Option<(usize, usize)> {
    let close = "{{/선택}}\n";
    let blank_byte = text.find(close)? + close.len();
    text[blank_byte..].starts_with("\n{{/항목}}").then(|| {
        let at = scalar_at(text, blank_byte);
        (at, at)
    })
}

fn utf16_at(text: &str, scalar: usize) -> usize {
    text.chars().take(scalar).map(char::len_utf16).sum()
}

/// Paint a range only from the active practice TXT and its backend session identity.
pub fn guide_range(
    state: &OnboardingState,
    resources: &RuntimeResources,
    event: &str,
) -> Result<Option<Value>, GraphError> {
    let Some(facts) = resources.authoring.active_facts()? else {
        return Ok(None);
    };
    if facts["media"] != "txt" || facts["source_path"] != practice_path(state, resources) {
        return Ok(None);
    }
    let Some(text) = facts["content"].as_str() else {
        return Ok(None);
    };
    let target = match event {
        "field_range_selected" => text.find("10일").map(|at| {
            let start = scalar_at(text, at);
            (start, start + 3)
        }),
        "item_range_selected" => item_target(text),
        "include_range_selected" => include_target(text),
        "omit_range_selected" => omit_target(text),
        _ => None,
    };
    Ok(target.map(|(start, end)| {
        json!({"session_id":facts["active_id"],"start":utf16_at(text,start),"end":utf16_at(text,end)})
    }))
}

fn selected_text<'a>(facts: &'a Value, payload: &Value) -> Option<(&'a str, usize, usize)> {
    let text = facts["content"].as_str()?;
    let selection = payload.get("selection")?.as_object()?;
    let start = from_utf16(text, selection.get("start")).ok()?;
    let end = from_utf16(text, selection.get("end")).ok()?;
    (start <= end).then_some((text, start, end))
}

fn options(facts: &Value) -> std::collections::HashSet<&str> {
    facts["analysis"]["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|slot| slot["label"] == "예산재배정")
        .flat_map(|slot| slot["options"].as_array().into_iter().flatten())
        .filter_map(|option| option["label"].as_str())
        .collect()
}

fn trial_report<'a>(facts: &Value, action: &str, result: &'a Value) -> Option<&'a Value> {
    if action != "trial" {
        return None;
    }
    let report = result.get("report")?;
    if report["missing_fields"]
        .as_array()
        .is_some_and(|fields| !fields.is_empty())
        || report["errors"]
            .as_array()
            .is_some_and(|errors| !errors.is_empty())
        || facts["media"] != "txt"
    {
        return None;
    }
    Some(report)
}

fn tested(facts: &Value, labels: &[&str]) -> bool {
    let Some(slot) = facts["analysis"]["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|slot| slot["label"] == "예산재배정")
    else {
        return false;
    };
    labels.iter().all(|label| {
        let option = slot["options"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|option| option["label"] == *label);
        option.is_some_and(|option| {
            facts["trial_revision_coverage"]
                .as_array()
                .is_some_and(|rows| {
                    rows.iter()
                        .any(|row| row["slot_id"] == slot["id"] && row["option_id"] == option["id"])
                })
        })
    })
}

fn finish_result(state: &mut OnboardingState, title: &str, body: &str) {
    let mut result = json!({"screen":"authoring","target":"save-template","title":title,"body":body,"count":1,"documents":[]});
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

pub fn match_event(
    state: &mut OnboardingState,
    resources: &RuntimeResources,
    event: &str,
    screen: &str,
    action: &str,
    payload: &Value,
    result: &Value,
) -> Result<Option<Map<String, Value>>, GraphError> {
    let Some(facts) = session(state, resources, screen, result)? else {
        return Ok(None);
    };
    let selected = if matches!(action, "locate" | "commands") {
        selected_text(&facts, payload)
    } else {
        None
    };
    let matched = match event {
        "practice_template_opened" => {
            action == "open_authoring_document" && practice_template_open(state, resources)?
        }
        "field_range_selected" => {
            selected.is_some_and(|(text, start, end)| slice(text, start, end).trim() == "10일")
        }
        "item_range_selected" => selected.is_some_and(|(text, start, end)| {
            item_target(text).is_some_and(|(begin, finish)| {
                begin <= start
                    && finish <= end
                    && slice(text, begin, start).trim().is_empty()
                    && !slice(text, begin, start).contains('\n')
                    && slice(text, finish, end).trim().is_empty()
                    && !slice(text, finish, end).contains('\n')
            })
        }),
        "include_range_selected" => selected.is_some_and(|(text, start, end)| {
            include_target(text)
                .is_some_and(|(begin, finish)| begin <= start && start < end && end <= finish + 1)
        }),
        "omit_range_selected" => selected.is_some_and(|(text, start, end)| {
            omit_target(text)
                .is_some_and(|(begin, _)| start == begin && (end == begin || end == begin + 1))
        }),
        "practice_field_created" => {
            action == "update"
                && facts["analysis"]["fields"]
                    .as_array()
                    .is_some_and(|fields| fields.iter().any(|field| field["name"] == "재배정기한"))
                && facts["content"]
                    .as_str()
                    .is_some_and(|text| !text.contains("10일"))
        }
        "practice_item_created" => {
            action == "update"
                && facts["analysis"]["slots"]
                    .as_array()
                    .is_some_and(|slots| slots.iter().any(|slot| slot["label"] == "예산재배정"))
        }
        "option_created" => action == "update" && options(&facts).contains("안내포함"),
        "practice_options_created" => {
            action == "update"
                && ["안내포함", "안내생략"]
                    .iter()
                    .all(|label| options(&facts).contains(*label))
        }
        "field_trial_passed" => trial_report(&facts, action, result).is_some_and(|report| {
            report["empty_fields"]
                .as_array()
                .is_none_or(|empty| empty.is_empty())
                && facts["values"]["재배정기한"]
                    .as_str()
                    .is_some_and(|value| !value.is_empty())
        }),
        "trial_names_filled" => action == "trial_fill_names",
        "option_trial_passed" => {
            trial_report(&facts, action, result).is_some()
                && tested(&facts, &["안내포함"])
                && ["안내포함"]
                    .iter()
                    .all(|label| options(&facts).contains(*label))
        }
        "practice_both_trials_passed" => {
            trial_report(&facts, action, result).is_some()
                && tested(&facts, &["안내포함", "안내생략"])
                && ["안내포함", "안내생략"]
                    .iter()
                    .all(|label| options(&facts).contains(*label))
        }
        "field_practice_saved" | "option_practice_saved" => {
            let ready = matches!(action, "save" | "save_authoring_document")
                && result["ok"] == true
                && facts["readiness"]["state"] == "ready";
            if ready {
                let path = result["path"]
                    .as_str()
                    .ok_or("연습 저장 경로가 없습니다.")?;
                let digest = crate::tutorial_workspace::fingerprint(Path::new(path))?;
                let context = state.progress.context_mut().ok_or("과정을 고르세요.")?;
                let saved = context
                    .entry("saved_fingerprints")
                    .or_insert_with(|| json!({}));
                if !saved.is_object() {
                    *saved = json!({});
                }
                saved[path] = Value::String(digest);
                let (title, body) = if event == "field_practice_saved" {
                    (
                        "내 필드 준비 완료",
                        "재배정기한 필드를 시험하고 사용 준비 상태로 저장했습니다.",
                    )
                } else {
                    (
                        "항목과 선택 준비 완료",
                        "두 선택을 시험하고 서식을 저장했습니다.",
                    )
                };
                finish_result(state, title, body);
            }
            ready
        }
        "impact_tab_opened" => action == "impact",
        "prepare_apply_ready" => {
            action == "prepare_apply"
                && &payload["job_name"]
                    == state
                        .progress
                        .context()
                        .and_then(|ctx| ctx.get("job_name"))
                        .unwrap_or(&Value::Null)
                && result["change_token"]
                    .as_str()
                    .is_some_and(|token| !token.is_empty())
        }
        "option_change_applied" => {
            action == "apply_job"
                && &result["job_name"]
                    == state
                        .progress
                        .context()
                        .and_then(|ctx| ctx.get("job_name"))
                        .unwrap_or(&Value::Null)
                && result["is_current"] == true
        }
        _ => false,
    };
    if !matched {
        return Ok(None);
    }
    let mut context = Map::new();
    if event == "option_change_applied" {
        context.insert("applied".into(), Value::Bool(true));
    }
    Ok(Some(context))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{include_target, item_target, omit_target, scalar_at, tested, utf16_at};
    use serde_json::json;

    #[test]
    fn practice_ranges_and_trial_evidence_use_document_coordinates() {
        let text = "😀\n{{#항목 예산재배정 예산재배정}}\n3. 안내\n\n\n{{/항목}}";
        let item = item_target(text).unwrap();
        assert_eq!(utf16_at(text, item.0), item.0 + 1);
        assert_eq!(item.1, scalar_at(text, text.find("\n\n\n").unwrap()) + 2);
        assert!(include_target(text).is_some());
        let options = "{{/선택}}\n\n{{/항목}}";
        let omit = omit_target(options).unwrap();
        assert_eq!(omit.0, omit.1);
        let facts = json!({
            "analysis":{"slots":[{"id":"s","label":"예산재배정","options":[{"id":"o","label":"안내포함"}]}]},
            "trial_revision_coverage":[{"slot_id":"s","option_id":"o"}]
        });
        assert!(tested(&facts, &["안내포함"]));
        assert!(!tested(&facts, &["안내생략"]));
    }
}
