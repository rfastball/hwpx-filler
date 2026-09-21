"""Pure JSON projections for the job controller."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict
from pathlib import Path

from ..application.document_creation_workbench import (
    DocumentCreationWorkbenchContextError,
    RecordValidationSummary,
)
from ..application.generation import GenerationOutcome
from ..application.workbench_execution_status import CHECKING, NO_EVIDENCE, STALE
from ..domain.identity_summary import identity_summary
from ..gui.result_errors import classify_result_error, describe_fill_note
from .managed_run_result import run_title


_EXECUTION_RESOLVABLE_STATUS_CODES = frozenset((NO_EVIDENCE, CHECKING, STALE))


def review_payload(requirement) -> dict:
    return {
        "required": requirement.required,
        "risk": requirement.risk_class,
        "targets": list(requirement.changed_targets),
        "first_run": requirement.first_run,
        "unknown_baseline": requirement.unknown_baseline,
        "structure_changed": requirement.structure_changed,
    }


def overwrite_response(*, total: int, conflict_names: list[str]) -> dict:
    return {
        "ok": False,
        "needs_overwrite": True,
        "total": total,
        "overwrite_count": len(conflict_names),
        "new_count": max(0, total - len(conflict_names)),
        "conflict_names": conflict_names[:10],
        "conflict_more": max(0, len(conflict_names) - 10),
    }


def candidate_card(
    *,
    name: str,
    tier: str,
    favorited: bool,
    last_run_at: str,
    suggested: bool,
    mode: str,
    mode_label: str,
    template_path: str,
    template_missing: bool,
    conn_label: str,
) -> dict:
    return {
        "name": name,
        "tier": tier,
        "favorited": favorited,
        "last_run_at": last_run_at,
        "suggested": suggested,
        "mode": mode,
        "mode_label": mode_label,
        "template_name": Path(template_path).name if template_path else "",
        "template_path": template_path,
        "template_missing": template_missing,
        "conn_label": conn_label,
    }


def browse_row(row: dict, *, mode_label: str) -> dict:
    return {**row, "mode_label": mode_label}


def record_rows(
    *,
    records: list[dict],
    display_order: list[int],
    selected_indices: set[int],
    planned_filenames: dict[int, str],
    identity,
) -> list[dict]:
    return [
        {
            "index": index,
            "selected": index in selected_indices,
            "name": planned_filenames.get(index, ""),
            "summary": identity.display_for(records[index]),
        }
        for index in display_order
    ]


def _record_advisory_notice(summary: RecordValidationSummary) -> str:
    if not summary.advisories:
        return ""
    return (
        f"빈 값 {summary.marked_value_count}칸이 있습니다. "
        "문서에는 미입력 표식이 들어갑니다."
    )


def serialize_observation(observation, *, execution_status: tuple[str, str]) -> dict:
    """Turn an already-decided workbench observation into JSON-safe values."""
    code, phrase = execution_status
    if isinstance(observation, DocumentCreationWorkbenchContextError):
        return {
            "kind": "context_error",
            "code": observation.code,
            "detail": observation.detail,
            "user_fixable": observation.user_fixable,
            "primary_action": observation.primary_action,
            "execution_status_code": code,
            "execution_status_phrase": phrase,
            "recover_action": {
                "label": "다시 확인", "enabled": True, "disabled_reason": None,
            },
            "create_action": {
                "label": "문서 만들기", "enabled": False, "disabled_reason": phrase,
            },
        }
    return {
        "kind": "observation",
        "primary_action": observation.primary_action,
        "primary_action_enabled": observation.primary_action_enabled,
        "disabled_reason": observation.disabled_reason,
        "execution_action": (
            {
                "label": "현재 설정 확인",
                "enabled": observation.resolve_execution_disabled_reason is None,
                "disabled_reason": observation.resolve_execution_disabled_reason,
            }
            if code in _EXECUTION_RESOLVABLE_STATUS_CODES
            else None
        ),
        "create_action": {
            "label": "문서 만들기",
            "enabled": observation.create_documents_enabled,
            "disabled_reason": observation.create_documents_disabled_reason,
        },
        "blockers": list(observation.blockers),
        "deep_link_targets": [
            {"blocker_code": target.blocker_code, "route": target.route}
            for target in observation.deep_link_targets
        ],
        "execution_status_code": code,
        "execution_status_phrase": phrase,
        "materialization_readiness": observation.materialization_readiness,
        "admission": {
            "state": observation.admission.state,
            "reasons": list(observation.admission.reasons),
        },
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
            if item.action_required
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
            "advisory_count": observation.record_validation.marked_value_count,
            "advisory_notice": _record_advisory_notice(observation.record_validation),
            "advisories": [
                {
                    "code": advisory.code,
                    "field_id": advisory.field_id,
                    "marked_record_count": advisory.marked_record_count,
                }
                for advisory in observation.record_validation.advisories
            ],
        },
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
        "content_section_label": observation.content_section_label,
        "input_requirements_label": observation.input_requirements_label,
        "delivery_label": observation.delivery_label,
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


def failure_rows(
    *,
    records: list[dict],
    indices: Sequence[int],
    results: Iterable,
    filename_source_columns: list[str],
) -> list[dict]:
    """Project attempted, failed records; cancellation may leave results short."""
    pairs = [(index, result) for index, result in zip(indices, results, strict=False) if not result.ok]
    if not pairs:
        return []
    summary = identity_summary(records, filename_tokens=filename_source_columns)
    rows = []
    for index, result in pairs:
        reason, known = classify_result_error(result.error)
        rows.append(
            {
                "index": index,
                "identity": (
                    summary.display_for(records[index])
                    if 0 <= index < len(records)
                    else ""
                ),
                "filename": Path(result.output_path).name,
                "reason": reason,
                "known": known,
            }
        )
    return rows


def failed_result(
    *,
    indices: Sequence[int],
    out_dir: str,
    message: str,
    failed_indices: Sequence[int],
    revisions: dict,
) -> dict:
    reason, known = classify_result_error(message)
    total = len(indices)
    return {
        "ok": True,
        "status": "failed",
        "title": run_title("failed", False, 0, total),
        "summary": f"문서를 만들지 못했습니다. 대상 {total}건이 모두 생성되지 않았습니다.",
        "level": "danger",
        "stage": "생성 시작 전",
        "message": reason,
        "known": known,
        "out_dir": out_dir,
        "succeeded": 0,
        "failed": total,
        "failed_selectable": len(failed_indices),
        "total": total,
        "failures": [],
        "fill_notes": [],
        "cancelled": False,
        "attempted": 0,
        "unstarted": total,
        "revisions": dict(revisions),
    }


def generation_result(
    outcome: GenerationOutcome,
    *,
    blanks: Sequence[str],
    failures: list[dict],
    failed_indices: Sequence[int],
    out_dir: str,
    revisions: dict,
) -> dict:
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
        summary += f" 문서는 모두 만들어졌지만 실행 기록 저장에 실패했습니다({outcome.stamp_error})."
    fill_notes = [
        describe_fill_note(note)
        for note in dict.fromkeys(
            note for result in outcome.results if result.ok for note in result.notes
        )
    ]
    if fill_notes:
        summary += f" 채움 주의 {len(fill_notes)}건(아래 기록 확인)."
    return {
        "ok": True,
        "status": outcome.status,
        "title": run_title(
            outcome.status, cancelled, outcome.succeeded, outcome.failed
        ),
        "stage": "",
        "message": "",
        "known": True,
        "summary": summary,
        "level": (
            "warn"
            if cancelled
            else ("ok" if outcome.failed == 0 and not outcome.stamp_error else "danger")
        ),
        "out_dir": out_dir,
        "succeeded": outcome.succeeded,
        "failed": outcome.failed,
        "failed_selectable": len(failed_indices),
        "total": outcome.total,
        "failures": failures,
        "fill_notes": fill_notes,
        "cancelled": cancelled,
        "attempted": outcome.attempted,
        "unstarted": outcome.unstarted,
        "revisions": dict(revisions),
    }
