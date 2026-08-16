"""per-Work fence 계약(S4-05 · #675): ``*_under_fence`` helper 는 정의 모듈 밖에서 호출되지 않는다.

production 코드가 fence 를 우회해 under-fence helper 를 직접 부르면 S3 Apply·S4 mutation 선형화가
깨진다. 그 우회를 정적으로 막는다 — under-fence helper 는 정의 모듈의 fence-획득 public entry
에서만 참조돼야 한다. 새 S4 command 가 같은 패턴(``*_under_fence``)을 쓰면 이 게이트가 함께 문다.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "hwpxfiller"


def _under_fence_defs() -> dict[str, Path]:
    """src 전역의 ``def *_under_fence`` 이름 → 정의 파일."""
    defs: dict[str, Path] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.endswith("_under_fence"):
                defs[node.name] = path
    return defs


def test_under_fence_helpers_exist() -> None:
    # 뿌리 계약이 성립하려면 최소 하나(S3 Apply)는 있어야 한다 — 오탐 방지 양성 대조.
    defs = _under_fence_defs()
    assert "apply_prepared_change_under_fence" in defs


def test_under_fence_helpers_not_referenced_outside_defining_module() -> None:
    defs = _under_fence_defs()
    names = set(defs)
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # ast.Name(직접 import 호출)·ast.Attribute(module.helper 접근) 둘 다 잡는다 —
            # 한쪽만 보면 게이트 정의역이 우회 호출을 안 담는다.
            referenced = None
            if isinstance(node, ast.Name) and node.id in names:
                referenced = node.id
            elif isinstance(node, ast.Attribute) and node.attr in names:
                referenced = node.attr
            if referenced is not None and path != defs[referenced]:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno} → {referenced}")
    assert not offenders, (
        "under-fence helper 를 정의 모듈 밖에서 참조했다(fence 우회 위험): " + "; ".join(offenders)
    )
