"""effective content·Active Field·deterministic operation compiler (S5-05 · #701).

S5-02(:mod:`hwpxfiller.application.execution_capture`)의 exact
:class:`CapturedExecutionInput`, S5-03 의 exact :class:`ExecutionTemplateStructure`,
S5-04 의 :class:`CompositionPremisesPassed` 를 **그대로 조합**해, 이번 실행에 살아남는
effective content 와 Active Field 를 순수하게 계산하고 deterministic
``RemoveOption + ApplyFieldBinding`` operation sequence 와 ``ActiveFieldRequirement`` 를
compile 한다.

경계(issue #701):
- **native mutation 0**. HWPX parse/clone/serialize/remove/write·resolver 실행·row 값 읽기·
  filename 계산을 하지 않는다(그래서 이 모듈은 hwpxcore/native/store 를 import 하지 않는다).
- **actual record value 미검사**. source 값의 존재/형식은 S5-12 VDR 소유. 여기서는 Active
  logical Field 의 binding *규칙* 만 qualification 한다.
- **fail-closed**. composition premise 가 PASS 아니면 operation 을 내지 않는다. unknown
  selection·structure mismatch 는 latest 로 fallback 하지 않고 context error 로 닫힌다.
  context/integrity/composition 오류를 user-fixable blocker 로 낮추지 않는다.
- **effective-only currentness**. detached selection·inactive binding·unused source key·
  authority/config version-only 변경은 execution basis semantic payload 를 바꾸지 않는다 —
  effective 의미만 payload 에 투영한다(provenance 제외).

operation order 는 **product structure 순서**(Slot·Option 선언 순서)와 occurrence 의
**structural_order**(S5-03 이 고정한 stable projection fact)만 쓴다 — live native package
traversal 에 의존하지 않는다.

digest seam: byte framing·SHA-256 은 S5-06 closed canonical set
(:mod:`hwpxfiller.domain.canonical_execution_encoding`). 여기서는 semantic payload + stable
ordering 을 고정하고 그 canonical encoder 로 주소화한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from hwpxfiller.application.execution_capture import (
    SLOT_CONFIGURATION_INCOMPLETE,
    CapturedExecutionInput,
    EffectiveSelectionBasis,
    ExactTemplateExecutionBasis,
    ExecutionCaptureIntegrityError,
    build_exact_execution_basis,
    project_effective_selection,
)
from hwpxfiller.application.execution_composition import (
    CompositionPremiseVerificationResult,
    CompositionPremisesPassed,
)
from hwpxfiller.application.execution_structure import (
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    ExecutionTemplateStructure,
    FieldOccurrence,
)
from hwpxfiller.application.slot_selection_input import (
    SlotConfigurationSnapshot,
    SlotlessSelectionContext,
)
from hwpxfiller.domain.canonical_execution_encoding import canonical_execution_digest
from hwpxfiller.domain.field_binding import (
    CONSTANT,
    EXACT_BLANK_POLICY,
    SOURCE,
    CanonicalBindingValue,
    CanonicalBoolean,
    CanonicalDate,
    CanonicalDateTime,
    CanonicalDecimal,
    ExactText,
    FieldBindingRule,
    value_type_of,
)

EXECUTION_SEMANTICS_CONTRACT = "execution-semantics/v1"
OPERATION_ALPHABET_VERSION = "execution-operation-alphabet/v1"

# ─── user-fixable Active qualification blocker 어휘 ─────────────────────────────────
ACTIVE_FIELD_UNBOUND = "ACTIVE_FIELD_UNBOUND"
ACTIVE_FIELD_BINDING_AMBIGUOUS = "ACTIVE_FIELD_BINDING_AMBIGUOUS"
ACTIVE_FIELD_BINDING_CONFLICT = "ACTIVE_FIELD_BINDING_CONFLICT"
REQUIRED_SOURCE_KEY_MISSING = "REQUIRED_SOURCE_KEY_MISSING"
UNSUPPORTED_FIELD_BINDING_RULE = "UNSUPPORTED_FIELD_BINDING_RULE"
UNSUPPORTED_FIELD_VALUE_TYPE = "UNSUPPORTED_FIELD_VALUE_TYPE"
UNSUPPORTED_DOCUMENT_VALUE_POLICY = "UNSUPPORTED_DOCUMENT_VALUE_POLICY"
NEEDS_CONFIGURATION_REVIEW = "NEEDS_CONFIGURATION_REVIEW"
NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
NEEDS_BINDING_SEMANTIC_MIGRATION = "NEEDS_BINDING_SEMANTIC_MIGRATION"
NEEDS_FIELD_BINDING_APPLICATION_REVIEW = "NEEDS_FIELD_BINDING_APPLICATION_REVIEW"

# 정규화 시 deterministic 우선순위(issue blocker 열거 순서).
_BLOCKER_PRIORITY = (
    ACTIVE_FIELD_UNBOUND,
    ACTIVE_FIELD_BINDING_AMBIGUOUS,
    ACTIVE_FIELD_BINDING_CONFLICT,
    REQUIRED_SOURCE_KEY_MISSING,
    UNSUPPORTED_FIELD_BINDING_RULE,
    UNSUPPORTED_FIELD_VALUE_TYPE,
    UNSUPPORTED_DOCUMENT_VALUE_POLICY,
    SLOT_CONFIGURATION_INCOMPLETE,
    NEEDS_CONFIGURATION_REVIEW,
    NEEDS_CONFIGURATION,
    NEEDS_BINDING_SEMANTIC_MIGRATION,
    NEEDS_FIELD_BINDING_APPLICATION_REVIEW,
)
_BLOCKER_PRIORITY_INDEX = {code: i for i, code in enumerate(_BLOCKER_PRIORITY)}

# ─── context error 어휘(user-fixable 로 낮추지 않는 fail-closed 실패) ──────────────────
COMPOSITION_PREMISES_NOT_PASSED = "COMPOSITION_PREMISES_NOT_PASSED"
COMPOSITION_STRUCTURE_MISMATCH = "COMPOSITION_STRUCTURE_MISMATCH"
COMPOSITION_POLICY_IDENTITY_MISMATCH = "COMPOSITION_POLICY_IDENTITY_MISMATCH"
SELECTION_CONTRACT_INTEGRITY_ERROR = "SELECTION_CONTRACT_INTEGRITY_ERROR"
SELECTION_STRUCTURE_DIGEST_MISMATCH = "SELECTION_STRUCTURE_DIGEST_MISMATCH"
SLOT_MODE_MISMATCH = "SLOT_MODE_MISMATCH"
UNKNOWN_SELECTION_TARGET = "UNKNOWN_SELECTION_TARGET"


class ExecutionCompilationError(ValueError):
    """compiler 내부 무결성 위반(bijection 등) — result 합타입이 아닌 예외."""


# ─── value expression 합타입(actual value 아님 — 규칙의 exact projection) ──────────────
@dataclass(frozen=True)
class FromSource:
    source_key: str
    value_type: str
    format_code: str | None
    document_content_value_policy_id: str


@dataclass(frozen=True)
class ConstantValue:
    canonical_value: CanonicalBindingValue
    format_code: str | None
    document_content_value_policy_id: str


@dataclass(frozen=True)
class IntentionalBlank:
    exact_blank_policy: str = EXACT_BLANK_POLICY


ActiveFieldValueExpression = FromSource | ConstantValue | IntentionalBlank


# ─── Active Field projection(중복 정본 없음 — 하나의 projection) ────────────────────────
@dataclass(frozen=True)
class ActiveFieldProjection:
    """occurrence order view + first-occurrence logical order view.

    occurrence count 는 여기 담지 않는다 — :class:`ActiveFieldRequirement` 한 곳만 소유한다.
    """

    active_field_sequence: tuple[str, ...]
    active_logical_field_order: tuple[str, ...]


@dataclass(frozen=True)
class ActiveFieldRequirement:
    """Active logical Field 하나의 축약 requirement — 모든 occurrence 가 같은 logical value 를 받는다."""

    field_id: str
    expected_active_occurrence_count: int
    value_expression: ActiveFieldValueExpression


# ─── operation alphabet v1 ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RemoveOption:
    slot_id: str
    option_id: str


@dataclass(frozen=True)
class ApplyFieldBinding:
    field_id: str


ExecutionOperation = RemoveOption | ApplyFieldBinding


# ─── EffectiveFieldBindingBasis ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class EffectiveFieldBindingRule:
    field_id: str
    binding_kind: str
    value_expression: ActiveFieldValueExpression


@dataclass(frozen=True)
class EffectiveFieldBindingBasis:
    """inactive Field binding·unused source key·Mapping 이름·경로·authority revision 을 제외한 basis."""

    effective_active_binding_rules: tuple[EffectiveFieldBindingRule, ...]
    active_binding_digest: str
    required_source_keys: tuple[str, ...]
    required_source_key_set_digest: str


@dataclass(frozen=True)
class CompositionVerificationRef:
    composition_contract_id: str
    native_primitive_contract_id: str
    template_structure_digest: str
    theorem_evidence_manifest_digest: str
    premise_verification_digest: str


# ─── blocker / result 합타입 ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class QualificationBlocker:
    code: str
    field_id: str | None
    detail: str


@dataclass(frozen=True)
class ExecutionQualificationBlocked:
    """사용자가 Active Field binding/구성을 고치면 풀리는 blocker 집합(deterministic 정규화)."""

    normalized_blockers: tuple[QualificationBlocker, ...]


@dataclass(frozen=True)
class ExecutionCompilationContextError:
    """평가 자체 불가 — composition 미증명·structure/selection 불일치·integrity 실패(fail-closed)."""

    code: str
    detail: str


@dataclass(frozen=True)
class QualifiedExecutionCompilation:
    """record·output·native 없이 완성된 record-independent document execution meaning."""

    exact_template_execution_basis: ExactTemplateExecutionBasis
    effective_selection_basis: EffectiveSelectionBasis
    effective_field_binding_basis: EffectiveFieldBindingBasis
    composition_verification_ref: CompositionVerificationRef
    active_field_projection: ActiveFieldProjection
    active_field_requirements: tuple[ActiveFieldRequirement, ...]
    ordered_operations: tuple[ExecutionOperation, ...]
    execution_basis_semantic_payload: Mapping[str, Any]
    # byte framing·SHA-256 은 S5-06 closed canonical set(domain.canonical_execution_encoding).
    execution_basis_semantic_digest: str


QualifyAndCompileExecutionResult = (
    QualifiedExecutionCompilation
    | ExecutionQualificationBlocked
    | ExecutionCompilationContextError
)


# ─── value expression 유도 ──────────────────────────────────────────────────────────
def _value_expression(rule: FieldBindingRule) -> ActiveFieldValueExpression:
    """FieldBindingRule → value expression. rule 은 이미 kind exclusivity·contract 를 검증했다."""
    policy_id = rule.document_content_value_policy.policy_id
    if rule.binding_kind == SOURCE:
        # SOURCE 규칙은 source_key·value_type 를 반드시 갖는다(FieldBindingRule 이 강제).
        assert rule.source_key is not None and rule.value_type is not None
        return FromSource(rule.source_key, rule.value_type, rule.format_code, policy_id)
    if rule.binding_kind == CONSTANT:
        assert rule.canonical_constant_value is not None
        return ConstantValue(rule.canonical_constant_value, rule.format_code, policy_id)
    return IntentionalBlank()  # INTENTIONAL_BLANK(BINDING_KINDS 소진)


def _is_active(occ: FieldOccurrence, selected: frozenset[tuple[str, str]]) -> bool:
    if occ.owner_kind in (OWNER_ROOT, OWNER_SLOT_SHARED):
        return True
    # OWNER_OPTION — selected Option 의 Field 만 active.
    return (occ.owner_slot_id, occ.owner_option_id) in selected  # type: ignore[comparison-overlap]


# ─── selected Option 해석(SLOTTED)·structure integrity 방어 ────────────────────────────
def _resolve_selected(
    structure: ExecutionTemplateStructure,
    selection: SlotConfigurationSnapshot,
) -> tuple[
    frozenset[tuple[str, str]],
    tuple[QualificationBlocker, ...],
    ExecutionCompilationContextError | None,
]:
    """effective_selections 를 exact Structure 로 방어한다.

    unknown Slot/Option 참조 → context error(integrity). Structure Slot 마다 selected Option 이
    정확히 하나가 아니면 → SLOT_CONFIGURATION_INCOMPLETE blocker(user-fixable).
    """
    product = structure.product_structure
    slot_ids = {slot.id for slot in product.slots}
    option_ids = {
        (slot.id, opt.id) for slot in product.slots for opt in slot.options
    }
    sel_map: dict[str, tuple[str, ...]] = {}
    for sel in selection.effective_selections.selections:
        if sel.slot_id not in slot_ids:
            return (
                frozenset(),
                (),
                ExecutionCompilationContextError(
                    UNKNOWN_SELECTION_TARGET,
                    f"selection 이 Structure 밖 Slot 을 참조: {sel.slot_id!r}",
                ),
            )
        for option_id in sel.selected_option_ids:
            if (sel.slot_id, option_id) not in option_ids:
                return (
                    frozenset(),
                    (),
                    ExecutionCompilationContextError(
                        UNKNOWN_SELECTION_TARGET,
                        f"selection 이 Structure 밖 Option 을 참조: "
                        f"({sel.slot_id!r}, {option_id!r})",
                    ),
                )
        sel_map[sel.slot_id] = sel.selected_option_ids

    selected: set[tuple[str, str]] = set()
    blockers: list[QualificationBlocker] = []
    for slot in product.slots:
        chosen = sel_map.get(slot.id)
        if chosen is None or len(chosen) != 1:
            blockers.append(
                QualificationBlocker(
                    SLOT_CONFIGURATION_INCOMPLETE,
                    None,
                    f"Slot {slot.id!r} 에 selected Option 이 정확히 하나가 아니다",
                )
            )
            continue
        selected.add((slot.id, chosen[0]))
    return frozenset(selected), tuple(blockers), None


def _active_projection(
    structure: ExecutionTemplateStructure, selected: frozenset[tuple[str, str]]
) -> tuple[ActiveFieldProjection, dict[str, int]]:
    """occurrence(structural_order)·first-occurrence logical order·occurrence count 를 계산한다."""
    active = sorted(
        (occ for occ in structure.field_occurrences if _is_active(occ, selected)),
        key=lambda o: o.structural_order,
    )
    sequence = tuple(occ.field_id for occ in active)
    logical: list[str] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for field_id in sequence:
        counts[field_id] = counts.get(field_id, 0) + 1
        if field_id not in seen:
            seen.add(field_id)
            logical.append(field_id)
    return ActiveFieldProjection(sequence, tuple(logical)), counts


# ─── requirement ↔ operation bijection validator ────────────────────────────────────
def verify_requirement_operation_bijection(
    requirements: tuple[ActiveFieldRequirement, ...],
    apply_operations: tuple[ApplyFieldBinding, ...],
) -> None:
    """각 requirement ↔ 정확히 하나의 ApplyFieldBinding(inactive 0·duplicate 0·missing/extra 0)."""
    req_fields = [r.field_id for r in requirements]
    op_fields = [op.field_id for op in apply_operations]
    if len(set(req_fields)) != len(req_fields):
        raise ExecutionCompilationError("requirement field 중복")
    if len(set(op_fields)) != len(op_fields):
        raise ExecutionCompilationError("ApplyFieldBinding field 중복")
    if req_fields != op_fields:
        raise ExecutionCompilationError(
            "requirement ↔ ApplyFieldBinding bijection 위반(집합·순서 불일치)"
        )


# ─── canonical semantic payload + digest seam ────────────────────────────────────────
def _encode_canonical_value(value: CanonicalBindingValue) -> dict[str, Any]:
    vt = value_type_of(value)
    if isinstance(value, ExactText):
        literal: Any = value.text
    elif isinstance(value, CanonicalDecimal):
        literal = value.literal
    elif isinstance(value, CanonicalDate):
        literal = value.iso
    elif isinstance(value, CanonicalDateTime):
        literal = value.iso
    else:  # CanonicalBoolean(합타입 소진)
        literal = value.value
    return {"value_type": vt, "literal": literal}


def _encode_value_expression(ve: ActiveFieldValueExpression) -> dict[str, Any]:
    if isinstance(ve, FromSource):
        return {
            "kind": "FROM_SOURCE",
            "source_key": ve.source_key,
            "value_type": ve.value_type,
            "format_code": ve.format_code,
            "document_content_value_policy_id": ve.document_content_value_policy_id,
        }
    if isinstance(ve, ConstantValue):
        return {
            "kind": "CONSTANT",
            "canonical_value": _encode_canonical_value(ve.canonical_value),
            "format_code": ve.format_code,
            "document_content_value_policy_id": ve.document_content_value_policy_id,
        }
    return {"kind": "INTENTIONAL_BLANK", "exact_blank_policy": ve.exact_blank_policy}


def _encode_operation(op: ExecutionOperation) -> dict[str, Any]:
    if isinstance(op, RemoveOption):
        return {"op": "REMOVE_OPTION", "slot_id": op.slot_id, "option_id": op.option_id}
    return {"op": "APPLY_FIELD_BINDING", "field_id": op.field_id}


def active_binding_digest(rules: tuple[EffectiveFieldBindingRule, ...]) -> str:
    """effective active binding 규칙의 content-address(S5-06 closed canonical framing).

    저장/제시 순서가 아니라 field_id 정렬로 identity — 순서 perturbation 에 불변. S5-06 decode
    verification 이 EffectiveFieldBindingBasis.active_binding_digest 를 이 함수로 재계산·대조한다.
    """
    payload = sorted(
        (
            {
                "field_id": r.field_id,
                "binding_kind": r.binding_kind,
                "value_expression": _encode_value_expression(r.value_expression),
            }
            for r in rules
        ),
        key=lambda d: d["field_id"],
    )
    return canonical_execution_digest(payload)


def required_source_key_set_digest(keys: tuple[str, ...]) -> str:
    """required source key set 의 content-address — unsigned UTF-8 byte order(순서 무관)."""
    return canonical_execution_digest(sorted(keys, key=lambda k: k.encode("utf-8")))


def _exact_basis_semantic(captured: CapturedExecutionInput) -> dict[str, Any]:
    """issue ExactTemplateExecutionBasis field 집합 — provenance(captured_at·경로·blob address·
    field_binding_authority_revision·config version) 제외.
    """
    applied = captured.template.applied
    qual = captured.template.qualification
    policy = captured.resolved_seal_policy
    return {
        "execution_base_kind": policy.execution_base_kind,
        "materialization_base_contract_id": policy.materialization_base_contract_id,
        "work_authority_id": captured.work_authority_id,
        "template_application_id": applied.template_application_id,
        "template_lineage_id": applied.template_lineage_id,
        "revision_id": applied.revision_id,
        "media": applied.media,
        "exact_content_digest": applied.exact_content_digest,
        "pass_evidence_id": qual.pass_evidence_id,
        "qualification_profile_id": qual.qualification_profile_id,
        "structure_projection_schema_version": (
            qual.structure_projection_schema_version
        ),
        "template_structure_digest": qual.template_structure_digest,
    }


def _build_semantic_payload(
    *,
    captured: CapturedExecutionInput,
    slot_mode: str,
    effective_selections: tuple[tuple[str, str], ...],
    binding_basis: EffectiveFieldBindingBasis,
    requirements: tuple[ActiveFieldRequirement, ...],
    ordered_operations: tuple[ExecutionOperation, ...],
    composition_ref: CompositionVerificationRef,
) -> dict[str, Any]:
    """effective 의미만 담는 execution basis semantic payload(effective-only currentness).

    제외: captured_at·source_configuration_version·field_binding_authority_revision·
    declared_selection_digest·canonical_blob_reference·Data Source path·Mapping display name·
    UI/store order. 포함: exact template basis·effective selection·active binding·requirement·
    ordered operation·composition ref.
    """
    return {
        "execution_semantics_contract": EXECUTION_SEMANTICS_CONTRACT,
        "operation_alphabet_version": OPERATION_ALPHABET_VERSION,
        "exact_template_execution_basis": _exact_basis_semantic(captured),
        "effective_selection": {
            "slot_mode": slot_mode,
            "selections": [
                {"slot_id": s, "selected_option_id": o}
                for s, o in effective_selections
            ],
        },
        "effective_field_binding": {
            "active_binding_digest": binding_basis.active_binding_digest,
            "required_source_keys": list(binding_basis.required_source_keys),
            "required_source_key_set_digest": (
                binding_basis.required_source_key_set_digest
            ),
            "active_binding_rules": sorted(
                (
                    {
                        "field_id": r.field_id,
                        "binding_kind": r.binding_kind,
                        "value_expression": _encode_value_expression(
                            r.value_expression
                        ),
                    }
                    for r in binding_basis.effective_active_binding_rules
                ),
                key=lambda d: d["field_id"],
            ),
        },
        "active_field_requirements": sorted(
            (
                {
                    "field_id": r.field_id,
                    "expected_active_occurrence_count": (
                        r.expected_active_occurrence_count
                    ),
                    "value_expression": _encode_value_expression(r.value_expression),
                }
                for r in requirements
            ),
            key=lambda d: d["field_id"],
        ),
        "ordered_operations": [_encode_operation(op) for op in ordered_operations],
        "composition_verification_ref": {
            "composition_contract_id": composition_ref.composition_contract_id,
            "native_primitive_contract_id": (
                composition_ref.native_primitive_contract_id
            ),
            "template_structure_digest": composition_ref.template_structure_digest,
            "theorem_evidence_manifest_digest": (
                composition_ref.theorem_evidence_manifest_digest
            ),
            "premise_verification_digest": (
                composition_ref.premise_verification_digest
            ),
        },
    }


def _deep_freeze(value: Any) -> Any:
    """JSON-safe payload 를 재귀적으로 얼린다(dict→MappingProxyType, list→tuple).

    바깥 MappingProxyType 만으로는 nested dict/list 변이를 못 막는다 — content-addressed
    payload 가 return 뒤 조용히 바뀌면 digest 가 stale 해진다(S5-03/04 와 같은 규율).
    """
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


def _normalize_blockers(
    blockers: list[QualificationBlocker],
) -> tuple[QualificationBlocker, ...]:
    """(code, field_id) 로 dedup 하고 deterministic 우선순위·field_id·detail 로 정렬한다."""
    unique: dict[tuple[str, str | None], QualificationBlocker] = {}
    for blocker in blockers:
        unique.setdefault((blocker.code, blocker.field_id), blocker)
    return tuple(
        sorted(
            unique.values(),
            key=lambda b: (
                _BLOCKER_PRIORITY_INDEX.get(b.code, len(_BLOCKER_PRIORITY)),
                b.field_id or "",
                b.detail,
            ),
        )
    )


# ─── 주 진입점 ──────────────────────────────────────────────────────────────────────
def qualify_and_compile_execution(
    *,
    captured: CapturedExecutionInput,
    composition_result: CompositionPremiseVerificationResult,
) -> QualifyAndCompileExecutionResult:
    """exact capture + structure + composition PASS → compile(순수·deterministic).

    precedence: (1) exact input integrity → (4) composition premise → (5) user-fixable Active
    qualification blocker → (6) deterministic compilation. context/integrity/composition 실패는
    user-fixable blocker 로 낮추지 않는다.
    """
    structure = captured.template.qualification.execution_structure
    structure_digest = captured.template.qualification.template_structure_digest

    # (4) composition gate — PASS 가 아니면 operation 을 내지 않는다(fail-closed).
    if not isinstance(composition_result, CompositionPremisesPassed):
        premise = getattr(composition_result, "premise_id", None)
        reason = getattr(composition_result, "reason", str(composition_result))
        return ExecutionCompilationContextError(
            COMPOSITION_PREMISES_NOT_PASSED,
            f"composition premise 미증명({type(composition_result).__name__}, "
            f"premise={premise}): {reason}",
        )
    # composition 결과가 이 structure 에 결속됨을 recompute 로 확인(주장 신뢰 금지).
    if composition_result.template_structure_digest != structure_digest:
        return ExecutionCompilationContextError(
            COMPOSITION_STRUCTURE_MISMATCH,
            "composition premise 가 이 template structure 와 다른 digest 에 결속됨",
        )
    # proof 가 capture 가 admit 한 exact policy 에 결속됨을 확인한다 — 다른 composition/native
    # primitive contract·theorem evidence 로 증명된 PASS 가 operation 을 authorize 하지 못하게
    # 세 identity 를 전부 대조한다(fail-closed).
    policy = captured.resolved_seal_policy
    proof_identity = (
        composition_result.composition_contract_id,
        composition_result.native_primitive_contract_id,
        composition_result.theorem_evidence_manifest_digest,
    )
    admitted_identity = (
        policy.composition_contract_id,
        policy.native_primitive_contract_id,
        policy.composition_theorem_evidence_manifest_digest,
    )
    if proof_identity != admitted_identity:
        return ExecutionCompilationContextError(
            COMPOSITION_POLICY_IDENTITY_MISMATCH,
            "composition proof 의 contract/native-primitive/theorem-evidence identity 가 "
            "admitted resolved_seal_policy 와 불일치",
        )

    # (1) selection projection — claimed effective/selection digest 를 recompute·대조한다.
    try:
        effective_selection_basis = project_effective_selection(captured.selection)
    except ExecutionCaptureIntegrityError as exc:
        return ExecutionCompilationContextError(
            SELECTION_CONTRACT_INTEGRITY_ERROR, str(exc)
        )
    if effective_selection_basis.template_structure_digest != structure_digest:
        return ExecutionCompilationContextError(
            SELECTION_STRUCTURE_DIGEST_MISMATCH,
            "selection 의 template_structure_digest 가 qualification structure 와 불일치",
        )

    has_slots = len(structure.product_structure.slots) > 0
    selection = captured.selection

    # slot_mode ↔ structure slot count 정합(변형과 structure 가 어긋나면 exact input 아님).
    if isinstance(selection, SlotConfigurationSnapshot):
        if not has_slots:
            return ExecutionCompilationContextError(
                SLOT_MODE_MISMATCH,
                "SLOTTED selection 이 slot 0 structure 와 결합됨",
            )
        selected, slot_blockers, ctx_err = _resolve_selected(structure, selection)
        if ctx_err is not None:
            return ctx_err
    elif isinstance(selection, SlotlessSelectionContext):
        if has_slots:
            return ExecutionCompilationContextError(
                SLOT_MODE_MISMATCH,
                "SLOTLESS selection 이 slot 있는 structure 와 결합됨",
            )
        selected, slot_blockers = frozenset(), ()
    else:  # pragma: no cover - SlotSelectionInput 합타입 소진
        return ExecutionCompilationContextError(
            SELECTION_CONTRACT_INTEGRITY_ERROR,
            f"미지원 SlotSelectionInput variant: {type(selection).__name__}",
        )

    # Active Field projection(occurrence·logical order·count).
    projection, counts = _active_projection(structure, selected)

    # (5) Active-only Binding Qualification.
    rules_by_field = {r.field_id: r for r in captured.field_binding.binding_rules}
    schema_keys = set(captured.field_binding.source_schema_keys)
    requirements: list[ActiveFieldRequirement] = []
    effective_rules: list[EffectiveFieldBindingRule] = []
    required_source_keys: set[str] = set()
    binding_blockers: list[QualificationBlocker] = []
    for field_id in projection.active_logical_field_order:
        rule = rules_by_field.get(field_id)
        if rule is None:
            binding_blockers.append(
                QualificationBlocker(
                    ACTIVE_FIELD_UNBOUND,
                    field_id,
                    f"Active Field {field_id!r} 에 effective binding 이 없다",
                )
            )
            continue
        value_expression = _value_expression(rule)
        if isinstance(value_expression, FromSource):
            if value_expression.source_key not in schema_keys:
                binding_blockers.append(
                    QualificationBlocker(
                        REQUIRED_SOURCE_KEY_MISSING,
                        field_id,
                        f"source_key {value_expression.source_key!r} 가 source schema 에 없다",
                    )
                )
                continue
            required_source_keys.add(value_expression.source_key)
        requirements.append(
            ActiveFieldRequirement(field_id, counts[field_id], value_expression)
        )
        effective_rules.append(
            EffectiveFieldBindingRule(field_id, rule.binding_kind, value_expression)
        )

    all_blockers = list(slot_blockers) + binding_blockers
    if all_blockers:
        return ExecutionQualificationBlocked(_normalize_blockers(all_blockers))

    # (6) deterministic compilation.
    slot_index = {slot.id: i for i, slot in enumerate(structure.product_structure.slots)}
    option_index = {
        (slot.id, opt.id): j
        for slot in structure.product_structure.slots
        for j, opt in enumerate(slot.options)
    }
    remove_ops = tuple(
        RemoveOption(region.slot_id, region.option_id)
        for region in sorted(
            (
                r
                for r in structure.option_regions
                if (r.slot_id, r.option_id) not in selected
            ),
            key=lambda r: (slot_index[r.slot_id], option_index[(r.slot_id, r.option_id)]),
        )
    )
    apply_ops = tuple(
        ApplyFieldBinding(field_id)
        for field_id in projection.active_logical_field_order
    )
    ordered_operations: tuple[ExecutionOperation, ...] = remove_ops + apply_ops

    requirements_t = tuple(requirements)
    verify_requirement_operation_bijection(requirements_t, apply_ops)

    effective_pairs = tuple(sorted(selected))
    binding_basis = EffectiveFieldBindingBasis(
        effective_active_binding_rules=tuple(effective_rules),
        active_binding_digest=active_binding_digest(tuple(effective_rules)),
        required_source_keys=tuple(
            sorted(required_source_keys, key=lambda k: k.encode("utf-8"))
        ),
        required_source_key_set_digest=required_source_key_set_digest(
            tuple(required_source_keys)
        ),
    )
    composition_ref = CompositionVerificationRef(
        composition_contract_id=composition_result.composition_contract_id,
        native_primitive_contract_id=composition_result.native_primitive_contract_id,
        template_structure_digest=composition_result.template_structure_digest,
        theorem_evidence_manifest_digest=(
            composition_result.theorem_evidence_manifest_digest
        ),
        premise_verification_digest=composition_result.premise_verification_digest,
    )
    slot_mode = effective_selection_basis.slot_mode
    payload = _build_semantic_payload(
        captured=captured,
        slot_mode=slot_mode,
        effective_selections=effective_pairs,
        binding_basis=binding_basis,
        requirements=requirements_t,
        ordered_operations=ordered_operations,
        composition_ref=composition_ref,
    )
    return QualifiedExecutionCompilation(
        exact_template_execution_basis=build_exact_execution_basis(
            captured.template, captured.resolved_seal_policy
        ),
        effective_selection_basis=effective_selection_basis,
        effective_field_binding_basis=binding_basis,
        composition_verification_ref=composition_ref,
        active_field_projection=projection,
        active_field_requirements=requirements_t,
        ordered_operations=ordered_operations,
        # digest 는 raw dict 에서, 노출은 deep-frozen 사본으로(return 뒤 변이 불가).
        execution_basis_semantic_payload=_deep_freeze(payload),
        execution_basis_semantic_digest=canonical_execution_digest(payload),
    )
