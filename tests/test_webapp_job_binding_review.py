"""SX-03(#726) — 「문서 만들기」 패널에 배선된 execution admission·readiness 헤드리스 가드 (post-R2 #740).

seal 판정·admission 파생은 SealExecutionPlanService·SealExecutionPlanProduct 테스트가 소유한다.
여기가 잰다: JobController 가 `self._seal_execution`(SX-SEAL) 을 소비해 (1) 확인 증거 없이
NO_EVIDENCE 로 서고, (2) `resolve_execution` 이 실 seal 을 돌려 binding 있는 Work 는
CURRENT+NOT_ADMITTED+NOT_READY 로, binding 없는 Work 는 정직한 blocked 로 관찰되며, (3) 어느 경우도
Primary Action 이 CREATE_DOCUMENTS 로 조용히 새지 않고, (4) snapshot 존이 그 관계를 그대로 나른다는 것.

R2(#740): currentness 축이 orchestration 으로 흡수됐다 — CURRENT/STALE 은 orchestration 상태가
나르고, opaque Plan ref·resolve_plan_reference·Profile admission store 는 사라졌다. seal 은 durable
side effect 없는 순수 재계산이라 마지막 sealed basis 는 digest 로만 잡힌다(_last_sealed_basis_digest).

**하드코딩 0**: admission/readiness/7상태는 전부 seal 서비스 fresh_observation 소비다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.application.jobs import Job
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.host.locations import default_template_authority_dir
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.seal_execution_plan_service import SealExecutionPlanService
from hwpxfiller.application.fresh_execution_observation import (
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
)
from hwpxfiller.webapp.slot_configuration_product import SlotConfigurationProduct
from hwpxfiller.webapp.workbench_observation_product import (
    WorkbenchObservationProduct,
    execution_verdicts_from_fresh,
)

from tests.test_execution_compilation import WORK
from tests.test_seal_execution_capture_runner import _seed_v2_work

WORK_REF = "봉인작업"
NOW = datetime(2026, 8, 18, 9, 0, 0)


def _clock():
    return lambda: NOW


def _controller(tmp_path: Path, *, with_binding: bool, wire_seal: bool = True):
    """실 SlotConfigurationProduct + SealExecutionPlanService 를 **같은 authority root** 로 배선.

    v2 Work 를 그 root 에 직접 seed 하고 registry 의 WorkAuthorityId 를 그 Work 에 못박아, 컨트롤러의
    job_name → seal 서비스 route 가 seed 한 Work 에 닿게 한다(test_seal_execution_plan_service 패턴).
    R2(#740): admission store seed 는 필요 없다 — runtime admission 은 materializer conformance
    capability(S6 미출하 → NOT_ADMITTED)만 본다.
    """
    root = default_template_authority_dir()
    _seed_v2_work(root, with_binding=with_binding)
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=WORK_REF, template_path=""))
    reg.assign_authority_id(WORK_REF, WORK)
    kwargs = dict(
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        slot_configuration=SlotConfigurationProduct(reg, root=root, clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
    )
    if wire_seal:
        kwargs["seal_execution"] = SealExecutionPlanService(reg, root=root, clock=datetime.now)
    ctrl = JobController(reg, lambda s, snap: None, **kwargs)
    ctrl.job_name = WORK_REF
    return ctrl


def _zone(ctrl) -> dict:
    return ctrl._workbench_observation_zone(tmissing=False)


# ── 확인 증거 없음 → NO_EVIDENCE(정직한 disabled) ─────────────────────────────────────────────
def test_no_evidence_before_any_check(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    zone = _zone(ctrl)
    assert zone["supported"] is True and zone["kind"] == "observation"
    assert zone["execution_status_code"] == "NO_EVIDENCE"
    assert zone["execution_status_phrase"] == "현재 설정을 확인해야 합니다"
    # 아직 확인 전이라 READY 를 주장하지 않는다(materialization NOT_READY).
    assert zone["materialization_readiness"] == "NOT_READY"
    assert zone["primary_action"] != "CREATE_DOCUMENTS"


# ── binding seed → resolve_execution → CURRENT + NOT_ADMITTED + NOT_READY(S6 미출하 정직) ───────
def test_resolve_execution_reaches_current_not_admitted_not_ready(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    assert zone["execution_status_code"] == "CURRENT"
    assert zone["execution_status_phrase"] == "현재 설정이 반영됐습니다"
    assert zone["admission"]["state"] == "NOT_ADMITTED"
    assert zone["materialization_readiness"] == "NOT_READY"
    # seal 루프가 닫혔다: 마지막 sealed basis digest 가 세션에 잡혔다(durable 아님).
    assert ctrl._last_sealed_basis_digest is not None
    # CREATE 로 조용히 새지 않는다(honest disabled) — delivery anchor + runtime.
    assert zone["primary_action"] != "CREATE_DOCUMENTS"


def test_create_documents_never_reached_with_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    obs = ctrl.workbench_observation()
    # CURRENT 여도 admission NOT_ADMITTED + delivery 미해결이라 CREATE_DOCUMENTS 아님.
    assert obs.primary_action != "CREATE_DOCUMENTS"
    assert obs.materialization_readiness == "NOT_READY"


# ── binding 없음 → 정직한 blocked(NO_EVIDENCE 를 CURRENT/READY 로 위장하지 않는다) ─────────────
def test_resolve_execution_without_binding_is_honestly_blocked(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=False)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    # 미봉인 — current Work 만 관찰(domain block). 7상태는 CURRENT/READY 가 아니다.
    assert zone["execution_status_code"] != "CURRENT"
    assert zone["execution_status_code"] in ("DOMAIN_BLOCKED", "POLICY_BLOCKED", "NO_EVIDENCE", "STALE")
    assert zone["materialization_readiness"] == "NOT_READY"
    assert zone["primary_action"] != "CREATE_DOCUMENTS"
    assert ctrl._last_sealed_basis_digest is None  # sealed 안 됨 → digest 없음


# ── refresh_observation: 지금 이 순간을 재관찰(orchestration 전이 없음) ──────────────────────────
def test_refresh_observation_reobserves_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    digest_after_seal = ctrl._last_sealed_basis_digest
    ctrl.dispatch("refresh_observation", {})
    # 재관찰은 같은 basis 를 재계산한다(같은 digest) — orchestration 은 SETTLED_CURRENT 유지.
    assert ctrl._last_sealed_basis_digest == digest_after_seal
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


def test_refresh_observation_standalone_observes_without_orchestration_transition(
    tmp_path: Path,
) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    # 사전 resolve 없이 refresh 만 해도 seal(순수 재계산)이 돌아 관찰을 얻는다 — orchestration 은
    # 건드리지 않으므로 IDLE 유지(자동 확인 궤도와 분리).
    ctrl.dispatch("refresh_observation", {})
    assert ctrl._last_fresh_observation is not None
    assert ctrl._session_orchestration.state == "IDLE"


# ── 반복 resolve 는 same-basis 를 같은 digest 로 재봉인(recompute 안정성) ──────────────────────────
def test_repeated_resolve_keeps_stable_basis_digest(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    first = ctrl._last_sealed_basis_digest
    ctrl.dispatch("resolve_execution", {})
    # basis 가 안 움직였으면 순수 재계산은 같은 execution_basis_digest 를 낸다.
    assert ctrl._last_sealed_basis_digest == first
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"


# ── 미주입 loud 거절(조용한 no-op 금지) ─────────────────────────────────────────────────────────
def test_resolve_execution_unwired_rejects_loudly(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    with pytest.raises(ValueError):
        ctrl.dispatch("resolve_execution", {})


# ── fresh_observation → verdict 추출(순수 재라벨, 재판정 0) ──────────────────────────────────────
def test_verdicts_from_context_error_observation() -> None:
    v = execution_verdicts_from_fresh(ExecutionObservationContextError("C_ERR", "detail"))
    # fresh 축 실패 → admission CONTEXT_ERROR(composer/status 가 ContextError 로 표현).
    assert v.admission.state == "CONTEXT_ERROR"
    assert v.materialization_readiness == "NOT_READY"


def test_verdicts_from_current_work_observation() -> None:
    obs = CurrentWorkExecutionObservation(
        work_authority_ref="w", current_sealability="DOMAIN_BLOCKED", observed_at="t"
    )
    v = execution_verdicts_from_fresh(obs)
    assert v.current_work_sealability == "DOMAIN_BLOCKED"
    assert v.admission.state == "NOT_ADMITTED"  # 미봉인 → 정직한 NOT_ADMITTED(READY 아님)


# ── automatic checking 트리거(durable slot mutation CHANGED → 자동 확인) ─────────────────────────
class _ChangedOutcome:
    changed = True


class _UnchangedOutcome:
    changed = False


class _SlotResp:
    def __init__(self, changed: bool) -> None:
        self.mutation_outcome = _ChangedOutcome() if changed else _UnchangedOutcome()


def test_changed_slot_mutation_triggers_auto_seal(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    # durable mutation CHANGED → effective_basis_changed True → CHECKING → seal → SETTLED_CURRENT.
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    assert ctrl._last_fresh_observation is not None
    assert ctrl._last_sealed_basis_digest is not None  # binding 있으니 sealed
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


def test_unchanged_slot_mutation_does_not_trigger_seal(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._maybe_auto_check(_SlotResp(changed=False))
    # 무변경 mutation → 반응할 basis 변경 없음(seal 미실행, 증거 없음 유지).
    assert ctrl._last_fresh_observation is None
    assert ctrl._session_orchestration.state == "IDLE"


def test_changed_mutation_without_binding_settles_not_current(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=False)
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    # seal 은 돌았지만 binding 미검토 → 미봉인(current-work 관찰). CURRENT 아님, digest 없음.
    assert ctrl._last_fresh_observation is not None
    assert ctrl._last_sealed_basis_digest is None
    assert _zone(ctrl)["execution_status_code"] != "CURRENT"


def test_auto_check_noop_without_seal_service(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    # seal 미주입이면 자동 확인 없음(honest — 표면 부재, 조용한 crash 아님).
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    assert ctrl._last_fresh_observation is None


# ── context error 를 user-fixable blocker 로 낮추지 않는다(§즉시 상향 계약) ──────────────────────
def test_context_error_observation_is_not_lowered_to_user_blocker(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._last_fresh_observation = ExecutionObservationContextError("E_CTX", "복원 실패")
    zone = _zone(ctrl)
    assert zone["kind"] == "context_error"
    assert zone["user_fixable"] is False
    assert zone["primary_action"] == "RECOVER_CONTEXT"


def test_zone_blank_without_selected_job(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.job_name = ""  # 미선택 → unsupported(조용히 비우지 않는다).
    zone = _zone(ctrl)
    assert zone["supported"] is False and zone["kind"] is None


# ── resolve_execution: FAILED 에서 수동 복구 후 재확인 ───────────────────────────────────────────
def test_resolve_execution_recovers_from_failed(tmp_path: Path) -> None:
    from hwpxfiller.application.automatic_seal_orchestration import AutomaticSealOrchestration

    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._session_orchestration = AutomaticSealOrchestration(
        state="FAILED", consecutive_seal_failures=3
    )
    ctrl.dispatch("resolve_execution", {})
    # FAILED → 수동 복구(IDLE) → CHECKING → 실 seal → SETTLED_CURRENT(binding 있음).
    assert ctrl._session_orchestration.state == "SETTLED_CURRENT"
    assert _zone(ctrl)["execution_status_code"] == "CURRENT"


# ── fresh 축 degrade(seal 실패는 조용히 CURRENT 로 두지 않는다) ─────────────────────────────────
class _RaisingSeal:
    """seal 이 예외를 던지는 fake seal 서비스 — degrade 경로 가드."""

    def seal_execution_plan(self, work, req):
        raise RuntimeError("seal boom")


def test_auto_seal_failure_leaves_last_observation(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    ctrl._seal_execution = _RaisingSeal()
    # route/context 예외 = 전이 실패(수동 복구 상한). 조용한 crash 아님, 마지막 관찰 보존(None).
    ctrl._maybe_auto_check(_SlotResp(changed=True))
    assert ctrl._last_fresh_observation is None


def test_refresh_observation_degrades_without_crashing(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True, wire_seal=False)
    ctrl._seal_execution = _RaisingSeal()
    # seal 실패 → 마지막 관찰 유지, 예외를 밖으로 내지 않는다.
    ctrl.dispatch("refresh_observation", {})
    assert ctrl._last_fresh_observation is None


# ── 사용자 문안 내부어 노출 0(#725 §테스트 12 계약 유지) ─────────────────────────────────────────
def test_observation_exposes_no_internal_vocabulary(tmp_path: Path) -> None:
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl.dispatch("resolve_execution", {})
    zone = _zone(ctrl)
    banned = ("Slot", "Sealed", "Plan", "digest", "Application", "VDR", "Candidate")
    texts = [zone["execution_status_phrase"], zone["content_section_label"],
             zone["input_requirements_label"], zone["delivery_label"]]
    if zone["disabled_reason"]:
        texts.append(zone["disabled_reason"])
    for text in texts:
        for word in banned:
            assert word not in text, (word, text)
