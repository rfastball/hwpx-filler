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
from dataclasses import dataclass

from hwpxfiller.host.per_work_fence import per_work_mutation_fence

from hwpxfiller.application.candidate_revision import (
    MutableSourceBinding,
    SourceCaptureError,
    TemplateLineage,
    TemplateSourceReader,
    capture_candidate_revision,
)
from hwpxfiller.application.work_bootstrap import (
    BOOTSTRAP_OK,
    TEMPLATE_INITIALIZATION_REQUIRED,
    BootstrapOutcome,
)
from hwpxfiller.application.prepare_orchestration import (
    APPLY_ALREADY_APPLIED,
    APPLY_APPLIED,
    APPLY_APPLIED_THEN_ADVANCED,
    APPLY_CONFLICT,
    APPLY_INTEGRITY_ERROR,
    APPLY_REJECTED,
    APPLY_SUPERSEDED,
    ApplyOutcome,
    derive_stage_ids,
    find_application,
    find_change,
    find_preparation,
    in_flight_preparations,
    plan_admission_ready,
    plan_admission_terminal,
    plan_apply,
    plan_capture_checkpoint,
    plan_change_status,
    plan_qualification_checkpoint,
    plan_recovery,
)
from hwpxfiller.application.execution_structure import (
    execution_pass_projection,
    is_supported_execution_projection,
)
from hwpxfiller.application.qualification_evidence import (
    ERROR,
    PASS,
    StructureProjection,
    build_records,
)
from hwpxfiller.application.template_qualification import (
    CandidateRevisionSnapshot,
    QualificationProfile,
    TemplateQualificationPassed,
    TemplateQualificationResult,
    qualify_template,
)
from hwpxfiller.application.work_template_state import (
    CHANGE_APPLIED,
    CHANGE_CONFLICTED,
    CHANGE_PREPARED,
    CHANGE_REJECTED,
    CHANGE_SUPERSEDED,
    PREP_BASE_CHANGED,
    PREP_CAPTURING,
    PREP_NO_CHANGE,
    PREP_PROFILE_REVOKED,
    PREP_QUALIFYING,
    PREP_READY,
    PREP_SOURCE_BINDING_CHANGED,
    PREP_SUPERSEDED,
    DocumentWork,
    MigrationProvenance,
    PreparedTemplateChange,
    TemplateChangePreparation,
    WorkTemplateStateAggregate,
)
from .work_template_store import initialize_work
from .candidate_store import ObjectCorrupt as CandidateCorrupt
from .candidate_store import ObjectNotFound as CandidateNotFound
from .candidate_store import CandidateObjectStore
from .qualification_store import ObjectCorrupt as QualCorrupt
from .qualification_store import ObjectNotFound as QualObjectNotFound
from .qualification_store import QualificationObjectStore
from .work_template_store import (
    AtomicWorkTemplateStateStore,
    WorkAggregateExists,
    WorkTemplateStoreError,
)

_INTEGRITY_ERRORS = (CandidateNotFound, CandidateCorrupt, QualObjectNotFound, QualCorrupt)


@dataclass(frozen=True)
class AdmissionResult:
    change: PreparedTemplateChange | None
    aggregate: WorkTemplateStateAggregate


# ponytail: 고정 상한. optimistic Profile discovery 는 process-local fence 아래 exact re-read 로
# 즉시 수렴하므로 실전 반복은 사실상 1 이다 — 상한은 pathological churn 을 유한 시간에 시끄럽게
# 종료시키는 안전판이다(처리량 이슈 시 #620 계열에서 상향).
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


