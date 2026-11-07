//! Pure TXT authoring over the existing structure and token grammars.

use crate::fields::python_whitespace;
use crate::structure_scan::{
    CONTEXT_MAX, PLACEMENT_OPTION, PLACEMENT_SLOT, StructureDiagnostic, StructureDiagnosticKind,
    iter_structure_markers, python_trim,
};
use crate::template_authoring::{command_label, field_candidates, whole_field_unset};
use crate::text_render::{iter_field_token_matches, python_str, python_truthy};
use crate::text_structure::{
    TextStructurePlacement, TextStructureScan, marker_lines, scan_text_structure,
    scan_text_token_spans, splitlines,
};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::sync::LazyLock;

const INVALID_SELECTION: &str = "고른 위치가 올바르지 않습니다.";
const FIELD_OVERLAP: &str = "고른 범위에 기존 필드가 포함되어 있습니다.";
const REGION_OVERLAP: &str = "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요.";
const STRUCTURE_FIRST: &str = "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요.";
const NO_CONTENT_LINE: &str = "고를 내용 줄이 없습니다.";
const NO_FILLED_VALUE: &str = "되돌릴 필드 값이 없습니다.";
const FIX_STALE: &str =
    "이 문제의 자동 수정이 더는 적용되지 않습니다. 문제 목록을 다시 확인하세요.";

#[derive(Clone, Debug, PartialEq)]
pub struct TxtAuthoringError {
    pub message: String,
    pub refusal: Option<Value>,
}
impl fmt::Display for TxtAuthoringError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for TxtAuthoringError {}
fn fail(message: impl Into<String>) -> TxtAuthoringError {
    TxtAuthoringError {
        message: message.into(),
        refusal: None,
    }
}
fn invalid_name(field: &str, message: &str) -> TxtAuthoringError {
    TxtAuthoringError {
        message: message.into(),
        refusal: Some(json!({"code":"invalid_name","field":field,"message":message})),
    }
}
fn conflict(name: &str, existing_count: usize) -> TxtAuthoringError {
    let message =
        format!("‘{name}’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요.");
    TxtAuthoringError {
        refusal: Some(
            json!({"code":"name_conflict","name":name,"existing_count":existing_count,"message":message}),
        ),
        message,
    }
}
fn chars(text: &str) -> usize {
    text.chars().count()
}
fn byte_at(text: &str, index: usize) -> usize {
    text.char_indices()
        .nth(index)
        .map_or(text.len(), |(at, _)| at)
}
fn part(text: &str, start: usize, end: usize) -> &str {
    &text[byte_at(text, start)..byte_at(text, end)]
}
fn utf16(text: &str, at: usize) -> usize {
    part(text, 0, at).encode_utf16().count()
}
pub fn from_utf16(text: &str, value: Option<&Value>) -> Result<usize, TxtAuthoringError> {
    let Some(at) = value.and_then(Value::as_u64) else {
        return Err(fail(INVALID_SELECTION));
    };
    let mut units = 0usize;
    for (index, ch) in text.chars().enumerate() {
        if units == at as usize {
            return Ok(index);
        }
        units += ch.len_utf16();
        if units > at as usize {
            return Err(fail("고른 위치가 문자 중간에 있습니다."));
        }
    }
    if units == at as usize {
        Ok(chars(text))
    } else {
        Err(fail("고른 위치가 문서 밖에 있습니다."))
    }
}
fn line_starts(text: &str) -> Vec<usize> {
    let mut starts = vec![0];
    starts.extend(
        splitlines(text)
            .iter()
            .map(|line| line.start_char + chars(line.whole)),
    );
    starts
}
fn line_at(starts: &[usize], at: usize) -> usize {
    starts
        .partition_point(|start| *start <= at)
        .saturating_sub(1)
        .min(starts.len().saturating_sub(2))
}
fn line_range(
    text: &str,
    start: usize,
    end: usize,
) -> Result<(usize, usize, usize, usize), TxtAuthoringError> {
    let starts = line_starts(text);
    if starts.len() == 1 {
        return Err(fail(NO_CONTENT_LINE));
    }
    let first = line_at(&starts, start);
    let last = line_at(&starts, end.saturating_sub(1).max(start));
    Ok((first, last, starts[first], starts[last + 1]))
}
fn eol(text: &str) -> &'static str {
    if text.contains("\r\n") { "\r\n" } else { "\n" }
}
fn command(value: &Value) -> Result<&Map<String, Value>, TxtAuthoringError> {
    value
        .as_object()
        .ok_or_else(|| fail("저작 명령이 사전이 아닙니다."))
}
fn action(command: &Map<String, Value>) -> &str {
    command.get("type").and_then(Value::as_str).unwrap_or("")
}
fn string<'a>(command: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    command.get(key).and_then(Value::as_str)
}
fn normalized_field(raw: Option<&Value>) -> Result<String, TxtAuthoringError> {
    let name = raw
        .and_then(Value::as_str)
        .and_then(crate::fields::normalize_field_id)
        .unwrap_or_default();
    if name.is_empty()
        || name.contains("{{")
        || name.contains("}}")
        || name.contains('|')
        || name.starts_with(['#', '/'])
    {
        return Err(invalid_name(
            "name",
            "필드 이름을 확인하세요. 비어 있거나 문법 기호가 포함되어 있습니다.",
        ));
    }
    Ok(name)
}
fn value_string(raw: Option<&Value>) -> String {
    raw.map_or_else(|| "None".into(), python_str)
}
fn marker_id(raw: Option<&Value>, renaming: bool) -> Result<String, TxtAuthoringError> {
    let message = if renaming {
        "항목이나 선택의 새 식별자를 입력하세요."
    } else {
        "항목이나 선택의 식별자를 입력하세요."
    };
    let Some(value) = raw
        .and_then(Value::as_str)
        .filter(|value| !python_trim(value).is_empty())
    else {
        return Err(invalid_name("identifier", message));
    };
    crate::hwpx_structure::marker_identifier(value).map_err(|error| {
        let message = error.to_string();
        let message = if message.starts_with("구간 표기로 되쓸 수 없는 id 입니다:") {
            let ident = crate::fields::normalize_field_id(value).unwrap_or_default();
            format!(
                "구간 표기로 되쓸 수 없는 id 입니다: {}",
                hwpx_core::structural_boundary::python_string_repr(&ident)
            )
        } else {
            message
        };
        invalid_name("identifier", &message)
    })
}
fn marker_label(raw: Option<&Value>) -> Result<String, TxtAuthoringError> {
    let value = raw.and_then(Value::as_str);
    crate::hwpx_structure::marker_label(value).map_err(|error| {
        let message = error.to_string();
        let message = if message.starts_with("구간 표기로 되쓸 수 없는 label 입니다:")
        {
            format!(
                "구간 표기로 되쓸 수 없는 label 입니다: {}",
                hwpx_core::structural_boundary::python_string_repr(value.unwrap_or(""))
            )
        } else {
            message
        };
        invalid_name("name", &message)
    })
}
fn marker_text(kind: &str, id: &str, label: Option<&Value>) -> Result<String, TxtAuthoringError> {
    let label = label.and_then(Value::as_str);
    crate::hwpx_structure::begin_marker_text(kind, id, label)
        .map_err(|error| fail(error.to_string()))
}
fn end_marker(kind: &str) -> Result<String, TxtAuthoringError> {
    crate::hwpx_structure::end_marker_text(kind).map_err(|error| fail(error.to_string()))
}

#[derive(Clone)]
struct FieldSite {
    start: usize,
    end: usize,
    name: String,
    source: String,
}
fn field_sites(text: &str) -> Vec<FieldSite> {
    iter_field_token_matches(text)
        .into_iter()
        .map(|m| FieldSite {
            start: chars(&text[..m.start]),
            end: chars(&text[..m.end]),
            name: python_trim(m.body).into(),
            source: m.source.into(),
        })
        .collect()
}
fn collapse_whitespace(text: &str) -> String {
    let mut out = String::new();
    let mut pending = false;
    for ch in text.chars() {
        if python_whitespace(ch) {
            pending = true;
        } else {
            if pending {
                out.push(' ');
                pending = false;
            }
            out.push(ch);
        }
    }
    if pending {
        out.push(' ');
    }
    out
}
fn context_parts(before: &str, focus: &str, after: &str, span: usize) -> (String, String, String) {
    let before = collapse_whitespace(before);
    let after = collapse_whitespace(after);
    let lead = format!(
        "{}{}",
        if chars(&before) > span { "…" } else { "" },
        part(&before, chars(&before).saturating_sub(span), chars(&before))
    );
    let trail = format!(
        "{}{}",
        part(&after, 0, span.min(chars(&after))),
        if chars(&after) > span { "…" } else { "" }
    );
    (lead, focus.into(), trail)
}
fn humanize(text: &str) -> String {
    let mut out = String::new();
    let mut at = 0;
    for m in iter_field_token_matches(text) {
        out.push_str(&text[at..m.start]);
        out.push('[');
        out.push_str(python_trim(m.body));
        out.push(']');
        at = m.end;
    }
    out.push_str(&text[at..]);
    out
}
fn occurrence_context(before: &str, focus: &str, after: &str) -> String {
    let (a, b, c) = context_parts(before, focus, after, 12);
    format!("{a}{b}{c}")
}
fn occurrences(text: &str, scan: &TextStructureScan) -> Vec<Value> {
    let starts = line_starts(text);
    let lines = splitlines(text);
    field_sites(text).into_iter().map(|site| {
        let line=line_at(&starts,site.start);
        let owner=scan.placements.iter().rev().find(|place|place.begin_marker_line<line && line<place.end_marker_line);
        let raw=lines.get(line).map_or("",|line|line.content);
        let column=site.start-starts[line];
        let before=part(raw,0,column.min(chars(raw)));
        let after=part(raw,(column+chars(&site.source)).min(chars(raw)),chars(raw));
        json!({"name":site.name,"start":utf16(text,site.start),"end":utf16(text,site.end),"line":line,
            "slot_id":owner.map(|item|item.slot_id.as_str()),"option_id":owner.and_then(|item|item.option_id.as_deref()),
            "context":occurrence_context(&humanize(before),&format!("[{}]",site.name),&humanize(after)),
            "raw":{"text":part(raw,0,chars(raw).min(CONTEXT_MAX))}})
    }).collect()
}
fn fields(text: &str, scan: &TextStructureScan) -> Vec<Value> {
    let mut names = Vec::<String>::new();
    let mut groups = Vec::<Vec<Value>>::new();
    for item in occurrences(text, scan) {
        let name = item["name"].as_str().unwrap_or("").to_owned();
        if let Some(index) = names.iter().position(|known| known == &name) {
            groups[index].push(item);
        } else {
            names.push(name);
            groups.push(vec![item]);
        }
    }
    names
        .into_iter()
        .zip(groups)
        .map(|(name, items)| json!({"name":name,"count":items.len(),"occurrences":items}))
        .collect()
}

