"""SX-SEAL(#719) SealExecutionPlanService — 실 store 백엔드로 실제 seal + fresh observation.

test_seal_execution_plan_product 의 fake World 계약을 production service 조립으로 강제한다: 실
Job registry·work/qualification/candidate/config/binding 로 실제 봉인해, binding 미seed→
ExecutionQualificationBlocked(+CurrentWorkExecutionObservation), seed→ExecutionPlanSealed(+current
sealable observation: NOT_ADMITTED·NOT_READY = S6 미출하 판정)을 낸다.

**R2(#740) 착지.** durable Plan store·Profile admission store·opaque Plan ref(resolve_plan_reference)·
HMAC secret 이 사라졌다 — seal 은 durable side effect 없는 순수 재계산이라 command outcome 은
``execution_basis_digest`` 로, observation 은 매 호출 current authority 재계산으로 온다. replay
idempotency·opaque ref restart·admission-store 조회 테스트는 그 축이 제거돼 삭제했다(아래 참조).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hwpxfiller.application.fresh_execution_observation import (
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    NOT_ADMITTED,
    NOT_READY,
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
)
from hwpxfiller.application.jobs import Job
from hwpxfiller.application.seal_execution_plan import RouteResolutionError
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.host.locations import default_template_authority_dir
from hwpxfiller.webapp.seal_execution_plan_product import (
    ExecutionPlanSealedProductOutcome,
    ExecutionQualificationBlockedProductOutcome,
)
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService

from tests.test_execution_compilation import WORK
from tests.test_seal_execution_capture_runner import _seed_v2_work

WORK_REF = "봉인작업"


def _registry(tmp_path) -> JobRegistry:
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=WORK_REF, template_path=""))
    # route 가 resolve 할 WorkAuthorityId 를 seed 한 work aggregate 의 work_id 에 못박는다.
    reg.assign_authority_id(WORK_REF, WORK)
    return reg


def _service(tmp_path, *, with_binding: bool) -> SealExecutionPlanService:
    # R2(#740): admission store seed 불필요 — runtime admission 은 base kind·runtime support·
    # materializer conformance 만 보고 mutable Profile admission store 를 읽지 않는다.
    root = default_template_authority_dir()
    _seed_v2_work(root, with_binding=with_binding)
    return SealExecutionPlanService(_registry(tmp_path), root=root, clock=datetime.now)


# ─── binding 미seed → ExecutionQualificationBlocked + current-work observation ──────────────
def test_binding_absent_blocks_with_current_work_observation(tmp_path) -> None:
    service = _service(tmp_path, with_binding=False)
    resp = service.seal_execution_plan(WORK_REF, "r1")
    assert isinstance(resp.command_outcome, ExecutionQualificationBlockedProductOutcome)
    assert isinstance(resp.fresh_observation, CurrentWorkExecutionObservation)


# ─── binding seed → ExecutionPlanSealed + S6 미출하 판정(NOT_ADMITTED·NOT_READY) ──────────
def test_binding_present_seals_current_not_admitted_not_ready(tmp_path) -> None:
    service = _service(tmp_path, with_binding=True)
    resp = service.seal_execution_plan(WORK_REF, "r1")
    outcome = resp.command_outcome
    assert isinstance(outcome, ExecutionPlanSealedProductOutcome)
    assert outcome.execution_basis_digest  # nonempty sealed basis identity
    obs = resp.fresh_observation
    assert isinstance(obs, CurrentSealedPlanObservation)
    # S6 미출하: runtime materializer 미admit → NOT_ADMITTED + NOT_READY(READY 과장 0).
    assert obs.runtime_policy_admission.state == NOT_ADMITTED
    assert (
        MATERIALIZATION_CONTRACT_NOT_ADMITTED in obs.runtime_policy_admission.reasons
    )
    assert obs.materialization_readiness == NOT_READY


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
