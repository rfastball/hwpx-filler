//! Pure document-value evidence for the authoring proposal panel.

use crate::format_engine::{presets, render as product_render};
use crate::structure_scan::python_trim;
use chrono::{Datelike, NaiveDate};
use hwpx_core::text_extract::decimal_digit;
use regex::Regex;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::OnceLock;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct CellRef {
    pub table: String,
    pub row: i64,
    pub col: i64,
    pub row_span: i64,
    pub col_span: i64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParagraphText {
    pub key: String,
    pub text: String,
    pub editable_end: usize,
    pub field_spans: Vec<(usize, usize)>,
    pub cell: Option<CellRef>,
}

#[derive(Clone, Copy, Debug)]
pub struct Transform {
    pub id: &'static str,
    pub family: &'static str,
    pub complexity: f64,
    pub kind: &'static str,
    pub fmt: &'static str,
    pub partial: bool,
}

impl Transform {
    pub fn binding(self) -> Value {
        let label = if self.family == "identity" {
            ""
        } else {
            presets(self.kind)
                .into_iter()
                .find_map(|(label, code)| (code == self.fmt).then_some(label))
                .unwrap_or(self.fmt)
        };
        json!({"type":self.kind,"fmt":self.fmt,"label":label})
    }
}

pub const TRANSFORMS: [Transform; 12] = [
    Transform {
        id: "identity",
        family: "identity",
        complexity: 0.0,
        kind: "text",
        fmt: "",
        partial: false,
    },
    Transform {
        id: "number_grouping",
        family: "number",
        complexity: 1.0,
        kind: "amount",
        fmt: "{:,}",
        partial: false,
    },
    Transform {
        id: "date_iso",
        family: "date",
        complexity: 1.0,
        kind: "date",
        fmt: "%Y-%m-%d",
        partial: false,
    },
    Transform {
        id: "date_dot",
        family: "date",
        complexity: 1.0,
        kind: "date",
        fmt: "%Y.%m.%d",
        partial: false,
    },
    Transform {
        id: "date_dot_spaced",
        family: "date",
        complexity: 1.2,
        kind: "date",
        fmt: "",
        partial: false,
    },
    Transform {
        id: "date_dot_ym",
        family: "date",
        complexity: 1.2,
        kind: "date",
        fmt: "ym",
        partial: true,
    },
    Transform {
        id: "date_korean",
        family: "date",
        complexity: 1.2,
        kind: "date",
        fmt: "kor_date",
        partial: false,
    },
    Transform {
        id: "date_korean_padded",
        family: "date",
        complexity: 1.3,
        kind: "date",
        fmt: "%Y년 %m월 %d일",
        partial: false,
    },
    Transform {
        id: "date_slash",
        family: "date",
        complexity: 1.0,
        kind: "date",
        fmt: "%Y/%m/%d",
        partial: false,
    },
    Transform {
        id: "datetime_iso",
        family: "datetime",
        complexity: 1.0,
        kind: "date",
        fmt: "%Y-%m-%d %H:%M",
        partial: false,
    },
    Transform {
        id: "datetime_dot_spaced",
        family: "datetime",
        complexity: 1.3,
        kind: "date",
        fmt: "datetime",
        partial: false,
    },
    Transform {
        id: "datetime_korean",
        family: "datetime",
        complexity: 1.3,
        kind: "date",
        fmt: "kor",
        partial: false,
    },
];

pub fn transform(id: &str) -> Option<Transform> {
    TRANSFORMS.iter().copied().find(|item| item.id == id)
}

fn normalized_digits(text: &str) -> Option<String> {
    text.chars()
        .map(|ch| decimal_digit(ch).map(|digit| (b'0' + digit as u8) as char))
        .collect()
}

fn date_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"^(\d{4})([-/.])(\d{2})([-/.])(\d{2})$").expect("static date pattern")
    })
}
fn datetime_pattern() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| {
        Regex::new(r"^(\d{4})([-/.])(\d{2})([-/.])(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$")
            .expect("static datetime pattern")
    })
}

