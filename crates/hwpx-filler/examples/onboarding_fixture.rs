//! Regenerate the seven frozen onboarding assets from fixture_source.json.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

#[path = "fixture_common/mod.rs"]
mod fixture_common;

use serde::Deserialize;
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Deserialize)]
struct Template {
    file: String,
    title: String,
    lines: Vec<String>,
    compile_fields: bool,
}

#[derive(Deserialize)]
struct TextTemplate {
    file: String,
    body: String,
}

#[derive(Deserialize)]
struct Source {
    fields: Vec<String>,
    records: Vec<serde_json::Map<String, serde_json::Value>>,
    records_2: Vec<serde_json::Map<String, serde_json::Value>>,
    templates: Vec<Template>,
    text_templates: Vec<TextTemplate>,
}

type Generated = Vec<(PathBuf, Vec<u8>)>;

fn source() -> Result<Source, Box<dyn Error>> {
    Ok(serde_json::from_str(include_str!(
        "../../../examples/onboarding/fixture_source.json"
    ))?)
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn csv_value(value: &str) -> String {
    if value.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", value.replace('"', "\"\""))
    } else {
        value.to_owned()
    }
}

fn csv(
    fields: &[String],
    records: &[serde_json::Map<String, serde_json::Value>],
) -> Result<Vec<u8>, Box<dyn Error>> {
    let mut text = String::from("\u{feff}");
    text.push_str(
        &fields
            .iter()
            .map(|field| csv_value(field))
            .collect::<Vec<_>>()
            .join(","),
    );
    text.push('\n');
    for record in records {
        let mut values = Vec::with_capacity(fields.len());
        for field in fields {
            let value = record
                .get(field)
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| format!("missing text field {field}"))?;
            values.push(csv_value(value));
        }
        text.push_str(&values.join(","));
        text.push('\n');
    }
    Ok(text.into_bytes())
}

fn generated() -> Result<Generated, Box<dyn Error>> {
    let source = source()?;
    let skeleton = fs::read(repo_root().join("tests/corpus/real/form_purchase_v1.hwpx"))?;
    let mut output = Vec::new();
    for template in source.templates {
        let lines = template
            .lines
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>();
        let bytes = if template.compile_fields {
            fixture_common::template(&skeleton, &template.title, &lines, false)?
        } else {
            fixture_common::uncompiled_template(&skeleton, &template.title, &lines)?
        };
        output.push((PathBuf::from("templates").join(template.file), bytes));
    }
    for template in source.text_templates {
        output.push((
            PathBuf::from("text_templates").join(template.file),
            template.body.into_bytes(),
        ));
    }
    output.push((
        PathBuf::from("data/계약목록.csv"),
        csv(&source.fields, &source.records)?,
    ));
    output.push((
        PathBuf::from("data/계약목록_2.csv"),
        csv(&source.fields, &source.records_2)?,
    ));
    Ok(output)
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = std::env::args_os().skip(1).collect::<Vec<_>>();
    let out = match args.as_slice() {
        [] => repo_root().join("examples/onboarding"),
        [flag, dir] if flag == "--out" => PathBuf::from(dir),
        _ => {
            return Err(
                "usage: cargo run -p hwpx-filler --example onboarding_fixture -- [--out DIR]"
                    .into(),
            );
        }
    };
    for (relative, bytes) in generated()? {
        let target = out.join(relative);
        fs::create_dir_all(target.parent().ok_or("missing output parent")?)?;
        fs::write(target, bytes)?;
    }
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::io::Read;

    #[test]
    fn frozen_assets_are_byte_identical() {
        let source = source().unwrap();
        assert_eq!(
            source.fields.iter().map(String::as_str).collect::<Vec<_>>(),
            [
                "공고번호",
                "수요기관",
                "품명",
                "사업명",
                "계약방법",
                "계약상대자",
                "계약금액",
                "납품조건"
            ]
        );
        assert_eq!((source.records.len(), source.records_2.len()), (3, 2));
        for record in &source.records {
            assert!(source.fields.iter().all(|field| {
                record
                    .get(field.as_str())
                    .and_then(serde_json::Value::as_str)
                    .is_some_and(|value| !value.trim().is_empty())
            }));
        }
        for (index, record) in source.records_2.iter().enumerate() {
            for field in &source.fields {
                let value = record
                    .get(field.as_str())
                    .and_then(serde_json::Value::as_str)
                    .unwrap();
                assert_eq!(value.trim().is_empty(), index == 1 && field == "납품조건");
            }
        }
        let generated = generated().unwrap();
        assert_eq!(generated.len(), 7);
        let mut visible =
            include_str!("../../../examples/onboarding/fixture_source.json").to_owned();
        for (name, bytes) in generated {
            let expected = fs::read(repo_root().join("examples/onboarding").join(&name)).unwrap();
            let first = bytes.iter().zip(&expected).position(|(a, b)| a != b);
            assert!(
                bytes == expected,
                "{}: generated {} expected {}, first differing byte {:?}",
                name.display(),
                bytes.len(),
                expected.len(),
                first
            );
            if name
                .extension()
                .is_some_and(|extension| extension == std::ffi::OsStr::new("hwpx"))
            {
                let mut archive =
                    zip::ZipArchive::new(std::io::Cursor::new(bytes.as_slice())).unwrap();
                for index in 0..archive.len() {
                    let mut entry = archive.by_index(index).unwrap();
                    let mut content = Vec::new();
                    entry.read_to_end(&mut content).unwrap();
                    visible.push_str(&String::from_utf8_lossy(&content));
                }
            } else {
                visible.push_str(&String::from_utf8_lossy(&bytes));
            }
        }
        for forbidden in [
            "조달청",
            "대전지방조달청",
            "나라장터",
            "루나이엔씨",
            "루나이앤씨",
            "육군군수사령부",
            "경제인문사회연구회",
            "방위사업청",
            "안준명",
            "황민오",
            "이순주",
            "조다래",
            "김성우",
            "korea.kr",
            "R26BK01666828",
            "25224100200",
        ] {
            assert!(
                !visible.contains(forbidden),
                "frozen onboarding asset contains {forbidden}"
            );
        }
    }
}
