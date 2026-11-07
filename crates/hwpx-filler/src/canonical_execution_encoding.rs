//! Versioned execution identity shared with the existing Python and TypeScript implementations.

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fmt;

pub const CANONICAL_ENCODING_VERSION: &str = "execution-canonical/v1";
const MAGIC: &[u8; 8] = b"HFPXEC1\0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanonicalEncodingError {
    Float,
    IntegerRange,
    LengthRange,
    UnsupportedVersion,
}

impl fmt::Display for CanonicalEncodingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::Float => "float has no canonical execution identity",
            Self::IntegerRange => "integer magnitude exceeds u64",
            Self::LengthRange => "count or UTF-8 byte length exceeds u32",
            Self::UnsupportedVersion => "unsupported canonical execution encoding version",
        };
        f.write_str(message)
    }
}

impl std::error::Error for CanonicalEncodingError {}

pub fn require_supported_encoding(version: &str) -> Result<(), CanonicalEncodingError> {
    if version == CANONICAL_ENCODING_VERSION {
        Ok(())
    } else {
        Err(CanonicalEncodingError::UnsupportedVersion)
    }
}

fn write_len(out: &mut Vec<u8>, len: usize) -> Result<(), CanonicalEncodingError> {
    let len = u32::try_from(len).map_err(|_| CanonicalEncodingError::LengthRange)?;
    out.extend_from_slice(&len.to_be_bytes());
    Ok(())
}

fn write_text(out: &mut Vec<u8>, value: &str) -> Result<(), CanonicalEncodingError> {
    write_len(out, value.len())?;
    out.extend_from_slice(value.as_bytes());
    Ok(())
}

fn write_number(
    out: &mut Vec<u8>,
    value: &serde_json::Number,
) -> Result<(), CanonicalEncodingError> {
    let decimal = value.to_string();
    if decimal
        .bytes()
        .any(|byte| matches!(byte, b'.' | b'e' | b'E'))
    {
        return Err(CanonicalEncodingError::Float);
    }
    let (negative, magnitude) = match decimal.strip_prefix('-') {
        Some(magnitude) => (true, magnitude),
        None => (false, decimal.as_str()),
    };
    let magnitude = magnitude
        .parse::<u64>()
        .map_err(|_| CanonicalEncodingError::IntegerRange)?;
    out.push(0x03);
    out.push(u8::from(negative && magnitude != 0));
    out.extend_from_slice(&magnitude.to_be_bytes());
    Ok(())
}

fn write_value(out: &mut Vec<u8>, value: &Value) -> Result<(), CanonicalEncodingError> {
    match value {
        Value::Null => out.push(0x00),
        Value::Bool(false) => out.push(0x01),
        Value::Bool(true) => out.push(0x02),
        Value::Number(number) => write_number(out, number)?,
        Value::String(text) => {
            out.push(0x04);
            write_text(out, text)?;
        }
        Value::Array(items) => {
            out.push(0x05);
            write_len(out, items.len())?;
            for item in items {
                write_value(out, item)?;
            }
        }
        Value::Object(items) => {
            out.push(0x06);
            write_len(out, items.len())?;
            let mut entries: Vec<_> = items.iter().collect();
            entries.sort_unstable_by(|(left, _), (right, _)| left.as_bytes().cmp(right.as_bytes()));
            for (key, item) in entries {
                write_text(out, key)?;
                write_value(out, item)?;
            }
        }
    }
    Ok(())
}

pub fn canonical_execution_bytes(value: &Value) -> Result<Vec<u8>, CanonicalEncodingError> {
    let mut out = Vec::new();
    out.extend_from_slice(MAGIC);
    write_text(&mut out, CANONICAL_ENCODING_VERSION)?;
    write_value(&mut out, value)?;
    Ok(out)
}

pub fn canonical_execution_digest(value: &Value) -> Result<String, CanonicalEncodingError> {
    let bytes = canonical_execution_bytes(value)?;
    let hash = Sha256::digest(&bytes);
    let mut digest = String::from("sha256:");
    for byte in hash {
        fmt::Write::write_fmt(&mut digest, format_args!("{byte:02x}"))
            .expect("writing into String cannot fail");
    }
    Ok(digest)
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn existing_cross_language_golden_vectors() {
        let source = include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tests/fixtures/execution_canonical_v1_golden.json"
        ));
        assert_eq!(
            Sha256::digest(source)
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>(),
            "253849a93d8c03f7f275ca82a67196ecaa199cf63384f7a86754e029133f0615"
        );
        let fixture: Value = serde_json::from_slice(source).unwrap();
        assert_eq!(fixture["encoding_version"], CANONICAL_ENCODING_VERSION);
        for vector in fixture["vectors"].as_array().unwrap() {
            let value = &vector["value"];
            let actual_hex: String = canonical_execution_bytes(value)
                .unwrap()
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect();
            assert_eq!(actual_hex, vector["canonical_hex"], "{}", vector["name"]);
            assert_eq!(
                canonical_execution_digest(value).unwrap(),
                vector["digest"],
                "{}",
                vector["name"]
            );
        }
    }

    #[test]
    fn integer_magnitude_and_float_boundaries() {
        for source in ["18446744073709551615", "-18446744073709551615"] {
            let value: Value = serde_json::from_str(source).unwrap();
            let bytes = canonical_execution_bytes(&value).unwrap();
            assert_eq!(&bytes[bytes.len() - 8..], &u64::MAX.to_be_bytes());
        }
        for source in ["18446744073709551616", "-18446744073709551616"] {
            let value: Value = serde_json::from_str(source).unwrap();
            assert_eq!(
                canonical_execution_bytes(&value),
                Err(CanonicalEncodingError::IntegerRange)
            );
        }
        for source in ["1.0", "1e0", "-0.0"] {
            let value: Value = serde_json::from_str(source).unwrap();
            assert_eq!(
                canonical_execution_bytes(&value),
                Err(CanonicalEncodingError::Float)
            );
        }
        let negative_zero: Value = serde_json::from_str("-0").unwrap();
        let zero: Value = serde_json::from_str("0").unwrap();
        assert_eq!(
            canonical_execution_bytes(&negative_zero),
            canonical_execution_bytes(&zero)
        );
        assert_eq!(
            require_supported_encoding("execution-canonical/v2"),
            Err(CanonicalEncodingError::UnsupportedVersion)
        );
    }
}
