"""SG-02(#734) static guard: theorem/static admission 과 runtime materializer conformance 는 disjoint.

theorem PASS 를 actual materialization 성공으로 조용히 승격시키는 경로가 생기지 않게, seal/compile
admission 경로가 :class:`RuntimeMaterializerConformanceRegistry`(current runtime conformance)를
**admission gate 로 import·consult 하지 않음** 을 정적으로 강제한다("declaration lives, result dies"
방어 — 문구만 좁히고 코드가 다시 섞이면 이 게이트가 잡는다).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "hwpxfiller" / "application"

# seal/compile 이 sealed Plan 의 ordered_operations 를 admit 하는 모듈들(sealing gate 경로).
SEALING_PATH_MODULES = (
    "seal_execution_plan.py",
    "execution_compilation.py",
    "execution_contract_set.py",
)

# runtime materializer conformance(current admission) seam — sealing gate 가 만지면 안 되는 심볼.
FORBIDDEN_RUNTIME_SYMBOLS = frozenset(
    {
        "RuntimeMaterializerConformanceRegistry",
        "RuntimeMaterializerConformanceManifest",
        "DEFAULT_RUNTIME_CONFORMANCE_REGISTRY",
        "runtime_conformance_digest",
        "require_admitted",
        "is_admitted",
    }
)


def _identifiers(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def test_sealing_path_never_consults_runtime_conformance_registry() -> None:
    offenders: list[str] = []
    for module in SEALING_PATH_MODULES:
        path = APP / module
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        used = _identifiers(tree) & FORBIDDEN_RUNTIME_SYMBOLS
        if used:
            offenders.append(f"{module}: {sorted(used)}")
    assert not offenders, (
        "seal/compile admission 경로가 runtime materializer conformance seam 을 consult 한다 "
        "(theorem PASS 를 actual materialization 성공으로 승격시키는 경로 금지):\n"
        + "\n".join(offenders)
    )


def test_default_runtime_conformance_registry_is_empty_until_s6() -> None:
    # 기본 registry 는 비어 있어야 한다 — 어떤 조회도 admit 되지 않는다(fail-closed, S6 가 채운다).
    from hwpxfiller.application.execution_composition import (
        DEFAULT_RUNTIME_CONFORMANCE_REGISTRY,
    )

    assert not DEFAULT_RUNTIME_CONFORMANCE_REGISTRY.is_admitted(
        runtime_capability_manifest_digest="sha256:x",
        materialization_contract_id="materialization/v1",
        materialization_base_contract_id="applied-template-candidate-base/v1",
        native_primitive_contract_id="hwpx-native-primitive/v1",
        composition_contract_id="hwpx-composition/v1",
        plan_schema_version="hwpx-execution-plan/v1",
        canonical_encoding_version="canonical-execution-encoding/v1",
    )
