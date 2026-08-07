"""R3-03 패리티 매트릭스의 형식·축·증거 실재를 닫는 게이트."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("pytester",)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "docs" / "UI_CONTRACT.md"
START = "<!-- R3-03-PARITY-MATRIX:START -->"
END = "<!-- R3-03-PARITY-MATRIX:END -->"
EXPECTED_AXES = {
    "css-cascade", "dom-aria", "keyboard-focus", "geometry",
    "motion", "forced-colors", "ts-copy",
}
EXPECTED_COLUMNS = ("축", "정적", "브라우저", "실창")
REFERENCE = re.compile(r"`([^`]+)`")
BLANK_PREFIX = "비어 있음 — "
_COLLECT_TIMEOUT_S = 300.0


def _matrix_text() -> str:
    text = CONTRACT.read_text(encoding="utf-8")
    assert text.count(START) == 1 and text.count(END) == 1, "패리티 매트릭스 마커는 각각 하나여야 합니다."
    return text.split(START, 1)[1].split(END, 1)[0]


def _parse_matrix(text: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        raise ValueError("패리티 표의 머리글·구분선·행이 모두 필요합니다.")

    def cells(line: str) -> tuple[str, ...]:
        return tuple(cell.strip() for cell in line.strip("|").split("|"))

    columns = cells(lines[0])
    if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells(lines[1])):
        raise ValueError("패리티 표의 두 번째 줄이 Markdown 구분선이 아닙니다.")
    rows: dict[str, tuple[str, ...]] = {}
    for line in lines[2:]:
        row = cells(line)
        if len(row) != len(columns):
            raise ValueError(f"패리티 표 열 수가 다릅니다: {line}")
        axis, *evidence = row
        if axis in rows:
            raise ValueError(f"패리티 축이 중복입니다: {axis}")
        rows[axis] = tuple(evidence)
    return columns, rows


def _collect_nodeids(args: list[str], output: Path) -> set[str]:
    """기존 suite probe로 pytest가 실제 선택한 node ID를 되읽는다."""
    tests_dir = REPO_ROOT / "tests"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tests_dir), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-c",
            str(REPO_ROOT / "pyproject.toml"),
            "--rootdir",
            str(REPO_ROOT),
            "-p",
            "no:cacheprovider",
            "-p",
            "_suite_probe",
            "--suite-probe-out",
            str(output),
            *args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=_COLLECT_TIMEOUT_S,
    )
    if proc.returncode != 0 or not output.is_file():
        raise RuntimeError(
            f"pytest 수집 실패(rc={proc.returncode})\n"
            f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
        )
    rows = json.loads(output.read_text(encoding="utf-8"))
    return {str(row["nodeid"]) for row in rows}


@pytest.fixture(scope="module")
def collection_evidence(tmp_path_factory) -> tuple[set[str], set[str]]:
    root = tmp_path_factory.mktemp("parity_collection")
    all_nodeids = _collect_nodeids([], root / "all.json")
    browser_nodeids = _collect_nodeids(["-m", "browser"], root / "browser.json")
    assert all_nodeids, "전체 pytest 수집이 0건입니다"
    assert browser_nodeids, "공식 `-m browser` 수집이 0건입니다"
    return all_nodeids, browser_nodeids


def _node_family(reference: str, nodeids: set[str]) -> set[str]:
    """비파라미터 참조가 가리키는 pytest 파라미터 family 전체를 돌려준다."""
    return {
        nodeid
        for nodeid in nodeids
        if nodeid == reference or nodeid.startswith(f"{reference}[")
    }


def _whole_family_is_selected(
    reference: str,
    all_nodeids: set[str],
    selected_nodeids: set[str],
) -> bool:
    family = _node_family(reference, all_nodeids)
    return bool(family) and family <= selected_nodeids


def _validate_matrix(
    text: str,
    all_nodeids: set[str],
    browser_nodeids: set[str],
) -> list[str]:
    failures: list[str] = []
    try:
        columns, rows = _parse_matrix(text)
    except ValueError as exc:
        return [str(exc)]
    if columns != EXPECTED_COLUMNS:
        failures.append(f"열이 다릅니다: {columns!r}")
    if set(rows) != EXPECTED_AXES:
        failures.append(
            f"축이 다릅니다 — 문서에만 {sorted(set(rows) - EXPECTED_AXES)}, "
            f"게이트에만 {sorted(EXPECTED_AXES - set(rows))}"
        )
    for axis, cells in rows.items():
        for column, cell in zip(EXPECTED_COLUMNS[1:], cells, strict=True):
            where = f"{axis}/{column}"
            if not cell:
                failures.append(f"{where}: 빈 칸입니다 — 사유 있는 공란을 쓰세요.")
                continue
            if cell.startswith("비어 있음"):
                if not cell.startswith(BLANK_PREFIX) or not cell.removeprefix(BLANK_PREFIX).strip():
                    failures.append(f"{where}: 공란 사유가 없습니다.")
                continue
            refs = REFERENCE.findall(cell)
            if not refs:
                failures.append(f"{where}: 검증 참조가 없습니다.")
                continue
            for ref in refs:
                file_name, separator, symbol = ref.partition("::")
                path = REPO_ROOT / file_name
                if not path.is_file():
                    failures.append(f"{where}: 검증 파일이 없습니다: {file_name}")
                    continue
                tests_root = (REPO_ROOT / "tests").resolve()
                is_collected_pytest_path = (
                    path.suffix == ".py"
                    and path.name.startswith("test_")
                    and path.resolve().is_relative_to(tests_root)
                    and bool(separator)
                )
                if column == "브라우저" and not is_collected_pytest_path:
                    failures.append(
                        f"{where}: browser 증거는 tests/test_*.py의 pytest node ID여야 합니다: {ref}"
                    )
                    continue
                if path.suffix == ".py":
                    if not is_collected_pytest_path or not _node_family(ref, all_nodeids):
                        failures.append(f"{where}: pytest가 수집하지 않는 테스트입니다: {ref}")
                    elif column == "브라우저" and not _whole_family_is_selected(
                        ref, all_nodeids, browser_nodeids
                    ):
                        failures.append(
                            f"{where}: 공식 `-m browser`가 전체 node family를 선택하지 않습니다: {ref}"
                        )
    return failures


def test_parity_matrix_is_closed_and_every_reference_exists(collection_evidence) -> None:
    failures = _validate_matrix(_matrix_text(), *collection_evidence)
    assert not failures, "패리티 매트릭스가 열려 있습니다:\n" + "\n".join(failures)


def test_ghost_gate_reference_is_rejected(collection_evidence) -> None:
    planted = _matrix_text().replace(
        "tests/test_web_css_manifest.py", "tests/__ghost_parity_gate__.py", 1,
    )
    failures = _validate_matrix(planted, *collection_evidence)
    assert any("__ghost_parity_gate__.py" in failure for failure in failures), failures


def test_blank_cell_without_a_reason_is_rejected(collection_evidence) -> None:
    planted = _matrix_text().replace(
        "비어 있음 — 링크 순서와 파일 전수는 실렌더 상태가 아니라 빌드 그래프 계약이다.",
        "비어 있음",
        1,
    )
    failures = _validate_matrix(planted, *collection_evidence)
    assert any("css-cascade/브라우저" in failure and "사유" in failure for failure in failures), failures


def test_browser_column_rejects_product_app_js_mutant(collection_evidence) -> None:
    planted = _matrix_text().replace(
        "tests/test_web_press_geometry.py::test_row_surface_left_edge_does_not_move_while_held",
        "frontend/src/shell/app.ts",
        1,
    )
    failures = _validate_matrix(planted, *collection_evidence)
    assert any("geometry/브라우저" in failure and "frontend/src/shell/app.ts" in failure for failure in failures), failures


def test_browser_column_rejects_unmarked_pytest_node(collection_evidence) -> None:
    planted = _matrix_text().replace(
        "tests/test_web_press_geometry.py::test_row_surface_left_edge_does_not_move_while_held",
        "tests/test_parity_matrix.py::test_ghost_gate_reference_is_rejected",
        1,
    )
    failures = _validate_matrix(planted, *collection_evidence)
    assert any("geometry/브라우저" in failure and "browser" in failure for failure in failures), failures


def test_browser_column_rejects_static_node_test_file(collection_evidence) -> None:
    planted = _matrix_text().replace(
        "tests/test_web_press_geometry.py::test_row_surface_left_edge_does_not_move_while_held",
        "tests/js/overlay_host.test.js",
        1,
    )
    failures = _validate_matrix(planted, *collection_evidence)
    assert any("geometry/브라우저" in failure and "overlay_host.test.js" in failure for failure in failures), failures


def test_browser_identity_follows_effective_pytest_collection(pytester) -> None:
    pytester.makeini(
        """
