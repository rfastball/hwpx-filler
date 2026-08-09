"""P1-02A 정적 그래프 축 — MRO 해소·구조적 디스패치 복원·SCC/hotspot 파생·digest 핀 원장.

기반 수집기(#512)가 남긴 미해결 좌표를 **제품 코드 접촉 없이** 정적으로 닫을 수 있는 만큼만
닫는다: 폐포 안 상속(C3)으로 self 호출을 부모 메서드에 잇고, ``?:prefix:``/``?:table:``
구조 좌표를 소유 클래스 MRO 의 메서드 목록으로 확장한다. 그래도 남는 것은 전수 원장으로
P1-02B·runtime trace 에 귀속한다 — 임의 callee 추측 금지 불변식은 여기서도 유효하다.

커밋 생성물은 전 사실이 아니라 **baseline SHA + digest 핀 + 파생 원장**이다(설계 패킷 §2.4):
사실 8천+행을 모두 커밋하지 않고, 결정론 재생성 digest 로 P1-03 이 같은 측정을 재현했는지
검증한다. baseline SHA 는 측정한 production ``src/`` 스냅숏으로 고정하고 현재 HEAD 를 자동
삽입하지 않는다 — 무관한 문서·테스트 커밋마다 원장이 드리프트하는 회로를 피한다.
"""

from __future__ import annotations

import ast
import json
import subprocess
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .closure import Closure, production_closure
from .collect import COLLECTOR as BASE_COLLECTOR
from .collect import (
    collect_facts,
    collect_symbols,
    import_binding_anchor,
    import_bound_name,
    import_original_name,
    runtime_module_exports,
)
from .schema import (
    Fact,
    FactGraphError,
    Provenance,
    Symbol,
    facts_digest,
    is_symbol_ref,
    parse_symbol_id,
    symbol_id,
)

COLLECTOR = "factgraph.static_graph"

BASELINE_SHA = "a5e1f784f9f0142adf7d04f29023cc805f60f968"

LEDGER_REL_PATH = "docs/factgraph/static_graph_02a.toml"
REGEN_COMMAND = "uv run python scripts/gen_static_graph_02a.py"

#: 미해결 rule → 후속 확인 경로 귀속표(#513 완료 조건 — 미해결마다 후속 경로가 선다).
#: 여기 없고 접두 규칙에도 안 걸리는 rule 이 원장에 나타나면 render 가 시끄럽게 죽는다 —
#: 소유자 없는 미해결이 조용히 쌓이는 길을 막는다.
FOLLOWUP_OF_RULE: dict[str, str] = {
    "call_local_binding": "P1-02B 데이터플로(지역 바인딩 추적) 또는 runtime trace",
    "call_via_local": "P1-02B 데이터플로 또는 runtime trace",
    "call_name_unresolved": "P1-02B 데이터플로 또는 runtime trace",
    "call_self_unresolved": "P1-02B 주입 콜백·인스턴스 필드 계측(생성자 1-hop) 또는 runtime trace",
    "call_self_chain": "P1-02B 상태·필드 계측",
    "call_super_unresolved": "P1-02A 폐포 밖 base의 MRO 또는 runtime trace",
    "call_attr_unresolved": "P1-02B 데이터플로 또는 runtime trace",
    "call_class_attr_miss": "P1-02B 클래스 속성 계측",
    "call_module_attr_miss": "P1-02A 모순 후보 — 실재하지 않는 모듈 속성 참조",
    "getattr_dynamic": "runtime trace 또는 P1-02B",
    "setattr_dynamic": "P1-02B 상태 계측",
    "hasattr_dynamic": "P1-02B",
    "delattr_dynamic": "P1-02B 상태 계측",
    "getattr_fstring_self": "P1-02A 복원 실패 좌표 — marker 해체 불능(구조 변화 의심)",
    "getattr_table_self": "P1-02A 복원 실패 좌표 — 표 판독 불능",
    "dynamic_import": "P1-02C 효과 계측",
    "dynamic_exec": "P1-02C 효과 계측",
    "import_star": "P1-02A 모순 후보 — 폐포 안 별 import",
    "import_from": "P1-02A 모순 후보 — 상수·재수출 해석 후에도 남은 부재 이름 import",
    "import_from_type_checking": "P1-02A 모순 후보 — TYPE_CHECKING 블록의 부재 이름 import",
    "class_base": "P1-02A 폐포 밖/동적 base 확인 또는 runtime trace",
    "decorator": "P1-02A 데코레이터 바인딩 확인 또는 runtime trace",
}


def followup_of(rule: str) -> str:
    exact = FOLLOWUP_OF_RULE.get(rule)
    if exact is not None:
        return exact
    if rule.startswith("call_shape:"):
        return "runtime trace(비정형 호출식)"
    raise FactGraphError(
        f"후속 귀속 없는 미해결 rule: {rule!r} — FOLLOWUP_OF_RULE 에 소유자를 등록하라"
    )


@dataclass(frozen=True)
class DispatchSite:
    kind: str  # "prefix" | "table"
    src: str  # 디스패치가 일어나는 심볼 ID
    owner: str  # "{module}:{class qualname}"
    key: str  # 접두 또는 표 속성 이름
    restored: tuple[str, ...]  # 복원된 대상 메서드 심볼 ID(정렬)
    file: str
    line: int
    anchor: str


@dataclass
class StaticGraphResult:
    closure: Closure
    symbols: tuple[Symbol, ...]
    base_facts: tuple[Fact, ...]
    derived_facts: tuple[Fact, ...]
    base_digest: str
    graph_digest: str
    # 이름이 mro 면 type.mro 메서드를 dataclass 가 기본값으로 오인한다 — mro_map 으로 둔다.
    # 폐포 밖 base(ext:/?:)도 순서 장벽으로 보존한다. 그 앞을 건너 내부 메서드를
    # STATIC_CONFIRMED 로 과신하지 않는 것이 이 부분 MRO의 핵심이다.
    mro_map: "dict[str, tuple[str, ...]]"  # class sid → 부분 MRO(자기·외부 장벽 포함)
    mro_failures: tuple[str, ...]
    dispatch_sites: tuple[DispatchSite, ...]
    table_misses: tuple[str, ...] = field(default_factory=tuple)

    @property
    def facts(self) -> tuple[Fact, ...]:
        return tuple(sorted({*self.base_facts, *self.derived_facts}, key=Fact.sort_key))


def build(repo_root: Path) -> StaticGraphResult:
    repo_root = Path(repo_root)
    closure = production_closure(repo_root)
    symbols = collect_symbols(repo_root, closure)
    runtime_exports = runtime_module_exports(repo_root, closure, symbols)
    base_facts = collect_facts(
        repo_root, closure, symbols, runtime_exports=runtime_exports
    )
    instance_writes = _instance_attribute_writes(base_facts)
    base_facts = _downgrade_shadowed_direct_self_calls(base_facts, instance_writes)
    index = {(s.module, s.qualname): s for s in symbols}

    reexport_facts = _resolve_reexports(base_facts, runtime_exports)
    reexport_use_facts = _resolve_reexport_uses(
        base_facts, reexport_facts, index, runtime_exports
    )
    structural_facts = tuple(
        sorted({*base_facts, *reexport_facts, *reexport_use_facts}, key=Fact.sort_key)
    )
    duplicate_classes = _duplicate_class_sids(repo_root, closure)
    mro_map, mro_failures = _linearize_all(
        symbols, structural_facts, ambiguous_class_sids=duplicate_classes
    )
    methods = _methods_by_class(symbols)
    base_facts = _downgrade_polymorphic_direct_self_calls(
        base_facts, mro_map, methods, instance_writes
    )

    derived: list[Fact] = [*reexport_facts, *reexport_use_facts]
    derived.extend(
        _resolve_self_calls(base_facts, index, mro_map, methods, instance_writes)
    )
    derived.extend(_resolve_super_calls(base_facts, index, mro_map, methods))
    sites, table_misses, dispatch_facts = _restore_dispatch(
        repo_root, base_facts, index, mro_map, methods
    )
    derived.extend(dispatch_facts)
    base_digest = facts_digest([s.id for s in symbols], base_facts)
    all_facts = tuple(sorted({*base_facts, *derived}, key=Fact.sort_key))
    graph_digest = facts_digest([s.id for s in symbols], all_facts)
    return StaticGraphResult(
        closure=closure,
        symbols=symbols,
        base_facts=base_facts,
        derived_facts=tuple(sorted(set(derived), key=Fact.sort_key)),
        base_digest=base_digest,
        graph_digest=graph_digest,
        mro_map=mro_map,
        mro_failures=mro_failures,
        dispatch_sites=sites,
        table_misses=table_misses,
    )


# ---------------------------------------------------------------------------
# 상속·MRO
# ---------------------------------------------------------------------------


