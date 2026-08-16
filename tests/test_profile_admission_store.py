"""Profile admission store(S5-08 · #704): create-once·CAS·append-only·fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.domain.qualification_profile_admission import (
    ADMITTED,
    REVOKED,
    AdmissionDecision,
    decision_ref,
)
from hwpxfiller.application.stored_profile_admission import (
    AdmissionIdempotencyRecord,
    AdmissionOutcome,
    bootstrap_stored,
    commit_next,
)
from hwpxfiller.external.profile_admission_store import (
    AdmissionAggregateConflict,
    AdmissionAggregateExists,
    AdmissionAggregateNotFound,
    AdmissionIntegrityError,
    AdmissionSchemaUnsupported,
    ProfileAdmissionStore,
    ProfileAdmissionStoreError,
)


def _outcome(code: str, version: int, state: str) -> AdmissionOutcome:
    return AdmissionOutcome(code, version, state, decision_ref("P", version))


def _bootstrap(pid: str = "P", state: str = ADMITTED):
    return bootstrap_stored(
        qualification_profile_id=pid,
        bound_manifest_digest="sha256:m",
        decision=AdmissionDecision(1, state, decision_ref(pid, 1), "req-1", None, "t"),
        record=AdmissionIdempotencyRecord(
            "req-1", "fp-1", AdmissionOutcome("INIT", 1, state, decision_ref(pid, 1)), "t"
        ),
    )


def _revoked_next(stored):
    revoke = AdmissionDecision(2, REVOKED, decision_ref("P", 2), "req-2", "reason", "t")
    return commit_next(
        stored, new_decision=revoke, record=AdmissionIdempotencyRecord(
            "req-2", "fp-2", _outcome("REVOKED", 2, REVOKED), "t"
        )
    )


def test_create_load_roundtrip(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    stored = _bootstrap()
    store.create(stored)
    assert store.exists("P")
    assert store.load("P") == stored


def test_create_once_rejects_second_create(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    store.create(_bootstrap())
    with pytest.raises(AdmissionAggregateExists):
        store.create(_bootstrap())


def test_commit_cas_and_conflict(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    stored = _bootstrap()
    store.create(stored)
    store.commit("P", 1, _revoked_next(stored))
    assert store.load("P").current_state == REVOKED
    # stale expected version → CONCURRENT_MODIFICATION
    with pytest.raises(AdmissionAggregateConflict) as exc:
        store.commit("P", 1, _revoked_next(stored))
    assert exc.value.code == "STORE_CONCURRENT_MODIFICATION"


def test_commit_rejects_history_rewrite(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    a = _bootstrap()
    store.create(a)
    # 다른 첫 decision(request_id 다름)으로 chain 을 갈아치우려는 commit → append-only 위반.
    b = bootstrap_stored(
        qualification_profile_id="P",
        bound_manifest_digest="sha256:m",
        decision=AdmissionDecision(1, ADMITTED, decision_ref("P", 1), "OTHER", None, "t"),
        record=AdmissionIdempotencyRecord(
            "OTHER", "fp-x", AdmissionOutcome("INIT", 1, ADMITTED, "P@v1"), "t"
        ),
    )
    import dataclasses

    forged = dataclasses.replace(b, aggregate_version=2)
    with pytest.raises(Exception):  # noqa: B017 — history rewrite 는 loud 거절이면 충분
        store.commit("P", 1, forged)


def test_load_missing_is_state_missing(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    with pytest.raises(AdmissionAggregateNotFound) as exc:
        store.load("absent")
    assert exc.value.code == "QUALIFICATION_PROFILE_ADMISSION_STATE_MISSING"


def test_summary_none_and_present(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    assert store.load_summary("absent") is None
    store.create(_bootstrap())
    assert store.load_summary("P").current_state == ADMITTED


def test_corrupt_digest_fail_closed(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    store.create(_bootstrap())
    path = tmp_path / "P.json"
    envelope = json.loads(path.read_text("utf-8"))
    envelope["content"]["aggregate_version"] = 99  # digest 와 어긋나게 손상
    path.write_text(json.dumps(envelope), "utf-8")
    with pytest.raises(AdmissionIntegrityError):
        store.load("P")


def test_broken_json_fail_closed(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    (tmp_path / "P.json").write_text("{not json", "utf-8")
    with pytest.raises(AdmissionIntegrityError):
        store.load("P")


def test_unknown_schema_fail_closed(tmp_path: Path) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest

    store = ProfileAdmissionStore(tmp_path)
    content = {"schema_version": "alien-v1"}
    (tmp_path / "P.json").write_text(
        json.dumps({"digest": content_digest(content), "content": content}), "utf-8"
    )
    with pytest.raises(AdmissionSchemaUnsupported):
        store.load("P")


def test_wrong_profile_binding_fail_closed(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    store.create(_bootstrap("P"))
    # P.json 을 Q.json 으로 복사하면 digest 는 통과해도 key 결속이 깨진다.
    (tmp_path / "Q.json").write_text((tmp_path / "P.json").read_text("utf-8"), "utf-8")
    with pytest.raises(AdmissionIntegrityError):
        store.load("Q")


def test_rejects_unsafe_profile_id(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    with pytest.raises(Exception):  # noqa: B017 — 경로 문자 거절
        store.exists("../escape")


def test_writer_lock_reused_for_same_key() -> None:
    from hwpxfiller.external.profile_admission_store import _lock

    a = _lock("k")  # 강한 참조를 잡아 WeakValueDictionary 항목을 살려 둔다
    assert _lock("k") is a  # 같은 key → 같은 lock object


def test_create_requires_version_one(tmp_path: Path) -> None:
    import dataclasses

    store = ProfileAdmissionStore(tmp_path)
    with pytest.raises(ProfileAdmissionStoreError):
        store.create(dataclasses.replace(_bootstrap(), aggregate_version=2))


def test_envelope_not_dict_fail_closed(tmp_path: Path) -> None:
    store = ProfileAdmissionStore(tmp_path)
    (tmp_path / "P.json").write_text("[]", "utf-8")
    with pytest.raises(AdmissionIntegrityError):
        store.load("P")


def test_content_not_dict_fail_closed(tmp_path: Path) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest

    store = ProfileAdmissionStore(tmp_path)
    envelope = {"digest": content_digest("x"), "content": "x"}  # digest 는 맞지만 content 가 str
    (tmp_path / "P.json").write_text(json.dumps(envelope), "utf-8")
    with pytest.raises(AdmissionIntegrityError):
        store.load("P")


def test_decodable_but_invalid_chain_fail_closed(tmp_path: Path) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest
    from hwpxfiller.application.stored_profile_admission import STORE_SCHEMA_VERSION

    store = ProfileAdmissionStore(tmp_path)
    content = {"schema_version": STORE_SCHEMA_VERSION, "decisions": [], "processed_requests": []}
    (tmp_path / "P.json").write_text(
        json.dumps({"digest": content_digest(content), "content": content}), "utf-8"
    )
    with pytest.raises(AdmissionIntegrityError):
        store.load("P")


def test_commit_guards(tmp_path: Path) -> None:
    import dataclasses

    store = ProfileAdmissionStore(tmp_path)
    stored = _bootstrap()
    store.create(stored)
    nxt = _revoked_next(stored)  # valid version-2 successor
    # 다른 Profile 로 교체 금지(별도 valid Q aggregate 를 P 파일에 commit)
    with pytest.raises(ProfileAdmissionStoreError):
        store.commit("P", 1, _bootstrap("Q"))
    # version 을 정확히 +1 이 아니게
    with pytest.raises(ProfileAdmissionStoreError):
        store.commit("P", 1, dataclasses.replace(nxt, aggregate_version=9))
    # bound manifest 변경 금지
    with pytest.raises(ProfileAdmissionStoreError):
        store.commit("P", 1, dataclasses.replace(nxt, bound_manifest_digest="sha256:other"))


def test_commit_rejects_ledger_reordering(tmp_path: Path) -> None:
    import dataclasses

    store = ProfileAdmissionStore(tmp_path)
    stored = _bootstrap()
    store.create(stored)
    nxt = _revoked_next(stored)  # processed_requests = (req-1, req-2)
    # 두 record 를 뒤바꾸면 aggregate 는 여전히 valid(둘 다 존재)하지만 ledger prefix 가 깨진다
    # → store 의 append-only 가 잡는다(truncation 은 aggregate 불변식이 먼저 잡는다).
    reordered = dataclasses.replace(
        nxt, processed_requests=(nxt.processed_requests[1], nxt.processed_requests[0])
    )
    with pytest.raises(ProfileAdmissionStoreError):
        store.commit("P", 1, reordered)
