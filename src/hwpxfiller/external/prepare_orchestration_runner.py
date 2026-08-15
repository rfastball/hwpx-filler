"""capture·qualification stage 결선과 crash recovery 실행 (S3-05 #655).

S3-04 가 만든 CAPTURING Preparation 을 받아 (1) pinned binding 을 capture 해 Candidate object 를
durable 하게 쓰고, (2) exact bytes 를 S2 qualification 에 넘겨 Attempt/Evidence 를 durable 하게
쓰고, 각 단계 뒤 Work aggregate 에 checkpoint 를 **한 번** 전진시킨다. object 는 aggregate 가
참조하기 **전에** durable 하다(object-first). 판정·상태 전이는
:mod:`hwpxfiller.application.prepare_orchestration` 이 소유하고, 여기는 엔진(S3-02 capture·S2
qualify)과 store 를 결선하는 어댑터다.

이 어댑터는 **신뢰 경계**다 — caller 가 넘긴 binding·lineage·profile 을 실행 전에 Preparation 이
서버에서 고정한 pin 과 대조하고, stage object id 는 (work_id, preparation_id)에서 결정론적으로
파생한다. 그래서 create-once store 가 stage 를 최대 한 번 실행하고(중복 worker 차단), restart 뒤
recovery 는 같은 id 를 재계산해 durable 결과를 찾는다 — capture·qualification 을 자동 재호출하지
않는다(S3 v1). 비-CAPTURING/이미 attempt 붙은 Preparation 은 reader/inspector 를 **부르기 전에**
short-circuit 한다.
"""

from __future__ import annotations

from collections.abc import Callable

from hwpxfiller.application.candidate_revision import (
    MutableSourceBinding,
    SourceCaptureError,
    TemplateLineage,
    TemplateSourceReader,
    capture_candidate_revision,
)
from hwpxfiller.application.prepare_orchestration import (
    derive_stage_ids,
    find_preparation,
    in_flight_preparations,
    plan_capture_checkpoint,
    plan_qualification_checkpoint,
    plan_recovery,
)
from hwpxfiller.application.qualification_evidence import ERROR, build_records
from hwpxfiller.application.template_qualification import (
    CandidateRevisionSnapshot,
    QualificationProfile,
    qualify_template,
)
from hwpxfiller.application.work_template_state import (
    PREP_CAPTURING,
    PREP_QUALIFYING,
    DocumentWork,
    TemplateChangePreparation,
)
from .candidate_store import CandidateObjectStore
from .qualification_store import ObjectNotFound as QualObjectNotFound
from .qualification_store import QualificationObjectStore
from .work_template_store import AtomicWorkTemplateStateStore, WorkTemplateStoreError


def run_capture_stage(
    work_store: AtomicWorkTemplateStateStore,
    candidate_store: CandidateObjectStore,
    *,
    work_id: str,
    preparation_id: str,
    lineage: TemplateLineage,
    binding: MutableSourceBinding,
    reader: TemplateSourceReader,
    resolve_current_generation: "Callable[[DocumentWork], int]",
    captured_at: str,
    created_at: str,
) -> TemplateChangePreparation:
    """pinned binding 을 capture 해 Candidate 를 durable 하게 쓰고 capture checkpoint 를 전진시킨다."""
    aggregate = work_store.load(work_id)
    prep = find_preparation(aggregate, preparation_id)
    if prep.status != PREP_CAPTURING:
        return prep  # 이미 전진했거나 terminal — reader 를 부르지 않는다(at-most-once)
    # 신뢰 경계: caller 가 넘긴 source 를 Preparation 의 서버 pin 과 대조한다. 서로 정합해도
    # pin 과 다르면 다른 source 를 이 Preparation 의 revision 으로 붙이는 것이라 거절한다.
    if (
        binding.source_binding_id != prep.source_binding_id
        or binding.generation != prep.source_binding_generation
        or lineage.template_lineage_id != aggregate.work.template_lineage_id
    ):
        raise WorkTemplateStoreError(
            f"capture 입력이 Preparation {preparation_id} 의 pin 과 불일치"
        )

    ids = derive_stage_ids(work_id, preparation_id)
    result = capture_candidate_revision(
        lineage=lineage,
        binding=binding,
        preparation_id=preparation_id,
        reader=reader,
        store=candidate_store,
        observation_id=ids.observation_id,
        revision_id=ids.revision_id,
        captured_at=captured_at,
        created_at=created_at,
    )
    capture_failed = isinstance(result, SourceCaptureError)
    reason = result.reason if isinstance(result, SourceCaptureError) else None
    with work_store.update(work_id) as txn:
        prep = find_preparation(txn.aggregate, preparation_id)
        # commit 시점 current binding 재확인 — capture window 동안 source 가 움직였으면 terminal.
        current_generation = resolve_current_generation(txn.aggregate.work)
        txn.aggregate = plan_capture_checkpoint(
            txn.aggregate,
            preparation_id,
            observation_id=ids.observation_id,
            revision_id=ids.revision_id,
            capture_failed=capture_failed,
            capture_error_reason=reason,
            binding_changed=current_generation != prep.source_binding_generation,
            completed_at=captured_at,
        )
    return find_preparation(work_store.load(work_id), preparation_id)


