from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_package_coverage.py"
SPEC = importlib.util.spec_from_file_location("check_package_coverage", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def _write_policy(path: Path, *, line: int = 50, branch: int = 50) -> None:
    path.write_text(
        "\n".join(
            [
                "[packages.hwpxcore]",
                'path = "src/hwpxcore"',
                f"line = {line}",
                f"branch = {branch}",
            ]
        ),
        encoding="utf-8",
    )


def _write_xml(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages><package name="hwpxcore"><classes>
    <class filename="src/hwpxcore/api.py"><lines>
      <line number="10" hits="1" branch="true" condition-coverage="50% (1/2)"/>
      <line number="11" hits="0"/>
    </lines></class>
    <class filename="src/hwpxcore/native/motw.py"><lines>
      <line number="20" hits="0" branch="true" condition-coverage="0% (0/8)"/>
    </lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )


def test_exact_package_excludes_native_subpackage(tmp_path: Path) -> None:
    policy = tmp_path / "floors.toml"
    coverage = tmp_path / "coverage.xml"
    _write_policy(policy)
    _write_xml(coverage)

    result = gate.evaluate(coverage, gate.load_floors(policy))[0]

    assert (result.lines_covered, result.lines_total) == (1, 2)
    assert (result.branches_covered, result.branches_total) == (1, 2)
    assert result.passed


def test_failure_reports_missing_line_and_branch_locations(tmp_path: Path) -> None:
    policy = tmp_path / "floors.toml"
    coverage = tmp_path / "coverage.xml"
    report = tmp_path / "report.md"
    _write_policy(policy, line=80, branch=80)
    _write_xml(coverage)

    assert gate.main([str(coverage), "--config", str(policy), "--markdown-output", str(report)]) == 1
    text = report.read_text(encoding="utf-8")
    assert "FAIL" in text
    assert "src/hwpxcore/api.py:11" in text
    assert "src/hwpxcore/api.py:10" in text


def test_missing_package_evidence_fails_loudly(tmp_path: Path) -> None:
    policy = tmp_path / "floors.toml"
    coverage = tmp_path / "coverage.xml"
    _write_policy(policy)
    coverage.write_text("<coverage><packages/></coverage>", encoding="utf-8")

    with pytest.raises(gate.CoverageGateError, match="no coverage evidence"):
        gate.evaluate(coverage, gate.load_floors(policy))


def test_native_floor_is_rejected(tmp_path: Path) -> None:
    policy = tmp_path / "floors.toml"
    policy.write_text(
        '[packages."hwpxcore.native"]\npath="src/hwpxcore/native"\nline=40\nbranch=32\n',
        encoding="utf-8",
    )

    with pytest.raises(gate.CoverageGateError, match="separate native scenario"):
        gate.load_floors(policy)


def test_repository_policy_has_audited_packages_only() -> None:
    floors = gate.load_floors(ROOT / "docs" / "package_coverage_floors.toml")
    assert {floor.name for floor in floors} == {
        "hwpxcore",
        "hwpxdiff",
        "hwpxdiff.webapp",
        "hwpxfiller",
        "hwpxfiller.core",
        "hwpxfiller.data",
        "hwpxfiller.gui",
        "hwpxfiller.webapp",
    }
