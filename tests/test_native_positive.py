"""Windows native 양성 경로 통합 게이트(#190).

실 Win32 클립보드와 실 최상위 창을 사용한다. Windows 데스크톱 세션이 없는 실행기는
``HWPX_SKIP_NATIVE_TESTS=1``로만 명시 옵트아웃한다. 런타임 부재를 자동 감지해 조용히
스킵하지 않는다. 파일 다이얼로그는 unattended CI에서 강제로 조작하지 않고, 실제 STA
스레드 안의 shim/probe로 선택·취소·오류 번역을 검증한다.
"""
from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import wintypes

import pytest

from hwpxcore.native import clipboard, dialogs, reveal, single_instance

_NATIVE_GATE = sys.platform != "win32" or bool(os.environ.get("HWPX_SKIP_NATIVE_TESTS"))
_NATIVE_REASON = (
    "Windows desktop native gate — HWPX_SKIP_NATIVE_TESTS=1로만 명시 옵트아웃"
)


@pytest.mark.skipif(_NATIVE_GATE, reason=_NATIVE_REASON)
def test_dialog_sta_probe_distinguishes_selection_cancel_and_error() -> None:
    """실 대화상자를 띄우지 않고 실제 STA 경계에서 3가지 공용 API 결과를 왕복한다."""
    selected = dialogs._in_sta_thread(
        lambda: dialogs._common_dialog_result(1, r"C:\문서\선택.hwpx", 0)
    )
    cancelled = dialogs._in_sta_thread(
        lambda: dialogs._common_dialog_result(0, "", 0)
    )
    assert selected == r"C:\문서\선택.hwpx"
    assert cancelled is None

    with pytest.raises(OSError, match=r"0x3002") as raised:
        dialogs._in_sta_thread(
            lambda: dialogs._common_dialog_result(0, "", 0x3002)
        )
    assert raised.value.errno == 0x3002


@pytest.mark.skipif(_NATIVE_GATE, reason=_NATIVE_REASON)
class TestWindowsNativePositivePaths:
    def test_clipboard_unicode_write_readback(self) -> None:
        """실 CF_UNICODETEXT에 한글·보조평면 문자를 쓴 뒤 같은 Win32 API로 되읽는다."""
        previous = clipboard.get_clipboard_text()
        marker = f"HWPX native probe {uuid.uuid4()} — 한글 𠮷"
        try:
            clipboard.set_clipboard_text(marker)
            assert clipboard.get_clipboard_text() == marker
        finally:
            # 텍스트가 있던 사용자 세션은 원값을 복원한다. 텍스트 형식이 없었던 세션도 빈
            # 텍스트로 끝내 probe marker가 남지 않게 한다.
            clipboard.set_clipboard_text(previous if previous is not None else "")

    def test_reveal_and_open_report_success_from_launch_boundary(
        self, tmp_path, monkeypatch
    ) -> None:
        """존재 경로가 각 OS launch boundary까지 전달되고 명시적 성공을 반환한다."""
        target = tmp_path / "문서.hwpx"
        target.write_bytes(b"probe")
        calls: list[tuple[str, object]] = []
        monkeypatch.setattr(
            reveal, "_launch_explorer", lambda path: calls.append(("reveal", path))
        )
        monkeypatch.setattr(
            reveal, "_start_file", lambda path: calls.append(("open", path))
        )

        assert reveal.reveal_in_explorer(target) is True
        assert reveal.open_path(target) is True
        assert calls == [("reveal", target), ("open", target)]

    @pytest.mark.parametrize(
        ("helper", "action"),
        [
            ("_launch_explorer", "탐색기에서 표시"),
            ("_start_file", "기본 앱으로 열기"),
        ],
    )
    def test_reveal_and_open_translate_os_errors(
        self, tmp_path, monkeypatch, helper: str, action: str
    ) -> None:
        target = tmp_path / "문서.hwpx"
        target.write_bytes(b"probe")

        def denied(_path) -> None:
            raise PermissionError(5, "access denied")

        monkeypatch.setattr(reveal, helper, denied)
        call = reveal.reveal_in_explorer if helper == "_launch_explorer" else reveal.open_path
        with pytest.raises(OSError, match=action) as raised:
            call(target)
        assert raised.value.errno == 5
        assert raised.value.filename == str(target)
        assert isinstance(raised.value.__cause__, PermissionError)

    def test_focus_existing_restores_real_visible_window(self) -> None:
        """실 Win32 최상위 창을 최소화한 뒤 focus signal이 찾아 복원하는 양성 경로."""
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        title = f"HWPX native focus probe {uuid.uuid4()}"

        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        ws_overlappedwindow = 0x00CF0000
        ws_visible = 0x10000000
        sw_minimize = 6
        hwnd = user32.CreateWindowExW(
            0,
            "STATIC",
            title,
            ws_overlappedwindow | ws_visible,
            -32000,
            -32000,
            120,
            80,
            None,
            None,
            kernel32.GetModuleHandleW(None),
            None,
        )
        assert hwnd, "실 Win32 probe 창을 만들 수 없습니다 — desktop opt-out이 필요합니다."
        try:
            user32.ShowWindow(hwnd, sw_minimize)
            assert user32.IsIconic(hwnd)
            assert single_instance.focus_existing(title) is True
            assert not user32.IsIconic(hwnd)
        finally:
            user32.DestroyWindow(hwnd)
