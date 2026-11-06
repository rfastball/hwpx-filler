//! Pool column serialization from the registry's projected rows and notices.

use hwpx_filler::dataset_pool::{DatasetPoolRow, PoolView, pool_icon_for_kind};
use serde_json::{Value, json};

pub(super) fn row_json(row: &DatasetPoolRow) -> Value {
    let reason = row.select_block_reason();
    let sub = if row.note.is_empty() {
        row.reference.clone()
    } else {
        format!("{} · {}", row.reference, row.note)
    };
    json!({
        "key":row.key,"name":row.name,"sub":sub,"reason":reason,
        "warns":[],"badge_label":row.badge_label,"badge_level":row.badge_level,
        "icon":pool_icon_for_kind(&row.kind),"selectable":reason.is_empty(),"path":row.locate_path,
        "actions":row.actions().iter().map(|action|json!({"key":action.key,"label":action.label})).collect::<Vec<_>>(),
    })
}

pub(super) fn notices(view: &PoolView) -> Vec<Value> {
    let mut output = view
        .corrupted
        .iter()
        .map(|item| {
            json!({
                "level":"danger",
                "text":format!("⚠ 손상된 등록 데이터: {} — {}",item.file_name,item.error),
                "actions":[]
            })
        })
        .collect::<Vec<_>>();
    for group in &view.duplicate_keys {
        let members = group
            .iter()
            .filter_map(|key| view.rows.iter().find(|row| &row.key == key))
            .collect::<Vec<_>>();
        if let Some(first) = members.first() {
            output.push(json!({
                "level":"warn",
                "text":format!("같은 데이터({})를 가리키는 등록이 {}건입니다. 남길 등록을 골라 정리하세요.",first.reference,members.len()),
                "actions":members.iter().map(|row|json!({
                    "key":"resolve_duplicate","label":format!("'{}' 남기기",row.name),"payload":{"keep":row.key}
                })).collect::<Vec<_>>()
            }));
        }
    }
    output
}
