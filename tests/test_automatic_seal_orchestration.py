"""automatic qualification/seal orchestration 순수 상태 기계 계약 (SX-01 · #724 §4 · #719 D2).

backend basis 판정을 재구현하지 않고 입력 플래그로 받음을 정적으로도 단언한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import hwpxfiller.application.automatic_seal_orchestration as orch_module
from hwpxfiller.application.document_creation_vocabulary import USER_VOCABULARY
from hwpxfiller.application.automatic_seal_orchestration import (
    CHECKING,
    DEFAULT_MAX_CONSECUTIVE_SEAL_FAILURES,
    FAILED,
    IDLE,
    ORCHESTRATION_STATES,
    ORCHESTRATION_USER_PHRASE,
    SETTLED_CURRENT,
    STALE,
    AutomaticSealOrchestration,
    on_durable_command_settled,
    on_seal_settled,
    request_manual_recovery,
)


# ─── effective_basis_changed=True → seal 시작 ───────────────────────────────────────────────
def test_basis_changed_starts_checking_and_seal():
    start = AutomaticSealOrchestration(state=IDLE)
    t = on_durable_command_settled(
        start, durable_command_succeeded=True, effective_basis_changed=True
    )
    assert t.should_start_seal is True
    assert t.next_state.state == CHECKING
    assert t.next_state.plan_affecting_inputs_locked is True
    assert t.next_state.global_lock is False


def test_basis_changed_from_settled_current_restarts_checking():
    settled = AutomaticSealOrchestration(state=SETTLED_CURRENT)
    t = on_durable_command_settled(
        settled, durable_command_succeeded=True, effective_basis_changed=True
    )
    assert t.should_start_seal is True
    assert t.next_state.state == CHECKING


# ─── same-basis → blanket reseal 0 ──────────────────────────────────────────────────────────
def test_same_basis_does_not_reseal_keeps_current():
    settled = AutomaticSealOrchestration(state=SETTLED_CURRENT)
    t = on_durable_command_settled(
        settled, durable_command_succeeded=True, effective_basis_changed=False
    )
    assert t.should_start_seal is False
    assert t.next_state.state == SETTLED_CURRENT


def test_same_basis_from_idle_settles_current_without_seal():
    t = on_durable_command_settled(
        AutomaticSealOrchestration(state=IDLE),
        durable_command_succeeded=True,
        effective_basis_changed=False,
    )
    assert t.should_start_seal is False
    assert t.next_state.state == SETTLED_CURRENT


def test_same_basis_while_checking_does_not_start_second_seal():
    checking = AutomaticSealOrchestration(state=CHECKING)
    t = on_durable_command_settled(
        checking, durable_command_succeeded=True, effective_basis_changed=False
    )
    assert t.should_start_seal is False
    assert t.next_state.state == CHECKING


# ─── durable command 실패 → seal 시작 안 함 ─────────────────────────────────────────────────
def test_failed_durable_command_does_not_start_seal():
    settled = AutomaticSealOrchestration(state=SETTLED_CURRENT)
    t = on_durable_command_settled(
        settled, durable_command_succeeded=False, effective_basis_changed=True
    )
    assert t.should_start_seal is False
    assert t.next_state.state == SETTLED_CURRENT


# ─── coalescing(타이머 없이 플래그로) ────────────────────────────────────────────────────────
def test_basis_change_while_checking_coalesces_without_second_seal():
    checking = AutomaticSealOrchestration(state=CHECKING)
    t = on_durable_command_settled(
        checking, durable_command_succeeded=True, effective_basis_changed=True
    )
    assert t.should_start_seal is False  # 두 번째 seal 을 동시에 띄우지 않는다
    assert t.next_state.state == CHECKING
    assert t.next_state.coalescing_pending is True


def test_coalesced_change_resumed_after_seal_settles():
    checking = AutomaticSealOrchestration(state=CHECKING, coalescing_pending=True)
    t = on_seal_settled(
        checking, seal_succeeded=True, resulting_currentness_current=True
    )
    # 대기 중이던 사용자 변경을 이어 검사한다(사용자 변경 유래 → 무한 자동 재시도 아님).
    assert t.should_start_seal is True
    assert t.next_state.state == CHECKING
    assert t.next_state.coalescing_pending is False


# ─── seal 성공/실패 전이 ────────────────────────────────────────────────────────────────────
def test_seal_success_current_settles():
    checking = AutomaticSealOrchestration(state=CHECKING, consecutive_seal_failures=2)
    t = on_seal_settled(
        checking, seal_succeeded=True, resulting_currentness_current=True
    )
    assert t.should_start_seal is False
    assert t.next_state.state == SETTLED_CURRENT
    assert t.next_state.consecutive_seal_failures == 0  # 성공은 실패 수를 reset


def test_seal_success_but_still_stale_goes_stale_without_retry():
    checking = AutomaticSealOrchestration(state=CHECKING)
    t = on_seal_settled(
        checking, seal_succeeded=True, resulting_currentness_current=False
    )
    assert t.should_start_seal is False  # 자동 재시도 안 함
    assert t.next_state.state == STALE


def test_seal_settled_when_not_checking_is_noop():
    settled = AutomaticSealOrchestration(state=SETTLED_CURRENT)
    t = on_seal_settled(
        settled, seal_succeeded=True, resulting_currentness_current=True
    )
    assert t.next_state.state == SETTLED_CURRENT
    assert t.should_start_seal is False


# ─── 실패 뒤 무한 재시도 아님 → 상한 도달 시 수동 복구 ───────────────────────────────────────
def test_failure_below_cap_goes_stale_no_auto_retry():
    checking = AutomaticSealOrchestration(state=CHECKING, consecutive_seal_failures=0)
    t = on_seal_settled(
        checking, seal_succeeded=False, resulting_currentness_current=False
    )
    assert t.should_start_seal is False
    assert t.next_state.state == STALE
    assert t.next_state.consecutive_seal_failures == 1


def test_failures_reaching_cap_require_manual_recovery():
    state = AutomaticSealOrchestration(
        state=CHECKING, consecutive_seal_failures=DEFAULT_MAX_CONSECUTIVE_SEAL_FAILURES - 1
    )
    t = on_seal_settled(
        state, seal_succeeded=False, resulting_currentness_current=False
    )
    assert t.next_state.state == FAILED
    assert t.next_state.requires_manual_recovery is True
    assert t.should_start_seal is False


def test_failed_state_does_not_auto_restart_on_basis_change():
    failed = AutomaticSealOrchestration(
        state=FAILED, consecutive_seal_failures=DEFAULT_MAX_CONSECUTIVE_SEAL_FAILURES
    )
    t = on_durable_command_settled(
        failed, durable_command_succeeded=True, effective_basis_changed=True
    )
    # 무한 자동 재시도 금지 — 수동 복구 전까지 seal 을 다시 시작하지 않는다.
    assert t.should_start_seal is False
    assert t.next_state.state == FAILED


def test_manual_recovery_resets_failed_to_idle():
    failed = AutomaticSealOrchestration(state=FAILED, consecutive_seal_failures=3)
    recovered = request_manual_recovery(failed)
    assert recovered.state == IDLE
    assert recovered.consecutive_seal_failures == 0
    assert recovered.requires_manual_recovery is False


def test_manual_recovery_noop_when_not_failed():
    settled = AutomaticSealOrchestration(state=SETTLED_CURRENT)
    assert request_manual_recovery(settled) == settled


# ─── CHECKING 은 Plan-affecting 만 잠근다(전역 아님) ──────────────────────────────────────────
def test_checking_locks_only_plan_affecting_never_global():
    checking = AutomaticSealOrchestration(state=CHECKING)
    assert checking.plan_affecting_inputs_locked is True
    assert checking.global_lock is False
    for other in (IDLE, SETTLED_CURRENT, STALE, FAILED):
        s = AutomaticSealOrchestration(state=other)
        assert s.plan_affecting_inputs_locked is False
        assert s.global_lock is False


# ─── 값 모델 검증 ────────────────────────────────────────────────────────────────────────────
def test_invalid_state_rejected():
    with pytest.raises(ValueError):
        AutomaticSealOrchestration(state="NOPE")


def test_negative_failures_rejected():
    with pytest.raises(ValueError):
        AutomaticSealOrchestration(state=IDLE, consecutive_seal_failures=-1)


def test_states_tuple_is_stable():
    assert ORCHESTRATION_STATES == (IDLE, CHECKING, SETTLED_CURRENT, STALE, FAILED)


# ─── 사용자 문안 vocabulary 정합 ────────────────────────────────────────────────────────────
def test_user_phrases_align_with_vocabulary_single_source():
    assert ORCHESTRATION_USER_PHRASE[SETTLED_CURRENT] == USER_VOCABULARY["Plan current"]
    assert ORCHESTRATION_USER_PHRASE[STALE] == USER_VOCABULARY["Plan stale"]


# ─── backend 판정 미재구현(정적 단언) + 수동 seal 동사 미export ──────────────────────────────
def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_does_not_import_backend_currentness_judgment():
    source = Path(orch_module.__file__).read_text(encoding="utf-8")
    modules = _imported_module_names(source)
    # currentness/basis 판정 소유 모듈을 import 하지 않는다 — 판정은 입력 플래그로 받는다.
    assert "hwpxfiller.webapp.seal_execution_plan_product" not in modules
    assert "hwpxfiller.application.fresh_execution_observation" not in modules
    assert "hwpxfiller.external.seal_orchestration_runner" not in modules
    # 프로젝트 import 는 vocabulary 하나뿐이다.
    project = {m for m in modules if m.startswith("hwpxfiller")}
    assert project == {"hwpxfiller.application.document_creation_vocabulary"}


def test_transition_functions_receive_basis_verdict_as_input_flag():
    import inspect

    params = inspect.signature(on_durable_command_settled).parameters
    assert "effective_basis_changed" in params  # backend 판정을 입력으로 받는다
    seal_params = inspect.signature(on_seal_settled).parameters
    assert "resulting_currentness_current" in seal_params


def test_no_manual_seal_management_verbs_exported():
    # seal now/reseal/publish 같은 수동 seal 관리 동사를 노출하지 않는다.
    public = {n for n in dir(orch_module) if not n.startswith("_")}
    for forbidden in ("seal_now", "reseal", "publish_plan", "start_seal", "manage_plan"):
        assert forbidden not in public
