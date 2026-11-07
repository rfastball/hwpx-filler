//! Authoring-screen host verbs that move a document or its trial files through a dialog.

use super::{HostCall, current_applied_template, listed_template_path};
use crate::dialogs::{hwpx_file_filter, open_file_dialog, save_file_dialog};
use crate::workspace_runtime::RuntimeResources;
use crate::workspace_switch::ScreenController;
use serde_json::{Value, json};
use std::path::Path;

pub(super) fn open_authoring_document(
    resources: &RuntimeResources,
    call: &HostCall<'_>,
) -> Result<Value, String> {
    let supplied = call.args.first().and_then(Value::as_str).unwrap_or("");
    let as_template = call.args.get(1).and_then(Value::as_bool).unwrap_or(false);
    let path = if supplied.is_empty() {
        open_file_dialog(
            vec![hwpx_file_filter(), ("모든 파일".into(), "*.*".into())],
            call.hwnd()?,
            String::new(),
        )
        .map_err(|e| e.to_string())?
    } else {
        Some(supplied.into())
    };
    let Some(path) = path else {
        return Ok(Value::Null);
    };
    if !supplied.is_empty() && !openable_supplied_path(resources, Path::new(&path))? {
        return Err("현재 템플릿 목록에 없는 경로입니다.".into());
    }
    resources
        .authoring
        .open_path(Path::new(&path), as_template)
        .map_err(|e| e.to_string())
}

/// A caller-supplied path opens only when it is a listed template or a work's applied copy.
fn openable_supplied_path(resources: &RuntimeResources, path: &Path) -> Result<bool, String> {
    let media = path
        .extension()
        .and_then(|v| v.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    Ok(
        listed_template_path(&resources.templates.path(), &media, path)?
            || current_applied_template(resources, path)?,
    )
}

/// The session's current content, refused with `changed` when its revision moved on.
fn current_content(
    resources: &RuntimeResources,
    session_id: &str,
    revision: u64,
    changed: &str,
) -> Result<Value, String> {
    let content = resources
        .authoring
        .dispatch("content", &json!({"session_id":session_id}))
        .map_err(|e| e.to_string())?;
    if content["revision"].as_u64() != Some(revision) {
        return Err(changed.into());
    }
    Ok(content)
}

pub(super) fn save_authoring_document(
    resources: &RuntimeResources,
    call: &HostCall<'_>,
) -> Result<Value, String> {
    let id = call.string(0)?;
    let revision = call
        .args
        .get(1)
        .and_then(Value::as_u64)
        .ok_or("문서 판본이 올바르지 않습니다.")?;
    let content = current_content(
        resources,
        id,
        revision,
        "문서가 변경되었습니다. 다시 저장하세요.",
    )?;
    let media = content["media"].as_str().ok_or("문서 매체가 없습니다.")?;
    let stem = content["source_stem"].as_str().unwrap_or("");
    let name = if stem.is_empty() {
        format!("새 템플릿.{media}")
    } else {
        format!("{stem}_템플릿.{media}")
    };
    let path = save_file_dialog(
        name,
        vec![(media.to_ascii_uppercase(), format!("*.{media}"))],
        media.into(),
        call.hwnd()?,
    )
    .map_err(|e| e.to_string())?;
    match path {
        Some(path) => resources
            .authoring
            .save_to_path(id, revision, Path::new(&path))
            .map_err(|e| e.to_string()),
        None => Ok(Value::Null),
    }
}

pub(super) fn authoring_cases_file(
    resources: &RuntimeResources,
    call: &HostCall<'_>,
) -> Result<Value, String> {
    let session_id = call.string(0)?;
    let action = call.string(1)?;
    resources
        .authoring
        .dispatch("content", &json!({"session_id":session_id}))
        .map_err(|e| e.to_string())?;
    let filters = vec![("시험 케이스 JSON".into(), "*.json".into())];
    match action {
        "import" => match open_file_dialog(filters, call.hwnd()?, String::new())
            .map_err(|e| e.to_string())?
        {
            Some(path) => resources
                .authoring
                .import_cases_path(session_id, Path::new(&path))
                .map_err(|e| e.to_string()),
            None => Ok(Value::Null),
        },
        "export" => match save_file_dialog(
            "시험 케이스.json".into(),
            filters,
            "json".into(),
            call.hwnd()?,
        )
        .map_err(|e| e.to_string())?
        {
            Some(path) => resources
                .authoring
                .export_cases_path(session_id, Path::new(&path))
                .map_err(|e| e.to_string()),
            None => Ok(Value::Null),
        },
        _ => Err("시험 자료 파일 명령이 잘못되었습니다.".into()),
    }
}

pub(super) fn export_authoring_result(
    resources: &RuntimeResources,
    call: &HostCall<'_>,
) -> Result<Value, String> {
    let session_id = call.string(0)?;
    let revision = call
        .args
        .get(1)
        .and_then(Value::as_u64)
        .ok_or("문서가 변경되었습니다. 다시 시험하세요.")?;
    let content = current_content(
        resources,
        session_id,
        revision,
        "문서가 변경되었습니다. 다시 시험하세요.",
    )?;
    let media = content["media"].as_str().ok_or("문서 매체가 없습니다.")?;
    let name = resources
        .authoring
        .export_result_name(session_id)
        .map_err(|e| e.to_string())?;
    match save_file_dialog(
        name,
        vec![(media.to_ascii_uppercase(), format!("*.{media}"))],
        media.into(),
        call.hwnd()?,
    )
    .map_err(|e| e.to_string())?
    {
        Some(path) => resources
            .authoring
            .export_result_path(session_id, revision, Path::new(&path))
            .map_err(|e| e.to_string()),
        None => Ok(Value::Null),
    }
}

pub(super) fn import_template_file(
    resources: &RuntimeResources,
    call: &HostCall<'_>,
) -> Result<Value, String> {
    let screen = call.string(0)?;
    let path = open_file_dialog(
        vec![("HWPX·TXT 템플릿".into(), "*.hwpx;*.txt".into())],
        call.hwnd()?,
        String::new(),
    )
    .map_err(|e| e.to_string())?;
    let Some(path) = path else {
        return Ok(Value::Null);
    };
    let result: Result<String, crate::workspace_switch::GraphError> = (|| {
        let dest = resources
            .template_files
            .copy_into_library(Path::new(&path))?;
        if screen == "editor" {
            Ok(resources.editor.adopt_imported_template(&dest)?)
        } else {
            Err("가져온 템플릿을 받을 화면이 아닙니다.".into())
        }
    })();
    Ok(match result {
        Ok(name) => json!(name),
        Err(error) => json!(format!("ERROR: {error}")),
    })
}
