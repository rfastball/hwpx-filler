//! Shared read-only mapping row projection for editor and library detail.

use crate::format_engine::parse_dt;
use crate::format_engine::presets;
use crate::job::MISSING_MARKER;
use crate::mapping::{FieldMapping, MappingError, MappingProfile, SOURCE_CARRIER_TYPES};
use crate::schema::infer_type;
use crate::text_slice::TextSlice;
use chrono::NaiveDateTime;
use regex::Regex;
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::sync::OnceLock;

fn sniff_txt_kind(column: &str, records: &[Map<String, Value>]) -> &'static str {
    static AMOUNT: OnceLock<Regex> = OnceLock::new();
    static DATE1: OnceLock<Regex> = OnceLock::new();
    static DATE2: OnceLock<Regex> = OnceLock::new();
    let amount = AMOUNT
        .get_or_init(|| Regex::new(r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*원?$").unwrap());
    let date1 = DATE1.get_or_init(|| Regex::new(r"^\d{4}\D+\d{1,2}\D+\d{1,2}(\D.*)?$").unwrap());
    let date2 = DATE2.get_or_init(|| Regex::new(r"^\d{8}(\D.*)?$").unwrap());
    let values = records
        .iter()
        .filter_map(|record| record.get(column))
        .filter(|value| !value.is_null())
        .map(|value| match value {
            Value::String(text) => text.clone(),
            Value::Bool(flag) => {
                if *flag {
                    "True".into()
                } else {
                    "False".into()
                }
            }
            _ => value.to_string(),
        })
        .map(|text| crate::structure_scan::python_trim(&text).to_owned())
        .filter(|text| !text.is_empty())
        .collect::<Vec<_>>();
    if !values.is_empty() && values.iter().all(|value| amount.is_match(value)) {
        "amount"
    } else if !values.is_empty()
        && values.iter().all(|value| {
            (date1.is_match(value) || date2.is_match(value)) && parse_dt(value).is_some()
        })
    {
        "date"
    } else {
        "text"
    }
}

/// Fixed TXT review rows: exact source-name matches are live, then saved human rules win.
pub fn txt_live_profile(
    template: &str,
    records: &[Map<String, Value>],
    saved: &MappingProfile,
) -> Result<MappingProfile, MappingError> {
    txt_live_profile_from_rows(&txt_review_rows(template, records, saved))
}

pub fn txt_review_rows(
    template: &str,
    records: &[Map<String, Value>],
    saved: &MappingProfile,
) -> Vec<RowState> {
    let mut rows = Vec::new();
    for field in crate::text_render::template_fields(template) {
        if let Some(persisted) = saved
            .mappings
            .iter()
            .rev()
            .find(|row| row.template_field == field)
        {
            rows.push(RowState::from_mapping(persisted));
        } else if records
            .first()
            .is_some_and(|record| record.contains_key(&field))
        {
            let mut row = RowState::empty(&field);
            row.source = field;
            row.field_type = sniff_txt_kind(&row.source, records).into();
            row.confirmed = true;
            row.auto_confirmed_exact = true;
            rows.push(row);
        } else {
            rows.push(RowState::empty(&field));
        }
    }
    rows
}
pub fn txt_live_profile_from_rows(rows: &[RowState]) -> Result<MappingProfile, MappingError> {
    MappingProfile::new(
        "",
        rows.iter()
            .filter(|row| row.has_content())
            .map(RowState::to_mapping)
            .collect(),
        Map::new(),
    )
}

pub const PENDING_PREVIEW_MARK: &str = "—";

#[derive(Clone, Debug)]
pub struct RowState {
    pub template_field: String,
    pub source: String,
    pub field_type: String,
    pub constant: String,
    pub fmt: String,
    pub slice: Option<TextSlice>,
    pub confirmed: bool,
    pub touched: bool,
    pub suggestion_score: f64,
    pub auto_confirmed_exact: bool,
}
impl RowState {
    fn empty(name: &str) -> Self {
        Self {
            template_field: name.into(),
            source: String::new(),
            field_type: match infer_type(name) {
                "date" => "date",
                "amount" => "amount",
                _ => "text",
            }
            .into(),
            constant: String::new(),
            fmt: String::new(),
            slice: None,
            confirmed: false,
            touched: false,
            suggestion_score: 0.0,
            auto_confirmed_exact: false,
        }
    }
    fn from_mapping(mapping: &FieldMapping) -> Self {
        Self {
            template_field: mapping.template_field.clone(),
            source: mapping.source.clone(),
            field_type: mapping.field_type.clone(),
            constant: mapping.constant.clone(),
            fmt: mapping.fmt.clone(),
            slice: mapping.slice.clone(),
            confirmed: true,
            touched: true,
            suggestion_score: 0.0,
            auto_confirmed_exact: false,
        }
    }
    fn has_content(&self) -> bool {
        matches!(self.field_type.as_str(), "const" | "today") || !self.source.is_empty()
    }
    fn status(&self) -> &'static str {
        if self.confirmed {
            "confirmed"
        } else if !self.has_content() {
            "needs_source"
        } else if !self.touched {
            "suggested"
        } else {
            "edited"
        }
    }
    fn source_kind(&self) -> &'static str {
        match self.field_type.as_str() {
            "const" => "const",
            "today" => "today",
            _ if !self.source.is_empty() => "column",
            _ => "",
        }
    }
    fn to_mapping(&self) -> FieldMapping {
        FieldMapping::new(
            &self.template_field,
            &self.source,
            &self.field_type,
            &self.constant,
            &self.fmt,
            self.slice.clone(),
        )
        .expect("restored mapping")
    }
}

