//! Loss-aware text projection from open HWPX packages.

use crate::package::HwpxPackage;
use crate::shape_text::{SHAPE_TAGS, shape_blocks};
use crate::text_model::{Block, Cell, CoverageLedger, Document, HP_NS, Section};
use crate::xml_dom::{Content, NodeId, XmlDocument, XmlError, parse_xml};
use std::collections::BTreeMap;
use std::str::FromStr;

pub type FieldFilter<'a> = dyn Fn(Option<&str>) -> bool + 'a;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InlineText {
    pub text: String,
    pub unmodelled: Vec<String>,
}

impl InlineText {
    pub fn exact(&self) -> bool {
        self.unmodelled.is_empty()
    }
}

pub(crate) fn classify(
    doc: &XmlDocument,
    ledger: &mut CoverageLedger,
    child: NodeId,
    handled: &[&str],
    ignored: &[&str],
    path: &str,
) -> String {
    let name = &doc.node(child).name;
    let local = name.local.clone();
    if !name.namespace.is_empty() && name.namespace != HP_NS {
        ledger.record(&name.clark(), format!("{path}/{local}"));
    } else if !handled.contains(&local.as_str()) && !ignored.contains(&local.as_str()) {
        ledger.record(&local, format!("{path}/{local}"));
    }
    local
}

pub fn decimal_digit(ch: char) -> Option<u32> {
    // Python's \d / int accept Unicode decimal digits, including mixed scripts.
    // Each Unicode Nd set has ten contiguous code points starting at zero.
    const ZERO: &[u32] = &[
        0x30, 0x660, 0x6F0, 0x7C0, 0x966, 0x9E6, 0xA66, 0xAE6, 0xB66, 0xBE6, 0xC66, 0xCE6, 0xD66,
        0xDE6, 0xE50, 0xED0, 0xF20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90,
        0x1B50, 0x1BB0, 0x1C40, 0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0,
        0xFF10, 0x104A0, 0x10D30, 0x11066, 0x110F0, 0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0,
        0x11650, 0x116C0, 0x11730, 0x118E0, 0x11950, 0x11C50, 0x11D50, 0x11DA0, 0x11F50, 0x16A60,
        0x16AC0, 0x16B50, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0, 0x1E4F0,
        0x1E950, 0x1FBF0,
    ];
    let code = ch as u32;
    let index = ZERO.partition_point(|zero| *zero <= code).checked_sub(1)?;
    let value = code - ZERO[index];
    (value < 10).then_some(value)
}

pub(crate) fn numbered_content_suffix(name: &str, prefix: &str) -> Option<String> {
    let base = name.rsplit('/').next()?.to_ascii_lowercase();
    let digits = base.strip_prefix(prefix)?.strip_suffix(".xml")?;
    if digits.is_empty() {
        return None;
    }
    let number: String = digits
        .chars()
        .map(decimal_digit)
        .collect::<Option<Vec<_>>>()?
        .into_iter()
        .map(|digit| char::from(b'0' + digit as u8))
        .collect();
    let normalized = number.trim_start_matches('0');
    Some(
        if normalized.is_empty() {
            "0"
        } else {
            normalized
        }
        .to_owned(),
    )
}

pub fn section_xml_names(package: &HwpxPackage) -> Vec<&str> {
    let mut names: Vec<_> = package
        .entries
        .iter()
        .filter_map(|entry| {
            numbered_content_suffix(&entry.name, "section")
                .map(|number| (number, entry.name.as_str()))
        })
        .collect();
    names.sort_unstable_by(|left, right| {
        left.0
            .len()
            .cmp(&right.0.len())
            .then(left.0.cmp(&right.0))
            .then(left.1.cmp(right.1))
    });
    names.into_iter().map(|(_, name)| name).collect()
}

fn header_footer_names<'a>(package: &'a HwpxPackage, prefix: &str) -> Vec<&'a str> {
    let mut names: Vec<_> = package
        .entries
        .iter()
        .filter_map(|entry| {
            let base = entry.name.rsplit('/').next()?.to_ascii_lowercase();
            (base.starts_with(prefix) && base.ends_with(".xml")).then_some(entry.name.as_str())
        })
        .collect();
    names.sort_unstable();
    names
}

