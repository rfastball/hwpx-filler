"""Profile admission aggregate(S5-08 · #704): 불변식·commit·idempotency·codec."""

from __future__ import annotations

import dataclasses

import pytest

from hwpxfiller.domain.qualification_profile_admission import (
    ADMITTED,
    REVOKED,
    AdmissionDecision,
    decision_ref,
    policy_observation_digest,
)
from hwpxfiller.application.stored_profile_admission import (
    AdmissionIdempotencyKeyReused,
    AdmissionIdempotencyRecord,
    AdmissionOutcome,
    StoredProfileAdmission,
    StoredProfileAdmissionError,
    bootstrap_stored,
    commit_next,
    decode_stored,
    encode_stored,
    find_request,
)


def _outcome(code: str, version: int, state: str, pid: str = "P") -> AdmissionOutcome:
    return AdmissionOutcome(code, version, state, decision_ref(pid, version))


def _record(req: str, fp: str, outcome: AdmissionOutcome) -> AdmissionIdempotencyRecord:
    return AdmissionIdempotencyRecord(req, fp, outcome, "t")


def _decision(pid: str, version: int, state: str, req: str = "r") -> AdmissionDecision:
    return AdmissionDecision(version, state, decision_ref(pid, version), req, None, "t")


def _bootstrap(state: str = ADMITTED) -> StoredProfileAdmission:
    return bootstrap_stored(
        qualification_profile_id="P",
        bound_manifest_digest="sha256:m",
        decision=_decision("P", 1, state, "req-1"),
        record=_record("req-1", "fp-1", _outcome("INITIALIZED", 1, state)),
    )


# ── bootstrap + 투영 ─────────────────────────────────────────────────────────────
def test_bootstrap_projects_current_state_from_chain() -> None:
    stored = _bootstrap(ADMITTED)
    assert stored.aggregate_version == 1
    assert stored.current_state == ADMITTED
    assert stored.current_decision_ref == "P@v1"
    assert stored.current_policy_observation_digest == policy_observation_digest(
        "P", 1, ADMITTED, "P@v1"
    )


def test_bootstrap_requires_version_one() -> None:
    with pytest.raises(StoredProfileAdmissionError):
        bootstrap_stored(
            qualification_profile_id="P",
            bound_manifest_digest="sha256:m",
            decision=_decision("P", 2, ADMITTED),
            record=_record("r", "fp", _outcome("X", 2, ADMITTED)),
        )


# ── commit_next: 전이·무전이·idempotency ─────────────────────────────────────────
def test_commit_next_appends_revoked_decision_and_bumps_version() -> None:
    stored = _bootstrap(ADMITTED)
    revoke = _decision("P", 2, REVOKED, "req-2")
    new = commit_next(
        stored,
        new_decision=revoke,
        record=_record("req-2", "fp-2", _outcome("REVOKED", 2, REVOKED)),
    )
    assert new.aggregate_version == 2
    assert new.current_state == REVOKED and len(new.decisions) == 2


def test_commit_next_without_decision_keeps_chain() -> None:
    stored = _bootstrap(REVOKED)
    new = commit_next(
        stored,
        new_decision=None,
        record=_record("req-2", "fp-2", _outcome("ALREADY_REVOKED", 1, REVOKED)),
    )
    assert new.aggregate_version == 2
    assert len(new.decisions) == 1 and new.current_state == REVOKED


def test_commit_next_same_request_same_fingerprint_replays() -> None:
    stored = _bootstrap(ADMITTED)
    same = commit_next(
        stored,
        new_decision=None,
        record=_record("req-1", "fp-1", _outcome("INITIALIZED", 1, ADMITTED)),
    )
    assert same is stored  # replay: 변경 없음


def test_commit_next_same_request_different_fingerprint_rejected() -> None:
    stored = _bootstrap(ADMITTED)
    with pytest.raises(AdmissionIdempotencyKeyReused):
        commit_next(
            stored,
            new_decision=None,
            record=_record("req-1", "fp-DIFFERENT", _outcome("X", 1, ADMITTED)),
        )


