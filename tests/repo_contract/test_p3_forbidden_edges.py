"""P3 이후 영속 public surface·forbidden edge·vendor integration 게이트.

정의역은 P2 ring 좌표, 실제 source tree, frontend runtime dependency다. 영속 예외와 공개
표면은 ``tests/architecture_contract.toml``과 양방향 대조하고, 퇴역 namespace·kernel
effect·vendor public type은 예외 없이 0을 요구한다.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

from _web_source import (
    ContractError,
    _frontend_sources,
    _frontend_specifiers,
    _js_masks,
    _resolve_frontend_module,
)


ROOT = Path(__file__).parents[2]
RINGS = ROOT / "docs" / "module_rings.toml"
CONTRACT = ROOT / "tests" / "architecture_contract.toml"

EXPECTED_SCHEMA = "architecture-contract/v1"
EXPECTED_CONTRACT_KEYS = {
    "schema",
    "product_vendor_import",
    "public_surface",
    "vendor_integration",
}
EXPECTED_VENDOR_INTEGRATION_KEYS = {
    "allowed_source_roots",
    "dispose_owner",
    "mount_owner",
    "packages",
    "update_owner",
}
RETIRED_MODULE_ROOTS = {"hwpxfiller.core"}
FORBIDDEN_KERNEL_ROOTS = {
    "ctypes",
    "datetime",
    "importlib",
    "msvcrt",
    "os",
    "pathlib",
    "pkgutil",
    "platform",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "sysconfig",
    "tempfile",
    "threading",
    "time",
    "urllib",
    "webview",
    "winreg",
}
FILESYSTEM_METHODS = {
    "exists",
    "glob",
    "is_dir",
    "is_file",
    "iterdir",
    "mkdir",
    "open",
    "read_bytes",
    "read_text",
    "rename",
    "replace",
    "resolve",
    "rglob",
    "rmdir",
    "stat",
    "symlink_to",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
VENDOR_ROOTS = {"ctypes", "lxml", "openpyxl", "webview", "xml", "zipfile"}
TS_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

# ``ContractError`` 와 frontend import-graph 스캐너(`_js_masks`·`_frontend_specifiers`·
# `_resolve_frontend_module`·`_frontend_sources`)는 SG-03(#735)에서 ``tests/_web_source.py``
# 로 올라갔다 — 이 게이트와 ``test_control_surface_reduction`` 이 같은 진실을 읽는다.


def _rings() -> "list[dict[str, object]]":
    document = tomllib.loads(RINGS.read_text(encoding="utf-8-sig"))
    return document["unit"]  # type: ignore[return-value]


def _architecture_contract() -> dict[str, object]:
    document = tomllib.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    if document.get("schema") != EXPECTED_SCHEMA or set(document) != EXPECTED_CONTRACT_KEYS:
        raise ContractError(f"architecture contract schema는 {EXPECTED_SCHEMA!r} 이어야 합니다")
    return document


def _public_surface() -> dict[str, set[str]]:
    raw = _architecture_contract()["public_surface"]
    if not isinstance(raw, dict) or list(raw) != ["hwpxcore", "hwpxfiller"]:
        raise ContractError("public_surface는 hwpxcore·hwpxfiller 두 root만 가져야 합니다")
    out: dict[str, set[str]] = {}
    for module, names in raw.items():
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ContractError(f"public_surface.{module}은 문자열 배열이어야 합니다")
        if names != sorted(names) or len(names) != len(set(names)):
            raise ContractError(f"public_surface.{module}은 중복 없는 정렬 목록이어야 합니다")
        if any(not name or name.startswith("_") for name in names):
            raise ContractError(f"public_surface.{module}에 private 이름이 있습니다")
        out[str(module)] = set(names)
    return out


def _validate_product_vendor_import(raw: object) -> set[str]:
    if not isinstance(raw, dict) or list(raw) != sorted(raw):
        raise ContractError("product_vendor_import는 module 순의 table이어야 합니다")
    facts: set[str] = set()
    product_modules = _product_modules()
    for module, names in raw.items():
        if module not in product_modules:
            raise ContractError(f"product_vendor_import: Product Domain 밖 모듈 {module!r}")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ContractError(f"product_vendor_import.{module}은 문자열 배열이어야 합니다")
        if names != sorted(names) or len(names) != len(set(names)):
            raise ContractError(
                f"product_vendor_import.{module}은 중복 없는 정렬 목록이어야 합니다"
            )
        for name in names:
            if any(token in name for token in ("*", "?", "[", "]", "|")):
                raise ContractError(f"product_vendor_import wildcard 금지: {name!r}")
            facts.add(f"{module}|{name}")
    return facts


def _product_vendor_policy() -> set[str]:
    return _validate_product_vendor_import(_architecture_contract()["product_vendor_import"])


def _js_code_mask(source: str) -> str:
    return _js_masks(source)[1]


def _has_ts_declaration(source: str, symbol: str) -> bool:
    if TS_IDENTIFIER.fullmatch(symbol) is None:
        raise ContractError(f"lifecycle owner symbol은 TS identifier여야 합니다: {symbol!r}")
    name = re.escape(symbol)
    declaration = (
        rf"(?m)^\s*(?:(?:(?:export|default|declare|async)\s+)*"
        rf"(?:function|class|const|let|var)\s+{name}(?![A-Za-z0-9_$])|"
        rf"(?:async\s+)?{name}\s*\([^;\n]*\)\s*(?::[^{{;\n]+)?\s*{{)"
    )
    return re.search(declaration, _js_code_mask(source)) is not None


def _in_source_roots(relative: str, roots: tuple[str, ...] | list[str]) -> bool:
    return any(relative == root or relative.startswith(f"{root}/") for root in roots)


def _vendor_integrations() -> dict[str, tuple[set[str], tuple[str, ...]]]:
    raw = _architecture_contract()["vendor_integration"]
    if not isinstance(raw, dict) or not raw or list(raw) != sorted(raw):
        raise ContractError("vendor_integration은 이름순의 비어 있지 않은 table이어야 합니다")

    package_document = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    dependencies = set(package_document.get("dependencies", {}))
    registered: list[str] = []
    out: dict[str, tuple[set[str], tuple[str, ...]]] = {}
    for name, record in raw.items():
        if not isinstance(record, dict) or set(record) != EXPECTED_VENDOR_INTEGRATION_KEYS:
            raise ContractError(f"vendor_integration.{name} 키가 고정 기대와 다릅니다")
        packages = record["packages"]
        roots = record["allowed_source_roots"]
        for key, values in (("packages", packages), ("allowed_source_roots", roots)):
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ContractError(f"vendor_integration.{name}.{key}는 문자열 배열이어야 합니다")
            if values != sorted(values) or len(values) != len(set(values)):
                raise ContractError(
                    f"vendor_integration.{name}.{key}는 중복 없는 정렬 목록이어야 합니다"
                )
            if any(any(token in value for token in ("*", "?", "[", "]")) for value in values):
                raise ContractError(
                    f"vendor_integration.{name}.{key}에는 wildcard를 쓸 수 없습니다"
                )
        for root in roots:
            if (
                not root.startswith("frontend/src/")
                or "\\" in root
                or ".." in Path(root).parts
                or not (ROOT / root).exists()
            ):
                raise ContractError(
                    f"vendor_integration.{name} 배치 경로가 유효하지 않습니다: {root!r}"
                )
        for lifecycle in ("mount_owner", "update_owner", "dispose_owner"):
            owner = record[lifecycle]
            if not isinstance(owner, str) or owner.count("|") != 1:
                raise ContractError(
                    f"vendor_integration.{name}.{lifecycle}는 source|symbol 형식이어야 합니다"
                )
            source, symbol = owner.split("|", 1)
            path = ROOT / source
            if (
                not source.startswith("frontend/src/")
                or "\\" in source
                or ".." in Path(source).parts
                or not path.is_file()
                or not _in_source_roots(source, roots)
                or not _has_ts_declaration(path.read_text(encoding="utf-8"), symbol)
            ):
                raise ContractError(
                    f"vendor_integration.{name}.{lifecycle} owner가 유효하지 않습니다: {owner!r}"
                )
        registered.extend(packages)
        out[str(name)] = (set(packages), tuple(roots))

    if len(registered) != len(set(registered)) or set(registered) != dependencies:
        raise ContractError(
            "package.json runtime dependency와 vendor_integration package가 정확히 일치해야 합니다"
        )
    return out


def _frontend_vendor_import_violations(sources: dict[str, str]) -> set[str]:
    allowed: dict[str, tuple[str, ...]] = {}
    vendor_roots: list[str] = []
    for packages, roots in _vendor_integrations().values():
        allowed.update({package: roots for package in packages})
        vendor_roots.extend(roots)

    violations: set[str] = set()
    relative_edges: dict[str, list[tuple[str, str]]] = {}
    for relative, source in sources.items():
        edges: list[tuple[str, str]] = []
        for specifier in _frontend_specifiers(relative, source):
            if specifier.startswith(".") or specifier.startswith(("/src/", "/js/")):
                if target := _resolve_frontend_module(relative, specifier, sources):
                    edges.append((specifier, target))
                continue
            package = specifier.split("/", 1)[0]
            if specifier.startswith("@"):
                package = "/".join(specifier.split("/", 2)[:2])
            roots = allowed.get(package)
            if roots is None or not _in_source_roots(relative, roots):
                violations.add(f"{relative}|{specifier}")
        relative_edges[relative] = edges

    provenance = {
        relative for relative in sources if _in_source_roots(relative, vendor_roots)
    }
    while additions := {
        relative
        for relative, edges in relative_edges.items()
        if any(target in provenance for _, target in edges)
    } - provenance:
        provenance.update(additions)
    for relative, edges in relative_edges.items():
        if relative.startswith("frontend/src/contract/"):
            violations.update(
                f"{relative}|{specifier}"
                for specifier, target in edges
                if target in provenance
            )
    return violations


def _tree(source: "str | bytes", filename: str = "<memory>") -> ast.Module:
    return ast.parse(source, filename=filename)


def _module_for_path(path: Path) -> str:
    try:
        relative = path.relative_to(ROOT / "src").with_suffix("")
    except ValueError:
        return ""
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(package: str, level: int, module: "str | None") -> str:
    if not level:
        return module or ""
    parts = package.split(".") if package else []
    base = parts[: max(len(parts) - (level - 1), 0)]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _qualified_name(node: ast.AST, aliases: "dict[str, str] | None" = None) -> str:
    aliases = aliases or {}
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _aliases(
    tree: ast.AST, source_module: str = "", *, source_is_package: bool = False
) -> dict[str, str]:
    package = source_module if source_is_package else source_module.rpartition(".")[0]
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(package, node.level, node.module)
            for alias in node.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = (
                        f"{base}.{alias.name}" if base else alias.name
                    )
    return aliases


def _match_module(value: str, known: set[str]) -> "str | None":
    matches = [m for m in known if value == m or value.startswith(f"{m}.")]
    return max(matches, key=len) if matches else None


def _import_targets(
    tree: ast.AST,
    *,
    source_module: str,
    source_is_package: bool,
    known: set[str],
) -> set[str]:
    package = source_module if source_is_package else source_module.rpartition(".")[0]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if match := _match_module(alias.name, known):
                    targets.add(match)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        base = _resolve_from(package, node.level, node.module)
        for alias in node.names:
            if alias.name == "*":
                if match := _match_module(base, known):
                    targets.add(f"{match}.*")
                continue
            candidate = f"{base}.{alias.name}" if base else alias.name
            if candidate in known:
                targets.add(candidate)
            elif match := _match_module(base, known):
                targets.add(match)
    return targets


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left)
        right = _literal_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _dynamic_import_names(tree: ast.AST) -> set[str]:
    aliases = _aliases(tree)
    parents = _parents(tree)
    bindings: dict[tuple[ast.AST, str], set[str | None]] = {}
    scope_types = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def lexical_scope(node: ast.AST) -> ast.AST:
        while not isinstance(node, scope_types):
            node = parents[node]
        return node

    def scope_chain(node: ast.AST) -> list[ast.AST]:
        scopes = [lexical_scope(node)]
        while not isinstance(scopes[-1], ast.Module):
            parent = parents[scopes[-1]]
            while not isinstance(
                parent, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                parent = parents[parent]
            scopes.append(parent)
        return scopes

    def bind(node: ast.AST, target: ast.AST, value: "str | None") -> None:
        for name in _bound_names(target):
            bindings.setdefault((lexical_scope(node), name), set()).add(value)

    defaults: dict[ast.arg, str] = {}
    for owner in ast.walk(tree):
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        positional = (*owner.args.posonlyargs, *owner.args.args)
        positional_with_defaults = (
            positional[-len(owner.args.defaults) :] if owner.args.defaults else ()
        )
        pairs = zip(positional_with_defaults, owner.args.defaults, strict=True)
        keyword_pairs = zip(owner.args.kwonlyargs, owner.args.kw_defaults, strict=True)
        for argument, default in (*pairs, *keyword_pairs):
            if (value := _literal_string(default)) is not None:
                defaults[argument] = value

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = _literal_string(node.value)
            for target in targets:
                bind(node, target, value)
        elif isinstance(node, (ast.AugAssign, ast.NamedExpr)):
            bind(node, node.target, None)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind(node, node.target, None)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bind(node, item.optional_vars, None)
        elif isinstance(node, ast.arg):
            values = bindings.setdefault((lexical_scope(node), node.arg), set())
            values.add(None)
            if node in defaults:
                values.add(defaults[node])

    def constants(node: ast.AST) -> set[str]:
        if (value := _literal_string(node)) is not None:
            return {value}
        if not isinstance(node, ast.Name):
            return set()
        for candidate in scope_chain(node):
            key = (candidate, node.id)
            if key in bindings:
                return {value for value in bindings[key] if isinstance(value, str)}
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and node.args
            and _qualified_name(node.func, aliases).rsplit(".", 1)[-1]
            in {"__import__", "find_spec", "import_module"}
        ):
            names.update(constants(node.args[0]))
    return names


def _dynamic_targets(tree: ast.AST, known: set[str]) -> set[str]:
    targets = {
        match
        for value in _dynamic_import_names(tree)
        if (match := _match_module(value, known))
    }
    aliases = _aliases(tree)
    bindings: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets_to_bind = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets_to_bind:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(node.value)

    def add_literal(node: ast.AST) -> None:
        if (value := _literal_string(node)) is not None:
            if match := _match_module(value, known):
                targets.add(match)

    def add_literals(node: ast.AST, resolving: frozenset[str] = frozenset()) -> None:
        add_literal(node)
        if isinstance(node, ast.Name) and node.id not in resolving:
            for value in bindings.get(node.id, ()):
                add_literals(value, resolving | {node.id})
            return
        for child in ast.iter_child_nodes(node):
            add_literals(child, resolving)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            qualified = _qualified_name(node.func, aliases)
            call = qualified.rsplit(".", 1)[-1]
            if node.args and (
                call == "patch"
                or qualified.endswith("monkeypatch.setattr")
                or qualified.endswith("monkeypatch.delattr")
            ):
                add_literal(node.args[0])
            if call == "Analysis":
                for keyword in node.keywords:
                    if keyword.arg == "hiddenimports":
                        add_literals(keyword.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets_to_check = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {target.id for target in targets_to_check if isinstance(target, ast.Name)}
            if node.value is not None and "REQUIRED_HIDDEN" in names:
                add_literals(node.value)
    return targets


def _consumer_targets(
    source: "str | bytes",
    *,
    source_module: str,
    known: set[str],
    filename: str,
    source_is_package: bool = False,
) -> set[str]:
    tree = _tree(source, filename)
    aliases = _aliases(tree, source_module, source_is_package=source_is_package)
    return _import_targets(
        tree,
        source_module=source_module,
        source_is_package=source_is_package,
        known=known,
    ) | _dynamic_targets(tree, known) | _annotation_targets(tree, aliases, known)


def _source_paths() -> list[Path]:
    paths = {ROOT / "conftest.py"}
    for root in ("src", "tests", "scripts", "examples", "packaging"):
        base = ROOT / root
        if base.is_dir():
            paths.update(base.rglob("*.py"))
    paths.update((ROOT / "packaging").rglob("*.spec"))
    return sorted(path for path in paths if "__pycache__" not in path.parts)


def _entry_point_targets(document: dict[str, object], known: set[str]) -> set[str]:
    metadata = document.get("project")
    if not isinstance(metadata, dict):
        return set()
    tables = [metadata.get(name) for name in ("scripts", "gui-scripts")]
    nested = metadata.get("entry-points")
    if isinstance(nested, dict):
        tables.extend(nested.values())
    return {
        target
        for table in tables
        if isinstance(table, dict)
        for value in table.values()
        if isinstance(value, str)
        if (target := _match_module(value.split(":", 1)[0], known))
    }


def _consumer_edges(known: set[str]) -> set[str]:
    edges: set[str] = set()
    for path in _source_paths():
        relative = path.relative_to(ROOT).as_posix()
        for target in _consumer_targets(
            path.read_bytes(),
            source_module=_module_for_path(path),
            known=known,
            filename=relative,
            source_is_package=path.name == "__init__.py",
        ):
            edges.add(f"{relative}|{target}")

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8-sig"))
    edges.update(f"pyproject.toml|{target}" for target in _entry_point_targets(project, known))
    return edges


RETIRED_DOCUMENT_REFERENCE = re.compile(
    r"\bhwpxfiller(?:\.|[\\/])core\b|\bhwpxfiller\s+import\s+core\b"
)


def _active_document_paths() -> list[Path]:
    paths = {ROOT / "README.md", ROOT / "CLAUDE.md"}
    for root in ("docs", "packaging", "examples"):
        paths.update(
            path
            for path in (ROOT / root).rglob("*")
            if path.suffix.lower() in {".md", ".html"} and "archive" not in path.parts
        )
    return sorted(path for path in paths if path.is_file())


def _bound_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        return {name for item in target.elts for name in _bound_names(item)}
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def _same_scope_body(node: ast.stmt) -> list[ast.stmt]:
    if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [*node.body, *node.orelse]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return node.body
    if isinstance(node, (ast.Try, ast.TryStar)):
        return [
            *node.body,
            *node.orelse,
            *node.finalbody,
            *(item for handler in node.handlers for item in handler.body),
        ]
    if isinstance(node, ast.Match):
        return [item for case in node.cases for item in case.body]
    return []


def _public_definitions(source: "str | bytes", module: str) -> set[str]:
    definitions: set[str] = set()
    is_package = _is_package_module(module)

    def visit(body: list[ast.stmt], owner: str) -> None:
        for node in body:
            names: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Import) and not is_package:
                names = [alias.asname or alias.name.split(".", 1)[0] for alias in node.names]
                names = [name for name in names if not name.startswith("_")]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module != "__future__"
                and not is_package
            ):
                if any(alias.name == "*" for alias in node.names):
                    raise ContractError(f"{module}: legacy leaf star import는 허용하지 않습니다")
                names = [alias.asname or alias.name for alias in node.names if alias.name != "*"]
                names = [name for name in names if not name.startswith("_")]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [name for target in targets for name in _bound_names(target)]
            elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
                names = [node.name.id]
            definitions.update(f"{module}|{owner}{name}" for name in names)
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{owner}{node.name}.")
            else:
                visit(_same_scope_body(node), owner)

    visit(_tree(source, module).body, "")
    return definitions


def _facade_exports(source: "str | bytes", module: str) -> tuple[set[str], set[str]]:
    tree = _tree(source, module)
    parents = _parents(tree)
    assignments: list[ast.Assign | ast.AnnAssign] = []

    def mentions_all(node: ast.AST) -> bool:
        return any(isinstance(item, ast.Name) and item.id == "__all__" for item in ast.walk(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(mentions_all(target) for target in targets):
                assignments.append(node)
        elif isinstance(node, (ast.AugAssign, ast.NamedExpr, ast.Delete)):
            targets = node.targets if isinstance(node, ast.Delete) else [node.target]
            if any(mentions_all(target) for target in targets):
                raise ContractError(f"{module}: __all__ mutation은 허용하지 않습니다")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and mentions_all(node.func.value)
        ):
            raise ContractError(f"{module}: __all__ mutation은 허용하지 않습니다")
    if len(assignments) != 1 or parents.get(assignments[0]) is not tree:
        raise ContractError(f"{module}: top-level explicit __all__ 은 정확히 하나여야 합니다")
    if sum(
        isinstance(node, ast.Name) and node.id == "__all__"
        for node in ast.walk(tree)
    ) != 1:
        raise ContractError(f"{module}: __all__ mutation은 허용하지 않습니다")

    imported: set[str] = set()
    declared: set[str] = set()
    has_all = False

    def visit(body: list[ast.stmt]) -> None:
        nonlocal has_all
        for node in body:
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                names.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if "__all__" in {
                    name for target in targets for name in _bound_names(target)
                }:
                    if node.value is None:
                        raise ContractError(f"{module}: __all__ 값이 없습니다")
                    declared.update(ast.literal_eval(node.value))
                    has_all = True
                else:
                    names.update(name for target in targets for name in _bound_names(target))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.TypeAlias):
                names.update(_bound_names(node.name))
            imported.update(name for name in names if not name.startswith("_"))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(_same_scope_body(node))

    visit(tree.body)
    if not has_all:
        raise ContractError(f"{module}: explicit __all__ 이 없습니다")
    prefix = f"{module}|"
    return ({prefix + name for name in imported}, {prefix + name for name in declared})


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names: list[str] = []
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return ".".join(reversed(names)) or "<module>"


def _kernel_effect_edges(source: "str | bytes", module: str) -> set[str]:
    tree = _tree(source, module)
    aliases = _aliases(tree, module)
    parents = _parents(tree)
    edges: set[str] = set()

    def is_bytes_io(node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and _qualified_name(
            node.func, aliases
        ) == "io.BytesIO"

    binding_proofs: dict[tuple[str, str], set[bool]] = {}

    def note(scope: str, target: ast.AST, proved_memory: bool) -> None:
        for name in _bound_names(target):
            binding_proofs.setdefault((scope, name), set()).add(proved_memory)

    for binding in ast.walk(tree):
        scope = _scope(binding, parents)
        if isinstance(binding, (ast.Assign, ast.AnnAssign)):
            targets = binding.targets if isinstance(binding, ast.Assign) else [binding.target]
            proved = binding.value is not None and is_bytes_io(binding.value)
            for target in targets:
                note(scope, target, proved)
        elif isinstance(binding, (ast.AugAssign, ast.NamedExpr)):
            note(scope, binding.target, False)
        elif isinstance(binding, (ast.For, ast.AsyncFor)):
            note(scope, binding.target, False)
        elif isinstance(binding, (ast.With, ast.AsyncWith)):
            for item in binding.items:
                if item.optional_vars is not None:
                    note(scope, item.optional_vars, False)
        elif isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_scope = binding.name if scope == "<module>" else f"{scope}.{binding.name}"
            arguments = [*binding.args.posonlyargs, *binding.args.args, *binding.args.kwonlyargs]
            if binding.args.vararg:
                arguments.append(binding.args.vararg)
            if binding.args.kwarg:
                arguments.append(binding.args.kwarg)
            for argument in arguments:
                binding_proofs.setdefault((function_scope, argument.arg), set()).add(False)

    def memoryish(node: ast.AST) -> bool:
        return is_bytes_io(node) or (
            isinstance(node, ast.Name)
            and binding_proofs.get((_scope(node, parents), node.id)) == {True}
        )

    def pathish(node: ast.AST) -> bool:
        return any(
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            or isinstance(item, ast.Name)
            and (
                any(word in item.id.lower() for word in ("file", "path"))
                or _qualified_name(item, aliases) == "pathlib.Path"
            )
            for item in ast.walk(node)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            package = module.rpartition(".")[0]
            base = _resolve_from(package, node.level, node.module)
            values = [f"{base}.{alias.name}" if base else alias.name for alias in node.names]
        else:
            values = []
        for value in values:
            if value.split(".", 1)[0] in FORBIDDEN_KERNEL_ROOTS or value.endswith(
                ".write_bytes_atomic"
            ):
                edges.add(f"{module}|<module>|import:{value}")

        if isinstance(node, ast.Call):
            qualified = _qualified_name(node.func, aliases)
            root = qualified.split(".", 1)[0]
            effect = ""
            if qualified.endswith(".write_bytes_atomic"):
                effect = f"durable-filesystem:{qualified}"
            elif qualified == "open" or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in FILESYSTEM_METHODS
                and (
                    node.func.attr not in {"open", "replace"}
                    or pathish(node.func.value)
                )
            ):
                effect = f"filesystem:{qualified}"
            elif root in FORBIDDEN_KERNEL_ROOTS:
                effect = root
            elif qualified == "zipfile.ZipFile":
                source = node.args[0] if node.args else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "file"),
                    None,
                )
                if source is not None and not memoryish(source):
                    effect = "filesystem:zipfile.ZipFile"
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                if any(pathish(value) for value in (node.func.value, *node.args)):
                    effect = f"filesystem:{qualified}"
            if effect:
                edges.add(f"{module}|{_scope(node, parents)}|{effect}")
        elif isinstance(node, (ast.Name, ast.Attribute)) and not isinstance(
            parents.get(node), ast.Attribute
        ) and not (
            isinstance(parents.get(node), ast.Call) and parents[node].func is node
        ):
            qualified = _qualified_name(node, aliases)
            root = qualified.split(".", 1)[0]
            if root in FORBIDDEN_KERNEL_ROOTS:
                edges.add(f"{module}|{_scope(node, parents)}|{root}")
    return edges


def _is_package_module(module: str) -> bool:
    for unit in _rings():
        if unit["module"] == module:
            return str(unit["source_write_set"][0]).endswith("/__init__.py")
    return (ROOT / "src" / Path(*module.split(".")) / "__init__.py").is_file()


def _all_import_names(tree: ast.AST, source_module: str) -> set[str]:
    package = source_module if _is_package_module(source_module) else source_module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(package, node.level, node.module)
            names.update(
                f"{base}.{alias.name}" if base else alias.name for alias in node.names
            )
    return names


def _kernel_product_import_edges(source: "str | bytes", module: str) -> set[str]:
    tree = _tree(source, module)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.name
                for alias in node.names
                if alias.name == "hwpxfiller" or alias.name.startswith("hwpxfiller.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "hwpxfiller" or node.module.startswith("hwpxfiller."):
                names.add(node.module)
    names.update(
        name
        for name in _dynamic_import_names(tree)
        if name == "hwpxfiller" or name.startswith("hwpxfiller.")
    )
    return {f"{module}|{name}" for name in names}


def _is_vendor_name(name: str) -> bool:
    root = name.split(".", 1)[0]
    if root in VENDOR_ROOTS or root.startswith("win32"):
        return True
    if "." not in name:
        return False
    return (
        root[:1].islower()
        and root not in sys.stdlib_module_names | {"hwpxcore", "hwpxfiller"}
        or name == "hwpxcore.package"
        or name.startswith("hwpxcore.package.HwpxPackage")
    )


def _is_vendor_import(name: str) -> bool:
    root = name.split(".", 1)[0]
    return _is_vendor_name(name) or root not in sys.stdlib_module_names | {
        "hwpxcore",
        "hwpxfiller",
    }


def _product_modules() -> set[str]:
    modules = {
        str(unit["module"])
        for unit in _rings()
        if str(unit["module"]).startswith("hwpxfiller")
        and str(unit["target"]) in {"DOMAIN", "APPLICATION"}
    }
    for directory in (ROOT / "src" / "hwpxfiller" / name for name in ("domain", "application")):
        for path in directory.rglob("*.py"):
            modules.add(_module_for_path(path))
    return modules


def _kernel_modules() -> set[str]:
    return {
        _module_for_path(path)
        for path in (ROOT / "src" / "hwpxcore").rglob("*.py")
    }


def _private_import_edges(
    source: "str | bytes", *, relative: str, module: str, source_is_package: bool
) -> set[str]:
    edges: set[str] = set()
    package = module if source_is_package else module.rpartition(".")[0]
    tree = _tree(source, relative)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update(
                f"{relative}|{alias.name}"
                for alias in node.names
                if any(part.startswith("_") for part in alias.name.split("."))
            )
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(package, node.level, node.module)
            if base != "__future__" and any(
                part.startswith("_") for part in base.split(".")
            ):
                edges.add(f"{relative}|{base}")
            edges.update(
                f"{relative}|{base}.{alias.name}"
                for alias in node.names
                if alias.name.startswith("_")
            )
    edges.update(
        f"{relative}|{name}"
        for name in _dynamic_import_names(tree)
        if name != "__future__" and any(part.startswith("_") for part in name.split("."))
    )
    return edges


def _production_private_imports() -> set[str]:
    edges: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        module = _module_for_path(path)
        edges.update(
            _private_import_edges(
                path.read_bytes(),
                relative=relative,
                module=module,
                source_is_package=path.name == "__init__.py",
            )
        )
    return edges


def _source_for_module(module: str) -> bytes:
    for unit in _rings():
        if unit["module"] == module:
            paths = unit["source_write_set"]
            if len(paths) != 1:
                raise AssertionError(f"{module}: source_write_set은 현재 한 파일이어야 합니다")
            return (ROOT / str(paths[0])).read_bytes()
    relative = Path("src", *module.split(".")).with_suffix(".py")
    package = ROOT / "src" / Path(*module.split(".")) / "__init__.py"
    path = package if package.is_file() else ROOT / relative
    return path.read_bytes()


def _vendor_import_edges(source: "str | bytes", module: str) -> set[str]:
    tree = _tree(source, module)
    return {
        f"{module}|{name}"
        for name in _all_import_names(tree, module) | _dynamic_import_names(tree)
        if _is_vendor_import(name)
    }


def _annotation_names(node: ast.AST, aliases: dict[str, str]) -> set[str]:
    names: set[str] = set()
    pending = [node]
    parsed_strings: set[str] = set()
    while pending:
        expression = pending.pop()
        parents = _parents(expression)
        for item in ast.walk(expression):
            if isinstance(item, (ast.Name, ast.Attribute)) and not isinstance(
                parents.get(item), ast.Attribute
            ):
                names.add(_qualified_name(item, aliases))
            elif (
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and item.value not in parsed_strings
            ):
                parsed_strings.add(item.value)
                try:
                    pending.append(ast.parse(item.value, mode="eval").body)
                except SyntaxError:
                    pass
    return names


def _annotation_targets(
    tree: ast.AST, aliases: dict[str, str], known: set[str]
) -> set[str]:
    annotations: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, ast.TypeAlias):
            annotations.append(node.value)
        elif isinstance(node, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)):
            annotations.extend(
                value
                for field in ("bound", "default_value")
                if (value := getattr(node, field, None)) is not None
            )
    return {
        match
        for annotation in annotations
        for name in _annotation_names(annotation, aliases)
        if (match := _match_module(name, known))
    }


def _function_annotations(
    node: "ast.FunctionDef | ast.AsyncFunctionDef", aliases: dict[str, str]
) -> set[str]:
    annotations = [arg.annotation for arg in (*node.args.posonlyargs, *node.args.args)]
    annotations.extend(arg.annotation for arg in node.args.kwonlyargs)
    if node.args.vararg:
        annotations.append(node.args.vararg.annotation)
    if node.args.kwarg:
        annotations.append(node.args.kwarg.annotation)
    annotations.append(node.returns)
    return {
        name
        for annotation in annotations
        if annotation is not None
        for name in _annotation_names(annotation, aliases)
    }


def _vendor_public_type_edges(source: "str | bytes", module: str) -> set[str]:
    tree = _tree(source, module)
    aliases = _aliases(tree, module, source_is_package=_is_package_module(module))
    edges: set[str] = set()

    def record(owner: str, annotation: ast.AST) -> None:
        for name in _annotation_names(annotation, aliases):
            if _is_vendor_name(name):
                edges.add(f"{module}|{owner}|{name}")

    def public(name: str) -> bool:
        return not name.startswith("_") or name.startswith("__") and name.endswith("__")

    def record_type_params(owner: str, node: ast.AST) -> None:
        for parameter in getattr(node, "type_params", ()):
            for field in ("bound", "default_value"):
                if (value := getattr(parameter, field, None)) is not None:
                    record(owner, value)

    def visit(body: list[ast.stmt], owner: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
                record_type_params(f"{owner}{node.name}", node)
                for name in _function_annotations(node, aliases):
                    if _is_vendor_name(name):
                        edges.add(f"{module}|{owner}{node.name}|{name}")
                if node.name == "__init__" and owner:
                    positional = (*node.args.posonlyargs, *node.args.args)
                    receiver = positional[0].arg if positional else None

                    def visit_initializer(
                        statements: list[ast.stmt], receiver_name: "str | None"
                    ) -> None:
                        for statement in statements:
                            if (
                                isinstance(statement, ast.AnnAssign)
                                and isinstance(statement.target, ast.Attribute)
                                and isinstance(statement.target.value, ast.Name)
                                and statement.target.value.id == receiver_name
                                and public(statement.target.attr)
                            ):
                                record(f"{owner}{statement.target.attr}", statement.annotation)
                            visit_initializer(_same_scope_body(statement), receiver_name)

                    visit_initializer(node.body, receiver)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if public(node.target.id):
                    binding = f"{owner}{node.target.id}"
                    record(binding, node.annotation)
                    if node.value is not None and any(
                        name.endswith(".TypeAlias")
                        for name in _annotation_names(node.annotation, aliases)
                    ):
                        record(binding, node.value)
            elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
                if public(node.name.id):
                    record_type_params(f"{owner}{node.name.id}", node)
                    record(f"{owner}{node.name.id}", node.value)
            elif isinstance(node, ast.ClassDef) and public(node.name):
                record_type_params(f"{owner}{node.name}", node)
                for base in node.bases:
                    record(f"{owner}{node.name}", base)
                visit(node.body, f"{owner}{node.name}.")
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(_same_scope_body(node), owner)

    visit(tree.body)
    return edges


def test_retired_namespace_has_no_consumer() -> None:
    self_edge = f"{Path(__file__).relative_to(ROOT).as_posix()}|"
    actual = {
        edge
        for edge in _consumer_edges(RETIRED_MODULE_ROOTS)
        if not edge.startswith(self_edge)  # 이 owner의 의도적 import-failure probe
    }
    assert not actual, f"retired namespace consumer: {sorted(actual)}"
    stale_docs = [
        path.relative_to(ROOT).as_posix()
        for path in _active_document_paths()
        if RETIRED_DOCUMENT_REFERENCE.search(path.read_text(encoding="utf-8"))
    ]
    assert not stale_docs, f"retired namespace docs: {stale_docs}"


def test_public_surface_is_exact_and_private_imports_are_zero() -> None:
    legacy_root = ROOT / "src" / "hwpxfiller" / "core"
    assert not legacy_root.exists(), "retired src/hwpxfiller/core 디렉터리가 다시 생겼습니다"
    assert importlib.util.find_spec("hwpxfiller.core") is None
    with pytest.raises(ModuleNotFoundError) as stopped:
        importlib.import_module("hwpxfiller.core")
    assert stopped.value.name == "hwpxfiller.core"
    for module, names in _public_surface().items():
        imported, declared = _facade_exports(_source_for_module(module), module)
        expected = {f"{module}|{name}" for name in names}
        assert imported == declared == expected
        runtime = getattr(importlib.import_module(module), "__all__", None)
        assert isinstance(runtime, list) and len(runtime) == len(names) and set(runtime) == names
    assert not _production_private_imports()


def test_hwpxcore_has_no_product_import_or_environment_effect() -> None:
    product_imports: set[str] = set()
    effects: set[str] = set()
    for module in sorted(_kernel_modules()):
        source = _source_for_module(module)
        product_imports |= _kernel_product_import_edges(source, module)
        effects |= _kernel_effect_edges(source, module)
    assert not product_imports, f"kernel product import: {sorted(product_imports)}"
    assert not effects, f"kernel environment effect: {sorted(effects)}"


def test_product_contract_has_no_new_vendor_import_or_public_type() -> None:
    imports: set[str] = set()
    public_types: set[str] = set()
    for module in sorted(_product_modules()):
        source = _source_for_module(module)
        imports |= _vendor_import_edges(source, module)
        public_types |= _vendor_public_type_edges(source, module)
    assert imports == _product_vendor_policy()
    assert not public_types, f"Product public vendor type: {sorted(public_types)}"
    assert not _frontend_vendor_import_violations(_frontend_sources())


def test_negative_probe_rejects_hwpxcore_product_import() -> None:
    source = """from importlib import import_module as load
