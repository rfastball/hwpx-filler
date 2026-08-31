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

U3-04(#877): 그 commit 의 의미는 **활성 Field upsert + 기존 판본의 비활성 Field 규칙 보존** 이다
(활성 Field 로 잘라 교체하지 않는다). 확정 이후 Option 을 바꿔 비활성이 됐다는 사실만으로 규칙을
버리면 그 Option 으로 되돌아올 때마다 같은 결정을 다시 확정하게 된다 — 옵션 왕복이 재확정을
무한히 요구하던 결함의 자리가 여기였다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..application.document_creation_workbench import InputRequirement
from ..application.field_binding_input import (
    AMBIGUOUS_BLANK_OMISSION,
    RUNTIME_TODAY_UNSUPPORTED,
    CurrentApplicationFieldStructure,
    FieldBindingMigrationDraft,
    FieldBindingReviewRequired,
    LegacyFieldBindingEntry,
    MigrationCandidateRule,
    StaleFieldBindingBasis,
    build_field_binding_input,
    legacy_field_binding_basis_fingerprint,
    prepare_legacy_field_binding_migration,
)
from ..application.jobs import (
    JobStorePort,
    ensure_job_authority_id,
    load_job,
)
from ..application.execution_composition import RuntimeMaterializerConformanceRegistry
from ..application.seal_execution_plan import (
    RouteResolutionError,
    SealExecutionPlanCommand,
)
from ..application.shipping_seal_policy import resolve_shipping_policy
from ..domain.field_binding import (
    FieldBindingRule,
    resolve_document_value_policy,
    txt_document_value_policy,
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
from ..external.runtime_capability import (
    admitted_runtime_conformance_registry,
    admitted_txt_runtime_conformance,
)
from ..external.seal_orchestration_runner import observe_current_basis_digest
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
            return observe_current_basis_digest(
                command,
                work_id,
                read_summary=self._capture.read_summary,
                capture_under_fence=self._capture.capture_execution,
                resolve_shipping_policy=resolve_shipping_policy,
            )

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
        return self._commit_mapping_binding(work_ref, request_id, media="hwpx")

    def commit_txt_mapping(
        self, work_ref: str, request_id: str
    ) -> BindingCommitProjection | None:
        """TXT Work 의 현재 Mapping 을 S5 Field Binding 판본으로 확정한다(S10-04 · #861).

        :meth:`commit_current_mapping` 과 **같은 몸통**이다 — 검토 축(현재 Active Field 전건에
        Mapping 결정이 있는가)도, 판본 규율(migration 1회 → 이후 current-application commit)도
        같다. 갈리는 것은 값 정책의 escaping 책임 하나뿐이고 그 번역은
        :func:`~hwpxfiller.domain.field_binding.txt_document_value_policy` 가 진다.

        메서드를 가른 이유는 media 가드가 **검토 축의 사실**이라서다: hwpx 진입점은 편집기
        저장 사건에 결속돼 있고 TXT 진입점은 작업대 복사 직전의 내부 pin 이다. 한 메서드가 두
        진입 문맥을 겸하면 어느 쪽이 이 판본을 만들었는지 사후에 말할 수 없다.
        """
        return self._commit_mapping_binding(work_ref, request_id, media="txt")

    def _commit_mapping_binding(
        self, work_ref: str, request_id: str, *, media: str
    ) -> BindingCommitProjection | None:
        job = load_job(self._registry, work_ref)
        if job.media != media or not job.authority_id:
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
        # 미매핑 검사는 **활성 Field 기준**이다(#877 재확인): 비활성 Field 는 이번 실행에 참여하지
        # 않으므로 Mapping 결정이 없어도 확정을 막지 않는다. 그 Field 가 다시 활성이 되는 순간
        # review 가 NEW_ACTIVE_FIELD 로 세워 그때 묻는다.
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
        # 판본 스코프 = 활성 Field upsert + 이미 확정된 비활성 Field 규칙 보존(#877). 판본이 없는
        # 최초 migration 이면 보존할 규칙도 없다(빈 tuple).
        binding_rules = _resolved_rules(
            draft, entries, active, media=media
        ) + _preserved_inactive_rules(draft, current, media=media)
        resolved = build_field_binding_input(
            workspace_instance_id=workspace_id,
            work_authority_id=job.authority_id,
            base_template_application_id=current.review.target_application_id,
            binding_rules=binding_rules,
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
                # 최초 판본에는 보존할 이전 규칙이 없다 — 활성 아닌 legacy entry 는 여기서
                # **명시 omission** 으로 회계된다(silent drop 금지). upsert 의미와 충돌하지
                # 않는다: 그 Field 가 활성이 되면 review 가 NEW_ACTIVE_FIELD 로 세워 확정을
                # 받고, 그 뒤로는 비활성이 되어도 판본이 규칙을 보존한다(#877).
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
        # 발급 형태·결속은 단일 helper(S6-05 · #812) — lazy 발급은 의미 1·2 의 성질.
        work_id = job.authority_id or ensure_job_authority_id(self._registry, work_ref)
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


def _rule_from_candidate(
    candidate: MigrationCandidateRule, *, media: str
) -> FieldBindingRule:
    """migration 후보 규칙 → exact FieldBindingRule(활성 upsert·보존 갱신 공용).

    값 정책은 매체가 가른다(S10-04 · #861): 같은 whitespace/line-break 의미를 갖되 escaping
    책임이 다르다. 사용자에게 다시 묻지 않고 표로 옮긴다 — 이미 확정한 값 의미를 매체가
    바뀌었다고 재확인시키는 것은 같은 결정을 두 번 시키는 것이다.
    """
    resolve_policy = (
        txt_document_value_policy if media == "txt" else resolve_document_value_policy
    )
    return FieldBindingRule(
        field_id=candidate.field_id,
        binding_kind=candidate.binding_kind,
        document_content_value_policy=resolve_policy(candidate.proposed_policy_id),
        source_key=candidate.source_key,
        format_code=candidate.format_code,
        canonical_constant_value=candidate.canonical_constant_value,
    )


def _preserved_inactive_rules(
    draft: FieldBindingMigrationDraft,
    current: CurrentFieldBindingReview,
    *,
    media: str,
) -> tuple[FieldBindingRule, ...]:
    """이미 확정된 Field 가 비활성이 되어도 판본에서 사라지지 않게 규칙을 이어 나른다(#877).

    **스코프는 판본, 값은 Mapping** 이다: 어떤 Field 가 판본에 드는지는 「한 번이라도 확정됐는가」
    (review 의 INACTIVE_ONLY 분류)가 정하고, 그 Field 의 값 결정은 그것이 아직 Mapping 에 살아
    있으면 **현재 Mapping** 이 정한다. 이전 규칙을 무조건 그대로 박으면 편집기가 보여주는 값과
    판본이 조용히 갈라진다 — 같은 상태를 두 곳이 판정하지 않게 Mapping 을 우선한다. Mapping 에서
    사라졌거나 명시 결정이 남은 blank 항목은 이전 규칙을 그대로 보존한다(비활성이라 실행에 참여
    하지 않고, 다시 활성이 되면 그때 review·commit 이 명시 결정을 요구한다).

    BROKEN(템플릿에서 사라진 Field)은 보존 대상이 아니다 — review 분류가 이미 갈라 두었고,
    존재하지 않는 Field 규칙을 실은 판본은 commit 결정이 거절한다.
    """
    prior = current.prior_revision
    if prior is None:
        return ()
    keep = frozenset(current.review.inactive_only_field_ids())
    candidates = {item.field_id: item for item in draft.candidate_rules}
    preserved: list[FieldBindingRule] = []
    for rule in prior.binding_rules:
        if rule.field_id not in keep:
            continue
        candidate = candidates.get(rule.field_id)
        preserved.append(
            rule if candidate is None else _rule_from_candidate(candidate, media=media)
        )
    return tuple(preserved)


# migration blocker 사유 → 사람이 읽는 문장. 코드는 링1/application 어휘이고 문안은 여기
# 한 곳에서만 조립한다(같은 사유를 두 자리가 다른 말로 하지 않게).
_MIGRATION_BLOCKER_TEXT = {
    AMBIGUOUS_BLANK_OMISSION: "legacy blank omission에 대한 명시 결정이 필요합니다",
    RUNTIME_TODAY_UNSUPPORTED: (
        "'오늘 날짜' 유형은 Field Binding 판본으로 아직 옮길 수 없습니다. "
        "이 누름틀을 데이터 항목이나 고정값으로 바꾸고 다시 저장하세요"
    ),
}
_MIGRATION_BLOCKER_FALLBACK_TEXT = (
    "legacy Mapping을 Field Binding 규칙으로 옮길 수 없습니다"
)


def _resolved_rules(
    draft: FieldBindingMigrationDraft,
    entries: tuple[LegacyFieldBindingEntry, ...],
    active: frozenset[str],
    *,
    media: str = "hwpx",
) -> tuple[FieldBindingRule, ...]:
    """현재 활성 Field 의 규칙 — 현재 Mapping 결정을 그대로 upsert 한다."""
    candidates = {item.field_id: item for item in draft.candidate_rules}
    # 후보가 없는 Field 는 draft 가 **왜** 못 지었는지를 blocker 로 이미 말했다 — 그
    # 사유를 그대로 재진술한다. 종전에는 사유를 묻지 않고 언제나 'blank omission' 으로
    # 적어, 다른 원인(「오늘 날짜」 유형)까지 엉뚜한 이름으로 보고했다.
    reasons = {item.field_id: item.reason for item in draft.blockers}
    rules: list[FieldBindingRule] = []
    for entry in entries:
        if entry.template_field not in active:
            continue
        candidate = candidates.get(entry.template_field)
        if candidate is None:
            raise FieldBindingReviewRequired(
                "FIELD_BINDING_MIGRATION_REVIEW_REQUIRED",
                _MIGRATION_BLOCKER_TEXT.get(
                    reasons.get(entry.template_field, ""),
                    _MIGRATION_BLOCKER_FALLBACK_TEXT,
                )
                + f": {entry.template_field!r}",
            )
        rules.append(_rule_from_candidate(candidate, media=media))
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
