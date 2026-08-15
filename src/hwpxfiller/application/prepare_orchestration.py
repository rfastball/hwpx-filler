"""capture→qualification checkpoint 판정과 crash recovery reconcile — 순수 층 (S3-05 #655).

S3-04 가 CAPTURING Preparation 을 만들면 S3-05 coordinator 가 pinned source 를 capture 하고 exact
Candidate 를 S2 qualification 에 넘긴다. 각 외부 stage 는 durable object 를 먼저 쓰고(object-first),
그 다음 이 모듈의 판정으로 Preparation checkpoint 를 **한 번** 전진시킨다. process 가 죽어도
completed durable 결과만 reconcile 하고 capture/qualification 을 조용히 재호출하지 않는다.

여기는 aggregate 값 하나를 받아 새 aggregate 값을 내는 판정이다. 실제 capture 엔진·qualify 엔진·
object store I/O 결선은 :mod:`hwpxfiller.external.prepare_orchestration_runner` 가 진다.

Observation/Revision/Attempt/Evidence id 는 preparation_id 에서 **결정론적으로** 파생한다 — 그래야
create-once store 로 stage 가 최대 한 번 실행되고(중복 차단), restart 뒤 aggregate 가 id 를 아직
기록하지 못했어도 recovery 가 id 를 다시 계산해 durable 결과를 찾을 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .qualification_evidence import ERROR, FAIL, PASS
from .work_template_state import (
    CHANGE_APPLIED,
    CHANGE_PREPARED,
    PREP_CAPTURE_ERROR,
    PREP_CAPTURING,
    PREP_INTERRUPTED,
    PREP_QUALIFICATION_ERROR,
    PREP_QUALIFICATION_FAILED,
    PREP_QUALIFYING,
    PREP_READY,
    PREP_SOURCE_BINDING_CHANGED,
    PREPARED_CHANGE,
    ApplyProvenance,
    OutboxEvent,
    PreparedTemplateChange,
    TemplateChangePreparation,
    WorkTemplateApplication,
    WorkTemplateStateAggregate,
    WorkTemplateStateError,
)

_IN_FLIGHT = frozenset({PREP_CAPTURING, PREP_QUALIFYING})

CHANGE_APPLIED_EVENT = "template.change_applied"

# apply 결과 어휘(S3-07) — 성공·재전송·전진·conflict·revocation·integrity 를 서로 다르게 닫는다.
APPLY_APPLIED = "APPLIED"
APPLY_ALREADY_APPLIED = "ALREADY_APPLIED"
APPLY_APPLIED_THEN_ADVANCED = "APPLIED_THEN_ADVANCED"
APPLY_SUPERSEDED = "SUPERSEDED"
APPLY_CONFLICT = "CONFLICT"
APPLY_REJECTED = "REJECTED"
APPLY_INTEGRITY_ERROR = "INTEGRITY_ERROR"


@dataclass(frozen=True)
class DerivedStageIds:
    """한 Preparation 의 외부 stage object id — preparation_id 에서 결정론적으로 파생."""

    observation_id: str
    revision_id: str
    attempt_id: str
    evidence_id: str


def derive_stage_ids(work_id: str, preparation_id: str) -> DerivedStageIds:
    # preparation_id 는 Work aggregate 안에서만 유일하나 object store 는 전역이다 — 다른 Work 의
    # 같은 preparation_id 가 서로의 stage object 를 덮지 않도록 work_id 로 namespace 한다.
    # 접미사·구분자는 _SAFE_ID([A-Za-z0-9._-]) 안이라 store 파일명으로 쓸 수 있다.
    prefix = f"{work_id}.{preparation_id}"
    return DerivedStageIds(
        observation_id=f"{prefix}.obs",
        revision_id=f"{prefix}.rev",
        attempt_id=f"{prefix}.att",
        evidence_id=f"{prefix}.ev",
    )


def find_preparation(
    aggregate: WorkTemplateStateAggregate, preparation_id: str
) -> TemplateChangePreparation:
    for prep in aggregate.preparations:
        if prep.preparation_id == preparation_id:
            return prep
    raise WorkTemplateStateError(f"preparation {preparation_id} 없음")


def in_flight_preparations(
    aggregate: WorkTemplateStateAggregate, current_session_id: str
) -> tuple[TemplateChangePreparation, ...]:
    """이전 process session 의 미완(CAPTURING/QUALIFYING) Preparation — recovery 대상."""
    return tuple(
        prep
        for prep in aggregate.preparations
        if prep.status in _IN_FLIGHT and prep.execution_session_id != current_session_id
    )


def _set_preparation(
    aggregate: WorkTemplateStateAggregate, preparation_id: str, **changes: object
) -> WorkTemplateStateAggregate:
    """대상 Preparation 을 교체한 새 aggregate(version+1). __post_init__ 이 재검증한다."""
    preparations = tuple(
        replace(prep, **changes) if prep.preparation_id == preparation_id else prep
        for prep in aggregate.preparations
    )
    return replace(
        aggregate,
        aggregate_version=aggregate.aggregate_version + 1,
        preparations=preparations,
    )


def plan_capture_checkpoint(
    aggregate: WorkTemplateStateAggregate,
    preparation_id: str,
    *,
    observation_id: str,
    revision_id: str,
    capture_failed: bool,
    capture_error_reason: str | None,
    binding_changed: bool,
    completed_at: str,
) -> WorkTemplateStateAggregate:
    """capture 완료를 Preparation 에 결속. CAPTURING 아닌 prep 은 no-op(at-most-once)."""
    prep = find_preparation(aggregate, preparation_id)
    if prep.status != PREP_CAPTURING:
        return aggregate  # 이미 전진했거나 terminal — 중복 checkpoint 금지
    if binding_changed:  # 우선순위: 재확인한 current binding 이 pinned 와 다르면 terminal
        return _set_preparation(
            aggregate, preparation_id,
            status=PREP_SOURCE_BINDING_CHANGED, completed_at=completed_at,
        )
    if capture_failed:
        # 실패 사유를 diagnostics 로 durable 하게 남긴다 — 조용히 버리지 않고 재진술 가능하게.
        return _set_preparation(
            aggregate, preparation_id,
            status=PREP_CAPTURE_ERROR,
            diagnostics=({"stage": "capture", "reason": capture_error_reason or "UNKNOWN"},),
            completed_at=completed_at,
        )
    return _set_preparation(
        aggregate, preparation_id,
        observation_id=observation_id, revision_id=revision_id, status=PREP_QUALIFYING,
    )


def plan_qualification_checkpoint(
    aggregate: WorkTemplateStateAggregate,
    preparation_id: str,
    *,
    outcome: str,
    attempt_id: str,
    evidence_id: str | None,
    completed_at: str,
) -> WorkTemplateStateAggregate:
    """qualification 결과를 Preparation 에 결속. QUALIFYING 아닌 prep 은 no-op."""
    prep = find_preparation(aggregate, preparation_id)
    if prep.status != PREP_QUALIFYING:
        return aggregate
    return _apply_attempt_outcome(
        aggregate, preparation_id,
        outcome=outcome, attempt_id=attempt_id, evidence_id=evidence_id,
        completed_at=completed_at,
    )


def plan_recovery(
    aggregate: WorkTemplateStateAggregate,
    preparation_id: str,
    *,
    attempt_outcome: str | None,
    attempt_id: str | None,
    evidence_id: str | None,
    completed_at: str,
) -> WorkTemplateStateAggregate:
    """in-flight Preparation 을 durable Attempt 로 reconcile. 없으면 INTERRUPTED(재호출 없음)."""
    prep = find_preparation(aggregate, preparation_id)
    if prep.status not in _IN_FLIGHT:
        return aggregate  # 이미 terminal — reconcile 대상 아님
    if attempt_outcome is None:
        # completed Attempt 없음 → capture/qualification 이 미완인 채 종료됨. 자동 재호출 금지.
        return _set_preparation(
            aggregate, preparation_id, status=PREP_INTERRUPTED, completed_at=completed_at
        )
    assert attempt_id is not None  # outcome 이 있으면 attempt 가 있다(coordinator 결선 계약)
    return _apply_attempt_outcome(
        aggregate, preparation_id,
        outcome=attempt_outcome, attempt_id=attempt_id, evidence_id=evidence_id,
        completed_at=completed_at,
    )


def _apply_attempt_outcome(
    aggregate: WorkTemplateStateAggregate,
    preparation_id: str,
    *,
    outcome: str,
    attempt_id: str,
    evidence_id: str | None,
    completed_at: str,
) -> WorkTemplateStateAggregate:
    """PASS/FAIL/ERROR Attempt 하나를 Preparation checkpoint 로 반영(qualification·recovery 공통)."""
    if outcome == PASS:
        # PASS 는 admission(S3-06) 전까지 QUALIFYING checkpoint 를 유지한다(terminal 아님).
        # status 를 명시 QUALIFYING 으로 두면 정상 경로(이미 QUALIFYING)엔 no-op 이고, CAPTURING
        # 에서 durable PASS 를 reconcile 하는 recovery 경로엔 올바른 승격이 된다.
        return _set_preparation(
            aggregate, preparation_id,
            attempt_id=attempt_id, evidence_id=evidence_id, status=PREP_QUALIFYING,
        )
    if outcome == FAIL:
        return _set_preparation(
            aggregate, preparation_id,
            attempt_id=attempt_id, evidence_id=evidence_id,
            status=PREP_QUALIFICATION_FAILED, completed_at=completed_at,
        )
    if outcome == ERROR:
        return _set_preparation(  # ERROR 는 Evidence 없음
            aggregate, preparation_id,
            attempt_id=attempt_id, status=PREP_QUALIFICATION_ERROR, completed_at=completed_at,
        )
    raise WorkTemplateStateError(  # pragma: no cover - build_records 가 PASS|FAIL|ERROR 로 소진
        f"미상 attempt outcome {outcome!r}"
    )


# ─── admission(S3-06): PASS checkpoint → Prepared Change 승격 또는 fail-closed ────

def find_application(aggregate: WorkTemplateStateAggregate, application_id: str):
    for app in aggregate.applications:
        if app.application_id == application_id:
            return app
    raise WorkTemplateStateError(f"application {application_id} 없음")


def find_change(
    aggregate: WorkTemplateStateAggregate, prepared_change_id: str
) -> PreparedTemplateChange:
    for change in aggregate.prepared_changes:
        if change.prepared_change_id == prepared_change_id:
            return change
    raise WorkTemplateStateError(f"prepared change {prepared_change_id} 없음")


def plan_admission_terminal(
    aggregate: WorkTemplateStateAggregate,
    preparation_id: str,
    status: str,
    *,
    completed_at: str,
) -> WorkTemplateStateAggregate:
    """admission gate 실패를 명시 terminal 로 닫는다(Prepared Change 없음)."""
    return _set_preparation(
        aggregate, preparation_id, status=status, completed_at=completed_at
    )


def plan_admission_ready(
    aggregate: WorkTemplateStateAggregate,
    preparation_id: str,
    *,
    prepared_change_id: str,
    target_pass_evidence_id: str,
    prepared_at: str,
) -> WorkTemplateStateAggregate:
    """durable PASS checkpoint 를 current base 에서 적용 가능한 Prepared Change 로 승격한다."""
    prep = find_preparation(aggregate, preparation_id)
    change = PreparedTemplateChange(
        prepared_change_id=prepared_change_id,
        preparation_id=preparation_id,
        work_id=prep.work_id,
        base_application_id=aggregate.work.current_template_application_id,
        target_pass_evidence_id=target_pass_evidence_id,
        status=CHANGE_PREPARED,
        prepared_at=prepared_at,
    )
    preparations = tuple(
        replace(p, status=PREP_READY, prepared_change_id=prepared_change_id, completed_at=prepared_at)
        if p.preparation_id == preparation_id
        else p
        for p in aggregate.preparations
    )
    return replace(
        aggregate,
        aggregate_version=aggregate.aggregate_version + 1,
        preparations=preparations,
        prepared_changes=(*aggregate.prepared_changes, change),
    )


# ─── apply(S3-07): Prepared Change 를 Work 에 원자 적용 ─────────────────────────

@dataclass(frozen=True)
class ApplyOutcome:
    """apply 명령 결과 — status 와 (성공/idempotent 이면) resulting Application id."""

    result: str
    resulting_application_id: str | None


def plan_change_status(
    aggregate: WorkTemplateStateAggregate, prepared_change_id: str, status: str
) -> WorkTemplateStateAggregate:
    """conflict 분류를 Change status 로만 닫는다(Application/current pointer 무변경)."""
    changes = tuple(
        replace(c, status=status) if c.prepared_change_id == prepared_change_id else c
        for c in aggregate.prepared_changes
    )
    return replace(
        aggregate, aggregate_version=aggregate.aggregate_version + 1, prepared_changes=changes
    )


def plan_apply(
    aggregate: WorkTemplateStateAggregate,
    change: PreparedTemplateChange,
    *,
    new_application_id: str,
    provenance_id: str,
    outbox_event_id: str,
    actor: str,
    applied_at: str,
) -> WorkTemplateStateAggregate:
    """새 Application·current pointer·Change APPLIED·provenance·outbox 를 하나의 commit 으로 낸다."""
    current = find_application(aggregate, aggregate.work.current_template_application_id)
    new_epoch = current.application_epoch + 1
    new_application = WorkTemplateApplication(
        application_id=new_application_id,
        work_id=change.work_id,
        application_epoch=new_epoch,
        pass_evidence_id=change.target_pass_evidence_id,
        previous_application_id=current.application_id,
        origin=PREPARED_CHANGE,
        prepared_change_id=change.prepared_change_id,
        actor=actor,
        applied_at=applied_at,
    )
    prepared_changes = tuple(
        replace(
            c, status=CHANGE_APPLIED,
            resulting_application_id=new_application_id, applied_at=applied_at,
        )
        if c.prepared_change_id == change.prepared_change_id
        else c
        for c in aggregate.prepared_changes
    )
    provenance = ApplyProvenance(
        provenance_id=provenance_id,
        work_id=change.work_id,
        from_application_id=current.application_id,
        to_application_id=new_application_id,
        from_pass_evidence_id=current.pass_evidence_id,
        to_pass_evidence_id=change.target_pass_evidence_id,
        prepared_change_id=change.prepared_change_id,
        epoch_before=current.application_epoch,
        epoch_after=new_epoch,
        actor=actor,
        applied_at=applied_at,
    )
    outbox = OutboxEvent(
        event_id=outbox_event_id,
        event_type=CHANGE_APPLIED_EVENT,
        payload={"work_id": change.work_id, "application_id": new_application_id},
    )
    return replace(
        aggregate,
        aggregate_version=aggregate.aggregate_version + 1,
        applications=(*aggregate.applications, new_application),
        work=replace(aggregate.work, current_template_application_id=new_application_id),
        prepared_changes=prepared_changes,
        apply_provenance=(*aggregate.apply_provenance, provenance),
        outbox_events=(*aggregate.outbox_events, outbox),
    )