from hwpxfiller.domain.job import Job
MODULE = 'hwpxfiller.core.job'
load(MODULE)
"""
    assert _kernel_product_import_edges(source, "hwpxcore.package") == {
        "hwpxcore.package|hwpxfiller.core.job",
        "hwpxcore.package|hwpxfiller.domain.job",
    }
    source = """from importlib import import_module
MODULE = 'hwpxfiller.core.job'
CLASS_MODULE = 'hwpxfiller.core.mapping'
if False:
    MODULE = 'json'
def outer():
    def inner():
        return import_module(MODULE)
class Probe:
    CLASS_MODULE = 'json'
    def load(self):
        return import_module(CLASS_MODULE)
def load_default(module='hwpxfiller.core.schema'):
    return import_module(module)
load_lambda = lambda module='hwpxfiller.core.template_status': import_module(module)
"""
    assert _kernel_product_import_edges(source, "hwpxcore.package") == {
        "hwpxcore.package|hwpxfiller.core.job",
        "hwpxcore.package|hwpxfiller.core.mapping",
        "hwpxcore.package|hwpxfiller.core.schema",
        "hwpxcore.package|hwpxfiller.core.template_status",
    }


def test_negative_probe_finds_direct_dynamic_and_build_legacy_consumers() -> None:
    known = RETIRED_MODULE_ROOTS
    cases = (
        "from hwpxfiller.core.job import Job\n",
        "import importlib\nimportlib.import_module('hwpxfiller.core.job')\n",
        "from importlib import import_module as load\nload('hwpxfiller.core.job')\n",
        "from importlib import import_module\nMODULE = 'hwpxfiller.core.job'\nimport_module(MODULE)\n",
        "from importlib import import_module\nimport_module('hwpxfiller.' + 'core')\n",
        "from importlib import import_module\nMODULE = 'hwpxfiller.' + 'core'\nimport_module(MODULE)\n",
        "from importlib import import_module\ndef load(MODULE='hwpxfiller.' + 'core'):\n return import_module(MODULE)\n",
        "Analysis([], hiddenimports=['hwpxfiller.core.job'])\n",
        "Analysis([], hiddenimports=['hwpxfiller.' + 'core'])\n",
        "HIDDEN = ['hwpxfiller.core.job']\nAnalysis([], hiddenimports=HIDDEN)\n",
        "REQUIRED_HIDDEN = ['hwpxfiller.' + 'core']\n",
        "import hwpxfiller\ndef f(x: 'hwpxfiller.core.job.Job') -> None: ...\n",
        "def f[T: 'hwpxfiller.core.job.Job'](x: T) -> None: ...\n",
        "type A[**P = 'hwpxfiller.core.job.Job'] = tuple[P.args]\n",
        "type A[*Ts = *tuple['hwpxfiller.core.job.Job']] = tuple[*Ts]\n",
    )
    for source in cases:
        assert _consumer_targets(
            source,
            source_module="hwpxfiller.application.probe",
            known=known,
            filename="<probe>",
        ) == {"hwpxfiller.core"}
    assert _entry_point_targets(
        {
            "project": {
                "entry-points": {
                    "probe": {"legacy": "hwpxfiller.core.job:Job"}
                }
            }
        },
        known,
    ) == {"hwpxfiller.core"}
    assert RETIRED_DOCUMENT_REFERENCE.search(
        "```python\nfrom hwpxfiller import core\n```\n"
    )
    assert RETIRED_DOCUMENT_REFERENCE.search("`hwpxfiller/core/job.py`\n")


def test_negative_probe_rejects_wildcard_vendor_policy() -> None:
    with pytest.raises(ContractError, match="wildcard"):
        _validate_product_vendor_import({"hwpxfiller.domain.authoring": ["lxml.*"]})


def test_negative_probe_finds_kernel_path_save() -> None:
    source = """import io
