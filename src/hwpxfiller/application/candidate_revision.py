"""stable exact-byte capture 와 Candidate Revision (S3-02 #652).

S3 의 Candidate 는 mutable 파일 경로나 열린 package 가 아니다. 이 모듈은 Template Lineage 의
pinned source binding 에서 **하나의 안정된 exact byte sequence** 를 읽었다는 증거(StableCapture)를
그대로 immutable ContentBlob·SourceCaptureObservation·TemplateRevision 으로 발행한다.

HWPX v1 은 capture 뒤 재serialize·ZIP 정규화를 하지 않는다 — stable capture 에 성공한 exact
bytes 가 곧 Candidate Revision canonical bytes 다. 안정성을 증명하지 못하면 Candidate 를 만들지
않고 fail-closed 로 종료한다(:class:`SourceCaptureError`).

여기는 native-free 모델·port 타입·순수 orchestration·codec 이다. 실제 파일 handle/stat 을
만지는 stable-capture 어댑터는 :mod:`hwpxfiller.external.template_source_reader`, blob/observation/
revision 의 create-once 저장은 :mod:`hwpxfiller.external.candidate_store` 가 진다.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

SOURCE_CAPTURE_ERROR = "SOURCE_CAPTURE_ERROR"
SOURCE_BINDING_CHANGED = "SOURCE_BINDING_CHANGED"
MEDIA_MISMATCH = "MEDIA_MISMATCH"


class CandidateRevisionError(ValueError):
    """Candidate 모델 불변식 위반."""


def blob_digest(data: bytes) -> str:
    """exact bytes 의 sha256 content-address (Blob identity·손상 검출용)."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ─── 입력 모델(pinned source binding·lineage) ────────────────────────────────

@dataclass(frozen=True)
class MutableSourceBinding:
    source_binding_id: str
    media: str
    host_reference: str
    display_metadata: Mapping[str, Any]
    generation: int


@dataclass(frozen=True)
class TemplateLineage:
    template_lineage_id: str
    media: str
    mutable_source_binding_id: str
    source_binding_generation: int
    updated_at: str


# ─── immutable 발행 객체 ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContentBlob:
    digest: str
    media: str
    exact_bytes: bytes
    byte_length: int
    digest_algorithm: str = "sha256"

    def __post_init__(self) -> None:
        if self.digest_algorithm != "sha256":
            raise CandidateRevisionError(f"미상 digest_algorithm {self.digest_algorithm!r}")
        if self.byte_length != len(self.exact_bytes):
            raise CandidateRevisionError("byte_length 가 exact_bytes 길이와 불일치")
        if self.digest != blob_digest(self.exact_bytes):
            raise CandidateRevisionError("digest 가 exact_bytes 와 불일치")


@dataclass(frozen=True)
class SourceCaptureObservation:
    observation_id: str
    preparation_id: str
    source_binding_id: str
    source_binding_generation: int
    capture_method: str
    observed_metadata: Mapping[str, Any]
    captured_content_digest: str
    captured_at: str


@dataclass(frozen=True)
class TemplateRevision:
    revision_id: str
    template_lineage_id: str
    media: str
    exact_content_digest: str
    origin_capture_observation_id: str
    created_at: str


# ─── stable capture port ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class StableCapture:
    """안정성이 증명된 exact bytes + 그 capture 관찰치(observation_id 는 service 가 부여)."""

    exact_bytes: bytes
    captured_content_digest: str
    source_binding_id: str
    source_binding_generation: int
    capture_method: str
    observed_metadata: Mapping[str, Any]


@dataclass(frozen=True)
class SourceCaptureError:
    """capture 안정성 증명 실패 — Candidate 를 만들지 않는다."""

    reason: str


CaptureResult = StableCapture | SourceCaptureError
TemplateSourceReader = Callable[[MutableSourceBinding], CaptureResult]


class CandidateObjectStorePort(Protocol):
    """CandidateRevisionService 가 쓰는 create-once 저장 계약(external adapter 가 구현)."""

    def put_blob(self, blob: ContentBlob) -> None: ...
    def get_blob(self, digest: str) -> ContentBlob: ...
    def put_observation(self, observation: SourceCaptureObservation) -> None: ...
    def get_observation(self, observation_id: str) -> SourceCaptureObservation: ...
    def put_revision(self, revision: TemplateRevision) -> None: ...
    def get_revision(self, revision_id: str) -> TemplateRevision: ...


@dataclass(frozen=True)
class CandidateRevisionCreated:
    revision: TemplateRevision
    blob: ContentBlob
    observation: SourceCaptureObservation


