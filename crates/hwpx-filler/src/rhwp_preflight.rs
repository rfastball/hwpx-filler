//! Fail-closed comparison of a source HWPX and the editor's unchanged export.

use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_core::text_model::HP_NS;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use serde_json::{Value, json};
use std::collections::BTreeSet;

#[derive(Debug, PartialEq, Eq)]
enum Canonical {
    Element {
        name: String,
        attrs: Vec<(String, String)>,
        namespaces: Vec<(String, String)>,
        children: Vec<Canonical>,
    },
    Text(String),
    Comment(String),
    Pi(String),
}
/// One `(prefix, uri)` declaration. Scopes list them innermost last; a missing default reads as "".
type Binding = (String, String);

fn bound<'a>(scope: &'a [Binding], prefix: &str) -> &'a str {
    scope
        .iter()
        .rev()
        .find(|(name, _)| name == prefix)
        .map_or("", |(_, uri)| uri.as_str())
}

/// Inclusive C14N 1.0 (the Python contract, `etree.tostring(method="c14n")`) renders a
/// declaration only where it changes the binding inherited from the parent element, so a
/// redundant `xmlns:hp` on a nested element is invisible while a moved or rebound one is not.
fn rendered_namespaces(parent: &[Binding], declared: &[Binding]) -> Vec<Binding> {
    let mut rendered: Vec<_> = declared
        .iter()
        .filter(|(prefix, uri)| bound(parent, prefix) != uri)
        .cloned()
        .collect();
    rendered.sort();
    rendered
}

/// Hancom's own unset defaults and rhwp's false BOOKMARK flags; every other value is compared.
fn unset_default(view: &XmlView, id: NodeId, local: &str, value: &str) -> bool {
    let node = view.node(id).expect("view node");
    if node.name.is(HP_NS, "p") {
        return matches!(
            (local, value),
            ("pageBreak" | "columnBreak" | "merged", "0") | ("id", "4294967295")
        );
    }
    if node.name.is(HP_NS, "lineShape") {
        return local == "endCap" && value == "FLAT";
    }
    node.name.local == "fieldBegin"
        && view.attr(id, "type") == Some("BOOKMARK")
        && matches!(local, "editable" | "dirty")
        && value == "0"
}

/// An `hp:t` holding no characters, attributes, children or tail cannot change a run.
fn empty_text(view: &XmlView, child: NodeId, next: Option<&Content>) -> bool {
    let node = view.node(child).expect("child");
    let tail = next.is_some_and(
        |next| matches!(next, Content::Text(value) | Content::CData(value) if !value.is_empty()),
    );
    node.name.is(HP_NS, "t") && node.attributes.is_empty() && node.children.is_empty() && !tail
}

fn canonical_children(view: &XmlView, id: NodeId, scope: &[Binding]) -> Vec<Canonical> {
    let parts = &view.node(id).expect("view node").children;
    let mut children = Vec::new();
    for (index, content) in parts.iter().enumerate() {
        match content {
            Content::Element(child) if empty_text(view, *child, parts.get(index + 1)) => {}
            Content::Element(child) => children.push(canonical_node(view, *child, scope)),
            Content::Text(value) | Content::CData(value) => {
                if let Some(Canonical::Text(previous)) = children.last_mut() {
                    previous.push_str(value)
                } else {
                    children.push(Canonical::Text(value.clone()))
                }
            }
            Content::Comment(value) => children.push(Canonical::Comment(value.clone())),
            Content::ProcessingInstruction(value) => children.push(Canonical::Pi(value.clone())),
        }
    }
    children
}

