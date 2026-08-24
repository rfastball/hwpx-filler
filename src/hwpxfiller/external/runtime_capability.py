"""shipping runtime materializer 의 capability manifest 발행 (S6-03 · #810).

`RuntimeMaterializerConformanceRegistry` 는 S5(SG-02)가 선언만 하고 비워 둔 admission seam 이다 —
이 모듈이 그 registry 에 등록할 **첫 PASS manifest 의 발행자**다. D4(#807): 이 manifest 는
theorem evidence 와 끝까지 다른 identity 다 — Plan semantic digest 에 절대 섞이지 않고,
`DEFAULT_RUNTIME_CONFORMANCE_REGISTRY`(전역)는 계속 비워 둔다(repo-contract 3곳이 강제).
composition root 가 :func:`admitted_runtime_conformance_registry` 로 **자기 registry 인스턴스**를
만들어 주입하는 것이 정식 주입 경로다(`runtime_conformance=` kwarg 우회 금지 계약 유지).

PASS 의 근거는 선언이 아니라 파생이다: manifest 의 모든 축은 production materializer
(:mod:`materialization_runner` · :mod:`materialization_conformance`)가 **실제로 import 하는 계약
상수**에서만 파생되고, 그 계약들의 actual 준수는 같은 커밋의 conformance corpus(매 병합 게이트)가
검증한다. 어느 축이든 드리프트하면 registry 의 7축 전건 AND 매칭이 NOT_ADMITTED 로 fail-closed
된다 — 값을 손으로 재타이핑해 위조할 자리가 없다.
"""

from __future__ import annotations

from typing import Any

from hwpxfiller.application.execution_capture import MATERIALIZATION_BASE_CONTRACT_ID
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    PASS,
    TXT_COMPOSITION_CONTRACT_ID,
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    RuntimeMaterializerConformanceManifest,
    RuntimeMaterializerConformanceRegistry,
)
from hwpxfiller.application.seal_execution_plan import SUPPORTED_PLAN_SCHEMAS
from hwpxfiller.application.shipping_seal_policy import (
    SHIPPING_MATERIALIZATION_CONTRACT_ID,
)
from hwpxfiller.domain.canonical_execution_encoding import (
    CANONICAL_ENCODING_VERSION,
    canonical_execution_digest,
)

from .materialization_conformance import CONFORMANCE_CONTRACT_ID
from .text_materialization_conformance import (
    TXT_CONFORMANCE_CONTRACT_ID,
)

RUNTIME_CAPABILITY_MANIFEST_SCHEMA = "hwpx-runtime-capability-manifest/v1"

#: TXT materializer 의 capability manifest schema(S10-04 · #861) — HWPX 와 **다른 이름**이다.
#: 같은 이름 아래 두 매체의 capability 를 실으면 한쪽 드리프트가 다른 쪽 admission 을 흔든다.
TXT_RUNTIME_CAPABILITY_MANIFEST_SCHEMA = "txt-runtime-capability-manifest/v1"

# capability 의 주체 — 이 러너가 executor/verifier 의 유일한 production 소유자다
# (tests/repo_contract/test_materialization_port_gate.py 가 강제).
_MATERIALIZER_IDENTITY = (
    "hwpxfiller.external.materialization_runner.ProductionMaterializationRunner"
)

_TXT_MATERIALIZER_IDENTITY = (
    "hwpxfiller.external.text_materialization_runner.TxtMaterializationRunner"
)


def runtime_capability_manifest_payload() -> dict[str, Any]:
    """runtime capability manifest 의 canonical payload — 전 필드가 실계약 상수에서 파생된다.

    이 payload 의 content digest 가 `runtime_capability_manifest_digest` 다. 저장소 어디에도
    이 digest 의 다른 발행자가 없다 — S5 가 비워 둔 자리를 이 함수가 처음 채운다.
    """
    return {
        "capability_manifest_schema": RUNTIME_CAPABILITY_MANIFEST_SCHEMA,
        "materializer": _MATERIALIZER_IDENTITY,
        "conformance_contract_id": CONFORMANCE_CONTRACT_ID,
        "native_primitive_contract_id": NATIVE_PRIMITIVE_CONTRACT_ID,
        "materialization_contract_id": SHIPPING_MATERIALIZATION_CONTRACT_ID,
        "materialization_base_contract_id": MATERIALIZATION_BASE_CONTRACT_ID,
        "admitted_composition_contract_ids": sorted((COMPOSITION_CONTRACT_ID,)),
        "supported_plan_schema_versions": sorted(SUPPORTED_PLAN_SCHEMAS),
        "supported_canonical_encoding_versions": sorted((CANONICAL_ENCODING_VERSION,)),
    }


def runtime_capability_manifest_digest() -> str:
    return canonical_execution_digest(runtime_capability_manifest_payload())


