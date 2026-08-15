"""S3-06 (#656): PASS admission·NO_CHANGE·Prepared Change 생성 계약.

durable PASS checkpoint(S3-05)를 ordered gate 로 재검사해 READY+Change 로 승격하거나 SUPERSEDED·
BASE_CHANGED·SOURCE_BINDING_CHANGED·PROFILE_REVOKED·NO_CHANGE 로 fail-closed 종료한다. 실 flow
(init→prepare→capture→qualify→admit)로 세워 완료 시점 rebase 금지·operational 동치·create-once·
recovery idempotency 를 잰다.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from hwpxfiller.application.candidate_revision import (
    ContentBlob,
    MutableSourceBinding,
    SourceCaptureObservation,
    StableCapture,
    TemplateLineage,
    TemplateRevision,
    blob_digest,
)
from hwpxfiller.application.prepare_template_change import PreparePins
from hwpxfiller.application.qualification_evidence import (
    PASS,
    QualificationAttempt,
    QualificationEvidence,
    QualificationProfileRevocation,
    StructureProjection,
    build_manifest,
    content_digest,
)
from hwpxfiller.application.qualification_evidence import project_structure  # noqa: F401
from hwpxfiller.application.template_qualification import (
    QualificationInspection,
    QualificationProfile,
    TemplateStructure,
)
from hwpxfiller.application.work_template_state import (
    CHANGE_PREPARED,
    PREP_BASE_CHANGED,
    PREP_NO_CHANGE,
    PREP_PROFILE_REVOKED,
    PREP_READY,
    PREP_SOURCE_BINDING_CHANGED,
    PREP_SUPERSEDED,
    WorkTemplateApplication,
)
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.prepare_orchestration_runner import (
    admit_preparation,
    run_capture_stage,
    run_qualification_stage,
)
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_template_store import (
    AtomicWorkTemplateStateStore,
    WorkTemplateStoreError,
    initialize_work,
    start_prepare,
)

PROF = "prof-v1"
GEN = 3
INIT_BYTES = b"OLD template bytes"
NEW_BYTES = b"NEW exact template bytes"
LINEAGE = TemplateLineage("LIN1", "hwpx", "SB1", GEN, "t0")
BINDING = MutableSourceBinding("SB1", "hwpx", "C:/tpl.hwpx", {}, GEN)


def _pass_evidence(qstore, cstore, *, ev_id, at_id, rev_id, obs_id, data, profile, prep_id):
    digest = blob_digest(data)
    cstore.put_blob(ContentBlob(digest, "hwpx", data, len(data)))
    cstore.put_observation(
        SourceCaptureObservation(obs_id, prep_id, "SB1", GEN, "zip", {}, digest, "t0")
    )
    cstore.put_revision(TemplateRevision(rev_id, "LIN1", "hwpx", digest, obs_id, "t0"))
    pl = {"root_fields": ["title"], "slots": []}
    qstore.put_attempt(QualificationAttempt(at_id, prep_id, rev_id, profile, PASS, ev_id, None, "t0", "t1"))
    qstore.put_evidence(
        QualificationEvidence(
            ev_id, at_id, rev_id, profile, PASS,
            StructureProjection("proj-v1", pl, content_digest(pl)), (), {"e": "1"}, "t1",
        )
    )


def _manifest(qstore, profile=PROF):
    qstore.put_manifest(
        build_manifest(
            qualification_profile_id=profile, media="hwpx", adapter_contract_version="a1",
            product_rule_version="p1", operation_alphabet_version="o1",
            projection_schema_version="proj-v1", manifest_payload={}, created_at="t0",
        )
    )


def _reader(data):
    return lambda _b: StableCapture(data, blob_digest(data), "SB1", GEN, "zip", {})


def _profile_ok():
    return QualificationProfile(
        PROF, lambda _b: QualificationInspection(TemplateStructure(("title",), ()), ())
    )


def _work_with_pass_checkpoint(tmp_path, *, capture_bytes=NEW_BYTES, init_profile=PROF):
    """init(INIT_BYTES) → prepare → capture(capture_bytes) → qualify PASS 까지 돌린 Work.

    반환 시 P1 은 QUALIFYING + PASS attempt/evidence 결속(admission 대상).
    """
    wstore = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore = QualificationObjectStore(tmp_path / "q")
    cstore = CandidateObjectStore(tmp_path / "c")
    _manifest(qstore)
    if init_profile != PROF:
        _manifest(qstore, init_profile)
    _pass_evidence(
        qstore, cstore, ev_id="EV0", at_id="AT0", rev_id="REV0", obs_id="OBS0",
        data=INIT_BYTES, profile=init_profile, prep_id="P0",
    )
    initialize_work(
        wstore, qstore, cstore, work_id="W1", template_lineage_id="LIN1",
        application_id="A1", pass_evidence_id="EV0", actor="t", applied_at="t2",
    )
    start_prepare(
        wstore, work_id="W1", prepare_request_id="RQ1", actor="t",
        resolve_pins=lambda _w: PreparePins("SB1", GEN, PROF),
        preparation_id="P1", execution_session_id="S1", started_at="t3",
    )
    run_capture_stage(
        wstore, cstore, work_id="W1", preparation_id="P1", lineage=LINEAGE, binding=BINDING,
        reader=_reader(capture_bytes), resolve_current_generation=lambda _w: GEN,
        captured_at="t4", created_at="t4",
    )
    run_qualification_stage(
        wstore, cstore, qstore, work_id="W1", preparation_id="P1", profile=_profile_ok(),
        engine_metadata={"e": "1"}, started_at="t5", completed_at="t6", qualified_at="t6",
    )
    return wstore, cstore, qstore


def _binding(_work):
    return ("SB1", GEN)


def _admit(wstore, cstore, qstore, binding=_binding, change_id="C1"):
    return admit_preparation(
        wstore, cstore, qstore, work_id="W1", preparation_id="P1",
        resolve_current_binding=binding, prepared_change_id=change_id, prepared_at="t7",
    )


def _prep(wstore):
    from hwpxfiller.application.prepare_orchestration import find_preparation

    return find_preparation(wstore.load("W1"), "P1")


# ─── 양성 ─────────────────────────────────────────────────────────────────────

def test_current_same_base_changed_yields_ready_and_change(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)  # NEW_BYTES != INIT_BYTES
    change = _admit(wstore, cstore, qstore)
    assert change is not None and change.status == CHANGE_PREPARED
    assert change.base_application_id == "A1"
    prep = _prep(wstore)
    assert prep.status == PREP_READY and prep.prepared_change_id == "C1"


def test_same_digest_same_profile_is_no_change(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path, capture_bytes=INIT_BYTES)
    change = _admit(wstore, cstore, qstore)
    assert change is None
    assert _prep(wstore).status == PREP_NO_CHANGE
    assert wstore.load("W1").prepared_changes == ()  # Change 없음


def test_same_digest_different_profile_yields_change(tmp_path):
    # 같은 bytes 라도 Profile 이 다르면 operational 동치가 아니다 → Change.
    wstore, cstore, qstore = _work_with_pass_checkpoint(
        tmp_path, capture_bytes=INIT_BYTES, init_profile="prof-OLD"
    )
    change = _admit(wstore, cstore, qstore)
    assert change is not None
    assert _prep(wstore).status == PREP_READY


def test_admission_is_idempotent(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    first = _admit(wstore, cstore, qstore)
    again = _admit(wstore, cstore, qstore, change_id="C-OTHER")  # 재호출, 새 id 무시돼야
    assert again.prepared_change_id == first.prepared_change_id == "C1"
    assert len(wstore.load("W1").prepared_changes) == 1  # 중복 생성 없음


# ─── race / gate ──────────────────────────────────────────────────────────────

def test_superseded_when_not_current_intent(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    start_prepare(
        wstore, work_id="W1", prepare_request_id="RQ2", actor="t",
        resolve_pins=lambda _w: PreparePins("SB1", GEN, PROF),
        preparation_id="P2", execution_session_id="S1", started_at="t6b",
    )  # P1 은 이미 SUPERSEDED
    change = _admit(wstore, cstore, qstore)
    assert change is None
    assert _prep(wstore).status == PREP_SUPERSEDED


def test_superseded_gate_when_current_pointer_cleared(tmp_path):
    # QUALIFYING 인데 work.current_template_preparation_id 가 P1 이 아니면 admission gate 가 SUPERSEDED.
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        txn.aggregate = replace(
            agg, aggregate_version=agg.aggregate_version + 1,
            work=replace(agg.work, current_template_preparation_id=None),
        )
    change = _admit(wstore, cstore, qstore)
    assert change is None
    assert _prep(wstore).status == PREP_SUPERSEDED


def test_base_changed_when_current_application_moved(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    # apply 를 흉내: current application 을 A2 로 옮긴다(prep.base_application_id=A1 과 불일치).
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        a2 = WorkTemplateApplication(
            "A2", "W1", 2, "EV0", "A1", "PREPARED_CHANGE", "Cx", "t", "t6c"
        )
        txn.aggregate = replace(
            agg, aggregate_version=agg.aggregate_version + 1,
            applications=(*agg.applications, a2),
            work=replace(agg.work, current_template_application_id="A2"),
        )
    change = _admit(wstore, cstore, qstore)
    assert change is None
    assert _prep(wstore).status == PREP_BASE_CHANGED  # 완료 시점 값으로 rebase 하지 않음


def test_source_binding_changed_gate(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    change = _admit(wstore, cstore, qstore, binding=lambda _w: ("SB1", GEN + 1))
    assert change is None
    assert _prep(wstore).status == PREP_SOURCE_BINDING_CHANGED


def test_profile_revoked_gate(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    qstore.put_revocation(QualificationProfileRevocation(PROF, "compromised", "admin", "t6d"))
    change = _admit(wstore, cstore, qstore)
    assert change is None
    assert _prep(wstore).status == PREP_PROFILE_REVOKED


# ─── 음성 ─────────────────────────────────────────────────────────────────────

def test_evidence_mismatch_is_integrity_failure(tmp_path):
    wstore, cstore, qstore = _work_with_pass_checkpoint(tmp_path)
    # Preparation 의 evidence pin 을 손으로 다른 것으로 바꿔 무결성 위반을 만든다.
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        preps = tuple(
            replace(p, evidence_id="EV0") if p.preparation_id == "P1" else p  # 다른 revision 의 evidence
            for p in agg.preparations
        )
        txn.aggregate = replace(agg, aggregate_version=agg.aggregate_version + 1, preparations=preps)
    with pytest.raises(WorkTemplateStoreError, match="admission"):
        _admit(wstore, cstore, qstore)
    assert wstore.load("W1").prepared_changes == ()  # Change 없음


def test_admit_noop_when_not_pass_checkpoint(tmp_path):
    # capture 만 하고 qualify 안 한 QUALIFYING(attempt 없음) → admission 대상 아님.
    wstore = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore = QualificationObjectStore(tmp_path / "q")
    cstore = CandidateObjectStore(tmp_path / "c")
    _manifest(qstore)
    _pass_evidence(
        qstore, cstore, ev_id="EV0", at_id="AT0", rev_id="REV0", obs_id="OBS0",
        data=INIT_BYTES, profile=PROF, prep_id="P0",
    )
    initialize_work(
        wstore, qstore, cstore, work_id="W1", template_lineage_id="LIN1",
        application_id="A1", pass_evidence_id="EV0", actor="t", applied_at="t2",
    )
    start_prepare(
        wstore, work_id="W1", prepare_request_id="RQ1", actor="t",
        resolve_pins=lambda _w: PreparePins("SB1", GEN, PROF),
        preparation_id="P1", execution_session_id="S1", started_at="t3",
    )
    run_capture_stage(
        wstore, cstore, work_id="W1", preparation_id="P1", lineage=LINEAGE, binding=BINDING,
        reader=_reader(NEW_BYTES), resolve_current_generation=lambda _w: GEN,
        captured_at="t4", created_at="t4",
    )  # QUALIFYING, attempt_id 없음
    assert _admit(wstore, cstore, qstore) is None
    assert wstore.load("W1").prepared_changes == ()
