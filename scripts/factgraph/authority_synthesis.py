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
SCHEMA = "authority-synthesis-03/v1"

#: 여섯 shard 공통 기반 사실 앵커(P1-01 폐포). src/ 가 이 값과 다르면 원장이 stale 이다.
ANCHOR_BASE_FACTS = "44f6e783fea3d6a88a4f0fd55d794a2d6a318a95109b1512a4c0a13ff784a6c8"
ANCHOR_GRAPH_FACTS = "cae41aa86a63fa35c8aa085eba03b8b3fbf0ca14d2631325540760e1d5b4d9f9"

#: 소비하는 원장 경로. 각 원장의 기반-사실 핀 좌표는 _SHARD_ANCHORS 가 안다.
INVENTORY_LEDGER = "docs/factgraph/python_symbol_inventory.toml"
STATIC_LEDGER = "docs/factgraph/static_graph_02a.toml"
STATE_LEDGER = "docs/factgraph/state_graph_02b.toml"
EFFECT_LEDGER = "docs/factgraph/effect_graph_02c.toml"
TRANSPORT_LEDGER = "docs/factgraph/transport_graph_02d.toml"
USE_CASE_LEDGER = "docs/factgraph/use_case_graph_02e.toml"

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
    transport: bool
    stateful_tx: bool
    shared_state: bool
    entries: "tuple[str, ...]"


@dataclass(frozen=True)
class MigrationUnit:
    """P2 병렬 절단 단위 하나 — source closure·write set·oracle·선후 DAG·제거 조건."""

    unit_id: str
    target: str
    modules: "tuple[str, ...]"
    symbol_count: int
    closure_digest: str
    write_set: "tuple[str, ...]"
    shared_with: "tuple[str, ...]"
    oracle_status: str
    oracle_entries: "tuple[str, ...]"
    predecessors: "tuple[str, ...]"
    successors: "tuple[str, ...]"
    compat_seam: str
    removal_condition: str
    blocking: "tuple[str, ...]"


@dataclass
class SynthesisResult:
    baseline_sha: str
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
) -> "tuple[str, str]":
    """한 모듈의 목표 권위와 사유. 애매하거나 헌장을 위반하면 P_REVIEW 로 시끄럽게 남긴다."""
    prior = _package_prior(module)
    effect_authorities = {
        EFFECT_CLASS_AUTHORITY[c] for c in effect_classes if c in EFFECT_CLASS_AUTHORITY
    }
    has_host = "HOST" in effect_authorities
    has_adapter = "EXTERNAL_ADAPTER" in effect_authorities
    has_ambient = "AMBIENT" in effect_authorities
    ambient = sorted(
        c for c in effect_classes if EFFECT_CLASS_AUTHORITY.get(c) == "AMBIENT"
    )

    # ① HOST 는 외곽 링이다 — OS·프로세스·창 효과와 그 조립을 모두 허용한다.
    if prior == "HOST":
        return "HOST", f"host 외곽 링 진입/조립(효과 {sorted(effect_classes) or '없음'})"

    # ② transport surface 는 표현 링이다 — 업무 코어에 있으면 안 된다.
    if transport_kinds:
        if module == "hwpxfiller.webapp.app":
            return "HOST", "transport facade(host_method·창 조립)를 공개한다"
        if prior == "FRONTEND_ADAPTER":
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
        if has_host or has_adapter or has_ambient:
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

    # ⑥ 효과 없는 업무 코어 — prior 를 그대로 목표 권위로 확정.
    if prior in ("DOMAIN", "APPLICATION"):
        return prior, f"효과·transport 없음, {prior} prior 확정"

    # ⑦ prior 자체가 미상(batch/naming/web_artifact/root).
    return "P_REVIEW_REQUIRED", f"패키지 prior 미상({module}) — 소유 결정 필요"


# ---------------------------------------------------------------------------
# migration unit·DAG·판정
# ---------------------------------------------------------------------------


