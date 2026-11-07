//! Pure value display formatting with explicit readable/degraded results.

use crate::structure_scan::python_trim;
use chrono::{Datelike, NaiveDate, NaiveDateTime, Timelike};
use hwpx_core::text_extract::decimal_digit;
use num_bigint::BigInt;
use regex::Regex;
use rustpython_format::{CharLen, FormatPart, FormatSpec, FormatString, FromTemplate};
use std::ops::Deref;
use std::str::FromStr;
use std::sync::OnceLock;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RenderOutcome {
    pub text: String,
    pub readable: bool,
}

fn good(text: impl Into<String>) -> RenderOutcome {
    RenderOutcome {
        text: text.into(),
        readable: true,
    }
}
fn degraded(value: &str) -> RenderOutcome {
    RenderOutcome {
        text: value.into(),
        readable: false,
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum ParsedNumber {
    Integer(String),
    Float(f64),
}

struct PythonString(String);
impl Deref for PythonString {
    type Target = str;
    fn deref(&self) -> &str {
        &self.0
    }
}
impl CharLen for PythonString {
    fn char_len(&self) -> usize {
        self.0.chars().count()
    }
}

fn number_filter(value: &str) -> String {
    value
        .chars()
        .filter(|c| decimal_digit(*c).is_some() || *c == '.' || *c == '-')
        .collect()
}

fn ascii_decimal(value: &str) -> Option<String> {
    value
        .chars()
        .map(|ch| decimal_digit(ch).map(|digit| (b'0' + digit as u8) as char))
        .collect()
}

pub fn parse_number(value: &str) -> Option<ParsedNumber> {
    let filtered = number_filter(value);
    if filtered.is_empty() || filtered.trim_matches(['-', '.']).is_empty() {
        return None;
    }
    let normalized: String = filtered
        .chars()
        .map(|ch| decimal_digit(ch).map_or(ch, |digit| (b'0' + digit as u8) as char))
        .collect();
    if normalized.contains('.') {
        normalized.parse::<f64>().ok().map(ParsedNumber::Float)
    } else {
        let negative = normalized.starts_with('-');
        let digits = normalized.strip_prefix('-').unwrap_or(&normalized);
        if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
        let digits = digits.trim_start_matches('0');
        Some(ParsedNumber::Integer(if digits.is_empty() {
            "0".into()
        } else if negative {
            format!("-{digits}")
        } else {
            digits.into()
        }))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ParsedDateTime {
    pub year: u32,
    pub month: u32,
    pub day: u32,
    pub hour: u32,
    pub minute: u32,
}

fn date_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})").expect("static regex"))
}
fn time_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(\d{1,2}):(\d{2})").expect("static regex"))
}
fn days_in_month(year: u32, month: u32) -> Option<u32> {
    Some(match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400)) {
                29
            } else {
                28
            }
        }
        _ => return None,
    })
}

pub fn parse_dt(value: &str) -> Option<ParsedDateTime> {
    let groups = date_re().captures(value)?;
    let year = ascii_decimal(groups.get(1)?.as_str())?
        .parse::<u32>()
        .ok()?;
    let month = ascii_decimal(groups.get(2)?.as_str())?
        .parse::<u32>()
        .ok()?;
    let day = ascii_decimal(groups.get(3)?.as_str())?
        .parse::<u32>()
        .ok()?;
    let (hour, minute) = time_re().captures(value).map_or(Some((0, 0)), |time| {
        Some((
            ascii_decimal(time.get(1)?.as_str())?.parse::<u32>().ok()?,
            ascii_decimal(time.get(2)?.as_str())?.parse::<u32>().ok()?,
        ))
    })?;
    if !(1..=9999).contains(&year)
        || day == 0
        || day > days_in_month(year, month)?
        || hour > 23
        || minute > 59
    {
        return None;
    }
    Some(ParsedDateTime {
        year,
        month,
        day,
        hour,
        minute,
    })
}

