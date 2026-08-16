"""Profile admission aggregate 의 file-atomic·CAS 저장 경계 (S5-08 · #704).

Profile 별 ``<profile_id>.json`` 에 admission aggregate 를 둔다. 갱신은 writer lease 아래
load→decode→검증→expected aggregate_version CAS→새 frozen aggregate→같은 디렉터리 temp write→
atomic replace 로 **한 번** commit 한다(:mod:`.atomic`). 어느 단계 실패도 기존 파일을 무손상으로
남긴다. Manifest 는 이 store 가 건드리지 않는다.

durability 주장 범위·비범위는 :mod:`.work_configuration_store` 와 같다: fsync·power-loss·
cross-process writer exclusion 은 v1 desktop 전제 밖(#620).
"""

from __future__ import annotations

import json
import re
import threading
import weakref
from pathlib import Path

from hwpxfiller.application.qualification_evidence import content_digest
from hwpxfiller.application.stored_profile_admission import (
    STORE_SCHEMA_VERSION,
    StoredProfileAdmission,
    StoredProfileAdmissionError,
    decode_stored,
    encode_stored,
)

from .atomic import write_text_atomic

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")


class ProfileAdmissionStoreError(Exception):
    """admission 저장 경계의 loud failure 기반."""

    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


class AdmissionAggregateNotFound(ProfileAdmissionStoreError):
    """참조한 Profile admission aggregate 파일이 없다."""

    code = "QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING"


class AdmissionAggregateExists(ProfileAdmissionStoreError):
    """이미 있는 admission aggregate 를 다시 create 하려 함(create-once)."""

    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


class AdmissionAggregateConflict(ProfileAdmissionStoreError):
    """expected aggregate_version 이 현재와 불일치(CAS 실패)."""

    code = "STORE_CONCURRENT_MODIFICATION"


class AdmissionIntegrityError(ProfileAdmissionStoreError):
    """envelope digest 손상·chain 불변식 위반 — partial 을 current 로 승격하지 않는다."""

    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


class AdmissionSchemaUnsupported(ProfileAdmissionStoreError):
    """저장 파일의 schema 가 이 런타임이 아는 정본이 아니다."""

    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ProfileAdmissionStoreError(f"저장할 수 없는 profile_id {value!r}")
    return value


# ponytail: in-process RLock — cross-process 원자성은 v1 desktop 전제 밖(#620).
_LOCKS: "weakref.WeakValueDictionary[str, threading.RLock]" = weakref.WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()


