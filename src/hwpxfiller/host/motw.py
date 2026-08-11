# -*- coding: utf-8 -*-
"""프로즌 번들의 Mark-of-the-Web(MOTW) self-unblock.

브라우저로 받은 포터블 zip 을 Windows 탐색기로 풀면 모든 파일에 "인터넷에서 가져옴"
표식(Zone.Identifier ADS)이 붙는다. 그러면 .NET Framework 가 차단된 pythonnet 어셈블리
로드를 거부해 pywebview(winforms/WebView2) 기동이 깨진다:

    RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from ...Python.Runtime.dll

설치본(Inno Setup)이 기록한 파일이나 개발 실행에는 MOTW 가 없어 문제가 없다 — 오직
포터블 zip 의 표준 다운로드·추출 흐름에서만 발생한다. 이 모듈은 ``webview`` 임포트 전에
번들 파일의 Zone.Identifier 스트림을 지워 self-unblock 한다(사용자가 수동 "차단 해제"를
하지 않아도 그냥 돌게).
"""
from __future__ import annotations

import os
import sys


def unblock_bundle() -> int:
    """프로즌일 때만 번들 트리의 Zone.Identifier(ADS)를 제거한다.

    최선 노력 — 실패(권한·잠김·비 NTFS·ADS 부재)는 조용히 넘긴다. 기동을 절대 막지
    않는다(비프로즌은 no-op). 지운 스트림 개수를 반환한다(스모크·로깅용).
    """
    if not getattr(sys, "frozen", False):
        return 0
    # onedir 는 _MEIPASS = _internal (pythonnet DLL 이 여기 있다). 실행 exe 디렉터리도
    # 함께 훑어 누락 없이 한다.
    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if exe_dir not in roots:
        roots.append(exe_dir)

    removed = 0
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                try:
                    os.remove(os.path.join(dirpath, name) + ":Zone.Identifier")
                    removed += 1
                except OSError:
                    pass  # ADS 부재·잠김·권한·비 NTFS — 무시(최선 노력)
    return removed
