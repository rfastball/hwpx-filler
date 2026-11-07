//! CSV/XLSX/XLSM input adapter with explicit header, formula-cache and scalar policies.

use crate::data_source::{DataSource, DataSourceError, Record};
use crate::structure_scan::python_trim;
use calamine::{Data, Reader, Xlsx, open_workbook_from_rs};
use chrono::{Duration, NaiveDate, NaiveDateTime, NaiveTime, Timelike};
use indexmap::IndexSet;
use num_bigint::BigInt;
use regex::Regex;
use rustpython_format::FormatSpec;
use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::Arc;

#[path = "data_excel_xml.rs"]
mod data_excel_xml;
use data_excel_xml::{has_sheet_dimension, has_sheet_rows, lexical_numeric_cells};
type SnapshotWorkbook = Xlsx<Cursor<Arc<[u8]>>>;

fn fail(message: impl Into<String>) -> DataSourceError {
    DataSourceError(message.into())
}
const MISSING_VALUE_REPORT_LIMIT: usize = 5;

fn missing_formula_error(coordinates: &[(usize, usize)]) -> DataSourceError {
    let listed = coordinates
        .iter()
        .take(MISSING_VALUE_REPORT_LIMIT)
        .map(|(row, col)| format!("행 {row} 열 {col}"))
        .collect::<Vec<_>>()
        .join(", ");
    let rest = coordinates.len().saturating_sub(MISSING_VALUE_REPORT_LIMIT);
    let listed = if rest > 0 {
        format!("{listed} 외 {rest}개")
    } else {
        listed
    };
    fail(format!(
        "수식이 있는 셀에 계산값이 저장돼 있지 않습니다({listed}). 엑셀에서 이 파일을 열어 다시 저장하면 계산값이 함께 저장되니, 저장한 파일을 다시 불러오세요."
    ))
}