def _build_units(
    module_auth: "dict[str, ModuleAuthority]",
    seams: "list[tuple[str, tuple[str, ...]]]",
    state_by_module: "dict[str, dict[str, set[str]]]",
    entries_by_module: "dict[str, list[str]]",
    module_oracle: "dict[str, str]",
    module_symbols: "dict[str, tuple[str, ...]]",
    tested_modules: "set[str]",
) -> "list[MigrationUnit]":
    """모듈을 migration unit 으로 절단한다. cross-module 공유 상태는 한 unit 으로 병합한다."""
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
        write_set: "set[str]" = set()
        for m in modules:
            write_set |= state_by_module.get(m, {}).get("writes", set())
            write_set |= state_by_module.get(m, {}).get("mutates", set())
        oracle_entries: "list[str]" = []
        entry_statuses: "set[str]" = set()
        for m in modules:
            oracle_entries.extend(entries_by_module.get(m, []))
            if m in module_oracle:
                entry_statuses.add(module_oracle[m])
        tested = any(m in tested_modules for m in modules)
        closure = sorted(s for m in modules for s in module_symbols.get(m, ()))
        sym_count = len(closure)
        closure_digest = hashlib.sha256("\n".join(closure).encode("utf-8")).hexdigest()
        # 진입 oracle 이 CORE 면 CORE, ENTRY 나 테스트 피복이 있으면 ENTRY, 둘 다 없으면 공백.
        # 0-심볼 패키지 init 은 pin 할 behavior 가 없다 — 공백이 아니라 STRUCTURAL.
        if sym_count == 0:
            oracle_status = "STRUCTURAL"
        elif "CORE" in entry_statuses:
            oracle_status = "CORE"
        elif "ENTRY" in entry_statuses or tested:
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
        compat = (
            "legacy screen/action 계약을 adapter 로 유지하며 이관"
            if target in ("FRONTEND_ADAPTER", "HOST")
            else "in-memory 구현이 Application 이 요구하는 외부 효과 계약을 따른다"
            if target == "EXTERNAL_ADAPTER"
            else "공개 이음새(입력·결과·요구 효과)를 타입계약으로 드러낸 뒤 이관"
        )
        removal = (
            "consumer-zero 도달 시 제거"
            if target == "RETIRE"
            else "old→new 책임 승계 후 legacy 심볼 consumer-zero 확인"
        )
        return MigrationUnit(
            unit_id=uid,
            target=target,
            modules=tuple(sorted(modules)),
            symbol_count=sym_count,
            closure_digest=closure_digest,
            write_set=tuple(sorted(write_set)),
            shared_with=tuple(sorted(shared_with)),
            oracle_status=oracle_status,
            oracle_entries=tuple(sorted(set(oracle_entries))),
            predecessors=(),
            successors=(),
            compat_seam=compat,
            removal_condition=removal,
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
) -> "tuple[str, list[str]]":
    reasons: "list[str]" = []
    if contradictions:
        reasons.append(f"원장 간 미해결 contradiction {len(contradictions)}건")
        return "BLOCKED", reasons
    unknown = [u.unit_id for u in units if u.target == "P_REVIEW_REQUIRED"]
    oracle_gap = [u.unit_id for u in units if u.oracle_status == "NONE"]
    if unknown:
        reasons.append(f"소유 불명 unit {len(unknown)}건(P_REVIEW_REQUIRED)")
    if oracle_gap:
        reasons.append(f"oracle 공백 unit {len(oracle_gap)}건")
    if sccs:
        reasons.append(f"거대 원자 cluster(SCC) {sccs}건")
    if unknown or oracle_gap or sccs:
        return "BLOCKED", reasons
    seam_units = [u for u in units if u.predecessors]
    if seam_units:
        reasons.append(
            f"central seam 선행 뒤 병렬화 가능 — 묶인 unit {len(seam_units)}건"
        )
        return "ORDERED_WAVES_READY", reasons
    reasons.append("모든 unit 이 독립 write set·oracle 보유, central seam 외 선후 강제 없음")
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
    effect_by_module = _effect_classes_by_module(effect.effect_facts)
    state_by_module = _state_by_module(shards["02b"])
    tx_modules = _tx_modules(shards["02b"])
    seams = _shared_state_seams(shards["02b"])
    shared_modules = {m for _s, mods in seams for m in mods}
    transport_by_module = _transport_modules(shards["02d"])
    host_module = _host_method_module(shards["02d"])
    if host_module:
        transport_by_module.setdefault(host_module, set()).add("host_method")
    entries_by_module, module_oracle, oracle_gaps = _entries_by_module(shards["02e"])
    tested_modules = _tested_modules(shards["02e"])

    modules: "list[ModuleAuthority]" = []
    module_auth: "dict[str, ModuleAuthority]" = {}
    for module in sorted(inv_modules):
        symbols = inv_modules[module]
        effect_classes = effect_by_module.get(module, set())
        transport_kinds = transport_by_module.get(module, set())
        stateful_tx = module in tx_modules
        shared = module in shared_modules
        target, reason = _assign_authority(
            module, symbols, effect_classes, transport_kinds, stateful_tx, shared
        )
        ma = ModuleAuthority(
            module=module,
            target=target,
            prior=_package_prior(module),
            reason=reason,
            symbol_count=len(symbols),
            effect_classes=tuple(sorted(effect_classes)),
            transport=bool(transport_kinds),
            stateful_tx=stateful_tx,
            shared_state=shared,
            entries=tuple(sorted(entries_by_module.get(module, []))),
        )
        modules.append(ma)
        module_auth[module] = ma

    units = _build_units(
        module_auth,
        seams,
        state_by_module,
        entries_by_module,
        module_oracle,
        inv_modules,
        tested_modules,
    )

    sccs = int(shards["02a"].get("counts", {}).get("sccs", 0))
    dynamic_open = int(shards["02a"].get("counts", {}).get("dynamic_open", 0))
    verdict, reasons = _verdict(contradictions, units, sccs, dynamic_open)

    return SynthesisResult(
        baseline_sha=_current_sha(repo_root),
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
        parts.append(f"closure_digest = {_q(u.closure_digest)}\n")
        parts.append(f"oracle_status = {_q(u.oracle_status)}\n")
        parts.append(f"predecessors = [{', '.join(_q(p) for p in u.predecessors)}]\n")
        parts.append(f"shared_with = [{', '.join(_q(s) for s in u.shared_with)}]\n")
        parts.append(f"write_set_count = {len(u.write_set)}\n")
        parts.append(f"blocking = [{', '.join(_q(b) for b in u.blocking)}]\n")
        parts.append(f"compat_seam = {_q(u.compat_seam)}\n")
        parts.append(f"removal_condition = {_q(u.removal_condition)}\n")
        parts.append("oracle_entries = [\n")
        parts.extend(f"  {_q(e)},\n" for e in u.oracle_entries)
        parts.append("]\n")

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
        for section in ("anchor", "counts", "verdict"):
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
