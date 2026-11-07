//! Product Slot and Option authoring over guarded native BOOKMARK handles.

use crate::hwpx_product_inspection::{
    inspect_slot_regions, serialize_slot_metatag, serialize_slot_option_metatag,
};
use crate::hwpx_structure_ops::{product_metatag_index, structure_region_name};
use crate::slot::{Slot, SlotOption};
use crate::structure_scan::python_trim;
use hwpx_core::bookmark_region::{
    BookmarkRegion, BookmarkRename, adjust_bookmark_region, append_bookmark_metatag,
    create_bookmark_region, rename_bookmark_regions,
};
use hwpx_core::package::HwpxPackage;
use hwpx_core::xml_view::Content;
use serde_json::{Value, json};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringRegionError(pub String, pub Option<Value>);
impl AuthoringRegionError {
    pub(crate) fn plain(message: String) -> Self {
        Self(message, None)
    }
    fn invalid_identifier(message: &str) -> Self {
        Self(
            message.into(),
            Some(json!({"code":"invalid_name","field":"identifier","message":message})),
        )
    }
    pub fn to_dict(&self) -> Option<&Value> {
        self.1.as_ref()
    }
}
impl fmt::Display for AuthoringRegionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AuthoringRegionError {}

fn integer(value: Option<&Value>) -> Option<usize> {
    match value? {
        Value::Bool(flag) => Some(usize::from(*flag)),
        Value::Number(number) => number
            .as_u64()
            .and_then(|value| usize::try_from(value).ok()),
        _ => None,
    }
}

fn signed_integer(value: Option<&Value>) -> Option<i128> {
    match value? {
        Value::Bool(flag) => Some(i128::from(*flag)),
        Value::Number(number) if number.is_i64() => number.as_i64().map(i128::from),
        Value::Number(number) if number.is_u64() => number.as_u64().map(i128::from),
        _ => None,
    }
}

fn clean_snapshot(
    package: &HwpxPackage,
) -> Result<crate::hwpx_product_inspection::SlotSnapshot, AuthoringRegionError> {
    let snapshot = inspect_slot_regions(package)
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
    if !snapshot.diagnostics.is_empty() {
        return Err(AuthoringRegionError::plain(
            "문서 구조 오류를 먼저 수정하세요.".into(),
        ));
    }
    Ok(snapshot)
}

fn plain(message: &str) -> AuthoringRegionError {
    AuthoringRegionError::plain(message.into())
}

fn native(error: impl fmt::Display) -> AuthoringRegionError {
    AuthoringRegionError::plain(error.to_string())
}

const REGION_MISSING: &str = "항목이나 선택 영역을 찾을 수 없습니다.";
const LABEL_NOT_TEXT: &str = "표시 이름은 텍스트여야 합니다.";
const PARAGRAPH_RANGE: &str = "문단 범위를 정확히 고르세요.";
const CHILD_UNRESOLVED: &str = "하위 선택 책갈피를 하나로 확정할 수 없습니다.";

/// Runs a native edit of one entry; if it fails, that entry gets its prior bytes back.
fn restoring_entry(
    package: &mut HwpxPackage,
    entry: &str,
    action: impl FnOnce(&mut HwpxPackage) -> Result<(), AuthoringRegionError>,
) -> Result<(), AuthoringRegionError> {
    let original = package
        .entries
        .iter()
        .find(|item| item.name == entry)
        .map(|item| item.data.clone());
    let result = action(package);
    if result.is_err()
        && let Some(original) = original
    {
        package
            .entries
            .iter_mut()
            .find(|item| item.name == entry)
            .unwrap()
            .data = original;
    }
    result
}

/// The slot id and, for an option command, the option id the command names.
fn region_ids<'a>(
    command: &'a Value,
    option: bool,
    missing_slot: &str,
    missing_option: &str,
) -> Result<(&'a str, Option<&'a str>), AuthoringRegionError> {
    let text = |key: &str, missing: &str| {
        command
            .get(key)
            .and_then(Value::as_str)
            .ok_or_else(|| plain(missing))
    };
    let slot_id = text("slot_id", missing_slot)?;
    let option_id = if option {
        Some(text("option_id", missing_option)?)
    } else {
        None
    };
    Ok((slot_id, option_id))
}

