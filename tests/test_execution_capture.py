"""S5-02 exact execution capture 판정 — result algebra·cross-reference·base·projection (#698)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
    CONTINUATION_BASE_NOT_SUPPORTED,
    CONTINUATION_OUTPUT_DOCUMENT,
    EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR,
    FIELD_BINDING_INPUT_INTEGRITY_ERROR,
    MATERIALIZATION_BASE_CONTRACT_ID,
    NEEDS_BINDING_SEMANTIC_MIGRATION,
    NEEDS_FIELD_BINDING_APPLICATION_REVIEW,
    QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR,
    QUALIFICATION_PROFILE_REVOKED,
    SELECTION_CONTRACT_INTEGRITY_ERROR,
    SLOT_CONFIGURATION_INCOMPLETE,
    SLOTLESS,
    SLOTTED,
    UNSUPPORTED_LOCAL_IMPLEMENTATION,
    CapturedExecutionDomainBlock,
    CapturedExecutionInput,
    CapturedExecutionPolicyBlock,
    CapturedFieldBinding,
    CapturedSelection,
    CapturedTemplateExecutionInput,
    DomainBlockedFieldBinding,
    DomainBlockedSelection,
    ExactTemplateExecutionBasis,
    ExactTemplateQualificationContext,
    ExecutionCaptureContextError,
    ExecutionCaptureIntegrityError,
    LegacyContinuationGenerationAdapter,
    ManagedPlanMaterializationAdapter,
    QualificationProfileSemanticPayload,
    ResolvedSealPolicy,
    WorkRouteRef,
    build_exact_execution_basis,
    judge_captured_execution,
    project_effective_selection,
    semantic_projection_digest,
)
from hwpxfiller.application.execution_structure import (
    EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    ENVELOPE_CAPABILITY_KEYS,
    RESOLVER_STABILITY_KEYS,
    ContentEntry,
    FieldOccurrence,
    OWNER_ROOT,
    build_execution_structure,
    template_structure_digest,
)
from hwpxfiller.application.field_binding_input import build_field_binding_input
from hwpxfiller.application.slot_configuration_context import ExactAppliedTemplateInput
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
)
from hwpxfiller.application.template_qualification import TemplateStructure
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    ExactText,
    FieldBindingRule,
)
from hwpxfiller.domain.slot_selection import SlotSelectionSet, digest_selection_set

WS = "ws-1"
WORK = "work-1"
APP = "app-1"
PROFILE = "hwpx-template-qualification-v2"
MEDIA = "hwpx"
CONTRACT = "slot-selection/v1"
AT = "2026-08-16T00:00:00Z"


def _structure():
    return build_execution_structure(
        product_structure=TemplateStructure(root_fields=("f1",), slots=()),
        occurrences=[
            FieldOccurrence(
                field_id="f1",
                occurrence_ordinal=0,
                owner_kind=OWNER_ROOT,
                owner_slot_id=None,
                owner_option_id=None,
                content_entry_id="e1",
                structural_order=0,
                native_value_target_class="text",
                resolver_contract_id="res/1",
            )
        ],
        slot_regions=[],
        option_regions=[],
        content_entries=[
            ContentEntry("e1", "para", {k: True for k in ENVELOPE_CAPABILITY_KEYS})
        ],
        resolver_stability_facts={k: True for k in RESOLVER_STABILITY_KEYS},
        admitted_relation_profile="rel/1",
    )


STRUCT_DIGEST = template_structure_digest(_structure())


def _payload(profile=PROFILE, media=MEDIA):
    return QualificationProfileSemanticPayload(
        qualification_profile_id=profile,
        media=media,
        adapter_contract_version="a/1",
        product_rule_version="p/1",
        operation_alphabet_version="o/1",
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload={"k": "v"},
    )


def _applied(work=WORK, app=APP, media=MEDIA):
    return ExactAppliedTemplateInput(
        work_id=work,
        template_application_id=app,
        revision_id="rev-1",
        media=media,
        template_lineage_id="lin-1",
        exact_content_digest="sha256:cccc",
        canonical_blob_reference="blob://x",
    )


def _qualification(profile=PROFILE, schema=EXECUTION_STRUCTURE_PROJECTION_SCHEMA, revision="rev-1"):
    struct = _structure()
    return ExactTemplateQualificationContext(
        pass_evidence_id="ev-1",
        qualification_profile_id=profile,
        qualification_profile_semantic_payload=_payload(profile=profile),
        structure_projection_schema_version=schema,
        template_structure_digest=template_structure_digest(struct),
        execution_structure=struct,
        composition_profile_state="SEALED",
        revision_id=revision,
    )


def _template(work=WORK, app=APP, ws=WS, media=MEDIA, profile=PROFILE):
    return CapturedTemplateExecutionInput(
        workspace_instance_id=ws,
        work_authority_id=work,
        applied=_applied(work=work, app=app, media=media),
        qualification=_qualification(profile=profile),
        captured_at=AT,
    )


def _policy(base=APPLIED_TEMPLATE_CANDIDATE, mat=MATERIALIZATION_BASE_CONTRACT_ID):
    return ResolvedSealPolicy(
        policy_resolution_version="pol/1",
        execution_base_kind=base,
        execution_semantic_contract_id="exec/1",
        binding_value_contract_id="bind/1",
        raw_record_contract_id="rr/1",
        document_value_resolution_contract_id="dvr/1",
        record_validation_contract_id="rv/1",
        record_review_contract_id="review/1",
        composition_contract_id="comp/1",
        native_primitive_contract_id="nat/1",
        materialization_base_contract_id=mat,
        composition_theorem_evidence_manifest_digest="sha256:dddd",
        materialization_contract_id="mat/1",
        plan_schema_version="plan/1",
        canonical_encoding_version="enc/1",
    )


def _slotless(work=WORK, app=APP):
    return SlotlessSelectionContext(
        work_id=work,
        template_application_id=app,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        template_structure_digest=STRUCT_DIGEST,
        source_configuration_version=None,
        declared_selection_digest=None,
        captured_at=AT,
    )


def _binding(work=WORK, app=APP, ws=WS):
    return build_field_binding_input(
        workspace_instance_id=ws,
        work_authority_id=work,
        base_template_application_id=app,
        binding_rules=[
            FieldBindingRule(
                field_id="f1",
                binding_kind=CONSTANT,
                document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
                canonical_constant_value=ExactText("v"),
            )
        ],
        source_schema_keys=("col",),
        raw_record_contract_id="rr/1",
        captured_at=AT,
    )


def _judge(**over):
    kw = dict(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        expected_template_application_id=APP,
        expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(),
        selection_observation=CapturedSelection(_slotless()),
        field_binding_observation=CapturedFieldBinding(_binding()),
        captured_at=AT,
    )
    kw.update(over)
    return judge_captured_execution(**kw)


# ─── identity / reuse ─────────────────────────────────────────────────────────────
def test_work_route_ref_is_not_authority_identity():
    ref = WorkRouteRef(workspace_instance_id=WS, work_ref="어떤 작업")
    # route locator 는 authority id 필드를 갖지 않는다(값 동일성으로 identity 를 주지 않는다).
    assert not hasattr(ref, "work_authority_id")
    assert ref.work_ref == "어떤 작업"


def test_selection_variants_have_no_workspace_field():
    # S4 Selection variant 에는 workspace field 가 없다 — cross-check 가 이를 비교하면 안 된다.
    assert not hasattr(_slotless(), "workspace_instance_id")


def test_no_selection_workspace_comparison_in_source():
    # repo gate: 이 모듈은 selection.workspace_instance_id 를 절대 읽지 않는다.
    src = Path("src/hwpxfiller/application/execution_capture.py").read_text("utf-8")
    assert not re.search(r"selection\w*\.workspace_instance_id", src)


def test_no_new_work_identity_generator_in_source():
    # 새 Work identity 발급 경로 0 — id 를 만들어내는 hashing/uuid seam 이 없다.
    src = Path("src/hwpxfiller/application/execution_capture.py").read_text("utf-8")
    assert "uuid" not in src
    assert "authority_id_identity" not in src


# ─── cross-reference ──────────────────────────────────────────────────────────────
def test_complete_input_when_all_exact():
    result = _judge()
    assert isinstance(result, CapturedExecutionInput)
    assert result.work_authority_id == WORK
    assert result.captured_execution_input_digest is None  # S5-06 이 채운다


def test_workspace_and_binding_exact_match_required():
    result = _judge(field_binding_observation=CapturedFieldBinding(_binding(ws="other-ws")))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == FIELD_BINDING_INPUT_INTEGRITY_ERROR


def test_work_id_four_way_equality():
    # selection.work_id 가 어긋나면 selection integrity context error.
    result = _judge(selection_observation=CapturedSelection(_slotless(work="other")))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == SELECTION_CONTRACT_INTEGRITY_ERROR


def test_application_id_three_way_equality():
    result = _judge(field_binding_observation=CapturedFieldBinding(_binding(app="other-app")))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == FIELD_BINDING_INPUT_INTEGRITY_ERROR


def test_request_work_authority_mismatch_is_applied_context_error():
    result = _judge(work_authority_id="other-work", template=_template())
    # template.work_authority_id(WORK) != 요청 work → applied context error.
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR


def test_binding_work_authority_mismatch_is_field_binding_error():
    result = _judge(field_binding_observation=CapturedFieldBinding(_binding(work="other")))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == FIELD_BINDING_INPUT_INTEGRITY_ERROR


def test_selection_application_mismatch_is_selection_error():
    result = _judge(selection_observation=CapturedSelection(_slotless(app="other-app")))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == SELECTION_CONTRACT_INTEGRITY_ERROR


def test_template_work_authority_must_equal_applied_work_id():
    # 한 DTO 안의 four-way anchor 위반은 loud 예외.
    with pytest.raises(ExecutionCaptureIntegrityError):
        CapturedTemplateExecutionInput(
            workspace_instance_id=WS,
            work_authority_id="w-a",
            applied=_applied(work="w-b"),
            qualification=_qualification(),
            captured_at=AT,
        )


def test_empty_required_field_rejected():
    with pytest.raises(ExecutionCaptureIntegrityError):
        QualificationProfileSemanticPayload(
            qualification_profile_id="",
            media=MEDIA,
            adapter_contract_version="a/1",
            product_rule_version="p/1",
            operation_alphabet_version="o/1",
            projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
            manifest_payload={},
        )


def test_project_effective_selection_rejects_unknown_variant():
    with pytest.raises(ExecutionCaptureIntegrityError):
        project_effective_selection(object())  # type: ignore[arg-type]


def test_semantic_projection_digest_is_deterministic_and_change_sensitive():
    proj = _judge().captured_execution_input_semantic_projection
    d1 = semantic_projection_digest(proj)
    d2 = semantic_projection_digest(dict(proj))
    assert d1 == d2 and d1.startswith("sha256:")
    changed = dict(proj)
    changed["work_authority_id"] = "changed"
    assert semantic_projection_digest(changed) != d1


def test_expected_profile_mismatch_is_qualification_context_error():
    result = _judge(expected_profile_id="other-profile")
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR


def test_expected_application_mismatch_is_applied_context_error():
    result = _judge(expected_template_application_id="other-app")
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR


def test_request_workspace_mismatch_is_applied_context_error():
    result = _judge(workspace_instance_id="other-ws")
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR


def test_internal_media_mismatch_raises_at_construction():
    # 한 DTO 안의 위반은 result 가 아니라 loud 예외(위조 payload 차단).
    with pytest.raises(ExecutionCaptureIntegrityError):
        CapturedTemplateExecutionInput(
            workspace_instance_id=WS,
            work_authority_id=WORK,
            applied=_applied(media="pdf"),
            qualification=_qualification(),  # payload media=hwpx
            captured_at=AT,
        )


def test_semantic_payload_profile_mismatch_raises():
    struct = _structure()
    with pytest.raises(ExecutionCaptureIntegrityError):
        ExactTemplateQualificationContext(
            pass_evidence_id="ev-1",
            qualification_profile_id="A",
            qualification_profile_semantic_payload=_payload(profile="B"),
            structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
            template_structure_digest=template_structure_digest(struct),
            execution_structure=struct,
            composition_profile_state="SEALED",
            revision_id="rev-1",
        )


# ─── result algebra ───────────────────────────────────────────────────────────────
def test_incomplete_slot_is_domain_block():
    result = _judge(
        selection_observation=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "미완")
    )
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert result.normalized_blockers == (SLOT_CONFIGURATION_INCOMPLETE,)
    assert "captured_at" not in _flatten_keys(result.captured_attempt_semantic_projection)


def test_legacy_binding_is_migration_block():
    result = _judge(
        field_binding_observation=DomainBlockedFieldBinding(
            NEEDS_BINDING_SEMANTIC_MIGRATION, "legacy"
        )
    )
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert result.normalized_blockers == (NEEDS_BINDING_SEMANTIC_MIGRATION,)


def test_stale_binding_base_is_application_review_block():
    result = _judge(
        field_binding_observation=DomainBlockedFieldBinding(
            NEEDS_FIELD_BINDING_APPLICATION_REVIEW, "stale"
        )
    )
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert result.normalized_blockers == (NEEDS_FIELD_BINDING_APPLICATION_REVIEW,)


def test_both_blocked_lists_both_blockers():
    result = _judge(
        selection_observation=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "x"),
        field_binding_observation=DomainBlockedFieldBinding(
            NEEDS_BINDING_SEMANTIC_MIGRATION, "y"
        ),
    )
    assert isinstance(result, CapturedExecutionDomainBlock)
    assert set(result.normalized_blockers) == {
        SLOT_CONFIGURATION_INCOMPLETE,
        NEEDS_BINDING_SEMANTIC_MIGRATION,
    }


def test_revoked_profile_is_policy_block():
    block = CapturedExecutionPolicyBlock(
        policy_code=QUALIFICATION_PROFILE_REVOKED, observed_at=AT, qualification_profile_id=PROFILE
    )
    result = _judge(policy_block=block)
    assert result is block


def test_context_error_does_not_consume_request_id_or_terminate():
    result = _judge(expected_profile_id="mismatch")
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.consumes_request_id is False
    assert result.is_terminal_command_outcome is False


def test_only_complete_input_carries_digest_field():
    # complete input variant 만 digest 필드를 가진다(다른 variant 엔 부여하지 않는다).
    assert hasattr(_judge(), "captured_execution_input_digest")
    block = _judge(
        selection_observation=DomainBlockedSelection(SLOT_CONFIGURATION_INCOMPLETE, "x")
    )
    assert not hasattr(block, "captured_execution_input_digest")


# ─── base / continuation ──────────────────────────────────────────────────────────
def test_applied_candidate_exact_base():
    basis = build_exact_execution_basis(_template(), _policy())
    assert isinstance(basis, ExactTemplateExecutionBasis)
    assert basis.execution_base_kind == APPLIED_TEMPLATE_CANDIDATE
    assert basis.materialization_base_contract_id == MATERIALIZATION_BASE_CONTRACT_ID
    assert basis.exact_content_digest == "sha256:cccc"


def test_non_applied_base_kind_rejected_no_fallback():
    with pytest.raises(ExecutionCaptureIntegrityError):
        build_exact_execution_basis(_template(), _policy(base="latest"))


def test_wrong_materialization_contract_rejected():
    with pytest.raises(ExecutionCaptureIntegrityError):
        build_exact_execution_basis(_template(), _policy(mat="something/v2"))


def test_unknown_base_kind_is_context_error():
    result = _judge(resolved_seal_policy=_policy(base="mystery"))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == UNSUPPORTED_LOCAL_IMPLEMENTATION


def test_wrong_materialization_contract_is_dependency_context_error():
    result = _judge(resolved_seal_policy=_policy(mat="other/v1"))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == EXECUTION_PLAN_DEPENDENCY_RESOLUTION_ERROR


def test_continuation_is_policy_block():
    result = _judge(resolved_seal_policy=_policy(base=CONTINUATION_OUTPUT_DOCUMENT))
    assert isinstance(result, CapturedExecutionPolicyBlock)
    assert result.policy_code == CONTINUATION_BASE_NOT_SUPPORTED


def test_legacy_and_managed_adapter_type_separation():
    legacy = LegacyContinuationGenerationAdapter()
    managed = ManagedPlanMaterializationAdapter()
    assert type(legacy) is not type(managed)
    assert not isinstance(legacy, ManagedPlanMaterializationAdapter)
    # legacy 는 exact/Plan-bound provenance 를 주장하지 않는다.
    assert legacy.claims_exact_guarantee is False
    assert legacy.claims_plan_bound_provenance is False
    assert managed.claims_exact_guarantee is True


def test_execution_structure_schema_must_match_declared_schema():
    # payload·declared 가 v1 로 일치해도 execution_structure(v2)와 어긋나면 loud 로 막힌다.
    struct = _structure()
    with pytest.raises(ExecutionCaptureIntegrityError):
        ExactTemplateQualificationContext(
            pass_evidence_id="ev-1",
            qualification_profile_id=PROFILE,
            qualification_profile_semantic_payload=QualificationProfileSemanticPayload(
                qualification_profile_id=PROFILE,
                media=MEDIA,
                adapter_contract_version="a/1",
                product_rule_version="p/1",
                operation_alphabet_version="o/1",
                projection_schema_version="hwpx-structure-projection-v1",
                manifest_payload={},
            ),
            structure_projection_schema_version="hwpx-structure-projection-v1",
            template_structure_digest=template_structure_digest(struct),
            execution_structure=struct,
            composition_profile_state="SEALED",
            revision_id="rev-1",
        )


def test_v1_structure_schema_rejected_at_construction():
    # v2-only ExecutionTemplateStructure 와 v1 선언 schema 는 loud integrity 로 막힌다(fail-closed).
    struct = _structure()
    with pytest.raises(ExecutionCaptureIntegrityError):
        ExactTemplateQualificationContext(
            pass_evidence_id="ev-1",
            qualification_profile_id=PROFILE,
            qualification_profile_semantic_payload=_payload(),
            structure_projection_schema_version="hwpx-structure-projection-v1",
            template_structure_digest=template_structure_digest(struct),
            execution_structure=struct,
            composition_profile_state="SEALED",
            revision_id="rev-1",
        )


# ─── projection ───────────────────────────────────────────────────────────────────
def _flatten_keys(mapping):
    keys = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                keys.add(k)
                walk(v)

    walk(mapping)
    return keys


def test_projection_excludes_captured_at():
    proj = _judge().captured_execution_input_semantic_projection
    assert "captured_at" not in _flatten_keys(proj)


def test_projection_excludes_authority_and_configuration_revision():
    proj = _judge().captured_execution_input_semantic_projection
    flat = _flatten_keys(proj)
    assert "field_binding_authority_revision" not in flat
    assert "source_configuration_version" not in flat
    assert "canonical_blob_reference" not in flat  # store address


def test_semantic_claim_change_changes_projection():
    base = _judge().captured_execution_input_semantic_projection
    other_binding = build_field_binding_input(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        base_template_application_id=APP,
        binding_rules=[
            FieldBindingRule(
                field_id="f1",
                binding_kind=CONSTANT,
                document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
                canonical_constant_value=ExactText("DIFFERENT"),
            )
        ],
        source_schema_keys=("col",),
        raw_record_contract_id="rr/1",
        captured_at=AT,
    )
    changed = _judge(
        field_binding_observation=CapturedFieldBinding(other_binding)
    ).captured_execution_input_semantic_projection
    assert base != changed


def test_projection_stable_against_incidental_captured_at():
    # captured_at 만 다른 두 template 은 같은 semantic projection 을 낸다(우연 변화와 분리).
    a = _judge().captured_execution_input_semantic_projection
    tmpl_b = CapturedTemplateExecutionInput(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        applied=_applied(),
        qualification=_qualification(),
        captured_at="2099-12-31T23:59:59Z",
    )
    b = _judge(template=tmpl_b).captured_execution_input_semantic_projection
    assert a == b


def test_effective_selection_projection_slot_mode():
    slotless = project_effective_selection(_slotless())
    assert slotless.slot_mode == SLOTLESS
    assert slotless.effective_selection_digest is None

    selections = SlotSelectionSet(())
    snapshot = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=3,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=selections,
        effective_selection_digest=digest_selection_set(CONTRACT, selections),
        declared_selection_digest=digest_selection_set(CONTRACT, selections),
        template_structure_digest=STRUCT_DIGEST,
        captured_at=AT,
    )
    slotted = project_effective_selection(snapshot)
    assert slotted.slot_mode == SLOTTED
    assert slotted.effective_selection_digest is not None


# ─── recompute/rebind integrity (Codex review #715) ────────────────────────────────
def _snapshot(effective_digest=None):
    selections = SlotSelectionSet(())
    return SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=3,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=selections,
        effective_selection_digest=(
            effective_digest
            if effective_digest is not None
            else digest_selection_set(CONTRACT, selections)
        ),
        declared_selection_digest=digest_selection_set(CONTRACT, selections),
        template_structure_digest=STRUCT_DIGEST,
        captured_at=AT,
    )


def test_selection_from_different_structure_digest_is_context_error():
    # #1: 같은 work/app 이라도 다른 structure(digest)에서 캡처된 선택은 exact input 이 아니다.
    result = _judge(
        selection_observation=CapturedSelection(
            SlotlessSelectionContext(
                work_id=WORK,
                template_application_id=APP,
                selection_semantic_contract_id=CONTRACT,
                structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
                template_structure_digest="sha256:different",
                source_configuration_version=None,
                declared_selection_digest=None,
                captured_at=AT,
            )
        )
    )
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == SELECTION_CONTRACT_INTEGRITY_ERROR


def test_selection_from_different_structure_schema_is_context_error():
    # #1(schema 축): 선택이 다른 projection schema 에서 캡처됐으면 exact input 이 아니다.
    result = _judge(
        selection_observation=CapturedSelection(
            SlotlessSelectionContext(
                work_id=WORK,
                template_application_id=APP,
                selection_semantic_contract_id=CONTRACT,
                structure_projection_schema_version="hwpx-structure-projection-v1",
                template_structure_digest=STRUCT_DIGEST,
                source_configuration_version=None,
                declared_selection_digest=None,
                captured_at=AT,
            )
        )
    )
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == SELECTION_CONTRACT_INTEGRITY_ERROR


def test_stale_template_structure_digest_rejected_at_construction():
    # #2: template_structure_digest claim 은 execution_structure recompute 와 대조된다.
    struct = _structure()
    with pytest.raises(ExecutionCaptureIntegrityError):
        ExactTemplateQualificationContext(
            pass_evidence_id="ev-1",
            qualification_profile_id=PROFILE,
            qualification_profile_semantic_payload=_payload(),
            structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
            template_structure_digest="sha256:stale",
            execution_structure=struct,
            composition_profile_state="SEALED",
            revision_id="rev-1",
        )


def test_evidence_must_bind_to_applied_revision():
    # #3: media 만 같은 다른 Candidate 에 남의 PASS evidence 를 붙이지 못한다.
    with pytest.raises(ExecutionCaptureIntegrityError):
        CapturedTemplateExecutionInput(
            workspace_instance_id=WS,
            work_authority_id=WORK,
            applied=_applied(),  # revision_id="rev-1"
            qualification=_qualification(revision="rev-2"),
            captured_at=AT,
        )


def test_forged_effective_selection_digest_rejected():
    # #4: claimed effective digest 를 믿지 않고 recompute 한다.
    with pytest.raises(ExecutionCaptureIntegrityError):
        project_effective_selection(_snapshot(effective_digest="sha256:forged"))
    result = _judge(selection_observation=CapturedSelection(_snapshot("sha256:forged")))
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == SELECTION_CONTRACT_INTEGRITY_ERROR


def test_manifest_payload_deep_copied():
    # #5: nested mapping/list 를 build 이후 caller 가 고쳐도 DTO 값이 흔들리지 않는다.
    nested = ["a"]
    payload = QualificationProfileSemanticPayload(
        qualification_profile_id=PROFILE,
        media=MEDIA,
        adapter_contract_version="a/1",
        product_rule_version="p/1",
        operation_alphabet_version="o/1",
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload={"nested": nested},
    )
    nested.append("MUTATED")
    assert payload.manifest_payload["nested"] == ["a"]


def test_resolved_seal_policy_rejects_empty_contract_id():
    # #6: 누락된 contract identity 를 capture 로 실어 나르지 않는다.
    with pytest.raises(ExecutionCaptureIntegrityError):
        _policy_with(raw_record_contract_id="")
    with pytest.raises(ExecutionCaptureIntegrityError):
        _policy_with(canonical_encoding_version="")


def _policy_with(**over):
    from dataclasses import replace

    return replace(_policy(), **over)


def test_policy_block_profile_must_match_requested():
    # #7: 다른/구 profile 의 policy 판정을 이 profile 의 결과로 되돌려주지 않는다.
    block = CapturedExecutionPolicyBlock(
        policy_code=QUALIFICATION_PROFILE_REVOKED,
        observed_at=AT,
        qualification_profile_id="OTHER-PROFILE",
    )
    result = _judge(policy_block=block)
    assert isinstance(result, ExecutionCaptureContextError)
    assert result.code == QUALIFICATION_PROFILE_MANIFEST_INTEGRITY_ERROR


def test_selection_claims_carry_projection_contract():
    # #8: projection 계약 version 이 semantic identity 에 참여한다.
    proj = _judge().captured_execution_input_semantic_projection
    assert proj["selection"]["selection_projection_contract"] == "execution-semantics/v1"
