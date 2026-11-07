//! Row matching: column conditions, range clauses and search branches over records.

use super::{ColumnCondition, ConditionGroup, FilterError, FilterModel, fail};
use crate::data_source::Record;
use crate::filter_primitives::{KIND_AMOUNT, KIND_TEXT, RangeClause, RangeCondition, cell_text};
use crate::format_engine::{ParsedDateTime, ParsedNumber, parse_dt, parse_number};
use crate::jamo::jamo_contains;
use crate::text_render::python_repr;
use indexmap::IndexMap;
use num_bigint::BigInt;
use regex::Regex;
use serde_json::Value;
use std::cmp::Ordering;
use std::collections::HashSet;
use std::str::FromStr;
use std::sync::OnceLock;

impl FilterModel {
    pub(super) fn conds_pass(
        &self,
        conds: &IndexMap<String, ColumnCondition>,
        record: &Record,
        except_values: Option<&str>,
    ) -> Result<bool, FilterError> {
        for (column, condition) in conds {
            if !condition.active() {
                continue;
            }
            let cell = cell_text(record, column);
            if condition
                .values
                .as_ref()
                .is_some_and(|values| !values.iter().any(|value| value == cell))
                && except_values != Some(column)
            {
                return Ok(false);
            }
            if !condition.text.is_empty() && !jamo_contains(cell, &condition.text) {
                return Ok(false);
            }
            if let Some(range) = &condition.range
                && !range_pass(self.kind(column)?, range, cell)?
            {
                return Ok(false);
            }
        }
        Ok(true)
    }
    pub fn col_pass(
        &self,
        record: &Record,
        except_values: Option<&str>,
    ) -> Result<bool, FilterError> {
        self.conds_pass(&self.cols, record, except_values)
    }
    pub(super) fn search_branches(
        &self,
        search: &str,
        pruned: &HashSet<String>,
        passing: &[&Record],
    ) -> Vec<String> {
        self.columns
            .iter()
            .filter(|column| self.kinds.get(*column).map_or(KIND_TEXT, String::as_str) == KIND_TEXT)
            .filter(|column| !pruned.contains(*column))
            .filter(|column| {
                passing
                    .iter()
                    .any(|record| jamo_contains(cell_text(record, column), search))
            })
            .cloned()
            .collect()
    }
    pub(super) fn group_rows(
        &self,
        group: &ConditionGroup,
        records: &[Record],
    ) -> Result<HashSet<usize>, FilterError> {
        let mut rows = vec![];
        for (index, record) in records.iter().enumerate() {
            if self.conds_pass(&group.cols, record, None)? {
                rows.push(index);
            }
        }
        if group.search.is_empty() {
            return Ok(rows.into_iter().collect());
        }
        let passing = rows
            .iter()
            .map(|index| &records[*index])
            .collect::<Vec<_>>();
        let branches = self.search_branches(&group.search, &group.pruned, &passing);
        Ok(rows
            .into_iter()
            .filter(|index| {
                branches
                    .iter()
                    .any(|branch| jamo_contains(cell_text(&records[*index], branch), &group.search))
            })
            .collect())
    }
}

fn number_rational(value: ParsedNumber) -> Option<(BigInt, i32)> {
    match value {
        ParsedNumber::Integer(text) => BigInt::from_str(&text).ok().map(|number| (number, 0)),
        ParsedNumber::Float(number) if number.is_finite() => {
            let bits = number.to_bits();
            let exponent = ((bits >> 52) & 0x7ff) as i32;
            let mantissa = bits & ((1u64 << 52) - 1);
            let (mantissa, exponent) = if exponent == 0 {
                (mantissa, -1074)
            } else {
                (mantissa | (1u64 << 52), exponent - 1075)
            };
            let mut integer = BigInt::from(mantissa);
            if bits >> 63 == 1 {
                integer = -integer;
            }
            Some((integer, exponent))
        }
        _ => None,
    }
}
fn compare_number(left: ParsedNumber, right: ParsedNumber) -> Option<Ordering> {
    let (mut left, left_exp) = number_rational(left)?;
    let (mut right, right_exp) = number_rational(right)?;
    if left_exp > right_exp {
        left <<= (left_exp - right_exp) as usize;
    }
    if right_exp > left_exp {
        right <<= (right_exp - left_exp) as usize;
    }
    Some(left.cmp(&right))
}
fn compare_date(left: ParsedDateTime, right: ParsedDateTime, with_time: bool) -> Ordering {
    let left_date = (left.year, left.month, left.day);
    let right_date = (right.year, right.month, right.day);
    left_date.cmp(&right_date).then_with(|| {
        if with_time {
            (left.hour, left.minute).cmp(&(right.hour, right.minute))
        } else {
            Ordering::Equal
        }
    })
}
fn time_form() -> &'static Regex {
    static TIME: OnceLock<Regex> = OnceLock::new();
    TIME.get_or_init(|| Regex::new(r"\d{1,2}:\d{2}").expect("static time grammar"))
}
fn clause_pass(kind: &str, clause: &RangeClause, cell: &str) -> Result<bool, FilterError> {
    let compared = if kind == KIND_AMOUNT {
        let Some(cell) = parse_number(cell) else {
            return Ok(false);
        };
        let operand = parse_number(&clause.operand).ok_or_else(|| {
            fail(format!(
                "범위 값 {} 을(를) 해석할 수 없습니다",
                python_repr(&Value::String(clause.operand.clone()))
            ))
        })?;
        compare_number(cell, operand).ok_or_else(|| fail("범위 숫자를 비교할 수 없습니다"))?
    } else {
        let Some(cell) = parse_dt(cell) else {
            return Ok(false);
        };
        let operand = parse_dt(&clause.operand).ok_or_else(|| {
            fail(format!(
                "범위 값 {} 을(를) 해석할 수 없습니다",
                python_repr(&Value::String(clause.operand.clone()))
            ))
        })?;
        compare_date(cell, operand, time_form().is_match(&clause.operand))
    };
    Ok(match clause.op.as_str() {
        "eq" => compared == Ordering::Equal,
        "ne" => compared != Ordering::Equal,
        "gt" => compared == Ordering::Greater,
        "ge" => compared != Ordering::Less,
        "lt" => compared == Ordering::Less,
        "le" => compared != Ordering::Greater,
        _ => return Err(fail("알 수 없는 비교 연산자")),
    })
}
fn range_pass(kind: &str, condition: &RangeCondition, cell: &str) -> Result<bool, FilterError> {
    let first = clause_pass(kind, &condition.first, cell)?;
    let Some(second) = &condition.second else {
        return Ok(first);
    };
    let second = clause_pass(kind, second, cell)?;
    Ok(if condition.joiner == "and" {
        first && second
    } else {
        first || second
    })
}