fn marker_target(context: &str) -> Option<String> {
    let marker = iter_structure_markers(context).into_iter().next()?;
    let tokens = marker
        .body
        .split(python_whitespace)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    (tokens.len() > 1 && tokens[0].starts_with('#')).then(|| tokens[1].into())
}
fn repair_suggestion(
    text: &str,
    scan: &TextStructureScan,
    item: &StructureDiagnostic,
) -> Option<Value> {
    if scan.diagnostics.len() != 1 || item.kind != StructureDiagnosticKind::UnbalancedMarker {
        return None;
    }
    let starts = line_starts(text);
    let lines = splitlines(text);
    let (start, end, replacement, label) =
        if item.message.contains("여는") && item.message.contains("없이 닫는") {
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
            (
                starts[at],
                starts[at + 1],
                String::new(),
                "짝이 없는 닫는 마커 제거",
            )
        } else if item.message.contains("열린 채") {
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
            (
                at,
                at,
                format!("{prefix}{marker}{}", eol(text)),
                "파일 끝에 닫는 마커 추가",
            )
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

#[derive(Clone)]
struct Edit {
    start: usize,
    end: usize,
    text: String,
}
#[derive(Clone)]
struct EditPlan {
    edits: Vec<Edit>,
    expanded: bool,
    cascade: bool,
}
fn plan(edits: Vec<Edit>, expanded: bool, cascade: bool) -> EditPlan {
    EditPlan {
        edits,
        expanded,
        cascade,
    }
}
fn edit(start: usize, end: usize, text: impl Into<String>) -> Edit {
    Edit {
        start,
        end,
        text: text.into(),
    }
}
fn apply_edits(text: &str, edits: &[Edit]) -> String {
    let mut result = text.to_owned();
    let mut sorted = edits.to_vec();
    sorted.sort_by_key(|item| (item.start, item.end));
    for item in sorted.into_iter().rev() {
        result.replace_range(
            byte_at(&result, item.start)..byte_at(&result, item.end),
            &item.text,
        );
    }
    result
}
fn selected_offsets(
    text: &str,
    command: &Map<String, Value>,
) -> Result<(usize, usize), TxtAuthoringError> {
    let default = json!(0);
    let start = from_utf16(text, command.get("start").or(Some(&default)))?;
    let end = from_utf16(
        text,
        command
            .get("end")
            .or(command.get("start"))
            .or(Some(&default)),
    )?;
    if start > end {
        Err(fail("고른 범위의 시작과 끝이 뒤바뀌었습니다."))
    } else {
        Ok((start, end))
    }
}
fn target<'a>(
    scan: &'a TextStructureScan,
    command: &Map<String, Value>,
) -> Option<&'a TextStructurePlacement> {
    let kind = command
        .get("kind")
        .map_or_else(|| "slot".into(), python_str);
    let slot = command.get("slot_id").map_or_else(String::new, python_str);
    let option = if kind == "option" {
        Some(
            command
                .get("option_id")
                .map_or_else(String::new, python_str),
        )
    } else {
        None
    };
    scan.placements
        .iter()
        .find(|place| place.kind == kind && place.slot_id == slot && place.option_id == option)
}
fn field_spans(
    text: &str,
    command: &Map<String, Value>,
    start: usize,
    end: usize,
) -> Result<Vec<(usize, usize)>, TxtAuthoringError> {
    let Some(raw) = command.get("ranges") else {
        return Ok(vec![(start, end)]);
    };
    if raw.is_null() {
        return Ok(vec![(start, end)]);
    }
    let ranges = raw.as_array().ok_or_else(|| fail(INVALID_SELECTION))?;
    let mut spans = Vec::new();
    for row in ranges {
        let row = row.as_object().ok_or_else(|| fail(INVALID_SELECTION))?;
        spans.push((
            from_utf16(text, row.get("start"))?,
            from_utf16(text, row.get("end"))?,
        ));
    }
    spans.sort();
    if !spans.contains(&(start, end))
        || spans
            .iter()
            .any(|(lo, hi)| lo > hi || part(text, *lo, *hi) != part(text, start, end))
    {
        return Err(fail(INVALID_SELECTION));
    }
    if spans
        .windows(2)
        .any(|window| window[0].1 > window[1].0 || window[0] == window[1])
    {
        return Err(fail(FIELD_OVERLAP));
    }
    Ok(spans)
}
fn field_edits(
    text: &str,
    command: &Map<String, Value>,
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let sites = field_sites(text);
    match action(command) {
        "create_field" => {
            let name = normalized_field(command.get("name"))?;
            let spans = field_spans(text, command, start, end)?;
            if spans
                .iter()
                .any(|(lo, hi)| sites.iter().any(|site| site.start < *hi && *lo < site.end))
            {
                return Err(fail(FIELD_OVERLAP));
            }
            Ok(plan(
                spans
                    .into_iter()
                    .map(|(lo, hi)| edit(lo, hi, format!("{{{{{name}}}}}")))
                    .collect(),
                false,
                false,
            ))
        }
        "rename_field" => {
            let old = normalized_field(command.get("old_name"))?;
            let new = normalized_field(command.get("name"))?;
            let existing = sites
                .iter()
                .filter(|site| site.name == old)
                .collect::<Vec<_>>();
            if existing.is_empty() {
                return Err(fail("필드를 찾을 수 없습니다."));
            }
            if old == new {
                return Ok(plan(Vec::new(), false, false));
            }
            let taken = sites.iter().filter(|site| site.name == new).count();
            if taken > 0 {
                return Err(conflict(&new, taken));
            }
            Ok(plan(
                existing
                    .iter()
                    .map(|site| edit(site.start, site.end, format!("{{{{{new}}}}}")))
                    .collect(),
                false,
                false,
            ))
        }
        "relink_field" | "unset_field" => {
            let replacement = if action(command) == "relink_field" {
                format!("{{{{{}}}}}", normalized_field(command.get("name"))?)
            } else {
                string(command, "text")
                    .ok_or_else(|| fail("의미를 해제한 뒤 남길 본문을 입력하세요."))?
                    .into()
            };
            let selected = if whole_field_unset(command) {
                let name = normalized_field(command.get("old_name"))?;
                let selected = sites
                    .iter()
                    .filter(|site| site.name == name)
                    .collect::<Vec<_>>();
                if selected.is_empty() {
                    return Err(fail("필드를 찾을 수 없습니다."));
                }
                selected
            } else {
                vec![
                    sites
                        .iter()
                        .find(|site| site.start <= start && start < site.end)
                        .ok_or_else(|| fail("고른 필드 사용 위치를 찾을 수 없습니다."))?,
                ]
            };
            Ok(plan(
                selected
                    .iter()
                    .map(|site| edit(site.start, site.end, &replacement))
                    .collect(),
                false,
                false,
            ))
        }
        _ => Err(fail("알 수 없는 필드 명령입니다.")),
    }
}
fn region_edits(
    text: &str,
    command: &Map<String, Value>,
    scan: &TextStructureScan,
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let kind = if action(command) == "create_slot" {
        PLACEMENT_SLOT
    } else {
        PLACEMENT_OPTION
    };
    let id = marker_id(command.get("id"), false)?;
    marker_label(command.get("label"))?;
    let (first, last, lo, hi) = line_range(text, start, end)?;
    if scan.placements.iter().any(|place| {
        place.kind == kind && place.begin_marker_line <= last && first <= place.end_marker_line
    }) {
        return Err(fail(REGION_OVERLAP));
    }
    if kind == PLACEMENT_OPTION {
        let owners = scan
            .placements
            .iter()
            .filter(|place| {
                place.kind == PLACEMENT_SLOT
                    && place.begin_marker_line < first
                    && last < place.end_marker_line
            })
            .collect::<Vec<_>>();
        if owners.len() != 1 || command.get("slot_id") != Some(&json!(owners[0].slot_id)) {
            return Err(fail("고른 범위는 하나의 항목 안에 있어야 합니다."));
        }
        if scan.slots.iter().any(|slot| {
            slot.id == owners[0].slot_id && slot.options.iter().any(|option| option.id == id)
        }) {
            return Err(fail("같은 항목에 해당 선택 식별자가 이미 있습니다."));
        }
    } else if scan.slots.iter().any(|slot| slot.id == id) {
        return Err(fail("항목 식별자가 이미 있습니다."));
    }
    let opening = format!(
        "{}{}",
        marker_text(kind, &id, command.get("label"))?,
        eol(text)
    );
    let closing = if hi == chars(text) && !text.ends_with(['\r', '\n']) {
        format!("{}{}", eol(text), end_marker(kind)?)
    } else {
        format!("{}{}", end_marker(kind)?, eol(text))
    };
    Ok(plan(
        vec![edit(lo, lo, opening), edit(hi, hi, closing)],
        lo != start || hi != end,
        false,
    ))
}
fn target_name(scan: &TextStructureScan, place: &TextStructurePlacement) -> String {
    let slot = scan.slots.iter().find(|slot| slot.id == place.slot_id);
    if place.kind == PLACEMENT_OPTION {
        let option = slot.and_then(|slot| {
            slot.options
                .iter()
                .find(|option| Some(&option.id) == place.option_id.as_ref())
        });
        option
            .and_then(|option| option.label.as_deref())
            .filter(|label| !label.is_empty())
            .unwrap_or(place.option_id.as_deref().unwrap_or(""))
            .into()
    } else {
        slot.and_then(|slot| slot.label.as_deref())
            .filter(|label| !label.is_empty())
            .unwrap_or(&place.slot_id)
            .into()
    }
}
fn block_edits(
    text: &str,
    command: &Map<String, Value>,
    scan: &TextStructureScan,
    target: &TextStructurePlacement,
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let starts = line_starts(text);
    let begin = target.begin_marker_line;
    let finish = target.end_marker_line;
    match action(command) {
        "rename_slot" | "rename_option" => {
            let current = if target.kind == PLACEMENT_OPTION {
                target.option_id.as_deref().unwrap_or("")
            } else {
                &target.slot_id
            };
            let new_id = command.get("id").map_or_else(|| current.into(), python_str);
            if new_id != current {
                marker_id(command.get("id"), true)?;
            }
            marker_label(command.get("label"))?;
            if target.kind == PLACEMENT_SLOT
                && scan
                    .slots
                    .iter()
                    .any(|slot| slot.id == new_id && slot.id != target.slot_id)
            {
                return Err(fail("항목 식별자가 이미 있습니다."));
            }
            if target.kind == PLACEMENT_OPTION
                && scan
                    .slots
                    .iter()
                    .filter(|slot| slot.id == target.slot_id)
                    .flat_map(|slot| &slot.options)
                    .any(|option| {
                        option.id == new_id && Some(&option.id) != target.option_id.as_ref()
                    })
            {
                return Err(fail("같은 항목에 해당 선택 식별자가 이미 있습니다."));
            }
            let existing_label = scan
                .slots
                .iter()
                .find(|slot| slot.id == target.slot_id)
                .and_then(|slot| {
                    if target.kind == PLACEMENT_SLOT {
                        slot.label.as_deref()
                    } else {
                        slot.options
                            .iter()
                            .find(|option| Some(&option.id) == target.option_id.as_ref())
                            .and_then(|option| option.label.as_deref())
                    }
                });
            let label = command
                .get("label")
                .cloned()
                .unwrap_or_else(|| existing_label.map_or(Value::Null, |label| json!(label)));
            Ok(plan(
                vec![edit(
                    starts[begin],
                    starts[begin + 1],
                    format!(
                        "{}{}",
                        marker_text(target.kind, &new_id, Some(&label))?,
                        eol(text)
                    ),
                )],
                false,
                false,
            ))
        }
        "delete" => Ok(plan(
            vec![edit(starts[begin], starts[finish + 1], "")],
            false,
            false,
        )),
        "unwrap" => {
            let children = scan
                .placements
                .iter()
                .filter(|place| place.kind == PLACEMENT_OPTION && place.slot_id == target.slot_id)
                .collect::<Vec<_>>();
            let cascade = target.kind == PLACEMENT_SLOT
                && !children.is_empty()
                && !command.get("cascade").is_some_and(python_truthy);
            let mut lines = vec![begin, finish];
            if target.kind == PLACEMENT_SLOT {
                for child in children {
                    lines.extend([child.begin_marker_line, child.end_marker_line]);
                }
            }
            lines.sort();
            lines.dedup();
            Ok(plan(
                lines
                    .into_iter()
                    .map(|line| edit(starts[line], starts[line + 1], ""))
                    .collect(),
                false,
                cascade,
            ))
        }
        "move" | "duplicate" => {
            let lo = starts[begin];
            let hi = starts[finish + 1];
            let default = json!(utf16(text, hi));
            let destination = from_utf16(text, command.get("destination").or(Some(&default)))?;
            if !starts.contains(&destination) {
                return Err(fail("옮기거나 복제할 위치는 줄 경계여야 합니다."));
            }
            if action(command) == "move" {
                if lo <= destination && destination <= hi {
                    return Err(fail("영역을 자기 안으로 옮길 수 없습니다."));
                }
                Ok(plan(
                    vec![
                        edit(lo, hi, ""),
                        edit(destination, destination, part(text, lo, hi)),
                    ],
                    false,
                    false,
                ))
            } else {
                let Some(new_id) = command.get("new_id").filter(|value| python_truthy(value))
                else {
                    return Err(fail("복제할 영역의 새 식별자를 입력하세요."));
                };
                let copied = part(text, lo, hi);
                let old = python_trim(part(text, starts[begin], starts[begin + 1]));
                let replacement =
                    marker_text(target.kind, &python_str(new_id), command.get("label"))?;
                Ok(plan(
                    vec![edit(
                        destination,
                        destination,
                        copied.replacen(old, &replacement, 1),
                    )],
                    false,
                    false,
                ))
            }
        }
        "adjust_range" => {
            let (first, last, _, _) = line_range(text, start, end)?;
            if first > last {
                return Err(fail("조정한 범위에 본문이 없습니다."));
            }
            Ok(plan(
                vec![
                    edit(starts[begin], starts[begin + 1], ""),
                    edit(starts[finish], starts[finish + 1], ""),
                    edit(
                        starts[first],
                        starts[first],
                        part(text, starts[begin], starts[begin + 1]),
                    ),
                    edit(
                        starts[last + 1],
                        starts[last + 1],
                        part(text, starts[finish], starts[finish + 1]),
                    ),
                ],
                true,
                false,
            ))
        }
        _ => Err(fail(format!(
            "알 수 없는 저작 명령입니다: {:?}",
            action(command)
        ))),
    }
}
fn plan_edits(text: &str, command: &Map<String, Value>) -> Result<EditPlan, TxtAuthoringError> {
    let scan = scan_text_structure(text);
    let action = action(command);
    if action == "repair_marker" {
        for item in &scan.diagnostics {
            if let Some(suggestion) = repair_suggestion(text, &scan, item)
                && suggestion["command"] == Value::Object(command.clone())
            {
                let lo = from_utf16(text, command.get("start"))?;
                let hi = from_utf16(text, command.get("end"))?;
                return Ok(plan(
                    vec![edit(lo, hi, value_string(command.get("text")))],
                    false,
                    false,
                ));
            }
        }
        return Err(fail(FIX_STALE));
    }
    if !scan.diagnostics.is_empty()
        && !matches!(
            action,
            "create_field" | "rename_field" | "relink_field" | "unset_field"
        )
    {
        return Err(fail(STRUCTURE_FIRST));
    }
    let (start, end) = selected_offsets(text, command)?;
    if matches!(
        action,
        "create_field" | "rename_field" | "relink_field" | "unset_field"
    ) {
        return field_edits(text, command, start, end);
    }
    if matches!(action, "create_slot" | "create_option") {
        return region_edits(text, command, &scan, start, end);
    }
    let target =
        target(&scan, command).ok_or_else(|| fail("항목이나 선택 영역을 찾을 수 없습니다."))?;
    block_edits(text, command, &scan, target, start, end)
}

