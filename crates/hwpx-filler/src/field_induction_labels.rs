//! Korean document label and fixed-wording evidence.
//! The numbering, label normalization, title, and document-kind rules are ports of
//! kordoc (MIT, THIRD_PARTY_NOTICES); procurement synonyms and sentence cues are
//! this product's own rules.

use crate::fields::python_whitespace;
use regex::Regex;
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex, OnceLock};

fn regex(pattern: &'static str) -> Regex {
    static COMPILED: LazyLock<Mutex<HashMap<&'static str, Regex>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    COMPILED
        .lock()
        .expect("static label pattern cache")
        .entry(pattern)
        .or_insert_with(|| Regex::new(pattern).expect("static label pattern"))
        .clone()
}
fn legal() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        regex(
            r"^(\d{1,2}\.|[가-힣]\.|\d{1,2}\)|[가-힣]\)|\(\d{1,2}\)|\([가-힣]\)|[①-⑳]|[㉮-㉻])\s+",
        )
    })
}
fn box_marker() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| regex(r"^([□■❑❏ㅁ○ㅇ◦●❍◎\-–―—ㅡ‣▪▫ㆍ·•∙])\s+"))
}
fn ordinal(ch: char) -> bool {
    let code = ch as u32;
    if code < 0xAC00 {
        return false;
    }
    let syllable = code - 0xAC00;
    [0, 4, 8, 13, 18, 20].iter().any(|v| {
        [0, 2, 3, 5, 6, 7, 9, 11, 12, 14, 15, 16, 17, 18]
            .iter()
            .any(|i| syllable == i * 588 + v * 28)
    })
}
fn marker(line: &str) -> Option<(usize, String)> {
    let capture = legal()
        .captures(line)
        .or_else(|| box_marker().captures(line))?;
    let full = capture.get(0)?;
    let token = capture.get(1)?.as_str();
    let syllable = token.chars().find(|ch| ('가'..='힣').contains(ch));
    if syllable.is_some()
        && !syllable.is_some_and(ordinal)
        && (token.ends_with('.') || token.ends_with(')'))
    {
        return None;
    }
    Some((full.end(), token.into()))
}
fn py_ltrim(text: &str) -> &str {
    text.trim_start_matches(python_whitespace)
}
fn py_trim(text: &str) -> &str {
    text.trim_matches(python_whitespace)
}
pub fn strip_markers(line: &str) -> String {
    let mut text = py_ltrim(line);
    for _ in 0..4 {
        let Some((end, _)) = marker(text) else { break };
        text = &text[end..];
    }
    text.into()
}
pub fn leading_marker(line: &str) -> Option<(usize, String)> {
    let text = py_ltrim(line);
    let token = legal().captures(text)?.get(1)?.as_str();
    marker(text)?;
    let level = if token.starts_with('(') {
        if token.chars().nth(1)?.is_numeric() {
            4
        } else {
            5
        }
    } else if ('①'..='⑳').contains(&token.chars().next()?) {
        6
    } else if ('㉮'..='㉻').contains(&token.chars().next()?) {
        7
    } else if token.ends_with('.') {
        if token.chars().next()?.is_numeric() {
            0
        } else {
            1
        }
    } else if token.chars().next()?.is_numeric() {
        2
    } else {
        3
    };
    Some((level, token.into()))
}
pub fn normalize_label(text: &str) -> String {
    py_trim(text)
        .chars()
        .filter(|ch| {
            !matches!(ch, ':' | '：' | '(' | ')' | '（' | '）' | '·' | '　')
                && !python_whitespace(*ch)
        })
        .collect()
}
pub fn label_before(left: &str) -> String {
    let line = left.rsplit('\n').next().unwrap_or("");
    let found = regex(r"([\w가-힣 ]{1,20})[:：]?\s*$")
        .captures(line)
        .and_then(|capture| capture.get(1))
        .map(|item| item.as_str())
        .unwrap_or(line);
    py_trim(found).into()
}
pub fn raw_label(left: &str, how: &str) -> String {
    let line = left.rsplit('\n').next().unwrap_or("");
    match how {
        "colon" => {
            let at = line
                .rfind(':')
                .into_iter()
                .chain(line.rfind('：'))
                .max()
                .unwrap_or(line.len());
            format!(
                "{}{}",
                strip_markers(&line[..at])
                    .split_whitespace()
                    .collect::<Vec<_>>()
                    .join(" "),
                line[at..].chars().next().unwrap_or_default()
            )
        }
        "cell" => left
            .rsplit('\n')
            .nth(1)
            .map(strip_markers)
            .unwrap_or_default()
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" "),
        _ => label_before(&strip_markers(line)),
    }
}
pub fn word_windows(line: &str) -> Vec<String> {
    let words: Vec<_> = line.split_whitespace().collect();
    (1..=3)
        .filter(|count| words.len() >= *count)
        .map(|count| words[words.len() - count..].join(" "))
        .collect()
}
fn numeric_value(text: &str) -> bool {
    regex(r"^제?\d+(?:[.,]\d+)*[십백천만억조]*(?:원|명|건|개|회|부|매|장|점|호|번|년|월|일|시|분|초|개월|주년|차례|퍼센트)?$").is_match(text)
}
pub fn is_label_cell(text: &str) -> bool {
    let stripped = regex(r"[¹²³⁴⁵⁶⁷⁸⁹⁰*※]+$").replace(py_trim(text), "");
    if stripped.is_empty() || stripped.chars().count() > 30 {
        return false;
    }
    let compact: String = stripped
        .chars()
        .filter(|ch| !python_whitespace(*ch))
        .collect();
    let length = compact.chars().count();
    regex(r"^[가-힣0-9()（）·:：\-]+$").is_match(&compact)
        && (2..=12).contains(&length)
        && compact.chars().filter(|ch|('가'..='힣').contains(ch)).count()>=2
        && (length<=8 || stripped.split_whitespace().count()<=2)
        && !numeric_value(&compact)
        && !regex(r"(?:입니다|합니다|습니다|하세요|십시오|시오|바랍니다|바람|할 것|할것|하며|하고|한다|된다|됨|음|임)$").is_match(&compact)
        && !regex(r"^[(（]주[)）]|^주식회사").is_match(&compact)
}

