"""SealExecutionPlan 의 production capture·fresh-observation seam 어댑터 (SX-SEAL · #719).

:mod:`hwpxfiller.external.seal_orchestration_runner` 와 `webapp/seal_execution_plan_product` 가
injectable seam 으로 남긴 두 port 의 실 store 결선이다:

- :meth:`read_summary` — current WorkTemplateApplication 요약(profile·application id)을 관찰한다.
- :meth:`capture_execution` — caller(Product)가 PerWorkFence 를 이미 쥔 상태에서 exact
  execution input 을 복원해 :func:`judge_captured_execution` 로 capture 판정을 낸다(R2-05b #740:
  ProfileFence·WorkFence 를 PerWorkFence 하나로 통합). fence 전제는 이 seam 을 주입받는 Product 의
  ``capture_under_fence`` 포트 타입이 나른다 — 구현 메서드 이름은 ``*_under_fence`` helper 계약
  (:mod:`tests.repo_contract.test_per_work_fence_gate`)과 분리한다(이 메서드는 fence-획득 public
  entry 가 아니라 Product 가 fence 아래 부르는 injectable 포트다).

**정상 capture 에서 금지하는 I/O**(port 계약 그대로): fence 재획득 · mutable HWPX source read ·
Job.template_path/template_override · latest Revision/Evidence 검색 · **HWPX parse/mutation** ·
Template Qualification 재실행 · Data Source reload. exact structure 는 PASS Evidence 의 durable
v2 projection 을 :func:`decode_execution_structure` 로 decode 할 뿐이고(원 HWPX 재parse 0, 선례
:func:`hwpxfiller.external.slot_command_runner` 의 chain fact 파생), applied bytes 는 Candidate
blob 을 **참조만** 한다.

capture 의 policy block 은 S3 :class:`QualificationProfileRevocation`
(``qualification_store.is_revoked``)을 읽는다 — profile revocation 은 current-work sealability 의
POLICY_BLOCKED 로 표현된다. **R2-05a(#740): mutable Profile admission store 축은 제거됐다** — runtime
admission 은 base kind·plan schema/encoding runtime support·materializer conformance capability 만
본다(별도 admission store read 없음).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hwpxfiller.application.execution_capture import (
    QUALIFICATION_PROFILE_REVOKED,
    CapturedExecutionPolicyBlock,
    CapturedFieldBinding,
    CapturedSelection,
    CaptureExecutionQualificationResult,
    CapturedTemplateExecutionInput,
    DomainBlockedFieldBinding,
    DomainBlockedSelection,
    ExecutionCaptureContextError,
    ExecutionCaptureIntegrityError,
    ExactTemplateQualificationContext,
    QualificationProfileSemanticPayload,
    ResolvedSealPolicy,
    judge_captured_execution,
)
from hwpxfiller.application.execution_compilation import project_active_fields
from hwpxfiller.application.execution_structure import (
    ExecutionStructureError,
    decode_execution_structure,
    template_structure_digest,
)
from hwpxfiller.application.field_binding_input import (
    CurrentApplicationFieldStructure,
    FieldBindingApplicationReview,
    FieldBindingInputIntegrityError,
    FieldBindingRevision,
    FieldReviewClassification,
    NEEDS_FIELD_BINDING_APPLICATION_REVIEW,
    NEW_ACTIVE_FIELD,
    build_field_binding_input,
    review_basis_digest,
    review_field_binding_for_current_application,
)
from hwpxfiller.application.qualification_evidence import content_digest
from hwpxfiller.application.seal_execution_plan import WorkExecutionSummary
from hwpxfiller.application.slot_configuration_context import (
    SlotConfigurationContext,
    SlotConfigurationContextError,
    resolve_exact_applied_template_input,
    resolve_slot_configuration_context,
)
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotSelectionCaptureError,
    plan_capture,
)
from hwpxfiller.application.work_slot_configuration import WorkSlotConfigurationDraft
from hwpxfiller.host.per_work_fence import per_work_mutation_fence

from .candidate_store import CandidateObjectStore, CandidateStoreError
from .field_binding_store import WorkFieldBindingStore, load_current_revision
from .qualification_store import QualificationObjectStore, QualificationStoreError
from .work_configuration_store import (
    ConfigurationAggregateNotFound,
    WorkSlotConfigurationStore,
)
from .work_template_store import (
    AtomicWorkTemplateStateStore,
    WorkAggregateNotFound,
    WorkTemplateStateAggregate,
    WorkTemplateStoreError,
)

# ─── composition profile state ────────────────────────────────────────────────────
# ``composition_profile_state`` 는 QualificationEvidence·Manifest 어디에도 persisted 필드가
# 없다(조회지 판정 신설 금지 — S5 는 이 값을 이 지점 이후로 재판정하지 않는다). exact v2 projection
# 을 decode 해 seal 가능한 composition-ready profile 을 복원했다는 사실을 나르는 정적 provenance
# 값이다. execution_basis_digest(currentness 판정)에는 들어가지 않고 request-specific evidence
# projection 에만 실린다.
COMPOSITION_PROFILE_SEALED = "SEALED"

# code 없는 store/integrity 실패의 generic capture context error code.
_GENERIC_CAPTURE_CONTEXT_ERROR = "EXECUTION_CAPTURE_CONTEXT_ERROR"

_CONTEXT_ERROR_TYPES = (
    SlotConfigurationContextError,
    ExecutionStructureError,
    QualificationStoreError,
    CandidateStoreError,
    WorkTemplateStoreError,
    ExecutionCaptureIntegrityError,
    FieldBindingInputIntegrityError,
)



@dataclass(frozen=True)
class CurrentFieldBindingReview:
    """Exact current Active Field set plus the canonical Binding review."""

    active_field_ids: tuple[str, ...]
    review: FieldBindingApplicationReview

class _WorkStateReadAdapter:
    """AtomicWorkTemplateStateStore → WorkTemplateStateReadPort(부재를 None 으로 번역).

    context resolver 는 ``load()->None`` 을 TEMPLATE_INITIALIZATION_REQUIRED 로 바꾼다 — store 의
    WorkAggregateNotFound raise 를 그 경계에 맞춘다(slot_configuration_product 와 동형).
    """

    def __init__(self, store: AtomicWorkTemplateStateStore) -> None:
        self._store = store

    def load(self, work_id: str) -> "WorkTemplateStateAggregate | None":
        try:
            return self._store.load(work_id)
        except WorkAggregateNotFound:
            return None


class SealExecutionCaptureRunner:
    """seal capture/summary seam 의 실 store 결선 — headless, fence 는 caller 가 쥔다."""

    def __init__(
        self,
        *,
        work_state_store: AtomicWorkTemplateStateStore,
        qualification_store: QualificationObjectStore,
        candidate_store: CandidateObjectStore,
        slot_config_store: WorkSlotConfigurationStore,
        field_binding_store: WorkFieldBindingStore,
        clock: Callable[[], str],
    ) -> None:
        self._work_state = work_state_store
        self._work_read = _WorkStateReadAdapter(work_state_store)
        self._qualification = qualification_store
        self._candidate = candidate_store
        self._slot_config = slot_config_store
        self._field_binding = field_binding_store
        self._clock = clock

    # ── fresh observation summary(fence 유무는 caller 가 안다) ──────────────────────
    def read_summary(
        self, workspace_instance_id: str, work_authority_id: str
    ) -> WorkExecutionSummary:
        """current WorkTemplateApplication 의 (profile, application) identity 요약.

        state 부재(bootstrap 전)는 ``WorkAggregateNotFound`` 로 raise 한다 — implicit default 로
        넘어가지 않는다(Port 계약). exact bytes/selection/binding 은 담지 않는다.
        """
        aggregate = self._work_state.load(work_authority_id)
        current_id = aggregate.work.current_template_application_id
        application = next(
            (a for a in aggregate.applications if a.application_id == current_id), None
        )
        if application is None:
            raise WorkTemplateStoreError(
                f"current application {current_id!r} 이 applications 에 없다"
            )
        evidence = self._qualification.get_evidence(application.pass_evidence_id)
        return WorkExecutionSummary(
            qualification_profile_id=evidence.qualification_profile_id,
            template_application_id=current_id,
        )


    def read_current_field_binding_review(
        self, workspace_instance_id: str, work_authority_id: str
    ) -> CurrentFieldBindingReview | None:
        """Project current Active Fields with the existing Binding review semantics."""
        with per_work_mutation_fence(workspace_instance_id, work_authority_id):
            aggregate = self._work_state.load(work_authority_id)
            application_id = aggregate.work.current_template_application_id
            now = self._clock()
            template, context = self._capture_template(
                workspace_instance_id,
                work_authority_id,
                application_id,
                now,
            )
            selection_observation = self._capture_selection(context, now)
            if not isinstance(selection_observation, CapturedSelection):
                return None

            selection = selection_observation.selection
            selected: frozenset[tuple[str, str]] = frozenset()
            if isinstance(selection, SlotConfigurationSnapshot):
                selected = frozenset(
                    (item.slot_id, option_id)
                    for item in selection.effective_selections.selections
                    for option_id in item.selected_option_ids
                )
            structure = template.qualification.execution_structure
            active, _counts = project_active_fields(structure, selected)
            active_ids = active.active_logical_field_order
            active_set = set(active_ids)
            all_fields = tuple(
                dict.fromkeys(
                    occurrence.field_id for occurrence in structure.field_occurrences
                )
            )
            old_revision = self._nearest_binding_revision(aggregate, application_id)
            current_structure = CurrentApplicationFieldStructure(
                application_id=application_id,
                active_field_ids=active_ids,
                inactive_field_ids=tuple(
                    field_id for field_id in all_fields if field_id not in active_set
                ),
                source_schema_keys=(
                    old_revision.source_schema_keys if old_revision is not None else ()
                ),
            )
            if old_revision is not None:
                review = review_field_binding_for_current_application(
                    old_revision, current_structure
                )
            else:
                review = FieldBindingApplicationReview(
                    work_authority_id=work_authority_id,
                    target_application_id=application_id,
                    review_basis_digest=review_basis_digest(current_structure),
                    classifications=tuple(
                        FieldReviewClassification(field_id, NEW_ACTIVE_FIELD)
                        for field_id in active_ids
                    ),
                )
            return CurrentFieldBindingReview(active_ids, review)

    def _nearest_binding_revision(
        self, aggregate: WorkTemplateStateAggregate, application_id: str
    ) -> FieldBindingRevision | None:
        applications = {item.application_id: item for item in aggregate.applications}
        current_id: str | None = application_id
        while current_id is not None:
            revision = load_current_revision(
                self._field_binding, aggregate.work.work_id, current_id
            )
            if revision is not None:
                return revision
            current_id = applications[current_id].previous_application_id
        return None
    # ── under-fence exact capture(Product 가 PerWorkFence 아래 부르는 injectable 포트) ─────
    def capture_execution(
        self,
        workspace_instance_id: str,
        work_authority_id: str,
        expected_template_application_id: str,
        expected_profile_id: str,
        resolved_seal_policy: ResolvedSealPolicy,
    ) -> CaptureExecutionQualificationResult:
        """복원된 exact (template, selection, binding, policy) 로 capture 판정을 낸다.

        precedence 는 :func:`judge_captured_execution` 와 결이 같다: profile revocation → context
        error → domain block → complete. revocation 은 profile id 만 필요하므로 exact context 복원
        전에 먼저 확인해(broken chain 이 revocation 을 가리지 못하게) policy block 을 낸다.
        """
        now = self._clock()

        # 1·2. profile revocation(S3) precedence + exact context 복원(v2 decode, 원 HWPX 재parse 0)
        # + selection/binding 관찰. revocation 은 record(get_revocation)로 단일 read 한다.
        try:
            revocation = self._qualification.get_revocation(expected_profile_id)
            if revocation is not None:  # precedence 상 앞 — chain 복원 전에 policy block.
                return self._policy_block(revocation, now)
            template, context = self._capture_template(
                workspace_instance_id, work_authority_id,
                expected_template_application_id, now,
            )
            selection_observation = self._capture_selection(context, now)
            field_binding_observation = self._capture_field_binding(
                workspace_instance_id, work_authority_id,
                context.template_application_id, now,
            )
        except _CONTEXT_ERROR_TYPES as exc:
            return ExecutionCaptureContextError(_context_error_code(exc), str(exc))

        # 3. pure capture 판정(policy block 은 위에서 이미 처리 → None).
        return judge_captured_execution(
            workspace_instance_id=workspace_instance_id,
            work_authority_id=work_authority_id,
            expected_template_application_id=expected_template_application_id,
            expected_profile_id=expected_profile_id,
            resolved_seal_policy=resolved_seal_policy,
            template=template,
            selection_observation=selection_observation,
            field_binding_observation=field_binding_observation,
            captured_at=now,
            policy_block=None,
        )

    # ── helpers ───────────────────────────────────────────────────────────────────
    def _policy_block(self, revocation, now: str) -> CapturedExecutionPolicyBlock:
        digest = content_digest(
            {
                "qualification_profile_id": revocation.qualification_profile_id,
                "reason": revocation.reason,
                "authority": revocation.authority,
                "revoked_at": revocation.revoked_at,
            }
        )
        return CapturedExecutionPolicyBlock(
            policy_code=QUALIFICATION_PROFILE_REVOKED,
            observed_at=now,
            qualification_profile_id=revocation.qualification_profile_id,
            observed_policy_version=None,
            policy_observation_digest=digest,
        )

    def _capture_template(
        self,
        workspace_instance_id: str,
        work_authority_id: str,
        expected_template_application_id: str,
        now: str,
    ) -> "tuple[CapturedTemplateExecutionInput, SlotConfigurationContext]":
        applied = resolve_exact_applied_template_input(
            self._work_read, self._qualification, self._candidate,
            work_authority_id, expected_template_application_id,
        )
        context = resolve_slot_configuration_context(
            self._work_read, self._qualification, self._candidate,
            workspace_instance_id, work_authority_id, expected_template_application_id,
        )
        evidence = self._qualification.get_evidence(context.pass_evidence_id)
        projection = evidence.structure_projection
        if projection is None:  # pragma: no cover - chain resolve 가 PASS+projection 을 보장
            raise ExecutionCaptureIntegrityError("PASS Evidence 에 structure projection 부재")
        # exact v2 execution structure — 원 HWPX 를 재parse 하지 않고 durable projection 을 decode.
        execution_structure = decode_execution_structure(projection.payload)
        manifest = self._qualification.get_manifest(context.qualification_profile_id)
        semantic_payload = QualificationProfileSemanticPayload(
            qualification_profile_id=manifest.qualification_profile_id,
            media=manifest.media,
            adapter_contract_version=manifest.adapter_contract_version,
            product_rule_version=manifest.product_rule_version,
            operation_alphabet_version=manifest.operation_alphabet_version,
            projection_schema_version=manifest.projection_schema_version,
            manifest_payload=manifest.manifest_payload,
        )
        qualification_context = ExactTemplateQualificationContext(
            pass_evidence_id=context.pass_evidence_id,
            qualification_profile_id=context.qualification_profile_id,
            qualification_profile_semantic_payload=semantic_payload,
            structure_projection_schema_version=context.structure_projection_schema_version,
            template_structure_digest=template_structure_digest(execution_structure),
            execution_structure=execution_structure,
            composition_profile_state=COMPOSITION_PROFILE_SEALED,
            revision_id=applied.revision_id,
        )
        template = CapturedTemplateExecutionInput(
            workspace_instance_id=workspace_instance_id,
            work_authority_id=work_authority_id,
            applied=applied,
            qualification=qualification_context,
            captured_at=now,
        )
        return template, context

    def _capture_selection(self, context: SlotConfigurationContext, now: str):
        config = self._load_config_draft(context.work_id, context.template_application_id)
        try:
            selection = plan_capture(context, config, now)
        except SlotSelectionCaptureError as exc:
            # presence=None 이라 plan_capture 는 SLOT_CONFIGURATION_INCOMPLETE 만 낸다(STALE 는
            # expected presence 가 있어야 발생). 사용자가 구성을 완성하면 풀리는 domain block 이다.
            return DomainBlockedSelection(exc.code, str(exc))
        return CapturedSelection(selection)

    def _load_config_draft(
        self, work_id: str, application_id: str
    ) -> "WorkSlotConfigurationDraft | None":
        try:
            stored = self._slot_config.load(work_id)
        except ConfigurationAggregateNotFound:
            return None
        for cfg in stored.configurations.configurations:
            if cfg.base_template_application_id == application_id:
                return cfg
        return None

    def _capture_field_binding(
        self, workspace_instance_id: str, work_authority_id: str,
        application_id: str, now: str,
    ):
        revision = load_current_revision(
            self._field_binding, work_authority_id, application_id
        )
        if revision is None:
            return DomainBlockedFieldBinding(
                NEEDS_FIELD_BINDING_APPLICATION_REVIEW,
                "current Application 에 field binding revision 이 없다",
            )
        field_binding = build_field_binding_input(
            workspace_instance_id=workspace_instance_id,
            work_authority_id=revision.work_authority_id,
            base_template_application_id=revision.base_template_application_id,
            binding_rules=revision.binding_rules,
            source_schema_keys=revision.source_schema_keys,
            raw_record_contract_id=revision.raw_record_contract_id,
            captured_at=now,
        )
        return CapturedFieldBinding(field_binding)


def _context_error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return _GENERIC_CAPTURE_CONTEXT_ERROR


__all__ = [
    "COMPOSITION_PROFILE_SEALED",
    "CurrentFieldBindingReview",
    "SealExecutionCaptureRunner",
]
