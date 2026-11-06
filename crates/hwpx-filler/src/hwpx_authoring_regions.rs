//! Product Slot and Option authoring over guarded native BOOKMARK handles.

use crate::hwpx_product_inspection::{
    inspect_slot_regions, serialize_slot_metatag, serialize_slot_option_metatag,
};
use crate::hwpx_structure_ops::{product_metatag_index, structure_region_name};
use crate::slot::{Slot, SlotOption};
use crate::structure_scan::python_trim;
use hwpx_core::bookmark_region::{
    BookmarkRename, adjust_bookmark_region, append_bookmark_metatag, create_bookmark_region,
    rename_bookmark_regions,
};
use hwpx_core::package::HwpxPackage;
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
    let label = match command.get("label") {
        None | Some(Value::Null) => None,
        Some(Value::String(text)) => Some(text.as_str()),
        _ => {
            return Err(AuthoringRegionError::plain(
                "표시 이름은 텍스트여야 합니다.".into(),
            ));
        }
    };
    let entry = command.get("entry").and_then(Value::as_str);
    let start = integer(command.get("start_paragraph"));
    let end = integer(command.get("end_paragraph"));
    if command
        .get("cell_path")
        .is_some_and(|value| !value.is_null())
    {
        return Err(AuthoringRegionError::plain(
            "표 셀 안에서는 항목·선택을 만들 수 없습니다. 표 밖 문단까지 이어서 고르세요.".into(),
        ));
    }
    let (Some(entry), Some(start), Some(end)) = (entry, start, end) else {
        return Err(AuthoringRegionError::plain(
            "문단 범위를 정확히 고르세요.".into(),
        ));
    };
    let (parent, payload, name) = if option {
        let owner = command
            .get("slot_id")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                AuthoringRegionError::plain("선택을 만들 상위 항목이 필요합니다.".into())
            })?;
        let parent = snapshot.slot_regions.get(owner).ok_or_else(|| {
            AuthoringRegionError::plain("선택을 만들 상위 항목이 필요합니다.".into())
        })?;
        if snapshot
            .option_regions
            .contains_key(&(owner.to_owned(), identifier.to_owned()))
        {
            return Err(AuthoringRegionError::plain(
                "같은 항목에 해당 선택 식별자가 이미 있습니다.".into(),
            ));
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
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
        (
            Some(parent.clone()),
            payload,
            structure_region_name(owner, Some(identifier)),
        )
    } else {
        if snapshot.slot_regions.contains_key(identifier) {
            return Err(AuthoringRegionError::plain(
                "항목 식별자가 이미 있습니다.".into(),
            ));
        }
        let payload = serialize_slot_metatag(&Slot {
            id: identifier.into(),
            options: Vec::new(),
            label: label.map(str::to_owned),
        })
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
        (None, payload, structure_region_name(identifier, None))
    };
    let original = package
        .entries
        .iter()
        .find(|item| item.name == entry)
        .map(|item| item.data.clone());
    let created = match create_bookmark_region(package, entry, start, end, &name, parent.as_ref()) {
        Ok(created) => created,
        Err(error) => {
            if let Some(original) = original {
                package
                    .entries
                    .iter_mut()
                    .find(|item| item.name == entry)
                    .unwrap()
                    .data = original;
            }
            return Err(AuthoringRegionError::plain(error.to_string()));
        }
    };
    if let Err(error) = append_bookmark_metatag(package, &created, &payload) {
        if let Some(original) = original {
            package
                .entries
                .iter_mut()
                .find(|item| item.name == entry)
                .unwrap()
                .data = original;
        }
        return Err(AuthoringRegionError::plain(error.to_string()));
    }
    Ok(())
}

