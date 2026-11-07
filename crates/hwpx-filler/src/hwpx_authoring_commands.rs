//! Atomic product authoring commands over the guarded native HWPX editors.

use crate::hwpx_authoring_analysis::{analyze_hwpx, fields};
use crate::hwpx_authoring_fields::{
    change_field, compile_token, create_field, create_fields, field_site_contexts, revert_template,
};
use crate::hwpx_authoring_preview::{command_preview_label, preview_content_context};
use crate::hwpx_authoring_region_blocks::{duplicate_region, move_region};
use crate::hwpx_authoring_regions::{adjust_region, create_region, rename_region};
use crate::hwpx_product_inspection::{SlotSnapshot, inspect_slot_regions};
use crate::hwpx_structure_ops::{remove_slot, remove_slot_option};
use crate::structure_scan::normalize_field_id;
use crate::template_authoring::{
    command_label, field_candidates, revert_template_message, whole_field_unset,
};
use crate::text_render::{python_repr, python_str, python_truthy};
use hwpx_core::bookmark_region::{BookmarkRegion, unwrap_bookmark_region};
use hwpx_core::package::HwpxPackage;
use hwpx_core::package::PackageEntry;
use serde_json::{Map, Value, json};
use std::fmt;

const CASCADE_MESSAGE: &str =
    "항목 의미를 해제하면 하위 선택 의미도 해제됩니다. 함께 해제를 확인하세요.";
const INVALID_SELECTION: &str = "고른 위치가 올바르지 않습니다.";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AuthoringCommandError {
    pub message: String,
    pub detail: Option<Value>,
}
impl AuthoringCommandError {
    fn plain(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            detail: None,
        }
    }
    pub fn to_dict(&self) -> Option<&Value> {
        self.detail.as_ref()
    }
}
impl fmt::Display for AuthoringCommandError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for AuthoringCommandError {}

fn error(error: impl fmt::Display) -> AuthoringCommandError {
    AuthoringCommandError::plain(error.to_string())
}

// Authoring edits only touch XML entries. Keep binaries borrowed from the caller
// during apply; preview's disposable package need not copy unrelated payloads.
fn xml_snapshot(package: &HwpxPackage) -> Vec<(usize, Vec<u8>)> {
    package
        .entries
        .iter()
        .enumerate()
        .filter(|(_, entry)| entry.name.to_ascii_lowercase().ends_with(".xml"))
        .map(|(at, entry)| (at, entry.data.clone()))
        .collect()
}
fn restore(package: &mut HwpxPackage, before: &[(usize, Vec<u8>)]) {
    for (at, bytes) in before {
        package.entries[*at].data = bytes.clone();
    }
}
fn changed_entries(package: &HwpxPackage, before: &[(usize, Vec<u8>)]) -> Vec<String> {
    before
        .iter()
        .filter(|(at, bytes)| package.entries[*at].data != *bytes)
        .map(|(at, _)| package.entries[*at].name.clone())
        .collect()
}
fn disposable(package: &HwpxPackage) -> HwpxPackage {
    HwpxPackage {
        entries: package
            .entries
            .iter()
            .map(|entry| PackageEntry {
                name: entry.name.clone(),
                data: if entry.name.to_ascii_lowercase().ends_with(".xml") {
                    entry.data.clone()
                } else {
                    Vec::new()
                },
                stored: entry.stored,
            })
            .collect(),
    }
}

