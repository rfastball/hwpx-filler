"""Managed 실행 결과를 작업 화면 결과와 세션 갱신값으로 투영한다."""

from __future__ import annotations

from dataclasses import dataclass

from ..application.document_creation_workbench import (
    HistoricalOutcomeSummary,
    RecordValidationSummary,
)
from ..domain.identity_summary import identity_summary
from ..external.delivery_coordinator import (
    DeliveryCompleted,
    DeliveryRefused,
)
from ..application.generation_delivery import CurrentResolvedDelivery
from ..viewmodel.mapping_state import STRUCTURE_NOTATION_BLOCK_MESSAGE
from ..viewmodel.result_errors import describe_fill_note
from ..application.slotless_run_bridge import STRUCTURE_NOTATION_UNCOMPILED
from .current_execution_preparation import CurrentDeliveryPreparation
from .managed_generation import (
    ManagedGenerationResult,
    ManagedReadBackFailed,
    ManagedRunCancelled,
    ManagedRunRefused,
)


ADMISSION_REJECT_TEXT = {
    "TEMPLATE_INITIALIZATION_REQUIRED": "이 템플릿을 문서 작업으로 초기화할 수 없어 생성할 수 없습니다. 템플릿 파일을 확인하세요.",
    "NEEDS_CONFIGURATION_REVIEW": "실행 구성 출처를 확인할 수 없어 생성을 멈췄습니다. 구성을 검토하세요.",
    "NEEDS_CONFIGURATION": "템플릿이 바뀌어 실행 구성을 다시 확인해야 생성할 수 있습니다.",
    "STALE_TEMPLATE_APPLICATION": "적용된 템플릿 판본이 최신이 아니라 생성을 멈췄습니다.",
    "SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE": "이 작업의 문서 구성이 아직 확립되지 않았습니다. '템플릿 변경사항 확인'을 먼저 실행한 뒤 다시 시도하세요.",
    "SLOTLESS_SELECTION_CONTEXT_REQUIRED": "슬롯 없는 실행 맥락을 확립하지 못해 생성할 수 없습니다.",
    "APPLIED_TEMPLATE_CONTENT_INTEGRITY_ERROR": "적용된 템플릿 바이트 무결성 확인에 실패해 생성을 멈췄습니다.",
    STRUCTURE_NOTATION_UNCOMPILED: STRUCTURE_NOTATION_BLOCK_MESSAGE,
}


@dataclass(frozen=True)
class ManagedRunProjection:
    result: dict
    generated_indices: tuple[int, ...] | None = None
    failed_indices: tuple[int, ...] | None = None
    historical_outcome: HistoricalOutcomeSummary | None = None


def run_title(status: str, cancelled: bool, succeeded: int, failed: int) -> str:
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


def managed_blank_note(summary: RecordValidationSummary) -> str:
    """완료 요약의 표식 병기 — legacy 갈래(`" 빈 값 표시 필드 N개(…)."`)와 같은 문형.

    수치는 **필드 수**다: legacy 가 세는 것도 「빈 값이 난 필드」의 수라, 여기서 칸 수를
    쓰면 같은 실행이 경로에 따라 다른 숫자를 말한다(managed 는 필드×문서를 아는 반면
    legacy 는 필드 집합만 안다 — 겹치는 축으로 맞춘다).
    """
    fields = [advisory.field_id for advisory in summary.advisories]
    if not fields:
        return ""
    return f" 빈 값 표시 필드 {len(fields)}개({', '.join(fields)})."


def managed_failure_row(
    *,
    resolved_delivery: CurrentResolvedDelivery,
    ordered_model_indices: list[int],
    failed_ordinal: int,
    reason: str,
    records: list[dict],
    filename_source_columns: list[str],
) -> tuple[int, dict]:
    """managed 실패 항목 하나 → legacy 실패 행(안착 중단·되읽기 실패가 같은 투영을 쓴다).

    identity 는 legacy 와 같은 링1 표시명(§10.10 판정 E) — 내부 locator 를 노출하지 않는다.
    """
    failed_index = (
        ordered_model_indices[failed_ordinal]
        if failed_ordinal < len(ordered_model_indices)
        else failed_ordinal
    )
    failed_item = resolved_delivery.ordered_items[failed_ordinal]
    summary = identity_summary(records, filename_tokens=filename_source_columns)
    return failed_index, {
        "index": failed_index,
        "identity": (
            summary.display_for(records[failed_index])
            if 0 <= failed_index < len(records)
            else ""
        ),
        "filename": failed_item.resolved_output_relative_path,
        "reason": reason,
        "known": True,
    }


