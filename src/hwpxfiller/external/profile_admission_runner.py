"""Profile admission command 결선 — bootstrap/register/revoke + fence-first 위임 (S5-08 · #704).

각 command 는 shared :func:`profile_admission_fence` 를 먼저 잡고 ``*_under_fence`` helper 로
위임한다(#675 pattern, non-reentrant). helper 는 fence 를 재획득하지 않는다.
``tests/repo_contract/test_per_work_fence_gate.py`` 가 under-fence 직접 호출을 정적으로 막는다.

state 부재는 절대 implicit ADMITTED 로 해석하지 않는다 — bootstrap 은 historical explicit
revocation record 로만 REVOKED 를 만들고, register 는 caller 가 명시한 initial decision 을 쓴다.
runtime query 에서 state 가 없으면 ``QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING`` context error.

manifest 저장소·revocation record 저장소·ProfileFence 는 **injectable port** 다 — S3 Apply·
S5 capture/publish/observation·S6 start 가 뒤 slice 에서 같은 registry 를 주입한다(여기선 안 함).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from hwpxfiller.application.qualification_evidence import (
    QualificationProfileManifest,
    QualificationProfileRevocation,
)
from hwpxfiller.application.stored_profile_admission import (
    AdmissionIdempotencyRecord,
    AdmissionOutcome,
    StoredProfileAdmission,
    bootstrap_stored,
    commit_next,
    find_request,
)
from hwpxfiller.domain.qualification_profile_admission import (
    ADMITTED,
    REVOKED,
    AdmissionDecision,
    ProfileAdmissionStateMissing,
    QualificationProfileAdmissionObservation,
    command_fingerprint,
    decision_ref,
    observe_chain,
)
from hwpxfiller.host.profile_admission_fence import profile_admission_fence

from .profile_admission_store import ProfileAdmissionStore

# outcome 어휘.
INITIALIZED_ADMITTED = "INITIALIZED_ADMITTED"
INITIALIZED_REVOKED = "INITIALIZED_REVOKED"
REGISTERED_ADMITTED = "REGISTERED_ADMITTED"
REGISTERED_REVOKED = "REGISTERED_REVOKED"
ALREADY_INITIALIZED = "ALREADY_INITIALIZED"
REVOKED_OUTCOME = "REVOKED"
ALREADY_REVOKED = "ALREADY_REVOKED"

_FenceFactory = Callable[[str], AbstractContextManager[None]]


class ProfileManifestReadPort(Protocol):
    """exact Profile Manifest 해결 port(S5-03 저장소가 구현). 없으면 raise."""

    def get_manifest(
        self, qualification_profile_id: str
    ) -> QualificationProfileManifest: ...


class ProfileRevocationRecordReadPort(Protocol):
    """historical explicit revocation record 해결 port(없으면 None)."""

    def get_revocation(
        self, qualification_profile_id: str
    ) -> QualificationProfileRevocation | None: ...


class ProfileManifestIntegrityError(Exception):
    """Manifest 부재·손상·profile 결속 불일치 — fail-closed(최신 검색 없음)."""

    code = "QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR"


class AdmissionIdempotencyKeyReused(Exception):
    """같은 request_id 를 다른 fingerprint 로 재사용."""

    code = "IDEMPOTENCY_KEY_REUSED"


@dataclass(frozen=True)
class AdmissionCommandResult:
    """command terminal outcome + 결과 admission 관찰."""

    outcome_code: str
    observation: QualificationProfileAdmissionObservation
    replayed: bool


def _resolve_manifest(
    manifest_port: ProfileManifestReadPort, profile_id: str
) -> QualificationProfileManifest:
    try:
        manifest = manifest_port.get_manifest(profile_id)
    except Exception as exc:  # 저장소 경계: 부재·손상 어느 것도 fail-closed 로 닫는다.
        raise ProfileManifestIntegrityError(
            f"manifest {profile_id} 해결 실패(fail-closed)"
        ) from exc
    if manifest is None or manifest.qualification_profile_id != profile_id:
        raise ProfileManifestIntegrityError(
            f"manifest {profile_id} 의 profile 결속 불일치"
        )
    return manifest


def _replay_result(
    stored_obs: QualificationProfileAdmissionObservation, outcome_code: str
) -> AdmissionCommandResult:
    return AdmissionCommandResult(outcome_code, stored_obs, replayed=True)


def _bootstrap(
    store: ProfileAdmissionStore,
    profile_id: str,
    manifest_digest: str,
    state: str,
    request_id: str,
    fingerprint: str,
    reason_ref: str | None,
    outcome_code: str,
    now: str,
) -> AdmissionCommandResult:
    decision = AdmissionDecision(
        policy_version=1,
        state=state,
        decision_ref=decision_ref(profile_id, 1),
        request_id=request_id,
        reason_ref=reason_ref,
        decided_at=now,
    )
    observation = observe_chain(profile_id, (decision,))
    record = AdmissionIdempotencyRecord(
        request_id=request_id,
        command_fingerprint=fingerprint,
        terminal_outcome=AdmissionOutcome(
            outcome_code, 1, state, decision.decision_ref
        ),
        recorded_at=now,
    )
    store.create(
        bootstrap_stored(
            qualification_profile_id=profile_id,
            bound_manifest_digest=manifest_digest,
            decision=decision,
            record=record,
        )
    )
    return AdmissionCommandResult(outcome_code, observation, replayed=False)


def _record_onto_existing(
    store: ProfileAdmissionStore,
    stored: StoredProfileAdmission,
    request_id: str,
    fingerprint: str,
    outcome_code: str,
    new_decision: AdmissionDecision | None,
    now: str,
) -> AdmissionCommandResult:
    """이미 존재하는 aggregate 에 first-seen ledger(+선택적 decision)를 한 commit 으로 얹는다."""
    profile_id = stored.qualification_profile_id
    existing = find_request(stored, request_id)
    if existing is not None:
        current = observe_chain(profile_id, stored.decisions)
        if existing.command_fingerprint == fingerprint:  # replay: 새 write 안 함
            return _replay_result(current, existing.terminal_outcome.outcome_code)
        raise AdmissionIdempotencyKeyReused(
            f"request {request_id} 가 다른 fingerprint 로 재사용됨"
        )
    decisions = stored.decisions + (
        (new_decision,) if new_decision is not None else ()
    )
    observation = observe_chain(profile_id, decisions)
    record = AdmissionIdempotencyRecord(
        request_id=request_id,
        command_fingerprint=fingerprint,
        terminal_outcome=AdmissionOutcome(
            outcome_code,
            observation.policy_version,
            observation.state,
            observation.current_decision_ref,
        ),
        recorded_at=now,
    )
    new_stored = commit_next(stored, new_decision=new_decision, record=record)
    store.commit(profile_id, stored.aggregate_version, new_stored)
    return AdmissionCommandResult(outcome_code, observation, replayed=False)


# ─── InitializeQualificationProfileAdmission ─────────────────────────────────────
def _initialize_under_fence(
    store: ProfileAdmissionStore,
    profile_id: str,
    request_id: str,
    manifest: QualificationProfileManifest,
    revocation: QualificationProfileRevocation | None,
    now: str,
) -> AdmissionCommandResult:
    fingerprint = command_fingerprint("INITIALIZE", profile_id, manifest.manifest_digest)
    if store.exists(profile_id):  # 재확인: 이미 bootstrap 됨 → idempotent
        return _record_onto_existing(
            store, store.load(profile_id), request_id, fingerprint,
            ALREADY_INITIALIZED, None, now,
        )
    if revocation is not None:  # historical explicit revocation → REVOKED v1
        return _bootstrap(
            store, profile_id, manifest.manifest_digest, REVOKED, request_id,
            fingerprint, revocation.reason, INITIALIZED_REVOKED, now,
        )
    return _bootstrap(  # revocation 없음 → ADMITTED v1(state 없음을 old 라서 ADMITTED 로 하지 않는다)
        store, profile_id, manifest.manifest_digest, ADMITTED, request_id,
        fingerprint, None, INITIALIZED_ADMITTED, now,
    )


def initialize_qualification_profile_admission(
    store: ProfileAdmissionStore,
    manifest_port: ProfileManifestReadPort,
    revocation_port: ProfileRevocationRecordReadPort,
    *,
    qualification_profile_id: str,
    request_id: str,
    now: str,
    fence: _FenceFactory = profile_admission_fence,
) -> AdmissionCommandResult:
    """기존 Profile 의 one-time admission bootstrap — revocation record 로만 REVOKED 를 만든다."""
    if not request_id:
        raise ValueError("request_id 는 비어 있을 수 없다")
    # manifest resolve → integrity → historical revocation record 는 fence 밖에서 읽는다.
    manifest = _resolve_manifest(manifest_port, qualification_profile_id)
    revocation = revocation_port.get_revocation(qualification_profile_id)
    with fence(qualification_profile_id):
        return _initialize_under_fence(
            store, qualification_profile_id, request_id, manifest, revocation, now
        )


# ─── RegisterPublishedQualificationProfileAdmission ──────────────────────────────
def _register_under_fence(
    store: ProfileAdmissionStore,
    profile_id: str,
    manifest_digest: str,
    initial_decision: str,
    request_id: str,
    now: str,
) -> AdmissionCommandResult:
    fingerprint = command_fingerprint(
        "REGISTER", profile_id, initial_decision, manifest_digest
    )
    if store.exists(profile_id):
        return _record_onto_existing(
            store, store.load(profile_id), request_id, fingerprint,
            ALREADY_INITIALIZED, None, now,
        )
    outcome_code = (
        REGISTERED_ADMITTED if initial_decision == ADMITTED else REGISTERED_REVOKED
    )
    return _bootstrap(
        store, profile_id, manifest_digest, initial_decision, request_id,
        fingerprint, None, outcome_code, now,
    )


def register_published_qualification_profile_admission(
    store: ProfileAdmissionStore,
    manifest_port: ProfileManifestReadPort,
    *,
    exact_profile_manifest_ref: str,
    initial_decision: str,
    request_id: str,
    now: str,
    fence: _FenceFactory = profile_admission_fence,
) -> AdmissionCommandResult:
    """새 Profile publication 의 explicit admission registration.

    initial_decision(ADMITTED|REVOKED)은 정책 호출자가 명시한다 — Profile 내용에서 추론하지
    않는다. publication txn 과 이 admission txn 은 분리다: registration 이 없으면 Profile 은
    존재해도 새 apply/seal 에는 state missing 으로 차단된다(별도 저장이라 여기서 아무것도 안 함).
    """
    if not request_id:
        raise ValueError("request_id 는 비어 있을 수 없다")
    if initial_decision not in (ADMITTED, REVOKED):
        raise ValueError(f"initial_decision 은 ADMITTED|REVOKED 여야 한다: {initial_decision!r}")
    manifest = _resolve_manifest(manifest_port, exact_profile_manifest_ref)
    with fence(manifest.qualification_profile_id):
        return _register_under_fence(
            store, manifest.qualification_profile_id, manifest.manifest_digest,
            initial_decision, request_id, now,
        )


# ─── RevokeQualificationProfile ──────────────────────────────────────────────────
def _revoke_under_fence(
    store: ProfileAdmissionStore,
    profile_id: str,
    request_id: str,
    reason_ref: str,
    now: str,
) -> AdmissionCommandResult:
    if not store.exists(profile_id):
        # state 없음 → context error. Initialize/Register 없이 revoke 하지 않는다.
        raise ProfileAdmissionStateMissing(
            f"profile {profile_id} admission state 없음 — 먼저 initialize/register"
        )
    stored = store.load(profile_id)
    fingerprint = command_fingerprint("REVOKE", profile_id, reason_ref)
    if stored.current_state == REVOKED:
        # 이미 REVOKED → deterministic ALREADY_REVOKED(새 decision append 없음).
        return _record_onto_existing(
            store, stored, request_id, fingerprint, ALREADY_REVOKED, None, now
        )
    next_version = stored.decisions[-1].policy_version + 1
    decision = AdmissionDecision(
        policy_version=next_version,
        state=REVOKED,
        decision_ref=decision_ref(profile_id, next_version),
        request_id=request_id,
        reason_ref=reason_ref,
        decided_at=now,
    )
    return _record_onto_existing(
        store, stored, request_id, fingerprint, REVOKED_OUTCOME, decision, now
    )


def revoke_qualification_profile(
    store: ProfileAdmissionStore,
    manifest_port: ProfileManifestReadPort,
    *,
    qualification_profile_id: str,
    request_id: str,
    reason_ref: str,
    now: str,
    fence: _FenceFactory = profile_admission_fence,
) -> AdmissionCommandResult:
    """ADMITTED → REVOKED 전이(policy_version +1). 이미 REVOKED 면 ALREADY_REVOKED terminal."""
    if not request_id:
        raise ValueError("request_id 는 비어 있을 수 없다")
    if not reason_ref:
        raise ValueError("reason_ref 는 비어 있을 수 없다")
    _resolve_manifest(manifest_port, qualification_profile_id)  # integrity 확인(수정하지 않음)
    with fence(qualification_profile_id):
        return _revoke_under_fence(
            store, qualification_profile_id, request_id, reason_ref, now
        )


# ─── admission query ports ───────────────────────────────────────────────────────
def read_qualification_profile_admission_under_fence(
    store: ProfileAdmissionStore, qualification_profile_id: str
) -> QualificationProfileAdmissionObservation:
    """authoritative under-fence read — caller 가 exact profile id 를 알고 ProfileFence 를 보유한다.

    latest Profile 을 검색하거나 fence 를 재획득하지 않는다. state 없으면 context error.
    """
    if not store.exists(qualification_profile_id):
        raise ProfileAdmissionStateMissing(
            f"profile {qualification_profile_id} admission state 없음"
        )
    stored = store.load(qualification_profile_id)
    return observe_chain(stored.qualification_profile_id, stored.decisions)


def read_qualification_profile_admission_summary(
    store: ProfileAdmissionStore, qualification_profile_id: str
) -> QualificationProfileAdmissionObservation | None:
    """outside-fence optimistic discovery summary — 없으면 None. authoritative 는 under-fence.

    fence 를 잡지 않아 관찰 직후 값이 바뀔 수 있다(discovery 전용). 손상은 fail-closed.
    """
    stored = store.load_summary(qualification_profile_id)
    if stored is None:
        return None
    return observe_chain(stored.qualification_profile_id, stored.decisions)
