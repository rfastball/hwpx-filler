"""Editor observations for tutorial completion.

Each matcher sees one product command that actually returned and answers whether it
established exactly its beat's fact. The table :data:`EDITOR_MATCHERS` is the whole editor
vocabulary; the contract test checks that every action beat's event has a matcher or is a
UI press (:data:`~hwpxfiller.viewmodel.tutorial_lessons.UI_PRESS_EVENTS`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

__all__ = ["EDITOR_MATCHERS", "Observation"]

HWPX = "물품 구매입찰 공고.hwpx"
CONTRACT = "낙찰자 선정 및 계약체결 안내.txt"
PURCHASE = "계약방법 결정 및 구매추진 안내.txt"
DATA = "공고목록.xlsx"
PATTERN = "구매입찰공고-{{입찰공고번호}}"


@dataclass(frozen=True)
class Observation:
    screen: str
    action: str
    payload: dict
    result: Any


Matcher = Callable[[Any, Observation], "dict | None"]


def _edit(tutorial: Any) -> Any:
    return tutorial._editor().edit


def _rows(tutorial: Any) -> dict:
    model = _edit(tutorial).model
    return {row.template_field: row for row in model.rows} if model else {}


def _inputs(tutorial: Any, template: str, sheet: str) -> bool:
    edit = _edit(tutorial)
    return (edit.template_path == tutorial._asset(template) and edit.data_path == tutorial._asset(DATA)
            and edit.data_sheet == sheet)


def _lesson_inputs(tutorial: Any) -> bool:
    """The editor holds what the current lesson's editor beats stand on."""
    lesson = tutorial.progress.selected
    edit = _edit(tutorial)
    if lesson == "first_hwpx":
        return _inputs(tutorial, HWPX, "공고")
    if lesson == "contract_txt":
        return _inputs(tutorial, CONTRACT, "계약")
    return bool(edit.editing_origin) and edit.editing_origin == tutorial._context().get("job_name")


def _ok(obs: Observation) -> bool:
    return not isinstance(obs.result, dict) or obs.result.get("ok") is not False


def _on(obs: Observation, *actions: str) -> bool:
    return obs.screen == "editor" and obs.action in actions and _ok(obs)


def _row_index(tutorial: Any, field: str) -> int:
    model = _edit(tutorial).model
    return next((i for i, row in enumerate(model.rows) if row.template_field == field), -1) if model else -1


# ------------------------------------------------------------------ new job and inputs
def _new_job_opened(tutorial: Any, obs: Observation) -> dict | None:
    edit = _edit(tutorial)
    return {} if _on(obs, "new_session") and not edit.template_path and not edit.editing_origin else None


def _template(name: str) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        return {} if _on(obs, "use_library_template") and _edit(tutorial).template_path == tutorial._asset(name) else None
    return match


def _data(template: str, sheet: str) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        return {} if (_on(obs, "use_pool_data", "load_data_sheet", "use_library_template")
                      and _inputs(tutorial, template, sheet)) else None
    return match


def _section(section: str) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        return {} if (_on(obs, "goto_section") and obs.payload.get("section") == section
                      and _edit(tutorial).section == section and _lesson_inputs(tutorial)) else None
    return match


# ------------------------------------------------------------------ binding rows
def _row_matches(row: Any, source: str, kind: str, fmt: "str | None") -> bool:
    """`_confirmed` 의 행별 판정만 떼어낸 조건(복잡도 예산 분리)."""
    return bool(row and row.confirmed and (not source or row.source == source)
                and (not kind or row.type == kind) and (fmt is None or row.fmt == fmt))


def _confirmed(field: str, source: str = "", kind: str = "", fmt: str | None = None) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        row = _rows(tutorial).get(field)
        return {} if (_on(obs, "set_confirmed") and _lesson_inputs(tutorial)
                      and _row_matches(row, source, kind, fmt)) else None
    return match


