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


def test_hwpxdiff_core_module_is_qt_free() -> None:
    """hwpxdiff/diff.py(+cli.py)는 stdlib+hwpxcore 만 — 성형·그룹화·렌더 로직이 뷰로
    돌아가 GUI/CLI 표면이 갈라지는 회귀(RC-17)를 막는다."""
    for module in ("diff.py", "cli.py"):
        path = ROOT / "src" / "hwpxdiff" / module
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any(n.split(".", 1)[0] in ("PySide6", "shiboken6") for n in names), (
                f"hwpxdiff/{module} 에 Qt 임포트가 들어왔다 — 순수 계층을 지켜라"
            )


def test_core_mapping_carries_no_source_specific_vocabulary() -> None:
    """범용 코어(core/mapping.py)는 특정 API 어휘를 품지 않는다(V1 소스 어휘 소유권).

    어휘(예: 나라장터 영문 코드 키·NARA_ALIASES)는 소유 소스(data/nara.py)로
    승격됐다. suggest_mappings 의 aliases 는 순수 범용 인자다 — 코어에 API별
    문자열이 새로 스며들면 README "core = no product logic" 규칙 위반을 알린다.
    """
    text = (ROOT / "src" / "hwpxfiller" / "core" / "mapping.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("NARA_ALIASES", "bidNtce", "presmptPrce", "opengDate"):
        assert forbidden not in text, (
            f"core/mapping.py 에 소스별 어휘 {forbidden!r} 가 남아 있다 — 소스로 승격하라"
        )
