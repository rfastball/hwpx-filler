//! Temporary per-row card edits, marks, and UTF-16 editor coordinates.

use crate::text_render::{
    RenderSegment, SEG_BLANK, SEG_LITERAL, align_fullwidth, has_space_run, render_segments,
};
use crate::txt_card::{CardRender, card_text};
use crate::txt_card_diff::{
    CardMark, EditTag, MARK_DECLARED, alignment, map_marks, resolved_names,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EditedCard {
    pub text: String,
    pub marks: Vec<CardMark>,
    pub filled: HashSet<String>,
    pub resolved: HashSet<String>,
    pub space_run: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CardView {
    pub text: String,
    pub base: String,
    pub marks: Vec<CardMark>,
    pub missing_fields: Vec<String>,
    pub empty_fields: Vec<String>,
    pub space_run: bool,
    pub plain: String,
    pub plain_base: String,
}
pub fn base_marks(segments: &[RenderSegment], declared: &HashSet<String>) -> Vec<CardMark> {
    let mut marks = Vec::new();
    let mut pos = 0;
    for segment in segments {
        let length = segment.text.chars().count();
        if segment.kind != SEG_LITERAL {
            let kind = if segment.kind == SEG_BLANK && declared.contains(&segment.name) {
                MARK_DECLARED
            } else {
                segment.kind
            };
            marks.push(CardMark {
                kind: kind.into(),
                name: segment.name.clone(),
                start: pos,
                end: pos + length,
            });
        }
        pos += length;
    }
    marks
}
fn slice(chars: &[char], start: usize, end: usize) -> String {
    if start >= end {
        String::new()
    } else {
        chars[start..end].iter().collect()
    }
}
fn align_outside(text: &str, marks: &[CardMark]) -> (String, Vec<CardMark>) {
    let source = text.chars().collect::<Vec<_>>();
    let mut sorted = marks.to_vec();
    sorted.sort_by_key(|mark| (mark.start, mark.end));
    let mut out = String::new();
    let mut moved = Vec::new();
    let mut cursor = 0;
    for mark in sorted {
        let start = mark.start.max(cursor);
        out.push_str(&align_fullwidth(&slice(&source, cursor, start)));
        let new_start = out.chars().count();
        out.push_str(&slice(&source, start, mark.end));
        moved.push(CardMark {
            start: new_start,
            end: new_start + mark.end.saturating_sub(start),
            ..mark.clone()
        });
        cursor = cursor.max(mark.end);
    }
    out.push_str(&align_fullwidth(&slice(&source, cursor, source.len())));
    (out, moved)
}
fn outside_has_space_run(text: &str, marks: &[CardMark]) -> bool {
    let source = text.chars().collect::<Vec<_>>();
    let mut sorted = marks.to_vec();
    sorted.sort_by_key(|mark| mark.start);
    let mut cursor = 0;
    for mark in sorted {
        if has_space_run(&slice(&source, cursor, mark.start)) {
            return true;
        }
        cursor = cursor.max(mark.end);
    }
    has_space_run(&slice(&source, cursor, source.len()))
}
pub fn edit_card(base: &str, marks: &[CardMark], edited: &str, fullwidth: bool) -> EditedCard {
    let (mapped, filled) = map_marks(base, marks, edited);
    let space_run = outside_has_space_run(edited, &mapped);
    let (text, shown) = if fullwidth {
        align_outside(edited, &mapped)
    } else {
        (edited.into(), mapped)
    };
    EditedCard {
        text,
        marks: shown,
        filled,
        resolved: resolved_names(base, marks, edited),
        space_run,
    }
}
pub fn card_view(
    rendered: &CardRender,
    declared: &HashSet<String>,
    gate_empty: &[String],
    edit: Option<&str>,
    fullwidth: bool,
) -> CardView {
    assert!(!rendered.fullwidth);
    let plain = card_text(&rendered.segments);
    let marks = base_marks(&rendered.segments, declared);
    let (base, base_shown) = if fullwidth {
        align_outside(&plain, &marks)
    } else {
        (plain.clone(), marks.clone())
    };
    let missing = rendered.report.missing_fields.clone();
    let Some(edit) = edit else {
        return CardView {
            text: base.clone(),
            base,
            marks: base_shown,
            missing_fields: missing,
            empty_fields: gate_empty.to_vec(),
            space_run: rendered.space_run,
            plain: plain.clone(),
            plain_base: plain,
        };
    };
    let edited = edit_card(&plain, &marks, edit, fullwidth);
    CardView {
        text: edited.text,
        base,
        marks: edited.marks,
        missing_fields: missing
            .into_iter()
            .filter(|name| !edited.resolved.contains(name))
            .collect(),
        empty_fields: gate_empty
            .iter()
            .filter(|name| !edited.filled.contains(*name))
            .cloned()
            .collect(),
        space_run: edited.space_run,
        plain: edit.into(),
        plain_base: plain,
    }
}
pub fn raw_card(template: &str) -> (String, Vec<CardMark>) {
    let (segments, _) = render_segments(template, &HashMap::new());
    (card_text(&segments), base_marks(&segments, &HashSet::new()))
}
pub fn line_break(text: &str) -> &'static str {
    let bytes = text.as_bytes();
    for (i, byte) in bytes.iter().enumerate() {
        if *byte == b'\r' {
            return if bytes.get(i + 1) == Some(&b'\n') {
                "\r\n"
            } else {
                "\r"
            };
        }
        if *byte == b'\n' {
            return "\n";
        }
    }
    "\n"
}
fn normalize_newlines(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}
pub fn editor_card(text: &str, marks: &[CardMark]) -> (String, Vec<Value>) {
    let source = text.chars().collect::<Vec<_>>();
    let mut offsets = Vec::with_capacity(source.len() + 1);
    let mut pos = 0;
    for (i, ch) in source.iter().enumerate() {
        offsets.push(pos);
        if *ch == '\n' && i > 0 && source[i - 1] == '\r' {
            continue;
        }
        pos += ch.len_utf16();
    }
    offsets.push(pos);
    (
        normalize_newlines(text),
        marks
            .iter()
            .map(|mark| {
                json!({"kind":mark.kind,"name":mark.name,
        "start":offsets[mark.start],"end":offsets[mark.end]})
            })
            .collect(),
    )
}
pub fn source_text(source: &str, edited: &str, eol: &str) -> String {
    let normalized = normalize_newlines(source);
    let edited = normalize_newlines(edited);
    let mut starts = Vec::new();
    let mut iter = source.char_indices().peekable();
    while let Some((at, ch)) = iter.next() {
        starts.push(at);
        if ch == '\r' && iter.peek().is_some_and(|(_, next)| *next == '\n') {
            iter.next();
        }
    }
    starts.push(source.len());
    let typed = edited.chars().collect::<Vec<_>>();
    alignment(&normalized, &edited)
        .into_iter()
        .map(|op| {
            if op.tag == EditTag::Equal {
                source[starts[op.i1]..starts[op.i2]].to_owned()
            } else {
                slice(&typed, op.j1, op.j2).replace('\n', eol)
            }
        })
        .collect()
}

#[derive(Clone, Debug, Default)]
pub struct CardEdits {
    texts: HashMap<usize, String>,
    seen: HashMap<usize, (String, u64)>,
    generation: u64,
    pub epoch: u64,
}
impl CardEdits {
    pub fn get(&self, index: Option<usize>) -> Option<&str> {
        index.and_then(|index| self.texts.get(&index).map(String::as_str))
    }
    pub fn len(&self) -> usize {
        self.texts.len()
    }
    pub fn is_empty(&self) -> bool {
        self.texts.is_empty()
    }
    pub fn contains(&self, index: usize) -> bool {
        self.texts.contains_key(&index)
    }
    pub fn put(&mut self, index: usize, text: String, unedited: &str) {
        self.texts.remove(&index);
        if text != unedited {
            self.texts.insert(index, text);
        } else if let Some((seen, _)) = self.seen.get_mut(&index) {
            *seen = unedited.into();
        }
    }
    pub fn text_rev(&mut self, index: Option<usize>, unedited: &str) -> u64 {
        let Some(index) = index else {
            return 0;
        };
        let update = self
            .seen
            .get(&index)
            .is_none_or(|(seen, _)| !self.texts.contains_key(&index) && seen != unedited);
        if update {
            self.generation += 1;
            self.seen.insert(index, (unedited.into(), self.generation));
        }
        self.seen[&index].1
    }
    pub fn revert(&mut self, index: usize) {
        if self.texts.remove(&index).is_some() {
            self.epoch += 1;
        }
    }
    pub fn signature(&self, index: usize, rules: &str) -> String {
        let payload = format!(
            "({}, {})",
            crate::text_render::python_repr(&Value::String(rules.into())),
            self.texts.get(&index).map_or_else(
                || "None".into(),
                |text| crate::text_render::python_repr(&Value::String(text.clone()))
            )
        );
        let digest = Sha256::digest(payload.as_bytes());
        digest.iter().map(|byte| format!("{byte:02x}")).collect()
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::txt_card_diff::CardMark;
    use serde_json::json;
    #[test]
    fn adjacent_filled_marks_keep_insertions_and_separate_aligned_ranges() {
        let adjacent = [
            CardMark {
                kind: "fill".into(),
                name: "A".into(),
                start: 0,
                end: 1,
            },
            CardMark {
                kind: "fill".into(),
                name: "B".into(),
                start: 1,
                end: 2,
            },
        ];
        let plain = edit_card("AB", &adjacent, "A!B", false);
        assert_eq!(plain.text, "A!B");
        assert_eq!((plain.marks[0].start, plain.marks[0].end), (0, 2));
        assert_eq!((plain.marks[1].start, plain.marks[1].end), (1, 3));
        let aligned = edit_card("AB", &adjacent, "A!B", true);
        assert_eq!(aligned.text, "A!B");
        assert_eq!((aligned.marks[1].start, aligned.marks[1].end), (2, 3));
    }

    fn marks(value: &Value) -> Vec<CardMark> {
        value
            .as_array()
            .unwrap()
            .iter()
            .map(|item| CardMark {
                kind: item["kind"].as_str().unwrap().into(),
                name: item["name"].as_str().unwrap().into(),
                start: item["start"].as_u64().unwrap() as usize,
                end: item["end"].as_u64().unwrap() as usize,
            })
            .collect()
    }
    fn mark_json(marks: &[CardMark]) -> Value {
        json!(marks.iter().map(|item| json!({"kind":item.kind,"name":item.name,"start":item.start,"end":item.end})).collect::<Vec<_>>())
    }

    #[test]
    fn card_edit_outputs_match_python_marks_newlines_alignment_and_utf16_oracles() {
        let cases: Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/txt_card_edit.json"))
                .unwrap();
        for (method, rows) in cases.as_object().unwrap() {
            if method == "alignment" {
                continue;
            }
            for row in rows.as_array().unwrap() {
                let args = row["args"].as_array().unwrap();
                let text = |at: usize| args[at].as_str().unwrap();
                let actual = match method.as_str() {
                    "base_marks" => {
                        let segments = args[0]
                            .as_array()
                            .unwrap()
                            .iter()
                            .map(|item| RenderSegment {
                                text: item["text"].as_str().unwrap().into(),
                                name: item["name"].as_str().unwrap().into(),
                                kind: match item["kind"].as_str().unwrap() {
                                    "literal" => "literal",
                                    "blank" => "blank",
                                    "fill" => "fill",
                                    "missing" => "missing",
                                    other => panic!("{other}"),
                                },
                            })
                            .collect::<Vec<_>>();
                        let declared = args[1]
                            .as_array()
                            .unwrap()
                            .iter()
                            .map(|item| item.as_str().unwrap().to_owned())
                            .collect();
                        mark_json(&base_marks(&segments, &declared))
                    }
                    "edit_card" => {
                        let result = edit_card(
                            text(0),
                            &marks(&args[1]),
                            text(2),
                            row["kwargs"]["fullwidth"].as_bool().unwrap(),
                        );
                        json!({"text":result.text,"marks":mark_json(&result.marks),
                            "filled":result.filled.into_iter().collect::<std::collections::BTreeSet<_>>(),
                            "resolved":result.resolved.into_iter().collect::<std::collections::BTreeSet<_>>(),"space_run":result.space_run})
                    }
                    "editor_card" => {
                        let (text, marks) = editor_card(text(0), &marks(&args[1]));
                        json!([text, marks])
                    }
                    "line_break" => json!(line_break(text(0))),
                    "source_text" => json!(source_text(text(0), text(1), text(2))),
                    "raw_card" => {
                        let (text, marks) = raw_card(text(0));
                        json!([text, mark_json(&marks)])
                    }
                    "plain_edit" => {
                        json!(crate::txt_card_diff::plain_edit(text(0), text(1), text(2)))
                    }
                    other => panic!("unknown oracle: {other}"),
                };
                assert_eq!(actual, row["expected"], "{method}: {}", row["test"]);
            }
        }
    }

    #[test]
    fn edits_clear_on_echo_and_keep_per_row_signatures_revisions_and_revert_epochs() {
        let mut edits = CardEdits::default();
        assert!(edits.is_empty());
        assert_eq!(edits.get(None), None);
        edits.revert(0);
        assert_eq!(edits.epoch, 0);
        let base = edits.signature(0, "규칙-지문");
        assert_eq!(edits.signature(0, "규칙-지문"), base);
        let first = edits.text_rev(Some(0), "09:00");
        assert_eq!(edits.text_rev(Some(0), "09:00"), first);
        let second = edits.text_rev(Some(0), "09:01");
        assert_ne!(first, second);
        edits.put(0, "09:01 고침".into(), "09:01");
        assert!(edits.contains(0));
        assert_eq!(edits.len(), 1);
        assert_eq!(edits.get(Some(0)), Some("09:01 고침"));
        assert_ne!(edits.signature(0, "규칙-지문"), base);
        assert_eq!(edits.signature(1, "규칙-지문"), base);
        assert_ne!(
            edits.signature(0, "다른 규칙"),
            edits.signature(0, "규칙-지문")
        );
        assert_eq!(edits.text_rev(Some(0), "09:02"), second);
        edits.put(0, "09:02".into(), "09:02");
        assert!(!edits.contains(0));
        assert_eq!(edits.get(Some(0)), None);
        assert_eq!(edits.text_rev(Some(0), "09:02"), second);
        assert_eq!(edits.text_rev(None, "x"), 0);
        assert_eq!(edits.signature(0, "규칙-지문"), base);
        edits.put(0, "고침".into(), "원문");
        edits.put(1, "다른 행".into(), "원문");
        edits.revert(0);
        assert_eq!(edits.epoch, 1);
        assert_eq!(edits.get(Some(1)), Some("다른 행"));
        edits.revert(0);
        assert_eq!(edits.epoch, 1);
        assert_eq!(edits.len(), 1);
    }
}
