"""P1-03 중앙 합성 — Authority Graph·SCC·P2 migration DAG 를 한 번만 해석하는 seam(#518).

P1-02A~E 의 병렬 fact shard 는 서로 독립이다. 이 모듈이 그 여섯 원장을 **한 번만** 해석해
목표 권위(#433 헌장)를 단일 귀속하고, migration unit·선후 DAG·behavior oracle 을 확정하며,
P2 를 ``ONE_WAVE_READY / ORDERED_WAVES_READY / BLOCKED`` 중 하나로 판정한다.

설계 결정:

- **content-anchor merge**. schema.merge_shards 는 baseline_sha 발산을 거절한다 — 02E 만
  baseline 이 02A 착지 커밋(``247333e``)이라 그대로 못 쓴다. 대신 여섯 원장이 **같은 기반
  사실**(``base_facts``/``graph_facts`` digest) 위임을 강제한다. src/ 폐포 내용이 바이트
  동일함을 그 digest 일치가 증명한다(schema.facts_digest 의 설계 목적). 어긋나면 contradiction.
- **재계측 없는 소비 + 한 축의 재실행 교차검증**. state·transport·use-case 파생 테이블은
  커밋된 원장이 이미 per-symbol 로 들고 있어 그대로 소비한다. 다만 02C 원장은 per-symbol
  effect **class**(fs/host/clock…)를 방출하지 않으므로 ``effect_graph.build`` 를 한 번 재실행해
  effect class 와 static 앵커(base/graph digest)를 함께 얻고, 재계측 effect digest 가 커밋
  원장의 핀과 같은지 대조한다(deterministic merge 의 교차검증).
- **호출 관계만으로 권위를 정하지 않는다**(#518 규칙). effect·state·transport·use-case 증거를
  함께 본다. 애매하거나 헌장을 위반하는(업무 코어가 concrete effect 를 직접 호출 등) 자리는
  **조용히 추측하지 않고 P_REVIEW_REQUIRED 로 사유와 함께** 남긴다(confirm-or-alarm).
"""

from __future__ import annotations

import hashlib
import ast
import csv
import json
import subprocess
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .effect_graph import build as build_effect
from .effect_graph import classify_external
from .schema import FactGraphError, parse_symbol_id

COLLECTOR = "factgraph.authority_synthesis"
LEDGER_REL_PATH = "docs/factgraph/authority_ledger_03.toml"
REGEN_COMMAND = "uv run python scripts/gen_authority_ledger_03.py"
SCHEMA = "authority-synthesis-03/v2"

#: 여섯 shard 공통 기반 사실 앵커(P1-01 폐포). src/ 가 이 값과 다르면 원장이 stale 이다.
ANCHOR_BASE_FACTS = "340ac8f5be9c2d38d64dd9367740f08a04ede46db14e00cff689a574b255864b"
ANCHOR_GRAPH_FACTS = "cf0c4aa91443c2c276d12f074e2fc2a56c8cbaa600e0cdc745921f730c2b5969"

#: 소비하는 원장 경로. 각 원장의 기반-사실 핀 좌표는 _SHARD_ANCHORS 가 안다.
INVENTORY_LEDGER = "docs/factgraph/python_symbol_inventory.toml"
STATIC_LEDGER = "docs/factgraph/static_graph_02a.toml"
STATE_LEDGER = "docs/factgraph/state_graph_02b.toml"
EFFECT_LEDGER = "docs/factgraph/effect_graph_02c.toml"
TRANSPORT_LEDGER = "docs/factgraph/transport_graph_02d.toml"
USE_CASE_LEDGER = "docs/factgraph/use_case_graph_02e.toml"
DECISION_LEDGER = "docs/factgraph/authority_decisions_03.toml"
R_OWNERSHIP_LEDGER = "docs/react_ownership_inventory.toml"
R_VERIFICATION_LEDGER = "docs/react_verification_ledger.toml"
TEST_PORTFOLIO = "docs/test_portfolio_inventory.csv"

SHARD_LEDGERS: "tuple[tuple[str, str], ...]" = (
    ("01", INVENTORY_LEDGER),
    ("02a", STATIC_LEDGER),
    ("02b", STATE_LEDGER),
    ("02c", EFFECT_LEDGER),
    ("02d", TRANSPORT_LEDGER),
    ("02e", USE_CASE_LEDGER),
)

#: #433 헌장의 목표 권위 8종. AMBIENT 는 내부 신호(port 필요)일 뿐 최종 어휘가 아니다.
AUTHORITIES: "tuple[str, ...]" = (
    "DOMAIN",
    "APPLICATION",
    "FRONTEND_ADAPTER",
    "EXTERNAL_ADAPTER",
    "HOST",
    "REACT",
    "RETIRE",
    "P_REVIEW_REQUIRED",
)

#: 02C effect class → 권위 증거. AMBIENT(clock/entropy/env)는 그 자체로 HOST/ADAPTER 를
#: 강제하지 않는다 — 업무 코어가 직접 만지면 port 주입 결정이 필요한 P_REVIEW 신호다.
EFFECT_CLASS_AUTHORITY: "dict[str, str]" = {
    "fs": "EXTERNAL_ADAPTER",
    "excel": "EXTERNAL_ADAPTER",
    "archive": "EXTERNAL_ADAPTER",
    "registry": "EXTERNAL_ADAPTER",
    "network": "EXTERNAL_ADAPTER",
    "lock": "EXTERNAL_ADAPTER",
    "process": "HOST",
    "host_webview": "HOST",
    "host_native": "HOST",
    "stdio": "HOST",
    "clock": "AMBIENT",
    "entropy": "AMBIENT",
    "env": "AMBIENT",
}

#: 패키지 위치 → 목표 권위 사전(prior). 측정 증거가 이를 덮으면 P_REVIEW 로 승격한다 —
#: prior 는 판정이 아니라 「증거가 없을 때의 기본 가설」이다.
_PRIOR_DOMAIN = ("hwpxcore.atomic", "hwpxcore.lineseg", "hwpxcore.motw",
                 "hwpxcore.package", "hwpxcore.text_extract", "hwpxcore.validate")

#: 의존 방향 링 서열(#433). 허용 import 는 바깥→안이다: 외곽(2)→Application(1)→Domain(0).
#: 안쪽이 바깥쪽을 import 하면(RING[src] < RING[dst]) 방향 위반이다. 외곽 셋
#: (FRONTEND_ADAPTER·EXTERNAL_ADAPTER·HOST)은 같은 서열의 peer 라 서로 조립 import 가능.
RING: "dict[str, int]" = {
    "DOMAIN": 0,
    "APPLICATION": 1,
    "FRONTEND_ADAPTER": 2,
    "EXTERNAL_ADAPTER": 2,
    "HOST": 2,
}


# ---------------------------------------------------------------------------
# 결과 자료구조
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contradiction:
    """에이전트 간(원장 간) 사실 충돌 하나 — 조용히 덮지 않고 중앙에 남긴다."""

    kind: str
    detail: str


@dataclass(frozen=True)
class ModuleAuthority:
    """한 production 모듈의 목표 권위 판정과 그 사실 근거."""

    module: str
    target: str
    prior: str
    reason: str
    symbol_count: int
    effect_classes: "tuple[str, ...]"
    composes: "tuple[str, ...]"  # 조립하는 effect-bearing 클래스 id(직접 호출 아닌 효과 증거)
    transport: bool
    stateful_tx: bool
    shared_state: bool
    entries: "tuple[str, ...]"


@dataclass(frozen=True)
class DirectionEdge:
    """import 방향 위반 하나 — 안쪽 링이 바깥쪽을 import 한 좌표."""

    src: str
    src_target: str
    dst: str
    dst_target: str


@dataclass(frozen=True)
class DependencyAnalysis:
    """모듈 import 그래프의 방향 판정. 결정 권위 간 위반은 0 이어야 한다(clean invariant)."""

    internal_edges: int
    decided_edges: int
    deferred_edges: int  # 끝점 하나 이상이 P_REVIEW — 권위 미결정이라 방향 판단 유보
    peer_edges: int  # 외곽 링 peer 간(방향 무관)
    violations: "tuple[DirectionEdge, ...]"
    planned_violations: "tuple[DirectionEdge, ...]" = ()


@dataclass(frozen=True)
class AuthorityDecision:
    """측정만으로 단일 귀속할 수 없던 모듈에 대한 사람 판정과 P2 추출 의무."""

    module: str
    target: str
    reason: str
    extractions: "tuple[str, ...]"


