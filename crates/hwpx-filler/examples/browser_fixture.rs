//! Browser resource-gate inputs and native rhwp roundtrip verdicts.
//! `cargo run -p hwpx-filler --example browser_fixture -- generate <output-dir>`
//! `cargo run -p hwpx-filler --example browser_fixture -- compare <original> <exported>`
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_core::text_model::HP_NS;
use hwpx_core::xml_view::{Content, NodeId, XmlView};
use hwpx_filler::hwpx_authoring_commands::apply_hwpx;
use hwpx_filler::hwpx_authoring_search::same_text_hwpx;
use hwpx_filler::rhwp_preflight::compare_rhwp_roundtrip;
use quick_xml::Reader;
use quick_xml::events::Event;
use serde_json::{Value, json};
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

const ENTRY: &str = "Contents/section0.xml";
const BID_SOURCE: &str = "real/bid_notice_limited_under100m.hwpx";

fn source(root: &Path, name: &str) -> Result<HwpxPackage, Box<dyn Error>> {
    Ok(HwpxPackage::from_bytes(
        &fs::read(root.join(name))?,
        PackageLimits::default(),
    )?)
}

fn write(package: &HwpxPackage, out: &Path, name: &str) -> Result<(), Box<dyn Error>> {
    fs::write(out.join(name), package.to_bytes()?)?;
    Ok(())
}

fn direct_paragraph_start(xml: &[u8], wanted: usize) -> Result<usize, Box<dyn Error>> {
    let mut reader = Reader::from_reader(xml);
    let mut depth = 0usize;
    let mut index = 0usize;
    loop {
        let offset = usize::try_from(reader.buffer_position())?;
        match reader.read_event()? {
            Event::Start(tag) => {
                if depth == 1 && tag.local_name().as_ref() == "p" {
                    if index == wanted {
                        return Ok(offset);
                    }
                    index += 1;
                }
                depth += 1;
            }
            Event::End(_) => depth -= 1,
            Event::Empty(tag) if depth == 1 && tag.local_name().as_ref() == "p" => index += 1,
            Event::Eof => break,
            _ => {}
        }
    }
    Err(format!("direct paragraph {wanted} not found among {index}").into())
}

fn direct_paragraph_end(xml: &[u8], start: usize) -> Result<usize, Box<dyn Error>> {
    let mut reader = Reader::from_reader(&xml[start..]);
    let mut depth = 0usize;
    loop {
        match reader.read_event()? {
            Event::Start(_) => depth += 1,
            Event::End(tag) => {
                if depth == 1 && tag.local_name().as_ref() == "p" {
                    return Ok(start + usize::try_from(reader.buffer_position())?);
                }
                depth -= 1;
            }
            Event::Eof => return Err("paragraph end missing".into()),
            _ => {}
        }
    }
}

fn trailing_field(package: &mut HwpxPackage) -> Result<(), Box<dyn Error>> {
    let entry = package
        .entries
        .iter_mut()
        .find(|entry| entry.name == ENTRY)
        .ok_or("missing section0.xml")?;
    let start = direct_paragraph_start(&entry.data, 34)?;
    let end = direct_paragraph_end(&entry.data, start)?;
    let paragraph = std::str::from_utf8(&entry.data[start..end])?;
    let run_end = paragraph
        .rfind("</hp:run>")
        .ok_or("paragraph 34 has no run")?;
    let insertion = "<hp:ctrl><hp:fieldBegin id=\"1700000001\" type=\"CLICK_HERE\" name=\"끝\" editable=\"1\" dirty=\"1\" zorder=\"-1\" fieldid=\"1700000002\" metaTag=\"\"/></hp:ctrl><hp:ctrl><hp:fieldEnd beginIDRef=\"1700000001\" fieldid=\"1700000002\"/></hp:ctrl>";
    let at = start + run_end;
    entry
        .data
        .splice(at..at, insertion.as_bytes().iter().copied());
    Ok(())
}

fn elements(view: &XmlView, id: NodeId) -> Vec<NodeId> {
    view.node(id)
        .into_iter()
        .flat_map(|node| &node.children)
        .filter_map(|child| {
            if let Content::Element(id) = child {
                Some(*id)
            } else {
                None
            }
        })
        .collect()
}

fn is_hp(view: &XmlView, id: NodeId, local: &str) -> bool {
    view.node(id).is_some_and(|node| node.name.is(HP_NS, local))
}

