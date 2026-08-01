"""suite 수집 분리 계약 — 어느 잡이 무엇을 도는가(N-11B · #424).

CI 는 이제 자원 축(marker)으로 잡을 가른다. 그 순간 marker 는 라벨이 아니라 **선택자**가 된다
— 축을 잘못 달거나 빠뜨리면 테스트가 사라지거나 두 번 돈다. 둘 다 조용하다:

- 게이트 테스트에 축을 안 달면 결정론적 `pytest-contract` 잡으로 흘러든다. 그 잡의 러너에는
  실 WebView2 도 설치 Chrome 도 없으니 옵트아웃이 켜져 있으면 **조용히 스킵**되고, 켜져 있지
  않으면 엉뚱한 잡에서 실 자원을 잡으려다 죽는다.
- 순수 검사에 축을 달면 그 검사는 경계 잡에서만 돈다. 게이트 밖 층을 따로 세운 이유
  (`test_quickstart_101_live` docstring L14-15)가 바로 그 층이 **옵트아웃 러너에서도** 돌아야
  한다는 것이었다 — 축을 넓게 칠하면 그 이유가 지워진다.
- 종전 `native` 이중 실행(전용 단계 + 무필터 전체 pytest)처럼 같은 책임이 한 run 에서 두 번
  돌면 시간만 먹고 판정은 하나도 늘지 않는다.

그래서 이 파일은 **수집 결과**를 본다. 선언(데코레이터가 붙었는가)이 아니라 pytest 가 실제로
고른 노드를 세는 것이 요점이다 — 클래스·모듈 단위로 얹힌 marker 도, 파라미터로 불어난 노드도
결과에서만 정확하다.

계약은 두 축이다.

1. **분할** — 축 marker 는 서로 겹치지 않고, 축 + 무표의 합이 전체 수집과 같다. CI 의 contract
   식(:data:`CONTRACT_EXPR`)이 그 무표 집합을 정확히 고른다.
2. **짝** — 옵트아웃 게이트(``skipif``)와 축 marker 는 **같은 노드에 함께** 있다. 게이트가
   말하는 자원과 축이 말하는 자원은 같은 것이어야 한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent

#: 자원 축 — marker 이름 ↔ 그 자원을 끄는 명시 옵트아웃 환경변수. 이 표가 단일 출처다:
#: `pyproject` 등록·게이트 `skipif`·CI 잡 선택이 전부 이 세 쌍을 가리킨다. 축을 늘리려면
#: 여기와 `pyproject` 와 워크플로를 **한 변경으로** 고친다 — 셋 중 하나만 늘면 아래가 멈춘다.
AXES: dict[str, str] = {
    "native": "HWPX_SKIP_NATIVE_TESTS",
    "browser": "HWPX_SKIP_MOTION_TESTS",
    "live": "HWPX_SKIP_GUI_TESTS",
}

#: 결정론적 contract suite 를 고르는 식. CI 의 `pytest-contract` 잡이 그대로 쓴다.
CONTRACT_EXPR = " and ".join(f"not {axis}" for axis in AXES)

# 수집은 로컬에서 0.7초다. 이 시한은 「느린 러너」가 아니라 **매달림**을 잡는 자리라
# 두 자릿수 배수로 둔다 — 시한이 촘촘하면 진단 대신 맨 TimeoutExpired 만 남는다.
_COLLECT_TIMEOUT_S = 300.0


# ─────────────────────────────── 수집 실측 ───────────────────────────────


def _run_pytest(args: "list[str]", timeout: float = _COLLECT_TIMEOUT_S):
    """자식 pytest 를 돌린다 — 부모 세션의 선택 상태에 오염되지 않게 별 프로세스로.

    ``tests/`` 를 ``PYTHONPATH`` 에 얹는 이유는 프로브 플러그인이 ``-p`` 로 **부팅 시점에**
    import 되기 때문이다(그때는 pytest 의 rootdir 삽입이 아직 없다).
    """
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(TESTS_DIR), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def rows(tmp_path_factory) -> "list[dict]":
    """전체 수집 한 번 — 노드마다 적용된 marker 와 게이트 사유."""
    out = tmp_path_factory.mktemp("suite_probe") / "collected.json"
    proc = _run_pytest(["-p", "_suite_probe", "--suite-probe-out", str(out)])

    assert proc.returncode == 0, (
        f"수집이 실패했습니다 — rc={proc.returncode}\n"
        f"stdout={proc.stdout[-3000:]}\nstderr={proc.stderr[-3000:]}"
    )
    assert out.exists(), (
        f"프로브가 아무것도 쓰지 않았습니다 — 플러그인이 안 실렸을 수 있습니다.\n"
        f"stdout={proc.stdout[-2000:]}"
    )
    collected = json.loads(out.read_text(encoding="utf-8"))
    assert collected, "수집이 0건이면 아래 계약이 아무것도 안 지킵니다"
    return collected


# ───────────────────────────── 순수 판정부 ─────────────────────────────


def _axes_of(row: dict) -> "set[str]":
    return {axis for axis in AXES if axis in row["markers"]}


def _gates_of(row: dict) -> "set[str]":
    """그 노드가 **자원 부재로** 꺼질 수 있는 축. 사유가 옵트아웃 변수를 이름으로 댄다.

    플랫폼 skipif(`sys.platform`)처럼 옵트아웃 변수를 대지 않는 게이트는 여기 안 걸린다 —
    자원 축이 아니라 실행 가능성의 문제라 잡을 가르는 근거가 못 된다.
    """
    reasons = " ".join(row["skip_reasons"])
    return {axis for axis, env in AXES.items() if env in reasons}


def _partition_problems(rows: "list[dict]") -> "list[str]":
    """축이 겹친 노드를 모은다 — 겹치면 두 잡이 같은 노드를 돌거나 식이 서로 물린다."""
    return [
        f"{row['nodeid']} 가 축 {sorted(_axes_of(row))} 을 겹쳐 답니다"
        for row in rows
        if len(_axes_of(row)) > 1
    ]


def _pairing_problems(rows: "list[dict]") -> "list[str]":
    """게이트와 축이 어긋난 노드를 모은다 — 양방향 모두 결함이다."""
    problems: "list[str]" = []
    for row in rows:
        axes, gates = _axes_of(row), _gates_of(row)
        for axis in sorted(gates - axes):
            problems.append(
                f"{row['nodeid']} 는 {AXES[axis]} 게이트 뒤인데 `{axis}` 축이 없습니다 — "
                "contract 잡으로 흘러들어 조용히 스킵되거나 없는 자원을 잡습니다"
            )
        for axis in sorted(axes - gates):
            problems.append(
                f"{row['nodeid']} 는 `{axis}` 축을 달았는데 {AXES[axis]} 게이트가 없습니다 — "
                "자원 없이도 도는 검사를 경계 잡에 가두면 옵트아웃 러너에서 사라집니다"
            )
    return problems


def _row(nodeid: str, markers: "list[str]" = (), reasons: "list[str]" = ()) -> dict:
    return {"nodeid": nodeid, "markers": list(markers), "skip_reasons": list(reasons)}


# ─────────────────────────────── 등록 계약 ───────────────────────────────


def test_the_registered_markers_are_exactly_the_resource_axes() -> None:
    """`pyproject` 의 등록 marker 가 자원 축과 **정확히** 같고, 각자 옵트아웃 변수를 댄다.

    축을 하나 늘리고 CI 식을 안 고치면 그 축은 어느 잡에서도 안 돈다 — 전체 수집이 줄었다는
    사실을 아무도 보지 않기 때문에 조용하다. 등록 목록을 축의 정의와 못 박아 그 길을 막는다.
    """
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ini = config["tool"]["pytest"]["ini_options"]

    declared = {line.split(":", 1)[0].strip(): line for line in ini.get("markers", [])}
    assert set(declared) == set(AXES), (
        f"등록 marker {sorted(declared)} 와 자원 축 {sorted(AXES)} 이 다릅니다 — "
        "축을 늘렸으면 CONTRACT_EXPR 과 CI 잡도 같은 변경에 담습니다."
    )
    for axis, env in AXES.items():
        assert env in declared[axis], (
            f"`{axis}` 등록 설명이 옵트아웃 변수 {env} 를 대지 않습니다 — "
            "짝 계약이 사유 문자열로 축을 알아봅니다."
        )
    assert "--strict-markers" in ini.get("addopts", []), (
        "--strict-markers 가 없으면 오타난 mark 가 조용히 아무것도 선택하지 않습니다."
    )


# ─────────────────────────────── 분할 계약 ───────────────────────────────


def test_the_axes_do_not_overlap(rows) -> None:
    """한 노드는 축을 많아야 하나 단다."""
    assert not _partition_problems(rows), "\n".join(_partition_problems(rows))


def test_every_axis_actually_holds_something(rows) -> None:
    """양성 대조 — 빈 축이 있으면 아래 분할 단언은 「아무것도 안 나눴다」로도 초록이다."""
    empty = [axis for axis in AXES if not any(axis in _axes_of(row) for row in rows)]

    assert not empty, f"수집이 0건인 축: {empty} — 그 잡은 아무것도 증명하지 않습니다."


def test_the_contract_expression_selects_exactly_the_unmarked_rest(rows) -> None:
    """CI 가 쓰는 **그 식**이 무표 집합과 정확히 같은 것을 고른다.

    식을 손으로 쓰는 한 「축은 셋인데 식은 둘만 뺀다」가 언제든 가능하다. 그 상태에서도 CI 는
    초록이다 — 경계 테스트가 contract 잡에서 한 번 더 돌 뿐이라 실패가 안 난다. 그래서 식을
    문자열로 검사하지 않고 **돌려서** 고른 것을 센다.
    """
    expected = {row["nodeid"] for row in rows if not _axes_of(row)}
    boundary = {row["nodeid"] for row in rows if _axes_of(row)}

    proc = _run_pytest(["-m", CONTRACT_EXPR])
    assert proc.returncode == 0, f"수집 실패 — {proc.stdout[-2000:]}{proc.stderr[-2000:]}"
    selected = {line.strip() for line in proc.stdout.splitlines() if "::" in line}

    assert selected == expected, (
        f"contract 식이 고른 것과 무표 집합이 다릅니다 — "
        f"식에만 있는 것 {sorted(selected - expected)[:5]} · "
        f"무표에만 있는 것 {sorted(expected - selected)[:5]}"
    )
    assert selected.isdisjoint(boundary), "contract 잡이 경계 노드를 다시 태웁니다"
    assert len(selected) + len(boundary) == len(rows), (
        f"분할이 전체를 덮지 않습니다 — contract {len(selected)} + 경계 {len(boundary)} "
        f"≠ 전체 {len(rows)}"
    )


# ──────────────────────────────── 짝 계약 ────────────────────────────────


def test_every_opt_out_gate_carries_its_axis_marker(rows) -> None:
    """게이트와 축은 같은 노드에 함께 있다 — 어긋나면 그 노드는 잘못된 잡에 산다."""
    problems = _pairing_problems(rows)

    assert not problems, "\n".join(problems)


def test_a_healthy_pairing_passes_so_the_negative_controls_mean_something() -> None:
    """양성 대조 — 아래 음성들이 「언제나 실패」가 아님을 먼저 보인다."""
    healthy = [
        _row("tests/test_x.py::test_pure"),
        _row("tests/test_x.py::test_gated", ["live"], ["… HWPX_SKIP_GUI_TESTS=1 로 옵트아웃"]),
    ]

    assert _pairing_problems(healthy) == []
    assert _partition_problems(healthy) == []


@pytest.mark.parametrize(
    ("markers", "reasons", "fragment"),
    [
        ([], ["… HWPX_SKIP_GUI_TESTS=1 로 옵트아웃"], "축이 없습니다"),
        (["live"], [], "게이트가 없습니다"),
        (["native"], ["… HWPX_SKIP_GUI_TESTS=1 로 옵트아웃"], "축이 없습니다"),
    ],
)
def test_the_pairing_check_notices_each_way_it_can_drift(markers, reasons, fragment) -> None:
    """음성 대조 — 축 누락·과다·엇갈림을 실제로 잡는가.

    실제 테스트 파일의 marker 를 떼었다 붙이는 시험은 다음 사람의 작업트리를 위협하므로
    **행을 조작해** 잰다.
    """
    problems = _pairing_problems([_row("tests/test_x.py::test_one", markers, reasons)])

    assert problems, "어긋남을 만들었는데 짝 계약이 조용합니다"
    assert any(fragment in problem for problem in problems), problems


def test_the_partition_check_notices_overlapping_axes() -> None:
    """음성 대조 — 축이 겹친 노드를 잡는가(겹치면 두 잡이 같은 것을 돈다)."""
    problems = _partition_problems([_row("tests/test_x.py::test_one", ["live", "native"])])

    assert problems and "겹쳐" in problems[0], problems
