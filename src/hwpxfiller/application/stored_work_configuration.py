"""S4 Work별 저장 aggregate — durable envelope·first-seen idempotency ledger (S4-03 #673).

#672 의 :class:`WorkSlotConfigurationAggregate`(work_id + Configuration 들)를 그대로 담고,
저장 계층이 더하는 것만 두른다: ``aggregate_version``(durable commit 횟수), 이 aggregate 가 사는
``workspace_instance_id``, 그리고 request 별 최초 terminal outcome 을 immutable 로 보존하는
first-seen idempotency ledger.

**소유 밖(발명 금지)**: 파일 원자 replace·writer lease·CAS 기계와 Workspace identity provider 는
:mod:`hwpxfiller.external.work_configuration_store` 가 진다. fingerprint 계산 의미는 #677 이
소유한다 — 여기는 그 schema ID·digest bytes 를 손실 없이 보존할 뿐이다. Projection DTO·파생
상태는 저장하지 않는다.

``aggregate_version`` 은 Configuration version 과 다르다: 후자는 declared 선택의 semantic 변경
횟수(#672), 전자는 Configuration 또는 ledger 를 포함한 durable commit 횟수다. NO_CHANGE 결과를
최초 ledger 에 적으면 Configuration version 은 그대로고 aggregate version 만 오를 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from hwpxfiller.application.work_slot_configuration import (
    WorkSlotConfigurationAggregate,
    decode_aggregate,
    empty_aggregate,
    encode_aggregate,
)

STORE_SCHEMA_VERSION = "work-slot-configuration-store-v1"


class StoredConfigurationError(ValueError):
    """저장 aggregate 값·ledger 불변식 위반."""


class IdempotencyKeyReused(StoredConfigurationError):
    """같은 request_id 를 다른 fingerprint 로 재사용 — 최초 record 를 수정하지 않는다."""


def _require_nonempty(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise StoredConfigurationError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


def _require_opt_pos_int(value: object, what: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StoredConfigurationError(f"{what} 은 1 이상 정수이거나 None 이어야 한다")


@dataclass(frozen=True)
class TerminalOutcome:
    """request 의 최초 commit 된 종결 결과 — Projection 전체가 아니라 판정 값만."""

    application_id: str
    outcome_code: str
    changed: bool
    source_configuration_version: int | None
    resulting_configuration_version: int | None

    def __post_init__(self) -> None:
        _require_nonempty(self.application_id, "application_id")
        _require_nonempty(self.outcome_code, "outcome_code")
        if not isinstance(self.changed, bool):
            raise StoredConfigurationError("changed 는 bool 이어야 한다")
        _require_opt_pos_int(
            self.source_configuration_version, "source_configuration_version"
        )
        _require_opt_pos_int(
            self.resulting_configuration_version, "resulting_configuration_version"
        )


@dataclass(frozen=True)
class IdempotencyRecord:
    """request_id 별 최초 record — 한번 적히면 immutable(fingerprint 는 #677 의미의 bytes 만)."""

    request_id: str
    fingerprint_schema_version: str
    command_fingerprint: str
    terminal_outcome: TerminalOutcome
    request_actor_binding_digest: str
    recorded_at: str

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        _require_nonempty(self.fingerprint_schema_version, "fingerprint_schema_version")
        _require_nonempty(self.command_fingerprint, "command_fingerprint")
        _require_nonempty(
            self.request_actor_binding_digest, "request_actor_binding_digest"
        )
        _require_nonempty(self.recorded_at, "recorded_at")
        if not isinstance(self.terminal_outcome, TerminalOutcome):
            raise StoredConfigurationError("terminal_outcome 은 TerminalOutcome 이어야 한다")


def _same_fingerprint(a: IdempotencyRecord, b: IdempotencyRecord) -> bool:
    return (
        a.fingerprint_schema_version == b.fingerprint_schema_version
        and a.command_fingerprint == b.command_fingerprint
    )


@dataclass(frozen=True)
class StoredWorkConfiguration:
    """한 Work 의 durable S4 상태 — Configuration aggregate + version + ledger."""

    schema_version: str
    aggregate_version: int
    workspace_instance_id: str
    configurations: WorkSlotConfigurationAggregate
    processed_requests: tuple[IdempotencyRecord, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STORE_SCHEMA_VERSION:
            raise StoredConfigurationError(
                f"미상 store schema_version {self.schema_version!r}"
            )
        if isinstance(self.aggregate_version, bool) or not isinstance(
            self.aggregate_version, int
        ):
            raise StoredConfigurationError("aggregate_version 은 정수여야 한다")
        if self.aggregate_version < 1:
            raise StoredConfigurationError("aggregate_version 은 1 이상이다")
        _require_nonempty(self.workspace_instance_id, "workspace_instance_id")
        if not isinstance(self.configurations, WorkSlotConfigurationAggregate):
            raise StoredConfigurationError(
                "configurations 는 WorkSlotConfigurationAggregate 이어야 한다"
            )
        seen: set[str] = set()
        for record in self.processed_requests:
            if not isinstance(record, IdempotencyRecord):
                raise StoredConfigurationError("processed_requests 항목이 IdempotencyRecord 아님")
            if record.request_id in seen:
                raise StoredConfigurationError(
                    f"request_id 당 record 는 최대 하나: {record.request_id}"
                )
            seen.add(record.request_id)

    @property
    def work_id(self) -> str:
        return self.configurations.work_id


def empty_stored(
    workspace_instance_id: str, work_id: str
) -> StoredWorkConfiguration:
    """Configuration·ledger 가 비어도 존재하는 최초 aggregate(aggregate_version 1)."""
    return StoredWorkConfiguration(
        schema_version=STORE_SCHEMA_VERSION,
        aggregate_version=1,
        workspace_instance_id=workspace_instance_id,
        configurations=empty_aggregate(work_id),
        processed_requests=(),
    )


def find_request(
    stored: StoredWorkConfiguration, request_id: str
) -> IdempotencyRecord | None:
    for record in stored.processed_requests:
        if record.request_id == request_id:
            return record
    return None


def append_request(
    stored: StoredWorkConfiguration, record: IdempotencyRecord
) -> StoredWorkConfiguration:
    """first-seen ledger append — 최초 record 는 immutable.

    같은 request_id + 같은 fingerprint 재전송은 replay 라 그대로 돌려준다(idempotent).
    같은 request_id + 다른 fingerprint 는 ``IdempotencyKeyReused`` 로 거절하고 최초 record 를
    수정하지 않는다. aggregate_version 은 여기서 올리지 않는다 — durable commit 은 store 몫이다.
    """
    existing = find_request(stored, record.request_id)
    if existing is not None:
        if _same_fingerprint(existing, record):
            return stored
        raise IdempotencyKeyReused(
            f"request {record.request_id} 가 다른 fingerprint 로 재사용됨"
        )
    return replace(
        stored, processed_requests=stored.processed_requests + (record,)
    )


# ─── codec ────────────────────────────────────────────────────────────────────
def _encode_outcome(outcome: TerminalOutcome) -> dict[str, Any]:
    return {
        "application_id": outcome.application_id,
        "outcome_code": outcome.outcome_code,
        "changed": outcome.changed,
        "source_configuration_version": outcome.source_configuration_version,
        "resulting_configuration_version": outcome.resulting_configuration_version,
    }


def _decode_outcome(data: Any) -> TerminalOutcome:
    if not isinstance(data, dict):
        raise StoredConfigurationError("terminal_outcome 표현이 malformed")
    return TerminalOutcome(
        application_id=data.get("application_id"),
        outcome_code=data.get("outcome_code"),
        changed=data.get("changed"),
        source_configuration_version=data.get("source_configuration_version"),
        resulting_configuration_version=data.get("resulting_configuration_version"),
    )


def _encode_record(record: IdempotencyRecord) -> dict[str, Any]:
    return {
        "request_id": record.request_id,
        "fingerprint_schema_version": record.fingerprint_schema_version,
        "command_fingerprint": record.command_fingerprint,
        "terminal_outcome": _encode_outcome(record.terminal_outcome),
        "request_actor_binding_digest": record.request_actor_binding_digest,
        "recorded_at": record.recorded_at,
    }


def _decode_record(data: Any) -> IdempotencyRecord:
    if not isinstance(data, dict):
        raise StoredConfigurationError("idempotency record 표현이 malformed")
    return IdempotencyRecord(
        request_id=data.get("request_id"),
        fingerprint_schema_version=data.get("fingerprint_schema_version"),
        command_fingerprint=data.get("command_fingerprint"),
        terminal_outcome=_decode_outcome(data.get("terminal_outcome")),
        request_actor_binding_digest=data.get("request_actor_binding_digest"),
        recorded_at=data.get("recorded_at"),
    )


def encode_stored(stored: StoredWorkConfiguration) -> dict[str, Any]:
    return {
        "schema_version": stored.schema_version,
        "aggregate_version": stored.aggregate_version,
        "workspace_instance_id": stored.workspace_instance_id,
        "configurations": encode_aggregate(stored.configurations),
        "processed_requests": [
            _encode_record(r) for r in stored.processed_requests
        ],
    }


def decode_stored(data: Any) -> StoredWorkConfiguration:
    if not isinstance(data, dict):
        raise StoredConfigurationError("stored aggregate 표현이 malformed")
    if not isinstance(data.get("processed_requests"), list):
        raise StoredConfigurationError("processed_requests 는 리스트여야 한다")
    if not isinstance(data.get("configurations"), dict):
        raise StoredConfigurationError("configurations 표현이 malformed")
    return StoredWorkConfiguration(
        schema_version=data.get("schema_version"),
        aggregate_version=data.get("aggregate_version"),
        workspace_instance_id=data.get("workspace_instance_id"),
        configurations=decode_aggregate(data["configurations"]),
        processed_requests=tuple(
            _decode_record(r) for r in data["processed_requests"]
        ),
    )
