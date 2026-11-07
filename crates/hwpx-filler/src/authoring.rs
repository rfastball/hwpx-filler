//! Read-only HWPX authoring token scan. Compilation remains a separate edit operation.

use crate::fields::python_whitespace;
use hwpx_core::authoring_edit::{TokenFieldEdit, compile_field_tokens};
use hwpx_core::package::HwpxPackage;
use hwpx_core::text_model::HP_NS;
use hwpx_core::xml_view::XmlView;
use hwpx_core::{Content, NodeId, XmlError};
use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::sync::OnceLock;

const CONTEXT_MAX: usize = 120;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenSite {
    pub name: String,
    pub context: String,
    pub compilable: bool,
    pub reason: String,
    pub entry: String,
    pub paragraph_path: String,
    pub start: isize,
    pub end: isize,
    pub(crate) literal: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TokenScanError(pub String);

impl fmt::Display for TokenScanError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TokenScanError {}
impl From<XmlError> for TokenScanError {
    fn from(value: XmlError) -> Self {
        Self(value.0)
    }
}

fn trim_python(text: &str) -> &str {
    text.trim_matches(python_whitespace)
}

fn token_regex() -> &'static Regex {
    static TOKEN: OnceLock<Regex> = OnceLock::new();
    TOKEN.get_or_init(|| {
        Regex::new(r"\{\{[\s\u{001C}-\u{001F}]*([^{}]+?)[\s\u{001C}-\u{001F}]*\}\}")
            .expect("fixed token regex")
    })
}

#[derive(Clone)]
struct TokenMatch {
    start: usize,
    end: usize,
    byte_start: usize,
    name: String,
    literal: String,
}

fn token_matches(text: &str, include_sigils: bool) -> Vec<TokenMatch> {
    let mut matches = Vec::new();
    let mut byte_at = 0;
    let mut char_at = 0;
    for captures in token_regex().captures_iter(text) {
        let full = captures.get(0).unwrap();
        char_at += text[byte_at..full.start()].chars().count();
        let start = char_at;
        char_at += text[full.start()..full.end()].chars().count();
        byte_at = full.end();
        let name = trim_python(captures.get(1).unwrap().as_str());
        if !include_sigils && matches!(name.chars().next(), Some('#' | '/')) {
            continue;
        }
        matches.push(TokenMatch {
            start,
            end: char_at,
            byte_start: full.start(),
            name: name.to_owned(),
            literal: full.as_str().to_owned(),
        });
    }
    matches
}

fn element_children(view: &XmlView, id: NodeId) -> impl Iterator<Item = NodeId> + '_ {
    view.node(id)
        .unwrap()
        .children
        .iter()
        .filter_map(|part| match part {
            Content::Element(child) => Some(*child),
            _ => None,
        })
}

fn node_children(view: &XmlView, id: NodeId) -> impl Iterator<Item = Option<NodeId>> + '_ {
    view.node(id)
        .unwrap()
        .children
        .iter()
        .filter_map(|part| match part {
            Content::Element(child) => Some(Some(*child)),
            Content::Comment(_) | Content::ProcessingInstruction(_) => Some(None),
            Content::Text(_) | Content::CData(_) => None,
        })
}

fn local(view: &XmlView, id: NodeId) -> &str {
    &view.node(id).unwrap().name.local
}

fn leading_text(view: &XmlView, id: NodeId) -> String {
    let mut text = String::new();
    for part in &view.node(id).unwrap().children {
        match part {
            Content::Text(value) | Content::CData(value) => text.push_str(value),
            _ => break,
        }
    }
    text
}

pub(crate) fn paragraph_context(view: &XmlView, paragraph: NodeId) -> String {
    let mut parts = String::new();
    'runs: for run in element_children(view, paragraph) {
        if local(view, run) != "run" {
            continue;
        }
        for child in element_children(view, run) {
            match local(view, child) {
                "t" => parts.push_str(&leading_text(view, child)),
                "tbl" => break 'runs,
                _ => {}
            }
        }
    }
    trim_python(&parts).chars().take(CONTEXT_MAX).collect()
}

