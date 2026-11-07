//! Trial rendering report: where each field value lands and which options drop out.

use super::{TxtAuthoringError, chars, fail, line_starts, utf16};
use crate::structure_scan::{PLACEMENT_OPTION, python_trim};
use crate::text_render::{iter_field_token_matches, python_str};
use crate::text_structure::{TextStructureScan, marker_lines, scan_text_structure, splitlines};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};

pub fn trial_document_values(
    names: &[String],
    values: &Map<String, Value>,
) -> (Map<String, Value>, Vec<String>) {
    let mut document = Map::new();
    let mut empty = Vec::new();
    for name in names {
        if document.contains_key(name) {
            continue;
        }
        let raw = values
            .get(name)
            .filter(|value| !value.is_null())
            .map_or_else(String::new, python_str);
        if python_trim(&raw).is_empty() {
            document.insert(
                name.clone(),
                json!(crate::job::MISSING_MARKER.replace("{field}", name)),
            );
            empty.push(name.clone());
        } else {
            document.insert(name.clone(), json!(raw));
        }
    }
    (document, empty)
}
fn require_trial_choices(
    scan: &TextStructureScan,
    selected: &Map<String, Value>,
) -> Result<(), TxtAuthoringError> {
    for slot in &scan.slots {
        let choice = selected.get(&slot.id).and_then(Value::as_str);
        if !slot.options.is_empty()
            && !slot
                .options
                .iter()
                .any(|option| Some(option.id.as_str()) == choice)
        {
            return Err(fail(format!(
                "'{}' 항목의 시험 선택을 지정하세요.",
                slot.id
            )));
        }
    }
    Ok(())
}
fn excluded_options(
    text: &str,
    scan: &TextStructureScan,
    selected: &Map<String, Value>,
    starts: &[usize],
) -> Result<Vec<Value>, TxtAuthoringError> {
    let mut excluded = Vec::new();
    for place in &scan.placements {
        let choice = selected.get(&place.slot_id).and_then(Value::as_str);
        if place.kind != PLACEMENT_OPTION || place.option_id.as_deref() == choice {
            continue;
        }
        let owner = scan
            .slots
            .iter()
            .find(|slot| slot.id == place.slot_id)
            .ok_or_else(|| fail("항목이 없습니다."))?;
        let label_of = |id: Option<&str>| {
            owner
                .options
                .iter()
                .find(|option| Some(option.id.as_str()) == id)
                .map(|option| {
                    option
                        .label
                        .as_deref()
                        .filter(|label| !label.is_empty())
                        .unwrap_or(&option.id)
                })
                .ok_or_else(|| fail("선택이 없습니다."))
        };
        let chosen_label = label_of(choice)?;
        let omitted_label = label_of(place.option_id.as_deref())?;
        excluded.push(json!({"slot_id":place.slot_id,"option_id":place.option_id,"selected_option_id":selected.get(&place.slot_id),
            "label":omitted_label,"reason":format!("현재 시험에서 '{chosen_label}'을 골라 '{omitted_label}'은 제외되었습니다."),
            "start":utf16(text,starts[place.begin_marker_line]),"end":utf16(text,starts[place.end_marker_line+1])}));
    }
    Ok(excluded)
}
pub fn trial(
    text: &str,
    values: &Map<String, Value>,
    selected: &Map<String, Value>,
    output: &str,
) -> Result<Value, TxtAuthoringError> {
    let scan = scan_text_structure(text);
    if !scan.diagnostics.is_empty() {
        return Err(fail("구조 오류를 수정한 뒤 결과를 시험하세요."));
    }
    require_trial_choices(&scan, selected)?;
    let chosen = selected
        .iter()
        .filter_map(|(key, value)| {
            value
                .as_str()
                .map(|choice| (key.clone(), HashSet::from([choice.to_owned()])))
        })
        .collect::<HashMap<_, _>>();
    let mut hidden = marker_lines(&scan);
    hidden.extend(crate::text_structure::unselected_option_lines(
        &scan, &chosen,
    ));
    let lines = splitlines(text);
    let starts = line_starts(text);
    let names = lines
        .iter()
        .enumerate()
        .filter(|(line, _)| !hidden.contains(line))
        .flat_map(|(_, line)| {
            iter_field_token_matches(line.whole)
                .into_iter()
                .map(|m| python_trim(m.body).to_owned())
        })
        .collect::<Vec<_>>();
    let (document, empty_fields) = trial_document_values(&names, values);
    let mut output_pos = 0;
    let mut occurrences = Vec::new();
    for (line, piece) in lines.iter().enumerate() {
        if hidden.contains(&line) {
            continue;
        }
        let mut cursor = 0;
        for found in iter_field_token_matches(piece.whole) {
            output_pos += piece.whole[cursor..found.start].encode_utf16().count();
            let name = python_trim(found.body);
            let value = document.get(name).and_then(Value::as_str).unwrap_or("");
            let source_start = starts[line] + chars(&piece.whole[..found.start]);
            let source_end = starts[line] + chars(&piece.whole[..found.end]);
            occurrences.push(json!({"name":name,"source_start":utf16(text,source_start),"source_end":utf16(text,source_end),
                "output_start":output_pos,"output_end":output_pos+value.encode_utf16().count(),"value":value}));
            output_pos += value.encode_utf16().count();
            cursor = found.end;
        }
        output_pos += piece.whole[cursor..].encode_utf16().count();
    }
    let excluded = excluded_options(text, &scan, selected, &starts)?;
    Ok(
        json!({"text":output,"report":{"missing_fields":[],"empty_fields":empty_fields},"occurrences":occurrences,"excluded":excluded}),
    )
}
