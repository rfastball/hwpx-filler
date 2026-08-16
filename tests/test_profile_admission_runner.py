"""Profile admission command 결선(S5-08 · #704): bootstrap/register/revoke·idempotency·semantics split."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hwpxfiller.application.qualification_evidence import (
    QualificationProfileManifest,
    QualificationProfileRevocation,
    build_manifest,
)
from hwpxfiller.domain.qualification_profile_admission import (
    ADMITTED,
    REVOKED,
    ProfileAdmissionStateMissing,
)
from hwpxfiller.external.profile_admission_runner import (
    ALREADY_INITIALIZED,
    ALREADY_REVOKED,
    INITIALIZED_ADMITTED,
    INITIALIZED_REVOKED,
    REGISTERED_ADMITTED,
    AdmissionIdempotencyKeyReused,
    ProfileManifestIntegrityError,
    initialize_qualification_profile_admission,
    read_qualification_profile_admission_summary,
    read_qualification_profile_admission_under_fence,
    register_published_qualification_profile_admission,
    revoke_qualification_profile,
)
from hwpxfiller.external.profile_admission_store import ProfileAdmissionStore


def _manifest(pid: str) -> QualificationProfileManifest:
    return build_manifest(
        qualification_profile_id=pid,
        media="hwpx",
        adapter_contract_version="a1",
        product_rule_version="p1",
        operation_alphabet_version="o1",
        projection_schema_version="hwpx-structure-projection-v1",
        manifest_payload={"k": pid},
        created_at="t",
    )


class FakeManifestPort:
    def __init__(self, manifests: dict[str, QualificationProfileManifest | None]) -> None:
        self._m = manifests

    def get_manifest(self, pid: str) -> QualificationProfileManifest:
        if pid not in self._m:
            raise KeyError(pid)
        return self._m[pid]  # type: ignore[return-value]


class FakeRevocationPort:
    def __init__(self, revoked: dict[str, QualificationProfileRevocation]) -> None:
        self._r = revoked

    def get_revocation(self, pid: str) -> QualificationProfileRevocation | None:
        return self._r.get(pid)


def _store(tmp_path: Path) -> ProfileAdmissionStore:
    return ProfileAdmissionStore(tmp_path)


def _init(store, pid="P", revoked=None, request_id="req-init"):
    return initialize_qualification_profile_admission(
        store,
        FakeManifestPort({pid: _manifest(pid)}),
        FakeRevocationPort(revoked or {}),
        qualification_profile_id=pid,
        request_id=request_id,
        now="t0",
    )


# ── initialization / registration ───────────────────────────────────────────────
def test_init_existing_manifest_no_revocation_is_admitted_v1(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = _init(store)
    assert result.outcome_code == INITIALIZED_ADMITTED
    assert result.observation.state == ADMITTED
    assert result.observation.policy_version == 1


def test_init_with_historical_revocation_is_revoked_v1(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rev = QualificationProfileRevocation("P", "bad", "auth", "t")
    result = _init(store, revoked={"P": rev})
    assert result.outcome_code == INITIALIZED_REVOKED
    assert result.observation.state == REVOKED and result.observation.policy_version == 1


def test_runtime_query_without_state_is_context_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ProfileAdmissionStateMissing) as exc:
        read_qualification_profile_admission_under_fence(store, "P")
    assert exc.value.code == "QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING"


def test_manifest_missing_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    port = FakeManifestPort({})  # get_manifest raises KeyError
    with pytest.raises(ProfileManifestIntegrityError):
        initialize_qualification_profile_admission(
            store, port, FakeRevocationPort({}),
            qualification_profile_id="P", request_id="r", now="t",
        )


def test_manifest_profile_mismatch_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    port = FakeManifestPort({"P": None})  # None binding
    with pytest.raises(ProfileManifestIntegrityError):
        initialize_qualification_profile_admission(
            store, port, FakeRevocationPort({}),
            qualification_profile_id="P", request_id="r", now="t",
        )


def test_publication_without_registration_has_no_admission_state(tmp_path: Path) -> None:
    # Manifest 는 존재해도(port 가 해결) registration 전에는 admission summary 가 0(None)이다.
    store = _store(tmp_path)
    assert read_qualification_profile_admission_summary(store, "P") is None


def test_registration_binds_exact_manifest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    manifest = _manifest("P")
    result = register_published_qualification_profile_admission(
        store, FakeManifestPort({"P": manifest}),
        exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-1", now="t",
    )
    assert result.outcome_code == REGISTERED_ADMITTED
    assert store.load("P").bound_manifest_digest == manifest.manifest_digest


def test_registration_initial_decision_validated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        register_published_qualification_profile_admission(
            store, FakeManifestPort({"P": _manifest("P")}),
            exact_profile_manifest_ref="P", initial_decision="MAYBE",
            request_id="reg-1", now="t",
        )


def _other_manifest(pid: str = "P") -> QualificationProfileManifest:
    return build_manifest(
        qualification_profile_id=pid, media="hwpx", adapter_contract_version="a1",
        product_rule_version="p1", operation_alphabet_version="o1",
        projection_schema_version="hwpx-structure-projection-v1",
        manifest_payload={"k": "DIFFERENT"}, created_at="t",
    )


def test_idempotent_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _init(store, request_id="req-A")
    replay = _init(store, request_id="req-A")  # 같은 request → replay
    assert replay.replayed and replay.outcome_code == first.outcome_code


def test_reinit_with_different_manifest_digest_is_integrity_error(tmp_path: Path) -> None:
    # finding 3: 같은 ID 를 다른 manifest digest 로 재초기화(새 request) → integrity, 성공 위장 금지.
    store = _store(tmp_path)
    _init(store, request_id="req-A")
    with pytest.raises(ProfileManifestIntegrityError):
        initialize_qualification_profile_admission(
            store, FakeManifestPort({"P": _other_manifest()}), FakeRevocationPort({}),
            qualification_profile_id="P", request_id="req-B", now="t0",
        )


def test_reregister_with_different_manifest_digest_is_integrity_error(tmp_path: Path) -> None:
    # finding 3: register 도 stored bound digest 와 다르면 ALREADY_INITIALIZED 가 아니라 integrity.
    store = _store(tmp_path)
    register_published_qualification_profile_admission(
        store, FakeManifestPort({"P": _manifest("P")}),
        exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-1", now="t",
    )
    with pytest.raises(ProfileManifestIntegrityError):
        register_published_qualification_profile_admission(
            store, FakeManifestPort({"P": _other_manifest()}),
            exact_profile_manifest_ref="P", initial_decision=ADMITTED,
            request_id="reg-2", now="t",
        )


def test_register_key_reuse_on_different_initial_decision(tmp_path: Path) -> None:
    # 같은 request_id + 같은 ref 인데 다른 명시 initial_decision → KEY_REUSED.
    store = _store(tmp_path)
    port = FakeManifestPort({"P": _manifest("P")})
    register_published_qualification_profile_admission(
        store, port, exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-1", now="t",
    )
    with pytest.raises(AdmissionIdempotencyKeyReused):
        register_published_qualification_profile_admission(
            store, port, exact_profile_manifest_ref="P", initial_decision=REVOKED,
            request_id="reg-1", now="t",
        )


def test_revocation_record_profile_mismatch_fail_closed(tmp_path: Path) -> None:
    # finding 2: 남의 profile 을 가리키는 revocation record 로 REVOKED bootstrap 하지 않는다.
    store = _store(tmp_path)
    from hwpxfiller.domain.qualification_profile_admission import (
        ProfileAdmissionIntegrityError,
    )

    wrong = QualificationProfileRevocation("OTHER", "bad", "auth", "t")
    with pytest.raises(ProfileAdmissionIntegrityError):
        initialize_qualification_profile_admission(
            store, FakeManifestPort({"P": _manifest("P")}),
            FakeRevocationPort({"P": wrong}),
            qualification_profile_id="P", request_id="r", now="t",
        )


def test_replay_does_not_touch_ports(tmp_path: Path) -> None:
    # finding 5: seen request 는 fence 안에서 stored 로만 replay — port 가 죽어도 성립한다.
    store = _store(tmp_path)
    _init(store, request_id="req-A")

    class ExplodingManifestPort:
        def get_manifest(self, pid: str):
            raise RuntimeError("port down")

    class ExplodingRevocationPort:
        def get_revocation(self, pid: str):
            raise RuntimeError("port down")

    replay = initialize_qualification_profile_admission(
        store, ExplodingManifestPort(), ExplodingRevocationPort(),
        qualification_profile_id="P", request_id="req-A", now="t0",
    )
    assert replay.replayed and replay.outcome_code == INITIALIZED_ADMITTED


def test_replay_reflects_first_outcome_not_current_chain(tmp_path: Path) -> None:
    # finding 1: 이후 revocation 이 있어도 최초 Initialize replay 는 그 최초 outcome/관찰을 낸다.
    store = _store(tmp_path)
    _init(store, request_id="req-A")
    _revoke(store, request_id="rev-1")  # 이후 REVOKED
    replay = _init(store, request_id="req-A")
    assert replay.replayed
    assert replay.outcome_code == INITIALIZED_ADMITTED  # 최초 outcome
    assert replay.observation.state == ADMITTED  # current(REVOKED) 가 아니라 최초 관찰
    assert replay.observation.policy_version == 1


def test_second_request_onto_existing_is_already_initialized(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store, request_id="req-A")
    again = _init(store, request_id="req-B")  # 다른 request, 이미 bootstrap 됨
    assert again.outcome_code == ALREADY_INITIALIZED and not again.replayed


# ── revocation ──────────────────────────────────────────────────────────────────
def _revoke(store, pid="P", request_id="rev-1", reason="reason-1"):
    return revoke_qualification_profile(
        store, FakeManifestPort({pid: _manifest(pid)}),
        qualification_profile_id=pid, request_id=request_id,
        reason_ref=reason, now="t1",
    )


def test_revoke_admitted_increments_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    result = _revoke(store)
    assert result.outcome_code == "REVOKED"
    assert result.observation.state == REVOKED and result.observation.policy_version == 2
    stored = store.load("P")
    assert len(stored.decisions) == 2 and stored.aggregate_version == 2


def test_revoke_missing_state_is_context_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ProfileAdmissionStateMissing):
        _revoke(store)  # initialize/register 없이 revoke 불가


def test_revoke_same_request_replays(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    a = _revoke(store, request_id="rev-1")
    b = _revoke(store, request_id="rev-1")
    assert b.replayed and b.outcome_code == a.outcome_code


def test_revoke_different_fingerprint_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    _revoke(store, request_id="rev-1", reason="reason-1")
    with pytest.raises(AdmissionIdempotencyKeyReused):
        _revoke(store, request_id="rev-1", reason="reason-DIFFERENT")


def test_already_revoked_is_deterministic_terminal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    _revoke(store, request_id="rev-1")
    again = _revoke(store, request_id="rev-2")  # 다른 request
    assert again.outcome_code == ALREADY_REVOKED
    assert again.observation.state == REVOKED
    assert len(store.load("P").decisions) == 2  # 새 decision append 없음


def test_concurrent_revoke_first_commit_wins(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(req: str) -> None:
        res = _revoke(store, request_id=req)
        with lock:
            outcomes.append(res.outcome_code)

    threads = [threading.Thread(target=worker, args=(f"rev-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(3)
    # fence 가 직렬화 → 정확히 하나는 REVOKED, 나머지는 ALREADY_REVOKED.
    assert sorted(outcomes) == ["ALREADY_REVOKED", "REVOKED"]
    assert len(store.load("P").decisions) == 2


# ── semantics / policy split + persistence ────────────────────────────────────────
def test_revocation_does_not_touch_bound_manifest(tmp_path: Path) -> None:
    # revocation 은 policy 만 바꾼다 — bound manifest(semantic identity) digest 는 불변.
    store = _store(tmp_path)
    _init(store)
    before = store.load("P").bound_manifest_digest
    _revoke(store)
    assert store.load("P").bound_manifest_digest == before


def test_restart_full_restoration(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    _revoke(store)
    fresh = ProfileAdmissionStore(tmp_path)  # 새 인스턴스 = restart
    obs = read_qualification_profile_admission_under_fence(fresh, "P")
    assert obs.state == REVOKED and obs.policy_version == 2


def test_summary_reflects_current_after_revoke(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _init(store)
    _revoke(store)
    summary = read_qualification_profile_admission_summary(store, "P")
    assert summary is not None and summary.state == REVOKED


def test_register_same_request_replays(tmp_path: Path) -> None:
    store = _store(tmp_path)
    port = FakeManifestPort({"P": _manifest("P")})
    first = register_published_qualification_profile_admission(
        store, port, exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-1", now="t",
    )
    replay = register_published_qualification_profile_admission(
        store, port, exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-1", now="t",
    )
    assert replay.replayed and replay.outcome_code == first.outcome_code


def test_register_onto_existing_is_already_initialized(tmp_path: Path) -> None:
    store = _store(tmp_path)
    port = FakeManifestPort({"P": _manifest("P")})
    register_published_qualification_profile_admission(
        store, port, exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-1", now="t",
    )
    again = register_published_qualification_profile_admission(
        store, port, exact_profile_manifest_ref="P", initial_decision=ADMITTED,
        request_id="reg-2", now="t",
    )
    assert again.outcome_code == ALREADY_INITIALIZED


def test_empty_request_id_and_reason_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    port = FakeManifestPort({"P": _manifest("P")})
    with pytest.raises(ValueError):
        initialize_qualification_profile_admission(
            store, port, FakeRevocationPort({}),
            qualification_profile_id="P", request_id="", now="t",
        )
    with pytest.raises(ValueError):
        register_published_qualification_profile_admission(
            store, port, exact_profile_manifest_ref="P", initial_decision=ADMITTED,
            request_id="", now="t",
        )
    _init(store)  # revoke 의 request_id/reason guard 는 fence·state 진입 전에 선다
    with pytest.raises(ValueError):
        revoke_qualification_profile(
            store, port, qualification_profile_id="P", request_id="",
            reason_ref="r", now="t",
        )
    with pytest.raises(ValueError):
        revoke_qualification_profile(
            store, port, qualification_profile_id="P", request_id="rev-x",
            reason_ref="", now="t",
        )


def test_injected_fence_is_used(tmp_path: Path) -> None:
    store = _store(tmp_path)
    calls: list[str] = []
    from contextlib import contextmanager

    @contextmanager
    def spy_fence(pid: str):
        calls.append(pid)
        yield

    initialize_qualification_profile_admission(
        store, FakeManifestPort({"P": _manifest("P")}), FakeRevocationPort({}),
        qualification_profile_id="P", request_id="r", now="t", fence=spy_fence,
    )
    assert calls == ["P"]