def _composition_projection(
    qualification: TemplateQualificationResult, projection_schema_version: str
) -> StructureProjection | None:
    """manifest 가 composition-ready schema 를 pin 했으면 그 PASS projection 을 고정한다(#773).

    schema 는 Profile manifest 의 pin 이고 evidence 는 그 pin 을 따른다. pin 이 composition-ready
    인데 inspection 이 execution structure 를 내지 않았으면 **시끄럽게 닫는다** — product-only
    projection 으로 조용히 되돌아가면 S5 가 나중에 decode 불가로 넘어져 원인이 여기서 멀어진다.
    """
    # composition-ready schema **전부**를 잡는다(v2·v4). v4 만 보면, manifest 가 v2 를 pin 했을 때
    # build_records 가 조용히 product-only payload 를 v2 label 로 써 버린다 — #773 이 없애려는
    # 그 결함을 다른 schema 에 그대로 남기는 셈이다.
    if not is_supported_execution_projection(projection_schema_version):
        return None
    if not isinstance(qualification, TemplateQualificationPassed):
        return None  # FAIL/ERROR 는 Evidence 에 structure 를 싣지 않는다.
    execution_structure = qualification.execution_structure
    if execution_structure is None:
        raise WorkTemplateStoreError(
            f"Profile 이 {projection_schema_version} 를 pin 했는데 inspection 이 "
            "composition-ready structure 를 내지 않았다"
        )
    return execution_pass_projection(execution_structure)


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
        structure_projection=_composition_projection(
            result, manifest.projection_schema_version
        ),
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


def admit_preparation(
    work_store: AtomicWorkTemplateStateStore,
    candidate_store: CandidateObjectStore,
    qualification_store: QualificationObjectStore,
    *,
    work_id: str,
    preparation_id: str,
    resolve_current_binding: "Callable[[DocumentWork], tuple[str, int]]",
    prepared_change_id: str,
    prepared_at: str,
) -> AdmissionResult:
    """durable PASS checkpoint 를 ordered gate 로 admission 한다 — READY+Change 또는 fail-closed.

    idempotent: 이미 READY 면 기존 Change 를, terminal 이면 무변경으로 닫는다. current intent·exact
    base·source binding·Profile revocation·exact PASS Evidence 를 완료 시점 값으로 rebase 하지 않고
    **재검사**하고, current target 과 operational 동치면 NO_CHANGE 로 닫는다(Work 변경 없음).
    """
    with work_store.update(work_id) as txn:
        aggregate = txn.aggregate
        prep = find_preparation(aggregate, preparation_id)
        if prep.status == PREP_READY:  # idempotent — 기존 Change 반환, 무변경
            return AdmissionResult(
                find_change(aggregate, prep.prepared_change_id), aggregate
            )
        if prep.status != PREP_QUALIFYING or prep.attempt_id is None:
            return AdmissionResult(None, aggregate)  # terminal/아직 PASS checkpoint 없음

        terminal = _admission_gate(
            aggregate, prep, candidate_store, qualification_store, resolve_current_binding
        )
        if terminal is not None:
            txn.aggregate = plan_admission_terminal(
                aggregate, preparation_id, terminal, completed_at=prepared_at
            )
            return AdmissionResult(None, txn.aggregate)
        txn.aggregate = plan_admission_ready(
            aggregate, preparation_id,
            prepared_change_id=prepared_change_id,
            target_pass_evidence_id=prep.evidence_id,
            prepared_at=prepared_at,
        )
        return AdmissionResult(
            find_change(txn.aggregate, prepared_change_id), txn.aggregate
        )


def _admission_gate(
    aggregate, prep, candidate_store, qualification_store, resolve_current_binding
) -> str | None:
    """ordered admission gate — 실패면 terminal status, 통과면 None. Evidence 무결성 위반은 loud."""
    if aggregate.work.current_template_preparation_id != prep.preparation_id:
        return PREP_SUPERSEDED  # current intent 아님
    if aggregate.work.current_template_application_id != prep.base_application_id:
        return PREP_BASE_CHANGED  # current base 를 완료 시점 값으로 rebase 하지 않는다
    if resolve_current_binding(aggregate.work) != (
        prep.source_binding_id,
        prep.source_binding_generation,
    ):
        return PREP_SOURCE_BINDING_CHANGED
    if qualification_store.is_revoked(prep.qualification_profile_id):
        return PREP_PROFILE_REVOKED

    evidence = qualification_store.get_evidence(prep.evidence_id)
    if (
        evidence.result != PASS
        or evidence.attempt_id != prep.attempt_id  # 이 Preparation 의 attempt 에서 나온 evidence 인가
        or evidence.revision_id != prep.revision_id
        or evidence.qualification_profile_id != prep.qualification_profile_id
        or evidence.structure_projection is None
    ):
        raise WorkTemplateStoreError(
            f"admission: PASS Evidence 가 Preparation {prep.preparation_id} pin 과 불일치"
        )

    current_app = find_application(aggregate, aggregate.work.current_template_application_id)
    current_evidence = qualification_store.get_evidence(current_app.pass_evidence_id)
    if _operational_target(candidate_store, evidence) == _operational_target(
        candidate_store, current_evidence
    ):
        return PREP_NO_CHANGE  # lineage·media·digest·profile 동치 — Work 변경 아님
    return None


