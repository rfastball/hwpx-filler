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

#: 원본 파일이 캡처된 applied bytes 와 갈렸는가 — **3상태**다(#932 B5). ``None`` 은 「안 갈렸다」가
#: 아니라 **판정 불성립**(미지원 매체·미부트스트랩)이고, ``unknown`` 은 「읽지 못해 모른다」다.
#: 셋을 섞지 않는 것이 이 상수들의 존재 이유다 — 모르는 것을 없는 것으로 접으면 그 접힘이 곧
#: 조용한 추측이고, 그 위에 세운 「숨김」은 사용자가 겪을 사실을 숨긴다.
SOURCE_DRIFT_CHANGED = "changed"
SOURCE_DRIFT_UNCHANGED = "unchanged"
SOURCE_DRIFT_UNKNOWN = "unknown"

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


def workbench_template_change_verdict(
    preparation_status: "str | None", source_drift: "str | None" = None
) -> "str | None":
    """제품 preparation status → 작업대 ``template_change_verdict``(``REVIEW_REQUIRED`` | ``None``).

    작업대 composer 의 ``REVIEW_TEMPLATE_CHANGE`` 축이 프로덕션에서 사문이던 것을 잇는 판정이다
    (#912 D2). 판정은 여기 한 곳이고 ring2 는 읽어 나르기만 한다 — 컨트롤러가 status 문자열을
    직접 분기하면 같은 상태를 템플릿 존과 작업대가 다르게 답하게 된다.

    Preparation 이 없으면(``None``) 그것만으로는 확인을 요구하지 않는다: 아직 한 번도 확인하지
    않은 작업은 적용된 템플릿이 곧 원본이라 대조할 변경이 없다.

    **원본 드리프트도 같은 요구를 세운다**(#932 B5). 생성은 캡처된 bytes 를 쓰므로(#681 F1)
    원본이 갈린 채 실행하면 「검토한 편집분이 반영 안 된 문서」가 조용히 나온다 — 존이 상시
    노출이던 때는 그 자리에 늘 단추가 있었지만, 조치가 있을 때만 서게 된 뒤로는 사용자가 그
    사실을 못 보고 지나갈 창이 생긴다. 그래서 드리프트를 실행 게이트로 승격한다: 막되
    좌초시키지 않는다 — 복구 동사(``#jobTplCheck``)는 같은 판정이 세우는 존 안에 있다.
    ``unknown``(값싸게 못 구함)도 같이 세운다. 모르는 채 캡처본으로 미는 것이 곧 조용한 추측이다.
    """
    if preparation_status in _UNSETTLED_PREPARATION_STATUSES:
        return REVIEW_REQUIRED
    if source_drift in (SOURCE_DRIFT_CHANGED, SOURCE_DRIFT_UNKNOWN):
        return REVIEW_REQUIRED
    return None


#: 확인이 **종결됐고 남은 조치가 없는** 제품 status. 존 노출 술어는 이 집합의 **여집합**을 묻는다
#: — 어휘에 새 status 가 늘면 기본이 「세움」이어야 조용히 사라지는 구획이 안 생긴다(#932 B5).
#: ``invalid``·``rejected`` 가 여기 있는 이유: 둘은 「기존 템플릿이 계속 쓰인다」는 종결 진술이고,
#: 그 상태에서 원본은 실제로 갈려 있으므로 존은 drift 축으로 어차피 선다(같은 사실을 두 축이
#: 각자 세우면 한쪽만 늙는다).
_SETTLED_PREPARATION_STATUSES: frozenset[str] = frozenset(
    {"no_change", "applied", "invalid", "rejected"}
)

_ZONE_ACTION_PREPARATION_STATUSES: frozenset[str] = frozenset(
    PRODUCT_PREPARATION_STATUSES
) - _SETTLED_PREPARATION_STATUSES


def template_change_zone_actionable(
    *,
    supported: bool,
    reason: str,
    preparation_status: "str | None",
    source_drift: "str | None",
) -> bool:
    """「템플릿 변경사항」 존을 세울 것인가 — #932 B5 판정의 **단 한 곳**.

    U4 12번(「0건이면 숨김」)이 그대로는 자기모순이었던 이유는 이 존이 결과 보고판이 아니라
    **스위치**였기 때문이다 — 건수를 알려면 확인을 돌려야 하는데 그 확인을 여는 단추가 존
    안에 있어서, 건수로 숨기면 확인을 개시할 방법이 사라진다. 그래서 술어의 입력은 「확인
    결과」가 아니라 **원본 드리프트**다: 확인을 안 눌러도 값싸게(digest) 아는 사실이라
    존이 자기 존재를 스스로 판정할 수 있다.

    세우는 갈래는 셋이다.

    - ``initialization_required`` — 초기 등록 실패. 비활성 + 진단 병기가 이 존의 몫이라 숨기면
      사용자는 자기 작업이 왜 안 도는지 물을 자리를 잃는다.
    - 미종결 preparation — ``ready``(적용이라는 미이행 동사)·``checking``(진행 중)과
      :data:`_UNSETTLED_PREPARATION_STATUSES` 여섯. 특히 후자는 ``REVIEW_TEMPLATE_CHANGE``
      blocker 가 서는 상태이고 그 복구 동사가 ``#jobTplCheck`` 라(``blocker_affordance``),
      여기서 숨기면 **없는 자리를 가리키는 지시**가 된다(#912 가 이름 붙인 결함류).
    - drift 가 ``changed``(조치 필요) 또는 ``unknown``(모른다 — 사유 병기하고 세운다).

    나머지 하나, 「부트스트랩됐고 원본 그대로이며 확인도 종결」에서만 숨는다. 웹이 든 결과
    재진술(적용 한 줄)까지 살피는 것은 표면 몫이다 — 재전송·재진술은 웹 소유라(#659).
    """
    if not supported:
        return False
    if reason == CAPABILITY_INITIALIZATION_REQUIRED:
        return True
    if preparation_status in _ZONE_ACTION_PREPARATION_STATUSES:
        return True
    return source_drift in (SOURCE_DRIFT_CHANGED, SOURCE_DRIFT_UNKNOWN)


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
