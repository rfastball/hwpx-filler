"""S6-01(#809) production materialization runner — ref+store 조달과 postcondition 자격.

SG-02 가 증명한 executor/verifier 를 production 승격하는 러너의 계약을 검증한다:
- 입력은 harness 손조립이 아니라 **Plan ref → store 조달**이고 전 구간 digest fail-closed 다.
- postcondition PASS 만 bytes 를 낸다 — FAIL 은 9 코드 그대로 반환되고 bytes 를 노출하지 않는다.
- filesystem 을 건드리지 않는다(bytes 에서 멈춘다). delivery/start gate 는 후속 슬라이스 몫.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from hwpxfiller.application.candidate_revision import ContentBlob, blob_digest
from hwpxfiller.application.execution_contract_set import plan_semantic_digest
from hwpxfiller.application.execution_structure import execution_pass_projection
from hwpxfiller.application.generation_delivery import (
    MaterializationInput,
    MaterializationInputPort,
    MaterializationInputResolutionError,
)
from hwpxfiller.application.qualification_evidence import (
    QualificationAttempt,
    QualificationEvidence,
)
from hwpxfiller.application.record_validation import ImmutableVdrStore
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    SCHEMA_VERSION as WORK_SCHEMA,
    DocumentWork,
    WorkTemplateApplication,
    WorkTemplateStateAggregate,
)
from hwpxfiller.domain.fields import FillNote
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.materialization_conformance import (
    OCCURRENCE_COUNT_MISMATCH,
    STRUCTURE_BYTES_INCONSISTENT,
    ConformanceFailure,
)
from hwpxfiller.external.materialization_runner import (
    MaterializationProcurementError,
    MaterializedDocumentBytes,
    ProductionMaterializationRunner,
    production_materialization_runner,
    store_backed_structure_resolver,
)
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore

from tests._materialization_case import (
    APP,
    AT,
    POSITIVE,
    PROFILE,
    WORK,
    Case,
    Opt,
    SlotS,
    _build_case,
    _one_of_two,
    _synth_case,
)


# ─── 조립 helper ──────────────────────────────────────────────────────────────────────
def _memory_runner(
    case: Case,
    *,
    candidate_blob_resolver=None,
    structure_resolver=None,
) -> tuple[ProductionMaterializationRunner, MaterializationInput]:
    """in-memory resolver 로 러너를 세운다 — 기본 resolver 는 case 의 정합 입력을 준다."""
    vdr_store = ImmutableVdrStore()
    vdr_ref = vdr_store.put(case.vdr)
    plan_ref = plan_semantic_digest(case.plan)
    runner = ProductionMaterializationRunner(
        input_port=MaterializationInputPort(
            plan_resolver={plan_ref: case.plan}.__getitem__, vdr_store=vdr_store
        ),
        candidate_blob_resolver=candidate_blob_resolver or (lambda digest: case.bytes),
        structure_resolver=structure_resolver or (lambda plan: case.structure),
    )
    return runner, MaterializationInput(
        sealed_execution_plan_ref=plan_ref, validated_record_ref=vdr_ref
    )


def _seed_authority(root, case: Case, *, application_id: str = APP) -> None:
    """공유 authority root 규약(works/qualification/candidates)대로 실 store 를 seed 한다."""
    CandidateObjectStore(root / "candidates").put_blob(
        ContentBlob(
            digest=blob_digest(case.bytes), media="hwpx",
            exact_bytes=case.bytes, byte_length=len(case.bytes),
        )
    )
    qual = QualificationObjectStore(root / "qualification")
    qual.put_attempt(
        QualificationAttempt(
            attempt_id="at-1", preparation_id="prep-1", revision_id="rev-1",
            qualification_profile_id=PROFILE, outcome="PASS", evidence_id="ev-1",
            error_code=None, started_at=AT, completed_at=AT,
        )
    )
    qual.put_evidence(
        QualificationEvidence(
            evidence_id="ev-1", attempt_id="at-1", revision_id="rev-1",
            qualification_profile_id=PROFILE, result="PASS",
            structure_projection=execution_pass_projection(case.structure),
            diagnostics=(), engine_metadata={}, qualified_at=AT,
        )
    )
    AtomicWorkTemplateStateStore(root / "works").create(
        WorkTemplateStateAggregate(
            schema_version=WORK_SCHEMA, aggregate_version=1,
            work=DocumentWork(
                work_id=WORK, template_lineage_id="lin-1",
                current_template_application_id=application_id,
                current_template_preparation_id=None, prepare_seq=0,
            ),
            applications=(
                WorkTemplateApplication(
                    application_id=application_id, work_id=WORK, application_epoch=1,
                    pass_evidence_id="ev-1", previous_application_id=None,
                    origin=INITIALIZATION, prepared_change_id=None, actor="t", applied_at=AT,
                ),
            ),
            preparations=(), prepared_changes=(), apply_provenance=(), outbox_events=(),
        )
    )


# ═══ 양성: corpus 전건이 production 조달 경로로 완주한다 ═══════════════════════════════
@pytest.mark.parametrize("name", sorted(POSITIVE))
def test_positive_corpus_materializes_through_production_runner(name: str) -> None:
    case = _build_case(POSITIVE[name]())
    runner, mi = _memory_runner(case)
    outcome = runner.materialize(mi)
    assert isinstance(outcome, MaterializedDocumentBytes), outcome
    # 산출 증거가 입력 ref 와 output bytes 에 정합이다.
    assert outcome.plan_semantic_digest == mi.sealed_execution_plan_ref
    assert outcome.validated_record_ref == mi.validated_record_ref
    assert outcome.output_digest == blob_digest(outcome.output_bytes)
    assert outcome.output_bytes != case.bytes  # 실제 mutation 이 일어났다


def test_runner_surfaces_fill_notes_not_swallowed() -> None:
    # 채움 완화(slot_synthesized)는 러너 산출에 그대로 실린다(confirm-or-alarm).
    case = _build_case(_synth_case())
    runner, mi = _memory_runner(case)
    outcome = runner.materialize(mi)
    assert isinstance(outcome, MaterializedDocumentBytes)
    assert FillNote("빈칸", "slot_synthesized") in outcome.execution_notes


def test_source_candidate_bytes_unmutated_by_runner() -> None:
    # S6-5: 러너 완주 후에도 source blob bytes 는 Plan 의 digest 그대로다.
    case = _build_case(_one_of_two())
    runner, mi = _memory_runner(case)
    assert isinstance(runner.materialize(mi), MaterializedDocumentBytes)
    assert blob_digest(case.bytes) == case.plan.execution_basis.template.exact_content_digest


# ═══ 실패 경로 1 — postcondition/precheck 실패는 9 코드 그대로, bytes 미노출 ═══════════
def test_structure_bytes_lie_returns_p7_failure() -> None:
    # 모든 digest 가 정합인데 structure↔bytes 대응만 어긋난 Plan(봉인 시점 거짓말) —
    # blob·structure digest 검사는 각자 자신만 증명하므로 P7 이 유일하게 잡는다.
    spec = _one_of_two()
    lied_bytes = replace(
        spec,
        slots=(SlotS("s1", ("주소",), (Opt("o1", ("항목",)), Opt("o3", ("금액",))), selected="o1"),),
    )
    case = _build_case(spec, bytes_from=lied_bytes)
    runner, mi = _memory_runner(case)
    outcome = runner.materialize(mi)
    assert isinstance(outcome, ConformanceFailure)
    assert outcome.code == STRUCTURE_BYTES_INCONSISTENT
    assert not hasattr(outcome, "output_bytes")  # 실패는 bytes 를 노출하지 않는다(S6-3)


def test_occurrence_lie_returns_postcondition_failure() -> None:
    # P7 은 field id 집합만 보므로 occurrence 수 거짓말은 통과한다 — mutation 후 재검사(P3)가
    # 자격 조건임을 러너 경로에서 증명한다(remove/write 성공 != Artifact 자격).
    spec = _one_of_two()  # structure 는 성명 occurrence 2 를 봉인
    case = _build_case(spec, bytes_from=replace(spec, root_fields=("성명",)))
    runner, mi = _memory_runner(case)
    outcome = runner.materialize(mi)
    assert isinstance(outcome, ConformanceFailure)
    assert outcome.code == OCCURRENCE_COUNT_MISMATCH
    assert not hasattr(outcome, "output_bytes")


# ═══ 실패 경로 2 — 조달 실패는 loud 예외(9 코드와 다른 층) ════════════════════════════
def test_candidate_blob_mismatch_fails_closed() -> None:
    case = _build_case(_one_of_two())
    other = _build_case(_synth_case())
    runner, mi = _memory_runner(case, candidate_blob_resolver=lambda digest: other.bytes)
    with pytest.raises(MaterializationProcurementError):
        runner.materialize(mi)


def test_structure_resolver_mismatch_fails_closed() -> None:
    case = _build_case(_one_of_two())
    other = _build_case(_synth_case())
    runner, mi = _memory_runner(case, structure_resolver=lambda plan: other.structure)
    with pytest.raises(MaterializationProcurementError):
        runner.materialize(mi)


def test_plan_ref_mismatch_propagates_from_input_port() -> None:
    # Plan resolve 재검증은 기존 MaterializationInputPort 가 진다 — 러너는 재판정하지 않는다.
    case = _build_case(_one_of_two())
    vdr_store = ImmutableVdrStore()
    vdr_ref = vdr_store.put(case.vdr)
    runner = ProductionMaterializationRunner(
        input_port=MaterializationInputPort(
            plan_resolver=lambda ref: case.plan, vdr_store=vdr_store
        ),
        candidate_blob_resolver=lambda digest: case.bytes,
        structure_resolver=lambda plan: case.structure,
    )
    with pytest.raises(MaterializationInputResolutionError):
        runner.materialize(
            MaterializationInput(
                sealed_execution_plan_ref="sha256:wrong", validated_record_ref=vdr_ref
            )
        )


def test_vdr_cross_bind_failure_propagates_from_input_port() -> None:
    # 다른 Plan 에 결속된 VDR 는 port 의 cross-bind 가 닫는다.
    case = _build_case(_one_of_two())
    other = _build_case(_synth_case())
    vdr_store = ImmutableVdrStore()
    other_vdr_ref = vdr_store.put(other.vdr)
    plan_ref = plan_semantic_digest(case.plan)
    runner = ProductionMaterializationRunner(
        input_port=MaterializationInputPort(
            plan_resolver={plan_ref: case.plan}.__getitem__, vdr_store=vdr_store
        ),
        candidate_blob_resolver=lambda digest: case.bytes,
        structure_resolver=lambda plan: case.structure,
    )
    with pytest.raises(MaterializationInputResolutionError):
        runner.materialize(
            MaterializationInput(
                sealed_execution_plan_ref=plan_ref, validated_record_ref=other_vdr_ref
            )
        )


# ═══ 실 store 결선(공유 authority root 규약) ══════════════════════════════════════════
def test_store_backed_wiring_materializes_roundtrip(tmp_path) -> None:
    case = _build_case(_one_of_two())
    _seed_authority(tmp_path, case)
    vdr_store = ImmutableVdrStore()
    vdr_ref = vdr_store.put(case.vdr)
    plan_ref = plan_semantic_digest(case.plan)
    runner = production_materialization_runner(
        tmp_path, plan_resolver={plan_ref: case.plan}.__getitem__, vdr_store=vdr_store
    )
    outcome = runner.materialize(
        MaterializationInput(
            sealed_execution_plan_ref=plan_ref, validated_record_ref=vdr_ref
        )
    )
    assert isinstance(outcome, MaterializedDocumentBytes), outcome
    assert outcome.output_digest == blob_digest(outcome.output_bytes)


def test_store_backed_structure_resolver_rejects_missing_application(tmp_path) -> None:
    case = _build_case(_one_of_two())
    _seed_authority(tmp_path, case, application_id="app-other")
    resolver = store_backed_structure_resolver(
        work_state_store=AtomicWorkTemplateStateStore(tmp_path / "works"),
        qualification_store=QualificationObjectStore(tmp_path / "qualification"),
    )
    with pytest.raises(MaterializationProcurementError):
        resolver(case.plan)  # Plan 은 APP 를 가리키는데 aggregate 엔 없다


def test_store_backed_structure_resolver_rejects_absent_projection(tmp_path) -> None:
    case = _build_case(_one_of_two())
    qual = QualificationObjectStore(tmp_path / "qualification")
    qual.put_attempt(
        QualificationAttempt(
            attempt_id="at-1", preparation_id="prep-1", revision_id="rev-1",
            qualification_profile_id=PROFILE, outcome="FAIL", evidence_id="ev-1",
            error_code=None, started_at=AT, completed_at=AT,
        )
    )
    qual.put_evidence(
        QualificationEvidence(
            evidence_id="ev-1", attempt_id="at-1", revision_id="rev-1",
            qualification_profile_id=PROFILE, result="FAIL", structure_projection=None,
            diagnostics=({"code": "X", "message": "x"},), engine_metadata={}, qualified_at=AT,
        )
    )
    AtomicWorkTemplateStateStore(tmp_path / "works").create(
        WorkTemplateStateAggregate(
            schema_version=WORK_SCHEMA, aggregate_version=1,
            work=DocumentWork(
                work_id=WORK, template_lineage_id="lin-1",
                current_template_application_id=APP,
                current_template_preparation_id=None, prepare_seq=0,
            ),
            applications=(
                WorkTemplateApplication(
                    application_id=APP, work_id=WORK, application_epoch=1,
                    pass_evidence_id="ev-1", previous_application_id=None,
                    origin=INITIALIZATION, prepared_change_id=None, actor="t", applied_at=AT,
                ),
            ),
            preparations=(), prepared_changes=(), apply_provenance=(), outbox_events=(),
        )
    )
    resolver = store_backed_structure_resolver(
        work_state_store=AtomicWorkTemplateStateStore(tmp_path / "works"),
        qualification_store=QualificationObjectStore(tmp_path / "qualification"),
    )
    with pytest.raises(MaterializationProcurementError):
        resolver(case.plan)
