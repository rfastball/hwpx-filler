"""HWPX 생성 엔진의 concrete 조립 — package path I/O를 엔진에 결속.

:class:`~hwpxfiller.domain.engine.HwpxEngine` 은 read/write 포트만 아는 Domain 이고, OCF ZIP
읽기·쓰기는 External 효과다. 그 결속을 여기 한 곳이 소유한다(P3-03, #591) —
ring 2/Host 와 테스트는 이 factory 로 실 엔진을 얻는다.
"""

from __future__ import annotations

from ..domain.engine import HwpxEngine
from .hwpx_package_io import read_hwpx_package, write_hwpx_package


def make_hwpx_engine() -> HwpxEngine:
    """실 zip IO 가 결속된 생성 엔진."""
    return HwpxEngine(
        read_package=read_hwpx_package,
        write_package=write_hwpx_package,
    )
