//! Mutable XML tree for HWPX content entries. Element identity survives sibling edits.

use quick_xml::encoding::DecodingReader;
use quick_xml::events::{BytesStart, Event};
use quick_xml::reader::Reader;
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct XmlError(pub String);

impl fmt::Display for XmlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for XmlError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct NodeId(pub usize);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Name {
    pub raw: String,
    pub namespace: String,
    pub local: String,
}

impl Name {
    pub fn is(&self, namespace: &str, local: &str) -> bool {
        self.namespace == namespace && self.local == local
    }
    pub fn clark(&self) -> String {
        if self.namespace.is_empty() {
            self.local.clone()
        } else {
            format!("{{{}}}{}", self.namespace, self.local)
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Attribute {
    pub name: Name,
    pub value: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Content {
    Element(NodeId),
    Text(String),
    CData(String),
    Comment(String),
    ProcessingInstruction(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Node {
    pub name: Name,
    pub attributes: Vec<Attribute>,
    pub namespaces: Vec<(String, String)>,
    pub parent: Option<NodeId>,
    pub children: Vec<Content>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct XmlDocument {
    pub(crate) nodes: Vec<Node>,
    pub root: NodeId,
}

const MAX_XML_DEPTH: usize = 256;

fn invalid(message: impl Into<String>) -> XmlError {
    XmlError(message.into())
}

fn xml_char(ch: char) -> bool {
    matches!(ch as u32, 0x9 | 0xA | 0xD | 0x20..=0xD7FF | 0xE000..=0xFFFD | 0x10000..=0x10FFFF)
        && ch != '\u{FFFE}'
        && ch != '\u{FFFF}'
}

fn check_text(value: &str) -> Result<(), XmlError> {
    if value.chars().all(xml_char) {
        Ok(())
    } else {
        Err(invalid("illegal XML 1.0 character"))
    }
}

fn split_name(raw: &str) -> Result<(&str, &str), XmlError> {
    let mut parts = raw.split(':');
    let first = parts.next().unwrap_or("");
    if first.is_empty() || !valid_name_part(first) {
        return Err(invalid("empty XML name"));
    }
    match parts.next() {
        None => Ok(("", first)),
        Some(local) if valid_name_part(local) && parts.next().is_none() => Ok((first, local)),
        _ => Err(invalid("invalid qualified XML name")),
    }
}

fn valid_name_part(value: &str) -> bool {
    fn start(ch: char) -> bool {
        matches!(ch as u32, 0x41..=0x5A | 0x5F | 0x61..=0x7A | 0xC0..=0xD6 | 0xD8..=0xF6 |
            0xF8..=0x2FF | 0x370..=0x37D | 0x37F..=0x1FFF | 0x200C..=0x200D |
            0x2070..=0x218F | 0x2C00..=0x2FEF | 0x3001..=0xD7FF |
            0xF900..=0xFDCF | 0xFDF0..=0xFFFD | 0x10000..=0xEFFFF)
    }
    fn continuation(ch: char) -> bool {
        start(ch)
            || matches!(ch as u32, 0x2D | 0x2E | 0x30..=0x39 | 0xB7 | 0x300..=0x36F | 0x203F..=0x2040)
    }
    let mut chars = value.chars();
    chars.next().is_some_and(start) && chars.all(continuation)
}

fn resolve_name(
    raw: &str,
    scopes: &HashMap<String, String>,
    attribute: bool,
) -> Result<Name, XmlError> {
    let (prefix, local) = split_name(raw)?;
    if prefix == "xmlns" {
        return Err(invalid("reserved xmlns prefix"));
    }
    let namespace = if prefix.is_empty() && attribute {
        ""
    } else if prefix == "xml" {
        "http://www.w3.org/XML/1998/namespace"
    } else if prefix.is_empty() {
        scopes.get("").map(String::as_str).unwrap_or("")
    } else {
        scopes
            .get(prefix)
            .map(String::as_str)
            .ok_or_else(|| invalid(format!("undeclared XML prefix: {prefix}")))?
    };
    Ok(Name {
        raw: raw.to_owned(),
        namespace: namespace.to_owned(),
        local: local.to_owned(),
    })
}

fn normalize_attribute(raw: &str) -> String {
    raw.replace("\r\n", "\n")
        .replace('\r', "\n")
        .replace(['\t', '\n'], " ")
}

fn decode_attr(raw: &str) -> Result<String, XmlError> {
    if raw.contains('<') {
        return Err(invalid("literal < in XML attribute"));
    }
    let normalized = normalize_attribute(raw);
    let decoded = quick_xml::escape::unescape(&normalized).map_err(|e| invalid(e.to_string()))?;
    check_text(&decoded)?;
    Ok(decoded.into_owned())
}

fn append_content(nodes: &mut [Node], parent: NodeId, content: Content) {
    nodes[parent.0].children.push(content);
}

pub fn parse_xml(source: &[u8]) -> Result<XmlDocument, XmlError> {
    let decoder = DecodingReader::new(source);
    let mut reader = Reader::from_reader(decoder);
    reader.config_mut().check_end_names = true;
    reader.config_mut().check_comments = true;
    let mut buffer = Vec::new();
    let mut nodes = Vec::<Node>::new();
    let mut stack = Vec::<NodeId>::new();
    let mut scopes = vec![HashMap::<String, String>::new()];
    let mut root = None;
    let mut seen_event = false;
    let mut seen_doctype = false;
    loop {
        buffer.clear();
        let event = reader
            .read_event_into(&mut buffer)
            .map_err(|e| invalid(e.to_string()))?;
        let empty = matches!(&event, Event::Empty(_));
        match event {
            Event::Decl(decl) => {
                if seen_event {
                    return Err(invalid("misplaced XML declaration"));
                }
                let mut stage = 0;
                let declaration = BytesStart::from_content(decl.as_ref().to_owned(), 3);
                for attr in declaration.attributes() {
                    let attr = attr.map_err(|e| invalid(e.to_string()))?;
                    stage = match attr.key.as_ref() {
                        "version" if stage == 0 => 1,
                        "encoding" if stage == 1 => 2,
                        "standalone" if stage == 1 || stage == 2 => 3,
                        _ => return Err(invalid("invalid XML declaration attribute")),
                    };
                }
                if decl.version().map_err(|e| invalid(e.to_string()))?.as_ref() != "1.0" {
                    return Err(invalid("unsupported XML version"));
                }
                if let Some(standalone) = decl.standalone() {
                    let value = standalone.map_err(|e| invalid(e.to_string()))?;
                    if value != "yes" && value != "no" {
                        return Err(invalid("invalid standalone declaration"));
                    }
                }
                seen_event = true;
                if let Some(encoding) = decl.encoder() {
                    reader.get_mut().set_encoding(encoding);
                } else if decl.encoding().is_some() {
                    return Err(invalid("unsupported XML encoding"));
                }
            }
            Event::Start(start) | Event::Empty(start) => {
                seen_event = true;
                if stack.len() >= MAX_XML_DEPTH {
                    return Err(invalid("XML nesting depth exceeds 256"));
                }
                let raw = start.name().as_ref().to_owned();
                let mut scope = scopes.last().cloned().unwrap_or_default();
                let mut namespaces = Vec::new();
                let mut raw_attrs = Vec::new();
                for attr in start.attributes() {
                    let attr = attr.map_err(|e| invalid(e.to_string()))?;
                    let key = attr.key.as_ref().to_owned();
                    let value = decode_attr(attr.value.as_ref())?;
                    if key == "xmlns" || key.starts_with("xmlns:") {
                        let prefix = key.strip_prefix("xmlns:").unwrap_or("").to_owned();
                        const XML_URI: &str = "http://www.w3.org/XML/1998/namespace";
                        const XMLNS_URI: &str = "http://www.w3.org/2000/xmlns/";
                        if (key != "xmlns" && prefix.is_empty())
                            || (!prefix.is_empty() && !valid_name_part(&prefix))
                            || prefix == "xmlns"
                            || (prefix == "xml" && value != XML_URI)
                            || (prefix != "xml" && value == XML_URI)
                            || value == XMLNS_URI
                            || (!prefix.is_empty() && value.is_empty())
                        {
                            return Err(invalid("invalid XML namespace declaration"));
                        }
                        scope.insert(prefix.clone(), value.clone());
                        namespaces.push((prefix, value));
                    } else {
                        raw_attrs.push((key, value));
                    }
                }
                let name = resolve_name(&raw, &scope, false)?;
                let mut seen = HashSet::new();
                let mut attributes = Vec::new();
                for (key, value) in raw_attrs {
                    let name = resolve_name(&key, &scope, true)?;
                    if !seen.insert((name.namespace.clone(), name.local.clone())) {
                        return Err(invalid("duplicate expanded XML attribute"));
                    }
                    attributes.push(Attribute { name, value });
                }
                let parent = stack.last().copied();
                if parent.is_none() && root.is_some() {
                    return Err(invalid("multiple XML roots"));
                }
                let id = NodeId(nodes.len());
                nodes.push(Node {
                    name,
                    attributes,
                    namespaces,
                    parent,
                    children: Vec::new(),
                });
                if let Some(parent) = parent {
                    append_content(&mut nodes, parent, Content::Element(id));
                } else {
                    root = Some(id);
                }
                if !empty {
                    stack.push(id);
                    scopes.push(scope);
                }
            }
            Event::End(_) => {
                seen_event = true;
                stack.pop().ok_or_else(|| invalid("unmatched XML end"))?;
                scopes.pop();
            }
            Event::Text(text) => {
                seen_event = true;
                let value = text.xml10_content().into_owned();
                if value.contains("]]>") {
                    return Err(invalid("literal ]]> in XML text"));
                }
                check_text(&value)?;
                if let Some(parent) = stack.last().copied() {
                    append_content(&mut nodes, parent, Content::Text(value));
                } else if !value
                    .bytes()
                    .all(|byte| matches!(byte, b' ' | b'\t' | b'\n' | b'\r'))
                {
                    return Err(invalid("text outside XML root"));
                }
            }
            Event::GeneralRef(reference) => {
                seen_event = true;
                let value = if let Some(ch) = reference
                    .resolve_char_ref()
                    .map_err(|e| invalid(e.to_string()))?
                {
                    ch.to_string()
                } else {
                    match reference.as_ref() {
                        "amp" => "&",
                        "lt" => "<",
                        "gt" => ">",
                        "quot" => "\"",
                        "apos" => "'",
                        _ => return Err(invalid("unresolved XML entity")),
                    }
                    .to_owned()
                };
                check_text(&value)?;
                let parent = stack
                    .last()
                    .copied()
                    .ok_or_else(|| invalid("entity outside XML root"))?;
                append_content(&mut nodes, parent, Content::Text(value));
            }
            Event::CData(data) => {
                seen_event = true;
                let value = data.xml10_content().into_owned();
                check_text(&value)?;
                let parent = stack
                    .last()
                    .copied()
                    .ok_or_else(|| invalid("CDATA outside XML root"))?;
                append_content(&mut nodes, parent, Content::CData(value));
            }
            Event::Comment(comment) => {
                seen_event = true;
                check_text(comment.as_ref())?;
                if let Some(parent) = stack.last().copied() {
                    append_content(
                        &mut nodes,
                        parent,
                        Content::Comment(comment.as_ref().to_owned()),
                    );
                }
            }
            Event::PI(pi) => {
                seen_event = true;
                if !valid_name_part(pi.target()) || pi.target().eq_ignore_ascii_case("xml") {
                    return Err(invalid("invalid XML processing instruction target"));
                }
                check_text(pi.as_ref())?;
                if let Some(parent) = stack.last().copied() {
                    append_content(
                        &mut nodes,
                        parent,
                        Content::ProcessingInstruction(pi.as_ref().to_owned()),
                    );
                }
            }
            Event::DocType(doctype) => {
                check_text(doctype.as_ref())?;
                if root.is_some() || !stack.is_empty() || seen_doctype {
                    return Err(invalid("DTD after XML root"));
                }
                seen_event = true;
                seen_doctype = true;
            } // A declaration is allowed; referenced custom entities are not.
            Event::Eof => break,
        }
    }
    if !stack.is_empty() {
        return Err(invalid("unclosed XML root"));
    }
    Ok(XmlDocument {
        nodes,
        root: root.ok_or_else(|| invalid("missing XML root"))?,
    })
}

impl XmlDocument {
    pub fn node(&self, id: NodeId) -> &Node {
        &self.nodes[id.0]
    }
    pub fn node_mut(&mut self, id: NodeId) -> &mut Node {
        &mut self.nodes[id.0]
    }
    pub fn parent(&self, id: NodeId) -> Option<NodeId> {
        self.node(id).parent
    }
    pub fn attr(&self, id: NodeId, local: &str) -> Option<&str> {
        self.node(id)
            .attributes
            .iter()
            .find(|a| a.name.namespace.is_empty() && a.name.local == local)
            .map(|a| a.value.as_str())
    }
    pub fn elements(&self, id: NodeId) -> impl Iterator<Item = NodeId> + '_ {
        self.node(id).children.iter().filter_map(|item| match item {
            Content::Element(id) => Some(*id),
            _ => None,
        })
    }
    pub fn descendants(&self, id: NodeId) -> Vec<NodeId> {
        let mut out = vec![id];
        let mut at = 0;
        while at < out.len() {
            let children: Vec<_> = self.elements(out[at]).collect();
            out.splice(at + 1..at + 1, children);
            at += 1;
        }
        out
    }
    pub fn direct_text(&self, id: NodeId) -> String {
        self.node(id)
            .children
            .iter()
            .filter_map(|part| match part {
                Content::Text(text) | Content::CData(text) => Some(text.as_str()),
                _ => None,
            })
            .collect()
    }
    pub fn iter_text(&self, id: NodeId) -> String {
        fn collect(doc: &XmlDocument, id: NodeId, out: &mut String) {
            for item in &doc.node(id).children {
                match item {
                    Content::Element(child) => collect(doc, *child, out),
                    Content::Text(text) | Content::CData(text) => out.push_str(text),
                    _ => {}
                }
            }
        }
        let mut out = String::new();
        collect(self, id, &mut out);
        out
    }
    pub fn remove_element(&mut self, id: NodeId) -> Result<(), XmlError> {
        let parent = self
            .parent(id)
            .ok_or_else(|| invalid("cannot remove root"))?;
        let index = self
            .node(parent)
            .children
            .iter()
            .position(|item| matches!(item, Content::Element(child) if *child == id))
            .ok_or_else(|| invalid("detached XML node"))?;
        self.node_mut(parent).children.remove(index);
        self.node_mut(id).parent = None;
        Ok(())
    }

    pub fn remove_element_with_tail(&mut self, id: NodeId) -> Result<(), XmlError> {
        let parent = self
            .parent(id)
            .ok_or_else(|| invalid("cannot remove root"))?;
        let index = self
            .node(parent)
            .children
            .iter()
            .position(|item| matches!(item, Content::Element(child) if *child == id))
            .ok_or_else(|| invalid("detached XML node"))?;
        let children = &mut self.node_mut(parent).children;
        children.remove(index);
        while matches!(
            children.get(index),
            Some(Content::Text(_) | Content::CData(_))
        ) {
            children.remove(index);
        }
        self.node_mut(id).parent = None;
        Ok(())
    }
    pub fn insert_element(
        &mut self,
        parent: NodeId,
        index: usize,
        id: NodeId,
    ) -> Result<(), XmlError> {
        if self.parent(id).is_some() || id == self.root || index > self.node(parent).children.len()
        {
            return Err(invalid("invalid XML insertion"));
        }
        let mut depth = 1;
        let mut current = Some(parent);
        while let Some(node) = current {
            if node == id || depth > MAX_XML_DEPTH {
                return Err(invalid("cyclic or overdeep XML insertion"));
            }
            current = self.parent(node);
            depth += 1;
        }
        let mut pending = vec![(id, depth)];
        while let Some((node, at)) = pending.pop() {
            if at > MAX_XML_DEPTH {
                return Err(invalid("XML insertion exceeds nesting depth"));
            }
            pending.extend(self.elements(node).map(|child| (child, at + 1)));
        }
        self.node_mut(parent)
            .children
            .insert(index, Content::Element(id));
        self.node_mut(id).parent = Some(parent);
        Ok(())
    }
    pub fn new_element(&mut self, name: Name, attributes: Vec<Attribute>) -> NodeId {
        let id = NodeId(self.nodes.len());
        self.nodes.push(Node {
            name,
            attributes,
            namespaces: Vec::new(),
            parent: None,
            children: Vec::new(),
        });
        id
    }
    pub fn clone_subtree(&mut self, id: NodeId) -> NodeId {
        let source = self.node(id).clone();
        let copy = self.new_element(source.name, source.attributes);
        self.node_mut(copy).namespaces = source.namespaces;
        for child in source.children {
            let item = match child {
                Content::Element(child) => {
                    let cloned = self.clone_subtree(child);
                    self.node_mut(cloned).parent = Some(copy);
                    Content::Element(cloned)
                }
                other => other,
            };
            self.node_mut(copy).children.push(item);
        }
        copy
    }
    pub fn strip_local_elements(&mut self, local: &str) {
        for id in self.descendants(self.root) {
            let targets: Vec<_> = self
                .elements(id)
                .filter(|child| self.node(*child).name.local == local)
                .collect();
            for target in targets {
                let _ = self.remove_element(target);
            }
        }
    }
    pub fn to_modified_bytes(&self) -> Result<Vec<u8>, XmlError> {
        let mut out = String::from("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n");
        self.write_node(self.root, &mut out)?;
        Ok(out.into_bytes())
    }
    pub(crate) fn fragment_xml(&self, id: NodeId) -> Result<String, XmlError> {
        let mut ancestors = Vec::new();
        let mut parent = self.parent(id);
        while let Some(current) = parent {
            ancestors.push(current);
            parent = self.parent(current);
        }
        ancestors.reverse();
        let mut scope: Vec<(String, String)> = Vec::new();
        for ancestor in ancestors {
            for (prefix, uri) in &self.node(ancestor).namespaces {
                if let Some(existing) = scope.iter_mut().find(|(key, _)| key == prefix) {
                    existing.1 = uri.clone();
                } else {
                    scope.push((prefix.clone(), uri.clone()));
                }
            }
        }
        scope.retain(|(prefix, _)| {
            !self
                .node(id)
                .namespaces
                .iter()
                .any(|(local, _)| local == prefix)
        });
        let mut out = String::new();
        self.write_node_with_scope(id, &scope, &mut out)?;
        Ok(out)
    }
    fn write_node(&self, id: NodeId, out: &mut String) -> Result<(), XmlError> {
        self.write_node_with_scope(id, &[], out)
    }
    fn write_node_with_scope(
        &self,
        id: NodeId,
        scope: &[(String, String)],
        out: &mut String,
    ) -> Result<(), XmlError> {
        let node = self.node(id);
        out.push('<');
        out.push_str(&node.name.raw);
        for (prefix, value) in scope {
            out.push_str(" xmlns");
            if !prefix.is_empty() {
                out.push(':');
                out.push_str(prefix);
            }
            out.push_str("=\"");
            escape_attr(value, out)?;
            out.push('"');
        }
        for (prefix, value) in &node.namespaces {
            out.push_str(" xmlns");
            if !prefix.is_empty() {
                out.push(':');
                out.push_str(prefix);
            }
            out.push_str("=\"");
            escape_attr(value, out)?;
            out.push('"');
        }
        for attr in &node.attributes {
            out.push(' ');
            out.push_str(&attr.name.raw);
            out.push_str("=\"");
            escape_attr(&attr.value, out)?;
            out.push('"');
        }
        if node.children.is_empty() {
            out.push_str("/>");
            return Ok(());
        }
        out.push('>');
        for child in &node.children {
            match child {
                Content::Element(child) => self.write_node(*child, out)?,
                Content::Text(text) => escape_text(text, out)?,
                Content::CData(text) => {
                    out.push_str("<![CDATA[");
                    out.push_str(text);
                    out.push_str("]]>");
                }
                Content::Comment(text) => {
                    out.push_str("<!--");
                    out.push_str(text);
                    out.push_str("-->");
                }
                Content::ProcessingInstruction(text) => {
                    out.push_str("<?");
                    out.push_str(text);
                    out.push_str("?>");
                }
            }
        }
        out.push_str("</");
        out.push_str(&node.name.raw);
        out.push('>');
        Ok(())
    }
}

fn escape_text(value: &str, out: &mut String) -> Result<(), XmlError> {
    check_text(value)?;
    for ch in value.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '\r' => out.push_str("&#13;"),
            _ => out.push(ch),
        }
    }
    Ok(())
}

fn escape_attr(value: &str, out: &mut String) -> Result<(), XmlError> {
    check_text(value)?;
    for ch in value.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '"' => out.push_str("&quot;"),
            '\t' => out.push_str("&#9;"),
            '\n' => out.push_str("&#10;"),
            '\r' => out.push_str("&#13;"),
            _ => out.push(ch),
        }
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn namespace_mixed_content_and_roundtrip() {
        let source = b"<?xml version='1.0'?><!DOCTYPE root><root xmlns='urn:body' xmlns:a='urn:attr' xmlns:xml='http://www.w3.org/XML/1998/namespace' plain='x&#9;y' a:plain='other' xml:lang='ko'>A&#13;&amp;<!-- note -->B<?pi x?><child/>tail</root>";
        let doc = parse_xml(source).unwrap();
        assert!(doc.node(doc.root).name.is("urn:body", "root"));
        assert_eq!(doc.attr(doc.root, "plain"), Some("x\ty"));
        assert_eq!(doc.node(doc.root).attributes[1].name.namespace, "urn:attr");
        assert_eq!(
            doc.node(doc.root).attributes[2].name.namespace,
            "http://www.w3.org/XML/1998/namespace"
        );
        assert_eq!(doc.iter_text(doc.root), "A\r&Btail");
        let reparsed = parse_xml(&doc.to_modified_bytes().unwrap()).unwrap();
        assert_eq!(reparsed.iter_text(reparsed.root), "A\r&Btail");
        assert_eq!(reparsed.attr(reparsed.root, "plain"), Some("x\ty"));
        assert_eq!(
            reparsed.node(reparsed.root).children.len(),
            doc.node(doc.root).children.len()
        );
    }

    #[test]
    fn declared_utf16le_with_bom_preserves_korean_text() {
        let xml = "<?xml version='1.0' encoding='UTF-16'?><r>한글</r>";
        let mut bytes = vec![0xff, 0xfe];
        for unit in xml.encode_utf16() {
            bytes.extend_from_slice(&unit.to_le_bytes());
        }
        let parsed = parse_xml(&bytes).unwrap();
        assert_eq!(parsed.iter_text(parsed.root), "한글");
        assert_eq!(
            parse_xml(&parsed.to_modified_bytes().unwrap())
                .unwrap()
                .iter_text(parsed.root),
            "한글"
        );
    }

    #[test]
    fn malformed_or_ambiguous_xml_is_rejected() {
        for source in [
            "<r><x:a/></r>",
            "<r xmlns:a='urn:x' xmlns:b='urn:x' a:id='1' b:id='2'/>",
            "<r/><other/>",
            "<r>&custom;</r>",
            "<r>&#x1;</r>",
            "<r>\u{1}</r>",
            "<1bad/>",
            "<r bad:name='x'/>",
            "<r xmlns:xml='urn:wrong'/>",
            "<r xmlns:a='http://www.w3.org/XML/1998/namespace'/>",
            "<r xmlns:a='http://www.w3.org/2000/xmlns/'/>",
            "<r xmlns:bad:name='urn:x'/>",
            "<r xmlns:><x/></r>",
            "<?xml version='1.0' foo='bar'?><r/>",
            "<?xml version='1.0' version='1.0'?><r/>",
            "<!DOCTYPE r [\u{1}]><r/>",
            "<r a='<'/>",
            "<r>]]></r>",
            "<r><!--bad--comment--></r>",
            "<r><?xml bad?></r>",
            "<r/><!DOCTYPE r>",
            "<r/><!DOCTYPE r><!DOCTYPE r>",
            "<r/><?xml version='1.0'?>",
        ] {
            assert!(parse_xml(source.as_bytes()).is_err(), "{source:?}");
        }
    }

    #[test]
    fn parser_bounds_nesting_before_recursive_serialization() {
        let allowed = format!(
            "{}{}",
            "<r>".repeat(MAX_XML_DEPTH),
            "</r>".repeat(MAX_XML_DEPTH)
        );
        assert!(parse_xml(allowed.as_bytes()).is_ok());
        let too_deep = format!(
            "{}{}",
            "<r>".repeat(MAX_XML_DEPTH + 1),
            "</r>".repeat(MAX_XML_DEPTH + 1)
        );
        assert!(parse_xml(too_deep.as_bytes()).is_err());
    }

    #[test]
    fn modified_xml_preserves_attribute_controls_and_text_carriage_return() {
        let source = b"<r a='&#9;&#10;&#13;' b='a\tb\nc\rd'>A&#13;B</r>";
        let parsed = parse_xml(source).unwrap();
        assert_eq!(parsed.attr(parsed.root, "a"), Some("\t\n\r"));
        assert_eq!(parsed.attr(parsed.root, "b"), Some("a b c d"));
        let output = parsed.to_modified_bytes().unwrap();
        let reparsed = parse_xml(&output).unwrap();
        assert_eq!(reparsed.attr(reparsed.root, "a"), Some("\t\n\r"));
        assert_eq!(reparsed.iter_text(reparsed.root), "A\rB");
    }

    #[test]
    fn stable_ids_and_layout_tail_survive_edits() {
        let mut doc =
            parse_xml(b"<r><p>before<linesegarray/>tail<run>after</run></p></r>").unwrap();
        let p = doc.elements(doc.root).next().unwrap();
        let run = doc.elements(p).nth(1).unwrap();
        doc.strip_local_elements("linesegarray");
        assert_eq!(doc.parent(run), Some(p));
        assert_eq!(doc.iter_text(p), "beforetailafter");
        let clone = doc.clone_subtree(run);
        doc.insert_element(p, doc.node(p).children.len(), clone)
            .unwrap();
        assert_eq!(doc.parent(clone), Some(p));
        assert_eq!(doc.iter_text(p), "beforetailafterafter");
        for (source, expected) in [
            (
                "<r><p>본문<linesegarray><lineseg/></linesegarray>tail<run><tab/>뒤</run></p><!--keep--><p><linesegarray/></p></r>",
                "<r><p>본문tail<run><tab/>뒤</run></p><!--keep--><p/></r>",
            ),
            (
                "<r xmlns:x='urn:other'><x:linesegarray/><linesegarray/><linesegarrayX/><x:lineseg/></r>",
                "<r xmlns:x='urn:other'><linesegarrayX/><x:lineseg/></r>",
            ),
            ("<r><p/></r>", "<r><p/></r>"),
        ] {
            let mut doc = parse_xml(source.as_bytes()).unwrap();
            let output = crate::lineseg::serialize_modified_section(&mut doc).unwrap();
            let expected = parse_xml(expected.as_bytes())
                .unwrap()
                .to_modified_bytes()
                .unwrap();
            assert_eq!(output, expected);
            assert_eq!(
                crate::lineseg::serialize_modified_section(&mut doc).unwrap(),
                output
            );
        }
    }
}
