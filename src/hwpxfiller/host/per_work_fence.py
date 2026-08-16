"""Per-Work command 선형화 fence (S4-05 · #675).

S3 store lock 과 S4 store lock 만 각각 잡으면 유령 승계가 가능하다: S4 가 A17 을 읽는
사이 S3 가 A18 을 적용하고 S4 가 STALE 을 받아도, 그 실패한 intent 가 A18 successor 로
복사될 수 있다. 이를 막으려면 S3 Apply·S4 mutation·향후 S5/S9 command 가 **같은** per-Work
fence 아래 선형화돼야 한다.

fence identity 는 root 경로·Job 이름·process session ID 가 아니라
``(WorkspaceInstanceId, WorkAuthorityId)`` 다 — S3 와 S4 가 다른 root store 를 써도 같은
Work 면 같은 fence instance 를 받는다.

lock order: fence → (S3 immutable/current reads) → 단일 store writer lease → atomic commit →
lease 해제 → 같은 fence 아래 fresh view → fence 해제. store lease 를 먼저 잡고 fence 를
기다리지 않는다. 한 command 가 두 writer lease 를 동시에 잡지 않는다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class PerWorkMutationFenceKey:
    workspace_instance_id: str
    work_authority_id: str


# ponytail: process-local registry — durable lease·stale PID recovery·cross-process 배제·
# 분산 lock 을 주장하지 않는다(v1 = workspace 하나당 writer process 하나, #620 에서 상향).
# process 종료와 함께 fence 는 사라진다.
_registry: dict[PerWorkMutationFenceKey, threading.Lock] = {}
_registry_guard = threading.Lock()


def _fence_lock(key: PerWorkMutationFenceKey) -> threading.Lock:
    """key 별 공유 fence lock — 같은 key 는 항상 같은 lock object 를 돌려준다."""
    with _registry_guard:
        lock = _registry.get(key)
        if lock is None:
            lock = threading.Lock()  # 비재진입: correctness 가 reentrancy 에 의존하지 않는다
            _registry[key] = lock
        return lock


@contextmanager
def per_work_mutation_fence(
    workspace_instance_id: str, work_authority_id: str
) -> Iterator[None]:
    """같은 (workspace, work) 의 mutation command 를 직렬화한다.

    비재진입이다 — under-fence helper 는 fence 를 다시 획득하지 않는다(그렇게 하면 deadlock).
    이 계약을 지키므로 correctness 가 reentrant lock 에 의존하지 않는다.
    """
    if not workspace_instance_id or not work_authority_id:
        raise ValueError("fence key 의 workspace_instance_id·work_authority_id 는 비어 있을 수 없다")
    key = PerWorkMutationFenceKey(workspace_instance_id, work_authority_id)
    with _fence_lock(key):
        yield