fn t_text_events(view: &XmlView, text: NodeId) -> (String, Vec<(usize, &'static str)>) {
    let mut result = String::new();
    let mut events = Vec::new();
    let mut length = 0;
    for part in &view.node(text).unwrap().children {
        match part {
            Content::Text(value) | Content::CData(value) => {
                result.push_str(value);
                length += value.chars().count();
            }
            Content::Element(child) => {
                let kind = match local(view, *child) {
                    "tab" => "tab",
                    "lineBreak" => "lineBreak",
                    _ => "inline",
                };
                events.push((length, kind));
                match kind {
                    "tab" => {
                        result.push('\t');
                        length += 1;
                    }
                    "lineBreak" => {
                        result.push('\n');
                        length += 1;
                    }
                    _ => {}
                }
            }
            Content::Comment(_) | Content::ProcessingInstruction(_) => {
                events.push((length, "inline"));
            }
        }
    }
    (result, events)
}

fn simple_text(view: &XmlView, run: NodeId) -> Option<(NodeId, String)> {
    let mut texts = Vec::new();
    let mut controls = 0;
    let mut others = 0;
    for child in element_children(view, run) {
        match local(view, child) {
            "t" => texts.push(child),
            "ctrl" => controls += 1,
            _ => others += 1,
        }
    }
    if texts.len() != 1 || controls != 0 || others != 0 {
        return None;
    }
    let text = texts[0];
    if view.node(text).unwrap().children.iter().any(|part| {
        matches!(
            part,
            Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
        )
    }) {
        return None;
    }
    Some((text, leading_text(view, text)))
}

#[derive(Clone)]
struct Piece {
    start: usize,
    end: usize,
    run: NodeId,
    simple: bool,
    child_index: usize,
}

struct ParagraphModel {
    text: String,
    pieces: Vec<Piece>,
    events: Vec<(usize, &'static str)>,
    run_base: HashMap<NodeId, usize>,
}

/// Walks a paragraph's runs, tracking field nesting, to build its [`ParagraphModel`].
struct ModelBuilder<'v> {
    view: &'v XmlView,
    model: ParagraphModel,
    depth: i32,
    length: usize,
}

impl ModelBuilder<'_> {
    fn run(&mut self, run: NodeId, child_index: usize) {
        let view = self.view;
        let simple = simple_text(view, run).is_some();
        self.model.run_base.entry(run).or_insert(self.length);
        for item in node_children(view, run) {
            let Some(node) = item else {
                if self.depth == 0 {
                    self.model.events.push((self.length, "struct"));
                }
                continue;
            };
            match local(view, node) {
                "ctrl" => self.control(node),
                "t" if self.depth == 0 => self.text(node, run, simple, child_index),
                "tab" | "lineBreak" if self.depth == 0 => self.line_break(node),
                _ if self.depth == 0 => self.model.events.push((self.length, "struct")),
                _ => {}
            }
        }
    }
    /// Field boundaries change the nesting depth; other top-level controls are events.
    fn control(&mut self, node: NodeId) {
        let mut field_boundary = false;
        for ctrl_child in element_children(self.view, node) {
            match local(self.view, ctrl_child) {
                "fieldBegin" => {
                    self.depth += 1;
                    field_boundary = true;
                }
                "fieldEnd" => {
                    self.depth = (self.depth - 1).max(0);
                    field_boundary = true;
                }
                _ => {}
            }
        }
        if self.depth == 0 && !field_boundary {
            self.model.events.push((self.length, "ctrl"));
        }
    }
    fn text(&mut self, node: NodeId, run: NodeId, simple: bool, child_index: usize) {
        let start = self.length;
        let (value, events) = t_text_events(self.view, node);
        self.length += value.chars().count();
        self.model.text.push_str(&value);
        let end = self.length;
        self.model.pieces.push(Piece {
            start,
            end,
            run,
            simple,
            child_index,
        });
        self.model
            .events
            .extend(events.into_iter().map(|(at, kind)| (start + at, kind)));
    }
    fn line_break(&mut self, node: NodeId) {
        let at = self.length;
        let kind = if local(self.view, node) == "tab" {
            "tab"
        } else {
            "lineBreak"
        };
        self.model.events.push((at, kind));
        self.model
            .text
            .push(if kind == "tab" { '\t' } else { '\n' });
        self.length += 1;
    }
}