fn canonical_node(view: &XmlView, id: NodeId, parent: &[Binding]) -> Canonical {
    let node = view.node(id).expect("view node");
    let mut attrs: Vec<_> = node
        .attributes
        .iter()
        .filter(|attribute| !unset_default(view, id, &attribute.name.local, &attribute.value))
        .map(|attribute| (attribute.name.raw.clone(), attribute.value.clone()))
        .collect();
    attrs.sort();
    let namespaces = rendered_namespaces(parent, &node.namespaces);
    let extended;
    let scope = if node.namespaces.is_empty() {
        parent
    } else {
        extended = [parent, node.namespaces.as_slice()].concat();
        extended.as_slice()
    };
    Canonical::Element {
        name: node.name.raw.clone(),
        attrs,
        namespaces,
        children: canonical_children(view, id, scope),
    }
}
fn same_xml(left: &[u8], right: &[u8]) -> bool {
    let (Ok(left), Ok(right)) = (XmlView::parse(left), XmlView::parse(right)) else {
        return false;
    };
    canonical_node(&left, left.root(), &[]) == canonical_node(&right, right.root(), &[])
}
pub fn compare_rhwp_roundtrip(original: &[u8], exported: &[u8]) -> Value {
    let parsed = (|| -> Result<(HwpxPackage, HwpxPackage), String> {
        Ok((
            HwpxPackage::from_bytes(original, PackageLimits::default())
                .map_err(|e| e.to_string())?,
            HwpxPackage::from_bytes(exported, PackageLimits::default())
                .map_err(|e| e.to_string())?,
        ))
    })();
    let (source, result) = match parsed {
        Ok(parts) => parts,
        Err(error) => {
            return json!({"editable":false,"diagnostics":[
        {"kind":"invalid_package","message":format!("편집기가 내보낸 문서를 읽을 수 없습니다: {error}")} ]});
        }
    };
    let names: BTreeSet<_> = source
        .entries
        .iter()
        .chain(&result.entries)
        .map(|entry| entry.name.as_str())
        .collect();
    let mut diagnostics = Vec::new();
    for name in names {
        let before = source.entries.iter().find(|entry| entry.name == name);
        let after = result.entries.iter().find(|entry| entry.name == name);
        let (Some(before), Some(after)) = (before, after) else {
            diagnostics.push(json!({"entry":name,"kind":"entry_set_changed",
                "message":"문서 내부 파일 구성이 변경되었습니다."}));
            continue;
        };
        if before.data == after.data {
            continue;
        }
        if name.to_ascii_lowercase().ends_with(".xml")
            || name.to_ascii_lowercase().ends_with(".hpf")
        {
            if same_xml(&before.data, &after.data) {
                continue;
            }
            diagnostics.push(json!({"entry":name,"kind":"xml_changed",
                "message":"문서 구조가 가져오기와 내보내기 사이에 변경되었습니다."}));
        } else {
            diagnostics.push(json!({"entry":name,"kind":"binary_changed",
                "message":"문서 내부 파일이 가져오기와 내보내기 사이에 변경되었습니다."}));
        }
    }
    json!({"editable":diagnostics.is_empty(),"diagnostics":diagnostics})
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::compare_rhwp_roundtrip;
    use hwpx_core::package::{HwpxPackage, MIMETYPE_NAME, MIMETYPE_VALUE, PackageEntry};
    use hwpx_core::text_model::HP_NS;

    #[test]
    fn unchanged_defaults_are_editable_while_xml_and_binary_changes_block() {
        let xml = format!(
            "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'><hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p></hs:sec>"
        );
        let mut package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: xml.into_bytes(),
                    stored: false,
                },
                PackageEntry {
                    name: "BinData/image.bin".into(),
                    data: b"image".to_vec(),
                    stored: true,
                },
            ],
        };
        let source = package.to_bytes().unwrap();
        let mut changed = package.clone();
        changed.entries[1].data = String::from_utf8(changed.entries[1].data.clone())
            .unwrap()
            .replace("<hp:p>", "<hp:p pageBreak='0'>")
            .into_bytes();
        assert_eq!(
            compare_rhwp_roundtrip(&source, &changed.to_bytes().unwrap())["editable"],
            true
        );
        changed.entries[1].data = String::from_utf8(changed.entries[1].data.clone())
            .unwrap()
            .replace("본문", "다름")
            .into_bytes();
        assert_eq!(
            compare_rhwp_roundtrip(&source, &changed.to_bytes().unwrap())["diagnostics"][0]["kind"],
            "xml_changed"
        );
        changed = package.clone();
        changed.entries[2].data.push(b'!');
        assert_eq!(
            compare_rhwp_roundtrip(&source, &changed.to_bytes().unwrap())["diagnostics"][0]["kind"],
            "binary_changed"
        );
        package.entries.push(PackageEntry {
            name: "BinData/new.bin".into(),
            data: b"new".to_vec(),
            stored: true,
        });
        assert_eq!(
            compare_rhwp_roundtrip(&source, &package.to_bytes().unwrap())["diagnostics"][0]["kind"],
            "entry_set_changed"
        );
        assert_eq!(
            compare_rhwp_roundtrip(&source, b"broken")["diagnostics"][0]["kind"],
            "invalid_package"
        );
    }

    #[test]
    fn only_proven_serializer_defaults_are_ignored() {
        let verdict = |source: &str, exported: &str| {
            let section = |body: &str| {
                format!(
                "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>"
            ).into_bytes()
            };
            let mut package = HwpxPackage {
                entries: vec![
                    PackageEntry {
                        name: MIMETYPE_NAME.into(),
                        data: MIMETYPE_VALUE.into(),
                        stored: true,
                    },
                    PackageEntry {
                        name: "Contents/section0.xml".into(),
                        data: section(source),
                        stored: false,
                    },
                ],
            };
            let original = package.to_bytes().unwrap();
            package.entries[1].data = section(exported);
            compare_rhwp_roundtrip(&original, &package.to_bytes().unwrap())
        };
        for (source, exported, editable) in [
            (
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                "<hp:p id='4294967295' pageBreak='0' columnBreak='0' merged='0'><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                true,
            ),
            (
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                "<hp:p pageBreak='1'><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                "<hp:p id='0'><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                "<hp:p columnBreak='1'><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                "<hp:p merged='1'><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:lineShape/></hp:run></hp:p>",
                "<hp:p><hp:run><hp:lineShape endCap='FLAT'/></hp:run></hp:p>",
                true,
            ),
            (
                "<hp:p><hp:run><hp:lineShape/></hp:run></hp:p>",
                "<hp:p><hp:run><hp:lineShape endCap='ROUND'/></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin type='BOOKMARK' name='s'/></hp:ctrl></hp:run></hp:p>",
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin type='BOOKMARK' name='s' editable='0' dirty='0'/></hp:ctrl></hp:run></hp:p>",
                true,
            ),
            (
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin type='BOOKMARK' name='s'/></hp:ctrl></hp:run></hp:p>",
                "<hp:p><hp:run><hp:ctrl><hp:fieldBegin type='BOOKMARK' name='s' editable='1'/></hp:ctrl></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:ctrl><hp:tab/></hp:ctrl><hp:t/></hp:run></hp:p>",
                "<hp:p><hp:run><hp:ctrl><hp:tab/></hp:ctrl></hp:run></hp:p>",
                true,
            ),
            (
                "<hp:p><hp:run><hp:t id='1'/></hp:run></hp:p>",
                "<hp:p><hp:run/></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:t> </hp:t></hp:run></hp:p>",
                "<hp:p><hp:run/></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:t><hp:lineBreak/></hp:t></hp:run></hp:p>",
                "<hp:p><hp:run/></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run charPrIDRef='1'><hp:t/></hp:run></hp:p>",
                "<hp:p><hp:run charPrIDRef='2'><hp:t/></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:t/>꼬리</hp:run></hp:p>",
                "<hp:p><hp:run>꼬리</hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:tbl metatag='important'/></hp:run></hp:p>",
                "<hp:p><hp:run><hp:tbl/></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList metatag='important'/></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>",
                "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList/></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>",
                false,
            ),
            (
                r##"<hp:p><hp:run><hp:tbl><hp:metaTag>{"name":"#hf"}</hp:metaTag></hp:tbl></hp:run></hp:p>"##,
                r##"<hp:p><hp:run><hp:tbl><hp:metaTag>{"name": "#hf"}</hp:metaTag></hp:tbl></hp:run></hp:p>"##,
                false,
            ),
        ] {
            let result = verdict(source, exported);
            assert_eq!(result["editable"], editable, "{source} -> {exported}");
            assert_eq!(
                result["diagnostics"].as_array().unwrap().is_empty(),
                editable
            );
        }
        for (name, source, exported) in [
            (
                "Contents/header.xml",
                "<hh:head xmlns:hh='http://www.hancom.co.kr/hwpml/2011/head'><hh:charPr id='1'/></hh:head>",
                "<hh:head xmlns:hh='http://www.hancom.co.kr/hwpml/2011/head'><hh:charPr id='2'/></hh:head>",
            ),
            (
                "Contents/content.hpf",
                "<opf:package xmlns:opf='http://www.idpf.org/2007/opf/'><opf:manifest><opf:item id='a'/><opf:item id='b'/></opf:manifest></opf:package>",
                "<opf:package xmlns:opf='http://www.idpf.org/2007/opf/'><opf:manifest><opf:item id='b'/><opf:item id='a'/></opf:manifest></opf:package>",
            ),
        ] {
            let mut package = HwpxPackage {
                entries: vec![
                    PackageEntry {
                        name: MIMETYPE_NAME.into(),
                        data: MIMETYPE_VALUE.into(),
                        stored: true,
                    },
                    PackageEntry {
                        name: name.into(),
                        data: source.as_bytes().to_vec(),
                        stored: false,
                    },
                ],
            };
            let original = package.to_bytes().unwrap();
            package.entries[1].data = exported.as_bytes().to_vec();
            let result = compare_rhwp_roundtrip(&original, &package.to_bytes().unwrap());
            assert_eq!(result["diagnostics"][0]["kind"], "xml_changed", "{name}");
            assert_eq!(result["diagnostics"][0]["entry"], name);
        }
    }

    fn section_editable(source: &str, exported: &str) -> bool {
        let section = |body: &str| {
            format!(
                "<hs:sec xmlns:hs='http://www.hancom.co.kr/hwpml/2011/section' xmlns:hp='{HP_NS}'>{body}</hs:sec>"
            )
            .into_bytes()
        };
        let mut package = HwpxPackage {
            entries: vec![
                PackageEntry {
                    name: MIMETYPE_NAME.into(),
                    data: MIMETYPE_VALUE.into(),
                    stored: true,
                },
                PackageEntry {
                    name: "Contents/section0.xml".into(),
                    data: section(source),
                    stored: false,
                },
            ],
        };
        let original = package.to_bytes().unwrap();
        package.entries[1].data = section(exported);
        let result = compare_rhwp_roundtrip(&original, &package.to_bytes().unwrap());
        let editable = result["editable"].as_bool().unwrap();
        assert_eq!(
            result["diagnostics"].as_array().unwrap().is_empty(),
            editable
        );
        editable
    }

    /// Namespace declarations follow inclusive C14N 1.0 like the Python comparator
    /// (`lxml` `method="c14n"`): only a declaration that changes the inherited binding is
    /// compared. Every expectation below was confirmed against that Python implementation.
    #[test]
    fn namespace_declarations_compare_by_inherited_binding_like_c14n() {
        let begin = "id='7' type='CLICK_HERE' name='구분' editable='1' dirty='1' zorder='-1' fieldid='8' metaTag=''";
        // The product's batch create_field output and rhwp's export of it (batch-fields.hwpx).
        let product = format!(
            "<hp:p><hp:run><hp:t>A</hp:t><hp:ctrl xmlns:hp='{HP_NS}'><hp:fieldBegin xmlns:hp='{HP_NS}' {begin}/></hp:ctrl><hp:t>:</hp:t><hp:ctrl xmlns:hp='{HP_NS}'><hp:fieldEnd xmlns:hp='{HP_NS}' beginIDRef='7' fieldid='8'/></hp:ctrl></hp:run></hp:p>"
        );
        let exported = format!(
            "<hp:p><hp:run><hp:t>A</hp:t><hp:ctrl><hp:fieldBegin id='7' type='CLICK_HERE' name='구분' editable='1' dirty='1' fieldid='8' xmlns:hp='{HP_NS}' zorder='-1' metaTag=''/></hp:ctrl><hp:t>:</hp:t><hp:ctrl><hp:fieldEnd beginIDRef='7' fieldid='8'/></hp:ctrl></hp:run></hp:p>"
        );
        assert!(section_editable(&product, &exported));
        assert!(section_editable(&exported, &product));
        for (source, exported, editable) in [
            (
                "<hp:p xmlns:x='urn:x'><hp:run/></hp:p>",
                "<hp:p><hp:run xmlns:x='urn:x'/></hp:p>",
                false,
            ),
            (
                "<hp:p xmlns:x='urn:x'><hp:run/></hp:p>",
                "<hp:p><hp:run/></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run xmlns:hp='urn:other'/></hp:p>",
                "<hp:p><hp:run/></hp:p>",
                false,
            ),
            (
                "<hp:p xmlns:x='urn:x'><hp:run xmlns:x='urn:y'><hp:ctrl xmlns:x='urn:x'/></hp:run></hp:p>",
                "<hp:p xmlns:x='urn:x'><hp:run xmlns:x='urn:y'><hp:ctrl/></hp:run></hp:p>",
                false,
            ),
            (
                "<hp:p xmlns:x='urn:x'><hp:run xmlns:x='urn:x'><hp:ctrl/></hp:run></hp:p>",
                "<hp:p xmlns:x='urn:x'><hp:run><hp:ctrl/></hp:run></hp:p>",
                true,
            ),
            (
                "<hp:p><hp:run xmlns=''/></hp:p>",
                "<hp:p><hp:run/></hp:p>",
                true,
            ),
            (
                "<hp:p xmlns='urn:d'><hp:run xmlns=''/></hp:p>",
                "<hp:p xmlns='urn:d'><hp:run/></hp:p>",
                false,
            ),
            (
                "<hp:p><hp:run><x:fieldBegin xmlns:x='urn:x' type='BOOKMARK'/></hp:run></hp:p>",
                "<hp:p><hp:run><x:fieldBegin xmlns:x='urn:x' type='BOOKMARK' editable='0' dirty='0'/></hp:run></hp:p>",
                true,
            ),
        ] {
            assert_eq!(
                section_editable(source, exported),
                editable,
                "{source} -> {exported}"
            );
        }
    }
}
