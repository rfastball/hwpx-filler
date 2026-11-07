//! Reads raw worksheet cell text from the same frozen workbook bytes as calamine.

use super::{DataSourceError, fail};
use quick_xml::{
    NsReader, Reader as XmlReader,
    events::{BytesEnd, BytesStart, Event},
    name::ResolveResult,
};
use std::collections::HashMap;
use std::io::{Cursor, Read, Seek};
use std::sync::Arc;
use zip::ZipArchive;

type NumericCellValues = HashMap<(u32, u32), String>;

fn zip_text<RS: Read + Seek>(
    archive: &mut ZipArchive<RS>,
    name: &str,
) -> Result<String, DataSourceError> {
    let mut text = String::new();
    archive
        .by_name(name)
        .map_err(|err| fail(err.to_string()))?
        .read_to_string(&mut text)
        .map_err(|err| fail(err.to_string()))?;
    Ok(text)
}

fn xml_attr(
    event: &quick_xml::events::BytesStart<'_>,
    key: &str,
) -> Result<Option<String>, DataSourceError> {
    for attr in event.attributes() {
        let attr = attr.map_err(|err| fail(err.to_string()))?;
        if attr.key.as_ref() == key {
            return attr
                .normalized_value(quick_xml::XmlVersion::Implicit1_0)
                .map(|value| Some(value.into_owned()))
                .map_err(|err| fail(err.to_string()));
        }
    }
    Ok(None)
}

fn sheet_xml_name<RS: Read + Seek>(
    archive: &mut ZipArchive<RS>,
    sheet: &str,
) -> Result<(String, bool), DataSourceError> {
    let workbook = zip_text(archive, "xl/workbook.xml")?;
    let is_1904 = workbook_uses_1904(&workbook)?;
    let id = sheet_relation_id(&workbook, sheet)?
        .ok_or_else(|| fail(format!("워크시트 관계가 없습니다: {sheet}")))?;
    let relationships = zip_text(archive, "xl/_rels/workbook.xml.rels")?;
    let target = relationship_target(&relationships, &id)?
        .ok_or_else(|| fail(format!("워크시트 경로가 없습니다: {sheet}")))?;
    if target.contains("..") || target.contains('\\') {
        return Err(fail("워크시트 경로가 유효하지 않습니다"));
    }
    let name = if target.starts_with("/xl/") {
        target.trim_start_matches('/').into()
    } else if target.starts_with("xl/") {
        target
    } else {
        format!("xl/{target}")
    };
    Ok((name, is_1904))
}

pub(super) fn has_sheet_dimension(bytes: &[u8], sheet: &str) -> Result<bool, DataSourceError> {
    let mut archive = ZipArchive::new(Cursor::new(bytes)).map_err(|err| fail(err.to_string()))?;
    let (name, _) = sheet_xml_name(&mut archive, sheet)?;
    let xml = zip_text(&mut archive, &name)?;
    let mut reader = XmlReader::from_str(&xml);
    loop {
        match reader.read_event().map_err(|err| fail(err.to_string()))? {
            Event::Start(event) | Event::Empty(event)
                if event.local_name().as_ref() == "dimension" =>
            {
                return Ok(true);
            }
            Event::Start(event) if event.local_name().as_ref() == "sheetData" => {
                return Ok(false);
            }
            Event::Eof => return Ok(false),
            _ => {}
        }
    }
}

pub(super) fn has_sheet_rows(bytes: &[u8], sheet: &str) -> Result<bool, DataSourceError> {
    let mut archive = ZipArchive::new(Cursor::new(bytes)).map_err(|err| fail(err.to_string()))?;
    let (name, _) = sheet_xml_name(&mut archive, sheet)?;
    let xml = zip_text(&mut archive, &name)?;
    let mut reader = XmlReader::from_str(&xml);
    loop {
        match reader.read_event().map_err(|err| fail(err.to_string()))? {
            Event::Start(event) | Event::Empty(event) if event.local_name().as_ref() == "row" => {
                return Ok(true);
            }
            Event::Eof => return Ok(false),
            _ => {}
        }
    }
}

fn workbook_uses_1904(workbook: &str) -> Result<bool, DataSourceError> {
    let mut reader = XmlReader::from_str(workbook);
    loop {
        match reader.read_event().map_err(|err| fail(err.to_string()))? {
            Event::Start(event) | Event::Empty(event)
                if event.local_name().as_ref() == "workbookPr" =>
            {
                return Ok(matches!(
                    xml_attr(&event, "date1904")?.as_deref(),
                    Some("1" | "true")
                ));
            }
            Event::Eof => return Ok(false),
            _ => {}
        }
    }
}

fn sheet_relation_id(workbook: &str, sheet: &str) -> Result<Option<String>, DataSourceError> {
    let mut reader = NsReader::from_str(workbook);
    loop {
        match reader.read_event().map_err(|err| fail(err.to_string()))? {
            Event::Start(event) | Event::Empty(event) if event.local_name().as_ref() == "sheet" => {
                if xml_attr(&event, "name")?.as_deref() == Some(sheet) {
                    return sheet_rid(&reader, &event);
                }
            }
            Event::Eof => return Ok(None),
            _ => {}
        }
    }
}

