//! Key-scoped Nara public-data source with injected byte transport.

use crate::data_source::{DataSource, DataSourceError, Record};
use crate::fields::python_whitespace;
use crate::nara_acquire::{NaraGatewayPort, NaraGatewayResponse};
use crate::text_render::python_repr;
use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime, Timelike};
use hwpx_core::text_extract::decimal_digit;
use indexmap::{IndexMap, IndexSet};
use regex::Regex;
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};
use std::fmt;
use std::sync::Arc;

pub const BASE: &str =
    "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo";
pub const OK_RESULT_CODE: &str = "00";
pub const REDACTED: &str = "[REDACTED]";
pub const NARA_SERVICE_KEY_NAME: &str = "nara-service-key";

pub type NaraFetcher = Arc<dyn Fn(&str) -> Result<Vec<u8>, String> + Send + Sync>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NaraFetchError(pub String);
impl fmt::Display for NaraFetchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for NaraFetchError {}
fn fail(detail: impl Into<String>) -> NaraFetchError {
    NaraFetchError(detail.into())
}

fn quote_plus(text: &str) -> String {
    let mut encoded = String::new();
    for byte in text.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => {
                encoded.push(byte as char)
            }
            b' ' => encoded.push('+'),
            _ => encoded.push_str(&format!("%{byte:02X}")),
        }
    }
    encoded
}

/// Scrub a raw key, its URL encodings and unknown ServiceKey query values.
pub fn redact(text: &str, secret: Option<&str>) -> String {
    if text.is_empty() {
        return String::new();
    }
    let mut out = text.to_owned();
    if let Some(secret) = secret.filter(|s| !s.is_empty()) {
        let mut variants = vec![
            secret.to_owned(),
            quote_plus(secret),
            quote_plus(secret).replace('+', "%20"),
        ];
        variants.sort_by_key(|item| std::cmp::Reverse(item.len()));
        variants.dedup();
        for variant in variants {
            out = out.replace(&variant, REDACTED);
        }
    }
    let re = Regex::new(r#"(?i)(service[_-]?key=)([^&\s#"'<>]*)"#).expect("constant regex");
    re.replace_all(&out, format!("${{1}}{REDACTED}"))
        .into_owned()
}

pub fn validate_range(bgn: &str, end: &str) -> Option<String> {
    fn parse(value: &str) -> Option<NaiveDateTime> {
        static FIELDS: std::sync::OnceLock<Regex> = std::sync::OnceLock::new();
        let pattern = FIELDS.get_or_init(|| Regex::new(
            r"^(?P<Y>\d\d\d\d)(?P<m>1[0-2]|0[1-9]|[1-9])(?P<d>3[0-1]|[1-2]\d|0[1-9]|[1-9]| [1-9])(?P<H>2[0-3]|[0-1]\d|\d| \d)(?P<M>[0-5]\d|\d)$"
        ).expect("fixed Python strptime grammar"));
        pattern.captures(value)?;
        let mut digits = String::with_capacity(12);
        for ch in value.chars() {
            digits.push(char::from_digit(decimal_digit(ch)?, 10)?);
        }
        let parsed = NaiveDateTime::parse_from_str(&digits, "%Y%m%d%H%M").ok()?;
        (1..=9999).contains(&parsed.year()).then_some(parsed)
    }
    for (label, value) in [("시작", bgn), ("종료", end)] {
        if value.chars().count() != 12 || value.chars().any(|c| !c.is_numeric()) {
            return Some(format!(
                "{label} 일시 형식이 올바르지 않습니다(YYYYMMDDHHMM 12자리)."
            ));
        }
    }
    let (Some(begin), Some(finish)) = (parse(bgn), parse(end)) else {
        return Some("일시를 해석할 수 없습니다(YYYYMMDDHHMM).".into());
    };
    if finish < begin {
        return Some("종료 일시가 시작 일시보다 빠릅니다.".into());
    }
    if begin.year() == 9999 && begin.month() == 12 {
        return Some("year 10000 is out of range".into());
    }
    let (year, month) = if begin.month() == 12 {
        (begin.year() + 1, 1)
    } else {
        (begin.year(), begin.month() + 1)
    };
    let Some(next_month) = (if month == 12 {
        NaiveDate::from_ymd_opt(year + 1, 1, 1)
    } else {
        NaiveDate::from_ymd_opt(year, month + 1, 1)
    }) else {
        return Some("일시를 해석할 수 없습니다(YYYYMMDDHHMM).".into());
    };
    let last_day = (next_month - Duration::days(1)).day();
    let Some(limit) = NaiveDate::from_ymd_opt(year, month, begin.day().min(last_day))
        .and_then(|day| day.and_hms_opt(begin.hour(), begin.minute(), begin.second()))
    else {
        return Some("일시를 해석할 수 없습니다(YYYYMMDDHHMM).".into());
    };
    if finish > limit {
        return Some("조회 기간은 최대 1개월입니다(시작~종료 간격을 1개월 이내로).".into());
    }
    None
}

fn object<'a>(
    value: &'a Value,
    message: &str,
) -> Result<&'a serde_json::Map<String, Value>, NaraFetchError> {
    value.as_object().ok_or_else(|| fail(message))
}
fn envelope(raw: &[u8]) -> Result<Value, NaraFetchError> {
    serde_json::from_slice(raw).map_err(|error| fail(error.to_string()))
}
fn body(data: &Value) -> Result<&serde_json::Map<String, Value>, NaraFetchError> {
    let root = object(data, "응답 루트가 객체가 아닙니다.")?;
    let response = root
        .get("response")
        .filter(|value| !value.is_null())
        .unwrap_or(&Value::Null);
    let response = if response.is_null() {
        return Ok(empty_body());
    } else {
        object(response, "response가 객체가 아닙니다.")?
    };
    let body = response
        .get("body")
        .filter(|value| !value.is_null())
        .unwrap_or(&Value::Null);
    if body.is_null() {
        return Ok(empty_body());
    }
    object(body, "response.body가 객체가 아닙니다.")
}
fn empty_body() -> &'static serde_json::Map<String, Value> {
    static EMPTY: std::sync::OnceLock<serde_json::Map<String, Value>> = std::sync::OnceLock::new();
    EMPTY.get_or_init(serde_json::Map::new)
}
fn python_value(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        _ => python_repr(value),
    }
}

