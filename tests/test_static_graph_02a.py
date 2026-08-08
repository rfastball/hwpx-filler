"""P1-02A import·call·construction 전수 그래프의 판별력·드리프트 게이트(#513).

합성 저장소에서 상속/MRO, 구조적 문자열·표 디스패치, 재수출, SCC·fan·constructor
hotspot과 호출 노드 전수성 오러클의 양성·음성을 각각 세운다. 실 저장소에서는 커밋 원장을
독립 파싱해 재계측한 열린 edge 전수와 좌표 단위로 대조한다.
"""

from __future__ import annotations

import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest
from factgraph import Evidence, Fact, Provenance, collect_facts, collect_symbols, production_closure
from factgraph.static_graph import (
    BASELINE_SHA,
    LEDGER_REL_PATH,
    REGEN_COMMAND,
    build,
    check,
    fan_metrics,
    followup_of,
    module_import_edges,
    nontrivial_sccs,
    open_unresolved,
    render,
    rewrite,
    uncovered_bare_decorator_sites,
    uncovered_call_sites,
    uncovered_import_sites,
    uncovered_inheritance_sites,
    unresolved_facts,
)
from factgraph.schema import FactGraphError, symbol_id

ROOT = Path(__file__).resolve().parents[1]


def _mini_repo(
    tmp_path: Path,
    files: "dict[str, str]",
    *,
    name: str = "repo",
) -> Path:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"mini\"\nversion = \"0\"\n\n"
        '[tool.hatch.build.targets.wheel]\npackages = ["src/alpha"]\n',
        encoding="utf-8",
    )
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return repo


def test_collector_adds_inheritance_bare_decorator_and_constant_binding(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/defs.py": """
                TOKEN = "[{field}]"

                class Base:
                    pass
            """,
            "src/alpha/mod.py": """
                from alpha.defs import Base, TOKEN

                def decorate(value):
                    return value

                @decorate
                class Child(Base):
                    pass

                class LocalBase:
                    pass

                class LocalChild(LocalBase):
                    pass

                def format_token():
                    return TOKEN.format(field="x")
            """,
        },
    )
    closure = production_closure(repo)
    symbols = collect_symbols(repo, closure)
    facts = collect_facts(repo, closure, symbols)

    assert any(
        f.src == "alpha.mod:Child#class"
        and f.rel == "inherits"
        and f.dst == "alpha.defs:Base#class"
        and f.evidence.anchor == "0"
        for f in facts
    )
    assert any(
        f.src == "alpha.mod:#module"
        and f.rel == "calls"
        and f.dst == "alpha.mod:decorate#function"
        and f.provenance.rule == "decorator"
        for f in facts
    )
    assert any(
        f.rel == "imports_symbol"
        and f.dst == "attr:alpha.defs:TOKEN"
        and f.grade == "STATIC_CONFIRMED"
        for f in facts
    )
    # 상수의 런타임 타입을 class symbol로 위조하지 않는다. 바인딩 좌표만 보존해 loud하게 남긴다.
    assert any(
        f.src == "alpha.mod:format_token#function"
        and f.dst == "?:attr:alpha.defs:TOKEN.format"
        and f.grade == "UNKNOWN"
        for f in facts
    )
    assert module_import_edges(facts)["alpha.mod"] == {"alpha.defs"}
    assert uncovered_inheritance_sites(repo, closure, facts) == []
    assert uncovered_bare_decorator_sites(repo, closure, facts) == []
    without_base = tuple(fact for fact in facts if fact.rel != "inherits")
    without_bare_decorator = tuple(
        fact for fact in facts if fact.provenance.rule != "decorator"
    )
    assert len(uncovered_inheritance_sites(repo, closure, without_base)) == 2
    assert len(uncovered_bare_decorator_sites(repo, closure, without_bare_decorator)) == 1

    wrong_owner = tuple(
        Fact(
            "alpha.mod:Wrong#class",
            fact.rel,
            fact.dst,
            fact.grade,
            fact.evidence,
            fact.provenance,
        )
        if fact.src == "alpha.mod:Child#class" and fact.rel == "inherits"
        else fact
        for fact in facts
    )
    assert any(
        "owner 불일치" in problem
        for problem in uncovered_inheritance_sites(repo, closure, wrong_owner)
    )

    wrong_target = tuple(
        Fact(
            fact.src,
            fact.rel,
            "alpha.mod:Child#class",
            fact.grade,
            fact.evidence,
            fact.provenance,
        )
        if fact.src == "alpha.mod:LocalChild#class" and fact.rel == "inherits"
        else fact
        for fact in facts
    )
    assert any(
        "target 불일치" in problem
        for problem in uncovered_inheritance_sites(repo, closure, wrong_target)
    )

    wrong_decorator_owner = tuple(
        Fact(
            "alpha.mod:Child#class",
            fact.rel,
            fact.dst,
            fact.grade,
            fact.evidence,
            fact.provenance,
        )
        if fact.provenance.rule == "decorator"
        else fact
        for fact in facts
    )
    assert any(
        "owner 불일치" in problem
        for problem in uncovered_bare_decorator_sites(repo, closure, wrong_decorator_owner)
    )


def test_mro_resolves_internal_parent_but_never_crosses_opaque_base(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                from outside import External

                class Base:
                    def inherited(self):
                        return 1

                class Safe(Base, External):
                    def run(self):
                        return self.inherited()

                class Unsafe(External, Base):
                    def run(self):
                        return self.inherited()

                class FieldShadow(Base):
                    def __init__(self, callback):
                        self.inherited = callback

                    def run(self):
                        return self.inherited()

                class DirectShadow:
                    def __init__(self, callback):
                        self.ping = callback

                    def ping(self):
                        return 1

                    def run(self):
                        return self.ping()

                class Polymorphic:
                    def ping(self):
                        return "base"

                    def run(self):
                        return self.ping()

                class Override(Polymorphic):
                    def ping(self):
                        return "override"
            """,
        },
    )
    result = build(repo)
    derived = {
        (f.src, f.dst, f.grade, f.provenance.rule)
        for f in result.derived_facts
        if f.provenance.rule == "call_self_mro"
    }
    assert (
        "alpha.mod:Safe.run#method",
        "alpha.mod:Base.inherited#method",
        "INFERRED",
        "call_self_mro",
    ) in derived
    assert not any(src == "alpha.mod:Unsafe.run#method" for src, *_rest in derived)
    assert not any(src == "alpha.mod:FieldShadow.run#method" for src, *_rest in derived)
    assert not any(
        fact.src == "alpha.mod:DirectShadow.run#method"
        and fact.dst == "alpha.mod:DirectShadow.ping#method"
        for fact in result.facts
    )
    assert {
        fact.dst
        for fact in result.derived_facts
        if fact.src == "alpha.mod:Polymorphic.run#method"
        and fact.provenance.rule == "call_self_mro"
    } == {
        "alpha.mod:Polymorphic.ping#method",
        "alpha.mod:Override.ping#method",
    }
    _dynamic, self_open, _noise = open_unresolved(result)
    assert any(f.src == "alpha.mod:Safe.run#method" for f in self_open)
    assert any(f.src == "alpha.mod:Unsafe.run#method" for f in self_open)
    assert any(f.src == "alpha.mod:FieldShadow.run#method" for f in self_open)
    assert any(f.src == "alpha.mod:DirectShadow.run#method" for f in self_open)
    assert any(f.src == "alpha.mod:Polymorphic.run#method" for f in self_open)


