"""automatic qualification/seal orchestration 의 상태 모델 + 전이 규칙 (SX-01 · #724 §4 · #719 D2).

**순수 상태 기계 계약**이다 — store/webapp/gui/타이머/스레드/실 seal 실행을 모른다. effective
execution basis 가 바뀌었는지의 **판정은 backend**(:mod:`hwpxfiller.webapp.seal_execution_plan_product`
의 ``_classify_currentness`` / :mod:`hwpxfiller.application.fresh_execution_observation`)가 소유하므로,
이 모듈은 그 판정을 **이미 내려진 입력 플래그**(``effective_basis_changed: bool`` 등)로 받는다 —
currentness/basis 를 직접 계산하지 않는다. 실제 트리거 배선은 SX-02 소관이다.

**소유하는 것 셋.**

1. **orchestration 상태 어휘**(§4: 검사 중/반영됨/다시 확인 필요/stale 하여 갱신).
2. **순수 전이 함수** — durable command 결과·backend basis 판정·현재 상태·연속 실패 수를 받아 다음
   상태와 "automatic seal 을 시작해야 하는가"를 낸다. 규율을 인코딩한다:

   - durable commit 성공 + ``effective_basis_changed=True`` → automatic qualification/seal 시작(CHECKING).
   - ``effective_basis_changed=False``(detached/inactive-only same basis) → **blanket reseal 금지**,
     CURRENT 유지.
   - CHECKING 동안 **Plan-affecting 입력만** 잠시 비활성화(플래그), 전역 잠금 아님.
   - stale/failure 뒤 **무한 자동 재시도 금지** — 실패 상한 도달 시 수동 복구 요구를 상태로 표현.
   - 연속 변경 짧게 coalesce 가능(coalescing 의도를 플래그로 표현하되 실제 타이머는 만들지 않는다).

3. **사용자에게 Plan/Seal 관리 동사를 노출하지 않는다는 계약** — 이 모듈은 seal now/reseal/publish
   같은 **수동 seal 동사를 export 하지 않는다**. 전이 함수는 사건에 대한 반응이지 사용자 동사가
   아니다. :func:`request_manual_recovery` 는 실패 상태에서 벗어나는 복구 reset 이지 seal 관리가
   아니다.

사용자 문안은 vocabulary 와 정합한다: ``SETTLED_CURRENT`` ↔ ``Plan current``,
``STALE`` ↔ ``Plan stale``(:data:`ORCHESTRATION_USER_PHRASE`). CHECKING/IDLE/FAILED 의 사용자 문안은
downstream(workbench)이 소유한다 — 여기서 새 사용자 한국어 문안을 발명하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from hwpxfiller.application.document_creation_vocabulary import USER_VOCABULARY

# ─── orchestration 상태 어휘(#724 §4) ───────────────────────────────────────────────────────
IDLE = "IDLE"  # 아직 자동 seal 궤도에 오르지 않음
CHECKING = "CHECKING"  # 검사 중 — automatic qualification/seal 진행(blocker EXECUTION_CHECKING)
SETTLED_CURRENT = "SETTLED_CURRENT"  # 반영됨 — Plan current(USER_VOCABULARY["Plan current"])
STALE = "STALE"  # 다시 확인 필요 — Plan stale(blocker EXECUTION_STALE)
FAILED = "FAILED"  # stale/실패 뒤 수동 복구 요구(무한 자동 재시도 금지)

#: 정의 순서가 계약이다.
ORCHESTRATION_STATES: tuple[str, ...] = (IDLE, CHECKING, SETTLED_CURRENT, STALE, FAILED)

#: 사용자 문안을 가진 두 상태만 vocabulary 정본에 정합시킨다(나머지는 downstream 소유).
ORCHESTRATION_USER_PHRASE: dict[str, str] = {
    SETTLED_CURRENT: USER_VOCABULARY["Plan current"],
    STALE: USER_VOCABULARY["Plan stale"],
}

#: 연속 seal 실패 상한 — 도달 시 FAILED(수동 복구 요구). 무한 자동 재시도를 금지하는 상한이다.
DEFAULT_MAX_CONSECUTIVE_SEAL_FAILURES = 3


@dataclass(frozen=True)
class AutomaticSealOrchestration:
    """orchestration 상태 값 — durable current state 가 아니라 session 진행 상태의 순수 값 모델.

    ``consecutive_seal_failures`` 는 상한 대비용이고, ``coalescing_pending`` 은 CHECKING 중 도착한
    basis 변경을 **타이머 없이** 이어붙이려는 의도 플래그다(settle 때 소비).
    """

    state: str = IDLE
    consecutive_seal_failures: int = 0
    coalescing_pending: bool = False

    def __post_init__(self) -> None:
        if self.state not in ORCHESTRATION_STATES:
            raise ValueError(f"미지원 orchestration state: {self.state!r}")
        if self.consecutive_seal_failures < 0:
            raise ValueError("consecutive_seal_failures 는 음수가 될 수 없다")

    @property
    def plan_affecting_inputs_locked(self) -> bool:
        """CHECKING 동안 **Plan-affecting 입력만** 잠근다 — 전역 잠금이 아니다(#724 §4)."""
        return self.state == CHECKING

    @property
    def global_lock(self) -> bool:
        """전역 잠금은 결코 걸지 않는다 — 데이터 탐색·이력·일반 navigation 은 항상 열려 있다."""
        return False

    @property
    def requires_manual_recovery(self) -> bool:
        """FAILED 는 수동 복구 전까지 자동 재시도하지 않는다."""
        return self.state == FAILED


@dataclass(frozen=True)
class OrchestrationTransition:
    """전이 결과 — 다음 상태 + 이 전이가 automatic seal 을 시작해야 하는지.

    ``should_start_seal`` 은 **오직 fresh durable command + effective_basis_changed=True** 에만
    True 다 — 상태 기계가 자기 자신을 재시도로 몰지 않는다(무한 자동 재시도 금지).
    """

    next_state: AutomaticSealOrchestration
    should_start_seal: bool


def on_durable_command_settled(
    current: AutomaticSealOrchestration,
    *,
    durable_command_succeeded: bool,
    effective_basis_changed: bool,
) -> OrchestrationTransition:
    """durable authority command 성공 뒤 backend basis 판정을 받아 다음 상태를 판정한다.

    ``effective_basis_changed`` 는 **backend 판정 결과**(``_classify_currentness`` 의 effective-only
    equality)이지 이 함수가 계산하는 값이 아니다.

    규율:

    - command 실패 → seal 시작 안 함, 상태 유지(반응할 basis 변경이 없다).
    - 성공 + ``effective_basis_changed=True``:
        - 이미 CHECKING 이면 두 번째 seal 을 동시에 띄우지 않고 **coalescing_pending** 만 세운다
          (연속 변경 coalesce — 타이머 없음). ``should_start_seal=False``.
        - FAILED 면 자동 재시도하지 않는다 — 수동 복구 전까지 FAILED 유지. ``should_start_seal=False``.
        - 그 밖(IDLE/SETTLED_CURRENT/STALE)에서는 CHECKING 으로 진입하고 ``should_start_seal=True``.
    - 성공 + ``effective_basis_changed=False``(detached/inactive-only same basis):
        - **blanket reseal 금지**. CHECKING 중이면 그대로 두고, 그 외에는 CURRENT 유지(SETTLED_CURRENT).
          ``should_start_seal=False``.
    """
    if not durable_command_succeeded:
        return OrchestrationTransition(current, should_start_seal=False)

    if effective_basis_changed:
        if current.state == FAILED:
            # 무한 자동 재시도 금지 — 수동 복구 전까지 FAILED 를 벗어나지 않는다.
            return OrchestrationTransition(current, should_start_seal=False)
        if current.state == CHECKING:
            # 진행 중 seal 위에 두 번째를 겹치지 않고 coalesce 의도만 표시(타이머 없음).
            return OrchestrationTransition(
                replace(current, coalescing_pending=True), should_start_seal=False
            )
        return OrchestrationTransition(
            AutomaticSealOrchestration(
                state=CHECKING,
                consecutive_seal_failures=current.consecutive_seal_failures,
                coalescing_pending=False,
            ),
            should_start_seal=True,
        )

    # same effective basis → blanket reseal 하지 않는다.
    if current.state == CHECKING:
        return OrchestrationTransition(current, should_start_seal=False)
    return OrchestrationTransition(
        replace(current, state=SETTLED_CURRENT, coalescing_pending=False),
        should_start_seal=False,
    )


def on_seal_settled(
    current: AutomaticSealOrchestration,
    *,
    seal_succeeded: bool,
    resulting_currentness_current: bool,
    max_consecutive_seal_failures: int = DEFAULT_MAX_CONSECUTIVE_SEAL_FAILURES,
) -> OrchestrationTransition:
    """진행 중 automatic seal 이 끝났을 때의 전이. ``resulting_currentness_current`` 는 backend 판정.

    - CHECKING 이 아닌데 호출되면 no-op(상태 유지).
    - 성공 + current: SETTLED_CURRENT, 실패 수 0 으로 reset.
        - 단, seal 도중 새 basis 변경이 coalesce 대기 중이면 곧바로 다시 CHECKING(coalescing 소비,
          ``should_start_seal=True``) — 사용자 변경에 의한 것이라 무한 자동 재시도가 아니다.
    - 성공했지만 여전히 stale(basis 가 또 움직임): STALE. 자동으로 다시 seal 하지 않는다.
    - 실패: 연속 실패 수 +1. 상한 도달 시 FAILED(수동 복구), 그 전이면 STALE. 어느 쪽도 자동 재시도
      하지 않는다.
    """
    if current.state != CHECKING:
        return OrchestrationTransition(current, should_start_seal=False)

    if seal_succeeded and resulting_currentness_current:
        if current.coalescing_pending:
            # coalesce 대기 중이던 사용자 변경을 이제 이어서 검사한다.
            return OrchestrationTransition(
                AutomaticSealOrchestration(
                    state=CHECKING,
                    consecutive_seal_failures=0,
                    coalescing_pending=False,
                ),
                should_start_seal=True,
            )
        return OrchestrationTransition(
            AutomaticSealOrchestration(
                state=SETTLED_CURRENT,
                consecutive_seal_failures=0,
                coalescing_pending=False,
            ),
            should_start_seal=False,
        )

    if seal_succeeded and not resulting_currentness_current:
        # seal 은 됐지만 그 사이 basis 가 또 움직였다 — stale 로 알리고 자동 재시도하지 않는다.
        return OrchestrationTransition(
            AutomaticSealOrchestration(
                state=STALE,
                consecutive_seal_failures=0,
                coalescing_pending=False,
            ),
            should_start_seal=False,
        )

    # 실패 — 연속 실패 수를 올리고 상한에서 수동 복구로 전환한다(무한 자동 재시도 금지).
    failures = current.consecutive_seal_failures + 1
    next_state = FAILED if failures >= max_consecutive_seal_failures else STALE
    return OrchestrationTransition(
        AutomaticSealOrchestration(
            state=next_state,
            consecutive_seal_failures=failures,
            coalescing_pending=False,
        ),
        should_start_seal=False,
    )


def request_manual_recovery(
    current: AutomaticSealOrchestration,
) -> AutomaticSealOrchestration:
    """FAILED 에서 벗어나는 수동 복구 reset — 실패 수를 0 으로 되돌리고 IDLE 로.

    이것은 Plan/Seal **관리 동사가 아니다**(seal now/reseal/publish 를 노출하지 않는다). 실패 상태의
    수동 복구를 상태로 표현하려는 것뿐이다(#724 §4: "수동 복구 요구를 상태로 표현"). FAILED 가 아니면
    상태를 바꾸지 않는다.
    """
    if current.state != FAILED:
        return current
    return AutomaticSealOrchestration(
        state=IDLE, consecutive_seal_failures=0, coalescing_pending=False
    )
