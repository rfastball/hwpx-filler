//! Edit plans: TXT authoring commands resolved into character-offset edits.

use super::analysis::repair_suggestion;
use super::{
    FIELD_OVERLAP, FIX_STALE, FieldSite, INVALID_SELECTION, REGION_OVERLAP, STRUCTURE_FIRST,
    TxtAuthoringError, action, byte_at, chars, conflict, end_marker, eol, fail, field_sites,
    from_utf16, line_range, line_starts, marker_id, marker_label, marker_text, normalized_field,
    part, string, utf16, value_string,
};
use crate::structure_scan::{PLACEMENT_OPTION, PLACEMENT_SLOT, python_trim};
use crate::template_authoring::whole_field_unset;
use crate::text_render::{python_str, python_truthy};
use crate::text_structure::{TextStructurePlacement, TextStructureScan, scan_text_structure};
use serde_json::{Map, Value, json};

#[derive(Clone)]
pub(super) struct Edit {
    pub(super) start: usize,
    pub(super) end: usize,
    pub(super) text: String,
}
#[derive(Clone)]
pub(super) struct EditPlan {
    pub(super) edits: Vec<Edit>,
    pub(super) expanded: bool,
    pub(super) cascade: bool,
}
fn plan(edits: Vec<Edit>, expanded: bool, cascade: bool) -> EditPlan {
    EditPlan {
        edits,
        expanded,
        cascade,
    }
}
pub(super) fn edit(start: usize, end: usize, text: impl Into<String>) -> Edit {
    Edit {
        start,
        end,
        text: text.into(),
    }
}
pub(super) fn apply_edits(text: &str, edits: &[Edit]) -> String {
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
pub(super) fn selected_offsets(
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
pub(super) fn target<'a>(
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
fn create_field_plan(
    text: &str,
    command: &Map<String, Value>,
    sites: &[FieldSite],
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
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
fn rename_field_plan(
    command: &Map<String, Value>,
    sites: &[FieldSite],
) -> Result<EditPlan, TxtAuthoringError> {
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
fn relink_or_unset_sites<'a>(
    command: &Map<String, Value>,
    sites: &'a [FieldSite],
    start: usize,
) -> Result<Vec<&'a FieldSite>, TxtAuthoringError> {
    if !whole_field_unset(command) {
        return Ok(vec![
            sites
                .iter()
                .find(|site| site.start <= start && start < site.end)
                .ok_or_else(|| fail("고른 필드 사용 위치를 찾을 수 없습니다."))?,
        ]);
    }
    let name = normalized_field(command.get("old_name"))?;
    let selected = sites
        .iter()
        .filter(|site| site.name == name)
        .collect::<Vec<_>>();
    if selected.is_empty() {
        return Err(fail("필드를 찾을 수 없습니다."));
    }
    Ok(selected)
}
fn relink_or_unset_plan(
    command: &Map<String, Value>,
    sites: &[FieldSite],
    start: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let replacement = if action(command) == "relink_field" {
        format!("{{{{{}}}}}", normalized_field(command.get("name"))?)
    } else {
        string(command, "text")
            .ok_or_else(|| fail("의미를 해제한 뒤 남길 본문을 입력하세요."))?
            .into()
    };
    let selected = relink_or_unset_sites(command, sites, start)?;
    Ok(plan(
        selected
            .iter()
            .map(|site| edit(site.start, site.end, &replacement))
            .collect(),
        false,
        false,
    ))
}
fn field_edits(
    text: &str,
    command: &Map<String, Value>,
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let sites = field_sites(text);
    match action(command) {
        "create_field" => create_field_plan(text, command, &sites, start, end),
        "rename_field" => rename_field_plan(command, &sites),
        "relink_field" | "unset_field" => relink_or_unset_plan(command, &sites, start),
        _ => Err(fail("알 수 없는 필드 명령입니다.")),
    }
}
fn region_identity_refusal(
    command: &Map<String, Value>,
    scan: &TextStructureScan,
    kind: &str,
    id: &str,
    lines: (usize, usize),
) -> Option<&'static str> {
    let (first, last) = lines;
    if kind != PLACEMENT_OPTION {
        return scan
            .slots
            .iter()
            .any(|slot| slot.id == id)
            .then_some("항목 식별자가 이미 있습니다.");
    }
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
        return Some("고른 범위는 하나의 항목 안에 있어야 합니다.");
    }
    scan.slots
        .iter()
        .any(|slot| {
            slot.id == owners[0].slot_id && slot.options.iter().any(|option| option.id == id)
        })
        .then_some("같은 항목에 해당 선택 식별자가 이미 있습니다.")
}
fn region_closing(text: &str, kind: &str, hi: usize) -> Result<String, TxtAuthoringError> {
    Ok(if hi == chars(text) && !text.ends_with(['\r', '\n']) {
        format!("{}{}", eol(text), end_marker(kind)?)
    } else {
        format!("{}{}", end_marker(kind)?, eol(text))
    })
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
    if let Some(message) = region_identity_refusal(command, scan, kind, &id, (first, last)) {
        return Err(fail(message));
    }
    let opening = format!(
        "{}{}",
        marker_text(kind, &id, command.get("label"))?,
        eol(text)
    );
    let closing = region_closing(text, kind, hi)?;
    Ok(plan(
        vec![edit(lo, lo, opening), edit(hi, hi, closing)],
        lo != start || hi != end,
        false,
    ))
}
pub(super) fn target_name(scan: &TextStructureScan, place: &TextStructurePlacement) -> String {
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

/// The selected region with its marker-line starts, shared by block commands.
struct Block<'a> {
    text: &'a str,
    command: &'a Map<String, Value>,
    scan: &'a TextStructureScan,
    target: &'a TextStructurePlacement,
    starts: Vec<usize>,
}