fn object(command: &Value) -> Result<&Map<String, Value>, AuthoringCommandError> {
    command
        .as_object()
        .ok_or_else(|| AuthoringCommandError::plain(INVALID_SELECTION))
}
fn context<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.get(key).filter(|v| !v.is_null())
}
fn name(value: Option<&Value>) -> Option<String> {
    value.and_then(Value::as_str).and_then(normalize_field_id)
}
fn prior_field_name<'a>(prior: &'a [Value], command: &Value) -> Option<&'a Value> {
    prior.iter().find_map(|field| {
        field
            .get("occurrences")?
            .as_array()?
            .iter()
            .any(|occurrence| {
                occurrence.get("entry") == command.get("entry")
                    && occurrence.get("occurrence") == command.get("occurrence")
            })
            .then(|| &field["name"])
    })
}
fn region_display_name(
    snapshot: &SlotSnapshot,
    slot_id: &str,
    option_id: Option<&str>,
) -> Option<String> {
    let slot = snapshot.slots.iter().find(|item| item.id == slot_id)?;
    if let Some(id) = option_id {
        let option = slot.options.iter().find(|item| item.id == id)?;
        Some(
            option
                .label
                .as_deref()
                .filter(|v| !v.is_empty())
                .unwrap_or(&option.id)
                .into(),
        )
    } else {
        Some(
            slot.label
                .as_deref()
                .filter(|v| !v.is_empty())
                .unwrap_or(&slot.id)
                .into(),
        )
    }
}
fn children_for_cascade(context: &Value) -> Vec<Value> {
    context
        .get("children")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|child| child.get("kind").and_then(Value::as_str) == Some("option"))
        .cloned()
        .collect()
}
fn cascade_error(children: Vec<Value>) -> AuthoringCommandError {
    AuthoringCommandError {
        message: CASCADE_MESSAGE.into(),
        detail: Some(
            json!({"code":"cascade_required","children":children,"message":CASCADE_MESSAGE}),
        ),
    }
}
fn unwrap_options(package: &mut HwpxPackage, slot_id: &str) -> Result<(), AuthoringCommandError> {
    loop {
        let snapshot = inspect_slot_regions(package).map_err(error)?;
        let next = snapshot
            .option_regions
            .iter()
            .filter(|((owner, _), _)| owner == slot_id)
            .max_by_key(|(_, region)| region.start_paragraph)
            .map(|(_, region)| region.clone());
        let Some(region) = next else {
            return Ok(());
        };
        unwrap_bookmark_region(package, &region).map_err(error)?;
    }
}
fn delete_region(
    package: &mut HwpxPackage,
    kind: &str,
    slot_id: &str,
    option_id: &str,
) -> Result<(), AuthoringCommandError> {
    if kind == "option" {
        remove_slot_option(package, slot_id, option_id).map_err(error)
    } else {
        remove_slot(package, slot_id).map_err(error)
    }
}
/// Unwraps the region; a slot with options first unwraps them, then its fresh region.
fn unwrap_region(
    package: &mut HwpxPackage,
    slot_id: &str,
    region: &BookmarkRegion,
    has_options: bool,
) -> Result<(), AuthoringCommandError> {
    if !has_options {
        return unwrap_bookmark_region(package, region).map_err(error);
    }
    unwrap_options(package, slot_id)?;
    let fresh = inspect_slot_regions(package).map_err(error)?;
    let region = fresh.slot_regions.get(slot_id).ok_or_else(|| {
        AuthoringCommandError::plain("항목이나 선택 영역을 찾을 수 없습니다.")
    })?;
    unwrap_bookmark_region(package, region).map_err(error)
}
fn remove_region(
    package: &mut HwpxPackage,
    command: &Value,
    action: &str,
    projecting: bool,
    impact_context: &Value,
) -> Result<bool, AuthoringCommandError> {
    let kind = command
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("slot");
    let slot_id = command
        .get("slot_id")
        .map_or_else(|| "None".into(), python_str);
    let option_id = command
        .get("option_id")
        .map_or_else(|| "None".into(), python_str);
    if action == "delete" {
        delete_region(package, kind, &slot_id, &option_id)?;
        return Ok(false);
    }
    let snapshot = inspect_slot_regions(package).map_err(error)?;
    if !snapshot.diagnostics.is_empty() {
        return Err(AuthoringCommandError::plain(
            "문서 구조 오류를 먼저 수정하세요.",
        ));
    }
    let region = if kind == "option" {
        snapshot
            .option_regions
            .get(&(slot_id.clone(), option_id.clone()))
    } else {
        snapshot.slot_regions.get(&slot_id)
    }
    .ok_or_else(|| AuthoringCommandError::plain("항목이나 선택 영역을 찾을 수 없습니다."))?
    .clone();
    let has_options = kind != "option"
        && snapshot
            .slots
            .iter()
            .any(|slot| slot.id == slot_id && !slot.options.is_empty());
    let cascade = has_options && !command.get("cascade").is_some_and(python_truthy);
    if cascade && !projecting {
        return Err(cascade_error(children_for_cascade(impact_context)));
    }
    unwrap_region(package, &slot_id, &region, has_options)?;
    Ok(cascade)
}

