"""P1-02B 상태 그래프 축 — mutable state·변이·transaction cluster·동시성 결부의 전수 계측.

기반 수집기(#512)는 속성 **재결속**(``attr_assign``/``global_rebind``/``setattr_literal``)만
남기고, 모듈 전역 생성·클래스 속성·필드 선언·컬렉션 내용 변이·속성 읽기 전수는 이 축(#514)
소유로 미뤘다. 이 모듈은 기반·02A 사실 위의 **파생 패스**로 그 간극을 닫는다 — 제품 코드
접촉 0, ``collect.py`` 수정 0.

방출 어휘(전부 중앙 ``schema.RELATIONS`` 등록 어휘):

- ``writes_attribute`` — 모듈 전역 할당(``module_global_assign``), 클래스 속성 할당
  (``class_attr_assign``), 필드 선언(``class_field_declaration``, annotation 만 있는 클래스
  본문 행 — 실행 시 쓰기는 합성 생성자 몫이라 grade 는 ``INFERRED``), 속성 삭제.
- ``mutates_attribute`` — 좌표의 결속을 갈아끼우지 않고 내용을 바꾸는 변이: 컬렉션 변이
  메서드 호출(``mutcall_*``)과 subscript 저장/삭제/증감(``subscript_mutation_*``).
  변이 메서드 가족은 이름 기반이라 수신자 타입을 정적으로 증명하지 못한다 — 그래서 해석된
  수신자도 grade 는 ``INFERRED`` 를 넘지 않고, 못 푼 수신자는 ``?:`` 좌표 그대로
  runtime-required 원장 행으로 남는다(임의 추측 금지).
- ``reads_attribute`` — self 수신 필드 읽기 전수(``attr_read_self``), 지역 데이터플로
  (매개변수 annotation·유일 생성자 결속)로 소유자가 닫힌 읽기(``attr_read_typed``),
  변이 증거가 있는 모듈 전역의 bare 이름 읽기(``global_read``). 소유자를 못 닫은 임의
  속성 읽기는 사실로 적지 않는다 — 그 경계는 원장 머리말에 명시된 정직한 좁힘이다.

수명·거래 축은 사실의 **조인**으로 원장에 선다: 저장 위치(모듈 전역/클래스 속성/인스턴스
필드), writer/mutator/reader 심볼 전수, 같은 본문에서 함께 변이되는 상태 집합(transaction
cluster 후보 — 원자성 주장이 아니라 공변이 사실), 둘 이상의 소유 단위가 쓰는 공유 상태,
threading 프리미티브가 결부된 좌표(취소·진행·확인 전이의 기반시설). 상태 이름 휴리스틱은
어디에도 없다 — 이슈 불변식대로 실제 writer/readers 만 기준이다.

커밋 생성물은 02A 와 같은 규약(digest 핀 + 파생 원장)이고, ``[input]`` 절이 02A 원장의
digest 를 그대로 들어 네 슬라이스가 같은 측정 위에 서 있음을 기계로 검증한다.
"""

from __future__ import annotations

import ast
import json
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from . import static_graph
from .closure import Closure, ModuleFile, production_closure
from .collect import call_site_anchor, collect_facts, collect_symbols, syntax_site_anchor
from .schema import (
    Evidence,
    Fact,
    FactGraphError,
    Provenance,
    Shard,
    Symbol,
    facts_digest,
    make_shard,
    parse_symbol_id,
    symbol_id,
)

COLLECTOR = "factgraph.state_graph"

LEDGER_REL_PATH = "docs/factgraph/state_graph_02b.toml"
REGEN_COMMAND = "uv run python scripts/gen_state_graph_02b.py"

#: 이름 기반 컬렉션/이벤트 변이 메서드 가족. 이름만으로는 수신자 타입을 증명하지 못하므로
#: 이 가족이 내는 해석 좌표의 grade 상한은 INFERRED 다(모듈 docstring).
MUTATOR_METHODS: frozenset[str] = frozenset(
    {
        "add",
        "append",
        "appendleft",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "popitem",
        "popleft",
        "remove",
        "reverse",
        "set",
        "setdefault",
        "sort",
        "update",
    }
)

_THREADING_PREFIX = "ext:threading."
SYNC_PRIMITIVES: tuple[str, ...] = (
    "Condition",
    "Event",
    "Lock",
    "RLock",
    "Semaphore",
    "Thread",
    "Timer",
)

#: 미해결 rule → 후속 확인 경로. 등록 없는 미해결 rule 이 원장에 나타나면 render 가 죽는다.
FOLLOWUP_OF_RULE: dict[str, str] = {
    "mutcall_local_binding": "함수-지역 수명 후보 — P1-03 lifetime 분류(탈출 여부는 02A call/construct 그래프·runtime trace 로 종결)",
    "subscript_mutation_local": "함수-지역 수명 후보 — P1-03 lifetime 분류(탈출 여부는 02A call/construct 그래프·runtime trace 로 종결)",
    "mutcall_attribute_opaque": "runtime trace 또는 P1-03 타입 결합 — 수신 객체 미확정",
    "mutcall_opaque": "runtime trace — 수신 식이 정적 좌표가 아니다",
    "subscript_mutation_opaque": "runtime trace 또는 P1-03 타입 결합 — 컨테이너 소유자 미확정",
    "mutcall_receiver_self": "02A MRO/디스패치 결합 또는 runtime trace — 자기 수신 변이 메서드",
    "attr_delete_opaque": "runtime trace — 삭제 대상 소유자 미확정",
}


def followup_of(rule: str) -> str:
    exact = FOLLOWUP_OF_RULE.get(rule)
    if exact is None:
        raise FactGraphError(
            f"후속 귀속 없는 미해결 rule: {rule!r} — FOLLOWUP_OF_RULE 에 소유자를 등록하라"
        )
    return exact


# ---------------------------------------------------------------------------
# 파생 수집 패스
# ---------------------------------------------------------------------------


@dataclass
class _Scope:
    sid: str
    first_param: str  # 메서드가 아니거나 staticmethod 면 ""
    cls_qual: str
    local_names: set[str]
    global_decls: set[str]
    root_types: "dict[str, str]"  # 이름 → 유일 클래스 SID (오염되면 빠진다)


