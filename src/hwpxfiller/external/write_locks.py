"""프로세스 내 공유 쓰기 잠금 — 같은 디렉터리를 보는 레지스트리들의 단일 쓰기 경계.

``dataset_store`` 가 들고 있던 잠금 테이블을 원문 승격했다(S9-01 · #827): 파일 레지스트리가
둘 이상(데이터셋 풀·Preset)이 되면서 같은 규율을 인라인 재구현할 자리가 생겼기 때문이다.

같은 디렉터리를 보는 컨트롤러·레지스트리 인스턴스는 하나의 쓰기 경계를 공유한다.
pywebview 는 호출마다 다른 스레드로 진입하고 화면마다 레지스트리를 새로 만들 수 있으므로
instance-local RLock 은 load→수정→save 사이의 lost update 를 막지 못한다. #182 범위는
single-process 직렬화이며 cross-process lock 은 명시적 비목표다.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

_WRITE_LOCKS: "dict[str, threading.RLock]" = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def shared_write_lock(directory: Path) -> "threading.RLock":
    """``directory`` 를 정규화한 키로 프로세스 단일 RLock 을 돌려준다(없으면 생성)."""
    key = os.path.normcase(os.path.abspath(os.fspath(directory)))
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.RLock())
