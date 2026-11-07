//! Guarded cross-document native XML transfer primitives.

use crate::bookmark_region::{BookmarkRegion, resolve_bookmark_topology};
use crate::field_occurrence::resolve_field_occurrences;
use crate::lineseg::serialize_modified_section;
use crate::package::HwpxPackage;
use crate::text_extract::decimal_digit;
use crate::text_model::HP_NS;
use crate::xml_dom::{Attribute, Content, Name, NodeId, XmlDocument, parse_xml};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeTransferError {
    pub code: &'static str,
    pub message: String,
}
impl fmt::Display for NativeTransferError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for NativeTransferError {}
fn fail(code: &'static str, message: impl Into<String>) -> NativeTransferError {
    NativeTransferError {
        code,
        message: message.into(),
    }
}
fn native(doc: &XmlDocument, id: NodeId, local: &str) -> bool {
    doc.node(id).name.is(HP_NS, local)
}
fn entry<'a>(package: &'a HwpxPackage, name: &str) -> Result<&'a [u8], NativeTransferError> {
    package
        .entries
        .iter()
        .find(|item| item.name == name)
        .map(|item| item.data.as_slice())
        .ok_or_else(|| fail("missing-entry", format!("missing XML entry: {name}")))
}

fn in_scope(doc: &XmlDocument, id: NodeId) -> Vec<(String, String)> {
    let mut chain = Vec::new();
    let mut cursor = Some(id);
    while let Some(at) = cursor {
        chain.push(at);
        cursor = doc.parent(at);
    }
    let mut scope = BTreeMap::new();
    for at in chain.into_iter().rev() {
        for (prefix, uri) in &doc.node(at).namespaces {
            scope.insert(prefix.clone(), uri.clone());
        }
    }
    scope.into_iter().collect()
}
fn import_subtree(target: &mut XmlDocument, source: &XmlDocument, id: NodeId) -> NodeId {
    let node = source.node(id).clone();
    let copy = target.new_element(node.name, node.attributes);
    target.node_mut(copy).namespaces = in_scope(source, id);
    for item in node.children {
        let child = match item {
            Content::Element(child) => {
                let cloned = import_subtree(target, source, child);
                target.node_mut(cloned).parent = Some(copy);
                Content::Element(cloned)
            }
            other => other,
        };
        target.node_mut(copy).children.push(child);
    }
    copy
}
fn native_run(target: &mut XmlDocument, source: &XmlDocument, source_run: NodeId) -> NodeId {
    let mut scope = in_scope(source, source_run);
    let mut prefix = "hfxfer".to_owned();
    while scope.iter().any(|(key, _)| key == &prefix) {
        prefix.push('x');
    }
    scope.push((prefix.clone(), HP_NS.into()));
    let run = target.new_element(
        Name {
            raw: format!("{prefix}:run"),
            namespace: HP_NS.into(),
            local: "run".into(),
        },
        source.node(source_run).attributes.clone(),
    );
    target.node_mut(run).namespaces = scope;
    run
}
fn set_attr(doc: &mut XmlDocument, id: NodeId, local: &str, value: &str) {
    if let Some(attr) = doc
        .node_mut(id)
        .attributes
        .iter_mut()
        .find(|item| item.name.namespace.is_empty() && item.name.local == local)
    {
        attr.value = value.into();
    } else {
        doc.node_mut(id).attributes.push(Attribute {
            name: Name {
                raw: local.into(),
                namespace: String::new(),
                local: local.into(),
            },
            value: value.into(),
        });
    }
}
fn decimal(value: &str) -> Option<String> {
    if value.is_empty() {
        return None;
    }
    let normalized = value
        .chars()
        .map(decimal_digit)
        .collect::<Option<Vec<_>>>()?;
    let digits = normalized
        .into_iter()
        .map(|digit| char::from(b'0' + digit as u8))
        .collect::<String>();
    let trimmed = digits.trim_start_matches('0');
    Some(if trimmed.is_empty() {
        "0".into()
    } else {
        trimmed.into()
    })
}
fn add_one(value: &str) -> String {
    let mut bytes = value.as_bytes().to_vec();
    for at in (0..bytes.len()).rev() {
        if bytes[at] < b'9' {
            bytes[at] += 1;
            return String::from_utf8(bytes).unwrap();
        }
        bytes[at] = b'0';
    }
    format!("1{}", String::from_utf8(bytes).unwrap())
}
pub(crate) fn next_native_id(package: &HwpxPackage) -> Result<String, NativeTransferError> {
    let mut maximum = "0".to_owned();
    for item in &package.entries {
        if !item.name.ends_with(".xml") {
            continue;
        }
        let doc = parse_xml(&item.data).map_err(|error| fail("invalid-xml", error.to_string()))?;
        for node in doc.descendants(doc.root) {
            for key in ["id", "fieldid"] {
                if let Some(value) = doc.attr(node, key).and_then(decimal)
                    && (value.len() > maximum.len()
                        || (value.len() == maximum.len() && value > maximum))
                {
                    maximum = value;
                }
            }
        }
    }
    Ok(add_one(&maximum))
}
fn split_char(text: &str, at: usize) -> Option<usize> {
    if at == text.chars().count() {
        return Some(text.len());
    }
    text.char_indices().nth(at).map(|(byte, _)| byte)
}
fn child_element(doc: &XmlDocument, id: NodeId, local: &str) -> Option<NodeId> {
    let children = doc.elements(id).collect::<Vec<_>>();
    (children.len() == 1 && native(doc, children[0], local)).then_some(children[0])
}
fn selected_texts(
    source: &XmlDocument,
    occ: &crate::field_occurrence::FieldOccurrence,
) -> Result<Vec<NodeId>, NativeTransferError> {
    let runs = source
        .elements(occ.paragraph)
        .filter(|id| native(source, *id, "run"))
        .collect::<Vec<_>>();
    let first = runs
        .iter()
        .position(|id| *id == occ.begin_run)
        .ok_or_else(|| fail("source-control", "missing begin run"))?;
    let last = runs
        .iter()
        .position(|id| *id == occ.end_run)
        .ok_or_else(|| fail("source-control", "missing end run"))?;
    let mut texts = Vec::new();
    for run in &runs[first..=last] {
        let children = &source.node(*run).children;
        let lower = if *run == occ.begin_run {
            children
                .iter()
                .position(|item| matches!(item,Content::Element(id) if *id==occ.begin_ctrl))
                .ok_or_else(|| fail("source-control", "missing begin control"))?
                + 1
        } else {
            0
        };
        let upper = if *run == occ.end_run {
            children
                .iter()
                .position(|item| matches!(item,Content::Element(id) if *id==occ.end_ctrl))
                .ok_or_else(|| fail("source-control", "missing end control"))?
        } else {
            children.len()
        };
        for item in &children[lower..upper] {
            match item {
                Content::Element(id)
                    if native(source, *id, "t")
                        && !source.node(*id).children.iter().any(|part| {
                            matches!(
                                part,
                                Content::Element(_)
                                    | Content::Comment(_)
                                    | Content::ProcessingInstruction(_)
                            )
                        }) =>
                {
                    texts.push(*id)
                }
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_) => {
                    return Err(fail(
                        "source-control",
                        "unsupported content in source Field",
                    ));
                }
                Content::Text(_) | Content::CData(_) => {}
            }
        }
    }
    if texts != occ.texts {
        return Err(fail(
            "source-coverage",
            "source Field content differs from resolved text",
        ));
    }
    Ok(texts)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FieldPasteResult {
    pub previous: String,
    pub inserted: String,
}
pub struct FieldPasteRequest<'a> {
    pub source_entry: &'a str,
    pub source_ordinal: usize,
    pub source_pairing_id: Option<&'a str>,
    pub target_entry: &'a str,
    pub target_paragraph: usize,
    pub start: usize,
    pub end: usize,
    pub with_meaning: bool,
}
/// Copy a complete source Field value (and optionally its native controls) into one simple target paragraph.
/// The target entry commits only after candidate reparsing and Field pairing checks succeed.
pub fn paste_field(
    source: &HwpxPackage,
    target: &mut HwpxPackage,
    request: &FieldPasteRequest<'_>,
) -> Result<FieldPasteResult, NativeTransferError> {
    let source_doc = parse_xml(entry(source, request.source_entry)?)
        .map_err(|error| fail("invalid-xml", error.to_string()))?;
    let resolved = resolve_field_occurrences(request.source_entry, &source_doc);
    if !resolved.diagnostics.is_empty() {
        return Err(fail("source-pairing", "source Field pairing is unusable"));
    }
    let occurrence = resolved
        .occurrences
        .get(request.source_ordinal)
        .ok_or_else(|| fail("source-ordinal", "source Field ordinal missing"))?;
    if source_doc.attr(occurrence.begin, "id") != request.source_pairing_id {
        return Err(fail(
            "source-pairing-changed",
            "source Field pairing changed",
        ));
    }
    if occurrence
        .raw_name
        .as_deref()
        .is_none_or(|name| name.trim().is_empty())
    {
        return Err(fail("source-name", "source Field name missing"));
    }
    let texts = selected_texts(&source_doc, occurrence)?;
    let copied = texts
        .iter()
        .map(|id| source_doc.direct_text(*id))
        .collect::<String>();
    let next = if request.with_meaning {
        Some(next_native_id(target)?)
    } else {
        None
    };
    let second = next.as_deref().map(add_one);
    let mut candidate = parse_xml(entry(target, request.target_entry)?)
        .map_err(|error| fail("invalid-xml", error.to_string()))?;
    let paragraphs = candidate
        .elements(candidate.root)
        .filter(|id| native(&candidate, *id, "p"))
        .collect::<Vec<_>>();
    let paragraph = *paragraphs
        .get(request.target_paragraph)
        .ok_or_else(|| fail("target-paragraph", "target paragraph missing"))?;
    if request.start > request.end {
        return Err(fail("target-range", "invalid target range"));
    }
    let runs = candidate
        .elements(paragraph)
        .filter(|id| native(&candidate, *id, "run"))
        .collect::<Vec<_>>();
    let run = if runs.len() == 1 {
        runs[0]
    } else {
        return Err(fail("target-complex", "target paragraph is complex"));
    };
    let text_id = child_element(&candidate, run, "t")
        .ok_or_else(|| fail("target-complex", "target paragraph is complex"))?;
    if candidate.node(text_id).children.iter().any(|part| {
        matches!(
            part,
            Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
        )
    }) {
        return Err(fail("target-complex", "target paragraph is complex"));
    }
    let original = candidate.direct_text(text_id);
    let left = split_char(&original, request.start)
        .ok_or_else(|| fail("target-outside", "target range outside paragraph"))?;
    let right = split_char(&original, request.end)
        .ok_or_else(|| fail("target-outside", "target range outside paragraph"))?;
    let mut new_runs = Vec::new();
    if left != 0 {
        let prefix = candidate.clone_subtree(run);
        let t = child_element(&candidate, prefix, "t").unwrap();
        candidate.node_mut(t).children = vec![Content::Text(original[..left].into())];
        new_runs.push(prefix);
    }
    if let Some(next) = &next {
        let begin = native_run(&mut candidate, &source_doc, occurrence.begin_run);
        let ctrl = import_subtree(&mut candidate, &source_doc, occurrence.begin_ctrl);
        let marker = child_element(&candidate, ctrl, "fieldBegin")
            .ok_or_else(|| fail("source-control", "invalid begin control"))?;
        set_attr(&mut candidate, marker, "id", next);
        set_attr(
            &mut candidate,
            marker,
            "fieldid",
            second.as_deref().unwrap(),
        );
        candidate
            .insert_element(begin, 0, ctrl)
            .map_err(|error| fail("write", error.to_string()))?;
        new_runs.push(begin);
    }
    for text in texts {
        let source_run = source_doc
            .parent(text)
            .ok_or_else(|| fail("source-control", "missing source text run"))?;
        let fresh = native_run(&mut candidate, &source_doc, source_run);
        let cloned = import_subtree(&mut candidate, &source_doc, text);
        candidate
            .insert_element(fresh, 0, cloned)
            .map_err(|error| fail("write", error.to_string()))?;
        new_runs.push(fresh);
    }
    if let Some(next) = &next {
        let end = native_run(&mut candidate, &source_doc, occurrence.end_run);
        let ctrl = import_subtree(&mut candidate, &source_doc, occurrence.end_ctrl);
        let marker = child_element(&candidate, ctrl, "fieldEnd")
            .ok_or_else(|| fail("source-control", "invalid end control"))?;
        set_attr(&mut candidate, marker, "beginIDRef", next);
        set_attr(
            &mut candidate,
            marker,
            "fieldid",
            second.as_deref().unwrap(),
        );
        candidate
            .insert_element(end, 0, ctrl)
            .map_err(|error| fail("write", error.to_string()))?;
        new_runs.push(end);
    }
    if right < original.len() {
        let suffix = candidate.clone_subtree(run);
        let t = child_element(&candidate, suffix, "t").unwrap();
        candidate.node_mut(t).children = vec![Content::Text(original[right..].into())];
        new_runs.push(suffix);
    }
    let position = candidate
        .node(paragraph)
        .children
        .iter()
        .position(|part| matches!(part,Content::Element(id) if *id==run))
        .ok_or_else(|| fail("write", "target run detached"))?;
    candidate
        .remove_element_with_tail(run)
        .map_err(|error| fail("write", error.to_string()))?;
    for (offset, fresh) in new_runs.into_iter().enumerate() {
        candidate
            .insert_element(paragraph, position + offset, fresh)
            .map_err(|error| fail("write", error.to_string()))?;
    }
    let bytes = serialize_modified_section(&mut candidate)
        .map_err(|error| fail("write", error.to_string()))?;
    let checked = parse_xml(&bytes).map_err(|error| fail("write", error.to_string()))?;
    if !resolve_field_occurrences(request.target_entry, &checked)
        .diagnostics
        .is_empty()
    {
        return Err(fail(
            "target-pairing",
            "target Field pairing became unusable",
        ));
    }
    let slot = target
        .entries
        .iter_mut()
        .find(|item| item.name == request.target_entry)
        .ok_or_else(|| fail("missing-entry", "target entry disappeared"))?;
    slot.data = bytes;
    Ok(FieldPasteResult {
        previous: original[left..right].into(),
        inserted: copied,
    })
}

