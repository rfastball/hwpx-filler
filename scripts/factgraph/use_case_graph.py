"""P1-02E use-case 축 — GUI·CLI logical entry 전수·경로·분류·test responsibility 원장.

#513 call-axis(``static_graph``)의 **read-only consumer** 다: 기반·파생 사실과 digest 를
입력으로 받고 중앙 relation 을 추가하지 않는다(``schema.py`` 무변경 — #517 설계 패킷).
경로 복원에서 이 축이 더 놓는 시임 홉(아래 3규칙)은 shard 사실이 아니라 **원장 파생**이며,
INFERENCE 로 rule 과 함께 기록된다 — 임의 callee 추측 금지 불변식은 여기서도 유효하다.

구조 유도 원칙(제품 모듈 이름 하드코딩 0):

- CLI/GUI entry 모듈은 ``pyproject.toml`` 의 ``[project.scripts]``/``[project.gui-scripts]``
  에서 유도한다. 수송 클래스는 GUI entry 함수가 construct 하는 entry 모듈 내 유일 클래스로,
  컨트롤러는 02A prefix dispatch site 의 소유 클래스로 유도한다.
- 라우터(전 컨트롤러가 공유하는 수송 공개 메서드)는 업무 entry 가 아니라 수송로다. 액션
  라우터는 prefix site 를 소유한 메서드로 판별하고 그 확장(액션 전수)이 entry 가 된다.
  나머지 라우터는 화면별 entry(화면 부팅)로 확장된다.
- 「같은 이름 = 같은 use case」를 추측하지 않는다: COMMON 판정은 이름이 아니라 **교차-host
  fan (1,1) 공유 core 동사**(양쪽 host 에서 정확히 entry 하나씩만 도달하는 동사)로 선다.
  반대로 「다른 wrapper = 별개 업무」도 추측하지 않는다 — 같은 어간의 교차-host entry 가
  core 구현을 하나도 공유하지 않으면 DUPLICATE 후보로 시끄럽게 센다.

test responsibility 축은 ``tests/`` 를 **사실의 원천**으로 읽는다(계측 폐포 확장이 아니다 —
production 폐포·02A digest 는 건드리지 않는다). 테스트 존재를 behavior oracle 존재와
동일시하지 않는다: 연결의 근거(basis)를 행마다 남기고, entry 수준 근거(FACT 에 가까운
직접 겨눔)와 core 수준 근거(간접·INFERENCE)를 구분하며, 근거가 없는 비어 있지 않은 경로는
characterization 필요 항목으로 loud 등록한다.

관측자 순환의 명시 규칙: 이 축의 게이트 테스트 파일 자체도 ``tests/`` 스캔 분모에 **정직하게
포함**된다(제외 규칙 없음). 그 행은 제품 참조 0 으로 수렴하는 고정점이라 재생성이 결정론으로
닫힌다 — 게이트가 자기 행의 존재와 제품 참조 0 을 단언해 이 규칙 자체를 지킨다.
"""

from __future__ import annotations

import ast
import json
import subprocess
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .closure import Closure
from .schema import FactGraphError, is_symbol_ref, parse_symbol_id
from .static_graph import StaticGraphResult, build

COLLECTOR = "factgraph.use_case_graph"

BASELINE_SHA = "247333e0ae69776ebf9ed9f2e596abf427c63b56"

LEDGER_REL_PATH = "docs/factgraph/use_case_graph_02e.toml"
REGEN_COMMAND = "uv run python scripts/gen_use_case_graph_02e.py"

#: 시임 홉 rule 어휘 — 여기 없는 rule 이 경로에 나타나면 render 가 죽는다(02A followup 규약).
SEAM_RULES: tuple[str, ...] = ("attr_delegate", "local_construct", "transport_delegate")

#: oracle 연결 근거 어휘. entry 수준(직접 겨눔)과 core 수준(간접)을 구분한다.
ENTRY_BASES: tuple[str, ...] = (
    "argv-literal",  # CLI 하위명령 리터럴 + entry 모듈 참조
    "trunk-flag",  # CLI 기본 경로의 필수 플래그 리터럴 + entry 모듈 참조
    "flag-literal",  # CLI 플래그 경로의 플래그 리터럴 + entry 모듈 참조
    "dispatch-literal",  # 액션 라우터 호출의 문자열 인자에 액션 이름
    "handler-ref",  # 접두 핸들러 이름을 직접 호출/참조
    "direct-call",  # 직접 메서드 이름 호출 + GUI entry 패키지 참조
    "boot-call",  # 화면 부팅 라우터 호출 + 해당 컨트롤러 모듈 참조
)
CORE_BASES: tuple[str, ...] = (
    "core-verb-import",  # entry 경로의 앵커/core 동사를 이름으로 직접 import
)

_ORACLE_STATUS = ("ENTRY", "CORE", "NONE")
_TypeSummary = tuple[frozenset[str], ...]


@dataclass(frozen=True)
class UseCaseEntry:
    entry_id: str
    host: str  # "cli" | "gui"
    kind: str  # cli_subcommand | cli_default | cli_flag | gui_action | gui_direct | gui_screen_boot
    roots: tuple[str, ...]


@dataclass(frozen=True)
class EntryRoute:
    entry: UseCaseEntry
    core_verbs: tuple[str, ...]
    seam_rules: tuple[str, ...]  # 이 경로 복원에 실제 기여한 rule 전수
    unresolved_out: int  # 경로 위 심볼에서 나가는 미해결 edge 수(정직한 사각 지표)


@dataclass(frozen=True)
class TestFileFacts:
    path: str  # 저장소 상대 posix 경로
    axes: tuple[str, ...]  # 자원 축 표식(비면 deterministic)
    product_modules: tuple[str, ...]
    imported_symbols: tuple[str, ...]  # 폐포 모듈에서 이름으로 import 한 심볼("모듈:이름")
    attr_calls: frozenset[str] = field(repr=False)
    str_literals: frozenset[str] = field(repr=False)
    #: 호출 인자로 등장한 문자열 전수 — **호출 형태 불문**. 액션 dispatch 를 지역 헬퍼로
    #: 감싼 테스트가 실재해서(실측: ``_send(ctrl, "액션", …)``), 특정 메서드 이름의 호출만
    #: 보면 헬퍼 경유 소비에 눈이 먼다(검증 원장 G2 의 같은 결함류 — 술어는 「무엇을
    #: 부르는가」가 아니라 「무엇에 닿는가」를 본다).
    call_arg_strings: frozenset[str] = field(repr=False)
    #: 수송 인스턴스에 결속된 공개 메서드 호출. 동명 컨트롤러 메서드는 제외한다.
    direct_calls: frozenset[str] = field(default_factory=frozenset, repr=False)
    #: 수송/컨트롤러 호출에서 함께 증명된 ``(screen, action)`` 쌍.
    dispatch_pairs: frozenset[tuple[str, str]] = field(default_factory=frozenset, repr=False)
    #: 화면 컨트롤러에 결속된 ``_do_<action>`` 직접 참조.
    handler_pairs: frozenset[tuple[str, str]] = field(default_factory=frozenset, repr=False)


@dataclass(frozen=True)
class OracleLink:
    test_path: str
    basis: str

    def __post_init__(self) -> None:
        if self.basis not in ENTRY_BASES + CORE_BASES:
            raise FactGraphError(f"미등록 oracle basis: {self.basis!r}")


@dataclass
class UseCaseResult:
    graph: StaticGraphResult
    entries: tuple[UseCaseEntry, ...]
    routes: "dict[str, EntryRoute]"  # entry_id → route
    classification: "dict[str, str]"  # entry_id → COMMON | HOST_ONLY | DUPLICATE
    counterpart: "dict[str, str]"  # COMMON/DUPLICATE entry → 상대 entry_id
    anchor_verbs: "dict[str, tuple[str, str]]"  # 동사 → (cli entry, gui entry)
    surface: "dict[str, object]"
    test_files: tuple[TestFileFacts, ...]
    oracles: "dict[str, tuple[OracleLink, ...]]"  # entry_id → 연결(정렬)
    oracle_status: "dict[str, str]"  # entry_id → ENTRY | CORE | NONE
    gaps: tuple[tuple[str, str], ...]  # (entry_id, 사유)


# ─────────────────────────────── 이름 해석 보조 ───────────────────────────────


