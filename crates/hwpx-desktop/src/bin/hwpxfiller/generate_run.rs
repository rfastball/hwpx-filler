//! CLI presentation and temporary-workspace ownership around managed generation.

use super::generate::{
    GENERATION_ARGPARSE_USAGE, GenerateArgs, LoadedRecords, SourceFailure, failure, load_records,
    prepare_generation,
};
use chrono::Local;
use hwpx_desktop::headless_generation::{
    HeadlessExecuted, HeadlessGenerationResult, HeadlessInput, TEMPLATE_INITIALIZATION,
    run_headless_generation,
};
use hwpx_desktop::managed_generation_service::{DeliveredDocument, ManagedGenerationResult};
use hwpx_filler::execution_contract_set::plan_semantic_digest;
use hwpx_filler::fields::{FillNote, FillNoteKind};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use uuid::Uuid;

struct TemporaryWorkspace(PathBuf);
impl TemporaryWorkspace {
    fn new() -> Result<Self, String> {
        let path = std::env::temp_dir().join(format!("hwpxfiller-cli-{}", Uuid::new_v4()));
        fs::create_dir(&path).map_err(|error| error.to_string())?;
        Ok(Self(path))
    }
}
impl Drop for TemporaryWorkspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn report_failure(item: SourceFailure) -> u8 {
    for notice in &item.notices {
        eprintln!("{notice}");
    }
    if item.argparse {
        eprintln!("{GENERATION_ARGPARSE_USAGE}");
        eprintln!("hwpxfiller: error: {}", item.message);
        return item.exit_code;
    }
    let mut lines = item.message.lines();
    if let Some(first) = lines.next() {
        eprintln!("[오류] {first}");
    }
    for line in lines {
        eprintln!("{line}");
    }
    item.exit_code
}

fn describe_note(note: &FillNote) -> String {
    match note.kind {
        FillNoteKind::InlineStripped => format!(
            "누름틀 '{}' 값 안의 인라인 요소({})를 값과 함께 제거하고 채웠습니다. 형광펜 등 표식이 사라졌을 수 있으니 산출물을 확인하세요.",
            note.field,
            note.detail.join(", ")
        ),
        FillNoteKind::SlotSynthesized => format!(
            "빈 누름틀 '{}' 에 값 자리를 새로 만들어 채웠습니다. 서식은 누름틀 주변 서식을 따릅니다.",
            note.field
        ),
        FillNoteKind::OccurrenceUnfillable => format!(
            "누름틀 '{}' 자리 중 구조상 기입할 수 없는 곳이 있어 건너뛰었습니다. 산출물에서 해당 자리를 확인하세요.",
            note.field
        ),
    }
}

fn delivered_json(doc: &DeliveredDocument) -> Value {
    json!({
        "item_ordinal": doc.item_ordinal,
        "record_identity": doc.record_identity,
        "relative_path": doc.relative_path,
        "absolute_path": doc.absolute_path.to_string_lossy(),
        "collision_disposition": doc.collision_disposition,
        "output_digest": doc.output_digest,
        "execution_notes": doc.execution_notes.iter().map(|note| json!({
            "field": note.field,
            "kind": note.kind.as_str(),
            "detail": note.detail,
        })).collect::<Vec<_>>(),
    })
}

fn ledger_path(out: &Path, generated_at: &str) -> PathBuf {
    let digits = generated_at
        .chars()
        .filter(char::is_ascii_digit)
        .collect::<String>();
    let base = if digits.len() >= 14 {
        format!("fill-ledger-{}-{}", &digits[..8], &digits[8..14])
    } else {
        "fill-ledger".into()
    };
    let mut suffix = 0;
    loop {
        let name = if suffix == 0 {
            format!("{base}.json")
        } else {
            format!("{base}-{suffix}.json")
        };
        let path = out.join(name);
        if !path.exists() {
            return path;
        }
        suffix += 1;
    }
}

fn write_ledger(
    args: &GenerateArgs,
    loaded: &LoadedRecords,
    result: &HeadlessExecuted,
) -> Result<PathBuf, String> {
    let (kind, delivered, aborted): (&str, &[DeliveredDocument], Option<Value>) = match &result
        .outcome
    {
        ManagedGenerationResult::Completed { delivered, .. } => {
            ("DeliveryCompleted", delivered, None)
        }
        ManagedGenerationResult::Aborted {
            code,
            detail,
            failed_item_ordinal,
            delivered,
        } => (
            "DeliveryAborted",
            delivered,
            Some(json!({"code":code,"detail":detail,"failed_item_ordinal":failed_item_ordinal})),
        ),
        ManagedGenerationResult::ReadBackFailed {
            code,
            detail,
            failed_item_ordinal,
            delivered,
        } => (
            "ManagedReadBackFailed",
            delivered,
            Some(json!({"code":code,"detail":detail,"failed_item_ordinal":failed_item_ordinal})),
        ),
        _ => return Err("배달 전 결과에는 생성 원장을 쓸 수 없습니다.".into()),
    };
    let mut payload = json!({
        "ledger_kind": "managed-delivery/v1",
        "generated_at": result.validated_at,
        "work_authority_id": result.work_authority_id,
        "execution_basis_digest": result.execution_basis_digest,
        "plan_semantic_digest": plan_semantic_digest(&result.plan_payload).map_err(|error| error.to_string())?,
        "outcome": kind,
        "delivered": delivered.iter().map(delivered_json).collect::<Vec<_>>(),
        "source": loaded.source_pointer,
    });
    if let Some(aborted) = aborted {
        payload["aborted"] = aborted;
    }
    let path = ledger_path(&args.out, &result.validated_at);
    let bytes = serde_json::to_vec_pretty(&payload).map_err(|error| error.to_string())?;
    super::write_bytes_atomic(&path, &bytes).map_err(|error| error.to_string())?;
    Ok(path)
}

