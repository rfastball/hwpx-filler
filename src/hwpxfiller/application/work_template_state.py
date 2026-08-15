"""per-Work Template Application aggregate — native-free 모델·불변식·코덱 (S3-03 #653).

S3 는 Template 전역 Active pointer 를 만들지 않는다. 각 Document Work 가 immutable
:class:`WorkTemplateApplication` 하나를 current 로 가리키고, 그 Work 의 mutable S3 상태와
적용 history 는 **Work 당 하나의 aggregate** 로 산다. 이 모듈은 그 aggregate 의 값·불변식·
dict 코덱을 소유한다 — writer lease·atomic replace·store 결속은
:mod:`hwpxfiller.external.work_template_store` 어댑터가 진다.

불변식은 dataclass ``__post_init__`` 이 진다(확인-또는-경보): 깨진 Application·aggregate 는
생성·decode 시점에 시끄럽게 거절된다. epoch 은 별도 필드가 아니라 current Application 에서
파생한다(``new_epoch = current.application_epoch + 1``) — DocumentWork 에 중복 저장하지 않는다.

Preparation·PreparedChange·ApplyProvenance·Outbox 의 최종 필드·상태 집합은 S3-04·S3-06 이
소유한다. 여기는 그 셋이 aggregate 에 실려 round-trip 하도록 하는 얇은 seam 레코드(identity +
opaque ``payload``)만 제공한다 — 도메인 필드를 미리 발명하지 않는다(YAGNI).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "work-template-state-v1"

INITIALIZATION = "INITIALIZATION"
PREPARED_CHANGE = "PREPARED_CHANGE"
_ORIGINS = (INITIALIZATION, PREPARED_CHANGE)


class WorkTemplateStateError(ValueError):
    """Work Template aggregate 의 불변식 위반."""


# ─── 핵심 값 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DocumentWork:
    """한 문서 작업의 mutable current pointer(적용 자체는 immutable history 에 산다)."""

    work_id: str
    template_lineage_id: str
    current_template_application_id: str
    current_template_preparation_id: str | None
    prepare_seq: int

    def __post_init__(self) -> None:
        if self.prepare_seq < 0:
            raise WorkTemplateStateError("prepare_seq 는 음수일 수 없다")


@dataclass(frozen=True)
class WorkTemplateApplication:
    """exact PASS Evidence 를 이 Work 의 current Template 으로 못박는 immutable 사건."""

    application_id: str
    work_id: str
    application_epoch: int
    pass_evidence_id: str
    previous_application_id: str | None
    origin: str
    prepared_change_id: str | None
    actor: str
    applied_at: str

    def __post_init__(self) -> None:
        if self.origin not in _ORIGINS:
            raise WorkTemplateStateError(f"미상 origin {self.origin!r}")
        if self.application_epoch < 1:
            raise WorkTemplateStateError("application_epoch 는 1 이상이다")
        if self.origin == INITIALIZATION:
            if self.previous_application_id is not None:
                raise WorkTemplateStateError("INITIALIZATION 은 previous 가 없어야 한다")
            if self.prepared_change_id is not None:
                raise WorkTemplateStateError(
                    "INITIALIZATION 은 prepared_change_id 를 갖지 않는다"
                )
        else:  # PREPARED_CHANGE
            if self.prepared_change_id is None:
                raise WorkTemplateStateError("PREPARED_CHANGE 는 prepared_change_id 가 필수다")
            if self.previous_application_id is None:
                raise WorkTemplateStateError("PREPARED_CHANGE 는 previous 가 필수다")


# ─── S3-04·S3-06 seam 레코드(얇은 identity + opaque payload) ──────────────────

@dataclass(frozen=True)
class TemplateChangePreparation:
    """prepare workflow(S3-04)가 채울 준비 레코드의 aggregate seam."""

    preparation_id: str
    work_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class PreparedTemplateChange:
    """apply 가능한 준비 완료 변경(S3-06)의 aggregate seam."""

    prepared_change_id: str
    preparation_id: str
    work_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ApplyProvenance:
    """apply transition 이 남기는 provenance 의 aggregate seam."""

    provenance_id: str
    application_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class OutboxEvent:
    """aggregate commit 과 원자적으로 발행되는 outbox 항목의 seam."""

    event_id: str
    event_type: str
    payload: Mapping[str, Any]


# ─── aggregate ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WorkTemplateStateAggregate:
    """한 Work 의 전체 S3 상태 — 하나의 파일로 원자 commit 되는 단위."""

    schema_version: str
    aggregate_version: int
    work: DocumentWork
    applications: tuple[WorkTemplateApplication, ...]
    preparations: tuple[TemplateChangePreparation, ...]
    prepared_changes: tuple[PreparedTemplateChange, ...]
    apply_provenance: tuple[ApplyProvenance, ...]
    outbox_events: tuple[OutboxEvent, ...]

    def __post_init__(self) -> None:
        validate_aggregate(self)


def validate_aggregate(aggregate: WorkTemplateStateAggregate) -> None:
    """aggregate 전체 참조 무결성·유일성 불변식(구성·decode 공통 문지기)."""
    if aggregate.schema_version != SCHEMA_VERSION:
        raise WorkTemplateStateError(
            f"미지원 schema_version {aggregate.schema_version!r}"
        )
    if aggregate.aggregate_version < 1:
        raise WorkTemplateStateError("aggregate_version 은 1 이상이다")

    work_id = aggregate.work.work_id
    epoch_by_id: dict[str, int] = {}
    epochs: set[int] = set()
    prepared_used: set[str] = set()
    for app in aggregate.applications:
        if app.work_id != work_id:
            raise WorkTemplateStateError(
                f"application {app.application_id} 가 다른 Work 에 속한다"
            )
        if app.application_id in epoch_by_id:
            raise WorkTemplateStateError(f"application_id 중복 {app.application_id}")
        if app.application_epoch in epochs:
            raise WorkTemplateStateError(
                f"application_epoch 중복 {app.application_epoch}"
            )
        epoch_by_id[app.application_id] = app.application_epoch
        epochs.add(app.application_epoch)
        if app.prepared_change_id is not None:
            if app.prepared_change_id in prepared_used:
                raise WorkTemplateStateError(
                    f"prepared_change_id {app.prepared_change_id} 에 Application 2개"
                )
            prepared_used.add(app.prepared_change_id)

    app_ids = epoch_by_id.keys()
    current = aggregate.work.current_template_application_id
    if current not in epoch_by_id:
        raise WorkTemplateStateError("current pointer 가 dangling(존재하지 않는 Application)")
    # current 는 history 의 terminal(최고 epoch)이어야 한다 — next_epoch = current+1 파생이
    # 성립하려면 current 뒤에 더 높은 epoch 이 있으면 안 된다(조용한 rollback 차단).
    if epoch_by_id[current] != max(epochs):
        raise WorkTemplateStateError("current pointer 가 최신 Application(최고 epoch)이 아니다")
    for app in aggregate.applications:
        if (
            app.previous_application_id is not None
            and app.previous_application_id not in app_ids
        ):
            raise WorkTemplateStateError(
                f"previous {app.previous_application_id} 가 dangling"
            )
    for record in (*aggregate.preparations, *aggregate.prepared_changes):
        if record.work_id != work_id:
            raise WorkTemplateStateError("preparation/change 가 다른 Work 에 속한다")
    # DocumentWork 자기 current preparation pointer 와 provenance→application 링크는
    # append-only 라 여기서 dangling 을 막는다(current_application 검증과 대칭). prepared_change
    # 존재·application↔prepared_change 링크는 prepared_changes 수명(apply 후 pruning)을 소유하는
    # S3-04·S3-06 이 지므로 여기서 강제하지 않는다(정당한 pruned history 오거절 방지).
    prep_ids = {p.preparation_id for p in aggregate.preparations}
    current_prep = aggregate.work.current_template_preparation_id
    if current_prep is not None and current_prep not in prep_ids:
        raise WorkTemplateStateError("current preparation pointer 가 dangling")
    for prov in aggregate.apply_provenance:
        if prov.application_id not in app_ids:
            raise WorkTemplateStateError(
                f"provenance {prov.provenance_id} 가 없는 application 을 가리킨다"
            )


# ─── codec: 저장 어댑터가 쓰는 native-free dict ↔ 값 ──────────────────────────

def _encode_work(work: DocumentWork) -> dict[str, Any]:
    return {
        "work_id": work.work_id,
        "template_lineage_id": work.template_lineage_id,
        "current_template_application_id": work.current_template_application_id,
        "current_template_preparation_id": work.current_template_preparation_id,
        "prepare_seq": work.prepare_seq,
    }


def _decode_work(data: Mapping[str, Any]) -> DocumentWork:
    return DocumentWork(
        work_id=data["work_id"],
        template_lineage_id=data["template_lineage_id"],
        current_template_application_id=data["current_template_application_id"],
        current_template_preparation_id=data["current_template_preparation_id"],
        prepare_seq=data["prepare_seq"],
    )


def _encode_application(app: WorkTemplateApplication) -> dict[str, Any]:
    return {
        "application_id": app.application_id,
        "work_id": app.work_id,
        "application_epoch": app.application_epoch,
        "pass_evidence_id": app.pass_evidence_id,
        "previous_application_id": app.previous_application_id,
        "origin": app.origin,
        "prepared_change_id": app.prepared_change_id,
        "actor": app.actor,
        "applied_at": app.applied_at,
    }


def _decode_application(data: Mapping[str, Any]) -> WorkTemplateApplication:
    return WorkTemplateApplication(
        application_id=data["application_id"],
        work_id=data["work_id"],
        application_epoch=data["application_epoch"],
        pass_evidence_id=data["pass_evidence_id"],
        previous_application_id=data["previous_application_id"],
        origin=data["origin"],
        prepared_change_id=data["prepared_change_id"],
        actor=data["actor"],
        applied_at=data["applied_at"],
    )


def encode_aggregate(aggregate: WorkTemplateStateAggregate) -> dict[str, Any]:
    return {
        "schema_version": aggregate.schema_version,
        "aggregate_version": aggregate.aggregate_version,
        "work": _encode_work(aggregate.work),
        "applications": [_encode_application(a) for a in aggregate.applications],
        "preparations": [
            {
                "preparation_id": p.preparation_id,
                "work_id": p.work_id,
                "payload": dict(p.payload),
            }
            for p in aggregate.preparations
        ],
        "prepared_changes": [
            {
                "prepared_change_id": c.prepared_change_id,
                "preparation_id": c.preparation_id,
                "work_id": c.work_id,
                "payload": dict(c.payload),
            }
            for c in aggregate.prepared_changes
        ],
        "apply_provenance": [
            {
                "provenance_id": pr.provenance_id,
                "application_id": pr.application_id,
                "payload": dict(pr.payload),
            }
            for pr in aggregate.apply_provenance
        ],
        "outbox_events": [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "payload": dict(e.payload),
            }
            for e in aggregate.outbox_events
        ],
    }


def decode_aggregate(data: Mapping[str, Any]) -> WorkTemplateStateAggregate:
    # payload 는 caller/디스크 소유였으므로 deep-copy 로 alias 를 끊는다(frozen 은 nested 를 못 막음).
    return WorkTemplateStateAggregate(
        schema_version=data["schema_version"],
        aggregate_version=data["aggregate_version"],
        work=_decode_work(data["work"]),
        applications=tuple(_decode_application(a) for a in data["applications"]),
        preparations=tuple(
            TemplateChangePreparation(
                preparation_id=p["preparation_id"],
                work_id=p["work_id"],
                payload=copy.deepcopy(p["payload"]),
            )
            for p in data["preparations"]
        ),
        prepared_changes=tuple(
            PreparedTemplateChange(
                prepared_change_id=c["prepared_change_id"],
                preparation_id=c["preparation_id"],
                work_id=c["work_id"],
                payload=copy.deepcopy(c["payload"]),
            )
            for c in data["prepared_changes"]
        ),
        apply_provenance=tuple(
            ApplyProvenance(
                provenance_id=pr["provenance_id"],
                application_id=pr["application_id"],
                payload=copy.deepcopy(pr["payload"]),
            )
            for pr in data["apply_provenance"]
        ),
        outbox_events=tuple(
            OutboxEvent(
                event_id=e["event_id"],
                event_type=e["event_type"],
                payload=copy.deepcopy(e["payload"]),
            )
            for e in data["outbox_events"]
        ),
    )