/// Product callers supply exact replacement names and metaTag texts; the core only
/// transfers native BOOKMARK controls and validates their resulting topology.
#[derive(Clone, Debug)]
pub struct BookmarkNameEdit {
    pub source_pairing_id: String,
    pub new_name: String,
    pub metatag_texts: Vec<String>,
}
pub struct BookmarkPasteRequest<'a> {
    pub source_region: &'a BookmarkRegion,
    pub target_entry: &'a str,
    pub destination_paragraph: usize,
    pub with_meaning: bool,
    pub name_edits: &'a [BookmarkNameEdit],
}
fn initial_text(doc: &XmlDocument, id: NodeId) -> String {
    doc.node(id)
        .children
        .iter()
        .take_while(|item| matches!(item, Content::Text(_) | Content::CData(_)))
        .map(|item| match item {
            Content::Text(text) | Content::CData(text) => text.as_str(),
            _ => unreachable!(),
        })
        .collect()
}
fn has_text(doc: &XmlDocument, nodes: &[NodeId]) -> bool {
    nodes
        .iter()
        .any(|id| native(doc, *id, "t") && !initial_text(doc, *id).is_empty())
}
fn block_controls_complete(
    doc: &XmlDocument,
    block: &[NodeId],
    region: &BookmarkRegion,
) -> Result<(), NativeTransferError> {
    let first = doc.descendants(block[0]);
    let last = doc.descendants(*block.last().unwrap());
    let begin = first
        .iter()
        .position(|id| {
            native(doc, *id, "fieldBegin") && doc.attr(*id, "id") == Some(region.pairing_id())
        })
        .ok_or_else(|| fail("partial-boundary", "region begin is not in first paragraph"))?;
    let end = last
        .iter()
        .position(|id| {
            native(doc, *id, "fieldEnd") && doc.attr(*id, "beginIDRef") == Some(region.pairing_id())
        })
        .ok_or_else(|| fail("partial-boundary", "region end is not in last paragraph"))?;
    if has_text(doc, &first[..begin]) || has_text(doc, &last[end + 1..]) {
        return Err(fail(
            "partial-content",
            "region boundaries exclude paragraph text",
        ));
    }
    Ok(())
}
fn supported_paragraph(doc: &XmlDocument, paragraph: NodeId) -> Result<(), NativeTransferError> {
    for item in &doc.node(paragraph).children {
        let child = match item {
            Content::Element(id) => *id,
            Content::Comment(_) | Content::ProcessingInstruction(_) => {
                return Err(fail("complex-paragraph", "unsupported paragraph child"));
            }
            Content::Text(_) | Content::CData(_) => continue,
        };
        if native(doc, child, "lineSegArray") {
            continue;
        }
        if !native(doc, child, "run") {
            return Err(fail("complex-paragraph", "unsupported paragraph child"));
        }
        for part in &doc.node(child).children {
            let id = match part {
                Content::Element(id) => *id,
                Content::Comment(_) | Content::ProcessingInstruction(_) => {
                    return Err(fail("complex-paragraph", "unsupported run child"));
                }
                Content::Text(_) | Content::CData(_) => continue,
            };
            if !native(doc, id, "t") && !native(doc, id, "ctrl") {
                return Err(fail("complex-paragraph", "unsupported run child"));
            }
        }
        for id in doc
            .descendants(child)
            .into_iter()
            .filter(|id| native(doc, *id, "ctrl"))
        {
            let children = doc
                .node(id)
                .children
                .iter()
                .filter(|part| {
                    matches!(
                        part,
                        Content::Element(_)
                            | Content::Comment(_)
                            | Content::ProcessingInstruction(_)
                    )
                })
                .collect::<Vec<_>>();
            if children.len() != 1
                || !matches!(children[0],Content::Element(marker) if native(doc,*marker,"fieldBegin") || native(doc,*marker,"fieldEnd"))
            {
                return Err(fail(
                    "unsupported-control",
                    "unsupported control in source block",
                ));
            }
        }
    }
    Ok(())
}
fn block_pairings(doc: &XmlDocument, block: &[NodeId]) -> HashSet<Option<String>> {
    let mut begins = HashSet::new();
    let mut ends = HashSet::new();
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            if native(doc, id, "fieldBegin") {
                begins.insert(doc.attr(id, "id").map(str::to_owned));
            }
            if native(doc, id, "fieldEnd") {
                ends.insert(doc.attr(id, "beginIDRef").map(str::to_owned));
            }
        }
    }
    begins.intersection(&ends).cloned().collect()
}
fn strip_external_controls(doc: &mut XmlDocument, block: &[NodeId], with_meaning: bool) {
    let internal = block_pairings(doc, block);
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            if !native(doc, id, "ctrl") {
                continue;
            }
            let Some(marker) = doc.elements(id).next() else {
                continue;
            };
            let pairing = if native(doc, marker, "fieldBegin") {
                doc.attr(marker, "id")
            } else {
                doc.attr(marker, "beginIDRef")
            }
            .map(str::to_owned);
            if !with_meaning || !internal.contains(&pairing) {
                let _ = doc.remove_element_with_tail(id);
            }
        }
    }
}
fn id_map(
    target: &HwpxPackage,
    doc: &XmlDocument,
    block: &[NodeId],
) -> Result<HashMap<String, String>, NativeTransferError> {
    let mut next = next_native_id(target)?;
    let mut mapping = HashMap::new();
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            for key in ["id", "fieldid"] {
                if let Some(old) = doc.attr(id, key)
                    && !mapping.contains_key(old)
                {
                    mapping.insert(old.to_owned(), next.clone());
                    next = add_one(&next);
                }
            }
        }
    }
    Ok(mapping)
}
fn replace_text(doc: &mut XmlDocument, id: NodeId, text: &str) {
    let node = doc.node_mut(id);
    let stop = node
        .children
        .iter()
        .position(|part| {
            matches!(
                part,
                Content::Element(_) | Content::Comment(_) | Content::ProcessingInstruction(_)
            )
        })
        .unwrap_or(node.children.len());
    node.children.drain(..stop);
    node.children.insert(0, Content::Text(text.into()));
}
fn apply_bookmark_names(
    doc: &mut XmlDocument,
    marker: NodeId,
    original: &str,
    edits: &[BookmarkNameEdit],
) -> Result<(), NativeTransferError> {
    let Some(edit) = edits.iter().find(|item| item.source_pairing_id == original) else {
        return Ok(());
    };
    set_attr(doc, marker, "name", &edit.new_name);
    let tags = doc
        .descendants(marker)
        .into_iter()
        .filter(|id| {
            native(doc, *id, "metaTag") && initial_text(doc, *id).contains("\"hwpxFiller\"")
        })
        .collect::<Vec<_>>();
    if !edit.metatag_texts.is_empty() && tags.len() != edit.metatag_texts.len() {
        return Err(fail(
            "metatag-count",
            "bookmark metaTag replacement count mismatch",
        ));
    }
    for (id, text) in tags.into_iter().zip(&edit.metatag_texts) {
        replace_text(doc, id, text);
    }
    Ok(())
}
fn remap_block(
    doc: &mut XmlDocument,
    block: &[NodeId],
    mapping: &HashMap<String, String>,
    edits: &[BookmarkNameEdit],
) -> Result<(), NativeTransferError> {
    for paragraph in block {
        for id in doc.descendants(*paragraph) {
            let original =
                if native(doc, id, "fieldBegin") && doc.attr(id, "type") == Some("BOOKMARK") {
                    doc.attr(id, "id").map(str::to_owned)
                } else {
                    None
                };
            for key in ["id", "fieldid", "beginIDRef", "endIDRef"] {
                if let Some(old) = doc.attr(id, key).map(str::to_owned)
                    && let Some(new) = mapping.get(&old)
                {
                    set_attr(doc, id, key, new);
                }
            }
            if let Some(old) = original {
                apply_bookmark_names(doc, id, &old, edits)?;
            }
        }
    }
    Ok(())
}
fn paragraph_plain(doc: &XmlDocument, id: NodeId) -> String {
    doc.descendants(id)
        .into_iter()
        .filter(|id| native(doc, *id, "t"))
        .map(|id| initial_text(doc, id))
        .collect()
}
fn paragraph_tail(doc: &XmlDocument, id: NodeId) -> Vec<Content> {
    let Some(at) = doc
        .node(doc.root)
        .children
        .iter()
        .position(|part| matches!(part,Content::Element(child) if *child==id))
    else {
        return Vec::new();
    };
    doc.node(doc.root).children[at + 1..]
        .iter()
        .take_while(|part| matches!(part, Content::Text(_) | Content::CData(_)))
        .cloned()
        .collect()
}
/// Copy complete source paragraphs into the target section. Product name and
/// metadata edits are explicit inputs; malformed source/target structure cannot commit.
pub fn paste_bookmark_block(
    source: &HwpxPackage,
    target: &mut HwpxPackage,
    request: &BookmarkPasteRequest<'_>,
) -> Result<String, NativeTransferError> {
    let region = request.source_region;
    let current = resolve_bookmark_topology(source)
        .map_err(|error| fail("source-topology", error.to_string()))?;
    if !current.contains(region) {
        return Err(fail("stale-region", "source BOOKMARK region changed"));
    }
    let source_doc = parse_xml(entry(source, &region.section)?)
        .map_err(|error| fail("invalid-xml", error.to_string()))?;
    let source_paragraphs = source_doc
        .elements(source_doc.root)
        .filter(|id| native(&source_doc, *id, "p"))
        .collect::<Vec<_>>();
    let block = source_paragraphs
        .get(region.start_paragraph..=region.end_paragraph)
        .ok_or_else(|| fail("source-region", "source paragraph range missing"))?;
    block_controls_complete(&source_doc, block, region)?;
    for paragraph in block {
        supported_paragraph(&source_doc, *paragraph)?;
    }
    let plain = block
        .iter()
        .map(|id| paragraph_plain(&source_doc, *id))
        .collect::<Vec<_>>()
        .join("\n");
    let mut candidate = parse_xml(entry(target, request.target_entry)?)
        .map_err(|error| fail("missing-entry", error.to_string()))?;
    let target_paragraphs = candidate
        .elements(candidate.root)
        .filter(|id| native(&candidate, *id, "p"))
        .collect::<Vec<_>>();
    if target_paragraphs.is_empty() {
        return Err(fail(
            "no-target-paragraph",
            "target section has no paragraph",
        ));
    }
    if request.destination_paragraph > target_paragraphs.len() {
        return Err(fail(
            "target-boundary",
            "target paragraph boundary outside section",
        ));
    }
    let mut clones = block
        .iter()
        .map(|id| import_subtree(&mut candidate, &source_doc, *id))
        .collect::<Vec<_>>();
    strip_external_controls(&mut candidate, &clones, request.with_meaning);
    if request.with_meaning {
        let mapping = id_map(target, &candidate, &clones)?;
        remap_block(&mut candidate, &clones, &mapping, request.name_edits)?;
    }
    let insertion=if request.destination_paragraph<target_paragraphs.len() {
        candidate.node(candidate.root).children.iter().position(|part|matches!(part,Content::Element(id) if *id==target_paragraphs[request.destination_paragraph]))
    } else {
        candidate.node(candidate.root).children.iter().position(|part|matches!(part,Content::Element(id) if *id==*target_paragraphs.last().unwrap())).map(|at| {
            let children=&candidate.node(candidate.root).children;
            at+1+children[at+1..].iter().take_while(|part|matches!(part,Content::Text(_)|Content::CData(_))).count()
        })
    }.ok_or_else(||fail("target-boundary","target paragraph detached"))?;
    let mut at = insertion;
    for (source_paragraph, clone) in block.iter().zip(clones.drain(..)) {
        candidate
            .insert_element(candidate.root, at, clone)
            .map_err(|error| fail("write", error.to_string()))?;
        at += 1;
        for tail in paragraph_tail(&source_doc, *source_paragraph) {
            candidate.node_mut(candidate.root).children.insert(at, tail);
            at += 1;
        }
    }
    let bytes = serialize_modified_section(&mut candidate)
        .map_err(|error| fail("write", error.to_string()))?;
    let slot = target
        .entries
        .iter_mut()
        .find(|item| item.name == request.target_entry)
        .ok_or_else(|| fail("missing-entry", "target entry disappeared"))?;
    let previous = std::mem::replace(&mut slot.data, bytes);
    if let Err(error) = resolve_bookmark_topology(target) {
        target
            .entries
            .iter_mut()
            .find(|item| item.name == request.target_entry)
            .unwrap()
            .data = previous;
        return Err(fail("target-topology", error.to_string()));
    }
    Ok(plain)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::bookmark_region::create_bookmark_region;
    use crate::package::PackageEntry;

    fn package(xml: String) -> HwpxPackage {
        HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "BinData/p.bin".into(),
                    data: vec![9, 8],
                    stored: true,
                },
            ],
        }
    }

    #[test]
    fn field_transfer_rekeys_controls_and_preserves_source_and_other_payloads() {
        let root = |body: &str| {
            format!(
                "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p>{body}</hp:p></hs:sec>"
            )
        };
        let source = package(root(
            "<hp:run><hp:ctrl><hp:fieldBegin id='4' fieldid='5' name='A' type='CLICK_HERE'/></hp:ctrl></hp:run><hp:run><hp:t>값</hp:t></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='4' fieldid='5'/></hp:ctrl></hp:run>",
        ));
        let mut target = package(root("<hp:run><hp:t>OLD</hp:t></hp:run>"));
        let before_source = source.clone();
        let before_binary = target.entries[1].clone();
        let result = paste_field(
            &source,
            &mut target,
            &FieldPasteRequest {
                source_entry: "Contents/section0.xml",
                source_ordinal: 0,
                source_pairing_id: Some("4"),
                target_entry: "Contents/section0.xml",
                target_paragraph: 0,
                start: 1,
                end: 2,
                with_meaning: true,
            },
        )
        .unwrap();
        assert_eq!(
            result,
            FieldPasteResult {
                previous: "L".into(),
                inserted: "값".into()
            }
        );
        assert_eq!(source, before_source);
        assert_eq!(target.entries[1], before_binary);
        let doc = parse_xml(&target.entries[0].data).unwrap();
        let resolved = resolve_field_occurrences("Contents/section0.xml", &doc);
        assert!(resolved.diagnostics.is_empty());
        assert_eq!(resolved.occurrences.len(), 1);
        let item = &resolved.occurrences[0];
        assert_eq!(doc.attr(item.begin, "id"), Some("1"));
        assert_eq!(doc.attr(item.end, "beginIDRef"), Some("1"));
        assert_eq!(doc.iter_text(doc.root), "O값D");
    }

    #[test]
    fn bookmark_block_transfer_preserves_paragraph_tail_and_renames_native_pair() {
        let root = |body: &str| {
            format!(
                "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>"
            )
        };
        let p = |text: &str| format!("<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>");
        let mut source = package(root(&format!(
            "{}{}\n{}",
            p("OUT"),
            p("&#48376;&#47928;"),
            p("END")
        )));
        let region =
            create_bookmark_region(&mut source, "Contents/section0.xml", 1, 1, "S", None).unwrap();
        let mut target = package(root(&format!("{}{}", p("X"), p("Y"))));
        let original_binary = target.entries[1].clone();
        let plain = paste_bookmark_block(
            &source,
            &mut target,
            &BookmarkPasteRequest {
                source_region: &region,
                target_entry: "Contents/section0.xml",
                destination_paragraph: 1,
                with_meaning: true,
                name_edits: &[BookmarkNameEdit {
                    source_pairing_id: region.pairing_id().into(),
                    new_name: "T".into(),
                    metatag_texts: Vec::new(),
                }],
            },
        )
        .unwrap();
        assert_eq!(plain, "본문");
        assert_eq!(target.entries[1], original_binary);
        let after = resolve_bookmark_topology(&target).unwrap();
        assert_eq!(after.len(), 1);
        assert_eq!(after[0].name.as_deref(), Some("T"));
        assert_eq!((after[0].start_paragraph, after[0].end_paragraph), (1, 1));
        let doc = parse_xml(&target.entries[0].data).unwrap();
        assert_eq!(doc.iter_text(doc.root), "X본문\nY");
        let inserted = doc
            .elements(doc.root)
            .filter(|id| native(&doc, *id, "p"))
            .nth(1)
            .unwrap();
        assert!(
            paragraph_tail(&doc, inserted)
                .iter()
                .any(|item| matches!(item,Content::Text(text) if text=="\n"))
        );
        let mut marker_doc = parse_xml(root("<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='S' type='BOOKMARK'><hp:metaTag>{\"hwpxFiller\":{\"id\":\"S\"}}</hp:metaTag></hp:fieldBegin></hp:ctrl></hp:run></hp:p>").as_bytes()).unwrap();
        let marker = marker_doc
            .descendants(marker_doc.root)
            .into_iter()
            .find(|id| native(&marker_doc, *id, "fieldBegin"))
            .unwrap();
        apply_bookmark_names(
            &mut marker_doc,
            marker,
            "1",
            &[BookmarkNameEdit {
                source_pairing_id: "1".into(),
                new_name: "T".into(),
                metatag_texts: Vec::new(),
            }],
        )
        .unwrap();
        assert_eq!(marker_doc.attr(marker, "name"), Some("T"));
        assert!(marker_doc.iter_text(marker).contains("\"id\":\"S\""));
    }
}