def _name_tables(
    result: StaticGraphResult,
) -> "tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]":
    """모듈별 Name → 폐포 클래스/함수 심볼 표 — 정의와 import(결속 이름) 양쪽에서."""
    class_table: dict[str, dict[str, str]] = {}
    func_table: dict[str, dict[str, str]] = {}
    for symbol in result.symbols:
        if "." in symbol.qualname:
            continue
        if symbol.kind == "class":
            class_table.setdefault(symbol.module, {})[symbol.qualname] = symbol.id
        elif symbol.kind == "function":
            func_table.setdefault(symbol.module, {})[symbol.qualname] = symbol.id
    for fact in result.facts:
        if fact.rel != "imports_symbol" or not is_symbol_ref(fact.dst):
            continue
        bound = fact.evidence.anchor.partition("<-")[0].partition("@c")[0]
        if not bound:
            continue
        src_module = parse_symbol_id(fact.src)[0]
        if fact.dst.endswith("#class"):
            class_table.setdefault(src_module, {})[bound] = fact.dst
        elif fact.dst.endswith("#function"):
            func_table.setdefault(src_module, {})[bound] = fact.dst
    return class_table, func_table


def _methods_by_class(result: StaticGraphResult) -> "dict[str, dict[str, str]]":
    out: dict[str, dict[str, str]] = {}
    for symbol in result.symbols:
        if symbol.kind == "method" and "." in symbol.qualname:
            cls_qual, method = symbol.qualname.rsplit(".", 1)
            out.setdefault(f"{symbol.module}:{cls_qual}#class", {})[method] = symbol.id
    return out


class _Resolver:
    """AST·사실 결합 해석기 — entry 유도와 시임 홉이 공유하는 문맥."""

    def __init__(self, repo_root: Path, result: StaticGraphResult) -> None:
        self.repo_root = Path(repo_root)
        self.result = result
        self.path_of_module = {mf.module: mf.path for mf in result.closure.modules}
        self.symbol_ids = {s.id for s in result.symbols}
        self.class_table, self.func_table = _name_tables(result)
        self.methods = _methods_by_class(result)
        self.adjacency: dict[str, set[str]] = {}
        self.unresolved_out: dict[str, int] = {}
        for fact in result.facts:
            if fact.rel in ("calls", "constructs"):
                if is_symbol_ref(fact.dst):
                    self.adjacency.setdefault(fact.src, set()).add(fact.dst)
                elif fact.dst.startswith("?:"):
                    self.unresolved_out[fact.src] = self.unresolved_out.get(fact.src, 0) + 1
        self._trees: dict[str, ast.Module] = {}
        self._attr_classes: "dict[str, dict[str, set[str]]] | None" = None
        self._seam_cache: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        self.transport_cls: "str | None" = None
        self.controller_classes: tuple[str, ...] = ()

    def tree(self, module: str) -> ast.Module:
        if module not in self._trees:
            path = self.repo_root / self.path_of_module[module]
            self._trees[module] = ast.parse(path.read_text(encoding="utf-8"))
        return self._trees[module]

    def mro_lookup(self, cls_sid: str, name: str) -> "str | None":
        for ancestor in self.result.mro_map.get(cls_sid, (cls_sid,)):
            if ancestor.endswith("#class") and name in self.methods.get(ancestor, {}):
                return self.methods[ancestor][name]
        return None

    def func_node(self, sid: str) -> "ast.FunctionDef | ast.AsyncFunctionDef | None":
        module, qualname, kind = parse_symbol_id(sid)
        if kind not in ("function", "method") or module not in self.path_of_module:
            return None
        node: ast.AST = self.tree(module)
        for part in qualname.split("."):
            found = None
            for child in ast.iter_child_nodes(node):
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and child.name == part
                ):
                    found = child
                    break
            if found is None:
                return None
            node = found
        return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None

    def local_class_bindings(
        self, node: ast.AST, module: str
    ) -> "dict[str, str]":
        """함수 본문의 ``x = C(...)`` 지역 결속(단순 Name 표적만 — 그 밖은 미해결 유지)."""
        table = self.class_table.get(module, {})
        out: dict[str, str] = {}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call):
                func = sub.value.func
                cname = func.id if isinstance(func, ast.Name) else None
                if cname and cname in table:
                    for target in sub.targets:
                        if isinstance(target, ast.Name):
                            out[target.id] = table[cname]
        return out

    def attr_classes(self) -> "dict[str, dict[str, set[str]]]":
        """클래스별 ``self.<a> = C(...)`` 인스턴스 속성 → 폐포 클래스 후보(전 폐포 1회 계산)."""
        if self._attr_classes is not None:
            return self._attr_classes
        out: dict[str, dict[str, set[str]]] = {}
        for mf in self.result.closure.modules:
            table = self.class_table.get(mf.module, {})
            if not table:
                continue
            for node in ast.walk(self.tree(mf.module)):
                if not isinstance(node, ast.ClassDef):
                    continue
                cls_sid = f"{mf.module}:{node.name}#class"
                if cls_sid not in self.symbol_ids:
                    continue
                for sub in ast.walk(node):
                    if not (isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call)):
                        continue
                    func = sub.value.func
                    cname = func.id if isinstance(func, ast.Name) else None
                    if not cname or cname not in table:
                        continue
                    for target in sub.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            out.setdefault(cls_sid, {}).setdefault(target.attr, set()).add(
                                table[cname]
                            )
        self._attr_classes = out
        return out

    def seam_hops(self, sid: str) -> "tuple[frozenset[str], frozenset[str]]":
        """방문 심볼 본문에서 3규칙으로 복원되는 홉과 실제 기여 rule — (대상, rule) 캐시."""
        cached = self._seam_cache.get(sid)
        if cached is not None:
            return cached
        targets: set[str] = set()
        rules: set[str] = set()
        node = self.func_node(sid)
        if node is None:
            empty = (frozenset(), frozenset())
            self._seam_cache[sid] = empty
            return empty
        module, qualname, kind = parse_symbol_id(sid)
        owner_cls = (
            f"{module}:{qualname.rsplit('.', 1)[0]}#class"
            if kind == "method" and "." in qualname
            else None
        )
        local_classes = self.local_class_bindings(node, module)
        attr_map = self.attr_classes().get(owner_cls, {}) if owner_cls else {}
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)):
                continue
            method = sub.func.attr
            base = sub.func.value
            if (
                owner_cls
                and isinstance(base, ast.Attribute)
                and isinstance(base.value, ast.Name)
                and base.value.id == "self"
            ):
                for candidate_cls in attr_map.get(base.attr, ()):
                    hit = self.mro_lookup(candidate_cls, method)
                    if hit:
                        targets.add(hit)
                        rules.add("attr_delegate")
            elif isinstance(base, ast.Name) and base.id in local_classes:
                hit = self.mro_lookup(local_classes[base.id], method)
                if hit:
                    targets.add(hit)
                    rules.add("local_construct")
            elif (
                owner_cls is not None
                and owner_cls == self.transport_cls
                and isinstance(base, ast.Call)
                and isinstance(base.func, ast.Attribute)
                and isinstance(base.func.value, ast.Name)
                and base.func.value.id == "self"
            ):
                for controller in self.controller_classes:
                    hit = self.mro_lookup(controller, method)
                    if hit:
                        targets.add(hit)
                        rules.add("transport_delegate")
        for rule in rules:
            if rule not in SEAM_RULES:
                raise FactGraphError(f"미등록 시임 rule: {rule!r}")
        pair = (frozenset(targets), frozenset(rules))
        self._seam_cache[sid] = pair
        return pair


# ─────────────────────────────── entry 유도 ───────────────────────────────


def _project_entry_points(repo_root: Path) -> "tuple[list[str], list[str]]":
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        raise FactGraphError(f"pyproject.toml 이 없다: {pyproject}")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    console = [str(v) for v in project.get("scripts", {}).values()]
    gui = [str(v) for v in project.get("gui-scripts", {}).values()]
    if not console or not gui:
        raise FactGraphError(
            "pyproject 의 [project.scripts]/[project.gui-scripts] 가 비었다 — "
            "logical entry 분모를 유도할 수 없다"
        )
    return sorted(console), sorted(gui)


def _guard_literal(test: ast.expr) -> "str | None":
    """``<name>[0] == "리터럴"`` 형태의 라우팅 가드에서 리터럴을 되읽는다."""
    for sub in ast.walk(test):
        if (
            isinstance(sub, ast.Compare)
            and len(sub.ops) == 1
            and isinstance(sub.ops[0], ast.Eq)
            and isinstance(sub.left, ast.Subscript)
            and isinstance(sub.left.value, ast.Name)
            and isinstance(sub.left.slice, ast.Constant)
            and sub.left.slice.value == 0
            and isinstance(sub.comparators[0], ast.Constant)
            and isinstance(sub.comparators[0].value, str)
        ):
            return sub.comparators[0].value
    return None


def _branch_returns(body: "list[ast.stmt]") -> bool:
    return bool(body) and isinstance(body[-1], ast.Return)


