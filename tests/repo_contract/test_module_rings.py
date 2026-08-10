"""모듈 ring 좌표 계약(`docs/module_rings.toml`)의 게이트 — 안쪽→바깥쪽 의존을 막는다.

물리 패키지 경계 게이트 4종(`test_domain_boundary`·`test_application_boundary`·
`test_external_adapter_boundary`·`test_host_boundary`)의 정의역은 각자 새 패키지뿐이라,
아직 옛 폴더(`core/`·`data/`·`gui/`·`webapp/`)에 사는 유닛의 방향은 **여기만** 본다.
#542 H-2 실측: `core.lint → webapp.screens` 를 심으면 repo_contract 92 노드 중 이 파일만
빨강이고 나머지 91 은 초록이다 — 물리 이관이 끝나기 전에 이 게이트를 지우면 순손실이다.

유래는 P1 계측의 P2 handoff(#512~#520)이고, P2 완주 뒤 P1 부기는 걷어내 계약만 남겼다.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[2]
RINGS = ROOT / "docs" / "module_rings.toml"


def _document() -> dict[str, object]:
    return tomllib.loads(RINGS.read_text(encoding="utf-8"))


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


#: 물리 경계 게이트가 ``rglob`` 으로 **범위째** 소유하는 패키지 — 새 파일이 자동으로 그
#: 게이트 모집단에 들어오므로 ring 인벤토리에 이름을 올릴 필요가 없다.
#: `domain/`=test_domain_boundary · `application/`=test_application_boundary ·
#: `external/`=test_external_adapter_boundary · `host/`=test_host_boundary.
PHYSICALLY_GATED = (
    "src/hwpxfiller/domain",
    "src/hwpxfiller/application",
    "src/hwpxfiller/external",
    "src/hwpxfiller/host",
)


def _governed_sources() -> "set[str]":
    return {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _is_physically_gated(source: str) -> bool:
    return any(source.startswith(f"{root}/") for root in PHYSICALLY_GATED)


def test_ring_contract_is_a_closed_minimal_inventory() -> None:
    """인벤토리는 **양방향**으로 닫힌다 — 등재된 파일이 있고, 있는 파일이 등재된다.

    한쪽(등재→존재)만 세면 등재되지 않은 새 모듈이 :func:`_internal_import_edges` 의
    정의역 밖에 앉아 방향 게이트를 **조용히** 통과한다(#542 감사가 지목한 「게이트 정의역이
    열거」의 이 파일판, 코덱스 #584 P2). 물리 경계 게이트가 ``rglob`` 으로 범위째 소유하는
    네 패키지만 예외이고, 그 밖의 새 파일은 등재 전까지 여기서 빨강이다.
    """
    document = _document()
    assert document["schema"] == "module-rings/v1"
    units = document["unit"]
    modules = [str(unit["module"]) for unit in units]
    sources = [str(path) for unit in units for path in unit["source_write_set"]]
    assert len(modules) == len(set(modules))
    assert len(sources) == len(set(sources))

    census = _governed_sources()
    listed = set(sources)
    assert not listed - census, f"인벤토리가 없는 파일을 가리킵니다: {sorted(listed - census)}"
    unregistered = {s for s in census - listed if not _is_physically_gated(s)}
    assert not unregistered, (
        "ring 인벤토리에 없는 모듈입니다 — docs/module_rings.toml 에 등재하거나 물리 경계 "
        f"패키지로 옮기세요(방향 게이트가 못 봅니다): {sorted(unregistered)}"
    )


def test_no_inward_module_depends_outward() -> None:
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
    assert outward <= allowed, f"새 안쪽→바깥쪽 의존: {sorted(outward - allowed)}"
    assert allowed <= outward, f"이미 제거된 예외를 계약에서 지우세요: {sorted(allowed - outward)}"


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
