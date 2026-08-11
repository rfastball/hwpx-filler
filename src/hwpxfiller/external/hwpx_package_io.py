"""HWPX package의 path 읽기와 durable 쓰기 adapter."""

from __future__ import annotations

from pathlib import Path

from .atomic import write_bytes_atomic
from hwpxcore.package import HwpxPackage


def read_hwpx_package(path: "str | Path") -> HwpxPackage:
    """경로의 bytes를 읽어 in-memory format kernel에 넘긴다."""
    return HwpxPackage.from_bytes(Path(path).read_bytes())


def write_hwpx_package(path: "str | Path", package: HwpxPackage) -> None:
    """package를 먼저 직렬화한 뒤 기존 atomic writer로 저장한다(RC-01)."""
    write_bytes_atomic(path, package.to_bytes())
