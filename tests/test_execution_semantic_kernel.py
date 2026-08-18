"""S5F-01(#740 R1) execution semantic kernel — control-plane 밖 순수 실행 의미 계산.

이 테스트가 증명하는 것(그리고 오직 이것만):
  1. 같은 exact durable authority → 같은 execution meaning(결정적).
  2. effective meaning 변경(선택 Option) → Active Field/operations 가 정확히 변경.
  3. C1~C10 위반 → fail-closed(Plan 을 내지 않는다).
  4. durable Plan store 없이도 durable authority 에서 Plan 재계산 가능.
  + parity: kernel 산출 semantic 은 기존 검증된 capture+compile seam 과 동일하다
    (비교 대상: exact Candidate·effective content·Active Fields·ordered operations·
     composition verdict·실행 최소 contract semantics. 비교 대상 아님: plan digest·request id·
     first-seen history·theorem evidence digest·Profile admission state·store ref).

fixture 는 기존 pure-path 테스트(:mod:`tests.test_execution_compilation`)의 native-free builder 를
그대로 재사용한다 — 새 fixture 체계를 세우지 않는다. policy 는 compile 이 요구하는 supported
plan schema·canonical encoding 을 쓴다(compilation 테스트의 unsupported "plan/1" 이 아니다).
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.execution_capture import (
    CapturedExecutionInput,
    CapturedFieldBinding,
    CapturedSelection,
    ResolvedSealPolicy,
    judge_captured_execution,
)
from hwpxfiller.application.execution_capture import (
    APPLIED_TEMPLATE_CANDIDATE,
    MATERIALIZATION_BASE_CONTRACT_ID,
)
from hwpxfiller.application.execution_composition import (
    COMPOSITION_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_ID,
    NATIVE_PRIMITIVE_CONTRACT_V1,
    THEOREM_EVIDENCE_V1,
    CompositionPremisesBlocked,
    TheoremEvidenceRegistry,
    theorem_evidence_digest,
    verify_execution_composition_premises,
)
from hwpxfiller.application.execution_semantic_kernel import (
    DurableExecutionAuthority,
    SealedExecutionPlanBlocked,
    SealedExecutionPlanValue,
    SemanticKernelContextError,
    compute_execution_snapshot,
    compute_sealed_execution_plan,
)
from hwpxfiller.application.execution_structure import (
    OWNER_OPTION,
    OWNER_ROOT,
    OWNER_SLOT_SHARED,
    RESOLVER_STABILITY_KEYS,
    OptionRegionObservation,
    SlotRegionObservation,
    build_execution_structure,
)
from hwpxfiller.application.seal_execution_plan import (
    UnsupportedLocalImplementation,
    compile_candidate,
)
from hwpxfiller.application.template_qualification import (
    TemplateOption,
    TemplateSlot,
    TemplateStructure,
)
from hwpxfiller.domain.canonical_execution_encoding import CANONICAL_ENCODING_VERSION

from tests.test_execution_compilation import (
    APP,
    PROFILE,
    WORK,
    WS,
    _binding,
    _entry,
    _occ,
    _rules,
    _slotless_selection,
    _slotless_structure,
    _snapshot,
    _structure,
    _template,
)


def _policy(**over) -> ResolvedSealPolicy:
    """compile 이 요구하는 supported plan schema·encoding + registered composition identity."""
    kw = dict(
        policy_resolution_version="policy/v1",
        execution_base_kind=APPLIED_TEMPLATE_CANDIDATE,
        execution_semantic_contract_id="execution-semantics/v1",
        binding_value_contract_id="binding-value/v1",
        raw_record_contract_id="raw-record/v1",
        document_value_resolution_contract_id="document-content-value/v1",
        record_validation_contract_id="record-validation/v1",
        record_review_contract_id="record-review/v1",
        composition_contract_id=COMPOSITION_CONTRACT_ID,
        native_primitive_contract_id=NATIVE_PRIMITIVE_CONTRACT_ID,
        materialization_base_contract_id=MATERIALIZATION_BASE_CONTRACT_ID,
        composition_theorem_evidence_manifest_digest=theorem_evidence_digest(
            THEOREM_EVIDENCE_V1
        ),
        materialization_contract_id="materialization/v1",
        plan_schema_version="hwpx-execution-plan/v1",
        canonical_encoding_version=CANONICAL_ENCODING_VERSION,
    )
    kw.update(over)
    return ResolvedSealPolicy(**kw)


def _authority(structure, *, selected="o1", policy=None) -> DurableExecutionAuthority:
    """durable authority 하나 — store·fence 없이 exact DTO 만 담는다."""
    return DurableExecutionAuthority(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        expected_template_application_id=APP,
        expected_profile_id=PROFILE,
        resolved_seal_policy=policy if policy is not None else _policy(),
        template=_template(structure),
        selection=_snapshot(structure, selected=selected),
        field_binding=_binding(structure),
        captured_at="2026-08-18T00:00:00Z",
    )


def _broken_resolver_structure():
    """`_structure()` 와 동형이되 resolver stability fact 를 전부 깨 C1~C10 이 FAILED 되게 한다."""
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
            OptionRegionObservation("s1", "o1", "c0", 15, 20, "remove-option/v1"),
            OptionRegionObservation("s1", "o2", "c0", 25, 30, "remove-option/v1"),
        ),
        content_entries=(_entry(),),
        resolver_stability_facts={k: False for k in RESOLVER_STABILITY_KEYS},
        admitted_relation_profile="unadmitted",
    )


# ── 1. 결정적: 같은 authority → 같은 execution meaning ──────────────────────────────────
def test_same_authority_yields_same_execution_meaning():
    structure = _structure()
    a = compute_sealed_execution_plan(_authority(structure))
    b = compute_sealed_execution_plan(_authority(structure))
    assert isinstance(a, SealedExecutionPlanValue)
    assert a == b
    assert a.plan_payload == b.plan_payload
    assert a.execution_basis == b.execution_basis


# ── 2. effective meaning 변경 → Active Field/operations 정확히 변경 ─────────────────────
def test_effective_meaning_change_changes_active_fields_and_operations():
    structure = _structure()
    plan_o1 = compute_sealed_execution_plan(_authority(structure, selected="o1"))
    plan_o2 = compute_sealed_execution_plan(_authority(structure, selected="o2"))
    assert isinstance(plan_o1, SealedExecutionPlanValue)
    assert isinstance(plan_o2, SealedExecutionPlanValue)
    # 선택 Option 이 다르면 Active Field 와 ordered operations 가 달라진다(항목↔금액, 제거 대상 반전).
    assert plan_o1.active_field_requirements != plan_o2.active_field_requirements
    assert plan_o1.ordered_operations != plan_o2.ordered_operations
    # 실제로 활성 field 집합이 항목(o1) vs 금액(o2) 로 갈린다.
    fields_o1 = {r.get("field_id") for r in plan_o1.active_field_requirements}
    fields_o2 = {r.get("field_id") for r in plan_o2.active_field_requirements}
    assert "항목" in fields_o1 and "항목" not in fields_o2
    assert "금액" in fields_o2 and "금액" not in fields_o1


# ── 3. C1~C10 위반 → fail-closed(Plan 없음) ────────────────────────────────────────────
def test_composition_premise_violation_is_fail_closed():
    broken = _broken_resolver_structure()
    # self-validate: 실제로 C1~C10 premise 가 FAILED 인 structure 임을 raw verifier 로 못박는다.
    result = verify_execution_composition_premises(
        structure=broken,
        native_primitive_contract=NATIVE_PRIMITIVE_CONTRACT_V1,
        theorem_evidence=THEOREM_EVIDENCE_V1,
    )
    assert isinstance(result, CompositionPremisesBlocked), result
    # kernel 은 Plan 을 내지 않고 fail-closed 로 raise 한다.
    with pytest.raises(SemanticKernelContextError):
        compute_sealed_execution_plan(_authority(broken))


# ── 3b. capture 단계 context 실패도 fail-closed(snapshot 을 latest 로 풀지 않는다) ───────
def test_capture_context_failure_is_fail_closed():
    structure = _structure()
    # 미지원 execution base kind → judge 가 context error 를 낸다(latest/default 로 안 푼다).
    authority = _authority(structure, policy=_policy(execution_base_kind="bogus/base"))
    with pytest.raises(SemanticKernelContextError):
        compute_execution_snapshot(authority)
    with pytest.raises(SemanticKernelContextError):
        compute_sealed_execution_plan(authority)


# ── 4. Plan store 없이도 durable authority 에서 Plan 재계산 가능 ─────────────────────────
def test_plan_recomputable_from_authority_without_store():
    structure = _structure()
    plan = compute_sealed_execution_plan(_authority(structure))
    assert isinstance(plan, SealedExecutionPlanValue)
    assert plan.plan_payload.active_field_requirements  # 실 Plan value 를 얻었다
    # kernel 모듈은 어떤 store/ledger 도 import 하지 않는다(control plane 밖 재계산의 구조적 증거).
    import hwpxfiller.application.execution_semantic_kernel as kern

    src = __import__("inspect").getsource(kern)
    for forbidden in ("work_execution_plan_store", "stored_execution_plan", "job_store", "_store"):
        assert forbidden not in src, f"kernel 이 {forbidden} 에 의존하면 안 된다"


# ── parity: kernel semantic == 기존 capture+compile seam ───────────────────────────────
def test_semantic_parity_with_existing_capture_compile_seam():
    structure = _structure()
    authority = _authority(structure)
    kern_value = compute_sealed_execution_plan(authority)
    assert isinstance(kern_value, SealedExecutionPlanValue)

    # 기존 seam 을 직접 구동: judge_captured_execution → compile_candidate.
    captured = judge_captured_execution(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        expected_template_application_id=APP,
        expected_profile_id=PROFILE,
        resolved_seal_policy=authority.resolved_seal_policy,
        template=authority.template,
        selection_observation=CapturedSelection(authority.selection),
        field_binding_observation=CapturedFieldBinding(authority.field_binding),
        captured_at=authority.captured_at,
        policy_block=None,
    )
    assert isinstance(captured, CapturedExecutionInput)
    candidate = compile_candidate(captured)

    # 실행 의미(exact basis·Active Fields·ordered operations·plan payload)가 동일하다.
    assert kern_value.plan_payload == candidate.plan_payload
    assert kern_value.execution_basis == candidate.execution_basis
    assert kern_value.active_field_requirements == candidate.plan_payload.active_field_requirements
    assert kern_value.ordered_operations == candidate.plan_payload.ordered_operations
    # kernel 이 만든 snapshot 도 동일 seam 산출과 같다.
    assert compute_execution_snapshot(authority) == captured


# ── 미지원 plan schema/encoding → fail-closed(latest 로 풀지 않는다) ──────────────────────
def test_unsupported_plan_schema_and_encoding_are_fail_closed():
    structure = _structure()
    with pytest.raises(SemanticKernelContextError):
        compute_sealed_execution_plan(
            _authority(structure, policy=_policy(plan_schema_version="bogus-plan/v9"))
        )
    with pytest.raises(SemanticKernelContextError):
        compute_sealed_execution_plan(
            _authority(structure, policy=_policy(canonical_encoding_version="bogus-enc/v9"))
        )


# ── Active Field 미바인딩 → user-fixable Blocked(Plan 없음, context error 아님) ────────────
def test_unbound_active_field_returns_blocked():
    structure = _structure()
    # o2(금액) 를 활성화하되 금액 rule 을 빼면 Active Field 가 미바인딩 → ExecutionQualificationBlocked.
    binding = _binding(structure, rules=_rules(drop=("금액",)))
    authority = DurableExecutionAuthority(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        expected_template_application_id=APP,
        expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(structure),
        selection=_snapshot(structure, selected="o2"),
        field_binding=binding,
        captured_at="2026-08-18T00:00:00Z",
    )
    result = compute_sealed_execution_plan(authority)
    assert isinstance(result, SealedExecutionPlanBlocked)
    assert result.normalized_blockers  # 사유가 비어 있지 않다


# ── R2-01: theorem runtime registry 결합 제거(kernel 은 registry 미consult) ──────────────
def _judge(authority):
    return judge_captured_execution(
        workspace_instance_id=authority.workspace_instance_id,
        work_authority_id=authority.work_authority_id,
        expected_template_application_id=authority.expected_template_application_id,
        expected_profile_id=authority.expected_profile_id,
        resolved_seal_policy=authority.resolved_seal_policy,
        template=authority.template,
        selection_observation=CapturedSelection(authority.selection),
        field_binding_observation=CapturedFieldBinding(authority.field_binding),
        captured_at=authority.captured_at,
        policy_block=None,
    )


def test_kernel_is_independent_of_theorem_registry_runtime():
    """kernel 은 theorem registry 가 resolve 못 해도 동일 Plan 을 낸다 — theorem runtime
    bureaucracy 와의 결합이 끊겼음을 행위로 증명한다. 대조로 compile_candidate 는 빈 registry 에서
    fail-closed 로 raise 하지만, kernel 산출은 registry-검증 경로(default)와 byte 동일하다."""
    structure = _structure()
    authority = _authority(structure)

    kern = compute_sealed_execution_plan(authority)  # registry 미consult → 성공
    assert isinstance(kern, SealedExecutionPlanValue)

    captured = _judge(authority)
    assert isinstance(captured, CapturedExecutionInput)
    # 대조: v1 미등록 빈 registry 에서 기존 seam 은 theorem 을 resolve 못 해 fail-closed.
    empty_registry = TheoremEvidenceRegistry()
    with pytest.raises(UnsupportedLocalImplementation):
        compile_candidate(captured, theorem_registry=empty_registry)

    # 그럼에도 kernel(registry 없음) 산출은 registry-검증 compile_candidate(default)와 byte 동일.
    canonical = compile_candidate(captured)
    assert kern.plan_payload == canonical.plan_payload
    assert kern.execution_basis == canonical.execution_basis


# ── slotless authority 도 순수 재계산된다 ──────────────────────────────────────────────
def test_slotless_authority_recomputes_plan():
    structure = _slotless_structure()
    authority = DurableExecutionAuthority(
        workspace_instance_id=WS,
        work_authority_id=WORK,
        expected_template_application_id=APP,
        expected_profile_id=PROFILE,
        resolved_seal_policy=_policy(),
        template=_template(structure),
        selection=_slotless_selection(structure),
        field_binding=_binding(structure),
        captured_at="2026-08-18T00:00:00Z",
    )
    plan = compute_sealed_execution_plan(authority)
    assert isinstance(plan, (SealedExecutionPlanValue, SealedExecutionPlanBlocked))