def project_managed_run_result(
    *,
    outcome: ManagedGenerationResult,
    preparation: CurrentDeliveryPreparation,
    records: list[dict],
    filename_source_columns: list[str],
    run_revisions: dict,
    generated_at: str,
    ledger_note: str = "",
) -> ManagedRunProjection:
    indices = list(preparation.record_preparation.ordered_model_indices)
    total = len(indices)
    blank_note = managed_blank_note(preparation.record_preparation.record_validation)
    if isinstance(outcome, (ManagedRunRefused, DeliveryRefused)):
        # 같은 admission 차단은 legacy 갈래와 같은 문장으로 재진술한다.
        return ManagedRunProjection({
            "ok": False,
            "error": ADMISSION_REJECT_TEXT.get(outcome.code, outcome.detail),
            "level": "warn",
        })
    resolved_delivery = preparation.result
    if not isinstance(resolved_delivery, CurrentResolvedDelivery):
        raise ValueError("managed result requires a resolved delivery plan")
    if isinstance(outcome, ManagedRunCancelled):
        # record 경계 취소는 안착 전이라 세션의 앞선 산출물 증거를 바꾸지 않는다.
        summary = (
            f"중단했습니다. 시도 {outcome.attempted}/{outcome.total}건 — 안착 전이라 "
            "문서는 만들지 않았습니다."
        ) + blank_note
        return ManagedRunProjection({
            "ok": True, "status": "cancelled",
            "title": run_title("cancelled", True, 0, 0),
            "stage": "", "message": "", "known": True, "summary": summary,
            "level": "warn", "out_dir": resolved_delivery.output_directory,
            "succeeded": 0, "failed": 0, "failed_selectable": 0,
            "total": outcome.total, "failures": [], "fill_notes": [],
            "cancelled": True, "attempted": outcome.attempted,
            "unstarted": outcome.total - outcome.attempted,
            "revisions": dict(run_revisions),
        })

    # DeliveryCompleted | ManagedReadBackFailed | DeliveryAborted: 앉은 문서까지는 유효하다.
    delivered = tuple(outcome.delivered)
    succeeded = len(delivered)
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
    if isinstance(outcome, DeliveryCompleted):
        summary = f"완료. 성공 {succeeded}/{total}, 실패 0." + blank_note
        if fill_notes:
            summary += f" 채움 주의 {len(fill_notes)}건(아래 기록 확인)."
        summary += ledger_note
        return ManagedRunProjection(
            {
                "ok": True, "status": "completed",
                "title": run_title("completed", False, succeeded, 0),
                "stage": "", "message": "", "known": True, "summary": summary,
                "level": "ok" if not ledger_note else "danger",
                "out_dir": outcome.output_directory,
                "succeeded": succeeded, "failed": 0, "failed_selectable": 0,
                "total": total, "failures": [], "fill_notes": fill_notes,
                "cancelled": False, "attempted": total, "unstarted": 0,
                "revisions": dict(run_revisions),
                "delivered": delivered_rows,
            },
            generated_indices=tuple(indices),
            failed_indices=(),
            historical_outcome=HistoricalOutcomeSummary(
                "DOCUMENTS_DELIVERED", generated_at
            ),
        )
    if isinstance(outcome, ManagedReadBackFailed):
        # 전건 안착 뒤 하나를 되읽지 못한 상태라 미착수는 0이고 성공 수에서만 빠진다.
        succeeded -= 1
        failed_index, failure = managed_failure_row(
            resolved_delivery=resolved_delivery,
            ordered_model_indices=indices,
            failed_ordinal=outcome.failed_item_ordinal,
            reason=outcome.detail,
            records=records,
            filename_source_columns=filename_source_columns,
        )
        status = "partiallyCompleted" if succeeded else "failed"
        summary = (
            f"완료. 성공 {succeeded}/{total}, 실패 1. 문서는 만들었지만 만든 뒤 다시 "
            f"읽어 확인하는 데 실패했습니다({outcome.code}). 해당 파일을 직접 열어 "
            "내용을 확인하세요."
        ) + blank_note + ledger_note
        return ManagedRunProjection(
            {
                "ok": True, "status": status,
                "title": run_title(status, False, succeeded, 1),
                "stage": "", "message": "", "known": True, "summary": summary,
                "level": "danger", "out_dir": resolved_delivery.output_directory,
                "succeeded": succeeded, "failed": 1, "failed_selectable": 1,
                "total": total, "failures": [failure], "fill_notes": fill_notes,
                "cancelled": False, "attempted": total, "unstarted": 0,
                "revisions": dict(run_revisions),
                "delivered": delivered_rows,
            },
            failed_indices=(failed_index,),
        )

    # DeliveryAborted: 실패 항목에서 멈췄고 이미 앉은 문서는 그대로 유지된다.
    failed_index, failure = managed_failure_row(
        resolved_delivery=resolved_delivery,
        ordered_model_indices=indices,
        failed_ordinal=outcome.failed_item_ordinal,
        reason=outcome.detail,
        records=records,
        filename_source_columns=filename_source_columns,
    )
    unstarted = total - succeeded - 1
    status = "partiallyCompleted" if succeeded else "failed"
    summary = (
        f"완료. 성공 {succeeded}/{total}, 실패 1. 미착수 {unstarted}건 — "
        "앉은 문서는 그대로 유지됩니다."
    ) + blank_note + ledger_note
    return ManagedRunProjection(
        {
            "ok": True, "status": status,
            "title": run_title(status, False, succeeded, 1),
            "stage": "", "message": "", "known": True, "summary": summary,
            "level": "danger", "out_dir": resolved_delivery.output_directory,
            "succeeded": succeeded, "failed": 1, "failed_selectable": 1,
            "total": total, "failures": [failure], "fill_notes": fill_notes,
            "cancelled": False, "attempted": succeeded + 1, "unstarted": unstarted,
            "revisions": dict(run_revisions),
            "delivered": delivered_rows,
        },
        failed_indices=(failed_index,),
    )


__all__ = [
    "ADMISSION_REJECT_TEXT",
    "ManagedRunProjection",
    "managed_blank_note",
    "managed_failure_row",
    "project_managed_run_result",
    "run_title",
]
