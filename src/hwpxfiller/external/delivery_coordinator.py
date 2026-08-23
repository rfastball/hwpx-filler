"""Delivery coordinator (S6-04 · #811) — resolved current delivery 의 atomic filesystem 집행.

S5/SX 가 「planned disposition 만 기록」으로 남겨 둔 자리(``generation_delivery.py`` 헤더)의
집행자다. bytes 생성(S6-01 러너)과 disk 안착의 소유자를 가른다(S6-7) — 이 모듈은 bytes 를
만들지 않고, materialization 판정·이름·disposition 을 **재판정하지 않는다**(D6): 무엇을 어디에
어떤 disposition 으로 앉힐지는 :class:`CurrentResolvedDelivery` 가, 앉혀도 되는 bytes 인지는
start gate + postcondition(:class:`MaterializedDocumentBytes`)이 이미 정했다.

집행 계약:

- ``WRITE_NEW``·``WRITE_ADD_SUFFIX`` = 「관찰 시점에 비어 있던 이름」 —
  :func:`write_bytes_atomic_exclusive` 로 집행한다. 관찰과 쓰기 사이에 생긴 파일은 생성 자체가
  거절하므로(no-clobber) 조용히 파괴되지 않는다. preview 승인은 filesystem reservation 이
  아니다(SX-04B) — 그 재확인을 별도 재관찰이 아니라 원자 생성이 진다.
- ``WRITE_OVERWRITE`` = 사용자가 명시 확인한 파괴 — :func:`write_bytes_atomic` 으로 교체한다.
- **write 는 전건 PASS 뒤에만 시작한다**: outcome 하나라도 실패·거절이면 아무것도 쓰지 않고
  사유를 재진술해 닫는다(S6-8 — 실패한 런은 filesystem 불변). legacy batch 의 「시작 전 전수
  차단」(RC-02) 선례와 같은 결이다.
- write 도중의 충돌·IO 실패는 그 항목에서 멈추고, 어디까지 앉았고 무엇이 남았는지를 숨기지
  않고 되돌려준다(항목별 원자 — 이미 앉은 문서는 유효하고, 실패 항목 이후는 손대지 않는다).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from hwpxfiller.application.generation_delivery import (
    PATH_OCCUPANCY_OBSERVATION_MISMATCH,
    WRITE_ADD_SUFFIX,
    WRITE_NEW,
    WRITE_OVERWRITE,
    CurrentResolvedDelivery,
)
from hwpxfiller.domain.fields import FillNote

from .atomic import write_bytes_atomic, write_bytes_atomic_exclusive
from .materialization_start_gate import StartMaterializationResult
from .materialization_runner import MaterializedDocumentBytes


class DeliveryContractError(Exception):
    """coordinator 입력이 계약 밖 — outcome 수·경로 봉쇄 위반은 거절이 아니라 loud 예외다."""


@dataclass(frozen=True)
class DeliveredDocument:
    """disk 에 앉은 문서 하나의 증거 — 원장(S6-05)이 그대로 나를 사실들."""

    item_ordinal: int
    record_identity: str
    relative_path: str
    absolute_path: str
    collision_disposition: str
    output_digest: str
    execution_notes: tuple[FillNote, ...]


@dataclass(frozen=True)
class DeliveryRefused:
    """write 0 으로 닫혔다 — filesystem 불변(S6-8). 사유는 상류 판정의 재진술이다."""

    code: str
    detail: str
    failed_item_ordinal: int


@dataclass(frozen=True)
class DeliveryAborted:
    """write 도중 멈췄다 — ``delivered`` 까지는 disk 에 유효하고 그 이후는 손대지 않았다."""

    code: str
    detail: str
    failed_item_ordinal: int
    delivered: tuple[DeliveredDocument, ...]


@dataclass(frozen=True)
class DeliveryCompleted:
    output_directory: str
    delivered: tuple[DeliveredDocument, ...]


DeliveryExecutionResult = DeliveryCompleted | DeliveryRefused | DeliveryAborted


def deliver_current_documents(
    *,
    resolved: CurrentResolvedDelivery,
    ordered_outcomes: Sequence[StartMaterializationResult],
) -> DeliveryExecutionResult:
    """item_ordinal 순서로 짝지어진 materialization outcome 을 disposition 대로 disk 에 앉힌다.

    짝짓기 축은 위치다 — current delivery item 에는 VDR ref 가 없고(그 부재가 SX-04B 계약),
    :func:`materialization_inputs_of` 와 같은 「item 순서 = 실행 순서」 투영을 caller 가 진다.
    수 불일치는 짝짓기 전제 붕괴라 거절이 아니라 예외로 닫는다.
    """
    items = resolved.ordered_items
    if len(ordered_outcomes) != len(items):
        raise DeliveryContractError(
            f"outcome {len(ordered_outcomes)}개가 delivery item {len(items)}개와 불일치"
        )

    # 1. 전건 PASS 게이트 — 하나라도 실패·거절이면 write 0(S6-8, filesystem 불변).
    for item, outcome in zip(items, ordered_outcomes, strict=True):
        if not isinstance(outcome, MaterializedDocumentBytes):
            return DeliveryRefused(
                code=outcome.code,
                detail=(
                    f"item {item.item_ordinal}({item.resolved_output_relative_path!r}) 의 "
                    f"materialization 이 닫히지 않아 아무것도 쓰지 않았다: {outcome.detail}"
                ),
                failed_item_ordinal=item.item_ordinal,
            )

    # 2. 집행 — 항목별 원자. 실패 항목에서 멈추고 사실을 그대로 되돌려준다.
    root = os.path.abspath(resolved.output_directory)
    delivered: list[DeliveredDocument] = []
    for item, outcome in zip(items, ordered_outcomes, strict=True):
        assert isinstance(outcome, MaterializedDocumentBytes)
        target = os.path.abspath(os.path.join(root, item.resolved_output_relative_path))
        # resolver 가 이미 경로 문자를 봉쇄했지만, 집행 경계는 억지량을 실측으로 다시 닫는다 —
        # root 밖으로 나가는 이름은 계약 밖이라 예외다(조용한 상위 디렉터리 쓰기 금지).
        if os.path.commonpath([root, target]) != root:
            raise DeliveryContractError(
                f"item {item.item_ordinal} 의 경로가 output directory 밖을 가리킨다: "
                f"{item.resolved_output_relative_path!r}"
            )
        try:
            if item.collision_disposition == WRITE_OVERWRITE:
                # 사용자가 명시 확인한 파괴(preview DESTRUCTIVE_OVERWRITE 승인) — 원자 교체.
                write_bytes_atomic(target, outcome.output_bytes)
            elif item.collision_disposition in (WRITE_NEW, WRITE_ADD_SUFFIX):
                write_bytes_atomic_exclusive(target, outcome.output_bytes)
            else:
                raise DeliveryContractError(
                    f"미지원 collision disposition: {item.collision_disposition!r}"
                )
        except FileExistsError:
            # 관찰 이후 disk 가 움직였다 — 계획의 전제(occupancy 관찰)가 더는 사실이 아니다.
            return DeliveryAborted(
                code=PATH_OCCUPANCY_OBSERVATION_MISMATCH,
                detail=(
                    f"item {item.item_ordinal} 의 대상 {item.resolved_output_relative_path!r} "
                    "이 관찰 이후 생겼다 — 기존 파일을 파괴하지 않고 멈췄다"
                ),
                failed_item_ordinal=item.item_ordinal,
                delivered=tuple(delivered),
            )
        delivered.append(
            DeliveredDocument(
                item_ordinal=item.item_ordinal,
                record_identity=item.record_identity,
                relative_path=item.resolved_output_relative_path,
                absolute_path=target,
                collision_disposition=item.collision_disposition,
                output_digest=outcome.output_digest,
                execution_notes=outcome.execution_notes,
            )
        )

    return DeliveryCompleted(output_directory=root, delivered=tuple(delivered))


__all__ = [
    "DeliveredDocument",
    "DeliveryAborted",
    "DeliveryCompleted",
    "DeliveryContractError",
    "DeliveryExecutionResult",
    "DeliveryRefused",
    "deliver_current_documents",
]
