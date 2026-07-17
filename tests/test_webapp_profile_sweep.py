"""인스턴스별 WebView2 프로필 스윕 가드 — ``hwpxfiller.webapp.app._sweep_stale_profiles`` (#75 리뷰).

고정 단일 프로필 + private_mode=True 는 정상 닫기의 clear_user_data rmtree 가 동시 실행
인스턴스의 프로필을 지우는 결함이었다 — 인스턴스별 폴더 + 부팅 스윕으로 교체하면서,
스윕이 (1) 고아·구판 잔재는 지우고 (2) 살아있는 프로필(열린 profile.lock)은 rename 프로브
실패로 무손상 보존하는지를 가드한다. rename 프로브는 Windows 파일 잠금 의미론에 기댄다.
"""
from __future__ import annotations

import sys

import pytest

from hwpxfiller.webapp.app import _sweep_stale_profiles

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="rename 프로브는 Windows 잠금 의미론 전제(앱 타깃 OS)")


def test_sweep_removes_orphans_and_legacy_layout(tmp_path):
    root = tmp_path / "webview"
    orphan = root / "profile-99999"
    orphan.mkdir(parents=True)
    (orphan / "junk.bin").write_bytes(b"x" * 16)
    legacy = root / "EBWebView"  # 구판 단일 폴더 레이아웃 잔재
    (legacy / "Default").mkdir(parents=True)
    (root / "stray.txt").write_text("파일은 건드리지 않는다", encoding="utf-8")
    _sweep_stale_profiles(root)
    assert not orphan.exists()
    assert not legacy.exists()
    assert (root / "stray.txt").exists()


def test_sweep_skips_live_profile_with_held_lock(tmp_path):
    root = tmp_path / "webview"
    live = root / "profile-11111"
    live.mkdir(parents=True)
    (live / "data.bin").write_bytes(b"y" * 16)
    with (live / "profile.lock").open("w"):
        _sweep_stale_profiles(root)
        assert live.is_dir()  # 열린 lock → rename 실패 → 통째 보존(부분 삭제 없음)
        assert (live / "data.bin").exists()
    # 잠금 해제(프로세스 종료 모사) 후에는 고아로 판정·정리된다.
    _sweep_stale_profiles(root)
    assert not live.exists()


def test_sweep_missing_root_is_noop(tmp_path):
    _sweep_stale_profiles(tmp_path / "없는폴더")  # 예외 없이 조용히 통과(첫 부팅)
