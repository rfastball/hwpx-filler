"""Pure JSON projections for the job controller."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ..application.document_creation_workbench import (
    DocumentCreationWorkbenchContextError,
    RecordValidationSummary,
)
from ..application.generation import GenerationOutcome
from ..application.workbench_execution_status import CHECKING, NO_EVIDENCE, STALE
from ..domain.job import work_mode
from ..domain.mapping import SOURCE_CARRIER_TYPES
from ..domain.identity_summary import identity_summary
from ..gui.result_errors import classify_result_error, describe_fill_note
from ..gui.work_candidates import (
    KIND_NEEDS_ACTION,
    MAIN_TOP_N,
    browse_candidates,
    candidate_rows,
    rank_available,
    suggested_work,
)
from ..gui.work_mode import WORK_MODE_TEXT, mode_sections, work_mode_label
from ..naming import pattern_field_tokens, plan_output_names
from .managed_run_result import run_title


_EXECUTION_RESOLVABLE_STATUS_CODES = frozenset((NO_EVIDENCE, CHECKING, STALE))
_CONN_MISSING_LABEL = "템플릿 없음"
_TXT_ONBOARDING_NOTE = (
    "저장된 TXT 작업이 없습니다. ‘문서 작업’의 [＋ 새 작업] → 템플릿 탭에서 "
    "TXT 템플릿을 선택하고 저장하세요."
)


def filename_source_columns(job, present_columns: Sequence[str]) -> list[str]:
    """Resolve filename template fields back to carried source columns."""
    tokens = set(pattern_field_tokens(job.filename_pattern))
    present = set(present_columns)
    columns: list[str] = []
    for mapping in job.mapping.mappings:
        if (
            mapping.template_field in tokens
            and mapping.type in SOURCE_CARRIER_TYPES
            and mapping.source in present
            and mapping.source not in columns
        ):
            columns.append(mapping.source)
    return columns


def base_panel_snapshot(
    *,
    job_name: str,
    last_run_job: str,
    job_data_unbound: bool,
    run_action: dict,
    out_dir: str,
    output_folder: dict,
    view_order: str,
    zone_selected_count: int,
    zone_epoch: int,
    selection_key: str,
    data_mount: int,
    data_label: str,
    data_source_label: str,
    data_target: dict,
    data_row: dict | None,
    data_pool_key: str,
    data_notice: dict | None,
    artifact_view: dict,
    new_work: dict,
    candidates: dict,
    browse: dict,
    range_draft: dict,
    template_change: dict,
    slot_configuration: dict,
    content_presets: dict,
) -> dict:
    """Build the branch-independent wire model from already prepared values."""
    return {
        "job_name": job_name,
        "managed_hwpx": False,
        "last_run_job": last_run_job,
        "has_job": bool(job_name),
        "job_data_unbound": job_data_unbound,
        "run_action": run_action,
        "guard": {
            "armed": False,
            "sel_count": 0,
            "in_def": 0,
            "extra": 0,
            "filter_active": False,
            "filter_parts": 0,
        },
        "out_dir": out_dir,
        "output_folder": output_folder,
        "view_order": view_order,
        "zone_selected_count": zone_selected_count,
        "zone_epoch": zone_epoch,
        "selection_key": selection_key,
        "data_mount": data_mount,
        "data_label": data_label,
        "data_source_label": data_source_label,
        "data_target": data_target,
        "data_row": data_row,
        "data_pool_key": data_pool_key,
        "data_notice": data_notice,
        "artifact_view": artifact_view,
        "new_work": new_work,
        "candidates": candidates,
        "browse": browse,
        "range_draft": range_draft,
        "template_change": template_change,
        "source_drift": None,
        "slot_configuration": slot_configuration,
        "content_presets": content_presets,
    }


def work_panel_snapshot(
    base: dict,
    *,
    managed_hwpx: bool,
    template_path: str,
    template_missing: bool,
    connection_label: str,
    filename_pattern: str,
    has_data: bool,
    record_count: int,
    selected_count: int,
    records: list[dict],
    filter_snapshot: dict,
    table_snapshot: dict,
    guard_snapshot: dict,
    preflight: dict,
    blank_fields: Sequence[str],
    drift: Sequence[str],
    name_tokens: Sequence[str],
    gate: dict,
    review: dict,
    rules_key: str | None = None,
    workbench_observation: dict | None = None,
    configuration_zones: dict | None = None,
) -> dict:
    """Build one TXT, empty, unsupported, or HWPX branch without live reads."""
    snapshot = dict(base)
    snapshot.update(
        {
            "managed_hwpx": managed_hwpx,
            "template_name": Path(template_path).name if template_path else "",
            "template_path": template_path,
            "template_missing": template_missing,
            "conn_label": connection_label,
            "filename_pattern": filename_pattern,
            "has_data": has_data,
            "record_count": record_count,
            "selected_count": selected_count,
            "records": records,
            "filter": filter_snapshot,
            "table": table_snapshot,
            "guard": guard_snapshot,
            "preflight": preflight,
            "blank_fields": list(blank_fields),
            "drift": list(drift),
            "name_tokens": list(name_tokens),
            "gate": gate,
            "review": review,
        }
    )
    if rules_key is not None:
        snapshot["rules_key"] = rules_key
    if workbench_observation is not None:
        snapshot["workbench_observation"] = workbench_observation
    if configuration_zones is not None:
        snapshot.update(configuration_zones)
    return snapshot


def connection_label(template_missing: bool) -> str:
    """Project an already observed availability fact into shared wording."""
    return _CONN_MISSING_LABEL if template_missing else ""


def candidate_payload(
    *,
    jobs,
    bound,
    fields: list[str] | None,
    active_name: str,
    txt_template_count: int,
    template_missing_by_path: Mapping[str, bool],
) -> dict:
    """Project already-loaded jobs into the data-bound candidate panel."""
    empty = {
        "top": [],
        "sections": [],
        "more": 0,
        "needs_count": 0,
        "suggested": "",
        "txt_note": "",
    }
    if fields is None:
        return empty

    by_name = {job.name: job for job in bound}
    ranked = rank_available(bound, fields)
    suggested = suggested_work(ranked, active=active_name)
    top = []
    for ranked_job in ranked[:MAIN_TOP_N]:
        job = by_name[ranked_job.name]
        missing = template_missing_by_path[job.template_path]
        top.append(
            candidate_card(
                name=ranked_job.name,
                tier=ranked_job.tier,
                favorited=bool(job.favorited_at),
                last_run_at=job.last_run_at,
                suggested=ranked_job.name == suggested,
                mode=ranked_job.mode,
                mode_label=work_mode_label(ranked_job.mode, short=True),
                template_path=job.template_path,
                template_missing=missing,
                conn_label=connection_label(missing),
            )
        )
    needs_count = sum(
        compatibility.kind == KIND_NEEDS_ACTION
        for _, compatibility in candidate_rows(bound, fields)
    )
    txt_note = ""
    if txt_template_count and not any(
        work_mode(job.template_path) == WORK_MODE_TEXT for job in jobs
    ):
        txt_note = _TXT_ONBOARDING_NOTE
    return {
        "top": top,
        "sections": mode_sections(top),
        "more": max(0, len(ranked) - MAIN_TOP_N),
        "needs_count": needs_count,
        "suggested": suggested,
        "txt_note": txt_note,
    }


def browse_payload(
    *,
    bound,
    fields: list[str] | None,
    browse_tab: str,
    browse_query: str,
) -> dict:
    """Project already-loaded jobs into the browse panel."""
    empty = {
        "tab": browse_tab,
        "query": browse_query,
        "rows": [],
        "sections": [],
        "available_count": 0,
        "needs_count": 0,
        "filtered_out": 0,
    }
    if fields is None:
        return empty
    result = browse_candidates(bound, fields, tab=browse_tab, query=browse_query)
    rows = [
        browse_row(row, mode_label=work_mode_label(row["mode"], short=True)) for row in result.rows
    ]
    return {
        "tab": result.tab,
        "query": browse_query,
        "rows": rows,
        "sections": mode_sections(rows),
        "available_count": result.available_count,
        "needs_count": result.needs_count,
        "filtered_out": result.filtered_out,
    }


def record_table_rows(
    *,
    records: list[dict],
    display_order: list[int],
    selected_indices: set[int],
    selected_model_indices: list[int],
    mapped_records: list[dict],
    filename_pattern: str | None,
    names_now: datetime | None,
    filename_source_columns: list[str],
) -> list[dict]:
    """Project records into stable display rows and selected output names."""
    if not records:
        return []
    names: dict[int, str] = {}
    if selected_model_indices and filename_pattern is not None:
        assert names_now is not None
        planned = plan_output_names(filename_pattern, mapped_records, now=names_now)
        names = dict(zip(selected_model_indices, planned, strict=True))
    return record_rows(
        records=records,
        display_order=display_order,
        selected_indices=selected_indices,
        planned_filenames=names,
        identity=identity_summary(records, filename_tokens=filename_source_columns),
    )


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
    return f"빈 값 {summary.marked_value_count}칸이 있습니다. 문서에는 미입력 표식이 들어갑니다."


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
                "label": "다시 확인",
                "enabled": True,
                "disabled_reason": None,
            },
            "create_action": {
                "label": "문서 만들기",
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
    pairs = [
        (index, result) for index, result in zip(indices, results, strict=False) if not result.ok
    ]
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
                    summary.display_for(records[index]) if 0 <= index < len(records) else ""
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
        summary = f"완료. 성공 {outcome.succeeded}/{outcome.total}, 실패 {outcome.failed}."
    if blanks:
        summary += f" 빈 값 표시 필드 {len(blanks)}개({', '.join(blanks)})."
    if outcome.stamp_error:
        summary += (
            f" 문서는 모두 만들어졌지만 실행 기록 저장에 실패했습니다({outcome.stamp_error})."
        )
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
        "title": run_title(outcome.status, cancelled, outcome.succeeded, outcome.failed),
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