const SYNONYM_GROUPS: &[&[&str]] = &[
    &[
        "공고명",
        "사업명",
        "건명",
        "입찰건명",
        "요청건명",
        "계약건명",
        "구매건명",
        "용역명",
    ],
    &["계약방법", "입찰방법", "입찰방식", "계약방식"],
    &[
        "계약상대자",
        "업체명",
        "상호",
        "계약업체",
        "대표계약업체",
        "계약자",
        "낙찰자",
    ],
    &["수요기관", "발주기관", "요청기관", "수요처"],
    &["추정가격", "추정금액"],
    &["사업예산", "예산액", "배정예산", "사업비", "예산"],
    &["계약금액", "계약액", "계약금"],
    &["납품기한", "납기", "납품일자", "납품기일", "납품기간"],
    &["담당자", "담당", "담당공무원", "계약담당자", "담당자명"],
    &["담당자전화번호", "전화번호", "연락처", "전화", "문의처"],
    &["입찰공고번호", "공고번호"],
    &["개찰일시", "개찰일", "개찰시각"],
    &["입찰마감일시", "입찰서마감", "접수마감일시", "마감일시"],
    &["세부품명", "품명", "물품명"],
    &["수량", "구매수량"],
    &["시행일", "시행일자"],
    &["수신자", "수신"],
];
fn synonyms(part: &str, column: &str) -> bool {
    SYNONYM_GROUPS.iter().any(|group| {
        group.contains(&part)
            && group
                .iter()
                .filter(|word| **word != part)
                .any(|word| *word == column || word.chars().count() >= 2 && column.ends_with(word))
    })
}
fn label_parts(label: &str) -> Vec<&str> {
    let parts: Vec<_> = regex(r"및|/|,|、|ㆍ")
        .split(label)
        .filter(|part| part.chars().count() >= 2)
        .collect();
    if parts.is_empty() { vec![label] } else { parts }
}
pub fn names_literally(label: &str, column: &str) -> bool {
    !label.is_empty()
        && !column.is_empty()
        && label_parts(label)
            .iter()
            .any(|part| part.contains(column) || column.contains(part))
}
fn bigrams(text: &str) -> Vec<String> {
    let text: String = text
        .to_lowercase()
        .chars()
        .filter(|ch| !python_whitespace(*ch) && !"_-.".contains(*ch))
        .collect();
    let chars: Vec<_> = text.chars().collect();
    if chars.len() < 2 {
        return if text.is_empty() {
            Vec::new()
        } else {
            vec![text]
        };
    }
    (0..chars.len() - 1)
        .map(|at| chars[at..at + 2].iter().collect())
        .collect()
}
pub fn name_overlap(label: &str, column: &str) -> f64 {
    let a = bigrams(label);
    let b = bigrams(column.rsplit('.').next().unwrap_or(""));
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let a: std::collections::HashSet<_> = a.into_iter().collect();
    let b: std::collections::HashSet<_> = b.into_iter().collect();
    a.intersection(&b).count() as f64 / b.len() as f64
}
pub fn label_matches(label: &str, column: &str, fuzzy: bool) -> bool {
    if label.is_empty() || column.is_empty() {
        return false;
    }
    for part in label_parts(label) {
        if part == column
            || part.starts_with(column)
                && column.chars().count() as f64 >= part.chars().count() as f64 * 0.6
            || column.starts_with(part)
                && part.chars().count() as f64 >= column.chars().count() as f64 * 0.75
            || part.chars().count() >= 2 && column.ends_with(part)
            || column.chars().count() >= 2 && part.ends_with(column)
            || synonyms(part, column)
        {
            return true;
        }
    }
    fuzzy && name_overlap(label, column) >= 0.5
}
fn colon_label(line: &str) -> Option<(String, &'static str)> {
    let at = line.rfind(':').into_iter().chain(line.rfind('：')).max()?;
    let gap = &line[at + line[at..].chars().next()?.len_utf8()..];
    if py_trim(gap).chars().count() > 25 {
        return None;
    }
    let mut head = strip_markers(&line[..at]);
    if normalize_label(&head).chars().count() > 16 {
        let boundary = regex(r"[,;]|\s{2,}")
            .find_iter(&head)
            .filter(|item| {
                ",;".contains(item.as_str())
                    || head[item.end()..].chars().take(3).count() == 3
                        && head[item.end()..]
                            .chars()
                            .take(3)
                            .all(|ch| !python_whitespace(ch))
            })
            .last()
            .map(|item| item.end());
        if let Some(boundary) = boundary {
            head = head[boundary..].into();
        }
    }
    let label: String = normalize_label(&head)
        .chars()
        .rev()
        .take(16)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    if label.is_empty() {
        return None;
    }
    if py_trim(gap).is_empty()
        || label.contains("및")
        || label.chars().any(|ch| "/ㆍ,".contains(ch))
    {
        Some((label, "colon"))
    } else {
        Some((String::new(), "colon-but-value-between"))
    }
}
pub fn extract_label(left: &str) -> (String, &'static str) {
    let line = left.rsplit('\n').next().unwrap_or("");
    if let Some(label) = colon_label(line) {
        return label;
    }
    let stripped = strip_markers(line);
    let stripped = if stripped
        .chars()
        .all(|ch| python_whitespace(ch) || "□■❑❏ㅁ○ㅇ◦●❍◎-–―—ㅡ‣▪▫ㆍ·•∙".contains(ch))
    {
        String::new()
    } else {
        stripped
    };
    if !py_trim(&stripped).is_empty() {
        return (normalize_label(&label_before(&stripped)), "before");
    }
    let previous = left
        .rsplit('\n')
        .nth(1)
        .map(strip_markers)
        .unwrap_or_default();
    if is_label_cell(&previous) && !regex(r"[:：]\s*\S").is_match(&previous) {
        return (normalize_label(&previous), "cell");
    }
    (String::new(), "none")
}

