//! Append-only managed delivery evidence; output facts come from the native runner.

use crate::atomic_file::write_bytes_atomic_exclusive;
use crate::managed_generation_service::ManagedGenerationResult;
use hwpx_filler::fields::FillNote;
use serde_json::{Value, json};
use std::io;
use std::path::{Path, PathBuf};

fn note_value(note: &FillNote) -> Value {
    json!({"field":note.field,"kind":note.kind.as_str(),"detail":note.detail})
}

pub(super) fn sidecar_path(out_dir: &Path, generated_at: &str) -> PathBuf {
    let stamp = generated_at
        .chars()
        .filter(char::is_ascii_digit)
        .collect::<String>();
    let base = if stamp.len() >= 14 {
        format!("fill-ledger-{}-{}", &stamp[..8], &stamp[8..14])
    } else {
        "fill-ledger".into()
    };
    let mut name = out_dir.join(format!("{base}.json"));
    let mut index = 1usize;
    while name.exists() {
        name = out_dir.join(format!("{base}-{index}.json"));
        index += 1;
    }
    name
}

pub(super) fn write_delivery_ledger(
    out_dir: &Path,
    generated_at: &str,
    work_id: &str,
    basis_digest: &str,
    plan_digest: &str,
    result: &ManagedGenerationResult,
) -> io::Result<PathBuf> {
    let (outcome, delivered, aborted) = match result {
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
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "no delivered evidence",
            ));
        }
    };
    let rows = delivered
        .iter()
        .map(|doc| {
            json!({
                "item_ordinal":doc.item_ordinal,"record_identity":doc.record_identity,
                "relative_path":doc.relative_path,"absolute_path":doc.absolute_path,
                "collision_disposition":doc.collision_disposition,"output_digest":doc.output_digest,
                "execution_notes":doc.execution_notes.iter().map(note_value).collect::<Vec<_>>(),
            })
        })
        .collect::<Vec<_>>();
    let mut payload = json!({
        "ledger_kind":"managed-delivery/v1","generated_at":generated_at,
        "work_authority_id":work_id,"execution_basis_digest":basis_digest,
        "plan_semantic_digest":plan_digest,"outcome":outcome,"delivered":rows,
    });
    if let Some(aborted) = aborted {
        payload
            .as_object_mut()
            .expect("ledger object")
            .insert("aborted".into(), aborted);
    }
    let bytes = serde_json::to_string_pretty(&payload)?;
    let mut name = sidecar_path(out_dir, generated_at);
    for _ in 0..100 {
        match write_bytes_atomic_exclusive(&name, bytes.as_bytes()) {
            Ok(()) => return Ok(name),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                name = sidecar_path(out_dir, generated_at);
            }
            Err(error) => return Err(error),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "delivery ledger names exhausted",
    ))
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use crate::managed_generation_service::DeliveredDocument;
    use hwpx_filler::fields::{FillNote, FillNoteKind};
    use std::fs;

    #[test]
    fn managed_ledger_accumulates_delivery_and_abort_evidence_without_source_pointer() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .join(format!("ledger-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let note = FillNote {
            field: "계약명".into(),
            kind: FillNoteKind::InlineStripped,
            detail: vec!["markpenBegin".into()],
        };
        let delivered = DeliveredDocument {
            item_ordinal: 0,
            record_identity: "rec-0".into(),
            relative_path: "doc-0.hwpx".into(),
            absolute_path: root.join("doc-0.hwpx"),
            collision_disposition: "WRITE_NEW".into(),
            output_digest: "sha256:0".into(),
            execution_notes: vec![note],
        };
        let stamp = "2026-07-12T14:05:03";
        let completed = ManagedGenerationResult::Completed {
            output_directory: root.clone(),
            delivered: vec![delivered.clone()],
        };
        let first =
            write_delivery_ledger(&root, stamp, "w-1", "sha256:b", "sha256:p", &completed).unwrap();
        assert_eq!(
            first.file_name().unwrap().to_string_lossy(),
            "fill-ledger-20260712-140503.json"
        );
        let saved: Value = serde_json::from_slice(&fs::read(&first).unwrap()).unwrap();
        assert_eq!(saved["ledger_kind"], "managed-delivery/v1");
        assert_eq!(saved["outcome"], "DeliveryCompleted");
        assert_eq!(
            saved["delivered"][0]["execution_notes"][0],
            json!({"field":"계약명","kind":"inline_stripped","detail":["markpenBegin"]})
        );
        assert!(saved.get("source").is_none());
        let aborted = ManagedGenerationResult::Aborted {
            code: "DELIVERY_WRITE_FAILED".into(),
            detail: "잠김".into(),
            failed_item_ordinal: 1,
            delivered: vec![delivered],
        };
        let second =
            write_delivery_ledger(&root, stamp, "w-1", "sha256:b", "sha256:p", &aborted).unwrap();
        assert_eq!(
            second.file_name().unwrap().to_string_lossy(),
            "fill-ledger-20260712-140503-1.json"
        );
        assert_eq!(
            fs::read(&first).unwrap(),
            serde_json::to_vec_pretty(&saved).unwrap()
        );
        let saved: Value = serde_json::from_slice(&fs::read(&second).unwrap()).unwrap();
        assert_eq!(saved["outcome"], "DeliveryAborted");
        assert_eq!(
            saved["aborted"],
            json!({"code":"DELIVERY_WRITE_FAILED","detail":"잠김","failed_item_ordinal":1})
        );
        assert_eq!(saved["delivered"][0]["item_ordinal"], 0);
        assert!(
            write_delivery_ledger(
                &root,
                stamp,
                "w-1",
                "b",
                "p",
                &ManagedGenerationResult::Refused {
                    code: "x".into(),
                    detail: "x".into(),
                    failed_item_ordinal: None
                }
            )
            .is_err()
        );
        fs::remove_dir_all(root).unwrap();
    }
}
