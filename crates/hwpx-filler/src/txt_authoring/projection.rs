//! Preview projection: what an authoring command changes, before it is applied.

use super::analysis::{analyze, repair_suggestion};
use super::edit_plan::{
    Edit, EditPlan, apply_edits, edit, plan_edits, selected_offsets, target, target_name,
};
use super::{
    FIX_STALE, NO_FILLED_VALUE, TxtAuthoringError, action, chars, command, context_parts, fail,
    field_sites, fields, from_utf16, humanize, line_range, line_starts, normalized_field,
    occurrences, part, utf16,
};
use crate::structure_scan::PLACEMENT_OPTION;
use crate::template_authoring::{command_label, field_candidates, whole_field_unset};
use crate::text_structure::{
    TextStructurePlacement, TextStructureScan, marker_lines, scan_text_structure, splitlines,
};
use serde_json::{Map, Value, json};
use std::collections::HashSet;

fn option_children(
    scan: &TextStructureScan,
    markers: &HashSet<usize>,
    first: usize,
    last: usize,
) -> Vec<Value> {
    scan.placements
        .iter()
        .filter(|place| {
            place.kind == PLACEMENT_OPTION
                && place.begin_marker_line >= first
                && place.end_marker_line <= last
                && !(place.begin_marker_line == first && place.end_marker_line == last)
        })
        .map(|place| {
            let count = (place.begin_marker_line + 1..place.end_marker_line)
                .filter(|line| !markers.contains(line))
                .count();
            json!({"kind":"option","id":place.option_id,"label":target_name(scan,place),"count":count})
        })
        .collect()
}
fn field_counts(
    text: &str,
    scan: &TextStructureScan,
    first: usize,
    last: usize,
) -> Vec<(String, usize)> {
    let mut counts = Vec::<(String, usize)>::new();
    for item in occurrences(text, scan) {
        if item["line"]
            .as_u64()
            .is_none_or(|line| line < first as u64 || line > last as u64)
        {
            continue;
        }
        let name = item["name"].as_str().unwrap_or("");
        if let Some(at) = counts.iter().position(|(known, _)| known == name) {
            counts[at].1 += 1;
        } else {
            counts.push((name.into(), 1));
        }
    }
    counts
}
fn line_block_children(
    text: &str,
    scan: &TextStructureScan,
    first: usize,
    last: usize,
) -> (Vec<Value>, Value) {
    let markers = marker_lines(scan);
    let mut children = option_children(scan, &markers, first, last);
    let options = children.len();
    let counts = field_counts(text, scan, first, last);
    let total = counts.iter().map(|(_, count)| count).sum::<usize>();
    for (name, count) in counts {
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
pub(super) fn text_hit_parts(text: &str, start: usize, end: usize) -> (String, String, String) {
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

/// The command being projected, with its scan, edit plan, and selected offsets.
struct Projecting<'a> {
    text: &'a str,
    command: &'a Map<String, Value>,
    scan: &'a TextStructureScan,
    plan: &'a EditPlan,
    start: usize,
    end: usize,
}

/// The command-specific part of a projection; everything else is shared.
struct View {
    before: Value,
    after: Value,
    included: Value,
    included_location: Value,
    children: Vec<Value>,
    counts: Value,
    label: String,
    extra: Map<String, Value>,
}

impl View {
    fn new(command: &Map<String, Value>) -> Self {
        View {
            before: Value::Null,
            after: Value::Null,
            included: Value::Null,
            included_location: Value::Null,
            children: Vec::new(),
            counts: Value::Null,
            label: command_label(command, None),
            extra: Map::new(),
        }
    }
    /// Shows the whole lines from `first` to `last` as the included range.
    fn include_lines(&mut self, at: &Projecting, first: usize, last: usize, lo: usize, hi: usize) {
        self.included = json!(part(at.text, lo, hi));
        self.after = self.included.clone();
        self.included_location = json!({"start":utf16(at.text,lo),"end":utf16(at.text,hi)});
        (self.children, self.counts) = line_block_children(at.text, at.scan, first, last);
    }
}

fn first_edit_text(plan: &EditPlan) -> Value {
    json!(
        plan.edits
            .first()
            .map(|item| item.text.as_str())
            .unwrap_or("")
    )
}

fn create_field_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let name = normalized_field(at.command.get("name"))?;
    let all = fields(at.text, at.scan);
    let existing = all
        .iter()
        .find(|item| item["name"] == name)
        .and_then(|item| item["count"].as_u64())
        .unwrap_or(0);
    view.before = json!(part(at.text, at.start, at.end));
    view.after = json!(format!("[ {name} ]"));
    view.extra
        .insert("links_existing".into(), json!(existing > 0));
    view.extra.insert("existing_count".into(), json!(existing));
    view.extra.insert(
        "candidates".into(),
        json!(field_candidates(&all).map_err(|error| fail(error.to_string()))?),
    );
    if at
        .command
        .get("ranges")
        .is_some_and(|value| !value.is_null())
    {
        let mut edits = at.plan.edits.clone();
        edits.sort_by_key(|item| (item.start, item.end));
        view.included = json!(
            edits
                .iter()
                .map(|item| text_hit_context(at.text, item.start, item.end))
                .collect::<Vec<_>>()
        );
    }
    Ok(())
}
fn rename_field_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let old = normalized_field(at.command.get("old_name"))?;
    let new = normalized_field(at.command.get("name"))?;
    view.before = json!(old);
    view.after = json!(new);
    view.label = command_label(at.command, Some(&json!(old)));
    Ok(())
}
fn unset_whole_field_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let name = normalized_field(at.command.get("old_name"))?;
    view.before = json!(format!("{{{{{name}}}}}"));
    view.after = first_edit_text(at.plan);
    view.included = json!(
        occurrences(at.text, at.scan)
            .into_iter()
            .filter(|item| item["name"] == name)
            .map(|item| item["context"].clone())
            .collect::<Vec<_>>()
    );
    view.label = command_label(at.command, Some(&json!(name)));
    Ok(())
}
fn relink_or_unset_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let site = field_sites(at.text)
        .into_iter()
        .find(|site| site.start <= at.start && at.start < site.end)
        .ok_or_else(|| fail("고른 필드 사용 위치를 찾을 수 없습니다."))?;
    view.before = json!(site.source);
    view.after = first_edit_text(at.plan);
    view.label = command_label(at.command, Some(&json!(site.name)));
    Ok(())
}
fn repair_marker_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let item: &Edit = at.plan.edits.first().ok_or_else(|| fail(FIX_STALE))?;
    view.before = json!(part(at.text, item.start, item.end));
    view.after = json!(if item.text.is_empty() {
        "마커 제거"
    } else {
        &item.text
    });
    let suggestion = at
        .scan
        .diagnostics
        .iter()
        .filter_map(|diag| repair_suggestion(at.text, at.scan, diag))
        .find(|row| row["command"] == Value::Object(at.command.clone()));
    view.label = command_label(at.command, suggestion.as_ref().map(|row| &row["label"]));
    Ok(())
}
fn create_region_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let (first, last, lo, hi) = line_range(at.text, at.start, at.end)?;
    view.before = json!(part(at.text, at.start, at.end));
    view.include_lines(at, first, last, lo, hi);
    Ok(())
}
fn unwrapped_text(at: &Projecting, starts: &[usize], place: &TextStructurePlacement) -> String {
    let removed = at
        .plan
        .edits
        .iter()
        .map(|item| item.start)
        .collect::<HashSet<_>>();
    splitlines(at.text)
        .iter()
        .enumerate()
        .filter(|(line, _)| {
            place.begin_marker_line <= *line
                && *line <= place.end_marker_line
                && !removed.contains(&starts[*line])
        })
        .map(|(_, line)| line.whole)
        .collect::<String>()
}
fn block_view(at: &Projecting, view: &mut View) -> Result<(), TxtAuthoringError> {
    let place = target(at.scan, at.command)
        .ok_or_else(|| fail("항목이나 선택 영역을 찾을 수 없습니다."))?;
    let starts = line_starts(at.text);
    let begin = place.begin_marker_line;
    let finish = place.end_marker_line;
    let region = json!(part(at.text, starts[begin], starts[finish + 1]));
    view.included = region.clone();
    view.included_location =
        json!({"start":utf16(at.text,starts[begin]),"end":utf16(at.text,starts[finish+1])});
    (view.children, view.counts) = line_block_children(at.text, at.scan, begin, finish);
    view.label = command_label(at.command, Some(&json!(target_name(at.scan, place))));
    view.before = region.clone();
    match action(at.command) {
        "delete" => view.after = json!(""),
        "unwrap" => view.after = json!(unwrapped_text(at, &starts, place)),
        "move" => view.after = region,
        "duplicate" => view.after = first_edit_text(at.plan),
        "rename_slot" | "rename_option" => {
            view.before = json!(part(at.text, starts[begin], starts[begin + 1]));
            view.after = first_edit_text(at.plan);
        }
        "adjust_range" => {
            let (first, last, lo, hi) = line_range(at.text, at.start, at.end)?;
            view.include_lines(at, first, last, lo, hi);
        }
        _ => view.before = Value::Null,
    }
    Ok(())
}
fn command_view(at: &Projecting) -> Result<View, TxtAuthoringError> {
    let mut view = View::new(at.command);
    match action(at.command) {
        "create_field" => create_field_view(at, &mut view)?,
        "rename_field" => rename_field_view(at, &mut view)?,
        "unset_field" if whole_field_unset(at.command) => unset_whole_field_view(at, &mut view)?,
        "relink_field" | "unset_field" => relink_or_unset_view(at, &mut view)?,
        "repair_marker" => repair_marker_view(at, &mut view)?,
        "create_slot" | "create_option" => create_region_view(at, &mut view)?,
        _ => block_view(at, &mut view)?,
    }
    Ok(view)
}
fn cascade_refusal(
    text: &str,
    command: &Map<String, Value>,
    scan: &TextStructureScan,
) -> TxtAuthoringError {
    let Some(target) = target(scan, command) else {
        return fail("항목이나 선택 영역을 찾을 수 없습니다.");
    };
    let (children, _) =
        line_block_children(text, scan, target.begin_marker_line, target.end_marker_line);
    cascade_error(
        children
            .into_iter()
            .filter(|item| item["kind"] == "option")
            .collect(),
    )
}
fn ensure_structure_kept(scan: &TextStructureScan, result: &str) -> Result<(), TxtAuthoringError> {
    if !scan.diagnostics.is_empty() {
        return Ok(());
    }
    match scan_text_structure(result).diagnostics.first() {
        Some(item) => Err(fail(format!(
            "명령을 적용하면 구조가 깨집니다: {}",
            item.message
        ))),
        None => Ok(()),
    }
}
fn edit_rows(text: &str, plan: &EditPlan) -> Vec<Value> {
    let mut rows=plan.edits.iter().map(|item|json!({"start":utf16(text,item.start),"end":utf16(text,item.end),"text":item.text})).collect::<Vec<_>>();
    rows.sort_by_key(|item| {
        (
            item["start"].as_u64().unwrap_or(0),
            item["end"].as_u64().unwrap_or(0),
        )
    });
    rows.reverse();
    rows
}
fn project(
    text: &str,
    command: &Map<String, Value>,
    projecting: bool,
) -> Result<Value, TxtAuthoringError> {
    if action(command) == "revert_template" {
        return Err(fail(NO_FILLED_VALUE));
    }
    let scan = scan_text_structure(text);
    let plan = plan_edits(text, command)?;
    if plan.cascade && !projecting {
        return Err(cascade_refusal(text, command, &scan));
    }
    let result = apply_edits(text, &plan.edits);
    ensure_structure_kept(&scan, &result)?;
    let (start, end) = selected_offsets(text, command)?;
    let original = (action(command) == "create_field").then(|| part(text, start, end).to_owned());
    let view = command_view(&Projecting {
        text,
        command,
        scan: &scan,
        plan: &plan,
        start,
        end,
    })?;
    let mut output = json!({"edits":edit_rows(text,&plan),"affected":plan.edits.len(),"expanded":plan.expanded,
        "result":analyze(&result),"captured_text":original,"original":original,"before":view.before,"after":view.after,
        "included":view.included,"included_location":view.included_location,"children":view.children,"counts":view.counts,
        "label":view.label,"requires_cascade":plan.cascade});
    if let Some(map) = output.as_object_mut() {
        map.extend(view.extra);
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
