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


# ─── Preparation 상태 어휘 (S3-04·S3-05) ──────────────────────────────────────
# in-flight(CAPTURING/QUALIFYING)/READY 는 새 prepare intent 가 supersede 하고, terminal 은 보존.
PREP_CAPTURING = "CAPTURING"
PREP_QUALIFYING = "QUALIFYING"  # S3-05: capture 성공 후 qualification 진행
PREP_READY = "READY"
PREP_SUPERSEDED = "SUPERSEDED"
PREP_APPLIED = "APPLIED"
PREP_CONFLICTED = "CONFLICTED"
PREP_REJECTED = "REJECTED"
# S3-05·S3-06 terminal 결과(더는 진행하지 않는다):
PREP_CAPTURE_ERROR = "CAPTURE_ERROR"
PREP_SOURCE_BINDING_CHANGED = "SOURCE_BINDING_CHANGED"
PREP_QUALIFICATION_FAILED = "QUALIFICATION_FAILED"
PREP_QUALIFICATION_ERROR = "QUALIFICATION_ERROR"
PREP_INTERRUPTED = "INTERRUPTED"  # process 종료로 stage 가 미완 — 자동 재호출 안 함
PREP_BASE_CHANGED = "BASE_CHANGED"  # S3-06: admission 시 current base 가 pinned base 와 다름
PREP_PROFILE_REVOKED = "PROFILE_REVOKED"
PREP_NO_CHANGE = "NO_CHANGE"  # 현재 target 과 operational 동치 — Work 변경 아님
_PREP_STATES = frozenset(
    {
        PREP_CAPTURING,
        PREP_QUALIFYING,
        PREP_READY,
        PREP_SUPERSEDED,
        PREP_APPLIED,
        PREP_CONFLICTED,
        PREP_REJECTED,
        PREP_CAPTURE_ERROR,
        PREP_SOURCE_BINDING_CHANGED,
        PREP_QUALIFICATION_FAILED,
        PREP_QUALIFICATION_ERROR,
        PREP_INTERRUPTED,
        PREP_BASE_CHANGED,
        PREP_PROFILE_REVOKED,
        PREP_NO_CHANGE,
    }
)

# PreparedChange 상태 — S3-04 SUPERSEDED, S3-06 PREPARED, S3-07 apply 가 APPLIED/CONFLICTED/REJECTED.
CHANGE_PREPARED = "PREPARED"
CHANGE_SUPERSEDED = "SUPERSEDED"
CHANGE_APPLIED = "APPLIED"
CHANGE_CONFLICTED = "CONFLICTED"
CHANGE_REJECTED = "REJECTED"
_CHANGE_STATES = frozenset(
    {CHANGE_PREPARED, CHANGE_SUPERSEDED, CHANGE_APPLIED, CHANGE_CONFLICTED, CHANGE_REJECTED}
)


@dataclass(frozen=True)
class TemplateChangePreparation:
    """한 prepare intent 의 서버 고정 스냅샷 — capture/qualification 진행에 따라 채워진다(S3-04).

    ``preparation_id`` 가 서버 측 intent identity 다(별도 prepare_intent_id 없음). base/binding/
    profile 은 prepare 시작 시 서버가 고정하고 client 입력을 받지 않는다. result 필드
    (observation_id·revision_id·attempt_id·evidence_id·prepared_change_id·completed_at)는
    CAPTURING 시점엔 모두 None 이고 후속 stage(S3-05·S3-06)가 채운다.
    """

    preparation_id: str
    work_id: str
    prepare_request_id: str
    prepare_seq: int
    base_application_id: str
    source_binding_id: str
    source_binding_generation: int
    qualification_profile_id: str
    execution_session_id: str
    status: str
    started_at: str
    observation_id: str | None = None
    revision_id: str | None = None
    attempt_id: str | None = None
    evidence_id: str | None = None
    prepared_change_id: str | None = None
    diagnostics: tuple[Mapping[str, str], ...] = ()
    completed_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _PREP_STATES:
            raise WorkTemplateStateError(f"미상 preparation status {self.status!r}")


@dataclass(frozen=True)
class PreparedTemplateChange:
    """current base 에서 적용 가능한 exact 변경(S3-06 admission 이 발행). apply(S3-07)가 소비한다.

    Prepared target 은 PASS Evidence 하나(``target_pass_evidence_id``)이고, base 는 그 시점
    ``current_template_application_id``. status PREPARED 로 태어나 apply 시 ``resulting_application_id``·
    ``applied_at`` 이 채워지거나 새 prepare 가 SUPERSEDED 로 낮춘다.
    """

    prepared_change_id: str
    preparation_id: str
    work_id: str
    base_application_id: str
    target_pass_evidence_id: str
    status: str
    prepared_at: str
    resulting_application_id: str | None = None
    applied_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _CHANGE_STATES:
            raise WorkTemplateStateError(f"미상 prepared change status {self.status!r}")


