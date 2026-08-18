"""SX-03(#726) §3 — 작업대 execution status 7상태 파생의 순수 재라벨 계약 (post-R2 #740).

여기가 잰다: 7상태 각각이 어느 verdict 조합에서 나오는지, 우선순위가 composer blocker 서열과
정합하는지, 그리고 함수가 **verdict 만 읽고 재판정하지 않는지**(입력에 없는 새 판정 0).

R2(#740): currentness 축(SemanticCurrentness CURRENT/STALE)이 orchestration 으로 흡수됐다 —
CURRENT/STALE/CHECKING/NO_EVIDENCE 는 orchestration 상태가, DOMAIN/POLICY/CONTEXT 는 fresh
observation 의 sealability·admission 이 나른다(current value 는 자명히 현재라 별도 currentness 없음).
"""

from __future__ import annotations

from hwpxfiller.application.automatic_seal_orchestration import (
    AutomaticSealOrchestration,
)
from hwpxfiller.application.fresh_execution_observation import (
    ADMISSION_CONTEXT_ERROR,
    ADMITTED,
    DOMAIN_BLOCKED as SEALABILITY_DOMAIN_BLOCKED,
    NOT_ADMITTED,
    POLICY_BLOCKED as SEALABILITY_POLICY_BLOCKED,
    SEALABILITY_CONTEXT_ERROR,
    RuntimePolicyAdmission,
)
from hwpxfiller.application.workbench_execution_status import (
    CHECKING,
    CONTEXT_ERROR,
    CURRENT,
    DOMAIN_BLOCKED,
    NO_EVIDENCE,
    POLICY_BLOCKED,
    STALE,
    WORKBENCH_EXECUTION_STATUS_CODES,
    derive_workbench_execution_status,
)

IDLE = AutomaticSealOrchestration()  # state=IDLE
CHECKING_ORCH = AutomaticSealOrchestration(state="CHECKING")
SETTLED = AutomaticSealOrchestration(state="SETTLED_CURRENT")
STALE_ORCH = AutomaticSealOrchestration(state="STALE")
FAILED_ORCH = AutomaticSealOrchestration(state="FAILED", consecutive_seal_failures=3)


# ── 각 상태의 대표 조합(R2: CURRENT/STALE/CHECKING/NO_EVIDENCE 는 orchestration 소스) ──────────
def test_no_evidence_when_idle_and_no_observation() -> None:
    assert derive_workbench_execution_status(orchestration=IDLE) == NO_EVIDENCE


def test_checking_when_orchestration_checking() -> None:
    assert derive_workbench_execution_status(orchestration=CHECKING_ORCH) == CHECKING


def test_current_when_orchestration_settled_current() -> None:
    assert derive_workbench_execution_status(orchestration=SETTLED) == CURRENT


def test_stale_when_orchestration_stale() -> None:
    assert derive_workbench_execution_status(orchestration=STALE_ORCH) == STALE


def test_stale_when_orchestration_failed() -> None:
    assert derive_workbench_execution_status(orchestration=FAILED_ORCH) == STALE


def test_domain_blocked_from_sealability() -> None:
    assert (
        derive_workbench_execution_status(
            orchestration=IDLE, current_work_sealability=SEALABILITY_DOMAIN_BLOCKED
        )
        == DOMAIN_BLOCKED
    )


def test_policy_blocked_from_sealability() -> None:
    assert (
        derive_workbench_execution_status(
            orchestration=IDLE, current_work_sealability=SEALABILITY_POLICY_BLOCKED
        )
        == POLICY_BLOCKED
    )


def test_context_error_from_admission() -> None:
    # fresh 축 실패는 ring2 가 admission=CONTEXT_ERROR 로 넘긴다 → CONTEXT_ERROR.
    assert (
        derive_workbench_execution_status(
            orchestration=SETTLED,
            admission=RuntimePolicyAdmission(state=ADMISSION_CONTEXT_ERROR, reasons=("X",)),
        )
        == CONTEXT_ERROR
    )


def test_context_error_from_sealability() -> None:
    assert (
        derive_workbench_execution_status(
            orchestration=IDLE, current_work_sealability=SEALABILITY_CONTEXT_ERROR
        )
        == CONTEXT_ERROR
    )


# ── 우선순위 계약(composer blocker 서열과 정합) ─────────────────────────────────────────────
def test_context_error_outranks_everything() -> None:
    # 다른 축이 정상이어도 CONTEXT_ERROR 하나면 CONTEXT_ERROR(fail-loud).
    assert (
        derive_workbench_execution_status(
            orchestration=CHECKING_ORCH,
            current_work_sealability=SEALABILITY_CONTEXT_ERROR,
        )
        == CONTEXT_ERROR
    )


def test_checking_outranks_domain_blocked() -> None:
    # 자동 재확인 중이면 sealability 의 DOMAIN_BLOCKED 위로 CHECKING 이 선다.
    assert (
        derive_workbench_execution_status(
            orchestration=CHECKING_ORCH,
            current_work_sealability=SEALABILITY_DOMAIN_BLOCKED,
        )
        == CHECKING
    )


def test_domain_blocked_outranks_current() -> None:
    # orchestration SETTLED 이어도 current Work 가 seal 불가면 DOMAIN_BLOCKED(막힌 항목이 반영 주장보다 우선).
    assert (
        derive_workbench_execution_status(
            orchestration=SETTLED,
            current_work_sealability=SEALABILITY_DOMAIN_BLOCKED,
        )
        == DOMAIN_BLOCKED
    )


def test_admission_not_admitted_alone_does_not_change_status() -> None:
    # §5 admission/readiness 는 별도 축이다 — NOT_ADMITTED 하나로 status 를 바꾸지 않는다
    # (SETTLED_CURRENT + NOT_ADMITTED 는 정상 S6-absent 상태다).
    status = derive_workbench_execution_status(
        orchestration=SETTLED,
        admission=RuntimePolicyAdmission(
            state=NOT_ADMITTED, reasons=("MATERIALIZATION_CONTRACT_NOT_ADMITTED",)
        ),
    )
    assert status == CURRENT


# ── 구조 계약 ────────────────────────────────────────────────────────────────────────────
def test_status_codes_are_exactly_seven_in_contract_order() -> None:
    assert WORKBENCH_EXECUTION_STATUS_CODES == (
        NO_EVIDENCE,
        CHECKING,
        CURRENT,
        STALE,
        DOMAIN_BLOCKED,
        POLICY_BLOCKED,
        CONTEXT_ERROR,
    )


def test_every_derivation_returns_a_declared_code() -> None:
    # 어떤 verdict 조합이든 반환은 항상 선언된 7 코드 중 하나(조용한 미지 상태 0).
    orchestrations = [IDLE, CHECKING_ORCH, SETTLED, STALE_ORCH, FAILED_ORCH]
    sealabilities = [
        None,
        SEALABILITY_DOMAIN_BLOCKED,
        SEALABILITY_POLICY_BLOCKED,
        SEALABILITY_CONTEXT_ERROR,
    ]
    admissions = [
        None,
        RuntimePolicyAdmission(state=ADMITTED),
        RuntimePolicyAdmission(state=NOT_ADMITTED, reasons=("R",)),
        RuntimePolicyAdmission(state=ADMISSION_CONTEXT_ERROR, reasons=("R",)),
    ]
    for orch in orchestrations:
        for seal in sealabilities:
            for adm in admissions:
                code = derive_workbench_execution_status(
                    orchestration=orch,
                    admission=adm,
                    current_work_sealability=seal,
                )
                assert code in WORKBENCH_EXECUTION_STATUS_CODES
