"""S5-07(#703) WorkExecutionPlanStore — file-atomic·CAS·first-seen durable primitives.

publish/ledger-only atomicity·idempotent replay·restart 복원·corruption fail-closed·CAS 를
검증한다. 순수 값/전이는 ``test_stored_execution_plan.py`` 가 지고, 여기서는 파일 I/O 경계를 진다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.stored_execution_plan import (
    ExecutionPlanIntegrityError,
    ExecutionPlanStoreIntegrityError,
    IdempotencyKeyReused,
    PlanPublished,
    SealTerminalOutcome,
    StoreConcurrentModification,
    plan_semantic_digest,
)
from hwpxfiller.external import work_execution_plan_store as store_mod
from hwpxfiller.external.work_execution_plan_store import WorkExecutionPlanStore

from tests.test_stored_execution_plan import (
    attempt_evidence,
    complete_evidence,
    deps,
    fingerprint,
    plan,
    policy,
    published_outcome,
    qual_blocked,
)


def _store(tmp_path) -> WorkExecutionPlanStore:
    return WorkExecutionPlanStore(tmp_path)


def _publish(store, *, request_id, expected, a_plan, evidence, kind="CREATED", fp=None):
    return store.publish_sealed_plan_atomic(
        work_authority_id="work-1",
        expected_aggregate_version=expected,
        request_id=request_id,
        fingerprint=fp or fingerprint(),
        resolved_seal_policy=policy(),
        capture_evidence=evidence,
        plan_payload=a_plan,
        dependency_set=deps(),
        published_outcome=published_outcome(a_plan, evidence, kind),
        now="t0",
    )


# ─── atomicity + persistence ──────────────────────────────────────────────────────────
def test_publish_persists_all_parts_and_restores_on_restart(tmp_path) -> None:
    p = plan()
    result = _publish(_store(tmp_path), request_id="r1", expected=0, a_plan=p,
                      evidence=complete_evidence())
    assert result.replayed is False
    assert result.aggregate.aggregate_version == 1
    # 새 store 인스턴스(=프로세스 재시작)로 전체 복원.
    reloaded = _store(tmp_path).load("work-1")
    assert reloaded == result.aggregate
    digest = plan_semantic_digest(p)
    assert digest in reloaded.plans_by_semantic_digest
    assert len(reloaded.plans_by_compilation_key) == 1
    assert len(reloaded.first_seen_ledger) == 1


def test_ledger_only_writes_no_plan(tmp_path) -> None:
    ev = attempt_evidence()
    store = _store(tmp_path)
    result = store.commit_seal_terminal_outcome_atomic(
        work_authority_id="work-1", expected_aggregate_version=0, request_id="r1",
        fingerprint=fingerprint(), resolved_seal_policy=policy(),
        capture_evidence=ev, terminal_outcome=qual_blocked(ev), now="t0",
    )
    assert result.aggregate.plans_by_semantic_digest == {}
    assert store.load("work-1").aggregate_version == 1


def test_reuse_by_second_request_preserves_own_evidence(tmp_path) -> None:
    p = plan()
    store = _store(tmp_path)
    _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence(seed="a"))
    ev2 = complete_evidence(seed="b")
    result = _publish(store, request_id="r2", expected=1, a_plan=p, evidence=ev2, kind="REUSED")
    ledger = result.aggregate.first_seen_ledger
    assert len(ledger) == 2
    assert len(result.aggregate.plans_by_semantic_digest) == 1  # create-once
    digests = {r.durable_capture_evidence.captured_execution_input_digest for r in ledger}
    assert len(digests) == 2  # 각 request 가 자기 evidence 보존


def test_replace_failure_leaves_previous_intact(tmp_path, monkeypatch) -> None:
    p = plan()
    store = _store(tmp_path)
    _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store_mod, "write_text_atomic", boom)
    with pytest.raises(OSError):
        _publish(store, request_id="r2", expected=1, a_plan=p, kind="REUSED",
                 evidence=complete_evidence(seed="b"))
    # 기존 aggregate 무손상(version 1, ledger 1건).
    reloaded = _store(tmp_path).load("work-1")
    assert reloaded.aggregate_version == 1
    assert len(reloaded.first_seen_ledger) == 1


def test_stray_temp_file_ignored_on_load(tmp_path) -> None:
    p = plan()
    _publish(_store(tmp_path), request_id="r1", expected=0, a_plan=p,
             evidence=complete_evidence())
    (tmp_path / "work-1.json.abc.tmp").write_text("garbage", "utf-8")
    assert _store(tmp_path).load("work-1").aggregate_version == 1


# ─── idempotency ──────────────────────────────────────────────────────────────────────
def test_same_request_same_fingerprint_replay(tmp_path) -> None:
    p = plan()
    store = _store(tmp_path)
    first = _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    replay = _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    assert replay.replayed is True
    assert replay.record == first.record
    assert replay.aggregate.aggregate_version == 1  # 새 commit 0


def test_concurrent_same_request_first_commit_wins(tmp_path) -> None:
    # in-process lease 로 직렬화 — 두 번째 호출은 durable record 를 되읽어 replay(loser reloads).
    p = plan()
    store = _store(tmp_path)
    _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    loser = _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence(seed="z"))
    assert loser.replayed is True
    assert store.load("work-1").aggregate_version == 1


def test_same_request_different_fingerprint_rejected(tmp_path) -> None:
    p = plan()
    store = _store(tmp_path)
    _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    with pytest.raises(IdempotencyKeyReused):
        _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence(),
                 fp=fingerprint(command_schema_version="seal-command/vDIFFERENT"))
    # 최초 record 수정 0.
    assert store.load("work-1").aggregate_version == 1


def test_auto_resolved_policy_preserved_after_default_change(tmp_path) -> None:
    # AUTO fingerprint 로 최초 policy A 를 봉인. 서버 default 가 B 로 바뀐 retry 도 최초 A 를 replay.
    p = plan()
    store = _store(tmp_path)
    first = _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    assert first.record.resolved_seal_policy.policy_resolution_version == "policy/v1"
    replay = store.publish_sealed_plan_atomic(
        work_authority_id="work-1", expected_aggregate_version=0, request_id="r1",
        fingerprint=fingerprint(), resolved_seal_policy=policy(policy_resolution_version="policy/v2"),
        capture_evidence=complete_evidence(), plan_payload=p, dependency_set=deps(),
        published_outcome=published_outcome(p, complete_evidence()), now="t9",
    )
    assert replay.replayed is True
    assert replay.record.resolved_seal_policy.policy_resolution_version == "policy/v1"


def test_replay_across_restart(tmp_path) -> None:
    p = plan()
    _publish(_store(tmp_path), request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    # 새 store 인스턴스에서 같은 request 재시도 → durable record replay.
    replay = _publish(_store(tmp_path), request_id="r1", expected=0, a_plan=p,
                      evidence=complete_evidence())
    assert replay.replayed is True


def test_retryable_integrity_failure_does_not_consume_request(tmp_path) -> None:
    p = plan()
    store = _store(tmp_path)
    # 잘못된 published_outcome claim → integrity error, ledger 미기록.
    with pytest.raises(ExecutionPlanIntegrityError):
        store.publish_sealed_plan_atomic(
            work_authority_id="work-1", expected_aggregate_version=0, request_id="r1",
            fingerprint=fingerprint(), resolved_seal_policy=policy(),
            capture_evidence=complete_evidence(), plan_payload=p, dependency_set=deps(),
            published_outcome=PlanPublished("CREATED", "sha256:forged",
                                            "sha256:forged", "sha256:forged"),
            now="t0",
        )
    assert not store.exists("work-1")
    # 교정된 재시도는 정상 소비.
    ok = _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    assert ok.replayed is False


def test_authorization_is_not_a_terminal_outcome() -> None:
    # store 가 아는 terminal 은 4종뿐 — authorization/route failure 는 여기 없다(비소비 실패).
    from typing import get_args
    names = {t.__name__ for t in get_args(SealTerminalOutcome)}
    assert names == {"PlanPublished", "ExecutionQualificationBlocked",
                     "ExecutionPolicyBlocked", "StaleExecutionBasis"}


# ─── CAS + corruption ─────────────────────────────────────────────────────────────────
def test_cas_conflict_rejected(tmp_path) -> None:
    p = plan()
    store = _store(tmp_path)
    _publish(store, request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    with pytest.raises(StoreConcurrentModification):
        _publish(store, request_id="r2", expected=0, a_plan=plan(removed_option="o9"),
                 evidence=complete_evidence(seed="b"))


def test_corrupt_envelope_digest_fail_closed(tmp_path) -> None:
    p = plan()
    _publish(_store(tmp_path), request_id="r1", expected=0, a_plan=p, evidence=complete_evidence())
    (tmp_path / "work-1.json").write_text('{"digest": "sha256:wrong", "content": {}}', "utf-8")
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        _store(tmp_path).load("work-1")


def test_corrupt_non_json_fail_closed(tmp_path) -> None:
    _publish(_store(tmp_path), request_id="r1", expected=0, a_plan=plan(),
             evidence=complete_evidence())
    (tmp_path / "work-1.json").write_text("not json", "utf-8")
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        _store(tmp_path).load("work-1")


def test_load_missing_aggregate_fail_closed(tmp_path) -> None:
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        _store(tmp_path).load("work-1")


def test_load_or_empty_absent_returns_version_zero(tmp_path) -> None:
    agg = _store(tmp_path).load_or_empty("work-1", "ws-1")
    assert agg.aggregate_version == 0
    assert agg.plans_by_semantic_digest == {}


def test_unsafe_work_id_rejected(tmp_path) -> None:
    from hwpxfiller.application.stored_execution_plan import ExecutionPlanStoreError
    with pytest.raises(ExecutionPlanStoreError):
        _store(tmp_path).exists("../escape")


def test_power_loss_and_multiwriter_nonclaim_documented() -> None:
    doc = store_mod.__doc__ or ""
    assert "power-loss" in doc
    assert "cross-process" in doc


def test_envelope_top_level_not_dict_fail_closed(tmp_path) -> None:
    (tmp_path / "work-1.json").write_text("[1, 2, 3]", "utf-8")
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        _store(tmp_path).load("work-1")


def test_envelope_valid_digest_but_non_dict_content_fail_closed(tmp_path) -> None:
    import json

    from hwpxfiller.application.qualification_evidence import content_digest

    payload = [1, 2, 3]
    envelope = {"digest": content_digest(payload), "content": payload}
    (tmp_path / "work-1.json").write_text(json.dumps(envelope), "utf-8")
    with pytest.raises(ExecutionPlanStoreIntegrityError):
        _store(tmp_path).load("work-1")


def test_writer_lease_reused_for_same_key() -> None:
    key = "reuse-key\x00work-1"
    first = store_mod._lock(key)
    try:
        assert store_mod._lock(key) is first  # 같은 key 는 같은 RLock 을 재사용한다
    finally:
        del first
