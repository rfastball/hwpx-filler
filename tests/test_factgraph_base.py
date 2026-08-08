"""P1-01 공용 수집 기반의 판별력 게이트(#512).

합성 미니 저장소(tmp 생성 — 커밋 fixture 없음)로 폐포·심볼·사실 수집의 양성·음성 판별력을
세우고, 실 저장소에서 분모 하한과 재실행 digest 동일성을 단언한다. 여기서 「판별력」은
승계 형질 S7 이다 — 술어가 초록인 것과 술어가 무는 것을 각각 실측으로 증명한다.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest
from factgraph import (
    GRADES,
    RELATIONS,
    Evidence,
    Fact,
    FactGraphError,
    Provenance,
    collect_facts,
    collect_symbols,
    edge_grades,
    make_shard,
    merge_shards,
    parse_symbol_id,
    production_closure,
    record_calls,
    symbol_id,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 합성 미니 저장소
# ---------------------------------------------------------------------------


def _mini_repo(tmp_path: Path, files: "dict[str, str]", packages: "list[str] | None" = None) -> Path:
    repo = tmp_path / "repo"
    pkg_list = packages if packages is not None else ["src/alpha"]
    rows = ", ".join(f'"{p}"' for p in pkg_list)
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"mini\"\nversion = \"0\"\n\n"
        f"[tool.hatch.build.targets.wheel]\npackages = [{rows}]\n",
        encoding="utf-8",
    )
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body), encoding="utf-8")
    return repo


def _facts_of(repo: Path, module: str) -> "list[Fact]":
    closure = production_closure(repo)
    symbols = collect_symbols(repo, closure)
    return [f for f in collect_facts(repo, closure, symbols) if f.src.startswith(f"{module}:")]


# ---------------------------------------------------------------------------
# 폐포
# ---------------------------------------------------------------------------


def test_closure_finds_modules_and_names_them(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/one.py": "X = 1\n",
            "src/alpha/sub/__init__.py": "",
            "src/alpha/sub/two.py": "Y = 2\n",
        },
    )
    closure = production_closure(repo)
    assert [m.module for m in closure.modules] == ["alpha", "alpha.one", "alpha.sub", "alpha.sub.two"]
    assert closure.modules[3].path == "src/alpha/sub/two.py"
    assert production_closure(repo) == closure  # 결정론


def test_closure_rejects_stray_source_outside_roots(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {"src/alpha/__init__.py": "", "src/orphan/ghost.py": "Z = 3\n"},
    )
    with pytest.raises(FactGraphError, match="ghost"):
        production_closure(repo)


def test_closure_rejects_empty_root(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path, {"src/alpha/__init__.py": ""}, packages=["src/alpha", "src/beta"])
    (repo / "src" / "beta").mkdir()
    with pytest.raises(FactGraphError, match="beta"):
        production_closure(repo)


def test_closure_rejects_missing_packages_table(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path, {"src/alpha/__init__.py": ""})
    (repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n", encoding="utf-8")
    with pytest.raises(FactGraphError, match="packages"):
        production_closure(repo)


# ---------------------------------------------------------------------------
# 심볼
# ---------------------------------------------------------------------------


def test_symbol_ids_cover_nesting_and_kinds(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                class C:
                    def m(self):
                        pass

                    @property
                    def p(self):
                        return 1

                def f():
                    def g():
                        pass
                    return g

                try:
                    def cond():
                        pass
                except Exception:
                    def cond():
                        pass
                """,
        },
    )
    ids = {s.id for s in collect_symbols(repo)}
    assert ids == {
        "alpha:#module",
        "alpha.mod:#module",
        "alpha.mod:C#class",
        "alpha.mod:C.m#method",
        "alpha.mod:C.p#method",
        "alpha.mod:f#function",
        "alpha.mod:f.<locals>.g#function",
        "alpha.mod:cond#function",  # 조건부 재정의는 같은 ID 로 접힌다
    }
    module, qualname, kind = parse_symbol_id("alpha.mod:f.<locals>.g#function")
    assert (module, qualname, kind) == ("alpha.mod", "f.<locals>.g", "function")


# ---------------------------------------------------------------------------
# import 축 — 정확 다중집합 대조(S1)
# ---------------------------------------------------------------------------


