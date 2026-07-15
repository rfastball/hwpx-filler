"""hwpxcore.native — 제품-불가지 Win32/OS 글루(외부 의존 0).

두 제품(:mod:`hwpxfiller` 웹·:mod:`hwpxdiff` 웹)이 공유하는 네이티브 표면:
파일/폴더 다이얼로그(comdlg32·shell32)와 클립보드(CF_UNICODETEXT). pywebview 의
edgechromium(WinForms) 접근성 재귀 크래시를 우회해 Win32 공용 API 를 직접 친다.

여기엔 제품 로직을 두지 않는다 — OS 글루뿐(:mod:`hwpxcore.atomic` 과 같은 층위).
제품 간 임포트 금지 규칙(tests/test_architecture.py) 아래에서 diff·filler 가 이 공용
계층으로만 다이얼로그를 공유한다 — 250줄 STA/OLE ctypes 를 복제하지 않기 위함.
"""
from __future__ import annotations

from .clipboard import set_clipboard_text
from .dialogs import open_file_dialog, open_folder_dialog, save_file_dialog

__all__ = [
    "set_clipboard_text",
    "open_file_dialog",
    "open_folder_dialog",
    "save_file_dialog",
]
