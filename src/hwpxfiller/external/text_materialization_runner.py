"""TXT materialization runner (S10-04 · #861) — Plan ref → text artifact bytes.

:class:`~hwpxfiller.external.materialization_runner.ProductionMaterializationRunner` 의 TXT
대칭물이자 TXT executor/verifier(:mod:`text_materialization_conformance`)의 **유일한 production
소유자**다. 조달 규율·단계 수·산출 타입이 HWPX 쪽과 같다 — 갈리는 것은 매체 primitive 뿐이다:

1. Plan·VDR 복원(:class:`MaterializationInputPort` — digest 재검증·cross-bind·완결성)
2. escaping 책임 확인(:func:`require_plaintext_materializer_escaping`) — 실행 전 gate
3. candidate bytes 조달 + Plan 의 ``exact_content_digest`` 로 재해시 대조
4. structure 조달 + Plan 의 ``template_structure_digest`` 로 대조
5. P7 precheck — 선언 structure 가 실제 텍스트 관찰과 id 일관
6. 2단계 실행 + 단계별 postcondition → 최종 postcondition 재검사

PASS 전건일 때만 :class:`MaterializedDocumentBytes` 를 낸다(HWPX 와 **같은 concrete class** —
delivery coordinator 가 매체를 모른 채 그대로 안착시킨다). FAIL 은 매체 중립 실패 코드 그대로
:class:`ConformanceFailure` 다.

**매체 검문이 먼저다.** Plan 이 선언한 native primitive 가 ``txt-line-primitive/v1`` 이 아니면
이 러너는 한 줄도 실행하지 않고 시끄럽게 닫는다 — HWPX Plan 을 평문 치환으로 실행하면 산출물은
zip 도 아니고 문서도 아닌 무엇이 된다.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from hwpxfiller.application.candidate_revision import blob_digest
from hwpxfiller.application.execution_composition import (
    TXT_NATIVE_PRIMITIVE_CONTRACT_ID,
    UnsupportedNativePrimitiveContract,
)
from hwpxfiller.application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
)
from hwpxfiller.application.execution_structure import (
    ExecutionTemplateStructure,
    template_structure_digest,
)
from hwpxfiller.application.generation_delivery import (
    MaterializationInput,
    MaterializationInputPort,
)
from hwpxfiller.application.record_validation import ImmutableVdrStore
from hwpxfiller.domain.field_binding import (
    ESCAPING_PLAINTEXT_MATERIALIZER,
    resolve_document_value_policy,
)

from .candidate_store import CandidateObjectStore
from .materialization_conformance_vocabulary import (
    ConformanceFailure,
    ConformancePass,
    MaterializationOutcome,
    MaterializedDocumentBytes,
)
from .materialization_runner import (
    EscapingResponsibilityError,
    MaterializationProcurementError,
    store_backed_structure_resolver,
)
from .qualification_store import QualificationObjectStore
from .text_materialization_conformance import (
    InMemoryTxtMaterialization,
    apply_txt_execution_plan_in_memory,
    verify_txt_materialization_postconditions,
    verify_txt_structure_bytes_consistency,
)
from .work_template_store import AtomicWorkTemplateStateStore


def require_plaintext_materializer_escaping(
    plan: SealedExecutionPlanSemanticPayload,
) -> None:
    """Plan 의 모든 값 정책이 escaping 을 **평문 materializer** 에 위임했는지 실행 전에 확인한다.

    평문에는 escape 문법이 없으므로 이 materializer 가 지는 escaping 은 항등(0회)이다. 그런데
    바로 그것이 이 gate 가 필요한 이유다: XML escaping 책임을 선언한 값(NATIVE_MATERIALIZER)이
    평문에 literal 로 꽂히면 ``&amp;`` 같은 pre-escaped 문자열이 그대로 붙여넣어지거나, 반대로
    평문용 값이 XML 에 들어가 escape 없이 새어 나간다. 어느 쪽도 조용히 진행하지 않는다.
    INTENTIONAL_BLANK 는 값 정책이 없다(``exact_blank_policy`` 소관) — 건너뛴다.
    """
    for requirement in plan.active_field_requirements:
        expression = requirement.get("value_expression")
        if not isinstance(expression, Mapping):
            raise EscapingResponsibilityError(
                f"requirement {requirement.get('field_id')!r} 에 value_expression 이 없다"
            )
        if expression.get("kind") == "INTENTIONAL_BLANK":
            continue
        policy = resolve_document_value_policy(
            str(expression.get("document_content_value_policy_id"))
        )
        if policy.escaping_responsibility != ESCAPING_PLAINTEXT_MATERIALIZER:
            raise EscapingResponsibilityError(
                f"값 정책 {policy.policy_id!r} 의 escaping 책임 "
                f"{policy.escaping_responsibility!r} 는 TXT materializer 소유가 아니다"
            )


class TxtMaterializationRunner:
    """Plan ref+VDR ref 에서 검증된 text artifact bytes 까지 — TXT executor/verifier 의 봉합."""

    def __init__(
        self,
        *,
        input_port: MaterializationInputPort,
        candidate_blob_resolver: Callable[[str], bytes],
        structure_resolver: Callable[
            [SealedExecutionPlanSemanticPayload], ExecutionTemplateStructure
        ],
    ) -> None:
        self._input_port = input_port
        self._candidate_blob_resolver = candidate_blob_resolver
        self._structure_resolver = structure_resolver

    def materialize(
        self, materialization_input: MaterializationInput
    ) -> MaterializationOutcome:
        """Plan 이 정한 operation 만 수행해 bytes 를 만들고 후행조건으로 재검사한다."""
        plan, vdr = self._input_port.resolve(materialization_input)

        # 0. 매체 검문 — 다른 매체의 Plan 을 평문 치환으로 실행하지 않는다(fail-closed).
        contracts = plan.execution_basis.contracts
        if contracts.native_primitive_contract_id != TXT_NATIVE_PRIMITIVE_CONTRACT_ID:
            raise UnsupportedNativePrimitiveContract(
                f"TXT materializer 가 실행할 수 없는 native primitive contract: "
                f"{contracts.native_primitive_contract_id!r}"
            )
        require_plaintext_materializer_escaping(plan)

        wanted_blob = plan.execution_basis.template.exact_content_digest
        candidate_bytes = self._candidate_blob_resolver(wanted_blob)
        if blob_digest(candidate_bytes) != wanted_blob:
            raise MaterializationProcurementError(
                f"조달한 candidate bytes 의 digest 가 Plan 과 불일치: 기대 {wanted_blob}"
            )

        wanted_structure = plan.execution_basis.selection.template_structure_digest
        structure = self._structure_resolver(plan)
        if template_structure_digest(structure) != wanted_structure:
            raise MaterializationProcurementError(
                f"조달한 structure 의 digest 가 Plan 과 불일치: 기대 {wanted_structure}"
            )

        precheck = verify_txt_structure_bytes_consistency(
            candidate_bytes=candidate_bytes, structure=structure
        )
        if isinstance(precheck, ConformanceFailure):
            return precheck

        materialized = apply_txt_execution_plan_in_memory(
            candidate_bytes=candidate_bytes,
            plan=plan,
            structure=structure,
            document_values=dict(vdr.document_values_in_order()),
        )
        if isinstance(materialized, ConformanceFailure):
            return materialized
        assert isinstance(materialized, InMemoryTxtMaterialization)
        verdict = verify_txt_materialization_postconditions(
            source_bytes=candidate_bytes,
            output_bytes=materialized.output_bytes,
            plan=plan,
            structure=structure,
            vdr=vdr,
            stage_facts=materialized.stage_facts,
        )
        if isinstance(verdict, ConformanceFailure):
            return verdict
        assert isinstance(verdict, ConformancePass)
        return MaterializedDocumentBytes(
            plan_semantic_digest=materialization_input.sealed_execution_plan_ref,
            validated_record_ref=materialization_input.validated_record_ref,
            output_bytes=materialized.output_bytes,
            output_digest=verdict.output_digest,
            # 평문 치환에는 완화(inline strip·slot 합성)가 없다 — 낼 note 가 구조적으로 0 이다.
            execution_notes=(),
        )


def txt_materialization_runner(
    root: Path,
    *,
    plan_resolver: Callable[[str], SealedExecutionPlanSemanticPayload],
    vdr_store: ImmutableVdrStore,
) -> TxtMaterializationRunner:
    """template authority root 아래 실 store 로 러너를 결선한다(HWPX 조립과 같은 규약)."""
    candidate_store = CandidateObjectStore(root / "candidates")
    return TxtMaterializationRunner(
        input_port=MaterializationInputPort(
            plan_resolver=plan_resolver, vdr_store=vdr_store
        ),
        candidate_blob_resolver=lambda digest: candidate_store.get_blob(
            digest
        ).exact_bytes,
        # structure 조달은 매체 중립이다 — PASS Evidence 의 durable projection 을 decode 할 뿐
        # 원 템플릿을 다시 읽지 않는다. 그래서 HWPX 러너의 것을 그대로 쓴다(재구현 0).
        structure_resolver=store_backed_structure_resolver(
            work_state_store=AtomicWorkTemplateStateStore(root / "works"),
            qualification_store=QualificationObjectStore(root / "qualification"),
        ),
    )


__all__ = [
    "TxtMaterializationRunner",
    "require_plaintext_materializer_escaping",
    "txt_materialization_runner",
]