fn report_result(
    args: &GenerateArgs,
    loaded: &LoadedRecords,
    result: HeadlessGenerationResult,
    write: impl FnOnce(&GenerateArgs, &LoadedRecords, &HeadlessExecuted) -> Result<PathBuf, String>,
) -> u8 {
    match result {
        HeadlessGenerationResult::NeedsOverwrite(item) => {
            eprintln!(
                "[오류] 같은 이름의 파일이 이미 있어 덮어쓰게 됩니다: {}",
                item.conflict_names.join(", ")
            );
            eprintln!("덮어쓰려면 --overwrite 를 지정하세요.");
            1
        }
        HeadlessGenerationResult::Refused(item) => {
            if item.code == "PATH_OCCUPANCY_OBSERVATION_FAILED" {
                eprintln!(
                    "[오류] 파일을 읽거나 쓸 수 없습니다: {} — {}",
                    args.out.display(),
                    item.details.join("; ")
                );
                return 2;
            }
            if item.stage == TEMPLATE_INITIALIZATION {
                eprintln!(
                    "[오류] 이 템플릿을 문서 작업으로 초기화할 수 없어 생성할 수 없습니다({}). 템플릿 파일을 확인하세요.",
                    item.code
                );
                return 1;
            }
            eprintln!("[오류] 문서를 만들지 않았습니다({}).", item.code);
            for detail in item.details {
                eprintln!("  {detail}");
            }
            1
        }
        HeadlessGenerationResult::Executed(result) => report_executed(args, loaded, &result, write),
    }
}

fn report_executed(
    args: &GenerateArgs,
    loaded: &LoadedRecords,
    result: &HeadlessExecuted,
    write: impl FnOnce(&GenerateArgs, &LoadedRecords, &HeadlessExecuted) -> Result<PathBuf, String>,
) -> u8 {
    let total = result.resolved_delivery.ordered_items.len();
    let (delivered, failed, complete): (&[DeliveredDocument], Option<(usize, &str)>, bool) =
        match &result.outcome {
            ManagedGenerationResult::Completed { delivered, .. } => (delivered, None, true),
            ManagedGenerationResult::Aborted {
                failed_item_ordinal,
                detail,
                delivered,
                ..
            } => (delivered, Some((*failed_item_ordinal, detail)), false),
            ManagedGenerationResult::ReadBackFailed {
                failed_item_ordinal,
                detail,
                delivered,
                ..
            } => (delivered, Some((*failed_item_ordinal, detail)), false),
            ManagedGenerationResult::Refused { code, detail, .. } => {
                eprintln!("[오류] 문서를 만들지 않았습니다({code}): {detail}");
                return 1;
            }
            ManagedGenerationResult::Cancelled { .. } => {
                eprintln!("[오류] 문서를 만들지 않았습니다(CANCELLED).");
                return 1;
            }
        };
    let succeeded = delivered.len()
        - usize::from(matches!(
            result.outcome,
            ManagedGenerationResult::ReadBackFailed { .. }
        ));
    println!("완료: {succeeded}/{total} 성공 -> {}", args.out.display());
    report_failed(result, delivered, failed);
    report_notes(delivered);
    if args.ledger {
        eprintln!("{}", ledger_notice(write(args, loaded, result), succeeded));
    }
    u8::from(!complete)
}

fn report_failed(
    result: &HeadlessExecuted,
    delivered: &[DeliveredDocument],
    failed: Option<(usize, &str)>,
) {
    let total = result.resolved_delivery.ordered_items.len();
    if let Some((ordinal, detail)) = failed {
        match &result.outcome {
            ManagedGenerationResult::Aborted { .. } => {
                let path =
                    &result.resolved_delivery.ordered_items[ordinal].resolved_output_relative_path;
                eprintln!("  [실패] {path}: {detail}");
                let unstarted = total.saturating_sub(delivered.len() + 1);
                if unstarted > 0 {
                    eprintln!("  [미착수] {unstarted}건 — 앞서 쓴 문서는 그대로 유지됩니다.");
                }
            }
            ManagedGenerationResult::ReadBackFailed { .. } => {
                let path = &delivered[ordinal].relative_path;
                eprintln!("  [실패] {path}: 만든 뒤 다시 읽어 확인하지 못했습니다({detail})");
            }
            _ => {}
        }
    }
}