fn line_block_children(
    text: &str,
    scan: &TextStructureScan,
    first: usize,
    last: usize,
) -> (Vec<Value>, Value) {
    let markers = marker_lines(scan);
    let mut children = Vec::new();
    let mut options = 0;
    for place in &scan.placements {
        if place.kind != PLACEMENT_OPTION
            || place.begin_marker_line < first
            || place.end_marker_line > last
            || (place.begin_marker_line == first && place.end_marker_line == last)
        {
            continue;
        }
        options += 1;
        let count = (place.begin_marker_line + 1..place.end_marker_line)
            .filter(|line| !markers.contains(line))
            .count();
        children.push(json!({"kind":"option","id":place.option_id,"label":target_name(scan,place),"count":count}));
    }
    let mut names = Vec::<String>::new();
    let mut counts = Vec::<usize>::new();
    for item in occurrences(text, scan) {
        if item["line"]
            .as_u64()
            .is_none_or(|line| line < first as u64 || line > last as u64)
        {
            continue;
        }
        let name = item["name"].as_str().unwrap_or("");
        if let Some(at) = names.iter().position(|known| known == name) {
            counts[at] += 1;
        } else {
            names.push(name.into());
            counts.push(1);
        }
    }
    let total = counts.iter().sum::<usize>();
    for (name, count) in names.into_iter().zip(counts) {
        children.push(json!({"kind":"field","id":name,"label":name,"count":count}));
    }
    let paragraphs = (first..=last)
        .filter(|line| !markers.contains(line))
        .count();
    (
        children,
        json!({"paragraphs":paragraphs,"fields":total,"options":options,"tables":0}),
    )
}
fn text_hit_parts(text: &str, start: usize, end: usize) -> (String, String, String) {
    let before = part(text, 0, start);
    let after = part(text, end, chars(text));
    let line_start = before
        .rfind(['\r', '\n'])
        .map_or(0, |at| chars(&before[..at + 1]));
    let line_end = after
        .find(['\r', '\n'])
        .map_or(chars(text), |at| end + chars(&after[..at]));
    let mut lo = start;
    let mut hi = end;
    let mut focus = part(text, start, end).to_owned();
    for site in field_sites(part(text, line_start, line_end)) {
        if site.start < end - line_start && start - line_start < site.end {
            lo = lo.min(line_start + site.start);
            hi = hi.max(line_start + site.end);
            focus = humanize(part(text, lo, hi));
        }
    }
    context_parts(
        &humanize(part(text, line_start, lo)),
        &focus,
        &humanize(part(text, hi, line_end)),
        12,
    )
}
pub fn text_hit_context(text: &str, start: usize, end: usize) -> String {
    let (a, b, c) = text_hit_parts(text, start, end);
    format!("{a}{b}{c}")
}
fn cascade_error(children: Vec<Value>) -> TxtAuthoringError {
    let message = "항목 의미를 해제하면 하위 선택 의미도 해제됩니다. 함께 해제를 확인하세요.";
    TxtAuthoringError {
        message: message.into(),
        refusal: Some(json!({"code":"cascade_required","children":children,"message":message})),
    }
}
fn project(
    text: &str,
    command: &Map<String, Value>,
    projecting: bool,
) -> Result<Value, TxtAuthoringError> {
    let action = action(command);
    if action == "revert_template" {
        return Err(fail(NO_FILLED_VALUE));
    }
    let scan = scan_text_structure(text);
    let plan = plan_edits(text, command)?;
    if plan.cascade && !projecting {
        let target =
            target(&scan, command).ok_or_else(|| fail("항목이나 선택 영역을 찾을 수 없습니다."))?;
        let (children, _) = line_block_children(
            text,
            &scan,
            target.begin_marker_line,
            target.end_marker_line,
        );
        return Err(cascade_error(
            children
                .into_iter()
                .filter(|item| item["kind"] == "option")
                .collect(),
        ));
    }
    let result = apply_edits(text, &plan.edits);
    if scan.diagnostics.is_empty() {
        let after = scan_text_structure(&result);
        if let Some(item) = after.diagnostics.first() {
            return Err(fail(format!(
                "명령을 적용하면 구조가 깨집니다: {}",
                item.message
            )));
        }
    }
    let starts = line_starts(text);
    let (start, end) = selected_offsets(text, command)?;
    let original = if action == "create_field" {
        Some(part(text, start, end).to_owned())
    } else {
        None
    };
    let mut before = Value::Null;
    let mut after = Value::Null;
    let mut included = Value::Null;
    let mut included_location = Value::Null;
    let mut children = Vec::new();
    let mut counts = Value::Null;
    let mut label = command_label(command, None);
    let mut extra = Map::new();
    match action {
        "create_field" => {
            let name = normalized_field(command.get("name"))?;
            let all = fields(text, &scan);
            let existing = all
                .iter()
                .find(|item| item["name"] == name)
                .and_then(|item| item["count"].as_u64())
                .unwrap_or(0);
            before = json!(original);
            after = json!(format!("[ {name} ]"));
            extra.insert("links_existing".into(), json!(existing > 0));
            extra.insert("existing_count".into(), json!(existing));
            extra.insert(
                "candidates".into(),
                json!(field_candidates(&all).map_err(|error| fail(error.to_string()))?),
            );
            if command.get("ranges").is_some_and(|value| !value.is_null()) {
                let mut edits = plan.edits.clone();
                edits.sort_by_key(|item| (item.start, item.end));
                included = json!(
                    edits
                        .iter()
                        .map(|item| text_hit_context(text, item.start, item.end))
                        .collect::<Vec<_>>()
                );
            }
        }
        "rename_field" => {
            let old = normalized_field(command.get("old_name"))?;
            let new = normalized_field(command.get("name"))?;
            before = json!(old);
            after = json!(new);
            label = command_label(command, Some(&json!(old)));
        }
        "unset_field" if whole_field_unset(command) => {
            let name = normalized_field(command.get("old_name"))?;
            before = json!(format!("{{{{{name}}}}}"));
            after = json!(
                plan.edits
                    .first()
                    .map(|item| item.text.as_str())
                    .unwrap_or("")
            );
            included = json!(
                occurrences(text, &scan)
                    .into_iter()
                    .filter(|item| item["name"] == name)
                    .map(|item| item["context"].clone())
                    .collect::<Vec<_>>()
            );
            label = command_label(command, Some(&json!(name)));
        }
        "relink_field" | "unset_field" => {
            let site = field_sites(text)
                .into_iter()
                .find(|site| site.start <= start && start < site.end)
                .ok_or_else(|| fail("고른 필드 사용 위치를 찾을 수 없습니다."))?;
            before = json!(site.source);
            after = json!(
                plan.edits
                    .first()
                    .map(|item| item.text.as_str())
                    .unwrap_or("")
            );
            label = command_label(command, Some(&json!(site.name)));
        }
        "repair_marker" => {
            let item = plan.edits.first().ok_or_else(|| fail(FIX_STALE))?;
            before = json!(part(text, item.start, item.end));
            after = json!(if item.text.is_empty() {
                "마커 제거"
            } else {
                &item.text
            });
            let suggestion = scan
                .diagnostics
                .iter()
                .filter_map(|diag| repair_suggestion(text, &scan, diag))
                .find(|row| row["command"] == Value::Object(command.clone()));
            label = command_label(command, suggestion.as_ref().map(|row| &row["label"]));
        }
        "create_slot" | "create_option" => {
            let (first, last, lo, hi) = line_range(text, start, end)?;
            before = json!(part(text, start, end));
            included = json!(part(text, lo, hi));
            after = included.clone();
            included_location = json!({"start":utf16(text,lo),"end":utf16(text,hi)});
            (children, counts) = line_block_children(text, &scan, first, last);
        }
        _ => {
            let target = target(&scan, command)
                .ok_or_else(|| fail("항목이나 선택 영역을 찾을 수 없습니다."))?;
            let begin = target.begin_marker_line;
            let finish = target.end_marker_line;
            let region = part(text, starts[begin], starts[finish + 1]);
            included = json!(region);
            included_location =
                json!({"start":utf16(text,starts[begin]),"end":utf16(text,starts[finish+1])});
            (children, counts) = line_block_children(text, &scan, begin, finish);
            label = command_label(command, Some(&json!(target_name(&scan, target))));
            match action {
                "delete" => {
                    before = json!(region);
                    after = json!("");
                }
                "unwrap" => {
                    let removed = plan
                        .edits
                        .iter()
                        .map(|item| item.start)
                        .collect::<HashSet<_>>();
                    let lines = splitlines(text);
                    let value = lines
                        .iter()
                        .enumerate()
                        .filter(|(line, _)| {
                            begin <= *line && *line <= finish && !removed.contains(&starts[*line])
                        })
                        .map(|(_, line)| line.whole)
                        .collect::<String>();
                    before = json!(region);
                    after = json!(value);
                }
                "move" => {
                    before = json!(region);
                    after = json!(region);
                }
                "duplicate" => {
                    before = json!(region);
                    after = json!(
                        plan.edits
                            .first()
                            .map(|item| item.text.as_str())
                            .unwrap_or("")
                    );
                }
                "rename_slot" | "rename_option" => {
                    before = json!(part(text, starts[begin], starts[begin + 1]));
                    after = json!(
                        plan.edits
                            .first()
                            .map(|item| item.text.as_str())
                            .unwrap_or("")
                    );
                }
                "adjust_range" => {
                    let (first, last, lo, hi) = line_range(text, start, end)?;
                    before = json!(region);
                    included = json!(part(text, lo, hi));
                    after = included.clone();
                    included_location = json!({"start":utf16(text,lo),"end":utf16(text,hi)});
                    (children, counts) = line_block_children(text, &scan, first, last);
                }
                _ => {}
            }
        }
    }
    let mut rows=plan.edits.iter().map(|item|json!({"start":utf16(text,item.start),"end":utf16(text,item.end),"text":item.text})).collect::<Vec<_>>();
    rows.sort_by_key(|item| {
        (
            item["start"].as_u64().unwrap_or(0),
            item["end"].as_u64().unwrap_or(0),
        )
    });
    rows.reverse();
    let mut output = json!({"edits":rows,"affected":plan.edits.len(),"expanded":plan.expanded,
        "result":analyze(&result),"captured_text":original,"original":original,"before":before,"after":after,
        "included":included,"included_location":included_location,"children":children,"counts":counts,
        "label":label,"requires_cascade":plan.cascade});
    if let Some(map) = output.as_object_mut() {
        map.extend(extra);
    }
    Ok(output)
}

