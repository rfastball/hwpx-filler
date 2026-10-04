"""Product observations that advance tutorial lessons: library, 문서 만들기 and the workbench.

:func:`match_event` is the single entry; the editor and authoring tables live beside it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .onboarding_match_authoring import AUTHORING_MATCHERS
from .onboarding_match_editor import EDITOR_MATCHERS, Matcher, Observation

__all__ = ["MATCHERS", "match_event"]

#: Rows the notice lessons pick, by lesson.
_REQUIRED_ROWS = {"first_hwpx": {0, 1, 2}, "repeat_hwpx": {3, 4, 5}}
#: lesson → (slot the single-option beat sets, the option it must hold).
_SLOT_CHOICE = {
    "first_hwpx": ("입찰참가자격", "소기업·소상공인"),
    "repeat_hwpx": ("입찰참가자격", "중·소기업"),
    "change_apply": ("예산재배정", "안내포함"),
}


def match_event(tutorial: Any, event: str, screen: str, action: str,
                payload: dict, result: Any) -> dict | None:
    matcher = MATCHERS.get(event)
    return None if matcher is None else matcher(tutorial, Observation(screen, action, payload, result))


def _ctx(tutorial: Any) -> dict:
    return tutorial._context()


def _same_job(tutorial: Any) -> bool:
    name = _ctx(tutorial).get("job_name")
    return bool(name) and tutorial._job().work.name == name


def _job_on(tutorial: Any, obs: Observation, *actions: str) -> bool:
    return obs.screen == "job" and obs.action in actions and _same_job(tutorial)


def _chosen(job: Any, slot_label: str) -> set:
    current = job.execution.current_slot_view(job.work.name)
    projection = current.current_view.projection if current else None
    return {option.display_text for slot in projection.slots if slot.display_text == slot_label
            for option in slot.options if option.selected and option.effective} if projection else set()


# ------------------------------------------------------------------ library and opening
def _library_selected(tutorial: Any, obs: Observation) -> dict | None:
    name = _ctx(tutorial).get("job_name")
    return {} if obs.screen == "library" and obs.action == "select_work" and name and obs.payload.get("name") == name else None


def _job_opened(tutorial: Any, obs: Observation) -> dict | None:
    return {} if _job_on(tutorial, obs, "select_job", "prefer_work") else None


def _derived_reopened(tutorial: Any, obs: Observation) -> dict | None:
    data, ctx = tutorial._job().data, _ctx(tutorial)
    if not (_job_on(tutorial, obs, "select_job", "prefer_work") and data.path == ctx.get("derived_data_path")
            and data.sheet == ctx.get("derived_sheet")):
        return None
    tutorial._finish_result("새 데이터 연결 완료", "저장한 작업을 다시 열어 새 파일과 시트를 확인했습니다.",
                            "job", "data-label", [], count=1)
    return {}


# ------------------------------------------------------------------ rows and filters
def _visible(job: Any) -> set:
    records = job.data.records
    return set(job.data.filter.visible_indices(records)) if job.data.filter else set(range(len(records)))


def _memo_opened(tutorial: Any, obs: Observation) -> dict | None:
    return {} if _job_on(tutorial, obs, "filter_panel") and obs.payload.get("column") == "메모" else None


def _memo_cleared(tutorial: Any, obs: Observation) -> dict | None:
    return {} if (_job_on(tutorial, obs, "filter_col_values") and obs.payload.get("column") == "메모"
                  and obs.payload.get("values") == []) else None


def _filtered(tutorial: Any, obs: Observation) -> dict | None:
    required = _REQUIRED_ROWS.get(tutorial.progress.selected or "")
    return {} if (obs.screen == "job" and obs.action.startswith("filter_") and _same_job(tutorial)
                  and obs.payload.get("column") == "메모" and _visible(tutorial._job()) == required) else None


def _picked_rows(tutorial: Any, obs: Observation) -> dict | None:
    required = _REQUIRED_ROWS.get(tutorial.progress.selected or "")
    selected = set(tutorial._job().data.selected_indices())
    return {} if (_job_on(tutorial, obs, "toggle_record", "select_range", "set_all", "range_draft_apply")
                  and selected == required) else None


def _all_rows(tutorial: Any, obs: Observation) -> dict | None:
    job = tutorial._job()
    count = len(job.data.records)
    return {} if _job_on(tutorial, obs, "set_all") and count and len(job.data.selected_indices()) == count else None


# ------------------------------------------------------------------ content options
def _slot_chosen(tutorial: Any, obs: Observation) -> dict | None:
    choice = _SLOT_CHOICE.get(tutorial.progress.selected or "")
    return {} if (choice and _job_on(tutorial, obs, "select_slot_option")
                  and choice[1] in _chosen(tutorial._job(), choice[0])) else None


def _notice_options(tutorial: Any, obs: Observation) -> dict | None:
    choice = _SLOT_CHOICE.get(tutorial.progress.selected or "")
    job = tutorial._job()
    return {} if (choice and _job_on(tutorial, obs, "select_slot_option")
                  and choice[1] in _chosen(job, choice[0]) and "고시 미만" in _chosen(job, "낙찰자 결정방법")) else None


# ------------------------------------------------------------------ HWPX generation
def _notice_ready(tutorial: Any, job: Any) -> bool:
    choice = _SLOT_CHOICE.get(tutorial.progress.selected or "")
    return bool(choice and job.data.path == tutorial._asset("공고목록.xlsx") and job.data.sheet == "공고"
                and job.work.vm.job.filename_pattern == "구매입찰공고-{{입찰공고번호}}"
                and choice[1] in _chosen(job, choice[0]) and "고시 미만" in _chosen(job, "낙찰자 결정방법"))


def _ran_three(tutorial: Any, obs: Observation) -> bool:
    result = obs.result if isinstance(obs.result, dict) else {}
    return obs.action == "generate" and _same_job(tutorial) and result.get("succeeded") == 3


def _generated_documents(tutorial: Any, obs: Observation) -> list[dict] | None:
    """The three documents of this lesson's rows, or None when the run was not that run."""
    job = tutorial._job()
    required = _REQUIRED_ROWS.get(tutorial.progress.selected or "") or set()
    if not _ran_three(tutorial, obs) or set(job.data.selected_indices()) != required or not _notice_ready(tutorial, job):
        return None
    documents = [{"name": Path(path).name, "path": str(path), "kind": "hwpx"} for path in job.delivered_artifact_paths()]
    expected = {job.data.records[index]["입찰공고번호"] for index in required}
    return documents if len(documents) == 3 and _named_after(documents, expected) else None