pub fn parse(raw: &[u8]) -> Result<Vec<Record>, NaraFetchError> {
    let data = envelope(raw)?;
    let body = body(&data)?;
    let mut items = body.get("items").unwrap_or(&Value::Null);
    if items.is_null() || items.as_str() == Some("") {
        return Ok(Vec::new());
    }
    if items.as_array().is_some_and(Vec::is_empty)
        || items.as_object().is_some_and(serde_json::Map::is_empty)
    {
        return Ok(Vec::new());
    }
    if let Some(map) = items.as_object()
        && let Some(inner) = map.get("item")
    {
        if map.len() != 1 {
            return Err(fail("items.item 봉투에 미등록 형제 키가 있습니다."));
        }
        items = inner;
        if items.is_null()
            || items.as_str() == Some("")
            || items.as_array().is_some_and(Vec::is_empty)
            || items.as_object().is_some_and(serde_json::Map::is_empty)
        {
            return Ok(Vec::new());
        }
    }
    let one;
    let rows = if let Some(list) = items.as_array() {
        list
    } else if items.is_object() {
        one = vec![items.clone()];
        &one
    } else {
        return Err(fail(
            "response.body.items.item은 레코드 객체 또는 목록이어야 합니다.",
        ));
    };
    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        let map = row
            .as_object()
            .ok_or_else(|| fail("items 목록에 레코드 객체가 아닌 값이 있습니다."))?;
        out.push(
            map.iter()
                .map(|(key, value)| (key.clone(), python_value(value)))
                .collect(),
        );
    }
    Ok(out)
}

pub fn result(raw: &[u8]) -> Result<(String, String), NaraFetchError> {
    let data = envelope(raw)?;
    let root = object(&data, "응답 루트가 객체가 아닙니다.")?;
    let response = root.get("response").and_then(Value::as_object);
    let header = response
        .and_then(|item| item.get("header"))
        .and_then(Value::as_object);
    Ok((
        header
            .and_then(|item| item.get("resultCode"))
            .map(python_value)
            .unwrap_or_default(),
        header
            .and_then(|item| item.get("resultMsg"))
            .map(python_value)
            .unwrap_or_default(),
    ))
}