struct DispatchResult {
    captured: Value,
    label: String,
    context: Value,
    extra: Map<String, Value>,
    cascade: bool,
}
fn dispatch(
    package: &mut HwpxPackage,
    command: &Value,
    action: &str,
    projecting: bool,
    prior: &[Value],
    mut label: String,
    mut context: Value,
) -> Result<DispatchResult, AuthoringCommandError> {
    let mut extra = Map::new();
    let mut captured = Value::Null;
    let mut cascade = false;
    match action {
        "create_field" => {
            let sites = if !command.get("ranges").unwrap_or(&Value::Null).is_null() {
                Some(field_site_contexts(package, command).map_err(error)?)
            } else {
                None
            };
            captured = Value::String(create_field(package, command).map_err(|e| {
                AuthoringCommandError {
                    message: e.0,
                    detail: e.1,
                }
            })?);
            let normalized = name(command.get("name"));
            let existing = prior
                .iter()
                .find(|item| item["name"].as_str() == normalized.as_deref())
                .and_then(|item| item["count"].as_u64())
                .unwrap_or(0);
            extra.insert("links_existing".into(), json!(existing > 0));
            extra.insert("existing_count".into(), json!(existing));
            extra.insert(
                "candidates".into(),
                json!(field_candidates(prior).map_err(error)?),
            );
            if let Some(sites) = sites {
                extra.insert("affected".into(), json!(sites.len()));
                context
                    .as_object_mut()
                    .unwrap()
                    .insert("included".into(), json!(sites));
            }
        }
        "create_fields" => {
            let sites = command
                .get("fields")
                .and_then(Value::as_array)
                .filter(|sites| !sites.is_empty() && sites.iter().all(Value::is_object))
                .ok_or_else(|| AuthoringCommandError::plain(INVALID_SELECTION))?;
            let count = create_fields(package, sites).map_err(|e| AuthoringCommandError {
                message: e.0,
                detail: e.1,
            })?;
            extra.insert("affected".into(), json!(count));
            extra.insert("before".into(), Value::Null);
            extra.insert("after".into(), Value::Null);
            let existing = sites.iter().any(|item| {
                name(item.get("name"))
                    .is_some_and(|n| prior.iter().any(|p| p["name"].as_str() == Some(n.as_str())))
            });
            extra.insert("links_existing".into(), json!(existing));
            label = "필드로 만들기".into();
        }
        "rename_field" | "relink_field" | "unset_field" => {
            captured =
                json!(
                    change_field(package, command).map_err(|e| AuthoringCommandError {
                        message: e.0,
                        detail: e.1
                    })?
                );
            let whole = whole_field_unset(object(command)?);
            let target = if action == "rename_field" || whole {
                command.get("old_name")
            } else {
                prior_field_name(prior, command)
            };
            label = command_label(object(command)?, target);
            if whole {
                let old = name(command.get("old_name"));
                let included: Vec<_> = prior
                    .iter()
                    .filter(|field| field["name"].as_str() == old.as_deref())
                    .flat_map(|field| field["occurrences"].as_array().into_iter().flatten())
                    .map(|occurrence| occurrence["context"].clone())
                    .collect();
                context
                    .as_object_mut()
                    .unwrap()
                    .insert("included".into(), json!(included));
            }
        }
        "compile_token" => captured = json!(compile_token(package, command).map_err(error)?),
        "revert_template" => {
            let count = revert_template(package).map_err(error)?;
            captured = json!(count);
            extra.insert("message".into(), json!(revert_template_message(count)));
        }
        "create_slot" | "create_option" => {
            create_region(package, command).map_err(|e| AuthoringCommandError {
                message: e.0,
                detail: e.1,
            })?
        }
        "rename_slot" | "rename_option" => {
            rename_region(package, command).map_err(|e| AuthoringCommandError {
                message: e.0,
                detail: e.1,
            })?
        }
        "adjust_range" => adjust_region(package, command).map_err(|e| AuthoringCommandError {
            message: e.0,
            detail: e.1,
        })?,
        "move" => move_region(package, command).map_err(|e| AuthoringCommandError {
            message: e.0,
            detail: e.1,
        })?,
        "duplicate" => duplicate_region(package, command).map_err(|e| AuthoringCommandError {
            message: e.0,
            detail: e.1,
        })?,
        "unwrap" | "delete" => {
            cascade = remove_region(package, command, action, projecting, &context)?
        }
        _ => {
            return Err(AuthoringCommandError::plain(format!(
                "지원하지 않는 HWPX 저작 명령입니다: {}",
                python_repr(command.get("type").unwrap_or(&Value::Null))
            )));
        }
    }
    Ok(DispatchResult {
        captured,
        label,
        context,
        extra,
        cascade,
    })
}