fn parse_time(value: &str) -> Option<(u32, u32)> {
    let value = python_trim(value);
    let (hour, minute) = if let Some((hour, minute)) = value.split_once(':') {
        if !(1..=2).contains(&hour.chars().count())
            || minute.chars().count() != 2
            || !hour.chars().all(|c| decimal_digit(c).is_some())
            || !minute.chars().all(|c| decimal_digit(c).is_some())
        {
            return None;
        }
        (
            ascii_decimal(hour)?.parse().ok()?,
            ascii_decimal(minute)?.parse().ok()?,
        )
    } else {
        if value.chars().count() != 4 || !value.chars().all(|c| decimal_digit(c).is_some()) {
            return None;
        }
        let digits = ascii_decimal(value)?;
        (digits[..2].parse().ok()?, digits[2..].parse().ok()?)
    };
    (hour < 24 && minute < 60).then_some((hour, minute))
}

fn reserved_date(code: &str, value: &str, dt: ParsedDateTime) -> Option<String> {
    let time = time_re().find(value).map(|m| m.as_str());
    let (short, korean, include_time) = match code {
        "" => (false, false, false),
        "datetime" => (false, false, true),
        "y2" => (true, false, true),
        "y2_date" => (true, false, false),
        "ym" => return Some(format!("{}. {}.", dt.year, dt.month)),
        "kor" => (false, true, true),
        "kor_date" => (false, true, false),
        _ => return None,
    };
    let mut result = if korean {
        format!("{}년 {}월 {}일", dt.year, dt.month, dt.day)
    } else if short {
        format!("'{:02}.{}.{}.", dt.year % 100, dt.month, dt.day)
    } else {
        format!("{}. {}. {}.", dt.year, dt.month, dt.day)
    };
    if include_time && let Some(time) = time {
        result.push(' ');
        result.push_str(time);
    }
    Some(result)
}

fn day_of_year(dt: ParsedDateTime) -> u32 {
    (1..dt.month)
        .map(|month| days_in_month(dt.year, month).unwrap_or(0))
        .sum::<u32>()
        + dt.day
}

fn weekday(dt: ParsedDateTime) -> u32 {
    // Sakamoto: Sunday=0, matching `%w`.
    let table = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4];
    let year = dt.year - u32::from(dt.month < 3);
    (year + year / 4 - year / 100 + year / 400 + table[(dt.month - 1) as usize] + dt.day) % 7
}

fn strftime(code: &str, dt: ParsedDateTime) -> Option<String> {
    strftime_with_precision(code, dt, 0, 0)
}

/// Format a caller-supplied clock without the minute precision of parsed source dates.
/// This is used by filename patterns, whose `now` includes seconds and microseconds.
pub fn format_datetime_direct(code: &str, now: NaiveDateTime) -> Option<String> {
    let year = u32::try_from(now.year()).ok()?;
    if !(1..=9999).contains(&year) {
        return None;
    }
    strftime_with_precision(
        code,
        ParsedDateTime {
            year,
            month: now.month(),
            day: now.day(),
            hour: now.hour(),
            minute: now.minute(),
        },
        now.second(),
        now.nanosecond() / 1000,
    )
}

