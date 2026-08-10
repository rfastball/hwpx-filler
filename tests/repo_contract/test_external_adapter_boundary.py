"""External Adapter는 안쪽에서 참조되지 않고 Frontend runtime을 모른다."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
EXTERNAL_PACKAGE = "hwpxfiller.external"
EXTERNAL_ROOT = SRC / "hwpxfiller" / "external"
LEGACY_FACADE = SRC / "hwpxfiller" / "webapp" / "settings.py"
CANONICAL_SETTINGS = EXTERNAL_ROOT / "settings.py"
PUBLIC_API = (
    "VALID_THEMES",
    "VALID_FONT_SCALES",
    "DEFAULT_MASTER_WIDTH",
    "MIN_MASTER_WIDTH",
    "MAX_MASTER_WIDTH",
    "VALID_DRAFT_FONTS",
    "PROPORTIONAL_DRAFT_FONTS",
    "BOOT_STAMP_UNKNOWN_VERSION",
    "VALID_TEMPLATE_MEDIA",
    "is_proportional_font",
    "alert",
    "home_dir",
    "load_theme",
    "save_theme",
    "load_font_scale",
    "save_font_scale",
    "load_master_width",
    "save_master_width",
    "load_window_geometry",
    "save_window_geometry",
    "load_draft_target_font",
    "save_draft_target_font",
    "load_boot_completed",
    "save_boot_completed",
    "load_job_collapsed_groups",
    "recollapse_job_group",
    "save_job_collapsed_groups",
    "load_template_group_map",
    "save_template_group_map",
    "load_template_collapsed_groups",
    "save_template_collapsed_groups",
    "save_template_group_state",
)

# 존재하지 않는 미래 Application 경로도 생성되는 순간 같은 금지선에 들어온다.
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


def _all_assignment(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert len(assignments) == 1
    return tuple(ast.literal_eval(assignments[0].value))


def test_inward_packages_do_not_import_external_adapters() -> None:
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in _inward_sources()
        for module, lineno in _resolved_imports(path)
        if module == EXTERNAL_PACKAGE or module.startswith(f"{EXTERNAL_PACKAGE}.")
    ]
    assert not offenders, "Domain/Application→External Adapter 역의존:\n" + "\n".join(offenders)


def test_external_package_is_no_reexport_shell_and_avoids_frontend_runtime() -> None:
    shell = EXTERNAL_ROOT / "__init__.py"
    shell_tree = ast.parse(shell.read_text(encoding="utf-8"), filename=str(shell))
    shell_code = [
        node
        for node in shell_tree.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    assert not shell_code, "External Adapter package shell에 재수출·실행 코드가 있습니다"

    forbidden = ("hwpxfiller.webapp", "webview", "pywebview")
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in sorted(EXTERNAL_ROOT.rglob("*.py"))
        for module, lineno in _resolved_imports(path)
        if any(module == name or module.startswith(f"{name}.") for name in forbidden)
    ]
    assert not offenders, "External Adapter→Frontend runtime 의존:\n" + "\n".join(offenders)


def test_settings_legacy_facade_only_reexports_external_objects() -> None:
    assert _all_assignment(CANONICAL_SETTINGS) == PUBLIC_API
    assert _all_assignment(LEGACY_FACADE) == PUBLIC_API

    tree = ast.parse(
        LEGACY_FACADE.read_text(encoding="utf-8"), filename=str(LEGACY_FACADE)
    )
    definitions = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    assert not definitions, f"legacy facade에 새 정의가 있습니다: {definitions}"

    canonical_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "hwpxfiller.external.settings"
        and node.level == 0
    ]
    assert len(canonical_imports) == 1
    imported = {(alias.name, alias.asname) for alias in canonical_imports[0].names}
    assert imported == {
        (name, None) for name in (*PUBLIC_API, "_check_media", "_settings_path")
    }

    assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
    assert len(assignments) == 1
    assignment = assignments[0]
    assert len(assignment.targets) == 1
    assert isinstance(assignment.targets[0], ast.Name)
    assert assignment.targets[0].id == "__all__"

    allowed_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            allowed_nodes.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "__future__",
            "hwpxfiller.external.settings",
        }:
            allowed_nodes.append(node)
        elif node is assignment:
            allowed_nodes.append(node)
    assert allowed_nodes == tree.body
