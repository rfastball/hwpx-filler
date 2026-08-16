"""Working Configuration 의 pure resolution·successor reconciliation·source delta (S4-06 · #676).

이 모듈은 순수하다: store·PerWorkMutationFence·Product token·UI·native HWPX 타입·latest
Revision 검색을 모른다. 세 가지를 소유한다.

1. **resolver** — declared :class:`SlotSelectionSet` 를 exact TemplateStructure·SelectionSemantic
   Contract 에 대고 판정해 RESOLVED/blocking/detached 로 가른다. 파생 상태를 저장하지 않고
   매번 재계산한다.
2. **successor reconciliation** — target Application 의 `previous_application_id` chain 을 걸어
   **nearest predecessor Configuration** 을 찾고(시간순 아님), 같은 Lineage 일 때만 declared
   SelectionSet 을 복사해 successor plan 을 낸다. cycle·dangling·epoch 역행·cross-Work 는 fail-closed.
3. **source delta** — nearest predecessor 대비 added/removed/preserved 를 결정론으로 낸다(UI 문구용).

**retained intent 는 별도 상태가 아니다**: Configuration 이 declared entry 를 지우지 않고 보존하면,
resolver 가 각 시점 structure 에 대고 분류한다 — 제거된 Slot 은 detached, 같은 ID 재등장 시 자동
RESOLVED. clear(#677)만 entry 를 지운다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from hwpxfiller.application.template_qualification import TemplateStructure
from hwpxfiller.application.work_slot_configuration import WorkSlotConfigurationDraft
from hwpxfiller.domain.slot_selection import (
    CARDINALITY_VIOLATION,
    MISSING_REQUIRED_SELECTION,
    NO_AVAILABLE_OPTIONS,
    SATISFIED,
    SelectionSemanticContractManifest,
    SlotSelection,
    SlotSelectionSet,
    UnsupportedSelectionPolicyError,
    declared_selection_digest,
    evaluate_slot,
    resolve_selection_policy,
)

# 판정 status 어휘.
RESOLVED = "RESOLVED"
SELECTED_OPTION_REMOVED = "SELECTED_OPTION_REMOVED"
UNSUPPORTED_SELECTION_POLICY = "UNSUPPORTED_SELECTION_POLICY"
SLOT_REMOVED = "SLOT_REMOVED"  # detached only

# top-level configuration status.
NOT_APPLICABLE = "NOT_APPLICABLE"
COMPLETE = "COMPLETE"
BLOCKED = "BLOCKED"

_BLOCKING_STATUSES = frozenset(
    {
        MISSING_REQUIRED_SELECTION,
        SELECTED_OPTION_REMOVED,
        CARDINALITY_VIOLATION,
        NO_AVAILABLE_OPTIONS,
        UNSUPPORTED_SELECTION_POLICY,
    }
)


class ReconciliationIntegrityError(Exception):
    """Application chain 무결성 위반(cycle·dangling·epoch 역행·cross-Work)."""


@dataclass(frozen=True)
class SlotDiagnostic:
    kind: str
    option_id: str | None = None


@dataclass(frozen=True)
class SlotResolution:
    slot_id: str
    policy: str | None
    declared_option_ids: tuple[str, ...]
    effective_option_ids: tuple[str, ...]
    status: str
    available_option_ids: tuple[str, ...]
    diagnostics: tuple[SlotDiagnostic, ...]


@dataclass(frozen=True)
class DetachedSelection:
    slot_id: str
    option_ids: tuple[str, ...]
    kind: str = SLOT_REMOVED


@dataclass(frozen=True)
class SlotConfigurationResolution:
    applicable: bool
    configuration_status: str
    slots: tuple[SlotResolution, ...]
    effective_selections: SlotSelectionSet
    detached_selections: tuple[DetachedSelection, ...]
    blocking_diagnostics: tuple[tuple[str, str], ...]  # (slot_id, status)
    blocking_kinds: tuple[str, ...]
    slot_selections_complete: bool


def _available_option_ids(slot_options: tuple) -> tuple[str, ...]:
    return tuple(opt.id for opt in slot_options)


def _resolve_one_slot(
    slot_id: str,
    available: tuple[str, ...],
    declared: tuple[str, ...],
    contract: SelectionSemanticContractManifest,
) -> SlotResolution:
    available_set = set(available)
    # 제거된 선택 option 은 primary status 와 무관하게 diagnostic 으로 함께 낸다.
    removed = tuple(
        SlotDiagnostic(SELECTED_OPTION_REMOVED, oid)
        for oid in declared
        if oid not in available_set
    )
    try:
        policy = resolve_selection_policy(contract, None)
        card = evaluate_slot(policy, len(available), len(declared))
    except UnsupportedSelectionPolicyError:
        return SlotResolution(
            slot_id, None, declared, (), UNSUPPORTED_SELECTION_POLICY, available, removed
        )

    if card == NO_AVAILABLE_OPTIONS:
        status = NO_AVAILABLE_OPTIONS
    elif card == MISSING_REQUIRED_SELECTION:
        status = MISSING_REQUIRED_SELECTION
    elif card == CARDINALITY_VIOLATION:  # 2개 이상
        status = CARDINALITY_VIOLATION
    else:  # SATISFIED: 정확히 1개
        status = RESOLVED if declared[0] in available_set else SELECTED_OPTION_REMOVED

    effective = (declared[0],) if status == RESOLVED else ()
    return SlotResolution(
        slot_id, policy, declared, effective, status, available, removed
    )


def resolve_slot_configuration(
    selections: SlotSelectionSet,
    structure: TemplateStructure,
    contract: SelectionSemanticContractManifest,
) -> SlotConfigurationResolution:
    """declared 선택을 exact structure·contract 에 대고 판정한다(store·HWPX 무관)."""
    declared_by_slot = {s.slot_id: s.selected_option_ids for s in selections.selections}
    current_slot_ids = {slot.id for slot in structure.slots}

    slots: list[SlotResolution] = []
    for slot in structure.slots:  # structure 순서 = 결정론
        available = _available_option_ids(slot.options)
        declared = declared_by_slot.get(slot.id, ())
        slots.append(_resolve_one_slot(slot.id, available, declared, contract))

    # declared 이지만 current structure 에 없는 Slot = detached retained intent.
    detached = tuple(
        DetachedSelection(s.slot_id, s.selected_option_ids)
        for s in selections.selections
        if s.slot_id not in current_slot_ids
    )

    effective = SlotSelectionSet(
        tuple(
            SlotSelection(sr.slot_id, sr.effective_option_ids)
            for sr in slots
            if sr.status == RESOLVED
        )
    )
    blocking = tuple(
        (sr.slot_id, sr.status) for sr in slots if sr.status in _BLOCKING_STATUSES
    )
    blocking_kinds = tuple(dict.fromkeys(status for _sid, status in blocking))

    applicable = len(structure.slots) >= 1
    complete = applicable and all(sr.status == RESOLVED for sr in slots)
    if not applicable:
        config_status = NOT_APPLICABLE
    elif complete:
        config_status = COMPLETE
    else:
        config_status = BLOCKED

    return SlotConfigurationResolution(
        applicable=applicable,
        configuration_status=config_status,
        slots=tuple(slots),
        effective_selections=effective,
        detached_selections=detached,
        blocking_diagnostics=blocking,
        blocking_kinds=blocking_kinds,
        slot_selections_complete=complete,
    )


# ─── successor reconciliation ────────────────────────────────────────────────
@dataclass(frozen=True)
class ReconciliationApplication:
    """reconciliation 이 필요한 Application 필드만 담은 pure 입력(store 무관)."""

    application_id: str
    previous_application_id: str | None
    application_epoch: int
    work_id: str
    template_lineage_id: str


def find_nearest_predecessor_configuration(
    target_application_id: str,
    applications: Mapping[str, ReconciliationApplication],
    configurations: Mapping[str, WorkSlotConfigurationDraft],
) -> WorkSlotConfigurationDraft | None:
    """previous_application_id chain 을 걸어 Configuration 이 있는 nearest predecessor 를 낸다.

    시간순 정렬을 쓰지 않는다. nearest 가 empty tombstone 이어도 거기서 멈춘다(더 오래된
    non-empty 를 부활시키지 않는다). cycle·dangling·epoch 역행·cross-Work 는 fail-closed.
    """
    target = applications.get(target_application_id)
    if target is None:
        raise ReconciliationIntegrityError(
            f"target application {target_application_id} 부재"
        )
    seen: set[str] = {target.application_id}
    current = target
    while current.previous_application_id is not None:
        prev = applications.get(current.previous_application_id)
        if prev is None:
            raise ReconciliationIntegrityError(
                f"dangling previous_application_id: {current.previous_application_id}"
            )
        if prev.application_id in seen:
            raise ReconciliationIntegrityError(
                f"application chain cycle: {prev.application_id}"
            )
        if prev.work_id != target.work_id:
            raise ReconciliationIntegrityError("chain 이 다른 Work 를 가리킨다")
        if prev.application_epoch >= current.application_epoch:
            raise ReconciliationIntegrityError(
                "epoch 이 previous 로 갈수록 정확히 감소하지 않는다"
            )
        seen.add(prev.application_id)
        config = configurations.get(prev.application_id)
        if config is not None:
            return config  # nearest — empty 여도 barrier 로 멈춘다
        current = prev
    return None


@dataclass(frozen=True)
class ReconciliationPlan:
    should_create_configuration: bool
    initial_selections: SlotSelectionSet
    source_application_id: str | None
    source_configuration_version: int | None
    source_declared_selection_digest: str | None
    resolution: SlotConfigurationResolution


def plan_successor_reconciliation(
    target_application_id: str,
    target_structure: TemplateStructure,
    contract: SelectionSemanticContractManifest,
    applications: Mapping[str, ReconciliationApplication],
    configurations: Mapping[str, WorkSlotConfigurationDraft],
) -> ReconciliationPlan:
    """target Application 의 successor Configuration plan 을 낸다(create·fence 결선은 #677).

    같은 Lineage 일 때만 nearest predecessor 의 declared SelectionSet 을 복사한다(retained intent
    포함 — 제거된 Slot entry 도 옮긴다). 다른 Lineage 는 empty 로 시작한다.
    """
    target = applications[target_application_id]
    source = find_nearest_predecessor_configuration(
        target_application_id, applications, configurations
    )

    if source is None:
        initial = SlotSelectionSet(())
        source_id = source_version = source_digest = None
    else:
        source_app = applications[source.base_template_application_id]
        same_lineage = source_app.template_lineage_id == target.template_lineage_id
        initial = source.selections if same_lineage else SlotSelectionSet(())
        source_id = source.base_template_application_id
        source_version = source.version
        source_digest = declared_selection_digest(source.selections)

    resolution = resolve_slot_configuration(initial, target_structure, contract)

    # target Slot 0개 규칙: source 없음/empty → 생성 생략, source non-empty → 전부 detached 생성.
    has_target_slots = len(target_structure.slots) >= 1
    if has_target_slots:
        should_create = True
    else:
        should_create = bool(resolution.detached_selections)

    return ReconciliationPlan(
        should_create_configuration=should_create,
        initial_selections=initial,
        source_application_id=source_id,
        source_configuration_version=source_version,
        source_declared_selection_digest=source_digest,
        resolution=resolution,
    )


# ─── source delta (UI 문구용, 정본 아님) ──────────────────────────────────────
@dataclass(frozen=True)
class ReconciliationSourceDelta:
    source_application_id: str
    source_configuration_version: int
    target_application_id: str
    added_slot_ids: tuple[str, ...]
    removed_slot_ids: tuple[str, ...]
    added_option_refs: tuple[tuple[str, str], ...]
    removed_option_refs: tuple[tuple[str, str], ...]
    removed_selected_option_refs: tuple[tuple[str, str], ...]
    preserved_selection_refs: tuple[tuple[str, str], ...]
    slot_order_changed: bool
    option_order_changes: tuple[str, ...]  # order 가 바뀐 slot_id 들


def _slot_option_map(structure: TemplateStructure) -> dict[str, tuple[str, ...]]:
    return {slot.id: _available_option_ids(slot.options) for slot in structure.slots}


def derive_reconciliation_source_delta(
    source_application_id: str,
    source_configuration_version: int,
    source_selections: SlotSelectionSet,
    source_structure: TemplateStructure,
    target_application_id: str,
    target_structure: TemplateStructure,
) -> ReconciliationSourceDelta:
    """nearest predecessor 대비 결정론 delta. source 는 **즉시 이전 Application 이 아니다**.

    "지난 구성 이후" 의미다 — immediate transition delta 로 오표시하지 않는다.
    """
    src = _slot_option_map(source_structure)
    tgt = _slot_option_map(target_structure)
    src_slots, tgt_slots = list(src), list(tgt)

    added_slots = tuple(sorted(set(tgt) - set(src)))
    removed_slots = tuple(sorted(set(src) - set(tgt)))
    common = [s for s in tgt_slots if s in src]

    added_opts: list[tuple[str, str]] = []
    removed_opts: list[tuple[str, str]] = []
    option_order_changes: list[str] = []
    for sid in common:
        s_opts, t_opts = src[sid], tgt[sid]
        added_opts += [(sid, o) for o in t_opts if o not in set(s_opts)]
        removed_opts += [(sid, o) for o in s_opts if o not in set(t_opts)]
        # 같은 집합인데 순서만 다르면 order change.
        if set(s_opts) == set(t_opts) and s_opts != t_opts:
            option_order_changes.append(sid)

    selected = {
        (s.slot_id, oid) for s in source_selections.selections for oid in s.selected_option_ids
    }
    removed_selected = tuple(
        sorted(
            ref
            for ref in selected
            if ref[0] not in tgt or ref[1] not in set(tgt.get(ref[0], ()))
        )
    )
    preserved = tuple(
        sorted(
            ref
            for ref in selected
            if ref[0] in tgt and ref[1] in set(tgt.get(ref[0], ()))
        )
    )
    slot_order_changed = [s for s in src_slots if s in tgt] != [
        s for s in tgt_slots if s in src
    ]

    return ReconciliationSourceDelta(
        source_application_id=source_application_id,
        source_configuration_version=source_configuration_version,
        target_application_id=target_application_id,
        added_slot_ids=added_slots,
        removed_slot_ids=removed_slots,
        added_option_refs=tuple(sorted(added_opts)),
        removed_option_refs=tuple(sorted(removed_opts)),
        removed_selected_option_refs=removed_selected,
        preserved_selection_refs=preserved,
        slot_order_changed=slot_order_changed,
        option_order_changes=tuple(option_order_changes),
    )
