"""DocumentCreationWorkbenchObservation composer 판정 테스트 (SX-01 · #724 §테스트 1·2·3·4·7·12).

composer(:mod:`hwpxfiller.application.document_creation_workbench`)가 기존 S3/S4/S5 권위 verdict 를
**재판정하지 않고** 합성만 하는지, blocker 를 동시에 보존하며 Primary Action 을 §3 사슬로 정확히
하나 고르는지, context error 를 user blocker 로 낮추지 않는지, S6 부재를 READY 로 과장하지 않는지,
historical/fresh 를 분리하는지, 사용자 문안에 내부어를 노출하지 않는지를 확인한다.

S6 부재 admission 은 실제 권위 경로(webapp ``s6_absent_runtime_conformance`` → application
``decide_runtime_policy_admission``)로 파생해 composer 에 넘긴다 — composer 가 그 판정을
재구현하지 않음을 증명한다.

R2(#740): currentness 축(SemanticCurrentness CURRENT/STALE)은 orchestration 으로 흡수됐다 —
CURRENT/STALE 은 orchestration 상태(SETTLED_CURRENT/STALE/FAILED)가 나른다. profile revocation 은
admission 축을 떠나 fresh observation 의 current-work sealability 로 갔으므로, admission 의 policy
축 blocker 는 EXECUTION_BASE_NOT_ADMITTED 로 재현한다.
"""

from __future__ import annotations

import pytest

from hwpxfiller.application.document_creation_vocabulary import (
    BLOCKER_CODES,
    PRIMARY_ACTION_CODES,
)
from hwpxfiller.application.document_creation_workbench import (
    CREATE_DOCUMENTS,
    KEEP,
    RECOVER_CONTEXT,
    RELEASE,
    RESOLVE_EXECUTION,
    RESOLVE_RUNTIME_POLICY,
    ActiveWorkContext,
    ContentSelectionSummary,
    DataScopeSummary,
    DeliveryPreviewSummary,
    DocumentCreationWorkbenchContextError,
    DocumentCreationWorkbenchObservation,
    HistoricalOutcomeSummary,
    InputRequirement,
    RecordValidationSummary,
    WorkbenchCompositionInput,
    WorkbenchContextIntegrity,
    _PRIMARY_ACTION_CHAIN,
    compose_blockers,
    compose_document_creation_workbench,
    compose_primary_action,
    decide_active_work_after_data_transition,
)
from hwpxfiller.application.automatic_seal_orchestration import (
    CHECKING,
    FAILED,
    SETTLED_CURRENT,
    STALE as ORCH_STALE,
    AutomaticSealOrchestration,
)
from hwpxfiller.application.fresh_execution_observation import (
    ADMITTED,
    EXECUTION_BASE_NOT_ADMITTED,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    NOT_ADMITTED,
    NOT_READY,
    READY,
    RuntimeAdmissionFacts,
    RuntimePolicyAdmission,
    decide_runtime_policy_admission,
)
from hwpxfiller.application.preview_requirement import (
    PreviewNotRequired,
    PreviewRequired,
)
from hwpxfiller.application.selection_compatibility import (
    AUTO_KEEP,
    REVIEW_REQUIRED,
)

# ─── 실제 권위 경로로 파생한 S6 부재 admission(재판정 아님을 증명) ─────────────────────────────
from hwpxfiller.webapp.seal_execution_plan_product import s6_absent_runtime_conformance


def _s6_absent_admission() -> RuntimePolicyAdmission:
    """S6 미출하 현실을 실제 권위로 재현: s6_absent_runtime_conformance → decide_runtime_policy_admission.

    합법적 S5 종료 상태는 (current) + NOT_ADMITTED(MATERIALIZATION_CONTRACT_NOT_ADMITTED) + NOT_READY 다.
    R2(#740): RuntimeAdmissionFacts 는 mutable Profile admission 축을 버렸다 — runtime capability 만 본다.
    """
    conformance = s6_absent_runtime_conformance(
        plan_schema_version="v1",
        canonical_encoding_version="v1",
        materialization_contract_id="c1",
        execution_base_kind="APPLIED_TEMPLATE_CANDIDATE",
    )
    facts = RuntimeAdmissionFacts(
        execution_base_kind_admitted=True,
        plan_schema_supported_by_runtime=conformance.plan_schema_supported,
        canonical_encoding_supported_by_runtime=conformance.canonical_encoding_supported,
        materializer_conformance=conformance.verdict,
    )
    return decide_runtime_policy_admission(facts)


