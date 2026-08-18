"""작업대 execution status 7상태 파생 — 이미 내려진 verdict 의 **순수 재라벨** (SX-03 · #726 §3).

#726 §3 이 못박은 7 개 사용자 실행 상태 machine-code 를 **하나의 순수 함수**로 낸다:

    NO_EVIDENCE · CHECKING · CURRENT · STALE · DOMAIN_BLOCKED · POLICY_BLOCKED · CONTEXT_ERROR

**재판정 0 계약.** 이 모듈은 currentness·admission·sealability·orchestration 을 **다시 판정하지
않는다** — 이미 backend 권위가 내린 verdict 를 받아 그 관계를 하나의 코드로 **재라벨**할 뿐이다.
그 verdict 들의 정본은:

- orchestration 상태 — :mod:`hwpxfiller.application.automatic_seal_orchestration`
  (IDLE/CHECKING/SETTLED_CURRENT/STALE/FAILED). R2(#740): CURRENT/STALE/CHECKING/NO_EVIDENCE 는
  이 축이 나른다(currentness 축이 흡수됐다 — current value 는 자명히 현재).
- runtime-policy admission / current-work sealability —
  :mod:`hwpxfiller.application.fresh_execution_observation`
  (:class:`RuntimePolicyAdmission` · sealability 어휘). DOMAIN/POLICY/CONTEXT 축을 나른다.

여기서 새 durable state·새 semantic 을 만들지 않는다(#726 즉시 상향: "테스트 완화로만 green" 과
같은 계열의 hollow measurement 금지). store/webapp/gui 를 import 하지 않는다(ring 경계).

**7상태 machine-code 는 이 모듈이 소유한다**(vocabulary 무변경 — 이건 사용자 문안이 아니라 wire
코드다). 사용자 문안 매핑은 :mod:`hwpxfiller.application.document_creation_vocabulary` 및
workbench composer 가 진다. 정의 순서가 계약이다(``scripts/gen_bridge_contract.py`` 가 이 tuple 을
방출해 Python↔TypeScript parity 를 지킨다).
"""

from __future__ import annotations

from hwpxfiller.application.automatic_seal_orchestration import (
    CHECKING as ORCHESTRATION_CHECKING,
    FAILED as ORCHESTRATION_FAILED,
    SETTLED_CURRENT as ORCHESTRATION_SETTLED_CURRENT,
    STALE as ORCHESTRATION_STALE,
    AutomaticSealOrchestration,
)
from hwpxfiller.application.fresh_execution_observation import (
    ADMISSION_CONTEXT_ERROR,
    DOMAIN_BLOCKED as SEALABILITY_DOMAIN_BLOCKED,
    POLICY_BLOCKED as SEALABILITY_POLICY_BLOCKED,
    SEALABILITY_CONTEXT_ERROR,
    RuntimePolicyAdmission,
)

# ─── 7상태 machine-code(정의 순서 = 계약) ───────────────────────────────────────────────
NO_EVIDENCE = "NO_EVIDENCE"  # 현재 설정을 확인해야 합니다 — 아직 확인 증거 없음(orchestration IDLE)
CHECKING = "CHECKING"  # 현재 설정을 확인하고 있습니다 — automatic seal 진행 중
CURRENT = "CURRENT"  # 현재 설정이 반영됐습니다
STALE = "STALE"  # 설정이 바뀌어 다시 확인해야 합니다
DOMAIN_BLOCKED = "DOMAIN_BLOCKED"  # 확인할 항목이 있습니다 — current Work 가 domain 상 seal 불가
POLICY_BLOCKED = "POLICY_BLOCKED"  # 현재 이 구성으로 실행을 준비할 수 없습니다
CONTEXT_ERROR = "CONTEXT_ERROR"  # 현재 실행 상태를 확인할 수 없습니다

#: 정의 순서가 계약이다(gen 스크립트가 방출).
WORKBENCH_EXECUTION_STATUS_CODES: tuple[str, ...] = (
    NO_EVIDENCE,
    CHECKING,
    CURRENT,
    STALE,
    DOMAIN_BLOCKED,
    POLICY_BLOCKED,
    CONTEXT_ERROR,
)

