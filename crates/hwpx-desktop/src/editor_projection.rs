//! Read-only snapshot assembly for the editor screen.

use crate::editor_intake::HWPX_RAW_BLOCK;
use chrono::NaiveDateTime;
use hwpx_filler::editor_mapping::EditorMappingModel;
use hwpx_filler::editor_session_state::{
    EditorSessionState, SECTION_BINDING, SECTION_FILENAME, SECTION_TEMPLATE, SECTIONS,
};
use hwpx_filler::job::template_media;
use hwpx_filler::mapping::{SUGGEST_THRESHOLD, suggest_mappings};
use hwpx_filler::mapping_state::row_projection;
use hwpx_filler::output_name::{
    format_seq_token, parse_filename_pattern, pattern_uses_seq, render_output_name, seq_token_pads,
};
use hwpx_filler::partial_gate::PartialGate;
use serde_json::{Map, Value, json};

const NAME_HINT: &str = "템플릿과 데이터 이름에서 미리 채웠습니다. 고쳐도 됩니다.";
const BINDING_CONFIRM_LABEL: &str = "연결 확정";
const DRIFT_TEXT: &str = "작성 당시와 템릿 필드 구성이 다릅니다. 매핑 재검토가 필요할 수 있습니다.";

pub struct EditorSnapshotFacts {
    pub template_name: String,
    pub template_key: String,
    pub template_live: bool,
    pub data_name: String,
    pub data_key: String,
    pub data_row: Value,
    pub data_sheet_tabs: Vec<Value>,
    pub output_folder: Value,
    pub now: NaiveDateTime,
}