fn has_body_text(doc: &XmlDocument) -> bool {
    if doc.node(doc.root).name.local == "head" {
        return false;
    }
    doc.descendants(doc.root).into_iter().any(|id| {
        if !doc.node(id).name.is(HP_NS, "t") {
            return false;
        }
        doc.node(id).children.iter().any(|part| match part {
            Content::Text(text) | Content::CData(text) => !text.trim().is_empty(),
            _ => false,
        })
    })
}

fn inline_value(node: &crate::xml_dom::Node) -> Option<&'static str> {
    if node.name.namespace != HP_NS
        || !node.children.iter().all(
            |part| matches!(part, Content::Text(text) | Content::CData(text) if text.is_empty()),
        )
    {
        return None;
    }
    match node.name.local.as_str() {
        "tab" => Some("\t"),
        "lineBreak" => Some("\n"),
        "fwSpace" => Some(" "),
        "markpenBegin" | "markpenEnd" => Some(""),
        _ => None,
    }
}

pub(crate) fn read_inline_text(doc: &XmlDocument, id: NodeId) -> InlineText {
    let mut text = String::new();
    let mut unmodelled = Vec::new();
    for part in &doc.node(id).children {
        match part {
            Content::Text(value) | Content::CData(value) => text.push_str(value),
            Content::Element(child) => {
                let node = doc.node(*child);
                if let Some(value) = inline_value(node) {
                    text.push_str(value);
                } else if node.name.namespace == HP_NS {
                    unmodelled.push(node.name.local.clone());
                } else if node.name.namespace.is_empty() {
                    unmodelled.push(format!("{{}}{}", node.name.local));
                } else {
                    unmodelled.push(node.name.clark());
                }
            }
            Content::Comment(_) | Content::ProcessingInstruction(_) => {}
        }
    }
    InlineText { text, unmodelled }
}

pub(crate) fn read_field_text(doc: &XmlDocument, texts: &[NodeId]) -> InlineText {
    let mut read = InlineText {
        text: String::new(),
        unmodelled: Vec::new(),
    };
    for id in texts {
        let part = read_inline_text(doc, *id);
        read.text.push_str(&part.text);
        read.unmodelled.extend(part.unmodelled);
    }
    read
}

fn field_label(doc: &XmlDocument, begin: NodeId, filter: Option<&FieldFilter<'_>>) -> String {
    let kind = doc.attr(begin, "type");
    if kind == Some("BOOKMARK") || filter.is_some_and(|accept| !accept(kind)) {
        return String::new();
    }
    doc.attr(begin, "name").unwrap_or("").trim().to_owned()
}

fn close_field(stack: &mut Vec<(Option<String>, String)>, begin_ref: Option<&str>) {
    if let Some(reference) = begin_ref {
        if let Some(index) = stack
            .iter()
            .rposition(|(id, _)| id.as_deref() == Some(reference))
        {
            stack.remove(index);
        }
    } else {
        stack.pop();
    }
}

fn flush(blocks: &mut Vec<Block>, text: &mut String, fields: &mut Vec<String>) {
    if !text.is_empty() {
        blocks.push(Block::Paragraph {
            text: std::mem::take(text),
            fields: std::mem::take(fields),
        });
    }
}

fn append_inline_text(
    inline: InlineText,
    ledger: &mut CoverageLedger,
    run_path: &str,
    stack: &[(Option<String>, String)],
    text: &mut String,
    fields: &mut Vec<String>,
) {
    for name in inline.unmodelled {
        let local = name.rsplit('}').next().unwrap_or(&name);
        ledger.record(&name, format!("{run_path}/t/{local}"));
    }
    if inline.text.is_empty() {
        return;
    }
    let label = stack
        .iter()
        .rev()
        .find_map(|(_, label)| (!label.is_empty()).then_some(label));
    if let Some(label) = label
        && !inline.text.trim().is_empty()
        && !fields.contains(label)
    {
        fields.push(label.clone());
    }
    text.push_str(&inline.text);
}