fn report_notes(delivered: &[DeliveredDocument]) {
    let mut seen = Vec::<FillNote>::new();
    for doc in delivered {
        for note in &doc.execution_notes {
            if !seen.contains(note) {
                seen.push(note.clone());
                eprintln!("  [주의] {}", describe_note(note));
            }
        }
    }
}

fn ledger_notice(result: Result<PathBuf, String>, succeeded: usize) -> String {
    match result {
        Ok(path) => format!("[원장] {} 저장", path.display()),
        Err(error) => format!(
            "[원장 실패] 사이드카를 저장하지 못했습니다: {error} — 생성물({succeeded}건)은 저장돼 있습니다."
        ),
    }
}

pub fn execute(args: GenerateArgs) -> u8 {
    let loaded = match load_records(&args) {
        Ok(value) => value,
        Err(error) => return report_failure(error),
    };
    execute_loaded(args, loaded)
}

pub(super) fn execute_loaded(args: GenerateArgs, loaded: LoadedRecords) -> u8 {
    for line in &loaded.notices {
        eprintln!("{line}");
    }
    let prepared = match prepare_generation(&args, &loaded, super::field_lines(&args.template)) {
        Ok(value) => value,
        Err(error) => return report_failure(error),
    };
    for line in prepared.notices.iter().skip(loaded.notices.len()) {
        eprintln!("{line}");
    }
    let workspace = match TemporaryWorkspace::new() {
        Ok(value) => value,
        Err(error) => {
            return report_failure(failure(2, format!("파일을 읽거나 쓸 수 없습니다: {error}")));
        }
    };
    let clock: Arc<dyn Fn() -> String + Send + Sync> =
        Arc::new(|| Local::now().format("%Y-%m-%dT%H:%M:%S").to_string());
    let result = run_headless_generation(HeadlessInput {
        workspace: &workspace.0,
        template_path: &args.template,
        mapping: &prepared.mapping,
        filename_pattern: &args.pattern,
        records: &loaded.records,
        source_schema_keys: &loaded.source_keys,
        output_directory: &args.out,
        overwrite: args.overwrite,
        clock,
    });
    match result {
        Ok(value) => report_result(&args, &loaded, value, write_ledger),
        Err(error) => report_failure(failure(2, format!("파일을 읽거나 쓸 수 없습니다: {error}"))),
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::super::generate::{Parsed, parse};
    use super::*;

    #[test]
    fn ledger_write_failure_reports_the_saved_documents_without_changing_the_exit_code() {
        let root = super::super::tests::test_directory();
        let template = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/corpus/real/bid_notice_limited_under100m.hwpx");
        let data = root.join("data.csv");
        fs::write(&data, "입찰공고번호,공고명\nR-1,공고\n").unwrap();
        let Parsed::Generate(args) = parse(&[
            "--template".into(),
            template.into_os_string(),
            "--data".into(),
            data.into_os_string(),
            "--out".into(),
            root.join("out").into_os_string(),
            "--ledger".into(),
            "--pattern".into(),
            "공고-{{입찰공고번호}}".into(),
        ])
        .unwrap() else {
            panic!("generation arguments")
        };
        let loaded = load_records(&args).unwrap_or_else(|error| panic!("{}", error.message));
        let prepared =
            prepare_generation(&args, &loaded, super::super::field_lines(&args.template))
                .unwrap_or_else(|error| panic!("{}", error.message));
        let result = run_headless_generation(HeadlessInput {
            workspace: &root.join("workspace"),
            template_path: &args.template,
            mapping: &prepared.mapping,
            filename_pattern: &args.pattern,
            records: &loaded.records,
            source_schema_keys: &loaded.source_keys,
            output_directory: &args.out,
            overwrite: false,
            clock: Arc::new(|| "2026-11-06T12:00:00".into()),
        })
        .unwrap();
        assert!(matches!(&result, HeadlessGenerationResult::Executed(result)
            if matches!(result.outcome, ManagedGenerationResult::Completed { .. })));
        let document = args.out.join("공고-R-1.hwpx");
        let before = fs::read(&document).unwrap();
        let blocked = root.join("blocked");
        fs::write(&blocked, "occupied").unwrap();
        let code = report_result(&args, &loaded, result, |args, loaded, result| {
            let mut args = args.clone();
            args.out = blocked.clone();
            let error = write_ledger(&args, loaded, result).unwrap_err();
            let message = ledger_notice(Err(error.clone()), 1);
            assert!(message.starts_with("[원장 실패]"));
            assert!(message.contains("생성물(1건)은 저장돼 있습니다."));
            Err(error)
        });
        assert_eq!(code, 0);
        assert_eq!(fs::read(&document).unwrap(), before);
        assert_eq!(fs::read(&blocked).unwrap(), b"occupied");
        assert_eq!(fs::read_dir(&args.out).unwrap().count(), 1);
        fs::remove_dir_all(root).unwrap();
    }
}