pub fn rename_region(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<(), AuthoringRegionError> {
    let snapshot = clean_snapshot(package)?;
    let option = command.get("type").and_then(Value::as_str) == Some("rename_option");
    let slot_id = command
        .get("slot_id")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            AuthoringRegionError::plain("항목이나 선택의 식별자가 필요합니다.".into())
        })?;
    let option_id = if option {
        Some(
            command
                .get("option_id")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    AuthoringRegionError::plain("항목이나 선택의 식별자가 필요합니다.".into())
                })?,
        )
    } else {
        None
    };
    let region = if let Some(option_id) = option_id {
        snapshot
            .option_regions
            .get(&(slot_id.to_owned(), option_id.to_owned()))
    } else {
        snapshot.slot_regions.get(slot_id)
    }
    .ok_or_else(|| AuthoringRegionError::plain("항목이나 선택 영역을 찾을 수 없습니다.".into()))?;
    let identifier = match command.get("id") {
        None => option_id.unwrap_or(slot_id),
        Some(value) => value.as_str().unwrap_or(""),
    };
    if python_trim(identifier).is_empty() {
        return Err(AuthoringRegionError::invalid_identifier(
            "항목이나 선택의 새 식별자를 입력하세요.",
        ));
    }
    let label = match command.get("label") {
        None => None,
        Some(Value::Null) => Some(None),
        Some(Value::String(text)) => Some(Some(text.as_str())),
        _ => {
            return Err(AuthoringRegionError::plain(
                "표시 이름은 텍스트여야 합니다.".into(),
            ));
        }
    };
    let payload = if let Some(option_id) = option_id {
        if identifier != option_id
            && snapshot
                .option_regions
                .contains_key(&(slot_id.to_owned(), identifier.to_owned()))
        {
            return Err(AuthoringRegionError::plain(
                "같은 항목에 해당 선택 식별자가 이미 있습니다.".into(),
            ));
        }
        let previous = snapshot
            .slots
            .iter()
            .find(|slot| slot.id == slot_id)
            .and_then(|slot| slot.options.iter().find(|option| option.id == option_id))
            .ok_or_else(|| {
                AuthoringRegionError::plain("항목이나 선택 영역을 찾을 수 없습니다.".into())
            })?;
        serialize_slot_option_metatag(&SlotOption {
            id: identifier.into(),
            order: previous.order,
            label: label.map_or_else(|| previous.label.clone(), |value| value.map(str::to_owned)),
        })
    } else {
        if identifier != slot_id && snapshot.slot_regions.contains_key(identifier) {
            return Err(AuthoringRegionError::plain(
                "항목 식별자가 이미 있습니다.".into(),
            ));
        }
        let previous = snapshot
            .slots
            .iter()
            .find(|slot| slot.id == slot_id)
            .ok_or_else(|| {
                AuthoringRegionError::plain("항목이나 선택 영역을 찾을 수 없습니다.".into())
            })?;
        serialize_slot_metatag(&Slot {
            id: identifier.into(),
            options: previous.options.clone(),
            label: label.map_or_else(|| previous.label.clone(), |value| value.map(str::to_owned)),
        })
    }
    .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
    let index = product_metatag_index(region)
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
    let new_name = structure_region_name(
        if option { slot_id } else { identifier },
        option.then_some(identifier),
    );
    let mut names = Vec::new();
    if !option
        && identifier != slot_id
        && let Some(previous) = snapshot.slots.iter().find(|slot| slot.id == slot_id)
    {
        let source = package
            .entries
            .iter()
            .find(|entry| entry.name == region.section)
            .ok_or_else(|| {
                AuthoringRegionError::plain("하위 선택 책갈피를 하나로 확정할 수 없습니다.".into())
            })?;
        let view = hwpx_core::xml_view::XmlView::parse(&source.data)
            .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
        for child in &previous.options {
            let old_name = structure_region_name(slot_id, Some(&child.id));
            let matches = view
                .descendants(view.root())
                .unwrap()
                .into_iter()
                .filter(|id| {
                    view.node(*id).is_some_and(|node| {
                        node.name.is(hwpx_core::text_model::HP_NS, "fieldBegin")
                    }) && view.attr(*id, "type") == Some("BOOKMARK")
                        && view.attr(*id, "name") == Some(old_name.as_str())
                })
                .count();
            if matches != 1 {
                return Err(AuthoringRegionError::plain(
                    "하위 선택 책갈피를 하나로 확정할 수 없습니다.".into(),
                ));
            }
            let child_region = snapshot
                .option_regions
                .get(&(slot_id.to_owned(), child.id.clone()))
                .ok_or_else(|| {
                    AuthoringRegionError::plain(
                        "하위 선택 책갈피를 하나로 확정할 수 없습니다.".into(),
                    )
                })?;
            if child_region.section != region.section {
                return Err(AuthoringRegionError::plain(
                    "하위 선택 책갈피를 하나로 확정할 수 없습니다.".into(),
                ));
            }
            names.push((
                child_region,
                structure_region_name(identifier, Some(&child.id)),
            ));
        }
    }
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
    rename_bookmark_regions(package, &edits)
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))
}