fn paragraph_model(view: &XmlView, paragraph: NodeId) -> ParagraphModel {
    let mut builder = ModelBuilder {
        view,
        model: ParagraphModel {
            text: String::new(),
            pieces: Vec::new(),
            events: Vec::new(),
            run_base: HashMap::new(),
        },
        depth: 0,
        length: 0,
    };
    for (child_index, child) in node_children(view, paragraph).enumerate() {
        let Some(run) = child else { continue };
        if local(view, run) == "run" {
            builder.run(run, child_index);
        }
    }
    builder.model
}

pub(crate) fn paragraph_model_text(view: &XmlView, paragraph: NodeId) -> String {
    paragraph_model(view, paragraph).text
}

fn run_has_field(view: &XmlView, run: NodeId) -> bool {
    view.descendants(run).unwrap().into_iter().any(|id| {
        view.node(id).unwrap().name.namespace == HP_NS
            && matches!(local(view, id), "fieldBegin" | "fieldEnd")
    })
}

fn site(
    name: String,
    context: &str,
    compilable: bool,
    reason: &str,
    location: (&str, &str),
    start: isize,
    end: isize,
) -> TokenSite {
    let (entry, path) = location;
    TokenSite {
        name,
        context: context.to_owned(),
        compilable,
        reason: reason.to_owned(),
        entry: entry.to_owned(),
        paragraph_path: path.to_owned(),
        start,
        end,
        literal: None,
    }
}

/// What a token match spans in the paragraph model.
struct Coverage<'v> {
    inside: Vec<&'static str>,
    runs: Vec<NodeId>,
    char_prs: HashSet<Option<&'v str>>,
    contiguous: bool,
    all_simple: bool,
}

impl Coverage<'_> {
    /// One run format, adjacent runs, no inner events, and no field in the runs.
    fn clean(&self, view: &XmlView) -> bool {
        let same_format =
            self.runs.len() == 1 || (self.char_prs.len() == 1 && !self.char_prs.contains(&None));
        self.inside.is_empty()
            && same_format
            && self.contiguous
            && !self.runs.iter().any(|run| run_has_field(view, *run))
    }
    /// Why a composite token cannot be compiled automatically, most specific first.
    fn refusal(&self) -> &'static str {
        if self
            .inside
            .iter()
            .any(|kind| matches!(*kind, "tab" | "lineBreak"))
        {
            "탭/줄바꿈이 토큰 안에 삽입됨"
        } else if self.inside.contains(&"ctrl") {
            "제어 요소가 토큰 사이에 끼임"
        } else if self.inside.contains(&"struct") {
            "비텍스트 구조 요소(표·그림 등)가 토큰 사이에 끼임"
        } else if self.char_prs.len() > 1 {
            "혼합 서식(charPrIDRef 상이)"
        } else if self.runs.len() > 1 && self.char_prs.contains(&None) {
            "토큰이 파편에 걸침(charPrIDRef 없음)"
        } else if !self.contiguous {
            "런 경계가 비연속"
        } else {
            "복합 런(수동 처리)"
        }
    }
}

fn coverage<'v>(
    view: &'v XmlView,
    model: &ParagraphModel,
    start: usize,
    end: usize,
) -> Option<Coverage<'v>> {
    let covered: Vec<_> = model
        .pieces
        .iter()
        .filter(|piece| piece.start < end && piece.end > start)
        .collect();
    if covered.is_empty() {
        return None;
    }
    let inside = model
        .events
        .iter()
        .filter(|(at, _)| start <= *at && *at < end)
        .map(|(_, kind)| *kind)
        .collect();
    let mut runs = Vec::new();
    let mut indexes = Vec::new();
    for piece in &covered {
        if !runs.contains(&piece.run) {
            runs.push(piece.run);
        }
        if !indexes.contains(&piece.child_index) {
            indexes.push(piece.child_index);
        }
    }
    let char_prs = runs
        .iter()
        .map(|run| view.attr(*run, "charPrIDRef"))
        .collect();
    Some(Coverage {
        inside,
        runs,
        char_prs,
        contiguous: indexes.windows(2).all(|pair| pair[1] == pair[0] + 1),
        all_simple: covered.iter().all(|piece| piece.simple),
    })
}

