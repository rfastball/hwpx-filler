from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[2]
HANDOFF = ROOT / "docs" / "p2_handoff.toml"


def _document() -> dict[str, object]:
    return tomllib.loads(HANDOFF.read_text(encoding="utf-8"))


def _module_for_path(relative: str) -> str:
    path = Path(relative)
    parts = list(path.with_suffix("").parts[1:])
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(package: str, *, level: int, module: str | None) -> str:
    if level:
        parts = package.split(".") if package else []
        keep = len(parts) - (level - 1)
        base = parts[: max(keep, 0)]
        if module:
            base.extend(module.split("."))
        return ".".join(base)
    return module or ""


def _internal_import_edges(units: list[dict[str, object]]) -> set[tuple[str, str]]:
    known = {str(unit["module"]) for unit in units}
    edges: set[tuple[str, str]] = set()
    for unit in units:
        source = str(unit["module"])
        for relative in unit["source_write_set"]:
            path = ROOT / str(relative)
            package = source if path.name == "__init__.py" else source.rpartition(".")[0]
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                candidates: list[str] = []
                if isinstance(node, ast.Import):
                    candidates.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    base = _resolve_from(package, level=node.level, module=node.module)
                    candidates.extend(
                        f"{base}.{alias.name}" if base else alias.name
                        for alias in node.names
                        if alias.name != "*"
                    )
                    if base:
                        candidates.append(base)
                for candidate in candidates:
                    matches = [
                        module
                        for module in known
                        if candidate == module or candidate.startswith(f"{module}.")
                    ]
                    if matches:
                        destination = max(matches, key=len)
                        if destination != source:
                            edges.add((source, destination))
    return edges


def test_handoff_is_a_closed_minimal_inventory() -> None:
    document = _document()
    assert document["schema"] == "p2-handoff/v1"
    assert document["p1_verdict"] == "ONE_WAVE_READY"
    units = document["unit"]
    modules = [str(unit["module"]) for unit in units]
    sources = [str(path) for unit in units for path in unit["source_write_set"]]
    assert len(modules) == len(set(modules))
    assert len(sources) == len(set(sources))
    assert all((ROOT / source).is_file() for source in sources)


def test_no_new_outward_dependency_is_hidden_by_the_p1_allowlist() -> None:
    document = _document()
    units = document["unit"]
    targets = {str(unit["module"]): str(unit["target"]) for unit in units}
    ring = {str(name): int(rank) for name, rank in document["ring"].items()}
    allowed = {
        (str(edge["src"]), str(edge["dst"]))
        for edge in document["allowed_direction_violation"]
    }
    outward = {
        (source, destination)
        for source, destination in _internal_import_edges(units)
        if targets[source] in ring
        and targets[destination] in ring
        and ring[targets[source]] < ring[targets[destination]]
    }
    assert outward <= allowed, f"P1 이후 새 안쪽→바깥쪽 의존: {sorted(outward - allowed)}"
    assert allowed <= outward, f"이미 제거된 P2 예외를 handoff에서 지우세요: {sorted(allowed - outward)}"


def test_required_pytest_oracles_still_collect() -> None:
    nodeids = sorted(
        {
            str(unit["oracle_nodeid"])
            for unit in _document()["unit"]
            if "oracle_nodeid" in unit
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--disable-warnings",
            *nodeids,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
