"""Profile admission domain(S5-08 · #704): digest·decision chain·전이·투영 불변식."""

from __future__ import annotations

import pytest

from hwpxfiller.domain.qualification_profile_admission import (
    ADMITTED,
    REVOKED,
    AdmissionDecision,
    ProfileAdmissionIntegrityError,
    command_fingerprint,
    decision_ref,
    observe_chain,
    policy_observation_digest,
    validate_decision_chain,
)


def _decision(pid: str, version: int, state: str, req: str = "r") -> AdmissionDecision:
    return AdmissionDecision(
        policy_version=version,
        state=state,
        decision_ref=decision_ref(pid, version),
        request_id=req,
        reason_ref=None,
        decided_at="t",
    )


# ── digest: 정의역과 제외 ────────────────────────────────────────────────────────
def test_observation_digest_binds_the_four_inputs() -> None:
    base = policy_observation_digest("P", 2, REVOKED, "P@v2")
    assert base.startswith("sha256:")
    assert base != policy_observation_digest("P", 3, REVOKED, "P@v2")  # version
    assert base != policy_observation_digest("P", 2, ADMITTED, "P@v2")  # state
    assert base != policy_observation_digest("Q", 2, REVOKED, "P@v2")  # profile
    assert base != policy_observation_digest("P", 2, REVOKED, "P@v3")  # decision ref


def test_observation_digest_rejects_unknown_state() -> None:
    with pytest.raises(ProfileAdmissionIntegrityError):
        policy_observation_digest("P", 1, "MYSTERY", "P@v1")


def test_fingerprint_differs_by_kind_and_parts() -> None:
    a = command_fingerprint("REVOKE", "P", "reason-1")
    assert a != command_fingerprint("REVOKE", "P", "reason-2")  # different reason
    assert a != command_fingerprint("INITIALIZE", "P", "reason-1")  # different kind
    assert a == command_fingerprint("REVOKE", "P", "reason-1")  # deterministic


# ── decision chain 불변식 ────────────────────────────────────────────────────────
def test_admitted_to_revoked_chain_valid_and_observed() -> None:
    chain = (_decision("P", 1, ADMITTED), _decision("P", 2, REVOKED))
    validate_decision_chain("P", chain)
    obs = observe_chain("P", chain)
    assert obs.state == REVOKED and obs.policy_version == 2
    assert obs.current_decision_ref == "P@v2"
    assert obs.policy_observation_digest == policy_observation_digest("P", 2, REVOKED, "P@v2")


def test_empty_chain_rejected() -> None:
    with pytest.raises(ProfileAdmissionIntegrityError):
        validate_decision_chain("P", ())


def test_non_monotonic_version_rejected() -> None:
    chain = (_decision("P", 1, ADMITTED), _decision("P", 3, REVOKED))
    with pytest.raises(ProfileAdmissionIntegrityError):
        validate_decision_chain("P", chain)


def test_mismatched_decision_ref_rejected() -> None:
    bad = AdmissionDecision(1, ADMITTED, "wrong-ref", "r", None, "t")
    with pytest.raises(ProfileAdmissionIntegrityError):
        validate_decision_chain("P", (bad,))


@pytest.mark.parametrize(
    "first,second",
    [(REVOKED, ADMITTED), (REVOKED, REVOKED), (ADMITTED, ADMITTED)],
)
def test_forbidden_transitions_rejected(first: str, second: str) -> None:
    chain = (_decision("P", 1, first), _decision("P", 2, second))
    with pytest.raises(ProfileAdmissionIntegrityError):
        validate_decision_chain("P", chain)


def test_lone_surrogate_rejected() -> None:
    with pytest.raises(ProfileAdmissionIntegrityError):
        policy_observation_digest("\ud800", 1, ADMITTED, "P@v1")  # lone surrogate


def test_policy_version_beyond_u32_rejected() -> None:
    with pytest.raises(ProfileAdmissionIntegrityError):
        policy_observation_digest("P", 2**33, ADMITTED, "P@v1")


def test_decision_rejects_unknown_state_and_empty_fields() -> None:
    with pytest.raises(ProfileAdmissionIntegrityError):
        AdmissionDecision(1, "NOPE", "P@v1", "r", None, "t")
    with pytest.raises(ProfileAdmissionIntegrityError):
        AdmissionDecision(1, ADMITTED, "P@v1", "", None, "t")  # empty request_id
    with pytest.raises(ProfileAdmissionIntegrityError):
        AdmissionDecision(0, ADMITTED, "P@v1", "r", None, "t")  # non-positive version
