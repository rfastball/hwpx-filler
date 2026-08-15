"""S3-04 (#654): idempotent Preparation과 latest-intent supersede 시작 흐름 계약.

판정(plan_prepare)은 순수 층에서, transaction·worker handoff(start_prepare)는 store 위에서 잰다 —
같은 setup(초기화된 aggregate)과 oracle(Preparation 상태·seq·current pointer)을 공유하므로 한
owner 로 모은다.
"""

from __future__ import annotations

import threading

import pytest

from hwpxfiller.application.candidate_revision import (
    ContentBlob,
    SourceCaptureObservation,
    TemplateRevision,
    blob_digest,
)
from hwpxfiller.application.prepare_template_change import (
    CAPTURE_REQUESTED,
    PreparePins,
    plan_prepare,
)
from hwpxfiller.application.qualification_evidence import (
    PASS,
    QualificationAttempt,
    QualificationEvidence,
    StructureProjection,
    build_manifest,
    content_digest,
)
from hwpxfiller.application.work_template_state import (
    CHANGE_PREPARED,
    CHANGE_SUPERSEDED,
    PREP_APPLIED,
    PREP_CAPTURING,
    PREP_READY,
    PREP_SUPERSEDED,
    PreparedTemplateChange,
    WorkTemplateStateAggregate,
)
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_template_store import (
    AtomicWorkTemplateStateStore,
    initialize_work,
    start_prepare,
)

REV = "REV1"
PROF = "prof-v1"
EV = "EV1"
PINS = PreparePins(source_binding_id="SB1", source_binding_generation=3, qualification_profile_id=PROF)


# ─── fixtures ─────────────────────────────────────────────────────────────────

def _seed_reference(qroot, croot):
    qstore = QualificationObjectStore(qroot)
    cstore = CandidateObjectStore(croot)
    exact = b"HWPX exact bytes"
    digest = blob_digest(exact)
    cstore.put_blob(ContentBlob(digest, "hwpx", exact, len(exact)))
    cstore.put_observation(
        SourceCaptureObservation("OBS1", "P1", "SB1", 1, "zip-read", {}, digest, "t0")
    )
    cstore.put_revision(TemplateRevision(REV, "LIN1", "hwpx", digest, "OBS1", "t0"))
    qstore.put_manifest(
        build_manifest(
            qualification_profile_id=PROF, media="hwpx", adapter_contract_version="a1",
            product_rule_version="p1", operation_alphabet_version="o1",
            projection_schema_version="proj-v1", manifest_payload={"k": "v"}, created_at="t0",
        )
    )
    payload = {"root_fields": [], "slots": []}
    qstore.put_attempt(
        QualificationAttempt("AT1", "P1", REV, PROF, PASS, EV, None, "t0", "t1")
    )
    qstore.put_evidence(
        QualificationEvidence(
            EV, "AT1", REV, PROF, PASS,
            StructureProjection("proj-v1", payload, content_digest(payload)),
            (), {"engine": "hwpx"}, "t1",
        )
    )
    return qstore, cstore