def run_qualification_stage(
    work_store: AtomicWorkTemplateStateStore,
    candidate_store: CandidateObjectStore,
    qualification_store: QualificationObjectStore,
    *,
    work_id: str,
    preparation_id: str,
    profile: QualificationProfile,
    engine_metadata: dict,
    started_at: str,
    completed_at: str,
    qualified_at: str,
) -> TemplateChangePreparation:
    """QUALIFYING Preparation 의 exact bytes 를 qualify 하고 Attempt/Evidence 를 durable 하게 쓴다."""
    prep = find_preparation(work_store.load(work_id), preparation_id)
    # QUALIFYING 아니거나 이미 attempt 가 붙었으면(PASS checkpoint 뒤 중복 delivery 포함) 호출 0.
    if prep.status != PREP_QUALIFYING or prep.attempt_id is not None:
        return prep
    # 신뢰 경계: runtime profile 과 그 projection schema 를 Preparation·Manifest pin 에 못박는다.
    if profile.id != prep.qualification_profile_id:
        raise WorkTemplateStoreError(
            f"qualification profile 이 Preparation {preparation_id} 의 pin 과 불일치"
        )
    manifest = qualification_store.get_manifest(prep.qualification_profile_id)

    revision = candidate_store.get_revision(prep.revision_id)
    blob = candidate_store.get_blob(revision.exact_content_digest)
    result = qualify_template(
        CandidateRevisionSnapshot(prep.revision_id, blob.exact_bytes), profile
    )
    ids = derive_stage_ids(work_id, preparation_id)
    attempt, evidence = build_records(
        result,
        attempt_id=ids.attempt_id,
        preparation_id=preparation_id,
        evidence_id=ids.evidence_id,
        projection_schema_version=manifest.projection_schema_version,  # caller 값 대신 pin
        engine_metadata=engine_metadata,
        started_at=started_at,
        completed_at=completed_at,
        qualified_at=qualified_at,
    )
    qualification_store.put_attempt(attempt)  # object-first
    if evidence is not None:
        qualification_store.put_evidence(evidence)
    with work_store.update(work_id) as txn:
        txn.aggregate = plan_qualification_checkpoint(
            txn.aggregate,
            preparation_id,
            outcome=attempt.outcome,
            attempt_id=attempt.attempt_id,
            evidence_id=evidence.evidence_id if evidence is not None else None,
            completed_at=completed_at,
        )
    return find_preparation(work_store.load(work_id), preparation_id)


def recover_preparation(
    work_store: AtomicWorkTemplateStateStore,
    qualification_store: QualificationObjectStore,
    *,
    work_id: str,
    preparation_id: str,
    completed_at: str,
) -> TemplateChangePreparation:
    """in-flight Preparation 을 durable Attempt 로 reconcile(없으면 INTERRUPTED). 재호출 없음."""
    ids = derive_stage_ids(work_id, preparation_id)
    outcome, attempt_id, evidence_id = _durable_attempt_result(qualification_store, ids)
    with work_store.update(work_id) as txn:
        txn.aggregate = plan_recovery(
            txn.aggregate,
            preparation_id,
            attempt_outcome=outcome,
            attempt_id=attempt_id,
            evidence_id=evidence_id,
            completed_at=completed_at,
        )
    return find_preparation(work_store.load(work_id), preparation_id)


def _durable_attempt_result(qualification_store, ids):
    """durable Attempt 를 읽되, PASS/FAIL 은 그 Evidence 가 실재할 때만 완료로 친다.

    put_attempt 뒤 put_evidence 전에 죽으면 Attempt 만 있고 Evidence 가 없다 — 그때 evidence_id 를
    checkpoint 에 복사하면 dangling reference 가 durable 해진다. 그래서 Evidence 미실재면 미완으로
    보고(INTERRUPTED) 자동 재호출은 하지 않는다.
    """
    try:
        attempt = qualification_store.get_attempt(ids.attempt_id)
    except QualObjectNotFound:
        return None, None, None
    if attempt.outcome == ERROR:
        return attempt.outcome, attempt.attempt_id, None
    try:
        qualification_store.get_evidence(attempt.evidence_id)
    except QualObjectNotFound:
        return None, None, None  # write window 미완 — 복원하지 않는다
    return attempt.outcome, attempt.attempt_id, attempt.evidence_id


def recover_session(
    work_store: AtomicWorkTemplateStateStore,
    qualification_store: QualificationObjectStore,
    *,
    work_id: str,
    current_session_id: str,
    completed_at: str,
) -> tuple[TemplateChangePreparation, ...]:
    """이전 session 의 미완 Preparation 을 전부 reconcile 한다(startup/첫 load recovery)."""
    prior = in_flight_preparations(work_store.load(work_id), current_session_id)
    return tuple(
        recover_preparation(
            work_store, qualification_store,
            work_id=work_id, preparation_id=prep.preparation_id, completed_at=completed_at,
        )
        for prep in prior
    )
