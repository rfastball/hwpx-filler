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


# ─── U3-04(#877): 판본은 활성 절단이 아니라 upsert + 비활성 규칙 보존 ────────────────────
def _roundtrip_world(tmp_path):
    """옵션 왕복 시나리오의 실 store 세계 — Mapping 은 네 Field 전건 확정 상태."""
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    # seed 한 config aggregate 와 같은 workspace identity 를 쓴다(select 가 그 aggregate 를 연다).
    WorkspaceMetadataStore(root).get_or_create("now", mint=lambda: WS)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)
    slots = SlotConfigurationProduct(registry, root=root, clock=datetime.now)
    return root, registry, service, slots


def _select_option(slots, option_id: str, request_id: str) -> None:
    opened = slots.open_slot_configuration(WORK_REF)
    token = opened.current_view.new_configuration_token
    assert token is not None
    response = slots.select_slot_option(WORK_REF, token, "s1", option_id, request_id)
    assert response.mutation_outcome is not None


def _review_states(service) -> dict[str, tuple[str, bool]]:
    projection = service.current_binding_review(WORK_REF)
    assert projection is not None
    return {
        item.field_id: (item.binding_state, item.action_required)
        for item in projection.input_requirements
    }


def test_option_roundtrip_needs_no_reconfirmation_after_both_options_committed(
    tmp_path,
) -> None:
    # A 확정 → B 전환(재확정 요구) → B 확정 → A 재선택. 마지막 단계에서 재확정 요구는 0 건이고
    # seal 이 그대로 통과한다 — 확정한 규칙이 비활성이 됐다고 판본에서 탈락하지 않기 때문이다.
    root, _registry_unused, service, slots = _roundtrip_world(tmp_path)
    bindings = WorkFieldBindingStore(root / "field_bindings")

    # 1) 옵션 o1(항목 활성)에서 확정.
    first = service.commit_current_mapping(WORK_REF, "commit-o1")
    assert first is not None and first.changed is True
    assert isinstance(
        service.seal_execution_plan(WORK_REF, "seal-o1").command_outcome,
        ExecutionPlanSealedProductOutcome,
    )

    # 2) 옵션 o2 로 전환 — 금액은 판본에 규칙이 없는 활성 Field 라 재확정을 요구한다.
    _select_option(slots, "o2", "select-o2")
    assert _review_states(service) == {
        "성명": ("PRESERVED", False),
        "주소": ("PRESERVED", False),
        "항목": ("INACTIVE_ONLY", False),
        "금액": ("NEW_ACTIVE_FIELD", True),
    }
    assert isinstance(
        service.seal_execution_plan(WORK_REF, "seal-o2-before").command_outcome,
        ExecutionQualificationBlockedProductOutcome,
    )

    # 3) 옵션 o2 에서 확정 — 판본은 교체가 아니라 upsert 다(비활성 항목 규칙이 남는다).
    second = service.commit_current_mapping(WORK_REF, "commit-o2")
    assert second is not None and second.changed is True
    revision = load_current_revision(bindings, WORK, "app-1")
    assert revision is not None
    assert {rule.field_id for rule in revision.binding_rules} == {
        "성명",
        "주소",
        "항목",
        "금액",
    }

    # 4) 옵션 o1 로 되돌아옴 — 재확정 요구 0 건, seal 통과.
    _select_option(slots, "o1", "select-o1-again")
    states = _review_states(service)
    assert states == {
        "성명": ("PRESERVED", False),
        "주소": ("PRESERVED", False),
        "항목": ("PRESERVED", False),
        "금액": ("INACTIVE_ONLY", False),
    }
    assert [field for field, (_, action) in states.items() if action] == []
    assert isinstance(
        service.seal_execution_plan(WORK_REF, "seal-o1-again").command_outcome,
        ExecutionPlanSealedProductOutcome,
    )


def test_preserved_inactive_rule_follows_the_current_mapping_decision(tmp_path) -> None:
    # 보존의 스코프는 판본이고 값은 Mapping 이다 — 비활성 동안 Mapping 이 바뀌면 판본이 따라간다
    # (편집기가 보여주는 값과 판본이 조용히 갈라지지 않는다).
    root, registry, service, slots = _roundtrip_world(tmp_path)
    service.commit_current_mapping(WORK_REF, "commit-o1")
    _select_option(slots, "o2", "select-o2")

    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping("고침")  # 항목(비활성) 포함 전건 재작성
    registry.save(job, allow_overwrite=True)
    service.commit_current_mapping(WORK_REF, "commit-o2-edited")

    revision = load_current_revision(WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1")
    assert revision is not None
    values = {
        rule.field_id: rule.canonical_constant_value.text
        for rule in revision.binding_rules
    }
    assert values["항목"] == "고침-항목"  # 비활성인데도 최신 결정
    assert values["금액"] == "고침-금액"


def test_inactive_unsupported_mapping_keeps_the_committed_rule_without_blocking(
    tmp_path,
) -> None:
    # 비활성 Field 가 옮길 수 없는 유형(「오늘 날짜」)으로 바뀌어도 확정을 막지 않는다
    # (명시 결정은 활성 Field 의 몫) — 판본은 이전에 확정한 규칙을 그대로 보존한다.
    root, registry, service, slots = _roundtrip_world(tmp_path)
    service.commit_current_mapping(WORK_REF, "commit-o1")
    _select_option(slots, "o2", "select-o2")

    job = registry.load(WORK_REF)
    job.mapping.mappings[2] = FieldMapping("항목", type="today")
    registry.save(job, allow_overwrite=True)
    committed = service.commit_current_mapping(WORK_REF, "commit-o2-blank")
    assert committed is not None

    revision = load_current_revision(WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1")
    assert revision is not None
    kept = {rule.field_id: rule for rule in revision.binding_rules}
    assert set(kept) == {"성명", "주소", "항목", "금액"}
    assert kept["항목"].canonical_constant_value.text == "v-항목"


def test_empty_constant_mapping_commits_as_an_exact_empty_text_rule(tmp_path) -> None:
    """빈 고정값은 모호하지 않다 — ``ExactText("")`` 규칙으로 그대로 확정된다.

    옛 ``blank``(출력 제외)는 Intentional Blank 와 뜻이 갈려 명시 결정을 요구했다. 그
    유형이 퇴역하고 「빈 문자열을 써 넣는다」 하나만 남으면서 그 모호함도 함께 죽었다.
    """
    root = tmp_path / "authority"
    _seed_v2_work(root, with_binding=False)
    registry = _registry(tmp_path)
    job = registry.load(WORK_REF)
    job.mapping = _complete_mapping()
    job.mapping.mappings[2] = FieldMapping("\ud56d\ubaa9", type="const")
    registry.save(job, allow_overwrite=True)
    service = SealExecutionPlanService(registry, root=root, clock=datetime.now)

    assert service.commit_current_mapping(WORK_REF, "binding-empty-const") is not None
    revision = load_current_revision(
        WorkFieldBindingStore(root / "field_bindings"), WORK, "app-1"
    )
    assert revision is not None
    rule = {r.field_id: r for r in revision.binding_rules}["\ud56d\ubaa9"]
    assert rule.canonical_constant_value.text == ""


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
