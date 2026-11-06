//! Field-set drift with Python SequenceMatcher-compatible rename scoring.

use crate::fields::python_whitespace;
use crate::schema::{SchemaError, extract_schema};
use hwpx_core::package::HwpxPackage;
use serde::Serialize;
use std::collections::{HashMap, HashSet};

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Rename {
    pub old: String,
    pub new: String,
    pub score: f64,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize)]
pub struct SchemaDrift {
    pub added: Vec<String>,
    pub removed: Vec<String>,
    pub renamed: Vec<Rename>,
}

impl SchemaDrift {
    pub fn has_changes(&self) -> bool {
        !self.added.is_empty() || !self.removed.is_empty() || !self.renamed.is_empty()
    }
}

fn longest_match(
    a: &[char],
    b: &[char],
    b2j: &HashMap<char, Vec<usize>>,
    alo: usize,
    ahi: usize,
    blo: usize,
    bhi: usize,
) -> (usize, usize, usize) {
    let (mut best_i, mut best_j, mut best_size) = (alo, blo, 0);
    let mut prev = HashMap::<usize, usize>::new();
    for (i, ch) in a.iter().enumerate().take(ahi).skip(alo) {
        let mut next = HashMap::new();
        if let Some(indices) = b2j.get(ch) {
            for &j in indices {
                if j < blo {
                    continue;
                }
                if j >= bhi {
                    break;
                }
                let size = prev.get(&j.wrapping_sub(1)).copied().unwrap_or(0) + 1;
                next.insert(j, size);
                if size > best_size {
                    best_i = i + 1 - size;
                    best_j = j + 1 - size;
                    best_size = size;
                }
            }
        }
        prev = next;
    }
    // With no explicit junk predicate, popular characters may still extend a match.
    while best_i > alo && best_j > blo && a[best_i - 1] == b[best_j - 1] {
        best_i -= 1;
        best_j -= 1;
        best_size += 1;
    }
    while best_i + best_size < ahi
        && best_j + best_size < bhi
        && a[best_i + best_size] == b[best_j + best_size]
    {
        best_size += 1;
    }
    (best_i, best_j, best_size)
}

fn matching_size(a: &[char], b: &[char]) -> usize {
    let mut b2j = HashMap::<char, Vec<usize>>::new();
    for (at, ch) in b.iter().enumerate() {
        b2j.entry(*ch).or_default().push(at);
    }
    if b.len() >= 200 {
        let threshold = b.len() / 100 + 1;
        b2j.retain(|_, positions| positions.len() <= threshold);
    }
    let mut queue = vec![(0, a.len(), 0, b.len())];
    let mut matches = Vec::new();
    while let Some((alo, ahi, blo, bhi)) = queue.pop() {
        let (i, j, size) = longest_match(a, b, &b2j, alo, ahi, blo, bhi);
        if size == 0 {
            continue;
        }
        matches.push((i, j, size));
        if alo < i && blo < j {
            queue.push((alo, i, blo, j));
        }
        if i + size < ahi && j + size < bhi {
            queue.push((i + size, ahi, j + size, bhi));
        }
    }
    matches.iter().map(|(_, _, size)| *size).sum()
}

pub fn similarity(a: &str, b: &str) -> f64 {
    let a: Vec<char> = a.chars().filter(|ch| !python_whitespace(*ch)).collect();
    let b: Vec<char> = b.chars().filter(|ch| !python_whitespace(*ch)).collect();
    if a == b {
        return 1.0;
    }
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let matched = matching_size(&a, &b);
    2.0 * matched as f64 / (a.len() + b.len()) as f64
}

