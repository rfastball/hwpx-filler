"""HWPX 템플릿 엔진의 concrete 조립 — package path 읽기를 엔진에 결속.

:class:`~hwpxfiller.domain.engine.HwpxEngine` 은 read 포트만 아는 Domain 이고, OCF ZIP
읽기는 External 효과다. 그 결속을 여기 한 곳이 소유한다(P3-03, #591) —
ring 2/Host 와 테스트는 이 factory 로 실 엔진을 얻는다.
"""

from __future__ import annotations

from ..domain.engine import HwpxEngine
from .hwpx_package_io import read_hwpx_package


def make_hwpx_engine() -> HwpxEngine:
    """실 zip 읽기가 결속된 템플릿 엔진."""
    return HwpxEngine(read_package=read_hwpx_package)
