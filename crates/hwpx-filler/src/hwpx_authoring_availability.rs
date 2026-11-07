//! Authoring command availability over native HWPX coordinates.

use crate::hwpx_authoring_analysis::analyze_hwpx;
use crate::hwpx_authoring_reading::{
    field_range_refusal, paragraph_sites, selected_paragraph, top_paragraphs,
};
use crate::hwpx_authoring_search::{index, selection_path};
use crate::hwpx_product_inspection::inspect_slot_regions;
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::XmlView;
use serde_json::{Value, json};
use std::collections::HashSet;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringAvailabilityError(pub String);
impl fmt::Display for AuthoringAvailabilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringAvailabilityError {}

const COMMANDS: [&str; 13] = [
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
const INVALID: &str = "고른 위치가 올바르지 않습니다.";
const STRUCTURE_FIRST: &str = "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요.";
const NEED_REGION: &str = "항목이나 선택 영역을 고르세요.";
const NEED_OPTION: &str = "선택 영역을 고르세요.";
const NEED_FIELD: &str = "필드를 고르세요.";
const ONE_FIELD: &str = "필드를 하나만 고르세요.";
const NEED_RANGE: &str = "문서에서 범위를 고르세요.";
const NEED_OCCURRENCE: &str = "필드 사용 위치를 하나 고르세요.";
const REGION_OVERLAP: &str = "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요.";
const MULTI_REGION: &str = "고른 범위가 여러 독립 영역에 걸쳐 있습니다. 한 범위를 고르세요.";
const OPTION_OUTSIDE: &str = "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요.";
const REGION_IN_CELL: &str =
    "표 셀 안에서는 항목·선택을 만들 수 없습니다. 표 밖 문단까지 이어서 고르세요.";
const FIELD_OVERLAP: &str = "고른 범위에 기존 필드가 포함되어 있습니다.";
const MULTI_PARAGRAPH_FIELD: &str = "여러 문단에 걸친 필드는 HWPX 누름틀 경계로 만들 수 없습니다.";

fn entries(reasons: &[Option<&'static str>; 13], alternative: bool) -> Vec<Value> {
    COMMANDS
        .iter()
        .enumerate()
        .map(|(index, command)| {
            let reason = reasons[index];
            json!({"type": command, "enabled": reason.is_none(), "reason": reason,
            "alternative": if alternative && index == 2 && reason.is_some() {
                json!({"label": "먼저 항목 만들기", "command_type": "create_slot"})
            } else { Value::Null }})
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

/// The region-command reason: broken structure first, then a missing target.
fn region_reason(broken: bool, allowed: bool, missing: &'static str) -> Option<&'static str> {
    if broken {
        Some(STRUCTURE_FIRST)
    } else if allowed {
        None
    } else {
        Some(missing)
    }
}

fn shared_reasons(
    field_hits: &[String],
    target_kind: Option<&str>,
    has_slot: bool,
    broken: bool,
) -> [Option<&'static str>; 13] {
    let mut reasons = [None; 13];
    let unique = field_hits.iter().collect::<HashSet<_>>().len();
    reasons[3] = field_reason(field_hits, unique > 1);
    reasons[4] = field_reason(field_hits, field_hits.len() > 1);
    reasons[5] = reasons[4];
    reasons[6] = region_reason(broken, has_slot, NEED_REGION);
    reasons[7] = region_reason(broken, target_kind == Some("option"), NEED_OPTION);
    for reason in &mut reasons[8..] {
        *reason = region_reason(broken, target_kind.is_some(), NEED_REGION);
    }
    reasons
}

struct Frame {
    entry: String,
    first: usize,
    last: usize,
    start: usize,
    end: usize,
}

fn selection_frame(
    package: &HwpxPackage,
    selection: &Value,
) -> Result<Option<Frame>, AuthoringAvailabilityError> {
    let values = (|| {
        let entry = selection.get("entry")?.as_str()?;
        let source = package.entries.iter().find(|item| item.name == entry)?;
        let first = index(
            selection
                .get("start_paragraph")
                .or_else(|| selection.get("paragraph")),
        )?;
        let last = index(
            selection
                .get("end_paragraph")
                .or_else(|| selection.get("start_paragraph"))
                .or_else(|| selection.get("paragraph")),
        )?;
        let start = selection
            .get("start")
            .map_or(Some(0), |value| index(Some(value)))?;
        let end = selection
            .get("end")
            .map_or(Some(start), |value| index(Some(value)))?;
        (first <= last && (first != last || start <= end))
            .then_some((source, first, last, start, end))
    })();
    let Some((source, first, last, start, end)) = values else {
        return Ok(None);
    };
    let view = XmlView::parse(&source.data)
        .map_err(|error| AuthoringAvailabilityError(error.to_string()))?;
    let path = selection.get("cell_path");
    let valid = if path.is_some_and(Value::is_array) {
        selection_path(selection)
            .is_some_and(|path| selected_paragraph(&view, first, Some(&path)).is_ok())
    } else if path.is_some_and(|value| !value.is_null()) {
        top_paragraphs(&view).get(first).is_some()
    } else {
        top_paragraphs(&view).get(last).is_some()
    };
    Ok(valid.then(|| Frame {
        entry: source.name.clone(),
        first,
        last,
        start,
        end,
    }))
}

fn overlaps_field(
    item: &Value,
    paragraph: usize,
    first: usize,
    last: usize,
    start: usize,
    end: usize,
) -> bool {
    let (Some(low), Some(high)) = (index(item.get("start")), index(item.get("end"))) else {
        return true;
    };
    if first < paragraph && paragraph < last {
        return true;
    }
    if first == last {
        if start == end {
            low <= start && start <= high
        } else {
            low < end && start < high
        }
    } else if paragraph == first {
        start <= high
    } else {
        low <= end
    }
}

fn field_hits(analysis: &Value, frame: &Frame, path: &Value) -> Vec<String> {
    let mut hits = Vec::new();
    for field in analysis["fields"].as_array().unwrap() {
        for item in field["occurrences"].as_array().unwrap() {
            let Some(paragraph) = index(item.get("paragraph")) else {
                continue;
            };
            if item["entry"] == frame.entry
                && item.get("cell_path").unwrap_or(&Value::Null) == path
                && frame.first <= paragraph
                && paragraph <= frame.last
                && overlaps_field(
                    item,
                    paragraph,
                    frame.first,
                    frame.last,
                    frame.start,
                    frame.end,
                )
            {
                hits.push(field["name"].as_str().unwrap().into());
            }
        }
    }
    hits
}

#[derive(Clone)]
struct Region {
    kind: &'static str,
    slot: String,
    option: Option<String>,
    start: usize,
    end: usize,
}

fn regions(analysis: &Value, entry: &str) -> Vec<Region> {
    let mut out = Vec::new();
    for slot in analysis["slots"].as_array().unwrap() {
        let slot_id = slot["id"].as_str().unwrap();
        for item in std::iter::once(slot).chain(slot["options"].as_array().unwrap().iter()) {
            let location = &item["location"];
            if location["entry"] != entry {
                continue;
            }
            let Some(start) = index(location.get("start_paragraph")) else {
                continue;
            };
            let Some(end) = index(location.get("end_paragraph")) else {
                continue;
            };
            let option =
                (item["kind"] == "option").then(|| item["id"].as_str().unwrap().to_owned());
            out.push(Region {
                kind: if option.is_some() { "option" } else { "slot" },
                slot: slot_id.into(),
                option,
                start,
                end,
            });
        }
    }
    out
}

/// The slot and option the selection targets: explicit context keys win, otherwise
/// the containing regions; a slot the document does not have targets nothing.
fn selection_target(
    context: &Value,
    containing: &[&Region],
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
) -> (Option<String>, Option<String>) {
    let explicit = |key: &str| context.get(key).and_then(Value::as_str).map(str::to_owned);
    let slot = if context.get("slot_id").is_some() {
        explicit("slot_id")
    } else {
        containing
            .iter()
            .find(|item| item.kind == "slot")
            .map(|item| item.slot.clone())
    };
    let option = if context.get("option_id").is_some() {
        explicit("option_id")
    } else {
        containing.iter().find_map(|item| item.option.clone())
    };
    if slot
        .as_ref()
        .is_some_and(|id| !snapshot.slot_regions.contains_key(id))
    {
        return (None, None);
    }
    (slot, option)
}

fn target_kind(slot: &Option<String>, option: &Option<String>) -> Option<&'static str> {
    match (slot, option) {
        (Some(_), Some(_)) => Some("option"),
        (Some(_), None) => Some("slot"),
        _ => None,
    }
}

/// Why a field cannot be created over a single-paragraph selection, if at all.
fn paragraph_field_reason(
    package: &HwpxPackage,
    selection: &Value,
    frame: &Frame,
    field_hits: &[String],
) -> Result<Option<&'static str>, AuthoringAvailabilityError> {
    let source = package
        .entries
        .iter()
        .find(|item| item.name == frame.entry)
        .unwrap();
    let view = XmlView::parse(&source.data)
        .map_err(|error| AuthoringAvailabilityError(error.to_string()))?;
    let path = selection_path(selection);
    let paragraph = selected_paragraph(&view, frame.first, path.as_deref())
        .map_err(|error| AuthoringAvailabilityError(error.into()))?;
    let scan = view.field_occurrences(&frame.entry);
    let sites = paragraph_sites(&view, paragraph, &scan);
    if !sites.sites.is_empty()
        && frame.start == frame.end
        && frame.start <= sites.text.chars().count()
    {
        return Ok(Some(NEED_RANGE));
    }
    let overlap = (!field_hits.is_empty() && frame.start != frame.end).then_some(FIELD_OVERLAP);
    Ok(field_range_refusal(&view, paragraph, &scan, &sites, frame.start, frame.end).or(overlap))
}

/// Reasons for create_slot and create_option, and whether to offer making a slot first.
fn create_region_reasons(
    broken: bool,
    in_cell: bool,
    hits: &[&Region],
    containing: &[&Region],
) -> (Option<&'static str>, Option<&'static str>, bool) {
    if broken {
        return (Some(STRUCTURE_FIRST), Some(STRUCTURE_FIRST), false);
    }
    if in_cell {
        return (Some(REGION_IN_CELL), Some(REGION_IN_CELL), false);
    }
    let slot = (!hits.is_empty()).then_some(REGION_OVERLAP);
    let owners = containing.iter().filter(|item| item.kind == "slot").count();
    if owners == 1 {
        let overlap = hits.iter().any(|item| item.kind == "option");
        (slot, overlap.then_some(REGION_OVERLAP), false)
    } else if hits.iter().any(|item| item.kind == "slot") {
        (slot, Some(MULTI_REGION), false)
    } else {
        (slot, Some(OPTION_OUTSIDE), true)
    }
}

pub fn available_commands_hwpx(
    package: &HwpxPackage,
    selection: &Value,
    context: Option<&Value>,
) -> Result<Vec<Value>, AuthoringAvailabilityError> {
    let Some(frame) = selection_frame(package, selection)? else {
        return Ok(entries(&[Some(INVALID); 13], false));
    };
    let analysis =
        analyze_hwpx(package).map_err(|error| AuthoringAvailabilityError(error.to_string()))?;
    let snapshot = inspect_slot_regions(package)
        .map_err(|error| AuthoringAvailabilityError(error.to_string()))?;
    let path = selection.get("cell_path").cloned().unwrap_or(Value::Null);
    let field_hits = field_hits(&analysis, &frame, &path);
    let regions = regions(&analysis, &frame.entry);
    let hits: Vec<_> = regions
        .iter()
        .filter(|item| path.is_null() && item.start <= frame.last && frame.first <= item.end)
        .collect();
    let containing: Vec<_> = hits
        .iter()
        .copied()
        .filter(|item| item.start <= frame.first && frame.last <= item.end)
        .collect();
    let crossing = hits
        .iter()
        .any(|item| !containing.iter().any(|other| std::ptr::eq(*item, *other)));
    let context = context
        .filter(|value| value.is_object())
        .unwrap_or(&Value::Null);
    let (slot, option) = selection_target(context, &containing, &snapshot);
    let broken = !snapshot.diagnostics.is_empty();
    let mut reasons = shared_reasons(&field_hits, target_kind(&slot, &option), slot.is_some(), broken);
    reasons[0] = if crossing {
        Some(MULTI_REGION)
    } else if frame.first != frame.last {
        Some(MULTI_PARAGRAPH_FIELD)
    } else {
        paragraph_field_reason(package, selection, &frame, &field_hits)?
    };
    let alternative;
    (reasons[1], reasons[2], alternative) =
        create_region_reasons(broken, !path.is_null(), &hits, &containing);
    Ok(entries(&reasons, alternative))
}

pub fn available_target_commands_hwpx(
    package: &HwpxPackage,
    kind: &str,
    name: Option<&str>,
) -> Result<Vec<Value>, AuthoringAvailabilityError> {
    if !matches!(kind, "field" | "occurrence" | "slot" | "option") {
        return Err(AuthoringAvailabilityError(INVALID.into()));
    }
    let snapshot = inspect_slot_regions(package)
        .map_err(|error| AuthoringAvailabilityError(error.to_string()))?;
    let broken = !snapshot.diagnostics.is_empty();
    let field = matches!(kind, "field" | "occurrence");
    let target = if field { None } else { Some(kind) };
    let field_name = [name.unwrap_or("").to_owned()];
    let mut reasons = shared_reasons(
        if field { &field_name } else { &[] },
        target,
        target.is_some(),
        broken,
    );
    if kind == "field" {
        reasons[4] = Some(NEED_OCCURRENCE);
    }
    reasons[0] = if field {
        Some(FIELD_OVERLAP)
    } else {
        Some(NEED_RANGE)
    };
    if broken {
        reasons[1] = Some(STRUCTURE_FIRST);
        reasons[2] = Some(STRUCTURE_FIRST);
    } else {
        reasons[1] = if field {
            Some(NEED_RANGE)
        } else {
            Some(REGION_OVERLAP)
        };
        reasons[2] = Some(match kind {
            "slot" => OPTION_OUTSIDE,
            "option" => REGION_OVERLAP,
            _ => NEED_RANGE,
        });
    }
    Ok(entries(&reasons, false))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::hwpx_authoring_commands::apply_hwpx;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn plain_range_offers_field_and_slot_and_explains_option_prerequisite() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let rows = available_commands_hwpx(
            &package,
            &json!({"entry": "Contents/section0.xml", "paragraph": 0, "start": 0, "end": 1}),
            None,
        )
        .unwrap();
        assert_eq!(rows[0]["enabled"], true);
        assert_eq!(rows[1]["enabled"], true);
        assert_eq!(rows[2]["reason"], OPTION_OUTSIDE);
        assert_eq!(rows[2]["alternative"]["command_type"], "create_slot");
        let target = available_target_commands_hwpx(&package, "field", Some("본문")).unwrap();
        assert_eq!(target[3]["enabled"], true);
        assert_eq!(target[4]["reason"], NEED_OCCURRENCE);
    }

    #[test]
    fn cell_selection_uses_its_own_paragraph_and_never_wraps_the_body() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>짧다</hp:t></hp:run></hp:p><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀 안의 꽤 긴 문구</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p><hp:p><hp:run><hp:t>뒤</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let cell_path = json!([{"parent_paragraph":1,"control":0,"cell":0,"paragraph":0}]);
        let selection = json!({"entry":"Contents/section0.xml","paragraph":0,
            "start_paragraph":0,"end_paragraph":0,"start":0,"end":2,"cell_path":cell_path});
        let rows = available_commands_hwpx(&package, &selection, None).unwrap();
        for kind in ["create_slot", "create_option"] {
            let row = rows.iter().find(|row| row["type"] == kind).unwrap();
            assert_eq!(row["enabled"], false);
            assert_eq!(row["reason"], REGION_IN_CELL);
            let before = package.clone();
            let mut command = selection.clone();
            command["type"] = json!(kind);
            command["id"] = json!("s");
            command["slot_id"] = json!("s");
            assert!(
                apply_hwpx(&mut package, &command)
                    .unwrap_err()
                    .message
                    .contains("표 셀 안에서는")
            );
            assert_eq!(package, before);
        }
        let field = json!({"entry":"Contents/section0.xml","paragraph":0,
            "start":5,"end":9,"cell_path":cell_path});
        let rows = available_commands_hwpx(&package, &field, None).unwrap();
        assert_eq!(rows[0]["enabled"], true);
        let mut command = field.clone();
        command["type"] = json!("create_field");
        command["name"] = json!("문구");
        apply_hwpx(&mut package, &command).unwrap();
        assert_eq!(
            analyze_hwpx(&package).unwrap()["fields"][0]["occurrences"][0]["cell_path"],
            cell_path
        );
    }
}