fn field_markers(
    doc: &XmlDocument,
    ctrl: NodeId,
    stack: &mut Vec<(Option<String>, String)>,
    filter: Option<&FieldFilter<'_>>,
) {
    for marker in doc.elements(ctrl) {
        match doc.node(marker).name.local.as_str() {
            "fieldBegin" => stack.push((
                doc.attr(marker, "id").map(str::to_owned),
                field_label(doc, marker, filter),
            )),
            "fieldEnd" => close_field(stack, doc.attr(marker, "beginIDRef")),
            _ => {}
        }
    }
}

fn append_object_blocks(
    produced: Vec<Block>,
    blocks: &mut Vec<Block>,
    text: &mut String,
    fields: &mut Vec<String>,
) {
    if !produced.is_empty() {
        flush(blocks, text, fields);
        blocks.extend(produced);
    }
}

fn object_blocks(
    doc: &XmlDocument,
    child: NodeId,
    ledger: &mut CoverageLedger,
    run_path: &str,
    filter: Option<&FieldFilter<'_>>,
) -> Vec<Block> {
    let local = doc.node(child).name.local.as_str();
    match local {
        "tbl" => table_blocks(doc, child, ledger, &format!("{run_path}/tbl"), filter),
        local if SHAPE_TAGS.contains(&local) => {
            shape_blocks(doc, child, ledger, &format!("{run_path}/{local}"), filter)
        }
        _ => Vec::new(),
    }
}

fn paragraph_blocks(
    doc: &XmlDocument,
    p: NodeId,
    ledger: &mut CoverageLedger,
    path: &str,
    filter: Option<&FieldFilter<'_>>,
) -> Vec<Block> {
    let mut blocks = Vec::new();
    let mut text = String::new();
    let mut fields = Vec::new();
    let mut stack: Vec<(Option<String>, String)> = Vec::new();
    for run in doc.elements(p) {
        if classify(doc, ledger, run, &["run"], &["linesegarray"], path) != "run" {
            continue;
        }
        let run_path = format!("{path}/run");
        for child in doc.elements(run) {
            let local = classify(
                doc,
                ledger,
                child,
                &[
                    "t",
                    "ctrl",
                    "tab",
                    "lineBreak",
                    "tbl",
                    "rect",
                    "ellipse",
                    "arc",
                    "polygon",
                    "curve",
                    "line",
                    "connectLine",
                    "container",
                    "pic",
                ],
                &["secPr"],
                &run_path,
            );
            match local.as_str() {
                "t" => append_inline_text(
                    read_inline_text(doc, child),
                    ledger,
                    &run_path,
                    &stack,
                    &mut text,
                    &mut fields,
                ),
                "ctrl" => field_markers(doc, child, &mut stack, filter),
                "tab" => text.push('\t'),
                "lineBreak" => text.push('\n'),
                _ => append_object_blocks(
                    object_blocks(doc, child, ledger, &run_path, filter),
                    &mut blocks,
                    &mut text,
                    &mut fields,
                ),
            }
        }
    }
    flush(&mut blocks, &mut text, &mut fields);
    if blocks.is_empty() {
        blocks.push(Block::Paragraph {
            text: String::new(),
            fields: Vec::new(),
        });
    }
    blocks
}

pub(crate) fn container_blocks(
    doc: &XmlDocument,
    container: NodeId,
    ledger: &mut CoverageLedger,
    path: &str,
    filter: Option<&FieldFilter<'_>>,
) -> Vec<Block> {
    let mut blocks = Vec::new();
    for child in doc.elements(container) {
        if classify(doc, ledger, child, &["p"], &[], path) == "p" {
            blocks.extend(paragraph_blocks(
                doc,
                child,
                ledger,
                &format!("{path}/p"),
                filter,
            ));
        }
    }
    blocks
}

fn cell_number(raw: &str) -> Result<Option<serde_json::Number>, ()> {
    let unsigned = raw.trim_start_matches('-');
    if unsigned.is_empty() || !unsigned.bytes().all(|byte| byte.is_ascii_digit()) {
        return Ok(None);
    }
    if raw.len() - unsigned.len() > 1 {
        return Err(());
    }
    let digits = unsigned.trim_start_matches('0');
    let normalized = if digits.is_empty() {
        "0".to_owned()
    } else if raw.starts_with('-') {
        format!("-{digits}")
    } else {
        digits.to_owned()
    };
    serde_json::Number::from_str(&normalized)
        .map(Some)
        .map_err(|_| ())
}