def _operational_target(candidate_store, evidence):
    """v1 operational equivalence key — (lineage, media, exact digest, profile)."""
    revision = candidate_store.get_revision(evidence.revision_id)
    return (
        revision.template_lineage_id,
        revision.media,
        revision.exact_content_digest,
        evidence.qualification_profile_id,
    )


_TERMINAL_RESULT = {
    CHANGE_SUPERSEDED: APPLY_SUPERSEDED,
    CHANGE_CONFLICTED: APPLY_CONFLICT,
    CHANGE_REJECTED: APPLY_REJECTED,
}


def apply_prepared_change(
    work_store: AtomicWorkTemplateStateStore,
    candidate_store: CandidateObjectStore,
    qualification_store: QualificationObjectStore,
    *,
    workspace_instance_id: str,
    work_id: str,
    change_id: str,
    actor: str,
    authorize: "Callable[[DocumentWork, str], None]",
    new_application_id: str,
    provenance_id: str,
    outbox_event_id: str,
    applied_at: str,
) -> tuple[ApplyOutcome, WorkTemplateStateAggregate]:
    """fence-first public entry — global lock order ``PerWorkFence → Store lease``.

    **S5F R2-05b(#740): ProfileFence·optimistic Profile discovery·bounded retry 를 제거했다.** profile
    은 immutable Template Application 의 함수라 fence 사이에 따로 관측할 대상이 아니다 — PerWorkFence
    하나 아래에서 change_id 로 exact Prepared Change 를 직접 적용한다. 새 Apply 의 fail-closed 는 exact
    PASS QualificationEvidence 무결성(:func:`_apply_integrity`)과 Work-local currentness(current
    preparation·base·source binding·profile revocation via qualification store·lineage/media)로 닫힌다
    (R2-05a 에서 mutable admission gate 는 이미 제거).

    commit 된 aggregate 를 **같은 fence 아래에서** 다시 읽어 함께 돌려준다 — fence 밖 reload 는
    그 사이 다른 apply 가 끼어들어 outcome↔view 가 어긋날 수 있다.
    """
    with per_work_mutation_fence(workspace_instance_id, work_id):
        outcome = apply_prepared_change_under_fence(
            work_store,
            candidate_store,
            qualification_store,
            work_id=work_id,
            change_id=change_id,
            actor=actor,
            authorize=authorize,
            new_application_id=new_application_id,
            provenance_id=provenance_id,
            outbox_event_id=outbox_event_id,
            applied_at=applied_at,
        )
        return outcome, work_store.load(work_id)