def shipping_runtime_conformance_manifest() -> RuntimeMaterializerConformanceManifest:
    """payload 의 축을 그대로 옮긴 PASS manifest — 재타이핑 없이 payload 가 단일 출처다."""
    payload = runtime_capability_manifest_payload()
    return RuntimeMaterializerConformanceManifest(
        runtime_capability_manifest_digest=canonical_execution_digest(payload),
        materialization_contract_id=payload["materialization_contract_id"],
        materialization_base_contract_id=payload["materialization_base_contract_id"],
        native_primitive_contract_id=payload["native_primitive_contract_id"],
        admitted_composition_contract_ids=tuple(
            payload["admitted_composition_contract_ids"]
        ),
        supported_plan_schema_versions=tuple(payload["supported_plan_schema_versions"]),
        supported_canonical_encoding_versions=tuple(
            payload["supported_canonical_encoding_versions"]
        ),
        conformance_status=PASS,
    )


def txt_runtime_capability_manifest_payload() -> dict[str, Any]:
    """TXT materializer 의 capability payload — HWPX 와 같은 규율, 다른 계약 상수(S10-04 · #861).

    실런타임 축(WebView2·설치 Chrome 같은)이 없다 — 평문 물질화는 순수 문자열 연산이라 이
    manifest 가 담는 것은 계약 identity 뿐이고, 그 계약들의 actual 준수는 같은 커밋의 TXT
    conformance 스위트가 검증한다. 값은 전부 실제 import 하는 상수에서 파생한다(재타이핑 0).
    """
    return {
        "capability_manifest_schema": TXT_RUNTIME_CAPABILITY_MANIFEST_SCHEMA,
        "materializer": _TXT_MATERIALIZER_IDENTITY,
        "conformance_contract_id": TXT_CONFORMANCE_CONTRACT_ID,
        "native_primitive_contract_id": TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
        "materialization_contract_id": SHIPPING_MATERIALIZATION_CONTRACT_ID,
        "materialization_base_contract_id": MATERIALIZATION_BASE_CONTRACT_ID,
        "admitted_composition_contract_ids": sorted((TXT_COMPOSITION_CONTRACT_ID,)),
        "supported_plan_schema_versions": sorted(SUPPORTED_PLAN_SCHEMAS),
        "supported_canonical_encoding_versions": sorted((CANONICAL_ENCODING_VERSION,)),
    }


def txt_runtime_capability_manifest_digest() -> str:
    return canonical_execution_digest(txt_runtime_capability_manifest_payload())


def txt_runtime_conformance_manifest() -> RuntimeMaterializerConformanceManifest:
    """TXT payload 의 축을 그대로 옮긴 PASS manifest — payload 가 단일 출처다."""
    payload = txt_runtime_capability_manifest_payload()
    return RuntimeMaterializerConformanceManifest(
        runtime_capability_manifest_digest=canonical_execution_digest(payload),
        materialization_contract_id=payload["materialization_contract_id"],
        materialization_base_contract_id=payload["materialization_base_contract_id"],
        native_primitive_contract_id=payload["native_primitive_contract_id"],
        admitted_composition_contract_ids=tuple(
            payload["admitted_composition_contract_ids"]
        ),
        supported_plan_schema_versions=tuple(payload["supported_plan_schema_versions"]),
        supported_canonical_encoding_versions=tuple(
            payload["supported_canonical_encoding_versions"]
        ),
        conformance_status=PASS,
    )


def admitted_runtime_conformance_registry() -> (
    tuple[RuntimeMaterializerConformanceRegistry, RuntimeMaterializerConformanceManifest]
):
    """정식 주입 경로의 조립 — 새 registry 인스턴스에 shipping PASS manifest 를 등록해 돌려준다.

    전역 `DEFAULT_RUNTIME_CONFORMANCE_REGISTRY` 를 채우지 않는다 — 그 공백은 theorem/runtime
    disjoint 의 repo-contract 이고 S6 는 철거하지 않는다(#807 D4).

    S10-04(#861): registry 에는 **두 매체의 manifest 가 함께** 등록된다(admission 은 7축 전건
    AND 라 서로를 admit 하지 못한다). 반환 두 번째 값은 종전대로 HWPX manifest 다 — TXT 축은
    :func:`admitted_txt_runtime_conformance` 가 따로 낸다(기존 호출부 의미 무변경).
    """
    registry = RuntimeMaterializerConformanceRegistry()
    manifest = shipping_runtime_conformance_manifest()
    registry.register(manifest)
    registry.register(txt_runtime_conformance_manifest())
    return registry, manifest


def admitted_txt_runtime_conformance() -> RuntimeMaterializerConformanceManifest:
    """TXT 축의 shipping PASS manifest(같은 registry 에 이미 등록된 그것)."""
    return txt_runtime_conformance_manifest()


__all__ = [
    "RUNTIME_CAPABILITY_MANIFEST_SCHEMA",
    "TXT_RUNTIME_CAPABILITY_MANIFEST_SCHEMA",
    "admitted_runtime_conformance_registry",
    "admitted_txt_runtime_conformance",
    "runtime_capability_manifest_digest",
    "runtime_capability_manifest_payload",
    "shipping_runtime_conformance_manifest",
    "txt_runtime_capability_manifest_digest",
    "txt_runtime_capability_manifest_payload",
    "txt_runtime_conformance_manifest",
]
