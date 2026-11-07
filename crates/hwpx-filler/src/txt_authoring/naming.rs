//! Field-name suggestion from the label text written before a selection.

use super::{chars, normalized_field};
use crate::fields::python_whitespace;
use crate::structure_scan::python_trim;
use regex::Regex;
use serde_json::json;
use std::sync::LazyLock;

static ENUMERATOR: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:[가-힣]\.|\d+[.)]|\(\d+\)|\([가-힣]\)|[①-⑳㉠-㉻]|[□■○●◦▪▫◆◇▶►※\-•·*])\s*")
        .unwrap()
});

/// The text before the label colon, or `None` when the selection follows no label.
fn label_prefix(before: &str) -> Option<&str> {
    let prefix = before.trim_end_matches(python_whitespace);
    if !prefix.ends_with([':', '：']) {
        return None;
    }
    Some(&prefix[..prefix.len() - prefix.chars().last()?.len_utf8()])
}
/// The last label segment, after any earlier colon, tab, or field token.
fn label_segment(prefix: &str) -> &str {
    let mut at = 0;
    for (index, ch) in prefix.char_indices() {
        if matches!(ch, ':' | '：' | '\t') {
            at = index + ch.len_utf8();
        }
    }
    if let Some(index) = prefix.rfind("}}") {
        at = at.max(index + 2);
    }
    &prefix[at..]
}
/// A label spelled as spaced single Hangul letters, such as "성 명".
fn spaced_hangul_label(segment: &str) -> Option<String> {
    let tokens = segment
        .split(python_whitespace)
        .filter(|token| !token.is_empty())
        .collect::<Vec<_>>();
    let run = tokens
        .iter()
        .rev()
        .take_while(|token| {
            token.chars().count() == 1
                && token
                    .chars()
                    .next()
                    .is_some_and(|ch| ('가'..='힣').contains(&ch))
        })
        .count();
    (run >= 2).then(|| tokens[tokens.len() - run..].concat())
}
fn strip_enumerators(mut label: String) -> String {
    loop {
        let next = ENUMERATOR.replace(&label, "").into_owned();
        if next == label {
            return label;
        }
        label = next;
    }
}
/// The words after the last run of two or more spaces, without enumerators.
fn last_gap_label(segment: &str) -> String {
    let letters = segment
        .trim_matches(python_whitespace)
        .chars()
        .collect::<Vec<_>>();
    let mut gap = 0;
    let mut previous = false;
    for (index, ch) in letters.iter().enumerate() {
        if python_whitespace(*ch) {
            if previous {
                gap = index + 1;
            }
        } else {
            previous = false;
            continue;
        }
        previous = true;
    }
    strip_enumerators(letters[gap..].iter().collect::<String>())
        .split(python_whitespace)
        .filter(|token| !token.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
pub fn suggest_field_name(before: &str, selected: &str, existing: &[String]) -> Option<String> {
    if python_trim(selected).is_empty()
        || selected.contains("{{")
        || selected.contains("}}")
        || selected.contains(['\n', '\r'])
    {
        return None;
    }
    let segment = label_segment(label_prefix(before)?);
    let label = spaced_hangul_label(segment).unwrap_or_else(|| last_gap_label(segment));
    if label.is_empty() || chars(&label) > 20 {
        return None;
    }
    let label = normalized_field(Some(&json!(label))).ok()?;
    let compact = label.split(python_whitespace).collect::<String>();
    existing
        .iter()
        .find(|item| item.split(python_whitespace).collect::<String>() == compact)
        .cloned()
        .or(Some(label))
}
