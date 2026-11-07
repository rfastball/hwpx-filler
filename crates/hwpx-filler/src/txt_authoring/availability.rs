//! Which authoring commands a selection or target allows, and why not.

use super::projection::text_hit_parts;
use super::{
    FIELD_OVERLAP, FieldSite, INVALID_SELECTION, NO_CONTENT_LINE, REGION_OVERLAP,
    STRUCTURE_FIRST, TxtAuthoringError, chars, fail, field_sites, from_utf16, line_at, line_range,
    line_starts, part, utf16,
};
use super::edit_plan::selected_offsets;
use crate::structure_scan::{PLACEMENT_OPTION, PLACEMENT_SLOT, python_trim};
use crate::text_structure::{
    TextStructurePlacement, TextStructureScan, scan_text_structure, scan_text_token_spans,
};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};

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

type Reasons = HashMap<&'static str, Option<&'static str>>;

fn availability_entries(reasons: &Reasons, alternatives: &HashMap<&'static str, Value>) -> Vec<Value> {
    COMMAND_TYPES
        .iter()
        .map(|kind| {
            let reason = reasons.get(kind).copied().flatten();
            json!({"type":kind,"enabled":reason.is_none(),"reason":reason,
            "alternative":if reason.is_some(){alternatives.get(kind).cloned()}else{None}})
        })
        .collect()
}
/// The field-selection reason: none picked, or more than one where one is needed.
fn field_reason(field_hits: &[String], too_many: bool) -> Option<&'static str> {
    if field_hits.is_empty() {
        Some(NEED_FIELD)
    } else if too_many {
        Some(ONE_FIELD)
    } else {
        None
    }
}
fn shared_reasons(
    field_hits: &[String],
    target_kind: Option<&str>,
    has_slot: bool,
    broken: bool,
) -> Reasons {
    let mut reasons = HashMap::new();
    let distinct = field_hits.iter().collect::<HashSet<_>>().len();
    reasons.insert("rename_field", field_reason(field_hits, distinct > 1));
    for kind in ["relink_field", "unset_field"] {
        reasons.insert(kind, field_reason(field_hits, field_hits.len() > 1));
    }
    let blocked = broken.then_some(STRUCTURE_FIRST);
    let region = |allowed: bool, missing: &'static str| blocked.or((!allowed).then_some(missing));
    reasons.insert("rename_slot", region(has_slot, NEED_REGION));
    reasons.insert(
        "rename_option",
        region(target_kind == Some("option"), NEED_OPTION),
    );
    for kind in ["adjust_range", "unwrap", "delete", "duplicate", "move"] {
        reasons.insert(kind, region(target_kind.is_some(), NEED_REGION));
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
/// The slot and option the selection belongs to: the explicit context first,
/// otherwise the innermost containing regions, and nothing for an unknown slot.
fn region_context(
    scan: &TextStructureScan,
    containing: &[&TextStructurePlacement],
    context: &Value,
) -> (Value, Value) {
    let contained = |kind: &str, id: fn(&TextStructurePlacement) -> Value| {
        containing
            .iter()
            .find(|place| place.kind == kind)
            .map_or(Value::Null, |place| id(place))
    };
    let slot_id = context
        .get("slot_id")
        .cloned()
        .unwrap_or_else(|| contained(PLACEMENT_SLOT, |place| json!(place.slot_id)));
    let option_id = context
        .get("option_id")
        .cloned()
        .unwrap_or_else(|| contained(PLACEMENT_OPTION, |place| json!(place.option_id)));
    if slot_id.is_null() || !scan.slots.iter().any(|slot| json!(slot.id) == slot_id) {
        (Value::Null, Value::Null)
    } else {
        (slot_id, option_id)
    }
}
fn region_kind(slot_id: &Value, option_id: &Value) -> Option<&'static str> {
    if slot_id.is_null() {
        None
    } else if option_id.is_null() {
        Some("slot")
    } else {
        Some("option")
    }
}
/// Fills the create-slot and create-option reasons for a whole-line selection.
fn create_region_reasons(
    scan: &TextStructureScan,
    lines: (usize, usize),
    reasons: &mut Reasons,
    alternatives: &mut HashMap<&'static str, Value>,
) {
    let (first, last) = lines;
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
        .count();
    let slot_hits = line_hits.iter().any(|place| place.kind == PLACEMENT_SLOT);
    if owners == 1 {
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
}
pub fn available_commands(text: &str, selection: &Value, context: Option<&Value>) -> Vec<Value> {
    let mut alternatives = HashMap::new();
    let offsets = selection
        .as_object()
        .and_then(|selection| selected_offsets(text, selection).ok());
    let Some((start, end)) = offsets else {
        let reasons = COMMAND_TYPES
            .iter()
            .map(|kind| (*kind, Some(INVALID_SELECTION)))
            .collect::<Reasons>();
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
    let (slot_id, option_id) =
        region_context(&scan, &containing, context.unwrap_or(&Value::Null));
    let broken = !scan.diagnostics.is_empty();
    let mut reasons = shared_reasons(
        &hits,
        region_kind(&slot_id, &option_id),
        !slot_id.is_null(),
        broken,
    );
    reasons.insert(
        "create_field",
        create_field_reason(&scan, &starts, &sites, start, end),
    );
    let region_reason = if broken {
        Some(STRUCTURE_FIRST)
    } else {
        match line_range(text, start, end) {
            Ok((first, last, _, _)) => {
                create_region_reasons(&scan, (first, last), &mut reasons, &mut alternatives);
                None
            }
            Err(_) => Some(NO_CONTENT_LINE),
        }
    };
    if let Some(reason) = region_reason {
        reasons.insert("create_slot", Some(reason));
        reasons.insert("create_option", Some(reason));
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