import zipfile
from pathlib import Path
def to_bytes(path: str) -> bytes:
    Path(path).write_bytes(b'x')
    return b'x'
def open_zip(source):
    return zipfile.ZipFile(source)
def open_zip_keyword(path):
    return zipfile.ZipFile(file=path)
def memory():
    buf = io.BytesIO()
def parse(buf):
    return zipfile.ZipFile(buf)
"""
    assert _kernel_effect_edges(source, "hwpxcore.codec") == {
        "hwpxcore.codec|<module>|import:pathlib.Path",
        "hwpxcore.codec|open_zip|filesystem:zipfile.ZipFile",
        "hwpxcore.codec|open_zip_keyword|filesystem:zipfile.ZipFile",
        "hwpxcore.codec|parse|filesystem:zipfile.ZipFile",
        "hwpxcore.codec|to_bytes|filesystem:write_bytes",
        "hwpxcore.codec|to_bytes|pathlib",
    }


def test_negative_probe_finds_vendor_type_contract_exposure(tmp_path: Path) -> None:
    source = """import lxml
import zipfile
from importlib import import_module as load
from typing import TYPE_CHECKING, Protocol
if TYPE_CHECKING:
    from lxml.etree import _Element
load('lxml.etree')
type ElementList = list['_Element']
def generic[T: '_Element'](value: T) -> T: ...
class Generic[T: '_Element']: ...
class Contract(Protocol):
    def __init__(this):
        this.root: '_Element'
        def nested(self):
            self.not_contract: '_Element'
    def __call__(self, root: '_Element') -> str: ...
    def __iter__(self) -> "list['_Element']": ...
