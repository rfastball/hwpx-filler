//! Versioned, pure TXT value slicing with Python-compatible scalar coordinates.

use crate::fields::python_whitespace;
use crate::structure_scan::python_trim;
use crate::text_render::python_repr;
use serde_json::{Map, Number, Value};
use std::cmp::Ordering;
use std::fmt;
use std::str::FromStr;

pub const TEXT_SLICE_BEFORE: &str = "before";
pub const TEXT_SLICE_AFTER: &str = "after";
pub const TEXT_SLICE_BETWEEN: &str = "between";
pub const TEXT_SLICE_SPLIT: &str = "split";
pub const TEXT_SLICE_HEAD: &str = "head";
pub const TEXT_SLICE_TAIL: &str = "tail";
pub const TEXT_SLICE_CHARS: &str = "chars";
pub const TEXT_SLICE_REPLACE: &str = "replace";
pub const TEXT_SLICE_REMOVE: &str = "remove";
pub const ON_MISSING_EMPTY: &str = "empty";
pub const ON_MISSING_KEEP: &str = "keep";
pub const TEXT_SLICE_MODES: [&str; 9] = [
    "before", "after", "between", "split", "head", "tail", "chars", "replace", "remove",
];
pub const TEXT_SLICE_V4_MODES: [&str; 2] = ["chars", "split"];

pub(crate) fn keys(mode: &str) -> Option<&'static [&'static str]> {
    Some(match mode {
        TEXT_SLICE_BEFORE | TEXT_SLICE_AFTER => &["delimiter"],
        TEXT_SLICE_BETWEEN => &["open", "close"],
        TEXT_SLICE_SPLIT => &["delimiter", "index"],
        TEXT_SLICE_HEAD | TEXT_SLICE_TAIL => &["count"],
        TEXT_SLICE_CHARS => &["start", "length"],
        TEXT_SLICE_REPLACE => &["find", "replace"],
        TEXT_SLICE_REMOVE => &["find"],
        _ => return None,
    })
}

fn missable(mode: &str) -> bool {
    matches!(
        mode,
        TEXT_SLICE_BEFORE
            | TEXT_SLICE_AFTER
            | TEXT_SLICE_BETWEEN
            | TEXT_SLICE_SPLIT
            | TEXT_SLICE_CHARS
    )
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextSliceError(pub String);
impl TextSliceError {
    pub const CODE: &'static str = "UNSUPPORTED_TEXT_SLICE";
}
impl fmt::Display for TextSliceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for TextSliceError {}

fn fail(message: impl Into<String>) -> TextSliceError {
    TextSliceError(message.into())
}

/// Decimal magnitude is kept as text, so valid Python integers beyond i64/u64
/// remain accepted. Slicing only compares this magnitude with a finite string.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SliceInt {
    negative: bool,
    digits: String,
}

impl fmt::Display for SliceInt {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.negative {
            f.write_str("-")?;
        }
        f.write_str(&self.digits)
    }
}

