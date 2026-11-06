//! Whole native paragraph blocks used by Slot and Option authoring.

use crate::hwpx_authoring_regions::AuthoringRegionError;
use crate::hwpx_product_inspection::{SlotSnapshot, inspect_slot_regions};
use crate::hwpx_structure_ops::{product_metatag_index, structure_region_name};
use crate::structure_scan::python_trim;
use hwpx_core::bookmark_region::{
    BookmarkCloneNames, duplicate_bookmark_block, move_bookmark_block,
};
use hwpx_core::package::HwpxPackage;
use hwpx_core::text_model::HP_NS;
use hwpx_core::xml_view::{Content, XmlView};
use serde_json::Value;

fn error(message: impl Into<String>) -> AuthoringRegionError {
    AuthoringRegionError::plain(message.into())
}

fn integer(value: Option<&Value>) -> Option<usize> {
    match value? {
        Value::Bool(flag) => Some(usize::from(*flag)),
        Value::Number(value) => value.as_u64().and_then(|value| usize::try_from(value).ok()),
        _ => None,
    }
}

fn top_level_paragraphs(package: &HwpxPackage, entry: &str) -> Result<usize, AuthoringRegionError> {
    let raw = package
        .entries
        .iter()
        .find(|item| item.name == entry)
        .ok_or_else(|| error("영역을 찾을 수 없습니다."))?;
    let view = XmlView::parse(&raw.data).map_err(|item| error(item.to_string()))?;
    Ok(view
        .node(view.root())
        .unwrap()
        .children
        .iter()
        .filter_map(|item| match item {
            Content::Element(id) => view.node(*id),
            _ => None,
        })
        .filter(|node| node.name.is(HP_NS, "p"))
        .count())
}

pub fn move_region(package: &mut HwpxPackage, command: &Value) -> Result<(), AuthoringRegionError> {
    let snapshot = inspect_slot_regions(package).map_err(|item| error(item.to_string()))?;
    if !snapshot.diagnostics.is_empty() {
        return Err(error("구조 오류가 있어 영역을 변경할 수 없습니다."));
    }
    let option = command.get("kind").and_then(Value::as_str) == Some("option");
    let slot_id = command
        .get("slot_id")
        .and_then(Value::as_str)
        .ok_or_else(|| error("항목 식별자가 필요합니다."))?;
    let region = if option {
        let option_id = command
            .get("option_id")
            .and_then(Value::as_str)
            .ok_or_else(|| error("선택 식별자가 필요합니다."))?;
        snapshot
            .option_regions
            .get(&(slot_id.to_owned(), option_id.to_owned()))
    } else {
        snapshot.slot_regions.get(slot_id)
    }
    .ok_or_else(|| error("영역을 찾을 수 없습니다."))?;
    if command
        .get("destination_entry")
        .is_some_and(|value| value.as_str() != Some(&region.section))
    {
        return Err(error("다른 문서 영역으로는 이동할 수 없습니다."));
    }
    if command
        .get("start")
        .is_some_and(|value| !(value.as_i64() == Some(0) || value == &Value::Bool(false)))
    {
        return Err(error("이동할 위치를 문단 시작에 놓으세요."));
    }
    let destination = integer(command.get("destination_paragraph"));
    let count = top_level_paragraphs(package, &region.section)?;
    let Some(destination) = destination.filter(|at| *at <= count) else {
        return Err(error("이동할 문단 경계가 올바르지 않습니다."));
    };
    if (region.start_paragraph..=region.end_paragraph + 1).contains(&destination) {
        return Err(error("현재 영역 안으로 이동할 수 없습니다."));
    }
    move_bookmark_block(package, region, destination).map_err(|item| error(item.to_string()))
}

