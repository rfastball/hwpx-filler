from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _import_roots(package: str) -> set[str]:
    roots: set[str] = set()
    for path in (ROOT / "src" / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_products_do_not_import_each_other() -> None:
    assert "hwpxfiller" not in _import_roots("hwpxdiff")
    assert "hwpxdiff" not in _import_roots("hwpxfiller")