fn strftime_with_precision(
    code: &str,
    dt: ParsedDateTime,
    second: u32,
    microsecond: u32,
) -> Option<String> {
    let date = NaiveDate::from_ymd_opt(dt.year as i32, dt.month, dt.day)?;
    let wd = weekday(dt) as usize;
    const WEEKDAY_ABBR: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const WEEKDAY_FULL: [&str; 7] = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ];
    const MONTH_ABBR: [&str; 12] = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    const MONTH_FULL: [&str; 12] = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ];
    let mut result = String::new();
    let mut chars = code.chars();
    while let Some(ch) = chars.next() {
        if ch != '%' {
            result.push(ch);
            continue;
        }
        let directive = chars.next()?;
        if directive == '#' {
            let unpadded = match chars.next()? {
                'Y' => dt.year,
                'y' => dt.year % 100,
                'm' => dt.month,
                'd' => dt.day,
                'H' => dt.hour,
                'M' => dt.minute,
                'S' => second,
                'I' => (dt.hour + 11) % 12 + 1,
                'j' => day_of_year(dt),
                _ => return None,
            };
            result.push_str(&unpadded.to_string());
            continue;
        }
        match directive {
            '%' => result.push('%'),
            'Y' => result.push_str(&format!("{:04}", dt.year)),
            'y' => result.push_str(&format!("{:02}", dt.year % 100)),
            'm' => result.push_str(&format!("{:02}", dt.month)),
            'd' => result.push_str(&format!("{:02}", dt.day)),
            'e' => result.push_str(&dt.day.to_string()),
            'H' => result.push_str(&format!("{:02}", dt.hour)),
            'M' => result.push_str(&format!("{:02}", dt.minute)),
            'S' => result.push_str(&format!("{second:02}")),
            'I' => result.push_str(&format!("{:02}", (dt.hour + 11) % 12 + 1)),
            'p' => result.push_str(if dt.hour < 12 { "AM" } else { "PM" }),
            'j' => result.push_str(&format!("{:03}", day_of_year(dt))),
            'w' => result.push_str(&weekday(dt).to_string()),
            'u' => result.push_str(&date.weekday().number_from_monday().to_string()),
            'a' => result.push_str(WEEKDAY_ABBR[wd]),
            'A' => result.push_str(WEEKDAY_FULL[wd]),
            'b' => result.push_str(MONTH_ABBR[(dt.month - 1) as usize]),
            'B' => result.push_str(MONTH_FULL[(dt.month - 1) as usize]),
            'c' => result.push_str(&format!(
                "{} {} {:2} {:02}:{:02}:{second:02} {:04}",
                WEEKDAY_ABBR[wd],
                MONTH_ABBR[(dt.month - 1) as usize],
                dt.day,
                dt.hour,
                dt.minute,
                dt.year
            )),
            'x' => result.push_str(&format!(
                "{:02}/{:02}/{:02}",
                dt.month,
                dt.day,
                dt.year % 100
            )),
            'X' => result.push_str(&format!("{:02}:{:02}:{second:02}", dt.hour, dt.minute)),
            'U' => result.push_str(&format!("{:02}", (day_of_year(dt) - 1 + 7 - wd as u32) / 7)),
            'W' => result.push_str(&format!(
                "{:02}",
                (day_of_year(dt) - 1 + 7 - date.weekday().num_days_from_monday()) / 7
            )),
            'G' => result.push_str(&format!("{:04}", date.iso_week().year())),
            'V' => result.push_str(&format!("{:02}", date.iso_week().week())),
            'f' => result.push_str(&format!("{microsecond:06}")),
            'z' | 'Z' => {}
            'F' => result.push_str(&format!("{:04}-{:02}-{:02}", dt.year, dt.month, dt.day)),
            'T' => result.push_str(&format!("{:02}:{:02}:{second:02}", dt.hour, dt.minute)),
            _ => return None,
        }
    }
    Some(result)
}

fn format_numeric(number: &ParsedNumber, spec: &str) -> Option<String> {
    let coerce_negative_zero = spec.contains('z');
    let normalized = if coerce_negative_zero {
        spec.replacen('z', "", 1)
    } else {
        spec.to_string()
    };
    let parsed = FormatSpec::parse(&normalized).ok()?;
    let rendered = match number {
        ParsedNumber::Integer(integer) => parsed.format_int(&BigInt::from_str(integer).ok()?).ok(),
        ParsedNumber::Float(float) => parsed.format_float(*float).ok(),
    }?;
    if coerce_negative_zero
        && rendered.starts_with('-')
        && rendered
            .chars()
            .filter(|ch| ch.is_ascii_digit())
            .all(|ch| ch == '0')
    {
        Some(rendered.trim_start_matches('-').to_string())
    } else {
        Some(rendered)
    }
}

