//! Structure analysis and marker repair suggestions for TXT authoring.

use super::{chars, eol, fields, line_starts, part, utf16};
use crate::fields::python_whitespace;
use crate::structure_scan::{
    CONTEXT_MAX, StructureDiagnostic, StructureDiagnosticKind, iter_structure_markers, python_trim,
};
use crate::text_structure::{
    TextStructureScan, scan_text_structure, scan_text_token_spans, splitlines,
};
use serde_json::{Value, json};

fn marker_target(context: &str) -> Option<String> {
    let marker = iter_structure_markers(context).into_iter().next()?;
    let tokens = marker
        .body
        .split(python_whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    (tokens.len() > 1 && tokens[0].starts_with('#')).then(|| tokens[1].into())
}

type RepairEdit = (usize, usize, String, &'static str);

fn closing_marker_removal(text: &str, item: &StructureDiagnostic) -> Option<RepairEdit> {
    let starts = line_starts(text);
    let lines = splitlines(text);
    let marker = if item.message.contains("선택") {
        "{{/선택}}"
    } else {
        "{{/항목}}"
    };
    let hits = lines
        .iter()
        .enumerate()
        .filter(|(_, line)| python_trim(line.content) == marker)
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    if hits.len() != 1 {
        return None;
    }
    let at = hits[0];
    Some((
        starts[at],
        starts[at + 1],
        String::new(),
        "짝이 없는 닫는 마커 제거",
    ))
}

fn opening_marker_append(text: &str, item: &StructureDiagnostic) -> Option<RepairEdit> {
    let marker = if item.context.starts_with("{{#선택 ") {
        "{{/선택}}"
    } else if item.context.starts_with("{{#항목 ") {
        "{{/항목}}"
    } else {
        return None;
    };
    let at = chars(text);
    let prefix = if text.is_empty() || text.ends_with(['\n', '\r']) {
        ""
    } else {
        eol(text)
    };
    Some((
        at,
        at,
        format!("{prefix}{marker}{}", eol(text)),
        "파일 끝에 닫는 마커 추가",
    ))
}

pub(super) fn repair_suggestion(
    text: &str,
    scan: &TextStructureScan,
    item: &StructureDiagnostic,
) -> Option<Value> {
    if scan.diagnostics.len() != 1 || item.kind != StructureDiagnosticKind::UnbalancedMarker {
        return None;
    }
    let (start, end, replacement, label) =
        if item.message.contains("여는") && item.message.contains("없이 닫는") {
            closing_marker_removal(text, item)?
        } else if item.message.contains("열린 채") {
            opening_marker_append(text, item)?
        } else {
            return None;
        };
    let candidate = format!(
        "{}{}{}",
        part(text, 0, start),
        replacement,
        part(text, end, chars(text))
    );
    if !scan_text_structure(&candidate).diagnostics.is_empty() {
        return None;
    }
    Some(
        json!({"label":label,"command":{"type":"repair_marker","start":utf16(text,start),"end":utf16(text,end),"text":replacement,"diagnostic":item.to_dict()}}),
    )
}

fn diagnostic_entry(text: &str, scan: &TextStructureScan, item: &StructureDiagnostic) -> Value {
    let lines = splitlines(text);
    let starts = line_starts(text);
    let hits = lines
        .iter()
        .enumerate()
        .filter(|(_, line)| {
            let content = python_trim(line.content);
            part(content, 0, chars(content).min(CONTEXT_MAX)) == item.context
        })
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    let location = if item.context.is_empty() || hits.len() != 1 {
        Value::Null
    } else {
        let line = hits[0];
        json!({"line":line,"start":utf16(text,starts[line]),"end":utf16(text,starts[line+1])})
    };
    let suggestion = repair_suggestion(text, scan, item);
    let mut actions = vec![json!({"label":"원문으로 이동","kind":"navigate","location":location})];
    if let Some(suggestion) = &suggestion {
        actions.push(
            json!({"label":suggestion["label"],"kind":"command","command":suggestion["command"]}),
        );
    }
    let mut result = item.to_dict();
    result["severity"] = json!("error");
    result["category"] = json!("structure");
    result["target"] = json!(marker_target(&item.context));
    result["location"] = location;
    result["actions"] = json!(actions);
    if let Some(suggestion) = suggestion {
        result["suggestion"] = suggestion;
    }
    result
}

pub fn analyze(text: &str) -> Value {
    let scan = scan_text_structure(text);
    let starts = line_starts(text);
    let placements = scan
        .placements
        .iter()
        .map(|place| {
            let mut row = place.to_dict();
            row["start"] = json!(utf16(text, starts[place.begin_marker_line]));
            row["end"] = json!(utf16(text, starts[place.end_marker_line + 1]));
            row["content_start_offset"] = json!(utf16(text, starts[place.content_start]));
            row["content_end_offset"] = json!(utf16(text, starts[place.content_end + 1]));
            row
        })
        .collect::<Vec<_>>();
    let mut slots = scan.to_dict()["slots"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    for slot in &mut slots {
        slot["kind"] = json!("slot");
        slot["location"] = placements
            .iter()
            .find(|row| row["kind"] == "slot" && row["slot_id"] == slot["id"])
            .cloned()
            .unwrap_or(Value::Null);
        let slot_id = slot["id"].clone();
        if let Some(options) = slot["options"].as_array_mut() {
            for option in options {
                option["kind"] = json!("option");
                option["slot_id"] = slot_id.clone();
                option["location"] = placements
                    .iter()
                    .find(|row| {
                        row["kind"] == "option"
                            && row["slot_id"] == slot_id
                            && row["option_id"] == option["id"]
                    })
                    .cloned()
                    .unwrap_or(Value::Null);
            }
        }
    }
    json!({"fields":fields(text,&scan),"slots":slots,"placements":placements,
        "spans":scan_text_token_spans(text,Some(&scan)).iter().map(|span|{
            let mut row=span.to_dict();row["start"]=json!(utf16(text,span.start));row["end"]=json!(utf16(text,span.end));row
        }).collect::<Vec<_>>(),
        "diagnostics":scan.diagnostics.iter().map(|item|diagnostic_entry(text,&scan,item)).collect::<Vec<_>>(),
        "summary":scan.summary.to_dict()})
}
