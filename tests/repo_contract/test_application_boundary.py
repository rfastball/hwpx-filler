"""P2가 세운 물리 Application 경계를 검증한다 — legacy facade 는 #538 에서 소멸했다."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]
APPLICATION_PACKAGE = ROOT / "src" / "hwpxfiller" / "application"
ALLOWED_INTERNAL_PREFIXES = (
    "hwpxfiller.application",
    "hwpxfiller.domain",
    # batch.py 와 gui/run_state.py 는 handoff unit target=APPLICATION(물리 이관 전) —
    # 생성 use case(application/generation.py)의 동륜이라 직접 소비가 inward 다.
    # 물리 application/ 이관 시 이 두 줄도 옮겨 없앤다.
    "hwpxfiller.batch",
    "hwpxfiller.gui.run_state",
)
CONCRETE_ADAPTER_ROOTS = {
    "aiohttp",
    "http",
    "httpx",
    "keyring",
    "lxml",
    "openpyxl",
    "requests",
    "socket",
    "ssl",
    "urllib",
    "webview",
    "win32cred",
    "win32crypt",
}
CLOCK_CALLS = {
    "datetime.date.today",
    "datetime.datetime.now",
    "datetime.datetime.today",
    "datetime.datetime.utcnow",
    "time.monotonic",
    "time.perf_counter",
    "time.time",
}


def _module_for_path(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(package: str, *, level: int, module: "str | None") -> str:
    if not level:
        return module or ""
    parts = package.split(".") if package else []
    keep = len(parts) - (level - 1)
    base = parts[: max(keep, 0)]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _imports(path: Path) -> "list[tuple[str, int]]":
    source = _module_for_path(path)
    package = source if path.name == "__init__.py" else source.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: "list[tuple[str, int]]" = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(package, level=node.level, module=node.module)
            if base:
                result.append((base, node.lineno))
            if node.level and node.module is None:
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


def _import_aliases(tree: ast.AST) -> "dict[str, str]":
    aliases: "dict[str, str]" = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                aliases[local] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in {"datetime", "time"}:
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _qualified_name(node: ast.expr, aliases: "dict[str, str]") -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def test_hwpxfiller_application_imports_point_inward() -> None:
    """Application은 inward 계약만 알고 network·wall clock 구현을 직접 고르지 않는다."""
    paths = sorted(APPLICATION_PACKAGE.rglob("*.py"))
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in paths
        for module, lineno in _imports(path)
        if _is_outward(module)
    ]
    assert not offenders, "Application의 바깥 방향 import:\n" + "\n".join(offenders)

    clock_references = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _import_aliases(tree)
        clock_references.extend(
            f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: "
            f"{_qualified_name(node, aliases)}"
            for node in ast.walk(tree)
            if isinstance(node, (ast.Attribute, ast.Name))
            and _qualified_name(node, aliases) in CLOCK_CALLS
        )
    assert not clock_references, "Application의 직접 wall-clock 선택:\n" + "\n".join(
        clock_references
    )