impl SliceInt {
    fn from_value(value: &Value, what: &str) -> Result<Self, TextSliceError> {
        let Value::Number(number) = value else {
            return Err(fail(format!(
                "가공 {what} 값이 정수가 아님: {}",
                python_repr(value)
            )));
        };
        let raw = number.to_string();
        if raw.contains(['.', 'e', 'E']) {
            return Err(fail(format!(
                "가공 {what} 값이 정수가 아님: {}",
                python_repr(value)
            )));
        }
        let negative = raw.starts_with('-');
        let digits = raw.trim_start_matches('-').trim_start_matches('0');
        Ok(Self {
            negative: negative && !digits.is_empty(),
            digits: if digits.is_empty() {
                "0".into()
            } else {
                digits.into()
            },
        })
    }
    fn positive(&self) -> bool {
        !self.negative && self.digits != "0"
    }
    fn zero(&self) -> bool {
        self.digits == "0"
    }
    fn cmp_usize(&self, other: usize) -> Ordering {
        if self.negative {
            return Ordering::Less;
        }
        let other = other.to_string();
        self.digits
            .len()
            .cmp(&other.len())
            .then_with(|| self.digits.as_str().cmp(other.as_str()))
    }
    fn magnitude_usize(&self) -> Option<usize> {
        self.digits.parse().ok()
    }
    fn to_value(&self) -> Value {
        let raw = if self.negative {
            format!("-{}", self.digits)
        } else {
            self.digits.clone()
        };
        Value::Number(Number::from_str(&raw).expect("validated decimal integer"))
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SliceOutcome {
    pub text: String,
    pub span: Option<(usize, usize)>,
    pub missed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TextSlice {
    pub(crate) mode: String,
    pub(crate) start: Option<SliceInt>,
    pub(crate) length: Option<SliceInt>,
    pub(crate) delimiter: Option<String>,
    pub(crate) index: Option<SliceInt>,
    pub(crate) open: Option<String>,
    pub(crate) close: Option<String>,
    pub(crate) count: Option<SliceInt>,
    pub(crate) find: Option<String>,
    pub(crate) replace: Option<String>,
    pub(crate) on_missing: String,
}

fn optional_int(
    data: &Map<String, Value>,
    key: &str,
    what: &str,
) -> Result<Option<SliceInt>, TextSliceError> {
    data.get(key)
        .filter(|value| !value.is_null())
        .map(|value| SliceInt::from_value(value, what))
        .transpose()
}

fn optional_text(
    data: &Map<String, Value>,
    key: &str,
    what: &str,
) -> Result<Option<String>, TextSliceError> {
    match data.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(s)) => Ok(Some(s.clone())),
        Some(other) => Err(fail(format!(
            "가공 {what} 값이 문자열이 아님: {}",
            python_repr(other)
        ))),
    }
}

fn require_text(value: Option<&String>, empty_message: &str) -> Result<(), TextSliceError> {
    if value.is_some_and(|s| !s.is_empty()) {
        Ok(())
    } else {
        Err(fail(empty_message))
    }
}

impl TextSlice {
    pub fn mode(&self) -> &str {
        &self.mode
    }
    pub fn on_missing(&self) -> &str {
        &self.on_missing
    }
    pub(crate) fn slot_value(&self, key: &str) -> Option<String> {
        match key {
            "start" => self.start.as_ref().map(ToString::to_string),
            "length" => self.length.as_ref().map(ToString::to_string),
            "delimiter" => self.delimiter.clone(),
            "index" => self.index.as_ref().map(ToString::to_string),
            "open" => self.open.clone(),
            "close" => self.close.clone(),
            "count" => self.count.as_ref().map(ToString::to_string),
            "find" => self.find.clone(),
            "replace" => self.replace.clone(),
            _ => None,
        }
    }
    pub fn from_dict(value: &Value) -> Result<Self, TextSliceError> {
        let Value::Object(data) = value else {
            let type_name = match value {
                Value::Null => "NoneType",
                Value::Bool(_) => "bool",
                Value::Number(_) => "int",
                Value::String(_) => "str",
                Value::Array(_) => "list",
                Value::Object(_) => "dict",
            };
            return Err(fail(format!("가공 명세가 사전이 아님: {type_name}")));
        };
        let mode_value = data.get("mode").unwrap_or(&Value::Null);
        let Some(mode) = mode_value.as_str().filter(|mode| keys(mode).is_some()) else {
            return Err(fail(format!(
                "알 수 없는 가공 방식: {} (지원: ('before', 'after', 'between', 'split', 'head', 'tail', 'chars', 'replace', 'remove'))",
                python_repr(mode_value)
            )));
        };
        let allowed = keys(mode).expect("validated");
        let mut unknown: Vec<_> = data
            .keys()
            .filter(|key| {
                key.as_str() != "mode"
                    && !(missable(mode) && key.as_str() == "on_missing")
                    && !allowed.contains(&key.as_str())
            })
            .cloned()
            .collect();
        unknown.sort();
        if !unknown.is_empty() {
            return Err(fail(format!(
                "가공 명세에 모르는 키: [{}]",
                unknown
                    .iter()
                    .map(|key| python_repr(&Value::String(key.clone())))
                    .collect::<Vec<_>>()
                    .join(", ")
            )));
        }
        let on_missing_value = data
            .get("on_missing")
            .cloned()
            .unwrap_or(Value::String(ON_MISSING_EMPTY.into()));
        let Some(on_missing) = on_missing_value.as_str() else {
            return Err(fail(format!(
                "알 수 없는 빠짐 처리: {}",
                python_repr(&on_missing_value)
            )));
        };
        if on_missing != ON_MISSING_EMPTY && on_missing != ON_MISSING_KEEP {
            return Err(fail(format!(
                "알 수 없는 빠짐 처리: {}",
                python_repr(&on_missing_value)
            )));
        }
        let mut spec = Self {
            mode: mode.into(),
            start: None,
            length: None,
            delimiter: None,
            index: None,
            open: None,
            close: None,
            count: None,
            find: None,
            replace: None,
            on_missing: on_missing.into(),
        };
        // Preserve Python __post_init__ precedence: the first required field is
        // checked before a malformed later field can replace its diagnostic.
        match mode {
            TEXT_SLICE_BEFORE | TEXT_SLICE_AFTER | TEXT_SLICE_SPLIT => {
                spec.delimiter = optional_text(data, "delimiter", "구분자")?;
                require_text(spec.delimiter.as_ref(), "구분자를 비울 수 없습니다")?;
                if mode == TEXT_SLICE_SPLIT {
                    spec.index = optional_int(data, "index", "번째")?;
                }
            }
            TEXT_SLICE_BETWEEN => {
                spec.open = optional_text(data, "open", "여는 기준 글자")?;
                require_text(spec.open.as_ref(), "가공 기준 글자가 비었음")?;
                spec.close = optional_text(data, "close", "닫는 기준 글자")?;
            }
            TEXT_SLICE_HEAD | TEXT_SLICE_TAIL => {
                spec.count = optional_int(data, "count", "글자 수")?;
            }
            TEXT_SLICE_CHARS => {
                spec.start = optional_int(data, "start", "시작")?;
                if !spec.start.as_ref().is_some_and(SliceInt::positive) {
                    return Err(fail("시작은 1 이상이어야 합니다"));
                }
                spec.length = optional_int(data, "length", "글자 수")?;
            }
            TEXT_SLICE_REPLACE | TEXT_SLICE_REMOVE => {
                spec.find = optional_text(data, "find", "찾을 글자")?;
                require_text(spec.find.as_ref(), "찾을 글자가 비었음")?;
                if mode == TEXT_SLICE_REPLACE {
                    spec.replace = optional_text(data, "replace", "바꿀 글자")?;
                }
            }
            _ => unreachable!(),
        }
        spec.validate()?;
        Ok(spec)
    }

