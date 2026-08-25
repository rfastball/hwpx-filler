"""문서 만들기 작업대 Observation composer — 기존 권위를 사용자 행동으로 합성 (SX-01 · #724 · #719 D3).

이 모듈은 S3(current Work/Application) · S4(Working Configuration projection) · S5(Binding/execution
observation) · record validation · delivery · current data/OrderedSelection 의 **이미 판정된
authoritative 상태**를 하나의 사용자 작업대 상태와 다음 행동으로 **합성하는 비영속 projection**
이다(#719 D3). React(ring2)가 여러 권위 상태를 조합해 새 semantic 을 만들지 않도록, 그 합성을
backend Product/Application 계약이 진다.

**절대 하지 않는 것(재판정 금지).**

- 새 durable state · ``current_plan_id`` · UI-only validity 를 만들지 않는다.
- record validity · output path · Active Field · PreviewRequirement · runtime admission 을
  **재판정하지 않는다** — 전부 backend 권위가 이미 내린 verdict 를 **shape 만** 받아 합성한다.
  admission 은 :mod:`hwpxfiller.application.fresh_execution_observation` verdict,
  readiness 는 그 모듈의 :func:`decide_materialization_readiness` **권위 함수**로 파생한다
  (R2(#740): currentness 축은 orchestration 상태로 흡수 — 별도 입력이 없다)
  (재구현 아님). preview requirement 는 :mod:`hwpxfiller.application.preview_requirement`,
  template change 는 :mod:`hwpxfiller.application.selection_compatibility` verdict, orchestration 은
  :mod:`hwpxfiller.application.automatic_seal_orchestration` 상태를 그대로 소비한다.
- store/webapp/gui/pywebview 를 import 하지 않는다(``tests/repo_contract/test_architecture.py`` 의
  링 경계가 강제). S6-absent runtime conformance(``s6_absent_runtime_conformance``)는 webapp 소유라
  여기서 import 하지 않고, **이미 파생된** ``RuntimePolicyAdmission`` verdict 로 받는다.

**입력 계약 DTO(이 모듈 소유 — SX-01/SX-02 경계선).** application composer 는 ring2 세션값을 직접
읽지 못하므로 최소 입력 DTO 를 여기서 정의한다. 이 DTO 들의 값은 **backend/controller(ring2, SX-02)가
채우는 사실**이지 프런트가 계산하는 값이 아니다 — 프런트가 이걸 계산하면 상향 조건(#724 즉시 상향)
위반이다. :class:`DataScopeSummary` · :class:`ContentSelectionSummary` · :class:`ActiveWorkContext`
가 그것이다. 나머지 축(currentness/admission/preview/orchestration/record/delivery)은 위 권위
모듈의 verdict 타입을 **재사용**한다.

frozen dataclass 만 쓴다. 어휘 문자열의 정본은
:mod:`hwpxfiller.application.document_creation_vocabulary` 이고 여기서는 **import 만** 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from hwpxfiller.application.automatic_seal_orchestration import (
    CHECKING,
    FAILED,
    SETTLED_CURRENT,
    STALE as ORCHESTRATION_STALE,
    AutomaticSealOrchestration,
)
from hwpxfiller.application.document_creation_vocabulary import (
    BLOCKER_CODES,
    PRIMARY_ACTION_CODES,
    USER_VOCABULARY,
)
from hwpxfiller.application.fresh_execution_observation import (
    ADMISSION_CONTEXT_ERROR,
    CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME,
    EXECUTION_BASE_NOT_ADMITTED,
    MATERIALIZATION_CONTRACT_NOT_ADMITTED,
    NOT_ADMITTED,
    PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME,
    RuntimePolicyAdmission,
    decide_materialization_readiness,
)
from hwpxfiller.application.field_binding_input import (
    BROKEN,
    INACTIVE_ONLY,
    NEW_ACTIVE_FIELD,
    PRESERVED,
)
from hwpxfiller.application.preview_requirement import (
    PreviewRequired,
    PreviewRequirement,
    SemanticValuePreviewProjection,
)
from hwpxfiller.application.run_delivery_intent import RunDeliveryIntent
from hwpxfiller.application.selection_compatibility import DETACHED, REVIEW_REQUIRED

# ─── blocker / primary action 코드(vocabulary 정본에서 풀어 씀 — 재정의 아님) ───────────────────
(
    SELECT_DATA,
    SELECT_RECORDS,
    SELECT_WORK,
    REVIEW_TEMPLATE_CHANGE,
    CHOOSE_CONTENT,
    REVIEW_BINDING,
    REVIEW_RECORD_DATA,
    REVIEW_DELIVERY,
    REVIEW_PREVIEW,
    EXECUTION_CHECKING,
    EXECUTION_STALE,
    POLICY_BLOCKED,
    RUNTIME_NOT_ADMITTED,
    CONTEXT_ERROR,
) = BLOCKER_CODES

(
    RECOVER_CONTEXT,
    PA_SELECT_DATA,
    PA_SELECT_RECORDS,
    PA_SELECT_WORK,
    PA_REVIEW_TEMPLATE_CHANGE,
    PA_CHOOSE_CONTENT,
    PA_REVIEW_BINDING,
    RESOLVE_EXECUTION,
    PA_REVIEW_RECORD_DATA,
    PA_REVIEW_DELIVERY,
    PA_REVIEW_PREVIEW,
    RESOLVE_RUNTIME_POLICY,
    CREATE_DOCUMENTS,
) = PRIMARY_ACTION_CODES

# ─── Primary Action 우선순위 사슬(#724 §3) ─────────────────────────────────────────────────────
# (blocker_code, primary_action_code) 쌍의 **우선순위 순서**. 이슈 §3 사슬을 리터럴로 인코딩한다:
#   context → 데이터 → 레코드 → Work → Template change → content → Binding
#   → execution checking/stale → record → delivery → required preview → runtime/policy → CREATE.
# 두 blocker(EXECUTION_CHECKING/EXECUTION_STALE)가 하나의 RESOLVE_EXECUTION 로,
# 두 blocker(POLICY_BLOCKED/RUNTIME_NOT_ADMITTED)가 하나의 RESOLVE_RUNTIME_POLICY 로 접힌다.
# :func:`compose_primary_action` 이 이 순서로 **첫 blocker 하나**만 골라 정확히 하나를 낸다.
_PRIMARY_ACTION_CHAIN: tuple[tuple[str, str], ...] = (
    (CONTEXT_ERROR, RECOVER_CONTEXT),
    (SELECT_DATA, PA_SELECT_DATA),
    (SELECT_RECORDS, PA_SELECT_RECORDS),
    (SELECT_WORK, PA_SELECT_WORK),
    (REVIEW_TEMPLATE_CHANGE, PA_REVIEW_TEMPLATE_CHANGE),
    (CHOOSE_CONTENT, PA_CHOOSE_CONTENT),
    (REVIEW_BINDING, PA_REVIEW_BINDING),
    (EXECUTION_CHECKING, RESOLVE_EXECUTION),
    (EXECUTION_STALE, RESOLVE_EXECUTION),
    (REVIEW_RECORD_DATA, PA_REVIEW_RECORD_DATA),
    (REVIEW_DELIVERY, PA_REVIEW_DELIVERY),
    (REVIEW_PREVIEW, PA_REVIEW_PREVIEW),
    (POLICY_BLOCKED, RESOLVE_RUNTIME_POLICY),
    (RUNTIME_NOT_ADMITTED, RESOLVE_RUNTIME_POLICY),
)

# admission NOT_ADMITTED 사유 → policy 축 vs runtime 축(어느 blocker 로 표현할지).
# R2(#740): QUALIFICATION_PROFILE_REVOKED 는 admission 축에서 사라졌다 — profile revocation 은 이제
# fresh observation 의 current-work sealability POLICY_BLOCKED 로 표현된다(7상태 status 축 소관).
# admission 의 정책성 not-admitted 사유는 base kind 뿐이다.
_POLICY_ADMISSION_REASONS: frozenset[str] = frozenset({EXECUTION_BASE_NOT_ADMITTED})
_RUNTIME_ADMISSION_REASONS: frozenset[str] = frozenset(
    {
        MATERIALIZATION_CONTRACT_NOT_ADMITTED,
        PLAN_SCHEMA_NOT_SUPPORTED_BY_RUNTIME,
        CANONICAL_ENCODING_NOT_SUPPORTED_BY_RUNTIME,
    }
)

# blocker → exact deep-link route(내부 route id — 사용자 문안이 아니다).
_DEEP_LINK_ROUTES: dict[str, str] = {
    SELECT_DATA: "job.data",
    SELECT_RECORDS: "job.records",
    SELECT_WORK: "library.work",
    REVIEW_TEMPLATE_CHANGE: "workbench.template_change",
    CHOOSE_CONTENT: "workbench.content",
    REVIEW_BINDING: "workbench.binding",
    REVIEW_RECORD_DATA: "workbench.record_data",
    REVIEW_PREVIEW: "workbench.preview",
    REVIEW_DELIVERY: "workbench.delivery",
    EXECUTION_CHECKING: "workbench.execution",
    EXECUTION_STALE: "workbench.execution",
    POLICY_BLOCKED: "workbench.runtime_policy",
    RUNTIME_NOT_ADMITTED: "workbench.runtime_policy",
    CONTEXT_ERROR: "workbench.context_recovery",
}

# CHECKING/FAILED 의 사용자 문안은 downstream(workbench)이 소유한다(automatic_seal_orchestration
# docstring). SETTLED_CURRENT/STALE 은 vocabulary 정본 문안을 쓴다. 전부 순수 한국어라 내부어(Slot/
# Sealed/digest/Plan)를 담지 않는다(#724 §테스트 12).
_CHECKING_PHRASE = "설정을 확인하고 있습니다"
_FAILED_PHRASE = "설정 확인에 실패했습니다. 다시 시도해 주세요"
_RUNTIME_DISABLED_PHRASE = "현재 환경에서는 문서를 만들 수 없습니다"
_POLICY_DISABLED_PHRASE = "정책상 지금은 문서를 만들 수 없습니다"
_CREATE_PREPARATION_DISABLED_PHRASE = "필요한 준비를 먼저 완료해 주세요"


# ══════════════════════════════════════ 입력 DTO(이 모듈 소유) ══════════════════════════════════
@dataclass(frozen=True)
class DataScopeSummary:
    """current data 요약 — 마운트 여부·record scope 요약(실제 데이터 값은 담지 않는다).

    **backend/controller(SX-02)가 채우는 사실**이다. ``mounted`` 는 데이터 소스가 세션에 올라와
    있는지, ``selected_record_count`` 는 표시순서 투영을 통과한 실행 입력 record 수다. raw 값은 담지
    않는다 — 그것은 record_validation/LoadedDataSnapshot 경계 소관이다.
    """

    mounted: bool
    record_scope_required: bool = True
    selected_record_count: int = 0
    total_record_count: int = 0

    def __post_init__(self) -> None:
        if self.selected_record_count < 0 or self.total_record_count < 0:
            raise ValueError("record count 는 음수가 될 수 없다")


@dataclass(frozen=True)
class ContentSelectionSummary:
    """OrderedSelection 요약 — 선택된 content 식별 + 미선택 필수 여부.

    **backend/controller(SX-02)가 채우는 사실**이다. ``has_unselected_required_content`` 는 필수
    Slot 의 내용이 아직 안 골라졌는지의 **이미 판정된** 사실이지 여기서 재판정하지 않는다.
    """

    selected_option_ids: tuple[str, ...] = ()
    has_unselected_required_content: bool = False


@dataclass(frozen=True)
class ActiveWorkContext:
    """active Work/Template Application 식별 + exact context 복원·현재 데이터 사용 가능 플래그.

    **backend/controller(SX-02)가 채우는 사실**이다. ``exact_context_restorable`` 과
    ``usable_with_current_data`` 의 **실제 판정은 SX-05/backend** 가 지고, 여기서는 그 플래그를
    **소비만** 한다(:func:`decide_active_work_after_data_transition`). 후보/추천 신호
    (``unique_candidate_available``·``is_favorite``·``recently_used``·``preferred_work_id``)는
    다른 Work 를 **자동 활성화하는 근거가 아니다**(#724 §9) — 사용자 명시 선택을 대체하지 않는다.
    """

    active: bool
    work_ref: str | None = None
    template_application_ref: str | None = None
    exact_context_restorable: bool = False
    usable_with_current_data: bool = False
    unique_candidate_available: bool = False
    is_favorite: bool = False
    recently_used: bool = False
    preferred_work_id: str | None = None

    def __post_init__(self) -> None:
        if self.active and (not isinstance(self.work_ref, str) or self.work_ref == ""):
            raise ValueError("active Work 는 비어 있지 않은 work_ref 가 필요하다")


@dataclass(frozen=True)
class RecordRecoveryTarget:
    snapshot_generation: int
    record_identity: str
    model_index: int
    field_id: str
    target_kind: str = 'cell'

    def __post_init__(self) -> None:
        if self.target_kind not in ('cell', 'row'):
            raise ValueError('record recovery target kind must be cell or row')
        if self.snapshot_generation < 0 or self.model_index < 0:
            raise ValueError("record recovery target position must be non-negative")
        if not self.record_identity or not self.field_id:
            raise ValueError("record recovery target identity and field are required")


@dataclass(frozen=True)
class RecordValidationIssue:
    record_identity: str
    record_display_locator: str
    field_id: str
    field_display_label: str
    message: str
    recovery_target: RecordRecoveryTarget

    def __post_init__(self) -> None:
        values = (
            self.record_identity,
            self.record_display_locator,
            self.field_id,
            self.field_display_label,
            self.message,
        )
        if any(not value for value in values):
            raise ValueError("record validation issue fields must be non-empty")
        if self.recovery_target.record_identity != self.record_identity:
            raise ValueError("record issue and recovery target identities must match")


@dataclass(frozen=True)
class RecordValidationSummary:
    """record validation 요약 — record_validation 권위(RecordValidationBlocked)의 verdict 를 담는다.

    여기서 record 를 재검증하지 않는다. ``has_blocking_issues`` 는 이미 내려진 판정이고
    ``issue_count`` 는 그 근거 수다. "막힌다"고 하면서 근거 수가 0 이면 hollow 라 시끄럽게 거절한다.
    """

    has_blocking_issues: bool = False
    issue_count: int = 0
    validated_count: int = 0
    blocked_count: int = 0
    issues: tuple[RecordValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.validated_count < 0 or self.blocked_count < 0:
            raise ValueError("record validation counts cannot be negative")
        if self.issues and len(self.issues) != self.issue_count:
            raise ValueError("record validation issue count mismatch")
        if self.issues and (not self.has_blocking_issues or self.blocked_count == 0):
            raise ValueError("record validation issues require blocked records")
        if self.issue_count < 0:
            raise ValueError("issue_count 는 음수가 될 수 없다")
        if self.has_blocking_issues and self.issue_count == 0:
            raise ValueError("has_blocking_issues 면 issue_count 가 1 이상이어야 한다(hollow 금지)")


@dataclass(frozen=True)
class PlannedDocumentSummary:
    """현재 관찰에서 만들 예정인 한 문서. Artifact/reservation/publication 이 아니다."""

    record_identity: str
    item_ordinal: int
    relative_path: str
    collision_disposition: str


@dataclass(frozen=True)
class DeliveryPreviewBlocker:
    code: str
    message: str
    item_ordinal: int | None = None
    field_id: str | None = None
    conflicting_relative_path: str | None = None


@dataclass(frozen=True)
class DeliveryPreviewSummary:
    """delivery 미리보기 요약 — ResolvedGenerationDeliveryPlan 의 사용자 투영(생성 예정 문서).

    ``label`` 과 ``is_artifact`` 는 ClassVar 로 **못박혀** 있다(#724 §7 · #719 D6): 이 요약은
    "생성 예정 문서"(Resolved Delivery)이지 "실제 생성된 결과"(Artifact)가 아니다 — 라벨을
    Artifact 처럼 보이게 바꿀 수 없다. ``resolvable=False`` 는 REVIEW_DELIVERY blocker 다.
    """

    resolvable: bool
    planned_output_names: tuple[str, ...] = ()
    planned_documents: tuple[PlannedDocumentSummary, ...] = ()
    blockers: tuple[DeliveryPreviewBlocker, ...] = ()
    label: ClassVar[str] = USER_VOCABULARY["Resolved Delivery"]  # "생성 예정 문서"
    is_artifact: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if self.resolvable and self.blockers:
            raise ValueError("resolvable delivery cannot have blockers")
        if self.planned_documents and self.planned_output_names != tuple(
            item.relative_path for item in self.planned_documents
        ):
            raise ValueError("planned delivery names and documents must match")


@dataclass(frozen=True)
class WorkbenchContextIntegrity:
    """context/무결성/미지원 복원 실패 신호 — 있으면 CONTEXT_ERROR 로 표현한다(user blocker 아님).

    ``restore_failure=True`` 는 작업대를 정합하게 구성할 수 없는 hard 실패다. 그때 code·detail 이
    비어 있으면 hollow context error 라 거절한다(#724 §테스트 3: 조용히 틀리지 않는다).
    """

    restore_failure: bool
    code: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.restore_failure and (self.code == "" or self.detail == ""):
            raise ValueError("restore_failure 면 code·detail 이 필요하다(hollow context error 금지)")


@dataclass(frozen=True)
class HistoricalOutcomeSummary:
    """historical command outcome 의 **부차** 요약 — 당시 사건 증거로만 보존(#724 §11 · #719 D9).

    현재 화면·Primary Action 을 **결정하지 못한다**. fresh observation 이 지배하고 이 필드는 진단용
    이라 사용자 문안 축(``user_facing_texts``)에 들어가지 않는다. ``outcome_kind`` 는 내부 코드
    (예: PLAN_PUBLISHED)라 기본 사용자 표면에 노출되지 않는다.
    """

    outcome_kind: str
    observed_at: str

    def __post_init__(self) -> None:
        for name in ("outcome_kind", "observed_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{name} 는 비어 있지 않은 문자열이어야 한다")


@dataclass(frozen=True)
class DeepLinkTarget:
    """blocker → exact deep-link route. ``route`` 는 내부 route id(사용자 문안 아님)."""

    blocker_code: str
    route: str


@dataclass(frozen=True)
class InputRequirement:
    """Backend-authored Active Field/Binding review item for passive UI rendering."""

    field_id: str
    display_label: str
    binding_state: str
    exact_target: str

    def __post_init__(self) -> None:
        if not self.field_id or not self.display_label:
            raise ValueError("field_id/display_label must be non-empty")
        if self.binding_state not in (PRESERVED, BROKEN, NEW_ACTIVE_FIELD, INACTIVE_ONLY):
            raise ValueError(f"unknown binding_state: {self.binding_state!r}")
        if self.exact_target != f"binding/{self.field_id}":
            raise ValueError("exact_target must identify the exact Binding field")

    @property
    def action_required(self) -> bool:
        return self.binding_state in (BROKEN, NEW_ACTIVE_FIELD)


# ══════════════════════════════════════ 합성 입력 aggregate ═════════════════════════════════════
@dataclass(frozen=True)
class WorkbenchCompositionInput:
    """composer 입력 aggregate — 이미 판정된 권위 verdict + 이 모듈 소유 요약 DTO 를 모은다.

    이 안의 verdict 축(``admission``·``preview_requirement``·``orchestration``·
    ``template_change_verdict``)은 backend 권위가 이미 내린 값이다 — composer 는 재판정하지 않고
    합성만 한다. R2(#740): currentness 축은 orchestration 으로 흡수됐다(current value 는 자명히
    현재라 별도 currentness 입력이 없다 — CURRENT/STALE 은 orchestration 상태가 나른다).
    ``run_delivery_intent`` 는 session-scoped 라 Plan/VDR identity 에 들어가지 않는다
    (#724 §8) — delivery preview 맥락으로만 실린다.
    """

    data_scope: DataScopeSummary
    content_selection: ContentSelectionSummary
    active_work: ActiveWorkContext
    admission: RuntimePolicyAdmission
    orchestration: AutomaticSealOrchestration
    preview_requirement: PreviewRequirement
    delivery: DeliveryPreviewSummary
    record_validation: RecordValidationSummary = field(default_factory=RecordValidationSummary)
    template_change_verdict: str | None = None
    active_field_requirement_ids: tuple[str, ...] = ()
    binding_review_needed: bool = False
    input_requirements: tuple[InputRequirement, ...] = ()
    preview_satisfied: bool = False
    semantic_preview: SemanticValuePreviewProjection | None = None
    run_delivery_intent: RunDeliveryIntent | None = None
    context_integrity: WorkbenchContextIntegrity | None = None
    historical_outcome: HistoricalOutcomeSummary | None = None


# ══════════════════════════════════════ 결과 타입 ══════════════════════════════════════════════
@dataclass(frozen=True)
class DocumentCreationWorkbenchContextError:
    """context/무결성/미지원 복원 실패 — user-fixable DOMAIN blocker 로 **낮추지 않는다**(#724 §테스트 3).

    ``user_fixable=False`` 와 ``primary_action=RECOVER_CONTEXT`` 를 ClassVar 로 못박아, 이 실패의
    다음 행동은 언제나 복구지 사용자가 데이터/내용/Binding 을 고쳐 넘어가는 길이 아님을 타입 수준에서
    보장한다.
    """

    code: str
    detail: str
    user_fixable: ClassVar[bool] = False
    primary_action: ClassVar[str] = RECOVER_CONTEXT

    def __post_init__(self) -> None:
        for name in ("code", "detail"):
            value = getattr(self, name)
            if not isinstance(value, str) or value == "":
                raise ValueError(f"{name} 는 비어 있지 않은 문자열이어야 한다")


@dataclass(frozen=True)
class DocumentCreationWorkbenchObservation:
    """사용자 작업대 상태 + 다음 행동의 비영속 projection(#724 §2).

    새 durable state·``current_plan_id``·UI-only validity 가 아니다. 필드는 세 부류다:
    (a) 이미 정한 것/다음에 정할 것 요약, (b) 이미 판정된 실행 verdict(재판정 아님), (c) 합성 결과
    (blockers·primary_action·disabled_reason·deep-link). ``historical_outcome`` 은 **부차** 필드로만
    실리고 main 상태·primary_action 을 지배하지 못한다(fresh 지배 — #724 §11).
    """

    # (a) 이미 정한 것 / 다음에 정할 것
    data_scope: DataScopeSummary
    content_selection: ContentSelectionSummary
    active_work: ActiveWorkContext
    active_field_requirement_ids: tuple[str, ...]
    # (b) 이미 판정된 실행 verdict — 재판정 아님(권위 shape 그대로)
    input_requirements: tuple[InputRequirement, ...]
    # R2(#740): currentness 축은 orchestration 으로 흡수(별도 필드 없음).
    admission: RuntimePolicyAdmission
    materialization_readiness: str  # decide_materialization_readiness 권위 함수 결과
    orchestration: AutomaticSealOrchestration
    record_validation: RecordValidationSummary
    preview_requirement: PreviewRequirement
    preview_satisfied: bool
    delivery: DeliveryPreviewSummary
    semantic_preview: SemanticValuePreviewProjection | None
    run_delivery_intent: RunDeliveryIntent | None
    # (c) 합성 결과
    blockers: tuple[str, ...]
    primary_action: str
    disabled_reason: str | None
    deep_link_targets: tuple[DeepLinkTarget, ...]
    # 사용자 문안(vocabulary 정본)
    content_section_label: str
    input_requirements_label: str
    execution_status_phrase: str
    delivery_label: str
    # 부차 — main 지배 아님
    historical_outcome: HistoricalOutcomeSummary | None = None

    @property
    def primary_action_enabled(self) -> bool:
        """Primary Action 이 지금 사용자가 완료 가능한지 — disabled_reason 이 있으면 비활성(숨김 아님)."""
        return self.disabled_reason is None

    @property
    def create_documents_enabled(self) -> bool:
        """Derived Create capability; not a durable readiness authority."""
        return self.primary_action == CREATE_DOCUMENTS and self.primary_action_enabled

    @property
    def create_documents_disabled_reason(self) -> str | None:
        """Explain the Create CTA independently of Primary Action precedence."""
        if self.create_documents_enabled:
            return None
        if self.admission.state == NOT_ADMITTED:
            if _has_runtime_reason(self.admission):
                return _RUNTIME_DISABLED_PHRASE
            return _POLICY_DISABLED_PHRASE
        return _CREATE_PREPARATION_DISABLED_PHRASE

    @property
    def user_facing_texts(self) -> tuple[str, ...]:
        """사용자 대면 문안 필드만 모은다 — 내부어 노출 0 계약(#724 §테스트 12)의 스캔 대상.

        blocker/primary_action 코드·deep-link route·진단 필드(admission.reasons·
        historical outcome_kind)는 사용자 문안이 아니므로 여기 들지 않는다.
        """
        texts = [
            self.content_section_label,
            self.input_requirements_label,
            self.execution_status_phrase,
            self.delivery_label,
            self.delivery.label,
        ]
        if self.disabled_reason is not None:
            texts.append(self.disabled_reason)
        if self.create_documents_disabled_reason is not None:
            texts.append(self.create_documents_disabled_reason)
        if self.semantic_preview is not None:
            texts.append(self.semantic_preview.label)
        for issue in self.record_validation.issues:
            texts.extend((issue.record_display_locator, issue.field_display_label, issue.message))
        texts.extend(blocker.message for blocker in self.delivery.blockers)
        return tuple(t for t in texts if t != "")


GetDocumentCreationWorkbenchResult = (
    DocumentCreationWorkbenchObservation | DocumentCreationWorkbenchContextError
)

# ══════════════════════════════════════ data transition 규칙(#724 §9 · D4) ═════════════════════
KEEP = "KEEP"
RELEASE = "RELEASE"


@dataclass(frozen=True)
class ActiveWorkTransitionDecision:
    """data transition 뒤 active Work 유지·해제 판정 — 다른 Work 를 **자동 활성화하지 않는다**.

    ``auto_activated_work_ref`` 는 타입이 ``None`` 으로 못박혀 있다 — 유일 후보·즐겨찾기·최근 사용·
    preferredWorkId 어느 것도 다른 Work 를 켜지 못한다는 계약(#724 §9)을 타입 수준에서 보장한다.
    RELEASE 면 컨트롤러가 후보/추천만 보이고 사용자 명시 선택을 기다린다.
    """

    disposition: str  # KEEP | RELEASE
    auto_activated_work_ref: None = None


def decide_active_work_after_data_transition(
    ctx: ActiveWorkContext,
) -> ActiveWorkTransitionDecision:
    """기존 active Work 유지 여부 — exact context 복원 가능 **and** 현재 데이터 사용 가능일 때만 KEEP.

    그 밖에는 RELEASE 하고, 후보/추천 신호가 있어도 **다른 Work 를 자동 활성화하지 않는다**(#724 §9).
    복원 가능성 판정 자체는 재구현하지 않는다 — ``ctx`` 의 플래그(backend/SX-05 가 채운 사실)를 소비만
    한다.
    """
    if ctx.active and ctx.exact_context_restorable and ctx.usable_with_current_data:
        return ActiveWorkTransitionDecision(disposition=KEEP)
    return ActiveWorkTransitionDecision(disposition=RELEASE)


# ══════════════════════════════════════ blocker / primary action 합성 ═══════════════════════════
def _has_policy_reason(admission: RuntimePolicyAdmission) -> bool:
    return bool(set(admission.reasons) & _POLICY_ADMISSION_REASONS)


def _has_runtime_reason(admission: RuntimePolicyAdmission) -> bool:
    return bool(set(admission.reasons) & _RUNTIME_ADMISSION_REASONS)


def binding_review_needed(
    *, blocker_signal: bool, input_requirements: "tuple[InputRequirement, ...]"
) -> bool:
    """``REVIEW_BINDING`` 이 서는 **그 술어** — 이 이름 하나가 조건의 단일 출처다(#911).

    두 갈래의 OR 이다: 봉인 판정이 결속 축 blocker 를 낸 경우와, 현재 Active Field 분류표에
    조치가 필요한 항목이 있는 경우. 함수로 뽑은 이유는 소비자가 둘이 됐기 때문이다 —
    :func:`compose_blockers` 가 관리 검토 사슬에 세우고, 편집기 footer 가 같은 사실로 무변경
    확정 동사를 무장한다. 두 자리가 각자 조건을 조립하면 「확정하라고 하는데 확정 동사가
    없다」(#911) 또는 그 거울상(「확정할 것이 없는데 동사가 서 있다」)이 조용히 생긴다.
    """
    return blocker_signal or any(item.action_required for item in input_requirements)


def compose_blockers(inp: WorkbenchCompositionInput) -> tuple[str, ...]:
    """여러 blocker 를 **동시에 보존**해 BLOCKER_CODES 순서로 낸다(#724 §테스트 2).

    각 blocker 는 이미 판정된 verdict/요약을 **읽어서만** 세운다 — 여기서 currentness·admission·
    record validity·preview·delivery 를 재판정하지 않는다. CONTEXT_ERROR 는 이 함수가 세우지 않는다:
    context error 는 :func:`compose_document_creation_workbench` 가 observation 이 아니라
    :class:`DocumentCreationWorkbenchContextError` 로 표현한다(user blocker 로 낮추지 않는다).
    """
    present: set[str] = set()

    # 데이터 / 레코드
    if not inp.data_scope.mounted:
        present.add(SELECT_DATA)
    elif inp.data_scope.record_scope_required and inp.data_scope.selected_record_count == 0:
        present.add(SELECT_RECORDS)

    # Work / Template change / content / Binding
    if not inp.active_work.active:
        present.add(SELECT_WORK)
    if inp.template_change_verdict in (REVIEW_REQUIRED, DETACHED):
        present.add(REVIEW_TEMPLATE_CHANGE)
    if inp.content_selection.has_unselected_required_content:
        present.add(CHOOSE_CONTENT)
    if binding_review_needed(
        blocker_signal=inp.binding_review_needed,
        input_requirements=inp.input_requirements,
    ):
        present.add(REVIEW_BINDING)

    # record / delivery / preview
    if inp.record_validation.has_blocking_issues:
        present.add(REVIEW_RECORD_DATA)
    if not inp.delivery.resolvable:
        present.add(REVIEW_DELIVERY)
    if isinstance(inp.preview_requirement, PreviewRequired) and not inp.preview_satisfied:
        present.add(REVIEW_PREVIEW)

    # execution(checking / stale) — orchestration verdict(R2(#740): currentness 축 흡수).
    # STALE 은 orchestration STALE/FAILED 가 나른다(durable command 가 settle 됐으나 재확인 필요).
    if inp.orchestration.state == CHECKING:
        present.add(EXECUTION_CHECKING)
    if inp.orchestration.state in (ORCHESTRATION_STALE, FAILED):
        present.add(EXECUTION_STALE)

    # runtime / policy — admission verdict(재판정 아님)
    if inp.admission.state == NOT_ADMITTED:
        policy = _has_policy_reason(inp.admission)
        runtime = _has_runtime_reason(inp.admission)
        if policy:
            present.add(POLICY_BLOCKED)
        if runtime:
            present.add(RUNTIME_NOT_ADMITTED)
        if not policy and not runtime:
            # NOT_ADMITTED 인데 알려진 사유가 없다 — 조용히 드롭하지 않고 runtime 축으로 시끄럽게.
            present.add(RUNTIME_NOT_ADMITTED)

    return tuple(code for code in BLOCKER_CODES if code in present)


def compose_primary_action(blockers: tuple[str, ...]) -> str:
    """#724 §3 우선순위 사슬로 **정확히 하나**의 Primary Action 을 낸다.

    ``blockers`` 중 사슬 순서에서 가장 앞서는 하나를 골라 그 Primary Action 을 반환한다. 아무 blocker 도
    없으면 종단 ``CREATE_DOCUMENTS``. 반환은 언제나 :data:`PRIMARY_ACTION_CODES` 의 한 원소다.
    """
    present = set(blockers)
    for blocker_code, action_code in _PRIMARY_ACTION_CHAIN:
        if blocker_code in present:
            return action_code
    return CREATE_DOCUMENTS


def _compose_deep_links(blockers: tuple[str, ...]) -> tuple[DeepLinkTarget, ...]:
    return tuple(
        DeepLinkTarget(blocker_code=code, route=_DEEP_LINK_ROUTES[code]) for code in blockers
    )


def _disabled_reason(
    primary_action: str, inp: WorkbenchCompositionInput
) -> str | None:
    """비활성 Primary Action 은 숨기지 않고 사유와 함께 낸다(#724 §3 · #719 D10·D30).

    runtime/policy 는 사용자가 지금 해소할 수 없어 disabled + 사유(S6 부재를 READY 로 과장 금지).
    execution checking 은 자동 진행 중이라 잠시 disabled. 그 밖의 Primary Action(SELECT_*·REVIEW_*·
    CHOOSE_CONTENT·RECOVER_CONTEXT·CREATE_DOCUMENTS)은 사용자가 완료 가능하므로 사유 없음.
    """
    if primary_action == RESOLVE_RUNTIME_POLICY:
        if _has_runtime_reason(inp.admission):
            return _RUNTIME_DISABLED_PHRASE
        return _POLICY_DISABLED_PHRASE
    if primary_action == RESOLVE_EXECUTION and inp.orchestration.state == CHECKING:
        return _CHECKING_PHRASE
    return None


def _execution_status_phrase(inp: WorkbenchCompositionInput) -> str:
    """실행 상태 사용자 문안 — orchestration verdict 에서 파생(R2(#740): currentness 흡수, 새 판정 아님)."""
    if inp.orchestration.state == CHECKING:
        return _CHECKING_PHRASE
    if inp.orchestration.state == FAILED:
        return _FAILED_PHRASE
    if inp.orchestration.state == ORCHESTRATION_STALE:
        return USER_VOCABULARY["Plan stale"]
    if inp.orchestration.state == SETTLED_CURRENT:
        return USER_VOCABULARY["Plan current"]
    return ""


# ══════════════════════════════════════ top-level composer ═════════════════════════════════════
def compose_document_creation_workbench(
    inp: WorkbenchCompositionInput,
) -> GetDocumentCreationWorkbenchResult:
    """S3/S4/S5 권위 상태 + 사용자 요약 → 하나의 작업대 Observation(또는 ContextError).

    **context error 는 절대 user-fixable DOMAIN blocker 로 낮추지 않는다**(#724 §테스트 3): hard
    integrity 신호나 admission 의 CONTEXT_ERROR verdict 는
    :class:`DocumentCreationWorkbenchContextError` 로 표현한다(그 다음 행동은 RECOVER_CONTEXT). 그
    밖에는 blocker 를 **동시에 보존**하고 Primary Action 을 §3 사슬로 정확히 하나 골라 Observation 을
    낸다. admission/preview/orchestration/record/delivery 는 전부 이미 내려진 verdict 를
    합성만 한다 — 재판정 없음. readiness 는 :func:`decide_materialization_readiness` 권위 함수로 파생.
    R2(#740): fresh observation 축 실패(ExecutionObservationContextError)는 ring2(observation
    product)가 admission=CONTEXT_ERROR 로 넘겨 이 경로가 ContextError 로 표현한다.
    """
    # 1) hard context/무결성/미지원 복원 실패 → ContextError(user blocker 아님).
    if inp.context_integrity is not None and inp.context_integrity.restore_failure:
        return DocumentCreationWorkbenchContextError(
            code=inp.context_integrity.code, detail=inp.context_integrity.detail
        )
    # 2) sub-axis(admission) CONTEXT_ERROR verdict → 역시 ContextError(정합한 작업대 불가).
    if inp.admission.state == ADMISSION_CONTEXT_ERROR:
        detail = ", ".join(inp.admission.reasons) or "실행 승인 판정을 복원할 수 없습니다"
        return DocumentCreationWorkbenchContextError(
            code="EXECUTION_ADMISSION_CONTEXT_ERROR", detail=detail
        )

    # 3) 정합한 Observation 합성.
    blockers = compose_blockers(inp)
    primary_action = compose_primary_action(blockers)
    readiness = decide_materialization_readiness(inp.admission)

    return DocumentCreationWorkbenchObservation(
        data_scope=inp.data_scope,
        content_selection=inp.content_selection,
        active_work=inp.active_work,
        active_field_requirement_ids=inp.active_field_requirement_ids,
        admission=inp.admission,
        input_requirements=inp.input_requirements,
        materialization_readiness=readiness,
        orchestration=inp.orchestration,
        record_validation=inp.record_validation,
        preview_requirement=inp.preview_requirement,
        preview_satisfied=inp.preview_satisfied,
        delivery=inp.delivery,
        semantic_preview=inp.semantic_preview,
        run_delivery_intent=inp.run_delivery_intent,
        blockers=blockers,
        primary_action=primary_action,
        disabled_reason=_disabled_reason(primary_action, inp),
        deep_link_targets=_compose_deep_links(blockers),
        content_section_label=USER_VOCABULARY["Slot"],
        input_requirements_label=USER_VOCABULARY["Active Field"],
        execution_status_phrase=_execution_status_phrase(inp),
        delivery_label=USER_VOCABULARY["Resolved Delivery"],
        historical_outcome=inp.historical_outcome,
    )


__all__ = [
    "RecordRecoveryTarget",
    "RecordValidationIssue",
    "DataScopeSummary",
    "ContentSelectionSummary",
    "ActiveWorkContext",
    "RecordValidationSummary",
    "DeliveryPreviewSummary",
    "DeliveryPreviewBlocker",
    "PlannedDocumentSummary",
    "WorkbenchContextIntegrity",
    "HistoricalOutcomeSummary",
    "DeepLinkTarget",
    "WorkbenchCompositionInput",
    "InputRequirement",
    "DocumentCreationWorkbenchObservation",
    "DocumentCreationWorkbenchContextError",
    "GetDocumentCreationWorkbenchResult",
    "ActiveWorkTransitionDecision",
    "decide_active_work_after_data_transition",
    "compose_blockers",
    "compose_primary_action",
    "compose_document_creation_workbench",
    "KEEP",
    "RELEASE",
]
