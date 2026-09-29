"""문서 생성 런의 잠금·취소·결과·배달 수명을 소유한다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import threading

from ..application.generation import (
    GenerationRun,
    PlanDecision,
    plan_generation,
    run_generation,
    start_run,
)
from ..application.execution_contract_set import (
    SealedExecutionPlanSemanticPayload,
    plan_semantic_digest,
)
from ..application.generation_delivery import CurrentResolvedDelivery, WRITE_OVERWRITE
from ..application.document_creation_workbench import HistoricalOutcomeSummary
from ..application.jobs import JobStorePort, stamp_run_completion
from ..external.artifact_observation import (
    ArtifactObservationRefused,
    observe_delivered_artifact,
)
from ..external.delivery_coordinator import (
    DeliveredDocument,
    DeliveryAborted,
    DeliveryCompleted,
)
from ..external.ledger_export import write_managed_delivery_ledger
from ..external.output_files import ensure_output_directory
from ..viewmodel.artifact_view_state import observed_artifact_snapshot
from ..application.run_delivery_intent import DEFAULT_COLLISION_POLICY
from ..viewmodel.run_state import RunDataInput, RunViewModel
from ..domain.job import Job, rules_fingerprints
from .job_presentation import (
    failed_result,
    failure_rows,
    generation_result,
    overwrite_response,
)
from .current_execution_preparation import CurrentDeliveryPreparation
from .managed_generation import ManagedReadBackFailed, run_managed_generation
from .managed_run_result import project_managed_run_result
from .seal_execution_plan_service import ManagedRunContext
from pathlib import Path

ARTIFACT_NOT_IN_SESSION = "ARTIFACT_NOT_IN_SESSION"
ARTIFACT_OBSERVED = "observed"


def _record_failure_note(reason: str) -> str:
    """문서는 앉았는데 그 뒤의 기록(원장·완주 스탬프)이 실패한 사실 — 한 문장 단일 출처."""
    return f" 문서는 만들어졌지만 실행 기록 저장에 실패했습니다({reason})."


@dataclass(frozen=True)
class RunInputCapture:
    """잠금 직후 고정한 데이터 값과 stale 재검사용 라이브 좌표."""

    data: RunDataInput
    indices: tuple[int, ...]
    snapshot_generation: int
    work_ref: str
    source_records: list[dict]
    source_schema_keys: tuple[str, ...]
    output_directory: str


@dataclass(frozen=True)
class LegacyRunResult:
    payload: dict
    stamped_job: Job | None = None
    stamped_rules_changed: bool = False


@dataclass(frozen=True)
class ManagedRunInput:
    """봉인된 plan과 같은 세대에서 준비한 managed 실행 입력."""

    payload: SealedExecutionPlanSemanticPayload
    preparation: CurrentDeliveryPreparation
    context: ManagedRunContext
    sealed_basis_digest: str
    capture: RunInputCapture
    filename_source_columns: list[str]


@dataclass(frozen=True)
class CompletionStamp:
    """완주 기록의 선언 — 저장소와 기록 시각을 **함께** 넘긴다(한쪽만 있는 상태가 없다)."""

    store: JobStorePort
    completed_at: Callable[[], str]


@dataclass(frozen=True)
class ManagedRunResult:
    """managed 런 1회의 wire 결과와 세션이 이어 받아야 할 사실.

    ``executed`` 는 파이프라인이 실제로 돌았는가(배달 시도 여부와 무관하게 참) — 이 런이
    디스크를 움직였을 수 있으므로 호출자는 폴더 관찰에 묶인 배달 준비를 버려야 한다.
    ``stamped_job``·``stamped_rules_changed`` 는 legacy :class:`LegacyRunResult` 와 같은 뜻이다.
    """

    payload: dict
    historical_outcome: HistoricalOutcomeSummary | None = None
    executed: bool = False
    stamped_job: Job | None = None
    stamped_rules_changed: bool = False


class DocumentRunCoordinator:
    """한 앱의 실행 잠금과 현재 런에서 파생된 모든 결과 좌표를 함께 보관한다."""

    def __init__(self, generation_lock: threading.Lock) -> None:
        self.lock = generation_lock
        self.run: GenerationRun | None = None
        self.last_generated: set[int] | None = None
        self.last_failed: list[int] = []
        self.last_run_job = ""
        self.run_revisions: dict[str, int] = {}
        self.overwrite_now_pin: tuple[str, datetime] | None = None
        self.delivery_collision = DEFAULT_COLLISION_POLICY
        self.delivered: tuple[DeliveredDocument, ...] = ()
        self.artifact_view: dict | None = None
        self.out_dir = ""

    def raise_if_generating(self, then_do: str, *, swap: bool = False) -> None:
        if not self.lock.locked():
            return
        if swap:
            raise ValueError(
                f"문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 {then_do}."
            )
        raise ValueError(f"문서 생성이 진행 중입니다. 끝난 뒤에 {then_do}.")

    def request_cancel(self) -> None:
        if self.run is not None:
            self.run.request_cancel()

    def begin(
        self, job: Job | None, *, job_name: str = "", token: str = ""
    ) -> GenerationRun | None:
        """잠금을 얻은 런만 현재 실행과 결과 근거를 교체한다."""
        if not self.lock.acquire(blocking=False):
            return None
        try:
            run = start_run(job, job_name=job_name, token=token)
        except Exception:
            self.lock.release()
            raise
        self.run = run
        return run

    def adopt_run_metadata(self, run: GenerationRun) -> None:
        """실행 경로에 진입한 런만 결과 주체와 판본으로 채택한다."""
        self.last_run_job = run.job_name
        self.run_revisions = dict(run.revisions)

    def finish(self) -> None:
        """현재 런 핸들을 먼저 지운 뒤 전역 생성 잠금을 놓는다."""
        self.run = None
        self.lock.release()

    def capture_input(
        self,
        *,
        datasource: object | None,
        records: list[dict],
        indices: list[int],
        snapshot_generation: int,
        work_ref: str,
        source_schema_keys: tuple[str, ...],
        output_directory: str,
    ) -> RunInputCapture:
        """한 런이 끝까지 쓸 행 순서와 stale 재검사 기준을 함께 고정한다."""
        return RunInputCapture(
            data=RunDataInput(datasource, tuple(records)),
            indices=tuple(indices),
            snapshot_generation=snapshot_generation,
            work_ref=work_ref,
            source_records=records,
            source_schema_keys=source_schema_keys,
            output_directory=output_directory,
        )

    def capture_now(
        self,
        *,
        confirm_overwrite: bool,
        pin_key: str,
        clock: Callable[[], datetime],
    ) -> datetime | None:
        """덮어쓰기 확인이 본 실행 시각을 같은 입력 세계에서만 재사용한다."""
        pin = self.overwrite_now_pin
        self.overwrite_now_pin = None
        if confirm_overwrite and pin is not None:
            return pin[1] if pin[0] == pin_key else None
        return clock()

    def arm_overwrite(self, pin_key: str, now: datetime) -> None:
        self.overwrite_now_pin = (pin_key, now)

    def plan_legacy(
        self,
        vm: RunViewModel,
        data: RunInputCapture,
        indices: list[int],
        *,
        now: datetime,
        confirm_overwrite: bool,
        existing_outputs: Callable[[str, list[str]], list[str]],
    ) -> PlanDecision:
        """한 런의 고정 데이터와 출력 설정으로 legacy 계획을 판정한다."""
        return plan_generation(
            vm,
            data.data,
            indices,
            data.output_directory,
            now=now,
            confirm_overwrite=confirm_overwrite,
            existing_outputs=existing_outputs,
        )

    def run_legacy(
        self,
        run: GenerationRun,
        vm: RunViewModel,
        capture: RunInputCapture,
        *,
        now: datetime,
        confirm_overwrite: bool,
        overwrite_pin_key: str,
        existing_outputs: Callable[[str, list[str]], list[str]],
        engine,
        progress,
        store: JobStorePort,
        completed_at: Callable[[], str],
        ensure_output_dir: Callable[[str], None],
        filename_source_columns: list[str],
    ) -> LegacyRunResult:
        """고정 입력의 legacy plan부터 결과 projection까지 한 transaction으로 실행한다."""
        self.adopt_run_metadata(run)
        indices = list(capture.indices)
        decision = self.plan_legacy(
            vm,
            capture,
            indices,
            now=now,
            confirm_overwrite=confirm_overwrite,
            existing_outputs=existing_outputs,
        )
        if decision.rejection is not None:
            return LegacyRunResult({
                "ok": False,
                "error": decision.rejection.message,
                "level": decision.rejection.level,
            })
        blanks = list(decision.blanks)
        if decision.needs_overwrite:
            self.arm_overwrite(overwrite_pin_key, now)
            return LegacyRunResult(overwrite_response(
                total=len(indices),
                conflict_names=[Path(path).name for path in decision.conflicts],
            ))
        plan = decision.plan
        assert plan is not None
        outcome = run_generation(
            run,
            plan,
            engine=engine,
            progress=progress,
            capture=(ValueError, OSError),
            store=store,
            completed_at=completed_at,
            existing_outputs=existing_outputs,
            ensure_output_dir=ensure_output_dir,
        )
        if outcome.error is not None:
            self.record_result(failed=list(indices))
            return LegacyRunResult(failed_result(
                indices=indices,
                out_dir=plan.out_dir,
                message=str(outcome.error) or outcome.error.__class__.__name__,
                failed_indices=self.last_failed,
                revisions=self.run_revisions,
            ))
        if outcome.completed:
            self.record_result(generated=set(indices))
        stamped_rules_changed = bool(
            outcome.stamped_job is not None
            and rules_fingerprints(outcome.stamped_job) != run.rules
        )
        results = list(outcome.results)
        failures = failure_rows(
            records=capture.source_records,
            indices=indices,
            results=results,
            filename_source_columns=(
                filename_source_columns
                if any(
                    not result.ok
                    for _index, result in zip(indices, results, strict=False)
                )
                else []
            ),
        )
        self.record_result(failed=[failure["index"] for failure in failures])
        return LegacyRunResult(
            generation_result(
                outcome,
                blanks=blanks,
                failures=failures,
                failed_indices=self.last_failed,
                out_dir=plan.out_dir,
                revisions=self.run_revisions,
            ),
            stamped_job=outcome.stamped_job,
            stamped_rules_changed=stamped_rules_changed,
        )

    def run_managed(
        self,
        run: GenerationRun,
        managed: ManagedRunInput,
        *,
        now: datetime,
        confirm_overwrite: bool,
        overwrite_pin_key: str,
        progress: Callable[[int, int], None] | None = None,
        completion: CompletionStamp | None = None,
    ) -> ManagedRunResult:
        """준비된 managed 입력을 출력 폴더 생성부터 결과 기록까지 실행한다.

        ``progress`` 는 legacy 와 같은 진행 델타 규약이다 — 시작(0/N)을 먼저 알리고 record
        물질화마다 한 번씩 부른다. ``completion`` 이 선언되면 전건 안착(:class:`DeliveryCompleted`)
        에서만 완주를 기록한다(:func:`~hwpxfiller.application.generation.run_completed` 와 같은
        사건 — 취소·부분 안착·되읽기 실패는 완주가 아니다). 기준선은 이 런이 고정한 규칙이다.
        """
        preparation = managed.preparation
        if not isinstance(preparation.result, CurrentResolvedDelivery):
            return ManagedRunResult({
                "ok": False,
                "error": "필요한 준비를 먼저 완료해 주세요",
                "level": "warn",
            })
        resolved_delivery = preparation.result

        overwriting = [
            item.resolved_output_relative_path
            for item in resolved_delivery.ordered_items
            if item.collision_disposition == WRITE_OVERWRITE
        ]
        if overwriting and not confirm_overwrite:
            self.arm_overwrite(overwrite_pin_key, now)
            return ManagedRunResult(overwrite_response(
                total=len(preparation.record_preparation.ordered_model_indices),
                conflict_names=[Path(name).name for name in overwriting],
            ))
        validated_at = now.isoformat(timespec="seconds")
        context = managed.context
        if progress is not None:
            # 시작 델타(0/N) — legacy 와 같다: 표면 진행바가 첫 record 완료 전에 시작을 안다.
            progress(0, len(preparation.record_preparation.raw_records))
        outcome = run_managed_generation(
            root=context.root,
            workspace_instance_id=context.workspace_instance_id,
            work_authority_id=context.work_authority_id,
            plan_payload=managed.payload,
            ordered_raw_snapshots=preparation.record_preparation.raw_records,
            resolved_delivery=resolved_delivery,
            validated_at=validated_at,
            runtime_registry=context.runtime_registry,
            runtime_capability_manifest_digest=(
                context.runtime_capability_manifest_digest
            ),
            current_basis_digest_reader=context.current_basis_digest_reader,
            cancel_requested=run.cancel.is_set,
            on_progress=progress,
        )
        stamped: Job | None = None
        stamp_note = ""
        if isinstance(outcome, DeliveryCompleted) and completion is not None:
            try:
                stamped = stamp_run_completion(
                    completion.store,
                    run.job_name,
                    completion.completed_at(),
                    rules=run.rules,
                )
            except (OSError, ValueError) as exc:
                # 문서는 이미 앉았다 — 예외로 완료 서사를 날리지 않고 기존 문장으로 알린다.
                stamp_note = _record_failure_note(str(exc) or exc.__class__.__name__)
        result = self.project_managed_result(
            outcome,
            managed,
            generated_at=validated_at,
            extra_note=stamp_note,
        )
        return ManagedRunResult(
            result.payload,
            result.historical_outcome,
            executed=True,
            stamped_job=stamped,
            stamped_rules_changed=bool(
                stamped is not None and rules_fingerprints(stamped) != run.rules
            ),
        )

    @staticmethod
    def prepare_managed_output(preparation: CurrentDeliveryPreparation) -> dict | None:
        """생성 직전에만 출력 폴더를 만들고 실패 문안을 돌려준다."""
        resolved_delivery = preparation.result
        if not isinstance(resolved_delivery, CurrentResolvedDelivery):
            raise ValueError("managed output requires a resolved delivery plan")
        try:
            ensure_output_directory(resolved_delivery.output_directory)
        except OSError:
            return {
                "ok": False,
                "error": "저장 폴더를 만들 수 없습니다. 다른 폴더를 선택하세요.",
                "level": "warn",
            }
        return None

    def project_managed_result(
        self,
        outcome,
        managed: ManagedRunInput,
        *,
        generated_at: str,
        extra_note: str = "",
    ) -> ManagedRunResult:
        """managed 결과를 wire 값으로 투영하고 배달·결과 증거를 함께 갱신한다.

        ``extra_note`` 는 원장 기록 실패와 같은 문장을 쓰는 완주 기록 실패다 — 두 실패가
        겹치면 같은 문장을 두 번 싣지 않는다.
        """
        delivered_outcome = isinstance(
            outcome, (DeliveryCompleted, DeliveryAborted, ManagedReadBackFailed)
        )
        ledger_note = ""
        if delivered_outcome:
            resolved_delivery = managed.preparation.result
            if not isinstance(resolved_delivery, CurrentResolvedDelivery):
                raise ValueError("managed result requires a resolved delivery plan")
            self.record_delivery(tuple(outcome.delivered))
            try:
                write_managed_delivery_ledger(
                    resolved_delivery.output_directory,
                    generated_at=generated_at,
                    work_authority_id=managed.context.work_authority_id,
                    execution_basis_digest=managed.sealed_basis_digest,
                    plan_semantic_digest=plan_semantic_digest(managed.payload),
                    result=outcome,
                )
            except OSError as exc:
                ledger_note = _record_failure_note(str(exc))
        if extra_note and not ledger_note:
            ledger_note = extra_note
        projection = project_managed_run_result(
            outcome=outcome,
            preparation=managed.preparation,
            records=managed.capture.source_records,
            filename_source_columns=(
                managed.filename_source_columns
                if isinstance(outcome, (ManagedReadBackFailed, DeliveryAborted))
                else []
            ),
            run_revisions=self.run_revisions,
            generated_at=generated_at,
            ledger_note=ledger_note,
        )
        if projection.generated_indices is not None:
            self.record_result(generated=set(projection.generated_indices))
        if projection.failed_indices is not None:
            self.record_result(failed=list(projection.failed_indices))
        return ManagedRunResult(projection.result, projection.historical_outcome)

    def record_delivery(self, delivered: tuple[DeliveredDocument, ...]) -> None:
        self.delivered = delivered
        self.close_artifact()

    def record_result(
        self,
        *,
        generated: set[int] | None = None,
        failed: list[int] | None = None,
    ) -> None:
        if generated is not None:
            self.last_generated = generated
        if failed is not None:
            self.last_failed = failed

    def delivered_artifact(self, ordinal: int) -> DeliveredDocument | None:
        return next((d for d in self.delivered if d.item_ordinal == ordinal), None)

    def delivered_paths(self) -> tuple[str, ...]:
        return tuple(d.absolute_path for d in self.delivered)

    def discard_delivery(self) -> None:
        self.delivered = ()
        self.artifact_view = None

    def artifact_payload(self) -> dict:
        if self.artifact_view is None:
            return {
                "open": False,
                "ordinal": -1,
                "filename": "",
                "status": "",
                "detail": "",
                "structure": None,
            }
        return dict(self.artifact_view)

    def open_artifact(self, ordinal: int) -> None:
        doc = self.delivered_artifact(ordinal)
        if doc is None:
            self.artifact_view = {
                "open": True,
                "ordinal": ordinal,
                "filename": "",
                "status": ARTIFACT_NOT_IN_SESSION,
                "detail": (
                    "이 문서는 지금 세션의 생성 결과에 없습니다. "
                    "문서를 다시 만든 뒤에 내용을 볼 수 있습니다."
                ),
                "structure": None,
            }
            return
        observed = observe_delivered_artifact(
            absolute_path=doc.absolute_path,
            recorded_digest=doc.output_digest,
        )
        if isinstance(observed, ArtifactObservationRefused):
            self.artifact_view = {
                "open": True,
                "ordinal": ordinal,
                "filename": doc.relative_path,
                "status": observed.code,
                "detail": observed.detail,
                "structure": None,
            }
            return
        self.artifact_view = {
            "open": True,
            "ordinal": ordinal,
            "filename": doc.relative_path,
            "status": ARTIFACT_OBSERVED,
            "detail": "",
            "structure": observed_artifact_snapshot(observed.package),
        }

    def close_artifact(self) -> None:
        self.artifact_view = None

    def invalidate_work_results(self) -> None:
        self.last_generated = None
        self.discard_delivery()
        self.overwrite_now_pin = None

    def invalidate_data_results(self) -> None:
        self.last_generated = None
        self.discard_delivery()
        self.overwrite_now_pin = None


__all__ = [
    "CompletionStamp",
    "DocumentRunCoordinator",
    "LegacyRunResult",
    "ManagedRunInput",
    "ManagedRunResult",
    "RunInputCapture",
]