@dataclass(frozen=True)
class MigrationUnit:
    """다른 에이전트가 추가 추론 없이 실행할 수 있는 P2 병렬 절단 패킷."""

    unit_id: str
    target: str
    modules: "tuple[str, ...]"
    symbol_count: int
    purpose: str
    current_responsibilities: "tuple[str, ...]"
    source_symbols: "tuple[str, ...]"
    closure_digest: str
    source_write_set: "tuple[str, ...]"
    read_only_adjacent: "tuple[str, ...]"
    write_set: "tuple[str, ...]"
    state_reads: "tuple[str, ...]"
    transaction_clusters: "tuple[str, ...]"
    effect_edges: "tuple[str, ...]"
    persistence_edges: "tuple[str, ...]"
    transport_edges: "tuple[str, ...]"
    target_inputs: "tuple[str, ...]"
    target_outputs: "tuple[str, ...]"
    required_effect_contracts: "tuple[str, ...]"
    extraction_obligations: "tuple[str, ...]"
    shared_with: "tuple[str, ...]"
    oracle_status: str
    oracle_entries: "tuple[str, ...]"
    positive_gates: "tuple[str, ...]"
    negative_gates: "tuple[str, ...]"
    predecessors: "tuple[str, ...]"
    successors: "tuple[str, ...]"
    compat_seam: str
    removal_condition: str
    rollback_condition: str
    stop_condition: str
    blocking: "tuple[str, ...]"


@dataclass
class SynthesisResult:
    baseline_sha: str
    source_digest: str
    base_facts: str
    graph_facts: str
    effect_facts: str
    sccs: int
    dynamic_open: int
    shard_digests: "dict[str, str]"
    contradictions: "tuple[Contradiction, ...]"
    modules: "tuple[ModuleAuthority, ...]"
    units: "tuple[MigrationUnit, ...]"
    shared_seams: "tuple[tuple[str, tuple[str, ...]], ...]"
    oracle_gaps: "tuple[str, ...]"
    oracle_pointer_gaps: "tuple[str, ...]"
    packet_gaps: "tuple[str, ...]"
    source_write_overlaps: "tuple[tuple[str, tuple[str, ...]], ...]"
    r_handoff_gaps: "tuple[str, ...]"
    dependency: DependencyAnalysis
    unowned_surfaces: "tuple[str, ...]"  # effect/state/transport 을 지되 권위 원장 밖인 모듈
    verdict: str
    verdict_reasons: "tuple[str, ...]"


# ---------------------------------------------------------------------------
# 원장 로드·앵커
# ---------------------------------------------------------------------------


def _load_toml(repo_root: Path, rel: str) -> dict:
    path = repo_root / rel
    if not path.is_file():
        raise FactGraphError(f"입력 원장 부재: {rel} — 선행 P1-02 를 먼저 착지하라")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _shard_base_pin(shard: str, data: dict) -> "str | None":
    """각 원장이 기반 사실을 어디에 핀했는가 — 좌표가 원장마다 다르다(계약이다)."""
    if shard == "01":
        return None  # 인벤토리는 fact digest 를 핀하지 않는다(심볼 목록만)
    if shard == "02a":
        return data.get("digests", {}).get("base_facts")
    if shard == "02b":
        return data.get("input", {}).get("base_facts")
    if shard == "02c":
        return data.get("digests", {}).get("base_facts")
    if shard == "02d":
        return data.get("digests", {}).get("base_facts_02a")
    if shard == "02e":
        return data.get("inputs", {}).get("base_facts")
    return None


def _shard_graph_pin(shard: str, data: dict) -> "str | None":
    """call-graph 사실 핀 — 02D 는 call-axis 파생이 아니라 이 핀이 없다(면제)."""
    if shard == "02a":
        return data.get("digests", {}).get("graph_facts")
    if shard == "02b":
        return data.get("input", {}).get("graph_facts")
    if shard == "02c":
        return data.get("digests", {}).get("graph_facts")
    if shard == "02e":
        return data.get("inputs", {}).get("graph_facts")
    return None  # 01·02d 는 graph_facts 핀 없음


def _merge_and_contradictions(
    repo_root: Path,
    shards: "dict[str, dict]",
    live_base: str,
    live_graph: str,
    live_effect: str,
) -> "tuple[list[Contradiction], dict[str, str]]":
    """content-anchor merge 의 일치 강제 + 원장 간 사실 충돌 원장.

    여섯 원장이 같은 기반 사실 위인가를 base/graph digest 일치로 강제한다. live 재계측이
    앵커 상수와 다르면 src/ 가 원장보다 앞섰다는 뜻이고, 원장끼리 갈리면 stale shard 다 —
    둘 다 시끄러운 contradiction 이다.
    """
    problems: "list[Contradiction]" = []
    digests: "dict[str, str]" = {}

    if live_base != ANCHOR_BASE_FACTS:
        problems.append(
            Contradiction(
                "live_base_drift",
                f"재계측 base_facts {live_base} ≠ 앵커 {ANCHOR_BASE_FACTS} "
                "— src/ 가 원장 기반보다 앞섰다. 선행 P1-02 를 재생성하라",
            )
        )
    if live_graph != ANCHOR_GRAPH_FACTS:
        problems.append(
            Contradiction(
                "live_graph_drift",
                f"재계측 graph_facts {live_graph} ≠ 앵커 {ANCHOR_GRAPH_FACTS}",
            )
        )

    for shard, rel in SHARD_LEDGERS:
        data = shards[shard]
        base_pin = _shard_base_pin(shard, data)
        graph_pin = _shard_graph_pin(shard, data)
        if base_pin is not None:
            digests[f"{shard}.base_facts"] = base_pin
            if base_pin != ANCHOR_BASE_FACTS:
                problems.append(
                    Contradiction(
                        "shard_base_mismatch",
                        f"{rel} 의 base_facts {base_pin} ≠ 앵커 {ANCHOR_BASE_FACTS}",
                    )
                )
        if graph_pin is not None:
            digests[f"{shard}.graph_facts"] = graph_pin
            if graph_pin != ANCHOR_GRAPH_FACTS:
                problems.append(
                    Contradiction(
                        "shard_graph_mismatch",
                        f"{rel} 의 graph_facts {graph_pin} ≠ 앵커 {ANCHOR_GRAPH_FACTS}",
                    )
                )

    # 02C effect digest 교차검증 — 재계측이 커밋 원장의 핀과 같은가.
    effect_pin = shards["02c"].get("digests", {}).get("effect_facts")
    digests["02c.effect_facts"] = effect_pin or ""
    if effect_pin != live_effect:
        problems.append(
            Contradiction(
                "effect_digest_mismatch",
                f"재계측 effect_facts {live_effect} ≠ 02C 원장 핀 {effect_pin}",
            )
        )

    return problems, digests


# ---------------------------------------------------------------------------
# 축별 증거 색인
# ---------------------------------------------------------------------------


def _module_of_symbol(sid: str) -> str:
    module, _qual, _kind = parse_symbol_id(sid)
    return module


def _state_module(state_id: str) -> str:
    """``attr:<module>:<qual>`` 좌표의 소유 모듈. state id 는 심볼 id 가 아니다."""
    body = state_id.removeprefix("attr:")
    module, _sep, _rest = body.partition(":")
    return module


def _inventory_modules(inv: dict) -> "dict[str, tuple[str, ...]]":
    out: "dict[str, tuple[str, ...]]" = {}
    for entry in inv.get("module", []):
        out[entry["name"]] = tuple(entry.get("symbols", []))
    return out


def _inventory_paths(inv: dict) -> "dict[str, str]":
    return {entry["name"]: entry["path"] for entry in inv.get("module", [])}


def _load_decisions(
    repo_root: Path, inventory_modules: "set[str]"
) -> "tuple[dict[str, AuthorityDecision], dict[str, str], list[Contradiction]]":
    """사람 판정을 읽고 중복·유령·어휘 오류를 contradiction으로 승격한다."""
    raw = _load_toml(repo_root, DECISION_LEDGER)
    problems: "list[Contradiction]" = []
    if raw.get("schema") != "authority-decisions-03/v1":
        problems.append(
            Contradiction("decision_schema", f"{DECISION_LEDGER} schema가 v1이 아니다")
        )
    decisions: "dict[str, AuthorityDecision]" = {}
    for row in raw.get("decision", []):
        module = str(row.get("module", ""))
        target = str(row.get("target", ""))
        reason = str(row.get("reason", "")).strip()
        extractions = tuple(str(v).strip() for v in row.get("extractions", []) if str(v).strip())
        if not module or module in decisions:
            problems.append(Contradiction("decision_duplicate", f"중복/공란 module: {module!r}"))
            continue
        if module not in inventory_modules:
            problems.append(Contradiction("decision_ghost", f"인벤토리 밖 결정: {module}"))
        if target not in AUTHORITIES or target in {"P_REVIEW_REQUIRED", "REACT"}:
            problems.append(Contradiction("decision_target", f"{module}: 잘못된 target {target!r}"))
        if not reason:
            problems.append(Contradiction("decision_reason", f"{module}: 판정 사유 공란"))
        decisions[module] = AuthorityDecision(module, target, reason, extractions)
    return decisions, dict(raw.get("r_handoff", {})), problems


def _content_digest(repo_root: Path, rel: str) -> str:
    return hashlib.sha256((repo_root / rel).read_bytes()).hexdigest()


