"""SealExecutionPlan Product 의 실 store 결선 서비스 (SX-SEAL · #719, post-R2 #740 착지).

:class:`SealExecutionPlanProduct` 는 seal seam(capture·summary·shipping policy)을 injectable 로
남긴 headless service 다. 이 모듈은 그 seam 을 production store 로 결선하고 「문서 만들기」 패널
(:class:`JobController`)에 주입할 얇은 표면을 낸다.

배치·공유: :class:`hwpxfiller.webapp.slot_configuration_product.SlotConfigurationProduct`·
:class:`TemplateChangeCoordinator` 와 **같은 template authority root**(:func:`default_template_authority_dir`)
아래 같은 subdir 을 연다 — bootstrap 이 세운 Work/Application/PASS Evidence·slot config와
구판 field binding을 읽는다(별도 스토어 조립 없음). 새 저장본의 실행 Binding은 Job Mapping에서
읽기 시점에 파생하며 S5 저장소에 다시 쓰지 않는다. :class:`WorkspaceMetadataStore` 는 root 를 직접
공유해 SlotConfigurationProduct 와 **같은 workspace_instance_id** 를 쓰고, 따라서 per-Work fence
키(ws, work_id)도 같은 namespace 에 든다.

**R2(#740) 착지.** historical durable Plan store·mutable Profile admission store·opaque Plan ref
(``resolve_plan_reference``)·HMAC secret 을 전부 제거했다 — observation 은 저장된 과거 Plan 을
조회하지 않고 매 호출 current authority 를 PerWorkFence 하나 아래 재계산한다(``fresh_observation``).
그래서 이 service 는 route·auth·capture·summary·shipping policy seam 만 결선한다.

구판 Job은 S5 판본과 Mapping을 대조해 충돌·이전 의미 판본을 검토 요구로 닫는다. 명시적
편집기 저장이 Job Mapping 권위를 세운 뒤에는 모든 규칙(비활성 Field 포함)을 그 저장본에서
파생하므로 Option 왕복에 추가 확정이나 S5 쓰기가 필요 없다.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.document_creation_workbench import InputRequirement
from ..application.jobs import (
    JobStorePort,
    ensure_job_authority_id,
    load_job,
)
from ..application.execution_composition import RuntimeMaterializerConformanceRegistry
from ..application.execution_structure import decode_execution_structure
from ..application.seal_execution_plan import (
    RouteResolutionError,
    SealExecutionPlanCommand,
)
from ..application.shipping_seal_policy import resolve_shipping_policy
from ..domain.job import Job
from ..domain.job import JOB_MAPPING_AUTHORITY
from .candidate_store import CandidateObjectStore
from .job_binding_projection import source_schema_keys as _source_schema_keys
from .field_binding_store import WorkFieldBindingStore
from .qualification_store import QualificationObjectStore
from .runtime_capability import (
    admitted_runtime_conformance_registry,
    admitted_txt_runtime_conformance,
)
from .seal_orchestration_runner import observe_current_basis_digest
from .seal_execution_capture_runner import (
    CurrentFieldBindingReview,
    SealExecutionCaptureRunner,
)
from .work_configuration_store import (
    WorkSlotConfigurationStore,
    WorkspaceMetadataStore,
)
from .work_template_store import AtomicWorkTemplateStateStore
from .work_template_store import WorkAggregateNotFound
from .seal_execution_plan_product import (
    RuntimeConformanceBinding,
    SealExecutionPlanProduct,
    SealExecutionPlanProductCommand,
    SealExecutionPlanResponse,
)


@dataclass(frozen=True)
class BindingReviewProjection:
    """Backend-authored review items; the UI performs no Binding inference."""

    active_field_ids: tuple[str, ...]
    input_requirements: tuple[InputRequirement, ...]


@dataclass(frozen=True)
class ManagedRunContext:
    """managed materialization 조립 재료(S6-05 · #812) — 서비스가 이미 쥔 것의 읽기 전용 묶음."""

    root: Path
    workspace_instance_id: str
    work_authority_id: str
    runtime_registry: RuntimeMaterializerConformanceRegistry
    runtime_capability_manifest_digest: str
    current_basis_digest_reader: "Callable[[], str | None]"


class SealExecutionPlanService:
    """job 화면이 소비하는 seal-execution Product 서비스 — webview 비의존, 헤드리스 구동."""

    def __init__(
        self,
        registry: JobStorePort,
        *,
        root: "str | Path",
        clock: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._root = Path(root)
        self._clock = clock
        # Per-call routing context, never a shared current-Work cache. Capture loads
        # the Job by its verified name so each basis read sees current atomic JSON.
        self._routed_work_ref: ContextVar[str | None] = ContextVar(
            "seal_routed_work_ref", default=None
        )
        # SlotConfigurationProduct·TemplateChangeCoordinator 와 같은 subdir(공유 authority root).
        work_state = AtomicWorkTemplateStateStore(self._root / "works")
        qualification = QualificationObjectStore(self._root / "qualification")
        candidate = CandidateObjectStore(self._root / "candidates")
        slot_config = WorkSlotConfigurationStore(self._root / "slot_configs")
        field_binding = WorkFieldBindingStore(self._root / "field_bindings")
        # root 직접 공유 → SlotConfigurationProduct 와 같은 workspace_instance_id.
        self._workspace = WorkspaceMetadataStore(self._root)

        self._work_state = work_state
        self._qualification = qualification
        capture = SealExecutionCaptureRunner(
            work_state_store=work_state,
            qualification_store=qualification,
            candidate_store=candidate,
            slot_config_store=slot_config,
            field_binding_store=field_binding,
            clock=self._seal_clock,
            job_for_work=self._routed_job,
        )
        self._capture = capture
        # S6-03(#810) 정식 주입 경로: shipping capability manifest 를 등록한 registry 인스턴스를
        # 결속한다 — 전역 DEFAULT registry 는 계속 비어 있고(`runtime_conformance=` kwarg 우회도
        # 여전히 금지), 판정은 매 관찰마다 Plan value 파생 7축 query 로 registry 가 낸다.
        runtime_registry, runtime_manifest = admitted_runtime_conformance_registry()
        self._runtime_registry = runtime_registry
        self._runtime_manifest = runtime_manifest
        # 같은 registry 안에 TXT 축 manifest 도 등록돼 있다(S10-04 · #861). admission 은 7축
        # 전건 AND 라 서로를 admit 하지 못하므로, 관찰·start gate 는 Plan 이 선언한 native
        # primitive 로 자기 manifest 를 고른다.
        self._txt_runtime_manifest = admitted_txt_runtime_conformance()
        # R2(#740): plan_store·read_admission_state·load_secret seam 이 사라졌다 — Product 는
        # route/auth + capture/summary/shipping 만 받아 매 호출 current authority 를 재계산한다.
        self._product = SealExecutionPlanProduct(
            resolve_route=self._resolve_route,
            authorize=self._authorize,
            read_summary=capture.read_summary,
            capture_under_fence=capture.capture_execution,
            resolve_shipping_policy=resolve_shipping_policy,
            clock=self._seal_clock,
            runtime_conformance_binding=RuntimeConformanceBinding(
                registry=runtime_registry,
                manifest=runtime_manifest,
                additional_manifests=(self._txt_runtime_manifest,),
            ),
        )

    # ── public surface(product 를 감싸는 얇은 표면) ────────────────────────────────
    def managed_run_context(
        self, work_ref: str, *, media: str = "hwpx"
    ) -> "ManagedRunContext | None":
        """managed materialization 조립 재료의 묶음 accessor(S6-05 · #812) — 발급 0.

        이 서비스가 __init__ 에서 이미 쥔 것(authority root·workspace·runtime registry·
        capability manifest·capture 결선)을 그대로 노출한다. ``authority_id`` 가 없으면 None —
        여기서 발급하지 않는다(발급은 라우팅·확인의 몫, 실행 준비 조회는 읽기 전용).
        reader 는 fence 없는 current basis 관찰이라 start gate 가 fence 아래에서 부른다.
        """
        job = load_job(self._registry, work_ref)
        if not job.authority_id:
            return None
        workspace_id = self._workspace.read()
        if workspace_id is None:
            return None
        work_id = job.authority_id
        command = SealExecutionPlanCommand(
            workspace_instance_id=workspace_id,
            work_ref=work_ref,
            request_id="managed-basis-read",
        )

        def read_basis() -> "str | None":
            token = self._routed_work_ref.set(work_ref)
            try:
                return observe_current_basis_digest(
                    command,
                    work_id,
                    read_summary=self._capture.read_summary,
                    capture_under_fence=self._capture.capture_execution,
                    resolve_shipping_policy=resolve_shipping_policy,
                )
            finally:
                self._routed_work_ref.reset(token)

        return ManagedRunContext(
            root=self._root,
            workspace_instance_id=workspace_id,
            work_authority_id=work_id,
            runtime_registry=self._runtime_registry,
            # capability manifest 는 매체축이다(S10-04 · #861) — 같은 registry 에 둘이 등록돼
            # 있고 admission 은 7축 전건 AND 라 잘못 고른 digest 는 조용히 통과하지 못한다.
            runtime_capability_manifest_digest=(
                self._txt_runtime_manifest
                if media == "txt"
                else self._runtime_manifest
            ).runtime_capability_manifest_digest,
            current_basis_digest_reader=read_basis,
        )

    def seal_execution_plan(
        self, work_ref: str, request_id: str
    ) -> SealExecutionPlanResponse:
        """current shipping default(AUTO)로 이 Work 의 exact execution plan 을 봉인·관찰한다.

        R2(#740): durable publication 없이 command outcome(``execution_basis_digest``)과 current
        Sealed Plan value 를 재계산한 fresh_observation 을 나란히 낸다 — opaque Plan ref 는 없다.
        """
        ws = self._workspace.get_or_create(self._seal_clock())
        command = SealExecutionPlanProductCommand(
            workspace_instance_id=ws, work_ref=work_ref, request_id=request_id
        )
        token = self._routed_work_ref.set(work_ref)
        try:
            return self._product.seal_execution_plan(command)
        finally:
            self._routed_work_ref.reset(token)

    def current_binding_review(self, work_ref: str) -> BindingReviewProjection | None:
        """Read-only Active Field/Binding review projection for the current exact basis."""
        job = load_job(self._registry, work_ref)
        if not job.authority_id:
            return None
        workspace_id = self._workspace.read()
        if workspace_id is None:
            return None
        current: CurrentFieldBindingReview | None = self._capture.read_current_field_binding_review(
            workspace_id,
            job.authority_id,
            _source_schema_keys(job.mapping),
            job=job,
        )
        if current is None:
            return None
        return BindingReviewProjection(
            active_field_ids=current.active_field_ids,
            input_requirements=tuple(
                InputRequirement(
                    field_id=item.field_id,
                    display_label=item.field_id,
                    binding_state=item.category,
                    exact_target=f"binding/{item.field_id}",
                )
                for item in current.review.classifications
            ),
        )

    # ── seam 결선 ──────────────────────────────────────────────────────────────────
    def _seal_clock(self) -> str:
        return self._clock().isoformat()

    def _routed_job(self, work_id: str) -> Job:
        work_ref = self._routed_work_ref.get()
        if work_ref is None:
            raise ValueError("Field Binding capture 에 routed Job 이 없습니다")
        job = load_job(self._registry, work_ref)
        if job.authority_id != work_id:
            raise ValueError("Field Binding capture 의 Work identity 가 이동했습니다")
        return job

    def unrepresented_legacy_rules(
        self, previous: Job, candidate: Job, editor_field_ids: frozenset[str]
    ) -> tuple[str, ...]:
        """Names of still-present S5 rules an explicit Job save cannot carry.

        Called by the editor while it holds the generation lease, before replacing
        Job JSON. A field removed from the current template is BROKEN, not inactive.
        """
        if previous.binding_authority == JOB_MAPPING_AUTHORITY or not previous.authority_id:
            return ()
        try:
            aggregate = self._work_state.load(previous.authority_id)
        except WorkAggregateNotFound as exc:
            raise ValueError("이전 Field Binding 의 Work 상태를 확인할 수 없습니다") from exc
        application_id = aggregate.work.current_template_application_id
        prior = self._capture._nearest_binding_revision(aggregate, application_id)
        if prior is None:
            return ()
        application = next(
            (item for item in aggregate.applications if item.application_id == application_id),
            None,
        )
        if application is None:
            raise ValueError("현재 템플릿 Application 을 확인할 수 없습니다")
        evidence = self._qualification.get_evidence(application.pass_evidence_id)
        projection = evidence.structure_projection
        if projection is None:
            raise ValueError("현재 템플릿의 Field 구조를 확인할 수 없습니다")
        structure = decode_execution_structure(projection.payload)
        present_fields = {
            occurrence.field_id
            for occurrence in structure.field_occurrences
        }
        saved_fields = {item.template_field for item in candidate.mapping.mappings}
        return tuple(
            rule.field_id
            for rule in prior.binding_rules
            if rule.field_id in present_fields
            and rule.field_id in editor_field_ids
            and rule.field_id not in saved_fields
        )

    def _resolve_route(self, workspace_instance_id: str, work_ref: str) -> str:
        """work_ref → WorkAuthorityId. 부재·손상은 RouteResolutionError(attempt, request 미소비)."""
        try:
            job = load_job(self._registry, work_ref)
        except Exception as exc:  # 부재·손상 = 접근 불가
            raise RouteResolutionError(f"work {work_ref!r} 접근 불가") from exc
        # 발급 형태·결속은 단일 helper(S6-05 · #812) — lazy 발급은 의미 1·2 의 성질.
        work_id = job.authority_id or ensure_job_authority_id(self._registry, work_ref)
        return work_id

    def _authorize(self, work_id: str, workspace_instance_id: str) -> None:
        # 단일 사용자 desktop — route(load_job)이 접근성을 이미 확인한다(별도 actor 판정 없음).
        return None


__all__ = [
    "BindingReviewProjection",
    "SealExecutionPlanService",
]
