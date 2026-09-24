"""문서 생성 화면의 dispatch·refresh·push를 조정한다.
데이터는 ``JobDataSession``, 작업은 ``ActiveWorkSession``이 소유한다.
준비·봉인은 ``JobExecutionSession``, 실행 수명은 ``DocumentRunCoordinator``가 소유한다.
컨트롤러는 주입된 의존성을 안쪽 소유자와 순수 presentation에 연결한다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading

from ..application.generation import (
    blank_marker,
)
from ..application.jobs import (
    JobStorePort,
    job_names,
    list_jobs,
    load_job,
    rename_job,
    set_favorite,
)
from ..domain.engine import HwpxEngine
from ..application.execution_contract_set import (
    execution_basis_digest,
)

# 구체 데이터 소스는 composition root가 주입한다.
from ..data.factory import pclm_reference
from ..external.delivery_coordinator import (
    DeliveredDocument,
)
from ..external.seal_execution_capture_runner import (
    CONTEXT_ERROR_TYPES,
    context_error_code,
)
from ..domain.job import (
    Job,
    template_media,
    work_mode,
)
from ..domain.pclm_views import PCLM_VIEW_TITLES  # 계약면 제목 — 라벨은 내부 이름을 안 든다
from ..domain.output_folder_default import (
    SOURCE_REMEMBERED as OUTPUT_FOLDER_SOURCE_SETTING,
    OutputFolderResolution,
)
from .output_folder_zone import output_folder_resolution, output_folder_zone
from ..viewmodel.filter_state import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_TEXT,
)
from ..viewmodel.review_state import (
    ReviewRequirement,
    review_requirement,
)
from ..viewmodel.run_state import (
    FileSourceFactoryPort,
    GateState,
    PoolSourceFactoryPort,
    RunDataInput,
    resolve_file_source,
    resolve_pool_source,
    template_missing,
)
from ..viewmodel.tutorial_state import Milestone
from ..viewmodel.work_mode import (
    WORK_MODE_TEXT,
    seat_kinds,
)
from ..viewmodel.work_candidates import (
    prework_gate,
    unsupported_media_gate,
    workbench_entry_gate,
)
from .action_registry import ZONE_MUTATIONS
from .active_work_session import ActiveWorkSession
from .template_change import (
    NO_SOURCE_DRIFT_JUDGMENT,
    TemplateChangeError,
    unsupported_zone,
)
from ..application.slotless_run_bridge import (
    SlotlessRunAdmissionError,
)
from dataclasses import asdict
from ..application.template_change_product import workbench_template_change_verdict
from ..application.document_creation_workbench import (
    DeliveryPreviewSummary,
    DocumentCreationWorkbenchContextError,
    RecordValidationSummary,
    WorkbenchContextIntegrity,
)
from ..application.generation_delivery import (
    CurrentResolvedDelivery,
)
from ..application.fresh_execution_observation import (
    CurrentSealedPlanObservation,
)
from ..application.run_delivery_intent import (
    DEFAULT_COLLISION_POLICY,
    RunDeliveryIntent,
)
from ..domain.raw_data_record import (
    RawDataRecordSnapshot,
    RawDataRecordError,
)
from ..domain.field_binding import FieldBindingError
from .slot_configuration_product import SlotConfigurationProductError
from .current_execution_preparation import (
    CurrentRecordCaptureError as _CurrentRecordCaptureError,
    capture_selected_records,
    current_record_identity,
    record_issue,
)
from .job_execution_session import JobExecutionSession
from .managed_run_result import (
    ADMISSION_REJECT_TEXT,
)
from .job_presentation import (
    base_panel_snapshot,
    browse_payload,
    candidate_payload,
    filename_source_columns,
    record_table_rows,
    review_payload,
    serialize_observation,
    connection_label,
    work_panel_snapshot,
)

from ..external.settings import (
    load_last_data_source,
    load_last_output_directory,
    save_last_data_source,
    save_last_output_directory,
)
from .data_zone import JobDataSession
from .document_run_coordinator import (
    DocumentRunCoordinator,
    ManagedRunInput,
    RunInputCapture,
)
from .screens import (
    NO_ROWS_TEXT,
    PushSink,
    TutorialSink,
    load_pool_into,
    pool_reference_quad,
    reference_missing,
    source_label,
    unwired_tutorial,
)
from .tutorial_loop import GenerationLoopLedger

#: 부팅 복원 실패를 빈 화면으로 숨기지 않고 기존 로드 사유와 함께 알린다.
_REMEMBERED_DATA_MISSING = (
    "지난번에 사용한 데이터 파일을 찾을 수 없습니다: {path}. 데이터를 다시 고르세요."
)
_REMEMBERED_DATA_FAILED = "지난번에 사용한 데이터를 다시 불러오지 못했습니다. {reason}"

#: 재마운트는 사라질 선택 수를 확인 문안에 포함하고 실패 사유를 그대로 재진술한다.
_REMOUNT_CONFIRM = "데이터를 다시 읽으면 지금 고른 {count}건의 선택과 필터 초안이 초기화됩니다."
_REMOUNT_FAILED = "데이터를 다시 읽지 못했습니다. {reason}"

# 사전검증 성공 문구는 링2 사용자 어휘로 순화한다(실행 화면 _PREFLIGHT_OK_TEXT 동형).
_PREFLIGHT_OK_TEXT = "검증 완료. 생성할 수 있습니다."


# 전체 표시순서는 로드 순서 index의 내림/오름차순이라 동률이 없다.
class JobController:
    """문서 생성 전이를 조정하고 판정은 링1 모델에 위임한다."""

    name = "job"
    _DATA_ACTIONS = frozenset(ZONE_MUTATIONS) | {
        "filter_panel",
        "range_draft_open",
        "range_draft_apply",
        "range_draft_cancel",
        "set_selected_only",
    }

    def __init__(
        self,
        registry: JobStorePort,
        push: PushSink,
        *,
        clock: Callable[[], datetime],
        engine: HwpxEngine,
        pool_registry,
        generation_lock: "threading.Lock",
        text_registry=None,
        file_source_factory: FileSourceFactoryPort,
        pool_source_factory: PoolSourceFactoryPort,
        existing_outputs: Callable[[str, list[str]], list[str]],
        ensure_output_dir: Callable[[str], None],
        template_change=None,
        slot_configuration=None,
        workbench_observation=None,
        seal_execution=None,
        tutorial: TutorialSink = unwired_tutorial,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self._clock = clock
        self._engine = engine
        # 튜토리얼에는 이미 성립한 전이만 통지하며 여기서 다시 판정하지 않는다.
        self._tutorial = tutorial
        # 반복 실행 이력의 판정은 GenerationLoopLedger가 소유한다.
        self._tutorial_loop = GenerationLoopLedger()
        # 지난 프로세스의 기억과 섞지 않는 현재 세션의 마지막 마운트다.
        self._tutorial_last_mount: "dict | None" = None
        # 템플릿 변경·슬롯 구성·관찰·봉인 서비스는 app이 조립한다. 컨트롤러는 현재 작업
        # 이름만 붙여 호출하며, 미주입 기능은 unsupported 또는 loud 거절로 드러낸다.
        self._template_change = template_change
        self.execution = JobExecutionSession(
            slot_configuration=slot_configuration,
            workbench_observation=workbench_observation,
            seal_execution=seal_execution,
        )
        self.work = ActiveWorkSession(
            registry,
            template_change,
            engine,
            self.execution.invalidate,
        )
        self.data = JobDataSession(pool_registry)
        self.runs = DocumentRunCoordinator(generation_lock)
        # 저장 폴더와 마지막 데이터는 부팅 때 읽고 각 전용 동사만 갱신한다.
        self._remembered_output_directory = load_last_output_directory()
        self._remembered_data_source = load_last_data_source()
        # 자동 복원은 부팅 1회만 수행해 현재 사용자의 선택을 되돌리지 않는다.
        self._boot_data_restored = False
        # 자동 복원 결과는 첫 스냅샷으로만 전달한다.
        self._boot_restore_in_progress = False
        # 데이터 소스 구현은 필수 주입해 링2의 service locator 뒷문을 막는다.
        self._file_source_factory = file_source_factory
        self._pool_source_factory = pool_source_factory
        self._existing_outputs = existing_outputs
        self._ensure_output_dir = ensure_output_dir
        # TXT 템플릿은 빈 후보 안내에만 쓰며 미주입 시 실 홈을 스캔하지 않는다.
        self.text_registry = text_registry
        # 화면 간 작업대 진입은 composition root가 callable로 결선한다.
        self.workbench_open: "Callable[[Job, list], None] | None" = None
        # 전역 저장 폴더는 작업 선택 전에도 유효하다.
        self.runs.out_dir = self._output_folder_resolution().directory
        # 표시 이름은 스냅샷당 한 시각을 공유하고 실행은 진입 시각을 별도로 잡는다.
        self._names_now: "datetime | None" = None
        self._panel_snapshot: dict = {}

    # --------------------------------------------- 진행 중인 런과의 경합 거절
    def raise_if_generating(self, then_do: str) -> None:
        """실행이 고정한 입력·규칙을 바꾸는 전이를 공용 lock 판정으로 거절한다.

        ``then_do``는 끝난 뒤 가능한 행동을 사용자 어휘로 재진술한다.
        """
        self.runs.raise_if_generating(then_do)

    def raise_if_generating_before_swap(self, then_do: str) -> None:
        """데이터·작업 교체 거절에는 기다림과 중단 출구를 함께 재진술한다."""
        self.runs.raise_if_generating(then_do, swap=True)

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        if self._boot_restore_in_progress:
            return  # 부팅 자동 마운트(U3-07 #880)의 결과는 첫 스냅샷이 나른다.
        self._push_sink(self.name, self.refresh_panel())

    # ------------------------------------------------------------- 스냅샷
    # -------------------------------------------- 범위 상태 접근(커밋 vs 초안, 판정 A·D)
    def delivered_artifact(self, ordinal: int) -> "DeliveredDocument | None":
        return self.runs.delivered_artifact(ordinal)

    def delivered_artifact_paths(self) -> "tuple[str, ...]":
        """앱이 이 세션에서 배달한 경로만 소유 경로 화이트리스트에 제공한다."""
        return self.runs.delivered_paths()

    def mounted_data_descriptor(self, path: str, sheet: str = "") -> dict:
        """브리지가 방금 성립한 파일 마운트를 되돌려줄 명시 값."""
        return {
            "label": source_label("file", Path(path).name),
            "path": path,
            "sheet": sheet,
            "rows": len(self.data.records),
        }

    def owned_session_paths(self) -> "tuple[str, ...]":
        """경로 어포던스가 허용할 실행 세션의 정확한 좌표."""
        return (self.runs.out_dir, *self.runs.delivered_paths())

    def _do_artifact_open(self, p: dict) -> dict:
        """배달 문서를 디스크에서 다시 관찰하고 실패도 열린 시트에서 재진술한다.

        세션은 문서 bytes를 캐시하지 않는다.
        """
        self.runs.open_artifact(int(p["ordinal"]))
        return {"ok": True}

    def _do_artifact_close(self, p: dict) -> None:
        self.runs.close_artifact()

    def _selection_key(self) -> str:
        """파일명에 영향을 주는 표시순서까지 담은 커밋 선택 지문을 낸다."""
        return ",".join(str(i) for i in self.data.selected_indices())

    def _run_data(self) -> RunDataInput:
        return RunDataInput(self.data.datasource, tuple(self.data.records))

    def _run_marker(self, indices: "list[int]", data: "RunDataInput | None" = None) -> str:
        """표시와 생성이 공유하는 미입력 표식을 현재 실행 입력에서 계산한다."""
        if self.work.vm is None or not indices:
            return ""
        return blank_marker(self.work.vm.blank_fields(data or self._run_data(), indices))

    def _review(
        self,
        vm=None,
        indices: "list[int] | None" = None,
        blanks: "list[str] | None" = None,
        data: "RunDataInput | None" = None,
    ) -> ReviewRequirement:
        """검토 고지의 입력을 계산하며 생성 게이트로 쓰지 않는다.

        실행 경로는 고정한 vm·행·빈값을 넘겨 세션 이동 뒤에도 같은 런을 설명한다.
        """
        target = self.work.vm if vm is None else vm
        if target is None:
            return ReviewRequirement()
        idx = self.data.selected_indices() if indices is None else indices
        bl = (
            list(target.blank_fields(data or self._run_data(), idx))
            if blanks is None
            else list(blanks)
        )
        return review_requirement(target.job, blank_fields=tuple(bl))

    # ---- 위험 배너의 재료 ------------------------------------------------------
    @staticmethod
    def _drift_fields(status) -> "list[str]":
        """구조 불일치 필드 — 선택과 무관하게 차단 배너로 발화한다(결정 36·RC-23)."""
        return [st.name for st in status.field_states if st.state == "drift"]

    # ------------------------------------------------- 세션 가드(블록 4, 결정 26·27)
    def _guard_state(self, vis_set: "set[int] | None" = None) -> dict:
        """마지막 완주 집합과 현재 선택을 비교해 재현 불가능한 수작업을 판정한다.

        렌더 경로는 이미 계산한 ``vis_set``을 넘겨 필터를 이중 평가하지 않는다.
        """
        return self.data.selection_guard(
            settled=set(self.runs.last_generated or ()), vis_set=vis_set
        )

    def _do_guard_state(self, p: dict) -> dict:
        """파괴 전이 직전에 현재 무장 상태를 다시 계산한다.

        생성은 push 없이 끝날 수 있어 캐시된 guard를 신뢰하지 않는다.
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def snapshot(self) -> dict:
        """마지막으로 준비한 패널을 IO나 상태 변경 없이 복사해 반환한다."""
        return deepcopy(self._panel_snapshot)

    def refresh_panel(self) -> dict:
        """외부 상태를 읽고 실행 준비를 갱신한 뒤 패널 읽기 모델을 설치한다."""
        self._panel_snapshot = deepcopy(self._prepare_panel_snapshot())
        return self.snapshot()

    def _prepare_panel_snapshot(self) -> dict:
        """외부 작업 목록을 한 번 읽고 매체별 패널 projection을 준비한다."""
        registry_notice_text = ""
        try:
            jobs = list_jobs(self.registry)
        except Exception:  # noqa: BLE001 — 조회 장애는 빈 후보 + loud 안내로 표면화한다.
            jobs = []
            registry_notice_text = (
                "문서 작업 목록을 다시 확인할 수 없습니다. 잠시 뒤 다시 시도하세요."
            )
        base = self._prepare_base_panel(jobs, registry_notice_text)
        if self.work.is_txt:
            return self._prepare_txt_panel(base, jobs)
        if self.work.vm is None:
            return self._prepare_empty_panel(base, jobs)
        return self._prepare_hwpx_panel(base)

    def _prepare_base_panel(self, jobs: list[Job], registry_notice_text: str) -> dict:
        """Prepare branch-independent values and hand JSON shaping to the presenter."""
        notice_text = " ".join(filter(None, (self.data.notice_text, registry_notice_text)))
        notice_level = "warn" if registry_notice_text else self.data.notice_level
        run_action = self._run_action()
        output_folder = self._output_folder_dict()
        selection_key = self._selection_key()
        data_target = self.data.data_target()
        data_row = self.data.data_row()
        artifact_view = self.runs.artifact_payload()
        _handoff, blocked = self.new_work_handoff()
        fields = (
            list(self.data.records[0])
            if self.data.datasource is not None and self.data.records
            else None
        )
        bound = self.data.bound_jobs(jobs) if fields is not None else []
        txt_template_count = 0
        if (
            fields is not None
            and self.text_registry is not None
            and not any(work_mode(job.template_path) == WORK_MODE_TEXT for job in jobs)
        ):
            txt_template_count = self.text_registry.count()
        template_missing_by_path = {
            job.template_path: template_missing(job.template_path) for job in bound
        }
        candidates = candidate_payload(
            jobs=jobs,
            bound=bound,
            fields=fields,
            active_name=self.work.name,
            txt_template_count=txt_template_count,
            template_missing_by_path=template_missing_by_path,
        )
        browse = browse_payload(
            bound=bound,
            fields=fields,
            browse_tab=self.work.browse_tab,
            browse_query=self.work.browse_query,
        )
        return base_panel_snapshot(
            job_name=self.work.name,
            last_run_job=self.runs.last_run_job,
            job_data_unbound=self.work.data_unbound,
            run_action=run_action,
            out_dir=self.runs.out_dir,
            output_folder=output_folder,
            view_order=self.data.view_order,
            zone_selected_count=self.data.zone_selected_count(),
            zone_epoch=self.data.zone_epoch,
            selection_key=selection_key,
            data_mount=self.data.snapshot_generation,
            data_label=self.data.label,
            data_source_label=source_label(self.data.source_kind, self.data.label),
            data_target=data_target,
            data_row=data_row,
            data_pool_key=self.data.pool_key,
            data_notice=({"level": notice_level, "text": notice_text} if notice_text else None),
            artifact_view=artifact_view,
            new_work={"can": not blocked, "reason": blocked},
            candidates=candidates,
            browse=browse,
            range_draft=self.data.range_draft_payload(),
            template_change=unsupported_zone(),
            slot_configuration=self.execution.blank_slot_zone(),
            content_presets=self.execution.blank_presets_zone(),
        )

    def _prepare_txt_panel(self, base: dict, jobs: list[Job]) -> dict:
        zone_indices = self.data.zone_indices()
        display_order = self.data.display_indices(list(range(len(self.data.records))))
        record_rows = record_table_rows(
            records=self.data.records,
            display_order=display_order,
            selected_model_indices=zone_indices,
            mapped_records=[],
            filename_pattern=None,
            names_now=None,
            filename_source_columns=[],
        )
        filter_snapshot, table_snapshot, guard_snapshot = self.data.panel_sections(
            zone_indices,
            record_rows,
            settled=set(self.runs.last_generated or ()),
        )
        txt_job = next((job for job in jobs if job.name == self.work.name), None)
        template_path = txt_job.template_path if txt_job is not None else ""
        is_template_missing = template_missing(template_path)
        configuration_zones = self._configuration_zones(
            template_media(template_path), is_template_missing
        )
        gate = workbench_entry_gate(
            has_data=self.data.datasource is not None,
            selected_count=self.data.selection.selected_count(),
            template_ready=not is_template_missing,
        )
        return work_panel_snapshot(
            base,
            managed_hwpx=False,
            template_path=template_path,
            template_missing=is_template_missing,
            connection_label=connection_label(is_template_missing),
            filename_pattern="",
            has_data=self.data.datasource is not None,
            record_count=len(self.data.records),
            selected_count=self.data.selection.selected_count(),
            records=record_rows,
            filter_snapshot=filter_snapshot,
            table_snapshot=table_snapshot,
            guard_snapshot=guard_snapshot,
            preflight={"level": "", "text": ""},
            blank_fields=[],
            drift=[],
            name_tokens=[],
            gate={
                "enabled": gate.enabled,
                "level": gate.level,
                "text": gate.text,
                "reason": gate.reason,
            },
            review=review_payload(ReviewRequirement()),
            configuration_zones=configuration_zones,
        )

    def _prepare_empty_panel(self, base: dict, jobs: list[Job]) -> dict:
        zone_indices = self.data.zone_indices()
        display_order = self.data.display_indices(list(range(len(self.data.records))))
        record_rows = record_table_rows(
            records=self.data.records,
            display_order=display_order,
            selected_model_indices=zone_indices,
            mapped_records=[],
            filename_pattern=None,
            names_now=None,
            filename_source_columns=[],
        )
        filter_snapshot, table_snapshot, guard_snapshot = self.data.panel_sections(
            zone_indices,
            record_rows,
            settled=set(self.runs.last_generated or ()),
        )
        gate = prework_gate(
            has_data=self.data.datasource is not None,
            selected_count=self.data.selection.selected_count(),
            has_candidates=bool(base["candidates"]["top"]),
        )
        unsupported_job = (
            next((job for job in jobs if job.name == self.work.name), None)
            if self.work.unsupported
            else None
        )
        template_path = unsupported_job.template_path if unsupported_job is not None else ""
        if self.work.unsupported:
            gate = unsupported_media_gate()
        is_template_missing = template_missing(template_path) if self.work.name else False
        return work_panel_snapshot(
            base,
            managed_hwpx=False,
            template_path=template_path,
            template_missing=is_template_missing,
            connection_label=connection_label(is_template_missing),
            filename_pattern="",
            has_data=self.data.datasource is not None,
            record_count=len(self.data.records),
            selected_count=self.data.selection.selected_count(),
            records=record_rows,
            filter_snapshot=filter_snapshot,
            table_snapshot=table_snapshot,
            guard_snapshot=guard_snapshot,
            preflight={"level": "", "text": ""},
            blank_fields=[],
            drift=[],
            name_tokens=[],
            gate={
                "enabled": gate.enabled,
                "level": gate.level,
                "text": gate.text,
                "reason": gate.reason,
            },
            review=review_payload(ReviewRequirement()),
        )

    def _prepare_hwpx_panel(self, base: dict) -> dict:
        assert self.work.vm is not None
        job = self.work.vm.job
        # S6-05(#812) 의미 3 파생 전환: bool(authority_id) 는 slotless 발급 작업까지 managed 로
        # 취급해 generate-once 트랩(#806 R1)의 곱 반대편 항이었다. managed 는 「materialization
        # 대상인가」= slot-bearing 사실(링1 projection 이 이미 소유)에서 파생한다.
        managed_hwpx = self._is_managed_hwpx_work(job)
        indices = self.data.selected_indices()
        # 빈 값 집합 1회 계산(U2 §2.13 단일 술어) — 표식(marker)·빈 값 표지(blank_fields)·
        # 요구 판정(blank_set)까지 전부 이 한 집합을 소비한다. 표식이 붙으면 파일명 패턴이
        # 그 필드를 참조할 때 이름·수렴·경로 길이가 전부 달라진다(1R P2 · 4R P2) —
        # 표시와 생성이 같은 술어를 공유해야 하는 이유.
        run_data = self._run_data()
        blanks = self.work.vm.blank_fields(run_data, indices) if indices else []
        marker = blank_marker(blanks)
        # 검토 요구(F5) — 판정은 durable 기준선이 진다(승인 대조는 #957 에서 사망).
        req = self._review(indices=indices, blanks=blanks, data=run_data)
        # 파일명 날짜 토큰의 기준 시각 — **이 스냅샷의 것**이다(#957 재정의).
        #
        # 종전엔 미리보기가 본 이름을 붙들려고 「보는 동안·승인이 서 있는 동안·본 뒤 입력이
        # 그대로인 동안」 세 조건으로 이 값을 얼렸다. 그 세 조건은 전부 확인 면의 사건이었고,
        # 면이 사라진 지금 남으면 아무도 기대지 않는 값을 얼리는 죽은 규칙이다.
        #
        # 지금 계약은 둘로 갈린다. **표시**는 스냅샷당 1회 캡처라 한 스냅샷 안의 소비처(게이트
        # 감사·표 「문서」 열·이름 계획)가 서로 맞고, **생성**은 실행 진입 시 1회 캡처라 한 런의
        # 이름·본문·충돌 판정이 한 시각을 말한다. 두 시각이 갈리는 것은 결함이 아니다 — 확인의
        # 자리가 만들어진 문서로 옮겨졌기 때문이다(#957). 다만 **덮어쓰기 확인 왕복** 안에서는
        # 갈리면 안 되고, 그 일치는 :attr:`_overwrite_now_pin` 이 진다.
        self._names_now = self._clock()
        # 선택분 매핑 적용은 표식 유/무 각 1회 — 표식 없는 판(빈 값 자리 판정)과 생성
        # 입력 판(_record_rows·확인 면)이 공유한다(이중 적용 방지).
        #
        # 본문의 ``today``(오늘 날짜) 유형도 **이 시각**을 쓴다(U4-E1 #939): 위에서 파일명
        # 날짜 토큰용으로 캡처한 값을 그대로 넘겨 한 스냅샷 안에서 이름과 본문이 한 시각을
        # 말한다. 여기서 따로 찍으면 표 「문서」 열과 본문 미리 값이 하위-일 경계에서 갈린다.
        mapped = (
            self.work.vm.mapped_records(run_data, indices, now=self._names_now) if indices else []
        )
        run_mapped = (
            self.work.vm.mapped_records(run_data, indices, marker, now=self._names_now)
            if marker
            else mapped
        )
        # 검토 요구는 **게이트가 아니라 고지**로 넘긴다(#957) — 해소 사건이 없으므로
        # 요구 자체가 사전검증 고지의 입력이다.
        configuration_gate = None
        if self._template_change is not None and job.media == "hwpx" and not managed_hwpx:
            verdict = self._template_change.generation_provenance_verdict(self.work.name)
            if verdict != "EXECUTION_ALLOWED":
                configuration_gate = GateState(
                    False,
                    "warn",
                    ADMISSION_REJECT_TEXT[verdict],
                    reason=verdict,
                )
        status = self.work.vm.refresh(  # 사전검증+배지+게이트+이름 계획 단일 산출(RC-23)
            run_data,
            indices,
            self.runs.out_dir,
            review_notice=req,
            mapped=run_mapped,
            now=self._names_now,
            configuration_gate=configuration_gate,
        )
        drift_fields = self._drift_fields(status)
        # 표는 **존 대상**을 그린다(F3 판정 D): 초안이 열려 있으면 그 선택·축으로 이름까지
        # 다시 계획한다 — 이름이 커밋 기준이면 편집기 안에서 순서를 바꿔도 「문서」 열이 안
        # 움직여 판정 I 의 완화가 하필 그 축을 만지는 자리에서 죽는다. 초안이 없으면 위에서
        # 이미 계산한 실행 입력·매핑을 그대로 재사용한다(평시 추가 비용 0).
        has_draft = self.data.range_draft is not None
        zone_indices = self.data.zone_indices() if has_draft else indices
        zone_mapped = run_mapped
        if has_draft:
            # 초안 집합의 표식은 그 집합에서 다시 센다 — 빈 값 여부는 선택에 딸린 사실이다.
            zone_marker = self._run_marker(zone_indices, run_data)
            zone_mapped = (
                self.work.vm.mapped_records(
                    run_data, zone_indices, zone_marker, now=self._names_now
                )
                if zone_indices
                else []
            )
        display_order = self.data.display_indices(list(range(len(self.data.records))))
        record_rows = record_table_rows(
            records=self.data.records,
            display_order=display_order,
            selected_model_indices=zone_indices,
            mapped_records=zone_mapped,
            filename_pattern=job.filename_pattern,
            names_now=self._names_now,
            filename_source_columns=filename_source_columns(
                job,
                tuple(self.data.records[0]) if self.data.records else (),
            ),
        )
        filter_snap, table_snap, guard_snap = self.data.panel_sections(
            zone_indices,
            record_rows,
            settled=set(self.runs.last_generated or ()),
        )
        # 템플릿 부재 시에만 복구 동선(다시 연결)을 노출한다(F30) — 홈 카드와 대칭. 술어·
        # 문안은 `_template_conn` 단일 출처이고, 이 축이 **재연결 도달 보장**을 진다
        # (#342 3R): 조건 없는 세션 값이라 데이터·호환성·순위와 무관하게 흐른다.
        tmissing = template_missing(job.template_path)
        tconn = connection_label(tmissing)
        configuration_zones = self._configuration_zones(job.media, tmissing)
        # 작업대 Observation(SX-03 #726) — currentness/admission/readiness/7상태/Primary Action 을
        # 한 사용자 작업대 상태로 노출한다. 판정·합성은 Product 소유(링2 재판정 0). 미조립·미선택·
        # 템플릿 부재면 unsupported(조용히 비우지 않는다).
        workbench_observation = self._workbench_observation_zone(tmissing)
        # 사전검증의 필드 판정이 통과해도 행 미선택·실행 준비 부족이면 생성 가능하다는
        # 뜻이 아니다. 실제 생성 동사의 판정을 그대로 읽고, 비차단 고지는 보존한다.
        if status.preflight.level == "ok":
            can_create = status.gate.enabled and (
                not managed_hwpx
                or workbench_observation.get("create_action", {}).get("enabled") is True
            )
            preflight_text = "\n".join(
                ((_PREFLIGHT_OK_TEXT,) if can_create else ()) + status.preflight.notices
            )
        else:
            preflight_text = status.preflight.text
        name_tokens = (
            self.work.vm.unresolved_name_tokens() if status.gate.reason == "name_tokens" else []
        )
        return work_panel_snapshot(
            base,
            managed_hwpx=managed_hwpx,
            template_path=job.template_path,
            template_missing=tmissing,
            connection_label=tconn,
            filename_pattern=job.filename_pattern,
            has_data=self.data.datasource is not None,
            record_count=len(self.data.records),
            selected_count=self.data.selection.selected_count(),
            records=record_rows,
            filter_snapshot=filter_snap,
            table_snapshot=table_snap,
            guard_snapshot=guard_snap,
            preflight={"level": status.preflight.level, "text": preflight_text},
            blank_fields=blanks,
            drift=drift_fields,
            name_tokens=name_tokens,
            gate={
                "enabled": status.gate.enabled,
                "level": status.gate.level,
                "text": status.gate.text,
                "reason": status.gate.reason,
            },
            review=review_payload(req),
            rules_key=req.rules_key,
            workbench_observation=workbench_observation,
            configuration_zones=configuration_zones,
        )

    def initial(self) -> dict:
        """화면 부팅 스냅샷 — 기억한 데이터를 **먼저** 마운트한다(U3-07 · #880).

        마운트를 여기서 하는 이유는 자리 하나뿐이기 때문이다: 첫 렌더에 이미 데이터가 서
        있어야 「매 세션 데이터를 다시 고른다」가 사라진다. 컨트롤러 생성 시점에 하면 창이
        뜨기 전 디스크 읽기가 부팅을 막고, 첫 dispatch 로 미루면 첫 화면이 빈 채로 한 번
        그려진다.
        """
        self._restore_remembered_data()
        return self.refresh_panel()

    # ------------------------------- 마지막 사용 데이터 기억·복원(U3-07 · #880)
    def _remember_data_source(self) -> None:
        """성사된 마운트의 성분을 설정에 남긴다 — 다음 부팅 자동 마운트의 재료.

        **세 마운트 경로가 같은 한 자리를 부른다**(파일 피커 → :meth:`load_data_path`,
        풀 겨눔 → :meth:`_after_pool_load`, 계약 목록 → :meth:`_mount_pclm`). 계약 목록은
        슬롯이 없어 파일 갈래와 같은 성분(``path``=db·``sheet``=뷰)을 쓰고, 출처 축
        (``source``)이 그 성분을 **어느 어댑터로 읽을지**를 말한다(#937). 성분은 세션이 그 마운트 시점에 포획해 둔
        것을 그대로 읽는다(``JobDataSession.new_work_handoff``와 같은 재료) — 여기서
        슬롯이나 파일을 다시 읽어 조립하면 지금
        화면에 없는 데이터를 기억하게 된다.

        기억은 **설정 층 소유**다: 풀 스키마(``DatasetReference``)는 건드리지 않는다.
        """
        descriptor = {
            "source": self.data.source_kind,
            "path": self.data.path,
            "sheet": self.data.sheet,
            "header_row": self.data.header_row,
            "pool_key": self.data.pool_key,
        }
        self._remembered_data_source = descriptor
        save_last_data_source(**descriptor)
        # T4/T12 데이터 마운트(#894) — 판정 축은 **마운트 성립 사실**이다(§3.2 부기): 「사용자가
        # 골랐는가」로 세우면 U3-07 의 부팅 자동 마운트가 달성으로 안 쳐져, 두 번째 세션부터
        # 체크리스트가 실제 진행보다 뒤처진다. 세 마운트 경로(파일 피커·풀 겨눔·부팅 복원)가
        # 전부 이 한 자리로 모이므로 통지도 여기 하나다.
        self._tutorial(Milestone.MOUNT_DATA)
        # T12 는 **이 세션 안에서의 교체**다. 비교 대상을 위의 `_remembered_data_source` 로
        # 두면 안 된다 — 그 칸은 부팅 때 지난 세션 값으로 이미 차 있어서(`load_last_data_source`),
        # 첫 마운트가 곧 교체로 읽힌다. 그래서 세션 전용 칸을 따로 든다: 같은 데이터를 다시
        # 세운 것(부팅 복원)은 교체가 아니고, 교체는 두 번째 마운트부터다.
        if self._tutorial_last_mount is not None and self._tutorial_last_mount != descriptor:
            self._tutorial(Milestone.REPLACE_DATA)
        self._tutorial_last_mount = descriptor

    def _restore_remembered_data(self) -> None:
        """부팅 1회 — 기억한 성분으로 데이터를 마운트하고, 실패는 사유를 싣는다.

        **성공은 손으로 마운트한 것과 같은 세션 상태**다(선택 0건·표시순서 기본·필터 재생성)
        — 같은 진입점(:meth:`load_data_path` / ``_do_load_pool``)을 타기 때문이다. 자동
        마운트는 사용자가 하던 「파일 다시 고르기」를 대신할 뿐이라 작업 선택·실행 상태는
        건드리지 않는다(부팅 시점의 그 둘은 어차피 비어 있다).

        **실패에서 기억을 지우지 않는다**: 외장 드라이브·네트워크 경로의 부재는 일시적일 수
        있고, 지운 기억은 그 드라이브가 돌아와도 되살아나지 않는다. 매 부팅 다시 시도하되
        사유는 그때마다 문안으로 말한다(조용한 빈 상태 금지).
        """
        if self._boot_data_restored:
            return
        self._boot_data_restored = True
        descriptor = self._remembered_data_source
        if not descriptor or self.data.source_kind:
            return  # 기억 없음(기존 settings.json) 또는 이미 마운트됨 = 기존 부팅 그대로
        self._boot_restore_in_progress = True
        try:
            refusal = self._mount_remembered_data(descriptor)
        finally:
            self._boot_restore_in_progress = False
        if refusal:
            self.data.notice_text = refusal
            self.data.notice_level = "warn"

    def _mount_remembered_data(self, descriptor: dict) -> str:
        """기억한 성분으로 마운트 — 성사면 ``""``, 실패면 **사유 문구**(상태는 빈 채).

        사유는 기존 로드 관문이 이미 낸 문장을 이어 붙인다(새 채널·새 문안 발명 금지):
        풀 경로는 :func:`~hwpxfiller.webapp.screens.load_pool_into` 의 거절(나라 동결·삭제된
        항목·죽은 참조·0행)이, 파일·계약 목록 경로는 소스 해석 예외와 :data:`NO_ROWS_TEXT`
        가 낸다. 파일 부재만 마운트를 시도하기 전에 가른다 — 판정은 풀 목록의 「끊김」
        배지와 **같은 술어**(:func:`~hwpxfiller.application.dataset_pool.reference_missing`)이고,
        계약 목록 db 도 그 술어의 대상이다(가리키는 것이 파일이면 종류를 묻지 않는다).
        """
        if descriptor["source"] == "pool":
            result = self._do_load_pool({"key": descriptor["pool_key"]})
            if result.get("ok"):
                return ""
            return _REMEMBERED_DATA_FAILED.format(reason=result.get("error", ""))
        path = descriptor["path"]
        if reference_missing(path):
            return _REMEMBERED_DATA_MISSING.format(path=path)
        try:
            if descriptor["source"] == "pclm":
                # 계약 목록 기억은 db+뷰 한 벌이다(#937) — 출처 축이 이미 종류를 말하므로
                # descriptor 에 종류를 따로 두지 않는다(둘이 어긋난 기억이 성립하지 않게).
                self._mount_pclm(path, descriptor["sheet"])
            else:
                self.load_data_path(path, sheet=descriptor["sheet"] or None)
        except Exception as exc:  # noqa: BLE001 — 읽기 실패는 사유 불문 loud 재진술
            return _REMEMBERED_DATA_FAILED.format(reason=exc)
        return ""

    def new_work_handoff(self) -> "tuple[dict, str]":
        """현재 마운트의 작업 생성용 데이터 참조를 반환한다."""
        return self.data.new_work_handoff()

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(
        self,
        path: str,
        *,
        sheet: "str | None" = None,
        header_row: int = 0,
    ) -> None:
        """선택된 데이터 파일을 세션에 마운트. 레코드 0건이면 시끄럽게 실패.

        **데이터-우선(§18.2)**: 작업 미선택에도 마운트할 수 있다. 데이터는 세션이 소유하고
        VM 평가는 그 세션에서 포획한 ``RunDataInput``을 받는다. 마운트 직후 선택은 **0건**이다
        (§18.2 commit 뒤 초기화 — 구 전체선택 계약의 개정, 봉합 지도 충돌 A).

        ``sheet`` 는 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트).
        시그니처 동형 — 브리지 ``pick_data_file``/``load_data_sheet`` 재사용.

        ``header_row`` 는 참조가 들고 있던 읽기 옵션의 승계 자리다(0 = 어댑터 기본).
        사람이 파일 피커에서 직접 고르는 경로는 이 옵션을 만들지 않아 늘 0이고, 값이 오는
        곳은 둘이다 — 풀 참조가 포획한 값과 **작업의 데이터 결속**(#932 U4-C). 결속을
        경로+시트로만 되읽으면 헤더 행이 다른 표를 같은 데이터라고 부른다.
        """
        self.raise_if_generating_before_swap("데이터를 바꾸세요")  # #302 P1 동류
        source, records = resolve_file_source(
            path,
            sheet=sheet,
            header_row=header_row,
            source_factory=self._file_source_factory,
        )  # 실패는 raise(§18.2 원자)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 성공 전 현재 runtime 미파기 — 아래 대입 전 반환
        self.runs.last_failed = []  # 실패 index 는 이 레코드 집합에서만 뜻이 있다(§10.10 판정 F)
        self._commit_data_mount(
            datasource=source,
            records=records,
            incoming=(path, sheet or "", header_row, ""),
            label=Path(path).name,
            source_kind="file",
            path=path,
            sheet=sheet or "",
            header_row=header_row,
            kind="",
            data_key=self.data.file_key(path, sheet),
        )
        try:
            self._remember_data_source()  # 다음 부팅 자동 마운트의 재료(U3-07 #880)
        finally:
            self._push()

    def _mount_pclm(self, db: str, view: str) -> None:
        """계약 목록(pclm) 뷰를 세션에 마운트 — :meth:`load_data_path` 의 **자매**(#937).

        본문 순서가 파일 마운트와 같은 이유는 그 순서 자체가 계약이기 때문이다: 생성 중
        거절 → 읽기(성공 전 현 runtime 미파기) → 직전 필터 스태시(옛 소스 키 기준) →
        전이 판정 → 세션 성분 → 소스 키 → 범위·필터 재생성 → 기억 → 푸시. 한 자리라도
        순서를 달리하면 이 화면의 불변식이 종류별로 갈린다.

        **소스는 링1 리졸버를 지난다**(:func:`~hwpxfiller.viewmodel.run_state.resolve_pool_source`)
        — 구체 선택은 유일한 제품 조립점이 주입한 factory 의 몫이라(P2-16), 여기서
        ``PclmDataSource`` 를 직접 만들면 링2 가 구체를 조용히 재선택하는 뒷문이 된다.
        풀 슬롯이 없는 마운트라 참조 형상은 :func:`~hwpxfiller.data.factory.
        pclm_reference` 가 짓는다(U6-F #980 이사 — 형상·복원이 한 층에 산다).

        읽기 실패(db 부재·뷰 손상·미지 뷰)는 삼키지 않고 그대로 올린다 — 호출자
        (결속 마운트·부팅 복원·재마운트)가 자기 채널의 문안으로 재진술한다.
        """
        self.raise_if_generating_before_swap("데이터를 바꾸세요")  # #302 P1 동류
        source, records = resolve_pool_source(
            pclm_reference(db, view),
            source_factory=self._pool_source_factory,
        )
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 성공 전 현재 runtime 미파기 — 아래 대입 전 반환
        self.runs.last_failed = []  # 실패 index 는 이 레코드 집합에서만 뜻이 있다(§10.10 판정 F)
        # 라벨에 면을 병기한다 — db 하나에 계약면이 넷이라 파일 이름만으로는 **무엇이 서
        # 있는지**를 말하지 못한다(엑셀의 `data_binding_label` 이 시트를 병기하는 것과 같은
        # 규율). 스냅샷 `data_target` 과 겹치는 것이 아니라, 저쪽은 성분이고 이쪽은 한 줄이다.
        # 병기하는 것은 **제목**이다: 라벨은 사람이 읽는 한 줄이라 내부 이름(`v_통합_v1`)이
        # 여기로 새면 결속 마운트 notice·소스 라벨까지 그 이름을 지고 다닌다. 미지 이름은
        # 감추지 않고 원문 그대로 남긴다(구판·손편집을 조용히 지우지 않는다).
        self._commit_data_mount(
            datasource=source,
            records=records,
            incoming=(db, view, 0, "pclm"),
            label=f"{Path(db).name} · {PCLM_VIEW_TITLES.get(view, view)}",
            source_kind="pclm",
            path=db,
            sheet=view,
            header_row=0,
            kind="pclm",
            data_key=self.data.pclm_key(db, view),
        )
        try:
            self._remember_data_source()  # 다음 부팅 자동 마운트의 재료(U3-07 #880)
        finally:
            self._push()

    def _mount_by_kind(self, path: str, sheet: str, header_row: int, kind: str) -> None:
        """결속 한 벌의 **종류로 마운트 경로를 가른다** — 종류 해석의 단일 자리(#937).

        여기 이름 없는 종류는 시끄럽게 거절한다(:func:`~hwpxfiller.data.factory.make_source`
        와 같은 규율): 모르는 종류를 파일 갈래로 흘려보내면 db 를 엑셀로 오파싱하거나
        확장자 거절이 「데이터 파일 형식」 문안으로 둔갑해 실제 사유를 덮는다.
        """
        if kind == "pclm":
            self._mount_pclm(path, sheet)
            return
        if kind:
            raise ValueError(f"알 수 없는 데이터 결속 종류입니다: {kind!r}")
        self.load_data_path(path, sheet=sheet or None, header_row=header_row)

    def _commit_data_mount(
        self,
        *,
        datasource,
        records: list,
        incoming: "tuple[str, str, int, str]",
        label: str,
        source_kind: str,
        path: str,
        sheet: str,
        header_row: int,
        kind: str,
        data_key: str,
        pool_key: str = "",
    ) -> None:
        """Work 재조정 뒤 데이터 마운트 한 벌을 원자 커밋한다."""
        reconciliation = self.work.reconcile_data_transition(incoming)
        self.data.clear_notice()
        if reconciliation.release:
            self._release_active_work()
        self.data.commit_mount(
            datasource=datasource,
            records=records,
            label=label,
            source_kind=source_kind,
            path=path,
            sheet=sheet,
            header_row=header_row,
            kind=kind,
            pool_key=pool_key,
            data_key=data_key,
        )
        self._apply_preferred_work()  # 보관된 명시 사건(§18.3 1행)을 이 데이터에서 판정
        self.data.install_filter(self.data.records, self._data_filter_hints())
        if reconciliation.warning:
            preferred = f" {self.data.notice_text}" if self.data.notice_text else ""
            self.data.notice_text = reconciliation.warning + preferred
            self.data.notice_level = "warn"
        self._invalidate_data_results()

    # ── 저장 폴더 도출(U3-06 · #879 → 전역화) ────────────────────────────────────
    def _output_folder_resolution(self) -> OutputFolderResolution:
        """실제로 쓸 저장 폴더 + 출처 + 사유 — ① 설정한 전역 폴더 ② 템플릿 옆 Results.

        판정은 링0 순수 함수(:func:`resolve_output_folder`)가 지고 관찰(설정한 폴더가 지금도
        있는가)은 공용 함수 :func:`~hwpxfiller.webapp.output_folder_zone.output_folder_resolution`
        이 진다 — 편집기 3단계의 읽기 전용 재진술이 **같은 함수**를 부른다(U6-D #978). 도출
        결과는 스냅샷에 실려 저장 폴더 표시·생성 예정 문서 계획·설정 모달에 그대로 나간다 —
        조용한 추측이 아니라 표시된 값이다.

        **도출의 단일 출입구다.** managed 축의 delivery intent 도, 구식 축의 ``out_dir`` 도
        여기를 지나야 한다 — 한쪽만 다른 자리에서 경로를 조립하면 두 축이 같은 상태를 두
        답으로 말한다(그것이 종전 세션 명시 지정 축에서 실제로 샜던 자리다).
        """
        return output_folder_resolution(
            template_path=(self.work.vm.job.template_path if self.work.vm is not None else ""),
            remembered_directory=self._remembered_output_directory,
        )

    def _effective_delivery(self) -> "tuple[RunDeliveryIntent | None, OutputFolderResolution]":
        """delivery 해결에 실제로 쓰이는 intent + 그 폴더의 출처(한 번의 도출로 둘 다).

        도출조차 불가능한 경우(템플릿 경로 부재)만 intent 가 ``None`` 이고, 그때만 저장 폴더
        지정이 생성의 전제조건으로 남는다. 충돌 처리는 세션 선언을 그대로 싣는다 — 여기서
        durable state 를 만들지 않는다(intent 수명 규약 불변). intent 는 **매번 도출에서
        물질화**된다: 세션이 들고 있던 명시 지정 축은 전역화로 사라졌다.
        """
        resolution = self._output_folder_resolution()
        if not resolution.resolved:
            return None, resolution
        return (
            RunDeliveryIntent(resolution.directory, self.runs.delivery_collision),
            resolution,
        )

    def _effective_run_delivery_intent(self) -> "RunDeliveryIntent | None":
        """실제로 쓰이는 intent만 — 출처가 필요한 호출부는 :meth:`_effective_delivery` 를 쓴다."""
        return self._effective_delivery()[0]

    def remembered_output_directory(self) -> str:
        """설정된 **전역 저장 폴더**의 지금 값 — 읽기 전용 공개 seam(U6-D #978 리뷰 3).

        이 값의 소유자는 이 컨트롤러 하나다(부팅 1회 판독 + :meth:`set_output_folder` 만이
        바꾼다). 편집기 3단계의 읽기 전용 재진술이 이것을 콜러블로 받아 읽는다 — 그쪽이
        설정 파일을 따로 읽으면 쓰기가 실패한 순간 두 표면이 서로 다른 폴더를 말한다(한쪽은
        방금 고른 값, 한쪽은 디스크의 옛 값). 도출·존 성형은 여전히 공용 함수가 진다.
        """
        return self._remembered_output_directory

    def _output_folder_dict(self) -> dict:
        """스냅샷의 ``output_folder`` 존 — 성형도 **공용 함수 하나**다(U6-D #978).

        존의 모양(키 넷)을 화면마다 다시 적으면 링0 판정이 하나여도 한쪽만 하향 사유를
        빠뜨리는 자리가 생긴다.
        """
        return output_folder_zone(
            template_path=(self.work.vm.job.template_path if self.work.vm is not None else ""),
            remembered_directory=self._remembered_output_directory,
        )

    def set_output_folder(self, path: str) -> None:
        """네이티브 폴더 피커가 고른 **전역** 저장 폴더를 세운다.

        **작업 미선택 상태에서도 유효하다.** 이것이 전역화가 바꾼 계약이다: 종전에는 저장
        폴더가 작업 속성이라 작업이 앉기 전에 고르면 작업 선택이 기본값으로 조용히 덮어썼고,
        그래서 화면은 작업이 없을 때 폴더 선택을 잠갔다. 지금 이 값은 설정이라 앉은 작업이
        없어도 쓸 수 있고, 작업이 나중에 앉아도 덮이지 않는다 — 그래서 이 동사의 자리도
        작업 화면이 아니라 **설정 모달**이다.

        갈래별 분기도 없다: managed 면의 delivery intent 도 구식 축의 ``out_dir`` 도 같은
        도출(:meth:`_output_folder_resolution`)을 지나므로, 여기서 할 일은 설정값을 갈고
        도출을 다시 세우는 것뿐이다(종전 #905 의 「고른 폴더가 갈래에 따라 조용히 무시된다」는
        축 자체가 사라졌다).

        영속 실패는 삼키지 않고 위층(브리지)이 ``ERROR:`` 로 되돌린다 — 다만 이번 선택은 이미
        메모리에 유효하고 화면도 그것을 그려야 하므로, 재도출·push 를 끝낸 뒤에 던진다.
        """
        # delivery preparation 은 폴더에 매인 관찰이다 — 폴더가 갈리면 무효다(재관찰 유발).
        self.execution.invalidate_delivery()
        try:
            self._remember_output_folder(path)
        finally:
            self.runs.out_dir = self._output_folder_resolution().directory
            self._push()

    def _remember_output_folder(self, path: str) -> None:
        """전역 저장 폴더를 설정에 남긴다 — 도출 후보 ①.

        자동으로 잡힌 기본값은 지나가지 않는다(이 메서드의 호출자는 폴더 피커 경로 하나다).
        """
        self._remembered_output_directory = path
        save_last_output_directory(path)

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        if self.data.is_stale_edit(action, payload, set(ZONE_MUTATIONS)):
            return {"stale": True, "epoch": self.data.zone_epoch}
        owner = self.data if action in self._DATA_ACTIONS else self
        handler = getattr(owner, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 작업 화면 액션: {action!r}")
        if action in {"range_draft_open", "range_draft_apply"}:
            self.raise_if_generating(
                "범위를 편집하세요" if action.endswith("open") else "적용하세요"
            )
        result = handler(payload)
        # 무변이 경로는 push 를 생략한다(고효율 리뷰 #8) — is_query 표식 핸들러(순수 질의:
        # filter_panel·guard_state). 동일 스냅샷 전량 재계산+재렌더 낭비 제거.
        #
        # 짝이던 `needs_confirm` 갈래는 U4 §2-30 에서 **생산자 0** 이 돼 걷혔다(마지막
        # 생산자가 그룹 병합·해산 승격이었다). 이 화면에 확인 왕복을 되들이는 핸들러가
        # 생기면 그 갈래도 자기 테스트와 함께 돌아온다 — 도달 불가 분기를 남겨 두면
        # 「규칙은 있는데 결과는 없는」 계약이 된다.
        is_query = getattr(handler, "is_query", False)
        # T5 작업·행 선택(#894) — 두 사실(현재 작업 성립 · 선택 ≥1)이 **서로 다른 액션 무리**
        # 에서 세워지므로(작업 카드 선택 vs 존 변이 13종), 액션마다 훅을 달면 그 목록이 곧
        # 두 번째 판정자가 된다. 스냅샷이 이미 같은 두 값을 읽어 `has_job`·`selected_count`
        # 로 싣고 있으므로, 여기서는 그 둘을 그대로 조회해 동시 성립만 본다.
        if not is_query and bool(self.work.name) and self.data.selection.selected_count() >= 1:
            self._tutorial(Milestone.SELECT_ROWS)
        if not is_query:
            self._push()
        return result

    def _do_refresh(self, p: dict) -> "dict | None":
        """레지스트리 재스캔 반영(C6) + stale 세션 무효화(master-detail 불변식).

        레지스트리(``registry.names()``)와 세션 패널(``self.work.vm``)이 갈라지지 않게 조정한다: 선택된
        작업이 다른 화면에서 삭제·개명돼 레지스트리에서 사라졌으면 세션을 무효화한다 — 안 그러면
        존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께 남아 유령 작업에서 생성된다
        (리뷰 #2). 조용히 두지 않고 빈 패널로 재진술(후보·라이브러리에서도 사라져 상실이 보인다).
        재스캔 자체는 스냅샷이 매번 ``names()`` 를 재읽어 반영(에디터 저장분 즉시 노출).
        작업 화면은 REFRESH_ON_NAV 에 있어 이 액션이 레일 복귀마다 발화하므로, 타 화면에서의
        삭제(그 화면으로 가려면 반드시 작업 화면을 이탈)가 복귀 시점에 잡힌다.
        """
        names = job_names(self.registry)
        if self.work.name and self.work.name in names:
            # **열린 작업의 규칙이 밖에서 바뀌었으면 다시 읽는다**(4R P1). 편집기가 자기
            # 화면으로 나간 뒤(F7) 저장은 이 화면 밖에서 일어나고, `self.work.vm` 은 선택 시점의
            # 인메모리 사본이라 그대로 두면 **저장한 사람이 옛 규칙으로 미리보고 옛 규칙으로
            # 생성한다** — 영속·실행 경로가 화면 사이에서 갈리는 자리다. 세션(데이터·선택·
            # 필터·저장 폴더)은 그대로 두고 규칙만 갈아 끼운다.
            self._reload_active_job()
            return None
        if self.work.name and self.work.name not in names:
            lost = self.work.name
            # 세션 무효화(vm·job_name·데이터·폴더 clear). confirm=True — 작업이 이미
            # 레지스트리에서 사라져 가드로 잡아둘 대상이 없다(잡으면 유령 세션 좌초).
            self._do_select_job({"name": "", "confirm": True})
            return {
                "notice": f"'{lost}' 작업이 다른 화면에서 삭제되어 열어 둔 실행 세션을 닫았습니다."
            }
        return None

    def _reload_active_job(self) -> bool:
        """durable Work 변경을 실제 seat 소유자에게 반영한다."""
        outcome = self.work.reload()
        if not outcome.changed:
            return False
        if outcome.rules_changed:
            self.runs.last_generated = None
            self.runs.discard_delivery()
        return True

    def _run_action(self) -> dict:
        """실행 버튼의 (행동 키, 라벨) — 매체 파생 2분기(§19.1·F6 판정 D)."""
        if self.work.is_txt:
            n = self.data.selection.selected_count()
            return {"key": "workbench", "label": f"검토·복사 시작 · {n}건"}
        return {"key": "generate", "label": "이 작업으로 문서 생성"}

    def _do_open_workbench(self, p: dict) -> dict:
        """TXT 검토·복사 작업대 진입 — 고정 사본을 넘기고 화면 전환은 웹이 한다.

        **열기는 성사 뒤다**(§10.15.1 계약면 2·3): 자격 없는 진입은 화면을 세우지 않고
        사유를 돌려준다. 진입을 막는 것은 셋이다 — 생성 중(진행 중 런의 규칙을 갈아 끼우면
        RC-02 「확인 대상 = 생성 대상」이 깨진다) · 범위 초안 열림(작업대는 **커밋된** 실행
        입력의 사본을 뜬다 — 적용도 안 한 편집으로 사본을 뜨면 어느 범위인지 갈린다) ·
        게이트 미충족(선택 0건에서 첫 레코드를 대신 쓰지 않는다, §18.10 수용 6).
        """
        if not self.work.is_txt or not self.work.name:
            return {"ok": False, "error": "TXT 검토·복사 작업이 아닙니다."}
        self.raise_if_generating_before_swap("작업대를 여세요")
        if self.data.range_draft is not None:
            return {"ok": False, "error": "범위 편집을 먼저 적용하거나 취소한 뒤 작업대를 여세요."}
        gate = workbench_entry_gate(
            has_data=self.data.datasource is not None,
            selected_count=self.data.selection.selected_count(),
        )
        if not gate.enabled:
            return {"ok": False, "error": gate.text}
        if self.workbench_open is None:  # confirm-or-alarm: 미배선은 시끄럽게(조용한 무동작 금지)
            raise ValueError("작업대 컨트롤러가 배선되지 않았습니다.")
        # Job 은 **쓰는 순간** 읽는다(1R P2) — 세션이 사본을 들고 있으면 그사이 이름이
        # 바뀌거나 규칙이 저장된 것을 못 본다. 여기가 유일한 소비처라 I/O 도 1회다.
        try:
            job = load_job(self.registry, self.work.name)
        except (FileNotFoundError, ValueError) as exc:
            return {
                "ok": False,
                "error": (f"작업 '{self.work.name}' 을(를) 읽을 수 없습니다: {exc}"),
            }
        # fail-closed 재확인(매체가 갈렸다면) — 판정은 링1 착석 분류(`seat_kinds`)와 같은
        # 술어다: 작업대의 진입 자격을 상대 화면에 물으면 화면 간 결합이 되살아난다(P2-24).
        if not seat_kinds(job.template_path)[0]:
            return {"ok": False, "error": "TXT 검토·복사 작업이 아닙니다."}
        indices = self.data.selected_indices()
        try:
            self.workbench_open(job, [(i, self.data.records[i]) for i in indices])
        except (OSError, UnicodeDecodeError) as exc:
            # 템플릿이 그사이 사라졌거나 읽을 수 없다 — **화면 안에서** 사유를 말한다(5R P2).
            # 날것 예외로 올리면 호출부(.then)가 못 받아 아무 설명 없이 아무 일도 안 난 것처럼
            # 보인다. 게이트도 이 사실을 미리 세지만(버튼이 정직하게 닫힌다) 그 판정과 이
            # 진입 사이에도 파일은 사라질 수 있으므로 둘 다 필요하다.
            #
            # **`UnicodeDecodeError` 도 같은 사건이다**(6R). 작업대는 UTF-8 로 읽는데 온나라
            # 기안 txt 는 ANSI/CP949 로 저장돼 오기 쉽고, 게이트는 파일 **존재**만 세므로
            # 버튼은 열려 있다. `OSError` 가 아니라 `ValueError` 계열이라 잡지 않으면 사유를
            # 말할 자리를 그대로 지나쳐, 열리는 척하던 버튼이 아무 말도 없이 끝난다.
            return {
                "ok": False,
                "error": (f"템플릿을 읽을 수 없습니다: {exc}. 템플릿을 다시 연결한 뒤 진행하세요."),
            }
        return {"ok": True, "count": len(indices)}

    def _do_remount_data(self, p: dict) -> dict:
        """현재 데이터를 **다시 읽는다**(U4 항목 5 · #932 U4-C) — 같은 참조, 새 레코드.

        ## 왜 「새로고침」이 재마운트인가

        이 앱에는 **stale 판정 술어가 없다**: 데이터는 마운트마다 디스크에서 다시 읽히고,
        mtime·해시 추적은 템플릿 축에만 있다. 그래서 「파일이 바뀌었는지」를 물을 수 없고,
        요구의 실체는 「지금 화면의 레코드를 지금 디스크로 갈아 끼워라」다. 결속이 durable
        이 된 뒤(§2.4) 같은 파일이 갱신되는 것이 흔한 사건이 되므로 이 동사가 짝이 된다.

        **새 마운트 경로를 만들지 않는다.** 세션이 마운트 시점에 포획해 둔 참조를
        그대로 기존 진입점(:meth:`load_data_path` / ``_do_load_pool`` /
        :meth:`_mount_pclm`)에 되돌려 준다 —
        부팅 복원(:meth:`_mount_remembered_data`)이 이미 같은 패턴이고, 여기서 성분을
        다시 조립하면 지금 화면에 없는 데이터를 새로고침하게 된다.

        ## 무엇이 사라지는지 먼저 말한다

        재마운트는 마운트와 **같은 seam** 을 타므로 선택·필터 초안·열 선별이 초기화된다
        (:meth:`_reset_range_for_snapshot`). 고른 행이 있는데 조용히 지우면 그것이 곧
        무확인 파괴라, 선택이 1건 이상이면 ``needs_confirm`` 왕복으로 **사라지는 집합을
        열거**한 뒤에만 실행한다. 0건이면 잃을 것이 없으므로 바로 돈다(없는 위험에
        확인을 물리면 그 확인이 다음 진짜 확인의 무게를 깎는다).
        """
        if not self.data.source_kind:
            return {"ok": False, "error": "다시 읽을 데이터가 없습니다. 데이터를 먼저 고르세요."}
        selected = self.data.selection.selected_count()
        if selected and not p.get("confirm"):
            return {
                "ok": True,
                "needs_confirm": True,
                "confirm_text": _REMOUNT_CONFIRM.format(count=selected),
            }
        if self.data.source_kind == "pool":
            return self._do_load_pool({"key": self.data.pool_key})
        try:
            if self.data.source_kind == "pclm":
                # 슬롯 없는 마운트라 되돌려 줄 진입점이 파일 갈래가 아니다(#937) — 성분은
                # 여기서도 세션이 포획해 둔 것을 그대로 쓴다(재조립 금지, 위 규율 그대로).
                self._mount_pclm(self.data.path, self.data.sheet)
            else:
                self.load_data_path(
                    self.data.path,
                    sheet=self.data.sheet or None,
                    header_row=self.data.header_row,
                )
        except Exception as exc:  # noqa: BLE001 — 사유 불문 loud 재진술
            return {"ok": False, "error": _REMOUNT_FAILED.format(reason=exc)}
        return {"ok": True, "label": source_label(self.data.source_kind, self.data.label)}

    def _mount_job_binding(self, job: Job) -> str:
        """선택 작업의 결속 판정에 따라 필요한 데이터 마운트만 실행한다."""
        decision = self.work.data_binding_mount(
            job,
            (self.data.path, self.data.sheet, self.data.header_row, self.data.kind),
        )
        if decision.action != "mount":
            return decision.notice
        try:
            self._mount_by_kind(
                decision.path,
                decision.sheet,
                decision.header_row,
                decision.kind,
            )
        except Exception as exc:  # noqa: BLE001 - the successful Work selection remains usable.
            return f"이 작업에 연결된 데이터를 불러오지 못했습니다. {exc}"
        return (
            f"이 작업에 연결된 데이터 '{self.data.label}' 을(를) 불러왔습니다. "
            "항목 선택은 초기화됐습니다."
        )

    def _do_select_job(self, p: dict) -> "dict | None":
        """후보·탐색에서 작업 선택 → RunViewModel 재구성. 저장 폴더 기본 = 템플릿/Results.

        **데이터-우선 보존 계약(§18.2)**: 데이터·선택·필터는 세션 소유라 작업 전환에서
        **생존**한다. 전환은 작업 규칙을 담은 VM만 재생성한다.
        전환이 잃는 것은 실행 증거(완주 담보)뿐이고(§19.10) 게이트가 재검증을 강제하므로
        조용한 소실이 없다. 구 T1 스위치 가드(전환=세션 파기 재확인)는 파기 자체가 사라져
        함께 죽었다 — 가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고=거짓말).
        ``confirm`` 페이로드 키는 왕복 동형 유지를 위해 수용하되 더는 판정에 쓰지 않는다.

        **작업 선택은 그 작업의 데이터를 세운다**(U4 §2.4, #932 U4-C — U2 §5.3 판정 D 의
        명시 철회). 종전 서술은 「작업 선택은 데이터를 세우지 않는다」였고 그 귀결이
        「작업을 열면 데이터가 이미 서 있다」의 소멸이었다. 결속이 durable 이 된 지금
        작업은 자기 데이터를 들고 오고, 이미 그 데이터가 서 있으면 아무 일도 하지 않는다.
        결속이 없는 구판 작업은 조용히 지나간다 — 「데이터 연결 필요」는 게이트가 말한다.
        """
        name = p["name"]
        # 생성 진행 중 전환 금지(#302 P1) — vm 교체가 진행 중 배치의 검증·계획과 경합한다.
        # 조용한 무시가 아니라 시끄러운 거부(raise → 셸 rejection 백스톱이 표면화).
        self.raise_if_generating_before_swap("작업을 전환하세요")
        self.data.clear_notice()
        # 사용자가 직접 골랐다 = 보관된 명시 사건보다 최신 의사. 들고 있으면 다음 마운트에서
        # 옛 의도가 되살아나 방금 고른 작업을 밀어낸다(지연된 조용한 추측).
        self.work.preferred = ""
        if not name:  # 선택 해제 = 작업만 내려놓는다(데이터 존은 그대로)
            self._release_active_work()
            return
        self.runs.invalidate_work_results()
        job = self.work.load(name)
        # 결속 데이터를 먼저 세운다. 뒤에 마운트하면 방금 앉힌 작업이 데이터 전이 판정에
        # 걸려 스스로 해제되므로 작업 착석 전에 coherent data state를 확정한다.
        mount_notice = self._mount_job_binding(job)
        # 실패 목록은 **전환이 실제로 성사된 뒤에** 비운다(2R P2): `load` 가 실패하면
        # 세션은 그대로인데(vm·job_name 불변) 목록만 사라져, 화면에 남은 「실패한 N건만
        # 선택」이 0건을 돌려주는 유령 행동이 된다. 위 `_last_generated` 조기 소거는
        # 안전 방향(가드 재무장)이라 그대로 두지만, 이쪽은 **복구 경로가 사라지는** 방향이다.
        self.runs.last_failed = []
        # **준비는 착석 앞이다**(#932 B5). 「변경사항 확인」이 겸직하던 최초 준비를 여기로
        # 옮기되, 착석 **뒤**에 두면 vm 은 준비 전 사본을 들고 앉는다 — 그러면 권위·
        # Application 정체가 세션에 안 서고, 생성 시점의 채택 대조가 그 간극을 「외부에서
        # 바뀐 작업」으로 읽어 선택을 해제한다. 옛 클릭이 확인 성공 뒤 `_adopt_seated_identity`
        # 로 하던 일을 `_seat_active_job` 이 그대로 하므로, 순서만 맞추면 같은 상태가 선다.
        # 실패는 삼키지 않는다: durable 실패 기록이 남고 템플릿 존이 비활성 + 진단으로
        # 재진술하며, 같은 실물로는 되돌지 않는다.
        job, was_prepared = self.work.prepare_for_seat(job)
        self.work.select(job)
        if self.data.records and self.work.vm is not None:
            # 필터 열 유형 재조정(#302 리뷰 P2): 무작업 마운트의 필터는 값 스니핑만 탔다 —
            # 작업이 정해진 지금 매핑 확정 유형 힌트를 반영한다. 단 **정의 없는 필터만**
            # 재생성한다: 사용자가 이미 만든 정의는 유형 재판정이 술어를 조용히 떨어뜨릴
            # 수 있어 그대로 둔다(사용자 확정 > 유형 힌트 — 조작 순서 의존을 정의 유무의
            # 명시 규칙으로 환원).
            if self.data.filter is not None and not self.data.filter.is_active():
                self.data.install_filter(self.data.records, self._data_filter_hints())
        # 저장 폴더는 두 축이 **같은 도출**을 지난다(U3-06 #879 → 전역화) — 여기서 템플릿 옆
        # 기본값을 직접 조립하면 설정한 전역 폴더가 작업 선택에서 조용히 덮인다(그것이 종전
        # 이 줄의 실제 거동이었고, 전역화가 지운 결함이다).
        self.runs.out_dir = self._output_folder_resolution().directory
        # **최초 준비는 선택이 진다**(#932 B5). 종전에는 이름이 전혀 다른 「변경사항 확인」
        # 단추가 그 겸직을 졌고, 그래서 갓 저장한 작업은 그걸 누르기 전까지 「포함할 내용」이
        # 서지 않았다 — 구간이 서려면 준비가 필요하고 생성이 열리려면 구간이 필요한 교착이라
        # 자동으로 준비하는 유일한 경로(생성)에는 도달할 수가 없었다. 스냅샷이 아니라 이
        # **명령 경로**에 거는 이유는 write-on-read 금지다(`_slot_configuration_zone` 참조).
        # 실패는 삼키지 않는다: 거절은 durable 실패 기록으로 남고 템플릿 존이 비활성 + 진단
        # 병기로 재진술한다(그 자리가 사유를 말할 단 한 곳이다).
        # 자동 확인(seal)의 트리거는 **준비 이전의** 권위를 본다: 종전 bootstrap 동사였던
        # 「변경사항 확인」도 seal 을 켜지 않았으므로, 준비를 앞당긴 것이 자동 seal 까지
        # 딸려 켜면 그건 이 판정이 안 받은 두 번째 변경이다(준비 ≠ 재확인).
        if job.media == "hwpx" and was_prepared:
            self._maybe_auto_check(effective_basis_changed=True)
        if mount_notice:
            # 마운트가 실패했거나 무엇을 초기화했는지는 조용히 넘기지 않는다.
            self.data.notice_text = mount_notice
            self.data.notice_level = "warn"

    def _release_active_work(self) -> None:
        """현재 active Work만 해제한다. 데이터와 후보는 그대로 둔다."""
        self.runs.invalidate_work_results()
        # 충돌 처리는 세션 축이라 작업 해제에서 기본값으로 돌아간다. 저장 폴더는 **같이 죽지
        # 않는다** — 전역 설정이라 작업이 없어도 값이 서 있고, 아래 재도출이 그것을 말한다.
        self.runs.delivery_collision = DEFAULT_COLLISION_POLICY
        self.work.clear()
        # 템플릿이 사라졌으므로 기본값 ②는 도출 불가가 되지만, 설정한 전역 폴더는 그대로
        # 산다 — 같은 함수를 지나 그 사실이 반영된다(여기서 ``""`` 로 지우지 않는다).
        self.runs.out_dir = self._output_folder_resolution().directory
        self.runs.last_failed = []

    def _release_changed_active_work(self, reason: str) -> None:
        """외부 권위 변경으로 stale해진 active Work를 loud RELEASE한다."""
        self._release_active_work()
        self.data.notice_text = f"{reason} 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
        self.data.notice_level = "warn"

    # --------------------------------------- 「문서 만들기에서 사용」(§19.8 3분기)
    def _do_prefer_work(self, p: dict) -> dict:
        """라이브러리의 명시 선택을 active Work 세션 판정으로 착지한다."""
        name = str(p.get("name", "")).strip()
        fields = (
            list(self.data.records[0])
            if self.data.datasource is not None and self.data.records
            else None
        )
        decision = self.work.request_preferred(name, present_fields=fields)
        if decision.action == "select":
            self._do_select_job({"name": decision.name})
            return {"promoted": True, "name": decision.name}
        return {
            "stored": True,
            "reason": decision.reason,
            "name": decision.name,
        }

    def _apply_preferred_work(self) -> None:
        """마운트 뒤 보관 선택을 한 번 소비해 세션 소유 문안을 싣는다."""
        fields = list(self.data.records[0]) if self.data.records else []
        notice = self.work.consume_preferred(present_fields=fields)
        if notice is not None:
            self.data.notice_text = notice.text
            self.data.notice_level = notice.level

    def _do_toggle_favorite(self, p: dict) -> dict:
        """즐겨찾기 지정/해제(§18.5) — 정렬 메타만 바꾸고 세션은 건드리지 않는다.

        활성 작업·매핑·파일명·검증·선택 어느 것도 폐기하지 않는다(§18.5 명문). 값은
        표면이 보내는 **의도한 상태**(``value``)다 — 현재 값을 여기서 뒤집으면 빠른 연속
        클릭이 서로의 결과를 되돌린다(토글 경합, #215 동류).

        지정 시각은 서버 시각으로 찍는다(정렬 근거를 표면이 정하지 않는다). 작업이 다른
        화면에서 사라졌으면 조용히 넘기지 않고 재진술한다 — 목록이 곧 다음 스냅샷에서
        갱신되므로 파괴는 없다.

        **시각은 레지스트리가 쓰기 잠금 안에서 찍는다**(리뷰 1R·6R P2): ①초 절단이면 1초 안의
        두 지정이 동률이 돼 "최신순"(§18.5)이 거짓이 되고, ②여기서 미리 찍으면 서로 다른 작업
        둘을 연속으로 별 찍을 때 스레드 스케줄링이 나중 클릭에 이른 시각을 줄 수 있다. 잠금 안
        스탬프는 쓰기 순서 = 시각 순서를 담보한다. (생성 스탬프 ``last_run_at`` 은 런 자체가
        초 단위보다 길어 같은 함정이 성립하지 않아 그대로 둔다.)
        """
        name = p["name"]
        try:
            set_favorite(self.registry, name, bool(p["value"]))
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": f"'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {exc}"}
        return {"ok": True}

    def _do_browse_tab(self, p: dict) -> None:
        """문서 탐색 탭 전환(§18.6) — **검색어는 유지한다**(계약 명문).

        미지 값은 링1이 사용 가능으로 퇴화시키므로(표면 오타가 빈 화면을 만들지 않는다)
        여기서는 받은 값을 그대로 세션에 둔다.
        """
        self.work.set_browse_tab(str(p.get("tab", "")))

    def _do_browse_query(self, p: dict) -> None:
        """문서 탐색 검색어 갱신 — 대상은 작업 표시 이름만(§18.6, 판정은 링1)."""
        self.work.set_browse_query(p.get("text", ""))

    def _do_dismiss_data_notice(self, p: dict) -> None:
        """데이터 통지 닫기(U4 §2.12 · #945) — 세우는 자리의 짝.

        이 채널에는 사용자가 끄는 전이가 없어서, 사유가 지나간 뒤에도 통지가 남아 지금이
        아닌 과거를 계속 서술했다(편집기 `dismiss_notice` 와 같은 결함류). 해소를 자동
        감지하려 들지 않는 것도 같은 이유다 — 통지마다 해소 술어를 새로 지어야 하고 그
        술어가 곧 두 번째 판정이다. 사유가 다시 서면 같은 트리거가 통지도 다시 세운다.

        레지스트리 조회 실패 경고는 여기서 지우지 않는다(지울 수도 없다) — 그 문안은
        스냅샷마다 실측에서 다시 합성되는 자동 소멸분이라 이 문의 대상이 아니다.
        """
        self.data.clear_notice()

    # (_auto_aim_default(#53-A 기본 데이터셋 자동 조준)는 U2 §5.3 판정 D 로 삭제 —
    #  작업↔데이터 결속이 폐기돼 작업 선택이 데이터를 세우지 않는다. #347.)

    def _do_relink_template(self, p: dict) -> dict:
        """작업 템플릿 다시 연결(#67) — 공유 확정 게이트 위임 + 기선택 작업 재적재.

        커밋된 작업이 지금 패널에 선택돼 있으면 옛 경로의 VM 이 stale 이므로 ``_do_select_job``
        으로 재구성한다 — 데이터 겨눔·저장 폴더를 초기화하므로 결과 문구로 재진술(confirm-or-alarm).

        **진행 중 런과 겹치면 거절한다**(9R P1 형제): 템플릿 경로는 durable 규칙이고 진행 중
        배치는 옛 vm 을 고정해 뒀다 — 지금 갈아치우면 그 배치의 결과가 디스크에 없는 규칙을
        자기 근거로 댄다. 편집기 진입과 같은 부류라 같은 술어를 쓴다.
        """
        self.raise_if_generating("템플릿을 다시 연결하세요")
        res = self.work.relink_template(
            p["name"],
            p.get("path", ""),
            confirm=bool(p.get("confirm")),
        )
        # 「지금 열어 둔 작업인가」는 **이름**으로 묻는다(1R P2) — `self.work.vm.job.name` 은 hwpx
        # 세션에서만 참이라 TXT 를 재연결하면 세션이 옛 템플릿을 그대로 그린다. 같은 질문에
        # 매체별 술어를 쓰면 그게 곧 구멍이다.
        if res.get("relinked") and res.pop("active"):
            self.execution.invalidate()
            self._do_select_job({"name": p["name"]})
            res["restated"] = (
                "템플릿을 다시 연결했습니다. 작업을 다시 불러왔으니 데이터와 저장 폴더 "
                "선택을 확인하세요."
            )
        elif res.get("relinked"):
            res.pop("active", None)
            res["restated"] = "템플릿을 다시 연결했습니다."
        else:
            res.pop("active", None)
        return res

    def _do_template_check(self, p: dict) -> dict:
        """[변경사항 확인](S3-09) — 현재 작업 템플릿 원본을 capture·검사해 종결 상태로 닫는다.

        요청 키(``request_id``)는 사용자 prepare intent 의 재전송 단위다 — 같은 키 재전송은
        같은 Preparation 을 돌려주고(중복 클릭), 새로 확인하려는 명시적 행동만 새 키를 만든다
        (웹 소유). work 식별·bootstrap·token 발급은 전부 코디네이터가 소유한다.
        """
        if self._template_change is None:
            raise ValueError("템플릿 변경 기능이 조립되지 않았습니다")
        if not self.work.name:
            raise ValueError("먼저 작업을 선택하세요")
        result, restored_job, application_id = self._template_change.check_for_seated_context(
            self.work.name, str(p.get("request_id", ""))
        )
        if result.get("reason") == "work_context_changed":
            self._release_changed_active_work("문서 작업이 변경되어")
            result["error"] = (
                "문서 작업이 변경되어 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
            )
            return result
        if result.get("ok") is True and not self._seat_is_identified():
            if not self._adopt_seated_identity(restored_job, application_id):
                self._release_changed_active_work("문서 작업이 변경되어")
                return {
                    "ok": False,
                    "reason": "work_context_changed",
                    "error": (
                        "문서 작업이 변경되어 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
                    ),
                }
        return result

    def _seat_is_identified(self) -> bool:
        """착석한 Work 의 durable 정체가 이미 서 있는가 — **실행뷰 유무와 무관**(S10-03 #860).

        종전에는 채택 자체가 ``self.work.vm is not None`` 아래 있어서, 실행뷰를 세우지 않는 TXT 는
        확인을 통과해도 `_seated_template_application_id` 가 세션 내내 ``None`` 이었다
        (`_seat_active_job` 은 이미 매체와 무관하게 그것을 세우는데, 확인이 **바꾼** 값을 다시
        받지 못했다). 매체 하나만 자기 정체를 들고 다니는 상태다.

        HWPX 는 in-memory Job 사본(``vm.job``)이 authority_id 를 함께 드므로 둘 다 서야 정체가
        선 것이고, TXT 는 그 사본 자체가 없어(Job 은 쓸 때마다 registry 에서 다시 읽는다)
        세션이 드는 정체가 이 id 하나다.
        """
        if self.work.seated_template_application_id is None:
            return False
        return self.work.vm is None or bool(self.work.vm.job.authority_id)

    def _adopt_seated_identity(
        self, restored_job: "Job | None", application_id: "str | None"
    ) -> bool:
        """확인이 확립한 durable 정체를 세션 seat 에 채택한다(실패면 False → loud RELEASE).

        실행뷰가 없으면(TXT·미지원 매체) 지킬 Job 사본도, 대조할 snapshot 도 없다 —
        :meth:`_can_adopt_seated_identity` 가 지키는 것이 바로 그 **사본**이므로, 사본이 없는
        seat 에 그 대조를 씌우면 없는 위험에 답하느라 멀쩡한 선택을 해제하게 된다. 그때 세션이
        받는 것은 확인이 방금 읽은 current Application id 하나다.
        """
        if application_id is None:
            return False
        if self.work.vm is None:
            self.work.seated_template_application_id = application_id
            return True
        if restored_job is None or not self.work.can_adopt_seated_identity(
            self.work.vm.job, restored_job
        ):
            return False
        self.work.vm.job.authority_id = restored_job.authority_id
        self.work.seated_template_application_id = application_id
        return True

    def _do_template_apply(self, p: dict) -> dict:
        """[변경사항 적용](S3-09) — opaque change token 하나로 원자 적용을 요청한다.

        진행 중 런과 겹치면 거절한다(재연결과 같은 부류) — 적용은 durable 권위 전환이고
        결과 재진술이 진행 중 배치와 섞이면 안 된다. cross-Work token·stale token 은
        코디네이터가 Work 무변경으로 거절한다.
        """
        if self._template_change is None:
            raise ValueError("템플릿 변경 기능이 조립되지 않았습니다")
        if not self.work.name:
            raise ValueError("먼저 작업을 선택하세요")
        self.raise_if_generating("템플릿 변경사항을 적용하세요")
        result, committed_application_id = self._template_change.apply_for_seated_context(
            self.work.name, str(p.get("change_token", ""))
        )
        if result.get("is_current") is True:
            self.work.seated_template_application_id = committed_application_id
            self.execution.invalidate()
            self._maybe_auto_check(effective_basis_changed=True)
        elif result.get("status") == "applied_then_advanced":
            self._release_changed_active_work("문서 작업에 다른 변경이 이어져")
        return result

    # ----------------------------------- 관리 동사(표면은 라이브러리, 소유는 이 컨트롤러)
    # 좌 목록이 죽어도(F2 PR-B) 아래 넷은 남는다: 열린 세션의 정체(``job_name``·VM)와 결속돼
    # 있어 여기가 계속 소유하고, 「문서 작업」 상세·그룹 헤더가 **교차 화면 dispatch** 로
    # 부른다(지도 §10.8 판정 F). 라이브러리에서 재구현하면 거기서 이름을 바꾼 순간 열린
    # 세션이 없는 이름을 가리킨다. 반면 세션과 무관한 복제·삭제·복원과 그룹 접힘은 표면과
    # 함께 걷혔다 — 라이브러리가 자기 채널에서 소유한다(판정 F 정정분).
    def _do_rename_job(self, p: dict) -> dict:
        """작업 이름 변경(인라인 편집 커밋) — 검증 실패는 ``{"ok": False, error}`` 재진술.

        열린 세션의 작업이면 세션 정체(``job_name``·VM)가 새 이름을 **추종**한다 — 이름
        변경은 비파괴(같은 작업)라 가드 없이 조용히 따라가되, 헤더가 즉시 새 이름을
        재진술하므로 변경이 보인다(전면 가시성).
        """
        name, new = p["name"], p.get("new", "")
        try:
            rename_job(self.registry, name, new)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        new_clean = new.strip()
        self.work.rename(name, new_clean)
        # 직전 런의 주체도 **같은 전이에서** 추종한다(3R P2) — 안 따라가면 같은 작업의
        # 결과가 남의 것으로 판정돼 복구 행동이 사라지고 강등 문구가 거짓말을 한다.
        if self.runs.last_run_job == name:
            self.runs.last_run_job = new_clean
        # (템플릿 권위 identity 는 Job durable 필드(`authority_id`)라 개명을 저절로
        #  따라간다 — 여기서 옮길 인덱스가 없다, S3-09 리뷰 P1.)
        return {"ok": True}

    # (close_guard_reason 은 U2 §2.9(#344)에서 사망 — 창 닫기는 명시적 종료 선언이고 진행
    #  중 선택은 계약상 보존하지 않는다. 이 화면은 창 종료 가드에 참여하지 않으며, 그 배제는
    #  tests/test_webapp_bridge.py 의 `silent_loss_by_contract` 표에 **선언**돼 있다. 가드
    #  술어 `_guard_state` 의 나머지 두 소비자 — `session_guard_for`(홈 삭제 가드, #268)와
    #  `_do_guard_state`(데이터 재겨눔·재연결 사전 확인) — 는 그대로 산다.)

    def session_guard_for(self, name: str) -> "dict | None":
        """타 화면(홈) 삭제 가드 조회(#268 리뷰) — 이 화면이 ``name`` 에 무장 세션을 열어
        두었으면 가드 수치(+``screen``)를 돌려준다. 판정·수치는 :meth:`_guard_state` 단일
        출처를 재사용한다(문안이 실제 소실 집합과 어긋나지 않게)."""
        if name and name == self.work.name:
            g = self._guard_state()
            if g["armed"]:
                return {"screen": self.name, **g}
        return None

    def _do_cancel_generation(self, p: dict) -> dict:
        """진행 중인 문서를 완결한 뒤 다음 레코드부터 중단하도록 요청한다."""
        self.runs.request_cancel()
        return {"ok": True}

    def _do_select_failed(self, p: dict) -> dict:
        """「실패한 N건만 선택」 — 선택을 직전 런의 실패 레코드로 **교체**한다(§10.10 판정 F).

        **생성은 하지 않는다**: 의사표시 2클릭 분리(결정 28 「직전 필터 재적용」이 정의만
        복원하고 선택은 건드리지 않는 것과 같은 격 구분). 성공분 보존은 신설 기제가 아니라
        덮어쓰기 확인 왕복(RC-02)이 담보한다 — 재생성이 성공분을 겨누면 그 수치가 모달에
        선다. 별도의 재시도 동사(건별 재실행·filename override)는 **짓지 않는다**(지도 §10.14
        기각): 확정 실패 원인 4종(권한·점유·공간·경로)은 규칙이 아니라 환경이 원인이라 **이
        선택 + 「문서 만들기」** 가 곧 재시도이고, 저장 폴더를 바꾸면 「다른 폴더에서 재시도」다.

        목록이 비었으면(수명 경계를 지났거나 실패 없던 런) ``0`` 을 돌려 표면이 무동작을
        정직하게 말한다 — 아무 반응 없는 버튼은 결함으로 읽힌다(``_do_set_all`` 선례).

        범위 초안이 열려 있으면 **거절**한다(F3): 이 동사는 존 액션이 아니라 **커밋된 선택을
        직접 교체**하는 결과 구획의 행동이라, 초안 아래에서 커밋을 갈면 사용자가 보고 있는
        범위와 적용 대상이 조용히 갈린다. 표면상 모달에 가려 닿지 않지만 잠금은 상태가 진다.
        """
        if self.data.range_draft is not None:
            raise ValueError("범위 편집기를 닫은 뒤에 실패분을 선택할 수 있습니다.")
        idx = [i for i in self.runs.last_failed if 0 <= i < len(self.data.records)]
        if not idx:
            return {"selected": 0}
        self.data.selection.set_none()
        for i in idx:
            self.data.selection.toggle(i, True)
        return {"selected": len(idx)}

    # 그룹 지정·개명·해산 동사는 U4 §2-30 에서 표면과 함께 걷혔다. 판정 몸통
    # (`application.jobs.assign_group`·`rename_group`·`disband_group`)과 접힘 영속
    # (`settings.recollapse_job_group`)은 **동결**로 남는다 — 지우지 않되 제품이 부르지
    # 않는다. 되살리면 이 화면이 다시 소유자다(열린 세션의 정체와 결속된 동사라서).

    def _data_filter_hints(self) -> "dict[str, str]":
        return {
            m.source: m.type
            for m in (self.work.vm.job.mapping.mappings if self.work.vm is not None else [])
            if m.source and m.type in (KIND_TEXT, KIND_DATE, KIND_AMOUNT)
        }

    def _invalidate_data_results(self) -> None:
        self.execution.invalidate_preparations()
        self.runs.invalidate_data_results()

    # (_do_ack_field·_do_unack_field 는 필드축 ack 폐기와 함께 사망 — U2 §2.13.
    #  빈 값은 #957 이후 차단이 아니라 표식이라 동의 사건 자체가 없다.)

    def _do_load_pool(self, p: dict) -> dict:
        key = p["key"]
        resolved: list = []

        def load(item) -> list:
            self.raise_if_generating_before_swap("데이터를 바꾸세요")
            source, records = resolve_pool_source(item, source_factory=self._pool_source_factory)
            resolved.append(source)
            return records

        res = load_pool_into(self.data.pool_registry, key, load)
        if not res["ok"]:
            return res
        item = res["item"]
        records = res["records"]
        path, sheet, header_row, kind = pool_reference_quad(item)
        self.runs.last_failed = []
        self._commit_data_mount(
            datasource=resolved[0],
            records=records,
            incoming=(path, sheet, header_row, kind),
            label=item.name,
            source_kind="pool",
            path=path,
            sheet=sheet,
            header_row=header_row,
            kind=kind,
            pool_key=key,
            data_key=self.data.pool_key_for(key, item),
        )
        self._remember_data_source()
        return {"ok": True, "label": source_label("pool", item.name)}

    # ------------------------------------------------------------------ 생성
    def _push_progress(self, done: int, total: int) -> None:
        """생성 진행 델타 — 전체 스냅샷 재계산(템플릿 재파싱) 없이 진행바만 갱신.

        ``run_token`` 을 함께 싣는다(R4-03): 진행 델타는 direct 반환과 **다른 채널**이라
        어느 실행의 것인지가 payload 밖에 없었다. 표면이 "지금 진행 중인 실행"이라고
        가정하면 새 실행이 시작된 뒤 도착한 앞선 런의 델타가 새 진행바를 뒤로 돌린다 —
        토큰 대조가 그 창을 닫는다. 값은 이 컨트롤러가 만들지 않고 되돌리기만 한다.
        """
        run = self.runs.run
        self._push_sink(
            self.name,
            {
                "progress": {
                    "done": done,
                    "total": total,
                    "run_token": run.token if run is not None else "",
                },
            },
        )

    def generate(self, *, confirm_overwrite: bool = False, run_token: str = "") -> dict:
        """게이트 통과 시 동기 생성 → 결과 dict. 덮어쓰기는 웹 재진술 후 재호출(RC-02).

        슬라이스 1은 실행 화면과 동일한 링1 계약을 배선한다 — 게이트 판정·덮어쓰기 재진술의
        표현(재진술 블록·modal.js)은 슬라이스 2(블록 6)가 광택한다.

        ``run_token`` 은 표면이 낸 불투명 상관 문자열이고 **모든** 반환 갈래에 되돌아간다
        (거절·덮어쓰기 필요·취소·성공·실패). 되돌림을 갈래마다 손으로 적지 않고 이 함수의
        단일 출구가 찍는 이유는 갈래가 늘 때 형제를 빠뜨리는 결함류를 구조로 막기 위해서다.
        생략하면 ``""`` 라 종전 호출자의 동작은 그대로다.
        """
        # 토큰은 **이 호출의 지역값**이다. 공유 필드에 먼저 실으면 자물쇠에 거절당할 두 번째
        # 호출이 **이긴 런의 이름표를 갈아치운다** — 그러면 실제로 도는 런의 진행 델타와 최종
        # 응답이 남의 토큰을 달고 나가 표면이 그것을 「남의 것」으로 폐기한다(문서는 만들어졌는데
        # 사용자는 「이미 생성 중」만 본다). 되돌림은 이 지역값이 지고, 공유 필드는 자물쇠를
        # 쥔 런만 세운다.
        token = run_token if isinstance(run_token, str) else ""
        result = self._generate_with_token(confirm_overwrite=confirm_overwrite, run_token=token)
        # 되돌림은 마지막 한 자리다. 판정에 쓰지 않으므로 값이 무엇이든 그대로 싣는다.
        result["run_token"] = token
        return result

    def _overwrite_pin_key(self) -> str:
        """덮어쓰기 확인 왕복이 결속되는 **세계의 정체**(#957).

        시각 하나를 왕복 사이에 붙들어 두는 것은 확인창이 재진술한 파괴 집합과 실제로
        파괴되는 집합을 같게 만들려는 것이다. 그 사이 세계가 바뀌면(존 변이·선택 변경·
        데이터 교체·작업 전환·재봉인) 그 시각은 이미 **다른 배치의 것**이라, 되쓰면 오히려
        사용자가 본 적 없는 이름을 만든다. 그래서 핀은 이 키에 결속되고 키가 어긋나면
        버린다 — 세대 자체를 지키는 것은 각 갈래의 stale 검사(managed 는 sealed basis
        digest·prep 캐시, legacy 는 `plan_generation` 재계획)다.
        """
        return "|".join(
            (
                self.work.name,
                self.data.data_key,
                str(self.data.snapshot_generation),
                str(self.data.zone_epoch),
                ",".join(str(i) for i in self.data.selected_indices()),
                self.execution.sealed_basis_digest or "-",
            )
        )

    def _generate_with_token(self, *, confirm_overwrite: bool = False, run_token: str = "") -> dict:
        """``generate`` 의 판정 본체 — 토큰은 진행 델타의 이름표로만 쓴다."""
        if self.work.vm is None:
            return {"ok": False, "error": "먼저 작업을 선택하세요.", "level": "warn"}
        job = self.work.vm.job
        # S6-05(#812): S6-absent \uac00\ub4dc(authority_id \ub2e8\ub3c5 \ud544\ud130)\ub294 \ucca0\uac70\ub410\ub2e4 \u2014 \uc2e4\ud589 \uacbd\ub85c \uc120\ud0dd
        # (\uc758\ubbf8 4)\uc740 \uc544\ub798\uc5d0\uc11c managed_hwpx \ud30c\uc0dd\uacfc \uac19\uc740 \uc6d0\ucc9c\uc73c\ub85c \uac08\ub9ac\uace0, managed \uac08\ub798\uc758
        # \uc2dc\uc791 \uc790\uaca9\uc740 start gate \uac00, slot-bearing \uc758 legacy \uc720\uc785\uc740 admission \uc774 \uac01\uc790 \uc18c\uc720\ud55c
        # \uc0ac\uc720\ub85c \ub2eb\ub294\ub2e4(#806 R1\u00b7R2 \uac00 \ub51b\ub294 \uc0ac\uc2e4).

        if self.data.range_draft is not None:
            # 초안이 열린 채 생성하면 사용자가 보고 있는 범위(초안)와 만들어지는 범위(커밋)가
            # 다르다 — 표면상 모달에 막혀 있지만 잠금은 DOM 이 아니라 상태가 진다(§10.11.2
            # 계약면 2). 거절 문안이 다음 행동(적용 또는 취소)을 지목한다.
            return {
                "ok": False,
                "level": "warn",
                "error": "범위 편집기가 열려 있습니다. 변경을 적용하거나 취소한 뒤 생성하세요.",
            }
        run_vm = self.work.vm
        visible_identity_before = (
            self.work.vm,
            getattr(getattr(self.work.vm, "job", None), "authority_id", None),
            self.work.seated_template_application_id,
            self.work.name,
        )
        run = self.runs.begin(
            getattr(run_vm, "job", None), job_name=self.work.name, token=run_token
        )
        if run is None:
            return {"ok": False, "error": "이미 문서를 생성하고 있습니다.", "level": "warn"}
        try:
            try:
                # 잠금 직후 VM·데이터·출력 폴더를 한 번만 붙든다.
                run_input = self.runs.capture_input(
                    datasource=self.data.datasource,
                    records=self.data.records,
                    indices=self.data.selected_indices(),
                    snapshot_generation=self.data.snapshot_generation,
                    work_ref=self.work.name,
                    source_schema_keys=(
                        tuple(self.data.filter.columns)
                        if self.data.filter is not None
                        else tuple(self.data.records[0].keys())
                        if self.data.records
                        else ()
                    ),
                    output_directory=self.runs.out_dir,
                )
                run_now = self.runs.capture_now(
                    confirm_overwrite=confirm_overwrite,
                    pin_key=self._overwrite_pin_key(),
                    clock=self._clock,
                )
                if run_now is None:
                    # 낡은 확인 — 물어본 배치가 이미 없다. 조용히 새 배치에 적용하지 않고
                    # 사유를 돌려준다(웹은 다시 눌러 새 확인 왕복을 연다).
                    visible_identity_changed = False
                    result = {
                        "ok": False,
                        "level": "warn",
                        "error": "생성 대상이 바뀌어 덮어쓰기 확인을 다시 받아야 합니다. "
                        "문서 만들기를 다시 실행하세요.",
                    }
                elif self._is_managed_hwpx_work(job):
                    # managed 갈래(S6-05) — legacy staging·admission 을 타지 않는다. 준비
                    # 미달·stale·runtime 은 파이프라인 안의 소유자들이 각자 사유로 닫는다.
                    visible_identity_changed = False
                    result = self._generate_managed_locked(
                        run,
                        run_vm,
                        run_input,
                        confirm_overwrite=confirm_overwrite,
                        now=run_now,
                    )
                else:
                    reject = self._resolve_managed_template(run_vm)
                    visible_identity_changed = (
                        self.work.vm,
                        getattr(getattr(self.work.vm, "job", None), "authority_id", None),
                        self.work.seated_template_application_id,
                        self.work.name,
                    ) != visible_identity_before
                    result = (
                        reject
                        if reject is not None
                        else self._generate_locked(
                            run,
                            run_vm,
                            run_input,
                            confirm_overwrite=confirm_overwrite,
                            now=run_now,
                        )
                    )
            finally:
                # staged 경로는 이 런에서만 유효하다 — VM 포인터를 비우고, 실행이 끝나 아무도
                # 참조하지 않는 staging 사본을 Host lifecycle 로 정리한다(#681, 판본별 영구 누적 방지).
                managed = (
                    run_vm is not None and getattr(run_vm, "_managed_template", None) is not None
                )
                if run_vm is not None:
                    run_vm._managed_template = None
                if managed and self._template_change is not None:
                    self._template_change.clear_generation_staging()
                self.runs.finish()
        except Exception:
            if (
                self.work.vm,
                getattr(getattr(self.work.vm, "job", None), "authority_id", None),
                self.work.seated_template_application_id,
                self.work.name,
            ) != visible_identity_before:
                self._push()
            raise
        # 런이 남긴 세션 변화(직전 런 주체·완주 스탬프)를 표면에 흘린다(3R P2) — `generate`
        # 는 dispatch 밖이라 자동 push 가 없어, 표면은 **런 이전 스냅샷**으로 결과 행동을
        # 판정하고 있었다. 덮어쓰기 확인 왕복(`needs_overwrite`)에는 밀지 않는다: 모달이
        # 열린 동안의 재렌더는 dispatch 의 무변이 push 생략과 같은 이유로 낭비다.
        if result.get("ok"):
            self._note_tutorial_generation(result)
            self._push()
        elif visible_identity_changed:
            self._push()
        return result

    # ------------------------------------------- 튜토리얼 루프 감지(#894)
    def note_template_compiled(self, path: str) -> None:
        """tpl 채널의 **누름틀 변환 성립** 통지를 받는다(T16 의 재료).

        디스패치 액션이 아니라 컨트롤러 간 seam 이다(tpl→편집기 재정산 선례): 웹이 부르는
        표면이 아니고, 조립 한 줄은 :class:`~hwpxfiller.webapp.app.WebFrontend` 가 소유한다.
        변이 통지(``mutation_sinks``)와 갈라 받는 이유는 :data:`~hwpxfiller.webapp.screens.
        CompileSink` 주석에 있다 — slot 개명 한 번이 「변환본으로 생성」을 켜지 않게.
        """
        self._tutorial_loop.note_compiled(path)

    def _tutorial_slot_shape(self) -> "dict[str, frozenset[str]] | None":
        """이번 작업의 「항목 → 고른 선택」 — 없으면 ``None``(구간 없는 템플릿·조회 불가).

        :meth:`_is_managed_hwpx_work` 와 **같은 가드·같은 read-only projection** 을 쓴다
        (#744): durable id 미발급 Work 를 Product 에 넘기면 read 중 권위 id 가 lazy 발급돼
        조회만으로 durable 표식이 생긴다. 실패는 「구성 없음」이 아니라 「모른다」라서
        ``None`` 이고, 그 경우 T17 은 서지 않는다(추측으로 체크하지 않는다).
        """
        if self.execution.slot_configuration is None or not self.work.name:
            return None
        job = getattr(self.work.vm, "job", None)
        if job is None or job.media != "hwpx" or not job.authority_id:
            return None
        try:
            response = self.execution.current_slot_view(self.work.name)
        except SlotConfigurationProductError:
            return None
        if response is None:
            return None
        projection = response.current_view.projection
        if projection is None:
            return None
        return {slot.slot_id: frozenset(slot.effective_option_ids) for slot in projection.slots}

    def _note_tutorial_generation(self, result: dict) -> None:
        """생성 완주의 마일스톤 통지(#894) — 성공 문서가 **1건 이상**일 때만.

        ``ok`` 는 취소·부분 실패도 참이라(문서 0건인 완주가 있다) 판정 축은 ``succeeded`` 다:
        §3.3 T7 의 달성 판정이 「생성 완료 사건(성공 ≥1)」이라고 그렇게 못박혀 있다.

        여기서 새로 판정하는 것은 없다. 어느 T 인지는 세션 이력
        (:class:`~hwpxfiller.webapp.screen_tutorial.GenerationLoopLedger`)이 낸 **사실 셋**이
        가른다. 승인축(T13)은 #957 에서 발신자가 사라졌다.
        """
        if int(result.get("succeeded", 0) or 0) < 1:
            return
        job = self.runs.last_run_job or self.work.name
        if not job:
            return
        self._tutorial(Milestone.GENERATE)
        if self._tutorial_loop.was_compiled(self._current_template_path()):
            self._tutorial(Milestone.GENERATE_FROM_COMPILED)
        facts = self._tutorial_loop.note_generated(
            job,
            mount_key=self.data.data_key,
            slot_shape=self._tutorial_slot_shape(),
        )
        if facts.repeat_job:
            self._tutorial(Milestone.SECOND_LAP)
        if facts.other_job_same_mount:
            self._tutorial(Milestone.SWITCH_JOB)
        if facts.options_changed:
            self._tutorial(Milestone.CHANGE_COMPOSITION)

    def _current_template_path(self) -> str:
        """이번 실행이 쓴 템플릿 경로 — 세션 VM 이 든 값(없으면 빈 문자열)."""
        job = getattr(self.work.vm, "job", None)
        return str(getattr(job, "template_path", "") or "")

    def _generate_managed_locked(
        self,
        run,
        run_vm,
        run_input: RunInputCapture,
        *,
        confirm_overwrite: bool = False,
        now: "datetime | None" = None,
    ) -> dict:
        """확인된 managed 준비 값을 실행 coordinator에 넘긴다."""
        self.runs.adopt_run_metadata(run)
        try:
            observation = self.workbench_observation(
                run_input=run_input,
                filename_pattern=run_vm.job.filename_pattern,
            )
        except ValueError:
            return {
                "ok": False,
                "error": "현재 환경에서는 문서를 만들 수 없습니다",
                "level": "warn",
            }
        if not observation.create_documents_enabled:
            return {
                "ok": False,
                "error": observation.create_documents_disabled_reason
                or "필요한 준비를 먼저 완료해 주세요",
                "level": "warn",
            }
        payload = self.execution.sealed_plan_payload
        if payload is None or (
            execution_basis_digest(payload.execution_basis) != self.execution.sealed_basis_digest
        ):
            return {
                "ok": False,
                "error": "실행 준비가 현재 확인 상태와 달라 생성하지 않았습니다. "
                "변경사항을 다시 확인해 주세요.",
                "level": "warn",
            }
        prep = self.execution.delivery_preparation
        if prep is None or not isinstance(prep.result, CurrentResolvedDelivery):
            return {
                "ok": False,
                "error": "필요한 준비를 먼저 완료해 주세요",
                "level": "warn",
            }
        output_error = self.runs.prepare_managed_output(prep)
        if output_error is not None:
            return output_error
        context = (
            self.execution.managed_run_context(run_input.work_ref)
            if self.execution.seal_execution is not None
            else None
        )
        if context is None:
            return {
                "ok": False,
                "error": "현재 환경에서는 문서를 만들 수 없습니다",
                "level": "warn",
            }
        result = self.runs.run_managed(
            run,
            ManagedRunInput(
                payload=payload,
                preparation=prep,
                context=context,
                sealed_basis_digest=self.execution.sealed_basis_digest or "",
                capture=run_input,
                filename_source_columns=filename_source_columns(
                    run_vm.job, run_input.source_schema_keys
                ),
            ),
            now=now if now is not None else self._clock(),
            confirm_overwrite=confirm_overwrite,
            overwrite_pin_key=self._overwrite_pin_key(),
        )
        if result.historical_outcome is not None:
            self.execution.record_managed_outcome(result.historical_outcome)
        return result.payload

    def _resolve_managed_template(self, run_vm) -> "dict | None":
        """managed Product Work(HWPX 새 문서) 생성이 겨눌 템플릿을 current Application 의
        exact applied bytes(staged)로 고정한다(#681 G11) — mutable ``job.template_path`` 직독을
        managed 경로에서 없앤다. 이어채우기(이전 출력)·txt·코디네이터 부재는 해당 없음.
        admission 차단은 fallback 없이 시끄러운 거절 dict 로 돌려준다(confirm-or-alarm).
        반환 ``None`` = managed 해당 없음 또는 통과(``run_vm._managed_template`` 설정됨).
        """
        if (
            self._template_change is None
            or getattr(getattr(run_vm, "job", None), "media", "") != "hwpx"
        ):
            return None

        def synchronize_seated_identity(restored_job: Job, application_id: str) -> None:
            if self.work.vm is run_vm and (
                not run_vm.job.authority_id or self.work.seated_template_application_id is None
            ):
                if not self.work.can_adopt_seated_identity(run_vm.job, restored_job):
                    self._release_changed_active_work("문서 작업이 변경되어")
                    raise TemplateChangeError(
                        "문서 작업이 변경되어 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
                    )
                run_vm.job.authority_id = restored_job.authority_id
                self.work.seated_template_application_id = application_id

        try:
            run_vm._managed_template = (
                self._template_change.resolve_generation_template_for_seated_context(
                    self.work.name, on_context=synchronize_seated_identity
                )
            )
        except (SlotlessRunAdmissionError, TemplateChangeError) as exc:
            if isinstance(exc, SlotlessRunAdmissionError):
                return {
                    "ok": False,
                    "level": "warn",
                    "error": ADMISSION_REJECT_TEXT.get(exc.code, "생성을 진행할 수 없습니다."),
                }
            return {"ok": False, "level": "warn", "error": str(exc)}
        return None

    def _generate_locked(
        self,
        run,
        run_vm,
        run_input: RunInputCapture,
        *,
        confirm_overwrite: bool = False,
        now: "datetime | None" = None,
    ) -> dict:
        """고정 런 입력을 legacy 실행 coordinator에 전달한다."""
        run_now = now if now is not None else self._clock()
        result = self.runs.run_legacy(
            run,
            run_vm,
            run_input,
            now=run_now,
            confirm_overwrite=confirm_overwrite,
            overwrite_pin_key=self._overwrite_pin_key(),
            existing_outputs=self._existing_outputs,
            engine=self._engine,
            progress=self._push_progress,
            store=self.registry,
            completed_at=lambda: self._clock().isoformat(timespec="seconds"),
            ensure_output_dir=self._ensure_output_dir,
            filename_source_columns=filename_source_columns(
                run_vm.job, run_input.source_schema_keys
            ),
        )
        if result.stamped_job is not None and run_vm is self.work.vm:
            if result.stamped_rules_changed:
                self.runs.last_generated = None
            run_vm.job = result.stamped_job
        return result.payload

    # ----------------------------------- S4 Working Slot Configuration(SX-02 #725)
    # 4개 command 는 전부 **dispatch 경로**다(직접 브리지 아님). work_ref 는 세션의 현재 작업
    # (payload 에 없음, template_check 선례). configuration_token 은 opaque(프런트가 직전 응답의 새
    # token 을 되돌려준다), request_id 는 프런트 발급 재전송 단위. command outcome + fresh view 는
    # Product `SlotConfigurationProduct._respond` 가 이미 조립하므로 컨트롤러는 asdict 로 관통만 한다
    # (local optimistic authority 0 — 응답 도착 시 backend view 로 통째 교체). 현재 구성의
    # broken/missing 분리는 projection(blocking_items·detached_selections)이, **이전에 고른 것의
    # 운명**은 projection.retained_selections(#777)가 이미 지므로 여기서 재판정하지 않는다.
    def _slot_response_dict(self, response) -> dict:
        """`SlotConfigurationCommandResponse`(중첩 frozen dataclass) → JSON-safe dict.

        `asdict` 가 중첩 dataclass·tuple 을 dict/list 로 재귀 변환한다. projection 의
        detached_selections·blocking_items·retained_selections 가 그대로 실려 프런트가
        분리 소비한다(문안·확인 UI 는 웹, 판정·수치는 Python).
        """
        return asdict(response)

    def _configuration_zones(self, media: str, template_missing: bool) -> dict:
        """Prepare the three configuration zones in their required dependency order."""
        template_change = unsupported_zone()
        if self._template_change is not None:
            drift = (
                NO_SOURCE_DRIFT_JUDGMENT
                if template_missing
                else self._template_change.source_drift(self.work.name)
            )
            template_change = self._template_change.zone(
                self.work.name,
                media,
                template_missing,
                source_drift=drift,
            )
        slot_configuration = self._slot_configuration_zone(template_missing)
        content_presets = self._content_presets_zone(
            template_missing,
            savable_selection=self._savable_selection(slot_configuration),
        )
        return {
            "template_change": template_change,
            "slot_configuration": slot_configuration,
            "content_presets": content_presets,
        }

    def _is_managed_hwpx_work(self, job) -> bool:
        """의미 3(managed_hwpx)의 파생(S6-05 · #812) — 실행 경로 의미와 한 원천에서 나온다.

        「이 Work 가 materialization 대상인가」= hwpx ∧ durable authority ∧ **slot-bearing**
        (링1 projection 의 slots 사실 — 재판정이 아니라 이름 붙이기). slotless 발급 작업은
        False → legacy 갈래로 흘러 R1 트랩이 구조로 소멸한다. view 실패·미초기화도 False —
        slot-bearing 이 잘못 legacy 로 가도 admission 이 제 사유로 loud 거절한다(#806 R2 백스톱).
        조회는 read-only projection(#744)이라 렌더 부작용이 없다.
        """
        return self.execution.is_managed_hwpx(self.work.name, job)

    # `_seat_is_managed_hwpx` 는 여기 있었다(#905) — 명령 좌표가 managed 갈래인지 묻는 술어였고
    # 유일한 소비자가 `set_output_folder` 의 갈래 분기였다. 저장 폴더가 전역화되면서 그 분기
    # 자체가 사라져 소비자 0 이 됐으므로 함께 걷는다(되살릴 일이 생기면 `_is_managed_hwpx_work`
    # 가 그대로 있다).

    def _slot_configuration_zone(self, tmissing: bool) -> dict:
        """스냅샷의 ``slot_configuration`` 존 — fresh current view 를 조회해 실어 보낸다.

        미주입·미선택·미지원 매체·템플릿 부재면 명시적 unsupported(분기별 키 동형). 초기화 전(Work
        durable id 미발급) Work 는 Product 를 부르지 않는다 — route 가 read 중 durable id 를 발급하므로
        (write-on-read) 렌더 부작용을 피한다. 초기화된 Work 는 #744 read-only projection 으로 조회한다
        — 스냅샷은 렌더라 open(ensure)의 successor reconciliation 물질화로 durable S4 를 바꾸지 않는다.
        ensure 는 명시적 open/refresh command(`_do_open_slot_configuration`·`_do_refresh_...`)에만 남긴다.

        **매체 판정은 S3 지원 집합 그대로다**(S10-03 #860): S4 아래(선택 언어·context·store·
        command·projection·Preset)는 어디에도 매체가 없고, 갈리는 것은 「그 bytes 를 무엇으로
        자격 심사하는가」 하나뿐이라 그 표(`SUPPORTED_MEDIA`)가 이 존의 자격도 진다. 여기서
        문자열을 다시 조립하면 새 매체가 설 때 한 가지만 늙는다.
        """
        job = (
            load_job(self.registry, self.work.name)
            if self.execution.slot_configuration is not None and self.work.name and not tmissing
            else None
        )
        return self.execution.slot_zone(self.work.name, job, tmissing)

    # ── 작업대 Observation 존(SX-03 #726) — 합성 observation → JSON-safe dict ───────────────
    @staticmethod
    def _workbench_observation_blank() -> dict:
        return {"supported": False, "kind": None}

    def _workbench_observation_zone(self, tmissing: bool) -> dict:
        """스냅샷의 ``workbench_observation`` 존 — 합성 Observation(또는 ContextError)을 실어 보낸다.

        미조립·미선택·템플릿 부재면 명시적 unsupported. 그 밖에는 :meth:`workbench_observation` 을
        조립해 JSON-safe dict 로 성형한다 — 판정·문안·7상태는 Product/status 함수가 이미 낸 값이라
        여기서 재판정하지 않는다(프런트도 재판정 0, 읽기만).

        **무결성 실패는 「아직 준비 안 됨」으로 접지 않는다**(#775). 위 pre-guard 가 미조립·미선택·
        템플릿 부재를 이미 걸러내므로, 여기까지 온 예외는 준비 부족이 아니라 context/무결성
        실패다 — :data:`CONTEXT_ERROR_TYPES` 집합을 잡아 화면 계약에 이미 있는 ``context_error``
        상태로 낸다(새 상태·새 문구 0). 그 집합은 ``ValueError`` 자손인 것(ExecutionStructureError
        등)과 아닌 것(FieldBindingInputIntegrityError 등)이 섞여 있어, 예전의 ``except ValueError``
        는 앞의 절반을 blank 로 접고 뒤의 절반으로는 스냅샷 조립을 통째로 죽였다. 집합 **밖**의
        예외는 그대로 전파한다 — 모르는 실패를 조용한 화면 값으로 바꾸지 않는다.
        """
        if self.execution.workbench_product is None or not self.work.name or tmissing:
            return self._workbench_observation_blank()
        try:
            observation = self.workbench_observation()
        except CONTEXT_ERROR_TYPES as exc:
            observation = DocumentCreationWorkbenchContextError(
                context_error_code(exc), str(exc) or "현재 실행 맥락을 복원하지 못했습니다"
            )
        return {
            # 저장 폴더 도출은 이 존에 없다(전역화) — 스냅샷 **최상위**의 `output_folder` 가
            # 그 자리다. observation 축과 무관하게 늘 실려야 한다는 U3-06 #879 의 이유는
            # 그대로이고(context error 로 관찰이 무너져도 "어디에 저장되는가"는 답할 수 있다),
            # 지금은 작업 유무와도 무관해야 해서 존이 아니라 최상위가 그것을 진다.
            "supported": True,
            **serialize_observation(
                observation, execution_status=self.execution.execution_status()
            ),
        }

    def _do_open_slot_configuration(self, p: dict) -> dict:
        """현재 작업의 S4 Working Configuration 을 열어 fresh projection + 새 token 을 낸다(무변이).

        React 가 stored configuration·Template 구조를 직접 조립하지 않는다 — Product 가 낸
        authoritative view 하나를 그대로 소비한다.
        """
        return self._slot_response_dict(self.execution.open_slot_configuration(self.work.name))

    def _do_refresh_slot_configuration(self, p: dict) -> dict:
        """현재 configuration 을 새로 고쳐 fresh current view 를 되받는다(무변이).

        optional ``configuration_token`` 을 실으면 Product 가 그 token 의 Application 과 현재
        Application 을 대조해 stale 여부(``refresh_required``)를 판정한다 — 미실으면 최초 조회다.
        """
        token = p.get("configuration_token")
        token = str(token) if token is not None else None
        return self._slot_response_dict(
            self.execution.refresh_slot_configuration(self.work.name, token)
        )

    def _do_select_slot_option(self, p: dict) -> dict:
        """Option 선택 = durable S4 command(별도 전체 저장 버튼 없음). command outcome + fresh view.

        stale token 은 Product 가 mutation 을 거절하고 fresh current view 를 되돌린다(유령 반영 0) —
        컨트롤러는 backend view 로 통째 교체만 한다(local optimistic authority 0).

        **automatic checking(SX-03 #726 · R2(#740) 착지).** durable commit 이 CHANGED 면
        `_maybe_auto_check` 가 자동 확인(`on_durable_command_settled` → 필요 시 seal → `on_seal_settled`)에
        진입한다. 수동 seal 버튼 0. seal 은 durable side effect 없는 순수 재계산이라 매 durable 변경마다
        재확인한다(opaque Plan ref 로 same-basis 를 미리 엿보던 경로는 R2 가 제거했다).

        생성과 **상호배제**한다(#725 리뷰). check-then-act(`raise_if_generating`)는 pywebview
        브리지가 별도 스레드라 검사와 mutation 사이에 `generate` 가 lock 을 잡아 old 구성을
        capture 하는 창이 남는다. 그래서 generation lock 을 직접 잡고 mutation+auto-check 를
        그 아래서 수행한다 — 그 사이 `generate`(non-blocking acquire)도 작업 전환/작업대 열기
        (`raise_if_generating_before_swap` 가 같은 lock 을 검사)도 끼지 못한다. 생성 중이면
        non-blocking 실패로 시끄럽게 거절한다.
        """
        response = self._slot_command_serialized_with_generation(
            "포함할 내용을 바꾸세요",
            lambda: self.execution.select_slot_option(
                self.work.name,
                str(p["configuration_token"]),
                str(p["slot_id"]),
                str(p["option_id"]),
                str(p["request_id"]),
            ),
        )
        return self._slot_response_dict(response)

    def _slot_command_serialized_with_generation(self, then_do: str, run):
        """durable slot mutation + auto-check 를 generation lock 아래 원자로 수행한다(#725 리뷰).

        generate 와 같은 lock 을 non-blocking 으로 잡아 상호배제한다 — 잡히면 mutation·auto-check
        를 하고 반드시 놓는다. 이미 생성 중이면 시끄럽게 거절한다(`raise_if_generating` 문안 동형).
        """
        if not self.runs.lock.acquire(blocking=False):
            raise ValueError(f"문서 생성이 진행 중입니다. 끝난 뒤에 {then_do}.")
        try:
            work_at_start = self.work.name
            response = run()
            # auto-check 를 이 mutation 의 exact Work 에 결속한다(#725 재리뷰 P1). 작업 전환
            # (`select_job`)은 check-then-act 라 이 임계구역 사이에 job_name 을 바꿀 수 있다 —
            # 그러면 바뀐 Work 를 seal 하게 된다. Work 가 그대로일 때만 auto-check 하고, 바뀌었으면
            # 건너뛴다(변경된 Work 는 자기 command 가 몰고, 이 Work 는 다음 관찰에서 fresh 재계산).
            if self.work.name == work_at_start:
                self._maybe_auto_check(response)
            return response
        finally:
            self.runs.lock.release()

    # `_do_clear_slot_selection` 은 #903 에서 제거됐다 — 유일한 트리거였던 detached 정리 버튼이
    # SG-01(#733) 이후 렌더될 수 없었고, EXACTLY_ONE 제어면에 「선택 비우기」 사용자 목적이 없다.
    # S4 command engine 의 clear(`slot_command.decide_clear`)는 그대로 서 있다(제품 표면만 제거).

    # ----------------------------------- Selection Preset 표면(S9-03 · #829)
    # 두 동사도 **dispatch 경로**다(직접 브리지 신설 0). 수치(적용 n·깨짐 m)는 S9-02
    # `PresetApplyDecision` 값이 Product 를 지나 그대로 실린다 — 여기서도 프런트에서도 slot
    # 목록을 다시 훑어 세지 않는다(같은 상태의 두 판정 금지).
    @staticmethod
    def _savable_selection(slot_zone: dict) -> bool:
        """방금 조립한 slot 존에서 「지금 저장할 선택이 있는가」를 집는다(판정 0 — 운반).

        값을 낸 것은 projection(:func:`~hwpxfiller.application.work_slot_configuration.has_declared_selection`)
        이고 여기는 같은 스냅샷의 두 존이 **같은 한 순간**을 말하도록 그 값을 옆으로 넘길 뿐이다.
        Preset 존이 view 를 따로 한 번 더 조회하면 두 존이 서로 다른 순간을 들 수 있다.
        """
        view = slot_zone.get("current_view") or {}
        projection = view.get("projection") or {}
        return bool(projection.get("savable_selection"))

    def _content_presets_zone(self, tmissing: bool, *, savable_selection: bool) -> dict:
        """스냅샷의 ``content_presets`` 존 — 홈 레지스트리 목록 + 손상 항목 병기.

        지원 조건은 ``slot_configuration`` 존과 **동형**이다(미주입·미선택·미지원 매체·템플릿
        부재면 명시적 unsupported). 목록 자체는 Work 무관이지만 이 존을 소비하는 표면이
        「포함할 내용」 존이라 같은 조건에서 함께 서고 함께 진다 — 그 동형이 매체 축에서도
        유지되므로(S10-03 #860) 매체 판정도 같은 `SUPPORTED_MEDIA` 를 묻는다.

        ``provenance`` 는 싣지 않는다 — advisory 내부 정보(Application·contract id)라 사용자
        표면의 재료가 아니다. 손상 항목은 숨기지 않고 ``corrupt`` 로 함께 나가고, 표면이
        비활성 + 사유 병기로 재진술한다.

        **목록은 현재 템플릿 구조에 전부 적용 가능한 것만 싣는다**(U3 §2 · #875). 종전에는 홈
        레지스트리 전량이 매 작업에 떠서, 다른 템플릿·다른 매체에서 만든 Preset 까지 「적용」
        버튼을 달고 서 있었다. 판정은 Product 를 지나 적용 경로와 **같은 해석**이 진다 — 이
        존은 어느 Work 를 대고 물을지만 정한다(호환을 여기서 다시 세지 않는다). 걸러진 항목의
        저장 파일은 그대로다(목록의 좁힘이지 삭제가 아니다).
        """
        job = (
            load_job(self.registry, self.work.name)
            if self.execution.slot_configuration is not None and self.work.name and not tmissing
            else None
        )
        return self.execution.presets_zone(
            self.work.name,
            job,
            tmissing,
            savable_selection=savable_selection,
        )

    def _do_save_selection_preset(self, p: dict) -> dict:
        """현재 선택을 이름 붙여 보관한다 — 조용한 덮기 경로 0(이름 충돌은 확인 왕복).

        generation lock 을 잡지 않는다: Work durable 상태는 **읽기만** 하고 쓰기는 홈
        레지스트리로 간다. 생성 중 배치가 고정한 실행 입력과 어긋날 것이 없다(select/clear
        와 갈리는 지점이고, 그 이유가 이 주석이다).
        """
        confirmed = p.get("confirmed_overwrite_key")
        result = self.execution.save_selection_preset(
            self.work.name,
            str(p["configuration_token"]),
            str(p["name"]),
            str(confirmed) if confirmed is not None else None,
        )
        return asdict(result)

    def _do_apply_selection_preset(self, p: dict) -> dict:
        """Preset 적용 = durable S4 mutation — select 와 **같은 규율**이다.

        생성과 상호배제하고(`_slot_command_serialized_with_generation`), CHANGED 면 자동
        확인에 진입한다(`_maybe_auto_check` — 응답의 `mutation_outcome` 축이 select 응답과
        같은 형이라 그 판정이 그대로 선다). 응답은 outcome·fresh view·새 token 에 적용 n·
        깨짐 m 을 얹은 것이고, 수치는 backend 값 그대로다.
        """
        response = self._slot_command_serialized_with_generation(
            "프리셋을 적용하세요",
            lambda: self.execution.apply_selection_preset(
                self.work.name,
                str(p["configuration_token"]),
                str(p["preset_key"]),
            ),
        )
        return self._slot_response_dict(response)

    # ── automatic seal orchestration(SX-03 #726 §2·§3 · SX-SEAL 배선) ──────────────────
    def editor_binding_confirm_pending(self, work_ref: str) -> bool:
        """편집 중 작업의 **연결 확정 대기** 여부(#911) — :meth:`on_editor_mapping_saved` 의 짝.

        저쪽이 확정을 쓰는 자리라면 여기는 그 확정이 아직 남았는지를 읽는 자리다. 답은
        관리 검토 사슬이 ``REVIEW_BINDING`` 을 세울 때 쓰는 **바로 그 술어**
        (:func:`~hwpxfiller.application.document_creation_workbench.binding_review_needed`)에
        같은 두 재료를 먹여 얻는다 — 편집기가 자기 기준을 따로 세우면 「확정하라는데 동사가
        없다」의 거울상(확정할 것이 없는데 동사가 서 있다)이 생긴다.

        합성 Observation 을 부르지 않는 이유는 그것이 읽기가 아니기 때문이다:
        :meth:`workbench_observation` 은 레코드 검증·배달 준비를 무효화하므로 편집기
        렌더 경로에서 부르면 세션이 붙들고 있던 준비가 조용히 사라진다.

        배선 가드 셋은 편집기 저장이 실제로 확정을 부르는 조건과 같아야 한다 — 확정하지
        못할 상태에서 동사를 무장하면 눌러도 아무 일이 없다. 세션 증거가 겨눈 작업과 편집
        대상이 다르면 이 세션은 그 작업에 대해 아는 것이 없다(정직한 거짓).
        """
        if (
            self.execution.seal_execution is None
            or self.execution.workbench_product is None
            or not work_ref
            or work_ref != self.work.name
        ):
            return False
        try:
            job = load_job(self.registry, work_ref)
        except Exception:  # noqa: BLE001 - 부재·손상은 「확정할 것 없음」으로 읽는다.
            return False
        if job.media != "hwpx" or not job.authority_id:
            return False
        projection = self.execution.binding_review_projection(self.work.name)
        return self.execution.binding_review_pending(
            input_requirements=(projection.input_requirements if projection is not None else ()),
        )

    def on_editor_mapping_saved(self, work_ref: str) -> dict:
        """Commit the saved Mapping to S5, then reuse automatic current-value checking."""
        job = load_job(self.registry, work_ref)
        if job.media != "hwpx" or not job.authority_id:
            return {"binding_commit_ok": False, "binding_revision_id": None}
        if self.execution.seal_execution is None:
            raise ValueError("Field Binding is not configured.")
        if not self.runs.lock.acquire(blocking=False):
            raise ValueError(
                "\ubb38\uc11c \uc0dd\uc131\uc774 \uc9c4\ud589 \uc911\uc785\ub2c8\ub2e4. \ub05d\ub09c \ub4a4\uc5d0 Mapping\uc744 \uc800\uc7a5\ud558\uc138\uc694."
            )
        try:
            result = self.execution.commit_current_mapping(work_ref)
            if result is not None and self.work.name == work_ref:
                self._maybe_auto_check(effective_basis_changed=result.changed)
            return {
                "binding_commit_ok": result is not None,
                "binding_revision_id": result.revision_id if result is not None else None,
            }
        finally:
            self.runs.lock.release()

    def _maybe_auto_check(
        self, slot_response=None, *, effective_basis_changed: "bool | None" = None
    ) -> None:
        """HWPX의 durable basis가 실제로 바뀐 뒤에만 자동 봉인을 시작한다.

        미변경 명령과 TXT 작업은 실행 계획의 basis가 아니므로 봉인하지 않는다.
        """
        if self.execution.seal_execution is None or not self.work.name:
            return
        if load_job(self.registry, self.work.name).media != "hwpx":
            return
        if effective_basis_changed is None:
            if slot_response is None:
                raise ValueError("슬롯 변경 결과가 없습니다")
            outcome = slot_response.mutation_outcome
            effective_basis_changed = outcome is not None and outcome.changed
        if not effective_basis_changed:
            return  # 무변이(open/ensure)·미변경 mutation → 반응할 basis 변경 없음.
        if self.execution.start_after_durable_change():
            self._run_automatic_seal()

    def _run_automatic_seal(self) -> None:
        """진행 중 orchestration(CHECKING)에서 실 seal 을 돌리고 결과로 다음 상태를 판정한다.

        coalesce 대기(진행 중 도착한 basis 변경)를 소진할 때만 다시 seal 한다 — 무한 자동 재시도 0.
        route/context 예외는 seal 실패(연속 실패 수 상한 → 수동 복구)로, 반환된 terminal outcome 은
        '실행됨'으로 본다(qualification/policy block 은 실패가 아니라 not-current 로 알린다).
        """
        self.execution.run_automatic_seal(
            self.work.name, max_coalesced=self._MAX_AUTO_SEAL_COALESCE
        )

    #: 진행 중 seal 위에 coalesce 로 이어붙는 연속 확인의 상한(무한 루프 방지).
    _MAX_AUTO_SEAL_COALESCE = 4

    def _capture_current_selected_records(
        self,
        run_input: RunInputCapture | None = None,
    ) -> tuple[int, tuple[int, ...], tuple[RawDataRecordSnapshot, ...]]:
        """선택 행을 frozen snapshot 으로 고정한다 — Plan 을 보지 않는다(값은 타입 없는 텍스트)."""
        generation = (
            run_input.snapshot_generation
            if run_input is not None
            else self.data.snapshot_generation
        )
        indices = (
            run_input.indices if run_input is not None else tuple(self.data.selected_indices())
        )
        rows = run_input.source_records if run_input is not None else self.data.records
        schema = (
            run_input.source_schema_keys
            if run_input is not None
            else (
                tuple(self.data.filter.columns)
                if self.data.filter is not None
                else tuple(rows[0].keys())
                if rows
                else ()
            )
        )
        captured_at = self._clock().isoformat(timespec="seconds")
        captured = capture_selected_records(
            snapshot_generation=generation,
            ordered_model_indices=indices,
            rows=rows,
            source_schema_keys=schema,
            captured_at=captured_at,
        )
        if (
            generation != self.data.snapshot_generation
            or rows is not self.data.records
            or indices != tuple(self.data.selected_indices())
        ):
            raise _CurrentRecordCaptureError(
                "데이터가 다시 불러와져 선택한 값을 함께 확인할 수 없습니다. 다시 시도해 주세요."
            )
        return generation, indices, captured

    def _current_record_validation(
        self,
        run_input: RunInputCapture | None = None,
    ) -> tuple[RecordValidationSummary, WorkbenchContextIntegrity | None]:
        fresh = self.execution.fresh_observation
        if not self.execution.is_settled_current:
            return RecordValidationSummary(), None
        if not isinstance(fresh, CurrentSealedPlanObservation):
            return RecordValidationSummary(), None
        plan = fresh.sealed_plan_value
        work_ref = run_input.work_ref if run_input is not None else self.work.name
        indices = (
            run_input.indices if run_input is not None else tuple(self.data.selected_indices())
        )
        generation = (
            run_input.snapshot_generation
            if run_input is not None
            else self.data.snapshot_generation
        )
        cached = self.execution.cached_records(
            snapshot_generation=generation,
            work_ref=work_ref,
            ordered_model_indices=indices,
            plan=plan,
        )
        if cached is not None:
            return cached.record_validation, None
        if not indices:
            return RecordValidationSummary(), None
        try:
            generation, captured_indices, raw_records = self._capture_current_selected_records(
                run_input
            )
            preparation = self.execution.prepare_records(
                snapshot_generation=generation,
                work_ref=work_ref,
                ordered_model_indices=captured_indices,
                plan=plan,
                raw_records=raw_records,
                project_issue=lambda blocker, model_index, record_identity: record_issue(
                    plan=plan,
                    blocker=blocker,
                    generation=generation,
                    model_index=model_index,
                    record_identity=record_identity,
                    columns=self.data.filter.columns if self.data.filter is not None else [],
                ),
            )
        except (_CurrentRecordCaptureError, RawDataRecordError, FieldBindingError) as exc:
            return RecordValidationSummary(), WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_RECORD_CAPTURE_STALE",
                detail=str(exc),
            )
        if isinstance(preparation, WorkbenchContextIntegrity):
            return RecordValidationSummary(), preparation
        if (
            generation != self.data.snapshot_generation
            or captured_indices != tuple(self.data.selected_indices())
            or work_ref != self.work.name
            or fresh != self.execution.fresh_observation
        ):
            return RecordValidationSummary(), WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_RECORD_PREPARATION_STALE",
                detail="확인 중 데이터나 작업 설정이 바뀌었습니다. 다시 시도해 주세요.",
            )
        self.execution.install_records(preparation)
        return preparation.record_validation, None

    def _do_recover_record_issue(self, p: dict) -> dict:
        target = p.get("target")
        if not isinstance(target, Mapping):
            raise ValueError("문제 위치 정보가 올바르지 않습니다.")
        preparation = self.execution.record_preparation
        target_kind = target.get("target_kind")
        if preparation is None:
            raise ValueError("현재 데이터 확인 결과가 없습니다. 다시 확인해 주세요.")
        exact_targets = tuple(
            asdict(issue.recovery_target) for issue in preparation.record_validation.issues
        )
        if dict(target) not in exact_targets:
            raise ValueError(
                "데이터가 다시 불러와져 문제 위치를 복원할 수 없습니다. 현재 데이터에서 다시 확인해 주세요."
            )
        generation = target.get("snapshot_generation")
        model_index = target.get("model_index")
        record_identity = target.get("record_identity")
        field_id = target.get("field_id")
        if (
            type(generation) is not int
            or type(model_index) is not int
            or not isinstance(record_identity, str)
            or not isinstance(field_id, str)
            or target_kind not in ("cell", "row")
            or generation != self.data.snapshot_generation
            or model_index not in tuple(self.data.selected_indices())
            or record_identity != current_record_identity(generation, model_index)
            or preparation.work_ref != self.work.name
            or not self.execution.is_settled_current
            or not isinstance(
                self.execution.fresh_observation,
                CurrentSealedPlanObservation,
            )
            or preparation.execution_value != self.execution.fresh_observation.sealed_plan_value
        ):
            raise ValueError(
                "데이터가 다시 불러와져 문제 위치를 복원할 수 없습니다. 현재 데이터에서 다시 확인해 주세요."
            )
        columns = self.data.filter.columns if self.data.filter is not None else []
        if target_kind == "cell" and field_id not in columns:
            raise ValueError("문제 데이터의 항목 위치를 복원할 수 없습니다.")
        if target_kind == "cell" and field_id in self.data.hidden_columns:
            raise ValueError("문제 항목이 숨겨져 있습니다. 열을 다시 표시한 뒤 이동해 주세요.")
        visible = (
            self.data.filter.visible_indices(self.data.records)
            if self.data.filter is not None
            else []
        )
        if model_index not in visible:
            raise ValueError("문제 행이 현재 검색 결과에 없습니다. 검색 조건을 해제해 주세요.")
        if target_kind == "row":
            return {
                "ok": True,
                "element_id": f"jobRow-{model_index}",
                "fallback_element_id": f"jobRow-{model_index}",
            }
        column_index = columns.index(field_id)
        return {
            "ok": True,
            "element_id": f"jobCell-{model_index}-{column_index}",
            "fallback_element_id": f"jobRow-{model_index}",
        }

    _do_recover_record_issue.is_query = True

    def _current_delivery(
        self,
        record_validation: RecordValidationSummary,
        *,
        run_input: RunInputCapture | None = None,
        filename_pattern: str | None = None,
    ) -> tuple[DeliveryPreviewSummary, WorkbenchContextIntegrity | None]:
        intent, folder_resolution = self._effective_delivery()
        work_ref = run_input.work_ref if run_input is not None else self.work.name
        generation = (
            run_input.snapshot_generation
            if run_input is not None
            else self.data.snapshot_generation
        )
        indices = (
            run_input.indices if run_input is not None else tuple(self.data.selected_indices())
        )
        exact_pattern = (
            filename_pattern
            if filename_pattern is not None
            else self.work.vm.job.filename_pattern
            if self.work.vm is not None
            else ""
        )
        return self.execution.resolve_delivery(
            record_validation=record_validation,
            snapshot_generation=generation,
            work_ref=work_ref,
            ordered_model_indices=indices,
            fresh_observation=self.execution.fresh_observation,
            run_delivery_intent=intent,
            exact_pattern=exact_pattern,
            capture_delivery_clock=lambda: self._clock().isoformat(timespec="seconds"),
            allow_missing_output_directory=(
                folder_resolution.source != OUTPUT_FOLDER_SOURCE_SETTING
            ),
        )

    def workbench_observation(
        self,
        *,
        run_input: RunInputCapture | None = None,
        filename_pattern: str | None = None,
    ):
        """현재 config를 읽고 레코드·배달 준비를 갱신해 Observation을 만든다."""
        if self.execution.workbench_product is None:
            raise ValueError("작업대 Observation 기능이 조립되지 않았습니다")
        work_ref = run_input.work_ref if run_input is not None else self.work.name
        job = (
            load_job(self.registry, work_ref)
            if self.execution.slot_configuration is not None and work_ref
            else None
        )
        configuration = self.execution.capture_workbench_configuration(job=job, work_ref=work_ref)
        if not self.execution.is_settled_current:
            self.execution.invalidate_preparations()
        record_validation, context_integrity = self._current_record_validation(run_input)
        if context_integrity is None:
            delivery, context_integrity = self._current_delivery(
                record_validation,
                run_input=run_input,
                filename_pattern=filename_pattern,
            )
        else:
            delivery = DeliveryPreviewSummary(resolvable=False)
        return self.execution.build_workbench_observation(
            configuration=configuration,
            work_ref=work_ref,
            data_mounted=(
                run_input.data.datasource is not None
                if run_input is not None
                else self.data.datasource is not None
            ),
            selected_record_count=(
                len(run_input.indices)
                if run_input is not None
                else self.data.selection.selected_count()
            ),
            total_record_count=(
                len(run_input.data.records) if run_input is not None else len(self.data.records)
            ),
            active_work_data_bound=not self.work.data_unbound,
            record_validation=record_validation,
            delivery=delivery,
            template_change_verdict=self._template_change_verdict(),
            run_delivery_intent=self._effective_run_delivery_intent(),
            context_integrity=context_integrity,
        )

    def _template_change_verdict(self) -> "str | None":
        """현재 작업의 템플릿 확인 상태를 읽기 전용으로 투영한다.

        렌더 경로에서 권위를 만들지 않으며 status 판정은 application 함수에 위임한다.
        """
        if self._template_change is None or not self.work.name:
            return None
        try:
            if load_job(self.registry, self.work.name).media != "hwpx":
                return None
            preparation = self._template_change.get_current_template_change_preparation(
                self.work.name
            )
        except Exception:  # noqa: BLE001 — 조회 실패는 확인 요구가 아니다(context 축 소관).
            return None
        status = preparation.get("status") if preparation is not None else None
        # 드리프트도 같은 요구를 세운다(#932 B5) — 존이 조치가 있을 때만 서게 된 뒤로,
        # 원본이 갈린 사실을 사용자가 못 본 채 캡처본으로 생성할 창이 생겼다. 판정은 여전히
        # application 층 한 곳이고 여기는 축을 실어 나르기만 한다.
        return workbench_template_change_verdict(status, self._source_drift_state())

    def _source_drift_state(self) -> "str | None":
        """현재 작업의 원본 드리프트 상태 — 읽기 전용(digest 비교뿐, 권위 발급 없음)."""
        if self._template_change is None or not self.work.name:
            return None
        try:
            return self._template_change.source_drift(self.work.name).state
        except Exception:  # noqa: BLE001 — 조회 실패는 요구가 아니다(context 축 소관).
            return None

    def _do_resolve_execution(self, p: dict) -> dict:
        """사용자 요청으로 자동 봉인 경로를 다시 시작한다.

        실패 상태는 수동 복구 전이를 먼저 거치며, 서비스 미주입은 명시적으로 거절한다.
        """
        if self.execution.seal_execution is None:
            raise ValueError("실행 확인 기능이 조립되지 않았습니다")
        if not self.work.name:
            raise ValueError("먼저 문서 작업을 선택하세요.")
        if self.execution.start_manual_recovery():
            self._run_automatic_seal()
        return {"ok": True}

    def _do_refresh_observation(self, p: dict) -> dict:
        """orchestration 전이 없이 fresh observation을 다시 계산한다.

        실패하면 이전 CURRENT를 유지하지 않고 context error로 교체한다. 미주입·미선택은
        기존 계약대로 무동작이다.
        """
        self.execution.refresh_observation(self.work.name)
        return {"ok": True}
