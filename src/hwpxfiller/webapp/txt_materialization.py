"""TXT 물질화 서비스 (S10-04 · #861) — 봉인 → VDR → start gate → text artifact bytes.

작업대의 복사가 **실제 문서**를 복사하게 만드는 자리다. S10-03 까지 slot-bearing TXT 의 복사는
차단돼 있었다: 화면이 그리던 것은 「고른 내용만 보이게 접은 **투영**」이고 투영은 실행 권위가
아니기 때문이다. 이 서비스가 그 투영 자리에 **Sealed Plan 이 정한 물질화 산출**을 세운다.

`external/managed_generation.run_managed_generation` 과 같은 순서를 밟되 delivery 를 하지 않는다 —
TXT 의 착지점은 filesystem 이 아니라 클립보드이고, 새 배달 표면은 이 슬라이스의 범위 밖이다
(#861 제외 항목). 그래서 여기서 멈추는 것은 **bytes** 다.

**seal 트리거는 복사 시점의 내부 pin 이다.** 사용자에게 「봉인」 동사를 노출하지 않는다
(:mod:`hwpxfiller.application.automatic_seal_orchestration` 의 규율) — 복사 직전에 현재 basis 로
봉인을 확보하고, 확보하지 못하면 그 사유가 그대로 **복사 차단 사유**로 재진술된다. 조용히
투영을 대신 내보내는 경로는 만들지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from ..application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
    plan_semantic_digest,
)
from ..application.generation_delivery import (
    MaterializationInput,
    MaterializationInputPort,
)
from ..application.record_validation import (
    ImmutableVdrStore,
    RecordValidationBlocked,
    ValidatedDataRecord,
    validate_data_record_against_plan,
)
from ..domain.raw_data_record import (
    RawRecordCaptureProvenance,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
)
from ..external.job_store import JobRegistry
from ..external.materialization_conformance_vocabulary import (
    ConformanceFailure,
    MaterializedDocumentBytes,
)
from ..external.materialization_start_gate import (
    StartMaterializationRefusal,
    start_materialization,
)
from ..external.text_materialization_conformance import TXT_ENCODING
from ..external.text_materialization_runner import txt_materialization_runner
from ..external.work_template_store import WorkTemplateStoreError
from ..external.seal_execution_plan_product import ExecutionPlanSealedProductOutcome
from ..external.seal_execution_plan_service import SealExecutionPlanService

#: 거절 코드 — 전부 **상류 판정의 재진술**이다(이 모듈은 새 판정을 만들지 않는다).
TXT_MEDIA_REQUIRED = "TXT_MEDIA_REQUIRED"
TEMPLATE_INITIALIZATION_REQUIRED = "TEMPLATE_INITIALIZATION_REQUIRED"
EXECUTION_PLAN_NOT_SEALED = "EXECUTION_PLAN_NOT_SEALED"
RECORD_VALIDATION_BLOCKED = "RECORD_VALIDATION_BLOCKED"
RECORD_CAPTURE_FAILED = "RECORD_CAPTURE_FAILED"


@dataclass(frozen=True)
class TxtMaterializationRefused:
    """물질화에 이르지 못했다 — 코드와 사유는 상류가 낸 것을 그대로 나른다."""

    code: str
    detail: str


TxtMaterializationResult = MaterializedDocumentBytes | TxtMaterializationRefused


def _source_value(value: object):
    """데이터 열 값 하나를 exact source 값으로 고정한다(「문서 만들기」 capture 와 동형).

    소스 값은 언제나 타입 없는 텍스트다 — 해석하지 않는다. 문자열이 아닌 값(숫자·날짜 객체 등)의
    ``str`` 승격은 타입 축과 무관한 **캡처 관용**이라 그대로 둔다: 여기서 raise 하면 열 하나의
    표현 때문에 복사 전체가 사유 없이 죽는다.
    """
    if value is None:
        return SourceNull()
    if not isinstance(value, str):
        value = str(value)
    return SourceText(value)


class TxtMaterializationService:
    """작업대가 복사 직전에 부르는 얇은 표면 — 봉인 확보부터 검증된 bytes 까지."""

    def __init__(
        self,
        registry: JobRegistry,
        seal_service: SealExecutionPlanService,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._seal = seal_service
        self._clock = clock
        # authority root 를 따로 받지 않는다(S10-04 · #861): 러너가 읽을 store 는 Plan 이
        # 봉인된 바로 그 authority 여야 하므로, 그 경로는 seal 서비스가 내는 실행 문맥
        # (:class:`ManagedRunContext`) 하나에서만 온다 — 두 곳에서 받으면 어긋날 자리가 생긴다.

    def materialize_record(
        self,
        work_ref: str,
        record: Mapping[str, object],
        *,
        request_id: str,
        runtime_now: datetime | None = None,
    ) -> TxtMaterializationResult:
        """레코드 1건을 현재 basis 의 Sealed Plan 으로 물질화한다(실패는 사유 있는 거절).

        ``runtime_now`` 는 「오늘 날짜」(RUNTIME_DATE)의 기준 시각이다 — 작업대가 카드 렌더에 쓴
        값을 넘기면 복사본과 카드가 같은 글자다. 없으면 이 호출이 시계를 **한 번** 읽는다.
        """
        job = self._registry.load(work_ref)
        if job.media != "txt":
            return TxtMaterializationRefused(
                TXT_MEDIA_REQUIRED, "TXT 작업이 아닙니다."
            )

        # 1. 봉인 — command outcome 이 Sealed 가 아니면 그 사유가 곧 복사 차단 사유다.
        #    **봉인이 먼저다**: 구성(고르지 않은 항목)처럼 사용자가 먼저 고쳐야 하는 사실은
        #    Binding 판본을 만들어도 풀리지 않으므로, 그 blocker 를 Binding 검토 사유로 덮어
        #    말하면 사용자가 엉뚱한 곳을 고치게 된다.
        try:
            outcome = self._seal.seal_execution_plan(work_ref, request_id).command_outcome
        except WorkTemplateStoreError as exc:
            # 아직 「변경사항 확인」이 Work 를 세우지 않았다 — 앱 전역이 쓰는 어휘로 재진술한다.
            return TxtMaterializationRefused(
                TEMPLATE_INITIALIZATION_REQUIRED,
                f"이 작업의 템플릿 확인이 아직 끝나지 않았습니다({exc}).",
            )
        if not isinstance(outcome, ExecutionPlanSealedProductOutcome):
            return TxtMaterializationRefused(
                EXECUTION_PLAN_NOT_SEALED, _blocked_detail(outcome)
            )
        plan = outcome.plan_payload
        if not isinstance(plan, SealedExecutionPlanSemanticPayload):
            return TxtMaterializationRefused(
                EXECUTION_PLAN_NOT_SEALED,
                "봉인 결과에 실행 payload 가 없습니다.",
            )

        context = self._seal.managed_run_context(work_ref, media="txt")
        if context is None:
            return TxtMaterializationRefused(
                TEMPLATE_INITIALIZATION_REQUIRED,
                "이 작업의 실행 권위를 확인할 수 없습니다.",
            )

        # 3. VDR — record 자격 판정은 record_validation 소유다(여기서 재조립 0).
        validated_at = (
            runtime_now if runtime_now is not None else self._clock()
        ).isoformat(timespec="seconds")
        try:
            snapshot = self._capture(record, validated_at)
        except ValueError as exc:
            return TxtMaterializationRefused(RECORD_CAPTURE_FAILED, str(exc))
        # 「오늘 날짜」(RUNTIME_DATE)도 이 물질화가 캡처한 그 시각으로 렌더한다(시계 1회).
        validated = validate_data_record_against_plan(
            plan=plan, snapshot=snapshot, validated_at=validated_at, runtime_clock=validated_at
        )
        if isinstance(validated, RecordValidationBlocked):
            codes = ", ".join(sorted({b.code for b in validated.blockers}))
            return TxtMaterializationRefused(
                RECORD_VALIDATION_BLOCKED, f"이 레코드의 검증이 닫히지 않았습니다: {codes}"
            )
        if not isinstance(validated, ValidatedDataRecord):
            return TxtMaterializationRefused(validated.code, validated.detail)

        # 4. start gate → LongMaterialization. process-local Plan resolver 라 위조 ref 는 거절.
        vdr_store = ImmutableVdrStore()
        vdr_ref = vdr_store.put(validated)
        plan_digest = plan_semantic_digest(plan)

        def resolve_plan(ref: str) -> SealedExecutionPlanSemanticPayload:
            if ref != plan_digest:
                raise KeyError(f"미지의 Plan ref: {ref!r}")
            return plan

        input_port = MaterializationInputPort(
            plan_resolver=resolve_plan, vdr_store=vdr_store
        )
        runner = txt_materialization_runner(
            context.root, plan_resolver=resolve_plan, vdr_store=vdr_store
        )
        result = start_materialization(
            workspace_instance_id=context.workspace_instance_id,
            work_authority_id=context.work_authority_id,
            materialization_input=MaterializationInput(
                sealed_execution_plan_ref=plan_digest, validated_record_ref=vdr_ref
            ),
            input_port=input_port,
            runner=runner,
            runtime_registry=context.runtime_registry,
            runtime_capability_manifest_digest=(
                context.runtime_capability_manifest_digest
            ),
            current_basis_digest_reader=context.current_basis_digest_reader,
        )
        if isinstance(result, StartMaterializationRefusal):
            return TxtMaterializationRefused(result.code, result.detail)
        if isinstance(result, ConformanceFailure):
            return TxtMaterializationRefused(result.code, result.detail)
        return result

    def _capture(self, record: Mapping[str, object], captured_at: str):
        keys = tuple(str(key) for key in record)
        return build_raw_record_snapshot(
            source_schema_keys=keys,
            source_values=[
                (str(key), _source_value(value)) for key, value in record.items()
            ],
            record_identity=f"workbench-record/{captured_at}/{len(keys)}",
            capture_provenance=RawRecordCaptureProvenance(
                source_adapter_contract_id="workbench-record-capture/v1",
                captured_at=captured_at,
                source_observation_ref="workbench-session",
            ),
        )


def materialized_text(document: MaterializedDocumentBytes) -> str:
    """검증된 산출 bytes 의 텍스트 얼굴 — 디코드도 산출과 **같은 엄격 UTF-8** 이다."""
    return document.output_bytes.decode(TXT_ENCODING)


def _blocked_detail(outcome: object) -> str:
    blockers = getattr(outcome, "normalized_blockers", None)
    if blockers:
        return "실행 계획을 봉인할 수 없습니다: " + ", ".join(blockers)
    policy_code = getattr(outcome, "policy_code", None)
    if policy_code:
        return f"실행 계획을 봉인할 수 없습니다: {policy_code}"
    stale = getattr(outcome, "stale_reason", None)
    if stale:
        return f"실행 기준이 그사이 바뀌었습니다: {stale}"
    return "실행 계획을 봉인할 수 없습니다."


__all__ = [
    "EXECUTION_PLAN_NOT_SEALED",
    "RECORD_CAPTURE_FAILED",
    "RECORD_VALIDATION_BLOCKED",
    "TEMPLATE_INITIALIZATION_REQUIRED",
    "TXT_MEDIA_REQUIRED",
    "TxtMaterializationRefused",
    "TxtMaterializationResult",
    "TxtMaterializationService",
    "materialized_text",
]
