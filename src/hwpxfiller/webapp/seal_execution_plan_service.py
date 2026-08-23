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

SX-03(#726): passive Binding review는 읽기만 하고, exact binding/<fieldId> 편집 저장 명령만
기존 S5 commit 함수로 Work-default immutable revision을 쓴다. commit 함수가 PerWorkFence 아래
Application 구조와 legacy Mapping 지문을 다시 확인하며, seal은 계속 current value 재계산이다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.document_creation_workbench import InputRequirement
from ..application.field_binding_input import (
    CurrentApplicationFieldStructure,
    FieldBindingMigrationDraft,
    FieldBindingReviewRequired,
    LegacyFieldBindingEntry,
    StaleFieldBindingBasis,
    build_field_binding_input,
    legacy_field_binding_basis_fingerprint,
    prepare_legacy_field_binding_migration,
)
from ..application.jobs import (
    JobStorePort,
    assign_job_authority_id,
    load_job,
)
from ..application.seal_execution_plan import RouteResolutionError
from ..application.shipping_seal_policy import resolve_shipping_policy
from ..domain.field_binding import (
    FieldBindingRule,
    resolve_document_value_policy,
)
from ..domain.job import Job
from ..domain.mapping import MappingProfile
from ..domain.raw_data_record import RAW_RECORD_CONTRACT_ID
from ..external.candidate_store import CandidateObjectStore
from ..external.field_binding_store import (
    LegacyMigrationBasis,
    WorkFieldBindingStore,
    commit_field_binding_for_current_application,
    commit_field_binding_migration,
    load_current_revision,
)
from ..external.qualification_store import QualificationObjectStore
from ..external.runtime_capability import admitted_runtime_conformance_registry
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
class BindingCommitProjection:
    """Result of translating the saved legacy Mapping into S5 authority."""

    changed: bool
    revision_id: str


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

        self._work_state = work_state
        self._field_binding = field_binding
        capture = SealExecutionCaptureRunner(
            work_state_store=work_state,
            qualification_store=qualification,
            candidate_store=candidate,
            slot_config_store=slot_config,
            field_binding_store=field_binding,
            clock=self._seal_clock,
        )
        self._capture = capture
        # S6-03(#810) 정식 주입 경로: shipping capability manifest 를 등록한 registry 인스턴스를
        # 결속한다 — 전역 DEFAULT registry 는 계속 비어 있고(`runtime_conformance=` kwarg 우회도
        # 여전히 금지), 판정은 매 관찰마다 Plan value 파생 7축 query 로 registry 가 낸다.
        runtime_registry, runtime_manifest = admitted_runtime_conformance_registry()
        self._runtime_registry = runtime_registry
        self._runtime_manifest = runtime_manifest
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
                registry=runtime_registry, manifest=runtime_manifest
            ),
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
                workspace_id,
                job.authority_id,
                _source_schema_keys(job.mapping),
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

    def commit_current_mapping(
        self, work_ref: str, request_id: str
    ) -> BindingCommitProjection | None:
        """Commit an explicit legacy Mapping save as the Work-default S5 revision."""
        job = load_job(self._registry, work_ref)
        if job.media != "hwpx" or not job.authority_id:
            return None
        workspace_id = self._workspace.get_or_create(self._seal_clock())
        entries = _legacy_entries(job.mapping)
        schema_keys = _source_schema_keys(job.mapping)
        captured_at = self._seal_clock()
        current = self._capture.read_current_field_binding_review(
            workspace_id,
            job.authority_id,
            schema_keys,
        )
        if current is None:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED",
                "current Active Field를 확인할 수 없습니다",
            )

        active = frozenset(current.active_field_ids)
        mapped = {entry.template_field for entry in entries}
        missing = tuple(
            field_id for field_id in current.active_field_ids if field_id not in mapped
        )
        if missing:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_APPLICATION_REVIEW_REQUIRED",
                f"현재 Active Field의 Mapping 결정이 필요합니다: {', '.join(missing)}",
            )

        draft = prepare_legacy_field_binding_migration(
            work_authority_id=job.authority_id,
            base_template_application_id=current.review.target_application_id,
            legacy_entries=entries,
            captured_at=captured_at,
        )
        resolved = build_field_binding_input(
            workspace_instance_id=workspace_id,
            work_authority_id=job.authority_id,
            base_template_application_id=current.review.target_application_id,
            binding_rules=_resolved_rules(draft, entries, active),
            source_schema_keys=schema_keys,
            raw_record_contract_id=RAW_RECORD_CONTRACT_ID,
            captured_at=captured_at,
        )
        prior = load_current_revision(
            self._field_binding,
            job.authority_id,
            current.review.target_application_id,
        )
        basis = _BindingCommitBasis(
            self,
            work_ref,
            job.authority_id,
            workspace_id,
            schema_keys,
            legacy_field_binding_basis_fingerprint(entries),
        )
        if current.has_prior_revision:
            result = commit_field_binding_for_current_application(
                self._field_binding,
                basis,
                workspace_instance_id=workspace_id,
                work_authority_id=job.authority_id,
                request_id=request_id,
                review=current.review,
                resolved_input=resolved,
                now=captured_at,
            )
        else:
            result = commit_field_binding_migration(
                self._field_binding,
                basis,
                workspace_instance_id=workspace_id,
                work_authority_id=job.authority_id,
                request_id=request_id,
                draft=draft,
                resolved_input=resolved,
                omitted_field_ids={
                    entry.template_field
                    for entry in entries
                    if entry.template_field not in active
                },
                now=captured_at,
            )
        revision_id = result.revision.field_binding_authority_revision
        return BindingCommitProjection(
            changed=prior is None
            or prior.field_binding_authority_revision != revision_id,
            revision_id=revision_id,
        )

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


