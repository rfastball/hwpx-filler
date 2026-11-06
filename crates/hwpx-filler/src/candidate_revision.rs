//! Stable exact-byte candidate capture values and create-once store orchestration.

use crate::text_render::python_repr;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::fmt;
use std::sync::Arc;

pub const SOURCE_CAPTURE_ERROR: &str = "SOURCE_CAPTURE_ERROR";
pub const SOURCE_BINDING_CHANGED: &str = "SOURCE_BINDING_CHANGED";
pub const MEDIA_MISMATCH: &str = "MEDIA_MISMATCH";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CandidateRevisionError(pub String);
impl fmt::Display for CandidateRevisionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for CandidateRevisionError {}
fn fail(detail: impl Into<String>) -> CandidateRevisionError {
    CandidateRevisionError(detail.into())
}
pub fn blob_digest(data: &[u8]) -> String {
    let digest = Sha256::digest(data);
    format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    )
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MutableSourceBinding {
    pub source_binding_id: String,
    pub media: String,
    pub host_reference: String,
    pub display_metadata: Map<String, Value>,
    pub generation: u64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateLineage {
    pub template_lineage_id: String,
    pub media: String,
    pub mutable_source_binding_id: String,
    pub source_binding_generation: u64,
    pub updated_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContentBlob {
    pub digest: String,
    pub media: String,
    pub exact_bytes: Arc<[u8]>,
    pub byte_length: usize,
    pub digest_algorithm: String,
}
impl ContentBlob {
    pub fn new(
        digest: String,
        media: String,
        exact_bytes: Arc<[u8]>,
        byte_length: usize,
        digest_algorithm: String,
    ) -> Result<Self, CandidateRevisionError> {
        if digest_algorithm != "sha256" {
            return Err(fail(format!(
                "미상 digest_algorithm {}",
                python_repr(&Value::String(digest_algorithm))
            )));
        }
        if byte_length != exact_bytes.len() {
            return Err(fail("byte_length 가 exact_bytes 길이와 불일치"));
        }
        if digest != blob_digest(&exact_bytes) {
            return Err(fail("digest 가 exact_bytes 와 불일치"));
        }
        Ok(Self {
            digest,
            media,
            exact_bytes,
            byte_length,
            digest_algorithm,
        })
    }
    pub fn verify(&self) -> Result<(), CandidateRevisionError> {
        Self::new(
            self.digest.clone(),
            self.media.clone(),
            self.exact_bytes.clone(),
            self.byte_length,
            self.digest_algorithm.clone(),
        )
        .map(|_| ())
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceCaptureObservation {
    pub observation_id: String,
    pub preparation_id: String,
    pub source_binding_id: String,
    pub source_binding_generation: u64,
    pub capture_method: String,
    pub observed_metadata: Map<String, Value>,
    pub captured_content_digest: String,
    pub captured_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TemplateRevision {
    pub revision_id: String,
    pub template_lineage_id: String,
    pub media: String,
    pub exact_content_digest: String,
    pub origin_capture_observation_id: String,
    pub created_at: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StableCapture {
    pub exact_bytes: Arc<[u8]>,
    pub captured_content_digest: String,
    pub source_binding_id: String,
    pub source_binding_generation: u64,
    pub capture_method: String,
    pub observed_metadata: Map<String, Value>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceCaptureError {
    pub reason: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CandidateRevisionCreated {
    pub revision: TemplateRevision,
    pub blob: ContentBlob,
    pub observation: SourceCaptureObservation,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CandidateRevisionResult {
    Created(Box<CandidateRevisionCreated>),
    CaptureError(SourceCaptureError),
}

pub trait TemplateSourceReader {
    fn capture(
        &mut self,
        binding: &MutableSourceBinding,
    ) -> Result<StableCapture, SourceCaptureError>;
}
pub trait CandidateObjectStore {
    fn put_blob(&mut self, blob: &ContentBlob) -> Result<(), CandidateRevisionError>;
    fn get_blob(&self, digest: &str) -> Result<ContentBlob, CandidateRevisionError>;
    fn put_observation(
        &mut self,
        observation: &SourceCaptureObservation,
    ) -> Result<(), CandidateRevisionError>;
    fn get_observation(&self, id: &str)
    -> Result<SourceCaptureObservation, CandidateRevisionError>;
    fn put_revision(&mut self, revision: &TemplateRevision) -> Result<(), CandidateRevisionError>;
    fn get_revision(&self, id: &str) -> Result<TemplateRevision, CandidateRevisionError>;
}
pub struct CandidateCaptureRequest<'a> {
    pub lineage: &'a TemplateLineage,
    pub binding: &'a MutableSourceBinding,
    pub preparation_id: &'a str,
    pub observation_id: &'a str,
    pub revision_id: &'a str,
    pub captured_at: &'a str,
    pub created_at: &'a str,
}
/// Capture exact bytes, then write Blob → Observation → Revision and reread all three.
pub fn capture_candidate_revision(
    request: &CandidateCaptureRequest<'_>,
    reader: &mut impl TemplateSourceReader,
    store: &mut impl CandidateObjectStore,
) -> Result<CandidateRevisionResult, CandidateRevisionError> {
    let lineage = request.lineage;
    let binding = request.binding;
    if binding.media != lineage.media {
        return Ok(CandidateRevisionResult::CaptureError(SourceCaptureError {
            reason: MEDIA_MISMATCH.into(),
        }));
    }
    if binding.source_binding_id != lineage.mutable_source_binding_id
        || binding.generation != lineage.source_binding_generation
    {
        return Ok(CandidateRevisionResult::CaptureError(SourceCaptureError {
            reason: SOURCE_BINDING_CHANGED.into(),
        }));
    }
    let capture = match reader.capture(binding) {
        Ok(capture) => capture,
        Err(error) => return Ok(CandidateRevisionResult::CaptureError(error)),
    };
    let blob = ContentBlob::new(
        capture.captured_content_digest.clone(),
        binding.media.clone(),
        capture.exact_bytes.clone(),
        capture.exact_bytes.len(),
        "sha256".into(),
    )?;
    let observation = SourceCaptureObservation {
        observation_id: request.observation_id.into(),
        preparation_id: request.preparation_id.into(),
        source_binding_id: capture.source_binding_id,
        source_binding_generation: capture.source_binding_generation,
        capture_method: capture.capture_method,
        observed_metadata: capture.observed_metadata,
        captured_content_digest: capture.captured_content_digest,
        captured_at: request.captured_at.into(),
    };
    let revision = TemplateRevision {
        revision_id: request.revision_id.into(),
        template_lineage_id: lineage.template_lineage_id.clone(),
        media: binding.media.clone(),
        exact_content_digest: blob.digest.clone(),
        origin_capture_observation_id: request.observation_id.into(),
        created_at: request.created_at.into(),
    };
    store.put_blob(&blob)?;
    store.put_observation(&observation)?;
    store.put_revision(&revision)?;
    let restored_blob = store.get_blob(&blob.digest)?;
    restored_blob.verify()?;
    let restored_observation = store.get_observation(request.observation_id)?;
    let restored_revision = store.get_revision(request.revision_id)?;
    if restored_blob != blob || restored_observation != observation || restored_revision != revision
    {
        return Err(fail("candidate 재읽기 값이 생성 값과 불일치"));
    }
    Ok(CandidateRevisionResult::Created(Box::new(
        CandidateRevisionCreated {
            revision,
            blob,
            observation,
        },
    )))
}

pub fn encode_observation(observation: &SourceCaptureObservation) -> Value {
    serde_json::json!({
        "observation_id":observation.observation_id,"preparation_id":observation.preparation_id,
        "source_binding_id":observation.source_binding_id,"source_binding_generation":observation.source_binding_generation,
        "capture_method":observation.capture_method,"observed_metadata":observation.observed_metadata,
        "captured_content_digest":observation.captured_content_digest,"captured_at":observation.captured_at,
    })
}
fn field<'a>(data: &'a Map<String, Value>, key: &str) -> Result<&'a Value, CandidateRevisionError> {
    data.get(key).ok_or_else(|| fail(format!("{key} 누락")))
}
fn string(data: &Map<String, Value>, key: &str) -> Result<String, CandidateRevisionError> {
    field(data, key)?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| fail(format!("{key} 는 문자열이어야 한다")))
}
fn unsigned(data: &Map<String, Value>, key: &str) -> Result<u64, CandidateRevisionError> {
    let value = field(data, key)?;
    if value.is_boolean() {
        return Err(fail(format!("{key} 는 정수여야 한다")));
    }
    value
        .as_u64()
        .ok_or_else(|| fail(format!("{key} 는 정수여야 한다")))
}
pub fn decode_observation(
    value: &Value,
) -> Result<SourceCaptureObservation, CandidateRevisionError> {
    let data = value
        .as_object()
        .ok_or_else(|| fail("observation 표현이 사전이 아니다"))?;
    Ok(SourceCaptureObservation {
        observation_id: string(data, "observation_id")?,
        preparation_id: string(data, "preparation_id")?,
        source_binding_id: string(data, "source_binding_id")?,
        source_binding_generation: unsigned(data, "source_binding_generation")?,
        capture_method: string(data, "capture_method")?,
        observed_metadata: field(data, "observed_metadata")?
            .as_object()
            .cloned()
            .ok_or_else(|| fail("observed_metadata 는 사전이어야 한다"))?,
        captured_content_digest: string(data, "captured_content_digest")?,
        captured_at: string(data, "captured_at")?,
    })
}
pub fn encode_revision(revision: &TemplateRevision) -> Value {
    serde_json::json!({"revision_id":revision.revision_id,"template_lineage_id":revision.template_lineage_id,"media":revision.media,"exact_content_digest":revision.exact_content_digest,"origin_capture_observation_id":revision.origin_capture_observation_id,"created_at":revision.created_at})
}
pub fn decode_revision(value: &Value) -> Result<TemplateRevision, CandidateRevisionError> {
    let data = value
        .as_object()
        .ok_or_else(|| fail("revision 표현이 사전이 아니다"))?;
    Ok(TemplateRevision {
        revision_id: string(data, "revision_id")?,
        template_lineage_id: string(data, "template_lineage_id")?,
        media: string(data, "media")?,
        exact_content_digest: string(data, "exact_content_digest")?,
        origin_capture_observation_id: string(data, "origin_capture_observation_id")?,
        created_at: string(data, "created_at")?,
    })
}

#[cfg(test)]
#[cfg_attr(coverage_nightly, coverage(off))]
mod tests {
    use super::*;
    use std::collections::HashMap;
    #[derive(Default)]
    struct MemoryStore {
        blobs: HashMap<String, ContentBlob>,
        observations: HashMap<String, SourceCaptureObservation>,
        revisions: HashMap<String, TemplateRevision>,
    }
    impl CandidateObjectStore for MemoryStore {
        fn put_blob(&mut self, blob: &ContentBlob) -> Result<(), CandidateRevisionError> {
            self.blobs.insert(blob.digest.clone(), blob.clone());
            Ok(())
        }
        fn get_blob(&self, digest: &str) -> Result<ContentBlob, CandidateRevisionError> {
            self.blobs
                .get(digest)
                .cloned()
                .ok_or_else(|| fail("blob missing"))
        }
        fn put_observation(
            &mut self,
            item: &SourceCaptureObservation,
        ) -> Result<(), CandidateRevisionError> {
            self.observations
                .insert(item.observation_id.clone(), item.clone());
            Ok(())
        }
        fn get_observation(
            &self,
            id: &str,
        ) -> Result<SourceCaptureObservation, CandidateRevisionError> {
            self.observations
                .get(id)
                .cloned()
                .ok_or_else(|| fail("observation missing"))
        }
        fn put_revision(&mut self, item: &TemplateRevision) -> Result<(), CandidateRevisionError> {
            self.revisions
                .insert(item.revision_id.clone(), item.clone());
            Ok(())
        }
        fn get_revision(&self, id: &str) -> Result<TemplateRevision, CandidateRevisionError> {
            self.revisions
                .get(id)
                .cloned()
                .ok_or_else(|| fail("revision missing"))
        }
    }
    struct Reader {
        calls: usize,
        fail_capture: bool,
    }
    impl TemplateSourceReader for Reader {
        fn capture(
            &mut self,
            binding: &MutableSourceBinding,
        ) -> Result<StableCapture, SourceCaptureError> {
            self.calls += 1;
            if self.fail_capture {
                return Err(SourceCaptureError {
                    reason: SOURCE_CAPTURE_ERROR.into(),
                });
            }
            let bytes: Arc<[u8]> = Arc::from(&b"exact bytes"[..]);
            Ok(StableCapture {
                captured_content_digest: blob_digest(&bytes),
                exact_bytes: bytes,
                source_binding_id: binding.source_binding_id.clone(),
                source_binding_generation: binding.generation,
                capture_method: "stable-handle".into(),
                observed_metadata: Map::new(),
            })
        }
    }
    #[test]
    fn pinned_binding_fences_capture_and_created_objects_reread() {
        let lineage = TemplateLineage {
            template_lineage_id: "line".into(),
            media: "hwpx".into(),
            mutable_source_binding_id: "source".into(),
            source_binding_generation: 2,
            updated_at: "t".into(),
        };
        let binding = MutableSourceBinding {
            source_binding_id: "source".into(),
            media: "hwpx".into(),
            host_reference: "path".into(),
            display_metadata: Map::new(),
            generation: 1,
        };
        let mut reader = Reader {
            calls: 0,
            fail_capture: false,
        };
        let mut store = MemoryStore::default();
        let request = CandidateCaptureRequest {
            lineage: &lineage,
            binding: &binding,
            preparation_id: "prep",
            observation_id: "obs",
            revision_id: "rev",
            captured_at: "t",
            created_at: "t",
        };
        let wrong_media = MutableSourceBinding {
            media: "txt".into(),
            ..binding.clone()
        };
        assert_eq!(
            capture_candidate_revision(
                &CandidateCaptureRequest {
                    binding: &wrong_media,
                    ..request
                },
                &mut reader,
                &mut store,
            )
            .unwrap(),
            CandidateRevisionResult::CaptureError(SourceCaptureError {
                reason: MEDIA_MISMATCH.into()
            })
        );
        assert_eq!(
            capture_candidate_revision(&request, &mut reader, &mut store).unwrap(),
            CandidateRevisionResult::CaptureError(SourceCaptureError {
                reason: SOURCE_BINDING_CHANGED.into()
            })
        );
        assert_eq!(reader.calls, 0);
        assert!(store.blobs.is_empty());
        let exact_bytes: Arc<[u8]> = Arc::from(&b"exact bytes"[..]);
        assert!(
            ContentBlob::new(
                "sha256:wrong".into(),
                "hwpx".into(),
                exact_bytes.clone(),
                11,
                "sha256".into()
            )
            .is_err()
        );
        assert!(
            ContentBlob::new(
                blob_digest(&exact_bytes),
                "hwpx".into(),
                exact_bytes,
                1,
                "sha256".into()
            )
            .is_err()
        );
        let mut current = binding.clone();
        current.generation = 2;
        let request = CandidateCaptureRequest {
            binding: &current,
            ..request
        };
        reader.fail_capture = true;
        assert_eq!(
            capture_candidate_revision(&request, &mut reader, &mut store).unwrap(),
            CandidateRevisionResult::CaptureError(SourceCaptureError {
                reason: SOURCE_CAPTURE_ERROR.into()
            })
        );
        assert!(store.blobs.is_empty());
        assert!(store.revisions.is_empty());
        reader.fail_capture = false;
        let CandidateRevisionResult::Created(created) =
            capture_candidate_revision(&request, &mut reader, &mut store).unwrap()
        else {
            panic!("expected created")
        };
        assert_eq!(reader.calls, 2);
        assert_eq!(created.blob.exact_bytes.as_ref(), b"exact bytes");
        assert_eq!(
            decode_revision(&encode_revision(&created.revision)).unwrap(),
            created.revision
        );
        assert_eq!(
            decode_observation(&encode_observation(&created.observation)).unwrap(),
            created.observation
        );
    }
}
