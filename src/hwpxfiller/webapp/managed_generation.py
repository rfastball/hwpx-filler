"""Managed 생성 파이프라인 (S6-05 · #812) — sealed payload → VDR → start gate → delivery.

legacy generator 를 한 번도 부르지 않는 managed HWPX 실행의 본체다(S6-9). 이 모듈은 판정을
만들지 않는다 — 봉인은 payload 가, record 자격은 :func:`validate_data_record_against_plan` 이,
시작 자격은 start gate(pin 4 + runtime admission)가, 안착은 delivery coordinator 가 이미
소유한 판정을 **순서대로 이어 붙일 뿐**이다(S6-10). filesystem 에 닿는 것은 coordinator 뿐이고,
어느 갈래의 실패도 write 0 이거나(사전 게이트·취소) 항목별 원자다(coordinator 계약).

record ↔ delivery item 의 짝은 위치다: caller 가 넘긴 raw snapshot 순서 = VDR 순서 =
materialization 순서 = ``resolved_delivery.ordered_items`` 순서(enumerate ordinal). 그 순서
일치는 delivery 준비(:func:`resolve_current_generation_delivery`)와 이 호출이 **같은 record
투영**에서 나왔다는 caller 의 전제이고, 수 불일치는 coordinator 가 loud 하게 닫는다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..application.execution_composition import (
    RuntimeMaterializerConformanceRegistry,
)
from ..application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
    plan_semantic_digest,
)
from ..application.generation_delivery import (
    CurrentResolvedDelivery,
    MaterializationInput,
    MaterializationInputPort,
)
from ..application.record_validation import (
    ImmutableVdrStore,
    RecordValidationBlocked,
    ValidatedDataRecord,
    validate_data_record_against_plan,
)
from ..domain.raw_data_record import RawDataRecordSnapshot
from ..external.candidate_store import CandidateObjectStore
from ..external.delivery_coordinator import (
    DeliveryExecutionResult,
    deliver_current_documents,
)
from ..external.materialization_runner import ProductionMaterializationRunner
from ..external.materialization_start_gate import (
    CurrentBasisDigestReader,
    StartMaterializationResult,
    start_materialization,
)
from ..external.materialization_runner import store_backed_structure_resolver
from ..external.qualification_store import QualificationObjectStore
from ..external.work_template_store import AtomicWorkTemplateStateStore

# record 검증 거절의 재진술 코드 — UI 검증(resolve/record 준비)이 이미 통과한 뒤라, 여기서
# 나면 준비와 실행 사이에 무언가 움직였다는 뜻이다(조용히 진행하지 않는다).
RECORD_VALIDATION_BLOCKED = "RECORD_VALIDATION_BLOCKED"


@dataclass(frozen=True)
class ManagedRunRefused:
    """실행 전 거절 — write 0, 사유는 상류 판정의 재진술이다."""

    code: str
    detail: str


@dataclass(frozen=True)
class ManagedRunCancelled:
    """record 경계에서 취소 — delivery 전이라 write 0(legacy 의 부분 유지와 다름을 명시)."""

    attempted: int
    total: int


ManagedGenerationResult = DeliveryExecutionResult | ManagedRunRefused | ManagedRunCancelled


def run_managed_generation(
    *,
    root: Path,
    workspace_instance_id: str,
    work_authority_id: str,
    plan_payload: SealedExecutionPlanSemanticPayload,
    ordered_raw_snapshots: Sequence[RawDataRecordSnapshot],
    resolved_delivery: CurrentResolvedDelivery,
    validated_at: str,
    runtime_registry: RuntimeMaterializerConformanceRegistry,
    runtime_capability_manifest_digest: str,
    current_basis_digest_reader: CurrentBasisDigestReader,
    cancel_requested: Callable[[], bool] = lambda: False,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> ManagedGenerationResult:
    """봉인 payload 가 정한 것만 수행해 record 들을 bytes 로 만들고 disposition 대로 앉힌다."""
    # 1. VDR 조달 — run-local store(durable 아님, S5-12 비범위 유지). UI 준비가 이미 통과한
    #    뒤라 여기서의 거절은 준비↔실행 사이의 이동이다 — fallback 없이 재진술로 닫는다.
    vdr_store = ImmutableVdrStore()
    vdr_refs: list[str] = []
    for ordinal, snapshot in enumerate(ordered_raw_snapshots):
        validated = validate_data_record_against_plan(
            plan=plan_payload, snapshot=snapshot, validated_at=validated_at
        )
        if isinstance(validated, ValidatedDataRecord):
            vdr_refs.append(vdr_store.put(validated))
            continue
        if isinstance(validated, RecordValidationBlocked):
            codes = ", ".join(sorted({blocker.code for blocker in validated.blockers}))
            return ManagedRunRefused(
                RECORD_VALIDATION_BLOCKED,
                f"record {ordinal} 의 검증이 닫히지 않았다: {codes}",
            )
        return ManagedRunRefused(validated.code, validated.detail)

    # 2. 러너 조립 — payload 하나만 digest 대조로 내주는 process-local resolver(위조 ref 거절).
    plan_digest = plan_semantic_digest(plan_payload)

    def resolve_plan(ref: str) -> SealedExecutionPlanSemanticPayload:
        if ref != plan_digest:
            raise KeyError(f"미지의 Plan ref: {ref!r}")
        return plan_payload

    input_port = MaterializationInputPort(
        plan_resolver=resolve_plan, vdr_store=vdr_store
    )
    candidate_store = CandidateObjectStore(root / "candidates")
    runner = ProductionMaterializationRunner(
        input_port=input_port,
        candidate_blob_resolver=lambda digest: candidate_store.get_blob(
            digest
        ).exact_bytes,
        structure_resolver=store_backed_structure_resolver(
            work_state_store=AtomicWorkTemplateStateStore(root / "works"),
            qualification_store=QualificationObjectStore(root / "qualification"),
        ),
    )

    # 3. record 당 start gate 1회 — pin 은 짧고(fence 아래 대조 4), LongMaterialization 은
    #    fence 밖이다. 취소는 record 경계에서만 읽는다(항목 중간 취소 없음 — 원자성 유지).
    total = len(vdr_refs)
    outcomes: list[StartMaterializationResult] = []
    for ordinal, vdr_ref in enumerate(vdr_refs):
        if cancel_requested():
            return ManagedRunCancelled(attempted=ordinal, total=total)
        outcome = start_materialization(
            workspace_instance_id=workspace_instance_id,
            work_authority_id=work_authority_id,
            materialization_input=MaterializationInput(
                sealed_execution_plan_ref=plan_digest, validated_record_ref=vdr_ref
            ),
            input_port=input_port,
            runner=runner,
            runtime_registry=runtime_registry,
            runtime_capability_manifest_digest=runtime_capability_manifest_digest,
            current_basis_digest_reader=current_basis_digest_reader,
        )
        outcomes.append(outcome)
        if on_progress is not None:
            on_progress(ordinal + 1, total)

    # 4. 안착 — 전건 PASS 게이트·항목별 원자는 coordinator 계약(S6-8).
    return deliver_current_documents(
        resolved=resolved_delivery, ordered_outcomes=outcomes
    )


__all__ = [
    "RECORD_VALIDATION_BLOCKED",
    "ManagedGenerationResult",
    "ManagedRunCancelled",
    "ManagedRunRefused",
    "run_managed_generation",
]