def _r_handoff_problems(
    repo_root: Path,
    handoff: "dict[str, str]",
    decisions: "dict[str, AuthorityDecision]",
) -> "list[str]":
    """R 원장의 네 미결정 항목이 P 판정과 같은 처분을 말하는지 교차검증한다."""
    ownership = _load_toml(repo_root, R_OWNERSHIP_LEDGER)
    _load_toml(repo_root, R_VERIFICATION_LEDGER)  # 입력 부재·파손도 fail-closed
    nodes = {str(row.get("id")): row for row in ownership.get("node", [])}
    reviews = {str(row.get("id")): row for row in ownership.get("review_item", [])}
    expected_handoff = {
        "close_guard_state": "host_internal",
        "tpl": "FRONTEND_ADAPTER",
        "nara_state": "APPLICATION",
        "pipeline_builder_state": "RETIRE",
    }
    gaps = [
        f"r_handoff.{key}: {handoff.get(key)!r} != {value!r}"
        for key, value in expected_handoff.items()
        if handoff.get(key) != value
    ]
    close = reviews.get("bridge/close-guard-state", {})
    if close.get("resolved") is not True or "host" not in str(close.get("disposition", "")).lower():
        gaps.append("R bridge/close-guard-state가 host_internal로 resolved되지 않았다")
    node_expectations = {
        "state/snapshot/tpl-channel": ("python_product", "hwpxfiller.webapp.screen_template"),
        "state/ring1/nara": ("python_product", "hwpxfiller.gui.nara_state"),
        "state/ring1/pipeline-builder": ("retire", "hwpxfiller.gui.pipeline_builder_state"),
    }
    for node_id, (classification, module) in node_expectations.items():
        node = nodes.get(node_id, {})
        if node.get("classification") != classification:
            gaps.append(f"R {node_id} classification이 {classification}이 아니다")
        if decisions.get(module) is None or decisions[module].target != expected_handoff[
            "tpl" if module.endswith("screen_template") else
            "nara_state" if module.endswith("nara_state") else
            "pipeline_builder_state"
        ]:
            gaps.append(f"R {node_id}와 P 결정 {module}이 어긋난다")
    return sorted(gaps)


def _oracle_pointers(use_case_toml: dict) -> "dict[str, set[str]]":
    """모듈별 실제 test/entry 포인터. 단순 boolean 접촉으로 oracle을 위조하지 않는다."""
    out: "dict[str, set[str]]" = {}
    for tf in use_case_toml.get("test_file", []):
        path = str(tf.get("path", ""))
        if not path:
            continue
        for module in tf.get("product_modules", []):
            out.setdefault(module, set()).add(f"{path} :: module-contact")
    for entry in use_case_toml.get("entry", []):
        for root in entry.get("roots", []):
            module = _module_of_symbol(root)
            # 실행 패킷은 entry당 대표 양성 포인터 둘이면 충분하다. 02E가 전수 센서스를 소유한다.
            for oracle in sorted(entry.get("oracles", []))[:2]:
                out.setdefault(module, set()).add(f"{entry['id']} <- {oracle}")
    return out


def _portfolio_oracles(repo_root: Path) -> "dict[str, set[str]]":
    """테스트 포트폴리오의 nodeid→covered module 관계를 실행 패킷 포인터로 재사용한다."""
    path = repo_root / TEST_PORTFOLIO
    if not path.is_file():
        return {}
    out: "dict[str, set[str]]" = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            nodeid = row.get("nodeid") or row.get("id") or ""
            for source in (row.get("covered_modules") or "").split(";"):
                source = source.strip().replace("\\", "/")
                if not source.startswith("src/") or not source.endswith(".py"):
                    continue
                module = source.removeprefix("src/").removesuffix(".py").replace("/", ".")
                if module.endswith(".__init__"):
                    module = module.removesuffix(".__init__")
                if nodeid:
                    out.setdefault(module, set()).add(nodeid)
    return out


def _effect_classes_by_module(effect_facts) -> "dict[str, set[str]]":
    """모듈 → 그 모듈 심볼이 접촉하는 effect class 집합(fs/host/clock…)."""
    out: "dict[str, set[str]]" = {}
    for fact in effect_facts:
        if fact.rel == "composes":
            continue
        if not fact.dst.startswith("ext:"):
            continue
        spec = classify_external(fact.dst.removeprefix("ext:"))
        if spec is None:
            continue
        _kind, _relation, label = spec
        out.setdefault(_module_of_symbol(fact.src), set()).add(label)
    return out


def _composes_by_module(composes_facts) -> "dict[str, tuple[str, ...]]":
    """모듈 → 그 모듈이 조립(construct)하는 effect-bearing 클래스 id 목록.

    02C 는 효과 보유 클래스의 조립 자리만 ``composes`` 로 잇는다(순수·오류 클래스 제외).
    직접 외부 호출이 없어도 adapter 를 생성하는 모듈은 composition root 다 — 효과 증거를
    직접 호출로만 좁히면 그 root 를 effect-free 로 오판한다(#532 리뷰).
    """
    out: "dict[str, set[str]]" = {}
    for fact in composes_facts:
        if fact.rel != "composes":
            continue
        out.setdefault(_module_of_symbol(fact.src), set()).add(fact.dst)
    return {m: tuple(sorted(v)) for m, v in out.items()}


def _import_edges(static) -> "tuple[tuple[str, str], ...]":
    """폐포 안 모듈 간 import 엣지(src module → dst module). 자기 자신·외부는 뺀다.

    ``import x`` 는 imports_module, ``from x import y`` 는 imports_symbol 로 방출된다 —
    방향 판정은 둘 다 봐야 한다(imports_module 만 보면 ``from`` 다수 코드베이스의 엣지
    대부분을 놓친다).
    """
    edges: "set[tuple[str, str]]" = set()
    for f in static.base_facts:
        if f.rel not in ("imports_module", "imports_symbol"):
            continue
        if f.dst.startswith(("ext:", "?:", "attr:")):
            continue
        try:
            src_mod, _q, _k = parse_symbol_id(f.src)
            dst_mod, _q2, _k2 = parse_symbol_id(f.dst)
        except FactGraphError:
            continue
        if src_mod != dst_mod:
            edges.add((src_mod, dst_mod))
    return tuple(sorted(edges))


def _direction_analysis(
    module_targets: "dict[str, str]",
    edges: "tuple[tuple[str, str], ...]",
    planned_sources: "set[str] | None" = None,
) -> DependencyAnalysis:
    """import 방향을 링 서열로 판정한다(#433). 안쪽이 바깥쪽을 import 하면 위반이다.

    끝점 하나라도 P_REVIEW(권위 미결정)면 방향을 판정하지 않고 유보한다 — UNKNOWN 을
    조용히 통과시키지 않되, 결정 안 된 권위로 위반을 위조하지도 않는다. 외곽 링 peer 끼리
    (FRONTEND_ADAPTER·EXTERNAL_ADAPTER·HOST)는 방향 무관이라 위반이 아니다.
    """
    decided = 0
    deferred = 0
    peer = 0
    violations: "list[DirectionEdge]" = []
    planned: "list[DirectionEdge]" = []
    planned_sources = planned_sources or set()
    for src, dst in edges:
        ts = module_targets.get(src)
        td = module_targets.get(dst)
        if (
            ts == "P_REVIEW_REQUIRED"
            or td == "P_REVIEW_REQUIRED"
            or ts not in RING
            or td not in RING
        ):
            deferred += 1
            continue
        decided += 1
        if RING[ts] == RING[td]:
            if ts != td:
                peer += 1
            continue
        if RING[ts] < RING[td]:  # 안쪽이 바깥쪽을 import — 위반
            edge = DirectionEdge(src, ts, dst, td)
            if src in planned_sources or dst in planned_sources:
                planned.append(edge)
            else:
                violations.append(edge)
    return DependencyAnalysis(
        internal_edges=len(edges),
        decided_edges=decided,
        deferred_edges=deferred,
        peer_edges=peer,
        violations=tuple(sorted(violations, key=lambda v: (v.src, v.dst))),
        planned_violations=tuple(sorted(planned, key=lambda v: (v.src, v.dst))),
    )


def _state_by_module(state_toml: dict) -> "dict[str, dict[str, set[str]]]":
    """모듈 → {writes, mutates, reads} state 좌표 집합."""
    out: "dict[str, dict[str, set[str]]]" = {}
    for st in state_toml.get("state", []):
        module = _state_module(st["id"])
        bucket = out.setdefault(module, {"writes": set(), "mutates": set(), "reads": set()})
        if st.get("writers"):
            bucket["writes"].add(st["id"])
        if st.get("mutators"):
            bucket["mutates"].add(st["id"])
        if st.get("readers"):
            bucket["reads"].add(st["id"])
    return out


def _tx_modules(state_toml: dict) -> "set[str]":
    """transaction cluster 를 소유한(원자 상태 묶음을 쓰는) 모듈."""
    out: "set[str]" = set()
    for cluster in state_toml.get("transaction_cluster", []):
        out.add(_module_of_symbol(cluster["src"]))
    return out


def _shared_state_seams(state_toml: dict) -> "list[tuple[str, tuple[str, ...]]]":
    """모듈 경계를 넘는 공유 상태 → central seam. 한 모듈 안 공유는 seam 이 아니다."""
    seams: "list[tuple[str, tuple[str, ...]]]" = []
    for shared in state_toml.get("shared_state", []):
        modules = sorted({_unit_module(u) for u in shared.get("units", [])})
        if len(modules) > 1:
            seams.append((shared["state"], tuple(modules)))
    return sorted(seams)


