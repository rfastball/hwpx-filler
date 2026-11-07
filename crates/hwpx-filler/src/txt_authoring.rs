//! Pure TXT authoring over the existing structure and token grammars.

use crate::fields::python_whitespace;
use crate::structure_scan::{CONTEXT_MAX, python_trim};
use crate::text_render::{iter_field_token_matches, python_str};
use crate::text_structure::{TextStructureScan, splitlines};
use serde_json::{Map, Value, json};
use std::fmt;

const INVALID_SELECTION: &str = "고른 위치가 올바르지 않습니다.";
const FIELD_OVERLAP: &str = "고른 범위에 기존 필드가 포함되어 있습니다.";
const REGION_OVERLAP: &str = "고른 범위가 기존 영역과 겹칩니다. 범위를 다시 고르세요.";
const STRUCTURE_FIRST: &str = "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요.";
const NO_CONTENT_LINE: &str = "고를 내용 줄이 없습니다.";
const NO_FILLED_VALUE: &str = "되돌릴 필드 값이 없습니다.";
const FIX_STALE: &str =
    "이 문제의 자동 수정이 더는 적용되지 않습니다. 문제 목록을 다시 확인하세요.";

#[derive(Clone, Debug, PartialEq)]
pub struct TxtAuthoringError {
    pub message: String,
    pub refusal: Option<Value>,
}
impl fmt::Display for TxtAuthoringError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for TxtAuthoringError {}
fn fail(message: impl Into<String>) -> TxtAuthoringError {
    TxtAuthoringError {
        message: message.into(),
        refusal: None,
    }
}
fn invalid_name(field: &str, message: &str) -> TxtAuthoringError {
    TxtAuthoringError {
        message: message.into(),
        refusal: Some(json!({"code":"invalid_name","field":field,"message":message})),
    }
}
fn conflict(name: &str, existing_count: usize) -> TxtAuthoringError {
    let message =
        format!("‘{name}’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요.");
    TxtAuthoringError {
        refusal: Some(
            json!({"code":"name_conflict","name":name,"existing_count":existing_count,"message":message}),
        ),
        message,
    }
}
fn chars(text: &str) -> usize {
    text.chars().count()
}
fn byte_at(text: &str, index: usize) -> usize {
    text.char_indices()
        .nth(index)
        .map_or(text.len(), |(at, _)| at)
}
fn part(text: &str, start: usize, end: usize) -> &str {
    &text[byte_at(text, start)..byte_at(text, end)]
}
fn utf16(text: &str, at: usize) -> usize {
    part(text, 0, at).encode_utf16().count()
}
pub fn from_utf16(text: &str, value: Option<&Value>) -> Result<usize, TxtAuthoringError> {
    let Some(at) = value.and_then(Value::as_u64) else {
        return Err(fail(INVALID_SELECTION));
    };
    let mut units = 0usize;
    for (index, ch) in text.chars().enumerate() {
        if units == at as usize {
            return Ok(index);
        }
        units += ch.len_utf16();
        if units > at as usize {
            return Err(fail("고른 위치가 문자 중간에 있습니다."));
        }
    }
    if units == at as usize {
        Ok(chars(text))
    } else {
        Err(fail("고른 위치가 문서 밖에 있습니다."))
    }
}
fn line_starts(text: &str) -> Vec<usize> {
    let mut starts = vec![0];
    starts.extend(
        splitlines(text)
            .iter()
            .map(|line| line.start_char + chars(line.whole)),
    );
    starts
}
fn line_at(starts: &[usize], at: usize) -> usize {
    starts
        .partition_point(|start| *start <= at)
        .saturating_sub(1)
        .min(starts.len().saturating_sub(2))
}
fn line_range(
    text: &str,
    start: usize,
    end: usize,
) -> Result<(usize, usize, usize, usize), TxtAuthoringError> {
    let starts = line_starts(text);
    if starts.len() == 1 {
        return Err(fail(NO_CONTENT_LINE));
    }
    let first = line_at(&starts, start);
    let last = line_at(&starts, end.saturating_sub(1).max(start));
    Ok((first, last, starts[first], starts[last + 1]))
}
fn eol(text: &str) -> &'static str {
    if text.contains("\r\n") { "\r\n" } else { "\n" }
}
fn command(value: &Value) -> Result<&Map<String, Value>, TxtAuthoringError> {
    value
        .as_object()
        .ok_or_else(|| fail("저작 명령이 사전이 아닙니다."))
}
fn action(command: &Map<String, Value>) -> &str {
    command.get("type").and_then(Value::as_str).unwrap_or("")
}
fn string<'a>(command: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    command.get(key).and_then(Value::as_str)
}
fn normalized_field(raw: Option<&Value>) -> Result<String, TxtAuthoringError> {
    let name = raw
        .and_then(Value::as_str)
        .and_then(crate::fields::normalize_field_id)
        .unwrap_or_default();
    if name.is_empty()
        || name.contains("{{")
        || name.contains("}}")
        || name.contains('|')
        || name.starts_with(['#', '/'])
    {
        return Err(invalid_name(
            "name",
            "필드 이름을 확인하세요. 비어 있거나 문법 기호가 포함되어 있습니다.",
        ));
    }
    Ok(name)
}
fn value_string(raw: Option<&Value>) -> String {
    raw.map_or_else(|| "None".into(), python_str)
}
fn marker_id(raw: Option<&Value>, renaming: bool) -> Result<String, TxtAuthoringError> {
    let message = if renaming {
        "항목이나 선택의 새 식별자를 입력하세요."
    } else {
        "항목이나 선택의 식별자를 입력하세요."
    };
    let Some(value) = raw
        .and_then(Value::as_str)
        .filter(|value| !python_trim(value).is_empty())
    else {
        return Err(invalid_name("identifier", message));
    };
    crate::hwpx_structure::marker_identifier(value).map_err(|error| {
        let message = error.to_string();
        let message = if message.starts_with("구간 표기로 되쓸 수 없는 id 입니다:") {
            let ident = crate::fields::normalize_field_id(value).unwrap_or_default();
            format!(
                "구간 표기로 되쓸 수 없는 id 입니다: {}",
                hwpx_core::structural_boundary::python_string_repr(&ident)
            )
        } else {
            message
        };
        invalid_name("identifier", &message)
    })
}
fn marker_label(raw: Option<&Value>) -> Result<String, TxtAuthoringError> {
    let value = raw.and_then(Value::as_str);
    crate::hwpx_structure::marker_label(value).map_err(|error| {
        let message = error.to_string();
        let message = if message.starts_with("구간 표기로 되쓸 수 없는 label 입니다:")
        {
            format!(
                "구간 표기로 되쓸 수 없는 label 입니다: {}",
                hwpx_core::structural_boundary::python_string_repr(value.unwrap_or(""))
            )
        } else {
            message
        };
        invalid_name("name", &message)
    })
}
fn marker_text(kind: &str, id: &str, label: Option<&Value>) -> Result<String, TxtAuthoringError> {
    let label = label.and_then(Value::as_str);
    crate::hwpx_structure::begin_marker_text(kind, id, label)
        .map_err(|error| fail(error.to_string()))
}
fn end_marker(kind: &str) -> Result<String, TxtAuthoringError> {
    crate::hwpx_structure::end_marker_text(kind).map_err(|error| fail(error.to_string()))
}

