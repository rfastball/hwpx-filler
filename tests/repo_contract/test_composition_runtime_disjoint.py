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
        plan_schema_version="hwpx-execution-plan/v2",
        canonical_encoding_version="canonical-execution-encoding/v1",
    )


# ── S6G-00(#806): runtime conformance override 는 production 에 존재하지 않는다(#729 잔여위험 4) ──
# `SealExecutionPlanProduct` 는 `runtime_conformance` 를 생성자 kwarg 로 받고 기본값이
# `s6_absent_runtime_conformance`(NOT_ADMITTED)다. production 이 그 kwarg 를 넘기는 순간 admission 이
# ADMITTED 로 뒤집히는데, 그것을 막는 계약이 여태 없었다. **S6 는 이 계약을 철거하지 않는다** —
# #807 D4 대로 S6 는 우회 kwarg 가 아니라 정식 주입 경로로 admit 한다. 지금 못 박지 않으면 S6 가
# kwarg 하나를 정식 경로로 만든다.
SRC = ROOT / "src"

RUNTIME_OVERRIDE_KWARG = "runtime_conformance"


def _override_call_sites(source: str, label: str) -> list[str]:
    """``runtime_conformance=`` 를 **인자로 넘기는** 자리만 센다(매개변수 선언은 정의라 제외)."""
    sites: list[str] = []
    tree = ast.parse(source, filename=label)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == RUNTIME_OVERRIDE_KWARG:
                sites.append(f"{label}:{node.lineno}")
    return sites


def test_production_never_passes_runtime_conformance_override() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        offenders += _override_call_sites(
            path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)).replace("\\", "/")
        )
    assert not offenders, (
        "production 이 runtime materializer conformance 를 kwarg 로 덮어쓴다 — admission 이 "
        "NOT_ADMITTED 에서 ADMITTED 로 뒤집힌다(S6 는 정식 주입 경로로 admit 한다):\n"
        + "\n".join(offenders)
    )


def test_negative_probe_detects_runtime_conformance_override() -> None:
    # 음성 대조는 **실 스캐너**를 태운다 — 자기 정규식이 아니라 현실을 재기 위해서다(#805 의 교훈).
    caught = _override_call_sites(
        "SealExecutionPlanProduct(resolve_route=r, runtime_conformance=always_admitted)\n",
        "probe.py",
    )
    assert caught == ["probe.py:1"]
    # 매개변수 **선언**은 잡지 않는다(정의는 seam 이고, 넘기는 것이 위반이다).
    assert _override_call_sites(
        "def __init__(self, *, runtime_conformance=default):\n    pass\n", "probe.py"
    ) == []
