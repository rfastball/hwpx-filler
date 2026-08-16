"""Profile admission fence + lock order guard(S5-08 · #704)."""

from __future__ import annotations

import threading

import pytest

from hwpxfiller.host.profile_admission_fence import (
    LockOrderViolation,
    ProfileFenceRegistryIntegrityError,
    _fence_lock,
    _registry,
    guard_single_registry,
    profile_admission_fence,
    store_lease_order_guard,
    work_fence_order_guard,
)


# ── fence identity ────────────────────────────────────────────────────────────
def test_same_profile_shares_one_fence() -> None:
    # key 는 profile_id 하나 — 서로 다른 root store 가 각자 불러도 같은 lock object.
    assert _fence_lock("P1") is _fence_lock("P1")


def test_different_profiles_independent() -> None:
    assert _fence_lock("P1") is not _fence_lock("P2")


def test_empty_profile_id_rejected() -> None:
    with pytest.raises(ValueError):
        with profile_admission_fence(""):
            pass


def test_same_profile_serialized() -> None:
    order: list[str] = []
    started = threading.Event()

    def hold() -> None:
        with profile_admission_fence("P-ser"):
            order.append("B:enter")

    with profile_admission_fence("P-ser"):
        t = threading.Thread(target=hold)
        t.start()
        assert not started.wait(0.15)  # B 는 fence 밖에서 대기
        order.append("A:inside")
    t.join(2)
    assert order == ["A:inside", "B:enter"]


# ── lock order ────────────────────────────────────────────────────────────────
def test_positive_order_profile_work_store() -> None:
    with profile_admission_fence("P-order"):
        with work_fence_order_guard():
            with store_lease_order_guard():
                pass  # ProfileFence → WorkFence → Store 는 허용


def test_work_fence_then_profile_rejected() -> None:
    with work_fence_order_guard():
        with pytest.raises(LockOrderViolation):
            with profile_admission_fence("P-x"):
                pass


def test_store_lease_then_profile_rejected() -> None:
    with store_lease_order_guard():
        with pytest.raises(LockOrderViolation):
            with profile_admission_fence("P-x"):
                pass


def test_store_lease_then_work_fence_rejected() -> None:
    with store_lease_order_guard():
        with pytest.raises(LockOrderViolation):
            with work_fence_order_guard():
                pass


def test_ledger_unwinds_after_violation() -> None:
    # 위반으로 raise 한 뒤에도 ledger 가 오염되지 않아 이후 정상 획득이 가능하다.
    with work_fence_order_guard():
        with pytest.raises(LockOrderViolation):
            with profile_admission_fence("P-x"):
                pass
    with profile_admission_fence("P-x"):  # ledger 비었으니 다시 바깥부터 정상
        pass


# ── registry 중복 방지 ───────────────────────────────────────────────────────────
def test_registry_singleton_guard() -> None:
    guard_single_registry(_registry)  # authoritative registry 는 통과
    with pytest.raises(ProfileFenceRegistryIntegrityError):
        guard_single_registry({})  # 사본으로 같은 key lock 분리 시도 → 거절
