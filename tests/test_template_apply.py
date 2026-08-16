"""S3-07 (#657): Prepared Template Change의 Work 원자 적용 계약.

apply는 준비된 exact target을 fixed base에서 소비하는 얇고 강한 경계다 — source 재읽기·qualification
재실행·latest 검색·silent rebase 없음. 성공·재전송·전진·conflict·revocation·integrity failure를
서로 다른 결과로 닫고, 성공은 새 Application·current pointer·Change APPLIED·provenance·outbox를
하나의 aggregate commit으로 관찰한다.
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
from hwpxfiller.application.prepare_orchestration import (
    APPLY_ALREADY_APPLIED,
    APPLY_APPLIED,
    APPLY_APPLIED_THEN_ADVANCED,
    APPLY_CONFLICT,
    APPLY_INTEGRITY_ERROR,
    APPLY_REJECTED,
    APPLY_SUPERSEDED,
    find_preparation,
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
from hwpxfiller.application.template_qualification import (
    QualificationInspection,
    QualificationProfile,
    TemplateStructure,
)
from hwpxfiller.application.work_template_state import (
    CHANGE_APPLIED,
    PREP_READY,
    PREPARED_CHANGE,
)
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.domain.qualification_profile_admission import ProfileAdmissionStateMissing
from hwpxfiller.external.prepare_orchestration_runner import (
    QualificationProfileRevoked,
    S3ApplyProfileDiscoveryRetryExhausted,
    admit_preparation,
    apply_prepared_change,
    run_capture_stage,
    run_qualification_stage,
)
from hwpxfiller.external.profile_admission_runner import (
    initialize_qualification_profile_admission,
    revoke_qualification_profile,
)
from hwpxfiller.external.profile_admission_store import ProfileAdmissionStore
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_template_store import (
    AtomicWorkTemplateStateStore,
    initialize_work,
    start_prepare,
)

PROF = "prof-v1"
GEN = 3
INIT_BYTES = b"OLD template bytes"
NEW_BYTES = b"NEW exact template bytes"
LINEAGE = TemplateLineage("LIN1", "hwpx", "SB1", GEN, "t0")
BINDING = MutableSourceBinding("SB1", "hwpx", "C:/tpl.hwpx", {}, GEN)


def _seed_init(qstore, cstore, manifest_media="hwpx"):
    digest = blob_digest(INIT_BYTES)
    cstore.put_blob(ContentBlob(digest, "hwpx", INIT_BYTES, len(INIT_BYTES)))
    cstore.put_observation(SourceCaptureObservation("OBS0", "P0", "SB1", GEN, "zip", {}, digest, "t0"))
    cstore.put_revision(TemplateRevision("REV0", "LIN1", "hwpx", digest, "OBS0", "t0"))
    qstore.put_manifest(
        build_manifest(
            qualification_profile_id=PROF, media=manifest_media, adapter_contract_version="a1",
            product_rule_version="p1", operation_alphabet_version="o1",
            projection_schema_version="proj-v1", manifest_payload={}, created_at="t0",
        )
    )
    pl = {"root_fields": ["title"], "slots": []}
    qstore.put_attempt(QualificationAttempt("AT0", "P0", "REV0", PROF, PASS, "EV0", None, "t0", "t1"))
    qstore.put_evidence(
        QualificationEvidence(
            "EV0", "AT0", "REV0", PROF, PASS,
            StructureProjection("proj-v1", pl, content_digest(pl)), (), {"e": "1"}, "t1",
        )
    )


def _ready_change(tmp_path, manifest_media="hwpx"):
    """init → prepare → capture(NEW) → qualify PASS → admit READY 까지 돌린 Work + C1."""
    wstore = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore = QualificationObjectStore(tmp_path / "q")
    cstore = CandidateObjectStore(tmp_path / "c")
    _seed_init(qstore, cstore, manifest_media)
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
        reader=lambda _b: StableCapture(NEW_BYTES, blob_digest(NEW_BYTES), "SB1", GEN, "zip", {}),
        resolve_current_generation=lambda _w: GEN, captured_at="t4", created_at="t4",
    )
    run_qualification_stage(
        wstore, cstore, qstore, work_id="W1", preparation_id="P1",
        profile=QualificationProfile(PROF, lambda _b: QualificationInspection(TemplateStructure(("title",), ()), ())),
        engine_metadata={"e": "1"}, started_at="t5", completed_at="t6", qualified_at="t6",
    )
    admit_preparation(
        wstore, cstore, qstore, work_id="W1", preparation_id="P1",
        resolve_current_binding=lambda _w: ("SB1", GEN), prepared_change_id="C1", prepared_at="t7",
    )
    # S5-09(#705): Apply 는 exact Profile 의 admission gate 를 통과해야 한다 — PROF 를 ADMITTED 로 세운다.
    astore = _admissions(wstore)
    initialize_qualification_profile_admission(
        astore, qstore, qstore, qualification_profile_id=PROF,
        request_id="admit-init", now="t7",
    )
    return wstore, cstore, qstore


def _admissions(wstore) -> ProfileAdmissionStore:
    """tmp_path 아래 admission 저장소(works 형제 디렉터리) — 테스트가 ADMITTED/REVOKED 를 심는다."""
    return ProfileAdmissionStore(wstore._root.parent / "admissions")


def _revoke(wstore, qstore) -> None:
    """PROF 의 admission 을 REVOKED 로 전이한다(ProfileFence 아래 S5-08 command)."""
    revoke_qualification_profile(
        _admissions(wstore), qstore, qualification_profile_id=PROF,
        request_id="revoke-1", reason_ref="compromised", now="t9",
    )


def _grant(_work, _actor):
    return None


def _apply(wstore, cstore, qstore, change_id="C1", app_id="A2", authorize=_grant):
    # public entry 는 (outcome, committed_aggregate) 를 fence 아래에서 함께 돌려준다(#675).
    outcome, _ = apply_prepared_change(
        wstore, cstore, qstore, admission_store=_admissions(wstore),
        workspace_instance_id="ws-test",
        work_id="W1", change_id=change_id, actor="t", authorize=authorize,
        new_application_id=app_id, provenance_id="PR1", outbox_event_id="OB1", applied_at="t8",
    )
    return outcome


def _change(wstore, change_id="C1"):
    for c in wstore.load("W1").prepared_changes:
        if c.prepared_change_id == change_id:
            return c
    raise AssertionError("change 없음")


# ─── 기본 성공 ────────────────────────────────────────────────────────────────

def test_apply_success_appends_application_and_bumps_epoch(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_APPLIED and outcome.resulting_application_id == "A2"
    agg = wstore.load("W1")
    assert agg.work.current_template_application_id == "A2"
    a2 = next(a for a in agg.applications if a.application_id == "A2")
    assert a2.application_epoch == 2 and a2.previous_application_id == "A1"
    assert a2.origin == PREPARED_CHANGE and a2.prepared_change_id == "C1"
    assert a2.pass_evidence_id == _change(wstore).target_pass_evidence_id
    assert _change(wstore).status == CHANGE_APPLIED
    assert _change(wstore).resulting_application_id == "A2"
    assert len(agg.apply_provenance) == 1 and len(agg.outbox_events) == 2  # capture 요청 + applied
    prov = agg.apply_provenance[0]
    assert (prov.from_application_id, prov.to_application_id) == ("A1", "A2")
    assert (prov.epoch_before, prov.epoch_after) == (1, 2)


# ─── idempotency ──────────────────────────────────────────────────────────────

def test_reapply_same_change_is_already_applied(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    _apply(wstore, cstore, qstore)
    again = _apply(wstore, cstore, qstore, app_id="A9")  # 재전송, 새 id 무시
    assert again.result == APPLY_ALREADY_APPLIED and again.resulting_application_id == "A2"
    agg = wstore.load("W1")
    assert sum(1 for a in agg.applications if a.application_id == "A2") == 1  # 중복 0
    assert len(agg.apply_provenance) == 1 and len(agg.outbox_events) == 2


def test_reapply_after_work_advanced_is_applied_then_advanced(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    _apply(wstore, cstore, qstore)  # current → A2
    # Work 가 A3 로 전진했다고 흉내
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        from hwpxfiller.application.work_template_state import WorkTemplateApplication

        a3 = WorkTemplateApplication("A3", "W1", 3, "EV0", "A2", "PREPARED_CHANGE", "Cx", "t", "t9")
        txn.aggregate = replace(
            agg, aggregate_version=agg.aggregate_version + 1,
            applications=(*agg.applications, a3),
            work=replace(agg.work, current_template_application_id="A3"),
        )
    again = _apply(wstore, cstore, qstore)
    assert again.result == APPLY_APPLIED_THEN_ADVANCED


# ─── conflict ─────────────────────────────────────────────────────────────────

def test_base_changed_yields_conflicted(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    with wstore.update("W1") as txn:  # base A1 → A2 로 이동(current preparation 은 유지)
        agg = txn.aggregate
        from hwpxfiller.application.work_template_state import WorkTemplateApplication

        a2 = WorkTemplateApplication("AX", "W1", 2, "EV0", "A1", "PREPARED_CHANGE", "Cx", "t", "t9")
        txn.aggregate = replace(
            agg, aggregate_version=agg.aggregate_version + 1,
            applications=(*agg.applications, a2),
            work=replace(agg.work, current_template_application_id="AX"),
        )
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_CONFLICT
    assert _change(wstore).status == "CONFLICTED"
    assert wstore.load("W1").work.current_template_application_id == "AX"  # silent rebase 0


def test_newer_preparation_yields_superseded(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    start_prepare(  # 새 prepare 가 current preparation 을 P2 로 옮김
        wstore, work_id="W1", prepare_request_id="RQ2", actor="t",
        resolve_pins=lambda _w: PreparePins("SB1", GEN, PROF),
        preparation_id="P2", execution_session_id="S1", started_at="t7b",
    )
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_SUPERSEDED
    assert _change(wstore).status == "SUPERSEDED"


def test_current_preparation_cleared_yields_superseded(tmp_path):
    # Change 는 아직 PREPARED 인데 current preparation pointer 가 이 prep 이 아니면 gate 가 SUPERSEDED.
    wstore, cstore, qstore = _ready_change(tmp_path)
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        txn.aggregate = replace(
            agg, aggregate_version=agg.aggregate_version + 1,
            work=replace(agg.work, current_template_preparation_id=None),
        )
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_SUPERSEDED
    assert _change(wstore).status == "SUPERSEDED"


# ─── failure ──────────────────────────────────────────────────────────────────


def test_evidence_field_mismatch_is_integrity_error(tmp_path):
    # target evidence 가 실재하지만 이 Preparation 의 attempt/revision 과 다르면 INTEGRITY_ERROR.
    wstore, cstore, qstore = _ready_change(tmp_path)
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        changes = tuple(
            replace(c, target_pass_evidence_id="EV0") if c.prepared_change_id == "C1" else c
            for c in agg.prepared_changes  # EV0 은 PASS 지만 attempt=AT0/revision=REV0 (prep 과 불일치)
        )
        txn.aggregate = replace(agg, aggregate_version=agg.aggregate_version + 1, prepared_changes=changes)
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_INTEGRITY_ERROR
    assert wstore.load("W1").work.current_template_application_id == "A1"

def test_profile_revoked_yields_rejected(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    qstore.put_revocation(QualificationProfileRevocation(PROF, "compromised", "admin", "t7c"))
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_REJECTED
    assert _change(wstore).status == "REJECTED"
    assert wstore.load("W1").work.current_template_application_id == "A1"  # 무변경


def test_evidence_missing_is_integrity_error(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    # target evidence 를 손으로 다른(부재) id 로 바꿔 무결성 위반을 만든다.
    with wstore.update("W1") as txn:
        agg = txn.aggregate
        changes = tuple(
            replace(c, target_pass_evidence_id="GONE") if c.prepared_change_id == "C1" else c
            for c in agg.prepared_changes
        )
        txn.aggregate = replace(agg, aggregate_version=agg.aggregate_version + 1, prepared_changes=changes)
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_INTEGRITY_ERROR
    agg = wstore.load("W1")
    assert agg.work.current_template_application_id == "A1"  # 상태 무변경
    assert _change(wstore).status == "PREPARED"  # Change 도 그대로


def test_missing_attempt_is_integrity_error(tmp_path):
    # admission 뒤 target Attempt 가 사라지면(Evidence 는 남아도) INTEGRITY_ERROR — dangling chain 방지.
    from hwpxfiller.application.prepare_orchestration import derive_stage_ids

    wstore, cstore, qstore = _ready_change(tmp_path)
    ids = derive_stage_ids("W1", "P1")
    (tmp_path / "q" / "attempts" / f"{ids.attempt_id}.json").unlink()  # Attempt 삭제
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_INTEGRITY_ERROR
    assert wstore.load("W1").work.current_template_application_id == "A1"


def test_manifest_media_mismatch_is_integrity_error(tmp_path):
    # pinned Profile Manifest 의 media 가 target revision 의 media 와 다르면 INTEGRITY_ERROR.
    wstore, cstore, qstore = _ready_change(tmp_path, manifest_media="docx")  # revision 은 hwpx
    outcome = _apply(wstore, cstore, qstore)
    assert outcome.result == APPLY_INTEGRITY_ERROR
    assert wstore.load("W1").work.current_template_application_id == "A1"


def test_commit_failure_keeps_prepared(tmp_path, monkeypatch):
    wstore, cstore, qstore = _ready_change(tmp_path)
    import hwpxfiller.external.work_template_store as mod

    monkeypatch.setattr(mod, "write_text_atomic", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        _apply(wstore, cstore, qstore)
    agg = wstore.load("W1")
    assert agg.work.current_template_application_id == "A1"  # A17 유지
    assert _change(wstore).status == "PREPARED"


def test_authorization_denied_blocks_apply(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)

    def deny(_w, _a):
        raise PermissionError("no access")

    with pytest.raises(PermissionError):
        _apply(wstore, cstore, qstore, authorize=deny)
    assert wstore.load("W1").work.current_template_application_id == "A1"


# ─── 음성: 다른 Work 무변경 ────────────────────────────────────────────────────

def test_other_work_untouched_by_apply(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    # 두 번째 Work 를 세우고 W1 apply 가 그것을 건드리지 않음을 본다.
    initialize_work(
        wstore, qstore, cstore, work_id="W2", template_lineage_id="LIN1",
        application_id="B1", pass_evidence_id="EV0", actor="t", applied_at="t2",
    )
    before = wstore.load("W2")
    _apply(wstore, cstore, qstore)
    assert wstore.load("W2") == before


# ─── S5-09(#705): Profile admission gate ─────────────────────────────────────────

def test_missing_admission_state_blocks_apply_write_zero(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    (_admissions(wstore)._root / f"{PROF}.json").unlink()  # admission state 제거
    with pytest.raises(ProfileAdmissionStateMissing):
        _apply(wstore, cstore, qstore)
    assert wstore.load("W1").work.current_template_application_id == "A1"  # write 0
    assert _change(wstore).status == "PREPARED"


def test_revoked_admission_blocks_new_apply_write_zero(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    _revoke(wstore, qstore)
    with pytest.raises(QualificationProfileRevoked):
        _apply(wstore, cstore, qstore)
    assert wstore.load("W1").work.current_template_application_id == "A1"  # 반쪽 적용 0
    assert _change(wstore).status == "PREPARED"


def test_public_route_reaches_admission_query(tmp_path):
    # 단순 symbol 참조가 아니라 실제 public Apply call path 가 admission query 에 도달함을 본다.
    wstore, cstore, qstore = _ready_change(tmp_path)
    astore = _admissions(wstore)
    queried: list[str] = []
    original_load = astore.load

    def spy_load(profile_id):
        queried.append(profile_id)
        return original_load(profile_id)

    astore.load = spy_load  # type: ignore[method-assign]
    outcome, _ = apply_prepared_change(
        wstore, cstore, qstore, admission_store=astore, workspace_instance_id="ws-test",
        work_id="W1", change_id="C1", actor="t", authorize=_grant,
        new_application_id="A2", provenance_id="PR1", outbox_event_id="OB1", applied_at="t8",
    )
    assert outcome.result == APPLY_APPLIED
    assert PROF in queried  # admission query 가 public route 에서 실제 실행됐다


# ─── discovery/재시도 ─────────────────────────────────────────────────────────────

def test_wrong_profile_discovery_releases_and_retries(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    calls: list[int] = []

    def discover():  # 첫 관측은 틀린 profile → release, 이후 정정
        calls.append(1)
        return "WRONG" if len(calls) == 1 else PROF

    outcome, _ = apply_prepared_change(
        wstore, cstore, qstore, admission_store=_admissions(wstore),
        workspace_instance_id="ws-test", work_id="W1", change_id="C1", actor="t",
        authorize=_grant, new_application_id="A2", provenance_id="PR1",
        outbox_event_id="OB1", applied_at="t8", discover_profile_id=discover,
    )
    assert outcome.result == APPLY_APPLIED
    assert len(calls) == 2  # 한 번 release 후 재시도해 성공


def test_bounded_retry_exhaustion_leaves_request_unconsumed(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    with pytest.raises(S3ApplyProfileDiscoveryRetryExhausted):
        apply_prepared_change(
            wstore, cstore, qstore, admission_store=_admissions(wstore),
            workspace_instance_id="ws-test", work_id="W1", change_id="C1", actor="t",
            authorize=_grant, new_application_id="A2", provenance_id="PR1",
            outbox_event_id="OB1", applied_at="t8",
            discover_profile_id=lambda: "ALWAYS-WRONG", max_discovery_attempts=3,
        )
    # request 미소비: change 는 여전히 PREPARED, current 무변경.
    assert _change(wstore).status == "PREPARED"
    assert wstore.load("W1").work.current_template_application_id == "A1"
    # 정정된 정상 discovery 로 다시 apply 하면 성공한다(request 가 소비되지 않았다).
    assert _apply(wstore, cstore, qstore).result == APPLY_APPLIED


# ─── revoke/apply 선형화 ──────────────────────────────────────────────────────────

def test_apply_first_then_revoke_keeps_historical_success(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    assert _apply(wstore, cstore, qstore).result == APPLY_APPLIED  # ADMITTED 관측 하 성공
    _revoke(wstore, qstore)  # 이후 revoke
    again = _apply(wstore, cstore, qstore, app_id="A9")  # idempotent replay
    assert again.result == APPLY_ALREADY_APPLIED  # 뒤늦은 revoke 가 역사적 성공을 뒤집지 않는다
    assert wstore.load("W1").work.current_template_application_id == "A2"


def test_revoke_first_then_apply_is_blocked(tmp_path):
    wstore, cstore, qstore = _ready_change(tmp_path)
    _revoke(wstore, qstore)  # ProfileFence 아래 REVOKED 선반영
    with pytest.raises(QualificationProfileRevoked):
        _apply(wstore, cstore, qstore)
    assert wstore.load("W1").work.current_template_application_id == "A1"  # 반쪽 적용 0
