//! Conservative mark projection across temporary TXT card edits.

use crate::structure_scan::python_trim;
use crate::text_render::{SEG_BLANK, SEG_MISSING};
use std::collections::{HashMap, HashSet};

pub const MARK_DECLARED: &str = "declared";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CardMark {
    pub kind: String,
    pub name: String,
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EditTag {
    Equal,
    Replace,
    Delete,
    Insert,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EditOp {
    pub tag: EditTag,
    pub i1: usize,
    pub i2: usize,
    pub j1: usize,
    pub j2: usize,
}

fn longest_match(
    a: &[char],
    b: &[char],
    alo: usize,
    ahi: usize,
    blo: usize,
    bhi: usize,
) -> (usize, usize, usize) {
    let mut b2j: HashMap<char, Vec<usize>> = HashMap::new();
    for (j, ch) in b.iter().enumerate().take(bhi).skip(blo) {
        b2j.entry(*ch).or_default().push(j);
    }
    let (mut best_i, mut best_j, mut best_size) = (alo, blo, 0);
    let mut previous = HashMap::<usize, usize>::new();
    for (i, ch) in a.iter().enumerate().take(ahi).skip(alo) {
        let mut next = HashMap::new();
        if let Some(indices) = b2j.get(ch) {
            for &j in indices {
                let size = previous.get(&j.wrapping_sub(1)).copied().unwrap_or(0) + 1;
                next.insert(j, size);
                if size > best_size {
                    (best_i, best_j, best_size) = (i + 1 - size, j + 1 - size, size);
                }
            }
        }
        previous = next;
    }
    // Every character is indexed; no excluded junk/popular characters can extend this maximum.
    (best_i, best_j, best_size)
}
fn matching_blocks(a: &[char], b: &[char]) -> Vec<(usize, usize, usize)> {
    let mut queue = vec![(0, a.len(), 0, b.len())];
    let mut blocks = Vec::new();
    while let Some((alo, ahi, blo, bhi)) = queue.pop() {
        let (i, j, n) = longest_match(a, b, alo, ahi, blo, bhi);
        if n == 0 {
            continue;
        }
        blocks.push((i, j, n));
        if alo < i && blo < j {
            queue.push((alo, i, blo, j));
        }
        if i + n < ahi && j + n < bhi {
            queue.push((i + n, ahi, j + n, bhi));
        }
    }
    blocks.sort_unstable();
    blocks
}
fn merge_matching_blocks(blocks: Vec<(usize, usize, usize)>) -> Vec<(usize, usize, usize)> {
    let mut merged: Vec<(usize, usize, usize)> = Vec::new();
    for (i, j, n) in blocks {
        if let Some(last) = merged.last_mut()
            && last.0 + last.2 == i
            && last.1 + last.2 == j
        {
            last.2 += n;
            continue;
        }
        merged.push((i, j, n));
    }
    merged
}
fn opcodes(a: &[char], b: &[char]) -> Vec<EditOp> {
    let mut merged = merge_matching_blocks(matching_blocks(a, b));
    merged.push((a.len(), b.len(), 0));
    let (mut ai, mut bj) = (0, 0);
    let mut result = Vec::new();
    for (i, j, n) in merged {
        if ai < i || bj < j {
            let tag = match (ai < i, bj < j) {
                (true, true) => EditTag::Replace,
                (true, false) => EditTag::Delete,
                (false, true) => EditTag::Insert,
                (false, false) => unreachable!(),
            };
            result.push(EditOp {
                tag,
                i1: ai,
                i2: i,
                j1: bj,
                j2: j,
            });
        }
        if n > 0 {
            result.push(EditOp {
                tag: EditTag::Equal,
                i1: i,
                i2: i + n,
                j1: j,
                j2: j + n,
            });
        }
        ai = i + n;
        bj = j + n;
    }
    if result.is_empty() {
        result.push(EditOp {
            tag: EditTag::Equal,
            i1: 0,
            i2: 0,
            j1: 0,
            j2: 0,
        });
    }
    result
}
fn cost(ops: &[EditOp]) -> usize {
    ops.iter()
        .filter(|op| op.tag != EditTag::Equal)
        .map(|op| (op.i2 - op.i1).max(op.j2 - op.j1))
        .sum()
}
pub fn alignment(base: &str, edited: &str) -> Vec<EditOp> {
    let a = base.chars().collect::<Vec<_>>();
    let b = edited.chars().collect::<Vec<_>>();
    let forward = opcodes(&a, &b);
    let reversed = opcodes(
        &a.iter().rev().copied().collect::<Vec<_>>(),
        &b.iter().rev().copied().collect::<Vec<_>>(),
    );
    let backward = reversed
        .into_iter()
        .rev()
        .map(|op| EditOp {
            tag: op.tag,
            i1: a.len() - op.i2,
            i2: a.len() - op.i1,
            j1: b.len() - op.j2,
            j2: b.len() - op.j1,
        })
        .collect::<Vec<_>>();
    if cost(&backward) < cost(&forward) {
        backward
    } else {
        forward
    }
}
fn chars(text: &str) -> Vec<char> {
    text.chars().collect()
}
fn piece(text: &[char], start: usize, end: usize) -> String {
    text[start..end].iter().collect()
}
fn left(pos: usize, ops: &[EditOp]) -> usize {
    for op in ops {
        if op.i2 > pos || op.i1 == pos {
            return if op.tag == EditTag::Equal && op.i1 < pos {
                op.j1 + pos - op.i1
            } else {
                op.j1
            };
        }
    }
    ops.last().map_or(0, |op| op.j2)
}
fn right(pos: usize, ops: &[EditOp]) -> usize {
    for op in ops.iter().rev() {
        if op.i1 < pos || op.i2 == pos {
            return if op.tag == EditTag::Equal && op.i2 > pos {
                op.j1 + pos - op.i1
            } else {
                op.j2
            };
        }
    }
    ops.first().map_or(0, |op| op.j1)
}
fn inward(mark: &CardMark, ops: &[EditOp]) -> CardMark {
    let start = right(mark.start, ops);
    CardMark {
        start,
        end: start.max(left(mark.end, ops)),
        ..mark.clone()
    }
}
fn outward(mark: &CardMark, ops: &[EditOp]) -> CardMark {
    let start = left(mark.start, ops);
    CardMark {
        start,
        end: start.max(right(mark.end, ops)),
        ..mark.clone()
    }
}
fn ambiguous_insert(
    mark: &CardMark,
    others: &[CardMark],
    base: &[char],
    pos: usize,
    text: &[char],
) -> bool {
    if others
        .iter()
        .any(|other| other.start <= pos && pos <= other.end)
    {
        return true;
    }
    if pos == mark.start && pos > 0 && base[pos - 1] == *text.last().unwrap_or(&'\0') {
        return true;
    }
    pos == mark.end && pos < base.len() && base[pos] == *text.first().unwrap_or(&'\0')
}
fn attributable(
    mark: &CardMark,
    others: &[CardMark],
    ops: &[EditOp],
    base: &[char],
    edited: &[char],
) -> bool {
    for op in ops {
        if op.tag == EditTag::Equal {
            continue;
        }
        if [mark.start, mark.end]
            .into_iter()
            .any(|pos| op.i1 < pos && pos < op.i2)
        {
            return false;
        }
        if op.i1 == op.i2
            && (op.i1 == mark.start || op.i1 == mark.end)
            && ambiguous_insert(mark, others, base, op.i1, &edited[op.j1..op.j2])
        {
            return false;
        }
    }
    true
}
pub fn map_marks(base: &str, marks: &[CardMark], edited: &str) -> (Vec<CardMark>, HashSet<String>) {
    let ops = alignment(base, edited);
    let a = chars(base);
    let b = chars(edited);
    let mut mapped = Vec::new();
    let mut unfilled = HashSet::new();
    for (index, mark) in marks.iter().enumerate() {
        let is_hole = mark.kind == SEG_BLANK || mark.kind == MARK_DECLARED;
        let moved = if is_hole {
            let wide = outward(mark, &ops);
            let others = marks
                .iter()
                .enumerate()
                .filter(|(at, _)| *at != index)
                .map(|(_, item)| item.clone())
                .collect::<Vec<_>>();
            let filled = !python_trim(&piece(&b, wide.start, wide.end)).is_empty()
                && attributable(mark, &others, &ops, &a, &b);
            if filled {
                wide
            } else {
                unfilled.insert(mark.name.clone());
                inward(mark, &ops)
            }
        } else if mark.kind == SEG_MISSING {
            inward(mark, &ops)
        } else {
            outward(mark, &ops)
        };
        mapped.push(moved);
    }
    let filled = marks
        .iter()
        .filter(|mark| mark.kind == SEG_BLANK || mark.kind == MARK_DECLARED)
        .map(|mark| mark.name.clone())
        .filter(|name| !unfilled.contains(name))
        .collect();
    (mapped, filled)
}
pub fn resolved_names(base: &str, marks: &[CardMark], edited: &str) -> HashSet<String> {
    let a = chars(base);
    let mut counts = HashMap::<(String, String), usize>::new();
    for mark in marks.iter().filter(|mark| mark.kind == SEG_MISSING) {
        *counts
            .entry((mark.name.clone(), piece(&a, mark.start, mark.end)))
            .or_default() += 1;
    }
    let mut kept = HashSet::new();
    let count = |haystack: &str, needle: &str| {
        if needle.is_empty() {
            0
        } else {
            haystack.match_indices(needle).count()
        }
    };
    for ((name, token), n) in &counts {
        if count(edited, token) > count(base, token).saturating_sub(*n) {
            kept.insert(name.clone());
        }
    }
    counts
        .keys()
        .map(|(name, _)| name.clone())
        .filter(|name| !kept.contains(name))
        .collect()
}
pub fn plain_edit(shown: &str, plain: &str, edited: &str) -> String {
    let s = chars(shown);
    let p = chars(plain);
    let e = chars(edited);
    let mut offsets = Vec::with_capacity(s.len() + 1);
    let mut at = 0;
    for ch in &s {
        offsets.push(at);
        at += if p.get(at) == Some(ch) { 1 } else { 2 };
    }
    offsets.push(at);
    if at != p.len() {
        return edited.into();
    }
    alignment(shown, edited)
        .into_iter()
        .map(|op| {
            if op.tag == EditTag::Equal {
                piece(&p, offsets[op.i1], offsets[op.i2])
            } else {
                piece(&e, op.j1, op.j2)
            }
        })
        .collect()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::{EditTag, alignment};
    use serde_json::{Value, json};
    #[test]
    fn alignment_matches_python_including_empty_repeated_and_non_bmp_text() {
        let cases: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/txt_card_edit.json"))
                .unwrap();
        for row in cases["alignment"].as_array().unwrap() {
            let base = row["args"][0].as_str().unwrap();
            let edited = row["args"][1].as_str().unwrap();
            let actual = alignment(base, edited)
                .into_iter()
                .map(|op| {
                    json!([
                        match op.tag {
                            EditTag::Equal => "equal",
                            EditTag::Replace => "replace",
                            EditTag::Delete => "delete",
                            EditTag::Insert => "insert",
                        },
                        op.i1,
                        op.i2,
                        op.j1,
                        op.j2,
                    ])
                })
                .collect::<Vec<_>>();
            assert_eq!(json!(actual), row["expected"], "{base:?} -> {edited:?}");
        }
    }
}