    fn validate(&self) -> Result<(), TextSliceError> {
        let mode = self.mode.as_str();
        if self.on_missing != ON_MISSING_EMPTY && !missable(mode) {
            return Err(fail(format!("{mode} 가공에는 빠짐 처리가 없음")));
        }
        match mode {
            TEXT_SLICE_BEFORE | TEXT_SLICE_AFTER | TEXT_SLICE_SPLIT => {
                require_text(self.delimiter.as_ref(), "구분자를 비울 수 없습니다")?
            }
            TEXT_SLICE_BETWEEN => {
                require_text(self.open.as_ref(), "가공 기준 글자가 비었음")?;
                require_text(self.close.as_ref(), "가공 기준 글자가 비었음")?;
            }
            TEXT_SLICE_HEAD | TEXT_SLICE_TAIL
                if !self.count.as_ref().is_some_and(SliceInt::positive) =>
            {
                return Err(fail("글자 수는 1 이상이어야 합니다"));
            }
            TEXT_SLICE_CHARS => {
                if !self.start.as_ref().is_some_and(SliceInt::positive) {
                    return Err(fail("시작은 1 이상이어야 합니다"));
                }
                if self.length.as_ref().is_some_and(|v| !v.positive()) {
                    return Err(fail("글자 수는 1 이상이어야 합니다"));
                }
            }
            TEXT_SLICE_REPLACE | TEXT_SLICE_REMOVE => {
                require_text(self.find.as_ref(), "찾을 글자가 비었음")?;
                if mode == TEXT_SLICE_REPLACE {
                    require_text(self.replace.as_ref(), "바꿀 글자가 비었음")?;
                }
            }
            _ => {}
        }
        if mode == TEXT_SLICE_SPLIT && self.index.as_ref().is_none_or(SliceInt::zero) {
            return Err(fail("번째는 0이 될 수 없습니다"));
        }
        Ok(())
    }

