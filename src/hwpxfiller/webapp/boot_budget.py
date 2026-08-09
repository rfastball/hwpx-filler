"""호환 facade — 부팅 예산의 정본은 :mod:`hwpxfiller.host.boot_budget` 이다."""

from __future__ import annotations

from ..host.boot_budget import (
    COLD_BUDGET_SECONDS,
    WARM_BUDGET_SECONDS,
    decide,
    detect_runtime_version,
)

__all__ = [
    "WARM_BUDGET_SECONDS",
    "COLD_BUDGET_SECONDS",
    "detect_runtime_version",
    "decide",
]