pub fn format_carries_time(number_format: Option<&str>) -> bool {
    let Some(number_format) = number_format.filter(|format| !format.is_empty()) else {
        return true;
    };
    let quoted = Regex::new("\"[^\"]*\"").expect("fixed regex");
    let code = quoted.replace_all(number_format, "").to_ascii_lowercase();
    code.contains("general")
        || ["h", "s", "am/pm", "a/p"]
            .iter()
            .any(|token| code.contains(token))
}
fn format_float(value: f64) -> String {
    FormatSpec::parse(".15g")
        .ok()
        .and_then(|spec| spec.format_float(value).ok())
        .unwrap_or_else(|| value.to_string())
}
fn lexical_number_text(raw: &str, value: f64) -> String {
    if raw
        .strip_prefix('-')
        .unwrap_or(raw)
        .bytes()
        .all(|byte| byte.is_ascii_digit())
        && let Ok(integer) = BigInt::from_str(raw)
    {
        return integer.to_string();
    }
    format_float(value)
}
fn cell_text_with_lexical(
    value: &Data,
    format: Option<&str>,
    raw: Option<&String>,
    is_1904: bool,
) -> String {
    if let Some(raw) = raw
        && let Ok(number) = raw.parse::<f64>()
    {
        match value {
            Data::Float(original) if !looks_like_date_format(format) => {
                return lexical_number_text(raw, number);
            }
            Data::Float(original) if number != *original => {
                return excel_datetime_text_epoch(number, false, format, is_1904)
                    .unwrap_or_else(|| format_float(number));
            }
            Data::DateTime(original) if number != original.as_f64() => {
                return excel_datetime_text_epoch(number, original.is_duration(), format, is_1904)
                    .unwrap_or_else(|| format_float(number));
            }
            Data::Int(_) => return lexical_number_text(raw, number),
            Data::Empty => {
                return if looks_like_date_format(format) {
                    excel_datetime_text_epoch(number, false, format, is_1904)
                        .unwrap_or_else(|| format_float(number))
                } else {
                    lexical_number_text(raw, number)
                };
            }
            _ => {}
        }
    }
    cell_text(value, format)
}
fn date_text(value: NaiveDateTime, number_format: Option<&str>) -> String {
    if value.time() == NaiveTime::MIN && !format_carries_time(number_format) {
        return value.date().format("%Y-%m-%d").to_string();
    }
    let mut out = value.format("%Y-%m-%d %H:%M:%S").to_string();
    let micros = value.and_utc().timestamp_subsec_micros();
    if micros != 0 {
        out.push_str(&format!(".{micros:06}"));
    }
    out
}
fn time_text(value: NaiveTime) -> String {
    let mut out = value.format("%H:%M:%S").to_string();
    let micros = value.nanosecond() / 1000;
    if micros != 0 {
        out.push_str(&format!(".{micros:06}"));
    }
    out
}
fn duration_text(millis: i64) -> String {
    let days = millis.div_euclid(86_400_000);
    let rest = millis.rem_euclid(86_400_000);
    let hour = rest / 3_600_000;
    let minute = rest % 3_600_000 / 60_000;
    let second = rest % 60_000 / 1000;
    let milli = rest % 1000;
    let body = if milli == 0 {
        format!("{hour}:{minute:02}:{second:02}")
    } else {
        format!("{hour}:{minute:02}:{second:02}.{milli:03}000")
    };
    if days == 0 {
        body
    } else if days == 1 {
        format!("1 day, {body}")
    } else {
        format!("{days} days, {body}")
    }
}
fn excel_datetime_text(
    serial: f64,
    is_duration: bool,
    number_format: Option<&str>,
) -> Option<String> {
    excel_datetime_text_epoch(serial, is_duration, number_format, false)
}
fn excel_epoch(is_1904: bool) -> Option<NaiveDateTime> {
    let (year, month, day) = if is_1904 {
        (1904, 1, 1)
    } else {
        (1899, 12, 30)
    };
    Some(NaiveDate::from_ymd_opt(year, month, day)?.and_time(NaiveTime::MIN))
}
fn excel_datetime_text_epoch(
    serial: f64,
    is_duration: bool,
    number_format: Option<&str>,
    is_1904: bool,
) -> Option<String> {
    if !serial.is_finite() {
        return None;
    }
    let millis = (serial * 86_400_000.0).round();
    if millis < i64::MIN as f64 || millis > i64::MAX as f64 {
        return None;
    }
    let millis = millis as i64;
    if is_duration {
        return Some(duration_text(millis));
    }
    let epoch = excel_epoch(is_1904)?;
    let adjusted = if !is_1904 && serial > 0.0 && serial < 60.0 {
        millis.checked_add(86_400_000)?
    } else {
        millis
    };
    let date = epoch.checked_add_signed(Duration::milliseconds(adjusted))?;
    if (0.0..1.0).contains(&serial) {
        return Some(time_text(date.time()));
    }
    Some(date_text(date, number_format))
}
fn looks_like_date_format(number_format: Option<&str>) -> bool {
    let Some(code) = number_format else {
        return false;
    };
    let quoted = Regex::new("\"[^\"]*\"").expect("fixed regex");
    let code = quoted.replace_all(code, "").to_ascii_lowercase();
    code.chars().any(|ch| ['y', 'd', 'h', 's'].contains(&ch))
        || code.contains("am/pm")
        || code.contains("a/p")
}
fn iso_cell_text(value: &str, number_format: Option<&str>) -> String {
    NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S%.f")
        .map(|date| date_text(date, number_format))
        .or_else(|_| {
            NaiveDate::parse_from_str(value, "%Y-%m-%d")
                .map(|date| date.format("%Y-%m-%d").to_string())
        })
        .or_else(|_| NaiveTime::parse_from_str(value, "%H:%M:%S%.f").map(time_text))
        .unwrap_or_else(|_| value.into())
}
fn numeric_cell_text(value: &Data, number_format: Option<&str>) -> String {
    match value {
        Data::Float(number) => {
            if looks_like_date_format(number_format) {
                excel_datetime_text(*number, false, number_format)
                    .unwrap_or_else(|| format_float(*number))
            } else {
                format_float(*number)
            }
        }
        Data::DateTime(value) => (if value.is_datetime() && value.as_f64() >= 1.0 {
            value
                .as_datetime()
                .map(|date| date_text(date, number_format))
        } else {
            None
        })
        .or_else(|| excel_datetime_text(value.as_f64(), value.is_duration(), number_format))
        .unwrap_or_else(|| value.to_string()),
        _ => unreachable!("numeric cell"),
    }
}
pub fn cell_text(value: &Data, number_format: Option<&str>) -> String {
    match value {
        Data::Empty => String::new(),
        Data::String(value) | Data::DurationIso(value) => value.clone(),
        Data::DateTimeIso(value) => iso_cell_text(value, number_format),
        Data::Bool(value) => if *value { "TRUE" } else { "FALSE" }.into(),
        Data::Int(value) => value.to_string(),
        Data::Float(_) | Data::DateTime(_) => numeric_cell_text(value, number_format),
        Data::Error(value) => value.to_string(),
    }
}
fn normalize_headers(raw: &[String]) -> Result<Vec<String>, DataSourceError> {
    let headers: Vec<_> = raw
        .iter()
        .map(|item| python_trim(item).to_owned())
        .collect();
    let blank: Vec<_> = headers
        .iter()
        .enumerate()
        .filter(|(_, item)| item.is_empty())
        .map(|(i, _)| (i + 1).to_string())
        .collect();
    if !blank.is_empty() {
        return Err(fail(format!(
            "빈 헤더 열은 사용할 수 없습니다: {}",
            blank.join(", ")
        )));
    }
    let mut seen = IndexSet::new();
    let mut duplicate = IndexSet::new();
    for header in &headers {
        if !seen.insert(header) {
            duplicate.insert(header);
        }
    }
    if !duplicate.is_empty() {
        return Err(fail(format!(
            "중복 헤더는 사용할 수 없습니다: {}",
            duplicate
                .into_iter()
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }
    Ok(headers)
}
fn append_record(
    headers: &[String],
    raw: &[String],
    row_number: usize,
    records: &mut Vec<Record>,
) -> Result<(), DataSourceError> {
    if raw.iter().all(|item| python_trim(item).is_empty()) {
        return Ok(());
    }
    if raw
        .iter()
        .skip(headers.len())
        .any(|item| !python_trim(item).is_empty())
    {
        return Err(fail(format!(
            "헤더보다 값이 많은 행입니다: 행 {row_number}, 헤더 {}열",
            headers.len()
        )));
    }
    records.push(
        headers
            .iter()
            .enumerate()
            .map(|(i, header)| (header.clone(), raw.get(i).cloned().unwrap_or_default()))
            .collect(),
    );
    Ok(())
}
#[derive(Default)]
struct CsvRows {
    rows: Vec<Vec<String>>,
    row: Vec<String>,
    field: String,
    quoted: bool,
    started: bool,
}
impl CsvRows {
    fn quoted_char(&mut self, ch: char, chars: &mut std::iter::Peekable<std::str::Chars<'_>>) {
        if ch == '"' {
            if chars.peek() == Some(&'"') {
                chars.next();
                self.field.push('"');
            } else {
                self.quoted = false;
            }
        } else {
            self.field.push(ch);
        }
    }
    fn newline(&mut self) {
        if self.started || !self.row.is_empty() {
            self.row.push(std::mem::take(&mut self.field));
            self.rows.push(std::mem::take(&mut self.row));
        } else {
            self.rows.push(Vec::new());
        }
        self.started = false;
    }
    fn unquoted_char(&mut self, ch: char, chars: &mut std::iter::Peekable<std::str::Chars<'_>>) {
        match ch {
            '"' if !self.started => {
                self.quoted = true;
                self.started = true;
            }
            ',' => {
                self.row.push(std::mem::take(&mut self.field));
                self.started = false;
            }
            '\r' | '\n' => {
                if ch == '\r' && chars.peek() == Some(&'\n') {
                    chars.next();
                }
                self.newline();
            }
            _ => {
                self.field.push(ch);
                self.started = true;
            }
        }
    }
    fn finish(mut self) -> Vec<Vec<String>> {
        if self.started || !self.row.is_empty() {
            self.row.push(self.field);
            self.rows.push(self.row);
        }
        self.rows
    }
}
fn csv_rows(text: &str) -> Vec<Vec<String>> {
    let mut rows = CsvRows::default();
    let mut chars = text.chars().peekable();
    while let Some(ch) = chars.next() {
        if rows.quoted {
            rows.quoted_char(ch, &mut chars);
        } else {
            rows.unquoted_char(ch, &mut chars);
        }
    }
    rows.finish()
}

pub fn sheet_overview(path: &Path) -> Result<Vec<(String, usize, usize)>, DataSourceError> {
    if path
        .extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("csv"))
    {
        return Ok(Vec::new());
    }
    let bytes: Arc<[u8]> = std::fs::read(path)
        .map_err(|err| fail(err.to_string()))?
        .into();
    let mut workbook: SnapshotWorkbook =
        open_workbook_from_rs::<SnapshotWorkbook, _>(Cursor::new(bytes.clone()))
            .map_err(|err| fail(err.to_string()))?;
    let mut out = Vec::new();
    for name in workbook.sheet_names() {
        let declared = has_sheet_dimension(&bytes, &name)?;
        let (rows, cols) = {
            let reader = workbook
                .worksheet_cells_reader(&name)
                .map_err(|err| fail(err.to_string()))?;
            let dim = reader.dimensions();
            if declared {
                (dim.end.0 as usize + 1, dim.end.1 as usize + 1)
            } else {
                (0, 0)
            }
        };
        out.push((name, rows, cols));
    }
    Ok(out)
}
pub fn ambiguous_sheets(path: &Path) -> Result<Vec<(String, usize, usize)>, DataSourceError> {
    let overview = sheet_overview(path)?;
    Ok(if overview.len() >= 2 {
        overview
    } else {
        Vec::new()
    })
}
pub fn ambiguous_sheet_error(path: &Path, prefix: &str) -> Option<String> {
    let sheets = ambiguous_sheets(path).ok()?;
    if sheets.is_empty() {
        return None;
    }
    let names = sheets
        .iter()
        .map(|(name, _, _)| name.as_str())
        .collect::<Vec<_>>()
        .join(", ");
    Some(format!(
        "{prefix}워크북에 시트가 여러 개입니다({names}). 「데이터 선택」의 「고정한 데이터」에서 시트를 지정해 다시 등록하세요."
    ))
}

fn no_header_row(
    values: &calamine::Range<Data>,
    bytes: &[u8],
    sheet: &str,
) -> Result<bool, DataSourceError> {
    // Explicit empty cells still form a header row and must reach header validation.
    Ok(values.end().is_none()
        && !has_sheet_dimension(bytes, sheet)?
        && !has_sheet_rows(bytes, sheet)?)
}

pub struct ExcelDataSource {
    pub path: PathBuf,
    pub sheet: Option<String>,
    pub header_row: usize,
    headers: Vec<String>,
    records: Vec<Record>,
    loaded: bool,
}
impl ExcelDataSource {
    pub fn new(
        path: impl Into<PathBuf>,
        sheet: Option<String>,
        header_row: usize,
    ) -> Result<Self, DataSourceError> {
        if header_row < 1 {
            return Err(fail("header_row는 1 이상의 정수여야 합니다."));
        }
        Ok(Self {
            path: path.into(),
            sheet,
            header_row,
            headers: Vec::new(),
            records: Vec::new(),
            loaded: false,
        })
    }
    fn load(&mut self) -> Result<(), DataSourceError> {
        if self.loaded {
            return Ok(());
        }
        if self
            .path
            .extension()
            .is_some_and(|extension| extension.eq_ignore_ascii_case("csv"))
        {
            self.load_csv()?;
        } else {
            self.load_xlsx()?;
        }
        self.loaded = true;
        Ok(())
    }
    fn load_csv(&mut self) -> Result<(), DataSourceError> {
        let bytes = std::fs::read(&self.path).map_err(|err| fail(err.to_string()))?;
        let bytes = bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes);
        let text = std::str::from_utf8(bytes).map_err(|err| fail(err.to_string()))?;
        let rows = csv_rows(text);
        if rows.len() < self.header_row {
            return Ok(());
        }
        self.headers = normalize_headers(&rows[self.header_row - 1])?;
        for (offset, row) in rows.iter().enumerate().skip(self.header_row) {
            append_record(&self.headers, row, offset + 1, &mut self.records)?;
        }
        Ok(())
    }
    fn load_xlsx(&mut self) -> Result<(), DataSourceError> {
        let bytes: Arc<[u8]> = std::fs::read(&self.path)
            .map_err(|err| fail(err.to_string()))?
            .into();
        let mut workbook: SnapshotWorkbook =
            open_workbook_from_rs::<SnapshotWorkbook, _>(Cursor::new(bytes.clone()))
                .map_err(|err| fail(err.to_string()))?;
        let name = self
            .sheet
            .as_ref()
            .filter(|name| !name.is_empty())
            .cloned()
            .or_else(|| workbook.sheet_names().first().cloned())
            .ok_or_else(|| fail("워크북에 시트가 없습니다."))?;
        let values = workbook
            .worksheet_range(&name)
            .map_err(|err| fail(err.to_string()))?;
        if no_header_row(&values, &bytes, &name)? {
            return Ok(());
        }
        let formulas = workbook
            .worksheet_formula(&name)
            .map_err(|err| fail(err.to_string()))?;
        let styles = workbook
            .worksheet_style(&name)
            .map_err(|err| fail(err.to_string()))?;
        let (rows, cols) = {
            let reader = workbook
                .worksheet_cells_reader(&name)
                .map_err(|err| fail(err.to_string()))?;
            let dim = reader.dimensions();
            // Valid XLSX sheets may omit <dimension>; the parsed value range still
            // records their actual cell extent even when the metadata says A1.
            let end = values.end().unwrap_or(dim.end);
            (
                dim.end.0.max(end.0) as usize + 1,
                dim.end.1.max(end.1) as usize + 1,
            )
        };
        if rows < self.header_row {
            return Ok(());
        }
        let (lexical, is_1904) = lexical_numeric_cells(bytes, &name)?;
        let header = self.header_row - 1;
        if (0..cols).any(|col| {
            formulas
                .get_value((header as u32, col as u32))
                .is_some_and(|formula| !formula.is_empty())
        }) {
            return Err(fail("헤더에는 Excel 수식을 사용할 수 없습니다."));
        }
        let raw_headers = (0..cols)
            .map(|col| {
                cell_text_with_lexical(
                    values
                        .get_value((header as u32, col as u32))
                        .unwrap_or(&Data::Empty),
                    None,
                    lexical.get(&(header as u32, col as u32)),
                    is_1904,
                )
            })
            .collect::<Vec<_>>();
        self.headers = normalize_headers(&raw_headers)?;
        let mut missing = Vec::new();
        let mut pending = Vec::new();
        for row in self.header_row..rows {
            let mut raw = Vec::new();
            for col in 0..cols {
                let value = values
                    .get_value((row as u32, col as u32))
                    .unwrap_or(&Data::Empty);
                if formulas
                    .get_value((row as u32, col as u32))
                    .is_some_and(|formula| !formula.is_empty())
                    && *value == Data::Empty
                {
                    missing.push((row + 1, col + 1));
                }
                let format = styles
                    .get((row as u32, col as u32))
                    .and_then(|style| style.number_format.as_ref())
                    .map(|format| format.format_code.as_str());
                raw.push(cell_text_with_lexical(
                    value,
                    format,
                    lexical.get(&(row as u32, col as u32)),
                    is_1904,
                ));
            }
            pending.push((row + 1, raw));
        }
        if !missing.is_empty() {
            return Err(missing_formula_error(&missing));
        }
        for (number, row) in pending {
            append_record(&self.headers, &row, number, &mut self.records)?;
        }
        Ok(())
    }
}
impl DataSource for ExcelDataSource {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
        self.load()?;
        Ok(self.records.clone())
    }
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
        self.load()?;
        Ok(self.headers.clone())
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::io::{Read, Write};

    fn workbook_with_sheet(source: &Path, sheet: &str) -> Vec<u8> {
        let file = std::fs::File::open(source).unwrap();
        let mut original = zip::ZipArchive::new(file).unwrap();
        let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
        for index in 0..original.len() {
            let mut entry = original.by_index(index).unwrap();
            if entry.is_dir() {
                continue;
            }
            let name = entry.name().unwrap().into_owned();
            let mut bytes = Vec::new();
            entry.read_to_end(&mut bytes).unwrap();
            writer
                .start_file(&name, zip::write::SimpleFileOptions::default())
                .unwrap();
            writer
                .write_all(if name == "xl/worksheets/sheet1.xml" {
                    sheet.as_bytes()
                } else {
                    &bytes
                })
                .unwrap();
        }
        writer.finish().unwrap().into_inner()
    }

    fn workbook_with_cells(source: &Path, missing_formula_cache: bool) -> Vec<u8> {
        let file = std::fs::File::open(source).unwrap();
        let mut original = zip::ZipArchive::new(file).unwrap();
        let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
        for index in 0..original.len() {
            let mut entry = original.by_index(index).unwrap();
            if entry.is_dir() {
                continue;
            }
            let name = entry.name().unwrap().into_owned();
            let mut bytes = Vec::new();
            entry.read_to_end(&mut bytes).unwrap();
            let bytes = match name.as_str() {
                "xl/workbook.xml" => String::from_utf8(bytes)
                    .unwrap()
                    .replace("<workbookPr/>", "<workbookPr date1904=\"1\"/>")
                    .into_bytes(),
                "xl/styles.xml" => String::from_utf8(bytes)
                    .unwrap()
                    .replace("<cellXfs count=\"1\">", "<cellXfs count=\"4\">")
                    .replace(
                        "</cellXfs>",
                        "<xf numFmtId=\"14\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/><xf numFmtId=\"21\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/><xf numFmtId=\"46\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/></cellXfs>",
                    )
                    .into_bytes(),
                "xl/worksheets/sheet1.xml" => format!(
                    "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><dimension ref=\"A1:G7\"/><sheetData><row r=\"1\">{}</row><row><c t=\"n\"><v>9007199254740993</v></c><c r=\"B2\" s=\"1\" t=\"n\"><v>1</v></c><c r=\"C2\" s=\"2\" t=\"n\"><v>0.5</v></c><c r=\"D2\" s=\"3\" t=\"n\"><v>1.25</v></c><c r=\"E2\"><f>1+1</f><v>2</v></c>{}<c r=\"G2\" t=\"d\"><v>2026-11-05T12:34:56.123</v></c></row><row/><row><c/><c><v>&#57;007199254740993</v></c></row><row><c r=\"B5\"><v>900719925474099&#51;</v></c></row><row><c r=\"B6\"><v>1&#50;.5</v></c></row><row><c r=\"B7\" s=\"1\"><v>1&#50;.5</v></c></row></sheetData></worksheet>",
                    ["integer", "date", "time", "duration", "cached", "uncached", "iso"]
                        .iter()
                        .enumerate()
                        .map(|(index, header)| format!("<c r=\"{}1\" t=\"inlineStr\"><is><t>{header}</t></is></c>", (b'A' + index as u8) as char))
                        .collect::<String>(),
                    if missing_formula_cache { "<c r=\"F2\"><f>1+2</f></c>" } else { "" },
                )
                .into_bytes(),
                _ => bytes,
            };
            writer
                .start_file(name, zip::write::SimpleFileOptions::default())
                .unwrap();
            writer.write_all(&bytes).unwrap();
        }
        writer.finish().unwrap().into_inner()
    }

    #[test]
    fn dimensionless_scenario_sheet_loads_all_cells_without_inventing_overview_size() {
        let workbook = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/scenario/data/조달_한글.xlsx");
        assert_eq!(
            sheet_overview(&workbook).unwrap(),
            vec![("Sheet".into(), 0, 0)]
        );
        let mut source = ExcelDataSource::new(&workbook, Some("Sheet".into()), 1).unwrap();
        let fields = source.fields().unwrap();
        assert_eq!(fields.len(), 25);
        assert_eq!(fields[0], "입찰공고번호");
        let records = source.records().unwrap();
        assert_eq!(records.len(), 3);
        assert_eq!(records[0]["입찰공고번호"], "2026-001");
        assert_eq!(records[0]["추정가격"], "45000000");
        let mut csv = ExcelDataSource::new(workbook.with_extension("csv"), None, 1).unwrap();
        assert_eq!(csv.records().unwrap(), records);
        assert_eq!(records[0]["공고명"], "친환경 선박용 소화장비 구매");

        let seed =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/multi_sheet.xlsx");
        let empty = std::env::temp_dir().join(format!(
            "hwpx-filler-empty-dimensionless-{}.xlsx",
            std::process::id()
        ));
        std::fs::write(
            &empty,
            workbook_with_sheet(
                &seed,
                "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData/></worksheet>",
            ),
        )
        .unwrap();
        let mut source = ExcelDataSource::new(&empty, Some("공고목록".into()), 1).unwrap();
        assert!(source.fields().unwrap().is_empty());
        assert!(source.records().unwrap().is_empty());
        assert_eq!(
            sheet_overview(&empty).unwrap()[0],
            ("공고목록".into(), 0, 0)
        );
        std::fs::remove_file(empty).unwrap();

        let blank_row = std::env::temp_dir().join(format!(
            "hwpx-filler-blank-dimensionless-{}.xlsx",
            std::process::id()
        ));
        std::fs::write(
            &blank_row,
            workbook_with_sheet(
                &seed,
                "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData><row r='1'><c r='A1'/></row></sheetData></worksheet>",
            ),
        )
        .unwrap();
        let mut source = ExcelDataSource::new(&blank_row, Some("공고목록".into()), 1).unwrap();
        assert!(
            source
                .fields()
                .unwrap_err()
                .to_string()
                .contains("빈 헤더 열")
        );
        std::fs::remove_file(blank_row).unwrap();
    }

    #[test]
    fn existing_workbook_and_bom_csv_share_ordered_records() {
        let workbook =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/multi_sheet.xlsx");
        assert_eq!(
            sheet_overview(&workbook).unwrap(),
            vec![("공고목록".into(), 3, 2), ("낙찰현황".into(), 4, 3)]
        );
        assert_eq!(ambiguous_sheets(&workbook).unwrap().len(), 2);
        let mut sheet = ExcelDataSource::new(&workbook, Some("공고목록".into()), 1).unwrap();
        assert_eq!(sheet.fields().unwrap().len(), 2);
        assert_eq!(sheet.records().unwrap().len(), 2);

        let csv =
            std::env::temp_dir().join(format!("hwpx-filler-excel-{}.csv", std::process::id()));
        std::fs::write(
            &csv,
            "\u{feff}공고명,금액,담당자\n장비,1000\n,,\n비품,2000,김\n",
        )
        .unwrap();
        let mut source = ExcelDataSource::new(&csv, None, 1).unwrap();
        assert_eq!(source.fields().unwrap(), vec!["공고명", "금액", "담당자"]);
        let rows = source.records().unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0]["담당자"], "");
        assert_eq!(rows[1]["담당자"], "김");
        assert_eq!(
            csv_rows("\nA,B\nx,y\n"),
            vec![
                Vec::<String>::new(),
                vec!["A".into(), "B".into()],
                vec!["x".into(), "y".into()]
            ]
        );
        assert_eq!(
            lexical_number_text("9007199254740993", 9_007_199_254_740_992.0),
            "9007199254740993"
        );
        assert_eq!(
            lexical_number_text("1234567890123456.0", 1_234_567_890_123_456.0),
            "1.23456789012346e+15"
        );
        let dated = csv.with_extension("xlsx");
        std::fs::write(&dated, workbook_with_cells(&workbook, false)).unwrap();
        let mut source = ExcelDataSource::new(&dated, Some("공고목록".into()), 1).unwrap();
        let row = &source.records().unwrap()[0];
        assert_eq!(row["integer"], "9007199254740993");
        assert_eq!(row["date"], "1904-01-02");
        assert_eq!(row["time"], "12:00:00");
        assert_eq!(row["duration"], "1 day, 6:00:00");
        assert_eq!(row["cached"], "2");
        assert_eq!(row["iso"], "2026-11-05 12:34:56.123000");
        assert_eq!(source.records().unwrap()[1]["date"], "9007199254740993");
        assert_eq!(source.records().unwrap()[2]["date"], "9007199254740993");
        assert_eq!(source.records().unwrap()[3]["date"], "12.5");
        assert_eq!(source.records().unwrap()[4]["date"], "1904-01-13 12:00:00");
        std::fs::write(&dated, workbook_with_cells(&workbook, true)).unwrap();
        let mut source = ExcelDataSource::new(&dated, Some("공고목록".into()), 1).unwrap();
        assert!(source.records().unwrap_err().0.contains("행 2 열 6"));
        std::fs::remove_file(dated).unwrap();

        std::fs::write(&csv, "\nA,B\nx,y\n").unwrap();
        let mut shifted = ExcelDataSource::new(&csv, None, 2).unwrap();
        assert_eq!(shifted.fields().unwrap(), vec!["A", "B"]);
        assert_eq!(shifted.records().unwrap()[0]["A"], "x");
        std::fs::remove_file(csv).unwrap();
    }

    #[test]
    fn headers_overflow_formula_summary_and_xlsm_refuse_or_read_without_loss() {
        let fixture =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/multi_sheet.xlsx");
        let base =
            std::env::temp_dir().join(format!("hwpx-filler-excel-boundary-{}", std::process::id()));
        let csv = base.with_extension("csv");
        let xlsx = base.with_extension("xlsx");
        let xlsm = base.with_extension("xlsm");
        let sheet = |last_column: char, headers: &str, rows: &str| {
            format!(
                "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><dimension ref=\"A1:{last_column}9\"/><sheetData><row r=\"1\">{headers}</row>{rows}</sheetData></worksheet>"
            )
        };
        let header = |column: &str, text: &str| {
            format!("<c r=\"{column}1\" t=\"inlineStr\"><is><t>{text}</t></is></c>")
        };
        assert!(ExcelDataSource::new(&csv, None, 0).is_err());
        let midnight = NaiveDate::from_ymd_opt(2026, 7, 22)
            .unwrap()
            .and_time(NaiveTime::MIN);
        assert_eq!(date_text(midnight, Some("yyyy-mm-dd")), "2026-07-22");
        assert_eq!(
            date_text(midnight, Some("yyyy-mm-dd hh:mm")),
            "2026-07-22 00:00:00"
        );
        for (headers, expected) in [
            (vec!["공고명", "", "담당자"], "빈 헤더"),
            (vec!["공고명", "공고명"], "중복 헤더"),
        ] {
            std::fs::write(&csv, format!("{}\n값,값,값\n", headers.join(","))).unwrap();
            assert!(
                ExcelDataSource::new(&csv, None, 1)
                    .unwrap()
                    .fields()
                    .unwrap_err()
                    .0
                    .contains(expected)
            );
            let xml = sheet(
                (b'A' + headers.len() as u8 - 1) as char,
                &headers
                    .iter()
                    .enumerate()
                    .map(|(index, name)| header(&((b'A' + index as u8) as char).to_string(), name))
                    .collect::<String>(),
                &format!(
                    "<row r=\"2\">{}</row>",
                    (0..headers.len())
                        .map(|index| format!(
                            "<c r=\"{}2\" t=\"inlineStr\"><is><t>값</t></is></c>",
                            (b'A' + index as u8) as char
                        ))
                        .collect::<String>()
                ),
            );
            std::fs::write(&xlsx, workbook_with_sheet(&fixture, &xml)).unwrap();
            let message = ExcelDataSource::new(&xlsx, Some("공고목록".into()), 1)
                .unwrap()
                .fields()
                .unwrap_err()
                .0;
            assert!(message.contains(expected), "{message}");
        }
        std::fs::write(&csv, "공고명\n장비,숨은 값\n").unwrap();
        assert!(
            ExcelDataSource::new(&csv, None, 1)
                .unwrap()
                .records()
                .unwrap_err()
                .0
                .contains("헤더보다 값이 많은 행")
        );
        let xml = sheet(
            'B',
            &header("A", "공고명"),
            "<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>장비</t></is></c><c r=\"B2\" t=\"inlineStr\"><is><t>숨은 값</t></is></c></row>",
        );
        std::fs::write(&xlsx, workbook_with_sheet(&fixture, &xml)).unwrap();
        assert!(
            ExcelDataSource::new(&xlsx, Some("공고목록".into()), 1)
                .unwrap()
                .records()
                .unwrap_err()
                .0
                .contains("빈 헤더")
        );

        let formulas = (2..=9)
            .map(|row| format!("<row r=\"{row}\"><c r=\"A{row}\"><f>1+{row}</f></c></row>"))
            .collect::<String>();
        let xml = sheet('A', &header("A", "합계"), &formulas);
        std::fs::write(&xlsx, workbook_with_sheet(&fixture, &xml)).unwrap();
        let message = ExcelDataSource::new(&xlsx, Some("공고목록".into()), 1)
            .unwrap()
            .records()
            .unwrap_err()
            .0;
        assert!(message.contains("행 2 열 1") && message.contains("행 6 열 1"));
        assert!(!message.contains("행 7 열 1"));
        assert!(
            message.contains("외 3개") && message.contains("엑셀에서 이 파일을 열어 다시 저장하면")
        );

        let formulas = "<row r=\"2\"><c r=\"A2\"><f>1+1</f></c></row><row r=\"3\"><c r=\"A3\"><f>1+2</f></c></row>";
        std::fs::write(
            &xlsx,
            workbook_with_sheet(&fixture, &sheet('A', &header("A", "합계"), formulas)),
        )
        .unwrap();
        let message = ExcelDataSource::new(&xlsx, Some("공고목록".into()), 1)
            .unwrap()
            .records()
            .unwrap_err()
            .0;
        assert!(message.contains("행 2 열 1") && message.contains("행 3 열 1"));
        assert!(!message.contains("외 "));

        let xml = sheet(
            'C',
            &format!(
                "{}{}{}",
                header("A", "공고명"),
                header("B", "금액"),
                header("C", "완료")
            ),
            "<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>전산장비</t></is></c><c r=\"B2\"><v>1000</v></c><c r=\"C2\" t=\"b\"><v>1</v></c></row><row r=\"3\"><c r=\"A3\" t=\"inlineStr\"><is><t>비품</t></is></c><c r=\"B3\"><v>1.25</v></c><c r=\"C3\" t=\"b\"><v>0</v></c></row>",
        );
        std::fs::write(&xlsm, workbook_with_sheet(&fixture, &xml)).unwrap();
        std::fs::write(
            &csv,
            "\u{feff}공고명,금액,완료\n전산장비,1000,TRUE\n비품,1.25,FALSE\n",
        )
        .unwrap();
        let mut macro_sheet = ExcelDataSource::new(&xlsm, Some("공고목록".into()), 1).unwrap();
        let mut csv_sheet = ExcelDataSource::new(&csv, None, 1).unwrap();
        assert_eq!(macro_sheet.fields().unwrap(), csv_sheet.fields().unwrap());
        assert_eq!(macro_sheet.records().unwrap(), csv_sheet.records().unwrap());
        std::fs::remove_file(csv).unwrap();
        std::fs::remove_file(xlsx).unwrap();
        std::fs::remove_file(xlsm).unwrap();
    }
}