class _StateWalker:
    """모듈 하나의 상태 사실 방출기 — 기반 수집기와 독립인 보수적 스코프 추적."""

    def __init__(
        self,
        mf: ModuleFile,
        tree: ast.Module,
        index: "dict[tuple[str, str], Symbol]",
        class_basenames: "dict[str, str]",
        mutated_globals: "frozenset[str] | None",
    ) -> None:
        self.mf = mf
        self.tree = tree
        self.index = index
        self.class_basenames = class_basenames
        self.mutated_globals = mutated_globals  # None = 1패스(global_read 미방출)
        self.module_sid = symbol_id(mf.module, "", "module")
        self.module_globals = _module_level_bound_names(tree)
        self.module_imports = _module_level_import_names(tree)
        self.facts: list[Fact] = []
        self.fn_stack: list[_Scope] = []
        self.class_stack: list[str] = []
        self.class_dataclassish: list[bool] = []
        self.qual_prefix: list[str] = []

    # -- 공용 ----------------------------------------------------------------

    def run(self) -> "list[Fact]":
        self._walk_body(self.tree.body, module_level=True)
        return self.facts

    def _src(self) -> str:
        if self.fn_stack:
            return self.fn_stack[-1].sid
        if self.class_stack:
            sym = self.index.get((self.mf.module, self.class_stack[-1]))
            if sym is not None:
                return sym.id
            return symbol_id(self.mf.module, self.class_stack[-1], "class")
        return self.module_sid

    def _emit(self, rel: str, dst: str, grade: str, node: ast.AST, rule: str, anchor: str) -> None:
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

    def _first_param(self) -> str:
        return self.fn_stack[-1].first_param if self.fn_stack else ""

    def _cls_qual(self) -> str:
        return self.fn_stack[-1].cls_qual if self.fn_stack else ""

    # -- 문 순회 --------------------------------------------------------------

    def _walk_body(self, body: "list[ast.stmt]", *, module_level: bool) -> None:
        for stmt in body:
            self._walk_stmt(stmt, module_level=module_level)

    def _walk_stmt(self, stmt: ast.stmt, *, module_level: bool) -> None:
        in_class_body = bool(self.class_stack) and not self.fn_stack
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._scan_exprs(
                [
                    *stmt.decorator_list,
                    *stmt.args.defaults,
                    *[d for d in stmt.args.kw_defaults if d is not None],
                ],
                module_level=module_level,
            )
            self._walk_function(stmt)
            return
        if isinstance(stmt, ast.ClassDef):
            self._scan_exprs(
                [*stmt.decorator_list, *stmt.bases, *[k.value for k in stmt.keywords]],
                module_level=module_level,
            )
            qualname = ".".join([*self.qual_prefix, stmt.name])
            self.class_stack.append(qualname)
            self.class_dataclassish.append(_is_dataclassish(stmt))
            self.qual_prefix.append(stmt.name)
            self._walk_body(stmt.body, module_level=False)
            self.qual_prefix.pop()
            self.class_dataclassish.pop()
            self.class_stack.pop()
            return
        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            self._handle_assign_stmt(stmt, module_level=module_level, in_class_body=in_class_body)
            exprs: list[ast.expr] = []
            if isinstance(stmt, ast.Assign):
                exprs = [*stmt.targets, stmt.value]
            elif isinstance(stmt, ast.AugAssign):
                exprs = [stmt.target, stmt.value]
            else:
                exprs = [stmt.target] + ([stmt.value] if stmt.value is not None else [])
            self._scan_exprs(exprs, module_level=module_level)
            return
        if isinstance(stmt, ast.Delete):
            self._handle_delete(stmt, module_level=module_level, in_class_body=in_class_body)
            self._scan_exprs(list(stmt.targets), module_level=module_level)
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._scan_exprs([stmt.target, stmt.iter], module_level=module_level)
            self._walk_body(stmt.body, module_level=module_level)
            self._walk_body(stmt.orelse, module_level=module_level)
            return
        if isinstance(stmt, ast.While):
            self._scan_exprs([stmt.test], module_level=module_level)
            self._walk_body(stmt.body, module_level=module_level)
            self._walk_body(stmt.orelse, module_level=module_level)
            return
        if isinstance(stmt, ast.If):
            self._scan_exprs([stmt.test], module_level=module_level)
            self._walk_body(stmt.body, module_level=module_level)
            self._walk_body(stmt.orelse, module_level=module_level)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            items: list[ast.expr] = []
            for item in stmt.items:
                items.append(item.context_expr)
                if item.optional_vars is not None:
                    items.append(item.optional_vars)
            self._scan_exprs(items, module_level=module_level)
            self._walk_body(stmt.body, module_level=module_level)
            return
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            self._walk_body(stmt.body, module_level=module_level)
            for handler in stmt.handlers:
                if handler.type is not None:
                    self._scan_exprs([handler.type], module_level=module_level)
                self._walk_body(handler.body, module_level=module_level)
            self._walk_body(stmt.orelse, module_level=module_level)
            self._walk_body(stmt.finalbody, module_level=module_level)
            return
        if isinstance(stmt, ast.Match):
            self._scan_exprs([stmt.subject], module_level=module_level)
            for case in stmt.cases:
                self._walk_body(case.body, module_level=module_level)
            return
        exprs = [
            child for child in ast.iter_child_nodes(stmt) if isinstance(child, ast.expr)
        ]
        if exprs:
            self._scan_exprs(exprs, module_level=module_level)

    def _walk_function(self, node: "ast.FunctionDef | ast.AsyncFunctionDef") -> None:
        qualname = ".".join([*self.qual_prefix, node.name])
        in_class = bool(self.class_stack) and not self.fn_stack
        kind = "method" if in_class else "function"
        sym = self.index.get((self.mf.module, qualname))
        sid = sym.id if sym is not None else symbol_id(self.mf.module, qualname, kind)
        args = node.args
        params = [
            a.arg
            for a in [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
            if a is not None
        ]
        is_static = in_class and any(
            isinstance(dec, ast.Name) and dec.id == "staticmethod"
            for dec in node.decorator_list
        )
        first = params[0] if params and in_class and not is_static else ""
        global_decls: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Global):
                global_decls.update(sub.names)
        scope = _Scope(
            sid=sid,
            first_param=first,
            cls_qual=self.class_stack[-1] if in_class else self._cls_qual(),
            local_names=set(params) | _function_local_names(node.body),
            global_decls=global_decls,
            root_types=_function_root_types(
                node, self.mf, self.index, self.class_basenames
            ),
        )
        self.fn_stack.append(scope)
        self.qual_prefix.extend([node.name, "<locals>"])
        outer_classes, self.class_stack = self.class_stack, []
        self._walk_body(node.body, module_level=False)
        self.class_stack = outer_classes
        self.qual_prefix = self.qual_prefix[:-2]
        self.fn_stack.pop()

    # -- 할당·삭제 -------------------------------------------------------------

    def _handle_assign_stmt(
        self,
        stmt: "ast.Assign | ast.AnnAssign | ast.AugAssign",
        *,
        module_level: bool,
        in_class_body: bool,
    ) -> None:
        if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
            if in_class_body and isinstance(stmt.target, ast.Name):
                cls = self.class_stack[-1]
                self._emit(
                    "writes_attribute",
                    f"attr:{self.mf.module}:{cls}.{stmt.target.id}",
                    "INFERRED",
                    stmt,
                    "class_field_declaration",
                    syntax_site_anchor(stmt.target),
                )
            return
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in _flat_targets(targets):
            if isinstance(target, ast.Name):
                if module_level:
                    self._emit(
                        "writes_attribute",
                        f"attr:{self.mf.module}:{target.id}",
                        "STATIC_CONFIRMED",
                        stmt,
                        "module_global_assign",
                        syntax_site_anchor(target),
                    )
                elif in_class_body:
                    cls = self.class_stack[-1]
                    self._emit(
                        "writes_attribute",
                        f"attr:{self.mf.module}:{cls}.{target.id}",
                        "STATIC_CONFIRMED",
                        stmt,
                        "class_attr_assign",
                        syntax_site_anchor(target),
                    )
                    if (
                        isinstance(stmt, ast.AnnAssign)
                        and self.class_dataclassish
                        and self.class_dataclassish[-1]
                    ):
                        # dataclass 의 annotation 필드는 합성 생성자가 인스턴스에 쓴다 —
                        # 클래스 네임스페이스 기본값과 별개로 필드 선언 사실을 함께 남긴다.
                        self._emit(
                            "writes_attribute",
                            f"attr:{self.mf.module}:{cls}.{target.id}",
                            "INFERRED",
                            stmt,
                            "class_field_declaration",
                            syntax_site_anchor(target),
                        )
                # 함수 지역 재결속은 상태가 아니고, global 선언 재결속은 기반이 이미 낸다.
            elif isinstance(target, ast.Subscript):
                self._emit_subscript_mutation(target, stmt)
            # Attribute target 재결속은 기반 attr_assign 이 이미 전수로 낸다(중복 금지).

    def _handle_delete(
        self, stmt: ast.Delete, *, module_level: bool, in_class_body: bool
    ) -> None:
        for target in stmt.targets:
            if isinstance(target, ast.Subscript):
                self._emit_subscript_mutation(target, stmt)
            elif isinstance(target, ast.Attribute):
                owner = self._attribute_owner(target)
                if owner is not None:
                    self._emit(
                        "writes_attribute",
                        f"attr:{owner}.{target.attr}",
                        "STATIC_CONFIRMED",
                        stmt,
                        "attr_delete",
                        syntax_site_anchor(target),
                    )
                else:
                    self._emit(
                        "writes_attribute",
                        f"?:attr:{_short(target.value)}.{target.attr}",
                        "UNKNOWN",
                        stmt,
                        "attr_delete_opaque",
                        syntax_site_anchor(target),
                    )
            elif isinstance(target, ast.Name):
                if module_level:
                    self._emit(
                        "writes_attribute",
                        f"attr:{self.mf.module}:{target.id}",
                        "STATIC_CONFIRMED",
                        stmt,
                        "module_global_delete",
                        syntax_site_anchor(target),
                    )
                elif in_class_body:
                    cls = self.class_stack[-1]
                    self._emit(
                        "writes_attribute",
                        f"attr:{self.mf.module}:{cls}.{target.id}",
                        "STATIC_CONFIRMED",
                        stmt,
                        "class_attr_delete",
                        syntax_site_anchor(target),
                    )

    def _emit_subscript_mutation(self, target: ast.Subscript, stmt: ast.stmt) -> None:
        anchor = syntax_site_anchor(target)
        container = target.value
        dst, grade, rule = self._container_coordinate(container, shadow=frozenset())
        self._emit("mutates_attribute", dst, grade, stmt, rule, anchor)

    # -- 식 순회(변이 메서드 호출·읽기) ------------------------------------------

    def _scan_exprs(self, exprs: "list[ast.expr]", *, module_level: bool) -> None:
        for expr in exprs:
            shadow = frozenset(_expression_shadow_names(expr))
            call_funcs = {
                id(node.func) for node in ast.walk(expr) if isinstance(node, ast.Call)
            }
            for node in ast.walk(expr):
                if isinstance(node, ast.Call):
                    self._handle_call(node, shadow)
                elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                    if module_level:
                        self._emit(
                            "writes_attribute",
                            f"attr:{self.mf.module}:{node.target.id}",
                            "STATIC_CONFIRMED",
                            node,
                            "module_global_assign",
                            syntax_site_anchor(node.target),
                        )
                    elif self.class_stack and not self.fn_stack:
                        cls = self.class_stack[-1]
                        self._emit(
                            "writes_attribute",
                            f"attr:{self.mf.module}:{cls}.{node.target.id}",
                            "STATIC_CONFIRMED",
                            node,
                            "class_attr_assign",
                            syntax_site_anchor(node.target),
                        )
                elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                    if id(node) in call_funcs:
                        continue  # 메서드 호출 수신 좌표는 call/mutates 사실이 든다
                    self._handle_attribute_read(node, shadow)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if id(node) in call_funcs:
                        continue
                    self._handle_name_read(node, shadow)

    def _handle_call(self, node: ast.Call, shadow: "frozenset[str]") -> None:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in MUTATOR_METHODS:
            return
        anchor = call_site_anchor(node)
        receiver = func.value
        first = self._first_param()
        if isinstance(receiver, ast.Name) and receiver.id == first and first:
            # 자기 수신 변이 메서드 — 자기 클래스가 그 이름을 직접 정의하면 일반 호출이라
            # 기반 calls 사실이 들고, 아니면 상속 컨테이너 변이 후보로 남긴다.
            cls = self._cls_qual()
            if self.index.get((self.mf.module, f"{cls}.{func.attr}")) is not None:
                return
            self._emit(
                "mutates_attribute",
                f"?:self:{cls}.{func.attr}",
                "UNKNOWN",
                node,
                "mutcall_receiver_self",
                anchor,
            )
            return
        dst, grade, rule_suffix = self._container_coordinate(receiver, shadow)
        rule = {
            "subscript_mutation_self": "mutcall_self_attribute",
            "subscript_mutation_class": "mutcall_class_attr",
            "subscript_mutation_global": "mutcall_module_global",
            "subscript_mutation_typed": "mutcall_typed_attribute",
            "subscript_mutation_local": "mutcall_local_binding",
            "subscript_mutation_opaque": _opaque_mutcall_rule(receiver),
        }[rule_suffix]
        if grade == "STATIC_CONFIRMED":
            grade = "INFERRED"  # 변이 메서드 가족은 이름 기반 — 상한 INFERRED(모듈 docstring)
        self._emit("mutates_attribute", dst, grade, node, rule, anchor)

    def _container_coordinate(
        self, container: ast.expr, shadow: "frozenset[str]"
    ) -> "tuple[str, str, str]":
        """컨테이너 식 → (dst, grade, subscript_mutation_* rule). mutcall 은 rule 만 바꾼다."""
        first = self._first_param()
        if (
            isinstance(container, ast.Attribute)
            and isinstance(container.value, ast.Name)
            and container.value.id == first
            and first
            and container.value.id not in shadow
        ):
            cls = self._cls_qual()
            return (
                f"attr:{self.mf.module}:{cls}.{container.attr}",
                "STATIC_CONFIRMED",
                "subscript_mutation_self",
            )
        if isinstance(container, ast.Attribute) and isinstance(container.value, ast.Name):
            root = container.value.id
            typed = self._root_type(root, shadow)
            if typed is not None:
                module, qual, _kind = parse_symbol_id(typed)
                return (
                    f"attr:{module}:{qual}.{container.attr}",
                    "INFERRED",
                    "subscript_mutation_typed",
                )
            return (
                f"?:attr:{root}.{container.attr}",
                "UNKNOWN",
                "subscript_mutation_opaque",
            )
        if isinstance(container, ast.Name):
            name = container.id
            if name in shadow or self._is_local(name):
                return (f"?:local:{name}", "UNKNOWN", "subscript_mutation_local")
            if self.class_stack and not self.fn_stack:
                cls = self.class_stack[-1]
                return (
                    f"attr:{self.mf.module}:{cls}.{name}",
                    "STATIC_CONFIRMED",
                    "subscript_mutation_class",
                )
            if name in self.module_globals:
                return (
                    f"attr:{self.mf.module}:{name}",
                    "STATIC_CONFIRMED",
                    "subscript_mutation_global",
                )
            if name in self.module_imports:
                # import 로 들어온 이름 — 소유 모듈을 지역 표기로 꾸미지 않는다(수명 오귀속 방지).
                return (f"?:name:{name}", "UNKNOWN", "subscript_mutation_opaque")
            if self.fn_stack:
                # 지역·클로저 이름(타입을 알아도 인스턴스 자체가 컨테이너라 필드 좌표가 아니다).
                return (f"?:local:{name}", "UNKNOWN", "subscript_mutation_local")
            return (f"?:name:{name}", "UNKNOWN", "subscript_mutation_opaque")
        return (f"?:expr:{_short(container)}", "UNKNOWN", "subscript_mutation_opaque")

    def _handle_attribute_read(self, node: ast.Attribute, shadow: "frozenset[str]") -> None:
        first = self._first_param()
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == first
            and first
            and node.value.id not in shadow
        ):
            cls = self._cls_qual()
            self._emit(
                "reads_attribute",
                f"attr:{self.mf.module}:{cls}.{node.attr}",
                "STATIC_CONFIRMED",
                node,
                "attr_read_self",
                syntax_site_anchor(node),
            )
            return
        if isinstance(node.value, ast.Name):
            typed = self._root_type(node.value.id, shadow)
            if typed is not None:
                module, qual, _kind = parse_symbol_id(typed)
                self._emit(
                    "reads_attribute",
                    f"attr:{module}:{qual}.{node.attr}",
                    "INFERRED",
                    node,
                    "attr_read_typed",
                    syntax_site_anchor(node),
                )
        # 그 밖의 속성 읽기는 소유자를 정적으로 못 닫는다 — 사실로 적지 않는 정직한 경계.

    def _handle_name_read(self, node: ast.Name, shadow: "frozenset[str]") -> None:
        if self.mutated_globals is None:
            return  # 1패스 — 변이 전역 집합이 아직 없다
        name = node.id
        if name not in self.mutated_globals or name not in self.module_globals:
            return
        if name in shadow:
            return
        if self.fn_stack:
            scope = self.fn_stack[-1]
            if name in scope.local_names and name not in scope.global_decls:
                return
        self._emit(
            "reads_attribute",
            f"attr:{self.mf.module}:{name}",
            "STATIC_CONFIRMED",
            node,
            "global_read",
            syntax_site_anchor(node),
        )

    # -- 해석 보조 -------------------------------------------------------------

    def _is_local(self, name: str) -> bool:
        if not self.fn_stack:
            return False
        scope = self.fn_stack[-1]
        return name in scope.local_names and name not in scope.global_decls

    def _root_type(self, name: str, shadow: "frozenset[str]") -> "str | None":
        if name in shadow or not self.fn_stack:
            return None
        return self.fn_stack[-1].root_types.get(name)

    def _attribute_owner(self, node: ast.Attribute) -> "str | None":
        first = self._first_param()
        if isinstance(node.value, ast.Name) and node.value.id == first and first:
            return f"{self.mf.module}:{self._cls_qual()}"
        return None


