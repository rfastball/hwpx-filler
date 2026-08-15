"""Qualification 영속 객체의 file-atomic create-once 저장 경계 (S3-01 #651).

전역 immutable object 를 파일로 durable write 한다 — Work aggregate(S3-03)가 이를 참조하기
전에 반드시 재읽기·digest 확인을 통과해야 한다. 규율:

- object 파일은 **create-once**: 같은 identity 에 다른 payload 를 쓰면 loud failure,
  같은 payload 재저장은 idempotent(확인-또는-경보 — 조용한 덮어쓰기 금지).
- 저장은 봉투 ``{"digest", "content"}`` 로 감싸고, 읽을 때 content 를 재해시해 봉투 digest 와
  대조한다 — 손상은 최신 검색으로 보완하지 않고 시끄럽게 올린다.
- identity 는 파일명이 되므로 경로 문자를 거절한다(traversal 차단).

위치-불가지다 — 생성자가 루트 디렉터리를 받는다(테스트는 tmp, 앱은 홈 아래). 판정·모델·
코덱은 :mod:`hwpxfiller.application.qualification_evidence` 가 소유하고, 여기는 그 값을
디스크와 오가게 하는 어댑터다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hwpxfiller.application.qualification_evidence import (
    QualificationAttempt,
    QualificationEvidence,
    QualificationProfileManifest,
    QualificationProfileRevocation,
    content_digest,
    decode_attempt,
    decode_evidence,
    decode_manifest,
    decode_revocation,
    encode_attempt,
    encode_evidence,
    encode_manifest,
    encode_revocation,
    validate_evidence_binding,
)
from .atomic import write_text_atomic

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")


class QualificationStoreError(Exception):
    """Qualification object 저장 경계의 loud failure 기반."""


class ObjectAlreadyExists(QualificationStoreError):
    """같은 identity 에 다른 payload 를 쓰려 함(create-once 위반)."""


class ObjectNotFound(QualificationStoreError):
    """참조한 immutable object 가 없음 — 최신 검색으로 보완하지 않는다."""


class ObjectCorrupt(QualificationStoreError):
    """봉투 digest 와 content 재해시가 불일치 — 저장 이후 손상."""


class InvalidObjectId(QualificationStoreError):
    """identity 에 파일명·경로로 쓸 수 없는 문자가 있음."""


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise InvalidObjectId(f"저장할 수 없는 identity {value!r}")
    return value


class QualificationObjectStore:
    """Profile Manifest·Revocation·Attempt·Evidence 의 create-once 파일 저장소."""

    def __init__(self, root: "str | Path") -> None:
        self._root = Path(root)

    # ── 봉투 IO ───────────────────────────────────────────────────────────
    def _path(self, kind: str, identity: str) -> Path:
        return self._root / kind / f"{_require_id(identity)}.json"

    def _put(self, kind: str, identity: str, content: dict) -> None:
        path = self._path(kind, identity)
        if path.exists():
            existing = self._get(kind, identity)  # 봉투 digest 검증을 지나 손상도 loud
            if existing != content:
                raise ObjectAlreadyExists(
                    f"{kind}/{identity} 에 다른 payload 를 쓸 수 없다(create-once)"
                )
            return  # 같은 payload 재저장 — idempotent
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"digest": content_digest(content), "content": content}
        write_text_atomic(path, json.dumps(envelope, ensure_ascii=False, indent=2))

    def _get(self, kind: str, identity: str) -> dict:
        path = self._path(kind, identity)
        if not path.exists():
            raise ObjectNotFound(f"{kind}/{identity} 없음")
        envelope = json.loads(path.read_text("utf-8"))
        content = envelope.get("content")
        if envelope.get("digest") != content_digest(content):
            raise ObjectCorrupt(f"{kind}/{identity} digest 손상")
        return content

    def _exists(self, kind: str, identity: str) -> bool:
        return self._path(kind, identity).exists()

    # ── Manifest ─────────────────────────────────────────────────────────
    def put_manifest(self, manifest: QualificationProfileManifest) -> None:
        self._put(
            "manifests", manifest.qualification_profile_id, encode_manifest(manifest)
        )

    def get_manifest(self, qualification_profile_id: str) -> QualificationProfileManifest:
        return decode_manifest(self._get("manifests", qualification_profile_id))

    # ── Revocation ───────────────────────────────────────────────────────
    def put_revocation(self, revocation: QualificationProfileRevocation) -> None:
        self._put(
            "revocations",
            revocation.qualification_profile_id,
            encode_revocation(revocation),
        )

    def get_revocation(
        self, qualification_profile_id: str
    ) -> QualificationProfileRevocation | None:
        if not self._exists("revocations", qualification_profile_id):
            return None
        return decode_revocation(self._get("revocations", qualification_profile_id))

    def is_revoked(self, qualification_profile_id: str) -> bool:
        return self._exists("revocations", qualification_profile_id)

    # ── Attempt ──────────────────────────────────────────────────────────
    def put_attempt(self, attempt: QualificationAttempt) -> None:
        # evidence_id 도 파일명이 되므로 attempt 를 영속하기 전에 저장 가능성을 확인한다 —
        # 안 그러면 put_evidence 가 거절할 id 를 단 attempt 가 dangling 으로 남는다.
        if attempt.evidence_id is not None:
            _require_id(attempt.evidence_id)
        self._put("attempts", attempt.attempt_id, encode_attempt(attempt))

    def get_attempt(self, attempt_id: str) -> QualificationAttempt:
        return decode_attempt(self._get("attempts", attempt_id))

    # ── Evidence ─────────────────────────────────────────────────────────
    def put_evidence(self, evidence: QualificationEvidence) -> None:
        """Evidence 는 자기 Attempt 의 exact binding 을 통과해야만 저장된다."""
        attempt = self.get_attempt(evidence.attempt_id)
        validate_evidence_binding(attempt, evidence)
        self._put("evidence", evidence.evidence_id, encode_evidence(evidence))

    def get_evidence(self, evidence_id: str) -> QualificationEvidence:
        return decode_evidence(self._get("evidence", evidence_id))
