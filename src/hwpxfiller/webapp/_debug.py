"""env-게이트 진단 로거 — ``HWPXFILLER_WEBAPP_LOG`` 설정 시에만 파일에 타임스탬프/스레드 기록.

프로덕션에선 무비용(환경변수 없으면 no-op). 파일 다이얼로그 멈춤 같은 스레드/네이티브 경계
문제를 실기기에서 좁히기 위한 훅 — GUI 앱은 stdout 이 안 보여 파일 로그가 필요하다.
"""
from __future__ import annotations

import os
import threading
import time

_PATH = os.environ.get("HWPXFILLER_WEBAPP_LOG")


def log(msg: str) -> None:
    if not _PATH:
        return
    line = f"{time.time():.3f} [{threading.current_thread().name}] {msg}\n"
    try:
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
