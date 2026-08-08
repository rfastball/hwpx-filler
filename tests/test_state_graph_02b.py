"""P1-02B 상태 그래프의 판별력·오러클·드리프트 게이트(#514).

합성 저장소에서 모듈 전역·클래스 속성·필드 선언·subscript/변이 메서드·읽기 사실의
양성·음성을 각각 세우고, 「미수집 0」 오러클이 실제 사실 결손을 빨갛게 만드는지(변이
판별력) 확인한다. 실 저장소에서는 커밋 원장의 결정론 재계측 일치와 02A 입력 앵커
(digest) 일치를 대조한다. runtime observer 는 관측 지도 안 쓰기만 기록하고 원상
복구하는지 양성·음성으로 검증한다.
"""

from __future__ import annotations

import textwrap
import tomllib
from pathlib import Path

import pytest
from factgraph import (
    Fact,
    FactGraphError,
    collect_facts,
    collect_symbols,
    edge_grades,
    merge_shards,
    production_closure,
)
from factgraph import static_graph
from factgraph.state_graph import (
    LEDGER_REL_PATH,
    build_state,
    check,
    collect_state_facts,
    followup_of,
    observe_attribute_writes,
    state_shard,
    uncovered_state_sites,
)

ROOT = Path(__file__).resolve().parents[1]


def _mini_repo(tmp_path: Path, files: "dict[str, str]", *, name: str = "repo") -> Path:
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


def _state_facts(repo: Path) -> tuple[Fact, ...]:
    closure = production_closure(repo)
    symbols = collect_symbols(repo, closure)
    base = collect_facts(repo, closure, symbols)
    return collect_state_facts(repo, closure, symbols, base_facts=base)


def _pairs(facts: "tuple[Fact, ...]", rule: str) -> "set[tuple[str, str]]":
    return {(f.dst, f.grade) for f in facts if f.provenance.rule == rule}


# ---------------------------------------------------------------------------
# 쓰기·선언 사실
# ---------------------------------------------------------------------------


