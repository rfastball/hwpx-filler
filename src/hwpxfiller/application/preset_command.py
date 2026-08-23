"""Preset 동사의 pure 판정·결과 값 (S9-02 · #828).

적용은 **제안**이다(#821 D3): Preset 이 든 선택 묶음을 현재 구조에 대고 판정하는 일은 전부
기존 S4 기계(:func:`~hwpxfiller.application.slot_reconciliation.resolve_slot_configuration`)가
지고, 이 모듈은 그 판정을 **분류·병합·수치화**할 뿐이다 — 새 판정 기계는 0 개다. 깨진 선택은
조용히 버려지지 않고 detached 어휘(:class:`~hwpxfiller.application.slot_configuration_projection.ProjectedDetachedSelection`)
로 결과에 실려 loud 하게 재진술된다.

store·fence·IO 를 모른다(:class:`PresetStorePort` 로만 저장소를 본다 — 결선은
``external/slot_command_runner.py``). 진단 코드 어휘를 이 모듈이 소유하고, 문안은 소유하지
않는다 — 수치·코드는 여기, 사용자 문구는 웹(S9-03)이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from hwpxfiller.application.slot_command import CHANGED, NO_CHANGE
from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.slot_configuration_projection import (
    ProjectedDetachedSelection,
)
from hwpxfiller.application.slot_reconciliation import (
    RESOLVED,
    resolve_slot_configuration,
)
from hwpxfiller.application.work_slot_configuration import (
    WorkSlotConfigurationDraft,
    apply_selections,
)
from hwpxfiller.domain.preset import CorruptPresetEntry, SelectionPreset
from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet

# ─── 진단 코드(#821 §3 + 부재) ────────────────────────────────────────────────
PRESET_NAME_CONFLICT = "PRESET_NAME_CONFLICT"
PRESET_EMPTY_SELECTION = "PRESET_EMPTY_SELECTION"
PRESET_ENTRY_CORRUPT = "PRESET_ENTRY_CORRUPT"
PRESET_NOT_FOUND = "PRESET_NOT_FOUND"

# ─── 결과 status 어휘 ────────────────────────────────────────────────────────
SAVED = "SAVED"
NEEDS_CONFIRM = "NEEDS_CONFIRM"
REJECTED = "REJECTED"
DELETED = "DELETED"


class PresetSaveRejected(Exception):
    """저장 판정이 거절한 입력 — ``code`` 가 사유의 안정 축이다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ─── store port(application 은 external 을 import 하지 않는다) ────────────────
class PresetStorePort(Protocol):
    """:class:`~hwpxfiller.external.preset_store.PresetRegistry` 가 구조적으로 만족한다."""

    def add(self, preset: SelectionPreset) -> str: ...

    def save_confirmed(self, expected_key: str, preset: SelectionPreset) -> str: ...

    def delete_loaded(self, key: str) -> SelectionPreset: ...

    def load(self, key: str) -> SelectionPreset: ...

    def find_name(self, name: str) -> "tuple[str, SelectionPreset] | None": ...

    def list_presets(
        self,
    ) -> "tuple[list[tuple[str, SelectionPreset]], list[CorruptPresetEntry]]": ...


# ─── 저장 판정 ────────────────────────────────────────────────────────────────
def plan_preset_save(
    config: WorkSlotConfigurationDraft | None,
    name: str,
    provenance: dict[str, str],
    now: str,
) -> SelectionPreset:
    """현재 Configuration 의 **declared 선택 그대로** Preset 값을 만든다.

    complete 여부를 판정하지 않는다 — 저장은 「지금 고른 것의 보관」이지 실행 가능성의 승인이
    아니다. 그 판정은 적용 시점에 현재 구조에 대고 다시 선다.

    선택이 하나도 없으면(Configuration 부재 포함) :class:`PresetSaveRejected` —
    ``PRESET_EMPTY_SELECTION``. 이름 검증은 :class:`SelectionPreset` 생성이 진다.
    """
    if config is None or len(config.selections.selections) == 0:
        raise PresetSaveRejected(
            PRESET_EMPTY_SELECTION, "저장할 선택이 없습니다(선택 0건)."
        )
    return SelectionPreset(
        name=name,
        selection_set=config.selections,
        provenance=provenance,
        created_at=now,
    )


