"""구조적 Interactive Slot Projection DTO (S4-08 · #678).

pure Resolution → Product DTO shaping 만 검증한다(store·fence·HWPX 무관). #676 resolver·
#674 context 값 모델을 fixture 로 재사용한다.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.slot_configuration_projection import (
    CONTEXT_ERROR,
    CURRENT,
    HAS_BROKEN_SELECTIONS,
    NEEDS_SELECTION,
    NOT_APPLICABLE,
    SLOT_SELECTIONS_COMPLETE,
    project_context_error,
    project_current_slot_configuration,
)
from hwpxfiller.application.slot_reconciliation import (
    SLOT_REMOVED,
    derive_reconciliation_source_delta,
    resolve_slot_configuration,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_slot_configuration import create_empty
from hwpxfiller.domain.slot_selection import (
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SelectionSemanticContractManifest,
    SlotSelection,
    SlotSelectionSet,
)

V1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")
BAD_CONTRACT = SelectionSemanticContractManifest(
    "slot-selection/x", "s", "c", "MANY", ("MANY",), "v"
)


def _structure(*slots: TemplateSlot) -> TemplateStructure:
    return TemplateStructure(slots=slots)


def _slot(
    sid: str,
    opts: list[TemplateOption],
    shared: tuple[str, ...] = (),
    label: str | None = None,
) -> TemplateSlot:
    return TemplateSlot(sid, shared_fields=shared, options=tuple(opts), label=label)


def _sel(*pairs: tuple[str, list[str]]) -> SlotSelectionSet:
    return SlotSelectionSet(tuple(SlotSelection(s, tuple(o)) for s, o in pairs))


def _ctx(structure: TemplateStructure) -> SlotConfigurationContext:
    return SlotConfigurationContext(
        workspace_instance_id="ws",
        work_id="w1",
        template_application_id="A1",
        template_lineage_id="L1",
        application_epoch=1,
        pass_evidence_id="E1",
        revision_id="R1",
        qualification_profile_id="P1",
        structure_projection_schema_version="hwpx-structure-projection-v1",
        template_structure=structure,
        template_structure_digest="sha256:d",
        selection_semantic_contract_id="slot-selection/v1",
        selection_semantic_contract=V1,
    )


def _project(structure, selections, contract=V1, source_delta=None):
    resolution = resolve_slot_configuration(selections, structure, contract)
    return project_current_slot_configuration(
        _ctx(structure), None, resolution, source_delta
    )


# ── configuration_status mapping table ────────────────────────────────────────
@pytest.mark.parametrize(
    "structure,selections,contract,expected",
    [
        # 0 slots → NOT_APPLICABLE.
        (_structure(), _sel(), V1, NOT_APPLICABLE),
        # missing required, 다른 broker 없음 → NEEDS_SELECTION.
        (_structure(_slot("s", [TemplateOption("A")])), _sel(), V1, NEEDS_SELECTION),
        # removed selected option → HAS_BROKEN_SELECTIONS.
        (
            _structure(_slot("s", [TemplateOption("A")])),
            _sel(("s", ["Z"])),
            V1,
            HAS_BROKEN_SELECTIONS,
        ),
        # cardinality violation → HAS_BROKEN_SELECTIONS.
        (
            _structure(_slot("s", [TemplateOption("A"), TemplateOption("B")])),
            _sel(("s", ["A", "B"])),
            V1,
            HAS_BROKEN_SELECTIONS,
        ),
        # no available options → HAS_BROKEN_SELECTIONS.
        (_structure(_slot("s", [])), _sel(), V1, HAS_BROKEN_SELECTIONS),
        # unsupported policy → HAS_BROKEN_SELECTIONS.
        (
            _structure(_slot("s", [TemplateOption("A")])),
            _sel(("s", ["A"])),
            BAD_CONTRACT,
            HAS_BROKEN_SELECTIONS,
        ),
        # 전부 resolved → SLOT_SELECTIONS_COMPLETE.
        (
            _structure(_slot("s", [TemplateOption("A")])),
            _sel(("s", ["A"])),
            V1,
            SLOT_SELECTIONS_COMPLETE,
        ),
    ],
)
def test_configuration_status_mapping(structure, selections, contract, expected) -> None:
    view = _project(structure, selections, contract)
    assert view.view_status == CURRENT
    assert view.configuration_status == expected


def test_missing_and_broken_distinct_when_both_present() -> None:
    # missing + cardinality 동시 → broken 이 우선해 HAS_BROKEN_SELECTIONS.
    structure = _structure(
        _slot("m", [TemplateOption("A")]),
        _slot("c", [TemplateOption("A"), TemplateOption("B")]),
    )
    view = _project(structure, _sel(("c", ["A", "B"])))
    assert view.configuration_status == HAS_BROKEN_SELECTIONS
    assert view.summary is not None
    assert view.summary.missing_selection_count == 1
    assert view.summary.broken_selection_count == 1
    assert set(view.summary.blocking_kinds) == {
        "MISSING_REQUIRED_SELECTION",
        "CARDINALITY_VIOLATION",
    }


# ── view_status: CURRENT vs CONTEXT_ERROR ─────────────────────────────────────
def test_context_error_has_no_normal_projection() -> None:
    view = project_context_error("STALE_TEMPLATE_APPLICATION", "요청 Application A1 ...")
    assert view.view_status == CONTEXT_ERROR
    assert view.context_error == "STALE_TEMPLATE_APPLICATION"  # stable code, not message
    assert view.context_error_detail == "요청 Application A1 ..."
    assert view.summary is None
    assert view.slots == () and view.detached_selections == ()
    assert view.configuration_present is False and view.configuration_version is None
    assert view.configuration_status == NOT_APPLICABLE  # partial fallback 없음


def test_configuration_presence_distinguishes_absence_from_tombstone() -> None:
    # F1: 빈 selections 는 부재·explicit-empty tombstone 둘 다 만들지만 두 view 는 구별돼야 한다.
    structure = _structure(_slot("s", [TemplateOption("A")]))
    resolution = resolve_slot_configuration(_sel(), structure, V1)

    absent = project_current_slot_configuration(_ctx(structure), None, resolution)
    assert absent.configuration_present is False and absent.configuration_version is None

    tombstone = create_empty("w1", "A1", "2026-08-16T00:00:00Z")
    present = project_current_slot_configuration(_ctx(structure), tombstone, resolution)
    assert present.configuration_present is True
    assert present.configuration_version == tombstone.version


# ── mutation-outcome vs current-view 분리 ─────────────────────────────────────
def test_fresh_projection_carries_no_request_stale_axis() -> None:
    # current view 는 request stale 관계를 담지 않는다 — 별도 mutation outcome 축이 진다.
    view = _project(_structure(_slot("s", [TemplateOption("A")])), _sel(("s", ["A"])))
    assert view.view_status == CURRENT
    assert not hasattr(view, "request_relation")
    assert not hasattr(view, "stale")


# ── slots / options projection ────────────────────────────────────────────────
def test_slot_option_projection_selected_effective_and_fields() -> None:
    structure = _structure(
        _slot(
            "s1",
            [
                TemplateOption("o1", fields=("f1", "f2"), label="기본 표지"),
                TemplateOption("o2", fields=("f3",)),
            ],
            shared=("sh1",),
            label="표지 유형",
        )
    )
    view = _project(structure, _sel(("s1", ["o1"])))
    (slot,) = view.slots
    assert slot.slot_id == "s1" and slot.display_text == "표지 유형"
    assert slot.shared_field_ids == ("sh1",)
    assert slot.declared_option_ids == ("o1",)
    assert slot.effective_option_ids == ("o1",)
    o1, o2 = slot.options
    assert o1.option_id == "o1" and o1.display_text == "기본 표지"
    assert o1.selected is True and o1.effective is True
    assert o1.structurally_associated_field_ids == ("f1", "f2")
    assert o2.selected is False and o2.effective is False
    assert o2.option_id == "o2" and o2.display_text == "라벨 미지정 (ID: o2)"


def test_slots_follow_template_order() -> None:
    structure = _structure(
        _slot("b", [TemplateOption("A")]),
        _slot("a", [TemplateOption("A")]),
    )
    view = _project(structure, _sel())
    assert [(s.slot_id, s.display_text) for s in view.slots] == [
        ("b", "라벨 미지정 (ID: b)"),
        ("a", "라벨 미지정 (ID: a)"),
    ]


def test_declared_effective_separation_on_removed_option() -> None:
    # 선택했지만 available 밖 → declared 는 남고 effective 는 빈다.
    view = _project(_structure(_slot("s", [TemplateOption("A")])), _sel(("s", ["Z"])))
    (slot,) = view.slots
    assert slot.declared_option_ids == ("Z",)
    assert slot.effective_option_ids == ()
    assert any(d.kind == "SELECTED_OPTION_REMOVED" for d in slot.diagnostics)


# ── detached projection ───────────────────────────────────────────────────────
def test_detached_selection_informational_and_clearable() -> None:
    # slot Z 가 structure 에 없다 → detached, clearable, SLOT_REMOVED.
    structure = _structure(_slot("s", [TemplateOption("A")]))
    view = _project(structure, _sel(("s", ["A"]), ("Z", ["C"])))
    (detached,) = view.detached_selections
    assert detached.slot_id == "Z"
    assert detached.selected_option_ids == ("C",)
    assert detached.clearable is True
    assert detached.status == SLOT_REMOVED
    # informational index 에도 실린다.
    assert any(c.slot_id == "Z" and c.kind == SLOT_REMOVED for c in view.informational_changes)


def test_zero_slots_still_shows_detached_selection() -> None:
    # slot 0개인데 retained detached 가 있으면 표시(NOT_APPLICABLE 이어도).
    view = _project(_structure(), _sel(("Z", ["C"])))
    assert view.configuration_status == NOT_APPLICABLE
    assert len(view.detached_selections) == 1
    assert view.summary is not None and view.summary.detached_selection_count == 1


# ── summary counts / blocking_items ───────────────────────────────────────────
def test_summary_and_blocking_items() -> None:
    structure = _structure(
        _slot("m", [TemplateOption("A")]),
        _slot("s", [TemplateOption("A")]),
    )
    view = _project(structure, _sel(("s", ["A"]), ("Z", ["C"])))
    assert view.summary is not None
    assert view.summary.missing_selection_count == 1  # m
    assert view.summary.detached_selection_count == 1  # Z
    assert view.summary.slot_selections_complete is False
    assert any(b.slot_id == "m" for b in view.blocking_items)


def test_blocking_index_carries_secondary_diagnostic_option_id() -> None:
    # F4: primary CARDINALITY_VIOLATION + secondary SELECTED_OPTION_REMOVED(Z) — 둘 다 실리고
    # 사라진 선택 option_id 를 잃지 않는다.
    structure = _structure(_slot("s", [TemplateOption("A"), TemplateOption("B")]))
    view = _project(structure, _sel(("s", ["A", "Z"])))  # 2 declared(cardinality), Z 는 제거됨
    kinds = {(b.kind, b.option_id) for b in view.blocking_items if b.slot_id == "s"}
    assert ("CARDINALITY_VIOLATION", None) in kinds  # primary
    assert ("SELECTED_OPTION_REMOVED", "Z") in kinds  # secondary, option_id 보존


# ── reconciliation delta: source-relative 만, immediate transition 아님 ──────────
def test_reconciliation_changes_present_only_with_delta() -> None:
    structure = _structure(_slot("s", [TemplateOption("A")]))
    assert _project(structure, _sel(("s", ["A"]))).reconciliation_changes is None

    source = _structure(_slot("old", [TemplateOption("X")]))
    delta = derive_reconciliation_source_delta(
        "A0", 2, _sel(("old", ["X"])), source, "A1", structure
    )
    view = _project(structure, _sel(("s", ["A"])), source_delta=delta)
    rc = view.reconciliation_changes
    assert rc is not None
    assert rc.source_application_id == "A0" and rc.source_configuration_version == 2
    assert rc.added_slot_ids == ("s",) and rc.removed_slot_ids == ("old",)
    # source-relative refs 만 — "이번 변경" immediate transition 필드는 없다.
    assert not hasattr(rc, "immediate") and not hasattr(rc, "applied_now")


def test_reconciliation_changes_surface_reorder_only_delta() -> None:
    # F3: option/slot 순서만 바뀐 delta 는 added/removed 가 비어도 reorder 로 표면화돼야 한다.
    source = _structure(
        _slot("s", [TemplateOption("A"), TemplateOption("B")]),
        _slot("t", [TemplateOption("A")]),
    )
    target = _structure(
        _slot("t", [TemplateOption("A")]),
        _slot("s", [TemplateOption("B"), TemplateOption("A")]),  # option 순서 뒤집힘
    )
    delta = derive_reconciliation_source_delta(
        "A0", 1, _sel(("s", ["A"])), source, "A1", target
    )
    rc = _project(target, _sel(("s", ["B"])), source_delta=delta).reconciliation_changes
    assert rc is not None
    assert rc.added_slot_ids == () and rc.removed_slot_ids == ()  # 추가·제거 없음
    assert rc.slot_order_changed is True
    assert rc.option_order_changes == ("s",)


# ── JSON-safety ───────────────────────────────────────────────────────────────
def test_dto_serializes_to_primitives() -> None:
    structure = _structure(
        _slot("s", [TemplateOption("A", fields=("f1",))], shared=("sh1",))
    )
    delta = derive_reconciliation_source_delta(
        "A0", 1, _sel(("s", ["A"])), structure, "A1", structure
    )
    view = _project(structure, _sel(("s", ["A"]), ("Z", ["C"])), source_delta=delta)
    # asdict → dict/list/str/int/bool 만; json.dumps 가 통과하면 primitive 로만 구성됨.
    payload = json.dumps(dataclasses.asdict(view))
    assert json.loads(payload)["view_status"] == CURRENT
    # context error variant 도 JSON-safe.
    json.dumps(dataclasses.asdict(project_context_error("BOOM")))


# ── #777: 이전 선택의 운명을 라벨과 함께 shape 한다(판정은 resolver 가 이미 했다) ──────────
def test_retained_selections_separate_the_three_fates_and_name_what_survives() -> None:
    """셋은 서로 다른 ``fate`` 로 나온다 — 뭉치면 화면이 다시 구별을 잃는다(#728 H4).

    라벨은 **현재 구조에 있는 것만** 채운다. 사라진 Slot/Option 의 이름은 현재 구조 어디에도
    없고, 그 자리에 내부 ID 를 꽂으면 사용자에게 아무것도 알려 주지 못한 채 H1 만 깬다.
    """
    current = _structure(
        _slot("s-keep", [TemplateOption("o-keep", label="추정가격 표시")], label="공고 상세"),
        _slot("s-broken", [TemplateOption("o-other", label="다른 것")], label="표지"),
    )
    previous = _sel(("s-keep", ["o-keep"]), ("s-broken", ["o-gone"]), ("s-gone", ["o-x"]))

    view = project_current_slot_configuration(
        _ctx(current),
        None,
        resolve_slot_configuration(_sel(), current, V1),
        retained=resolve_slot_configuration(previous, current, V1),
    )
    fates = {r.slot_id: r for r in view.retained_selections}

    assert set(fates) == {"s-keep", "s-broken", "s-gone"}
    assert fates["s-keep"].fate == "RESOLVED"
    assert fates["s-broken"].fate == "SELECTED_OPTION_REMOVED"
    assert fates["s-gone"].fate == SLOT_REMOVED
    assert len({r.fate for r in view.retained_selections}) == 3  # 한 값으로 뭉치지 않았다

    assert fates["s-keep"].slot_display_text == "공고 상세"
    assert fates["s-broken"].slot_display_text == "표지"  # slot 은 남아 이름을 댈 수 있다
    assert fates["s-gone"].slot_display_text is None
    # 이전에 고른 Option 의 **이름**은 어디에도 싣지 않는다 — 남은 것은 같은 ID 뿐이고 그 ID 의
    # 현재 라벨은 이전 라벨이 아니다(같은 ID 재사용 시 없는 역사를 지어내게 된다).
    assert not any(hasattr(r, "option_display_texts") for r in view.retained_selections)

    # 현재 구성은 그대로다 — 이전 이야기가 지금 골라진 것을 만들지 않는다(false AUTO_KEEP 금지).
    assert all(slot.effective_option_ids == () for slot in view.slots)


def test_retained_selections_are_absent_when_there_is_no_previous_story() -> None:
    """이전 Configuration 이 없으면 할 말이 없다 — 빈 목록이지 추측이 아니다."""
    structure = _structure(_slot("s", [TemplateOption("A")]))
    assert _project(structure, _sel()).retained_selections == ()
    assert project_context_error("STALE_TEMPLATE_APPLICATION").retained_selections == ()


def test_retained_selections_skip_slots_the_user_never_answered() -> None:
    """이전에 고르지 않은 Slot 은 운명이랄 게 없다 — 말하지 않는다."""
    structure = _structure(
        _slot("s1", [TemplateOption("A")]), _slot("s2", [TemplateOption("B")])
    )
    view = project_current_slot_configuration(
        _ctx(structure),
        None,
        resolve_slot_configuration(_sel(), structure, V1),
        retained=resolve_slot_configuration(_sel(("s1", ["A"])), structure, V1),
    )
    assert [r.slot_id for r in view.retained_selections] == ["s1"]


def test_retained_selections_stay_json_safe() -> None:
    """프런트로 나가는 값이라 asdict → json 이 그대로 돌아야 한다."""
    structure = _structure(_slot("s", [TemplateOption("A", label="가")], label="ㄱ"))
    view = project_current_slot_configuration(
        _ctx(structure),
        None,
        resolve_slot_configuration(_sel(), structure, V1),
        retained=resolve_slot_configuration(_sel(("s", ["A"]), ("z", ["Q"])), structure, V1),
    )
    payload = json.loads(json.dumps(dataclasses.asdict(view), ensure_ascii=False))
    assert [r["fate"] for r in payload["retained_selections"]] == ["RESOLVED", SLOT_REMOVED]