fn page_meta(raw: &[u8]) -> Result<(u64, u64, u64), NaraFetchError> {
    let data = envelope(raw)?;
    let body = body(&data)?;
    let integer = |name: &str, positive: bool| -> Result<u64, NaraFetchError> {
        let value = body.get(name).unwrap_or(&Value::Null);
        if value.is_boolean() {
            return Err(fail(format!("{name}이 정수가 아닙니다.")));
        }
        let text = match value {
            Value::String(text) => text.trim_matches(python_whitespace),
            Value::Number(_) => {
                let number = value.as_u64().or_else(|| {
                    let float = value.as_f64()?;
                    (float.is_finite()
                        && float.fract() == 0.0
                        && (0.0..18_446_744_073_709_551_616.0).contains(&float))
                    .then_some(float as u64)
                });
                let Some(number) = number else {
                    return Err(fail(format!(
                        "{name}이 정수가 아닙니다: {}",
                        python_repr(value)
                    )));
                };
                if positive && number == 0 {
                    return Err(fail(format!("{name} 범위가 올바르지 않습니다: {number}.")));
                }
                return Ok(number);
            }
            _ => {
                return Err(fail(format!(
                    "{name}이 정수가 아닙니다: {}",
                    python_repr(value)
                )));
            }
        };
        let normalized = text
            .chars()
            .map(|ch| {
                decimal_digit(ch)
                    .and_then(|digit| char::from_digit(digit, 10))
                    .unwrap_or(ch)
            })
            .collect::<String>();
        let number: u64 = normalized
            .parse()
            .map_err(|_| fail(format!("{name}이 정수가 아닙니다: {}", python_repr(value))))?;
        if positive && number == 0 {
            return Err(fail(format!("{name} 범위가 올바르지 않습니다: {number}.")));
        }
        Ok(number)
    };
    Ok((
        integer("pageNo", true)?,
        integer("numOfRows", true)?,
        integer("totalCount", false)?,
    ))
}

fn auth_failure_detail(raw: &[u8]) -> Option<String> {
    let text = String::from_utf8_lossy(raw);
    let auth = Regex::new(r"<returnAuthMsg>\s*([^<]+?)\s*</returnAuthMsg>").ok()?;
    let code = Regex::new(r"<returnReasonCode>\s*([^<]+?)\s*</returnReasonCode>").ok()?;
    let message = auth.captures(&text)?.get(1)?.as_str();
    let suffix = code
        .captures(&text)
        .and_then(|capture| capture.get(1))
        .map(|m| format!(" (코드 {})", m.as_str()))
        .unwrap_or_default();
    Some(format!("인증 실패 — {message}{suffix}"))
}

