//! Immutable XML entry view for format-level inspection.

use crate::native_admission::{EntryFieldScan, observe_field_doc};
use crate::text_extract::{InlineText, read_inline_text};
use crate::xml_dom::{Node, XmlDocument, XmlError, parse_xml};

pub use crate::xml_dom::{Content, NodeId};

/// Node IDs belong to one view. No mutable XML tree or serializer is exposed.
pub struct XmlView {
    doc: XmlDocument,
}

impl XmlView {
    pub fn parse(source: &[u8]) -> Result<Self, XmlError> {
        Ok(Self {
            doc: parse_xml(source)?,
        })
    }

    pub fn root(&self) -> NodeId {
        self.doc.root
    }

    pub fn node(&self, id: NodeId) -> Option<&Node> {
        self.doc.nodes.get(id.0)
    }

    pub fn parent(&self, id: NodeId) -> Option<NodeId> {
        self.node(id)?.parent
    }

    pub fn attr(&self, id: NodeId, local: &str) -> Option<&str> {
        self.node(id)?
            .attributes
            .iter()
            .find(|attribute| attribute.name.namespace.is_empty() && attribute.name.local == local)
            .map(|attribute| attribute.value.as_str())
    }

    pub fn descendants(&self, id: NodeId) -> Option<Vec<NodeId>> {
        self.node(id)?;
        Some(self.doc.descendants(id))
    }

    pub fn direct_text(&self, id: NodeId) -> Option<String> {
        self.node(id)?;
        Some(self.doc.direct_text(id))
    }

    pub fn inline_text(&self, id: NodeId) -> Option<InlineText> {
        self.node(id)?;
        Some(read_inline_text(&self.doc, id))
    }

    pub fn path(&self, id: NodeId) -> Option<String> {
        self.node(id)?;
        Some(path_for_doc(&self.doc, id))
    }

    /// Serialize one element as a standalone fragment with its in-scope namespaces.
    pub fn fragment_xml(&self, id: NodeId) -> Result<Option<String>, XmlError> {
        if self.node(id).is_none() {
            return Ok(None);
        }
        self.doc.fragment_xml(id).map(Some)
    }

    /// Ordinary Field pairs and their exact values, tied to this view's paragraph IDs.
    pub fn field_occurrences(&self, entry: &str) -> EntryFieldScan {
        observe_field_doc(entry, &self.doc)
    }
}

pub(crate) fn path_for_doc(doc: &XmlDocument, id: NodeId) -> String {
    fn step(doc: &XmlDocument, id: NodeId) -> &str {
        let name = &doc.node(id).name;
        if name.namespace.is_empty() || name.raw.contains(':') {
            &name.raw
        } else {
            "*"
        }
    }
    let mut segments = Vec::new();
    let mut current = Some(id);
    while let Some(node) = current {
        let token = step(doc, node);
        let mut segment = token.to_owned();
        if let Some(parent) = doc.parent(node) {
            let siblings: Vec<_> = doc
                .elements(parent)
                .filter(|sibling| step(doc, *sibling) == token)
                .collect();
            if siblings.len() > 1 {
                let position = siblings
                    .iter()
                    .position(|sibling| *sibling == node)
                    .unwrap()
                    + 1;
                segment.push_str(&format!("[{position}]"));
            }
        }
        segments.push(segment);
        current = doc.parent(node);
    }
    segments.reverse();
    format!("/{}", segments.join("/"))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::text_model::HP_NS;

    #[test]
    fn immutable_view_links_empty_field_to_table_paragraph_and_keeps_mixed_order() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>A<!--note--><![CDATA[B]]>C</hp:t><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:ctrl><hp:fieldBegin id='1' name='empty'/></hp:ctrl></hp:run><hp:run><hp:ctrl><hp:fieldEnd beginIDRef='1'/></hp:ctrl></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hs:sec>"
        );
        let view = XmlView::parse(xml.as_bytes()).unwrap();
        let ids = view.descendants(view.root()).unwrap();
        let text = ids
            .iter()
            .copied()
            .find(|id| view.node(*id).unwrap().name.is(HP_NS, "t"))
            .unwrap();
        assert!(matches!(
            view.node(text).unwrap().children.as_slice(),
            [Content::Text(a), Content::Comment(_), Content::CData(b), Content::Text(c)]
                if a == "A" && b == "B" && c == "C"
        ));
        let fields = view.field_occurrences("Contents/section0.xml");
        assert!(fields.pairing_usable());
        assert_eq!(fields.fields.len(), 1);
        let field = &fields.fields[0];
        assert_eq!(field.raw_name.as_deref(), Some("empty"));
        assert_eq!(field.value.text, "");
        assert!(view.node(field.paragraph).unwrap().name.is(HP_NS, "p"));
        let fragment = view.fragment_xml(field.begin).unwrap().unwrap();
        let reparsed = XmlView::parse(fragment.as_bytes()).unwrap();
        assert!(
            reparsed
                .node(reparsed.root())
                .unwrap()
                .name
                .is(HP_NS, "fieldBegin")
        );
        assert_eq!(reparsed.attr(reparsed.root(), "name"), Some("empty"));
        let sublist = view.parent(field.paragraph).unwrap();
        assert!(view.node(sublist).unwrap().name.is(HP_NS, "subList"));
        assert!(ids.contains(&field.paragraph));
        assert!(view.node(NodeId(usize::MAX)).is_none());
    }
}