def collect_state_facts(
    repo_root: Path,
    closure: "Closure | None" = None,
    symbols: "tuple[Symbol, ...] | None" = None,
    base_facts: "tuple[Fact, ...] | None" = None,
) -> tuple[Fact, ...]:
    """상태 축 파생 사실 전수 — 2패스(변이 수집 → 변이 전역의 읽기 수집) 결정론."""
    repo_root = Path(repo_root)
    closure = closure or production_closure(repo_root)
    symbols = symbols if symbols is not None else collect_symbols(repo_root, closure)
    index = {(s.module, s.qualname): s for s in symbols}
    class_basenames = _unique_class_basenames(symbols)
    trees = {
        mf.module: ast.parse((repo_root / mf.path).read_text(encoding="utf-8"), filename=mf.path)
        for mf in closure.modules
    }
    facts: list[Fact] = []
    for mf in closure.modules:
        walker = _StateWalker(mf, trees[mf.module], index, class_basenames, None)
        facts.extend(walker.run())

    mutated_by_module: dict[str, set[str]] = {}
    rebind_rules = {"global_rebind"}
    for fact in [*facts, *(base_facts or ())]:
        if fact.dst.startswith("attr:") and (
            fact.rel == "mutates_attribute" or fact.provenance.rule in rebind_rules
        ):
            body = fact.dst.removeprefix("attr:")
            module, sep, qual = body.partition(":")
            if sep and qual and "." not in qual:
                mutated_by_module.setdefault(module, set()).add(qual)
    for mf in closure.modules:
        mutated = frozenset(mutated_by_module.get(mf.module, set()))
        if not mutated:
            continue
        walker = _StateWalker(mf, trees[mf.module], index, class_basenames, mutated)
        facts.extend(
            fact for fact in walker.run() if fact.provenance.rule == "global_read"
        )
    return tuple(sorted(set(facts), key=Fact.sort_key))