def _parse_args_names(func: ast.AST) -> set[str]:
    """``<ns> = <x>.parse_args(...)`` 의 네임스페이스 결속 이름."""
    names: set[str] = set()
    for sub in ast.walk(func):
        if (
            isinstance(sub, ast.Assign)
            and isinstance(sub.value, ast.Call)
            and isinstance(sub.value.func, ast.Attribute)
            and sub.value.func.attr == "parse_args"
        ):
            for target in sub.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _flag_literal_of(trunk: ast.AST, attr: str) -> "str | None":
    """argparse dest ``attr`` 에 대응하는 ``add_argument`` 옵션 리터럴을 되읽는다."""
    for sub in ast.walk(trunk):
        if not (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "add_argument"
        ):
            continue
        for arg in sub.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                literal = arg.value
                if literal.lstrip("-").replace("-", "_") == attr:
                    return literal
    return None


def _required_trunk_flags(trunk: ast.AST) -> "tuple[str, ...]":
    out: list[str] = []
    for sub in ast.walk(trunk):
        if not (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "add_argument"
        ):
            continue
        required = any(
            kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in sub.keywords
        )
        if not required:
            continue
        for arg in sub.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(arg.value)
    return tuple(sorted(set(out)))


def _derive_cli_entries(
    resolver: _Resolver, console_entries: "list[str]"
) -> "tuple[list[UseCaseEntry], dict[str, object]]":
    entries: list[UseCaseEntry] = []
    meta: dict[str, object] = {}
    cli_modules: list[str] = []
    for spec in console_entries:
        module, _, _fn = spec.partition(":")
        if module not in resolver.path_of_module:
            raise FactGraphError(f"console entry 모듈이 폐포 밖이다: {spec!r}")
        cli_modules.append(module)
        tree = resolver.tree(module)
        func_table = resolver.func_table.get(module, {})

        # 라우팅 트렁크 = argv[0] 가드를 가장 많이 든 최상위 함수
        trunk: "ast.FunctionDef | None" = None
        trunk_guards = 0
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            guards = sum(
                1
                for sub in ast.walk(node)
                if isinstance(sub, ast.If) and _guard_literal(sub.test) is not None
            )
            if guards > trunk_guards:
                trunk, trunk_guards = node, guards
        if trunk is None:
            raise FactGraphError(f"CLI 라우팅 가드를 찾지 못했다: {module}")
        trunk_sid = f"{module}:{trunk.name}#function"

        guarded: set[str] = set()
        local_classes = resolver.local_class_bindings(trunk, module)
        for stmt in trunk.body:
            if not (isinstance(stmt, ast.If) and _guard_literal(stmt.test) is not None):
                continue
            literal = _guard_literal(stmt.test)
            roots: set[str] = set()
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    sid = func_table.get(sub.func.id)
                    if sid:
                        roots.add(sid)
                        guarded.add(sid)
            entries.append(
                UseCaseEntry(f"cli:{literal}", "cli", "cli_subcommand", tuple(sorted(roots)))
            )

        # 플래그 경로: 네임스페이스 속성 단독 가드 + 분기 말단 return
        namespaces = _parse_args_names(trunk)
        flag_attrs: list[str] = []
        for sub in ast.walk(trunk):
            if (
                isinstance(sub, ast.If)
                and isinstance(sub.test, ast.Attribute)
                and isinstance(sub.test.value, ast.Name)
                and sub.test.value.id in namespaces
                and _branch_returns(sub.body)
            ):
                flag_attrs.append(sub.test.attr)
        flag_literals: list[str] = []
        for attr in sorted(set(flag_attrs)):
            literal = _flag_literal_of(trunk, attr)
            if literal is None:
                raise FactGraphError(f"플래그 경로 {attr!r} 의 옵션 리터럴을 되읽지 못했다")
            flag_literals.append(literal)
            flag_if = next(
                sub
                for sub in ast.walk(trunk)
                if isinstance(sub, ast.If)
                and isinstance(sub.test, ast.Attribute)
                and sub.test.attr == attr
            )
            roots = set()
            for sub in ast.walk(flag_if):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    sid = func_table.get(sub.func.id)
                    if sid:
                        roots.add(sid)
                elif (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id in local_classes
                ):
                    hit = resolver.mro_lookup(local_classes[sub.func.value.id], sub.func.attr)
                    if hit:
                        roots.add(hit)
            entries.append(
                UseCaseEntry(f"cli:{literal}", "cli", "cli_flag", tuple(sorted(roots)))
            )

        # 기본 경로 = 트렁크의 직접 해석 callee − 가드 분기 root + 트렁크 시임 홉
        default_roots = {
            dst for dst in resolver.adjacency.get(trunk_sid, set()) if dst not in guarded
        }
        default_roots |= resolver.seam_hops(trunk_sid)[0]
        entries.append(
            UseCaseEntry("cli:default", "cli", "cli_default", tuple(sorted(default_roots)))
        )
        meta.setdefault("cli_trunks", []).append(trunk_sid)  # type: ignore[union-attr]
        meta.setdefault("cli_required_flags", []).extend(  # type: ignore[union-attr]
            _required_trunk_flags(trunk)
        )
        meta.setdefault("cli_flag_literals", []).extend(flag_literals)  # type: ignore[union-attr]
    meta["cli_modules"] = cli_modules
    return entries, meta


def _class_screen_names(resolver: _Resolver, class_sids: "tuple[str, ...]") -> "dict[str, str]":
    out: dict[str, str] = {}
    for cls_sid in class_sids:
        module, qualname, _ = parse_symbol_id(cls_sid)
        for node in ast.walk(resolver.tree(module)):
            if isinstance(node, ast.ClassDef) and node.name == qualname:
                for stmt in node.body:
                    if (
                        isinstance(stmt, ast.Assign)
                        and any(
                            isinstance(t, ast.Name) and t.id == "name" for t in stmt.targets
                        )
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)
                    ):
                        out[cls_sid] = stmt.value.value
        if cls_sid not in out:
            raise FactGraphError(f"컨트롤러의 화면 이름(name 상수)을 찾지 못했다: {cls_sid}")
    return out


def _derive_gui_entries(
    resolver: _Resolver, gui_entries: "list[str]"
) -> "tuple[list[UseCaseEntry], dict[str, object]]":
    result = resolver.result
    entries: list[UseCaseEntry] = []
    meta: dict[str, object] = {}
    prefix_sites = [site for site in result.dispatch_sites if site.kind == "prefix"]
    if not prefix_sites:
        raise FactGraphError("prefix dispatch site 가 없다 — GUI 액션 분모를 유도할 수 없다")
    controllers = tuple(sorted({f"{site.owner}#class" for site in prefix_sites}))

    gui_modules: list[str] = []
    transports: list[str] = []
    for spec in gui_entries:
        module, _, fn = spec.partition(":")
        if module not in resolver.path_of_module:
            raise FactGraphError(f"gui entry 모듈이 폐포 밖이다: {spec!r}")
        gui_modules.append(module)
        main_sid = f"{module}:{fn}#function"
        candidates = sorted(
            dst
            for dst in resolver.adjacency.get(main_sid, set())
            if dst.endswith("#class") and parse_symbol_id(dst)[0] == module
        )
        if len(candidates) != 1:
            raise FactGraphError(
                f"수송 클래스 후보가 유일하지 않다({spec!r}): {candidates}"
            )
        transports.append(candidates[0])
    if len(set(transports)) != 1:
        raise FactGraphError(f"gui entry 들의 수송 클래스가 갈린다: {sorted(set(transports))}")
    transport_cls = transports[0]
    resolver.transport_cls = transport_cls
    resolver.controller_classes = controllers

    # 컨트롤러 검증: 수송 클래스 메서드가 construct 하는 클래스 집합과 prefix 소유 집합 대조
    constructed: set[str] = set()
    for method_sid in resolver.methods.get(transport_cls, {}).values():
        constructed |= {
            dst for dst in resolver.adjacency.get(method_sid, set()) if dst.endswith("#class")
        }
    missing = [cls for cls in controllers if cls not in constructed]
    if missing:
        raise FactGraphError(
            f"prefix dispatch 소유 클래스가 수송 클래스의 구성 밖이다: {missing}"
        )

    screen_of = _class_screen_names(resolver, controllers)
    transport_methods = resolver.methods.get(transport_cls, {})
    public_methods = {
        name: sid for name, sid in transport_methods.items() if not name.startswith("_")
    }

    # 라우터 = 전 컨트롤러가 공유하는 수송 공개 메서드. 액션 라우터는 prefix site 소유 메서드.
    routers = {
        name
        for name in public_methods
        if all(resolver.mro_lookup(cls, name) is not None for cls in controllers)
    }
    action_router_methods = {site.src for site in prefix_sites}
    action_routers = {
        name
        for name in routers
        if any(
            resolver.mro_lookup(cls, name) in action_router_methods for cls in controllers
        )
    }
    boot_routers = sorted(routers - action_routers)

    seen_actions: dict[tuple[str, str], set[str]] = {}
    for site in prefix_sites:
        owner_sid = f"{site.owner}#class"
        screen = screen_of[owner_sid]
        for target in site.restored:
            method_name = parse_symbol_id(target)[1].rsplit(".", 1)[-1]
            action = method_name[len(site.key) :]
            seen_actions.setdefault((screen, action), set()).add(target)
    for (screen, action), roots in sorted(seen_actions.items()):
        entries.append(
            UseCaseEntry(
                f"gui:{screen}/{action}", "gui", "gui_action", tuple(sorted(roots))
            )
        )
    for name, sid in sorted(public_methods.items()):
        if name in routers:
            continue
        entries.append(UseCaseEntry(f"gui:direct/{name}", "gui", "gui_direct", (sid,)))
    for router in boot_routers:
        for cls in controllers:
            root = resolver.mro_lookup(cls, router)
            if root is None:  # 라우터 정의상 불가능하지만, 침묵 대신 시끄럽게
                raise FactGraphError(f"라우터 {router!r} 가 {cls} 에 없다")
            entries.append(
                UseCaseEntry(
                    f"gui:{screen_of[cls]}/{router}", "gui", "gui_screen_boot", (root,)
                )
            )

    meta["gui_modules"] = gui_modules
    meta["transport"] = transport_cls
    meta["controllers"] = list(controllers)
    meta["screens"] = sorted(screen_of.values())
    meta["routers"] = sorted(routers)
    meta["boot_routers"] = boot_routers
    return entries, meta