pub fn diff_names(old_names: &[String], new_names: &[String], threshold: f64) -> SchemaDrift {
    let old_set: HashSet<_> = old_names.iter().collect();
    let new_set: HashSet<_> = new_names.iter().collect();
    let added: Vec<_> = new_names
        .iter()
        .filter(|name| !old_set.contains(name))
        .cloned()
        .collect();
    let removed: Vec<_> = old_names
        .iter()
        .filter(|name| !new_set.contains(name))
        .cloned()
        .collect();
    let mut used_new = HashSet::new();
    let mut renamed = Vec::new();
    for old in &removed {
        let (mut best, mut best_score) = (None, 0.0);
        for new in &added {
            if used_new.contains(new) {
                continue;
            }
            let score = similarity(old, new);
            if score > best_score {
                best = Some(new);
                best_score = score;
            }
        }
        if let Some(new) = best.filter(|_| best_score >= threshold) {
            renamed.push(Rename {
                old: old.clone(),
                new: new.clone(),
                score: format!("{best_score:.3}")
                    .parse()
                    .expect("formatted finite ratio"),
            });
            used_new.insert(new.clone());
        }
    }
    let renamed_old: HashSet<_> = renamed.iter().map(|item| &item.old).collect();
    SchemaDrift {
        added: added
            .into_iter()
            .filter(|name| !used_new.contains(name))
            .collect(),
        removed: removed
            .into_iter()
            .filter(|name| !renamed_old.contains(name))
            .collect(),
        renamed,
    }
}

pub fn diff_schema(old: &HwpxPackage, new: &HwpxPackage) -> Result<SchemaDrift, SchemaError> {
    let old_names = extract_schema(old)?.field_names();
    let new_names = extract_schema(new)?.field_names();
    Ok(diff_names(&old_names, &new_names, 0.8))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn drift_keeps_order_and_prefers_first_equal_score_rename() {
        let old = vec!["계약명".into(), "공고명".into(), "사업예산".into()];
        let new = vec!["계약명".into(), "공고 명".into(), "부서".into()];
        let drift = diff_names(&old, &new, 0.8);
        assert_eq!(drift.added, ["부서"]);
        assert_eq!(drift.removed, ["사업예산"]);
        assert_eq!(
            drift.renamed,
            [Rename {
                old: "공고명".into(),
                new: "공고 명".into(),
                score: 1.0
            }]
        );
        assert!(drift.has_changes());
        let package = |names: &[String]| {
            HwpxPackage {
            entries: vec![hwpx_core::package::PackageEntry {
                name: "Contents/section0.xml".into(),
                data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='http://www.hancom.co.kr/hwpml/2011/paragraph'>{}</hs:sec>", names.iter().map(|name| format!("<hp:p><hp:run><hp:ctrl><hp:fieldBegin name='{name}'/><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>")).collect::<String>()).into_bytes(),
                stored: false,
            }],
        }
        };
        assert_eq!(diff_schema(&package(&old), &package(&new)).unwrap(), drift);
        assert!(
            !diff_schema(&package(&old), &package(&old))
                .unwrap()
                .has_changes()
        );
        let replaced =
            diff_schema(&package(&["사업예산".into()]), &package(&["공고명".into()])).unwrap();
        assert_eq!(replaced.added, ["공고명"]);
        assert_eq!(replaced.removed, ["사업예산"]);
        assert!(replaced.renamed.is_empty());
        assert_eq!(similarity("입찰개시일시", "입찰마감일시"), 2.0 * 4.0 / 12.0);
        let old_tie = format!("{}{}", "A".repeat(65), "B".repeat(15));
        let new_tie = format!("{}{}", "A".repeat(65), "C".repeat(15));
        assert_eq!(
            diff_names(&[old_tie], &[new_tie], 0.8).renamed[0].score,
            0.812
        );
    }

    #[test]
    fn normalized_unicode_whitespace_and_popular_characters_match_python_rules() {
        assert_eq!(similarity("A\u{001c}B", "AB"), 1.0);
        assert_eq!(
            similarity("가".repeat(200).as_str(), "가".repeat(199).as_str()),
            398.0 / 399.0
        );
        assert!(
            diff_names(&["A".into()], &["B".into()], 0.8)
                .renamed
                .is_empty()
        );
    }
}