def _clear_input(**overrides: object) -> WorkbenchCompositionInput:
    """blocker 0 → CREATE_DOCUMENTS 가 나오는 완전 정리 상태(ADMITTED 가정). override 로 축을 흔든다.

    orchestration 은 SETTLED_CURRENT(반영됨) — R2 이후 CURRENT 는 이 상태가 나른다.
    """
    base: dict[str, object] = dict(
        data_scope=DataScopeSummary(
            mounted=True, record_scope_required=True, selected_record_count=3, total_record_count=3
        ),
        content_selection=ContentSelectionSummary(
            selected_option_ids=("opt-1",), has_unselected_required_content=False
        ),
        active_work=ActiveWorkContext(
            active=True,
            work_ref="work-1",
            exact_context_restorable=True,
            usable_with_current_data=True,
        ),
        admission=RuntimePolicyAdmission(ADMITTED),
        orchestration=AutomaticSealOrchestration(state=SETTLED_CURRENT),
        preview_requirement=PreviewNotRequired(),
        delivery=DeliveryPreviewSummary(resolvable=True, planned_output_names=("문서-1.hwpx",)),
        record_validation=RecordValidationSummary(has_blocking_issues=False),
        template_change_verdict=AUTO_KEEP,
        preview_satisfied=True,
    )
    base.update(overrides)
    return WorkbenchCompositionInput(**base)  # type: ignore[arg-type]


def _observation(**overrides: object) -> DocumentCreationWorkbenchObservation:
    result = compose_document_creation_workbench(_clear_input(**overrides))
    assert isinstance(result, DocumentCreationWorkbenchObservation)
    return result


