"""창 없는 managed 문서 생성 — CLI 가 GUI 와 **같은 척추**를 타는 조립(#1081 PR3).

GUI 의 「문서 만들기」는 작업 선택(권위·초기 등록) → 연결 판본 들이기 → 실행 계획 봉인 →
레코드 검증 → 배달 계획 → materialization → 배달·되읽기를 여러 세션 객체에 나눠 밟는다. 이
모듈은 같은 단계들을 **같은 함수들로** 한 번에 이어 붙일 뿐 판정을 새로 만들지 않는다:

- 초기 등록: :class:`~hwpxfiller.external.template_change.TemplateChangeCoordinator` 의
  ``ensure_bootstrapped`` (착석이 부르는 그 동사).
- 연결 판본·봉인·실행 맥락: :class:`~hwpxfiller.external.seal_execution_plan_service
  .SealExecutionPlanService`.
- 레코드·배달 준비: :mod:`hwpxfiller.external.current_execution_preparation`.
- 실행: :func:`~hwpxfiller.external.managed_generation.run_managed_generation`.

CLI 에는 durable 작업이 없다. 그래서 **호출자가 준 임시 작업공간**(작업 레지스트리 + 권위
root)에 이 실행 하나만을 위한 Work 를 세우고 끝나면 버린다(결정 Q3-a, #1081). 산출물과
사이드카 원장만 ``output_directory`` 에 남는다.

실패는 모두 구분된 결과 값이다(예외로 올리지 않는다). 파일 시스템에 닿는 것은 배달뿐이고
그 앞의 어느 거절도 write 0 이다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import uuid

from ..application.execution_contract_set import SealedExecutionPlanSemanticPayload
from ..application.fresh_execution_observation import (
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
)
from ..application.generation_delivery import (
    WRITE_OVERWRITE,
    CurrentResolvedDelivery,
    DeliveryPlanBlocked,
    DeliveryPlanContextError,
)
from ..application.run_delivery_intent import OVERWRITE_EXPLICIT, RunDeliveryIntent
from ..domain.job import JOB_MAPPING_AUTHORITY, Job
from ..domain.mapping import MappingProfile
from .current_execution_preparation import (
    DELIVERY_BLOCKER_PHRASES,
    CurrentRecordCaptureError,
    CurrentRecordPreparation,
    capture_selected_records,
    prepare_current_delivery,
    prepare_current_records,
    record_issue,
)
from .job_store import JobRegistry
from .managed_generation import ManagedGenerationResult, run_managed_generation
from .output_files import ensure_output_directory
from .seal_execution_plan_product import ExecutionPlanSealedProductOutcome
from .seal_execution_plan_service import SealExecutionPlanService
from .template_change import TemplateChangeCoordinator

#: 임시 작업공간 안 Work 의 이름 — 사용자에게 보이지 않는다(파일 이름에도 쓰이지 않는다).
HEADLESS_WORK_NAME = "cli-run"

# 거절 단계 어휘 — 호출자가 문장과 종료 코드를 고른다.
TEMPLATE_INITIALIZATION = "TEMPLATE_INITIALIZATION"
EXECUTION_NOT_SEALABLE = "EXECUTION_NOT_SEALABLE"
RECORD_VALIDATION = "RECORD_VALIDATION"
DELIVERY_PLAN = "DELIVERY_PLAN"


@dataclass(frozen=True)
class HeadlessRefused:
    """실행 전 거절 — write 0. ``details`` 는 사람이 읽을 사유 줄들이다."""

    stage: str
    code: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class HeadlessNeedsOverwrite:
    """기존 파일을 덮어쓰는 배달 계획 — ``--overwrite`` 없이는 쓰지 않는다(write 0)."""

    conflict_names: tuple[str, ...]


@dataclass(frozen=True)
class HeadlessExecuted:
    """managed 파이프라인이 돌았다 — ``outcome`` 은 그 결과 합타입 그대로다."""

    outcome: ManagedGenerationResult
    work_authority_id: str
    execution_basis_digest: str
    plan_payload: SealedExecutionPlanSemanticPayload
    resolved_delivery: CurrentResolvedDelivery
    validated_at: str


HeadlessGenerationResult = HeadlessRefused | HeadlessNeedsOverwrite | HeadlessExecuted


def run_headless_generation(
    *,
    workspace: Path,
    template_path: str,
    mapping: MappingProfile,
    filename_pattern: str,
    records: "Sequence[dict[str, str]]",
    source_schema_keys: "tuple[str, ...]",
    output_directory: str,
    overwrite: bool,
    clock: "Callable[[], datetime]",
) -> HeadlessGenerationResult:
    """임시 작업공간에 Work 하나를 세워 managed 로 문서를 만든다.

    ``workspace`` 는 호출자가 소유하는 빈 폴더다(작업 레지스트리·권위 root 가 그 안에 선다).
    ``records`` 는 매핑 전 원천 값이다 — 매핑·표시형·빈 값 표식은 연결 판본과 managed 검증이
    GUI 와 같은 규칙으로 적용한다.
    """
    registry = JobRegistry(workspace / "jobs")
    root = workspace / "authority"
    registry.save(
        Job(
            name=HEADLESS_WORK_NAME,
            template_path=str(Path(template_path).resolve()),
            mapping=mapping,
            filename_pattern=filename_pattern,
            binding_authority=JOB_MAPPING_AUTHORITY,
        )
    )

    bootstrap = TemplateChangeCoordinator(registry, root=root, clock=clock).ensure_bootstrapped(
        HEADLESS_WORK_NAME
    )
    if bootstrap.get("ok") is not True or not bootstrap.get("bootstrapped"):
        return HeadlessRefused(
            TEMPLATE_INITIALIZATION, str(bootstrap.get("reason") or "initialization_required")
        )

    seal = SealExecutionPlanService(registry, root=root, clock=clock)
    response = seal.seal_execution_plan(HEADLESS_WORK_NAME, uuid.uuid4().hex)
    fresh = response.fresh_observation
    outcome = response.command_outcome
    if not isinstance(fresh, CurrentSealedPlanObservation) or not isinstance(
        outcome, ExecutionPlanSealedProductOutcome
    ):
        details = (
            list(fresh.normalized_blockers_or_policy)
            if isinstance(fresh, CurrentWorkExecutionObservation)
            else []
        )
        review = seal.current_binding_review(HEADLESS_WORK_NAME)
        mapped = {item.template_field for item in mapping.mappings}
        pending = [
            field_id
            for field_id in (review.active_field_ids if review is not None else ())
            if field_id not in mapped
        ]
        if pending:
            # 연결 결정이 없는 활성 필드 — 무엇을 매핑해야 하는지 이름으로 말한다.
            details.append("연결이 필요한 필드: " + ", ".join(pending))
        return HeadlessRefused(
            EXECUTION_NOT_SEALABLE,
            (
                fresh.current_sealability
                if isinstance(fresh, CurrentWorkExecutionObservation)
                else type(fresh).__name__
            ),
            tuple(details),
        )
    payload = outcome.plan_payload
    if not isinstance(payload, SealedExecutionPlanSemanticPayload):
        return HeadlessRefused(EXECUTION_NOT_SEALABLE, "SEALED_PLAN_PAYLOAD_MISSING")
    plan = fresh.sealed_plan_value
    captured_at = clock().isoformat(timespec="seconds")

    indices = tuple(range(len(records)))
    try:
        raw = capture_selected_records(
            snapshot_generation=0,
            ordered_model_indices=indices,
            rows=records,
            source_schema_keys=source_schema_keys,
            captured_at=captured_at,
        )
    except CurrentRecordCaptureError as exc:
        return HeadlessRefused(RECORD_VALIDATION, "CURRENT_RECORD_CAPTURE_FAILED", (str(exc),))
    columns = list(source_schema_keys)
    preparation = prepare_current_records(
        snapshot_generation=0,
        work_ref=HEADLESS_WORK_NAME,
        ordered_model_indices=indices,
        plan=plan,
        raw_records=raw,
        project_issue=lambda blocker, model_index, record_identity: record_issue(
            plan=plan,
            blocker=blocker,
            generation=0,
            model_index=model_index,
            record_identity=record_identity,
            columns=columns,
        ),
    )
    if not isinstance(preparation, CurrentRecordPreparation):
        return HeadlessRefused(RECORD_VALIDATION, preparation.code, (preparation.detail,))
    validation = preparation.record_validation
    if validation.has_blocking_issues:
        return HeadlessRefused(
            RECORD_VALIDATION,
            "RECORD_VALIDATION_BLOCKED",
            tuple(
                f"{issue.record_display_locator} {issue.field_display_label}: {issue.message}"
                for issue in validation.issues
            ),
        )

    binding = fresh.current_field_binding
    if binding is None:
        return HeadlessRefused(DELIVERY_PLAN, "CURRENT_DELIVERY_BINDING_CONTEXT_MISSING")
    delivery = prepare_current_delivery(
        record_preparation=preparation,
        current_field_binding=binding,
        exact_pattern=filename_pattern,
        run_delivery_intent=RunDeliveryIntent(
            str(Path(output_directory).resolve()), OVERWRITE_EXPLICIT
        ),
        captured_delivery_clock=captured_at,
        allow_missing_output_directory=True,
    ).result
    if isinstance(delivery, DeliveryPlanContextError):
        return HeadlessRefused(DELIVERY_PLAN, delivery.code, (delivery.detail,))
    if isinstance(delivery, DeliveryPlanBlocked):
        return HeadlessRefused(
            DELIVERY_PLAN,
            delivery.blockers[0].code if delivery.blockers else "DELIVERY_PLAN_BLOCKED",
            tuple(
                " ".join(
                    part
                    for part in (
                        DELIVERY_BLOCKER_PHRASES.get(
                            blocker.code, "생성 예정 문서 이름을 확인할 수 없습니다."
                        ),
                        blocker.conflicting_relative_path or "",
                        f"({blocker.detail})" if getattr(blocker, "detail", "") else "",
                    )
                    if part
                )
                for blocker in delivery.blockers
            ),
        )
    overwriting = tuple(
        item.resolved_output_relative_path
        for item in delivery.ordered_items
        if item.collision_disposition == WRITE_OVERWRITE
    )
    if overwriting and not overwrite:
        return HeadlessNeedsOverwrite(overwriting)

    context = seal.managed_run_context(HEADLESS_WORK_NAME)
    if context is None:
        return HeadlessRefused(EXECUTION_NOT_SEALABLE, "MANAGED_RUN_CONTEXT_UNAVAILABLE")
    ensure_output_directory(delivery.output_directory)
    result = run_managed_generation(
        root=context.root,
        workspace_instance_id=context.workspace_instance_id,
        work_authority_id=context.work_authority_id,
        plan_payload=payload,
        ordered_raw_snapshots=preparation.raw_records,
        resolved_delivery=delivery,
        validated_at=captured_at,
        runtime_registry=context.runtime_registry,
        runtime_capability_manifest_digest=context.runtime_capability_manifest_digest,
        current_basis_digest_reader=context.current_basis_digest_reader,
    )
    return HeadlessExecuted(
        outcome=result,
        work_authority_id=context.work_authority_id,
        execution_basis_digest=outcome.execution_basis_digest,
        plan_payload=payload,
        resolved_delivery=delivery,
        validated_at=captured_at,
    )


__all__ = [
    "DELIVERY_PLAN",
    "EXECUTION_NOT_SEALABLE",
    "HEADLESS_WORK_NAME",
    "RECORD_VALIDATION",
    "TEMPLATE_INITIALIZATION",
    "HeadlessExecuted",
    "HeadlessGenerationResult",
    "HeadlessNeedsOverwrite",
    "HeadlessRefused",
    "run_headless_generation",
]
