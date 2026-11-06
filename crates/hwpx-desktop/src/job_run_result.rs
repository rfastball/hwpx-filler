//! Project managed delivery facts into the existing Job result vocabulary.

use crate::managed_generation_service::{DeliveredDocument, ManagedGenerationResult};
use hwpx_filler::data_source::Record;
use hwpx_filler::identity_summary::identity_summary;
use hwpx_filler::result_errors::{classify_result_error, describe_fill_note};
use serde_json::{Value, json};

pub(super) struct RunProjection {
    pub result: Value,
    pub generated_indices: Option<Vec<usize>>,
    pub failed_indices: Option<Vec<usize>>,
    pub delivered: Option<Vec<DeliveredDocument>>,
    pub completed: bool,
}

pub(super) fn run_title(status: &str, cancelled: bool, succeeded: usize, failed: usize) -> String {
    if cancelled {
        return format!("생성을 중단했습니다 · {succeeded}개 완료");
    }
    match status {
        "completed" => format!("문서 생성 완료 · {succeeded}개"),
        "partiallyCompleted" => format!("{succeeded}개 성공 · {failed}개 실패"),
        _ => "문서 생성 실패".into(),
    }
}

fn failure_row(
    ordinal: usize,
    reason: &str,
    filename: &str,
    indices: &[usize],
    records: &[Record],
    filename_sources: &[String],
) -> (usize, Value) {
    let index = indices.get(ordinal).copied().unwrap_or(ordinal);
    let identity = identity_summary(records, None, filename_sources);
    let (reason, known) = classify_result_error(reason);
    (
        index,
        json!({
            "index":index,
            "identity":records.get(index).map_or(String::new(), |record| identity.display_for(record)),
            "filename":filename,"reason":reason,"known":known,
        }),
    )
}

fn delivered_rows(delivered: &[DeliveredDocument]) -> Vec<Value> {
    delivered
        .iter()
        .map(|doc| {
            json!({
                "ordinal":doc.item_ordinal,"filename":doc.relative_path,
                "disposition":doc.collision_disposition,"path":doc.absolute_path,
            })
        })
        .collect()
}

fn fill_notes(delivered: &[DeliveredDocument]) -> Vec<String> {
    let mut seen = Vec::new();
    for doc in delivered {
        for note in &doc.execution_notes {
            if !seen.contains(note) {
                seen.push(note.clone());
            }
        }
    }
    seen.iter().map(describe_fill_note).collect()
}

fn blank_note(marked_fields: &[String]) -> String {
    if marked_fields.is_empty() {
        String::new()
    } else {
        format!(
            " 빈 값 표시 필드 {}개({}).",
            marked_fields.len(),
            marked_fields.join(", ")
        )
    }
}

pub(super) struct ProjectionInput<'a> {
    pub outcome: &'a ManagedGenerationResult,
    pub output_directory: &'a str,
    pub resolved_names: &'a [String],
    pub indices: &'a [usize],
    pub records: &'a [Record],
    pub filename_sources: &'a [String],
    pub marked_fields: &'a [String],
    pub revisions: Value,
    pub ledger_note: &'a str,
}

