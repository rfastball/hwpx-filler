"""Preset 동사의 pure 판정과 runner 결선 헤드리스 테스트(S9-02 · #828).

적용은 제안이다: 판정은 전부 S4 reconciliation 이 지고, 깨진 선택은 조용히 버려지지 않고
detached 어휘로 함께 나온다. Preset 이 언급하지 않은 Slot 의 기존 선택은 소거되지 않으며,
조용한 덮기 경로(이름 충돌·확인 근거 불일치)는 전부 확인 왕복으로 되돌아온다.

하네스(구조·포트·context·store)는 :mod:`tests.test_slot_command` 의 것을 그대로 쓴다 —
같은 seam 을 두 번 지어 두 판정이 갈라지는 것을 막는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_slot_command import (  # 같은 rootdir 의 공용 하네스
    NOW,
    _clear,
    _ctx,
    _ports,
    _select,
    _store,
)

from hwpxfiller.application.preset_command import (
    DELETED,
    NEEDS_CONFIRM,
    PRESET_EMPTY_SELECTION,
    PRESET_ENTRY_CORRUPT,
    PRESET_NAME_CONFLICT,
    PRESET_NOT_FOUND,
    REJECTED,
    SAVED,
    PresetApplyDecision,
    PresetDeleteResult,
    PresetSaveRejected,
    PresetSaveResult,
    decide_apply_preset,
    delete_selection_preset,
    fit_preset_selections,
    list_selection_presets,
    plan_preset_save,
    preset_list_actionable,
)
from hwpxfiller.application.slot_command import (
    CHANGED,
    NO_CHANGE,
    STALE_CONFIGURATION,
    STALE_TEMPLATE_APPLICATION,
    ConfigurationContextClaimMismatch,
    CrossWorkConfigurationToken,
)
from hwpxfiller.application.slot_configuration_projection import (
    SLOT_SELECTIONS_COMPLETE,
)
from hwpxfiller.application.slot_reconciliation import (
    SELECTED_OPTION_REMOVED,
    SLOT_REMOVED,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_slot_configuration import (
    apply_selections,
    create_empty,
    has_declared_selection,
)
from hwpxfiller.domain.preset import SelectionPreset
from hwpxfiller.domain.slot_selection import (
    CARDINALITY_VIOLATION,
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    NO_AVAILABLE_OPTIONS,
    SlotSelection,
    SlotSelectionSet,
)
from hwpxfiller.external.preset_store import PresetRegistry
from hwpxfiller.external.slot_command_runner import (
    apply_selection_preset,
    save_selection_preset,
)

CONTRACT_MANIFEST = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get("slot-selection/v1")

# s1·s2 는 고를 것이 있고, s3 는 Option 이 없다(NO_AVAILABLE_OPTIONS 대조).
_TWO = TemplateStructure(
    root_fields=(),
    slots=(
        TemplateSlot(id="s1", options=(TemplateOption("o1"), TemplateOption("o2"))),
        TemplateSlot(id="s2", options=(TemplateOption("x1"), TemplateOption("x2"))),
    ),
)
_THREE = TemplateStructure(
    root_fields=(),
    slots=_TWO.slots + (TemplateSlot(id="s3", options=()),),
)


def _pure_ctx(structure: TemplateStructure = _THREE) -> object:
    """``decide_apply_preset`` 이 읽는 두 필드만 담은 최소 context."""
    return SimpleNamespace(
        template_structure=structure, selection_semantic_contract=CONTRACT_MANIFEST
    )


def _sel(*pairs: "tuple[str, tuple[str, ...]]") -> SlotSelectionSet:
    return SlotSelectionSet(
        tuple(SlotSelection(slot_id, options) for slot_id, options in pairs)
    )


def _config(*pairs: "tuple[str, tuple[str, ...]]"):
    base = create_empty("w1", "A1", NOW)
    if not pairs:
        return base
    return apply_selections(base, _sel(*pairs), NOW)


def _declared(config) -> dict[str, tuple[str, ...]]:
    return {e.slot_id: e.selected_option_ids for e in config.selections.selections}


def _registry(tmp_path: Path) -> PresetRegistry:
    return PresetRegistry(tmp_path / "presets")


def _preset(name: str = "표준", selections: SlotSelectionSet | None = None) -> SelectionPreset:
    return SelectionPreset(
        name=name,
        selection_set=selections if selections is not None else _sel(("s1", ("o1",))),
        provenance={},
        created_at=NOW,
    )


# ── pure: 적용 판정 ────────────────────────────────────────────────────────────
def test_partial_match_reports_applied_and_broken_together() -> None:
    """유효 1건과 깨짐 2건이 **동시에** 나온다 — 깨진 것은 조용히 사라지지 않는다."""
    decision = decide_apply_preset(
        _pure_ctx(),
        _config(),
        _sel(("s1", ("o1",)), ("s2", ("사라진옵션",)), ("s9", ("z",))),
        NOW,
    )
    assert decision.applied_slot_ids == ("s1",) and decision.applied_count == 1
    assert decision.broken_count == 2
    assert [(b.slot_id, b.status) for b in decision.broken] == [
        ("s2", SELECTED_OPTION_REMOVED),
        ("s9", SLOT_REMOVED),
    ]
    assert all(not b.clearable for b in decision.broken)


def test_unmentioned_slot_selection_is_preserved() -> None:
    """음성 대조: Preset 이 언급하지 않은 Slot 의 기존 선택을 조용히 소거하지 않는다."""
    decision = decide_apply_preset(
        _pure_ctx(), _config(("s2", ("x1",))), _sel(("s1", ("o1",))), NOW
    )
    assert decision.outcome_code == CHANGED
    assert decision.new_config is not None
    assert _declared(decision.new_config) == {"s2": ("x1",), "s1": ("o1",)}


def test_reapplying_same_selection_is_idempotent() -> None:
    decision = decide_apply_preset(
        _pure_ctx(), _config(("s1", ("o1",))), _sel(("s1", ("o1",))), NOW
    )
    assert decision.outcome_code == NO_CHANGE and not decision.changed
    assert decision.new_config is None
    assert decision.source_version == decision.resulting_version


def test_broken_entries_never_reach_the_declared_set() -> None:
    decision = decide_apply_preset(
        _pure_ctx(), _config(), _sel(("s1", ("o1",)), ("s9", ("z",))), NOW
    )
    assert decision.new_config is not None
    assert _declared(decision.new_config) == {"s1": ("o1",)}  # s9 는 보고로만 남는다


def test_cardinality_and_no_options_are_broken_not_applied() -> None:
    decision = decide_apply_preset(
        _pure_ctx(), _config(), _sel(("s1", ("o1", "o2")), ("s3", ("무엇이든",))), NOW
    )
    assert decision.applied_slot_ids == ()
    assert [(b.slot_id, b.status) for b in decision.broken] == [
        ("s1", CARDINALITY_VIOLATION),
        ("s3", NO_AVAILABLE_OPTIONS),
    ]
    assert decision.outcome_code == NO_CHANGE


# ── pure: 구조 호환 판정(#875) ─────────────────────────────────────────────────
# 목록 필터와 적용은 **같은 해석**을 쓴다. 아래 대조는 `fully_applicable` 이 무엇을 뜻하는지와,
# 적용 경로의 수치가 그 같은 값에서 나오는지를 함께 잰다(두 곳 판정 금지).


@pytest.mark.parametrize(
    "proposal",
    [
        _sel(("s1", ("o1",))),  # 구조 일부만 언급 — 언급한 것은 전부 RESOLVED
        _sel(("s1", ("o1",)), ("s2", ("x2",))),  # 고를 수 있는 것 전부
    ],
)
def test_fit_is_fully_applicable_when_every_declared_entry_resolves(proposal) -> None:
    """양성: 언급한 slot·option 이 전부 현재 구조에서 RESOLVED 면 호환이다.

    구조에는 있으나 Preset 이 언급하지 않은 Slot(s2·s3)은 판정 대상이 아니다 — 적용도 소거도
    하지 않으므로 「전부 적용 가능」을 깨지 않는다.
    """
    fit = fit_preset_selections(_pure_ctx(), proposal)
    assert fit.fully_applicable is True
    assert fit.broken == ()
    assert len(fit.applied) == fit.declared_slot_count == len(proposal.selections)


@pytest.mark.parametrize(
    ("proposal", "broken_slot"),
    [
        (_sel(("s9", ("z",))), "s9"),  # 모르는 slot
        (_sel(("s1", ("사라진옵션",))), "s1"),  # 모르는 option
    ],
)
def test_fit_is_not_applicable_for_unknown_slot_or_option(proposal, broken_slot) -> None:
    """음성: 현재 구조가 모르는 slot·option 이 하나라도 있으면 호환이 아니다."""
    fit = fit_preset_selections(_pure_ctx(), proposal)
    assert fit.fully_applicable is False
    assert [b.slot_id for b in fit.broken] == [broken_slot]


def test_partial_overlap_is_not_compatible_even_though_something_applies() -> None:
    """경계: 일부만 서면 호환이 아니다 — 목록의 줄은 「고르면 그대로 서는 것」을 뜻해야 한다."""
    proposal = _sel(("s1", ("o1",)), ("s9", ("z",)))
    fit = fit_preset_selections(_pure_ctx(), proposal)
    assert len(fit.applied) == 1 and len(fit.broken) == 1  # 실제로 무언가는 선다
    assert fit.fully_applicable is False


def test_apply_numbers_come_from_the_same_fit_the_list_filter_uses() -> None:
    """단일 출처: 적용 수치가 목록 필터가 묻는 그 값에서 나온다(구조를 두 번 훑지 않는다)."""
    proposal = _sel(("s1", ("o1",)), ("s2", ("사라진옵션",)), ("s9", ("z",)))
    fit = fit_preset_selections(_pure_ctx(), proposal)
    decision = decide_apply_preset(_pure_ctx(), _config(), proposal, NOW)
    assert decision.applied_slot_ids == tuple(e.slot_id for e in fit.applied)
    assert decision.broken == fit.broken
    assert fit.fully_applicable is False  # 그래서 이 Preset 은 목록에도 안 실린다


# ── pure: 저장 판정 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("config", [None, _config()])
def test_empty_selection_save_is_rejected(config) -> None:
    with pytest.raises(PresetSaveRejected) as exc:
        plan_preset_save(config, "표준", {}, NOW)
    assert exc.value.code == PRESET_EMPTY_SELECTION


def test_save_keeps_declared_selection_as_is() -> None:
    """저장은 선택 값의 보관 — complete 여부를 판정하지 않는다(s2 미선택이어도 저장된다)."""
    preset = plan_preset_save(
        _config(("s1", ("o1",))), "표준", {"template_application_id": "A1"}, NOW
    )
    assert preset.selection_set == _sel(("s1", ("o1",)))
    assert preset.provenance_map == {"template_application_id": "A1"}


# ── runner: 저장 ──────────────────────────────────────────────────────────────
def _save(store, ports, reg, ctx, *, name="표준", confirmed=None):
    return save_selection_preset(
        store, *ports, reg, context=ctx, name=name,
        confirmed_overwrite_key=confirmed, now=NOW,
    )


def test_save_captures_current_selection_with_provenance(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())  # s1=o1
    result = _save(store, ports, reg, _ctx(presence=True, version=2))
    assert result.status == SAVED and result.code is None
    assert result.saved_key is not None
    saved = reg.load(result.saved_key)
    assert saved.selection_set == _sel(("s1", ("o1",)))
    assert saved.provenance_map["template_application_id"] == "A1"
    assert saved.provenance_map["selection_contract_id"] == "slot-selection/v1"


def test_save_name_conflict_needs_confirm_and_writes_nothing(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())
    first = _save(store, ports, reg, _ctx(presence=True, version=2))
    before = sorted(p.name for p in reg.directory.iterdir())
    again = _save(store, ports, reg, _ctx(presence=True, version=2))
    assert again.status == NEEDS_CONFIRM and again.code == PRESET_NAME_CONFLICT
    assert again.existing_key == first.saved_key
    assert again.existing_created_at == NOW and again.detail
    assert sorted(p.name for p in reg.directory.iterdir()) == before  # 쓰기 0


def test_confirmed_overwrite_replaces_same_slot(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())
    first = _save(store, ports, reg, _ctx(presence=True, version=2))
    _select(store, ports, _ctx(presence=True, version=2), req="r2", option="o2")
    result = _save(
        store, ports, reg, _ctx(presence=True, version=3), confirmed=first.saved_key
    )
    assert result.status == SAVED and result.saved_key == first.saved_key
    assert reg.load(first.saved_key).selection_set == _sel(("s1", ("o2",)))
    assert len(reg.list_entries()) == 1


def test_confirmed_overwrite_against_stale_basis_needs_confirm(tmp_path: Path) -> None:
    """확인 사이 그 이름이 **다른 슬롯**으로 옮겨 갔으면 덮지 않고 다시 묻는다."""
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())
    first = _save(store, ports, reg, _ctx(presence=True, version=2))
    assert first.saved_key is not None
    reg.delete(first.saved_key)
    other = reg.add(_preset("표준", _sel(("s1", ("o2",)))))
    result = _save(
        store, ports, reg, _ctx(presence=True, version=2), confirmed=first.saved_key
    )
    assert result.status == NEEDS_CONFIRM and result.existing_key == other
    assert reg.load(other).selection_set == _sel(("s1", ("o2",)))  # 무변경


def test_confirmed_overwrite_of_vanished_target_lands_as_new_save(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())
    first = _save(store, ports, reg, _ctx(presence=True, version=2))
    assert first.saved_key is not None
    reg.delete(first.saved_key)
    result = _save(
        store, ports, reg, _ctx(presence=True, version=2), confirmed=first.saved_key
    )
    assert result.status == SAVED and result.saved_key != first.saved_key
    assert reg.load(result.saved_key).name == "표준"


def test_save_without_any_selection_is_rejected(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    result = _save(store, ports, reg, _ctx())  # Configuration 자체가 없다
    assert result.status == REJECTED and result.code == PRESET_EMPTY_SELECTION
    assert reg.list_presets() == ([], [])


# ── runner: 적용 ──────────────────────────────────────────────────────────────
def _apply(store, ports, reg, ctx, key):
    return apply_selection_preset(
        store, *ports, reg, context=ctx, preset_key=key, now=NOW
    )


def test_apply_restores_selection_end_to_end(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())  # s1=o1, config v2
    saved = _save(store, ports, reg, _ctx(presence=True, version=2))
    _clear(store, ports, _ctx(presence=True, version=2), req="r2", slot="s1")  # v3
    result = _apply(store, ports, reg, _ctx(presence=True, version=3), saved.saved_key)
    assert result.outcome is not None
    assert result.outcome.outcome_code == CHANGED
    assert result.outcome.resulting_configuration_version == 4
    assert result.applied_slot_ids == ("s1",) and result.broken_count == 0
    assert result.view is not None and result.view_error is None
    assert result.view.configuration_status == SLOT_SELECTIONS_COMPLETE


def test_apply_partial_match_restates_broken_entries(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(structure=_TWO), _registry(tmp_path)
    key = reg.add(
        _preset(
            "혼합",
            _sel(("s1", ("o1",)), ("s2", ("사라짐",)), ("s9", ("z",))),
        )
    )
    result = _apply(store, ports, reg, _ctx(), key)
    assert result.outcome is not None and result.outcome.outcome_code == CHANGED
    assert result.applied_count == 1 and result.broken_count == 2
    assert [(b.slot_id, b.status) for b in result.broken] == [
        ("s2", SELECTED_OPTION_REMOVED),
        ("s9", SLOT_REMOVED),
    ]
    stored = store.load("w1").configurations.configurations[0]
    assert _declared(stored) == {"s1": ("o1",)}


def test_apply_with_stale_configuration_version_stores_nothing(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    _select(store, ports, _ctx())  # config v2
    key = reg.add(_preset("표준", _sel(("s1", ("o2",)))))
    before = store.load("w1")
    result = _apply(store, ports, reg, _ctx(presence=True, version=1), key)
    assert result.outcome is not None
    assert result.outcome.outcome_code == STALE_CONFIGURATION
    assert not result.outcome.changed and result.applied_count == 0
    assert store.load("w1") == before  # 무저장


def test_apply_missing_preset_is_not_found(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    result = _apply(store, ports, reg, _ctx(), "a" * 16)
    assert result.rejection_code == PRESET_NOT_FOUND and result.rejection_detail
    assert result.outcome is None and result.view is None


def test_apply_corrupt_preset_states_the_reason(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    reg.directory.mkdir(parents=True, exist_ok=True)
    reg.slot_path("b" * 16).write_text("{ 깨진 JSON", encoding="utf-8")
    result = _apply(store, ports, reg, _ctx(), "b" * 16)
    assert result.rejection_code == PRESET_ENTRY_CORRUPT and result.rejection_detail
    assert result.outcome is None


def test_apply_invalid_key_is_not_found(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    result = _apply(store, ports, reg, _ctx(), "../탈출")
    assert result.rejection_code == PRESET_NOT_FOUND and result.rejection_detail


def test_apply_on_stale_template_application_stores_nothing(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(current="A2"), _registry(tmp_path)
    key = reg.add(_preset())
    result = _apply(store, ports, reg, _ctx(app="A1"), key)  # token 은 옛 A1
    assert result.outcome is not None
    assert result.outcome.outcome_code == STALE_TEMPLATE_APPLICATION
    assert result.applied_count == 0 and not store.exists("w1")
    assert result.view is None and result.view_error is not None


def test_apply_contract_claim_mismatch_raises_without_storage(tmp_path: Path) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    key = reg.add(_preset())
    with pytest.raises(ConfigurationContextClaimMismatch):
        _apply(store, ports, reg, _ctx(contract="slot-selection/v9"), key)
    assert not store.exists("w1")


@pytest.mark.parametrize("verb", ["save", "apply"])
def test_cross_work_token_raised_before_any_work(tmp_path: Path, verb: str) -> None:
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    key = reg.add(_preset())
    ctx = _ctx(work="w1", token_work="other")
    with pytest.raises(CrossWorkConfigurationToken):
        if verb == "save":
            _save(store, ports, reg, ctx)
        else:
            _apply(store, ports, reg, ctx, key)
    assert not store.exists("w1")


def test_apply_of_all_broken_preset_still_materializes_planned_config(tmp_path: Path) -> None:
    """적용할 것이 하나도 없어도 새로 plan 된 Configuration 은 남는다(select 동형)."""
    store, ports, reg = _store(tmp_path), _ports(), _registry(tmp_path)
    key = reg.add(_preset("사라진묶음", _sel(("s9", ("z",)))))
    result = _apply(store, ports, reg, _ctx(), key)
    assert result.outcome is not None and result.outcome.outcome_code == NO_CHANGE
    assert result.applied_count == 0 and result.broken_count == 1
    assert len(store.load("w1").configurations.configurations) == 1


def test_apply_under_slotless_barrier_materializes_nothing(tmp_path: Path) -> None:
    """Slot 0개 구조에서는 판정만 하고 Configuration 을 만들지 않는다(부재≠tombstone)."""
    store = _store(tmp_path)
    ports = _ports(structure=TemplateStructure(root_fields=(), slots=()))
    reg = _registry(tmp_path)
    key = reg.add(_preset())
    result = _apply(store, ports, reg, _ctx(), key)
    assert result.outcome is not None and result.outcome.outcome_code == NO_CHANGE
    assert result.broken_count == 1  # s1 은 detached 로 보고된다
    assert not store.exists("w1")


class _RacingRegistry:
    """스캔↔잠금 사이에 같은 이름이 끼어든 레지스트리 — ``add`` 백스톱 경로 재현."""

    def __init__(self, inner: PresetRegistry) -> None:
        self._inner = inner
        self._scanned = False

    def find_name(self, name: str):
        if not self._scanned:  # 1차 스캔에서는 비어 있다고 답한다
            self._scanned = True
            return None
        return self._inner.find_name(name)

    def add(self, preset: SelectionPreset) -> str:
        return self._inner.add(preset)


def test_save_add_backstop_folds_into_confirmation(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    inner = _registry(tmp_path)
    taken = inner.add(_preset("표준"))
    _select(store, ports, _ctx())
    result = _save(store, ports, _RacingRegistry(inner), _ctx(presence=True, version=2))
    assert result.status == NEEDS_CONFIRM and result.code == PRESET_NAME_CONFLICT
    assert result.existing_key == taken  # 지금 사실을 동봉해 다시 묻는다
    assert len(inner.list_entries()) == 1  # 조용한 덮기 0


# ── 결과 값 불변식 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": SAVED, "code": PRESET_NAME_CONFLICT, "saved_key": "k"},
        {"status": SAVED, "code": None, "saved_key": None},
        {"status": NEEDS_CONFIRM, "code": None, "saved_key": None},
        {"status": NEEDS_CONFIRM, "code": PRESET_NAME_CONFLICT, "saved_key": "k"},
        {"status": REJECTED, "code": None, "saved_key": None},
        {"status": REJECTED, "code": PRESET_EMPTY_SELECTION, "saved_key": "k"},
        {"status": "무엇", "code": None, "saved_key": None},
    ],
)
def test_save_result_invariants_are_locked(kwargs) -> None:
    with pytest.raises(ValueError):
        PresetSaveResult(existing_key=None, existing_created_at=None, detail=None, **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": DELETED, "code": None, "name": None},
        {"status": DELETED, "code": PRESET_NOT_FOUND, "name": "표준"},
        {"status": REJECTED, "code": None, "name": None},
        {"status": REJECTED, "code": PRESET_NOT_FOUND, "name": "표준"},
        {"status": "무엇", "code": None, "name": None},
    ],
)
def test_delete_result_invariants_are_locked(kwargs) -> None:
    with pytest.raises(ValueError):
        PresetDeleteResult(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"outcome_code": "무엇", "changed": False, "new_config": None},
        {"outcome_code": CHANGED, "changed": False, "new_config": None},
        {"outcome_code": NO_CHANGE, "changed": False, "new_config": _config()},
    ],
)
def test_apply_decision_invariants_are_locked(kwargs) -> None:
    with pytest.raises(ValueError):
        PresetApplyDecision(
            source_version=1, resulting_version=1, applied_slot_ids=(), broken=(), **kwargs
        )


# ── 나열·삭제 ─────────────────────────────────────────────────────────────────
def test_listing_surfaces_corruption_beside_healthy_items(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.add(_preset("나중"))
    reg.add(_preset("가장먼저", _sel(("s2", ("x1",)))))
    reg.slot_path("c" * 16).write_text(json.dumps({"schema_version": "x"}), encoding="utf-8")
    listing = list_selection_presets(reg, _pure_ctx())
    assert [item.name for item in listing.items] == ["가장먼저", "나중"]
    assert listing.corrupt_count == 1 and listing.corrupt_code == PRESET_ENTRY_CORRUPT
    assert listing.corrupt[0].error
    assert listing.items[0].created_at == NOW and listing.items[0].provenance == {}


def test_listing_drops_items_the_current_structure_cannot_fully_apply(
    tmp_path: Path,
) -> None:
    """#875: 현재 구조에 전부 적용 가능한 것만 실린다 — 부분 겹침도 빠진다.

    저장 파일은 그대로다(삭제가 아니라 목록의 좁힘) — 구조가 맞는 작업에서 다시 뜬다.
    """
    reg = _registry(tmp_path)
    reg.add(_preset("여기맞음", _sel(("s1", ("o1",)))))
    reg.add(_preset("모르는슬롯", _sel(("s1", ("o1",)), ("s9", ("z",)))))
    reg.add(_preset("모르는옵션", _sel(("s2", ("사라진옵션",)))))

    listing = list_selection_presets(reg, _pure_ctx())
    assert [item.name for item in listing.items] == ["여기맞음"]
    # 걸러진 것은 파일로 남아 있다 — 다른 구조에서 다시 서야 한다.
    assert len(list(reg.directory.glob("*.preset.json"))) == 3


def test_listing_without_a_structure_claims_no_compatible_item_but_keeps_corruption(
    tmp_path: Path,
) -> None:
    """대조할 구조가 없으면 호환을 **주장할 수 있는** 항목이 0 이다(전량 노출 복귀 금지).

    손상 항목은 호환 판정의 대상이 아니라 표시 대상이라 그대로 남는다.
    """
    reg = _registry(tmp_path)
    reg.add(_preset("무엇이든", _sel(("s1", ("o1",)))))
    reg.slot_path("c" * 16).write_text(json.dumps({"schema_version": "x"}), encoding="utf-8")

    listing = list_selection_presets(reg, None)
    assert listing.items == ()
    assert listing.corrupt_count == 1 and listing.corrupt[0].error


# ── 「보관된 선택」 구획 노출 술어(U4 13번 · #932) ────────────────────────────────────────
def test_preset_list_stands_on_stored_or_corrupt_items(tmp_path: Path) -> None:
    """목록 구획은 **이미 보관된 것**을 묻는다 — 적용이라는 미이행 동사가 걸려 있을 때 선다."""
    reg = _registry(tmp_path)
    empty = list_selection_presets(reg, _pure_ctx())
    assert preset_list_actionable(empty) is False

    reg.add(_preset("표준", _sel(("s1", ("o1",)))))
    assert preset_list_actionable(list_selection_presets(reg, _pure_ctx())) is True

    reg2 = _registry(tmp_path / "other")
    reg2.directory.mkdir(parents=True, exist_ok=True)
    reg2.slot_path("c" * 16).write_text(json.dumps({"schema_version": "x"}), encoding="utf-8")
    corrupt_only = list_selection_presets(reg2, _pure_ctx())
    # 손상만 남아도 선다: 비활성 + 사유 병기가 이 구획의 몫이라 숨기면 사용자가 묻지 못한다.
    assert corrupt_only.items == () and corrupt_only.corrupt_count == 1
    assert preset_list_actionable(corrupt_only) is True


@pytest.mark.parametrize("savable", [False, True])
def test_two_predicates_cover_exactly_what_the_single_one_did(tmp_path: Path, savable) -> None:
    """13번의 3항 OR 과 14~17 의 두 술어는 **합집합에서 동치**다 — 구획이 갈렸을 뿐 잃은 갈래가 없다.

    옛 식을 여기 그대로 적어 두는 이유는, 그 식을 프로덕션에 남기면 그것이 곧 산출자 0 코드가
    되기 때문이다. 계약은 살리고 죽은 함수는 남기지 않는다.
    """
    reg = _registry(tmp_path)
    for listing in (list_selection_presets(reg, _pure_ctx()),):
        legacy = bool(listing.items) or bool(listing.corrupt) or savable
        assert (preset_list_actionable(listing) or savable) is legacy

    reg.add(_preset("표준", _sel(("s1", ("o1",)))))
    listed = list_selection_presets(reg, _pure_ctx())
    legacy = bool(listed.items) or bool(listed.corrupt) or savable
    assert (preset_list_actionable(listed) or savable) is legacy


@pytest.mark.parametrize(
    "config,savable",
    [(None, False), (_config(), False), (_config(("s1", ("o1",))), True)],
)
def test_zone_predicate_and_save_gate_never_disagree(config, savable) -> None:
    """보이는 저장 단추 = 이행되는 저장이다 — 두 술어가 같은 함수를 물어야 성립한다.

    갈리면 화면은 단추를 세우고 backend 는 그 저장을 ``PRESET_EMPTY_SELECTION`` 으로 거절하는
    자리가 생긴다(#912 가 이름 붙인 「이행되지 않는 동사」).
    """
    assert has_declared_selection(config) is savable
    if savable:
        assert plan_preset_save(config, "표준", {}, NOW).name == "표준"
    else:
        with pytest.raises(PresetSaveRejected) as exc:
            plan_preset_save(config, "표준", {}, NOW)
        assert exc.value.code == PRESET_EMPTY_SELECTION


# ── 적용 표지: 「지금 어떤 프리셋이 서 있는가」의 단일 출처(U4-G2 · #945 F3) ────────────────
# 종전에는 이 상태가 아무 데도 없어서 직전 왕복의 휘발 재진술이 그 자리를 대신 서 있었다.
# 여기가 재는 것은 진리표다 — 일치·불일치·프리셋 0·손상만·선택 0·비호환·다수 일치.


def test_applied_key_points_at_the_preset_that_is_currently_standing(
    tmp_path: Path,
) -> None:
    reg = _registry(tmp_path)
    key = reg.add(_preset("표준", _sel(("s1", ("o1",)))))
    reg.add(_preset("다른", _sel(("s2", ("x1",)))))

    standing = list_selection_presets(reg, _pure_ctx(), _config(("s1", ("o1",))))
    assert standing.applied_key == key
    # 같음의 정의는 domain 의 `semantic_selection_equal` 하나다 — 저장 순서가 달라도 같다.


def test_applied_key_falls_when_the_selection_is_changed_by_hand(tmp_path: Path) -> None:
    """수동 변경으로 일치가 깨지면 표지도 내려간다 — 표지는 사건이 아니라 상태다."""
    reg = _registry(tmp_path)
    reg.add(_preset("표준", _sel(("s1", ("o1",)))))
    assert list_selection_presets(reg, _pure_ctx(), _config(("s1", ("o2",)))).applied_key is None
    # 프리셋이 언급하지 않은 Slot 을 더 골라도 「곧 그 프리셋」은 더 이상 참이 아니다.
    widened = _config(("s1", ("o1",)), ("s2", ("x1",)))
    assert list_selection_presets(reg, _pure_ctx(), widened).applied_key is None


@pytest.mark.parametrize("config", [None, _config()])
def test_applied_key_is_none_on_an_empty_selection(tmp_path: Path, config) -> None:
    """선택 0건 위에는 어떤 프리셋도 서 있지 않다(저장조차 거절되는 상태다)."""
    reg = _registry(tmp_path)
    reg.add(_preset("표준", _sel(("s1", ("o1",)))))
    assert list_selection_presets(reg, _pure_ctx(), config).applied_key is None


def test_applied_key_is_none_without_items_or_with_corruption_only(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    empty = list_selection_presets(reg, _pure_ctx(), _config(("s1", ("o1",))))
    assert empty.items == () and empty.applied_key is None

    reg.directory.mkdir(parents=True, exist_ok=True)
    reg.slot_path("c" * 16).write_text(json.dumps({"schema_version": "x"}), encoding="utf-8")
    corrupt_only = list_selection_presets(reg, _pure_ctx(), _config(("s1", ("o1",))))
    # 읽을 수 없는 항목은 무엇과도 일치를 주장할 수 없다 — 그래도 목록에는 남는다.
    assert corrupt_only.corrupt_count == 1 and corrupt_only.applied_key is None


def test_applied_key_only_considers_items_the_structure_can_fully_apply(
    tmp_path: Path,
) -> None:
    """목록에서 걸러진 항목은 표지 후보가 아니다 — 안 보이는 줄에 표지를 켤 수 없다."""
    reg = _registry(tmp_path)
    reg.add(_preset("모르는옵션", _sel(("s2", ("사라진옵션",)))))
    listing = list_selection_presets(reg, _pure_ctx(), _config(("s2", ("사라진옵션",))))
    assert listing.items == () and listing.applied_key is None


def test_duplicate_content_marks_the_first_listed_item_only(tmp_path: Path) -> None:
    """같은 내용이 두 이름으로 보관돼 있으면 **목록 순서의 첫 항목**이 표지를 든다.

    어느 쪽을 지목해도 진술은 참이라 요구는 결정론뿐이고, 둘 다 켜서 「둘이 서 있다」는 없는
    개념을 만들지 않는다.
    """
    reg = _registry(tmp_path)
    later = reg.add(_preset("나중", _sel(("s1", ("o1",)))))
    first = reg.add(_preset("가장먼저", _sel(("s1", ("o1",)))))
    listing = list_selection_presets(reg, _pure_ctx(), _config(("s1", ("o1",))))
    assert [item.name for item in listing.items] == ["가장먼저", "나중"]
    assert listing.applied_key == first != later


def test_listing_without_a_config_claims_no_standing_preset(tmp_path: Path) -> None:
    """``config`` 를 넘기지 않는 호출(목록만 묻는 자리)은 표지를 주장하지 않는다."""
    reg = _registry(tmp_path)
    reg.add(_preset("표준", _sel(("s1", ("o1",)))))
    assert list_selection_presets(reg, _pure_ctx()).applied_key is None


def test_delete_restates_the_destroyed_name(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    key = reg.add(_preset("표준"))
    result = delete_selection_preset(reg, key)
    assert result.status == DELETED and result.name == "표준" and result.code is None
    assert not reg.exists(key)


@pytest.mark.parametrize("key", ["d" * 16, "../탈출"])
def test_delete_missing_or_invalid_key_is_not_found(tmp_path: Path, key: str) -> None:
    reg = _registry(tmp_path)
    result = delete_selection_preset(reg, key)
    assert result.status == REJECTED and result.code == PRESET_NOT_FOUND
    assert result.name is None and result.detail
