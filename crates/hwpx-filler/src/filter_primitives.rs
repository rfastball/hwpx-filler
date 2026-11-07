//! Shared pure grammar for the Job screen's declared column filters.

use crate::data_source::Record;
use crate::format_engine::{parse_dt, parse_number};
use crate::structure_scan::python_trim;
use regex::Regex;
use std::collections::HashMap;
use std::sync::OnceLock;

pub const KIND_TEXT: &str = "text";
pub const KIND_AMOUNT: &str = "amount";
pub const KIND_DATE: &str = "date";
pub const PRESET_UNREADABLE: &str = "이 필터의 저장 형식을 읽을 수 없습니다.";

pub fn cell_text<'a>(record: &'a Record, column: &str) -> &'a str {
    record.get(column).map_or("", String::as_str)
}

fn date_forms() -> &'static [Regex; 2] {
    static DATE: OnceLock<[Regex; 2]> = OnceLock::new();
    DATE.get_or_init(|| {
        [
            Regex::new(r"^\d{4}\D+\d{1,2}\D+\d{1,2}(\D.*)?$").expect("static date grammar"),
            Regex::new(r"^\d{8}(\D.*)?$").expect("static date grammar"),
        ]
    })
}
fn amount_form() -> &'static Regex {
    static AMOUNT: OnceLock<Regex> = OnceLock::new();
    AMOUNT.get_or_init(|| {
        Regex::new(r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[\s\x{001C}-\x{001F}]*원?$")
            .expect("static amount grammar")
    })
}

pub fn is_dateish(value: &str) -> bool {
    let trimmed = python_trim(value);
    date_forms().iter().any(|pattern| pattern.is_match(trimmed)) && parse_dt(trimmed).is_some()
}
pub fn is_amountish(value: &str) -> bool {
    amount_form().is_match(python_trim(value))
}

pub fn sniff_column_kinds(
    records: &[Record],
    hints: &HashMap<String, String>,
) -> HashMap<String, String> {
    let mut kinds = HashMap::new();
    let Some(first) = records.first() else {
        return kinds;
    };
    for column in first.keys() {
        if let Some(hint) = hints
            .get(column)
            .filter(|hint| matches!(hint.as_str(), KIND_TEXT | KIND_AMOUNT | KIND_DATE))
        {
            kinds.insert(column.clone(), hint.clone());
            continue;
        }
        let values = records
            .iter()
            .map(|record| python_trim(cell_text(record, column)))
            .filter(|value| !value.is_empty())
            .collect::<Vec<_>>();
        let kind = if !values.is_empty() && values.iter().all(|value| is_amountish(value)) {
            KIND_AMOUNT
        } else if !values.is_empty() && values.iter().all(|value| is_dateish(value)) {
            KIND_DATE
        } else {
            KIND_TEXT
        };
        kinds.insert(column.clone(), kind.into());
    }
    kinds
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RangeClause {
    pub op: String,
    pub operand: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RangeCondition {
    pub first: RangeClause,
    pub second: Option<RangeClause>,
    pub joiner: String,
}

pub fn range_condition_from_payload(
    first: Option<&serde_json::Value>,
    second: Option<&serde_json::Value>,
    joiner: Option<&str>,
) -> Result<Option<RangeCondition>, &'static str> {
    fn clause(raw: Option<&serde_json::Value>) -> Result<Option<RangeClause>, &'static str> {
        let Some(raw) = raw.filter(|value| !value.is_null()) else {
            return Ok(None);
        };
        let Some(map) = raw.as_object() else {
            return Err(PRESET_UNREADABLE);
        };
        let operand = map
            .get("operand")
            .filter(|value| !value.is_null())
            .map_or_else(String::new, |value| match value {
                serde_json::Value::String(text) => text.clone(),
                _ => crate::text_render::python_repr(value),
            });
        let operand = python_trim(&operand).to_owned();
        if operand.is_empty() {
            return Ok(None);
        }
        let op = map
            .get("op")
            .filter(|value| !value.is_null())
            .map_or_else(String::new, |value| match value {
                serde_json::Value::String(text) => text.clone(),
                _ => crate::text_render::python_repr(value),
            });
        Ok(Some(RangeClause { op, operand }))
    }
    let Some(first) = clause(first)? else {
        return Ok(None);
    };
    Ok(Some(RangeCondition {
        first,
        second: clause(second)?,
        joiner: joiner
            .filter(|value| !value.is_empty())
            .unwrap_or("and")
            .into(),
    }))
}

pub fn valid_range_operand(kind: &str, value: &str) -> bool {
    match kind {
        KIND_AMOUNT => is_amountish(value) && parse_number(value).is_some(),
        KIND_DATE => is_dateish(value),
        _ => false,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn sniff_and_range_grammar_keep_safe_text_fallback() {
        let mut row = Record::new();
        row.insert("bid".into(), "12,000원".into());
        row.insert("notice".into(), "1차".into());
        row.insert("due".into(), "2026-07-15".into());
        row.insert("blank".into(), "".into());
        let kinds = sniff_column_kinds(&[row], &HashMap::new());
        assert_eq!(kinds["bid"], KIND_AMOUNT);
        assert_eq!(kinds["notice"], KIND_TEXT);
        assert_eq!(kinds["due"], KIND_DATE);
        assert_eq!(kinds["blank"], KIND_TEXT);
        assert!(is_amountish("12\u{001c}원"));
        assert!(!is_amountish("1억"));
        assert!(!is_dateish("제2026-15호"));
        let condition =
            range_condition_from_payload(Some(&json!({"op":"ge","operand":" 100 "})), None, None)
                .unwrap()
                .unwrap();
        assert_eq!(condition.first.operand, "100");
        assert!(
            range_condition_from_payload(Some(&json!({"operand":" "})), None, None)
                .unwrap()
                .is_none()
        );
        assert_eq!(
            range_condition_from_payload(Some(&json!(1)), None, None).unwrap_err(),
            PRESET_UNREADABLE
        );
    }
}