fn cell_metadata(
    doc: &XmlDocument,
    cell: NodeId,
    ledger: &mut CoverageLedger,
) -> (
    BTreeMap<String, serde_json::Number>,
    BTreeMap<String, serde_json::Number>,
) {
    let mut span = BTreeMap::new();
    let mut addr = BTreeMap::new();
    for child in doc.elements(cell) {
        let target = match doc.node(child).name.local.as_str() {
            "cellSpan" => &mut span,
            "cellAddr" => &mut addr,
            _ => continue,
        };
        let keys: &[&str] = if doc.node(child).name.local == "cellSpan" {
            &["colSpan", "rowSpan"]
        } else {
            &["colAddr", "rowAddr"]
        };
        for key in keys {
            if let Some(raw) = doc.attr(child, key) {
                match cell_number(raw) {
                    Ok(Some(value)) => {
                        target.insert((*key).to_owned(), value);
                    }
                    Ok(None) => {}
                    Err(()) => {
                        ledger.failure.get_or_insert_with(|| {
                            format!("invalid cell numeric attribute {key}={raw:?}")
                        });
                    }
                }
            }
        }
    }
    (span, addr)
}

fn table_blocks(
    doc: &XmlDocument,
    table: NodeId,
    ledger: &mut CoverageLedger,
    path: &str,
    filter: Option<&FieldFilter<'_>>,
) -> Vec<Block> {
    let mut captions = Vec::new();
    let mut rows = Vec::new();
    for child in doc.elements(table) {
        let local = classify(
            doc,
            ledger,
            child,
            &["tr", "caption"],
            &["sz", "pos", "outMargin", "inMargin"],
            path,
        );
        if local == "caption" {
            captions.extend(crate::shape_text::caption_blocks(
                doc,
                child,
                ledger,
                &format!("{path}/caption"),
                filter,
            ));
        } else if local == "tr" {
            let tr_path = format!("{path}/tr");
            let mut cells = Vec::new();
            for cell in doc.elements(child) {
                if classify(doc, ledger, cell, &["tc"], &[], &tr_path) != "tc" {
                    continue;
                }
                let cell_path = format!("{tr_path}/tc");
                let (span, addr) = cell_metadata(doc, cell, ledger);
                let mut blocks = Vec::new();
                for sub in doc.elements(cell) {
                    if classify(
                        doc,
                        ledger,
                        sub,
                        &["subList", "cellSpan", "cellAddr"],
                        &["cellSz", "cellMargin"],
                        &cell_path,
                    ) == "subList"
                    {
                        blocks.extend(container_blocks(
                            doc,
                            sub,
                            ledger,
                            &format!("{cell_path}/subList"),
                            filter,
                        ));
                    }
                }
                cells.push(Cell { blocks, span, addr });
            }
            rows.push(cells);
        }
    }
    captions.push(Block::Table { rows });
    captions
}

fn entry_bytes<'a>(package: &'a HwpxPackage, name: &str) -> &'a [u8] {
    &package
        .entries
        .iter()
        .find(|entry| entry.name == name)
        .expect("selected package entry exists")
        .data
}

pub fn extract_document(
    package: &HwpxPackage,
    filter: Option<&FieldFilter<'_>>,
) -> Result<Document, XmlError> {
    let mut document = Document::default();
    let mut ledger = CoverageLedger::default();
    for name in section_xml_names(package) {
        let parsed = parse_xml(entry_bytes(package, name))?;
        let label = name
            .rsplit('/')
            .next()
            .unwrap_or(name)
            .rsplit_once('.')
            .map_or(name, |(stem, _)| stem);
        document.sections.push(Section {
            blocks: container_blocks(&parsed, parsed.root, &mut ledger, label, filter),
        });
    }
    for (prefix, target) in [
        ("header", &mut document.headers),
        ("footer", &mut document.footers),
    ] {
        for name in header_footer_names(package, prefix) {
            let parsed = parse_xml(entry_bytes(package, name))?;
            if has_body_text(&parsed) {
                let label = name
                    .rsplit('/')
                    .next()
                    .unwrap_or(name)
                    .rsplit_once('.')
                    .map_or(name, |(stem, _)| stem);
                target.push(Section {
                    blocks: container_blocks(&parsed, parsed.root, &mut ledger, label, filter),
                });
            }
        }
    }
    if let Some(failure) = ledger.failure {
        return Err(XmlError(failure));
    }
    document.unhandled = ledger.counts;
    document.unhandled_examples = ledger.examples;
    Ok(document)
}

