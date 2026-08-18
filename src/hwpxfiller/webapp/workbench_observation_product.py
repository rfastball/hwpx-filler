"""문서 만들기 작업대 Observation 어댑터 — controller 세션 사실을 WorkbenchCompositionInput 으로 조립 (SX-02 · #725).

`compose_document_creation_workbench`(SX-01 #724 소유)를 **소비만** 하는 ring2 어댑터다. ring1/application
composer 는 세션값을 직접 읽지 못하므로, controller(ring2)가 든 세션 사실(데이터 마운트·선택 record 수·
active Work·S4 content 선택 요약·orchestration 상태)을 :class:`WorkbenchCompositionInput` 으로 shape 한다.
**판정은 여기서 하지 않는다** — blocker/primary_action/readiness 합성은 전부 composer(backend 권위)가 진다.

**슬라이스 경계(additive 규율).** SX-02 는 다음 네 축만 실제 세션 사실로 채운다:

- ``data_scope``          — 데이터 마운트·record scope(:func:`data_scope_from_session`)
- ``content_selection``   — S4 projection 이 이미 판정한 content 선택 요약(:func:`content_selection_from_view`)
- ``active_work``         — active Work 식별(:func:`active_work_from_session`)
- ``orchestration``       — controller 가 든 session-scoped :class:`AutomaticSealOrchestration`

나머지 축(``admission``·``preview_requirement``·``delivery``·``record_validation``·
``binding_review_needed``·``active_field_requirement_ids``·``preview_satisfied``·``semantic_preview``·
``template_change_verdict``·``context_integrity``·``historical_outcome``)은 **명시적 seam 기본값**이다.
각 seam 은 `_sx03_seam_*` / `_sx04_seam_*` 부분함수 하나가 낸다 — SX-03/SX-04 가 자기 함수 본문만
실제 backend verdict 로 바꿔 끼우면 되게 축별로 분리했다(다른 축의 라인을 건드리지 않는다).

**seam 기본값은 실제 verdict 를 하드코딩하지 않는다(#725 즉시 상향: "UI 가 semantic 을 재해석").** 그래서
이 슬라이스의 합성 Observation 은 **아직 사용자 실행 표면이 아니다** — SX-02 의 snapshot 은 S4 projection
(`slot_configuration` 키)만 노출하고 이 Observation 을 노출하지 않는다. 노출 seam 은 SX-03/04/05 소관이다.
정직성 앵커: :func:`_sx04_seam_delivery` 가 ``resolvable=False`` 라 delivery 축이 실제로 채워지기 전에는
Primary Action 이 결코 ``CREATE_DOCUMENTS`` 에 닿지 못한다 — 뒤 슬라이스가 이 Observation 을 성급히
노출해도 조용한 green 대신 시끄러운 ``REVIEW_DELIVERY`` 로 막힌다(confirm-or-alarm).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..application.automatic_seal_orchestration import AutomaticSealOrchestration
from ..application.document_creation_workbench import (
    ActiveWorkContext,
    ContentSelectionSummary,
    DataScopeSummary,
    DeliveryPreviewSummary,
    GetDocumentCreationWorkbenchResult,
    RecordValidationSummary,
    WorkbenchCompositionInput,
    compose_document_creation_workbench,
)
from ..application.fresh_execution_observation import (
    ADMISSION_CONTEXT_ERROR,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    NOT_ADMITTED,
    NOT_READY,
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    FreshExecutionObservation,
    RuntimePolicyAdmission,
)
from ..application.preview_requirement import PreviewNotRequired, PreviewRequirement
from ..application.slot_configuration_projection import (
    HAS_BROKEN_SELECTIONS,
    NEEDS_SELECTION,
    CurrentSlotConfigurationView,
)
from ..application.workbench_execution_status import (
    WORKBENCH_EXECUTION_STATUS_PHRASE,
    derive_workbench_execution_status,
)


# ── SX-02 소유 축: 세션 사실 → 요약 DTO ────────────────────────────────────────────────────────
def data_scope_from_session(
    *, mounted: bool, selected_record_count: int, total_record_count: int
) -> DataScopeSummary:
    """데이터 존 세션값 → :class:`DataScopeSummary`. record scope 는 v1 에서 항상 필요(현행 실행 계약)."""
    return DataScopeSummary(
        mounted=mounted,
        record_scope_required=True,
        selected_record_count=selected_record_count,
        total_record_count=total_record_count,
    )


def content_selection_from_view(
    view: CurrentSlotConfigurationView | None,
) -> ContentSelectionSummary:
    """S4 projection → content 선택 요약. **재판정하지 않는다** — projection 이 이미 낸 값을 shape 만 한다.

    ``selected_option_ids`` 는 effective option(현재 실효 선택)의 flat 합이고,
    ``has_unselected_required_content`` 는 projection 의 ``configuration_status`` 가 아직 손볼 내용이
    남았다는 두 상태 — 필수 Slot 미선택(``NEEDS_SELECTION``) **또는** 깨진 선택(``HAS_BROKEN_SELECTIONS``:
    선택했던 Option 이 사라졌거나 cardinality 가 깨짐) — 일 때 True 다. broken 을 흘려보내면 사용자를
    고쳐야 할 구성 너머로 지나치게 하므로 CHOOSE_CONTENT 로 시끄럽게 막는다. projection 부재(context
    error·미조회)는 선택 없음으로 본다.
    """
    if view is None:
        return ContentSelectionSummary()
    selected: list[str] = []
    for slot in view.slots:
        selected.extend(slot.effective_option_ids)
    return ContentSelectionSummary(
        selected_option_ids=tuple(selected),
        has_unselected_required_content=view.configuration_status
        in (NEEDS_SELECTION, HAS_BROKEN_SELECTIONS),
    )


def active_work_from_session(work_ref: str | None) -> ActiveWorkContext:
    """세션의 선택된 Work → :class:`ActiveWorkContext`. work_ref 가 있으면 active, 없으면 미선택.

    exact context 복원·현재 데이터 사용 가능 판정(``exact_context_restorable``·
    ``usable_with_current_data``)은 **SX-05/backend 소관**이라 여기서 채우지 않는다 —
    :func:`decide_active_work_after_data_transition` 이 소비할 플래그의 자리만 둔다.
    """
    if work_ref:
        return ActiveWorkContext(active=True, work_ref=work_ref)
    return ActiveWorkContext(active=False)


# ── SX-03 축: seal 서비스의 fresh_observation → execution verdict(재라벨만, 재판정 0) ─────────────
@dataclass(frozen=True)
class WorkbenchExecutionVerdicts:
    """seal 서비스 fresh_observation 에서 **추출한** execution verdict 묶음(새 판정 0).

    R2(#740): currentness 축이 orchestration 으로 흡수돼 verdict 는 admission·sealability·readiness
    세 값만 나른다. ``admission`` 은 composer 가 요구하는 non-None 값이자 status 축의 CONTEXT_ERROR
    입력이다(fresh 축 실패는 admission=CONTEXT_ERROR 로 표현). ``current_work_sealability`` 는 7상태
    DOMAIN/POLICY/CONTEXT 파생용(sealable/증거 없음이면 None). ``materialization_readiness`` 는
    product 가 이미 :func:`decide_materialization_readiness` 로 낸 값이다.
    """

    admission: RuntimePolicyAdmission
    current_work_sealability: str | None
    materialization_readiness: str


#: 확인 증거 부재(seal 미실행)·current-work 미봉인의 정직한 runtime admission — S6 미출하와 같은
#: 계열로 NOT_ADMITTED. unknown 을 ADMITTED 로 풀지 않는다(fail-closed, #726 §5).
_NO_EVIDENCE_ADMISSION = RuntimePolicyAdmission(
    state=NOT_ADMITTED, reasons=(MATERIALIZATION_CONTRACT_NOT_ADMITTED,)
)


def execution_verdicts_from_fresh(
    fresh: FreshExecutionObservation | None,
) -> WorkbenchExecutionVerdicts:
    """fresh_observation → execution verdict(순수 재라벨 — admission/sealability 를 재판정하지 않는다).

    R2(#740) fresh_observation union 기준:

    - :class:`CurrentSealedPlanObservation` — current Work 가 sealable 이다. admission/readiness 를
      그대로 shape 한다(예: NOT_ADMITTED + NOT_READY = S6 미출하 정상 종료). CURRENT 상태는 status
      축에서 orchestration.SETTLED_CURRENT 가 나른다.
    - :class:`CurrentWorkExecutionObservation` — seal 불가, current Work 만 관찰됐다. sealability
      (DOMAIN_BLOCKED/POLICY_BLOCKED/CONTEXT_ERROR)를 7상태 축으로 나른다. admission 은 정직한
      NOT_ADMITTED(READY 과장 0).
    - :class:`ExecutionObservationContextError` — fresh 축 실패 → admission CONTEXT_ERROR(composer 가
      ContextError 로 표현, 7상태도 CONTEXT_ERROR — user-fixable blocker 로 낮추지 않는다).
    - ``None`` — 아직 seal 을 돌리지 않았다(NO_EVIDENCE) — 정직한 blocked 기본값.
    """
    if isinstance(fresh, CurrentSealedPlanObservation):
        return WorkbenchExecutionVerdicts(
            admission=fresh.runtime_policy_admission,
            current_work_sealability=None,
            materialization_readiness=fresh.materialization_readiness,
        )
    if isinstance(fresh, CurrentWorkExecutionObservation):
        return WorkbenchExecutionVerdicts(
            admission=_NO_EVIDENCE_ADMISSION,
            current_work_sealability=fresh.current_sealability,
            materialization_readiness=NOT_READY,
        )
    if isinstance(fresh, ExecutionObservationContextError):
        return WorkbenchExecutionVerdicts(
            admission=RuntimePolicyAdmission(
                state=ADMISSION_CONTEXT_ERROR, reasons=(fresh.detail,)
            ),
            current_work_sealability=None,
            materialization_readiness=NOT_READY,
        )
    return WorkbenchExecutionVerdicts(
        admission=_NO_EVIDENCE_ADMISSION,
        current_work_sealability=None,
        materialization_readiness=NOT_READY,
    )


def _sx03_seam_preview_requirement() -> PreviewRequirement:
    # PreviewRequirement 정책 v1: 일반 Option 선택은 NOT_REQUIRED(#724 §6). 새 Work 첫 실행·Template
    # Application 변경 뒤 첫 실행 등 REQUIRED 판정은 preview_requirement 판정 함수 소관(SX-04 축).
    return PreviewNotRequired()


# ── SX-04 seam(record/delivery/preview-satisfied 축) — 부분함수 하나씩 ────────────────────────────
def _sx04_seam_record_validation() -> RecordValidationSummary:
    # SX-04 seam: 실제 record validation 은 RecordValidation 권위 verdict 로 온다.
    return RecordValidationSummary()


def _sx04_seam_delivery() -> DeliveryPreviewSummary:
    # SX-04 seam(정직성 앵커): delivery 가 실제로 채워지기 전에는 resolvable=False —
    # Primary Action 이 CREATE_DOCUMENTS 로 조용히 새지 않고 REVIEW_DELIVERY 로 시끄럽게 막힌다.
    return DeliveryPreviewSummary(resolvable=False)


def _sx04_seam_preview_satisfied() -> bool:
    # SX-04 seam: preview 승인 사건 소비는 SX-04 축이다.
    return False


class WorkbenchObservationProduct:
    """작업대 Observation 합성 Product — headless(webview 비의존). controller 가 주입받아 든다.

    상태를 갖지 않는다(세션 사실은 매 호출 인자로 받는다). SX-02 는 SX-02 축만 실제 사실로 채우고
    seam 축은 위 부분함수가 낸다 — SX-03/04 가 이 클래스에 새 인자를 더하고 seam 함수 본문을 교체한다.
    """

    def compose(
        self,
        *,
        data_mounted: bool,
        selected_record_count: int,
        total_record_count: int,
        active_work_ref: str | None,
        slot_view: CurrentSlotConfigurationView | None,
        orchestration: AutomaticSealOrchestration,
        fresh_observation: FreshExecutionObservation | None = None,
        active_field_requirement_ids: tuple[str, ...] = (),
        binding_review_needed: bool = False,
        template_change_verdict: str | None = None,
    ) -> GetDocumentCreationWorkbenchResult:
        """세션 사실 + seal 서비스 fresh_observation → 작업대 Observation(또는 ContextError).

        판정은 하지 않는다 — admission/readiness 는 :func:`execution_verdicts_from_fresh`
        가 fresh_observation 에서 **추출**한 값을 그대로 composer 에 넘긴다(하드코딩 0). CURRENT/STALE 은
        orchestration 축이 나른다(R2(#740): currentness 흡수). SX-04 축(record/delivery/preview)은
        여전히 seam 기본값이다 — delivery anchor(resolvable=False)가 CREATE 로의 조용한 누수를 막는다.
        """
        verdicts = execution_verdicts_from_fresh(fresh_observation)
        composition = WorkbenchCompositionInput(
            # ── SX-02 소유 축(실제 세션 사실) ──
            data_scope=data_scope_from_session(
                mounted=data_mounted,
                selected_record_count=selected_record_count,
                total_record_count=total_record_count,
            ),
            content_selection=content_selection_from_view(slot_view),
            active_work=active_work_from_session(active_work_ref),
            orchestration=orchestration,
            # ── SX-03 축(fresh_observation 소비 — 재판정 0) ──
            admission=verdicts.admission,
            preview_requirement=_sx03_seam_preview_requirement(),
            active_field_requirement_ids=active_field_requirement_ids,
            binding_review_needed=binding_review_needed,
            template_change_verdict=template_change_verdict,
            # ── SX-04 seam ──
            record_validation=_sx04_seam_record_validation(),
            delivery=_sx04_seam_delivery(),
            preview_satisfied=_sx04_seam_preview_satisfied(),
        )
        return compose_document_creation_workbench(composition)

    def execution_status(
        self,
        *,
        orchestration: AutomaticSealOrchestration,
        fresh_observation: FreshExecutionObservation | None,
    ) -> tuple[str, str]:
        """작업대 execution status 7상태 (code, phrase) — verdict 로 파생(NO_EVIDENCE 정확).

        R2(#740): CURRENT/STALE/CHECKING/NO_EVIDENCE 는 orchestration 이, DOMAIN/POLICY/CONTEXT 는
        fresh observation 이 나른다 — 증거 없음(orchestration IDLE)을 STALE 로 뭉개지 않는다. phrase
        정본은 :data:`WORKBENCH_EXECUTION_STATUS_PHRASE`(#726 §3).
        """
        verdicts = execution_verdicts_from_fresh(fresh_observation)
        code = derive_workbench_execution_status(
            orchestration=orchestration,
            admission=verdicts.admission,
            current_work_sealability=verdicts.current_work_sealability,
        )
        return code, WORKBENCH_EXECUTION_STATUS_PHRASE[code]


__all__ = [
    "WorkbenchObservationProduct",
    "WorkbenchExecutionVerdicts",
    "execution_verdicts_from_fresh",
    "data_scope_from_session",
    "content_selection_from_view",
    "active_work_from_session",
]
