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
    RESOLVED,
    SELECTED_OPTION_REMOVED,
    SLOT_REMOVED,
    UNSUPPORTED_SELECTION_POLICY,
    ReconciliationSourceDelta,
    SlotConfigurationResolution,
    SlotResolution,
)
from hwpxfiller.application.template_qualification import TemplateSlot
from hwpxfiller.application.work_slot_configuration import (
    WorkSlotConfigurationDraft,
    has_declared_selection,
)
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
# 재선택으로 닫을 수 없는 것들 — 「다른 것을 고르세요」가 할 수 없는 일을 시키는 자리다.
_UNSELECTABLE_STATUSES = frozenset({NO_AVAILABLE_OPTIONS, UNSUPPORTED_SELECTION_POLICY})
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
class ProjectedRetainedSelection:
    """successor 로 넘어온 뒤 **이전에 고른 것이 어떻게 됐는지**(#777).

    Template 이 바뀌면 SG-01(#733) compatibility gate 가 의미 동일성을 exact 증명하지 못한
    선택을 successor 선언집합에 싣지 않는다 — 그것이 fail-closed 설계다. 그런데 종전에는 그
    사실이 **아무 데도 안 남아서**, 사용자는 자기가 고른 셋이 어떻게 됐는지 묻지도 못한 채
    「아직 선택 안 함」만 봤다. 「숨기는 대신 비활성 + 사유 병기」의 정반대다.

    셋은 서로 **다른 행동**을 부른다(#728 H4). 그래서 한 값으로 뭉뚱그리지 않는다.

    ``RESOLVED``
        Slot·Option 이 successor 에도 있다. 그대로 다시 고르면 닫힌다.
        **자동 승계가 아니다** — Template 이 바뀌었으므로 확인은 사용자가 한다.
    ``SELECTED_OPTION_REMOVED``
        Slot 은 남았고 고른 Option 이 사라졌다. **다른 것을 골라야** 닫힌다.
    ``SLOT_REMOVED``
        항목 자체가 사라졌다. 정보일 뿐 현재 구성의 일부가 아니고 자동 부활하지 않는다.

    ``NO_AVAILABLE_OPTIONS``·``UNSUPPORTED_SELECTION_POLICY``
        Slot 은 남았지만 지금은 **고를 수 있는 것이 없다**. 「다른 것을 고르세요」는 할 수 없는
        일을 시키는 문안이라, 이 둘은 재선택 요구와 갈라 둔다.

    ``slot_display_text`` 는 현재 구조에 있는 Slot 만 채운다(사라진 Slot 은 `None`) — 내부 ID 를
    사용자에게 보이지 않는다(#728 H1).

    **이전에 고른 Option 의 이름은 싣지 않는다.** 남아 있는 것은 같은 ID 뿐이고, 그 ID 의
    **현재** 라벨은 이전 라벨이 아니다 — successor 가 같은 ID 를 다른 뜻으로 다시 쓰면(compatibility
    gate 가 의미 동일성 증명을 거절한 바로 그 경우) 현재 라벨을 「이전에 고르신 것」이라고 부르는
    순간 없는 역사를 지어낸다. predecessor 라벨은 보존되지 않으므로 이름 대신 Slot 과 개수로 말한다.
    """

    slot_id: str
    slot_display_text: str | None
    option_ids: tuple[str, ...]
    fate: str


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
    #: 「포함할 내용」 구획을 세울 것인가(U4 13번) — 판정은 :func:`content_selection_zone_actionable`
    #: 하나이고 링2 는 읽어 나르기만 한다. 링2 가 ``len(slots)`` 을 다시 세면 같은 상태를 두 곳이
    #: 판정하게 되고, 그 둘 중 하나만 늙는다.
    zone_actionable: bool = False
    #: 지금 Preset 으로 저장할 선택이 있는가 — 저장 게이트와 **같은** :func:`has_declared_selection`.
    savable_selection: bool = False
    retained_selections: tuple[ProjectedRetainedSelection, ...] = ()


def content_selection_zone_actionable(
    slots: "tuple[ProjectedSlot, ...]", configuration_status: str
) -> bool:
    """「포함할 내용」 구획을 세울 것인가 — U4 13번 판정의 **단 한 곳**.

    사용자 확정(2026-08-30): **고를 항목이 있을 때만** 선다. slot 이 없는 작업에서 이 구획은
    「이 문서 작업에는 선택할 내용이 없습니다.」한 줄로 영영 서 있었고, 그 줄은 사용자가 확인할
    것도 할 것도 아니었다 — U3 §3(#876)이 세운 「확인할 것이 없으면 숨김이 기본」의 적용이다.

    12번(#932 B5)의 스위치 트랩은 여기서 재현되지 않는다: 항목을 **만드는** 동사가 이 구획
    안에 없기 때문이다. 구간을 세우는 것은 「변경사항 확인」(템플릿 존)이고, 그 존은 자기 술어로
    따로 선다. 이 구획은 이미 있는 항목을 고르는 자리라 항목이 없으면 개시할 것도 없다.

    ``configuration_status`` 를 함께 묻는 이유는 **지시가 겨누는 자리**를 술어가 지게 하기
    위해서다. ``CHOOSE_CONTENT`` blocker 의 복구 동사가 이 구획 안의 라디오(``.cs-option-input``,
    :mod:`~hwpxfiller.webapp.blocker_affordance`)라, 그 blocker 가 서는 두 상태에서 구획이 사라지면
    **없는 자리를 가리키는 지시**가 된다(#912 가 이름 붙인 결함류). 오늘 그 두 상태는 slot ≥ 1
    을 함의하므로 이 갈래는 결과를 바꾸지 않지만, 함의가 깨지는 날 조용히 사라지는 것이 하필
    지시가 겨눈 자리다 — 그래서 결과가 아니라 **술어의 입력**으로 못박는다.
    """
    if configuration_status in (NEEDS_SELECTION, HAS_BROKEN_SELECTIONS):
        return True
    return len(slots) > 0


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
        # context error 는 이 두 축을 주장하지 않는다 — 구획은 「실패 재진술 + 복구 동사」로
        # 서고(그 갈래는 표면 소유), 저장할 선택도 구조 없이는 말할 수 없다.
        zone_actionable=False,
        savable_selection=False,
    )


