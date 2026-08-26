"""Prepare/Apply 제품 status 투영 — 내부 어휘 → opaque Product Contract (S3-09 #659).

내부 aggregate 는 Preparation 15상태·Change 5상태·Apply 7결과를 각자 소유한다. 제품 표면은
그중 무엇도 그대로 내보내지 않는다 — 이 모듈이 **단 한 곳에서** 제품 status 로 투영하고,
계약 생성기(`scripts/gen_bridge_contract.py`)가 아래 어휘 튜플을 TypeScript union 으로
발행한다(Python·TS 가 status 문자열을 각자 손으로 관리하지 않는다).

투영 규칙 두 가지가 이 모듈의 존재 이유다:

- ``PREP_APPLIED`` 는 사어다 — apply 는 Change 를 APPLIED 로 찍고 Preparation 은 READY 로
  남긴다(S3-07). 그래서 READY Preparation 의 제품 status 는 **그 Change 의 상태에서** 파생한다.
- infrastructure/integrity/authorization 실패는 정상 domain status 가 아니다 —
  ``APPLY_INTEGRITY_ERROR`` 는 여기 투영표에 없고 호출자가 오류 경로로 분리한다(#659).

순수 모듈: I/O·store·token 발급 없음(그건 webapp 코디네이터 몫).
"""

from __future__ import annotations

from typing import Any

from .prepare_orchestration import (
    APPLY_ALREADY_APPLIED,
    APPLY_APPLIED,
    APPLY_APPLIED_THEN_ADVANCED,
    APPLY_CONFLICT,
    APPLY_REJECTED,
    APPLY_SUPERSEDED,
)
from .selection_compatibility import REVIEW_REQUIRED
from .work_template_state import (
    CHANGE_APPLIED,
    CHANGE_CONFLICTED,
    CHANGE_PREPARED,
    CHANGE_REJECTED,
    CHANGE_SUPERSEDED,
    PREP_APPLIED,
    PREP_BASE_CHANGED,
    PREP_CAPTURE_ERROR,
    PREP_CAPTURING,
    PREP_CONFLICTED,
    PREP_INTERRUPTED,
    PREP_NO_CHANGE,
    PREP_PROFILE_REVOKED,
    PREP_QUALIFICATION_ERROR,
    PREP_QUALIFICATION_FAILED,
    PREP_QUALIFYING,
    PREP_READY,
    PREP_REJECTED,
    PREP_SOURCE_BINDING_CHANGED,
    PREP_SUPERSEDED,
    TemplateChangePreparation,
)

# ─── 제품 status 어휘(계약 정본 — 생성기가 이 튜플을 TS union 으로 발행) ─────

PRODUCT_PREPARATION_STATUSES = (
    "checking",
    "ready",
    "no_change",
    "invalid",
    "error",
    "interrupted",
    "source_changed",
    "changed_while_checking",
    "superseded",
    "applied",
    "conflict",
    "rejected",
)

PRODUCT_APPLY_STATUSES = (
    "applied",
    "already_applied",
    "applied_then_advanced",
    "conflict",
    "superseded",
    "rejected",
)

# Preparation 이 capability 밖일 때 UI 가 받는 사유 코드(회귀 계약 #659).
CAPABILITY_UNSUPPORTED_MEDIA = "unsupported_media"
CAPABILITY_INITIALIZATION_REQUIRED = "initialization_required"

# ─── 내부 → 제품 투영표 ──────────────────────────────────────────────────────

_PREP_TO_PRODUCT = {
    PREP_CAPTURING: "checking",
    PREP_QUALIFYING: "checking",
    PREP_SUPERSEDED: "superseded",
    PREP_APPLIED: "applied",  # 사어지만 어휘에 있는 한 투영은 닫아 둔다
    PREP_CONFLICTED: "conflict",
    PREP_REJECTED: "rejected",
    PREP_CAPTURE_ERROR: "error",
    PREP_SOURCE_BINDING_CHANGED: "source_changed",
    PREP_QUALIFICATION_FAILED: "invalid",
    PREP_QUALIFICATION_ERROR: "error",
    PREP_INTERRUPTED: "interrupted",
    PREP_BASE_CHANGED: "changed_while_checking",
    PREP_PROFILE_REVOKED: "rejected",
    PREP_NO_CHANGE: "no_change",
}

_READY_CHANGE_TO_PRODUCT = {
    CHANGE_PREPARED: "ready",
    CHANGE_APPLIED: "applied",
    CHANGE_SUPERSEDED: "superseded",
    CHANGE_CONFLICTED: "conflict",
    CHANGE_REJECTED: "rejected",
}

_APPLY_TO_PRODUCT = {
    APPLY_APPLIED: "applied",
    APPLY_ALREADY_APPLIED: "already_applied",
    APPLY_APPLIED_THEN_ADVANCED: "applied_then_advanced",
    APPLY_CONFLICT: "conflict",
    APPLY_SUPERSEDED: "superseded",
    APPLY_REJECTED: "rejected",
}


