"""content-addressed Plan 의 file-atomic·CAS·first-seen durable store(S5-07 · #703).

Work(``work_authority_id``) 단위 ``<work>.json`` 에 :class:`WorkExecutionPlanAggregate` 를 둔다.
한 atomic primitive 를 얹는다:

- :meth:`publish_sealed_plan_atomic` — Plan record create/reuse + compilation mapping +
  dependency retention refs + aggregate version 을 **한 commit** 으로.

R2-04a(#740): first-seen request ledger·replay·idempotency 를 제거했다 — 같은 request 재호출은
historical outcome 을 replay 하지 않고 현재 authority 에서 재계산한다. REUSE(같은 content-address)는
aggregate 무변경으로 write 를 생략하고, CREATE 만 CAS 아래 version+1 을 쓴다(in-process writer
lease 아래 first commit wins).

durability 주장 범위·비주장은 :mod:`.work_configuration_store` 와 동일하다: temp 완성→atomic
replace, crash 뒤 old/new 완성 파일만 관찰, envelope digest 검증. **주장하지 않음**: fsync·
power-loss commit durability·cross-process writer exclusion(단일 프로세스 desktop 전제 #620).

값·불변식·codec·순수 전이는 :mod:`hwpxfiller.application.stored_execution_plan` 소유다.
"""

from __future__ import annotations

import json
import re
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hwpxfiller.application.execution_capture import ResolvedSealPolicy
from hwpxfiller.application.execution_contract_set import (
    DurableSealCaptureEvidence,
    SealedExecutionPlanSemanticPayload,
)
from hwpxfiller.application.qualification_evidence import content_digest
from hwpxfiller.application.stored_execution_plan import (
    ExecutionPlanStoreError,
    ExecutionPlanStoreIntegrityError,
    PlanDependencySet,
    PlanPublished,
    StoreConcurrentModification,
    WorkExecutionPlanAggregate,
    apply_publish,
    decode_aggregate,
    empty_aggregate,
    encode_aggregate,
)

from .atomic import write_text_atomic

_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")


def _require_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ExecutionPlanStoreError(f"저장할 수 없는 work_authority_id {value!r}")
    return value


# 프로세스 안 (root, work) 별 writer lease — 지원 topology 는 작업 디렉터리당 writer 프로세스 하나(#192).
# ponytail: in-process RLock — cross-process 원자성은 v1 desktop 전제 밖(#620).
_LOCKS: "weakref.WeakValueDictionary[str, threading.RLock]" = weakref.WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()


