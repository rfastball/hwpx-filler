"""shipping seal policy 해석 — raw request intent + current shipping default → ResolvedSealPolicy.

이 모듈은 **순수**하다: store·fence·wall-clock·HWPX·native 를 모른다. current shipping build 의
default contract 집합을 이 한 곳에서 소유하고(shipping-default 단일 출처), raw
:class:`SealExecutionPlanCommand` intent 를 exact :class:`ResolvedSealPolicy` 로 canonicalize 한다.

규율(:class:`ShippingSealPolicyResolver` 계약):

- **EXACT selector 는 그대로 반영한다** — 요청이 명시한 값을 policy 에 그대로 싣는다. 요청 A /
  policy B 라는 모순 쌍을 만들지 않는다(불일치는 S5-10 ``require_exact_selector_consistency`` 가
  durable ledger 이전에 시끄럽게 잡는다).
- **AUTO 는 current shipping default 로 canonicalize 한다** — 생략된 selector 는 지금 출하 build 의
  기본 contract 로 확정한다.
- **fail-closed** — unknown/latest fallback 이 없다. 여기서 정하는 것은 오직 (a) 요청이 준 EXACT
  값, (b) 이 모듈이 소유한 shipping default(매체별 composition 축 포함) 뿐이다. store 를 읽지
  않는다 — ``observed`` 에서 읽는 것은 **Qualification Profile identity 하나**이고, 그것이
  composition/native-primitive/theorem 축을 가른다(S10-04 · #861, 아래 표). 같은 매체 안에서는
  여전히 Work-불변이다.

``execution_base_kind`` 은 요청에서 그대로 echo 한다 — S5 v1 admitted base 검증은 capture/compile
층이 지고(``APPLIED_TEMPLATE_CANDIDATE`` 이 아니면 policy block/ context error), 여기서는 요청과
policy 가 어긋나지 않게 요청 값을 그대로 싣는다.
"""

from __future__ import annotations

from hwpxfiller.application.execution_capture import (
    MATERIALIZATION_BASE_CONTRACT_ID,
    ResolvedSealPolicy,
)
from hwpxfiller.application.execution_compilation import EXECUTION_SEMANTICS_CONTRACT
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    THEOREM_EVIDENCE_TXT_V1,
    THEOREM_EVIDENCE_V1,
    TXT_COMPOSITION_CONTRACT_ID,
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    theorem_evidence_digest,
)
from hwpxfiller.application.execution_structure import (
    TXT_EXECUTION_QUALIFICATION_PROFILE_ID,
)
from hwpxfiller.application.seal_execution_plan import (
    SUPPORTED_PLAN_SCHEMAS,
    SealExecutionPlanCommand,
    WorkExecutionSummary,
)
from hwpxfiller.application.stored_execution_plan import (
    RequestedExact,
    RequestedVersionSelector,
)
from hwpxfiller.domain.canonical_execution_encoding import CANONICAL_ENCODING_VERSION
from hwpxfiller.domain.field_binding import (
    BINDING_VALUE_VERSION,
    DOCUMENT_CONTENT_VALUE_POLICY_VERSION,
)
from hwpxfiller.domain.raw_data_record import (
    RAW_RECORD_CONTRACT_ID,
    RECORD_REVIEW_CONTRACT_ID,
)
from hwpxfiller.application.record_validation import RECORD_VALIDATION_CONTRACT_ID

# ─── shipping-default 단일 출처 ──────────────────────────────────────────────────────
# 이 build 가 resolve 하는 policy 의 버전 label(의미가 바뀌면 새 label — 같은 label 의미 수정 금지).
SHIPPING_POLICY_RESOLUTION_VERSION = "policy/v1"

# current shipping default plan schema — AUTO 가 canonicalize 되는 값(latest fallback 없음).
SHIPPING_PLAN_SCHEMA_VERSION = SUPPORTED_PLAN_SCHEMAS[0]

# S6 materialization contract — 아직 미출하다. 다른 정본이 없어 이 모듈이 default 를 소유한다.
SHIPPING_MATERIALIZATION_CONTRACT_ID = "materialization/v1"

