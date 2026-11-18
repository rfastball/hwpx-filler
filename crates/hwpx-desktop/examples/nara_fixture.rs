#![cfg_attr(coverage_nightly, feature(coverage_attribute))]
//! Reharvest the deliberately non-deterministic Nara corpus with the native parser.
//! The committed corpus stays frozen until a reviewer updates its purpose manifest.
use chrono::{Duration, Local};
use hwpx_desktop::nara_transport::nara_fetcher;
use hwpx_filler::data_source::Record;
use hwpx_filler::nara::{self, NaraStdDataSource};
use hwpx_filler::structure_scan::python_trim;
use serde_json::{Value, json};
use std::cmp::Reverse;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

type Picked = Vec<(String, Vec<&'static str>)>;

fn value<'a>(record: &'a Record, key: &str) -> &'a str {
    record.get(key).map(String::as_str).unwrap_or("")
}

fn redact(record: Record) -> Record {
    record
        .into_iter()
        .map(|(key, value)| {
            let masked = if key.ends_with("OfclNm") && !value.is_empty() {
                "담당자".to_string()
            } else if key.ends_with("Tel") {
                value
                    .chars()
                    .map(|ch| if ch.is_ascii_digit() { '0' } else { ch })
                    .collect()
            } else if key.ends_with("EmailAdrs") && !value.is_empty() {
                "official@example.go.kr".to_string()
            } else {
                value
            };
            (key, masked)
        })
        .collect()
}

fn take(picked: &mut Picked, record: &Record, why: &'static str) {
    let number = value(record, "bidNtceNo");
    if let Some((_, reasons)) = picked.iter_mut().find(|(key, _)| key == number) {
        if !reasons.contains(&why) {
            reasons.push(why);
        }
    } else {
        picked.push((number.to_string(), vec![why]));
    }
}

fn take_spread(
    picked: &mut Picked,
    records: &[Record],
    predicate: impl Fn(&Record) -> bool,
    why: &'static str,
) {
    let matches: Vec<_> = records.iter().filter(|record| predicate(record)).collect();
    let fresh = matches.iter().copied().find(|record| {
        !picked
            .iter()
            .any(|(number, _)| number == value(record, "bidNtceNo"))
    });
    if let Some(record) = fresh.or_else(|| matches.first().copied()) {
        take(picked, record, why);
    }
}

fn empty_fields(record: &Record) -> usize {
    record
        .values()
        .filter(|text| python_trim(text).is_empty())
        .count()
}

fn amount(record: &Record) -> u128 {
    value(record, "asignBdgtAmt").parse().unwrap_or(0)
}