/// Openers with no complete token, reported as fragments.
fn fragment_sites(model: &ParagraphModel, context: &str, location: (&str, &str)) -> Vec<TokenSite> {
    let complete: HashSet<_> = token_matches(&model.text, true)
        .into_iter()
        .map(|matched| matched.byte_start)
        .collect();
    model
        .text
        .match_indices("{{")
        .filter(|(opener, _)| !complete.contains(opener))
        .map(|(opener, _)| {
            site(
                trim_python(&model.text[opener..])
                    .chars()
                    .take(40)
                    .collect(),
                context,
                false,
                "토큰이 파편에 걸침",
                location,
                -1,
                -1,
            )
        })
        .collect()
}

fn classify_composite(
    view: &XmlView,
    model: &ParagraphModel,
    context: &str,
    entry: &str,
    path: &str,
    compiled: &mut Vec<TokenSite>,
    skipped: &mut Vec<TokenSite>,
) {
    for matched in token_matches(&model.text, false) {
        let Some(coverage) = coverage(view, model, matched.start, matched.end) else {
            continue;
        };
        let clean = coverage.clean(view);
        if clean && coverage.all_simple {
            continue;
        }
        let reason = if clean { "" } else { coverage.refusal() };
        let mut found = site(
            matched.name,
            context,
            clean,
            reason,
            (entry, path),
            matched.start as isize,
            matched.end as isize,
        );
        found.literal = Some(matched.literal);
        if clean {
            compiled.push(found);
        } else {
            skipped.push(found);
        }
    }
    skipped.extend(fragment_sites(model, context, (entry, path)));
}

/// The text of a simple run joined with following simple runs of the same format,
/// and the index just past the group.
fn simple_run_group(
    view: &XmlView,
    children: &[Option<NodeId>],
    index: usize,
    text: String,
) -> (String, usize) {
    let mut group_text = text;
    let mut next = index + 1;
    let Some(char_pr) = children[index].and_then(|run| view.attr(run, "charPrIDRef")) else {
        return (group_text, next);
    };
    while next < children.len() {
        let Some(candidate) = children[next] else {
            break;
        };
        if local(view, candidate) != "run" {
            break;
        }
        let Some((_, candidate_text)) = simple_text(view, candidate) else {
            break;
        };
        if candidate_text.is_empty() || view.attr(candidate, "charPrIDRef") != Some(char_pr) {
            break;
        }
        group_text.push_str(&candidate_text);
        next += 1;
    }
    (group_text, next)
}

/// How a run's controls change the field nesting depth.
fn field_depth_change(view: &XmlView, run: NodeId) -> i32 {
    element_children(view, run)
        .filter(|child| local(view, *child) == "ctrl")
        .flat_map(|child| element_children(view, child))
        .map(|control| match local(view, control) {
            "fieldBegin" => 1,
            "fieldEnd" => -1,
            _ => 0,
        })
        .sum()
}

fn scan_paragraph(
    view: &XmlView,
    paragraph: NodeId,
    entry: &str,
    path: &str,
    compiled: &mut Vec<TokenSite>,
    skipped: &mut Vec<TokenSite>,
) {
    let context = paragraph_context(view, paragraph);
    let model = paragraph_model(view, paragraph);
    let children: Vec<_> = node_children(view, paragraph).collect();
    let mut depth = 0i32;
    let mut index = 0;
    while index < children.len() {
        let Some(run) = children[index].filter(|run| local(view, *run) == "run") else {
            index += 1;
            continue;
        };
        if let Some((_, text)) = simple_text(view, run)
            && depth == 0
            && !text.is_empty()
        {
            let (group_text, next) = simple_run_group(view, &children, index, text);
            let base = model.run_base[&run];
            for matched in token_matches(&group_text, false) {
                let mut found = site(
                    matched.name,
                    &context,
                    true,
                    "",
                    (entry, path),
                    (base + matched.start) as isize,
                    (base + matched.end) as isize,
                );
                found.literal = Some(matched.literal);
                compiled.push(found);
            }
            index = next;
            continue;
        }
        depth += field_depth_change(view, run);
        index += 1;
    }
    classify_composite(view, &model, &context, entry, path, compiled, skipped);
}

