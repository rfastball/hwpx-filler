"""Product Slot values restored from canonical HWPX."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlotOption:
    id: str
    label: str
    order: int


@dataclass(frozen=True)
class Slot:
    id: str
    label: str
    cardinality: str
    min_options: int
    options: tuple[SlotOption, ...]
    ordering: str = "template_order"
