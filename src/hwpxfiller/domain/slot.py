"""Product Slot values restored from canonical HWPX."""

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