    pub fn missable(&self) -> bool {
        missable(&self.mode)
    }
    pub fn is_v4_expressible(&self) -> bool {
        TEXT_SLICE_V4_MODES.contains(&self.mode.as_str()) && self.on_missing == ON_MISSING_EMPTY
    }
    pub fn to_dict(&self) -> Value {
        let mut out = Map::new();
        out.insert("mode".into(), Value::String(self.mode.clone()));
        for key in keys(&self.mode).expect("validated mode") {
            let value = match *key {
                "start" => self.start.as_ref().map(SliceInt::to_value),
                "length" => self.length.as_ref().map(SliceInt::to_value),
                "delimiter" => self.delimiter.as_ref().map(|s| Value::String(s.clone())),
                "index" => self.index.as_ref().map(SliceInt::to_value),
                "open" => self.open.as_ref().map(|s| Value::String(s.clone())),
                "close" => self.close.as_ref().map(|s| Value::String(s.clone())),
                "count" => self.count.as_ref().map(SliceInt::to_value),
                "find" => self.find.as_ref().map(|s| Value::String(s.clone())),
                "replace" => self.replace.as_ref().map(|s| Value::String(s.clone())),
                _ => unreachable!(),
            };
            if let Some(value) = value {
                out.insert((*key).into(), value);
            }
        }
        if self.on_missing != ON_MISSING_EMPTY {
            out.insert("on_missing".into(), Value::String(self.on_missing.clone()));
        }
        Value::Object(out)
    }

    pub fn locate(&self, text: &str) -> Option<(usize, usize)> {
        let total = text.chars().count();
        match self.mode.as_str() {
            TEXT_SLICE_BEFORE | TEXT_SLICE_AFTER => {
                let delimiter = self.delimiter.as_ref()?;
                let at = text.find(delimiter)?;
                let position = text[..at].chars().count();
                if self.mode == TEXT_SLICE_BEFORE {
                    Some(tight(text, 0, position))
                } else {
                    Some(tight(text, position + delimiter.chars().count(), total))
                }
            }
            TEXT_SLICE_BETWEEN => {
                let open = self.open.as_ref()?;
                let close = self.close.as_ref()?;
                let at = text.find(open)?;
                let begin_byte = at + open.len();
                let end_byte = begin_byte + text[begin_byte..].find(close)?;
                Some(tight(
                    text,
                    text[..begin_byte].chars().count(),
                    text[..end_byte].chars().count(),
                ))
            }
            TEXT_SLICE_SPLIT => {
                let delimiter = self.delimiter.as_ref()?;
                let index = self.index.as_ref()?;
                let mut parts = Vec::new();
                let mut cursor = 0;
                while let Some(relative) = text[cursor..].find(delimiter) {
                    let at = cursor + relative;
                    parts.push((text[..cursor].chars().count(), text[..at].chars().count()));
                    cursor = at + delimiter.len();
                }
                parts.push((text[..cursor].chars().count(), total));
                let position = if index.negative {
                    let magnitude = index.magnitude_usize()?;
                    parts.len().checked_sub(magnitude)?
                } else {
                    let positive = index.magnitude_usize()?;
                    positive.checked_sub(1)?
                };
                parts
                    .get(position)
                    .map(|&(begin, end)| tight(text, begin, end))
            }
            TEXT_SLICE_HEAD => Some((
                0,
                self.count
                    .as_ref()?
                    .magnitude_usize()
                    .unwrap_or(total)
                    .min(total),
            )),
            TEXT_SLICE_TAIL => Some((
                total.saturating_sub(self.count.as_ref()?.magnitude_usize().unwrap_or(total)),
                total,
            )),
            TEXT_SLICE_CHARS => {
                let start = self.start.as_ref()?;
                if start.cmp_usize(total) == Ordering::Greater {
                    return None;
                }
                let begin = start.magnitude_usize()?.checked_sub(1)?;
                if begin >= total {
                    return None;
                }
                let remaining = total - begin;
                let length = self
                    .length
                    .as_ref()
                    .and_then(SliceInt::magnitude_usize)
                    .unwrap_or(remaining);
                Some((begin, begin + length.min(remaining)))
            }
            _ => None,
        }
    }