# ══════════════════════════════════════ (1) Primary Action 결정 ═════════════════════════════════
@pytest.mark.parametrize(
    "overrides, expected_blocker, expected_primary",
    [
        # 완전 정리(ADMITTED) → 종단 CREATE_DOCUMENTS
        ({}, None, CREATE_DOCUMENTS),
        # 데이터 미마운트 → SELECT_DATA
        ({"data_scope": DataScopeSummary(mounted=False)}, "SELECT_DATA", "SELECT_DATA"),
        # 마운트했으나 레코드 선택 0 → SELECT_RECORDS
        (
            {"data_scope": DataScopeSummary(mounted=True, record_scope_required=True, selected_record_count=0)},
            "SELECT_RECORDS",
            "SELECT_RECORDS",
        ),
        # active Work 없음 → SELECT_WORK
        ({"active_work": ActiveWorkContext(active=False)}, "SELECT_WORK", "SELECT_WORK"),
        # Template change REVIEW_REQUIRED → REVIEW_TEMPLATE_CHANGE
        ({"template_change_verdict": REVIEW_REQUIRED}, "REVIEW_TEMPLATE_CHANGE", "REVIEW_TEMPLATE_CHANGE"),
        # 필수 내용 미선택 → CHOOSE_CONTENT
        (
            {"content_selection": ContentSelectionSummary(has_unselected_required_content=True)},
            "CHOOSE_CONTENT",
            "CHOOSE_CONTENT",
        ),
        # Binding 검토 → REVIEW_BINDING
        ({"binding_review_needed": True}, "REVIEW_BINDING", "REVIEW_BINDING"),
        # orchestration CHECKING → EXECUTION_CHECKING → RESOLVE_EXECUTION
        (
            {"orchestration": AutomaticSealOrchestration(state=CHECKING)},
            "EXECUTION_CHECKING",
            RESOLVE_EXECUTION,
        ),
        # orchestration STALE → EXECUTION_STALE → RESOLVE_EXECUTION (R2: currentness 흡수)
        (
            {"orchestration": AutomaticSealOrchestration(state=ORCH_STALE)},
            "EXECUTION_STALE",
            RESOLVE_EXECUTION,
        ),
        # record 검토 → REVIEW_RECORD_DATA
        (
            {"record_validation": RecordValidationSummary(has_blocking_issues=True, issue_count=2)},
            "REVIEW_RECORD_DATA",
            "REVIEW_RECORD_DATA",
        ),
        # 필수 preview 미충족 → REVIEW_PREVIEW
        (
            {
                "preview_requirement": PreviewRequired(reason="NEW_WORK_FIRST_RUN", exact_basis_ref="b1"),
                "preview_satisfied": False,
            },
            "REVIEW_PREVIEW",
            "REVIEW_PREVIEW",
        ),
        # delivery 미해결 → REVIEW_DELIVERY
        ({"delivery": DeliveryPreviewSummary(resolvable=False)}, "REVIEW_DELIVERY", "REVIEW_DELIVERY"),
        # policy 사유 NOT_ADMITTED(base kind) → POLICY_BLOCKED → RESOLVE_RUNTIME_POLICY
        (
            {"admission": RuntimePolicyAdmission(NOT_ADMITTED, (EXECUTION_BASE_NOT_ADMITTED,))},
            "POLICY_BLOCKED",
            RESOLVE_RUNTIME_POLICY,
        ),
    ],
)
def test_primary_action_across_state_combinations(
    overrides: dict[str, object], expected_blocker: str | None, expected_primary: str
) -> None:
    obs = _observation(**overrides)
    if expected_blocker is None:
        assert obs.blockers == ()
    else:
        assert expected_blocker in obs.blockers
    assert obs.primary_action == expected_primary
    assert obs.primary_action in PRIMARY_ACTION_CODES


def test_primary_action_chain_covers_every_blocker_and_matches_vocabulary_order() -> None:
    """사슬이 14 blocker 를 모두 덮고, Primary Action 이 vocabulary 정본 순서와 어긋나지 않는다."""
    chained_blockers = [b for b, _ in _PRIMARY_ACTION_CHAIN]
    # 사슬은 14 blocker 를 모두 덮는다(coverage). 순서는 BLOCKER_CODES 정의순이 아니라
    # Primary Action 우선순위순이다(CONTEXT_ERROR→RECOVER_CONTEXT 가 최우선).
    assert set(chained_blockers) == set(BLOCKER_CODES)
    assert len(chained_blockers) == len(BLOCKER_CODES)  # 중복 없음
    # Primary Action 은 전부 정본 코드
    for _, action in _PRIMARY_ACTION_CHAIN:
        assert action in PRIMARY_ACTION_CODES
    # 사슬이 방출하는 Primary Action 의 첫 등장 순서 = PRIMARY_ACTION_CODES 순서(종단 CREATE 제외)
    seen: list[str] = []
    for _, action in _PRIMARY_ACTION_CHAIN:
        if action not in seen:
            seen.append(action)
    assert seen == [a for a in PRIMARY_ACTION_CODES if a != CREATE_DOCUMENTS]


def test_compose_primary_action_returns_exactly_one_by_priority() -> None:
    """여러 blocker 를 줘도 사슬 최상위 하나만 골라 정확히 하나를 낸다."""
    # 낮은 우선순위(REVIEW_DELIVERY)와 높은 우선순위(SELECT_DATA)가 함께 있으면 SELECT_DATA 승.
    action = compose_primary_action(("SELECT_DATA", "REVIEW_DELIVERY", "RUNTIME_NOT_ADMITTED"))
    assert action == "SELECT_DATA"
    # 아무 blocker 도 없으면 CREATE_DOCUMENTS.
    assert compose_primary_action(()) == CREATE_DOCUMENTS
    # 항상 정확히 하나(문자열) 반환.
    for code in BLOCKER_CODES:
        result = compose_primary_action((code,))
        assert isinstance(result, str) and result in PRIMARY_ACTION_CODES


