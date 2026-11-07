//! Context evidence for one visible document-value site.

use crate::field_induction::{CellRef, ParagraphText, Slot, hangul_bounded, specificity};
use crate::field_induction_labels::{
    CUE_FIXED, CUE_GENERIC, CUE_REPEAT, data_cue, extract_label, glued_left, is_label_cell,
    label_matches, leading_marker, names_literally, normalize_label, number_frame, raw_label,
    static_cue, strip_markers, word_windows,
};
use regex::Regex;
use std::collections::{BTreeMap, HashMap};
use std::sync::OnceLock;

const MASK: char = '␀';
const SPECIFIC: f64 = 0.75;

#[derive(Clone, Debug)]
pub struct SpotEvidence {
    pub slot: Slot,
    pub text: String,
    pub label: String,
    pub matched: Vec<String>,
    pub literal: Vec<String>,
    pub glued: bool,
    pub cue: Option<&'static str>,
    pub data: bool,
    pub standalone: bool,
    pub creatable: bool,
    pub bounded: bool,
}
impl SpotEvidence {
    pub fn labelled(&self) -> bool {
        !self.matched.is_empty() && !self.glued && matches!(self.cue, None | Some(CUE_REPEAT))
    }
    pub fn anchored(&self) -> bool {
        (self.standalone || self.data) && !self.glued
    }
    pub fn generic(&self) -> bool {
        self.cue == Some(CUE_GENERIC)
    }
    pub fn fixed(&self) -> bool {
        self.cue == Some(CUE_FIXED)
    }
}