def _unit_module(unit: str) -> str:
    """02B shared_state 의 unit 문자열(``module`` 또는 ``module:Class``) → 모듈."""
    return unit.partition(":")[0]


def _transport_modules(transport_toml: dict) -> "dict[str, set[str]]":
    """모듈 → transport surface 종류 집합(endpoint/host_method/channel)."""
    out: "dict[str, set[str]]" = {}
    for ep in transport_toml.get("endpoint", []):
        handler = ep.get("handler")
        if handler:
            out.setdefault(_module_of_symbol(handler), set()).add("endpoint")
    for ch in transport_toml.get("channel", []):
        producer = ch.get("producer")
        if producer:
            out.setdefault(_module_of_symbol(producer), set()).add("channel")
    return out


def _host_method_module(transport_toml: dict) -> "str | None":
    """host_method 를 공개하는 transport facade 모듈(WebFrontend 소유)."""
    surface = transport_toml.get("host_method", [])
    # host_method 는 이름만 들고 소유 심볼을 안 든다 — endpoint handler 의 공통 부모가 소유다.
    return "hwpxfiller.webapp.app" if surface else None


def _entries_by_module(
    use_case_toml: dict,
) -> "tuple[dict[str, list[str]], dict[str, str], list[str]]":
    """모듈 → (진입 id 목록, oracle_status), 그리고 oracle 공백 진입 목록."""
    by_module: "dict[str, list[str]]" = {}
    module_oracle: "dict[str, str]" = {}
    gaps: "list[str]" = []
    order = {"NONE": 0, "ENTRY": 1, "CORE": 2}
    for entry in use_case_toml.get("entry", []):
        status = entry.get("oracle_status", "NONE")
        roots = entry.get("roots", [])
        if status == "NONE":
            gaps.append(entry["id"])
        for root in roots:
            module = _module_of_symbol(root)
            by_module.setdefault(module, []).append(entry["id"])
            prev = module_oracle.get(module)
            if prev is None or order[status] < order[prev]:
                module_oracle[module] = status
    for eid, reason in (
        (g["entry"], g["reason"]) for g in use_case_toml.get("characterization_gap", [])
    ):
        gaps.append(f"{eid} ({reason})")
    return by_module, module_oracle, sorted(set(gaps))


def _tested_modules(use_case_toml: dict) -> "set[str]":
    """테스트가 실제로 접촉하는 production 모듈 — behavior oracle 의 존재 증거.

    「진입점이 아니다」와 「oracle 이 없다」는 다르다(부재판별력). 진입 root 로 안 나타나도
    테스트 파일이 그 모듈을 import 하면 특성화 oracle 이 있는 것이다 — 이것이 없어야 진짜 공백.
    """
    out: "set[str]" = set()
    for tf in use_case_toml.get("test_file", []):
        out.update(tf.get("product_modules", []))
    return out


def _transaction_clusters_by_module(state_toml: dict) -> "dict[str, tuple[str, ...]]":
    out: "dict[str, list[str]]" = {}
    for cluster in state_toml.get("transaction_cluster", []):
        module = _module_of_symbol(cluster["src"])
        members = ",".join(cluster.get("members", []))
        out.setdefault(module, []).append(f"{cluster['src']} => {members}")
    return {module: tuple(sorted(values)) for module, values in out.items()}


def _effect_edges_by_module(effect) -> "dict[str, tuple[str, ...]]":
    out: "dict[str, set[str]]" = {}
    for fact in (*effect.effect_facts, *effect.composes_facts):
        module = _module_of_symbol(fact.src)
        out.setdefault(module, set()).add(f"{fact.rel}:{fact.src}->{fact.dst}")
    return {module: tuple(sorted(values)) for module, values in out.items()}


def _transport_edges_by_module(transport_toml: dict) -> "dict[str, tuple[str, ...]]":
    out: "dict[str, set[str]]" = {}
    for ep in transport_toml.get("endpoint", []):
        if ep.get("handler"):
            module = _module_of_symbol(ep["handler"])
            out.setdefault(module, set()).add(f"endpoint:{ep['screen']}/{ep['action']}")
    for channel in transport_toml.get("channel", []):
        if channel.get("producer"):
            module = _module_of_symbol(channel["producer"])
            out.setdefault(module, set()).add(
                f"channel:{channel.get('kind', 'unknown')}/{channel['name']}"
            )
    if transport_toml.get("host_method"):
        out.setdefault("hwpxfiller.webapp.app", set()).update(
            f"host_method:{method['name']}" for method in transport_toml["host_method"]
        )
    return {module: tuple(sorted(values)) for module, values in out.items()}


def _module_purpose(repo_root: Path, source_path: str, module: str, target: str) -> str:
    if target == "RETIRE":
        return f"{module}의 소비자 0 잔재를 안전하게 제거한다."
    try:
        tree = ast.parse((repo_root / source_path).read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree, clean=True) or ""
    except (OSError, SyntaxError, UnicodeError):
        doc = ""
    return doc.splitlines()[0].strip() if doc else f"{module} 구조적 패키지 셸"


def _source_write_overlaps(
    units: "list[MigrationUnit]",
) -> "tuple[tuple[str, tuple[str, ...]], ...]":
    owner: "dict[str, list[str]]" = {}
    for unit in units:
        for path in unit.source_write_set:
            owner.setdefault(path, []).append(unit.unit_id)
    return tuple(
        (path, tuple(sorted(set(unit_ids))))
        for path, unit_ids in sorted(owner.items())
        if len(set(unit_ids)) > 1
    )


def _packet_gaps(units: "list[MigrationUnit]") -> "tuple[str, ...]":
    """v2 실행 패킷의 필수 필드·실재 포인터를 fail-closed로 검사한다."""
    gaps: "list[str]" = []
    for unit in units:
        scalar_fields = {
            "purpose": unit.purpose,
            "closure_digest": unit.closure_digest,
            "compat_seam": unit.compat_seam,
            "removal_condition": unit.removal_condition,
            "rollback_condition": unit.rollback_condition,
            "stop_condition": unit.stop_condition,
        }
        for name, value in scalar_fields.items():
            if not value.strip():
                gaps.append(f"{unit.unit_id}.{name}")
        if not unit.source_write_set:
            gaps.append(f"{unit.unit_id}.source_write_set")
        if unit.oracle_status != "STRUCTURAL":
            if not unit.oracle_entries:
                gaps.append(f"{unit.unit_id}.oracle_entries")
            if not unit.positive_gates:
                gaps.append(f"{unit.unit_id}.positive_gates")
        if not unit.negative_gates:
            gaps.append(f"{unit.unit_id}.negative_gates")
    return tuple(sorted(gaps))


# ---------------------------------------------------------------------------
# 권위 귀속(#433 헌장)
# ---------------------------------------------------------------------------


def _package_prior(module: str) -> str:
    if module in _PRIOR_DOMAIN:
        return "DOMAIN"
    if module.startswith("hwpxcore.native"):
        return "EXTERNAL_ADAPTER"  # native = concrete 외부 효과
    if module.startswith("hwpxcore"):
        return "DOMAIN"  # 포맷 코어(루트 패키지 포함)
    if module.startswith("hwpxfiller.core"):
        return "DOMAIN"
    if module.startswith("hwpxfiller.data"):
        return "DOMAIN"
    if module.startswith("hwpxfiller.gui"):
        return "APPLICATION"
    if module.startswith("hwpxfiller.webapp"):
        return "FRONTEND_ADAPTER"
    if module == "hwpxfiller.cli":
        return "HOST"
    return "P_REVIEW_REQUIRED"  # batch·naming·web_artifact·root


