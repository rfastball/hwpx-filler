"""P2가 세운 물리 Domain 경계를 검증한다 — legacy facade 는 #538 에서 소멸했다."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]
DOMAIN_PACKAGE = ROOT / "src" / "hwpxfiller" / "domain"
ALLOWED_INTERNAL_PREFIXES = ("hwpxfiller.domain", "hwpxcore.domain")
CONCRETE_ADAPTER_ROOTS = {"lxml", "openpyxl", "webview"}
def _module_for_path(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(package: str, *, level: int, module: str | None) -> str:
    if not level:
        return module or ""
    parts = package.split(".") if package else []
    keep = len(parts) - (level - 1)
    base = parts[: max(keep, 0)]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _imports(path: Path) -> list[tuple[str, int]]:
    source = _module_for_path(path)
    package = source if path.name == "__init__.py" else source.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(package, level=node.level, module=node.module)
            if base:
                result.append((base, node.lineno))
            # 멤버까지 편다 — `from ..data import base` 처럼 패키지+멤버로 쪼갠 형이 base 로만
            # 접히면 모듈 단위 금지선(방향·facade 소비자)을 그대로 통과한다(기존 External
            # 경계 게이트의 관용구를 여기에도 맞춘다).
            result.extend(
                (f"{base}.{alias.name}" if base else alias.name, node.lineno)
                for alias in node.names
                if alias.name != "*"
            )
    return result


def _is_outward(module: str) -> bool:
    root = module.split(".", 1)[0]
    if root in CONCRETE_ADAPTER_ROOTS:
        return True
    if root not in {"hwpxcore", "hwpxfiller"}:
        return False
    return not any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in ALLOWED_INTERNAL_PREFIXES
    )


def test_hwpxfiller_domain_imports_point_inward() -> None:
    """Domain은 자기 경계나 독립 format Domain만 알고 바깥 제품 층은 모른다."""
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in sorted(DOMAIN_PACKAGE.rglob("*.py"))
        for module, lineno in _imports(path)
        if _is_outward(module)
    ]
    assert not offenders, "Domain의 바깥 방향 import:\n" + "\n".join(offenders)
