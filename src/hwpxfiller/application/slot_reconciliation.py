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

from hwpxfiller.application.selection_compatibility import (
    AUTO_KEEP,
    ChainApplicationFacts,
    SelectionCompatibilityFacts,
    classify_selection,
)
from hwpxfiller.application.template_qualification import TemplateStructure
from hwpxfiller.application.work_slot_configuration import (
    RECONCILED_FROM_PREDECESSOR,
    WorkSlotConfigurationDraft,
)
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
    # nearest config 를 찾더라도 chain 전체를 끝까지 걸어 무결성을 검증한 뒤 돌려준다 —
    # nearest 뒤쪽의 cycle·epoch skip·dangling 을 조용히 신뢰하지 않는다(fail-closed).
    seen: set[str] = {target.application_id}
    current = target
    nearest: WorkSlotConfigurationDraft | None = None
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
        # previous 는 정확히 한 epoch 아래여야 한다(Application 생성이 current+1) — skip 은
        # 중간 empty tombstone 을 건너뛰어 오래된 선택을 부활시킬 수 있어 거절한다.
        if prev.application_epoch != current.application_epoch - 1:
            raise ReconciliationIntegrityError(
                "previous epoch 이 정확히 1 감소하지 않는다(skip·역행)"
            )
        seen.add(prev.application_id)
        config = configurations.get(prev.application_id)
        if config is not None:
            # chain 안 모든 Configuration provenance 검증(#684 가 #676 으로 미룬 참조 무결성).
            # nearest 는 첫 발견만 기록하되 검증·chain 순회는 끝까지 이어간다.
            _validate_configuration_provenance(config, configurations)
            if nearest is None:
                nearest = config
        current = prev
    return nearest


def _validate_configuration_provenance(
    config: WorkSlotConfigurationDraft,
    configurations: Mapping[str, WorkSlotConfigurationDraft],
) -> None:
    """RECONCILED Configuration 의 predecessor 참조가 실재·version·digest 로 일치하는지 확인한다.

    #684 의 `WorkSlotConfigurationAggregate.__post_init__` 이 존재·version·digest 대조를
    successor reconciliation(여기)으로 명시 미뤘다 — 그 audit 무결성을 여기서 닫는다.
    """
    if config.origin != RECONCILED_FROM_PREDECESSOR:
        return
    source = configurations.get(config.reconciled_from_application_id or "")
    if source is None:
        raise ReconciliationIntegrityError(
            "reconciled_from Configuration 이 aggregate 에 없다(유령 승계)"
        )
    if source.version != config.reconciled_from_version:
        raise ReconciliationIntegrityError("reconciled_from version 이 provenance 와 불일치")
    if (
        declared_selection_digest(source.selections)
        != config.reconciled_from_declared_selection_digest
    ):
        raise ReconciliationIntegrityError("reconciled_from digest 가 provenance 와 불일치")


@dataclass(frozen=True)
class ReconciliationPlan:
    should_create_configuration: bool
    initial_selections: SlotSelectionSet
    source_application_id: str | None
    source_configuration_version: int | None
    source_declared_selection_digest: str | None
    resolution: SlotConfigurationResolution
    compatibility_facts: tuple[SelectionCompatibilityFacts, ...] = ()


def _ordered_chain(
    applications: Mapping[str, ReconciliationApplication],
    target_application_id: str,
    source_application_id: str,
) -> list[str]:
    """target → previous walk 로 source..target 순 application_id 리스트를 낸다.

    chain 무결성은 :func:`find_nearest_predecessor_configuration` 이 이미 검증했으므로 여기서는
    source 에 닿을 때까지 previous 를 걷기만 한다.

    # ponytail: AUTO_KEEP 는 epoch-contiguous previous_application_id walk 상의 연속성만 본다
    # (removal 을 넘어선 재등장은 REMOVED_IN_CHAIN 으로 REVIEW). branch/merge lineage 를
    # 다뤄야 하면 chain 을 DAG walk 로 승격한다 — 현재 lineage 는 선형이라 불필요.
    """
    ids: list[str] = []
    current: str | None = target_application_id
    while current is not None:
        ids.append(current)
        if current == source_application_id:
            break
        app = applications.get(current)
        current = app.previous_application_id if app is not None else None
    ids.reverse()
    return ids