def _lock(key: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


class ProfileAdmissionStore:
    """Profile 별 admission aggregate 의 create-once·file-atomic·CAS 저장소."""

    def __init__(self, root: "str | Path") -> None:
        # resolve: per-root writer lease 가 경로 alias 로 갈라지지 않도록 정규화한다.
        self._root = Path(root).resolve()

    def _path(self, profile_id: str) -> Path:
        return self._root / f"{_require_id(profile_id)}.json"

    def _lock_key(self, profile_id: str) -> str:
        return f"{self._root}\x00{profile_id}"

    def exists(self, profile_id: str) -> bool:
        return self._path(profile_id).exists()

    def _read_content(self, profile_id: str) -> dict:
        path = self._path(profile_id)
        try:
            envelope = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise AdmissionIntegrityError(f"{path.name} JSON 파싱 실패(손상)") from exc
        if not isinstance(envelope, dict):
            raise AdmissionIntegrityError(f"{path.name} envelope 형식 손상")
        content = envelope.get("content")
        if envelope.get("digest") != content_digest(content):
            raise AdmissionIntegrityError(f"{path.name} digest 손상")
        if not isinstance(content, dict):
            raise AdmissionIntegrityError(f"{path.name} content 형식 손상")
        return content

    def load(self, profile_id: str) -> StoredProfileAdmission:
        path = self._path(profile_id)
        if not path.exists():
            raise AdmissionAggregateNotFound(f"profile {profile_id} admission aggregate 없음")
        content = self._read_content(profile_id)
        if content.get("schema_version") != STORE_SCHEMA_VERSION:
            raise AdmissionSchemaUnsupported(
                f"profile {profile_id} admission schema 미상: {content.get('schema_version')!r}"
            )
        try:
            stored = decode_stored(content)
        except StoredProfileAdmissionError as exc:
            # digest 유효해도 chain·ledger 가 malformed 이면 store 계약 오류로 정규화한다.
            raise AdmissionIntegrityError(
                f"profile {profile_id} admission aggregate 불변식 위반"
            ) from exc
        if stored.qualification_profile_id != profile_id:
            # 파일이 잘못된 이름으로 복사·이동되면 digest 통과해도 key 결속이 깨진다.
            raise AdmissionIntegrityError(
                f"profile {profile_id} 파일이 다른 Profile({stored.qualification_profile_id}) "
                "aggregate 를 담았다"
            )
        return stored

    def load_summary(self, profile_id: str) -> StoredProfileAdmission | None:
        """outside-fence optimistic discovery read — 없으면 None(authoritative 는 under-fence).

        손상은 여기서도 fail-closed(조용한 최신 검색 없음). discovery 라 fence 를 잡지 않는다.
        """
        if not self._path(profile_id).exists():
            return None
        return self.load(profile_id)

    def create(self, stored: StoredProfileAdmission) -> None:
        """새 admission aggregate 를 최초 commit 한다(create-once, version 1)."""
        if stored.aggregate_version != 1:
            raise ProfileAdmissionStoreError(
                f"최초 aggregate commit 은 version 1 이어야 한다: {stored.aggregate_version}"
            )
        profile_id = _require_id(stored.qualification_profile_id)
        path = self._path(profile_id)
        with _lock(self._lock_key(profile_id)):
            if path.exists():
                raise AdmissionAggregateExists(
                    f"profile {profile_id} admission aggregate 이미 존재"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            content = encode_stored(stored)
            envelope = {"digest": content_digest(content), "content": content}
            write_text_atomic(path, json.dumps(envelope, ensure_ascii=False, indent=2))

    def commit(
        self,
        profile_id: str,
        expected_aggregate_version: int,
        new_stored: StoredProfileAdmission,
    ) -> None:
        """writer lease 아래 CAS→atomic commit. expected version 불일치면 CONCURRENT_MODIFICATION."""
        profile_id = _require_id(profile_id)
        with _lock(self._lock_key(profile_id)):
            current = self.load(profile_id)
            if current.aggregate_version != expected_aggregate_version:
                raise AdmissionAggregateConflict(
                    f"profile {profile_id} CAS 실패: expected {expected_aggregate_version}, "
                    f"current {current.aggregate_version}"
                )
            if new_stored.qualification_profile_id != profile_id:
                raise ProfileAdmissionStoreError("commit 안에서 다른 Profile 로 바꿀 수 없다")
            if new_stored.aggregate_version != current.aggregate_version + 1:
                raise ProfileAdmissionStoreError(
                    "commit 은 aggregate_version 을 정확히 1 올려야 한다"
                )
            if new_stored.bound_manifest_digest != current.bound_manifest_digest:
                raise ProfileAdmissionStoreError("commit 은 bound manifest 를 바꿀 수 없다")
            if current.decisions != new_stored.decisions[: len(current.decisions)]:
                # decision chain 은 immutable — 기존 마디를 지우거나 바꾸면 history 위조다.
                raise ProfileAdmissionStoreError("decision chain 은 append-only 다(기존 마디 보존)")
            prior = current.processed_requests
            if new_stored.processed_requests[: len(prior)] != prior:
                raise ProfileAdmissionStoreError(
                    "first-seen ledger 는 append-only 다(기존 기록 보존)"
                )
            content = encode_stored(new_stored)
            envelope = {"digest": content_digest(content), "content": content}
            write_text_atomic(self._path(profile_id), json.dumps(envelope, ensure_ascii=False, indent=2))