fn template_ready(state: &EditorSessionState) -> bool {
    state
        .schema
        .as_ref()
        .is_some_and(|schema| !schema.fields.is_empty())
        && !state.gate_error
        && state.gate.as_ref().is_none_or(PartialGate::can_proceed)
}
pub fn can_advance(state: &EditorSessionState, section: &str) -> bool {
    match section {
        SECTION_TEMPLATE => template_ready(state) && !state.data_path.is_empty(),
        SECTION_BINDING => state
            .model
            .as_ref()
            .is_some_and(EditorMappingModel::is_complete),
        _ => false,
    }
}
pub fn advance_block_reason(state: &EditorSessionState) -> &'static str {
    if !state.raw_block.is_empty() {
        return "";
    }
    if state.gate_error {
        return "템플릿 상태를 확인할 수 없습니다.";
    }
    if state.template_path.is_empty() {
        return "왼쪽에서 템플릿을 고르세요.";
    }
    if state
        .schema
        .as_ref()
        .is_none_or(|schema| schema.fields.is_empty())
    {
        return HWPX_RAW_BLOCK;
    }
    if !template_ready(state) {
        return "이 템플릿은 아직 진행할 수 없습니다. 미해결 토큰을 확인하세요.";
    }
    if state.data_path.is_empty() {
        return "오른쪽에서 데이터를 고르세요.";
    }
    ""
}
fn data_columns(source_fields: &[String]) -> Vec<Value> {
    let mut out = vec![json!({"value":"","label":"열을 고르세요","kind":"none","field":""})];
    out.extend(source_fields.iter().map(
        |field| json!({"value":format!("col:{field}"),"label":field,"kind":"column","field":field}),
    ));
    out.push(json!({"value":"sp:const","label":"고정값…","kind":"const","field":""}));
    out.push(json!({"value":"sp:today","label":"오늘 날짜","kind":"today","field":""}));
    out
}
fn pattern_preview(state: &EditorSessionState, now: NaiveDateTime) -> String {
    if state.section != SECTION_FILENAME
        || template_media(&state.template_path) == "txt"
        || state.pattern.is_empty()
    {
        return String::new();
    }
    let Ok(tokens) = parse_filename_pattern(&Value::String(state.pattern.clone())) else {
        return String::new();
    };
    let values = state
        .model
        .as_ref()
        .map(|model| model.name_token_values(&state.current_record(), Some(now)))
        .unwrap_or_default();
    let Ok((first, _)) = render_output_name(&tokens, &values, 1, Some(now), false) else {
        return String::new();
    };
    if !pattern_uses_seq(&state.pattern) {
        return first;
    }
    let pad = seq_token_pads(&state.pattern).into_iter().next().flatten();
    format!(
        "{first} · {} · {}",
        format_seq_token(pad.as_deref(), 2),
        format_seq_token(pad.as_deref(), 3)
    )
}
fn binding_snapshot(
    state: &EditorSessionState,
    now: NaiveDateTime,
) -> Result<Map<String, Value>, String> {
    let Some(model) = state.model.as_ref() else {
        return Ok(json!({"rows":[],"is_complete":false,"binding_head":{"suggested":0,"needs_confirm":0,"const":0,"promote_label":"","promoted_label":"","unused_columns":0}}).as_object().cloned().unwrap());
    };
    let record = state.current_record();
    let mut rows = Vec::with_capacity(model.rows.len());
    for (index, row) in model.rows.iter().enumerate() {
        let mut projection = row_projection(
            &row.projection_row(),
            &record,
            index,
            &state.source_fields,
            !state.records.is_empty(),
            Some(now),
            "ready",
        )?;
        projection
            .as_object_mut()
            .expect("row projection")
            .remove("source_label");
        projection
            .as_object_mut()
            .expect("row projection")
            .remove("display_label");
        if let Some(spec) = row.spec.as_ref() {
            projection["inferred_type"] = json!(spec.inferred_type);
            projection["context"] = json!(spec.context);
        }
        projection["contract_reason"] = json!(row.contract_reason());
        if !row.auto_confirmed_exact && !row.contract_state_label().is_empty() {
            projection["state_label"] = json!(row.contract_state_label());
        }
        rows.push(projection);
    }
    let (filled, empty, unmapped) = model
        .preview_counts(&record, Some(now))
        .map_err(|error| error.to_string())?;
    let preview_empties = model
        .preview_empties(&record, Some(now))
        .map_err(|error| error.to_string())?;
    let (suggested, needs, constant, _) = model.counts();
    let promoted = model
        .rows
        .iter()
        .any(|row| row.confirmed && !row.auto_confirmed_exact);
    Ok(json!({
        "rows": rows,
        "counts":{"filled":filled,"empty":empty,"unmapped":unmapped},
        "preview_empties": preview_empties,
        "preview_index": if state.records.is_empty(){0}else{state.preview_index%state.records.len()+1},
        "preview_count":state.records.len(),"is_complete":model.is_complete(),
        "schema_only":model.source_fields.is_empty(),
        "binding_head":{"suggested":suggested,"needs_confirm":needs,"const":constant,
            "promote_label":format!("제안 {suggested}건 모두 확인"),
            "promoted_label":if promoted{"제안을 모두 확인했습니다"}else{"확인할 제안이 없습니다"},
            "unused_columns":model.unused_source_fields().len()}
    }).as_object().cloned().unwrap())
}
fn pairing_counts(
    state: &EditorSessionState,
    fields: &[String],
    ready: bool,
) -> (usize, usize, &'static str) {
    if !ready || state.section != SECTION_TEMPLATE {
        (0, 0, "")
    } else if state.model.as_ref().is_some()
        && state.model_key.as_ref() == Some(&state.model_key_now())
    {
        let auto = state
            .model
            .as_ref()
            .unwrap()
            .rows
            .iter()
            .filter(|row| row.confirmed)
            .count();
        (
            auto,
            state
                .model
                .as_ref()
                .unwrap()
                .rows
                .len()
                .saturating_sub(auto),
            "model",
        )
    } else {
        let auto = suggest_mappings(
            fields,
            &state.source_fields,
            &Default::default(),
            SUGGEST_THRESHOLD,
        )
        .len();
        (auto, fields.len().saturating_sub(auto), "preview")
    }
}