pub fn preview(text: &str, command_value: &Value) -> Result<Value, TxtAuthoringError> {
    project(text, command(command_value)?, true)
}
pub fn apply(text: &str, command_value: &Value) -> Result<(String, Value), TxtAuthoringError> {
    let command = command(command_value)?;
    let projection = project(text, command, false)?;
    let edits = projection["edits"]
        .as_array()
        .ok_or_else(|| fail("편집 계획이 없습니다."))?
        .iter()
        .map(|row| {
            Ok(edit(
                from_utf16(text, row.get("start"))?,
                from_utf16(text, row.get("end"))?,
                row["text"].as_str().unwrap_or(""),
            ))
        })
        .collect::<Result<Vec<_>, TxtAuthoringError>>()?;
    Ok((apply_edits(text, &edits), projection))
}

pub fn confirm_tier(command: &Value, preview: &Value, impact: Option<&Value>) -> &'static str {
    let action = command["type"].as_str().unwrap_or("");
    if matches!(action, "delete" | "revert_template")
        || (action == "unwrap"
            && (python_truthy(&preview["requires_cascade"]) || python_truthy(&command["cascade"])))
    {
        return "button";
    }
    if matches!(
        action,
        "rename_field"
            | "adjust_range"
            | "move"
            | "duplicate"
            | "unwrap"
            | "unset_field"
            | "relink_field"
            | "paste"
            | "repair_marker"
    ) || (matches!(action, "rename_slot" | "rename_option")
        && command.get("id").is_some()
        && command["id"]
            != command[if action == "rename_slot" {
                "slot_id"
            } else {
                "option_id"
            }])
        || python_truthy(&preview["expanded"])
    {
        return "enter";
    }
    if action == "create_field"
        && (python_truthy(&command["ranges"]) || python_truthy(&preview["links_existing"]))
    {
        return "enter";
    }
    let impact = impact.unwrap_or(&Value::Null);
    if python_truthy(&impact["field_delta"]["removed_fields"]) {
        return "enter";
    }
    if python_truthy(&impact["linked_jobs"])
        && impact["structure_delta"]
            .as_object()
            .is_some_and(|map| map.values().any(python_truthy))
    {
        return "enter";
    }
    if impact["impact_unverified"]
        .as_i64()
        .is_some_and(|count| count > 0)
    {
        return "enter";
    }
    "none"
}
pub fn created_target(command: &Value, result: &Value) -> Option<Value> {
    match command["type"].as_str()? {
        "create_field" => {
            let name = crate::fields::normalize_field_id(command["name"].as_str()?)?;
            let field = result["fields"]
                .as_array()?
                .iter()
                .find(|field| field["name"] == name)?;
            let occurrences = field["occurrences"].as_array()?.clone();
            let first = occurrences.first()?;
            Some(
                json!({"kind":"field","name":name,"count":field.get("count").cloned().unwrap_or(json!(occurrences.len())),
                "occurrences":occurrences,"location":first}),
            )
        }
        "create_slot" | "create_option" => {
            let slot_id = if command["type"] == "create_slot" {
                &command["id"]
            } else {
                &command["slot_id"]
            };
            let slot = result["slots"]
                .as_array()?
                .iter()
                .find(|slot| &slot["id"] == slot_id)?;
            if command["type"] == "create_slot" {
                return Some(json!({"kind":"slot","slot_id":slot_id,"location":slot["location"]}));
            }
            let option = slot["options"]
                .as_array()?
                .iter()
                .find(|option| option["id"] == command["id"])?;
            Some(
                json!({"kind":"option","slot_id":slot_id,"option_id":option["id"],"location":option["location"]}),
            )
        }
        _ => None,
    }
}
pub fn renamed_target(command: &Value, result: &Value) -> Option<Value> {
    match command["type"].as_str()? {
        "rename_field" => {
            let name = crate::fields::normalize_field_id(command["name"].as_str()?)?;
            let field = result["fields"]
                .as_array()?
                .iter()
                .find(|field| field["name"] == name)?;
            let occurrences = field["occurrences"].as_array()?.clone();
            let first = occurrences.first()?;
            Some(
                json!({"kind":"field","name":name,"count":field.get("count").cloned().unwrap_or(json!(occurrences.len())),
                "occurrences":occurrences,"location":first}),
            )
        }
        "rename_slot" | "rename_option" => {
            let slot_id = if command["type"] == "rename_slot" {
                command.get("id").unwrap_or(&command["slot_id"])
            } else {
                &command["slot_id"]
            };
            let slot = result["slots"]
                .as_array()?
                .iter()
                .find(|slot| &slot["id"] == slot_id)?;
            if command["type"] == "rename_slot" {
                let mut slot = slot.clone();
                slot["kind"] = json!("slot");
                slot["slot_id"] = slot_id.clone();
                return Some(slot);
            }
            let option_id = command.get("id").unwrap_or(&command["option_id"]);
            let option = slot["options"]
                .as_array()?
                .iter()
                .find(|option| &option["id"] == option_id)?;
            let mut option = option.clone();
            option["kind"] = json!("option");
            option["slot_id"] = slot_id.clone();
            option["option_id"] = option_id.clone();
            Some(option)
        }
        _ => None,
    }
}
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
static ENUMERATOR: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:[가-힣]\.|\d+[.)]|\(\d+\)|\([가-힣]\)|[①-⑳㉠-㉻]|[□■○●◦▪▫◆◇▶►※\-•·*])\s*")
        .unwrap()
});
pub fn suggest_field_name(before: &str, selected: &str, existing: &[String]) -> Option<String> {
    if python_trim(selected).is_empty()
        || selected.contains("{{")
        || selected.contains("}}")
        || selected.contains(['\n', '\r'])
    {
        return None;
    }
    let prefix = before.trim_end_matches(python_whitespace);
    if !prefix.ends_with([':', '：']) {
        return None;
    }
    let prefix = &prefix[..prefix.len() - prefix.chars().last()?.len_utf8()];
    let mut at = 0;
    for (index, ch) in prefix.char_indices() {
        if matches!(ch, ':' | '：' | '\t') {
            at = index + ch.len_utf8();
        }
    }
    if let Some(index) = prefix.rfind("}}") {
        at = at.max(index + 2);
    }
    let segment = &prefix[at..];
    let tokens = segment
        .split(python_whitespace)
        .filter(|token| !token.is_empty())
        .collect::<Vec<_>>();
    let run = tokens
        .iter()
        .rev()
        .take_while(|token| {
            token.chars().count() == 1
                && token
                    .chars()
                    .next()
                    .is_some_and(|ch| ('가'..='힣').contains(&ch))
        })
        .count();
    let label = if run >= 2 {
        tokens[tokens.len() - run..].concat()
    } else {
        let letters = segment
            .trim_matches(python_whitespace)
            .chars()
            .collect::<Vec<_>>();
        let mut gap = 0;
        let mut previous = false;
        for (index, ch) in letters.iter().enumerate() {
            if python_whitespace(*ch) {
                if previous {
                    gap = index + 1;
                }
            } else {
                previous = false;
                continue;
            }
            previous = true;
        }
        let mut label = letters[gap..].iter().collect::<String>();
        loop {
            let next = ENUMERATOR.replace(&label, "").into_owned();
            if next == label {
                break;
            }
            label = next;
        }
        label
            .split(python_whitespace)
            .filter(|token| !token.is_empty())
            .collect::<Vec<_>>()
            .join(" ")
    };
    if label.is_empty() || chars(&label) > 20 {
        return None;
    }
    let label = normalized_field(Some(&json!(label))).ok()?;
    let compact = label.split(python_whitespace).collect::<String>();
    existing
        .iter()
        .find(|item| item.split(python_whitespace).collect::<String>() == compact)
        .cloned()
        .or(Some(label))
}