"""
    assert _vendor_import_edges(source, "hwpxfiller.application.contract") == {
        "hwpxfiller.application.contract|lxml",
        "hwpxfiller.application.contract|lxml.etree",
        "hwpxfiller.application.contract|lxml.etree._Element",
        "hwpxfiller.application.contract|zipfile",
    }
    assert _vendor_public_type_edges(source, "hwpxfiller.application.contract") == {
        "hwpxfiller.application.contract|Contract.__call__|lxml.etree._Element",
        "hwpxfiller.application.contract|Contract.__iter__|lxml.etree._Element",
        "hwpxfiller.application.contract|Contract.root|lxml.etree._Element",
        "hwpxfiller.application.contract|ElementList|lxml.etree._Element",
        "hwpxfiller.application.contract|Generic|lxml.etree._Element",
        "hwpxfiller.application.contract|generic|lxml.etree._Element",
    }
    for symbol in ("", "dispose()"):
        with pytest.raises(ContractError, match="TS identifier"):
            _has_ts_declaration("", symbol)
    assert not _has_ts_declaration(
        (
            '// function dispose() {}\nconst note = "function dispose() {}";\n'
            "const pattern = /function dispose/;\n"
        ),
        "dispose",
    )
    assert not _has_ts_declaration("boot();\n", "boot")
    assert "frontend/js/bridge.js" in _frontend_sources()
    source_root = tmp_path / "frontend"
    expected_sources = {
        "frontend/src/probe.cjs",
        "frontend/src/probe.cts",
        "frontend/src/probe.mts",
    }
    for relative in expected_sources:
        path = source_root / relative.removeprefix("frontend/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module.exports = {};\n", encoding="utf-8")
    assert set(_frontend_sources(source_root)) == expected_sources
    assert not _frontend_vendor_import_violations(
        {
            "frontend/src/screens/comment_probe.ts": (
                "// import(vendorName)\n"
                "const text = 'import(vendorName)';\n"
                "/* import(otherName) */\n"
                "const raw = `raw import(vendorName)`;\n"
                'const nested = `${"import(vendorName)"}`;\n'
                'const rawReference = `\n/// <reference types="vendor-types" />\n`;\n'
            )
        }
    )
    with pytest.raises(ContractError, match="문자열 literal"):
        _frontend_vendor_import_violations(
            {
                "frontend/src/screens/dynamic_probe.ts": (
                    "const sdk = `${import(vendorName)}`;\n"
                )
            }
        )
    with pytest.raises(ContractError, match="require\\(\\) specifier"):
        _frontend_vendor_import_violations(
            {"frontend/src/screens/require_probe.cjs": "require(vendorName);\n"}
        )
    assert _frontend_vendor_import_violations(
        {
            "frontend/js/vendor_probe.js": 'import "react"\n',
            "frontend/src/contract/absolute.ts": (
                'export type { VendorNode } from "/src/react/vendor-types"\n'
            ),
            "frontend/src/contract/direct.ts": (
                'import "react"\n'
                'import type { Root } from "react-dom/client"\n'
            ),
            "frontend/src/contract/common.cjs": 'require("react")\n',
            "frontend/src/contract/import_equals.ts": (
                'import type ReactTypes = require("react")\n'
            ),
            "frontend/src/contract/probe.ts": (
                'export type { VendorNode } from "../react/vendor.ts"\n'
            ),
            "frontend/src/contract/reference.d.ts": (
                '/// <reference types="react" />\n'
            ),
            "frontend/src/contract/module.mts": 'module.require("react-dom/client")\n',
            "frontend/src/react/vendor.ts": (
                'import type { ReactNode } from "react"\n'
                "export type VendorNode = ReactNode\n"
            ),
            "frontend/src/react/vendor-types.d.ts": (
                'import type { ReactNode } from "react"\n'
                "export type VendorNode = ReactNode\n"
            ),
            "frontend/src/screens/probe.ts": (
                'const sdk = `${import("vendor-sdk")}`;\n'
            ),
        }
    ) == {
        "frontend/js/vendor_probe.js|react",
        "frontend/src/contract/absolute.ts|/src/react/vendor-types",
        "frontend/src/contract/direct.ts|react",
        "frontend/src/contract/direct.ts|react-dom/client",
        "frontend/src/contract/common.cjs|react",
        "frontend/src/contract/import_equals.ts|react",
        "frontend/src/contract/probe.ts|../react/vendor.ts",
        "frontend/src/contract/reference.d.ts|react",
        "frontend/src/contract/module.mts|react-dom/client",
        "frontend/src/screens/probe.ts|vendor-sdk",
    }


def test_negative_probe_finds_new_legacy_definition_and_export() -> None:
    assert _public_definitions(
        "from hwpxfiller.domain.job import Job as ImportedJob, _private\n"
        "if True:\n def NewCanonical(): ...\n Alias, _Private = (1, 2)\n",
        "hwpxfiller.core.probe",
    ) == {
        "hwpxfiller.core.probe|Alias",
        "hwpxfiller.core.probe|ImportedJob",
        "hwpxfiller.core.probe|NewCanonical",
        "hwpxfiller.core.probe|_Private",
    }
    with pytest.raises(ContractError, match="star import"):
        _public_definitions("from hwpxfiller.domain.job import *\n", "hwpxfiller.core.probe")
    imported, declared = _facade_exports(
        """from .job import Job, NewExport
