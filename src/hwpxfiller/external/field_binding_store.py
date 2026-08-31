"""S5 Field Binding 의 file-atomic 저장 + fence-first commit 결선 (S5-01 · #697).

Work별 ``<work_authority_id>.json`` 에 :class:`StoredWorkFieldBinding` aggregate 를 둔다.
갱신은 writer lease 아래 load→decode→검증→CAS→새 frozen aggregate→temp write→atomic replace 로
**한 번** commit 한다(:mod:`.atomic`). 어느 단계 실패도 기존 파일을 무손상으로 남긴다.

두 commit(legacy migration·current Application review)은 shared
:func:`per_work_mutation_fence` 를 먼저 잡고 ``*_under_fence`` helper 로 위임한다(#675 pattern,
non-reentrant). 순수 결정(basis 이동·미해결 blocker·integrity)은
:mod:`hwpxfiller.application.field_binding_input` 이 지고, 여기선 idempotency ledger replay·
저장만 한다. context/integrity/stale 은 domain-terminal 로 저장하지 않는다(request id 미소비).

durability 주장 범위는 기존 파일 store 와 같다 — power-loss fsync durability 는 주장하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from hwpxfiller.application.field_binding_input import (
    CurrentApplicationFieldStructure,
    FieldBindingApplicationReview,
    FieldBindingInput,
    FieldBindingMigrationDraft,
    FieldBindingRevision,
    decide_application_review_commit,
    decide_migration_commit,
)
from hwpxfiller.application.legacy_field_binding_store_v1 import (
    is_legacy_v1,
    migrate_stored_v1,
)
from hwpxfiller.application.qualification_evidence import content_digest
from hwpxfiller.application.stored_field_binding import (
    APPLICATION_REVIEW,
    MIGRATION,
    STORE_SCHEMA_VERSION,
    CommittedDraftRecord,
    FieldBindingIdempotencyKeyReused,
    FieldBindingIdempotencyRecord,
    StoredFieldBindingError,
    StoredWorkFieldBinding,
    commit_revision,
    decode_stored,
    empty_stored,
    encode_stored,
    find_request,
    revision_by_id,
)
from hwpxfiller.host.per_work_fence import per_work_mutation_fence

from .atomic import write_text_atomic

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")

FINGERPRINT_SCHEMA_VERSION = "field-binding-commit-fingerprint/v1"
FIELD_BINDING_REVISION_COMMITTED = "FIELD_BINDING_REVISION_COMMITTED"
_FINGERPRINT_MAGIC = b"HFBFP1\0\0"


class WorkFieldBindingStoreError(Exception):
    """Field Binding 저장 경계의 loud failure 기반."""


class FieldBindingAggregateNotFound(WorkFieldBindingStoreError):
    pass


class FieldBindingAggregateExists(WorkFieldBindingStoreError):
    pass


class FieldBindingAggregateConflict(WorkFieldBindingStoreError):
    """expected aggregate_version 이 현재와 불일치(CAS 실패)."""


class FieldBindingIntegrityError(WorkFieldBindingStoreError):
    """envelope digest 손상·JSON 파싱 실패 — partial 을 current 로 승격하지 않는다."""


class FieldBindingSchemaUnsupported(WorkFieldBindingStoreError):
    pass


class FieldBindingWorkspaceMismatch(WorkFieldBindingStoreError):
    """저장 aggregate 의 workspace 가 context 와 다르다(cross-workspace 재사용)."""


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise WorkFieldBindingStoreError(f"저장할 수 없는 work_authority_id {value!r}")
    return value


# ponytail: in-process RLock — cross-process 원자성은 v1 desktop 전제 밖(#620 상향).
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


def _read_enveloped(path: Path) -> dict:
    try:
        envelope = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise FieldBindingIntegrityError(f"{path.name} JSON 파싱 실패(손상)") from exc
    if not isinstance(envelope, dict):
        raise FieldBindingIntegrityError(f"{path.name} envelope 형식 손상")
    content = envelope.get("content")
    if envelope.get("digest") != content_digest(content):
        raise FieldBindingIntegrityError(f"{path.name} digest 손상")
    if not isinstance(content, dict):
        raise FieldBindingIntegrityError(f"{path.name} content 형식 손상")
    return content


class WorkFieldBindingStore:
    """Work별 Field Binding aggregate 의 create-once·file-atomic·CAS 저장소."""

    def __init__(self, root: "str | Path") -> None:
        self._root = Path(root).resolve()

    def _path(self, work_authority_id: str) -> Path:
        return self._root / f"{_require_id(work_authority_id)}.json"

    def _lock_key(self, work_authority_id: str) -> str:
        return f"{self._root}\x00{work_authority_id}"

    def exists(self, work_authority_id: str) -> bool:
        return self._path(work_authority_id).exists()

    def load(self, work_authority_id: str) -> StoredWorkFieldBinding:
        path = self._path(work_authority_id)
        if not path.exists():
            raise FieldBindingAggregateNotFound(
                f"work {work_authority_id} Field Binding aggregate 없음"
            )
        content = _read_enveloped(path)
        # schema_version 필드 하나가 판별자다 — v1 파일은 decode-path 에서 v2 로 옮겨 읽고
        # (파일은 손대지 않는다), 그 밖의 값은 latest 로 풀지 않고 시끄럽게 닫는다.
        version = content.get("schema_version")
        if version == STORE_SCHEMA_VERSION:
            decode = decode_stored
        elif is_legacy_v1(content):
            decode = migrate_stored_v1
        else:
            raise FieldBindingSchemaUnsupported(
                f"work {work_authority_id} aggregate schema 미상: {version!r}"
            )
        try:
            stored = decode(content)
        except StoredFieldBindingError as exc:
            raise FieldBindingIntegrityError(
                f"work {work_authority_id} aggregate 불변식 위반"
            ) from exc
        if stored.work_authority_id != work_authority_id:
            raise FieldBindingIntegrityError(
                f"work {work_authority_id} 파일이 다른 Work"
                f"({stored.work_authority_id}) aggregate 를 담았다"
            )
        return stored

    def create(self, stored: StoredWorkFieldBinding) -> None:
        if stored.aggregate_version != 1:
            raise WorkFieldBindingStoreError(
                f"최초 aggregate commit 은 version 1 이어야 한다: {stored.aggregate_version}"
            )
        work_id = stored.work_authority_id
        path = self._path(work_id)
        with _lock(self._lock_key(work_id)):
            if path.exists():
                raise FieldBindingAggregateExists(
                    f"work {work_id} Field Binding aggregate 이미 존재"
                )
            _write_enveloped(path, encode_stored(stored))

    def update(
        self,
        work_authority_id: str,
        expected_aggregate_version: int,
        mutate: "Callable[[StoredWorkFieldBinding], StoredWorkFieldBinding]",
    ) -> StoredWorkFieldBinding:
        """writer lease 아래 read→CAS→mutate→atomic commit 을 한 번 수행한다."""
        with _lock(self._lock_key(work_authority_id)):
            current = self.load(work_authority_id)
            if current.aggregate_version != expected_aggregate_version:
                raise FieldBindingAggregateConflict(
                    f"work {work_authority_id} CAS 실패: "
                    f"expected {expected_aggregate_version}, "
                    f"current {current.aggregate_version}"
                )
            new = mutate(current)
            if new.work_authority_id != work_authority_id:
                raise WorkFieldBindingStoreError(
                    "update 안에서 다른 Work 로 바꿀 수 없다"
                )
            if new.workspace_instance_id != current.workspace_instance_id:
                raise WorkFieldBindingStoreError(
                    "update 는 workspace identity 를 바꿀 수 없다"
                )
            if new.aggregate_version != current.aggregate_version + 1:
                raise WorkFieldBindingStoreError(
                    "commit 은 aggregate_version 을 정확히 1 올려야 한다"
                )
            prior = current.first_seen_command_ledger
            if new.first_seen_command_ledger[: len(prior)] != prior:
                raise WorkFieldBindingStoreError(
                    "first-seen ledger 는 append-only 다(기존 기록 보존)"
                )
            prior_revs = current.immutable_binding_revisions
            if new.immutable_binding_revisions[: len(prior_revs)] != prior_revs:
                # immutable revision history 는 append-only — 기존 base 를 수정하지 않는다.
                raise WorkFieldBindingStoreError(
                    "immutable revision history 는 append-only 다(old base 불변)"
                )
            _write_enveloped(self._path(work_authority_id), encode_stored(new))
            return new


# ─── commit ports ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LegacyMigrationBasis:
    """commit 시점 legacy migration basis — current Application 과 legacy fingerprint 둘 다.

    legacy Mapping entry 가 그대로여도 Work 가 A17→A18 로 옮겼으면 fingerprint 만으론 stale 을
    못 본다 — current Application 을 함께 실어 fence 아래 재확인한다.
    """

    current_application_id: str
    legacy_basis_fingerprint: str


class LegacyFieldBindingBasisPort(Protocol):
    """commit 시점 legacy migration basis(current Application + fingerprint) 재확인."""

    def current_legacy_migration_basis(
        self, work_authority_id: str
    ) -> LegacyMigrationBasis: ...


class CurrentApplicationFieldStructurePort(Protocol):
    """commit 시점 current Template Application 의 Field 구조."""

    def current_application_field_structure(
        self, work_authority_id: str
    ) -> CurrentApplicationFieldStructure: ...


@dataclass(frozen=True)
class FieldBindingCommitResult:
    revision: FieldBindingRevision
    outcome_replayed: bool


# ─── commit fingerprint ──────────────────────────────────────────────────────────
def _text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return len(raw).to_bytes(4, "big") + raw


def commit_fingerprint(
    kind: str, resolved_input: FieldBindingInput, basis_token: str
) -> str:
    """request semantic fingerprint — 같은 request+같은 content+같은 basis 는 replay.

    ``basis_token`` 은 command 의 capture 기준(migration=legacy fingerprint, review=review basis
    digest)이다. resolved_input 만 봤다면 같은 request ID 를 다른 draft/review 로 재사용해도 이전
    revision 이 조용히 replay 된다 — basis 를 포함해 그 mismatch 를 reuse 로 시끄럽게 만든다.
    """
    out = bytearray()
    out += _FINGERPRINT_MAGIC
    out += _text(FINGERPRINT_SCHEMA_VERSION)
    out += _text(kind)
    out += _text(resolved_input.work_authority_id)
    out += _text(resolved_input.base_template_application_id)
    out += _text(resolved_input.raw_record_contract_id)
    out += _text(resolved_input.canonical_binding_digest)
    out += _text(resolved_input.canonical_source_schema_digest)
    out += _text(basis_token)
    return "sha256:" + hashlib.sha256(bytes(out)).hexdigest()


# ─── shared commit machinery ─────────────────────────────────────────────────────
def _load_existing(
    store: WorkFieldBindingStore, ws: str, work_id: str
) -> StoredWorkFieldBinding | None:
    if not store.exists(work_id):
        return None
    stored = store.load(work_id)
    if stored.workspace_instance_id != ws:
        raise FieldBindingWorkspaceMismatch(
            f"저장 workspace {stored.workspace_instance_id!r} 가 context {ws!r} 와 다르다"
        )
    return stored


def _replay_or_none(
    stored: StoredWorkFieldBinding | None, request_id: str, fingerprint: str
) -> FieldBindingCommitResult | None:
    """ledger 에 최초 결과가 있으면 replay — context decoder 없이 저장 revision 을 되돌려준다."""
    if stored is None:
        return None
    existing = find_request(stored, request_id)
    if existing is None:
        return None
    if (
        existing.command_fingerprint == fingerprint
        and existing.fingerprint_schema_version == FINGERPRINT_SCHEMA_VERSION
    ):
        revision = revision_by_id(stored, existing.produced_revision_id)
        if revision is None:  # pragma: no cover - ledger↔revision 무결성은 aggregate 불변식
            raise FieldBindingIntegrityError("ledger 가 없는 revision 을 가리킨다")
        return FieldBindingCommitResult(revision, outcome_replayed=True)
    raise FieldBindingIdempotencyKeyReused(
        f"request {request_id} 가 다른 fingerprint 로 재사용됨"
    )


def _persist_commit(
    store: WorkFieldBindingStore,
    ws: str,
    work_id: str,
    stored: StoredWorkFieldBinding | None,
    revision: FieldBindingRevision,
    draft_record: CommittedDraftRecord,
    ledger_record: FieldBindingIdempotencyRecord,
) -> None:
    """revision·current pointer·draft·ledger 를 한 aggregate commit 으로 쓴다."""
    if stored is None:
        base = empty_stored(ws, work_id)  # version 1
        new = commit_revision(base, revision, draft_record, ledger_record)
        store.create(new)
        return
    new = replace(
        commit_revision(stored, revision, draft_record, ledger_record),
        aggregate_version=stored.aggregate_version + 1,
    )
    store.update(work_id, stored.aggregate_version, lambda _cur: new)


def _finish_commit(
    store: WorkFieldBindingStore,
    ws: str,
    work_id: str,
    stored: StoredWorkFieldBinding | None,
    revision: FieldBindingRevision,
    kind: str,
    request_id: str,
    fingerprint: str,
    application_id: str,
    basis_fingerprint: str,
    now: str,
) -> FieldBindingCommitResult:
    revision_id = revision.field_binding_authority_revision
    draft_record = CommittedDraftRecord(
        kind=kind,
        request_id=request_id,
        application_id=application_id,
        basis_fingerprint=basis_fingerprint,
        produced_revision_id=revision_id,
        recorded_at=now,
    )
    ledger_record = FieldBindingIdempotencyRecord(
        request_id=request_id,
        fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
        command_fingerprint=fingerprint,
        produced_revision_id=revision_id,
        outcome_code=FIELD_BINDING_REVISION_COMMITTED,
        recorded_at=now,
    )
    _persist_commit(
        store, ws, work_id, stored, revision, draft_record, ledger_record
    )
    return FieldBindingCommitResult(revision, outcome_replayed=False)


# ─── legacy migration commit ─────────────────────────────────────────────────────
def commit_field_binding_migration(
    store: WorkFieldBindingStore,
    basis_port: LegacyFieldBindingBasisPort,
    *,
    workspace_instance_id: str,
    work_authority_id: str,
    request_id: str,
    draft: FieldBindingMigrationDraft,
    resolved_input: FieldBindingInput,
    omitted_field_ids: "frozenset[str] | set[str]" = frozenset(),
    now: str,
) -> FieldBindingCommitResult:
    """CommitFieldBindingMigration — fence 아래 legacy basis 재확인·immutable revision 생성."""
    with per_work_mutation_fence(workspace_instance_id, work_authority_id):
        return _commit_migration_under_fence(
            store, basis_port, workspace_instance_id, work_authority_id,
            request_id, draft, resolved_input, omitted_field_ids, now,
        )


def _commit_migration_under_fence(
    store: WorkFieldBindingStore,
    basis_port: LegacyFieldBindingBasisPort,
    ws: str,
    work_id: str,
    request_id: str,
    draft: FieldBindingMigrationDraft,
    resolved_input: FieldBindingInput,
    omitted_field_ids: "frozenset[str] | set[str]",
    now: str,
) -> FieldBindingCommitResult:
    _require_route(ws, work_id, resolved_input)
    stored = _load_existing(store, ws, work_id)
    fingerprint = commit_fingerprint(
        MIGRATION, resolved_input, draft.legacy_basis_fingerprint
    )
    replayed = _replay_or_none(stored, request_id, fingerprint)
    if replayed is not None:
        return replayed
    # fence 아래에서 current Application + legacy fingerprint 를 함께 재확인한다.
    basis = basis_port.current_legacy_migration_basis(work_id)
    # 순수 결정 — stale/review/integrity 는 여기서 raise 하고 ledger 를 남기지 않는다.
    revision = decide_migration_commit(
        draft, resolved_input, basis.current_application_id,
        basis.legacy_basis_fingerprint, omitted_field_ids,
    )
    return _finish_commit(
        store, ws, work_id, stored, revision, MIGRATION, request_id, fingerprint,
        draft.base_template_application_id, draft.legacy_basis_fingerprint, now,
    )


# ─── current Application review commit ───────────────────────────────────────────
def commit_field_binding_for_current_application(
    store: WorkFieldBindingStore,
    structure_port: CurrentApplicationFieldStructurePort,
    *,
    workspace_instance_id: str,
    work_authority_id: str,
    request_id: str,
    review: FieldBindingApplicationReview,
    resolved_input: FieldBindingInput,
    now: str,
) -> FieldBindingCommitResult:
    """CommitFieldBindingForCurrentApplication — fence 아래 current Application 재확인·새 revision."""
    with per_work_mutation_fence(workspace_instance_id, work_authority_id):
        return _commit_review_under_fence(
            store, structure_port, workspace_instance_id, work_authority_id,
            request_id, review, resolved_input, now,
        )


def _commit_review_under_fence(
    store: WorkFieldBindingStore,
    structure_port: CurrentApplicationFieldStructurePort,
    ws: str,
    work_id: str,
    request_id: str,
    review: FieldBindingApplicationReview,
    resolved_input: FieldBindingInput,
    now: str,
) -> FieldBindingCommitResult:
    _require_route(ws, work_id, resolved_input)
    stored = _load_existing(store, ws, work_id)
    fingerprint = commit_fingerprint(
        APPLICATION_REVIEW, resolved_input, review.review_basis_digest
    )
    replayed = _replay_or_none(stored, request_id, fingerprint)
    if replayed is not None:
        return replayed
    current_structure = structure_port.current_application_field_structure(work_id)
    revision = decide_application_review_commit(
        review, resolved_input, current_structure
    )
    return _finish_commit(
        store, ws, work_id, stored, revision, APPLICATION_REVIEW, request_id,
        fingerprint, review.target_application_id, review.review_basis_digest, now,
    )


def _require_route(ws: str, work_id: str, resolved_input: FieldBindingInput) -> None:
    """route-bound Work·workspace 가 입력의 결속과 일치해야 한다(cross-work commit 금지)."""
    if (
        resolved_input.work_authority_id != work_id
        or resolved_input.workspace_instance_id != ws
    ):
        raise FieldBindingWorkspaceMismatch(
            "resolved_input 의 work/workspace 결속이 route 와 다르다"
        )


# ─── read ─────────────────────────────────────────────────────────────────────────
def load_current_revision(
    store: WorkFieldBindingStore, work_authority_id: str, application_id: str
) -> FieldBindingRevision | None:
    """Application 별 current revision 의 exact lookup(없으면 None)."""
    if not store.exists(work_authority_id):
        return None
    stored = store.load(work_authority_id)
    for pointer in stored.current_by_application:
        if pointer.application_id == application_id:
            return revision_by_id(stored, pointer.revision_id)
    return None