#: 7상태 → 사용자 문안(#726 §3 리터럴). 이 문안이 execution status 축의 **정본**이고, 코드+문안을
#: 한 곳에 둬 두 자리가 같은 상태를 다르게 부르지 않게 한다. 내부어(Slot/Plan/Sealed/digest)를
#: 담지 않는다(#725 §테스트 12 계약과 정합).
WORKBENCH_EXECUTION_STATUS_PHRASE: dict[str, str] = {
    NO_EVIDENCE: "현재 설정을 확인해야 합니다",
    CHECKING: "현재 설정을 확인하고 있습니다",
    CURRENT: "현재 설정이 반영됐습니다",
    STALE: "설정이 바뀌어 다시 확인해야 합니다",
    DOMAIN_BLOCKED: "확인할 항목이 있습니다",
    POLICY_BLOCKED: "현재 이 구성으로 실행을 준비할 수 없습니다",
    CONTEXT_ERROR: "현재 실행 상태를 확인할 수 없습니다",
}


def _has_context_error(
    admission: RuntimePolicyAdmission | None,
    current_work_sealability: str | None,
) -> bool:
    """어느 축이든 CONTEXT_ERROR verdict 면 True — 재판정 아니라 이미 내려진 상태 읽기."""
    if admission is not None and admission.state == ADMISSION_CONTEXT_ERROR:
        return True
    if current_work_sealability == SEALABILITY_CONTEXT_ERROR:
        return True
    return False


def derive_workbench_execution_status(
    *,
    orchestration: AutomaticSealOrchestration,
    admission: RuntimePolicyAdmission | None = None,
    current_work_sealability: str | None = None,
) -> str:
    """이미 내려진 verdict → 7상태 machine-code(재판정 0, 재라벨만).

    입력은 전부 backend 권위가 이미 판정한 값이다. **R2(#740): currentness 축은 orchestration 으로
    흡수됐다** — CURRENT/STALE/CHECKING/NO_EVIDENCE 는 orchestration 상태가 나르고, fresh observation
    은 DOMAIN/POLICY/CONTEXT 축만 나른다(current value 는 자명히 현재라 별도 currentness 가 없다):

    - ``orchestration`` — automatic seal 진행 상태(필수). CURRENT=SETTLED_CURRENT, STALE=STALE/FAILED,
      CHECKING=CHECKING, NO_EVIDENCE=IDLE.
    - ``admission`` — runtime-policy admission verdict(CONTEXT_ERROR 만 status 축에 영향;
      NOT_ADMITTED/ADMITTED 자체는 §5 의 **별도** admission/readiness 축이라 여기서 status 를
      바꾸지 않는다). fresh observation 축 실패(ExecutionObservationContextError)도 ring2 가
      admission=CONTEXT_ERROR 로 넘긴다.
    - ``current_work_sealability`` — current-work fresh observation 의 sealability
      (DOMAIN_BLOCKED/POLICY_BLOCKED/CONTEXT_ERROR). sealable/관찰 없음이면 ``None``.

    우선순위(composer 의 blocker 서열과 정합 — 재구현 아님):

    1. **CONTEXT_ERROR** — 어느 축이든 CONTEXT_ERROR verdict(fail-loud, 사용자 blocker 로 낮추지
       않는다는 계약과 정합).
    2. **CHECKING** — automatic seal 진행 중(orchestration CHECKING).
    3. **DOMAIN_BLOCKED / POLICY_BLOCKED** — current Work sealability 가 막혔다.
    4. **STALE** — orchestration STALE/FAILED(basis 가 움직였다·자동 확인이 stale/실패로 끝났다).
       CURRENT 보다 앞선다(설정 변화가 반영 주장보다 우선).
    5. **CURRENT** — orchestration SETTLED_CURRENT(반영됨).
    6. **NO_EVIDENCE** — 그 밖(orchestration IDLE): 아직 확인 증거 없음.
    """
    if _has_context_error(admission, current_work_sealability):
        return CONTEXT_ERROR
    if orchestration.state == ORCHESTRATION_CHECKING:
        return CHECKING
    if current_work_sealability == SEALABILITY_DOMAIN_BLOCKED:
        return DOMAIN_BLOCKED
    if current_work_sealability == SEALABILITY_POLICY_BLOCKED:
        return POLICY_BLOCKED
    if orchestration.state in (ORCHESTRATION_STALE, ORCHESTRATION_FAILED):
        return STALE
    if orchestration.state == ORCHESTRATION_SETTLED_CURRENT:
        return CURRENT
    return NO_EVIDENCE


__all__ = [
    "NO_EVIDENCE",
    "CHECKING",
    "CURRENT",
    "STALE",
    "DOMAIN_BLOCKED",
    "POLICY_BLOCKED",
    "CONTEXT_ERROR",
    "WORKBENCH_EXECUTION_STATUS_CODES",
    "WORKBENCH_EXECUTION_STATUS_PHRASE",
    "derive_workbench_execution_status",
]
