"""S3 Apply 의 global lock-order 배선 정적 계약 (S5-09 · #705).

repository 전역 순서는 ``QualificationProfileAdmissionFence → PerWorkMutationFence →
S3 WorkTemplateStateStore writer lease`` 다. 이 게이트는 S3 public Apply 가 그 순서로
fence 를 획득하고(WorkFence-before-ProfileFence lexical path 0), WorkFence·Store lease 가
shared lock-order ledger 에 참여하며, public Apply call path 가 admission query 에 실제
도달함을 정적으로 증명한다. 런타임 거절(역순 LockOrderViolation)과 실제 write-0 정책은
``tests/test_profile_admission_fence.py`` 와 ``tests/test_template_apply.py`` 가 진다.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "hwpxfiller"
RUNNER = SRC / "external" / "prepare_orchestration_runner.py"
WORK_FENCE = SRC / "host" / "per_work_fence.py"
WORK_STORE = SRC / "external" / "work_template_store.py"
PROFILE_FENCE_MODULE = "hwpxfiller.host.profile_admission_fence"

_PROFILE_FENCE_CALLS = {"profile_fence", "profile_admission_fence"}


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


def _with_call_line(func: ast.FunctionDef, target: set[str] | str) -> int | None:
    """func 안에서 지정 호출을 여는 첫 ``with`` 의 lineno(없으면 None)."""
    wanted = {target} if isinstance(target, str) else target
    lines = [
        item.context_expr.lineno
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id in wanted
    ]
    return min(lines) if lines else None


# ── 순서: ProfileFence 가 WorkFence 보다 바깥(먼저) ────────────────────────────────
def test_apply_acquires_profile_fence_before_work_fence() -> None:
    apply = _func(_tree(RUNNER), "apply_prepared_change")
    profile_line = _with_call_line(apply, _PROFILE_FENCE_CALLS)
    work_line = _with_call_line(apply, "per_work_mutation_fence")
    assert profile_line is not None, "public Apply 가 ProfileFence 를 획득하지 않는다"
    assert work_line is not None, "public Apply 가 WorkFence 를 획득하지 않는다"
    # lexical 순서 = 획득 순서: ProfileFence 의 with 가 WorkFence 의 with 보다 앞선다.
    assert profile_line < work_line, "WorkFence-before-ProfileFence lexical path 는 0 이어야 한다"


# ── WorkFence·Store lease 가 shared lock-order ledger 에 참여 ─────────────────────
def test_work_fence_participates_in_order_ledger() -> None:
    fence = _func(_tree(WORK_FENCE), "per_work_mutation_fence")
    assert "work_fence_order_guard" in _call_names(fence)


def test_store_lease_participates_in_order_ledger() -> None:
    update = _func(_tree(WORK_STORE), "update")
    assert "store_lease_order_guard" in _call_names(update)


# ── shared registry: 사본이 아니라 host 정본 모듈에서 import ────────────────────────
def _imports_from(path: Path, module: str) -> set[str]:
    # 절대·상대 import 모두 잡도록 module 의 마지막 세그먼트로 비교한다
    # (relative ``from .profile_admission_runner`` 의 node.module 은 bare 이름이다).
    leaf = module.rsplit(".", 1)[-1]
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == module or node.module.rsplit(".", 1)[-1] == leaf
        ):
            names.update(a.name for a in node.names)
    return names


def test_shared_profile_fence_registry_imported() -> None:
    # runner·WorkFence 가 각자 host 정본 fence/guard 를 쓴다(사본 registry 금지).
    assert "profile_admission_fence" in _imports_from(RUNNER, PROFILE_FENCE_MODULE)
    assert "work_fence_order_guard" in _imports_from(WORK_FENCE, PROFILE_FENCE_MODULE)
    assert "store_lease_order_guard" in _imports_from(WORK_STORE, PROFILE_FENCE_MODULE)


# ── public Apply call path 가 under-fence helper 를 배선한다 ─────────────────────────
def test_public_apply_wires_under_fence_helper() -> None:
    # S5F R2-05a(#740): mutable Profile admission query(require_admitted·read_qualification_profile_
    # admission_under_fence)를 제거했다. public apply 는 여전히 ProfileFence→WorkFence 아래에서
    # under-fence helper 를 호출한다(admission gate 없이 exact qualification evidence 로 fail-closed).
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