# ─────────────────────────────── 경로·분류 ───────────────────────────────


def _core_projection(meta: "dict[str, object]") -> "tuple[tuple[str, ...], tuple[str, ...]]":
    """core 동사 판별의 제외 집합 — (제외 모듈, 제외 패키지 접두)를 표면에서 유도한다."""
    excluded_modules = tuple(sorted(set(meta.get("cli_modules", []))))  # type: ignore[arg-type]
    prefixes: set[str] = set()
    for module in meta.get("gui_modules", []):  # type: ignore[union-attr]
        package = str(module).rsplit(".", 1)[0]
        prefixes.add(package + ".")
    return excluded_modules, tuple(sorted(prefixes))


def _route(
    resolver: _Resolver,
    entry: UseCaseEntry,
    excluded_modules: "tuple[str, ...]",
    excluded_prefixes: "tuple[str, ...]",
) -> EntryRoute:
    seen: set[str] = set()
    rules: set[str] = set()
    queue = deque(root for root in entry.roots if root in resolver.symbol_ids)
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        nexts = set(resolver.adjacency.get(current, set()))
        hop_targets, hop_rules = resolver.seam_hops(current)
        nexts |= hop_targets
        rules |= hop_rules
        module, qualname, kind = parse_symbol_id(current)
        if kind == "class":
            init = resolver.mro_lookup(current, "__init__")
            if init:
                nexts.add(init)
        for nxt in nexts:
            if nxt not in seen:
                queue.append(nxt)
    core: set[str] = set()
    unresolved = 0
    for sid in seen:
        unresolved += resolver.unresolved_out.get(sid, 0)
        module, _qual, kind = parse_symbol_id(sid)
        if kind not in ("function", "method"):
            continue
        if module in excluded_modules or module.startswith(excluded_prefixes):
            continue
        core.add(sid)
    return EntryRoute(entry, tuple(sorted(core)), tuple(sorted(rules)), unresolved)


def _guard_projection_not_degenerate(
    closure_modules: "tuple[str, ...]",
    excluded_modules: "tuple[str, ...]",
    excluded_prefixes: "tuple[str, ...]",
) -> None:
    """투영이 폐포를 통째로 삼키면 모든 경로가 조용히 비어 버린다 — 시끄럽게 거절한다.

    전제는 「GUI 표면은 전용 패키지에 산다」(실저장소 구조)다. entry 모듈이 최상위 패키지에
    직접 살면 그 패키지 접두가 폐포 전체를 덮는다 — 그때 0 개짜리 core 투영으로 초록을
    내는 대신 전제 위반을 좌표로 말한다.
    """
    survivors = [
        module
        for module in closure_modules
        if module not in excluded_modules and not module.startswith(excluded_prefixes)
    ]
    if not survivors:
        raise FactGraphError(
            "core 투영이 공집합이다 — GUI entry 패키지 접두가 폐포 전체를 덮는다: "
            f"제외 접두 {list(excluded_prefixes)}"
        )


def _stem(entry_id: str) -> str:
    tail = entry_id.rsplit("/", 1)[-1] if "/" in entry_id else entry_id.partition(":")[2]
    return tail.lstrip("-").replace("-", "_")


def _classify(
    routes: "dict[str, EntryRoute]",
) -> "tuple[dict[str, str], dict[str, str], dict[str, tuple[str, str]]]":
    hosts = {eid: route.entry.host for eid, route in routes.items()}
    cli_union: set[str] = set()
    gui_union: set[str] = set()
    for eid, route in routes.items():
        (cli_union if hosts[eid] == "cli" else gui_union).update(route.core_verbs)
    shared = cli_union & gui_union

    anchor_verbs: dict[str, tuple[str, str]] = {}
    for verb in sorted(shared):
        cli_holders = sorted(
            eid for eid, r in routes.items() if hosts[eid] == "cli" and verb in r.core_verbs
        )
        gui_holders = sorted(
            eid for eid, r in routes.items() if hosts[eid] == "gui" and verb in r.core_verbs
        )
        if len(cli_holders) == 1 and len(gui_holders) == 1:
            anchor_verbs[verb] = (cli_holders[0], gui_holders[0])

    classification: dict[str, str] = {}
    counterpart: dict[str, str] = {}
    for eid in routes:
        partners = {
            pair[1] if hosts[eid] == "cli" else pair[0]
            for verb, pair in anchor_verbs.items()
            if eid in pair
        }
        if len(partners) > 1:
            raise FactGraphError(f"COMMON 상대가 유일하지 않다: {eid} ↔ {sorted(partners)}")
        if partners:
            classification[eid] = "COMMON"
            counterpart[eid] = next(iter(partners))

    # DUPLICATE 후보: 같은 어간의 교차-host entry 가 비어 있지 않은 core 경로를 갖고도
    # 구현을 하나도 공유하지 않는 경우 — 이름 일치를 근거로 병합하지도 방치하지도 않는다.
    by_stem: dict[str, list[str]] = {}
    for eid in routes:
        by_stem.setdefault(_stem(eid), []).append(eid)
    duplicate_candidates: dict[str, set[str]] = {}
    for stem_ids in by_stem.values():
        for left in stem_ids:
            for right in stem_ids:
                if (
                    left < right
                    and hosts[left] != hosts[right]
                    and left not in classification
                    and right not in classification
                    and routes[left].core_verbs
                    and routes[right].core_verbs
                    and not (set(routes[left].core_verbs) & set(routes[right].core_verbs))
                ):
                    duplicate_candidates.setdefault(left, set()).add(right)
                    duplicate_candidates.setdefault(right, set()).add(left)
    ambiguous = {
        eid: sorted(partners)
        for eid, partners in duplicate_candidates.items()
        if len(partners) > 1
    }
    if ambiguous:
        detail = "; ".join(f"{eid} ↔ {partners}" for eid, partners in sorted(ambiguous.items()))
        raise FactGraphError(f"DUPLICATE 상대가 유일하지 않다: {detail}")
    for left, partners in sorted(duplicate_candidates.items()):
        right = next(iter(partners))
        classification[left] = "DUPLICATE"
        counterpart[left] = right
    for eid in routes:
        classification.setdefault(eid, "HOST_ONLY")
    return classification, counterpart, anchor_verbs


# ─────────────────────────── test responsibility ───────────────────────────


def _axis_vocabulary(repo_root: Path) -> "tuple[str, ...]":
    """pytest marker 등록(단일 출처)에서 자원 축 이름을 유도한다."""
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    markers = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
    axes = tuple(sorted(str(m).partition(":")[0].strip() for m in markers))
    if not axes:
        raise FactGraphError("pyproject 에 pytest marker 등록이 없다 — 축 어휘를 유도할 수 없다")
    return axes


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def _scope_nodes(root: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.AST, ...]:
    """한 lexical scope의 노드만 걷는다(중첩 함수·클래스의 동명 지역값은 제외)."""

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.nodes: list[ast.AST] = []

        def visit(self, node: ast.AST) -> None:
            self.nodes.append(node)
            super().visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

    visitor = Visitor()
    for statement in root.body:
        visitor.visit(statement)
    return tuple(visitor.nodes)


