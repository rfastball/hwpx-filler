//! Entry-local protected ranges and paragraph extents, indexed once for admission.

use super::*;

#[derive(Clone, Debug)]
pub(crate) struct ProtectedRange {
    pub begin: NodeId,
    pub end: NodeId,
    pub begin_name: String,
    pub end_name: String,
}
#[derive(Clone, Debug)]
pub(crate) struct NativeAdmissionIndex {
    pub order: HashMap<NodeId, usize>,
    pub ranges: Vec<ProtectedRange>,
    pub unpaired: Vec<NodeId>,
    pub unsupported_inline: Vec<(NodeId, String)>,
    pub top_level_spans: HashMap<NodeId, (usize, usize)>,
    pub top_level_nonparagraph_prefix: Vec<usize>,
    pub section_definition_orders: Vec<usize>,
}

fn range_marker(local: &str) -> Option<(&'static str, bool)> {
    match local {
        "markpenBegin" => Some(("markpen", true)),
        "markpenEnd" => Some(("markpen", false)),
        "insertBegin" => Some(("insert", true)),
        "insertEnd" => Some(("insert", false)),
        "deleteBegin" => Some(("delete", true)),
        "deleteEnd" => Some(("delete", false)),
        _ => None,
    }
}
fn range_key<'a>(doc: &'a XmlDocument, id: NodeId, kind: &str) -> Option<Vec<&'a str>> {
    if kind == "markpen" {
        return Some(Vec::new());
    }
    Some(vec![
        doc.attr(id, "Id").filter(|s| !s.is_empty())?,
        doc.attr(id, "TcId").filter(|s| !s.is_empty())?,
    ])
}

pub(crate) fn build_native_admission_index(detail: &NativeEntryDetail) -> NativeAdmissionIndex {
    let doc = &detail.doc;
    let order = detail.order.clone();
    let (ranges, unpaired) = protected_ranges(detail);
    let unsupported_inline = unsupported_inline(detail);
    let children = top_level_items(doc);
    let mut top_level_spans = HashMap::new();
    let mut prefix = vec![0];
    for item in children {
        if let Some(id) = item {
            let descendants = doc.descendants(id);
            top_level_spans.insert(id, (order[&id], order[descendants.last().unwrap()]));
        }
        prefix.push(
            prefix.last().copied().unwrap_or(0)
                + usize::from(item.is_none_or(|id| !native(doc, id, "p"))),
        );
    }
    let section_definition_orders = detail
        .nodes
        .iter()
        .filter(|id| native(doc, **id, "secPr") || native(doc, **id, "colPr"))
        .map(|id| order[id])
        .collect();
    NativeAdmissionIndex {
        order,
        ranges,
        unpaired,
        unsupported_inline,
        top_level_spans,
        top_level_nonparagraph_prefix: prefix,
        section_definition_orders,
    }
}

fn protected_ranges(detail: &NativeEntryDetail) -> (Vec<ProtectedRange>, Vec<NodeId>) {
    let doc = &detail.doc;
    let mut stack: Vec<(String, Vec<String>, NodeId)> = Vec::new();
    let mut ranges = Vec::new();
    let mut unpaired = Vec::new();
    for id in detail.nodes.iter().copied() {
        if doc.node(id).name.namespace != HP_NS {
            continue;
        }
        let Some((kind, is_begin)) = range_marker(&doc.node(id).name.local) else {
            continue;
        };
        let Some(key) = range_key(doc, id, kind) else {
            unpaired.push(id);
            continue;
        };
        if is_begin {
            stack.push((
                kind.to_owned(),
                key.iter().map(|s| (*s).to_owned()).collect(),
                id,
            ));
        } else if stack.last().is_some_and(|(last_kind, last_key, _)| {
            last_kind == kind && last_key.iter().map(String::as_str).eq(key.iter().copied())
        }) {
            let (_, _, begin) = stack.pop().unwrap();
            ranges.push(ProtectedRange {
                begin,
                end: id,
                begin_name: node_name(doc, begin),
                end_name: node_name(doc, id),
            });
        } else {
            unpaired.push(id);
        }
    }
    unpaired.extend(stack.into_iter().map(|(_, _, id)| id));
    (ranges, unpaired)
}

fn unsupported_inline(detail: &NativeEntryDetail) -> Vec<(NodeId, String)> {
    let doc = &detail.doc;
    fn collect_unsupported(
        doc: &XmlDocument,
        node: NodeId,
        include_self: bool,
        out: &mut Vec<(NodeId, String)>,
    ) {
        if include_self {
            out.push((node, node_name(doc, node)));
        }
        for part in &doc.node(node).children {
            match part {
                Content::Element(child) => collect_unsupported(doc, *child, true, out),
                Content::Comment(_) => out.push((node, "#comment".to_owned())),
                Content::ProcessingInstruction(_) => out.push((node, "#pi".to_owned())),
                _ => {}
            }
        }
    }
    let mut unsupported_inline = Vec::new();
    for text in detail
        .nodes
        .iter()
        .copied()
        .filter(|id| native(doc, *id, "t"))
    {
        for part in &doc.node(text).children {
            match part {
                Content::Element(child) => {
                    let local = doc.node(*child).name.local.as_str();
                    let safe = doc.node(*child).name.namespace == HP_NS
                        && matches!(
                            local,
                            "tab"
                                | "lineBreak"
                                | "fwSpace"
                                | "markpenBegin"
                                | "markpenEnd"
                                | "insertBegin"
                                | "insertEnd"
                                | "deleteBegin"
                                | "deleteEnd"
                        );
                    collect_unsupported(doc, *child, !safe, &mut unsupported_inline);
                }
                Content::Comment(_) => unsupported_inline.push((text, "#comment".to_owned())),
                Content::ProcessingInstruction(_) => {
                    unsupported_inline.push((text, "#pi".to_owned()))
                }
                _ => {}
            }
        }
    }
    unsupported_inline
}
