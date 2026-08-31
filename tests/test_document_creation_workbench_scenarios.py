"""H1~H7 사용자 과업 시나리오 판정 (SX-01 · #724 §12).

#724 §12 의 과업 T1~T7 을 composer(:mod:`hwpxfiller.application.document_creation_workbench`)
시나리오 단언으로 인코딩한다. 각 H 는 **PASS 또는 BLOCKED 만** 허용한다 — composer 가 해당 과업의
상태를 정확히 표현하면 그 시나리오 테스트는 PASS 다. 각 테스트는 판정을 ``VERDICT`` 상수와 단언
메시지로 **명시적으로** 남긴다.

과업 대응:

    T1 필수 포함 내용 선택          → CHOOSE_CONTENT blocker/primary 정확
    T2 선택→새 입력 항목 설명        → content 변경이 Active Field requirement 변화로 반영(원인 표현)
    T3 Binding blocker 수정 뒤 복귀  → REVIEW_BINDING + deep-link target 존재
    T4 Template Apply preserved/broken → AUTO_KEEP 재승인 없음, REVIEW_REQUIRED/DETACHED 만 행동
    T5 SETTLED_CURRENT + NOT_ADMITTED → RUNTIME_NOT_ADMITTED, primary disabled + reason, READY 아님
    T6 stale command 뒤 fresh 복귀    → EXECUTION_STALE, fresh 지배
    T7 생성 예정 문서 vs 실제 결과    → delivery 요약 "생성 예정", Artifact 아님

R2(#740): currentness 축(SemanticCurrentness)이 orchestration 으로 흡수됐다 — CURRENT/STALE 는
orchestration 상태(SETTLED_CURRENT/STALE)가 나른다(별도 currentness 입력 없음).
"""

from __future__ import annotations

from hwpxfiller.application.automatic_seal_orchestration import (
    SETTLED_CURRENT,
    STALE as ORCH_STALE,
    AutomaticSealOrchestration,
)
from hwpxfiller.application.document_creation_workbench import (
    CREATE_DOCUMENTS,
    RESOLVE_EXECUTION,
    RESOLVE_RUNTIME_POLICY,
    ActiveWorkContext,
    ContentSelectionSummary,
    DataScopeSummary,
    DeliveryPreviewSummary,
    DocumentCreationWorkbenchObservation,
    HistoricalOutcomeSummary,
    RecordValidationSummary,
    WorkbenchCompositionInput,
    compose_document_creation_workbench,
)
from hwpxfiller.application.fresh_execution_observation import (
    ADMITTED,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    NOT_READY,
    RuntimeAdmissionFacts,
    RuntimePolicyAdmission,
    decide_runtime_policy_admission,
)
from hwpxfiller.application.selection_compatibility import AUTO_KEEP, DETACHED, REVIEW_REQUIRED
from hwpxfiller.webapp.seal_execution_plan_product import s6_absent_runtime_conformance

PASS = "PASS"


def _s6_absent_admission() -> RuntimePolicyAdmission:
    """S6 미출하 admission 을 실제 권위로 파생(s6_absent_runtime_conformance 경유)."""
    conf = s6_absent_runtime_conformance(
        plan_schema_version="v1",
        canonical_encoding_version="v1",
        materialization_contract_id="c1",
        execution_base_kind="APPLIED_TEMPLATE_CANDIDATE",
    )
    facts = RuntimeAdmissionFacts(
        execution_base_kind_admitted=True,
        plan_schema_supported_by_runtime=conf.plan_schema_supported,
        canonical_encoding_supported_by_runtime=conf.canonical_encoding_supported,
        materializer_conformance=conf.verdict,
    )
    return decide_runtime_policy_admission(facts)


def _input(**overrides: object) -> WorkbenchCompositionInput:
    """모든 상위 축이 정리된 baseline(ADMITTED) — 시나리오별로 관심 축만 흔든다."""
    base: dict[str, object] = dict(
        data_scope=DataScopeSummary(
            mounted=True, record_scope_required=True, selected_record_count=2, total_record_count=2
        ),
        content_selection=ContentSelectionSummary(
            selected_option_ids=("opt-1",), has_unselected_required_content=False
        ),
        active_work=ActiveWorkContext(
            active=True, work_ref="work-1", exact_context_restorable=True, bound_to_current_data=True
        ),
        admission=RuntimePolicyAdmission(ADMITTED),
        orchestration=AutomaticSealOrchestration(state=SETTLED_CURRENT),
        delivery=DeliveryPreviewSummary(resolvable=True, planned_output_names=("문서-1.hwpx", "문서-2.hwpx")),
        record_validation=RecordValidationSummary(has_blocking_issues=False),
        template_change_verdict=AUTO_KEEP,
    )
    base.update(overrides)
    return WorkbenchCompositionInput(**base)  # type: ignore[arg-type]


def _obs(**overrides: object) -> DocumentCreationWorkbenchObservation:
    result = compose_document_creation_workbench(_input(**overrides))
    assert isinstance(result, DocumentCreationWorkbenchObservation), "context error 아님이 전제"
    return result


