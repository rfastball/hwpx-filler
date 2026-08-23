"""S6-03(#810) shipping runtime capability manifest 발행과 정식 주입 경로.

발행되는 PASS manifest 의 모든 축이 production materializer 가 실제 import 하는 계약 상수에서
파생되고, 실제 봉인 Plan(REAL compiler 산출)이 그 manifest 로 admit 됨을 증명한다. 전역
DEFAULT registry 는 계속 비어 있다(D4 — theorem/runtime disjoint 유지).
"""

from __future__ import annotations

from types import SimpleNamespace

from hwpxfiller.application.execution_capture import MATERIALIZATION_BASE_CONTRACT_ID
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    DEFAULT_RUNTIME_CONFORMANCE_REGISTRY,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    PASS,
)
from hwpxfiller.application.execution_contract_semantics import ExecutionContractSemantics
from hwpxfiller.application.fresh_execution_observation import (
    MATERIALIZER_ADMITTED,
    MATERIALIZER_NOT_ADMITTED,
)
from hwpxfiller.application.generation_delivery import (
    MANAGED_RUN_STARTABLE,
    evaluate_managed_run_admission,
)
from hwpxfiller.application.shipping_seal_policy import (
    SHIPPING_MATERIALIZATION_CONTRACT_ID,
    SHIPPING_PLAN_SCHEMA_VERSION,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    canonical_execution_digest,
)
from hwpxfiller.external.runtime_capability import (
    admitted_runtime_conformance_registry,
    runtime_capability_manifest_digest,
    runtime_capability_manifest_payload,
    shipping_runtime_conformance_manifest,
)
from hwpxfiller.webapp.seal_execution_plan_product import (
    RuntimeConformanceBinding,
    registry_conformance_for_plan_value,
)

from tests._materialization_case import _build_case, _one_of_two


# ═══ manifest 발행 — 전 축이 실계약 상수에서 파생된다 ═══════════════════════════════════
def test_manifest_axes_derive_from_real_contract_constants() -> None:
    manifest = shipping_runtime_conformance_manifest()
    assert manifest.conformance_status == PASS
    assert manifest.materialization_contract_id == SHIPPING_MATERIALIZATION_CONTRACT_ID
    assert manifest.materialization_base_contract_id == MATERIALIZATION_BASE_CONTRACT_ID
    assert manifest.native_primitive_contract_id == NATIVE_PRIMITIVE_CONTRACT_ID
    assert COMPOSITION_CONTRACT_ID in manifest.admitted_composition_contract_ids
    assert SHIPPING_PLAN_SCHEMA_VERSION in manifest.supported_plan_schema_versions
    assert CANONICAL_ENCODING_VERSION in manifest.supported_canonical_encoding_versions


def test_capability_digest_is_payload_content_address() -> None:
    payload = runtime_capability_manifest_payload()
    assert runtime_capability_manifest_digest() == canonical_execution_digest(payload)
    manifest = shipping_runtime_conformance_manifest()
    assert manifest.runtime_capability_manifest_digest == canonical_execution_digest(payload)


def test_minting_does_not_touch_default_global_registry() -> None:
    # D4: 전역 registry 공백은 S6 가 철거하지 않는 계약이다 — 발행은 자기 인스턴스에만 한다.
    admitted_runtime_conformance_registry()
    assert not DEFAULT_RUNTIME_CONFORMANCE_REGISTRY.is_admitted(
        runtime_capability_manifest_digest=runtime_capability_manifest_digest(),
        materialization_contract_id=SHIPPING_MATERIALIZATION_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        plan_schema_version=SHIPPING_PLAN_SCHEMA_VERSION,
        canonical_encoding_version=CANONICAL_ENCODING_VERSION,
    )


# ═══ 실제 봉인 Plan 이 admit 된다 — dead branch(MANAGED_RUN_STARTABLE_IN_S6) 소생 ═══════
def test_admitted_registry_makes_a_real_sealed_plan_startable() -> None:
    case = _build_case(_one_of_two())  # REAL compiler 가 봉인한 Plan
    registry, manifest = admitted_runtime_conformance_registry()
    admission = evaluate_managed_run_admission(
        runtime_registry=registry,
        sealed_execution_plan=case.plan,
        runtime_capability_manifest_digest=manifest.runtime_capability_manifest_digest,
    )
    assert admission.materialization_startable is True
    assert admission.status == MANAGED_RUN_STARTABLE  # "MANAGED_RUN_STARTABLE_IN_S6"


def test_foreign_capability_digest_is_not_startable() -> None:
    # 발행된 digest 가 아니면 같은 registry 라도 admit 되지 않는다(위조 digest fail-closed).
    case = _build_case(_one_of_two())
    registry, _manifest = admitted_runtime_conformance_registry()
    admission = evaluate_managed_run_admission(
        runtime_registry=registry,
        sealed_execution_plan=case.plan,
        runtime_capability_manifest_digest="sha256:" + "0" * 64,
    )
    assert admission.materialization_startable is False


# ═══ Plan value 파생 registry 판정(웹 관찰 축의 정식 주입 경로) ═══════════════════════════
def _plan_value_duck(case, **over) -> SimpleNamespace:
    semantics = ExecutionContractSemantics.from_contract_set(
        case.plan.execution_basis.contracts
    )
    kw = dict(
        contract_semantics=semantics,
        plan_schema_version=case.plan.plan_schema_version,
        canonical_encoding_version=case.plan.canonical_encoding_version,
    )
    kw.update(over)
    return SimpleNamespace(**kw)


def test_registry_conformance_admits_matching_plan_value() -> None:
    case = _build_case(_one_of_two())
    registry, manifest = admitted_runtime_conformance_registry()
    binding = RuntimeConformanceBinding(registry=registry, manifest=manifest)
    conformance = registry_conformance_for_plan_value(binding, _plan_value_duck(case))
    assert conformance.verdict == MATERIALIZER_ADMITTED
    assert conformance.plan_schema_supported is True
    assert conformance.canonical_encoding_supported is True
    assert (
        conformance.runtime_capability_manifest_digest
        == manifest.runtime_capability_manifest_digest
    )


def test_registry_conformance_rejects_unsupported_schema_per_axis() -> None:
    # NOT_ADMITTED 이면 digest 를 싣지 않고, 어긋난 축(plan schema)이 bool 로 구분된다 —
    # 링2 가 사유를 재조립하지 않고 admission reason 으로 이을 수 있는 형태다.
    case = _build_case(_one_of_two())
    registry, manifest = admitted_runtime_conformance_registry()
    binding = RuntimeConformanceBinding(registry=registry, manifest=manifest)
    conformance = registry_conformance_for_plan_value(
        binding, _plan_value_duck(case, plan_schema_version="hwpx-execution-plan/v999")
    )
    assert conformance.verdict == MATERIALIZER_NOT_ADMITTED
    assert conformance.plan_schema_supported is False
    assert conformance.canonical_encoding_supported is True
    assert conformance.runtime_capability_manifest_digest is None
