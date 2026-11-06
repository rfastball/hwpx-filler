//! Python 3.13 Unicode casefold for product text matching.

use std::collections::HashMap;
use std::sync::LazyLock;

// Frozen from the Python 3.13 Unicode 15.1 oracle. Rust lowercase alone
// cannot preserve expansions such as ß -> ss or final sigma -> σ.
static CASEFOLD: LazyLock<HashMap<char, String>> = LazyLock::new(|| {
    include_str!("python_casefold_15_1.txt")
        .lines()
        .filter(|line| !line.starts_with('#'))
        .map(|line| {
            let (code, bytes) = line.split_once(';').expect("casefold table delimiter");
            let ch = char::from_u32(u32::from_str_radix(code, 16).expect("casefold codepoint"))
                .expect("casefold scalar");
            let octets: Vec<u8> = bytes
                .as_bytes()
                .chunks_exact(2)
                .map(|pair| {
                    u8::from_str_radix(std::str::from_utf8(pair).expect("casefold hex"), 16)
                        .expect("casefold byte")
                })
                .collect();
            (ch, String::from_utf8(octets).expect("casefold UTF-8"))
        })
        .collect()
});

pub fn python_casefold(value: &str) -> String {
    let mut out = String::new();
    for ch in value.chars() {
        if let Some(mapped) = CASEFOLD.get(&ch) {
            out.push_str(mapped);
        } else {
            out.push(ch);
        }
    }
    out
}
