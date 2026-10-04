"""Editor observations for tutorial completion."""

from __future__ import annotations

from typing import Any


def _editor_scope(tutorial: Any, editor: Any, lesson: str) -> bool:
    template = {
        "first_hwpx": "물품 구매입찰 공고.hwpx",
        "contract_txt": "낙찰자 선정 및 계약체결 안내.txt",
        "purchase_txt": "계약방법 결정 및 구매추진 안내.txt",
        "replace_data": "물품 구매입찰 공고.hwpx",
    }.get(lesson)
    if not template or editor.edit.template_path != tutorial._asset(template):
        return False
    beat = tutorial.progress.beat()
    expected_data = (tutorial._context().get("derived_data_path")
                     if lesson == "replace_data" and beat is not None
                     and beat.id in {"connect", "rebind", "reopen"}
                     else tutorial._asset("공고목록.xlsx"))
    expected_sheet = "계약" if lesson == "contract_txt" else "공고"
    return editor.edit.data_path == expected_data and editor.edit.data_sheet == expected_sheet


def match_editor_input(tutorial: Any, event: str, screen: str, action: str) -> dict | None:
    editor = tutorial._editor().edit
    if event == "template_selected" and screen == "editor" and action == "use_library_template":
        return {} if editor.template_path == tutorial._asset("물품 구매입찰 공고.hwpx") else None
    return _match_data_input(tutorial, editor, event, screen, action)


def _match_data_input(tutorial: Any, editor: Any, event: str, screen: str,
                      action: str) -> dict | None:
    templates = {
        "notice_data_selected": "물품 구매입찰 공고.hwpx",
        "contract_inputs_selected": "낙찰자 선정 및 계약체결 안내.txt",
        "purchase_inputs_selected": "계약방법 결정 및 구매추진 안내.txt",
    }
    template = templates.get(event)
    if template is None:
        return None
    sheet = "계약" if event == "contract_inputs_selected" else "공고"
    if screen == "editor" and action in {"load_data_sheet", "use_pool_data", "use_library_template"}:
        if (editor.template_path == tutorial._asset(template)
                and editor.data_path == tutorial._asset("공고목록.xlsx")
                and editor.data_sheet == sheet):
            return {}
    return None


def _notice_mapping(rows: dict) -> bool:
    expected = {"낙찰자결정방법": "낙찰방법", "담당자 전화번호": "담당자전화"}
    return all((row := rows.get(key)) and row.source == source and row.confirmed
               for key, source in expected.items())


def _saved_job(tutorial: Any, event: str, result: Any, rows: dict) -> dict | None:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    edit = tutorial._editor().edit
    expected = {
        "notice_job_saved": "물품 구매입찰 공고.hwpx",
        "contract_job_saved": "낙찰자 선정 및 계약체결 안내.txt",
        "purchase_job_saved": "계약방법 결정 및 구매추진 안내.txt",
    }.get(event)
    if expected and edit.template_path != tutorial._asset(expected):
        return None
    if event == "derived_job_rebound" and edit.data_path != tutorial._context().get("derived_data_path"):
        return None
    if not _saved_content_valid(event, edit, rows):
        return None
    return {"job_name": edit.job_name}


def _saved_content_valid(event: str, edit: Any, rows: dict) -> bool:
    if event == "notice_job_saved":
        return _notice_saved(edit, rows)
    if event == "contract_job_saved":
        return _contract_saved(rows)
    if event == "purchase_job_saved":
        return _purchase_saved(edit, rows)
    return True


def _notice_saved(edit: Any, rows: dict) -> bool:
    return edit.pattern == "구매입찰공고-{{입찰공고번호}}" and _notice_mapping(rows)


def _contract_saved(rows: dict) -> bool:
    firm, amount = rows.get("대표계약업체"), rows.get("계약보증금")
    return bool(firm and firm.source == "계약상대자" and firm.confirmed
                and amount and amount.type == "amount" and amount.fmt == "")


def _purchase_saved(edit: Any, rows: dict) -> bool:
    item = rows.get("군품명")
    return bool(item and item.slice is not None and edit.records
                and item.to_mapping().value_for(edit.records[0]) == "드릴")


def match_editor(tutorial: Any, event: str, action: str, result: Any) -> dict | None:
    lesson = tutorial.progress.selected
    editor = tutorial._editor()
    if not lesson or not _editor_scope(tutorial, editor, lesson):
        return None
    return _match_editor_scoped(tutorial, editor.edit, event, action, result)


def _match_editor_scoped(tutorial: Any, edit: Any, event: str, action: str,
                         result: Any) -> dict | None:
    mapping = edit.model
    rows = {row.template_field: row for row in mapping.rows} if mapping else {}
    if event in {"notice_mapping_confirmed", "notice_pattern_set"}:
        return _match_notice_editor(edit, event, action, rows)
    if event in {"notice_job_saved", "contract_job_saved", "purchase_job_saved", "derived_job_rebound"}:
        return _saved_job(tutorial, event, result, rows) if action == "save" else None
    if event in {"contract_mapping_set", "contract_currency_set"}:
        return _match_contract_editor(event, action, rows)
    if event in {"purchase_slice_set", "purchase_formats_checked"}:
        return _match_purchase_editor(edit, event, action, rows)
    return _match_derived_editor(tutorial, edit, event, action)


def _match_derived_editor(tutorial: Any, edit: Any, event: str, action: str) -> dict | None:
    if event == "derived_data_selected" and action in {"load_data_sheet", "use_pool_data"}:
        return {} if edit.data_path == tutorial._context().get("derived_data_path") else None
    return None


def _match_notice_editor(edit: Any, event: str, action: str, rows: dict) -> dict | None:
    if event == "notice_mapping_confirmed" and action in {"set_confirmed", "confirm_suggested"}:
        return {} if _notice_mapping(rows) else None
    if event == "notice_pattern_set" and action == "set_pattern":
        return {} if edit.pattern == "구매입찰공고-{{입찰공고번호}}" else None
    return None


def _match_contract_editor(event: str, action: str, rows: dict) -> dict | None:
    if event == "contract_mapping_set" and action in {"set_source", "set_confirmed"}:
        row = rows.get("대표계약업체")
        return {} if _contract_mapping_set(row) else None
    if event == "contract_currency_set" and action == "set_display":
        row = rows.get("계약보증금")
        return {} if row and row.type == "amount" and row.fmt == "" else None
    return None


def _contract_mapping_set(row: Any) -> bool:
    return bool(row and row.source == "계약상대자" and row.confirmed)


def _match_purchase_editor(edit: Any, event: str, action: str, rows: dict) -> dict | None:
    if event == "purchase_slice_set" and action == "set_slice":
        return {} if _purchase_slice_set(edit, rows.get("군품명")) else None
    if event == "purchase_formats_checked" and action in {"set_display", "step_preview"}:
        return {} if _purchase_formats_checked(rows) else None
    return None


def _purchase_slice_set(edit: Any, row: Any) -> bool:
    sample = edit.records[0] if edit.records else None
    return bool(row and row.source == "군품명" and row.slice is not None
                and sample and row.to_mapping().value_for(sample) == "드릴")


def _purchase_formats_checked(rows: dict) -> bool:
    return any(row.type == "date" for row in rows.values()) and any(row.type == "amount" for row in rows.values())