# ─── 매체가 가르는 유일한 축(S10-04 · #861) ────────────────────────────────────────────
# composition/native-primitive 는 **매체의 사실**이다: HWPX 는 bookmark region 제거·field marker
# write, TXT 는 줄 제거·평문 삽입. 그래서 이 셋만 관찰된 Qualification Profile 로 갈린다. 나머지
# contract(값 정책·record·plan schema·encoding)는 매체 중립이라 계속 build 전역 default 다.
#
# 이것이 "``observed`` 는 seam 대칭용이고 shipping default 는 Work-불변"이라는 종전 서술의 유일한
# 예외다 — Work 가 아니라 **Profile identity** 로 갈리고, 같은 매체 안에서는 여전히 불변이다.
# 매체를 policy 밖에서 추측하면(예: materializer 가 Plan 을 열어 보고) 봉인된 계약과 실제 실행이
# 갈리므로, 갈림은 policy 한 곳에서 명시로 일어난다.
_MEDIA_COMPOSITION_AXIS: "dict[str, tuple[str, str, str]]" = {
    TXT_EXECUTION_QUALIFICATION_PROFILE_ID: (
        TXT_COMPOSITION_CONTRACT_ID,
        TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
        theorem_evidence_digest(THEOREM_EVIDENCE_TXT_V1),
    ),
}

_DEFAULT_COMPOSITION_AXIS = (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    theorem_evidence_digest(THEOREM_EVIDENCE_V1),
)


def _selected(selector: RequestedVersionSelector, default: str) -> str:
    """EXACT selector 는 그 값을 그대로, 그 외(AUTO)는 shipping default 를 canonicalize 한다."""
    if isinstance(selector, RequestedExact):
        return selector.value
    return default


def resolve_shipping_policy(
    command: SealExecutionPlanCommand, observed: WorkExecutionSummary
) -> ResolvedSealPolicy:
    """raw intent + current shipping default → exact ResolvedSealPolicy(순수, fail-closed).

    EXACT selector(execution semantic contract·plan schema·canonical encoding)는 그대로 반영하고,
    나머지 contract 집합은 이 build 의 shipping default 로 확정한다. ``execution_base_kind`` 은
    요청에서 echo 한다(요청/policy 모순 금지). unknown 을 latest 로 풀지 않는다.
    """
    composition_id, native_primitive_id, theorem_digest = _MEDIA_COMPOSITION_AXIS.get(
        observed.qualification_profile_id, _DEFAULT_COMPOSITION_AXIS
    )
    return ResolvedSealPolicy(
        policy_resolution_version=SHIPPING_POLICY_RESOLUTION_VERSION,
        execution_base_kind=command.requested_execution_base_kind,
        execution_semantic_contract_id=_selected(
            command.requested_execution_semantic_contract, EXECUTION_SEMANTICS_CONTRACT
        ),
        binding_value_contract_id=BINDING_VALUE_VERSION,
        raw_record_contract_id=RAW_RECORD_CONTRACT_ID,
        document_value_resolution_contract_id=DOCUMENT_CONTENT_VALUE_POLICY_VERSION,
        record_validation_contract_id=RECORD_VALIDATION_CONTRACT_ID,
        record_review_contract_id=RECORD_REVIEW_CONTRACT_ID,
        composition_contract_id=composition_id,
        native_primitive_contract_id=native_primitive_id,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        composition_theorem_evidence_manifest_digest=theorem_digest,
        materialization_contract_id=SHIPPING_MATERIALIZATION_CONTRACT_ID,
        plan_schema_version=_selected(
            command.requested_plan_schema, SHIPPING_PLAN_SCHEMA_VERSION
        ),
        canonical_encoding_version=_selected(
            command.requested_canonical_encoding, CANONICAL_ENCODING_VERSION
        ),
    )


__all__ = [
    "SHIPPING_POLICY_RESOLUTION_VERSION",
    "SHIPPING_PLAN_SCHEMA_VERSION",
    "SHIPPING_MATERIALIZATION_CONTRACT_ID",
    "resolve_shipping_policy",
]