def _assign_authority(
    module: str,
    symbols: "tuple[str, ...]",
    effect_classes: "set[str]",
    transport_kinds: "set[str]",
    stateful_tx: bool,
    shared_state: bool,
    composes: "tuple[str, ...]" = (),
) -> "tuple[str, str]":
    """한 모듈의 목표 권위와 사유. 애매하거나 헌장을 위반하면 P_REVIEW 로 시끄럽게 남긴다."""
    prior = _package_prior(module)
    effect_authorities = {
        EFFECT_CLASS_AUTHORITY[c] for c in effect_classes if c in EFFECT_CLASS_AUTHORITY
    }
    has_host = "HOST" in effect_authorities
    has_adapter = "EXTERNAL_ADAPTER" in effect_authorities
    has_ambient = "AMBIENT" in effect_authorities
    has_effect = has_host or has_adapter or has_ambient
    ambient = sorted(
        c for c in effect_classes if EFFECT_CLASS_AUTHORITY.get(c) == "AMBIENT"
    )

    # ① HOST 는 외곽 링이다 — OS·프로세스·창 효과와 그 조립을 모두 허용한다.
    if prior == "HOST":
        return "HOST", f"host 외곽 링 진입/조립(효과 {sorted(effect_classes) or '없음'})"

    # ② transport surface 는 표현 링이다 — 업무 코어에 있으면 안 된다. transport 소유가
    #    concrete/ambient 효과 증거를 조용히 억제하지 않는다(#532 리뷰): 효과를 겸하면
    #    표현/adapter 분리 결정이 필요하므로 P_REVIEW.
    if transport_kinds:
        if module == "hwpxfiller.webapp.app":
            return "HOST", "transport facade(host_method·창 조립)를 공개한다"
        if prior == "FRONTEND_ADAPTER":
            if has_effect:
                return (
                    "P_REVIEW_REQUIRED",
                    f"표현 controller 가 transport 와 concrete/ambient 효과"
                    f"({sorted(effect_classes)})를 겸한다 — external adapter 분리 결정 필요",
                )
            return "FRONTEND_ADAPTER", f"transport surface({sorted(transport_kinds)})를 소유한다"
        return (
            "P_REVIEW_REQUIRED",
            f"{prior} prior 인데 transport surface({sorted(transport_kinds)})를 든다 "
            "— 표현/업무 분리 결정 필요",
        )

    # ③ native/external adapter prior — host 효과만이면 HOST, 아니면 EXTERNAL_ADAPTER.
    if prior == "EXTERNAL_ADAPTER":
        if has_host and not has_adapter:
            return "HOST", f"native host 기능({sorted(effect_classes)})"
        return "EXTERNAL_ADAPTER", f"외부 효과 수행({sorted(effect_classes) or '재수출·상수'})"

    # ④ 표현 링(FRONTEND_ADAPTER prior)의 비-transport 헬퍼.
    if prior == "FRONTEND_ADAPTER":
        if has_effect:
            return (
                "P_REVIEW_REQUIRED",
                f"표현 링 모듈이 concrete/ambient 효과({sorted(effect_classes)})를 직접 만진다 "
                "— external adapter 분리 결정 필요",
            )
        return "FRONTEND_ADAPTER", "transport 없는 표현 링 헬퍼(효과 없음)"

    # ⑤ 업무 코어(DOMAIN/APPLICATION prior)가 concrete 효과를 직접 만진다 → 헌장 위반.
    if has_host or has_adapter:
        return (
            "P_REVIEW_REQUIRED",
            f"{prior} prior 가 concrete 효과({sorted(effect_classes)})를 직접 호출 "
            "— port 추출·adapter 분리 결정 필요(헌장 금지선)",
        )
    if has_ambient:
        return (
            "P_REVIEW_REQUIRED",
            f"{prior} prior 가 ambient 효과({ambient})를 직접 만진다 "
            "— clock/env/entropy port 주입 결정 필요",
        )
    # composes: 직접 외부 호출이 없어도 effect-bearing 클래스를 생성하면 adapter
    #           composition root 다 — 업무 코어에 두면 리뷰 없이 adapter 를 심는다(#532 리뷰).
    if composes:
        return (
            "P_REVIEW_REQUIRED",
            f"{prior} prior 가 effect-bearing 클래스({len(composes)}개)를 조립한다 "
            "— adapter composition root, 소유 결정 필요",
        )

    # ⑥ 효과·조립 없는 업무 코어 — prior 를 그대로 목표 권위로 확정.
    if prior in ("DOMAIN", "APPLICATION"):
        return prior, f"효과·transport·조립 없음, {prior} prior 확정"

    # ⑦ prior 자체가 미상(batch/naming/web_artifact/root).
    return "P_REVIEW_REQUIRED", f"패키지 prior 미상({module}) — 소유 결정 필요"


# ---------------------------------------------------------------------------
# migration unit·DAG·판정
# ---------------------------------------------------------------------------


def _build_units(
    repo_root: Path,
    module_auth: "dict[str, ModuleAuthority]",
    seams: "list[tuple[str, tuple[str, ...]]]",
    state_by_module: "dict[str, dict[str, set[str]]]",
    entries_by_module: "dict[str, list[str]]",
    module_oracle: "dict[str, str]",
    module_symbols: "dict[str, tuple[str, ...]]",
    module_paths: "dict[str, str]",
    oracle_pointers: "dict[str, set[str]]",
    decisions: "dict[str, AuthorityDecision]",
    transaction_clusters: "dict[str, tuple[str, ...]]",
    effect_edges: "dict[str, tuple[str, ...]]",
    transport_edges: "dict[str, tuple[str, ...]]",
    import_edges: "tuple[tuple[str, str], ...]",
) -> "list[MigrationUnit]":
    """모듈을 self-contained P2 packet으로 절단한다. 공유 상태만 원자 unit으로 병합한다."""
    # 공유 상태로 묶인 모듈 그룹(union-find 없이 간단 병합).
    groups: "list[set[str]]" = []
    for _state, modules in seams:
        target = set(modules)
        merged = [g for g in groups if g & target]
        for g in merged:
            groups.remove(g)
            target |= g
        groups.append(target)
    grouped_modules = {m for g in groups for m in g}

    units: "list[MigrationUnit]" = []
    seam_of: "dict[str, tuple[str, ...]]" = {}
    for group in groups:
        for m in group:
            seam_of[m] = tuple(sorted(group - {m}))

    def _unit_for(modules: "list[str]", uid: str) -> MigrationUnit:
        targets = {module_auth[m].target for m in modules if m in module_auth}
        if len(targets) == 1:
            target = next(iter(targets))
        else:
            target = "P_REVIEW_REQUIRED"
        state_writes: "set[str]" = set()
        state_reads: "set[str]" = set()
        for m in modules:
            state_writes |= state_by_module.get(m, {}).get("writes", set())
            state_writes |= state_by_module.get(m, {}).get("mutates", set())
            state_reads |= state_by_module.get(m, {}).get("reads", set())
        behavior_oracles: "set[str]" = set()
        entry_statuses: "set[str]" = set()
        for m in modules:
            behavior_oracles |= oracle_pointers.get(m, set())
            if m in module_oracle:
                entry_statuses.add(module_oracle[m])
        # 포트폴리오는 한 모듈에 수백 nodeid를 연결할 수 있다. packet은 테스트 센서스가
        # 아니라 실행 handoff이므로 entry별 포인터는 전부 보존하고, 그 밖의 대표 양성
        # gate만 결정론적으로 제한한다(전수는 TEST_PORTFOLIO와 02E가 계속 소유한다).
        entry_specific = sorted(p for p in behavior_oracles if " <- " in p)
        exact_nodeids = sorted(
            p for p in behavior_oracles if "::" in p and " :: module-contact" not in p
        )
        module_contacts = sorted(p for p in behavior_oracles if " :: module-contact" in p)
        behavior_oracles = set(entry_specific + exact_nodeids[:6] + module_contacts[:2])
        closure = sorted(s for m in modules for s in module_symbols.get(m, ()))
        sym_count = len(closure)
        closure_digest = hashlib.sha256("\n".join(closure).encode("utf-8")).hexdigest()
        # 진입 oracle 이 CORE 면 CORE, ENTRY 나 테스트 피복이 있으면 ENTRY, 둘 다 없으면 공백.
        # 0-심볼 패키지 init 은 pin 할 behavior 가 없다 — 공백이 아니라 STRUCTURAL.
        if sym_count == 0:
            oracle_status = "STRUCTURAL"
        elif "CORE" in entry_statuses:
            oracle_status = "CORE"
        elif "ENTRY" in entry_statuses or behavior_oracles:
            oracle_status = "ENTRY"
        else:
            oracle_status = "NONE"
        shared_with: "set[str]" = set()
        for m in modules:
            shared_with |= set(seam_of.get(m, ()))
        shared_with -= set(modules)
        blocking: "list[str]" = []
        if target == "P_REVIEW_REQUIRED":
            blocking.append("authority-unknown")
        if oracle_status == "NONE":
            blocking.append("oracle-gap")
        source_write_set = tuple(sorted(module_paths[m] for m in modules))
        adjacent = tuple(
            sorted(
                {dst for src, dst in import_edges if src in modules and dst not in modules}
                | {src for src, dst in import_edges if dst in modules and src not in modules}
            )
        )
        module_effect_edges = tuple(
            sorted(edge for m in modules for edge in effect_edges.get(m, ()))
        )
        module_transport_edges = tuple(
            sorted(edge for m in modules for edge in transport_edges.get(m, ()))
        )
        module_transactions = tuple(
            sorted(edge for m in modules for edge in transaction_clusters.get(m, ()))
        )
        persistence_classes = {"fs", "archive", "excel", "network", "registry", "lock"}
        has_persistence = any(
            persistence_classes & set(module_auth[m].effect_classes) for m in modules
        )
        persistence_edges = module_effect_edges if has_persistence else ()
        outputs = tuple(
            sorted(
                [s for s in closure if not s.rpartition(":")[2].startswith("_")]
                + [f"entry:{e}" for m in modules for e in entries_by_module.get(m, [])]
            )
        )
        responsibilities: "list[str]" = [f"public-symbols:{len(outputs)}"]
        if state_writes:
            responsibilities.append(f"state-write:{len(state_writes)}")
        if state_reads:
            responsibilities.append(f"state-read:{len(state_reads)}")
        if module_effect_edges:
            responsibilities.append(f"effect-edge:{len(module_effect_edges)}")
        if module_transport_edges:
            responsibilities.append(f"transport-edge:{len(module_transport_edges)}")
        if any(entries_by_module.get(m) for m in modules):
            responsibilities.append(
                f"entry:{sum(len(entries_by_module.get(m, [])) for m in modules)}"
            )
        contracts: "set[str]" = set()
        if target in {"DOMAIN", "APPLICATION", "FRONTEND_ADAPTER"}:
            for m in modules:
                contracts.update(f"port:{kind}" for kind in module_auth[m].effect_classes)
                contracts.update(f"composition-port:{edge}" for edge in module_auth[m].composes)
        extraction_obligations = tuple(
            sorted(item for m in modules for item in decisions.get(m, AuthorityDecision(m, target, "", ())).extractions)
        )
        module_label = ", ".join(modules)
        compat = (
            f"{module_label}: 기존 screen/action 및 snapshot 이름을 delegating facade로 유지"
            if target == "FRONTEND_ADAPTER"
            else f"{module_label}: 기존 import/public symbol을 새 {target} 구현으로 위임"
        )
        if target == "RETIRE":
            compat = f"{module_label}: 제거 커밋 전 consumer-zero를 재확인하고 package shell은 보존"
        removal = (
            f"{module_label}: production consumer-zero 확인 뒤 모듈/잔재와 전용 테스트를 함께 제거"
            if target == "RETIRE"
            else f"{module_label}: old→new 승계 뒤 legacy symbol consumer-zero와 oracle 통과 시 제거"
        )
        return MigrationUnit(
            unit_id=uid,
            target=target,
            modules=tuple(sorted(modules)),
            symbol_count=sym_count,
            purpose=" / ".join(
                _module_purpose(repo_root, module_paths[m], m, target) for m in modules
            ),
            current_responsibilities=tuple(responsibilities),
            source_symbols=tuple(closure),
            closure_digest=closure_digest,
            source_write_set=source_write_set,
            read_only_adjacent=adjacent,
            write_set=tuple(sorted(state_writes)),
            state_reads=tuple(sorted(state_reads)),
            transaction_clusters=module_transactions,
            effect_edges=module_effect_edges,
            persistence_edges=persistence_edges,
            transport_edges=module_transport_edges,
            target_inputs=adjacent,
            target_outputs=outputs,
            required_effect_contracts=tuple(sorted(contracts)),
            extraction_obligations=extraction_obligations,
            shared_with=tuple(sorted(shared_with)),
            oracle_status=oracle_status,
            oracle_entries=tuple(sorted(behavior_oracles)),
            positive_gates=tuple(sorted(behavior_oracles)),
            negative_gates=(
                "tests/test_authority_gate_04.py::test_migration_packet_mutations_turn_red",
            ),
            predecessors=(),
            successors=(),
            compat_seam=compat,
            removal_condition=removal,
            rollback_condition=(
                f"{module_label}: unit 변경만 되돌리고 기존 facade/public surface를 권위로 복귀"
            ),
            stop_condition=(
                f"{module_label}: behavior oracle, effect contract, source-write-set 중 하나라도 "
                "드리프트하면 이관을 중단"
            ),
            blocking=tuple(blocking),
        )

    idx = 0
    for group in sorted(groups, key=lambda g: sorted(g)[0]):
        idx += 1
        units.append(_unit_for(sorted(group), f"unit-seam-{idx:02d}"))
    for module in sorted(module_auth):
        if module in grouped_modules:
            continue
        idx += 1
        units.append(_unit_for([module], f"unit-{idx:02d}"))

    # 선후 DAG — central seam 으로 묶인 unit 은 서로 선행(원자 이관), write-set 겹침도 선후.
    by_module_unit = {m: u.unit_id for u in units for m in u.modules}
    write_owner: "dict[str, set[str]]" = {}
    for u in units:
        for st in u.write_set:
            write_owner.setdefault(st, set()).add(u.unit_id)
    linked: "dict[str, set[str]]" = {u.unit_id: set() for u in units}
    for owners in write_owner.values():
        if len(owners) > 1:
            for a in owners:
                linked[a] |= owners - {a}
    for _state, modules in seams:
        uids = {by_module_unit[m] for m in modules if m in by_module_unit}
        for a in uids:
            linked[a] |= uids - {a}

    final: "list[MigrationUnit]" = []
    for u in units:
        neighbours = tuple(sorted(linked[u.unit_id]))
        final.append(replace(u, predecessors=neighbours, successors=neighbours))
    return final


