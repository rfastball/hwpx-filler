"""복잡도 예산 — 거대 모듈·클래스·함수가 새로 생기지 못하게 하는 상한과 동결 원장.

상한은 목표 품질 값이고(`scripts/complexity_measure.py` 의 `CEILINGS`), 오늘 넘는 단위만
`tests/contracts/complexity-budget.toml` 에 동결돼 내려가기만 한다. 판정 규칙과 측정기는
`scripts/complexity_budget.py`·`scripts/complexity_measure.py` 가 단일 출처이고, 이 파일은 그
판정을 저장소 실측에 걸고(1~4) 판정기 자체가 무는지를 음성 대조로 확인한다(5).

실패를 고치는 길은 원장 상향이 아니라 책임 분리다 — 메시지가 쪼갤 자리를 함께 말한다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import complexity_budget as budget
import complexity_measure as measure
import pytest

ROOT = Path(__file__).resolve().parents[2]

#: 발견 파일 수 하한 — 0개를 재고 통과하는 길을 막는다(도입 시 실측 Python 495 · JS 129).
PYTHON_FILE_FLOOR = 400
JS_FILE_FLOOR = 100


@pytest.fixture(scope="module")
def survey() -> tuple[dict[str, measure.Unit], dict[str, list[str]]]:
    return measure.measure_repository(ROOT)


@pytest.fixture(scope="module")
def found(survey) -> dict[budget.Key, budget.Reading]:
    return budget.readings(survey[0])


@pytest.fixture(scope="module")
def ledger() -> dict[budget.Key, budget.Entry]:
    return budget.read_ledger(ROOT)


def _fail(messages: list[str]) -> None:
    if messages:
        pytest.fail(f"{len(messages)}건\n" + "\n".join(messages), pytrace=False)


# ───────────────────────── 1~4. 저장소 실측 ─────────────────────────


def test_no_unit_exceeds_its_ceiling_or_frozen_value(found, ledger) -> None:
    _fail(budget.exceedances(found, ledger))


def test_the_ledger_is_closed_against_the_merge_base(found, ledger) -> None:
    _fail(budget.closed_violations(ledger, budget.base_ledger(ROOT), found))


def test_the_ratchet_does_not_lag_behind_measurements(found, ledger) -> None:
    _fail(budget.lagging_entries(found, ledger))


def test_no_ledger_entry_is_stale(found, ledger) -> None:
    _fail(budget.stale_entries(found, ledger))


# ───────────────────────── 5. 측정기 자기 검증 ─────────────────────────


def test_discovery_has_a_floor_and_covers_both_tiers(survey) -> None:
    units, files = survey
    assert len(files["python"]) >= PYTHON_FILE_FLOOR, files["python"][:5]
    assert len(files["js"]) >= JS_FILE_FLOOR, files["js"][:5]
    for language, suffixes in (("python", (".py",)), ("js", measure.JS_SUFFIXES)):
        tiers = {measure.tier_of(rel) for rel in files[language] if rel.endswith(suffixes)}
        assert tiers == {"production", "test"}, (language, tiers)
    assert {unit.kind for unit in units.values()} == {"module", "class", "function"}


def test_exclusions_are_explicit_and_still_point_somewhere(survey) -> None:
    _, files = survey
    every = files["python"] + files["js"]
    for prefix, reason in measure.EXCLUDED.items():
        assert reason.strip(), prefix
        assert (ROOT / prefix).is_dir(), f"제외 {prefix} 가 가리키는 곳이 없습니다 — 제외를 지우세요"
        assert not any(rel.startswith(prefix) for rel in every), prefix


def test_selftest_probes_and_tests_are_test_tier_and_scripts_are_production() -> None:
    assert measure.tier_of("frontend/src/selftest/probes/index.js") == "test"
    assert measure.tier_of("tests/test_engine.py") == "test"
    assert measure.tier_of("conftest.py") == "test"
    assert measure.tier_of("frontend/src/screens/workbench.ts") == "production"
    assert measure.tier_of("scripts/docs_contract.py") == "production"
    assert measure.tier_of("src/hwpxfiller/webapp/screen_job.py") == "production"


def _overflow_python() -> str:
    methods = "\n".join(
        f"    def {prefix}_{index}(self):\n        return {index}"
        for prefix, count in (("run", 14), ("preset", 7)) for index in range(count)
    )
    branches = "\n".join(f"    if x == {index}:\n        y = {index}" for index in range(10))
    filler = "\n".join(f"    z{index} = {index}" for index in range(30))
    padding = "\n".join(f"v{index} = {index}" for index in range(240))
    return (f'"""모듈 독스트링."""\n\nclass Fat:\n{methods}\n\n\n'
            f"def tangled(x):\n    y = 0\n{branches}\n{filler}\n    return y\n\n{padding}\n")


def _python_units(source: str, path: str = "src/fake.py") -> dict[str, measure.Unit]:
    return measure.merge_units(measure.measure_python_source(path, source))


def test_a_synthetic_overflow_is_caught_with_a_prescription() -> None:
    found = budget.readings(_python_units(_overflow_python()))
    messages = "\n".join(budget.exceedances(found, {}))

    assert "src/fake.py::Fat — class_methods 21 > 상한 20(production 등급)" in messages
    assert "run_*(14) preset_*(7)" in messages
    assert "src/fake.py::tangled — function_complexity 11 > 상한 10" in messages
    assert "src/fake.py::tangled — function_statements 52 > 상한 50" in messages
    assert "가장 큰 몸체 블록: L" in messages
    assert "src/fake.py — module_statements" in messages and "Fat(43)" in messages
    assert messages.count(budget.REMEDY) == 4
    # 같은 소스가 test 등급이면 느슨한 상한 아래다.
    assert budget.exceedances(budget.readings(_python_units(_overflow_python(), "tests/f.py")), {}) == []


_PLAIN = '''\
"""모듈 독스트링 — 길게 써도 벌하지 않는다.