fn impact(
    package: &HwpxPackage,
    before: &[(usize, Vec<u8>)],
    command: &Value,
    before_label: &str,
    result: Value,
    dispatch: DispatchResult,
) -> Value {
    let changed = changed_entries(package, before);
    let captured_text = dispatch.captured.as_str().map(str::to_owned);
    let after_label = command_preview_label(command, true, Some(&dispatch.captured));
    let from = context(&dispatch.context, "before")
        .cloned()
        .or_else(|| captured_text.as_ref().map(|text| json!(text)))
        .unwrap_or_else(|| json!(before_label));
    let after = context(&dispatch.context, "after")
        .cloned()
        .unwrap_or_else(|| json!(after_label));
    let affected = dispatch
        .captured
        .as_u64()
        .map_or(changed.len() as u64, |count| count);
    let mut body = Map::new();
    body.insert("changed_entries".into(), json!(changed));
    body.insert("affected".into(), json!(affected));
    body.insert("result".into(), result);
    body.insert("captured_text".into(), json!(captured_text));
    body.insert("original".into(), json!(captured_text));
    body.insert("before".into(), from);
    body.insert("after".into(), after);
    for key in ["included", "included_location", "counts"] {
        body.insert(
            key.into(),
            dispatch.context.get(key).cloned().unwrap_or(Value::Null),
        );
    }
    body.insert(
        "expanded".into(),
        dispatch
            .context
            .get("expanded")
            .cloned()
            .unwrap_or(json!(false)),
    );
    body.insert(
        "children".into(),
        dispatch
            .context
            .get("children")
            .cloned()
            .unwrap_or(json!([])),
    );
    body.insert("label".into(), json!(dispatch.label));
    body.insert("requires_cascade".into(), json!(dispatch.cascade));
    body.extend(dispatch.extra);
    Value::Object(body)
}

fn execute(
    package: &mut HwpxPackage,
    command: &Value,
    projecting: bool,
) -> Result<Value, AuthoringCommandError> {
    let before = xml_snapshot(package);
    let mut dispatch_started = false;
    let result = (|| {
        let action = command.get("type").and_then(Value::as_str).unwrap_or("");
        let before_label = command_preview_label(command, false, None);
        let context = preview_content_context(package, command).map_err(error)?;
        let prior = if matches!(
            action,
            "create_field" | "create_fields" | "rename_field" | "relink_field" | "unset_field"
        ) {
            fields(package).map_err(error)?
        } else {
            Vec::new()
        };
        let target = context.get("target_name").filter(|v| !v.is_null());
        let mut label = command_label(object(command)?, target);
        if matches!(action, "rename_slot" | "rename_option") {
            let snapshot = inspect_slot_regions(package).map_err(error)?;
            let slot_id = command
                .get("slot_id")
                .map_or_else(|| "None".into(), python_str);
            let option_id = (action == "rename_option").then(|| {
                command
                    .get("option_id")
                    .map_or_else(|| "None".into(), python_str)
            });
            let display = region_display_name(&snapshot, &slot_id, option_id.as_deref());
            let display = display.map(Value::String);
            label = command_label(object(command)?, display.as_ref());
        }
        dispatch_started = true;
        let dispatched = dispatch(package, command, action, projecting, &prior, label, context)?;
        let analyzed = analyze_hwpx(package).map_err(error)?;
        if analyzed["diagnostics"]
            .as_array()
            .is_some_and(|v| !v.is_empty())
        {
            let mut source = disposable(package);
            restore(&mut source, &before);
            if analyze_hwpx(&source).map_err(error)?["diagnostics"]
                .as_array()
                .is_some_and(Vec::is_empty)
            {
                return Err(AuthoringCommandError::plain(
                    "명령을 적용하면 문서 구조가 깨집니다.",
                ));
            }
        }
        Ok(impact(
            package,
            &before,
            command,
            &before_label,
            analyzed,
            dispatched,
        ))
    })();
    if result.is_err() {
        restore(package, &before);
    }
    result.map_err(|err| {
        if dispatch_started
            && err.detail.is_none()
            && !err.message.chars().any(|ch| ('가'..='힣').contains(&ch))
        {
            AuthoringCommandError::plain(
                "이 문서의 구조나 고른 범위 때문에 명령을 적용할 수 없습니다.",
            )
        } else {
            err
        }
    })
}