# ══════════════════════════════════════ (2) 여러 blocker 보존 + primary 1개 ═════════════════════
def test_multiple_blockers_preserved_with_single_primary() -> None:
    obs = _observation(
        data_scope=DataScopeSummary(mounted=True, record_scope_required=True, selected_record_count=0),
        content_selection=ContentSelectionSummary(has_unselected_required_content=True),
        binding_review_needed=True,
        record_validation=RecordValidationSummary(has_blocking_issues=True, issue_count=1),
        delivery=DeliveryPreviewSummary(resolvable=False),
    )
    # 동시에 선 여러 blocker 를 모두 보존한다.
    for code in ("SELECT_RECORDS", "CHOOSE_CONTENT", "REVIEW_BINDING", "REVIEW_RECORD_DATA", "REVIEW_DELIVERY"):
        assert code in obs.blockers
    # 순서는 BLOCKER_CODES 순서를 따른다(결정론적).
    assert list(obs.blockers) == [c for c in BLOCKER_CODES if c in set(obs.blockers)]
    # 그래도 Primary Action 은 정확히 하나 — 사슬 최상위(SELECT_RECORDS).
    assert obs.primary_action == "SELECT_RECORDS"
    # blocker 마다 deep-link target 이 하나씩 있다(같은 개수·같은 코드 집합).
    assert tuple(t.blocker_code for t in obs.deep_link_targets) == obs.blockers
    assert all(t.route for t in obs.deep_link_targets)


# ══════════════════════════════════════ (3) context error ≠ user blocker ════════════════════════
def test_hard_context_integrity_failure_is_context_error_not_user_blocker() -> None:
    result = compose_document_creation_workbench(
        _clear_input(
            # 데이터도 없고 내용도 미선택인 채로 hard integrity 실패를 준다.
            data_scope=DataScopeSummary(mounted=False),
            content_selection=ContentSelectionSummary(has_unselected_required_content=True),
            context_integrity=WorkbenchContextIntegrity(
                restore_failure=True, code="INTEGRITY_VIOLATION", detail="복원 불가"
            ),
        )
    )
    # user-fixable Observation 으로 낮추지 않고 ContextError 로 표현한다.
    assert isinstance(result, DocumentCreationWorkbenchContextError)
    assert result.user_fixable is False
    assert result.primary_action == RECOVER_CONTEXT
    assert result.code == "INTEGRITY_VIOLATION"


def test_admission_context_error_surfaces_as_context_error() -> None:
    """R2(#740): fresh observation 축 실패(ExecutionObservationContextError)는 ring2 가 admission
    CONTEXT_ERROR 로 넘겨 이 경로가 ContextError 로 표현한다 — user-fixable blocker 로 낮추지 않는다.
    (구 currentness CONTEXT_ERROR 채널은 currentness 축과 함께 사라졌고 이 채널로 합류했다.)
    """
    from hwpxfiller.application.fresh_execution_observation import ADMISSION_CONTEXT_ERROR

    result = compose_document_creation_workbench(
        _clear_input(admission=RuntimePolicyAdmission(ADMISSION_CONTEXT_ERROR, ("RUNTIME_CAPABILITY_CONTEXT_ERROR",)))
    )
    assert isinstance(result, DocumentCreationWorkbenchContextError)
    # 어떤 user-fixable blocker 로도 축소되지 않았다(Observation 이 아니다).
    assert not isinstance(result, DocumentCreationWorkbenchObservation)
    assert result.primary_action == RECOVER_CONTEXT
    assert result.code == "EXECUTION_ADMISSION_CONTEXT_ERROR"


def test_context_integrity_rejects_hollow_signal() -> None:
    with pytest.raises(ValueError):
        WorkbenchContextIntegrity(restore_failure=True)  # code·detail 없음 → hollow


