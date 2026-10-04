"""부분 실창 범위 — `--live-scope` 값을 선택으로 해소하고 live 항목·증거를 판정하는 층.

- ``full``(기본) — 아무것도 고르지 않는다.
- ``<이름[,이름]>`` — 범위 지도의 범위. selftest 부팅은 그 프로브와 `after` 닫힘만 돈다.
- ``auto`` — `origin/master` merge-base 대비 변경(작업 트리·미추적 포함)을 범위로 옮긴다.
  공유 파일이나 어디에도 안 걸리는 파일이 하나라도 있으면 전체다.

CI(``CI``·``GITHUB_ACTIONS``)에서 부분 요청은 :class:`LiveScopeError` 다.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from live_scope_keys import SELFTEST_GATE_CLASS, SELFTEST_GATE_NODE, keep_selftest_test
from live_scope_map import (
    AUTO,
    FULL,
    ROOT,
    LiveScopeError,
    ProbeGraph,
    ScopeMap,
    load_probe_graph,
    load_scope_map,
)

OPTION = "--live-scope"
#: 부분 실행을 거절하는 CI 표지 — 둘 중 하나라도 참이면 CI 다.
CI_ENV = ("CI", "GITHUB_ACTIONS")
#: 프런트 러너에 선택을 넘기는 환경변수 — `selftest_runner.SELFTEST_PROBES_ENV` 와 같다.
PROBES_ENV = "HWPX_SELFTEST_PROBES"
#: 선택 실행의 증거 표식 — `selftest_runner.SELECTION_EVIDENCE_KEY` 와 같다.
SELECTION_KEY = "selftest_selection"
DEFAULT_BASE = "origin/master"


# ───────────────────────────── 변경 → 범위 ─────────────────────────────


def _matches(path: str, globs: Iterable[str]) -> "str | None":
    pure = PurePosixPath(path)
    for pattern in globs:
        if pure.full_match(pattern):
            return pattern
    return None


@dataclass(frozen=True)
class FileVerdict:
    path: str
    kind: str  # "shared" | "scope" | "no_live" | "unmapped"
    scopes: tuple[str, ...] = ()
    rule: str = ""

    def describe(self) -> str:
        if self.kind == "shared":
            return f"전체 — 공유 `{self.rule}`"
        if self.kind == "scope":
            return f"범위 {', '.join(self.scopes)}"
        if self.kind == "no_live":
            return f"실창 불필요 — `{self.rule}`"
        return "전체 — 어느 범위에도 없다(애매하면 전체)"


def classify_path(path: str, scope_map: ScopeMap) -> FileVerdict:
    path = path.replace("\\", "/")
    if rule := _matches(path, scope_map.shared):
        return FileVerdict(path, "shared", rule=rule)
    hits = tuple(name for name, scope in scope_map.scopes.items() if _matches(path, scope.paths))
    if hits:
        return FileVerdict(path, "scope", scopes=hits)
    if rule := _matches(path, scope_map.no_live):
        return FileVerdict(path, "no_live", rule=rule)
    return FileVerdict(path, "unmapped")


@dataclass(frozen=True)
class AutoDecision:
    kind: str  # "full" | "partial" | "none"
    scopes: tuple[str, ...]
    verdicts: tuple[FileVerdict, ...]
    reason: str


def _forcing_count(verdicts: Sequence[FileVerdict]) -> int:
    return sum(1 for v in verdicts if v.kind in ("shared", "unmapped"))


def _hit_scopes(verdicts: Sequence[FileVerdict], scope_map: ScopeMap) -> tuple[str, ...]:
    """걸린 범위 — 지도의 선언 순서로."""
    hit = {name for v in verdicts for name in v.scopes}
    return tuple(name for name in scope_map.scopes if name in hit)


def decide(paths: Sequence[str], scope_map: ScopeMap) -> AutoDecision:
    """변경 목록 → 판정. 공유·미등록이 하나라도 있으면 전체, 변경이 없어도 전체다."""
    verdicts = tuple(classify_path(path, scope_map) for path in sorted(set(paths)))
    if not verdicts:
        return AutoDecision(FULL, (), verdicts, "변경 없음 — 고를 근거가 없어 전체")
    forcing = _forcing_count(verdicts)
    if forcing:
        return AutoDecision(FULL, (), verdicts, f"전체를 강제하는 파일 {forcing}개")
    scopes = _hit_scopes(verdicts, scope_map)
    if not scopes:
        return AutoDecision("none", (), verdicts, "모든 변경이 실창 불필요 목록이다")
    return AutoDecision("partial", scopes, verdicts, f"국소 변경 → 범위 {', '.join(scopes)}")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    if done.returncode != 0:
        raise LiveScopeError(f"git {' '.join(args)} 실패: {done.stderr.strip()}")
    return done.stdout


def changed_files(base: str = DEFAULT_BASE, root: Path = ROOT) -> list[str]:
    """merge-base 대비 변경(커밋·스테이지·작업 트리·삭제) + 미추적 파일."""
    merge_base = _git(root, "merge-base", "HEAD", base).strip()
    tracked = _git(root, "diff", "--name-only", "--no-renames", merge_base).splitlines()
    untracked = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({line.strip() for line in [*tracked, *untracked] if line.strip()})


# ───────────────────────────── 선택 해소 ─────────────────────────────


@dataclass(frozen=True)
class Selection:
    """`--live-scope` 의 해소 결과. ``mode`` 가 ``full`` 이면 아무것도 고르지 않는다."""

    requested: str
    mode: str  # "full" | "partial" | "none"
    scopes: tuple[str, ...] = ()
    probes: tuple[str, ...] = ()
    closure: tuple[str, ...] = ()
    produced: frozenset[str] = frozenset()
    tests: frozenset[str] = frozenset()
    auto: "AutoDecision | None" = None
    note: str = ""

    @property
    def partial(self) -> bool:
        return self.mode != FULL


FULL_SELECTION = Selection(requested=FULL, mode=FULL)


def ci_active(environ: Mapping[str, str] = os.environ) -> bool:
    return any(environ.get(name, "").strip().lower() not in ("", "0", "false") for name in CI_ENV)


def _scoped(
    requested: str,
    names: Sequence[str],
    scope_map: ScopeMap,
    graph: ProbeGraph,
    auto: "AutoDecision | None" = None,
) -> Selection:
    unknown = [name for name in names if name not in scope_map.scopes]
    if unknown:
        raise LiveScopeError(
            f"모르는 live 범위 {unknown} — 가능한 값: {FULL}, {AUTO}, "
            + ", ".join(scope_map.scopes)
        )
    probes: list[str] = []
    tests: set[str] = set()
    for name in names:
        scope = scope_map.scopes[name]
        probes.extend(p for p in scope.probes if p not in probes)
        tests.update(scope.tests)
    closure = graph.closure(probes) if probes else ()
    return Selection(
        requested=requested,
        mode="partial",
        scopes=tuple(names),
        probes=tuple(probes),
        closure=closure,
        produced=graph.keys_of(closure),
        tests=frozenset(tests),
        auto=auto,
    )


def _resolve_auto(
    scope_map: ScopeMap, graph: ProbeGraph, changed: "Sequence[str] | None"
) -> Selection:
    try:
        paths = list(changed) if changed is not None else changed_files()
    except LiveScopeError as exc:
        decision = AutoDecision(FULL, (), (), f"변경 목록을 못 얻어 전체: {exc}")
    else:
        decision = decide(paths, scope_map)
    if decision.kind == "partial":
        return _scoped(AUTO, decision.scopes, scope_map, graph, auto=decision)
    return Selection(requested=AUTO, mode=decision.kind, auto=decision, note=decision.reason)


def _scope_names(requested: str) -> list[str]:
    names = [part.strip() for part in requested.split(",")]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise LiveScopeError(f"{OPTION} 형태 위반: {requested!r}")
    if FULL in names or AUTO in names:
        raise LiveScopeError(f"{FULL}·{AUTO} 는 다른 범위와 섞지 않는다: {requested!r}")
    return names


def resolve(
    value: "str | None",
    *,
    scope_map: "ScopeMap | None" = None,
    graph: "ProbeGraph | None" = None,
    environ: Mapping[str, str] = os.environ,
    changed: "Sequence[str] | None" = None,
) -> Selection:
    """옵션 값 → :class:`Selection`. CI 에서 부분 요청은 :class:`LiveScopeError` 다."""
    requested = (value or FULL).strip()
    if requested == FULL:
        return FULL_SELECTION
    if ci_active(environ):
        raise LiveScopeError(
            f"{OPTION}={requested} 는 CI 에서 쓸 수 없다 — 병합 게이트는 전체 live 만 돈다"
        )
    scope_map = scope_map or load_scope_map()
    graph = graph or load_probe_graph()
    if requested == AUTO:
        return _resolve_auto(scope_map, graph, changed)
    return _scoped(requested, _scope_names(requested), scope_map, graph)


# ───────────────────────────── 항목 판정 ─────────────────────────────


def base_nodeid(nodeid: str) -> str:
    return nodeid.split("[", 1)[0]


def keep_live_item(
    nodeid: str,
    selection: Selection,
    selftest_keys: Mapping[str, "frozenset[str] | None"],
) -> bool:
    """부분 실행에서 live 항목 하나를 남기는가(``none`` 이면 언제나 아니다)."""
    if selection.mode != "partial":
        return selection.mode == FULL
    base = base_nodeid(nodeid)
    prefix = f"{SELFTEST_GATE_NODE}::{SELFTEST_GATE_CLASS}::"
    if base.startswith(prefix):
        if not selection.closure:
            return False
        return keep_selftest_test(selftest_keys.get(base[len(prefix):]), selection.produced)
    return base in selection.tests


# ───────────────────────────── selftest 증거 ─────────────────────────────


def selftest_boot_env(selection: Selection, base: Mapping[str, str]) -> dict[str, str]:
    """selftest 부팅 환경 — 부분이면 선택을 싣고, 전체면 그 변수를 **확실히 지운다**."""
    env = dict(base)
    env.pop(PROBES_ENV, None)
    if selection.mode == "partial" and selection.probes:
        env[PROBES_ENV] = ",".join(selection.probes)
    return env


def _partial_mismatch(selection: Selection, evidence: Mapping, echoed: object) -> "str | None":
    if not isinstance(echoed, Mapping):
        reason = evidence.get("error") or "(사유 없음)"
        return f"부분 실행 증거에 {SELECTION_KEY} 가 없다 — 러너 사유: {reason}"
    requested = list(echoed.get("requested") or [])
    if echoed.get("partial") is not True or requested != list(selection.probes):
        return f"선택 표식 불일치: 요청 {list(selection.probes)} / 증거 {dict(echoed)!r}"
    planned = sorted(echoed.get("planned") or [])
    if set(planned) != set(selection.closure):
        return (
            f"닫힘 불일치: 하니스 {sorted(selection.closure)} / 러너 {planned}"
            " — 그래프 스냅숏을 다시 생성하세요 (node scripts/selftest_probe_graph.mjs --write)"
        )
    return None


def selection_mismatch(selection: Selection, evidence: Mapping) -> "str | None":
    """증거의 선택 표식이 이 실행의 해소와 맞는가 — 부분이 전체로, 전체가 부분으로 읽히지 않게."""
    echoed = evidence.get(SELECTION_KEY)
    if selection.mode == "partial":
        return _partial_mismatch(selection, evidence, echoed)
    if echoed is not None:
        return f"전체 실행인데 증거에 선택 표식이 있다: {echoed!r}"
    return None


# ───────────────────────────── 보고 ─────────────────────────────


def header_lines(selection: Selection) -> list[str]:
    lines: list[str] = []
    if selection.auto is not None:
        lines.append(f"live 범위 auto({DEFAULT_BASE} merge-base 대비): {selection.auto.reason}")
        lines.extend(f"  {v.path} → {v.describe()}" for v in selection.auto.verdicts)
    if selection.mode == FULL:
        if selection.requested != FULL:
            lines.append("live 범위: 전체(full)")
        return lines
    if selection.mode == "none":
        lines.append("live 범위: 없음 — live 테스트를 전부 deselect 합니다(병합 판정 아님)")
        return lines
    lines.append(f"live 범위: 부분 — {', '.join(selection.scopes)} (병합 판정 아님)")
    if selection.probes:
        lines.append(f"  selftest 선택 {list(selection.probes)} → 닫힘 {len(selection.closure)}개")
    return lines


def summary_lines(selection: Selection, kept: Sequence[str], deselected: Sequence[str]) -> list[str]:
    lines = [
        f"요청: {OPTION}={selection.requested} → {selection.mode}"
        + (f" ({', '.join(selection.scopes)})" if selection.scopes else ""),
    ]
    if selection.probes:
        lines.append(f"selftest 선택: {', '.join(selection.probes)}")
        lines.append(f"selftest 닫힘({len(selection.closure)}): {', '.join(selection.closure)}")
    lines.append(f"남긴 live 테스트: {len(kept)}개 · 제외(deselect): {len(deselected)}개")
    lines.extend(f"  제외 {nodeid}" for nodeid in deselected)
    lines.append(
        "이 결과는 병합 판정이 아니다 — 전체 live 는 CI live-webview2(pytest -m live)가 진다."
    )
    return lines