def test_import_facts_exact_multiset(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/util.py": "def helper():\n    pass\n",
            "src/alpha/sub/__init__.py": "",
            "src/alpha/mod.py": """
                from typing import TYPE_CHECKING

                import json
                import os.path as osp
                from alpha.util import helper
                from alpha import sub
                from .util import helper as h2
                from alpha.util import missing_name

                if TYPE_CHECKING:
                    from alpha.util import helper as typed

                def scoped():
                    import csv
                """,
        },
    )
    rows = {
        (f.src, f.rel, f.dst, f.grade, f.provenance.rule)
        for f in _facts_of(repo, "alpha.mod")
        if f.rel.startswith("imports")
    }
    mod = symbol_id("alpha.mod", "", "module")
    helper_sid = "alpha.util:helper#function"
    ok = "STATIC_CONFIRMED"
    assert rows == {
        (mod, "imports_symbol", "ext:typing.TYPE_CHECKING", ok, "import_from"),
        (mod, "imports_module", "ext:json", ok, "import_plain"),
        (mod, "imports_module", "ext:os.path", ok, "import_plain"),
        (mod, "imports_symbol", helper_sid, ok, "import_from"),
        (mod, "imports_module", "alpha.sub:#module", ok, "import_from"),
        # 상대 import 도 같은 좌표로 해석된다 — 정확 다중집합이라 중복은 접힌다.
        # 미해결 dst 는 등급도 미해결이다 — 해석 실패를 확정 증거로 적지 않는다.
        (mod, "imports_symbol", "?:name:alpha.util.missing_name", "UNKNOWN", "import_from"),
        (mod, "imports_symbol", helper_sid, ok, "import_from_type_checking"),
        ("alpha.mod:scoped#function", "imports_module", "ext:csv", ok, "import_plain"),
    }


def test_scoped_import_does_not_leak_into_module_bindings(tmp_path: Path) -> None:
    """함수 안 import 별칭이 모듈 수준 해석을 오염시키면 거짓 확정 edge 가 샌다(리뷰 P1)."""
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def helper():
                    from json import dumps as encode
                    return encode({})

                def encode():
                    pass

                def caller():
                    encode()
                """,
        },
    )
    facts = _facts_of(repo, "alpha.mod")
    caller_calls = {
        (f.dst, f.grade) for f in facts if f.src == "alpha.mod:caller#function" and f.rel == "calls"
    }
    assert caller_calls == {("alpha.mod:encode#function", "STATIC_CONFIRMED")}
    helper_calls = {
        (f.dst, f.grade) for f in facts if f.src == "alpha.mod:helper#function" and f.rel == "calls"
    }
    # 함수 자신의 스코프 안에서는 지역 별칭이 유효하다 — encode 는 지역 바인딩으로 남는다
    assert helper_calls == {("?:local:encode", "UNKNOWN")}


def test_star_import_is_declared_dynamic(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {"src/alpha/__init__.py": "", "src/alpha/mod.py": "from os.path import *\n"},
    )
    facts = _facts_of(repo, "alpha.mod")
    assert [(f.rel, f.grade, f.provenance.rule) for f in facts] == [
        ("dynamic_site", "DECLARED_DYNAMIC", "import_star")
    ]


# ---------------------------------------------------------------------------
# call·construct 축
# ---------------------------------------------------------------------------


def test_call_and_construct_resolution(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/kinds.py": "class Widget:\n    def spin(self):\n        pass\n",
            "src/alpha/mod.py": """
                from alpha.kinds import Widget

                class Runner:
                    def go(self):
                        self.go2()
                        self.injected()

                    def go2(self):
                        pass

                def top():
                    w = Widget()
                    local = top
                    local()
                    print("x")
                    unknown_name()

                def shadow(print):
                    print("shadowed")
                """,
        },
    )
    rows = {
        (f.src, f.rel, f.dst, f.grade, f.provenance.rule)
        for f in _facts_of(repo, "alpha.mod")
        if f.rel in ("calls", "constructs")
    }
    assert rows == {
        ("alpha.mod:Runner.go#method", "calls", "alpha.mod:Runner.go2#method",
         "INFERRED", "call_self"),
        # 주입 콜백은 자기 클래스에 없다 — 추측하지 않고 미해결로 남는다(02A/B 몫)
        ("alpha.mod:Runner.go#method", "calls", "?:self:Runner.injected",
         "UNKNOWN", "call_self_unresolved"),
        ("alpha.mod:top#function", "constructs", "alpha.kinds:Widget#class",
         "STATIC_CONFIRMED", "call_name"),
        ("alpha.mod:top#function", "calls", "?:local:local", "UNKNOWN", "call_local_binding"),
        ("alpha.mod:top#function", "calls", "ext:builtins.print", "STATIC_CONFIRMED", "call_builtin"),
        ("alpha.mod:top#function", "calls", "?:name:unknown_name", "UNKNOWN",
         "call_name_unresolved"),
        # 매개변수가 내장 이름을 가려도 과신하지 않는다
        ("alpha.mod:shadow#function", "calls", "?:local:print", "UNKNOWN", "call_local_binding"),
    }


def test_dynamic_sites_are_loud_not_skipped(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def dispatch(target, name):
                    handler = getattr(target, "do_" + name)
                    handler()
                    known = getattr(target, "fixed")
                    factory()(1)
                    __import__("json")

                def factory():
                    return print

                # 음성 대조: 문자열·주석 속 형태는 사실이 아니다
                DOC = "getattr(x, name) 을 호출한다"
                # getattr(x, dynamic_name)
                """,
        },
    )
    facts = _facts_of(repo, "alpha.mod")
    dyn = {(f.dst, f.grade, f.provenance.rule) for f in facts if f.rel == "dynamic_site"}
    assert dyn == {
        ("?:builtin:getattr", "DECLARED_DYNAMIC", "getattr_dynamic"),
        ("?:expr:Call", "UNKNOWN", "call_shape:Call"),
        ("?:builtin:__import__", "DECLARED_DYNAMIC", "dynamic_import"),
    }
    reads = {(f.dst, f.provenance.rule) for f in facts if f.rel == "reads_attribute"}
    assert reads == {("attr:?:target.fixed", "getattr_literal")}
    # 음성 대조 — 문자열/주석의 getattr 는 어떤 사실도 만들지 않는다(위 집합이 전부다)
    assert sum(1 for f in facts if "dynamic_name" in f.evidence.anchor) == 0


