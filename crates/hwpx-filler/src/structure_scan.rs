//! Shared product grammar and read-only range state machine for structure markers.

use crate::fields::python_whitespace;
pub use crate::fields::{collapse_field_id, normalize_field_id};
use crate::slot::{Slot, SlotOption};
use serde_json::{Value, json};
use std::collections::HashSet;

pub const CONTEXT_MAX: usize = 120;
pub const SLOT_KEYWORD: &str = "항목";
pub const OPTION_KEYWORD: &str = "선택";
pub const PLACEMENT_SLOT: &str = "slot";
pub const PLACEMENT_OPTION: &str = "option";

pub fn python_trim(s: &str) -> &str {
    s.trim_matches(python_whitespace)
}

pub fn is_structure_sigil(raw: &str) -> bool {
    raw.trim_start_matches(python_whitespace)
        .starts_with(['#', '/'])
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenMatch<'a> {
    pub start: usize,
    pub end: usize,
    pub source: &'a str,
    pub body: &'a str,
}

/// Match Python's `{{\s*([^{}]+?)\s*}}` from left to right. `allow_pipe=false`
/// applies the TXT renderer's narrower body grammar.
pub fn token_matches(text: &str, allow_pipe: bool) -> Vec<TokenMatch<'_>> {
    let mut matches = Vec::new();
    let mut from = 0;
    while let Some(relative) = text[from..].find("{{") {
        let start = from + relative;
        let inner = start + 2;
        let mut end = None;
        for (offset, c) in text[inner..].char_indices() {
            if c == '{' || (c == '|' && !allow_pipe) {
                break;
            }
            if c == '}' {
                if text[inner + offset..].starts_with("}}") {
                    end = Some(inner + offset);
                }
                break;
            }
        }
        if let Some(close) = end {
            let interior = &text[inner..close];
            let leading = interior.trim_start_matches(python_whitespace);
            // The capture has minimum length one; all-whitespace bodies capture
            // their last character after the greedy leading whitespace.
            let body = if leading.is_empty() {
                interior
                    .char_indices()
                    .last()
                    .map(|(last, _)| &interior[last..])
            } else {
                let trimmed = leading.trim_end_matches(python_whitespace);
                Some(trimmed)
            };
            if let Some(body) = body {
                let finish = close + 2;
                matches.push(TokenMatch {
                    start,
                    end: finish,
                    source: &text[start..finish],
                    body,
                });
                from = finish;
                continue;
            }
        }
        // A rejected opener can overlap a valid one (`{{{x}}` -> `{{x}}`).
        from = start + 1;
    }
    matches
}

pub fn iter_field_tokens(text: &str) -> Vec<TokenMatch<'_>> {
    token_matches(text, true)
        .into_iter()
        .filter(|m| !is_structure_sigil(m.body))
        .collect()
}

pub fn iter_structure_markers(text: &str) -> Vec<TokenMatch<'_>> {
    token_matches(text, true)
        .into_iter()
        .filter(|m| is_structure_sigil(m.body))
        .collect()
}

fn split_once_whitespace(s: &str) -> (&str, &str) {
    let s = s.trim_start_matches(python_whitespace);
    let end = s.find(python_whitespace).unwrap_or(s.len());
    (&s[..end], s[end..].trim_start_matches(python_whitespace))
}

pub fn split_structure_marker(raw: &str) -> (String, String, String) {
    let body = raw.trim_start_matches(python_whitespace);
    let mut chars = body.chars();
    let sigil = chars.next().map_or(String::new(), |c| c.to_string());
    let rest = python_trim(chars.as_str());
    let (keyword, tail) = split_once_whitespace(rest);
    (sigil, keyword.into(), tail.into())
}

