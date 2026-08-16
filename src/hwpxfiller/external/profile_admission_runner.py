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
    ProfileAdmissionIntegrityError,
    ProfileAdmissionStateMissing,
    QualificationProfileAdmissionObservation,
    command_fingerprint,
    decision_ref,
    observe_chain,
    policy_observation_digest,
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


def _resolve_revocation(
    revocation_port: ProfileRevocationRecordReadPort, profile_id: str
) -> QualificationProfileRevocation | None:
    """historical revocation record 를 profile 결속까지 검증해 읽는다(finding 2).

    반환 record 의 profile 이 요청 profile 과 다르면 남의 record 로 REVOKED bootstrap 하는
    것이라 fail-closed(manifest port 의 key-binding 검사와 같은 규율).
    """
    revocation = revocation_port.get_revocation(profile_id)
    if revocation is not None and revocation.qualification_profile_id != profile_id:
        raise ProfileAdmissionIntegrityError(
            f"revocation record 의 profile 결속 불일치: 요청 {profile_id}, "
            f"record {revocation.qualification_profile_id}"
        )
    return revocation


def _verify_bound_digest(
    stored: StoredProfileAdmission, manifest: QualificationProfileManifest
) -> None:
    """이미 등록된 aggregate 의 bound manifest digest 가 지금 resolve 된 것과 같은지 확인(finding 3).

    같은 profile ID 가 다른 manifest digest 로 재등록되면 idempotent 성공처럼 보이면 안 된다 —
    reused ID 가 다른 semantics 에 결속된 것이므로 integrity error 로 시끄럽게 닫는다.
    """
    if stored.bound_manifest_digest != manifest.manifest_digest:
        raise ProfileManifestIntegrityError(
            f"profile {stored.qualification_profile_id} 는 다른 manifest digest 로 이미 등록됨"
            f"(stored {stored.bound_manifest_digest}, resolved {manifest.manifest_digest})"
        )


def _observation_from_outcome(
    profile_id: str, outcome: AdmissionOutcome
) -> QualificationProfileAdmissionObservation:
    """durable first-seen outcome 그대로 관찰을 복원한다(finding 1).

    replay 는 최초 outcome 을 재생하는 것이라, 이후 revocation 이 있었더라도 그 최초 outcome 이
    가리키던 version/state/decision_ref 로 관찰을 세운다 — current chain 으로 재조립하지 않는다
    (안 그러면 INITIALIZED_ADMITTED outcome 에 REVOKED 관찰이 붙는 내부 모순이 생긴다).
    """
    return QualificationProfileAdmissionObservation(
        qualification_profile_id=profile_id,
        policy_version=outcome.resulting_policy_version,
        state=outcome.resulting_state,
        current_decision_ref=outcome.current_decision_ref,
        policy_observation_digest=policy_observation_digest(
            profile_id,
            outcome.resulting_policy_version,
            outcome.resulting_state,
            outcome.current_decision_ref,
        ),
    )


