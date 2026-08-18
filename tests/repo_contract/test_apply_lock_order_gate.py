"""S3 Apply 의 global lock-order 배선 정적 계약 (S5-09 · #705; S5F R2-05b · #740).

R2-05b: ``QualificationProfileAdmissionFence`` 를 제거했다. repository 전역 순서는 이제
``PerWorkMutationFence → S3 WorkTemplateStateStore writer lease`` 2-rank 다. 이 게이트는 S3 public
Apply 가 WorkFence 를 획득해 under-fence helper 를 호출하고, WorkFence·Store lease 가 shared
lock-order ledger 에 참여하며, guard 를 host 정본 ``per_work_fence`` 모듈에서 쓴다(사본 registry
금지)를 정적으로 증명한다. 런타임 거절(역순 LockOrderViolation)은 ``tests/test_per_work_fence.py``
가, write-0 정책은 ``tests/test_template_apply.py`` 가 진다.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "hwpxfiller"
RUNNER = SRC / "external" / "prepare_orchestration_runner.py"
WORK_FENCE = SRC / "host" / "per_work_fence.py"
WORK_STORE = SRC / "external" / "work_template_store.py"
FENCE_MODULE = "hwpxfiller.host.per_work_fence"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} 정의를 찾지 못했다")


def _call_names(node: ast.AST) -> list[str]:
    """node 하위 모든 호출의 (단순) 함수 이름."""
    names: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
            names.append(sub.func.id)
    return names


def _with_call_line(func: ast.FunctionDef, target: str) -> int | None:
    """func 안에서 지정 호출을 여는 첫 ``with`` 의 lineno(없으면 None)."""
    lines = [
        item.context_expr.lineno
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == target
    ]
    return min(lines) if lines else None


# ── apply 가 PerWorkFence 를 획득 ─────────────────────────────────────────────────
def test_apply_acquires_work_fence() -> None:
    # R2-05b: ProfileFence 제거로 public Apply 는 PerWorkFence 하나만 획득한다.
    apply = _func(_tree(RUNNER), "apply_prepared_change")
    work_line = _with_call_line(apply, "per_work_mutation_fence")
    assert work_line is not None, "public Apply 가 WorkFence 를 획득하지 않는다"


# ── WorkFence·Store lease 가 shared lock-order ledger 에 참여 ─────────────────────
def test_work_fence_participates_in_order_ledger() -> None:
    fence = _func(_tree(WORK_FENCE), "per_work_mutation_fence")
    assert "work_fence_order_guard" in _call_names(fence)


def test_store_lease_participates_in_order_ledger() -> None:
    update = _func(_tree(WORK_STORE), "update")
    assert "store_lease_order_guard" in _call_names(update)


# ── shared guard: 사본이 아니라 host 정본 per_work_fence 모듈에서 import ─────────────
def _imports_from(path: Path, module: str) -> set[str]:
    # 절대·상대 import 모두 잡도록 module 의 마지막 세그먼트로 비교한다.
    leaf = module.rsplit(".", 1)[-1]
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == module or node.module.rsplit(".", 1)[-1] == leaf
        ):
            names.update(a.name for a in node.names)
    return names


def test_lock_order_guards_from_host_module() -> None:
    # runner 는 host 정본 WorkFence 를, WORK_STORE 는 host 정본 store-lease guard 를 쓴다
    # (work_fence_order_guard 는 per_work_fence 가 직접 소유하므로 import census 대상이 아니다).
    assert "per_work_mutation_fence" in _imports_from(RUNNER, FENCE_MODULE)
    assert "store_lease_order_guard" in _imports_from(WORK_STORE, FENCE_MODULE)


# ── public Apply call path 가 under-fence helper 를 배선한다 ─────────────────────────
def test_public_apply_wires_under_fence_helper() -> None:
    # public apply 는 PerWorkFence 아래에서 under-fence helper 를 호출한다(admission gate 없이 exact
    # qualification evidence 로 fail-closed — R2-05a 로 mutable admission, R2-05b 로 ProfileFence 제거).
    tree = _tree(RUNNER)
    apply = _func(tree, "apply_prepared_change")
    under_fence_calls = [
        call
        for call in ast.walk(apply)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "apply_prepared_change_under_fence"
    ]
    assert under_fence_calls, "apply 가 under-fence helper 를 호출하지 않는다"