const COMMAND_TYPES: [&str; 13] = [
    "create_field",
    "create_slot",
    "create_option",
    "rename_field",
    "relink_field",
    "unset_field",
    "rename_slot",
    "rename_option",
    "adjust_range",
    "unwrap",
    "delete",
    "duplicate",
    "move",
];
const NEED_FIELD: &str = "필드를 고르세요.";
const ONE_FIELD: &str = "필드를 하나만 고르세요.";
const NEED_REGION: &str = "항목이나 선택 영역을 고르세요.";
const NEED_OPTION: &str = "선택 영역을 고르세요.";
const NEED_RANGE: &str = "문서에서 범위를 고르세요.";
const OPTION_OUTSIDE: &str = "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요.";
const MULTI_REGION: &str = "고른 범위가 여러 독립 영역에 걸쳐 있습니다. 한 범위를 고르세요.";
fn availability_entries(
    reasons: &HashMap<&'static str, Option<&'static str>>,
    alternatives: &HashMap<&'static str, Value>,
) -> Vec<Value> {
    COMMAND_TYPES
        .iter()
        .map(|kind| {
            let reason = reasons.get(kind).copied().flatten();
            json!({"type":kind,"enabled":reason.is_none(),"reason":reason,
            "alternative":if reason.is_some(){alternatives.get(kind).cloned()}else{None}})
        })
        .collect()
}
fn shared_reasons(
    field_hits: &[String],
    target_kind: Option<&str>,
    has_slot: bool,
    broken: bool,
) -> HashMap<&'static str, Option<&'static str>> {
    let mut reasons = HashMap::new();
    let distinct = field_hits.iter().collect::<HashSet<_>>().len();
    reasons.insert(
        "rename_field",
        if field_hits.is_empty() {
            Some(NEED_FIELD)
        } else if distinct > 1 {
            Some(ONE_FIELD)
        } else {
            None
        },
    );
    for kind in ["relink_field", "unset_field"] {
        reasons.insert(
            kind,
            if field_hits.is_empty() {
                Some(NEED_FIELD)
            } else if field_hits.len() > 1 {
                Some(ONE_FIELD)
            } else {
                None
            },
        );
    }
    let blocked = if broken { Some(STRUCTURE_FIRST) } else { None };
    reasons.insert(
        "rename_slot",
        blocked.or(if has_slot { None } else { Some(NEED_REGION) }),
    );
    reasons.insert(
        "rename_option",
        blocked.or(if target_kind == Some("option") {
            None
        } else {
            Some(NEED_OPTION)
        }),
    );
    for kind in ["adjust_range", "unwrap", "delete", "duplicate", "move"] {
        reasons.insert(
            kind,
            blocked.or(if target_kind.is_some() {
                None
            } else {
                Some(NEED_REGION)
            }),
        );
    }
    reasons
}
fn overlaps(lo: usize, hi: usize, start: usize, end: usize) -> bool {
    if start == end {
        lo <= start && start <= hi
    } else {
        lo < end && start < hi
    }
}
fn placement_hits<'a>(
    scan: &'a TextStructureScan,
    starts: &[usize],
    start: usize,
    end: usize,
) -> (Vec<&'a TextStructurePlacement>, bool) {
    let hit = scan
        .placements
        .iter()
        .filter_map(|place| {
            let lo = starts[place.begin_marker_line];
            let hi = starts[place.end_marker_line + 1];
            overlaps(lo, hi, start, end).then_some((place, lo, hi))
        })
        .collect::<Vec<_>>();
    let containing = hit
        .iter()
        .filter(|(_, lo, hi)| *lo <= start && end <= *hi)
        .map(|(place, _, _)| *place)
        .collect();
    let crossing = hit.iter().any(|(_, lo, hi)| !(*lo <= start && end <= *hi));
    (containing, crossing)
}
fn create_field_reason(
    scan: &TextStructureScan,
    starts: &[usize],
    sites: &[FieldSite],
    start: usize,
    end: usize,
) -> Option<&'static str> {
    if placement_hits(scan, starts, start, end).1 {
        return Some(MULTI_REGION);
    }
    let inside = sites.iter().any(|site| {
        if start == end {
            site.start < start && start < site.end
        } else {
            site.start < end && start < site.end
        }
    });
    inside.then_some(FIELD_OVERLAP)
}
pub fn available_commands(text: &str, selection: &Value, context: Option<&Value>) -> Vec<Value> {
    let mut reasons = HashMap::new();
    let alternatives = HashMap::new();
    let selection = selection.as_object();
    let offsets = selection.and_then(|selection| selected_offsets(text, selection).ok());
    let Some((start, end)) = offsets else {
        for kind in COMMAND_TYPES {
            reasons.insert(kind, Some(INVALID_SELECTION));
        }
        return availability_entries(&reasons, &alternatives);
    };
    let scan = scan_text_structure(text);
    let starts = line_starts(text);
    let sites = field_sites(text);
    let hits = sites
        .iter()
        .filter(|site| overlaps(site.start, site.end, start, end))
        .map(|site| site.name.clone())
        .collect::<Vec<_>>();
    let (containing, _) = placement_hits(&scan, &starts, start, end);
    let context = context.unwrap_or(&Value::Null);
    let slot_id = context.get("slot_id").cloned().unwrap_or_else(|| {
        containing
            .iter()
            .find(|place| place.kind == PLACEMENT_SLOT)
            .map_or(Value::Null, |place| json!(place.slot_id))
    });
    let option_id = context.get("option_id").cloned().unwrap_or_else(|| {
        containing
            .iter()
            .find(|place| place.kind == PLACEMENT_OPTION)
            .map_or(Value::Null, |place| json!(place.option_id))
    });
    let (slot_id, option_id) =
        if slot_id.is_null() || !scan.slots.iter().any(|slot| json!(slot.id) == slot_id) {
            (Value::Null, Value::Null)
        } else {
            (slot_id, option_id)
        };
    let target_kind = if !option_id.is_null() && !slot_id.is_null() {
        Some("option")
    } else if !slot_id.is_null() {
        Some("slot")
    } else {
        None
    };
    reasons = shared_reasons(
        &hits,
        target_kind,
        !slot_id.is_null(),
        !scan.diagnostics.is_empty(),
    );
    reasons.insert(
        "create_field",
        create_field_reason(&scan, &starts, &sites, start, end),
    );
    if !scan.diagnostics.is_empty() {
        reasons.insert("create_slot", Some(STRUCTURE_FIRST));
        reasons.insert("create_option", Some(STRUCTURE_FIRST));
        return availability_entries(&reasons, &alternatives);
    }
    let (first, last, _, _) = match line_range(text, start, end) {
        Ok(range) => range,
        Err(_) => {
            reasons.insert("create_slot", Some(NO_CONTENT_LINE));
            reasons.insert("create_option", Some(NO_CONTENT_LINE));
            return availability_entries(&reasons, &alternatives);
        }
    };
    let line_hits = scan
        .placements
        .iter()
        .filter(|place| place.begin_marker_line <= last && first <= place.end_marker_line)
        .collect::<Vec<_>>();
    reasons.insert(
        "create_slot",
        (!line_hits.is_empty()).then_some(REGION_OVERLAP),
    );
    let owners = scan
        .placements
        .iter()
        .filter(|place| {
            place.kind == PLACEMENT_SLOT
                && place.begin_marker_line < first
                && last < place.end_marker_line
        })
        .collect::<Vec<_>>();
    let slot_hits = line_hits.iter().any(|place| place.kind == PLACEMENT_SLOT);
    let mut alternatives = alternatives;
    if owners.len() == 1 {
        reasons.insert(
            "create_option",
            line_hits
                .iter()
                .any(|place| place.kind == PLACEMENT_OPTION)
                .then_some(REGION_OVERLAP),
        );
    } else if slot_hits {
        reasons.insert("create_option", Some(MULTI_REGION));
    } else {
        reasons.insert("create_option", Some(OPTION_OUTSIDE));
        alternatives.insert(
            "create_option",
            json!({"label":"먼저 항목 만들기","command_type":"create_slot"}),
        );
    }
    availability_entries(&reasons, &alternatives)
}