pub fn iter_paragraph_texts(document: &Document) -> Vec<&str> {
    fn walk<'a>(blocks: &'a [Block], output: &mut Vec<&'a str>) {
        for block in blocks {
            match block {
                Block::Paragraph { text, .. } => output.push(text),
                Block::TextBox { blocks } => walk(blocks, output),
                Block::Table { rows } => {
                    for row in rows {
                        for cell in row {
                            walk(&cell.blocks, output);
                        }
                    }
                }
            }
        }
    }
    let mut output = Vec::new();
    for section in document
        .headers
        .iter()
        .chain(&document.sections)
        .chain(&document.footers)
    {
        walk(&section.blocks, &mut output);
    }
    output
}

pub fn full_text(document: &Document) -> String {
    iter_paragraph_texts(document).join("\n")
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::package::PackageLimits;
    use std::fs;
    use std::path::Path;

    #[test]
    fn inline_values_preserve_controls_and_report_unmodelled_content() {
        let cases = [
            (
                "가<hp:tab width='1668' leader='0' type='1'/>나<hp:lineBreak/>다<hp:fwSpace/>라",
                "가\t나\n다 라",
                vec![],
            ),
            (
                "가<hp:markpenBegin/>나<hp:markpenEnd/><!-- 주석 -->다",
                "가나다",
                vec![],
            ),
            (
                "앞<x:unknown>x</x:unknown>뒤",
                "앞뒤",
                vec!["{urn:x}unknown"],
            ),
            ("a<hp:nbSpace/>b", "ab", vec!["nbSpace"]),
            (
                "a<hp:insertBegin Id='1' TcId='2'/>b<hp:insertEnd Id='1' TcId='2'/>",
                "ab",
                vec!["insertBegin", "insertEnd"],
            ),
            ("a<hp:tab>x</hp:tab>b", "ab", vec!["tab"]),
            ("a<hp:fwSpace><hp:x/></hp:fwSpace>b", "ab", vec!["fwSpace"]),
        ];
        for (inner, text, unmodelled) in cases {
            let doc = parse_xml(
                format!("<hp:t xmlns:hp='{HP_NS}' xmlns:x='urn:x'>{inner}</hp:t>").as_bytes(),
            )
            .unwrap();
            let read = read_inline_text(&doc, doc.root);
            assert_eq!(read.text, text, "{inner}");
            assert_eq!(read.unmodelled, unmodelled, "{inner}");
            assert_eq!(read.exact(), unmodelled.is_empty());
        }
        let doc = parse_xml(format!("<hp:run xmlns:hp='{HP_NS}'><hp:t>가<hp:tab/></hp:t><hp:t><hp:nbSpace/>나</hp:t></hp:run>").as_bytes()).unwrap();
        let read = read_field_text(&doc, &doc.elements(doc.root).collect::<Vec<_>>());
        assert_eq!(read.text, "가\t나");
        assert_eq!(read.unmodelled, ["nbSpace"]);

        let doc = parse_xml(format!("<sec xmlns:hp='{HP_NS}' xmlns:x='urn:x'><hp:p><hp:run><hp:t>앞<x:unknown>x</x:unknown>뒤</hp:t><hp:t>a<hp:nbSpace/>b<hp:fwSpace/>c<hp:markpenBegin/>d<hp:markpenEnd/></hp:t></hp:run></hp:p></sec>").as_bytes()).unwrap();
        let mut ledger = CoverageLedger::default();
        assert_eq!(
            container_blocks(&doc, doc.root, &mut ledger, "sec", None),
            [Block::Paragraph {
                text: "앞뒤ab cd".into(),
                fields: vec![]
            }]
        );
        assert_eq!(
            ledger.counts,
            [("{urn:x}unknown".into(), 1), ("nbSpace".into(), 1)].into()
        );
        assert_eq!(
            ledger.examples,
            [
                ("{urn:x}unknown".into(), "sec/p/run/t/unknown".into()),
                ("nbSpace".into(), "sec/p/run/t/nbSpace".into())
            ]
            .into()
        );
    }

    #[test]
    fn field_names_follow_matching_end_and_requested_type_filter() {
        let fixture: serde_json::Value = serde_json::from_str(include_str!(
            "../../../tests/fixtures/inline_field_values.json"
        ))
        .unwrap();
        let cases = [
            (
                fixture["typed_fields"].as_str().unwrap(),
                vec!["계약명", "링크"],
                vec!["계약명"],
            ),
            (
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin id='5' name='이름'/><hp:fieldEnd beginIDRef='99'/></hp:ctrl><hp:t>값</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='5'/></hp:ctrl></hp:run></hp:p>",
                vec!["이름"],
                vec!["이름"],
            ),
        ];
        for (body, expected, filtered) in cases {
            let package = HwpxPackage {
                entries: vec![crate::package::PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: format!("<sec xmlns:hp='{HP_NS}'>{body}</sec>").into_bytes(),
                    stored: false,
                }],
            };
            for (filter, names) in [
                (None, expected),
                (
                    Some(&(|kind: Option<&str>| kind != Some("HYPERLINK")) as &FieldFilter<'_>),
                    filtered,
                ),
            ] {
                let document = extract_document(&package, filter).unwrap();
                let Block::Paragraph { fields, .. } = &document.sections[0].blocks[0] else {
                    panic!("expected paragraph");
                };
                assert_eq!(fields, &names);
            }
        }
    }

    #[test]
    fn synthetic_blocks_preserve_shape_caption_order_and_unknown_diagnostics() {
        let cases: serde_json::Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/text_extraction.json"))
                .unwrap();
        for case in cases.as_array().unwrap() {
            let name = case["name"].as_str().unwrap();
            let doc = parse_xml(case["xml"].as_str().unwrap().as_bytes()).unwrap();
            let mut ledger = CoverageLedger::default();
            let blocks = container_blocks(&doc, doc.root, &mut ledger, "sec", None);
            assert!(ledger.failure.is_none(), "{name}");
            assert_eq!(
                serde_json::to_value(&blocks).unwrap(),
                case["blocks"],
                "{name}"
            );
            assert_eq!(
                serde_json::to_value(&ledger.counts).unwrap(),
                case["unhandled"],
                "{name}"
            );
            assert_eq!(
                serde_json::to_value(&ledger.examples).unwrap(),
                case["unhandled_examples"],
                "{name}"
            );
            let document = Document {
                sections: vec![Section { blocks }],
                ..Document::default()
            };
            assert_eq!(
                serde_json::to_value(iter_paragraph_texts(&document)).unwrap(),
                case["texts"],
                "{name}"
            );
        }
    }

    #[test]
    fn numeric_looking_malformed_cell_metadata_fails_closed() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:cellSpan colSpan='--1' rowSpan='1'/><hp:subList><hp:p><hp:run><hp:t>x</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![crate::package::PackageEntry {
                name: "Contents/section0.xml".to_owned(),
                data: xml.into_bytes(),
                stored: false,
            }],
        };
        assert!(extract_document(&package, None).is_err());
    }

    fn raw_text_segments(doc: &XmlDocument, id: NodeId, segments: &mut Vec<String>) {
        let mut pending = String::new();
        for part in &doc.node(id).children {
            match part {
                Content::Text(text) | Content::CData(text) => pending.push_str(text),
                _ => {
                    if !pending.is_empty() {
                        segments.push(std::mem::take(&mut pending));
                    }
                    if let Content::Element(child) = part {
                        raw_text_segments(doc, *child, segments);
                    }
                }
            }
        }
        if !pending.is_empty() {
            segments.push(pending);
        }
    }

    fn under_field_control(doc: &XmlDocument, id: NodeId) -> bool {
        std::iter::successors(doc.parent(id), |parent| doc.parent(*parent))
            .any(|parent| doc.node(parent).name.is(HP_NS, "ctrl"))
    }

    fn assert_source_text_preserved(doc: &XmlDocument, haystack: &str, next: &mut usize) -> usize {
        let mut fixed_spaces = 0;
        for id in doc.descendants(doc.root) {
            if !doc.node(id).name.is(HP_NS, "t") {
                continue;
            }
            let mut segments = Vec::new();
            raw_text_segments(doc, id, &mut segments);
            for segment in segments {
                let needle = segment.trim();
                assert!(haystack.contains(needle), "source text lost: {needle:?}");
            }
            for part in &doc.node(id).children {
                match part {
                    Content::Text(text) | Content::CData(text) => {
                        fixed_spaces += text.matches(' ').count()
                    }
                    Content::Element(child) => {
                        let name = &doc.node(*child).name;
                        assert_eq!(name.namespace, HP_NS, "new inline namespace: {name:?}");
                        assert!(
                            ["tab", "lineBreak", "fwSpace", "markpenBegin", "markpenEnd"]
                                .contains(&name.local.as_str()),
                            "new inline element: {name:?}"
                        );
                        fixed_spaces += usize::from(name.local == "fwSpace");
                    }
                    _ => {}
                }
            }
            if !under_field_control(doc, id) {
                let prefix: String = doc
                    .node(id)
                    .children
                    .iter()
                    .map_while(|part| match part {
                        Content::Text(text) | Content::CData(text) => Some(text.as_str()),
                        _ => None,
                    })
                    .collect();
                let needle = prefix.trim();
                if let Some(first) = needle.chars().next() {
                    let at = haystack[*next..]
                        .find(needle)
                        .unwrap_or_else(|| panic!("paragraph order lost: {needle:?}"));
                    *next += at + first.len_utf8();
                }
            }
        }
        fixed_spaces
    }

    fn assert_corpus_invariants(package: &HwpxPackage, document: &Document, path: &Path) {
        let haystack = full_text(document);
        assert!(
            document.unhandled.is_empty(),
            "{}: {:?}",
            path.display(),
            document.unhandled_examples
        );
        let mut next = 0;
        let mut fixed_spaces = 0;
        for name in section_xml_names(package) {
            let source = parse_xml(entry_bytes(package, name)).unwrap();
            fixed_spaces += assert_source_text_preserved(&source, &haystack, &mut next);
        }
        let body = Document {
            sections: document.sections.clone(),
            ..Document::default()
        };
        assert_eq!(
            full_text(&body).matches(' ').count(),
            fixed_spaces,
            "{}",
            path.display()
        );
        if path.file_name().unwrap() == "spec_revision_2025.hwpx" {
            assert_eq!(fixed_spaces, 2);
        }
        let bytes = package.to_bytes().unwrap();
        let reopened = HwpxPackage::from_bytes(&bytes, PackageLimits::default()).unwrap();
        assert_eq!(
            reopened.entries.len(),
            package.entries.len(),
            "{}",
            path.display()
        );
        for source in &package.entries {
            let output = reopened
                .entries
                .iter()
                .find(|entry| entry.name == source.name)
                .unwrap_or_else(|| panic!("{}: entry lost: {}", path.display(), source.name));
            assert!(
                output.data == source.data,
                "{}: entry changed: {}",
                path.display(),
                source.name
            );
        }
        assert!(
            &extract_document(&reopened, None).unwrap() == document,
            "{}: extraction changed after roundtrip",
            path.display()
        );
        let mut zip = zip::ZipArchive::new(std::io::Cursor::new(bytes)).unwrap();
        let first = zip.by_index(0).unwrap();
        assert_eq!(first.name(), "mimetype");
        assert_eq!(first.compression(), zip::CompressionMethod::Stored);
    }

    #[test]
    fn real_corpus_matches_existing_extraction_goldens() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus");
        let inputs = fs::read_dir(root.join("real")).unwrap();
        let mut matched = 0;
        for input in inputs {
            let path = input.unwrap().path();
            if path.extension().is_none_or(|extension| extension != "hwpx") {
                continue;
            }
            let package =
                HwpxPackage::from_bytes(&fs::read(&path).unwrap(), PackageLimits::default())
                    .unwrap();
            let document = extract_document(&package, None).unwrap();
            assert_corpus_invariants(&package, &document, &path);
            let actual = serde_json::to_value(document).unwrap();
            let expected: serde_json::Value = serde_json::from_slice(
                &fs::read(
                    root.join("golden")
                        .join(path.file_stem().unwrap())
                        .with_extension("json"),
                )
                .unwrap(),
            )
            .unwrap();
            assert_eq!(actual, expected, "{}", path.display());
            matched += 1;
        }
        assert_eq!(matched, 8);
    }

    #[test]
    fn inline_field_filter_and_header_footer_boundaries() {
        use crate::package::PackageEntry;
        let xml = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:ctrl><hp:fieldBegin type='HYPERLINK' name='link' id='1'/></hp:ctrl><hp:t>A<hp:tab/>B<hp:fwSpace/>C</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hs:sec>"
        );
        let package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: "mimetype".into(),
                    data: b"application/hwp+zip".to_vec(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.as_bytes().to_vec(),
                    stored: false,
                },
                PackageEntry {
                    name: "Contents/header.xml".into(),
                    data: format!("<hp:head xmlns:hp='{HP_NS}'><hp:refList/></hp:head>")
                        .into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "Contents/header1.xml".into(),
                    data: xml.as_bytes().to_vec(),
                    stored: false,
                },
                PackageEntry {
                    name: "Contents/footer1.xml".into(),
                    data: xml.as_bytes().to_vec(),
                    stored: false,
                },
            ],
        };
        let default = extract_document(&package, None).unwrap();
        assert_eq!(default.headers.len(), 1);
        assert_eq!(default.footers.len(), 1);
        assert_eq!(full_text(&default), "A\tB C\nA\tB C\nA\tB C");
        assert_eq!(
            default.sections[0].blocks[0],
            Block::Paragraph {
                text: "A\tB C".into(),
                fields: vec!["link".into()]
            }
        );
        let filtered = extract_document(&package, Some(&|kind| kind != Some("HYPERLINK"))).unwrap();
        assert_eq!(
            filtered.sections[0].blocks[0],
            Block::Paragraph {
                text: "A\tB C".into(),
                fields: vec![]
            }
        );
    }

    #[test]
    fn inline_unknown_namespace_and_padded_cell_numbers() {
        let xml = format!(
            "<hs:sec xmlns:hs='urn:section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>A<tab/>B</hp:t><hp:tbl><hp:tr><hp:tc><hp:cellSpan colSpan='01' rowSpan='000'/><hp:cellAddr colAddr='-01' rowAddr='-0'/><hp:subList><hp:p><hp:run><hp:t>cell</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let parsed = parse_xml(xml.as_bytes()).unwrap();
        let t = parsed
            .descendants(parsed.root)
            .into_iter()
            .find(|id| parsed.node(*id).name.is(HP_NS, "t"))
            .unwrap();
        assert_eq!(
            read_inline_text(&parsed, t),
            InlineText {
                text: "AB".into(),
                unmodelled: vec!["{}tab".into()]
            }
        );
        let mut ledger = CoverageLedger::default();
        let blocks = container_blocks(&parsed, parsed.root, &mut ledger, "section0", None);
        assert_eq!(ledger.counts.get("{}tab"), Some(&1));
        let table = blocks
            .iter()
            .find_map(|block| {
                if let Block::Table { rows } = block {
                    Some(rows)
                } else {
                    None
                }
            })
            .unwrap();
        let cell = &table[0][0];
        assert_eq!(cell.span["colSpan"].to_string(), "1");
        assert_eq!(cell.span["rowSpan"].to_string(), "0");
        assert_eq!(cell.addr["colAddr"].to_string(), "-1");
        assert_eq!(cell.addr["rowAddr"].to_string(), "0");
        let empty_cdata = parse_xml(
            format!("<hp:t xmlns:hp='{HP_NS}'>A<hp:tab><![CDATA[]]></hp:tab>B</hp:t>").as_bytes(),
        )
        .unwrap();
        assert_eq!(
            read_inline_text(&empty_cdata, empty_cdata.root).text,
            "A\tB"
        );
        assert!(read_inline_text(&empty_cdata, empty_cdata.root).exact());
    }
}
