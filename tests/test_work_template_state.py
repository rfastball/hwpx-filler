"""S3-03 (#653): per-Work Template Application aggregate·file-atomic store 계약.

양성(초기화·history·round trip·직렬화·Work 격리)과 음성(global pointer 부재·cross-work·
epoch/prepared_change 중복·dangling·atomic 실패 무손상·손상 무승격·missing 참조 거절)을
한 owner 로 모은다 — 셋 다(aggregate 모델·store·initialization) 같은 setup·oracle 을 공유한다.
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
from hwpxfiller.application.qualification_evidence import (
    PASS,
    QualificationAttempt,
    QualificationEvidence,
    StructureProjection,
    build_manifest,
    content_digest,
)
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    PREPARED_CHANGE,
    SCHEMA_VERSION,
    ApplyProvenance,
    DocumentWork,
    TemplateChangePreparation,
    WorkTemplateApplication,
    WorkTemplateStateAggregate,
    WorkTemplateStateError,
    decode_aggregate,
    encode_aggregate,
)
from hwpxfiller.external.candidate_store import (
    CandidateObjectStore,
    ObjectNotFound as RevisionNotFound,
)
from hwpxfiller.external.qualification_store import (
    ObjectNotFound as EvidenceNotFound,
    QualificationObjectStore,
)
from hwpxfiller.external.work_template_store import (
    AtomicWorkTemplateStateStore,
    WorkAggregateCorrupt,
    WorkAggregateExists,
    WorkAggregateNotFound,
    WorkTemplateReferenceError,
    WorkTemplateStoreError,
    initialize_work,
)

REV = "REV1"
PROF = "prof-v1"
EV = "EV1"


# ─── fixtures: 참조 대상 object 를 두 store 에 심는다 ──────────────────────────

def _seed_reference(qroot, croot, *, result=PASS, with_revision=True, with_manifest=True):
    qstore = QualificationObjectStore(qroot)
    cstore = CandidateObjectStore(croot)
    exact = b"HWPX exact bytes"
    digest = blob_digest(exact)
    if with_revision:
        cstore.put_blob(ContentBlob(digest, "hwpx", exact, len(exact)))
        cstore.put_observation(
            SourceCaptureObservation(
                observation_id="OBS1",
                preparation_id="P1",
                source_binding_id="SB1",
                source_binding_generation=1,
                capture_method="zip-read",
                observed_metadata={},
                captured_content_digest=digest,
                captured_at="t0",
            )
        )
        cstore.put_revision(
            TemplateRevision(REV, "LIN1", "hwpx", digest, "OBS1", "t0")
        )
    if with_manifest:
        qstore.put_manifest(
            build_manifest(
                qualification_profile_id=PROF,
                media="hwpx",
                adapter_contract_version="a1",
                product_rule_version="p1",
                operation_alphabet_version="o1",
                projection_schema_version="proj-v1",
                manifest_payload={"k": "v"},
                created_at="t0",
            )
        )
    projection = None
    diagnostics: tuple = ()
    if result == PASS:
        payload = {"root_fields": [], "slots": []}
        projection = StructureProjection("proj-v1", payload, content_digest(payload))
    else:
        diagnostics = ({"kind": "x", "message": "bad"},)
    qstore.put_attempt(
        QualificationAttempt(
            attempt_id="AT1",
            preparation_id="P1",
            revision_id=REV,
            qualification_profile_id=PROF,
            outcome=result,
            evidence_id=EV,
            error_code=None,
            started_at="t0",
            completed_at="t1",
        )
    )
    qstore.put_evidence(
        QualificationEvidence(
            evidence_id=EV,
            attempt_id="AT1",
            revision_id=REV,
            qualification_profile_id=PROF,
            result=result,
            structure_projection=projection,
            diagnostics=diagnostics,
            engine_metadata={"engine": "hwpx"},
            qualified_at="t1",
        )
    )
    return qstore, cstore


def _init(tmp_path, work_id="W1", **over):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")
    kwargs = dict(
        work_id=work_id,
        template_lineage_id="LIN1",
        application_id="A1",
        pass_evidence_id=EV,
        actor="tester",
        applied_at="t2",
    )
    kwargs.update(over)
    aggregate = initialize_work(store, qstore, cstore, **kwargs)
    return store, aggregate


def _app(**over):
    args = dict(
        application_id="A1",
        work_id="W1",
        application_epoch=1,
        pass_evidence_id=EV,
        previous_application_id=None,
        origin=INITIALIZATION,
        prepared_change_id=None,
        actor="tester",
        applied_at="t2",
    )
    args.update(over)
    return WorkTemplateApplication(**args)


def _prep(**over):
    args = dict(
        preparation_id="P1",
        work_id="W1",
        prepare_request_id="RQ1",
        prepare_seq=1,
        base_application_id="A1",
        source_binding_id="SB1",
        source_binding_generation=1,
        qualification_profile_id=PROF,
        execution_session_id="S1",
        status="CAPTURING",
        started_at="t3",
    )
    args.update(over)
    return TemplateChangePreparation(**args)


def _aggregate(apps, *, work_over=None, version=1):
    work_kwargs = dict(
        work_id="W1",
        template_lineage_id="LIN1",
        current_template_application_id=apps[0].application_id,
        current_template_preparation_id=None,
        prepare_seq=0,
    )
    if work_over:
        work_kwargs.update(work_over)
    return WorkTemplateStateAggregate(
        schema_version=SCHEMA_VERSION,
        aggregate_version=version,
        work=DocumentWork(**work_kwargs),
        applications=tuple(apps),
        preparations=(),
        prepared_changes=(),
        apply_provenance=(),
        outbox_events=(),
    )


# ─── 양성 ─────────────────────────────────────────────────────────────────────

def test_initialization_creates_epoch_1_application(tmp_path):
    store, aggregate = _init(tmp_path)
    app = aggregate.applications[0]
    assert app.origin == INITIALIZATION
    assert app.application_epoch == 1
    assert app.previous_application_id is None
    assert aggregate.work.current_template_application_id == "A1"
    assert store.load("W1") == aggregate


def test_history_a_b_a_separates_identity_and_epoch(tmp_path):
    # A→B→A: 같은 Evidence 로 되돌아와도 Application identity 와 epoch 은 분리된다.
    a = _app(application_id="A1")
    b = _app(
        application_id="A2",
        application_epoch=2,
        previous_application_id="A1",
        origin=PREPARED_CHANGE,
        prepared_change_id="C1",
    )
    a2 = _app(
        application_id="A3",
        application_epoch=3,
        previous_application_id="A2",
        origin=PREPARED_CHANGE,
        prepared_change_id="C2",
    )
    agg = _aggregate([a, b, a2], work_over={"current_template_application_id": "A3"})
    epochs = {x.application_epoch for x in agg.applications}
    ids = {x.application_id for x in agg.applications}
    assert epochs == {1, 2, 3}
    assert len(ids) == 3


def test_encode_decode_round_trip(tmp_path):
    _, aggregate = _init(tmp_path)
    assert decode_aggregate(encode_aggregate(aggregate)) == aggregate


def test_concurrent_update_serializes_under_lease(tmp_path):
    store, _ = _init(tmp_path)
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def bump():
        barrier.wait()
        try:
            with store.update("W1") as txn:
                agg = txn.aggregate
                txn.aggregate = _aggregate(
                    list(agg.applications), version=agg.aggregate_version + 1
                )
        except Exception as exc:  # 직렬화되면 두 번째도 성공(버전 +1), 경합이면 버전 위반
            errors.append(exc)

    threads = [threading.Thread(target=bump) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert store.load("W1").aggregate_version == 3  # 1 → 2 → 3, 유실 없음


def test_only_target_work_changes(tmp_path):
    store, _ = _init(tmp_path, work_id="W1")
    # 두 번째 Work 를 같은 store 에 초기화하고 W1 갱신이 W2 를 건드리지 않음을 본다.
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")
    initialize_work(
        store, qstore, cstore,
        work_id="W2", template_lineage_id="LIN1", application_id="B1",
        pass_evidence_id=EV, actor="t", applied_at="t2",
    )
    before_w2 = store.load("W2")
    with store.update("W1") as txn:
        agg = txn.aggregate
        txn.aggregate = _aggregate(
            list(agg.applications), version=agg.aggregate_version + 1
        )
    assert store.load("W2") == before_w2


def test_update_without_mutation_does_not_commit(tmp_path):
    store, _ = _init(tmp_path)
    with store.update("W1"):
        pass  # aggregate 를 건드리지 않음
    assert store.load("W1").aggregate_version == 1


# ─── 음성 ─────────────────────────────────────────────────────────────────────

def test_no_global_active_revision_field(tmp_path):
    _, aggregate = _init(tmp_path)
    encoded = encode_aggregate(aggregate)
    assert "active_revision_id" not in encoded
    assert "active_revision_id" not in encoded["work"]


def test_application_of_other_work_rejected_on_decode(tmp_path):
    encoded = encode_aggregate(_aggregate([_app()]))
    encoded["applications"][0]["work_id"] = "OTHER"
    with pytest.raises(WorkTemplateStateError, match="다른 Work"):
        decode_aggregate(encoded)


def test_duplicate_epoch_rejected(tmp_path):
    with pytest.raises(WorkTemplateStateError, match="epoch 중복"):
        _aggregate([_app(application_id="A1"), _app(application_id="A2")])


def test_dangling_current_pointer_rejected(tmp_path):
    with pytest.raises(WorkTemplateStateError, match="dangling"):
        _aggregate([_app()], work_over={"current_template_application_id": "MISSING"})


def test_same_prepared_change_two_applications_rejected(tmp_path):
    a = _app(application_id="A1")
    b = _app(
        application_id="A2", application_epoch=2, previous_application_id="A1",
        origin=PREPARED_CHANGE, prepared_change_id="C1",
    )
    c = _app(
        application_id="A3", application_epoch=3, previous_application_id="A2",
        origin=PREPARED_CHANGE, prepared_change_id="C1",  # 같은 change 재사용
    )
    with pytest.raises(WorkTemplateStateError, match="Application 2개"):
        _aggregate([a, b, c], work_over={"current_template_application_id": "A3"})


def test_atomic_replace_failure_keeps_existing(tmp_path, monkeypatch):
    store, _ = _init(tmp_path)
    import hwpxfiller.external.work_template_store as mod

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "write_text_atomic", boom)
    with pytest.raises(OSError):
        with store.update("W1") as txn:
            agg = txn.aggregate
            txn.aggregate = _aggregate(
                list(agg.applications), version=agg.aggregate_version + 1
            )
    assert store.load("W1").aggregate_version == 1  # 기존 무손상


def test_corrupt_file_is_not_promoted_to_current(tmp_path):
    store, _ = _init(tmp_path)
    (tmp_path / "works" / "W1.json").write_text("{ not json", "utf-8")
    with pytest.raises(WorkAggregateCorrupt):
        store.load("W1")


def test_temp_residue_is_not_loaded(tmp_path):
    store, _ = _init(tmp_path)
    (tmp_path / "works" / "W1.json.stale.tmp").write_text("garbage", "utf-8")
    assert store.load("W1").aggregate_version == 1  # .tmp 는 current 가 아니다


def test_missing_pass_evidence_reference_rejected(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")
    with pytest.raises(EvidenceNotFound):
        initialize_work(
            store, qstore, cstore,
            work_id="W1", template_lineage_id="LIN1", application_id="A1",
            pass_evidence_id="MISSING", actor="t", applied_at="t2",
        )


def test_fail_evidence_reference_rejected(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c", result="FAIL")
    with pytest.raises(WorkTemplateReferenceError, match="PASS 가 아니다"):
        initialize_work(
            store, qstore, cstore,
            work_id="W1", template_lineage_id="LIN1", application_id="A1",
            pass_evidence_id=EV, actor="t", applied_at="t2",
        )


def test_missing_revision_reference_rejected(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c", with_revision=False)
    with pytest.raises(RevisionNotFound):
        initialize_work(
            store, qstore, cstore,
            work_id="W1", template_lineage_id="LIN1", application_id="A1",
            pass_evidence_id=EV, actor="t", applied_at="t2",
        )


def test_missing_manifest_reference_rejected(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c", with_manifest=False)
    with pytest.raises(EvidenceNotFound):
        initialize_work(
            store, qstore, cstore,
            work_id="W1", template_lineage_id="LIN1", application_id="A1",
            pass_evidence_id=EV, actor="t", applied_at="t2",
        )


def test_invalid_work_id_rejected(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    with pytest.raises(WorkTemplateStoreError, match="work_id"):
        store.load("../escape")


def test_reinitialize_existing_work_rejected(tmp_path):
    store, _ = _init(tmp_path)
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")
    with pytest.raises(WorkAggregateExists):
        initialize_work(
            store, qstore, cstore,
            work_id="W1", template_lineage_id="LIN1", application_id="A9",
            pass_evidence_id=EV, actor="t", applied_at="t2",
        )


def test_update_missing_work_raises(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    with pytest.raises(WorkAggregateNotFound):
        with store.update("nope"):
            pass


def test_update_version_must_advance_by_one(tmp_path):
    store, _ = _init(tmp_path)
    with pytest.raises(WorkTemplateStoreError, match="정확히 1"):
        with store.update("W1") as txn:
            agg = txn.aggregate
            txn.aggregate = _aggregate(list(agg.applications), version=5)  # 건너뜀


@pytest.mark.parametrize(
    "thunk",
    [
        lambda: DocumentWork("W1", "L", "A1", None, -1),  # prepare_seq < 0
        lambda: _app(origin="XXX"),  # 미상 origin
        lambda: _app(application_epoch=0),  # epoch < 1
        lambda: _app(previous_application_id="A0"),  # INITIALIZATION + previous
        lambda: _app(prepared_change_id="C1"),  # INITIALIZATION + change
        lambda: _app(origin=PREPARED_CHANGE, previous_application_id="A0"),  # change 없음
        lambda: _app(origin=PREPARED_CHANGE, prepared_change_id="C1"),  # previous 없음
    ],
)
def test_object_invariant_guards_reject(thunk):
    with pytest.raises(WorkTemplateStateError):
        thunk()


def test_aggregate_version_below_one_rejected():
    with pytest.raises(WorkTemplateStateError, match="aggregate_version"):
        _aggregate([_app()], version=0)


def test_unknown_schema_version_rejected():
    with pytest.raises(WorkTemplateStateError, match="schema_version"):
        WorkTemplateStateAggregate(
            schema_version="bogus",
            aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0),
            applications=(_app(),),
            preparations=(),
            prepared_changes=(),
            apply_provenance=(),
            outbox_events=(),
        )


def test_unknown_preparation_status_rejected():
    with pytest.raises(WorkTemplateStateError, match="preparation status"):
        _prep(status="WAT")


def test_unknown_prepared_change_status_rejected():
    from hwpxfiller.application.work_template_state import PreparedTemplateChange

    with pytest.raises(WorkTemplateStateError, match="prepared change status"):
        PreparedTemplateChange("C1", "P1", "W1", "A1", "EVx", "WAT", "t3")


def test_duplicate_provenance_id_rejected():
    p = ApplyProvenance("PR1", "W1", "A1", "A1", "EV", "EV", "C1", 1, 1, "a", "t")
    with pytest.raises(WorkTemplateStateError, match="provenance_id 중복"):
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION, aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0), applications=(_app(),),
            preparations=(), prepared_changes=(),
            apply_provenance=(p, p), outbox_events=(),
        )


def test_duplicate_outbox_event_id_rejected():
    from hwpxfiller.application.work_template_state import OutboxEvent

    e = OutboxEvent("OB1", "template.change_applied", {})
    with pytest.raises(WorkTemplateStateError, match="outbox event_id 중복"):
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION, aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0), applications=(_app(),),
            preparations=(), prepared_changes=(), apply_provenance=(),
            outbox_events=(e, e),
        )


def test_duplicate_prepared_change_id_rejected():
    from hwpxfiller.application.work_template_state import (
        CHANGE_PREPARED,
        PreparedTemplateChange,
    )

    c1 = PreparedTemplateChange("C1", "P1", "W1", "A1", "EVx", CHANGE_PREPARED, "t3")
    c2 = PreparedTemplateChange("C1", "P2", "W1", "A1", "EVy", CHANGE_PREPARED, "t3")  # 같은 id
    with pytest.raises(WorkTemplateStateError, match="prepared_change_id 중복"):
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION,
            aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0),
            applications=(_app(),),
            preparations=(),
            prepared_changes=(c1, c2),
            apply_provenance=(),
            outbox_events=(),
        )


def test_duplicate_preparation_id_rejected():
    with pytest.raises(WorkTemplateStateError, match="preparation_id 중복"):
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION,
            aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0),
            applications=(_app(),),
            preparations=(
                _prep(preparation_id="P1", prepare_request_id="R1"),
                _prep(preparation_id="P1", prepare_request_id="R2"),  # 같은 id 재사용
            ),
            prepared_changes=(),
            apply_provenance=(),
            outbox_events=(),
        )


def test_duplicate_application_id_rejected():
    a = _app(application_id="A1", application_epoch=1)
    b = _app(application_id="A1", application_epoch=2)  # 같은 id, 다른 epoch
    with pytest.raises(WorkTemplateStateError, match="application_id 중복"):
        _aggregate([a, b])


def test_dangling_previous_rejected():
    a = _app(
        application_id="A1", origin=PREPARED_CHANGE,
        prepared_change_id="C1", previous_application_id="GONE",
    )
    with pytest.raises(WorkTemplateStateError, match="previous.*dangling"):
        _aggregate([a])


def test_current_pointer_not_terminal_rejected():
    # A1(epoch1)·A2(epoch2) 인데 current 가 A1 로 되돌아가면 조용한 rollback → 거절.
    a = _app(application_id="A1", application_epoch=1)
    b = _app(
        application_id="A2", application_epoch=2, previous_application_id="A1",
        origin=PREPARED_CHANGE, prepared_change_id="C1",
    )
    with pytest.raises(WorkTemplateStateError, match="최고 epoch"):
        _aggregate([a, b], work_over={"current_template_application_id": "A1"})


def test_dangling_current_preparation_pointer_rejected():
    with pytest.raises(WorkTemplateStateError, match="current preparation"):
        _aggregate(
            [_app()], work_over={"current_template_preparation_id": "MISSING"}
        )


def test_dangling_provenance_reference_rejected():
    with pytest.raises(WorkTemplateStateError, match="provenance"):
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION,
            aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0),
            applications=(_app(),),
            preparations=(),
            prepared_changes=(),
            apply_provenance=(
                ApplyProvenance("PR1", "W1", "GONE", "GONE", "EV", "EV", "C1", 1, 2, "a", "t"),
            ),
            outbox_events=(),
        )


def test_lineage_mismatch_reference_rejected(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")  # revision lineage = LIN1
    with pytest.raises(WorkTemplateReferenceError, match="lineage"):
        initialize_work(
            store, qstore, cstore,
            work_id="W1", template_lineage_id="OTHER", application_id="A1",
            pass_evidence_id=EV, actor="t", applied_at="t2",
        )


def test_in_place_payload_mutation_is_not_silently_discarded(tmp_path):
    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    store.create(
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION,
            aggregate_version=1,
            work=DocumentWork("W1", "LIN1", "A1", None, 0),
            applications=(_app(),),
            preparations=(_prep(diagnostics=({"k": "v"},)),),
            prepared_changes=(),
            apply_provenance=(),
            outbox_events=(),
        )
    )
    # nested diagnostics dict 를 in-place 로 고치고 version 을 안 올리면 조용히 유실되지 않고 거절된다.
    with pytest.raises(WorkTemplateStoreError, match="정확히 1"):
        with store.update("W1") as txn:
            txn.aggregate.preparations[0].diagnostics[0]["k"] = "changed"
    assert store.load("W1").aggregate_version == 1  # 기존 무손상


def test_preparation_of_other_work_rejected():
    with pytest.raises(WorkTemplateStateError, match="preparation/change"):
        WorkTemplateStateAggregate(
            schema_version=SCHEMA_VERSION,
            aggregate_version=1,
            work=DocumentWork("W1", "L", "A1", None, 0),
            applications=(_app(),),
            preparations=(_prep(work_id="OTHER"),),
            prepared_changes=(),
            apply_provenance=(),
            outbox_events=(),
        )


def test_update_cannot_retarget_work(tmp_path):
    store, _ = _init(tmp_path)
    qstore, cstore = _seed_reference(tmp_path / "q", tmp_path / "c")
    initialize_work(
        store, qstore, cstore,
        work_id="W2", template_lineage_id="LIN1", application_id="B1",
        pass_evidence_id=EV, actor="t", applied_at="t2",
    )
    with pytest.raises(WorkTemplateStoreError, match="다른 Work"):
        with store.update("W1") as txn:
            other = store.load("W2")
            txn.aggregate = _aggregate(
                list(other.applications),
                work_over={"work_id": "W2", "current_template_application_id": "B1"},
                version=txn.aggregate.aggregate_version + 1,
            )