fn parse_date(value: &str) -> Option<(NaiveDate, Option<(u32, u32)>)> {
    let value = python_trim(value);
    if let Some(parts) = date_pattern().captures(value) {
        if parts.get(2)?.as_str() != parts.get(4)?.as_str() {
            return None;
        }
        let year = normalized_digits(parts.get(1)?.as_str())?.parse().ok()?;
        let month = normalized_digits(parts.get(3)?.as_str())?.parse().ok()?;
        let day = normalized_digits(parts.get(5)?.as_str())?.parse().ok()?;
        return NaiveDate::from_ymd_opt(year, month, day).map(|date| (date, None));
    }
    let parts = datetime_pattern().captures(value)?;
    if parts.get(2)?.as_str() != parts.get(4)?.as_str() {
        return None;
    }
    let year = normalized_digits(parts.get(1)?.as_str())?.parse().ok()?;
    let month = normalized_digits(parts.get(3)?.as_str())?.parse().ok()?;
    let day = normalized_digits(parts.get(5)?.as_str())?.parse().ok()?;
    let hour = normalized_digits(parts.get(6)?.as_str())?.parse().ok()?;
    let minute = normalized_digits(parts.get(7)?.as_str())?.parse().ok()?;
    let date = NaiveDate::from_ymd_opt(year, month, day)?;
    date.and_hms_opt(hour, minute, 0)?;
    Some((date, Some((hour, minute))))
}

fn number_grouping(value: &str) -> Option<String> {
    let text = python_trim(value);
    let (negative, unsigned) = text
        .strip_prefix('-')
        .map_or((false, text), |rest| (true, rest));
    let (whole, fractional) = unsigned
        .split_once('.')
        .map_or((unsigned, None), |(a, b)| (a, Some(b)));
    if whole.is_empty()
        || fractional.is_some_and(str::is_empty)
        || !whole.chars().all(|ch| decimal_digit(ch).is_some())
        || fractional.is_some_and(|part| !part.chars().all(|ch| decimal_digit(ch).is_some()))
    {
        return None;
    }
    let canonical = whole == "0"
        || whole
            .chars()
            .next()
            .is_some_and(|ch| ('1'..='9').contains(&ch));
    if !canonical {
        return None;
    }
    let whole = normalized_digits(whole)?;
    let digits: Vec<char> = whole.chars().collect();
    let mut grouped = String::new();
    for (index, ch) in digits.iter().enumerate() {
        if index > 0 && (digits.len() - index).is_multiple_of(3) {
            grouped.push(',');
        }
        grouped.push(*ch);
    }
    if negative {
        grouped.insert(0, '-');
    }
    if let Some(frac) = fractional {
        grouped.push('.');
        grouped.push_str(frac);
    }
    Some(grouped)
}

fn render_transform(spec: Transform, value: &str) -> Option<String> {
    if spec.id == "identity" {
        return Some(value.into());
    }
    if spec.id == "number_grouping" {
        return number_grouping(value);
    }
    let (date, time) = parse_date(value)?;
    if spec.family == "datetime" && time.is_none()
        || spec.family == "date" && time.is_some() && spec.id != "date_dot_ym"
    {
        return None;
    }
    let (year, month, day) = (date.year(), date.month(), date.day());
    Some(match spec.id {
        "date_iso" => format!("{year:04}-{month:02}-{day:02}"),
        "date_dot" => format!("{year:04}.{month:02}.{day:02}"),
        "date_dot_spaced" => format!("{year}. {month}. {day}."),
        "date_dot_ym" => format!("{year}. {month}."),
        "date_korean" => format!("{year}년 {month}월 {day}일"),
        "date_korean_padded" => format!("{year}년 {month:02}월 {day:02}일"),
        "date_slash" => format!("{year:04}/{month:02}/{day:02}"),
        "datetime_iso" => {
            let (hour, minute) = time?;
            format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}")
        }
        "datetime_dot_spaced" => {
            let (hour, minute) = time?;
            format!("{year}. {month}. {day}. {hour:02}:{minute:02}")
        }
        "datetime_korean" => {
            let (hour, minute) = time?;
            format!("{year}년 {month}월 {day}일 {hour:02}:{minute:02}")
        }
        _ => return None,
    })
}

