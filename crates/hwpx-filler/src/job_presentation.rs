//! Pure Job panel row and candidate projections over already observed facts.

use crate::data_source::Record;
use crate::dataset_pool::pool_icon_for_kind;
use crate::home_state::{work_mode_label, work_mode_short_label};
use crate::identity_summary::identity_summary;
use crate::job::{Job, work_mode};
use crate::work_candidates::{
    MAIN_TOP_N, TAB_NEEDS_ACTION, browse_candidates, candidate_rows, rank_available, suggested_work,
};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::path::Path;

const TXT_ONBOARDING_NOTE: &str = "저장된 TXT 작업이 없습니다. ‘문서 작업’의 [＋ 새 작업] → 템플릿 탭에서 TXT 템플릿을 선택하고 저장하세요.";
pub const SESSION_DATA_KEY: &str = "session";

pub fn session_data_row(
    name: &str,
    kind: &str,
    path: &str,
    sheet: &str,
    header_row: u64,
    record_count: usize,
) -> Value {
    let mut parts = Vec::new();
    if !sheet.is_empty() {
        parts.push(format!("시트: {sheet}"));
    }
    if header_row > 0 {
        parts.push(format!("헤더 {header_row}행"));
    }
    parts.push(format!("{record_count}행"));
    let icon = pool_icon_for_kind(if kind.is_empty() { "excel" } else { kind });
    json!({"key":SESSION_DATA_KEY,"name":name,"sub":parts.join(" · "),"reason":"","warns":[],
        "badge_label":"사용 중","badge_level":"ok","icon":icon,"selectable":true,"path":path,"actions":[]})
}

pub fn mode_sections(items: &[Value]) -> Vec<Value> {
    let mut modes = Vec::<String>::new();
    for item in items {
        let mode = item
            .get("mode")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .unwrap_or("unsupported");
        if !modes.iter().any(|existing| existing == mode) {
            modes.push(mode.into());
        }
    }
    modes
        .iter()
        .map(|mode| {
            let names = items
                .iter()
                .filter(|item| item.get("mode").and_then(Value::as_str) == Some(mode))
                .filter_map(|item| item.get("name").and_then(Value::as_str))
                .collect::<Vec<_>>();
            json!({"mode":mode,"mode_label":work_mode_label(mode),"names":names})
        })
        .collect()
}
pub fn candidate_payload(
    jobs: &[Job],
    bound: &[Job],
    fields: Option<&[String]>,
    active_name: &str,
    txt_template_count: usize,
    template_missing_by_path: &HashMap<String, bool>,
) -> Result<Value, String> {
    let Some(fields) = fields else {
        return Ok(
            json!({"top":[],"sections":[],"more":0,"needs_count":0,"suggested":"","txt_note":""}),
        );
    };
    let by_name = bound
        .iter()
        .map(|job| (job.name.as_str(), job))
        .collect::<HashMap<_, _>>();
    let ranked = rank_available(bound, fields);
    let suggested = suggested_work(&ranked, active_name);
    let top = ranked
        .iter()
        .take(MAIN_TOP_N)
        .map(|item| {
            let job = by_name
                .get(item.name.as_str())
                .ok_or_else(|| format!("후보 작업이 없습니다: {}", item.name))?;
            let missing = *template_missing_by_path
                .get(&job.template_path)
                .ok_or_else(|| format!("템플릿 상태가 없습니다: {}", job.template_path))?;
            let template_name = Path::new(&job.template_path)
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or_default();
            Ok(
                json!({"name":item.name,"tier":item.tier,"favorited":!job.favorited_at.is_empty(),
            "last_run_at":job.last_run_at,"suggested":item.name==suggested,
            "mode":item.mode,"mode_label":work_mode_short_label(item.mode),"template_name":template_name,
            "template_path":job.template_path,"template_missing":missing,
            "conn_label":if missing{"템플릿 없음"}else{""}}),
            )
        })
        .collect::<Result<Vec<_>, String>>()?;
    let needs_count = candidate_rows(bound, fields)
        .into_iter()
        .filter(|(_, compat)| compat.kind == TAB_NEEDS_ACTION)
        .count();
    let txt_note = if txt_template_count > 0
        && !jobs
            .iter()
            .any(|job| work_mode(&job.template_path) == "text_review_copy")
    {
        TXT_ONBOARDING_NOTE
    } else {
        ""
    };
    Ok(
        json!({"sections":mode_sections(&top),"top":top,"more":ranked.len().saturating_sub(MAIN_TOP_N),
        "needs_count":needs_count,"suggested":suggested,"txt_note":txt_note}),
    )
}
pub fn browse_payload(bound: &[Job], fields: Option<&[String]>, tab: &str, query: &str) -> Value {
    let Some(fields) = fields else {
        return json!({"tab":tab,"query":query,"rows":[],"sections":[],"available_count":0,"needs_count":0,"filtered_out":0});
    };
    let result = browse_candidates(bound, fields, tab, query);
    let rows=result.rows.into_iter().map(|row|json!({"name":row.name,"missing":row.missing,"mode":row.mode,"mode_label":work_mode_short_label(row.mode)})).collect::<Vec<_>>();
    json!({"tab":result.tab,"query":query,"sections":mode_sections(&rows),"rows":rows,
        "available_count":result.available_count,"needs_count":result.needs_count,"filtered_out":result.filtered_out})
}
/// Source columns carried into filename tokens, in mapping order.
pub fn filename_source_columns(job: &Job, present_columns: &[String]) -> Vec<String> {
    let tokens = crate::output_name::pattern_field_tokens(&job.filename_pattern)
        .into_iter()
        .collect::<std::collections::HashSet<_>>();
    let present = present_columns
        .iter()
        .map(String::as_str)
        .collect::<std::collections::HashSet<_>>();
    let mut columns = Vec::new();
    for mapping in &job.mapping.mappings {
        if tokens.contains(&mapping.template_field)
            && crate::mapping::SOURCE_CARRIER_TYPES.contains(&mapping.field_type.as_str())
            && present.contains(mapping.source.as_str())
            && !columns.contains(&mapping.source)
        {
            columns.push(mapping.source.clone());
        }
    }
    columns
}

pub fn record_rows(
    records: &[Record],
    display_order: &[usize],
    selected_indices: &[usize],
    planned_names: &HashMap<usize, String>,
    filename_source_columns: &[String],
) -> Result<Vec<Value>, String> {
    let identity = identity_summary(records, None, filename_source_columns);
    let selected = selected_indices.iter().copied().collect::<HashSet<_>>();
    display_order.iter().map(|&index|records.get(index).map(|record|json!({
        "index":index,"selected":selected.contains(&index),"name":planned_names.get(&index).map_or("",String::as_str),
        "summary":identity.display_for(record)})).ok_or_else(||format!("행 인덱스가 범위를 벗어났습니다: {index}"))).collect()
}
