"""Application-bound Working Slot Configuration — 값 모델·version 의미·codec (S4-02 #672).

#671 의 :class:`SlotSelectionSet` 를 특정 Document Work 와 exact Template Application 에
결속된 mutable Working Configuration 으로 만든다. 이 모듈이 소유하는 것: identity
``(work_id, base_template_application_id)``, version 의미(declared 선택의 semantic value 가
바뀔 때만 +1), origin/predecessor provenance, explicit-empty tombstone 보존, per-Work
aggregate 와 dict codec 불변식.

**소유 밖(발명 금지)**: 파일 원자 store·Workspace identity·first-seen ledger(#673),
pure resolution·successor reconciliation·retained intent(#676), Select/Clear command·CAS·
fingerprint(#677), token·Product API(#679). 파생 상태(COMPLETE/BROKEN/MISSING, available
Option, TemplateStructure, policy, effective/detached selections, Projection DTO,
SourceDelta, active Field)는 **저장하지 않는다** — exact Structure·Contract 로 다시 계산한다.

historical immutability 는 모델 flag 가 아니라 command layer 의 shared fence 와 current
exact-match gate 가 맡는다 — 여기 모델에는 frozen 필드가 없다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from hwpxfiller.domain.slot_selection import (
    SlotSelectionSet,
    decode_selection_set,
    declared_selection_digest,
    encode_selection_set,
    semantic_selection_equal,
)

SCHEMA_VERSION = "work-slot-configuration-v1"

EMPTY = "EMPTY"
RECONCILED_FROM_PREDECESSOR = "RECONCILED_FROM_PREDECESSOR"
_ORIGINS = (EMPTY, RECONCILED_FROM_PREDECESSOR)


class WorkSlotConfigurationError(ValueError):
    """Working Configuration 불변식 위반."""


def _require_nonempty(value: object, what: str) -> str:
    if not isinstance(value, str) or value == "":
        raise WorkSlotConfigurationError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


@dataclass(frozen=True)
class WorkSlotConfigurationDraft:
    """exact Application 에 결속된 한 Working Configuration.

    identity = ``(work_id, base_template_application_id)`` — 별도 configuration_id 를
    발명하지 않는다. version 은 declared SelectionSet 의 semantic value 가 바뀔 때만 +1 이고
    aggregate version 과 분리된다(execution semantic identity 가 아니다).
    """

    work_id: str
    base_template_application_id: str
    version: int
    selections: SlotSelectionSet
    origin: str
    reconciled_from_application_id: str | None
    reconciled_from_version: int | None
    reconciled_from_declared_selection_digest: str | None
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _require_nonempty(self.work_id, "work_id")
        _require_nonempty(self.base_template_application_id, "base_template_application_id")
        _require_nonempty(self.created_at, "created_at")
        _require_nonempty(self.updated_at, "updated_at")
        if not isinstance(self.selections, SlotSelectionSet):
            raise WorkSlotConfigurationError("selections 는 SlotSelectionSet 이어야 한다")
        if self.version < 1:
            raise WorkSlotConfigurationError("version 은 1 이상이다")
        if self.origin not in _ORIGINS:
            raise WorkSlotConfigurationError(f"미상 origin {self.origin!r}")
        provenance = (
            self.reconciled_from_application_id,
            self.reconciled_from_version,
            self.reconciled_from_declared_selection_digest,
        )
        if self.origin == EMPTY:
            if any(p is not None for p in provenance):
                raise WorkSlotConfigurationError(
                    "EMPTY origin 은 predecessor provenance 를 가질 수 없다"
                )
        else:  # RECONCILED_FROM_PREDECESSOR
            if any(p is None for p in provenance):
                raise WorkSlotConfigurationError(
                    "RECONCILED origin 은 세 provenance 가 모두 있어야 한다"
                )
            _require_nonempty(
                self.reconciled_from_application_id, "reconciled_from_application_id"
            )
            _require_nonempty(
                self.reconciled_from_declared_selection_digest,
                "reconciled_from_declared_selection_digest",
            )
            assert self.reconciled_from_version is not None  # narrow for type checker
            if self.reconciled_from_version < 1:
                raise WorkSlotConfigurationError("reconciled_from_version 은 1 이상이다")

    @property
    def is_empty(self) -> bool:
        """explicit-empty tombstone — 존재하되 declared intent 가 비었다(Config 없음과 다르다)."""
        return len(self.selections.selections) == 0


def create_empty(
    work_id: str, base_template_application_id: str, now: str
) -> WorkSlotConfigurationDraft:
    """predecessor 없이 생긴 최초 empty Configuration(version 1)."""
    return WorkSlotConfigurationDraft(
        work_id=work_id,
        base_template_application_id=base_template_application_id,
        version=1,
        selections=SlotSelectionSet(()),
        origin=EMPTY,
        reconciled_from_application_id=None,
        reconciled_from_version=None,
        reconciled_from_declared_selection_digest=None,
        created_at=now,
        updated_at=now,
    )


def create_reconciled(
    work_id: str,
    base_template_application_id: str,
    selections: SlotSelectionSet,
    source_application_id: str,
    source_version: int,
    source_declared_selection_digest: str,
    now: str,
) -> WorkSlotConfigurationDraft:
    """predecessor 의 declared intent 를 옮겨 담아 생긴 Configuration(version 1).

    reconciliation 판정·source 선택 자체는 #676 이 낸다 — 여기서는 그 결과를 provenance
    와 함께 immutable value 로 담을 뿐이다.
    """
    return WorkSlotConfigurationDraft(
        work_id=work_id,
        base_template_application_id=base_template_application_id,
        version=1,
        selections=selections,
        origin=RECONCILED_FROM_PREDECESSOR,
        reconciled_from_application_id=source_application_id,
        reconciled_from_version=source_version,
        reconciled_from_declared_selection_digest=source_declared_selection_digest,
        created_at=now,
        updated_at=now,
    )


def apply_selections(
    draft: WorkSlotConfigurationDraft,
    new_selections: SlotSelectionSet,
    now: str,
) -> WorkSlotConfigurationDraft:
    """declared 선택을 갈아끼운 새 Draft — version 은 semantic value 가 바뀔 때만 +1.

    같은 선택 재선택·entry 없는 Slot clear 처럼 semantic no-op 이면 그대로 돌려준다(idempotent).
    origin·provenance 는 생성 이력이라 보존한다. Select/Clear 어느 선택을 바꿀지·CAS·
    fingerprint 는 #677 이 이 seam 위에 얹는다.
    """
    if semantic_selection_equal(draft.selections, new_selections):
        return draft
    return replace(
        draft,
        selections=new_selections,
        version=draft.version + 1,
        updated_at=now,
    )


@dataclass(frozen=True)
class WorkSlotConfigurationAggregate:
    """한 Document Work 의 모든 Application-bound Configuration 을 담는 per-Work 컨테이너.

    Work 는 Application history(A17·A18…)를 갖고 각 Application 마다 Configuration 하나가
    산다. store 결속·원자 replace 는 #673 이 진다 — 여기는 값·불변식·codec 이다.
    """

    schema_version: str
    work_id: str
    configurations: tuple[WorkSlotConfigurationDraft, ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.work_id, "work_id")
        seen: set[str] = set()
        for config in self.configurations:
            if config.work_id != self.work_id:
                raise WorkSlotConfigurationError(
                    "Configuration 의 work_id 가 aggregate owner 와 불일치"
                )
            if config.base_template_application_id in seen:
                raise WorkSlotConfigurationError(
                    "같은 Application 의 Configuration 중복"
                )
            seen.add(config.base_template_application_id)


def empty_aggregate(work_id: str) -> WorkSlotConfigurationAggregate:
    return WorkSlotConfigurationAggregate(
        schema_version=SCHEMA_VERSION, work_id=work_id, configurations=()
    )


# ─── codec ────────────────────────────────────────────────────────────────────

def _encode_config(config: WorkSlotConfigurationDraft) -> dict[str, Any]:
    return {
        "work_id": config.work_id,
        "base_template_application_id": config.base_template_application_id,
        "version": config.version,
        "selections": encode_selection_set(config.selections),
        # decode 시 재검증 가능한 seam — 저장 bytes 손상·의미 드리프트를 시끄럽게 잡는다.
        "declared_selection_digest": declared_selection_digest(config.selections),
        "origin": config.origin,
        "reconciled_from_application_id": config.reconciled_from_application_id,
        "reconciled_from_version": config.reconciled_from_version,
        "reconciled_from_declared_selection_digest": (
            config.reconciled_from_declared_selection_digest
        ),
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }


def _decode_config(data: Mapping[str, Any]) -> WorkSlotConfigurationDraft:
    selections = decode_selection_set(data["selections"])
    stored_digest = data.get("declared_selection_digest")
    if stored_digest != declared_selection_digest(selections):
        raise WorkSlotConfigurationError(
            "저장된 selection digest 가 복원 selection 과 불일치(손상·드리프트)"
        )
    return WorkSlotConfigurationDraft(
        work_id=data["work_id"],
        base_template_application_id=data["base_template_application_id"],
        version=data["version"],
        selections=selections,
        origin=data["origin"],
        reconciled_from_application_id=data.get("reconciled_from_application_id"),
        reconciled_from_version=data.get("reconciled_from_version"),
        reconciled_from_declared_selection_digest=data.get(
            "reconciled_from_declared_selection_digest"
        ),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )


def encode_aggregate(aggregate: WorkSlotConfigurationAggregate) -> dict[str, Any]:
    return {
        "schema_version": aggregate.schema_version,
        "work_id": aggregate.work_id,
        "configurations": [_encode_config(c) for c in aggregate.configurations],
    }


def decode_aggregate(data: Mapping[str, Any]) -> WorkSlotConfigurationAggregate:
    schema = data.get("schema_version")
    if schema != SCHEMA_VERSION:
        raise WorkSlotConfigurationError(f"미상 schema_version {schema!r}")
    return WorkSlotConfigurationAggregate(
        schema_version=SCHEMA_VERSION,
        work_id=data["work_id"],
        configurations=tuple(
            _decode_config(c) for c in data["configurations"]
        ),
    )