pub fn profile_source_vocabulary(profile: &MappingProfile) -> Vec<String> {
    let mut seen = HashSet::new();
    profile
        .mappings
        .iter()
        .filter(|mapping| !mapping.source.is_empty() && seen.insert(mapping.source.clone()))
        .map(|mapping| mapping.source.clone())
        .collect()
}

/// The library's template-based rows never auto-connect to same-named data columns.
pub fn library_rows(fields: Option<&[String]>, profile: &MappingProfile) -> Vec<RowState> {
    match fields {
        Some(fields) => fields
            .iter()
            .map(|field| {
                profile
                    .mappings
                    .iter()
                    .rev()
                    .find(|mapping| mapping.template_field == *field)
                    .map_or_else(|| RowState::empty(field), RowState::from_mapping)
            })
            .collect(),
        None => profile
            .mappings
            .iter()
            .map(RowState::from_mapping)
            .collect(),
    }
}

fn ordinal(index: i64) -> String {
    const NATIVE: [&str; 10] = [
        "첫째",
        "둘째",
        "셋째",
        "넷째",
        "다섯째",
        "여섯째",
        "일곱째",
        "여덟째",
        "아홉째",
        "열째",
    ];
    if index == -1 {
        return "마지막".into();
    }
    if index < 0 {
        return format!("끝에서 {}", ordinal(-index));
    }
    NATIVE
        .get(index.saturating_sub(1) as usize)
        .map_or_else(|| format!("{index}번째"), |word| (*word).into())
}
fn slot(slice: &TextSlice, key: &str) -> String {
    slice.to_dict().get(key).map_or_else(
        || "None".into(),
        |value| match value {
            Value::String(value) => value.clone(),
            Value::Null => "None".into(),
            value => value.to_string(),
        },
    )
}
pub(crate) fn slice_label(slice: Option<&TextSlice>) -> String {
    let Some(slice) = slice else {
        return "+ 가공".into();
    };
    match slice.mode() {
        "before" => format!("‘{}’ 앞까지", slot(slice, "delimiter")),
        "after" => format!("‘{}’ 뒤부터", slot(slice, "delimiter")),
        "between" => format!(
            "‘{}’ 뒤부터 ‘{}’ 앞까지",
            slot(slice, "open"),
            slot(slice, "close")
        ),
        "split" => format!(
            "‘{}’로 나눈 조각 중 {}",
            slot(slice, "delimiter"),
            ordinal(slot(slice, "index").parse().unwrap_or(1))
        ),
        "head" => format!("앞에서 {}글자", slot(slice, "count")),
        "tail" => format!("뒤에서 {}글자", slot(slice, "count")),
        "chars" if slot(slice, "length") == "None" => {
            format!("{}번째 글자부터", slot(slice, "start"))
        }
        "chars" => format!(
            "{}번째 글자부터 {}글자",
            slot(slice, "start"),
            slot(slice, "length")
        ),
        "replace" => format!(
            "‘{}’ 대신 ‘{}’",
            slot(slice, "find"),
            slot(slice, "replace")
        ),
        _ => format!("‘{}’ 지우기", slot(slice, "find")),
    }
}
fn method(mode: &str, parts: Vec<Value>) -> Value {
    let missable = matches!(mode, "before" | "after" | "between" | "split" | "chars");
    json!({
        "mode": mode, "parts": parts,
        "miss_choice": matches!(mode, "before" | "after" | "between"),
        "on_missing": if missable { Some("keep") } else { None },
    })
}
fn text_input(key: &str, label: &str, wide: bool) -> Value {
    json!({"input": key, "kind":"text", "label": label, "wide": wide})
}
fn number_input(key: &str, label: &str, optional: bool) -> Value {
    json!({"input": key, "kind":"number", "label": label, "optional": optional})
}
fn slice_methods(slice: Option<&TextSlice>) -> Value {
    let mut indexes = vec![1, 2, 3, -1];
    if let Some(slice) = slice.filter(|slice| slice.mode() == "split")
        && let Ok(index) = slot(slice, "index").parse::<i64>()
        && !indexes.contains(&index)
    {
        indexes.push(index);
    }
    indexes.sort_by(|left, right| match (left > &0, right > &0) {
        (true, false) => std::cmp::Ordering::Less,
        (false, true) => std::cmp::Ordering::Greater,
        (true, true) => left.cmp(right),
        (false, false) => right.cmp(left),
    });
    let ordinal_input = json!({"input":"index", "kind":"ordinal", "label":"몇째 조각",
        "options": indexes.iter().map(|index| json!({"value":index,"label":ordinal(*index)})).collect::<Vec<_>>()});
    json!([
        {"label":"일부만 쓰기", "methods":[
            method("before", vec![text_input("delimiter","앞까지의 기준 글자",false),json!({"text":"앞까지"})]),
            method("after", vec![text_input("delimiter","뒤부터의 기준 글자",false),json!({"text":"뒤부터"})]),
            method("between", vec![text_input("open","뒤부터의 기준 글자",false),json!({"text":"뒤부터"}),text_input("close","앞까지의 기준 글자",false),json!({"text":"앞까지"})]),
            method("split", vec![text_input("delimiter","나누는 글자",false),json!({"text":"로 나눈 조각 중","attach":true}),ordinal_input]),
            method("head", vec![json!({"text":"앞에서"}),number_input("count","앞에서 글자 수",false),json!({"text":"글자","attach":true})]),
            method("tail", vec![json!({"text":"뒤에서"}),number_input("count","뒤에서 글자 수",false),json!({"text":"글자","attach":true})]),
            method("chars", vec![number_input("start","몇 번째 글자부터",false),json!({"text":"번째 글자부터","attach":true}),number_input("length","글자 수",true),json!({"text":"글자","attach":true})]),
        ]},
        {"label":"글자 고치기", "methods":[
            method("replace", vec![text_input("find","찾을 글자",true),json!({"text":"대신"}),text_input("replace","바꿀 글자",true)]),
            method("remove", vec![text_input("find","지울 글자",true),json!({"text":"지우기"})]),
        ]},
    ])
}
fn display_options(source_kind: &str) -> Value {
    if source_kind == "const" {
        return json!([]);
    }
    let kinds: &[&str] = if source_kind == "today" {
        &["today"]
    } else {
        &["text", "date", "amount"]
    };
    Value::Array(
        kinds
            .iter()
            .filter_map(|kind| {
                let options = presets(kind).into_iter().map(|(label, code)| json!({
            "value": format!("{kind}:{code}"), "label": label, "type": kind, "fmt": code,
        })).collect::<Vec<_>>();
                (!options.is_empty()).then(|| {
                    json!({"label": match *kind {
            "date" => "날짜", "amount" => "금액", "today" => "오늘 날짜", _ => "텍스트",
        }, "options": options})
                })
            })
            .collect(),
    )
}

