//! Human-readable condition labels for chips, descriptions and preset names.

use super::ColumnCondition;
use crate::filter_primitives::RangeCondition;

fn value_label(value: &str) -> &str {
    if value.is_empty() { "(빈값)" } else { value }
}
fn op_label(op: &str) -> &str {
    match op {
        "eq" => "=",
        "ne" => "≠",
        "gt" => ">",
        "ge" => "≥",
        "lt" => "<",
        "le" => "≤",
        _ => "?",
    }
}
fn joiner_label(joiner: &str) -> &str {
    if joiner == "and" { "∧" } else { "∨" }
}
pub(super) fn describe_condition(column: &str, condition: &ColumnCondition) -> Vec<String> {
    let mut parts = vec![];
    if let Some(values) = &condition.values {
        if values.len() == 1 {
            parts.push(format!("{column} = {}", value_label(&values[0])));
        } else {
            parts.push(format!(
                "{column} ∈ {{{}}}",
                values
                    .iter()
                    .map(|value| value_label(value))
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
    }
    if !condition.text.is_empty() {
        parts.push(format!("{column} 포함 '{}'", condition.text));
    }
    if let Some(range) = &condition.range {
        let mut text = format!(
            "{column} {} '{}'",
            op_label(&range.first.op),
            range.first.operand
        );
        if let Some(second) = &range.second {
            text.push_str(&format!(
                " {} {} '{}'",
                joiner_label(&range.joiner),
                op_label(&second.op),
                second.operand
            ));
        }
        parts.push(text);
    }
    parts
}
pub(super) fn short_condition(column: &str, condition: &ColumnCondition) -> Vec<String> {
    let mut parts = vec![];
    if let Some(values) = &condition.values {
        let values = values
            .iter()
            .map(|value| value_label(value))
            .collect::<Vec<_>>();
        match values.len() {
            0 => parts.push(format!("{column} ∈ {{}}")),
            1 => parts.push(format!("{column} {}", values[0])),
            count => parts.push(format!("{column} {} 외 {}개", values[0], count - 1)),
        }
    }
    if !condition.text.is_empty() {
        parts.push(format!("{column} 포함 '{}'", condition.text));
    }
    if let Some(range) = &condition.range {
        parts.push(short_range(column, range));
    }
    parts
}
/// A `ge … and lt …` pair reads as `a~b`; any other range keeps its operators.
fn short_range(column: &str, range: &RangeCondition) -> String {
    if range.joiner == "and"
        && range.first.op == "ge"
        && range
            .second
            .as_ref()
            .is_some_and(|second| second.op == "lt")
    {
        let second = range.second.as_ref().expect("checked second");
        return format!("{column} {}~{}", range.first.operand, second.operand);
    }
    let mut text = format!(
        "{column} {} {}",
        op_label(&range.first.op),
        range.first.operand
    );
    if let Some(second) = &range.second {
        text.push_str(&format!(
            " {} {} {}",
            joiner_label(&range.joiner),
            op_label(&second.op),
            second.operand
        ));
    }
    text
}
pub(super) fn search_part(search: &str, branches: &[String]) -> String {
    if branches.is_empty() {
        format!("검색 '{search}' (매치 없음)")
    } else {
        format!("({}) 포함 '{search}'", branches.join(" ∨ "))
    }
}
