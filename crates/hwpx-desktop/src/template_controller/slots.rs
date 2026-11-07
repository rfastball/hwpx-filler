//! Slot actions: target id, confirmation text, the locked package mutation, and the done line.

use super::*;

/// The trimmed slot id an action targets; decompiling every slot targets none.
pub(super) fn slot_target(
    action: &str,
    payload: &Map<String, Value>,
) -> Result<String, GraphError> {
    if action == "slot_decompile_all" {
        return Ok(String::new());
    }
    let raw = payload
        .get("slot_id")
        .and_then(Value::as_str)
        .ok_or("slot_id must be a string")?;
    let value = python_trim(raw);
    if value.is_empty() {
        return Err("대상 항목 id 가 비어 있습니다.".into());
    }
    Ok(value.to_owned())
}

/// The confirmation a destructive slot action returns before it touches the file.
pub(super) fn slot_confirmation(
    action: &str,
    path: &Path,
    name: &str,
    slot_id: &str,
) -> Result<Value, GraphError> {
    let text = match action {
        "slot_decompile" => format!(
            "'{slot_id}' 항목을 구간 표기로 되돌립니다.\n되돌린 뒤: '{name}' 은(는) 다시 변환하기 전까지 문서를 만들 수 없습니다.\n한글에서 표기를 고친 뒤 '누름틀·구간 변환'을 다시 하세요."
        ),
        "slot_decompile_all" => {
            let package = read_package(path)?;
            let count = inspect_slots(&package)?.0.len();
            format!(
                "항목 {count}개를 전부 구간 표기로 되돌립니다.\n되돌린 뒤: '{name}' 은(는) 다시 변환하기 전까지 문서를 만들 수 없습니다.\n한글에서 표기를 고친 뒤 '누름틀·구간 변환'을 다시 하세요."
            )
        }
        _ => {
            let package = read_package(path)?;
            let options = inspect_slots(&package)?
                .0
                .into_iter()
                .find(|slot| slot.id == slot_id)
                .map_or(String::new(), |slot| {
                    format!(" · 선택 {}개", slot.options.len())
                });
            format!(
                "'{slot_id}' 항목을 지웁니다.\n사라지는 것: 항목 범위의 본문{options}\n대상 파일: {name}"
            )
        }
    };
    let mut answer =
        json!({"ok":true,"needs_confirm":true,"kind":action,"path":path,"confirm_text":text});
    if action != "slot_decompile_all" {
        answer["slot_id"] = json!(slot_id);
    }
    Ok(answer)
}

/// The requested slot label with Python falsy values read as no label.
pub(super) fn slot_label(payload: &Map<String, Value>) -> String {
    match payload.get("label") {
        None | Some(Value::Null | Value::Bool(false)) => String::new(),
        Some(Value::String(value)) => python_trim(value).to_owned(),
        Some(Value::Number(value)) if value.as_f64() == Some(0.0) => String::new(),
        Some(Value::Array(value)) if value.is_empty() => String::new(),
        Some(Value::Object(value)) if value.is_empty() => String::new(),
        Some(value) => python_repr(value),
    }
}

/// Mutates the package under the caller's directory lock; returns the slot count and whether it was written.
pub(super) fn mutate_slots(
    path: &Path,
    action: &str,
    slot_id: &str,
    label: &str,
) -> Result<(usize, bool), GraphError> {
    let mut package = read_package(path)?;
    let mutated = match action {
        "slot_rename" => {
            rename_slot_label(&mut package, slot_id, (!label.is_empty()).then_some(label))?;
            true
        }
        "slot_decompile" => {
            decompile_slot(&mut package, slot_id)?;
            true
        }
        "slot_decompile_all" => !decompile_structure(&mut package)?.is_empty(),
        "slot_remove" => {
            remove_slot(&mut package, slot_id)?;
            true
        }
        _ => return Err("unknown template slot action".into()),
    };
    if mutated {
        write_bytes_atomic(path, &package.to_bytes()?)?;
    }
    Ok((inspect_slots(&package)?.0.len(), mutated))
}

/// The completed-action line before the template name.
pub(super) fn slot_done_line(action: &str, label: &str, slot_id: &str) -> String {
    match action {
        "slot_rename" if label.is_empty() => format!("항목 이름을 지웠습니다 '{slot_id}'"),
        "slot_rename" => format!("항목 이름을 바꿨습니다 '{slot_id}'"),
        "slot_decompile" => format!("항목을 표기로 되돌렸습니다 '{slot_id}'"),
        "slot_decompile_all" => "전 항목을 표기로 되돌렸습니다".into(),
        _ => format!("항목을 지웠습니다 '{slot_id}'"),
    }
}
