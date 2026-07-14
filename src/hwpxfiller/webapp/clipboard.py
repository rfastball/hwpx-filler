"""OS 클립보드 쓰기 — Win32 CF_UNICODETEXT(외부 의존 0, 한글 안전).

txt 트랙의 완료 동작(복사=commit)이 여기 산다. ``QClipboard.setText`` 의 상당물을 pywebview
프로세스(=이 Python)에서 직접 구현한다 — ``file://`` 이 secure context 가 아니어도
``navigator.clipboard`` 우회가 불필요하고, ``clip.exe`` 코드페이지 한글 깨짐을 회피한다.

스파이크(SPIKE_FINDINGS.md Q2)에서 한글 왕복 확인된 구현을 승격한 것. 64비트 ``HGLOBAL``
핸들 절단(``OverflowError``)은 ctypes ``argtypes``/``restype`` 명시로 막는다.
"""
from __future__ import annotations

import sys

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def set_clipboard_text(text: str) -> None:
    """``text`` 를 OS 클립보드에 UTF-16 로 넣는다. Windows 전용(비-Windows 는 시끄럽게 실패)."""
    if sys.platform != "win32":  # confirm-or-alarm: 조용히 무시하지 않는다.
        raise OSError("클립보드 쓰기는 Windows 에서만 지원됩니다.")

    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32  # type: ignore[attr-defined]
    k = ctypes.windll.kernel32  # type: ignore[attr-defined]
    # 64비트 핸들 절단 방지 — argtypes/restype 미명시 시 ctypes 가 c_int 로 보고 HGLOBAL
    # (포인터 크기)이 넘쳐 OverflowError. 명시가 핵심.
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = wintypes.LPVOID
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE

    if not u.OpenClipboard(None):
        raise OSError("클립보드를 열 수 없습니다.")
    try:
        u.EmptyClipboard()
        buf = text.encode("utf-16-le") + b"\x00\x00"
        h = k.GlobalAlloc(GMEM_MOVEABLE, len(buf))
        ptr = k.GlobalLock(h)
        ctypes.memmove(ptr, buf, len(buf))
        k.GlobalUnlock(h)
        u.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        u.CloseClipboard()
