//! Pure editor slice preview and drag-selection suggestions.

use crate::fields::python_whitespace;
use crate::job::MISSING_MARKER;
use crate::mapping_state::slice_label;
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use crate::text_slice::TextSlice;
use serde_json::{Map, Value, json};
use std::collections::HashSet;

const LIMIT: usize = 10;
const SPLIT: &[&str] = &[",", "-", "/", " ", "·"];
fn fail(text: impl Into<String>) -> String {
    text.into()
}
fn repr(text: &str) -> String {
    python_repr(&Value::String(text.into()))
}
fn text_at(value: &str, start: usize, end: usize) -> String {
    value
        .chars()
        .skip(start)
        .take(end.saturating_sub(start))
        .collect()
}
fn segments(value: &str, span: Option<(usize, usize)>) -> Value {
    if let Some((start, end)) = span {
        json!({"pre":text_at(value,0,start),"keep":text_at(value,start,end),"post":text_at(value,end,value.chars().count())})
    } else {
        json!({"pre":value,"keep":"","post":""})
    }
}
fn values(records: &[Map<String, Value>], source: &str) -> Vec<String> {
    records
        .iter()
        .take(LIMIT)
        .map(|row| python_trim(row.get(source).and_then(Value::as_str).unwrap_or("")).into())
        .collect()
}
fn shape(text: &str) -> String {
    let mut out = String::new();
    let mut group = '\0';
    for ch in python_trim(text).chars() {
        let current = if ch.is_ascii_digit() {
            '9'
        } else if ch.is_ascii_alphabetic() {
            'a'
        } else if ('가'..='힣').contains(&ch) {
            '가'
        } else {
            '\0'
        };
        if current == '\0' {
            out.push(ch);
            group = '\0';
        } else if group != current {
            out.push(current);
            group = current;
        }
    }
    out
}
fn utf16_to_scalar(value: &str, offset: &Value) -> Result<usize, String> {
    let Some(target) = offset.as_u64().filter(|_| !offset.is_boolean()) else {
        return Err(fail(format!(
            "선택 좌표가 올바르지 않음: {}",
            python_repr(offset)
        )));
    };
    let mut units = 0u64;
    for (index, ch) in value.chars().enumerate() {
        if units == target {
            return Ok(index);
        }
        units += if (ch as u32) > 0xffff { 2 } else { 1 };
        if units > target {
            return Err(fail(format!(
                "선택 좌표가 글자 가운데를 가리킴: {}",
                python_repr(offset)
            )));
        }
    }
    if units == target {
        Ok(value.chars().count())
    } else {
        Err(fail(format!(
            "선택 좌표가 값 밖을 가리킴: {}",
            python_repr(offset)
        )))
    }
}
fn status_word(status: &str) -> &'static str {
    match status {
        "hit" => "맞음",
        "odd" => "형식 다름",
        "miss" => "확인 필요",
        _ => "빈 값",
    }
}
fn miss_tag(spec: &TextSlice) -> String {
    let value = spec.to_dict();
    match spec.mode() {
        "before" | "after" => format!("‘{}’ 없음", value["delimiter"].as_str().unwrap_or("")),
        "between" => format!(
            "‘{}’ 또는 ‘{}’ 없음",
            value["open"].as_str().unwrap_or(""),
            value["close"].as_str().unwrap_or("")
        ),
        "split" => "조각 없음".into(),
        _ => "확인 필요".into(),
    }
}
fn from_value(value: Value) -> Option<TextSlice> {
    TextSlice::from_dict(&value).ok()
}
/// Delimiter specs from the nearest non-space characters around the selection.
fn delimiter_specs(
    start: usize,
    end: usize,
    len: usize,
    neighbours: (Option<char>, Option<char>),
) -> Vec<Value> {
    let (before, after) = neighbours;
    let mut out = Vec::new();
    if start == 0
        && let Some(ch) = after
    {
        out.push(json!({"mode":"before","delimiter":ch.to_string(),"on_missing":"keep"}));
    }
    if end == len
        && let Some(ch) = before
    {
        out.push(json!({"mode":"after","delimiter":ch.to_string(),"on_missing":"keep"}));
    }
    if start > 0
        && end < len
        && let (Some(b), Some(a)) = (before, after)
    {
        out.push(json!({"mode":"between","open":b.to_string(),"close":a.to_string(),"on_missing":"keep"}));
    }
    out
}
/// Split specs for each separator whose pieces include the selected text.
fn split_specs(value: &str, want: &str) -> Vec<Value> {
    let mut out = Vec::new();
    for delimiter in SPLIT.iter().filter(|delimiter| value.contains(**delimiter)) {
        let pieces = value.split(delimiter).map(python_trim).collect::<Vec<_>>();
        if let Some(at) = pieces.iter().position(|piece| *piece == want) {
            let index = if at == pieces.len() - 1 && at > 0 {
                -1
            } else {
                at as i64 + 1
            };
            out.push(json!({"mode":"split","delimiter":delimiter,"index":index,"on_missing":"keep"}));
        }
    }
    out
}
fn position_spec(start: usize, end: usize, len: usize) -> Value {
    if start == 0 {
        json!({"mode":"head","count":end})
    } else if end == len {
        json!({"mode":"tail","count":len-start})
    } else {
        json!({"mode":"chars","start":start+1,"length":end-start,"on_missing":"keep"})
    }
}
fn candidate_specs(value: &str, start: usize, end: usize) -> Vec<TextSlice> {
    let chars = value.chars().collect::<Vec<_>>();
    let want = text_at(value, start, end);
    let before = chars[..start]
        .iter()
        .rev()
        .find(|ch| !python_whitespace(**ch))
        .copied();
    let after = chars[end..]
        .iter()
        .find(|ch| !python_whitespace(**ch))
        .copied();
    let mut out = delimiter_specs(start, end, chars.len(), (before, after));
    out.extend(split_specs(value, &want));
    out.push(position_spec(start, end, chars.len()));
    out.into_iter().filter_map(from_value).collect()
}
/// The selection narrowed past leading and trailing whitespace.
fn trimmed_selection(value: &str, mut begin: usize, mut finish: usize) -> (usize, usize) {
    let chars = value.chars().collect::<Vec<_>>();
    while begin < finish && python_whitespace(chars[begin]) {
        begin += 1;
    }
    while finish > begin && python_whitespace(chars[finish - 1]) {
        finish -= 1;
    }
    (begin, finish)
}
/// Specs that reproduce the selection on the sample, best row agreement first.
fn scored_candidates(values: &[String], value: &str, begin: usize, finish: usize) -> Vec<Value> {
    let want = text_at(value, begin, finish);
    let target = shape(&want);
    let total = values.iter().filter(|item| !item.is_empty()).count();
    let mut seen = HashSet::new();
    let mut scored = Vec::new();
    for (order, spec) in candidate_specs(value, begin, finish)
        .into_iter()
        .enumerate()
    {
        let outcome = spec.evaluate(value);
        if outcome.missed
            || python_trim(&outcome.text) != want
            || !seen.insert(spec.mode().to_owned())
        {
            continue;
        }
        let matched = values
            .iter()
            .filter(|item| !item.is_empty())
            .filter(|item| {
                let outcome = spec.evaluate(item);
                !outcome.missed && shape(&outcome.text) == target
            })
            .count();
        scored.push((matched, order, spec));
    }
    scored.sort_by_key(|(matched, order, _)| (std::cmp::Reverse(*matched), *order));
    scored.into_iter().map(|(matched, _, spec)| {
        json!({"mode":spec.mode(),"slice":spec.to_dict(),"label":slice_label(Some(&spec)),"matched":matched,"total":total,"tag":format!("{matched}/{total}행 맞음"),"tip":format!("맞는 행: 값 있는 {total}행 중 {matched}행"),"full":matched==total})
    }).collect()
}
fn propose(values: &[String], sample: usize, start: &Value, end: &Value) -> Result<Value, String> {
    let value = values
        .get(sample)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| fail(format!("예시 행이 올바르지 않음: {sample}")))?;
    let begin = utf16_to_scalar(value, start)?;
    let finish = utf16_to_scalar(value, end)?;
    if finish < begin {
        return Err(fail(format!(
            "선택 범위가 거꾸로임: {}~{}",
            python_repr(start),
            python_repr(end)
        )));
    }
    let (begin, finish) = trimmed_selection(value, begin, finish);
    let candidates = if begin < finish {
        scored_candidates(values, value, begin, finish)
    } else {
        Vec::new()
    };
    Ok(
        json!({"ok":true,"candidates":candidates,"message":if candidates.is_empty(){"고른 부분에 맞는 방식이 없습니다. 방식을 직접 고르세요."}else{""}}),
    )
}
/// One preview row: its status, sliced result, kept span, and explanatory tags.
fn row_outcome(
    value: &str,
    spec: Option<&TextSlice>,
    target: Option<&String>,
) -> (&'static str, String, Option<(usize, usize)>, Vec<String>) {
    if value.is_empty() {
        return ("empty", String::new(), None, Vec::new());
    }
    let Some(spec) = spec else {
        return ("plain", value.to_owned(), None, Vec::new());
    };
    let outcome = spec.evaluate(value);
    let status = if outcome.missed || python_trim(&outcome.text).is_empty() {
        "miss"
    } else if target.is_some_and(|target| shape(&outcome.text) != *target) {
        "odd"
    } else {
        "hit"
    };
    let mut tags = Vec::new();
    if outcome.missed {
        tags.push(miss_tag(spec));
    } else if status == "odd" {
        tags.push("형식 다름".into());
    }
    (status, outcome.text, outcome.span, tags)
}
fn miss_choice(spec: Option<&TextSlice>) -> Option<Value> {
    spec.filter(|spec|matches!(spec.mode(),"before"|"after"|"between")).map(|spec|{
        let raw=spec.to_dict();let subject=if spec.mode()=="between"{format!("‘{}’ 또는 ‘{}’",raw["open"].as_str().unwrap_or(""),raw["close"].as_str().unwrap_or(""))}else{format!("‘{}’",raw["delimiter"].as_str().unwrap_or(""))};
        json!({"label":format!("{subject} 없는 행"),"value":spec.on_missing(),"choices":[{"value":"keep","label":"원본 그대로"},{"value":"empty","label":"빈 값"}]})
    })
}
fn with_segments(mut object: Value, value: &str, span: Option<(usize, usize)>) -> Value {
    for (key, value) in segments(value, span).as_object().unwrap() {
        object[key] = value.clone();
    }
    object
}
/// The preview rows and how many rows fall in each status.
fn preview_rows(
    field: &str,
    spec: Option<&TextSlice>,
    values: &[String],
    target: Option<&String>,
) -> (Vec<Value>, [usize; 4]) {
    let mut counts = [0usize; 4];
    let mut rows = Vec::new();
    for (position, value) in values.iter().enumerate() {
        let (status, result, span, tags) = row_outcome(value, spec, target);
        if let Some(index) = ["hit", "odd", "miss", "empty"]
            .iter()
            .position(|known| *known == status)
        {
            counts[index] += 1;
        }
        let missing = python_trim(&result).is_empty();
        let row = json!({"index":position,"label":format!("{}행",position+1),"result":if missing{MISSING_MARKER.replace("{field}",field)}else{result},"marker":missing,"status":status,"tags":tags});
        rows.push(with_segments(row, value, span));
    }
    (rows, counts)
}
fn preview(
    field: &str,
    spec: Option<&TextSlice>,
    values: &[String],
    sample: Option<&Value>,
) -> Value {
    let sample_index = sample
        .and_then(Value::as_u64)
        .and_then(|n| usize::try_from(n).ok())
        .filter(|index| values.get(*index).is_some_and(|value| !value.is_empty()))
        .or_else(|| values.iter().position(|value| !value.is_empty()));
    let sample_value = sample_index
        .and_then(|index| values.get(index))
        .map(String::as_str)
        .unwrap_or("");
    let sample_outcome = spec
        .zip(sample_index)
        .map(|(spec, _)| spec.evaluate(sample_value));
    let edits = spec.is_some_and(|spec| matches!(spec.mode(), "replace" | "remove"));
    let target = if edits {
        None
    } else {
        sample_outcome
            .as_ref()
            .filter(|outcome| !outcome.missed && !python_trim(&outcome.text).is_empty())
            .map(|outcome| shape(&outcome.text))
    };
    let (rows, counts) = preview_rows(field, spec, values, target.as_ref());
    let summary = ["hit", "odd", "miss", "empty"]
        .into_iter()
        .zip(counts)
        .filter(|(_, count)| *count > 0)
        .map(|(status, count)| format!("{} {count}행", status_word(status)))
        .collect::<Vec<_>>()
        .join(" · ");
    let sample_block = with_segments(
        json!({"index":sample_index,"value":sample_value,"miss_tag":sample_outcome.as_ref().filter(|outcome|outcome.missed).and(spec).map(miss_tag).unwrap_or_default()}),
        sample_value,
        sample_outcome.as_ref().and_then(|outcome| outcome.span),
    );
    let samples=values.iter().enumerate().map(|(position,value)|json!({"index":position,"label":format!("{}",position+1),"aria":format!("{}행{}",position+1,if value.is_empty(){", 빈 값"}else{""}),"disabled":value.is_empty(),"pressed":Some(position)==sample_index})).collect::<Vec<_>>();
    json!({"ok":true,"slice":spec.map(TextSlice::to_dict),"rows":rows,"rows_label":format!("불러온 {}행 미리보기",values.len()),"summary":summary,"hint":if spec.is_none(){"쓸 부분을 끌어 고르거나 방식을 고르세요."}else{""},"sample":sample_block,"samples":samples,"miss_choice":miss_choice(spec)})
}
pub fn slice_query(
    kind: &str,
    field: &str,
    source: &str,
    spec: Option<&TextSlice>,
    enabled: bool,
    records: &[Map<String, Value>],
    payload: &Value,
) -> Result<Value, String> {
    if !enabled {
        return Err(fail(format!(
            "가공은 데이터 열 값에만 둘 수 있음: {}",
            repr(field)
        )));
    }
    let values = values(records, source);
    match kind {
        "preview" => Ok(preview(field, spec, &values, payload.get("sample"))),
        "propose" => {
            let sample = payload
                .get("sample")
                .and_then(Value::as_i64)
                .filter(|_| !payload["sample"].is_boolean())
                .ok_or_else(|| {
                    fail(format!(
                        "sample 값이 정수가 아님: {}",
                        python_repr(&payload["sample"])
                    ))
                })?;
            if sample < 0 {
                return Err(fail(format!("예시 행이 올바르지 않음: {sample}")));
            }
            for key in ["start", "end"] {
                if payload[key].as_i64().is_none() || payload[key].is_boolean() {
                    return Err(fail(format!(
                        "{key} 값이 정수가 아님: {}",
                        python_repr(&payload[key])
                    )));
                }
            }
            propose(&values, sample as usize, &payload["start"], &payload["end"])
        }
        _ => Err(fail(format!("알 수 없는 가공 질의: {}", repr(kind)))),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    fn spec(value: &Value) -> Option<TextSlice> {
        (!value.is_null()).then(|| TextSlice::from_dict(value).unwrap())
    }

    fn outcome(case: &Value) -> Option<Result<Value, String>> {
        let args = &case["args"];
        let kwargs = &case["kwargs"];
        Some(match case["function"].as_str().unwrap() {
            "value_shape" => Ok(json!(shape(args[0].as_str().unwrap()))),
            "code_point_offset" => {
                utf16_to_scalar(args[0].as_str().unwrap(), &args[1]).map(|v| json!(v))
            }
            "slice_values" => Ok(json!(values(
                &serde_json::from_value::<Vec<Map<String, Value>>>(args[0].clone()).unwrap(),
                args[1].as_str().unwrap()
            ))),
            "propose_slices" => propose(
                &serde_json::from_value::<Vec<String>>(args[0].clone()).unwrap(),
                args[1].as_u64().unwrap() as usize,
                &args[2],
                &args[3],
            ),
            "preview_slice" => Ok(preview(
                args[0].as_str().unwrap(),
                spec(&args[1]).as_ref(),
                &serde_json::from_value::<Vec<String>>(args[2].clone()).unwrap(),
                kwargs.get("sample"),
            )),
            "slice_query" => slice_query(
                args[0].as_str().unwrap(),
                kwargs["field"].as_str().unwrap(),
                kwargs["source"].as_str().unwrap(),
                spec(&kwargs["spec"]).as_ref(),
                kwargs["enabled"].as_bool().unwrap(),
                &serde_json::from_value::<Vec<Map<String, Value>>>(kwargs["records"].clone())
                    .unwrap(),
                &kwargs["payload"],
            ),
            _ => return None,
        })
    }

    #[test]
    fn previews_and_proposals_preserve_status_spans_accessibility_and_errors() {
        assert_web_fixture();
        let cases: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/editor_slice.json"))
                .unwrap();
        for case in cases.as_array().unwrap() {
            if let Some(actual) = outcome(case) {
                if let Some(error) = case.get("error") {
                    assert_eq!(actual.unwrap_err(), error.as_str().unwrap(), "{case}");
                } else {
                    assert_eq!(actual.unwrap(), case["expected"], "{case}");
                }
            }
        }
    }

    fn assert_web_fixture() {
        let web: Value = serde_json::from_str(include_str!(
            "../../../tests/js/fixtures/slice_popover.json"
        ))
        .unwrap();
        let amounts = [
            "170,309,180원 (VAT 포함)",
            "48,500,000원 (VAT 포함)",
            "9,900,000원",
            "1,230,000원 (VAT 별도)",
            "",
        ]
        .map(str::to_owned);
        for (key, raw, sample) in [
            ("preview_none", Value::Null, None),
            (
                "preview_before",
                json!({"mode":"before","delimiter":"원","on_missing":"keep"}),
                Some(json!(0)),
            ),
            (
                "preview_between",
                json!({"mode":"between","open":"(","close":")"}),
                Some(json!(2)),
            ),
        ] {
            assert_eq!(
                preview("계약금액", spec(&raw).as_ref(), &amounts, sample.as_ref()),
                web[key],
                "{key}"
            );
        }
        assert_eq!(
            propose(&amounts, 0, &json!(0), &json!(11)).unwrap(),
            web["propose_amount"]
        );
        assert_eq!(
            propose(&amounts, 0, &json!(12), &json!(13)).unwrap(),
            web["propose_none"]
        );
    }
}
