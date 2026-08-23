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

from datetime import datetime

import pytest

from hwpxfiller.application.fresh_execution_observation import (
    ADMITTED,
    READY,
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
)
from hwpxfiller.application.jobs import Job
from hwpxfiller.application.field_binding_input import (
    FieldBindingReviewRequired,
    StaleFieldBindingBasis,
)
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.field_binding_store import WorkFieldBindingStore, load_current_revision
from hwpxfiller.application.seal_execution_plan import RouteResolutionError
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.work_configuration_store import WorkspaceMetadataStore
from hwpxfiller.host.locations import default_template_authority_dir
from hwpxfiller.webapp.seal_execution_plan_product import (
    ExecutionPlanSealedProductOutcome,
    ExecutionQualificationBlockedProductOutcome,
)
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct

import hwpxfiller.webapp.seal_execution_plan_service as service_module
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


def test_saved_mapping_commits_revision_and_recomputes_sealed_value(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)

    committed = service.commit_current_mapping(WORK_REF, "binding-1")

    assert committed is not None and committed.changed is True
    revision = load_current_revision(
        WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1"
    )
    assert revision is not None
    assert tuple(rule.field_id for rule in revision.binding_rules) == (
        "\uc131\uba85",
        "\uc8fc\uc18c",
        "\ud56d\ubaa9",
    )
    resp = service.seal_execution_plan(WORK_REF, "seal-after-binding")
    assert isinstance(resp.command_outcome, ExecutionPlanSealedProductOutcome)
    assert isinstance(resp.fresh_observation, CurrentSealedPlanObservation)
    unchanged = service.commit_current_mapping(WORK_REF, "binding-2")
    assert unchanged is not None and unchanged.changed is False
    assert unchanged.revision_id == committed.revision_id


def test_blank_legacy_mapping_stays_review_required_and_writes_nothing(tmp_path) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    job.mapping.mappings[2] = FieldMapping("\ud56d\ubaa9", type="blank")
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)

    with pytest.raises(FieldBindingReviewRequired, match="explicit|\\uba85\\uc2dc"):
        service.commit_current_mapping(WORK_REF, "binding-blank")

    assert not WorkFieldBindingStore(root / "field_bindings").exists(WORK)


def test_mapping_basis_change_during_commit_writes_no_revision(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    real_commit = service_module.commit_field_binding_migration

    def race_mapping(*args, **kwargs):
        raced = registry.load(WORK_REF)
        raced.mapping = _complete_mapping("raced")
        registry.save(raced, allow_overwrite=True)
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(
        service_module,
        "commit_field_binding_migration",
        race_mapping,
    )

    with pytest.raises(StaleFieldBindingBasis):
        service.commit_current_mapping(WORK_REF, "binding-stale")

    assert not WorkFieldBindingStore(root / "field_bindings").exists(WORK)