def _linearize_all(
    symbols: tuple[Symbol, ...],
    facts: tuple[Fact, ...],
    *,
    ambiguous_class_sids: "set[str] | frozenset[str]" = frozenset(),
) -> "tuple[dict[str, tuple[str, ...]], tuple[str, ...]]":
    class_sids = {s.id for s in symbols if s.kind == "class"}
    bases: dict[str, list[str]] = {sid: [] for sid in class_sids}
    ordered: dict[str, dict[int, list[Fact]]] = {}
    for f in facts:
        if f.rel == "inherits" and f.src in class_sids:
            try:
                position = int(f.evidence.anchor or "0")
            except ValueError as exc:
                raise FactGraphError(
                    f"inherits base 순서가 정수가 아니다: {f.src} {f.evidence.anchor!r}"
                ) from exc
            ordered.setdefault(f.src, {}).setdefault(position, []).append(f)
    # 동일 stable SID의 ClassDef가 두 좌표에 있으면 base/method inventory를 definition별로
    # 분리하지 않는 v1 그래프에서는 서로 존재 불가능한 branch 조합을 만들 수 있다. 완전한
    # definition identity가 생기기 전에는 MRO 파생을 보수적으로 막는다.
    ambiguous_classes = set(ambiguous_class_sids)
    for sid, rows in ordered.items():
        selected: list[str] = []
        for position, candidates in sorted(rows.items()):
            # 재수출 파생은 같은 source 좌표의 UNKNOWN base 를 닫는 replacement 다. 반면
            # 조건부로 같은 qualname class 가 여러 번 정의돼 서로 다른 좌표에서 같은 base
            # slot 을 채운 경우에는 가능한 branch 전체를 보존해야 한다. 좌표별로 먼저 닫힌
            # 파생을 우선한 뒤 좌표 사이 target 집합을 비교해야 두 경우를 혼동하지 않는다.
            by_site: dict[tuple[str, int, str], list[Fact]] = {}
            for fact in candidates:
                site = (fact.evidence.file, fact.evidence.line, fact.evidence.anchor)
                by_site.setdefault(site, []).append(fact)
            targets: set[str] = set()
            for site_facts in by_site.values():
                resolved = {
                    fact.dst
                    for fact in site_facts
                    if fact.provenance.rule
                    in {
                        "inherits_reexport",
                        "inherits_reexport_attr",
                        "inherits_module_reexport",
                    }
                }
                targets.update(resolved or {fact.dst for fact in site_facts})
            if len(targets) != 1:
                ambiguous_classes.add(sid)
                selected.append(f"?:ambiguous_base:{sid}:{position}")
            else:
                selected.append(next(iter(targets)))
        bases[sid] = selected

    mro: dict[str, tuple[str, ...]] = {}
    failures: list[str] = []

    def linearize(sid: str, seen: "tuple[str, ...]") -> "tuple[str, ...] | None":
        if sid in mro:
            return mro[sid]
        if sid in ambiguous_classes:
            return None
        if sid in seen:
            return None  # 순환 상속 — 실코드라면 정의 시점 오류지만, 조용히 넘기지 않는다
        direct = bases.get(sid, [])
        parents: list[list[str]] = []
        for base in direct:
            if base in class_sids:
                lin = linearize(base, (*seen, sid))
                if lin is None:
                    return None
                parents.append(list(lin))
            else:
                # 폐포 밖/미해결 base 의 내부 상속은 알 수 없다. base 자체를 불투명
                # 장벽으로 MRO에 남겨, 그 뒤의 내부 메서드를 확정 호출로 오인하지 않는다.
                parents.append([base])
        merged = _c3_merge([[sid], *parents, direct.copy()])
        if merged is None:
            return None
        mro[sid] = tuple(merged)
        return mro[sid]

    for sid in sorted(class_sids):
        if linearize(sid, ()) is None:
            failures.append(sid)
    return mro, tuple(sorted(failures))


