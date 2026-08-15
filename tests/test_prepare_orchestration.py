"""S3-05 (#655): capture→qualification checkpoint 결선과 crash recovery 계약.

capture/qualify 엔진은 이미 검증됐으므로 stub reader/profile 로 결선하고, 이 파일이 잰다:
단계 결과의 정확한 persistence(PASS/FAIL/ERROR)·object-first 참조·crash window reconcile·
source-changed terminal·중복 stage 차단. 판정 세부는 순수 planner 로 직접, 결선·object-first 는
coordinator 로 잰다(같은 setup/oracle 공유 → 한 owner).
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.candidate_revision import (
    MutableSourceBinding,
    SourceCaptureError,
    StableCapture,
    TemplateLineage,
    blob_digest,
)
from hwpxfiller.application.prepare_orchestration import (
    derive_stage_ids,
    find_preparation,
    plan_capture_checkpoint,
    plan_recovery,
)
from hwpxfiller.application.qualification_evidence import build_records
from hwpxfiller.application.template_qualification import (
    QualificationInspection,
    QualificationProfile,
    TemplateDiagnostic,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_template_state import (
    PREP_CAPTURE_ERROR,
    PREP_CAPTURING,
    PREP_INTERRUPTED,
    PREP_QUALIFICATION_ERROR,
    PREP_QUALIFICATION_FAILED,
    PREP_QUALIFYING,
    PREP_SOURCE_BINDING_CHANGED,
    PREP_SUPERSEDED,
)
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.prepare_orchestration_runner import (
    recover_preparation,
    recover_session,
    run_capture_stage,
    run_qualification_stage,
)
from hwpxfiller.external.qualification_store import (
    ObjectNotFound as QualObjectNotFound,
    QualificationObjectStore,
)
from hwpxfiller.external.work_template_store import (
    AtomicWorkTemplateStateStore,
    initialize_work,
    start_prepare,
)
from hwpxfiller.application.prepare_template_change import PreparePins

PROF = "prof-v1"
EV0 = "EV0"  # init evidence
GEN = 3
EXACT = b"HWPX exact bytes"
DIGEST = blob_digest(EXACT)
LINEAGE = TemplateLineage("LIN1", "hwpx", "SB1", GEN, "t0")
BINDING = MutableSourceBinding("SB1", "hwpx", "C:/tpl.hwpx", {}, GEN)


# ─── stub 엔진 port ───────────────────────────────────────────────────────────

def _good_reader(_binding):
    return StableCapture(EXACT, DIGEST, "SB1", GEN, "zip-read", {})


def _failing_reader(_binding):
    return SourceCaptureError("READER_BOOM")


def _profile(outcome):
    def inspect(_bytes):
        if outcome == "PASS":
            return QualificationInspection(
                TemplateStructure(root_fields=("title",), slots=(TemplateSlot("s", (), ()),)), ()
            )
        if outcome == "FAIL":
            return QualificationInspection(None, (TemplateDiagnostic("bad-field", "empty"),))
        raise RuntimeError("inspector boom")  # ERROR

    return QualificationProfile(PROF, inspect)


def _gen(_work):
    return GEN


# ─── fixtures ─────────────────────────────────────────────────────────────────

def _seed_init_reference(qroot, croot):
    qstore = QualificationObjectStore(qroot)
    cstore = CandidateObjectStore(croot)
    from hwpxfiller.application.candidate_revision import (
        ContentBlob,
        SourceCaptureObservation,
        TemplateRevision,
    )
    from hwpxfiller.application.qualification_evidence import (
        PASS,
        QualificationAttempt,
        QualificationEvidence,
        StructureProjection,
        build_manifest,
        content_digest,
    )

    cstore.put_blob(ContentBlob(DIGEST, "hwpx", EXACT, len(EXACT)))
    cstore.put_observation(
        SourceCaptureObservation("OBS0", "P0", "SB1", 1, "zip", {}, DIGEST, "t0")
    )
    cstore.put_revision(TemplateRevision("REV0", "LIN1", "hwpx", DIGEST, "OBS0", "t0"))
    qstore.put_manifest(
        build_manifest(
            qualification_profile_id=PROF, media="hwpx", adapter_contract_version="a1",
            product_rule_version="p1", operation_alphabet_version="o1",
            projection_schema_version="proj-v1", manifest_payload={}, created_at="t0",
        )
    )
    pl = {"root_fields": [], "slots": []}
    qstore.put_attempt(QualificationAttempt("AT0", "P0", "REV0", PROF, PASS, EV0, None, "t0", "t1"))
    qstore.put_evidence(
        QualificationEvidence(
            EV0, "AT0", "REV0", PROF, PASS,
            StructureProjection("proj-v1", pl, content_digest(pl)), (), {"e": "1"}, "t1",
        )
    )
    return qstore, cstore


def _capturing_work(tmp_path, session="SESS1"):
    """CAPTURING Preparation P1 이 하나 선 Work."""
    wstore = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore, cstore = _seed_init_reference(tmp_path / "q", tmp_path / "c")
    initialize_work(
        wstore, qstore, cstore, work_id="W1", template_lineage_id="LIN1",
        application_id="A1", pass_evidence_id=EV0, actor="t", applied_at="t2",
    )
    start_prepare(
        wstore, work_id="W1", prepare_request_id="RQ1", actor="t",
        resolve_pins=lambda _w: PreparePins("SB1", GEN, PROF),
        preparation_id="P1", execution_session_id=session, started_at="t3",
    )
    return wstore, cstore, qstore


def _capture(wstore, cstore, reader=_good_reader, gen=_gen):
    return run_capture_stage(
        wstore, cstore, work_id="W1", preparation_id="P1", lineage=LINEAGE, binding=BINDING,
        reader=reader, resolve_current_generation=gen, captured_at="t4", created_at="t4",
    )


def _qualify(wstore, cstore, qstore, outcome):
    return run_qualification_stage(
        wstore, cstore, qstore, work_id="W1", preparation_id="P1", profile=_profile(outcome),
        projection_schema_version="proj-v1", engine_metadata={"engine": "hwpx"},
        started_at="t5", completed_at="t6", qualified_at="t6",
    )


def _durable_attempt(qstore, outcome):
    """qualification 이 돌아 object 는 durable, 그러나 aggregate checkpoint 는 미commit 인 crash 상태."""
    from hwpxfiller.application.template_qualification import (
        TemplateQualificationAttemptErrored,
        TemplateQualificationFailed,
        TemplateQualificationPassed,
    )

    ids = derive_stage_ids("P1")
    if outcome == "PASS":
        res = TemplateQualificationPassed("P1.rev", PROF, TemplateStructure(("title",), ()))
    elif outcome == "FAIL":
        res = TemplateQualificationFailed("P1.rev", PROF, (TemplateDiagnostic("x", "y"),))
    else:
        res = TemplateQualificationAttemptErrored("P1.rev", PROF, "INSPECTION_ERROR")
    attempt, evidence = build_records(
        res, attempt_id=ids.attempt_id, preparation_id="P1", evidence_id=ids.evidence_id,
        projection_schema_version="proj-v1", engine_metadata={"e": "1"},
        started_at="t5", completed_at="t6", qualified_at="t6",
    )
    qstore.put_attempt(attempt)
    if evidence is not None:
        qstore.put_evidence(evidence)


# ─── 기본 결과 ────────────────────────────────────────────────────────────────

def test_capture_success_then_pass_checkpoint(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    cap = _capture(wstore, cstore)
    assert cap.status == PREP_QUALIFYING
    assert cap.revision_id == "P1.rev" and cap.observation_id == "P1.obs"
    # object-first: aggregate 가 참조하는 revision 은 이미 durable
    cstore.get_revision(cap.revision_id)
    prep = _qualify(wstore, cstore, qstore, "PASS")
    assert prep.status == PREP_QUALIFYING  # PASS 는 admission 전까지 QUALIFYING checkpoint
    assert prep.attempt_id == "P1.att" and prep.evidence_id == "P1.ev"
    assert qstore.get_evidence("P1.ev").structure_projection is not None


def test_capture_success_then_fail_terminal(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    _capture(wstore, cstore)
    prep = _qualify(wstore, cstore, qstore, "FAIL")
    assert prep.status == PREP_QUALIFICATION_FAILED
    assert qstore.get_evidence("P1.ev").result == "FAIL"


def test_capture_success_then_error_terminal_no_evidence(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    _capture(wstore, cstore)
    prep = _qualify(wstore, cstore, qstore, "ERROR")
    assert prep.status == PREP_QUALIFICATION_ERROR
    assert prep.evidence_id is None
    with pytest.raises(QualObjectNotFound):
        qstore.get_evidence("P1.ev")  # ERROR 는 Evidence 없음


def test_capture_error_skips_qualification(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    cap = _capture(wstore, cstore, reader=_failing_reader)
    assert cap.status == PREP_CAPTURE_ERROR
    prep = _qualify(wstore, cstore, qstore, "PASS")  # QUALIFYING 아님 → 호출 0
    assert prep.status == PREP_CAPTURE_ERROR
    with pytest.raises(QualObjectNotFound):
        qstore.get_attempt("P1.att")  # attempt 자체가 안 만들어짐


# ─── crash window ─────────────────────────────────────────────────────────────

def test_capturing_then_exit_is_interrupted(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)  # capture 시작 전 종료
    prep = recover_preparation(wstore, qstore, work_id="W1", preparation_id="P1", completed_at="t9")
    assert prep.status == PREP_INTERRUPTED


def test_revision_durable_before_attach_then_exit(tmp_path):
    # capture object 는 durable(orphan)이나 aggregate attach 전 종료 → INTERRUPTED, 자동 recapture 금지.
    wstore, cstore, qstore = _capturing_work(tmp_path)
    from hwpxfiller.application.candidate_revision import capture_candidate_revision

    ids = derive_stage_ids("P1")
    capture_candidate_revision(
        lineage=LINEAGE, binding=BINDING, preparation_id="P1", reader=_good_reader,
        store=cstore, observation_id=ids.observation_id, revision_id=ids.revision_id,
        captured_at="t4", created_at="t4",
    )  # object durable, checkpoint 미commit → prep 여전히 CAPTURING
    assert find_preparation(wstore.load("W1"), "P1").status == PREP_CAPTURING
    prep = recover_preparation(wstore, qstore, work_id="W1", preparation_id="P1", completed_at="t9")
    assert prep.status == PREP_INTERRUPTED  # revision orphan 이어도 재호출 없이 INTERRUPTED


def test_pass_evidence_durable_before_admission_recovers_without_requalify(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    _capture(wstore, cstore)  # prep → QUALIFYING
    _durable_attempt(qstore, "PASS")  # Attempt/Evidence durable, checkpoint 미commit
    prep = recover_preparation(wstore, qstore, work_id="W1", preparation_id="P1", completed_at="t9")
    assert prep.status == PREP_QUALIFYING  # PASS checkpoint 복원(재qualify 없음)
    assert prep.attempt_id == "P1.att" and prep.evidence_id == "P1.ev"


def test_fail_evidence_durable_before_commit_reconciles_fail(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    _capture(wstore, cstore)
    _durable_attempt(qstore, "FAIL")
    prep = recover_preparation(wstore, qstore, work_id="W1", preparation_id="P1", completed_at="t9")
    assert prep.status == PREP_QUALIFICATION_FAILED


def test_error_attempt_durable_reconciles_error(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    _capture(wstore, cstore)
    _durable_attempt(qstore, "ERROR")
    prep = recover_preparation(wstore, qstore, work_id="W1", preparation_id="P1", completed_at="t9")
    assert prep.status == PREP_QUALIFICATION_ERROR
    assert prep.evidence_id is None


# ─── race ─────────────────────────────────────────────────────────────────────

def test_capture_of_superseded_prep_does_not_return_to_current(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    # 새 prepare 가 P1 을 supersede
    start_prepare(
        wstore, work_id="W1", prepare_request_id="RQ2", actor="t",
        resolve_pins=lambda _w: PreparePins("SB1", GEN, PROF),
        preparation_id="P2", execution_session_id="SESS1", started_at="t3b",
    )
    assert find_preparation(wstore.load("W1"), "P1").status == PREP_SUPERSEDED
    cap = _capture(wstore, cstore)  # 뒤늦은 P1 capture
    assert cap.status == PREP_SUPERSEDED  # no-op — current 로 복귀하지 않음
    assert wstore.load("W1").work.current_template_preparation_id == "P2"


def test_source_binding_generation_changed_is_terminal(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    cap = _capture(wstore, cstore, gen=lambda _w: GEN + 1)  # live source 가 움직임
    assert cap.status == PREP_SOURCE_BINDING_CHANGED


def test_duplicate_capture_worker_runs_stage_at_most_once(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    first = _capture(wstore, cstore)
    second = _capture(wstore, cstore)  # 중복 worker
    assert first.revision_id == second.revision_id == "P1.rev"
    assert second.status == PREP_QUALIFYING  # 두 번째는 no-op(create-once + CAPTURING 아님)


def test_recover_session_reconciles_prior_session_only(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path, session="OLD")
    recovered = recover_session(
        wstore, qstore, work_id="W1", current_session_id="NEW", completed_at="t9"
    )
    assert [p.status for p in recovered] == [PREP_INTERRUPTED]
    # 같은 session 은 recovery 대상 아님
    assert recover_session(wstore, qstore, work_id="W1", current_session_id="OLD", completed_at="t9") == ()


# ─── 순수 planner 경계 ─────────────────────────────────────────────────────────

def test_capture_checkpoint_binding_change_beats_capture_success(tmp_path):
    # binding_changed 가 capture 성공보다 우선(둘 다 참일 때 SOURCE_BINDING_CHANGED).
    wstore, cstore, qstore = _capturing_work(tmp_path)
    agg = wstore.load("W1")
    out = plan_capture_checkpoint(
        agg, "P1", observation_id="P1.obs", revision_id="P1.rev",
        capture_failed=False, binding_changed=True, completed_at="t4",
    )
    assert find_preparation(out, "P1").status == PREP_SOURCE_BINDING_CHANGED


def test_recovery_noop_on_terminal_preparation(tmp_path):
    wstore, cstore, qstore = _capturing_work(tmp_path)
    _capture(wstore, cstore, reader=_failing_reader)  # CAPTURE_ERROR(terminal)
    agg = wstore.load("W1")
    out = plan_recovery(
        agg, "P1", attempt_outcome=None, attempt_id=None, evidence_id=None, completed_at="t9"
    )
    assert out is agg  # terminal 은 reconcile 대상 아님(no-op)


def test_find_preparation_missing_raises(tmp_path):
    from hwpxfiller.application.work_template_state import WorkTemplateStateError

    wstore, cstore, qstore = _capturing_work(tmp_path)
    with pytest.raises(WorkTemplateStateError, match="preparation .* 없음"):
        find_preparation(wstore.load("W1"), "GHOST")


def test_qualification_checkpoint_noop_when_not_qualifying(tmp_path):
    from hwpxfiller.application.prepare_orchestration import plan_qualification_checkpoint

    wstore, cstore, qstore = _capturing_work(tmp_path)  # P1 은 CAPTURING(아직 QUALIFYING 아님)
    agg = wstore.load("W1")
    out = plan_qualification_checkpoint(
        agg, "P1", outcome="PASS", attempt_id="P1.att", evidence_id="P1.ev", completed_at="t6"
    )
    assert out is agg  # QUALIFYING 아니면 no-op


def test_in_flight_excludes_same_session(tmp_path):
    from hwpxfiller.application.prepare_orchestration import in_flight_preparations

    wstore, cstore, qstore = _capturing_work(tmp_path, session="CUR")  # CAPTURING in-flight
    assert in_flight_preparations(wstore.load("W1"), "CUR") == ()  # 같은 session 제외
    assert len(in_flight_preparations(wstore.load("W1"), "OTHER")) == 1