한국어 설명이 여러 줄 이어진다.
"""


class Box:
    """클래스 독스트링."""

    def pick(self, items, flag):
        """메서드 독스트링."""
        out = []
        for item in items:
            if item and flag or not item:
                out.append(item)
        return [x for x in out if x]
'''

_JOINED = (
    "class Box:\n"
    "    def pick(self, items, flag):\n"
    "        out = []\n"
    "        for item in items:\n"
    "            if item and flag or not item: out.append(item)\n"
    "        return [x for x in out if x]\n"
)


def _metrics(units: dict[str, measure.Unit]) -> dict[str, dict[str, int]]:
    return {ident: unit.metrics for ident, unit in units.items()}


def test_line_joining_and_docstrings_do_not_change_python_measurements() -> None:
    plain = _metrics(_python_units(_PLAIN))
    assert plain == _metrics(_python_units(_JOINED))
    assert plain["src/fake.py::Box.pick"] == {"function_complexity": 7, "function_statements": 5}

    one_line = "x = 1; y = 2; z = 3\n"
    assert _metrics(_python_units(one_line)) == _metrics(_python_units("x = 1\ny = 2\nz = 3\n"))


@pytest.mark.parametrize("rel", [
    "scripts/complexity_budget.py",
    "src/hwpxfiller/webapp/screen_job.py",
    "tests/repo_contract/test_quality_workflow.py",
])
def test_reformatting_a_real_file_keeps_its_measurements(rel: str) -> None:
    source = (ROOT / rel).read_text(encoding="utf-8")
    reformatted = ast.unparse(ast.parse(source))  # 주석 제거·줄 재배치
    assert _metrics(_python_units(source, rel)) == _metrics(_python_units(reformatted, rel))


_JS_PLAIN = '''\
"use strict";
/** JSDoc 은 세지 않는다.
 *  여러 줄이어도. */
export class Panel {
  open() { return 1; }
  close = () => { this.x = 0; };
}

export function route(a, b) {
  if (a && b) {
    return a ?? b;
  }
  for (const item of a) {
    item.go();
  }
  test("이름 있는 콜백", () => { if (a) b(); });
  return a ? 1 : 2;
}
'''


def _js_metrics(tmp_path: Path, sources: dict[str, str]) -> dict[str, dict[str, int]]:
    for rel, text in sources.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return _metrics(measure.merge_units(measure.measure_js_files(tmp_path, sorted(sources))))


def test_js_measurements_follow_syntax_not_lines(tmp_path: Path) -> None:
    joined = " ".join(
        line for line in _JS_PLAIN.splitlines()
        if not line.lstrip().startswith(("/**", "*", '"use strict"'))
    )
    plain = _js_metrics(tmp_path, {"src/a.js": _JS_PLAIN})
    assert plain == _js_metrics(tmp_path, {"src/a.js": joined})
    assert plain["src/a.js::Panel"] == {"class_methods": 2}
    assert plain["src/a.js::route"] == {"function_complexity": 6, "function_statements": 6}
    assert plain['src/a.js::route.test("이름 있는 콜백")'] == {
        "function_complexity": 2, "function_statements": 2,
    }
    assert plain["src/a.js"] == {"module_statements": 12}


def test_a_synthetic_js_overflow_is_caught(tmp_path: Path) -> None:
    methods = "\n".join(f"  handleItem{index}() {{ return {index}; }}" for index in range(21))
    branches = "\n".join(f"  if (x === {index}) y = {index};" for index in range(10))
    source = (f"class Fat {{\n{methods}\n}}\n"
              f"const tangled = (x) => {{\n  let y = 0;\n{branches}\n  return y;\n}};\n")
    for rel in ("src/fat.ts", "src/fat.tsx"):
        units = measure.merge_units(_js_units(tmp_path, rel, source))
        messages = "\n".join(budget.exceedances(budget.readings(units), {}))
        assert f"{rel}::Fat — class_methods 21 > 상한 20" in messages
        assert "handle*(21)" in messages
        assert f"{rel}::tangled — function_complexity 11 > 상한 10" in messages


def _js_units(tmp_path: Path, rel: str, source: str) -> list[measure.Unit]:
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")
    return measure.measure_js_files(tmp_path, [rel])


def test_missing_node_or_unparsable_js_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(measure.MeasureError, match="스킵 사유가 아닙니다"):
        measure.measure_js_files(tmp_path, ["a.js"], node=str(tmp_path / "no-node.exe"))
    with pytest.raises(measure.MeasureError, match="파싱 실패"):
        _js_units(tmp_path, "src/broken.ts", "function (\n")
    with pytest.raises(measure.MeasureError, match="파싱 실패"):
        measure.measure_python_source("src/broken.py", "def (:\n")


# ───────────────────────── 5. 판정기 자기 검증 ─────────────────────────


def _reading(value: int, metric: str = "class_methods", path: str = "src/x.py") -> budget.Reading:
    unit = measure.Unit(path, "Big", "class", {metric: value}, ["run_a"] * value)
    return budget.Reading(unit, metric, value)


KEY = ("src/x.py::Big", "class_methods")


def test_the_closed_ledger_refuses_raises_and_new_entries_without_a_fresh_override() -> None:
    found = {KEY: _reading(30)}
    base = {KEY: budget.Entry(30)}
    raised = {KEY: budget.Entry(31)}
    assert "30 → 31 상향" in budget.closed_violations(raised, base, found)[0]
    assert "새 항목" in budget.closed_violations(raised, {}, found)[0]
    approved = {KEY: budget.Entry(31, "#1234", "협력 객체 분리 전 단계")}
    assert budget.closed_violations(approved, base, found) == []
    assert budget.closed_violations(approved, {}, found) == []
    # 기준에 이미 있던 override 는 다음 상향을 열지 않는다.
    stale_override = {KEY: budget.Entry(31, "#1234", "같은 이슈 재사용")}
    assert budget.closed_violations(stale_override, {KEY: budget.Entry(30, "#1234", "x")}, found)
    # reason 없는 override·이슈 번호가 아닌 override 는 탈출구가 아니다.
    assert budget.closed_violations({KEY: budget.Entry(31, "#1234")}, base, found)
    assert budget.closed_violations({KEY: budget.Entry(31, "TODO", "x")}, base, found)
    assert budget.closed_violations({KEY: budget.Entry(29)}, base, found) == []


def test_the_bootstrap_ledger_must_equal_measurements() -> None:
    found = {KEY: _reading(30)}
    assert budget.closed_violations({KEY: budget.Entry(30)}, None, found) == []
    assert budget.closed_violations({KEY: budget.Entry(31)}, None, found)


def test_lagging_and_stale_entries_are_reported_and_tighten_only_lowers() -> None:
    ledger = {KEY: budget.Entry(40)}
    assert "--tighten" in budget.lagging_entries({KEY: _reading(35)}, ledger)[0]
    assert budget.lagging_entries({KEY: _reading(36)}, ledger) == []
    assert "상한 안으로" in budget.stale_entries({KEY: _reading(20)}, ledger)[0]
    assert "사라졌습니다" in budget.stale_entries({}, ledger)[0]
    assert "동결값 40" in budget.exceedances({KEY: _reading(41)}, ledger)[0]

    assert budget.tightened(ledger, {KEY: _reading(35)}) == {KEY: budget.Entry(35)}
    assert budget.tightened(ledger, {KEY: _reading(45)}) == {KEY: budget.Entry(40)}
    assert budget.tightened(ledger, {KEY: _reading(20)}) == {}
    assert budget.tightened(ledger, {}) == {}


def test_the_ledger_round_trips_through_the_writer() -> None:
    entries = {
        KEY: budget.Entry(31, "#1234", '따옴표 " 와 한글'),
        ("src/x.py", "module_statements"): budget.Entry(400),
    }
    assert budget.parse_ledger(budget.dump_ledger(entries)) == entries
    with pytest.raises(budget.LedgerError, match="모르는 축"):
        budget.parse_ledger(f'schema = "{budget.SCHEMA}"\n[budget."a.py"]\nlines = 3\n')
