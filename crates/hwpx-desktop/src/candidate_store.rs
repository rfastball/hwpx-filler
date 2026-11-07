//! Durable create-once Candidate objects with reread and content-address verification.

use crate::atomic_file::write_bytes_atomic_exclusive;
use base64::{Engine, engine::general_purpose::STANDARD};
use hwpx_filler::candidate_revision::{
    CandidateObjectStore, CandidateRevisionError, ContentBlob, SourceCaptureObservation,
    TemplateRevision, blob_digest, decode_observation, decode_revision, encode_observation,
    encode_revision,
};
use hwpx_filler::execution_structure::content_digest;
use hwpx_filler::text_render::python_repr;
use serde_json::{Value, json};
use std::fmt;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObjectFileErrorKind {
    AlreadyExists,
    NotFound,
    Corrupt,
    InvalidId,
    DanglingReference,
    Io,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectFileError {
    pub kind: ObjectFileErrorKind,
    pub detail: String,
}
impl fmt::Display for ObjectFileError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.detail)
    }
}
impl std::error::Error for ObjectFileError {}
fn error(kind: ObjectFileErrorKind, detail: impl Into<String>) -> ObjectFileError {
    ObjectFileError {
        kind,
        detail: detail.into(),
    }
}
pub(crate) fn safe_id(identity: &str) -> Result<(), ObjectFileError> {
    if identity.is_empty()
        || !identity
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
    {
        return Err(error(
            ObjectFileErrorKind::InvalidId,
            format!(
                "저장할 수 없는 identity {}",
                python_repr(&Value::String(identity.into()))
            ),
        ));
    }
    Ok(())
}
#[derive(Clone, Debug)]
pub(crate) struct ObjectFileStore {
    root: PathBuf,
}
impl ObjectFileStore {
    pub(crate) fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }
    pub(crate) fn path(&self, kind: &str, id: &str) -> Result<PathBuf, ObjectFileError> {
        safe_id(id)?;
        Ok(self.root.join(kind).join(format!("{id}.json")))
    }
    pub(crate) fn exists(&self, kind: &str, id: &str) -> Result<bool, ObjectFileError> {
        Ok(self.path(kind, id)?.exists())
    }
    pub(crate) fn get(&self, kind: &str, id: &str) -> Result<Value, ObjectFileError> {
        let path = self.path(kind, id)?;
        let bytes = fs::read(&path).map_err(|e| {
            if e.kind() == std::io::ErrorKind::NotFound {
                error(ObjectFileErrorKind::NotFound, format!("{kind}/{id} 없음"))
            } else {
                error(ObjectFileErrorKind::Io, format!("{kind}/{id}: {e}"))
            }
        })?;
        let envelope: Value = serde_json::from_slice(&bytes).map_err(|e| {
            error(
                ObjectFileErrorKind::Corrupt,
                format!("{kind}/{id} JSON 손상: {e}"),
            )
        })?;
        let content = envelope
            .get("content")
            .filter(|value| value.is_object())
            .ok_or_else(|| {
                error(
                    ObjectFileErrorKind::Corrupt,
                    format!("{kind}/{id} content 손상"),
                )
            })?;
        if envelope.get("digest").and_then(Value::as_str) != Some(content_digest(content).as_str())
        {
            return Err(error(
                ObjectFileErrorKind::Corrupt,
                format!("{kind}/{id} digest 손상"),
            ));
        }
        Ok(content.clone())
    }
    pub(crate) fn put(&self, kind: &str, id: &str, content: &Value) -> Result<(), ObjectFileError> {
        if !content.is_object() {
            return Err(error(
                ObjectFileErrorKind::Corrupt,
                format!("{kind}/{id} content 는 객체여야 한다"),
            ));
        }
        let path = self.path(kind, id)?;
        if path.exists() {
            return self.require_same(kind, id, content);
        }
        let parent = path.parent().expect("object path has kind parent");
        fs::create_dir_all(parent)
            .map_err(|e| error(ObjectFileErrorKind::Io, format!("{kind}/{id}: {e}")))?;
        let envelope = json!({"digest": content_digest(content), "content":content});
        let bytes = serde_json::to_vec_pretty(&envelope)
            .map_err(|e| error(ObjectFileErrorKind::Io, e.to_string()))?;
        match write_bytes_atomic_exclusive(&path, &bytes) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                self.require_same(kind, id, content)
            }
            Err(e) => Err(error(ObjectFileErrorKind::Io, format!("{kind}/{id}: {e}"))),
        }
    }
    fn require_same(&self, kind: &str, id: &str, content: &Value) -> Result<(), ObjectFileError> {
        if self.get(kind, id)? == *content {
            Ok(())
        } else {
            Err(error(
                ObjectFileErrorKind::AlreadyExists,
                format!("{kind}/{id} 에 다른 payload 를 쓸 수 없다(create-once)"),
            ))
        }
    }
}
pub struct FileCandidateObjectStore {
    objects: ObjectFileStore,
}
impl FileCandidateObjectStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self {
            objects: ObjectFileStore::new(root),
        }
    }
    pub fn object_path(&self, kind: &str, identity: &str) -> Result<PathBuf, ObjectFileError> {
        self.objects.path(kind, identity)
    }
    fn blob_key<'a>(&self, digest: &'a str) -> &'a str {
        digest.split_once(':').map_or(digest, |(_, suffix)| suffix)
    }
    pub fn put_blob(&self, blob: &ContentBlob) -> Result<(), ObjectFileError> {
        blob.verify()
            .map_err(|e| error(ObjectFileErrorKind::Corrupt, e.0))?;
        let content = json!({
            "digest":blob.digest,
            "digest_algorithm":blob.digest_algorithm,
            "media":blob.media,
            "byte_length":blob.byte_length,
            "exact_bytes_b64":STANDARD.encode(&*blob.exact_bytes),
        });
        self.objects
            .put("blobs", self.blob_key(&blob.digest), &content)
    }
    pub fn get_blob(&self, digest: &str) -> Result<ContentBlob, ObjectFileError> {
        let content = self.objects.get("blobs", self.blob_key(digest))?;
        let stored = content["digest"].as_str().ok_or_else(|| {
            error(
                ObjectFileErrorKind::Corrupt,
                format!("blob {digest} digest 형식 불량"),
            )
        })?;
        if stored != digest {
            return Err(error(
                ObjectFileErrorKind::NotFound,
                format!("blob {digest} 없음(저장 digest {stored})"),
            ));
        }
        let encoded = content["exact_bytes_b64"].as_str().ok_or_else(|| {
            error(
                ObjectFileErrorKind::Corrupt,
                format!("blob {digest} bytes 형식 불량"),
            )
        })?;
        let bytes = STANDARD.decode(encoded).map_err(|_| {
            error(
                ObjectFileErrorKind::Corrupt,
                format!("blob {digest} base64 손상"),
            )
        })?;
        if blob_digest(&bytes) != digest {
            return Err(error(
                ObjectFileErrorKind::Corrupt,
                format!("blob {digest} bytes 가 digest 와 불일치"),
            ));
        }
        let media = content["media"].as_str().ok_or_else(|| {
            error(
                ObjectFileErrorKind::Corrupt,
                format!("blob {digest} media 형식 불량"),
            )
        })?;
        let byte_length = content["byte_length"]
            .as_u64()
            .and_then(|length| usize::try_from(length).ok())
            .ok_or_else(|| {
                error(
                    ObjectFileErrorKind::Corrupt,
                    format!("blob {digest} byte_length 형식 불량"),
                )
            })?;
        let algorithm = content["digest_algorithm"].as_str().ok_or_else(|| {
            error(
                ObjectFileErrorKind::Corrupt,
                format!("blob {digest} digest_algorithm 형식 불량"),
            )
        })?;
        ContentBlob::new(
            digest.into(),
            media.into(),
            Arc::from(bytes),
            byte_length,
            algorithm.into(),
        )
        .map_err(|e| error(ObjectFileErrorKind::Corrupt, e.0))
    }
    pub fn has_blob(&self, digest: &str) -> Result<bool, ObjectFileError> {
        let key = self.blob_key(digest);
        if !self.objects.exists("blobs", key)? {
            return Ok(false);
        }
        let content = self.objects.get("blobs", key)?;
        Ok(content["digest"].as_str() == Some(digest))
    }
    pub fn put_observation(
        &self,
        observation: &SourceCaptureObservation,
    ) -> Result<(), ObjectFileError> {
        self.objects.put(
            "observations",
            &observation.observation_id,
            &encode_observation(observation),
        )
    }
    pub fn get_observation(&self, id: &str) -> Result<SourceCaptureObservation, ObjectFileError> {
        decode_observation(&self.objects.get("observations", id)?)
            .map_err(|e| error(ObjectFileErrorKind::Corrupt, e.0))
    }
    pub fn put_revision(&self, revision: &TemplateRevision) -> Result<(), ObjectFileError> {
        if !self.has_blob(&revision.exact_content_digest)? {
            return Err(error(
                ObjectFileErrorKind::DanglingReference,
                format!(
                    "revision {} 의 blob {} 부재",
                    revision.revision_id, revision.exact_content_digest
                ),
            ));
        }
        self.get_blob(&revision.exact_content_digest)?;
        let observation = match self.get_observation(&revision.origin_capture_observation_id) {
            Ok(value) => value,
            Err(e) if e.kind == ObjectFileErrorKind::NotFound => {
                return Err(error(
                    ObjectFileErrorKind::DanglingReference,
                    format!(
                        "revision {} 의 origin observation 부재",
                        revision.revision_id
                    ),
                ));
            }
            Err(e) => return Err(e),
        };
        if observation.captured_content_digest != revision.exact_content_digest {
            return Err(error(
                ObjectFileErrorKind::DanglingReference,
                format!(
                    "revision {} 의 blob 이 origin observation 의 capture digest 와 불일치",
                    revision.revision_id
                ),
            ));
        }
        self.objects.put(
            "revisions",
            &revision.revision_id,
            &encode_revision(revision),
        )
    }
    pub fn get_revision(&self, id: &str) -> Result<TemplateRevision, ObjectFileError> {
        decode_revision(&self.objects.get("revisions", id)?)
            .map_err(|e| error(ObjectFileErrorKind::Corrupt, e.0))
    }
}
fn as_candidate_error(error: ObjectFileError) -> CandidateRevisionError {
    CandidateRevisionError(error.detail)
}
impl CandidateObjectStore for FileCandidateObjectStore {
    fn put_blob(&mut self, blob: &ContentBlob) -> Result<(), CandidateRevisionError> {
        Self::put_blob(self, blob).map_err(as_candidate_error)
    }
    fn get_blob(&self, digest: &str) -> Result<ContentBlob, CandidateRevisionError> {
        Self::get_blob(self, digest).map_err(as_candidate_error)
    }
    fn put_observation(
        &mut self,
        observation: &SourceCaptureObservation,
    ) -> Result<(), CandidateRevisionError> {
        Self::put_observation(self, observation).map_err(as_candidate_error)
    }
    fn get_observation(
        &self,
        id: &str,
    ) -> Result<SourceCaptureObservation, CandidateRevisionError> {
        Self::get_observation(self, id).map_err(as_candidate_error)
    }
    fn put_revision(&mut self, revision: &TemplateRevision) -> Result<(), CandidateRevisionError> {
        Self::put_revision(self, revision).map_err(as_candidate_error)
    }
    fn get_revision(&self, id: &str) -> Result<TemplateRevision, CandidateRevisionError> {
        Self::get_revision(self, id).map_err(as_candidate_error)
    }
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use serde_json::Map;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn create_once_rereads_blob_and_proves_revision_origin() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(format!(
            "../../.cache/candidate-store-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let store = FileCandidateObjectStore::new(&root);
        let bytes: Arc<[u8]> = Arc::from(&b"template"[..]);
        let digest = blob_digest(&bytes);
        let blob =
            ContentBlob::new(digest.clone(), "hwpx".into(), bytes, 8, "sha256".into()).unwrap();
        store.put_blob(&blob).unwrap();
        store.put_blob(&blob).unwrap();
        assert_eq!(store.get_blob(&digest).unwrap(), blob);
        assert!(!store.has_blob(&digest.replace("sha256", "sha512")).unwrap());
        let revision = TemplateRevision {
            revision_id: "R1".into(),
            template_lineage_id: "L1".into(),
            media: "hwpx".into(),
            exact_content_digest: digest.clone(),
            origin_capture_observation_id: "O1".into(),
            created_at: "t1".into(),
        };
        assert_eq!(
            store.put_revision(&revision).unwrap_err().kind,
            ObjectFileErrorKind::DanglingReference
        );
        let observation = SourceCaptureObservation {
            observation_id: "O1".into(),
            preparation_id: "P1".into(),
            source_binding_id: "S1".into(),
            source_binding_generation: 1,
            capture_method: "file-handle-stable".into(),
            observed_metadata: Map::new(),
            captured_content_digest: digest.clone(),
            captured_at: "t1".into(),
        };
        store.put_observation(&observation).unwrap();
        store.put_revision(&revision).unwrap();
        store.put_revision(&revision).unwrap();
        assert_eq!(store.get_revision("R1").unwrap(), revision);
        store
            .put_observation(&SourceCaptureObservation {
                observation_id: "O3".into(),
                ..observation.clone()
            })
            .unwrap();
        store
            .put_revision(&TemplateRevision {
                revision_id: "R2".into(),
                origin_capture_observation_id: "O3".into(),
                ..revision.clone()
            })
            .unwrap();
        assert_eq!(
            store.get_revision("R2").unwrap().exact_content_digest,
            digest
        );
        assert_eq!(fs::read_dir(root.join("blobs")).unwrap().count(), 1);
        let other_bytes: Arc<[u8]> = Arc::from(&b"other value"[..]);
        let other_digest = blob_digest(&other_bytes);
        store
            .put_blob(
                &ContentBlob::new(
                    other_digest.clone(),
                    "hwpx".into(),
                    other_bytes,
                    11,
                    "sha256".into(),
                )
                .unwrap(),
            )
            .unwrap();
        let other_observation = SourceCaptureObservation {
            observation_id: "O2".into(),
            captured_content_digest: other_digest.clone(),
            ..observation
        };
        store.put_observation(&other_observation).unwrap();
        assert_eq!(
            store
                .put_revision(&TemplateRevision {
                    origin_capture_observation_id: "O2".into(),
                    ..revision.clone()
                })
                .unwrap_err()
                .kind,
            ObjectFileErrorKind::DanglingReference
        );
        assert_eq!(
            store
                .put_revision(&TemplateRevision {
                    exact_content_digest: other_digest,
                    origin_capture_observation_id: "O2".into(),
                    ..revision.clone()
                })
                .unwrap_err()
                .kind,
            ObjectFileErrorKind::AlreadyExists
        );
        let changed = TemplateRevision {
            exact_content_digest: blob_digest(b"other"),
            ..revision
        };
        assert_eq!(
            store.put_revision(&changed).unwrap_err().kind,
            ObjectFileErrorKind::DanglingReference
        );
        let path = store
            .object_path("blobs", digest.split_once(':').unwrap().1)
            .unwrap();
        let original = fs::read(&path).unwrap();
        let mut malformed: Value = serde_json::from_slice(&original).unwrap();
        malformed["content"]["byte_length"] = json!("8");
        malformed["digest"] = json!(content_digest(&malformed["content"]));
        fs::write(&path, serde_json::to_vec(&malformed).unwrap()).unwrap();
        assert_eq!(
            store.get_blob(&digest).unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        fs::write(&path, original).unwrap();
        let mut forged: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        forged["content"]["exact_bytes_b64"] = json!(STANDARD.encode(b"forged"));
        forged["digest"] = json!(content_digest(&forged["content"]));
        fs::write(path, serde_json::to_vec(&forged).unwrap()).unwrap();
        assert_eq!(
            store.get_blob(&digest).unwrap_err().kind,
            ObjectFileErrorKind::Corrupt
        );
        assert_eq!(
            store.get_revision("../R1").unwrap_err().kind,
            ObjectFileErrorKind::InvalidId
        );
        fs::remove_dir_all(root).unwrap();
    }
}