def _compatibility_gated_selections(
    source_selections: SlotSelectionSet,
    contract: SelectionSemanticContractManifest,
    chain_ids: list[str],
    chain_facts: Mapping[str, ChainApplicationFacts],
    source_application_id: str,
) -> tuple[SlotSelectionSet, tuple[SelectionCompatibilityFacts, ...]]:
    """source declared 선택을 compatibility 로 걸러 AUTO_KEEP 만 successor 선언집합에 싣는다."""
    chain_structs = [
        chain_facts[aid].execution_structure if aid in chain_facts else None
        for aid in chain_ids
    ]
    src_facts = chain_facts.get(source_application_id)
    source_contract_id = src_facts.selection_contract_id if src_facts else None
    source_policy = src_facts.selection_policy if src_facts else None
    target_contract_id = contract.contract_id
    target_policy = resolve_selection_policy(contract, None)

    kept: list[SlotSelection] = []
    facts: list[SelectionCompatibilityFacts] = []
    for selection in source_selections.selections:
        kept_options: list[str] = []
        for option_id in selection.selected_option_ids:
            fact = classify_selection(
                selection.slot_id, option_id, chain_structs,
                source_contract_id=source_contract_id,
                target_contract_id=target_contract_id,
                source_policy=source_policy,
                target_policy=target_policy,
            )
            facts.append(fact)
            if fact.classification == AUTO_KEEP:
                kept_options.append(option_id)
        if kept_options:
            kept.append(SlotSelection(selection.slot_id, tuple(kept_options)))
    return SlotSelectionSet(tuple(kept)), tuple(facts)


def plan_successor_reconciliation(
    target_application_id: str,
    target_structure: TemplateStructure,
    contract: SelectionSemanticContractManifest,
    applications: Mapping[str, ReconciliationApplication],
    configurations: Mapping[str, WorkSlotConfigurationDraft],
    *,
    chain_facts: Mapping[str, ChainApplicationFacts] | None = None,
) -> ReconciliationPlan:
    """target Application 의 successor Configuration plan 을 낸다(create·fence 결선은 #677).

    같은 Lineage 이고 nearest predecessor 선택의 의미 호환성이 exact evidence 로 증명될 때만
    그 Option 을 successor 선언집합에 싣는다(``AUTO_KEEP``). 증명 못 하면(unknown/v1/변경/removed)
    싣지 않고 ``compatibility_facts`` 에 ``REVIEW_REQUIRED`` 로 남겨 사용자 재선택으로 닫는다.
    다른 Lineage 는 오늘처럼 empty 로 시작한다. ``chain_facts`` 미제공은 evidence-missing 으로
    취급돼 fail-closed(전부 REVIEW)된다.
    """
    facts_map = chain_facts if chain_facts is not None else {}
    target = applications[target_application_id]
    source = find_nearest_predecessor_configuration(
        target_application_id, applications, configurations
    )

    compatibility_facts: tuple[SelectionCompatibilityFacts, ...] = ()
    if source is None:
        initial = SlotSelectionSet(())
        source_id = source_version = source_digest = None
    else:
        source_id = source.base_template_application_id
        source_app = applications[source_id]
        same_lineage = source_app.template_lineage_id == target.template_lineage_id
        if same_lineage:
            chain_ids = _ordered_chain(applications, target_application_id, source_id)
            initial, compatibility_facts = _compatibility_gated_selections(
                source.selections, contract, chain_ids, facts_map, source_id
            )
        else:
            initial = SlotSelectionSet(())
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
        compatibility_facts=compatibility_facts,
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
