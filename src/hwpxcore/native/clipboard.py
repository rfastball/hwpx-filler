"""OS 클립보드 읽기·쓰기 — Win32 CF_UNICODETEXT(외부 의존 0, 한글 안전).

txt 트랙의 완료 동작(복사=commit)이 여기 산다. ``QClipboard.setText`` 의 상당물을 pywebview
프로세스(=이 Python)에서 직접 구현한다 — ``file://`` 이 secure context 가 아니어도
``navigator.clipboard`` 우회가 불필요하고, ``clip.exe`` 코드페이지 한글 깨짐을 회피한다.

스파이크(SPIKE_FINDINGS.md Q2)에서 한글 왕복 확인된 구현을 승격한 것. 64비트 ``HGLOBAL``
핸들 절단(``OverflowError``)은 ctypes ``argtypes``/``restype`` 명시로 막는다.
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
_OPEN_RETRIES = 10
_OPEN_RETRY_SECONDS = 0.02


def _apis():
    """64-bit safe clipboard/kernel API bindings."""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    return user32, kernel32


def _open(user32) -> None:
    """짧은 외부 점유는 재시도하되, 계속 잠겨 있으면 시끄럽게 실패한다."""
    for attempt in range(_OPEN_RETRIES):
        if user32.OpenClipboard(None):
            return
        if attempt + 1 < _OPEN_RETRIES:
            time.sleep(_OPEN_RETRY_SECONDS)
    raise OSError("클립보드를 열 수 없습니다.")


def set_clipboard_text(text: str) -> None:
    """``text`` 를 OS 클립보드에 UTF-16 로 넣는다. Windows 전용(비-Windows 는 시끄럽게 실패)."""
    if sys.platform != "win32":  # confirm-or-alarm: 조용히 무시하지 않는다.
        raise OSError("클립보드 쓰기는 Windows 에서만 지원됩니다.")

    u, k = _apis()
    _open(u)
    h = None
    try:
        if not u.EmptyClipboard():
            raise OSError("클립보드를 비울 수 없습니다.")
        buf = text.encode("utf-16-le") + b"\x00\x00"
        h = k.GlobalAlloc(GMEM_MOVEABLE, len(buf))
        if not h:
            raise OSError("클립보드 메모리를 할당할 수 없습니다.")
        ptr = k.GlobalLock(h)
        if not ptr:
            raise OSError("클립보드 메모리를 잠글 수 없습니다.")
        ctypes.memmove(ptr, buf, len(buf))
        k.GlobalUnlock(h)
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            raise OSError("클립보드 데이터를 기록할 수 없습니다.")
        h = None  # 성공 시 소유권은 OS로 넘어간다.
    finally:
        if h:
            k.GlobalFree(h)
        u.CloseClipboard()


def get_clipboard_text() -> "str | None":
    """OS 클립보드의 UTF-16 텍스트를 읽는다. 텍스트 형식이 없으면 ``None``.

    쓰기 양성 경로를 실제 Win32 왕복으로 확인하는 프로브이자, 제품 코드에서도 필요한 경우
    같은 64비트 안전 바인딩을 재사용할 수 있는 대칭 API다.
    """
    if sys.platform != "win32":
        raise OSError("클립보드 읽기는 Windows 에서만 지원됩니다.")

    u, k = _apis()
    _open(u)
    try:
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        h = u.GetClipboardData(CF_UNICODETEXT)
        if not h:
            raise OSError("클립보드 데이터를 읽을 수 없습니다.")
        ptr = k.GlobalLock(h)
        if not ptr:
            raise OSError("클립보드 메모리를 잠글 수 없습니다.")
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()