def _named_after(documents: list[dict], identifiers: set) -> bool:
    return all(any(identifier in doc["name"] for doc in documents) for identifier in identifiers)


def _generated(final: bool) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        documents = _generated_documents(tutorial, obs)
        if documents is None:
            return None
        _ctx(tutorial)["generated"] = documents
        if final:
            tutorial._finish_result("다시 만든 문서 3건", "새 행의 입찰공고번호로 문서를 만들었습니다.",
                                    "job", "results", documents)
        return {}
    return match


def _result_opened(tutorial: Any, obs: Observation) -> dict | None:
    ctx = _ctx(tutorial)
    artifact = tutorial._job().runs.artifact_payload()
    if (not _job_on(tutorial, obs, "artifact_open") or obs.result != {"ok": True} or not ctx.get("generated")
            or artifact.get("status") != "observed" or not artifact.get("structure")
            or not any(Path(doc["path"]).name == Path(artifact.get("filename", "")).name for doc in ctx["generated"])):
        return None
    tutorial._finish_result("생성한 문서 3건", "결과 문서의 내용을 확인했습니다.", "job", "results", ctx["generated"])
    return {}


# ------------------------------------------------------------------ TXT workbench
def _bench(tutorial: Any) -> tuple[Any, dict] | None:
    wb = tutorial._workbench()
    if not wb or not wb.is_open or wb.job_name != _ctx(tutorial).get("job_name"):
        return None
    return wb, wb.snapshot().get("card") or {}


def _bench_opened(tutorial: Any, obs: Observation) -> dict | None:
    opened = obs.action == "open_workbench" and isinstance(obs.result, dict) and obs.result.get("ok") is True
    return {} if opened and _bench(tutorial) is not None else None


def _blank_observed(tutorial: Any, obs: Observation) -> dict | None:
    bench = _bench(tutorial) if obs.action == "open_workbench" else None
    return {} if bench and "계약보증금" in bench[1].get("empty_fields", []) else None


def _stepped(tutorial: Any, obs: Observation) -> dict | None:
    bench = _bench(tutorial) if obs.action in {"step", "set_current"} else None
    row = bench[1].get("source_row") if bench else None
    return {} if row is not None and row not in _ctx(tutorial).get("copied_rows", []) else None


def _copied(rows: int, finish: bool) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        bench = _bench(tutorial)
        result = obs.result if isinstance(obs.result, dict) else {}
        if bench is None or obs.action != "copy_clipboard" or result.get("copied") is not True:
            return None
        ctx = _ctx(tutorial)
        row = (bench[1].get("last_copy") or {}).get("row")
        copied = set(ctx.get("copied_rows", [])) | ({row} if row is not None else set())
        ctx["copied_rows"] = sorted(copied)
        if len(copied) < rows:
            return None
        if finish:
            tutorial._finish_result("TXT 복사 완료", f"서로 다른 {len(copied)}개 행을 복사했습니다.",
                                    "workbench", "wb-copy", [], count=len(copied))
        return {}
    return match


def _option_reviewed(tutorial: Any, obs: Observation) -> dict | None:
    bench = _bench(tutorial)
    rendered = "".join(segment.get("text", "") for segment in (bench[1] if bench else {}).get("segments", []))
    if not (_bench_opened(tutorial, obs) is not None and _same_job(tutorial) and _ctx(tutorial).get("applied")
            and "안내포함" in _chosen(tutorial._job(), "예산재배정") and "예산 재배정 여부" in rendered):
        return None
    tutorial._finish_result("변경 적용 결과", "고른 안내 문단의 채운 내용을 확인했습니다.",
                            "workbench", "txt-review", [], count=1)
    return {}


MATCHERS: dict[str, Matcher] = {
    **EDITOR_MATCHERS,
    **AUTHORING_MATCHERS,
    "library_job_selected": _library_selected,
    "job_opened": _job_opened,
    "derived_reopened": _derived_reopened,
    "memo_filter_opened": _memo_opened,
    "memo_values_cleared": _memo_cleared,
    "notice_first_filtered": _filtered,
    "notice_second_filtered": _filtered,
    "notice_first_rows": _picked_rows,
    "notice_second_rows": _picked_rows,
    "rows_selected": _all_rows,
    "slot_option_chosen": _slot_chosen,
    "notice_first_options": _notice_options,
    "notice_second_options": _notice_options,
    "notice_first_generated": _generated(final=False),
    "notice_second_generated": _generated(final=True),
    "notice_result_opened": _result_opened,
    "txt_workbench_opened": _bench_opened,
    "blank_observed": _blank_observed,
    "first_row_copied": _copied(1, finish=False),
    "contract_two_reviewed": _stepped,
    "contract_two_copied": _copied(2, finish=True),
    "purchase_copied": _copied(1, finish=True),
    "option_result_reviewed": _option_reviewed,
}
