"""S4 Configuration 의 file-atomic 저장 + durable Workspace identity provider (S4-03 #673).

S3 상태와 **분리된** Work별 ``<work_id>.json`` 에 S4 aggregate 를 둔다(잦은 selection mutation
이라 Template Application history 와 파일을 합치지 않는다). 갱신은 writer lease 아래
load→decode→검증→expected aggregate_version CAS→새 frozen aggregate 완성→같은 디렉터리 temp
write→atomic replace 로 **한 번** commit 한다(:mod:`.atomic`). 어느 단계 실패도 기존 파일을
무손상으로 남긴다.

Workspace identity 는 create-once 로 영속되는 ``WorkspaceInstanceId`` 다 — process session·경로
문자열이 아니라, S3·S4 fence 와 S4 token 이 같은 값을 소비한다. read 마다 새 ID 를 만들지 않고,
없는 기존 설치에는 명시적 create-once initialization 을 한다.

durability 주장 범위: temp 완성 전 기존 파일 유지·atomic replace 실패 시 기존 파일 유지·crash
뒤 old/new 완성 파일만 관찰·envelope digest 검증. **주장하지 않음**: fsync·directory fsync·
power-loss commit durability·cross-process writer exclusion(단일 프로세스 desktop 전제 #620).

값·불변식·코덱은 :mod:`hwpxfiller.application.stored_work_configuration` 소유. fingerprint 계산은
#677, Select/Clear command·fence 는 #675/#677 이 이 store 위에 얹는다.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
import weakref
from collections.abc import Callable
from pathlib import Path

from hwpxfiller.application.qualification_evidence import content_digest
from hwpxfiller.application.stored_work_configuration import (
    STORE_SCHEMA_VERSION,
    StoredConfigurationError,
    StoredWorkConfiguration,
    decode_stored,
    encode_stored,
)

from .atomic import write_text_atomic

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")

_WORKSPACE_SCHEMA_VERSION = "workspace-metadata-v1"
_METADATA_FILENAME = "workspace.json"


class WorkConfigurationStoreError(Exception):
    """S4 Configuration 저장 경계의 loud failure 기반(CONFIGURATION_PERSISTENCE_ERROR)."""


class WorkspaceIdentityIntegrityError(WorkConfigurationStoreError):
    """workspace metadata 가 손상·부정합 — 조용히 새 ID 로 넘어가지 않는다."""


class ConfigurationAggregateNotFound(WorkConfigurationStoreError):
    """참조한 Work S4 aggregate 파일이 없다."""


class ConfigurationAggregateExists(WorkConfigurationStoreError):
    """이미 있는 Work S4 aggregate 를 다시 create 하려 함(create-once)."""


class ConfigurationAggregateConflict(WorkConfigurationStoreError):
    """expected aggregate_version 이 현재와 불일치(CAS 실패)."""


class ConfigurationIntegrityError(WorkConfigurationStoreError):
    """envelope digest 손상·JSON 파싱 실패 — partial 을 current 로 승격하지 않는다."""


class ConfigurationSchemaUnsupported(WorkConfigurationStoreError):
    """저장 파일의 schema 가 이 런타임이 아는 정본이 아니다."""


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise WorkConfigurationStoreError(f"저장할 수 없는 work_id {value!r}")
    return value


# 프로세스 안 (root, key) 별 writer lease. 지원 topology 는 작업 디렉터리당 writer 프로세스
# 하나(#192)라 in-process 직렬화로 충분하다.
# ponytail: in-process RLock — cross-process 원자성은 v1 desktop 전제 밖(#673), 필요 시 #620 상향.
_LOCKS: "weakref.WeakValueDictionary[str, threading.RLock]" = (
    weakref.WeakValueDictionary()
)
_LOCKS_GUARD = threading.Lock()


def _lock(key: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _write_enveloped(path: Path, content: dict) -> None:
    envelope = {"digest": content_digest(content), "content": content}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(envelope, ensure_ascii=False, indent=2))


def _read_enveloped(path: Path, on_corrupt: type[WorkConfigurationStoreError]) -> dict:
    try:
        envelope = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise on_corrupt(f"{path.name} JSON 파싱 실패(손상)") from exc
    if not isinstance(envelope, dict):
        raise on_corrupt(f"{path.name} envelope 형식 손상")
    content = envelope.get("content")
    if envelope.get("digest") != content_digest(content):
        raise on_corrupt(f"{path.name} digest 손상")
    if not isinstance(content, dict):
        raise on_corrupt(f"{path.name} content 형식 손상")
    return content


class WorkspaceMetadataStore:
    """durable ``WorkspaceInstanceId`` provider — create-once, read 마다 새로 만들지 않는다."""

    def __init__(self, root: "str | Path") -> None:
        # resolve: 상대/절대·심볼릭·Windows 대소문자 alias 가 같은 lock key 를 얻게 한다.
        self._root = Path(root).resolve()

    @property
    def _path(self) -> Path:
        return self._root / _METADATA_FILENAME

    def read(self) -> "str | None":
        """현재 workspace_instance_id 또는 없으면 None. 손상은 fail-closed."""
        if not self._path.exists():
            return None
        content = _read_enveloped(self._path, WorkspaceIdentityIntegrityError)
        if content.get("schema_version") != _WORKSPACE_SCHEMA_VERSION:
            raise WorkspaceIdentityIntegrityError("workspace metadata schema 미상")
        instance_id = content.get("workspace_instance_id")
        if not isinstance(instance_id, str) or instance_id == "":
            raise WorkspaceIdentityIntegrityError("workspace_instance_id 부재·형식 손상")
        return instance_id

    def get_or_create(
        self,
        now: str,
        mint: "Callable[[], str] | None" = None,
    ) -> str:
        """최초 1회 create-once 로 ID 를 심고, 이후엔 그대로 돌려준다(restart 동일).

        경로 문자열·process ID 에서 파생하지 않는다 — mint(기본 uuid4)로 새로 뽑아 영속한다.
        lease 안에서 read-first 라, 이미 있으면 mint 를 부르지도 쓰지도 않는다(overwrite 없음).
        """
        with _lock(f"{self._root}\x00__workspace__"):
            existing = self.read()
            if existing is not None:
                return existing
            instance_id = (mint or (lambda: uuid.uuid4().hex))()
            _require_nonempty_id(instance_id)
            _write_enveloped(
                self._path,
                {
                    "schema_version": _WORKSPACE_SCHEMA_VERSION,
                    "workspace_instance_id": instance_id,
                    "created_at": now,
                },
            )
            return instance_id


def _require_nonempty_id(value: str) -> None:
    if not isinstance(value, str) or value == "":
        raise WorkspaceIdentityIntegrityError("minted workspace_instance_id 가 비었다")


class WorkSlotConfigurationStore:
    """Work별 S4 aggregate 의 create-once·file-atomic·CAS 저장소."""

    def __init__(self, root: "str | Path") -> None:
        # resolve: per-root writer lease 가 경로 alias 로 갈라지지 않도록 정규화한다.
        self._root = Path(root).resolve()

    def _path(self, work_id: str) -> Path:
        return self._root / f"{_require_id(work_id)}.json"

    def _lock_key(self, work_id: str) -> str:
        return f"{self._root}\x00{work_id}"

    def exists(self, work_id: str) -> bool:
        return self._path(work_id).exists()

    def load(self, work_id: str) -> StoredWorkConfiguration:
        path = self._path(work_id)
        if not path.exists():
            raise ConfigurationAggregateNotFound(f"work {work_id} S4 aggregate 없음")
        content = _read_enveloped(path, ConfigurationIntegrityError)
        if content.get("schema_version") != STORE_SCHEMA_VERSION:
            raise ConfigurationSchemaUnsupported(
                f"work {work_id} S4 aggregate schema 미상: {content.get('schema_version')!r}"
            )
        try:
            stored = decode_stored(content)
        except (StoredConfigurationError, KeyError, TypeError, AttributeError) as exc:
            # digest 유효해도 configurations 내부가 malformed 이면 store 계약 오류로 정규화한다.
            raise ConfigurationIntegrityError(
                f"work {work_id} S4 aggregate 불변식 위반"
            ) from exc
        if stored.work_id != work_id:
            # 파일이 잘못된 이름으로 복사·이동되면 digest 는 통과해도 key 결속이 깨진다 —
            # 다른 Work 의 선택을 조용히 적용하지 않도록 거절한다.
            raise ConfigurationIntegrityError(
                f"work {work_id} 파일이 다른 Work({stored.work_id}) aggregate 를 담았다"
            )
        return stored

    def create(self, stored: StoredWorkConfiguration) -> None:
        """새 Work S4 aggregate 를 최초 commit 한다(create-once)."""
        if stored.aggregate_version != 1:
            # create 는 최초 durable commit 이다 — version>1 은 일어나지 않은 commit 을 주장한다.
            raise WorkConfigurationStoreError(
                f"최초 aggregate commit 은 version 1 이어야 한다: {stored.aggregate_version}"
            )
        work_id = stored.work_id
        path = self._path(work_id)
        with _lock(self._lock_key(work_id)):
            if path.exists():
                raise ConfigurationAggregateExists(f"work {work_id} S4 aggregate 이미 존재")
            _write_enveloped(path, encode_stored(stored))

    def update(
        self,
        work_id: str,
        expected_aggregate_version: int,
        mutate: "Callable[[StoredWorkConfiguration], StoredWorkConfiguration]",
    ) -> StoredWorkConfiguration:
        """writer lease 아래 read→CAS→mutate→atomic commit 을 한 번 수행한다.

        ``expected_aggregate_version`` 이 현재와 다르면 CAS 실패(CONFLICT)로 거절한다. commit 은
        aggregate_version 을 정확히 1 올려야 한다 — ledger-only NO_CHANGE 도 durable commit 이라
        version 을 올린다. mutate 가 던지면 write 를 건너뛰어 기존 파일이 무손상으로 남는다.
        """
        with _lock(self._lock_key(work_id)):
            current = self.load(work_id)
            if current.aggregate_version != expected_aggregate_version:
                raise ConfigurationAggregateConflict(
                    f"work {work_id} CAS 실패: expected {expected_aggregate_version}, "
                    f"current {current.aggregate_version}"
                )
            new = mutate(current)
            if new.work_id != work_id:
                raise WorkConfigurationStoreError("update 안에서 다른 Work 로 바꿀 수 없다")
            if new.workspace_instance_id != current.workspace_instance_id:
                # durable workspace identity 는 fence·token 이 쓰는 값이라 재결속 금지.
                raise WorkConfigurationStoreError(
                    "update 는 workspace identity 를 바꿀 수 없다"
                )
            if new.aggregate_version != current.aggregate_version + 1:
                raise WorkConfigurationStoreError(
                    "commit 은 aggregate_version 을 정확히 1 올려야 한다"
                )
            prior = current.processed_requests
            if new.processed_requests[: len(prior)] != prior:
                # first-seen ledger 는 immutable — 기존 기록을 지우거나 바꾸면 재실행·키
                # 재사용이 열린다. 기존 ledger 가 commit ledger 의 prefix 로 남아야 한다.
                raise WorkConfigurationStoreError(
                    "first-seen ledger 는 append-only 다(기존 기록 보존)"
                )
            _write_enveloped(self._path(work_id), encode_stored(new))
            return new
