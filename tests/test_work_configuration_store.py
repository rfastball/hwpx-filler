"""S4-03(#673) durable Workspace identity·Work별 file-atomic S4 store·first-seen ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.application.stored_work_configuration import (
    STORE_SCHEMA_VERSION,
    IdempotencyKeyReused,
    IdempotencyRecord,
    StoredConfigurationError,
    TerminalOutcome,
    append_request,
    decode_stored,
    empty_stored,
    encode_stored,
    find_request,
)
from hwpxfiller.application.work_slot_configuration import (
    WorkSlotConfigurationAggregate,
    create_empty,
)
from hwpxfiller.external.work_configuration_store import (
    ConfigurationAggregateConflict,
    ConfigurationAggregateExists,
    ConfigurationAggregateNotFound,
    ConfigurationIntegrityError,
    ConfigurationSchemaUnsupported,
    WorkspaceIdentityIntegrityError,
    WorkspaceMetadataStore,
    WorkSlotConfigurationStore,
)

NOW = "2026-08-16T00:00:00Z"
WS = "ws-instance-1"


def _record(request_id: str = "req1", fingerprint: str = "fp-a") -> IdempotencyRecord:
    return IdempotencyRecord(
        request_id=request_id,
        fingerprint_schema_version="fp/v1",
        command_fingerprint=fingerprint,
        terminal_outcome=TerminalOutcome("A18", "APPLIED", True, 1, 2),
        request_actor_binding_digest="sha256:actor",
        recorded_at=NOW,
    )


# ── Workspace identity ────────────────────────────────────────────────────────
def test_workspace_id_is_create_once_and_stable_across_restart(tmp_path: Path) -> None:
    minted = iter(["id-A", "id-B"])
    store = WorkspaceMetadataStore(tmp_path)
    first = store.get_or_create(NOW, mint=lambda: next(minted))
    # 두 번째 호출·새 store 인스턴스(restart) 모두 mint 를 부르지 않고 같은 ID.
    assert store.get_or_create(NOW, mint=lambda: next(minted)) == first
    assert WorkspaceMetadataStore(tmp_path).read() == first
    assert first == "id-A"  # id-B 는 소비되지 않았다


def test_different_workspaces_get_different_ids(tmp_path: Path) -> None:
    a = WorkspaceMetadataStore(tmp_path / "a").get_or_create(NOW, mint=lambda: "id-A")
    b = WorkspaceMetadataStore(tmp_path / "b").get_or_create(NOW, mint=lambda: "id-B")
    assert a != b


def test_workspace_metadata_corruption_fails_closed(tmp_path: Path) -> None:
    store = WorkspaceMetadataStore(tmp_path)
    store.get_or_create(NOW, mint=lambda: "id-A")
    meta = tmp_path / "workspace.json"
    envelope = json.loads(meta.read_text("utf-8"))
    envelope["content"]["workspace_instance_id"] = "tampered"  # digest 재계산 안 함
    meta.write_text(json.dumps(envelope), "utf-8")
    with pytest.raises(WorkspaceIdentityIntegrityError):
        store.read()


# ── store ─────────────────────────────────────────────────────────────────────
def _store(tmp_path: Path) -> WorkSlotConfigurationStore:
    return WorkSlotConfigurationStore(tmp_path / "configs")


def test_create_once_rejects_second_create(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    assert store.exists("w1")
    with pytest.raises(ConfigurationAggregateExists):
        store.create(empty_stored(WS, "w1"))


def test_load_missing_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationAggregateNotFound):
        _store(tmp_path).load("nope")


def test_update_bumps_aggregate_version_and_persists_ledger(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    new = store.update("w1", 1, lambda cur: _bump(append_request(cur, _record())))
    assert new.aggregate_version == 2
    reloaded = store.load("w1")
    assert reloaded.aggregate_version == 2
    assert find_request(reloaded, "req1") is not None


def test_update_cas_conflict(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    store.update("w1", 1, lambda cur: _bump(append_request(cur, _record())))
    # 현재 version 은 2 인데 expected 1 로 다시 → CONFLICT(lost update 차단).
    with pytest.raises(ConfigurationAggregateConflict):
        store.update("w1", 1, lambda cur: _bump(cur))


def test_partial_temp_file_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    (tmp_path / "configs" / "w1.json.stale.tmp").write_text("{partial", "utf-8")
    assert store.load("w1").work_id == "w1"  # 최종 파일만 관찰


def test_mutate_exception_keeps_prior_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))

    def _boom(_cur: object) -> object:
        raise RuntimeError("mid-mutation")

    with pytest.raises(RuntimeError):
        store.update("w1", 1, _boom)  # type: ignore[arg-type]
    assert store.load("w1").aggregate_version == 1  # 무손상


def test_envelope_digest_corruption_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    path = tmp_path / "configs" / "w1.json"
    envelope = json.loads(path.read_text("utf-8"))
    envelope["content"]["aggregate_version"] = 99  # digest 재계산 안 함
    path.write_text(json.dumps(envelope), "utf-8")
    with pytest.raises(ConfigurationIntegrityError):
        store.load("w1")


def test_unknown_schema_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    path = tmp_path / "configs" / "w1.json"
    # content 를 바꾸고 digest 를 정직하게 재계산 → schema 만 미상.
    from hwpxfiller.application.qualification_evidence import content_digest

    envelope = json.loads(path.read_text("utf-8"))
    envelope["content"]["schema_version"] = "work-slot-configuration-store-v99"
    envelope["digest"] = content_digest(envelope["content"])
    path.write_text(json.dumps(envelope), "utf-8")
    with pytest.raises(ConfigurationSchemaUnsupported):
        store.load("w1")


def test_empty_tombstone_and_ledger_only_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # Configuration 없이 ledger record 만 있는 aggregate 도 존재·복원된다.
    ledger_only = _bump(append_request(empty_stored(WS, "w1"), _record()))
    store.create(empty_stored(WS, "w1"))
    result = store.update("w1", 1, lambda cur: ledger_only)
    reloaded = store.load("w1")
    assert reloaded == result
    assert len(reloaded.configurations.configurations) == 0  # ledger-only
    assert find_request(reloaded, "req1") is not None


# ── ledger ──────────────────────────────────────────────────────────────────
def test_ledger_at_most_one_and_replay_same_fingerprint() -> None:
    stored = empty_stored(WS, "w1")
    once = append_request(stored, _record())
    # 같은 request_id + 같은 fingerprint 재전송 = replay, 변화 없음.
    assert append_request(once, _record()) == once
    assert len(once.processed_requests) == 1


def test_ledger_reuse_different_fingerprint_rejected() -> None:
    stored = append_request(empty_stored(WS, "w1"), _record(fingerprint="fp-a"))
    with pytest.raises(IdempotencyKeyReused):
        append_request(stored, _record(fingerprint="fp-b"))


def test_stored_roundtrip_with_configuration_and_ledger() -> None:
    aggregate = WorkSlotConfigurationAggregate(
        "work-slot-configuration-v1", "w1", (create_empty("w1", "A18", NOW),)
    )
    from dataclasses import replace as dc_replace

    stored = dc_replace(
        empty_stored(WS, "w1"),
        configurations=aggregate,
        processed_requests=(_record(),),
    )
    assert decode_stored(encode_stored(stored)) == stored


def test_decode_rejects_unknown_store_schema() -> None:
    with pytest.raises(StoredConfigurationError):
        decode_stored(
            {
                "schema_version": "nope",
                "aggregate_version": 1,
                "workspace_instance_id": WS,
                "configurations": {
                    "schema_version": "work-slot-configuration-v1",
                    "work_id": "w1",
                    "configurations": [],
                },
                "processed_requests": [],
            }
        )


# ── value invariants (fail-closed) ────────────────────────────────────────────
def test_terminal_outcome_invariants() -> None:
    with pytest.raises(StoredConfigurationError):
        TerminalOutcome("", "APPLIED", True, None, None)  # empty application_id
    with pytest.raises(StoredConfigurationError):
        TerminalOutcome("A", "APPLIED", "yes", None, None)  # type: ignore[arg-type]
    with pytest.raises(StoredConfigurationError):
        TerminalOutcome("A", "APPLIED", True, 0, None)  # version < 1
    with pytest.raises(StoredConfigurationError):
        TerminalOutcome("A", "APPLIED", True, True, None)  # bool is not a version


def test_idempotency_record_invariants() -> None:
    with pytest.raises(StoredConfigurationError):
        IdempotencyRecord("", "fp/v1", "fp", _record().terminal_outcome, "d", NOW)
    with pytest.raises(StoredConfigurationError):
        IdempotencyRecord("r", "fp/v1", "fp", "not-outcome", "d", NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"aggregate_version": 1.5},
        {"aggregate_version": 0},
        {"workspace_instance_id": ""},
    ],
)
def test_stored_invariants(kwargs: dict) -> None:
    from dataclasses import replace as dc_replace

    with pytest.raises(StoredConfigurationError):
        dc_replace(empty_stored(WS, "w1"), **kwargs)


def test_stored_rejects_duplicate_request_id() -> None:
    from dataclasses import replace as dc_replace

    rec = _record()
    with pytest.raises(StoredConfigurationError):
        dc_replace(empty_stored(WS, "w1"), processed_requests=(rec, rec))


@pytest.mark.parametrize(
    "data",
    [
        "not-a-dict",
        {"schema_version": STORE_SCHEMA_VERSION, "processed_requests": "x"},
        {
            "schema_version": STORE_SCHEMA_VERSION,
            "aggregate_version": 1,
            "workspace_instance_id": WS,
            "configurations": "not-a-dict",
            "processed_requests": [],
        },
    ],
)
def test_decode_stored_malformed_rejected(data: object) -> None:
    with pytest.raises(StoredConfigurationError):
        decode_stored(data)


def test_decode_record_and_outcome_malformed_rejected() -> None:
    from dataclasses import replace as dc_replace

    good = encode_stored(
        dc_replace(empty_stored(WS, "w1"), processed_requests=(_record(),))
    )
    bad_record = json.loads(json.dumps(good))
    bad_record["processed_requests"][0] = "not-a-dict"
    with pytest.raises(StoredConfigurationError):
        decode_stored(bad_record)
    bad_outcome = json.loads(json.dumps(good))
    bad_outcome["processed_requests"][0]["terminal_outcome"] = "not-a-dict"
    with pytest.raises(StoredConfigurationError):
        decode_stored(bad_outcome)


def test_find_request_absent_is_none() -> None:
    from dataclasses import replace as dc_replace

    with_one = dc_replace(empty_stored(WS, "w1"), processed_requests=(_record("req1"),))
    assert find_request(with_one, "other") is None  # 있는 record 를 지나쳐도 None


def test_stored_rejects_non_aggregate_configurations() -> None:
    from dataclasses import replace as dc_replace

    with pytest.raises(StoredConfigurationError):
        dc_replace(empty_stored(WS, "w1"), configurations="not-an-aggregate")  # type: ignore[arg-type]


# ── store-boundary guards ─────────────────────────────────────────────────────
def test_store_rejects_unsafe_work_id(tmp_path: Path) -> None:
    from hwpxfiller.external.work_configuration_store import WorkConfigurationStoreError

    with pytest.raises(WorkConfigurationStoreError):
        _store(tmp_path).load("../escape")


def test_update_rejects_work_id_swap(tmp_path: Path) -> None:
    from hwpxfiller.external.work_configuration_store import WorkConfigurationStoreError

    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    with pytest.raises(WorkConfigurationStoreError):
        store.update("w1", 1, lambda cur: _bump(empty_stored(WS, "w2")))


def test_update_requires_exact_plus_one(tmp_path: Path) -> None:
    from hwpxfiller.external.work_configuration_store import WorkConfigurationStoreError

    store = _store(tmp_path)
    store.create(empty_stored(WS, "w1"))
    with pytest.raises(WorkConfigurationStoreError):
        store.update("w1", 1, lambda cur: cur)  # version 안 올림


def test_workspace_read_none_when_absent(tmp_path: Path) -> None:
    assert WorkspaceMetadataStore(tmp_path).read() is None


def test_minted_empty_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceIdentityIntegrityError):
        WorkspaceMetadataStore(tmp_path).get_or_create(NOW, mint=lambda: "")


@pytest.mark.parametrize("raw", ["{bad json", "[]", '"a-string"'])
def test_config_file_non_object_or_unparseable_fails_closed(
    tmp_path: Path, raw: str
) -> None:
    store = _store(tmp_path)
    path = tmp_path / "configs" / "w1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, "utf-8")
    with pytest.raises(ConfigurationIntegrityError):
        store.load("w1")


def test_config_content_non_dict_fails_closed(tmp_path: Path) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest

    store = _store(tmp_path)
    path = tmp_path / "configs" / "w1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "not-an-object"
    path.write_text(
        json.dumps({"digest": content_digest(content), "content": content}), "utf-8"
    )
    with pytest.raises(ConfigurationIntegrityError):
        store.load("w1")


def test_decoded_invariant_violation_wrapped_as_integrity_error(tmp_path: Path) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest

    store = _store(tmp_path)
    good = encode_stored(empty_stored(WS, "w1"))
    good["aggregate_version"] = 0  # schema 는 정본이나 불변식 위반
    path = tmp_path / "configs" / "w1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"digest": content_digest(good), "content": good}), "utf-8"
    )
    with pytest.raises(ConfigurationIntegrityError):
        store.load("w1")


def test_stored_rejects_non_record_and_bool_version() -> None:
    from dataclasses import replace as dc_replace

    with pytest.raises(StoredConfigurationError):
        dc_replace(empty_stored(WS, "w1"), processed_requests=("x",))  # type: ignore[arg-type]
    with pytest.raises(StoredConfigurationError):
        dc_replace(empty_stored(WS, "w1"), aggregate_version=True)


def test_terminal_outcome_allows_none_versions() -> None:
    TerminalOutcome("A", "NO_CHANGE", False, None, None)  # 유효 — 예외 없음


def test_lock_cache_reuses_live_lock() -> None:
    from hwpxfiller.external.work_configuration_store import _lock

    a = _lock("same-key")  # a 를 잡고 있어 weakref 가 살아 있다
    assert _lock("same-key") is a


def test_workspace_bad_schema_or_empty_id_fails_closed(tmp_path: Path) -> None:
    from hwpxfiller.application.qualification_evidence import content_digest

    meta = tmp_path / "workspace.json"
    for content in (
        {"schema_version": "nope", "workspace_instance_id": "x"},
        {"schema_version": "workspace-metadata-v1", "workspace_instance_id": ""},
    ):
        meta.write_text(
            json.dumps({"digest": content_digest(content), "content": content}), "utf-8"
        )
        with pytest.raises(WorkspaceIdentityIntegrityError):
            WorkspaceMetadataStore(tmp_path).read()


def _bump(stored: object) -> object:
    """aggregate_version 을 정확히 +1 한 새 stored(테스트용 commit 헬퍼)."""
    from dataclasses import replace as dc_replace

    return dc_replace(stored, aggregate_version=stored.aggregate_version + 1)  # type: ignore[attr-defined]