pub struct NaraStdDataSource {
    pub service_key: String,
    pub bgn_dt: String,
    pub end_dt: String,
    pub num_rows: u64,
    pub page_no: u64,
    fetcher: NaraFetcher,
}
impl NaraStdDataSource {
    pub fn new(
        service_key: impl Into<String>,
        bgn_dt: impl Into<String>,
        end_dt: impl Into<String>,
        num_rows: u64,
        page_no: u64,
        fetcher: NaraFetcher,
    ) -> Self {
        Self {
            service_key: service_key.into(),
            bgn_dt: bgn_dt.into(),
            end_dt: end_dt.into(),
            num_rows,
            page_no,
            fetcher,
        }
    }
    pub fn url(&self, page_no: Option<u64>) -> String {
        format!(
            "{BASE}?ServiceKey={}&pageNo={}&numOfRows={}&type=json&bidNtceBgnDt={}&bidNtceEndDt={}",
            quote_plus(&self.service_key),
            page_no.unwrap_or(self.page_no),
            self.num_rows,
            quote_plus(&self.bgn_dt),
            quote_plus(&self.end_dt)
        )
    }
    pub fn redacted_url(&self) -> String {
        redact(&self.url(None), Some(&self.service_key))
    }
    fn request(&self, page: u64) -> Result<Vec<u8>, NaraFetchError> {
        (self.fetcher)(&self.url(Some(page)))
            .map_err(|item| fail(redact(&item, Some(&self.service_key))))
    }
    pub fn fetch_one(&self) -> Result<Vec<u8>, NaraFetchError> {
        self.request(self.page_no)
    }
    pub fn records_checked(&self) -> Result<Vec<Record>, NaraFetchError> {
        let run = || -> Result<Vec<Record>, NaraFetchError> {
            if let Some(detail) = validate_range(&self.bgn_dt, &self.end_dt) {
                return Err(fail(format!("조회 조건 오류: {detail}")));
            }
            if self.num_rows == 0 {
                return Err(fail("조회 조건 오류: num_rows는 1 이상 정수여야 합니다."));
            }
            if self.page_no == 0 {
                return Err(fail("조회 조건 오류: page_no는 1 이상 정수여야 합니다."));
            }
            let mut page = self.page_no;
            let mut expected_total = None;
            let mut response_size = None;
            let mut expected_remaining = 0;
            let mut last_page = 0;
            let mut records = Vec::new();
            let mut seen = HashSet::new();
            loop {
                let raw = self.request(page)?;
                let current = || -> Result<_, NaraFetchError> {
                    let (code, msg) = result(&raw)?;
                    if code != OK_RESULT_CODE {
                        return Err(fail(format!(
                            "API 오류 [{}] {}",
                            if code.is_empty() {
                                "코드 없음"
                            } else {
                                &code
                            },
                            if msg.is_empty() {
                                "메시지 없음"
                            } else {
                                &msg
                            }
                        )));
                    }
                    Ok((parse(&raw)?, page_meta(&raw)?))
                };
                let (page_records, (actual, size, total)) = current().map_err(|error| {
                    if let Some(detail) = auth_failure_detail(&raw) {
                        fail(detail)
                    } else {
                        error
                    }
                })?;
                if actual != page {
                    return Err(fail(format!(
                        "페이지 응답 불일치: 요청 {page}, 응답 {actual}."
                    )));
                }
                if expected_total.is_none() {
                    expected_total = Some(total);
                    response_size = Some(size);
                    let skipped = self.page_no.saturating_sub(1).saturating_mul(size);
                    expected_remaining = total.saturating_sub(skipped);
                    last_page = total.div_ceil(size);
                } else {
                    if let Some(previous) = expected_total
                        && total != previous
                    {
                        return Err(fail(format!(
                            "페이지 취득 중 totalCount 변경: {} → {total}.",
                            previous
                        )));
                    }
                    if let Some(previous) = response_size
                        && size != previous
                    {
                        return Err(fail(format!(
                            "페이지 취득 중 numOfRows 변경: {} → {size}.",
                            previous
                        )));
                    }
                }
                if page_records.len() as u64 > size {
                    return Err(fail(format!(
                        "페이지 {page} 레코드 수가 numOfRows를 초과했습니다: {} > {size}.",
                        page_records.len()
                    )));
                }
                for record in page_records.iter().cloned() {
                    let notice = record.get("bidNtceNo").map(String::as_str).unwrap_or("");
                    let identity = if !notice.is_empty() {
                        format!(
                            "notice\0{notice}\0{}",
                            record.get("bidNtceOrd").map(String::as_str).unwrap_or("")
                        )
                    } else {
                        let sorted: BTreeMap<_, _> = record.iter().collect();
                        format!(
                            "record\0{}",
                            serde_json::to_string(&sorted).map_err(|e| fail(e.to_string()))?
                        )
                    };
                    if !seen.insert(identity) {
                        return Err(fail(format!(
                            "페이지 {page}에 이전 페이지와 중복·겹침 레코드가 있습니다."
                        )));
                    }
                    records.push(record);
                }
                if self.page_no > last_page {
                    if !page_records.is_empty() {
                        return Err(fail("totalCount 범위 밖 페이지가 레코드를 반환했습니다."));
                    }
                    return Ok(Vec::new());
                }
                if page >= last_page {
                    if records.len() as u64 != expected_remaining {
                        return Err(fail(format!(
                            "totalCount와 실제 취득 건수가 일치하지 않습니다: 예상 {expected_remaining}, 실제 {}.",
                            records.len()
                        )));
                    }
                    return Ok(records);
                }
                if page_records.is_empty() {
                    return Err(fail(format!(
                        "totalCount 도달 전 중간 페이지 {page}가 비어 있습니다."
                    )));
                }
                page = page
                    .checked_add(1)
                    .ok_or_else(|| fail("페이지 번호가 범위를 벗어났습니다."))?;
            }
        };
        run().map_err(|item| fail(redact(&item.0, Some(&self.service_key))))
    }
}
impl DataSource for NaraStdDataSource {
    fn records(&mut self) -> Result<Vec<Record>, DataSourceError> {
        self.records_checked()
            .map_err(|item| DataSourceError(item.0))
    }
    fn fields(&mut self) -> Result<Vec<String>, DataSourceError> {
        let mut seen = IndexSet::new();
        for record in self.records()? {
            seen.extend(record.into_keys());
        }
        Ok(seen.into_iter().collect())
    }
    fn field_labels(&self) -> IndexMap<String, String> {
        default_field_labels()
    }
}