pub const CUE_FIXED: &str = "fixed";
pub const CUE_GENERIC: &str = "generic";
pub const CUE_REPEAT: &str = "repeat";
const INSTRUMENTS: &[&str] = &[
    "고시",
    "훈령",
    "예규",
    "지침",
    "규정",
    "세부기준",
    "계약예규",
    "규칙",
    "조례",
    "시행령",
    "시행규칙",
    "법률",
];
const TITLES: &[&str] = &[
    "회장",
    "사장",
    "이사장",
    "위원장",
    "대표",
    "대표이사",
    "장관",
    "차관",
    "청장",
    "처장",
    "실장",
    "국장",
    "과장",
    "팀장",
    "계장",
    "부장",
    "차장",
    "대리",
    "주임",
    "주무관",
    "사무관",
    "서기관",
    "연구관",
    "연구사",
    "연구원",
    "담당",
    "담당자",
    "교수",
    "원장",
    "소장",
    "센터장",
    "관장",
    "본부장",
    "지점장",
    "담당관",
    "상사",
    "중사",
    "하사",
    "원사",
    "준위",
    "소위",
    "중위",
    "대위",
    "소령",
    "중령",
    "대령",
    "군무원",
];
fn is_slot(prefix: &str) -> bool {
    regex(r"[가-힣A-Za-z)]\s*[:：]\s*$").is_match(prefix)
}
pub fn number_frame(left: &str, right: &str) -> bool {
    left.ends_with('제')
        && right
            .chars()
            .next()
            .is_some_and(|ch| "호차회번".contains(ch))
}
pub fn glued_left(left: &str, span: &str) -> bool {
    left.chars().last().is_some_and(char::is_alphanumeric)
        && span.chars().next().is_some_and(char::is_alphanumeric)
}
pub fn data_cue(left: &str, span: &str, right: &str) -> bool {
    if number_frame(left, right) {
        return true;
    }
    let text = py_trim(span);
    if regex(r"^0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}$").is_match(text) {
        return true;
    }
    let title = TITLES.iter().any(|word| {
        right.trim_start().starts_with(word)
            && !right.trim_start()[word.len()..]
                .chars()
                .next()
                .is_some_and(|ch| ('가'..='힣').contains(&ch))
    });
    if regex(r"^[가-힣]{2,4}$").is_match(text) && title {
        return true;
    }
    TITLES
        .iter()
        .any(|word| regex(r"^[가-힣]{2,4}\s$").is_match(text.strip_suffix(word).unwrap_or("")))
}
fn quoted(left: &str, right: &str) -> bool {
    for (open, close) in [
        ('「', '」'),
        ('『', '』'),
        ('“', '”'),
        ('‘', '’'),
        ('《', '》'),
        ('〈', '〉'),
    ] {
        if left.matches(open).count() > left.matches(close).count()
            && let Some(end) = right.find(close)
        {
            let inside_left = left.rsplit(open).next().unwrap_or("");
            let inside_right = &right[..end];
            if !py_trim(inside_left).is_empty() || !py_trim(inside_right).is_empty() {
                return true;
            }
        }
    }
    false
}
pub fn static_cue(
    left: &str,
    span: &str,
    right: &str,
    repeats: usize,
    prefixes: &[String],
) -> Option<&'static str> {
    let line_left = left.rsplit('\n').next().unwrap_or("");
    let line_right = right.split('\n').next().unwrap_or("");
    if quoted(line_left, line_right)
        || regex(r"^\s?[가-힣]{1,6}\s*[:：]").is_match(line_right)
        || INSTRUMENTS.iter().any(|word| {
            let suffix = line_right.trim_start().strip_prefix(word);
            suffix.is_some_and(|suffix| {
                suffix.is_empty()
                    || suffix
                        .chars()
                        .next()
                        .is_some_and(|ch| ") ,.」』".contains(ch))
            })
        })
        || regex(r"^\s*(?:\.\s+\.\s+\.|년\s+월\s+일)").is_match(line_right)
    {
        return Some(CUE_FIXED);
    }
    let before = regex(r"[.。]\s|\n").split(left).last().unwrap_or("");
    let after = regex(r"[.。](?:\s|$)|\n").split(right).next().unwrap_or("");
    let sentence = format!("{before}{span}{after}");
    if !is_slot(line_left) && regex(r"(?:하여야|해야|되어야)\s?(?:한다|합니다|하며|하고|함)|(?:할|될|볼)\s?수\s?(?:있다|있습니다|있으며|있고|없다|없습니다|없으며)|아니한다|아니합니다|아니하는|않는다|않습니다|(?:으로|로)\s?한다|에\s?따른다|에\s?따릅니다|준용한다|한한다|해당한다|경우에는|경우에|때에는|바랍니다|하여서는").is_match(&sentence){return Some(CUE_GENERIC)}
    let here: String = line_left
        .chars()
        .rev()
        .take(32)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    if repeats >= 5
        && prefixes.len() >= 2
        && !is_slot(&here)
        && prefixes
            .iter()
            .any(|prefix| prefix != &here && is_slot(prefix))
    {
        return Some(CUE_REPEAT);
    }
    None
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn markers_cells_and_synonyms_keep_document_label_boundaries() {
        assert_eq!(normalize_label(" 품          명: "), "품명");
        assert_eq!(
            strip_markers("  ① 입찰방식: 전자입찰"),
            "입찰방식: 전자입찰"
        );
        assert_eq!(strip_markers("가. 개찰일시"), "개찰일시");
        assert_eq!(strip_markers("는. 이하"), "는. 이하");
        assert_eq!(strip_markers("1. 가. 1) (1) 깊은 항목"), "깊은 항목");
        assert_eq!(strip_markers("1. 가. 1) (1) ① 다섯째"), "① 다섯째");
        assert!(is_label_cell("업 체 명"));
        for value in [
            "6개월",
            "(주)원트리즈뮤직",
            "",
            "가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가가",
        ] {
            assert!(!is_label_cell(value), "{value}");
        }
        assert_eq!(
            extract_label(" 사  업  예  산:  "),
            ("사업예산".into(), "colon")
        );
        assert_eq!(
            extract_label(" 수 량 및 단 위:  6 "),
            ("수량및단위".into(), "colon")
        );
        assert_eq!(
            extract_label("1) 품명 및 수량\n -"),
            ("품명및수량".into(), "cell")
        );
        assert_eq!(
            extract_label("다음과 같이 공고합니다.\n"),
            ("".into(), "none")
        );
        assert_eq!(extract_label("단위: 대\n"), ("".into(), "none"));
        assert_eq!(
            extract_label("비고: ".to_owned().as_str()),
            ("비고".into(), "colon")
        );
        assert_eq!(
            extract_label(&format!("비고: {} ", "가".repeat(26))).1,
            "before"
        );
        assert_ne!(extract_label("(): ").1, "colon");
        assert_eq!(raw_label(" 다. 수 량: ", "colon"), "수 량:");
        assert_eq!(raw_label("계약방법\n", "cell"), "계약방법");
        assert_eq!(raw_label("가. 이 입찰은 ", "before"), "이 입찰은");
        assert_eq!(
            leading_marker("1. 입찰에 부치는 사항"),
            Some((0, "1.".into()))
        );
        assert_eq!(leading_marker(" 나. 추정가격: 1"), Some((1, "나.".into())));
        assert_eq!(leading_marker("(1) 세부"), Some((4, "(1)".into())));
        assert_eq!(leading_marker("는. 이하"), None);
        assert_eq!(
            word_windows("시스템에 세부품명번호 10자리"),
            vec![
                "10자리",
                "세부품명번호 10자리",
                "시스템에 세부품명번호 10자리"
            ]
        );
        assert!(word_windows("").is_empty());
        assert!(names_literally("품명및수량", "세부품명"));
        assert!(!names_literally("입찰방식", "입찰방법"));
        for (label, column) in [
            ("품명", "세부품명"),
            ("수량및단위", "단위"),
            ("요청건명", "공고명"),
            ("입찰방식", "계약방법"),
            ("공고명칭", "공고명"),
            ("담당자전화번호", "전화번호"),
        ] {
            assert!(label_matches(label, column, false), "{label}/{column}");
        }
        assert!(!label_matches("공고", "공고명", false));
        assert!(label_matches("낙찰자결정방식", "낙찰자결정방법", true));
        assert!(!label_matches("낙찰자결정을위한", "낙찰자결정방법", false));
        assert_eq!(label_before("\n납부기한: "), "납부기한");
        assert_eq!(name_overlap("납부기한", "납부기한"), 1.0);
        assert_eq!(name_overlap("", "납부기한"), 0.0);
    }

    #[test]
    fn static_wording_and_data_cues_do_not_turn_prose_into_slots() {
        assert_eq!(
            static_cue(
                "근거: “조달청 군수품 구매 ",
                "적격심사",
                " 세부기준” 제4조",
                1,
                &[]
            ),
            Some(CUE_FIXED)
        );
        assert_eq!(
            static_cue("전자입찰특별유의서 (", "조달청", " 고시)", 1, &[]),
            Some(CUE_FIXED)
        );
        assert_eq!(
            static_cue("제목  「", "선박 개선", "」 낙찰자 선정", 1, &[]),
            None
        );
        assert_eq!(
            static_cue(
                "계약상대자는 ",
                "조달청",
                "의 승인을 받아야 하며 이를 위반한 경우에는 해지할 수 있다",
                1,
                &[]
            ),
            Some(CUE_GENERIC)
        );
        assert_eq!(
            static_cue(
                "수요기관 ",
                "조달청",
                "에서 요청한 물품을 다음과 같이 공고합니다",
                1,
                &[]
            ),
            None
        );
        assert_eq!(static_cue("", "20", "  .   .   .", 1, &[]), Some(CUE_FIXED));
        assert_eq!(
            static_cue("", "20", "  년   월   일", 1, &[]),
            Some(CUE_FIXED)
        );
        let prefixes = vec!["수요기관: ".into(), "관련 문의는 ".into(), "근거: ".into()];
        assert_eq!(
            static_cue("관련 문의는 ", "조달청", " 콜센터로", 6, &prefixes),
            Some(CUE_REPEAT)
        );
        assert_eq!(
            static_cue("관련 문의는 ", "조달청", " 콜센터로", 3, &prefixes),
            None
        );
        assert!(data_cue("", "042-481-1234", ""));
        assert!(data_cue("", "김다온", " 주무관 (042)"));
        assert!(!data_cue("", "김다온", "에게"));
        assert!(!data_cue("", "화생방과", ""));
        assert!(!data_cue("주무관 ", "홍길동", " (☎ 042)"));
        assert!(data_cue("조달청 물품공고 제", "R26BK99000001-000", "호"));
        assert!(!data_cue("제", "12", "조"));
        assert!(glued_left("제", "R26"));
        assert!(!glued_left("번호 ", "R26"));
    }
}