def apply_prepared_change_under_fence(
    work_store: AtomicWorkTemplateStateStore,
    candidate_store: CandidateObjectStore,
    qualification_store: QualificationObjectStore,
    *,
    work_id: str,
    change_id: str,
    actor: str,
    authorize: "Callable[[DocumentWork, str], None]",
    new_application_id: str,
    provenance_id: str,
    outbox_event_id: str,
    applied_at: str,
) -> ApplyOutcome:
    """Prepared Change 를 fixed base 에서 Work 에 원자 적용한다 — source/qualification 재실행 없음.

    **ProfileFence·WorkFence 를 이미 잡은 caller 만 호출한다**(public ``apply_prepared_change``
    를 통한다). 직접 호출 금지는 ``tests/repo_contract/test_per_work_fence_gate.py`` 가 강제한다.

    S5F R2-05a(#740): mutable Profile admission gate 를 제거했다 — 새 Apply 의 fail-closed 는 exact
    PASS QualificationEvidence 무결성(:func:`_apply_integrity`)과 Work-local currentness(current
    Preparation·exact base·source binding·profile revocation via qualification store·lineage/media)로
    닫힌다. status-first idempotency(APPLIED 는 current 위치에 따라 ALREADY_APPLIED/APPLIED_THEN_ADVANCED,
    이미 terminal 이면 그 결과)를 먼저 닫고, PREPARED 만 **완료 시점 값으로 rebase 없이** 재검사한다.
    object missing·digest 손상은 일반 conflict 가 아니라 INTEGRITY_ERROR 로 상태 무변경 종료다.
    """
    holder: dict = {"outcome": None}
    with work_store.update(work_id) as txn:
        aggregate = txn.aggregate
        change = find_change(aggregate, change_id)  # 없으면 loud
        authorize(aggregate.work, actor)  # Work 접근·Template 적용 권한

        if change.status == CHANGE_APPLIED:  # idempotency 먼저
            result = (
                APPLY_ALREADY_APPLIED
                if aggregate.work.current_template_application_id
                == change.resulting_application_id
                else APPLY_APPLIED_THEN_ADVANCED
            )
            return ApplyOutcome(result, change.resulting_application_id)
        if change.status != CHANGE_PREPARED:  # SUPERSEDED/CONFLICTED/REJECTED 이력 반환
            return ApplyOutcome(_TERMINAL_RESULT[change.status], None)

        prep = find_preparation(aggregate, change.preparation_id)
        # conflict 분류(ordered) — Change status 로만 닫고 base 를 자동 rebase 하지 않는다.
        if (
            aggregate.work.current_template_preparation_id != prep.preparation_id
            or prep.status != PREP_READY
            or prep.prepared_change_id != change_id
        ):
            conflict = (CHANGE_SUPERSEDED, APPLY_SUPERSEDED)  # newer Preparation 이 current
        elif aggregate.work.current_template_application_id != change.base_application_id:
            conflict = (CHANGE_CONFLICTED, APPLY_CONFLICT)  # base 전진
        elif qualification_store.is_revoked(prep.qualification_profile_id):
            conflict = (CHANGE_REJECTED, APPLY_REJECTED)
        else:
            conflict = None
        if conflict is not None:
            change_status, result = conflict
            txn.aggregate = plan_change_status(aggregate, change_id, change_status)
            return ApplyOutcome(result, None)

        if not _apply_integrity(candidate_store, qualification_store, aggregate, prep, change):
            return ApplyOutcome(APPLY_INTEGRITY_ERROR, None)  # 상태 무변경

        txn.aggregate = plan_apply(
            aggregate, change,
            new_application_id=new_application_id, provenance_id=provenance_id,
            outbox_event_id=outbox_event_id, actor=actor, applied_at=applied_at,
        )
        holder["outcome"] = ApplyOutcome(APPLY_APPLIED, new_application_id)
    return holder["outcome"]


def _apply_integrity(candidate_store, qualification_store, aggregate, prep, change) -> bool:
    """exact Attempt↔Evidence↔Revision·digest·lineage/media·Manifest 재검증(revocation 은 conflict 축)."""
    try:
        evidence = qualification_store.get_evidence(change.target_pass_evidence_id)
        attempt = qualification_store.get_attempt(prep.attempt_id)  # Attempt 실재도 요구
        if (
            evidence.result != PASS
            or evidence.structure_projection is None
            or attempt.outcome != PASS
            or attempt.evidence_id != evidence.evidence_id  # 완전 Attempt↔Evidence 결속
            or evidence.attempt_id != attempt.attempt_id
            or attempt.attempt_id != prep.attempt_id
            or evidence.revision_id != prep.revision_id
            or evidence.qualification_profile_id != prep.qualification_profile_id
        ):
            return False
        revision = candidate_store.get_revision(evidence.revision_id)
        candidate_store.get_blob(revision.exact_content_digest)  # 재해시로 digest 검증
        manifest = qualification_store.get_manifest(prep.qualification_profile_id)
        current = find_application(aggregate, aggregate.work.current_template_application_id)
        current_revision = candidate_store.get_revision(
            qualification_store.get_evidence(current.pass_evidence_id).revision_id
        )
    except _INTEGRITY_ERRORS:
        return False
    return (
        revision.template_lineage_id == aggregate.work.template_lineage_id
        and manifest.media == revision.media  # profile 이 이 media 를 위한 것인가
        and revision.media == current_revision.media  # 같은 Work 는 media 를 못 바꾼다
    )


