"""Host는 바깥 효과를 소유하고 Domain/Application은 Host를 찾지 않는다."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
HOST_PACKAGE = "hwpxfiller.host"

# 현 물리 패키지의 inward 층과 P2에서 생기는 명시 패키지를 함께 닫는다. 존재하지 않는 미래
# 경로는 건너뛰되, 생성되는 순간 같은 gate 모집단에 자동으로 들어온다.
INWARD_ROOTS = (
    SRC / "hwpxcore",
    SRC / "hwpxfiller" / "domain",
    SRC / "hwpxfiller" / "application",
    SRC / "hwpxfiller" / "core",
    SRC / "hwpxfiller" / "data",
    SRC / "hwpxfiller" / "gui",
)
INWARD_FILES = (
    SRC / "hwpxfiller" / "batch.py",
    SRC / "hwpxfiller" / "naming.py",
)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolved_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_name = _module_name(path)
    package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            parts = package.split(".") if package else []
            keep = len(parts) - (node.level - 1)
            base_parts = parts[: max(keep, 0)]
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
        else:
            base = node.module or ""
        if base:
            imports.append((base, node.lineno))
        imports.extend(
            (f"{base}.{alias.name}" if base else alias.name, node.lineno)
            for alias in node.names
            if alias.name != "*"
        )
    return imports


def _inward_sources() -> list[Path]:
    sources = [path for root in INWARD_ROOTS if root.is_dir() for path in root.rglob("*.py")]
    sources.extend(path for path in INWARD_FILES if path.is_file())
    return sorted(set(sources))


def test_inward_packages_do_not_import_host() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in _inward_sources()
        for module, lineno in _resolved_imports(path)
        if module == HOST_PACKAGE or module.startswith(f"{HOST_PACKAGE}.")
    ]
    assert not offenders, "Domain/Application→Host 역의존:\n" + "\n".join(offenders)


def test_host_does_not_import_frontend_runtime() -> None:
    forbidden = ("hwpxfiller.webapp", "webview", "pywebview")
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in sorted((SRC / "hwpxfiller" / "host").rglob("*.py"))
        for module, lineno in _resolved_imports(path)
        if any(module == name or module.startswith(f"{name}.") for name in forbidden)
    ]
    assert not offenders, "Host→Frontend runtime 의존:\n" + "\n".join(offenders)


def test_boot_budget_host_leaf_has_only_stdlib_inputs() -> None:
    path = SRC / "hwpxfiller" / "host" / "boot_budget.py"
    roots = {module.split(".", 1)[0] for module, _lineno in _resolved_imports(path)}
    assert roots <= {"__future__", "sys", "winreg"}, (
        f"boot_budget Host leaf에 외부 package 의존이 들어왔습니다: {sorted(roots)}"
    )
