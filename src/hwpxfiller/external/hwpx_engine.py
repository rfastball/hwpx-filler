"""HWPX 생성 엔진의 concrete 조립 — 패키지 열기 효과를 엔진에 결속(P2-19, #567).

:class:`~hwpxfiller.core.engine.HwpxEngine` 은 opener 포트만 아는 Domain 이고, OCF ZIP
열기(:meth:`hwpxcore.package.HwpxPackage.open`)는 External 효과다. 그 결속을 여기 한 곳이
소유한다(P2-12 ``inspect_hwpx_template`` 선례) — ring 2/Host 와 테스트는 이 factory 로
실 엔진을 얻는다.
"""

from __future__ import annotations

from hwpxcore.package import HwpxPackage

from ..core.engine import HwpxEngine


def make_hwpx_engine() -> HwpxEngine:
    """실 zip IO 가 결속된 생성 엔진."""
    return HwpxEngine(open_package=HwpxPackage.open)
