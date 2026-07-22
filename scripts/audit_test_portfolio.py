"""Reproducible inventory and matrix builder for the test portfolio audit.

The tool deliberately consumes pytest/coverage artifacts instead of invoking the
test runner.  That keeps evidence collection separate from classification and
makes stale or partial evidence fail loudly.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LAYERS = {"unit", "contract", "integration", "ui-runtime", "distribution"}
PLATFORMS = {
    "cross-platform",
    "windows",
    "windows-desktop-webview2",
    "windows-packaging",
    "windows-installer-release",
}
RISK_SURFACES = {
    "document-package-integrity",
    "extract-fill-transform",
    "diff-correctness",
    "mapping-validation-drift",
    "durable-registry-persistence",
    "data-ingestion-boundaries",
    "application-workflows",
    "web-runtime-bridge",
    "native-packaging-release",
    "architecture-design-system",
}
VERIFICATION_METHODS = {
    "behavioral",
    "static-source",
    "snapshot-golden",
    "real-runtime",
    "build-install",
}
FIXTURE_KINDS = {"none", "synthetic", "real-corpus", "recorded-external", "mixed"}
DISPOSITIONS = {
    "keep-owner",
    "keep-supporting",
    "merge-candidate",
    "reclassify",
}
CSV_FIELDS = [
    "nodeid",
    "source",
    "layer",
    "risk_surfaces",
    "platform",
    "execution_unit_id",
    "contract_claims",
    "claim_count",
    "fixture_kind",
    "verification_method",
    "owner_contract",
    "duration_s",
    "covered_modules",
    "correlation_group",
    "duplicate_of",
    "disposition",
    "evidence",
]


class AuditError(RuntimeError):
    """Raised when evidence or classification is incomplete."""


@dataclass(frozen=True)
class TestCase:
    nodeid: str
    source: str
    duration: float
    outcome: str


def _source_and_nodeid(classname: str, name: str) -> tuple[str, str]:
    parts = classname.split(".")
    if len(parts) < 2 or parts[0] != "tests":
        raise AuditError(f"unsupported pytest classname: {classname!r}")
    source = "/".join(parts[:2]) + ".py"
    suffix = parts[2:] + [name]
    return source, "::".join([source, *suffix])


def read_junit(path: Path) -> list[TestCase]:
    if not path.is_file():
        raise AuditError(f"JUnit evidence missing: {path}")
    root = ET.parse(path).getroot()
    cases: list[TestCase] = []
    for element in root.iter("testcase"):
        source, nodeid = _source_and_nodeid(element.attrib["classname"], element.attrib["name"])
        outcome = "passed"
        if element.find("failure") is not None:
            outcome = "failed"
        elif element.find("error") is not None:
            outcome = "error"
        elif element.find("skipped") is not None:
            outcome = "skipped"
        cases.append(TestCase(nodeid, source, float(element.attrib.get("time", 0.0)), outcome))
    if not cases:
        raise AuditError(f"JUnit contains no test cases: {path}")
    seen: set[str] = set()
    duplicates = {case.nodeid for case in cases if case.nodeid in seen or seen.add(case.nodeid)}
    if duplicates:
        raise AuditError(f"duplicate nodeids in JUnit: {sorted(duplicates)[:5]}")
    return cases


def read_coverage_contexts(path: Path, repo_root: Path) -> dict[str, set[str]]:
    if not path.is_file():
        raise AuditError(f"coverage context evidence missing: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    inverse: dict[str, set[str]] = defaultdict(set)
    root = repo_root.resolve()
    for filename, details in report.get("files", {}).items():
        file_path = Path(filename)
        try:
            module = file_path.resolve().relative_to(root).as_posix()
        except ValueError:
            normalized = filename.replace("\\", "/")
            marker = "/src/"
            module = "src/" + normalized.split(marker, 1)[1] if marker in normalized else normalized
        for contexts in details.get("contexts", {}).values():
            for context in contexts:
                nodeid = context.removesuffix("|run")
                if nodeid:
                    inverse[nodeid].add(module)
    return inverse


def _base_nodeid(nodeid: str) -> str:
    return re.sub(r"\[[^\]]*\]$", "", nodeid)


def _ast_test_metadata(path: Path) -> dict[str, tuple[int, list[str]]]:
    # Python accepts a UTF-8 BOM at the start of a source file, but ``ast.parse``
    # receives an already-decoded string and therefore cannot strip it itself.
    # Match Python's source loader by consuming the optional BOM here.
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    result: dict[str, tuple[int, list[str]]] = {}
    class_stack: list[str] = []

    def walk(nodes: Iterable[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                class_stack.append(node.name)
                walk(node.body)
                class_stack.pop()
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                key = "::".join([*class_stack, node.name])
                claims = sum(isinstance(item, ast.Assert) for item in ast.walk(node))
                fixtures = [arg.arg for arg in node.args.args if arg.arg != "self"]
                result[key] = (max(claims, 1), fixtures)

    walk(tree.body)
    return result


def _merged_rule(config: dict[str, Any], case: TestCase) -> dict[str, Any]:
    rule = dict(config.get("defaults", {}))
    file_rules = config.get("files", {})
    if case.source not in file_rules:
        raise AuditError(f"classification missing file rule: {case.source}")
    rule.update(file_rules[case.source])
    base = _base_nodeid(case.nodeid)
    class_key = base.rsplit("::", 1)[0] if base.count("::") >= 2 else ""
    if class_key in config.get("classes", {}):
        rule.update(config["classes"][class_key])
    if base in config.get("tests", {}):
        rule.update(config["tests"][base])
    return rule


def validate_classification(config: dict[str, Any], cases: list[TestCase]) -> None:
    sources = {case.source for case in cases}
    file_rules = set(config.get("files", {}))
    if sources != file_rules:
        raise AuditError(
            "classification file-rule mismatch; "
            f"missing={sorted(sources - file_rules)[:5]}, stale={sorted(file_rules - sources)[:5]}"
        )
    bases = {_base_nodeid(case.nodeid) for case in cases}
    test_rules = set(config.get("tests", {}))
    stale_tests = test_rules - bases
    if stale_tests:
        raise AuditError(f"stale test classification overrides: {sorted(stale_tests)[:5]}")
    classes = {base.rsplit("::", 1)[0] for base in bases if base.count("::") >= 2}
    class_rules = set(config.get("classes", {}))
    stale_classes = class_rules - classes
    if stale_classes:
        raise AuditError(f"stale class classification overrides: {sorted(stale_classes)[:5]}")


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    return list(value or [])


def _validate_rule(rule: dict[str, Any], nodeid: str) -> None:
    checks = (
        ("layer", LAYERS),
        ("platform", PLATFORMS),
        ("fixture_kind", FIXTURE_KINDS),
        ("verification_method", VERIFICATION_METHODS),
        ("disposition", DISPOSITIONS),
    )
    for field, allowed in checks:
        if rule.get(field) not in allowed:
            raise AuditError(f"{nodeid}: invalid {field}={rule.get(field)!r}")
    risks = set(_list_value(rule.get("risk_surfaces")))
    if not risks or not risks <= RISK_SURFACES:
        raise AuditError(f"{nodeid}: invalid risk_surfaces={sorted(risks)!r}")


def collect_rows(
    cases: list[TestCase],
    coverage: dict[str, set[str]],
    classification: dict[str, Any],
    repo_root: Path,
) -> list[dict[str, str]]:
    ast_cache: dict[str, dict[str, tuple[int, list[str]]]] = {}
    rows: list[dict[str, str]] = []
    for case in cases:
        rule = _merged_rule(classification, case)
        _validate_rule(rule, case.nodeid)
        if case.source not in ast_cache:
            ast_cache[case.source] = _ast_test_metadata(repo_root / case.source)
        symbol = "::".join(_base_nodeid(case.nodeid).split("::")[1:])
        claim_count, fixtures = ast_cache[case.source].get(symbol, (1, []))
        execution = str(rule.get("execution_unit", "{nodeid}")).format(nodeid=case.nodeid)
        claim = str(rule.get("contract_claims") or symbol.split("::")[-1].removeprefix("test_").replace("_", " "))
        owner = str(rule.get("owner_contract") or claim)
        evidence = str(rule.get("evidence") or f"{case.source}; fixtures={','.join(fixtures) or '-'}")
        covered = coverage.get(case.nodeid, coverage.get(_base_nodeid(case.nodeid), set()))
        rows.append(
            {
                "nodeid": case.nodeid,
                "source": case.source,
                "layer": rule["layer"],
                "risk_surfaces": ";".join(_list_value(rule["risk_surfaces"])),
                "platform": rule["platform"],
                "execution_unit_id": execution,
                "contract_claims": claim,
                "claim_count": str(claim_count),
                "fixture_kind": rule["fixture_kind"],
                "verification_method": rule["verification_method"],
                "owner_contract": owner,
                "duration_s": f"{case.duration:.6f}",
                "covered_modules": ";".join(sorted(covered)),
                "correlation_group": str(rule.get("correlation_group", "")),
                "duplicate_of": str(rule.get("duplicate_of", "")),
                "disposition": rule["disposition"],
                "evidence": evidence,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise AuditError(f"inventory missing: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_FIELDS:
            raise AuditError(f"inventory columns differ: {reader.fieldnames!r}")
        return list(reader)


def validate_rows(rows: list[dict[str, str]], junit: list[TestCase] | None = None) -> None:
    nodeids = [row["nodeid"] for row in rows]
    if len(nodeids) != len(set(nodeids)):
        raise AuditError("inventory contains duplicate nodeids")
    for row in rows:
        _validate_rule(row, row["nodeid"])
        if not row["execution_unit_id"] or not row["owner_contract"]:
            raise AuditError(f"{row['nodeid']}: missing execution unit or owner contract")
        try:
            int(row["claim_count"])
            float(row["duration_s"])
        except ValueError as exc:
            raise AuditError(f"{row['nodeid']}: invalid numeric field") from exc
    if junit is not None:
        expected = {case.nodeid for case in junit}
        actual = set(nodeids)
        if expected != actual:
            missing = sorted(expected - actual)[:5]
            stale = sorted(actual - expected)[:5]
            raise AuditError(f"inventory/JUnit mismatch; missing={missing}, stale={stale}")


def render_matrix(rows: list[dict[str, str]], metadata: dict[str, str]) -> str:
    by_risk: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        for risk in row["risk_surfaces"].split(";"):
            by_risk[risk].append(row)
    lines = [
        "# 테스트 포트폴리오 생성 매트릭스",
        "",
        "> `scripts/audit_test_portfolio.py render`로 재생성한다. 수치는 위험 태그별 중복 집계를 허용한다.",
        "",
        f"- 기준 SHA: `{metadata.get('baseline_sha', 'unknown')}`",
        f"- 수집 사례: **{len(rows)}**",
        f"- 독립 실행 단위: **{len({row['execution_unit_id'] for row in rows})}**",
        f"- 계약 단언: **{sum(int(row['claim_count']) for row in rows)}**",
        f"- 합산 실행시간: **{sum(float(row['duration_s']) for row in rows):.2f}s**",
        "",
        "## 위험 표면 요약",
        "",
        "| 위험 표면 | 사례 | 실행 단위 | 단언 | 시간(s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for risk in sorted(by_risk):
        group = by_risk[risk]
        lines.append(
            f"| `{risk}` | {len(group)} | {len({row['execution_unit_id'] for row in group})} | "
            f"{sum(int(row['claim_count']) for row in group)} | {sum(float(row['duration_s']) for row in group):.2f} |"
        )
    lines.extend(["", "## 계층 요약", "", "| 계층 | 사례 | 실행 단위 |", "|---|---:|---:|"])
    for layer in sorted(LAYERS):
        group = [row for row in rows if row["layer"] == layer]
        lines.append(f"| `{layer}` | {len(group)} | {len({row['execution_unit_id'] for row in group})} |")
    lines.extend(["", "## 계층 × 플랫폼", "", "| 계층 | 플랫폼 | 사례 | 실행 단위 |", "|---|---|---:|---:|"])
    cells: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        cells[(row["layer"], row["platform"])].append(row)
    for (layer, platform), group in sorted(cells.items()):
        lines.append(f"| `{layer}` | `{platform}` | {len(group)} | {len({row['execution_unit_id'] for row in group})} |")
    lines.extend(["", "## 상관 그룹", "", "| 그룹 | 사례 | 실행 단위 |", "|---|---:|---:|"])
    correlations: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["correlation_group"]:
            correlations[row["correlation_group"]].append(row)
    for name, group in sorted(correlations.items()):
        lines.append(f"| `{name}` | {len(group)} | {len({row['execution_unit_id'] for row in group})} |")
    lines.extend(["", "## 최장 실행 사례", "", "| nodeid | 시간(s) |", "|---|---:|"])
    for row in sorted(rows, key=lambda item: float(item["duration_s"]), reverse=True)[:20]:
        lines.append(f"| `{row['nodeid']}` | {float(row['duration_s']):.3f} |")
    return "\n".join(lines) + "\n"


def load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise AuditError(f"classification missing: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect")
    collect.add_argument("--junit", type=Path, required=True)
    collect.add_argument("--coverage-contexts", type=Path, required=True)
    collect.add_argument("--classification", type=Path, required=True)
    collect.add_argument("--repo-root", type=Path, default=Path.cwd())
    collect.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("inventory", type=Path)
    validate.add_argument("--junit", type=Path)
    render = sub.add_parser("render")
    render.add_argument("inventory", type=Path)
    render.add_argument("--metadata", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "collect":
            cases = read_junit(args.junit)
            coverage = read_coverage_contexts(args.coverage_contexts, args.repo_root)
            classification = load_toml(args.classification)
            validate_classification(classification, cases)
            rows = collect_rows(cases, coverage, classification, args.repo_root)
            validate_rows(rows, cases)
            write_csv(args.output, rows)
            print(f"wrote {len(rows)} test cases to {args.output}")
        elif args.command == "validate":
            rows = read_csv(args.inventory)
            junit = read_junit(args.junit) if args.junit else None
            validate_rows(rows, junit)
            print(f"validated {len(rows)} test cases")
        else:
            rows = read_csv(args.inventory)
            validate_rows(rows)
            metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
            output = render_matrix(rows, metadata)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
            print(f"rendered matrix to {args.output}")
    except (AuditError, OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"audit error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
