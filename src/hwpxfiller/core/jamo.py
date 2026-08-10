"""Legacy import facade for :mod:`hwpxfiller.domain.jamo`."""

from __future__ import annotations

from hwpxfiller.domain.jamo import (
    CHOSEONG,
    JUNGSEONG,
    JONGSEONG,
    decompose,
    jamo_find,
    jamo_contains,
)

__all__ = [
    "CHOSEONG",
    "JUNGSEONG",
    "JONGSEONG",
    "decompose",
    "jamo_find",
    "jamo_contains",
]
