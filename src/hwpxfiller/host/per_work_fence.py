"""Per-Work command 선형화 fence + repository lock order guard (S4-05 · #675; S5F R2-05b · #740).

S3 store lock 과 S4 store lock 만 각각 잡으면 유령 승계가 가능하다: S4 가 A17 을 읽는
사이 S3 가 A18 을 적용하고 S4 가 STALE 을 받아도, 그 실패한 intent 가 A18 successor 로
복사될 수 있다. 이를 막으려면 S3 Apply·S4 mutation·향후 S5/S9 command 가 **같은** per-Work
fence 아래 선형화돼야 한다.

fence identity 는 root 경로·Job 이름·process session ID 가 아니라
``(WorkspaceInstanceId, WorkAuthorityId)`` 다 — S3 와 S4 가 다른 root store 를 써도 같은
Work 면 같은 fence instance 를 받는다.

**S5F R2-05b(#740): QualificationProfileAdmissionFence(ProfileFence)를 제거했다.** repository
global lock order 는 이제 2-rank 다(바깥→안):

    PerWorkMutationFence → 단일 Store writer lease

이 순서를 thread-local held-lock ledger 로 강제한다. store lease 를 먼저 잡고 fence 를
기다리면 deadlock 위험이라 시끄럽게 거절한다. 한 command 가 두 writer lease 를 동시에 잡지 않는다.
lock-order rank guard 는 이 모듈이 소유한다(예전 profile_admission_fence 에서 이관 — Store lease
결선은 S5-09 가 :func:`store_lease_order_guard` 로 참여한다).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

# ─── repository lock order(작을수록 바깥) — 획득은 rank 오름차순만 허용 ────────────────
# R2-05b: ProfileFence(rank 0) 제거로 2-rank 만 남는다 — PerWorkMutationFence → StoreWriterLease.
WORK_FENCE_RANK = 0
STORE_LEASE_RANK = 1
_RANK_NAMES = {
    WORK_FENCE_RANK: "PerWorkMutationFence",
    STORE_LEASE_RANK: "StoreWriterLease",
}


class LockOrderViolation(RuntimeError):
    """repository global lock order 위반(안쪽 lock 보유 중 바깥 lock 대기)."""

    code = "LOCK_ORDER_VIOLATION"


# ponytail: process-local·thread-local. cross-process·분산 lock 을 주장하지 않는다
# (v1 = workspace 하나당 writer process 하나, #620). thread 종료·process 종료와 함께 사라진다.
_held = threading.local()


def _held_ranks() -> list[int]:
    ranks = getattr(_held, "ranks", None)
    if ranks is None:
        ranks = []
        _held.ranks = ranks
    return ranks


@contextmanager
def lock_order_rank(rank: int) -> Iterator[None]:
    """rank 를 thread-local ledger 에 밀어 넣되, 이미 쥔 lock 보다 바깥이면 거절한다.

    현재 이 thread 가 쥔 lock 중 하나라도 rank 가 **더 크면**(더 안쪽이면) 바깥 lock 을
    나중에 잡는 것이라 lock order 위반이다 — 잡기 전에 raise 한다(ledger 오염 없음).
    """
    ranks = _held_ranks()
    if ranks and max(ranks) > rank:
        inner = _RANK_NAMES.get(max(ranks), str(max(ranks)))
        outer = _RANK_NAMES.get(rank, str(rank))
        raise LockOrderViolation(
            f"{inner}(안쪽)을 쥔 채 {outer}(바깥)을 기다릴 수 없다"
            f"(order: {' → '.join(_RANK_NAMES[r] for r in sorted(_RANK_NAMES))})"
        )
    ranks.append(rank)
    try:
        yield
    finally:
        ranks.pop()


@contextmanager
def work_fence_order_guard() -> Iterator[None]:
    """PerWorkMutationFence 획득 자리를 lock-order ledger 에 표시한다(가장 바깥 rank)."""
    with lock_order_rank(WORK_FENCE_RANK):
        yield


@contextmanager
def store_lease_order_guard() -> Iterator[None]:
    """단일 Store writer lease 획득 자리를 lock-order ledger 에 표시한다(S5-09 배선)."""
    with lock_order_rank(STORE_LEASE_RANK):
        yield


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
    # global lock order 참여(R2-05b): 이 WorkFence(바깥) → Store lease(안). inner lock 을 쥔 채
    # 이 WorkFence 를 기다리면 guard 가 시끄럽게 거절한다.
    with work_fence_order_guard():
        with _fence_lock(key):
            yield
