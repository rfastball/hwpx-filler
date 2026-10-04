"""부분 실창 범위 — 국소 변경에 필요한 live 테스트만 고르는 **로컬 전용** 하니스(pytest·CLI).

전체 live(`pytest -m live`)는 selftest 부팅 하나에 콜드 부팅 십여 회와 101 실주행까지 태운다.
병합 판정은 CI `live-webview2` 가 언제나 그 전체로 지고, 이 하니스는 그 판정을 **대신하지 않는다**.
로컬에서 명백히 국소적인 변경을 고칠 때만 `--live-scope` 로 범위를 좁힌다. 범위 밖 live 테스트는
**deselect** 된다(skip 이 아니다 — 통과로 세지 않는다).

층은 넷이다 — 원장 읽기(`live_scope_map.py`), selftest 테스트의 키 찾기(`live_scope_keys.py`),
선택 해소·판정(`live_scope_select.py`), 그리고 이 파일(pytest 플러그인·픽스처 연결·CLI).
같은 판정을 손으로 보려면: ``uv run python scripts/live_scope.py auto`` (또는 범위 이름).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from live_scope_keys import (
    RUN_WIDE_KEYS,
    SELFTEST_GATE_CLASS,
    SELFTEST_GATE_NODE,
    SELFTEST_GATE_PATH,
    keep_selftest_test,
    selftest_test_keys,
)
from live_scope_map import (
    AUTO,
    FULL,
    LiveScopeError,
    ProbeGraph,
    ScopeMap,
    load_probe_graph,
    load_scope_map,
)
from live_scope_select import (
    CI_ENV,
    FULL_SELECTION,
    OPTION,
    PROBES_ENV,
    SELECTION_KEY,
    Selection,
    base_nodeid,
    changed_files,
    decide,
    header_lines,
    keep_live_item,
    resolve,
    selection_mismatch,
    selftest_boot_env,
    summary_lines,
)

__all__ = [
    "AUTO", "CI_ENV", "FULL", "OPTION", "PROBES_ENV", "RUN_WIDE_KEYS", "SELECTION_KEY",
    "SELFTEST_GATE_CLASS", "SELFTEST_GATE_NODE", "SELFTEST_GATE_PATH", "LiveScopeError",
    "ProbeGraph", "ScopeMap", "Selection", "base_nodeid", "changed_files", "checked_evidence",
    "decide", "header_lines", "keep_live_item", "keep_selftest_test", "live_selection",
    "load_probe_graph", "load_scope_map", "resolve", "selection_mismatch", "selftest_boot",
    "selftest_boot_env", "selftest_test_keys", "summary_lines",
]


# ───────────────────────────── pytest 플러그인 ─────────────────────────────
# 루트 `conftest.py` 가 ``pytest_plugins = ["live_scope"]`` 로 싣는다. 옵션이 없으면 아무것도
# 바꾸지 않는다(전체 = 지금 그대로).


@dataclass
class ItemPlan:
    kept: list = field(default_factory=list)
    deselected: list = field(default_factory=list)


_SELECTION = pytest.StashKey[Selection]()
_OUTCOME = pytest.StashKey[ItemPlan]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        OPTION,
        dest="live_scope",
        default=None,
        metavar="full|auto|이름[,이름]",
        help=(
            "로컬 전용 부분 실창: tests/contracts/live-scopes.toml 의 범위만 live 를 돌린다"
            " (기본 full, CI 에서는 거절)."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    if PROBES_ENV in os.environ:
        raise pytest.UsageError(
            f"{PROBES_ENV} 는 하니스가 소유한다 — 환경에 미리 두면 전체 selftest 가 조용히"
            f" 부분으로 바뀐다. 지우고 {OPTION} 로 고르세요."
        )
    try:
        selection = resolve(config.getoption("live_scope"))
    except LiveScopeError as exc:
        raise pytest.UsageError(str(exc)) from None
    config.stash[_SELECTION] = selection


def live_selection(config: pytest.Config) -> Selection:
    """이 실행의 해소 결과 — 플러그인이 안 실린 실행(직접 import 등)은 전체다."""
    return config.stash.get(_SELECTION, FULL_SELECTION)


def pytest_report_header(config: pytest.Config) -> "list[str]":
    return header_lines(live_selection(config))


def pytest_collection_modifyitems(config: pytest.Config, items: "list[pytest.Item]") -> None:
    selection = live_selection(config)
    if selection.mode == FULL:
        return
    keys = selftest_test_keys(SELFTEST_GATE_PATH.read_text(encoding="utf-8"))
    plan = ItemPlan()
    remaining: "list[pytest.Item]" = []
    for item in items:
        if item.get_closest_marker("live") is None:
            remaining.append(item)
        elif keep_live_item(item.nodeid, selection, keys):
            remaining.append(item)
            plan.kept.append(item.nodeid)
        else:
            plan.deselected.append(item)
    if plan.deselected:
        config.hook.pytest_deselected(items=plan.deselected)
        items[:] = remaining
    config.stash[_OUTCOME] = plan


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    selection = live_selection(config)
    if selection.requested == FULL:
        return  # 옵션 없음·full — 지금과 같은 실행, 덧붙일 말이 없다
    terminalreporter.section("부분 실창 범위(로컬 전용)", sep="=", yellow=True, bold=True)
    lines = header_lines(selection) if selection.auto is not None else []
    if selection.mode == FULL:
        lines.append("auto 가 전체를 골랐다 — live 테스트를 하나도 빼지 않았다.")
    else:
        plan = config.stash.get(_OUTCOME, ItemPlan())
        deselected = [item.nodeid for item in plan.deselected]
        lines.extend(summary_lines(selection, plan.kept, deselected))
    for line in lines:
        terminalreporter.write_line(line)


# ───────────────────────────── selftest 픽스처 연결 ─────────────────────────────


def selftest_boot(config: pytest.Config, base_env: Mapping[str, str]) -> dict:
    """selftest 부팅 인자(``env``·``what``) — 부분이면 선택을 싣고, 전체면 그 변수를 지운다."""
    selection = live_selection(config)
    what = (
        f"부분 모드 모듈 픽스처({', '.join(selection.probes)})"
        if selection.mode == "partial"
        else "full 모드 모듈 픽스처"
    )
    return {"env": selftest_boot_env(selection, base_env), "what": what}


def checked_evidence(config: pytest.Config, out: Path) -> dict:
    """증거를 읽고 선택 표식이 이 실행의 해소와 맞는지 단언한다 — 부분이 전체로 읽히지 않게."""
    evidence = json.loads(out.read_text(encoding="utf-8"))
    mismatch = selection_mismatch(live_selection(config), evidence)
    assert mismatch is None, mismatch
    return evidence


# ───────────────────────────── CLI ─────────────────────────────


def _utf8_console() -> None:
    """콘솔 코드페이지와 무관하게 한글·기호를 그대로 낸다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _print_selection(selection: Selection) -> None:
    for line in header_lines(selection) or ["live 범위: 전체(full)"]:
        print(line)
    if selection.mode != "partial":
        return
    if selection.closure:
        print(f"  selftest 닫힘: {', '.join(selection.closure)}")
    for node in sorted(selection.tests):
        print(f"  live 테스트: {node}")


def main(argv: "Sequence[str] | None" = None) -> int:
    _utf8_console()
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        selection = resolve(args[0] if args else AUTO)
    except LiveScopeError as exc:
        print(f"live 범위 오류: {exc}", file=sys.stderr)
        return 2
    _print_selection(selection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
