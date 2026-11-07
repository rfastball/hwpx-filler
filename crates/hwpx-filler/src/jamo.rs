//! Hangul syllable decomposition for the library's incremental IME search.

const CHO: [char; 19] = [
    'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ',
    'ㅌ', 'ㅍ', 'ㅎ',
];
const JUNG: [char; 21] = [
    'ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ',
    'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ',
];
const JONG: [&str; 28] = [
    "", "ㄱ", "ㄲ", "ㄱㅅ", "ㄴ", "ㄴㅈ", "ㄴㅎ", "ㄷ", "ㄹ", "ㄹㄱ", "ㄹㅁ", "ㄹㅂ", "ㄹㅅ",
    "ㄹㅌ", "ㄹㅍ", "ㄹㅎ", "ㅁ", "ㅂ", "ㅂㅅ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ",
    "ㅎ",
];

fn append_decomposed(ch: char, into: &mut String, positions: Option<(&mut Vec<usize>, usize)>) {
    let index = ch as u32;
    let part = if (0xAC00..=0xD7A3).contains(&index) {
        let value = (index - 0xAC00) as usize;
        into.push(CHO[value / 588]);
        into.push(JUNG[(value % 588) / 28]);
        into.push_str(JONG[value % 28]);
        2 + JONG[value % 28].chars().count()
    } else {
        into.push(ch);
        1
    };
    if let Some((positions, source_index)) = positions {
        positions.extend(std::iter::repeat_n(source_index, part));
    }
}

pub fn decompose(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
    for ch in text.chars() {
        append_decomposed(ch, &mut result, None);
    }
    result
}

/// Returns Python-codepoint positions, which must be sliced before crossing a JS boundary.
pub fn jamo_find(haystack: &str, needle: &str) -> Option<(usize, usize)> {
    if needle.is_empty() {
        return None;
    }
    let mut expanded = String::with_capacity(haystack.len());
    let mut positions = Vec::new();
    for (index, ch) in haystack.chars().enumerate() {
        append_decomposed(ch, &mut expanded, Some((&mut positions, index)));
    }
    let expanded = expanded.chars().collect::<Vec<_>>();
    let needle = decompose(needle).chars().collect::<Vec<_>>();
    let start = expanded
        .windows(needle.len())
        .position(|part| part == needle)?;
    Some((positions[start], positions[start + needle.len() - 1] + 1))
}

pub fn jamo_contains(haystack: &str, needle: &str) -> bool {
    jamo_find(haystack, needle).is_some()
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn partial_ime_and_compound_final_keep_source_character_positions() {
        let tables: serde_json::Value =
            serde_json::from_str(include_str!("../../../tests/fixtures/jamo_tables.json")).unwrap();
        assert_eq!(serde_json::to_value(CHO).unwrap(), tables["CHO"]);
        assert_eq!(serde_json::to_value(JUNG).unwrap(), tables["JUNG"]);
        assert_eq!(serde_json::to_value(JONG).unwrap(), tables["JONG"]);
        for (text, expanded) in [
            ("가", "ㄱㅏ"),
            ("행", "ㅎㅐㅇ"),
            ("힣", "ㅎㅣㅎ"),
            ("닭", "ㄷㅏㄹㄱ"),
            ("몫", "ㅁㅗㄱㅅ"),
            ("앉", "ㅇㅏㄴㅈ"),
            ("제2026-15호", "ㅈㅔ2026-15ㅎㅗ"),
            ("ㅅ", "ㅅ"),
            ("abc", "abc"),
            ("", ""),
        ] {
            assert_eq!(decompose(text), expanded, "{text}");
        }
        for (text, query, span, highlight) in [
            ("😀행복도시", "행복도ㅅ", (1, 5), "행복도시"),
            ("📋 행복도시", "복도", (3, 5), "복도"),
            ("행복도시", "행복도시", (0, 4), "행복도시"),
            ("세종특별자치시 행복도시", "행복도ㅅ", (8, 12), "행복도시"),
            ("닭고기", "달", (0, 1), "닭"),
            ("닭고기", "닭", (0, 1), "닭"),
            ("각하", "가", (0, 1), "각"),
            ("정문", "정ㅁ", (0, 2), "정문"),
            ("행복도시", "복도", (1, 3), "복도"),
            ("세종특별자치시 이전", "자치", (4, 6), "자치"),
            ("제2026-15호", "2026", (1, 5), "2026"),
            ("제2026-15호", "제2026", (0, 5), "제2026"),
            ("도시도시", "도시", (0, 2), "도시"),
            ("ABC상사", "ABC", (0, 3), "ABC"),
        ] {
            assert_eq!(jamo_find(text, query), Some(span), "{text}: {query}");
            assert!(jamo_contains(text, query));
            assert_eq!(
                text.chars()
                    .skip(span.0)
                    .take(span.1 - span.0)
                    .collect::<String>(),
                highlight
            );
        }
        assert!(jamo_contains("계약 목록", "계ㅇ"));
        for (text, query) in [
            ("ABC상사", "abc"),
            ("행복도시", "ㅎㅂㄷ"),
            ("닭고기", "담"),
            ("강남", "간"),
            ("제2026-15호", "2027"),
            ("행복도시", ""),
            ("", "가"),
            ("", ""),
        ] {
            assert_eq!(jamo_find(text, query), None, "{text}: {query}");
            assert!(!jamo_contains(text, query));
        }
    }
}
