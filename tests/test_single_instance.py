"""단일 인스턴스 가드 — ``hwpxcore.native.single_instance`` (#74 리뷰3).

홈당 하나만 뜨게 못박는 Win32 네임드 뮤텍스. 뮤텍스 이름이 홈 경로로 키되는지(다른 홈은
독립·같은 홈은 충돌)와, 같은 홈 두 번째 취득이 차단되는지를 가드한다.
"""
from __future__ import annotations

import sys

import pytest

from hwpxcore.native import single_instance


def test_mutex_name_is_stable_and_home_scoped(tmp_path):
    a, b = tmp_path / "home-a", tmp_path / "home-b"
    assert single_instance._mutex_name(a) == single_instance._mutex_name(a)  # 안정(호출 불변)
    assert single_instance._mutex_name(a) != single_instance._mutex_name(b)  # 홈별 분리
    assert "\\" not in single_instance._mutex_name(a)  # 역슬래시(네임스페이스 구분자) 없음


def test_mutex_name_normalizes_equivalent_paths(tmp_path):
    # resolve() 정규화 — 같은 실경로의 다른 표기는 같은 뮤텍스여야 더블클릭이 확실히 막힌다.
    home = tmp_path / "home"
    home.mkdir()
    assert single_instance._mutex_name(home) == single_instance._mutex_name(tmp_path / "home" / ".")


@pytest.mark.skipif(
    sys.platform != "win32", reason="네임드 뮤텍스는 Win32 전용(앱 타깃 OS)")
class TestWin32Guard:
    @staticmethod
    def _close(handle):
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(handle)

    def test_second_acquire_same_home_is_blocked(self, tmp_path):
        first = single_instance.acquire(tmp_path)
        assert first is not None  # primary
        try:
            assert single_instance.acquire(tmp_path) is None  # 두 번째 = 차단(더블클릭)
        finally:
            self._close(first)  # 핸들 해제 = 뮤텍스 소멸(다음 인스턴스가 다시 primary)
        assert single_instance.acquire(tmp_path) is not None  # 해제 후 재취득 가능

    def test_different_homes_are_independent(self, tmp_path):
        a = single_instance.acquire(tmp_path / "a")
        b = single_instance.acquire(tmp_path / "b")
        try:
            assert a is not None and b is not None  # 다른 홈 = 서로 안 막음
        finally:
            self._close(a)
            self._close(b)

    def test_focus_existing_returns_false_when_no_window(self):
        # 뜬 창이 없으면 best-effort 포커스는 조용히 False(두 번째 인스턴스는 어차피 종료).
        assert single_instance.focus_existing("존재하지 않는 창 제목 zzz-9f3a") is False