def test_find_request() -> None:
    stored = _bootstrap(ADMITTED)
    assert find_request(stored, "req-1") is not None
    assert find_request(stored, "absent") is None


# ── aggregate 불변식 ─────────────────────────────────────────────────────────────
def test_current_state_disagreeing_with_chain_is_integrity_error() -> None:
    stored = _bootstrap(ADMITTED)
    with pytest.raises(StoredProfileAdmissionError):
        dataclasses.replace(stored, current_state=REVOKED)  # tail 은 ADMITTED


def test_duplicate_request_id_rejected() -> None:
    stored = _bootstrap(ADMITTED)
    dup = _record("req-1", "fp-x", _outcome("X", 1, ADMITTED))
    with pytest.raises(StoredProfileAdmissionError):
        dataclasses.replace(stored, processed_requests=stored.processed_requests + (dup,))


def test_unknown_schema_rejected() -> None:
    stored = _bootstrap(ADMITTED)
    with pytest.raises(StoredProfileAdmissionError):
        dataclasses.replace(stored, schema_version="other-v9")


def test_outcome_and_record_field_validation() -> None:
    with pytest.raises(StoredProfileAdmissionError):
        AdmissionOutcome("", 1, ADMITTED, "P@v1")  # empty code
    with pytest.raises(StoredProfileAdmissionError):
        AdmissionOutcome("X", 0, ADMITTED, "P@v1")  # non-positive version
    with pytest.raises(StoredProfileAdmissionError):
        AdmissionIdempotencyRecord("r", "fp", "not-outcome", "t")  # type: ignore[arg-type]


# ── codec ───────────────────────────────────────────────────────────────────────
def test_codec_roundtrip_after_revoke() -> None:
    stored = commit_next(
        _bootstrap(ADMITTED),
        new_decision=_decision("P", 2, REVOKED, "req-2"),
        record=_record("req-2", "fp-2", _outcome("REVOKED", 2, REVOKED)),
    )
    assert decode_stored(encode_stored(stored)) == stored


@pytest.mark.parametrize(
    "payload",
    [
        "not-a-dict",
        {"decisions": "x", "processed_requests": []},
        {"decisions": [], "processed_requests": "x"},
    ],
)
def test_decode_rejects_malformed(payload: object) -> None:
    with pytest.raises(StoredProfileAdmissionError):
        decode_stored(payload)


def test_decode_rejects_broken_chain() -> None:
    good = encode_stored(_bootstrap(ADMITTED))
    good["decisions"][0]["policy_version"] = 5  # chain 검증이 잡는다(digest 밖 손상)
    with pytest.raises(StoredProfileAdmissionError):
        decode_stored(good)


def test_invalid_aggregate_version_rejected() -> None:
    with pytest.raises(StoredProfileAdmissionError):
        dataclasses.replace(_bootstrap(ADMITTED), aggregate_version=0)


def test_non_record_ledger_item_rejected() -> None:
    with pytest.raises(StoredProfileAdmissionError):
        dataclasses.replace(_bootstrap(ADMITTED), processed_requests=("not-a-record",))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "qualification-profile-admission-store-v1",
         "decisions": ["not-a-dict"], "processed_requests": []},
        {"schema_version": "qualification-profile-admission-store-v1",
         "decisions": [], "processed_requests": ["not-a-dict"]},
    ],
)
def test_decode_rejects_malformed_members(payload: dict) -> None:
    with pytest.raises(StoredProfileAdmissionError):
        decode_stored(payload)


def test_decode_rejects_invalid_decision_value() -> None:
    good = encode_stored(_bootstrap(ADMITTED))
    good["decisions"][0]["state"] = "NOPE"  # AdmissionDecision 값 불변식 위반
    with pytest.raises(StoredProfileAdmissionError):
        decode_stored(good)


def test_decode_rejects_malformed_outcome() -> None:
    good = encode_stored(_bootstrap(ADMITTED))
    good["processed_requests"][0]["terminal_outcome"] = "not-a-dict"
    with pytest.raises(StoredProfileAdmissionError):
        decode_stored(good)
