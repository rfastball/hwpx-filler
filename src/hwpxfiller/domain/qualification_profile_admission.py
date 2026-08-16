"""Qualification Profile admission policy 값·의미 (S5-08 · #704).

immutable Qualification Profile **semantics**(Manifest)와, 현재 새 seal/materialization 을
허용하는 **mutable operational admission**(이 모듈)을 분리한다. Manifest 에 revoked flag 를
넣지 않는다 — admission 은 monotonic policy_version 을 가진 별도 decision chain 이다.

이 모듈은 순수하다: store·fence·manifest 저장소·HWPX 를 모른다. 값 불변식·decision chain
복원·canonical digest 만 소유한다. bootstrap/register/revoke command 결선은
:mod:`hwpxfiller.external.profile_admission_runner`, durable aggregate 는
:mod:`hwpxfiller.application.stored_profile_admission` 이 진다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

# state 어휘 — v1 전이는 ADMITTED → REVOKED 하나뿐(un-revoke 비범위).
ADMITTED = "ADMITTED"
REVOKED = "REVOKED"
_STATES = (ADMITTED, REVOKED)

# canonical framing v1 — length-prefixed UTF-8(u32 big-endian) + u32.
# ponytail: self-contained encoder. S5-06 이 closed framing set 을 소유하면 그리로 접는다(#704).
_MAGIC = b"HFPADM1\0"  # exact 8 bytes
POLICY_OBSERVATION_DIGEST_VERSION = "profile-admission-observation/v1"
_U32_MAX = 0xFFFF_FFFF


class ProfileAdmissionError(Exception):
    """admission 값·chain 불변식 위반의 뿌리."""

    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


class ProfileAdmissionIntegrityError(ProfileAdmissionError):
    code = "QUALIFICATION_PROFILE_ADMISSION_INTEGRITY_ERROR"


class ProfileAdmissionStateMissing(ProfileAdmissionError):
    """runtime query 에서 admission state 가 없다 — implicit ADMITTED 로 넘어가지 않는다(context error)."""

    code = "QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING"


def _require_text(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ProfileAdmissionIntegrityError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogate
        raise ProfileAdmissionIntegrityError(f"{what} 에 유효하지 않은 Unicode scalar") from exc
    return value


def _require_pos_int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProfileAdmissionIntegrityError(f"{what} 은 1 이상 정수여야 한다")
    return value


def _encode_text(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > _U32_MAX:  # pragma: no cover - 4GB 초과 텍스트는 실전 도달 불가한 방어 가드
        raise ProfileAdmissionIntegrityError("canonical text 가 u32 범위 초과")
    return len(raw).to_bytes(4, "big") + raw


def _encode_u32(value: int) -> bytes:
    if value < 0 or value > _U32_MAX:
        raise ProfileAdmissionIntegrityError("canonical u32 값이 범위 초과")
    return value.to_bytes(4, "big")


def decision_ref(qualification_profile_id: str, policy_version: int) -> str:
    """decision 의 결정적 안정 참조 — 같은 (profile, version) 은 replay 에도 같은 bytes."""
    _require_text(qualification_profile_id, "qualification_profile_id")
    _require_pos_int(policy_version, "policy_version")
    return f"{qualification_profile_id}@v{policy_version}"


def policy_observation_digest(
    qualification_profile_id: str,
    policy_version: int,
    state: str,
    current_decision_ref: str,
) -> str:
    """sha256(profile_id, policy_version, state, current_decision_ref).

    updated_at·store path·audit 문안·actor session·lock instance 는 **제외**한다 —
    같은 policy 관찰은 언제 어디서 읽어도 같은 digest 다.
    """
    _require_text(qualification_profile_id, "qualification_profile_id")
    _require_pos_int(policy_version, "policy_version")
    if state not in _STATES:
        raise ProfileAdmissionIntegrityError(f"미상 state {state!r}")
    _require_text(current_decision_ref, "current_decision_ref")
    canonical = (
        _MAGIC
        + _encode_text(POLICY_OBSERVATION_DIGEST_VERSION)
        + _encode_text(qualification_profile_id)
        + _encode_u32(policy_version)
        + _encode_text(state)
        + _encode_text(current_decision_ref)
    )
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def command_fingerprint(command_kind: str, *parts: str) -> str:
    """command idempotency fingerprint — 같은 의미 입력은 같은 bytes(다르면 KEY_REUSED 판정)."""
    _require_text(command_kind, "command_kind")
    canonical = bytearray(_MAGIC)
    canonical += _encode_text("profile-admission-command/v1")
    canonical += _encode_text(command_kind)
    canonical += _encode_u32(len(parts))
    for part in parts:
        canonical += _encode_text(part)
    return "sha256:" + hashlib.sha256(bytes(canonical)).hexdigest()


@dataclass(frozen=True)
class AdmissionDecision:
    """decision chain 의 immutable 한 마디 — 한번 적히면 값이 고정된다."""

    policy_version: int
    state: str
    decision_ref: str
    request_id: str
    reason_ref: str | None
    decided_at: str

    def __post_init__(self) -> None:
        _require_pos_int(self.policy_version, "policy_version")
        if self.state not in _STATES:
            raise ProfileAdmissionIntegrityError(f"미상 decision state {self.state!r}")
        # decision_ref 의 (profile, version) 결속은 chain 검증이 진다(여기선 존재만).
        _require_text(self.decision_ref, "decision_ref")
        _require_text(self.request_id, "request_id")
        if self.reason_ref is not None:
            _require_text(self.reason_ref, "reason_ref")
        _require_text(self.decided_at, "decided_at")


def validate_decision_chain(
    qualification_profile_id: str, decisions: Sequence[AdmissionDecision]
) -> None:
    """chain 불변식 — monotonic version·v1 전이·결정적 ref.

    - 비어 있지 않다(committed aggregate 는 최소 bootstrap decision 하나).
    - policy_version 은 1 부터 정확히 +1 씩 strictly monotonic(index+1).
    - decision_ref 는 (profile, version) 의 결정적 값과 일치.
    - 첫 decision 은 ADMITTED|REVOKED(bootstrap). ADMITTED→REVOKED 만 허용,
      REVOKED→ADMITTED(un-revoke)·REVOKED→REVOKED·ADMITTED→ADMITTED 는 거절.
    """
    if not decisions:
        raise ProfileAdmissionIntegrityError("decision chain 이 비어 있다")
    prev: AdmissionDecision | None = None
    for index, decision in enumerate(decisions):
        expected_version = index + 1
        if decision.policy_version != expected_version:
            raise ProfileAdmissionIntegrityError(
                f"policy_version 이 monotonic 아님: index {index} 에 "
                f"{decision.policy_version}(기대 {expected_version})"
            )
        if decision.decision_ref != decision_ref(
            qualification_profile_id, decision.policy_version
        ):
            raise ProfileAdmissionIntegrityError(
                f"decision_ref 가 (profile, version) 결정값과 불일치: {decision.decision_ref!r}"
            )
        if prev is not None and not (prev.state == ADMITTED and decision.state == REVOKED):
            raise ProfileAdmissionIntegrityError(
                f"허용되지 않은 전이 {prev.state}→{decision.state}(v1 은 ADMITTED→REVOKED 만)"
            )
        prev = decision


@dataclass(frozen=True)
class QualificationProfileAdmissionObservation:
    """under-fence authoritative admission 관찰(updated_at 없음 = digest 정의역과 동일)."""

    qualification_profile_id: str
    policy_version: int
    state: str
    current_decision_ref: str
    policy_observation_digest: str


@dataclass(frozen=True)
class QualificationProfileAdmissionState:
    """durable current admission state(관찰 + updated_at)."""

    qualification_profile_id: str
    policy_version: int
    state: str
    current_decision_ref: str
    policy_observation_digest: str
    updated_at: str


def observe_chain(
    qualification_profile_id: str, decisions: Sequence[AdmissionDecision]
) -> QualificationProfileAdmissionObservation:
    """검증된 chain 의 tail 을 authoritative observation 으로 투영한다(current state 복원)."""
    validate_decision_chain(qualification_profile_id, decisions)
    tail = decisions[-1]
    return QualificationProfileAdmissionObservation(
        qualification_profile_id=qualification_profile_id,
        policy_version=tail.policy_version,
        state=tail.state,
        current_decision_ref=tail.decision_ref,
        policy_observation_digest=policy_observation_digest(
            qualification_profile_id, tail.policy_version, tail.state, tail.decision_ref
        ),
    )
