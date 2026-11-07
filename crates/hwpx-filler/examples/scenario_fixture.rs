//! Regenerate the scenario HWPX, CSV, and text-only XLSX fixture set.
//! Run with `cargo run -p hwpx-filler --example scenario_fixture -- --out tests/corpus/scenario`.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

mod fixture_common;

use fixture_common::template;
use serde::Deserialize;
use std::error::Error;
use std::fs;
use std::io::{Cursor, Write};
use std::path::{Path, PathBuf};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

#[derive(Deserialize)]
struct Template {
    name: String,
    title: String,
    lines: Vec<String>,
}

#[derive(Deserialize)]
struct Source {
    fields: Vec<String>,
    records: Vec<Vec<String>>,
    templates: Vec<Template>,
}

type GeneratedFiles = Vec<(String, Vec<u8>)>;

fn source() -> Result<Source, Box<dyn Error>> {
    Ok(serde_json::from_str(include_str!(
        "../../../tests/corpus/scenario/fixture_source.json"
    ))?)
}

fn csv_cell(value: &str) -> String {
    if value.contains([',', '"', '\r', '\n']) {
        format!("\"{}\"", value.replace('"', "\"\""))
    } else {
        value.to_owned()
    }
}

fn csv(source: &Source) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut bytes = vec![0xef, 0xbb, 0xbf];
    for row in std::iter::once(&source.fields).chain(source.records.iter()) {
        if row.len() != source.fields.len() {
            return Err("scenario row width differs from header".into());
        }
        bytes.extend_from_slice(
            row.iter()
                .map(|value| csv_cell(value))
                .collect::<Vec<_>>()
                .join(",")
                .as_bytes(),
        );
        // 저장소 정본은 `.gitattributes`(eol=lf)대로 LF 다.
        bytes.extend_from_slice(b"\n");
    }
    Ok(bytes)
}

fn xml_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn xlsx(source: &Source) -> Result<Vec<u8>, Box<dyn Error>> {
    if source.fields.len() > 26
        || source
            .records
            .iter()
            .any(|row| row.len() != source.fields.len())
    {
        return Err("scenario XLSX column width is invalid".into());
    }
    let mut sheet = String::from(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>",
    );
    for (row_index, row) in std::iter::once(&source.fields)
        .chain(source.records.iter())
        .enumerate()
    {
        let number = row_index + 1;
        sheet.push_str(&format!("<row r=\"{number}\">"));
        for (column, value) in row.iter().enumerate() {
            let cell = format!("{}{number}", (b'A' + column as u8) as char);
            sheet.push_str(&format!(
                "<c r=\"{cell}\" t=\"inlineStr\"><is><t>{}</t></is></c>",
                xml_text(value)
            ));
        }
        sheet.push_str("</row>");
    }
    sheet.push_str("</sheetData></worksheet>");
    let parts = [
        (
            "[Content_Types].xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/><Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/></Types>",
        ),
        (
            "_rels/.rels",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>",
        ),
        (
            "xl/workbook.xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?><workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Sheet\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>",
        ),
        (
            "xl/_rels/workbook.xml.rels",
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/></Relationships>",
        ),
    ];
    let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    for (name, body) in parts {
        writer.start_file(name, options)?;
        writer.write_all(body.as_bytes())?;
    }
    writer.start_file("xl/worksheets/sheet1.xml", options)?;
    writer.write_all(sheet.as_bytes())?;
    Ok(writer.finish()?.into_inner())
}

fn write(out: &Path, kind: &str, name: &str, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    let dir = out.join(kind);
    fs::create_dir_all(&dir)?;
    fs::write(dir.join(name), bytes)?;
    Ok(())
}

fn generated(source: &Source, skeleton: &[u8]) -> Result<GeneratedFiles, Box<dyn Error>> {
    let mut files = Vec::new();
    for item in &source.templates {
        let lines = item.lines.iter().map(String::as_str).collect::<Vec<_>>();
        files.push((
            format!("templates/{}", item.name),
            template(skeleton, &item.title, &lines, true)?,
        ));
    }
    files.push(("data/조달_한글.csv".to_owned(), csv(source)?));
    files.push(("data/조달_한글.xlsx".to_owned(), xlsx(source)?));
    Ok(files)
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let out = match args.as_slice() {
        [] => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus/scenario"),
        [flag, path] if flag == "--out" => PathBuf::from(path),
        _ => return Err("usage: scenario_fixture [--out DIR]".into()),
    };
    let skeleton = fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus/real/form_purchase_v1.hwpx"),
    )?;
    for (name, bytes) in generated(&source()?, &skeleton)? {
        let (kind, filename) = name.split_once('/').ok_or("invalid fixture path")?;
        write(&out, kind, filename, &bytes)?;
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use calamine::{Data, Reader, Xlsx};

    #[test]
    fn generated_scenario_matches_committed_content_and_rows() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../");
        let base = root.join("tests/corpus/scenario");
        let skeleton = fs::read(root.join("tests/corpus/real/form_purchase_v1.hwpx")).unwrap();
        let source = source().unwrap();
        for (name, bytes) in generated(&source, &skeleton).unwrap() {
            let committed = fs::read(base.join(&name)).unwrap();
            if name.ends_with(".hwpx") {
                assert_eq!(committed, bytes, "{name}");
            } else if name.ends_with(".csv") {
                assert_eq!(committed, bytes, "{name}");
            } else {
                let read_rows = |blob| {
                    let mut workbook: Xlsx<_> = Xlsx::new(Cursor::new(blob)).unwrap();
                    workbook
                        .worksheet_range("Sheet")
                        .unwrap()
                        .rows()
                        .map(|row| {
                            row.iter()
                                .map(|cell| {
                                    assert!(matches!(cell, Data::String(_)));
                                    cell.to_string()
                                })
                                .collect::<Vec<_>>()
                        })
                        .collect::<Vec<_>>()
                };
                let values = read_rows(bytes);
                let expected = std::iter::once(source.fields.clone())
                    .chain(source.records.clone())
                    .collect::<Vec<_>>();
                assert_eq!(values, expected, "{name}");
                assert_eq!(read_rows(committed), values, "{name} committed rows");
            }
        }
    }
}
