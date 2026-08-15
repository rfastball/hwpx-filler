"""capture·qualification stage 결선과 crash recovery 실행 (S3-05 #655).

S3-04 가 만든 CAPTURING Preparation 을 받아 (1) pinned binding 을 capture 해 Candidate object 를
durable 하게 쓰고, (2) exact bytes 를 S2 qualification 에 넘겨 Attempt/Evidence 를 durable 하게
쓰고, 각 단계 뒤 Work aggregate 에 checkpoint 를 **한 번** 전진시킨다. object 는 aggregate 가
참조하기 **전에** durable 하다(object-first). 판정·상태 전이는
:mod:`hwpxfiller.application.prepare_orchestration` 이 소유하고, 여기는 엔진(S3-02 capture·S2
qualify)과 store 를 결선하는 어댑터다.

stage object id 는 preparation_id 에서 결정론적으로 파생하므로 create-once store 가 stage 를
최대 한 번 실행하고(중복 worker 차단), restart 뒤 recovery 는 같은 id 를 재계산해 durable 결과를
찾는다 — capture·qualification 을 자동 재호출하지 않는다(S3 v1).
"""

from __future__ import annotations

from collections.abc import Callable

from hwpxfiller.application.candidate_revision import (
    SOURCE_BINDING_CHANGED,
    MutableSourceBinding,
    SourceCaptureError,
    TemplateLineage,
    TemplateSourceReader,
)
from hwpxfiller.application.prepare_orchestration import (
    derive_stage_ids,
    find_preparation,
    in_flight_preparations,
    plan_capture_checkpoint,
    plan_qualification_checkpoint,
    plan_recovery,
)
from hwpxfiller.application.candidate_revision import capture_candidate_revision
from hwpxfiller.application.qualification_evidence import build_records
from hwpxfiller.application.template_qualification import (
    CandidateRevisionSnapshot,
    QualificationProfile,
    qualify_template,
)
from hwpxfiller.application.work_template_state import (
    PREP_QUALIFYING,
    DocumentWork,
    TemplateChangePreparation,
)
from .candidate_store import CandidateObjectStore
from .qualification_store import ObjectNotFound as AttemptNotFound
from .qualification_store import QualificationObjectStore
from .work_template_store import AtomicWorkTemplateStateStore


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
    ids = derive_stage_ids(preparation_id)
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
    binding_changed = (
        isinstance(result, SourceCaptureError) and result.reason == SOURCE_BINDING_CHANGED
    )
    capture_failed = isinstance(result, SourceCaptureError) and not binding_changed
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
            binding_changed=binding_changed
            or current_generation != prep.source_binding_generation,
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
    projection_schema_version: str,
    engine_metadata: dict,
    started_at: str,
    completed_at: str,
    qualified_at: str,
) -> TemplateChangePreparation:
    """QUALIFYING Preparation 의 exact bytes 를 qualify 하고 Attempt/Evidence 를 durable 하게 쓴다."""
    prep = find_preparation(work_store.load(work_id), preparation_id)
    if prep.status != PREP_QUALIFYING:
        return prep  # capture 가 terminal/미완 → qualification 호출 0

    revision = candidate_store.get_revision(prep.revision_id)
    blob = candidate_store.get_blob(revision.exact_content_digest)
    result = qualify_template(
        CandidateRevisionSnapshot(prep.revision_id, blob.exact_bytes), profile
    )
    ids = derive_stage_ids(preparation_id)
    attempt, evidence = build_records(
        result,
        attempt_id=ids.attempt_id,
        preparation_id=preparation_id,
        evidence_id=ids.evidence_id,
        projection_schema_version=projection_schema_version,
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
    ids = derive_stage_ids(preparation_id)
    try:
        attempt = qualification_store.get_attempt(ids.attempt_id)
    except AttemptNotFound:
        attempt = None
    with work_store.update(work_id) as txn:
        txn.aggregate = plan_recovery(
            txn.aggregate,
            preparation_id,
            attempt_outcome=attempt.outcome if attempt is not None else None,
            attempt_id=attempt.attempt_id if attempt is not None else None,
            evidence_id=attempt.evidence_id if attempt is not None else None,
            completed_at=completed_at,
        )
    return find_preparation(work_store.load(work_id), preparation_id)


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