#[derive(Clone)]
struct FieldSite {
    start: usize,
    end: usize,
    name: String,
    source: String,
}
fn field_sites(text: &str) -> Vec<FieldSite> {
    iter_field_token_matches(text)
        .into_iter()
        .map(|m| FieldSite {
            start: chars(&text[..m.start]),
            end: chars(&text[..m.end]),
            name: python_trim(m.body).into(),
            source: m.source.into(),
        })
        .collect()
}
fn collapse_whitespace(text: &str) -> String {
    let mut out = String::new();
    let mut pending = false;
    for ch in text.chars() {
        if python_whitespace(ch) {
            pending = true;
        } else {
            if pending {
                out.push(' ');
                pending = false;
            }
            out.push(ch);
        }
    }
    if pending {
        out.push(' ');
    }
    out
}
fn context_parts(before: &str, focus: &str, after: &str, span: usize) -> (String, String, String) {
    let before = collapse_whitespace(before);
    let after = collapse_whitespace(after);
    let lead = format!(
        "{}{}",
        if chars(&before) > span { "…" } else { "" },
        part(&before, chars(&before).saturating_sub(span), chars(&before))
    );
    let trail = format!(
        "{}{}",
        part(&after, 0, span.min(chars(&after))),
        if chars(&after) > span { "…" } else { "" }
    );
    (lead, focus.into(), trail)
}
fn humanize(text: &str) -> String {
    let mut out = String::new();
    let mut at = 0;
    for m in iter_field_token_matches(text) {
        out.push_str(&text[at..m.start]);
        out.push('[');
        out.push_str(python_trim(m.body));
        out.push(']');
        at = m.end;
    }
    out.push_str(&text[at..]);
    out
}
fn occurrence_context(before: &str, focus: &str, after: &str) -> String {
    let (a, b, c) = context_parts(before, focus, after, 12);
    format!("{a}{b}{c}")
}
fn occurrences(text: &str, scan: &TextStructureScan) -> Vec<Value> {
    let starts = line_starts(text);
    let lines = splitlines(text);
    field_sites(text).into_iter().map(|site| {
        let line=line_at(&starts,site.start);
        let owner=scan.placements.iter().rev().find(|place|place.begin_marker_line<line && line<place.end_marker_line);
        let raw=lines.get(line).map_or("",|line|line.content);
        let column=site.start-starts[line];
        let before=part(raw,0,column.min(chars(raw)));
        let after=part(raw,(column+chars(&site.source)).min(chars(raw)),chars(raw));
        json!({"name":site.name,"start":utf16(text,site.start),"end":utf16(text,site.end),"line":line,
            "slot_id":owner.map(|item|item.slot_id.as_str()),"option_id":owner.and_then(|item|item.option_id.as_deref()),
            "context":occurrence_context(&humanize(before),&format!("[{}]",site.name),&humanize(after)),
            "raw":{"text":part(raw,0,chars(raw).min(CONTEXT_MAX))}})
    }).collect()
}
fn fields(text: &str, scan: &TextStructureScan) -> Vec<Value> {
    let mut names = Vec::<String>::new();
    let mut groups = Vec::<Vec<Value>>::new();
    for item in occurrences(text, scan) {
        let name = item["name"].as_str().unwrap_or("").to_owned();
        if let Some(index) = names.iter().position(|known| known == &name) {
            groups[index].push(item);
        } else {
            names.push(name);
            groups.push(vec![item]);
        }
    }
    names
        .into_iter()
        .zip(groups)
        .map(|(name, items)| json!({"name":name,"count":items.len(),"occurrences":items}))
        .collect()
}

