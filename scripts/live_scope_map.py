"""부분 실창 범위 — 범위 지도(`live-scopes.toml`)와 프로브 그래프 스냅숏을 읽는 층.

선택·판정은 `live_scope_select.py`, pytest 연결과 CLI 는 `live_scope.py` 가 진다. 이 모듈은
두 원장을 읽어 형태를 확인하고, 프로브 선택의 `after` 닫힘을 러너(`runner.js` `plan`)와 같은
정의로 계산한다.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPE_MAP_PATH = ROOT / "tests" / "contracts" / "live-scopes.toml"
PROBE_GRAPH_PATH = ROOT / "tests" / "contracts" / "selftest-probe-graph.json"

FULL = "full"
AUTO = "auto"
#: 선택이 뜻을 갖는 모드 — 그래프의 다른 모드 프로브는 별도 콜드 부팅이 돌린다.
SELFTEST_MODE = "full"


class LiveScopeError(Exception):
    """범위 지도·선택·그래프의 계약 위반 — 조용히 전체나 0개로 접지 않는다."""


# ───────────────────────────── 범위 지도 ─────────────────────────────


@dataclass(frozen=True)
class Scope:
    name: str
    description: str
    probes: tuple[str, ...]
    tests: tuple[str, ...]
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ScopeMap:
    shared: tuple[str, ...]
    no_live: tuple[str, ...]
    full_only: Mapping[str, str]
    scopes: Mapping[str, Scope]


_SCOPE_FIELDS = {"description", "probes", "tests", "paths"}
_TOP_FIELDS = {"version", "shared", "no_live", "full_only", "scopes"}


def _strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise LiveScopeError(f"{where} 는 비어 있지 않은 문자열 목록이어야 한다: {value!r}")
    if len(set(value)) != len(value):
        raise LiveScopeError(f"{where} 에 중복이 있다: {value!r}")
    return tuple(value)


def _optional_strings(body: Mapping, key: str, where: str) -> tuple[str, ...]:
    return _strings(body[key], f"{where}.{key}") if body[key] else ()


def _load_full_only(raw: Mapping) -> dict[str, str]:
    full_only = raw.get("full_only", {})
    if not isinstance(full_only, dict) or any(
        not isinstance(v, str) or not v.strip() for v in full_only.values()
    ):
        raise LiveScopeError("full_only 는 `노드 id = \"이유\"` 표여야 한다")
    return dict(full_only)


def _load_scope(name: str, body: object) -> Scope:
    if name in (FULL, AUTO) or not name.isidentifier():
        raise LiveScopeError(f"범위 이름 {name!r} 는 식별자이고 full·auto 가 아니어야 한다")
    if not isinstance(body, dict) or set(body) != _SCOPE_FIELDS:
        raise LiveScopeError(f"범위 {name}: 필드는 정확히 {sorted(_SCOPE_FIELDS)}")
    probes = _optional_strings(body, "probes", name)
    tests = _optional_strings(body, "tests", name)
    if not probes and not tests:
        raise LiveScopeError(f"범위 {name} 가 아무 live 테스트도 고르지 않는다")
    if any("[" in node for node in tests):
        raise LiveScopeError(f"범위 {name}.tests 는 파라미터 꼬리 없이 적는다: {tests}")
    paths = _optional_strings(body, "paths", name)
    return Scope(name, str(body["description"]), probes, tests, paths)


def load_scope_map(path: Path = SCOPE_MAP_PATH) -> ScopeMap:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(raw) - _TOP_FIELDS
    if unknown or raw.get("version") != 1:
        raise LiveScopeError(f"{path.name}: 모르는 최상위 키 {sorted(unknown)} 또는 version != 1")
    scopes = {name: _load_scope(name, body) for name, body in raw.get("scopes", {}).items()}
    return ScopeMap(
        shared=_strings(raw["shared"], "shared"),
        no_live=_strings(raw["no_live"], "no_live"),
        full_only=_load_full_only(raw),
        scopes=scopes,
    )


# ───────────────────────────── 프로브 그래프 ─────────────────────────────


@dataclass(frozen=True)
class Probe:
    name: str
    cluster: str
    keys: tuple[str, ...]
    modes: tuple[str, ...]
    after: tuple[str, ...]


def _seeds(selection: Iterable[str], planned: Mapping[str, Probe], mode: str) -> list[str]:
    """선택(프로브 이름·묶음 id) → 씨앗 이름. 모르거나 두 뜻인 이름은 시끄럽게 거절한다."""
    clusters = {probe.cluster for probe in planned.values()}
    seeds: list[str] = []
    for name in selection:
        if name in planned and name in clusters:
            raise LiveScopeError(f"{name!r} 는 프로브 이름이자 묶음 id 다")
        if name in planned:
            seeds.append(name)
        elif name in clusters:
            seeds.extend(p.name for p in planned.values() if p.cluster == name)
        else:
            raise LiveScopeError(f"선택한 프로브/묶음 {name!r} 이(가) 모드 {mode} 에 없다")
    return seeds


def _after_closure(seeds: Iterable[str], planned: Mapping[str, Probe], mode: str) -> set[str]:
    closed: set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name in closed:
            continue
        if name not in planned:
            raise LiveScopeError(f"after 가 가리키는 {name!r} 이(가) 모드 {mode} 에 없다")
        closed.add(name)
        stack.extend(planned[name].after)
    return closed


@dataclass(frozen=True)
class ProbeGraph:
    """`selftest-probe-graph.json` — 프런트 레지스트리의 스냅숏(드리프트는 Node 테스트가 잡는다)."""

    probes: tuple[Probe, ...]

    @property
    def by_name(self) -> dict[str, Probe]:
        return {probe.name: probe for probe in self.probes}

    def mode_probes(self, mode: str = SELFTEST_MODE) -> tuple[Probe, ...]:
        return tuple(probe for probe in self.probes if mode in probe.modes)

    def closure(self, selection: Iterable[str], mode: str = SELFTEST_MODE) -> tuple[str, ...]:
        """선택 + 전이 `after` — 러너 `plan(mode, {probes})` 와 같은 정의.

        순서는 그래프 등록 순서다(집합 비교용).
        """
        planned = {probe.name: probe for probe in self.mode_probes(mode)}
        closed = _after_closure(_seeds(selection, planned, mode), planned, mode)
        return tuple(name for name in planned if name in closed)

    def keys_of(self, names: Iterable[str]) -> frozenset[str]:
        by_name = self.by_name
        return frozenset(key for name in names for key in by_name[name].keys)


def load_probe_graph(path: Path = PROBE_GRAPH_PATH) -> ProbeGraph:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise LiveScopeError(f"{path.name}: version 1 그래프가 아니다")
    probes = tuple(
        Probe(
            name=entry["name"],
            cluster=entry["cluster"],
            keys=tuple(entry["keys"]),
            modes=tuple(entry["modes"]),
            after=tuple(entry["after"]),
        )
        for entry in raw["probes"]
    )
    return ProbeGraph(probes)