def test_prefix_and_table_dispatch_restore_only_provable_edges(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                class Dispatcher:
                    _HANDLERS = {"one": "_do_one", "missing": "_do_missing"}

                    def by_prefix(self, action):
                        return getattr(self, f"_do_{action}")()

                    def with_suffix(self, action):
                        return getattr(self, f"_do_{action}_missing")()

                    def with_conversion(self, action):
                        return getattr(self, f"_do_{action!r}")()

                    def by_table(self, action):
                        return getattr(self, self._HANDLERS[action])()

                    def _do_one(self):
                        return 1

                    TEXT = "getattr(self, f'_do_{action}')"
                    # getattr(self, f"_do_{action}")

                class NonLiteral:
                    _HANDLERS = dict(one="_do_one")

                    def dispatch(self, action):
                        return getattr(self, self._HANDLERS[action])()

                    def _do_one(self):
                        return 1

                class NonStringKeys:
                    _HANDLERS = {1: "_do_one"}

                    def dispatch(self, action):
                        return getattr(self, self._HANDLERS[action])()

                    def _do_one(self):
                        return 1

                class Reassigned:
                    _HANDLERS = {"one": "_do_one"}
                    _HANDLERS = {"two": "_do_two"}

                    def dispatch(self, action):
                        return getattr(self, self._HANDLERS[action])()

                    def _do_one(self):
                        return 1

                    def _do_two(self):
                        return 2

                class ReadOnly:
                    _HANDLERS = {"one": "_do_one"}

                    def lookup(self, action):
                        return getattr(self, self._HANDLERS[action])

                    def _do_one(self):
                        return 1
            """,
        },
    )
    result = build(repo)
    assert [(s.kind, s.owner, s.key) for s in result.dispatch_sites] == [
        ("prefix", "alpha.mod:Dispatcher", "_do_"),
        ("table", "alpha.mod:Dispatcher", "_HANDLERS"),
    ]
    prefix = result.dispatch_sites[0]
    assert prefix.restored == ("alpha.mod:Dispatcher._do_one#method",)
    assert any("_do_missing" in miss for miss in result.table_misses)
    assert any("NonLiteral._HANDLERS" in miss for miss in result.table_misses)
    assert any("NonStringKeys._HANDLERS" in miss for miss in result.table_misses)
    assert any("Reassigned._HANDLERS" in miss for miss in result.table_misses)
    assert not any(site.owner == "alpha.mod:ReadOnly" for site in result.dispatch_sites)
    assert not any(
        fact.src
        in {
            "alpha.mod:Dispatcher.with_suffix#method",
            "alpha.mod:Dispatcher.with_conversion#method",
        }
        and fact.provenance.rule == "prefix_dispatch"
        for fact in result.derived_facts
    )
    restored = {
        (f.src, f.dst, f.grade, f.provenance.rule)
        for f in result.derived_facts
        if f.provenance.rule in ("prefix_dispatch", "table_dispatch")
    }
    assert (
        "alpha.mod:Dispatcher.by_prefix#method",
        "alpha.mod:Dispatcher._do_one#method",
        "DECLARED_DYNAMIC",
        "prefix_dispatch",
    ) in restored
    assert (
        "alpha.mod:Dispatcher.by_table#method",
        "alpha.mod:Dispatcher._do_one#method",
        "DECLARED_DYNAMIC",
        "table_dispatch",
    ) in restored
    dynamic_open, _self_open, _noise = open_unresolved(result)
    # 표 일부가 복원돼도 누락 값이 하나면 그 동적 자리는 닫힌 것으로 위장하지 않는다.
    assert any(f.dst.endswith("Dispatcher._HANDLERS") for f in dynamic_open)
    assert any(f.dst.endswith("NonLiteral._HANDLERS") for f in dynamic_open)
    assert any(f.dst.endswith("NonStringKeys._HANDLERS") for f in dynamic_open)
    assert any(f.dst.endswith("Reassigned._HANDLERS") for f in dynamic_open)
    assert any(f.dst.endswith("ReadOnly._HANDLERS") for f in dynamic_open)


def test_reexport_resolution_is_bounded_by_data_not_a_magic_depth(tmp_path: Path) -> None:
    files = {"src/alpha/__init__.py": ""}
    for index in range(6):
        files[f"src/alpha/a{index}.py"] = (
            f"from alpha.a{index + 1} import Base, helper\n"
        )
    files["src/alpha/a6.py"] = """
        class Base:
            def inherited(self):
                return 1

        def helper():
            return 1
    """
    files["src/alpha/use.py"] = """
        from alpha.a0 import Base, helper

        class Child(Base):
            def run(self):
                return self.inherited()

        def make_and_call():
            helper()
            return Base()
    """
    files["src/alpha/local.py"] = """
        def factory():
            from alpha.a0 import Base

            class Local(Base):
                def run(self):
                    return self.inherited()

            return Local
    """
    files["src/alpha/target.py"] = """
        class Widget:
            pass

        def ping():
            return 1
    """
    files["src/alpha/api.py"] = "from alpha import target as toolkit\n"
    files["src/alpha/facade_fn.py"] = "from alpha.a6 import helper\n"
    files["src/alpha/module_use.py"] = """
        from alpha import facade_fn
        from alpha.api import toolkit

        class Child(toolkit.Widget):
            pass

        def use_module():
            facade_fn.helper()
            toolkit.ping()
            return toolkit.Widget()
    """
    files["src/alpha/late.py"] = """
        class TooEarly(Base):
            pass

        from alpha.a0 import Base
    """
    result = build(_mini_repo(tmp_path, files))
    assert any(
        f.src == "alpha.a0:#module"
        and f.dst == "alpha.a6:helper#function"
        and f.provenance.rule == "import_reexport"
        for f in result.derived_facts
    )
    derived = {
        (f.src, f.rel, f.dst, f.provenance.rule)
        for f in result.derived_facts
    }
    assert (
        "alpha.use:Child#class",
        "inherits",
        "alpha.a6:Base#class",
        "inherits_reexport",
    ) in derived
    assert (
        "alpha.use:make_and_call#function",
        "calls",
        "alpha.a6:helper#function",
        "call_reexport",
    ) in derived
    assert (
        "alpha.use:make_and_call#function",
        "constructs",
        "alpha.a6:Base#class",
        "construct_reexport",
    ) in derived
    assert (
        "alpha.use:Child.run#method",
        "calls",
        "alpha.a6:Base.inherited#method",
        "call_self_mro",
    ) in derived
    assert (
        "alpha.local:factory.<locals>.Local#class",
        "inherits",
        "alpha.a6:Base#class",
        "inherits_reexport",
    ) in derived
    assert (
        "alpha.local:factory.<locals>.Local.run#method",
        "calls",
        "alpha.a6:Base.inherited#method",
        "call_self_mro",
    ) in derived
    assert (
        "alpha.module_use:use_module#function",
        "calls",
        "alpha.target:ping#function",
        "call_reexport_attr",
    ) in derived
    assert (
        "alpha.module_use:use_module#function",
        "calls",
        "alpha.a6:helper#function",
        "call_module_reexport",
    ) in derived
    assert (
        "alpha.module_use:use_module#function",
        "constructs",
        "alpha.target:Widget#class",
        "construct_reexport_attr",
    ) in derived
    assert (
        "alpha.module_use:Child#class",
        "inherits",
        "alpha.target:Widget#class",
        "inherits_reexport_attr",
    ) in derived
    assert any(
        f.src == "alpha.module_use:#module"
        and f.rel == "imports_module"
        and f.dst == "alpha.target:#module"
        and f.provenance.rule == "import_reexport"
        for f in result.derived_facts
    )
    edges = module_import_edges(result.facts)
    assert edges["alpha.use"] == {"alpha.a0", "alpha.a6"}
    assert edges["alpha.module_use"] == {
        "alpha.api",
        "alpha.facade_fn",
        "alpha.target",
    }
    assert not any(
        src == "alpha.late:TooEarly#class" and rule == "inherits_reexport"
        for src, _rel, _dst, rule in derived
    )


def _fact(src: str, rel: str, dst: str, line: int) -> Fact:
    return Fact(
        src,
        rel,
        dst,
        "STATIC_CONFIRMED",
        Evidence("src/alpha/mod.py", line, f"site-{line}"),
        Provenance("test.static_graph", "fixture"),
    )


def test_scc_fan_and_construction_hotspots_are_derived_from_edges() -> None:
    ma = symbol_id("alpha.a", "", "module")
    mb = symbol_id("alpha.b", "", "module")
    mc = symbol_id("alpha.c", "", "module")
    fa = symbol_id("alpha.a", "make", "function")
    fb = symbol_id("alpha.b", "serve", "function")
    cls = symbol_id("alpha.c", "Thing", "class")
    facts = (
        _fact(ma, "imports_module", mb, 1),
        _fact(mb, "imports_module", ma, 2),
        _fact(mc, "imports_module", mb, 3),
        _fact(fa, "constructs", cls, 4),
        _fact(fa, "calls", fb, 5),
        _fact(fa, "calls", fb, 7),  # 같은 edge의 다른 호출 좌표 — degree는 하나다
        _fact(fb, "calls", fa, 6),
    )
    assert nontrivial_sccs(module_import_edges(facts)) == (("alpha.a", "alpha.b"),)
    fan_out, fan_in, constructs = fan_metrics(facts)
    assert fan_out[fa] == 2
    assert fan_in[fa] == 1 and fan_in[fb] == 1 and fan_in[cls] == 1
    assert constructs == {fa: 1}


def test_call_completeness_oracle_distinguishes_two_calls_on_one_line(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/left.py": "def ping():\n    return 1\n",
            "src/alpha/right.py": "def ping():\n    return 2\n",
            "src/alpha/mod.py": """
                import alpha.left as side

                def first():
                    pass

                def second():
                    pass

                def both():
                    first(); second()

                def via_module():
                    side.ping()
            """,
        },
    )
    result = build(repo)
    assert uncovered_call_sites(repo, result.closure, result.facts) == []
    without_second = tuple(
        f
        for f in result.facts
        if not (
            f.src == "alpha.mod:both#function"
            and f.rel == "calls"
            and f.dst == "alpha.mod:second#function"
        )
    )
    problems = uncovered_call_sites(repo, result.closure, without_second)
    assert len(problems) == 1
    assert "second()" in problems[0] and "호출에 사실이 없다" in problems[0]

    wrong_first = tuple(
        Fact(
            f.src,
            f.rel,
            "alpha.mod:second#function",
            f.grade,
            f.evidence,
            f.provenance,
        )
        if f.src == "alpha.mod:both#function"
        and f.rel == "calls"
        and f.dst == "alpha.mod:first#function"
        else f
        for f in result.facts
    )
    integrity = uncovered_call_sites(repo, result.closure, wrong_first)
    assert len(integrity) == 1
    assert "호출 target 불일치" in integrity[0] and "source='first'" in integrity[0]

    wrong_module = tuple(
        Fact(
            fact.src,
            fact.rel,
            "alpha.right:ping#function",
            fact.grade,
            fact.evidence,
            fact.provenance,
        )
        if fact.src == "alpha.mod:via_module#function"
        and fact.dst == "alpha.left:ping#function"
        else fact
        for fact in result.facts
    )
    module_integrity = uncovered_call_sites(repo, result.closure, wrong_module)
    assert len(module_integrity) == 1
    assert "호출 target module 불일치" in module_integrity[0]


def test_annotation_calls_follow_runtime_evaluation_mode(tmp_path: Path) -> None:
    eager = _mini_repo(
        tmp_path / "eager",
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def marker():
                    return object

                module_value: marker()

                def annotated(value: marker()) -> marker():
                    local_value: marker()
                    return value
            """,
        },
    )
    eager_result = build(eager)
    eager_calls = [
        fact
        for fact in eager_result.base_facts
        if fact.dst == "alpha.mod:marker#function" and fact.rel == "calls"
    ]
    assert len(eager_calls) == 3
    assert uncovered_call_sites(eager, eager_result.closure, eager_result.facts) == []

    postponed = _mini_repo(
        tmp_path / "postponed",
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                from __future__ import annotations

                def marker():
                    return object

                module_value: marker()

                def annotated(value: marker()) -> marker():
                    local_value: marker()
                    return value
            """,
        },
    )
    postponed_result = build(postponed)
    assert not any(
        fact.dst == "alpha.mod:marker#function" and fact.rel == "calls"
        for fact in postponed_result.base_facts
    )
    assert uncovered_call_sites(
        postponed, postponed_result.closure, postponed_result.facts
    ) == []


def test_import_completeness_oracle_tracks_each_binding_on_the_same_line(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": "import json as first; import csv as second\n",
        },
    )
    result = build(repo)
    assert uncovered_import_sites(repo, result.closure, result.facts) == []
    without_second = tuple(
        f
        for f in result.facts
        if not (
            f.evidence.file == "src/alpha/mod.py"
            and f.evidence.anchor.startswith("second<-csv@c")
            and f.rel == "imports_module"
        )
    )
    problems = uncovered_import_sites(repo, result.closure, without_second)
    assert problems == [
        "src/alpha/mod.py:1:29 import 바인딩 'second'(원본 'csv')에 사실이 없다"
    ]


def test_import_oracle_distinguishes_two_dotted_aliases_with_the_same_bound(
    tmp_path: Path,
) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/a.py": "",
            "src/alpha/b.py": "",
            "src/alpha/mod.py": "import alpha.a, alpha.b\n",
        },
    )
    result = build(repo)
    without_b = tuple(
        fact
        for fact in result.facts
        if not fact.evidence.anchor.startswith("alpha<-alpha.b@c")
    )
    assert uncovered_import_sites(repo, result.closure, result.facts) == []
    assert uncovered_import_sites(repo, result.closure, without_b) == [
        "src/alpha/mod.py:1:16 import 바인딩 'alpha'(원본 'alpha.b')에 사실이 없다"
    ]


def test_import_oracle_keeps_duplicate_identical_alias_coordinates(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": "import json as same, json as same\n",
        },
    )
    result = build(repo)
    same_rows = [
        fact
        for fact in result.base_facts
        if fact.evidence.file == "src/alpha/mod.py"
        and fact.evidence.anchor.startswith("same<-json@c")
    ]
    assert len(same_rows) == 2
    without_second = tuple(
        fact
        for fact in result.facts
        if not fact.evidence.anchor.endswith("@c21-33")
    )
    assert uncovered_import_sites(repo, result.closure, result.facts) == []
    assert uncovered_import_sites(repo, result.closure, without_second) == [
        "src/alpha/mod.py:1:21 import 바인딩 'same'(원본 'json')에 사실이 없다"
    ]


def test_super_staticmethod_and_ambiguous_class_edges_never_overclaim(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                from outside import External

                class Base:
                    def ping(self):
                        return 1

                class Safe(Base):
                    def run(self):
                        return super().ping()

                class Before(Base, External):
                    def run(self):
                        return super().ping()

                class Blocked(External, Base):
                    def run(self):
                        return super().ping()

                class Static:
                    def target(self):
                        return 1

                    @staticmethod
                    def run(value):
                        return value.target()

                if flag:
                    class Ambiguous:
                        def run(self):
                            return self.ping()
                else:
                    class Ambiguous(Base):
                        pass
            """,
        },
    )
    result = build(repo)
    super_edges = {
        (fact.src, fact.dst, fact.grade)
        for fact in result.derived_facts
        if fact.provenance.rule == "call_super_mro"
    }
    assert (
        "alpha.mod:Safe.run#method",
        "alpha.mod:Base.ping#method",
        "INFERRED",
    ) in super_edges
    assert (
        "alpha.mod:Before.run#method",
        "alpha.mod:Base.ping#method",
        "INFERRED",
    ) in super_edges
    assert not any(src == "alpha.mod:Blocked.run#method" for src, _dst, _grade in super_edges)
    assert not any(
        fact.src == "alpha.mod:Static.run#method"
        and fact.dst == "alpha.mod:Static.target#method"
        for fact in result.facts
    )
    assert "alpha.mod:Ambiguous#class" in result.mro_failures
    assert not any(
        fact.src == "alpha.mod:Ambiguous.run#method"
        and fact.provenance.rule == "call_self_mro"
        for fact in result.derived_facts
    )
    _dynamic, _self_open, noise = open_unresolved(result)
    assert noise["call_super_unresolved"] == 3


