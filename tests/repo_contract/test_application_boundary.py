"""P2가 세운 물리 Application 경계와 legacy facade 형상을 검증한다."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]
APPLICATION_PACKAGE = ROOT / "src" / "hwpxfiller" / "application"
LEGACY_FACADE = ROOT / "src" / "hwpxfiller" / "gui" / "dataset_pool_state.py"
PUBLIC_API = (
    "DatasetPoolPort",
    "PoolAction",
    "DatasetPoolRow",
    "DatasetPoolViewModel",
    "available_actions",
    "kind_transition_clause",
    "reference_summary",
)
ALLOWED_INTERNAL_PREFIXES = (
    "hwpxfiller.application",
    "hwpxfiller.domain",
    # 아직 Application으로 물리 이관되지 않은 같은 링의 기간 검증 권위.
    "hwpxfiller.gui.nara_state",
)
CONCRETE_ADAPTER_ROOTS = {"lxml", "openpyxl", "webview"}


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


def test_hwpxfiller_application_imports_point_inward() -> None:
    """Application은 Domain·같은 Application 협력자만 알고 adapter/host를 모른다."""
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in sorted(APPLICATION_PACKAGE.rglob("*.py"))
        for module, lineno in _imports(path)
        if _is_outward(module)
    ]
    assert not offenders, "Application의 바깥 방향 import:\n" + "\n".join(offenders)


def test_dataset_pool_legacy_facade_only_reexports_application_objects() -> None:
    """구 GUI 경로는 정의·wrapper 없이 Application 공개 객체만 다시 노출한다."""
    tree = ast.parse(
        LEGACY_FACADE.read_text(encoding="utf-8"), filename=str(LEGACY_FACADE)
    )
    definitions = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert not definitions, f"legacy facade에 새 정의가 있습니다: {definitions}"

    application_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "hwpxfiller.application.dataset_pool"
        and node.level == 0
    ]
    assert len(application_imports) == 1
    imported = [(alias.name, alias.asname) for alias in application_imports[0].names]
    assert imported == [(name, None) for name in PUBLIC_API]

    assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
    assert len(assignments) == 1
    assignment = assignments[0]
    assert [target.id for target in assignment.targets if isinstance(target, ast.Name)] == [
        "__all__"
    ]
    assert tuple(ast.literal_eval(assignment.value)) == PUBLIC_API

    allowed_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            allowed_nodes.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "__future__",
            "hwpxfiller.application.dataset_pool",
        }:
            allowed_nodes.append(node)
        elif node is assignment:
            allowed_nodes.append(node)
    assert allowed_nodes == tree.body