# ══════════════════════════════════════ (4) S6 부재: (current) + NOT_ADMITTED + NOT_READY ════════
def test_s6_absent_is_current_not_admitted_not_ready() -> None:
    admission = _s6_absent_admission()
    # admission 은 실제 권위가 내린 verdict — composer 가 재판정하지 않는다.
    assert admission.state == NOT_ADMITTED
    assert MATERIALIZATION_CONTRACT_NOT_ADMITTED in admission.reasons

    # orchestration SETTLED_CURRENT(반영됨) + S6 부재 admission.
    obs = _observation(admission=admission)
    # CURRENT 는 orchestration 축이 나른다(R2: currentness 흡수).
    assert obs.orchestration.state == SETTLED_CURRENT
    # readiness 는 decide_materialization_readiness 권위 함수 결과 → NOT_READY(S6 부재를 READY 로 과장 금지).
    assert obs.materialization_readiness == NOT_READY
    # runtime 축 blocker 로 정직하게 표현.
    assert "RUNTIME_NOT_ADMITTED" in obs.blockers
    # Primary Action 은 CREATE_DOCUMENTS 가 아니라 disabled RESOLVE_RUNTIME_POLICY + 사유.
    assert obs.primary_action == RESOLVE_RUNTIME_POLICY
    assert obs.primary_action != CREATE_DOCUMENTS
    assert obs.primary_action_enabled is False
    assert obs.disabled_reason is not None and obs.disabled_reason != ""


def test_admitted_current_is_ready_and_can_create() -> None:
    """대조군: ADMITTED + orchestration SETTLED_CURRENT 면 READY 이고 CREATE_DOCUMENTS 가 열린다(활성)."""
    obs = _observation(admission=RuntimePolicyAdmission(ADMITTED))
    assert obs.materialization_readiness == READY
    assert obs.blockers == ()
    assert obs.primary_action == CREATE_DOCUMENTS
    assert obs.primary_action_enabled is True
    assert obs.disabled_reason is None


# ══════════════════════════════════════ (7) historical / fresh 분리 ═════════════════════════════
def test_historical_outcome_does_not_dominate_fresh_stale() -> None:
    """historical PlanPublished + orchestration STALE → primary 는 STALE 지배(RESOLVE_EXECUTION)."""
    historical = HistoricalOutcomeSummary(outcome_kind="PLAN_PUBLISHED", observed_at="2026-08-18T00:00:00Z")
    obs = _observation(
        orchestration=AutomaticSealOrchestration(state=ORCH_STALE),
        historical_outcome=historical,
    )
    # 부차 필드로 보존되지만 현재 상태를 지배하지 못한다.
    assert obs.historical_outcome is historical
    assert "EXECUTION_STALE" in obs.blockers
    assert obs.primary_action == RESOLVE_EXECUTION
    # historical PlanPublished 가 "생성 가능"으로 새지 않는다.
    assert obs.primary_action != CREATE_DOCUMENTS


def test_orchestration_failed_needs_manual_recovery_but_stays_stale_blocker() -> None:
    obs = _observation(orchestration=AutomaticSealOrchestration(state=FAILED, consecutive_seal_failures=3))
    assert "EXECUTION_STALE" in obs.blockers
    assert obs.orchestration.requires_manual_recovery is True


# ══════════════════════════════════════ data transition 규칙(#724 §9) ═══════════════════════════
def test_active_work_kept_only_when_restorable_and_usable() -> None:
    keep = decide_active_work_after_data_transition(
        ActiveWorkContext(active=True, work_ref="w", exact_context_restorable=True, usable_with_current_data=True)
    )
    assert keep.disposition == KEEP
    assert keep.auto_activated_work_ref is None