fn amount_template(code: &str, number: &ParsedNumber) -> Option<String> {
    let parsed = FormatString::from_str(code).ok()?;
    let mut out = String::new();
    let mut automatic_index = 0;
    let mut explicit = false;
    let mut automatic = false;
    for part in parsed.format_parts {
        match part {
            FormatPart::Literal(literal) => out.push_str(&literal),
            FormatPart::Field {
                field_name,
                conversion_spec,
                format_spec,
            } => {
                let (field_index, attribute) =
                    field_name.split_once('.').unwrap_or((&field_name, ""));
                if field_index.is_empty() {
                    automatic = true;
                    if explicit || automatic_index != 0 {
                        return None;
                    }
                    automatic_index += 1;
                } else {
                    explicit = true;
                    if automatic || field_index != "0" {
                        return None;
                    }
                }
                let spec = if format_spec == "{0}" {
                    format_numeric(number, "")?
                } else if format_spec.contains(['{', '}']) {
                    return None;
                } else {
                    format_spec
                };
                let selected = match attribute {
                    "" | "real" => number.clone(),
                    "imag" => match number {
                        ParsedNumber::Integer(_) => ParsedNumber::Integer("0".into()),
                        ParsedNumber::Float(_) => ParsedNumber::Float(0.0),
                    },
                    _ => return None,
                };
                let rendered = if let Some(conversion) = conversion_spec {
                    if !matches!(conversion, 's' | 'r' | 'a') {
                        return None;
                    }
                    let raw = match &selected {
                        ParsedNumber::Integer(integer) => integer.clone(),
                        ParsedNumber::Float(float) => format!("{float:?}"),
                    };
                    FormatSpec::parse(&spec)
                        .ok()?
                        .format_string(&PythonString(raw))
                        .ok()?
                } else {
                    format_numeric(&selected, &spec)?
                };
                out.push_str(&rendered);
            }
        }
    }
    Some(out)
}

fn digits(value: &str) -> Vec<char> {
    value
        .chars()
        .filter(|c| decimal_digit(*c).is_some())
        .collect()
}

fn digit_group(digits: &[char], start: usize, end: usize) -> String {
    digits[start..end].iter().collect()
}

fn starts_with_02(digits: &[char]) -> bool {
    digits.first() == Some(&'0') && digits.get(1) == Some(&'2')
}

fn mask_text(code: &str, value: &str) -> Option<String> {
    let digits = digits(value);
    match code {
        "phone" => match digits.len() {
            11 => Some(format!(
                "{}-{}-{}",
                digit_group(&digits, 0, 3),
                digit_group(&digits, 3, 7),
                digit_group(&digits, 7, 11)
            )),
            10 if starts_with_02(&digits) => Some(format!(
                "{}-{}-{}",
                digit_group(&digits, 0, 2),
                digit_group(&digits, 2, 6),
                digit_group(&digits, 6, 10)
            )),
            10 => Some(format!(
                "{}-{}-{}",
                digit_group(&digits, 0, 3),
                digit_group(&digits, 3, 6),
                digit_group(&digits, 6, 10)
            )),
            9 if starts_with_02(&digits) => Some(format!(
                "{}-{}-{}",
                digit_group(&digits, 0, 2),
                digit_group(&digits, 2, 5),
                digit_group(&digits, 5, 9)
            )),
            _ => None,
        },
        "biz" if digits.len() == 10 => Some(format!(
            "{}-{}-{}",
            digit_group(&digits, 0, 3),
            digit_group(&digits, 3, 5),
            digit_group(&digits, 5, 10)
        )),
        _ => None,
    }
}

