//! Shared deterministic HWPX fixture authoring over the format and product kernels.

use hwpx_core::package::{HwpxPackage, PackageLimits};
use hwpx_filler::authoring::compile_document;
use std::error::Error;

mod legacy_zip;

pub fn write_package(package: &HwpxPackage) -> Result<Vec<u8>, Box<dyn Error>> {
    legacy_zip::write(&package.entries)
}

fn xml_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn paragraph(text: &str) -> String {
    format!(
        "<hp:p paraPrIDRef=\"0\" styleIDRef=\"0\" pageBreak=\"0\" columnBreak=\"0\" merged=\"0\"><hp:run charPrIDRef=\"0\"><hp:t>{}</hp:t></hp:run></hp:p>",
        xml_text(text)
    )
}

fn section(
    source: &str,
    title: &str,
    lines: &[&str],
    blank: bool,
) -> Result<Vec<u8>, Box<dyn Error>> {
    let root_start = source.find("<hs:sec ").ok_or("missing section root")?;
    let root_end = source[root_start..]
        .find('>')
        .ok_or("unclosed section root")?
        + root_start
        + 1;
    let sec_start = source.find("<hp:secPr ").ok_or("missing secPr")?;
    let sec_end = source[sec_start..]
        .find("</hp:secPr>")
        .ok_or("unclosed secPr")?
        + sec_start
        + "</hp:secPr>".len();
    if sec_start < root_end || !source.ends_with("</hs:sec>") {
        return Err("unexpected section layout".into());
    }
    let mut xml = String::from("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n");
    xml.push_str(&source[root_start..root_end]);
    xml.push_str("<hp:p id=\"3121190098\" paraPrIDRef=\"0\" styleIDRef=\"0\" pageBreak=\"0\" columnBreak=\"0\" merged=\"0\"><hp:run charPrIDRef=\"0\">");
    xml.push_str(&source[sec_start..sec_end]);
    xml.push_str("</hp:run><hp:run charPrIDRef=\"0\"><hp:t>");
    xml.push_str(&xml_text(title));
    xml.push_str("</hp:t></hp:run></hp:p>");
    if blank {
        xml.push_str(&paragraph(""));
    }
    for line in lines {
        xml.push_str(&paragraph(line));
    }
    xml.push_str("</hs:sec>");
    Ok(xml.into_bytes())
}

fn build_template(
    skeleton: &[u8],
    title: &str,
    lines: &[&str],
    blank: bool,
    compile_fields: bool,
) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut package = HwpxPackage::from_bytes(skeleton, PackageLimits::default())?;
    let entry = package
        .entries
        .iter_mut()
        .find(|entry| entry.name == "Contents/section0.xml")
        .ok_or("missing section0.xml")?;
    entry.data = section(std::str::from_utf8(&entry.data)?, title, lines, blank)?;
    if compile_fields {
        let report = compile_document(&mut package, None)?;
        if !report.skipped.is_empty() {
            return Err(format!("uncompiled tokens: {:?}", report.skipped).into());
        }
        let entry = package
            .entries
            .iter_mut()
            .find(|entry| entry.name == "Contents/section0.xml")
            .ok_or("missing compiled section0.xml")?;
        let xml = std::str::from_utf8(&entry.data)?;
        let root_end = xml.find("><hp:p").ok_or("compiled section root missing")? + 1;
        let (root, body) = xml.split_at(root_end);
        const HP_DECL: &str = " xmlns:hp=\"http://www.hancom.co.kr/hwpml/2011/paragraph\"";
        if !root.contains(HP_DECL) {
            return Err("compiled section lost hp namespace".into());
        }
        entry.data = format!("{}{}", root, body.replace(HP_DECL, "")).into_bytes();
    }
    write_package(&package)
}

pub fn template(
    skeleton: &[u8],
    title: &str,
    lines: &[&str],
    blank: bool,
) -> Result<Vec<u8>, Box<dyn Error>> {
    build_template(skeleton, title, lines, blank, true)
}

#[allow(dead_code)] // Only the onboarding example needs the preserved marker source.
pub fn uncompiled_template(
    skeleton: &[u8],
    title: &str,
    lines: &[&str],
) -> Result<Vec<u8>, Box<dyn Error>> {
    build_template(skeleton, title, lines, false, false)
}
