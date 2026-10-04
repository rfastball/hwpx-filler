"""Product observations that advance tutorial lessons."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..external.tutorial_practice import fingerprint
from .onboarding_match_editor import match_editor, match_editor_input


def match_event(tutorial: Any, event: str, screen: str, action: str,
                payload: dict, result: Any) -> dict | None:
    if event == "template_selected" or event in {
            "notice_data_selected", "contract_inputs_selected", "purchase_inputs_selected"}:
        return match_editor_input(tutorial, event, screen, action)
    if screen == "editor":
        return match_editor(tutorial, event, action, result)
    return _match_non_editor(tutorial, event, screen, action, payload, result)


def _match_non_editor(tutorial: Any, event: str, screen: str, action: str,
                      payload: dict, result: Any) -> dict | None:
    if screen == "job":
        matched = match_job(tutorial, event, action, payload, result)
        if matched is not None:
            return matched
    if screen == "workbench" or action in {"open_workbench", "copy_clipboard"}:
        matched = match_workbench(tutorial, event, action, result)
        if matched is not None:
            return matched
    if screen == "tutorial":
        return _match_prepared_data(event, action, result)
    return match_authoring(tutorial, event, screen, action, result)


def _match_prepared_data(event: str, action: str, result: Any) -> dict | None:
    if event in {"derived_data_prepared", "blank_data_prepared"} and action == "prepare_examples":
        return {"derived_data_path": result["path"],
                "derived_sheet": "계약" if event == "blank_data_prepared" else "공고"} if isinstance(result, dict) and result.get("path") else None
    return None


def _correct_notice_options(job: Any, lesson: str) -> bool:
    current = job.execution.current_slot_view(job.work.name)
    projection = current.current_view.projection if current else None
    labels = {
        slot.display_text: {option.display_text for option in slot.options
                            if option.selected and option.effective}
        for slot in projection.slots
    } if projection else {}
    expected = "소기업·소상공인" if lesson == "first_hwpx" else "중·소기업"
    return expected in labels.get("입찰참가자격", set()) and "고시 미만" in labels.get("낙찰자 결정방법", set())


def _notice_generated(tutorial: Any, event: str, job: Any, selected: set,
                      required: set | None, lesson: str | None, result: Any) -> dict | None:
    ctx = tutorial._context()
    if not _generation_ready(tutorial, job, selected, required, lesson, result):
        return None
    documents = [{"name": Path(path).name, "path": str(path), "kind": "hwpx"}
                 for path in job.delivered_artifact_paths()]
    expected_ids = {job.data.records[index]["입찰공고번호"] for index in required or ()}
    if len(documents) != 3 or not all(any(identifier in doc["name"] for doc in documents)
                                      for identifier in expected_ids):
        return None
    ctx["generated"] = documents
    if event == "notice_second_generated":
        tutorial._finish_result("다시 만든 문서 3건", "새 행의 입찰공고번호로 문서를 만들었습니다.",
                                "job", "results", ctx["generated"])
    return {}


def _generation_ready(tutorial: Any, job: Any, selected: set,
                      required: set | None, lesson: str | None, result: Any) -> bool:
    ctx = tutorial._context()
    if (job.work.name != ctx.get("job_name") or not ctx.get("job_name") or selected != required
            or job.data.path != tutorial._asset("공고목록.xlsx") or job.data.sheet != "공고"):
        return False
    return bool(lesson and _correct_notice_options(job, lesson)
                and job.work.vm.job.filename_pattern == "구매입찰공고-{{입찰공고번호}}"
                and isinstance(result, dict) and result.get("succeeded") == 3)


def _notice_result_opened(tutorial: Any, job: Any, same_job: bool, result: Any) -> dict | None:
    ctx = tutorial._context()
    artifact = job.runs.artifact_payload()
    if (not same_job or result != {"ok": True} or not ctx.get("generated")
            or artifact.get("status") != "observed" or not artifact.get("structure")
            or not any(Path(doc["path"]).name == Path(artifact.get("filename", "")).name
                       for doc in ctx["generated"])):
        return None
    tutorial._finish_result("생성한 문서 3건", "결과 문서의 내용을 확인했습니다.",
                            "job", "results", ctx["generated"])
    return {}


def _option_result_reviewed(tutorial: Any, job: Any, same_job: bool, result: Any) -> dict | None:
    ctx = tutorial._context()
    wb = tutorial._workbench()
    if not _option_review_ready(ctx, same_job, result):
        return None
    option_set = _review_options(job)
    card = wb.snapshot().get("card") or {}
    rendered = "".join(segment.get("text", "") for segment in card.get("segments", []))
    if _option_content_ready(option_set, wb, ctx, rendered):
        tutorial._finish_result("변경 적용 결과", "고른 안내 문단의 채운 내용을 확인했습니다.",
                                "workbench", "txt-review", [], count=1)
        return {}
    return None


def _review_options(job: Any) -> list:
    current = job.execution.current_slot_view(job.work.name)
    projection = current.current_view.projection if current else None
    return [option for slot in projection.slots
            if slot.display_text == "예산 재배정 안내"
            for option in slot.options if option.selected and option.effective] if projection else []


def _option_review_ready(ctx: dict, same_job: bool, result: Any) -> bool:
    return bool(same_job and ctx.get("applied") and isinstance(result, dict)
                and result.get("ok") is True)


def _option_content_ready(options: list, wb: Any, ctx: dict, rendered: str) -> bool:
    return (any(option.display_text == "안내 포함" for option in options)
            and wb.is_open and wb.job_name == ctx.get("job_name")
            and "예산 재배정 여부" in rendered)


def _job_rows(tutorial: Any, event: str, action: str, payload: dict,
              job: Any, same_job: bool, selected: set, required: set | None,
              lesson: str | None) -> dict | None:
    if event in {"rows_cleared", "notice_first_filtered", "notice_second_filtered"}:
        return _job_filter_rows(event, action, payload, job, same_job, selected, required)
    return _job_select_rows(event, action, job, same_job, selected, required, lesson)


def _job_filter_rows(event: str, action: str, payload: dict, job: Any,
                     same_job: bool, selected: set, required: set | None) -> dict | None:
    if event == "rows_cleared" and action in {"set_none", "toggle_record", "select_range"}:
        return {} if same_job and not selected else None
    if event in {"notice_first_filtered", "notice_second_filtered"} and action.startswith("filter_"):
        return {} if _notice_filtered(job, same_job, payload, required) else None
    return None


def _job_select_rows(event: str, action: str, job: Any, same_job: bool,
                     selected: set, required: set | None, lesson: str | None) -> dict | None:
    if event in {"notice_first_rows", "notice_second_rows"} and action in {
            "toggle_record", "select_range", "set_all", "range_draft_apply"}:
        return {} if same_job and selected == required else None
    if event in {"notice_first_options", "notice_second_options"} and action == "select_slot_option":
        return {} if same_job and lesson and _correct_notice_options(job, lesson) else None
    return None


def _notice_filtered(job: Any, same_job: bool, payload: dict, required: set | None) -> bool:
    records = job.data.records
    visible = set(job.data.filter.visible_indices(records)) if job.data.filter else set(range(len(records)))
    return same_job and payload.get("column") == "메모" and visible == required


def match_job(tutorial: Any, event: str, action: str, payload: dict, result: Any) -> dict | None:
    ctx = tutorial._context()
    job = tutorial._job()
    selected = set(job.data.selected_indices())
    lesson = tutorial.progress.selected
    required = {"first_hwpx": {0, 1, 2}, "repeat_hwpx": {3, 4, 5}}.get(lesson) if lesson else None
    same_job = job.work.name == ctx.get("job_name") and bool(ctx.get("job_name"))
    if event in {"notice_job_opened", "derived_reopened"} and action in {"select_job", "prefer_work"}:
        return _job_opened(tutorial, event, job, same_job)
    return _match_job_action(tutorial, event, action, payload, result, job,
                             same_job, selected, required, lesson)


def _job_opened(tutorial: Any, event: str, job: Any, same_job: bool) -> dict | None:
    if event == "notice_job_opened":
        return {} if same_job else None
    ctx = tutorial._context()
    if same_job and job.data.path == ctx.get("derived_data_path") and job.data.sheet == ctx.get("derived_sheet"):
        tutorial._finish_result("새 데이터 연결 완료", "저장한 작업을 다시 열어 새 파일과 시트를 확인했습니다.",
                                "job", "data-picker", [], count=1)
        return {}
    return None


def _match_job_action(tutorial: Any, event: str, action: str, payload: dict, result: Any,
                      job: Any, same_job: bool, selected: set, required: set | None,
                      lesson: str | None) -> dict | None:
    row_match = _job_rows(tutorial, event, action, payload, job, same_job, selected, required, lesson)
    if row_match is not None:
        return row_match
    if event in {"notice_first_generated", "notice_second_generated"} and action == "generate":
        return _notice_generated(tutorial, event, job, selected, required, lesson, result)
    if event == "notice_result_opened" and action == "artifact_open":
        return _notice_result_opened(tutorial, job, same_job, result)
    if event == "option_result_reviewed" and action == "open_workbench":
        return _option_result_reviewed(tutorial, job, same_job, result)
    return None


def match_workbench(tutorial: Any, event: str, action: str, result: Any) -> dict | None:
    wb = tutorial._workbench()
    ctx = tutorial._context()
    if not wb or not wb.is_open or wb.job_name != ctx.get("job_name"):
        return None
    card = wb.snapshot().get("card") or {}
    if event in {"contract_two_reviewed", "purchase_two_reviewed", "blank_observed", "blank_repaired"}:
        return _workbench_review(ctx, wb, card, event, action)
    if event in {"contract_two_copied", "purchase_copied"}:
        return _workbench_copy(tutorial, ctx, wb, event, action, result)
    return None


def _workbench_review(ctx: dict, wb: Any, card: dict, event: str, action: str) -> dict | None:
    source_row = card.get("source_row")
    if event in {"contract_two_reviewed", "purchase_two_reviewed"} and action in {"set_current", "step", "open_workbench"}:
        if source_row is not None and wb.view == "filled":
            seen = set(ctx.get("reviewed_rows", []))
            seen.add(source_row)
            ctx["reviewed_rows"] = sorted(seen)
            return {} if len(seen) >= 2 else None
    return _workbench_blank(card, event, action)


def _workbench_blank(card: dict, event: str, action: str) -> dict | None:
    if event == "blank_observed" and action in {"set_current", "step", "open_workbench"}:
        return {} if "계약보증금" in card.get("empty_fields", []) else None
    if event == "blank_repaired" and action == "set_map_value":
        return {} if "계약보증금" not in card.get("empty_fields", []) else None
    return None


def _workbench_copy(tutorial: Any, ctx: dict, wb: Any, event: str,
                    action: str, result: Any) -> dict | None:
    if action != "copy_clipboard" or not isinstance(result, dict) or result.get("copied") is not True:
        return None
    last = wb.snapshot().get("card", {}).get("last_copy") or {}
    copied = set(ctx.get("copied_rows", []))
    copied.add(last.get("row"))
    copied.discard(None)
    ctx["copied_rows"] = sorted(copied)
    target = 2 if event == "contract_two_copied" else 1
    if len(copied) >= target:
        tutorial._finish_result("TXT 복사 완료", f"서로 다른 {len(copied)}개 행을 복사했습니다.",
                                "workbench", "txt-copy", [], count=len(copied))
        return {}
    return None


def _match_authoring_field(tutorial: Any, event: str, action: str, result: dict,
                           authoring: Any, session: Any, fields: set) -> dict | None:
    if event == "field_practice_saved":
        return _field_practice_saved(tutorial, action, result, authoring, session)
    if event == "practice_field_created" and action == "update":
        return {} if _practice_field_created(fields, session) else None
    if event == "field_trial_input":
        return _field_trial_input(action, session)
    if event == "field_trial_passed" and action == "trial":
        return {} if _field_trial_passed(result) else None
    return None


def _field_trial_input(action: str, session: Any) -> dict | None:
    if action == "trial_input":
        return {} if session.values.get("재배정기한") else None
    return None


def _field_practice_saved(tutorial: Any, action: str, result: dict,
                          authoring: Any, session: Any) -> dict | None:
    if action in {"save", "save_authoring_document"}:
        return _authoring_saved(tutorial, "field_practice_saved", result, authoring, session)
    return None


def _practice_field_created(fields: set, session: Any) -> bool:
    return "재배정기한" in fields and "10일" not in session.content.decode("utf-8")


def _field_trial_passed(result: dict) -> bool:
    report = result.get("report") or {}
    return result.get("ok") is not False and not report.get("missing_fields") and not report.get("errors")


def _authoring_saved(tutorial: Any, event: str, result: dict,
                     authoring: Any, session: Any) -> dict | None:
    if result.get("ok") is True and authoring._readiness(session)["state"] == "ready":
        tutorial._context().setdefault("saved_fingerprints", {})[result["path"]] = fingerprint(Path(result["path"]))
        if event == "field_practice_saved":
            tutorial._finish_result("내 필드 준비 완료", "재배정기한 필드를 시험하고 사용 준비 상태로 저장했습니다.",
                                    "authoring", "save-template", [], count=1)
        return {}
    return None


def _match_authoring_option(tutorial: Any, event: str, action: str, result: dict,
                            authoring: Any, session: Any, slots: list) -> dict | None:
    if event == "option_practice_saved" and action in {"save", "save_authoring_document"}:
        return _authoring_saved(tutorial, event, result, authoring, session)
    if event in {"practice_item_created", "practice_options_created", "practice_both_trials_passed"}:
        return _match_option_practice(event, action, result, session, slots)
    if event == "option_change_applied" and action == "apply_job":
        return {"applied": True} if _option_change_applied(tutorial, result) else None
    return None


def _match_option_practice(event: str, action: str, result: dict,
                           session: Any, slots: list) -> dict | None:
    if event == "practice_item_created" and action == "update":
        return {} if any(slot.get("label") == "예산 재배정 안내" for slot in slots) else None
    if event == "practice_options_created" and action == "update":
        return {} if _practice_options_created(slots) else None
    if event == "practice_both_trials_passed" and action == "trial":
        return _both_trials_passed(result, session, slots)
    return None


def _practice_options_created(slots: list) -> bool:
    return any({option.get("label") for option in slot.get("options", [])} >= {"안내 포함", "안내 생략"}
               for slot in slots)


def _option_change_applied(tutorial: Any, result: dict) -> bool:
    return result.get("job_name") == tutorial._context().get("job_name") and result.get("is_current") is True


def _both_trials_passed(result: dict, session: Any, slots: list) -> dict | None:
    report = result.get("report") or {}
    if result.get("ok") is False or report.get("missing_fields") or report.get("errors"):
        return None
    for slot in slots:
        if slot.get("label") == "예산 재배정 안내":
            return {} if _both_options_tested(session, slot) else None
    return None


def _both_options_tested(session: Any, slot: dict) -> bool:
    options = {option.get("id") for option in slot.get("options", [])}
    tested = {option for (slot_id, option), (revision, _fingerprint)
              in session.trial_coverage_evidence.items()
              if slot_id == slot.get("id") and revision == session.revision}
    return options == tested and len(options) == 2


def match_authoring(tutorial: Any, event: str, screen: str, action: str, result: Any) -> dict | None:
    if screen != "authoring" or not isinstance(result, dict):
        return None
    authoring = tutorial.controllers["authoring"]
    session = authoring.sessions.get(authoring.active_id)
    if session is None or session.media != "txt":
        return None
    if session.source_path != tutorial._asset("낙찰자 선정 및 계약체결 안내.txt"):
        return None
    analysis = session.analysis
    if event in {"field_practice_opened", "option_practice_opened"} and action == "open_authoring_document":
        return {}
    if event in {"practice_field_created", "field_trial_input", "field_trial_passed", "field_practice_saved"}:
        fields = {field.get("name") for field in analysis.get("fields", [])}
        return _match_authoring_field(tutorial, event, action, result, authoring, session, fields)
    return _match_authoring_option(tutorial, event, action, result, authoring, session,
                                   analysis.get("slots", []))
