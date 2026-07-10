"""hwpxdiff — HWPX 규격서 개정 비교(별도 제품, 읽기 도구).

:mod:`hwpxcore` (공통 파서)에만 의존한다 — :mod:`hwpxfiller` 와 상호 임포트 금지.
진입점: GUI ``hwpx-diff``(또는 ``python -m hwpxdiff``), CLI ``hwpxdiff OLD NEW [--html]``.
"""

from __future__ import annotations

__version__ = "0.1.0"
