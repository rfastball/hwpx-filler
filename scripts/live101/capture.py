"""픽셀 캡처 어댑터 — HWND 탐색 · ``PrintWindow`` · PNG 저장 · **정착 정책**(N-11A · #423).

시나리오는 "여기서 찍는다"를 이름으로만 말하고, 그 이름이 무엇이 되는지는 여기가 정한다.
``check`` 모드는 :class:`NullSink` 를 끼워 같은 대본을 픽셀 없이 완주한다.

## 왜 정착 정책이 여기 있어야 하는가

종전에는 셔터 앞에 고정 ``sleep`` 을 뒀다(기본 0.45s, 재렌더가 큰 자리는 1.2s). 그 수치는
"이 정도면 되겠지"였고, 실제로 **되지 않았다**: N-11A 착수 실측에서
``09-range-editor.png`` 가 범위 편집기 시트가 합성되는 도중에 떠져 화면 절반이 회색 블록으로
찢겼다. DOM 은 이미 참이었다 — 「마지막 페인트가 끝났는가」는 DOM 에서 잴 수 없기 때문이다.

그래서 시간이 아니라 **결과**로 잰다: 프레임을 두 번 떠서 같으면 정착으로 본다. 다르면 다시
뜬다. 예산 안에 두 프레임이 같아지지 않으면 마지막 프레임을 저장하되 그 사실을 보고서에
``unstable`` 로 남긴다 — 조용히 찢긴 컷을 문서에 넣지 않는다(confirm-or-alarm).

## 왜 ``PW_RENDERFULLCONTENT`` 인가

WebView2 는 DirectComposition 으로 그린다. 이 플래그 없이 ``PrintWindow`` 를 부르면 그 영역이
통째로 검게 나온다 — 즉 "캡처는 성공했는데 내용이 없는" 조용한 실패다.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

_PW_RENDERFULLCONTENT = 0x00000002
_PW_CLIENTONLY = 0x00000001

#: 두 프레임이 같아질 때까지 다시 뜨는 예산. 넘기면 마지막 프레임 + ``unstable`` 표식.
SETTLE_BUDGET_S = 3.0
#: 프레임 사이 간격. 60Hz 한 프레임(16ms)보다 넉넉하고 사람 눈보다 촘촘하다.
SETTLE_INTERVAL_S = 0.2
#: 셔터 앞 최소 정착 — 전이가 **시작**되기 전에 두 프레임을 뜨면 둘 다 옛 화면이라 같다.
SETTLE_FLOOR_S = 0.35
#: 저장 폭 상한(물리 px) — DPI 배율 캡처를 문서 무게에 맞게 축소.
MAX_PNG_WIDTH = 1600


def find_window(title: str, timeout: float = 30.0) -> int:
    """제목으로 **보이는** 창을 찾는다 — 숨은 창을 잡으면 FOUC 은닉 상태를 찍는다."""
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd and user32.IsWindowVisible(hwnd):
            return int(hwnd)
        time.sleep(0.2)
    raise RuntimeError(f"보이는 창을 찾지 못함: {title!r} (FOUC 은닉 미해제?)")


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def grab_frame(hwnd: int) -> "tuple[int, int, bytes]":
    """클라이언트 영역 한 프레임을 raw BGRX 로 뜬다."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise RuntimeError("GetClientRect 실패")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"창 클라이언트 영역이 비정상: {width}x{height}")

    hdc_win = user32.GetDC(wintypes.HWND(hwnd))
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
    try:
        gdi32.SelectObject(hdc_mem, bmp)
        ok = user32.PrintWindow(
            wintypes.HWND(hwnd), hdc_mem, _PW_RENDERFULLCONTENT | _PW_CLIENTONLY
        )
        if not ok:
            raise RuntimeError("PrintWindow 실패")

        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = width
        header.biHeight = -height  # top-down
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, bmp, 0, height, buffer, ctypes.byref(header), 0)
        return width, height, buffer.raw
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(wintypes.HWND(hwnd), hdc_win)


class NullSink:
    """``check`` 모드의 셔터 — 이름만 세고 픽셀은 만들지 않는다."""

    def __init__(self) -> None:
        self.shots: "list[str]" = []
        self.unstable: "list[str]" = []

    def shoot(self, name: str) -> None:
        self.shots.append(name)

    def geometry(self) -> "dict[str, int]":
        return {}


class Win32Sink:
    """실 픽셀 셔터. 정착할 때까지 다시 뜨고, 정착하지 못하면 **그 사실을 남긴다**."""

    def __init__(self, hwnd: int, out_dir: Path, *, max_width: int = MAX_PNG_WIDTH) -> None:
        self.hwnd = hwnd
        self.out_dir = out_dir
        self.max_width = max_width
        self.shots: "list[str]" = []
        self.unstable: "list[str]" = []
        self._last_size = (0, 0)

    def shoot(self, name: str) -> None:
        width, height, pixels, settled = self._settled_frame()
        if not settled:
            self.unstable.append(name)
        self._last_size = (width, height)
        self.shots.append(name)
        index = len(self.shots)
        self._save(width, height, pixels, self.out_dir / f"{index:02d}-{name}.png")

    def geometry(self) -> "dict[str, int]":
        width, height = self._last_size
        return {"capture_width": width, "capture_height": height}

    def _settled_frame(self) -> "tuple[int, int, bytes, bool]":
        """두 프레임이 같아질 때까지 — 「마지막 페인트」는 DOM 이 아니라 픽셀이 답한다."""
        time.sleep(SETTLE_FLOOR_S)
        width, height, previous = grab_frame(self.hwnd)
        deadline = time.monotonic() + SETTLE_BUDGET_S
        while time.monotonic() < deadline:
            time.sleep(SETTLE_INTERVAL_S)
            width, height, current = grab_frame(self.hwnd)
            if current == previous:
                return width, height, current, True
            previous = current
        return width, height, previous, False

    def _save(self, width: int, height: int, pixels: bytes, path: Path) -> None:
        from PIL import Image

        image = Image.frombuffer("RGB", (width, height), pixels, "raw", "BGRX", 0, 1)
        if width > self.max_width:
            ratio = self.max_width / width
            image = image.resize(
                (self.max_width, max(1, round(height * ratio))), Image.LANCZOS
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
