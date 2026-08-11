"""P3 namespace/kernel 이동 전 금지 edge 게이트와 합성 음성 대조(#592).

정의역은 P2 ring 좌표와 P3 census 다. 현재 잔존 위반은
``tests/kernel_boundary_contract.toml``의 exact allowlist와 양방향 대조한다. P3-99에서
그 원장을 제거하거나 영구 계약으로 승격할 때 이 게이트도 같은 변경으로 처분한다.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
CENSUS = ROOT / "docs" / "p3_kernel_census.toml"
RINGS = ROOT / "docs" / "module_rings.toml"
POLICY = ROOT / "tests" / "kernel_boundary_contract.toml"

EXPECTED_SCHEMA = "kernel-boundary/v1"
EXPECTED_ALLOWLISTS = {
    "kernel_product_import",
    "kernel_effect",
    "legacy_consumer",
    "legacy_definition",
    "legacy_export",
    "legacy_symbol_use",
    "product_vendor_import",
    "vendor_public_type",
}
VALUE_WIDTH = {
    "kernel_product_import": 1,
    "kernel_effect": 2,
    "legacy_consumer": 1,
    "legacy_definition": 1,
    "legacy_export": 1,
    "legacy_symbol_use": 1,
    "product_vendor_import": 1,
    "vendor_public_type": 2,
}
DEFINITION_CLUSTER_ID = {
    "hwpxfiller.core.job|_key_names_the_same_file": "FC-09",
    "hwpxfiller.core.mapping|MappingProfile.load": "FC-12",
}
SYMBOL_USE = {"FC-12": "MappingProfile.load"}
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


class ContractError(ValueError):
    """정책을 exact allowlist로 해석할 수 없을 때의 fail-closed 오류."""


def _census() -> dict[str, object]:
    return tomllib.loads(CENSUS.read_text(encoding="utf-8-sig"))


def _entries() -> "list[dict[str, object]]":
    return _census()["entry"]  # type: ignore[return-value]


def _rings() -> "list[dict[str, object]]":
    document = tomllib.loads(RINGS.read_text(encoding="utf-8-sig"))
    return document["unit"]  # type: ignore[return-value]


def _known_modules() -> set[str]:
    return {str(entry["current_module"]) for entry in _entries()}


def _validate_policy(document: dict[str, object]) -> dict[str, set[str]]:
    if document.get("schema") != EXPECTED_SCHEMA:
        raise ContractError(f"policy schema는 {EXPECTED_SCHEMA!r} 이어야 합니다")
    raw = document.get("allowlist")
    if not isinstance(raw, dict) or set(raw) != EXPECTED_ALLOWLISTS:
        raise ContractError(f"allowlist 키가 고정 기대와 다릅니다: {set(raw or {})}")

    entries = {str(entry["id"]): entry for entry in _entries()}
    out: dict[str, set[str]] = {}
    for name in sorted(EXPECTED_ALLOWLISTS):
        grouped = raw[name]
        if not isinstance(grouped, dict) or list(grouped) != sorted(grouped):
            raise ContractError(f"{name}은 census ID 순으로 정렬된 table이어야 합니다")
        facts: set[str] = set()
        for census_id, values in grouped.items():
            if census_id not in entries:
                raise ContractError(f"{name}: 알 수 없는 census ID {census_id!r}")
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ContractError(f"{name}.{census_id}은 문자열 배열이어야 합니다")
            if values != sorted(values) or len(values) != len(set(values)):
                raise ContractError(f"{name}.{census_id}은 중복 없는 정렬 목록이어야 합니다")
            module = str(entries[census_id]["current_module"])
            for value in values:
                if any(token in value for token in ("*", "?", "[", "]")):
                    raise ContractError(f"{name} wildcard 금지: {value!r}")
                if len(value.split("|")) != VALUE_WIDTH[name]:
                    raise ContractError(f"{name} record 형식 오류: {value!r}")
                fact = (
                    f"{value}|{module}"
                    if name in {"legacy_consumer", "legacy_symbol_use"}
                    else f"{module}|{value}"
                )
                if fact in facts:
                    raise ContractError(f"{name}: 여러 census ID가 같은 residual을 가리킵니다: {fact}")
                entry = entries[census_id]
                if name == "legacy_consumer" and entry.get("consumer_kind") == "symbol_use":
                    raise ContractError(f"{name}: symbol-use cluster는 module consumer를 소유할 수 없습니다")
                if name == "legacy_symbol_use" and entry.get("consumer_kind") != "symbol_use":
                    raise ContractError(f"{name}: symbol-use census cluster만 소유할 수 있습니다")
                if name == "kernel_effect" and (
                    entry["disposition"] == "FORMAT_KERNEL"
                    or not entry["environment_or_effect"]
                ):
                    raise ContractError(f"{name}: effect 소유 census cluster가 아닙니다: {census_id}")
                if name == "legacy_definition":
                    expected = DEFINITION_CLUSTER_ID.get(fact)
                    if expected and census_id != expected:
                        raise ContractError(f"{fact}의 census cluster는 {expected}입니다")
                    if not expected and census_id in DEFINITION_CLUSTER_ID.values():
                        raise ContractError(f"{census_id}에는 그 cluster의 exact symbol만 허용됩니다")
                facts.add(fact)
        out[name] = facts
    return out


def _policy() -> dict[str, set[str]]:
    return _validate_policy(tomllib.loads(POLICY.read_text(encoding="utf-8-sig")))


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


def _dynamic_import_names(tree: ast.AST) -> set[str]:
    # ponytail: 계산형 모듈명은 현행에 없으므로 도입될 때 constant propagation을 추가한다.
    aliases = _aliases(tree)
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and node.args
        and _qualified_name(node.func, aliases).rsplit(".", 1)[-1]
        in {"__import__", "find_spec", "import_module"}
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _dynamic_targets(tree: ast.AST, known: set[str]) -> set[str]:
    targets = {
        match
        for value in _dynamic_import_names(tree)
        if (match := _match_module(value, known))
    }
    aliases = _aliases(tree)

    def add_literal(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if match := _match_module(node.value, known):
                targets.add(match)

    def add_literals(node: ast.AST) -> None:
        for item in ast.walk(node):
            add_literal(item)

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
    return _import_targets(
        tree,
        source_module=source_module,
        source_is_package=source_is_package,
        known=known,
    ) | _dynamic_targets(tree, known)


def _source_paths() -> list[Path]:
    paths: set[Path] = set()
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


def _symbol_use_sources(module: str, symbol: str) -> set[str]:
    expected = f"{module}.{symbol}"
    sources: set[str] = set()
    for path in _source_paths():
        relative = path.relative_to(ROOT).as_posix()
        tree = _tree(path.read_bytes(), relative)
        aliases = _aliases(
            tree,
            _module_for_path(path),
            source_is_package=path.name == "__init__.py",
        )
        if any(
            isinstance(node, ast.Attribute)
            and _qualified_name(node, aliases) == expected
            for node in ast.walk(tree)
        ):
            sources.add(relative)
    return sources


def _category(relative: str) -> str:
    root = relative.split("/", 1)[0]
    if root == "src":
        return "production"
    if root == "tests":
        return "test"
    if root in {"scripts", "examples"}:
        return "scripts"
    return "build"


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

    def visit(body: list[ast.stmt], owner: str) -> None:
        for node in body:
            names: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
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


def _legacy_definitions() -> set[str]:
    sources = {str(unit["module"]): unit["source_write_set"] for unit in _rings()}
    out: set[str] = set()
    for module in sorted(m for m in _known_modules() if m.startswith("hwpxfiller.core")):
        for relative in sources[module]:
            out |= _public_definitions((ROOT / str(relative)).read_bytes(), module)
    return out


def _facade_exports(source: "str | bytes", module: str) -> tuple[set[str], set[str]]:
    tree = _tree(source, module)
    imported: set[str] = set()
    declared: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                names.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, ast.Assign) and "__all__" in {
                name for target in node.targets for name in _bound_names(target)
            }:
                declared.update(ast.literal_eval(node.value))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names.update(name for target in targets for name in _bound_names(target))
            elif isinstance(node, ast.TypeAlias):
                names.update(_bound_names(node.name))
            imported.update(name for name in names if not name.startswith("_"))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(_same_scope_body(node))

    visit(tree.body)
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
            elif qualified == "zipfile.ZipFile" and node.args:
                if not memoryish(node.args[0]):
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

    def visit(body: list[ast.stmt], owner: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and public(node.name):
                for name in _function_annotations(node, aliases):
                    if _is_vendor_name(name):
                        edges.add(f"{module}|{owner}{node.name}|{name}")
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
                    record(f"{owner}{node.name.id}", node.value)
            elif isinstance(node, ast.ClassDef) and public(node.name):
                for base in node.bases:
                    record(f"{owner}{node.name}", base)
                visit(node.body, f"{owner}{node.name}.")
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(_same_scope_body(node), owner)

    visit(tree.body)
    return edges


def test_policy_is_exact_sorted_and_wildcard_free() -> None:
    _policy()


def test_census_consumer_counts_match_executable_import_graph() -> None:
    known = _known_modules()
    edges = _consumer_edges(known)
    by_module: dict[str, set[str]] = {module: set() for module in known}
    for edge in edges:
        relative, target = edge.split("|", 1)
        if not target.endswith(".*"):
            by_module[target].add(relative)
    entries = _entries()
    assert {
        str(entry["id"])
        for entry in entries
        if entry["consumer_kind"] == "symbol_use"
    } == set(SYMBOL_USE)
    symbol_facts: set[str] = set()
    for entry in entries:
        module = str(entry["current_module"])
        if entry["consumer_kind"] == "symbol_use":
            sources = _symbol_use_sources(module, SYMBOL_USE[str(entry["id"])])
            symbol_facts.update(f"{source}|{module}" for source in sources)
        else:
            assert entry["consumer_kind"] == "module_import"
            sources = by_module[module]
        actual = {name: 0 for name in ("production", "test", "scripts", "build")}
        for relative in sources:
            actual[_category(relative)] += 1
        assert actual == entry["consumers"], f"{entry['id']}: consumer census drift {actual}"
    assert symbol_facts == _policy()["legacy_symbol_use"]


def test_legacy_consumers_are_the_exact_shrinking_allowlist() -> None:
    actual = {
        edge
        for edge in _consumer_edges(_known_modules())
        if edge.split("|", 1)[1].startswith("hwpxfiller.core")
    }
    assert actual == _policy()["legacy_consumer"], (
        f"legacy consumer added={sorted(actual - _policy()['legacy_consumer'])}, "
        f"stale={sorted(_policy()['legacy_consumer'] - actual)}"
    )


def test_legacy_namespace_has_no_new_definition_or_export() -> None:
    policy = _policy()
    assert _legacy_definitions() == policy["legacy_definition"]
    actual: set[str] = set()
    for module in ("hwpxcore", "hwpxfiller.core"):
        imported, declared = _facade_exports(_source_for_module(module), module)
        assert imported == declared
        actual |= imported
    assert actual == policy["legacy_export"]


def test_hwpxcore_has_no_new_product_import_or_environment_effect() -> None:
    product_imports: set[str] = set()
    effects: set[str] = set()
    format_modules = {
        str(entry["current_module"])
        for entry in _entries()
        if entry["disposition"] == "FORMAT_KERNEL"
    }
    for module in sorted(m for m in _known_modules() if m.startswith("hwpxcore")):
        source = _source_for_module(module)
        product_imports |= _kernel_product_import_edges(source, module)
    for module in sorted(format_modules):
        source = _source_for_module(module)
        effects |= _kernel_effect_edges(source, module)
    policy = _policy()
    assert product_imports == policy["kernel_product_import"]
    assert effects == policy["kernel_effect"], (
        f"kernel effect added={sorted(effects - policy['kernel_effect'])}, "
        f"stale={sorted(policy['kernel_effect'] - effects)}"
    )


def test_product_contract_has_no_new_vendor_import_or_public_type() -> None:
    imports: set[str] = set()
    public_types: set[str] = set()
    for module in sorted(_product_modules()):
        source = _source_for_module(module)
        imports |= _vendor_import_edges(source, module)
        public_types |= _vendor_public_type_edges(source, module)
    policy = _policy()
    assert imports == policy["product_vendor_import"]
    assert public_types == policy["vendor_public_type"]


def test_negative_probe_rejects_hwpxcore_product_import() -> None:
    source = """from importlib import import_module as load
