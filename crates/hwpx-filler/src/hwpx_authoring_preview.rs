//! Read-only native paragraph preview for HWPX authoring commands.

use crate::hwpx_authoring_analysis::fields;
use crate::hwpx_authoring_reading::{is_hp, leading_text, top_paragraphs};
use crate::hwpx_product_inspection::{SlotSnapshot, inspect_slot_regions};
use crate::text_render::python_repr;
use hwpx_core::bookmark_region::BookmarkRegion;
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::{NodeId, XmlView};
use serde_json::{Value, json};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringPreviewError(pub String);
impl fmt::Display for AuthoringPreviewError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringPreviewError {}

fn as_text(value: Option<&Value>) -> String {
    match value {
        None => String::new(),
        Some(Value::String(text)) => text.clone(),
        Some(value) => python_repr(value),
    }
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null | Value::Bool(false) => false,
        Value::Number(number) => number.as_f64() != Some(0.0),
        Value::String(text) => !text.is_empty(),
        Value::Array(items) => !items.is_empty(),
        Value::Object(items) => !items.is_empty(),
        Value::Bool(true) => true,
    }
}

fn field_label(
    command: &Value,
    action: &str,
    after: bool,
    captured: Option<&Value>,
) -> Option<String> {
    match action {
        "create_field" | "compile_token" => Some(if after {
            format!("[ {} ]", as_text(command.get("name")))
        } else {
            as_text(captured.filter(|value| truthy(value)))
        }),
        "rename_field" | "relink_field" => Some(as_text(command.get(if after {
            "name"
        } else {
            "old_name"
        }))),
        "unset_field" => Some(if after {
            as_text(command.get("text"))
        } else {
            format!("[ {} ]", as_text(command.get("old_name")))
        }),
        _ => None,
    }
}

pub fn command_preview_label(command: &Value, after: bool, captured: Option<&Value>) -> String {
    let action = command.get("type").and_then(Value::as_str).unwrap_or("");
    if let Some(label) = field_label(command, action, after, captured) {
        return label;
    }
    match action {
        "create_slot" | "rename_slot" | "create_option" | "rename_option" => {
            let noun = if action.ends_with("slot") {
                "항목"
            } else {
                "선택"
            };
            format!(
                "{} {}",
                noun,
                as_text(command.get(if after { "id" } else { "slot_id" }))
            )
        }
        "delete" => if after {
            "삭제됨"
        } else {
            "영역 내용과 의미"
        }
        .into(),
        "unwrap" => if after {
            "본문 유지"
        } else {
            "의미 경계"
        }
        .into(),
        "revert_template" => String::new(),
        _ => as_text(command.get("type")),
    }
}

fn region_name(snapshot: &SlotSnapshot, slot_id: &str, option_id: Option<&str>) -> Option<String> {
    let slot = snapshot.slots.iter().find(|item| item.id == slot_id)?;
    if let Some(option_id) = option_id {
        let option = slot.options.iter().find(|item| item.id == option_id)?;
        Some(option.label.clone().unwrap_or_else(|| option.id.clone()))
    } else {
        Some(slot.label.clone().unwrap_or_else(|| slot.id.clone()))
    }
}

fn target_region<'a>(
    snapshot: &'a SlotSnapshot,
    slot: &str,
    option: Option<&str>,
    on_option: bool,
) -> Option<&'a BookmarkRegion> {
    if on_option {
        snapshot
            .option_regions
            .get(&(slot.to_owned(), option?.to_owned()))
    } else {
        snapshot.slot_regions.get(slot)
    }
}

fn paragraph_text(view: &XmlView, paragraph: NodeId) -> String {
    let mut text = String::new();
    for id in view.descendants(paragraph).unwrap_or_default() {
        if is_hp(view, id, "t") {
            text.push_str(&leading_text(view, id));
        }
    }
    text
}

fn option_children(
    snapshot: &SlotSnapshot,
    entry: &str,
    start: usize,
    end: usize,
    exclude: Option<(&str, &str)>,
) -> Vec<Value> {
    let mut children = Vec::new();
    for slot in &snapshot.slots {
        for option in &slot.options {
            if exclude == Some((&slot.id, &option.id)) {
                continue;
            }
            let Some(region) = snapshot
                .option_regions
                .get(&(slot.id.clone(), option.id.clone()))
            else {
                continue;
            };
            if region.section == entry
                && start <= region.start_paragraph
                && region.end_paragraph <= end
            {
                children.push(json!({"kind": "option", "id": option.id,
                    "label": option.label.as_deref().unwrap_or(&option.id),
                    "count": region.end_paragraph - region.start_paragraph + 1}));
            }
        }
    }
    children
}

fn field_children(
    package: &HwpxPackage,
    entry: &str,
    start: usize,
    end: usize,
) -> Result<Vec<Value>, AuthoringPreviewError> {
    let field_rows = fields(package).map_err(|error| AuthoringPreviewError(error.to_string()))?;
    let mut children = Vec::new();
    for field in field_rows {
        let count = field["occurrences"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|item| {
                item["entry"] == entry
                    && item["paragraph"]
                        .as_u64()
                        .is_some_and(|at| start as u64 <= at && at <= end as u64)
            })
            .count();
        if count > 0 {
            let name = field["name"].as_str().unwrap();
            children.push(json!({"kind": "field", "id": name, "label": name, "count": count}));
        }
    }
    Ok(children)
}