def _replay_or_reject(
    stored: StoredProfileAdmission, request_id: str, fingerprint: str
) -> AdmissionCommandResult | None:
    """stored request 를 fence 안에서 먼저 상의한다(finding 5) — port 해결 없이 replay/거절.

    seen + 같은 fingerprint → 최초 durable outcome replay(외부 의존성 없이). seen + 다른
    fingerprint → KEY_REUSED. unseen → None(caller 가 port 를 해결해 진행). fingerprint 는
    caller 제공 입력만으로 만들어 port 가 잠시 불가해도 idempotent retry 가 성립한다.
    """
    existing = find_request(stored, request_id)
    if existing is None:
        return None
    if existing.command_fingerprint != fingerprint:
        raise AdmissionIdempotencyKeyReused(
            f"request {request_id} 가 다른 fingerprint 로 재사용됨"
        )
    return AdmissionCommandResult(
        existing.terminal_outcome.outcome_code,
        _observation_from_outcome(stored.qualification_profile_id, existing.terminal_outcome),
        replayed=True,
    )


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
    """UNSEEN request 를 이미 존재하는 aggregate 에 얹는다(replay/거절은 caller 가 이미 처리).

    first-seen ledger(+선택적 decision)를 한 aggregate commit 으로 쓴다.
    """
    profile_id = stored.qualification_profile_id
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
    manifest_port: ProfileManifestReadPort,
    revocation_port: ProfileRevocationRecordReadPort,
    profile_id: str,
    request_id: str,
    now: str,
) -> AdmissionCommandResult:
    # fingerprint 는 caller 입력(profile)만 — port 없이 replay 판정 가능(finding 5).
    fingerprint = command_fingerprint("INITIALIZE", profile_id)
    if store.exists(profile_id):
        stored = store.load(profile_id)
        replay = _replay_or_reject(stored, request_id, fingerprint)
        if replay is not None:  # seen → durable outcome replay(port 불필요)
            return replay
        # unseen onto existing → manifest 결속 확인 후 idempotent ALREADY_INITIALIZED.
        _verify_bound_digest(stored, _resolve_manifest(manifest_port, profile_id))
        return _record_onto_existing(
            store, stored, request_id, fingerprint, ALREADY_INITIALIZED, None, now
        )
    # no aggregate → 이제서야 external port 를 해결한다(finding 5).
    manifest = _resolve_manifest(manifest_port, profile_id)
    revocation = _resolve_revocation(revocation_port, profile_id)
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
    # fence 를 먼저 잡고, stored request replay 를 port 해결보다 앞에 둔다(finding 5).
    with fence(qualification_profile_id):
        return _initialize_under_fence(
            store, manifest_port, revocation_port, qualification_profile_id, request_id, now
        )


# ─── RegisterPublishedQualificationProfileAdmission ──────────────────────────────
def _register_under_fence(
    store: ProfileAdmissionStore,
    manifest_port: ProfileManifestReadPort,
    profile_ref: str,
    initial_decision: str,
    request_id: str,
    now: str,
) -> AdmissionCommandResult:
    # fingerprint 는 caller 입력(ref + 명시 decision)만 — port 없이 replay 판정(finding 5).
    fingerprint = command_fingerprint("REGISTER", profile_ref, initial_decision)
    if store.exists(profile_ref):
        stored = store.load(profile_ref)
        replay = _replay_or_reject(stored, request_id, fingerprint)
        if replay is not None:
            return replay
        # 같은 ID 를 다른 manifest digest 로 재등록하면 성공처럼 보이면 안 된다(finding 3).
        _verify_bound_digest(stored, _resolve_manifest(manifest_port, profile_ref))
        return _record_onto_existing(
            store, stored, request_id, fingerprint, ALREADY_INITIALIZED, None, now
        )
    manifest = _resolve_manifest(manifest_port, profile_ref)
    outcome_code = (
        REGISTERED_ADMITTED if initial_decision == ADMITTED else REGISTERED_REVOKED
    )
    return _bootstrap(
        store, profile_ref, manifest.manifest_digest, initial_decision, request_id,
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
    fence key 는 caller 가 명시한 exact manifest ref(= profile id)라 port 없이 잡는다.
    """
    if not request_id:
        raise ValueError("request_id 는 비어 있을 수 없다")
    if initial_decision not in (ADMITTED, REVOKED):
        raise ValueError(f"initial_decision 은 ADMITTED|REVOKED 여야 한다: {initial_decision!r}")
    with fence(exact_profile_manifest_ref):
        return _register_under_fence(
            store, manifest_port, exact_profile_manifest_ref,
            initial_decision, request_id, now,
        )


# ─── RevokeQualificationProfile ──────────────────────────────────────────────────
def _revoke_under_fence(
    store: ProfileAdmissionStore,
    manifest_port: ProfileManifestReadPort,
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
    # fingerprint 는 caller 입력(profile + reason)만 — port 없이 replay 판정(finding 5).
    fingerprint = command_fingerprint("REVOKE", profile_id, reason_ref)
    replay = _replay_or_reject(stored, request_id, fingerprint)
    if replay is not None:
        return replay
    # unseen → 이제서야 manifest 를 해결·결속 확인(수정하지 않음).
    _verify_bound_digest(stored, _resolve_manifest(manifest_port, profile_id))
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
    with fence(qualification_profile_id):
        return _revoke_under_fence(
            store, manifest_port, qualification_profile_id, request_id, reason_ref, now
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
