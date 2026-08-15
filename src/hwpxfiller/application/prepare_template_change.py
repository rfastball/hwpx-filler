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
    PREP_QUALIFYING,
    PREP_READY,
    PREP_SUPERSEDED,
    OutboxEvent,
    PreparedTemplateChange,
    TemplateChangePreparation,
    WorkTemplateStateAggregate,
)

# 새 prepare intent 가 낮추는 pending 상태 — capture(CAPTURING)·qualify(QUALIFYING) in-flight 와
# READY 를 supersede 한다. QUALIFYING 을 빠뜨리면 replaced intent 가 recovery 에서 계속 active 로
# 취급된다(S3-05 가 QUALIFYING 을 in-flight 로 추가하며 함께 갱신).
_SUPERSEDABLE = frozenset({PREP_CAPTURING, PREP_QUALIFYING, PREP_READY})

# capture worker 를 부르는 durable 신호 — commit 과 원자적으로 outbox 에 남는다. post-commit
# 콜백이 실패해도 이 record 가 생존해 dispatcher(후속 stage)가 재시도할 수 있다.
CAPTURE_REQUESTED = "template.capture_requested"


def find_preparation_by_request(
    aggregate: WorkTemplateStateAggregate, prepare_request_id: str
) -> "TemplateChangePreparation | None":
    """이미 있는 (work, prepare_request_id) Preparation 을 찾는다(멱등 short-circuit 용)."""
    for prep in aggregate.preparations:
        if prep.prepare_request_id == prepare_request_id:
            return prep
    return None


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
    existing = find_preparation_by_request(aggregate, prepare_request_id)
    if existing is not None:
        return PreparePlan(aggregate, existing, created=False)

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
    capture_event = OutboxEvent(
        event_id=f"{preparation_id}:capture",  # preparation 당 1개, 결정론적 identity
        event_type=CAPTURE_REQUESTED,
        payload={"preparation_id": preparation_id, "work_id": work.work_id},
    )
    # replace() 로 바꾼 필드만 지정한다 — applications·apply_provenance·migration_provenance 같은
    # 미지정 필드가 자동 보존된다(fresh 생성이 bootstrap provenance 를 조용히 None 으로 덮던 결함 차단).
    new_aggregate = replace(
        aggregate,
        aggregate_version=aggregate.aggregate_version + 1,
        work=replace(
            work, prepare_seq=new_seq, current_template_preparation_id=preparation_id
        ),
        preparations=(*preparations, new_prep),
        prepared_changes=prepared_changes,
        outbox_events=(*aggregate.outbox_events, capture_event),
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