fn char_slice(text: &str, start: usize, end: usize) -> String {
    text.chars()
        .skip(start)
        .take(end.saturating_sub(start))
        .collect()
}
fn collapsed(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub struct DocumentView {
    pub paragraphs: Vec<ParagraphText>,
    whole: String,
    cells: Vec<(CellRef, String)>,
    where_labels: Vec<String>,
    masks: HashMap<usize, Vec<(usize, usize)>>,
}
fn push_cell_text(cell_texts: &mut Vec<(CellRef, Vec<String>)>, paragraph: &ParagraphText) {
    if let Some(cell) = &paragraph.cell {
        if let Some((_, texts)) = cell_texts.iter_mut().find(|(key, _)| key == cell) {
            texts.push(paragraph.text.clone())
        } else {
            cell_texts.push((cell.clone(), vec![paragraph.text.clone()]));
        }
    }
}
fn compute_where_label(
    paragraph: &ParagraphText,
    numbering: &mut BTreeMap<usize, String>,
) -> String {
    if paragraph.cell.is_none()
        && let Some((level, token)) = leading_marker(&paragraph.text)
    {
        numbering.retain(|depth, _| *depth < level);
        numbering.insert(level, token);
    }
    let mut path = numbering.values().cloned().collect::<Vec<_>>().join(" ");
    path = path.trim_end_matches('.').into();
    if paragraph.cell.is_some() {
        path = if path.is_empty() {
            "표 칸".into()
        } else {
            format!("표 칸, {path}")
        };
    }
    path
}
fn mask_slot(
    masks: &mut HashMap<usize, Vec<(usize, usize)>>,
    paragraphs: &[ParagraphText],
    slot: &Slot,
) {
    let text = &paragraphs[slot.paragraph].text;
    let span = char_slice(text, slot.start, slot.end);
    if specificity(&span) >= SPECIFIC || hangul_bounded(text, slot.start, slot.end) {
        masks
            .entry(slot.paragraph)
            .or_default()
            .push((slot.start, slot.end));
    }
}
impl DocumentView {
    pub fn new(paragraphs: &[ParagraphText], slots: &[Slot]) -> Self {
        let mut cell_texts: Vec<(CellRef, Vec<String>)> = Vec::new();
        for paragraph in paragraphs {
            push_cell_text(&mut cell_texts, paragraph);
        }
        let cells = cell_texts
            .into_iter()
            .map(|(cell, texts)| (cell, collapsed(&texts.join(" "))))
            .collect();
        let mut numbering: BTreeMap<usize, String> = BTreeMap::new();
        let mut where_labels = Vec::new();
        for paragraph in paragraphs {
            where_labels.push(compute_where_label(paragraph, &mut numbering));
        }
        let mut masks: HashMap<usize, Vec<(usize, usize)>> = HashMap::new();
        for slot in slots {
            mask_slot(&mut masks, paragraphs, slot);
        }
        Self {
            paragraphs: paragraphs.to_vec(),
            whole: paragraphs
                .iter()
                .map(|paragraph| paragraph.text.as_str())
                .collect::<Vec<_>>()
                .join("\n"),
            cells,
            where_labels,
            masks,
        }
    }
    pub fn where_label(&self, index: usize) -> &str {
        &self.where_labels[index]
    }
    pub fn repeats(&self, text: &str) -> usize {
        self.whole.matches(text).count()
    }
    pub fn line_prefixes(&self, text: &str) -> Vec<String> {
        let mut found = Vec::new();
        let mut start = 0;
        while found.len() < 50 {
            let Some(offset) = self.whole[start..].find(text) else {
                break;
            };
            let at = start + offset;
            let line_start = self.whole[..at].rfind('\n').map_or(0, |index| index + 1);
            let before = &self.whole[line_start..at];
            found.push(
                before
                    .chars()
                    .rev()
                    .take(32)
                    .collect::<Vec<_>>()
                    .into_iter()
                    .rev()
                    .collect(),
            );
            start = at + text.len();
            if start >= self.whole.len() {
                break;
            }
        }
        found
    }
    pub fn masked_line(&self, slot: &Slot) -> (String, String) {
        let mut chars: Vec<char> = self.paragraphs[slot.paragraph].text.chars().collect();
        for (start, end) in self.masks.get(&slot.paragraph).into_iter().flatten() {
            if (*start, *end) != (slot.start, slot.end) {
                for at in *start..*end {
                    if let Some(ch) = chars.get_mut(at) {
                        *ch = MASK;
                    }
                }
            }
        }
        let left: String = chars[..slot.start].iter().collect();
        let right: String = chars[slot.end..].iter().collect();
        (
            left.rsplit('\n').next().unwrap_or("").into(),
            right.split('\n').next().unwrap_or("").into(),
        )
    }
    fn left_of(&self, cell: &CellRef) -> String {
        self.cells
            .iter()
            .find(|(other, _)| {
                other.table == cell.table
                    && other.row <= cell.row
                    && cell.row < other.row + other.row_span
                    && other.col + other.col_span == cell.col
            })
            .map(|(_, text)| text.clone())
            .unwrap_or_default()
    }
    fn above(&self, cell: &CellRef) -> String {
        self.cells
            .iter()
            .find(|(other, _)| {
                other.table == cell.table
                    && other.col <= cell.col
                    && cell.col < other.col + other.col_span
                    && other.row + other.row_span == cell.row
            })
            .map(|(_, text)| text.clone())
            .unwrap_or_default()
    }
    pub fn previous_lines(&self, index: usize) -> Vec<String> {
        if let Some(cell) = &self.paragraphs[index].cell {
            let labels: Vec<_> = [self.left_of(cell), self.above(cell)]
                .into_iter()
                .filter(|text| !text.is_empty() && is_label_cell(&strip_markers(text)))
                .collect();
            if !labels.is_empty() {
                return labels;
            }
        }
        vec![
            index
                .checked_sub(1)
                .and_then(|at| self.paragraphs.get(at))
                .map(|paragraph| paragraph.text.clone())
                .unwrap_or_default(),
        ]
    }
    pub fn next_line(&self, index: usize) -> &str {
        self.paragraphs
            .get(index + 1)
            .map_or("", |paragraph| paragraph.text.as_str())
    }
}

#[derive(Default)]
struct LabelEvidence {
    text: String,
    matched: Vec<String>,
    literal: Vec<String>,
    left: String,
}
fn found(text: String, key: &str, matched: Vec<String>) -> LabelEvidence {
    let literal = matched
        .iter()
        .filter(|column| names_literally(key, &normalize_label(column)))
        .cloned()
        .collect();
    LabelEvidence {
        text,
        matched,
        literal,
        left: String::new(),
    }
}
fn matching(columns: &[String], label: &str, fuzzy: bool) -> Vec<String> {
    columns
        .iter()
        .filter(|column| label_matches(label, &normalize_label(column), fuzzy))
        .cloned()
        .collect()
}
fn line_label(left: &str, columns: &[String]) -> LabelEvidence {
    let (label, how) = extract_label(left);
    let matched = if label.is_empty() {
        Vec::new()
    } else {
        matching(columns, &label, matches!(how, "colon" | "cell"))
    };
    if !matched.is_empty() || !matches!(how, "before" | "colon-but-value-between") {
        return found(
            if label.is_empty() {
                String::new()
            } else {
                raw_label(left, how)
            },
            &label,
            matched,
        );
    }
    for window in word_windows(&strip_markers(left.rsplit('\n').next().unwrap_or(""))) {
        let key = normalize_label(&window);
        let hit = matching(columns, &key, false);
        if !hit.is_empty() {
            return found(window, &key, hit);
        }
    }
    found(
        if label.is_empty() {
            String::new()
        } else {
            raw_label(left, how)
        },
        &label,
        Vec::new(),
    )
}
fn label(view: &DocumentView, slot: &Slot, columns: &[String]) -> LabelEvidence {
    let before = char_slice(&view.paragraphs[slot.paragraph].text, 0, slot.start);
    let mut first = None;
    for previous in view.previous_lines(slot.paragraph) {
        let left = format!("{previous}\n{before}");
        let mut evidence = line_label(&left, columns);
        evidence.left = left;
        if !evidence.matched.is_empty() {
            return evidence;
        }
        if first.is_none() {
            first = Some(evidence)
        }
    }
    first.unwrap_or_default()
}
fn alnum_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[가-힣A-Za-z0-9]").expect("static alnum"))
}
fn standalone(span: &str, line_left: &str, line_right: &str) -> bool {
    static PARENTHESES: OnceLock<Regex> = OnceLock::new();
    static ALIGNMENT: OnceLock<Regex> = OnceLock::new();
    static COLON_TAIL: OnceLock<Regex> = OnceLock::new();
    if span
        .chars()
        .last()
        .is_some_and(|ch| ('가'..='힣').contains(&ch))
        && line_right
            .chars()
            .next()
            .is_some_and(|ch| ('가'..='힣').contains(&ch))
    {
        return false;
    }
    let left = line_left.rsplit(['~', '∼']).next().unwrap_or("");
    let right = line_right.split(['~', '∼']).next().unwrap_or("");
    let no_parentheses = PARENTHESES
        .get_or_init(|| Regex::new(r"\([^)]*\)|（[^）]*）").expect("static parenthesis"))
        .replace_all(right, "");
    let letters = alnum_re().find_iter(&no_parentheses).count();
    if letters == 0
        && ALIGNMENT
            .get_or_init(|| Regex::new(r"(?: {2,}|\t)$").expect("static alignment"))
            .is_match(left)
    {
        return true;
    }
    let left = strip_markers(left);
    let left = left.trim();
    let colon_tail = COLON_TAIL
        .get_or_init(|| Regex::new(r"[:：][\s␀]*$").expect("static colon tail"))
        .is_match(left);
    (!alnum_re().is_match(left) || colon_tail) && letters <= 2
}
fn apposition(left: &str, right: &str) -> bool {
    (left.ends_with("␀(") || left.ends_with("␀（"))
        && (right.starts_with(')') || right.starts_with('）'))
}
pub fn spot_evidence(view: &DocumentView, slot: &Slot, columns: &[String]) -> SpotEvidence {
    let paragraph = &view.paragraphs[slot.paragraph];
    let length = paragraph.text.chars().count();
    let span = char_slice(&paragraph.text, slot.start, slot.end);
    let before = char_slice(&paragraph.text, 0, slot.start);
    let after = char_slice(&paragraph.text, slot.end, length);
    let line_left = before.rsplit('\n').next().unwrap_or("");
    let line_right = after.split('\n').next().unwrap_or("");
    let right = format!("{after}\n{}", view.next_line(slot.paragraph));
    let label = label(view, slot, columns);
    let (masked_left, masked_right) = view.masked_line(slot);
    let cue = static_cue(
        &label.left,
        &span,
        &right,
        view.repeats(&span),
        &view.line_prefixes(&span),
    );
    SpotEvidence {
        slot: slot.clone(),
        text: span.clone(),
        label: label.text,
        matched: label.matched,
        literal: label.literal,
        glued: glued_left(line_left, &span) && !number_frame(line_left, line_right),
        cue,
        data: data_cue(line_left, &span, &right) || apposition(&masked_left, &masked_right),
        standalone: standalone(&span, &masked_left, &masked_right),
        creatable: slot.end < paragraph.editable_end,
        bounded: hangul_bounded(&paragraph.text, slot.start, slot.end),
    }
}