pub(super) fn project(input: ProjectionInput<'_>) -> RunProjection {
    let ProjectionInput {
        outcome,
        output_directory,
        resolved_names,
        indices,
        records,
        filename_sources,
        marked_fields,
        revisions,
        ledger_note,
    } = input;
    let total = indices.len();
    let blank_note = blank_note(marked_fields);
    if let ManagedGenerationResult::Refused { code, detail, .. } = outcome {
        let message = match code.as_str() {
            "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR" => {
                "적용된 템플릿 바이트 무결성 확인에 실패해 생성을 멈췄습니다."
            }
            "STRUCTURE_NOTATION_UNCOMPILED" => {
                "구간 표기가 아직 변환되지 않았습니다. '템플릿' 탭에서 '누름틀·구간 변환'을 먼저 실행하세요."
            }
            _ => detail,
        };
        return RunProjection {
            result: json!({"ok":false,"error":message,"level":"warn"}),
            generated_indices: None,
            failed_indices: None,
            delivered: None,
            completed: false,
        };
    }
    if let ManagedGenerationResult::Cancelled { attempted, total } = outcome {
        let summary = format!(
            "중단했습니다. 시도 {attempted}/{total}건 — 안착 전이라 문서는 만들지 않았습니다.{blank_note}"
        );
        return RunProjection {
            result: json!({
                "ok":true,"status":"cancelled","title":run_title("cancelled",true,0,0),
                "stage":"","message":"","known":true,"summary":summary,"level":"warn",
                "out_dir":output_directory,"succeeded":0,"failed":0,"failed_selectable":0,
                "total":total,"failures":[],"fill_notes":[],"cancelled":true,
                "attempted":attempted,"unstarted":total-attempted,"revisions":revisions,
            }),
            generated_indices: None,
            failed_indices: None,
            delivered: None,
            completed: false,
        };
    }
    let (delivered, failed_ordinal, code, detail, readback) = match outcome {
        ManagedGenerationResult::Completed { delivered, .. } => (delivered, None, "", "", false),
        ManagedGenerationResult::Aborted {
            delivered,
            failed_item_ordinal,
            code,
            detail,
        } => (
            delivered,
            Some(*failed_item_ordinal),
            code.as_str(),
            detail.as_str(),
            false,
        ),
        ManagedGenerationResult::ReadBackFailed {
            delivered,
            failed_item_ordinal,
            code,
            detail,
        } => (
            delivered,
            Some(*failed_item_ordinal),
            code.as_str(),
            detail.as_str(),
            true,
        ),
        _ => unreachable!("terminal outcome cases handled above"),
    };
    let delivered_listing = delivered_rows(delivered);
    let fill_notes = fill_notes(delivered);
    if let Some(ordinal) = failed_ordinal {
        let succeeded = delivered.len() - usize::from(readback);
        let filename = resolved_names.get(ordinal).map_or("", String::as_str);
        let (failed_index, failure) = failure_row(
            ordinal,
            detail,
            filename,
            indices,
            records,
            filename_sources,
        );
        let status = if succeeded > 0 {
            "partiallyCompleted"
        } else {
            "failed"
        };
        let unstarted = if readback {
            0
        } else {
            total.saturating_sub(succeeded + 1)
        };
        let summary = if readback {
            format!(
                "완료. 성공 {succeeded}/{total}, 실패 1. 문서는 만들었지만 만든 뒤 다시 읽어 확인하는 데 실패했습니다({code}). 해당 파일을 직접 열어 내용을 확인하세요.{blank_note}{ledger_note}"
            )
        } else {
            format!(
                "완료. 성공 {succeeded}/{total}, 실패 1. 미착수 {unstarted}건 — 앉은 문서는 그대로 유지됩니다.{blank_note}{ledger_note}"
            )
        };
        return RunProjection {
            result: json!({
                "ok":true,"status":status,"title":run_title(status,false,succeeded,1),
                "stage":"","message":"","known":true,"summary":summary,"level":"danger",
                "out_dir":output_directory,"succeeded":succeeded,"failed":1,"failed_selectable":1,
                "total":total,"failures":[failure],"fill_notes":fill_notes,"cancelled":false,
                "attempted":if readback {total}else{succeeded+1},"unstarted":unstarted,
                "revisions":revisions,"delivered":delivered_listing,
            }),
            generated_indices: None,
            failed_indices: Some(vec![failed_index]),
            delivered: Some(delivered.clone()),
            completed: false,
        };
    }
    let succeeded = delivered.len();
    let mut summary = format!("완료. 성공 {succeeded}/{total}, 실패 0.{blank_note}");
    if !fill_notes.is_empty() {
        summary.push_str(&format!(
            " 채움 주의 {}건(아래 기록 확인).",
            fill_notes.len()
        ));
    }
    summary.push_str(ledger_note);
    RunProjection {
        result: json!({
            "ok":true,"status":"completed","title":run_title("completed",false,succeeded,0),
            "stage":"","message":"","known":true,"summary":summary,
            "level":if ledger_note.is_empty(){"ok"}else{"danger"},
            "out_dir":output_directory,"succeeded":succeeded,"failed":0,"failed_selectable":0,
            "total":total,"failures":[],"fill_notes":fill_notes,"cancelled":false,
            "attempted":total,"unstarted":0,"revisions":revisions,"delivered":delivered_listing,
        }),
        generated_indices: Some(indices.to_vec()),
        failed_indices: Some(vec![]),
        delivered: Some(delivered.clone()),
        completed: true,
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;

    fn project_outcome(outcome: &ManagedGenerationResult, ledger_note: &str) -> RunProjection {
        project(ProjectionInput {
            outcome,
            output_directory: "C:/out",
            resolved_names: &["a.hwpx".into(), "b.hwpx".into()],
            indices: &[2, 0],
            records: &[
                Record::from_iter([("name".into(), "A".into())]),
                Record::from_iter([("name".into(), "B".into())]),
                Record::from_iter([("name".into(), "C".into())]),
            ],
            filename_sources: &["name".into()],
            marked_fields: &[],
            revisions: json!({"template":2,"binding":3}),
            ledger_note,
        })
    }

    fn documents() -> Vec<DeliveredDocument> {
        ["a.hwpx", "b.hwpx"]
            .into_iter()
            .enumerate()
            .map(|(index, name)| DeliveredDocument {
                item_ordinal: index,
                record_identity: format!("rec-{index}"),
                relative_path: name.into(),
                absolute_path: std::path::Path::new("C:/out").join(name),
                collision_disposition: "WRITE_NEW".into(),
                output_digest: format!("sha256:{}", "0".repeat(64)),
                execution_notes: vec![],
            })
            .collect()
    }

    #[test]
    fn delivery_outcomes_preserve_prior_evidence_and_report_post_write_failure() {
        for outcome in [
            ManagedGenerationResult::Refused {
                code: "REFUSED".into(),
                detail: "거절됨".into(),
                failed_item_ordinal: None,
            },
            ManagedGenerationResult::Cancelled {
                attempted: 1,
                total: 2,
            },
        ] {
            let projected = project_outcome(&outcome, "");
            assert!(projected.delivered.is_none());
            assert!(projected.generated_indices.is_none());
            assert!(projected.failed_indices.is_none());
            assert!(!projected.completed);
            assert_eq!(projected.result["level"], "warn");
            if matches!(outcome, ManagedGenerationResult::Cancelled { .. }) {
                assert_eq!(projected.result["status"], "cancelled");
                assert_eq!(projected.result["attempted"], 1);
                assert_eq!(projected.result["unstarted"], 1);
                assert_eq!(projected.result["succeeded"], 0);
            } else {
                assert_eq!(
                    projected.result,
                    json!({"ok":false,"error":"거절됨","level":"warn"})
                );
            }
        }
        let docs = documents();
        let completed = ManagedGenerationResult::Completed {
            output_directory: "C:/out".into(),
            delivered: docs.clone(),
        };
        for note in [
            "",
            " 문서는 만들어졌지만 실행 기록 저장에 실패했습니다(ledger denied).",
        ] {
            let projected = project_outcome(&completed, note);
            assert!(projected.completed);
            assert_eq!(projected.delivered, Some(docs.clone()));
            assert_eq!(projected.generated_indices, Some(vec![2, 0]));
            assert_eq!(projected.failed_indices, Some(vec![]));
            assert_eq!(projected.result["status"], "completed");
            assert_eq!(projected.result["succeeded"], 2);
            assert_eq!(projected.result["failed"], 0);
            assert_eq!(
                projected.result["level"],
                if note.is_empty() { "ok" } else { "danger" }
            );
            assert!(
                projected.result["summary"]
                    .as_str()
                    .unwrap()
                    .ends_with(note)
            );
        }
        let failed = ManagedGenerationResult::ReadBackFailed {
            delivered: docs.clone(),
            failed_item_ordinal: 1,
            code: "ARTIFACT_DIGEST_MISMATCH".into(),
            detail: "b.hwpx 의 내용이 안착 기록과 다르다".into(),
        };
        let projected = project_outcome(&failed, "");
        assert_eq!(projected.delivered, Some(docs));
        assert_eq!(projected.failed_indices, Some(vec![0]));
        assert!(projected.generated_indices.is_none() && !projected.completed);
        let result = projected.result;
        assert_eq!(result["status"], "partiallyCompleted");
        assert_eq!(result["level"], "danger");
        assert_eq!(
            (
                result["succeeded"].as_u64(),
                result["failed"].as_u64(),
                result["attempted"].as_u64(),
                result["unstarted"].as_u64()
            ),
            (Some(1), Some(1), Some(2), Some(0))
        );
        assert_eq!(result["failures"][0]["index"], 0);
        assert_eq!(result["failures"][0]["filename"], "b.hwpx");
        assert_eq!(
            result["failures"][0]["reason"],
            "b.hwpx 의 내용이 안착 기록과 다르다"
        );
        let summary = result["summary"].as_str().unwrap();
        assert!(summary.contains("ARTIFACT_DIGEST_MISMATCH") && summary.contains("다시 읽어 확인"));
        assert!(!summary.contains("앉은 문서는 그대로 유지됩니다"));
        let aborted = project_outcome(
            &ManagedGenerationResult::Aborted {
                delivered: vec![],
                failed_item_ordinal: 0,
                code: "DELIVERY_WRITE_FAILED".into(),
                detail: "access denied".into(),
            },
            "",
        );
        assert_eq!(aborted.result["status"], "failed");
        assert_eq!(aborted.result["attempted"], 1);
        assert_eq!(aborted.result["unstarted"], 1);
        assert_eq!(aborted.failed_indices, Some(vec![2]));
    }
}
