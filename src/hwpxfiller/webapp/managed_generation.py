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

완주(``DeliveryCompleted``) 직후에는 앉은 파일들을 관찰 커널(:mod:`hwpxfiller.external
.artifact_observation`)로 되읽어 기록 digest 와 대조한다 — #818 의 「안착 bytes read-back digest
재검증」 항목을 S7-01(#823 · #820 D6)이 여기서 회수한 것이고, 실패는 안착 사실을 부정하지 않는
:class:`ManagedReadBackFailed` 라는 구분된 상태로 낸다.
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
from ..application.slotless_run_bridge import (
    APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
    STRUCTURE_NOTATION_UNCOMPILED,
)
from ..domain.raw_data_record import RawDataRecordSnapshot
from ..external.candidate_store import CandidateObjectStore
from ..external.artifact_observation import (
    ArtifactObservationRefused,
    observe_delivered_artifact,
)
from ..external.delivery_coordinator import (
    DeliveredDocument,
    DeliveryCompleted,
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
from ..external.template_inspection import hwpx_structure_marker_count
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


@dataclass(frozen=True)
class ManagedReadBackFailed:
    """안착은 됐으나 되읽기 검증이 서지 않았다(S7-01 · #823 — #818 회수).

    ``delivered`` 는 여전히 유효한 사실이다: 파일들은 이미 disk 에 앉았고 이 상태는 그것을
    되돌리지도 부정하지도 않는다. 다른 것은 「앉은 것을 다시 읽어 기록과 대조했더니 어긋났다」
    는 관찰 결과뿐이라, 완주·중단 어느 쪽으로도 뭉개지 않고 구분된 상태로 낸다.
    """

    code: str
    detail: str
    failed_item_ordinal: int
    delivered: tuple[DeliveredDocument, ...]


ManagedGenerationResult = (
    DeliveryExecutionResult
    | ManagedRunRefused
    | ManagedRunCancelled
    | ManagedReadBackFailed
)


def _refuse_uncompiled_structure_notation(
    candidate_store: CandidateObjectStore,
    plan_payload: SealedExecutionPlanSemanticPayload,
) -> "ManagedRunRefused | None":
    """managed 실행이 **실제로 쓸 bytes** 에 미변환 구간 표기가 남았으면 거절한다(S8-F1 · #852).

    S8-04(#835)가 세운 같은 검문이 slotless admission 에만 살아, slot-bearing 작업은
    ``{{#항목}}`` 문단을 그대로 실은 문서를 만들 수 있었다(S8-99 감사 F-1). 다중 슬롯
    문서에서 한 슬롯만 「표기로 풀기」 하면 제품이 스스로 그 상태를 만든다.

    검문 대상은 캐시된 상태가 아니라 러너가 조달할 바로 그 Candidate blob 이다 — Plan 이
    봉인한 ``exact_content_digest`` 로 같은 store 에서 같은 bytes 를 집는다. 판정 수치는
    스캐너 단일 출처 파생(:func:`~hwpxfiller.external.template_inspection
    .hwpx_structure_marker_count`)이고 여기서 다시 세지 않는다. 거절 코드·문안은 slotless
    쪽과 같은 것을 쓴다 — 같은 차단을 같은 문장으로.

    조달 자체가 끊긴 경우(blob 부재)는 종전대로 store 예외가 그대로 올라간다 — 러너가
    같은 digest 로 같은 실패를 낼 자리이고 그 loud 계약을 이 검문이 가로채지 않는다.
    읽어 온 bytes 를 **열지 못하면** 「마커 0」 으로 접지 않고 무결성 오류로 닫는다
    (fail-closed): qualification 이 이미 parse 를 증명한 bytes 라 여기서 실패했다는 것은
    그때 본 것과 다르다는 뜻이고, 못 읽은 문서를 통과시키면 검문이 있으나 마나다.
    """
    wanted_blob = plan_payload.execution_basis.template.exact_content_digest
    exact_bytes = candidate_store.get_blob(wanted_blob).exact_bytes
    try:
        marker_n = hwpx_structure_marker_count(exact_bytes)
    except Exception as exc:  # noqa: BLE001 — 열기·파싱 실패류를 제품 상태로 번역(raw 누출 금지)
        return ManagedRunRefused(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            f"실행할 Candidate bytes 를 읽을 수 없어 구간 표기를 확인하지 못했다: {exc}",
        )
    if marker_n > 0:
        return ManagedRunRefused(
            STRUCTURE_NOTATION_UNCOMPILED,
            f"실행할 템플릿에 미변환 구간 표기가 {marker_n}건 남아 있다",
        )
    return None


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
    # 2b. 실행이 쓸 bytes 가 확정된 직후의 admission 검문(S8-F1 · #852) — 여기는 아직
    #     write 0 이라(안착은 4단계) 거절이 filesystem 을 건드리지 않는다.
    notation_refusal = _refuse_uncompiled_structure_notation(
        candidate_store, plan_payload
    )
    if notation_refusal is not None:
        return notation_refusal
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
    delivery = deliver_current_documents(
        resolved=resolved_delivery, ordered_outcomes=outcomes
    )
    if not isinstance(delivery, DeliveryCompleted):
        # 부분 안착(``DeliveryAborted``)의 되읽기는 이 슬라이스의 범위 밖이다(#818 잔여) —
        # 조용히 절반만 검증하지 않고 멈춘 사실 그대로 올려보낸다.
        return delivery

    # 5. 되읽기 검증(#820 D6) — 앉은 파일을 다시 읽어 기록 digest 와 대조한다. 반환된 bytes·
    #    package 는 판정에만 쓰고 버린다(보존·캐시 없음 — S7-03 이 필요할 때 다시 관찰한다).
    for doc in delivery.delivered:
        observed = observe_delivered_artifact(
            absolute_path=doc.absolute_path, recorded_digest=doc.output_digest
        )
        if isinstance(observed, ArtifactObservationRefused):
            return ManagedReadBackFailed(
                code=observed.code,
                detail=observed.detail,
                failed_item_ordinal=doc.item_ordinal,
                delivered=delivery.delivered,
            )
    return delivery


__all__ = [
    "RECORD_VALIDATION_BLOCKED",
    "ManagedGenerationResult",
    "ManagedReadBackFailed",
    "ManagedRunCancelled",
    "ManagedRunRefused",
    "run_managed_generation",
]