def _duplicate_class_sids(repo_root: Path, closure: Closure) -> set[str]:
    """stable SID로 접히기 전 ClassDef 좌표를 독립 재열거해 중복 definition을 찾는다."""
    counts: dict[str, int] = {}

    def walk(module: str, body: "list[ast.stmt]", prefix: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{node.name}"
                walk(module, node.body, f"{qualname}.<locals>.", False)
            elif isinstance(node, ast.ClassDef):
                qualname = f"{prefix}{node.name}"
                sid = symbol_id(module, qualname, "class")
                counts[sid] = counts.get(sid, 0) + 1
                walk(module, node.body, f"{qualname}.", True)
            else:
                for block in _statement_blocks(node):
                    walk(module, block, prefix, in_class)

    for mf in closure.modules:
        tree = ast.parse((repo_root / mf.path).read_text(encoding="utf-8"))
        walk(mf.module, tree.body, "", False)
    return {sid for sid, count in counts.items() if count > 1}


def _c3_merge(sequences: "list[list[str]]") -> "list[str] | None":
    result: list[str] = []
    seqs = [list(s) for s in sequences if s]
    while seqs:
        head = None
        for seq in seqs:
            candidate = seq[0]
            if not any(candidate in other[1:] for other in seqs):
                head = candidate
                break
        if head is None:
            return None  # C3 불능 — 호출자가 실패 원장에 든다
        result.append(head)
        seqs = [[x for x in seq if x != head] for seq in seqs]
        seqs = [s for s in seqs if s]
    return result


def _methods_by_class(symbols: tuple[Symbol, ...]) -> "dict[str, dict[str, str]]":
    out: dict[str, dict[str, str]] = {}
    class_coord = {
        (s.module, s.qualname): s.id for s in symbols if s.kind == "class"
    }
    for s in symbols:
        if s.kind != "method" or "." not in s.qualname:
            continue
        cls_qual, name = s.qualname.rsplit(".", 1)
        cls_sid = class_coord.get((s.module, cls_qual))
        if cls_sid is not None:
            out.setdefault(cls_sid, {})[name] = s.id
    return out


def _instance_attribute_writes(base_facts: tuple[Fact, ...]) -> set[tuple[str, str]]:
    """해결된 ``self.field = ...`` 좌표를 (class SID, field)로 되읽는다."""
    out: set[tuple[str, str]] = set()
    for fact in base_facts:
        if fact.rel != "writes_attribute" or not fact.dst.startswith("attr:"):
            continue
        body = fact.dst.removeprefix("attr:")
        module, sep, qual_field = body.partition(":")
        owner, dot, field = qual_field.rpartition(".")
        if not sep or not dot or not module or module == "?" or not owner:
            continue
        out.add((symbol_id(module, owner, "class"), field))
    return out


def _downgrade_shadowed_direct_self_calls(
    base_facts: tuple[Fact, ...], instance_writes: set[tuple[str, str]]
) -> tuple[Fact, ...]:
    """known instance field가 같은 이름 method lookup을 가릴 수 있는 direct self edge를 연다."""
    out: list[Fact] = []
    for fact in base_facts:
        if fact.provenance.rule != "call_self" or not is_symbol_ref(fact.dst):
            out.append(fact)
            continue
        module, qualname, kind = parse_symbol_id(fact.dst)
        owner, dot, name = qualname.rpartition(".")
        if kind != "method" or not dot or (symbol_id(module, owner, "class"), name) not in instance_writes:
            out.append(fact)
            continue
        out.append(
            Fact(
                src=fact.src,
                rel="calls",
                dst=f"?:self:{owner}.{name}",
                grade="UNKNOWN",
                evidence=fact.evidence,
                provenance=Provenance(BASE_COLLECTOR, "call_self_unresolved"),
            )
        )
    return tuple(sorted(set(out), key=Fact.sort_key))


def _downgrade_polymorphic_direct_self_calls(
    base_facts: tuple[Fact, ...],
    mro: "dict[str, tuple[str, ...]]",
    methods: "dict[str, dict[str, str]]",
    instance_writes: set[tuple[str, str]],
) -> tuple[Fact, ...]:
    """known subclass가 다른 runtime target을 만들 수 있는 direct self site를 연다.

    lexical class에 같은 이름 method가 있어도 실제 receiver가 subclass면 override 또는
    instance field가 우선한다. 그런 좌표를 단일 direct edge로 닫지 않고 ``?:self`` marker로
    되돌린 뒤, ``_resolve_self_calls``가 known receiver별 후보를 전부 파생하게 한다.
    """
    out: list[Fact] = []
    for fact in base_facts:
        if fact.provenance.rule != "call_self" or not is_symbol_ref(fact.dst):
            out.append(fact)
            continue
        target_module, target_qual, target_kind = parse_symbol_id(fact.dst)
        owner_qual, dot, name = target_qual.rpartition(".")
        if target_kind != "method" or not dot:
            out.append(fact)
            continue
        owner_sid = symbol_id(target_module, owner_qual, "class")
        polymorphic = False
        for receiver_sid, chain in mro.items():
            if receiver_sid == owner_sid or owner_sid not in chain[1:]:
                continue
            if any(
                (ancestor, name) in instance_writes
                for ancestor in chain
                if is_symbol_ref(ancestor)
            ):
                polymorphic = True
                break
            if _lookup_method(receiver_sid, name, mro, methods) != fact.dst:
                polymorphic = True
                break
        if not polymorphic:
            out.append(fact)
            continue
        out.append(
            Fact(
                src=fact.src,
                rel="calls",
                dst=f"?:self:{owner_qual}.{name}",
                grade="UNKNOWN",
                evidence=fact.evidence,
                provenance=Provenance(BASE_COLLECTOR, "call_self_unresolved"),
            )
        )
    return tuple(sorted(set(out), key=Fact.sort_key))


def _lookup_method(
    cls_sid: str,
    name: str,
    mro: "dict[str, tuple[str, ...]]",
    methods: "dict[str, dict[str, str]]",
    skip_own: bool = False,
) -> "str | None":
    chain = mro.get(cls_sid, (cls_sid,))
    for ancestor in chain[1:] if skip_own else chain:
        if not is_symbol_ref(ancestor) or parse_symbol_id(ancestor)[2] != "class":
            return None  # 불투명 base 앞을 건너뛰면 거짓 STATIC_CONFIRMED 가 된다
        found = methods.get(ancestor, {}).get(name)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# 해소·복원 패스
# ---------------------------------------------------------------------------


def _class_sid_of_marker(marker: str, prefix: str) -> "tuple[str, str, str] | None":
    """``?:self:{qual}.{name}`` / ``?:prefix:{module}:{qual}.{key}`` 좌표 해체."""
    body = marker.removeprefix(prefix)
    if body == marker:
        return None
    head, _sep, tail = body.rpartition(".")
    if not head or not tail:
        return None
    module, sep, qual = head.partition(":")
    if not sep:
        return None
    return module, qual, tail


def _resolve_self_calls(
    base_facts: tuple[Fact, ...],
    index: "dict[tuple[str, str], Symbol]",
    mro: "dict[str, tuple[str, ...]]",
    methods: "dict[str, dict[str, str]]",
    instance_writes: set[tuple[str, str]],
) -> "list[Fact]":
    out: list[Fact] = []
    for f in base_facts:
        if f.provenance.rule != "call_self_unresolved":
            continue
        # dst 형식: ?:self:{cls_qual}.{name} — 모듈은 src 심볼이 든다
        body = f.dst.removeprefix("?:self:")
        cls_qual, _sep, name = body.rpartition(".")
        if not cls_qual or not name:
            continue
        module = parse_symbol_id(f.src)[0]
        cls_sym = index.get((module, cls_qual))
        if cls_sym is None:
            continue
        receivers = [cls_sym.id]
        receivers.extend(
            receiver_sid
            for receiver_sid, chain in mro.items()
            if receiver_sid != cls_sym.id and cls_sym.id in chain[1:]
        )
        for receiver_sid in receivers:
            chain = mro.get(receiver_sid, (receiver_sid,))
            if any(
                (ancestor, name) in instance_writes
                for ancestor in chain
                if is_symbol_ref(ancestor)
            ):
                continue
            found = _lookup_method(receiver_sid, name, mro, methods)
            if found is None:
                continue
            out.append(
                Fact(
                    src=f.src,
                    rel="calls",
                    dst=found,
                    grade="INFERRED",
                    evidence=f.evidence,
                    provenance=Provenance(COLLECTOR, "call_self_mro"),
                )
            )
    return out


def _resolve_super_calls(
    base_facts: tuple[Fact, ...],
    index: "dict[tuple[str, str], Symbol]",
    mro: "dict[str, tuple[str, ...]]",
    methods: "dict[str, dict[str, str]]",
) -> "list[Fact]":
    """``super().method``를 내부 partial MRO에서만 닫는다.

    폐포 밖/미해결 base는 ``_lookup_method``의 불투명 장벽으로 남아 임의의 뒤쪽 내부
    메서드까지 건너뛰지 않는다. 그런 좌표는 전용 ``call_super_unresolved`` 행으로 후속
    원장에 남는다.
    """
    out: list[Fact] = []
    for fact in base_facts:
        if fact.provenance.rule != "call_super_unresolved":
            continue
        body = fact.dst.removeprefix("?:super:")
        cls_qual, _sep, name = body.rpartition(".")
        if not cls_qual or not name:
            continue
        module = parse_symbol_id(fact.src)[0]
        cls_sym = index.get((module, cls_qual))
        if cls_sym is None:
            continue
        found = _lookup_method(cls_sym.id, name, mro, methods, skip_own=True)
        if found is None:
            continue
        out.append(
            Fact(
                src=fact.src,
                rel="calls",
                dst=found,
                grade="INFERRED",
                evidence=fact.evidence,
                provenance=Provenance(COLLECTOR, "call_super_mro"),
            )
        )
    return out


def _restore_dispatch(
    repo_root: Path,
    base_facts: tuple[Fact, ...],
    index: "dict[tuple[str, str], Symbol]",
    mro: "dict[str, tuple[str, ...]]",
    methods: "dict[str, dict[str, str]]",
) -> "tuple[tuple[DispatchSite, ...], tuple[str, ...], list[Fact]]":
    sites: list[DispatchSite] = []
    misses: list[str] = []
    out: list[Fact] = []
    invoked_getattrs = _invoked_getattr_sites(repo_root, base_facts)
    for f in base_facts:
        if f.provenance.rule == "getattr_fstring_self":
            key_site = (f.evidence.file, f.evidence.line, f.evidence.anchor)
            if key_site not in invoked_getattrs:
                continue
            parsed = _class_sid_of_marker(f.dst, "?:prefix:")
            if parsed is None:
                misses.append(f.dst)
                continue
            module, cls_qual, key = parsed
            cls_sid = symbol_id(module, cls_qual, "class")
            if cls_sid not in mro:
                misses.append(f"{f.dst} -> MRO/definition ambiguity")
                continue
            targets = _prefix_targets(cls_sid, key, mro, methods)
            sites.append(
                DispatchSite(
                    "prefix",
                    f.src,
                    f"{module}:{cls_qual}",
                    key,
                    targets,
                    f.evidence.file,
                    f.evidence.line,
                    f.evidence.anchor,
                )
            )
            out.extend(_dispatch_fact(f, t, "prefix_dispatch") for t in targets)
        elif f.provenance.rule == "getattr_table_self":
            key_site = (f.evidence.file, f.evidence.line, f.evidence.anchor)
            if key_site not in invoked_getattrs:
                continue
            parsed = _class_sid_of_marker(f.dst, "?:table:")
            if parsed is None:
                misses.append(f.dst)
                continue
            module, cls_qual, key = parsed
            cls_sid = symbol_id(module, cls_qual, "class")
            if cls_sid not in mro:
                misses.append(f"{f.dst} -> MRO/definition ambiguity")
                continue
            values = _read_table_literal(repo_root, index, mro, module, cls_qual, key)
            if values is None:
                misses.append(f.dst)
                continue
            targets = []
            for name in values:
                found = _lookup_method(cls_sid, name, mro, methods)
                if found is None:
                    misses.append(f"{f.dst} -> 표 값 {name!r} 이 MRO 에 없다")
                    continue
                targets.append(found)
            targets = tuple(sorted(set(targets)))
            sites.append(
                DispatchSite(
                    "table",
                    f.src,
                    f"{module}:{cls_qual}",
                    key,
                    targets,
                    f.evidence.file,
                    f.evidence.line,
                    f.evidence.anchor,
                )
            )
            out.extend(_dispatch_fact(f, t, "table_dispatch") for t in targets)
    sites.sort(key=lambda s: (s.owner, s.kind, s.key, s.src, s.file, s.line, s.anchor))
    return tuple(sites), tuple(sorted(set(misses))), out


def _invoked_getattr_sites(
    repo_root: Path, base_facts: tuple[Fact, ...]
) -> set[tuple[str, int, str]]:
    """결과가 곧바로 호출되는 ``getattr(...)(...)`` inner-call 좌표만 반환한다."""
    files = {
        fact.evidence.file
        for fact in base_facts
        if fact.provenance.rule in ("getattr_fstring_self", "getattr_table_self")
    }
    invoked: set[tuple[str, int, str]] = set()
    for file in files:
        tree = ast.parse((repo_root / file).read_text(encoding="utf-8"))
        for parent in ast.walk(tree):
            if not isinstance(parent, ast.Call) or not isinstance(parent.func, ast.Call):
                continue
            inner = parent.func
            if isinstance(inner.func, ast.Name) and inner.func.id == "getattr":
                invoked.add((file, inner.lineno, _oracle_syntax_anchor(inner)))

        scopes: list[ast.AST] = [tree]
        scopes.extend(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

        class ScopeUseVisitor(ast.NodeVisitor):
            def __init__(self, root: ast.AST) -> None:
                self.root = root
                self.assignments: dict[str, list[ast.AST]] = {}
                self.calls: dict[str, list[tuple[int, int]]] = {}

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node is self.root:
                    self.generic_visit(node)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                if node is self.root:
                    self.generic_visit(node)

            def visit_Assign(self, node: ast.Assign) -> None:
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value = node.value
                for name in targets:
                    if (
                        isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Name)
                        and value.func.id == "getattr"
                    ):
                        self.assignments.setdefault(name, []).append(value)
                    else:
                        self.assignments.setdefault(name, []).append(node)
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if isinstance(node.target, ast.Name):
                    value = node.value
                    if (
                        isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Name)
                        and value.func.id == "getattr"
                    ):
                        self.assignments.setdefault(node.target.id, []).append(value)
                    else:
                        self.assignments.setdefault(node.target.id, []).append(node)
                self.generic_visit(node)

            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Name):
                    self.calls.setdefault(node.func.id, []).append(
                        (node.lineno, node.col_offset)
                    )
                self.generic_visit(node)

        for scope in scopes:
            visitor = ScopeUseVisitor(scope)
            visitor.visit(scope)
            for name, assignments in visitor.assignments.items():
                if len(assignments) != 1 or name not in visitor.calls:
                    continue  # 재할당/branch가 있으면 어느 callable이 불리는지 추측하지 않는다
                assignment = assignments[0]
                if not (
                    isinstance(assignment, ast.Call)
                    and isinstance(assignment.func, ast.Name)
                    and assignment.func.id == "getattr"
                ):
                    continue
                if any(
                    call_position > (assignment.lineno, assignment.col_offset)
                    for call_position in visitor.calls[name]
                ):
                    invoked.add(
                        (file, assignment.lineno, _oracle_syntax_anchor(assignment))
                    )
    return invoked