fn find_region<'a>(
    snapshot: &'a crate::hwpx_product_inspection::SlotSnapshot,
    slot_id: &str,
    option_id: Option<&str>,
) -> Result<&'a BookmarkRegion, AuthoringRegionError> {
    if let Some(option_id) = option_id {
        snapshot
            .option_regions
            .get(&(slot_id.to_owned(), option_id.to_owned()))
    } else {
        snapshot.slot_regions.get(slot_id)
    }
    .ok_or_else(|| plain(REGION_MISSING))
}

fn new_region_label(command: &Value) -> Result<Option<&str>, AuthoringRegionError> {
    match command.get("label") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) => Ok(Some(text.as_str())),
        _ => Err(plain(LABEL_NOT_TEXT)),
    }
}

/// The entry and paragraph range a new region spans; table cells are refused.
fn new_region_span(command: &Value) -> Result<(&str, usize, usize), AuthoringRegionError> {
    let entry = command.get("entry").and_then(Value::as_str);
    let start = integer(command.get("start_paragraph"));
    let end = integer(command.get("end_paragraph"));
    if command
        .get("cell_path")
        .is_some_and(|value| !value.is_null())
    {
        return Err(plain(
            "표 셀 안에서는 항목·선택을 만들 수 없습니다. 표 밖 문단까지 이어서 고르세요.",
        ));
    }
    let (Some(entry), Some(start), Some(end)) = (entry, start, end) else {
        return Err(plain(PARAGRAPH_RANGE));
    };
    Ok((entry, start, end))
}

/// The new region's parent bookmark, metatag payload, and bookmark name.
type NewRegion = (Option<BookmarkRegion>, String, String);

fn new_option_region(
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
    command: &Value,
    identifier: &str,
    label: Option<&str>,
) -> Result<NewRegion, AuthoringRegionError> {
    let owner = command
        .get("slot_id")
        .and_then(Value::as_str)
        .ok_or_else(|| plain("선택을 만들 상위 항목이 필요합니다."))?;
    let parent = snapshot
        .slot_regions
        .get(owner)
        .ok_or_else(|| plain("선택을 만들 상위 항목이 필요합니다."))?;
    if snapshot
        .option_regions
        .contains_key(&(owner.to_owned(), identifier.to_owned()))
    {
        return Err(plain("같은 항목에 해당 선택 식별자가 이미 있습니다."));
    }
    let order = snapshot
        .slots
        .iter()
        .find(|slot| slot.id == owner)
        .unwrap()
        .options
        .len();
    let payload = serialize_slot_option_metatag(&SlotOption {
        id: identifier.into(),
        order,
        label: label.map(str::to_owned),
    })
    .map_err(native)?;
    Ok((
        Some(parent.clone()),
        payload,
        structure_region_name(owner, Some(identifier)),
    ))
}

fn new_slot_region(
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
    identifier: &str,
    label: Option<&str>,
) -> Result<NewRegion, AuthoringRegionError> {
    if snapshot.slot_regions.contains_key(identifier) {
        return Err(plain("항목 식별자가 이미 있습니다."));
    }
    let payload = serialize_slot_metatag(&Slot {
        id: identifier.into(),
        options: Vec::new(),
        label: label.map(str::to_owned),
    })
    .map_err(native)?;
    Ok((None, payload, structure_region_name(identifier, None)))
}

