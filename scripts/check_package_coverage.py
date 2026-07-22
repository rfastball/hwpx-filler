"""Enforce exact-package line and branch floors from coverage.py XML.

Each configured path covers files directly inside that directory.  Subpackages
are intentionally excluded so a weak surface (notably ``hwpxcore.native``)
cannot be hidden inside an aggregate parent percentage.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


class CoverageGateError(RuntimeError):
    """Raised when the policy or coverage evidence is incomplete."""


@dataclass(frozen=True)
class Floor:
    name: str
    path: str
    line: float
    branch: float


@dataclass
class PackageResult:
    floor: Floor
    lines_covered: int = 0
    lines_total: int = 0
    branches_covered: int = 0
    branches_total: int = 0
    missing_lines: dict[str, list[int]] = field(default_factory=dict)
    missing_branches: dict[str, list[int]] = field(default_factory=dict)

    @property
    def line_rate(self) -> float:
        return 100.0 * self.lines_covered / self.lines_total

    @property
    def branch_rate(self) -> float:
        return 100.0 * self.branches_covered / self.branches_total

    @property
    def passed(self) -> bool:
        return self.line_rate >= self.floor.line and self.branch_rate >= self.floor.branch


_BRANCH_COUNTS = re.compile(r"\((\d+)\s*/\s*(\d+)\)")


def _normalized_source_path(filename: str) -> PurePosixPath:
    normalized = filename.replace("\\", "/").lstrip("./")
    if normalized.startswith("src/"):
        normalized = normalized[4:]
    return PurePosixPath(normalized)


def load_floors(path: Path) -> list[Floor]:
    if not path.is_file():
        raise CoverageGateError(f"coverage floor policy missing: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    packages = data.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise CoverageGateError("coverage floor policy has no [packages.*] entries")

    floors: list[Floor] = []
    seen_paths: set[str] = set()
    for name, values in packages.items():
        if not isinstance(values, dict):
            raise CoverageGateError(f"invalid package policy: {name}")
        try:
            package_path = str(values["path"]).replace("\\", "/").removeprefix("src/").rstrip("/")
            line = float(values["line"])
            branch = float(values["branch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CoverageGateError(f"invalid package policy: {name}") from exc
        if not package_path or package_path in seen_paths:
            raise CoverageGateError(f"duplicate or empty package path: {package_path!r}")
        if not 0 <= line <= 100 or not 0 <= branch <= 100:
            raise CoverageGateError(f"floor outside 0..100: {name}")
        if name == "hwpxcore.native" or package_path == "hwpxcore/native":
            raise CoverageGateError("hwpxcore.native must use the separate native scenario gate")
        seen_paths.add(package_path)
        floors.append(Floor(str(name), package_path, line, branch))
    return floors


def _branch_counts(line: ET.Element) -> tuple[int, int]:
    if line.attrib.get("branch") != "true":
        return 0, 0
    match = _BRANCH_COUNTS.search(line.attrib.get("condition-coverage", ""))
    if match is None:
        raise CoverageGateError("branch line lacks coverage.py condition counts")
    return int(match.group(1)), int(match.group(2))


def evaluate(xml_path: Path, floors: list[Floor]) -> list[PackageResult]:
    if not xml_path.is_file():
        raise CoverageGateError(f"coverage XML missing: {xml_path}")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise CoverageGateError(f"invalid coverage XML: {xml_path}") from exc

    results = {floor.path: PackageResult(floor) for floor in floors}
    for class_element in root.findall(".//class"):
        filename = class_element.attrib.get("filename")
        if not filename:
            continue
        source_path = _normalized_source_path(filename)
        result = results.get(source_path.parent.as_posix())
        if result is None:
            continue
        for line in class_element.findall("./lines/line"):
            try:
                number = int(line.attrib["number"])
                hits = int(line.attrib.get("hits", "0"))
            except (KeyError, ValueError) as exc:
                raise CoverageGateError(f"invalid line evidence in {filename}") from exc
            result.lines_total += 1
            if hits:
                result.lines_covered += 1
            else:
                result.missing_lines.setdefault(filename, []).append(number)
            covered, total = _branch_counts(line)
            result.branches_covered += covered
            result.branches_total += total
            if total and covered < total:
                result.missing_branches.setdefault(filename, []).append(number)

    for result in results.values():
        if result.lines_total == 0:
            raise CoverageGateError(f"no coverage evidence for package {result.floor.name}")
        if result.branches_total == 0:
            raise CoverageGateError(f"no branch evidence for package {result.floor.name}")
    return list(results.values())


def _locations(items: dict[str, list[int]], limit: int = 80) -> str:
    locations: list[str] = []
    for filename, numbers in sorted((items or {}).items()):
        locations.extend(f"{filename}:{number}" for number in numbers)
    if len(locations) > limit:
        locations = [*locations[:limit], f"… and {len(locations) - limit} more"]
    return ", ".join(locations) or "none"


def render_markdown(results: list[PackageResult]) -> str:
    lines = [
        "# Package coverage gate",
        "",
        "Only files directly in each package are counted; subpackages are separate surfaces.",
        "",
        "| Package | Line | Floor | Branch | Floor | Result |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for result in results:
        lines.append(
            f"| `{result.floor.name}` | {result.line_rate:.2f}% "
            f"({result.lines_covered}/{result.lines_total}) | {result.floor.line:g}% | "
            f"{result.branch_rate:.2f}% ({result.branches_covered}/{result.branches_total}) | "
            f"{result.floor.branch:g}% | {'PASS' if result.passed else 'FAIL'} |"
        )
    failed = [result for result in results if not result.passed]
    if failed:
        lines.extend(["", "## Regressions"])
        for result in failed:
            lines.extend(
                [
                    "",
                    f"### `{result.floor.name}`",
                    "",
                    f"- Missing lines: {_locations(result.missing_lines)}",
                    f"- Partial/missing branch lines: {_locations(result.missing_branches)}",
                ]
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_xml", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args(argv)
    try:
        results = evaluate(args.coverage_xml, load_floors(args.config))
        report = render_markdown(results)
        if args.markdown_output:
            args.markdown_output.write_text(report, encoding="utf-8")
        print(report, end="")
        return 0 if all(result.passed for result in results) else 1
    except (CoverageGateError, OSError) as exc:
        print(f"coverage gate error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
