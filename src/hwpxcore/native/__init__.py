"""hwpxcore.native — 제품-불가지 Win32/OS 글루(외부 의존 0).

웹 프론트엔드가 쓰는 네이티브 표면: 파일/폴더 다이얼로그(comdlg32·shell32)와
클립보드(CF_UNICODETEXT). pywebview 의 edgechromium(WinForms) 접근성 재귀 크래시를
우회해 Win32 공용 API 를 직접 친다.

여기엔 제품 로직을 두지 않는다 — OS 글루뿐(:mod:`hwpxcore.atomic` 과 같은 층위).
별도 저장소 ``hwpx-diff`` 도 이 250줄 STA/OLE ctypes 의 사본을 그대로 쓰므로
(:mod:`hwpxcore` 사본 참조), 제품 색이 스며들면 두 사본이 갈라진다.
"""
from __future__ import annotations

from .clipboard import get_clipboard_text, set_clipboard_text
from .dialogs import open_file_dialog, open_folder_dialog, save_file_dialog
from .reveal import open_path, reveal_in_explorer

__all__ = [
    "set_clipboard_text",
    "get_clipboard_text",
    "open_file_dialog",
    "open_folder_dialog",
    "save_file_dialog",
    "open_path",
    "reveal_in_explorer",
]