def _dispatch_fact(site_fact: Fact, target: str, rule: str) -> Fact:
    return Fact(
        src=site_fact.src,
        rel="calls",
        dst=target,
        grade="DECLARED_DYNAMIC",
        evidence=site_fact.evidence,
        provenance=Provenance(COLLECTOR, rule),
    )


def _prefix_targets(
    cls_sid: str,
    prefix: str,
    mro: "dict[str, tuple[str, ...]]",
    methods: "dict[str, dict[str, str]]",
) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for ancestor in mro.get(cls_sid, (cls_sid,)):
        if not is_symbol_ref(ancestor) or parse_symbol_id(ancestor)[2] != "class":
            break
        for name, sid in methods.get(ancestor, {}).items():
            if name.startswith(prefix) and name not in seen:
                seen[name] = sid  # MRO 앞선 정의가 이긴다
    return tuple(sorted(seen.values()))


def _read_table_literal(
    repo_root: Path,
    index: "dict[tuple[str, str], Symbol]",
    mro: "dict[str, tuple[str, ...]]",
    module: str,
    cls_qual: str,
    attr: str,
) -> "tuple[str, ...] | None":
    """클래스(또는 MRO 조상)가 소유한 str→str 리터럴 표의 값 목록 — 못 찾으면 None(loud)."""
    cls_sid = symbol_id(module, cls_qual, "class")
    for ancestor in mro.get(cls_sid, (cls_sid,)):
        if not is_symbol_ref(ancestor) or parse_symbol_id(ancestor)[2] != "class":
            break
        anc_module, anc_qual, _kind = parse_symbol_id(ancestor)
        anc_sym = index.get((anc_module, anc_qual))
        if anc_sym is None:
            continue
        values = _table_in_class(repo_root / anc_sym.file, anc_qual, attr)
        if values is not None:
            return values
    return None


def _table_in_class(path: Path, cls_qual: str, attr: str) -> "tuple[str, ...] | None":
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:  # pragma: no cover - closure 가 이미 파싱을 보장
        raise FactGraphError(f"표 판독 실패: {path} ({exc})") from exc

    def find(body: "list[ast.stmt]", prefix: str) -> "tuple[str, ...] | None":
        for node in body:
            if isinstance(node, ast.ClassDef):
                qual = f"{prefix}{node.name}"
                if qual == cls_qual:
                    return read_table(node.body)
                nested = find(node.body, f"{qual}.")
                if nested is not None:
                    return nested
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{node.name}"
                nested = find(node.body, f"{qual}.<locals>.")
                if nested is not None:
                    return nested
            else:
                for block in _statement_blocks(node):
                    nested = find(block, prefix)
                    if nested is not None:
                        return nested
        return None

    def read_table(body: "list[ast.stmt]") -> "tuple[str, ...] | None":
        assignments: list[ast.expr | None] = []
        for node in body:
            target = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            if not (isinstance(target, ast.Name) and target.id == attr):
                continue
            assignments.append(getattr(node, "value", None))
        if len(assignments) != 1:
            return None  # 0 또는 재할당/branch 후보 — 어느 값이 runtime 표인지 추측하지 않는다
        value = assignments[0]
        if isinstance(value, ast.Dict) and all(
                isinstance(k, ast.Constant)
                and isinstance(k.value, str)
                and isinstance(v, ast.Constant)
                and isinstance(v.value, str)
                for k, v in zip(value.keys, value.values, strict=True)
        ):
            return tuple(v.value for v in value.values)  # type: ignore[union-attr]
        return None  # 표는 있는데 리터럴 str→str 이 아니다 — 복원하지 않는다(loud)

    return find(tree.body, "")


def _statement_blocks(node: ast.stmt) -> "list[list[ast.stmt]]":
    """조건부/try/match 안 정의도 심볼 수집기와 같은 qualname으로 찾는다."""
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


def _runtime_import_target(fact: Fact) -> "str | None":
    """import fact의 dependency target을 실제 runtime bound object로 정규화한다.

    ``import a.b``는 ``a.b``에 의존하지만 현재 scope에 묶이는 객체는 root package ``a``다.
    이 차이를 무시하면 그 이름을 다시 export할 때 ``a.b``를 거짓 runtime facade로 만든다.
    내부 root module은 안정 ID로 복원하고, 폐포 밖 dotted import는 target kind를 증명할 수
    없으므로 재수출 표에서 제외해 loud UNKNOWN으로 남긴다.
    """
    target = fact.dst
    if fact.provenance.rule != "import_plain" or not fact.evidence.anchor:
        return target
    bound = import_bound_name(fact.evidence.anchor)
    imported = import_original_name(fact.evidence.anchor)
    if imported == bound or not imported.startswith(f"{bound}."):
        return target  # alias가 있거나 dotted import가 아니다
    if is_symbol_ref(target) and parse_symbol_id(target)[2] == "module":
        return symbol_id(bound, "", "module")
    return None


def _resolve_reexports(
    base_facts: tuple[Fact, ...],
    runtime_exports: "dict[tuple[str, str], frozenset[str]]",
) -> "list[Fact]":
    """``__init__`` 경유 재수출 import 의 해소 — 별칭은 import 사실의 anchor(결속 이름)로 복원.

    폐포 모듈이 모듈 수준 import 로 묶은 이름을 수출 표로 보고, 그 이름을 가져오는 미해결
    import 를 원 좌표로 잇는다. 사슬 재수출은 데이터 크기로 제한된 고정점까지 닫고, 그래도
    남거나 둘 이상 후보가 생기면 미해결 그대로 둔다 — 임의 추측 금지.
    """
    open_rows = [
        f
        for f in base_facts
        if f.grade == "UNKNOWN"
        and f.dst.startswith("?:name:")
        and f.provenance.rule.startswith("import_from")
        and not f.provenance.rule.endswith("_type_checking")
    ]

    derived: list[Fact] = []
    for fact in open_rows:
        base, _sep, name = fact.dst.removeprefix("?:name:").rpartition(".")
        targets = runtime_exports.get((base, name), frozenset())
        if len(targets) != 1:
            continue  # 0은 미해결, 2+는 branch ambiguity — 둘 다 임의 선택 금지
        target = next(iter(targets))
        if target.startswith("?:"):
            continue
        relation = (
            "imports_module"
            if is_symbol_ref(target) and parse_symbol_id(target)[2] == "module"
            else "imports_symbol"
        )
        derived.append(
            Fact(
                src=fact.src,
                rel=relation,
                dst=target,
                grade="STATIC_CONFIRMED",
                evidence=fact.evidence,
                provenance=Provenance(COLLECTOR, "import_reexport"),
            )
        )
    return derived