pub fn create_region(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<(), AuthoringRegionError> {
    let snapshot = clean_snapshot(package)?;
    let option = command.get("type").and_then(Value::as_str) == Some("create_option");
    let identifier = command
        .get("id")
        .and_then(Value::as_str)
        .filter(|value| !python_trim(value).is_empty())
        .ok_or_else(|| {
            AuthoringRegionError::invalid_identifier("항목이나 선택의 식별자를 입력하세요.")
        })?;
    let label = new_region_label(command)?;
    let (entry, start, end) = new_region_span(command)?;
    let (parent, payload, name) = if option {
        new_option_region(&snapshot, command, identifier, label)?
    } else {
        new_slot_region(&snapshot, identifier, label)?
    };
    restoring_entry(package, entry, |package| {
        let created = create_bookmark_region(package, entry, start, end, &name, parent.as_ref())
            .map_err(native)?;
        append_bookmark_metatag(package, &created, &payload).map_err(native)
    })
}

/// The rename's label: `None` keeps the current one, `Some(None)` clears it.
fn rename_label(command: &Value) -> Result<Option<Option<&str>>, AuthoringRegionError> {
    match command.get("label") {
        None => Ok(None),
        Some(Value::Null) => Ok(Some(None)),
        Some(Value::String(text)) => Ok(Some(Some(text.as_str()))),
        _ => Err(plain(LABEL_NOT_TEXT)),
    }
}

fn renamed_label(label: Option<Option<&str>>, previous: &Option<String>) -> Option<String> {
    label.map_or_else(|| previous.clone(), |value| value.map(str::to_owned))
}

fn renamed_option_payload(
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
    ids: (&str, &str),
    identifier: &str,
    label: Option<Option<&str>>,
) -> Result<String, AuthoringRegionError> {
    let (slot_id, option_id) = ids;
    if identifier != option_id
        && snapshot
            .option_regions
            .contains_key(&(slot_id.to_owned(), identifier.to_owned()))
    {
        return Err(plain("같은 항목에 해당 선택 식별자가 이미 있습니다."));
    }
    let previous = snapshot
        .slots
        .iter()
        .find(|slot| slot.id == slot_id)
        .and_then(|slot| slot.options.iter().find(|option| option.id == option_id))
        .ok_or_else(|| plain(REGION_MISSING))?;
    serialize_slot_option_metatag(&SlotOption {
        id: identifier.into(),
        order: previous.order,
        label: renamed_label(label, &previous.label),
    })
    .map_err(native)
}

fn renamed_slot_payload(
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
    slot_id: &str,
    identifier: &str,
    label: Option<Option<&str>>,
) -> Result<String, AuthoringRegionError> {
    if identifier != slot_id && snapshot.slot_regions.contains_key(identifier) {
        return Err(plain("항목 식별자가 이미 있습니다."));
    }
    let previous = snapshot
        .slots
        .iter()
        .find(|slot| slot.id == slot_id)
        .ok_or_else(|| plain(REGION_MISSING))?;
    serialize_slot_metatag(&Slot {
        id: identifier.into(),
        options: previous.options.clone(),
        label: renamed_label(label, &previous.label),
    })
    .map_err(native)
}

fn bookmark_begin_count(view: &hwpx_core::xml_view::XmlView, name: &str) -> usize {
    view.descendants(view.root())
        .unwrap()
        .into_iter()
        .filter(|id| {
            view.node(*id)
                .is_some_and(|node| node.name.is(hwpx_core::text_model::HP_NS, "fieldBegin"))
                && view.attr(*id, "type") == Some("BOOKMARK")
                && view.attr(*id, "name") == Some(name)
        })
        .count()
}

/// Bookmark renames that carry a renamed slot's options to the new slot id.
fn child_option_renames<'a>(
    package: &HwpxPackage,
    snapshot: &'a crate::hwpx_product_inspection::SlotSnapshot,
    region: &BookmarkRegion,
    slot_id: &str,
    identifier: &str,
) -> Result<Vec<(&'a BookmarkRegion, String)>, AuthoringRegionError> {
    let Some(previous) = snapshot.slots.iter().find(|slot| slot.id == slot_id) else {
        return Ok(Vec::new());
    };
    let source = package
        .entries
        .iter()
        .find(|entry| entry.name == region.section)
        .ok_or_else(|| plain(CHILD_UNRESOLVED))?;
    let view = hwpx_core::xml_view::XmlView::parse(&source.data).map_err(native)?;
    let mut names = Vec::new();
    for child in &previous.options {
        let old_name = structure_region_name(slot_id, Some(&child.id));
        if bookmark_begin_count(&view, &old_name) != 1 {
            return Err(plain(CHILD_UNRESOLVED));
        }
        let child_region = snapshot
            .option_regions
            .get(&(slot_id.to_owned(), child.id.clone()))
            .filter(|child_region| child_region.section == region.section)
            .ok_or_else(|| plain(CHILD_UNRESOLVED))?;
        names.push((
            child_region,
            structure_region_name(identifier, Some(&child.id)),
        ));
    }
    Ok(names)
}

