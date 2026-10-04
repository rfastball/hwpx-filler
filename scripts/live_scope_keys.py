"""부분 실창 범위 — `TestWebSelftestGate` 의 테스트가 읽는 증거 키를 정적으로 찾는 층.

부분 실행은 선택 닫힘이 내는 키만 읽는 selftest 테스트를 남긴다. 그러려면 테스트마다 읽는 키를
알아야 하고, 못 읽은 테스트는 ``None`` 이다 — 빈 키로 통과시키거나 조용히 빼지 않는다.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELFTEST_GATE_PATH = ROOT / "tests" / "test_web_selftest_gate.py"
#: selftest 게이트의 단일 부팅 소비자 — 이 클래스의 테스트는 키로 고른다.
SELFTEST_GATE_NODE = "tests/test_web_selftest_gate.py"
SELFTEST_GATE_CLASS = "TestWebSelftestGate"
SELFTEST_FIXTURE = "selftest_result"
#: 특정 프로브가 아니라 실행 전체를 말하는 키(실패한 프로브가 남기는 사유).
RUN_WIDE_KEYS = frozenset({"error"})

#: (픽스처로 보이는 노드, 키 노드) — 키 노드가 없으면 ``None``.
_Read = "tuple[ast.AST, ast.AST | None] | None"


def _literal(node: "ast.AST | None") -> "str | None":
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_fixture(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == SELFTEST_FIXTURE


def _subscript_read(node: ast.AST) -> _Read:
    """``selftest_result["k"]``."""
    return (node.value, node.slice) if isinstance(node, ast.Subscript) else None


def _get_read(node: ast.AST) -> _Read:
    """``selftest_result.get("k")``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return node.func.value, (node.args[0] if node.args else None)
    return None


def _probe_read(node: ast.AST) -> _Read:
    """``probe(selftest_result, "k")``."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "probe"
        and len(node.args) == 2
    ):
        return node.args[0], node.args[1]
    return None


def _contains_read(node: ast.AST) -> _Read:
    """``"k" in selftest_result`` · ``not in``."""
    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.In, ast.NotIn))
    ):
        return node.comparators[0], node.left
    return None


_READERS: "tuple[Callable[[ast.AST], tuple[ast.AST, ast.AST | None] | None], ...]" = (
    _subscript_read,
    _get_read,
    _probe_read,
    _contains_read,
)


def _key_read(node: ast.AST) -> "tuple[ast.AST, ast.AST | None] | None":
    for reader in _READERS:
        found = reader(node)
        if found is not None and _is_fixture(found[0]):
            return found
    return None


def _unaccounted_use(func: ast.FunctionDef, accounted: "set[int]") -> bool:
    """인정한 읽기 밖에서 픽스처를 쓰는가(헬퍼에 통째로 넘기기·순회 등)."""
    return any(
        _is_fixture(node) and isinstance(node.ctx, ast.Load) and id(node) not in accounted
        for node in ast.walk(func)
        if isinstance(node, ast.Name)
    )


def _function_keys(func: ast.FunctionDef) -> "frozenset[str] | None":
    keys: set[str] = set()
    accounted: set[int] = set()
    for node in ast.walk(func):
        found = _key_read(node)
        if found is None:
            continue
        key = _literal(found[1])
        if key is None:
            return None
        keys.add(key)
        accounted.add(id(found[0]))
    if not keys or _unaccounted_use(func, accounted):
        return None
    return frozenset(keys)


def selftest_test_keys(source: str) -> "dict[str, frozenset[str] | None]":
    """`TestWebSelftestGate` 의 테스트마다 읽는 증거 키 — 정적으로 못 정하면 ``None``.

    인정하는 읽기: ``selftest_result["k"]`` · ``selftest_result.get("k")`` ·
    ``"k" in selftest_result`` · ``probe(selftest_result, "k")``. 그 밖의 사용(헬퍼에 통째로
    넘기기·순회·동적 키)은 ``None`` 이고, 계약 테스트가 그 테스트를 실패시킨다.
    """
    tree = ast.parse(source)
    found: dict[str, "frozenset[str] | None"] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == SELFTEST_GATE_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    found[item.name] = _function_keys(item)
    return found


def keep_selftest_test(keys: "frozenset[str] | None", produced: frozenset[str]) -> bool:
    """부분 실행에 남는가 — 읽는 키가 전부 선택 닫힘이 낸 키여야 한다(실행 전체 키 제외)."""
    if keys is None:
        return False
    return keys - RUN_WIDE_KEYS <= produced
