"""AST 기반 수집기 — import·call·construct·attribute write 축의 기반 사실 방출.

이 수집기는 **모듈-국소 정적 해석**만 한다: 같은 모듈 안에서 정적으로 완결되는 참조와
import 표를 한 겹 따라가는 참조는 좌표로 해석하고, 그 밖은 전부 미해결(``?:``)·동적
(``dynamic_site``) 사실로 **시끄럽게** 남긴다. 문자열 디스패치 복원·상속(MRO) 해소·주입
콜백의 데이터플로는 P1-02A/B(#513·#514) 소유다 — 여기서 어설프게 추측하면 「unresolved
call 을 임의 callee 로 추측하지 않는다」 불변식이 깨진다.

해석의 정직한 경계(#512 — 이해 못 한 형태의 조용한 통과 금지):

- 함수 지역 바인딩이 모듈 이름을 가리는 경우를 지역 이름 표로 걸러 ``?:local:`` 로
  남긴다. 지역 표는 매개변수·단순 할당·for/with/except 표적까지만 본다 — 그 밖의 가림은
  과신(잘못된 STATIC_CONFIRMED) 대신 미해결 방향으로 샌다.
- 호출 대상이 수집기가 모르는 식 형태(호출의 호출 등)면 ``dynamic_site``(UNKNOWN)를
  방출한다. skip 이 아니다.
- 속성 **읽기** 전수 조사는 P1-02B 소유다. 여기서는 리터럴 getattr/hasattr 만
  ``reads_attribute`` 로 남긴다(전 속성 접근을 다 적으면 기반 shard 가 잡음이 된다).
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from pathlib import Path

from .closure import Closure, ModuleFile, production_closure
from .schema import (
    Evidence,
    Fact,
    FactGraphError,
    Provenance,
    Symbol,
    is_symbol_ref,
    parse_symbol_id,
    symbol_id,
)

COLLECTOR = "factgraph.collect"

_GETATTR_FAMILY = {"getattr", "hasattr", "delattr", "setattr"}
_DYNAMIC_BUILTINS = {"__import__": "dynamic_import", "exec": "dynamic_exec", "eval": "dynamic_exec"}
_BUILTIN_NAMES = frozenset(dir(builtins))
_IMPORT_ANCHOR_SEP = "<-"
_IMPORT_ANCHOR_COORD_SEP = "@c"
_BINDING_UNBOUND = "?:binding:unbound"
_BINDING_OPAQUE = "?:binding:opaque"
_EXPORT_REF_PREFIX = "?:export:"
_IDENTITY_DECORATORS = frozenset(
    {"ext:dataclasses.dataclass", "ext:typing.runtime_checkable"}
)


def import_binding_anchor(bound: str, imported: str, node: "ast.AST | None" = None) -> str:
    """한 import alias의 결속 이름과 원 이름을 함께 보존하는 고유 anchor."""
    anchor = f"{bound}{_IMPORT_ANCHOR_SEP}{imported}"
    if node is None:
        return anchor
    return (
        f"{anchor}{_IMPORT_ANCHOR_COORD_SEP}"
        f"{getattr(node, 'col_offset', -1)}-{getattr(node, 'end_col_offset', -1)}"
    )


def import_bound_name(anchor: str) -> str:
    """``import_binding_anchor``에서 재수출에 쓰는 결속 이름을 되읽는다."""
    bound, sep, _imported = anchor.partition(_IMPORT_ANCHOR_SEP)
    return bound if sep else anchor  # #512 구형 fact와 합칠 때도 안전하게 읽는다


def import_original_name(anchor: str) -> str:
    """``import_binding_anchor``에서 source에 적힌 원 import 이름을 되읽는다."""
    _bound, sep, imported = anchor.partition(_IMPORT_ANCHOR_SEP)
    imported = imported.partition(_IMPORT_ANCHOR_COORD_SEP)[0]
    return imported if sep else anchor


def collect_symbols(repo_root: Path, closure: "Closure | None" = None) -> tuple[Symbol, ...]:
    repo_root = Path(repo_root)
    closure = closure or production_closure(repo_root)
    out: list[Symbol] = []
    for mf in closure.modules:
        out.extend(_module_symbols(mf, _parse(repo_root, mf)))
    # 조건부 재정의(try/except 폴백 등)는 같은 ID 로 접힌다 — 인벤토리는 ID 집합이다.
    unique = {s.id: s for s in out}
    return tuple(sorted(unique.values(), key=lambda s: s.id))


def collect_facts(
    repo_root: Path,
    closure: "Closure | None" = None,
    symbols: "tuple[Symbol, ...] | None" = None,
    runtime_exports: "dict[tuple[str, str], frozenset[str]] | None" = None,
) -> tuple[Fact, ...]:
    repo_root = Path(repo_root)
    closure = closure or production_closure(repo_root)
    symbols = symbols if symbols is not None else collect_symbols(repo_root, closure)
    index = {(s.module, s.qualname): s for s in symbols}
    modules_by_name = {mf.module: mf for mf in closure.modules}
    trees = {mf.module: _parse(repo_root, mf) for mf in closure.modules}
    runtime_exports = runtime_exports or runtime_module_exports(
        repo_root, closure, symbols, trees=trees
    )
    # 모듈-수준 상수(할당 바인딩)는 def/class 심볼이 아니지만 import 대상이다 — 이 표가
    # 없으면 상수 import 전부가 미해결로 새서 「폐포 안 해석 완료」 주장이 좁아진다.
    constants = {module: _module_level_names(tree) for module, tree in trees.items()}
    facts: list[Fact] = []
    for mf in closure.modules:
        walker = _FactsWalker(
            mf,
            trees[mf.module],
            index,
            modules_by_name,
            constants,
            runtime_exports,
        )
        facts.extend(walker.run())
    return tuple(sorted(set(facts), key=Fact.sort_key))


def runtime_module_exports(
    repo_root: Path,
    closure: Closure,
    symbols: tuple[Symbol, ...],
    *,
    trees: "dict[str, ast.Module] | None" = None,
) -> dict[tuple[str, str], frozenset[str]]:
    """성공적으로 초기화된 module의 최종 이름 바인딩 후보를 source-order로 계산한다.

    함수 body의 global lookup과 facade 재수출은 정의가 보인 순서가 아니라 module 초기화가
    끝난 뒤의 namespace를 본다. 조건부 branch·삭제·opaque assignment는 후보 집합에 그대로
    남겨 유일 target이 아닐 때 STATIC으로 승격하지 않는다.
    """
    repo_root = Path(repo_root)
    trees = trees or {mf.module: _parse(repo_root, mf) for mf in closure.modules}
    modules = {mf.module for mf in closure.modules}
    index = {(symbol.module, symbol.qualname): symbol for symbol in symbols}

    def from_base(mf: ModuleFile, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        parts = mf.module.split(".")
        if not mf.path.endswith("__init__.py"):
            parts = parts[:-1]
        if node.level > 1:
            parts = parts[: len(parts) - (node.level - 1)]
        return ".".join(parts + ([node.module] if node.module else []))

    def merge(states: "list[dict[str, set[str]]]") -> dict[str, set[str]]:
        keys = {name for state in states for name in state}
        return {
            name: set().union(
                *(state.get(name, {_BINDING_UNBOUND}) for state in states)
            )
            for name in keys
        }

    def is_type_guard(test: ast.expr, state: dict[str, set[str]]) -> bool:
        if isinstance(test, ast.Name):
            return state.get(test.id) == {"ext:typing.TYPE_CHECKING"}
        return bool(
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and state.get(test.value.id) == {"ext:typing"}
        )

    def decorators_preserve_identity(
        node: "ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef",
        state: dict[str, set[str]],
    ) -> bool:
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            resolved: set[str] | None = None
            if isinstance(target, ast.Name):
                resolved = state.get(target.id)
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and len(state.get(target.value.id, set())) == 1
            ):
                root = next(iter(state[target.value.id]))
                resolved = {f"{root}.{target.attr}"}
            if resolved is None or len(resolved) != 1 or not resolved <= _IDENTITY_DECORATORS:
                return False
            if resolved == {"ext:dataclasses.dataclass"} and isinstance(decorator, ast.Call):
                if any(
                    keyword.arg is None
                    or (
                        keyword.arg == "slots"
                        and not (
                            isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is False
                        )
                    )
                    for keyword in decorator.keywords
                ):
                    return False
        return True

    def execute(
        mf: ModuleFile, body: "list[ast.stmt]", incoming: dict[str, set[str]]
    ) -> dict[str, set[str]]:
        state = {name: set(targets) for name, targets in incoming.items()}
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = index.get((mf.module, stmt.name))
                state[stmt.name] = (
                    {
                        symbol.id
                        if symbol is not None
                        else symbol_id(mf.module, stmt.name, "function")
                    }
                    if decorators_preserve_identity(stmt, state)
                    else {_BINDING_OPAQUE}
                )
            elif isinstance(stmt, ast.ClassDef):
                symbol = index.get((mf.module, stmt.name))
                state[stmt.name] = (
                    {
                        symbol.id
                        if symbol is not None
                        else symbol_id(mf.module, stmt.name, "class")
                    }
                    if decorators_preserve_identity(stmt, state)
                    else {_BINDING_OPAQUE}
                )
            elif isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    bound = alias.asname or alias.name.split(".", 1)[0]
                    runtime_module = alias.name if alias.asname else alias.name.split(".", 1)[0]
                    state[bound] = {
                        symbol_id(runtime_module, "", "module")
                        if runtime_module in modules
                        else f"ext:{runtime_module}"
                    }
            elif isinstance(stmt, ast.ImportFrom):
                base = from_base(mf, stmt)
                for alias in stmt.names:
                    if alias.name == "*":
                        for targets in state.values():
                            targets.add(_BINDING_OPAQUE)
                        state["*"] = {_BINDING_OPAQUE}
                        continue
                    bound = alias.asname or alias.name
                    full = f"{base}.{alias.name}" if base else alias.name
                    if base in modules:
                        target = f"{_EXPORT_REF_PREFIX}{base}:{alias.name}"
                    elif full in modules:
                        target = symbol_id(full, "", "module")
                    else:
                        target = f"ext:{full}"
                    state[bound] = {target}
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    for name in _target_names(target):
                        state[name] = {f"attr:{mf.module}:{name}"}
            elif isinstance(stmt, ast.AnnAssign):
                if stmt.value is None:
                    continue  # annotation-only 문은 runtime binding을 만들지 않는다
                for name in _target_names(stmt.target):
                    state[name] = {f"attr:{mf.module}:{name}"}
            elif isinstance(stmt, ast.AugAssign):
                for name in _target_names(stmt.target):
                    state[name] = {f"attr:{mf.module}:{name}"}
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    for name in _target_names(target):
                        state[name] = {_BINDING_UNBOUND}
            elif isinstance(stmt, ast.If):
                if is_type_guard(stmt.test, state):
                    state = execute(mf, stmt.orelse, state)
                else:
                    body_state = execute(mf, stmt.body, state)
                    else_state = execute(mf, stmt.orelse, state) if stmt.orelse else state
                    state = merge([body_state, else_state])
            elif isinstance(stmt, ast.Try):
                success = execute(mf, stmt.orelse, execute(mf, stmt.body, state))
                branches = [success, state]
                branches.extend(execute(mf, handler.body, state) for handler in stmt.handlers)
                state = execute(mf, stmt.finalbody, merge(branches))
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                iterated = execute(mf, stmt.body, state)
                merged = merge([state, iterated])
                else_state = execute(mf, stmt.orelse, merged)
                state = merge([merged, else_state]) if stmt.orelse else merged
                if isinstance(stmt, (ast.For, ast.AsyncFor)):
                    for name in _target_names(stmt.target):
                        state.setdefault(name, set()).add(_BINDING_UNBOUND)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                state = execute(mf, stmt.body, state)
                for item in stmt.items:
                    if item.optional_vars is not None:
                        for name in _target_names(item.optional_vars):
                            state[name] = {_BINDING_OPAQUE}
            elif isinstance(stmt, ast.Match):
                branches = [state]
                branches.extend(execute(mf, case.body, state) for case in stmt.cases)
                state = merge(branches)
        return state

    raw: dict[tuple[str, str], set[str]] = {}
    for mf in closure.modules:
        final = execute(mf, trees[mf.module].body, {})
        raw.update({(mf.module, name): targets for name, targets in final.items()})

    for _round in range(len(raw) + 1):
        changed = False
        for key, targets in list(raw.items()):
            expanded: set[str] = set()
            for target in targets:
                if not target.startswith(_EXPORT_REF_PREFIX):
                    expanded.add(target)
                    continue
                module_name, sep, export_name = target.removeprefix(
                    _EXPORT_REF_PREFIX
                ).rpartition(":")
                if not sep:
                    expanded.add(_BINDING_OPAQUE)
                    continue
                exported = raw.get((module_name, export_name))
                if exported is not None and exported != {target}:
                    expanded.update(exported)
                else:
                    submodule = f"{module_name}.{export_name}"
                    expanded.add(
                        symbol_id(submodule, "", "module")
                        if submodule in modules
                        else _BINDING_UNBOUND
                    )
            if expanded != targets:
                raw[key] = expanded
                changed = True
        if not changed:
            break
    return {key: frozenset(targets) for key, targets in raw.items()}


def _module_level_names(tree: ast.Module) -> frozenset[str]:
    """모듈 수준(조건부 블록 포함, def/class 내부 제외)에서 할당으로 묶이는 이름 전부."""
    names: set[str] = set()

    def visit(body: "list[ast.stmt]") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    names.update(_target_names(t))
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                names.update(_target_names(node.target))
                visit(node.body)
                visit(node.orelse)
                continue
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        names.update(_target_names(item.optional_vars))
            for block in _stmt_blocks(node):
                visit(block)
    visit(tree.body)
    return frozenset(names)


def _parse(repo_root: Path, mf: ModuleFile) -> ast.Module:
    path = repo_root / mf.path
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=mf.path)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        # 읽기·파싱 실패는 「사실 없음」이 아니라 구조 오류다 — 조용한 skip 금지.
        raise FactGraphError(f"모듈을 파싱할 수 없다: {mf.path} ({exc})") from exc


def _direct_import_origins(
    mf: ModuleFile, tree: ast.Module
) -> "tuple[dict[str, set[str]], dict[str, set[str]]]":
    """모듈 namespace에 직접 쓰인 import origin 후보를 보수적으로 모은다.

    ``runtime_module_exports``는 최종 객체를 알려 주지만, 그 객체가 한 단계 import로
    들어왔는지 facade 여러 겹을 거쳤는지는 의도적으로 평탄화한다. 기반 수집기는 한 단계
    import만 닫고 다단 재수출은 #513 파생 그래프에 남겨야 하므로 두 정보를 분리한다.
    함수·클래스 내부 import는 module global 결속이 아니어서 내려가지 않는다.
    """
    symbol_origins: dict[str, set[str]] = {}
    module_targets: dict[str, set[str]] = {}

    def from_base(node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        parts = mf.module.split(".")
        if not mf.path.endswith("__init__.py"):
            parts = parts[:-1]
        if node.level > 1:
            parts = parts[: len(parts) - (node.level - 1)]
        return ".".join(parts + ([node.module] if node.module else []))

    def visit(body: "list[ast.stmt]") -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    bound = alias.asname or alias.name.split(".", 1)[0]
                    target = alias.name if alias.asname else alias.name.split(".", 1)[0]
                    module_targets.setdefault(bound, set()).add(target)
                continue
            if isinstance(stmt, ast.ImportFrom):
                base = from_base(stmt)
                for alias in stmt.names:
                    if alias.name == "*":
                        continue
                    bound = alias.asname or alias.name
                    symbol_origins.setdefault(bound, set()).add(base)
                    full = f"{base}.{alias.name}" if base else alias.name
                    module_targets.setdefault(bound, set()).add(full)
                continue
            for block in _stmt_blocks(stmt):
                visit(block)

    visit(tree.body)
    return symbol_origins, module_targets


# ---------------------------------------------------------------------------
# 심볼 패스
# ---------------------------------------------------------------------------


def _module_symbols(mf: ModuleFile, tree: ast.Module) -> list[Symbol]:
    out = [Symbol(mf.module, "", "module", mf.path, 1)]

    def walk(body: "list[ast.stmt]", prefix: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}{node.name}"
                kind = "method" if in_class else "function"
                out.append(Symbol(mf.module, q, kind, mf.path, node.lineno))
                walk(node.body, f"{q}.<locals>.", False)
            elif isinstance(node, ast.ClassDef):
                q = f"{prefix}{node.name}"
                out.append(Symbol(mf.module, q, "class", mf.path, node.lineno))
                walk(node.body, f"{q}.", True)
            else:
                for block in _stmt_blocks(node):
                    walk(block, prefix, in_class)

    walk(tree.body, "", False)
    return out


def _stmt_blocks(node: ast.stmt) -> "list[list[ast.stmt]]":
    """조건부 정의(if/try/with/for 안의 def)를 놓치지 않도록 문 블록을 편다."""
    blocks: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        block = getattr(node, attr, None)
        if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
            blocks.append(block)
    for handler in getattr(node, "handlers", []) or []:
        blocks.append(handler.body)
    for case in getattr(node, "cases", []) or []:
        blocks.append(case.body)
    return blocks


# ---------------------------------------------------------------------------
# 사실 패스
# ---------------------------------------------------------------------------


@dataclass
class _FnScope:
    symbol_sid: str
    first_param: str  # self/cls 류 — 실제 첫 매개변수 이름
    cls_qual: str  # def 시점의 클래스 좌표 — 메서드가 아니면 ""
    local_names: set[str]
    global_decls: set[str] = field(default_factory=set)


class _FactsWalker:
    def __init__(
        self,
        mf: ModuleFile,
        tree: ast.Module,
        index: "dict[tuple[str, str], Symbol]",
        modules_by_name: "dict[str, ModuleFile]",
        constants: "dict[str, frozenset[str]] | None" = None,
        runtime_exports: "dict[tuple[str, str], frozenset[str]] | None" = None,
    ) -> None:
        self.mf = mf
        self.tree = tree
        self.index = index
        self.symbols_by_id = {symbol.id: symbol for symbol in index.values()}
        self.modules = modules_by_name
        self.constants = constants or {}
        self.runtime_exports = runtime_exports or {}
        self.future_annotations = any(
            isinstance(stmt, ast.ImportFrom)
            and stmt.module == "__future__"
            and any(alias.name == "annotations" for alias in stmt.names)
            for stmt in tree.body
        )
        self.module_sid = symbol_id(mf.module, "", "module")
        self.facts: list[Fact] = []
        # 모듈 수준 바인딩: 이름 → dst 문자열(symbol ID 또는 ext:)
        # module body는 위에서 아래로 실행된다. 전체 symbol inventory를 미리 넣으면
        # ``helper(); def helper`` 같은 forward reference를 거짓 STATIC으로 만든다.
        self.bindings: dict[str, str] = {}
        # import a.b [as c] 로 묶인 모듈 별칭: 이름 → 점 경로
        self.module_aliases: dict[str, str] = {}
        self.final_bindings: dict[str, str] = {}
        self.final_module_aliases: dict[str, str] = {}
        direct_symbol_origins, direct_module_targets = _direct_import_origins(mf, tree)
        for (module, name), targets in self.runtime_exports.items():
            if module != mf.module or len(targets) != 1:
                continue
            target = next(iter(targets))
            if target.startswith("?:"):
                continue
            if is_symbol_ref(target):
                target_module, _target_qual, target_kind = parse_symbol_id(target)
                if target_kind == "module":
                    if (
                        target_module == mf.module
                        or target_module in direct_module_targets.get(name, set())
                    ):
                        self.final_module_aliases[name] = target_module
                elif (
                    target_module == mf.module
                    or target_module in direct_symbol_origins.get(name, set())
                ):
                    self.final_bindings[name] = target
            elif target.startswith("ext:"):
                self.final_bindings[name] = target
            elif target.startswith("attr:"):
                _prefix, target_module, _target_name = target.split(":", 2)
                if (
                    target_module == mf.module
                    or target_module in direct_symbol_origins.get(name, set())
                ):
                    self.final_bindings[name] = target
        # builtin 구조 규칙(getattr/super)은 module 어디선가 같은 이름을 묶으면 보수적으로
        # 끈다. 함수 body는 module 초기화 뒤 실행될 수 있어 뒤쪽 rebinding도 영향을 준다.
        self.module_bound_names = _module_bound_names(tree)
        self.fn_stack: list[_FnScope] = []
        self.class_stack: list[str] = []  # class qualname
        self.class_global_bindings: list[tuple[dict[str, str], dict[str, str]]] = []
        self.qual_prefix: list[str] = []
        self.type_checking_depth = 0
        self.expression_shadow_stack: list[set[str]] = []

    # -- 공용 -----------------------------------------------------------------

    def run(self) -> list[Fact]:
        for stmt in self.tree.body:
            self._walk(stmt)
        return self.facts

    def _src(self) -> str:
        if self.fn_stack:
            return self.fn_stack[-1].symbol_sid
        if self.class_stack:
            sym = self.index.get((self.mf.module, self.class_stack[-1]))
            if sym is not None:
                return sym.id
        return self.module_sid

    def _emit(
        self,
        rel: str,
        dst: str,
        grade: str,
        node: ast.AST,
        rule: str,
        anchor: str = "",
        src: "str | None" = None,
    ) -> None:
        self.facts.append(
            Fact(
                src=src if src is not None else self._src(),
                rel=rel,
                dst=dst,
                grade=grade,
                evidence=Evidence(self.mf.path, getattr(node, "lineno", 0), anchor),
                provenance=Provenance(COLLECTOR, rule),
            )
        )

    # -- 구조 재귀 -------------------------------------------------------------

    @staticmethod
    def _merge_binding_states(
        left_bindings: dict[str, str],
        left_aliases: dict[str, str],
        right_bindings: dict[str, str],
        right_aliases: dict[str, str],
    ) -> "tuple[dict[str, str], dict[str, str]]":
        """두 제어흐름의 확정 결속만 보존하고 갈린 이름은 opaque로 남긴다."""
        names = {
            *left_bindings,
            *left_aliases,
            *right_bindings,
            *right_aliases,
        }
        bindings: dict[str, str] = {}
        aliases: dict[str, str] = {}
        for name in names:
            if (
                name in left_bindings
                and name in right_bindings
                and left_bindings[name] == right_bindings[name]
            ):
                bindings[name] = left_bindings[name]
            elif (
                name in left_aliases
                and name in right_aliases
                and left_aliases[name] == right_aliases[name]
            ):
                aliases[name] = left_aliases[name]
            else:
                bindings[name] = _BINDING_OPAQUE
        return bindings, aliases

    def _walk(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._walk_function(node)
        elif isinstance(node, ast.ClassDef):
            self._walk_class(node)
        elif isinstance(node, ast.Import):
            self._handle_import(node)
        elif isinstance(node, ast.ImportFrom):
            self._handle_import_from(node)
        elif isinstance(node, ast.Global):
            if self.fn_stack:
                self.fn_stack[-1].global_decls.update(node.names)
        elif isinstance(node, ast.If) and self._is_type_checking_guard(node.test):
            self._walk(node.test)
            bindings_before = dict(self.bindings)
            aliases_before = dict(self.module_aliases)
            self.type_checking_depth += 1
            for child in node.body:
                self._walk(child)
            self.type_checking_depth -= 1
            # TYPE_CHECKING body는 runtime module namespace를 만들지 않는다.
            self.bindings = bindings_before
            self.module_aliases = aliases_before
            for child in node.orelse:
                self._walk(child)
        elif isinstance(node, ast.If):
            self._walk(node.test)
            bindings_before = dict(self.bindings)
            aliases_before = dict(self.module_aliases)
            for child in node.body:
                self._walk(child)
            body_bindings = dict(self.bindings)
            body_aliases = dict(self.module_aliases)
            self.bindings = dict(bindings_before)
            self.module_aliases = dict(aliases_before)
            for child in node.orelse:
                self._walk(child)
            else_bindings = dict(self.bindings)
            else_aliases = dict(self.module_aliases)
            self.bindings, self.module_aliases = self._merge_binding_states(
                body_bindings, body_aliases, else_bindings, else_aliases
            )
        elif isinstance(node, (ast.Try, ast.TryStar)):
            bindings_before = dict(self.bindings)
            aliases_before = dict(self.module_aliases)

            # 정상 완료 경로는 body 뒤에 else가 이어진다. handler는 body의 어느 지점에서든
            # 진입할 수 있으므로 진입 전 결속에서 따로 걸어, 성공 경로와 순차 실행처럼
            # 섞이지 않게 한다. 갈린 이름은 아래 merge에서 opaque로 남는다.
            for child in node.body:
                self._walk(child)
            for child in node.orelse:
                self._walk(child)
            branch_states = [(dict(self.bindings), dict(self.module_aliases))]

            for handler in node.handlers:
                self.bindings = dict(bindings_before)
                self.module_aliases = dict(aliases_before)
                if handler.type is not None:
                    self._walk(handler.type)
                if handler.name:
                    self.bindings[handler.name] = _BINDING_OPAQUE
                    self.module_aliases.pop(handler.name, None)
                for child in handler.body:
                    self._walk(child)
                # ``except ... as name``은 handler 종료 때 Python이 이름을 지운다.
                if handler.name:
                    self.bindings.pop(handler.name, None)
                    self.module_aliases.pop(handler.name, None)
                branch_states.append((dict(self.bindings), dict(self.module_aliases)))

            self.bindings, self.module_aliases = branch_states[0]
            for branch_bindings, branch_aliases in branch_states[1:]:
                self.bindings, self.module_aliases = self._merge_binding_states(
                    self.bindings,
                    self.module_aliases,
                    branch_bindings,
                    branch_aliases,
                )
            for child in node.finalbody:
                self._walk(child)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            if isinstance(node, (ast.For, ast.AsyncFor)):
                self._walk(node.iter)
            else:
                self._walk(node.test)
            bindings_before = dict(self.bindings)
            aliases_before = dict(self.module_aliases)
            if isinstance(node, (ast.For, ast.AsyncFor)):
                for name in _target_names(node.target):
                    self.bindings[name] = _BINDING_OPAQUE
                    self.module_aliases.pop(name, None)
            for child in node.body:
                self._walk(child)
            body_bindings = dict(self.bindings)
            body_aliases = dict(self.module_aliases)
            loop_bindings, loop_aliases = self._merge_binding_states(
                body_bindings, body_aliases, bindings_before, aliases_before
            )
            self.bindings = dict(loop_bindings)
            self.module_aliases = dict(loop_aliases)
            for child in node.orelse:
                self._walk(child)
            else_bindings = dict(self.bindings)
            else_aliases = dict(self.module_aliases)
            if node.orelse:
                self.bindings, self.module_aliases = self._merge_binding_states(
                    else_bindings, else_aliases, loop_bindings, loop_aliases
                )
        elif isinstance(node, ast.Call):
            self._handle_call(node)
            for child in ast.iter_child_nodes(node):
                self._walk(child)
        elif isinstance(node, ast.Lambda):
            for default in [*node.args.defaults, *filter(None, node.args.kw_defaults)]:
                self._walk(default)
            params = {
                arg.arg
                for arg in [
                    *node.args.posonlyargs,
                    *node.args.args,
                    node.args.vararg,
                    *node.args.kwonlyargs,
                    node.args.kwarg,
                ]
                if arg is not None
            }
            self.expression_shadow_stack.append(params)
            self._walk(node.body)
            self.expression_shadow_stack.pop()
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            self._walk_comprehension(node)
        elif isinstance(node, ast.AnnAssign):
            self._handle_assign(node)
            self._walk(node.target)
            # Module/class variable annotations are evaluated unless future annotations
            # is active. Function-local variable annotations are never evaluated.
            if not self.future_annotations and (not self.fn_stack or self.class_stack):
                self._walk(node.annotation)
            if node.value is not None:
                self._walk(node.value)
            self._update_assignment_bindings(node)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.NamedExpr)):
            self._handle_assign(node)
            for child in ast.iter_child_nodes(node):
                self._walk(child)
            self._update_assignment_bindings(node)
        elif isinstance(node, ast.Delete):
            for child in ast.iter_child_nodes(node):
                self._walk(child)
            for target in node.targets:
                for name in _target_names(target):
                    self.bindings.pop(name, None)
                    self.module_aliases.pop(name, None)
        else:
            for child in ast.iter_child_nodes(node):
                self._walk(child)

    def _walk_function(self, node: "ast.FunctionDef | ast.AsyncFunctionDef") -> None:
        # 데코레이터·기본값은 바깥 문맥에서 평가된다.
        for dec in node.decorator_list:
            self._emit_bare_decorator(dec)
            self._walk(dec)
        for default in [*node.args.defaults, *filter(None, node.args.kw_defaults)]:
            self._walk(default)
        if not self.future_annotations:
            annotations = [
                *(arg.annotation for arg in node.args.posonlyargs),
                *(arg.annotation for arg in node.args.args),
                *(arg.annotation for arg in node.args.kwonlyargs),
                node.args.vararg.annotation if node.args.vararg is not None else None,
                node.args.kwarg.annotation if node.args.kwarg is not None else None,
                node.returns,
            ]
            for annotation in filter(None, annotations):
                self._walk(annotation)
        qualname = ".".join([*self.qual_prefix, node.name])
        sym = self.index.get((self.mf.module, qualname))
        sid = sym.id if sym is not None else symbol_id(self.mf.module, qualname, "function")
        args = node.args
        params = [
            a.arg
            for a in [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
            if a is not None
        ]
        is_static_method = bool(self.class_stack) and any(
            self._is_staticmethod_decorator(dec) for dec in node.decorator_list
        )
        has_outer_function = bool(self.fn_stack)
        scope = _FnScope(
            symbol_sid=sid,
            first_param="" if is_static_method else (params[0] if params else ""),
            cls_qual=self.class_stack[-1] if self.class_stack else "",
            local_names=set(params) | _assigned_names(node.body),
        )
        self.fn_stack.append(scope)
        self.qual_prefix.extend([node.name, "<locals>"])
        in_class, self.class_stack = self.class_stack, []
        # 함수 안 import 는 그 스코프의 바인딩이다 — 표를 복사해 두고 나갈 때 되돌리지
        # 않으면 지역 별칭이 모듈 수준 해석을 오염시켜 거짓 STATIC_CONFIRMED 가 샌다.
        bindings_before = dict(self.bindings)
        aliases_before = dict(self.module_aliases)
        if not has_outer_function:
            # module function과 direct method의 bare name은 module 초기화가 끝난 최종 globals를
            # 본다. class namespace나 함수 정의보다 앞선 import snapshot을 물려주면 재결속을
            # 옛 target으로 확정하는 거짓 edge가 생긴다.
            self.bindings = dict(self.final_bindings)
            self.module_aliases = dict(self.final_module_aliases)
        elif in_class and self.class_global_bindings:
            global_bindings, global_aliases = self.class_global_bindings[-1]
            self.bindings = dict(global_bindings)
            self.module_aliases = dict(global_aliases)
        for stmt in node.body:
            self._walk(stmt)
        self.bindings = bindings_before
        self.module_aliases = aliases_before
        self.class_stack = in_class
        self.qual_prefix = self.qual_prefix[:-2]
        self.fn_stack.pop()
        self.bindings[node.name] = (
            sid if self._decorators_preserve_identity(node.decorator_list) else _BINDING_OPAQUE
        )
        self.module_aliases.pop(node.name, None)

    def _walk_class(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self._emit_bare_decorator(dec)
            self._walk(dec)
        qualname = ".".join([*self.qual_prefix, node.name])
        cls_sym = self.index.get((self.mf.module, qualname))
        cls_sid = cls_sym.id if cls_sym is not None else symbol_id(self.mf.module, qualname, "class")
        # base 순서는 MRO(C3)의 입력이다 — 정렬로 잃지 않도록 anchor 에 서수를 싣는다.
        for order, base in enumerate(node.bases):
            dst, grade = self._resolve_ref(base)
            self._emit(
                "inherits", dst, grade, base, "class_base", anchor=str(order), src=cls_sid,
            )
        for base in [*node.bases, *node.keywords]:
            self._walk(base)
        method_globals = (
            self.class_global_bindings[-1]
            if self.class_global_bindings
            else (dict(self.bindings), dict(self.module_aliases))
        )
        self.class_global_bindings.append(method_globals)
        self.class_stack.append(qualname)
        self.qual_prefix.append(node.name)
        bindings_before = dict(self.bindings)
        aliases_before = dict(self.module_aliases)
        for stmt in node.body:
            self._walk(stmt)
        self.bindings = bindings_before
        self.module_aliases = aliases_before
        self.qual_prefix.pop()
        self.class_stack.pop()
        self.class_global_bindings.pop()
        self.bindings[node.name] = (
            cls_sid if self._decorators_preserve_identity(node.decorator_list) else _BINDING_OPAQUE
        )
        self.module_aliases.pop(node.name, None)

    def _is_type_checking_guard(self, test: ast.expr) -> bool:
        """실제 ``typing.TYPE_CHECKING`` 바인딩만 runtime-false guard로 인정한다."""
        if isinstance(test, ast.Name):
            return self.bindings.get(test.id) == "ext:typing.TYPE_CHECKING"
        if (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
        ):
            return self.module_aliases.get(test.value.id) == "typing"
        return False

    def _decorators_preserve_identity(self, decorators: "list[ast.expr]") -> bool:
        for decorator in decorators:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            resolved: str | None = None
            if isinstance(target, ast.Name):
                resolved = self.bindings.get(target.id)
            elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                module = self.module_aliases.get(target.value.id)
                if module is not None:
                    resolved = f"ext:{module}.{target.attr}"
            if resolved not in _IDENTITY_DECORATORS:
                return False
            if resolved == "ext:dataclasses.dataclass" and isinstance(decorator, ast.Call):
                if any(
                    keyword.arg is None
                    or (
                        keyword.arg == "slots"
                        and not (
                            isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is False
                        )
                    )
                    for keyword in decorator.keywords
                ):
                    return False
        return True

    def _walk_comprehension(
        self, node: "ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp"
    ) -> None:
        """comprehension의 implicit function scope를 source evaluation 순서로 걷는다."""
        cumulative: set[str] = set()
        for generator in node.generators:
            self.expression_shadow_stack.append(set(cumulative))
            self._walk(generator.iter)
            self.expression_shadow_stack.pop()
            cumulative.update(_target_names(generator.target))
            self.expression_shadow_stack.append(set(cumulative))
            for condition in generator.ifs:
                self._walk(condition)
            self.expression_shadow_stack.pop()
        self.expression_shadow_stack.append(cumulative)
        if isinstance(node, ast.DictComp):
            self._walk(node.key)
            self._walk(node.value)
        else:
            self._walk(node.elt)
        self.expression_shadow_stack.pop()

    def _builtin_available(self, name: str) -> bool:
        return (
            not self._is_shadowed(name)
            and not any(name in scope.local_names for scope in self.fn_stack)
            and name not in self.module_bound_names
            and name not in self.bindings
            and name not in self.module_aliases
        )

    def _is_staticmethod_decorator(self, decorator: ast.expr) -> bool:
        if isinstance(decorator, ast.Name):
            if decorator.id == "staticmethod" and self._builtin_available("staticmethod"):
                return True
            return self.bindings.get(decorator.id) == "ext:builtins.staticmethod"
        if (
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "staticmethod"
            and isinstance(decorator.value, ast.Name)
        ):
            return self.module_aliases.get(decorator.value.id) == "builtins"
        return False

    def _update_assignment_bindings(
        self, node: "ast.Assign | ast.AugAssign | ast.AnnAssign | ast.NamedExpr"
    ) -> None:
        if isinstance(node, ast.AnnAssign) and node.value is None:
            return
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        simple_value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) else None
        resolved_binding: str | None = None
        resolved_module: str | None = None
        if isinstance(simple_value, ast.Name):
            resolved_binding = self.bindings.get(simple_value.id)
            resolved_module = self.module_aliases.get(simple_value.id)
            if (
                resolved_binding is None
                and resolved_module is None
                and simple_value.id in _BUILTIN_NAMES
                and self._builtin_available(simple_value.id)
            ):
                resolved_binding = f"ext:builtins.{simple_value.id}"
        for target in targets:
            for name in _target_names(target):
                self.bindings.pop(name, None)
                self.module_aliases.pop(name, None)
                if resolved_binding is not None:
                    self.bindings[name] = resolved_binding
                elif resolved_module is not None:
                    self.module_aliases[name] = resolved_module

    def _emit_bare_decorator(self, dec: ast.expr) -> None:
        """괄호 없는 데코레이터(@property 등)도 정의 시점 호출이다 — Call 노드가 아니라
        일반 순회가 놓치므로 여기서 calls 사실을 낸다. @deco(...) 형태는 Call 처리가 맡는다."""
        if isinstance(dec, ast.Call):
            return
        dst, grade = self._resolve_ref(dec)
        self._emit("calls", dst, grade, dec, "decorator", syntax_site_anchor(dec))

    def _resolve_ref(self, expr: ast.expr) -> tuple[str, str]:
        """호출이 아닌 이름 참조(데코레이터·클래스 base)의 dst 해석 — call 해석과 같은 표를 쓴다."""
        if isinstance(expr, ast.Name):
            if self._is_shadowed(expr.id):
                return f"?:local:{expr.id}", "UNKNOWN"
            bound = self.bindings.get(expr.id)
            if bound is not None:
                if bound.startswith("?:"):
                    return f"?:name:{expr.id}", "UNKNOWN"
                symbol = self.symbols_by_id.get(bound)
                if (
                    symbol is not None
                    and symbol.module == self.mf.module
                    and symbol.line > getattr(expr, "lineno", 0)
                ):
                    return f"?:name:{expr.id}", "UNKNOWN"
                return bound, "STATIC_CONFIRMED"
            dotted = self.module_aliases.get(expr.id)
            if dotted is not None:
                return self._module_ref(dotted), "STATIC_CONFIRMED"
            if expr.id in _BUILTIN_NAMES and self._builtin_available(expr.id):
                return f"ext:builtins.{expr.id}", "STATIC_CONFIRMED"
            return f"?:name:{expr.id}", "UNKNOWN"
        if isinstance(expr, ast.Attribute):
            parts: list[str] = []
            base: ast.expr = expr
            while isinstance(base, ast.Attribute):
                parts.insert(0, base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                dotted = self.module_aliases.get(base.id)
                if dotted is not None:
                    if len(parts) == 1 and dotted in self.modules:
                        targets = self.runtime_exports.get((dotted, parts[0]), frozenset())
                        target = next(iter(targets)) if len(targets) == 1 else None
                        if target is not None and is_symbol_ref(target):
                            target_module, _target_qual, target_kind = parse_symbol_id(target)
                            if target_module == dotted and target_kind != "module":
                                return target, "STATIC_CONFIRMED"
                        sub = f"{dotted}.{parts[0]}"
                        if target is not None and target == symbol_id(sub, "", "module"):
                            return symbol_id(sub, "", "module"), "STATIC_CONFIRMED"
                        return f"?:name:{dotted}.{parts[0]}", "UNKNOWN"
                    if dotted not in self.modules:
                        return f"ext:{dotted}.{'.'.join(parts)}", "STATIC_CONFIRMED"
                return f"?:attr:{base.id}.{'.'.join(parts)}", "UNKNOWN"
            return f"?:expr:{type(base).__name__}", "UNKNOWN"
        return f"?:expr:{type(expr).__name__}", "UNKNOWN"

    # -- import ---------------------------------------------------------------

    def _import_rule(self, base: str) -> str:
        return f"import_{base}" if self.type_checking_depth == 0 else f"import_{base}_type_checking"

    def _handle_import(self, node: ast.Import) -> None:
        # import 사실의 anchor = 이 문이 묶는 이름 — 재수출 파생(02A)이 별칭을 복원할 열쇠다.
        for alias in node.names:
            dotted = alias.name
            bound = alias.asname or dotted.split(".", 1)[0]
            self._emit(
                "imports_module", self._module_ref(dotted), "STATIC_CONFIRMED", node,
                self._import_rule("plain"), anchor=import_binding_anchor(bound, dotted, alias),
            )
            self.bindings.pop(bound, None)
            self.module_aliases[bound] = dotted if alias.asname else dotted.split(".", 1)[0]

    def _handle_import_from(self, node: ast.ImportFrom) -> None:
        base = self._from_base(node)
        for alias in node.names:
            if alias.name == "*":
                self._emit(
                    "dynamic_site",
                    f"?:star:{base}",
                    "DECLARED_DYNAMIC",
                    node,
                    "import_star",
                    anchor=import_binding_anchor("*", "*", alias),
                )
                continue
            full = f"{base}.{alias.name}" if base else alias.name
            bound = alias.asname or alias.name
            if base in self.modules:
                sym = self.index.get((base, alias.name))
                constant_ref = f"attr:{base}:{alias.name}"
                targets = self.runtime_exports.get((base, alias.name), frozenset())
                target = next(iter(targets)) if len(targets) == 1 else None
                if sym is not None and target == sym.id:
                    self.module_aliases.pop(bound, None)
                    self.bindings[bound] = target
                    self._emit(
                        "imports_symbol", target, "STATIC_CONFIRMED", node,
                        self._import_rule("from"),
                        anchor=import_binding_anchor(bound, alias.name, alias),
                    )
                elif target == constant_ref:
                    # 모듈-수준 상수(할당 바인딩) — def/class 심볼이 아니라 속성 좌표로 해석한다.
                    self.module_aliases.pop(bound, None)
                    self.bindings[bound] = constant_ref
                    self._emit(
                        "imports_symbol", constant_ref, "STATIC_CONFIRMED", node,
                        self._import_rule("from"),
                        anchor=import_binding_anchor(bound, alias.name, alias),
                    )
                elif not targets and full in self.modules:
                    # package에 runtime attribute가 없을 때만 same-name submodule fallback이다.
                    self.bindings.pop(bound, None)
                    self.module_aliases[bound] = full
                    self._emit(
                        "imports_module",
                        self._module_ref(full),
                        "STATIC_CONFIRMED",
                        node,
                        self._import_rule("from"),
                        anchor=import_binding_anchor(bound, alias.name, alias),
                    )
                else:
                    # 폐포 모듈에서 없는 이름을 가져온다 — 재수출/동적 이름일 수 있다.
                    # 미해결 dst 는 등급도 미해결이다(해석 실패를 확정 증거로 적지 않는다).
                    self._emit(
                        "imports_symbol", f"?:name:{full}", "UNKNOWN", node,
                        self._import_rule("from"),
                        anchor=import_binding_anchor(bound, alias.name, alias),
                    )
                    self.bindings.pop(bound, None)
                    self.module_aliases.pop(bound, None)
                continue
            if full in self.modules:
                self._emit(
                    "imports_module", self._module_ref(full), "STATIC_CONFIRMED", node,
                    self._import_rule("from"), anchor=import_binding_anchor(bound, alias.name, alias),
                )
                self.bindings.pop(bound, None)
                self.module_aliases[bound] = full
                continue
            self._emit(
                "imports_symbol", f"ext:{full}", "STATIC_CONFIRMED", node,
                self._import_rule("from"), anchor=import_binding_anchor(bound, alias.name, alias),
            )
            self.module_aliases.pop(bound, None)
            self.bindings[bound] = f"ext:{full}"

    def _from_base(self, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        parts = self.mf.module.split(".")
        if not self.mf.path.endswith("__init__.py"):
            parts = parts[:-1]
        parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
        return ".".join(parts + ([node.module] if node.module else []))

    def _module_ref(self, dotted: str) -> str:
        if dotted in self.modules:
            return symbol_id(dotted, "", "module")
        return f"ext:{dotted}"

    # -- call -----------------------------------------------------------------

    def _handle_call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and self._builtin_available(func.id):
            if func.id in _GETATTR_FAMILY:
                self._handle_getattr_family(node, func.id)
                return
            if func.id in _DYNAMIC_BUILTINS:
                self._emit(
                    "dynamic_site", f"?:builtin:{func.id}", "DECLARED_DYNAMIC", node,
                    _DYNAMIC_BUILTINS[func.id], call_site_anchor(node),
                )
                return
        if isinstance(func, ast.Name):
            rel, dst, grade, rule = self._resolve_name_call(func.id)
        elif isinstance(func, ast.Attribute):
            rel, dst, grade, rule = self._resolve_attr_call(func)
        else:
            self._emit(
                "dynamic_site", f"?:expr:{type(func).__name__}", "UNKNOWN", node,
                f"call_shape:{type(func).__name__}", call_site_anchor(node),
            )
            return
        self._emit(rel, dst, grade, node, rule, call_site_anchor(node))

    def _is_shadowed(self, name: str) -> bool:
        return any(name in names for names in self.expression_shadow_stack) or any(
            name in scope.local_names and name not in scope.global_decls
            for scope in self.fn_stack
        )

    def _resolve_name_call(self, name: str) -> tuple[str, str, str, str]:
        if self._is_shadowed(name):
            return "calls", f"?:local:{name}", "UNKNOWN", "call_local_binding"
        dst = self.bindings.get(name)
        if dst is not None:
            if dst.startswith("?:"):
                return "calls", f"?:name:{name}", "UNKNOWN", "call_name_unresolved"
            return self._rel_for(dst), dst, "STATIC_CONFIRMED", "call_name"
        dotted = self.module_aliases.get(name)
        if dotted is not None:
            return "calls", self._module_ref(dotted), "INFERRED", "call_module_alias"
        if name in _BUILTIN_NAMES and self._builtin_available(name):
            return "calls", f"ext:builtins.{name}", "STATIC_CONFIRMED", "call_builtin"
        return "calls", f"?:name:{name}", "UNKNOWN", "call_name_unresolved"

    def _resolve_attr_call(self, func: ast.Attribute) -> tuple[str, str, str, str]:
        parts: list[str] = []
        base: ast.expr = func
        while isinstance(base, ast.Attribute):
            parts.insert(0, base.attr)
            base = base.value
        scope = self.fn_stack[-1] if self.fn_stack else None
        if (
            isinstance(base, ast.Call)
            and isinstance(base.func, ast.Name)
            and base.func.id == "super"
            and not base.args
            and not base.keywords
            and self._builtin_available("super")
            and scope is not None
            and scope.cls_qual
            and scope.first_param
            and len(parts) == 1
        ):
            # ``super().method``의 실제 target은 현재 클래스 MRO가 있어야 정직하게 정해진다.
            # 기반 수집기는 전용 좌표만 남기고 #513 정적 그래프가 내부 MRO에서 닫는다.
            return (
                "calls",
                f"?:super:{scope.cls_qual}.{parts[0]}",
                "UNKNOWN",
                "call_super_unresolved",
            )
        if not isinstance(base, ast.Name):
            return (
                "calls", f"?:expr:{type(base).__name__}", "UNKNOWN",
                f"call_shape:{type(base).__name__}",
            )
        root = base.id
        dotted_tail = ".".join(parts)
        if scope is not None and scope.cls_qual and root == scope.first_param:
            # 메서드 안 self/cls 호출 — 자기 클래스 안에서만 해석한다. 상속·Mixin 은 02A 몫.
            if len(parts) == 1:
                sym = self.index.get((self.mf.module, f"{scope.cls_qual}.{parts[0]}"))
                if sym is not None:
                    return "calls", sym.id, "INFERRED", "call_self"
                return (
                    "calls", f"?:self:{scope.cls_qual}.{parts[0]}", "UNKNOWN",
                    "call_self_unresolved",
                )
            return "calls", f"?:self:{scope.cls_qual}.{dotted_tail}", "UNKNOWN", "call_self_chain"
        if self._is_shadowed(root):
            return "calls", f"?:local:{root}.{dotted_tail}", "UNKNOWN", "call_via_local"
        dotted = self.module_aliases.get(root)
        if dotted is not None:
            resolved = self._resolve_module_attr(dotted, parts)
            if resolved is not None:
                return resolved
            return "calls", f"?:attr:{dotted}.{dotted_tail}", "UNKNOWN", "call_attr_unresolved"
        bound = self.bindings.get(root)
        if bound is not None and bound.startswith("ext:"):
            return "calls", f"{bound}.{dotted_tail}", "STATIC_CONFIRMED", "call_ext_attr"
        if bound is not None and is_symbol_ref(bound) and len(parts) == 1:
            mod, qual, kind = parse_symbol_id(bound)
            if kind == "class":
                sym = self.index.get((mod, f"{qual}.{parts[0]}"))
                if sym is not None:
                    return "calls", sym.id, "STATIC_CONFIRMED", "call_class_attr"
                return "calls", f"?:attr:{mod}:{qual}.{parts[0]}", "UNKNOWN", "call_class_attr_miss"
        if bound is not None:
            # 모듈 상수 같은 비심볼 바인딩의 메서드 호출이다. 값의 런타임 타입을 정적
            # 심볼로 꾸며내지 않고, 해석된 바인딩 좌표만 보존해 후속 데이터플로에 넘긴다.
            return (
                "calls",
                f"?:attr:{bound.removeprefix('attr:')}.{dotted_tail}",
                "UNKNOWN",
                "call_attr_unresolved",
            )
        return "calls", f"?:attr:{root}.{dotted_tail}", "UNKNOWN", "call_attr_unresolved"

    def _resolve_module_attr(self, dotted: str, parts: "list[str]") -> "tuple[str, str, str, str] | None":
        if len(parts) == 1 and dotted in self.modules:
            targets = self.runtime_exports.get((dotted, parts[0]), frozenset())
            target = next(iter(targets)) if len(targets) == 1 else None
            if target is not None and is_symbol_ref(target):
                target_module, _target_qual, target_kind = parse_symbol_id(target)
                if target_module == dotted and target_kind != "module":
                    return self._rel_for(target), target, "STATIC_CONFIRMED", "call_module_attr"
            sub = f"{dotted}.{parts[0]}"
            if target is not None and target == symbol_id(sub, "", "module"):
                return None  # 모듈 자체 호출 형태 — 미해결로 남긴다
            return "calls", f"?:name:{dotted}.{parts[0]}", "UNKNOWN", "call_module_attr_miss"
        if dotted not in self.modules:
            return "calls", f"ext:{dotted}.{'.'.join(parts)}", "STATIC_CONFIRMED", "call_ext_attr"
        return None

    def _rel_for(self, dst: str) -> str:
        if is_symbol_ref(dst) and parse_symbol_id(dst)[2] == "class":
            return "constructs"
        return "calls"

    # -- getattr 계열·속성 쓰기 -------------------------------------------------

    def _handle_getattr_family(self, node: ast.Call, name: str) -> None:
        attr = node.args[1] if len(node.args) >= 2 else None
        if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
            owner = self._attr_owner(node.args[0])
            rel = "writes_attribute" if name in ("setattr", "delattr") else "reads_attribute"
            self._emit(
                rel,
                f"attr:{owner}.{attr.value}",
                "STATIC_CONFIRMED",
                node,
                f"{name}_literal",
                call_site_anchor(node),
            )
            return
        structured = self._structured_self_dispatch(node, name)
        if structured is not None:
            dst, rule = structured
            self._emit(
                "dynamic_site", dst, "DECLARED_DYNAMIC", node, rule, call_site_anchor(node)
            )
            return
        self._emit(
            "dynamic_site", f"?:builtin:{name}", "DECLARED_DYNAMIC", node,
            f"{name}_dynamic", call_site_anchor(node),
        )

    def _structured_self_dispatch(self, node: ast.Call, name: str) -> "tuple[str, str] | None":
        """자기 클래스를 향한 구조적 동적 디스패치 — dst 에 좌표를 실어 02A 복원 패스가
        재파싱 없이 확장할 수 있게 한다.

        - ``getattr(self, f"<접두>{…}")`` → ``?:prefix:{클래스}.{접두}``
        - ``getattr(self, self.X[k])``(X 가 클래스 소유 str→str 표) → ``?:table:{클래스}.X``
        """
        scope = self.fn_stack[-1] if self.fn_stack else None
        if (
            name != "getattr"
            or scope is None
            or not scope.cls_qual
            or len(node.args) < 2
            or not isinstance(node.args[0], ast.Name)
            or node.args[0].id != scope.first_param
        ):
            return None
        attr = node.args[1]
        if (
            isinstance(attr, ast.JoinedStr)
            and len(attr.values) == 2
            and isinstance(attr.values[0], ast.Constant)
            and isinstance(attr.values[0].value, str)
            and attr.values[0].value
            and isinstance(attr.values[1], ast.FormattedValue)
            and attr.values[1].conversion == -1
            and attr.values[1].format_spec is None
        ):
            return (
                f"?:prefix:{self.mf.module}:{scope.cls_qual}.{attr.values[0].value}",
                "getattr_fstring_self",
            )
        if (
            isinstance(attr, ast.Subscript)
            and isinstance(attr.value, ast.Attribute)
            and isinstance(attr.value.value, ast.Name)
            and attr.value.value.id == scope.first_param
        ):
            return (
                f"?:table:{self.mf.module}:{scope.cls_qual}.{attr.value.attr}",
                "getattr_table_self",
            )
        return None

    def _handle_assign(self, node: "ast.Assign | ast.AugAssign | ast.AnnAssign | ast.NamedExpr") -> None:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        else:
            targets = [node.target]
        flat: list[ast.expr] = []
        while targets:
            t = targets.pop()
            if isinstance(t, (ast.Tuple, ast.List)):
                targets.extend(t.elts)
            elif isinstance(t, ast.Starred):
                targets.append(t.value)
            else:
                flat.append(t)
        scope = self.fn_stack[-1] if self.fn_stack else None
        for t in flat:
            if isinstance(t, ast.Attribute):
                self._emit(
                    "writes_attribute", f"attr:{self._attr_owner(t.value)}.{t.attr}",
                    "STATIC_CONFIRMED", node, "attr_assign",
                )
            elif (
                isinstance(t, ast.Name)
                and scope is not None
                and t.id in scope.global_decls
            ):
                self._emit(
                    "writes_attribute", f"attr:{self.mf.module}:{t.id}",
                    "STATIC_CONFIRMED", node, "global_rebind",
                )

    def _attr_owner(self, node: ast.expr) -> str:
        scope = self.fn_stack[-1] if self.fn_stack else None
        if (
            isinstance(node, ast.Name)
            and scope is not None
            and scope.cls_qual
            and node.id == scope.first_param
        ):
            return f"{self.mf.module}:{scope.cls_qual}"
        try:
            text = ast.unparse(node)
        except Exception:  # noqa: BLE001 — 진단 좌표 생성 실패는 형태 이름으로 대체한다
            text = type(node).__name__
        return f"?:{text[:60]}"


def _assigned_names(body: "list[ast.stmt]") -> set[str]:
    """함수 지역 바인딩 이름 — 중첩 def/class/lambda 안은 그 스코프의 것이므로 내려가지 않는다."""
    names: set[str] = set()

    def visit(stmts: "list[ast.stmt]") -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
                continue
            for node in ast.walk(stmt):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        names.update(_target_names(t))
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    names.update(_target_names(node.target))
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        if item.optional_vars is not None:
                            names.update(_target_names(item.optional_vars))
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    names.add(node.name)
                elif isinstance(node, ast.NamedExpr):
                    names.update(_target_names(node.target))
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        if alias.name != "*":
                            names.add(alias.asname or alias.name.split(".", 1)[0])

    visit(body)
    return names


def _target_names(target: ast.expr) -> set[str]:
    out: set[str] = set()
    stack = [target]
    while stack:
        t = stack.pop()
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            stack.extend(t.elts)
        elif isinstance(t, ast.Starred):
            stack.append(t.value)
    return out


def _module_bound_names(tree: ast.Module) -> frozenset[str]:
    """module 초기화 중 한 번이라도 묶이는 이름 — builtin special-case의 보수적 veto."""
    names = set(_module_level_names(tree))

    def visit(body: "list[ast.stmt]") -> None:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
                continue
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name.split(".", 1)[0])
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    names.update(_target_names(target))
            for block in _stmt_blocks(stmt):
                visit(block)

    visit(tree.body)
    return frozenset(names)


def call_site_anchor(node: ast.Call) -> str:
    """같은 줄의 호출도 구분하는 안정 좌표 + 짧은 원문.

    ``Evidence`` v1 은 별도 column 필드가 없으므로 호출 노드의 시작/끝 열을 anchor 에
    싣는다. 전수성 오러클도 이 함수를 그대로 써서 ``f(); g()`` 중 하나만 수집된 거짓
    초록을 막는다.
    """
    try:
        text = ast.unparse(node).replace("\r", " ").replace("\n", " ")[:120]
    except Exception:  # noqa: BLE001 — 앵커는 진단 보조라 형태 이름으로 대체한다
        return type(node).__name__
    start = getattr(node, "col_offset", -1)
    end = getattr(node, "end_col_offset", -1)
    return f"c{start}-{end}:{text}"


def syntax_site_anchor(node: ast.AST) -> str:
    """Call이 아닌 정의 시점 표현식도 같은 줄에서 구분하는 안정 anchor."""
    try:
        text = ast.unparse(node).replace("\r", " ").replace("\n", " ")[:120]
    except Exception:  # noqa: BLE001 — 앵커는 진단 보조라 형태 이름으로 대체한다
        text = type(node).__name__
    start = getattr(node, "col_offset", -1)
    end = getattr(node, "end_col_offset", -1)
    return f"c{start}-{end}:{text}"