# ══════════════════════════════════════ H1 / T1 ════════════════════════════════════════════════
def test_h1_choose_required_content() -> None:
    """T1: 필수 포함 내용을 아직 안 골랐을 때 CHOOSE_CONTENT 로 정확히 안내하고, 고르면 해소된다."""
    verdict = PASS

    # BLOCKED 국면: 필수 내용 미선택 → CHOOSE_CONTENT blocker + primary.
    before = _obs(content_selection=ContentSelectionSummary(has_unselected_required_content=True))
    assert "CHOOSE_CONTENT" in before.blockers, f"{verdict}: 필수 내용 미선택이 CHOOSE_CONTENT 로 안내돼야 한다"
    assert before.primary_action == "CHOOSE_CONTENT"

    # 해소 국면: 필수 내용 선택 → CHOOSE_CONTENT 사라짐.
    after = _obs(
        content_selection=ContentSelectionSummary(
            selected_option_ids=("opt-required",), has_unselected_required_content=False
        )
    )
    assert "CHOOSE_CONTENT" not in after.blockers, f"{verdict}: 내용 선택 뒤 blocker 가 사라져야 한다"
    # H1 판정: PASS — 필수 내용 선택 안내와 해소가 정확하다.
    assert verdict == PASS


# ══════════════════════════════════════ H2 / T2 ════════════════════════════════════════════════
def test_h2_selection_introduces_new_input_requirement() -> None:
    """T2: 내용 선택이 새로 필요해진 입력 항목(Active Field)으로 반영되고 그 원인이 표현된다."""
    verdict = PASS

    # 선택 전: 요구 입력 항목 하나, Binding 검토 불필요.
    before = _obs(
        content_selection=ContentSelectionSummary(selected_option_ids=("opt-1",)),
        active_field_requirement_ids=("field-a",),
        binding_review_needed=False,
    )
    # 선택 후: opt-2 를 더 고르자 새 입력 항목(field-b)이 필요해지고 Binding 검토가 생긴다.
    after = _obs(
        content_selection=ContentSelectionSummary(selected_option_ids=("opt-1", "opt-2")),
        active_field_requirement_ids=("field-a", "field-b"),
        binding_review_needed=True,
    )
    # Active Field requirement 변화가 반영된다(원인 = 내용 선택 변경).
    assert set(before.active_field_requirement_ids) < set(after.active_field_requirement_ids), (
        f"{verdict}: 내용 선택이 새 입력 항목으로 반영돼야 한다"
    )
    assert "field-b" in after.active_field_requirement_ids
    # 새로 필요해진 입력이 REVIEW_BINDING 으로 행동 대상이 된다(원인 표현).
    assert "REVIEW_BINDING" in after.blockers
    assert after.input_requirements_label == "입력이 필요한 항목"
    # H2 판정: PASS — 선택이 새 입력 요구로 이어지고 원인이 표현된다.
    assert verdict == PASS


# ══════════════════════════════════════ H3 / T3 ════════════════════════════════════════════════
def test_h3_binding_blocker_has_deep_link_and_clears() -> None:
    """T3: Binding blocker 에 같은 위치로 돌아갈 exact deep-link target 이 있고, 고치면 해소된다."""
    verdict = PASS

    blocked = _obs(binding_review_needed=True)
    assert "REVIEW_BINDING" in blocked.blockers
    # deep-link target 존재 — 수정 뒤 같은 위치로 복귀할 수 있다.
    targets = {t.blocker_code: t.route for t in blocked.deep_link_targets}
    assert "REVIEW_BINDING" in targets, f"{verdict}: REVIEW_BINDING deep-link target 이 있어야 한다"
    assert targets["REVIEW_BINDING"] == "workbench.binding"

    fixed = _obs(binding_review_needed=False)
    assert "REVIEW_BINDING" not in fixed.blockers, f"{verdict}: Binding 수정 뒤 blocker 가 사라져야 한다"
    # H3 판정: PASS — Binding blocker 의 위치 복귀 target 이 있고 수정으로 해소된다.
    assert verdict == PASS


# ══════════════════════════════════════ H4 / T4 ════════════════════════════════════════════════
def test_h4_template_apply_preserved_vs_broken() -> None:
    """T4: Template Apply 뒤 AUTO_KEEP 는 재승인 없음, REVIEW_REQUIRED/DETACHED 만 행동 대상."""
    verdict = PASS

    # preserved(AUTO_KEEP) — 재승인 요구 없음.
    kept = _obs(template_change_verdict=AUTO_KEEP)
    assert "REVIEW_TEMPLATE_CHANGE" not in kept.blockers, f"{verdict}: AUTO_KEEP 는 재승인이 없어야 한다"

    # broken(REVIEW_REQUIRED) — 행동 대상.
    review = _obs(template_change_verdict=REVIEW_REQUIRED)
    assert "REVIEW_TEMPLATE_CHANGE" in review.blockers
    assert review.primary_action == "REVIEW_TEMPLATE_CHANGE"

    # detached(DETACHED) — 역시 행동 대상.
    detached = _obs(template_change_verdict=DETACHED)
    assert "REVIEW_TEMPLATE_CHANGE" in detached.blockers
    # H4 판정: PASS — 유지된 선택과 다시 결정할 선택이 구분된다.
    assert verdict == PASS