pub fn duplicate_region(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<(), AuthoringRegionError> {
    let snapshot = inspect_slot_regions(package).map_err(|item| error(item.to_string()))?;
    if !snapshot.diagnostics.is_empty() {
        return Err(error("구조 오류가 있어 영역을 변경할 수 없습니다."));
    }
    let option = command.get("kind").and_then(Value::as_str) == Some("option");
    let slot_id = command
        .get("slot_id")
        .and_then(Value::as_str)
        .ok_or_else(|| error("항목 식별자가 필요합니다."))?;
    let region = if option {
        let option_id = command
            .get("option_id")
            .and_then(Value::as_str)
            .ok_or_else(|| error("선택 식별자가 필요합니다."))?;
        snapshot
            .option_regions
            .get(&(slot_id.to_owned(), option_id.to_owned()))
    } else {
        snapshot.slot_regions.get(slot_id)
    }
    .ok_or_else(|| error("영역을 찾을 수 없습니다."))?;
    if command
        .get("destination_entry")
        .is_some_and(|value| value.as_str() != Some(&region.section))
    {
        return Err(error("다른 문서 영역으로는 복제할 수 없습니다."));
    }
    if command
        .get("start")
        .is_some_and(|value| !(value.as_i64() == Some(0) || value == &Value::Bool(false)))
    {
        return Err(error("복제할 위치를 문단 시작에 놓으세요."));
    }
    let new_id = command
        .get("new_id")
        .and_then(Value::as_str)
        .filter(|value| !python_trim(value).is_empty())
        .ok_or_else(|| error("복제할 영역의 새 식별자가 필요합니다."))?;
    let destination = match command.get("destination_paragraph") {
        None => Some(region.end_paragraph + 1),
        value => integer(value),
    };
    let count = top_level_paragraphs(package, &region.section)?;
    let Some(destination) = destination.filter(|at| *at <= count) else {
        return Err(error("복제할 문단 경계가 올바르지 않습니다."));
    };
    validate_clone_destination(&snapshot, slot_id, option, new_id, destination)?;
    let index = product_metatag_index(region).map_err(|item| error(item.to_string()))?;
    let mut payload: Value =
        serde_json::from_str(&region.meta_tags[index]).map_err(|item| error(item.to_string()))?;
    payload["hwpxFiller"]["id"] = Value::String(new_id.into());
    let payload = serde_json::to_string(&payload).map_err(|item| error(item.to_string()))?;
    let name = structure_region_name(
        if option { slot_id } else { new_id },
        option.then_some(new_id),
    );
    let old_prefix = format!("{slot_id}/");
    let new_prefix = format!("{new_id}/");
    duplicate_bookmark_block(
        package,
        region,
        destination,
        BookmarkCloneNames {
            name: &name,
            metatag: Some((index, &payload)),
            child_prefix: (!option).then_some((&old_prefix, &new_prefix)),
        },
    )
    .map_err(|item| error(item.to_string()))
}

fn validate_clone_destination(
    snapshot: &SlotSnapshot,
    slot_id: &str,
    option: bool,
    new_id: &str,
    destination: usize,
) -> Result<(), AuthoringRegionError> {
    if option {
        let owner = snapshot
            .slot_regions
            .get(slot_id)
            .ok_or_else(|| error("영역을 찾을 수 없습니다."))?;
        if destination < owner.start_paragraph || destination > owner.end_paragraph + 1 {
            return Err(error("복제한 선택은 같은 항목 안에 놓아야 합니다."));
        }
        if snapshot
            .option_regions
            .contains_key(&(slot_id.to_owned(), new_id.to_owned()))
        {
            return Err(error("같은 이름의 선택이 이미 있습니다."));
        }
    } else if snapshot.slot_regions.contains_key(new_id) {
        return Err(error("같은 이름의 항목이 이미 있습니다."));
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::hwpx_authoring_commands::apply_hwpx;
    use crate::hwpx_authoring_regions::create_region;
    use hwpx_core::bookmark_region::append_bookmark_metatag;
    use hwpx_core::package::PackageEntry;
    use serde_json::json;

    const ENTRY: &str = "Contents/section0.xml";

    fn slot_package(paragraphs: usize, end: usize) -> HwpxPackage {
        let body = (0..paragraphs)
            .map(|at| format!("<hp:p><hp:run><hp:t>{at}</hp:t></hp:run></hp:p>"))
            .collect::<String>();
        let mut package = HwpxPackage { entries: vec![PackageEntry {
            name: ENTRY.into(), stored: false,
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>").into_bytes(),
        }] };
        create_region(&mut package, &json!({"type":"create_slot", "id":"s", "entry":ENTRY, "start_paragraph":0, "end_paragraph":end})).unwrap();
        package
    }

    fn option(package: &mut HwpxPackage, id: &str, paragraph: usize) {
        create_region(package, &json!({"type":"create_option", "id":id, "slot_id":"s", "entry":ENTRY, "start_paragraph":paragraph, "end_paragraph":paragraph})).unwrap();
    }

    fn insert_before(package: &mut HwpxPackage, closing: &str, occurrence: usize, extra: &str) {
        let xml = String::from_utf8(package.entries[0].data.clone()).unwrap();
        let index = xml.match_indices(closing).nth(occurrence).unwrap().0;
        package.entries[0].data = format!("{}{extra}{}", &xml[..index], &xml[index..]).into_bytes();
    }

    fn option_ids(package: &HwpxPackage) -> Vec<String> {
        let snapshot = inspect_slot_regions(package).unwrap();
        assert!(snapshot.diagnostics.is_empty());
        snapshot.slots[0]
            .options
            .iter()
            .map(|item| item.id.clone())
            .collect()
    }

    #[test]
    fn duplicate_options_extend_only_their_parent_and_preserve_order() {
        let mut package = slot_package(3, 2);
        option(&mut package, "a", 1);
        option(&mut package, "b", 2);
        apply_hwpx(&mut package, &json!({"type":"duplicate", "kind":"option", "slot_id":"s", "option_id":"a", "new_id":"a_copy", "destination_paragraph":2})).unwrap();
        assert_eq!(option_ids(&package), ["a", "a_copy", "b"]);
        apply_hwpx(&mut package, &json!({"type":"duplicate", "kind":"option", "slot_id":"s", "option_id":"b", "new_id":"b_copy"})).unwrap();
        assert_eq!(option_ids(&package), ["a", "a_copy", "b", "b_copy"]);
        apply_hwpx(&mut package, &json!({"type":"duplicate", "kind":"option", "slot_id":"s", "option_id":"a", "new_id":"first", "destination_paragraph":0})).unwrap();
        assert_eq!(
            option_ids(&package),
            ["first", "a", "a_copy", "b", "b_copy"]
        );
        let snapshot = inspect_slot_regions(&package).unwrap();
        let owner = &snapshot.slot_regions["s"];
        assert_eq!((owner.start_paragraph, owner.end_paragraph), (0, 5));
        assert!(
            snapshot
                .option_regions
                .values()
                .all(|item| item.parent.as_deref() == Some(owner))
        );

        let mut shared = slot_package(2, 0);
        option(&mut shared, "a", 0);
        let before = shared.clone();
        let error = apply_hwpx(&mut shared, &json!({"type":"duplicate", "kind":"option", "slot_id":"s", "option_id":"a", "new_id":"b", "destination_paragraph":1})).unwrap_err();
        assert!(
            error.to_string().contains("문서 구조가 깨집니다"),
            "{error}"
        );
        assert_eq!(shared, before);
    }

    #[test]
    fn duplicate_refuses_invalid_requests_and_unsupported_content_without_mutation() {
        let mut package = slot_package(3, 2);
        option(&mut package, "a", 1);
        option(&mut package, "b", 2);
        let before = package.clone();
        for (command, message) in [
            (
                json!({"type":"duplicate", "slot_id":"s"}),
                "새 식별자가 필요",
            ),
            (
                json!({"type":"duplicate", "slot_id":"s", "new_id":"t", "destination_paragraph":"4"}),
                "문단 경계가 올바르지 않",
            ),
            (
                json!({"type":"duplicate", "kind":"option", "slot_id":"s", "option_id":"a", "new_id":"b", "destination_paragraph":2}),
                "같은 이름의 선택",
            ),
        ] {
            let error = apply_hwpx(&mut package, &command).unwrap_err();
            assert!(error.to_string().contains(message), "{error}");
            assert_eq!(package, before);
        }
        for (closing, extra, message) in [
            ("</hp:p>", "<hp:tbl/>", "복제할 수 없는 문서 요소"),
            ("</hp:run>", "<hp:tbl/>", "복제할 수 없는 제어 요소"),
            (
                "</hp:run>",
                "<hp:ctrl><hp:tab/></hp:ctrl>",
                "복제할 수 없는 제어 요소",
            ),
            (
                "</hp:fieldBegin>",
                "<hp:junk/>",
                "필드 메타데이터는 복제할 수 없",
            ),
        ] {
            let mut package = slot_package(2, 0);
            insert_before(&mut package, closing, 0, extra);
            let before = package.clone();
            let error = apply_hwpx(&mut package, &json!({"type":"duplicate", "slot_id":"s", "new_id":"copy", "destination_paragraph":1})).unwrap_err();
            assert!(error.to_string().contains(message), "{extra}: {error}");
            assert_eq!(package, before);
        }
    }

    #[test]
    fn duplicate_refuses_fields_crossing_either_block_boundary() {
        for inside_first in [true, false] {
            let mut package = slot_package(2, 0);
            let begin = "<hp:run><hp:ctrl><hp:fieldBegin id='5' type='CLICKHERE' name='F'/></hp:ctrl></hp:run>";
            let end = "<hp:run><hp:ctrl><hp:fieldEnd beginIDRef='5'/></hp:ctrl></hp:run>";
            insert_before(&mut package, "</hp:p>", usize::from(!inside_first), begin);
            insert_before(&mut package, "</hp:p>", usize::from(inside_first), end);
            let before = package.clone();
            let error = apply_hwpx(&mut package, &json!({"type":"duplicate", "slot_id":"s", "new_id":"copy", "destination_paragraph":2})).unwrap_err();
            assert!(error.to_string().contains("가로지르는 필드"), "{error}");
            assert_eq!(package, before);
        }
    }

    #[test]
    fn duplicate_preserves_foreign_metadata_and_bookmarks_while_rebasing_options() {
        let mut package = slot_package(3, 1);
        option(&mut package, "a", 1);
        let owner = inspect_slot_regions(&package).unwrap().slot_regions["s"].clone();
        append_bookmark_metatag(&mut package, &owner, "[]").unwrap();
        insert_before(&mut package, "</hp:p>", 0, "<hp:lineSegArray/>");
        insert_before(
            &mut package,
            "</hp:run>",
            0,
            "<hp:ctrl><hp:fieldBegin id='7' type='BOOKMARK' name='독립'/></hp:ctrl><hp:ctrl><hp:fieldEnd beginIDRef='7'/></hp:ctrl>",
        );
        apply_hwpx(
            &mut package,
            &json!({"type":"duplicate", "slot_id":"s", "new_id":"s2", "destination_paragraph":2}),
        )
        .unwrap();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert!(snapshot.diagnostics.is_empty());
        assert_eq!(
            snapshot
                .slots
                .iter()
                .map(|item| (item.id.as_str(), item.options[0].id.as_str()))
                .collect::<Vec<_>>(),
            [("s", "a"), ("s2", "a")]
        );
        for id in ["s", "s2"] {
            assert!(
                snapshot.slot_regions[id]
                    .meta_tags
                    .contains(&"[]".to_owned())
            );
        }
        let regions = hwpx_core::bookmark_region::resolve_bookmark_topology(&package).unwrap();
        let foreign = regions
            .iter()
            .filter(|item| item.name.as_deref() == Some("독립"))
            .collect::<Vec<_>>();
        assert_eq!(foreign.len(), 2);
        assert_ne!(foreign[0].pairing_id(), foreign[1].pairing_id());
        apply_hwpx(
            &mut package,
            &json!({"type":"rename_option", "slot_id":"s2", "option_id":"a", "id":"a2"}),
        )
        .unwrap();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert_eq!(snapshot.slots[0].options[0].id, "a");
        assert_eq!(snapshot.slots[1].options[0].id, "a2");
    }

    #[test]
    fn moves_closed_region_paragraphs_and_preserves_identity() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{}</hs:sec>",
            (0..4)
                .map(|at| format!("<hp:p><hp:run><hp:t>{at}</hp:t></hp:run></hp:p>T{at}"))
                .collect::<String>()
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        create_region(&mut package, &json!({"type": "create_slot", "id": "s", "entry": "Contents/section0.xml", "start_paragraph": 0, "end_paragraph": 1})).unwrap();
        move_region(
            &mut package,
            &json!({"type": "move", "slot_id": "s", "destination_paragraph": 4}),
        )
        .unwrap();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert!(snapshot.diagnostics.is_empty());
        assert_eq!(snapshot.slot_regions["s"].start_paragraph, 2);
        assert_eq!(snapshot.slot_regions["s"].end_paragraph, 3);
        let view = XmlView::parse(&package.entries[0].data).unwrap();
        let text: String = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| view.node(*id).unwrap().name.is(HP_NS, "t"))
            .filter_map(|id| view.direct_text(id))
            .collect();
        assert_eq!(text, "2301");
        assert_eq!(view.direct_text(view.root()).unwrap(), "T2T3T0T1");
        let stable = package.clone();
        assert!(
            move_region(
                &mut package,
                &json!({"type": "move", "slot_id": "s", "destination_paragraph": 3})
            )
            .is_err()
        );
        assert_eq!(package, stable);
        duplicate_region(&mut package, &json!({"type": "duplicate", "slot_id": "s", "new_id": "copy", "destination_paragraph": 0})).unwrap();
        let snapshot = inspect_slot_regions(&package).unwrap();
        assert!(snapshot.diagnostics.is_empty());
        assert_eq!(snapshot.slot_regions["copy"].start_paragraph, 0);
        assert_eq!(snapshot.slot_regions["s"].start_paragraph, 4);
        let view = XmlView::parse(&package.entries[0].data).unwrap();
        let text: String = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| view.node(*id).unwrap().name.is(HP_NS, "t"))
            .filter_map(|id| view.direct_text(id))
            .collect();
        assert_eq!(text, "012301");
        assert_eq!(view.direct_text(view.root()).unwrap(), "T0T1T2T3T0T1");
    }
}
