"""per-Work mutation fence(S4-05 · #675): identity·직렬화·fence-first 위임."""

from __future__ import annotations

import threading

import pytest

from hwpxfiller.external import prepare_orchestration_runner as runner
from hwpxfiller.host.per_work_fence import (
    PerWorkMutationFenceKey,
    _fence_lock,
    per_work_mutation_fence,
)


# ── identity ──────────────────────────────────────────────────────────────────
def test_same_workspace_and_work_share_one_fence() -> None:
    key = PerWorkMutationFenceKey("ws-1", "W1")
    # S3 와 S4 가 각자 부르는 두 호출(root 는 key 에 없다)이 같은 lock object 를 받는다.
    assert _fence_lock(key) is _fence_lock(PerWorkMutationFenceKey("ws-1", "W1"))


def test_different_workspace_or_work_get_different_fences() -> None:
    base = _fence_lock(PerWorkMutationFenceKey("ws-1", "W1"))
    assert base is not _fence_lock(PerWorkMutationFenceKey("ws-2", "W1"))
    assert base is not _fence_lock(PerWorkMutationFenceKey("ws-1", "W2"))


def test_empty_fence_key_rejected() -> None:
    with pytest.raises(ValueError):
        with per_work_mutation_fence("", "W1"):
            pass
    with pytest.raises(ValueError):
        with per_work_mutation_fence("ws-1", ""):
            pass


# ── serialization ─────────────────────────────────────────────────────────────
def test_same_work_commands_are_serialized() -> None:
    order: list[str] = []
    started = threading.Event()

    def hold(tag: str) -> None:
        with per_work_mutation_fence("ws-ser", "W-ser"):
            order.append(f"{tag}:enter")
            started.set()
            order.append(f"{tag}:exit")

    with per_work_mutation_fence("ws-ser", "W-ser"):
        t = threading.Thread(target=hold, args=("B",))
        t.start()
        # B 는 fence 를 기다리며 진입 못 한다 — 이 블록이 끝나야 들어온다.
        assert not started.wait(0.2)
        order.append("A:inside")
    t.join(2)
    # A 가 fence 를 온전히 쥐는 동안 B 는 절대 끼어들지 못한다.
    assert order == ["A:inside", "B:enter", "B:exit"]


def test_different_works_run_concurrently() -> None:
    a_in = threading.Event()
    b_in = threading.Event()

    def hold(ev: threading.Event, work: str) -> None:
        with per_work_mutation_fence("ws-c", work):
            ev.set()
            assert (a_in if work == "WB" else b_in).wait(2)  # 서로가 동시에 안에 있다

    ta = threading.Thread(target=hold, args=(a_in, "WA"))
    tb = threading.Thread(target=hold, args=(b_in, "WB"))
    ta.start()
    tb.start()
    assert a_in.wait(2) and b_in.wait(2)  # 다른 Work 는 동시 보유 가능
    ta.join(2)
    tb.join(2)


# ── fence-first 위임 ────────────────────────────────────────────────────────────
def test_public_apply_holds_fence_before_delegating(monkeypatch: pytest.MonkeyPatch) -> None:
    key = PerWorkMutationFenceKey("ws-app", "W-app")
    seen = {}

    def spy(*_a: object, **_k: object) -> str:
        seen["held"] = _fence_lock(key).locked()  # helper 실행 시 fence 가 잡혀 있어야 한다
        return "sentinel"

    monkeypatch.setattr(runner, "apply_prepared_change_under_fence", spy)
    result = runner.apply_prepared_change(
        None, None, None, workspace_instance_id="ws-app", work_id="W-app",
        change_id="C", actor="a", authorize=lambda _w, _a: None,
        new_application_id="A", provenance_id="P", outbox_event_id="O", applied_at="t",
    )
    assert result == "sentinel"
    assert seen["held"] is True
    assert not _fence_lock(key).locked()  # 반환 뒤 해제