/// Apply one HWPX authoring command atomically, returning the UI impact projection.
pub fn apply_hwpx(
    package: &mut HwpxPackage,
    command: &Value,
) -> Result<Value, AuthoringCommandError> {
    execute(package, command, false)
}

/// Preview a command on disposable XML while leaving the caller's package byte-identical.
pub fn preview_hwpx(
    package: &HwpxPackage,
    command: &Value,
) -> Result<Value, AuthoringCommandError> {
    execute(&mut disposable(package), command, true)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::fields::FieldDocument;
    use hwpx_core::package::{MIMETYPE_NAME, MIMETYPE_VALUE};
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn revert_filled_fields_across_sections_and_table_preserves_other_entries() {
        let field = |id: usize, name: &str, value: &str| {
            format!(
                "<hp:run><hp:ctrl><hp:fieldBegin id='{id}' name='{name}' type='CLICK_HERE'/></hp:ctrl></hp:run><hp:run><hp:t>{value}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='{id}'/></hp:ctrl></hp:run>"
            )
        };
        let section = |body: String| {
            format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>").into_bytes()
        };
        let entry = |name: &str, data: Vec<u8>| PackageEntry {
            name: name.into(),
            data,
            stored: false,
        };
        let first = section(format!(
            "<hp:p>{}{}</hp:p><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p>{}</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>",
            field(1, "계약명", "{{계약명}}"),
            field(2, "계약명", "{{계약명}}"),
            field(3, "공급가액", "{{공급가액}}"),
        ));
        let mut package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.to_vec(),
                    stored: true,
                },
                entry("Contents/section0.xml", first),
                entry(
                    "Contents/section1.xml",
                    section(format!("<hp:p>{}</hp:p>", field(4, "담당자", "{{담당자}}"))),
                ),
                entry(
                    "Contents/section2.xml",
                    section(format!(
                        "<hp:p>{}</hp:p>",
                        field(5, "미작성", "{{ 미작성 }}")
                    )),
                ),
                entry("BinaryData/image.png", vec![0, 1, 2, 255]),
            ],
        };
        for (entry, values) in [
            (
                "Contents/section0.xml",
                vec![("계약명", "정보시스템 구축"), ("공급가액", "1,000,000원")],
            ),
            ("Contents/section1.xml", vec![("담당자", "홍길동")]),
        ] {
            let mut document = FieldDocument::new(&mut package, entry).unwrap();
            for (name, value) in values {
                assert!(document.set_field(name, value).unwrap());
            }
        }
        let before = package.clone();
        let command = json!({"type":"revert_template"});
        let preview = preview_hwpx(&package, &command).unwrap();
        assert_eq!(package, before);
        assert_eq!(preview["affected"], 4);
        assert_eq!(preview["message"], "사라지는 것: 필드 값 4개");
        assert_eq!(
            preview["changed_entries"],
            json!(["Contents/section0.xml", "Contents/section1.xml"])
        );

        let impact = apply_hwpx(&mut package, &command).unwrap();
        assert_eq!(impact["changed_entries"], preview["changed_entries"]);
        for (index, expected) in [
            (
                0,
                vec![
                    ("계약명", "{{계약명}}"),
                    ("계약명", "{{계약명}}"),
                    ("공급가액", "{{공급가액}}"),
                ],
            ),
            (1, vec![("담당자", "{{담당자}}")]),
        ] {
            let document =
                FieldDocument::new(&mut package, &format!("Contents/section{index}.xml")).unwrap();
            let values = document.field_values().unwrap();
            assert_eq!(
                values
                    .iter()
                    .map(|(name, value)| (name.as_str(), value.as_str()))
                    .collect::<Vec<_>>(),
                expected
            );
        }
        assert_eq!(package.entries[3], before.entries[3]);
        assert_eq!(package.entries[4], before.entries[4]);
        assert_eq!(
            crate::template_authoring::document_commands("hwpx", &analyze_hwpx(&package).unwrap())
                [0]["enabled"],
            false
        );
    }

    #[test]
    fn preview_and_cascade_refusal_keep_package_bytes_until_confirmed_apply() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>공통</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>선택</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "BinData/photo.bin".into(),
                    data: vec![1, 2, 3],
                    stored: true,
                },
            ],
        };
        apply_hwpx(&mut package, &json!({"type":"create_slot","entry":"Contents/section0.xml","start_paragraph":0,"end_paragraph":1,"id":"s"})).unwrap();
        apply_hwpx(&mut package, &json!({"type":"create_option","entry":"Contents/section0.xml","start_paragraph":1,"end_paragraph":1,"slot_id":"s","id":"a"})).unwrap();
        let before = package.clone();
        let command = json!({"type":"unwrap","kind":"slot","slot_id":"s"});
        let preview = preview_hwpx(&package, &command).unwrap();
        assert!(preview["requires_cascade"].as_bool().unwrap());
        assert_eq!(package, before);
        let refused = apply_hwpx(&mut package, &command).unwrap_err();
        assert_eq!(refused.to_dict().unwrap()["code"], "cascade_required");
        assert_eq!(package, before);
        let impact = apply_hwpx(
            &mut package,
            &json!({"type":"unwrap","kind":"slot","slot_id":"s","cascade":true}),
        )
        .unwrap();
        assert_eq!(impact["changed_entries"], json!(["Contents/section0.xml"]));
        assert_eq!(package.entries[1], before.entries[1]);
    }

    #[test]
    fn unusable_field_revert_maps_value_error_after_rollback() {
        let filled = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='3' name='A' type='CLICK_HERE'/></hp:ctrl></hp:run><hp:run><hp:t>채운 값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='3'/></hp:ctrl></hp:run></hp:p></hs:sec>"
        );
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='7' name='A' type='CLICK_HERE'/></hp:ctrl></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: filled.into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "Contents/section1.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
            ],
        };
        let before = package.clone();
        let refusal = apply_hwpx(&mut package, &json!({"type":"revert_template"})).unwrap_err();
        assert_eq!(
            refusal.message,
            "이 문서의 구조나 고른 범위 때문에 명령을 적용할 수 없습니다."
        );
        assert_eq!(package, before);
    }

    #[test]
    fn multi_field_command_is_atomic_across_sites_and_refuses_overlap() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>장비 조달청 장비</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        let before = package.clone();
        for fields in [
            Value::Null,
            json!([]),
            json!(["x"]),
            json!([{"name":"A","ranges":[]}]),
        ] {
            let bad = json!({"type":"create_fields","fields":fields});
            assert!(apply_hwpx(&mut package, &bad).is_err());
            assert_eq!(package, before);
        }
        let command = json!({"type":"create_fields","fields":[
            {"name":"품명","ranges":[
                {"entry":"Contents/section0.xml","paragraph":0,"start":7,"end":9},
                {"entry":"Contents/section0.xml","paragraph":0,"start":0,"end":2}
            ]},
            {"name":"기관","ranges":[
                {"entry":"Contents/section0.xml","paragraph":0,"start":3,"end":6}
            ]}
        ]});
        let preview = preview_hwpx(&package, &command).unwrap();
        assert_eq!(package, before);
        assert_eq!(preview["affected"], 3);
        let impact = apply_hwpx(&mut package, &command).unwrap();
        assert_eq!(impact["affected"], 3);
        let analysis = crate::hwpx_authoring_analysis::analyze_hwpx(&package).unwrap();
        let fields = analysis["fields"].as_array().unwrap();
        assert_eq!(
            fields.iter().find(|field| field["name"] == "품명").unwrap()["count"],
            2
        );
        assert_eq!(
            fields.iter().find(|field| field["name"] == "기관").unwrap()["count"],
            1
        );

        let changed = package.clone();
        let overlap = json!({"type":"create_fields","fields":[
            {"name":"A","ranges":[{"entry":"Contents/section0.xml","paragraph":0,"start":0,"end":2}]},
            {"name":"B","ranges":[{"entry":"Contents/section0.xml","paragraph":0,"start":1,"end":3}]}
        ]});
        assert!(apply_hwpx(&mut package, &overlap).is_err());
        assert_eq!(package, changed);
    }
}
