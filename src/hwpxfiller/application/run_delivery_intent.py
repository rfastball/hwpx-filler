"""session-scoped RunDeliveryIntent + delivery resolver 어댑터 (SX-01 · #724 §8 · #719 D5).

**순수 application 계약**이다 — store/webapp/gui 를 모르고, 새 durable state·새 semantic rule·
store write 를 만들지 않는다. 출력 위치와 같은 이름 처리 정책은 Document Work 기본 속성도,
Sealed Plan/VDR identity 도 **아니다** — session-scoped 의도일 뿐이다.

::

    RunDeliveryIntent
    ├─ output_directory
    └─ collision_policy = ADD_SUFFIX | FAIL | OVERWRITE_EXPLICIT   (기본 ADD_SUFFIX)

**핵심 계약**(#724 §8): RunDeliveryIntent 변경 → Plan 유지·VDR 유지·**delivery 만 재해결**.
:func:`hwpxfiller.application.generation_delivery.resolve_generation_delivery_plan` 이
``sealed_execution_plan``·``ordered_validated_records``(Plan/VDR identity)와
``output_directory_basis``·``overwrite_policy``(delivery)를 **서로 독립한 인자**로 받으므로,
delivery 의도를 바꿔도 Plan/VDR digest 입력은 손대지 않는다. 이 모듈은 그 resolver 입력으로
매핑하는 **얇은 어댑터**만 제공한다 — RunDeliveryIntent 자체의 digest 를 만들지 않는다
(intent 는 content-addressed identity 가 아니다).

collision policy 어휘의 정본은 :mod:`hwpxfiller.application.document_creation_vocabulary`,
resolver overwrite disposition 어휘의 정본은 :mod:`hwpxfiller.application.generation_delivery`
다 — 둘 다 **import 만** 한다(재정의 없음).

.. note:: **legacy compatibility 사상**

   resolver 의 disposition 어휘는 ``OVERWRITE_EXISTING``/``SKIP_EXISTING``/``FAIL_ON_EXISTING``
   뿐이라 legacy :func:`map_run_delivery_intent_to_resolution_inputs` 는 ``ADD_SUFFIX`` 를 가장
   보수적인 ``FAIL_ON_EXISTING`` 으로 유지한다. current production path 는 이 어댑터를 거치지 않고
   :func:`hwpxfiller.application.generation_delivery.resolve_current_generation_delivery` 가
   ``RunDeliveryIntent`` 와 one-shot filesystem observation 을 직접 소비해 실제 suffix 를 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from hwpxfiller.application.document_creation_vocabulary import (
    COLLISION_POLICIES,
    DEFAULT_COLLISION_POLICY,
)
from hwpxfiller.application.generation_delivery import (
    FAIL_ON_EXISTING,
    OVERWRITE_EXISTING,
)

# collision policy 어휘를 vocabulary 정본에서 풀어 쓴다(재정의 아님).
ADD_SUFFIX, FAIL, OVERWRITE_EXPLICIT = COLLISION_POLICIES

#: RunDeliveryIntent collision policy → resolver overwrite disposition.
#: legacy compatibility resolver 용. current production resolver 는 intent 를 직접 소비한다.
_OVERWRITE_POLICY_BY_COLLISION: dict[str, str] = {
    OVERWRITE_EXPLICIT: OVERWRITE_EXISTING,
    FAIL: FAIL_ON_EXISTING,
    # 비파괴 기본값 — on-disk add-suffix 어휘 부재로 가장 보수적인 비파괴·무드롭 disposition 에 사상.
    ADD_SUFFIX: FAIL_ON_EXISTING,
}


@dataclass(frozen=True)
class RunDeliveryIntent:
    """session-scoped 출력 의도 — Plan/VDR identity 에 들어가지 않는다(#724 §8, D5).

    **digest 를 만들지 않는다**: intent 는 content-addressed identity 가 아니라 session 값이다.
    변경 시 Plan/VDR 은 유지되고 delivery 만 재해결한다. 기본 충돌 동작은 비파괴 ``ADD_SUFFIX`` 이고
    overwrite 는 사용자가 ``OVERWRITE_EXPLICIT`` 을 **명시적으로** 골랐을 때만이다.

    .. note:: **「기억한 저장 폴더」는 이 객체가 아니다**(U3-06 · #879)

       마지막 명시 지정을 다음 세션에 되살리는 것은 설정 층
       (:func:`hwpxfiller.external.settings.load_last_output_directory`)이 지고, 그 값과 템플릿
       옆 ``Results`` 중 무엇을 쓸지는 링0 순수 판정
       (:func:`hwpxfiller.domain.output_folder_default.resolve_output_folder`)이 낸다. 컨트롤러는
       그 결과로 **이 세션의** intent 를 세워 resolver 에 건넨다 — 즉 intent 는 여전히 durable
       state 가 아니고 session-scoped 이며, 작업 전환·해제에서 소거된다. 영속되는 것은 도출의
       재료(마지막 명시 지정 경로)뿐이다.
    """

    output_directory: str
    collision_policy: str = DEFAULT_COLLISION_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.output_directory, str) or self.output_directory == "":
            raise ValueError("output_directory 는 비어 있지 않은 문자열이어야 한다")
        if self.collision_policy not in COLLISION_POLICIES:
            raise ValueError(f"미지원 collision policy: {self.collision_policy!r}")

    @property
    def is_destructive(self) -> bool:
        """파괴적(overwrite) 의도 여부 — OVERWRITE_EXPLICIT 을 명시로 골랐을 때만 True."""
        return self.collision_policy == OVERWRITE_EXPLICIT


@dataclass(frozen=True)
class DeliveryResolutionInputs:
    """RunDeliveryIntent 를 resolver 가 받는 delivery 인자로 사상한 결과(Plan/VDR 인자와 분리).

    ``resolve_generation_delivery_plan`` 의 ``output_directory_basis``·``overwrite_policy`` 에
    각각 대응한다 — Plan/VDR 인자(``sealed_execution_plan``·``ordered_validated_records``)는 이
    DTO 에 없다. 그래서 이 값을 바꿔도 Plan/VDR digest 입력은 손대지 않는다.
    """

    output_directory_basis: str
    overwrite_policy: str


def map_run_delivery_intent_to_resolution_inputs(
    intent: RunDeliveryIntent,
) -> DeliveryResolutionInputs:
    """session-scoped intent → resolver delivery 인자(얇은 사상, 새 semantic rule 없음).

    output_directory 는 그대로 ``output_directory_basis`` 로, collision_policy 는
    :data:`_OVERWRITE_POLICY_BY_COLLISION` 로 resolver disposition 에 사상한다. Plan/VDR 인자는
    이 함수의 관심 밖이다 — delivery 만 재해결하기 때문이다.
    """
    return DeliveryResolutionInputs(
        output_directory_basis=intent.output_directory,
        overwrite_policy=_OVERWRITE_POLICY_BY_COLLISION[intent.collision_policy],
    )
