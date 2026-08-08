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
from .schema import Evidence, Fact, FactGraphError, Provenance, Symbol, symbol_id

COLLECTOR = "factgraph.collect"

_GETATTR_FAMILY = {"getattr", "hasattr", "delattr", "setattr"}
_DYNAMIC_BUILTINS = {"__import__": "dynamic_import", "exec": "dynamic_exec", "eval": "dynamic_exec"}
_BUILTIN_NAMES = frozenset(dir(builtins))


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
    repo_root: Path, closure: "Closure | None" = None, symbols: "tuple[Symbol, ...] | None" = None
) -> tuple[Fact, ...]:
    repo_root = Path(repo_root)
    closure = closure or production_closure(repo_root)
    symbols = symbols if symbols is not None else collect_symbols(repo_root, closure)
    index = {(s.module, s.qualname): s for s in symbols}
    modules_by_name = {mf.module: mf for mf in closure.modules}
    facts: list[Fact] = []
    for mf in closure.modules:
        walker = _FactsWalker(mf, _parse(repo_root, mf), index, modules_by_name)
        facts.extend(walker.run())
    return tuple(sorted(set(facts), key=Fact.sort_key))


def _parse(repo_root: Path, mf: ModuleFile) -> ast.Module:
    path = repo_root / mf.path
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=mf.path)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        # 읽기·파싱 실패는 「사실 없음」이 아니라 구조 오류다 — 조용한 skip 금지.
        raise FactGraphError(f"모듈을 파싱할 수 없다: {mf.path} ({exc})") from exc


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
    ) -> None:
        self.mf = mf
        self.tree = tree
        self.index = index
        self.modules = modules_by_name
        self.module_sid = symbol_id(mf.module, "", "module")
        self.facts: list[Fact] = []
        # 모듈 수준 바인딩: 이름 → dst 문자열(symbol ID 또는 ext:)
        self.bindings: dict[str, str] = {
            s.qualname: s.id
            for s in index.values()
            if s.module == mf.module and s.qualname and "." not in s.qualname
        }
        # import a.b [as c] 로 묶인 모듈 별칭: 이름 → 점 경로
        self.module_aliases: dict[str, str] = {}
        self.fn_stack: list[_FnScope] = []
        self.class_stack: list[str] = []  # class qualname
        self.qual_prefix: list[str] = []
        self.type_checking_depth = 0

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

    def _emit(self, rel: str, dst: str, grade: str, node: ast.AST, rule: str, anchor: str = "") -> None:
        self.facts.append(
            Fact(
                src=self._src(),
                rel=rel,
                dst=dst,
                grade=grade,
                evidence=Evidence(self.mf.path, getattr(node, "lineno", 0), anchor),
                provenance=Provenance(COLLECTOR, rule),
            )
        )

    # -- 구조 재귀 -------------------------------------------------------------

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
        elif isinstance(node, ast.If) and _is_type_checking(node.test):
            self.type_checking_depth += 1
            for child in node.body:
                self._walk(child)
            self.type_checking_depth -= 1
            for child in node.orelse:
                self._walk(child)
        elif isinstance(node, ast.Call):
            self._handle_call(node)
            for child in ast.iter_child_nodes(node):
                self._walk(child)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            self._handle_assign(node)
            for child in ast.iter_child_nodes(node):
                self._walk(child)
        else:
            for child in ast.iter_child_nodes(node):
                self._walk(child)

    def _walk_function(self, node: "ast.FunctionDef | ast.AsyncFunctionDef") -> None:
        # 데코레이터·기본값은 바깥 문맥에서 평가된다.
        for dec in node.decorator_list:
            self._walk(dec)
        for default in [*node.args.defaults, *filter(None, node.args.kw_defaults)]:
            self._walk(default)
        qualname = ".".join([*self.qual_prefix, node.name])
        sym = self.index.get((self.mf.module, qualname))
        sid = sym.id if sym is not None else symbol_id(self.mf.module, qualname, "function")
        args = node.args
        params = [
            a.arg
            for a in [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
            if a is not None
        ]
        scope = _FnScope(
            symbol_sid=sid,
            first_param=params[0] if params else "",
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
        for stmt in node.body:
            self._walk(stmt)
        self.bindings = bindings_before
        self.module_aliases = aliases_before
        self.class_stack = in_class
        self.qual_prefix = self.qual_prefix[:-2]
        self.fn_stack.pop()

    def _walk_class(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self._walk(dec)
        for base in [*node.bases, *node.keywords]:
            self._walk(base)
        qualname = ".".join([*self.qual_prefix, node.name])
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

    # -- import ---------------------------------------------------------------

    def _import_rule(self, base: str) -> str:
        return f"import_{base}" if self.type_checking_depth == 0 else f"import_{base}_type_checking"

    def _handle_import(self, node: ast.Import) -> None:
        for alias in node.names:
            dotted = alias.name
            self._emit(
                "imports_module", self._module_ref(dotted), "STATIC_CONFIRMED", node,
                self._import_rule("plain"),
            )
            bound = alias.asname or dotted.split(".", 1)[0]
            self.module_aliases[bound] = dotted if alias.asname else dotted.split(".", 1)[0]

    def _handle_import_from(self, node: ast.ImportFrom) -> None:
        base = self._from_base(node)
        for alias in node.names:
            if alias.name == "*":
                self._emit(
                    "dynamic_site", f"?:star:{base}", "DECLARED_DYNAMIC", node, "import_star",
                )
                continue
            full = f"{base}.{alias.name}" if base else alias.name
            bound = alias.asname or alias.name
            if full in self.modules:
                self._emit(
                    "imports_module", self._module_ref(full), "STATIC_CONFIRMED", node,
                    self._import_rule("from"),
                )
                self.module_aliases[bound] = full
                continue
            if base in self.modules:
                sym = self.index.get((base, alias.name))
                if sym is not None:
                    self.bindings[bound] = sym.id
                    self._emit(
                        "imports_symbol", sym.id, "STATIC_CONFIRMED", node,
                        self._import_rule("from"),
                    )
                else:
                    # 폐포 모듈에서 없는 이름을 가져온다 — 재수출/동적 이름일 수 있다.
                    # 미해결 dst 는 등급도 미해결이다(해석 실패를 확정 증거로 적지 않는다).
                    self._emit(
                        "imports_symbol", f"?:name:{full}", "UNKNOWN", node,
                        self._import_rule("from"),
                    )
                continue
            self._emit(
                "imports_symbol", f"ext:{full}", "STATIC_CONFIRMED", node, self._import_rule("from"),
            )
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
        if isinstance(func, ast.Name) and not self._is_shadowed(func.id):
            if func.id in _GETATTR_FAMILY:
                self._handle_getattr_family(node, func.id)
                return
            if func.id in _DYNAMIC_BUILTINS:
                self._emit(
                    "dynamic_site", f"?:builtin:{func.id}", "DECLARED_DYNAMIC", node,
                    _DYNAMIC_BUILTINS[func.id], _anchor(node),
                )
                return
        if isinstance(func, ast.Name):
            rel, dst, grade, rule = self._resolve_name_call(func.id)
        elif isinstance(func, ast.Attribute):
            rel, dst, grade, rule = self._resolve_attr_call(func)
        else:
            self._emit(
                "dynamic_site", f"?:expr:{type(func).__name__}", "UNKNOWN", node,
                f"call_shape:{type(func).__name__}", _anchor(node),
            )
            return
        self._emit(rel, dst, grade, node, rule)

    def _is_shadowed(self, name: str) -> bool:
        return any(
            name in scope.local_names and name not in scope.global_decls
            for scope in self.fn_stack
        )

    def _resolve_name_call(self, name: str) -> tuple[str, str, str, str]:
        if self._is_shadowed(name):
            return "calls", f"?:local:{name}", "UNKNOWN", "call_local_binding"
        dst = self.bindings.get(name)
        if dst is not None:
            return self._rel_for(dst), dst, "STATIC_CONFIRMED", "call_name"
        dotted = self.module_aliases.get(name)
        if dotted is not None:
            return "calls", self._module_ref(dotted), "INFERRED", "call_module_alias"
        if name in _BUILTIN_NAMES:
            return "calls", f"ext:builtins.{name}", "STATIC_CONFIRMED", "call_builtin"
        return "calls", f"?:name:{name}", "UNKNOWN", "call_name_unresolved"

    def _resolve_attr_call(self, func: ast.Attribute) -> tuple[str, str, str, str]:
        parts: list[str] = []
        base: ast.expr = func
        while isinstance(base, ast.Attribute):
            parts.insert(0, base.attr)
            base = base.value
        if not isinstance(base, ast.Name):
            return (
                "calls", f"?:expr:{type(base).__name__}", "UNKNOWN",
                f"call_shape:{type(base).__name__}",
            )
        root = base.id
        dotted_tail = ".".join(parts)
        scope = self.fn_stack[-1] if self.fn_stack else None
        if scope is not None and scope.cls_qual and root == scope.first_param:
            # 메서드 안 self/cls 호출 — 자기 클래스 안에서만 해석한다. 상속·Mixin 은 02A 몫.
            if len(parts) == 1:
                sym = self.index.get((self.mf.module, f"{scope.cls_qual}.{parts[0]}"))
                if sym is not None:
                    return "calls", sym.id, "STATIC_CONFIRMED", "call_self"
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
        if bound is not None and len(parts) == 1:
            from .schema import parse_symbol_id

            mod, qual, kind = parse_symbol_id(bound)
            if kind == "class":
                sym = self.index.get((mod, f"{qual}.{parts[0]}"))
                if sym is not None:
                    return "calls", sym.id, "STATIC_CONFIRMED", "call_class_attr"
                return "calls", f"?:attr:{mod}:{qual}.{parts[0]}", "UNKNOWN", "call_class_attr_miss"
        return "calls", f"?:attr:{root}.{dotted_tail}", "UNKNOWN", "call_attr_unresolved"

    def _resolve_module_attr(self, dotted: str, parts: "list[str]") -> "tuple[str, str, str, str] | None":
        if len(parts) == 1 and dotted in self.modules:
            sym = self.index.get((dotted, parts[0]))
            if sym is not None:
                return self._rel_for(sym.id), sym.id, "STATIC_CONFIRMED", "call_module_attr"
            sub = f"{dotted}.{parts[0]}"
            if sub in self.modules:
                return None  # 모듈 자체 호출 형태 — 미해결로 남긴다
            return "calls", f"?:name:{dotted}.{parts[0]}", "UNKNOWN", "call_module_attr_miss"
        if dotted not in self.modules:
            return "calls", f"ext:{dotted}.{'.'.join(parts)}", "STATIC_CONFIRMED", "call_ext_attr"
        return None

    def _rel_for(self, dst: str) -> str:
        from .schema import is_symbol_ref, parse_symbol_id

        if is_symbol_ref(dst) and parse_symbol_id(dst)[2] == "class":
            return "constructs"
        return "calls"

    # -- getattr 계열·속성 쓰기 -------------------------------------------------

    def _handle_getattr_family(self, node: ast.Call, name: str) -> None:
        attr = node.args[1] if len(node.args) >= 2 else None
        if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
            owner = self._attr_owner(node.args[0])
            rel = "writes_attribute" if name in ("setattr", "delattr") else "reads_attribute"
            self._emit(rel, f"attr:{owner}.{attr.value}", "STATIC_CONFIRMED", node, f"{name}_literal")
            return
        self._emit(
            "dynamic_site", f"?:builtin:{name}", "DECLARED_DYNAMIC", node,
            f"{name}_dynamic", _anchor(node),
        )

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


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _anchor(node: ast.AST) -> str:
    try:
        return ast.unparse(node)[:120]
    except Exception:  # noqa: BLE001 — 앵커는 진단 보조라 형태 이름으로 대체한다
        return type(node).__name__