pub fn render_outcome(kind: &str, code: &str, value: &str) -> RenderOutcome {
    match kind {
        "amount" => {
            let Some(number) = parse_number(value) else {
                return degraded(value);
            };
            amount_template(if code.is_empty() { "{:,}원" } else { code }, &number)
                .map_or_else(|| degraded(value), good)
        }
        "date" => {
            if ["", "datetime", "y2", "y2_date", "ym", "kor", "kor_date"].contains(&code) {
                let Some(dt) = parse_dt(value) else {
                    return degraded(value);
                };
                return good(reserved_date(code, value, dt).expect("reserved code"));
            }
            let dt = parse_dt(value).or_else(|| {
                parse_time(value).map(|(hour, minute)| ParsedDateTime {
                    year: 1900,
                    month: 1,
                    day: 1,
                    hour,
                    minute,
                })
            });
            dt.and_then(|dt| strftime(code, dt))
                .map_or_else(|| degraded(value), good)
        }
        "text" if !code.is_empty() => mask_text(code, value).map_or_else(|| degraded(value), good),
        _ => good(value),
    }
}

pub fn render(kind: &str, code: &str, value: &str) -> String {
    render_outcome(kind, code, value).text
}

pub fn presets(kind: &str) -> Vec<(&'static str, &'static str)> {
    match kind {
        "amount" => vec![
            ("원", ""),
            ("숫자", "{:,}"),
            ("소수 2자리", "{:,.2f}"),
            ("백분율", "{:.1%}"),
        ],
        "date" | "today" => vec![
            ("표준", ""),
            ("표준(시간 포함)", "datetime"),
            ("표준(약식)", "y2_date"),
            ("표준(약식·시간 포함)", "y2"),
            ("표준(연·월)", "ym"),
            ("한글", "kor_date"),
            ("한글(시간 포함)", "kor"),
            ("ISO", "%Y-%m-%d"),
            ("점", "%Y.%m.%d"),
            ("점(시간 포함)", "%Y.%m.%d %H:%M"),
            ("연-월", "%Y-%m"),
            ("시각", "%H:%M"),
            ("날짜+시각", "%Y-%m-%d %H:%M"),
            ("한글일시", "%Y년 %m월 %d일 %H:%M"),
        ],
        "text" => vec![("원문", ""), ("전화", "phone"), ("사업자번호", "biz")],
        _ => Vec::new(),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn format_outcome_preserves_python_presets_custom_specs_and_degraded_reads() {
        let examples = [
            ("amount", "", "150000000", "150,000,000원", true),
            ("amount", "{:,}", "150000000", "150,000,000", true),
            ("amount", "{:,}", "21,326,800원", "21,326,800", true),
            (
                "amount",
                "일금 {:,}원정",
                "150000000",
                "일금 150,000,000원정",
                true,
            ),
            ("amount", "{:,.2f}", "1234.5", "1,234.50", true),
            ("amount", "{:.1%}", "0.05", "5.0%", true),
            ("amount", "{:Q}", "100", "100", false),
            ("amount", "{:,}", "미정", "미정", false),
            ("amount", "{:,}원", "미정", "미정", false),
            ("date", "", "2026-06-15", "2026. 6. 15.", true),
            ("date", "", "2026-06-15 18:00", "2026. 6. 15.", true),
            (
                "date",
                "datetime",
                "2026-06-15 18:00",
                "2026. 6. 15. 18:00",
                true,
            ),
            ("date", "datetime", "2026-06-15", "2026. 6. 15.", true),
            ("date", "y2", "2026-07-03 09:00", "'26.7.3. 09:00", true),
            ("date", "y2", "2026-07-03", "'26.7.3.", true),
            ("date", "y2_date", "2026-07-03 09:00", "'26.7.3.", true),
            (
                "date",
                "kor",
                "2026-06-15 18:00",
                "2026년 6월 15일 18:00",
                true,
            ),
            ("date", "kor", "2026-06-15", "2026년 6월 15일", true),
            (
                "date",
                "kor_date",
                "2026-06-15 18:00",
                "2026년 6월 15일",
                true,
            ),
            ("date", "ym", "2026-10-12", "2026. 10.", true),
            ("date", "ym", "2026/10/12 09:00:00", "2026. 10.", true),
            ("date", "ym", "", "", false),
            ("date", "%Y.%m.%d", "2026-06-15", "2026.06.15", true),
            ("date", "%Y-%m-%d", "미정", "미정", false),
            (
                "date",
                "%Y-%m-%d %H:%M",
                "2026-6-5 18:00",
                "2026-06-05 18:00",
                true,
            ),
            ("date", "%H:%M", "1400", "14:00", true),
            ("date", "%H:%M", "18:00", "18:00", true),
            ("date", "ym", "미정", "미정", false),
            ("text", "", "아무 텍스트", "아무 텍스트", true),
            ("text", "phone", "01012345678", "010-1234-5678", true),
            ("text", "phone", "0212345678", "02-1234-5678", true),
            ("text", "phone", "0311234567", "031-123-4567", true),
            ("text", "biz", "1234567890", "123-45-67890", true),
            ("text", "phone", "123", "123", false),
            ("text", "%Y", "값", "값", false),
            ("const", "{:,}", "값", "값", true),
        ];
        for (kind, code, input, expected, readable) in examples {
            let result = render_outcome(kind, code, input);
            assert_eq!(
                result,
                RenderOutcome {
                    text: expected.into(),
                    readable
                },
                "{kind}/{code}/{input}"
            );
            assert_eq!(render(kind, code, input), expected);
        }
        assert_eq!(presets("today"), presets("date"));
        assert!(presets("const").is_empty());
        for (kind, expected) in [
            ("amount", vec![("원", ""), ("숫자", "{:,}")]),
            (
                "date",
                vec![
                    ("표준", ""),
                    ("표준(시간 포함)", "datetime"),
                    ("표준(약식)", "y2_date"),
                    ("표준(약식·시간 포함)", "y2"),
                    ("표준(연·월)", "ym"),
                    ("한글", "kor_date"),
                    ("한글(시간 포함)", "kor"),
                    ("점(시간 포함)", "%Y.%m.%d %H:%M"),
                    ("ISO", "%Y-%m-%d"),
                    ("시각", "%H:%M"),
                    ("날짜+시각", "%Y-%m-%d %H:%M"),
                    ("한글일시", "%Y년 %m월 %d일 %H:%M"),
                ],
            ),
            (
                "text",
                vec![("원문", ""), ("전화", "phone"), ("사업자번호", "biz")],
            ),
        ] {
            let offered = presets(kind);
            for pair in expected {
                assert!(offered.contains(&pair), "{kind}/{pair:?}");
            }
        }
        assert_eq!(parse_dt("2026-02-29"), None);
        assert_eq!(parse_number("--5"), None);
        assert_eq!(parse_number("²"), None);
        assert_eq!(render("amount", "{:,}", "１２３４"), "1,234");
        assert_eq!(
            render("date", "%Y-%m-%d", "２０２６-０６-１５"),
            "2026-06-15"
        );
        assert_eq!(
            render("text", "phone", "０１０１２３４５６７８"),
            "０１０-１２３４-５６７８"
        );
        assert_eq!(
            render_outcome("amount", "{0.real}", "150,000,000원"),
            good("150000000")
        );
        assert_eq!(
            render_outcome("amount", "{0.imag}", "150,000,000원"),
            good("0")
        );
        assert_eq!(render_outcome("amount", "{0:{0}}", "0.05"), good("0.05"));
        assert_eq!(render_outcome("amount", "{:z.1f}", "-0.04"), good("0.0"));
        assert_eq!(
            render("date", "%a %A %b %B", "2026-06-15"),
            "Mon Monday Jun June"
        );
        assert_eq!(
            render("date", "%U %W %G-W%V-%u", "2026-06-15"),
            "24 24 2026-W25-1"
        );
        assert_eq!(
            render("date", "%#d/%#m/%#Y|%f|%z%Z", "2026-06-15"),
            "15/6/2026|000000|"
        );
    }
}
