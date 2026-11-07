//! Pure XML edit for placing styled paragraphs at original top-level gaps.

use crate::lineseg::serialize_modified_section;
use crate::native_admission::native_element;
use crate::text_model::HP_NS;
use crate::xml_dom::{Attribute, Content, Name, NodeId, XmlDocument, XmlError, parse_xml};
use std::collections::BTreeMap;

fn invalid(message: impl Into<String>) -> XmlError {
    XmlError(message.into())
}

fn paragraphs(doc: &XmlDocument) -> Vec<NodeId> {
    doc.elements(doc.root)
        .filter(|id| doc.node(*id).name.is(HP_NS, "p"))
        .collect()
}

fn unqualified_attribute(doc: &XmlDocument, id: NodeId, local: &str) -> Option<Attribute> {
    doc.node(id)
        .attributes
        .iter()
        .find(|attribute| attribute.name.namespace.is_empty() && attribute.name.local == local)
        .map(|attribute| Attribute {
            name: Name {
                raw: local.into(),
                namespace: String::new(),
                local: local.into(),
            },
            value: attribute.value.clone(),
        })
}

fn marker_paragraph(
    doc: &mut XmlDocument,
    neighbor: NodeId,
    text: &str,
) -> Result<NodeId, XmlError> {
    let paragraph = native_element(doc, "p", &[]);
    for attribute in ["paraPrIDRef", "styleIDRef"] {
        if let Some(value) = unqualified_attribute(doc, neighbor, attribute) {
            doc.node_mut(paragraph).attributes.push(value);
        }
    }
    let run = native_element(doc, "run", &[]);
    let char_style = doc
        .elements(neighbor)
        .find(|id| doc.node(*id).name.is(HP_NS, "run"))
        .and_then(|id| unqualified_attribute(doc, id, "charPrIDRef"));
    if let Some(value) = char_style {
        doc.node_mut(run).attributes.push(value);
    }
    let content = native_element(doc, "t", &[]);
    doc.node_mut(content)
        .children
        .push(Content::Text(text.into()));
    doc.insert_element(run, 0, content)?;
    doc.insert_element(paragraph, 0, run)?;
    Ok(paragraph)
}

/// Style neighbor and root child index for one original paragraph gap: before
/// paragraph `gap`, or after the last paragraph when `gap` is the paragraph count.
fn insertion_site(
    doc: &XmlDocument,
    originals: &[NodeId],
    gap: usize,
) -> Result<(NodeId, usize), XmlError> {
    let neighbor = if gap == originals.len() {
        *originals.last().unwrap()
    } else {
        originals[gap]
    };
    let mut position = doc
        .node(doc.root)
        .children
        .iter()
        .position(|part| matches!(part, Content::Element(id) if *id == neighbor))
        .ok_or_else(|| invalid("detached marker neighbor"))?;
    if gap == originals.len() {
        position += 1;
    }
    Ok((neighbor, position))
}

/// Insert `(gap, marker text)` in list order, with gaps referring to the original
/// direct native paragraph sequence. No package or filesystem mutation occurs.
pub fn insert_marker_paragraphs(
    source: &[u8],
    insertions: &[(usize, String)],
) -> Result<Vec<u8>, XmlError> {
    let mut doc = parse_xml(source)?;
    let originals = paragraphs(&doc);
    if originals.is_empty() {
        return Err(invalid("본문 직계 문단이 없어 마커를 되심을 수 없습니다."));
    }
    let mut groups: BTreeMap<usize, Vec<&str>> = BTreeMap::new();
    for (gap, text) in insertions {
        if *gap > originals.len() {
            return Err(invalid(format!(
                "마커 삽입 위치 {gap} 가 문단 수 {} 밖입니다.",
                originals.len()
            )));
        }
        groups.entry(*gap).or_default().push(text);
    }
    if groups.is_empty() {
        return Ok(source.to_vec());
    }
    for (gap, texts) in groups.into_iter().rev() {
        let (neighbor, position) = insertion_site(&doc, &originals, gap)?;
        for text in texts.into_iter().rev() {
            let paragraph = marker_paragraph(&mut doc, neighbor, text)?;
            doc.insert_element(doc.root, position, paragraph)?;
        }
    }
    let candidate = serialize_modified_section(&mut doc)?;
    let verified = parse_xml(&candidate)?;
    let actual = paragraphs(&verified);
    if actual.len() != originals.len() + insertions.len() {
        return Err(invalid(
            "marker paragraph count changed during serialization",
        ));
    }
    Ok(candidate)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn inserts_same_gap_in_order_inherits_style_and_strips_lineseg() {
        let source = format!(
            "<s:sec xmlns:s='urn:section' xmlns:h='{HP_NS}'><h:p paraPrIDRef='4' styleIDRef='5'><h:run charPrIDRef='6'><h:t>A</h:t></h:run><h:linesegarray/></h:p><h:p><h:run><h:t>B</h:t></h:run></h:p></s:sec>"
        );
        let bytes = insert_marker_paragraphs(
            source.as_bytes(),
            &[(1, "{{#항목 s}}".into()), (1, "{{/항목}}".into())],
        )
        .unwrap();
        let text = String::from_utf8(bytes).unwrap();
        assert!(text.find("{{#항목 s}}").unwrap() < text.find("{{/항목}}").unwrap());
        assert!(!text.contains("linesegarray"));
        // Gap one inherits the second paragraph's (absent) style, not the first's.
        assert_eq!(text.matches("paraPrIDRef=\"4\"").count(), 1);
        assert_eq!(
            insert_marker_paragraphs(source.as_bytes(), &[]).unwrap(),
            source.as_bytes()
        );
        assert!(insert_marker_paragraphs(source.as_bytes(), &[(3, "x".into())]).is_err());
    }
}