pub fn preview_content_context(
    package: &HwpxPackage,
    command: &Value,
) -> Result<Value, AuthoringPreviewError> {
    let action = command.get("type").and_then(Value::as_str).unwrap_or("");
    if !matches!(
        action,
        "create_slot"
            | "create_option"
            | "adjust_range"
            | "unwrap"
            | "delete"
            | "duplicate"
            | "move"
    ) {
        return Ok(json!({}));
    }
    let slot_id = command.get("slot_id").and_then(Value::as_str).unwrap_or("");
    let on_option = command.get("kind").and_then(Value::as_str) == Some("option");
    let option_id = command.get("option_id").and_then(Value::as_str);
    let snapshot =
        inspect_slot_regions(package).map_err(|error| AuthoringPreviewError(error.to_string()))?;
    let mut target_name = Value::Null;
    let mut prior = None;
    let (mut entry, mut start, mut end) =
        if matches!(action, "create_slot" | "create_option" | "adjust_range") {
            (
                command.get("entry").and_then(Value::as_str),
                command.get("start_paragraph").and_then(Value::as_u64),
                command.get("end_paragraph").and_then(Value::as_u64),
            )
        } else {
            (None, None, None)
        };
    if !matches!(action, "create_slot" | "create_option") {
        target_name = region_name(&snapshot, slot_id, on_option.then_some(option_id).flatten())
            .map_or(Value::Null, Value::String);
        let region = target_region(&snapshot, slot_id, option_id, on_option);
        if action == "adjust_range" {
            prior = region;
            if entry.is_none() {
                entry = region.map(|item| item.section.as_str());
            }
        } else if let Some(region) = region {
            entry = Some(&region.section);
            start = Some(region.start_paragraph as u64);
            end = Some(region.end_paragraph as u64);
        }
    }
    let (Some(entry), Some(start), Some(end)) = (entry, start, end) else {
        return Ok(json!({"target_name": target_name}));
    };
    let (Ok(start), Ok(end)) = (usize::try_from(start), usize::try_from(end)) else {
        return Ok(json!({"target_name": target_name}));
    };
    let Some(source) = package.entries.iter().find(|item| item.name == entry) else {
        return Ok(json!({"target_name": target_name}));
    };
    let view =
        XmlView::parse(&source.data).map_err(|error| AuthoringPreviewError(error.to_string()))?;
    let paragraphs = top_paragraphs(&view);
    if start > end || end >= paragraphs.len() {
        return Ok(json!({"target_name": target_name}));
    }
    let lines: Vec<_> = paragraphs[start..=end]
        .iter()
        .map(|id| paragraph_text(&view, *id))
        .collect();
    let included = lines.join("\n");
    let previous = if let Some(region) = prior {
        paragraphs[region.start_paragraph..=region.end_paragraph]
            .iter()
            .map(|id| paragraph_text(&view, *id))
            .collect::<Vec<_>>()
            .join("\n")
    } else {
        included.clone()
    };
    let exclude = if on_option && !matches!(action, "create_slot" | "create_option") {
        option_id.map(|option| (slot_id, option))
    } else {
        None
    };
    let mut children = option_children(&snapshot, entry, start, end, exclude);
    let options = children.len();
    let fields = field_children(package, entry, start, end)?;
    let field_count: usize = fields
        .iter()
        .map(|field| field["count"].as_u64().unwrap_or(0) as usize)
        .sum();
    children.extend(fields);
    let tables = paragraphs[start..=end]
        .iter()
        .map(|id| {
            view.descendants(*id)
                .unwrap_or_default()
                .into_iter()
                .filter(|child| is_hp(&view, *child, "tbl"))
                .count()
        })
        .sum::<usize>();
    let counts = json!({"paragraphs": end - start + 1, "fields": field_count, "options": options, "tables": tables});
    let detail = format!(
        "\n\n포함: 문단 {}개 · 필드 {}곳 · 하위 영역 {}곳",
        end - start + 1,
        field_count,
        options
    );
    let expanded = matches!(action, "create_slot" | "create_option")
        && (command
            .get("start")
            .and_then(Value::as_i64)
            .is_some_and(|at| at > 0)
            || command
                .get("end")
                .and_then(Value::as_u64)
                .is_some_and(|at| (at as usize) < lines.last().unwrap().chars().count()));
    let after = if action == "delete" {
        "본문과 의미가 삭제됩니다.".into()
    } else {
        format!(
            "{}\n\n{}",
            included,
            command_preview_label(command, true, None)
        )
    };
    Ok(
        json!({"before": format!("{previous}{detail}"), "after": after,
        "included": included.chars().take(500).collect::<String>(), "expanded": expanded,
        "included_location": {"entry": entry, "start_paragraph": start, "end_paragraph": end},
        "children": children, "counts": counts, "target_name": target_name}),
    )
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn create_slot_preview_reports_expanded_paragraph_and_content_count() {
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
        let preview = preview_content_context(&package, &json!({"type": "create_slot", "id": "s", "entry": "Contents/section0.xml", "start_paragraph": 0, "end_paragraph": 0, "start": 1, "end": 1})).unwrap();
        assert_eq!(preview["included"], "본문");
        assert_eq!(
            preview["included_location"],
            json!({"entry": "Contents/section0.xml", "start_paragraph": 0, "end_paragraph": 0})
        );
        assert_eq!(
            preview["counts"],
            json!({"paragraphs": 1, "fields": 0, "options": 0, "tables": 0})
        );
        assert_eq!(preview["expanded"], true);
        assert_eq!(preview["after"], "본문\n\n항목 s");
        assert_eq!(
            command_preview_label(
                &json!({"type": "rename_field", "old_name": null}),
                false,
                None
            ),
            "None"
        );
        assert_eq!(
            command_preview_label(&json!({"type": "create_field"}), false, Some(&json!(0))),
            ""
        );
        assert_eq!(
            command_preview_label(&json!({"type": "create_field"}), false, Some(&json!(["A"]))),
            "['A']"
        );
        assert_eq!(
            command_preview_label(&json!({"type": false}), false, None),
            "False"
        );
    }
}
