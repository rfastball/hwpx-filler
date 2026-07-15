"""네이티브 파일 열기/저장 다이얼로그 — Win32 comdlg32(외부 의존 0).

**왜 pywebview 의 ``create_file_dialog`` 을 안 쓰나(소이슈 ②의 실제 해소).**
pywebview 의 edgechromium 백엔드는 WinForms 호스트로 다이얼로그를 띄우는데, 그 접근성
(AccessibilityObject) 마샬링이 무한 재귀(``maximum recursion depth exceeded``)에 빠져 파일
다이얼로그가 뜨기 전에 모달이 멈춘다. 스파이크(SPIKE_FINDINGS.md Q2)는 이를 '외부 UIA 주입
한정'으로 봤으나, 실기기 수동검증에서 **정상 클릭 경로**로도 재현됐다 — 스크린리더 등 접근성
클라이언트가 떠 있으면 재발한다. 조용히 멈추는 경로(confirm-or-alarm 위반)를 두느니, 클립보드와
동일한 방식으로 Win32 공용 다이얼로그를 직접 친다 — WinForms 호스트를 우회해 결정적이다.

다이얼로그는 전용 STA 스레드에서 실행한다 — 공용 다이얼로그는 STA + OLE 초기화를 요구하는데
pywebview 의 js_api 스레드 아파트 상태를 신뢰할 수 없으므로 격리한다. 호출은 다이얼로그가 닫힐
때까지 블록한다(기대 동작).
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable

from ._debug import log

# comdlg32 OFN 플래그.
OFN_HIDEREADONLY = 0x00000004
OFN_OVERWRITEPROMPT = 0x00000002
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_EXPLORER = 0x00080000
OFN_NOCHANGEDIR = 0x00000008

_MAX = 4096


class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", wintypes.LPVOID),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", wintypes.LPVOID),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


def _filter_block(filters: "list[tuple[str, str]]") -> str:
    """(설명, 패턴) 쌍 목록을 comdlg32 이중 널 종결 필터 문자열로."""
    parts: "list[str]" = []
    for desc, pattern in filters:
        parts.extend((f"{desc} ({pattern})", pattern))
    return "\0".join(parts) + "\0\0"


def _in_sta_thread(target: "Callable[[], object]") -> object:
    """target 을 OLE STA 로 초기화한 전용 스레드에서 실행하고 결과를 돌려준다(블록)."""
    box: dict = {}
    err: dict = {}

    def run() -> None:
        ole32 = ctypes.oledll.ole32  # type: ignore[attr-defined]
        # STA. 이미 다른 모드로 초기화됐으면(RPC_E_CHANGED_MODE) 그냥 진행 — best effort.
        try:
            ole32.OleInitialize(None)
            initialized = True
            log("sta: OleInitialize ok")
        except OSError as exc:
            initialized = False
            log(f"sta: OleInitialize failed {exc!r}")
        try:
            box["value"] = target()
        except Exception as exc:  # noqa: BLE001  (스레드 밖으로 시끄럽게 전달)
            log(f"sta: target() raised {exc!r}")
            err["exc"] = exc
        finally:
            if initialized:
                ole32.OleUninitialize()

    t = threading.Thread(target=run, daemon=True, name="win32-file-dialog")
    log("in_sta_thread: starting thread")
    t.start()
    t.join()
    log("in_sta_thread: thread joined")
    if "exc" in err:
        raise err["exc"]
    return box.get("value")


def _require_windows() -> None:
    if sys.platform != "win32":  # confirm-or-alarm: 조용히 무시하지 않는다.
        raise OSError("파일 다이얼로그는 Windows 에서만 지원됩니다.")


def _owner_hwnd(owner_title: "str | None"):
    """제목으로 앱 최상위 창 HWND 해석 — 다이얼로그 소유주로 써 앞으로 띄운다.

    pywebview 내부(window.native)를 건드리지 않고 Win32 ``FindWindowW`` 로만 찾는다 —
    WinForms 접근성 재귀 크래시를 피하는 게 이 화면 전체 이전의 핵심(소이슈 ②).
    소유주가 없으면 다이얼로그가 WebView2 창 **뒤로** 떠 사용자가 못 보고 앱이 멈춘 듯 보인다.
    """
    if not owner_title:
        return 0
    find = ctypes.windll.user32.FindWindowW  # type: ignore[attr-defined]
    find.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    find.restype = wintypes.HWND
    hwnd = find(None, owner_title) or 0
    log(f"owner hwnd for {owner_title!r} = {hwnd}")
    return hwnd


def open_file_dialog(
    filters: "list[tuple[str, str]]", owner_title: "str | None" = None
) -> "str | None":
    """네이티브 열기 다이얼로그. 선택 경로 또는 None(취소). ``filters``=(설명, 패턴) 쌍."""
    _require_windows()

    def call() -> "str | None":
        buf = ctypes.create_unicode_buffer(_MAX)
        ofn = _OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(ofn)
        ofn.hwndOwner = _owner_hwnd(owner_title)
        ofn.lpstrFilter = _filter_block(filters)
        ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        ofn.nMaxFile = _MAX
        ofn.Flags = (
            OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
            | OFN_HIDEREADONLY | OFN_NOCHANGEDIR
        )
        fn = ctypes.windll.comdlg32.GetOpenFileNameW  # type: ignore[attr-defined]
        fn.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
        fn.restype = wintypes.BOOL
        log("open: before GetOpenFileNameW")
        ok = fn(ctypes.byref(ofn))
        log(f"open: after GetOpenFileNameW ok={ok}")
        return buf.value if ok else None

    log("open_file_dialog: enter")
    return _in_sta_thread(call)  # type: ignore[return-value]


def save_file_dialog(
    default_name: str,
    filters: "list[tuple[str, str]]",
    default_ext: str = "",
    owner_title: "str | None" = None,
) -> "str | None":
    """네이티브 저장 다이얼로그. 선택 경로 또는 None(취소). 덮어쓰기 확인 포함."""
    _require_windows()

    def call() -> "str | None":
        buf = ctypes.create_unicode_buffer(_MAX)
        buf.value = default_name
        ofn = _OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(ofn)
        ofn.hwndOwner = _owner_hwnd(owner_title)
        ofn.lpstrFilter = _filter_block(filters)
        ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        ofn.nMaxFile = _MAX
        if default_ext:
            ofn.lpstrDefExt = default_ext
        ofn.Flags = (
            OFN_EXPLORER | OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST
            | OFN_HIDEREADONLY | OFN_NOCHANGEDIR
        )
        fn = ctypes.windll.comdlg32.GetSaveFileNameW  # type: ignore[attr-defined]
        fn.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
        fn.restype = wintypes.BOOL
        return buf.value if fn(ctypes.byref(ofn)) else None

    return _in_sta_thread(call)  # type: ignore[return-value]


# ------------------------------------------------------------------ 폴더 선택
# BROWSEINFOW.ulFlags — SHBrowseForFolderW 동작 비트.
BIF_RETURNONLYFSDIRS = 0x00000001  # 파일시스템 폴더만(가상 노드 배제)
BIF_EDITBOX = 0x00000010           # 경로 직접 입력 상자
BIF_NEWDIALOGSTYLE = 0x00000040    # 리사이즈·새폴더 버튼(OLE STA 필요 — _in_sta_thread 가 초기화)


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wintypes.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wintypes.LPWSTR),
        ("lpszTitle", wintypes.LPCWSTR),
        ("ulFlags", wintypes.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", wintypes.LPARAM),
        ("iImage", ctypes.c_int),
    ]


def open_folder_dialog(
    title: str = "저장 폴더 선택", owner_title: "str | None" = None
) -> "str | None":
    """네이티브 폴더 선택 다이얼로그(shell32 ``SHBrowseForFolderW``). 경로 또는 None(취소).

    실행 화면의 **신규 네이티브 표면**(에픽 #20 화면 #18) — 파일 다이얼로그와 같은 이유로
    pywebview 우회, 전용 STA 스레드에서 실행하고 앱 창을 소유주로 지정한다(뒤로 숨어 '멈춤'
    으로 보이지 않게). ``BIF_NEWDIALOGSTYLE`` 은 OLE 초기화를 요구하는데
    :func:`_in_sta_thread` 가 ``OleInitialize`` 로 이미 처리한다.
    """
    _require_windows()

    def call() -> "str | None":
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        name_buf = ctypes.create_unicode_buffer(_MAX)  # 표시명 수신 버퍼(수명 유지)
        bi = _BROWSEINFOW()
        bi.hwndOwner = _owner_hwnd(owner_title)
        bi.pidlRoot = None
        bi.pszDisplayName = ctypes.cast(name_buf, wintypes.LPWSTR)
        bi.lpszTitle = title
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX
        shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFOW)]
        shell32.SHBrowseForFolderW.restype = wintypes.LPVOID  # PIDL(널=취소)
        log("folder: before SHBrowseForFolderW")
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        log(f"folder: after SHBrowseForFolderW pidl={bool(pidl)}")
        if not pidl:
            return None
        try:
            out = ctypes.create_unicode_buffer(_MAX)
            shell32.SHGetPathFromIDListW.argtypes = [wintypes.LPVOID, wintypes.LPWSTR]
            shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
            ok = shell32.SHGetPathFromIDListW(pidl, out)
            return out.value if ok else None
        finally:
            # PIDL 은 셸 할당 — CoTaskMemFree 로 반환(_in_sta_thread 의 OLE 아파트 안).
            ctypes.windll.ole32.CoTaskMemFree(pidl)  # type: ignore[attr-defined]

    log("open_folder_dialog: enter")
    return _in_sta_thread(call)  # type: ignore[return-value]
