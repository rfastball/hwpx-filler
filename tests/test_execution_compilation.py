"""S5-05(#701) effective content·Active Field·deterministic operation compiler.

체크리스트: effective content(root/shared/selected retain·unselected target·slot/option order·
slotless 0·fail-closed) · Active Field(occurrence count·canonical sequence·inactive 제외·
selected delta·native handle 0) · qualification(SOURCE/CONSTANT/BLANK positive·unbound·
required source key·inactive nonblocking·record 미검사) · compiler(deterministic order·
bijection·duplicate/missing rejection·same-span dedup 0·order perturbation invariant) ·
effective-only(detached/inactive/unused-key/version-only 불변·active change 변경) ·
no-forbidden-work(reader/filename/parser spy 0).

모든 structure fixture 는 S5-03 native-free builder 로 세우고 composition PASS 는 실 S5-04
verifier 로 얻는다(실 HWPX mutation·row read 0).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    MATERIALIZATION_BASE_CONTRACT_ID,
    SLOTLESS,
    SLOTTED,
    CapturedExecutionInput,
    CapturedTemplateExecutionInput,
    ExactTemplateQualificationContext,
    QualificationProfileSemanticPayload,
    ResolvedSealPolicy,
)
from hwpxfiller.application.execution_compilation import (
    ACTIVE_FIELD_UNBOUND,
    COMPOSITION_POLICY_IDENTITY_MISMATCH,
    COMPOSITION_PREMISES_NOT_PASSED,
    COMPOSITION_STRUCTURE_MISMATCH,
    REQUIRED_SOURCE_KEY_MISSING,
    SELECTION_CONTRACT_INTEGRITY_ERROR,
    SELECTION_STRUCTURE_DIGEST_MISMATCH,
    SLOT_CONFIGURATION_INCOMPLETE,
    SLOT_MODE_MISMATCH,
    UNKNOWN_SELECTION_TARGET,
    ActiveFieldRequirement,
    ApplyFieldBinding,
    ConstantValue,
    ExecutionCompilationContextError,
    ExecutionCompilationError,
    ExecutionQualificationBlocked,
    FromSource,
    IntentionalBlank,
    QualifiedExecutionCompilation,
    RemoveOption,
    qualify_and_compile_execution,
    verify_requirement_operation_bijection,
)
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_V1,
    THEOREM_EVIDENCE_V1,
    CompositionPremisesBlocked,
    CompositionPremisesPassed,
    CompositionPremiseContextError,
    theorem_evidence_digest,
    verify_execution_composition_premises,
)
from hwpxfiller.application.execution_structure import (
    ENVELOPE_CAPABILITY_KEYS,
    EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    RESOLVER_STABILITY_KEYS,
    ContentEntry,
    FieldOccurrence,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
    template_structure_digest,
)
from hwpxfiller.application.field_binding_input import build_field_binding_input
from hwpxfiller.application.slot_configuration_context import ExactAppliedTemplateInput
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    DOCUMENT_CONTENT_VALUE_POLICY_V1,
    EXACT_BLANK_POLICY,
    INTENTIONAL_BLANK,
    SOURCE,
    ExactText,
    FieldBindingRule,
)
from hwpxfiller.domain.slot_selection import (
    SlotSelection,
    SlotSelectionSet,
    digest_selection_set,
)

WS = "ws-1"
WORK = "work-1"
APP = "app-1"
PROFILE = "hwpx-template-qualification-v2"
MEDIA = "hwpx"
CONTRACT = "slot-selection/v1"
AT = "2026-08-16T00:00:00Z"
RC = "hwpx-field-resolver/v1"  # native primitive field_resolver 와 일치(composition PASS 조건)
REMOVE = "remove-option/v1"  # native primitive option_removal 과 일치
VTC = "hwpx-field-value/v1"
RESOLVER_FACTS = {k: True for k in RESOLVER_STABILITY_KEYS}


def _entry(entry_id="c0"):
    return ContentEntry(entry_id, "section-body/v1", {k: True for k in ENVELOPE_CAPABILITY_KEYS})


def _occ(field_id, ordinal, kind, order, slot=None, option=None):
    return FieldOccurrence(
        field_id=field_id,
        occurrence_ordinal=ordinal,
        owner_kind=kind,
        owner_slot_id=slot,
        owner_option_id=option,
        content_entry_id="c0",
        structural_order=order,
        native_value_target_class=VTC,
        resolver_contract_id=RC,
    )


def _structure():
    """root 성명(x2)+shared 주소 + slot s1{o1:항목, o2:금액}, o1·o2 disjoint region."""
    product = TemplateStructure(
        root_fields=("성명",),
        slots=(
            TemplateSlot(
                id="s1",
                shared_fields=("주소",),
                options=(TemplateOption("o1", ("항목",)), TemplateOption("o2", ("금액",))),
            ),
        ),
    )
    return build_execution_structure(
        product_structure=product,
        occurrences=(
            _occ("성명", 0, OWNER_ROOT, 0),
            _occ("주소", 0, OWNER_SLOT_SHARED, 12, slot="s1"),
            _occ("항목", 0, OWNER_OPTION, 16, slot="s1", option="o1"),
            _occ("금액", 0, OWNER_OPTION, 26, slot="s1", option="o2"),
            _occ("성명", 1, OWNER_ROOT, 50),
        ),
        slot_regions=(SlotRegionObservation("s1", "c0", 10, 40),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", 15, 20, REMOVE),
            OptionRegionObservation("s1", "o2", "c0", 25, 30, REMOVE),
        ),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _slotless_structure():
    return build_execution_structure(
        product_structure=TemplateStructure(root_fields=("성명",)),
        occurrences=(_occ("성명", 0, OWNER_ROOT, 0),),
        slot_regions=(),
        option_regions=(),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )


def _passed(structure):
    result = verify_execution_composition_premises(
        structure=structure,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(result, CompositionPremisesPassed), result
    return result


def _payload():
    return QualificationProfileSemanticPayload(
        qualification_profile_id=PROFILE,
        media=MEDIA,
        adapter_contract_version="a/1",
        product_rule_version="p/1",
        operation_alphabet_version="o/1",
        projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        manifest_payload={"k": "v"},
    )


def _applied(app=APP, revision="rev-1"):
    return ExactAppliedTemplateInput(
        work_id=WORK,
        template_application_id=app,
        revision_id=revision,
        media=MEDIA,
        template_lineage_id="lin-1",
        exact_content_digest="sha256:cccc",
        canonical_blob_reference="blob://x",
    )


def _qualification(structure, app=APP, revision="rev-1"):
    return ExactTemplateQualificationContext(
        pass_evidence_id="ev-1",
        qualification_profile_id=PROFILE,
        qualification_profile_semantic_payload=_payload(),
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        template_structure_digest=template_structure_digest(structure),
        execution_structure=structure,
        composition_profile_state="SEALED",
        revision_id=revision,
    )


def _template(structure, app=APP, revision="rev-1"):
    return CapturedTemplateExecutionInput(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        applied=_applied(app=app, revision=revision),
        qualification=_qualification(structure, app=app, revision=revision),
        captured_at=AT,
    )


def _policy(**over):
    # composition identity 3종은 실 verifier 가 증명하는 registered v1 identity 와 일치해야
    # proof↔policy binding 게이트를 통과한다.
    kw = dict(
        policy_resolution_version="pol/1",
        execution_base_kind=APPLIED_TEMPLATE_CANDIDATE,
        execution_semantic_contract_id="exec/1",
        binding_value_contract_id="bind/1",
        raw_record_contract_id="rr/1",
        document_value_resolution_contract_id="dvr/1",
        record_validation_contract_id="rv/1",
        record_review_contract_id="review/1",
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        composition_theorem_evidence_manifest_digest=theorem_evidence_digest(
            THEOREM_EVIDENCE_V1
        ),
        materialization_contract_id="mat/1",
        plan_schema_version="plan/1",
        canonical_encoding_version="enc/1",
    )
    kw.update(over)
    return ResolvedSealPolicy(**kw)


def _snapshot(structure, *, selected="o1", detached=None, app=APP, config_version=3):
    """s1 에 selected Option 하나(기본 o1). detached=옵션 id 를 declared 에만 더한다."""
    effective = SlotSelectionSet((SlotSelection("s1", (selected,)),))
    declared_sels = [SlotSelection("s1", (selected,) + ((detached,) if detached else ()))]
    declared = SlotSelectionSet(tuple(declared_sels))
    return SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=app,
        source_configuration_version=config_version,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, declared),
        template_structure_digest=template_structure_digest(structure),
        captured_at=AT,
    )


def _slotless_selection(structure):
    return SlotlessSelectionContext(
        work_id=WORK,
        template_application_id=APP,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        template_structure_digest=template_structure_digest(structure),
        source_configuration_version=None,
        declared_selection_digest=None,
        captured_at=AT,
    )


def _rules(*, name_key="이름", drop=(), extra=()):
    """성명=SOURCE(name_key)·주소=CONSTANT·항목=BLANK·금액=SOURCE. drop 은 field_id 를 뺀다."""
    base = {
        "성명": FieldBindingRule(
            field_id="성명",
            binding_kind=SOURCE,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            source_key=name_key,
            format_code="",
        ),
        "주소": FieldBindingRule(
            field_id="주소",
            binding_kind=CONSTANT,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            canonical_constant_value=ExactText("서울"),
        ),
        "항목": FieldBindingRule(
            field_id="항목",
            binding_kind=INTENTIONAL_BLANK,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
        ),
        "금액": FieldBindingRule(
            field_id="금액",
            binding_kind=SOURCE,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            source_key="금액열",
        ),
    }
    return tuple(r for fid, r in base.items() if fid not in drop) + tuple(extra)


def _binding(structure, *, rules=None, schema_keys=("이름", "금액열", "unused"), app=APP):
    return build_field_binding_input(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        base_template_application_id=app,
        binding_rules=_rules() if rules is None else rules,
        source_schema_keys=schema_keys,
        raw_record_contract_id="rr/1",
        captured_at=AT,
    )


def _captured(structure, *, selection=None, binding=None, policy=None, app=APP, revision="rev-1"):
    return CapturedExecutionInput(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        template=_template(structure, app=app, revision=revision),
        selection=selection if selection is not None else _snapshot(structure, app=app),
        field_binding=binding if binding is not None else _binding(structure, app=app),
        resolved_seal_policy=policy if policy is not None else _policy(),
        captured_execution_input_semantic_projection={},
        captured_at=AT,
    )


def _compile(structure, **over):
    captured = _captured(structure, **over)
    return qualify_and_compile_execution(
        captured=captured, composition_result=_passed(structure)
    )


# ══ effective content ═════════════════════════════════════════════════════════════
def test_root_shared_selected_retain_unselected_target_exact():
    structure = _structure()
    result = _compile(structure, selection=_snapshot(structure, selected="o1"))
    assert isinstance(result, QualifiedExecutionCompilation)
    # unselected o2 만 RemoveOption target, selected o1 은 0.
    removes = [op for op in result.ordered_operations if isinstance(op, RemoveOption)]
    assert removes == [RemoveOption("s1", "o2")]
    # active logical: 성명(root)·주소(shared)·항목(selected o1). 금액(o2)은 제외.
    assert result.active_field_projection.active_logical_field_order == ("성명", "주소", "항목")


def test_slot_and_option_order_deterministic():
    # 두 slot·각 2 option, selected 는 각각 o?1. RemoveOption 은 slot order 그다음 option order.
    product = TemplateStructure(
        slots=(
            TemplateSlot("sA", options=(TemplateOption("a1"), TemplateOption("a2"))),
            TemplateSlot("sB", options=(TemplateOption("b1"), TemplateOption("b2"))),
        ),
    )
    structure = build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(
            SlotRegionObservation("sA", "c0", 0, 40),
            SlotRegionObservation("sB", "c0", 50, 90),
        ),
        option_regions=(
            # 저장 순서를 일부러 역순으로 흩뜨린다.
            OptionRegionObservation("sB", "b2", "c0", 75, 80, REMOVE),
            OptionRegionObservation("sB", "b1", "c0", 55, 60, REMOVE),
            OptionRegionObservation("sA", "a2", "c0", 25, 30, REMOVE),
            OptionRegionObservation("sA", "a1", "c0", 5, 10, REMOVE),
        ),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )
    effective = SlotSelectionSet(
        (SlotSelection("sA", ("a1",)), SlotSelection("sB", ("b1",)))
    )
    snap = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, effective),
        template_structure_digest=template_structure_digest(structure),
        captured_at=AT,
    )
    binding = _binding(structure, rules=(), schema_keys=())
    result = _compile(structure, selection=snap, binding=binding)
    assert isinstance(result, QualifiedExecutionCompilation)
    removes = [op for op in result.ordered_operations if isinstance(op, RemoveOption)]
    # unselected: a2(slot 0 option 1), b2(slot 1 option 1) → slot order then option order.
    assert removes == [RemoveOption("sA", "a2"), RemoveOption("sB", "b2")]


def test_slotless_remove_target_zero():
    structure = _slotless_structure()
    binding = _binding(structure, rules=(_rules()[0],), schema_keys=("이름",))
    result = _compile(structure, selection=_slotless_selection(structure), binding=binding)
    assert isinstance(result, QualifiedExecutionCompilation)
    assert not any(isinstance(op, RemoveOption) for op in result.ordered_operations)
    assert result.effective_selection_basis.slot_mode == SLOTLESS
    assert result.active_field_projection.active_logical_field_order == ("성명",)


def test_unknown_selection_fail_closed():
    structure = _structure()
    effective = SlotSelectionSet((SlotSelection("s1", ("nonexistent",)),))
    snap = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, effective),
        template_structure_digest=template_structure_digest(structure),
        captured_at=AT,
    )
    result = _compile(structure, selection=snap)
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == UNKNOWN_SELECTION_TARGET


def test_unknown_slot_reference_fail_closed():
    structure = _structure()
    effective = SlotSelectionSet((SlotSelection("s2", ("o1",)),))
    snap = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, effective),
        template_structure_digest=template_structure_digest(structure),
        captured_at=AT,
    )
    result = _compile(structure, selection=snap)
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == UNKNOWN_SELECTION_TARGET


def test_incomplete_slot_blocked():
    structure = _structure()
    # effective_selections 가 s1 을 담지 않음 → SLOT_CONFIGURATION_INCOMPLETE blocker.
    effective = SlotSelectionSet(())
    snap = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, effective),
        template_structure_digest=template_structure_digest(structure),
        captured_at=AT,
    )
    result = _compile(structure, selection=snap)
    assert isinstance(result, ExecutionQualificationBlocked)
    assert [b.code for b in result.normalized_blockers] == [SLOT_CONFIGURATION_INCOMPLETE]


# ══ Active Field ═══════════════════════════════════════════════════════════════════
def test_repeated_logical_field_occurrence_count():
    structure = _structure()
    result = _compile(structure)
    assert isinstance(result, QualifiedExecutionCompilation)
    # 성명 occurrence 2, 나머지 1.
    counts = {r.field_id: r.expected_active_occurrence_count for r in result.active_field_requirements}
    assert counts["성명"] == 2
    assert counts["주소"] == 1 and counts["항목"] == 1
    # occurrence sequence(structural order): 성명@0, 주소@12, 항목@16, 성명@50.
    assert result.active_field_projection.active_field_sequence == ("성명", "주소", "항목", "성명")


def test_inactive_option_field_excluded_and_selected_delta():
    structure = _structure()
    r1 = _compile(structure, selection=_snapshot(structure, selected="o1"))
    r2 = _compile(structure, selection=_snapshot(structure, selected="o2"))
    assert isinstance(r1, QualifiedExecutionCompilation)
    assert isinstance(r2, QualifiedExecutionCompilation)
    assert r1.active_field_projection.active_logical_field_order == ("성명", "주소", "항목")
    # selected 를 o2 로 바꾸면 Active option Field 가 항목→금액 으로 delta.
    assert r2.active_field_projection.active_logical_field_order == ("성명", "주소", "금액")
    assert r1.execution_basis_semantic_digest != r2.execution_basis_semantic_digest


def test_no_native_handle_or_path_in_output():
    structure = _structure()
    result = _compile(structure)
    assert isinstance(result, QualifiedExecutionCompilation)
    text = repr(result.ordered_operations) + repr(result.active_field_requirements)
    for forbidden in ("blob://", "structural_order", "resolver_contract", "native_value"):
        assert forbidden not in text
    # operation alphabet 은 slot/option/field id 만 — native node/handle/BoundaryPairRef 없음.
    for op in result.ordered_operations:
        assert isinstance(op, (RemoveOption, ApplyFieldBinding))


# ══ qualification ══════════════════════════════════════════════════════════════════
def test_source_constant_blank_positive():
    structure = _structure()
    result = _compile(structure)
    assert isinstance(result, QualifiedExecutionCompilation)
    by_field = {r.field_id: r.value_expression for r in result.active_field_requirements}
    assert isinstance(by_field["성명"], FromSource)
    assert by_field["성명"].source_key == "이름"
    assert not hasattr(by_field["성명"], "value_type")
    assert isinstance(by_field["주소"], ConstantValue)
    assert isinstance(by_field["주소"].canonical_value, ExactText)
    assert isinstance(by_field["항목"], IntentionalBlank)
    assert by_field["항목"].exact_blank_policy == EXACT_BLANK_POLICY


def test_unbound_active_field_blocked():
    structure = _structure()
    binding = _binding(structure, rules=_rules(drop=("주소",)))
    result = _compile(structure, binding=binding)
    assert isinstance(result, ExecutionQualificationBlocked)
    codes = [(b.code, b.field_id) for b in result.normalized_blockers]
    assert (ACTIVE_FIELD_UNBOUND, "주소") in codes


def test_required_source_key_set_and_missing_blocker():
    structure = _structure()
    # positive: required source keys = active SOURCE 규칙의 key 만(성명=이름). unused·금액열(비active) 제외.
    ok = _compile(structure, selection=_snapshot(structure, selected="o1"))
    assert isinstance(ok, QualifiedExecutionCompilation)
    assert ok.effective_field_binding_basis.required_source_keys == ("이름",)
    # missing: 성명 SOURCE key 가 schema 에 없으면 REQUIRED_SOURCE_KEY_MISSING.
    binding = _binding(structure, rules=_rules(name_key="빠진열"), schema_keys=("금액열",))
    bad = _compile(structure, binding=binding)
    assert isinstance(bad, ExecutionQualificationBlocked)
    assert bad.normalized_blockers[0].code == REQUIRED_SOURCE_KEY_MISSING


def test_inactive_binding_error_nonblocking():
    structure = _structure()
    # 금액(o2 = 비active)의 source_key 를 schema 에 없는 값으로 바꿔도 blocker 아님(제외).
    rules = _rules()
    rules = tuple(
        FieldBindingRule(
            field_id=r.field_id,
            binding_kind=r.binding_kind,
            document_content_value_policy=r.document_content_value_policy,
            source_key="비존재열" if r.field_id == "금액" else r.source_key,
            format_code=r.format_code,
            canonical_constant_value=r.canonical_constant_value,
        )
        for r in rules
    )
    binding = _binding(structure, rules=rules, schema_keys=("이름",))
    result = _compile(structure, selection=_snapshot(structure, selected="o1"), binding=binding)
    # 금액 은 o2 라 inactive → 그 SOURCE key 부재는 blocker 가 아니다.
    assert isinstance(result, QualifiedExecutionCompilation)
    assert "금액" not in {r.field_id for r in result.active_field_requirements}


def test_value_expressions_carry_no_value_type_slot():
    """v2 payload: 고정값은 tagged text 하나, FROM_SOURCE 는 value_type 키가 없다."""
    from hwpxfiller.application.execution_compilation import (
        _encode_canonical_value,
        encode_value_expression,
    )

    assert _encode_canonical_value(ExactText("1,500")) == {"kind": "TEXT", "text": "1,500"}
    assert _encode_canonical_value(ExactText("")) == {"kind": "TEXT", "text": ""}
    assert encode_value_expression(FromSource("열", None, "document-content-value/v1")) == {
        "kind": "FROM_SOURCE",
        "source_key": "열",
        "format_code": None,
        "document_content_value_policy_id": "document-content-value/v1",
    }
    assert encode_value_expression(
        ConstantValue(ExactText("고정"), None, "document-content-value/v1")
    ) == {
        "kind": "CONSTANT",
        "canonical_value": {"kind": "TEXT", "text": "고정"},
        "format_code": None,
        "document_content_value_policy_id": "document-content-value/v1",
    }


def test_actual_record_value_not_checked():
    # source_key 가 schema 에 있으면 실제 row 값 없이도 통과한다(값 존재/형식 미검사).
    structure = _structure()
    result = _compile(structure)
    assert isinstance(result, QualifiedExecutionCompilation)


# ══ compiler determinism / bijection ══════════════════════════════════════════════
def test_operation_order_and_bijection():
    structure = _structure()
    result = _compile(structure)
    assert isinstance(result, QualifiedExecutionCompilation)
    ops = result.ordered_operations
    # RemoveOption 이 전부 ApplyFieldBinding 앞에 온다.
    kinds = [type(op).__name__ for op in ops]
    first_apply = kinds.index("ApplyFieldBinding")
    assert all(k == "RemoveOption" for k in kinds[:first_apply])
    assert all(k == "ApplyFieldBinding" for k in kinds[first_apply:])
    # requirement ↔ ApplyFieldBinding bijection.
    applies = tuple(op for op in ops if isinstance(op, ApplyFieldBinding))
    verify_requirement_operation_bijection(result.active_field_requirements, applies)
    assert [op.field_id for op in applies] == [r.field_id for r in result.active_field_requirements]


def test_bijection_validator_rejects_mismatch():
    reqs = (ActiveFieldRequirement("a", 1, IntentionalBlank()),)
    with pytest.raises(ExecutionCompilationError):
        verify_requirement_operation_bijection(reqs, (ApplyFieldBinding("b"),))
    with pytest.raises(ExecutionCompilationError):
        verify_requirement_operation_bijection(reqs, (ApplyFieldBinding("a"), ApplyFieldBinding("a")))
    with pytest.raises(ExecutionCompilationError):
        verify_requirement_operation_bijection(
            (reqs[0], reqs[0]), (ApplyFieldBinding("a"),)
        )


def test_storage_order_perturbation_same_semantic_result():
    structure = _structure()
    # binding rule 순서를 뒤집고 schema key 순서를 흩뜨려도 같은 semantic digest.
    rules = tuple(reversed(_rules()))
    b1 = _binding(structure, schema_keys=("이름", "금액열", "unused"))
    b2 = _binding(structure, rules=rules, schema_keys=("unused", "금액열", "이름"))
    r1 = _compile(structure, binding=b1)
    r2 = _compile(structure, binding=b2)
    assert isinstance(r1, QualifiedExecutionCompilation)
    assert isinstance(r2, QualifiedExecutionCompilation)
    assert r1.execution_basis_semantic_digest == r2.execution_basis_semantic_digest
    assert r1.ordered_operations == r2.ordered_operations


def test_same_span_target_blocks_before_compile():
    # 두 distinct Option 이 같은 span(SAME_SPAN) → S5-04 가 먼저 Blocked, compiler dedup 0.
    product = TemplateStructure(
        slots=(TemplateSlot("s1", options=(TemplateOption("o1"), TemplateOption("o2"))),)
    )
    structure = build_execution_structure(
        product_structure=product,
        occurrences=(),
        slot_regions=(SlotRegionObservation("s1", "c0", 0, 40),),
        option_regions=(
            OptionRegionObservation("s1", "o1", "c0", 10, 20, REMOVE),
            OptionRegionObservation("s1", "o2", "c0", 10, 20, REMOVE),
        ),
        content_entries=(_entry(),),
        resolver_stability_facts=RESOLVER_FACTS,
        admitted_relation_profile="unadmitted",
    )
    comp = verify_execution_composition_premises(
        structure=structure,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(comp, CompositionPremisesBlocked)
    # compiler 는 Blocked 를 받으면 operation 을 만들지 않고 context error 로 닫는다.
    binding = _binding(structure, rules=(), schema_keys=())
    effective = SlotSelectionSet((SlotSelection("s1", ("o1",)),))
    snap = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, effective),
        template_structure_digest=template_structure_digest(structure),
        captured_at=AT,
    )
    result = qualify_and_compile_execution(
        captured=_captured(structure, selection=snap, binding=binding),
        composition_result=comp,
    )
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == COMPOSITION_PREMISES_NOT_PASSED


# ══ composition gate ═══════════════════════════════════════════════════════════════
def test_composition_context_error_fail_closed():
    structure = _structure()
    ctx = CompositionPremiseContextError("SOME_CODE", "C3", "fact 부재")
    result = qualify_and_compile_execution(
        captured=_captured(structure), composition_result=ctx
    )
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == COMPOSITION_PREMISES_NOT_PASSED


def test_composition_bound_to_other_structure_rejected():
    structure = _structure()
    other = _slotless_structure()
    result = qualify_and_compile_execution(
        captured=_captured(structure), composition_result=_passed(other)
    )
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == COMPOSITION_STRUCTURE_MISMATCH


@pytest.mark.parametrize(
    "field",
    [
        "composition_contract_id",
        "native_primitive_contract_id",
        "composition_theorem_evidence_manifest_digest",
    ],
)
def test_proof_identity_must_match_admitted_policy(field):
    # proof 는 실 verifier 의 registered v1 identity 를 담는다. policy 가 다른 composition/
    # native-primitive/theorem-evidence identity 를 admit 했으면 fail-closed(다른 증명이
    # operation 을 authorize 하지 못한다).
    structure = _structure()
    tampered_policy = _policy(**{field: "sha256:otherproof"})
    result = qualify_and_compile_execution(
        captured=_captured(structure, policy=tampered_policy),
        composition_result=_passed(structure),
    )
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == COMPOSITION_POLICY_IDENTITY_MISMATCH


def test_semantic_payload_is_deeply_immutable():
    structure = _structure()
    result = _compile(structure)
    assert isinstance(result, QualifiedExecutionCompilation)
    payload = result.execution_basis_semantic_payload
    # 바깥·nested mapping 재바인딩 불가.
    with pytest.raises(TypeError):
        payload["effective_selection"]["slot_mode"] = "TAMPERED"  # type: ignore[index]
    # nested list 는 tuple 로 얼려 append 불가.
    assert isinstance(payload["effective_selection"]["selections"], tuple)
    assert isinstance(payload["ordered_operations"], tuple)
    with pytest.raises(AttributeError):
        payload["ordered_operations"].append({})  # type: ignore[attr-defined]


def test_slot_mode_mismatch_fail_closed():
    # SLOTLESS selection 이 slot 있는 structure 와 결합되면 mode mismatch.
    structure = _structure()
    result = _compile(structure, selection=_slotless_selection(structure))
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == SLOT_MODE_MISMATCH
    # 반대로 SLOTTED snapshot(=SlotConfigurationSnapshot)이 slot 0 structure 와 결합돼도 mismatch.
    slotless = _slotless_structure()
    effective = SlotSelectionSet(())
    snap = SlotConfigurationSnapshot(
        work_id=WORK,
        template_application_id=APP,
        source_configuration_version=1,
        selection_semantic_contract_id=CONTRACT,
        structure_projection_schema_version=EXECUTION_STRUCTURE_PROJECTION_SCHEMA,
        effective_selections=effective,
        effective_selection_digest=digest_selection_set(CONTRACT, effective),
        declared_selection_digest=digest_selection_set(CONTRACT, effective),
        template_structure_digest=template_structure_digest(slotless),
        captured_at=AT,
    )
    r2 = qualify_and_compile_execution(
        captured=_captured(
            slotless,
            selection=snap,
            binding=_binding(slotless, rules=(_rules()[0],), schema_keys=("이름",)),
        ),
        composition_result=_passed(slotless),
    )
    assert isinstance(r2, ExecutionCompilationContextError)
    assert r2.code == SLOT_MODE_MISMATCH


def test_selection_structure_digest_mismatch():
    import dataclasses

    structure = _structure()
    # selection 이 다른 structure digest 를 주장하면(qualification 과 불일치) fail-closed.
    wrong = dataclasses.replace(_snapshot(structure), template_structure_digest="sha256:0000")
    result = _compile(structure, selection=wrong)
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == SELECTION_STRUCTURE_DIGEST_MISMATCH


def test_selection_digest_tamper_context_error():
    structure = _structure()
    good = _snapshot(structure)
    # effective_selection_digest 를 위조한 snapshot → project_effective_selection recompute 로 거절.
    import dataclasses

    tampered = dataclasses.replace(good, effective_selection_digest="sha256:deadbeef")
    result = _compile(structure, selection=tampered)
    assert isinstance(result, ExecutionCompilationContextError)
    assert result.code == SELECTION_CONTRACT_INTEGRITY_ERROR


# ══ effective-only currentness ════════════════════════════════════════════════════
def _digest(structure, **over):
    r = _compile(structure, **over)
    assert isinstance(r, QualifiedExecutionCompilation)
    return r.execution_basis_semantic_digest


def test_detached_only_selection_basis_invariant():
    structure = _structure()
    base = _digest(structure, selection=_snapshot(structure, selected="o1"))
    detached = _digest(structure, selection=_snapshot(structure, selected="o1", detached="o2"))
    assert base == detached


def test_config_version_only_basis_invariant():
    structure = _structure()
    base = _digest(structure, selection=_snapshot(structure, config_version=1))
    other = _digest(structure, selection=_snapshot(structure, config_version=99))
    assert base == other


def test_unused_source_key_basis_invariant():
    structure = _structure()
    base = _digest(structure, binding=_binding(structure, schema_keys=("이름", "금액열", "unused")))
    more = _digest(structure, binding=_binding(structure, schema_keys=("이름", "금액열", "unused", "extra2")))
    assert base == more


def test_inactive_binding_change_basis_invariant():
    structure = _structure()
    base = _digest(structure, selection=_snapshot(structure, selected="o1"))
    # 금액(o2 inactive)의 constant 로 kind 를 바꿔도 active basis 불변.
    rules = tuple(
        FieldBindingRule(
            field_id="금액",
            binding_kind=CONSTANT,
            document_content_value_policy=DOCUMENT_CONTENT_VALUE_POLICY_V1,
            canonical_constant_value=ExactText("변경됨"),
        )
        if r.field_id == "금액"
        else r
        for r in _rules()
    )
    changed = _digest(
        structure,
        selection=_snapshot(structure, selected="o1"),
        binding=_binding(structure, rules=rules),
    )
    assert base == changed


def test_active_semantic_change_alters_basis():
    structure = _structure()
    base = _digest(structure)
    # active 성명 의 source_key(=required key) 변경은 basis 를 바꾼다.
    changed = _digest(
        structure, binding=_binding(structure, rules=_rules(name_key="금액열"), schema_keys=("금액열",))
    )
    assert base != changed


# ══ no forbidden work(source purity 게이트) ═══════════════════════════════════════
def test_module_imports_no_native_or_io():
    src = Path("src/hwpxfiller/application/execution_compilation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    forbidden = ("hwpxcore", "zipfile", "lxml", "os", "pathlib", "hwpxfiller.external", "hwpxfiller.host")
    for name in imported:
        assert not any(name == f or name.startswith(f + ".") for f in forbidden), name
    # reader/filename/parser/remover/writer/serializer 심볼도 실제 코드(주석·docstring 밖)에 없다 —
    # AST identifier 로 검사해 산문 충돌을 피한다.
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for spy in ("read_data_sheet", "resolve_filename", "HwpxPackage", "serialize", "clone", "_exit"):
        assert spy not in identifiers