    pub fn evaluate(&self, text: &str) -> SliceOutcome {
        if self.mode == TEXT_SLICE_REPLACE || self.mode == TEXT_SLICE_REMOVE {
            let find = self.find.as_deref().expect("validated");
            let replace = self.replace.as_deref().unwrap_or("");
            return SliceOutcome {
                text: python_trim(&text.replace(find, replace)).into(),
                span: None,
                missed: false,
            };
        }
        if let Some((start, end)) = self.locate(text) {
            let begin = char_byte(text, start);
            let finish = char_byte(text, end);
            SliceOutcome {
                text: text[begin..finish].into(),
                span: Some((start, end)),
                missed: false,
            }
        } else {
            SliceOutcome {
                text: if self.on_missing == ON_MISSING_KEEP {
                    text.into()
                } else {
                    String::new()
                },
                span: None,
                missed: true,
            }
        }
    }
    pub fn apply(&self, text: &str) -> String {
        self.evaluate(text).text
    }
}

fn char_byte(text: &str, index: usize) -> usize {
    text.char_indices()
        .nth(index)
        .map_or(text.len(), |(byte, _)| byte)
}

fn tight(text: &str, mut begin: usize, mut end: usize) -> (usize, usize) {
    let chars: Vec<char> = text.chars().collect();
    while begin < end && python_whitespace(chars[begin]) {
        begin += 1;
    }
    while end > begin && python_whitespace(chars[end - 1]) {
        end -= 1;
    }
    (begin, end)
}

pub fn text_slice_from_payload(data: Option<&Value>) -> Result<Option<TextSlice>, TextSliceError> {
    data.filter(|value| !value.is_null())
        .map(TextSlice::from_dict)
        .transpose()
}

pub fn apply_text_slice(spec: Option<&TextSlice>, text: &str) -> String {
    spec.map_or_else(|| text.into(), |spec| spec.apply(text))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn each_slice_mode_preserves_codepoint_spans_and_serialized_shape() {
        let examples = [
            (
                json!({"mode":"before","delimiter":"-"}),
                " 앞 -뒤 ",
                "앞",
                Some((1, 2)),
            ),
            (
                json!({"mode":"after","delimiter":"-"}),
                "앞- 뒤 ",
                "뒤",
                Some((3, 4)),
            ),
            (
                json!({"mode":"between","open":"(","close":")"}),
                "x( 한글 )z",
                "한글",
                Some((3, 5)),
            ),
            (
                json!({"mode":"split","delimiter":",","index":-1}),
                "a, 💡 ,끝",
                "끝",
                Some((6, 7)),
            ),
            (
                json!({"mode":"head","count":2}),
                "💡ab",
                "💡a",
                Some((0, 2)),
            ),
            (json!({"mode":"tail","count":2}), "💡ab", "ab", Some((1, 3))),
            (
                json!({"mode":"chars","start":2,"length":2}),
                "💡ab",
                "ab",
                Some((1, 3)),
            ),
            (
                json!({"mode":"replace","find":"a","replace":"b"}),
                " aa ",
                "bb",
                None,
            ),
            (json!({"mode":"remove","find":"a"}), " a b a ", "b", None),
        ];
        for (encoded, text, expected, span) in examples {
            let spec = TextSlice::from_dict(&encoded).unwrap();
            assert_eq!(spec.to_dict(), encoded);
            assert_eq!(
                spec.evaluate(text),
                SliceOutcome {
                    text: expected.into(),
                    span,
                    missed: false
                }
            );
        }
        assert_eq!(apply_text_slice(None, " 그대로 "), " 그대로 ");
        let huge = TextSlice::from_dict(
            &serde_json::from_str::<Value>(
                r#"{"mode":"head","count":999999999999999999999999999999999999999}"#,
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(huge.apply("짧음"), "짧음");
    }

    #[test]
    fn malformed_specs_reject_and_missing_policy_does_not_guess() {
        let invalid = [
            (json!({"mode":"chars","start":true}), "정수가 아님"),
            (
                json!({"mode":"chars","start":1,"length":0}),
                "글자 수는 1 이상",
            ),
            (json!({"mode":"split","delimiter":"-"}), "번째는 0"),
            (
                json!({"mode":"between","open":"(","close":")","start":1}),
                "모르는 키",
            ),
            (json!({"mode":"remove","find":""}), "찾을 글자가 비었음"),
            (
                json!({"mode":"head","count":2,"on_missing":"keep"}),
                "모르는 키",
            ),
        ];
        for (value, expected) in invalid {
            assert!(
                TextSlice::from_dict(&value)
                    .unwrap_err()
                    .0
                    .contains(expected),
                "{value}"
            );
        }
        let spec =
            TextSlice::from_dict(&json!({"mode":"chars","start":50,"on_missing":"keep"})).unwrap();
        assert_eq!(
            spec.evaluate(" 💡 "),
            SliceOutcome {
                text: " 💡 ".into(),
                span: None,
                missed: true
            }
        );
        assert!(spec.to_dict().get("on_missing").is_some());
    }

    #[test]
    fn missable_modes_preserve_explicit_keep_without_changing_legacy_bytes() {
        for (base, text) in [
            (json!({"mode":"before","delimiter":"X"}), "abc"),
            (json!({"mode":"after","delimiter":"X"}), "abc"),
            (
                json!({"mode":"between","open":"(","close":")"}),
                "no parens",
            ),
            (json!({"mode":"split","delimiter":"-","index":5}), "a-b"),
            (json!({"mode":"chars","start":50}), "abc"),
        ] {
            let empty = TextSlice::from_dict(&base).unwrap();
            assert_eq!(empty.to_dict(), base);
            assert_eq!(
                empty.evaluate(text),
                SliceOutcome {
                    text: String::new(),
                    span: None,
                    missed: true
                }
            );
            let mut keep = base.as_object().unwrap().clone();
            keep.insert("on_missing".into(), json!("keep"));
            let keep = TextSlice::from_dict(&Value::Object(keep)).unwrap();
            assert_eq!(
                keep.evaluate(text),
                SliceOutcome {
                    text: text.into(),
                    span: None,
                    missed: true
                }
            );
            assert_eq!(TextSlice::from_dict(&keep.to_dict()).unwrap(), keep);
        }
        let explicit =
            TextSlice::from_dict(&json!({"mode":"before","delimiter":"X","on_missing":"empty"}))
                .unwrap();
        assert_eq!(explicit.to_dict(), json!({"mode":"before","delimiter":"X"}));
        for payload in [
            json!({"mode":"before","delimiter":"","on_missing":"keep"}),
            json!({"mode":"between","open":"(","close":""}),
            json!({"mode":"head","count":0}),
            json!({"mode":"tail","count":true}),
            json!({"mode":"replace","find":"x","replace":""}),
            json!({"mode":"split","delimiter":"-","index":0}),
            json!({"mode":"regex","pattern":".*"}),
            json!({"mode":"head","count":3,"on_missing":"keep"}),
            json!({"mode":"before","delimiter":"X","on_missing":"vanish"}),
        ] {
            assert!(TextSlice::from_dict(&payload).is_err(), "{payload}");
        }
    }

    #[test]
    fn contract_list_slices_keep_source_order_and_amount_rendering() {
        use crate::mapping::FieldMapping;
        for (column, raw, kind, spec, expected) in [
            (
                "입찰공고번호",
                "R26BK09017075-000",
                "text",
                json!({"mode":"split","delimiter":"-","index":1}),
                "R26BK09017075",
            ),
            (
                "계약번호",
                "R26TA0911050700",
                "text",
                json!({"mode":"chars","start":1,"length":3}),
                "R26",
            ),
            (
                "조달요구번호",
                "MPKPLA26910290, MPKPLA26910291",
                "text",
                json!({"mode":"split","delimiter":", ","index":-1}),
                "MPKPLA26910291",
            ),
            (
                "납품기한",
                "계약 후 90일 이내",
                "text",
                json!({"mode":"split","delimiter":" ","index":3}),
                "90일",
            ),
            (
                "계약금액",
                "170,309,180원 (VAT 포함)",
                "amount",
                json!({"mode":"split","delimiter":"원","index":1}),
                "170,309,180원",
            ),
        ] {
            let slice = TextSlice::from_dict(&spec).unwrap();
            let field = FieldMapping::new("필드", column, kind, "", "", Some(slice)).unwrap();
            let record = [(column.into(), json!(raw))].into_iter().collect();
            assert_eq!(
                field.value_for(&record, None).unwrap(),
                expected,
                "{column}"
            );
            assert_eq!(FieldMapping::from_dict(&field.to_dict()).unwrap(), field);
        }
        let chars = TextSlice::from_dict(&json!({"mode":"chars","start":1})).unwrap();
        assert!(FieldMapping::new("f", "", "const", "x", "", Some(chars.clone())).is_err());
        assert!(FieldMapping::new("f", "", "today", "", "", Some(chars)).is_err());
        assert!(
            FieldMapping::from_dict(
                &json!({"template_field":"f","source":"k","slice":{"mode":"split","index":1}})
            )
            .is_err()
        );
        assert_eq!(
            crate::mapping::apply_transform(
                "amount",
                "  170,309,180원 (VAT 포함) ",
                "",
                "",
                None,
                Some(
                    &TextSlice::from_dict(&json!({"mode":"split","delimiter":"원","index":1}))
                        .unwrap()
                )
            )
            .unwrap(),
            "170,309,180원"
        );
    }
}
