"""SX-SEAL(#719) SealExecutionPlanService — 실 store 백엔드로 실제 seal + fresh observation.

test_seal_execution_plan_product 의 fake World 계약을 production service 조립으로 강제한다: 실
Job registry·work/qualification/candidate/config/binding 로 실제 봉인해, binding 미seed→
ExecutionQualificationBlocked(+CurrentWorkExecutionObservation), seed→ExecutionPlanSealed(+current
sealable observation: ADMITTED·READY — S6-03(#810)이 shipping capability manifest 를 정식
주입 경로로 결속했다)을 낸다.

**R2(#740) 착지.** durable Plan store·Profile admission store·opaque Plan ref(resolve_plan_reference)·
HMAC secret 이 사라졌다 — seal 은 durable side effect 없는 순수 재계산이라 command outcome 은
``execution_basis_digest`` 로, observation 은 매 호출 current authority 재계산으로 온다. replay
idempotency·opaque ref restart·admission-store 조회 테스트는 그 축이 제거돼 삭제했다(아래 참조).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from hwpxfiller.application.fresh_execution_observation import (
    ADMITTED,
    READY,
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
)
from hwpxfiller.application.jobs import Job
from hwpxfiller.domain.job import JOB_MAPPING_AUTHORITY
from hwpxfiller.application.field_binding_input import field_binding_authority_revision_identity
from hwpxfiller.application.stored_field_binding import ApplicationRevisionPointer
from hwpxfiller.domain.field_binding import (
    FIELD_BINDING_SEMANTIC_VERSION_V2,
    FIELD_BINDING_SEMANTIC_VERSION_V3,
    FIELD_BINDING_SEMANTIC_VERSION_V4,
    digest_binding_rules,
)
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.field_binding_store import WorkFieldBindingStore, load_current_revision
from hwpxfiller.application.seal_execution_plan import RouteResolutionError
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.work_configuration_store import WorkspaceMetadataStore
from hwpxfiller.host.locations import default_template_authority_dir
from hwpxfiller.external.seal_execution_plan_product import (
    ExecutionPlanSealedProductOutcome,
    ExecutionQualificationBlockedProductOutcome,
)
from hwpxfiller.external.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct

from tests.test_execution_compilation import WORK
from tests.test_seal_execution_capture_runner import WS, _seed_v2_work

WORK_REF = "봉인작업"


def _registry(tmp_path) -> JobRegistry:
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=WORK_REF, template_path="managed.hwpx"))
    # route 가 resolve 할 WorkAuthorityId 를 seed 한 work aggregate 의 work_id 에 못박는다.
    reg.assign_authority_id(WORK_REF, WORK)
    return reg


def _service(tmp_path, *, with_binding: bool) -> SealExecutionPlanService:
    # R2(#740): admission store seed 불필요 — runtime admission 은 base kind·runtime support·
    # materializer conformance 만 보고 mutable Profile admission store 를 읽지 않는다.
    root = default_template_authority_dir()
    _seed_v2_work(root, with_binding=with_binding)
    registry = _registry(tmp_path)
    if with_binding:
        job = registry.load(WORK_REF)
        job.mapping = MappingProfile(
            mappings=[
                FieldMapping("\uc131\uba85", source="\uc774\ub984"),
                FieldMapping("\uc8fc\uc18c", type="const", const="\uc11c\uc6b8"),
                FieldMapping("\ud56d\ubaa9", type="blank"),
                FieldMapping("\uae08\uc561", source="\uae08\uc561\uc5f4"),
            ]
        )
        job.binding_authority = JOB_MAPPING_AUTHORITY
        registry.save(job, allow_overwrite=True)
    return SealExecutionPlanService(registry, root=root, clock=datetime.now)


# ─── binding 미seed → ExecutionQualificationBlocked + current-work observation ──────────────
def test_binding_absent_blocks_with_current_work_observation(tmp_path) -> None:
    service = _service(tmp_path, with_binding=False)
    resp = service.seal_execution_plan(WORK_REF, "r1")
    assert isinstance(resp.command_outcome, ExecutionQualificationBlockedProductOutcome)
    assert isinstance(resp.fresh_observation, CurrentWorkExecutionObservation)


# ─── binding seed → ExecutionPlanSealed + S6-03 정식 주입 판정(ADMITTED·READY) ────────────
def test_binding_present_seals_current_admitted_ready(tmp_path) -> None:
    # S6-03(#810): 실 서비스는 shipping capability manifest 를 등록한 registry 를 결속하므로
    # 실제 봉인 Plan 의 관찰은 ADMITTED + READY 다(NOT_ADMITTED 는 binding 부재 기본값에만 남는다).
    service = _service(tmp_path, with_binding=True)
    resp = service.seal_execution_plan(WORK_REF, "r1")
    outcome = resp.command_outcome
    assert isinstance(outcome, ExecutionPlanSealedProductOutcome)
    assert outcome.execution_basis_digest  # nonempty sealed basis identity
    obs = resp.fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    assert obs.runtime_policy_admission.state == ADMITTED
    assert obs.runtime_policy_admission.reasons == ()
    assert obs.materialization_readiness == READY


# ─── R2(#740): durable publication 없는 순수 재계산 → 같은 basis 는 같은 digest(결정론) ─────
def test_reseal_recomputes_same_basis_digest(tmp_path) -> None:
    service = _service(tmp_path, with_binding=True)
    first = service.seal_execution_plan(WORK_REF, "r1").command_outcome
    again = service.seal_execution_plan(WORK_REF, "r2").command_outcome
    assert isinstance(first, ExecutionPlanSealedProductOutcome)
    assert isinstance(again, ExecutionPlanSealedProductOutcome)
    # historical Plan lookup·replay idempotency 는 사라졌지만, 같은 current authority 는 같은
    # execution_basis_digest 로 재계산된다(value 가 곧 현재).
    assert again.execution_basis_digest == first.execution_basis_digest


# ─── S6-05(#812): sealed payload 운반 + managed run 조립 재료 ──────────────────────────
def test_sealed_outcome_carries_the_plan_payload(tmp_path) -> None:
    # payload 는 identity 가 아니라 화물 — basis digest 와 같은 응답에서 짝으로 온다(재판정 0).
    from hwpxfiller.application.execution_contract_set import (
        SealedExecutionPlanSemanticPayload,
        execution_basis_digest,
    )

    service = _service(tmp_path, with_binding=True)
    outcome = service.seal_execution_plan(WORK_REF, "r1").command_outcome
    assert isinstance(outcome, ExecutionPlanSealedProductOutcome)
    payload = outcome.plan_payload
    assert isinstance(payload, SealedExecutionPlanSemanticPayload)
    assert execution_basis_digest(payload.execution_basis) == outcome.execution_basis_digest


def test_managed_run_context_exposes_assembly_without_minting(tmp_path) -> None:
    service = _service(tmp_path, with_binding=True)
    # authority 미발급(어떤 확인·seal 도 전) — 발급하지 않고 None.
    assert service.managed_run_context(WORK_REF) is None
    outcome = service.seal_execution_plan(WORK_REF, "r1").command_outcome
    assert isinstance(outcome, ExecutionPlanSealedProductOutcome)
    context = service.managed_run_context(WORK_REF)
    assert context is not None
    assert context.work_authority_id
    assert context.runtime_capability_manifest_digest.startswith("sha256:")
    # reader 는 fence 없이 current basis 를 관찰한다 — 방금 봉인한 digest 와 동치다.
    assert context.current_basis_digest_reader() == outcome.execution_basis_digest


def test_basis_reader_returns_none_when_current_is_not_sealable(tmp_path) -> None:
    # binding 없는 Work 는 sealable 이 아니다 — reader 는 None(gate 가 시끄럽게 닫는다).
    service = _service(tmp_path, with_binding=False)
    service.seal_execution_plan(WORK_REF, "r1")  # route 가 authority 를 발급(blocked 종결)
    context = service.managed_run_context(WORK_REF)
    assert context is not None
    assert context.current_basis_digest_reader() is None


# ─── route 실패: 알 수 없는 work_ref → RouteResolutionError(request 미소비) ─────────────
def test_unknown_work_ref_raises_route_error(tmp_path) -> None:
    root = default_template_authority_dir()
    _seed_v2_work(root, with_binding=True)
    service = SealExecutionPlanService(_registry(tmp_path), root=root, clock=datetime.now)
    with pytest.raises(RouteResolutionError):
        service.seal_execution_plan("등록되지-않은-작업", "r1")


# ─── 삭제한 케이스(제거된 축) ─────────────────────────────────────────────────────────────
# - test_replay_returns_same_published_plan: R2 가 command_replayed/idempotency replay 를 제거.
#   대신 test_reseal_recomputes_same_basis_digest 가 결정론적 재계산을 확인한다.
# - test_opaque_ref_resolves_across_restart: resolve_plan_reference·opaque Plan ref 제거.
# - test_published_observation_surfaces_missing_admission: mutable Profile admission store 제거
#   (admission 부재라는 상태가 더는 없다 — runtime admission 은 capability 만 본다).


def test_binding_absent_projects_new_active_fields_and_exact_targets(tmp_path) -> None:
    service = _service(tmp_path, with_binding=False)
    service.seal_execution_plan(WORK_REF, "r1")

    projection = service.current_binding_review(WORK_REF)
    assert projection is not None
    assert projection.active_field_ids == ("\uc131\uba85", "\uc8fc\uc18c", "\ud56d\ubaa9")
    assert tuple(item.binding_state for item in projection.input_requirements) == (
        "NEW_ACTIVE_FIELD",
        "NEW_ACTIVE_FIELD",
        "NEW_ACTIVE_FIELD",
    )
    assert all(item.action_required for item in projection.input_requirements)
    assert tuple(item.exact_target for item in projection.input_requirements) == (
        "binding/\uc131\uba85",
        "binding/\uc8fc\uc18c",
        "binding/\ud56d\ubaa9",
    )


def test_binding_review_preserves_inactive_as_non_actionable(tmp_path) -> None:
    service = _service(tmp_path, with_binding=True)
    service.seal_execution_plan(WORK_REF, "r1")

    projection = service.current_binding_review(WORK_REF)
    assert projection is not None
    states = {
        item.field_id: (item.binding_state, item.action_required)
        for item in projection.input_requirements
    }
    assert states == {
        "\uc131\uba85": ("PRESERVED", False),
        "\uc8fc\uc18c": ("PRESERVED", False),
        "\ud56d\ubaa9": ("PRESERVED", False),
        "\uae08\uc561": ("INACTIVE_ONLY", False),
    }


def test_option_change_changes_backend_active_field_projection(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    WorkspaceMetadataStore(root).get_or_create("now", mint=lambda: WS)
    registry = _registry(tmp_path)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    slots = SlotConfigurationProduct(registry, root=root, clock=datetime.now)
    opened = slots.open_slot_configuration(WORK_REF)
    token = opened.current_view.new_configuration_token
    assert token is not None

    before = service.current_binding_review(WORK_REF)
    assert before is not None
    changed = slots.select_slot_option(
        WORK_REF,
        token,
        "s1",
        "o2",
        "select-o2",
    )
    assert changed.mutation_outcome is not None
    after = service.current_binding_review(WORK_REF)
    assert after is not None

    assert before.active_field_ids == ("\uc131\uba85", "\uc8fc\uc18c", "\ud56d\ubaa9")
    assert after.active_field_ids == ("\uc131\uba85", "\uc8fc\uc18c", "\uae08\uc561")


def test_passive_binding_review_does_not_create_workspace_metadata(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    registry = _registry(tmp_path)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    workspace = WorkspaceMetadataStore(root)
    assert workspace.read() is None

    assert service.current_binding_review(WORK_REF) is None
    assert workspace.read() is None
    registry.save(Job(name="draft", template_path="managed.hwpx"))
    assert service.current_binding_review("draft") is None
    assert service.managed_run_context("draft") is None
    assert registry.load("draft").authority_id == ""
    assert workspace.read() is None


def _complete_mapping(value: str = "v") -> MappingProfile:
    return MappingProfile(
        mappings=[
            FieldMapping(field_id, type="const", const=f"{value}-{field_id}")
            for field_id in (
                "\uc131\uba85",
                "\uc8fc\uc18c",
                "\ud56d\ubaa9",
                "\uae08\uc561",
            )
        ]
    )


def _review_states(service) -> dict[str, tuple[str, bool]]:
    projection = service.current_binding_review(WORK_REF)
    assert projection is not None
    return {
        item.field_id: (item.binding_state, item.action_required)
        for item in projection.input_requirements
    }


def test_saved_mapping_seals_without_a_second_binding_write(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    job.binding_authority = JOB_MAPPING_AUTHORITY
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)

    assert isinstance(
        service.seal_execution_plan(WORK_REF, "seal-mapping").command_outcome,
        ExecutionPlanSealedProductOutcome,
    )
    assert load_current_revision(
        WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1"
    ) is None
    assert all(not required for _, required in _review_states(service).values())


def test_option_roundtrip_keeps_inactive_mapping_rule_without_recommit(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    WorkspaceMetadataStore(root).get_or_create("now", mint=lambda: WS)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    job.binding_authority = JOB_MAPPING_AUTHORITY
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    slots = SlotConfigurationProduct(registry, root=root, clock=datetime.now)

    for index, option_id in enumerate(("o1", "o2", "o1")):
        opened = slots.open_slot_configuration(WORK_REF)
        token = opened.current_view.new_configuration_token
        assert token is not None
        slots.select_slot_option(WORK_REF, token, "s1", option_id, f"select-{index}")
        assert isinstance(
            service.seal_execution_plan(WORK_REF, f"seal-{index}").command_outcome,
            ExecutionPlanSealedProductOutcome,
        )
        assert all(not required for _, required in _review_states(service).values())
    assert load_current_revision(
        WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1"
    ) is None


def test_legacy_mapping_binding_conflict_requires_explicit_job_save(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=True)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping("edited")
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    prior = load_current_revision(WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1")
    assert prior is not None

    blocked = service.seal_execution_plan(WORK_REF, "before-explicit-save")
    assert isinstance(blocked.command_outcome, ExecutionQualificationBlockedProductOutcome)
    assert any(required for _, required in _review_states(service).values())

    job = registry.load(WORK_REF)
    job.binding_authority = JOB_MAPPING_AUTHORITY  # explicit editor-save outcome
    registry.save(job, allow_overwrite=True)
    sealed = service.seal_execution_plan(WORK_REF, "after-explicit-save")
    assert isinstance(sealed.command_outcome, ExecutionPlanSealedProductOutcome)
    assert load_current_revision(WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1") == prior


def test_legacy_matching_schema_still_rejects_different_rules(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=True)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = MappingProfile(mappings=[
        FieldMapping("성명", source="이름"),
        FieldMapping("주소", source="unused"),
        FieldMapping("항목", type="blank"),
        FieldMapping("금액", source="금액열"),
    ])
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)

    assert isinstance(
        service.seal_execution_plan(WORK_REF, "matching-schema-conflict").command_outcome,
        ExecutionQualificationBlockedProductOutcome,
    )
    assert any(required for _, required in _review_states(service).values())


def test_legacy_s5_only_inactive_rule_cannot_disappear_on_editor_save(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=True)
    registry = _registry(tmp_path)
    previous = registry.load(WORK_REF)
    candidate = registry.load(WORK_REF)
    # The old S5 aggregate carries the option-only “금액” rule, absent from
    # Mapping. A projected editor save must refuse a silent loss of that rule.
    candidate.mapping = MappingProfile(
        mappings=[FieldMapping(field, type="const", const="new") for field in ("성명", "주소", "항목")]
    )
    candidate.binding_authority = JOB_MAPPING_AUTHORITY
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    all_fields = frozenset(("성명", "주소", "항목", "금액"))
    assert service.unrepresented_legacy_rules(previous, candidate, all_fields) == ("금액",)

    candidate.mapping.mappings.append(FieldMapping("금액", type="const", const=""))
    assert service.unrepresented_legacy_rules(previous, candidate, all_fields) == ()

    candidate.mapping.mappings.pop()
    # The editor is showing a newer template without that old field. It is
    # removed, not an omitted inactive decision from the current schema.
    assert service.unrepresented_legacy_rules(
        previous, candidate, frozenset(("성명", "주소", "항목"))
    ) == ()
    previous.authority_id = "missing-work"
    with pytest.raises(ValueError, match="Work 상태"):
        service.unrepresented_legacy_rules(previous, candidate, all_fields)


@pytest.mark.parametrize("contract", (
    FIELD_BINDING_SEMANTIC_VERSION_V2,
    FIELD_BINDING_SEMANTIC_VERSION_V3,
    FIELD_BINDING_SEMANTIC_VERSION_V4,
))
def test_outdated_s5_stays_blocked_until_explicit_job_save(tmp_path, contract) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=True)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    registry.save(job, allow_overwrite=True)
    store = WorkFieldBindingStore(root / "field_bindings")
    current = load_current_revision(store, WORK, "app-1")
    assert current is not None
    rules = (
        tuple(dataclasses.replace(rule, format_kind=None, format_code=rule.format_code or None)
              for rule in current.binding_rules)
        if contract == FIELD_BINDING_SEMANTIC_VERSION_V2
        else current.binding_rules
    )
    digest = digest_binding_rules(rules, contract_id=contract)
    revision_id = field_binding_authority_revision_identity(
        work_authority_id=WORK,
        base_template_application_id="app-1",
        field_binding_semantic_contract_id=contract,
        source_schema_contract_id=current.source_schema_contract_id,
        raw_record_contract_id=current.raw_record_contract_id,
        canonical_binding_digest=digest,
        canonical_source_schema_digest=current.canonical_source_schema_digest,
    )
    old = dataclasses.replace(
        current, binding_rules=rules,
        field_binding_authority_revision=revision_id,
        field_binding_semantic_contract_id=contract,
        canonical_binding_digest=digest,
    )
    stored = store.load(WORK)
    store.update(WORK, stored.aggregate_version, lambda aggregate: dataclasses.replace(
        aggregate,
        aggregate_version=aggregate.aggregate_version + 1,
        current_by_application=(ApplicationRevisionPointer("app-1", revision_id),),
        immutable_binding_revisions=aggregate.immutable_binding_revisions + (old,),
    ))
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)

    blocked = service.seal_execution_plan(WORK_REF, "before-explicit-save")
    assert isinstance(blocked.command_outcome, ExecutionQualificationBlockedProductOutcome)
    assert "NEEDS_BINDING_SEMANTIC_MIGRATION" in blocked.command_outcome.normalized_blockers
    assert service.current_binding_review(WORK_REF) is not None
    assert load_current_revision(store, WORK, "app-1") == old

    job = registry.load(WORK_REF)
    job.binding_authority = JOB_MAPPING_AUTHORITY
    registry.save(job, allow_overwrite=True)
    sealed = service.seal_execution_plan(WORK_REF, "after-explicit-save")
    assert isinstance(sealed.command_outcome, ExecutionPlanSealedProductOutcome)
    assert load_current_revision(store, WORK, "app-1") == old


def test_routed_job_context_is_nested_and_identity_checked(tmp_path) -> None:
    service = _service(tmp_path, with_binding=False)
    registry = service._registry
    other = Job(name="other", template_path="managed.hwpx", authority_id="other-work")
    registry.save(other)
    outer = service._routed_work_ref.set(WORK_REF)
    try:
        assert service._routed_job(WORK).name == WORK_REF
        inner = service._routed_work_ref.set("other")
        try:
            assert service._routed_job("other-work").name == "other"
            with pytest.raises(ValueError, match="identity"):
                service._routed_job(WORK)
        finally:
            service._routed_work_ref.reset(inner)
        assert service._routed_job(WORK).name == WORK_REF
    finally:
        service._routed_work_ref.reset(outer)
    with pytest.raises(ValueError, match="routed Job"):
        service._routed_job(WORK)
