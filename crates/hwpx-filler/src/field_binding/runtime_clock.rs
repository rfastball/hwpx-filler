//! ISO clock syntax accepted by the existing Python datetime contract.

use super::{FieldBindingError, FieldBindingErrorKind, error, repr};
use chrono::{Datelike, NaiveDate, NaiveDateTime, NaiveTime, Weekday};

pub fn parse_runtime_clock(value: Option<&str>) -> Result<NaiveDateTime, FieldBindingError> {
    let Some(value) = value.filter(|value| !value.is_empty()) else {
        return Err(error(
            FieldBindingErrorKind::RuntimeClockUnavailable,
            "실행 시각이 주어지지 않았다",
        ));
    };
    parse_iso_clock(value).ok_or_else(|| {
        error(
            FieldBindingErrorKind::RuntimeClockUnavailable,
            format!("실행 시각이 유효한 ISO 8601 이 아니다: {}", repr(value)),
        )
    })
}

fn ascii_number(text: &str) -> Option<u32> {
    if text.is_empty() || !text.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    text.parse().ok()
}

fn extended_week_end(value: &str) -> Option<usize> {
    if value.get(8..9) != Some("-") {
        return Some(8);
    }
    if value.len() == 9 {
        return None;
    }
    // Python resolves YYYY-Www-## as a hyphen separator followed by an hour.
    if value.as_bytes().get(10).is_some_and(u8::is_ascii_digit) {
        Some(8)
    } else {
        Some(10)
    }
}

fn date_end(value: &str) -> Option<usize> {
    match value.get(4..5)? {
        "-" if value.get(5..6) == Some("W") => extended_week_end(value),
        "-" => Some(10),
        "W" => {
            let end = 7 + value
                .get(7..)?
                .bytes()
                .take_while(u8::is_ascii_digit)
                .count();
            Some(if end < 9 {
                end
            } else if end % 2 == 0 {
                7
            } else {
                8
            })
        }
        _ => Some(8),
    }
}

fn week_date(value: &str, year: i32, separated: bool) -> Option<NaiveDate> {
    let start = if separated { 6 } else { 5 };
    let week = ascii_number(value.get(start..start + 2)?)?;
    let tail = value.get(start + 2..)?;
    let day = if tail.is_empty() {
        1
    } else {
        let digit = if separated {
            tail.strip_prefix('-')?
        } else {
            tail
        };
        if digit.len() != 1 {
            return None;
        }
        ascii_number(digit)?
    };
    let weekday = [
        Weekday::Mon,
        Weekday::Tue,
        Weekday::Wed,
        Weekday::Thu,
        Weekday::Fri,
        Weekday::Sat,
        Weekday::Sun,
    ]
    .get(usize::try_from(day.checked_sub(1)?).ok()?)?;
    let date = NaiveDate::from_isoywd_opt(year, week, *weekday)?;
    (1..=9999).contains(&date.year()).then_some(date)
}

fn parse_iso_date(value: &str) -> Option<NaiveDate> {
    let year = i32::try_from(ascii_number(value.get(..4)?)?).ok()?;
    if !(1..=9999).contains(&year) {
        return None;
    }
    let separated = value.get(4..5) == Some("-");
    let start = if separated { 5 } else { 4 };
    if value.get(start..start + 1) == Some("W") {
        return week_date(value, year, separated);
    }
    let month = ascii_number(value.get(start..start + 2)?)?;
    let tail = value.get(start + 2..)?;
    let day = if separated {
        tail.strip_prefix('-')?
    } else {
        tail
    };
    if day.len() != 2 {
        return None;
    }
    NaiveDate::from_ymd_opt(year, month, ascii_number(day)?)
}

fn fraction_micros(digits: &str) -> Option<u32> {
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    let first = &digits[..digits.len().min(6)];
    Some(ascii_number(first)? * 10_u32.pow(6 - u32::try_from(first.len()).ok()?))
}

fn time_components(value: &str) -> Option<[u32; 4]> {
    let (whole, fraction) = value
        .split_once(['.', ','])
        .map_or((value, None), |(a, b)| (a, Some(b)));
    let compact = if whole.contains(':') {
        let parts = whole.split(':').collect::<Vec<_>>();
        if !(2..=3).contains(&parts.len()) || parts.iter().any(|part| part.len() != 2) {
            return None;
        }
        parts.concat()
    } else {
        whole.to_owned()
    };
    if ![2, 4, 6].contains(&compact.len()) || !compact.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    let mut components = [0; 4];
    for (index, chunk) in compact.as_bytes().chunks_exact(2).enumerate() {
        components[index] = u32::from(chunk[0] - b'0') * 10 + u32::from(chunk[1] - b'0');
    }
    if let Some(digits) = fraction {
        components[3] = fraction_micros(digits)?;
    }
    Some(components)
}

fn valid_offset(value: &str) -> bool {
    if value == "Z" {
        return true;
    }
    let Some(rest) = value.strip_prefix(['+', '-']) else {
        return false;
    };
    let Some([hour, minute, second, _]) = time_components(rest) else {
        return false;
    };
    // Python normalizes offset minutes/seconds before checking the one-day bound.
    hour * 3600 + minute * 60 + second < 86400
}

fn parse_iso_time(value: &str) -> Option<NaiveTime> {
    let zone_at = value
        .char_indices()
        .skip(1)
        .find(|(_, ch)| matches!(ch, '+' | '-' | 'Z'))
        .map(|(index, _)| index);
    let (time, zone) = zone_at.map_or((value, ""), |index| value.split_at(index));
    if !zone.is_empty() && !valid_offset(zone) {
        return None;
    }
    let [hour, minute, second, micros] = time_components(time)?;
    NaiveTime::from_hms_micro_opt(hour, minute, second, micros)
}

fn parse_iso_clock(value: &str) -> Option<NaiveDateTime> {
    let end = date_end(value)?;
    let date = parse_iso_date(value.get(..end)?)?;
    let tail = value.get(end..)?;
    if tail.is_empty() {
        return Some(date.and_time(NaiveTime::MIN));
    }
    let time = tail.get(tail.chars().next()?.len_utf8()..)?;
    Some(date.and_time(parse_iso_time(time)?))
}
