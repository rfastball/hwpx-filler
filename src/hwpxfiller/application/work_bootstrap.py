"""legacy Job → S3 bootstrap 결과 어휘 — 순수 판정 (S3-08 #658).

legacy Job 의 integer ``template_revision``/``binding_revision`` 은 S3 의 immutable identity 가
아니다. bootstrap 은 read migration 이 아니라 명시 write command 이고(coordinator 가 진다), 여기는
그 결과 어휘다.

Template 적용 뒤 과거 구성이 새 current Application 의 실행 권위로 조용히 재사용되지 않게 하는
판정은 managed 생성이 current Application 의 Field Binding 판본으로 진다(#1081 PR2 — 종전의
provenance guard 는 slot 없는 legacy admission 과 함께 사라졌다).
"""

from __future__ import annotations

from dataclasses import dataclass

from .work_template_state import WorkTemplateStateAggregate

# bootstrap 결과
BOOTSTRAP_OK = "BOOTSTRAP_OK"
TEMPLATE_INITIALIZATION_REQUIRED = "TEMPLATE_INITIALIZATION_REQUIRED"  # capture/qualify 실패 — repair

# 실행 구성 verdict 어휘 — 실행 캡처(:mod:`execution_capture`)가 재사용한다. 생성 진입의
# provenance 판정 함수는 slot 없는 legacy admission 과 함께 사라졌다(#1081 PR2): managed
# 생성은 current Application 의 Field Binding 판본으로 같은 사실을 닫는다.
NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"  # base 가 current 와 불일치
NEEDS_CONFIGURATION_REVIEW = "NEEDS_CONFIGURATION_REVIEW"  # provenance 증명 불가(UNKNOWN)


@dataclass(frozen=True)
class BootstrapOutcome:
    """bootstrap 명령 결과 — 성공이면 aggregate, 실패면 repair 진단 사유."""

    result: str
    aggregate: WorkTemplateStateAggregate | None = None
    reason: str | None = None