def _verdict(
    contradictions: "list[Contradiction]",
    units: "list[MigrationUnit]",
    sccs: int,
    dynamic_open: int,
    oracle_gaps: "tuple[str, ...]" = (),
    dependency: "DependencyAnalysis | None" = None,
    unowned: "tuple[str, ...]" = (),
    packet_gaps: "tuple[str, ...]" = (),
    oracle_pointer_gaps: "tuple[str, ...]" = (),
    source_write_overlaps: "tuple[tuple[str, tuple[str, ...]], ...]" = (),
    r_handoff_gaps: "tuple[str, ...]" = (),
) -> "tuple[str, list[str]]":
    reasons: "list[str]" = []
    if contradictions:
        reasons.append(f"원장 간 미해결 contradiction {len(contradictions)}건")
        return "BLOCKED", reasons
    direction_violations = len(dependency.violations) if dependency else 0
    if direction_violations:
        reasons.append(f"결정 권위 간 의존 방향 위반 {direction_violations}건(안쪽→바깥쪽)")
    if unowned:
        reasons.append(f"권위 원장 밖 effect/state/transport 표면 {len(unowned)}건(소유 불명)")
    if packet_gaps:
        reasons.append(f"P2 실행 패킷 필수 필드 공백 {len(packet_gaps)}건")
    if oracle_pointer_gaps:
        reasons.append(f"실재 behavior oracle 포인터 공백 {len(oracle_pointer_gaps)}건")
    if source_write_overlaps:
        reasons.append(f"P2 source write-set 충돌 {len(source_write_overlaps)}건")
    if r_handoff_gaps:
        reasons.append(f"R→P 권위 핸드오프 불일치 {len(r_handoff_gaps)}건")
    unknown = [u.unit_id for u in units if u.target == "P_REVIEW_REQUIRED"]
    unit_oracle_gap = [u.unit_id for u in units if u.oracle_status == "NONE"]
    if unknown:
        reasons.append(f"소유 불명 unit {len(unknown)}건(P_REVIEW_REQUIRED)")
    if unit_oracle_gap:
        reasons.append(f"oracle 공백 unit {len(unit_oracle_gap)}건")
    # entry-level oracle 공백은 unit 집계로 뭉개지면 안 된다(#532 리뷰): 한 모듈의 한 진입만
    # 특성화돼도 unit 은 ENTRY 로 서지만, 미특성화 진입은 여전히 안전 이관을 막는다.
    if oracle_gaps:
        reasons.append(f"entry-level oracle 공백 {len(oracle_gaps)}건(특성화 미보유 진입)")
    # 미해결 동적 call edge 는 정적 그래프가 못 본 이관 의존을 숨긴다 — ready 로 넘기지 않는다.
    if dynamic_open:
        reasons.append(f"미해결 동적 call edge {dynamic_open}건(정적 그래프 밖 의존 은닉)")
    if sccs:
        reasons.append(f"거대 원자 cluster(SCC) {sccs}건")
    if (
        unknown
        or unit_oracle_gap
        or oracle_gaps
        or dynamic_open
        or sccs
        or direction_violations
        or unowned
        or packet_gaps
        or oracle_pointer_gaps
        or source_write_overlaps
        or r_handoff_gaps
    ):
        return "BLOCKED", reasons
    seam_units = [u for u in units if u.predecessors]
    if seam_units:
        reasons.append(
            f"central seam 선행 뒤 병렬화 가능 — 묶인 unit {len(seam_units)}건"
        )
        return "ORDERED_WAVES_READY", reasons
    reasons.append(
        "모든 unit 이 독립 source/state write set·실재 oracle·효과 계약을 보유하고 "
        "central seam 외 선후 강제가 없음"
    )
    return "ONE_WAVE_READY", reasons


# ---------------------------------------------------------------------------
# 합성 진입점
# ---------------------------------------------------------------------------