def _python_oracle_facts(
    tree: ast.Module,
    type_symbols: "dict[str, str]",
    handler_prefix: str,
) -> "tuple[frozenset[str], frozenset[tuple[str, str]], frozenset[tuple[str, str]]]":
    """Python 테스트의 호출을 수송/화면 receiver에 결속해 구조 사실로 만든다."""

    type_modules = {symbol.rsplit(".", 1)[0] for symbol in type_symbols}
    class_aliases: dict[str, str] = {}
    module_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.partition(".")[0]
                module_aliases[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                imported = f"{node.module}.{alias.name}"
                local = alias.asname or alias.name
                if imported in type_symbols:
                    class_aliases[local] = type_symbols[imported]
                elif imported in type_modules:
                    module_aliases[local] = imported

    def type_reference(expr: ast.AST) -> str | None:
        if isinstance(expr, ast.Name) and expr.id in class_aliases:
            return class_aliases[expr.id]
        dotted = _dotted_name(expr)
        if not dotted:
            return None
        if dotted in type_symbols:
            return type_symbols[dotted]
        head, dot, tail = dotted.partition(".")
        if dot and head in module_aliases:
            return type_symbols.get(f"{module_aliases[head]}.{tail}")
        return None

    def expression_summary(
        expr: ast.AST,
        env: "dict[str, frozenset[str]]",
        function_returns: "dict[str, _TypeSummary]",
    ) -> _TypeSummary:
        if isinstance(expr, ast.Name):
            if expr.id in env:
                return (env[expr.id],)
            tag = type_reference(expr)
            return (frozenset((tag,)),) if tag else ()
        tag = type_reference(expr)
        if tag:
            return (frozenset((tag,)),)
        if isinstance(expr, ast.Call):
            constructor = type_reference(expr.func)
            if constructor:
                return (frozenset((constructor,)),)
            if isinstance(expr.func, ast.Name) and expr.func.id in function_returns:
                return function_returns[expr.func.id]
            if isinstance(expr.func, ast.Attribute) and expr.func.attr == "__new__":
                candidates: set[str] = set()
                owner = type_reference(expr.func.value)
                if owner:
                    candidates.add(owner)
                for arg in expr.args:
                    arg_type = type_reference(arg)
                    if arg_type:
                        candidates.add(arg_type)
                if candidates:
                    return (frozenset(candidates),)
        if isinstance(expr, (ast.Tuple, ast.List)):
            parts: list[frozenset[str]] = []
            for item in expr.elts:
                summary = expression_summary(item, env, function_returns)
                parts.append(summary[0] if len(summary) == 1 else frozenset())
            return tuple(parts)
        if isinstance(expr, ast.IfExp):
            left = expression_summary(expr.body, env, function_returns)
            right = expression_summary(expr.orelse, env, function_returns)
            if len(left) == len(right):
                return tuple(a | b for a, b in zip(left, right, strict=True))
        return ()

    def bind_target(
        target: ast.AST,
        summary: _TypeSummary,
        env: "dict[str, frozenset[str]]",
    ) -> bool:
        changed = False
        if isinstance(target, ast.Name) and len(summary) == 1 and summary[0]:
            merged = env.get(target.id, frozenset()) | summary[0]
            changed = merged != env.get(target.id)
            env[target.id] = merged
        elif isinstance(target, (ast.Tuple, ast.List)) and len(target.elts) == len(summary):
            for item, part in zip(target.elts, summary, strict=True):
                changed |= bind_target(item, (part,), env)
        return changed

    def populate_env(
        nodes: "tuple[ast.AST, ...]",
        env: "dict[str, frozenset[str]]",
        function_returns: "dict[str, _TypeSummary]",
    ) -> None:
        for _ in range(6):
            changed = False
            for node in nodes:
                if isinstance(node, ast.Assign):
                    summary = expression_summary(node.value, env, function_returns)
                    for target in node.targets:
                        changed |= bind_target(target, summary, env)
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    summary = expression_summary(node.value, env, function_returns)
                    changed |= bind_target(node.target, summary, env)
            if not changed:
                break

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module_nodes = _scope_nodes(tree)
    module_env: dict[str, frozenset[str]] = {}
    function_returns: dict[str, _TypeSummary] = {}
    function_envs: dict[str, dict[str, frozenset[str]]] = {}
    for _ in range(8):
        populate_env(module_nodes, module_env, function_returns)
        changed = False
        for name, function in functions.items():
            env = dict(module_env)
            for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
                if arg.annotation is not None:
                    tag = type_reference(arg.annotation)
                    if tag:
                        env[arg.arg] = frozenset((tag,))
            nodes = _scope_nodes(function)
            populate_env(nodes, env, function_returns)
            parts = [
                expression_summary(node.value, env, function_returns)
                for node in nodes
                if isinstance(node, ast.Return) and node.value is not None
            ]
            parts = [part for part in parts if part]
            if parts and len({len(part) for part in parts}) == 1:
                merged = tuple(
                    frozenset().union(*(part[index] for part in parts))
                    for index in range(len(parts[0]))
                )
                if function_returns.get(name) != merged:
                    function_returns[name] = merged
                    changed = True
            function_envs[name] = env
        if not changed:
            break

    wrapper_specs: dict[str, list[tuple[int, tuple[int, ...]]]] = {}
    for name, function in functions.items():
        params = [
            arg.arg
            for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        ]
        for node in _scope_nodes(function):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dispatch"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in params
            ):
                continue
            argument_params = tuple(
                params.index(arg.id)
                for arg in node.args
                if isinstance(arg, ast.Name) and arg.id in params
            )
            if argument_params:
                wrapper_specs.setdefault(name, []).append(
                    (params.index(node.func.value.id), argument_params)
                )

    direct_calls: set[str] = set()
    dispatch_pairs: set[tuple[str, str]] = set()
    handler_pairs: set[tuple[str, str]] = set()

    def scalar_types(
        expr: ast.AST,
        env: "dict[str, frozenset[str]]",
    ) -> frozenset[str]:
        summary = expression_summary(expr, env, function_returns)
        return summary[0] if len(summary) == 1 else frozenset()

    def one_screen(tags: frozenset[str]) -> str | None:
        if len(tags) != 1:
            return None
        tag = next(iter(tags))
        return tag.partition(":")[2] if tag.startswith("screen:") else None

    def string_arg(call: ast.Call, index: int) -> str | None:
        if index >= len(call.args):
            return None
        arg = call.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None

    def collect(nodes: "tuple[ast.AST, ...]", env: "dict[str, frozenset[str]]") -> None:
        for node in nodes:
            if handler_prefix and isinstance(node, ast.Attribute) and node.attr.startswith(handler_prefix):
                screen = one_screen(scalar_types(node.value, env))
                if screen:
                    handler_pairs.add((screen, node.attr.removeprefix(handler_prefix)))
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                tags = scalar_types(node.func.value, env)
                if tags == frozenset(("transport",)):
                    if node.func.attr == "dispatch":
                        screen, action = string_arg(node, 0), string_arg(node, 1)
                        if screen is not None and action is not None:
                            dispatch_pairs.add((screen, action))
                    else:
                        direct_calls.add(node.func.attr)
                screen = one_screen(tags)
                if screen and node.func.attr == "dispatch":
                    action = string_arg(node, 0)
                    if action is not None:
                        dispatch_pairs.add((screen, action))
            elif isinstance(node.func, ast.Name) and node.func.id == "getattr":
                if len(node.args) >= 2:
                    screen = one_screen(scalar_types(node.args[0], env))
                    attr = node.args[1]
                    if (
                        screen
                        and isinstance(attr, ast.Constant)
                        and isinstance(attr.value, str)
                        and handler_prefix
                        and attr.value.startswith(handler_prefix)
                    ):
                        handler_pairs.add((screen, attr.value.removeprefix(handler_prefix)))
            if isinstance(node.func, ast.Name):
                for receiver_index, argument_indices in wrapper_specs.get(node.func.id, []):
                    if receiver_index >= len(node.args):
                        continue
                    if not argument_indices:
                        continue
                    tags = scalar_types(node.args[receiver_index], env)
                    if tags == frozenset(("transport",)) and len(argument_indices) >= 2:
                        screen_index, action_index = argument_indices[:2]
                        screen = string_arg(node, screen_index)
                        action = string_arg(node, action_index)
                        if screen is not None and action is not None:
                            dispatch_pairs.add((screen, action))
                    else:
                        screen = one_screen(tags)
                        action_index = next(iter(argument_indices))
                        action = string_arg(node, action_index)
                        if screen and action is not None:
                            dispatch_pairs.add((screen, action))

    collect(module_nodes, module_env)
    for name, function in functions.items():
        collect(_scope_nodes(function), function_envs.get(name, dict(module_env)))
    return frozenset(direct_calls), frozenset(dispatch_pairs), frozenset(handler_pairs)


