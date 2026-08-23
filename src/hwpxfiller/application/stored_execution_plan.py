"""SealExecutionPlan terminal outcome 값 모델 — durable store 없이 current value 로 산다(S5-10 · #706).

S5F R2-04b-2(#740): content-addressed durable Plan store(aggregate·plan record·codec·compilation
mapping·dependency retention·first-sealed provenance·CREATE/REUSE publication)를 **전부 제거**했다.
seal 은 durable Plan 을 남기지 않는다 — orchestration 은 current candidate 에서 직접 성공 결과를
반환한다. 이 모듈은 그 순수 값 모델만 소유한다:

- ``ExecutionPlanSealed`` — durable publication 없이 current candidate 에서 낸 seal 성공(현재-value).
  content-address·publication kind·plan record 가 없다. sealed current basis 의 identity 만 싣는다.
- ``ExecutionQualificationBlocked`` / ``ExecutionPolicyBlocked`` / ``StaleExecutionBasis`` — 나머지
  terminal 결과(전부 durable 하지 않고 fresh 로 되돌린다).

fail-closed: unknown stale_reason·빈 필드는 조용히 넘기지 않고 시끄럽게 닫는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# stale 사유 어휘 — S6-02(#810) start gate 가 같은 값을 재진술하므로 상수로 승격(값 불변).
DIGEST_MISMATCH = "DIGEST_MISMATCH"
CURRENT_BASIS_NOT_SEALABLE = "CURRENT_BASIS_NOT_SEALABLE"
_STALE_REASONS = frozenset({DIGEST_MISMATCH, CURRENT_BASIS_NOT_SEALABLE})


# ─── 오류 ────────────────────────────────────────────────────────────────────────────
class ExecutionPlanOutcomeError(Exception):
    """terminal outcome 값 모델의 loud failure(빈 필드·미상 어휘)."""

    code = "EXECUTION_PLAN_OUTCOME_ERROR"


def _require_str(value: object, what: str) -> str:
    # str() 강제 변환 금지 — null/number/list 를 조용히 문자열로 만들지 않고 fail-closed.
    if not isinstance(value, str) or value == "":
        raise ExecutionPlanOutcomeError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value


# ─── RequestedVersionSelector = AUTO | EXACT(value) ──────────────────────────────────
@dataclass(frozen=True)
class RequestedAuto:
    """서버 default 로 resolve 하라는 raw intent — resolve 된 exact 값과 동일 취급 금지."""


@dataclass(frozen=True)
class RequestedExact:
    """요청자가 못박은 exact contract/schema/encoding 값."""

    value: str

    def __post_init__(self) -> None:
        _require_str(self.value, "RequestedExact.value")


RequestedVersionSelector = RequestedAuto | RequestedExact


# ─── SealTerminalOutcome = 4 변형 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class ExecutionPlanSealed:
    """durable publication 없이 current candidate 에서 직접 반환하는 seal 성공(현재-value).

    content-addressed store·publication kind(CREATE/REUSE)·plan record·plan_semantic_digest 를
    싣지 않는다 — sealed current basis 의 identity(``execution_basis_digest``)만 담는다. 이 digest 는
    final gate 의 basis-equality staleness 판정이 이미 계산하는 값이라 parity·식별에 재사용한다.

    ``plan_payload``(S6-05 · #812)는 identity 가 아니라 **운반 화물**이다 — 방금 봉인된
    ``SealedExecutionPlanSemanticPayload`` 를 재판정 없이 materialization caller 까지 나른다.
    durable 로 남기지 않고(R2 #740 의 durable Plan store 제거는 유지), 세션이 basis digest 와
    같은 응답에서 함께 보관해 짝을 맞춘다.
    """

    execution_basis_digest: str
    plan_payload: Any | None = None

    def __post_init__(self) -> None:
        _require_str(self.execution_basis_digest, "execution_basis_digest")


@dataclass(frozen=True)
class ExecutionQualificationBlocked:
    capture_evidence_ref: str
    normalized_blockers: tuple[str, ...]
    captured_execution_input_digest: "str | None" = None
    captured_attempt_digest: "str | None" = None

    def __post_init__(self) -> None:
        _require_str(self.capture_evidence_ref, "capture_evidence_ref")
        if not all(isinstance(b, str) and b for b in self.normalized_blockers):
            raise ExecutionPlanOutcomeError("normalized_blockers 형식 불량")


@dataclass(frozen=True)
class ExecutionPolicyBlocked:
    policy_code: str
    qualification_profile_id: "str | None" = None
    observed_policy_version: "str | None" = None
    policy_observation_digest: "str | None" = None
    captured_attempt_digest: "str | None" = None

    def __post_init__(self) -> None:
        _require_str(self.policy_code, "policy_code")


@dataclass(frozen=True)
class StaleExecutionBasis:
    captured_execution_input_digest: str
    candidate_execution_basis_digest: str
    stale_reason: str  # DIGEST_MISMATCH | CURRENT_BASIS_NOT_SEALABLE
    observed_current_summary: "Mapping[str, Any] | None" = None

    def __post_init__(self) -> None:
        _require_str(
            self.captured_execution_input_digest, "captured_execution_input_digest"
        )
        _require_str(
            self.candidate_execution_basis_digest, "candidate_execution_basis_digest"
        )
        if self.stale_reason not in _STALE_REASONS:
            raise ExecutionPlanOutcomeError(f"stale_reason 미상: {self.stale_reason!r}")


SealTerminalOutcome = (
    ExecutionPlanSealed
    | ExecutionQualificationBlocked
    | ExecutionPolicyBlocked
    | StaleExecutionBasis
)