def synthesize(repo_root: Path) -> SynthesisResult:
    repo_root = Path(repo_root)
    shards = {shard: _load_toml(repo_root, rel) for shard, rel in SHARD_LEDGERS}

    effect = build_effect(repo_root)
    static = effect.static
    live_base = static.base_digest
    live_graph = static.graph_digest
    live_effect = effect.effect_digest

    contradictions, shard_digests = _merge_and_contradictions(
        repo_root, shards, live_base, live_graph, live_effect
    )

    inv_modules = _inventory_modules(shards["01"])
    inv_paths = _inventory_paths(shards["01"])
    decisions, r_handoff, decision_problems = _load_decisions(repo_root, set(inv_modules))
    contradictions.extend(decision_problems)
    shard_digests["03.decisions"] = _content_digest(repo_root, DECISION_LEDGER)
    shard_digests["R.ownership"] = _content_digest(repo_root, R_OWNERSHIP_LEDGER)
    shard_digests["R.verification"] = _content_digest(repo_root, R_VERIFICATION_LEDGER)
    effect_by_module = _effect_classes_by_module(effect.effect_facts)
    composes_by_module = _composes_by_module(effect.composes_facts)
    state_by_module = _state_by_module(shards["02b"])
    tx_modules = _tx_modules(shards["02b"])
    seams = _shared_state_seams(shards["02b"])
    shared_modules = {m for _s, mods in seams for m in mods}
    transport_by_module = _transport_modules(shards["02d"])
    host_module = _host_method_module(shards["02d"])
    if host_module:
        transport_by_module.setdefault(host_module, set()).add("host_method")
    entries_by_module, module_oracle, oracle_gaps = _entries_by_module(shards["02e"])
    oracle_pointers = _oracle_pointers(shards["02e"])
    for module, pointers in _portfolio_oracles(repo_root).items():
        oracle_pointers.setdefault(module, set()).update(pointers)
    r_handoff_gaps = tuple(_r_handoff_problems(repo_root, r_handoff, decisions))

    modules: "list[ModuleAuthority]" = []
    module_auth: "dict[str, ModuleAuthority]" = {}
    for module in sorted(inv_modules):
        symbols = inv_modules[module]
        effect_classes = effect_by_module.get(module, set())
        transport_kinds = transport_by_module.get(module, set())
        stateful_tx = module in tx_modules
        shared = module in shared_modules
        composes = composes_by_module.get(module, ())
        measured_target, measured_reason = _assign_authority(
            module, symbols, effect_classes, transport_kinds, stateful_tx, shared, composes
        )
        decision = decisions.get(module)
        if decision is not None:
            target = decision.target
            reason = f"사람 판정: {decision.reason} / 측정 신호: {measured_reason}"
        else:
            target, reason = measured_target, measured_reason
        if measured_target == "P_REVIEW_REQUIRED" and decision is None:
            contradictions.append(
                Contradiction("decision_missing", f"{module}: P_REVIEW_REQUIRED 사람 판정 부재")
            )
        ma = ModuleAuthority(
            module=module,
            target=target,
            prior=_package_prior(module),
            reason=reason,
            symbol_count=len(symbols),
            effect_classes=tuple(sorted(effect_classes)),
            composes=composes,
            transport=bool(transport_kinds),
            stateful_tx=stateful_tx,
            shared_state=shared,
            entries=tuple(sorted(entries_by_module.get(module, []))),
        )
        modules.append(ma)
        module_auth[module] = ma

    internal_import_edges = _import_edges(static)
    units = _build_units(
        repo_root,
        module_auth,
        seams,
        state_by_module,
        entries_by_module,
        module_oracle,
        inv_modules,
        inv_paths,
        oracle_pointers,
        decisions,
        _transaction_clusters_by_module(shards["02b"]),
        _effect_edges_by_module(effect),
        _transport_edges_by_module(shards["02d"]),
        internal_import_edges,
    )

    module_targets = {m.module: m.target for m in modules}
    dependency = _direction_analysis(module_targets, internal_import_edges, set(decisions))
    # effect/state/transport 을 지는 모든 모듈이 권위 원장 안에 있는가 — UNKNOWN 을 green 으로
    # 넘기지 않는다. 신규 effectful/stateful/transport 모듈이 인벤토리 밖이면 여기서 걸린다.
    surface_modules = set(effect_by_module) | set(state_by_module) | set(transport_by_module)
    unowned_surfaces = tuple(sorted(m for m in surface_modules if m not in module_targets))

    sccs = int(shards["02a"].get("counts", {}).get("sccs", 0))
    dynamic_open = int(shards["02a"].get("counts", {}).get("dynamic_open", 0))
    packet_gaps = _packet_gaps(units)
    oracle_pointer_gaps = tuple(
        sorted(u.unit_id for u in units if u.oracle_status != "STRUCTURAL" and not u.oracle_entries)
    )
    source_write_overlaps = _source_write_overlaps(units)
    verdict, reasons = _verdict(
        contradictions,
        units,
        sccs,
        dynamic_open,
        tuple(oracle_gaps),
        dependency,
        unowned_surfaces,
        packet_gaps,
        oracle_pointer_gaps,
        source_write_overlaps,
        r_handoff_gaps,
    )

    return SynthesisResult(
        baseline_sha=_current_sha(repo_root),
        source_digest=_source_digest(repo_root, static.closure),
        base_facts=live_base,
        graph_facts=live_graph,
        effect_facts=live_effect,
        sccs=sccs,
        dynamic_open=dynamic_open,
        shard_digests=shard_digests,
        contradictions=tuple(contradictions),
        modules=tuple(modules),
        units=tuple(units),
        shared_seams=tuple(seams),
        oracle_gaps=tuple(oracle_gaps),
        oracle_pointer_gaps=oracle_pointer_gaps,
        packet_gaps=packet_gaps,
        source_write_overlaps=source_write_overlaps,
        r_handoff_gaps=r_handoff_gaps,
        dependency=dependency,
        unowned_surfaces=unowned_surfaces,
        verdict=verdict,
        verdict_reasons=tuple(reasons),
    )