class TemplateChangeProjectionError(ValueError):
    """투영표 밖 내부 상태 — 조용한 기본값 대신 시끄럽게 실패한다."""


def product_preparation_status(
    preparation: TemplateChangePreparation, change_status: "str | None"
) -> str:
    """내부 Preparation(+그 Change) 상태 → 제품 status.

    READY 는 Change 상태로 세분한다 — apply·supersede·conflict 가 Preparation 을 되찍지
    않는 것이 S3-07 의 계약이라, READY 만 보면 applied/superseded 를 ready 로 오보한다.
    """
    if preparation.status == PREP_READY:
        if change_status is None:
            raise TemplateChangeProjectionError(
                f"READY Preparation {preparation.preparation_id} 에 Change 상태가 없다"
            )
        product = _READY_CHANGE_TO_PRODUCT.get(change_status)
    else:
        product = _PREP_TO_PRODUCT.get(preparation.status)
    if product is None:
        raise TemplateChangeProjectionError(
            f"투영표 밖 상태: prep={preparation.status!r} change={change_status!r}"
        )
    return product


#: 확인이 **종결되지 않아** 다시 확인해야 하는 제품 status(#912 D2). 셋을 가르는 기준은 하나다:
#: 「지금 '변경사항 확인'을 누르면 이 상태가 지워지는가」.
#:
#: - 여기 드는 여섯은 전부 확인 도중·직후에 무언가 어긋나 결론이 없는 상태이고, 재확인이 곧 해소다.
#: - ``ready`` 는 결론이 있고 해소 동사가 **적용**이라 여기 없다. 확인만으로 지워지지 않는 상태를
#:   확인 요구로 세우면 「적용하기 싫은 변경」이 생성을 영영 막는 막다른 길이 된다(#804 부류).
#: - ``no_change``·``applied`` 는 종결이고, ``invalid``·``rejected`` 는 「기존 템플릿이 계속
#:   쓰인다」는 종결 진술이라 생성을 막을 근거가 아니다.
#: - ``checking`` 은 진행 중이라 사용자 조치가 아니다.
_UNSETTLED_PREPARATION_STATUSES: frozenset[str] = frozenset(
    {
        "error",
        "interrupted",
        "conflict",
        "source_changed",
        "changed_while_checking",
        "superseded",
    }
)


def workbench_template_change_verdict(preparation_status: "str | None") -> "str | None":
    """제품 preparation status → 작업대 ``template_change_verdict``(``REVIEW_REQUIRED`` | ``None``).

    작업대 composer 의 ``REVIEW_TEMPLATE_CHANGE`` 축이 프로덕션에서 사문이던 것을 잇는 판정이다
    (#912 D2). 판정은 여기 한 곳이고 ring2 는 읽어 나르기만 한다 — 컨트롤러가 status 문자열을
    직접 분기하면 같은 상태를 템플릿 존과 작업대가 다르게 답하게 된다.

    Preparation 이 없으면(``None``) 확인을 요구하지 않는다: 아직 한 번도 확인하지 않은 작업은
    적용된 템플릿이 곧 원본이라 대조할 변경이 없다. 그 상태에서 원본이 실제로 편집됐다면
    :meth:`~hwpxfiller.webapp.template_change.TemplateChangeCoordinator.source_drift_note` 가
    따로 시끄럽게 말한다.
    """
    if preparation_status in _UNSETTLED_PREPARATION_STATUSES:
        return REVIEW_REQUIRED
    return None


def product_apply_status(apply_result: str) -> str:
    """내부 ApplyOutcome.result → 제품 status. INTEGRITY_ERROR 는 domain status 가 아니라 여기 없다."""
    product = _APPLY_TO_PRODUCT.get(apply_result)
    if product is None:
        raise TemplateChangeProjectionError(f"투영표 밖 apply 결과: {apply_result!r}")
    return product


def preparation_view(
    preparation: TemplateChangePreparation,
    change_status: "str | None",
    *,
    preparation_token: str,
    change_token: "str | None",
    diagnostics: "tuple[tuple[str, str], ...]" = (),
) -> dict[str, Any]:
    """JSON-safe TemplateChangePreparationView — 내부 ID·revision·base·경로를 내보내지 않는다.

    ``diagnostics`` 는 (kind, message) 쌍이다 — capture 실패 사유는 Preparation 에, FAIL
    진단은 Evidence 에 살아서 **조립은 store 를 아는 코디네이터가** 하고 여기는 형태만 안다.
    ``change_token`` 은 제품 status 가 ``ready`` 일 때만 실린다(#659 계약). 호출자가 넘겼어도
    ready 가 아니면 버린다 — stale token 이 다른 상태에 실려 나가는 경로를 구조로 막는다.
    """
    status = product_preparation_status(preparation, change_status)
    return {
        "preparation_token": preparation_token,
        "status": status,
        "change_token": change_token if status == "ready" else None,
        "diagnostics": [{"kind": kind, "message": message} for kind, message in diagnostics],
        "prepared_at": preparation.completed_at,
    }
