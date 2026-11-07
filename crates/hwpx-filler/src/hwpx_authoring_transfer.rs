//! Explicit HWPX semantic capture and guarded cross-document paste.

use crate::hwpx_authoring_analysis::analyze_hwpx;
use crate::text_render::python_truthy;
use hwpx_core::bookmark_region::{BookmarkRegion, resolve_bookmark_topology};
use hwpx_core::native_transfer::{
    BookmarkNameEdit, BookmarkPasteRequest, FieldPasteRequest, NativeTransferError,
    paste_bookmark_block, paste_field,
};
use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_core::text_extract::section_xml_names;
use hwpx_core::xml_view::XmlView;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticCapture {
    pub media: String,
    pub kind: String,
    pub source_bytes: Vec<u8>,
    pub selector: Value,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransferError(pub String);
impl fmt::Display for TransferError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TransferError {}
fn error(message: impl Into<String>) -> TransferError {
    TransferError(message.into())
}

fn diagnostics_clean(package: &HwpxPackage, message: &str) -> Result<Value, TransferError> {
    let detail = analyze_hwpx(package).map_err(|item| error(item.to_string()))?;
    if detail["diagnostics"]
        .as_array()
        .is_some_and(|items| !items.is_empty())
    {
        return Err(error(message));
    }
    Ok(detail)
}
/// Capture a selected HWPX Field, Slot or Option from an exact package snapshot.
pub fn capture_semantic(
    package: &HwpxPackage,
    selector: &Value,
) -> Result<SemanticCapture, TransferError> {
    let detail = diagnostics_clean(package, "구조 오류가 있어 의미를 복사할 수 없습니다.")?;
    let kind = selector.get("kind").and_then(Value::as_str).unwrap_or("");
    let found = match kind {
        "field" => detail["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|field| {
                field["occurrences"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .any(|item| {
                        item.get("entry") == selector.get("entry")
                            && item.get("occurrence") == selector.get("occurrence")
                            && item.get("pairing_id") == selector.get("pairing_id")
                    })
            }),
        "slot" => detail["slots"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|slot| slot.get("id") == selector.get("slot_id")),
        "option" => detail["slots"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|slot| {
                slot.get("id") == selector.get("slot_id")
                    && slot["options"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .any(|option| option.get("id") == selector.get("option_id"))
            }),
        _ => false,
    };
    if !found {
        return Err(error("복사할 의미 요소를 찾을 수 없습니다."));
    }
    Ok(SemanticCapture {
        media: "hwpx".into(),
        kind: kind.into(),
        source_bytes: package.to_bytes().map_err(|item| error(item.to_string()))?,
        selector: selector.clone(),
    })
}
fn styles_compatible(source: &HwpxPackage, target: &HwpxPackage) -> bool {
    fn dependencies(package: &HwpxPackage) -> HashMap<&str, &[u8]> {
        let sections: HashSet<_> = section_xml_names(package).into_iter().collect();
        package
            .entries
            .iter()
            .filter(|item| item.name != "mimetype" && !sections.contains(item.name.as_str()))
            .map(|item| (item.name.as_str(), item.data.as_slice()))
            .collect()
    }
    dependencies(source) == dependencies(target)
}
fn integer(value: Option<&Value>) -> Option<usize> {
    match value? {
        Value::Bool(flag) => Some(usize::from(*flag)),
        Value::Number(n) => n.as_u64().and_then(|n| usize::try_from(n).ok()),
        _ => None,
    }
}
fn field_error(error: NativeTransferError) -> TransferError {
    let message = match error.code {
        "missing-entry" => "붙여넣을 문서 영역을 찾을 수 없습니다.",
        "source-ordinal" => "복사한 필드 위치를 찾을 수 없습니다.",
        "source-pairing-changed" => "복사한 필드 사용 위치가 바뀌었습니다.",
        "source-name" => "필드 이름을 확인할 수 없습니다.",
        "source-control" => "복사한 필드 안에 지원하지 않는 제어 요소가 있습니다.",
        "source-coverage" => "복사한 필드 내용을 온전히 확인할 수 없습니다.",
        "target-paragraph" => "붙여넣을 문단을 확인하세요.",
        "target-range" => "붙여넣을 문자 범위를 확인하세요.",
        "target-complex" => "복합 문단에는 의미 필드를 붙여넣을 수 없습니다.",
        "target-outside" => "붙여넣을 문자 범위가 문단 밖에 있습니다.",
        _ => return TransferError(error.message),
    };
    TransferError(message.into())
}
fn field_paste(
    source: &HwpxPackage,
    target: &mut HwpxPackage,
    selector: &Value,
    destination: &Value,
    with_meaning: bool,
) -> Result<(String, String), TransferError> {
    let (Some(source_entry), Some(entry), Some(ordinal)) = (
        selector.get("entry").and_then(Value::as_str),
        destination.get("entry").and_then(Value::as_str),
        integer(selector.get("occurrence")),
    ) else {
        return Err(error("복사할 필드나 붙여넣을 영역을 확인하세요."));
    };
    if with_meaning {
        let source_bytes = source
            .entries
            .iter()
            .find(|item| item.name == source_entry)
            .ok_or_else(|| error("붙여넣을 문서 영역을 찾을 수 없습니다."))?;
        let view = XmlView::parse(&source_bytes.data).map_err(|item| error(item.to_string()))?;
        let source_name = view
            .field_occurrences(source_entry)
            .fields
            .get(ordinal)
            .and_then(|item| item.raw_name.as_deref())
            .map(str::to_owned);
        let target_detail = analyze_hwpx(target).map_err(|item| error(item.to_string()))?;
        if source_name.as_deref().is_some_and(|name| {
            target_detail["fields"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|item| item["name"] == name)
        }) && destination.get("link_existing") != Some(&Value::Bool(true))
        {
            return Err(error(
                "같은 이름의 필드가 있습니다. 기존 필드 연결을 확인하세요.",
            ));
        }
    }
    let (Some(paragraph), Some(start), Some(end)) = (
        integer(destination.get("paragraph")),
        integer(destination.get("start")),
        integer(destination.get("end")),
    ) else {
        return Err(error("붙여넣을 문자 범위를 확인하세요."));
    };
    let result = paste_field(
        source,
        target,
        &FieldPasteRequest {
            source_entry,
            source_ordinal: ordinal,
            source_pairing_id: selector.get("pairing_id").and_then(Value::as_str),
            target_entry: entry,
            target_paragraph: paragraph,
            start,
            end,
            with_meaning,
        },
    )
    .map_err(field_error)?;
    Ok((result.previous, result.inserted))
}
fn selected_region(
    source: &HwpxPackage,
    kind: &str,
    selector: &Value,
) -> Result<(BookmarkRegion, Value), TransferError> {
    let detail = analyze_hwpx(source).map_err(|item| error(item.to_string()))?;
    let slot = detail["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|slot| slot.get("id") == selector.get("slot_id"));
    let selected = if kind == "slot" {
        slot.cloned()
    } else {
        slot.and_then(|row| row["options"].as_array())
            .and_then(|rows| {
                rows.iter()
                    .find(|row| row.get("id") == selector.get("option_id"))
            })
            .cloned()
    };
    let selected = selected.ok_or_else(|| error("복사할 영역을 찾을 수 없습니다."))?;
    let loc = &selected["location"];
    let raw = &selected["raw"];
    if loc.is_null() || raw.is_null() {
        return Err(error("복사할 영역을 찾을 수 없습니다."));
    }
    let regions = resolve_bookmark_topology(source).map_err(|item| error(item.to_string()))?;
    let region = regions
        .into_iter()
        .find(|region| {
            loc["entry"] == region.section
                && raw["bookmark_name"].as_str() == region.name.as_deref()
                && loc["start_paragraph"] == region.start_paragraph
                && loc["end_paragraph"] == region.end_paragraph
        })
        .ok_or_else(|| error("복사할 영역을 찾을 수 없습니다."))?;
    Ok((region, selected))
}
fn metatag_edits(region: &BookmarkRegion, new_id: &str) -> Result<Vec<String>, TransferError> {
    let mut updates = Vec::new();
    for raw in &region.meta_tags {
        if !raw.contains("\"hwpxFiller\"") {
            continue;
        }
        let mut data: Value = serde_json::from_str(raw).map_err(|item| error(item.to_string()))?;
        data["hwpxFiller"]["id"] = json!(new_id);
        updates.push(serde_json::to_string(&data).map_err(|item| error(item.to_string()))?);
    }
    Ok(updates)
}
fn block_error(error: NativeTransferError) -> TransferError {
    let message = match error.code {
        "missing-entry" => "붙여넣을 문서 영역을 찾을 수 없습니다.",
        "no-target-paragraph" => "붙여넣을 문단이 없습니다.",
        "target-boundary" => "붙여넣을 문단 경계가 올바르지 않습니다.",
        "partial-boundary" => "영역 경계를 문단 단위로 복사할 수 없습니다.",
        "partial-content" => "문단 일부만 포함한 의미 영역은 내용 손실 없이 복사할 수 없습니다.",
        "complex-paragraph" => "복합 문서 요소는 의미째 붙여넣을 수 없습니다.",
        "unsupported-control" => "지원하지 않는 제어 요소가 포함되어 있습니다.",
        _ => return TransferError(error.message),
    };
    TransferError(message.into())
}
fn field_names<'a>(fields: impl Iterator<Item = &'a Value>) -> HashSet<String> {
    fields
        .filter_map(|field| field["name"].as_str())
        .map(str::to_owned)
        .collect()
}
fn rows(value: &Value) -> impl Iterator<Item = &Value> {
    value.as_array().into_iter().flatten()
}
/// Names of source fields used inside the copied region.
fn copied_field_names(
    source: &HwpxPackage,
    region: &BookmarkRegion,
) -> Result<HashSet<String>, TransferError> {
    let detail = analyze_hwpx(source).map_err(|item| error(item.to_string()))?;
    let inside = |occ: &Value| {
        occ["entry"] == region.section
            && occ["paragraph"].as_u64().is_some_and(|at| {
                region.start_paragraph as u64 <= at && at <= region.end_paragraph as u64
            })
    };
    Ok(field_names(
        rows(&detail["fields"]).filter(|field| rows(&field["occurrences"]).any(inside)),
    ))
}
/// The slot bookmark name, refused when the id is taken or the spot is inside a region.
fn slot_bookmark_name(
    target: &HwpxPackage,
    target_detail: &Value,
    new_id: &str,
    at: (&str, usize),
) -> Result<String, TransferError> {
    let (entry, index) = at;
    if rows(&target_detail["slots"]).any(|slot| slot["id"] == new_id) {
        return Err(error(
            "같은 항목 식별자가 있습니다. 새 식별자를 입력하세요.",
        ));
    }
    if resolve_bookmark_topology(target)
        .map_err(|item| error(item.to_string()))?
        .iter()
        .any(|row| {
            row.section == entry && row.start_paragraph < index && index <= row.end_paragraph
        })
    {
        return Err(error("항목을 다른 의미 영역 안에 넣을 수 없습니다."));
    }
    Ok(new_id.to_owned())
}
/// The option bookmark name under its owner slot, which must enclose the paste point.
fn option_bookmark_name(
    target_detail: &Value,
    destination: &Value,
    new_id: &str,
    at: (&str, usize),
) -> Result<String, TransferError> {
    let (entry, index) = at;
    let owner_id = destination.get("slot_id").and_then(Value::as_str);
    let owner = rows(&target_detail["slots"])
        .find(|slot| slot.get("id").and_then(Value::as_str) == owner_id)
        .filter(|slot| {
            slot["location"]["entry"] == entry
                && !rows(&slot["options"]).any(|opt| opt["id"] == new_id)
        })
        .ok_or_else(|| error("상위 항목이나 선택 식별자를 확인하세요."))?;
    let location = &owner["location"];
    let encloses = location["start_paragraph"]
        .as_u64()
        .is_some_and(|at| at < (index as u64))
        && location["end_paragraph"]
            .as_u64()
            .is_some_and(|at| (index as u64) <= at);
    if !encloses {
        return Err(error("선택은 상위 항목 안의 문단 경계에 붙여넣으세요."));
    }
    Ok(format!("{}/{new_id}", owner_id.unwrap()))
}
/// Renames for option bookmarks nested in a copied slot, moved under the new slot id.
fn child_name_edits(
    source: &HwpxPackage,
    selector: &Value,
    region: &BookmarkRegion,
    new_id: &str,
) -> Result<Vec<BookmarkNameEdit>, TransferError> {
    let old_prefix = format!(
        "{}/",
        selector
            .get("slot_id")
            .and_then(Value::as_str)
            .unwrap_or("")
    );
    let nested = |child: &BookmarkRegion| {
        child.pairing_id() != region.pairing_id()
            && child.section == region.section
            && child.start_paragraph >= region.start_paragraph
            && child.end_paragraph <= region.end_paragraph
    };
    Ok(resolve_bookmark_topology(source)
        .map_err(|item| error(item.to_string()))?
        .into_iter()
        .filter(|child| nested(child))
        .filter_map(|child| {
            let suffix = child.name.as_deref()?.strip_prefix(&old_prefix)?;
            Some(BookmarkNameEdit {
                source_pairing_id: child.pairing_id().into(),
                new_name: format!("{new_id}/{suffix}"),
                metatag_texts: Vec::new(),
            })
        })
        .collect())
}
/// Bookmark renames that give the pasted region (and a slot's options) their new ids.
fn meaning_name_edits(
    source: &HwpxPackage,
    target: &HwpxPackage,
    request: (&Value, &Value, &str),
    copied: (&BookmarkRegion, &Value),
    at: (&str, usize),
) -> Result<Vec<BookmarkNameEdit>, TransferError> {
    let (selector, destination, kind) = request;
    let (region, selected) = copied;
    let new_id = destination
        .get("new_id")
        .filter(|value| python_truthy(value))
        .or_else(|| selected.get("id"))
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| error("새 식별자를 입력하세요."))?;
    let target_detail = analyze_hwpx(target).map_err(|item| error(item.to_string()))?;
    let copied_names = copied_field_names(source, region)?;
    let target_names = field_names(rows(&target_detail["fields"]));
    if !copied_names.is_disjoint(&target_names)
        && destination.get("link_existing") != Some(&Value::Bool(true))
    {
        return Err(error(
            "같은 이름의 필드가 있습니다. 기존 필드 연결을 확인하세요.",
        ));
    }
    let bookmark_name = if kind == "slot" {
        slot_bookmark_name(target, &target_detail, new_id, at)?
    } else {
        option_bookmark_name(&target_detail, destination, new_id, at)?
    };
    let mut edits = vec![BookmarkNameEdit {
        source_pairing_id: region.pairing_id().into(),
        new_name: bookmark_name,
        metatag_texts: metatag_edits(region, new_id)?,
    }];
    if kind == "slot" {
        edits.extend(child_name_edits(source, selector, region, new_id)?);
    }
    Ok(edits)
}
fn block_paste(
    source: &HwpxPackage,
    target: &mut HwpxPackage,
    selector: &Value,
    destination: &Value,
    kind: &str,
    with_meaning: bool,
) -> Result<(String, String), TransferError> {
    let (region, selected) = selected_region(source, kind, selector)?;
    let (Some(entry), Some(index)) = (
        destination.get("entry").and_then(Value::as_str),
        integer(destination.get("destination_paragraph")),
    ) else {
        return Err(error("붙여넣을 문단 시작 위치를 고르세요."));
    };
    if destination
        .get("start")
        .is_some_and(|value| value != &json!(0))
    {
        return Err(error("붙여넣을 문단 시작 위치를 고르세요."));
    }
    let edits = if with_meaning {
        meaning_name_edits(
            source,
            target,
            (selector, destination, kind),
            (&region, &selected),
            (entry, index),
        )?
    } else {
        Vec::new()
    };
    let inserted = paste_bookmark_block(
        source,
        target,
        &BookmarkPasteRequest {
            source_region: &region,
            target_entry: entry,
            destination_paragraph: index,
            with_meaning,
            name_edits: &edits,
        },
    )
    .map_err(block_error)?;
    Ok((String::new(), inserted))
}

/// Paste into a caller-owned disposable package. On any failure all target XML bytes roll back.
pub fn paste_semantic(
    target: &mut HwpxPackage,
    captured: &SemanticCapture,
    destination: &Value,
    with_meaning: bool,
) -> Result<Value, TransferError> {
    if captured.media != "hwpx" {
        return Err(error(
            "서로 다른 파일 형식 사이의 의미 붙여넣기는 지원하지 않습니다.",
        ));
    }
    if captured.source_bytes.is_empty() || !captured.selector.is_object() {
        return Err(error("복사한 의미 데이터가 올바르지 않습니다."));
    }
    let source = HwpxPackage::from_bytes(&captured.source_bytes, PackageLimits::default())
        .map_err(|item| error(item.to_string()))?;
    if !styles_compatible(&source, target) {
        return Err(error(
            "두 HWPX 문서의 서식 참조가 달라 원래 모양을 보존할 수 없습니다.",
        ));
    }
    diagnostics_clean(target, "대상 문서의 구조 오류를 먼저 수정하세요.")?;
    let before = target
        .entries
        .iter()
        .filter(|entry| entry.name.to_ascii_lowercase().ends_with(".xml"))
        .map(|entry| (entry.name.clone(), entry.data.clone()))
        .collect::<Vec<_>>();
    let result = (|| {
        let (previous, inserted) = if captured.kind == "field" {
            field_paste(
                &source,
                target,
                &captured.selector,
                destination,
                with_meaning,
            )?
        } else {
            block_paste(
                &source,
                target,
                &captured.selector,
                destination,
                &captured.kind,
                with_meaning,
            )?
        };
        let result = diagnostics_clean(target, "붙여넣으면 대상 문서의 의미 구조가 깨집니다.")?;
        let changed = before
            .iter()
            .filter(|(name, bytes)| {
                target
                    .entries
                    .iter()
                    .any(|entry| &entry.name == name && &entry.data != bytes)
            })
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>();
        Ok(
            json!({"changed_entries":changed,"affected":1,"before":previous,"after":inserted,
            "original":previous,"captured_text":previous,"result":result,"expanded":false}),
        )
    })();
    if result.is_err() {
        for (name, bytes) in before {
            if let Some(entry) = target.entries.iter_mut().find(|entry| entry.name == name) {
                entry.data = bytes;
            }
        }
    }
    result
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::hwpx_authoring_analysis::analyze_hwpx;
    use crate::hwpx_authoring_commands::apply_hwpx;
    use hwpx_core::package::{MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};
    use hwpx_core::text_model::HP_NS;

    fn package(body: &str) -> HwpxPackage {
        package_paragraphs(&[body])
    }

    fn package_paragraphs(paragraphs: &[&str]) -> HwpxPackage {
        let body = paragraphs
            .iter()
            .map(|paragraph| format!("<hp:p>{paragraph}</hp:p>"))
            .collect::<String>();
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>"
        );
        HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "BinData/p.bin".into(),
                    data: vec![1, 2, 3],
                    stored: true,
                },
            ],
        }
    }

    #[test]
    fn captured_field_pastes_atomically_and_keeps_unrelated_entries() {
        let source = package(
            "<hp:run><hp:ctrl><hp:fieldBegin id='4' fieldid='5' name='A' type='CLICK_HERE'/></hp:ctrl></hp:run><hp:run charPrIDRef='7'><hp:t>값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='4' fieldid='5'/></hp:ctrl></hp:run>",
        );
        let selector =
            json!({"kind":"field","entry":"Contents/section0.xml","occurrence":0,"pairing_id":"4"});
        let captured = capture_semantic(&source, &selector).unwrap();
        assert_eq!(
            capture_semantic(
                &source,
                &json!({"kind":"field","entry":"Contents/section0.xml","occurrence":0,"pairing_id":"missing"})
            )
            .unwrap_err()
            .0,
            "복사할 의미 요소를 찾을 수 없습니다."
        );
        let mut target = package("<hp:run charPrIDRef='1'><hp:t>OLD</hp:t></hp:run>");
        let before = target.clone();
        let mut style_mismatch = target.clone();
        style_mismatch.entries[2].data = vec![9, 9, 9];
        let mismatched_before = style_mismatch.clone();
        assert!(
            paste_semantic(
                &mut style_mismatch,
                &captured,
                &json!({"entry":"Contents/section0.xml","paragraph":0,"start":1,"end":2}),
                true
            )
            .is_err()
        );
        assert_eq!(style_mismatch, mismatched_before);
        let impact = paste_semantic(
            &mut target,
            &captured,
            &json!({"entry":"Contents/section0.xml","paragraph":0,"start":1,"end":2}),
            true,
        )
        .unwrap();
        assert_eq!(impact["changed_entries"], json!(["Contents/section0.xml"]));
        assert_eq!(impact["before"], "L");
        assert_eq!(impact["after"], "값");
        assert_eq!(analyze_hwpx(&target).unwrap()["fields"][0]["name"], "A");
        assert!(
            String::from_utf8(target.entries[1].data.clone())
                .unwrap()
                .contains("charPrIDRef=\"7\"")
        );
        assert_eq!(target.entries[0], before.entries[0]);
        assert_eq!(target.entries[2], before.entries[2]);
        let mut plain = before.clone();
        paste_semantic(
            &mut plain,
            &captured,
            &json!({"entry":"Contents/section0.xml","paragraph":0,"start":1,"end":2}),
            false,
        )
        .unwrap();
        assert_eq!(analyze_hwpx(&plain).unwrap()["fields"], json!([]));
        let unchanged = target.clone();
        let refusal=paste_semantic(&mut target,&captured,&json!({"entry":"Contents/section0.xml","paragraph":0,"start":1,"end":2,"link_existing":true}),true).unwrap_err();
        assert!(refusal.0.contains("복합 문단"));
        assert_eq!(target, unchanged);
        let malformed = SemanticCapture {
            media: "hwpx".into(),
            kind: String::new(),
            source_bytes: Vec::new(),
            selector: Value::Null,
        };
        assert_eq!(
            paste_semantic(&mut target, &malformed, &Value::Null, true)
                .unwrap_err()
                .0,
            "복사한 의미 데이터가 올바르지 않습니다."
        );
        assert_eq!(target, unchanged);
    }

    #[test]
    fn slot_paste_rekeys_child_option_and_refuses_missing_identity_without_mutation() {
        let entry = "Contents/section0.xml";
        let mut source = package_paragraphs(&[
            "<hp:run><hp:t>공통</hp:t></hp:run>",
            "<hp:run><hp:t>선택</hp:t></hp:run>",
            "<hp:run><hp:t>끝</hp:t></hp:run>",
        ]);
        apply_hwpx(
            &mut source,
            &json!({"type":"create_slot","entry":entry,"start_paragraph":0,"end_paragraph":1,"id":"s"}),
        )
        .unwrap();
        apply_hwpx(
            &mut source,
            &json!({"type":"create_option","entry":entry,"start_paragraph":1,"end_paragraph":1,"slot_id":"s","id":"a"}),
        )
        .unwrap();
        let captured = capture_semantic(&source, &json!({"kind":"slot","slot_id":"s"})).unwrap();
        let mut collision = source.clone();
        let collision_before = collision.clone();
        let refusal = paste_semantic(
            &mut collision,
            &captured,
            &json!({"entry":entry,"destination_paragraph":3}),
            true,
        )
        .unwrap_err();
        assert!(refusal.0.contains("새 식별자"));
        assert_eq!(collision, collision_before);
        let mut target = package("<hp:run><hp:t>기존</hp:t></hp:run>");
        for (destination, reason) in [
            (
                json!({"entry":entry,"destination_paragraph":1,"start":1,"new_id":"s2"}),
                "문단 시작",
            ),
            (
                json!({"entry":entry,"destination_paragraph":3,"new_id":"s2"}),
                "문단 경계",
            ),
            (
                json!({"entry":"Contents/missing.xml","destination_paragraph":1,"new_id":"s2"}),
                "문서 영역",
            ),
        ] {
            let before = target.clone();
            let refusal = paste_semantic(&mut target, &captured, &destination, true).unwrap_err();
            assert!(refusal.0.contains(reason), "{}", refusal.0);
            assert_eq!(target, before);
        }
        let mut no_paragraph = package_paragraphs(&[]);
        let before_empty = no_paragraph.clone();
        let refusal = paste_semantic(
            &mut no_paragraph,
            &captured,
            &json!({"entry":entry,"destination_paragraph":0,"new_id":"s2"}),
            true,
        )
        .unwrap_err();
        assert!(refusal.0.contains("구조 오류"));
        assert_eq!(no_paragraph, before_empty);
        paste_semantic(
            &mut target,
            &captured,
            &json!({"entry":entry,"destination_paragraph":1,"start":0,"new_id":"s2"}),
            true,
        )
        .unwrap();
        let detail = analyze_hwpx(&target).unwrap();
        assert_eq!(detail["slots"][0]["id"], "s2");
        assert_eq!(detail["slots"][0]["options"][0]["id"], "a");
        let xml = String::from_utf8(target.entries[1].data.clone()).unwrap();
        assert!(xml.contains("s2/a"));
        apply_hwpx(
            &mut target,
            &json!({"type":"rename_slot","slot_id":"s2","id":"s3"}),
        )
        .unwrap();
        let renamed = analyze_hwpx(&target).unwrap();
        assert_eq!(renamed["slots"][0]["id"], "s3");
        assert_eq!(renamed["slots"][0]["options"][0]["id"], "a");
    }

    #[test]
    fn option_paste_requires_the_selected_owner_and_a_free_child_identity() {
        let entry = "Contents/section0.xml";
        let mut source = package_paragraphs(&[
            "<hp:run><hp:t>공통</hp:t></hp:run>",
            "<hp:run><hp:t>선택 문장</hp:t></hp:run>",
            "<hp:run><hp:t>끝</hp:t></hp:run>",
        ]);
        apply_hwpx(
            &mut source,
            &json!({"type":"create_slot","entry":entry,"start_paragraph":0,"end_paragraph":2,"id":"s"}),
        )
        .unwrap();
        apply_hwpx(
            &mut source,
            &json!({"type":"create_option","entry":entry,"start_paragraph":1,"end_paragraph":1,"slot_id":"s","id":"a"}),
        )
        .unwrap();
        let captured = capture_semantic(
            &source,
            &json!({"kind":"option","slot_id":"s","option_id":"a"}),
        )
        .unwrap();
        let mut target = package_paragraphs(&[
            "<hp:run><hp:t>공통</hp:t></hp:run>",
            "<hp:run><hp:t>여기</hp:t></hp:run>",
            "<hp:run><hp:t>끝</hp:t></hp:run>",
        ]);
        apply_hwpx(
            &mut target,
            &json!({"type":"create_slot","entry":entry,"start_paragraph":0,"end_paragraph":2,"id":"t"}),
        )
        .unwrap();
        let destination =
            json!({"entry":entry,"destination_paragraph":1,"start":0,"slot_id":"t","new_id":"b"});
        for (invalid, reason) in [
            (
                json!({"entry":entry,"destination_paragraph":1,"slot_id":"missing","new_id":"b"}),
                "상위 항목",
            ),
            (
                json!({"entry":entry,"destination_paragraph":3,"slot_id":"t","new_id":"b"}),
                "상위 항목 안",
            ),
        ] {
            let before = target.clone();
            let refusal = paste_semantic(&mut target, &captured, &invalid, true).unwrap_err();
            assert!(refusal.0.contains(reason), "{}", refusal.0);
            assert_eq!(target, before);
        }
        paste_semantic(&mut target, &captured, &destination, true).unwrap();
        let detail = analyze_hwpx(&target).unwrap();
        assert_eq!(detail["slots"][0]["id"], "t");
        assert_eq!(detail["slots"][0]["options"][0]["id"], "b");
        assert!(
            String::from_utf8(target.entries[1].data.clone())
                .unwrap()
                .contains("선택 문장")
        );
        let after = target.clone();
        let refusal = paste_semantic(&mut target, &captured, &destination, true).unwrap_err();
        assert!(refusal.0.contains("상위 항목이나 선택 식별자"));
        assert_eq!(target, after);
        let captured_slot =
            capture_semantic(&source, &json!({"kind":"slot","slot_id":"s"})).unwrap();
        let refusal = paste_semantic(
            &mut target,
            &captured_slot,
            &json!({"entry":entry,"destination_paragraph":1,"new_id":"other"}),
            true,
        )
        .unwrap_err();
        assert!(refusal.0.contains("다른 의미 영역"));
        assert_eq!(target, after);
    }

    #[test]
    fn slot_paste_links_contained_fields_only_with_explicit_confirmation() {
        let entry = "Contents/section0.xml";
        let mut source = package_paragraphs(&[
            "<hp:run><hp:t>공통</hp:t></hp:run>",
            "<hp:run><hp:t>값</hp:t></hp:run>",
        ]);
        apply_hwpx(
            &mut source,
            &json!({"type":"create_field","entry":entry,"paragraph":1,"start":0,"end":1,"name":"F"}),
        )
        .unwrap();
        apply_hwpx(
            &mut source,
            &json!({"type":"create_slot","entry":entry,"start_paragraph":0,"end_paragraph":1,"id":"s"}),
        )
        .unwrap();
        let captured = capture_semantic(&source, &json!({"kind":"slot","slot_id":"s"})).unwrap();
        let mut target = package("<hp:run><hp:t>기존</hp:t></hp:run>");
        apply_hwpx(
            &mut target,
            &json!({"type":"create_field","entry":entry,"paragraph":0,"start":0,"end":2,"name":"F"}),
        )
        .unwrap();
        let destination = json!({"entry":entry,"destination_paragraph":1,"new_id":"s2"});
        let before = target.clone();
        let refusal = paste_semantic(&mut target, &captured, &destination, true).unwrap_err();
        assert!(refusal.0.contains("기존 필드 연결"));
        assert_eq!(target, before);
        let mut linked = destination.clone();
        linked["link_existing"] = json!(true);
        paste_semantic(&mut target, &captured, &linked, true).unwrap();
        assert_eq!(analyze_hwpx(&target).unwrap()["fields"][0]["count"], 2);
    }
}