if True:
    PublicAlias, _hidden = (object(), object())
__all__ = ['Job', 'NewExport', 'PublicAlias']
""",
        "hwpxfiller.core",
    )
    assert imported == declared == {
        "hwpxfiller.core|Job",
        "hwpxfiller.core|NewExport",
        "hwpxfiller.core|PublicAlias",
    }
    imported, declared = _facade_exports(
        "__all__: list[str] = ['Ghost']\n", "hwpxfiller"
    )
    assert imported == set()
    assert declared == {"hwpxfiller|Ghost"}
    with pytest.raises(ContractError, match="explicit __all__"):
        _facade_exports("pass\n", "hwpxfiller")
    with pytest.raises(ContractError, match="mutation"):
        _facade_exports("__all__ = []\n__all__.append('Ghost')\n", "hwpxfiller")
    with pytest.raises(ContractError, match="mutation"):
        _facade_exports(
            "__all__ = []\n_alias = __all__\n_alias.append('Ghost')\n", "hwpxfiller"
        )
    assert _private_import_edges(
        "from hwpxcore._private import Public\n",
        relative="src/hwpxfiller/domain/probe.py",
        module="hwpxfiller.domain.probe",
        source_is_package=False,
    ) == {"src/hwpxfiller/domain/probe.py|hwpxcore._private"}
    assert _private_import_edges(
        "from importlib import import_module\nimport_module('hwpxcore._private')\n",
        relative="src/hwpxfiller/domain/probe.py",
        module="hwpxfiller.domain.probe",
        source_is_package=False,
    ) == {"src/hwpxfiller/domain/probe.py|hwpxcore._private"}
