//! Durable create-once qualification records with attempt/evidence binding.

use crate::candidate_store::{ObjectFileError, ObjectFileErrorKind, ObjectFileStore, safe_id};
use hwpx_filler::execution_structure::QualificationProfileManifest;
use hwpx_filler::qualification_evidence::{
    QualificationAttempt, QualificationEvidence, QualificationProfileRevocation, decode_attempt,
    decode_evidence, decode_manifest, decode_revocation, encode_attempt, encode_evidence,
    encode_manifest, encode_revocation, validate_evidence_binding, verify_manifest,
};
use std::path::PathBuf;

pub struct FileQualificationObjectStore {
    objects: ObjectFileStore,
}
impl FileQualificationObjectStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self {
            objects: ObjectFileStore::new(root),
        }
    }
    pub fn object_path(&self, kind: &str, identity: &str) -> Result<PathBuf, ObjectFileError> {
        self.objects.path(kind, identity)
    }
    pub fn put_manifest(
        &self,
        manifest: &QualificationProfileManifest,
    ) -> Result<(), ObjectFileError> {
        verify_manifest(manifest).map_err(|e| ObjectFileError {
            kind: ObjectFileErrorKind::Corrupt,
            detail: e.detail,
        })?;
        self.objects.put(
            "manifests",
            &manifest.qualification_profile_id,
            &encode_manifest(manifest),
        )
    }
    pub fn get_manifest(&self, id: &str) -> Result<QualificationProfileManifest, ObjectFileError> {
        decode_manifest(&self.objects.get("manifests", id)?).map_err(|e| ObjectFileError {
            kind: ObjectFileErrorKind::Corrupt,
            detail: e.detail,
        })
    }
    pub fn put_revocation(
        &self,
        revocation: &QualificationProfileRevocation,
    ) -> Result<(), ObjectFileError> {
        self.objects.put(
            "revocations",
            &revocation.qualification_profile_id,
            &encode_revocation(revocation),
        )
    }
    pub fn get_revocation(
        &self,
        id: &str,
    ) -> Result<Option<QualificationProfileRevocation>, ObjectFileError> {
        if !self.objects.exists("revocations", id)? {
            return Ok(None);
        }
        decode_revocation(&self.objects.get("revocations", id)?)
            .map(Some)
            .map_err(|e| ObjectFileError {
                kind: ObjectFileErrorKind::Corrupt,
                detail: e.detail,
            })
    }
    pub fn is_revoked(&self, id: &str) -> Result<bool, ObjectFileError> {
        self.objects.exists("revocations", id)
    }
    pub fn put_attempt(&self, attempt: &QualificationAttempt) -> Result<(), ObjectFileError> {
        if let Some(id) = &attempt.evidence_id {
            safe_id(id)?;
        }
        attempt.validate().map_err(|e| ObjectFileError {
            kind: ObjectFileErrorKind::Corrupt,
            detail: e.detail,
        })?;
        self.objects
            .put("attempts", &attempt.attempt_id, &encode_attempt(attempt))
    }
    pub fn get_attempt(&self, id: &str) -> Result<QualificationAttempt, ObjectFileError> {
        decode_attempt(&self.objects.get("attempts", id)?).map_err(|e| ObjectFileError {
            kind: ObjectFileErrorKind::Corrupt,
            detail: e.detail,
        })
    }
    pub fn put_evidence(&self, evidence: &QualificationEvidence) -> Result<(), ObjectFileError> {
        let attempt = self.get_attempt(&evidence.attempt_id)?;
        validate_evidence_binding(&attempt, evidence).map_err(|e| ObjectFileError {
            kind: ObjectFileErrorKind::DanglingReference,
            detail: e.detail,
        })?;
        self.objects.put(
            "evidence",
            &evidence.evidence_id,
            &encode_evidence(evidence),
        )
    }
    pub fn get_evidence(&self, id: &str) -> Result<QualificationEvidence, ObjectFileError> {
        decode_evidence(&self.objects.get("evidence", id)?).map_err(|e| ObjectFileError {
            kind: ObjectFileErrorKind::Corrupt,
            detail: e.detail,
        })
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use hwpx_filler::execution_structure::content_digest;
    use serde_json::{Map, json};
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn create_once_evidence_binding_and_corrupt_reread() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/qualification-store-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let store = FileQualificationObjectStore::new(&root);
        assert!(store.get_revocation("profile").unwrap().is_none());
        let manifest_payload = json!({"rules":["x"]});
        let manifest = QualificationProfileManifest {
            qualification_profile_id: "profile".into(),
            media: "hwpx".into(),
            adapter_contract_version: "adapter/v1".into(),
            product_rule_version: "product/v1".into(),
            operation_alphabet_version: "ops/v1".into(),
            projection_schema_version: "proj/v1".into(),
            manifest_digest: content_digest(&manifest_payload),
            manifest_payload,
            created_at: "t0".into(),
        };
        store.put_manifest(&manifest).unwrap();
        store.put_manifest(&manifest).unwrap();
        assert_eq!(store.get_manifest("profile").unwrap(), manifest);
        let mut changed = manifest.clone();
        changed.media = "txt".into();
        assert_eq!(
            store.put_manifest(&changed).unwrap_err().kind,
            ObjectFileErrorKind::AlreadyExists
        );
        let attempt = QualificationAttempt {
            attempt_id: "A1".into(),
            preparation_id: "P1".into(),
            revision_id: "R1".into(),
            qualification_profile_id: "profile".into(),
            outcome: "FAIL".into(),
            evidence_id: Some("E1".into()),
            error_code: None,
            started_at: "t1".into(),
            completed_at: "t2".into(),
        };
        let mut bad = attempt.clone();
        bad.evidence_id = Some("ev/1".into());
        assert_eq!(
            store.put_attempt(&bad).unwrap_err().kind,
            ObjectFileErrorKind::InvalidId
        );
        assert!(!root.join("attempts").exists());
        bad = attempt.clone();
        bad.evidence_id = None;
        assert_eq!(
            store.put_attempt(&bad).unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        assert!(!root.join("attempts").exists());
        let mut invalid_manifest = manifest.clone();
        invalid_manifest.qualification_profile_id = "invalid".into();
        invalid_manifest.manifest_payload = json!({"changed":true});
        assert_eq!(
            store.put_manifest(&invalid_manifest).unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        assert!(!store.object_path("manifests", "invalid").unwrap().exists());
        store.put_attempt(&attempt).unwrap();
        store.put_attempt(&attempt).unwrap();
        assert_eq!(store.get_attempt("A1").unwrap(), attempt);
        let evidence = QualificationEvidence {
            evidence_id: "E1".into(),
            attempt_id: "A1".into(),
            revision_id: "R1".into(),
            qualification_profile_id: "profile".into(),
            result: "FAIL".into(),
            structure_projection: None,
            diagnostics: vec![Map::from_iter([
                ("kind".into(), json!("missing-field")),
                ("message".into(), json!("missing")),
            ])],
            engine_metadata: Map::new(),
            qualified_at: "t2".into(),
        };
        let mut mismatched = evidence.clone();
        mismatched.revision_id = "other".into();
        assert_eq!(
            store.put_evidence(&mismatched).unwrap_err().kind,
            ObjectFileErrorKind::DanglingReference
        );
        store.put_evidence(&evidence).unwrap();
        store.put_evidence(&evidence).unwrap();
        assert_eq!(store.get_evidence("E1").unwrap(), evidence);
        assert_eq!(
            store.get_evidence("missing").unwrap_err().kind,
            ObjectFileErrorKind::NotFound
        );
        assert!(!store.is_revoked("profile").unwrap());
        let revoked = QualificationProfileRevocation {
            qualification_profile_id: "profile".into(),
            reason: "superseded".into(),
            authority: "owner".into(),
            revoked_at: "t3".into(),
        };
        store.put_revocation(&revoked).unwrap();
        store.put_revocation(&revoked).unwrap();
        assert!(store.is_revoked("profile").unwrap());
        assert_eq!(
            store.get_revocation("profile").unwrap(),
            Some(revoked.clone())
        );
        let mut changed = revoked;
        changed.reason = "different".into();
        assert_eq!(
            store.put_revocation(&changed).unwrap_err().kind,
            ObjectFileErrorKind::AlreadyExists
        );
        assert_eq!(store.get_manifest("profile").unwrap(), manifest);
        let path = store.object_path("evidence", "E1").unwrap();
        let mut envelope: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        envelope["content"]["revision_id"] = json!("tampered");
        fs::write(path, serde_json::to_vec(&envelope).unwrap()).unwrap();
        assert_eq!(
            store.get_evidence("E1").unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        assert_eq!(
            store.put_evidence(&evidence).unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        let path = store.object_path("manifests", "profile").unwrap();
        let mut envelope: serde_json::Value =
            serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        envelope["content"]["media"] = json!("tampered");
        let damaged = serde_json::to_vec(&envelope).unwrap();
        fs::write(&path, &damaged).unwrap();
        assert_eq!(
            store.put_manifest(&manifest).unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        assert_eq!(fs::read(&path).unwrap(), damaged);
        let root = root.canonicalize().unwrap();
        let cache = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../.cache")
            .canonicalize()
            .unwrap();
        assert!(root.starts_with(cache));
        assert!(
            root.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("qualification-store-")
        );
        fs::remove_dir_all(root).unwrap();
    }
}
