"""부분 실창 범위 계약 — `scripts/live_scope.py` · `tests/contracts/live-scopes.toml` (창 없음).

부분 실창은 로컬에서 국소 변경을 싸게 확인하는 길이고, 병합 판정은 언제나 CI 의 전체 live 다.
그 경계가 무너지는 길은 셋이다: (1) 어떤 live 테스트가 어느 범위에도 없어 부분 실행에서 영영
안 돌거나, (2) 선택 닫힘이 실제 러너와 달라 부분 결과를 잘못 읽거나, (3) CI 가 부분 옵션을
받아들이는 것. 여기서 셋을 양성·음성 대조로 세운다.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import live_scope as ls
import live_scope_select
from hwpxfiller.webapp import selftest_runner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def scope_map() -> ls.ScopeMap:
    return ls.load_scope_map()


@pytest.fixture(scope="module")
def graph() -> ls.ProbeGraph:
    return ls.load_probe_graph()


@pytest.fixture(scope="module")
def gate_keys() -> "dict[str, frozenset[str] | None]":
    return ls.selftest_test_keys(ls.SELFTEST_GATE_PATH.read_text(encoding="utf-8"))


def _is_live_mark(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "live"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
    )


def _module_is_live(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        and "live" in ast.unparse(node.value)
        for node in tree.body
    )


def _is_live_test(node: ast.AST, inherited: bool) -> bool:
    return (
        isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_")
        and (inherited or any(_is_live_mark(d) for d in node.decorator_list))
    )


def _live_tests() -> "dict[str, str]":
    """정적으로 찾은 live 테스트 기본 노드 id → 종류("class"|"function")."""
    found: dict[str, str] = {}
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_live = _module_is_live(tree)
        rel = path.relative_to(ROOT).as_posix()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                live = module_live or any(_is_live_mark(d) for d in node.decorator_list)
                for item in node.body:
                    if _is_live_test(item, live):
                        found[f"{rel}::{node.name}::{item.name}"] = "class"
            elif _is_live_test(node, module_live):
                found[f"{rel}::{node.name}"] = "function"
    return found


# ───────────────────────────── 전수: 고아 live 테스트 없음 ─────────────────────────────


def test_the_static_live_inventory_sees_both_live_modules() -> None:
    """양성 대조 — 정적 목록이 비면 아래 전수 검사가 공허하게 초록이 된다."""
    live = _live_tests()
    files = {node.split("::", 1)[0] for node in live}
    assert {"tests/test_web_selftest_gate.py", "tests/test_quickstart_101_live.py"} <= files
    assert any(kind == "class" for kind in live.values())
    assert sum(kind == "function" for kind in live.values()) >= 10


def test_every_live_function_belongs_to_a_scope_or_is_declared_full_only(scope_map) -> None:
    scoped = {node for scope in scope_map.scopes.values() for node in scope.tests}
    functions = {node for node, kind in _live_tests().items() if kind == "function"}

    orphans = sorted(functions - scoped - set(scope_map.full_only))
    assert not orphans, (
        "어느 범위에도, full_only 에도 없는 live 테스트 — 부분 실행에서 이유 없이 영영 안 돈다:\n"
        + "\n".join(orphans)
        + "\n→ tests/contracts/live-scopes.toml 의 범위 tests 또는 [full_only] 에 적으세요."
    )
    both = sorted(scoped & set(scope_map.full_only))
    assert not both, f"범위에도 있고 full_only 에도 있다: {both}"


def test_scope_and_full_only_entries_name_live_tests_that_exist(scope_map) -> None:
    functions = {node for node, kind in _live_tests().items() if kind == "function"}
    named = {node for scope in scope_map.scopes.values() for node in scope.tests}
    stale = sorted((named | set(scope_map.full_only)) - functions)
    assert not stale, f"지도가 없는(또는 live 가 아닌) 테스트를 가리킨다: {stale}"


def test_every_selftest_gate_test_has_statically_known_keys(gate_keys) -> None:
    """`TestWebSelftestGate` 의 모든 테스트가 읽는 키를 정적으로 말할 수 있어야 한다."""
    live_class = {
        node.rsplit("::", 1)[1]
        for node, kind in _live_tests().items()
        if kind == "class" and node.startswith(ls.SELFTEST_GATE_NODE)
    }
    assert live_class and set(gate_keys) == live_class
    unknown = sorted(name for name, keys in gate_keys.items() if keys is None)
    assert not unknown, (
        "증거 키를 정적으로 못 읽는 selftest 테스트 — 부분 실행이 고를 수 없다:\n"
        + "\n".join(unknown)
        + "\n→ selftest_result[\"키\"] · probe(selftest_result, \"키\") 형태로 읽으세요."
    )


def test_every_selftest_key_is_produced_by_a_full_mode_probe(gate_keys, graph) -> None:
    produced = graph.keys_of(p.name for p in graph.mode_probes())
    missing = {
        name: sorted(keys - ls.RUN_WIDE_KEYS - produced)
        for name, keys in gate_keys.items()
        if keys is not None and keys - ls.RUN_WIDE_KEYS - produced
    }
    assert not missing, f"어느 full 모드 프로브도 내지 않는 키를 읽는다: {missing}"


def test_every_selftest_gate_test_is_kept_by_some_scope(scope_map, graph, gate_keys) -> None:
    orphans = []
    for name in gate_keys:
        node = f"{ls.SELFTEST_GATE_NODE}::{ls.SELFTEST_GATE_CLASS}::{name}"
        if not any(
            ls.keep_live_item(node, ls.resolve(scope, scope_map=scope_map, graph=graph, environ={}),
                              gate_keys)
            for scope in scope_map.scopes
        ):
            orphans.append(name)
    assert not orphans, f"어느 범위로도 고를 수 없는 selftest 테스트: {orphans}"


def test_every_scope_resolves_against_the_probe_graph(scope_map, graph) -> None:
    for name, scope in scope_map.scopes.items():
        if scope.probes:
            closure = graph.closure(scope.probes)
            assert closure, name
            assert set(closure) <= {p.name for p in graph.mode_probes()}


def test_the_key_extractor_refuses_what_it_cannot_read() -> None:
    """음성 대조 — 동적 키·통째 넘기기는 ``None``(부분 실행에서 빠지고 계약이 붉어진다)."""
    source = '''
class TestWebSelftestGate:
    def test_literal(self, selftest_result):
        assert selftest_result["a"] and probe(selftest_result, "b")["x"]
        assert "error" not in selftest_result, selftest_result.get("error")
    def test_dynamic(self, selftest_result):
        key = "a"
        assert selftest_result[key]
    def test_handed_off(self, selftest_result):
        helper(selftest_result)
    def test_iterated(self, selftest_result):
        assert all(selftest_result)
'''
    keys = ls.selftest_test_keys(source)
    assert keys["test_literal"] == frozenset({"a", "b", "error"})
    assert keys["test_dynamic"] is None
    assert keys["test_handed_off"] is None
    assert keys["test_iterated"] is None
    assert ls.keep_selftest_test(frozenset({"error"}), frozenset()) is True
    assert ls.keep_selftest_test(frozenset({"a", "b"}), frozenset({"a"})) is False
    assert ls.keep_selftest_test(None, frozenset({"a"})) is False


# ───────────────────────────── 닫힘 ─────────────────────────────


def test_closure_pulls_in_after_dependencies_across_clusters(graph) -> None:
    closure = set(graph.closure(["data_picker"]))
    # D 안의 사슬과 묶음 간 간선(data_picker → milestone_h_wave1 → job_data_first) 둘 다.
    assert {"data_picker", "job_editmode", "milestone_h_wave1", "job_data_first"} <= closure
    assert "react_runtime" not in closure and "url" not in closure


def test_cluster_ids_expand_to_their_full_mode_probes_only(graph) -> None:
    closure = graph.closure(["E"])
    assert "theme_persist" in closure
    # geometry_only·쓰기 모드 프로브는 별도 콜드 부팅이 돈다 — full 선택에 끼지 않는다.
    assert "window_geometry" not in closure and "theme_write" not in closure


def test_unknown_probe_names_fail_loudly(graph) -> None:
    with pytest.raises(ls.LiveScopeError, match="no_such_probe"):
        graph.closure(["job_mirror", "no_such_probe"])
    with pytest.raises(ls.LiveScopeError):
        graph.closure(["window_geometry"])  # full 모드 밖


# ───────────────────────────── auto 선택기 ─────────────────────────────


def test_a_shared_file_forces_full(scope_map) -> None:
    decision = ls.decide(["frontend/src/screens/job_run.ts", "frontend/src/shell/app.ts"], scope_map)
    assert decision.kind == ls.FULL
    assert any(v.kind == "shared" for v in decision.verdicts)


def test_an_unmapped_file_forces_full(scope_map) -> None:
    decision = ls.decide(["frontend/src/screens/icons.ts"], scope_map)
    assert decision.kind == ls.FULL and decision.verdicts[0].kind == "unmapped"
    assert ls.decide(["src/hwpxfiller/domain/job.py"], scope_map).kind == ls.FULL


def test_a_local_file_selects_its_scope(scope_map) -> None:
    decision = ls.decide(["frontend/src/screens/job_read.ts", "docs/workflow.md"], scope_map)
    assert decision.kind == "partial" and decision.scopes == ("job",)
    both = ls.decide(["frontend/src/screens/library.ts", "frontend/css/authoring.css"], scope_map)
    assert set(both.scopes) == {"library", "authoring"}


def test_docs_and_non_live_tests_need_no_live(scope_map) -> None:
    decision = ls.decide(["docs/workflow.md", "tests/test_engine.py", "AGENTS.md"], scope_map)
    assert decision.kind == "none"
    # 하니스·selftest 게이트 자체는 tests/ 아래여도 공유다.
    assert ls.decide(["tests/test_web_selftest_gate.py"], scope_map).kind == ls.FULL
    assert ls.decide(["tests/contracts/live-scopes.toml"], scope_map).kind == ls.FULL


def test_no_changes_means_full(scope_map) -> None:
    assert ls.decide([], scope_map).kind == ls.FULL


def test_auto_resolves_to_a_partial_selection_with_reasons(scope_map, graph) -> None:
    selection = ls.resolve(
        ls.AUTO, scope_map=scope_map, graph=graph, environ={},
        changed=["frontend/src/screens/job_read.ts"],
    )
    assert selection.mode == "partial" and selection.scopes == ("job",)
    assert "job_mirror" in selection.closure
    assert any("job_read.ts" in line for line in ls.header_lines(selection))
    full = ls.resolve(
        ls.AUTO, scope_map=scope_map, graph=graph, environ={}, changed=["src/hwpxcore/lineseg.py"]
    )
    assert full.mode == ls.FULL and full.auto is not None


def test_auto_falls_back_to_full_when_git_cannot_answer(scope_map, graph, monkeypatch) -> None:
    def broken(*_args, **_kwargs):
        raise ls.LiveScopeError("git 없음")

    monkeypatch.setattr(live_scope_select, "changed_files", broken)
    selection = ls.resolve(ls.AUTO, scope_map=scope_map, graph=graph, environ={})
    assert selection.mode == ls.FULL and "git 없음" in selection.note


# ───────────────────────────── CI 거절·옵션 ─────────────────────────────


@pytest.mark.parametrize("env", [{"CI": "true"}, {"GITHUB_ACTIONS": "true"}, {"CI": "1"}])
@pytest.mark.parametrize("value", ["job", "auto", "settings,journey101"])
def test_ci_rejects_every_partial_request(scope_map, graph, env, value) -> None:
    with pytest.raises(ls.LiveScopeError, match="CI"):
        ls.resolve(value, scope_map=scope_map, graph=graph, environ=env)


def test_ci_still_runs_full(scope_map, graph) -> None:
    for value in (None, "full"):
        selection = ls.resolve(value, scope_map=scope_map, graph=graph, environ={"CI": "true"})
        assert selection.mode == ls.FULL


@pytest.mark.parametrize("value", ["nope", "job,", "job,job", "job,full", "auto,job"])
def test_malformed_or_unknown_scopes_are_refused(scope_map, graph, value) -> None:
    with pytest.raises(ls.LiveScopeError):
        ls.resolve(value, scope_map=scope_map, graph=graph, environ={})


def _pytest(args: "list[str]", **env_overrides: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in (*ls.CI_ENV, ls.PROBES_ENV)}
    env.update(env_overrides, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="backslashreplace", timeout=300,
    )


def test_the_plugin_refuses_partial_scope_under_ci() -> None:
    done = _pytest(["--collect-only", "-q", "--live-scope=job", "tests/test_live_scope.py"],
                   GITHUB_ACTIONS="true")
    assert done.returncode == 4, done.stdout + done.stderr  # pytest UsageError
    assert "CI" in done.stderr


def test_the_plugin_refuses_a_preset_probe_selection_env() -> None:
    done = _pytest(["--collect-only", "-q", "tests/test_live_scope.py"],
                   **{ls.PROBES_ENV: "job_mirror"})
    assert done.returncode == 4 and ls.PROBES_ENV in done.stderr, done.stderr


def test_the_plugin_deselects_out_of_scope_live_tests_and_says_so() -> None:
    done = _pytest(["--collect-only", "-q", "-m", "live", "--live-scope=journey101"])
    assert done.returncode == 0, done.stdout + done.stderr
    collected = [line for line in done.stdout.splitlines() if line.startswith("tests/")]
    assert collected and all(line.startswith("tests/test_quickstart_101_live.py") for line in collected)
    assert "부분 실창 범위" in done.stdout and "병합 판정이 아니다" in done.stdout
    assert "제외 tests/test_web_selftest_gate.py::TestWebSelftestGate::test_no_probe_error" in done.stdout


def test_without_the_option_nothing_is_deselected() -> None:
    done = _pytest(["--collect-only", "-q", "-m", "live"])
    assert done.returncode == 0, done.stderr
    collected = [line for line in done.stdout.splitlines() if line.startswith("tests/")]
    assert {ls.base_nodeid(line) for line in collected} == set(_live_tests())
    assert "부분 실창 범위" not in done.stdout


# ───────────────────────────── 픽스처·증거 대조 ─────────────────────────────


def test_selection_echo_is_checked_both_ways(scope_map, graph) -> None:
    full = ls.resolve(None, environ={})
    assert ls.selection_mismatch(full, {"job_on": True}) is None
    assert ls.selection_mismatch(full, {ls.SELECTION_KEY: {"partial": True}}) is not None

    part = ls.resolve("job", scope_map=scope_map, graph=graph, environ={})
    ok = {ls.SELECTION_KEY: {
        "requested": list(part.probes), "planned": list(part.closure), "partial": True,
    }}
    assert ls.selection_mismatch(part, ok) is None
    assert "러너 사유: 터짐" in ls.selection_mismatch(part, {"error": "터짐"})
    drifted = {ls.SELECTION_KEY: {**ok[ls.SELECTION_KEY], "planned": ["job_mirror"]}}
    assert "닫힘 불일치" in ls.selection_mismatch(part, drifted)


def test_boot_env_carries_or_strips_the_selection(scope_map, graph) -> None:
    base = {"A": "1", ls.PROBES_ENV: "stale"}
    assert ls.PROBES_ENV not in ls.selftest_boot_env(ls.resolve(None, environ={}), base)
    part = ls.resolve("job", scope_map=scope_map, graph=graph, environ={})
    assert ls.selftest_boot_env(part, base)[ls.PROBES_ENV] == "C,data_sheet"
    only_101 = ls.resolve("journey101", scope_map=scope_map, graph=graph, environ={})
    assert ls.PROBES_ENV not in ls.selftest_boot_env(only_101, base)


def test_harness_names_match_the_driver_and_the_runner() -> None:
    assert ls.PROBES_ENV == selftest_runner.SELFTEST_PROBES_ENV
    assert ls.SELECTION_KEY == selftest_runner.SELECTION_EVIDENCE_KEY
    runner_js = (ROOT / "frontend" / "src" / "selftest" / "runner.js").read_text(encoding="utf-8")
    assert f'SELECTION_EVIDENCE_KEY = "{ls.SELECTION_KEY}"' in runner_js


# ───────────────────────────── 드라이버(selftest_runner) ─────────────────────────────


def test_driver_parses_the_selection_env() -> None:
    parse = selftest_runner._selftest_probe_selection
    assert parse({}) is None
    assert parse({ls.PROBES_ENV: "C, data_sheet"}) == ("C", "data_sheet")
    for bad in ("", "C,,D", " , "):
        with pytest.raises(ValueError):
            parse({ls.PROBES_ENV: bad})


class _Ctx:
    def __init__(self) -> None:
        self.window = object()
        self.finished: "dict | None" = None

    def finish(self, evidence: dict) -> None:
        self.finished = evidence


class _Client:
    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence
        self.calls: list[dict] = []

    def drive(self, mode, **kwargs):
        self.calls.append({"mode": mode, **kwargs})
        return selftest_runner.selftest_api.SelftestOutcome(
            mode=mode, ok=True, code="ok", detail="", evidence=dict(self.evidence)
        )


def _drive(monkeypatch, env: dict, evidence: dict) -> "tuple[_Ctx, _Client]":
    for name in (ls.PROBES_ENV, "HWPX_SELFTEST_SET_THEME", "HWPX_SELFTEST_NO_CAPABILITY",
                 "HWPX_SELFTEST_GLOBAL_DELTA", "HWPX_SELFTEST_GEOMETRY_ONLY",
                 "HWPX_SELFTEST_SET_FONT_SCALE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    client = _Client(evidence)
    monkeypatch.setattr(
        selftest_runner.selftest_api.SelftestClient, "for_window",
        classmethod(lambda cls, window, **kwargs: client),
    )
    ctx = _Ctx()
    selftest_runner.drive(ctx)  # type: ignore[arg-type]
    return ctx, client


def test_driver_forwards_the_selection_and_checks_its_echo(monkeypatch) -> None:
    echoed = {"job_mirror": {}, ls.SELECTION_KEY: {
        "requested": ["job_mirror"], "planned": ["job_data_first", "job_mirror"], "partial": True,
    }}
    ctx, client = _drive(monkeypatch, {ls.PROBES_ENV: "job_mirror"}, echoed)
    assert client.calls[0]["probes"] == ("job_mirror",)
    assert ctx.finished is not None and "error" not in ctx.finished

    ctx, _ = _drive(monkeypatch, {ls.PROBES_ENV: "job_mirror"}, {"job_mirror": {}})
    assert ctx.finished is not None and ls.SELECTION_KEY in ctx.finished["error"]

    ctx, client = _drive(monkeypatch, {}, {"job_on": True})
    assert client.calls[0]["probes"] is None and "error" not in (ctx.finished or {})
    ctx, _ = _drive(monkeypatch, {}, {"job_on": True, ls.SELECTION_KEY: {"partial": True}})
    assert "선택 요청 없이" in (ctx.finished or {}).get("error", "")


def test_driver_refuses_a_selection_outside_full_mode(monkeypatch) -> None:
    ctx, client = _drive(
        monkeypatch, {ls.PROBES_ENV: "job_mirror", "HWPX_SELFTEST_SET_THEME": "dark"}, {}
    )
    assert not client.calls
    assert ctx.finished is not None and "full 모드 전용" in ctx.finished["error"]
