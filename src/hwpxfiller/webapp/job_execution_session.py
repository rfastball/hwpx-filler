"""문서 생성 화면의 실행 세션 상태와 준비 캐시를 소유한다.

컨트롤러는 라이브 선택을 캡처하고 전이 순서를 지킨다. 이 객체는 봉인 관찰과
레코드·배달 준비의 수명만 맡으며 화면이나 컨트롤러를 의존하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import uuid

from ..application.automatic_seal_orchestration import (
    FAILED,
    SETTLED_CURRENT,
    AutomaticSealOrchestration,
    on_durable_command_settled,
    on_seal_settled,
    request_manual_recovery,
)
from ..application.document_creation_workbench import (
    DeliveryPreviewSummary,
    HistoricalOutcomeSummary,
    RecordValidationSummary,
    WorkbenchContextIntegrity,
)
from ..application.execution_semantic_kernel import SealedExecutionPlanValue
from ..application.field_binding_input import FieldBindingInput
from ..application.fresh_execution_observation import (
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    FreshExecutionObservation,
)
from ..application.run_delivery_intent import RunDeliveryIntent
from ..application.generation_delivery import DeliveryPlanContextError
from ..domain.raw_data_record import RawDataRecordSnapshot
from .current_execution_preparation import (
    CurrentDeliveryPreparation,
    CurrentRecordPreparation,
    delivery_projection,
    prepare_current_delivery,
    prepare_current_records,
    unresolved_delivery,
)
from .seal_execution_plan_product import ExecutionPlanSealedProductOutcome
from .slot_configuration_product import SlotConfigurationProduct, SlotConfigurationProductError
from .seal_execution_plan_service import BindingReviewProjection
from .template_change import SUPPORTED_MEDIA
from ..application.preset_command import preset_list_actionable
from ..domain.job import Job


@dataclass(frozen=True)
class WorkbenchConfiguration:
    slot_view: object | None
    binding_review: BindingReviewProjection | None


class JobExecutionSession:
    """실행 봉인 증거와 그 증거에서 만든 준비 캐시의 단일 소유자."""

    def __init__(
        self,
        *,
        slot_configuration=None,
        workbench_observation=None,
        seal_execution=None,
    ) -> None:
        self.slot_configuration = slot_configuration
        self.workbench_product = workbench_observation
        self.seal_execution = seal_execution
        self.orchestration = AutomaticSealOrchestration()
        self.fresh_observation: FreshExecutionObservation | None = None
        self.sealed_basis_digest: str | None = None
        self.sealed_plan_payload = None
        self.managed_outcome: HistoricalOutcomeSummary | None = None
        self.record_preparation: CurrentRecordPreparation | None = None
        self.delivery_preparation: CurrentDeliveryPreparation | None = None

    @staticmethod
    def blank_slot_zone() -> dict:
        return {
            "supported": False,
            "initialized": False,
            "mutation_outcome": None,
            "current_view": None,
            "refresh_required": False,
            "error": None,
        }

    @staticmethod
    def blank_presets_zone() -> dict:
        return {
            "supported": False,
            "items": [],
            "corrupt": [],
            "list_actionable": False,
            "save_actionable": False,
            "applied_key": None,
        }

    def require_slot_configuration(self, work_ref: str) -> SlotConfigurationProduct:
        if self.slot_configuration is None:
            raise ValueError("문서 구성 기능이 조립되지 않았습니다")
        if not work_ref:
            raise ValueError("먼저 작업을 선택하세요")
        return self.slot_configuration

    def slot_zone(self, work_ref: str, job: Job | None, template_missing: bool) -> dict:
        """현재 Work의 read-only 구성 projection을 JSON 값으로 만든다."""
        blank = self.blank_slot_zone()
        if (
            self.slot_configuration is None
            or not work_ref
            or job is None
            or template_missing
            or job.media not in SUPPORTED_MEDIA
        ):
            return blank
        if not job.authority_id:
            return {**blank, "supported": True}
        try:
            response = self.slot_configuration.current_slot_configuration_view(work_ref)
        except SlotConfigurationProductError as exc:
            return {
                **blank,
                "supported": True,
                "error": {
                    "code": exc.code,
                    "message": "포함할 내용을 불러오지 못했습니다. 다시 불러오세요.",
                    "action": {"key": "refresh", "label": "다시 불러오기"},
                },
            }
        return {
            "supported": True,
            "initialized": True,
            "error": None,
            **asdict(response),
        }

    def is_managed_hwpx(self, work_ref: str, job: Job) -> bool:
        if (
            job.media != "hwpx"
            or not job.authority_id
            or self.slot_configuration is None
            or not work_ref
        ):
            return False
        try:
            response = self.slot_configuration.current_slot_configuration_view(work_ref)
        except SlotConfigurationProductError:
            return False
        projection = response.current_view.projection
        return projection is not None and bool(projection.slots)

    def open_slot_configuration(self, work_ref: str):
        return self.require_slot_configuration(work_ref).open_slot_configuration(work_ref)

    def refresh_slot_configuration(self, work_ref: str, token: str | None):
        return self.require_slot_configuration(work_ref).refresh_slot_configuration(work_ref, token)

    def select_slot_option(
        self,
        work_ref: str,
        configuration_token: str,
        slot_id: str,
        option_id: str,
        request_id: str,
    ):
        return self.require_slot_configuration(work_ref).select_slot_option(
            work_ref, configuration_token, slot_id, option_id, request_id
        )

    def presets_zone(
        self,
        work_ref: str,
        job: Job | None,
        template_missing: bool,
        *,
        savable_selection: bool,
    ) -> dict:
        blank = self.blank_presets_zone()
        if (
            self.slot_configuration is None
            or not work_ref
            or job is None
            or template_missing
            or job.media not in SUPPORTED_MEDIA
        ):
            return blank
        listing = self.slot_configuration.list_selection_presets(
            work_ref if job.authority_id else None
        )
        return {
            "supported": True,
            "items": [
                {"key": item.key, "name": item.name, "created_at": item.created_at}
                for item in listing.items
            ],
            "corrupt": [
                {"file_name": entry.file_name, "error": entry.error}
                for entry in listing.corrupt
            ],
            "corrupt_code": listing.corrupt_code,
            "list_actionable": preset_list_actionable(listing),
            "save_actionable": savable_selection,
            "applied_key": listing.applied_key,
        }

    def save_selection_preset(
        self,
        work_ref: str,
        configuration_token: str,
        name: str,
        confirmed_overwrite_key: str | None,
    ):
        return self.require_slot_configuration(work_ref).save_selection_preset(
            work_ref, configuration_token, name, confirmed_overwrite_key
        )

    def apply_selection_preset(
        self, work_ref: str, configuration_token: str, preset_key: str
    ):
        return self.require_slot_configuration(work_ref).apply_selection_preset(
            work_ref, configuration_token, preset_key
        )

    def current_slot_view(self, work_ref: str):
        if self.slot_configuration is None or not work_ref:
            return None
        return self.slot_configuration.current_slot_configuration_view(work_ref)

    def current_binding_review(self, work_ref: str):
        if self.seal_execution is None or not work_ref:
            return None
        return self.seal_execution.current_binding_review(work_ref)

    def binding_review_projection(self, work_ref: str):
        """fresh Work 관찰이 있을 때만 durable binding 분류표를 읽는다."""
        if (
            self.seal_execution is None
            or not work_ref
            or not isinstance(self.fresh_observation, CurrentWorkExecutionObservation)
        ):
            return None
        return self.seal_execution.current_binding_review(work_ref)

    def managed_run_context(self, work_ref: str):
        if self.seal_execution is None:
            return None
        return self.seal_execution.managed_run_context(work_ref)

    def execution_status(self):
        if self.workbench_product is None:
            raise ValueError("작업대 Observation 기능이 조립되지 않았습니다")
        return self.workbench_product.execution_status(
            orchestration=self.orchestration,
            fresh_observation=self.fresh_observation,
        )

    def compose_workbench(self, **facts):
        if self.workbench_product is None:
            raise ValueError("작업대 Observation 기능이 조립되지 않았습니다")
        return self.workbench_product.compose(**facts)

    def capture_workbench_configuration(
        self, *, job: Job | None, work_ref: str
    ) -> WorkbenchConfiguration:
        """레코드 준비 전에 같은 Work의 slot·binding read view를 고정한다."""
        slot_view = None
        if (
            self.slot_configuration is not None
            and job is not None
            and job.media == "hwpx"
            and job.authority_id
        ):
            try:
                response = self.current_slot_view(work_ref)
            except SlotConfigurationProductError:
                response = None
            if response is not None:
                slot_view = response.current_view.projection
        return WorkbenchConfiguration(
            slot_view=slot_view,
            binding_review=self.binding_review_projection(work_ref),
        )

    def build_workbench_observation(
        self,
        *,
        configuration: WorkbenchConfiguration,
        work_ref: str,
        data_mounted: bool,
        selected_record_count: int,
        total_record_count: int,
        active_work_data_bound: bool,
        record_validation: RecordValidationSummary,
        delivery: DeliveryPreviewSummary,
        template_change_verdict: str | None,
        run_delivery_intent: RunDeliveryIntent | None,
        context_integrity: WorkbenchContextIntegrity | None,
    ):
        """현재 config·binding·seal 증거와 준비 결과를 한 Observation으로 합성한다."""
        binding = configuration.binding_review
        return self.compose_workbench(
            data_mounted=data_mounted,
            selected_record_count=selected_record_count,
            total_record_count=total_record_count,
            active_work_ref=work_ref or None,
            active_work_data_bound=active_work_data_bound,
            slot_view=configuration.slot_view,
            orchestration=self.orchestration,
            fresh_observation=self.fresh_observation,
            active_field_requirement_ids=(
                binding.active_field_ids if binding is not None else ()
            ),
            input_requirements=(
                binding.input_requirements if binding is not None else ()
            ),
            record_validation=record_validation,
            delivery=delivery,
            template_change_verdict=template_change_verdict,
            historical_outcome=self.managed_outcome,
            run_delivery_intent=run_delivery_intent,
            context_integrity=context_integrity,
        )

    def binding_review_pending(self, *, input_requirements) -> bool:
        if self.workbench_product is None:
            return False
        return self.workbench_product.binding_review_pending(
            fresh_observation=self.fresh_observation,
            input_requirements=input_requirements,
        )

    def commit_current_mapping(self, work_ref: str):
        if self.seal_execution is None:
            raise ValueError("Field Binding is not configured.")
        return self.seal_execution.commit_current_mapping(work_ref, uuid.uuid4().hex)

    def run_automatic_seal(self, work_ref: str, *, max_coalesced: int) -> None:
        """CHECKING 전이를 실제 seal 호출과 결속해 coalesce를 유한하게 소진한다."""
        if self.seal_execution is None:
            raise ValueError("실행 확인 기능이 조립되지 않았습니다")
        for _ in range(max_coalesced):
            try:
                response = self.seal_execution.seal_execution_plan(
                    work_ref, uuid.uuid4().hex
                )
            except Exception:  # noqa: BLE001 - product failures drive the state machine.
                self.settle_seal(succeeded=False, current=False)
                return
            self.absorb_seal_response(response)
            if not self.settle_seal(
                succeeded=True,
                current=isinstance(
                    response.fresh_observation, CurrentSealedPlanObservation
                ),
            ):
                return

    def refresh_observation(self, work_ref: str) -> None:
        if self.seal_execution is None or not work_ref:
            return
        try:
            response = self.seal_execution.seal_execution_plan(
                work_ref, uuid.uuid4().hex
            )
            self.absorb_seal_response(response)
        except Exception as exc:  # noqa: BLE001 - stale CURRENT must be replaced loudly.
            self.record_refresh_failure(exc)

    @property
    def is_settled_current(self) -> bool:
        return self.orchestration.state == SETTLED_CURRENT

    def invalidate(self) -> None:
        """작업 기준이 바뀌면 모든 세션 실행 증거를 버린다."""
        self.orchestration = AutomaticSealOrchestration()
        self.fresh_observation = None
        self.sealed_basis_digest = None
        self.sealed_plan_payload = None
        self.managed_outcome = None
        self.invalidate_preparations()

    def invalidate_preparations(self) -> None:
        """봉인 증거는 유지하고 선택·배달 입력에 묶인 준비만 버린다."""
        self.record_preparation = None
        self.delivery_preparation = None

    def invalidate_delivery(self) -> None:
        """레코드 준비는 유지하고 폴더·시각에 묶인 배달 준비만 버린다."""
        self.delivery_preparation = None

    def start_after_durable_change(self) -> bool:
        transition = on_durable_command_settled(
            self.orchestration,
            durable_command_succeeded=True,
            effective_basis_changed=True,
        )
        self.orchestration = transition.next_state
        return transition.should_start_seal

    def start_manual_recovery(self) -> bool:
        if self.orchestration.state == FAILED:
            self.orchestration = request_manual_recovery(self.orchestration)
        return self.start_after_durable_change()

    def settle_seal(self, *, succeeded: bool, current: bool) -> bool:
        transition = on_seal_settled(
            self.orchestration,
            seal_succeeded=succeeded,
            resulting_currentness_current=current,
        )
        self.orchestration = transition.next_state
        return transition.should_start_seal

    def absorb_seal_response(self, response) -> None:
        """한 응답에서 나온 관찰·basis·payload를 같은 세대로 보관한다."""
        self.fresh_observation = response.fresh_observation
        if isinstance(response.command_outcome, ExecutionPlanSealedProductOutcome):
            self.sealed_basis_digest = response.command_outcome.execution_basis_digest
            self.sealed_plan_payload = response.command_outcome.plan_payload

    def record_refresh_failure(self, error: Exception) -> None:
        self.fresh_observation = ExecutionObservationContextError(
            "OBSERVATION_REFRESH_FAILED", str(error)
        )

    def cached_records(
        self,
        *,
        snapshot_generation: int,
        work_ref: str,
        ordered_model_indices: tuple[int, ...],
        plan: SealedExecutionPlanValue,
    ) -> CurrentRecordPreparation | None:
        cached = self.record_preparation
        if (
            cached is not None
            and cached.snapshot_generation == snapshot_generation
            and cached.work_ref == work_ref
            and cached.ordered_model_indices == ordered_model_indices
            and cached.execution_value == plan
        ):
            return cached
        return None

    def install_records(self, preparation: CurrentRecordPreparation) -> None:
        """컨트롤러가 라이브 상태를 재검사한 뒤에만 호출한다."""
        self.record_preparation = preparation

    @staticmethod
    def prepare_records(
        *,
        snapshot_generation: int,
        work_ref: str,
        ordered_model_indices: tuple[int, ...],
        plan: SealedExecutionPlanValue,
        raw_records: tuple[RawDataRecordSnapshot, ...],
        project_issue: Callable,
    ):
        """고정된 레코드 값으로 준비를 계산한다. 설치는 live 재검사 뒤에만 한다."""
        return prepare_current_records(
            snapshot_generation=snapshot_generation,
            work_ref=work_ref,
            ordered_model_indices=ordered_model_indices,
            plan=plan,
            raw_records=raw_records,
            project_issue=project_issue,
        )

    def cached_delivery(
        self,
        *,
        record_preparation: CurrentRecordPreparation,
        current_field_binding: FieldBindingInput,
        exact_pattern: str,
        run_delivery_intent: RunDeliveryIntent,
    ) -> CurrentDeliveryPreparation | None:
        cached = self.delivery_preparation
        if (
            cached is not None
            and cached.record_preparation is record_preparation
            and cached.current_field_binding == current_field_binding
            and cached.exact_pattern == exact_pattern
            and cached.run_delivery_intent == run_delivery_intent
        ):
            return cached
        return None

    def prepare_delivery(
        self,
        *,
        record_preparation: CurrentRecordPreparation,
        current_field_binding: FieldBindingInput,
        exact_pattern: str,
        run_delivery_intent: RunDeliveryIntent,
        captured_delivery_clock: str,
        allow_missing_output_directory: bool,
    ) -> CurrentDeliveryPreparation:
        prepared = prepare_current_delivery(
            record_preparation=record_preparation,
            current_field_binding=current_field_binding,
            exact_pattern=exact_pattern,
            run_delivery_intent=run_delivery_intent,
            captured_delivery_clock=captured_delivery_clock,
            allow_missing_output_directory=allow_missing_output_directory,
        )
        self.delivery_preparation = prepared
        return prepared

    def resolve_delivery(
        self,
        *,
        record_validation: RecordValidationSummary,
        snapshot_generation: int,
        work_ref: str,
        ordered_model_indices: tuple[int, ...],
        fresh_observation: FreshExecutionObservation | None,
        run_delivery_intent: RunDeliveryIntent | None,
        exact_pattern: str,
        capture_delivery_clock: Callable[[], str],
        allow_missing_output_directory: bool,
    ) -> tuple[DeliveryPreviewSummary, WorkbenchContextIntegrity | None]:
        """현재 레코드 준비와 봉인 결속에서 배달 미리보기를 갱신한다."""
        if run_delivery_intent is None:
            return unresolved_delivery(
                "OUTPUT_DIRECTORY_REQUIRED", "저장 폴더를 선택하세요."
            ), None
        preparation = self.record_preparation
        if record_validation.has_blocking_issues:
            return unresolved_delivery(
                "RECORD_VALIDATION_REQUIRED", "먼저 데이터 문제를 확인하세요."
            ), None
        if (
            preparation is None
            or preparation.snapshot_generation != snapshot_generation
            or preparation.work_ref != work_ref
            or preparation.ordered_model_indices != ordered_model_indices
            or not preparation.validated_records
        ):
            return unresolved_delivery(
                "CURRENT_RECORD_PREPARATION_REQUIRED", "생성할 데이터를 먼저 선택하세요."
            ), None
        if not isinstance(fresh_observation, CurrentSealedPlanObservation):
            return unresolved_delivery(
                "CURRENT_EXECUTION_REQUIRED", "현재 설정을 먼저 확인하세요."
            ), None
        current_field_binding = fresh_observation.current_field_binding
        if current_field_binding is None:
            return DeliveryPreviewSummary(resolvable=False), WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_DELIVERY_BINDING_CONTEXT_MISSING",
                detail="현재 파일 이름에 사용할 항목 연결을 복원할 수 없습니다.",
            )
        cached = self.cached_delivery(
            record_preparation=preparation,
            current_field_binding=current_field_binding,
            exact_pattern=exact_pattern,
            run_delivery_intent=run_delivery_intent,
        )
        if cached is None:
            cached = self.prepare_delivery(
                record_preparation=preparation,
                current_field_binding=current_field_binding,
                exact_pattern=exact_pattern,
                run_delivery_intent=run_delivery_intent,
                captured_delivery_clock=capture_delivery_clock(),
                allow_missing_output_directory=allow_missing_output_directory,
            )
        if isinstance(cached.result, DeliveryPlanContextError):
            return DeliveryPreviewSummary(resolvable=False), WorkbenchContextIntegrity(
                restore_failure=True,
                code=cached.result.code,
                detail=cached.result.detail,
            )
        return delivery_projection(cached.result), None

    def record_managed_outcome(self, outcome: HistoricalOutcomeSummary) -> None:
        self.managed_outcome = outcome


__all__ = ["JobExecutionSession"]
