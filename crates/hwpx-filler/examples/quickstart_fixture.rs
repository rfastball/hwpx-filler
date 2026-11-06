//! Regenerate the tracked Quickstart 101 HWPX templates and CSV data.
//! Run with `cargo run -p hwpx-filler --example quickstart_fixture -- --out examples/quickstart-101`.
#![cfg_attr(coverage_nightly, feature(coverage_attribute))]

mod fixture_common;

use fixture_common::template;
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

const FIELDS: [&str; 6] = [
    "공고번호",
    "수요기관",
    "공고명",
    "추정가격",
    "납품기한",
    "담당자",
];
const RECORDS: [[&str; 6]; 3] = [
    [
        "2026-001",
        "해양수산부",
        "사무용 복합기 구매",
        "12000000",
        "2026-08-31",
        "김담당",
    ],
    [
        "2026-002",
        "국립수산과학원",
        "회의실 빔프로젝터 구매",
        "8500000",
        "2026-09-15",
        "박담당",
    ],
    [
        "2026-003",
        "부산지방해양수산청",
        "현장 안전화 구매",
        "3200000",
        "2026-08-20",
        "이담당",
    ],
];
const RECORDS_2: [[&str; 6]; 2] = [
    [
        "2026-101",
        "동해어업관리단",
        "순찰정 통신장비 구매",
        "27000000",
        "2026-10-10",
        "최담당",
    ],
    [
        "2026-102",
        "동해어업관리단",
        "구명조끼 일괄 구매",
        "4600000",
        "2026-09-05",
        "최담당",
    ],
];
const BID_LINES: [&str; 6] = [
    "공고번호: {{공고번호}}",
    "수요기관: {{수요기관}}",
    "공고명: {{공고명}}",
    "추정가격: {{추정가격}}",
    "납품기한: {{납품기한}}",
    "담당자: {{담당자}}",
];
const PURCHASE_LINES: [&str; 4] = [
    "수요기관: {{수요기관}}",
    "품명: {{공고명}}",
    "추정가격: {{추정가격}}",
    "담당자: {{담당자}}",
];

fn csv(records: &[[&str; 6]]) -> Vec<u8> {
    let mut bytes = vec![0xef, 0xbb, 0xbf];
    bytes.extend_from_slice(FIELDS.join(",").as_bytes());
    bytes.extend_from_slice(b"\r\n");
    for record in records {
        bytes.extend_from_slice(record.join(",").as_bytes());
        bytes.extend_from_slice(b"\r\n");
    }
    bytes
}

fn write(out: &Path, kind: &str, name: &str, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    let dir = out.join(kind);
    fs::create_dir_all(&dir)?;
    fs::write(dir.join(name), bytes)?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let out = match args.as_slice() {
        [] => PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../examples/quickstart-101"),
        [flag, path] if flag == "--out" => PathBuf::from(path),
        _ => return Err("usage: quickstart_fixture [--out DIR]".into()),
    };
    let skeleton = fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/corpus/real/form_purchase_v1.hwpx"),
    )?;
    let files = [
        ("발주요청서.hwpx", "■ 발 주 요 청 서", BID_LINES.as_slice()),
        (
            "구매요청서.hwpx",
            "■ 구 매 요 청 서",
            PURCHASE_LINES.as_slice(),
        ),
    ];
    for (name, title, lines) in files {
        write(
            &out,
            "templates",
            name,
            &template(&skeleton, title, lines, true)?,
        )?;
    }
    write(&out, "data", "발주목록.csv", &csv(&RECORDS))?;
    write(&out, "data", "발주목록_2.csv", &csv(&RECORDS_2))?;
    Ok(())
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn generated_quickstart_matches_committed_assets() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../");
        let base = root.join("examples/quickstart-101");
        let skeleton = fs::read(root.join("tests/corpus/real/form_purchase_v1.hwpx")).unwrap();
        for (name, title, lines) in [
            ("발주요청서.hwpx", "■ 발 주 요 청 서", BID_LINES.as_slice()),
            (
                "구매요청서.hwpx",
                "■ 구 매 요 청 서",
                PURCHASE_LINES.as_slice(),
            ),
        ] {
            assert_eq!(
                fs::read(base.join("templates").join(name)).unwrap(),
                template(&skeleton, title, lines, true).unwrap(),
                "{name}"
            );
        }
        assert_eq!(
            csv(&RECORDS),
            fs::read(base.join("data/발주목록.csv")).unwrap()
        );
        assert_eq!(
            csv(&RECORDS_2),
            fs::read(base.join("data/발주목록_2.csv")).unwrap()
        );
    }
}