fn rename_identity_refusal(
    scan: &TextStructureScan,
    target: &TextStructurePlacement,
    new_id: &str,
) -> Option<&'static str> {
    if target.kind == PLACEMENT_SLOT {
        return scan
            .slots
            .iter()
            .any(|slot| slot.id == new_id && slot.id != target.slot_id)
            .then_some("항목 식별자가 이미 있습니다.");
    }
    (target.kind == PLACEMENT_OPTION
        && scan
            .slots
            .iter()
            .filter(|slot| slot.id == target.slot_id)
            .flat_map(|slot| &slot.options)
            .any(|option| option.id == new_id && Some(&option.id) != target.option_id.as_ref()))
    .then_some("같은 항목에 해당 선택 식별자가 이미 있습니다.")
}
fn existing_region_label<'a>(
    scan: &'a TextStructureScan,
    target: &TextStructurePlacement,
) -> Option<&'a str> {
    let slot = scan.slots.iter().find(|slot| slot.id == target.slot_id)?;
    if target.kind == PLACEMENT_SLOT {
        slot.label.as_deref()
    } else {
        slot.options
            .iter()
            .find(|option| Some(&option.id) == target.option_id.as_ref())
            .and_then(|option| option.label.as_deref())
    }
}
fn rename_region_plan(block: &Block) -> Result<EditPlan, TxtAuthoringError> {
    let Block {
        text,
        command,
        scan,
        target,
        starts,
    } = block;
    let begin = target.begin_marker_line;
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
    if let Some(message) = rename_identity_refusal(scan, target, &new_id) {
        return Err(fail(message));
    }
    let label = command.get("label").cloned().unwrap_or_else(|| {
        existing_region_label(scan, target).map_or(Value::Null, |label| json!(label))
    });
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
fn unwrap_plan(block: &Block) -> EditPlan {
    let Block {
        command,
        scan,
        target,
        starts,
        ..
    } = block;
    let children = scan
        .placements
        .iter()
        .filter(|place| place.kind == PLACEMENT_OPTION && place.slot_id == target.slot_id)
        .collect::<Vec<_>>();
    let cascade = target.kind == PLACEMENT_SLOT
        && !children.is_empty()
        && !command.get("cascade").is_some_and(python_truthy);
    let mut lines = vec![target.begin_marker_line, target.end_marker_line];
    if target.kind == PLACEMENT_SLOT {
        for child in children {
            lines.extend([child.begin_marker_line, child.end_marker_line]);
        }
    }
    lines.sort();
    lines.dedup();
    plan(
        lines
            .into_iter()
            .map(|line| edit(starts[line], starts[line + 1], ""))
            .collect(),
        false,
        cascade,
    )
}
fn duplicate_edit(
    block: &Block,
    destination: usize,
    lo: usize,
    hi: usize,
) -> Result<Edit, TxtAuthoringError> {
    let Block {
        text,
        command,
        target,
        starts,
        ..
    } = block;
    let begin = target.begin_marker_line;
    let Some(new_id) = command.get("new_id").filter(|value| python_truthy(value)) else {
        return Err(fail("복제할 영역의 새 식별자를 입력하세요."));
    };
    let copied = part(text, lo, hi);
    let old = python_trim(part(text, starts[begin], starts[begin + 1]));
    let replacement = marker_text(target.kind, &python_str(new_id), command.get("label"))?;
    Ok(edit(
        destination,
        destination,
        copied.replacen(old, &replacement, 1),
    ))
}
fn move_or_duplicate_plan(block: &Block) -> Result<EditPlan, TxtAuthoringError> {
    let Block {
        text,
        command,
        target,
        starts,
        ..
    } = block;
    let lo = starts[target.begin_marker_line];
    let hi = starts[target.end_marker_line + 1];
    let default = json!(utf16(text, hi));
    let destination = from_utf16(text, command.get("destination").or(Some(&default)))?;
    if !starts.contains(&destination) {
        return Err(fail("옮기거나 복제할 위치는 줄 경계여야 합니다."));
    }
    if action(command) != "move" {
        return Ok(plan(
            vec![duplicate_edit(block, destination, lo, hi)?],
            false,
            false,
        ));
    }
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
}
fn adjust_range_plan(
    block: &Block,
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let Block {
        text,
        target,
        starts,
        ..
    } = block;
    let begin = target.begin_marker_line;
    let finish = target.end_marker_line;
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
fn block_edits(
    text: &str,
    command: &Map<String, Value>,
    scan: &TextStructureScan,
    target: &TextStructurePlacement,
    start: usize,
    end: usize,
) -> Result<EditPlan, TxtAuthoringError> {
    let block = Block {
        text,
        command,
        scan,
        target,
        starts: line_starts(text),
    };
    let starts = &block.starts;
    match action(command) {
        "rename_slot" | "rename_option" => rename_region_plan(&block),
        "delete" => Ok(plan(
            vec![edit(
                starts[target.begin_marker_line],
                starts[target.end_marker_line + 1],
                "",
            )],
            false,
            false,
        )),
        "unwrap" => Ok(unwrap_plan(&block)),
        "move" | "duplicate" => move_or_duplicate_plan(&block),
        "adjust_range" => adjust_range_plan(&block, start, end),
        _ => Err(fail(format!(
            "알 수 없는 저작 명령입니다: {:?}",
            action(command)
        ))),
    }
}
fn repair_marker_plan(
    text: &str,
    command: &Map<String, Value>,
    scan: &TextStructureScan,
) -> Result<EditPlan, TxtAuthoringError> {
    for item in &scan.diagnostics {
        if let Some(suggestion) = repair_suggestion(text, scan, item)
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
    Err(fail(FIX_STALE))
}
pub(super) fn plan_edits(
    text: &str,
    command: &Map<String, Value>,
) -> Result<EditPlan, TxtAuthoringError> {
    let scan = scan_text_structure(text);
    let action = action(command);
    if action == "repair_marker" {
        return repair_marker_plan(text, command, &scan);
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