pub fn rename_region(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<(), AuthoringRegionError> {
    let snapshot = clean_snapshot(package)?;
    let option = command.get("type").and_then(Value::as_str) == Some("rename_option");
    let missing = "항목이나 선택의 식별자가 필요합니다.";
    let (slot_id, option_id) = region_ids(command, option, missing, missing)?;
    let region = find_region(&snapshot, slot_id, option_id)?;
    let identifier = match command.get("id") {
        None => option_id.unwrap_or(slot_id),
        Some(value) => value.as_str().unwrap_or(""),
    };
    if python_trim(identifier).is_empty() {
        return Err(AuthoringRegionError::invalid_identifier(
            "항목이나 선택의 새 식별자를 입력하세요.",
        ));
    }
    let label = rename_label(command)?;
    let payload = match option_id {
        Some(option_id) => {
            renamed_option_payload(&snapshot, (slot_id, option_id), identifier, label)?
        }
        None => renamed_slot_payload(&snapshot, slot_id, identifier, label)?,
    };
    let index = product_metatag_index(region).map_err(native)?;
    let new_name = structure_region_name(
        if option { slot_id } else { identifier },
        option.then_some(identifier),
    );
    let names = if !option && identifier != slot_id {
        child_option_renames(package, &snapshot, region, slot_id, identifier)?
    } else {
        Vec::new()
    };
    let mut edits = vec![BookmarkRename {
        region,
        name: &new_name,
        metatag: Some((index, &payload)),
    }];
    edits.extend(names.iter().map(|(region, name)| BookmarkRename {
        region,
        name,
        metatag: None,
    }));
    rename_bookmark_regions(package, &edits).map_err(native)
}

/// The requested inclusive paragraph range, possibly negative until bounds are known.
fn adjusted_range(command: &Value) -> Result<(i128, i128), AuthoringRegionError> {
    let start = signed_integer(command.get("start_paragraph"));
    let end = signed_integer(command.get("end_paragraph"));
    match (start, end) {
        (Some(start), Some(end)) if start <= end => Ok((start, end)),
        _ => Err(plain(PARAGRAPH_RANGE)),
    }
}

fn is_hp_element(view: &hwpx_core::xml_view::XmlView, part: &Content, name: &str) -> bool {
    matches!(part, Content::Element(id)
        if view.node(*id).is_some_and(|node| node.name.is(hwpx_core::text_model::HP_NS, name)))
}

fn section_paragraphs(view: &hwpx_core::xml_view::XmlView) -> Vec<hwpx_core::xml_view::NodeId> {
    view.node(view.root())
        .unwrap()
        .children
        .iter()
        .filter_map(|part| match part {
            Content::Element(id) if is_hp_element(view, part, "p") => Some(*id),
            _ => None,
        })
        .collect()
}

/// Refuses a range that leaves the owner slot, or a slot range that drops its options.
fn containment_refusal(
    snapshot: &crate::hwpx_product_inspection::SlotSnapshot,
    ids: (&str, Option<&str>),
    start: usize,
    end: usize,
) -> Result<(), AuthoringRegionError> {
    let (slot_id, option_id) = ids;
    if option_id.is_some() {
        let owner = snapshot
            .slot_regions
            .get(slot_id)
            .ok_or_else(|| plain(REGION_MISSING))?;
        if start < owner.start_paragraph || end > owner.end_paragraph {
            return Err(plain("고른 범위는 상위 항목 안에 있어야 합니다."));
        }
    } else if snapshot.option_regions.iter().any(|((owner, _), child)| {
        owner == slot_id && (start > child.start_paragraph || end < child.end_paragraph)
    }) {
        return Err(plain("조정한 항목 범위에서 하위 선택이 벗어납니다."));
    }
    Ok(())
}

pub fn adjust_region(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<(), AuthoringRegionError> {
    let snapshot = clean_snapshot(package)?;
    let option = command.get("kind").and_then(Value::as_str) == Some("option");
    let ids = region_ids(
        command,
        option,
        "항목 식별자가 필요합니다.",
        "선택 식별자가 필요합니다.",
    )?;
    let region = find_region(&snapshot, ids.0, ids.1)?;
    let (start, end) = adjusted_range(command)?;
    let len = package
        .entries
        .iter()
        .find(|entry| entry.name == region.section)
        .ok_or_else(|| plain(REGION_MISSING))?;
    let view = hwpx_core::xml_view::XmlView::parse(&len.data).map_err(native)?;
    let paragraphs = section_paragraphs(&view);
    if start < 0 || end >= paragraphs.len() as i128 {
        return Err(plain("고른 문단 범위가 문서 영역 밖에 있습니다."));
    }
    let (start, end) = (start as usize, end as usize);
    if [paragraphs[start], paragraphs[end]]
        .iter()
        .any(|paragraph| {
            !view
                .node(*paragraph)
                .unwrap()
                .children
                .iter()
                .any(|part| is_hp_element(&view, part, "run"))
        })
    {
        return Err(plain("경계 문단에 편집 가능한 텍스트 런이 없습니다."));
    }
    containment_refusal(&snapshot, ids, start, end)?;
    adjust_bookmark_region(package, region, start, end).map_err(native)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_core::bookmark_region::create_bookmark_region;
    use hwpx_core::package::PackageEntry;
    use hwpx_core::text_model::HP_NS;
    use serde_json::json;

    #[test]
    fn creates_slot_then_option_and_refuses_duplicate_without_mutation() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{}</hs:sec>",
            (0..5)
                .map(|at| format!("<hp:p><hp:run><hp:t>{at}</hp:t></hp:run></hp:p>"))
                .collect::<String>()
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let invalid = create_region(&mut package, &json!({"type":"create_slot","id":"","entry":"Contents/section0.xml","start_paragraph":0,"end_paragraph":1})).unwrap_err();
        assert_eq!(
            invalid.to_dict(),
            Some(
                &json!({"code":"invalid_name","field":"identifier","message":"항목이나 선택의 식별자를 입력하세요."})
            )
        );
        create_region(&mut package, &json!({"type": "create_slot", "id": "s", "label": "항목", "entry": "Contents/section0.xml", "start_paragraph": 0, "end_paragraph": 4})).unwrap();
        create_region(&mut package, &json!({"type": "create_option", "id": "a", "label": "선택", "slot_id": "s", "entry": "Contents/section0.xml", "start_paragraph": 1, "end_paragraph": 1})).unwrap();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert!(snapshot.diagnostics.is_empty());
        assert_eq!(snapshot.slots.len(), 1);
        assert_eq!(snapshot.slots[0].options[0].id, "a");
        let stable = package.clone();
        assert!(create_region(&mut package, &json!({"type": "create_option", "id": "a", "slot_id": "s", "entry": "Contents/section0.xml", "start_paragraph": 1, "end_paragraph": 1})).is_err());
        assert_eq!(package, stable);
        adjust_region(&mut package, &json!({"kind": "option", "slot_id": "s", "option_id": "a", "start_paragraph": 2, "end_paragraph": 3})).unwrap();
        adjust_region(
            &mut package,
            &json!({"kind": "slot", "slot_id": "s", "start_paragraph": 1, "end_paragraph": 4}),
        )
        .unwrap();
        let mut ambiguous = package.clone();
        let owner = inspect_slot_regions(&ambiguous).unwrap().slot_regions["s"].clone();
        create_bookmark_region(
            &mut ambiguous,
            "Contents/section0.xml",
            4,
            4,
            "s/a",
            Some(&owner),
        )
        .unwrap();
        let before = ambiguous.clone();
        assert_eq!(
            rename_region(
                &mut ambiguous,
                &json!({"type": "rename_slot", "slot_id": "s", "id": "renamed"})
            )
            .unwrap_err()
            .0,
            "하위 선택 책갈피를 하나로 확정할 수 없습니다."
        );
        assert_eq!(ambiguous, before);
        rename_region(
            &mut package,
            &json!({"type": "rename_slot", "slot_id": "s", "id": "renamed", "label": "새 항목"}),
        )
        .unwrap();
        rename_region(&mut package, &json!({"type": "rename_option", "slot_id": "renamed", "option_id": "a", "id": "changed", "label": "새 선택"})).unwrap();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert!(snapshot.diagnostics.is_empty());
        assert_eq!(snapshot.slots[0].id, "renamed");
        assert_eq!(snapshot.slots[0].label.as_deref(), Some("새 항목"));
        assert_eq!(snapshot.slots[0].options[0].id, "changed");
        assert_eq!(
            snapshot.slots[0].options[0].label.as_deref(),
            Some("새 선택")
        );
        assert_eq!(snapshot.slot_regions["renamed"].start_paragraph, 1);
        assert_eq!(
            snapshot.option_regions[&("renamed".into(), "changed".into())].start_paragraph,
            2
        );
        let stable = package.clone();
        assert!(adjust_region(&mut package, &json!({"kind": "slot", "slot_id": "renamed", "start_paragraph": 3, "end_paragraph": 4})).is_err());
        assert_eq!(package, stable);
        let mut no_run = package.clone();
        let source = String::from_utf8(no_run.entries[0].data.clone()).unwrap();
        no_run.entries[0].data = source.replace("</hs:sec>", "<hp:p/></hs:sec>").into_bytes();
        let before = no_run.clone();
        assert_eq!(adjust_region(&mut no_run, &json!({"kind": "slot", "slot_id": "renamed", "start_paragraph": 1, "end_paragraph": 5})).unwrap_err().0, "경계 문단에 편집 가능한 텍스트 런이 없습니다.");
        assert_eq!(no_run, before);
    }
}