def _configuration_status(resolution: SlotConfigurationResolution) -> str:
    if not resolution.applicable:
        return NOT_APPLICABLE
    if resolution.slot_selections_complete:
        return SLOT_SELECTIONS_COMPLETE
    if any(kind in _BROKEN_STATUSES for kind in resolution.blocking_kinds):
        return HAS_BROKEN_SELECTIONS
    return NEEDS_SELECTION


def project_retained_selections(
    context: SlotConfigurationContext,
    resolution: SlotConfigurationResolution,
    retained: SlotConfigurationResolution | None,
) -> tuple[ProjectedRetainedSelection, ...]:
    """이전 Configuration 의 **선언 선택**을 현재 구조에 대고 분류한 것을 DTO 로 shape 한다.

    입력은 이미 :func:`resolve_slot_configuration` 이 낸 판정이다 — 여기서 다시 판정하지 않고
    Slot 라벨만 붙이고, **현재 resolution 이 이미 닫은 항목을 걷어낸다**.

    닫힘의 기준은 「현재 Configuration 이 있는가」가 아니라 **「그 Slot 이 지금 유효 선택을
    갖는가」**다. 전자로 끊으면 successor 에서 한 칸을 고르는 순간 나머지 사연이 통째로
    증발한다 — 아직 안 고른 Slot 도, 사라진 항목도 함께.
    """
    if retained is None:
        return ()
    answered = {
        slot_res.slot_id for slot_res in resolution.slots if slot_res.effective_option_ids
    }
    slot_by_id = {slot.id: slot for slot in context.template_structure.slots}
    projected: list[ProjectedRetainedSelection] = []
    for slot_res in retained.slots:
        if not slot_res.declared_option_ids or slot_res.slot_id in answered:
            continue  # 이전에 안 골랐거나, 사용자가 이미 다시 골라 닫은 항목
        struct_slot = slot_by_id.get(slot_res.slot_id)
        removed = any(d.kind == SELECTED_OPTION_REMOVED for d in slot_res.diagnostics)
        if slot_res.status in _UNSELECTABLE_STATUSES:
            # 고를 수 있는 것이 없거나 현재 방식에서 선택 불가 — 재선택을 시킬 수 없다.
            fate = slot_res.status
        else:
            fate = SELECTED_OPTION_REMOVED if removed else RESOLVED
        projected.append(
            ProjectedRetainedSelection(
                slot_id=slot_res.slot_id,
                slot_display_text=(
                    _display_text(struct_slot.label, slot_res.slot_id) if struct_slot else None
                ),
                option_ids=slot_res.declared_option_ids,
                fate=fate,
            )
        )
    projected.extend(
        ProjectedRetainedSelection(
            slot_id=detached.slot_id,
            slot_display_text=None,  # 사라진 Slot 의 라벨은 현재 구조 어디에도 없다
            option_ids=detached.option_ids,
            fate=SLOT_REMOVED,
        )
        for detached in retained.detached_selections
    )
    return tuple(projected)


def project_current_slot_configuration(
    context: SlotConfigurationContext,
    configuration: WorkSlotConfigurationDraft | None,
    resolution: SlotConfigurationResolution,
    source_delta: ReconciliationSourceDelta | None = None,
    retained: SlotConfigurationResolution | None = None,
) -> CurrentSlotConfigurationView:
    """verified current context 의 Resolution 을 구조적 Projection DTO 로 shape 한다.

    configuration 은 fields 를 위해 쓰지 않는다(fields 는 exact structure 소유) — 부재/존재만
    이미 Resolution 에 반영돼 있다. structure.slots 와 resolution.slots 는 같은 순서·길이라
    zip 으로 정렬한다.

    ``retained`` 는 **이전 Configuration 의 선언 선택을 현재 구조에 대고** 판정한 별도 Resolution
    이다(#777). current resolution 과 섞지 않는다 — 그것은 「지금 무엇이 골라져 있는가」이고,
    이쪽은 「이전에 고른 것이 어떻게 됐는가」다. 둘을 한 값으로 뭉치면 아직 안 고른 것과 방금
    잃은 것이 같은 빈칸이 된다.
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

    status = _configuration_status(resolution)
    return CurrentSlotConfigurationView(
        view_status=CURRENT,
        configuration_status=status,
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
        zone_actionable=content_selection_zone_actionable(slots, status),
        savable_selection=has_declared_selection(configuration),
        retained_selections=project_retained_selections(context, resolution, retained),
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
