"""Profile-scoped admission aggregate — durable decision chain + first-seen ledger (S5-08 · #704).

한 Qualification Profile 의 durable admission 상태를 담는다: ``aggregate_version``(durable commit
횟수), immutable decision chain, current state 투영, request 별 최초 terminal outcome 을 보존하는
first-seen idempotency ledger. Manifest 는 이 aggregate 가 **수정하지 않는다**(참조만).

값·불변식·코덱만 소유한다(native-free). 파일 원자 replace·CAS·writer lease 는
:mod:`hwpxfiller.external.profile_admission_store`, fence·command 결선은
:mod:`hwpxfiller.external.profile_admission_runner` 가 진다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from hwpxfiller.domain.qualification_profile_admission import (
    AdmissionDecision,
    ProfileAdmissionIntegrityError,
    observe_chain,
)

STORE_SCHEMA_VERSION = "qualification-profile-admission-store-v1"


class StoredProfileAdmissionError(ValueError):
    """저장 aggregate 값·ledger 불변식 위반."""

    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


class AdmissionIdempotencyKeyReused(StoredProfileAdmissionError):
    """같은 request_id 를 다른 fingerprint 로 재사용 — 최초 record 를 수정하지 않는다."""

    code = "IDEMPOTENCY_KEY_REUSED"


def _require_nonempty(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise StoredProfileAdmissionError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


@dataclass(frozen=True)
class AdmissionOutcome:
    """request 의 최초 commit 된 종결 결과 — 판정 값만."""

    outcome_code: str
    resulting_policy_version: int
    resulting_state: str
    current_decision_ref: str

    def __post_init__(self) -> None:
        _require_nonempty(self.outcome_code, "outcome_code")
        if isinstance(self.resulting_policy_version, bool) or not isinstance(
            self.resulting_policy_version, int
        ) or self.resulting_policy_version < 1:
            raise StoredProfileAdmissionError("resulting_policy_version 은 1 이상 정수여야 한다")
        _require_nonempty(self.resulting_state, "resulting_state")
        _require_nonempty(self.current_decision_ref, "current_decision_ref")


@dataclass(frozen=True)
class AdmissionIdempotencyRecord:
    """request_id 별 최초 record — 한번 적히면 immutable."""

    request_id: str
    command_fingerprint: str
    terminal_outcome: AdmissionOutcome
    recorded_at: str

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        _require_nonempty(self.command_fingerprint, "command_fingerprint")
        _require_nonempty(self.recorded_at, "recorded_at")
        if not isinstance(self.terminal_outcome, AdmissionOutcome):
            raise StoredProfileAdmissionError("terminal_outcome 은 AdmissionOutcome 이어야 한다")


def _validate_ledger_against_chain(
    decisions: tuple[AdmissionDecision, ...],
    processed_requests: tuple[AdmissionIdempotencyRecord, ...],
) -> None:
    """checksum 만 통과한 envelope 를 ledger↔chain 정합으로 한번 더 닫는다(fail-closed).

    - 각 decision 을 만든 request_id 는 반드시 ledger 에 남아 있어야 한다(창작자 누락 금지).
    - 각 ledger outcome 은 자기가 가리키는 policy_version 의 chain snapshot(state·decision_ref)과
      일치해야 한다 — unknown state·존재하지 않는 version·남의 profile decision_ref 를 거절한다.
    """
    by_version = {d.policy_version: d for d in decisions}  # version 은 chain 검증이 유일 보장
    ledger_requests = {r.request_id for r in processed_requests}
    for decision in decisions:
        if decision.request_id not in ledger_requests:
            raise StoredProfileAdmissionError(
                f"decision v{decision.policy_version} 을 만든 request 가 ledger 에 없음"
            )
    for record in processed_requests:
        outcome = record.terminal_outcome
        snapshot = by_version.get(outcome.resulting_policy_version)
        if snapshot is None:
            raise StoredProfileAdmissionError(
                f"ledger outcome 이 없는 policy_version {outcome.resulting_policy_version} 을 가리킴"
            )
        if (
            outcome.resulting_state != snapshot.state
            or outcome.current_decision_ref != snapshot.decision_ref
        ):
            raise StoredProfileAdmissionError(
                f"ledger outcome 이 chain snapshot(v{outcome.resulting_policy_version})과 불일치"
            )


@dataclass(frozen=True)
class StoredProfileAdmission:
    """한 Profile 의 durable admission aggregate."""

    schema_version: str
    aggregate_version: int
    qualification_profile_id: str
    bound_manifest_digest: str
    current_state: str
    current_decision_ref: str
    current_policy_observation_digest: str
    decisions: tuple[AdmissionDecision, ...]
    processed_requests: tuple[AdmissionIdempotencyRecord, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STORE_SCHEMA_VERSION:
            raise StoredProfileAdmissionError(
                f"미상 store schema_version {self.schema_version!r}"
            )
        if isinstance(self.aggregate_version, bool) or not isinstance(
            self.aggregate_version, int
        ) or self.aggregate_version < 1:
            raise StoredProfileAdmissionError("aggregate_version 은 1 이상 정수여야 한다")
        _require_nonempty(self.qualification_profile_id, "qualification_profile_id")
        _require_nonempty(self.bound_manifest_digest, "bound_manifest_digest")
        # current state 는 decision chain 에서 복원 가능해야 한다(denorm 필드 == chain tail).
        observation = observe_chain(self.qualification_profile_id, self.decisions)
        if (
            self.current_state != observation.state
            or self.current_decision_ref != observation.current_decision_ref
            or self.current_policy_observation_digest != observation.policy_observation_digest
        ):
            raise StoredProfileAdmissionError(
                "current state 투영이 decision chain tail 과 불일치(손상)"
            )
        seen: set[str] = set()
        for record in self.processed_requests:
            if not isinstance(record, AdmissionIdempotencyRecord):
                raise StoredProfileAdmissionError(
                    "processed_requests 항목이 AdmissionIdempotencyRecord 아님"
                )
            if record.request_id in seen:
                raise StoredProfileAdmissionError(
                    f"request_id 당 record 는 최대 하나: {record.request_id}"
                )
            seen.add(record.request_id)
        _validate_ledger_against_chain(self.decisions, self.processed_requests)


def bootstrap_stored(
    *,
    qualification_profile_id: str,
    bound_manifest_digest: str,
    decision: AdmissionDecision,
    record: AdmissionIdempotencyRecord,
) -> StoredProfileAdmission:
    """최초 admission aggregate(aggregate_version 1, decision chain 길이 1)를 만든다."""
    if decision.policy_version != 1:
        raise StoredProfileAdmissionError("bootstrap decision 은 policy_version 1 이어야 한다")
    observation = observe_chain(qualification_profile_id, (decision,))
    return StoredProfileAdmission(
        schema_version=STORE_SCHEMA_VERSION,
        aggregate_version=1,
        qualification_profile_id=qualification_profile_id,
        bound_manifest_digest=bound_manifest_digest,
        current_state=observation.state,
        current_decision_ref=observation.current_decision_ref,
        current_policy_observation_digest=observation.policy_observation_digest,
        decisions=(decision,),
        processed_requests=(record,),
    )


def find_request(
    stored: StoredProfileAdmission, request_id: str
) -> AdmissionIdempotencyRecord | None:
    for record in stored.processed_requests:
        if record.request_id == request_id:
            return record
    return None


def _projected(
    stored: StoredProfileAdmission, decisions: tuple[AdmissionDecision, ...]
) -> dict[str, str]:
    observation = observe_chain(stored.qualification_profile_id, decisions)
    return {
        "current_state": observation.state,
        "current_decision_ref": observation.current_decision_ref,
        "current_policy_observation_digest": observation.policy_observation_digest,
    }


def commit_next(
    stored: StoredProfileAdmission,
    *,
    new_decision: AdmissionDecision | None,
    record: AdmissionIdempotencyRecord,
) -> StoredProfileAdmission:
    """append-only ledger + optional decision append 를 한 durable commit(version+1)으로 만든다.

    ``new_decision`` 이 None 이면 chain 을 늘리지 않는다(ALREADY_* 처럼 상태를 안 바꾸는 outcome).
    같은 request_id + 같은 fingerprint 재전송은 replay 라 stored 를 그대로 돌려준다(caller 가
    outcome 을 재생). 다른 fingerprint 는 ``AdmissionIdempotencyKeyReused`` 로 거절한다.
    """
    existing = find_request(stored, record.request_id)
    if existing is not None:
        if existing.command_fingerprint == record.command_fingerprint:
            return stored
        raise AdmissionIdempotencyKeyReused(
            f"request {record.request_id} 가 다른 fingerprint 로 재사용됨"
        )
    decisions = stored.decisions + ((new_decision,) if new_decision is not None else ())
    return replace(
        stored,
        aggregate_version=stored.aggregate_version + 1,
        decisions=decisions,
        processed_requests=stored.processed_requests + (record,),
        **_projected(stored, decisions),
    )


# ─── codec ────────────────────────────────────────────────────────────────────
def _encode_decision(decision: AdmissionDecision) -> dict[str, Any]:
    return {
        "policy_version": decision.policy_version,
        "state": decision.state,
        "decision_ref": decision.decision_ref,
        "request_id": decision.request_id,
        "reason_ref": decision.reason_ref,
        "decided_at": decision.decided_at,
    }


def _decode_decision(data: Any) -> AdmissionDecision:
    if not isinstance(data, dict):
        raise StoredProfileAdmissionError("decision 표현이 malformed")
    try:
        return AdmissionDecision(
            policy_version=data.get("policy_version"),
            state=data.get("state"),
            decision_ref=data.get("decision_ref"),
            request_id=data.get("request_id"),
            reason_ref=data.get("reason_ref"),
            decided_at=data.get("decided_at"),
        )
    except ProfileAdmissionIntegrityError as exc:
        raise StoredProfileAdmissionError(str(exc)) from exc


def _encode_outcome(outcome: AdmissionOutcome) -> dict[str, Any]:
    return {
        "outcome_code": outcome.outcome_code,
        "resulting_policy_version": outcome.resulting_policy_version,
        "resulting_state": outcome.resulting_state,
        "current_decision_ref": outcome.current_decision_ref,
    }


def _decode_outcome(data: Any) -> AdmissionOutcome:
    if not isinstance(data, dict):
        raise StoredProfileAdmissionError("terminal_outcome 표현이 malformed")
    return AdmissionOutcome(
        outcome_code=data.get("outcome_code"),
        resulting_policy_version=data.get("resulting_policy_version"),
        resulting_state=data.get("resulting_state"),
        current_decision_ref=data.get("current_decision_ref"),
    )


def _encode_record(record: AdmissionIdempotencyRecord) -> dict[str, Any]:
    return {
        "request_id": record.request_id,
        "command_fingerprint": record.command_fingerprint,
        "terminal_outcome": _encode_outcome(record.terminal_outcome),
        "recorded_at": record.recorded_at,
    }


def _decode_record(data: Any) -> AdmissionIdempotencyRecord:
    if not isinstance(data, dict):
        raise StoredProfileAdmissionError("idempotency record 표현이 malformed")
    return AdmissionIdempotencyRecord(
        request_id=data.get("request_id"),
        command_fingerprint=data.get("command_fingerprint"),
        terminal_outcome=_decode_outcome(data.get("terminal_outcome")),
        recorded_at=data.get("recorded_at"),
    )


def encode_stored(stored: StoredProfileAdmission) -> dict[str, Any]:
    return {
        "schema_version": stored.schema_version,
        "aggregate_version": stored.aggregate_version,
        "qualification_profile_id": stored.qualification_profile_id,
        "bound_manifest_digest": stored.bound_manifest_digest,
        "current_state": stored.current_state,
        "current_decision_ref": stored.current_decision_ref,
        "current_policy_observation_digest": stored.current_policy_observation_digest,
        "decisions": [_encode_decision(d) for d in stored.decisions],
        "processed_requests": [_encode_record(r) for r in stored.processed_requests],
    }


def decode_stored(data: Any) -> StoredProfileAdmission:
    if not isinstance(data, dict):
        raise StoredProfileAdmissionError("stored aggregate 표현이 malformed")
    if not isinstance(data.get("decisions"), list):
        raise StoredProfileAdmissionError("decisions 는 리스트여야 한다")
    if not isinstance(data.get("processed_requests"), list):
        raise StoredProfileAdmissionError("processed_requests 는 리스트여야 한다")
    try:
        return StoredProfileAdmission(
            schema_version=data.get("schema_version"),
            aggregate_version=data.get("aggregate_version"),
            qualification_profile_id=data.get("qualification_profile_id"),
            bound_manifest_digest=data.get("bound_manifest_digest"),
            current_state=data.get("current_state"),
            current_decision_ref=data.get("current_decision_ref"),
            current_policy_observation_digest=data.get("current_policy_observation_digest"),
            decisions=tuple(_decode_decision(d) for d in data["decisions"]),
            processed_requests=tuple(
                _decode_record(r) for r in data["processed_requests"]
            ),
        )
    except ProfileAdmissionIntegrityError as exc:
        # chain 검증 실패(digest 통과했어도 내부 malformed)를 store 계약 오류로 정규화한다.
        raise StoredProfileAdmissionError(str(exc)) from exc
