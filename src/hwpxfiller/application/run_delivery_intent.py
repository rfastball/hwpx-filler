"""현재 생성의 세션별 저장 폴더·충돌 정책 입력."""

from __future__ import annotations

from dataclasses import dataclass

from hwpxfiller.application.document_creation_vocabulary import (
    COLLISION_POLICIES,
    DEFAULT_COLLISION_POLICY,
)
ADD_SUFFIX, FAIL, OVERWRITE_EXPLICIT = COLLISION_POLICIES


@dataclass(frozen=True)
class RunDeliveryIntent:
    """세션별 출력 의도. 기본 충돌 정책은 덮어쓰기이며 실제 충돌은 배달 준비가 판정한다.

    이 값은 Plan/VDR identity 에 들어가지 않는다. 변경 시 배달만 다시 해석한다.

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
