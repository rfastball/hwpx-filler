"""legacy Job → S3 bootstrap 결과와 Configuration provenance 실행 guard — 순수 판정 (S3-08 #658).

legacy Job 의 integer ``template_revision``/``binding_revision`` 은 S3 의 immutable identity 가
아니다. bootstrap 은 read migration 이 아니라 명시 write command 이고(coordinator 가 진다), 여기는
그 결과 어휘와 **실행 진입 guard** 판정이다.

Template 적용 뒤 과거 Configuration/Plan 이 새 current Application 의 실행 권위로 조용히 재사용되지
않게 한다 — Configuration 의 base Application 이 current 와 다르거나 provenance 를 증명할 수 없으면
실행을 fail-closed 로 막는다(S3 는 구조 호환성을 추측하지 않는다; 그 판단은 S4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .work_template_state import WorkTemplateStateAggregate

# bootstrap 결과
BOOTSTRAP_OK = "BOOTSTRAP_OK"
TEMPLATE_INITIALIZATION_REQUIRED = "TEMPLATE_INITIALIZATION_REQUIRED"  # capture/qualify 실패 — repair

# 실행 provenance verdict
EXECUTION_ALLOWED = "EXECUTION_ALLOWED"
NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"  # base 가 current 와 불일치
NEEDS_CONFIGURATION_REVIEW = "NEEDS_CONFIGURATION_REVIEW"  # provenance 증명 불가(UNKNOWN)

# Configuration.base_template_application_id 가 증명 불가일 때 쓰는 sentinel.
UNKNOWN_APPLICATION = None


@dataclass(frozen=True)
class BootstrapOutcome:
    """bootstrap 명령 결과 — 성공이면 aggregate, 실패면 repair 진단 사유."""

    result: str
    aggregate: WorkTemplateStateAggregate | None = None
    reason: str | None = None


def evaluate_execution_provenance(
    configuration_base_application_id: "str | None",
    work_current_application_id: str,
) -> str:
    """실행 진입 guard — Configuration 의 base 가 current Application 과 exact 일치할 때만 허용.

    ``None`` 은 provenance 증명 불가(UNKNOWN) → NEEDS_CONFIGURATION_REVIEW(bootstrap A1 에 자동
    귀속하지 않는다). 알려진 다른 Application → NEEDS_CONFIGURATION(완료 시점 값으로 rebase 금지).
    """
    if configuration_base_application_id is UNKNOWN_APPLICATION:
        return NEEDS_CONFIGURATION_REVIEW
    if configuration_base_application_id != work_current_application_id:
        return NEEDS_CONFIGURATION
    return EXECUTION_ALLOWED
