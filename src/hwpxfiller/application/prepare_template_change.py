"""prepare intent 시작의 순수 판정 — idempotency·server pinning·latest-intent supersede (S3-04 #654).

사용자의 [변경사항 확인] 한 번이 하나의 prepare intent 다. 같은 ``prepare_request_id`` 재전송은
같은 Preparation 을 mutation 없이 반환하고(멱등), 새 intent 는 이전 pending(CAPTURING/READY)
Preparation 과 그 PREPARED Change 를 current 후보에서 supersede 한다. 이미 APPLIED/CONFLICTED/
REJECTED 인 이력은 건드리지 않는다.

여기는 aggregate 값 하나를 받아 새 aggregate 값을 내는 **판정**이다(확인-또는-경보의 판정 면).
Work writer lease·atomic commit·post-commit worker handoff 같은 I/O 는
:func:`hwpxfiller.external.work_template_store.start_prepare` 가 진다. base/source binding/profile 은
서버가 고정한다 — client 입력을 받지 않는다(base 는 current Application 에서 파생).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .work_template_state import (
    CHANGE_PREPARED,
    CHANGE_SUPERSEDED,
    PREP_CAPTURING,
    PREP_READY,
    PREP_SUPERSEDED,
    PreparedTemplateChange,
    TemplateChangePreparation,
    WorkTemplateStateAggregate,
)

_SUPERSEDABLE = frozenset({PREP_CAPTURING, PREP_READY})


@dataclass(frozen=True)
class PreparePins:
    """prepare 시작 시 서버가 고정하는 값 — resolver port 가 current Work 에서 산출한다."""

    source_binding_id: str
    source_binding_generation: int
    qualification_profile_id: str


@dataclass(frozen=True)
class PreparePlan:
    """판정 결과 — 새 aggregate, 대상 Preparation, 새로 생성했는지(worker handoff 게이트)."""

    aggregate: WorkTemplateStateAggregate
    preparation: TemplateChangePreparation
    created: bool


def plan_prepare(
    aggregate: WorkTemplateStateAggregate,
    *,
    prepare_request_id: str,
    pins: PreparePins,
    preparation_id: str,
    execution_session_id: str,
    started_at: str,
) -> PreparePlan:
    """(work, prepare_request_id) 멱등 시작 판정. 같은 key 면 mutation 없이 기존 것을 돌려준다."""
    for prep in aggregate.preparations:
        if prep.prepare_request_id == prepare_request_id:
            return PreparePlan(aggregate, prep, created=False)

    work = aggregate.work
    new_seq = work.prepare_seq + 1
    new_prep = TemplateChangePreparation(
        preparation_id=preparation_id,
        work_id=work.work_id,
        prepare_request_id=prepare_request_id,
        prepare_seq=new_seq,
        base_application_id=work.current_template_application_id,  # 서버 고정(client 입력 아님)
        source_binding_id=pins.source_binding_id,
        source_binding_generation=pins.source_binding_generation,
        qualification_profile_id=pins.qualification_profile_id,
        execution_session_id=execution_session_id,
        status=PREP_CAPTURING,
        started_at=started_at,
    )
    preparations, prepared_changes = _supersede_prior(aggregate)
    new_aggregate = WorkTemplateStateAggregate(
        schema_version=aggregate.schema_version,
        aggregate_version=aggregate.aggregate_version + 1,
        work=replace(
            work, prepare_seq=new_seq, current_template_preparation_id=preparation_id
        ),
        applications=aggregate.applications,
        preparations=(*preparations, new_prep),
        prepared_changes=prepared_changes,
        apply_provenance=aggregate.apply_provenance,
        outbox_events=aggregate.outbox_events,
    )
    return PreparePlan(new_aggregate, new_prep, created=True)


def _supersede_prior(
    aggregate: WorkTemplateStateAggregate,
) -> tuple[tuple[TemplateChangePreparation, ...], tuple[PreparedTemplateChange, ...]]:
    """이전 current Preparation 이 pending 이면 SUPERSEDED 로 낮추고, 그 PREPARED Change 도 같이."""
    prior_id = aggregate.work.current_template_preparation_id
    if prior_id is None:
        return aggregate.preparations, aggregate.prepared_changes

    superseded_change_ids: set[str] = set()
    preparations = []
    for prep in aggregate.preparations:
        if prep.preparation_id == prior_id and prep.status in _SUPERSEDABLE:
            preparations.append(replace(prep, status=PREP_SUPERSEDED))
            if prep.prepared_change_id is not None:
                superseded_change_ids.add(prep.prepared_change_id)
        else:
            preparations.append(prep)  # APPLIED/CONFLICTED/REJECTED 이력은 보존

    prepared_changes = tuple(
        replace(change, status=CHANGE_SUPERSEDED)
        if change.prepared_change_id in superseded_change_ids
        and change.status == CHANGE_PREPARED
        else change
        for change in aggregate.prepared_changes
    )
    return tuple(preparations), prepared_changes
