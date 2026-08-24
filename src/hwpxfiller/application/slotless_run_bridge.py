"""slotless legacy 실행 admission — exact applied Candidate bytes + 전체 실행 provenance (S4-11 #681).

S3-99 가 남긴 잔여: `evaluate_execution_provenance` 는 판정이 옳으나 production caller 가 없고
기존 generation 이 mutable `Job.template_path` 를 직독한다. 이 모듈이 그 guard 에 실제 caller 를
주고, slotless legacy 실행을 **exact applied Candidate bytes + 전체 execution configuration
provenance 가 모두 증명될 때만** 허용한다.

허용식(모두 참):
    current Application exact resolution 성공
    ∧ ExactAppliedTemplateInput exact integrity 성공
    ∧ exact Candidate bytes 가 generator template input
    ∧ evaluate_execution_provenance(base, current) == EXECUTION_ALLOWED
    ∧ exact SlotlessSelectionContext 존재
    ∧ 기존 legacy preflight 통과(호출자 소유)

`SlotlessSelectionContext` 만으로 Mapping·Constants·Output Rules provenance 를 증명하지 않는다 —
그 전체 provenance 는 `ExecutionConfigurationProvenancePort`(기존 Job/Mapping config 권위 소유)가 낸다.
S4 Slot Configuration 의 base 로 전체 execution provenance 를 대체하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .slot_configuration_context import ExactAppliedTemplateInput
from .slot_selection_input import SlotConfigurationSnapshot, SlotlessSelectionContext
from .work_bootstrap import (
    EXECUTION_ALLOWED,
    NEEDS_CONFIGURATION,
    NEEDS_CONFIGURATION_REVIEW,
    evaluate_execution_provenance,
)

# 제품 상태 / 오류 어휘.
SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE = "SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE"
SLOTLESS_SELECTION_CONTEXT_REQUIRED = "SLOTLESS_SELECTION_CONTEXT_REQUIRED"
APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR = "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR"
#: 실행할 bytes 에 미변환 구간 표기가 남았다(S8-04 #835). 이것을 통과시키면 산출물은
#: 모든 선택지를 품은 채 마커 텍스트까지 그대로 실린 **구조적으로 틀린 문서**가 된다.
STRUCTURE_NOTATION_UNCOMPILED = "STRUCTURE_NOTATION_UNCOMPILED"


class SlotlessRunAdmissionError(Exception):
    """slotless 실행 admission 거절 — code 로 제품 상태를 싣는다(fail-closed)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class ExecutionConfigurationProvenancePort(Protocol):
    """전체 execution configuration 의 base Application provenance 원천(기존 Job/Mapping 권위).

    provenance 를 durable 로 증명할 수 없으면 ``None``(UNKNOWN)이다 — S4 Slot base 로 대체하지
    않는다. UNKNOWN 을 bootstrap/current Application 에 자동 귀속하지 않는다.
    """

    def resolve_base_template_application_id(self, work_id: str) -> str | None: ...


@dataclass(frozen=True)
class AdmittedSlotlessRun:
    """admission 통과 시 고정하는 immutable run-plan input.

    staging path 자체는 identity 가 아니다 — exact digest 와 Application ID 가 provenance 다.
    이 값은 fence 아래에서 고정되고, 장기 generation 은 fence 밖에서 이 고정값만 쓴다.
    """

    work_id: str
    template_application_id: str
    exact_content_digest: str
    staged_template_path: str
    slotless_context: SlotlessSelectionContext


def admit_slotless_run(
    selection_input: "SlotlessSelectionContext | SlotConfigurationSnapshot",
    applied_input: ExactAppliedTemplateInput,
    execution_base_application_id: str | None,
    stage_exact_bytes: "Callable[[str], str]",
    *,
    count_structure_markers: "Callable[[str], int]",
) -> AdmittedSlotlessRun:
    """순수 admission — slot guard → provenance gate → exact bytes staging → 구조 표기 검문.

    ``stage_exact_bytes(digest) -> path`` 는 Candidate blob 을 content-addressed read-only 경로로
    옮기고 digest 를 검증하는 호출자 주입이다(bytes read/serialize 는 그 adapter 안, 여기 순수).
    slot-bearing 은 S5/S6 미완이라 실행 불가, slotless 만 provenance·bytes 게이트를 통과한다.

    ``count_structure_markers(staged_path) -> int`` 도 같은 결의 주입이다(파싱은 adapter 안).
    **기본값 없는 필수 인자**인 이유는 하나다: 빠뜨린 호출이 「마커 0」으로 조용히 통과하면
    이 게이트는 존재하지만 아무것도 막지 않는다. 세는 주체는 스캐너 단일 출처
    (:attr:`~hwpxfiller.domain.authoring.StructureSummary.markers`)이고 여기는 그 수치로
    **판정만** 한다 — admission 이 마커를 다시 세지 않는다. 검문 대상은 캐시된 상태가 아니라
    이 실행이 실제로 쓸 staged bytes 다(실행 시점 재읽기).
    """
    if isinstance(selection_input, SlotConfigurationSnapshot):
        # slot-bearing Template: 선택이 complete 여도 S5/S6 전에는 legacy generator 를 부르지 않는다.
        raise SlotlessRunAdmissionError(
            SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE,
            "Slot 이 있는 Template 은 실행 자격(S5)·materialization(S6) 전에는 실행할 수 없다",
        )
    if not isinstance(selection_input, SlotlessSelectionContext):
        raise SlotlessRunAdmissionError(SLOTLESS_SELECTION_CONTEXT_REQUIRED)

    current_application_id = selection_input.template_application_id
    # exact applied bytes 는 current Application 과 결속돼야 한다(다른 Application bytes 실행 금지).
    if applied_input.template_application_id != current_application_id:
        raise SlotlessRunAdmissionError(
            APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR,
            "applied Candidate 가 current Application 과 다른 Application 을 가리킨다",
        )

    verdict = evaluate_execution_provenance(
        execution_base_application_id, current_application_id
    )
    if verdict != EXECUTION_ALLOWED:
        # UNKNOWN → NEEDS_CONFIGURATION_REVIEW, 알려진 old → NEEDS_CONFIGURATION(둘 다 verdict code).
        raise SlotlessRunAdmissionError(verdict)

    staged_path = stage_exact_bytes(applied_input.exact_content_digest)
    marker_n = count_structure_markers(staged_path)
    if marker_n > 0:
        raise SlotlessRunAdmissionError(
            STRUCTURE_NOTATION_UNCOMPILED,
            f"실행할 템플릿에 미변환 구간 표기가 {marker_n}건 남아 있다",
        )
    return AdmittedSlotlessRun(
        work_id=applied_input.work_id,
        template_application_id=current_application_id,
        exact_content_digest=applied_input.exact_content_digest,
        staged_template_path=staged_path,
        slotless_context=selection_input,
    )


# verdict code re-export — 소비자(runner·컨트롤러)가 제품 상태를 한 곳에서 참조.
__all__ = [
    "AdmittedSlotlessRun",
    "ExecutionConfigurationProvenancePort",
    "SlotlessRunAdmissionError",
    "admit_slotless_run",
    "NEEDS_CONFIGURATION",
    "NEEDS_CONFIGURATION_REVIEW",
    "SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE",
    "SLOTLESS_SELECTION_CONTEXT_REQUIRED",
    "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR",
    "STRUCTURE_NOTATION_UNCOMPILED",
]