# ══════════════════════════════════════ H5 / T5 ════════════════════════════════════════════════
def test_h5_current_but_not_admitted() -> None:
    """T5: SETTLED_CURRENT + NOT_ADMITTED → RUNTIME_NOT_ADMITTED, primary disabled + reason, READY 아님.

    R2(#740): '반영됨'은 orchestration SETTLED_CURRENT(baseline)가 나른다 — currentness 필드는 없다.
    그 위에서 runtime admission 이 NOT_ADMITTED 면 정직하게 RUNTIME_NOT_ADMITTED 로 막힌다.
    """
    verdict = PASS

    admission = _s6_absent_admission()
    assert MATERIALIZATION_CONTRACT_NOT_ADMITTED in admission.reasons

    obs = _obs(admission=admission)
    assert obs.orchestration.state == SETTLED_CURRENT, f"{verdict}: 반영됨은 SETTLED_CURRENT 로 정직해야 한다"
    assert "RUNTIME_NOT_ADMITTED" in obs.blockers
    assert obs.materialization_readiness == NOT_READY, f"{verdict}: S6 부재를 READY 로 과장하지 않는다"
    assert obs.primary_action == RESOLVE_RUNTIME_POLICY
    assert obs.primary_action != CREATE_DOCUMENTS
    # disabled 이지만 숨기지 않고 사유와 함께.
    assert obs.primary_action_enabled is False
    assert obs.disabled_reason, f"{verdict}: 비활성 Primary Action 은 사유와 함께여야 한다"
    # H5 판정: PASS — SETTLED_CURRENT + NOT_ADMITTED 를 정직하게 해석한다.
    assert verdict == PASS


# ══════════════════════════════════════ H6 / T6 ════════════════════════════════════════════════
def test_h6_stale_command_then_fresh_recovery() -> None:
    """T6: stale command 뒤에도 fresh state 가 지배하고, fresh 가 CURRENT 로 돌아오면 복구된다."""
    verdict = PASS

    # 과거 사건(historical)은 보존하되, orchestration 이 STALE 이면 STALE 이 지배한다.
    historical = HistoricalOutcomeSummary(outcome_kind="STALE_EXECUTION_BASIS", observed_at="2026-08-18T00:00:00Z")
    stale = _obs(
        orchestration=AutomaticSealOrchestration(state=ORCH_STALE),
        historical_outcome=historical,
    )
    assert "EXECUTION_STALE" in stale.blockers, f"{verdict}: stale command 는 EXECUTION_STALE 로 표현"
    assert stale.primary_action == RESOLVE_EXECUTION
    assert stale.historical_outcome is historical  # 부차 보존
    assert stale.execution_status_phrase == "설정이 바뀌어 다시 확인해야 합니다"

    # orchestration 이 다시 SETTLED_CURRENT 로 정착하면(자동 seal 재확인) stale 이 사라지고 복구된다.
    recovered = _obs(
        orchestration=AutomaticSealOrchestration(state=SETTLED_CURRENT),
        historical_outcome=historical,
    )
    assert "EXECUTION_STALE" not in recovered.blockers, f"{verdict}: SETTLED_CURRENT 복귀로 stale 이 사라져야 한다"
    # H6 판정: PASS — stale 뒤 fresh state 가 지배하고 복구된다.
    assert verdict == PASS


# ══════════════════════════════════════ H7 / T7 ════════════════════════════════════════════════
def test_h7_planned_delivery_not_artifact() -> None:
    """T7: delivery 요약은 '생성 예정 문서'로 말하고 Artifact(실제 결과)가 아니다.

    종전 이 시나리오는 semantic value preview 라벨('생성 내용 확인')까지 함께 겨눴다.
    그 투영은 #957 슬라이스 ③ 에서 사라졌으므로 남은 축 하나 — **계획과 결과를 가르는
    delivery 어휘** — 만 겨눈다. 계획된 이름은 여전히 디스크 write 없이 실린다.
    """
    verdict = PASS

    obs = _obs(
        delivery=DeliveryPreviewSummary(resolvable=True, planned_output_names=("문서-1.hwpx", "문서-2.hwpx")),
    )
    # "생성 예정 문서"(Resolved Delivery) — 실제 생성된 결과(Artifact)가 아니다.
    assert obs.delivery_label == "생성 예정 문서", f"{verdict}: delivery 는 '생성 예정'으로 말해야 한다"
    assert obs.delivery.label == "생성 예정 문서"
    assert obs.delivery.is_artifact is False, f"{verdict}: delivery 요약은 Artifact 가 아니다"
    # 생성 예정 문서 이름이 계획으로만 실린다(디스크 write 아님).
    assert obs.delivery.planned_output_names == ("문서-1.hwpx", "문서-2.hwpx")
    # H7 판정: PASS — 생성 예정 문서와 실제 결과가 구분된다.
    assert verdict == PASS
