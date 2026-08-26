"""blocker 어포던스의 **헤드리스 불변식**(#912 (b) 층) — 「지시했으면 수단을 실었는가」.

정적 표(``tests/repo_contract/test_blocker_affordance_registry.py``)는 선언과 실재의 대조만
본다. 그 층은 「그 blocker 가 실제로 선 상태에서 수단이 실려 나오는가」를 못 본다 — 규칙의
존재를 볼 뿐 결과를 못 본다. 그 결과를 여기서 잰다: 컨트롤러를 실제 상태로 몰아넣고 스냅샷
존이 무엇을 싣는지 되읽는다.

세 형태를 각각 잰다.

* ⓐ 활성 동사 — ``CONTEXT_ERROR``/``RECOVER_CONTEXT`` 의 복구 동사(#912 D4). 수리 전에는
  ``recover_action`` 키 자체가 없어 이 파일의 첫 단언이 **빨강**이었다.
* ⓑ 자동 진행 — ``EXECUTION_CHECKING`` 은 동사를 숨기지 않고 비활성 + 사유로 낸다.
* ⓒ 설계상 없음 — ``RUNTIME_NOT_ADMITTED``/``POLICY_BLOCKED`` 의 「환경」·「정책」 사유는
  **실제로 그 축이 거절했을 때만** 나온다(#928 이 뗀 사유 분리를 불변식으로 고정).

## 여기 없는 것

``CHOOSE_CONTENT ⇒ 고를 수 있는 갈래 ≥ 1`` 은 아직 세우지 않는다. 지금 제품은 재선택으로
고칠 수 없는 상태(``_UNSELECTABLE_STATUSES`` 만 남은 갈래)에서도 ``CHOOSE_CONTENT``(고르라)를
올리고 라디오는 옳게 비활성이라, 그 불변식은 **오늘 빨강**이다(#912 D3 · 수리는 #921). 지금
세우면 수리 없이 빨강이 상주해 게이트의 신호가 죽는다 — 그 수리와 **함께** 빨강→초록으로
세우는 것이 맞다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.application.automatic_seal_orchestration import (
    CHECKING,
    AutomaticSealOrchestration,
)
from hwpxfiller.application.document_creation_workbench import (
    _CHECKING_PHRASE,
    _CREATE_PREPARATION_DISABLED_PHRASE,
    _POLICY_DISABLED_PHRASE,
    _RUNTIME_DISABLED_PHRASE,
)
from hwpxfiller.application.fresh_execution_observation import (
    EXECUTION_BASE_NOT_ADMITTED,
    EXECUTION_EVIDENCE_NOT_OBSERVED,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    NOT_ADMITTED,
    ExecutionObservationContextError,
    RuntimePolicyAdmission,
)
from hwpxfiller.webapp.action_registry import ACTION_REGISTRY
from hwpxfiller.webapp.blocker_affordance import (
    ACTIVE_VERB,
    AUTOMATIC_PROGRESS,
    BLOCKER_AFFORDANCES,
)

# 공용 하네스는 같은 축을 이미 배선한 파일이 소유한다(실 SlotConfigurationProduct +
# SealExecutionPlanService 를 같은 authority root 로 세우는 `_controller`).
from tests.test_document_creation_workbench import _observation
from tests.test_webapp_job_binding_review import _controller, _zone


# ── ⓐ 활성 동사 — context error 의 복구 동사(#912 D4) ────────────────────────────────────────
def test_context_error_carries_an_enabled_recovery_verb(tmp_path: Path) -> None:
    """``kind == "context_error"`` 면 복구 동사가 **실리고 활성**이다.

    수리 전에는 이 존이 danger 문안(`detail`)과 비활성 생성 버튼만 냈다. 그것을 지울 동사는
    ``refresh_observation`` 인데 registry·핸들러 양쪽에 있으면서 화면에도 스냅샷에도 선 적이
    없었다 — 단방향 배선이다. 사용자가 보는 것은 「복원하지 못했습니다」 한 줄이고 다음
    행동이 없다.
    """
    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._last_fresh_observation = ExecutionObservationContextError("E_CTX", "복원 실패")
    zone = _zone(ctrl)
    assert zone["kind"] == "context_error"
    assert zone["primary_action"] == "RECOVER_CONTEXT"

    recover = zone["recover_action"]
    assert recover["enabled"] is True, "복구 동사가 비활성이면 다음 행동이 여전히 없다"
    assert recover["label"], "동사에 문안이 없으면 화면에서 빈 버튼이 된다"
    assert recover["disabled_reason"] is None

    # 확인 축의 동사는 이 자리에 서지 않는다 — 관찰이 무너졌는데 「현재 설정 확인」을 세우면
    # 두 동사가 같은 자리를 다툰다(어느 것이 이 상태를 지우는지 사용자가 못 고른다).
    assert zone.get("execution_action") is None


def test_the_recovery_verb_round_trips_through_the_registered_action(
    tmp_path: Path,
) -> None:
    """선언된 좌표(``job.refresh_observation``)가 실제로 이 상태를 지운다 — 왕복까지 잰다.

    표가 좌표를 옳게 적었는지는 정적 층이 보고, 그 좌표가 **정말 이 상태를 겨누는지**는
    여기서만 보인다. 등록·핸들러·표가 전부 있는데 서로 다른 것을 가리키는 자리가
    D4 의 형상이었다.
    """
    affordance = BLOCKER_AFFORDANCES["CONTEXT_ERROR"]
    assert affordance.kind == ACTIVE_VERB
    screen, _, action = str(affordance.dispatch_action).partition(".")
    assert action in ACTION_REGISTRY[screen]

    ctrl = _controller(tmp_path, with_binding=True)
    ctrl._last_fresh_observation = ExecutionObservationContextError("E_CTX", "복원 실패")
    assert _zone(ctrl)["kind"] == "context_error"

    ctrl.dispatch(action, {})
    # 다시 관찰이 성공했으므로 맥락 실패가 남아 있지 않다(조용한 유지 금지의 거울상).
    assert _zone(ctrl)["kind"] == "observation"


# ── ⓑ 자동 진행 — 숨기지 않고 비활성 + 사유 ─────────────────────────────────────────────────
def test_checking_keeps_the_verb_disabled_with_a_reason() -> None:
    """``EXECUTION_CHECKING`` 은 동사를 걷지 않는다 — 비활성 + 사유가 그 형태다.

    걷어 버리면 「설정을 확인하고 있습니다」가 지울 수단 없이 서고(=D1 의 형상), 활성으로
    두면 자동 확인이 도는 중에 같은 일을 또 시키는 버튼이 된다. 표의 :data:`AUTOMATIC_PROGRESS`
    가 선언하는 것이 정확히 이 중간 형태다.
    """
    assert BLOCKER_AFFORDANCES["EXECUTION_CHECKING"].kind == AUTOMATIC_PROGRESS
    observation = _observation(orchestration=AutomaticSealOrchestration(state=CHECKING))
    assert "EXECUTION_CHECKING" in observation.blockers
    assert observation.resolve_execution_disabled_reason == _CHECKING_PHRASE


# ── ⓒ 설계상 없음 — 「환경」·「정책」 사유는 그 축이 실제로 거절했을 때만 ───────────────────────
@pytest.mark.parametrize(
    ("reason", "expected_phrase", "expected_blocker"),
    [
        (MATERIALIZATION_CONTRACT_NOT_ADMITTED, _RUNTIME_DISABLED_PHRASE, "RUNTIME_NOT_ADMITTED"),
        (EXECUTION_BASE_NOT_ADMITTED, _POLICY_DISABLED_PHRASE, "POLICY_BLOCKED"),
    ],
)
def test_environment_grade_reasons_name_the_axis_that_actually_refused(
    reason: str, expected_phrase: str, expected_blocker: str
) -> None:
    """「환경」·「정책」 사유는 :data:`NO_VERB_BY_DESIGN` blocker 가 **실제로 설 때만** 나온다.

    사유와 형태가 갈리면 사용자는 지금 지울 수 있는 상태를 못 지우는 상태로 읽는다 — 동사가
    없는 것이 옳은 자리와 동사가 있어야 하는데 없는 자리가 같은 문장으로 말해지기 때문이다.
    #928 이 그 둘을 뗐고 여기가 그 분리를 불변식으로 고정한다.
    """
    observation = _observation(admission=RuntimePolicyAdmission(NOT_ADMITTED, (reason,)))
    assert expected_blocker in observation.blockers
    assert observation.create_documents_disabled_reason == expected_phrase


def test_unobserved_is_not_dressed_up_as_an_environment_refusal() -> None:
    """「아직 확인하지 않았다」는 거절이 아니라 재료 부재다 — 사유도 형태도 갈린다.

    ``EXECUTION_EVIDENCE_NOT_OBSERVED`` 는 ``NOT_ADMITTED`` 를 타고 오지만 runtime/policy 축이
    아니다. 그래서 blocker 는 동사가 있는 확인 축(``EXECUTION_NO_EVIDENCE``)으로 서고 사유는
    정직한 준비 폴백이다. 이 갈림이 무너지면 D1 이 그대로 되살아난다.
    """
    observation = _observation(
        admission=RuntimePolicyAdmission(NOT_ADMITTED, (EXECUTION_EVIDENCE_NOT_OBSERVED,))
    )
    assert "EXECUTION_NO_EVIDENCE" in observation.blockers
    assert "RUNTIME_NOT_ADMITTED" not in observation.blockers
    assert "POLICY_BLOCKED" not in observation.blockers
    assert observation.create_documents_disabled_reason == _CREATE_PREPARATION_DISABLED_PHRASE
    # 확인 축이 섰으니 그것을 지울 동사는 무장돼 있다(자동 확인 중이 아니므로 사유 없음).
    assert observation.resolve_execution_disabled_reason is None