def _js_tokens(source: str, rel: str) -> tuple[tuple[str, str], ...]:
    """주석·산문·정규식을 코드로 세지 않는 최소 JavaScript lexical token 열거."""

    tokens: list[tuple[str, str]] = []
    i = 0
    previous = ""
    regex_starts = {"", "(", "[", "{", "=", ",", ":", ";", "!", "?", "=>"}
    regex_words = {"return", "case", "throw", "delete", "void", "typeof", "yield"}
    while i < len(source):
        char = source[i]
        if char.isspace():
            i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i + 2)
            i = len(source) if end < 0 else end + 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise FactGraphError(f"JavaScript 테스트 파싱 실패(닫히지 않은 주석): {rel}")
            i = end + 2
            continue
        if char in "'\"":
            quote = char
            i += 1
            value: list[str] = []
            while i < len(source) and source[i] != quote:
                if source[i] in "\r\n":
                    raise FactGraphError(f"JavaScript 테스트 파싱 실패(닫히지 않은 문자열): {rel}")
                if source[i] == "\\":
                    i += 1
                    if i >= len(source):
                        break
                    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
                    value.append(escapes.get(source[i], source[i]))
                else:
                    value.append(source[i])
                i += 1
            if i >= len(source):
                raise FactGraphError(f"JavaScript 테스트 파싱 실패(닫히지 않은 문자열): {rel}")
            i += 1
            tokens.append(("string", "".join(value)))
            previous = "string"
            continue
        if char == "`":
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == "`":
                    i += 1
                    break
                i += 1
            else:
                raise FactGraphError(f"JavaScript 테스트 파싱 실패(닫히지 않은 template): {rel}")
            tokens.append(("template", ""))
            previous = "template"
            continue
        if char == "/" and (previous in regex_starts or previous in regex_words):
            i += 1
            in_class = False
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == "[":
                    in_class = True
                elif source[i] == "]":
                    in_class = False
                elif source[i] == "/" and not in_class:
                    i += 1
                    while i < len(source) and source[i].isalpha():
                        i += 1
                    break
                elif source[i] in "\r\n":
                    raise FactGraphError(f"JavaScript 테스트 파싱 실패(닫히지 않은 정규식): {rel}")
                i += 1
            else:
                raise FactGraphError(f"JavaScript 테스트 파싱 실패(닫히지 않은 정규식): {rel}")
            tokens.append(("regex", ""))
            previous = "regex"
            continue
        if char.isalpha() or char in "_$":
            end = i + 1
            while end < len(source) and (source[end].isalnum() or source[end] in "_$"):
                end += 1
            word = source[i:end]
            tokens.append(("ident", word))
            previous = word
            i = end
            continue
        punct = "=>" if source.startswith("=>", i) else char
        tokens.append(("punct", punct))
        previous = punct
        i += len(punct)
    return tuple(tokens)


def _js_oracle_facts(
    source: str,
    rel: str,
) -> "tuple[frozenset[str], frozenset[tuple[str, str]]]":
    tokens = _js_tokens(source, rel)
    direct_calls: set[str] = set()
    dispatch_pairs: set[tuple[str, str]] = set()

    for index, (kind, value) in enumerate(tokens):
        if kind != "ident" or value not in ("dispatch", "call"):
            continue
        if index == 0 or tokens[index - 1][1] != ".":
            continue
        tail = tokens[index + 1 : index + 6]
        if (
            len(tail) == 5
            and tail[0][1] == "("
            and tail[1][0] == "string"
            and tail[2][1] == ","
            and tail[3][0] == "string"
        ):
            dispatch_pairs.add((tail[1][1], tail[3][1]))

    start = next(
        (
            index + 3
            for index in range(len(tokens) - 3)
            if tokens[index : index + 3]
            == (("ident", "const"), ("ident", "DELEGATIONS"), ("punct", "="))
            and tokens[index + 3] == ("punct", "[")
        ),
        None,
    )
    if start is not None:
        depth = 0
        end = start
        for end in range(start, len(tokens)):
            if tokens[end] == ("punct", "["):
                depth += 1
            elif tokens[end] == ("punct", "]"):
                depth -= 1
                if depth == 0:
                    break
        else:
            raise FactGraphError(f"JavaScript 테스트 파싱 실패(DELEGATIONS 미종결): {rel}")
        for index in range(start + 1, end - 5):
            row = tokens[index : index + 6]
            if not (
                row[0] == ("punct", "[")
                and row[1][0] == "string"
                and row[2] == ("punct", ",")
                and row[3][0] == "string"
                and row[4] == ("punct", ",")
                and row[5] == ("punct", "[")
            ):
                continue
            backend_method = row[3][1]
            if backend_method == "dispatch":
                args = tokens[index + 6 : index + 10]
                if (
                    len(args) == 4
                    and args[0][0] == "string"
                    and args[1] == ("punct", ",")
                    and args[2][0] == "string"
                ):
                    dispatch_pairs.add((args[0][1], args[2][1]))
            else:
                direct_calls.add(backend_method)
    return frozenset(direct_calls), frozenset(dispatch_pairs)