def _notice_mapping(tutorial: Any, obs: Observation) -> dict | None:
    rows = _rows(tutorial)
    expected = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화"}
    done = all((row := rows.get(key)) and row.source == source and row.confirmed for key, source in expected.items())
    return {} if _on(obs, "set_confirmed", "confirm_suggested") and _lesson_inputs(tutorial) and done else None


def _contract_source(tutorial: Any, obs: Observation) -> dict | None:
    row = _rows(tutorial).get("대표계약업체")
    return {} if _on(obs, "set_source") and _lesson_inputs(tutorial) and row and row.source == "계약상대자" else None


def _contract_currency(tutorial: Any, obs: Observation) -> dict | None:
    row = _rows(tutorial).get("계약보증금")
    return {} if _on(obs, "set_display") and _lesson_inputs(tutorial) and row and row.type == "amount" and row.fmt == "" else None


def _notice_date_format(tutorial: Any, obs: Observation) -> dict | None:
    row = _rows(tutorial).get("게시일시")
    return {} if (_on(obs, "set_display") and _lesson_inputs(tutorial)
                  and row and row.type == "date" and row.fmt == "ym") else None


def _pattern_set(tutorial: Any, obs: Observation) -> dict | None:
    return {} if _on(obs, "set_pattern") and _lesson_inputs(tutorial) and _edit(tutorial).pattern == PATTERN else None


# ------------------------------------------------------------------ slice (purchase lesson)
def _sliced_to_drill(tutorial: Any) -> bool:
    edit, row = _edit(tutorial), _rows(tutorial).get("군품명")
    return bool(row and row.source == "군품명" and row.slice is not None and edit.records
                and row.to_mapping().value_for(edit.records[0]) == "드릴")


def _slice_opened(tutorial: Any, obs: Observation) -> dict | None:
    return {} if (obs.screen == "editor" and obs.action == "preview_slice" and _lesson_inputs(tutorial)
                  and obs.payload.get("index") == _row_index(tutorial, "군품명")) else None


def _slice_set(tutorial: Any, obs: Observation) -> dict | None:
    return {} if _on(obs, "set_slice") and _lesson_inputs(tutorial) and _sliced_to_drill(tutorial) else None


def _slice_confirmed(tutorial: Any, obs: Observation) -> dict | None:
    row = _rows(tutorial).get("군품명")
    return {} if _on(obs, "set_confirmed") and _sliced_to_drill(tutorial) and row and row.confirmed else None


def _formats_checked(tutorial: Any, obs: Observation) -> dict | None:
    kinds = {row.type for row in _rows(tutorial).values()}
    return {} if _on(obs, "step_preview") and _lesson_inputs(tutorial) and {"date", "amount"} <= kinds else None


# ------------------------------------------------------------------ data replacement lesson
def _editor_job_opened(tutorial: Any, obs: Observation) -> dict | None:
    return {} if obs.screen == "editor" and obs.action == "open_job_in_editor" and _lesson_inputs(tutorial) else None


def _derived(tutorial: Any) -> str:
    return tutorial._context().get("derived_data_path", "")


def _browse_started(tutorial: Any, obs: Observation) -> dict | None:
    return {} if obs.screen == "editor" and obs.action == "mapping_reset_stakes" and _lesson_inputs(tutorial) else None


def _file_picked(tutorial: Any, obs: Observation) -> dict | None:
    result = obs.result if isinstance(obs.result, dict) else {}
    return {} if (obs.action == "pick_data_file" and _lesson_inputs(tutorial) and result.get("needs_sheet")
                  and obs.payload.get("path") == _derived(tutorial)) else None


def _derived_selected(tutorial: Any, obs: Observation) -> dict | None:
    edit = _edit(tutorial)
    return {} if (_on(obs, "load_data_sheet", "use_pool_data") and _lesson_inputs(tutorial)
                  and edit.data_path == _derived(tutorial)
                  and edit.data_sheet == tutorial._context().get("derived_sheet")) else None