__all__ = [
    "BindingCommitProjection",
    "BindingReviewProjection",
    "SealExecutionPlanService",
]


def _legacy_entries(mapping: MappingProfile) -> tuple[LegacyFieldBindingEntry, ...]:
    return tuple(
        LegacyFieldBindingEntry(
            item.template_field,
            item.type,
            item.source,
            item.const,
            item.fmt,
        )
        for item in mapping.mappings
    )


def _source_schema_keys(mapping: MappingProfile) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.source
            for item in mapping.mappings
            if item.type in {"text", "date", "amount"}
        )
    )


def _resolved_rules(
    draft: FieldBindingMigrationDraft,
    entries: tuple[LegacyFieldBindingEntry, ...],
    active: frozenset[str],
) -> tuple[FieldBindingRule, ...]:
    candidates = {item.field_id: item for item in draft.candidate_rules}
    rules: list[FieldBindingRule] = []
    for entry in entries:
        if entry.template_field not in active:
            continue
        candidate = candidates.get(entry.template_field)
        if candidate is None:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_MIGRATION_REVIEW_REQUIRED",
                f"legacy blank omission\uc5d0 \ub300\ud55c \uba85\uc2dc \uacb0\uc815\uc774 \ud544\uc694\ud569\ub2c8\ub2e4: {entry.template_field!r}",
            )
        rules.append(
            FieldBindingRule(
                field_id=candidate.field_id,
                binding_kind=candidate.binding_kind,
                document_content_value_policy=resolve_document_value_policy(
                    candidate.proposed_policy_id
                ),
                source_key=candidate.source_key,
                value_type=candidate.value_type,
                format_code=candidate.format_code,
                canonical_constant_value=candidate.canonical_constant_value,
            )
        )
    return tuple(rules)


@dataclass(frozen=True)
class _BindingCommitBasis:
    service: SealExecutionPlanService
    work_ref: str
    work_authority_id: str
    workspace_instance_id: str
    source_schema_keys: tuple[str, ...]
    legacy_fingerprint: str

    def _current_job(self) -> Job:
        job = load_job(self.service._registry, self.work_ref)
        if job.authority_id != self.work_authority_id or (
            legacy_field_binding_basis_fingerprint(_legacy_entries(job.mapping))
            != self.legacy_fingerprint
        ):
            raise StaleFieldBindingBasis(
                "legacy Mapping basis가 capture 이후 이동했습니다"
            )
        return job

    def current_legacy_migration_basis(
        self, work_authority_id: str
    ) -> LegacyMigrationBasis:
        self._current_job()
        aggregate = self.service._work_state.load(work_authority_id)
        return LegacyMigrationBasis(
            aggregate.work.current_template_application_id,
            self.legacy_fingerprint,
        )

    def current_application_field_structure(
        self, work_authority_id: str
    ) -> CurrentApplicationFieldStructure:
        self._current_job()
        structure = self.service._capture.current_application_field_structure(
            self.workspace_instance_id,
            work_authority_id,
            self.source_schema_keys,
        )
        if structure is None:
            raise StaleFieldBindingBasis(
                "current Application structure를 확인할 수 없습니다"
            )
        return structure
