"""P2가 세운 물리 Application 경계와 legacy facade 형상을 검증한다."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


ROOT = Path(__file__).parents[2]
APPLICATION_PACKAGE = ROOT / "src" / "hwpxfiller" / "application"
LEGACY_FACADES = (
    (
        ROOT / "src" / "hwpxfiller" / "gui" / "dataset_pool_state.py",
        "hwpxfiller.application.dataset_pool",
        (
            "DatasetPoolPort",
            "PoolAction",
            "DatasetPoolRow",
            "DatasetPoolViewModel",
            "available_actions",
            "kind_transition_clause",
            "reference_summary",
        ),
    ),
    (
        ROOT / "src" / "hwpxfiller" / "gui" / "nara_state.py",
        "hwpxfiller.application.nara_acquire",
        (
            "DT_FMT",
            "AcquiredNaraData",
            "AcquireResult",
            "ConnResult",
            "NaraAcquireViewModel",
        ),
    ),
)
ALLOWED_INTERNAL_PREFIXES = (
    "hwpxfiller.application",
    "hwpxfiller.domain",
    # core/job.py 는 P2-21 1단계에서 저장·잠금 물리를 external/host 로 내리고 Domain 순수로
    # 남았다(handoff unit target=DOMAIN). 물리 domain/ 이관 전까지 Application 이 이 모듈의
    # 값 계약(Job)을 아는 것은 inward 다 — core 전체가 아니라 이 모듈만 허용한다.
    "hwpxfiller.core.job",
    # batch.py 와 gui/run_state.py 는 handoff unit target=APPLICATION(물리 이관 전) —
    # 생성 use case(application/generation.py)의 동륜이라 직접 소비가 inward 다.
    # core.job 과 같은 과도기 허용이며 물리 application/ 이관 시 이 두 줄도 옮겨 없앤다.
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


def test_application_legacy_facades_only_reexport_same_objects() -> None:
    """구 GUI 경로는 정의·wrapper 없이 canonical 객체를 그대로 다시 노출한다."""
    for legacy_facade, application_module, public_api in LEGACY_FACADES:
        tree = ast.parse(
            legacy_facade.read_text(encoding="utf-8"), filename=str(legacy_facade)
        )
        definitions = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            )
        ]
        assert not definitions, (
            f"{legacy_facade.relative_to(ROOT)}에 새 정의가 있습니다: {definitions}"
        )

        application_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == application_module
            and node.level == 0
        ]
        assert len(application_imports) == 1, legacy_facade.relative_to(ROOT)
        imported = [(alias.name, alias.asname) for alias in application_imports[0].names]
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
                application_module,
            }:
                allowed_nodes.append(node)
            elif node is assignment:
                allowed_nodes.append(node)
        assert allowed_nodes == tree.body

        legacy_module = importlib.import_module(_module_for_path(legacy_facade))
        canonical_module = importlib.import_module(application_module)
        assert all(
            getattr(legacy_module, name) is getattr(canonical_module, name)
            for name in public_api
        )