pub fn available_target_commands(
    text: &str,
    kind: &str,
    name: Option<&str>,
) -> Result<Vec<Value>, TxtAuthoringError> {
    if !matches!(kind, "field" | "occurrence" | "slot" | "option") {
        return Err(fail(INVALID_SELECTION));
    }
    let broken = !scan_text_structure(text).diagnostics.is_empty();
    let field = matches!(kind, "field" | "occurrence");
    let region = if field { None } else { Some(kind) };
    let hits = if field {
        vec![name.unwrap_or("").to_owned()]
    } else {
        Vec::new()
    };
    let mut reasons = shared_reasons(&hits, region, region.is_some(), broken);
    if kind == "field" {
        reasons.insert("relink_field", Some("필드 사용 위치를 하나 고르세요."));
    }
    reasons.insert(
        "create_field",
        Some(if field { FIELD_OVERLAP } else { NEED_RANGE }),
    );
    if broken {
        reasons.insert("create_slot", Some(STRUCTURE_FIRST));
        reasons.insert("create_option", Some(STRUCTURE_FIRST));
    } else {
        reasons.insert(
            "create_slot",
            Some(if field { NEED_RANGE } else { REGION_OVERLAP }),
        );
        reasons.insert(
            "create_option",
            Some(if kind == "slot" {
                OPTION_OUTSIDE
            } else if kind == "option" {
                REGION_OVERLAP
            } else {
                NEED_RANGE
            }),
        );
    }
    Ok(availability_entries(&reasons, &HashMap::new()))
}
pub fn same_text_sites(text: &str, selection: &Value) -> Vec<Value> {
    let Some(selection) = selection.as_object() else {
        return Vec::new();
    };
    let (start, end) = match (
        from_utf16(text, selection.get("start")),
        from_utf16(text, selection.get("end")),
    ) {
        (Ok(start), Ok(end)) => (start, end),
        _ => return Vec::new(),
    };
    if start > end {
        return Vec::new();
    }
    let phrase = part(text, start, end);
    if python_trim(phrase).is_empty() {
        return Vec::new();
    }
    let scan = scan_text_structure(text);
    let starts = line_starts(text);
    let sites = field_sites(text);
    let grammar = scan_text_token_spans(text, Some(&scan));
    let mut output = Vec::new();
    for (byte, _) in text.match_indices(phrase) {
        let lo = chars(&text[..byte]);
        let hi = lo + chars(phrase);
        if (lo < end && start < hi) || grammar.iter().any(|span| span.start < hi && lo < span.end) {
            continue;
        }
        let (lead, focus, tail) = text_hit_parts(text, lo, hi);
        let begin = lead.encode_utf16().count();
        let context = format!("{lead}{focus}{tail}");
        let reason = create_field_reason(&scan, &starts, &sites, lo, hi);
        output.push(json!({"location":{"start":utf16(text,lo),"end":utf16(text,hi)},"line":line_at(&starts,lo),
            "context":context,"focus":{"start":begin,"end":begin+focus.encode_utf16().count()},
            "enabled":reason.is_none(),"reason":reason}));
    }
    output
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
    let mut excluded = Vec::new();
    for place in &scan.placements {
        if place.kind != PLACEMENT_OPTION
            || place.option_id.as_deref() == selected.get(&place.slot_id).and_then(Value::as_str)
        {
            continue;
        }
        let owner = scan
            .slots
            .iter()
            .find(|slot| slot.id == place.slot_id)
            .ok_or_else(|| fail("항목이 없습니다."))?;
        let chosen = owner
            .options
            .iter()
            .find(|option| {
                selected.get(&place.slot_id).and_then(Value::as_str) == Some(option.id.as_str())
            })
            .ok_or_else(|| fail("선택이 없습니다."))?;
        let omitted = owner
            .options
            .iter()
            .find(|option| Some(option.id.as_str()) == place.option_id.as_deref())
            .ok_or_else(|| fail("선택이 없습니다."))?;
        let chosen_label = chosen
            .label
            .as_deref()
            .filter(|label| !label.is_empty())
            .unwrap_or(&chosen.id);
        let omitted_label = omitted
            .label
            .as_deref()
            .filter(|label| !label.is_empty())
            .unwrap_or(&omitted.id);
        excluded.push(json!({"slot_id":place.slot_id,"option_id":place.option_id,"selected_option_id":selected.get(&place.slot_id),
            "label":omitted_label,"reason":format!("현재 시험에서 '{chosen_label}'을 골라 '{omitted_label}'은 제외되었습니다."),
            "start":utf16(text,starts[place.begin_marker_line]),"end":utf16(text,starts[place.end_marker_line+1])}));
    }
    Ok(
        json!({"text":output,"report":{"missing_fields":[],"empty_fields":empty_fields},"occurrences":occurrences,"excluded":excluded}),
    )
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn utf16_field_edit_preview_and_apply_agree() {
        let source = "😀 값\n";
        let command = json!({"type":"create_field","start":3,"end":4,"name":"이름"});
        let previewed = preview(source, &command).unwrap();
        assert_eq!(
            previewed["edits"],
            json!([{"start":3,"end":4,"text":"{{이름}}"}])
        );
        let (changed, impact) = apply(source, &command).unwrap();
        assert_eq!(changed, "😀 {{이름}}\n");
        assert_eq!(impact, previewed);
        assert_eq!(source, "😀 값\n");
        let sites = same_text_sites("○○시청 ○○시청", &json!({"start":0,"end":4}));
        assert_eq!(sites.len(), 1);
        assert_eq!(sites[0]["focus"], json!({"start":5,"end":9}));
    }

    #[test]
    fn copy_context_elides_token_grammar_and_merges_whitespace() {
        let source = "머리말\n계약 상대방 수요기관: {{수요기관}} 담당자 {{담당자}} 연락처\n끝";
        let analysis = analyze(source);
        let fields = analysis["fields"].as_array().unwrap();
        let request = fields
            .iter()
            .find(|field| field["name"] == "수요기관")
            .unwrap();
        let person = fields
            .iter()
            .find(|field| field["name"] == "담당자")
            .unwrap();
        assert_eq!(
            request["occurrences"][0]["context"],
            "…약 상대방 수요기관: [수요기관] 담당자 [담당자] 연…"
        );
        assert_eq!(
            person["occurrences"][0]["context"],
            "… [수요기관] 담당자 [담당자] 연락처"
        );
        assert_eq!(
            occurrence_context("짧은 앞", "[이름]", "뒤"),
            "짧은 앞[이름]뒤"
        );
        assert_eq!(
            occurrence_context(&"가".repeat(20), "[이름]", &"나".repeat(20)),
            format!("…{}[이름]{}…", "가".repeat(12), "나".repeat(12))
        );
        assert_eq!(
            occurrence_context("앞\t\t말  ", "[x]", "  뒤\n말"),
            "앞 말 [x] 뒤 말"
        );
        let hit = text_hit_context("첫 줄\n앞 {{이름}} 공고 뒤\n끝", 13, 15);
        assert_eq!(hit, "앞 [이름] 공고 뒤");
    }

    #[test]
    fn nested_option_requires_cascade_before_unwrap() {
        let source = "{{#항목 s}}\n{{#선택 a}}\n본문\n{{/선택}}\n{{/항목}}\n";
        let command = json!({"type":"unwrap","kind":"slot","slot_id":"s"});
        let previewed = preview(source, &command).unwrap();
        assert_eq!(previewed["requires_cascade"], true);
        let error = apply(source, &command).unwrap_err();
        assert_eq!(error.refusal.unwrap()["code"], "cascade_required");
        assert!(source.starts_with("{{#항목 s}}"));
    }

    #[test]
    fn field_edits_preserve_utf16_scope_and_conflicts() {
        let source = "😀 이름 {{이름}}";
        let (created, plan) = apply(
            source,
            &json!({"type":"create_field","start":3,"end":5,"name":"이름"}),
        )
        .unwrap();
        assert_eq!(created, "😀 {{이름}} {{이름}}");
        assert_eq!(
            plan["edits"],
            json!([{"start":3,"end":5,"text":"{{이름}}"}])
        );
        let (renamed, impact) = apply(
            &created,
            &json!({"type":"rename_field","old_name":"이름","name":"성명"}),
        )
        .unwrap();
        assert_eq!(renamed, "😀 {{성명}} {{성명}}");
        assert_eq!(impact["affected"], 2);
        let (relinked, _) = apply(
            &renamed,
            &json!({"type":"relink_field","start":4,"name":"담당자"}),
        )
        .unwrap();
        assert_eq!(relinked, "😀 {{담당자}} {{성명}}");
        let conflict = preview(
            "{{성명}} {{담당자}} {{담당자}}",
            &json!({"type":"rename_field","old_name":"성명","name":"담당자"}),
        )
        .unwrap_err();
        assert_eq!(
            conflict.refusal.unwrap(),
            json!({"code":"name_conflict","name":"담당자",
            "existing_count":2,"message":"‘담당자’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."})
        );
        assert_eq!(source, "😀 이름 {{이름}}");

        let with_candidates = "{{이름}} 값 {{주소}}\n";
        let fresh = preview(
            with_candidates,
            &json!({"type":"create_field","start":7,"end":8,"name":"연락처"}),
        )
        .unwrap();
        assert_eq!(fresh["links_existing"], false);
        assert_eq!(fresh["existing_count"], 0);
        assert_eq!(
            fresh["candidates"],
            json!([{"name":"이름","count":1},{"name":"주소","count":1}])
        );
        let linked = preview(
            with_candidates,
            &json!({"type":"create_field","start":7,"end":8,"name":"이름"}),
        )
        .unwrap();
        assert_eq!(linked["links_existing"], true);
        assert_eq!(linked["existing_count"], 1);
        assert_eq!(linked["result"]["fields"][0]["count"], 2);
    }

    #[test]
    fn repeated_sites_share_one_field_plan_without_absorbing_tokens() {
        let source = "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n{{○○시청}}\n";
        let sites = same_text_sites(source, &json!({"start":0,"end":4}));
        assert_eq!(
            sites
                .iter()
                .map(|site| site["location"].clone())
                .collect::<Vec<_>>(),
            vec![
                json!({"start":11,"end":15}),
                json!({"start":20,"end":24}),
                json!({"start":25,"end":29})
            ]
        );
        assert_eq!(sites[2]["focus"], json!({"start":5,"end":9}));
        let command = json!({"type":"create_field","name":"수요기관","start":0,"end":4,
            "ranges":[{"start":0,"end":4},{"start":25,"end":29},{"start":11,"end":15}]});
        let (changed, plan) = apply(source, &command).unwrap();
        assert_eq!(
            changed,
            "{{수요기관}} 귀하\n서명 {{수요기관}} (인)\n○○시청 {{수요기관}}\n{{○○시청}}\n"
        );
        assert_eq!(plan["affected"], 3);
        assert_eq!(plan["edits"].as_array().unwrap().len(), 3);
        assert_eq!(confirm_tier(&command, &plan, None), "enter");
        let overlap = json!({"type":"create_field","name":"a","start":0,"end":2,
            "ranges":[{"start":0,"end":2},{"start":1,"end":3}]});
        assert!(
            apply("아아아", &overlap)
                .unwrap_err()
                .message
                .contains("기존 필드가 포함")
        );
        assert_eq!(
            source,
            "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n{{○○시청}}\n"
        );
    }

    #[test]
    fn confirmation_and_created_target_follow_actual_edit_impact() {
        let empty_impact = json!({"linked_jobs":[],"impact_unverified":0,
            "field_delta":{"added_fields":[],"removed_fields":[]},
            "structure_delta":{"added_slots":[],"removed_slots":[],
                "added_options":[],"removed_options":[],"renamed":[]}});
        assert_eq!(
            confirm_tier(
                &json!({"type":"create_field","name":"기관"}),
                &json!({}),
                Some(&empty_impact)
            ),
            "none"
        );
        assert_eq!(
            confirm_tier(
                &json!({"type":"create_field","name":"기관"}),
                &json!({"links_existing":true}),
                Some(&empty_impact)
            ),
            "enter"
        );
        assert_eq!(
            confirm_tier(
                &json!({"type":"unwrap","slot_id":"s","cascade":true}),
                &json!({}),
                Some(&empty_impact)
            ),
            "button"
        );
        assert_eq!(
            confirm_tier(
                &json!({"type":"rename_field","old_name":"기관","name":"담당"}),
                &json!({}),
                Some(&empty_impact)
            ),
            "enter"
        );

        let source = "기관: 조달청\n본문\n끝\n";
        let (with_field, _) = apply(
            source,
            &json!({"type":"create_field","start":4,"end":7,"name":"기관"}),
        )
        .unwrap();
        let field = created_target(
            &json!({"type":"create_field","name":" 기관 "}),
            &analyze(&with_field),
        )
        .unwrap();
        assert_eq!(field["kind"], "field");
        assert_eq!(field["name"], "기관");
        assert_eq!(field["location"], field["occurrences"][0]);
        assert_eq!(field["location"]["start"], 4);
        assert_eq!(field["location"]["end"], 10);
        assert!(created_target(&json!({"type":"rename_field"}), &analyze(&with_field)).is_none());
    }

    #[test]
    fn confirmation_tier_exposes_each_destructive_or_uncertain_impact() {
        let empty = json!({"linked_jobs":[],"impact_unverified":0,
            "field_delta":{"added_fields":[],"removed_fields":[]},
            "structure_delta":{"added_slots":[],"removed_slots":[],"added_options":[],
                "removed_options":[],"renamed":[]}});
        for (command, preview, impact, expected) in [
            (
                json!({"type":"delete","slot_id":"s"}),
                json!({}),
                empty.clone(),
                "button",
            ),
            (
                json!({"type":"unwrap","slot_id":"s","cascade":true}),
                json!({}),
                empty.clone(),
                "button",
            ),
            (
                json!({"type":"create_slot","id":"s"}),
                json!({"expanded":true}),
                empty.clone(),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"t"}),
                json!({}),
                empty.clone(),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                empty.clone(),
                "none",
            ),
            (
                json!({"type":"create_field","name":"F"}),
                json!({}),
                json!({"impact_unverified":1}),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                json!({"field_delta":{"removed_fields":["F"]}}),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                json!({"linked_jobs":["작업"],"structure_delta":{"added_slots":["t"]}}),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                json!({"linked_jobs":["작업"]}),
                "none",
            ),
        ] {
            assert_eq!(
                confirm_tier(&command, &preview, Some(&impact)),
                expected,
                "{command}"
            );
        }
    }

    #[test]
    fn name_suggestion_and_invalid_identifiers_keep_distinct_refusals() {
        assert_eq!(
            suggest_field_name("수요 기관: ", "○○시청", &["수요기관".into()]),
            Some("수요기관".into())
        );
        assert_eq!(suggest_field_name("수요기관 ", "○○시청", &[]), None);
        assert_eq!(suggest_field_name("기관: ", "{{기관}}", &[]), None);

        let empty_name = preview(
            "수요기관: ○○시청",
            &json!({"type":"create_field","start":6,"end":10,"name":"  "}),
        )
        .unwrap_err();
        assert_eq!(empty_name.refusal.unwrap()["field"], "name");
        let invalid_id = preview(
            "본문\n끝\n",
            &json!({"type":"create_slot","start":0,"end":2,"id":"a b","label":"표시"}),
        )
        .unwrap_err();
        assert_eq!(invalid_id.refusal.unwrap()["field"], "identifier");
        let empty_id = preview(
            "본문\n끝\n",
            &json!({"type":"create_slot","start":0,"end":2,"id":"","label":""}),
        )
        .unwrap_err();
        assert_eq!(
            empty_id.refusal.unwrap(),
            json!({"code":"invalid_name","field":"identifier",
                "message":"항목이나 선택의 식별자를 입력하세요."})
        );
        let invalid_label = preview(
            "본문\n끝\n",
            &json!({"type":"create_slot","start":0,"end":2,"id":"a","label":"표  시"}),
        )
        .unwrap_err();
        assert_eq!(invalid_label.refusal.unwrap()["field"], "name");
    }

    #[test]
    fn ambiguous_structure_ranges_refuse_without_changing_the_editor_text() {
        let offset = |source: &str, needle: &str| {
            source[..source.find(needle).unwrap()]
                .encode_utf16()
                .count()
        };
        let original = "앞\n공통\n첫째\n둘째\n끝\n";
        let (slotted, _) = apply(
            original,
            &json!({"type":"create_slot","start":offset(original,"공통"),
                "end":offset(original,"끝"),"id":"s"}),
        )
        .unwrap();
        let (source, _) = apply(
            &slotted,
            &json!({"type":"create_option","start":offset(&slotted,"첫째"),
                "end":offset(&slotted,"둘째"),"slot_id":"s","id":"a"}),
        )
        .unwrap();
        let cases = [
            (
                json!({"type":"create_slot","start":offset(&source,"공통"),
                "end":offset(&source,"둘째"),"id":"other"}),
                "겹칩니다",
            ),
            (
                json!({"type":"create_option","start":0,"end":1,
                "slot_id":"s","id":"b"}),
                "하나의 항목",
            ),
            (
                json!({"type":"create_option","start":offset(&source,"둘째"),
                "end":offset(&source,"둘째")+2,"slot_id":"s","id":"a"}),
                "식별자",
            ),
            (
                json!({"type":"unwrap","kind":"slot","slot_id":"s"}),
                "함께 해제",
            ),
            (
                json!({"type":"move","kind":"slot","slot_id":"s",
                "destination":offset(&source,"공통")}),
                "자기 안",
            ),
            (
                json!({"type":"duplicate","kind":"slot","slot_id":"s"}),
                "새 식별자",
            ),
        ];
        for (command, expected) in cases {
            assert!(
                apply(&source, &command)
                    .unwrap_err()
                    .message
                    .contains(expected)
            );
        }
        assert_eq!(analyze(&source)["slots"][0]["id"], "s");
        assert!(
            apply(
                "😀본문",
                &json!({"type":"create_field","start":1,"end":2,"name":"F"})
            )
            .unwrap_err()
            .message
            .contains("문자 중간")
        );
    }

    #[test]
    fn whole_field_unset_is_one_plan_while_an_occurrence_unset_stays_local() {
        let source = "가 {{F}}\n{{G}} 나 {{F}}\n끝 {{F}}\n";
        let analysis = analyze(source);
        let occurrences = analysis["fields"]
            .as_array()
            .unwrap()
            .iter()
            .find(|field| field["name"] == "F")
            .unwrap()["occurrences"]
            .clone();
        let command = json!({"type":"unset_field","old_name":"F","name":"F",
            "occurrences":occurrences,"start":2,"end":7,"text":"값"});
        let projected = preview(source, &command).unwrap();
        assert_eq!(projected["affected"], 3);
        assert_eq!(projected["edits"].as_array().unwrap().len(), 3);
        assert_eq!(projected["label"], "‘F’ 필드 의미 해제");
        assert_eq!(projected["before"], "{{F}}");
        assert_eq!(projected["after"], "값");
        assert_eq!(projected["result"]["fields"][0]["name"], "G");
        assert_eq!(
            apply(source, &command).unwrap().0,
            "가 값\n{{G}} 나 값\n끝 값\n"
        );
        let local = json!({"type":"unset_field","old_name":"F","name":"F",
            "start":2,"end":7,"text":"값"});
        assert_eq!(
            apply(source, &local).unwrap().0,
            "가 값\n{{G}} 나 {{F}}\n끝 {{F}}\n"
        );
    }

    #[test]
    fn analysis_name_tags_keep_utf16_coordinates_and_region_pairing() {
        let source = "😀 {{공고명}}\n{{#항목 사유 변경 사유}}\n본문\n{{/항목}}\n";
        let spans = analyze(source)["spans"].as_array().unwrap().clone();
        assert_eq!(spans.len(), 3);
        assert_eq!(spans[0]["label"], "공고명");
        assert_eq!(
            (spans[0]["start"].as_u64(), spans[0]["end"].as_u64()),
            (Some(3), Some(10))
        );
        assert_eq!(spans[1]["region"], "slot");
        assert_eq!(spans[1]["role"], "open");
        assert_eq!(spans[2]["role"], "close");
        assert_eq!(spans[1]["paired"], true);
        assert_eq!(spans[2]["paired"], true);
    }

    #[test]
    fn structure_preview_refusal_and_marker_repair_keep_source() {
        let source = "머리\n공통 {{F}}\n첫째\n둘째\n끝\n";
        let index =
            |text: &str, needle: &str| text[..text.find(needle).unwrap()].encode_utf16().count();
        let (slot, _) = apply(source, &json!({"type":"create_slot","start":3,"end":index(source,"끝"),"id":"s","label":"특약"})).unwrap();
        let first = index(&slot, "첫째");
        let (with_option, _) = apply(
            &slot,
            &json!({"type":"create_option","start":first,"end":first+2,"slot_id":"s","id":"a"}),
        )
        .unwrap();
        let planned = preview(
            &with_option,
            &json!({"type":"unwrap","kind":"slot","slot_id":"s"}),
        )
        .unwrap();
        assert_eq!(planned["requires_cascade"], true);
        assert_eq!(planned["counts"]["options"], 1);
        assert_eq!(planned["children"][0]["id"], "a");
        let refused = apply(
            &with_option,
            &json!({"type":"unwrap","kind":"slot","slot_id":"s"}),
        )
        .unwrap_err();
        assert_eq!(refused.refusal.unwrap()["code"], "cascade_required");
        assert_eq!(analyze(&with_option)["diagnostics"], json!([]));
        let outside = available_commands(&with_option, &json!({"start":0,"end":2}), None);
        let option = outside
            .iter()
            .find(|row| row["type"] == "create_option")
            .unwrap();
        assert_eq!(option["enabled"], false);
        assert_eq!(
            option["reason"],
            "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요."
        );
        let field_at = index(&with_option, "{{F}}") + 1;
        let on_field = available_commands(
            &with_option,
            &json!({"start":field_at,"end":field_at}),
            Some(&json!({"slot_id":"s","option_id":null})),
        );
        assert_eq!(
            on_field
                .iter()
                .find(|row| row["type"] == "unset_field")
                .unwrap()["enabled"],
            true
        );
        assert_eq!(
            on_field
                .iter()
                .find(|row| row["type"] == "create_field")
                .unwrap()["reason"],
            "고른 범위에 기존 필드가 포함되어 있습니다."
        );
        let broken_commands =
            available_commands("{{#항목 s}}\n본문\n", &json!({"start":12,"end":12}), None);
        assert_eq!(
            broken_commands
                .iter()
                .find(|row| row["type"] == "create_slot")
                .unwrap()["reason"],
            "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요."
        );

        let broken = "앞\n{{/항목}}\n뒤\n";
        let diagnostic = &analyze(broken)["diagnostics"][0];
        assert_eq!(diagnostic["category"], "structure");
        let repair = diagnostic["suggestion"]["command"].clone();
        let (fixed, _) = apply(broken, &repair).unwrap();
        assert_eq!(fixed, "앞\n뒤\n");
        assert!(
            apply(&fixed, &repair)
                .unwrap_err()
                .message
                .contains("더는 적용되지")
        );
    }
}
