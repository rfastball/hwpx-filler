"""「작업」 화면 컨트롤러 — 좌 작업 목록 + 우 세션 패널 4존(webview 비의존).

R-flow 구현 라운드(에픽 #90). R-info 1부가 확정한 「작업」 화면(변형 B master-detail: 좌
목록 + 우 4존 세션 패널)의 착지. 이 컨트롤러는 **링2 표면**이다 — 실행 화면(``screen_run.py``,
슬라이스 3에서 사망)을 재사용하지 않고 링1 VM 을 **직접 임포트**해 구동한다(부록 A: "계약
대부분은 링1이 소유하고, 죽는 것은 링2 표면뿐" — 그 링2 표면이 죽어 이제 여기가 유일 소비처).
실행 결정(데이터 로드·사전검증·3상태 배지·강제 확인 게이트·생성 계획)은
:class:`~hwpxfiller.gui.run_state.RunViewModel`(Qt-free), 레코드 선택은
:class:`~hwpxfiller.gui.selection_state.SelectionModel`(Qt-free)이 소유한다 — 재구현 금지(#87).

**4존 스냅샷**: 헤더(작업 정체)·데이터(겨눔·행 선택)·본문(필드 배지 거울·게이트)·완료(생성
결과 세션 스코프). 존은 표현 구조라 job.js 가 필드를 배치한다 — 스냅샷 필드는 실행 화면과
평행해 링1 배선이 감사 가능하다(같은 refresh/게이트/생성 계약 소비).

**네이티브 표면 동형**: ``load_data_path``·``set_output_folder``·``generate``·``render`` 시그니처를
실행 화면과 같게 유지해 브리지(:mod:`~hwpxfiller.webapp.app`)의 화면-파라미터 네이티브 헬퍼
(``pick_data_file``·``load_data_sheet``·``pick_output_folder``·``generate``)를 등록 한 줄로 재사용한다.

**후속 슬라이스**(confirm-or-alarm: 없는 기능을 있는 척하지 않는다) — 아직 이 패널에 없는 것:
- 좌 목록의 2구획 틴트·group-by 렌즈·컴파일 배지 등 풍부화(홈 브라우저 VM 채택).
- 건 연속성 직전 필터 재적용(블록 4 결정 28, PR-4)·txt 큐(블록 3)·빠른 기안(블록 5).
- 세션 가드의 유보 성분: **T2**(마법사 인계 비파괴화 — 에디터 접합, 슬라이스 5)·수동 필드
  입력 성분(블록 5, 슬라이스 7). **T3**(큐 부분 진행)은 검토·복사 작업대가 진다(F6 —
  구 기안 세션 공용 본체의 승계처). 술어 몸통은 이 화면과
  공유(:meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin._selection_guard`).
(슬라이스 2 착지분 — 게이트 재진술 블록·거울 채움 테이블·덮어쓰기 modal.js 수치 합성·식별
요약 링1 :func:`~hwpxfiller.domain.identity_summary.identity_summary`(#88, A-1-15) — 과
슬라이스 4 착지분 — 필터 선언 표면(결정 23~25)·세션 가드 T1+데이터 재겨눔(결정 26·27,
T4=가드 불요·T5=수용 손실) — 은 본문에 배선돼 있다.)

**스코프 경계 — 미구현 명시(#89, A-4-33)**: ``screen_run.py`` 경계 절을 승계한다 — 나라·
RC-06·생성 원장 항은 **원문 그대로**, 이어채우기 항만 실행 화면 사망으로 맥락을 반영해
**재기술**했다(원문의 "실행 화면에선 강등/숨김"이 이제 거짓이라 verbatim 불가). 아래는 링1
seam 은 존치하나 이 패널이 노출하지 않는다. "없는 기능을 있는 척하지 않는다"의 명문이며,
표면(실행 화면)이 죽어도 이 경계 선언은 죽지 않는다(F40 전례 방지):
- 나라장터 소스 겨눔(동결 해제 시 재배선)·나라 애드혹 취득.
- 기존 문서 이어채우기(#18 결정으로 강등/숨김 — seam 은 링1 ``target_mode``/``set_prev_output``
  게이트 술어에 잔존, A-4-32).
- 생성 원장 opt-in. 협조적 취소(RC-06)는 #220에서 건 경계 중단으로 배선됐다.
덮어쓰기 확인·미입력 강제 확인 게이트·구조 드리프트 차단·미입력 표식·다중 시트 확정
게이트(#33)는 모두 포함한다.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
from datetime import datetime
from pathlib import Path
import threading

from ..application.generation import (
    GenerationRun,
    blank_marker,
    plan_generation,
    run_generation,
    start_run,
)
from ..application.jobs import (
    JobStorePort,
    assign_group,
    disband_group,
    group_member_count,
    job_content_fingerprint,
    job_exists,
    job_names,
    list_jobs,
    load_job,
    rename_group,
    rename_job,
    set_favorite,
)
from ..domain.engine import HwpxEngine
from ..application.execution_contract_set import (
    execution_basis_digest,
    plan_semantic_digest,
)
from ..domain.identity_summary import identity_summary
from ..external.artifact_observation import (
    ArtifactObservationRefused,
    observe_delivered_artifact,
)
from ..external.delivery_coordinator import (
    DeliveredDocument,
    DeliveryAborted,
    DeliveryCompleted,
    DeliveryRefused,
)
from ..gui.artifact_view_state import observed_artifact_snapshot
from ..external.ledger_export import write_managed_delivery_ledger
from .managed_generation import (
    ManagedReadBackFailed,
    ManagedRunCancelled,
    ManagedRunRefused,
    run_managed_generation,
)
from ..domain.job import (
    Job,
    rules_fingerprints,
    work_mode,
)
from ..domain.mapping import SOURCE_CARRIER_TYPES
from ..domain.template_status import OUTPUT_SUBDIR_NAME
from ..gui.filter_state import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_TEXT,
    FilterModel,
)
from ..gui.result_errors import classify_result_error, describe_fill_note
from ..naming import pattern_uses_seq
from ..gui.record_range import RecordRange, RecordRangeDraft
from ..gui.review_state import (
    ReviewRequirement,
    ReviewState,
    build_evidence,
    review_gate_text,
    previous_values,
    review_requirement,
)
from ..gui.run_state import (
    FileSourceFactoryPort,
    PoolSourceFactoryPort,
    RunViewModel,
    resolve_file_source,
    resolve_pool_source,
    template_missing,
)
from ..gui.selection_state import SelectionModel
from ..gui.work_mode import (
    WORK_MODE_TEXT,
    last_use_label,
    mode_sections,
    seat_kinds,
    work_mode_label,
)
from ..gui.work_candidates import (
    KIND_AVAILABLE,
    KIND_NEEDS_ACTION,
    MAIN_TOP_N,
    TAB_AVAILABLE,
    TAB_NEEDS_ACTION,
    browse_candidates,
    candidate_rows,
    compatibility_for,
    prework_gate,
    unsupported_media_gate,
    workbench_entry_gate,
    preferred_promotion,
    rank_available,
    suggested_work,
)
from .action_registry import ZONE_MUTATIONS
from .template_change import TemplateChangeError, unsupported_zone
from ..application.slotless_run_bridge import SlotlessRunAdmissionError
# S4 Working Slot Configuration 배선(SX-02 #725) — Product/Observation 소비만(재구현 금지).
from dataclasses import asdict, dataclass
import uuid
from ..application.automatic_seal_orchestration import (
    FAILED as ORCHESTRATION_FAILED,
    SETTLED_CURRENT as ORCHESTRATION_SETTLED_CURRENT,
    AutomaticSealOrchestration,
    on_durable_command_settled,
    on_seal_settled,
    request_manual_recovery,
)
from ..application.document_creation_workbench import (
    ActiveWorkContext,
    DeliveryPreviewBlocker,
    DeliveryPreviewSummary,
    DocumentCreationWorkbenchContextError,
    HistoricalOutcomeSummary,
    PlannedDocumentSummary,
    RecordRecoveryTarget,
    RecordValidationIssue,
    RecordValidationSummary,
    RELEASE,
    RESOLVE_EXECUTION,
    WorkbenchContextIntegrity,
    decide_active_work_after_data_transition,
)
from ..application.generation_delivery import (
    DeliveryPlanBlocked,
    DeliveryPlanContextError,
    FILENAME_PATTERN_CONTRACT_ID,
    GenerationDeliveryBindingBasis,
    NON_REGULAR,
    PathOccupancyEntry,
    PathOccupancyObservation,
    REGULAR_FILE,
    CurrentResolvedDelivery,
    build_delivery_binding_basis,
    resolve_current_generation_delivery,
)
from ..application.preview_requirement import (
    CurrentPreviewPreparationError,
    PreviewNotRequired,
    PreviewRequired,
    PreviewRequirement,
    SemanticValuePreviewProjection,
    build_current_preview_projection,
    evaluate_current_preview_requirement,
)
from ..application.fresh_execution_observation import (
    CurrentSealedPlanObservation,
    CurrentWorkExecutionObservation,
    ExecutionObservationContextError,
    FreshExecutionObservation,
)
from ..application.execution_semantic_kernel import SealedExecutionPlanValue
from ..application.record_validation import (
    CurrentValidatedDataRecord,
    RECORD_BLANK_POLICY_VIOLATION,
    RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED,
    RECORD_EXPLICIT_NULL_NOT_ALLOWED,
    RECORD_REQUIRED_VALUE_MISSING,
    RECORD_VALUE_FORMAT_INVALID,
    RECORD_VALUE_TYPE_INVALID,
    RecordValidationBlocked,
    RecordValidationContextError,
    RecordValidationBlocker,
    validate_data_records_against_current_value,
)
from ..application.run_delivery_intent import (
    ADD_SUFFIX,
    RunDeliveryIntent,
)
from ..application.field_binding_input import FieldBindingInput
from ..domain.raw_data_record import (
    RawDataRecordSnapshot,
    RawDataRecordError,
    RawRecordCaptureProvenance,
    SourceBoolean,
    SourceDate,
    SourceDateTime,
    SourceDecimal,
    SourceNull,
    SourceText,
    build_raw_record_snapshot,
)
from ..domain.field_binding import (
    BOOLEAN,
    DATE,
    DATETIME,
    DECIMAL,
    EXACT_TEXT,
    FieldBindingError,
)
from .seal_execution_plan_product import ExecutionPlanSealedProductOutcome
from .slot_configuration_product import SlotConfigurationProductError

# managed 생성 admission 차단 코드 → 사용자 문안(confirm-or-alarm — 조용한 fallback 없음).
_ADMISSION_REJECT_TEXT = {
    "TEMPLATE_INITIALIZATION_REQUIRED": "이 템플릿을 문서 작업으로 초기화할 수 없어 생성할 수 없습니다. 템플릿 파일을 확인하세요.",
    "NEEDS_CONFIGURATION_REVIEW": "실행 구성 출처를 확인할 수 없어 생성을 멈췄습니다. 구성을 검토하세요.",
    "NEEDS_CONFIGURATION": "템플릿이 바뀌어 실행 구성을 다시 확인해야 생성할 수 있습니다.",
    "STALE_TEMPLATE_APPLICATION": "적용된 템플릿 판본이 최신이 아니라 생성을 멈췄습니다.",
    "SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE": "이 템플릿의 슬롯 구성 실행은 아직 지원하지 않습니다.",
    "SLOTLESS_SELECTION_CONTEXT_REQUIRED": "슬롯 없는 실행 맥락을 확립하지 못해 생성할 수 없습니다.",
    "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR": "적용된 템플릿 바이트 무결성 확인에 실패해 생성을 멈췄습니다.",
}
from .job_list import drift_note
from ..external.settings import recollapse_job_group
from .data_zone import (
    EMPTY_FILTER as _EMPTY_FILTER,
    EMPTY_TABLE as _EMPTY_TABLE,
    DataZoneMixin,
)
from .screens import (
    NO_ROWS_TEXT,
    PoolTargetingMixin,
    PushSink,
    relink_job_template,
    source_label,
)

# 사전검증 성공 문구는 링2 사용자 어휘로 순화한다(실행 화면 _PREFLIGHT_OK_TEXT 동형).
_PREFLIGHT_OK_TEXT = "검증 완료. 생성할 수 있습니다."

#: 「연결 상태」 문안(U2 §4 판정 C, #342) — 텍스트가 정본이고 색은 강조다. 세션 축과 후보
#: 카드가 **같은 문자열**을 써야 같은 상태를 두 이름으로 부르지 않는다.
_CONN_MISSING_LABEL = "템플릿 없음"


def _template_conn(path: str) -> "tuple[bool, str]":
    """템플릿 연결 상태 ``(부재인가, 「연결 상태」 문안)`` — **단일 술어·단일 문안**.

    #342 리뷰 3라운드의 근본 조치다. 종전엔 같은 질문을 세 자리가 각자 답했고 술어까지
    갈렸다 — 스냅샷 vm-None 가지는 ``bool(path) and not exists`` 라 **빈 경로를 정상**으로
    보고했는데, 후보 카드는 ``not path or not exists`` 라 같은 작업을 「템플릿 없음」으로
    그렸다. 사망 점검표는 「찾을 수 없음」과 「경로가 비어 있음」을 **한 축**(연결 상태)에
    승계시켰으므로 술어도 하나여야 한다: 둘 다 "이 작업으로는 문서를 만들 수 없다"이고
    복구 동선도 같은 재연결이다. 술어 몸통은 링1
    (:func:`~hwpxfiller.gui.run_state.template_missing`)이 소유하고(P2-24), 여기는 문안만.

    호출측이 ``has_job`` 을 이미 알고 있다(작업이 없으면 물을 대상 자체가 없다).
    """
    missing = template_missing(path)
    return missing, (_CONN_MISSING_LABEL if missing else "")


#: 산출물 관찰이 **세션 좌표에서** 서지 않았다(S7-03 · #825). 커널 거절 셋
#: (:mod:`~hwpxfiller.external.artifact_observation`)과 겹치지 않는 넷째 상태다: 파일이
#: 어떤가를 묻기도 전에 「그 문서가 이 세션 결과에 없다」로 끝난 경우다. 조용한 무시로
#: 접지 않는 이유는 #775 교훈 그대로 — 준비 안 됨과 무결성 실패는 같은 빈 화면이 아니다.
ARTIFACT_NOT_IN_SESSION = "ARTIFACT_NOT_IN_SESSION"

#: 관찰이 성립한 상태의 이름표. 거절 코드와 같은 축에 실려 화면이 한 값으로 분기한다.
ARTIFACT_OBSERVED = "observed"

# 데이터 미겨눔 상태의 재진술 빈 골격 — 필터/테이블 골격은 데이터 존 공유 믹스인
# (data_zone.EMPTY_*)이 소유한다(PR-2b).
_EMPTY_RESTATE = {
    "origin": None, "filter_active": False, "in_def": 0, "extra": 0, "sample": [],
}

# 재진술 이름 목록 표본 크기 — 소량(≤N)=전부, 대량=층화 표본 N + 「외 …건 펼치기」(결정 5·36).
_RESTATE_SAMPLE = 3

# 전체 표시순서 2값(§18.10) — ``snapshotOrdinal``(=로드 순서 index) 내림/오름차순.
# 정렬 키가 정수라 **동률이 원리적으로 없다** — 2차 정렬 규칙이 필요 없고 두 값은 정확한
# 역이다(지도 §10.11.1 정밀도 면). 새 값을 늘리려면 그 성질부터 다시 센다.
VIEW_ORDER_DESC = "sourceDesc"
VIEW_ORDER_ASC = "sourceAsc"
VIEW_ORDERS = (VIEW_ORDER_DESC, VIEW_ORDER_ASC)


@dataclass(frozen=True)
class _CurrentRecordPreparation:
    snapshot_generation: int
    work_ref: str
    ordered_model_indices: tuple[int, ...]
    execution_value: SealedExecutionPlanValue
    raw_records: tuple[RawDataRecordSnapshot, ...]
    validated_records: tuple[CurrentValidatedDataRecord, ...]
    record_validation: RecordValidationSummary


@dataclass(frozen=True)
class _CurrentDeliveryPreparation:
    record_preparation: _CurrentRecordPreparation
    current_field_binding: FieldBindingInput
    exact_pattern: str
    run_delivery_intent: RunDeliveryIntent
    captured_delivery_clock: str
    result: CurrentResolvedDelivery | DeliveryPlanBlocked | DeliveryPlanContextError


@dataclass(frozen=True)
class _CurrentPreviewPreparation:
    record_preparation: _CurrentRecordPreparation
    delivery_preparation: _CurrentDeliveryPreparation
    requirement: PreviewRequirement
    projection: SemanticValuePreviewProjection
    preview_token: str


class _CurrentRecordCaptureError(ValueError):
    pass


def _capture_source_value(value: object, declared_type: str | None):
    if value is None:
        return SourceNull()
    if not isinstance(value, str):
        raise _CurrentRecordCaptureError('데이터 값을 정확히 읽을 수 없습니다.')
    if declared_type in (None, EXACT_TEXT):
        return SourceText(value)
    try:
        if declared_type == DECIMAL:
            return SourceDecimal(value)
        if declared_type == DATE:
            return SourceDate(value)
        if declared_type == DATETIME:
            return SourceDateTime(value)
        if declared_type == BOOLEAN and value in ('TRUE', 'FALSE'):
            return SourceBoolean(value == 'TRUE')
    except FieldBindingError:
        return SourceText(value)
    if declared_type == BOOLEAN:
        return SourceText(value)
    raise _CurrentRecordCaptureError('현재 필드의 데이터 값 종류를 확인할 수 없습니다.')


_RECORD_BLOCKER_PHRASES = {
    RECORD_REQUIRED_VALUE_MISSING: "필수 값이 없습니다.",
    RECORD_EXPLICIT_NULL_NOT_ALLOWED: "값이 명시적으로 비어 있어 사용할 수 없습니다.",
    RECORD_VALUE_TYPE_INVALID: "값의 종류가 이 항목에서 요구하는 형식과 다릅니다.",
    RECORD_VALUE_FORMAT_INVALID: "값 형식이 올바르지 않습니다.",
    RECORD_BLANK_POLICY_VIOLATION: "빈 값이나 공백만 있는 값은 사용할 수 없습니다.",
    RECORD_DOCUMENT_VALUE_RESOLUTION_FAILED: "이 값을 문서 내용으로 해석할 수 없습니다.",
}

_DELIVERY_BLOCKER_PHRASES = {
    "OUTPUT_NAME_TOKEN_UNRESOLVED": "파일 이름에 사용할 값을 확인할 수 없습니다.",
    "OUTPUT_NAME_BINDING_AMBIGUOUS": "파일 이름에 사용할 항목 연결을 하나로 확인할 수 없습니다.",
    "OUTPUT_NAME_VALUE_RESOLUTION_FAILED": "파일 이름에 사용할 값을 해석할 수 없습니다.",
    "OUTPUT_NAME_PATTERN_INVALID": "파일 이름 규칙이 올바르지 않습니다.",
    "OUTPUT_NAME_CONFLICT_REVIEW_REQUIRED": "같은 이름의 파일이 있습니다:",
    "OUTPUT_PATH_NON_REGULAR_CONFLICT": "같은 이름의 폴더나 바로가기 등이 있어 덮어쓸 수 없습니다:",
}


# (결과 3태 판정은 :func:`hwpxfiller.application.generation.run_status` 가 소유한다 —
#  P2-23. 여기는 그 태 facts 를 받아 문안만 조립한다.)
def _run_title(status: str, cancelled: bool, succeeded: int, failed: int) -> str:
    """3태 제목 — 취소는 태를 바꾸지 않고 제목이 그 사실을 **먼저** 말한다.

    문안이 Python 에 있는 이유는 요약(``summary``)과 같다: 같은 수치를 두 층이 따로
    조립하면 제목과 요약이 갈라진다(공유 합성기 규율).
    """
    if cancelled:
        return f"생성을 중단했습니다 · {succeeded}개 완료"
    if status == "completed":
        return f"문서 생성 완료 · {succeeded}개"
    if status == "partiallyCompleted":
        return f"{succeeded}개 성공 · {failed}개 실패"
    return "문서 생성 실패"


def _run_exit_summary(
    status: str, cancelled: bool, succeeded: int, failed: int,
    unstarted: int, attempted: int, total: int,
) -> str:
    """**퇴장 요약** — 결과가 세션에서 물러날 때 실행 기록에 남는 한 줄의 수치 몸통(§2.18).

    제목(:func:`_run_title`)과 **다른 함수인 이유**(#363 리뷰 P2): 요구가 반대다.
    제목은 구획 **머리**라 일부러 짧다 — 나머지 수치는 같은 구획의 요약·실패 행·증거가
    바로 옆에서 말하므로 취소 갈래가 ``failed`` 를 접고 ``failed`` 태가 수치를 통째로
    생략해도 화면에서는 아무것도 잃지 않는다. 퇴장 줄은 그 구획이 **초기화된 뒤 남는
    유일한 흔적**이라 정반대로 **하나도 흘리면 안 된다**. 제목을 손실 없게 바꾸면
    머리가 길어지고 같은 수치를 구획이 두 번 말한다 — 그래서 표면을 늘리지 않고
    **같은 층(Python)에 목적이 다른 합성기**를 하나 더 둔다. 금지된 것은 층을 넘는
    재조립(웹이 수치를 다시 세는 것)이지 같은 층의 두 문장이 아니다(``summary`` 가
    제목과 나란히 사는 것과 같은 형태).

    **0 인 성분은 지어내지 않는다**: 실패·미착수는 있을 때만 붙는다. 취소의 완료 수는
    0 이라도 남긴다 — 「어디까지 됐나」가 그 보고의 머리이고, 0 은 지어낸 성분이 아니라
    그 질문의 답이다.

    ``attempted == 0`` 인 실패(배치 진입 전)는 **성공/실패로 가르지 않는다**: 그 페이로드는
    같은 레코드를 ``failed`` 와 ``unstarted`` 에 동시에 세므로(둘 다 대상 전량) 그대로
    이어 붙이면 같은 건을 두 번 말한다. 시도가 없었다는 사실과 대상 수가 그 태의 진실이다.
    """
    if cancelled:
        parts = [f"중단 · {succeeded}개 성공"]
        if failed:
            parts.append(f"{failed}개 실패")
        if unstarted:
            parts.append(f"미착수 {unstarted}건")
        return " · ".join(parts)
    if status == "failed" and attempted == 0:
        return f"생성 시작 전 실패 · 대상 {total}건"
    parts = [f"{succeeded}개 성공"]
    if failed:
        parts.append(f"{failed}개 실패")
    return " · ".join(parts)


class JobController(DataZoneMixin, PoolTargetingMixin):
    """「작업」 화면 — 좌 작업 목록 선택 + 우 세션 패널(링1 RunViewModel/SelectionModel 위임).

    실행 화면(``screen_run.py``) 사망(슬라이스 3) 이후 **링1 실행 결정을 소비하는 유일 세션
    표면**이다. 슬라이스 1 시절 존재하던 RunController 와의 링2 배선 중복(``load_data_path``·
    ``dispatch``·``_do_*``·``_auto_aim_default``·``snapshot`` 골자)은 실행 화면 제거로 **자연 소멸**했다
    (#94 종결 — 공유 베이스 추출 대신 중복 유발 표면을 제거하는 결정의 귀결). 남은 소비 표면이
    하나뿐이라 링2 재구현을 막을 별도 가드는 불요 — 링1 결정(사전검증·게이트 단일 산출·생성 계획·
    ack 상태기계)은 여전히 :class:`~hwpxfiller.gui.run_state.RunViewModel`/:class:`~hwpxfiller.gui.
    selection_state.SelectionModel` 이 소유하고, ``test_job_panel_imports_ring1_and_does_not_
    reimplement``(#87)가 이 컨트롤러의 링1 메서드 재구현을 계속 막는다."""

    name = "job"

    def __init__(
        self,
        registry: JobStorePort,
        push: PushSink,
        *,
        clock: Callable[[], datetime],
        engine: HwpxEngine,
        pool_registry,
        generation_lock: "threading.Lock",
        text_registry=None,
        file_source_factory: FileSourceFactoryPort,
        pool_source_factory: PoolSourceFactoryPort,
        existing_outputs: Callable[[str, list[str]], list[str]],
        ensure_output_dir: Callable[[str], None],
        template_change=None,
        slot_configuration=None,
        workbench_observation=None,
        seal_execution=None,
    ) -> None:
        self.registry = registry
        self._push_sink = push
        self._clock = clock
        self._engine = engine
        # 템플릿 변경 확인·적용 코디네이터(S3-09 #659) — 조립은 webapp.app 이 한다.
        # opaque token·bootstrap·S3 스토어 소유는 전부 저쪽이고 이 컨트롤러는 세션의
        # 현재 작업 이름을 붙여 관통만 한다(판정을 링2 에서 재조립하지 않는다).
        # 미주입(None)이면 존은 unsupported·동사는 loud 거절 — text_registry 선례(위)와
        # 같은 이유로 무관 테스트·CLI 소비자에 S3 스토어 조립을 물리지 않는다.
        self._template_change = template_change
        # S4 Working Slot Configuration Product(SX-02 #679·#725) — durable slot command·HMAC token·
        # fresh view 소유는 저쪽이고 이 컨트롤러는 세션의 현재 작업 이름을 붙여 관통만 한다. 미주입
        # (None)이면 존은 unsupported·동사는 loud 거절(template_change 선례) — 무관 테스트·CLI 소비자에
        # S4 스토어 조립을 물리지 않는다. 판정·문안·token 을 링2 에서 재조립하지 않는다(재판정 금지).
        self._slot_configuration = slot_configuration
        # 작업대 Observation 합성 Product(SX-01 #724 소비 어댑터) — S3/S4/S5 권위를 사용자 작업대 상태로
        # 합성한다. SX-02 는 content/data/active/orchestration 축만 채우고 나머지는 seam 이라, 이
        # Observation 은 아직 사용자 실행 표면이 아니다(snapshot 에 노출하지 않는다 — SX-03/04/05 소관).
        self._workbench_observation = workbench_observation
        # SealExecutionPlan production 서비스(SX-SEAL #719 결선) — 조립·store 소유는 webapp.app 이
        # 진다. 이 컨트롤러는 참조만 보관하고, dispatch·automatic 트리거·snapshot 노출 배선은 SX-03
        # 소관이라 여기서 하지 않는다(미주입이면 seal 표면 부재).
        self._seal_execution = seal_execution
        # session-scoped automatic seal orchestration 상태(SX-01 #724 §4). durable current state 가
        # 아니라 세션 진행 값이다. SX-SEAL 이 seal 인프라를 배선했으므로(#719) SX-03 이 자동 확인
        # 트리거를 아래 `_maybe_auto_check` 로 배선한다(수동 seal 버튼 0).
        self._session_orchestration = AutomaticSealOrchestration()
        self._current_record_preparation: _CurrentRecordPreparation | None = None
        self._run_delivery_intent: RunDeliveryIntent | None = None
        self._current_delivery_preparation: _CurrentDeliveryPreparation | None = None
        self._current_preview_preparation: _CurrentPreviewPreparation | None = None
        self._approved_preview_token: str | None = None
        # 마지막으로 봉인된 current basis 의 digest(**세션 소유·durable 아님**). R2(#740): opaque Plan
        # ref·resolve_plan_reference 가 사라져 seal 은 durable side effect 없는 순수 재계산이다 —
        # observe 성공마다 이 digest 를 갱신하고, durable mutation 이 changed 면 매번 재확인한다
        # (UI 가 basis 를 계산하지 않는다).
        self._last_sealed_basis_digest: "str | None" = None
        # 마지막 seal/observe 의 fresh observation(CurrentSealedPlanObservation/CurrentWorkExecutionObservation/
        # ExecutionObservationContextError). 작업대 Observation 의 admission/readiness/7상태를
        # 여기서 **소비만** 한다(재판정 0). None = 아직 확인 증거 없음(NO_EVIDENCE).
        self._last_fresh_observation: "FreshExecutionObservation | None" = None
        # 마지막 seal 이 봉인한 plan payload(S6-05 · #812) — identity 가 아니라 화물이다.
        # basis digest 와 **같은 응답**에서 짝으로 보관해 managed 실행이 재판정 없이 소비한다.
        self._last_sealed_plan_payload = None
        # 마지막 managed 완주의 실행 증거(S6-05) — 작업대 historical_outcome 으로만 나른다.
        self._last_managed_outcome: "HistoricalOutcomeSummary | None" = None
        # 직전 managed 실행이 **실제로 disk 에 앉힌** 문서들(S7-03 · #825). 결과 존의 문서
        # 목록과 산출물 관찰·「다른 이름으로 저장」이 겨누는 좌표이고, 범위는 **현재 세션
        # 결과**뿐이다(#820 D5 — 원장 되읽기는 이 슬라이스 밖). bytes 는 들지 않는다:
        # 관찰이 필요할 때마다 커널을 다시 부른다(#820 D1 — 캐시는 관찰 권위가 못 된다).
        # 수명은 `_last_generated` 와 같은 자리다 — 데이터 교체·작업 전환에서 비운다.
        self._last_delivered: "tuple[DeliveredDocument, ...]" = ()
        # 산출물 관찰 시트의 **열림과 결과**(S7-03) — JobPreviewSheet 선례대로 열림·값이
        # 전부 Python 소유다. DOM 이 들면 push 재렌더가 면을 조용히 닫거나 남의 문서를 그린다.
        self._artifact_view: "dict | None" = None
        # 데이터 소스 factory 포트(P2-16) — **필수 주입**. 구체 선택(엑셀/CSV·풀 복원)은
        # 유일한 제품 조립점 `webapp.app` 이 하고, 이 컨트롤러는 링1 리졸버로 관통만 한다
        # (기본값·service locator 를 두면 링2 가 구체를 조용히 재선택하는 뒷문이 된다).
        self._file_source_factory = file_source_factory
        self._pool_source_factory = pool_source_factory
        self._existing_outputs = existing_outputs
        self._ensure_output_dir = ensure_output_dir
        # TXT 템플릿 레지스트리(F6 PR-B 고지 ①) — 후보 TXT 구획 빈 상태의 술어에만 쓴다
        # (txt 템플릿 有 ∧ txt 작업 0건). 앱 조립에선 tpl·편집기와 같은 인스턴스를 주입한다.
        # 미주입(None)이면 술어가 항상 거짓 — 테스트·CLI 소비자에 실 홈 스캔을 물리지 않는다.
        self.text_registry = text_registry
        self.vm: "RunViewModel | None" = None
        # 명시 선택 시점에 seated VM이 가리키던 기존 durable identity의
        # 세션 래치. 새 identity를 만들거나 영속하지 않는다.
        self._seated_template_application_id: "str | None" = None
        # 세션 소유 데이터(data-first 봉합, §18.2 보존 계약) — 마운트된 datasource·records 는
        # 컨트롤러(세션)가 보유해 **작업 전환에서 생존**한다. vm 은 재생성 시
        # ``set_acquired`` 로 이 상태를 주입받는 소비자다(RC-22 원자 진입점 재사용).
        self.datasource = None
        self.records: "list[dict]" = []
        self.selection = SelectionModel(0)
        # 전문 범위 편집기 초안(§18.10, 재작성 F3) — 열려 있으면 존 13액션이 **이것**을
        # 편집하고 커밋된 범위는 그대로 선다(불변식 §18.11-21). 스냅샷 세대는 초안이 어느
        # 레코드 집합 위에서 열렸는지의 표식이다(적용 시점 정합 판정).
        self.range_draft: "RecordRangeDraft | None" = None
        self._snapshot_gen = 0
        # 존 변이의 **대상 세계 세대**(리뷰 4R) — 초안이 열리거나 닫히거나(적용·취소) 데이터가
        # 갈릴 때 오른다. 웹은 발신 시점에 보고 있던 세대를 실어 보내고, 세대가 다른 변이는
        # **남의 세계의 편집**이라 적용하지 않는다: 느린 출구 뒤에 줄 선 편집이 초안이 사라진
        # 커밋 범위에 착지하던 창을 원천에서 닫는다(경계의 시간 축, 지도 §10.11.9).
        self.zone_epoch = 0
        # 전체 표시순서(§18.10 ``recordRange.viewOrder``, 재작성 F3 — 지도 §10.11).
        # **데이터 귀속** 상태다: 새 스냅샷은 기본값으로 돌아간다(불변식 §18.11-13 "새
        # 스냅샷은 최신 행 먼저"). 개인화 설정으로 승격하지 않는다 — 순서가 파일명의
        # 함수라(§2 충돌 B) 지난 데이터의 순서를 새 데이터가 물고 오면 이름이 조용히 갈린다.
        self.view_order = VIEW_ORDER_DESC
        # 필터 선언 상태(블록 4, 결정 23~25) — 스코프 = 세션(작업×데이터, 결정 24).
        # 데이터 겨눔 시 생성, 작업 전환·데이터 교체 시 재생성(전환 인계는 PR-4 결정 28).
        self.filter: "FilterModel | None" = None
        # 마지막 생성 완주 집합(결정 27) — 완료 이벤트 = 무장 해제(내역은 완료 존이 담보).
        self._last_generated: "set[int] | None" = None
        # 직전 런의 실패 레코드 원본 index(지도 §10.10 판정 F) — 「실패한 N건만 선택」의
        # 소재. **Python 이 소유**한다: 웹이 들고 있다 되돌려주면 그 사이의 데이터 교체·
        # 표시순서 변경이 남의 행을 고른다. 수명 = 이 데이터·이 작업(둘 중 하나가 바뀌면 비운다).
        self._last_failed: "list[int]" = []
        # 직전 런의 **주체**(3R P2 근본 조치) — 결과는 그 실행의 것이고 세션은 그 뒤로도
        # 움직인다. 그 정체를 결과 payload(한 번 찍고 안 변하는 값)에 넣으면 **정체의
        # 변화**(이름 변경)를 따라가지 못해 같은 작업이 남처럼 보인다. 그래서 주체 추적은
        # 세션 상태의 일이고, 표면은 이 값과 `job_name` — **둘 다 Python 이 낸 값** — 만
        # 비교한다. 작업 전환에도 남는다: 남아 있어야 "지금 열린 작업이 그 런의 작업과
        # 다르다"를 말할 수 있다.
        self._last_run_job = ""
        # 직전 런이 **고정한** 판본(재작성 F7 판정 I·§13-7). 런 시작 시점에 찍고 그 뒤
        # 디스크를 다시 읽지 않는다 — 결과가 대는 근거는 그 런이 실제로 쓴 규칙의 세대다.
        self._run_revisions: "dict[str, int]" = {}
        # 검토 승인 사건(재작성 F5, 지도 §10.12 판정 B) — **세션 소유·미영속**. 기준선은
        # `Job.reviewed_rules` 가 durable 로 들고, 승인만 여기 산다: 승인하고 실행하지 않은
        # 채 재시작하면 요구가 되돌아온다(열린 게이트로 시작하지 않는다). 폐기 코드는 없다
        # — 승인이 규칙 지문(+선택 결속 위험이면 선택 지문)에 결속돼 자동으로 무효가 된다.
        self.review = ReviewState()
        # 미리보기 드로어(F5) — **열림 여부와 자리가 Python 소유**다(§10.12.1 정체 면,
        # F3 초안이 세운 선례). DOM 클래스로 들면 push 재렌더가 면을 조용히 닫거나
        # 자리를 되돌린다. 자리는 **표시순 서수**이지 원본 index 가 아니다(판정 M).
        self.preview_open = False
        self.preview_pos = 0
        # 「빈 값 있는 건만 보기」(U2 §2.13) — ‹ › 이동을 빈 값 있는 건으로 한정하는 면의
        # 보기 상태. 열림·자리와 같은 이유로 Python 소유이고, 면이 닫히면 함께 놓는다.
        # 훑기 가속의 실제 기제는 표지가 아니라 이 한정이다(선례: 「실패한 건만 선택」).
        self.preview_blank_only = False
        # 미리보기가 **본 이름**의 시각을 붙들어 두는 핀(5R P2) — 값은 그때의 실행 입력
        # 정체다. 그 정체가 그대로인 동안만 유효하고, 생성이 소비하면 놓는다.
        self._names_pin: "str | None" = None
        # 직전 필터 슬롯(결정 28) — 정의 가진 세션이 죽을 때 덮어쓰는 1칸 세션 메모리
        # (앱 수명·미저장 — 필터 영속 뒷문 금지). 소스 일치 게이트용 키와 쌍.
        self._last_filter: "dict | None" = None  # {"source_key": str, "state": dict}
        self._data_key = ""  # 현 데이터 소스 정체(file:경로 | pool:참조) — 소스 일치 판정
        self.job_name = ""  # 후보·탐색에서 겨눈 작업(패널 세션의 주체)
        # **선택된 작업이 TXT 인가**(재작성 F6) — `vm` 은 hwpx 실행뷰라 TXT 에선 None 이다.
        # 두 축을 가르는 이유(지도 §10.15 판정 A 의 표면판): F6 이전에는 `vm is None` 이
        # 곧 「작업 미선택」이었는데, TXT 가 합류하면서 그 술어에 뜻이 둘 생겼다. 그래서
        # **선택 여부는 `job_name`, hwpx 실행뷰 존재는 `vm`, 매체는 이 플래그**다.
        #
        # **Job 사본을 들지 않는다**(1R P2 근본 조치). 첫 판은 여기에 `txt_job: Job` 을 들었고,
        # 그 순간 durable 사실의 **제2 정본**이 생겨 이름 변경·재연결·재적재가 전부 조용한
        # 구멍이 됐다(그 경로들은 `vm.job` 만 유지한다). 이 저장소가 이미 적어 둔 규율과
        # 같다: "메모리 사본을 들지 않고 영속 키를 그때그때 읽고 쓴다"(`recollapse_job_group`).
        # 매체는 `template_path` 확장자 파생이라 이름이 바뀌어도 불변이고(§13-17), 실제
        # Job 은 **쓰는 순간** 스냅샷이 이미 읽는 목록·레지스트리에서 집는다.
        self.job_is_txt = False
        # 선택된 작업의 템플릿이 hwpx 도 txt 도 아님 — 실행 표면이 **없다**. TXT 와 나란히
        # 두는 이유는 같다: `vm is None` 하나로는 세 상태를 말할 수 없다(링1 `seat_kinds`).
        self.job_unsupported = False
        # 작업대 세션 개시 handoff(사후 주입 — 라이브러리 `session_guards` 선례). 진입
        # 판정은 이 컨트롤러가 내고 세션 개시만 위임한다. **컨트롤러 객체가 아니라
        # callable** 이다(P2-24): 화면 간 결합은 조립부(webapp.app)가 결선하는 이 한
        # 이음새뿐이고, 이 화면은 상대 화면의 형체(클래스·메서드 표면)를 모른다.
        self.workbench_open: "Callable[[Job, list], None] | None" = None
        # 문서 탐색 상태(§18.6) — 탭·검색어는 **세션 소유**다: 탭을 옮겨도 검색어가 살아야
        # 하고(계약 명문), 시트를 닫고 다시 열어도 방금 찾던 자리로 돌아온다. 스크롤·포커스는
        # 프런트 소유(React reconciliation + 화면 전환 executor 의 보존)라 여기 두지 않는다.
        self.browse_tab = TAB_AVAILABLE
        self.browse_query = ""
        # preferredWorkId(§18.3 개정 1행) — 라이브러리 「문서 만들기에서 사용」이 낸 **명시
        # 사건**을 데이터가 준비되는 시점까지 들고 있는 자리. 슬2가 규칙만 박제하고 비워
        # 뒀던 seam 이며, 그 사건의 유일한 원천이 F2 에서 섰다. 승격·소비 규칙은
        # :meth:`_apply_preferred_work`.
        self.preferred_work = ""
        self.data_label = ""
        self.data_source = ""  # 소스 종류 플래그('file'|'pool') — 병기 라벨은 스냅샷이 합성(K8)
        self.data_pool_key = ""  # 겨눈 풀 슬롯 키(§5.3 — 라벨은 개명 자유라 정체가 못 된다)
        self.out_dir = ""
        # 레코드 미리보기의 날짜 토큰 기준 시각(F33) — 스냅샷마다 갱신되고 generate 가 재사용
        # (미리보기=실파일명, RC-02 확장). None=미리보기 전(헤드리스 직행).
        self._names_now: "datetime | None" = None
        # 데이터 겨눔 결과 재진술(preferred_work 판정 등) — 성공(ok)/실패(warn)를 스냅샷에 노출.
        self.data_notice_text = ""
        self.data_notice_level = ""
        # 진행 중인 run 의 **핸들**(P2-23) — 정본(주체·판본·규칙 지문·cancel Event·상관
        # 토큰)은 Application :class:`~hwpxfiller.application.generation.GenerationRun`
        # 이 소유하고, 컨트롤러는 취소 요청·진행 델타 이름표 조회(transport)만 한다.
        # 토큰(R4-03)은 표면이 낸 불투명 문자열이라 여기서 파생·검증·정규화하지 않는다.
        self._run: "GenerationRun | None" = None
        # 진행 중인 런은 **한 앱에 하나뿐인 사실**이라 자물쇠는 **필수 주입**이다(9R P1 →
        # P2-24 폴백 제거) — 규칙을 쓰는 표면이 이 화면 밖에도 있으므로(편집기 진입·
        # 라이브러리 재연결) 그쪽이 같은 자물쇠를 봐야 하고, 화면이 자기 것을 세우면
        # run transaction 상태의 제2 정본이 된다(#570 pool_registry 폴백 제거와 같은 규율).
        self._generation_lock = generation_lock
        # 등록 데이터(풀) 겨눔(#26/#6) — composition root(webapp.app)가 주입한다.
        # 자기 생성 폴백은 #570 에서 제거됐다(주석 304-305 의 금지 선언과 자기모순이던
        # locator 뒷문 — 기본값이 있으면 링2 가 구체 저장을 조용히 재선택한다).
        self.pool_registry = pool_registry

    # --------------------------------------------- 진행 중인 런과의 경합 거절(9R P1)
    def raise_if_generating(self, then_do: str) -> None:
        """진행 중인 런과 겹치면 안 되는 전이의 **단일 거절**.

        이 거절이 필요한 자리의 공통 형상: 진행 중 배치가 **고정한 입력**(vm·데이터·범위)을
        그 배치가 끝나기 전에 갈아치우는 전이다. 그러면 결과가 어느 입력으로 만들어진 것인지
        갈리고, 최악은 결과가 **디스크에 없는 세대**를 자기 근거로 대는 것이다(§13-7).

        **왜 한 정의로 모으는가**(9R P1): 같은 판정이 표면마다 인라인 사본으로 흩어져 있었고,
        그래서 이 화면 밖에 있는 규칙 쓰기 경로(편집기 진입·라이브러리 재연결)가 조용히
        빠져 있었다 — 열거가 흩어지면 한 자리가 빠진다는 F7 의 반복 기제와 같은 형태다
        (지도 §10.13.14). 새 규칙 쓰기 표면은 이 메서드를 부르면 된다.

        ``then_do`` = 「끝난 뒤에 ___」에 들어갈 사람 어휘(무엇을 못 했는지 재진술).
        """
        if self._generation_lock.locked():
            raise ValueError(f"문서 생성이 진행 중입니다. 끝난 뒤에 {then_do}.")

    def raise_if_generating_before_swap(self, then_do: str) -> None:
        """위와 같은 거절의 **교체 계열 문안** — 중단이라는 출구를 함께 재진술한다.

        데이터·작업 교체는 진행 중 배치를 기다릴 것 없이 **중단**해도 되는 전이라, 거절이
        기다림만 말하면 사람이 쥔 출구 하나를 숨기는 셈이 된다(과소 안내).
        """
        if self._generation_lock.locked():
            raise ValueError(f"문서 생성이 진행 중입니다. 중단하거나 완료된 뒤 {then_do}.")

    # ------------------------------------------------------------- 관측 푸시
    def _push(self) -> None:
        self._push_sink(self.name, self.snapshot())

    # ------------------------------------------------------------- 스냅샷
    # -------------------------------------------- 범위 상태 접근(커밋 vs 초안, 판정 A·D)
    def _committed_range(self) -> RecordRange:
        """세션의 커밋된 범위 — 실행 입력·게이트·거울·세션 가드가 보는 유일한 값."""
        return RecordRange(self.selection, self.filter, self.view_order)

    def _zone_range(self) -> RecordRange:
        """존(표·필터·스트립·재진술)이 편집·표시하는 범위 — 초안이 열려 있으면 초안."""
        return self.range_draft.range if self.range_draft else self._committed_range()

    def _zone_sel(self) -> SelectionModel:
        return self._zone_range().selection

    def _zone_flt(self) -> "FilterModel | None":
        return self._zone_range().filter

    def _zone_set_flt(self, model: FilterModel) -> None:
        if self.range_draft is not None:
            self.range_draft.range.filter = model
        else:
            self.filter = model

    def _zone_visible(self, view) -> "list[int]":
        """「선택된 항목만 보기」(초안 전용 보기) — 검색·열 필터를 **일시적으로 적용하지 않고**
        초안 선택 집합만 그린다. 필터 정의는 살아 있고(칩 줄 유지) 판정은 필터 가시 집합을
        계속 쓴다 — 보기 상태가 판정을 물들이면 "선택만 보는 중"이 "정의-유래 선택"으로
        오독된다(재진술 유래가 뒤집힌다)."""
        if self.range_draft is not None and self.range_draft.selected_only:
            return self.range_draft.range.selection.selected_indices()
        return view.visible_indices()

    def _zone_hidden(self) -> "set[str]":
        """사용자 열 선별의 적용 범위(U2 §2.19, #341) — **인라인 표 한정**.

        ⤢ 시트(범위 초안)는 전 열·원본 순서다(#271 "시트 = 전체 진실" 유지): 초안이 열려
        있으면 숨김을 적용하지 않는다. 세션 숨김 집합 자체는 살아 있어 시트를 닫으면
        인라인이 다시 선별을 따른다 — 적용 여부의 판정이 Python 한 곳이라 인라인·시트·칩이
        각자 답을 갖지 않는다.
        """
        return set() if self.range_draft is not None else set(self.hidden_columns)

    def _hide_allowed(self) -> bool:
        """「이 열 숨기기」 제공 여부 — 시트로 이사한 패널에는 항목이 서지 않는다(#341)."""
        return self.range_draft is None

    @staticmethod
    def _ordered(view_order: str, indices: "list[int]") -> "list[int]":
        """표시 순서 투영의 몸통 — 축 값 하나에 대한 순수 함수(커밋·초안이 같이 쓴다)."""
        return sorted(indices, reverse=view_order == VIEW_ORDER_DESC)

    def _display_indices(self, indices: "list[int]") -> "list[int]":
        """**존 표시** 순서(§18.10, 충돌 B 확정 2026-07-26) — 초안이 열려 있으면 초안의 축.

        기본 `sourceDesc` 는 최신 행(마지막 원본 행)이 먼저다. 표 렌더·필터 밖 선택 스트립·
        파일 이름 미리보기가 **이 한 훅을 공유**한다(보이는 것 = 만들어지는 것) — 축을
        사용자에게 연 뒤에도 소비처를 늘리지 않는 것이 WYSIWYG 의 담보다(지도 §10.11.1
        도달성 면). 실행 입력만은 이 훅을 타지 않는다: :meth:`_indices` 는 **커밋된** 축으로
        직접 투영한다(초안이 실행 순서를 미리 바꾸면 불변식 §18.11-21 이 깨진다).
        """
        return self._ordered(self._zone_range().view_order, indices)

    def _reset_range_for_snapshot(self, count: int) -> None:
        """새 스냅샷(데이터 마운트·교체) = 범위 상태 초기화 — 선택 0건 + 기본 표시순서.

        불변식 §18.11-12(commit 뒤 최초 선택 0건)·13(새 스냅샷은 최신 행 먼저)의 단일 이행
        지점이다. 두 마운트 경로(파일·풀)가 같은 seam 을 타야 한 쪽만 고쳐지는 드리프트가
        안 생긴다. **작업 선택은 이 seam 을 타지 않는다** — 불변식 §18.11-23(문서 작업 선택은
        `RecordRangeState` 를 바꾸지 않는다). 필터 재생성(`_init_filter`)은 작업 선택도
        조건부로 타므로 그쪽에 얹지 않는다.
        """
        self.selection = SelectionModel(count, all_selected=False)
        self.view_order = VIEW_ORDER_DESC
        # 사용자 열 선별도 데이터 교체에 소멸한다(U2 §2.19, #341 — 필터와 같은 계층: 열
        # 지형이 바뀐다). 작업 선택의 조건부 필터 재생성(`_init_filter` 유형 재조정)은 이
        # seam 을 타지 않으므로 선별이 생존한다 — 숨김은 데이터의 축이지 작업의 축이 아니다.
        self.hidden_columns = set()
        # 세대를 올리고 초안을 버린다(판정 J): 초안의 index 는 죽은 스냅샷의 좌표다. 세대는
        # 초안이 살아남는 경로가 생기더라도 적용 시점에 그 사실이 **드러나게** 하는 표식이다.
        self._snapshot_gen += 1
        self._invalidate_current_preparations()
        self.range_draft = None
        self.zone_epoch += 1

    def _do_set_view_order(self, p: dict) -> None:
        """표시순서 전환 — 미지 값은 시끄럽게 거절한다(조용한 기본값 강등 금지).

        선택 집합은 **건드리지 않는다**: 순서는 투영이고 선택은 집합이라 축이 바뀌어도
        같은 행이 남는다(§18.10 "검색과 필터는 가시성만"의 정렬판). 바뀌는 것은 생성
        **순서**와 그 함수인 파일명 순번이며, 그 사실은 표면 문안(`order_note`)이 진다.
        """
        value = str(p.get("value", ""))
        if value not in VIEW_ORDERS:
            raise ValueError(f"알 수 없는 표시순서: {value!r}")
        if self.range_draft is not None:  # 축도 초안이 덮는다(판정 B) — 적용해야 실행에 든다
            self.range_draft.range.view_order = value
        else:
            self.view_order = value

    # --------------------------------- 전문 범위 편집기 초안(§18.10, 지도 §10.11 판정 A·F)
    def _draft_or_raise(self) -> RecordRangeDraft:
        if self.range_draft is None:  # 표면 오배선 — 초안 없는 초안 액션은 프로그램 결함
            raise ValueError("범위 편집기가 열려 있지 않습니다.")
        return self.range_draft

    # ---- 미리보기 드로어(F5, 지도 §10.12) ------------------------------------
    def _do_preview_open(self, p: dict) -> dict:
        """드로어 열기. §13-2 대로 **요구가 없어도 열린다**(정상 반복 실행에서 선택).

        거절 넷: ⓐ생성 중(진행 중 런의 입력을 보며 승인하면 어느 범위의 승인인지 갈린다)
        ⓑ범위 초안 열림(판정 H — 미리보기는 **커밋된** 실행 입력의 상이다. 초안 세계를
        그리면 적용도 안 한 편집을 승인하게 되고 그건 불변식 21 위반이다) ⓒ선택 0건
        (§18.11-6: 선택 0건에서는 미리보기에 진입하지 않고 첫 레코드로 대신하지 않는다)
        ⓓ**TXT 작업**(재작성 F6 판정 J — 배제 선언).

        ⓓ의 문안이 ⓒ와 갈리는 이유: TXT 는 작업이 **선택된 채로** `vm` 이 없다. 그 상태에서
        "먼저 문서 작업을 선택하세요"라고 말하면 방금 고른 작업을 못 본 척하는 거짓 지시가
        된다 — 같은 술어(`vm is None`)에 뜻이 둘이라는 사실을 문안까지 끌고 온 자리다.
        """
        self.raise_if_generating("미리보기를 여세요")
        if self.range_draft is not None:
            raise ValueError("범위 편집을 적용하거나 취소한 뒤에 미리보기를 여세요.")
        if self.vm is not None and self.vm.job.authority_id:
            self.workbench_observation()
            if self._current_preview_preparation is None:
                raise ValueError(
                    "현재 생성 내용을 확인할 수 없습니다. 먼저 데이터와 저장 위치를 확인하세요."
                )
            self.preview_open = True
            self.preview_pos = 0
            return {"ok": True}
        if self.job_is_txt:
            raise ValueError(
                "이 작업은 검토·복사 작업대에서 행마다 값을 확인합니다."
            )
        if self.vm is None:
            raise ValueError("먼저 문서 작업을 선택하세요.")
        if not self._indices():
            raise ValueError("미리볼 문서를 최소 1건 선택하세요.")
        self.preview_open = True
        # `at`(deep-link 복귀, §10.15.15 판정 C) — 값의 출처는 Python 이 push 한
        # `preview.pos` 의 왕복이다(EditContext 를 지나 돌아온다). 편집 중 선택이 줄었으면
        # 클램프가 안전측으로 접는다 — stale 인덱스로 남의 행을 그리지 않는다.
        self.preview_pos = max(0, min(len(self._indices()) - 1, int(p.get("at", 0) or 0)))
        # 핀(5R P2)은 여기서 조립하지 않는다 — 면이 열려 있는 동안 스냅샷이 **같은
        # 술어로** 채운다. 두 자리가 각자 조립하면 그 순간 정체가 두 벌이 된다
        # (F3 1R 이 표면의 자체 조립에서 났던 자리).
        return {"ok": True}

    def _do_preview_close(self, p: dict) -> None:
        self.preview_open = False
        self.preview_pos = 0
        self.preview_blank_only = False  # 면의 보기 상태 — 열림과 같은 수명(U2 §2.13)

    # ---- 산출물 관찰(S7-03 · #825, #820 D1·D4) --------------------------------
    def delivered_artifact(self, ordinal: int) -> "DeliveredDocument | None":
        """이 세션이 앉힌 문서 중 ``item_ordinal`` 이 맞는 것 — 없으면 ``None``.

        겨눔의 정체가 **ordinal** 인 이유는 표시 index·파일명이 그 사이 갈릴 수 있는 값이기
        때문이다(선택·표시순서·재실행). ordinal 은 그 실행이 고정한 좌표다.
        """
        return next(
            (d for d in self._last_delivered if d.item_ordinal == ordinal), None
        )

    def delivered_artifact_paths(self) -> "tuple[str, ...]":
        """이 세션이 **앱 자신이 내준** 문서의 절대경로 전수.

        소유 경로 화이트리스트(``webapp.app.WebFrontend._validate_owned``)의 세션 성분이다 —
        행 어포던스(폴더에서 보기·경로 복사)가 결과 문서를 겨눌 수 있는 유일한 근거이고,
        등록의 원천은 「이 앱이 방금 그 파일을 만들었다」는 사실 하나다(검증 완화 아님).
        """
        return tuple(d.absolute_path for d in self._last_delivered)

    def _discard_delivered_artifacts(self) -> None:
        """배달 좌표와 열린 관찰 면을 **함께** 놓는다.

        좌표만 비우고 면을 남기면 그 면은 이미 없는 실행의 문서를 계속 그리고, 면만 닫고
        좌표를 남기면 저장·관찰이 남의 데이터 좌표를 가리킨다. 둘은 한 수명이다.
        """
        self._last_delivered = ()
        self._artifact_view = None

    def _artifact_view_payload(self) -> dict:
        """관찰 시트의 스냅샷 투영 — 닫힌 상태도 **키를 갖춰** 낸다(키 부재 분기 금지)."""
        view = self._artifact_view
        if view is None:
            return {
                "open": False, "ordinal": -1, "filename": "",
                "status": "", "detail": "", "structure": None,
            }
        return dict(view)

    def _do_artifact_open(self, p: dict) -> dict:
        """배달 문서 하나를 **다시 관찰해** 시트를 연다(#820 D1).

        성립 경로는 커널 재호출 하나뿐이다 — 세션이 bytes 를 들고 있다가 내주는 길은 없다.
        서지 않는 경우(세션 좌표 밖·파일 부재·digest 불일치·재파싱 실패)는 전부 **면을 열어
        사유를 말한다**: 조용히 무시하면 사용자는 「눌렀는데 아무 일도 없다」만 보고, 그것은
        준비 안 됨과 무결성 실패를 같은 침묵으로 접는 것이다(#775 교훈).
        """
        ordinal = int(p["ordinal"])
        doc = self.delivered_artifact(ordinal)
        if doc is None:
            self._artifact_view = {
                "open": True, "ordinal": ordinal, "filename": "",
                "status": ARTIFACT_NOT_IN_SESSION,
                "detail": (
                    "이 문서는 지금 세션의 생성 결과에 없습니다. "
                    "문서를 다시 만든 뒤에 내용을 볼 수 있습니다."
                ),
                "structure": None,
            }
            return {"ok": True}
        observed = observe_delivered_artifact(
            absolute_path=doc.absolute_path, recorded_digest=doc.output_digest
        )
        if isinstance(observed, ArtifactObservationRefused):
            # 사유는 커널 실측의 재진술이다 — 여기서 다시 짓지 않는다(판정 단일 출처).
            self._artifact_view = {
                "open": True, "ordinal": ordinal, "filename": doc.relative_path,
                "status": observed.code, "detail": observed.detail, "structure": None,
            }
            return {"ok": True}
        self._artifact_view = {
            "open": True, "ordinal": ordinal, "filename": doc.relative_path,
            "status": ARTIFACT_OBSERVED, "detail": "",
            "structure": observed_artifact_snapshot(observed.package),
        }
        return {"ok": True}

    def _do_artifact_close(self, p: dict) -> None:
        self._artifact_view = None

    def _preview_blank_positions(self, mapped: "list[dict] | None" = None) -> "list[int]":
        """빈 값이 있는 건의 표시순 자리 — 판정은 링1
        (:meth:`~hwpxfiller.gui.run_state.RunViewModel.blank_record_positions`)이 소유한다
        (P2-24: 필드축 ``blank_fields`` 와 같은 층·같은 술어). 여기는 세션 상태(vm 유무·
        실행 입력)를 대는 관통이다."""
        if self.vm is None:
            return []
        return self.vm.blank_record_positions(self._indices(), mapped)

    def _do_preview_blank_only(self, p: dict) -> None:
        """「빈 값 있는 건만 보기」 토글(U2 §2.13) — ‹ › 이동을 그 건들로 한정한다.

        켤 때 빈 값 건이 없으면 시끄럽게 거절한다(무동작 토글 금지 — 표면도 0건이면
        비활성이지만 잠금은 상태가 진다). 켜는 순간 자리가 대상 밖이면 가장 가까운
        빈 값 건으로 당긴다 — 한정을 켰는데 대상 밖 건을 보고 있으면 ‹ › 가 어디서
        움직이는지 갈린다.
        """
        if not self.preview_open:
            raise ValueError("미리보기를 연 뒤에 쓸 수 있습니다.")
        value = bool(p.get("value"))
        if value:
            positions = self._preview_blank_positions()
            if not positions:
                raise ValueError("빈 값이 있는 문서가 없습니다.")
            if self.preview_pos not in positions:
                after = [q for q in positions if q >= self.preview_pos]
                self.preview_pos = after[0] if after else positions[-1]
        self.preview_blank_only = value

    def _do_preview_move(self, p: dict) -> None:
        """레코드 이동 — 자리는 **표시순 서수**다(판정 M). 웹은 인덱스를 되돌려주지 않는다.

        경계에서 멈춘다(순환하지 않는다): 마지막에서 한 번 더 눌러 첫 건으로 돌아가면
        「몇 번째를 보고 있는가」가 사용자 머릿속에서 끊긴다. 「빈 값 있는 건만 보기」가
        켜져 있으면 이동은 그 건들 사이로만 간다(§2.13 — 한정이 곧 훑기 가속의 기제).
        """
        if not self.preview_open:
            raise ValueError("미리보기가 열려 있지 않습니다.")
        total = len(self._indices())
        if not total:
            return
        delta = int(p["delta"])
        if self.preview_blank_only:
            positions = self._preview_blank_positions()
            if positions:
                if delta > 0:
                    nxt = [q for q in positions if q > self.preview_pos]
                    if nxt:
                        self.preview_pos = min(nxt[0], total - 1)
                else:
                    prv = [q for q in positions if q < self.preview_pos]
                    if prv:
                        self.preview_pos = max(prv[-1], 0)
                return
        self.preview_pos = max(0, min(total - 1, self.preview_pos + delta))

    def _do_preview_approve(self, p: dict) -> None:
        """명시 승인 — 불변식 §13-4(생성 ≠ 승인)의 유일한 사건.

        **면이 열려 있을 때만** 받는다: 승인은 증거를 본 사건이라, 증거를 띄우지 않은
        경로로 세우면 그 승인은 무엇에 근거했는지 말할 수 없다(F-06 이 지목한 바로 그
        결함을 우리 손으로 재현하는 꼴). 요구가 없으면 거절한다 — 조용히 세우지 않는다.
        """
        if self.vm is not None and self.vm.job.authority_id:
            token = p.get("preview_token")
            if not isinstance(token, str) or not token:
                raise ValueError("현재 생성 내용 확인 토큰이 필요합니다.")
            if not self.preview_open:
                raise ValueError("생성 내용을 연 뒤에 확인할 수 있습니다.")
            self.workbench_observation()
            current = self._current_preview_preparation
            if current is None:
                raise ValueError(
                    "현재 생성 내용을 더 이상 구성할 수 없습니다. 다시 확인해 주세요."
                )
            if token != current.preview_token:
                raise ValueError("생성 내용이 바뀌었습니다. 새 내용을 다시 확인해 주세요.")
            if not isinstance(current.requirement, PreviewRequired):
                raise ValueError("현재 생성 내용은 별도 승인이 필요하지 않습니다.")
            self._approved_preview_token = token
            return
        if not self.preview_open:
            raise ValueError("미리보기를 연 뒤에 확인할 수 있습니다.")
        req, unmet = self._review()
        if unmet is None:
            raise ValueError("지금 확인이 필요한 변경이 없습니다.")
        self.review.approve(req, self._review_scope_key())

    def _do_range_draft_open(self, p: dict) -> dict:
        """편집기 진입 = 범위 깊은 복제. 이미 열려 있으면 **다시 복제하지 않는다**.

        재진입이 복제를 갱신하면 왕복 지연 중 두 번 눌린 출구가 사용자의 편집을 조용히
        되돌린다(멱등). 생성 중 진입은 거절한다 — 초안 적용은 실행 입력을 바꾸는 전이라
        진행 중인 런과 겹치면 어느 범위로 만든 결과인지 갈린다.
        """
        self.raise_if_generating("범위를 편집하세요")
        if self.datasource is None or not self.records:
            raise ValueError("데이터를 먼저 선택하세요.")
        if self.range_draft is None:
            committed = self._committed_range()
            self.range_draft = RecordRangeDraft(
                range=committed.copy(),
                snapshot_gen=self._snapshot_gen,
                base_fingerprint=committed.fingerprint(),
            )
            self.zone_epoch += 1     # 이 순간부터 존 변이의 대상은 초안이다
        return {"ok": True, "epoch": self.zone_epoch}

    def _do_range_draft_apply(self, p: dict) -> dict:
        """적용 = 초안을 커밋으로 원자 교체. 세대가 다르면 **거절하고 면을 닫지 않는다**.

        세대 불일치(적용 전 데이터가 갈림)에서 조용히 커밋하면 죽은 스냅샷의 index 로 남의
        행을 고른다 — F4 판정 F("웹이 인덱스를 들고 있다 되돌려주면")와 같은 뿌리다.
        실행 증거의 처리는 여기서 하지 않는다: 지문이 갈리면 결과가 「직전 실행」으로
        **강등**되고(F4 판정 G) 그 판정은 스냅샷을 보는 표면이 이미 갖고 있다 — 폐기는
        「결과 닫기」 하나뿐이라는 규칙을 초안이 되돌리지 않는다.
        """
        draft = self._draft_or_raise()
        self.raise_if_generating("적용하세요")
        if draft.snapshot_gen != self._snapshot_gen:
            raise ValueError(
                "데이터가 바뀌어 편집하던 범위를 적용할 수 없습니다. "
                "지금 데이터에서 다시 고르세요."
            )
        self.selection = draft.range.selection
        self.filter = draft.range.filter
        self.view_order = draft.range.view_order
        self.range_draft = None
        self.zone_epoch += 1     # 초안 세계는 여기서 끝난다 — 뒤늦은 편집은 남의 것
        return {"ok": True}

    def _do_range_draft_cancel(self, p: dict) -> dict:
        """취소 = 초안만 버린다(불변식 §18.11-21) — 메인 범위·실행 증거는 그대로다."""
        self.range_draft = None
        self.zone_epoch += 1     # 적용과 같다: 버린 세계의 편집이 커밋에 착지하지 않게
        return {"ok": True}

    def _do_set_selected_only(self, p: dict) -> None:
        """「선택된 항목만 보기」 — 초안 안에서만 사는 **보기** 상태(판정 B, 적용 대상 아님)."""
        self._draft_or_raise().selected_only = bool(p.get("value"))

    def _indices(self) -> "list[int]":
        """실행 입력 = OrderedSelection(§2): 선택 집합을 **전체 표시순서에 투영**한다.

        생성·미리보기·거울이 전부 이 순서를 소비한다 — 순번 토큰(``{{seq}}``)과 동명
        꼬리표(``naming._dedupe``)가 화면에 보이는 위→아래 순서를 그대로 따른다(WYSIWYG).
        같은 선택이라도 표시 순서가 다르면 파일명이 달라질 수 있다 — 인지하고 수용한
        확정(봉합 지도 §2)이며, 완화는 파일명 미리보기가 같은 투영을 보여주는 것이다.

        **커밋된 범위로만** 투영한다(F3 판정 D): 초안이 열려 있어도 실행 입력은 움직이지
        않는다 — 적용 전 메인 범위 불변이 불변식 §18.11-21 이다.
        """
        return self._ordered(self.view_order, self.selection.selected_indices())

    def _zone_indices(self) -> "list[int]":
        """존이 그리는 선택 투영 — 표의 파일 이름 미리보기와 재진술이 소비한다.

        초안이 열려 있으면 **초안 기준**이다: 이름이 커밋 기준으로 남으면 편집기 안에서
        순서를 바꿔도 「문서」 열이 안 움직여, 판정 I 의 완화("표가 새 이름을 즉시
        보여준다")가 하필 그 축을 만지는 자리에서 죽는다.
        """
        zone = self._zone_range()
        return self._ordered(zone.view_order, zone.selection.selected_indices())

    def _range_draft_payload(self) -> dict:
        """범위 초안 구획 — 열림·변경 여부·초안 수치·보기 상태.

        ``dirty`` 는 **연 뒤 내가 바꿨는가**다(이탈 가드의 무장 조건, 판정 F). ``sel_count``
        는 초안 기준이라 면 footer 의 「선택 적용: N건」이 커밋 수치와 갈리지 않는다 —
        표면이 행을 세지 않는다(F4 3R 근본원인: 정합을 표면이 재판정하게 두지 않는다).
        """
        draft = self.range_draft
        if draft is None:
            return {
                "open": False, "dirty": False, "sel_count": 0,
                "selected_only": False, "view_order": self.view_order,
            }
        return {
            "open": True,
            "dirty": draft.is_dirty(),
            "sel_count": draft.range.selection.selected_count(),
            "selected_only": draft.selected_only,
            "view_order": draft.range.view_order,
        }

    def _selection_key(self) -> str:
        """**커밋된** 실행 입력의 지문 — 결과 강등 판정(F4)과 승인 결속(F5)이 함께 쓴다.

        순서까지 담는다: 표시순서가 바뀌면 파일 이름이 실제로 달라지므로 같은 선택도 다른
        실행 입력이다(§2 충돌 B). 두 소비처가 각자 조립하면 그 순간 지문이 두 벌이 된다
        (F3 리뷰 1R 이 표면의 자체 조립에서 났던 자리) — 그래서 메서드 하나가 낸다.
        """
        return ",".join(str(i) for i in self._indices())

    def _run_marker(self, indices: "list[int]") -> str:
        """이 실행 입력에 실제로 붙을 미입력 표식 — 생성·미리보기·승인의 **단일 술어**.

        조건은 「빈 값이 있으면」 하나다(U2 §2.13 재정의) — 필드축 ack 가 폐기되면서
        「확인 안 된 빈 값」이라는 중간 상태 자체가 사라졌다. 표식 삽입 동의는 승인이
        겸하고, 승인 지문에 빈 값 집합이 들어가 조용한 통과를 막는다. 이 조건이 세
        자리에서 갈리면 각각 다른 실행 입력을 그리거나 승인하게 된다(1R P2 · 4R P2).
        """
        if self.vm is None or not indices:
            return ""
        return blank_marker(self.vm.blank_fields(indices))

    def _review_scope_key(
        self, indices: "list[int] | None" = None,
        blanks: "list[str] | None" = None,
    ) -> str:
        """승인이 결속되는 범위 — **어느 스냅샷의** 어느 선택인가(2R P1).

        선택 index 만으로는 부족하다: 데이터 A 에서 의미·파일명 위험을 승인한 뒤 데이터 B 를
        올리면 선택은 0건으로 리셋되지만 세션의 승인 집합은 남고, 같은 index 를 다시 고르는
        순간 **같은 키가 재구성돼** B 의 값·이름을 한 번도 보지 않은 채 게이트가 열린다.
        `_snapshot_gen` 은 마운트마다 오르는 단조 표식이라 그 재구성을 원리적으로 막는다.

        `selection_key`(F4 결과 강등)와 **따로 두는** 이유: 그쪽은 "이 결과가 지금 실행 입력의
        것인가"를 묻는 값이고 이쪽은 "이 승인이 무엇을 보고 난 것인가"를 묻는 값이다. 한
        문자열이 두 질문을 겸하면 한쪽 요구가 다른 쪽 의미를 조용히 바꾼다(F3 3R 의
        `selected_count` 가 표 머리와 게이트 지목을 겸하던 자리와 같은 결함류).
        """
        idx = self._indices() if indices is None else indices
        sel = ",".join(str(i) for i in idx)
        # 표식 상태는 승인의 일부다(4R P2) — 그 성분이 종전엔 이진값(표식 유/무)이었는데
        # **빈 값 필드 집합의 해시**로 승격했다(U2 §2.13 조건). 이진값이면 「담당자가 빈
        # 데이터」에서 승인한 것이 「개찰장소가 빈 데이터」에서도 유효해, 한 번도 보지 않은
        # 표식이 박힌 문서가 조용히 생성된다. 집합이 갈리면 키가 갈려 승인이 자동 무효다.
        bl = (
            (self.vm.blank_fields(idx) if self.vm is not None else [])
            if blanks is None else blanks
        )
        if bl:
            blob = ",".join(sorted(bl)).encode("utf-8")
            bkey = hashlib.sha256(blob).hexdigest()[:12]
        else:
            bkey = "-"
        return f"{self._snapshot_gen}|{bkey}|{sel}"

    def _review(
        self, vm=None, indices: "list[int] | None" = None,
        blanks: "list[str] | None" = None,
    ) -> "tuple[ReviewRequirement, ReviewRequirement | None]":
        """(현재 검토 요구, 아직 승인 안 된 요구 or None) — F5 판정 B·I.

        게이트에 넘기는 것은 **미승인분**이다. 요구 자체는 표면이 문안·증거를 그리는 데
        쓰므로 승인 뒤에도 그대로 돌려준다(승인했다는 사실을 말하려면 무엇을 승인했는지가
        필요하다).

        ``vm``·``indices`` 를 받는 이유(1R P1): 생성 백스톱은 **그 런의 주체**로 물어야
        한다. 세션은 배치가 도는 사이에도 움직이므로(브리지 호출이 스레드별) 현재 상태를
        읽으면 남의 작업의 승인으로 이 런을 통과시킬 수 있다 — 완주 스탬프가 run 이
        고정한 정체로만 적히는 것과 같은 근거다. ``blanks`` 도 같은 이유로 **그 런의 주체**
        (`target`)에서 센다 — 요구 판정(blank_set)과 승인 결속(scope key)이 같은 집합을
        보게 호출측이 이미 센 값을 관통시킬 수 있다.
        """
        target = self.vm if vm is None else vm
        if target is None:
            return ReviewRequirement(), None
        idx = self._indices() if indices is None else indices
        bl = list(target.blank_fields(idx)) if blanks is None else list(blanks)
        req = review_requirement(target.job, blank_fields=tuple(bl))
        if not req.required:
            return req, None
        approved = self.review.is_approved(
            req, self._review_scope_key(idx, bl)
        )
        return req, (None if approved else req)

    def _review_payload(self, req: ReviewRequirement, unmet) -> dict:
        """검토 요구의 표면 몫 — 「미리보기」 버튼 표지와 드로어 승인 버튼이 읽는다.

        ``required`` 는 요구의 **존재**이고 ``approved`` 는 그 해소다. 둘을 한 불리언으로
        뭉개면(v6 `preview.required && !approved`) 표면이 "승인했다"를 말할 수 없다 —
        승인 뒤 남는 것이 안심의 근거다.
        """
        return {
            "required": req.required,
            "approved": req.required and unmet is None,
            "risk": req.risk_class,
            "targets": list(req.changed_targets),
            "first_run": req.first_run,
            "unknown_baseline": req.unknown_baseline,
            "structure_changed": req.structure_changed,
        }

    def _raw_record(self, indices: "list[int]", pos: int) -> "dict":
        """표시순 자리(`pos`)의 **원본 레코드** — 이전 판본 규칙을 다시 적용할 재료.

        렌더된 값(`mapped`)으로는 다른 규칙을 적용할 수 없다: 이미 지금 규칙이 통과한
        결과라 원천이 아니다. 자리→원본 index 변환은 실행 입력과 같은 리스트를 쓴다
        (같은 순서를 두 번 계산하지 않는다 — 판정 M 의 서수 규율).
        """
        if not (0 <= pos < len(indices)):
            return {}
        index = indices[pos]
        return self.records[index] if 0 <= index < len(self.records) else {}

    def _preview_payload(
        self, req: ReviewRequirement, unmet, mapped: "list[dict]", names: "list[str]",
        audit_counts: "tuple[int, int]",
        indices: "list[int]",
        blank_positions: "list[int] | None" = None,
    ) -> dict:
        """확인 면 구획 — 닫혀 있으면 뼈대만(그리지 않는 값은 오조립의 미끼, §10.8.6 규칙 ①).

        값·이름은 **파생**이다(판정 A): 값은 실행 입력과 같은 ``mapped_records``, 이름은
        표 「문서」 열이 쓰는 그 문자열 그대로다. 한 건만 따로 계산하면 ``{{seq}}`` 가 1 로
        고정되고 꼬리표가 사라져 미리보기가 실행과 다른 이름을 말한다.

        ``blank_positions`` 는 빈 값 있는 건의 표시순 자리(§2.13 「빈 값 있는 건만 보기」) —
        호출측(snapshot)이 표식 없는 매핑 출력에서 이미 센 값을 관통시킨다(이중 계산 방지).
        """
        total = len(mapped)
        bp = self._preview_blank_positions() if blank_positions is None else blank_positions
        if not self.preview_open:
            return {
                "open": False, "pos": 0, "total": total, "can_open": total > 0,
                "blank_only": False, "blank_count": len(bp),
                "can_prev": False, "can_next": False,
            }
        # 열려 있는 동안 선택이 줄면 자리가 넘칠 수 있다 — 닫지 않고 자리를 당긴다
        # (§10.12.1 실패 경로: 면 안에서 재진술하고 면을 닫지 않는다).
        pos = min(self.preview_pos, total - 1) if total else 0
        record = mapped[pos] if total else {}
        order = [m.template_field for m in self.vm.job.mapping.mappings] if self.vm else []
        converged, too_long = audit_counts
        # ‹ › 가용성도 여기서 판정한다 — 한정(blank_only)이 켜지면 경계가 「그 건들의
        # 처음·끝」으로 바뀌는데, 표면이 pos/total 로 재유도하면 두 판정이 갈린다.
        blank_only = self.preview_blank_only and bool(bp)
        can_prev = any(q < pos for q in bp) if blank_only else pos > 0
        can_next = any(q > pos for q in bp) if blank_only else pos < total - 1
        return {
            "open": True,
            "can_open": total > 0,
            "pos": pos,
            "total": total,
            "blank_only": blank_only,
            "blank_count": len(bp),
            "can_prev": can_prev,
            "can_next": can_next,
            "filename": names[pos] if 0 <= pos < len(names) else "",
            # 「적용 범위」 축은 없다(U2 §2.3). 이 축의 존재 이유였던 runOverrides 는 §10.14
            # 에서 기각·사망했고 §10.15 판정 H 가 작업대의 대응 배지를 "말할 상태가 없다"며
            # 이미 죽였다 — 값이 하나뿐인 축은 정보가 아니라 없는 선택지의 암시다.
            "rows": [
                {"name": f, "value": str(record.get(f, ""))} for f in order
            ],
            "evidence": build_evidence(
                req, mapped=mapped, names=tuple(names), converged=converged,
                too_long=too_long, pos=pos,
                # 직전 판본 규칙으로 **같은 레코드**를 다시 렌더한 값(F7 판정 H — F5 가
                # 되깎기 조건으로 박제한 before/after 의 회수).
                before=previous_values(
                    self.vm.job, req.changed_fields, self._raw_record(indices, pos)
                ) if self.vm is not None else None,
            ),
            "can_approve": unmet is not None and total > 0,
            "empty_note": "" if total else "선택한 문서가 없습니다. 표에서 만들 문서를 고르세요.",
        }

    def _order_note(self) -> str:
        """표시순서 축 옆 상시 재진술(지도 §10.11 판정 I) — 확인 왕복 대신 문안이 진다.

        앞 절은 **언제나 참**이고(표시 순서 = 생성 순서), 파일 이름 절은 규칙이 실제로
        ``{{seq}}`` 를 쓸 때만 붙는다 — 안 쓰는 작업에도 말하면 문안이 거짓이 되고 거짓
        경보는 경보를 싸구려로 만든다. 같은 이름이 겹칠 때 붙는 꼬리표도 순서의 함수지만
        문안이 지지 않는다: 표 「문서」 열이 그 행이 받을 **실이름**을 이미 보여준다
        (보이는 변화 앞의 경고는 과경고 — 완화 조항).
        """
        note = "보이는 순서대로 생성됩니다."
        if self.vm is not None and pattern_uses_seq(self.vm.job.filename_pattern):
            note += " 파일 이름의 순번도 이 순서를 따릅니다."
        return note

    def _candidate_payload(self, jobs) -> dict:
        """현재 데이터에 대한 문서 작업 후보(§18.4)+메인 순위(§18.5·§19.3) — 판정·정렬 모두
        링1 단일 출처 소비.

        데이터 미준비면 빈 구획(§18.1 — 계산 자체를 하지 않는다). ``jobs`` 는 문서 탐색과
        같은 스캔 1회 결과를 받아 목록·후보가 갈라지지 않는다. fields 는 필터 열 파생과
        같은 원천(``records[0].keys``) — 표시와 판정이 같은 열 집합을 본다.

        반환 5구획:

        - ``top`` = 상위 :data:`~hwpxfiller.gui.work_candidates.MAIN_TOP_N` available,
          순위순. 카드가 그릴 근거(계층·즐겨찾기·마지막 실행·추천 표지)를 함께 싣는다.
          이 구획은 **투영**이다 — 데이터 마운트·호환성·순위 슬라이스 셋에 걸린다. 그래서
          재연결 도달 보장을 여기 얹지 않는다(#342 리뷰 3라운드 근본 조치): 조건마다 구멍이
          하나씩 나므로 그 의무는 조건이 없는 **세션 축**(``template_missing``·``conn_label``
          → 액션바)이 진다. 카드의 「연결 상태」·경고 클릭은 *렌더된 카드에 대한* 계약이다.
        - ``more`` = 순위 밖 available 수. 0이 아니면 표면이 **정직하게 고지**한다 —
          전체 목록 표면(문서 탐색)은 슬라이스 3 소관이라 지금은 수치만 말한다.
        - ``needs``·``needs_more`` = 확인 필요(needs_action) 이름순 상위 N + 잘린 수.
          메인 순위엔 못 들어가지만(§18.5) 전용 표면(확인 필요 탭)이 생기기 전까지 막힌
          이유를 여기서 계속 말한다(삭제는 의무를 상속한다). available 과 같은 상한을
          두는 건 데이터 존이 비활성 칩으로 넘치지 않게 하기 위함이고, 잘린 만큼은
          available 과 똑같이 수치로 고지한다.
        - ``suggested`` = 추천 작업 이름(§18.3 개정, 없으면 ``""``).
        """
        empty = {
            "top": [], "sections": [], "more": 0, "needs_count": 0, "suggested": "",
            "txt_note": "",
        }
        if self.datasource is None or not self.records:
            return empty
        fields = list(self.records[0].keys())
        by_name = {j.name: j for j in jobs}
        ranked = rank_available(jobs, fields)
        suggested = suggested_work(ranked, active=self.job_name)

        top = []
        for r in ranked[:MAIN_TOP_N]:
            job = by_name[r.name]
            # 「연결 상태」 축(U2 §4 판정 C·F, #342) — 렌더된 카드는 자기 작업의 연결
            # 상태를 말한다(§18.4 는 Template 읽기를 available 판정 밖에 뒀지만, 부재
            # 판정은 파일 존재 검사 하나라 이미 싸다 — 판정 F). 술어·문안은 `_template_conn`
            # 단일 출처다: 세션 축과 문자열이 갈리면 같은 상태를 두 이름으로 부른다.
            missing, conn_label = _template_conn(job.template_path)
            top.append({
                "name": r.name,
                "tier": r.tier,
                "favorited": bool(job.favorited_at),
                # 원시 ISO — 표시 문안(자릿수·구분자)은 표면이 만든다(판정만 Python).
                # 의미는 **완주(전건 성공) 실행**이다(지도 §8.2 ②).
                "last_run_at": job.last_run_at,
                "suggested": r.name == suggested,
                # 작업 방식(§19.1) + 그 표시 문구 — 카드 부제와 구획 판단이 소비한다(§19.3).
                # 라벨을 표면이 짓지 않는 이유는 같은 축을 그리는 표면이 셋이기 때문이다
                # (후보 카드·문서 탐색·라이브러리) — 문구가 갈리면 같은 상태를 다르게 부른다.
                "mode": r.mode,
                "mode_label": work_mode_label(r.mode, short=True),
                # 최근 사용 문안도 Python 이 낸다 — **매체마다 술어가 다르다**(§19.4).
                # 표면이 한 문구로 뭉치면 하필 구별이 중요한 자리에서 이력을 거짓으로 말한다.
                "last_run_label": last_use_label(r.mode, job.last_run_at),
                # 템플릿 정체(판정 B) — 활성 카드의 확장 부제(파일명)와 ⋮(열기·폴더에서
                # 보기)가 소비한다. 경로는 추적성 로케이트(#53-B)와 같은 전체 경로.
                "template_name": Path(job.template_path).name if job.template_path else "",
                "template_path": job.template_path,
                "template_missing": missing,
                "conn_label": conn_label,
            })
        needs = sorted(
            (
                {"name": j.name, "missing": list(c.missing)}
                for j, c in candidate_rows(jobs, fields)
                if c.kind == KIND_NEEDS_ACTION
            ),
            key=lambda d: d["name"],
        )
        return {
            "top": top,
            # 작업 방식 구획(§19.3) — **판정은 여기**서 하고 표면은 머리글을 그릴지만 정한다.
            # 순서는 첫 등장 순 = 각 구획 최고 순위의 위치이고, 한 방식뿐이면 구획이 1개라
            # 표면이 평면으로 퇴화한다(카드 부제의 방식 텍스트는 그때도 남는다).
            "sections": mode_sections(top),
            "more": max(0, len(ranked) - MAIN_TOP_N),
            # 확인 필요 전체는 문서 탐색(§18.6)이 소유한다 — 후보 줄엔 **수치만** 남긴다
            # (슬라이스 3: 칩 구획 이사, 삭제는 의무를 상속한다).
            "needs_count": len(needs),
            "suggested": suggested,
            "txt_note": self._txt_onboarding_note(jobs),
        }

    def _txt_onboarding_note(self, jobs) -> str:
        """후보 TXT 구획 빈 상태 고지(F6 PR-B 고지 ① — §10.15.15 판정 A) — 대체 경로 재진술.

        술어: **txt 템플릿 有 ∧ txt 방식 작업 0건**. 휘발 「기안」만 쓰던 사용자에게 정확히
        발화하고, 순수 HWPX 사용자(템플릿 0 = 아래 스캔이 빈 목록으로 즉시 끝난다)와 이미
        TXT 작업을 가진 사용자(in-memory 선판정으로 스캔 자체가 없다)에겐 0 소음이다.
        상시 배너·1회 다이얼로그·영속 플래그를 두지 않는다 — 매 스냅샷 파생(결정 2).
        """
        if self.text_registry is None:
            return ""
        if any(work_mode(j.template_path) == WORK_MODE_TEXT for j in jobs):
            return ""
        if self.text_registry.count() == 0:
            return ""
        return (
            "저장된 TXT 작업이 아직 없습니다. '문서 작업'의 [＋ 새 작업] 템플릿 탭에서 "
            "TXT 템플릿을 골라 작업으로 저장하면 여기 후보로 서고, 검토·복사 작업대로 "
            "이어집니다."
        )

    def _browse_payload(self, jobs) -> dict:
        """문서 탐색 구획(§18.6·§19.5) — 탭·검색 판정은 링1 단일 출처 소비.

        데이터 미준비면 빈 골격이다(§18.1 — 후보를 계산하지 않으므로 탐색도 없다). 시트가
        열려 있는지는 표면 상태라 여기서 모른다: 판정은 언제나 최신이고, 열지 않았으면
        아무도 안 본다(스냅샷 분기보다 단순한 쪽).
        """
        empty = {
            "tab": self.browse_tab, "query": self.browse_query, "rows": [], "sections": [],
            "available_count": 0, "needs_count": 0, "filtered_out": 0,
        }
        if self.datasource is None or not self.records:
            return empty
        res = browse_candidates(
            jobs, list(self.records[0].keys()),
            tab=self.browse_tab, query=self.browse_query,
        )
        rows = [{**r, "mode_label": work_mode_label(r["mode"], short=True)}
                for r in res.rows]
        return {
            "tab": res.tab,
            "query": self.browse_query,
            # 행은 링1이 실은 `mode` 를 그대로 나른다 — 탭 **안**의 구획 판단용(§19.5).
            "rows": rows,
            # 탭 **안**의 방식 구획(§19.5) — 탭이 primary classification 이라 방식을 탭으로
            # 올리지 않는다. 같은 퇴화 규칙(1방식 = 평면)이 여기도 그대로 선다.
            "sections": mode_sections(rows),
            "available_count": res.available_count,
            "needs_count": res.needs_count,
            "filtered_out": res.filtered_out,
        }

    def _filename_source_columns(self) -> "list[str]":
        """파일명 패턴이 이미 나르는 **원본 데이터 열** — 식별 요약 토큰 모드 입력(결정 37).

        파일명 토큰은 **매핑 후 템플릿 필드** 네임스페이스인데(파일명은 매핑 적용 후 레코드에서
        해소, :meth:`~hwpxfiller.gui.run_state.RunViewModel.unresolved_name_tokens`), 식별
        요약은 **원본 레코드**(사용자가 데이터에서 본 열)를 소비한다. 그래서 파일명이 요구하는
        템플릿 필드를 매핑의 ``source`` 로 역해소해 원본 열로 돌려준다 — 그렇지 않으면 토큰
        모드가 엉뚱한 네임스페이스로 오발한다(confirm-or-alarm).

        **원본 열을 실제로 나르는 유형만** 대상이다(:data:`~hwpxfiller.domain.mapping.
        SOURCE_CARRIER_TYPES`). ``const`` 은 리터럴을 방출해 ``source`` 값과 무관하고(옛 매핑에서
        ``source`` 가 남아 있어도 파일명은 그 열을 나르지 않는다), ``blank`` 은 빈 값이다 — 둘을
        나르는 열로 오인하면 구별 열이 토큰 모드로 침묵 배제된다(리뷰 반영). 원본 레코드에
        실재하는 열만 반환한다(부재 열 헛발 방지).
        """
        from ..naming import pattern_field_tokens

        if self.vm is None:
            return []  # 작업 미선택 = 파일명 네임스페이스 부재 — 토큰 모드 입력 없음
        tokens = set(pattern_field_tokens(self.vm.job.filename_pattern))
        present = set(self.records[0].keys()) if self.records else set()
        cols: "list[str]" = []
        for m in self.vm.job.mapping.mappings:
            # source 유래 유형만 파일명이 그 열을 나른다(단일 출처 SOURCE_CARRIER_TYPES).
            if (m.template_field in tokens and m.type in SOURCE_CARRIER_TYPES
                    and m.source in present and m.source not in cols):
                cols.append(m.source)
        return cols

    def _record_rows(self, indices: "list[int]", mapped: "list[dict]") -> "list[dict]":
        """각 레코드 = 원본 식별 요약 + 그 행이 만들 **실**파일명 미리보기(F33).

        ``indices``·``mapped`` 는 :meth:`snapshot` 가 1회 계산해 넘긴다(``_mirror`` 와 공유 —
        매핑 이중 적용 방지, 리뷰 반영).

        식별 요약은 링1 단일 함수(:func:`~hwpxfiller.domain.identity_summary.identity_summary`,
        결정 37·A-1-15)가 **전체 레코드 집합 위에서 1회** 판정한다 — 어느 열로 요약할지는
        집합 의존(중복 해소·토큰 모드)이라 선택과 무관하게 안정적이어야 한다. 표면은 표현만
        입히고 '어느 열'은 재구현하지 않는다(부록 A-1-15).

        파일명은 생성과 동일 규칙으로 계산한다(:func:`~hwpxfiller.naming.plan_output_names`).
        ``{{seq}}``·충돌 접미사는 최종 선택 집합에 따라 달라지므로 **선택된** 레코드에만 이름을
        계산한다(미선택 행에 확정되지 않은 이름을 지어내지 않는다 — confirm-or-alarm). 날짜 토큰
        기준 시각은 여기서 캡처해 ``_names_now`` 로 남긴다(:meth:`generate` 가 같은 값 소비 —
        RC-02 '확인 대상=생성 대상'의 미리보기 확장).
        """
        if not self.records:
            return []
        from ..naming import plan_output_names

        names: "dict[int, str]" = {}
        if indices and self.vm is not None:  # 파일명은 작업 속성 — 미선택이면 미리보기 없음
            # 시각은 **이 스냅샷이 잡아 둔 것**을 쓴다(2R P2): 여기서 따로 찍으면 같은
            # 스냅샷 안에서 게이트 감사(refresh)와 표 「문서」 열이 다른 시각을 갖고,
            # `{{date:SS}}` 같은 하위-일 토큰이 초 경계를 넘는 순간 미리보기가 승인시킨
            # 이름과 생성물이 갈린다(덮어쓰기 대상 집합까지 함께 바뀐다). 캡처는
            # :meth:`snapshot` 이 스냅샷당 1회 한다 — 폴백은 직접 호출(테스트) 경로용이다.
            if self._names_now is None:
                self._names_now = self._clock()
            planned = plan_output_names(
                self.vm.job.filename_pattern, mapped, now=self._names_now,
            )
            names = dict(zip(indices, planned, strict=True))
        isum = identity_summary(
            self.records, filename_tokens=self._filename_source_columns()
        )
        # 목록 순서 = 표시순 투영 — 각 행은 원본 index 를 지녀 선택·토글이 안전하다.
        # 선택 표지는 **존 대상**(초안이 열려 있으면 초안)이다: 표는 사용자가 지금 편집하는
        # 것을 그린다(F3 판정 D 경계표 1행).
        zone_sel = self._zone_sel()
        return [
            {
                "index": i,
                "selected": zone_sel.is_selected(i),
                "name": names.get(i, ""),
                "summary": isum.display_for(self.records[i]),  # 표시=빈 세그먼트를 마커(빈칸)로 채워 위치 보존(생략 아님 — 서로 다른 행이 동일 문자열로 붕괴하는 것 차단)
            }
            for i in self._display_indices(list(range(len(self.records))))
        ]

    # ---- 본문 존(U2 §2.13 — 표 없는 한 줄) ------------------------------------
    # 구 거울 테이블(_mirror·_field_value_display·_formatted_fields)은 필드축 ack 폐기와
    # 함께 사망했다: 값을 말하는 표면은 확인 면(미리보기 시트) 하나다. 여기 남는 것은
    # danger 차단 배너의 재료(drift 필드)와 빈 값 표지의 재료(blank_fields)뿐이다.
    @staticmethod
    def _drift_fields(status) -> "list[str]":
        """구조 불일치 필드 — 선택과 무관하게 차단 배너로 발화한다(결정 36·RC-23)."""
        return [st.name for st in status.field_states if st.state == "drift"]

    def _filter_sections(
        self, indices: "list[int]", record_rows: "list[dict]"
    ) -> "tuple[dict, dict, dict, dict]":
        """필터·테이블·재진술 유래 스냅샷(블록 4) — 합성은 공유 믹스인(:class:`~hwpxfiller.
        webapp.data_zone.DataZoneMixin`), 여기는 화면 몫(선두 「문서」 열 소재·재진술 유래·
        가드)만 얹는다.

        - **table/filter**: :meth:`_zone_sections` 가 FilterView 1회 평가(캐시 계약)로 합성.
          선두 「문서」 열 소재(이름·요약)는 ``record_rows`` 재사용(F33 승계 — 조용한 드롭 아님).
        - **restate.origin**: 선택 유래는 **집합 비교로 매 스냅샷 판정**(무상태 — 캡처
          시점 정의 텍스트가 스테일해지는 창이 없다): 선택==현 매치 전체 = 정의-유래,
          그 외 = 직접(필터 활성이면 매치/밖 수치 병기 — S4 델타).
        - **restate.sample**: 층화 표본(결정 5) — 광의 OR 에서 소수 가지가 반드시 등장.
        """
        if self.filter is None:  # 데이터 미겨눔 — 작업 미선택은 무관(데이터 존은 세션 소유)
            return _EMPTY_FILTER, _EMPTY_TABLE, _EMPTY_RESTATE, self._guard_state()
        # 선두 열 소재는 ``record_rows`` 재사용 — 이 화면은 그 목록을 스냅샷 ``records`` 로도
        # 싣기 때문에 이미 전량 지어져 있다(믹스인은 실리는 행에만 이 조회를 부른다).
        rows_by_index = {r["index"]: r for r in record_rows}
        filter_snap, table_snap, view, visible = self._zone_sections(
            indices, rows_by_index.__getitem__
        )
        assert view is not None  # filter 존재를 위에서 확인 — 믹스인 빈 골격 분기 아님
        # 판정(유래·수치)은 **필터의 가시 집합**을 쓴다 — 렌더용 `visible` 은 「선택된 항목만
        # 보기」에서 갈아끼워지므로(F3), 그걸로 유래를 판정하면 보기 상태가 곧 「정의-유래」로
        # 둔갑한다. 보기와 판정을 같은 값으로 뭉개지 않는다.
        zone_flt = self._zone_flt()
        assert zone_flt is not None
        vis_set = set(view.visible_indices())
        sel_set = set(indices)
        f_active = zone_flt.is_active()
        origin = None
        if indices:
            origin = "definition" if (f_active and sel_set == vis_set) else "manual"
        restate_snap = {
            "origin": origin,
            "filter_active": f_active,
            "in_def": len(sel_set & vis_set) if f_active else 0,
            "extra": len(sel_set - vis_set) if f_active else 0,
            "sample": (
                view.stratified_sample(indices, _RESTATE_SAMPLE)
                if f_active else indices[:_RESTATE_SAMPLE]
            ),
        }
        # 세션 가드는 **커밋된** 범위의 판정이다(F3 판정 D): 초안이 열려 있으면 위 view 는
        # 초안 필터의 것이라 가시 집합을 물려주면 남의 정의로 커밋 선택을 잰다. 그때만
        # 재평가한다(평시엔 이중 평가 금지 계약 그대로 — 리뷰 #7).
        guard = (
            self._guard_state() if self.range_draft is not None
            else self._guard_state(vis_set=vis_set)
        )
        return filter_snap, table_snap, restate_snap, guard

    # ------------------------------------------------- 세션 가드(블록 4, 결정 26·27)
    def _guard_state(self, vis_set: "set[int] | None" = None) -> dict:
        """무장 판정 = 집합 비교(결정 27) — "재현 불가능한 수작업"이 있는가.

        술어 몸통은 :meth:`~hwpxfiller.webapp.data_zone.DataZoneMixin._selection_guard` 공유
        (txt T3 가드와 단일 출처, 슬라이스 6 PR-4) — 여기선 이 화면의 **완료 이벤트가 설명하는
        집합**만 댄다: 마지막 생성분(생성 = 무장 해제). 수동 필드 입력 성분은 빠른 기안
        표면(블록 5)이 슬라이스 7 에서 합류한다.

        ``vis_set`` 은 렌더 경로(:meth:`_filter_sections`)가 이미 산출한 가시 집합 —
        스냅샷에서 필터를 이중 평가하지 않기 위한 전달이다(FilterView 캐시 계약,
        고효율 리뷰 #7). 디스패치 단발 판정(select_job·guard_state)은 생략하고 직접 평가.

        구 ``ack_count`` 열거 성분은 필드축 ack 폐기(U2 §2.13)와 함께 걷혔다 — 세워 둔
        확인이라는 상태 자체가 없어졌으므로, 남겨 두면 가드가 **존재하지 않는 것을
        잃는다고** 말한다(과경고는 경보를 싸구려로 만든다).
        """
        return self._selection_guard(
            settled=set(self._last_generated or ()), vis_set=vis_set
        )

    def _do_guard_state(self, p: dict) -> dict:
        """무장 상태 실시간 질의 — 표면의 파괴 전이 사전 확인(데이터 재겨눔·재연결)이 소비.

        스냅샷 캐시(LAST.guard)는 왕복 지연·무푸시 경로(``generate`` 는 dispatch 밖이라
        push 가 없다)에서 stale 이 된다 — 판정은 항상 Python 이 지금 내린다(고효율 리뷰
        #4: 완주 직후 데이터 재겨눔에 거짓 확인 모달·#3: 무장 직후 창에 무확인 통과).
        """
        return self._guard_state()

    _do_guard_state.is_query = True  # 무변이 질의 — dispatch 가 push 를 생략한다

    def snapshot(self) -> dict:
        """세션 패널 스냅샷 — 필드는 실행 화면과 평행(링1 배선 감사 가능).

        존 배치는 job.js 소관(현재 데이터·거울·결과 / side-card 후보·정체·생성 준비).
        좌 목록 4키(``job_rows``·``job_sections``·``job_flat``·``job_group_names``)는 표면과
        함께 사망했다(F2 PR-B, 지도 §10.9 판정 F): 아무도 그리지 않는 페이로드가 남으면 다음
        세션이 그걸 근거로 목록을 되살린다. 저장된 작업의 전역 목록은 「문서 작업」 소관이다.
        """
        # 조회 경계(재작성 F6 — TXT 합류): 이 화면은 **저장 작업 전체**를 조회한다. 방식
        # 국경은 이제 후보 판정(`compatibility_for`)이 지므로 목록에서 미리 걸러 내지
        # 않는다 — 여기서 빼면 후보 판정이 못 보는 작업이 생겨 「확인 필요」 사유도 못 낸다.
        registry_notice_text = ""
        try:
            jobs = list_jobs(self.registry)
        except Exception:  # noqa: BLE001 — 조회 장애는 빈 후보 + loud 안내로 표면화한다.
            jobs = []
            registry_notice_text = (
                "문서 작업 목록을 다시 확인할 수 없습니다. "
                "잠시 뒤 다시 시도하세요."
            )
        notice_text = " ".join(
            filter(None, (self.data_notice_text, registry_notice_text))
        )
        notice_level = "warn" if registry_notice_text else self.data_notice_level
        base = {
            "job_name": self.job_name,
            # managed HWPX comes from durable Work identity, never a suffix heuristic.
            "managed_hwpx": False,
            # 직전 런의 주체(3R P2) — 결과 구획의 행동이 "이 결과가 지금 열린 작업의
            # 것인가"를 물을 때 쓰는 값. 판정에 드는 두 값이 같은 출처(이 스냅샷)에서 온다.
            "last_run_job": self._last_run_job,
            # 작업이 선택됐는가 — **`vm` 이 아니라 이름**이다(F6): TXT 는 hwpx 실행뷰를
            # 세우지 않으므로 `vm is not None` 은 "선택됨"이 아니라 "hwpx 로 실행한다"다.
            "has_job": bool(self.job_name),
            # 실행 행동 = **매체 파생 2분기**(F6 판정 D). 라벨과 행동 키를 Python 이 낸다 —
            # 표면이 매체를 다시 읽어 분기하면 같은 판정이 두 곳에 산다.
            "run_action": self._run_action(),
            # 세션 가드 무장 상태(결정 26·27) — 표면 참고용(진실은 guard_state 실시간 질의;
            # 렌더 판은 _filter_sections 가 같은 뷰로 산출해 아래 update 가 덮는다).
            "guard": {
                "armed": False, "sel_count": 0, "in_def": 0, "extra": 0,
                "filter_active": False, "filter_parts": 0,
            },
            "out_dir": self.out_dir,
            # 전체 표시순서 축(§18.10) + 그 옆 상시 재진술(판정 I). 값은 데이터 귀속이라
            # 작업 미선택 상태에서도 실린다 — 축은 데이터의 성질이지 작업의 성질이 아니다.
            "view_order": self.view_order,
            "order_note": self._order_note(),
            # 존 표 머리의 「선택 N/M」 — **존 대상**의 수치다(리뷰 3R). `selected_count` 는
            # 커밋 수치로 남아 게이트 지목 같은 판정이 계속 소비한다: 같은 이름의 값 하나가
            # 두 세계를 겸하면, 초안 체크박스와 footer 는 3건인데 표 머리만 5건인 자리가 난다.
            "zone_selected_count": self._zone_sel().selected_count(),
            # 존 변이가 되실어 보낼 대상 세계 세대(리뷰 4R) — 웹은 판정하지 않고 나른다.
            "zone_epoch": self.zone_epoch,
            # **커밋된** 실행 입력의 지문 — 완료 결과의 세션 판정(F4 판정 G 강등)이 소비한다.
            # 표면이 표의 선택 표지로 이 값을 만들면, 표가 초안을 그리는 동안(F3 판정 D)
            # 적용도 안 한 편집이 결과를 강등시키고 취소해도 되돌아오지 않는다(리뷰 1R).
            # 순서까지 담는다: 표시순서가 바뀌면 파일 이름이 실제로 달라지므로 같은 선택도
            # 다른 실행 입력이다(§2 충돌 B). 승인 결속(F5 판정 I)이 같은 값을 쓴다.
            "selection_key": self._selection_key(),
            # **이 마운트의 정체**(#363 리뷰 P2) — 결과 처분(§2.18)의 데이터 성분이 소비한다.
            # 표시 라벨(`data_source_label`)로는 못 가른다: 같은 basename 의 다른 파일·같은
            # 통합문서의 다른 시트·같은 경로의 바뀐 내용이 전부 같은 문자열이라, 데이터를
            # 갈아 끼워도 「교체」로 안 읽히고 결과가 남의 데이터에 붙은 채 남는다.
            # 값은 **마운트 세대**다(`_reset_range_for_snapshot` 단조 증가 — 호출자는
            # `load_data_path`·`_after_pool_load` 둘뿐이라 마운트 ⟺ 세대 변화). 경로·시트
            # 정체를 여기서 다시 조립하지 않는 이유가 둘: ①어느 파일인가와 무관하게
            # **다시 읽었다**는 사실 자체가 교체이므로 세대가 더 정확하다(같은 경로 재읽기도
            # 새 레코드다) ②경로 정체성 축은 §5.3/#347 이 재편 중이라 두 정의가 생긴다.
            # 승인 범위 키(`_review_scope_key`)가 같은 세대를 쓰는 것도 같은 근거다.
            "data_mount": self._snapshot_gen,
            "data_label": self.data_label,
            # 소스 종류 병기 라벨(#26) — 저장 상태가 아니라 플래그에서 매번 합성(K8).
            "data_source_label": source_label(self.data_source, self.data_label),
            # 마운트 대상 재진술(F1) — 데이터 선택 다이얼로그의 「현재 데이터」·고정 프리필.
            "data_target": self._data_target(),
            # 데이터 겨눔 결과 재진술(preferred_work 판정 등) — 없으면 None.
            "data_notice": (
                {"level": notice_level, "text": notice_text}
                if notice_text else None
            ),
        }
        # 산출물 관찰 시트(S7-03 · #825) — 열림·대상·판정·수치는 전부 Python 이 낸다.
        # 어느 갈래로 빠져나가든 키가 있어야 표면이 키 부재로 갈라지지 않으므로 `base` 에 산다.
        base["artifact_view"] = self._artifact_view_payload()
        # 「이 데이터로 새 작업」 가부(U2 §2.4·#349 리뷰 P1) — **판정은 여기 하나**다.
        # 표면이 `data_target.path` 유무로 유추하면 「누를 수 있다」고 그려 놓고 백엔드가
        # 거절하는 어긋남이 난다. 막힐 땐 숨기지 않고 비활성 + 사유 병기(조용한 무동작 금지).
        _handoff, _blocked = self.new_work_handoff()
        base["new_work"] = {"can": not _blocked, "reason": _blocked}
        # 후보(§18.4) — 데이터 준비 시에만 계산(§18.1: 미준비면 계산 자체를 하지 않는다).
        # 판정 fields 는 필터 열 파생과 같은 원천(records[0].keys — 표시=판정 정합).
        base["candidates"] = self._candidate_payload(jobs)
        # 문서 탐색(§18.6) — 후보 줄의 「외 N건」·「확인 필요」가 여기로 이어진다.
        base["browse"] = self._browse_payload(jobs)
        # 범위 초안 구획(F3) — 열림 여부가 DOM 클래스가 아니라 **상태**다(§10.11.2 정체 면).
        base["range_draft"] = self._range_draft_payload()
        # 템플릿 변경 존(S3-09) 기본값 — TXT·미상·미선택은 명시적 unsupported(키 부재 분기
        # 금지). hwpx 분기가 실제 capability·현재 Preparation 으로 덮어쓴다.
        base["template_change"] = unsupported_zone()
        # S4 Working Slot Configuration 존 기본값(SX-02 #725) — TXT·미선택·미상 매체는 명시적
        # 미지원(키 부재 분기 금지, template_change 선례). hwpx 분기가 실제 fresh view 로 덮는다.
        base["slot_configuration"] = self._slot_blank_zone()
        # Selection Preset 목록 존 기본값(S9-03 #829) — 같은 이유로 키 부재 분기를 만들지 않는다.
        base["content_presets"] = self._content_presets_blank()
        if self.job_is_txt:
            # ── TXT 작업 선택(재작성 F6) — 실행 표면이 작업대라 hwpx 실행뷰가 없다.
            # 데이터 존·후보·탐색은 hwpx 와 **완전히 같은 것**을 쓴다(§18.11-24: 두 매체가
            # 같은 OrderedSelection 을 소비한다). 갈리는 것은 게이트와 실행 행동뿐이다.
            zone_indices = self._zone_indices()
            record_rows = self._record_rows(zone_indices, [])
            filter_snap, table_snap, restate_snap, guard_snap = self._filter_sections(
                zone_indices, record_rows
            )
            # 템플릿 정체는 **이번 스캔의 목록**에서 집는다 — 세션이 Job 사본을 들지 않으므로
            # (1R P2) 이름 변경·재연결이 자동으로 반영되고, 추가 I/O 도 없다(목록은 위에서
            # 이미 읽었다). 그사이 삭제됐으면 정직하게 「템플릿 없음」으로 그린다 —
            # 세션 정리는 `_do_refresh` 의 소실 고지가 다음 왕복에서 한다.
            txt_job = next((j for j in jobs if j.name == self.job_name), None)
            tpath = txt_job.template_path if txt_job is not None else ""
            # 세션 축의 연결 상태(#342 3R) — 술어·문안 단일 출처. 재연결 도달 보장이 이
            # 축에 걸리므로 매체 가지마다 빠짐없이 싣는다(진입 게이트도 같은 술어를 쓴다).
            tmissing, tconn = _template_conn(tpath)
            g = workbench_entry_gate(
                has_data=self.datasource is not None,
                selected_count=self.selection.selected_count(),
                template_ready=not tmissing,
            )
            base.update({
                "template_name": Path(tpath).name if tpath else "",
                "template_path": tpath,
                "template_missing": tmissing,
                "conn_label": tconn,
                # 파일 이름 규칙은 TXT 에 **없다**(§3.2) — 빈 문자열은 "아직 안 정했다"가
                # 아니라 "이 매체엔 그 축이 없다"이고, 표면이 그 자리를 그리지 않는다.
                "filename_pattern": "",
                "has_data": self.datasource is not None,
                "record_count": len(self.records),
                "selected_count": self.selection.selected_count(),
                "records": record_rows,
                "preflight": {"level": "", "text": ""},
                # 빈 값 표지·드리프트·이름 토큰은 hwpx 생성 경로의 것이다 — TXT 는 값
                # 확인을 작업대가 레코드마다 눈으로 하므로 여기서 겸하지 않는다(판정 단일 출처).
                "blank_fields": [], "drift": [], "name_tokens": [],
                "filter": filter_snap, "table": table_snap, "restate": restate_snap,
                "guard": guard_snap,
                "gate": {"enabled": g.enabled, "level": g.level, "text": g.text,
                         "reason": g.reason},
                # 검토 요구·확인 면은 **배제 선언**(지도 §10.15 판정 J): 확인 면은
                # 값+파일 이름+승인의 면인데 TXT 엔 파일 이름 축이 없고, 작업대가 이미
                # 레코드 전수를 채운 모습으로 보여 주는 검토 표면이다. 골격만 실어 표면이
                # 키 부재로 갈라지지 않게 한다.
                "review": self._review_payload(ReviewRequirement(), None),
                "preview": {"open": False, "pos": 0, "total": 0, "can_open": False,
                            "blank_only": False, "blank_count": 0,
                            "can_prev": False, "can_next": False},
            })
            return base
        if self.vm is None:
            # 작업 미선택 상태 — 데이터 존은 세션 소유라 그대로 산다(데이터-우선, §18.2).
            zone_indices = self._zone_indices()
            record_rows = self._record_rows(zone_indices, [])
            filter_snap, table_snap, restate_snap, guard_snap = self._filter_sections(
                zone_indices, record_rows
            )
            g = prework_gate(
                has_data=self.datasource is not None,
                selected_count=self.selection.selected_count(),
                # available 만 센다(#302 리뷰 P2) — needs_action 뿐이면 모든 후보 버튼이
                # 비활성이라 "선택하세요"는 이행 불가능한 지시(문안 정직성 위반)가 된다.
                # 순위 밖(more)도 선택 가능한 후보라 top 이 비어야만 "없음"이다.
                has_candidates=bool(base["candidates"]["top"]),
            )
            # **미상 매체는 「작업 미선택」이 아니다**: 작업은 골라져 있고(`has_job`) 실행
            # 표면만 없다. prework 문안("먼저 문서 작업을 선택하세요")을 그대로 쓰면 이미
            # 고른 사람에게 이행 불가능한 지시를 주고, 화면은 「작업 있음」과 「없음」을
            # 동시에 말한다. 사유와 복구 동선(재연결)을 그 자리에서 말한다.
            unsup_job = (
                next((j for j in jobs if j.name == self.job_name), None)
                if self.job_unsupported else None
            )
            utpath = unsup_job.template_path if unsup_job is not None else ""
            if self.job_unsupported:
                # 막는 축은 템플릿이다 — 게이트 문안·사유는 링1 단일 산출(P2-24).
                g = unsupported_media_gate()
            # 연결 상태는 **작업이 있을 때만** 참·거짓을 말한다(#342 3R): 미선택 상태에서
            # 빈 경로를 「템플릿 없음」으로 부르면 화면이 없는 작업의 부재를 경보한다.
            umissing, uconn = _template_conn(utpath) if self.job_name else (False, "")
            base.update({
                "template_name": Path(utpath).name if utpath else "",
                "template_path": utpath,
                "filename_pattern": "",
                "template_missing": umissing,
                "conn_label": uconn,
                "has_data": self.datasource is not None,
                "record_count": len(self.records),
                "selected_count": self.selection.selected_count(),
                "records": record_rows,
                "preflight": {"level": "", "text": ""},
                "blank_fields": [], "drift": [], "name_tokens": [],
                "filter": filter_snap, "table": table_snap, "restate": restate_snap,
                "guard": guard_snap,
                # 게이트는 링1 단일 산출(prework_gate) 소비 — 링2 문안 재조립 금지(RC-23 동형).
                "gate": {"enabled": g.enabled, "level": g.level, "text": g.text,
                         "reason": g.reason},
                # 작업이 없으면 검토할 규칙도 미리볼 값도 없다 — 뼈대만 실어 표면이
                # 키 부재로 갈라지지 않게 한다(빈 값과 없는 키는 다른 결함류를 만든다).
                "review": self._review_payload(ReviewRequirement(), None),
                "preview": {"open": False, "pos": 0, "total": 0, "can_open": False,
                            "blank_only": False, "blank_count": 0,
                            "can_prev": False, "can_next": False},
            })
            return base
        job = self.vm.job
        # S6-05(#812) 의미 3 파생 전환: bool(authority_id) 는 slotless 발급 작업까지 managed 로
        # 취급해 generate-once 트랩(#806 R1)의 곱 반대편 항이었다. managed 는 「materialization
        # 대상인가」= slot-bearing 사실(링1 projection 이 이미 소유)에서 파생한다.
        base["managed_hwpx"] = self._is_managed_hwpx_work(job)
        indices = self._indices()
        # 빈 값 집합 1회 계산(U2 §2.13 단일 술어) — 표식(marker)·빈 값 표지(blank_fields)·
        # 승인 지문 성분(scope key 해시)·요구 판정(blank_set)이 전부 이 한 집합을 소비한다.
        # 표식이 붙으면 파일명 패턴이 그 필드를 참조할 때 이름·수렴·경로 길이가 전부
        # 달라진다(1R P2 · 4R P2) — 생성·미리보기·승인이 같은 술어를 공유해야 하는 이유.
        blanks = self.vm.blank_fields(indices) if indices else []
        marker = blank_marker(blanks)
        # 검토 요구(F5) — 요구 판정은 durable 기준선이, 승인 대조는 세션이 한다.
        req, req_unmet = self._review(indices=indices, blanks=blanks)
        # 파일명 날짜 토큰의 기준 시각(2R·3R·5R P2) — 이 값은 **사용자가 본 것**의 일부다.
        #
        # 스냅샷당 1회 캡처하면 한 스냅샷 안의 소비처(게이트 감사·표 「문서」 열·드로어·
        # 생성)는 서로 맞지만 **스냅샷 사이**에서 움직인다: `{{date:SS}}` 가 그 사이 초
        # 경계를 넘으면 생성이 사용자가 본 적 없는 이름을 쓴다. 그래서 **누군가 그 값에
        # 기대는 동안 얼린다**. 기대는 자리는 셋이다:
        #   ① 면이 열려 있다(지금 보고 있다)
        #   ② 승인이 서 있다(그 이름으로 확인했다)
        #   ③ **한 번 본 뒤 아직 그 실행 입력 그대로다**(5R P2) — 검토 요구가 없는 반복
        #      실행에서도 미리보기는 열린다(§13-2). 생성 버튼을 누르려면 면을 닫아야
        #      하는데 닫는 순간 ①②가 다 거짓이라, 1초만 들여다봐도 화면이 보여준 것과
        #      다른 이름(그리고 다른 덮어쓰기 대상)이 만들어졌다.
        # 핀은 **실행 입력이 그대로인 동안**만 유효하다 — 규칙·데이터·표식·선택 중 하나라도
        # 바뀌면 화면이 보여준 이름도 이미 낡았으므로 새로 찍는 게 맞다(승인 정체와 같은 축).
        pin = f"{req.rules_key}|{self._review_scope_key(indices, blanks)}"
        if self.preview_open:
            self._names_pin = pin      # 보고 있는 동안 핀은 현재 정체를 따라간다
        pinned = self._names_pin == pin
        if self._names_now is None or not (
            self.preview_open or (req.required and req_unmet is None) or pinned
        ):
            self._names_now = self._clock()
            self._names_pin = None
        # 선택분 매핑 적용은 표식 유/무 각 1회 — 표식 없는 판(빈 값 자리 판정)과 생성
        # 입력 판(_record_rows·확인 면)이 공유한다(이중 적용 방지).
        mapped = self.vm.mapped_records(indices) if indices else []
        run_mapped = self.vm.mapped_records(indices, marker) if marker else mapped
        # 게이트에는 **아직 승인 안 된** 요구만 넘긴다(승인됐으면 그 자리에서 열려야 한다).
        status = self.vm.refresh(  # 사전검증+배지+게이트+이름 계획 단일 산출(RC-23)
            indices, self.out_dir, review_unmet=req_unmet, mapped=run_mapped,
            now=self._names_now,
        )
        preflight_text = (
            _PREFLIGHT_OK_TEXT if status.preflight.level == "ok" else status.preflight.text
        )
        drift_fields = self._drift_fields(status)
        # 빈 값 있는 건의 자리(§2.13) — 표식 **없는** 매핑 출력에서 센다(표식을 채우면
        # 언제나 0건). 확인 면 「빈 값 있는 건만 보기」와 ‹ › 가용성이 소비한다.
        blank_positions = self._preview_blank_positions(mapped)
        # 표는 **존 대상**을 그린다(F3 판정 D): 초안이 열려 있으면 그 선택·축으로 이름까지
        # 다시 계획한다 — 이름이 커밋 기준이면 편집기 안에서 순서를 바꿔도 「문서」 열이 안
        # 움직여 판정 I 의 완화가 하필 그 축을 만지는 자리에서 죽는다. 초안이 없으면 위에서
        # 이미 계산한 실행 입력·매핑을 그대로 재사용한다(평시 추가 비용 0).
        zone_indices = self._zone_indices()
        zone_mapped = run_mapped
        if self.range_draft is not None:
            # 초안 집합의 표식은 그 집합에서 다시 센다 — 빈 값 여부는 선택에 딸린 사실이다.
            zone_marker = self._run_marker(zone_indices)
            zone_mapped = (
                self.vm.mapped_records(zone_indices, zone_marker) if zone_indices else []
            )
        record_rows = self._record_rows(zone_indices, zone_mapped)
        filter_snap, table_snap, restate_snap, guard_snap = self._filter_sections(
            zone_indices, record_rows
        )
        # 템플릿 부재 시에만 복구 동선(다시 연결)을 노출한다(F30) — 홈 카드와 대칭. 술어·
        # 문안은 `_template_conn` 단일 출처이고, 이 축이 **재연결 도달 보장**을 진다
        # (#342 3R): 조건 없는 세션 값이라 데이터·호환성·순위와 무관하게 흐른다.
        tmissing, tconn = _template_conn(job.template_path)
        # 템플릿 변경 존(S3-09) — 판정·token·epoch 전부 코디네이터 소유(링2 재조립 금지).
        if self._template_change is not None:
            base["template_change"] = self._template_change.zone(self.job_name, "hwpx", tmissing)
            # 원본 파일이 캡처 이후 편집됐으면 시끄럽게 표식한다(생성은 캡처본을 씀, #681 F1).
            base["source_drift"] = (
                None if tmissing else self._template_change.source_drift_note(self.job_name)
            )
        # S4 Working Slot Configuration 존(SX-02 #725) — projection·token·상태 전부 Product 소유
        # (링2 재조립 금지). fresh current view 를 매 스냅샷 조회한다: open 은 무변이라 늘 fresh
        # view+새 token 을 낸다(F1/F2 fence). preserved/broken/detached 분리는 projection 이 이미 진다.
        base["slot_configuration"] = self._slot_configuration_zone(tmissing)
        # Selection Preset 목록 존(S9-03 #829) — 같은 지원 조건에서 함께 선다. 손상 항목은
        # 숨기지 않고 함께 실려 표면이 비활성 + 사유 병기로 재진술한다.
        base["content_presets"] = self._content_presets_zone(tmissing)
        # 작업대 Observation(SX-03 #726) — currentness/admission/readiness/7상태/Primary Action 을
        # 한 사용자 작업대 상태로 노출한다. 판정·합성은 Product 소유(링2 재판정 0). 미조립·미선택·
        # 템플릿 부재면 unsupported(조용히 비우지 않는다).
        base["workbench_observation"] = self._workbench_observation_zone(tmissing)
        base.update({
            "template_name": Path(job.template_path).name if job.template_path else "",
            "template_path": job.template_path,  # 추적성 로케이트(#53-B) — 전체 경로
            "template_missing": tmissing,
            "conn_label": tconn,
            "filename_pattern": job.filename_pattern,
            "has_data": self.datasource is not None,
            "record_count": len(self.records),
            "selected_count": self.selection.selected_count(),
            "records": record_rows,
            # 필터 상태·데이터 테이블·재진술 유래·가드(블록 4) — 표면은 받은 것을 그리기만.
            "filter": filter_snap,
            "table": table_snap,
            "restate": restate_snap,
            "guard": guard_snap,
            "preflight": {"level": status.preflight.level, "text": preflight_text},
            # 본문 존 = 표 없는 한 줄(U2 §2.13) — 빈 값 표지의 재료(필드 이름 목록)만
            # 싣는다. 값은 싣지 않는다: 값을 말하는 표면은 확인 면 하나다.
            "blank_fields": list(blanks),
            "drift": drift_fields,
            # 미해소 파일명 토큰(#128) — 드리프트와 **같은 danger 자격**이라 같은 자리(거울)에서
            # 차단 배너 + 행동 링크로 발화한다. 종전엔 게이트 캡션 한 줄뿐이라 거울은 전 행
            # 「채움」으로 건강해 보이고 재진술은 말없이 사라지는, 신호 없는 차단이었다.
            #
            # **게이트가 실제로 이 사유로 막을 때만** 싣는다(리뷰 F2): 토큰 미해소는 템플릿을
            # 못 읽는 상태에서도 참이라, 사실만 보고 그리면 게이트는 "구조를 읽을 수 없다"고
            # 막는데 거울은 크게 "파일명을 고치라"고 말한다 — 사용자를 엉뚱한 수리로 보내고,
            # #128 이 없앤 바로 그 어긋남(문안 ≠ 실제 집합)을 반대 방향으로 되살린다.
            # 서열 판정은 run_state 단일 출처(gate.reason)를 소비하고 여기서 재유도하지 않는다.
            "name_tokens": (
                self.vm.unresolved_name_tokens()
                if status.gate.reason == "name_tokens" else []
            ),
            # `reason` 도 함께 싣는다(리뷰 R1) — 표지 문안이 게이트 서열을 **재유도하지 않고**
            # 이 이름 하나만 읽게 하려고 링1 이 낸 필드다(어휘 분리: 규칙축=「승인」).
            "gate": {
                "enabled": status.gate.enabled,
                "level": status.gate.level,
                "text": status.gate.text,
                "reason": status.gate.reason,
            },
            # 검토 요구·미리보기 드로어(F5). 이름·값은 위 단일 산출을 재사용한다 —
            # 표면이 따로 계획하면 미리보기가 실행과 다른 이름을 말한다(판정 A).
            "review": self._review_payload(req, req_unmet),
            # **규칙의 지문**도 실행 입력의 정체다(6R P2). 결과가 「지금 결과」로 남으려면
            # 그것을 만든 규칙이 아직 그 규칙이어야 한다 — 편집기에서 매핑·파일 이름을 고치고
            # 돌아오면 재적재(`_reload_active_job`)가 규칙을 갈아 끼우는데, 세션 지문에 규칙이
            # 없으면 **다른 규칙으로 만든 결과가 「지금 결과」로 남아** 후속 행동(실패분 선택·
            # 파일 이름 수리)까지 열린 채다. 값은 검토 요구가 이미 계산한 그 지문을 쓴다 —
            # 같은 상태를 두 번 세지 않는다(판정 단일 출처).
            "rules_key": req.rules_key,
            # 드로어는 **생성 입력 그대로**를 그린다(표식 포함) — 여기가 "보이는 것 =
            # 만들어지는 것"의 마지막 자리다.
            "preview": self._preview_payload(
                req, req_unmet, run_mapped, list(status.audit.names),
                (len(status.audit.converged), len(status.audit.too_long)),
                indices, blank_positions,
            ),
        })
        return base

    def initial(self) -> dict:
        return self.snapshot()

    # ------------------------------------------- 네이티브 보조(브리지가 다이얼로그 담당)
    def load_data_path(self, path: str, *, sheet: "str | None" = None) -> None:
        """선택된 데이터 파일을 세션에 마운트. 레코드 0건이면 시끄럽게 실패.

        **데이터-우선(§18.2)**: 작업 미선택에도 마운트할 수 있다 — 데이터는 세션 소유고
        vm 은 있으면 ``set_acquired`` 로 주입받는다. 마운트 직후 선택은 **0건**이다
        (§18.2 commit 뒤 초기화 — 구 전체선택 계약의 개정, 봉합 지도 충돌 A).

        ``sheet`` 는 웹에서 확정한 시트명(다중 시트 확정 게이트 #33, None=CSV·단일 시트).
        시그니처 동형 — 브리지 ``pick_data_file``/``load_data_sheet`` 재사용.
        """
        self.raise_if_generating_before_swap("데이터를 바꾸세요")  # #302 P1 동류
        source, records = resolve_file_source(
            path, sheet=sheet, source_factory=self._file_source_factory
        )  # 실패는 raise(§18.2 원자)
        if not records:
            raise ValueError(NO_ROWS_TEXT)  # 성공 전 현재 runtime 미파기 — 아래 대입 전 반환
        self._stash_filter()  # 죽는 세션의 정의 → 직전 필터 슬롯(결정 28, 옛 소스 키 기준)
        self._last_failed = []  # 실패 index 는 이 레코드 집합에서만 뜻이 있다(§10.10 판정 F)
        self._commit_data_transition(source, records)
        self.data_label = Path(path).name
        self.data_source = "file"  # 병기 라벨은 스냅샷이 합성(#26·K8)
        self.data_pool_key = ""  # 파일 마운트 = 풀 겨눔 해제(§5.3 슬롯 정체)
        self.data_path, self.data_sheet = path, sheet or ""  # 「이 데이터 고정」 프리필(F1)
        # 파일 겨눔은 헤더 행 옵션을 만들지 않는다(어댑터 기본) — 풀 겨눔이 포획해 둔 값이
        # 남지 않게 같은 자리에서 비운다(마운트 성분은 **한 벌**로 갈린다, 리뷰 2R).
        self.data_header_row = 0
        self._data_key = self._file_key(path, sheet)  # 소스 일치 게이트(결정 28)
        self._reset_range_for_snapshot(len(records))  # 선택 0건 + 표시순서 기본(§18.2·F3)
        self._init_filter()  # 데이터 교체 = 필터 재생성(결정 24 — 열 지형이 바뀐다)
        self._push()

    def _commit_data_transition(self, source, records: list) -> None:
        """성공적으로 읽은 새 데이터와 그에 따른 active Work를 함께 세션에 반영한다."""
        work_ref = self.job_name
        seated_job = self.vm.job if self.vm is not None else None
        active_job = None
        restored_template_application_id = None
        restore_failed = False
        exact_context_restorable = False
        if work_ref:
            try:
                active_job = load_job(self.registry, work_ref)
                if self._template_change is not None:
                    restored_template_application_id = (
                        self._template_change.current_template_application_id(
                            active_job.authority_id or None
                        )
                    )
                    if (
                        active_job.authority_id
                        and restored_template_application_id is None
                    ):
                        restore_failed = True
                exact_context_restorable = bool(
                    seated_job is not None
                    # 빈 값끼리의 equality 는 identity 증거가 아니다.
                    and seated_job.authority_id
                    and active_job.authority_id == seated_job.authority_id
                    and self._same_work_snapshot(seated_job, active_job)
                    and (
                        self._template_change is None
                        or bool(
                            restored_template_application_id
                            and self._seated_template_application_id
                            and restored_template_application_id
                            == self._seated_template_application_id
                        )
                    )
                )
            except Exception:  # noqa: BLE001 — 읽을 수 없는 active Work는 exact 복원 불가다.
                active_job = None
                restore_failed = True
        context = ActiveWorkContext(
            active=bool(work_ref),
            work_ref=work_ref or None,
            template_application_ref=restored_template_application_id,
            exact_context_restorable=exact_context_restorable,
            usable_with_current_data=(
                active_job is not None
                and compatibility_for(active_job, list(records[0].keys())).kind == KIND_AVAILABLE
            ),
        )
        decision = decide_active_work_after_data_transition(context)
        self._clear_data_notice()
        if decision.disposition == RELEASE and work_ref:
            self._release_active_work()
        self.datasource = source
        self.records = records
        if self.vm is not None:
            self.vm.set_acquired(source, records)  # 데이터 귀속 원자 진입점(RC-22)
        self._apply_preferred_work()  # 보관된 명시 사건(§18.3 1행)을 이 데이터에서 판정
        preferred_restatement = (
            f" {self.data_notice_text}" if self.data_notice_text else ""
        )
        if restore_failed:
            self.data_notice_text = (
                "이전 문서 작업을 다시 확인할 수 없어 선택을 해제했습니다. "
                f"문서 작업을 다시 선택하세요.{preferred_restatement}"
            )
            self.data_notice_level = "warn"

        elif active_job is not None and not exact_context_restorable:
            self.data_notice_text = (
                "이전 문서 작업이 같은 작업인지 확인할 수 없어 선택을 해제했습니다. "
                f"문서 작업을 다시 선택하세요.{preferred_restatement}"
            )
            self.data_notice_level = "warn"
        elif active_job is not None and not context.usable_with_current_data:
            self.data_notice_text = (
                "이전 문서 작업은 이 데이터로 실행할 수 없어 선택을 해제했습니다. "
                "아래 후보를 선택하거나 「확인 필요」에서 사유를 확인하세요."
                f"{preferred_restatement}"
            )
            self.data_notice_level = "warn"

    def _same_work_snapshot(self, seated: Job, restored: Job) -> bool:
        """authority 외 실행 문맥이 같은 registry Job snapshot인지 판정한다."""
        return (
            job_content_fingerprint(self.registry, restored)
            == job_content_fingerprint(self.registry, seated)
            and restored.template_revision == seated.template_revision
            and restored.binding_revision == seated.binding_revision
            and restored.previous_rules == seated.previous_rules
        )

    def _can_adopt_seated_identity(self, seated: Job, restored: Job) -> bool:
        """identity 미발급 seat만 exact same snapshot의 durable identity를 받을 수 있다."""
        return (
            (not seated.authority_id or seated.authority_id == restored.authority_id)
            and self._same_work_snapshot(seated, restored)
        )

    def set_output_folder(self, path: str) -> None:
        """네이티브 폴더 피커가 고른 저장 폴더를 반영(게이트 전제조건, UD-06)."""
        if self.vm is not None and self.vm.job.authority_id:
            collision = (
                self._run_delivery_intent.collision_policy
                if self._run_delivery_intent is not None
                else ADD_SUFFIX
            )
            self._run_delivery_intent = RunDeliveryIntent(path, collision)
            self._current_delivery_preparation = None
            self._invalidate_current_preview()
            self._push()
            return
        self.out_dir = path
        self._push()

    # ------------------------------------------------------- 웹→Python 데이터 액션
    def dispatch(self, action: str, payload: dict):
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:  # confirm-or-alarm: 미지 액션은 시끄럽게.
            raise ValueError(f"알 수 없는 작업 화면 액션: {action!r}")
        if self._is_stale_zone_edit(action, payload):
            # 조용한 무시가 아니라 **명시 판정**이다: 사용자는 그 세계를 이미 버렸고(취소·
            # 적용·데이터 교체는 전부 명시 행동), 버린 세계의 편집을 지금 세계에 적용하는
            # 것이야말로 조용한 파괴다. 상태는 그대로라 push 도 하지 않는다.
            return {"stale": True, "epoch": self.zone_epoch}
        result = handler(payload)
        # 무변이 경로는 push 를 생략한다(고효율 리뷰 #8) — ① is_query 표식 핸들러(순수
        # 질의: filter_panel·guard_state) ② needs_confirm 반환(가드가 전이를 막아 상태
        # 그대로). 동일 스냅샷 전량 재계산+재렌더가 모달 여는 중에 겹치는 낭비 제거.
        is_query = getattr(handler, "is_query", False)
        blocked = isinstance(result, dict) and result.get("needs_confirm")
        if not is_query and not blocked:
            self._push()
        return result

    def _do_set_delivery_collision(self, p: dict) -> dict:
        if self._run_delivery_intent is None:
            raise ValueError("먼저 저장 폴더를 선택하세요.")
        self._run_delivery_intent = RunDeliveryIntent(
            self._run_delivery_intent.output_directory,
            str(p["collision_policy"]),
        )
        self._current_delivery_preparation = None
        self._invalidate_current_preview()
        return {"ok": True}

    def _do_refresh_delivery(self, p: dict) -> dict:
        if self._run_delivery_intent is None:
            raise ValueError("먼저 저장 폴더를 선택하세요.")
        self._current_delivery_preparation = None
        self._invalidate_current_preview()
        return {"ok": True}

    def _is_stale_zone_edit(self, action: str, payload: dict) -> bool:
        """이 존 변이가 **남의 세계**를 겨누고 있는가(리뷰 4R).

        세대를 안 실은 발신은 검사하지 않는다 — 존을 공유하는 「기안」 화면과 초안 개념이
        없는 호출부는 세대를 모른다(무검사 통과가 그들에게는 정답이다).
        """
        if action not in ZONE_MUTATIONS or "epoch" not in payload:
            return False
        try:
            return int(payload["epoch"]) != self.zone_epoch
        except (TypeError, ValueError):
            return True   # 해석 불가 = 정체 불명 → 적용하지 않는다(안전 방향)

    def _do_refresh(self, p: dict) -> "dict | None":
        """레지스트리 재스캔 반영(C6) + stale 세션 무효화(master-detail 불변식).

        레지스트리(``registry.names()``)와 세션 패널(``self.vm``)이 갈라지지 않게 조정한다: 선택된
        작업이 다른 화면에서 삭제·개명돼 레지스트리에서 사라졌으면 세션을 무효화한다 — 안 그러면
        존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께 남아 유령 작업에서 생성된다
        (리뷰 #2). 조용히 두지 않고 빈 패널로 재진술(후보·라이브러리에서도 사라져 상실이 보인다).
        재스캔 자체는 스냅샷이 매번 ``names()`` 를 재읽어 반영(에디터 저장분 즉시 노출).
        작업 화면은 REFRESH_ON_NAV 에 있어 이 액션이 레일 복귀마다 발화하므로, 타 화면에서의
        삭제(그 화면으로 가려면 반드시 작업 화면을 이탈)가 복귀 시점에 잡힌다.
        """
        names = job_names(self.registry)
        if self.job_name and self.job_name in names:
            # **열린 작업의 규칙이 밖에서 바뀌었으면 다시 읽는다**(4R P1). 편집기가 자기
            # 화면으로 나간 뒤(F7) 저장은 이 화면 밖에서 일어나고, `self.vm` 은 선택 시점의
            # 인메모리 사본이라 그대로 두면 **저장한 사람이 옛 규칙으로 미리보고 옛 규칙으로
            # 생성한다** — 영속·실행 경로가 화면 사이에서 갈리는 자리다. 세션(데이터·선택·
            # 필터·저장 폴더)은 그대로 두고 규칙만 갈아 끼운다.
            self._reload_active_job()
            return None
        if self.job_name and self.job_name not in names:
            lost = self.job_name
            # 세션 무효화(vm·job_name·데이터·폴더 clear). confirm=True — 작업이 이미
            # 레지스트리에서 사라져 가드로 잡아둘 대상이 없다(잡으면 유령 세션 좌초).
            self._do_select_job({"name": "", "confirm": True})
            return {
                "notice": f"'{lost}' 작업이 다른 화면에서 삭제되어 열어 둔 실행 세션을 닫았습니다."
            }
        return None

    def _reload_active_job(self) -> bool:
        """디스크의 최신 규칙으로 활성 VM 을 다시 세운다 — 바뀐 게 없으면 아무것도 안 한다.

        **지문이 갈릴 때만** 손대는 이유(4R P1): 이 경로는 화면 전환마다 발화한다
        (`REFRESH_ON_NAV`). 무조건 재구성하면 평시 왕복이 실행 증거·미리보기 자리를 매번
        되돌려, 아무 일도 없었는데 게이트가 다시 닫히는 것처럼 보인다.

        갈렸을 때 버리는 것은 계약이 버리라는 것뿐이다(§19.10): **완주 담보**(그 규칙으로
        만든 문서가 담보하던 것)와 **열려 있던 미리보기**(옛 규칙의 상). 승인은 따로 지우지
        않는다 — 규칙 지문에 결속돼 자동으로 무효가 된다(F5 판정 I).
        """
        if not self.job_name:
            return False
        try:
            job = load_job(self.registry, self.job_name)
        except Exception:  # noqa: BLE001 — 손상은 다음 스냅샷의 건강 표면이 말한다
            return False
        # **자리가 갈렸으면 다시 앉힌다**(2R P2 → §10.16 판정 E 정정, 리뷰 1R P2). 매체
        # 교차 방어는 게이트가 원천 차단해 이 분기의 옛 역할은 죽었지만, 게이트가 **허용**하는
        # 복구 전이(미상 `.docx` 구작업 → 라이브러리 relink 로 hwpx/txt 에 앉힘)가 자리를
        # 갈고, 그 변화는 이 화면 밖에서 일어난다 — 여기서 안 받으면 화면이 유효해진 템플릿을
        # 재선택 전까지 unsupported 라고 계속 주장한다. 지문 대조는 unsupported 세션(vm 없음)
        # 을 못 보므로 대체가 아니다.
        if seat_kinds(job.template_path) != (self.job_is_txt, self.job_unsupported):
            self._seat_active_job(job)
            self._last_generated = None   # 실행 표면 자체가 갈렸다 — 옛 증거는 남의 것이다
            self._discard_delivered_artifacts()  # 배달 좌표도 그 표면의 것이다(S7-03)
            self._do_preview_close({})
            return True
        # TXT 세션은 여기서 **되살릴 캐시가 없다**(1R P2 이후) — Job 사본을 들지 않으므로
        # 다음 스냅샷이 목록에서 최신값을 집는다. 할 일이 없는 것이 정상이지 누락이 아니다.
        if self.vm is None:
            return False
        # **판본 메타까지 본다**(7R P2). `content_fingerprint` 는 판본 3필드를 일부러 뺀다
        # (편집 세션에 거짓 파괴 확인을 띄우지 않으려고) — 그래서 그것만으로는 "지금 것인가"를
        # 답할 수 없다: 규칙이 A→B→A 로 돌아온 저장은 내용 지문이 같지만 세대는 앞서 있고,
        # 그 상태로 실행하면 결과가 **디스크에 없는 세대**를 자기 근거로 댄다(§13-7).
        # 직전 판본 값도 같은 이유로 센다 — before/after 증거의 원천이다.
        same_rules = job_content_fingerprint(self.registry, job) == job_content_fingerprint(
            self.registry, self.vm.job
        )
        same_generation = (
            job.template_revision == self.vm.job.template_revision
            and job.binding_revision == self.vm.job.binding_revision
            and job.previous_rules == self.vm.job.previous_rules
        )
        if same_rules and same_generation:
            return False
        self._seat_active_job(job)
        if not same_rules:
            # 규칙이 실제로 갈렸을 때만 증거를 걷는다 — 판본 메타만 앞선 경우(A→B→A)는
            # 실행 입력이 그대로라 완주 담보·열린 면을 되돌릴 이유가 없다(과잉 리셋 금지).
            self._last_generated = None
            self._discard_delivered_artifacts()  # 옛 규칙으로 만든 문서다(S7-03)
            self._do_preview_close({})
        return True

    def _seat_active_job(self, job: Job) -> None:
        """활성 작업의 **매체와 실행뷰를 함께** 세운다 — 둘이 갈라질 자리를 남기지 않는다.

        매체 파생 2분기(F6 판정 D): TXT 는 hwpx 실행뷰를 세우지 않는다(`RunViewModel` 이
        템플릿을 hwpx 로 파싱하므로 진입 가드가 loud 거부한다).

        **왜 함수 하나인가**(2R P2 근본 조치): 1R 에서 Job 사본을 지웠지만 그 자리에 매체
        **래치**가 남았고, 그 래치는 「작업 선택」 사건에서만 갱신됐다. durable 템플릿 경로는
        그 사건 **밖에서도** 바뀐다(라이브러리 재연결 — 같은 매체 재연결과 미상 구작업의
        복구가 경로를 갈아 끼운다; 교차는 §10.16 판정 C 가 게이트에서 차단). 값이 갈라진
        상태는 실행 버튼이 엉뚱한 표면을 광고하거나 재적재가 `RunViewModel` 을 세우려다
        터지는 형태로 나타났다. 두 값을 **한 자리에서만** 세우면 갈라질 수가 없고, 갱신이
        필요한 곳은 이 함수를 부르면 된다.
        """
        job_is_txt, job_unsupported = seat_kinds(job.template_path)
        vm = (
            None
            if (job_is_txt or job_unsupported)
            else RunViewModel(job, engine=self._engine)
        )
        seated_template_application_id = (
            self._template_change.current_template_application_id(
                job.authority_id or None
            )
            if vm is not None and self._template_change is not None
            else None
        )
        # 세션 데이터 주입도 **여기가** 한다: vm 을 세우는 자리와 그 vm 이 볼 데이터를
        # 실어 주는 자리가 갈리면, 한쪽만 부르는 경로가 곧 빈 실행뷰가 된다(재적재가
        # 실제로 그랬다). 데이터·선택·필터는 세션 소유라 작업 전환에서 생존한다(§18.2).
        if vm is not None and self.records:
            vm.set_acquired(self.datasource, self.records)  # 데이터 귀속 원자 진입점(RC-22)
        self.job_is_txt, self.job_unsupported = job_is_txt, job_unsupported
        self.vm = vm
        self._seated_template_application_id = seated_template_application_id

    def _run_action(self) -> dict:
        """실행 버튼의 (행동 키, 라벨) — 매체 파생 2분기(§19.1·F6 판정 D)."""
        if self.job_is_txt:
            n = self.selection.selected_count()
            return {"key": "workbench", "label": f"검토·복사 시작 · {n}건"}
        return {"key": "generate", "label": "이 작업으로 문서 생성"}

    def _do_open_workbench(self, p: dict) -> dict:
        """TXT 검토·복사 작업대 진입 — 고정 사본을 넘기고 화면 전환은 웹이 한다.

        **열기는 성사 뒤다**(§10.15.1 계약면 2·3): 자격 없는 진입은 화면을 세우지 않고
        사유를 돌려준다. 진입을 막는 것은 셋이다 — 생성 중(진행 중 런의 규칙을 갈아 끼우면
        RC-02 「확인 대상 = 생성 대상」이 깨진다) · 범위 초안 열림(작업대는 **커밋된** 실행
        입력의 사본을 뜬다 — 적용도 안 한 편집으로 사본을 뜨면 어느 범위인지 갈린다) ·
        게이트 미충족(선택 0건에서 첫 레코드를 대신 쓰지 않는다, §18.10 수용 6).
        """
        if not self.job_is_txt or not self.job_name:
            return {"ok": False, "error": "TXT 검토·복사 작업이 아닙니다."}
        self.raise_if_generating_before_swap("작업대를 여세요")
        if self.range_draft is not None:
            return {"ok": False,
                    "error": "범위 편집을 먼저 적용하거나 취소한 뒤 작업대를 여세요."}
        gate = workbench_entry_gate(
            has_data=self.datasource is not None,
            selected_count=self.selection.selected_count(),
        )
        if not gate.enabled:
            return {"ok": False, "error": gate.text}
        if self.workbench_open is None:  # confirm-or-alarm: 미배선은 시끄럽게(조용한 무동작 금지)
            raise ValueError("작업대 컨트롤러가 배선되지 않았습니다.")
        # Job 은 **쓰는 순간** 읽는다(1R P2) — 세션이 사본을 들고 있으면 그사이 이름이
        # 바뀌거나 규칙이 저장된 것을 못 본다. 여기가 유일한 소비처라 I/O 도 1회다.
        try:
            job = load_job(self.registry, self.job_name)
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": (
                f"작업 '{self.job_name}' 을(를) 읽을 수 없습니다: {exc}")}
        # fail-closed 재확인(매체가 갈렸다면) — 판정은 링1 착석 분류(`seat_kinds`)와 같은
        # 술어다: 작업대의 진입 자격을 상대 화면에 물으면 화면 간 결합이 되살아난다(P2-24).
        if not seat_kinds(job.template_path)[0]:
            return {"ok": False, "error": "TXT 검토·복사 작업이 아닙니다."}
        indices = self._indices()
        try:
            self.workbench_open(job, [(i, self.records[i]) for i in indices])
        except (OSError, UnicodeDecodeError) as exc:
            # 템플릿이 그사이 사라졌거나 읽을 수 없다 — **화면 안에서** 사유를 말한다(5R P2).
            # 날것 예외로 올리면 호출부(.then)가 못 받아 아무 설명 없이 아무 일도 안 난 것처럼
            # 보인다. 게이트도 이 사실을 미리 세지만(버튼이 정직하게 닫힌다) 그 판정과 이
            # 진입 사이에도 파일은 사라질 수 있으므로 둘 다 필요하다.
            #
            # **`UnicodeDecodeError` 도 같은 사건이다**(6R). 작업대는 UTF-8 로 읽는데 온나라
            # 기안 txt 는 ANSI/CP949 로 저장돼 오기 쉽고, 게이트는 파일 **존재**만 세므로
            # 버튼은 열려 있다. `OSError` 가 아니라 `ValueError` 계열이라 잡지 않으면 사유를
            # 말할 자리를 그대로 지나쳐, 열리는 척하던 버튼이 아무 말도 없이 끝난다.
            return {"ok": False, "error": (
                f"템플릿을 읽을 수 없습니다: {exc}. 템플릿을 다시 연결한 뒤 진행하세요.")}
        return {"ok": True, "count": len(indices)}

    def _do_select_job(self, p: dict) -> "dict | None":
        """후보·탐색에서 작업 선택 → RunViewModel 재구성. 저장 폴더 기본 = 템플릿/Results.

        **데이터-우선 보존 계약(§18.2)**: 데이터·선택·필터는 세션 소유라 작업 전환에서
        **생존**한다 — 전환은 vm 만 재생성하고 세션 데이터를 ``set_acquired`` 로 주입한다.
        전환이 잃는 것은 실행 증거(완주 담보·승인)뿐이고(§19.10) 게이트가 재검증을 강제하므로
        조용한 소실이 없다. 구 T1 스위치 가드(전환=세션 파기 재확인)는 파기 자체가 사라져
        함께 죽었다 — 가드 문안은 실제로 사라지는 집합과 일치해야 한다(과경고=거짓말).
        ``confirm`` 페이로드 키는 왕복 동형 유지를 위해 수용하되 더는 판정에 쓰지 않는다.

        (구 기본 데이터셋 자동 조준(#53-A)은 U2 §5.3 판정 D 로 폐기 — 작업 선택은 데이터를
        세우지 않는다. 데이터는 세션 소유라 이미 마운트돼 있으면 전환에서 생존하고, 없으면
        사용자가 데이터 선택 면에서 명시로 고른다 — 요구는 세션당 1회다.)
        """
        name = p["name"]
        # 생성 진행 중 전환 금지(#302 P1) — vm 교체가 진행 중 배치의 검증·계획과 경합한다.
        # 조용한 무시가 아니라 시끄러운 거부(raise → 셸 rejection 백스톱이 표면화).
        self.raise_if_generating_before_swap("작업을 전환하세요")
        self._clear_data_notice()
        # 사용자가 직접 골랐다 = 보관된 명시 사건보다 최신 의사. 들고 있으면 다음 마운트에서
        # 옛 의도가 되살아나 방금 고른 작업을 밀어낸다(지연된 조용한 추측).
        self.preferred_work = ""
        if not name:  # 선택 해제 = 작업만 내려놓는다(데이터 존은 그대로)
            self._release_active_work()
            return
        self._discard_active_work_session_evidence()
        job = load_job(self.registry, name)
        # 실패 목록은 **전환이 실제로 성사된 뒤에** 비운다(2R P2): `load` 가 실패하면
        # 세션은 그대로인데(vm·job_name 불변) 목록만 사라져, 화면에 남은 「실패한 N건만
        # 선택」이 0건을 돌려주는 유령 행동이 된다. 위 `_last_generated` 조기 소거는
        # 안전 방향(가드 재무장)이라 그대로 두지만, 이쪽은 **복구 경로가 사라지는** 방향이다.
        self._last_failed = []
        self._seat_active_job(job)
        self.job_name = name
        if self.records and self.vm is not None:
            # 필터 열 유형 재조정(#302 리뷰 P2): 무작업 마운트의 필터는 값 스니핑만 탔다 —
            # 작업이 정해진 지금 매핑 확정 유형 힌트를 반영한다. 단 **정의 없는 필터만**
            # 재생성한다: 사용자가 이미 만든 정의는 유형 재판정이 술어를 조용히 떨어뜨릴
            # 수 있어 그대로 둔다(사용자 확정 > 유형 힌트 — 조작 순서 의존을 정의 유무의
            # 명시 규칙으로 환원).
            if self.filter is not None and not self.filter.is_active():
                self._init_filter()
        self.out_dir = (
            str(Path(job.template_path).parent / OUTPUT_SUBDIR_NAME)
            if job.template_path else ""
        )
        if job.media == "hwpx" and job.authority_id:
            self._maybe_auto_check(effective_basis_changed=True)

    def _release_active_work(self) -> None:
        """현재 active Work만 해제한다. 데이터와 후보는 그대로 둔다."""
        self._discard_active_work_session_evidence()
        self.vm = None
        self._seated_template_application_id = None
        self._run_delivery_intent = None
        self.job_is_txt = False
        self.job_unsupported = False
        self.job_name = ""
        self.out_dir = ""
        self._last_failed = []

    def _release_changed_active_work(self, reason: str) -> None:
        """외부 권위 변경으로 stale해진 active Work를 loud RELEASE한다."""
        self._release_active_work()
        self.data_notice_text = f"{reason} 선택을 해제했습니다. 문서 작업을 다시 선택하세요."
        self.data_notice_level = "warn"

    def _discard_active_work_session_evidence(self) -> None:
        """active Work에 묶인 실행·검토·미리보기 증거만 버린다."""
        self._last_generated = None
        # 배달 좌표는 **그 작업의 실행**이 낸 것이다(S7-03) — 작업이 바뀌면 남의 문서를
        # 가리키게 되므로 완주 담보와 같은 자리에서 놓는다.
        self._discard_delivered_artifacts()
        self.review.clear()
        self._do_preview_close({})

    # --------------------------------------- 「문서 만들기에서 사용」(§19.8 3분기)
    def _ranked_now(self) -> list:
        """현재 데이터 기준 available 순위 — 후보 구획과 **같은 링1 판정**을 재사용한다."""
        if self.datasource is None or not self.records:
            return []
        fields = list(self.records[0].keys())
        return rank_available(list_jobs(self.registry), fields)

    def _do_prefer_work(self, p: dict) -> dict:
        """라이브러리 「문서 만들기에서 사용」의 착지 — §19.8 분기를 **Python 이 가른다**.

        분기 판정(데이터 준비·호환)은 링1 술어가 이미 소유하므로 표면이 다시 계산하면 같은
        상태를 두 곳이 판정하게 된다(판정 단일 출처). 웹은 반환된 ``reason`` 으로 라우팅만
        한다.

        ```text
        데이터 ready + 호환   → 명시 선택(select_job) — RecordRangeState 는 세션 소유라 생존
        데이터 ready + 비호환 → 활성 불변 + 보관. 표면이 「확인 필요」 탭에서 사유를 보인다
        데이터 없음           → 보관 후 안내 하나 — 데이터 선택을 반드시 지난다(§5.3 판정 D).
                               마운트 시 _apply_preferred_work 가 판정한다
        ```

        (구 ``default_data`` 분기 — 작업의 기본 데이터 참조(#53-A)를 무데이터에서 자동
        마운트 — 는 U2 §5.3 판정 D 로 결속 자체가 폐기되며 죽었다. F2 PR-B 판정 I 가
        걱정한 「#53-A 도달 불가능」은 #53-A 자체가 죽어 소멸. 데이터↔작업 결속은 어느
        방향으로도 다시 들이지 않는다.)

        **비호환에서 활성으로 세우지 않는 이유**: 게이트가 닫힌 채 화면이 "이걸 만들 참"이라고
        말하게 된다. 계약도 그 경우 선택이 아니라 **사유 표면**으로 보내라고 적는다(§19.8).
        """
        name = str(p.get("name", "")).strip()
        if not name:
            raise ValueError("겨눌 작업 이름이 비어 있습니다.")
        if not job_exists(self.registry, name):
            raise ValueError(f"'{name}' 작업을 찾을 수 없습니다.")
        self.preferred_work = name
        if self.datasource is None or not self.records:
            return {"stored": True, "reason": "no_data", "name": name}
        if any(r.name == name for r in self._ranked_now()):
            self.preferred_work = ""  # 소비 — 지금 이뤄졌다
            self._do_select_job({"name": name})
            return {"promoted": True, "name": name}
        return {"stored": True, "reason": "incompatible", "name": name}

    def _apply_preferred_work(self) -> None:
        """마운트 직후 보관된 명시 사건을 재진술한다. **1회 소비**, 자동 선택은 하지 않는다.

        호환 판정은 링1(:func:`preferred_promotion`)이 내고 여기서는 후보 안내만 한다.
        보관분은 **비운다** — 다음 마운트까지 들고 있으면
        사용자가 잊은 의도가 나중에 조용히 발화한다(지연된 조용한 추측 금지).

        선택하지 않은 사유는 삼키지 않는다: 사용자가 방금 「이 작업을 쓰겠다」고 눌렀는데
        아무 일도 안 일어나면 그게 조용한 소실이다. 기존 활성 작업이 있어 계약이 유지를
        지시한 경우(§18.3 2행)와 이 데이터로 실행할 수 없는 경우를 갈라 재진술한다.
        """
        name, self.preferred_work = self.preferred_work, ""
        if not name:
            return
        try:
            exists = job_exists(self.registry, name)
            ranked = self._ranked_now() if exists else []
        except Exception:  # noqa: BLE001 — 후보 조회 실패는 성공한 데이터 마운트를 되돌리지 않는다.
            self.data_notice_text = (
                f"「문서 작업」에서 고른 '{name}' 작업을 다시 확인할 수 없습니다. "
                "아래 후보에서 문서 작업을 다시 선택하세요."
            )
            self.data_notice_level = "warn"
            return
        if not exists:  # 그사이 삭제·개명 — 유령을 겨누지 않는다
            self.data_notice_text = (
                f"「문서 작업」에서 고른 '{name}' 작업이 더는 없습니다."
            )
            self.data_notice_level = "warn"
            return
        promoted = preferred_promotion(
            ranked, active=self.job_name, preferred=name,
        )
        in_top = any(r.name == name for r in ranked[:MAIN_TOP_N])
        next_action = (
            "아래 후보에서 직접 고르세요."
            if in_top else "'문서 작업'에서 직접 선택하세요."
        )
        if promoted:
            self.data_notice_text = (
                f"이전에 고른 '{promoted}' 작업을 사용할 수 있습니다. {next_action}"
            )
            self.data_notice_level = "warn"
            return
        if self.job_name:
            self.data_notice_text = (
                f"'{self.job_name}' 작업이 이미 열려 있어 '{name}' 으로 바꾸지 않았습니다. "
                f"{next_action}"
            )
        else:
            self.data_notice_text = (
                f"「문서 작업」에서 고른 '{name}' 은(는) 이 데이터로 실행할 수 없습니다. "
                "「확인 필요」에서 사유를 확인하세요."
            )
        self.data_notice_level = "warn"

    def _do_toggle_favorite(self, p: dict) -> dict:
        """즐겨찾기 지정/해제(§18.5) — 정렬 메타만 바꾸고 세션은 건드리지 않는다.

        활성 작업·매핑·파일명·검증·선택 어느 것도 폐기하지 않는다(§18.5 명문). 값은
        표면이 보내는 **의도한 상태**(``value``)다 — 현재 값을 여기서 뒤집으면 빠른 연속
        클릭이 서로의 결과를 되돌린다(토글 경합, #215 동류).

        지정 시각은 서버 시각으로 찍는다(정렬 근거를 표면이 정하지 않는다). 작업이 다른
        화면에서 사라졌으면 조용히 넘기지 않고 재진술한다 — 목록이 곧 다음 스냅샷에서
        갱신되므로 파괴는 없다.

        **시각은 레지스트리가 쓰기 잠금 안에서 찍는다**(리뷰 1R·6R P2): ①초 절단이면 1초 안의
        두 지정이 동률이 돼 "최신순"(§18.5)이 거짓이 되고, ②여기서 미리 찍으면 서로 다른 작업
        둘을 연속으로 별 찍을 때 스레드 스케줄링이 나중 클릭에 이른 시각을 줄 수 있다. 잠금 안
        스탬프는 쓰기 순서 = 시각 순서를 담보한다. (생성 스탬프 ``last_run_at`` 은 런 자체가
        초 단위보다 길어 같은 함정이 성립하지 않아 그대로 둔다.)
        """
        name = p["name"]
        try:
            set_favorite(self.registry, name, bool(p["value"]))
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False,
                    "error": f"'{name}' 작업의 즐겨찾기를 바꾸지 못했습니다: {exc}"}
        return {"ok": True}

    def _do_browse_tab(self, p: dict) -> None:
        """문서 탐색 탭 전환(§18.6) — **검색어는 유지한다**(계약 명문).

        미지 값은 링1이 사용 가능으로 퇴화시키므로(표면 오타가 빈 화면을 만들지 않는다)
        여기서는 받은 값을 그대로 세션에 둔다.
        """
        self.browse_tab = (
            TAB_NEEDS_ACTION if p.get("tab") == TAB_NEEDS_ACTION else TAB_AVAILABLE
        )

    def _do_browse_query(self, p: dict) -> None:
        """문서 탐색 검색어 갱신 — 대상은 작업 표시 이름만(§18.6, 판정은 링1)."""
        self.browse_query = str(p.get("text", ""))

    def _clear_data_notice(self) -> None:
        self.data_notice_text = ""
        self.data_notice_level = ""

    # (_auto_aim_default(#53-A 기본 데이터셋 자동 조준)는 U2 §5.3 판정 D 로 삭제 —
    #  작업↔데이터 결속이 폐기돼 작업 선택이 데이터를 세우지 않는다. #347.)

    def _do_relink_template(self, p: dict) -> dict:
        """작업 템플릿 다시 연결(#67) — 공유 확정 게이트 위임 + 기선택 작업 재적재.

        커밋된 작업이 지금 패널에 선택돼 있으면 옛 경로의 VM 이 stale 이므로 ``_do_select_job``
        으로 재구성한다 — 데이터 겨눔·저장 폴더를 초기화하므로 결과 문구로 재진술(confirm-or-alarm).

        **진행 중 런과 겹치면 거절한다**(9R P1 형제): 템플릿 경로는 durable 규칙이고 진행 중
        배치는 옛 vm 을 고정해 뒀다 — 지금 갈아치우면 그 배치의 결과가 디스크에 없는 규칙을
        자기 근거로 댄다. 편집기 진입과 같은 부류라 같은 술어를 쓴다.
        """
        self.raise_if_generating("템플릿을 다시 연결하세요")
        res = relink_job_template(
            self.registry, p["name"], p.get("path", ""),
            engine=self._engine, confirm=bool(p.get("confirm")),
        )
        # 「지금 열어 둔 작업인가」는 **이름**으로 묻는다(1R P2) — `self.vm.job.name` 은 hwpx
        # 세션에서만 참이라 TXT 를 재연결하면 세션이 옛 템플릿을 그대로 그린다. 같은 질문에
        # 매체별 술어를 쓰면 그게 곧 구멍이다.
        if res.get("relinked") and self.job_name == p["name"]:
            self._invalidate_execution_evidence()
            self._do_select_job({"name": p["name"]})
            res["restated"] = (
                "템플릿을 다시 연결했습니다. 작업을 다시 불러왔으니 데이터와 저장 폴더 "
                "선택을 확인하세요."
            )
        elif res.get("relinked"):
            res["restated"] = "템플릿을 다시 연결했습니다."
        return res

    def _do_template_check(self, p: dict) -> dict:
        """[변경사항 확인](S3-09) — 현재 작업 템플릿 원본을 capture·검사해 종결 상태로 닫는다.

        요청 키(``request_id``)는 사용자 prepare intent 의 재전송 단위다 — 같은 키 재전송은
        같은 Preparation 을 돌려주고(중복 클릭), 새로 확인하려는 명시적 행동만 새 키를 만든다
        (웹 소유). work 식별·bootstrap·token 발급은 전부 코디네이터가 소유한다.
        """
        if self._template_change is None:
            raise ValueError("템플릿 변경 기능이 조립되지 않았습니다")
        if not self.job_name:
            raise ValueError("먼저 작업을 선택하세요")
        result, restored_job, application_id = (
            self._template_change.check_for_seated_context(
                self.job_name, str(p.get("request_id", ""))
            )
        )
        if result.get("reason") == "work_context_changed":
            self._release_changed_active_work("문서 작업이 변경되어")
            result["error"] = (
                "문서 작업이 변경되어 선택을 해제했습니다. "
                "문서 작업을 다시 선택하세요."
            )
            return result
        if (
            result.get("ok") is True
            and self.vm is not None
            and (
                not self.vm.job.authority_id
                or self._seated_template_application_id is None
            )
        ):
            if (
                restored_job is None
                or application_id is None
                or not self._can_adopt_seated_identity(self.vm.job, restored_job)
            ):
                self._release_changed_active_work("문서 작업이 변경되어")
                return {
                    "ok": False,
                    "reason": "work_context_changed",
                    "error": (
                        "문서 작업이 변경되어 선택을 해제했습니다. "
                        "문서 작업을 다시 선택하세요."
                    ),
                }
            self.vm.job.authority_id = restored_job.authority_id
            self._seated_template_application_id = application_id
        return result

    def _do_template_apply(self, p: dict) -> dict:
        """[변경사항 적용](S3-09) — opaque change token 하나로 원자 적용을 요청한다.

        진행 중 런과 겹치면 거절한다(재연결과 같은 부류) — 적용은 durable 권위 전환이고
        결과 재진술이 진행 중 배치와 섞이면 안 된다. cross-Work token·stale token 은
        코디네이터가 Work 무변경으로 거절한다.
        """
        if self._template_change is None:
            raise ValueError("템플릿 변경 기능이 조립되지 않았습니다")
        if not self.job_name:
            raise ValueError("먼저 작업을 선택하세요")
        self.raise_if_generating("템플릿 변경사항을 적용하세요")
        result, committed_application_id = (
            self._template_change.apply_for_seated_context(
                self.job_name, str(p.get("change_token", ""))
            )
        )
        if result.get("is_current") is True:
            self._seated_template_application_id = committed_application_id
            self._invalidate_execution_evidence()
            self._maybe_auto_check(effective_basis_changed=True)
        elif result.get("status") == "applied_then_advanced":
            self._release_changed_active_work("문서 작업에 다른 변경이 이어져")
        return result

    # ----------------------------------- 관리 동사(표면은 라이브러리, 소유는 이 컨트롤러)
    # 좌 목록이 죽어도(F2 PR-B) 아래 넷은 남는다: 열린 세션의 정체(``job_name``·VM)와 결속돼
    # 있어 여기가 계속 소유하고, 「문서 작업」 상세·그룹 헤더가 **교차 화면 dispatch** 로
    # 부른다(지도 §10.8 판정 F). 라이브러리에서 재구현하면 거기서 이름을 바꾼 순간 열린
    # 세션이 없는 이름을 가리킨다. 반면 세션과 무관한 복제·삭제·복원과 그룹 접힘은 표면과
    # 함께 걷혔다 — 라이브러리가 자기 채널에서 소유한다(판정 F 정정분).
    def _do_rename_job(self, p: dict) -> dict:
        """작업 이름 변경(인라인 편집 커밋) — 검증 실패는 ``{"ok": False, error}`` 재진술.

        열린 세션의 작업이면 세션 정체(``job_name``·VM)가 새 이름을 **추종**한다 — 이름
        변경은 비파괴(같은 작업)라 가드 없이 조용히 따라가되, 헤더가 즉시 새 이름을
        재진술하므로 변경이 보인다(전면 가시성).
        """
        name, new = p["name"], p.get("new", "")
        try:
            rename_job(self.registry, name, new)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        new_clean = new.strip()
        if self.job_name == name:
            self.job_name = new_clean
            if self.vm is not None:
                self.vm.job.name = new_clean
        # 직전 런의 주체도 **같은 전이에서** 추종한다(3R P2) — 안 따라가면 같은 작업의
        # 결과가 남의 것으로 판정돼 복구 행동이 사라지고 강등 문구가 거짓말을 한다.
        if self._last_run_job == name:
            self._last_run_job = new_clean
        # (템플릿 권위 identity 는 Job durable 필드(`authority_id`)라 개명을 저절로
        #  따라간다 — 여기서 옮길 인덱스가 없다, S3-09 리뷰 P1.)
        return {"ok": True}

    # (close_guard_reason 은 U2 §2.9(#344)에서 사망 — 창 닫기는 명시적 종료 선언이고 진행
    #  중 선택은 계약상 보존하지 않는다. 이 화면은 창 종료 가드에 참여하지 않으며, 그 배제는
    #  tests/test_webapp_bridge.py 의 `silent_loss_by_contract` 표에 **선언**돼 있다. 가드
    #  술어 `_guard_state` 의 나머지 두 소비자 — `session_guard_for`(홈 삭제 가드, #268)와
    #  `_do_guard_state`(데이터 재겨눔·재연결 사전 확인) — 는 그대로 산다.)

    def session_guard_for(self, name: str) -> "dict | None":
        """타 화면(홈) 삭제 가드 조회(#268 리뷰) — 이 화면이 ``name`` 에 무장 세션을 열어
        두었으면 가드 수치(+``screen``)를 돌려준다. 판정·수치는 :meth:`_guard_state` 단일
        출처를 재사용한다(문안이 실제 소실 집합과 어긋나지 않게)."""
        if name and name == self.job_name:
            g = self._guard_state()
            if g["armed"]:
                return {"screen": self.name, **g}
        return None

    def _do_cancel_generation(self, p: dict) -> dict:
        """진행 중인 문서를 완결한 뒤 다음 레코드부터 중단하도록 요청한다."""
        run = self._run
        if run is not None:
            run.request_cancel()
        return {"ok": True}

    def _do_select_failed(self, p: dict) -> dict:
        """「실패한 N건만 선택」 — 선택을 직전 런의 실패 레코드로 **교체**한다(§10.10 판정 F).

        **생성은 하지 않는다**: 의사표시 2클릭 분리(결정 28 「직전 필터 재적용」이 정의만
        복원하고 선택은 건드리지 않는 것과 같은 격 구분). 성공분 보존은 신설 기제가 아니라
        덮어쓰기 확인 왕복(RC-02)이 담보한다 — 재생성이 성공분을 겨누면 그 수치가 모달에
        선다. 별도의 재시도 동사(건별 재실행·filename override)는 **짓지 않는다**(지도 §10.14
        기각): 확정 실패 원인 4종(권한·점유·공간·경로)은 규칙이 아니라 환경이 원인이라 **이
        선택 + 「문서 만들기」** 가 곧 재시도이고, 저장 폴더를 바꾸면 「다른 폴더에서 재시도」다.

        목록이 비었으면(수명 경계를 지났거나 실패 없던 런) ``0`` 을 돌려 표면이 무동작을
        정직하게 말한다 — 아무 반응 없는 버튼은 결함으로 읽힌다(``_do_set_all`` 선례).

        범위 초안이 열려 있으면 **거절**한다(F3): 이 동사는 존 액션이 아니라 **커밋된 선택을
        직접 교체**하는 결과 구획의 행동이라, 초안 아래에서 커밋을 갈면 사용자가 보고 있는
        범위와 적용 대상이 조용히 갈린다. 표면상 모달에 가려 닿지 않지만 잠금은 상태가 진다.
        """
        if self.range_draft is not None:
            raise ValueError("범위 편집기를 닫은 뒤에 실패분을 선택할 수 있습니다.")
        idx = [i for i in self._last_failed if 0 <= i < len(self.records)]
        if not idx:
            return {"selected": 0}
        self.selection.set_none()
        for i in idx:
            self.selection.toggle(i, True)
        return {"selected": len(idx)}

    def _do_set_group(self, p: dict) -> None:
        """그룹 지정/해제(이동 다이얼로그 확정) — ``group=""`` 는 「그룹 없음」으로 이동.

        새 그룹 = 다이얼로그의 새 이름 입력이 이 액션으로 그대로 들어온다(소속=생성,
        빈 그룹 불가 불변식은 모델 구조가 담보).
        """
        assign_group(self.registry, p["name"], p.get("group", ""))

    def _drift_note(self, seen, count: int) -> str:
        """확인 시점 건수와 실제 이동 건수 어긋남 고지(#149) — 공용 job_list.drift_note 위임."""
        return drift_note(seen, count)

    # (접힘 영속 정리는 :func:`~hwpxfiller.external.settings.recollapse_job_group` 이
    #  소유한다 — P2-24: 읽기-수정-쓰기가 컨트롤러에 남으면 설정 영속의 제2 조립자가 된다.
    #  그룹을 개명·해산하는 동사는 여기가 소유하므로 호출도 여기서 한다.)

    def _do_rename_group(self, p: dict) -> dict:
        """그룹 이름 변경 — 새 이름이 **기존 그룹**이면 병합이므로 확인 승격(무확인 반환).

        순수 개명이면 접힘 상태를 새 이름으로 승계한다(이름만 바뀐 같은 그룹). 병합이면
        대상 그룹의 접힘 상태를 존중하고 옛 이름만 접힘 집합에서 걷는다.

        확인 문안의 건수는 **약속이 아니라 그 시점의 관측**이다(#149) — 실제 이동 건수는 잠금
        안 일괄 갱신이 세어 ``count`` 로 돌려주고, 확인 때 본 수(``seen``)와 다르면
        ``drift_note`` 로 함께 말한다.
        """
        old, new = p["name"], p.get("new", "").strip()
        if not new:
            return {"ok": False, "error": "그룹 이름이 비어 있습니다."}
        if new == old:
            return {"ok": True, "count": 0, "drift_note": ""}
        target_members = group_member_count(self.registry, new)
        if target_members and not p.get("confirm"):
            count = group_member_count(self.registry, old)
            return {"needs_confirm": True, "kind": "merge_group", "name": old,
                    "new": new, "count": count, "target_count": target_members}
        count = rename_group(self.registry, old, new)
        recollapse_job_group(old, new if not target_members else "")
        return {"ok": True, "count": count, "drift_note": self._drift_note(p.get("seen"), count)}

    def _do_disband_group(self, p: dict) -> dict:
        """그룹 해산(결정 43) — 무확인 호출은 소속 수 재진술로 멈춘다. 소속은 「그룹 없음」으로.

        재진술한 수는 그 시점의 관측이다 — 실제 이동 건수·어긋남 고지는 ``_drift_note``(#149).
        """
        name = p["name"]
        if not p.get("confirm"):
            count = group_member_count(self.registry, name)
            return {"needs_confirm": True, "name": name, "count": count}
        count = disband_group(self.registry, name)
        recollapse_job_group(name, "")
        return {"ok": True, "count": count, "drift_note": self._drift_note(p.get("seen"), count)}

    # (행 선택 4액션·필터 12액션·직전 필터 슬롯·소스 키는 DataZoneMixin 으로 이동 —
    #  슬라이스 6 PR-2b: txt 큐가 같은 존을 재사용한다. data_zone.py 가 정본.)

    def _records(self) -> list:
        return self.records  # 세션 소유(데이터-우선) — vm 은 주입 소비자일 뿐

    def _init_filter(self) -> None:
        """데이터 겨눔 시 필터 신설(결정 24) — 설치는 믹스인, 힌트(매핑 확정 유형)는 화면 몫.

        작업 미선택 마운트(데이터-우선)에선 힌트 없이 값 스니핑만 쓴다 — 작업을 나중에
        선택해도 필터는 데이터 스코프라 재생성하지 않는다(§18.10: 필터는 가시성만).
        """
        hints = {
            m.source: m.type
            for m in (self.vm.job.mapping.mappings if self.vm is not None else [])
            if m.source and m.type in (KIND_TEXT, KIND_DATE, KIND_AMOUNT)
        }
        self._install_filter(self.records, hints)
        self._last_generated = None  # 완주 집합의 인덱스는 이전 데이터 좌표 — 교체 시 무효
        self._discard_delivered_artifacts()  # 배달 좌표도 이전 데이터의 것이다(S7-03)
        self._do_preview_close({})   # 미리보던 값은 이전 스냅샷의 것이다(F5)

    # (_do_ack_field·_do_unack_field 는 필드축 ack 폐기와 함께 사망 — U2 §2.13.
    #  표식 삽입 동의는 확인 면의 승인(preview_approve — blank_set 위험종)이 겸한다.)

    # -------------------------- 등록 데이터(풀) 겨눔(#26/#6) — 공용 래퍼(K4)의 화면별 훅
    def _pool_loader(self):
        """세션 소유 풀 로더(데이터-우선) — 작업 미선택에도 겨눌 수 있다."""
        return self._load_pool_records

    def _load_pool_records(self, item) -> list:
        """풀 항목 → 세션 마운트. 0건이면 상태 불변(공용 관문이 문구 재진술).

        링1 리졸버(:func:`~hwpxfiller.gui.run_state.resolve_pool_source`)를 직접 소비한다 —
        vm 경유(``load_pool_item``)는 작업 선택을 전제해 데이터-우선과 어긋난다. vm 이
        있으면 같은 데이터를 ``set_acquired`` 로 주입(데이터 귀속 원자 진입점, RC-22).
        """
        self.raise_if_generating_before_swap("데이터를 바꾸세요")  # #302 P1 동류
        source, records = resolve_pool_source(
            item, source_factory=self._pool_source_factory
        )
        if not records:
            return []
        self._commit_data_transition(source, records)
        return records

    def _after_pool_load(self, records: list) -> None:
        """풀 겨눔도 파일과 동일하게 새 데이터 = 선택 0건(§18.2)·ack·필터 초기화를 탄다."""
        self._stash_filter()  # 죽는 세션의 정의 → 슬롯(옛 소스 키 기준 — 키 갱신 전에)
        self._last_failed = []  # 파일 마운트와 같은 수명(§10.10 판정 F)
        self._data_key = self._pool_key()  # 라벨은 믹스인/자동 조준이 이미 세팅
        self._reset_range_for_snapshot(len(records))  # 선택 0건 + 표시순서 기본(§18.2·F3)
        self._init_filter()  # 데이터 교체 = 필터 재생성(결정 24)

    # ------------------------------------------------------------------ 생성
    def _push_progress(self, done: int, total: int) -> None:
        """생성 진행 델타 — 전체 스냅샷 재계산(템플릿 재파싱) 없이 진행바만 갱신.

        ``run_token`` 을 함께 싣는다(R4-03): 진행 델타는 direct 반환과 **다른 채널**이라
        어느 실행의 것인지가 payload 밖에 없었다. 표면이 "지금 진행 중인 실행"이라고
        가정하면 새 실행이 시작된 뒤 도착한 앞선 런의 델타가 새 진행바를 뒤로 돌린다 —
        토큰 대조가 그 창을 닫는다. 값은 이 컨트롤러가 만들지 않고 되돌리기만 한다.
        """
        run = self._run
        self._push_sink(self.name, {
            "progress": {
                "done": done, "total": total,
                "run_token": run.token if run is not None else "",
            },
        })

    def generate(self, *, confirm_overwrite: bool = False, run_token: str = "") -> dict:
        """게이트 통과 시 동기 생성 → 결과 dict. 덮어쓰기는 웹 재진술 후 재호출(RC-02).

        슬라이스 1은 실행 화면과 동일한 링1 계약을 배선한다 — 게이트 판정·덮어쓰기 재진술의
        표현(재진술 블록·modal.js)은 슬라이스 2(블록 6)가 광택한다.

        ``run_token`` 은 표면이 낸 불투명 상관 문자열이고 **모든** 반환 갈래에 되돌아간다
        (거절·덮어쓰기 필요·취소·성공·실패). 되돌림을 갈래마다 손으로 적지 않고 이 함수의
        단일 출구가 찍는 이유는 갈래가 늘 때 형제를 빠뜨리는 결함류를 구조로 막기 위해서다.
        생략하면 ``""`` 라 종전 호출자의 동작은 그대로다.
        """
        # 토큰은 **이 호출의 지역값**이다. 공유 필드에 먼저 실으면 자물쇠에 거절당할 두 번째
        # 호출이 **이긴 런의 이름표를 갈아치운다** — 그러면 실제로 도는 런의 진행 델타와 최종
        # 응답이 남의 토큰을 달고 나가 표면이 그것을 「남의 것」으로 폐기한다(문서는 만들어졌는데
        # 사용자는 「이미 생성 중」만 본다). 되돌림은 이 지역값이 지고, 공유 필드는 자물쇠를
        # 쥔 런만 세운다.
        token = run_token if isinstance(run_token, str) else ""
        result = self._generate_with_token(confirm_overwrite=confirm_overwrite, run_token=token)
        # 되돌림은 마지막 한 자리다. 판정에 쓰지 않으므로 값이 무엇이든 그대로 싣는다.
        result["run_token"] = token
        return result

    def _generate_with_token(self, *, confirm_overwrite: bool = False, run_token: str = "") -> dict:
        """``generate`` 의 판정 본체 — 토큰은 진행 델타의 이름표로만 쓴다."""
        if self.vm is None:
            return {"ok": False, "error": "먼저 작업을 선택하세요.", "level": "warn"}
        job = self.vm.job
        # S6-05(#812): S6-absent \uac00\ub4dc(authority_id \ub2e8\ub3c5 \ud544\ud130)\ub294 \ucca0\uac70\ub410\ub2e4 \u2014 \uc2e4\ud589 \uacbd\ub85c \uc120\ud0dd
        # (\uc758\ubbf8 4)\uc740 \uc544\ub798\uc5d0\uc11c managed_hwpx \ud30c\uc0dd\uacfc \uac19\uc740 \uc6d0\ucc9c\uc73c\ub85c \uac08\ub9ac\uace0, managed \uac08\ub798\uc758
        # \uc2dc\uc791 \uc790\uaca9\uc740 start gate \uac00, slot-bearing \uc758 legacy \uc720\uc785\uc740 admission \uc774 \uac01\uc790 \uc18c\uc720\ud55c
        # \uc0ac\uc720\ub85c \ub2eb\ub294\ub2e4(#806 R1\u00b7R2 \uac00 \ub51b\ub294 \uc0ac\uc2e4).

        if self.range_draft is not None:
            # 초안이 열린 채 생성하면 사용자가 보고 있는 범위(초안)와 만들어지는 범위(커밋)가
            # 다르다 — 표면상 모달에 막혀 있지만 잠금은 DOM 이 아니라 상태가 진다(§10.11.2
            # 계약면 2). 거절 문안이 다음 행동(적용 또는 취소)을 지목한다.
            return {
                "ok": False, "level": "warn",
                "error": "범위 편집기가 열려 있습니다. 변경을 적용하거나 취소한 뒤 생성하세요.",
            }
        if not self._generation_lock.acquire(blocking=False):
            return {"ok": False, "error": "이미 문서를 생성하고 있습니다.", "level": "warn"}
        # 이 런의 주체를 **자물쇠를 쥔 직후에 붙들고 이후 라이브 세션을 다시 읽지 않는다**
        # (#302 P1): 생성 중 작업 전환이 self.vm 을 갈아끼우면 검증·계획이 남의 작업으로
        # 새고, 완주 뒤 현재 상태를 읽으면 남의 작업에 역사를 적는다. 주체·판본·규칙 지문·
        # cancel Event·상관 토큰의 정본은 Application run 객체다(P2-23) — 진행 델타의
        # 이름표는 자물쇠를 쥔 런만 세우고, 끝나면 핸들을 비운다(남은 이름표는 어떤 런도
        # 겨누지 않는다).
        run_vm = self.vm
        run = start_run(
            getattr(run_vm, "job", None), job_name=self.job_name, token=run_token
        )
        self._run = run
        visible_identity_before = (
            self.vm,
            getattr(getattr(self.vm, "job", None), "authority_id", None),
            self._seated_template_application_id,
            self.job_name,
        )
        try:
            try:
                if self._is_managed_hwpx_work(job):
                    # managed 갈래(S6-05) — legacy staging·admission 을 타지 않는다. 준비
                    # 미달·stale·runtime 은 파이프라인 안의 소유자들이 각자 사유로 닫는다.
                    visible_identity_changed = False
                    result = self._generate_managed_locked(run, run_vm)
                else:
                    reject = self._resolve_managed_template(run_vm)
                    visible_identity_changed = (
                        self.vm,
                        getattr(getattr(self.vm, "job", None), "authority_id", None),
                        self._seated_template_application_id,
                        self.job_name,
                    ) != visible_identity_before
                    result = (
                        reject
                        if reject is not None
                        else self._generate_locked(
                            run, run_vm, confirm_overwrite=confirm_overwrite
                        )
                    )
            finally:
                self._run = None
                # staged 경로는 이 런에서만 유효하다 — VM 포인터를 비우고, 실행이 끝나 아무도
                # 참조하지 않는 staging 사본을 Host lifecycle 로 정리한다(#681, 판본별 영구 누적 방지).
                managed = (
                    run_vm is not None
                    and getattr(run_vm, "_managed_template", None) is not None
                )
                if run_vm is not None:
                    run_vm._managed_template = None
                if managed and self._template_change is not None:
                    self._template_change.clear_generation_staging()
                self._generation_lock.release()
        except Exception:
            if (
                self.vm,
                getattr(getattr(self.vm, "job", None), "authority_id", None),
                self._seated_template_application_id,
                self.job_name,
            ) != visible_identity_before:
                self._push()
            raise
        # 런이 남긴 세션 변화(직전 런 주체·완주 스탬프)를 표면에 흘린다(3R P2) — `generate`
        # 는 dispatch 밖이라 자동 push 가 없어, 표면은 **런 이전 스냅샷**으로 결과 행동을
        # 판정하고 있었다. 덮어쓰기 확인 왕복(`needs_overwrite`)에는 밀지 않는다: 모달이
        # 열린 동안의 재렌더는 dispatch 의 무변이 push 생략과 같은 이유로 낭비다.
        if result.get("ok"):
            # 생성이 그 시각을 **소비했다** — 핀을 놓는다(5R P2). 안 놓으면 같은 입력으로
            # 한 번 더 만들 때 지난 런의 시각이 그대로 재사용돼 날짜 토큰이 늙는다.
            self._names_pin = None
            self._push()
        elif visible_identity_changed:
            self._push()
        return result

    def _generate_managed_locked(self, run, run_vm) -> dict:
        """managed HWPX 실행(S6-05 · #812) — legacy generator 를 부르지 않는다(S6-9).

        판정 재조립 0(S6-10): 준비 판정은 workbench observation 이, payload↔digest 짝은
        같은 seal 응답 출처가, 시작 자격은 start gate 가, 안착은 delivery coordinator 가
        소유한다. 거절 문안은 observation 의 disabled_reason 재진술이다(구 가드와 같은
        원천, 다른 자리). 취소는 record 경계에서만 읽고 write 0 이다(legacy 의 부분 유지와
        다름을 요약이 말한다).
        """
        self._last_run_job = run.job_name
        self._run_revisions = dict(run.revisions)
        try:
            observation = self.workbench_observation()
        except ValueError:
            return {
                "ok": False,
                "error": "현재 환경에서는 문서를 만들 수 없습니다",
                "level": "warn",
            }
        if not observation.create_documents_enabled:
            return {
                "ok": False,
                "error": observation.create_documents_disabled_reason
                or "필요한 준비를 먼저 완료해 주세요",
                "level": "warn",
            }
        payload = self._last_sealed_plan_payload
        if payload is None or (
            execution_basis_digest(payload.execution_basis)
            != self._last_sealed_basis_digest
        ):
            return {
                "ok": False,
                "error": "실행 준비가 현재 확인 상태와 달라 생성하지 않았습니다. "
                "변경사항을 다시 확인해 주세요.",
                "level": "warn",
            }
        prep = self._current_delivery_preparation
        if prep is None or not isinstance(prep.result, CurrentResolvedDelivery):
            return {
                "ok": False,
                "error": "필요한 준비를 먼저 완료해 주세요",
                "level": "warn",
            }
        context = (
            self._seal_execution.managed_run_context(self.job_name)
            if self._seal_execution is not None
            else None
        )
        if context is None:
            return {
                "ok": False,
                "error": "현재 환경에서는 문서를 만들 수 없습니다",
                "level": "warn",
            }
        now = self._clock().isoformat(timespec="seconds")
        outcome = run_managed_generation(
            root=context.root,
            workspace_instance_id=context.workspace_instance_id,
            work_authority_id=context.work_authority_id,
            plan_payload=payload,
            ordered_raw_snapshots=prep.record_preparation.raw_records,
            resolved_delivery=prep.result,
            validated_at=now,
            runtime_registry=context.runtime_registry,
            runtime_capability_manifest_digest=(
                context.runtime_capability_manifest_digest
            ),
            current_basis_digest_reader=context.current_basis_digest_reader,
            cancel_requested=run.cancel.is_set,
        )
        return self._managed_result_dict(outcome, prep, payload, context, now)

    def _managed_result_dict(self, outcome, prep, payload, context, now: str) -> dict:
        """managed 실행 결과 → legacy 와 같은 키 집합의 결과 dict(JobResultZone 무변경)."""
        indices = list(prep.record_preparation.ordered_model_indices)
        total = len(indices)
        if isinstance(outcome, (ManagedRunRefused, DeliveryRefused)):
            return {"ok": False, "error": outcome.detail, "level": "warn"}
        if isinstance(outcome, ManagedRunCancelled):
            summary = (
                f"중단했습니다. 시도 {outcome.attempted}/{outcome.total}건 — 안착 전이라 "
                "문서는 만들지 않았습니다."
            )
            return {
                "ok": True, "status": "cancelled",
                "title": _run_title("cancelled", True, 0, 0),
                "exit_summary": _run_exit_summary(
                    "cancelled", True, 0, 0,
                    outcome.total - outcome.attempted, outcome.attempted, outcome.total,
                ),
                "stage": "", "message": "", "known": True, "summary": summary,
                "level": "warn", "out_dir": prep.result.output_directory,
                "succeeded": 0, "failed": 0, "failed_selectable": 0,
                "total": outcome.total, "failures": [], "fill_notes": [],
                "cancelled": True, "attempted": outcome.attempted,
                "unstarted": outcome.total - outcome.attempted,
                "revisions": dict(self._run_revisions),
            }
        # DeliveryCompleted | ManagedReadBackFailed | DeliveryAborted — 앉은 문서까지는
        # 유효하다(되읽기 실패도 안착 사실을 부정하지 않는다 — S7-01 · #823).
        delivered = list(outcome.delivered)
        succeeded = len(delivered)
        # 세션이 앉힌 문서 좌표를 여기서 세운다(S7-03 · #825) — 되읽기 실패·중단 갈래도
        # **앉은 것까지는** 유효하므로 같은 자리에서 실린다. 결과 dict 의 목록은 그
        # 좌표의 투영이고 bytes 는 어느 쪽도 들지 않는다(#820 D1·D2).
        self._last_delivered = tuple(delivered)
        self._artifact_view = None  # 새 실행 = 열려 있던 관찰은 앞선 실행의 것이다
        delivered_rows = [
            {
                "ordinal": doc.item_ordinal,
                "filename": doc.relative_path,
                "disposition": doc.collision_disposition,
                "path": doc.absolute_path,
            }
            for doc in delivered
        ]
        fill_notes = [
            describe_fill_note(note)
            for note in dict.fromkeys(
                note for doc in delivered for note in doc.execution_notes
            )
        ]
        ledger_note = ""
        try:
            write_managed_delivery_ledger(
                prep.result.output_directory,
                generated_at=now,
                work_authority_id=context.work_authority_id,
                execution_basis_digest=self._last_sealed_basis_digest or "",
                plan_semantic_digest=plan_semantic_digest(payload),
                result=outcome,
            )
        except OSError as exc:
            # 기록 실패의 loud surface — 문서는 이미 앉았으므로 요약에 병기한다.
            ledger_note = f" 문서는 만들어졌지만 실행 기록 저장에 실패했습니다({exc})."
        if isinstance(outcome, DeliveryCompleted):
            self._last_generated = set(indices)
            self._last_failed = []
            self._last_managed_outcome = HistoricalOutcomeSummary(
                "DOCUMENTS_DELIVERED", now
            )
            summary = f"완료. 성공 {succeeded}/{total}, 실패 0."
            if fill_notes:
                summary += f" 채움 주의 {len(fill_notes)}건(아래 기록 확인)."
            summary += ledger_note
            return {
                "ok": True, "status": "completed",
                "title": _run_title("completed", False, succeeded, 0),
                "exit_summary": _run_exit_summary(
                    "completed", False, succeeded, 0, 0, total, total
                ),
                "stage": "", "message": "", "known": True, "summary": summary,
                "level": "ok" if not ledger_note else "danger",
                "out_dir": outcome.output_directory,
                "succeeded": succeeded, "failed": 0, "failed_selectable": 0,
                "total": total, "failures": [], "fill_notes": fill_notes,
                "cancelled": False, "attempted": total, "unstarted": 0,
                "revisions": dict(self._run_revisions),
                "delivered": delivered_rows,
            }
        if isinstance(outcome, ManagedReadBackFailed):
            # 안착은 전건 됐고, 그중 하나를 되읽어 확인하는 데 실패했다(#818 회수) — 실패
            # 항목도 disk 에 있으므로 미착수는 0 이고 성공 수에서만 빠진다.
            succeeded -= 1
            failed_index, failure = self._managed_failure_row(
                prep, indices, outcome.failed_item_ordinal, outcome.detail
            )
            self._last_failed = [failed_index]
            status = "partiallyCompleted" if succeeded else "failed"
            summary = (
                f"완료. 성공 {succeeded}/{total}, 실패 1. 문서는 만들었지만 만든 뒤 다시 "
                f"읽어 확인하는 데 실패했습니다({outcome.code}). 해당 파일을 직접 열어 "
                "내용을 확인하세요."
            ) + ledger_note
            return {
                "ok": True, "status": status,
                "title": _run_title(status, False, succeeded, 1),
                "exit_summary": _run_exit_summary(
                    status, False, succeeded, 1, 0, total, total
                ),
                "stage": "", "message": "", "known": True, "summary": summary,
                "level": "danger", "out_dir": prep.result.output_directory,
                "succeeded": succeeded, "failed": 1,
                "failed_selectable": len(self._last_failed),
                "total": total, "failures": [failure], "fill_notes": fill_notes,
                "cancelled": False, "attempted": total, "unstarted": 0,
                "revisions": dict(self._run_revisions),
                "delivered": delivered_rows,
            }
        # DeliveryAborted — 실패 항목에서 멈췄다(항목별 원자, 사실 그대로 표면화).
        failed_index, failure = self._managed_failure_row(
            prep, indices, outcome.failed_item_ordinal, outcome.detail
        )
        failures = [failure]
        self._last_failed = [failed_index]
        unstarted = total - succeeded - 1
        status = "partiallyCompleted" if succeeded else "failed"
        summary = (
            f"완료. 성공 {succeeded}/{total}, 실패 1. 미착수 {unstarted}건 — "
            "앉은 문서는 그대로 유지됩니다."
        ) + ledger_note
        return {
            "ok": True, "status": status,
            "title": _run_title(status, False, succeeded, 1),
            "exit_summary": _run_exit_summary(
                status, False, succeeded, 1, unstarted, succeeded + 1, total
            ),
            "stage": "", "message": "", "known": True, "summary": summary,
            "level": "danger", "out_dir": prep.result.output_directory,
            "succeeded": succeeded, "failed": 1,
            "failed_selectable": len(self._last_failed),
            "total": total, "failures": failures, "fill_notes": fill_notes,
            "cancelled": False, "attempted": succeeded + 1, "unstarted": unstarted,
            "revisions": dict(self._run_revisions),
            "delivered": delivered_rows,
        }

    def _managed_failure_row(
        self, prep, indices, failed_ordinal: int, reason: str
    ) -> "tuple[int, dict]":
        """managed 실패 항목 하나 → legacy 실패 행(안착 중단·되읽기 실패가 같은 투영을 쓴다).

        identity 는 legacy 와 같은 링1 표시명(§10.10 판정 E) — 내부 locator 를 노출하지 않는다.
        """
        failed_index = (
            indices[failed_ordinal] if failed_ordinal < len(indices) else failed_ordinal
        )
        failed_item = prep.result.ordered_items[failed_ordinal]
        isum = identity_summary(
            self.records, filename_tokens=self._filename_source_columns()
        )
        return failed_index, {
            "index": failed_index,
            "identity": (
                isum.display_for(self.records[failed_index])
                if 0 <= failed_index < len(self.records) else ""
            ),
            "filename": failed_item.resolved_output_relative_path,
            "reason": reason,
            "known": True,
        }

    def _resolve_managed_template(self, run_vm) -> "dict | None":
        """managed Product Work(HWPX 새 문서) 생성이 겨눌 템플릿을 current Application 의
        exact applied bytes(staged)로 고정한다(#681 G11) — mutable ``job.template_path`` 직독을
        managed 경로에서 없앤다. 이어채우기(이전 출력)·txt·코디네이터 부재는 해당 없음.
        admission 차단은 fallback 없이 시끄러운 거절 dict 로 돌려준다(confirm-or-alarm).
        반환 ``None`` = managed 해당 없음 또는 통과(``run_vm._managed_template`` 설정됨).
        """
        if (
            self._template_change is None
            or getattr(run_vm, "template_override", None) is not None  # 이어채우기=이전 출력
            or getattr(getattr(run_vm, "job", None), "media", "") != "hwpx"
        ):
            return None

        def synchronize_seated_identity(restored_job: Job, application_id: str) -> None:
            if self.vm is run_vm and (
                not run_vm.job.authority_id
                or self._seated_template_application_id is None
            ):
                if not self._can_adopt_seated_identity(run_vm.job, restored_job):
                    self._release_changed_active_work("문서 작업이 변경되어")
                    raise TemplateChangeError(
                        "문서 작업이 변경되어 선택을 해제했습니다. "
                        "문서 작업을 다시 선택하세요."
                    )
                run_vm.job.authority_id = restored_job.authority_id
                self._seated_template_application_id = application_id

        try:
            run_vm._managed_template = (
                self._template_change.resolve_generation_template_for_seated_context(
                    self.job_name, on_context=synchronize_seated_identity
                )
            )
        except (SlotlessRunAdmissionError, TemplateChangeError) as exc:
            if isinstance(exc, SlotlessRunAdmissionError):
                return {
                    "ok": False, "level": "warn",
                    "error": _ADMISSION_REJECT_TEXT.get(
                        exc.code, "생성을 진행할 수 없습니다."
                    ),
                }
            return {"ok": False, "level": "warn", "error": str(exc)}
        return None

    def _generate_locked(self, run, run_vm, *, confirm_overwrite: bool = False) -> dict:
        """단일 생성 실행의 링2 결선 — 판정·척추는 Application use case 가 소유한다(P2-23).

        ``run`` 은 :func:`~hwpxfiller.application.generation.start_run` 이 시작 시점에
        고정한 주체·판본·규칙 지문의 정본, ``run_vm`` 은 같은 시점에 붙든 실행뷰다 —
        이후 라이브 세션(self.vm)을 판정 입력으로 다시 읽지 않는다(#302 P1). 여기 남는
        것은 게이트 선언(검토 판정기·확정 여부)과 facts→payload/문안 투영뿐이다.
        """
        self._last_run_job = run.job_name   # 결과 행동의 주체(3R P2) — 세션 상태가 소유
        self._run_revisions = dict(run.revisions)  # §13-7 시작 시점 고정(F7 판정 I)
        indices = self._indices()
        out_dir = self.out_dir

        # 게이트 판정 순서(①가드 ②빈 값 ③검토 백스톱 ④표식 ⑤덮어쓰기 ⑥불변 계획)는
        # Application 이 소유한다. 검토 판정기는 **이 런의 주체**(run_vm·indices·그 입력의
        # 빈 값)로 묻는 게이트 선언이다 — 세션은 배치가 도는 사이에도 움직인다(1R P1).
        # 날짜 토큰 시각은 미리보기가 캡처한 값을 재사용한다(표시=확인=생성 일치, RC-02).
        now = self._names_now or self._clock()
        decision = plan_generation(
            run_vm, indices, out_dir, now=now,
            review_check=lambda bl: self._review(run_vm, indices, bl)[1],
            confirm_overwrite=confirm_overwrite,
            existing_outputs=self._existing_outputs,
        )
        if decision.rejection is not None:
            return {
                "ok": False,
                "error": decision.rejection.message,
                "level": decision.rejection.level,
            }
        if decision.review_unmet is not None:
            return {
                "ok": False, "level": "warn",
                "error": review_gate_text(decision.review_unmet),
            }
        blanks = list(decision.blanks)
        if decision.needs_overwrite:
            # 수치 합성(결정 36): 총량·파괴분(덮어씀)·신규분을 종류별로 재진술한다.
            # 표면(job.js)이 이 수치로 modal.js 본문을 합성한다 — 문안은 웹 소유(RC-02).
            names = [Path(p).name for p in decision.conflicts]
            return {
                "ok": False, "needs_overwrite": True,
                "total": len(indices),                      # 총량
                "overwrite_count": len(names),              # 파괴분(기존 덮어씀)
                "new_count": len(indices) - len(names),     # 신규분(새 파일)
                "conflict_names": names[:10],               # 파괴분 표본
                "conflict_more": max(0, len(names) - 10),
            }
        plan = decision.plan
        assert plan is not None  # PlanDecision 4태의 잔여 갈래 — 위 세 갈래가 소진했다

        # materialize → 완주 판정 → durable 기록 요청 → facts (Application 척추).
        # 엔진(zip IO)은 Host 가 조립해 여기로 관통시키고, 완주 기록은 use case 가
        # `application.jobs.stamp_run_completion` 으로 요청한다(controller 직접 쓰기 0).
        outcome = run_generation(
            run, plan,
            engine=self._engine,
            progress=self._push_progress,
            capture=(ValueError, OSError),
            store=self.registry,
            completed_at=lambda: self._clock().isoformat(timespec="seconds"),
            existing_outputs=self._existing_outputs,
            ensure_output_dir=self._ensure_output_dir,
        )
        if outcome.error is not None:
            # 배치가 **시작조차 못 한** 실패(구조 드리프트·산출물 충돌·폴더 오류) —
            # 지도 §10.10 판정 C. 결과 구획으로 회수한다(브리지 rejection 으로 새지 않게).
            self._last_failed = list(indices)
            return self._failed_result(
                indices, plan.out_dir,
                str(outcome.error) or outcome.error.__class__.__name__,
            )

        # 완료 이벤트 = 가드 무장 해제(결정 27) — **완주**(전건 성공)만이다(고효율 리뷰
        # #1). 완주 술어는 스탬프와 한 곳(:func:`run_completed`)을 공유한다(#129) —
        # 둘로 갈라지면 홈 이력과 가드가 서로 다른 실행을 완료로 부른다.
        if outcome.completed:
            self._last_generated = set(indices)
        # 인메모리 사본은 **그 런의 VM 이 아직 현 세션일 때만** 동기화한다(디스크와
        # 갈라지지 않게) — 세션이 다른 작업으로 옮겨갔으면 남의 VM 을 만지지 않는다.
        # 검토 기준선도 같이 되싣는다(F5 판정 B): 스탬프가 디스크에만 남으면 세션은
        # 방금 완주한 규칙을 여전히 「미검토」로 읽는다.
        if outcome.stamped_job is not None and run_vm is self.vm:
            if rules_fingerprints(outcome.stamped_job) != run.rules:
                self._last_generated = None
                self._do_preview_close({})
            run_vm.job = outcome.stamped_job

        cancelled = outcome.cancelled
        if cancelled:
            summary = (
                f"중단했습니다. 완료 {outcome.attempted}/{outcome.total}건"
                f"(성공 {outcome.succeeded}, 실패 {outcome.failed}), "
                f"미착수 {outcome.unstarted}건. 완료된 문서는 그대로 유지됩니다."
            )
        else:
            summary = (
                f"완료. 성공 {outcome.succeeded}/{outcome.total}, 실패 {outcome.failed}."
            )
        if blanks:
            summary += f" 빈 값 표시 필드 {len(blanks)}개({', '.join(blanks)})."
        if outcome.stamp_error:
            # 기록 실패의 loud surface(confirm-or-alarm) — 문서는 이미 만들어졌으므로
            # 완료 서사를 날리지 않고 사유를 완료 요약에 병기한다.
            summary += (
                " 문서는 모두 만들어졌지만 실행 기록 저장에 실패했습니다"
                f"({outcome.stamp_error})."
            )
        # 실패 항목은 **구조화**해 넘긴다(§10.10 판정 E) — 파일명만으로 부르면 "어느
        # 행인가"를 사용자가 표에서 되찾아야 한다. 원본 index 는 「실패한 N건만 선택」의
        # 입력이기도 하다(판정 F). ``outcome.results`` 는 ``plan.records`` 와 같은 순서이고
        # 그 순서는 ``indices`` 다(build_generation_plan 이 같은 리스트로 짓는다).
        failures = self._failure_rows(indices, list(outcome.results))
        self._last_failed = [f["index"] for f in failures]
        # 채움 완화 사실(#154)은 완료 표면에 시끄럽게 — 파괴적 의미론(인라인 요소
        # 제거·값 런 합성)이 무경고면 조용한 데이터 손실이다(confirm-or-alarm).
        # 템플릿 구조 속성이라 레코드 수와 무관하게 한 번씩(순서 보존 dedupe).
        fill_notes = [
            describe_fill_note(n)
            for n in dict.fromkeys(
                n for r in outcome.results if r.ok for n in r.notes
            )
        ]
        if fill_notes:
            summary += f" 채움 주의 {len(fill_notes)}건(아래 기록 확인)."
        return {
            "ok": True,
            "status": outcome.status,
            "title": _run_title(
                outcome.status, cancelled, outcome.succeeded, outcome.failed
            ),
            # 퇴장 요약(§2.18) — 결과가 물러난 뒤 남는 유일한 흔적이라 **수치를 하나도
            # 흘리지 않는다**. 제목과 목적이 달라 합성기가 따로다(둘 다 Python 소유).
            "exit_summary": _run_exit_summary(
                outcome.status, cancelled, outcome.succeeded, outcome.failed,
                outcome.unstarted, outcome.attempted, outcome.total,
            ),
            # 실패 단계·받은 메시지는 배치 진입 전 실패(_failed_result)의 자리다 —
            # 레코드 단위 실패는 각 행이 자기 사유를 진다. 모양은 한 벌로 유지한다.
            "stage": "",
            "message": "",
            "known": True,
            "summary": summary,
            "level": (
                "warn" if cancelled
                else (
                    "ok" if outcome.failed == 0 and not outcome.stamp_error
                    else "danger"
                )
            ),
            "out_dir": plan.out_dir,
            "succeeded": outcome.succeeded,
            "failed": outcome.failed,
            # 「실패한 N건만 선택」의 노출·라벨은 **이 수치**가 정한다(1R P2): 실패 행
            # 목록에서 파생하면, 행 없이 전량이 실패하는 런(배치 진입 전 실패)에서 복구
            # 행동이 통째로 숨는다 — 뒤에 선택을 바꾸면 대상 집합을 되찾을 길이 없다.
            # index 를 Python 이 소유하기로 한 이상(판정 F) 그 개수도 Python 이 낸다.
            "failed_selectable": len(self._last_failed),
            "total": outcome.total,
            "failures": failures,
            "fill_notes": fill_notes,
            "cancelled": cancelled,
            "attempted": outcome.attempted,
            "unstarted": outcome.unstarted,
            "revisions": dict(self._run_revisions),
        }

    def _failure_rows(self, indices: "list[int]", results: list) -> "list[dict]":
        """실패 레코드 = 원본 index + 식별 요약 + 실파일명 + 사유(+원인 확정 여부).

        식별 요약은 링1 단일 함수(:func:`~hwpxfiller.domain.identity_summary.identity_summary`,
        결정 37)를 재사용한다 — 표 「문서」 열과 **같은 판정**이라 사용자가 결과에서 본
        이름으로 표에서 그 행을 찾는다(§10.10 판정 E: 어느 열로 부를지 재구현 금지).
        ``results`` 는 취소 런에서 ``indices`` 보다 짧다 — zip 이 짧은 쪽에서 멈추는 것이
        곧 "시도한 것만 결과가 있다"는 뜻이다(미착수는 실패가 아니다).
        """
        # strict=False 는 의도다(위 문단) — 취소 런의 짧은 results 가 정상 입력이다.
        pairs = [(i, r) for i, r in zip(indices, results, strict=False) if not r.ok]
        if not pairs:
            return []
        isum = identity_summary(
            self.records, filename_tokens=self._filename_source_columns()
        )
        rows = []
        for i, res in pairs:
            reason, known = classify_result_error(res.error)
            rows.append({
                "index": i,
                "identity": (
                    isum.display_for(self.records[i])
                    if 0 <= i < len(self.records) else ""
                ),
                "filename": Path(res.output_path).name,
                "reason": reason,
                "known": known,
            })
        return rows

    def _failed_result(self, indices: "list[int]", out_dir: str, message: str) -> dict:
        """배치 진입 전 실패 → ``failed`` 태 결과(§10.10 판정 C).

        계약 §10.3 이 요구하는 것을 그대로 싣는다: **실패 단계·영향 레코드·받은 메시지**
        와 원인 확정 여부. 원인을 꾸며내지 않으므로 아는 패턴이 없으면 ``known=False`` 로
        표면이 「원인 진단 미연결」을 세운다. ``ok=True`` 인 이유: 이것은 게이트 거절
        (실행하지 않음)이 아니라 **실행하다 실패**라서 결과 구획의 소관이다.

        ``failures`` 는 비어 있다 — 레코드별 시도가 없었으므로 행별 사유를 지어내지
        않는다. 영향 레코드는 수치(``failed``·``failed_selectable``)와 복구 행동으로
        나른다: 행이 없다고 「실패한 N건만 선택」까지 숨으면 전량 실패에서 대상 집합을
        되찾을 길이 사라진다(1R P2).
        """
        reason, known = classify_result_error(message)
        n = len(indices)
        return {
            "ok": True,
            "status": "failed",
            "title": _run_title("failed", False, 0, n),
            # 시도가 0 이라 성공/실패로 가르지 않는다 — 이 페이로드는 같은 레코드를
            # `failed` 와 `unstarted` 에 동시에 세므로 이어 붙이면 같은 건을 두 번 말한다.
            "exit_summary": _run_exit_summary("failed", False, 0, n, n, 0, n),
            "summary": f"문서를 만들지 못했습니다. 대상 {n}건이 모두 생성되지 않았습니다.",
            "level": "danger",
            "stage": "생성 시작 전",
            "message": reason,
            "known": known,
            "out_dir": out_dir,
            "succeeded": 0,
            "failed": n,
            "failed_selectable": len(self._last_failed),
            "total": n,
            "failures": [],
            "fill_notes": [],
            "cancelled": False,
            "attempted": 0,
            "unstarted": n,
            # 계약 §10.3 이 원인 미확정 화면에 **명시적으로** 요구하는 증거다("사용한
            # Template·Binding 판본") — 원인을 모를수록 아는 사실을 빠짐없이 대야 한다.
            "revisions": dict(self._run_revisions),
        }

    # ----------------------------------- S4 Working Slot Configuration(SX-02 #725)
    # 4개 command 는 전부 **dispatch 경로**다(직접 브리지 아님). work_ref 는 세션의 현재 작업
    # (payload 에 없음, template_check 선례). configuration_token 은 opaque(프런트가 직전 응답의 새
    # token 을 되돌려준다), request_id 는 프런트 발급 재전송 단위. command outcome + fresh view 는
    # Product `SlotConfigurationProduct._respond` 가 이미 조립하므로 컨트롤러는 asdict 로 관통만 한다
    # (local optimistic authority 0 — 응답 도착 시 backend view 로 통째 교체). 현재 구성의
    # broken/missing 분리는 projection(blocking_items·detached_selections)이, **이전에 고른 것의
    # 운명**은 projection.retained_selections(#777)가 이미 지므로 여기서 재판정하지 않는다.
    def _slot_response_dict(self, response) -> dict:
        """`SlotConfigurationCommandResponse`(중첩 frozen dataclass) → JSON-safe dict.

        `asdict` 가 중첩 dataclass·tuple 을 dict/list 로 재귀 변환한다. projection 의
        detached_selections·blocking_items·retained_selections 가 그대로 실려 프런트가
        분리 소비한다(문안·확인 UI 는 웹, 판정·수치는 Python).
        """
        return asdict(response)

    @staticmethod
    def _slot_blank_zone() -> dict:
        """미지원 slot_configuration 존 — 매 호출 fresh dict(공유 mutable 상수 금지)."""
        return {
            "supported": False,
            "initialized": False,
            "mutation_outcome": None,
            "current_view": None,
            "refresh_required": False,
            "error": None,
        }

    def _is_managed_hwpx_work(self, job) -> bool:
        """의미 3(managed_hwpx)의 파생(S6-05 · #812) — 실행 경로 의미와 한 원천에서 나온다.

        「이 Work 가 materialization 대상인가」= hwpx ∧ durable authority ∧ **slot-bearing**
        (링1 projection 의 slots 사실 — 재판정이 아니라 이름 붙이기). slotless 발급 작업은
        False → legacy 갈래로 흘러 R1 트랩이 구조로 소멸한다. view 실패·미초기화도 False —
        slot-bearing 이 잘못 legacy 로 가도 admission 이 제 사유로 loud 거절한다(#806 R2 백스톱).
        조회는 read-only projection(#744)이라 렌더 부작용이 없다.
        """
        if job.media != "hwpx" or not job.authority_id:
            return False
        if self._slot_configuration is None or not self.job_name:
            return False
        try:
            response = self._slot_configuration.current_slot_configuration_view(
                self.job_name
            )
        except SlotConfigurationProductError:
            return False
        projection = response.current_view.projection
        return projection is not None and bool(projection.slots)

    def _slot_configuration_zone(self, tmissing: bool) -> dict:
        """스냅샷의 ``slot_configuration`` 존 — fresh current view 를 조회해 실어 보낸다.

        미주입·미선택·비-hwpx·템플릿 부재면 명시적 unsupported(분기별 키 동형). 초기화 전(Work
        durable id 미발급) Work 는 Product 를 부르지 않는다 — route 가 read 중 durable id 를 발급하므로
        (write-on-read) 렌더 부작용을 피한다. 초기화된 Work 는 #744 read-only projection 으로 조회한다
        — 스냅샷은 렌더라 open(ensure)의 successor reconciliation 물질화로 durable S4 를 바꾸지 않는다.
        ensure 는 명시적 open/refresh command(`_do_open_slot_configuration`·`_do_refresh_...`)에만 남긴다.
        """
        blank = self._slot_blank_zone()
        if self._slot_configuration is None or not self.job_name or tmissing:
            return blank
        job = load_job(self.registry, self.job_name)
        if job.media != "hwpx":
            return blank
        if not job.authority_id:
            # 템플릿 확인(bootstrap) 전 — 지원은 하되 아직 조회하지 않는다(durable id 미발급 보존).
            return {**blank, "supported": True}
        try:
            response = self._slot_configuration.current_slot_configuration_view(self.job_name)
        except SlotConfigurationProductError as exc:
            # 정상 미초기화와 실패를 구분한다. 진단 code 는 보존하되 사용자 표면에는 snapshot
            # 재당김만 권한다 — Slot Product refresh 는 durable reconciliation 을 할 수 있다.
            return {
                **blank,
                "supported": True,
                "error": {
                    "code": exc.code,
                    "message": "포함할 내용을 불러오지 못했습니다. 다시 불러오세요.",
                    "action": {"key": "refresh", "label": "다시 불러오기"},
                },
            }
        return {
            "supported": True,
            "initialized": True,
            "error": None,
            **self._slot_response_dict(response),
        }

    # ── 작업대 Observation 존(SX-03 #726) — 합성 observation → JSON-safe dict ───────────────
    @staticmethod
    def _workbench_observation_blank() -> dict:
        return {"supported": False, "kind": None}

    def _workbench_observation_zone(self, tmissing: bool) -> dict:
        """스냅샷의 ``workbench_observation`` 존 — 합성 Observation(또는 ContextError)을 실어 보낸다.

        미조립·미선택·템플릿 부재면 명시적 unsupported. 그 밖에는 :meth:`workbench_observation` 을
        조립해 JSON-safe dict 로 성형한다 — 판정·문안·7상태는 Product/status 함수가 이미 낸 값이라
        여기서 재판정하지 않는다(프런트도 재판정 0, 읽기만).
        """
        if self._workbench_observation is None or not self.job_name or tmissing:
            return self._workbench_observation_blank()
        try:
            observation = self.workbench_observation()
        except ValueError:
            return self._workbench_observation_blank()
        return {"supported": True, **self._serialize_observation(observation)}

    def _serialize_observation(self, observation) -> dict:
        """`DocumentCreationWorkbenchObservation | ...ContextError` → JSON-safe dict(재판정 0).

        context error 는 user-fixable blocker 로 낮추지 않는다(kind=context_error, user_fixable=False).
        observation 은 blocker/primary_action/disabled_reason/deep-link + 이미 판정된 execution
        verdict(admission/readiness) + 7상태(code+phrase)를 성형한다. R2(#740): currentness 축은
        7상태(CURRENT/STALE)로 흡수돼 별도 키가 없다.
        """
        code, phrase = self._workbench_observation.execution_status(
            orchestration=self._session_orchestration,
            fresh_observation=self._last_fresh_observation,
        )
        if isinstance(observation, DocumentCreationWorkbenchContextError):
            return {
                "kind": "context_error",
                "code": observation.code,
                "detail": observation.detail,
                "user_fixable": observation.user_fixable,
                "primary_action": observation.primary_action,
                "execution_status_code": code,
                "execution_status_phrase": phrase,
                "create_action": {
                    "label": "\ubb38\uc11c \ub9cc\ub4e4\uae30",
                    "enabled": False,
                    "disabled_reason": phrase,
                },
            }
        return {
            "kind": "observation",
            "primary_action": observation.primary_action,
            "primary_action_enabled": observation.primary_action_enabled,
            "disabled_reason": observation.disabled_reason,
            "execution_action": (
                {
                    "label": "\ud604\uc7ac \uc124\uc815 \ud655\uc778",
                    "enabled": observation.primary_action_enabled,
                    "disabled_reason": observation.disabled_reason,
                }
                if observation.primary_action == RESOLVE_EXECUTION
                else None
            ),
            "create_action": {
                "label": "\ubb38\uc11c \ub9cc\ub4e4\uae30",
                "enabled": observation.create_documents_enabled,
                "disabled_reason": observation.create_documents_disabled_reason,
            },
            "blockers": list(observation.blockers),
            "deep_link_targets": [
                {"blocker_code": t.blocker_code, "route": t.route}
                for t in observation.deep_link_targets
            ],
            "execution_status_code": code,
            "execution_status_phrase": phrase,
            "materialization_readiness": observation.materialization_readiness,
            "admission": {
                "state": observation.admission.state,
                "reasons": list(observation.admission.reasons),
            },
            # S6-05(#812): 세션 실행 증거 — 부차 키(Primary Action·문안을 결정하지 않는다).
            "historical_outcome": (
                {
                    "outcome_kind": observation.historical_outcome.outcome_kind,
                    "observed_at": observation.historical_outcome.observed_at,
                }
                if observation.historical_outcome is not None
                else None
            ),
            "active_field_requirement_ids": list(observation.active_field_requirement_ids),
            "input_requirements": [
                {
                    "field_id": item.field_id,
                    "display_label": item.display_label,
                    "binding_state": item.binding_state,
                    "action_required": item.action_required,
                    "exact_target": item.exact_target,
                }
                for item in observation.input_requirements
            ],
            "binding_review_needed": "REVIEW_BINDING" in observation.blockers,
            "record_validation": {
                "validated_count": observation.record_validation.validated_count,
                "blocked_count": observation.record_validation.blocked_count,
                "issue_count": observation.record_validation.issue_count,
                "issues": [
                    {
                        "record_identity": issue.record_identity,
                        "record_display_locator": issue.record_display_locator,
                        "field_id": issue.field_id,
                        "field_display_label": issue.field_display_label,
                        "message": issue.message,
                        "recovery_target": asdict(issue.recovery_target),
                    }
                    for issue in observation.record_validation.issues
                ],
            },
            "preview_requirement": {
                "kind": observation.preview_requirement.kind,
                **(
                    {"reason": observation.preview_requirement.reason}
                    if isinstance(observation.preview_requirement, PreviewRequired)
                    else {}
                ),
            },
            "preview_satisfied": observation.preview_satisfied,
            "semantic_preview": (
                {
                    "preview_token": observation.semantic_preview.preview_token,
                    "requirement": {
                        "kind": observation.semantic_preview.requirement.kind,
                        **(
                            {"reason": observation.semantic_preview.requirement.reason}
                            if isinstance(
                                observation.semantic_preview.requirement,
                                PreviewRequired,
                            )
                            else {}
                        ),
                    },
                    "included_content_summary": (
                        observation.semantic_preview.included_content_summary
                    ),
                    "ordered_records": [
                        {
                            "record_identity": record.record_identity,
                            "record_display_locator": record.record_display_locator,
                            "logical_field_values": [
                                {
                                    "field_id": field.field_id,
                                    "display_label": field.display_label,
                                    "value": field.value,
                                }
                                for field in record.logical_field_values
                            ],
                            "planned_document_relative_path": (
                                record.planned_document_relative_path
                            ),
                            "collision_disposition": record.collision_disposition,
                        }
                        for record in observation.semantic_preview.ordered_records
                    ],
                }
                if self.preview_open and observation.semantic_preview is not None
                else None
            ),
            "run_delivery_intent": (
                {
                    "output_directory": observation.run_delivery_intent.output_directory,
                    "collision_policy": observation.run_delivery_intent.collision_policy,
                }
                if observation.run_delivery_intent is not None
                else None
            ),
            "delivery": {
                "resolvable": observation.delivery.resolvable,
                "planned_documents": [
                    {
                        "record_identity": item.record_identity,
                        "item_ordinal": item.item_ordinal,
                        "relative_path": item.relative_path,
                        "collision_disposition": item.collision_disposition,
                    }
                    for item in observation.delivery.planned_documents
                ],
                "blockers": [
                    {
                        "code": blocker.code,
                        "message": blocker.message,
                        "item_ordinal": blocker.item_ordinal,
                        "field_id": blocker.field_id,
                        "conflicting_relative_path": blocker.conflicting_relative_path,
                    }
                    for blocker in observation.delivery.blockers
                ],
            },
            # 사용자 문안 축(vocabulary 정본 — 내부어 0).
            "content_section_label": observation.content_section_label,
            "input_requirements_label": observation.input_requirements_label,
            "delivery_label": observation.delivery_label,
            # 이미 정한 것 요약.
            "active_work": {
                "active": observation.active_work.active,
                "work_ref": observation.active_work.work_ref,
            },
            "data_scope": {
                "mounted": observation.data_scope.mounted,
                "selected_record_count": observation.data_scope.selected_record_count,
                "total_record_count": observation.data_scope.total_record_count,
            },
        }

    def _require_slot_configuration(self) -> None:
        if self._slot_configuration is None:
            raise ValueError("문서 구성 기능이 조립되지 않았습니다")
        if not self.job_name:
            raise ValueError("먼저 작업을 선택하세요")

    def _do_open_slot_configuration(self, p: dict) -> dict:
        """현재 작업의 S4 Working Configuration 을 열어 fresh projection + 새 token 을 낸다(무변이).

        React 가 stored configuration·Template 구조를 직접 조립하지 않는다 — Product 가 낸
        authoritative view 하나를 그대로 소비한다.
        """
        self._require_slot_configuration()
        return self._slot_response_dict(
            self._slot_configuration.open_slot_configuration(self.job_name)
        )

    def _do_refresh_slot_configuration(self, p: dict) -> dict:
        """현재 configuration 을 새로 고쳐 fresh current view 를 되받는다(무변이).

        optional ``configuration_token`` 을 실으면 Product 가 그 token 의 Application 과 현재
        Application 을 대조해 stale 여부(``refresh_required``)를 판정한다 — 미실으면 최초 조회다.
        """
        self._require_slot_configuration()
        token = p.get("configuration_token")
        token = str(token) if token is not None else None
        return self._slot_response_dict(
            self._slot_configuration.refresh_slot_configuration(self.job_name, token)
        )

    def _do_select_slot_option(self, p: dict) -> dict:
        """Option 선택 = durable S4 command(별도 전체 저장 버튼 없음). command outcome + fresh view.

        stale token 은 Product 가 mutation 을 거절하고 fresh current view 를 되돌린다(유령 반영 0) —
        컨트롤러는 backend view 로 통째 교체만 한다(local optimistic authority 0).

        **automatic checking(SX-03 #726 · R2(#740) 착지).** durable commit 이 CHANGED 면
        `_maybe_auto_check` 가 자동 확인(`on_durable_command_settled` → 필요 시 seal → `on_seal_settled`)에
        진입한다. 수동 seal 버튼 0. seal 은 durable side effect 없는 순수 재계산이라 매 durable 변경마다
        재확인한다(opaque Plan ref 로 same-basis 를 미리 엿보던 경로는 R2 가 제거했다).

        생성과 **상호배제**한다(#725 리뷰). check-then-act(`raise_if_generating`)는 pywebview
        브리지가 별도 스레드라 검사와 mutation 사이에 `generate` 가 lock 을 잡아 old 구성을
        capture 하는 창이 남는다. 그래서 generation lock 을 직접 잡고 mutation+auto-check 를
        그 아래서 수행한다 — 그 사이 `generate`(non-blocking acquire)도 작업 전환/작업대 열기
        (`raise_if_generating_before_swap` 가 같은 lock 을 검사)도 끼지 못한다. 생성 중이면
        non-blocking 실패로 시끄럽게 거절한다.
        """
        self._require_slot_configuration()
        response = self._slot_command_serialized_with_generation(
            "포함할 내용을 바꾸세요",
            lambda: self._slot_configuration.select_slot_option(
                self.job_name,
                str(p["configuration_token"]),
                str(p["slot_id"]),
                str(p["option_id"]),
                str(p["request_id"]),
            ),
        )
        return self._slot_response_dict(response)

    def _slot_command_serialized_with_generation(self, then_do: str, run):
        """durable slot mutation + auto-check 를 generation lock 아래 원자로 수행한다(#725 리뷰).

        generate 와 같은 lock 을 non-blocking 으로 잡아 상호배제한다 — 잡히면 mutation·auto-check
        를 하고 반드시 놓는다. 이미 생성 중이면 시끄럽게 거절한다(`raise_if_generating` 문안 동형).
        """
        if not self._generation_lock.acquire(blocking=False):
            raise ValueError(f"문서 생성이 진행 중입니다. 끝난 뒤에 {then_do}.")
        try:
            work_at_start = self.job_name
            response = run()
            # auto-check 를 이 mutation 의 exact Work 에 결속한다(#725 재리뷰 P1). 작업 전환
            # (`select_job`)은 check-then-act 라 이 임계구역 사이에 job_name 을 바꿀 수 있다 —
            # 그러면 바뀐 Work 를 seal 하게 된다. Work 가 그대로일 때만 auto-check 하고, 바뀌었으면
            # 건너뛴다(변경된 Work 는 자기 command 가 몰고, 이 Work 는 다음 관찰에서 fresh 재계산).
            if self.job_name == work_at_start:
                self._maybe_auto_check(response)
            return response
        finally:
            self._generation_lock.release()

    def _do_clear_slot_selection(self, p: dict) -> dict:
        """Slot 선택 해제 = durable S4 command. command outcome + fresh view(선택과 동일 규율).

        automatic checking 진입은 `_do_select_slot_option` 과 같은 규율이다(`_maybe_auto_check`).
        생성과의 상호배제도 같은 규율이다(#725 리뷰) — generation lock 아래 원자로 수행한다.
        """
        self._require_slot_configuration()
        response = self._slot_command_serialized_with_generation(
            "선택을 해제하세요",
            lambda: self._slot_configuration.clear_slot_selection(
                self.job_name,
                str(p["configuration_token"]),
                str(p["slot_id"]),
                str(p["request_id"]),
            ),
        )
        return self._slot_response_dict(response)

    # ----------------------------------- Selection Preset 표면(S9-03 · #829)
    # 두 동사도 **dispatch 경로**다(직접 브리지 신설 0). 수치(적용 n·깨짐 m)는 S9-02
    # `PresetApplyDecision` 값이 Product 를 지나 그대로 실린다 — 여기서도 프런트에서도 slot
    # 목록을 다시 훑어 세지 않는다(같은 상태의 두 판정 금지).
    @staticmethod
    def _content_presets_blank() -> dict:
        """미지원 content_presets 존 — 매 호출 fresh dict(공유 mutable 상수 금지)."""
        return {"supported": False, "items": [], "corrupt": []}

    def _content_presets_zone(self, tmissing: bool) -> dict:
        """스냅샷의 ``content_presets`` 존 — 홈 레지스트리 목록 + 손상 항목 병기.

        지원 조건은 ``slot_configuration`` 존과 **동형**이다(미주입·미선택·비-hwpx·템플릿
        부재면 명시적 unsupported). 목록 자체는 Work 무관이지만 이 존을 소비하는 표면이
        「포함할 내용」 존이라 같은 조건에서 함께 서고 함께 진다.

        ``provenance`` 는 싣지 않는다 — advisory 내부 정보(Application·contract id)라 사용자
        표면의 재료가 아니다. 손상 항목은 숨기지 않고 ``corrupt`` 로 함께 나가고, 표면이
        비활성 + 사유 병기로 재진술한다.
        """
        blank = self._content_presets_blank()
        if self._slot_configuration is None or not self.job_name or tmissing:
            return blank
        job = load_job(self.registry, self.job_name)
        if job.media != "hwpx":
            return blank
        listing = self._slot_configuration.list_selection_presets()
        return {
            "supported": True,
            "items": [
                {"key": item.key, "name": item.name, "created_at": item.created_at}
                for item in listing.items
            ],
            "corrupt": [
                {"file_name": entry.file_name, "error": entry.error}
                for entry in listing.corrupt
            ],
            "corrupt_code": listing.corrupt_code,
        }

    def _do_save_selection_preset(self, p: dict) -> dict:
        """현재 선택을 이름 붙여 보관한다 — 조용한 덮기 경로 0(이름 충돌은 확인 왕복).

        generation lock 을 잡지 않는다: Work durable 상태는 **읽기만** 하고 쓰기는 홈
        레지스트리로 간다. 생성 중 배치가 고정한 실행 입력과 어긋날 것이 없다(select/clear
        와 갈리는 지점이고, 그 이유가 이 주석이다).
        """
        self._require_slot_configuration()
        confirmed = p.get("confirmed_overwrite_key")
        result = self._slot_configuration.save_selection_preset(
            self.job_name,
            str(p["configuration_token"]),
            str(p["name"]),
            str(confirmed) if confirmed is not None else None,
        )
        return asdict(result)

    def _do_apply_selection_preset(self, p: dict) -> dict:
        """Preset 적용 = durable S4 mutation — select 와 **같은 규율**이다.

        생성과 상호배제하고(`_slot_command_serialized_with_generation`), CHANGED 면 자동
        확인에 진입한다(`_maybe_auto_check` — 응답의 `mutation_outcome` 축이 select 응답과
        같은 형이라 그 판정이 그대로 선다). 응답은 outcome·fresh view·새 token 에 적용 n·
        깨짐 m 을 얹은 것이고, 수치는 backend 값 그대로다.
        """
        self._require_slot_configuration()
        response = self._slot_command_serialized_with_generation(
            "프리셋을 적용하세요",
            lambda: self._slot_configuration.apply_selection_preset(
                self.job_name,
                str(p["configuration_token"]),
                str(p["preset_key"]),
            ),
        )
        return self._slot_response_dict(response)

    # ── 세션 주체(Work) 정체 — 전환 시 실행 증거 무효화 ──────────────────────────────────
    @property
    def job_name(self) -> str:
        return self._job_name

    @job_name.setter
    def job_name(self, value: str) -> None:
        """세션 주체 Work. 다른 Work 로 바뀌면 세션 실행 증거를 함께 버린다.

        orchestration·fresh observation·basis digest 는 그것을 만든 Work 에 묶인다 — A 를 확인해
        SETTLED_CURRENT 로 둔 뒤 B 로 전환하면, B 는 아직 확인 전이므로 A 의 관찰로 B 를 CURRENT 라
        하지 않는다(조용히 틀리지 않는다). 같은 값 재대입은 재설정하지 않는다.
        """
        prior = getattr(self, "_job_name", None)
        self._job_name = value
        if prior is not None and value != prior:
            self._invalidate_execution_evidence()

    def _invalidate_execution_evidence(self) -> None:
        """Drop session-only execution evidence after its Work basis moves."""
        self._session_orchestration = AutomaticSealOrchestration()
        self._last_fresh_observation = None
        self._last_sealed_basis_digest = None
        self._last_sealed_plan_payload = None
        self._last_managed_outcome = None
        self._invalidate_current_preparations()

    # ── automatic seal orchestration(SX-03 #726 §2·§3 · SX-SEAL 배선) ──────────────────
    def on_editor_mapping_saved(self, work_ref: str) -> dict:
        """Commit the saved Mapping to S5, then reuse automatic current-value checking."""
        job = load_job(self.registry, work_ref)
        if job.media != "hwpx" or not job.authority_id:
            return {"binding_commit_ok": False, "binding_revision_id": None}
        if self._seal_execution is None:
            raise ValueError("Field Binding is not configured.")
        if not self._generation_lock.acquire(blocking=False):
            raise ValueError(
                "\ubb38\uc11c \uc0dd\uc131\uc774 \uc9c4\ud589 \uc911\uc785\ub2c8\ub2e4. \ub05d\ub09c \ub4a4\uc5d0 Mapping\uc744 \uc800\uc7a5\ud558\uc138\uc694."
            )
        try:
            result = self._seal_execution.commit_current_mapping(
                work_ref, uuid.uuid4().hex
            )
            if result is not None and self.job_name == work_ref:
                self._maybe_auto_check(effective_basis_changed=result.changed)
            return {
                "binding_commit_ok": result is not None,
                "binding_revision_id": result.revision_id if result is not None else None,
            }
        finally:
            self._generation_lock.release()

    def _maybe_auto_check(
        self, slot_response=None, *, effective_basis_changed: "bool | None" = None
    ) -> None:
        """durable slot mutation 뒤 자동 확인 진입 — mutation 이 CHANGED 일 때만(#724 §4).

        R2(#740): seal 은 durable side effect 없는 순수 재계산이고 opaque Plan ref 로 same-basis 를
        미리 엿보던 경로가 사라졌다 — durable 변경이 CHANGED 면 항상 재확인한다(``effective_basis_changed
        =True``). 미변경(open/ensure)은 아래 guard 로 걸러 blanket reseal 을 막는다. seal product
        미주입이면 자동 확인 없음(honest — 표면 부재).
        """
        if self._seal_execution is None or not self.job_name:
            return
        if effective_basis_changed is None:
            outcome = slot_response.mutation_outcome
            effective_basis_changed = outcome is not None and outcome.changed
        if not effective_basis_changed:
            return  # 무변이(open/ensure)·미변경 mutation → 반응할 basis 변경 없음.
        transition = on_durable_command_settled(
            self._session_orchestration,
            durable_command_succeeded=True,
            effective_basis_changed=True,
        )
        self._session_orchestration = transition.next_state
        if transition.should_start_seal:
            self._run_automatic_seal()

    def _run_automatic_seal(self) -> None:
        """진행 중 orchestration(CHECKING)에서 실 seal 을 돌리고 결과로 다음 상태를 판정한다.

        coalesce 대기(진행 중 도착한 basis 변경)를 소진할 때만 다시 seal 한다 — 무한 자동 재시도 0.
        route/context 예외는 seal 실패(연속 실패 수 상한 → 수동 복구)로, 반환된 terminal outcome 은
        '실행됨'으로 본다(qualification/policy block 은 실패가 아니라 not-current 로 알린다).
        """
        assert self._seal_execution is not None
        for _ in range(self._MAX_AUTO_SEAL_COALESCE):
            try:
                resp = self._seal_execution.seal_execution_plan(
                    self.job_name, uuid.uuid4().hex
                )
            except Exception:  # noqa: BLE001 — route/auth/context 예외 = 전이 실패(수동 복구 상한).
                transition = on_seal_settled(
                    self._session_orchestration,
                    seal_succeeded=False,
                    resulting_currentness_current=False,
                )
                self._session_orchestration = transition.next_state
                return
            self._absorb_seal_response(resp)
            transition = on_seal_settled(
                self._session_orchestration,
                seal_succeeded=True,
                resulting_currentness_current=self._fresh_is_current(resp.fresh_observation),
            )
            self._session_orchestration = transition.next_state
            if not transition.should_start_seal:
                return

    #: 진행 중 seal 위에 coalesce 로 이어붙는 연속 확인의 상한(무한 루프 방지).
    _MAX_AUTO_SEAL_COALESCE = 4

    def _absorb_seal_response(self, resp) -> None:
        """seal 응답 흡수 — fresh observation 보관 + sealed 면 basis digest·plan payload 를
        같은 응답에서 짝으로 갱신한다(S6-05 — 대조가 유의미하려면 출처가 같아야 한다)."""
        self._last_fresh_observation = resp.fresh_observation
        if isinstance(resp.command_outcome, ExecutionPlanSealedProductOutcome):
            self._last_sealed_basis_digest = resp.command_outcome.execution_basis_digest
            self._last_sealed_plan_payload = resp.command_outcome.plan_payload

    @staticmethod
    def _fresh_is_current(fresh: "FreshExecutionObservation") -> bool:
        # R2(#740): current sealable value 가 관찰되면 그 값이 곧 현재다(currentness 축 흡수).
        return isinstance(fresh, CurrentSealedPlanObservation)

    @staticmethod
    def _current_record_identity(snapshot_generation: int, model_index: int) -> str:
        return f"current-record/{snapshot_generation}/{model_index}"

    @staticmethod
    def _current_source_value_types(plan: SealedExecutionPlanValue) -> dict[str, str]:
        source_types: dict[str, str] = {}
        for requirement in plan.active_field_requirements:
            value_expression = requirement.get('value_expression')
            if not isinstance(value_expression, Mapping):
                continue
            if value_expression.get('kind') != 'FROM_SOURCE':
                continue
            source_key = value_expression.get('source_key')
            value_type = value_expression.get('value_type')
            if not isinstance(source_key, str) or not isinstance(value_type, str):
                raise _CurrentRecordCaptureError(
                    '현재 필드의 원본 항목과 데이터 값 종류를 확인할 수 없습니다.'
                )
            existing = source_types.get(source_key)
            if existing is not None and existing != value_type:
                source_types[source_key] = EXACT_TEXT
                continue
            source_types[source_key] = value_type
        return source_types

    def _capture_current_selected_records(
        self, plan: SealedExecutionPlanValue,
    ) -> tuple[int, tuple[int, ...], tuple[RawDataRecordSnapshot, ...]]:
        generation = self._snapshot_gen
        indices = tuple(self._indices())
        rows = self.records
        schema = (
            tuple(self.filter.columns)
            if self.filter is not None
            else tuple(rows[0].keys())
            if rows
            else ()
        )
        captured_at = self._clock().isoformat(timespec="seconds")
        source_value_types = self._current_source_value_types(plan)
        captured: list[RawDataRecordSnapshot] = []
        for model_index in indices:
            if not 0 <= model_index < len(rows):
                raise _CurrentRecordCaptureError("선택한 데이터 위치를 확인할 수 없습니다.")
            source_values = []
            for key, value in rows[model_index].items():
                if not isinstance(key, str):
                    raise _CurrentRecordCaptureError("데이터 항목 이름을 확인할 수 없습니다.")
                if value is None:
                    source_value = SourceNull()
                elif isinstance(value, str):
                    source_value = _capture_source_value(
                        value, source_value_types.get(key)
                    )
                else:
                    raise _CurrentRecordCaptureError(
                        f"{model_index + 1}행 {key} 값을 정확히 읽을 수 없습니다."
                    )
                source_values.append((key, source_value))
            captured.append(
                build_raw_record_snapshot(
                    source_schema_keys=schema,
                    source_values=source_values,
                    record_identity=self._current_record_identity(generation, model_index),
                    capture_provenance=RawRecordCaptureProvenance(
                        source_adapter_contract_id="job-current-record-capture/v1",
                        captured_at=captured_at,
                        source_observation_ref=f"job-snapshot/{generation}",
                    ),
                )
            )
        if (
            generation != self._snapshot_gen
            or rows is not self.records
            or indices != tuple(self._indices())
        ):
            raise _CurrentRecordCaptureError(
                "데이터가 다시 불러와져 선택한 값을 함께 확인할 수 없습니다. 다시 시도해 주세요."
            )
        return generation, indices, tuple(captured)

    @staticmethod
    def _record_source_key(plan: SealedExecutionPlanValue, field_id: str) -> str:
        for requirement in plan.active_field_requirements:
            if requirement.get("field_id") != field_id:
                continue
            value_expression = requirement.get("value_expression")
            if isinstance(value_expression, Mapping):
                source_key = value_expression.get("source_key")
                if isinstance(source_key, str) and source_key:
                    return source_key
        raise _CurrentRecordCaptureError("문제 데이터의 원본 항목을 확인할 수 없습니다.")

    def _record_issue(
        self,
        *,
        plan: SealedExecutionPlanValue,
        blocker: RecordValidationBlocker,
        generation: int,
        model_index: int,
        record_identity: str,
    ) -> RecordValidationIssue:
        if not isinstance(blocker.field_id, str):
            raise _CurrentRecordCaptureError("문제 데이터의 필드를 확인할 수 없습니다.")
        message = _RECORD_BLOCKER_PHRASES.get(blocker.code)
        if message is None:
            raise _CurrentRecordCaptureError("데이터 문제를 사용자 문안으로 표시할 수 없습니다.")
        source_key = self._record_source_key(plan, blocker.field_id)
        columns = self.filter.columns if self.filter is not None else []
        target = RecordRecoveryTarget(
            snapshot_generation=generation,
            record_identity=record_identity,
            model_index=model_index,
            field_id=source_key,
            target_kind='cell' if source_key in columns else 'row',
        )
        return RecordValidationIssue(
            record_identity=record_identity,
            record_display_locator=f"데이터 {model_index + 1}행",
            field_id=blocker.field_id,
            field_display_label=source_key,
            message=message,
            recovery_target=target,
        )

    def _current_record_validation(
        self,
    ) -> tuple[RecordValidationSummary, WorkbenchContextIntegrity | None]:
        fresh = self._last_fresh_observation
        if self._session_orchestration.state != ORCHESTRATION_SETTLED_CURRENT:
            return RecordValidationSummary(), None
        if not isinstance(fresh, CurrentSealedPlanObservation):
            return RecordValidationSummary(), None
        plan = fresh.sealed_plan_value
        work_ref = self.job_name
        indices = tuple(self._indices())
        cached = self._current_record_preparation
        if (
            cached is not None
            and cached.snapshot_generation == self._snapshot_gen
            and cached.work_ref == work_ref
            and cached.ordered_model_indices == indices
            and cached.execution_value == plan
        ):
            return cached.record_validation, None
        if not indices:
            return RecordValidationSummary(), None
        try:
            generation, captured_indices, raw_records = (
                self._capture_current_selected_records(plan)
            )
            results = validate_data_records_against_current_value(
                plan=plan,
                snapshots=raw_records,
                validated_at=raw_records[0].capture_provenance.captured_at,
            )
            validated: list[CurrentValidatedDataRecord] = []
            issues: list[RecordValidationIssue] = []
            blocked_count = 0
            for model_index, snapshot, result in zip(
                captured_indices, raw_records, results, strict=True
            ):
                if isinstance(result, RecordValidationContextError):
                    return RecordValidationSummary(), WorkbenchContextIntegrity(
                        restore_failure=True, code=result.code, detail=result.detail
                    )
                if isinstance(result, RecordValidationBlocked):
                    blocked_count += 1
                    issues.extend(
                        self._record_issue(
                            plan=plan,
                            blocker=blocker,
                            generation=generation,
                            model_index=model_index,
                            record_identity=snapshot.record_identity,
                        )
                        for blocker in result.blockers
                    )
                else:
                    validated.append(result)
        except (_CurrentRecordCaptureError, RawDataRecordError, FieldBindingError) as exc:
            return RecordValidationSummary(), WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_RECORD_CAPTURE_STALE",
                detail=str(exc),
            )
        if (
            generation != self._snapshot_gen
            or captured_indices != tuple(self._indices())
            or work_ref != self.job_name
            or fresh != self._last_fresh_observation
        ):
            return RecordValidationSummary(), WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_RECORD_PREPARATION_STALE",
                detail="확인 중 데이터나 작업 설정이 바뀌었습니다. 다시 시도해 주세요.",
            )
        summary = RecordValidationSummary(
            has_blocking_issues=bool(issues),
            issue_count=len(issues),
            validated_count=len(validated),
            blocked_count=blocked_count,
            issues=tuple(issues),
        )
        self._current_record_preparation = _CurrentRecordPreparation(
            snapshot_generation=generation,
            work_ref=work_ref,
            ordered_model_indices=captured_indices,
            execution_value=plan,
            raw_records=raw_records,
            validated_records=tuple(validated),
            record_validation=summary,
        )
        return summary, None

    def _do_recover_record_issue(self, p: dict) -> dict:
        target = p.get("target")
        if not isinstance(target, Mapping):
            raise ValueError("문제 위치 정보가 올바르지 않습니다.")
        preparation = self._current_record_preparation
        target_kind = target.get('target_kind')
        if preparation is None:
            raise ValueError("현재 데이터 확인 결과가 없습니다. 다시 확인해 주세요.")
        exact_targets = tuple(
            asdict(issue.recovery_target) for issue in preparation.record_validation.issues
        )
        if dict(target) not in exact_targets:
            raise ValueError(
                "데이터가 다시 불러와져 문제 위치를 복원할 수 없습니다. 현재 데이터에서 다시 확인해 주세요."
            )
        generation = target.get("snapshot_generation")
        model_index = target.get("model_index")
        record_identity = target.get("record_identity")
        field_id = target.get("field_id")
        if (
            type(generation) is not int
            or type(model_index) is not int
            or not isinstance(record_identity, str)
            or not isinstance(field_id, str)
            or target_kind not in ('cell', 'row')
            or generation != self._snapshot_gen
            or model_index not in tuple(self._indices())
            or record_identity != self._current_record_identity(generation, model_index)
            or preparation.work_ref != self.job_name
            or self._session_orchestration.state != ORCHESTRATION_SETTLED_CURRENT
            or not isinstance(self._last_fresh_observation, CurrentSealedPlanObservation)
            or preparation.execution_value != self._last_fresh_observation.sealed_plan_value
        ):
            raise ValueError(
                "데이터가 다시 불러와져 문제 위치를 복원할 수 없습니다. 현재 데이터에서 다시 확인해 주세요."
            )
        columns = self.filter.columns if self.filter is not None else []
        if target_kind == 'cell' and field_id not in columns:
            raise ValueError("문제 데이터의 항목 위치를 복원할 수 없습니다.")
        if target_kind == 'cell' and field_id in self.hidden_columns:
            raise ValueError("문제 항목이 숨겨져 있습니다. 열을 다시 표시한 뒤 이동해 주세요.")
        visible = self.filter.visible_indices(self.records) if self.filter is not None else []
        if model_index not in visible:
            raise ValueError("문제 행이 현재 검색 결과에 없습니다. 검색 조건을 해제해 주세요.")
        if target_kind == 'row':
            return {
                'ok': True,
                'element_id': f'jobRow-{model_index}',
                'fallback_element_id': f'jobRow-{model_index}',
            }
        column_index = columns.index(field_id)
        return {
            "ok": True,
            "element_id": f"jobCell-{model_index}-{column_index}",
            "fallback_element_id": f"jobRow-{model_index}",
        }

    _do_recover_record_issue.is_query = True

    @staticmethod
    def _unresolved_delivery(code: str, message: str) -> DeliveryPreviewSummary:
        return DeliveryPreviewSummary(
            resolvable=False,
            blockers=(DeliveryPreviewBlocker(code=code, message=message),),
        )

    @staticmethod
    def _observe_path_occupancy(
        intent: RunDeliveryIntent, observed_at: str
    ) -> PathOccupancyObservation:
        root = Path(intent.output_directory)
        if not root.is_absolute():
            raise ValueError("저장 폴더는 전체 경로여야 합니다.")
        try:
            entries = tuple(
                sorted(
                    (
                        PathOccupancyEntry(
                            entry.name,
                            REGULAR_FILE
                            if not entry.is_symlink() and entry.is_file()
                            else NON_REGULAR,
                        )
                        for entry in root.iterdir()
                    ),
                    key=lambda entry: entry.relative_name.casefold(),
                )
            )
        except OSError as exc:
            raise ValueError("저장 폴더의 현재 파일 목록을 읽을 수 없습니다.") from exc
        return PathOccupancyObservation(intent.output_directory, entries, observed_at)

    @staticmethod
    def _delivery_projection(
        result: CurrentResolvedDelivery | DeliveryPlanBlocked,
    ) -> DeliveryPreviewSummary:
        if isinstance(result, DeliveryPlanBlocked):
            return DeliveryPreviewSummary(
                resolvable=False,
                blockers=tuple(
                    DeliveryPreviewBlocker(
                        code=blocker.code,
                        message=_DELIVERY_BLOCKER_PHRASES.get(
                            blocker.code, "생성 예정 문서 이름을 확인할 수 없습니다."
                        ),
                        item_ordinal=blocker.item_ordinal,
                        field_id=blocker.field_id,
                        conflicting_relative_path=blocker.conflicting_relative_path,
                    )
                    for blocker in result.blockers
                ),
            )
        planned = tuple(
            PlannedDocumentSummary(
                record_identity=item.record_identity,
                item_ordinal=item.item_ordinal,
                relative_path=item.resolved_output_relative_path,
                collision_disposition=item.collision_disposition,
            )
            for item in result.ordered_items
        )
        return DeliveryPreviewSummary(
            resolvable=True,
            planned_output_names=tuple(item.relative_path for item in planned),
            planned_documents=planned,
        )

    def _invalidate_current_preview(self) -> None:
        self._current_preview_preparation = None
        self._approved_preview_token = None

    def _invalidate_current_preparations(self) -> None:
        self._current_record_preparation = None
        self._current_delivery_preparation = None
        self._invalidate_current_preview()

    def _current_preview(
        self,
    ) -> tuple[_CurrentPreviewPreparation | None, WorkbenchContextIntegrity | None]:
        if self._session_orchestration.state != ORCHESTRATION_SETTLED_CURRENT:
            self._invalidate_current_preparations()
            return None, None
        record_preparation = self._current_record_preparation
        delivery_preparation = self._current_delivery_preparation
        if (
            record_preparation is None
            or delivery_preparation is None
            or delivery_preparation.record_preparation is not record_preparation
            or not isinstance(delivery_preparation.result, CurrentResolvedDelivery)
        ):
            self._invalidate_current_preview()
            return None, None

        cached = self._current_preview_preparation
        if (
            cached is not None
            and cached.record_preparation is record_preparation
            and cached.delivery_preparation is delivery_preparation
        ):
            return cached, None

        self._invalidate_current_preview()
        requirement = evaluate_current_preview_requirement(delivery_preparation.result)
        preview_token = uuid.uuid4().hex
        try:
            projection = build_current_preview_projection(
                preview_token=preview_token,
                requirement=requirement,
                plan=record_preparation.execution_value,
                raw_records=record_preparation.raw_records,
                validated_records=record_preparation.validated_records,
                delivery=delivery_preparation.result,
                record_display_locators=tuple(
                    f"데이터 {model_index + 1}행"
                    for model_index in record_preparation.ordered_model_indices
                ),
            )
        except CurrentPreviewPreparationError as exc:
            return None, WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_PREVIEW_PREPARATION_STALE",
                detail=str(exc),
            )
        if (
            record_preparation is not self._current_record_preparation
            or delivery_preparation is not self._current_delivery_preparation
        ):
            return None, WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_PREVIEW_PREPARATION_STALE",
                detail="확인 중 데이터나 생성 예정 경로가 바뀌었습니다. 다시 시도해 주세요.",
            )
        current = _CurrentPreviewPreparation(
            record_preparation=record_preparation,
            delivery_preparation=delivery_preparation,
            requirement=requirement,
            projection=projection,
            preview_token=preview_token,
        )
        self._current_preview_preparation = current
        return current, None

    def _current_delivery(
        self,
        record_validation: RecordValidationSummary,
    ) -> tuple[DeliveryPreviewSummary, WorkbenchContextIntegrity | None]:
        intent = self._run_delivery_intent
        if intent is None:
            return self._unresolved_delivery(
                "OUTPUT_DIRECTORY_REQUIRED", "저장 폴더를 선택하세요."
            ), None
        preparation = self._current_record_preparation
        if record_validation.has_blocking_issues:
            return self._unresolved_delivery(
                "RECORD_VALIDATION_REQUIRED", "먼저 데이터 문제를 확인하세요."
            ), None
        if (
            preparation is None
            or preparation.snapshot_generation != self._snapshot_gen
            or preparation.work_ref != self.job_name
            or preparation.ordered_model_indices != tuple(self._indices())
            or not preparation.validated_records
        ):
            return self._unresolved_delivery(
                "CURRENT_RECORD_PREPARATION_REQUIRED", "생성할 데이터를 먼저 선택하세요."
            ), None
        fresh = self._last_fresh_observation
        if not isinstance(fresh, CurrentSealedPlanObservation):
            return self._unresolved_delivery(
                "CURRENT_EXECUTION_REQUIRED", "현재 설정을 먼저 확인하세요."
            ), None
        current_field_binding = fresh.current_field_binding
        if current_field_binding is None:
            return DeliveryPreviewSummary(resolvable=False), WorkbenchContextIntegrity(
                restore_failure=True,
                code="CURRENT_DELIVERY_BINDING_CONTEXT_MISSING",
                detail="현재 파일 이름에 사용할 항목 연결을 복원할 수 없습니다.",
            )
        exact_pattern = self.vm.job.filename_pattern if self.vm is not None else ""
        cached = self._current_delivery_preparation
        if (
            cached is not None
            and cached.record_preparation is preparation
            and cached.current_field_binding == current_field_binding
            and cached.exact_pattern == exact_pattern
            and cached.run_delivery_intent == intent
        ):
            if isinstance(cached.result, DeliveryPlanContextError):
                return DeliveryPreviewSummary(resolvable=False), WorkbenchContextIntegrity(
                    restore_failure=True,
                    code=cached.result.code,
                    detail=cached.result.detail,
                )
            return self._delivery_projection(cached.result), None

        captured_clock = self._clock().isoformat(timespec="seconds")
        basis = build_delivery_binding_basis(
            base_template_application_id=current_field_binding.base_template_application_id,
            field_binding_authority_revision=(
                current_field_binding.field_binding_authority_revision
            ),
            filename_pattern_contract_id=FILENAME_PATTERN_CONTRACT_ID,
            exact_pattern=exact_pattern,
            active_field_ids=(
                str(requirement["field_id"])
                for requirement in preparation.execution_value.active_field_requirements
            ),
            binding_rules=current_field_binding.binding_rules,
            document_value_resolution_contract_id=(
                preparation.execution_value.contract_semantics
                .document_value_resolution_contract_id
            ),
        )
        result: CurrentResolvedDelivery | DeliveryPlanBlocked | DeliveryPlanContextError
        if isinstance(basis, (DeliveryPlanBlocked, DeliveryPlanContextError)):
            result = basis
        else:
            assert isinstance(basis, GenerationDeliveryBindingBasis)
            try:
                occupancy = self._observe_path_occupancy(intent, captured_clock)
            except ValueError as exc:
                result = DeliveryPlanContextError(
                    "PATH_OCCUPANCY_OBSERVATION_FAILED", str(exc)
                )
            else:
                result = resolve_current_generation_delivery(
                    sealed_execution_plan=preparation.execution_value,
                    ordered_validated_records=preparation.validated_records,
                    ordered_raw_snapshots=preparation.raw_records,
                    delivery_binding_basis=basis,
                    exact_pattern=exact_pattern,
                    captured_delivery_clock=captured_clock,
                    run_delivery_intent=intent,
                    path_occupancy=occupancy,
                )
        self._current_delivery_preparation = _CurrentDeliveryPreparation(
            record_preparation=preparation,
            current_field_binding=current_field_binding,
            exact_pattern=exact_pattern,
            run_delivery_intent=intent,
            captured_delivery_clock=captured_clock,
            result=result,
        )
        if isinstance(result, DeliveryPlanContextError):
            return DeliveryPreviewSummary(resolvable=False), WorkbenchContextIntegrity(
                restore_failure=True, code=result.code, detail=result.detail
            )
        return self._delivery_projection(result), None

    def workbench_observation(self):
        """세션 사실 + seal 서비스 fresh observation → 작업대 Observation(SX-01 #724 · SX-03 #726).

        admission/readiness/7상태는 세션이 든 마지막 fresh observation
        (``_last_fresh_observation``)을 **소비만** 한다 — composer/status 함수가 재라벨하고 이 화면은
        재판정하지 않는다(CURRENT/STALE 은 orchestration 축이 나른다). fresh observation 이 없으면
        NO_EVIDENCE(정직한 disabled). SX-04 축
        (record/preview/delivery)은 seam 유지 — delivery anchor 가 CREATE 로의 누수를 막는다.
        """
        if self._workbench_observation is None:
            raise ValueError("작업대 Observation 기능이 조립되지 않았습니다")
        slot_view = None
        if self._slot_configuration is not None and self.job_name:
            job = load_job(self.registry, self.job_name)
            if job.media == "hwpx" and job.authority_id:
                try:
                    # #744: 관찰은 읽기다 — read-only projection 을 쓴다. open(ensure)은 stored
                    # config 부재 시 successor reconciliation 을 durable 하게 물질화하므로 render
                    # 경로에서 부르면 authority 를 mutate 한다(그 basis 변경은 관찰과도 어긋난다).
                    resp = self._slot_configuration.current_slot_configuration_view(self.job_name)
                except SlotConfigurationProductError:
                    resp = None
                if resp is not None:
                    slot_view = resp.current_view.projection
        binding_projection = None
        if (
            self._seal_execution is not None
            and self.job_name
            and isinstance(self._last_fresh_observation, CurrentWorkExecutionObservation)
        ):
            binding_projection = self._seal_execution.current_binding_review(self.job_name)
        if self._session_orchestration.state != ORCHESTRATION_SETTLED_CURRENT:
            self._invalidate_current_preparations()
        record_validation, context_integrity = self._current_record_validation()
        preview_preparation = None
        if context_integrity is None:
            delivery, delivery_context = self._current_delivery(record_validation)
            context_integrity = delivery_context
            if context_integrity is None and delivery.resolvable:
                preview_preparation, preview_context = self._current_preview()
                context_integrity = preview_context
            else:
                self._invalidate_current_preview()
        else:
            delivery = DeliveryPreviewSummary(resolvable=False)
        if context_integrity is not None:
            self._invalidate_current_preview()
            preview_preparation = None
        preview_requirement = (
            preview_preparation.requirement
            if preview_preparation is not None
            else PreviewNotRequired()
        )
        preview_satisfied = (
            not isinstance(preview_requirement, PreviewRequired)
            or self._approved_preview_token == preview_preparation.preview_token
        )
        return self._workbench_observation.compose(
            data_mounted=self.datasource is not None,
            selected_record_count=self.selection.selected_count(),
            total_record_count=len(self.records),
            active_work_ref=self.job_name or None,
            slot_view=slot_view,
            orchestration=self._session_orchestration,
            fresh_observation=self._last_fresh_observation,
            active_field_requirement_ids=(
                binding_projection.active_field_ids if binding_projection is not None else ()
            ),
            input_requirements=(
                binding_projection.input_requirements if binding_projection is not None else ()
            ),
            record_validation=record_validation,
            delivery=delivery,
            preview_requirement=preview_requirement,
            preview_satisfied=preview_satisfied,
            semantic_preview=(
                preview_preparation.projection
                if preview_preparation is not None
                else None
            ),
            # S6-05(#812): 세션의 managed 실행 증거 — 부차 축(Primary Action 불결정).
            historical_outcome=self._last_managed_outcome,
            run_delivery_intent=self._run_delivery_intent,
            context_integrity=context_integrity,
        )

    def _do_resolve_execution(self, p: dict) -> dict:
        """'현재 설정 확인' Primary Action(EXECUTION_CHECKING/STALE·NO_EVIDENCE) — 자동 확인의 명시 재실행.

        수동 seal 관리 동사가 아니다: automatic checking 과 **같은 seal 경로**를 사용자가 명시로
        재개할 뿐이다(§4 "수동 복구 요구를 상태로 표현"). FAILED 면 먼저 수동 복구(IDLE)로 되돌린 뒤
        CHECKING 진입 → 실 seal. seal 미주입이면 loud 거절(조용한 no-op 금지).
        """
        if self._seal_execution is None:
            raise ValueError("실행 확인 기능이 조립되지 않았습니다")
        if not self.job_name:
            raise ValueError("먼저 문서 작업을 선택하세요.")
        if self._session_orchestration.state == ORCHESTRATION_FAILED:
            self._session_orchestration = request_manual_recovery(self._session_orchestration)
        transition = on_durable_command_settled(
            self._session_orchestration,
            durable_command_succeeded=True,
            effective_basis_changed=True,
        )
        self._session_orchestration = transition.next_state
        if transition.should_start_seal:
            self._run_automatic_seal()
        return {"ok": True}

    def _do_refresh_observation(self, p: dict) -> dict:
        """현재 설정의 관찰을 '지금 이 순간'으로 새로 고친다(orchestration 전이 없음).

        R2(#740): observation 은 current authority 의 재계산이라 seal 과 하나다 — 별도의 'seal 없이
        관찰' 경로가 없다. seal 은 durable side effect 없는 순수 재계산이므로 다시 돌려
        ``_last_fresh_observation``·basis digest 만 교체하고 orchestration 상태는 건드리지 않는다
        (자동 확인 궤도와 분리). **확인이 실패하면 마지막 관찰을 조용히 유지하지 않고** context error 로
        교체한다 — refresh 가 route/store/무결성 오류로 실패했는데 이전 CURRENT 를 계속 주장하지
        않는다(조용히 틀리지 않는다). 미주입·미선택이면 no-op.
        """
        if self._seal_execution is not None and self.job_name:
            try:
                resp = self._seal_execution.seal_execution_plan(
                    self.job_name, uuid.uuid4().hex
                )
                self._absorb_seal_response(resp)
            except Exception as exc:  # noqa: BLE001 — 확인 실패를 시끄럽게(CURRENT 유지 금지).
                self._last_fresh_observation = ExecutionObservationContextError(
                    "OBSERVATION_REFRESH_FAILED", str(exc)
                )
        return {"ok": True}
