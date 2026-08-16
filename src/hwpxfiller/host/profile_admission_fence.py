"""Qualification Profile admission fence + repository lock order guard (S5-08 · #704).

``QualificationProfileAdmissionFence`` 는 Profile policy mutation(initialize/register/revoke)과
exact policy observation 을 선형화하는 **process-local shared registry** 다. key 는
``qualification_profile_id`` 하나 — root 경로·process session 이 아니다. store writer lease 가
아니라 policy 선형화 fence 다.

repository global lock order(바깥→안):

    QualificationProfileAdmissionFence → PerWorkMutationFence → 단일 Store writer lease

이 순서를 thread-local held-lock ledger 로 강제한다. 안쪽 lock 을 쥔 채 바깥 lock 을 기다리면
deadlock 위험이라 시끄럽게 거절한다(WorkFence 보유 뒤 ProfileFence 대기, Store lease 보유 뒤
ProfileFence/WorkFence 대기). 실제 WorkFence/Store lease 의 ledger 참여 결선은 S5-09 가 소유한다 —
여기서는 세 rank 의 guard context manager 와 ProfileFence 참여만 제공한다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

# lock rank(작을수록 바깥) — 획득은 rank 오름차순만 허용한다.
PROFILE_FENCE_RANK = 0
WORK_FENCE_RANK = 1
STORE_LEASE_RANK = 2
_RANK_NAMES = {
    PROFILE_FENCE_RANK: "QualificationProfileAdmissionFence",
    WORK_FENCE_RANK: "PerWorkMutationFence",
    STORE_LEASE_RANK: "StoreWriterLease",
}


class ProfileFenceRegistryIntegrityError(Exception):
    """profile-admission fence registry 가 중복·손상 — 같은 key lock 을 분리하지 않는다."""

    code = "PROFILE_FENCE_REGISTRY_INTEGRITY_ERROR"


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
    """PerWorkMutationFence 획득 자리를 lock-order ledger 에 표시한다(S5-09 가 실제 fence 에 감쌈)."""
    with lock_order_rank(WORK_FENCE_RANK):
        yield


@contextmanager
def store_lease_order_guard() -> Iterator[None]:
    """단일 Store writer lease 획득 자리를 lock-order ledger 에 표시한다(S5-09 배선)."""
    with lock_order_rank(STORE_LEASE_RANK):
        yield


_registry: dict[str, threading.Lock] = {}
_registry_guard = threading.Lock()


def _fence_lock(qualification_profile_id: str) -> threading.Lock:
    """profile_id 별 공유 fence lock — 같은 id 는 항상 같은 lock object(root 무관)."""
    with _registry_guard:
        lock = _registry.get(qualification_profile_id)
        if lock is None:
            lock = threading.Lock()  # 비재진입: correctness 가 reentrancy 에 의존하지 않는다
            _registry[qualification_profile_id] = lock
        return lock


def guard_single_registry(candidate: dict[str, threading.Lock]) -> None:
    """같은 key lock 을 분리하려는 두 번째 registry 를 거절한다(process 전역 하나만 authoritative).

    S5-09 이후 fence 참여자가 늘어도 registry 는 이 모듈의 ``_registry`` 하나여야 한다 —
    사본을 만들어 자기 lock 을 배분하면 같은 Profile 을 두 lock 이 지키게 돼 선형화가 깨진다.
    """
    if candidate is not _registry:
        raise ProfileFenceRegistryIntegrityError(
            "profile-admission fence 는 process 전역 registry 하나만 쓴다(사본으로 lock 분리 금지)"
        )


@contextmanager
def profile_admission_fence(qualification_profile_id: str) -> Iterator[None]:
    """같은 Profile 의 admission command·observation 을 직렬화한다(process-local, 비재진입).

    lock order 의 가장 바깥(rank 0)이다 — 획득 시 이미 WorkFence·Store lease 를 쥐고 있으면
    거절한다. under-fence helper 는 fence 를 재획득하지 않는다(그렇게 하면 deadlock).
    """
    if not qualification_profile_id:
        raise ValueError("profile fence key 의 qualification_profile_id 는 비어 있을 수 없다")
    with lock_order_rank(PROFILE_FENCE_RANK):
        with _fence_lock(qualification_profile_id):
            yield