def scan_test_files(
    repo_root: Path,
    closure: Closure,
    *,
    tests_rel: str = "tests",
    extra_files: "tuple[str, ...]" = ("conftest.py",),
    axes: "tuple[str, ...] | None" = None,
    type_symbols: "dict[str, str] | None" = None,
    handler_prefix: str = "_do_",
) -> tuple[TestFileFacts, ...]:
    """테스트 파일의 참조 사실 스캔 — 존재가 아니라 **참조 구조**에서 사실을 뽑는다.

    분모는 ``tests_rel`` 하위 ``.py`` 전수 + ``extra_files`` 다. 파싱 실패는 skip 이 아니라
    오류다. 이 게이트의 자기 파일도 분모에 든다(모듈 docstring 의 순환 규칙).
    """
    repo_root = Path(repo_root)
    axes = axes if axes is not None else _axis_vocabulary(repo_root)
    module_names = {mf.module for mf in closure.modules}
    top_packages = {name.partition(".")[0] for name in module_names}

    paths: list[str] = []
    tests_dir = repo_root / tests_rel
    if not tests_dir.is_dir():
        raise FactGraphError(f"테스트 트리가 없다: {tests_dir}")
    paths.extend(p.relative_to(repo_root).as_posix() for p in sorted(tests_dir.rglob("*.py")))
    js_dir = tests_dir / "js"
    if js_dir.is_dir():
        paths.extend(p.relative_to(repo_root).as_posix() for p in sorted(js_dir.rglob("*.js")))
    for extra in extra_files:
        if (repo_root / extra).is_file():
            paths.append(extra)

    out: list[TestFileFacts] = []
    type_symbols = type_symbols or {}
    for rel in sorted(set(paths)):
        if rel.endswith(".js"):
            source = (repo_root / rel).read_text(encoding="utf-8-sig")
            direct_calls, dispatch_pairs = _js_oracle_facts(source, rel)
            out.append(
                TestFileFacts(
                    path=rel,
                    axes=(),
                    product_modules=(),
                    imported_symbols=(),
                    attr_calls=frozenset(),
                    str_literals=frozenset(),
                    call_arg_strings=frozenset(),
                    direct_calls=direct_calls,
                    dispatch_pairs=dispatch_pairs,
                )
            )
            continue
        try:
            # utf-8-sig: BOM 을 든 테스트 파일이 실재한다(실측) — CPython 소스 디코딩과 같은
            # 처리다. BOM 을 구문 오류로 만들면 실파일이 분모에서 시끄럽게가 아니라 잘못 죽는다.
            tree = ast.parse((repo_root / rel).read_text(encoding="utf-8-sig"))
        except SyntaxError as exc:
            raise FactGraphError(f"테스트 파일 파싱 실패(조용한 skip 금지): {rel} — {exc}") from exc
        product_modules: set[str] = set()
        imported_symbols: set[str] = set()
        marker_axes: set[str] = set()
        attr_calls: set[str] = set()
        str_literals: set[str] = set()
        call_arg_strings: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.partition(".")[0] in top_packages:
                        product_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.partition(".")[0] in top_packages:
                    product_modules.add(node.module)
                    for alias in node.names:
                        # ``from 패키지 import 모듈`` 은 심볼이 아니라 모듈 참조다 —
                        # 폐포 모듈 이름과 대조해 갈라 적는다(둘을 섞으면 CLI entry
                        # 모듈 참조가 심볼 행세를 해서 근거 판정이 좁아진다).
                        dotted = f"{node.module}.{alias.name}"
                        if dotted in module_names:
                            product_modules.add(dotted)
                        else:
                            imported_symbols.add(f"{node.module}:{alias.name}")
            elif isinstance(node, ast.Attribute):
                if (
                    node.attr in axes
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr == "mark"
                ):
                    marker_axes.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if len(node.value) <= 80:
                    str_literals.add(node.value)
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    attr_calls.add(node.func.attr)
                call_arg_strings.update(
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
        direct_calls, dispatch_pairs, handler_pairs = _python_oracle_facts(
            tree, type_symbols, handler_prefix
        )
        out.append(
            TestFileFacts(
                path=rel,
                axes=tuple(sorted(marker_axes)),
                product_modules=tuple(sorted(product_modules)),
                imported_symbols=tuple(sorted(imported_symbols)),
                attr_calls=frozenset(attr_calls),
                str_literals=frozenset(str_literals),
                call_arg_strings=frozenset(call_arg_strings),
                direct_calls=direct_calls,
                dispatch_pairs=dispatch_pairs,
                handler_pairs=handler_pairs,
            )
        )
    return tuple(out)


def _link_oracles(
    routes: "dict[str, EntryRoute]",
    surface: "dict[str, object]",
    test_files: tuple[TestFileFacts, ...],
) -> "tuple[dict[str, tuple[OracleLink, ...]], dict[str, str], tuple[tuple[str, str], ...]]":
    cli_modules = set(surface.get("cli_modules", []))  # type: ignore[arg-type]
    required_flags = set(surface.get("cli_required_flags", []))  # type: ignore[arg-type]
    boot_routers = set(surface.get("boot_routers", []))  # type: ignore[arg-type]
    controller_module_of_screen = dict(surface.get("controller_module_of_screen", {}))  # type: ignore[arg-type]

    def references_cli(tf: TestFileFacts) -> bool:
        return any(m in cli_modules for m in tf.product_modules)

    links: dict[str, list[OracleLink]] = {eid: [] for eid in routes}
    for tf in test_files:
        for eid, route in routes.items():
            entry = route.entry
            bases: list[str] = []
            if entry.host == "cli" and references_cli(tf):
                literal = entry.entry_id.partition(":")[2]
                if entry.kind == "cli_subcommand" and literal in tf.str_literals:
                    bases.append("argv-literal")
                elif entry.kind == "cli_flag" and literal in tf.str_literals:
                    bases.append("flag-literal")
                elif entry.kind == "cli_default" and (required_flags & tf.str_literals):
                    bases.append("trunk-flag")
            elif entry.host == "gui":
                tail = entry.entry_id.rsplit("/", 1)[-1]
                screen = entry.entry_id.partition(":")[2].partition("/")[0]
                if entry.kind == "gui_action":
                    if (screen, tail) in tf.dispatch_pairs:
                        bases.append("dispatch-literal")
                    if (screen, tail) in tf.handler_pairs:
                        bases.append("handler-ref")
                elif entry.kind == "gui_direct":
                    if tail in tf.direct_calls:
                        bases.append("direct-call")
                elif entry.kind == "gui_screen_boot":
                    controller_module = controller_module_of_screen.get(screen, "")
                    if (
                        tail in boot_routers
                        and tail in tf.attr_calls
                        and controller_module in tf.product_modules
                    ):
                        bases.append("boot-call")
            if not bases:
                # 경로 위 core **함수**를 모듈-한정 이름으로 직접 import 한 테스트 —
                # wrapper 가 아니라 그 밑의 동사를 겨눈 증인이다(CORE 수준, INFERENCE).
                # 모듈 한정이 없으면 범용 이름(validate 등)이 무관 entry 에 들러붙는다.
                route_functions = {
                    f"{parse_symbol_id(v)[0]}:{parse_symbol_id(v)[1]}"
                    for v in route.core_verbs
                    if v.endswith("#function")
                }
                if route_functions & set(tf.imported_symbols):
                    bases.append("core-verb-import")
            for basis in bases:
                links[eid].append(OracleLink(tf.path, basis))

    ordered = {
        eid: tuple(sorted(set(candidates), key=lambda link: (link.test_path, link.basis)))
        for eid, candidates in links.items()
    }
    status: dict[str, str] = {}
    for eid, candidates in ordered.items():
        if any(link.basis in ENTRY_BASES for link in candidates):
            status[eid] = "ENTRY"
        elif candidates:
            status[eid] = "CORE"
        else:
            status[eid] = "NONE"

    gaps: list[tuple[str, str]] = []
    for eid, route in sorted(routes.items()):
        if status[eid] == "NONE":
            reason = (
                "core 경로가 비어 있지 않은데 어느 근거로도 겨누는 테스트가 없다"
                if route.core_verbs
                else "core 투영 경로가 비어 있고 entry 수준에서 겨누는 테스트도 없다"
            )
            gaps.append((eid, reason))
        elif status[eid] == "CORE":
            gaps.append(
                (eid, "wrapper 를 entry 수준에서 겨누는 테스트가 없다(core 동사 import 만)")
            )
    return ordered, status, tuple(gaps)


# ─────────────────────────────── 조립 ───────────────────────────────


def build_use_cases(repo_root: Path) -> UseCaseResult:
    repo_root = Path(repo_root)
    graph = build(repo_root)
    resolver = _Resolver(repo_root, graph)
    console_entries, gui_entry_specs = _project_entry_points(repo_root)
    gui_list, gui_meta = _derive_gui_entries(resolver, gui_entry_specs)  # transport 문맥 선행
    cli_list, cli_meta = _derive_cli_entries(resolver, console_entries)
    entries = tuple(
        sorted(cli_list + gui_list, key=lambda entry: (entry.host, entry.entry_id))
    )
    ids = [entry.entry_id for entry in entries]
    duplicates = sorted({eid for eid in ids if ids.count(eid) > 1})
    if duplicates:
        raise FactGraphError(f"entry id 충돌: {duplicates}")

    surface: dict[str, object] = {**cli_meta, **gui_meta}
    prefix_sites = [site for site in graph.dispatch_sites if site.kind == "prefix"]
    surface["prefix_key"] = prefix_sites[0].key if prefix_sites else ""
    controllers = tuple(surface.get("controllers", []))  # type: ignore[arg-type]
    screen_of = _class_screen_names(resolver, tuple(controllers))
    surface["controller_module_of_screen"] = {
        screen: parse_symbol_id(cls)[0] for cls, screen in screen_of.items()
    }
    routers = set(surface.get("routers", []))  # type: ignore[arg-type]
    surface["action_router_names"] = sorted(routers - set(surface.get("boot_routers", [])))  # type: ignore[arg-type]

    excluded_modules, excluded_prefixes = _core_projection(surface)
    _guard_projection_not_degenerate(
        tuple(mf.module for mf in graph.closure.modules), excluded_modules, excluded_prefixes
    )
    routes = {
        entry.entry_id: _route(resolver, entry, excluded_modules, excluded_prefixes)
        for entry in entries
    }
    classification, counterpart, anchor_verbs = _classify(routes)
    type_symbols = {
        f"{parse_symbol_id(cls)[0]}.{parse_symbol_id(cls)[1]}": f"screen:{screen}"
        for cls, screen in screen_of.items()
    }
    transport_module, transport_name, _ = parse_symbol_id(str(surface["transport"]))
    type_symbols[f"{transport_module}.{transport_name}"] = "transport"
    test_files = scan_test_files(
        repo_root,
        graph.closure,
        type_symbols=type_symbols,
        handler_prefix=str(surface["prefix_key"]),
    )
    oracles, oracle_status, gaps = _link_oracles(routes, surface, test_files)
    return UseCaseResult(
        graph=graph,
        entries=entries,
        routes=routes,
        classification=classification,
        counterpart=counterpart,
        anchor_verbs=anchor_verbs,
        surface=surface,
        test_files=test_files,
        oracles=oracles,
        oracle_status=oracle_status,
        gaps=gaps,
    )


# ─────────────────────────────── 원장 ───────────────────────────────

_HEADER = f"""# 생성 파일 — 직접 편집 금지. P1-02E use-case·test responsibility 원장(#517).
# 원천: 고정 baseline src/ 의 02A 정적 그래프(read-only 입력) + tests/ 참조 스캔
# 재생성: {REGEN_COMMAND}
# 검사:   {REGEN_COMMAND} --check
schema = "use-case-graph-02e/v1"
"""


def render(repo_root: Path, *, _baseline_checked: bool = False) -> str:
    repo_root = Path(repo_root)
    if not _baseline_checked:
        problems = _baseline_source_problems(repo_root)
        if problems:
            raise FactGraphError("; ".join(problems))
    result = build_use_cases(repo_root)
    graph = result.graph

    hosts = {eid: route.entry.host for eid, route in result.routes.items()}
    n_cli = sum(1 for host in hosts.values() if host == "cli")
    n_gui = len(hosts) - n_cli
    by_class = {"COMMON": 0, "HOST_ONLY": 0, "DUPLICATE": 0}
    for eid in result.classification:
        by_class[result.classification[eid]] += 1
    empty_routes = sum(1 for route in result.routes.values() if not route.core_verbs)
    status_counts = {name: 0 for name in _ORACLE_STATUS}
    for status in result.oracle_status.values():
        status_counts[status] += 1
    axis_counts: dict[str, int] = {}
    for tf in result.test_files:
        key = ",".join(tf.axes) if tf.axes else "deterministic"
        axis_counts[key] = axis_counts.get(key, 0) + 1

    parts = [_HEADER, "\n[baseline]\n"]
    parts.append(f"git_sha = {_q(BASELINE_SHA)}\n")
    parts.append("\n# 02A call-axis 입력 핀 — 같은 기반 사실 위의 파생임을 P1-03 이 검증한다.\n")
    parts.append("[inputs]\n")
    parts.append(f'base_facts = "{graph.base_digest}"\n')
    parts.append(f'graph_facts = "{graph.graph_digest}"\n')

    parts.append("\n[surface]\n")
    for key in (
        "cli_modules",
        "cli_trunks",
        "cli_required_flags",
        "cli_flag_literals",
        "gui_modules",
        "screens",
        "routers",
        "boot_routers",
        "action_router_names",
    ):
        values = sorted({str(v) for v in result.surface.get(key, [])})  # type: ignore[union-attr]
        parts.append(f"{key} = [{', '.join(_q(v) for v in values)}]\n")
    parts.append(f"transport = {_q(str(result.surface.get('transport', '')))}\n")
    parts.append(f"controllers = {len(result.surface.get('controllers', []))}\n")  # type: ignore[arg-type]

    parts.append("\n[counts]\n")
    parts.append(f"entries_total = {len(result.entries)}\n")
    parts.append(f"entries_cli = {n_cli}\n")
    parts.append(f"entries_gui = {n_gui}\n")
    parts.append(f"common = {by_class['COMMON']}\n")
    parts.append(f"host_only = {by_class['HOST_ONLY']}\n")
    parts.append(f"duplicate = {by_class['DUPLICATE']}\n")
    parts.append(f"anchor_verbs = {len(result.anchor_verbs)}\n")
    parts.append(f"empty_route_entries = {empty_routes}\n")
    parts.append(f"oracle_entry = {status_counts['ENTRY']}\n")
    parts.append(f"oracle_core = {status_counts['CORE']}\n")
    parts.append(f"oracle_none = {status_counts['NONE']}\n")
    parts.append(f"characterization_gaps = {len(result.gaps)}\n")
    parts.append(f"test_files = {len(result.test_files)}\n")
    parts.append("\n[test_axis_counts]\n")
    for key, count in sorted(axis_counts.items()):
        parts.append(f"{_q(key)} = {count}\n")

    parts.append("\n# 교차-host fan(1,1) 공유 core 동사 — COMMON 판정의 사실 근거.\n")
    for verb, (cli_id, gui_id) in sorted(result.anchor_verbs.items()):
        parts.append("\n[[anchor]]\n")
        parts.append(f"verb = {_q(verb)}\n")
        parts.append(f"cli_entry = {_q(cli_id)}\n")
        parts.append(f"gui_entry = {_q(gui_id)}\n")

    for entry in result.entries:
        route = result.routes[entry.entry_id]
        parts.append("\n[[entry]]\n")
        parts.append(f"id = {_q(entry.entry_id)}\n")
        parts.append(f"host = {_q(entry.host)}\n")
        parts.append(f"kind = {_q(entry.kind)}\n")
        parts.append(f"classification = {_q(result.classification[entry.entry_id])}\n")
        partner = result.counterpart.get(entry.entry_id)
        if partner:
            parts.append(f"counterpart = {_q(partner)}\n")
        anchors = sorted(
            verb for verb, pair in result.anchor_verbs.items() if entry.entry_id in pair
        )
        if anchors:
            parts.append(f"anchor_verbs = [{', '.join(_q(a) for a in anchors)}]\n")
        parts.append(f"core_verb_count = {len(route.core_verbs)}\n")
        parts.append(f"unresolved_out = {route.unresolved_out}\n")
        if route.seam_rules:
            parts.append(
                f"seam_rules = [{', '.join(_q(r) for r in route.seam_rules)}]\n"
            )
        parts.append("roots = [\n")
        parts.extend(f"  {_q(root)},\n" for root in entry.roots)
        parts.append("]\n")
        parts.append(f"oracle_status = {_q(result.oracle_status[entry.entry_id])}\n")
        links = result.oracles[entry.entry_id]
        parts.append("oracles = [\n")
        parts.extend(f"  {_q(f'{link.test_path} :: {link.basis}')},\n" for link in links)
        parts.append("]\n")

    parts.append("\n# 근거 없는 비어 있지 않은 경로 — characterization 필요 항목(loud).\n")
    for entry_id, reason in result.gaps:
        parts.append("\n[[characterization_gap]]\n")
        parts.append(f"entry = {_q(entry_id)}\n")
        parts.append(f"reason = {_q(reason)}\n")

    for tf in result.test_files:
        parts.append("\n[[test_file]]\n")
        parts.append(f"path = {_q(tf.path)}\n")
        axis = ",".join(tf.axes) if tf.axes else "deterministic"
        parts.append(f"axis = {_q(axis)}\n")
        parts.append("product_modules = [\n")
        parts.extend(f"  {_q(m)},\n" for m in tf.product_modules)
        parts.append("]\n")
    return "".join(parts)


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def check(repo_root: Path) -> "list[str]":
    repo_root = Path(repo_root)
    problems = _baseline_source_problems(repo_root)
    if problems:
        return problems
    target = repo_root / LEDGER_REL_PATH
    expected = render(repo_root, _baseline_checked=True)
    if not target.is_file():
        return [f"{LEDGER_REL_PATH}: 생성물이 없습니다 — `{REGEN_COMMAND}` 로 생성하세요."]
    if target.read_text(encoding="utf-8") == expected:
        return []
    problems = [f"{LEDGER_REL_PATH}: 원장 드리프트 — `{REGEN_COMMAND}` 로 재생성하세요."]
    try:
        actual = tomllib.loads(target.read_text(encoding="utf-8"))
        fresh = tomllib.loads(expected)
        for section in ("inputs", "counts"):
            left = actual.get(section, {})
            right = fresh.get(section, {})
            for key in sorted(set(left) | set(right)):
                if left.get(key) != right.get(key):
                    problems.append(
                        f"  {section}.{key}: 커밋본 {left.get(key)!r} ≠ 재계측 {right.get(key)!r}"
                    )
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"  커밋본을 파싱할 수 없다(직접 편집 흔적?): {exc}")
    return problems