pub fn default_field_labels() -> IndexMap<String, String> {
    [
        ("bidNtceNo", "입찰공고번호"),
        ("bidNtceOrd", "입찰공고차수"),
        ("bidNtceNm", "공고명"),
        ("bidNtceSttusNm", "공고상태"),
        ("bidNtceDate", "공고일자"),
        ("bidNtceBgn", "공고시각"),
        ("bsnsDivNm", "업무구분"),
        ("cntrctCnclsMthdNm", "계약방법"),
        ("cntrctCnclsSttusNm", "계약체결형태"),
        ("bidwinrDcsnMthdNm", "낙찰자결정방법"),
        ("ntceInsttNm", "공고기관"),
        ("ntceInsttCd", "공고기관코드"),
        ("ntceInsttOfclDeptNm", "공고기관담당부서"),
        ("ntceInsttOfclNm", "공고기관담당자"),
        ("ntceInsttOfclTel", "공고기관담당자전화번호"),
        ("dmndInsttNm", "수요기관"),
        ("dmndInsttOfclDeptNm", "수요기관담당부서"),
        ("dmndInsttOfclNm", "수요기관담당자"),
        ("dmndInsttOfclTel", "수요기관담당자전화번호"),
        ("bidBeginDate", "입찰개시일자"),
        ("bidBeginTm", "입찰개시시각"),
        ("bidClseDate", "입찰마감일자"),
        ("bidClseTm", "입찰마감시각"),
        ("bidPrtcptQlfctRgstClseDate", "입찰참가자격등록마감일자"),
        ("bidPrtcptQlfctRgstClseTm", "입찰참가자격등록마감시각"),
        ("opengDate", "개찰일자"),
        ("opengTm", "개찰시각"),
        ("opengPlce", "개찰장소"),
        ("asignBdgtAmt", "배정예산"),
        ("presmptPrce", "추정가격"),
        ("rgnLmtYn", "지역제한여부"),
        ("prtcptPsblRgnNm", "참가가능지역"),
        ("indstrytyLmtYn", "업종제한여부"),
        ("bidprcPsblIndstrytyNm", "투찰가능업종"),
        ("bidNtceUrl", "공고URL"),
    ]
    .into_iter()
    .map(|(key, value)| (key.into(), value.into()))
    .collect()
}