from hwpxfiller.domain.job import Job
load('hwpxfiller.core.job')
"""
    assert _kernel_product_import_edges(source, "hwpxcore.package") == {
        "hwpxcore.package|hwpxfiller.core.job",
        "hwpxcore.package|hwpxfiller.domain.job",
    }


def test_negative_probe_finds_direct_dynamic_and_build_legacy_consumers() -> None:
    known = _known_modules()
    cases = (
        "from hwpxfiller.core.job import Job\n",
        "import importlib\nimportlib.import_module('hwpxfiller.core.job')\n",
        "from importlib import import_module as load\nload('hwpxfiller.core.job')\n",
        "Analysis([], hiddenimports=['hwpxfiller.core.job'])\n",
    )
    for source in cases:
        assert _consumer_targets(
            source,
            source_module="hwpxfiller.application.probe",
            known=known,
            filename="<probe>",
        ) == {"hwpxfiller.core.job"}
    assert _entry_point_targets(
        {
            "project": {
                "entry-points": {
                    "probe": {"legacy": "hwpxfiller.core.job:Job"}
                }
            }
        },
        known,
    ) == {"hwpxfiller.core.job"}


def test_negative_probe_rejects_wildcard_allowlist() -> None:
    allowlist = {name: {} for name in EXPECTED_ALLOWLISTS}
    allowlist["legacy_consumer"] = {"FC-08": ["src/**"]}
    with pytest.raises(ContractError, match="wildcard"):
        _validate_policy({"schema": EXPECTED_SCHEMA, "allowlist": allowlist})


def test_negative_probe_finds_kernel_path_save() -> None:
    source = """import io
