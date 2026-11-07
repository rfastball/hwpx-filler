//! Caption and text-box projection for anchored shapes.

use crate::text_extract::{FieldFilter, classify, container_blocks};
use crate::text_model::{Block, CoverageLedger, HC_NS};
use crate::xml_dom::{NodeId, XmlDocument};

pub(crate) const SHAPE_TAGS: &[&str] = &[
    "rect",
    "ellipse",
    "arc",
    "polygon",
    "curve",
    "line",
    "connectLine",
    "container",
    "pic",
];
const IGNORE_SHAPE: &[&str] = &[
    "sz",
    "pos",
    "outMargin",
    "inMargin",
    "offset",
    "orgSz",
    "curSz",
    "flip",
    "rotationInfo",
    "renderingInfo",
    "lineShape",
    "fillBrush",
    "shadow",
    "pt",
    "pt0",
    "pt1",
    "pt2",
    "pt3",
    "center",
    "ax1",
    "ax2",
    "start1",
    "end1",
    "start2",
    "end2",
    "startPt",
    "endPt",
    "controlPoints",
    "point",
    "seg",
    "shapeComment",
    "metaTag",
];
const IGNORE_PIC: &[&str] = &["img", "imgRect", "imgClip", "imgDim", "effects"];

fn sublist_blocks(
    doc: &XmlDocument,
    owner: NodeId,
    ledger: &mut CoverageLedger,
    path: &str,
    filter: Option<&FieldFilter<'_>>,
    ignored: &[&str],
) -> Vec<Block> {
    let mut blocks = Vec::new();
    for child in doc.elements(owner) {
        if classify(doc, ledger, child, &["subList"], ignored, path) == "subList" {
            blocks.extend(container_blocks(
                doc,
                child,
                ledger,
                &format!("{path}/subList"),
                filter,
            ));
        }
    }
    blocks
}

pub(crate) fn caption_blocks(
    doc: &XmlDocument,
    caption: NodeId,
    ledger: &mut CoverageLedger,
    path: &str,
    filter: Option<&FieldFilter<'_>>,
) -> Vec<Block> {
    sublist_blocks(doc, caption, ledger, path, filter, &[])
}

pub(crate) fn shape_blocks(
    doc: &XmlDocument,
    shape: NodeId,
    ledger: &mut CoverageLedger,
    path: &str,
    filter: Option<&FieldFilter<'_>>,
) -> Vec<Block> {
    let kind = doc.node(shape).name.local.as_str();
    let mut captions = Vec::new();
    let mut body = Vec::new();
    for child in doc.elements(shape) {
        let name = &doc.node(child).name;
        let local = name.local.as_str();
        let ignored =
            IGNORE_SHAPE.contains(&local) || (kind == "pic" && IGNORE_PIC.contains(&local));
        let local = if name.namespace == HC_NS && ignored {
            local.to_owned()
        } else {
            let mut handled = vec!["drawText", "caption"];
            if kind == "container" {
                handled.extend_from_slice(SHAPE_TAGS);
            }
            let mut ignored = IGNORE_SHAPE.to_vec();
            if kind == "pic" {
                ignored.extend_from_slice(IGNORE_PIC);
            }
            classify(doc, ledger, child, &handled, &ignored, path)
        };
        match local.as_str() {
            "caption" => captions.extend(sublist_blocks(
                doc,
                child,
                ledger,
                &format!("{path}/caption"),
                filter,
                &[],
            )),
            "drawText" => body.push(Block::TextBox {
                blocks: sublist_blocks(
                    doc,
                    child,
                    ledger,
                    &format!("{path}/drawText"),
                    filter,
                    &["textMargin"],
                ),
            }),
            local if kind == "container" && SHAPE_TAGS.contains(&local) => body.extend(
                shape_blocks(doc, child, ledger, &format!("{path}/{local}"), filter),
            ),
            _ => {}
        }
    }
    captions.extend(body);
    captions
}
