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


# ── TXT 축(S10-04 · #861) — 같은 registry, 다른 계약 identity ─────────────────
def test_txt_manifest_is_registered_and_never_admits_the_hwpx_axis() -> None:
    """두 매체 manifest 가 한 registry 에 살되 **서로를 admit 하지 않는다**(7축 전건 AND).

    한쪽 manifest 로 다른 매체를 admit 할 수 있으면 HWPX Plan 이 평문 materializer 로,
    또는 그 반대로 흘러갈 자리가 생긴다.
    """
    from hwpxfiller.application.execution_composition import (
        TXT_COMPOSITION_CONTRACT_ID,
        TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    )
    from hwpxfiller.external.runtime_capability import (
        admitted_txt_runtime_conformance,
        txt_runtime_capability_manifest_digest,
        txt_runtime_capability_manifest_payload,
    )

    registry, hwpx = admitted_runtime_conformance_registry()
    txt = admitted_txt_runtime_conformance()
    assert txt.conformance_status == PASS
    assert txt.runtime_capability_manifest_digest != hwpx.runtime_capability_manifest_digest
    # payload 가 단일 출처다 — manifest 축은 재타이핑이 아니라 그 payload 에서 나온다.
    payload = txt_runtime_capability_manifest_payload()
    assert txt.runtime_capability_manifest_digest == txt_runtime_capability_manifest_digest()
    assert payload["native_primitive_contract_id"] == TXT_NATIVE_PRIMITIVE_CONTRACT_ID

    def _query(manifest, *, native: str, composition: str) -> bool:
        return registry.is_admitted(
            runtime_capability_manifest_digest=(
                manifest.runtime_capability_manifest_digest
            ),
            materialization_contract_id=manifest.materialization_contract_id,
            materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
            native_primitive_contract_id=native,
            composition_contract_id=composition,
            plan_schema_version=manifest.supported_plan_schema_versions[0],
            canonical_encoding_version=(
                manifest.supported_canonical_encoding_versions[0]
            ),
        )

    assert _query(txt, native=TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                  composition=TXT_COMPOSITION_CONTRACT_ID) is True
    assert _query(hwpx, native=NATIVE_PRIMITIVE_CONTRACT_ID,
                  composition=COMPOSITION_CONTRACT_ID) is True
    # 교차는 어느 방향으로도 admit 되지 않는다.
    assert _query(txt, native=NATIVE_PRIMITIVE_CONTRACT_ID,
                  composition=COMPOSITION_CONTRACT_ID) is False
    assert _query(hwpx, native=TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
                  composition=TXT_COMPOSITION_CONTRACT_ID) is False


def test_binding_picks_the_manifest_of_the_plans_native_primitive() -> None:
    """관찰은 Plan 이 선언한 primitive 로 자기 manifest 를 고른다 — 못 고르면 fail-closed."""
    from hwpxfiller.application.execution_composition import (
        TXT_COMPOSITION_CONTRACT_ID,
        TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    )
    from hwpxfiller.external.runtime_capability import admitted_txt_runtime_conformance

    registry, hwpx = admitted_runtime_conformance_registry()
    txt = admitted_txt_runtime_conformance()
    binding = RuntimeConformanceBinding(
        registry=registry, manifest=hwpx, additional_manifests=(txt,)
    )
    assert binding.manifest_for(TXT_NATIVE_PRIMITIVE_CONTRACT_ID) is txt
    assert binding.manifest_for(NATIVE_PRIMITIVE_CONTRACT_ID) is hwpx
    assert binding.manifest_for("미등록/v1") is hwpx  # primary — 질의에서 닫힌다

    case = _build_case(_one_of_two())
    value = _plan_value_duck(case)
    txt_semantics = ExecutionContractSemantics(
        raw_record_contract_id=value.contract_semantics.raw_record_contract_id,
        source_schema_contract_id=value.contract_semantics.source_schema_contract_id,
        binding_value_contract_id=value.contract_semantics.binding_value_contract_id,
        record_validation_contract_id=(
            value.contract_semantics.record_validation_contract_id
        ),
        record_review_contract_id=value.contract_semantics.record_review_contract_id,
        document_value_resolution_contract_id=(
            value.contract_semantics.document_value_resolution_contract_id
        ),
        composition_contract_id=TXT_COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=(
            value.contract_semantics.materialization_base_contract_id
        ),
        materialization_contract_id=(
            value.contract_semantics.materialization_contract_id
        ),
    )
    txt_value = SimpleNamespace(
        contract_semantics=txt_semantics,
        plan_schema_version=value.plan_schema_version,
        canonical_encoding_version=value.canonical_encoding_version,
    )
    conformance = registry_conformance_for_plan_value(binding, txt_value)
    assert conformance.verdict == MATERIALIZER_ADMITTED
    assert (
        conformance.runtime_capability_manifest_digest
        == txt.runtime_capability_manifest_digest
    )