/// Preview kind/text and empty/error flags from the mapping's own value,
/// once the row is past the first-row pending/error short-circuit.
fn resolve_mapping_preview(
    row: &RowState,
    record: &Map<String, Value>,
    now: Option<NaiveDateTime>,
) -> (&'static str, String, bool, bool) {
    match row.to_mapping().value_for(record, now) {
        Err(_) => ("error", String::new(), false, true),
        Ok(_) if !row.has_content() => ("none", String::new(), false, false),
        Ok(value)
            if value.is_empty() && !(row.field_type == "const" && row.constant.is_empty()) =>
        {
            (
                "missing",
                MISSING_MARKER.replace("{field}", &row.template_field),
                true,
                false,
            )
        }
        Ok(value) => ("value", value, false, false),
    }
}
/// Preview kind/text and empty/error flags. `first_row_state` is explicit so
/// unread data is never shown as missing output.
fn resolve_preview(
    row: &RowState,
    record: &Map<String, Value>,
    now: Option<NaiveDateTime>,
    first_row_state: &str,
) -> (&'static str, String, bool, bool) {
    if first_row_state == "pending" {
        return ("pending", PENDING_PREVIEW_MARK.into(), false, false);
    }
    if first_row_state == "error" {
        return ("error", String::new(), false, true);
    }
    resolve_mapping_preview(row, record, now)
}
/// Source kind/value/missing-label triple for the row's bound source.
fn resolve_source(row: &RowState, source_fields: &[String]) -> (&'static str, String, String) {
    let source_kind = row.source_kind();
    let source_value = match source_kind {
        "column" => format!("col:{}", row.source),
        "const" | "today" => format!("sp:{source_kind}"),
        _ => String::new(),
    };
    let source_missing_label = if source_kind == "column" && !source_fields.contains(&row.source) {
        format!("{} (데이터에 없음)", row.source)
    } else {
        String::new()
    };
    (source_kind, source_value, source_missing_label)
}
/// Human label for the row's confirmation state.
fn resolve_state_label(auto_confirmed_exact: bool, state: &str) -> &'static str {
    if auto_confirmed_exact {
        return "자동확정 · 이름 일치";
    }
    match state {
        "confirmed" => "확인",
        "suggested" => "제안",
        _ => "확인 필요",
    }
}
/// Whether a text slice applies to this row's current source/type.
fn slice_enabled_for(row: &RowState) -> bool {
    !row.source.is_empty() && SOURCE_CARRIER_TYPES.contains(&row.field_type.as_str())
}
/// Display text for the source column/value, preferring the missing-label.
fn resolve_source_label(source_kind: &str, source_missing_label: &str, row: &RowState) -> String {
    if !source_missing_label.is_empty() {
        return source_missing_label.to_string();
    }
    match source_kind {
        "column" => row.source.clone(),
        "const" => format!("고정값… {}", row.constant).trim_end().into(),
        "today" => "오늘 날짜".into(),
        _ => "열을 고르세요".into(),
    }
}
/// Existing editor/library row shape. `first_row_state` is explicit so unread data is never shown as missing output.
pub fn row_projection(
    row: &RowState,
    record: &Map<String, Value>,
    index: usize,
    source_fields: &[String],
    has_records: bool,
    now: Option<NaiveDateTime>,
    first_row_state: &str,
) -> Result<Value, String> {
    if !["ready", "pending", "error"].contains(&first_row_state) {
        return Err(format!("알 수 없는 첫 행 상태: {first_row_state}"));
    }
    let (preview_kind, preview, empty, preview_error) =
        resolve_preview(row, record, now, first_row_state);
    let (source_kind, source_value, source_missing_label) = resolve_source(row, source_fields);
    let state = row.status();
    let state_label = resolve_state_label(row.auto_confirmed_exact, state);
    let score = (row.suggestion_score * 1000.0).round_ties_even() / 1000.0;
    let mut projection = json!({
        "index": index, "template_field": row.template_field,
        "inferred_type": "", "context": "", "source": row.source,
        "type": row.field_type, "const": row.constant, "fmt": row.fmt,
        "display_options": display_options(source_kind),
        "display_value": format!("{}:{}", row.field_type, row.fmt),
        "slice": row.slice.as_ref().map(TextSlice::to_dict),
        "slice_label": slice_label(row.slice.as_ref()),
        "slice_enabled": slice_enabled_for(row),
        "slice_methods": slice_methods(row.slice.as_ref()),
        "confirmed": row.confirmed, "touched": row.touched,
        "has_content": row.has_content(),
        "confirmable": row.has_content() || row.confirmed,
        "revertable": row.touched && !row.confirmed && has_records,
        "suggestion_score": score,
        "preview": preview, "preview_kind": preview_kind,
        "preview_empty": empty, "preview_error": preview_error,
        "row_state": state, "state_label": state_label,
        "contract_reason": "", "source_kind": source_kind,
        "source_value": source_value, "source_missing_label": source_missing_label,
    });
    let source_label = resolve_source_label(source_kind, &source_missing_label, row);
    let display_label = presets(&row.field_type)
        .into_iter()
        .find_map(|(label, code)| (code == row.fmt).then_some(label))
        .unwrap_or(PENDING_PREVIEW_MARK);
    projection["source_label"] = Value::String(source_label);
    projection["display_label"] = Value::String(display_label.into());
    Ok(projection)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{RowState, row_projection, txt_live_profile};
    use crate::format_engine::{presets, render};
    use crate::mapping::{FieldMapping, MappingProfile};
    use serde_json::json;

    fn assert_slice_presentation_fixtures() {
        let web: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/js/fixtures/slice_popover.json"
        ))
        .unwrap();
        assert_eq!(super::slice_methods(None), web["methods"]);
        let split = crate::text_slice::TextSlice::from_dict(
            &json!({"mode":"split","delimiter":",","index":5}),
        )
        .unwrap();
        assert_eq!(super::slice_methods(Some(&split)), web["methods_split5"]);
        let cases: serde_json::Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/editor_slice.json"))
                .unwrap();
        for case in cases.as_array().unwrap() {
            let args = &case["args"];
            let name = case["function"].as_str().unwrap();
            if ![
                "ordinal_label",
                "slice_label",
                "slice_methods",
                "split_index_options",
            ]
            .contains(&name)
            {
                continue;
            }
            let actual = if name == "ordinal_label" {
                json!(super::ordinal(args[0].as_i64().unwrap()))
            } else {
                let slice = (!args[0].is_null())
                    .then(|| crate::text_slice::TextSlice::from_dict(&args[0]).unwrap());
                match name {
                    "slice_label" => json!(super::slice_label(slice.as_ref())),
                    "slice_methods" => super::slice_methods(slice.as_ref()),
                    _ => {
                        super::slice_methods(slice.as_ref())[0]["methods"][3]["parts"][2]["options"]
                            .clone()
                    }
                }
            };
            assert_eq!(actual, case["expected"], "{case}");
        }
    }

    #[test]
    fn restored_library_rows_keep_preview_and_slice_choices_distinct() {
        assert_slice_presentation_fixtures();
        let record = json!({"사업명": "청사 냉난방 교체", "빈열": ""});
        let record = record.as_object().unwrap();
        let source_fields = ["사업명".into(), "빈열".into()];
        let mut bound = RowState::empty("계약명");
        bound.source = "사업명".into();
        bound.confirmed = true;
        let mut amount = RowState::empty("금액");
        amount.source = "빈열".into();
        amount.field_type = "amount".into();
        amount.confirmed = true;
        let empty = RowState::empty("담당자");
        let rows = [bound, amount, empty];
        let views = rows
            .iter()
            .enumerate()
            .map(|(index, row)| {
                row_projection(row, record, index, &source_fields, true, None, "ready").unwrap()
            })
            .collect::<Vec<_>>();
        assert_eq!(
            views
                .iter()
                .map(|view| view["preview_kind"].as_str().unwrap())
                .collect::<Vec<_>>(),
            ["value", "missing", "none"]
        );
        assert_eq!(views[0]["preview"], "청사 냉난방 교체");
        let offered = views[0]["display_options"]
            .as_array()
            .unwrap()
            .iter()
            .flat_map(|group| group["options"].as_array().unwrap())
            .collect::<Vec<_>>();
        let expected = ["text", "date", "amount"]
            .into_iter()
            .flat_map(|kind| presets(kind).into_iter().map(move |(_, code)| (kind, code)))
            .collect::<Vec<_>>();
        assert_eq!(
            offered
                .iter()
                .map(|item| (
                    item["type"].as_str().unwrap(),
                    item["fmt"].as_str().unwrap()
                ))
                .collect::<Vec<_>>(),
            expected
        );
        for (option, (kind, code)) in offered.iter().zip(expected) {
            assert_eq!(option["value"], format!("{kind}:{code}"));
            let raw = match (kind, code) {
                ("amount", "{:.1%}") => "0.0525",
                ("amount", _) => "24750000",
                ("date", _) => "2026/7/17 18:05",
                ("text", "phone") => "01012345678",
                ("text", "biz") => "1234567890",
                _ => "대한상사",
            };
            if (kind, code) != ("text", "") {
                assert_ne!(render(kind, code, raw), raw, "{kind}:{code}");
            }
        }
        assert_eq!(views[1]["preview"], "〘미입력·금액〙");
        assert_eq!(views[2]["source_label"], "열을 고르세요");
        assert_eq!(
            views[0]["slice_methods"][0]["methods"][0]["on_missing"],
            "keep"
        );
        assert!(views[0]["slice_methods"][0]["methods"][4]["on_missing"].is_null());
        let pending =
            row_projection(&rows[0], record, 0, &source_fields, false, None, "pending").unwrap();
        assert_eq!(pending["preview_kind"], "pending");
        assert_eq!(pending["preview"], "—");
        assert_eq!(pending["source_value"], "col:사업명");
        assert_eq!(pending["preview_error"], false);
        assert_eq!(pending["preview_empty"], false);
        let failed =
            row_projection(&rows[0], record, 0, &source_fields, false, None, "error").unwrap();
        assert_eq!(failed["preview_kind"], "error");
        assert_eq!(failed["preview"], "");
        assert_eq!(failed["preview_error"], true);
        assert!(
            row_projection(&rows[0], record, 0, &source_fields, false, None, "loaded").is_err()
        );
        assert_eq!(views[0]["source_label"], "사업명");
        assert_eq!(views[0]["display_label"], "원문");
        let missing = row_projection(&rows[0], record, 0, &[], true, None, "ready").unwrap();
        assert_eq!(missing["source_label"], "사업명 (데이터에 없음)");
        let now = chrono::NaiveDate::from_ymd_opt(2026, 6, 15)
            .unwrap()
            .and_hms_opt(18, 4, 0)
            .unwrap();
        let mut special = RowState::empty("작성일");
        special.field_type = "today".into();
        special.confirmed = true;
        let today = row_projection(
            &special,
            record,
            0,
            &source_fields,
            true,
            Some(now),
            "ready",
        )
        .unwrap();
        assert_eq!(today["source_value"], "sp:today");
        assert_eq!(today["source_label"], "오늘 날짜");
        assert_eq!(today["preview"], "2026. 6. 15.");
        for (value, label) in [("해당 없음", "고정값… 해당 없음"), ("", "고정값…")]
        {
            special.field_type = "const".into();
            special.constant = value.into();
            let view = row_projection(
                &special,
                record,
                0,
                &source_fields,
                true,
                Some(now),
                "ready",
            )
            .unwrap();
            assert_eq!(view["source_label"], label);
            assert_eq!(view["display_label"], "—");
            assert_eq!(view["preview"], value);
            assert_eq!(view["preview_kind"], "value");
        }
        let mut sliced = rows[0].clone();
        for (index, preview, kind) in [(1, "청사", "value"), (9, "〘미입력·계약명〙", "missing")]
        {
            let spec = json!({"mode":"split", "delimiter":" ", "index":index});
            sliced.slice = Some(crate::text_slice::TextSlice::from_dict(&spec).unwrap());
            let view =
                row_projection(&sliced, record, 0, &source_fields, true, None, "ready").unwrap();
            assert_eq!(view["slice"], spec);
            assert_eq!(view["slice_enabled"], true);
            assert_eq!(view["preview"], preview);
            assert_eq!(view["preview_kind"], kind);
        }
        let saved = MappingProfile::new(
            "",
            vec![FieldMapping::new("수신", "다른 열", "text", "", "", None).unwrap()],
            Default::default(),
        )
        .unwrap();
        let record = json!({"수신":"자동값","다른 열":"저장값","일자":"2025-01-02"});
        let live = txt_live_profile(
            "{{수신}} / {{일자}} / {{미정}}",
            &[record.as_object().unwrap().clone()],
            &saved,
        )
        .unwrap();
        assert_eq!(
            live.mappings
                .iter()
                .map(|m| (m.template_field.as_str(), m.source.as_str()))
                .collect::<Vec<_>>(),
            [("수신", "다른 열"), ("일자", "일자")]
        );
    }
}