def _fresh_work(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")
    initialize_work(
        store, qstore, cstore,
        work_id="W1", template_lineage_id="LIN1", application_id="A1",
        pass_evidence_id=EV, actor="tester", applied_at="t2",
    )
    return store


def _pins(_work):
    return PINS


_SEQ = iter(range(1000))


def _start(store, request_id="RQ1", **over):
    kwargs = dict(
        work_id="W1",
        prepare_request_id=request_id,
        actor="tester",
        resolve_pins=_pins,
        preparation_id=f"PREP-{next(_SEQ)}",
        execution_session_id="SESS1",
        started_at="t3",
    )
    kwargs.update(over)
    return start_prepare(store, **kwargs)


# ─── 양성 ─────────────────────────────────────────────────────────────────────

def test_first_prepare_pins_base_source_profile(tmp_path):
    store = _fresh_work(tmp_path)
    prep = _start(store, preparation_id="P1")
    assert prep.status == PREP_CAPTURING
    assert prep.base_application_id == "A1"  # 서버가 current application 을 base 로 고정
    assert (prep.source_binding_id, prep.source_binding_generation) == ("SB1", 3)
    assert prep.qualification_profile_id == PROF
    agg = store.load("W1")
    assert agg.work.current_template_preparation_id == "P1"
    assert agg.work.prepare_seq == 1
    assert agg.aggregate_version == 2  # init(1) → prepare(2)


def test_same_request_returns_same_preparation(tmp_path):
    store = _fresh_work(tmp_path)
    first = _start(store, request_id="RQ1", preparation_id="P1")
    again = _start(store, request_id="RQ1", preparation_id="P2")  # 재전송, 새 id 무시돼야
    assert again.preparation_id == first.preparation_id == "P1"
    agg = store.load("W1")
    assert len(agg.preparations) == 1
    assert agg.work.prepare_seq == 1  # 증가 없음
    assert agg.aggregate_version == 2  # 재전송은 commit 없음


def test_new_request_bumps_seq_and_supersedes_pending(tmp_path):
    store = _fresh_work(tmp_path)
    _start(store, request_id="RQ1", preparation_id="P1")
    _start(store, request_id="RQ2", preparation_id="P2")
    agg = store.load("W1")
    by_id = {p.preparation_id: p for p in agg.preparations}
    assert by_id["P1"].status == PREP_SUPERSEDED  # 이전 pending 은 supersede
    assert by_id["P2"].status == PREP_CAPTURING
    assert agg.work.current_template_preparation_id == "P2"
    assert agg.work.prepare_seq == 2


def test_new_prepare_supersedes_ready_prep_and_prepared_change(tmp_path):
    # READY Preparation + PREPARED Change 를 손으로 세운 뒤 새 prepare 가 둘 다 낮추는지.
    store = _fresh_work(tmp_path)
    with store.update("W1") as txn:
        agg = txn.aggregate
        ready = _cap_prep("P1", status=PREP_READY, prepared_change_id="C1")
        txn.aggregate = WorkTemplateStateAggregate(
            schema_version=agg.schema_version,
            aggregate_version=agg.aggregate_version + 1,
            work=_with(agg.work, current_template_preparation_id="P1"),
            applications=agg.applications,
            preparations=(ready,),
            prepared_changes=(PreparedTemplateChange("C1", "P1", "W1", "A1", "EVx", CHANGE_PREPARED, "t3"),),
            apply_provenance=(),
            outbox_events=(),
        )
    _start(store, request_id="RQ2", preparation_id="P2")
    agg = store.load("W1")
    by_id = {p.preparation_id: p for p in agg.preparations}
    assert by_id["P1"].status == PREP_SUPERSEDED
    assert agg.prepared_changes[0].status == CHANGE_SUPERSEDED


# ─── 동시성 ───────────────────────────────────────────────────────────────────

def test_same_key_two_threads_one_preparation_one_worker(tmp_path):
    store = _fresh_work(tmp_path)
    handoffs: list = []
    barrier = threading.Barrier(2)

    def run(pid):
        barrier.wait()
        _start(
            store, request_id="RQ1", preparation_id=pid,
            on_worker_handoff=handoffs.append,
        )

    threads = [threading.Thread(target=run, args=(f"P{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    agg = store.load("W1")
    assert len(agg.preparations) == 1  # Preparation 1개
    assert len(handoffs) == 1  # worker handoff 1회


def test_different_keys_last_commit_is_current(tmp_path):
    store = _fresh_work(tmp_path)
    _start(store, request_id="RQ1", preparation_id="P1")
    _start(store, request_id="RQ2", preparation_id="P2")
    # 마지막 commit 한 intent 가 current (aggregate 순서 = lease 직렬화 순서).
    assert store.load("W1").work.current_template_preparation_id == "P2"


# ─── 음성 ─────────────────────────────────────────────────────────────────────

def test_prepare_does_not_create_application_epoch(tmp_path):
    store = _fresh_work(tmp_path)
    before = store.load("W1").applications
    _start(store, request_id="RQ1", preparation_id="P1")
    assert store.load("W1").applications == before  # Application/epoch 불변


def test_prior_applied_change_not_superseded(tmp_path):
    # 이전 current Preparation 이 APPLIED 이력이면 새 prepare 가 SUPERSEDED 로 덮지 않는다.
    store = _fresh_work(tmp_path)
    with store.update("W1") as txn:
        agg = txn.aggregate
        applied = _cap_prep("P1", status=PREP_APPLIED, prepared_change_id="C1")
        txn.aggregate = WorkTemplateStateAggregate(
            schema_version=agg.schema_version,
            aggregate_version=agg.aggregate_version + 1,
            work=_with(agg.work, current_template_preparation_id="P1"),
            applications=agg.applications,
            preparations=(applied,),
            prepared_changes=(PreparedTemplateChange("C1", "P1", "W1", "A1", "EVx", CHANGE_PREPARED, "t3"),),
            apply_provenance=(),
            outbox_events=(),
        )
    _start(store, request_id="RQ2", preparation_id="P2")
    agg = store.load("W1")
    by_id = {p.preparation_id: p for p in agg.preparations}
    assert by_id["P1"].status == PREP_APPLIED  # 이력 보존
    assert agg.prepared_changes[0].status == CHANGE_PREPARED  # Change 도 그대로


def test_no_client_supplied_base_or_profile_channel(tmp_path):
    # base 는 인자가 아니라 current application 파생이라, client 가 base 를 주입할 자리가 없다.
    store = _fresh_work(tmp_path)
    import inspect

    params = set(inspect.signature(start_prepare).parameters)
    for forbidden in ("base_application_id", "revision_id", "source_path", "expected_work_version"):
        assert forbidden not in params


def test_failed_worker_handoff_leaves_durable_outbox(tmp_path):
    # 콜백이 commit 뒤 던져도 CAPTURING prep + capture outbox event 는 durable(재시도 가능).
    store = _fresh_work(tmp_path)

    def boom(_prep):
        raise RuntimeError("executor down")

    with pytest.raises(RuntimeError):
        _start(store, request_id="RQ1", preparation_id="P1", on_worker_handoff=boom)
    agg = store.load("W1")
    assert agg.preparations[0].status == PREP_CAPTURING
    assert [e.event_type for e in agg.outbox_events] == [CAPTURE_REQUESTED]


def test_replay_returns_existing_even_if_resolver_now_fails(tmp_path):
    # 멱등 replay 는 resolve_pins 앞에서 short-circuit → resolver 가 이제 실패해도 안 터진다.
    store = _fresh_work(tmp_path)
    first = _start(store, request_id="RQ1", preparation_id="P1")

    def broken(_work):
        raise RuntimeError("source gone")

    again = _start(store, request_id="RQ1", preparation_id="P2", resolve_pins=broken)
    assert again.preparation_id == first.preparation_id


def test_commit_failure_skips_worker(tmp_path, monkeypatch):
    store = _fresh_work(tmp_path)
    handoffs: list = []
    import hwpxfiller.external.work_template_store as mod

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "write_text_atomic", boom)
    with pytest.raises(OSError):
        _start(store, request_id="RQ1", preparation_id="P1", on_worker_handoff=handoffs.append)
    assert handoffs == []  # commit 실패 → worker 시작 없음
    assert store.load("W1").work.current_template_preparation_id is None  # 무손상


def test_authorize_can_block_before_mutation(tmp_path):
    store = _fresh_work(tmp_path)

    def deny(_work, _actor):
        raise PermissionError("nope")

    with pytest.raises(PermissionError):
        _start(store, request_id="RQ1", preparation_id="P1", authorize=deny)
    assert store.load("W1").work.current_template_preparation_id is None


def test_plan_prepare_pure_idempotent_without_store(tmp_path):
    # 순수 판정을 store 없이 직접: 같은 request 는 같은 aggregate 객체를 그대로 돌려준다.
    store = _fresh_work(tmp_path)
    agg = store.load("W1")
    plan1 = plan_prepare(
        agg, prepare_request_id="RQ1", pins=PINS,
        preparation_id="P1", execution_session_id="S", started_at="t3",
    )
    assert plan1.created
    replay = plan_prepare(
        plan1.aggregate, prepare_request_id="RQ1", pins=PINS,
        preparation_id="P2", execution_session_id="S", started_at="t9",
    )
    assert not replay.created
    assert replay.aggregate is plan1.aggregate  # mutation 없음


# ─── 도우미 ───────────────────────────────────────────────────────────────────

def _cap_prep(preparation_id, *, status, prepared_change_id=None):
    from hwpxfiller.application.work_template_state import TemplateChangePreparation

    return TemplateChangePreparation(
        preparation_id=preparation_id, work_id="W1", prepare_request_id="RQ-seed",
        prepare_seq=1, base_application_id="A1", source_binding_id="SB1",
        source_binding_generation=3, qualification_profile_id=PROF,
        execution_session_id="S0", status=status, started_at="t3",
        prepared_change_id=prepared_change_id,
    )


def _with(work, **over):
    from dataclasses import replace

    return replace(work, **over)