def _resolve_reexport_uses(
    base_facts: tuple[Fact, ...],
    reexport_facts: "list[Fact]",
    index: "dict[tuple[str, str], Symbol]",
    runtime_exports: "dict[tuple[str, str], frozenset[str]]",
) -> "list[Fact]":
    """재수출로 닫힌 import 바인딩을 base/decorator/call/constructor 사용까지 전파한다.

    기반 수집기는 모듈-국소 한 겹만 보므로 ``from package import Reexported``를 처음에는
    UNKNOWN으로 남기는 것이 정직하다. 02A가 원 수출을 확인한 뒤에도 그 이름의 사용을
    미해결로 방치하면 constructor/MRO edge가 빠진다. 모듈 import는 같은 모듈 전체에,
    함수-로컬 import는 그 심볼 안에서만 적용해 과도한 스코프 전파를 피한다.
    """
    module_bindings: dict[tuple[str, str], list[tuple[str, int]]] = {}
    local_bindings: dict[tuple[str, str], list[tuple[str, int]]] = {}
    module_exports: dict[tuple[str, str], set[str]] = {
        key: {next(iter(targets))}
        for key, targets in runtime_exports.items()
        if len(targets) == 1 and not next(iter(targets)).startswith("?:")
    }
    # 직접 import도 root module 바인딩과 그 모듈이 재노출하는 member의 증거다. 재수출
    # 파생만 넣으면 ``import settings; settings.home_dir()`` 같은 facade 경로가 열린다.
    for fact in (*base_facts, *reexport_facts):
        if not fact.evidence.anchor:
            continue
        if fact.rel not in ("imports_symbol", "imports_module") or fact.dst.startswith("?:"):
            continue
        if fact.provenance.rule.endswith("_type_checking"):
            continue
        target = _runtime_import_target(fact)
        if target is None:
            continue
        module, _qual, kind = parse_symbol_id(fact.src)
        bound = import_bound_name(fact.evidence.anchor)
        key = (module, bound) if kind == "module" else (fact.src, bound)
        if kind == "module":
            module_bindings.setdefault(key, []).append((target, fact.evidence.line))
        else:
            local_bindings.setdefault(key, []).append((target, fact.evidence.line))

    def unique_target(
        points: "list[tuple[str, int]] | None", fact: Fact, *, require_prior: bool
    ) -> "str | None":
        if not points:
            return None
        eligible = [target for target, line in points if not require_prior or line <= fact.evidence.line]
        targets = set(eligible)
        return next(iter(targets)) if len(targets) == 1 else None

    def binding_for(fact: Fact, name: str, *, local_only: bool = False) -> "str | None":
        module, qualname, source_kind = parse_symbol_id(fact.src)
        definition_time = fact.rel == "inherits" or fact.provenance.rule == "decorator"
        local_points = local_bindings.get((fact.src, name))
        if local_points is not None:
            # 함수 local은 compile-time에 outer lookup을 가리고, class namespace도
            # 조건부 local 후보가 있으면 module target 하나로 임의 fallback할 수 없다.
            return unique_target(local_points, fact, require_prior=True)
        # 함수 안 import는 그 함수의 local class/function까지 lexical하게 보인다. 가장
        # 가까운 소유자를 택하되 다른 함수·클래스로 새지 않게 ``.<locals>.`` 경계만 따른다.
        nested_candidates: list[tuple[int, str]] = []
        for (owner_sid, bound), points in local_bindings.items():
            if bound != name:
                continue
            owner_module, owner_qual, owner_kind = parse_symbol_id(owner_sid)
            if owner_module != module or owner_kind not in ("function", "method"):
                continue
            if qualname.startswith(f"{owner_qual}.<locals>."):
                target = unique_target(points, fact, require_prior=definition_time)
                if target is not None:
                    nested_candidates.append((len(owner_qual), target))
        if nested_candidates:
            return max(nested_candidates)[1]
        if local_only:
            return None
        if source_kind in {"function", "method"} and not definition_time:
            # 함수 body의 global lookup은 module 초기화가 끝난 namespace를 본다.
            # 조건부 import fact 한 줄만 보고 닫으면 ``if flag: import x as len``의
            # false branch(내장 len)를 잃으므로 최종 runtime 후보가 유일할 때만 전파한다.
            final_targets = runtime_exports.get((module, name), frozenset())
            if len(final_targets) != 1:
                return None
            final_target = next(iter(final_targets))
            return None if final_target.startswith("?:") else final_target
        return unique_target(
            module_bindings.get((module, name)),
            fact,
            require_prior=definition_time or source_kind in {"module", "class"},
        )

    out: list[Fact] = []
    for fact in base_facts:
        if fact.grade != "UNKNOWN":
            continue
        target: str | None = None
        relation: str | None = None
        rule: str | None = None
        grade = "STATIC_CONFIRMED"
        if fact.provenance.rule == "call_module_attr_miss" and fact.dst.startswith("?:name:"):
            module, sep, attr = fact.dst.removeprefix("?:name:").rpartition(".")
            if not sep:
                continue
            exported = module_exports.get((module, attr), set())
            if len(exported) != 1:
                continue
            target = next(iter(exported))
            if not is_symbol_ref(target):
                continue
            target_kind = parse_symbol_id(target)[2]
            relation = "constructs" if target_kind == "class" else "calls"
            rule = (
                "construct_module_reexport"
                if relation == "constructs"
                else "call_module_reexport"
            )
        elif (
            fact.provenance.rule in {"class_base", "decorator"}
            and fact.dst.startswith("?:name:")
            and "." in fact.dst.removeprefix("?:name:")
            and fact.rel in {"calls", "inherits"}
        ):
            module, sep, attr = fact.dst.removeprefix("?:name:").rpartition(".")
            if not sep:
                continue
            exported = module_exports.get((module, attr), set())
            if len(exported) != 1:
                continue
            target = next(iter(exported))
            if not is_symbol_ref(target):
                continue
            target_kind = parse_symbol_id(target)[2]
            if fact.rel == "inherits":
                if target_kind != "class":
                    continue
                relation, rule = "inherits", "inherits_module_reexport"
            else:
                relation, rule = "calls", "decorator_module_reexport"
        elif fact.dst.startswith(("?:name:", "?:local:")) and fact.rel in ("calls", "inherits"):
            prefix = "?:name:" if fact.dst.startswith("?:name:") else "?:local:"
            name = fact.dst.removeprefix(prefix)
            if "." in name:
                continue  # import fact 자체의 fully-qualified 미해결 좌표는 별도 파생이 닫는다
            target = binding_for(fact, name, local_only=prefix == "?:local:")
            if target is None or not is_symbol_ref(target):
                continue
            target_kind = parse_symbol_id(target)[2]
            if fact.rel == "inherits":
                if target_kind != "class":
                    continue
                relation, rule = "inherits", "inherits_reexport"
            else:
                relation = "constructs" if target_kind == "class" else "calls"
                rule = "construct_reexport" if relation == "constructs" else "call_reexport"
            if prefix == "?:local:":
                grade = "INFERRED"
        elif fact.dst.startswith(("?:attr:", "?:local:")) and fact.rel in ("calls", "inherits"):
            prefix = "?:attr:" if fact.dst.startswith("?:attr:") else "?:local:"
            body = fact.dst.removeprefix(prefix)
            root, sep, attr = body.partition(".")
            if not sep:
                continue
            owner = binding_for(fact, root, local_only=prefix == "?:local:")
            if owner is None or not is_symbol_ref(owner):
                continue
            module, qualname, kind = parse_symbol_id(owner)
            if kind == "class":
                member = index.get((module, f"{qualname}.{attr}"))
            elif kind == "module":
                member = index.get((module, attr))
                if member is None:
                    exported = module_exports.get((module, attr), set())
                    if len(exported) == 1 and is_symbol_ref(next(iter(exported))):
                        exported_target = next(iter(exported))
                        exported_module, exported_qual, exported_kind = parse_symbol_id(
                            exported_target
                        )
                        member = index.get((exported_module, exported_qual))
                        if member is None and exported_kind == "module":
                            member = index.get((exported_module, ""))
            else:
                continue
            if member is None:
                continue
            target = member.id
            if fact.rel == "inherits":
                if member.kind != "class":
                    continue
                relation, rule = "inherits", "inherits_reexport_attr"
            else:
                relation = "constructs" if member.kind == "class" else "calls"
                rule = (
                    "construct_reexport_attr" if relation == "constructs" else "call_reexport_attr"
                )
            if prefix == "?:local:":
                grade = "INFERRED"
        if target is None or relation is None or rule is None:
            continue
        out.append(
            Fact(
                src=fact.src,
                rel=relation,
                dst=target,
                grade=grade,
                evidence=fact.evidence,
                provenance=Provenance(COLLECTOR, rule),
            )
        )
    return out


# ---------------------------------------------------------------------------
# 파생 산출 — SCC·fan·hotspot·미해결 원장
# ---------------------------------------------------------------------------


def module_import_edges(facts: tuple[Fact, ...]) -> "dict[str, set[str]]":
    edges: dict[str, set[str]] = {}
    for f in facts:
        src_module = parse_symbol_id(f.src)[0]
        if f.provenance.rule == "import_star" and f.dst.startswith("?:star:"):
            dst_module = f.dst.removeprefix("?:star:")
        elif f.rel not in ("imports_module", "imports_symbol"):
            continue
        elif is_symbol_ref(f.dst):
            dst_module = parse_symbol_id(f.dst)[0]
        elif f.dst.startswith("attr:"):
            # 내부 모듈 상수 import는 symbol이 아니라 ``attr:<module>:<name>`` 좌표다.
            # import edge에서는 그 소유 모듈을 되살려 상수 의존이 그래프에서 사라지지 않게 한다.
            dst_module, sep, _name = f.dst.removeprefix("attr:").rpartition(":")
            if not sep:
                continue
        elif f.dst.startswith("?:name:") and f.provenance.rule.startswith("import_from"):
            # ``from facade import reexport``는 origin symbol 파생과 별개로 source가 직접
            # 의존한 facade edge를 보존한다. 미해결/재수출이라는 이유로 import 방향을
            # 원본 구현 module 하나로 치환하면 SCC·경계 질의가 거짓이 된다.
            dst_module, sep, _name = f.dst.removeprefix("?:name:").rpartition(".")
            if not sep:
                continue
        else:
            continue
        if src_module != dst_module:
            edges.setdefault(src_module, set()).add(dst_module)
    return edges


