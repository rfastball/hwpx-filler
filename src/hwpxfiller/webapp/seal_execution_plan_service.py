"""SealExecutionPlan Product 의 실 store 결선 서비스 (SX-SEAL · #719, post-R2 #740 착지).

:class:`SealExecutionPlanProduct` 는 seal seam(capture·summary·shipping policy)을 injectable 로
남긴 headless service 다. 이 모듈은 그 seam 을 production store 로 결선하고 「문서 만들기」 패널
(:class:`JobController`)에 주입할 얇은 표면을 낸다.

배치·공유: :class:`hwpxfiller.webapp.slot_configuration_product.SlotConfigurationProduct`·
:class:`TemplateChangeCoordinator` 와 **같은 template authority root**(:func:`default_template_authority_dir`)
아래 같은 subdir 을 연다 — bootstrap 이 세운 Work/Application/PASS Evidence·slot config·field
binding 을 그대로 읽는다(별도 스토어 조립 없음). :class:`WorkspaceMetadataStore` 는 root 를 직접
공유해 SlotConfigurationProduct 와 **같은 workspace_instance_id** 를 쓰고, 따라서 per-Work fence
키(ws, work_id)도 같은 namespace 에 든다.

**R2(#740) 착지.** historical durable Plan store·mutable Profile admission store·opaque Plan ref
(``resolve_plan_reference``)·HMAC secret 을 전부 제거했다 — observation 은 저장된 과거 Plan 을
조회하지 않고 매 호출 current authority 를 PerWorkFence 하나 아래 재계산한다(``fresh_observation``).
그래서 이 service 는 route·auth·capture·summary·shipping policy seam 만 결선한다.

경계: additive 다. dispatch·automatic 트리거·action registry·frontend·generated types 배선은
SX-03 소유고, field-binding commit 도 SX-03 이 진다 — 이 service 는 field binding 을 **읽기만**
한다(capture 가 exact revision 을 복원할 뿐 쓰지 않는다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.document_creation_workbench import InputRequirement
from ..application.jobs import (
    JobStorePort,
    assign_job_authority_id,
    load_job,
)
from ..application.seal_execution_plan import RouteResolutionError
from ..application.shipping_seal_policy import resolve_shipping_policy
from ..external.candidate_store import CandidateObjectStore
from ..external.field_binding_store import WorkFieldBindingStore
from ..external.qualification_store import QualificationObjectStore
from ..external.seal_execution_capture_runner import (
    CurrentFieldBindingReview,
    SealExecutionCaptureRunner,
)
from ..external.work_configuration_store import (
    WorkSlotConfigurationStore,
    WorkspaceMetadataStore,
)
from ..external.work_template_store import AtomicWorkTemplateStateStore
from .seal_execution_plan_product import (
    SealExecutionPlanProduct,
    SealExecutionPlanProductCommand,
    SealExecutionPlanResponse,
)



@dataclass(frozen=True)
class BindingReviewProjection:
    """Backend-authored review items; the UI performs no Binding inference."""

    active_field_ids: tuple[str, ...]
    input_requirements: tuple[InputRequirement, ...]

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
        # SlotConfigurationProduct·TemplateChangeCoordinator 와 같은 subdir(공유 authority root).
        work_state = AtomicWorkTemplateStateStore(self._root / "works")
        qualification = QualificationObjectStore(self._root / "qualification")
        candidate = CandidateObjectStore(self._root / "candidates")
        slot_config = WorkSlotConfigurationStore(self._root / "slot_configs")
        field_binding = WorkFieldBindingStore(self._root / "field_bindings")
        # root 직접 공유 → SlotConfigurationProduct 와 같은 workspace_instance_id.
        self._workspace = WorkspaceMetadataStore(self._root)

        capture = SealExecutionCaptureRunner(
            work_state_store=work_state,
            qualification_store=qualification,
            candidate_store=candidate,
            slot_config_store=slot_config,
            field_binding_store=field_binding,
            clock=self._seal_clock,
        )
        self._capture = capture
        # R2(#740): plan_store·read_admission_state·load_secret seam 이 사라졌다 — Product 는
        # route/auth + capture/summary/shipping 만 받아 매 호출 current authority 를 재계산한다.
        self._product = SealExecutionPlanProduct(
            resolve_route=self._resolve_route,
            authorize=self._authorize,
            read_summary=capture.read_summary,
            capture_under_fence=capture.capture_execution,
            resolve_shipping_policy=resolve_shipping_policy,
            clock=self._seal_clock,
        )

    # ── public surface(product 를 감싸는 얇은 표면) ────────────────────────────────
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
        return self._product.seal_execution_plan(command)

    def current_binding_review(self, work_ref: str) -> BindingReviewProjection | None:
        """Read-only Active Field/Binding review projection for the current exact basis."""
        job = load_job(self._registry, work_ref)
        if not job.authority_id:
            return None
        workspace_id = self._workspace.read()
        if workspace_id is None:
            return None
        current: CurrentFieldBindingReview | None = (
            self._capture.read_current_field_binding_review(
                workspace_id, job.authority_id
            )
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

    def _resolve_route(self, workspace_instance_id: str, work_ref: str) -> str:
        """work_ref → WorkAuthorityId. 부재·손상은 RouteResolutionError(attempt, request 미소비)."""
        try:
            job = load_job(self._registry, work_ref)
        except Exception as exc:  # 부재·손상 = 접근 불가
            raise RouteResolutionError(f"work {work_ref!r} 접근 불가") from exc
        work_id = job.authority_id or assign_job_authority_id(
            self._registry, work_ref, uuid.uuid4().hex
        ).authority_id
        assert work_id is not None
        return work_id

    def _authorize(self, work_id: str, workspace_instance_id: str) -> None:
        # 단일 사용자 desktop — route(load_job)이 접근성을 이미 확인한다(별도 actor 판정 없음).
        return None


__all__ = ["BindingReviewProjection", "SealExecutionPlanService"]