def rewrite(repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    problems = _baseline_source_problems(repo_root)
    if problems:
        raise FactGraphError("; ".join(problems))
    target = repo_root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(repo_root, _baseline_checked=True))
    return target


def _baseline_source_problems(repo_root: Path) -> "list[str]":
    """실저장소 생성물이 고정 SHA 라벨과 다른 ``src/``를 섞지 못하게 막는다(02A 규약)."""
    if not (repo_root / ".git").exists():
        return []  # 합성 fixture 에는 Git baseline 계약을 강제하지 않는다
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE_SHA}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if exists.returncode != 0:
        return [f"baseline commit 부재: {BASELINE_SHA}"]
    changed = subprocess.run(
        ["git", "diff", "--quiet", BASELINE_SHA, "--", "src"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "src"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if changed.returncode != 0 or untracked.stdout.strip():
        return [f"baseline {BASELINE_SHA} 이후 production src/가 바뀌었다 — SHA를 재확정하라"]
    return []


__all__ = [
    "BASELINE_SHA",
    "COLLECTOR",
    "CORE_BASES",
    "ENTRY_BASES",
    "LEDGER_REL_PATH",
    "REGEN_COMMAND",
    "SEAM_RULES",
    "EntryRoute",
    "OracleLink",
    "TestFileFacts",
    "UseCaseEntry",
    "UseCaseResult",
    "build_use_cases",
    "check",
    "render",
    "rewrite",
    "scan_test_files",
]
