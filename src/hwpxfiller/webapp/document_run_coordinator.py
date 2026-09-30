"""문서 생성 런의 잠금·취소·결과·배달 수명을 소유한다."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
import threading

from ..application.generation import GenerationRun, start_run
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
from ..viewmodel.run_state import RunDataInput
from ..domain.job import Job, rules_fingerprints
from .job_presentation import overwrite_response
from ..external.current_execution_preparation import CurrentDeliveryPreparation
from ..external.managed_generation import ManagedReadBackFailed, run_managed_generation
from .managed_run_result import project_managed_run_result
from ..external.seal_execution_plan_service import ManagedRunContext
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
    source_records: tuple[dict, ...]
    source_schema_keys: tuple[str, ...]
    output_directory: str
    #: 잠금 시점 `JobDataSession.records` 리스트 그 객체 — identity 토큰 전용이다.
    #: source_records(불변 스냅샷)와 달리 이 필드는 절대 순회·수정하지 않는다. "그 리스트가
    #: 재마운트로 통째로 바뀌었는가"를 `is` 비교로 재현하기 위해서만 쓴다(L-4). id() 정수를
    #: 저장하면 원본 리스트가 GC된 뒤 다른 객체가 같은 id를 재사용할 수 있어 부정확하다 —
    #: 참조 자체를 들고 있어야 `is` 비교가 항상 옳다.
    source_records_ref: "Sequence[dict]" = ()


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
    ``stamped_job``·``stamped_rules_changed`` 는 완주 기록된 Job 과 그 규칙 지문이 런 고정 규칙과
    달라졌는가다(세션 사본 채택·결과 무효화 판정에 쓴다).
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
            source_records=tuple(records),
            source_schema_keys=source_schema_keys,
            output_directory=output_directory,
            source_records_ref=records,
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
    "ManagedRunInput",
    "ManagedRunResult",
    "RunInputCapture",
]