fn scan_entry_tokens(name: &str, source: &[u8]) -> Result<Vec<TokenSite>, TokenScanError> {
    let view = XmlView::parse(source)?;
    let mut compiled = Vec::new();
    let mut skipped = Vec::new();
    for paragraph in view.descendants(view.root()).unwrap() {
        if view.node(paragraph).unwrap().name.is(HP_NS, "p") {
            let path = view.path(paragraph).unwrap();
            scan_paragraph(&view, paragraph, name, &path, &mut compiled, &mut skipped);
        }
    }
    compiled.extend(skipped);
    Ok(compiled)
}

/// Inspect every HWPX content XML in package order without modifying the package.
pub fn scan_tokens(package: &HwpxPackage) -> Result<Vec<TokenSite>, TokenScanError> {
    let mut sites = Vec::new();
    for name in package.content_xml_names() {
        let source = package
            .entries
            .iter()
            .find(|item| item.name == name)
            .unwrap();
        sites.extend(scan_entry_tokens(name, &source.data)?);
    }
    Ok(sites)
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CompileReport {
    pub compiled: Vec<String>,
    pub skipped: Vec<TokenSite>,
    pub modified: bool,
}

/// Compile every eligible token, or one scanner coordinate, without writing to the filesystem.
/// Candidate XML bytes are staged until all selected entries succeed.
pub fn compile_document(
    package: &mut HwpxPackage,
    only: Option<(&str, &str, isize)>,
) -> Result<CompileReport, TokenScanError> {
    let names: Vec<_> = package
        .content_xml_names()
        .into_iter()
        .map(str::to_owned)
        .collect();
    let mut report = CompileReport::default();
    let mut replacements = Vec::new();
    for name in names {
        if only.is_some_and(|(wanted, _, _)| wanted != name) {
            continue;
        }
        let index = package
            .entries
            .iter()
            .position(|entry| entry.name == name)
            .unwrap();
        let source = &package.entries[index].data;
        let initial = scan_entry_tokens(&name, source)?;
        let selected: Vec<_> = initial
            .iter()
            .filter(|site| {
                site.compilable
                    && only.is_none_or(|(_, path, start)| {
                        site.paragraph_path == path && site.start == start
                    })
            })
            .take(if only.is_some() { 1 } else { usize::MAX })
            .cloned()
            .collect();
        let edits: Vec<_> = selected
            .iter()
            .map(|site| {
                Ok(TokenFieldEdit {
                    paragraph_path: &site.paragraph_path,
                    start: site.start as usize,
                    end: site.end as usize,
                    literal: site
                        .literal
                        .as_deref()
                        .ok_or_else(|| TokenScanError("missing complete token literal".into()))?,
                    name: &site.name,
                })
            })
            .collect::<Result<_, TokenScanError>>()?;
        let (sites, replacement) = if edits.is_empty() {
            (initial, None)
        } else {
            let data = compile_field_tokens(source, &edits)
                .map_err(|error| TokenScanError(error.to_string()))?;
            (scan_entry_tokens(&name, &data)?, Some(data))
        };
        report
            .compiled
            .extend(selected.into_iter().map(|site| site.name));
        report.skipped.extend(
            sites
                .into_iter()
                .filter(|site| {
                    !site.compilable && only.is_none_or(|(_, path, _)| site.paragraph_path == path)
                })
                .map(|mut site| {
                    site.entry.clear();
                    site.paragraph_path.clear();
                    site
                }),
        );
        if let Some(data) = replacement {
            replacements.push((index, data));
        }
    }
    for (index, data) in replacements {
        package.entries[index].data = data;
    }
    report.modified = !report.compiled.is_empty();
    Ok(report)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::fields::FieldDocument;
    use hwpx_core::package::PackageEntry;

    fn package(xml: &str) -> HwpxPackage {
        HwpxPackage {
            entries: vec![PackageEntry {
                name: "Contents/section0.xml".into(),
                data: xml.as_bytes().to_vec(),
                stored: false,
            }],
        }
    }

    fn marker_fragments(package: &HwpxPackage) -> Vec<String> {
        let view = XmlView::parse(&package.entries[0].data).unwrap();
        view.descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| {
                view.node(*id).unwrap().name.is(HP_NS, "p")
                    && !crate::structure_scan::iter_structure_markers(&paragraph_model_text(
                        &view, *id,
                    ))
                    .is_empty()
            })
            .map(|id| view.fragment_xml(id).unwrap().unwrap())
            .collect()
    }

    #[test]
    fn token_scan_keeps_field_depth_composite_reason_and_scalar_offsets() {
        let xml = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns:hp='{HP_NS}'><hp:p><hp:run charPrIDRef='7'><hp:t>🙂{{{{가</hp:t></hp:run><hp:run charPrIDRef='7'><hp:t>나}}}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:ctrl><hp:fieldBegin name='X'/></hp:ctrl></hp:run><hp:run><hp:t>{{{{X}}}}</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p><hp:p><hp:run charPrIDRef='1'><hp:t>{{{{혼</hp:t></hp:run><hp:run charPrIDRef='2'><hp:t>합}}}}</hp:t></hp:run></hp:p></hs:sec>"
        );
        let package = package(&xml);
        let before = package.clone();
        let sites = scan_tokens(&package).unwrap();
        assert_eq!(package, before);
        assert_eq!(sites.len(), 2);
        assert_eq!(
            (
                &*sites[0].name,
                sites[0].compilable,
                sites[0].start,
                sites[0].end
            ),
            ("가나", true, 1, 7)
        );
        assert_eq!(sites[0].paragraph_path, "/hs:sec/hp:p[1]");
        assert_eq!((&*sites[1].name, sites[1].compilable), ("혼합", false));
        assert!(sites[1].reason.contains("혼합 서식"));
        assert_eq!(sites[1].paragraph_path, "/hs:sec/hp:p[3]");
    }

    #[test]
    fn token_scan_reports_inline_and_partial_tokens_after_compilable_sites() {
        let xml = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns='{HP_NS}'><p><run><t>{{{{#항목 A}}}}</t></run></p><p><run><t>앞 {{{{열<tab/>림}}}} 뒤</t></run></p><p><run><t>{{{{미완성</t></run></p><p><run><t>{{{{정상}}}}</t></run></p></hs:sec>"
        );
        let sites = scan_tokens(&package(&xml)).unwrap();
        assert_eq!(sites.len(), 3);
        assert_eq!((&*sites[0].name, sites[0].compilable), ("정상", true));
        assert_eq!(sites[0].paragraph_path, "/hs:sec/*[4]");
        assert_eq!((&*sites[1].name, sites[1].compilable), ("열\t림", false));
        assert!(sites[1].reason.contains("탭/줄바꿈"));
        assert_eq!(sites[1].paragraph_path, "/hs:sec/*[2]");
        assert_eq!(
            (&*sites[2].name, sites[2].start, sites[2].end),
            ("{{미완성", -1, -1)
        );
    }

    #[test]
    fn compile_document_preserves_other_entries_and_is_idempotent() {
        let xml = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>{{{{#항목 특약 제목}}}}</hp:t></hp:run></hp:p><hp:p><hp:run charPrIDRef='7'><hp:t>앞 {{{{A}}}} / {{{{B}}}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>{{{{/항목}}}}</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = self::package(&xml);
        let before_markers = marker_fragments(&package);
        assert_eq!(before_markers.len(), 2);
        let before_text = hwpx_core::text_extract::full_text(
            &hwpx_core::text_extract::extract_document(&package, None).unwrap(),
        );
        package.entries.push(PackageEntry {
            name: "BinData/keep.bin".into(),
            data: vec![0, 1, 2],
            stored: true,
        });
        let before_asset = package.entries[1].clone();
        let report = compile_document(&mut package, None).unwrap();
        assert_eq!(report.compiled, ["A", "B"]);
        assert!(report.skipped.is_empty() && report.modified);
        assert_eq!(package.entries[1], before_asset);
        assert_eq!(marker_fragments(&package), before_markers);
        assert_eq!(
            hwpx_core::text_extract::full_text(
                &hwpx_core::text_extract::extract_document(&package, None).unwrap()
            ),
            before_text
        );
        let view = XmlView::parse(&package.entries[0].data).unwrap();
        let names: Vec<_> = view
            .descendants(view.root())
            .unwrap()
            .into_iter()
            .filter(|id| view.node(*id).unwrap().name.is(HP_NS, "fieldBegin"))
            .map(|id| view.attr(id, "name").unwrap())
            .collect();
        assert_eq!(names, ["A", "B"]);
        assert!(
            scan_tokens(&package)
                .unwrap()
                .iter()
                .all(|site| !site.compilable)
        );
        let compiled = package.clone();
        let second = compile_document(&mut package, None).unwrap();
        assert!(!second.modified);
        assert_eq!(package, compiled);
    }

    #[test]
    fn composite_token_keeps_leading_tab_and_empty_markers_outside_filled_value() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run charPrIDRef='7'><hp:tab/><hp:t marker='BEFORE'/><hp:t>{{{{계약명}}}}</hp:t><hp:t marker='AFTER'/></hp:run><hp:linesegarray/></hp:p></hs:sec>"
        );
        let mut package = self::package(&xml);
        package.entries.push(PackageEntry {
            name: "Contents/section1.xml".into(),
            data: format!("<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>토큰 없음</hp:t></hp:run><hp:linesegarray/></hp:p></hs:sec>").into_bytes(),
            stored: false,
        });
        let untouched = package.entries[1].clone();
        let report = compile_document(&mut package, None).unwrap();
        assert_eq!(report.compiled, ["계약명"]);
        assert!(!String::from_utf8_lossy(&package.entries[0].data).contains("linesegarray"));
        assert_eq!(package.entries[1], untouched);
        let view = XmlView::parse(&package.entries[0].data).unwrap();
        let nodes = view.descendants(view.root()).unwrap();
        let tab = nodes
            .iter()
            .position(|id| view.node(*id).unwrap().name.is(HP_NS, "tab"))
            .unwrap();
        let marker = nodes
            .iter()
            .position(|id| view.attr(*id, "marker") == Some("BEFORE"))
            .unwrap();
        let begin = nodes
            .iter()
            .position(|id| view.node(*id).unwrap().name.is(HP_NS, "fieldBegin"))
            .unwrap();
        assert!(tab < marker && marker < begin);
        let mut field = FieldDocument::new(&mut package, "Contents/section0.xml").unwrap();
        assert!(field.set_field("계약명", "정보시스템 구축").unwrap());
        assert_eq!(
            field.read_field("계약명").unwrap().as_deref(),
            Some("정보시스템 구축")
        );
        let filled = XmlView::parse(&package.entries[0].data).unwrap();
        let nodes = filled.descendants(filled.root()).unwrap();
        for name in ["BEFORE", "AFTER"] {
            let marker = nodes
                .iter()
                .find(|id| filled.attr(**id, "marker") == Some(name))
                .unwrap();
            assert!(filled.node(*marker).unwrap().children.is_empty());
        }
        assert!(
            nodes
                .iter()
                .any(|id| filled.node(*id).unwrap().name.is(HP_NS, "tab"))
        );
    }

    #[test]
    fn selected_token_and_later_failure_leave_unselected_bytes_unchanged() {
        let xml = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>{{{{A}}}}</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>{{{{B}}}}</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = self::package(&xml);
        let site = scan_tokens(&package)
            .unwrap()
            .into_iter()
            .find(|site| site.name == "B")
            .unwrap();
        let report = compile_document(
            &mut package,
            Some((&site.entry, &site.paragraph_path, site.start)),
        )
        .unwrap();
        assert_eq!(report.compiled, ["B"]);
        assert_eq!(
            scan_tokens(&package)
                .unwrap()
                .into_iter()
                .filter(|site| site.compilable)
                .map(|site| site.name)
                .collect::<Vec<_>>(),
            ["A"]
        );
        let selected = package.clone();
        assert!(
            !compile_document(&mut package, Some((&site.entry, "/missing", 0)))
                .unwrap()
                .modified
        );
        assert_eq!(package, selected);

        let bad = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t id='--1'>{{{{C}}}}</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = self::package(&xml);
        package.entries.push(PackageEntry {
            name: "Contents/section1.xml".into(),
            data: bad.into_bytes(),
            stored: false,
        });
        let before = package.clone();
        assert!(compile_document(&mut package, None).is_err());
        assert_eq!(package, before);
    }
}