/// An identity rendering and a date/datetime rendering agree on the same input
/// unchanged: keep only one of the pair to avoid reporting a duplicate reading.
fn identity_date_duplicate(result: &[(Transform, String)], spec: &Transform, value: &str) -> bool {
    result.iter().any(|(prior, _)| {
        (prior.id == "identity" || spec.id == "identity")
            && matches!(
                if prior.id == "identity" {
                    spec.family
                } else {
                    prior.family
                },
                "date" | "datetime"
            )
            && render_transform(
                if prior.id == "identity" {
                    *spec
                } else {
                    *prior
                },
                value,
            )
            .as_deref()
                == Some(value)
    })
}

pub fn renderings(value: &str) -> Vec<(Transform, String)> {
    let mut specs = TRANSFORMS;
    specs.sort_by(|left, right| left.complexity.total_cmp(&right.complexity));
    let mut result: Vec<(Transform, String)> = Vec::new();
    for spec in specs {
        let Some(rendered) = render_transform(spec, value) else {
            continue;
        };
        if python_trim(&rendered).is_empty() {
            continue;
        }
        if identity_date_duplicate(&result, &spec, value) {
            continue;
        }
        if product_render(spec.kind, spec.fmt, value) != rendered {
            continue;
        }
        result.push((spec, rendered));
    }
    result
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Candidate {
    pub column: String,
    pub transform: &'static str,
    pub rendered: String,
    pub paragraph: usize,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug)]
pub struct Slot {
    pub paragraph: usize,
    pub start: usize,
    pub end: usize,
    pub candidates: Vec<Candidate>,
}