pub fn snapshot(state: &EditorSessionState, facts: &EditorSnapshotFacts) -> Result<Value, String> {
    let field_names = state
        .schema
        .as_ref()
        .map_or_else(Vec::new, |schema| schema.field_names());
    let ready =
        !state.template_path.is_empty() && !state.data_path.is_empty() && !field_names.is_empty();
    let (auto, confirm, basis) = pairing_counts(state, &field_names, ready);
    let detail = if state.template_path.is_empty() {
        json!({"available":false,"reason":""})
    } else if facts.template_live {
        json!({"available":true,"reason":""})
    } else {
        json!({"available":false,"reason":"서식 폴더 밖의 템플릿이라 항목 상세를 열 수 없습니다. 설정에서 서식 폴더를 확인하세요."})
    };
    let data_options = data_columns(&state.source_fields);
    let sample_rows = state
        .records
        .iter()
        .take(3)
        .map(|row| {
            state
                .source_fields
                .iter()
                .map(|field| {
                    row.get(field)
                        .and_then(Value::as_str)
                        .unwrap_or("")
                        .to_owned()
                })
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();
    let dirty = state.dirty_sections();
    let revisions = state.base.as_ref().map_or_else(
        || json!({}),
        |base| json!({"template":base.template_revision,"binding":base.binding_revision}),
    );
    let drift = state
        .loaded_provenance
        .get("template_fields")
        .and_then(Value::as_str)
        .filter(|text| {
            !text.is_empty() && !field_names.is_empty() && *text != field_names.join(" · ")
        })
        .map_or("", |_| DRIFT_TEXT);
    let mut view = json!({
        "section":state.section,"sections":SECTIONS,
        "reachable":SECTIONS.into_iter().map(|section|(section.to_owned(),json!(if state.editing_origin.is_empty(){can_advance(state,section)}else{true}))).collect::<Map<String,Value>>(),
        "is_draft":state.is_draft(),"dirty_sections":dirty,"dirty":!dirty.is_empty()||state.has_unsaved_work(),
        "changes":state.changes(),"context":state.context,"revisions":revisions,
        "template_path":state.template_path,"template_name":facts.template_name,
        "template_media":if state.template_path.is_empty(){""}else{template_media(&state.template_path)},
        "field_count":field_names.len(),"fields":state.schema.as_ref().map_or_else(Vec::new,|schema|schema.fields.clone()),
    });
    let data = json!({
        "raw_block":state.raw_block,"session_detail":detail,"schema_drift":drift,
        "gate":state.gate.as_ref().map(PartialGate::snapshot),"gate_error":state.gate_error,
        "data_path":state.data_path,"data_name":facts.data_name,"data_sheet":state.data_sheet,
        "data_header_row":state.data_header_row,"data_kind":state.data_kind,"data_pool_key":state.data_pool_key,
        "data_sheet_tabs":facts.data_sheet_tabs,"record_count":state.records.len(),"source_fields":state.source_fields,
        "data_column_options":data_options,"sample_rows":sample_rows,"name":state.job_name,
        "job_name_is_derived":state.job_name_is_derived,
        "name_hint":if state.job_name_is_derived{NAME_HINT}else{""},"pattern":state.pattern,
        "output_folder":facts.output_folder,"binding_confirm":{"pending":state.binding_confirm_pending,"label":BINDING_CONFIRM_LABEL},
        "unconfirm_undo_count":state.unconfirm_undo.len(),"editing_origin":state.editing_origin,
        "pairing":{"ready":ready,"template_name":facts.template_name,"data_name":facts.data_name,
            "template_key":facts.template_key,"data_key":facts.data_key,"data_row":facts.data_row,
            "field_count":field_names.len(),"column_count":state.source_fields.len(),"auto_count":auto,
            "confirm_count":confirm,"basis":basis,
            "advance_block_reason":if state.raw_block.is_empty(){advance_block_reason(state)}else{&state.raw_block}},
        "pattern_preview":pattern_preview(state,facts.now),"notice":state.current_notice()
    });
    for (key, value) in data.as_object().expect("data projection") {
        view[key] = value.clone();
    }
    for (key, value) in binding_snapshot(state, facts.now)? {
        view[key] = value;
    }
    Ok(view)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn pairing_uses_proposals_until_the_current_model_owns_confirmation() {
        let fields = vec!["계약금액".into(), "존재하지않는들판xyz".into()];
        let mut state = EditorSessionState::default();
        assert_eq!(pairing_counts(&state, &fields, false), (0, 0, ""));
        assert_eq!(pairing_counts(&state, &fields, true), (0, 2, "preview"));
        state.source_fields = vec!["계약_금액".into()];
        assert_eq!(pairing_counts(&state, &[], true), (0, 0, "preview"));
        assert_eq!(pairing_counts(&state, &fields, true), (1, 1, "preview"));
        assert!(state.model.is_none());
        state.model = Some(EditorMappingModel::from_field_names(
            &fields,
            &state.source_fields,
            &Default::default(),
            &Default::default(),
        ));
        state.model_key = Some(state.model_key_now());
        assert_eq!(pairing_counts(&state, &fields, true), (0, 2, "model"));
        state
            .model
            .as_mut()
            .unwrap()
            .set_confirmed(0, true)
            .unwrap();
        assert_eq!(pairing_counts(&state, &fields, true), (1, 1, "model"));
        state.data_path = "다른 데이터.csv".into();
        assert_eq!(pairing_counts(&state, &fields, true), (1, 1, "preview"));
        assert!(state.model.as_ref().unwrap().rows[0].confirmed);
        state.section = SECTION_BINDING.into();
        assert_eq!(pairing_counts(&state, &fields, true), (0, 0, ""));
    }
}
