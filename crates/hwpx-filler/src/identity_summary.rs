//! Stable record labels shared by result tables, delivery and workbench projections.

use crate::data_source::Record;
use crate::structure_scan::python_trim;
use hwpx_core::text_extract::decimal_digit;
use std::collections::{HashMap, HashSet};

pub const BLANK_CELL_MARK: &str = "(빈칸)";
pub const COGNITION_WIDTH: usize = 2;
pub const MAX_COLUMNS: usize = 3;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DisqualifierStats {
    pub empty: usize,
    pub constant: usize,
    pub ordinal: Vec<String>,
    pub duplicate: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SummaryStep {
    pub layer: &'static str,
    pub column: Option<String>,
    pub residual: Option<usize>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IdentitySummary {
    pub columns: Vec<String>,
    pub residual_collisions: usize,
    pub token_mode: bool,
    pub steps: Vec<SummaryStep>,
    pub disqualified: DisqualifierStats,
}
impl IdentitySummary {
    pub fn summary_for(&self, record: &Record) -> String {
        self.columns
            .iter()
            .map(|column| cell(record, column))
            .collect::<Vec<_>>()
            .join(" · ")
    }
    pub fn display_for(&self, record: &Record) -> String {
        self.columns
            .iter()
            .map(|column| {
                let value = cell(record, column);
                if value.is_empty() {
                    BLANK_CELL_MARK.into()
                } else {
                    value
                }
            })
            .collect::<Vec<_>>()
            .join(" · ")
    }
    pub fn collision_flags(&self, rows: &[Record]) -> Vec<bool> {
        let keys = rows
            .iter()
            .map(|row| key(row, &self.columns))
            .collect::<Vec<_>>();
        let mut counts = HashMap::new();
        for item in &keys {
            *counts.entry(item).or_insert(0usize) += 1;
        }
        keys.iter().map(|item| counts[item] > 1).collect()
    }
}
fn cell(record: &Record, column: &str) -> String {
    record
        .get(column)
        .map(|value| python_trim(value).to_owned())
        .unwrap_or_default()
}
fn key(row: &Record, columns: &[String]) -> String {
    columns
        .iter()
        .map(|column| cell(row, column))
        .collect::<Vec<_>>()
        .join("\u{001f}")
}
fn collisions(rows: &[Record], columns: &[String]) -> usize {
    let mut counts = HashMap::new();
    for row in rows {
        *counts.entry(key(row, columns)).or_insert(0usize) += 1;
    }
    counts.values().filter(|count| **count > 1).sum()
}
fn ordinal(values: &[String]) -> bool {
    if values.len() < 2 {
        return false;
    }
    let numbers = values
        .iter()
        .map(|value| {
            if value.is_empty() {
                return None;
            }
            let mut digits = String::new();
            for ch in value.chars() {
                digits.push(char::from_digit(decimal_digit(ch)?, 10)?);
            }
            let trimmed = digits.trim_start_matches('0');
            Some(if trimmed.is_empty() {
                "0".into()
            } else {
                trimmed.to_owned()
            })
        })
        .collect::<Option<Vec<_>>>();
    let Some(numbers) = numbers else {
        return false;
    };
    numbers
        .iter()
        .enumerate()
        .all(|(index, number)| number == &index.to_string())
        || numbers
            .iter()
            .enumerate()
            .all(|(index, number)| number == &(index + 1).to_string())
}
fn static_reason(values: &[String]) -> Option<&'static str> {
    if values.iter().all(String::is_empty) {
        Some("empty")
    } else if values.iter().collect::<HashSet<_>>().len() <= 1 {
        Some("constant")
    } else if ordinal(values) {
        Some("ordinal")
    } else {
        None
    }
}
fn eligible(
    column: &str,
    chosen: &[String],
    given: &HashSet<&str>,
    static_reasons: &HashMap<String, Option<&'static str>>,
    values: &HashMap<String, Vec<String>>,
) -> bool {
    !given.contains(column)
        && !chosen.iter().any(|name| name == column)
        && static_reasons.get(column) == Some(&None)
        && !chosen
            .iter()
            .any(|name| values.get(name) == values.get(column))
}
/// The initial column set: left-to-right cognition picks with no filename tokens given,
/// or a single token-mode marker step when tokens were given (no cognition picks then).
fn seed_columns(
    rows: &[Record],
    cols: &[String],
    given: &HashSet<&str>,
    reasons: &HashMap<String, Option<&'static str>>,
    values: &HashMap<String, Vec<String>>,
) -> (Vec<String>, Vec<SummaryStep>) {
    let mut columns = Vec::new();
    let mut steps = Vec::new();
    if given.is_empty() {
        for column in cols {
            if columns.len() >= COGNITION_WIDTH {
                break;
            }
            if eligible(column, &columns, given, reasons, values) {
                columns.push(column.clone());
                steps.push(SummaryStep {
                    layer: "cognition",
                    column: Some(column.clone()),
                    residual: Some(collisions(rows, &columns)),
                });
            }
        }
    } else {
        steps.push(SummaryStep {
            layer: "token-mode",
            column: None,
            residual: None,
        });
    }
    (columns, steps)
}
/// Greedily add the best remaining discriminator column until collisions clear,
/// no eligible column improves the residual, or `MAX_COLUMNS` is reached.
fn discriminate(
    rows: &[Record],
    cols: &[String],
    given: &HashSet<&str>,
    reasons: &HashMap<String, Option<&'static str>>,
    values: &HashMap<String, Vec<String>>,
    columns: &mut Vec<String>,
    steps: &mut Vec<SummaryStep>,
) {
    while columns.len() < MAX_COLUMNS {
        let current = collisions(rows, columns);
        if current == 0 {
            break;
        }
        let mut best = None;
        for column in cols {
            if !eligible(column, columns, given, reasons, values) {
                continue;
            }
            let mut probe = columns.clone();
            probe.push(column.clone());
            let score = collisions(rows, &probe);
            if best
                .as_ref()
                .is_none_or(|(_, old_score)| score < *old_score)
            {
                best = Some((column.clone(), score));
            }
        }
        let Some((column, score)) = best else {
            steps.push(SummaryStep {
                layer: "stop",
                column: None,
                residual: Some(current),
            });
            break;
        };
        if score >= current {
            steps.push(SummaryStep {
                layer: "stop",
                column: None,
                residual: Some(current),
            });
            break;
        }
        columns.push(column.clone());
        steps.push(SummaryStep {
            layer: "discrimination",
            column: Some(column),
            residual: Some(score),
        });
    }
}
/// Classify every column not already chosen or given by filename token into its disqualifier bucket.
fn disqualify(
    cols: &[String],
    given: &HashSet<&str>,
    reasons: &HashMap<String, Option<&'static str>>,
    values: &HashMap<String, Vec<String>>,
    columns: &[String],
) -> DisqualifierStats {
    let mut stats = DisqualifierStats::default();
    for column in cols {
        if given.contains(column.as_str()) {
            continue;
        }
        match reasons[column] {
            Some("empty") => stats.empty += 1,
            Some("constant") => stats.constant += 1,
            Some("ordinal") => stats.ordinal.push(column.clone()),
            _ if !columns.contains(column)
                && columns.iter().any(|name| values[name] == values[column]) =>
            {
                stats.duplicate.push(column.clone())
            }
            _ => (),
        }
    }
    stats
}
pub fn identity_summary(
    rows: &[Record],
    columns: Option<&[String]>,
    filename_tokens: &[String],
) -> IdentitySummary {
    let cols = columns.map_or_else(
        || {
            rows.first()
                .map_or_else(Vec::new, |row| row.keys().cloned().collect())
        },
        ToOwned::to_owned,
    );
    let given = filename_tokens
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let mut result = IdentitySummary {
        columns: vec![],
        residual_collisions: 0,
        token_mode: !given.is_empty(),
        steps: vec![],
        disqualified: DisqualifierStats::default(),
    };
    if rows.is_empty() || cols.is_empty() {
        return result;
    }
    let values = cols
        .iter()
        .map(|column| {
            (
                column.clone(),
                rows.iter().map(|row| cell(row, column)).collect::<Vec<_>>(),
            )
        })
        .collect::<HashMap<_, _>>();
    let reasons = cols
        .iter()
        .map(|column| (column.clone(), static_reason(&values[column])))
        .collect::<HashMap<_, _>>();
    let (seeded, seeded_steps) = seed_columns(rows, &cols, &given, &reasons, &values);
    result.columns = seeded;
    result.steps = seeded_steps;
    discriminate(
        rows,
        &cols,
        &given,
        &reasons,
        &values,
        &mut result.columns,
        &mut result.steps,
    );
    result.residual_collisions = collisions(rows, &result.columns);
    result.disqualified = disqualify(&cols, &given, &reasons, &values, &result.columns);
    result
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn left_cognition_then_best_discriminator_excludes_row_ordinal() {
        let rows = [
            [("A", "alpha"), ("B", "x"), ("C", "1"), ("D", "a")],
            [("A", "alpha"), ("B", "x"), ("C", "2"), ("D", "b")],
            [("A", "beta"), ("B", "y"), ("C", "3"), ("D", "c")],
        ]
        .into_iter()
        .map(|row| {
            row.into_iter()
                .map(|(key, value)| (key.into(), value.into()))
                .collect::<Record>()
        })
        .collect::<Vec<_>>();
        let summary = identity_summary(&rows, None, &[]);
        assert_eq!(summary.columns, ["A", "B", "D"]);
        assert_eq!(summary.disqualified.ordinal, ["C"]);
        assert_eq!(summary.residual_collisions, 0);
        assert_eq!(summary.display_for(&rows[1]), "alpha · x · b");
        assert_eq!(summary.collision_flags(&rows), [false; 3]);
        let token = identity_summary(&rows, None, &["A".into()]);
        assert_eq!(token.columns, ["D"]);
        assert!(token.token_mode);
    }

    #[test]
    fn nara_wide_record_identity_ignores_decoy_columns() {
        let encoded: Vec<serde_json::Value> = serde_json::from_slice(include_bytes!(
            "../../../tests/fixtures/identity_summary_nara.json"
        ))
        .unwrap();
        let rows: Vec<Record> = encoded
            .into_iter()
            .map(|row| {
                row.as_object()
                    .unwrap()
                    .iter()
                    .map(|(key, value)| (key.clone(), value.as_str().unwrap().to_owned()))
                    .collect()
            })
            .collect();
        assert_eq!((rows.len(), rows[0].len()), (12, 53));
        let columns = rows[0].keys().cloned().collect::<Vec<_>>();
        let summary = identity_summary(&rows, Some(&columns), &[]);
        assert_eq!(summary.columns, ["bidNtceNo", "bidNtceNm"]);
        assert_eq!(summary.residual_collisions, 0);
        assert_eq!(summary.disqualified.duplicate, ["refNtceNo"]);
        assert_eq!(
            (summary.disqualified.empty, summary.disqualified.constant),
            (6, 10)
        );
        assert_eq!(
            summary.summary_for(&rows[0]),
            "R26BK01621756 · Adobe Creative Cloud 라이선스 연간사용권 구매"
        );
        assert_eq!(summary.collision_flags(&rows), [false; 12]);
    }

    #[test]
    fn token_and_duplicate_backstops_keep_identity_honest() {
        let rows = (0..8)
            .map(|index| {
                let slot = index % 4;
                [
                    ("연번".into(), (index + 1).to_string()),
                    ("부서".into(), "재무과".into()),
                    (
                        "담당자".into(),
                        ["김OO", "김OO", "이OO", "이OO"][slot].into(),
                    ),
                    (
                        "품명".into(),
                        [
                            "사무용 소모품 일괄",
                            "OO의약품 외 2행",
                            "사무용 소모품 일괄",
                            "실험기자재",
                        ][slot]
                            .into(),
                    ),
                    ("규격".into(), ["A형", "-", "B형", "C형"][slot].into()),
                    ("기초금액".into(), (10_000_000 + index * 137).to_string()),
                ]
                .into_iter()
                .collect::<Record>()
            })
            .collect::<Vec<_>>();
        let columns = ["연번", "부서", "담당자", "품명", "규격", "기초금액"].map(str::to_owned);
        let normal = identity_summary(&rows, Some(&columns), &[]);
        assert_eq!(normal.columns, ["담당자", "품명", "기초금액"]);
        assert_eq!(
            normal
                .steps
                .iter()
                .map(|step| step.layer)
                .collect::<Vec<_>>(),
            ["cognition", "cognition", "discrimination"]
        );
        assert_eq!(normal.disqualified.ordinal, ["연번"]);
        assert_eq!(normal.disqualified.constant, 1);
        assert_eq!(normal.residual_collisions, 0);
        let token = identity_summary(&rows, Some(&columns), &["품명".into()]);
        assert_eq!(token.columns, ["기초금액"]);
        assert_eq!(token.steps[0].layer, "token-mode");

        let duplicate_rows = [
            ("A4 복사용지", "80g", "100"),
            ("A4 복사용지", "80g", "100"),
            ("프린터 토너", "HP정품", "2"),
            ("무선 마우스", "2.4GHz", "10"),
        ]
        .into_iter()
        .map(|(name, spec, quantity)| {
            [
                ("품명".into(), name.into()),
                ("규격".into(), spec.into()),
                ("수량".into(), quantity.into()),
            ]
            .into_iter()
            .collect::<Record>()
        })
        .collect::<Vec<_>>();
        let duplicate = identity_summary(
            &duplicate_rows,
            Some(&["품명".into(), "규격".into(), "수량".into()]),
            &[],
        );
        assert_eq!(duplicate.columns, ["품명", "규격"]);
        assert_eq!(duplicate.residual_collisions, 2);
        assert_eq!(
            duplicate.collision_flags(&duplicate_rows),
            [true, true, false, false]
        );
        assert_eq!(duplicate.steps.last().unwrap().layer, "stop");

        let joined = [("1", "23"), ("12", "3")]
            .into_iter()
            .map(|(a, b)| {
                [("a".into(), a.into()), ("b".into(), b.into())]
                    .into_iter()
                    .collect::<Record>()
            })
            .collect::<Vec<_>>();
        let separated = identity_summary(&joined, Some(&["a".into(), "b".into()]), &[]);
        assert_eq!(separated.residual_collisions, 0);
        assert_eq!(separated.collision_flags(&joined), [false, false]);
        let single = identity_summary(&duplicate_rows[..1], None, &[]);
        assert_eq!(single.residual_collisions, 0);
        assert_eq!(single.collision_flags(&duplicate_rows[..1]), [false]);

        let blanks = [("", "X"), ("X", "")]
            .into_iter()
            .map(|(a, b)| {
                [("a".into(), a.into()), ("b".into(), b.into())]
                    .into_iter()
                    .collect::<Record>()
            })
            .collect::<Vec<_>>();
        let marked = identity_summary(&blanks, Some(&["a".into(), "b".into()]), &[]);
        assert_eq!(marked.columns, ["a", "b"]);
        assert_ne!(
            marked.display_for(&blanks[0]),
            marked.display_for(&blanks[1])
        );
        assert!(marked.display_for(&blanks[0]).contains(BLANK_CELL_MARK));
        assert_eq!(marked.collision_flags(&blanks), [false, false]);

        let ids = (0..3)
            .map(|index| {
                [
                    ("공고번호".into(), (1001 + index).to_string()),
                    ("부서".into(), "총무과".into()),
                ]
                .into_iter()
                .collect::<Record>()
            })
            .collect::<Vec<_>>();
        let recognized = identity_summary(&ids, None, &[]);
        assert_eq!(recognized.columns, ["공고번호"]);
        assert!(recognized.disqualified.ordinal.is_empty());
        let ordinal_rows = (0..4)
            .map(|index| {
                [
                    ("idx".into(), index.to_string()),
                    ("name".into(), format!("n{}", index % 2)),
                ]
                .into_iter()
                .collect::<Record>()
            })
            .collect::<Vec<_>>();
        assert_eq!(
            identity_summary(&ordinal_rows, None, &[])
                .disqualified
                .ordinal,
            ["idx"]
        );
    }
}