def _flat_targets(targets: "list[ast.expr]") -> "list[ast.expr]":
    out: list[ast.expr] = []
    stack = list(targets)
    while stack:
        t = stack.pop()
        if isinstance(t, (ast.Tuple, ast.List)):
            stack.extend(t.elts)
        elif isinstance(t, ast.Starred):
            stack.append(t.value)
        else:
            out.append(t)
    return out


def _module_level_bound_names(tree: ast.Module) -> frozenset[str]:
    """모듈 수준(중첩 블록 포함, def/class 본문 제외)에서 할당으로 묶이는 이름."""
    names: set[str] = set()

    def visit(body: "list[ast.stmt]") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in _flat_targets(list(targets)):
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                for t in _flat_targets([node.target]):
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            for block in _statement_blocks(node):
                visit(block)

    visit(tree.body)
    return frozenset(names)


def _function_local_names(body: "list[ast.stmt]") -> set[str]:
    names: set[str] = set()

    def visit(stmts: "list[ast.stmt]") -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
                continue
            for node in ast.walk(stmt):
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in _flat_targets(list(targets)):
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    for t in _flat_targets([node.target]):
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        if item.optional_vars is not None:
                            for t in _flat_targets([item.optional_vars]):
                                if isinstance(t, ast.Name):
                                    names.add(t.id)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    names.add(node.name)
                elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        if alias.name != "*":
                            names.add(alias.asname or alias.name.split(".", 1)[0])

    visit(body)
    return names


def _module_level_import_names(tree: ast.Module) -> frozenset[str]:
    """모듈 수준(중첩 블록 포함, def/class 본문 제외) import 가 묶는 이름."""
    names: set[str] = set()

    def visit(body: "list[ast.stmt]") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name != "*":
                        names.add(alias.asname or alias.name.split(".", 1)[0])
            for block in _statement_blocks(node):
                visit(block)

    visit(tree.body)
    return frozenset(names)