def bootstrap_work(
    work_store: AtomicWorkTemplateStateStore,
    candidate_store: CandidateObjectStore,
    qualification_store: QualificationObjectStore,
    *,
    work_id: str,
    bootstrap_request_id: str,
    lineage: TemplateLineage,
    binding: MutableSourceBinding,
    reader: TemplateSourceReader,
    profile: QualificationProfile,
    legacy_template_revision: int,
    legacy_binding_revision: int,
    legacy_source_reference: str,
    observation_id: str,
    revision_id: str,
    attempt_id: str,
    evidence_id: str,
    application_id: str,
    engine_metadata: dict,
    actor: str,
    captured_at: str,
    created_at: str,
    started_at: str,
    completed_at: str,
    qualified_at: str,
) -> BootstrapOutcome:
    """legacy Job 을 명시적으로 capture→qualify→PASS→INITIALIZATION Application 으로 bootstrap 한다.

    read migration 이 아니다 — legacy Job JSON 은 읽지도 고치지도 않는다(caller 가 legacy counter·
    source reference 를 넘긴다). capture/qualification 실패는 가짜 Application 을 만들지 않고
    TEMPLATE_INITIALIZATION_REQUIRED 로 닫는다(repair 대상). 같은 work_id 재전송은 멱등하다.
    """
    if work_store.exists(work_id):  # 이미 bootstrap 됨 — 멱등 반환
        return BootstrapOutcome(BOOTSTRAP_OK, work_store.load(work_id))

    capture = capture_candidate_revision(
        lineage=lineage, binding=binding, preparation_id=bootstrap_request_id, reader=reader,
        store=candidate_store, observation_id=observation_id, revision_id=revision_id,
        captured_at=captured_at, created_at=created_at,
    )
    if isinstance(capture, SourceCaptureError):
        return BootstrapOutcome(TEMPLATE_INITIALIZATION_REQUIRED, reason=capture.reason)

    manifest = qualification_store.get_manifest(profile.id)
    qualification = qualify_template(
        CandidateRevisionSnapshot(revision_id, capture.blob.exact_bytes), profile
    )
    attempt, evidence = build_records(
        qualification,
        attempt_id=attempt_id,
        preparation_id=bootstrap_request_id,
        evidence_id=evidence_id,
        projection_schema_version=manifest.projection_schema_version,
        engine_metadata=engine_metadata,
        started_at=started_at,
        completed_at=completed_at,
        qualified_at=qualified_at,
        structure_projection=_composition_projection(
            qualification, manifest.projection_schema_version
        ),
    )
    qualification_store.put_attempt(attempt)  # object-first
    if evidence is not None:
        qualification_store.put_evidence(evidence)
    if attempt.outcome != PASS:  # FAIL/ERROR → repair required, legacy 데이터 무손상
        return BootstrapOutcome(TEMPLATE_INITIALIZATION_REQUIRED, reason=attempt.outcome)
    # admission/apply 와 같은 Profile 자격 게이트를 bootstrap 도 통과해야 한다(우회 금지):
    # 무효 qualification 권위(revoked Profile·media 불일치)로 epoch-1 current 를 세우지 않는다.
    if qualification_store.is_revoked(profile.id):
        return BootstrapOutcome(TEMPLATE_INITIALIZATION_REQUIRED, reason="PROFILE_REVOKED")
    if manifest.media != capture.revision.media:
        return BootstrapOutcome(TEMPLATE_INITIALIZATION_REQUIRED, reason="MEDIA_MISMATCH")

    provenance = MigrationProvenance(
        bootstrap_request_id=bootstrap_request_id,
        legacy_template_revision=legacy_template_revision,
        legacy_binding_revision=legacy_binding_revision,
        legacy_source_reference=legacy_source_reference,
        migrated_at=qualified_at,
    )
    try:
        aggregate = initialize_work(
            work_store, qualification_store, candidate_store,
            work_id=work_id, template_lineage_id=lineage.template_lineage_id,
            application_id=application_id, pass_evidence_id=evidence_id, actor=actor,
            applied_at=qualified_at, migration_provenance=provenance,
        )
    except WorkAggregateExists:  # 동시 bootstrap 경합 — 먼저 commit 한 것으로 화해(멱등)
        return BootstrapOutcome(BOOTSTRAP_OK, work_store.load(work_id))
    return BootstrapOutcome(BOOTSTRAP_OK, aggregate)


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