@dataclass(frozen=True)
class ApplyProvenance:
    """apply transition 의 audit 상세(S3-07). Application history 가 정본, 이건 감사용 부기다."""

    provenance_id: str
    work_id: str
    from_application_id: str
    to_application_id: str
    from_pass_evidence_id: str
    to_pass_evidence_id: str
    prepared_change_id: str
    epoch_before: int
    epoch_after: int
    actor: str
    applied_at: str


@dataclass(frozen=True)
class OutboxEvent:
    """aggregate commit 과 원자적으로 발행되는 outbox 항목의 seam."""

    event_id: str
    event_type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class MigrationProvenance:
    """legacy Job 을 S3 로 bootstrap 한 증거(S3-08). legacy counter 는 **identity 가 아니라 출처**다."""

    bootstrap_request_id: str
    legacy_template_revision: int
    legacy_binding_revision: int
    legacy_source_reference: str
    migrated_at: str


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
    migration_provenance: MigrationProvenance | None = None  # bootstrap 된 Work 만(S3-08)

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
    # preparation_id 는 서버 측 intent identity 다 — 중복은 current pointer 를 두 record 사이에서
    # 모호하게 만들므로 application_id 유일성과 대칭으로 거절한다(id 재사용 방어, 루트 원인 한 곳).
    prep_ids: set[str] = set()
    for prep in aggregate.preparations:
        if prep.preparation_id in prep_ids:
            raise WorkTemplateStateError(f"preparation_id 중복 {prep.preparation_id}")
        prep_ids.add(prep.preparation_id)
    change_ids: set[str] = set()
    for change in aggregate.prepared_changes:
        if change.prepared_change_id in change_ids:
            raise WorkTemplateStateError(
                f"prepared_change_id 중복 {change.prepared_change_id}"
            )
        change_ids.add(change.prepared_change_id)
    # DocumentWork 자기 current preparation pointer 와 provenance→application 링크는
    # append-only 라 여기서 dangling 을 막는다(current_application 검증과 대칭). prepared_change
    # 존재·application↔prepared_change 링크는 prepared_changes 수명(apply 후 pruning)을 소유하는
    # S3-04·S3-06 이 지므로 여기서 강제하지 않는다(정당한 pruned history 오거절 방지).
    current_prep = aggregate.work.current_template_preparation_id
    if current_prep is not None and current_prep not in prep_ids:
        raise WorkTemplateStateError("current preparation pointer 가 dangling")
    provenance_ids: set[str] = set()
    for prov in aggregate.apply_provenance:
        if prov.from_application_id not in app_ids or prov.to_application_id not in app_ids:
            raise WorkTemplateStateError(
                f"provenance {prov.provenance_id} 가 없는 application 을 가리킨다"
            )
        if prov.provenance_id in provenance_ids:
            raise WorkTemplateStateError(f"provenance_id 중복 {prov.provenance_id}")
        provenance_ids.add(prov.provenance_id)
    # outbox event_id 유일성 — dispatcher 가 event_id 로 dedup 하므로 중복은 전달 유실을 부른다.
    event_ids: set[str] = set()
    for event in aggregate.outbox_events:
        if event.event_id in event_ids:
            raise WorkTemplateStateError(f"outbox event_id 중복 {event.event_id}")
        event_ids.add(event.event_id)


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


def _encode_preparation(prep: TemplateChangePreparation) -> dict[str, Any]:
    return {
        "preparation_id": prep.preparation_id,
        "work_id": prep.work_id,
        "prepare_request_id": prep.prepare_request_id,
        "prepare_seq": prep.prepare_seq,
        "base_application_id": prep.base_application_id,
        "source_binding_id": prep.source_binding_id,
        "source_binding_generation": prep.source_binding_generation,
        "qualification_profile_id": prep.qualification_profile_id,
        "execution_session_id": prep.execution_session_id,
        "status": prep.status,
        "started_at": prep.started_at,
        "observation_id": prep.observation_id,
        "revision_id": prep.revision_id,
        "attempt_id": prep.attempt_id,
        "evidence_id": prep.evidence_id,
        "prepared_change_id": prep.prepared_change_id,
        "diagnostics": [dict(d) for d in prep.diagnostics],
        "completed_at": prep.completed_at,
    }


