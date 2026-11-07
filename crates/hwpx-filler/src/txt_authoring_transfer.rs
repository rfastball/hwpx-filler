//! Explicit semantic capture and paste for TXT editor snapshots.

use crate::hwpx_structure::begin_marker_text;
use crate::structure_scan::python_trim;
use crate::text_render::{iter_field_token_matches, python_str, python_truthy};
use crate::text_structure::{scan_text_token_spans, splitlines};
use crate::txt_authoring::analyze;
use serde_json::{Value, json};
use std::collections::HashSet;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TxtTransferError(pub String);
impl fmt::Display for TxtTransferError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TxtTransferError {}
fn fail(message: impl Into<String>) -> TxtTransferError {
    TxtTransferError(message.into())
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
fn units(text: &str, index: usize) -> usize {
    part(text, 0, index).encode_utf16().count()
}
fn offset(text: &str, value: Option<&Value>) -> Result<usize, TxtTransferError> {
    let at = match value {
        Some(Value::Number(number)) => number.as_i64().filter(|at| *at >= 0).map(|at| at as usize),
        Some(Value::Bool(value)) => Some(usize::from(*value)),
        _ => None,
    };
    let Some(at) = at else {
        return Err(fail("고른 위치가 올바르지 않습니다."));
    };
    let mut position = 0;
    for (index, ch) in text.chars().enumerate() {
        if position == at {
            return Ok(index);
        }
        position += ch.len_utf16();
        if position > at {
            break;
        }
    }
    if position == at {
        Ok(chars(text))
    } else {
        Err(fail("고른 위치가 문자 경계에 있지 않습니다."))
    }
}
fn field_plain(text: &str) -> String {
    let mut result = text.to_owned();
    for found in iter_field_token_matches(text).into_iter().rev() {
        result.replace_range(found.start..found.end, python_trim(found.body));
    }
    result
}
/// Capture one exact TXT meaning unit from the caller's immutable snapshot.
pub fn capture_txt(text: &str, selector: &Value) -> Result<Value, TxtTransferError> {
    let kind = selector["kind"].as_str().unwrap_or("");
    let detail = analyze(text);
    if kind == "field" {
        let position = offset(text, selector.get("start"))?;
        let found = iter_field_token_matches(text)
            .into_iter()
            .find(|found| {
                let start = chars(&text[..found.start]);
                let end = chars(&text[..found.end]);
                start <= position && position < end
            })
            .ok_or_else(|| fail("복사할 필드 사용 위치를 고르세요."))?;
        let name = python_trim(found.body);
        return Ok(
            json!({"media":"txt","kind":"field","name":name,"text":found.source,"plain":name}),
        );
    }
    if kind == "text" {
        let start = offset(text, selector.get("start"))?;
        let end = offset(text, selector.get("end"))?;
        if start >= end {
            return Err(fail("복사할 본문을 고르세요."));
        }
        if scan_text_token_spans(text, None)
            .iter()
            .any(|span| span.start < end && start < span.end)
        {
            return Err(fail("의미를 포함한 범위는 필드·항목·선택으로 복사하세요."));
        }
        let snippet = part(text, start, end);
        return Ok(json!({"media":"txt","kind":"text","text":snippet,"plain":snippet}));
    }
    if !matches!(kind, "slot" | "option") {
        return Err(fail("복사할 의미 요소를 고르세요."));
    }
    let slot = detail["slots"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|slot| slot["id"] == selector["slot_id"]);
    let item = if kind == "slot" {
        slot
    } else {
        slot.and_then(|slot| {
            slot["options"].as_array().and_then(|options| {
                options
                    .iter()
                    .find(|option| option["id"] == selector["option_id"])
            })
        })
    };
    let location = item
        .and_then(|item| item.get("location"))
        .filter(|location| !location.is_null());
    if location.is_none()
        || detail["diagnostics"]
            .as_array()
            .is_some_and(|rows| !rows.is_empty())
    {
        return Err(fail("구조 오류가 있어 의미 영역을 복사할 수 없습니다."));
    }
    let location = location.unwrap();
    let start = offset(text, location.get("start"))?;
    let end = offset(text, location.get("end"))?;
    let snippet = part(text, start, end);
    let plain = splitlines(snippet)
        .into_iter()
        .filter(|line| {
            let row = line
                .content
                .trim_start_matches(crate::fields::python_whitespace);
            !["{{#항목", "{{#선택", "{{/항목", "{{/선택"]
                .iter()
                .any(|prefix| row.starts_with(prefix))
        })
        .map(|line| line.whole)
        .collect::<String>();
    let plain = field_plain(&plain);
    Ok(
        json!({"media":"txt","kind":kind,"id":if kind=="slot"{&selector["slot_id"]}else{&selector["option_id"]},
        "label":item.and_then(|item|item["label"].as_str()).unwrap_or(""),"text":snippet,"plain":plain}),
    )
}

/// Paste into a disposable TXT snapshot; failures leave the input unchanged.
pub fn paste_txt(
    text: &str,
    captured: &Value,
    destination: &Value,
    with_meaning: bool,
) -> Result<(String, Value), TxtTransferError> {
    if captured["media"] != "txt" {
        return Err(fail(
            "서로 다른 파일 형식 사이의 의미 붙여넣기는 지원하지 않습니다.",
        ));
    }
    let start = offset(text, destination.get("start"))?;
    let end = offset(text, destination.get("end"))?;
    if start > end {
        return Err(fail("붙여넣을 범위가 올바르지 않습니다."));
    }
    let kind = captured["kind"]
        .as_str()
        .ok_or_else(|| fail("복사한 의미 데이터가 올바르지 않습니다."))?;
    let raw = if with_meaning {
        captured.get("text")
    } else {
        captured.get("plain")
    }
    .ok_or_else(|| fail("복사한 의미 데이터가 올바르지 않습니다."))?;
    let mut snippet = python_str(raw);
    let before = analyze(text);
    if with_meaning {
        let names = iter_field_token_matches(&snippet)
            .into_iter()
            .map(|found| python_trim(found.body).to_owned())
            .collect::<HashSet<_>>();
        let existing = before["fields"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|row| row["name"].as_str())
            .collect::<HashSet<_>>();
        if names.iter().any(|name| existing.contains(name.as_str()))
            && destination.get("link_existing") != Some(&Value::Bool(true))
        {
            return Err(fail(
                "같은 이름의 필드가 있습니다. 기존 필드 연결을 확인하세요.",
            ));
        }
    }
    if with_meaning && matches!(kind, "slot" | "option") {
        if before["diagnostics"]
            .as_array()
            .is_some_and(|rows| !rows.is_empty())
        {
            return Err(fail("대상 문서의 구조 오류를 먼저 수정하세요."));
        }
        if start != end || (start != 0 && !matches!(text.chars().nth(start - 1), Some('\r' | '\n')))
        {
            return Err(fail("의미 영역은 줄 시작 위치에 붙여넣으세요."));
        }
        let identifier = destination
            .get("new_id")
            .filter(|value| python_truthy(value))
            .or_else(|| captured.get("id"));
        let Some(identifier) = identifier
            .and_then(Value::as_str)
            .filter(|value| !python_trim(value).is_empty())
        else {
            return Err(fail("새 식별자를 입력하세요."));
        };
        if kind == "slot"
            && before["slots"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|slot| slot["id"] == identifier)
        {
            return Err(fail("같은 항목 식별자가 있습니다. 새 식별자를 입력하세요."));
        }
        if kind == "option" {
            let owner = before["slots"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|slot| slot["id"] == destination["slot_id"]);
            if owner.is_none()
                || owner.is_some_and(|owner| {
                    owner["options"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .any(|option| option["id"] == identifier)
                })
            {
                return Err(fail("상위 항목이나 선택 식별자를 확인하세요."));
            }
        }
        let lines = splitlines(&snippet);
        let Some(first) = lines.first() else {
            return Err(fail("복사한 의미 데이터가 올바르지 않습니다."));
        };
        let eol = if first.whole.contains("\r\n") {
            "\r\n"
        } else {
            "\n"
        };
        let opening = begin_marker_text(
            kind,
            identifier,
            captured["label"].as_str().filter(|value| !value.is_empty()),
        )
        .map_err(|error| fail(error.to_string()))?;
        snippet = format!(
            "{opening}{eol}{}",
            lines
                .iter()
                .skip(1)
                .map(|line| line.whole)
                .collect::<String>()
        );
    }
    let result = format!(
        "{}{}{}",
        part(text, 0, start),
        snippet,
        part(text, end, chars(text))
    );
    let after = analyze(&result);
    if with_meaning
        && matches!(kind, "slot" | "option")
        && after["diagnostics"]
            .as_array()
            .is_some_and(|rows| !rows.is_empty())
    {
        return Err(fail("이 위치에 붙여넣으면 항목·선택 구조가 깨집니다."));
    }
    let previous = part(text, start, end);
    Ok((
        result,
        json!({"edits":[{"start":units(text,start),"end":units(text,end),"text":snippet}],
        "affected":1,"before":previous,"after":snippet,"original":previous,"captured_text":previous,
        "result":after,"expanded":false}),
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn captured_field_and_region_paste_preserve_source_and_meaning_choice() {
        let source = "{{이름}}\n";
        let captured = capture_txt(source, &json!({"kind":"field","start":1})).unwrap();
        assert!(
            paste_txt("{{이름}}\n", &captured, &json!({"start":7,"end":7}), true)
                .unwrap_err()
                .0
                .contains("기존 필드 연결")
        );
        let (linked, linked_impact) = paste_txt(
            "{{이름}}\n",
            &captured,
            &json!({"start":7,"end":7,"link_existing":true}),
            true,
        )
        .unwrap();
        assert_eq!(linked, "{{이름}}\n{{이름}}");
        assert_eq!(linked_impact["affected"], 1);
        let (plain, impact) = paste_txt("", &captured, &json!({"start":0,"end":0}), false).unwrap();
        assert_eq!(plain, "이름");
        assert_eq!(impact["after"], "이름");
        assert_eq!(source, "{{이름}}\n");

        let block = "{{#항목 s}}\n{{#선택 a}}\n본문\n{{/선택}}\n{{/항목}}\n";
        let region = capture_txt(block, &json!({"kind":"slot","slot_id":"s"})).unwrap();
        let (pasted, impact) =
            paste_txt("", &region, &json!({"start":0,"end":0,"new_id":"t"}), true).unwrap();
        assert!(pasted.starts_with("{{#항목 t}}\n"));
        assert_eq!(impact["result"]["slots"][0]["id"], "t");
        assert_eq!(impact["result"]["slots"][0]["options"][0]["id"], "a");
        assert_eq!(
            block,
            "{{#항목 s}}\n{{#선택 a}}\n본문\n{{/선택}}\n{{/항목}}\n"
        );
        assert!(
            paste_txt(
                "본문",
                &region,
                &json!({"start":1,"end":1,"new_id":"other"}),
                true
            )
            .unwrap_err()
            .0
            .contains("줄 시작")
        );
        assert!(
            capture_txt("😀본문", &json!({"kind":"text","start":1,"end":3}))
                .unwrap_err()
                .0
                .contains("문자 경계")
        );
        for (text, selector, reason) in [
            ("본문", json!({"kind":"field","start":0}), "필드 사용 위치"),
            (
                "본문",
                json!({"kind":"text","start":1,"end":1}),
                "본문을 고르",
            ),
            ("본문", json!({"kind":"unknown"}), "의미 요소"),
            (
                "{{#항목 s}}\n본문\n",
                json!({"kind":"slot","slot_id":"s"}),
                "구조 오류",
            ),
        ] {
            assert!(capture_txt(text, &selector).unwrap_err().0.contains(reason));
        }
        for (text, destination, reason) in [
            ("본문", json!({"start":2,"end":1}), "범위"),
            ("본문", json!({"start":0,"end":1}), "줄 시작"),
            (
                "{{#항목 broken}}\n",
                json!({"start":0,"end":0}),
                "구조 오류",
            ),
        ] {
            assert!(
                paste_txt(text, &region, &destination, true)
                    .unwrap_err()
                    .0
                    .contains(reason)
            );
        }
    }
}
