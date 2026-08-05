"""R3-03 패리티 매트릭스의 형식·축·증거 실재를 닫는 게이트."""
from __future__ import annotations

import ast
import re
from pathlib import Path

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


def _python_test_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    symbols = {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                symbols.add(f"{node.name}::{child.name}")
    return symbols


def _validate_matrix(text: str) -> list[str]:
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
                if path.suffix == ".py" and separator:
                    if symbol not in _python_test_symbols(path):
                        failures.append(f"{where}: Python 테스트가 없습니다: {ref}")
    return failures


def test_parity_matrix_is_closed_and_every_reference_exists() -> None:
    failures = _validate_matrix(_matrix_text())
    assert not failures, "패리티 매트릭스가 열려 있습니다:\n" + "\n".join(failures)


def test_ghost_gate_reference_is_rejected() -> None:
    planted = _matrix_text().replace(
        "tests/test_web_css_manifest.py", "tests/__ghost_parity_gate__.py", 1,
    )
    failures = _validate_matrix(planted)
    assert any("__ghost_parity_gate__.py" in failure for failure in failures), failures


def test_blank_cell_without_a_reason_is_rejected() -> None:
    planted = _matrix_text().replace(
        "비어 있음 — 링크 순서와 파일 전수는 실렌더 상태가 아니라 빌드 그래프 계약이다.",
        "비어 있음",
        1,
    )
    failures = _validate_matrix(planted)
    assert any("css-cascade/브라우저" in failure and "사유" in failure for failure in failures), failures
