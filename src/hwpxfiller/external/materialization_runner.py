"""Production materialization runner (S6-01 · #809) — Plan ref → HWPX document bytes.

SG-02(#734)가 증명해 둔 in-memory executor/verifier(:mod:`materialization_conformance`)를
production ref+store 조달로 감싸는 **유일한 production 소유자**다. 새 의미를 파생하지 않는다 —
무엇을 제거할지는 Plan 의 ``REMOVE_OPTION``, 무엇을 쓸지는 VDR 의 logical document value 가
이미 정했다(S6-1·S6-2).

경계(issue #809):
- **bytes 에서 멈춘다.** filesystem write·delivery disposition·Artifact identity 는 S6-04 의
  delivery coordinator 몫이고(S6-7), start gate/fence ordering 은 S6-02 몫이다 — 이 러너는
  그 둘이 감쌀 안쪽 함수 형태만 세운다.
- **조달은 전부 digest fail-closed.** Plan·VDR 는 :class:`MaterializationInputPort` 가 재검증
  하고, candidate bytes 는 반환값을 Plan 의 ``exact_content_digest`` 로 재해시 대조하며,
  structure 는 Plan 의 ``template_structure_digest`` 와 대조한다. resolver 가 무엇을 주든
  대조 없이는 쓰지 않는다.
- **postcondition 이 자격이다.** remove/write 호출 성공만으로 bytes 를 내지 않는다 — mutation
  후 재검사(:func:`verify_materialization_postconditions`) PASS 시에만
  :class:`MaterializedDocumentBytes` 를 내고, FAIL 은 9 실패 코드 그대로
  :class:`ConformanceFailure` 를 반환한다(S6-3·D3, output bytes 미노출).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from hwpxfiller.application.candidate_revision import blob_digest
from hwpxfiller.application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
)
from hwpxfiller.application.execution_structure import (
    ExecutionTemplateStructure,
    decode_execution_structure,
    template_structure_digest,
)
from hwpxfiller.application.generation_delivery import (
    MaterializationInput,
    MaterializationInputPort,
)
from hwpxfiller.application.record_validation import ImmutableVdrStore
from hwpxfiller.domain.fields import FillNote

from .candidate_store import CandidateObjectStore
from .materialization_conformance import (
    ConformanceFailure,
    ConformancePass,
    apply_execution_plan_in_memory,
    verify_materialization_postconditions,
    verify_structure_bytes_consistency,
)
from .qualification_store import QualificationObjectStore
from .work_template_store import AtomicWorkTemplateStateStore


class MaterializationProcurementError(Exception):
    """입력 조달이 Plan 과 대조 실패 — postcondition 9 코드가 아니라 loud 예외로 닫는다.

    postcondition 실패(:class:`ConformanceFailure`)는 「실행했더니 결과가 계약 위반」이고,
    조달 실패는 「실행할 자격이 있는 입력을 복원하지 못함」이다 — 두 층을 섞지 않는다.
    """


@dataclass(frozen=True)
class MaterializedDocumentBytes:
    """postcondition PASS 를 통과한 materialization 산출 — bytes 와 그 증거.

    ``execution_notes`` 는 채움이 「경고 후 진행」으로 처리한 완화 사실(FillNote)로, 삼키지
    않고 상위(S6-04 delivery·원장)가 record/warn 하게 나른다(confirm-or-alarm).
    """

    plan_semantic_digest: str
    validated_record_ref: str
    output_bytes: bytes
    output_digest: str
    execution_notes: tuple[FillNote, ...]


MaterializationOutcome = MaterializedDocumentBytes | ConformanceFailure


class ProductionMaterializationRunner:
    """Plan ref+VDR ref 에서 검증된 HWPX document bytes 까지 — executor/verifier 의 production 봉합.

    조달 seam 셋(input port·candidate blob resolver·structure resolver)은 생성자 주입이다 —
    S6-02 start gate 가 fence 아래에서 이 러너를 LongMaterialization 으로 호출한다.
    """

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
        """Plan 이 정한 native operation 만 수행해 bytes 를 만들고 후행조건으로 재검사한다."""
        # 1. Plan·VDR 복원 — digest 재검증·cross-bind·completeness 는 port 가 이미 진다
        #    (두 벌 판정 금지: 여기서 requirement/count 를 재조립하지 않는다).
        plan, vdr = self._input_port.resolve(materialization_input)

        # 2. candidate bytes 조달 — resolver 반환을 Plan 의 exact_content_digest 로 재해시 대조.
        wanted_blob = plan.execution_basis.template.exact_content_digest
        candidate_bytes = self._candidate_blob_resolver(wanted_blob)
        if blob_digest(candidate_bytes) != wanted_blob:
            raise MaterializationProcurementError(
                f"조달한 candidate bytes 의 digest 가 Plan 과 불일치: 기대 {wanted_blob}"
            )

        # 3. structure 조달 — Plan 이 봉인한 template_structure_digest 와 대조.
        wanted_structure = plan.execution_basis.selection.template_structure_digest
        structure = self._structure_resolver(plan)
        if template_structure_digest(structure) != wanted_structure:
            raise MaterializationProcurementError(
                f"조달한 structure 의 digest 가 Plan 과 불일치: 기대 {wanted_structure}"
            )

        # 4. P7 precheck — digest 는 각자 자신만 증명하므로 structure↔bytes 대응은 이 검사가
        #    유일하게 잇는다(봉인 시점에 structure 가 bytes 를 거짓말한 Plan 을 여기서 닫는다).
        precheck = verify_structure_bytes_consistency(
            candidate_bytes=candidate_bytes, structure=structure
        )
        if isinstance(precheck, ConformanceFailure):
            return precheck

        # 5. in-memory 실행 → 6. postcondition 재검사(자격). FAIL 은 코드 재조립 없이 그대로.
        materialized = apply_execution_plan_in_memory(
            candidate_bytes=candidate_bytes,
            ordered_operations=plan.ordered_operations,
            document_values=dict(vdr.document_values_in_order()),
        )
        verdict = verify_materialization_postconditions(
            source_bytes=candidate_bytes,
            output_bytes=materialized.output_bytes,
            plan=plan,
            structure=structure,
            vdr=vdr,
            execution_notes=materialized.notes,
        )
        if isinstance(verdict, ConformanceFailure):
            return verdict
        assert isinstance(verdict, ConformancePass)
        return MaterializedDocumentBytes(
            plan_semantic_digest=materialization_input.sealed_execution_plan_ref,
            validated_record_ref=materialization_input.validated_record_ref,
            output_bytes=materialized.output_bytes,
            output_digest=verdict.output_digest,
            execution_notes=verdict.notes,
        )


def store_backed_structure_resolver(
    *,
    work_state_store: AtomicWorkTemplateStateStore,
    qualification_store: QualificationObjectStore,
) -> Callable[[SealedExecutionPlanSemanticPayload], ExecutionTemplateStructure]:
    """Plan 의 Work/Application 사슬로 PASS Evidence 의 durable v2 projection 을 decode 한다.

    원 HWPX 를 재parse 하지 않는다(:class:`SealExecutionCaptureRunner` 와 같은 조달 경로).
    사슬이 끊긴 곳은 :class:`MaterializationProcurementError` 로 시끄럽게 닫는다 — digest
    대조는 러너가 진다(이 resolver 는 조달만 한다).
    """

    def resolve(
        plan: SealedExecutionPlanSemanticPayload,
    ) -> ExecutionTemplateStructure:
        aggregate = work_state_store.load(plan.execution_basis.work_authority_id)
        application_id = plan.execution_basis.template.template_application_id
        application = next(
            (a for a in aggregate.applications if a.application_id == application_id),
            None,
        )
        if application is None:
            raise MaterializationProcurementError(
                f"Plan 의 Application {application_id!r} 이 Work aggregate 에 없다"
            )
        evidence = qualification_store.get_evidence(application.pass_evidence_id)
        projection = evidence.structure_projection
        if projection is None:
            raise MaterializationProcurementError(
                f"PASS Evidence {application.pass_evidence_id!r} 에 structure projection 부재"
            )
        return decode_execution_structure(projection.payload)

    return resolve


def production_materialization_runner(
    root: Path,
    *,
    plan_resolver: Callable[[str], SealedExecutionPlanSemanticPayload],
    vdr_store: ImmutableVdrStore,
) -> ProductionMaterializationRunner:
    """template authority root 아래 실 store 로 러너를 결선한다(조립 편의).

    ``works``/``qualification``/``candidates`` subdir 는 :class:`SealExecutionPlanService`
    와 같은 공유 authority root 규약이다. plan_resolver·vdr_store 는 process-local 이라
    (R2 #740: durable Plan store 제거) caller 가 주입한다.
    """
    candidate_store = CandidateObjectStore(root / "candidates")
    return ProductionMaterializationRunner(
        input_port=MaterializationInputPort(
            plan_resolver=plan_resolver, vdr_store=vdr_store
        ),
        candidate_blob_resolver=lambda digest: candidate_store.get_blob(
            digest
        ).exact_bytes,
        structure_resolver=store_backed_structure_resolver(
            work_state_store=AtomicWorkTemplateStateStore(root / "works"),
            qualification_store=QualificationObjectStore(root / "qualification"),
        ),
    )


__all__ = [
    "MaterializationOutcome",
    "MaterializationProcurementError",
    "MaterializedDocumentBytes",
    "ProductionMaterializationRunner",
    "production_materialization_runner",
    "store_backed_structure_resolver",
]