def _json_safe(value: Any) -> Any:
    """Mapping→dict·sequence→list 로 재귀 정규화한다(MappingProxyType/tuple 을 durable JSON 으로)."""
    if isinstance(value, Mapping):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _lock(key: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


@dataclass(frozen=True)
class SealCommandResult:
    """publish primitive 결과 — content-addressed create/reuse 뒤의 현재 aggregate(R2-04a).

    first-seen replay/idempotency 를 제거했다: REUSE 는 aggregate 를 무변경으로 되돌리고(write 생략),
    CREATE 만 version 을 올린다. request 별 record/replayed 를 더는 싣지 않는다.
    """

    aggregate: WorkExecutionPlanAggregate


class WorkExecutionPlanStore:
    """Work별 Plan aggregate 의 file-atomic·CAS·first-seen durable 저장소."""

    def __init__(self, root: "str | Path") -> None:
        # resolve: per-root writer lease 가 경로 alias(상대/절대·심볼릭·대소문자)로 갈라지지 않게 정규화.
        self._root = Path(root).resolve()

    def _path(self, work_authority_id: str) -> Path:
        return self._root / f"{_require_id(work_authority_id)}.json"

    def _lock_key(self, work_authority_id: str) -> str:
        return f"{self._root}\x00{work_authority_id}"

    def exists(self, work_authority_id: str) -> bool:
        return self._path(work_authority_id).exists()

    def load(self, work_authority_id: str) -> WorkExecutionPlanAggregate:
        """durable aggregate 를 decode 한다 — 없으면 loud error(:meth:`load_or_empty` 는 empty 반환)."""
        path = self._path(work_authority_id)
        if not path.exists():
            raise ExecutionPlanStoreIntegrityError(
                f"work {work_authority_id} plan aggregate 없음"
            )
        content = self._read_enveloped(path)
        return decode_aggregate(content, work_authority_id)

    def load_or_empty(
        self, work_authority_id: str, workspace_instance_id: str
    ) -> WorkExecutionPlanAggregate:
        """durable aggregate 또는 없으면 version 0 empty(첫 commit 이 version 1 을 낸다)."""
        path = self._path(work_authority_id)
        if not path.exists():
            return empty_aggregate(work_authority_id, workspace_instance_id)
        content = self._read_enveloped(path)
        return decode_aggregate(content, work_authority_id)

    def _read_enveloped(self, path: Path) -> dict:
        try:
            envelope = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise ExecutionPlanStoreIntegrityError(f"{path.name} JSON 파싱 실패(손상)") from exc
        if not isinstance(envelope, dict):
            raise ExecutionPlanStoreIntegrityError(f"{path.name} envelope 형식 손상")
        content = envelope.get("content")
        if envelope.get("digest") != content_digest(content):
            raise ExecutionPlanStoreIntegrityError(f"{path.name} digest 손상")
        if not isinstance(content, dict):
            raise ExecutionPlanStoreIntegrityError(f"{path.name} content 형식 손상")
        return content

    def _write(self, work_authority_id: str, aggregate: WorkExecutionPlanAggregate) -> None:
        # Plan payload 는 deep-freeze 로 MappingProxyType 를 담는다(봉인 alias 차단). durable JSON 은
        # plain 타입만 담으므로 정규화한다 — canonical digest 는 structure 기반이라 값이 불변이다.
        content = _json_safe(encode_aggregate(aggregate))
        envelope = {"digest": content_digest(content), "content": content}
        path = self._path(work_authority_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(envelope, ensure_ascii=False, indent=2))

    def publish_sealed_plan_atomic(
        self,
        *,
        work_authority_id: str,
        workspace_instance_id: str,
        expected_aggregate_version: int,
        request_id: str,
        resolved_seal_policy: ResolvedSealPolicy,
        capture_evidence: DurableSealCaptureEvidence,
        plan_payload: SealedExecutionPlanSemanticPayload,
        dependency_set: PlanDependencySet,
        published_outcome: PlanPublished,
        now: str,
    ) -> SealCommandResult:
        """Plan create/reuse·compilation mapping·dependency retention 을 한 aggregate commit 으로 원자화.

        first-seen ledger·idempotency 는 없다(R2-04a): REUSE 는 aggregate 무변경 → write 생략,
        CREATE 만 CAS 아래 version+1 을 쓴다.
        """
        with _lock(self._lock_key(work_authority_id)):
            current = self.load_or_empty(work_authority_id, workspace_instance_id)
            if current.aggregate_version != expected_aggregate_version:
                raise StoreConcurrentModification(
                    f"work {work_authority_id} CAS 실패: expected {expected_aggregate_version}, "
                    f"current {current.aggregate_version}"
                )
            new_aggregate = apply_publish(
                current,
                request_id=request_id,
                resolved_seal_policy=resolved_seal_policy,
                capture_evidence=capture_evidence,
                plan_payload=plan_payload,
                dependency_set=dependency_set,
                published_outcome=published_outcome,
                now=now,
            )
            # REUSE = 무변경(version 동일) → durable write 생략(재작성은 idempotent 낭비).
            if new_aggregate.aggregate_version != current.aggregate_version:
                self._write(work_authority_id, new_aggregate)
            return SealCommandResult(aggregate=new_aggregate)