fn region_end_follows_object(
    package: &HwpxPackage,
    end_paragraph: usize,
) -> Result<(), Box<dyn Error>> {
    let xml = &package
        .entries
        .iter()
        .find(|entry| entry.name == ENTRY)
        .ok_or("missing section0.xml")?
        .data;
    let view = XmlView::parse(xml)?;
    let paragraph = elements(&view, view.root())
        .into_iter()
        .filter(|id| is_hp(&view, *id, "p"))
        .nth(end_paragraph)
        .ok_or("generated end paragraph missing")?;
    let bookmarks: Vec<_> = view
        .descendants(view.root())
        .ok_or("invalid root")?
        .into_iter()
        .filter(|id| is_hp(&view, *id, "fieldBegin") && view.attr(*id, "type") == Some("BOOKMARK"))
        .collect();
    let [begin] = bookmarks.as_slice() else {
        return Err("expected one generated BOOKMARK".into());
    };
    let bookmark = view.attr(*begin, "id").ok_or("BOOKMARK id missing")?;
    let end = view
        .descendants(paragraph)
        .ok_or("invalid paragraph")?
        .into_iter()
        .find(|id| is_hp(&view, *id, "fieldEnd") && view.attr(*id, "beginIDRef") == Some(bookmark))
        .ok_or("generated BOOKMARK end missing")?;
    let ctrl = view.parent(end).ok_or("BOOKMARK end control missing")?;
    let trailing: Vec<_> = elements(&view, paragraph)
        .into_iter()
        .filter(|id| is_hp(&view, *id, "run"))
        .flat_map(|run| elements(&view, run))
        .filter(|id| {
            !is_hp(&view, *id, "t") || !view.direct_text(*id).unwrap_or_default().is_empty()
        })
        .collect();
    let position = trailing
        .iter()
        .position(|id| *id == ctrl)
        .ok_or("BOOKMARK end not in run")?;
    let prior = *trailing
        .get(
            position
                .checked_sub(1)
                .ok_or("BOOKMARK end has no prior object")?,
        )
        .ok_or("BOOKMARK end has no prior object")?;
    if view
        .descendants(prior)
        .ok_or("invalid prior object")?
        .into_iter()
        .any(|id| is_hp(&view, id, "tbl") || is_hp(&view, id, "fieldEnd"))
    {
        return Ok(());
    }
    Err("BOOKMARK end does not follow trailing table or field".into())
}

fn generate(root: &Path, out: &Path) -> Result<(), Box<dyn Error>> {
    fs::create_dir_all(out)?;
    let mut batch = source(root, "quickstart/구매요청서.hwpx")?;
    let selected = json!({"entry":ENTRY,"paragraph":2,"start_paragraph":2,
        "end_paragraph":2,"start":4,"end":5});
    let peers = same_text_hwpx(&batch, &selected)?;
    let sites: Vec<Value> = peers
        .iter()
        .filter(|hit| hit["enabled"] == true)
        .map(|hit| hit["location"].clone())
        .collect();
    if sites.len() != 3 {
        return Err(format!("expected three same-text sites, got {}", sites.len()).into());
    }
    let mut ranges = vec![selected.clone()];
    ranges.extend(sites);
    let mut command = selected.clone();
    command["type"] = json!("create_field");
    command["name"] = json!("구분");
    command["ranges"] = json!(ranges);
    apply_hwpx(&mut batch, &command)?;
    write(&batch, out, "batch-fields.hwpx")?;

    for (start, end) in [(20, 35), (20, 36), (36, 36)] {
        let mut package = source(root, BID_SOURCE)?;
        apply_hwpx(
            &mut package,
            &json!({"type":"create_slot","entry":ENTRY,
            "start_paragraph":start,"end_paragraph":end,"id":"a"}),
        )?;
        region_end_follows_object(&package, end)?;
        write(&package, out, &format!("slot-{start}-{end}-table-end.hwpx"))?;
    }
    let mut package = source(root, BID_SOURCE)?;
    trailing_field(&mut package)?;
    write(&package, out, "trailing-empty-field.hwpx")?;
    apply_hwpx(
        &mut package,
        &json!({"type":"create_slot","entry":ENTRY,
        "start_paragraph":20,"end_paragraph":34,"id":"a"}),
    )?;
    region_end_follows_object(&package, 34)?;
    write(&package, out, "slot-20-34-trailing-empty-field.hwpx")?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    match args.as_slice() {
        [action, out] if action == "generate" => {
            let corpus = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus");
            generate(&corpus, Path::new(out))
        }
        [action, original, exported] if action == "compare" => {
            let verdict = compare_rhwp_roundtrip(&fs::read(original)?, &fs::read(exported)?);
            println!("{verdict}");
            Ok(())
        }
        _ => Err(
            "usage: browser_fixture generate <output-dir> | compare <original> <exported>".into(),
        ),
    }
}
