"""단일 인스턴스 가드 — Win32 네임드 뮤텍스(외부 의존 0).

앱은 한 홈(``settings.json`` + WebView2 프로필)당 하나만 떠야 한다: ``private_mode=True`` 의
``clear_user_data`` (정상 닫기 rmtree)가 같은 프로필을 공유하는 두 번째 인스턴스를 밑에서
지우기 때문이다(#74 리뷰). 이를 per-pid 프로필 + 부팅 스윕 + 락으로 *방어* 하던 기계 대신,
애초에 두 번째 인스턴스가 뜨지 않게 못박는다 — 대부분의 데스크톱 앱(Word·Slack)의 패턴이자,
경합·조용한 소실·TOCTOU 크래시 클래스를 통째로 소거하는 정공법(#74 리뷰3).

뮤텍스 이름은 **홈 경로로 키한다**: 서로 다른 ``HWPXFILLER_HOME`` (테스트 격리·다중 프로필)은
독립이고, 같은 홈의 더블클릭만 막힌다. 기본(Session) 네임스페이스라 다른 로그인 세션의 다른
사용자와도 독립이다. 비-Windows(개발용)에선 무집행(항상 primary) — 앱 타깃 OS 는 Windows.
"""
from __future__ import annotations

import ctypes
import hashlib
import sys
from ctypes import wintypes
from pathlib import Path

from ._debug import log

_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9


class _Sentinel:
    """비-Windows·가드 포기 시의 무집행 토큰 — 보유해도 아무 일 없고 항상 primary 취급."""


def _mutex_name(home: Path) -> str:
    """홈 경로 → 뮤텍스 이름. 이름에 역슬래시(네임스페이스 구분자)가 못 오므로 경로를 안정
    해시한다(``hash()`` 는 PYTHONHASHSEED 로 프로세스마다 달라 부적합 → sha1)."""
    try:
        key = str(home.resolve())
    except OSError:
        key = str(home)
    return "hwpx-filler-single-instance-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def acquire(home: Path) -> "object | None":
    """이 홈의 단일 인스턴스 뮤텍스를 잡는다.

    반환: primary 이면 살려 둘 토큰(프로세스 수명 동안 보유 — 뮤텍스 핸들은 종료 시 OS 가
    회수한다), 이미 다른 인스턴스가 잡고 있으면 ``None``. 뮤텍스 생성 자체가 실패하면 가드를
    포기하되 부팅은 막지 않는다(무집행 토큰 반환) — 가드 부재가 부팅 불능보다 낫다.
    """
    if sys.platform != "win32":
        return _Sentinel()
    # use_last_error=True: CreateMutexW 직후의 GetLastError 를 ctypes 내부 호출이 덮지 않게
    # 저장·복원하고 get_last_error() 로 읽는다(windll 공유 인스턴스의 last-error 경합 회피).
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, _mutex_name(home))
    last_error = ctypes.get_last_error()
    if not handle:
        log(f"[single_instance] CreateMutexW 실패(err={last_error}) — 가드 없이 진행")
        return _Sentinel()
    if last_error == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle  # 보유 = 뮤텍스 유지(핸들은 프로세스 종료 시 OS 회수)


def focus_existing(window_title: str) -> bool:
    """이미 떠 있는 인스턴스의 **보이는** 창을 찾아 복원·전면화한다(best-effort).

    실패해도 무해 — 두 번째 인스턴스는 어차피 종료한다(조용한 종료 폴백). 창 제목으로 찾는다
    (``webview.create_window(WINDOW_TITLE, …)`` 가 캡션으로 심는 값과 동일).

    **가시성 가드(#75 리뷰4 #3)**: 첫 인스턴스가 아직 콜드부트 중이면 창은 hidden 상태로 생성돼
    있다(FOUC 은닉 — 테마 주입 전 show 대기). 그 창에 SW_RESTORE 를 걸면 테마 미주입 창을 강제
    노출해 FOUC 를 낸다. 보이는 창일 때만 전면화하고, 부팅 중(숨김)이면 건드리지 않는다 —
    첫 인스턴스가 준비되면 스스로 show 한다."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    hwnd = user32.FindWindowW(None, window_title)
    if not hwnd:
        return False
    if not user32.IsWindowVisible(hwnd):
        return False  # 부팅 중 숨김창 — 강제 노출로 FOUC 내지 않는다(첫 인스턴스가 곧 show)
    user32.ShowWindow(hwnd, _SW_RESTORE)      # 최소화돼 있으면 복원
    user32.SetForegroundWindow(hwnd)
    return True