@dataclass(frozen=True)
class PresetSaveResult:
    """저장 시도의 판정·수치 — 문안 0(``detail`` 은 로그용 사실 서술)."""

    status: str  # SAVED | NEEDS_CONFIRM | REJECTED
    code: str | None  # None | PRESET_NAME_CONFLICT | PRESET_EMPTY_SELECTION
    saved_key: str | None
    existing_key: str | None  # NEEDS_CONFIRM 일 때 충돌 항목 key
    existing_created_at: str | None
    detail: str | None

    def __post_init__(self) -> None:
        if self.status == SAVED:
            if self.saved_key is None or self.code is not None:
                raise ValueError("SAVED 는 code 없이 saved_key 를 가진다")
        elif self.status == NEEDS_CONFIRM:
            if self.code != PRESET_NAME_CONFLICT or self.saved_key is not None:
                raise ValueError("NEEDS_CONFIRM 은 이름 충돌이고 저장하지 않는다")
        elif self.status == REJECTED:
            if self.code is None or self.saved_key is not None:
                raise ValueError("REJECTED 는 사유 코드를 갖고 저장하지 않는다")
        else:
            raise ValueError(f"미상 저장 status {self.status!r}")


# ─── 적용 판정 ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PresetApplyDecision:
    """적용 제안의 판정 결과 — **적용 n·깨짐 m 수치의 단일 출처**(#828).

    소비 표면은 이 값을 그대로 싣는다. 링2 가 slot 목록을 다시 훑어 개수를 재조립하면 같은
    상태를 두 곳이 판정하는 것이 된다.
    """

    outcome_code: str  # CHANGED | NO_CHANGE
    changed: bool
    new_config: WorkSlotConfigurationDraft | None  # 무변경이면 None
    source_version: int
    resulting_version: int
    applied_slot_ids: tuple[str, ...]
    broken: tuple[ProjectedDetachedSelection, ...]

    def __post_init__(self) -> None:
        if self.outcome_code not in (CHANGED, NO_CHANGE):
            raise ValueError(f"미상 적용 outcome {self.outcome_code!r}")
        if self.changed != (self.outcome_code == CHANGED):
            raise ValueError("outcome_code 와 changed 가 어긋난다")
        if self.changed != (self.new_config is not None):
            raise ValueError("changed 와 new_config 존재가 어긋난다")

    @property
    def applied_count(self) -> int:
        return len(self.applied_slot_ids)

    @property
    def broken_count(self) -> int:
        return len(self.broken)


def _overlay(
    base: SlotSelectionSet, applied: tuple[SlotSelection, ...]
) -> SlotSelectionSet:
    """기존 declared set 위에 적용 대상 entry 를 **덧씌운다**(교체/추가, 나머지 보존).

    전체 교체가 아닌 이유: Preset 이 언급하지 않은 Slot 의 기존 선택을 전체 교체는 **조용히
    소거**한다. 적용은 제안이지 소거 승인이 아니다(#821 D3). ``slot_command._with_slot`` 과
    동형이지만 그것은 정의 모듈 private 이라 여기 로컬로 둔다(한 순회로 끝난다).
    """
    replacement = {entry.slot_id: entry for entry in applied}
    merged = [replacement.get(entry.slot_id, entry) for entry in base.selections]
    present = {entry.slot_id for entry in base.selections}
    merged.extend(entry for entry in applied if entry.slot_id not in present)
    return SlotSelectionSet(tuple(merged))


