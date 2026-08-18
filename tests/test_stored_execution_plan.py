"""SealExecutionPlan terminal outcome 값 모델 — durable store 제거 후 순수 값 계약(S5F R2-04b-2 · #740).

content-addressed store·aggregate·codec·publication(CREATE/REUSE)은 사라졌다. 이 테스트는 남은
terminal outcome 값 모델(``ExecutionPlanSealed``·blocked·policy·stale)과 selector 의 fail-closed
검증만 확인한다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.stored_execution_plan import (
    ExecutionPlanOutcomeError,
    ExecutionPlanSealed,
    ExecutionPolicyBlocked,
    ExecutionQualificationBlocked,
    RequestedAuto,
    RequestedExact,
    SealTerminalOutcome,
    StaleExecutionBasis,
)


# ─── ExecutionPlanSealed(현재-value 성공, publication 없음) ─────────────────────────────
def test_sealed_outcome_carries_basis_identity() -> None:
    sealed = ExecutionPlanSealed(execution_basis_digest="sha256:basis")
    assert sealed.execution_basis_digest == "sha256:basis"
    assert isinstance(sealed, SealTerminalOutcome)  # union 멤버
    # durable publication 어휘를 싣지 않는다.
    for gone in ("publication_kind", "plan_semantic_digest", "captured_execution_input_digest"):
        assert not hasattr(sealed, gone)


def test_sealed_outcome_empty_basis_digest_rejected() -> None:
    with pytest.raises(ExecutionPlanOutcomeError):
        ExecutionPlanSealed(execution_basis_digest="")


# ─── ExecutionQualificationBlocked ────────────────────────────────────────────────────
def test_qualification_blocked_valid_and_fail_closed() -> None:
    blocked = ExecutionQualificationBlocked(
        capture_evidence_ref="sha256:ev", normalized_blockers=("ACTIVE_FIELD_UNBOUND",)
    )
    assert blocked.normalized_blockers == ("ACTIVE_FIELD_UNBOUND",)
    with pytest.raises(ExecutionPlanOutcomeError):
        ExecutionQualificationBlocked(capture_evidence_ref="", normalized_blockers=())
    with pytest.raises(ExecutionPlanOutcomeError):
        ExecutionQualificationBlocked(
            capture_evidence_ref="sha256:ev", normalized_blockers=("",)
        )


# ─── ExecutionPolicyBlocked ───────────────────────────────────────────────────────────
def test_policy_blocked_valid_and_fail_closed() -> None:
    pol = ExecutionPolicyBlocked(policy_code="QUALIFICATION_PROFILE_REVOKED")
    assert pol.policy_code == "QUALIFICATION_PROFILE_REVOKED"
    assert pol.qualification_profile_id is None
    with pytest.raises(ExecutionPlanOutcomeError):
        ExecutionPolicyBlocked(policy_code="")


# ─── StaleExecutionBasis ──────────────────────────────────────────────────────────────
def test_stale_valid_and_unknown_reason_rejected() -> None:
    stale = StaleExecutionBasis(
        captured_execution_input_digest="sha256:in",
        candidate_execution_basis_digest="sha256:basis",
        stale_reason="DIGEST_MISMATCH",
    )
    assert stale.stale_reason == "DIGEST_MISMATCH"
    with pytest.raises(ExecutionPlanOutcomeError):
        StaleExecutionBasis(
            captured_execution_input_digest="sha256:in",
            candidate_execution_basis_digest="sha256:basis",
            stale_reason="BOGUS_REASON",
        )
    with pytest.raises(ExecutionPlanOutcomeError):
        StaleExecutionBasis(
            captured_execution_input_digest="",
            candidate_execution_basis_digest="sha256:basis",
            stale_reason="DIGEST_MISMATCH",
        )


# ─── RequestedVersionSelector = AUTO | EXACT ─────────────────────────────────────────
def test_requested_selector_auto_and_exact() -> None:
    assert RequestedAuto() != RequestedExact("v1")  # AUTO 는 resolve 된 exact 와 다르다
    assert RequestedExact("v1").value == "v1"
    with pytest.raises(ExecutionPlanOutcomeError):
        RequestedExact("")
