"""첫 Job 등록과 Configuration 실행 guard 계약.

bootstrap 은 명시 write command 다.
capture→qualify→PASS→INITIALIZATION Application 을 원자로 만들거나, 실패면 가짜 Application 없이
repair 로 닫는다. guard 는 과거 Configuration 이 새 current Application 실행 권위로 조용히
재사용되지 않게 한다.
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
from hwpxfiller.application.qualification_evidence import build_manifest
from hwpxfiller.application.template_qualification import (
    QualificationInspection,
    QualificationProfile,
    TemplateDiagnostic,
    TemplateStructure,
)
from hwpxfiller.application.work_bootstrap import (
    BOOTSTRAP_OK,
    TEMPLATE_INITIALIZATION_REQUIRED,
)
from hwpxfiller.application.work_template_state import INITIALIZATION
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.prepare_orchestration_runner import bootstrap_work
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore

PROF = "prof-v1"
GEN = 3
BYTES = b"template bytes"
LINEAGE = TemplateLineage("LIN1", "hwpx", "SB1", GEN, "t0")
BINDING = MutableSourceBinding("SB1", "hwpx", "C:/template.hwpx", {}, GEN)


def _good_reader(_b):
    return StableCapture(BYTES, blob_digest(BYTES), "SB1", GEN, "zip", {})


def _profile(outcome):
    def inspect(_bytes):
        if outcome == "PASS":
            return QualificationInspection(TemplateStructure(("title",), ()), ())
        if outcome == "FAIL":
            return QualificationInspection(None, (TemplateDiagnostic("bad", "x"),))
        raise RuntimeError("boom")

    return QualificationProfile(PROF, inspect)


def _stores(tmp_path, manifest_media="hwpx"):
    wstore = AtomicWorkTemplateStateStore(tmp_path / "works")
    qstore = QualificationObjectStore(tmp_path / "q")
    cstore = CandidateObjectStore(tmp_path / "c")
    qstore.put_manifest(
        build_manifest(
            qualification_profile_id=PROF, media=manifest_media, adapter_contract_version="a1",
            product_rule_version="p1", operation_alphabet_version="o1",
            projection_schema_version="proj-v1", manifest_payload={}, created_at="t0",
        )
    )
    return wstore, qstore, cstore


def _bootstrap(wstore, qstore, cstore, *, reader=_good_reader, outcome="PASS", request="BR1"):
    return bootstrap_work(
        wstore, cstore, qstore, work_id="W1", bootstrap_request_id=request,
        lineage=LINEAGE, binding=BINDING, reader=reader, profile=_profile(outcome),
        observation_id="OBS1", revision_id="REV1", attempt_id="AT1", evidence_id="EV1",
        application_id="A1", engine_metadata={"e": "1"}, actor="t",
        captured_at="t1", created_at="t1", started_at="t2", completed_at="t3", qualified_at="t3",
    )


# ─── 성공 ─────────────────────────────────────────────────────────────────────

def test_first_job_bootstraps_to_initialization_application(tmp_path):
    wstore, qstore, cstore = _stores(tmp_path)
    outcome = _bootstrap(wstore, qstore, cstore)
    assert outcome.result == BOOTSTRAP_OK
    agg = wstore.load("W1")
    a1 = agg.applications[0]
    assert a1.origin == INITIALIZATION and a1.application_epoch == 1
    assert agg.work.current_template_application_id == "A1"


def test_bootstrap_is_idempotent(tmp_path):
    wstore, qstore, cstore = _stores(tmp_path)
    first = _bootstrap(wstore, qstore, cstore)
    again = _bootstrap(wstore, qstore, cstore, request="BR-OTHER")  # 재전송
    assert again.result == BOOTSTRAP_OK
    assert again.aggregate.applications[0].application_id == first.aggregate.applications[0].application_id
    assert len(wstore.load("W1").applications) == 1  # 중복 Application 없음


# ─── 실패 ─────────────────────────────────────────────────────────────────────

def test_capture_error_requires_initialization_and_creates_no_work(tmp_path):
    wstore, qstore, cstore = _stores(tmp_path)
    outcome = _bootstrap(wstore, qstore, cstore, reader=lambda _b: SourceCaptureError("MISSING"))
    assert outcome.result == TEMPLATE_INITIALIZATION_REQUIRED
    assert outcome.reason == "MISSING" and outcome.aggregate is None
    assert not wstore.exists("W1")  # 가짜 Application 없음


def test_qualification_fail_requires_initialization(tmp_path):
    wstore, qstore, cstore = _stores(tmp_path)
    outcome = _bootstrap(wstore, qstore, cstore, outcome="FAIL")
    assert outcome.result == TEMPLATE_INITIALIZATION_REQUIRED
    assert not wstore.exists("W1")
    assert qstore.get_evidence("EV1").result == "FAIL"  # FAIL evidence 는 durable


def test_qualification_error_requires_initialization_no_evidence(tmp_path):
    wstore, qstore, cstore = _stores(tmp_path)
    outcome = _bootstrap(wstore, qstore, cstore, outcome="ERROR")
    assert outcome.result == TEMPLATE_INITIALIZATION_REQUIRED
    assert not wstore.exists("W1")
    from hwpxfiller.external.qualification_store import ObjectNotFound

    with pytest.raises(ObjectNotFound):
        qstore.get_evidence("EV1")  # ERROR 는 Evidence 없음


def test_revoked_profile_requires_initialization(tmp_path):
    # bootstrap 도 admission/apply 와 같은 revocation 게이트를 통과해야 한다(우회 금지).
    from hwpxfiller.application.qualification_evidence import QualificationProfileRevocation

    wstore, qstore, cstore = _stores(tmp_path)
    qstore.put_revocation(QualificationProfileRevocation(PROF, "compromised", "admin", "t0"))
    outcome = _bootstrap(wstore, qstore, cstore)
    assert outcome.result == TEMPLATE_INITIALIZATION_REQUIRED and outcome.reason == "PROFILE_REVOKED"
    assert not wstore.exists("W1")


def test_manifest_media_mismatch_requires_initialization(tmp_path):
    wstore, qstore, cstore = _stores(tmp_path, manifest_media="docx")  # revision 은 hwpx
    outcome = _bootstrap(wstore, qstore, cstore)
    assert outcome.result == TEMPLATE_INITIALIZATION_REQUIRED and outcome.reason == "MEDIA_MISMATCH"
    assert not wstore.exists("W1")


def test_concurrent_create_collision_reconciles(tmp_path, monkeypatch):
    # exists() 가 놓친 동시 생성(WorkAggregateExists)을 기존 aggregate 로 화해한다.
    wstore, qstore, cstore = _stores(tmp_path)
    _bootstrap(wstore, qstore, cstore)  # W1 이미 존재
    monkeypatch.setattr(wstore, "exists", lambda _w: False)  # exists 우회 → initialize 가 충돌
    outcome = _bootstrap(wstore, qstore, cstore)  # 같은 request(같은 ids) 재전송
    assert outcome.result == BOOTSTRAP_OK
    assert outcome.aggregate.applications[0].application_id == "A1"  # 먼저 commit 한 것