def decide_apply_preset(
    ctx: SlotConfigurationContext,
    config: WorkSlotConfigurationDraft,
    proposal: SlotSelectionSet,
    now: str,
) -> PresetApplyDecision:
    """Preset 선택 묶음을 현재 구조에 대고 판정해 적용 대상과 깨진 것을 가른다.

    대조 대상은 **proposal 만**이다(현재 config 가 아니다) — 「이 Preset 이 지금 쓸 수 있는가」가
    물음이라 현재 선택을 섞으면 답이 흐려진다. 그래서 구조에는 있으나 proposal 이 언급하지
    않은 Slot 은 적용에도 깨짐에도 세지 않는다(이 명령의 대상이 아니다).

    깨진 entry 는 새 declared set 에 **싣지 않는다** — 보고로만 남는다. 유효하지 않은 값을
    Configuration 에 적어 두면 사용자가 고치지 않은 채로 blocked 상태만 늘어난다. proposal
    entry 는 option ≥1 이라 ``MISSING_REQUIRED_SELECTION`` 으로는 분류되지 않는다.
    """
    resolution = resolve_slot_configuration(
        proposal, ctx.template_structure, ctx.selection_semantic_contract
    )
    proposed = {
        entry.slot_id: entry.selected_option_ids for entry in proposal.selections
    }

    applied: list[SlotSelection] = []
    broken: list[ProjectedDetachedSelection] = []
    for slot_res in resolution.slots:  # structure 순서 = 결정론
        declared = proposed.get(slot_res.slot_id)
        if declared is None:
            continue
        if slot_res.status == RESOLVED:
            applied.append(
                SlotSelection(slot_res.slot_id, slot_res.effective_option_ids)
            )
        else:
            # RESOLVED 가 아닌 것은 **전부** 깨짐으로 보고한다(status 를 열거해 거르지 않는다):
            # 열거 밖의 status 가 생기면 그 entry 는 적용도 보고도 되지 않고 조용히 증발한다.
            broken.append(
                ProjectedDetachedSelection(
                    slot_id=slot_res.slot_id,
                    selected_option_ids=declared,
                    clearable=False,  # Configuration 에 실리지 않았으니 지울 것이 없다
                    status=slot_res.status,
                )
            )
    broken.extend(
        ProjectedDetachedSelection(
            slot_id=detached.slot_id,
            selected_option_ids=detached.option_ids,
            clearable=False,
        )
        for detached in resolution.detached_selections
    )

    source_version = config.version
    new_config = apply_selections(config, _overlay(config.selections, tuple(applied)), now)
    changed = new_config.version != source_version
    return PresetApplyDecision(
        outcome_code=CHANGED if changed else NO_CHANGE,
        changed=changed,
        new_config=new_config if changed else None,
        source_version=source_version,
        resulting_version=new_config.version,
        applied_slot_ids=tuple(entry.slot_id for entry in applied),
        broken=tuple(broken),
    )


# ─── 나열 ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PresetListItem:
    key: str
    name: str
    created_at: str
    provenance: dict[str, str]


@dataclass(frozen=True)
class PresetListing:
    """정상 항목과 손상 항목을 **함께** 낸다 — 비활성 + 사유 병기의 원천."""

    items: tuple[PresetListItem, ...]
    corrupt: tuple[CorruptPresetEntry, ...]
    corrupt_code: str = field(default=PRESET_ENTRY_CORRUPT)

    @property
    def corrupt_count(self) -> int:
        return len(self.corrupt)


def list_selection_presets(port: PresetStorePort) -> PresetListing:
    """이름순 목록 + 손상 항목. 손상을 목록에서 지우지 않는다(숨기면 사용자가 못 묻는다)."""
    entries, corrupt = port.list_presets()
    ordered = sorted(entries, key=lambda entry: (entry[1].name, entry[0]))
    return PresetListing(
        items=tuple(
            PresetListItem(
                key=key,
                name=preset.name,
                created_at=preset.created_at,
                provenance=preset.provenance_map,
            )
            for key, preset in ordered
        ),
        corrupt=tuple(corrupt),
    )


# ─── 삭제 ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PresetDeleteResult:
    status: str  # DELETED | REJECTED
    code: str | None  # None | PRESET_NOT_FOUND
    name: str | None  # 지워진 항목의 이름(파괴 재진술 소재)
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status == DELETED:
            if self.name is None or self.code is not None:
                raise ValueError("DELETED 는 code 없이 지워진 이름을 재진술한다")
        elif self.status == REJECTED:
            if self.code is None or self.name is not None:
                raise ValueError("REJECTED 는 사유 코드를 갖고 이름을 주장하지 않는다")
        else:
            raise ValueError(f"미상 삭제 status {self.status!r}")


def delete_selection_preset(port: PresetStorePort, key: str) -> PresetDeleteResult:
    """삭제 위임 + 지워진 항목의 이름 재진술.

    부재·불량 키·읽을 수 없는 항목은 ``PRESET_NOT_FOUND`` 로 접고 사유를 ``detail`` 에 그대로
    남긴다 — 코드는 「지울 대상을 얻지 못했다」 하나이되 이유는 숨기지 않는다.
    """
    try:
        preset = port.delete_loaded(key)
    except (FileNotFoundError, ValueError) as exc:
        return PresetDeleteResult(REJECTED, PRESET_NOT_FOUND, None, str(exc))
    return PresetDeleteResult(DELETED, None, preset.name, None)