def test_module_class_and_declaration_write_facts(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/glob.py": """
            import dataclasses

            VERSION = 1
            NAMES: list = []
            if VERSION:
                FLAG = True
            COUNT = 0
            COUNT += 1

            class Cfg:
                kind = "base"
                slots: int

            def local_stuff():
                hidden = 2
                return hidden

            @dataclasses.dataclass
            class Row:
                name: str
                weight: int = 0
            """,
        },
    )
    facts = _state_facts(repo)

    globals_ = _pairs(facts, "module_global_assign")
    assert ("attr:alpha.glob:VERSION", "STATIC_CONFIRMED") in globals_
    assert ("attr:alpha.glob:NAMES", "STATIC_CONFIRMED") in globals_
    # 모듈 수준 조건부 블록 안 할당도 모듈 전역이다.
    assert ("attr:alpha.glob:FLAG", "STATIC_CONFIRMED") in globals_
    # 재결속(증감 할당)은 같은 좌표의 두 번째 write 사실로 남는다.
    count_writes = [f for f in facts if f.dst == "attr:alpha.glob:COUNT"]
    assert len(count_writes) == 2

    class_attrs = _pairs(facts, "class_attr_assign")
    assert ("attr:alpha.glob:Cfg.kind", "STATIC_CONFIRMED") in class_attrs
    assert ("attr:alpha.glob:Row.weight", "STATIC_CONFIRMED") in class_attrs

    declared = _pairs(facts, "class_field_declaration")
    assert ("attr:alpha.glob:Cfg.slots", "INFERRED") in declared
    assert ("attr:alpha.glob:Row.name", "INFERRED") in declared
    # dataclass 의 값 있는 annotation 필드는 클래스 기본값 + 인스턴스 필드 선언 둘 다다.
    assert ("attr:alpha.glob:Row.weight", "INFERRED") in declared

    # 음성: 함수 지역 재결속은 상태 사실이 아니다.
    assert not any(f.dst == "attr:alpha.glob:hidden" for f in facts)


# ---------------------------------------------------------------------------
# 변이 사실 — subscript·변이 메서드·수신자 해석
# ---------------------------------------------------------------------------

_MUT_FILES = {
    "src/alpha/__init__.py": "",
    "src/alpha/models.py": """
    class Job:
        def __init__(self):
            self.tags = []
            self.steps = []
    """,
    "src/alpha/mut.py": """
    from alpha.models import Job

    TABLE = {}

    class Basket:
        def __init__(self):
            self.rows = []
            self.cache = {}

        def push(self, item):
            self.rows.append(item)
            self.cache["k"] = item
            del self.cache["k"]

        def refresh(self):
            self.update()

        def update(self):
            self.rows.clear()

    class Sack(dict):
        def touch(self):
            self.update(a=1)

    def fill(job: Job):
        job.tags.append(1)

    def build():
        j = Job()
        j.steps.append(2)
        return j

    def churn(flag):
        j = Job()
        if flag:
            j = build()
        j.steps.append(3)

    def local_only():
        rows = []
        rows.append(1)

    def grow():
        TABLE["k"] = 1

    def chain(d):
        d.setdefault("k", []).append(1)
    """,
}


def test_subscript_and_mutator_call_mutations(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path, _MUT_FILES)
    facts = _state_facts(repo)

    assert ("attr:alpha.mut:Basket.rows", "INFERRED") in _pairs(facts, "mutcall_self_attribute")
    assert ("attr:alpha.mut:Basket.cache", "STATIC_CONFIRMED") in _pairs(
        facts, "subscript_mutation_self"
    )
    # del self.cache["k"] 도 같은 컨테이너 변이 좌표다(저장·삭제 각 1건 = 2건).
    cache_mutations = [f for f in facts if f.dst == "attr:alpha.mut:Basket.cache"]
    assert len([f for f in cache_mutations if f.rel == "mutates_attribute"]) == 2

    assert ("attr:alpha.mut:TABLE", "STATIC_CONFIRMED") in _pairs(
        facts, "subscript_mutation_global"
    )
    # 매개변수 annotation·유일 생성자 결속은 폐포 클래스 필드 좌표로 닫힌다(INFERRED).
    typed = _pairs(facts, "mutcall_typed_attribute")
    assert ("attr:alpha.models:Job.tags", "INFERRED") in typed
    assert ("attr:alpha.models:Job.steps", "INFERRED") in typed
    # 재결속으로 오염된 이름은 임의 추측 대신 미해결로 남는다.
    assert ("?:attr:j.steps", "UNKNOWN") in _pairs(facts, "mutcall_attribute_opaque")
    # 함수 지역 컬렉션은 지역 수명 후보 좌표다.
    assert ("?:local:rows", "UNKNOWN") in _pairs(facts, "mutcall_local_binding")
    assert ("?:local:d", "UNKNOWN") in _pairs(facts, "mutcall_local_binding")
    # 호출 결과 수신자는 정적 좌표가 아니다.
    assert any(f.provenance.rule == "mutcall_opaque" for f in facts)

    # 자기 수신 변이 메서드: 자기 클래스가 정의하면 일반 호출(사실 없음 — 음성),
    # 정의가 없으면 상속 컨테이너 변이 후보(?:self 미해결 — 양성).
    self_mutations = _pairs(facts, "mutcall_receiver_self")
    assert ("?:self:Sack.update", "UNKNOWN") in self_mutations
    assert not any("Basket.update" in dst for dst, _grade in self_mutations)


# ---------------------------------------------------------------------------
# 읽기 사실
# ---------------------------------------------------------------------------


def test_reads_and_mutable_global_reads(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/reads.py": """
            REGISTRY = {}
            LABELS = {"a": "b"}

            class Holder:
                def __init__(self):
                    self.value = 1

                def show(self):
                    return self.value

                def poke(self):
                    return self.helper()

                def helper(self):
                    return 0

            def put(k, v):
                REGISTRY[k] = v

            def peek():
                return REGISTRY

            def label():
                return LABELS

            def typed_read(h: Holder):
                return h.value
            """,
        },
    )
    facts = _state_facts(repo)

    reads_self = _pairs(facts, "attr_read_self")
    assert ("attr:alpha.reads:Holder.value", "STATIC_CONFIRMED") in reads_self
    # 음성: 메서드 호출의 수신 속성은 읽기 사실이 아니라 call 사실의 몫이다.
    assert not any(dst.endswith(".helper") for dst, _grade in reads_self)

    assert ("attr:alpha.reads:Holder.value", "INFERRED") in _pairs(facts, "attr_read_typed")

    global_reads = _pairs(facts, "global_read")
    # 변이 증거가 있는 전역만 읽기를 계측한다 — 상수 표는 잡음이라 적지 않는다.
    assert ("attr:alpha.reads:REGISTRY", "STATIC_CONFIRMED") in global_reads
    assert not any("LABELS" in dst for dst, _grade in global_reads)


# ---------------------------------------------------------------------------
# 상태 행·거래·공유·동시성 조인
# ---------------------------------------------------------------------------


def test_state_rows_clusters_shared_and_sync(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/decl.py": """
            import dataclasses

            @dataclasses.dataclass
            class Note:
                text: str
            """,
            "src/alpha/sync.py": """
            import threading

            JOBS = []

            class Runner:
                def __init__(self):
                    self._lock = threading.Lock()
                    self._stop = threading.Event()
                    self.count = 0
                    self.notes = []

                def bump(self):
                    self.count = self.count + 1
                    self.notes.append("x")

                def enqueue(self):
                    JOBS.append(self)

            class Drainer:
                def drain(self):
                    JOBS.clear()
            """,
        },
    )
    result = build_state(repo)
    rows = {row.state_id: row for row in result.states}

    lock_row = rows["attr:alpha.sync:Runner._lock"]
    assert lock_row.sync == ("Lock",)
    assert lock_row.storage == "instance_field"
    stop_row = rows["attr:alpha.sync:Runner._stop"]
    assert stop_row.sync == ("Event",)

    note_row = rows["attr:alpha.decl:Note.text"]
    assert note_row.declared_only is True

    jobs_row = rows["attr:alpha.sync:JOBS"]
    assert jobs_row.storage == "module_global"
    assert "alpha.sync:Runner.enqueue#method" in jobs_row.mutators
    assert "alpha.sync:Drainer.drain#method" in jobs_row.mutators

    clusters = {c.src: c.members for c in result.clusters}
    assert clusters["alpha.sync:Runner.bump#method"] == (
        "attr:alpha.sync:Runner.count",
        "attr:alpha.sync:Runner.notes",
    )

    shared = {s.state_id: s.units for s in result.shared}
    assert shared["attr:alpha.sync:JOBS"] == (
        "alpha.sync",
        "alpha.sync:Drainer",
        "alpha.sync:Runner",
    )

    # bump 는 자기 필드를 읽는 reader 로도 연결된다(같은 사실 축의 조인).
    assert "alpha.sync:Runner.bump#method" in rows["attr:alpha.sync:Runner.count"].readers


# ---------------------------------------------------------------------------
# 「미수집 0」 오러클 — 판별력
# ---------------------------------------------------------------------------


def test_uncovered_state_oracle_positive_and_negative(tmp_path: Path) -> None:
    repo = _mini_repo(
        tmp_path,
        {
            "src/alpha/__init__.py": "",
            "src/alpha/two.py": """
            class P:
                def __init__(self):
                    self.z = 1

                def read(self):
                    return self.z

                def hit(self, a, b):
                    a.x.append(1); b.y.append(2)
            """,
        },
    )
    closure = production_closure(repo)
    symbols = collect_symbols(repo, closure)
    base = collect_facts(repo, closure, symbols)
    state = collect_state_facts(repo, closure, symbols, base_facts=base)
    everything = [*base, *state]

    assert uncovered_state_sites(repo, closure, everything) == []

    # 같은 줄 두 변이 중 하나만 지워도 그 좌표가 정확히 빨갛다(앵커 판별력).
    dropped = [
        f
        for f in everything
        if not (f.rel == "mutates_attribute" and f.dst == "?:attr:b.y")
    ]
    problems = uncovered_state_sites(repo, closure, dropped)
    assert len(problems) == 1
    assert "'append'" in problems[0]

    # 속성 할당 write 사실 결손도 빨갛다.
    dropped = [f for f in everything if not (f.rel == "writes_attribute" and f.dst.endswith(".z"))]
    problems = uncovered_state_sites(repo, closure, dropped)
    assert any("속성 할당" in p for p in problems)

    # self 읽기 사실 결손도 빨갛다.
    dropped = [f for f in everything if f.provenance.rule != "attr_read_self"]
    problems = uncovered_state_sites(repo, closure, dropped)
    assert any("self 읽기" in p for p in problems)


# ---------------------------------------------------------------------------
# runtime observer
# ---------------------------------------------------------------------------


class _Probe:
    pass


def _writer(obj: "_Probe") -> None:
    obj.field = 7


def test_runtime_observer_records_and_restores() -> None:
    code_map = {_writer.__code__.co_filename: ("t.mod", "tests/t.py")}
    symbol_index = {("t.mod", "_writer"): "t.mod:_writer#function"}

    with observe_attribute_writes(_Probe, "t.mod", "_Probe", code_map, symbol_index) as facts:
        _writer(_Probe())
        # 관측 지도 밖 파일에서 온 쓰기는 기록하지 않는다 — 부재는 「안 본 것」이다.
        namespace: dict = {}
        exec(  # noqa: S102 — 관측 밖 co_filename 을 가진 호출자를 만드는 유일한 방법
            compile("def outsider(o):\n    o.field = 9\n", "<detached>", "exec"), namespace
        )
        namespace["outsider"](_Probe())

    assert [(f.src, f.dst, f.grade) for f in facts] == [
        ("t.mod:_writer#function", "attr:t.mod:_Probe.field", "RUNTIME_CONFIRMED")
    ]
    # 정적 추론 증거와 실행 증거가 같은 edge 에 서면 등급이 승급한다.
    static_guess = Fact(
        src="t.mod:_writer#function",
        rel="writes_attribute",
        dst="attr:t.mod:_Probe.field",
        grade="INFERRED",
        evidence=facts[0].evidence,
        provenance=facts[0].provenance,
    )
    grades = edge_grades([*facts, static_guess])
    key = ("t.mod:_writer#function", "writes_attribute", "attr:t.mod:_Probe.field")
    assert grades[key] == "RUNTIME_CONFIRMED"

    # 문맥이 끝나면 원상 복구 — 더 기록되지 않고 클래스 사전도 깨끗하다.
    _writer(_Probe())
    assert len(facts) == 1
    assert "__setattr__" not in _Probe.__dict__


# ---------------------------------------------------------------------------
# shard·어휘
# ---------------------------------------------------------------------------


def test_unknown_followup_rule_rejected() -> None:
    with pytest.raises(FactGraphError):
        followup_of("이런_rule_은_없다")


def test_state_shard_merges_with_static_shard_on_same_baseline(tmp_path: Path) -> None:
    repo = _mini_repo(tmp_path, _MUT_FILES)
    shard = state_shard(repo)
    assert shard.baseline_sha == static_graph.BASELINE_SHA
    merged = merge_shards([shard, shard])
    assert merged.facts == shard.facts


def test_input_anchor_mismatch_is_loud(tmp_path: Path) -> None:
    """02A 원장과 다른 src 위에서 02B render 는 서지 않는다 — 4슬라이스 결합의 실물 음성.

    실 저장소에서는 git baseline 가드가 먼저 물기 때문에, 가드가 없는 합성 저장소로
    digest 앵커 분기 자체를 겨눈다.
    """
    repo = _mini_repo(tmp_path, _MUT_FILES)
    static_graph.rewrite(repo)
    from factgraph.state_graph import render, rewrite

    rewrite(repo)
    assert check(repo) == []

    target = repo / "src/alpha/models.py"
    original = target.read_text(encoding="utf-8")

    # 변이 ①: 모듈 전역 할당 — 기반/02A 사실에는 보이지 않는, 02B 가 메우는 간극이다.
    # 앵커는 서고(02A digest 불변) 02B 자기 드리프트 층이 문다.
    target.write_text(original + "\nEXTRA = []\n", encoding="utf-8")
    problems = check(repo)
    assert problems and any("state_facts" in p for p in problems)

    # 변이 ②: 호출이 낀 할당 — 02A 사실이 움직이므로 입력 앵커 자체가 시끄럽게 죽는다.
    target.write_text(original + "\nEXTRA = list()\n", encoding="utf-8")
    with pytest.raises(FactGraphError, match="입력 앵커 불일치"):
        render(repo)


# ---------------------------------------------------------------------------
# 실 저장소 게이트 — 원장·입력 앵커
# ---------------------------------------------------------------------------


def test_real_ledger_matches_committed_and_input_anchor() -> None:
    problems = check(ROOT)
    assert problems == [], "\n".join(problems)

    document = tomllib.loads((ROOT / LEDGER_REL_PATH).read_text(encoding="utf-8"))
    upstream = tomllib.loads(
        (ROOT / static_graph.LEDGER_REL_PATH).read_text(encoding="utf-8")
    )
    # 02A 원장과 같은 측정 위에 서 있는가 — 4슬라이스 공통 기준의 기계 검증.
    assert document["input"]["base_facts"] == upstream["digests"]["base_facts"]
    assert document["input"]["graph_facts"] == upstream["digests"]["graph_facts"]
    assert document["baseline"]["git_sha"] == upstream["baseline"]["git_sha"]

    assert document["counts"]["uncovered_state_sites"] == 0
    assert document["counts"]["states"] == len(document["state"])
    # 미해결 행 전수가 등록된 후속 경로를 든다 — 소유자 없는 미해결 금지.
    for row in document.get("unresolved", []):
        assert row["followup"] == followup_of(row["rule"])
    assert document["counts"]["unresolved_state_open"] == len(document.get("unresolved", []))