def _decode_preparation(data: Mapping[str, Any]) -> TemplateChangePreparation:
    return TemplateChangePreparation(
        preparation_id=data["preparation_id"],
        work_id=data["work_id"],
        prepare_request_id=data["prepare_request_id"],
        prepare_seq=data["prepare_seq"],
        base_application_id=data["base_application_id"],
        source_binding_id=data["source_binding_id"],
        source_binding_generation=data["source_binding_generation"],
        qualification_profile_id=data["qualification_profile_id"],
        execution_session_id=data["execution_session_id"],
        status=data["status"],
        started_at=data["started_at"],
        observation_id=data["observation_id"],
        revision_id=data["revision_id"],
        attempt_id=data["attempt_id"],
        evidence_id=data["evidence_id"],
        prepared_change_id=data["prepared_change_id"],
        diagnostics=tuple(dict(d) for d in data["diagnostics"]),
        completed_at=data["completed_at"],
    )


def encode_aggregate(aggregate: WorkTemplateStateAggregate) -> dict[str, Any]:
    return {
        "schema_version": aggregate.schema_version,
        "aggregate_version": aggregate.aggregate_version,
        "work": _encode_work(aggregate.work),
        "applications": [_encode_application(a) for a in aggregate.applications],
        "preparations": [_encode_preparation(p) for p in aggregate.preparations],
        "prepared_changes": [
            {
                "prepared_change_id": c.prepared_change_id,
                "preparation_id": c.preparation_id,
                "work_id": c.work_id,
                "base_application_id": c.base_application_id,
                "target_pass_evidence_id": c.target_pass_evidence_id,
                "status": c.status,
                "prepared_at": c.prepared_at,
                "resulting_application_id": c.resulting_application_id,
                "applied_at": c.applied_at,
            }
            for c in aggregate.prepared_changes
        ],
        "apply_provenance": [
            {
                "provenance_id": pr.provenance_id,
                "work_id": pr.work_id,
                "from_application_id": pr.from_application_id,
                "to_application_id": pr.to_application_id,
                "from_pass_evidence_id": pr.from_pass_evidence_id,
                "to_pass_evidence_id": pr.to_pass_evidence_id,
                "prepared_change_id": pr.prepared_change_id,
                "epoch_before": pr.epoch_before,
                "epoch_after": pr.epoch_after,
                "actor": pr.actor,
                "applied_at": pr.applied_at,
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
        "migration_provenance": _encode_migration(aggregate.migration_provenance),
    }


def _encode_migration(mp: "MigrationProvenance | None") -> dict[str, Any] | None:
    if mp is None:
        return None
    return {
        "bootstrap_request_id": mp.bootstrap_request_id,
        "legacy_template_revision": mp.legacy_template_revision,
        "legacy_binding_revision": mp.legacy_binding_revision,
        "legacy_source_reference": mp.legacy_source_reference,
        "migrated_at": mp.migrated_at,
    }


def _decode_migration(data: "Mapping[str, Any] | None") -> "MigrationProvenance | None":
    if data is None:
        return None
    return MigrationProvenance(
        bootstrap_request_id=data["bootstrap_request_id"],
        legacy_template_revision=data["legacy_template_revision"],
        legacy_binding_revision=data["legacy_binding_revision"],
        legacy_source_reference=data["legacy_source_reference"],
        migrated_at=data["migrated_at"],
    )


def decode_aggregate(data: Mapping[str, Any]) -> WorkTemplateStateAggregate:
    # payload 는 caller/디스크 소유였으므로 deep-copy 로 alias 를 끊는다(frozen 은 nested 를 못 막음).
    return WorkTemplateStateAggregate(
        schema_version=data["schema_version"],
        aggregate_version=data["aggregate_version"],
        work=_decode_work(data["work"]),
        applications=tuple(_decode_application(a) for a in data["applications"]),
        preparations=tuple(_decode_preparation(p) for p in data["preparations"]),
        prepared_changes=tuple(
            PreparedTemplateChange(
                prepared_change_id=c["prepared_change_id"],
                preparation_id=c["preparation_id"],
                work_id=c["work_id"],
                base_application_id=c["base_application_id"],
                target_pass_evidence_id=c["target_pass_evidence_id"],
                status=c["status"],
                prepared_at=c["prepared_at"],
                resulting_application_id=c["resulting_application_id"],
                applied_at=c["applied_at"],
            )
            for c in data["prepared_changes"]
        ),
        apply_provenance=tuple(
            ApplyProvenance(
                provenance_id=pr["provenance_id"],
                work_id=pr["work_id"],
                from_application_id=pr["from_application_id"],
                to_application_id=pr["to_application_id"],
                from_pass_evidence_id=pr["from_pass_evidence_id"],
                to_pass_evidence_id=pr["to_pass_evidence_id"],
                prepared_change_id=pr["prepared_change_id"],
                epoch_before=pr["epoch_before"],
                epoch_after=pr["epoch_after"],
                actor=pr["actor"],
                applied_at=pr["applied_at"],
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
        migration_provenance=_decode_migration(data.get("migration_provenance")),
    )