def test_runtime_reexport_rejects_branch_ambiguity_and_type_checking_only(
    tmp_path: Path,
) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/i1.py": """
                class OnlyType:
                    pass

                def helper():
                    return 1
            """,
            "src/alpha/i2.py": """
                def helper():
                    return 2
            """,
            "src/alpha/api.py": """
                from typing import TYPE_CHECKING

                if branch:
                    from alpha.i1 import helper
                else:
                    from alpha.i2 import helper

                if TYPE_CHECKING:
                    from alpha.i1 import OnlyType
            """,
            "src/alpha/api_plain.py": "import alpha.i1\n",
            "src/alpha/use.py": """
                from alpha.api import OnlyType, helper
                from alpha.api_plain import alpha

                def run():
                    helper()
                    alpha.helper()
                    return OnlyType()

                def conditional(flag):
                    if flag:
                        from alpha.i1 import helper as local_helper
                    return local_helper()
            """,
        },
    )
    result = build(repo)
    assert not any(
        fact.src == "alpha.use:#module"
        and fact.provenance.rule == "import_reexport"
        and fact.evidence.anchor.startswith(("helper<-helper@c", "OnlyType<-OnlyType@c"))
        for fact in result.derived_facts
    )
    assert not any(
        fact.src == "alpha.use:run#function"
        and fact.dst == "alpha.i1:helper#function"
        and fact.provenance.rule == "call_reexport_attr"
        for fact in result.derived_facts
    )
    unresolved = unresolved_facts(result)
    assert any(fact.dst == "?:name:alpha.api.helper" for fact in unresolved)
    assert any(fact.dst == "?:name:alpha.api.OnlyType" for fact in unresolved)
    assert any(fact.dst == "?:attr:alpha.helper" for fact in unresolved)
    assert any(
        fact.src == "alpha.use:conditional#function"
        and fact.dst == "?:local:local_helper"
        for fact in unresolved
    )
    assert any(
        fact.src == "alpha.use:conditional#function"
        and fact.dst == "alpha.i1:helper#function"
        and fact.grade == "INFERRED"
        and fact.provenance.rule == "call_reexport"
        for fact in result.derived_facts
    )


def test_try_branches_keep_conflicting_import_bindings_loud(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/a.py": """
                def helper():
                    return 1
            """,
            "src/alpha/b.py": """
                def helper():
                    return 2
            """,
            "src/alpha/mod.py": """
                try:
                    from alpha.a import helper
                except ImportError:
                    from alpha.b import helper

                module_value = helper()

                class Holder:
                    try:
                        from alpha.a import helper as class_helper
                    except ImportError:
                        from alpha.b import helper as class_helper

                    value = class_helper()
            """,
        },
    )
    result = build(repo)
    ambiguous_sources = {"alpha.mod:#module", "alpha.mod:Holder#class"}
    candidate_targets = {"alpha.a:helper#function", "alpha.b:helper#function"}
    violations = [
        (fact.src, fact.dst, fact.grade, fact.provenance.rule)
        for fact in result.facts
        if fact.src in ambiguous_sources
        and fact.rel in {"calls", "constructs"}
        and fact.dst in candidate_targets
        and fact.grade != "UNKNOWN"
    ]
    assert violations == []
    unresolved = unresolved_facts(result)
    assert any(
        fact.src == "alpha.mod:#module"
        and fact.dst == "?:name:helper"
        and fact.grade == "UNKNOWN"
        for fact in unresolved
    )
    assert any(
        fact.src == "alpha.mod:Holder#class"
        and fact.dst == "?:name:class_helper"
        and fact.grade == "UNKNOWN"
        for fact in unresolved
    )


def test_runtime_scope_and_builtin_guards_prevent_false_static_edges(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/a.py": """
                class Later:
                    pass

                def helper(*args):
                    return args
            """,
            "src/alpha/b.py": """
                def helper(*args):
                    return args
            """,
            "src/alpha/facade.py": """
                def helper():
                    return "old"

                from alpha.a import helper
            """,
            "src/alpha/mod.py": """
                before_definition()

                from builtins import staticmethod as sm
                from dataclasses import dataclass
                from typing import TYPE_CHECKING as TC
                from alpha.a import helper as getattr
                from alpha.a import helper as super
                import alpha.facade as api

                def defaulted(value=after_definition()):
                    return value

                @decorate_later()
                def decorated():
                    return 1

                def before_definition():
                    return 1

                def after_definition():
                    return 1

                def decorate_later():
                    return lambda value: value

                if TC:
                    from alpha.a import helper

                if flag:
                    from alpha.a import helper as len

                def type_only_leak():
                    return helper()

                def ambiguous_builtin():
                    return len([])

                def via_facade():
                    return api.helper()

                def shadowed():
                    return 1

                def replace(value):
                    return lambda: value

                @replace
                def replaced():
                    return 1

                def use_replaced():
                    return replaced()

                def global_branch(flag):
                    global branch_hit
                    if flag:
                        from alpha.a import helper as branch_hit
                    else:
                        from alpha.b import helper as branch_hit
                    return branch_hit()

                def global_builtin_branch(flag):
                    global len
                    if flag:
                        from alpha.a import helper as len
                    else:
                        from alpha.b import helper as len
                    return len()

                from alpha.a import helper as loop_hit
                for _item in [1]:
                    break
                else:
                    from alpha.b import helper as loop_hit

                def use_loop_hit():
                    return loop_hit()

                @dataclass(slots=True)
                class Slotted:
                    value: int

                def make_slotted():
                    return Slotted(1)

                @dataclass(frozen=True)
                class Frozen:
                    value: int

                def make_frozen():
                    return Frozen(1)

                def lambda_scope():
                    return (lambda shadowed: shadowed())(lambda: None)

                def comprehension_scope(items):
                    return [shadowed() for shadowed in items]

                class ClassBuiltinShadow:
                    from alpha.a import helper as getattr
                    value = getattr("value")

                class ClassBranch:
                    if flag:
                        from alpha.a import helper as len
                    else:
                        from alpha.b import helper as len
                    value = len([])

                class ClassScoped:
                    from alpha.a import helper

                    def run(self):
                        return helper()

                class Forward(Later):
                    pass

                class Later:
                    def ping(self):
                        return 1

                class Shadowed(Later):
                    def run(self, action):
                        return super().ping(), getattr(self, f"_do_{action}")()

                    def _do_one(self):
                        return 1

                class StaticAlias:
                    def target(self):
                        return 1

                    @sm
                    def run(value):
                        return value.target()
            """,
        },
    )
    result = build(repo)
    assert not any(
        fact.src in {
            "alpha.mod:type_only_leak#function",
            "alpha.mod:ClassScoped.run#method",
        }
        and fact.dst == "alpha.a:helper#function"
        and fact.grade != "UNKNOWN"
        for fact in result.facts
    )
    assert not any(
        fact.src == "alpha.mod:use_replaced#function"
        and fact.dst == "alpha.mod:replaced#function"
        and fact.grade != "UNKNOWN"
        for fact in result.facts
    )
    assert not any(
        fact.src
        in {
            "alpha.mod:global_branch#function",
            "alpha.mod:global_builtin_branch#function",
            "alpha.mod:use_loop_hit#function",
        }
        and fact.rel in {"calls", "constructs"}
        and fact.dst
        in {
            "alpha.a:helper#function",
            "alpha.b:helper#function",
            "ext:builtins.len",
        }
        and fact.grade != "UNKNOWN"
        for fact in result.facts
    )
    assert not any(
        fact.src == "alpha.mod:make_slotted#function"
        and fact.dst == "alpha.mod:Slotted#class"
        and fact.grade != "UNKNOWN"
        for fact in result.facts
    )
    assert any(
        fact.src == "alpha.mod:make_frozen#function"
        and fact.dst == "alpha.mod:Frozen#class"
        and fact.rel == "constructs"
        for fact in result.base_facts
    )
    assert not any(
        fact.src == "alpha.mod:#module"
        and fact.dst
        in {
            "alpha.mod:before_definition#function",
            "alpha.mod:after_definition#function",
            "alpha.mod:decorate_later#function",
        }
        and fact.grade != "UNKNOWN"
        for fact in result.base_facts
    )
    assert not any(
        fact.src == "alpha.mod:ambiguous_builtin#function"
        and fact.dst in {"ext:builtins.len", "alpha.a:helper#function"}
        and fact.grade != "UNKNOWN"
        for fact in result.facts
    )
    assert any(
        fact.src == "alpha.mod:via_facade#function"
        and fact.dst == "alpha.a:helper#function"
        and fact.provenance.rule == "call_module_reexport"
        for fact in result.derived_facts
    )
    assert not any(
        fact.src
        in {
            "alpha.mod:lambda_scope#function",
            "alpha.mod:comprehension_scope#function",
        }
        and fact.dst == "alpha.mod:shadowed#function"
        for fact in result.facts
    )
    assert any(
        fact.src == "alpha.mod:ClassBuiltinShadow#class"
        and fact.dst == "alpha.a:helper#function"
        and fact.provenance.rule == "call_name"
        for fact in result.base_facts
    )
    assert not any(
        fact.src == "alpha.mod:ClassBuiltinShadow#class"
        and fact.provenance.rule.startswith("getattr_")
        for fact in result.base_facts
    )
    assert not any(
        fact.src == "alpha.mod:ClassBranch#class"
        and fact.rel in {"calls", "constructs"}
        and fact.dst
        in {
            "alpha.a:helper#function",
            "alpha.b:helper#function",
            "ext:builtins.len",
        }
        and fact.grade != "UNKNOWN"
        for fact in result.facts
    )
    forward = [
        fact
        for fact in result.base_facts
        if fact.src == "alpha.mod:Forward#class" and fact.rel == "inherits"
    ]
    assert len(forward) == 1 and forward[0].dst == "?:name:Later"
    assert not any(
        fact.src == "alpha.mod:Shadowed.run#method"
        and fact.provenance.rule in {"call_super_mro", "prefix_dispatch"}
        for fact in result.derived_facts
    )
    assert not any(site.owner == "alpha.mod:Shadowed" for site in result.dispatch_sites)
    assert not any(
        fact.src == "alpha.mod:StaticAlias.run#method"
        and fact.dst == "alpha.mod:StaticAlias.target#method"
        for fact in result.facts
    )


def test_generated_ledger_is_deterministic_complete_and_drift_sensitive(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def invoke(callback):
                    return callback()
            """,
        },
    )
    assert render(repo) == render(repo)
    target = rewrite(repo)
    assert target == repo / LEDGER_REL_PATH
    assert check(repo) == []
    document = tomllib.loads(target.read_text(encoding="utf-8"))
    assert document["baseline"]["git_sha"] == BASELINE_SHA
    measured = unresolved_facts(build(repo))
    committed = document["unresolved"]
    assert len(committed) == len(measured)
    assert all(row["file"] and row["line"] > 0 and row["followup"] for row in committed)
    measured_by_rule: dict[str, int] = {}
    for fact in measured:
        measured_by_rule[fact.provenance.rule] = (
            measured_by_rule.get(fact.provenance.rule, 0) + 1
        )
    assert document["unresolved_by_rule"] == measured_by_rule
    assert document["followup"] == {
        rule: followup_of(rule) for rule in measured_by_rule
    }
    assert document["counts"] | {
        "sccs": 0,
        "dispatch_edges": 0,
        "mro_failures": 0,
        "table_misses": 0,
        "construct_hotspot_nodes": 0,
        "fan_out_nodes": 0,
        "fan_in_nodes": 0,
    } == document["counts"]
    assert all(
        document["counts"][key] == 0
        for key in (
            "uncovered_call_sites",
            "uncovered_import_sites",
            "uncovered_inheritance_sites",
            "uncovered_bare_decorator_sites",
        )
    )

    with open(repo / "src/alpha/mod.py", "a", encoding="utf-8") as fh:
        fh.write("\ndef appeared():\n    return invoke(print)\n")
    problems = check(repo)
    assert problems and "원장 드리프트" in problems[0]
    assert any("digest" in problem for problem in problems)
    assert REGEN_COMMAND in problems[0]


