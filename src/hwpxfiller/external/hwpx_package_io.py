"""HWPX package의 path 읽기와 durable 쓰기 adapter."""

from __future__ import annotations

from pathlib import Path

from .atomic import write_bytes_atomic
from hwpxcore.package import DEFAULT_PACKAGE_LIMITS, HwpxPackage


def read_hwpx_package(path: "str | Path") -> HwpxPackage:
    """경로의 bytes를 읽어 in-memory format kernel에 넘긴다.

    읽기 전에 파일 크기를 같은 자원 예산으로 잰다(#800) — 한도를 넘는 파일은 메모리에
    올리지 않고 거절한다. 나머지 예산(엔트리 수·크기·압축률)은 커널이 잰다.
    """
    source = Path(path)
    DEFAULT_PACKAGE_LIMITS.check_archive_size(source.stat().st_size)
    return HwpxPackage.from_bytes(source.read_bytes(), limits=DEFAULT_PACKAGE_LIMITS)


def write_hwpx_package(path: "str | Path", package: HwpxPackage) -> None:
    """package를 먼저 직렬화한 뒤 기존 atomic writer로 저장한다(RC-01)."""
    write_bytes_atomic(path, package.to_bytes())
