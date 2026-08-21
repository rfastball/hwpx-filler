"""구조적 Interactive Slot Projection — Resolution → Product DTO (S4-08 · #678).

#676 :class:`SlotConfigurationResolution` 과 exact :class:`SlotConfigurationContext`,
current Working Configuration(또는 명시 부재), optional
:class:`ReconciliationSourceDelta` 를 **JSON-safe read-model** 로 shape 한다. 정상 경로에서
HWPX bytes 를 다시 parse 하지 않는다(context 가 이미 decode 한 structure·contract 만 읽는다).

이 layer 는 ring1 판정을 **재조립하지 않는다**. per-slot status·effective·detached 는
Resolution 이 이미 판정했고 여기선 값을 primitive 로 shape 할 뿐이다. 소유하는 것 셋:

1. DTO shape(:class:`CurrentSlotConfigurationView` 이하 전 sub-DTO),
2. mutation-outcome ↔ current-view 분리(``view_status`` 는 request stale 여부와 무관하게
   verified current context 면 ``CURRENT``),
3. ``configuration_status`` mapping(0-slot / missing-only / broken / complete).

소유 밖: Product token 문자열·Product API(#679), Snapshot(#680), run bridge(#681).
display_text 는 canonical label 이며, historical label 부재는 ID 와 명시적 표식으로 드러낸다.
"""

from __future__ import annotations

from dataclasses import dataclass

from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.slot_reconciliation import (
    SELECTED_OPTION_REMOVED,
    SLOT_REMOVED,
    UNSUPPORTED_SELECTION_POLICY,
    ReconciliationSourceDelta,
    SlotConfigurationResolution,
    SlotResolution,
)
from hwpxfiller.application.template_qualification import TemplateSlot
from hwpxfiller.application.work_slot_configuration import WorkSlotConfigurationDraft
from hwpxfiller.domain.slot_selection import (
    CARDINALITY_VIOLATION,
    MISSING_REQUIRED_SELECTION,
    NO_AVAILABLE_OPTIONS,
)

# ─── view_status ────────────────────────────────────────────────────────────────
CURRENT = "CURRENT"
CONTEXT_ERROR = "CONTEXT_ERROR"

# ─── configuration_status ────────────────────────────────────────────────────────
NOT_APPLICABLE = "NOT_APPLICABLE"
NEEDS_SELECTION = "NEEDS_SELECTION"
HAS_BROKEN_SELECTIONS = "HAS_BROKEN_SELECTIONS"
SLOT_SELECTIONS_COMPLETE = "SLOT_SELECTIONS_COMPLETE"

# "removed selected option · cardinality · no options · unsupported policy" = broken.
# missing-required 만 있으면 broken 이 아니라 NEEDS_SELECTION 이다.
_BROKEN_STATUSES = frozenset(
    {
        SELECTED_OPTION_REMOVED,
        CARDINALITY_VIOLATION,
        NO_AVAILABLE_OPTIONS,
        UNSUPPORTED_SELECTION_POLICY,
    }
)
# primary blocking = broken + missing-required(= NEEDS_SELECTION 유발 blocker).
_BLOCKING_STATUSES = _BROKEN_STATUSES | {MISSING_REQUIRED_SELECTION}


@dataclass(frozen=True)
class ProjectedDiagnostic:
    kind: str
    option_id: str | None = None


@dataclass(frozen=True)
class ProjectedOption:
    option_id: str
    display_text: str
    selected: bool
    effective: bool
    structurally_associated_field_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProjectedSlot:
    slot_id: str
    display_text: str
    selection_policy: str | None
    status: str
    declared_option_ids: tuple[str, ...]
    effective_option_ids: tuple[str, ...]
    options: tuple[ProjectedOption, ...]
    shared_field_ids: tuple[str, ...]
    diagnostics: tuple[ProjectedDiagnostic, ...]


@dataclass(frozen=True)
class ProjectedDetachedSelection:
    slot_id: str
    selected_option_ids: tuple[str, ...]
    clearable: bool
    status: str = SLOT_REMOVED