fn curate(records: &[Record]) -> Picked {
    let mut picked = Vec::new();
    for record in records
        .iter()
        .filter(|record| python_trim(value(record, "bidBeginDate")).is_empty())
        .take(2)
    {
        take(
            &mut picked,
            record,
            "F1: 입찰일자 전체 결측 — 일자/시각 서식의 빈값 경계",
        );
    }

    let mut names = HashMap::new();
    for record in records {
        *names.entry(value(record, "bidNtceNm")).or_insert(0_usize) += 1;
    }
    if let Some(name) = records
        .iter()
        .map(|record| value(record, "bidNtceNm"))
        .find(|name| names[name] >= 2)
    {
        for record in records
            .iter()
            .filter(|record| value(record, "bidNtceNm") == name)
            .take(2)
        {
            take(
                &mut picked,
                record,
                "F3: 공고명 중복 — 파일명 충돌/데이터 손실 재현",
            );
        }
    }

    let mut by_name: Vec<_> = records.iter().collect();
    by_name.sort_by_key(|record| value(record, "bidNtceNm").chars().count());
    if let Some(record) = by_name.first() {
        take(&mut picked, record, "tour: 최단 공고명");
    }
    if let Some(record) = by_name.last() {
        take(&mut picked, record, "tour: 최장 공고명(영문혼합 가능)");
    }
    if let Some((_, record)) = records
        .iter()
        .enumerate()
        .max_by_key(|(index, record)| (empty_fields(record), Reverse(*index)))
    {
        take(&mut picked, record, "tour: 최다 빈필드 레코드");
    }

    take_spread(
        &mut picked,
        records,
        |record| {
            value(record, "cntrctCnclsMthdNm").contains("수의")
                || value(record, "bidwinrDcsnMthdNm").contains("수의")
        },
        "다양성: 수의계약(경쟁입찰 아님) 흐름",
    );
    take_spread(
        &mut picked,
        records,
        |record| value(record, "bidNtceSttusNm").contains("재입찰"),
        "다양성: 재입찰공고 상태",
    );
    take_spread(
        &mut picked,
        records,
        |record| {
            value(record, "cntrctCnclsSttusNm").contains("단가")
                || value(record, "bidNtceNm").contains("단가")
        },
        "다양성: 단가계약",
    );
    take_spread(
        &mut picked,
        records,
        |record| {
            !python_trim(value(record, "opengPlce")).is_empty()
                && !value(record, "opengPlce").contains("나라장터")
        },
        "다양성: 자유서식 개찰장소(방번호 등)",
    );
    take_spread(
        &mut picked,
        records,
        |record| {
            value(record, "indstrytyLmtYn") == "Y"
                && !python_trim(value(record, "bidprcPsblIndstrytyNm")).is_empty()
        },
        "다양성: 업종제한 Y(투찰가능업종 채워짐)",
    );
    take_spread(
        &mut picked,
        records,
        |record| value(record, "rgnLmtYn") == "Y",
        "다양성: 지역제한 Y",
    );
    take_spread(
        &mut picked,
        records,
        |record| value(record, "elctrnBidYn") == "N",
        "다양성: 전자입찰 N(오프라인 투찰)",
    );
    take_spread(
        &mut picked,
        records,
        |record| value(record, "cmmnCntrctYn") == "Y",
        "다양성: 공동계약 가능",
    );

    if let Some((_, record)) = records
        .iter()
        .enumerate()
        .max_by_key(|(index, record)| (amount(record), Reverse(*index)))
    {
        take_spread(
            &mut picked,
            records,
            |candidate| value(candidate, "bidNtceNo") == value(record, "bidNtceNo"),
            "tour: 최대 배정예산",
        );
    }
    if let Some(record) = records
        .iter()
        .filter(|record| amount(record) > 0)
        .min_by_key(|record| amount(record))
    {
        take_spread(
            &mut picked,
            records,
            |candidate| value(candidate, "bidNtceNo") == value(record, "bidNtceNo"),
            "tour: 최소 배정예산",
        );
    }
    if let Some(record) = records
        .iter()
        .filter(|record| {
            !python_trim(value(record, "bidBeginDate")).is_empty()
                && value(record, "cntrctCnclsMthdNm").contains("경쟁")
        })
        .min_by_key(|record| empty_fields(record))
    {
        take(
            &mut picked,
            record,
            "기준선: 필드 완비 happy-path(회귀 승격 1순위)",
        );
    }
    picked
}

fn parse_args() -> Result<(String, String, u64, bool), String> {
    let now = Local::now();
    let mut begin = (now - Duration::days(14)).format("%Y%m%d%H%M").to_string();
    let mut end = now.format("%Y%m%d%H%M").to_string();
    let mut rows = 100_u64;
    let mut dry_run = false;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--bgn" => begin = args.next().ok_or("--bgn 값이 필요합니다.")?,
            "--end" => end = args.next().ok_or("--end 값이 필요합니다.")?,
            "--num-rows" => {
                rows = args
                    .next()
                    .ok_or("--num-rows 값이 필요합니다.")?
                    .parse()
                    .map_err(|_| "--num-rows는 정수여야 합니다.")?;
            }
            "--dry-run" => dry_run = true,
            "--help" | "-h" => {
                println!(
                    "usage: cargo run -p hwpx-desktop --example nara_fixture --no-default-features -- [--bgn YYYYMMDDHHMM] [--end YYYYMMDDHHMM] [--num-rows N] [--dry-run]"
                );
                std::process::exit(0);
            }
            _ => return Err(format!("알 수 없는 인자: {arg}")),
        }
    }
    Ok((begin, end, rows, dry_run))
}