mod analysis;
mod availability;
mod edit_plan;
mod naming;
mod outcome;
mod projection;
mod trial;

pub use analysis::analyze;
pub use availability::{available_commands, available_target_commands, same_text_sites};
pub use naming::suggest_field_name;
pub use outcome::{confirm_tier, created_target, renamed_target};
pub use projection::{apply, preview, text_hit_context};
pub use trial::{trial, trial_document_values};

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn utf16_field_edit_preview_and_apply_agree() {
        let source = "😀 값\n";
        let command = json!({"type":"create_field","start":3,"end":4,"name":"이름"});
        let previewed = preview(source, &command).unwrap();
        assert_eq!(
            previewed["edits"],
            json!([{"start":3,"end":4,"text":"{{이름}}"}])
        );
        let (changed, impact) = apply(source, &command).unwrap();
        assert_eq!(changed, "😀 {{이름}}\n");
        assert_eq!(impact, previewed);
        assert_eq!(source, "😀 값\n");
        let sites = same_text_sites("○○시청 ○○시청", &json!({"start":0,"end":4}));
        assert_eq!(sites.len(), 1);
        assert_eq!(sites[0]["focus"], json!({"start":5,"end":9}));
    }

    #[test]
    fn copy_context_elides_token_grammar_and_merges_whitespace() {
        let source = "머리말\n계약 상대방 수요기관: {{수요기관}} 담당자 {{담당자}} 연락처\n끝";
        let analysis = analyze(source);
        let fields = analysis["fields"].as_array().unwrap();
        let request = fields
            .iter()
            .find(|field| field["name"] == "수요기관")
            .unwrap();
        let person = fields
            .iter()
            .find(|field| field["name"] == "담당자")
            .unwrap();
        assert_eq!(
            request["occurrences"][0]["context"],
            "…약 상대방 수요기관: [수요기관] 담당자 [담당자] 연…"
        );
        assert_eq!(
            person["occurrences"][0]["context"],
            "… [수요기관] 담당자 [담당자] 연락처"
        );
        assert_eq!(
            occurrence_context("짧은 앞", "[이름]", "뒤"),
            "짧은 앞[이름]뒤"
        );
        assert_eq!(
            occurrence_context(&"가".repeat(20), "[이름]", &"나".repeat(20)),
            format!("…{}[이름]{}…", "가".repeat(12), "나".repeat(12))
        );
        assert_eq!(
            occurrence_context("앞\t\t말  ", "[x]", "  뒤\n말"),
            "앞 말 [x] 뒤 말"
        );
        let hit = text_hit_context("첫 줄\n앞 {{이름}} 공고 뒤\n끝", 13, 15);
        assert_eq!(hit, "앞 [이름] 공고 뒤");
    }

    #[test]
    fn nested_option_requires_cascade_before_unwrap() {
        let source = "{{#항목 s}}\n{{#선택 a}}\n본문\n{{/선택}}\n{{/항목}}\n";
        let command = json!({"type":"unwrap","kind":"slot","slot_id":"s"});
        let previewed = preview(source, &command).unwrap();
        assert_eq!(previewed["requires_cascade"], true);
        let error = apply(source, &command).unwrap_err();
        assert_eq!(error.refusal.unwrap()["code"], "cascade_required");
        assert!(source.starts_with("{{#항목 s}}"));
    }

    #[test]
    fn field_edits_preserve_utf16_scope_and_conflicts() {
        let source = "😀 이름 {{이름}}";
        let (created, plan) = apply(
            source,
            &json!({"type":"create_field","start":3,"end":5,"name":"이름"}),
        )
        .unwrap();
        assert_eq!(created, "😀 {{이름}} {{이름}}");
        assert_eq!(
            plan["edits"],
            json!([{"start":3,"end":5,"text":"{{이름}}"}])
        );
        let (renamed, impact) = apply(
            &created,
            &json!({"type":"rename_field","old_name":"이름","name":"성명"}),
        )
        .unwrap();
        assert_eq!(renamed, "😀 {{성명}} {{성명}}");
        assert_eq!(impact["affected"], 2);
        let (relinked, _) = apply(
            &renamed,
            &json!({"type":"relink_field","start":4,"name":"담당자"}),
        )
        .unwrap();
        assert_eq!(relinked, "😀 {{담당자}} {{성명}}");
        let conflict = preview(
            "{{성명}} {{담당자}} {{담당자}}",
            &json!({"type":"rename_field","old_name":"성명","name":"담당자"}),
        )
        .unwrap_err();
        assert_eq!(
            conflict.refusal.unwrap(),
            json!({"code":"name_conflict","name":"담당자",
            "existing_count":2,"message":"‘담당자’ 필드가 이미 있습니다. 다른 이름을 쓰거나 기존 필드에 연결하세요."})
        );
        assert_eq!(source, "😀 이름 {{이름}}");

        let with_candidates = "{{이름}} 값 {{주소}}\n";
        let fresh = preview(
            with_candidates,
            &json!({"type":"create_field","start":7,"end":8,"name":"연락처"}),
        )
        .unwrap();
        assert_eq!(fresh["links_existing"], false);
        assert_eq!(fresh["existing_count"], 0);
        assert_eq!(
            fresh["candidates"],
            json!([{"name":"이름","count":1},{"name":"주소","count":1}])
        );
        let linked = preview(
            with_candidates,
            &json!({"type":"create_field","start":7,"end":8,"name":"이름"}),
        )
        .unwrap();
        assert_eq!(linked["links_existing"], true);
        assert_eq!(linked["existing_count"], 1);
        assert_eq!(linked["result"]["fields"][0]["count"], 2);
    }

    #[test]
    fn repeated_sites_share_one_field_plan_without_absorbing_tokens() {
        let source = "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n{{○○시청}}\n";
        let sites = same_text_sites(source, &json!({"start":0,"end":4}));
        assert_eq!(
            sites
                .iter()
                .map(|site| site["location"].clone())
                .collect::<Vec<_>>(),
            vec![
                json!({"start":11,"end":15}),
                json!({"start":20,"end":24}),
                json!({"start":25,"end":29})
            ]
        );
        assert_eq!(sites[2]["focus"], json!({"start":5,"end":9}));
        let command = json!({"type":"create_field","name":"수요기관","start":0,"end":4,
            "ranges":[{"start":0,"end":4},{"start":25,"end":29},{"start":11,"end":15}]});
        let (changed, plan) = apply(source, &command).unwrap();
        assert_eq!(
            changed,
            "{{수요기관}} 귀하\n서명 {{수요기관}} (인)\n○○시청 {{수요기관}}\n{{○○시청}}\n"
        );
        assert_eq!(plan["affected"], 3);
        assert_eq!(plan["edits"].as_array().unwrap().len(), 3);
        assert_eq!(confirm_tier(&command, &plan, None), "enter");
        let overlap = json!({"type":"create_field","name":"a","start":0,"end":2,
            "ranges":[{"start":0,"end":2},{"start":1,"end":3}]});
        assert!(
            apply("아아아", &overlap)
                .unwrap_err()
                .message
                .contains("기존 필드가 포함")
        );
        assert_eq!(
            source,
            "○○시청 귀하\n서명 ○○시청 (인)\n○○시청 ○○시청\n{{○○시청}}\n"
        );
    }

    #[test]
    fn confirmation_and_created_target_follow_actual_edit_impact() {
        let empty_impact = json!({"linked_jobs":[],"impact_unverified":0,
            "field_delta":{"added_fields":[],"removed_fields":[]},
            "structure_delta":{"added_slots":[],"removed_slots":[],
                "added_options":[],"removed_options":[],"renamed":[]}});
        assert_eq!(
            confirm_tier(
                &json!({"type":"create_field","name":"기관"}),
                &json!({}),
                Some(&empty_impact)
            ),
            "none"
        );
        assert_eq!(
            confirm_tier(
                &json!({"type":"create_field","name":"기관"}),
                &json!({"links_existing":true}),
                Some(&empty_impact)
            ),
            "enter"
        );
        assert_eq!(
            confirm_tier(
                &json!({"type":"unwrap","slot_id":"s","cascade":true}),
                &json!({}),
                Some(&empty_impact)
            ),
            "button"
        );
        assert_eq!(
            confirm_tier(
                &json!({"type":"rename_field","old_name":"기관","name":"담당"}),
                &json!({}),
                Some(&empty_impact)
            ),
            "enter"
        );

        let source = "기관: 조달청\n본문\n끝\n";
        let (with_field, _) = apply(
            source,
            &json!({"type":"create_field","start":4,"end":7,"name":"기관"}),
        )
        .unwrap();
        let field = created_target(
            &json!({"type":"create_field","name":" 기관 "}),
            &analyze(&with_field),
        )
        .unwrap();
        assert_eq!(field["kind"], "field");
        assert_eq!(field["name"], "기관");
        assert_eq!(field["location"], field["occurrences"][0]);
        assert_eq!(field["location"]["start"], 4);
        assert_eq!(field["location"]["end"], 10);
        assert!(created_target(&json!({"type":"rename_field"}), &analyze(&with_field)).is_none());
    }

    #[test]
    fn confirmation_tier_exposes_each_destructive_or_uncertain_impact() {
        let empty = json!({"linked_jobs":[],"impact_unverified":0,
            "field_delta":{"added_fields":[],"removed_fields":[]},
            "structure_delta":{"added_slots":[],"removed_slots":[],"added_options":[],
                "removed_options":[],"renamed":[]}});
        for (command, preview, impact, expected) in [
            (
                json!({"type":"delete","slot_id":"s"}),
                json!({}),
                empty.clone(),
                "button",
            ),
            (
                json!({"type":"unwrap","slot_id":"s","cascade":true}),
                json!({}),
                empty.clone(),
                "button",
            ),
            (
                json!({"type":"create_slot","id":"s"}),
                json!({"expanded":true}),
                empty.clone(),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"t"}),
                json!({}),
                empty.clone(),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                empty.clone(),
                "none",
            ),
            (
                json!({"type":"create_field","name":"F"}),
                json!({}),
                json!({"impact_unverified":1}),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                json!({"field_delta":{"removed_fields":["F"]}}),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                json!({"linked_jobs":["작업"],"structure_delta":{"added_slots":["t"]}}),
                "enter",
            ),
            (
                json!({"type":"rename_slot","slot_id":"s","id":"s"}),
                json!({}),
                json!({"linked_jobs":["작업"]}),
                "none",
            ),
        ] {
            assert_eq!(
                confirm_tier(&command, &preview, Some(&impact)),
                expected,
                "{command}"
            );
        }
    }

    #[test]
    fn name_suggestion_and_invalid_identifiers_keep_distinct_refusals() {
        assert_eq!(
            suggest_field_name("수요 기관: ", "○○시청", &["수요기관".into()]),
            Some("수요기관".into())
        );
        assert_eq!(suggest_field_name("수요기관 ", "○○시청", &[]), None);
        assert_eq!(suggest_field_name("기관: ", "{{기관}}", &[]), None);

        let empty_name = preview(
            "수요기관: ○○시청",
            &json!({"type":"create_field","start":6,"end":10,"name":"  "}),
        )
        .unwrap_err();
        assert_eq!(empty_name.refusal.unwrap()["field"], "name");
        let invalid_id = preview(
            "본문\n끝\n",
            &json!({"type":"create_slot","start":0,"end":2,"id":"a b","label":"표시"}),
        )
        .unwrap_err();
        assert_eq!(invalid_id.refusal.unwrap()["field"], "identifier");
        let empty_id = preview(
            "본문\n끝\n",
            &json!({"type":"create_slot","start":0,"end":2,"id":"","label":""}),
        )
        .unwrap_err();
        assert_eq!(
            empty_id.refusal.unwrap(),
            json!({"code":"invalid_name","field":"identifier",
                "message":"항목이나 선택의 식별자를 입력하세요."})
        );
        let invalid_label = preview(
            "본문\n끝\n",
            &json!({"type":"create_slot","start":0,"end":2,"id":"a","label":"표  시"}),
        )
        .unwrap_err();
        assert_eq!(invalid_label.refusal.unwrap()["field"], "name");
    }

    #[test]
    fn ambiguous_structure_ranges_refuse_without_changing_the_editor_text() {
        let offset = |source: &str, needle: &str| {
            source[..source.find(needle).unwrap()]
                .encode_utf16()
                .count()
        };
        let original = "앞\n공통\n첫째\n둘째\n끝\n";
        let (slotted, _) = apply(
            original,
            &json!({"type":"create_slot","start":offset(original,"공통"),
                "end":offset(original,"끝"),"id":"s"}),
        )
        .unwrap();
        let (source, _) = apply(
            &slotted,
            &json!({"type":"create_option","start":offset(&slotted,"첫째"),
                "end":offset(&slotted,"둘째"),"slot_id":"s","id":"a"}),
        )
        .unwrap();
        let cases = [
            (
                json!({"type":"create_slot","start":offset(&source,"공통"),
                "end":offset(&source,"둘째"),"id":"other"}),
                "겹칩니다",
            ),
            (
                json!({"type":"create_option","start":0,"end":1,
                "slot_id":"s","id":"b"}),
                "하나의 항목",
            ),
            (
                json!({"type":"create_option","start":offset(&source,"둘째"),
                "end":offset(&source,"둘째")+2,"slot_id":"s","id":"a"}),
                "식별자",
            ),
            (
                json!({"type":"unwrap","kind":"slot","slot_id":"s"}),
                "함께 해제",
            ),
            (
                json!({"type":"move","kind":"slot","slot_id":"s",
                "destination":offset(&source,"공통")}),
                "자기 안",
            ),
            (
                json!({"type":"duplicate","kind":"slot","slot_id":"s"}),
                "새 식별자",
            ),
        ];
        for (command, expected) in cases {
            assert!(
                apply(&source, &command)
                    .unwrap_err()
                    .message
                    .contains(expected)
            );
        }
        assert_eq!(analyze(&source)["slots"][0]["id"], "s");
        assert!(
            apply(
                "😀본문",
                &json!({"type":"create_field","start":1,"end":2,"name":"F"})
            )
            .unwrap_err()
            .message
            .contains("문자 중간")
        );
    }

    #[test]
    fn whole_field_unset_is_one_plan_while_an_occurrence_unset_stays_local() {
        let source = "가 {{F}}\n{{G}} 나 {{F}}\n끝 {{F}}\n";
        let analysis = analyze(source);
        let occurrences = analysis["fields"]
            .as_array()
            .unwrap()
            .iter()
            .find(|field| field["name"] == "F")
            .unwrap()["occurrences"]
            .clone();
        let command = json!({"type":"unset_field","old_name":"F","name":"F",
            "occurrences":occurrences,"start":2,"end":7,"text":"값"});
        let projected = preview(source, &command).unwrap();
        assert_eq!(projected["affected"], 3);
        assert_eq!(projected["edits"].as_array().unwrap().len(), 3);
        assert_eq!(projected["label"], "‘F’ 필드 의미 해제");
        assert_eq!(projected["before"], "{{F}}");
        assert_eq!(projected["after"], "값");
        assert_eq!(projected["result"]["fields"][0]["name"], "G");
        assert_eq!(
            apply(source, &command).unwrap().0,
            "가 값\n{{G}} 나 값\n끝 값\n"
        );
        let local = json!({"type":"unset_field","old_name":"F","name":"F",
            "start":2,"end":7,"text":"값"});
        assert_eq!(
            apply(source, &local).unwrap().0,
            "가 값\n{{G}} 나 {{F}}\n끝 {{F}}\n"
        );
    }

    #[test]
    fn analysis_name_tags_keep_utf16_coordinates_and_region_pairing() {
        let source = "😀 {{공고명}}\n{{#항목 사유 변경 사유}}\n본문\n{{/항목}}\n";
        let spans = analyze(source)["spans"].as_array().unwrap().clone();
        assert_eq!(spans.len(), 3);
        assert_eq!(spans[0]["label"], "공고명");
        assert_eq!(
            (spans[0]["start"].as_u64(), spans[0]["end"].as_u64()),
            (Some(3), Some(10))
        );
        assert_eq!(spans[1]["region"], "slot");
        assert_eq!(spans[1]["role"], "open");
        assert_eq!(spans[2]["role"], "close");
        assert_eq!(spans[1]["paired"], true);
        assert_eq!(spans[2]["paired"], true);
    }

    #[test]
    fn structure_preview_refusal_and_marker_repair_keep_source() {
        let source = "머리\n공통 {{F}}\n첫째\n둘째\n끝\n";
        let index =
            |text: &str, needle: &str| text[..text.find(needle).unwrap()].encode_utf16().count();
        let (slot, _) = apply(source, &json!({"type":"create_slot","start":3,"end":index(source,"끝"),"id":"s","label":"특약"})).unwrap();
        let first = index(&slot, "첫째");
        let (with_option, _) = apply(
            &slot,
            &json!({"type":"create_option","start":first,"end":first+2,"slot_id":"s","id":"a"}),
        )
        .unwrap();
        let planned = preview(
            &with_option,
            &json!({"type":"unwrap","kind":"slot","slot_id":"s"}),
        )
        .unwrap();
        assert_eq!(planned["requires_cascade"], true);
        assert_eq!(planned["counts"]["options"], 1);
        assert_eq!(planned["children"][0]["id"], "a");
        let refused = apply(
            &with_option,
            &json!({"type":"unwrap","kind":"slot","slot_id":"s"}),
        )
        .unwrap_err();
        assert_eq!(refused.refusal.unwrap()["code"], "cascade_required");
        assert_eq!(analyze(&with_option)["diagnostics"], json!([]));
        let outside = available_commands(&with_option, &json!({"start":0,"end":2}), None);
        let option = outside
            .iter()
            .find(|row| row["type"] == "create_option")
            .unwrap();
        assert_eq!(option["enabled"], false);
        assert_eq!(
            option["reason"],
            "선택은 항목 안에 만들 수 있습니다. 먼저 항목 안의 내용을 고르세요."
        );
        let field_at = index(&with_option, "{{F}}") + 1;
        let on_field = available_commands(
            &with_option,
            &json!({"start":field_at,"end":field_at}),
            Some(&json!({"slot_id":"s","option_id":null})),
        );
        assert_eq!(
            on_field
                .iter()
                .find(|row| row["type"] == "unset_field")
                .unwrap()["enabled"],
            true
        );
        assert_eq!(
            on_field
                .iter()
                .find(|row| row["type"] == "create_field")
                .unwrap()["reason"],
            "고른 범위에 기존 필드가 포함되어 있습니다."
        );
        let broken_commands =
            available_commands("{{#항목 s}}\n본문\n", &json!({"start":12,"end":12}), None);
        assert_eq!(
            broken_commands
                .iter()
                .find(|row| row["type"] == "create_slot")
                .unwrap()["reason"],
            "구조 오류를 먼저 수정한 뒤 영역 명령을 실행하세요."
        );

        let broken = "앞\n{{/항목}}\n뒤\n";
        let diagnostic = &analyze(broken)["diagnostics"][0];
        assert_eq!(diagnostic["category"], "structure");
        let repair = diagnostic["suggestion"]["command"].clone();
        let (fixed, _) = apply(broken, &repair).unwrap();
        assert_eq!(fixed, "앞\n뒤\n");
        assert!(
            apply(&fixed, &repair)
                .unwrap_err()
                .message
                .contains("더는 적용되지")
        );
    }
}