[pytest]
markers =
    browser: browser axis
    live: live axis
""".lstrip()
    )
    pytester.makepyfile(
        test_marker_claims="""
import pytest as pt

pytestmark = pt.mark.browser
pytestmark = pt.mark.live

def test_overwritten_module_marker():
    pass

@pt.mark.browser
def test_alias_marker():
    pass

@pt.mark.browser
class TestHidden:
    __test__ = False

    def test_hidden(self):
        pass

class TestClassMarker:
    pytestmark = pt.mark.browser

    def test_class_marker(self):
        pass

class BrowserBase:
    @pt.mark.browser
    def test_inherited_marker(self):
        pass

class TestInherited(BrowserBase):
    pass

@pt.mark.parametrize(
    "value",
    [
        pt.param(1, marks=pt.mark.browser, id="browser"),
        pt.param(2, id="plain"),
    ],
)
def test_parameter_marker(value):
    pass
"""
    )
    full_result = pytester.runpytest_subprocess(
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
    )
    browser_result = pytester.runpytest_subprocess(
        "--collect-only",
        "-q",
        "-m",
        "browser",
        "-p",
        "no:cacheprovider",
    )
    assert full_result.ret == 0, full_result.stderr.str()
    assert browser_result.ret == 0, browser_result.stderr.str()
    collected = {line.strip() for line in full_result.stdout.lines if "::" in line}
    selected = {line.strip() for line in browser_result.stdout.lines if "::" in line}
    suffixes = {nodeid.split("::", 1)[1] for nodeid in selected}

    assert "test_overwritten_module_marker" not in suffixes
    assert not any("TestHidden" in suffix for suffix in suffixes)
    assert "test_alias_marker" in suffixes
    assert "TestClassMarker::test_class_marker" in suffixes
    assert "TestInherited::test_inherited_marker" in suffixes
    assert "test_parameter_marker[browser]" in suffixes
    assert "test_parameter_marker[plain]" not in suffixes
    assert not _whole_family_is_selected(
        "test_marker_claims.py::test_parameter_marker",
        collected,
        selected,
    )
    assert _whole_family_is_selected(
        "test_marker_claims.py::test_parameter_marker[browser]",
        collected,
        selected,
    )