def _resuggest_asked(tutorial: Any, obs: Observation) -> dict | None:
    return {} if (obs.screen == "editor" and obs.action == "mapping_reset_stakes" and _lesson_inputs(tutorial)
                  and _edit(tutorial).section == "binding" and _edit(tutorial).data_path == _derived(tutorial)) else None


def _resuggested(tutorial: Any, obs: Observation) -> dict | None:
    result = obs.result if isinstance(obs.result, dict) else {}
    return {} if _on(obs, "resuggest_all") and _lesson_inputs(tutorial) and result.get("resuggested") else None


def _rebind_confirmed(tutorial: Any, obs: Observation) -> dict | None:
    rows = _rows(tutorial).values()
    return {} if (_on(obs, "confirm_suggested") and _lesson_inputs(tutorial) and rows
                  and _edit(tutorial).data_path == _derived(tutorial) and all(row.confirmed for row in rows)) else None


# ------------------------------------------------------------------ saving
def _saved(template: str, valid: Callable[[Any, dict], bool]) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        edit = _edit(tutorial)
        result = obs.result if isinstance(obs.result, dict) else {}
        if not (obs.screen == "editor" and obs.action == "save" and result.get("ok") is True
                and edit.template_path == tutorial._asset(template)):
            return None
        return {"job_name": edit.job_name} if valid(edit, _rows(tutorial)) else None
    return match


def _notice_saved(edit: Any, rows: dict) -> bool:
    expected = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화"}
    date_row = rows.get("게시일시")
    return (edit.pattern == PATTERN
            and all((row := rows.get(key)) and row.source == source and row.confirmed
                    for key, source in expected.items())
            and bool(date_row and date_row.type == "date" and date_row.fmt == "ym" and date_row.confirmed))


def _contract_saved(_edit: Any, rows: dict) -> bool:
    firm, amount = rows.get("대표계약업체"), rows.get("계약보증금")
    return bool(firm and firm.source == "계약상대자" and firm.confirmed
                and amount and amount.type == "amount" and amount.fmt == "" and amount.confirmed)


def _purchase_saved(edit: Any, rows: dict) -> bool:
    item = rows.get("군품명")
    return bool(item and item.slice is not None and edit.records
                and item.to_mapping().value_for(edit.records[0]) == "드릴")


EDITOR_MATCHERS: dict[str, Matcher] = {
    "new_job_opened": _new_job_opened,
    "template_selected": _template(HWPX),
    "contract_template_selected": _template(CONTRACT),
    "notice_data_selected": _data(HWPX, "공고"),
    "contract_inputs_selected": _data(CONTRACT, "계약"),
    "editor_section_binding": _section("binding"),
    "editor_section_filename": _section("filename"),
    "editor_section_template": _section("template"),
    "notice_row_confirmed": _confirmed("낙찰자결정방법", "낙찰방법"),
    "notice_mapping_confirmed": _notice_mapping,
    "notice_date_format_set": _notice_date_format,
    "notice_date_confirmed": _confirmed("게시일시", kind="date", fmt="ym"),
    "notice_pattern_set": _pattern_set,
    "contract_source_chosen": _contract_source,
    "contract_mapping_set": _confirmed("대표계약업체", "계약상대자"),
    "contract_currency_set": _contract_currency,
    "contract_amount_confirmed": _confirmed("계약보증금", kind="amount"),
    "slice_popover_opened": _slice_opened,
    "purchase_slice_set": _slice_set,
    "purchase_slice_confirmed": _slice_confirmed,
    "purchase_formats_checked": _formats_checked,
    "editor_job_opened": _editor_job_opened,
    "data_browse_started": _browse_started,
    "data_file_picked": _file_picked,
    "derived_data_selected": _derived_selected,
    "resuggest_asked": _resuggest_asked,
    "rows_resuggested": _resuggested,
    "rebind_rows_confirmed": _rebind_confirmed,
    "notice_job_saved": _saved(HWPX, _notice_saved),
    "contract_job_saved": _saved(CONTRACT, _contract_saved),
    "purchase_job_saved": _saved(PURCHASE, _purchase_saved),
}
