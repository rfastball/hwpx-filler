"""Product Slot values restored from canonical media (HWPX native structure · TXT 표기).

값 모델은 **매체 중립**이다 — 같은 선언은 HWPX native Slot 구조에서 복원하든 TXT 구간
표기에서 스캔하든(S10-01 #858) 같은 :class:`Slot` 이어야 하고, 그 동등성이 두 매체가
한 상태기계를 쓴다는 사실의 검사 가능한 얼굴이다. 그래서 매체별 값 모델을 새로
만들지 않는다(좌표는 갈리지만 선언은 하나다).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotOption:
    id: str
    order: int
    label: str | None = None


@dataclass(frozen=True)
class Slot:
    id: str
    options: tuple[SlotOption, ...]
    label: str | None = None