fn run() -> Result<(), String> {
    let (begin, end, rows, dry_run) = parse_args()?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .ok_or("저장소 경로를 찾지 못했습니다.")?;
    let key_path = root.join(".secrets/nara_service_key");
    let key = fs::read_to_string(&key_path)
        .map_err(|_| format!("[중단] ServiceKey 없음: {}", key_path.display()))?;
    let key = key.trim();
    if key.is_empty() {
        return Err("[중단] ServiceKey가 비어 있습니다.".into());
    }
    let source = NaraStdDataSource::new(key, &begin, &end, rows, 1, nara_fetcher(20_000));
    println!("[취득] {}", source.redacted_url());
    let records = source
        .records_checked()
        .map_err(|err| format!("[FINDING] 취득 실패: {err}"))?;
    let mut counts = HashMap::new();
    for record in &records {
        *counts
            .entry(value(record, "bsnsDivNm").to_string())
            .or_insert(0_usize) += 1;
    }
    let goods: Vec<_> = records
        .into_iter()
        .map(redact)
        .filter(|record| value(record, "bsnsDivNm") == "물품")
        .collect();
    println!(
        "[취득] 전체 {}건 {:?} → 물품 {}건",
        counts.values().sum::<usize>(),
        counts,
        goods.len()
    );
    let picked = curate(&goods);
    let by_no: HashMap<_, _> = goods
        .iter()
        .map(|record| (value(record, "bidNtceNo"), record))
        .collect();
    let items: Vec<_> = picked
        .iter()
        .map(|(number, _)| (*by_no[number.as_str()]).clone())
        .collect();
    let item_values: Vec<Value> = items
        .iter()
        .map(|record| {
            Value::Object(
                record
                    .iter()
                    .map(|(key, value)| (key.clone(), Value::String(value.clone())))
                    .collect(),
            )
        })
        .collect();
    let envelope: Value = json!({
        "_comment": format!("실 나라장터 표준서비스 물품 공고 다양성 표본({begin}~{end} 취득). PII 마스킹: 담당자명->'담당자', 전화 숫자->0, 이메일->official@example.go.kr. 각 레코드의 선택 목적은 README.md 참조. NaraStdDataSource.parse() 가 소비. 재생성: crates/hwpx-desktop/examples/nara_fixture.rs (라이브 취득이라 비결정적)."),
        "response": { "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {"pageNo": 1, "numOfRows": items.len(), "totalCount": items.len(), "items": item_values} }
    });
    let blob = serde_json::to_string_pretty(&envelope).map_err(|err| err.to_string())?;
    let parsed = nara::parse(blob.as_bytes()).map_err(|err| err.to_string())?;
    if parsed.len() != items.len() {
        return Err("parse 왕복 건수 불일치".into());
    }
    println!("\n[선택] {}건 (parse 왕복 OK):", items.len());
    for (number, reasons) in &picked {
        println!(
            "- {number} | {}",
            value(by_no[number.as_str()], "bidNtceNm")
        );
        for reason in reasons {
            println!("    · {reason}");
        }
    }
    if dry_run {
        println!("\n[dry-run] 파일 미기록.");
        return Ok(());
    }
    let output = root.join("tests/corpus/nara_mulpum/mulpum.json");
    fs::create_dir_all(output.parent().ok_or("출력 경로가 잘못되었습니다.")?)
        .map_err(|err| err.to_string())?;
    hwpx_desktop::atomic_file::write_bytes_atomic(&output, blob.as_bytes())
        .map_err(|err| err.to_string())?;
    println!("\n[기록] {}", output.display());
    println!("[알림] README.md 의 레코드→목적 매니페스트를 위 선택과 맞춰 갱신하세요.");
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    #[test]
    fn selecting_keeps_first_duplicate_pair_and_masks_contact_fields() {
        let mut first = Record::new();
        first.insert("bidNtceNo".into(), "A".into());
        first.insert("bidNtceNm".into(), "같은 이름".into());
        first.insert("bidBeginDate".into(), "".into());
        first.insert("담당OfclNm".into(), "홍길동".into());
        first.insert("phoneTel".into(), "010-1234".into());
        let mut second = first.clone();
        second.insert("bidNtceNo".into(), "B".into());
        let records = vec![redact(first), redact(second)];
        assert_eq!(records[0]["담당OfclNm"], "담당자");
        assert_eq!(records[0]["phoneTel"], "000-0000");
        assert_eq!(
            curate(&records)
                .iter()
                .map(|row| row.0.as_str())
                .collect::<Vec<_>>(),
            vec!["A", "B"]
        );
    }

    #[test]
    fn frozen_corpus_selection_matches_the_existing_purpose_order() {
        let records = nara::parse(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tests/corpus/nara_mulpum/mulpum.json"
        )))
        .unwrap();
        let actual: Vec<_> = curate(&records).into_iter().map(|row| row.0).collect();
        assert_eq!(
            actual,
            [
                "R26BK01621756",
                "R26BK01610529",
                "R26BK01626820",
                "R26BK01623111",
                "R26BK01617419",
                "R26BK01625381",
                "R26BK01626870",
                "R26BK01620476",
                "R26BK01631147",
                "R26BK01619047",
                "R26BK01625395",
                "R26BK01623300"
            ]
        );
    }
}