def test_unknown_unresolved_rule_is_rejected_loudly() -> None:
    with pytest.raises(FactGraphError, match="후속 귀속 없는"):
        followup_of("brand_new_unowned_rule")


def test_real_graph_and_committed_ledger_match_exactly() -> None:
    baseline = subprocess.run(
        ["git", "cat-file", "-e", f"{BASELINE_SHA}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert baseline.returncode == 0, f"baseline commit 부재: {baseline.stderr}"
    source_diff = subprocess.run(
        ["git", "diff", "--quiet", BASELINE_SHA, "--", "src"],
        cwd=ROOT,
        check=False,
    )
    assert source_diff.returncode == 0, "baseline 이후 production src/가 바뀌었다 — SHA를 재확정하라"
    result = build(ROOT)
    assert len(result.closure.modules) >= 80
    assert len(result.symbols) >= 1_500
    assert result.mro_failures == ()
    assert result.table_misses == ()
    assert len(result.dispatch_sites) >= 7
    assert uncovered_call_sites(ROOT, result.closure, result.facts) == []
    assert uncovered_import_sites(ROOT, result.closure, result.facts) == []
    assert uncovered_inheritance_sites(ROOT, result.closure, result.facts) == []
    assert uncovered_bare_decorator_sites(ROOT, result.closure, result.facts) == []
    assert check(ROOT) == [], f"`{REGEN_COMMAND}` 로 원장을 재생성해야 한다"

    document = tomllib.loads((ROOT / LEDGER_REL_PATH).read_text(encoding="utf-8"))
    assert document["digests"] == {
        "base_facts": result.base_digest,
        "graph_facts": result.graph_digest,
    }
    measured = {
        (
            f.src,
            f.rel,
            f.dst,
            f.grade,
            f.evidence.file,
            f.evidence.line,
            f.evidence.anchor,
            f.provenance.collector,
            f.provenance.rule,
            followup_of(f.provenance.rule),
        )
        for f in unresolved_facts(result)
    }
    committed = [
        (
            row["src"],
            row["rel"],
            row["dst"],
            row["grade"],
            row["file"],
            row["line"],
            row["anchor"],
            row["collector"],
            row["rule"],
            row["followup"],
        )
        for row in document["unresolved"]
    ]
    measured_rows = [
        (
            f.src,
            f.rel,
            f.dst,
            f.grade,
            f.evidence.file,
            f.evidence.line,
            f.evidence.anchor,
            f.provenance.collector,
            f.provenance.rule,
            followup_of(f.provenance.rule),
        )
        for f in unresolved_facts(result)
    ]
    assert committed == measured_rows
    assert document["counts"]["unresolved_open"] == len(measured)

    dynamic_open, self_open, noise = open_unresolved(result)
    assert document["counts"] | {
        "modules": len(result.closure.modules),
        "symbols": len(result.symbols),
        "facts_base": len(result.base_facts),
        "facts_derived": len(result.derived_facts),
        "dynamic_open": len(dynamic_open),
        "self_unresolved_open": len(self_open),
        "unresolved_open": len(measured_rows),
    } == document["counts"]
    by_rule: dict[str, int] = {}
    for fact in unresolved_facts(result):
        by_rule[fact.provenance.rule] = by_rule.get(fact.provenance.rule, 0) + 1
    assert document["unresolved_by_rule"] == by_rule
    assert document["followup"] == {rule: followup_of(rule) for rule in by_rule}

    edges = module_import_edges(result.facts)
    sccs = nontrivial_sccs(edges)
    fan_out, fan_in, constructs = fan_metrics(result.facts)
    assert document["counts"]["module_import_edges"] == sum(
        len(targets) for targets in edges.values()
    )
    assert document["counts"]["sccs"] == len(sccs)
    assert document.get("scc", []) == [{"members": list(members)} for members in sccs]

    committed_dispatch = [
        (
            row["kind"],
            row["owner"],
            row["key"],
            row["src"],
            row["file"],
            row["line"],
            row["anchor"],
            row["restored"],
            tuple(row["restored_targets"]),
        )
        for row in document.get("dispatch", [])
    ]
    measured_dispatch = [
        (
            site.kind,
            site.owner,
            site.key,
            site.src,
            site.file,
            site.line,
            site.anchor,
            len(site.restored),
            site.restored,
        )
        for site in result.dispatch_sites
    ]
    assert committed_dispatch == measured_dispatch
    assert document["counts"]["dispatch_sites"] == len(result.dispatch_sites)
    assert document["counts"]["dispatch_edges"] == sum(
        len(site.restored) for site in result.dispatch_sites
    )
    assert {row["class"] for row in document.get("mro_failure", [])} == set(
        result.mro_failures
    )
    assert {row["marker"] for row in document.get("table_miss", [])} == set(
        result.table_misses
    )

    def top_rows(values: "dict[str, int]") -> "list[dict[str, object]]":
        rows = sorted(values.items(), key=lambda item: (-item[1], item[0]))[:10]
        return [{"symbol": symbol, "count": count} for symbol, count in rows]

    assert document.get("construct_hotspot", []) == top_rows(constructs)
    assert document.get("fan_out_top", []) == top_rows(fan_out)
    assert document.get("fan_in_top", []) == top_rows(fan_in)