fn char_at(text: &str, at: usize) -> Option<char> {
    text.chars().nth(at)
}
fn char_slice(text: &str, start: usize, end: usize) -> String {
    text.chars()
        .skip(start)
        .take(end.saturating_sub(start))
        .collect()
}
fn is_latin(ch: char) -> bool {
    ch.is_ascii_alphabetic()
}
fn digit_glued(chars: &[char], outer: isize, step: isize) -> bool {
    let Some(ch) = usize::try_from(outer)
        .ok()
        .and_then(|at| chars.get(at).copied())
    else {
        return false;
    };
    if ch.is_numeric() || is_latin(ch) {
        return true;
    }
    (ch == ',' || ch == '.')
        && usize::try_from(outer + step)
            .ok()
            .and_then(|at| chars.get(at))
            .is_some_and(|ch| ch.is_numeric())
}
fn latin_glued(chars: &[char], outer: isize) -> bool {
    usize::try_from(outer)
        .ok()
        .and_then(|at| chars.get(at))
        .is_some_and(|ch| is_latin(*ch) || ch.is_numeric())
}
fn date_continues() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"^ \d{1,2}\.").expect("static date continuation"))
}
fn date_before() -> &'static Regex {
    static PATTERN: OnceLock<Regex> = OnceLock::new();
    PATTERN.get_or_init(|| Regex::new(r"\d{4}\. (?:\d{1,2}\. )?$").expect("static date prefix"))
}
fn inside_dot_date(text: &str, start: usize, end: usize) -> bool {
    let before = char_slice(text, 0, start);
    let after = char_slice(text, end, text.chars().count());
    (char_at(text, end - 1) == Some('.') && date_continues().is_match(&after))
        || char_at(text, start).is_some_and(|ch| ch.is_numeric()) && date_before().is_match(&before)
}
fn digit_boundary_violation(
    chars: &[char],
    start: usize,
    end: usize,
    first: char,
    last: char,
) -> bool {
    (first.is_numeric() && digit_glued(chars, start as isize - 1, -1))
        || (last.is_numeric() && digit_glued(chars, end as isize, 1))
}
fn latin_boundary_violation(
    chars: &[char],
    start: usize,
    end: usize,
    first: char,
    last: char,
) -> bool {
    (is_latin(first) && latin_glued(chars, start as isize - 1))
        || (is_latin(last) && latin_glued(chars, end as isize))
}
pub fn boundary_ok(text: &str, start: usize, end: usize) -> bool {
    let chars: Vec<char> = text.chars().collect();
    if start >= end || end > chars.len() || inside_dot_date(text, start, end) {
        return false;
    }
    let first = chars[start];
    let last = chars[end - 1];
    if digit_boundary_violation(&chars, start, end, first, last) {
        return false;
    }
    !latin_boundary_violation(&chars, start, end, first, last)
}
pub fn hangul_bounded(text: &str, start: usize, end: usize) -> bool {
    !(start > 0 && char_at(text, start - 1).is_some_and(|ch| ('가'..='힣').contains(&ch))
        || char_at(text, end).is_some_and(|ch| ('가'..='힣').contains(&ch)))
}
pub fn occurrences(paragraph: &ParagraphText, rendered: &str) -> Vec<(usize, usize)> {
    if rendered.is_empty() {
        return Vec::new();
    }
    let length = rendered.chars().count();
    paragraph
        .text
        .char_indices()
        .enumerate()
        .filter_map(|(start, (byte, _))| {
            if !paragraph.text[byte..].starts_with(rendered) {
                return None;
            }
            let end = start + length;
            (boundary_ok(&paragraph.text, start, end)
                && !paragraph
                    .field_spans
                    .iter()
                    .any(|(low, high)| *low < end && start < *high))
            .then_some((start, end))
        })
        .collect()
}
pub fn find_candidates(
    paragraphs: &[ParagraphText],
    row: &[(String, Option<String>)],
) -> Vec<Candidate> {
    let mut out = Vec::new();
    for (column, value) in row {
        let Some(value) = value.as_ref().filter(|value| !value.is_empty()) else {
            continue;
        };
        let programs = renderings(value);
        let candidates = |partial: bool| {
            programs
                .iter()
                .filter(|(spec, _)| spec.partial == partial)
                .flat_map(|(spec, rendered)| {
                    paragraphs
                        .iter()
                        .enumerate()
                        .flat_map(move |(paragraph_at, paragraph)| {
                            occurrences(paragraph, rendered)
                                .into_iter()
                                .map(move |(start, end)| Candidate {
                                    column: column.clone(),
                                    transform: spec.id,
                                    rendered: rendered.clone(),
                                    paragraph: paragraph_at,
                                    start,
                                    end,
                                })
                        })
                })
                .collect::<Vec<_>>()
        };
        let whole = candidates(false);
        out.extend(if whole.is_empty() {
            candidates(true)
        } else {
            whole
        });
    }
    out
}
pub fn mask(candidates: &[Candidate]) -> Vec<Slot> {
    let mut by_span: BTreeMap<(usize, usize, usize), Vec<Candidate>> = BTreeMap::new();
    for candidate in candidates {
        by_span
            .entry((candidate.paragraph, candidate.start, candidate.end))
            .or_default()
            .push(candidate.clone());
    }
    let mut keys: Vec<_> = by_span.keys().copied().collect();
    keys.sort_by_key(|(paragraph, start, end)| {
        (std::cmp::Reverse(end - start), *paragraph, *start)
    });
    let mut kept = Vec::new();
    for (paragraph, start, end) in keys {
        if kept
            .iter()
            .any(|slot: &Slot| slot.paragraph == paragraph && start < slot.end && slot.start < end)
        {
            continue;
        }
        kept.push(Slot {
            paragraph,
            start,
            end,
            candidates: by_span.remove(&(paragraph, start, end)).unwrap_or_default(),
        });
    }
    kept.sort_by_key(|slot| (slot.paragraph, slot.start));
    kept
}
pub fn specificity(rendered: &str) -> f64 {
    let core = python_trim(rendered);
    let digits = core.chars().filter(|ch| ch.is_numeric()).count();
    if digits > 0 && core.chars().all(|ch| ch.is_numeric() || ",.-".contains(ch)) {
        return ((digits as f64 - 1.0) / 5.0).clamp(0.0, 1.0);
    }
    if digits > 0 && core.chars().any(|ch| ('가'..='힣').contains(&ch)) {
        return 1.0;
    }
    (core.chars().count() as f64 / 4.0).clamp(0.0, 1.0)
}
pub fn found_columns(paragraphs: &[ParagraphText], row: &[(String, Option<String>)]) -> usize {
    row.iter()
        .filter(|(_, value)| value.as_ref().is_some_and(|value| !value.is_empty()))
        .filter(|(_, value)| {
            renderings(value.as_deref().unwrap_or_default())
                .iter()
                .any(|(_, rendered)| {
                    paragraphs
                        .iter()
                        .any(|paragraph| !occurrences(paragraph, rendered).is_empty())
                })
        })
        .count()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::collections::{HashMap, HashSet};

    fn doc(lines: &[&str]) -> Vec<ParagraphText> {
        lines
            .iter()
            .enumerate()
            .map(|(index, text)| ParagraphText {
                key: format!("p{index}"),
                text: (*text).into(),
                editable_end: text.chars().count() + 1,
                field_spans: Vec::new(),
                cell: None,
            })
            .collect()
    }
    fn row(items: &[(&str, Option<&str>)]) -> Vec<(String, Option<String>)> {
        items
            .iter()
            .map(|(name, value)| ((*name).into(), value.map(str::to_owned)))
            .collect()
    }
    fn rendered(value: &str) -> HashMap<&'static str, String> {
        renderings(value)
            .into_iter()
            .map(|(spec, text)| (spec.id, text))
            .collect()
    }

    #[test]
    fn programs_keep_only_product_equivalent_unambiguous_values() {
        assert_eq!(
            rendered("00123").keys().copied().collect::<HashSet<_>>(),
            HashSet::from(["identity"])
        );
        assert!(!rendered("2026-01-05").contains_key("date_iso"));
        assert!(!rendered("2026/09/15").contains_key("date_slash"));
        let date = rendered("2026/09/11 10:00:00");
        assert_eq!(date["datetime_dot_spaced"], "2026. 9. 11. 10:00");
        assert_eq!(date["datetime_korean"], "2026년 9월 11일 10:00");
        assert!(!date.contains_key("date_korean"));
        assert!(!date.contains_key("date_dot_spaced"));
        assert_eq!(
            rendered("170309180"),
            HashMap::from([
                ("identity", "170309180".into()),
                ("number_grouping", "170,309,180".into())
            ])
        );
        assert_eq!(rendered("-1234.5")["number_grouping"], "-1,234.5");
        assert!(!rendered("-1234.50").contains_key("number_grouping"));
        assert_eq!(rendered("물품내역서 참조").len(), 1);
        assert!(renderings("   ").is_empty());
        assert!(!rendered("2026-13-40").contains_key("date_iso"));
        assert!(!rendered("2026-02-30 10:00").contains_key("datetime_iso"));
        assert!(!rendered("내일").contains_key("date_korean"));
        assert_eq!(
            transform("date_dot_ym").unwrap().binding(),
            json!({"type":"date","fmt":"ym","label":"표준(연·월)"})
        );
        assert!(transform("date_dot_ym").unwrap().partial);
        assert!(!transform("date_dot").unwrap().partial);
        assert_eq!(rendered("2026/10/12 09:00:00")["date_dot_ym"], "2026. 10.");
        for value in ["2026-09-05", "2026-09-05 08:07", "1234567", "12.5", "육군"] {
            for (spec, text) in renderings(value) {
                assert_eq!(
                    product_render(spec.kind, spec.fmt, value),
                    text,
                    "{}",
                    spec.id
                );
            }
        }
        assert_eq!(transform("identity").unwrap().binding()["label"], "");
        assert_eq!(
            transform("number_grouping").unwrap().binding(),
            json!({"type":"amount","fmt":"{:,}","label":"숫자"})
        );
        assert_eq!(
            transform("date_slash").unwrap().binding()["label"],
            "%Y/%m/%d"
        );
        assert_eq!(
            transform("datetime_korean").unwrap().binding()["label"],
            "한글(시간 포함)"
        );
    }

    #[test]
    fn candidate_boundaries_exclude_fragments_and_preserve_longest_editable_spans() {
        assert!(
            find_candidates(&doc(&["금액 2026000원"]), &row(&[("year", Some("2026"))])).is_empty()
        );
        assert!(
            find_candidates(&doc(&["금액 2,026,000원"]), &row(&[("year", Some("2026"))]))
                .is_empty()
        );
        assert!(
            !find_candidates(&doc(&["2026년도 예산"]), &row(&[("year", Some("2026"))])).is_empty()
        );
        for (text, start, end) in [
            ("abc12345", 3, 5),
            ("INV-12a", 4, 6),
            ("xAB", 1, 3),
            ("AB9", 0, 2),
            ("1.25", 2, 4),
            ("25,1", 0, 2),
        ] {
            assert!(!boundary_ok(text, start, end), "{text}");
        }
        assert!(boundary_ok("한국상사귀하", 0, 4));
        assert!(
            find_candidates(
                &doc(&["메모: "]),
                &row(&[("memo", Some("")), ("none", None)])
            )
            .is_empty()
        );
        let mut protected = doc(&["수요기관: 조달청"]);
        protected[0].field_spans = vec![(6, 9)];
        assert!(find_candidates(&protected, &row(&[("agency", Some("조달청"))])).is_empty());
        let candidates = find_candidates(
            &doc(&["기간 2026-09-15 까지"]),
            &row(&[
                ("d", Some("2026-09-15")),
                ("y", Some("2026")),
                ("same", Some("2026-09-15")),
            ]),
        );
        let slots = mask(&candidates);
        assert_eq!(
            slots
                .iter()
                .map(|slot| (slot.start, slot.end))
                .collect::<Vec<_>>(),
            vec![(3, 13)]
        );
        assert_eq!(
            slots[0]
                .candidates
                .iter()
                .map(|candidate| candidate.column.as_str())
                .collect::<HashSet<_>>(),
            HashSet::from(["d", "same"])
        );
        assert_eq!(specificity("3"), 0.0);
        assert_eq!(specificity("2026년 9월 30일"), 1.0);
        assert_eq!(specificity("12"), 0.2);
        assert_eq!(
            found_columns(
                &doc(&["수요기관: 조달청", "금액 1,000원"]),
                &row(&[
                    ("a", Some("조달청")),
                    ("b", Some("1000")),
                    ("c", Some("없는 값")),
                    ("d", None)
                ])
            ),
            2
        );
        let partial = find_candidates(
            &doc(&["2026. 10.", "개찰일시: 2026. 10. 21. 11:00"]),
            &row(&[
                ("게시일시", Some("2026-10-12 09:00")),
                ("개찰일시", Some("2026-10-21 11:00")),
            ]),
        );
        assert!(
            partial
                .iter()
                .any(|item| item.column == "게시일시" && item.transform == "date_dot_ym")
        );
        assert!(
            !partial
                .iter()
                .any(|item| item.column == "개찰일시" && item.transform == "date_dot_ym")
        );
        assert!(!boundary_ok("2026. 10. 19. 10:00", 6, 8));
        assert!(boundary_ok("2026. 10. 19. 10:00", 14, 19));
    }
}