import zipfile
from pathlib import Path
def to_bytes(path: str) -> bytes:
    Path(path).write_bytes(b'x')
    return b'x'
def open_zip(source):
    return zipfile.ZipFile(source)
def memory():
    buf = io.BytesIO()
def parse(buf):
    return zipfile.ZipFile(buf)
"""
    assert _kernel_effect_edges(source, "hwpxcore.codec") == {
        "hwpxcore.codec|<module>|import:pathlib.Path",
        "hwpxcore.codec|open_zip|filesystem:zipfile.ZipFile",
        "hwpxcore.codec|parse|filesystem:zipfile.ZipFile",
        "hwpxcore.codec|to_bytes|filesystem:write_bytes",
        "hwpxcore.codec|to_bytes|pathlib",
    }


def test_negative_probe_finds_vendor_type_contract_exposure() -> None:
    source = """import lxml
import zipfile
from importlib import import_module as load
from typing import TYPE_CHECKING, Protocol
if TYPE_CHECKING:
    from lxml.etree import _Element
load('lxml.etree')
type ElementList = list['_Element']
class Contract(Protocol):
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
        "hwpxfiller.application.contract|ElementList|lxml.etree._Element",
    }


def test_negative_probe_finds_new_legacy_definition_and_export() -> None:
    assert _public_definitions(
        "if True:\n def NewCanonical(): ...\n Alias, _Private = (1, 2)\n",
        "hwpxfiller.core.probe",
    ) == {
        "hwpxfiller.core.probe|Alias",
        "hwpxfiller.core.probe|NewCanonical",
        "hwpxfiller.core.probe|_Private",
    }
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