@pytest.mark.parametrize(
    "ctx",
    [
        # 복원 불가
        ActiveWorkContext(active=True, work_ref="w", exact_context_restorable=False, usable_with_current_data=True),
        # 현재 데이터에서 사용 불가
        ActiveWorkContext(active=True, work_ref="w", exact_context_restorable=True, usable_with_current_data=False),
        # 애초에 active 아님
        ActiveWorkContext(active=False),
    ],
)
def test_active_work_released_never_auto_activates_another(ctx: ActiveWorkContext) -> None:
    decision = decide_active_work_after_data_transition(ctx)
    assert decision.disposition == RELEASE
    # 다른 Work 를 자동 활성화하지 않는다 — 타입이 None 으로 못박혀 있다.
    assert decision.auto_activated_work_ref is None


def test_release_ignores_candidate_and_preference_signals() -> None:
    """유일 후보·즐겨찾기·최근 사용·preferredWorkId 가 있어도 KEEP 로 바꾸거나 자동 활성화하지 않는다."""
    ctx = ActiveWorkContext(
        active=True,
        work_ref="w",
        exact_context_restorable=False,  # 복원 불가라 RELEASE 대상
        usable_with_current_data=True,
        unique_candidate_available=True,
        is_favorite=True,
        recently_used=True,
        preferred_work_id="preferred-w",
    )
    decision = decide_active_work_after_data_transition(ctx)
    assert decision.disposition == RELEASE
    assert decision.auto_activated_work_ref is None


# ══════════════════════════════════════ (12) 사용자 문안 내부어 노출 0 ═══════════════════════════
_INTERNAL_TERMS = (
    "slot", "option", "sealed", "seal", "plan", "digest", "vdr",
    "artifact", "binding", "qualification", "currentness", "admission",
)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"orchestration": AutomaticSealOrchestration(state=CHECKING)},
        {"orchestration": AutomaticSealOrchestration(state=FAILED, consecutive_seal_failures=3)},
        {"orchestration": AutomaticSealOrchestration(state=ORCH_STALE)},
        {"admission": RuntimePolicyAdmission(NOT_ADMITTED, (MATERIALIZATION_CONTRACT_NOT_ADMITTED,))},
        {"admission": RuntimePolicyAdmission(NOT_ADMITTED, (EXECUTION_BASE_NOT_ADMITTED,))},
    ],
)
def test_user_facing_texts_expose_no_internal_terms(overrides: dict[str, object]) -> None:
    obs = _observation(**overrides)
    for text in obs.user_facing_texts:
        lowered = text.lower()
        for term in _INTERNAL_TERMS:
            assert term not in lowered, f"사용자 문안 {text!r} 이 내부어 {term!r} 를 노출한다"
    # 사용자 문안 라벨은 vocabulary 정본 값이어야 한다.
    assert obs.content_section_label == "포함할 내용"
    assert obs.input_requirements_label == "입력이 필요한 항목"
    assert obs.delivery_label == "생성 예정 문서"


def test_delivery_label_is_planned_not_artifact() -> None:
    obs = _observation()
    assert obs.delivery.label == "생성 예정 문서"
    assert obs.delivery.is_artifact is False


def test_record_validation_rejects_hollow_blocking() -> None:
    with pytest.raises(ValueError):
        RecordValidationSummary(has_blocking_issues=True, issue_count=0)


def test_binding_review_items_keep_existing_review_semantics_and_exact_targets() -> None:
    items = tuple(
        InputRequirement(
            field_id=field_id,
            display_label=field_id,
            binding_state=state,
            exact_target=f"binding/{field_id}",
        )
        for field_id, state in (
            ("preserved", "PRESERVED"),
            ("broken", "BROKEN"),
            ("new", "NEW_ACTIVE_FIELD"),
            ("inactive", "INACTIVE_ONLY"),
        )
    )
    obs = _observation(input_requirements=items)

    assert tuple(item.action_required for item in obs.input_requirements) == (
        False,
        True,
        True,
        False,
    )
    assert tuple(item.exact_target for item in obs.input_requirements) == (
        "binding/preserved",
        "binding/broken",
        "binding/new",
        "binding/inactive",
    )
    assert obs.primary_action == "REVIEW_BINDING"