def _is_dataclassish(node: ast.ClassDef) -> bool:
    """데코레이터 leaf 이름이 ``dataclass`` 인가 — annotation 필드의 합성 생성자 쓰기 판별."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute):
            leaf = target.attr
        elif isinstance(target, ast.Name):
            leaf = target.id
        else:
            leaf = ""
        if leaf == "dataclass":
            return True
    return False


def _expression_shadow_names(expr: ast.expr) -> set[str]:
    """식 안 lambda 매개변수·comprehension 표적 — 보수적 subtree-전역 가림."""
    names: set[str] = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.Lambda):
            args = node.args
            names.update(
                a.arg
                for a in [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
                if a is not None
            )
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in node.generators:
                for t in _flat_targets([generator.target]):
                    if isinstance(t, ast.Name):
                        names.add(t.id)
    return names


def _unique_class_basenames(symbols: tuple[Symbol, ...]) -> "dict[str, str]":
    """폐포 전역에서 basename 이 유일한 클래스만 — 겹치면 해석하지 않는다(임의 추측 금지)."""
    seen: dict[str, list[str]] = {}
    for s in symbols:
        if s.kind != "class":
            continue
        base = s.qualname.rsplit(".", 1)[-1]
        seen.setdefault(base, []).append(s.id)
    return {base: sids[0] for base, sids in seen.items() if len(sids) == 1}


def _annotation_class_name(annotation: ast.expr) -> "str | None":
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        text = annotation.value
    else:
        try:
            text = ast.unparse(annotation)
        except Exception:  # noqa: BLE001 — 못 읽는 annotation 은 해석 포기가 정직하다
            return None
    text = text.strip().strip("'\"")
    candidates = [part.strip() for part in text.split("|")]
    candidates = [part for part in candidates if part and part != "None"]
    if len(candidates) != 1:
        return None
    name = candidates[0].split("[", 1)[0].strip()
    if not name or not name.replace(".", "").replace("_", "").isalnum():
        return None
    return name.rsplit(".", 1)[-1]


def _function_root_types(
    node: "ast.FunctionDef | ast.AsyncFunctionDef",
    mf: ModuleFile,
    index: "dict[tuple[str, str], Symbol]",
    class_basenames: "dict[str, str]",
) -> "dict[str, str]":
    """이름 → 유일 클래스 SID. 매개변수 annotation·유일 생성자 결속만 믿고, 재결속은 오염."""

    def resolve(name: str) -> "str | None":
        local = index.get((mf.module, name))
        if local is not None and local.kind == "class":
            return local.id
        return class_basenames.get(name)

    bindings: dict[str, list[str | None]] = {}
    args = node.args
    for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        resolved: str | None = None
        if a.annotation is not None:
            ann_name = _annotation_class_name(a.annotation)
            if ann_name is not None:
                resolved = resolve(ann_name)
        bindings.setdefault(a.arg, []).append(resolved)
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            bindings.setdefault(extra.arg, []).append(None)

    def visit(stmts: "list[ast.stmt]") -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.setdefault(stmt.name, []).append(None)
                continue
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Assign):
                    for t in _flat_targets(list(sub.targets)):
                        if not isinstance(t, ast.Name):
                            continue
                        resolved = None
                        if (
                            isinstance(sub.value, ast.Call)
                            and isinstance(sub.value.func, ast.Name)
                        ):
                            resolved = resolve(sub.value.func.id)
                        bindings.setdefault(t.id, []).append(resolved)
                elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
                    for t in _flat_targets([sub.target]):
                        if isinstance(t, ast.Name):
                            bindings.setdefault(t.id, []).append(None)
                elif isinstance(sub, (ast.For, ast.AsyncFor)):
                    for t in _flat_targets([sub.target]):
                        if isinstance(t, ast.Name):
                            bindings.setdefault(t.id, []).append(None)
                elif isinstance(sub, (ast.With, ast.AsyncWith)):
                    for item in sub.items:
                        if item.optional_vars is not None:
                            for t in _flat_targets([item.optional_vars]):
                                if isinstance(t, ast.Name):
                                    bindings.setdefault(t.id, []).append(None)
                elif isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name):
                    bindings.setdefault(sub.target.id, []).append(None)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        if alias.name != "*":
                            bindings.setdefault(
                                alias.asname or alias.name.split(".", 1)[0], []
                            ).append(None)

    visit(node.body)
    return {
        name: entries[0]
        for name, entries in bindings.items()
        if len(entries) == 1 and entries[0] is not None
    }


def _opaque_mutcall_rule(receiver: ast.expr) -> str:
    if isinstance(receiver, ast.Attribute):
        return "mutcall_attribute_opaque"
    return "mutcall_opaque"


def _short(node: ast.AST) -> str:
    try:
        return ast.unparse(node).replace("\r", " ").replace("\n", " ")[:60]
    except Exception:  # noqa: BLE001 — 진단 좌표는 형태 이름으로 대체한다
        return type(node).__name__


def _statement_blocks(node: ast.stmt) -> "list[list[ast.stmt]]":
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
# 상태·거래·공유 조인
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateRow:
    state_id: str
    storage: str  # "module_global" | "class_attr" | "instance_field"
    declared_only: bool
    writers: tuple[str, ...]
    mutators: tuple[str, ...]
    readers: tuple[str, ...]
    sync: tuple[str, ...]


@dataclass(frozen=True)
class TransactionCluster:
    src: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class SharedState:
    state_id: str
    units: tuple[str, ...]


@dataclass(frozen=True)
class SyncSite:
    kind: str
    state_id: str  # 결부 좌표를 못 찾으면 "?:unbound"
    file: str
    line: int


@dataclass
class StateGraphResult:
    static: static_graph.StaticGraphResult
    state_facts: tuple[Fact, ...]
    state_digest: str
    full_digest: str
    states: tuple[StateRow, ...]
    clusters: tuple[TransactionCluster, ...]
    shared: tuple[SharedState, ...]
    sync_sites: tuple[SyncSite, ...]
    inherited_queue: int
    inherited_queue_site_covered: int


_INSTANCE_RULES = frozenset(
    {
        "attr_assign",
        "setattr_literal",
        "delattr_literal",
        "class_field_declaration",
        "subscript_mutation_self",
        "subscript_mutation_typed",
        "mutcall_self_attribute",
        "mutcall_typed_attribute",
        "attr_delete",
    }
)
_CLASS_RULES = frozenset(
    {"class_attr_assign", "class_attr_delete", "subscript_mutation_class", "mutcall_class_attr"}
)


def _resolved_attr_coordinate(dst: str) -> "tuple[str, str] | None":
    """``attr:{module}:{qual}`` → (module, qual). 미해결(?:)·형식 밖은 None."""
    if not dst.startswith("attr:"):
        return None
    body = dst.removeprefix("attr:")
    if body.startswith("?"):
        return None
    module, sep, qual = body.partition(":")
    if not sep or not module or not qual:
        return None
    return module, qual


def _writer_unit(src: str, index: "dict[tuple[str, str], Symbol]") -> str:
    module, qual, kind = parse_symbol_id(src)
    if qual:
        top = qual.split(".", 1)[0]
        top_symbol = index.get((module, top))
        if top_symbol is not None and top_symbol.kind == "class":
            return f"{module}:{top}"
    return module


def build_state(repo_root: Path) -> StateGraphResult:
    repo_root = Path(repo_root)
    static_result = static_graph.build(repo_root)
    closure = static_result.closure
    symbols = static_result.symbols
    index = {(s.module, s.qualname): s for s in symbols}
    state_facts = collect_state_facts(
        repo_root, closure, symbols, base_facts=static_result.base_facts
    )
    symbol_ids = [s.id for s in symbols]
    state_digest = facts_digest(symbol_ids, state_facts)
    full_digest = facts_digest(symbol_ids, [*static_result.facts, *state_facts])

    all_state_facts = [
        *state_facts,
        *(
            f
            for f in static_result.base_facts
            if f.rel in ("writes_attribute", "reads_attribute")
        ),
    ]
    writers: dict[str, set[str]] = {}
    mutators: dict[str, set[str]] = {}
    readers: dict[str, set[str]] = {}
    rules_by_state: dict[str, set[str]] = {}
    for fact in all_state_facts:
        coord = _resolved_attr_coordinate(fact.dst)
        if coord is None:
            continue
        state_id = fact.dst
        rules_by_state.setdefault(state_id, set()).add(fact.provenance.rule)
        if fact.rel == "writes_attribute":
            writers.setdefault(state_id, set()).add(fact.src)
        elif fact.rel == "mutates_attribute":
            mutators.setdefault(state_id, set()).add(fact.src)
        elif fact.rel == "reads_attribute":
            readers.setdefault(state_id, set()).add(fact.src)

    sync_sites: list[SyncSite] = []
    sync_by_state: dict[str, set[str]] = {}
    write_sites: dict[tuple[str, int], set[str]] = {}
    for fact in all_state_facts:
        if fact.rel == "writes_attribute" and _resolved_attr_coordinate(fact.dst):
            write_sites.setdefault((fact.evidence.file, fact.evidence.line), set()).add(fact.dst)
    for fact in static_result.base_facts:
        if fact.rel != "calls" or not fact.dst.startswith(_THREADING_PREFIX):
            continue
        kind = fact.dst.removeprefix(_THREADING_PREFIX)
        if kind not in SYNC_PRIMITIVES:
            continue
        bound = sorted(write_sites.get((fact.evidence.file, fact.evidence.line), set()))
        if bound:
            for state_id in bound:
                sync_by_state.setdefault(state_id, set()).add(kind)
                sync_sites.append(
                    SyncSite(kind, state_id, fact.evidence.file, fact.evidence.line)
                )
        else:
            sync_sites.append(
                SyncSite(kind, "?:unbound", fact.evidence.file, fact.evidence.line)
            )
    sync_sites.sort(key=lambda s: (s.file, s.line, s.kind, s.state_id))

    state_ids = sorted(set(writers) | set(mutators))
    rows: list[StateRow] = []
    for state_id in state_ids:
        rules = rules_by_state.get(state_id, set())
        coord = _resolved_attr_coordinate(state_id)
        assert coord is not None  # state_ids 는 해석 좌표만 든다
        _module, qual = coord
        if "." not in qual:
            storage = "module_global"
        elif rules & _INSTANCE_RULES:
            storage = "instance_field"
        elif rules & _CLASS_RULES:
            storage = "class_attr"
        else:
            storage = "instance_field"
        read_rules = {
            "attr_read_self",
            "attr_read_typed",
            "global_read",
            "getattr_literal",
            "hasattr_literal",
        }
        declared_only = (rules - read_rules) == {"class_field_declaration"}
        rows.append(
            StateRow(
                state_id=state_id,
                storage=storage,
                declared_only=declared_only,
                writers=tuple(sorted(writers.get(state_id, set()))),
                mutators=tuple(sorted(mutators.get(state_id, set()))),
                readers=tuple(sorted(readers.get(state_id, set()))),
                sync=tuple(sorted(sync_by_state.get(state_id, set()))),
            )
        )

    per_src: dict[str, set[str]] = {}
    for fact in all_state_facts:
        if fact.rel not in ("writes_attribute", "mutates_attribute"):
            continue
        if _resolved_attr_coordinate(fact.dst) is None:
            continue
        kind = parse_symbol_id(fact.src)[2]
        if kind not in ("function", "method"):
            continue  # 모듈/클래스 src 는 import 시점 초기화 — 실행 거래가 아니다
        per_src.setdefault(fact.src, set()).add(fact.dst)
    clusters = tuple(
        TransactionCluster(src=src, members=tuple(sorted(members)))
        for src, members in sorted(per_src.items())
        if len(members) >= 2
    )

    shared: list[SharedState] = []
    for row in rows:
        units = {
            _writer_unit(src, index) for src in [*row.writers, *row.mutators]
        }
        if len(units) >= 2:
            shared.append(SharedState(state_id=row.state_id, units=tuple(sorted(units))))
    shared.sort(key=lambda s: s.state_id)

    inherited = [
        fact
        for fact in static_graph.unresolved_facts(static_result)
        if "02B" in static_graph.followup_of(fact.provenance.rule)
    ]
    covered_sites = {
        (f.evidence.file, f.evidence.line)
        for f in state_facts
        if _resolved_attr_coordinate(f.dst) is not None
    }
    inherited_covered = sum(
        1 for f in inherited if (f.evidence.file, f.evidence.line) in covered_sites
    )

    return StateGraphResult(
        static=static_result,
        state_facts=state_facts,
        state_digest=state_digest,
        full_digest=full_digest,
        states=tuple(rows),
        clusters=clusters,
        shared=tuple(shared),
        sync_sites=tuple(sync_sites),
        inherited_queue=len(inherited),
        inherited_queue_site_covered=inherited_covered,
    )


def state_shard(repo_root: Path) -> Shard:
    """P1-03 merge 입력용 shard — 02A shard 와 같은 baseline 을 들어야 merge 가 받는다.

    ``global_read`` 는 기반 사실(global rebind)에 의존하므로 기반 수집을 여기서도 돌려
    ``build_state`` 와 같은 사실 집합이 나오게 한다(두 입구의 digest 가 갈리면 안 된다).
    """
    repo_root = Path(repo_root)
    closure = production_closure(repo_root)
    symbols = collect_symbols(repo_root, closure)
    base = collect_facts(repo_root, closure, symbols)
    facts = collect_state_facts(repo_root, closure, symbols, base_facts=base)
    return make_shard(
        "state-02b",
        COLLECTOR,
        static_graph.BASELINE_SHA,
        [s.id for s in symbols],
        list(facts),
    )


# ---------------------------------------------------------------------------
# 「미수집 0」 오러클 — 독립 AST 분모
# ---------------------------------------------------------------------------


def _oracle_anchor(node: ast.AST) -> str:
    """수집기와 별도로 재구성하는 앵커 — 같은 줄 두 사이트의 거짓 초록을 막는다."""
    try:
        text = ast.unparse(node).replace("\r", " ").replace("\n", " ")[:120]
    except Exception:  # noqa: BLE001 — 진단 좌표는 형태 이름으로 대체한다
        text = type(node).__name__
    start = getattr(node, "col_offset", -1)
    end = getattr(node, "end_col_offset", -1)
    return f"c{start}-{end}:{text}"


def uncovered_state_sites(
    repo_root: Path, closure: Closure, facts: "tuple[Fact, ...] | list[Fact]"
) -> "list[str]":
    """폐포의 모든 상태 변이·self 읽기 좌표에 사실이 최소 1건 앉아 있는가.

    분모는 이 함수가 소스에서 독립 재열거한다: 속성/subscript 표적 할당·삭제, 모듈 전역·
    클래스 본문 이름 할당, annotation 필드 선언, 변이 메서드 호출, self 속성 읽기.
    사실 인덱스는 (file, line) 또는 (file, line, anchor) 로 대조하고, 좌표가 결정적인
    분모(모듈 전역·클래스 속성·self)는 dst 일치까지 요구해 「아무 사실 한 건」의 거짓
    초록을 좁힌다.
    """
    writes_by_line: dict[tuple[str, int], set[str]] = {}
    mutates_by_anchor: dict[tuple[str, int, str], int] = {}
    reads_by_line: dict[tuple[str, int], set[str]] = {}
    for fact in facts:
        key = (fact.evidence.file, fact.evidence.line)
        if fact.rel == "writes_attribute":
            writes_by_line.setdefault(key, set()).add(fact.dst)
        elif fact.rel == "mutates_attribute":
            mutates_by_anchor[(*key, fact.evidence.anchor)] = (
                mutates_by_anchor.get((*key, fact.evidence.anchor), 0) + 1
            )
        elif fact.rel == "reads_attribute":
            reads_by_line.setdefault(key, set()).add(fact.dst)

    problems: list[str] = []

    for mf in closure.modules:
        tree = ast.parse((Path(repo_root) / mf.path).read_text(encoding="utf-8"), filename=mf.path)
        _OracleWalker(mf, tree, writes_by_line, mutates_by_anchor, reads_by_line, problems).run()
    return sorted(set(problems))


class _OracleWalker:
    """방출 walker 와 별도 구현 — 규칙을 공유하면 같은 구멍이 양쪽에 나 초록이 된다."""

    def __init__(
        self,
        mf: ModuleFile,
        tree: ast.Module,
        writes_by_line: "dict[tuple[str, int], set[str]]",
        mutates_by_anchor: "dict[tuple[str, int, str], int]",
        reads_by_line: "dict[tuple[str, int], set[str]]",
        problems: "list[str]",
    ) -> None:
        self.mf = mf
        self.tree = tree
        self.writes = writes_by_line
        self.mutates = mutates_by_anchor
        self.reads = reads_by_line
        self.problems = problems
        self.class_stack: list[str] = []
        self.first_params: list[str] = []
        self.method_cls: list[str] = []  # 함수별 정의 시점 클래스 좌표(메서드가 아니면 "")
        self.qual_prefix: list[str] = []
        self.class_methods = _lexical_class_methods(tree)

    def run(self) -> None:
        self._body(self.tree.body, module_level=True)

    # -- 대조 -----------------------------------------------------------------

    def _need_write(self, node: ast.AST, dst: "str | None", leaf: "str | None", what: str) -> None:
        key = (self.mf.path, getattr(node, "lineno", 0))
        found = self.writes.get(key, set())
        if dst is not None and dst in found:
            return
        if dst is None and leaf is not None and any(d.endswith(f".{leaf}") for d in found):
            return
        self.problems.append(
            f"{self.mf.path}:{getattr(node, 'lineno', 0)} {what} 에 writes 사실이 없다"
            f" (기대 {dst or leaf})"
        )

    def _need_mutation(self, node: ast.AST, anchor_node: ast.AST, what: str) -> None:
        key = (self.mf.path, getattr(node, "lineno", 0), _oracle_anchor(anchor_node))
        if key not in self.mutates:
            self.problems.append(
                f"{self.mf.path}:{getattr(node, 'lineno', 0)} {what} 에 mutates 사실이 없다"
                f" ({key[2]})"
            )

    def _need_read(self, node: ast.Attribute, cls_qual: str) -> None:
        key = (self.mf.path, node.lineno)
        expected = f"attr:{self.mf.module}:{cls_qual}.{node.attr}"
        if expected not in self.reads.get(key, set()):
            self.problems.append(
                f"{self.mf.path}:{node.lineno} self 읽기 {node.attr!r} 에 reads 사실이 없다"
            )

    # -- 순회 -----------------------------------------------------------------

    def _body(self, body: "list[ast.stmt]", *, module_level: bool) -> None:
        for stmt in body:
            self._stmt(stmt, module_level=module_level)

    def _stmt(self, stmt: ast.stmt, *, module_level: bool) -> None:
        in_class_body = bool(self.class_stack) and not self.first_params
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._exprs(
                [
                    *stmt.decorator_list,
                    *stmt.args.defaults,
                    *[d for d in stmt.args.kw_defaults if d is not None],
                ]
            )
            args = stmt.args
            params = [a.arg for a in [*args.posonlyargs, *args.args]]
            is_static = in_class_body and any(
                isinstance(dec, ast.Name) and dec.id == "staticmethod"
                for dec in stmt.decorator_list
            )
            first = params[0] if params and in_class_body and not is_static else ""
            self.first_params.append(first)
            self.method_cls.append(self.class_stack[-1] if in_class_body else "")
            self.qual_prefix.extend([stmt.name, "<locals>"])
            outer, self.class_stack = self.class_stack, []
            self._body(stmt.body, module_level=False)
            self.class_stack = outer
            self.qual_prefix = self.qual_prefix[:-2]
            self.method_cls.pop()
            self.first_params.pop()
            return
        if isinstance(stmt, ast.ClassDef):
            self._exprs([*stmt.decorator_list, *stmt.bases, *[k.value for k in stmt.keywords]])
            qualname = ".".join([*self.qual_prefix, stmt.name])
            self.class_stack.append(qualname)
            self.qual_prefix.append(stmt.name)
            self._body(stmt.body, module_level=False)
            self.qual_prefix.pop()
            self.class_stack.pop()
            return
        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if isinstance(stmt, ast.AnnAssign) and stmt.value is None:
                if in_class_body and isinstance(stmt.target, ast.Name):
                    self._need_write(
                        stmt,
                        f"attr:{self.mf.module}:{self.class_stack[-1]}.{stmt.target.id}",
                        None,
                        "필드 선언",
                    )
                return
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in _flat_targets(list(targets)):
                if isinstance(target, ast.Attribute):
                    self._need_write(stmt, None, target.attr, f"속성 할당 {target.attr!r}")
                elif isinstance(target, ast.Subscript):
                    self._need_mutation(stmt, target, "subscript 변이")
                elif isinstance(target, ast.Name):
                    if module_level:
                        self._need_write(
                            stmt, f"attr:{self.mf.module}:{target.id}", None, "모듈 전역 할당"
                        )
                    elif in_class_body:
                        self._need_write(
                            stmt,
                            f"attr:{self.mf.module}:{self.class_stack[-1]}.{target.id}",
                            None,
                            "클래스 속성 할당",
                        )
            exprs: list[ast.expr] = list(targets)
            value = getattr(stmt, "value", None)
            if value is not None:
                exprs.append(value)
            self._exprs(exprs)
            return
        if isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                if isinstance(target, ast.Attribute):
                    self._need_write(stmt, None, target.attr, f"속성 삭제 {target.attr!r}")
                elif isinstance(target, ast.Subscript):
                    self._need_mutation(stmt, target, "subscript 삭제")
                elif isinstance(target, ast.Name):
                    if module_level:
                        self._need_write(
                            stmt, f"attr:{self.mf.module}:{target.id}", None, "모듈 전역 삭제"
                        )
                    elif in_class_body:
                        self._need_write(
                            stmt,
                            f"attr:{self.mf.module}:{self.class_stack[-1]}.{target.id}",
                            None,
                            "클래스 속성 삭제",
                        )
            self._exprs(list(stmt.targets))
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor)):
            self._exprs([stmt.target, stmt.iter])
            self._body(stmt.body, module_level=module_level)
            self._body(stmt.orelse, module_level=module_level)
            return
        if isinstance(stmt, ast.While):
            self._exprs([stmt.test])
            self._body(stmt.body, module_level=module_level)
            self._body(stmt.orelse, module_level=module_level)
            return
        if isinstance(stmt, ast.If):
            self._exprs([stmt.test])
            self._body(stmt.body, module_level=module_level)
            self._body(stmt.orelse, module_level=module_level)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            items: list[ast.expr] = []
            for item in stmt.items:
                items.append(item.context_expr)
                if item.optional_vars is not None:
                    items.append(item.optional_vars)
            self._exprs(items)
            self._body(stmt.body, module_level=module_level)
            return
        if isinstance(stmt, (ast.Try, ast.TryStar)):
            self._body(stmt.body, module_level=module_level)
            for handler in stmt.handlers:
                if handler.type is not None:
                    self._exprs([handler.type])
                self._body(handler.body, module_level=module_level)
            self._body(stmt.orelse, module_level=module_level)
            self._body(stmt.finalbody, module_level=module_level)
            return
        if isinstance(stmt, ast.Match):
            self._exprs([stmt.subject])
            for case in stmt.cases:
                self._body(case.body, module_level=module_level)
            return
        exprs = [child for child in ast.iter_child_nodes(stmt) if isinstance(child, ast.expr)]
        if exprs:
            self._exprs(exprs)

    def _exprs(self, exprs: "list[ast.expr]") -> None:
        first = self.first_params[-1] if self.first_params else ""
        for expr in exprs:
            shadow = _expression_shadow_names(expr)
            call_funcs = {
                id(node.func) for node in ast.walk(expr) if isinstance(node, ast.Call)
            }
            for node in ast.walk(expr):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr in MUTATOR_METHODS:
                        if (
                            isinstance(func.value, ast.Name)
                            and first
                            and func.value.id == first
                            and func.attr in self.class_methods.get(self._method_cls(), set())
                        ):
                            continue  # 자기 클래스가 정의한 같은 이름 메서드 — 일반 호출
                        self._need_mutation(node, node, f"변이 메서드 {func.attr!r}")
                elif (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Load)
                    and id(node) not in call_funcs
                    and isinstance(node.value, ast.Name)
                    and first
                    and node.value.id == first
                    and node.value.id not in shadow
                ):
                    self._need_read(node, self._method_cls())

    def _method_cls(self) -> str:
        # 메서드 본문에서 class_stack 은 비워지므로 정의 시점 클래스를 함수 스택이 든다.
        return self.method_cls[-1] if self.method_cls else ""


def _lexical_class_methods(tree: ast.Module) -> "dict[str, set[str]]":
    out: dict[str, set[str]] = {}

    def direct_methods(body: "list[ast.stmt]", methods: "set[str]") -> None:
        # 조건부 블록(if/try) 안 정의도 클래스 네임스페이스의 메서드다 — 심볼 수집기와 동형.
        for sub in body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.add(sub.name)
            elif not isinstance(sub, ast.ClassDef):
                for block in _statement_blocks(sub):
                    direct_methods(block, methods)

    def walk(body: "list[ast.stmt]", prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                qual = f"{prefix}{node.name}"
                direct_methods(node.body, out.setdefault(qual, set()))
                walk(node.body, f"{qual}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(node.body, f"{prefix}{node.name}.<locals>.")
            else:
                for block in _statement_blocks(node):
                    walk(block, prefix)

    walk(tree.body, "")
    return out


# ---------------------------------------------------------------------------
# runtime observer — 테스트 전용 setattr 관측(제품 코드 접촉 0)
# ---------------------------------------------------------------------------


@contextmanager
def observe_attribute_writes(
    target_cls: type,
    owner_module: str,
    owner_qualname: str,
    code_map: Mapping[str, tuple[str, str]],
    symbol_index: Mapping[tuple[str, str], str],
) -> Iterator["list[Fact]"]:
    """관측 대상 클래스의 인스턴스 속성 쓰기를 ``RUNTIME_CONFIRMED`` 사실로 기록한다.

    ``runtime_trace.record_calls`` 와 같은 규약이다: ``code_map`` 은 ``co_filename`` 원문 →
    (모듈, 저장소 상대 경로), ``symbol_index`` 는 (모듈, qualname) → symbol ID. 관측 지도
    밖에서 온 쓰기는 기록하지 않는다 — 그 부재는 「없음」이 아니라 「이 seam 이 안 본 것」
    이다. 클래스 ``__setattr__`` 를 문맥 동안만 바꿔 끼우고 원상 복구한다(테스트 전용 —
    제품 런타임에 이 함수를 아는 코드는 없다).
    """
    facts: list[Fact] = []
    recorded: set[tuple[str, str]] = set()
    had_own = "__setattr__" in target_cls.__dict__
    original_entry = target_cls.__dict__.get("__setattr__")
    previous = target_cls.__setattr__

    def _recording(instance: object, name: str, value: object) -> None:
        frame = sys._getframe(1)
        entry = code_map.get(frame.f_code.co_filename)
        if entry is not None:
            module, rel_path = entry
            sid = symbol_index.get((module, frame.f_code.co_qualname))
            src = sid if sid is not None else f"?:runtime:{module}.{frame.f_code.co_qualname}"
            if not src.startswith("?:"):
                key = (src, name)
                if key not in recorded:
                    recorded.add(key)
                    facts.append(
                        Fact(
                            src=src,
                            rel="writes_attribute",
                            dst=f"attr:{owner_module}:{owner_qualname}.{name}",
                            grade="RUNTIME_CONFIRMED",
                            evidence=Evidence(file=rel_path, line=frame.f_lineno, anchor=name),
                            provenance=Provenance(COLLECTOR, "setattr_observe"),
                        )
                    )
        previous(instance, name, value)

    target_cls.__setattr__ = _recording  # type: ignore[method-assign, assignment]
    try:
        yield facts
    finally:
        if had_own and original_entry is not None:
            target_cls.__setattr__ = original_entry  # type: ignore[method-assign]
        else:
            del target_cls.__setattr__
        facts.sort(key=Fact.sort_key)


# ---------------------------------------------------------------------------
# 원장 render/check/rewrite
# ---------------------------------------------------------------------------

_HEADER = f"""# 생성 파일 — 직접 편집 금지. P1-02B 상태 그래프 원장(#514).
# 원천: 고정 baseline src/ + scripts/factgraph 기반·02A·상태 파생 사실의 결정론 재계측
# 재생성: {REGEN_COMMAND}
# 검사:   {REGEN_COMMAND} --check
schema = "state-graph-02b/v1"
"""


def _committed_input_digests(repo_root: Path) -> "tuple[str, str]":
    target = repo_root / static_graph.LEDGER_REL_PATH
    if not target.is_file():
        raise FactGraphError(
            f"입력 원장이 없다: {static_graph.LEDGER_REL_PATH} — 02A 원장이 먼저 서야 한다"
        )
    document = tomllib.loads(target.read_text(encoding="utf-8"))
    digests = document.get("digests", {})
    base = digests.get("base_facts", "")
    graph = digests.get("graph_facts", "")
    if not base or not graph:
        raise FactGraphError(f"입력 원장에 digest 가 없다: {static_graph.LEDGER_REL_PATH}")
    return base, graph


def render(repo_root: Path, *, _baseline_checked: bool = False) -> str:
    repo_root = Path(repo_root)
    if not _baseline_checked:
        baseline_problems = _baseline_problems(repo_root)
        if baseline_problems:
            raise FactGraphError("; ".join(baseline_problems))
    result = build_state(repo_root)

    committed_base, committed_graph = _committed_input_digests(repo_root)
    if (result.static.base_digest, result.static.graph_digest) != (
        committed_base,
        committed_graph,
    ):
        raise FactGraphError(
            "입력 앵커 불일치 — 02A 원장의 digest 와 재계측이 다르다: "
            f"base {committed_base} ≠ {result.static.base_digest} 또는 "
            f"graph {committed_graph} ≠ {result.static.graph_digest}"
        )

    coverage = uncovered_state_sites(
        repo_root,
        result.static.closure,
        [*result.static.base_facts, *result.state_facts],
    )
    if coverage:
        sample = "; ".join(coverage[:5])
        raise FactGraphError(f"상태 그래프 미수집 좌표 {len(coverage)}건: {sample}")

    unresolved = tuple(
        sorted(
            (f for f in result.state_facts if f.grade == "UNKNOWN"),
            key=Fact.sort_key,
        )
    )

    parts = [_HEADER, "\n[baseline]\n"]
    parts.append(f"git_sha = {_q(static_graph.BASELINE_SHA)}\n")
    parts.append("\n# 입력 앵커 — 02A 원장의 digest 와 같아야 render 가 선다(4슬라이스 공통 기준).\n")
    parts.append("[input]\n")
    parts.append(f"static_ledger = {_q(static_graph.LEDGER_REL_PATH)}\n")
    parts.append(f'base_facts = "{result.static.base_digest}"\n')
    parts.append(f'graph_facts = "{result.static.graph_digest}"\n')
    parts.append("\n[digests]\n")
    parts.append(f'state_facts = "{result.state_digest}"\n')
    parts.append(f'full_graph = "{result.full_digest}"\n')

    storage_counts: dict[str, int] = {}
    for row in result.states:
        storage_counts[row.storage] = storage_counts.get(row.storage, 0) + 1
    parts.append("\n[counts]\n")
    parts.append(f"modules = {len(result.static.closure.modules)}\n")
    parts.append(f"symbols = {len(result.static.symbols)}\n")
    parts.append(f"facts_state = {len(result.state_facts)}\n")
    parts.append(f"states = {len(result.states)}\n")
    for storage in ("instance_field", "class_attr", "module_global"):
        parts.append(f"states_{storage} = {storage_counts.get(storage, 0)}\n")
    parts.append(
        f"states_declared_only = {sum(1 for row in result.states if row.declared_only)}\n"
    )
    parts.append(f"transaction_clusters = {len(result.clusters)}\n")
    parts.append(f"shared_states = {len(result.shared)}\n")
    parts.append(f"sync_sites = {len(result.sync_sites)}\n")
    parts.append(
        f"sync_unbound = {sum(1 for s in result.sync_sites if s.state_id == '?:unbound')}\n"
    )
    parts.append("uncovered_state_sites = 0\n")
    parts.append(f"unresolved_state_open = {len(unresolved)}\n")
    parts.append(f"inherited_02b_queue = {result.inherited_queue}\n")
    parts.append(f"inherited_02b_queue_site_covered = {result.inherited_queue_site_covered}\n")

    by_rule: dict[str, int] = {}
    for fact in result.state_facts:
        by_rule[fact.provenance.rule] = by_rule.get(fact.provenance.rule, 0) + 1
    parts.append("\n[state_rules]\n")
    for rule, count in sorted(by_rule.items()):
        parts.append(f"{_q(rule)} = {count}\n")

    open_rules = sorted({f.provenance.rule for f in unresolved})
    parts.append("\n# rule → 후속 확인 경로 — 미해결은 소유자가 있어야 원장이다.\n")
    parts.append("[followup]\n")
    for rule in open_rules:
        parts.append(f"{_q(rule)} = {_q(followup_of(rule))}\n")

    for row in result.states:
        parts.append("\n[[state]]\n")
        parts.append(f"id = {_q(row.state_id)}\n")
        parts.append(f"storage = {_q(row.storage)}\n")
        parts.append(f"declared_only = {'true' if row.declared_only else 'false'}\n")
        parts.append(_list_field("writers", row.writers))
        parts.append(_list_field("mutators", row.mutators))
        parts.append(_list_field("readers", row.readers))
        parts.append(_list_field("sync", row.sync))

    for cluster in result.clusters:
        parts.append("\n[[transaction_cluster]]\n")
        parts.append(f"src = {_q(cluster.src)}\n")
        parts.append(_list_field("members", cluster.members))

    for shared_row in result.shared:
        parts.append("\n[[shared_state]]\n")
        parts.append(f"state = {_q(shared_row.state_id)}\n")
        parts.append(_list_field("units", shared_row.units))

    for site in result.sync_sites:
        parts.append("\n[[sync_primitive]]\n")
        parts.append(f"kind = {_q(site.kind)}\n")
        parts.append(f"state = {_q(site.state_id)}\n")
        parts.append(f"file = {_q(site.file)}\n")
        parts.append(f"line = {site.line}\n")

    # 미해결은 하나도 숨기지 않고 좌표까지 커밋한다 — runtime trace/P1-03 의 작업 큐다.
    for fact in unresolved:
        parts.append("\n[[unresolved]]\n")
        parts.append(f"src = {_q(fact.src)}\n")
        parts.append(f"rel = {_q(fact.rel)}\n")
        parts.append(f"dst = {_q(fact.dst)}\n")
        parts.append(f"grade = {_q(fact.grade)}\n")
        parts.append(f"file = {_q(fact.evidence.file)}\n")
        parts.append(f"line = {fact.evidence.line}\n")
        parts.append(f"anchor = {_q(fact.evidence.anchor)}\n")
        parts.append(f"collector = {_q(fact.provenance.collector)}\n")
        parts.append(f"rule = {_q(fact.provenance.rule)}\n")
        parts.append(f"followup = {_q(followup_of(fact.provenance.rule))}\n")
    return "".join(parts)


def _list_field(name: str, values: "tuple[str, ...]") -> str:
    if not values:
        return f"{name} = []\n"
    body = "".join(f"  {_q(value)},\n" for value in values)
    return f"{name} = [\n{body}]\n"


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def check(repo_root: Path) -> "list[str]":
    repo_root = Path(repo_root)
    baseline_problems = _baseline_problems(repo_root)
    if baseline_problems:
        return baseline_problems
    target = repo_root / LEDGER_REL_PATH
    expected = render(repo_root, _baseline_checked=True)
    if not target.is_file():
        return [f"{LEDGER_REL_PATH}: 생성물이 없습니다 — `{REGEN_COMMAND}` 로 생성하세요."]
    if target.read_text(encoding="utf-8") == expected:
        return []
    problems = [f"{LEDGER_REL_PATH}: 원장 드리프트 — `{REGEN_COMMAND}` 로 재생성하세요."]
    try:
        actual_digests = tomllib.loads(target.read_text(encoding="utf-8")).get("digests", {})
        expected_digests = tomllib.loads(expected).get("digests", {})
        for key in sorted(set(actual_digests) | set(expected_digests)):
            if actual_digests.get(key) != expected_digests.get(key):
                problems.append(
                    f"  digest {key}: 커밋본 {actual_digests.get(key)} ≠ 재계측 {expected_digests.get(key)}"
                )
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"  커밋본을 파싱할 수 없다(직접 편집 흔적?): {exc}")
    return problems


def rewrite(repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    baseline_problems = _baseline_problems(repo_root)
    if baseline_problems:
        raise FactGraphError("; ".join(baseline_problems))
    target = repo_root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(repo_root, _baseline_checked=True))
    return target


def _baseline_problems(repo_root: Path) -> "list[str]":
    from .static_graph import _baseline_source_problems

    return _baseline_source_problems(repo_root)


__all__ = [
    "COLLECTOR",
    "FOLLOWUP_OF_RULE",
    "LEDGER_REL_PATH",
    "MUTATOR_METHODS",
    "REGEN_COMMAND",
    "SYNC_PRIMITIVES",
    "SharedState",
    "StateGraphResult",
    "StateRow",
    "SyncSite",
    "TransactionCluster",
    "build_state",
    "check",
    "collect_state_facts",
    "followup_of",
    "observe_attribute_writes",
    "render",
    "rewrite",
    "state_shard",
    "uncovered_state_sites",
]
