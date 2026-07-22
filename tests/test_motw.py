# -*- coding: utf-8 -*-
"""hwpxcore.motw self-unblock 계약."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hwpxcore.motw import unblock_bundle


def test_noop_when_not_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """비프로즌(개발·pytest)에서는 아무것도 하지 않고 0 을 반환한다."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert unblock_bundle() == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Zone.Identifier ADS 는 NTFS(Windows) 전용")
def test_removes_zone_identifier_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """프로즌으로 위장하면 번들 트리의 Zone.Identifier(ADS)를 제거한다."""
    payload = tmp_path / "Python.Runtime.dll"
    payload.write_bytes(b"stub")
    ads = f"{payload}:Zone.Identifier"
    with open(ads, "w", encoding="ascii") as stream:
        stream.write("[ZoneTransfer]\nZoneId=3\n")
    # ADS 가 실제로 붙었는지 확인(NTFS 아니면 여기서 이미 실패 → 환경 문제로 스킵)
    try:
        assert Path(ads).exists()
    except OSError:
        pytest.skip("ADS 미지원 파일시스템")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))

    removed = unblock_bundle()

    assert removed >= 1
    assert not Path(ads).exists()      # 표식 제거됨
    assert payload.read_bytes() == b"stub"  # 파일 본문은 보존


def test_frozen_without_ads_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """표식 없는 파일뿐이면(설치본·비다운로드) 실패 없이 0 을 반환한다."""
    (tmp_path / "clean.dll").write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    assert unblock_bundle() == 0
