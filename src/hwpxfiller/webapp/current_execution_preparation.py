"""현재 선택 레코드와 배달 계획의 값 계산.

세션의 currentness, 캐시 수명, 실행 잠금은 ``JobController``가 소유한다. 이 모듈은
컨트롤러가 고정해 넘긴 값만 캡처·검증하고 저장 폴더를 읽기 전용으로 관찰한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..application.document_creation_workbench import (
    DeliveryPreviewBlocker,
    DeliveryPreviewSummary,
    PlannedDocumentSummary,
    RecordValidationAdvisory,
    RecordValidationIssue,
    RecordValidationSummary,
    WorkbenchContextIntegrity,
)
from ..application.execution_semantic_kernel import SealedExecutionPlanValue
from ..application.field_binding_input import FieldBindingInput
from ..application.generation_delivery import (
    FILENAME_PATTERN_CONTRACT_ID,
    NON_REGULAR,
    REGULAR_FILE,
    CurrentResolvedDelivery,
    DeliveryPlanBlocked,
    DeliveryPlanContextError,
    GenerationDeliveryBindingBasis,
    PathOccupancyEntry,
    PathOccupancyObservation,
    build_delivery_binding_basis,
    resolve_current_generation_delivery,
)
from ..application.record_validation import (
    CurrentValidatedDataRecord,
    MISSING_VALUE_MARKED,
    RecordValidationBlocked,
    RecordValidationBlocker,
    RecordValidationContextError,
    marked_missing_fields,
    validate_data_records_against_current_value,
)
from ..application.run_delivery_intent import RunDeliveryIntent
from ..domain.raw_data_record import (
    RawDataRecordSnapshot,
    RawRecordCaptureProvenance,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
)


@dataclass(frozen=True)
class CurrentRecordPreparation:
    snapshot_generation: int
    work_ref: str
    ordered_model_indices: tuple[int, ...]
    execution_value: SealedExecutionPlanValue
    raw_records: tuple[RawDataRecordSnapshot, ...]
    validated_records: tuple[CurrentValidatedDataRecord, ...]
    record_validation: RecordValidationSummary


@dataclass(frozen=True)
class CurrentDeliveryPreparation:
    record_preparation: CurrentRecordPreparation
    current_field_binding: FieldBindingInput
    exact_pattern: str
    run_delivery_intent: RunDeliveryIntent
    captured_delivery_clock: str
    result: CurrentResolvedDelivery | DeliveryPlanBlocked | DeliveryPlanContextError


class CurrentRecordCaptureError(ValueError):
    pass


def current_record_identity(snapshot_generation: int, model_index: int) -> str:
    return f"current-record/{snapshot_generation}/{model_index}"


def capture_source_value(value: object) -> SourceNull | SourceText:
    """데이터 칸 하나를 exact source 값으로 고정한다 — 값은 언제나 타입 없는 텍스트다."""
    if value is None:
        return SourceNull()
    if isinstance(value, str):
        return SourceText(value)
    raise CurrentRecordCaptureError("데이터 값을 정확히 읽을 수 없습니다.")


def capture_selected_records(
    *,
    snapshot_generation: int,
    ordered_model_indices: tuple[int, ...],
    rows: list[dict],
    source_schema_keys: tuple[str, ...],
    captured_at: str,
) -> tuple[RawDataRecordSnapshot, ...]:
    captured: list[RawDataRecordSnapshot] = []
    for model_index in ordered_model_indices:
        if not 0 <= model_index < len(rows):
            raise CurrentRecordCaptureError("선택한 데이터 위치를 확인할 수 없습니다.")
        source_values = []
        for key, value in rows[model_index].items():
            if not isinstance(key, str):
                raise CurrentRecordCaptureError("데이터 항목 이름을 확인할 수 없습니다.")
            if value is None or isinstance(value, str):
                source_value = capture_source_value(value)
            else:
                raise CurrentRecordCaptureError(
                    f"{model_index + 1}행 {key} 값을 정확히 읽을 수 없습니다."
                )
            source_values.append((key, source_value))
        captured.append(
            build_raw_record_snapshot(
                source_schema_keys=source_schema_keys,
                source_values=source_values,
                record_identity=current_record_identity(snapshot_generation, model_index),
                capture_provenance=RawRecordCaptureProvenance(
                    source_adapter_contract_id="job-current-record-capture/v1",
                    captured_at=captured_at,
                    source_observation_ref=f"job-snapshot/{snapshot_generation}",
                ),
            )
        )
    return tuple(captured)


def prepare_current_records(
    *,
    snapshot_generation: int,
    work_ref: str,
    ordered_model_indices: tuple[int, ...],
    plan: SealedExecutionPlanValue,
    raw_records: tuple[RawDataRecordSnapshot, ...],
    project_issue: Callable[
        [RecordValidationBlocker, int, str], RecordValidationIssue
    ],
) -> CurrentRecordPreparation | WorkbenchContextIntegrity:
    results = validate_data_records_against_current_value(
        plan=plan,
        snapshots=raw_records,
        validated_at=raw_records[0].capture_provenance.captured_at,
    )
    validated: list[CurrentValidatedDataRecord] = []
    issues: list[RecordValidationIssue] = []
    blocked_count = 0
    for model_index, snapshot, result in zip(
        ordered_model_indices, raw_records, results, strict=True
    ):
        if isinstance(result, RecordValidationContextError):
            return WorkbenchContextIntegrity(
                restore_failure=True, code=result.code, detail=result.detail
            )
        if isinstance(result, RecordValidationBlocked):
            blocked_count += 1
            issues.extend(
                project_issue(blocker, model_index, snapshot.record_identity)
                for blocker in result.blockers
            )
        else:
            validated.append(result)

    # 표식 사실 집계(#957) — **차단분과 다른 통**이다. 필드별 문서 수로 접는 이유는
    # 사용자가 고칠 자리가 「그 열」이라서다: 칸 수만 말하면 어느 열을 손봐야 하는지
    # 말하지 않고, 문서마다 한 줄씩 세우면 100건 선택에서 목록이 사실을 덮는다.
    marked_counts: dict[str, int] = {}
    for record in validated:
        for field_id in marked_missing_fields(record.validation_provenance):
            marked_counts[field_id] = marked_counts.get(field_id, 0) + 1
    summary = RecordValidationSummary(
        has_blocking_issues=bool(issues),
        issue_count=len(issues),
        validated_count=len(validated),
        blocked_count=blocked_count,
        issues=tuple(issues),
        advisories=tuple(
            RecordValidationAdvisory(MISSING_VALUE_MARKED, field_id, count)
            for field_id, count in marked_counts.items()
        ),
    )
    return CurrentRecordPreparation(
        snapshot_generation=snapshot_generation,
        work_ref=work_ref,
        ordered_model_indices=ordered_model_indices,
        execution_value=plan,
        raw_records=raw_records,
        validated_records=tuple(validated),
        record_validation=summary,
    )


def unresolved_delivery(code: str, message: str) -> DeliveryPreviewSummary:
    return DeliveryPreviewSummary(
        resolvable=False,
        blockers=(DeliveryPreviewBlocker(code=code, message=message),),
    )


def observe_path_occupancy(
    intent: RunDeliveryIntent,
    observed_at: str,
    *,
    allow_missing: bool = False,
) -> PathOccupancyObservation:
    """저장 폴더의 현재 점유 관찰. 폴더를 만들지 않는다(관찰은 관찰이다).

    ``allow_missing`` 은 **도출한 기본값**에만 선다(U3-06 #879): 아직 없는 폴더는 점유가
    비어 있다는 사실이고, 그 폴더는 생성이 만든다. 그 밖의 판독 실패(권한·잠김)는 이 완화를
    받지 않는다 — 설정한 저장 폴더는 도출이 이미 존재를 확인했으므로, 여기서 읽히지 않는
    것은 「아직 없다」가 아니라 「읽을 수 없다」다.
    """
    root = Path(intent.output_directory)
    if not root.is_absolute():
        raise ValueError("저장 폴더는 전체 경로여야 합니다.")
    if allow_missing and not root.exists():
        return PathOccupancyObservation(intent.output_directory, (), observed_at)
    try:
        entries = tuple(
            sorted(
                (
                    PathOccupancyEntry(
                        entry.name,
                        REGULAR_FILE
                        if not entry.is_symlink() and entry.is_file()
                        else NON_REGULAR,
                    )
                    for entry in root.iterdir()
                ),
                key=lambda entry: entry.relative_name.casefold(),
            )
        )
    except OSError as exc:
        raise ValueError("저장 폴더의 현재 파일 목록을 읽을 수 없습니다.") from exc
    return PathOccupancyObservation(intent.output_directory, entries, observed_at)


DELIVERY_BLOCKER_PHRASES = {
    "OUTPUT_NAME_TOKEN_UNRESOLVED": "파일 이름에 사용할 값을 확인할 수 없습니다.",
    "OUTPUT_NAME_BINDING_AMBIGUOUS": "파일 이름에 사용할 항목 연결을 하나로 확인할 수 없습니다.",
    "OUTPUT_NAME_PATTERN_INVALID": "파일 이름 규칙이 올바르지 않습니다.",
    "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED": "같은 이름의 파일이 있습니다:",
    "OUTPUT_PATH_NON_REGULAR_CONFLICT": "같은 이름의 폴더나 바로가기 등이 있어 덮어쓸 수 없습니다:",
}


def delivery_projection(
    result: CurrentResolvedDelivery | DeliveryPlanBlocked,
) -> DeliveryPreviewSummary:
    if isinstance(result, DeliveryPlanBlocked):
        return DeliveryPreviewSummary(
            resolvable=False,
            blockers=tuple(
                DeliveryPreviewBlocker(
                    code=blocker.code,
                    message=DELIVERY_BLOCKER_PHRASES.get(
                        blocker.code, "생성 예정 문서 이름을 확인할 수 없습니다."
                    ),
                    item_ordinal=blocker.item_ordinal,
                    field_id=blocker.field_id,
                    conflicting_relative_path=blocker.conflicting_relative_path,
                )
                for blocker in result.blockers
            ),
        )
    planned = tuple(
        PlannedDocumentSummary(
            record_identity=item.record_identity,
            item_ordinal=item.item_ordinal,
            relative_path=item.resolved_output_relative_path,
            collision_disposition=item.collision_disposition,
        )
        for item in result.ordered_items
    )
    return DeliveryPreviewSummary(
        resolvable=True,
        planned_output_names=tuple(item.relative_path for item in planned),
        planned_documents=planned,
    )


def prepare_current_delivery(
    *,
    record_preparation: CurrentRecordPreparation,
    current_field_binding: FieldBindingInput,
    exact_pattern: str,
    run_delivery_intent: RunDeliveryIntent,
    captured_delivery_clock: str,
    allow_missing_output_directory: bool,
) -> CurrentDeliveryPreparation:
    """고정된 record·binding·pattern·intent로 현재 배달 계획을 한 번 계산한다.

    캐시의 currentness와 수명은 컨트롤러가 판단한다. 여기서는 점유를 읽기만 하고 폴더를
    만들지 않으며, 도출한 기본 폴더의 부재만 빈 점유로 허용한다.
    """
    basis = build_delivery_binding_basis(
        base_template_application_id=current_field_binding.base_template_application_id,
        field_binding_authority_revision=(
            current_field_binding.field_binding_authority_revision
        ),
        filename_pattern_contract_id=FILENAME_PATTERN_CONTRACT_ID,
        exact_pattern=exact_pattern,
        active_field_ids=(
            str(requirement["field_id"])
            for requirement in record_preparation.execution_value.active_field_requirements
        ),
        binding_rules=current_field_binding.binding_rules,
        document_value_resolution_contract_id=(
            record_preparation.execution_value.contract_semantics
            .document_value_resolution_contract_id
        ),
    )
    result: CurrentResolvedDelivery | DeliveryPlanBlocked | DeliveryPlanContextError
    if isinstance(basis, (DeliveryPlanBlocked, DeliveryPlanContextError)):
        result = basis
    else:
        assert isinstance(basis, GenerationDeliveryBindingBasis)
        try:
            occupancy = observe_path_occupancy(
                run_delivery_intent,
                captured_delivery_clock,
                allow_missing=allow_missing_output_directory,
            )
        except ValueError as exc:
            result = DeliveryPlanContextError(
                "PATH_OCCUPANCY_OBSERVATION_FAILED", str(exc)
            )
        else:
            result = resolve_current_generation_delivery(
                sealed_execution_plan=record_preparation.execution_value,
                ordered_validated_records=record_preparation.validated_records,
                ordered_raw_snapshots=record_preparation.raw_records,
                delivery_binding_basis=basis,
                exact_pattern=exact_pattern,
                captured_delivery_clock=captured_delivery_clock,
                run_delivery_intent=run_delivery_intent,
                path_occupancy=occupancy,
            )
    return CurrentDeliveryPreparation(
        record_preparation=record_preparation,
        current_field_binding=current_field_binding,
        exact_pattern=exact_pattern,
        run_delivery_intent=run_delivery_intent,
        captured_delivery_clock=captured_delivery_clock,
        result=result,
    )


__all__ = [
    "DELIVERY_BLOCKER_PHRASES",
    "CurrentDeliveryPreparation",
    "CurrentRecordCaptureError",
    "CurrentRecordPreparation",
    "capture_selected_records",
    "capture_source_value",
    "current_record_identity",
    "delivery_projection",
    "observe_path_occupancy",
    "prepare_current_delivery",
    "prepare_current_records",
    "unresolved_delivery",
]