pub fn adjust_region(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<(), AuthoringRegionError> {
    let snapshot = clean_snapshot(package)?;
    let option = command.get("kind").and_then(Value::as_str) == Some("option");
    let slot_id = command
        .get("slot_id")
        .and_then(Value::as_str)
        .ok_or_else(|| AuthoringRegionError::plain("항목 식별자가 필요합니다.".into()))?;
    let option_id = if option {
        Some(
            command
                .get("option_id")
                .and_then(Value::as_str)
                .ok_or_else(|| AuthoringRegionError::plain("선택 식별자가 필요합니다.".into()))?,
        )
    } else {
        None
    };
    let region = if let Some(option_id) = option_id {
        snapshot
            .option_regions
            .get(&(slot_id.to_owned(), option_id.to_owned()))
    } else {
        snapshot.slot_regions.get(slot_id)
    }
    .ok_or_else(|| AuthoringRegionError::plain("항목이나 선택 영역을 찾을 수 없습니다.".into()))?;
    let start = signed_integer(command.get("start_paragraph"));
    let end = signed_integer(command.get("end_paragraph"));
    let (Some(start), Some(end)) = (start, end) else {
        return Err(AuthoringRegionError::plain(
            "문단 범위를 정확히 고르세요.".into(),
        ));
    };
    if start > end {
        return Err(AuthoringRegionError::plain(
            "문단 범위를 정확히 고르세요.".into(),
        ));
    }
    let len = package
        .entries
        .iter()
        .find(|entry| entry.name == region.section)
        .ok_or_else(|| {
            AuthoringRegionError::plain("항목이나 선택 영역을 찾을 수 없습니다.".into())
        })?;
    let view = hwpx_core::xml_view::XmlView::parse(&len.data)
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))?;
    let paragraphs: Vec<_> = view
        .node(view.root())
        .unwrap()
        .children
        .iter()
        .filter_map(|part| match part {
            hwpx_core::xml_view::Content::Element(id)
                if view
                    .node(*id)
                    .is_some_and(|node| node.name.is(hwpx_core::text_model::HP_NS, "p")) =>
            {
                Some(*id)
            }
            _ => None,
        })
        .collect();
    if start < 0 || end >= paragraphs.len() as i128 {
        return Err(AuthoringRegionError::plain(
            "고른 문단 범위가 문서 영역 밖에 있습니다.".into(),
        ));
    }
    let (start, end) = (start as usize, end as usize);
    if [paragraphs[start], paragraphs[end]].iter().any(|paragraph| {
        !view.node(*paragraph).unwrap().children.iter().any(|part| {
            matches!(part, hwpx_core::xml_view::Content::Element(id) if view.node(*id).is_some_and(|node| node.name.is(hwpx_core::text_model::HP_NS, "run")))
        })
    }) {
        return Err(AuthoringRegionError::plain("경계 문단에 편집 가능한 텍스트 런이 없습니다.".into()));
    }
    if option {
        let owner = snapshot.slot_regions.get(slot_id).ok_or_else(|| {
            AuthoringRegionError::plain("항목이나 선택 영역을 찾을 수 없습니다.".into())
        })?;
        if start < owner.start_paragraph || end > owner.end_paragraph {
            return Err(AuthoringRegionError::plain(
                "고른 범위는 상위 항목 안에 있어야 합니다.".into(),
            ));
        }
    } else if snapshot.option_regions.iter().any(|((owner, _), child)| {
        owner == slot_id && (start > child.start_paragraph || end < child.end_paragraph)
    }) {
        return Err(AuthoringRegionError::plain(
            "조정한 항목 범위에서 하위 선택이 벗어납니다.".into(),
        ));
    }
    adjust_bookmark_region(package, region, start, end)
        .map_err(|error| AuthoringRegionError::plain(error.to_string()))
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