pub fn structure_marker_name(tail: &str) -> (Option<String>, String) {
    let (id, label) = split_once_whitespace(tail);
    (
        normalize_field_id(id),
        collapse_field_id(label).unwrap_or_default(),
    )
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StructureDiagnosticKind {
    UnbalancedMarker,
    CrossedRange,
    UnknownKeyword,
    EmptySlotId,
    EmptyOptionId,
    DuplicateSlotId,
    DuplicateOptionId,
    OptionOutsideSlot,
    NestedSlot,
    NestedOption,
    MarkerInTable,
    MarkerNotTopLevel,
    MarkerNotAlone,
    EmptyRange,
    EndMarkerExtraText,
}

impl StructureDiagnosticKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::UnbalancedMarker => "unbalanced_marker",
            Self::CrossedRange => "crossed_range",
            Self::UnknownKeyword => "unknown_keyword",
            Self::EmptySlotId => "empty_slot_id",
            Self::EmptyOptionId => "empty_option_id",
            Self::DuplicateSlotId => "duplicate_slot_id",
            Self::DuplicateOptionId => "duplicate_option_id",
            Self::OptionOutsideSlot => "option_outside_slot",
            Self::NestedSlot => "nested_slot",
            Self::NestedOption => "nested_option",
            Self::MarkerInTable => "marker_in_table",
            Self::MarkerNotTopLevel => "marker_not_top_level",
            Self::MarkerNotAlone => "marker_not_alone",
            Self::EmptyRange => "empty_range",
            Self::EndMarkerExtraText => "end_marker_extra_text",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureDiagnostic {
    pub kind: StructureDiagnosticKind,
    pub message: String,
    pub context: String,
    pub entry: String,
    pub index: Option<usize>,
}

impl StructureDiagnostic {
    pub fn to_dict(&self) -> Value {
        json!({ "kind": self.kind.as_str(), "message": self.message, "context": self.context })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StructureSummary {
    pub slots: usize,
    pub options: usize,
    pub fields: usize,
    pub markers: usize,
}

impl StructureSummary {
    pub fn to_dict(&self) -> Value {
        json!({ "slots": self.slots, "options": self.options,
            "fields": self.fields, "markers": self.markers })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RangePlacement {
    pub kind: &'static str,
    pub slot_id: String,
    pub option_id: Option<String>,
    pub begin_index: usize,
    pub end_index: usize,
    pub content_start: usize,
    pub content_end: usize,
}

#[derive(Clone, Debug)]
struct OpenRange {
    id: String,
    label: String,
    context: String,
    entry: String,
    begin_index: usize,
    content: usize,
    first_content: Option<usize>,
    last_content: Option<usize>,
}

impl OpenRange {
    fn new(id: String, label: String, context: &str, entry: &str, index: usize) -> Self {
        Self {
            id,
            label,
            context: context.into(),
            entry: entry.into(),
            begin_index: index,
            content: 0,
            first_content: None,
            last_content: None,
        }
    }
    fn note_content(&mut self, index: usize) {
        self.first_content.get_or_insert(index);
        self.last_content = Some(index);
    }
}

pub struct StructureReader {
    pub slots: Vec<Slot>,
    pub diagnostics: Vec<StructureDiagnostic>,
    pub placements: Vec<RangePlacement>,
    pub markers: usize,
    scope: String,
    slot: Option<OpenRange>,
    option: Option<OpenRange>,
    options: Vec<SlotOption>,
    option_placements: Vec<RangePlacement>,
    seen_slot_ids: HashSet<String>,
    entry: String,
    index: usize,
    located: bool,
}

impl StructureReader {
    pub fn new(scope: &str) -> Self {
        Self {
            slots: Vec::new(),
            diagnostics: Vec::new(),
            placements: Vec::new(),
            markers: 0,
            scope: scope.into(),
            slot: None,
            option: None,
            options: Vec::new(),
            option_placements: Vec::new(),
            seen_slot_ids: HashSet::new(),
            entry: String::new(),
            index: 0,
            located: false,
        }
    }
    pub fn position(&mut self, entry: &str, index: Option<usize>) {
        self.entry = entry.into();
        if let Some(index) = index {
            self.index = index;
        }
        self.located = index.is_some();
    }
    pub fn note_markers(&mut self, count: usize) {
        self.markers += count;
    }
    pub fn note(
        &mut self,
        kind: StructureDiagnosticKind,
        message: String,
        context: &str,
        at: Option<(String, usize)>,
    ) {
        let (entry, index) = at.map_or_else(
            || (self.entry.clone(), self.located.then_some(self.index)),
            |(entry, index)| (entry, Some(index)),
        );
        self.diagnostics.push(StructureDiagnostic {
            kind,
            message,
            context: context.into(),
            entry,
            index,
        });
    }
    pub fn count_content(&mut self) {
        if let Some(option) = &mut self.option {
            option.content += 1;
        } else if let Some(slot) = &mut self.slot {
            slot.content += 1;
        }
        if let Some(slot) = &mut self.slot {
            slot.note_content(self.index);
        }
        if let Some(option) = &mut self.option {
            option.note_content(self.index);
        }
    }
    pub fn read_marker(&mut self, raw: &str, context: &str) {
        use StructureDiagnosticKind as K;
        let (sigil, keyword, tail) = split_structure_marker(raw);
        if keyword != SLOT_KEYWORD && keyword != OPTION_KEYWORD {
            self.note(
                K::UnknownKeyword,
                format!(
                    "알 수 없는 구간 키워드입니다: 「{}」 — 「항목」·「선택」만 쓸 수 있습니다.",
                    if keyword.is_empty() {
                        "(없음)"
                    } else {
                        &keyword
                    }
                ),
                context,
                None,
            );
        } else if sigil == "#" {
            self.begin(&keyword, &tail, context);
        } else {
            self.end(&keyword, &tail, context);
        }
    }
    pub fn settle_refused(&mut self, raw: &str, context: &str) {
        let (sigil, keyword, tail) = split_structure_marker(raw);
        if sigil != "/"
            || (keyword == OPTION_KEYWORD && self.option.is_none())
            || (keyword == SLOT_KEYWORD && self.slot.is_none())
            || (keyword != SLOT_KEYWORD && keyword != OPTION_KEYWORD)
        {
            return;
        }
        self.count_content();
        self.end(&keyword, &tail, context);
    }
    pub fn close_entry(&mut self) {
        use StructureDiagnosticKind as K;
        if let Some(option) = self.option.take() {
            self.note(K::UnbalancedMarker,
                format!("「선택 {}」 범위가 열린 채 {} 끝났습니다 — 닫는 마커가 없습니다(범위는 한 파일 안에서 닫혀야 합니다).", option.id, self.scope),
                &option.context, Some((option.entry, option.begin_index)));
        }
        if let Some(slot) = self.slot.take() {
            self.note(K::UnbalancedMarker,
                format!("「항목 {}」 범위가 열린 채 {} 끝났습니다 — 닫는 마커가 없습니다(범위는 한 파일 안에서 닫혀야 합니다).", slot.id, self.scope),
                &slot.context, Some((slot.entry, slot.begin_index)));
            self.options.clear();
            self.option_placements.clear();
        }
    }
    fn begin(&mut self, keyword: &str, tail: &str, context: &str) {
        use StructureDiagnosticKind as K;
        let (ident, label) = structure_marker_name(tail);
        let Some(ident) = ident else {
            let kind = if keyword == SLOT_KEYWORD {
                K::EmptySlotId
            } else {
                K::EmptyOptionId
            };
            self.note(
                kind,
                format!("「{keyword}」 마커에 id 가 없습니다 — id 는 필수입니다."),
                context,
                None,
            );
            return;
        };
        if keyword == SLOT_KEYWORD {
            if let Some(slot) = &self.slot {
                self.note(K::NestedSlot,
                    format!("「항목 {}」 안에서 다시 「항목 {ident}」 을 열었습니다 — 항목 중첩은 없습니다.", slot.id), context, None);
                return;
            }
            if !self.seen_slot_ids.insert(ident.clone()) {
                self.note(
                    K::DuplicateSlotId,
                    format!("같은 문서에서 항목 id 「{ident}」 가 두 번 선언됐습니다."),
                    context,
                    None,
                );
            }
            self.slot = Some(OpenRange::new(
                ident,
                label,
                context,
                &self.entry,
                self.index,
            ));
            self.options.clear();
            self.option_placements.clear();
        } else {
            let Some(slot) = &self.slot else {
                self.note(K::OptionOutsideSlot,
                    format!("「선택 {ident}」 이 항목 범위 밖에 있습니다 — 선택은 항목 직속만 가능합니다."), context, None);
                return;
            };
            if let Some(option) = &self.option {
                self.note(
                    K::NestedOption,
                    format!(
                        "「선택 {}」 이 닫히기 전에 「선택 {ident}」 을 열었습니다.",
                        option.id
                    ),
                    context,
                    None,
                );
                return;
            }
            if self.options.iter().any(|option| option.id == ident) {
                let slot_id = slot.id.clone();
                self.note(
                    K::DuplicateOptionId,
                    format!("항목 「{slot_id}」 안에서 선택 id 「{ident}」 가 두 번 선언됐습니다."),
                    context,
                    None,
                );
            }
            self.option = Some(OpenRange::new(
                ident,
                label,
                context,
                &self.entry,
                self.index,
            ));
        }
    }
    fn placement(
        &self,
        kind: &'static str,
        opened: &OpenRange,
        slot_id: String,
        option_id: Option<String>,
    ) -> RangePlacement {
        RangePlacement {
            kind,
            slot_id,
            option_id,
            begin_index: opened.begin_index,
            end_index: self.index,
            content_start: opened.first_content.unwrap_or(opened.begin_index + 1),
            content_end: opened.last_content.unwrap_or(self.index.saturating_sub(1)),
        }
    }
    fn end(&mut self, keyword: &str, tail: &str, context: &str) {
        use StructureDiagnosticKind as K;
        if !python_trim(tail).is_empty() {
            let extra = collapse_field_id(tail).unwrap_or_default();
            self.note(K::EndMarkerExtraText,
                format!("닫는 「{keyword}」 마커에 남은 텍스트가 있습니다: 「{extra}」 — 닫는 마커는 키워드만 가집니다."),
                context, None);
        }
        if keyword == OPTION_KEYWORD {
            if self.option.is_none() {
                self.note(
                    K::UnbalancedMarker,
                    "여는 「선택」 마커 없이 닫는 「선택」 마커가 나왔습니다.".into(),
                    context,
                    None,
                );
            } else {
                self.close_option(context);
            }
            return;
        }
        if self.slot.is_none() {
            self.note(
                K::UnbalancedMarker,
                "여는 「항목」 마커 없이 닫는 「항목」 마커가 나왔습니다.".into(),
                context,
                None,
            );
            return;
        }
        if let Some(option) = &self.option {
            let option_id = option.id.clone();
            let slot_id = self.slot.as_ref().map(|s| s.id.clone()).unwrap_or_default();
            self.note(K::CrossedRange,
                format!("「선택 {option_id}」 이 닫히기 전에 「항목 {slot_id}」 이 닫혔습니다 — 범위가 교차합니다."), context, None);
            self.close_option(context);
        }
        let slot = self.slot.take().expect("checked above");
        if slot.content == 0 {
            self.note(
                K::EmptyRange,
                format!("「항목 {}」 범위에 내용 문단이 없습니다.", slot.id),
                context,
                None,
            );
        }
        self.slots.push(Slot {
            id: slot.id.clone(),
            options: std::mem::take(&mut self.options),
            label: (!slot.label.is_empty()).then_some(slot.label.clone()),
        });
        self.placements
            .push(self.placement(PLACEMENT_SLOT, &slot, slot.id.clone(), None));
        self.placements.append(&mut self.option_placements);
    }
    fn close_option(&mut self, context: &str) {
        use StructureDiagnosticKind as K;
        let option = self.option.take().expect("checked above");
        if option.content == 0 {
            self.note(
                K::EmptyRange,
                format!("「선택 {}」 범위에 내용 문단이 없습니다.", option.id),
                context,
                None,
            );
        }
        self.options.push(SlotOption {
            id: option.id.clone(),
            order: self.options.len(),
            label: (!option.label.is_empty()).then_some(option.label.clone()),
        });
        let slot_id = self
            .slot
            .as_ref()
            .expect("option belongs to slot")
            .id
            .clone();
        self.option_placements.push(self.placement(
            PLACEMENT_OPTION,
            &option,
            slot_id,
            Some(option.id.clone()),
        ));
        self.slot.as_mut().expect("option belongs to slot").content += 1;
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn shared_token_grammar_keeps_unicode_whitespace_and_sigil_separate() {
        let text = "{{\u{001c} #항목 A }} {{x|amount}} {{\u{001c}이름\u{001c}}} {{ }} {{{x}}";
        let markers = iter_structure_markers(text);
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].body, "#항목 A");
        let fields = iter_field_tokens(text);
        assert_eq!(
            fields.iter().map(|m| m.body).collect::<Vec<_>>(),
            ["x|amount", "이름", " ", "x"]
        );
        assert_eq!(
            normalize_field_id(" {{  중\u{001c} 첩  }} "),
            Some("중 첩".into())
        );
    }
}
