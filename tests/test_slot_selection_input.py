"""S4-10(#680) S5 입력 capture — 합타입·slotless/complete 판정·digest·fenced 경계."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.application.slot_configuration_context import SlotConfigurationContext
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
    SlotSelectionCaptureError,
    plan_capture,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_slot_configuration import (
    EMPTY,
    WorkSlotConfigurationDraft,
)
from hwpxfiller.domain.slot_selection import (
    DEFAULT_SELECTION_SEMANTIC_REGISTRY,
    SlotSelection,
    SlotSelectionSet,
    digest_selection_set,
)

NOW = "2026-08-16T00:00:00Z"
CONTRACT = "slot-selection/v1"
V1 = DEFAULT_SELECTION_SEMANTIC_REGISTRY.get(CONTRACT)
_SLOTTED = TemplateStructure(
    slots=(TemplateSlot(id="s1", options=(TemplateOption("o1"), TemplateOption("o2"))),)
)
_SLOTLESS = TemplateStructure(slots=())


def _sel(*pairs: tuple[str, list[str]]) -> SlotSelectionSet:
    return SlotSelectionSet(tuple(SlotSelection(s, tuple(o)) for s, o in pairs))


def _ctx(structure: TemplateStructure, app: str = "A1") -> SlotConfigurationContext:
    return SlotConfigurationContext(
        workspace_instance_id="ws-1", work_id="w1", template_application_id=app,
        template_lineage_id="L1", application_epoch=1, pass_evidence_id="E1",
        revision_id="R1", qualification_profile_id="hwpx-template-qualification-v1",
        structure_projection_schema_version="hwpx-structure-projection-v1",
        template_structure=structure, template_structure_digest="sha256:struct",
        selection_semantic_contract_id=CONTRACT, selection_semantic_contract=V1,
    )


def _cfg(selections: SlotSelectionSet, version: int = 1) -> WorkSlotConfigurationDraft:
    return WorkSlotConfigurationDraft(
        work_id="w1", base_template_application_id="A1", version=version,
        selections=selections, origin=EMPTY,
        reconciled_from_application_id=None, reconciled_from_version=None,
        reconciled_from_declared_selection_digest=None, created_at=NOW, updated_at=NOW,
    )


# ── pure judgment ─────────────────────────────────────────────────────────────
def test_complete_slot_bearing_makes_snapshot() -> None:
    snap = plan_capture(_ctx(_SLOTTED), _cfg(_sel(("s1", ["o1"]))), NOW)
    assert isinstance(snap, SlotConfigurationSnapshot)
    assert snap.effective_selections == _sel(("s1", ["o1"]))
    assert snap.effective_selection_digest == digest_selection_set(CONTRACT, _sel(("s1", ["o1"])))
    assert snap.template_structure_digest == "sha256:struct"
    assert snap.source_configuration_version == 1


@pytest.mark.parametrize("selections", [_sel(), _sel(("s1", ["gone"]))])  # missing / removed
def test_incomplete_capture_rejected(selections: SlotSelectionSet) -> None:
    with pytest.raises(SlotSelectionCaptureError) as e:
        plan_capture(_ctx(_SLOTTED), _cfg(selections), NOW)
    assert e.value.code == "SLOT_CONFIGURATION_INCOMPLETE"


def test_no_config_on_slot_bearing_is_incomplete() -> None:
    with pytest.raises(SlotSelectionCaptureError) as e:
        plan_capture(_ctx(_SLOTTED), None, NOW)
    assert e.value.code == "SLOT_CONFIGURATION_INCOMPLETE"


def test_stale_configuration_version_rejected() -> None:
    with pytest.raises(SlotSelectionCaptureError) as e:
        plan_capture(_ctx(_SLOTTED), _cfg(_sel(("s1", ["o1"])), version=3), NOW,
                     expected_configuration_presence=True, expected_configuration_version=1)
    assert e.value.code == "STALE_CONFIGURATION"


def test_presence_cas() -> None:
    slotted, cfg = _ctx(_SLOTTED), _cfg(_sel(("s1", ["o1"])), version=2)
    # presence=True + version 일치 → snapshot
    assert isinstance(
        plan_capture(slotted, cfg, NOW, expected_configuration_presence=True,
                     expected_configuration_version=2),
        SlotConfigurationSnapshot,
    )
    # presence=True + version 불일치 → STALE
    with pytest.raises(SlotSelectionCaptureError) as e1:
        plan_capture(slotted, cfg, NOW, expected_configuration_presence=True,
                     expected_configuration_version=1)
    assert e1.value.code == "STALE_CONFIGURATION"
    # presence=False 인데 config 가 생겼음 → STALE(미관찰 선택 캡처 방지)
    with pytest.raises(SlotSelectionCaptureError) as e2:
        plan_capture(slotted, cfg, NOW, expected_configuration_presence=False)
    assert e2.value.code == "STALE_CONFIGURATION"
    # presence=False + 실제 부재 → 통과(여기선 slot-bearing 이라 INCOMPLETE 로 진행)
    with pytest.raises(SlotSelectionCaptureError) as e3:
        plan_capture(slotted, None, NOW, expected_configuration_presence=False)
    assert e3.value.code == "SLOT_CONFIGURATION_INCOMPLETE"  # CAS 통과 후 완전성에서 걸림


def test_slotless_context_without_config() -> None:
    out = plan_capture(_ctx(_SLOTLESS), None, NOW)
    assert isinstance(out, SlotlessSelectionContext)
    assert out.source_configuration_version is None
    assert out.declared_selection_digest is None


def test_slotless_context_with_detached_only_config() -> None:
    # slot count 0 이면 Configuration·detached 유무와 무관하게 slotless 를 만든다.
    out = plan_capture(_ctx(_SLOTLESS), _cfg(_sel(("gone", ["x"])), version=4), NOW)
    assert isinstance(out, SlotlessSelectionContext)
    assert out.source_configuration_version == 4
    assert out.declared_selection_digest == digest_selection_set(CONTRACT, _sel(("gone", ["x"])))


# ── digest semantics ──────────────────────────────────────────────────────────
def test_detached_in_declared_not_effective() -> None:
    # config 는 current slot s1 + detached "gone" 을 선언한다.
    snap = plan_capture(_ctx(_SLOTTED), _cfg(_sel(("s1", ["o1"]), ("gone", ["x"]))), NOW)
    assert isinstance(snap, SlotConfigurationSnapshot)
    assert snap.effective_selection_digest == digest_selection_set(CONTRACT, _sel(("s1", ["o1"])))
    assert snap.declared_selection_digest == digest_selection_set(
        CONTRACT, _sel(("s1", ["o1"]), ("gone", ["x"]))
    )
    assert snap.effective_selection_digest != snap.declared_selection_digest


def test_detached_only_clear_keeps_effective_digest() -> None:
    with_detached = plan_capture(
        _ctx(_SLOTTED), _cfg(_sel(("s1", ["o1"]), ("gone", ["x"])), version=1), NOW
    )
    cleared = plan_capture(
        _ctx(_SLOTTED), _cfg(_sel(("s1", ["o1"])), version=2), NOW
    )
    assert isinstance(with_detached, SlotConfigurationSnapshot)
    assert isinstance(cleared, SlotConfigurationSnapshot)
    # version·declared 는 바뀌어도 effective digest 는 같다 → version 만으로 currentness 판정 금지.
    assert with_detached.effective_selection_digest == cleared.effective_selection_digest
    assert with_detached.declared_selection_digest != cleared.declared_selection_digest
    assert with_detached.source_configuration_version != cleared.source_configuration_version


def test_storage_order_independent_digest() -> None:
    struct = TemplateStructure(
        slots=(
            TemplateSlot(id="a", options=(TemplateOption("o1"),)),
            TemplateSlot(id="b", options=(TemplateOption("o2"),)),
        )
    )
    forward = plan_capture(_ctx(struct), _cfg(_sel(("a", ["o1"]), ("b", ["o2"]))), NOW)
    reverse = plan_capture(_ctx(struct), _cfg(_sel(("b", ["o2"]), ("a", ["o1"]))), NOW)
    assert isinstance(forward, SlotConfigurationSnapshot)
    assert isinstance(reverse, SlotConfigurationSnapshot)
    assert forward.effective_selection_digest == reverse.effective_selection_digest


# ── fenced entry (full port stack) ──────────────────────────────────────────────
from hwpxfiller.application.candidate_revision import TemplateRevision  # noqa: E402
from hwpxfiller.application.qualification_evidence import (  # noqa: E402
    QualificationEvidence,
    build_manifest,
    project_structure,
)
from hwpxfiller.application.slot_command import ConfigurationCommandContext  # noqa: E402
from hwpxfiller.application.slot_configuration_context import (  # noqa: E402
    StaleTemplateApplication,
)
from hwpxfiller.application.work_template_state import (  # noqa: E402
    INITIALIZATION,
    DocumentWork,
    WorkTemplateApplication,
)
from hwpxfiller.external.slot_command_runner import (  # noqa: E402
    capture_slot_selection_input,
    select_slot_option,
)
from hwpxfiller.external.work_configuration_store import (  # noqa: E402
    WorkSlotConfigurationStore,
)

SCHEMA = "hwpx-structure-projection-v1"
PROFILE = "hwpx-template-qualification-v1"


class _Qual:
    def __init__(self, evidence: QualificationEvidence, manifest: object) -> None:
        self._e, self._m = evidence, manifest

    def get_evidence(self, evidence_id: str) -> QualificationEvidence:
        return self._e

    def get_manifest(self, qualification_profile_id: str) -> object:
        return self._m


class _Candidate:
    def get_revision(self, revision_id: str) -> TemplateRevision:
        return TemplateRevision("R1", "L1", "hwpx", "sha256:blob1", "OBS1", NOW)

    def has_blob(self, digest: str) -> bool:
        return digest == "sha256:blob1"


class _WorkState:
    def __init__(self, agg: object) -> None:
        self._agg = agg

    def load(self, work_id: str) -> object:
        return self._agg


def _ports(structure: TemplateStructure = _SLOTTED, current: str = "A1"):
    work = DocumentWork("w1", "L1", current, None, 0)
    app = WorkTemplateApplication(
        application_id="A1", work_id="w1", application_epoch=1, pass_evidence_id="E1",
        previous_application_id=None, origin=INITIALIZATION, prepared_change_id=None,
        actor="t", applied_at=NOW,
    )
    evidence = QualificationEvidence(
        evidence_id="E1", attempt_id="AT1", revision_id="R1",
        qualification_profile_id=PROFILE, result="PASS",
        structure_projection=project_structure(structure, SCHEMA),
        diagnostics=(), engine_metadata={}, qualified_at=NOW,
    )
    manifest = build_manifest(
        qualification_profile_id=PROFILE, media="hwpx", adapter_contract_version="a",
        product_rule_version="p", operation_alphabet_version="op",
        projection_schema_version=SCHEMA, manifest_payload={"x": 1}, created_at=NOW,
    )
    agg = SimpleNamespace(work=work, applications=(app,))
    return _WorkState(agg), _Qual(evidence, manifest), _Candidate()


def _cmd_ctx(version: int | None = None) -> ConfigurationCommandContext:
    return ConfigurationCommandContext(
        workspace_instance_id="ws-1", expected_work_authority_id="w1",
        token_work_authority_id="w1", token_template_application_id="A1",
        token_selection_contract_id=CONTRACT, token_configuration_presence=version is not None,
        token_configuration_version=version, actor_binding_digest="sha256:actor",
    )


def test_capture_rejects_stale_application(tmp_path: Path) -> None:
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    with pytest.raises(StaleTemplateApplication):
        capture_slot_selection_input(
            store, *_ports(), workspace_instance_id="ws-1",
            expected_work_authority_id="w1",
            expected_template_application_id="A0",  # current 는 A1
            captured_at=NOW,
        )


def test_capture_rejects_other_workspace_aggregate(tmp_path: Path) -> None:
    # 같은 Work ID 이지만 다른 workspace 의 aggregate 를 캡처하지 않는다(cross-workspace).
    from hwpxfiller.application.slot_command import WorkspaceIdentityMismatch
    from hwpxfiller.application.stored_work_configuration import empty_stored

    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    store.create(empty_stored("ws-OTHER", "w1"))  # 다른 workspace
    with pytest.raises(WorkspaceIdentityMismatch):
        capture_slot_selection_input(
            store, *_ports(), workspace_instance_id="ws-1",
            expected_work_authority_id="w1", expected_template_application_id="A1",
            captured_at=NOW,
        )


def test_capture_slotless_through_fence(tmp_path: Path) -> None:
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    out = capture_slot_selection_input(
        store, *_ports(structure=_SLOTLESS), workspace_instance_id="ws-1",
        expected_work_authority_id="w1", expected_template_application_id="A1",
        captured_at=NOW,
    )
    assert isinstance(out, SlotlessSelectionContext)


def test_capture_snapshot_through_fence(tmp_path: Path) -> None:
    store = WorkSlotConfigurationStore(tmp_path / "cfg")
    ports = _ports()
    # 실제 select 로 store 를 채운다(ensure=v1, select=v2).
    select_slot_option(
        store, *ports, context=_cmd_ctx(), request_id="r1",
        slot_id="s1", option_id="o1", now=NOW,
    )
    out = capture_slot_selection_input(
        store, *ports, workspace_instance_id="ws-1", expected_work_authority_id="w1",
        expected_template_application_id="A1", expected_configuration_presence=True,
        expected_configuration_version=2, captured_at=NOW,
    )
    assert isinstance(out, SlotConfigurationSnapshot)
    assert out.effective_selections == _sel(("s1", ["o1"]))
    assert out.source_configuration_version == 2