/// One-page gateway for the acquisition view model; bulk pagination stays in NaraStdDataSource.
pub struct NaraStdGateway {
    pub fetcher: NaraFetcher,
}
impl NaraStdGateway {
    fn header(
        &self,
        key: &str,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<(Vec<u8>, String, String), String> {
        let source = NaraStdDataSource::new(key, bgn, end, num_rows, page_no, self.fetcher.clone());
        let raw = source.fetch_one().map_err(|error| error.to_string())?;
        let (code, message) = result(&raw)
            .map_err(|error| redact(&auth_failure_detail(&raw).unwrap_or(error.0), Some(key)))?;
        Ok((raw, redact(&code, Some(key)), redact(&message, Some(key))))
    }
}
impl NaraGatewayPort for NaraStdGateway {
    fn fetch(
        &self,
        key: &str,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<NaraGatewayResponse, String> {
        let (raw, code, message) = self.header(key, bgn, end, num_rows, page_no)?;
        let records = parse(&raw)
            .map_err(|error| redact(&auth_failure_detail(&raw).unwrap_or(error.0), Some(key)))?;
        Ok(NaraGatewayResponse {
            records,
            result_code: code,
            result_msg: message,
            field_labels: default_field_labels(),
        })
    }
    fn probe(
        &self,
        key: &str,
        bgn: &str,
        end: &str,
        num_rows: u64,
        page_no: u64,
    ) -> Result<NaraGatewayResponse, String> {
        let (_raw, code, message) = self.header(key, bgn, end, num_rows, page_no)?;
        Ok(NaraGatewayResponse {
            records: Vec::new(),
            result_code: code,
            result_msg: message,
            field_labels: default_field_labels(),
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn nara_fixture_and_paginated_fail_closed_boundary() {
        assert_secret_redaction();
        assert_response_shapes();
        assert_pagination_contract();
        assert_failures_are_redacted();
        let live = include_bytes!("../../../tests/fixtures/nara_std_response.json");
        let rows = parse(live).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0]["bidNtceNo"], "R26BK01561738");
        assert!(!rows[0]["bidNtceNm"].starts_with('\''));
        assert_eq!(result(live).unwrap().0, "00");
        let mut live_source = source(Arc::new(move |_| Ok(live.to_vec())));
        assert_eq!(live_source.records().unwrap(), rows);
        let fields = live_source.fields().unwrap();
        assert_eq!(fields[0], "bidNtceNo");
        assert!(fields.iter().any(|field| field == "presmptPrce"));
        assert!(validate_range("202601310000", "202602282359").is_some());
        assert!(validate_range("202601310000", "202602280000").is_none());
        assert!(validate_range("202612150000", "202701150000").is_none());
        assert!(validate_range("202606010000", "202606302359").is_none());
        for (begin, end) in [
            ("2026060100", "202606302359"),
            ("20260601000a", "202606302359"),
            ("202613010000", "202613020000"),
        ] {
            assert!(validate_range(begin, end).is_some());
        }
        assert!(
            validate_range("202606100000", "202606010000")
                .unwrap()
                .contains("빠릅니다")
        );
        assert!(
            validate_range("202606010000", "202607150000")
                .unwrap()
                .contains("1개월")
        );
        assert!(validate_range("２０２６０６０１００００", "２０２６０６３０２３５９").is_some());
        assert!(
            validate_range("²02606010000", "202606302359")
                .unwrap()
                .contains("해석")
        );
        assert!(validate_range("000001010000", "000001310000").is_some());
        assert!(validate_range("999912010000", "999912310000").is_some());
        assert!(validate_range("20260601090٠", "20260630235٩").is_none());

        let key = "aB3+xY/z9Q==pLm4Kn7";
        let page = |number: u64, notice: &str| {
            serde_json::to_vec(&json!({
                "response": {"header": {"resultCode":"00", "resultMsg":"정상"},
                    "body":{"pageNo": number,"numOfRows":1,"totalCount":2,
                        "items":{"item":[{"bidNtceNo":notice,"bidNtceNm":"공고"}]}}}
            }))
            .unwrap()
        };
        let first = page(1, "N1");
        let second = page(2, "N2");
        let fetcher: NaraFetcher = Arc::new(move |url| {
            if url.contains("pageNo=1") {
                Ok(first.clone())
            } else if url.contains("pageNo=2") {
                Ok(second.clone())
            } else {
                Err("unexpected page".into())
            }
        });
        let source = NaraStdDataSource::new(key, "202606010000", "202606302359", 1, 1, fetcher);
        assert_eq!(source.records_checked().unwrap().len(), 2);
        assert!(
            source
                .url(None)
                .contains("ServiceKey=aB3%2BxY%2Fz9Q%3D%3DpLm4Kn7")
        );
        assert!(!source.redacted_url().contains(key));

        let duplicate = page(2, "N1");
        let first = page(1, "N1");
        let key_error = format!("ServiceKey={key}");
        let fetcher: NaraFetcher = Arc::new(move |url| {
            if url.contains("pageNo=1") {
                Ok(first.clone())
            } else if url.contains("pageNo=2") {
                Ok(duplicate.clone())
            } else {
                Err(key_error.clone())
            }
        });
        let source = NaraStdDataSource::new(key, "202606010000", "202606302359", 1, 1, fetcher);
        assert!(
            source
                .records_checked()
                .unwrap_err()
                .0
                .contains("중복·겹침")
        );
        assert_eq!(
            redact(&format!("ServiceKey={key}"), Some(key)),
            "ServiceKey=[REDACTED]"
        );
        let malformed = serde_json::to_vec(&json!({"response":{
            "header":{"resultCode":"00","resultMsg":format!("echo {key}")},
            "body":{"items":42}
        }}))
        .unwrap();
        let gateway = NaraStdGateway {
            fetcher: Arc::new(move |_| Ok(malformed.clone())),
        };
        let probe = gateway
            .probe(key, "202606010000", "202606302359", 1, 1)
            .unwrap();
        assert_eq!(probe.result_code, "00");
        assert!(!probe.result_msg.contains(key));
        assert!(probe.result_msg.contains(REDACTED));
        assert!(
            gateway
                .fetch(key, "202606010000", "202606302359", 1, 1)
                .is_err()
        );
    }

    const KEY: &str = "aB3+xY/z9Q==pLm4Kn7";

    fn assert_secret_redaction() {
        for key in [KEY, "a b+c/한글=="] {
            let encoded = quote_plus(key);
            let percent_space = encoded.replace('+', "%20");
            for text in [
                format!("요청 실패: 키={key} 재시도"),
                format!("HTTP Error 500: https://host/x?ServiceKey={encoded}&type=json"),
                format!("encoded={percent_space}"),
            ] {
                let safe = redact(&text, Some(key));
                assert!(
                    !safe.contains(key)
                        && !safe.contains(&encoded)
                        && !safe.contains(&percent_space)
                );
                assert!(safe.contains(REDACTED));
            }
        }
        for name in [
            "ServiceKey",
            "serviceKey",
            "service_key",
            "SERVICE_KEY",
            "service-key",
        ] {
            assert_eq!(
                redact(&format!("http://h/x?{name}=SEKRET&pageNo=1"), None),
                format!("http://h/x?{name}=[REDACTED]&pageNo=1")
            );
        }
        for text in ["", "아무 비밀 없음"] {
            assert_eq!(redact(text, None), text);
            assert_eq!(redact(text, Some("")), text);
        }
    }

    fn source(fetcher: NaraFetcher) -> NaraStdDataSource {
        NaraStdDataSource::new(KEY, "202606010000", "202606302359", 2, 1, fetcher)
    }

    fn page(number: u64, total: u64, notices: &[&str]) -> Value {
        json!({"response": {
            "header": {"resultCode":"00", "resultMsg":"정상"},
            "body": {"pageNo":number, "numOfRows":2, "totalCount":total,
                "items":{"item":notices.iter().map(|notice|
                    json!({"bidNtceNo":notice,"bidNtceOrd":"000"})
                ).collect::<Vec<_>>()}}
        }})
    }

    fn bytes(value: &Value) -> Vec<u8> {
        serde_json::to_vec(value).unwrap()
    }

    fn assert_response_shapes() {
        let single = json!({"bidNtceNo":"X1","bidNtceNm":"단건"});
        assert_eq!(
            parse(&bytes(&json!({"response":{"body":{"items":single}}}))).unwrap(),
            vec![Record::from([
                ("bidNtceNo".into(), "X1".into()),
                ("bidNtceNm".into(), "단건".into())
            ])]
        );
        assert_eq!(
            parse(include_bytes!(
                "../../../tests/fixtures/nara_items_item_response.json"
            ))
            .unwrap(),
            vec![Record::from([
                ("bidNtceNo".into(), "R26BK09990001".into()),
                ("bidNtceOrd".into(), "000".into()),
                ("bidNtceNm".into(), "봉투 단건".into())
            ])]
        );
        for items in [
            json!([]),
            json!({}),
            Value::Null,
            json!(""),
            json!({"item":[]}),
            json!({"item":null}),
        ] {
            assert!(
                parse(&bytes(&json!({"response":{"body":{"items":items}}})))
                    .unwrap()
                    .is_empty()
            );
        }
        let bad = json!({"response":{"body":{"items":{"item":"not-a-list-or-record"}}}});
        assert!(parse(&bytes(&bad)).unwrap_err().0.contains("items.item"));
        let normal = page(1, 4, &["N1"]);
        assert_eq!(page_meta(&bytes(&normal)).unwrap(), (1, 2, 4));
        for (key, value) in [("totalCount", 2.9), ("pageNo", 1.5), ("numOfRows", 0.25)] {
            let mut bad = normal.clone();
            bad["response"]["body"][key] = json!(value);
            assert!(
                page_meta(&bytes(&bad))
                    .unwrap_err()
                    .0
                    .contains("정수가 아닙니다")
            );
        }
        let mut integral = normal;
        integral["response"]["body"]["totalCount"] = json!(4.0);
        assert_eq!(page_meta(&bytes(&integral)).unwrap(), (1, 2, 4));
    }

    fn assert_pagination_contract() {
        use std::sync::Mutex;
        let pages = [
            page(1, 5, &["N1", "N2"]),
            page(2, 5, &["N3", "N4"]),
            page(3, 5, &["N5"]),
        ];
        for start in [1, 2] {
            let calls = Arc::new(Mutex::new(Vec::new()));
            let observed = calls.clone();
            let responses = pages.clone();
            let mut src = source(Arc::new(move |url| {
                let number: usize = url
                    .split('&')
                    .find_map(|part| part.strip_prefix("pageNo="))
                    .unwrap()
                    .parse()
                    .unwrap();
                observed.lock().unwrap().push(number);
                Ok(bytes(&responses[number - 1]))
            }));
            src.page_no = start;
            let rows = src.records_checked().unwrap();
            let expected = if start == 1 {
                vec!["N1", "N2", "N3", "N4", "N5"]
            } else {
                vec!["N3", "N4", "N5"]
            };
            assert_eq!(
                rows.iter()
                    .map(|row| row["bidNtceNo"].as_str())
                    .collect::<Vec<_>>(),
                expected
            );
            assert_eq!(
                *calls.lock().unwrap(),
                (start as usize..=3).collect::<Vec<_>>()
            );
        }
        for (second, message) in [
            (page(2, 3, &["N2"]), "중복·겹침"),
            (page(2, 3, &[]), "totalCount"),
            (page(2, 4, &["N3", "N4"]), "totalCount 변경"),
        ] {
            let src = source(Arc::new(move |url| {
                Ok(bytes(&if url.contains("pageNo=1") {
                    page(1, 3, &["N1", "N2"])
                } else {
                    second.clone()
                }))
            }));
            assert!(
                src.records_checked().unwrap_err().0.contains(message),
                "{message}"
            );
        }
        let mut changed_size = page(2, 5, &["N3"]);
        changed_size["response"]["body"]["numOfRows"] = json!(1);
        for (second, message) in [
            (page(2, 5, &[]), "중간 페이지"),
            (page(3, 5, &["N3", "N4"]), "페이지 응답 불일치"),
            (changed_size, "numOfRows 변경"),
            (page(2, 5, &["N3", "N4", "N5"]), "초과"),
        ] {
            let src = source(Arc::new(move |url| {
                Ok(bytes(&if url.contains("pageNo=1") {
                    page(1, 5, &["N1", "N2"])
                } else {
                    second.clone()
                }))
            }));
            assert!(
                src.records_checked().unwrap_err().0.contains(message),
                "{message}"
            );
        }
        for notices in [vec![], vec!["unexpected"]] {
            let empty = notices.is_empty();
            let mut src = source(Arc::new(move |_| Ok(bytes(&page(4, 5, &notices)))));
            src.page_no = 4;
            let result = src.records_checked();
            if empty {
                assert!(result.unwrap().is_empty());
            } else {
                assert!(result.unwrap_err().0.contains("범위 밖"));
            }
        }
        let calls = Arc::new(Mutex::new(0));
        let observed = calls.clone();
        let gateway = NaraStdGateway {
            fetcher: Arc::new(move |_| {
                *observed.lock().unwrap() += 1;
                Ok(bytes(&pages[0]))
            }),
        };
        let response = gateway
            .fetch(KEY, "202606010000", "202606302359", 2, 1)
            .unwrap();
        assert_eq!(response.records.len(), 2);
        assert_eq!(response.result_code, "00");
        assert_eq!(response.field_labels["bidNtceNm"], "공고명");
        assert_eq!(*calls.lock().unwrap(), 1);
    }

    fn assert_redacted(message: &str) {
        assert!(!message.contains(KEY));
        assert!(!message.contains(&quote_plus(KEY)));
        assert!(message.contains(REDACTED));
    }

    fn assert_failures_are_redacted() {
        use std::sync::Mutex;
        for fail_at in [1, 2] {
            let calls = Arc::new(Mutex::new(0));
            let observed = calls.clone();
            let src = source(Arc::new(move |url| {
                let mut count = observed.lock().unwrap();
                *count += 1;
                if *count == fail_at {
                    Err(format!("timeout {KEY} {url}"))
                } else {
                    Ok(bytes(&page(1, 3, &["N1", "N2"])))
                }
            }));
            let error = src.records_checked().unwrap_err();
            assert_redacted(&error.0);
            assert!(std::error::Error::source(&error).is_none());
            assert_eq!(*calls.lock().unwrap(), fail_at);
            assert!(src.url(None).starts_with(BASE));
            assert!(
                src.url(None)
                    .contains("&type=json&bidNtceBgnDt=202606010000&bidNtceEndDt=202606302359")
            );
            assert_redacted(&src.redacted_url());
        }
        let xml = b"<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>";
        let error = source(Arc::new(move |_| Ok(xml.to_vec())))
            .records_checked()
            .unwrap_err();
        assert!(
            error.0.contains("SERVICE_KEY_IS_NOT_REGISTERED_ERROR") && error.0.contains("코드 30")
        );
        assert!(!error.0.contains(KEY));
        for items in [json!([]), json!([{"bidNtceNo":"X1"}])] {
            let raw = bytes(
                &json!({"response":{"header":{"resultCode":"07","resultMsg":"INVALID_REQUEST_PARAMETER_ERROR"},"body":{"items":items}}}),
            );
            let error = source(Arc::new(move |_| Ok(raw.clone())))
                .records_checked()
                .unwrap_err();
            assert!(error.0.contains("API 오류 [07]"));
        }
        let raw = bytes(&json!({"response":{"header":{
            "resultCode":format!("07-{KEY}-{}", quote_plus(KEY)),
            "resultMsg":format!("rejected ServiceKey={KEY}; encoded={}", quote_plus(KEY))},"body":{}}}));
        let fetcher: NaraFetcher = Arc::new(move |_| Ok(raw.clone()));
        assert_redacted(&source(fetcher.clone()).records_checked().unwrap_err().0);
        let response = NaraStdGateway { fetcher }
            .fetch(KEY, "202606010000", "202606302359", 100, 1)
            .unwrap();
        assert_redacted(&response.result_code);
        assert_redacted(&response.result_msg);
        assert!(response.result_msg.contains("ServiceKey=[REDACTED]"));
        let missing = source(Arc::new(|_| {
            Ok(br#"{"response":{"body":{"items":[]}}}"#.to_vec())
        }));
        assert!(
            missing
                .records_checked()
                .unwrap_err()
                .0
                .contains("코드 없음")
        );
        let empty = NaraStdGateway {
            fetcher: Arc::new(|_| Ok(Vec::new())),
        };
        assert!(
            !empty
                .fetch(KEY, "202606010000", "202606302359", 100, 1)
                .unwrap_err()
                .contains(KEY)
        );
        let mut invalid = source(Arc::new(|_| panic!("invalid query must not fetch")));
        invalid.bgn_dt = "202601010000".into();
        assert!(invalid.records_checked().unwrap_err().0.contains("1개월"));
    }
}
