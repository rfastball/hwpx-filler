"""S4-07(#677) Slot Configuration command·fingerprint·CAS·durable idempotent replay."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hwpxfiller.application.candidate_revision import TemplateRevision
from hwpxfiller.application.qualification_evidence import (
    QualificationEvidence,
    build_manifest,
    project_structure,
)
from hwpxfiller.application.slot_command import (
    CHANGED,
    CLEAR,
    NO_CHANGE,
    SELECT,
    STALE_CONFIGURATION,
    STALE_TEMPLATE_APPLICATION,
    UNKNOWN_OPTION,
    UNKNOWN_SLOT,
    ConfigurationCommandContext,
    ConfigurationContextClaimMismatch,
    CrossWorkConfigurationToken,
    command_fingerprint,
)
from hwpxfiller.application.stored_work_configuration import IdempotencyKeyReused
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    PREPARED_CHANGE,
    DocumentWork,
    WorkTemplateApplication,
)
from hwpxfiller.external.slot_command_runner import (
    clear_slot_selection,
    ensure_current_slot_configuration,
    get_current_slot_configuration,
    select_slot_option,
)
from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore

NOW = "2026-08-16T00:00:00Z"
SCHEMA = "hwpx-structure-projection-v1"
PROFILE = "hwpx-template-qualification-v1"
WS = "ws-1"
CONTRACT = "slot-selection/v1"

_STRUCTURE = TemplateStructure(
    root_fields=(),
    slots=(TemplateSlot(id="s1", shared_fields=(), options=(TemplateOption("o1"), TemplateOption("o2"))),),
)


def _work(current: str = "A1") -> DocumentWork:
    return DocumentWork("w1", "L1", current, None, 0)


def _app(app_id: str = "A1", prev: str | None = None, epoch: int = 1) -> WorkTemplateApplication:
    origin = INITIALIZATION if prev is None else PREPARED_CHANGE
    return WorkTemplateApplication(
        application_id=app_id, work_id="w1", application_epoch=epoch,
        pass_evidence_id="E1", previous_application_id=prev,
        origin=origin, prepared_change_id=None if prev is None else "PC1",
        actor="t", applied_at=NOW,
    )


def _evidence(structure: TemplateStructure = _STRUCTURE) -> QualificationEvidence:
    return QualificationEvidence(
        evidence_id="E1", attempt_id="AT1", revision_id="R1",
        qualification_profile_id=PROFILE, result="PASS",
        structure_projection=project_structure(structure, SCHEMA),
        diagnostics=(), engine_metadata={}, qualified_at=NOW,
    )


class _Qual:
    def __init__(self, structure: TemplateStructure = _STRUCTURE) -> None:
        self._structure = structure

    def get_evidence(self, evidence_id: str) -> QualificationEvidence:
        return _evidence(self._structure)

    def get_manifest(self, qualification_profile_id: str) -> object:
        return build_manifest(
            qualification_profile_id=PROFILE, media="hwpx", adapter_contract_version="a",
            product_rule_version="p", operation_alphabet_version="op",
            projection_schema_version=SCHEMA, manifest_payload={"x": 1}, created_at=NOW,
        )


class _Candidate:
    def get_revision(self, revision_id: str) -> TemplateRevision:
        return TemplateRevision("R1", "L1", "hwpx", "sha256:blob1", "OBS1", NOW)

    def has_blob(self, digest: str) -> bool:
        return digest == "sha256:blob1"


class _WorkState:
    def __init__(self, current: str = "A1", apps: tuple | None = None) -> None:
        self._agg = SimpleNamespace(
            work=_work(current), applications=apps if apps is not None else (_app(),)
        )

    def load(self, work_id: str) -> object:
        return self._agg


def _ports(current: str = "A1", apps: tuple | None = None, structure: TemplateStructure = _STRUCTURE):
    return _WorkState(current, apps), _Qual(structure), _Candidate()


def _ctx(
    *, app: str = "A1", presence: bool = False, version: int | None = None,
    work: str = "w1", token_work: str | None = None, contract: str = CONTRACT,
) -> ConfigurationCommandContext:
    return ConfigurationCommandContext(
        workspace_instance_id=WS,
        expected_work_authority_id=work,
        token_work_authority_id=token_work if token_work is not None else work,
        token_template_application_id=app,
        token_selection_contract_id=contract,
        token_configuration_presence=presence,
        token_configuration_version=version,
        actor_binding_digest="sha256:actor",
    )


def _store(tmp_path: Path) -> WorkSlotConfigurationStore:
    return WorkSlotConfigurationStore(tmp_path / "cfg")


def _select(store, ports, ctx, *, req="r1", slot="s1", option="o1"):
    return select_slot_option(
        store, *ports, context=ctx, request_id=req, slot_id=slot, option_id=option, now=NOW
    )


# ── ensure ────────────────────────────────────────────────────────────────────
def test_ensure_creates_then_noop(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    first = ensure_current_slot_configuration(store, *ports, context=_ctx(), now=NOW)
    assert first.outcome_code == CHANGED and first.changed
    again = ensure_current_slot_configuration(store, *ports, context=_ctx(), now=NOW)
    assert again.outcome_code == NO_CHANGE and not again.changed
    assert len(store.load("w1").configurations.configurations) == 1  # 하나만


# ── select / clear ────────────────────────────────────────────────────────────
def test_select_then_same_is_no_change(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    out = _select(store, ports, _ctx())
    assert out.outcome_code == CHANGED and out.resulting_configuration_version == 2
    # 같은 값 재선택(token 이 이제 version 2 를 봄) → NO_CHANGE
    same = _select(store, ports, _ctx(presence=True, version=2), req="r2")
    assert same.outcome_code == NO_CHANGE and not same.changed


def test_select_unknown_slot(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    assert _select(store, ports, _ctx(), slot="nope").outcome_code == UNKNOWN_SLOT


def test_select_unknown_option(tmp_path: Path) -> None:
    store, ports = _store(tmp_path / "b"), _ports()
    assert _select(store, ports, _ctx(), option="zzz").outcome_code == UNKNOWN_OPTION


def test_clear_removes_then_noop(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    _select(store, ports, _ctx())  # s1=o1 (config version 2)
    cleared = clear_slot_selection(
        store, *ports, context=_ctx(presence=True, version=2), request_id="r2", slot_id="s1", now=NOW
    )
    assert cleared.outcome_code == CHANGED
    again = clear_slot_selection(
        store, *ports, context=_ctx(presence=True, version=3), request_id="r3", slot_id="s1", now=NOW
    )
    assert again.outcome_code == NO_CHANGE


# ── CAS / stale ───────────────────────────────────────────────────────────────
def test_stale_configuration_version_rejected(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    _select(store, ports, _ctx())  # config now version 2
    # token 이 version 1 을 봤다고 주장 → STALE_CONFIGURATION(같은 값이어도)
    out = _select(store, ports, _ctx(presence=True, version=1), req="r2")
    assert out.outcome_code == STALE_CONFIGURATION and not out.changed


def test_stale_template_application_rejected(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports(current="A2")  # current 는 A2
    out = _select(store, ports, _ctx(app="A1"))  # token 은 옛 A1
    assert out.outcome_code == STALE_TEMPLATE_APPLICATION and not out.changed


def test_cross_work_token_raised_not_stored(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    with pytest.raises(CrossWorkConfigurationToken):
        _select(store, ports, _ctx(work="w1", token_work="other"))


def test_contract_claim_mismatch_raised(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    with pytest.raises(ConfigurationContextClaimMismatch):
        _select(store, ports, _ctx(contract="slot-selection/v9"))


# ── idempotency / replay ──────────────────────────────────────────────────────
def test_replay_same_request_same_fingerprint(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    first = _select(store, ports, _ctx())
    replay = _select(store, ports, _ctx(), req="r1")  # 같은 request_id·같은 claims
    assert replay.outcome_replayed is True
    assert replay.outcome_code == first.outcome_code
    assert replay.resulting_configuration_version == first.resulting_configuration_version
    # ledger record 하나만
    assert len(store.load("w1").processed_requests) == 1


def test_key_reuse_different_payload_rejected(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    _select(store, ports, _ctx())
    before = store.load("w1").processed_requests
    with pytest.raises(IdempotencyKeyReused):
        _select(store, ports, _ctx(presence=True, version=2), option="o2")  # 같은 req 다른 option
    assert store.load("w1").processed_requests == before  # 기존 record 불변


def test_replay_after_application_advance(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _select(store, _ports(), _ctx())
    # Application 이 advance 해 current 가 A2 여도, 같은 request 는 원래 outcome 을 재생한다.
    replay = _select(store, _ports(current="A2"), _ctx(app="A1"), req="r1")
    assert replay.outcome_replayed and replay.outcome_code == first.outcome_code


# ── historical isolation ──────────────────────────────────────────────────────
def test_mutation_touches_only_current_application(tmp_path: Path) -> None:
    # A1·A2 두 Application 에 각각 config. current=A2 에 select → A1 config 무변경.
    store = _store(tmp_path)
    ports1 = _ports(current="A1")
    _select(store, ports1, _ctx(app="A1"))  # A1 config version 2
    a1_before = next(
        c for c in store.load("w1").configurations.configurations
        if c.base_template_application_id == "A1"
    )
    apps = (_app("A1"), _app("A2", prev="A1", epoch=2))
    ports2 = _ports(current="A2", apps=apps)
    _select(store, ports2, _ctx(app="A2"), req="r2")
    a1_after = next(
        c for c in store.load("w1").configurations.configurations
        if c.base_template_application_id == "A1"
    )
    assert a1_after == a1_before  # historical A1 config 무변경


# ── fingerprint ───────────────────────────────────────────────────────────────
def test_fingerprint_stable_across_new_token_same_claims() -> None:
    a = command_fingerprint(SELECT, _ctx(presence=True, version=3), "s1", "o1")
    b = command_fingerprint(SELECT, _ctx(presence=True, version=3), "s1", "o1")
    assert a == b  # token ciphertext·nonce·issued_at 은 fingerprint 밖


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: replace(c, expected_work_authority_id="w9", token_work_authority_id="w9"),
        lambda c: replace(c, token_selection_contract_id="slot-selection/v9"),
        lambda c: replace(c, token_configuration_version=99),
        lambda c: replace(c, workspace_instance_id="ws-9"),
    ],
)
def test_fingerprint_changes_on_claim_change(mutate) -> None:
    base = _ctx(presence=True, version=3)
    assert command_fingerprint(SELECT, base, "s1", "o1") != command_fingerprint(
        SELECT, mutate(base), "s1", "o1"
    )


def test_fingerprint_clear_differs_from_select_and_option() -> None:
    ctx = _ctx(presence=True, version=3)
    sel_o1 = command_fingerprint(SELECT, ctx, "s1", "o1")
    sel_o2 = command_fingerprint(SELECT, ctx, "s1", "o2")
    clear = command_fingerprint(CLEAR, ctx, "s1", None)
    assert len({sel_o1, sel_o2, clear}) == 3  # clear marker 는 어떤 option 과도 다르다


# ── get ───────────────────────────────────────────────────────────────────────
def test_get_reflects_current_selection(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    _select(store, ports, _ctx())
    view = get_current_slot_configuration(store, *ports, context=_ctx(presence=True, version=2))
    assert view.configuration_version == 2
    assert view.resolution.slot_selections_complete is True


def test_get_before_any_configuration(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    view = get_current_slot_configuration(store, *ports, context=_ctx())
    assert view.configuration is None and view.configuration_version is None


def test_clear_other_slot_without_entry_is_noop(tmp_path: Path) -> None:
    # config 에 s1 entry 만 있을 때 s2(structure 엔 있음) clear → entry 없어 NO_CHANGE.
    two = TemplateStructure(
        slots=(
            TemplateSlot(id="s1", options=(TemplateOption("o1"),)),
            TemplateSlot(id="s2", options=(TemplateOption("x"),)),
        )
    )
    store, ports = _store(tmp_path), _ports(structure=two)
    _select(store, ports, _ctx())  # s1=o1, config version 2
    out = clear_slot_selection(
        store, *ports, context=_ctx(presence=True, version=2), request_id="r2", slot_id="s2", now=NOW
    )
    assert out.outcome_code == NO_CHANGE


def test_clear_unknown_slot(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports()
    out = clear_slot_selection(
        store, *ports, context=_ctx(), request_id="r1", slot_id="ghost", now=NOW
    )
    assert out.outcome_code == UNKNOWN_SLOT


# ── slotless (0-slot structure) barrier ─────────────────────────────────────────
_EMPTY_STRUCTURE = TemplateStructure(root_fields=(), slots=())


def test_ensure_slotless_skips_creation(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports(structure=_EMPTY_STRUCTURE)
    out = ensure_current_slot_configuration(store, *ports, context=_ctx(), now=NOW)
    assert out.outcome_code == NO_CHANGE and store.exists("w1")  # ledger-only 존재
    assert len(store.load("w1").configurations.configurations) == 0  # config 없음


def test_select_slotless_is_unknown_slot(tmp_path: Path) -> None:
    store, ports = _store(tmp_path), _ports(structure=_EMPTY_STRUCTURE)
    assert _select(store, ports, _ctx(), slot="s1").outcome_code == UNKNOWN_SLOT


# ── pure decision branches ──────────────────────────────────────────────────────
def test_decide_select_unsupported_policy_and_no_options() -> None:
    from hwpxfiller.application.slot_command import (
        NO_AVAILABLE_OPTIONS,
        UNSUPPORTED_SELECTION_POLICY,
        decide_select,
    )
    from hwpxfiller.application.work_slot_configuration import create_empty
    from hwpxfiller.domain.slot_selection import SelectionSemanticContractManifest

    v1 = SimpleNamespace(
        template_structure=TemplateStructure(
            slots=(TemplateSlot(id="s1", options=()),)  # option 0개
        ),
        selection_semantic_contract=SimpleNamespace(
            default_selection_policy="EXACTLY_ONE", supported_selection_policies=("EXACTLY_ONE",)
        ),
    )
    cfg = create_empty("w1", "A1", NOW)
    assert decide_select(v1, cfg, "s1", "x", NOW).outcome_code == NO_AVAILABLE_OPTIONS

    bad = SimpleNamespace(
        template_structure=TemplateStructure(slots=(TemplateSlot(id="s1", options=(TemplateOption("o1"),)),)),
        selection_semantic_contract=SelectionSemanticContractManifest(
            "c", "s", "c", "MANY", ("MANY",), "v"  # None cardinality 미지원
        ),
    )
    assert decide_select(bad, cfg, "s1", "o1", NOW).outcome_code == UNSUPPORTED_SELECTION_POLICY