@dataclass(frozen=True)
class ProjectedChangeItem:
    """flat structural index(banner·notices 용) — Product 문구는 #679 가 kind 로 조립한다."""

    slot_id: str
    kind: str
    option_id: str | None = None


@dataclass(frozen=True)
class ProjectionSummary:
    blocking_kinds: tuple[str, ...]
    missing_selection_count: int
    broken_selection_count: int
    detached_selection_count: int
    slot_selections_complete: bool


@dataclass(frozen=True)
class ProjectionReconciliationChanges:
    """source-relative 구조 변화("지난 구성 이후") — delta 있을 때만. immediate transition 아님."""

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
    option_order_changes: tuple[str, ...]


@dataclass(frozen=True)
class CurrentSlotConfigurationView:
    """구조적 Interactive Projection DTO — JSON-safe(dataclasses.asdict → dict/list/str/int/bool).

    ``view_status`` 는 request 의 stale 여부와 **무관**하다 — verified current context 면
    ``CURRENT`` + projection, context error 면 ``CONTEXT_ERROR`` + no projection(partial fallback 없음).
    request stale 관계는 :class:`ConfigurationMutationOutcome` 축이 따로 진다.
    """

    view_status: str
    configuration_status: str
    context_error: str | None
    context_error_detail: str | None
    configuration_present: bool
    configuration_version: int | None
    summary: ProjectionSummary | None
    slots: tuple[ProjectedSlot, ...]
    detached_selections: tuple[ProjectedDetachedSelection, ...]
    reconciliation_changes: ProjectionReconciliationChanges | None
    blocking_items: tuple[ProjectedChangeItem, ...]
    informational_changes: tuple[ProjectedChangeItem, ...]


def project_context_error(
    context_error_code: str, context_error_detail: str | None = None
) -> CurrentSlotConfigurationView:
    """context error → normal projection 을 구성했다고 주장하지 않는다(NOT_APPLICABLE·비어 있음).

    ``context_error_code`` 는 :class:`SlotConfigurationContextError` 의 stable ``.code`` 다 —
    localized 메시지가 아니라 안정 코드로 분기하라고 그것을 싣는다. 원문은 detail 로만 남긴다.
    """
    return CurrentSlotConfigurationView(
        view_status=CONTEXT_ERROR,
        configuration_status=NOT_APPLICABLE,
        context_error=context_error_code,
        context_error_detail=context_error_detail,
        configuration_present=False,
        configuration_version=None,
        summary=None,
        slots=(),
        detached_selections=(),
        reconciliation_changes=None,
        blocking_items=(),
        informational_changes=(),
    )


def _configuration_status(resolution: SlotConfigurationResolution) -> str:
    if not resolution.applicable:
        return NOT_APPLICABLE
    if resolution.slot_selections_complete:
        return SLOT_SELECTIONS_COMPLETE
    if any(kind in _BROKEN_STATUSES for kind in resolution.blocking_kinds):
        return HAS_BROKEN_SELECTIONS
    return NEEDS_SELECTION


