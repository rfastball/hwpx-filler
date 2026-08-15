"""ContentBlob·SourceCaptureObservation·TemplateRevision 의 create-once 파일 저장 (S3-02 #652).

전역 immutable object 를 파일로 durable write 하고, Work aggregate 가 참조하기 전에 재읽기·
digest 확인을 강제한다. Blob 은 content-address(digest) 로 dedup 되고, Revision 은 자기 Blob 과
origin Observation 이 실재할 때만 저장된다(참조 무결성 — dangling Candidate 금지).

봉투 ``{"digest","content"}`` create-once 기계는 :mod:`~hwpxfiller.external.qualification_store`
와 형태가 같지만, S3-01·S3-02 는 병렬 슬라이스라 서로를 import 하지 않는다(단독 revert
가능성 — 불변식 20). 통합 refactor 는 후속 슬라이스가 셋째 소비자와 함께 연다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from hwpxfiller.application.candidate_revision import (
    ContentBlob,
    SourceCaptureObservation,
    TemplateRevision,
    blob_digest,
    decode_observation,
    decode_revision,
    encode_observation,
    encode_revision,
)
from .atomic import write_text_atomic

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")


class CandidateStoreError(Exception):
    """Candidate object 저장 경계의 loud failure 기반."""


class ObjectAlreadyExists(CandidateStoreError):
    """같은 identity 에 다른 payload 를 쓰려 함(create-once 위반)."""


class ObjectNotFound(CandidateStoreError):
    """참조한 immutable object 가 없음 — 최신 검색으로 보완하지 않는다."""


class ObjectCorrupt(CandidateStoreError):
    """저장 digest 와 재해시가 불일치 — 저장 이후 손상."""


class InvalidObjectId(CandidateStoreError):
    """identity 에 파일명·경로로 쓸 수 없는 문자가 있음."""


class DanglingReference(CandidateStoreError):
    """Revision 이 존재하지 않는 Blob·Observation 을 가리킴."""


def _object_digest(content: dict) -> str:
    canonical = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise InvalidObjectId(f"저장할 수 없는 identity {value!r}")
    return value


class CandidateObjectStore:
    """Blob·Observation·Revision 의 create-once 파일 저장소."""

    def __init__(self, root: "str | Path") -> None:
        self._root = Path(root)

    # ── 봉투 IO ───────────────────────────────────────────────────────────
    def _path(self, kind: str, identity: str) -> Path:
        return self._root / kind / f"{_require_id(identity)}.json"

    def _put(self, kind: str, identity: str, content: dict) -> None:
        path = self._path(kind, identity)
        if path.exists():
            existing = json.loads(path.read_text("utf-8")).get("content")
            if existing != content:
                raise ObjectAlreadyExists(
                    f"{kind}/{identity} 에 다른 payload 를 쓸 수 없다(create-once)"
                )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"digest": _object_digest(content), "content": content}
        write_text_atomic(path, json.dumps(envelope, ensure_ascii=False, indent=2))

    def _get(self, kind: str, identity: str) -> dict:
        path = self._path(kind, identity)
        if not path.exists():
            raise ObjectNotFound(f"{kind}/{identity} 없음")
        envelope = json.loads(path.read_text("utf-8"))
        content = envelope.get("content")
        if envelope.get("digest") != _object_digest(content):
            raise ObjectCorrupt(f"{kind}/{identity} digest 손상")
        return content

    def _exists(self, kind: str, identity: str) -> bool:
        return self._path(kind, identity).exists()

    # ── Blob (content-address dedup) ──────────────────────────────────────
    @staticmethod
    def _blob_key(digest: str) -> str:
        return digest.split(":", 1)[-1]

    def put_blob(self, blob: ContentBlob) -> None:
        content = {
            "digest": blob.digest,
            "digest_algorithm": blob.digest_algorithm,
            "media": blob.media,
            "byte_length": blob.byte_length,
            "exact_bytes_b64": base64.b64encode(blob.exact_bytes).decode("ascii"),
        }
        self._put("blobs", self._blob_key(blob.digest), content)

    def get_blob(self, digest: str) -> ContentBlob:
        content = self._get("blobs", self._blob_key(digest))
        # _blob_key 는 알고리즘 접두를 버리므로 저장된 full digest 가 요청과 같은지 확인한다 —
        # 안 그러면 sha512:<같은hex> 요청이 sha256 blob 으로 조용히 해석된다.
        if content["digest"] != digest:
            raise ObjectNotFound(f"blob {digest} 없음(저장 digest {content['digest']})")
        exact_bytes = base64.b64decode(content["exact_bytes_b64"])
        if blob_digest(exact_bytes) != content["digest"]:
            raise ObjectCorrupt(f"blob {digest} bytes 가 digest 와 불일치")
        return ContentBlob(
            digest=content["digest"],
            media=content["media"],
            exact_bytes=exact_bytes,
            byte_length=content["byte_length"],
            digest_algorithm=content["digest_algorithm"],
        )

    def has_blob(self, digest: str) -> bool:
        if not self._exists("blobs", self._blob_key(digest)):
            return False
        return self._get("blobs", self._blob_key(digest))["digest"] == digest

    # ── Observation ───────────────────────────────────────────────────────
    def put_observation(self, observation: SourceCaptureObservation) -> None:
        self._put(
            "observations", observation.observation_id, encode_observation(observation)
        )

    def get_observation(self, observation_id: str) -> SourceCaptureObservation:
        return decode_observation(self._get("observations", observation_id))

    # ── Revision (참조 무결성) ─────────────────────────────────────────────
    def put_revision(self, revision: TemplateRevision) -> None:
        if not self.has_blob(revision.exact_content_digest):
            raise DanglingReference(
                f"revision {revision.revision_id} 의 blob {revision.exact_content_digest} 부재"
            )
        if not self._exists("observations", revision.origin_capture_observation_id):
            raise DanglingReference(
                f"revision {revision.revision_id} 의 origin observation 부재"
            )
        # origin observation 이 실제로 이 bytes 를 capture 했음을 증명해야 한다 — 존재만으로는
        # 다른 blob 을 가리키는 내부 불일치 provenance 를 막지 못한다.
        observation = self.get_observation(revision.origin_capture_observation_id)
        if observation.captured_content_digest != revision.exact_content_digest:
            raise DanglingReference(
                f"revision {revision.revision_id} 의 blob 이 origin observation 의 "
                f"capture digest 와 불일치"
            )
        self._put("revisions", revision.revision_id, encode_revision(revision))

    def get_revision(self, revision_id: str) -> TemplateRevision:
        return decode_revision(self._get("revisions", revision_id))
