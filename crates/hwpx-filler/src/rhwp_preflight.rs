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
fn canonical_node(view: &XmlView, id: NodeId) -> Canonical {
    let node = view.node(id).expect("view node");
    let mut attrs: Vec<_> = node
        .attributes
        .iter()
        .filter(|attribute| {
            let value = attribute.value.as_str();
            if node.name.is(HP_NS, "p")
                && matches!(
                    (attribute.name.local.as_str(), value),
                    ("pageBreak" | "columnBreak" | "merged", "0") | ("id", "4294967295")
                )
            {
                return false;
            }
            if node.name.is(HP_NS, "lineShape")
                && attribute.name.local == "endCap"
                && value == "FLAT"
            {
                return false;
            }
            if node.name.is(HP_NS, "fieldBegin")
                && view.attr(id, "type") == Some("BOOKMARK")
                && matches!(attribute.name.local.as_str(), "editable" | "dirty")
                && value == "0"
            {
                return false;
            }
            true
        })
        .map(|attribute| (attribute.name.raw.clone(), attribute.value.clone()))
        .collect();
    attrs.sort();
    let mut namespaces = node.namespaces.clone();
    namespaces.sort();
    let mut children = Vec::new();
    for (index, content) in node.children.iter().enumerate() {
        match content {
            Content::Element(child) => {
                let descendant = view.node(*child).expect("child");
                let tail=node.children.get(index+1).is_some_and(|next|matches!(next,Content::Text(value)|Content::CData(value) if !value.is_empty()));
                if descendant.name.is(HP_NS, "t")
                    && descendant.attributes.is_empty()
                    && descendant.children.is_empty()
                    && !tail
                {
                    continue;
                }
                children.push(canonical_node(view, *child));
            }
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
    Canonical::Element {
        name: node.name.raw.clone(),
        attrs,
        namespaces,
        children,
    }
}
fn same_xml(left: &[u8], right: &[u8]) -> bool {
    let (Ok(left), Ok(right)) = (XmlView::parse(left), XmlView::parse(right)) else {
        return false;
    };
    canonical_node(&left, left.root()) == canonical_node(&right, right.root())
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
}