def nontrivial_sccs(edges: "dict[str, set[str]]") -> "tuple[tuple[str, ...], ...]":
    """Tarjan(반복형) — 크기 2 이상의 강결합 성분만 정렬해 낸다."""
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[tuple[str, ...]] = []
    counter = 0
    nodes = sorted(set(edges) | {d for ds in edges.values() for d in ds})
    for root in nodes:
        if root in order:
            continue
        work: list[tuple[str, Iterator[str]]] = [(root, iter(sorted(edges.get(root, ()))))]
        order[root] = low[root] = counter = counter + 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in order:
                    order[child] = low[child] = counter = counter + 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(edges.get(child, ())))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], order[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == order[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    sccs.append(tuple(sorted(component)))
    return tuple(sorted(sccs))


def fan_metrics(facts: tuple[Fact, ...]) -> "tuple[dict[str, int], dict[str, int], dict[str, int]]":
    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = {}
    construction_sites: dict[str, set[tuple[str, str, int, str]]] = {}
    for f in facts:
        if f.rel not in ("calls", "constructs") or not is_symbol_ref(f.dst):
            continue
        outgoing.setdefault(f.src, set()).add(f.dst)
        incoming.setdefault(f.dst, set()).add(f.src)
        if f.rel == "constructs":
            construction_sites.setdefault(f.src, set()).add(
                (f.dst, f.evidence.file, f.evidence.line, f.evidence.anchor)
            )
    fan_out = {src: len(targets) for src, targets in outgoing.items()}
    fan_in = {dst: len(sources) for dst, sources in incoming.items()}
    constructs = {src: len(sites) for src, sites in construction_sites.items()}
    return fan_out, fan_in, constructs


def _open_unresolved_partitions(
    result: StaticGraphResult,
) -> "tuple[tuple[Fact, ...], tuple[Fact, ...], tuple[Fact, ...]]":
    """(동적 자리, MRO 후 self 호출, 그 밖의 UNKNOWN) 전수 — 닫힌 기반 행만 제외."""
    # 한 행에 해소·미해소 self 호출이 공존할 수 있어 좌표에 **메서드 이름까지** 넣는다 —
    # 좌표 충돌로 열린 항목이 조용히 닫힌 것처럼 보이면 안 된다.
    resolved_sites = {
        (
            f.src,
            f.evidence.file,
            f.evidence.line,
            f.evidence.anchor,
            parse_symbol_id(f.dst)[1].rsplit(".", 1)[-1],
        )
        for f in result.derived_facts
        if f.provenance.rule == "call_self_mro" and f.grade == "STATIC_CONFIRMED"
    }
    super_resolved_sites = {
        (f.src, f.evidence.file, f.evidence.line, f.evidence.anchor)
        for f in result.derived_facts
        if f.provenance.rule == "call_super_mro" and f.grade == "STATIC_CONFIRMED"
    }
    restored_sites = {
        (f.src, f.evidence.file, f.evidence.line, f.evidence.anchor)
        for f in result.derived_facts
        if f.provenance.rule in ("prefix_dispatch", "table_dispatch")
    }
    incomplete_table_markers = tuple(result.table_misses)
    reexport_resolved = {
        (f.src, f.evidence.file, f.evidence.line, f.evidence.anchor)
        for f in result.derived_facts
        if f.provenance.rule == "import_reexport"
    }
    reexport_use_resolved = {
        (f.src, f.evidence.file, f.evidence.line, f.evidence.anchor)
        for f in result.derived_facts
        if f.grade == "STATIC_CONFIRMED"
        and f.provenance.rule
        in (
            "call_reexport",
            "construct_reexport",
            "inherits_reexport",
            "call_reexport_attr",
            "construct_reexport_attr",
            "inherits_reexport_attr",
            "call_module_reexport",
            "construct_module_reexport",
            "inherits_module_reexport",
            "decorator_module_reexport",
        )
    }
    dynamic_open: list[Fact] = []
    self_open: list[Fact] = []
    noise: list[Fact] = []
    for f in result.base_facts:
        rule = f.provenance.rule
        key = (f.src, f.evidence.file, f.evidence.line, f.evidence.anchor)
        if f.rel == "dynamic_site":
            table_incomplete = rule == "getattr_table_self" and any(
                miss == f.dst or miss.startswith(f"{f.dst} ->")
                for miss in incomplete_table_markers
            )
            if (
                rule in ("getattr_fstring_self", "getattr_table_self")
                and key in restored_sites
                and not table_incomplete
            ):
                continue  # 복원 완료 — dispatch 절이 든다
            dynamic_open.append(f)
        elif rule == "call_self_unresolved":
            name = f.dst.rsplit(".", 1)[-1]
            if (*key, name) in resolved_sites:
                continue
            self_open.append(f)
        elif rule == "call_super_unresolved":
            if key in super_resolved_sites:
                continue
            noise.append(f)
        elif f.grade == "UNKNOWN":
            if key in reexport_use_resolved:
                continue
            if (
                rule.startswith("import_from")
                and key in reexport_resolved
            ):
                continue  # 재수출 파생이 닫았다
            noise.append(f)
    return (
        tuple(sorted(dynamic_open, key=Fact.sort_key)),
        tuple(sorted(self_open, key=Fact.sort_key)),
        tuple(sorted(noise, key=Fact.sort_key)),
    )


def unresolved_facts(result: StaticGraphResult) -> tuple[Fact, ...]:
    """파생 패스로도 닫히지 않은 UNKNOWN/DECLARED_DYNAMIC 사실의 전수."""
    dynamic_open, self_open, noise = _open_unresolved_partitions(result)
    return tuple(sorted({*dynamic_open, *self_open, *noise}, key=Fact.sort_key))


def open_unresolved(
    result: StaticGraphResult,
) -> "tuple[tuple[Fact, ...], tuple[Fact, ...], dict[str, int]]":
    """호환 요약: (동적 자리, MRO 후 self 호출, 그 밖의 UNKNOWN rule별 계수)."""
    dynamic_open, self_open, noise = _open_unresolved_partitions(result)
    counts: dict[str, int] = {}
    for fact in noise:
        rule = fact.provenance.rule
        counts[rule] = counts.get(rule, 0) + 1
    return dynamic_open, self_open, dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# 「미수집 0」 오러클
# ---------------------------------------------------------------------------

_SITE_RELS = frozenset(
    {"calls", "constructs", "dynamic_site", "reads_attribute", "writes_attribute"}
)


def _oracle_syntax_anchor(node: ast.AST) -> str:
    """수집기와 별도로 source AST에서 재구성하는 전수성 오러클 anchor."""
    try:
        text = ast.unparse(node).replace("\r", " ").replace("\n", " ")[:120]
    except Exception:  # noqa: BLE001 — 진단 좌표는 형태명으로 fail-loud하게 남긴다
        text = type(node).__name__
    return f"c{getattr(node, 'col_offset', -1)}-{getattr(node, 'end_col_offset', -1)}:{text}"


def _runtime_call_nodes(tree: ast.Module) -> "list[ast.Call]":
    """실제로 평가될 수 있는 Call만 독립 AST denominator로 열거한다.

    함수 signature와 module/class 변수 annotation은 기본 모드에서 정의 시점에
    평가되지만 ``from __future__ import annotations``에서는 지연된다. 함수-local 변수
    annotation은 어느 모드에서도 평가되지 않는다. 단순 ``ast.walk``는 이 차이를 잃어
    inert annotation을 미수집으로 오판하므로 scope를 별도로 추적한다.
    """
    future_annotations = any(
        isinstance(stmt, ast.ImportFrom)
        and stmt.module == "__future__"
        and any(alias.name == "annotations" for alias in stmt.names)
        for stmt in tree.body
    )

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.calls: list[ast.Call] = []
            self.scopes = ["module"]

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast visitor protocol
            self.calls.append(node)
            self.generic_visit(node)

        def _visit_function(
            self, node: "ast.FunctionDef | ast.AsyncFunctionDef"
        ) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in [*node.args.defaults, *filter(None, node.args.kw_defaults)]:
                self.visit(default)
            if not future_annotations:
                annotations = [
                    *(arg.annotation for arg in node.args.posonlyargs),
                    *(arg.annotation for arg in node.args.args),
                    *(arg.annotation for arg in node.args.kwonlyargs),
                    node.args.vararg.annotation if node.args.vararg is not None else None,
                    node.args.kwarg.annotation if node.args.kwarg is not None else None,
                    node.returns,
                ]
                for annotation in filter(None, annotations):
                    self.visit(annotation)
            self.scopes.append("function")
            for statement in node.body:
                self.visit(statement)
            self.scopes.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
            for default in [*node.args.defaults, *filter(None, node.args.kw_defaults)]:
                self.visit(default)
            self.scopes.append("function")
            self.visit(node.body)
            self.scopes.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            self.scopes.append("class")
            for statement in node.body:
                self.visit(statement)
            self.scopes.pop()

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
            self.visit(node.target)
            if not future_annotations and self.scopes[-1] != "function":
                self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)

    visitor = Visitor()
    visitor.visit(tree)
    return visitor.calls


def _oracle_top_level_imports(
    tree: ast.Module, module_names: set[str], current_module: str, *, is_package: bool
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """독립 direct-call oracle용 유일한 top-level import binding만 보수적으로 고른다."""
    module_candidates: dict[str, set[str]] = {}
    symbol_candidates: dict[str, set[tuple[str, str]]] = {}
    other_bindings: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                target = alias.name if alias.asname else alias.name.split(".", 1)[0]
                module_candidates.setdefault(bound, set()).add(target)
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.level == 0:
                base = stmt.module or ""
            else:
                parts = current_module.split(".")
                if not is_package:
                    parts = parts[:-1]
                if stmt.level > 1:
                    parts = parts[: len(parts) - (stmt.level - 1)]
                base = ".".join(parts + ([stmt.module] if stmt.module else []))
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                full = f"{base}.{alias.name}" if base else alias.name
                if full in module_names:
                    module_candidates.setdefault(bound, set()).add(full)
                else:
                    symbol_candidates.setdefault(bound, set()).add((base, alias.name))
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            other_bindings.add(stmt.name)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    other_bindings.add(target.id)
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    other_bindings.add(target.id)
    modules = {
        bound: next(iter(targets))
        for bound, targets in module_candidates.items()
        if len(targets) == 1 and bound not in other_bindings and bound not in symbol_candidates
    }
    symbols = {
        bound: next(iter(targets))
        for bound, targets in symbol_candidates.items()
        if len(targets) == 1 and bound not in other_bindings and bound not in module_candidates
    }
    return modules, symbols


def uncovered_call_sites(
    repo_root: Path, closure: Closure, facts: tuple[Fact, ...]
) -> "list[str]":
    """모든 ``ast.Call``의 site coverage와 직접 callee edge의 최소 정합성을 검증한다.

    좌표에 아무 사실이나 한 건 남기는 false-green을 막기 위해, source가 독립적으로 말해 주는
    direct name/attribute terminal과 concrete symbol target도 대조한다. name alias처럼 별도
    데이터플로가 필요한 경우는 같은 module의 직접 이름만 보수적으로 검사한다.
    """
    by_site: dict[tuple[str, int, str], list[Fact]] = {}
    for fact in facts:
        if fact.rel in _SITE_RELS:
            key = (fact.evidence.file, fact.evidence.line, fact.evidence.anchor)
            by_site.setdefault(key, []).append(fact)
    problems: list[str] = []
    module_names = {mf.module for mf in closure.modules}
    for mf in closure.modules:
        tree = ast.parse((Path(repo_root) / mf.path).read_text(encoding="utf-8"))
        module_aliases, symbol_aliases = _oracle_top_level_imports(
            tree,
            module_names,
            mf.module,
            is_package=mf.path.endswith("__init__.py"),
        )
        for node in _runtime_call_nodes(tree):
            anchor = _oracle_syntax_anchor(node)
            key = (mf.path, node.lineno, anchor)
            site_facts = by_site.get(key, [])
            if not site_facts:
                problems.append(
                    f"{mf.path}:{node.lineno}:{node.col_offset} 호출에 사실이 없다 "
                    f"({anchor})"
                )
                continue
            expected_leaf: str | None = None
            expected_module: str | None = None
            if isinstance(node.func, ast.Name):
                imported = symbol_aliases.get(node.func.id)
                if imported is not None:
                    # A ``from facade import name`` binding can legitimately resolve
                    # to the facade's final re-export origin.  This independent
                    # syntax oracle does not reconstruct that module's execution
                    # timeline, so it verifies the callable leaf but deliberately
                    # leaves the target module to the re-export oracle.
                    _imported_module, expected_leaf = imported
                else:
                    expected_leaf = node.func.id
                    expected_module = mf.module
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in module_aliases
            ):
                expected_module = module_aliases[node.func.value.id]
                expected_leaf = node.func.attr
            elif isinstance(node.func, ast.Attribute):
                expected_leaf = node.func.attr
            if expected_leaf is None:
                continue
            for fact in site_facts:
                if (
                    fact.provenance.collector != BASE_COLLECTOR
                    or fact.rel not in ("calls", "constructs")
                    or not is_symbol_ref(fact.dst)
                ):
                    continue
                target_module, target_qual, target_kind = parse_symbol_id(fact.dst)
                if expected_module is not None and target_module != expected_module:
                    problems.append(
                        f"{mf.path}:{node.lineno}:{node.col_offset} 호출 target module 불일치: "
                        f"source={expected_module!r}, fact={fact.rel}:{fact.dst}"
                    )
                    continue
                target_leaf = target_qual.rsplit(".", 1)[-1] if target_qual else ""
                expected_rel = "constructs" if target_kind == "class" else "calls"
                if target_leaf != expected_leaf or fact.rel != expected_rel:
                    problems.append(
                        f"{mf.path}:{node.lineno}:{node.col_offset} 호출 target 불일치: "
                        f"source={expected_leaf!r}, fact={fact.rel}:{fact.dst}"
                    )
    return sorted(set(problems))


def uncovered_import_sites(
    repo_root: Path, closure: Closure, facts: tuple[Fact, ...]
) -> "list[str]":
    """모든 import alias가 import fact 또는 loud star dynamic 사실을 갖는가."""
    covered = {
        (f.evidence.file, f.evidence.line, f.evidence.anchor)
        for f in facts
        if f.rel in ("imports_module", "imports_symbol")
        or f.provenance.rule == "import_star"
    }
    problems: list[str] = []
    for mf in closure.modules:
        module_name, module_path = mf.module, mf.path
        tree = ast.parse((Path(repo_root) / module_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                bound = "*" if alias.name == "*" else alias.asname or alias.name.split(".", 1)[0]
                anchor = import_binding_anchor(bound, alias.name, alias)
                if (mf.path, node.lineno, anchor) not in covered:
                    problems.append(
                        f"{mf.path}:{node.lineno}:{alias.col_offset} import 바인딩 {bound!r}"
                        f"(원본 {alias.name!r})에 사실이 없다"
                    )
    return sorted(set(problems))


def uncovered_inheritance_sites(
    repo_root: Path, closure: Closure, facts: tuple[Fact, ...]
) -> "list[str]":
    """모든 base 위치가 올바른 class owner와 보수적 local target을 갖는가."""
    by_site: dict[tuple[str, int, str], list[Fact]] = {}
    for fact in facts:
        if fact.rel == "inherits":
            by_site.setdefault(
                (fact.evidence.file, fact.evidence.line, fact.evidence.anchor), []
            ).append(fact)
    problems: list[str] = []
    for mf in closure.modules:
        module_name, module_path = mf.module, mf.path
        tree = ast.parse((Path(repo_root) / module_path).read_text(encoding="utf-8"))

        def walk(
            body: "list[ast.stmt]",
            prefix: str,
            module_name: str = module_name,
            module_path: str = module_path,
        ) -> None:
            prior_classes: dict[str, str | None] = {}
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{prefix}{node.name}"
                    walk(node.body, f"{qualname}.<locals>.")
                    continue
                if isinstance(node, ast.ClassDef):
                    qualname = f"{prefix}{node.name}"
                    owner_sid = symbol_id(module_name, qualname, "class")
                    for order, base in enumerate(node.bases):
                        key = (module_path, base.lineno, str(order))
                        rows = by_site.get(key, [])
                        owner_rows = [fact for fact in rows if fact.src == owner_sid]
                        if not owner_rows:
                            problems.append(
                                f"{module_path}:{base.lineno}:{base.col_offset} class base #{order}의 "
                                f"owner 불일치 또는 inherits 사실 부재 ({owner_sid})"
                            )
                            continue
                        expected = (
                            prior_classes.get(base.id) if isinstance(base, ast.Name) else None
                        )
                        if expected is not None and not any(
                            fact.dst == expected for fact in owner_rows
                        ):
                            problems.append(
                                f"{module_path}:{base.lineno}:{base.col_offset} class base #{order} "
                                f"target 불일치: expected={expected}"
                            )
                    walk(node.body, f"{qualname}.")
                    prior_classes[node.name] = (
                        None if node.name in prior_classes else owner_sid
                    )
                    continue
                for block in _statement_blocks(node):
                    walk(block, prefix)

        walk(tree.body, "")
    return sorted(set(problems))


def uncovered_bare_decorator_sites(
    repo_root: Path, closure: Closure, facts: tuple[Fact, ...]
) -> "list[str]":
    """bare decorator 호출이 정의 시점의 올바른 execution owner에 붙는가."""
    by_site: dict[tuple[str, int, str], list[Fact]] = {}
    for fact in facts:
        if fact.provenance.rule == "decorator":
            by_site.setdefault(
                (fact.evidence.file, fact.evidence.line, fact.evidence.anchor), []
            ).append(fact)
    problems: list[str] = []
    for mf in closure.modules:
        module_name, module_path = mf.module, mf.path
        tree = ast.parse((Path(repo_root) / module_path).read_text(encoding="utf-8"))

        def walk(
            body: "list[ast.stmt]",
            prefix: str,
            in_class: bool,
            execution_owner: str,
            module_name: str = module_name,
            module_path: str = module_path,
        ) -> None:
            prior_definitions: dict[str, str | None] = {}
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for decorator in node.decorator_list:
                        if isinstance(decorator, ast.Call):
                            continue  # ast.Call completeness oracle가 소유한다
                        anchor = _oracle_syntax_anchor(decorator)
                        rows = by_site.get((module_path, decorator.lineno, anchor), [])
                        owner_rows = [
                            fact for fact in rows if fact.src == execution_owner
                        ]
                        if not owner_rows:
                            problems.append(
                                f"{module_path}:{decorator.lineno}:{decorator.col_offset} bare "
                                f"decorator owner 불일치 또는 calls 사실 부재 ({execution_owner})"
                            )
                            continue
                        expected = (
                            prior_definitions.get(decorator.id)
                            if isinstance(decorator, ast.Name)
                            else None
                        )
                        if expected is not None and not any(
                            fact.dst == expected for fact in owner_rows
                        ):
                            problems.append(
                                f"{module_path}:{decorator.lineno}:{decorator.col_offset} bare "
                                f"decorator target 불일치: expected={expected}"
                            )
                    qualname = f"{prefix}{node.name}"
                    if isinstance(node, ast.ClassDef):
                        sid = symbol_id(module_name, qualname, "class")
                        walk(node.body, f"{qualname}.", True, sid)
                    else:
                        kind = "method" if in_class else "function"
                        sid = symbol_id(module_name, qualname, kind)
                        walk(node.body, f"{qualname}.<locals>.", False, sid)
                    prior_definitions[node.name] = (
                        None if node.name in prior_definitions else sid
                    )
                    continue
                for block in _statement_blocks(node):
                    walk(block, prefix, in_class, execution_owner)

        walk(tree.body, "", False, symbol_id(module_name, "", "module"))
    return sorted(set(problems))


# ---------------------------------------------------------------------------
# 원장 render/check/rewrite
# ---------------------------------------------------------------------------

_HEADER = f"""# 생성 파일 — 직접 편집 금지. P1-02A 정적 그래프 원장(#513).
# 원천: 고정 baseline src/ + scripts/factgraph 기반·파생 사실의 결정론 재계측
# 재생성: {REGEN_COMMAND}
# 검사:   {REGEN_COMMAND} --check
schema = "static-graph-02a/v1"
"""


def render(repo_root: Path, *, _baseline_checked: bool = False) -> str:
    if not _baseline_checked:
        baseline_problems = _baseline_source_problems(Path(repo_root))
        if baseline_problems:
            raise FactGraphError("; ".join(baseline_problems))
    result = build(repo_root)
    dynamic_open, self_open, noise = open_unresolved(result)
    unresolved = unresolved_facts(result)
    edges = module_import_edges(result.facts)
    sccs = nontrivial_sccs(edges)
    fan_out, fan_in, constructs = fan_metrics(result.facts)
    coverage = {
        "call": uncovered_call_sites(repo_root, result.closure, result.facts),
        "import": uncovered_import_sites(repo_root, result.closure, result.facts),
        "inheritance": uncovered_inheritance_sites(repo_root, result.closure, result.facts),
        "bare_decorator": uncovered_bare_decorator_sites(
            repo_root, result.closure, result.facts
        ),
    }
    coverage_problems = [problem for problems in coverage.values() for problem in problems]
    if coverage_problems:
        sample = "; ".join(coverage_problems[:5])
        raise FactGraphError(f"정적 그래프 미수집 좌표 {len(coverage_problems)}건: {sample}")

    parts = [_HEADER, "\n[baseline]\n"]
    parts.append(f"git_sha = {_q(BASELINE_SHA)}\n")
    parts.append("\n[digests]\n")
    parts.append(f'base_facts = "{result.base_digest}"\n')
    parts.append(f'graph_facts = "{result.graph_digest}"\n')

    parts.append("\n[counts]\n")
    parts.append(f"modules = {len(result.closure.modules)}\n")
    parts.append(f"symbols = {len(result.symbols)}\n")
    parts.append(f"facts_base = {len(result.base_facts)}\n")
    parts.append(f"facts_derived = {len(result.derived_facts)}\n")
    parts.append(f"dispatch_sites = {len(result.dispatch_sites)}\n")
    parts.append(f"dispatch_edges = {sum(len(site.restored) for site in result.dispatch_sites)}\n")
    parts.append(f"module_import_edges = {sum(len(targets) for targets in edges.values())}\n")
    parts.append(f"sccs = {len(sccs)}\n")
    parts.append(f"mro_failures = {len(result.mro_failures)}\n")
    parts.append(f"table_misses = {len(result.table_misses)}\n")
    parts.append(f"construct_hotspot_nodes = {len(constructs)}\n")
    parts.append(f"fan_out_nodes = {len(fan_out)}\n")
    parts.append(f"fan_in_nodes = {len(fan_in)}\n")
    parts.append("uncovered_call_sites = 0\n")
    parts.append("uncovered_import_sites = 0\n")
    parts.append("uncovered_inheritance_sites = 0\n")
    parts.append("uncovered_bare_decorator_sites = 0\n")
    parts.append(f"dynamic_open = {len(dynamic_open)}\n")
    parts.append(f"self_unresolved_open = {len(self_open)}\n")
    parts.append(f"unresolved_open = {len(unresolved)}\n")

    by_rule: dict[str, int] = {}
    for fact in unresolved:
        rule = fact.provenance.rule
        by_rule[rule] = by_rule.get(rule, 0) + 1
    parts.append("\n# 열린 edge 전수의 rule별 요약. 좌표·근거·provenance는 [[unresolved]]가 든다.\n")
    parts.append("[unresolved_by_rule]\n")
    for rule, count in sorted(by_rule.items()):
        parts.append(f"{_q(rule)} = {count}\n")

    parts.append("\n# rule → 후속 확인 경로 귀속표 — 미해결은 소유자가 있어야 원장이다.\n")
    parts.append("# (지금 원장에 실제로 나타난 rule 전수 — 미등록 rule 은 render 가 거절한다)\n")
    parts.append("[followup]\n")
    present_rules = sorted(by_rule)
    for rule in present_rules:
        parts.append(f"{_q(rule)} = {_q(followup_of(rule))}\n")

    # 전 사실 8천+행은 digest로 핀하고, 그중 아직 닫히지 않은 edge는 하나도 숨기지 않고
    # 좌표까지 커밋한다. 이 목록이 P1-02B/runtime trace의 실제 작업 큐다.
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

    for scc in sccs:
        parts.append("\n[[scc]]\n")
        parts.append("members = [\n")
        parts.extend(f'  "{m}",\n' for m in scc)
        parts.append("]\n")

    for site in result.dispatch_sites:
        parts.append("\n[[dispatch]]\n")
        parts.append(f"kind = {_q(site.kind)}\n")
        parts.append(f"owner = {_q(site.owner)}\n")
        parts.append(f"key = {_q(site.key)}\n")
        parts.append(f"src = {_q(site.src)}\n")
        parts.append(f"file = {_q(site.file)}\n")
        parts.append(f"line = {site.line}\n")
        parts.append(f"anchor = {_q(site.anchor)}\n")
        parts.append(f"restored = {len(site.restored)}\n")
        parts.append("restored_targets = [\n")
        parts.extend(f"  {_q(target)},\n" for target in site.restored)
        parts.append("]\n")

    for sid in result.mro_failures:
        parts.append("\n[[mro_failure]]\n")
        parts.append(f"class = {_q(sid)}\n")
    for miss in result.table_misses:
        parts.append("\n[[table_miss]]\n")
        parts.append(f"marker = {_q(miss)}\n")

    parts.append(_top_section("construct_hotspot", constructs, 10))
    parts.append(_top_section("fan_out_top", fan_out, 10))
    parts.append(_top_section("fan_in_top", fan_in, 10))
    return "".join(parts)


def _top_section(name: str, counts: "dict[str, int]", top: int) -> str:
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    out = []
    for sid, count in rows:
        out.append(f"\n[[{name}]]\n")
        out.append(f"symbol = {_q(sid)}\n")
        out.append(f"count = {count}\n")
    return "".join(out)


def _q(value: str) -> str:
    """TOML basic string과 공통인 JSON 인코딩으로 진단 원문을 안전하게 싣는다."""
    return json.dumps(value, ensure_ascii=False)


def check(repo_root: Path) -> "list[str]":
    repo_root = Path(repo_root)
    baseline_problems = _baseline_source_problems(repo_root)
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
    baseline_problems = _baseline_source_problems(repo_root)
    if baseline_problems:
        raise FactGraphError("; ".join(baseline_problems))
    target = repo_root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(repo_root, _baseline_checked=True))
    return target


def _baseline_source_problems(repo_root: Path) -> list[str]:
    """실저장소 생성물이 고정 SHA 라벨과 다른 ``src/``를 섞지 못하게 막는다."""
    if not (repo_root / ".git").exists():
        return []  # 합성 fixture에는 Git baseline 계약을 강제하지 않는다
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
        return [
            f"baseline {BASELINE_SHA} 이후 production src/가 바뀌었다 — SHA를 재확정하라"
        ]
    return []


__all__ = [
    "BASE_COLLECTOR",
    "BASELINE_SHA",
    "COLLECTOR",
    "DispatchSite",
    "FOLLOWUP_OF_RULE",
    "LEDGER_REL_PATH",
    "REGEN_COMMAND",
    "StaticGraphResult",
    "build",
    "check",
    "fan_metrics",
    "module_import_edges",
    "nontrivial_sccs",
    "open_unresolved",
    "render",
    "rewrite",
    "uncovered_call_sites",
    "uncovered_bare_decorator_sites",
    "uncovered_import_sites",
    "uncovered_inheritance_sites",
    "unresolved_facts",
]