fn sheet_rid(
    reader: &NsReader<&[u8]>,
    event: &BytesStart<'_>,
) -> Result<Option<String>, DataSourceError> {
    let mut id = None;
    for attr in event.attributes() {
        let attr = attr.map_err(|err| fail(err.to_string()))?;
        let (ns, local) = reader.resolver().resolve_attribute(attr.key);
        if local.as_ref() == "id"
            && matches!(ns,ResolveResult::Bound(uri)
            if ["http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                "http://purl.oclc.org/ooxml/officeDocument/relationships"].contains(&uri.0))
        {
            id = Some(
                attr.normalized_value(quick_xml::XmlVersion::Implicit1_0)
                    .map_err(|err| fail(err.to_string()))?
                    .into_owned(),
            );
        }
    }
    Ok(id)
}

fn relationship_target(relationships: &str, id: &str) -> Result<Option<String>, DataSourceError> {
    let mut reader = XmlReader::from_str(relationships);
    loop {
        match reader.read_event().map_err(|err| fail(err.to_string()))? {
            Event::Start(event) | Event::Empty(event)
                if event.local_name().as_ref() == "Relationship" =>
            {
                if xml_attr(&event, "Id")?.as_deref() == Some(id) {
                    return xml_attr(&event, "Target");
                }
            }
            Event::Eof => return Ok(None),
            _ => {}
        }
    }
}

fn cell_position(label: &str) -> Option<(u32, u32)> {
    let split = label.find(|ch: char| ch.is_ascii_digit())?;
    let (column, row) = label.split_at(split);
    if column.is_empty() || !column.bytes().all(|ch| ch.is_ascii_uppercase()) {
        return None;
    }
    let column = column.bytes().try_fold(0_u32, |acc, ch| {
        acc.checked_mul(26)?.checked_add(u32::from(ch - b'A' + 1))
    })?;
    let row = row.parse::<u32>().ok()?;
    Some((row.checked_sub(1)?, column.checked_sub(1)?))
}

#[derive(Default)]
struct NumericCells {
    cells: NumericCellValues,
    cell: Option<(u32, u32)>,
    numeric: bool,
    row: u32,
    col: u32,
    in_value: bool,
    value: String,
}
impl NumericCells {
    fn start(&mut self, event: &BytesStart<'_>) -> Result<(), DataSourceError> {
        if event.local_name().as_ref() == "row" {
            if let Some(number) =
                xml_attr(event, "r")?.and_then(|number| number.parse::<u32>().ok())
            {
                self.row = number.saturating_sub(1);
            }
        } else if event.local_name().as_ref() == "c" {
            let position = xml_attr(event, "r")?
                .and_then(|label| cell_position(&label))
                .unwrap_or((self.row, self.col));
            self.col = position.1;
            self.cell = Some(position);
            self.numeric = xml_attr(event, "t")?.is_none_or(|kind| kind == "n");
        } else if event.local_name().as_ref() == "v" && self.cell.is_some() {
            self.in_value = true;
            self.value.clear();
        }
        Ok(())
    }
    fn end(&mut self, event: &BytesEnd<'_>) {
        if event.local_name().as_ref() == "v" && self.in_value {
            if let Some(cell) = self.cell.filter(|_| self.numeric) {
                self.cells.insert(cell, self.value.clone());
            }
            self.in_value = false;
        } else if event.local_name().as_ref() == "c" {
            self.cell = None;
            self.numeric = false;
            self.col += 1;
        } else if event.local_name().as_ref() == "row" {
            self.row += 1;
            self.col = 0;
        }
    }
    fn accept(&mut self, event: Event<'_>) -> Result<(), DataSourceError> {
        match event {
            Event::Start(start) => self.start(&start)?,
            Event::Text(text) if self.in_value => self.value.push_str(text.as_ref()),
            Event::GeneralRef(reference) if self.in_value => {
                let ch = reference
                    .resolve_char_ref()
                    .map_err(|err| fail(err.to_string()))?
                    .ok_or_else(|| fail("숫자 셀에 알 수 없는 XML 참조가 있습니다"))?;
                self.value.push(ch);
            }
            Event::End(end) => self.end(&end),
            _ => {}
        }
        Ok(())
    }
}

pub(super) fn lexical_numeric_cells(
    bytes: Arc<[u8]>,
    sheet: &str,
) -> Result<(NumericCellValues, bool), DataSourceError> {
    let mut archive = ZipArchive::new(Cursor::new(bytes)).map_err(|err| fail(err.to_string()))?;
    let (name, is_1904) = sheet_xml_name(&mut archive, sheet)?;
    let xml = zip_text(&mut archive, &name)?;
    let mut reader = XmlReader::from_str(&xml);
    reader.config_mut().expand_empty_elements = true;
    let mut scan = NumericCells::default();
    loop {
        let event = reader.read_event().map_err(|err| fail(err.to_string()))?;
        if matches!(event, Event::Eof) {
            break;
        }
        scan.accept(event)?;
    }
    Ok((scan.cells, is_1904))
}