CandidateRevisionResult = CandidateRevisionCreated | SourceCaptureError


def capture_candidate_revision(
    *,
    lineage: TemplateLineage,
    binding: MutableSourceBinding,
    preparation_id: str,
    reader: TemplateSourceReader,
    store: CandidateObjectStorePort,
    observation_id: str,
    revision_id: str,
    captured_at: str,
    created_at: str,
) -> CandidateRevisionResult:
    """한 prepare attempt 가 exact bytes 하나를 Candidate 로 확정하거나 fail-closed 종료한다.

    write 순서는 Blob → Observation → Revision 이고, 세 object 를 재읽기·digest 검증한 뒤에만
    성공을 반환한다. 실패하면 어떤 object 도 dangling 참조로 남기지 않는다.
    """
    if binding.media != lineage.media:
        return SourceCaptureError(MEDIA_MISMATCH)
    # lineage 는 특정 source binding 의 특정 generation 을 pin 한다 — id 만 맞고 generation 이
    # 어긋나면 repin 이므로 capture 하지 않는다(gen 7 lineage 에 gen 8 binding 거절).
    if (
        binding.source_binding_id != lineage.mutable_source_binding_id
        or binding.generation != lineage.source_binding_generation
    ):
        return SourceCaptureError(SOURCE_BINDING_CHANGED)

    result = reader(binding)
    if isinstance(result, SourceCaptureError):
        return result

    blob = ContentBlob(
        digest=result.captured_content_digest,
        media=binding.media,
        exact_bytes=result.exact_bytes,
        byte_length=len(result.exact_bytes),
    )
    observation = SourceCaptureObservation(
        observation_id=observation_id,
        preparation_id=preparation_id,
        source_binding_id=result.source_binding_id,
        source_binding_generation=result.source_binding_generation,
        capture_method=result.capture_method,
        observed_metadata=copy.deepcopy(dict(result.observed_metadata)),  # reader alias 차단
        captured_content_digest=result.captured_content_digest,
        captured_at=captured_at,
    )
    revision = TemplateRevision(
        revision_id=revision_id,
        template_lineage_id=lineage.template_lineage_id,
        media=binding.media,
        exact_content_digest=blob.digest,
        origin_capture_observation_id=observation_id,
        created_at=created_at,
    )

    store.put_blob(blob)  # digest 재사용(dedup)·create-once
    store.put_observation(observation)
    store.put_revision(revision)  # blob·observation 존재를 검증(참조 무결성)

    # 세 object 재읽기·digest 검증 — 어댑터 _get 이 봉투 digest 를 확인한다.
    store.get_blob(blob.digest)
    store.get_observation(observation_id)
    store.get_revision(revision_id)
    return CandidateRevisionCreated(revision=revision, blob=blob, observation=observation)


# ─── codec: 저장 어댑터가 쓰는 native-free dict ↔ 값 ──────────────────────────

def encode_observation(observation: SourceCaptureObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "preparation_id": observation.preparation_id,
        "source_binding_id": observation.source_binding_id,
        "source_binding_generation": observation.source_binding_generation,
        "capture_method": observation.capture_method,
        "observed_metadata": dict(observation.observed_metadata),
        "captured_content_digest": observation.captured_content_digest,
        "captured_at": observation.captured_at,
    }


def decode_observation(data: Mapping[str, Any]) -> SourceCaptureObservation:
    return SourceCaptureObservation(
        observation_id=data["observation_id"],
        preparation_id=data["preparation_id"],
        source_binding_id=data["source_binding_id"],
        source_binding_generation=data["source_binding_generation"],
        capture_method=data["capture_method"],
        observed_metadata=data["observed_metadata"],
        captured_content_digest=data["captured_content_digest"],
        captured_at=data["captured_at"],
    )


def encode_revision(revision: TemplateRevision) -> dict[str, Any]:
    return {
        "revision_id": revision.revision_id,
        "template_lineage_id": revision.template_lineage_id,
        "media": revision.media,
        "exact_content_digest": revision.exact_content_digest,
        "origin_capture_observation_id": revision.origin_capture_observation_id,
        "created_at": revision.created_at,
    }


def decode_revision(data: Mapping[str, Any]) -> TemplateRevision:
    return TemplateRevision(
        revision_id=data["revision_id"],
        template_lineage_id=data["template_lineage_id"],
        media=data["media"],
        exact_content_digest=data["exact_content_digest"],
        origin_capture_observation_id=data["origin_capture_observation_id"],
        created_at=data["created_at"],
    )