def project_current_slot_configuration(
    context: SlotConfigurationContext,
    configuration: WorkSlotConfigurationDraft | None,
    resolution: SlotConfigurationResolution,
    source_delta: ReconciliationSourceDelta | None = None,
) -> CurrentSlotConfigurationView:
    """verified current context 의 Resolution 을 구조적 Projection DTO 로 shape 한다.

    configuration 은 fields 를 위해 쓰지 않는다(fields 는 exact structure 소유) — 부재/존재만
    이미 Resolution 에 반영돼 있다. structure.slots 와 resolution.slots 는 같은 순서·길이라
    zip 으로 정렬한다.
    """
    structure = context.template_structure
    slots = tuple(
        _project_slot(struct_slot, slot_res)
        for struct_slot, slot_res in zip(structure.slots, resolution.slots, strict=True)
    )
    detached = tuple(
        ProjectedDetachedSelection(
            slot_id=d.slot_id,
            selected_option_ids=d.option_ids,
            clearable=True,  # detached retained intent 는 clear 로 제거 가능(#677).
        )
        for d in resolution.detached_selections
    )

    missing = sum(1 for s in resolution.slots if s.status == MISSING_REQUIRED_SELECTION)
    broken = sum(1 for s in resolution.slots if s.status in _BROKEN_STATUSES)
    summary = ProjectionSummary(
        blocking_kinds=resolution.blocking_kinds,
        missing_selection_count=missing,
        broken_selection_count=broken,
        detached_selection_count=len(detached),
        slot_selections_complete=resolution.slot_selections_complete,
    )

    # blocking index: 각 slot 의 primary blocker + secondary diagnostic(제거된 option_id 보존).
    # structure 순서로 결정론. primary 만 보면 어떤 선택이 사라졌는지(option_id)를 잃는다.
    blocking_items: list[ProjectedChangeItem] = []
    for sr in resolution.slots:
        if sr.status in _BLOCKING_STATUSES:
            blocking_items.append(ProjectedChangeItem(slot_id=sr.slot_id, kind=sr.status))
        blocking_items.extend(
            ProjectedChangeItem(slot_id=sr.slot_id, kind=d.kind, option_id=d.option_id)
            for d in sr.diagnostics
        )
    informational = tuple(
        ProjectedChangeItem(slot_id=d.slot_id, kind=SLOT_REMOVED) for d in detached
    )

    return CurrentSlotConfigurationView(
        view_status=CURRENT,
        configuration_status=_configuration_status(resolution),
        context_error=None,
        context_error_detail=None,
        configuration_present=configuration is not None,
        configuration_version=configuration.version if configuration is not None else None,
        summary=summary,
        slots=slots,
        detached_selections=detached,
        reconciliation_changes=_project_delta(source_delta),
        blocking_items=tuple(blocking_items),
        informational_changes=informational,
    )


def _project_slot(struct_slot: TemplateSlot, slot_res: SlotResolution) -> ProjectedSlot:
    declared = set(slot_res.declared_option_ids)
    effective = set(slot_res.effective_option_ids)
    options = tuple(
        ProjectedOption(
            option_id=opt.id,
            display_text=_display_text(opt.label, opt.id),
            selected=opt.id in declared,
            effective=opt.id in effective,
            structurally_associated_field_ids=opt.fields,
        )
        for opt in struct_slot.options
    )
    return ProjectedSlot(
        slot_id=slot_res.slot_id,
        display_text=_display_text(struct_slot.label, slot_res.slot_id),
        selection_policy=slot_res.policy,
        status=slot_res.status,
        declared_option_ids=slot_res.declared_option_ids,
        effective_option_ids=slot_res.effective_option_ids,
        options=options,
        shared_field_ids=struct_slot.shared_fields,
        diagnostics=tuple(
            ProjectedDiagnostic(kind=d.kind, option_id=d.option_id)
            for d in slot_res.diagnostics
        ),
    )


def _display_text(label: str | None, identifier: str) -> str:
    return label if label is not None else f"라벨 미지정 (ID: {identifier})"


def _project_delta(
    delta: ReconciliationSourceDelta | None,
) -> ProjectionReconciliationChanges | None:
    if delta is None:
        return None
    return ProjectionReconciliationChanges(
        source_application_id=delta.source_application_id,
        source_configuration_version=delta.source_configuration_version,
        target_application_id=delta.target_application_id,
        added_slot_ids=delta.added_slot_ids,
        removed_slot_ids=delta.removed_slot_ids,
        added_option_refs=delta.added_option_refs,
        removed_option_refs=delta.removed_option_refs,
        removed_selected_option_refs=delta.removed_selected_option_refs,
        preserved_selection_refs=delta.preserved_selection_refs,
        slot_order_changed=delta.slot_order_changed,
        option_order_changes=delta.option_order_changes,
    )
