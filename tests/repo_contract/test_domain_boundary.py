"""P2가 세운 물리 Domain 경계와 legacy facade 형상을 검증한다."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]
DOMAIN_PACKAGE = ROOT / "src" / "hwpxfiller" / "domain"
LEGACY_FACADES = (
    (
        ROOT / "src" / "hwpxfiller" / "core" / "identity_summary.py",
        "hwpxfiller.domain.identity_summary",
        (
            "BLANK_CELL_MARK",
            "COGNITION_WIDTH",
            "MAX_COLUMNS",
            "DisqualifierStats",
            "SummaryStep",
            "IdentitySummary",
            "identity_summary",
        ),
    ),
    (
        ROOT / "src" / "hwpxfiller" / "core" / "source_profile.py",
        "hwpxfiller.domain.source_profile",
        ("SAMPLE_N", "FieldProfile", "tentative_type", "profile_fields"),
    ),
)
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


def test_hwpxfiller_domain_imports_point_inward() -> None:
    """Domain은 자기 경계나 독립 format Domain만 알고 바깥 제품 층은 모른다."""
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{lineno}: {module}"
        for path in sorted(DOMAIN_PACKAGE.rglob("*.py"))
        for module, lineno in _imports(path)
        if _is_outward(module)
    ]
    assert not offenders, "Domain의 바깥 방향 import:\n" + "\n".join(offenders)


def test_legacy_facades_only_reexport_domain_objects() -> None:
    """구 경로는 정의·wrapper 없이 각 새 정본의 공개 이름만 다시 노출한다."""
    for legacy_facade, domain_module, public_api in LEGACY_FACADES:
        tree = ast.parse(
            legacy_facade.read_text(encoding="utf-8"), filename=str(legacy_facade)
        )
        definitions = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert not definitions, (
            f"{legacy_facade.relative_to(ROOT)}에 새 정의가 있습니다: {definitions}"
        )

        domain_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == domain_module
            and node.level == 0
        ]
        assert len(domain_imports) == 1, legacy_facade.relative_to(ROOT)
        imported = [(alias.name, alias.asname) for alias in domain_imports[0].names]
        assert imported == [(name, None) for name in public_api]

        assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
        assert len(assignments) == 1, legacy_facade.relative_to(ROOT)
        assignment = assignments[0]
        assert [
            target.id for target in assignment.targets if isinstance(target, ast.Name)
        ] == ["__all__"]
        assert tuple(ast.literal_eval(assignment.value)) == public_api

        allowed_nodes = []
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                allowed_nodes.append(node)
            elif isinstance(node, ast.ImportFrom) and node.module in {
                "__future__",
                domain_module,
            }:
                allowed_nodes.append(node)
            elif node is assignment:
                allowed_nodes.append(node)
        assert allowed_nodes == tree.body