def test_attribute_writes(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                STATE = None

                class Box:
                    def __init__(self):
                        self.value = 1
                        self.a, self.b = 2, 3

                def rebind():
                    global STATE
                    STATE = object()

                def poke(thing):
                    setattr(thing, "flag", True)
                    setattr(thing, compute(), True)

                def compute():
                    return "x"
                """,
        },
    )
    facts = _facts_of(repo, "alpha.mod")
    writes = {(f.src, f.dst, f.provenance.rule) for f in facts if f.rel == "writes_attribute"}
    assert writes == {
        ("alpha.mod:Box.__init__#method", "attr:alpha.mod:Box.value", "attr_assign"),
        ("alpha.mod:Box.__init__#method", "attr:alpha.mod:Box.a", "attr_assign"),
        ("alpha.mod:Box.__init__#method", "attr:alpha.mod:Box.b", "attr_assign"),
        ("alpha.mod:rebind#function", "attr:alpha.mod:STATE", "global_rebind"),
        ("alpha.mod:poke#function", "attr:?:thing.flag", "setattr_literal"),
    }
    assert ("?:builtin:setattr", "DECLARED_DYNAMIC", "setattr_dynamic") in {
        (f.dst, f.grade, f.provenance.rule) for f in facts if f.rel == "dynamic_site"
    }


# ---------------------------------------------------------------------------
# 스키마·shard·merge
# ---------------------------------------------------------------------------


def _fact(src: str, rel: str, dst: str, grade: str, line: int = 1) -> Fact:
    return Fact(src, rel, dst, grade, Evidence("src/x.py", line), Provenance("t", "r"))


def test_schema_rejects_unregistered_vocabulary() -> None:
    sid = symbol_id("alpha", "f", "function")
    with pytest.raises(FactGraphError, match="relation"):
        _fact(sid, "telepathy", sid, "UNKNOWN")
    with pytest.raises(FactGraphError, match="grade"):
        _fact(sid, "calls", sid, "MAYBE")
    with pytest.raises(FactGraphError, match="kind"):
        symbol_id("alpha", "f", "widget")
    with pytest.raises(FactGraphError):
        parse_symbol_id("no-separator")
    # 위조 symbol ID 형태는 # 이 있어도 거절된다 — 파싱이 실제로 받아야 참조다(리뷰 P2)
    with pytest.raises(FactGraphError):
        _fact("garbage#junk", "calls", sid, "UNKNOWN")
    with pytest.raises(FactGraphError):
        _fact(sid, "calls", "foo#function", "UNKNOWN")
    with pytest.raises(FactGraphError):
        _fact(sid, "calls", "foo:#bogus", "UNKNOWN")


def test_shard_digest_is_order_free_and_content_sensitive() -> None:
    sid_a = symbol_id("alpha", "a", "function")
    sid_b = symbol_id("alpha", "b", "function")
    facts = [_fact(sid_a, "calls", sid_b, "STATIC_CONFIRMED"), _fact(sid_b, "calls", sid_a, "UNKNOWN")]
    one = make_shard("s", "p", "sha" * 10, [sid_a, sid_b], facts)
    two = make_shard("s", "p", "sha" * 10, [sid_b, sid_a], list(reversed(facts)))
    assert one.digest == two.digest
    three = make_shard(
        "s", "p", "sha" * 10, [sid_a, sid_b],
        [*facts, _fact(sid_a, "calls", sid_b, "STATIC_CONFIRMED", line=99)],
    )
    assert three.digest != one.digest


def test_merge_rejects_mixed_baselines_and_upgrades_grades() -> None:
    sid_a = symbol_id("alpha", "a", "function")
    sid_b = symbol_id("alpha", "b", "function")
    static = make_shard("s1", "p", "aaa", [sid_a], [_fact(sid_a, "calls", sid_b, "STATIC_CONFIRMED")])
    runtime = make_shard("s2", "p", "aaa", [sid_b], [_fact(sid_a, "calls", sid_b, "RUNTIME_CONFIRMED", 7)])
    other = make_shard("s3", "p", "bbb", [sid_a], [])
    with pytest.raises(FactGraphError, match="baseline"):
        merge_shards([static, other])
    merged = merge_shards([static, runtime])
    assert merged.symbols == (sid_a, sid_b)
    grades = edge_grades(merged.facts)
    assert grades[(sid_a, "calls", sid_b)] == "STATIC_AND_RUNTIME_CONFIRMED"
    solo = edge_grades(static.facts)
    assert solo[(sid_a, "calls", sid_b)] == "STATIC_CONFIRMED"


# ---------------------------------------------------------------------------
# runtime trace seam
# ---------------------------------------------------------------------------


def test_runtime_seam_confirms_dynamic_dispatch(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/mod.py": """
                def do_jump():
                    return "jump"

                def direct():
                    return 1

                def dispatch(name):
                    import sys
                    handler = getattr(sys.modules[__name__], "do_" + name)
                    direct()
                    return handler()
                """,
        },
    )
    closure = production_closure(repo)
    symbols = collect_symbols(repo, closure)
    static_facts = collect_facts(repo, closure, symbols)
    mod_path = repo / "src/alpha/mod.py"
    spec = importlib.util.spec_from_file_location("alpha_mod_under_trace", mod_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        code_map = {module.dispatch.__code__.co_filename: ("alpha.mod", "src/alpha/mod.py")}
        index = {(s.module, s.qualname): s.id for s in symbols}
        with record_calls(code_map, index) as runtime_facts:
            assert module.dispatch("jump") == "jump"
    finally:
        del sys.modules[spec.name]

    dispatch_sid = "alpha.mod:dispatch#function"
    runtime_edges = {(f.src, f.dst) for f in runtime_facts}
    assert (dispatch_sid, "alpha.mod:do_jump#function") in runtime_edges  # 문자열 디스패치 실측
    assert (dispatch_sid, "alpha.mod:direct#function") in runtime_edges
    assert all(f.grade == "RUNTIME_CONFIRMED" and f.rel == "calls" for f in runtime_facts)
    # 실행 증거의 좌표는 정적 증거와 같은 저장소 상대 경로다 — 모듈 이름이 아니다(리뷰 P2)
    assert {f.evidence.file for f in runtime_facts} == {"src/alpha/mod.py"}

    # 정적 쪽은 그 edge 를 모른 채 동적 자리만 loud 하게 남겼다 — merge 가 두 증거를 잇는다
    static_shard = make_shard("static", "p", "sha0", [s.id for s in symbols], list(static_facts))
    runtime_shard = make_shard("runtime", "p", "sha0", [], list(runtime_facts))
    merged = merge_shards([static_shard, runtime_shard])
    grades = edge_grades(merged.facts)
    assert grades[(dispatch_sid, "calls", "alpha.mod:do_jump#function")] == "RUNTIME_CONFIRMED"
    assert (
        grades[(dispatch_sid, "calls", "alpha.mod:direct#function")]
        == "STATIC_AND_RUNTIME_CONFIRMED"
    )


# ---------------------------------------------------------------------------
# 실 저장소 — 분모 하한·재실행 결정론(S2)
# ---------------------------------------------------------------------------


def test_real_closure_meets_floor_and_is_deterministic() -> None:
    closure = production_closure(ROOT)
    names = {m.module for m in closure.modules}
    # 분모 하한 — 폐포가 조용히 좁아지면 여기서 빨강이다.
    assert len(closure.modules) >= 80, f"폐포가 좁아졌다: {len(closure.modules)}개"
    assert "hwpxcore" in names and "hwpxfiller.core.job" in names
    symbols = collect_symbols(ROOT, closure)
    assert len(symbols) >= 1500, f"심볼 수가 하한 밑이다: {len(symbols)}"
    facts = collect_facts(ROOT, closure, symbols)
    assert {f.rel for f in facts} <= set(RELATIONS)
    assert {f.grade for f in facts} <= set(GRADES)
    one = make_shard("base", "p1-01", "sha0", [s.id for s in symbols], list(facts))
    two = make_shard(
        "base", "p1-01", "sha0",
        [s.id for s in collect_symbols(ROOT, closure)],
        list(collect_facts(ROOT, closure)),
    )
    assert one.digest == two.digest, "같은 트리 재계측의 digest 가 다르다 — 결정론 위반"