def _current_sha(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return "0" * 40
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip() or "0" * 40


def _source_digest(repo_root: Path, closure) -> str:
    """production 폐포 파일의 **바이트** 내용 digest.

    ``facts_digest`` 는 심볼·사실 record 를 해시한다 — 순수 계산·리터럴만 바꾼 편집은 사실
    그래프를 안 움직여 그 digest 가 그대로다(#532 리뷰). 이 digest 는 파일 바이트를 직접
    해시하므로 그런 편집도 잡는다. 합성이 「어떤 소스를 baseline 으로 분석했는가」의 정직한 핀.
    """
    hasher = hashlib.sha256()
    for mf in sorted(closure.modules, key=lambda m: m.path):
        hasher.update(mf.path.encode("utf-8"))
        hasher.update(b"\0")
        # 줄바꿈을 정규화한다 — .gitattributes(eol=lf)로 CI 는 LF, 로컬 working tree 는
        # CRLF 일 수 있어(예: core/__init__.py) 바이트 직해시는 환경마다 갈린다. 내용 편집만
        # 잡고 줄바꿈 스타일은 무시한다.
        raw = (repo_root / mf.path).read_bytes()
        hasher.update(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        hasher.update(b"\0")
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# 렌더·검사·재생성
# ---------------------------------------------------------------------------

_HEADER = f"""# 생성 파일 — 직접 편집 금지. P1-03 중앙 합성 원장 — Authority·migration DAG(#518).
# 원천: P1-02A~E 여섯 원장의 content-anchor merge + effect_graph 재계측 교차검증
# 재생성: {REGEN_COMMAND}
# 검사:   {REGEN_COMMAND} --check
schema = "{SCHEMA}"
"""


def _q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(repo_root: Path) -> str:
    result = synthesize(repo_root)
    parts = [_HEADER]

    parts.append("\n[anchor]\n")
    parts.append("# 여섯 shard 공통 기반 사실 — 같은 측정 위임의 증거.\n")
    parts.append(f"base_facts = {_q(result.base_facts)}\n")
    parts.append(f"graph_facts = {_q(result.graph_facts)}\n")
    parts.append(f"effect_facts = {_q(result.effect_facts)}\n")
    parts.append("# 폐포 파일 바이트 digest — 사실을 안 바꾸는 리터럴 편집도 잡는 baseline 핀.\n")
    parts.append(f"source_digest = {_q(result.source_digest)}\n")

    parts.append("\n[inputs]\n")
    parts.append("# 소비한 원장과 각 원장의 기반-사실 핀(merge 일치 증거).\n")
    for key in sorted(result.shard_digests):
        parts.append(f"{_q(key)} = {_q(result.shard_digests[key])}\n")

    by_target = {a: 0 for a in AUTHORITIES}
    for m in result.modules:
        by_target[m.target] += 1
    unit_targets = {a: 0 for a in AUTHORITIES}
    for u in result.units:
        unit_targets[u.target] = unit_targets.get(u.target, 0) + 1

    parts.append("\n[counts]\n")
    parts.append(f"modules = {len(result.modules)}\n")
    parts.append(f"symbols = {sum(m.symbol_count for m in result.modules)}\n")
    parts.append(f"sccs = {result.sccs}\n")
    parts.append(f"dynamic_open = {result.dynamic_open}\n")
    parts.append(f"contradictions = {len(result.contradictions)}\n")
    parts.append(f"migration_units = {len(result.units)}\n")
    parts.append(f"shared_seams = {len(result.shared_seams)}\n")
    parts.append(f"oracle_gaps = {len(result.oracle_gaps)}\n")
    parts.append(f"oracle_pointer_gaps = {len(result.oracle_pointer_gaps)}\n")
    parts.append(f"packet_gaps = {len(result.packet_gaps)}\n")
    parts.append(f"source_write_overlaps = {len(result.source_write_overlaps)}\n")
    parts.append(f"r_handoff_gaps = {len(result.r_handoff_gaps)}\n")
    parts.append(f"unowned_surfaces = {len(result.unowned_surfaces)}\n")
    parts.append(f"direction_violations = {len(result.dependency.violations)}\n")
    parts.append(f"planned_direction_obligations = {len(result.dependency.planned_violations)}\n")
    parts.append(f"p_review_modules = {by_target['P_REVIEW_REQUIRED']}\n")
    parts.append(f"p_review_units = {unit_targets['P_REVIEW_REQUIRED']}\n")

    parts.append("\n[authority_by_target]\n")
    for auth in AUTHORITIES:
        parts.append(f"{auth} = {by_target[auth]}\n")

    parts.append("\n[verdict]\n")
    parts.append(f"final = {_q(result.verdict)}\n")
    parts.append("reasons = [\n")
    parts.extend(f"  {_q(r)},\n" for r in result.verdict_reasons)
    parts.append("]\n")

    dep = result.dependency
    parts.append("\n[dependency]\n")
    parts.append("# import 방향 판정(#433 링 서열). 결정 권위 간 위반은 0 이어야 한다.\n")
    parts.append(f"internal_edges = {dep.internal_edges}\n")
    parts.append(f"decided_edges = {dep.decided_edges}\n")
    parts.append(f"deferred_edges = {dep.deferred_edges}\n")  # 끝점이 P_REVIEW — 방향 판단 유보
    parts.append(f"peer_edges = {dep.peer_edges}\n")  # 외곽 링 peer 간(방향 무관)
    parts.append(f"violations = {len(dep.violations)}\n")
    parts.append(f"planned_obligations = {len(dep.planned_violations)}\n")

    parts.append("\n# 의존 방향 위반 — 안쪽 링이 바깥쪽을 import 한 자리(있으면 헌장 금지선).\n")
    for v in dep.violations:
        parts.append("\n[[direction_violation]]\n")
        parts.append(f"src = {_q(v.src)}\n")
        parts.append(f"src_target = {_q(v.src_target)}\n")
        parts.append(f"dst = {_q(v.dst)}\n")
        parts.append(f"dst_target = {_q(v.dst_target)}\n")

    parts.append("\n# 현재 소스의 계획된 방향 위반 — 해당 unit의 extraction_obligations로 P2에서 제거.\n")
    for v in dep.planned_violations:
        parts.append("\n[[planned_direction_obligation]]\n")
        parts.append(f"src = {_q(v.src)}\n")
        parts.append(f"src_target = {_q(v.src_target)}\n")
        parts.append(f"dst = {_q(v.dst)}\n")
        parts.append(f"dst_target = {_q(v.dst_target)}\n")

    parts.append("\n# 원장 간 사실 충돌 — 없으면 merge 가 일치했다는 뜻이다.\n")
    for c in result.contradictions:
        parts.append("\n[[contradiction]]\n")
        parts.append(f"kind = {_q(c.kind)}\n")
        parts.append(f"detail = {_q(c.detail)}\n")

    parts.append("\n# 모듈 경계를 넘는 공유 상태 — central seam(원자 이관 강제).\n")
    for state, modules in result.shared_seams:
        parts.append("\n[[shared_seam]]\n")
        parts.append(f"state = {_q(state)}\n")
        parts.append(f"modules = [{', '.join(_q(m) for m in modules)}]\n")

    parts.append("\n# 모듈별 목표 권위 판정과 사실 근거.\n")
    for m in result.modules:
        parts.append("\n[[module_authority]]\n")
        parts.append(f"module = {_q(m.module)}\n")
        parts.append(f"target = {_q(m.target)}\n")
        parts.append(f"prior = {_q(m.prior)}\n")
        parts.append(f"symbols = {m.symbol_count}\n")
        parts.append(f"effect_classes = [{', '.join(_q(c) for c in m.effect_classes)}]\n")
        parts.append(f"composes = [{', '.join(_q(c) for c in m.composes)}]\n")
        parts.append(f"transport = {str(m.transport).lower()}\n")
        parts.append(f"stateful_tx = {str(m.stateful_tx).lower()}\n")
        parts.append(f"shared_state = {str(m.shared_state).lower()}\n")
        parts.append(f"reason = {_q(m.reason)}\n")

    parts.append("\n# P2 migration unit — source closure·write set·oracle·선후 DAG·제거 조건.\n")
    for u in result.units:
        parts.append("\n[[migration_unit]]\n")
        parts.append(f"id = {_q(u.unit_id)}\n")
        parts.append(f"target = {_q(u.target)}\n")
        parts.append(f"modules = [{', '.join(_q(m) for m in u.modules)}]\n")
        parts.append(f"symbol_count = {u.symbol_count}\n")
        parts.append(f"purpose = {_q(u.purpose)}\n")
        parts.append(f"closure_digest = {_q(u.closure_digest)}\n")
        parts.append(f"oracle_status = {_q(u.oracle_status)}\n")
        parts.append(f"predecessors = [{', '.join(_q(p) for p in u.predecessors)}]\n")
        parts.append(f"successors = [{', '.join(_q(p) for p in u.successors)}]\n")
        parts.append(f"shared_with = [{', '.join(_q(s) for s in u.shared_with)}]\n")
        parts.append(f"write_set_count = {len(u.write_set)}\n")
        parts.append(f"source_write_set_count = {len(u.source_write_set)}\n")
        parts.append(f"blocking = [{', '.join(_q(b) for b in u.blocking)}]\n")
        parts.append(f"compat_seam = {_q(u.compat_seam)}\n")
        parts.append(f"removal_condition = {_q(u.removal_condition)}\n")
        parts.append(f"rollback_condition = {_q(u.rollback_condition)}\n")
        parts.append(f"stop_condition = {_q(u.stop_condition)}\n")
        for name, values in (
            ("current_responsibilities", u.current_responsibilities),
            ("source_symbols", u.source_symbols),
            ("source_write_set", u.source_write_set),
            ("read_only_adjacent", u.read_only_adjacent),
            ("state_reads", u.state_reads),
            ("transaction_clusters", u.transaction_clusters),
            ("effect_edges", u.effect_edges),
            ("persistence_edges", u.persistence_edges),
            ("transport_edges", u.transport_edges),
            ("target_inputs", u.target_inputs),
            ("target_outputs", u.target_outputs),
            ("required_effect_contracts", u.required_effect_contracts),
            ("extraction_obligations", u.extraction_obligations),
            ("positive_gates", u.positive_gates),
            ("negative_gates", u.negative_gates),
        ):
            parts.append(f"{name} = [\n")
            parts.extend(f"  {_q(value)},\n" for value in values)
            parts.append("]\n")
        # 원자 이관 대상 상태 좌표를 그대로 남긴다 — count 만으로는 같은 크기의 다른 write set 을
        # 구분 못 하고, P2 가 무엇을 함께 옮겨야 하는지 알 수 없다(#532 리뷰).
        parts.append("write_set = [\n")
        parts.extend(f"  {_q(s)},\n" for s in u.write_set)
        parts.append("]\n")
        parts.append("oracle_entries = [\n")
        parts.extend(f"  {_q(e)},\n" for e in u.oracle_entries)
        parts.append("]\n")

    for path, unit_ids in result.source_write_overlaps:
        parts.append("\n[[source_write_overlap]]\n")
        parts.append(f"path = {_q(path)}\n")
        parts.append(f"units = [{', '.join(_q(uid) for uid in unit_ids)}]\n")

    for gap in result.packet_gaps:
        parts.append("\n[[packet_gap]]\n")
        parts.append(f"field = {_q(gap)}\n")

    for gap in result.r_handoff_gaps:
        parts.append("\n[[r_handoff_gap]]\n")
        parts.append(f"detail = {_q(gap)}\n")

    parts.append("\n# oracle 공백 — behavior oracle 이 없어 안전 이관이 막히는 진입.\n")
    for gap in result.oracle_gaps:
        parts.append("\n[[oracle_gap]]\n")
        parts.append(f"entry = {_q(gap)}\n")

    return "".join(parts)


def check(repo_root: Path) -> "list[str]":
    repo_root = Path(repo_root)
    target = repo_root / LEDGER_REL_PATH
    try:
        expected = render(repo_root)
    except FactGraphError as exc:
        return [f"{LEDGER_REL_PATH}: 합성 실패 — {exc}"]
    if not target.is_file():
        return [f"{LEDGER_REL_PATH}: 생성물이 없습니다 — `{REGEN_COMMAND}` 로 생성하세요."]
    if target.read_text(encoding="utf-8") == expected:
        return []
    problems = [f"{LEDGER_REL_PATH}: 원장 드리프트 — `{REGEN_COMMAND}` 로 재생성하세요."]
    try:
        actual = tomllib.loads(target.read_text(encoding="utf-8"))
        fresh = tomllib.loads(expected)
        for section in ("anchor", "counts", "verdict", "dependency"):
            left = actual.get(section, {})
            right = fresh.get(section, {})
            for key in sorted(set(left) | set(right)):
                if left.get(key) != right.get(key):
                    problems.append(
                        f"  {section}.{key}: 커밋본 {left.get(key)!r} ≠ 재합성 {right.get(key)!r}"
                    )
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"  커밋본을 파싱할 수 없다(직접 편집 흔적?): {exc}")
    return problems


def rewrite(repo_root: Path) -> Path:
    repo_root = Path(repo_root)
    target = repo_root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(repo_root))
    return target
