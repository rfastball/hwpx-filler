"""SX-SEAL(#719) production capture/summary seam — 실 store 백엔드 강제.

test_seal_orchestration_runner 의 fake World/Resolver 가 커버하던 capture 계약을 production
:class:`SealExecutionCaptureRunner` 로 강제한다. bootstrap_work 는 v1 product projection 만 내므로
(decode_execution_structure 불가) 실 store 에 **v2 execution PASS Evidence** 를 직접 seed 한다
(test_slot_command._v2_exec 선례). complete capture 는 fake World 가 publish 하던 것과 같은 조각
(_structure·_snapshot·_binding)을 실 store 에서 복원해 compile_candidate 까지 PlanCandidate 로 간다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.candidate_revision import (
    ContentBlob,
    SourceCaptureObservation,
    TemplateRevision,
    blob_digest,
)
from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    QUALIFICATION_PROFILE_REVOKED,
    CapturedExecutionDomainBlock,
    CapturedExecutionInput,
    CapturedExecutionPolicyBlock,
    ExecutionCaptureContextError,
)
from hwpxfiller.application.execution_compilation import SLOT_CONFIGURATION_INCOMPLETE
from hwpxfiller.application.execution_structure import (
    build_execution_manifest,
    execution_pass_projection,
)
from hwpxfiller.application.field_binding_input import (
    NEEDS_FIELD_BINDING_APPLICATION_REVIEW,
    FieldBindingRevision,
    build_field_binding_input,
)
from hwpxfiller.application.qualification_evidence import (
    QualificationAttempt,
    QualificationEvidence,
    QualificationProfileRevocation,
)
from hwpxfiller.application.seal_execution_plan import (
    PlanCandidate,
    SealExecutionPlanCommand,
    WorkExecutionSummary,
    compile_candidate,
)
from hwpxfiller.application.shipping_seal_policy import resolve_shipping_policy
from hwpxfiller.application.stored_field_binding import (
    STORE_SCHEMA_VERSION as FB_SCHEMA,
    ApplicationRevisionPointer,
    StoredWorkFieldBinding,
)
from hwpxfiller.application.stored_work_configuration import (
    STORE_SCHEMA_VERSION as CFG_STORE_SCHEMA,
    StoredWorkConfiguration,
)
from hwpxfiller.application.work_slot_configuration import (
    EMPTY,
    SCHEMA_VERSION as CFG_AGG_SCHEMA,
    WorkSlotConfigurationAggregate,
    WorkSlotConfigurationDraft,
)
from hwpxfiller.application.work_template_state import (
    INITIALIZATION,
    SCHEMA_VERSION as WORK_SCHEMA,
    DocumentWork,
    WorkTemplateApplication,
    WorkTemplateStateAggregate,
)
from hwpxfiller.domain.slot_selection import SlotSelection, SlotSelectionSet
from hwpxfiller.external.candidate_store import CandidateObjectStore
from hwpxfiller.external.qualification_store import QualificationObjectStore
from hwpxfiller.external.field_binding_store import WorkFieldBindingStore
from hwpxfiller.external.seal_execution_capture_runner import SealExecutionCaptureRunner
from hwpxfiller.external.work_configuration_store import WorkSlotConfigurationStore
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore

from tests.test_execution_compilation import (
    APP,
    AT,
    MEDIA,
    PROFILE,
    WORK,
    WS,
    _rules,
    _structure,
)

LINEAGE = "lin-1"
EVIDENCE_ID = "ev-1"
REVISION_ID = "rev-1"
OBSERVATION_ID = "obs-1"
BLOB_BYTES = b"exact-template-bytes"
CONTRACT = "slot-selection/v1"


# ─── 실 store seed ────────────────────────────────────────────────────────────────────
def _seed_v2_work(
    root, *, with_binding: bool = True, with_config: bool = True, revoked: bool = False
) -> None:
    works = AtomicWorkTemplateStateStore(root / "works")
    qual = QualificationObjectStore(root / "qualification")
    cand = CandidateObjectStore(root / "candidates")
    configs = WorkSlotConfigurationStore(root / "slot_configs")
    bindings = WorkFieldBindingStore(root / "field_bindings")

    # candidate: blob → observation → revision(참조 무결성).
    digest = blob_digest(BLOB_BYTES)
    cand.put_blob(
        ContentBlob(digest=digest, media=MEDIA, exact_bytes=BLOB_BYTES, byte_length=len(BLOB_BYTES))
    )
    cand.put_observation(
        SourceCaptureObservation(
            observation_id=OBSERVATION_ID, preparation_id="prep-1", source_binding_id="sb-1",
            source_binding_generation=1, capture_method="zip", observed_metadata={},
            captured_content_digest=digest, captured_at=AT,
        )
    )
    cand.put_revision(
        TemplateRevision(
            revision_id=REVISION_ID, template_lineage_id=LINEAGE, media=MEDIA,
            exact_content_digest=digest, origin_capture_observation_id=OBSERVATION_ID,
            created_at=AT,
        )
    )

    # qualification: v2 manifest + v2 execution PASS Evidence(+ optional revocation).
    qual.put_manifest(
        build_execution_manifest(
            media=MEDIA, adapter_contract_version="a/1", product_rule_version="p/1",
            operation_alphabet_version="o/1", created_at=AT,
        )
    )
    qual.put_attempt(
        QualificationAttempt(
            attempt_id="at-1", preparation_id="prep-1", revision_id=REVISION_ID,
            qualification_profile_id=PROFILE, outcome="PASS", evidence_id=EVIDENCE_ID,
            error_code=None, started_at=AT, completed_at=AT,
        )
    )
    qual.put_evidence(
        QualificationEvidence(
            evidence_id=EVIDENCE_ID, attempt_id="at-1", revision_id=REVISION_ID,
            qualification_profile_id=PROFILE, result="PASS",
            structure_projection=execution_pass_projection(_structure()),
            diagnostics=(), engine_metadata={}, qualified_at=AT,
        )
    )
    if revoked:
        qual.put_revocation(
            QualificationProfileRevocation(
                qualification_profile_id=PROFILE, reason="policy", authority="admin",
                revoked_at=AT,
            )
        )

    # work aggregate: current Application 이 그 PASS Evidence 를 가리킨다.
    works.create(
        WorkTemplateStateAggregate(
            schema_version=WORK_SCHEMA, aggregate_version=1,
            work=DocumentWork(
                work_id=WORK, template_lineage_id=LINEAGE,
                current_template_application_id=APP,
                current_template_preparation_id=None, prepare_seq=0,
            ),
            applications=(
                WorkTemplateApplication(
                    application_id=APP, work_id=WORK, application_epoch=1,
                    pass_evidence_id=EVIDENCE_ID, previous_application_id=None,
                    origin=INITIALIZATION, prepared_change_id=None, actor="t", applied_at=AT,
                ),
            ),
            preparations=(), prepared_changes=(), apply_provenance=(), outbox_events=(),
        )
    )

    if with_config:
        draft = WorkSlotConfigurationDraft(
            work_id=WORK, base_template_application_id=APP, version=1,
            selections=SlotSelectionSet((SlotSelection("s1", ("o1",)),)),
            origin=EMPTY, reconciled_from_application_id=None, reconciled_from_version=None,
            reconciled_from_declared_selection_digest=None, created_at=AT, updated_at=AT,
        )
        configs.create(
            StoredWorkConfiguration(
                schema_version=CFG_STORE_SCHEMA, aggregate_version=1, workspace_instance_id=WS,
                configurations=WorkSlotConfigurationAggregate(
                    schema_version=CFG_AGG_SCHEMA, work_id=WORK, configurations=(draft,)
                ),
                processed_requests=(),
            )
        )

    if with_binding:
        binding_input = build_field_binding_input(
            workspace_instance_id=WS, work_authority_id=WORK, base_template_application_id=APP,
            binding_rules=_rules(), source_schema_keys=("이름", "금액열", "unused"),
            raw_record_contract_id="rr/1", captured_at=AT,
        )
        revision = FieldBindingRevision(
            work_authority_id=binding_input.work_authority_id,
            base_template_application_id=binding_input.base_template_application_id,
            field_binding_authority_revision=binding_input.field_binding_authority_revision,
            field_binding_semantic_contract_id=binding_input.field_binding_semantic_contract_id,
            source_schema_contract_id=binding_input.source_schema_contract_id,
            raw_record_contract_id=binding_input.raw_record_contract_id,
            binding_rules=binding_input.binding_rules,
            source_schema_keys=binding_input.source_schema_keys,
            canonical_binding_digest=binding_input.canonical_binding_digest,
            canonical_source_schema_digest=binding_input.canonical_source_schema_digest,
            captured_at=binding_input.captured_at,
        )
        bindings.create(
            StoredWorkFieldBinding(
                schema_version=FB_SCHEMA, aggregate_version=1, workspace_instance_id=WS,
                work_authority_id=WORK,
                current_by_application=(
                    ApplicationRevisionPointer(APP, revision.field_binding_authority_revision),
                ),
                immutable_binding_revisions=(revision,), migration_drafts=(),
                application_review_drafts=(), first_seen_command_ledger=(),
            )
        )


def _runner(root) -> SealExecutionCaptureRunner:
    return SealExecutionCaptureRunner(
        work_state_store=AtomicWorkTemplateStateStore(root / "works"),
        qualification_store=QualificationObjectStore(root / "qualification"),
        candidate_store=CandidateObjectStore(root / "candidates"),
        slot_config_store=WorkSlotConfigurationStore(root / "slot_configs"),
        field_binding_store=WorkFieldBindingStore(root / "field_bindings"),
        clock=lambda: AT,
    )


def _policy():
    command = SealExecutionPlanCommand(
        workspace_instance_id=WS, work_ref="job-ref", request_id="r1",
        requested_execution_base_kind=APPLIED_TEMPLATE_CANDIDATE,
    )
    return resolve_shipping_policy(command, WorkExecutionSummary(PROFILE, APP))


def _capture(root, app=APP, profile=PROFILE):
    return _runner(root).capture_execution(WS, WORK, app, profile, _policy())


# ─── read_summary ──────────────────────────────────────────────────────────────────────
def test_read_summary_returns_current_profile_and_application(tmp_path) -> None:
    _seed_v2_work(tmp_path)
    summary = _runner(tmp_path).read_summary(WS, WORK)
    assert summary == WorkExecutionSummary(PROFILE, APP)


def test_read_summary_absent_work_raises(tmp_path) -> None:
    from hwpxfiller.external.work_template_store import WorkAggregateNotFound

    with pytest.raises(WorkAggregateNotFound):
        _runner(tmp_path).read_summary(WS, WORK)


# ─── complete capture → publishable ─────────────────────────────────────────────────────
def test_complete_capture_publishes_end_to_end(tmp_path) -> None:
    _seed_v2_work(tmp_path)
    policy = _policy()
    captured = _runner(tmp_path).capture_execution(WS, WORK, APP, PROFILE, policy)
    assert isinstance(captured, CapturedExecutionInput)
    # policy echo(fail-closed 게이트가 대조하는 값) + cross-ref identity.
    assert captured.resolved_seal_policy == policy
    assert captured.workspace_instance_id == WS
    assert captured.work_authority_id == WORK
    assert captured.template.applied.template_application_id == APP
    assert captured.template.qualification.qualification_profile_id == PROFILE
    assert captured.captured_execution_input_digest  # nonempty
    # capture 가 fake World 가 publish 하던 것과 같은 basis 로 compile → PlanCandidate.
    candidate = compile_candidate(captured)
    assert isinstance(candidate, PlanCandidate)


# ─── domain block: binding 부재 ─────────────────────────────────────────────────────────
def test_missing_field_binding_is_domain_block(tmp_path) -> None:
    _seed_v2_work(tmp_path, with_binding=False)
    result = _capture(tmp_path)
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert NEEDS_FIELD_BINDING_APPLICATION_REVIEW in result.normalized_blockers


# ─── domain block: slot config 부재(불완전 선택) ────────────────────────────────────────
def test_missing_slot_configuration_is_domain_block(tmp_path) -> None:
    _seed_v2_work(tmp_path, with_config=False)
    result = _capture(tmp_path)
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert SLOT_CONFIGURATION_INCOMPLETE in result.normalized_blockers


# ─── policy block: revocation ────────────────────────────────────────────────────────────
def test_revoked_profile_is_policy_block(tmp_path) -> None:
    _seed_v2_work(tmp_path, revoked=True)
    result = _capture(tmp_path)
    assert isinstance(result, CapturedExecutionPolicyBlock)
    assert result.policy_code == QUALIFICATION_PROFILE_REVOKED
    assert result.qualification_profile_id == PROFILE
    assert result.policy_observation_digest  # revocation record 로부터 채운다


# ─── context error: stale application(current 아님) ─────────────────────────────────────
def test_stale_application_is_context_error(tmp_path) -> None:
    _seed_v2_work(tmp_path)
    result = _capture(tmp_path, app="other-app")
    assert isinstance(result, ExecutionCaptureContextError)


# ─── context error: work 미seed(부재) ────────────────────────────────────────────────────
def test_capture_absent_work_is_context_error(tmp_path) -> None:
    # work aggregate 미seed → _WorkStateReadAdapter 가 WorkAggregateNotFound 를 None 으로 번역 →
    # resolver 가 TemplateInitializationRequired → capture 는 context error 로 닫는다(raise 아님).
    result = _capture(tmp_path)
    assert isinstance(result, ExecutionCaptureContextError)


# ─── domain block: config 파일은 있으나 current Application draft 부재 ───────────────────
def test_config_present_without_current_app_draft_is_domain_block(tmp_path) -> None:
    # config 파일 자체는 존재(ConfigurationAggregateNotFound 경로와 구별)하되 current Application(APP)
    # draft 가 없다 → _load_config_draft 의 loop-not-found → SLOTTED 구조가 불완전 선택으로 막힌다.
    _seed_v2_work(tmp_path, with_config=False)
    WorkSlotConfigurationStore(tmp_path / "slot_configs").create(
        StoredWorkConfiguration(
            schema_version=CFG_STORE_SCHEMA, aggregate_version=1, workspace_instance_id=WS,
            configurations=WorkSlotConfigurationAggregate(
                schema_version=CFG_AGG_SCHEMA, work_id=WORK,
                configurations=(
                    WorkSlotConfigurationDraft(
                        work_id=WORK, base_template_application_id="other-app", version=1,
                        selections=SlotSelectionSet((SlotSelection("s1", ("o1",)),)),
                        origin=EMPTY, reconciled_from_application_id=None,
                        reconciled_from_version=None,
                        reconciled_from_declared_selection_digest=None,
                        created_at=AT, updated_at=AT,
                    ),
                ),
            ),
            processed_requests=(),
        )
    )
    result = _capture(tmp_path)
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert SLOT_CONFIGURATION_INCOMPLETE in result.normalized_blockers


# ─── context error: code 없는 store 오류 → generic fallback code ─────────────────────────
def test_missing_evidence_is_generic_context_error(tmp_path) -> None:
    # current Application 이 없는 evidence 를 가리킨다 → get_evidence 가 ObjectNotFound(.code 없음)
    # → capture 는 generic capture context error code 로 정규화한다.
    AtomicWorkTemplateStateStore(tmp_path / "works").create(
        WorkTemplateStateAggregate(
            schema_version=WORK_SCHEMA, aggregate_version=1,
            work=DocumentWork(
                work_id=WORK, template_lineage_id=LINEAGE,
                current_template_application_id=APP,
                current_template_preparation_id=None, prepare_seq=0,
            ),
            applications=(
                WorkTemplateApplication(
                    application_id=APP, work_id=WORK, application_epoch=1,
                    pass_evidence_id="ghost-evidence", previous_application_id=None,
                    origin=INITIALIZATION, prepared_change_id=None, actor="t", applied_at=AT,
                ),
            ),
            preparations=(), prepared_changes=(), apply_provenance=(), outbox_events=(),
        )
    )
    result = _capture(tmp_path)
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == "EXECUTION_CAPTURE_CONTEXT_ERROR"


# ─── shipping policy: EXACT selector 반영(default 아님) ──────────────────────────────────
def test_shipping_policy_reflects_exact_selector() -> None:
    from hwpxfiller.application.stored_execution_plan import RequestedExact

    command = SealExecutionPlanCommand(
        workspace_instance_id=WS, work_ref="job-ref", request_id="r1",
        requested_execution_semantic_contract=RequestedExact("custom-exec/v9"),
    )
    policy = resolve_shipping_policy(command, WorkExecutionSummary(PROFILE, APP))
    # AUTO default("execution-semantics/v1")가 아니라 EXACT 요청값을 그대로 반영한다.
    assert policy.execution_semantic_contract_id == "custom-exec/v9"
