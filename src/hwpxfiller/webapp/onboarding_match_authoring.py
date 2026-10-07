"""Template-authoring observations of the practice TXT (lessons 7–9).

A text range is chosen in the browser, but every choice is asked to Python as ``locate`` /
``commands`` with its offsets, so the range beats are observed product queries: the matcher
reads which lines of the practice document the offsets cover.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..domain.template_authoring_primitives import from_utf16, to_utf16
from ..external.tutorial_practice import fingerprint
from .onboarding_match_editor import Matcher, Observation
from .onboarding_seed import applied_txt_path

__all__ = ["AUTHORING_MATCHERS", "guide_range", "practice_template_open"]

TXT = "낙찰자 선정 및 계약체결 안내.txt"
SLOT, INCLUDE, OMIT = "예산재배정", "안내포함", "안내생략"
_CLOSE_OPTION = "{{/선택}}\n"


def _practice_path(tutorial: Any) -> str:
    if tutorial.progress.selected != "change_apply":
        return tutorial._asset(TXT)
    return applied_txt_path(tutorial)


def _session(tutorial: Any, obs: Observation) -> Any:
    if obs.screen != "authoring" or not isinstance(obs.result, dict) or obs.result.get("ok") is False:
        return None
    authoring = tutorial.controllers["authoring"]
    session = authoring.sessions.get(authoring.active_id)
    if session is None or session.media != "txt" or session.source_path != _practice_path(tutorial):
        return None
    return session


def practice_template_open(tutorial: Any) -> bool:
    """The lesson's TXT is open in place: the listed template or the job's applied file."""
    authoring = tutorial.controllers["authoring"]
    session = authoring.sessions.get(authoring.active_id)
    return (session is not None and session.media == "txt" and session.source_path == _practice_path(tutorial)
            and session.save_path == session.source_path)


def _slots(session: Any) -> list:
    return session.analysis.get("slots", [])


def _options(session: Any) -> set:
    return {option.get("label") for slot in _slots(session) if slot.get("label") == SLOT
            for option in slot.get("options", [])}


# ------------------------------------------------------------------ opening the practice TXT
def _template_opened(tutorial: Any, obs: Observation) -> dict | None:
    """The current lesson's edit control opened its expected TXT for template authoring."""
    opened = obs.action == "open_authoring_document" and _session(tutorial, obs) is not None
    return {} if opened and practice_template_open(tutorial) else None


# ------------------------------------------------------------------ text ranges
def _range(tutorial: Any, obs: Observation) -> tuple[str, int, int] | None:
    session = _session(tutorial, obs) if obs.action in {"locate", "commands"} else None
    selection = obs.payload.get("selection")
    if session is None or not isinstance(selection, dict):
        return None
    text = session.content.decode("utf-8")
    try:  # the editor speaks UTF-16 units; the document is read in code points
        start, end = from_utf16(text, selection.get("start")), from_utf16(text, selection.get("end"))
    except ValueError:
        return None
    return (text, start, end) if start <= end else None


def _paragraph(text: str) -> tuple[int, int]:
    """Start and end (the newline) of paragraph 3."""
    begin = text.index("\n3. ") + 1 if "\n3. " in text else -1
    return begin, (text.index("\n", begin) if begin >= 0 else -1)


def _in_item(text: str, begin: int) -> bool:
    """Paragraph 3 sits directly inside the item (the line above is its opening marker), not in a choice."""
    return begin > 0 and text[:begin - 1].rsplit("\n", 1)[-1].startswith(f"{{{{#항목 {SLOT} ")


def _field_target(text: str) -> tuple[int, int] | None:
    at = text.find("10일")
    return (at, at + 3) if at >= 0 else None


def _item_target(text: str) -> tuple[int, int] | None:
    """Paragraph 3 and the empty line below it, up to the start of the second empty line."""
    begin, finish = _paragraph(text)
    return (begin, finish + 2) if begin >= 0 and text[finish:finish + 3] == "\n\n\n" else None


def _include_target(text: str) -> tuple[int, int] | None:
    begin, finish = _paragraph(text)
    return (begin, finish) if _in_item(text, begin) else None


def _omit_target(text: str) -> tuple[int, int] | None:
    if _CLOSE_OPTION not in text:
        return None
    blank = text.index(_CLOSE_OPTION) + len(_CLOSE_OPTION)
    return (blank, blank) if text[blank:].startswith("\n{{/항목}}") else None


#: The exact range each range beat asks for. The guide paints it on the editor and boxes it; the
#: matchers below accept a natural selection of it.
_TARGETS: dict[str, Callable[[str], tuple[int, int] | None]] = {
    "field_range_selected": _field_target,
    "item_range_selected": _item_target,
    "include_range_selected": _include_target,
    "omit_range_selected": _omit_target,
}


def guide_range(tutorial: Any, event: str | None) -> dict | None:
    """The current range beat's target in the open practice document, as editor (UTF-16) offsets."""
    target = _TARGETS.get(event or "")
    authoring = tutorial.controllers["authoring"]
    session = authoring.sessions.get(authoring.active_id)
    if target is None or session is None or session.media != "txt" or session.source_path != _practice_path(tutorial):
        return None
    text = session.content.decode("utf-8")
    found = target(text)
    return None if found is None else {"session_id": authoring.active_id,
                                       "start": to_utf16(text, found[0]), "end": to_utf16(text, found[1])}


def _field_range(tutorial: Any, obs: Observation) -> dict | None:
    picked = _range(tutorial, obs)
    return {} if picked and picked[0][picked[1]:picked[2]].strip() == "10일" else None


def _item_range(tutorial: Any, obs: Observation) -> dict | None:
    """A drag over the painted lines: from the paragraph's first character to anywhere on the second empty line
    below it (blanks on either end allowed). Stopping on the first empty line would leave it out of the item."""
    picked = _range(tutorial, obs)
    target = _item_target(picked[0]) if picked else None
    if picked is None or target is None:
        return None
    text, start, end = picked
    head, tail = text[target[0]:start], text[target[1]:end]
    return {} if (target[0] <= start and not head.strip() and "\n" not in head
                  and target[1] <= end and not tail.strip() and "\n" not in tail) else None


def _include_range(tutorial: Any, obs: Observation) -> dict | None:
    picked = _range(tutorial, obs)
    target = _include_target(picked[0]) if picked else None
    if picked is None or target is None:
        return None
    _text, start, end = picked
    return {} if target[0] <= start < end <= target[1] + 1 else None


def _omit_range(tutorial: Any, obs: Observation) -> dict | None:
    picked = _range(tutorial, obs)
    target = _omit_target(picked[0]) if picked else None
    if picked is None or target is None:
        return None
    _text, start, end = picked
    return {} if start == target[0] and end in {target[0], target[0] + 1} else None


# ------------------------------------------------------------------ structure
def _updated(tutorial: Any, obs: Observation) -> Any:
    return _session(tutorial, obs) if obs.action == "update" else None


def _field_created(tutorial: Any, obs: Observation) -> dict | None:
    session = _updated(tutorial, obs)
    fields = {field.get("name") for field in session.analysis.get("fields", [])} if session else set()
    return {} if "재배정기한" in fields and "10일" not in session.content.decode("utf-8") else None


def _item_created(tutorial: Any, obs: Observation) -> dict | None:
    session = _updated(tutorial, obs)
    return {} if session and any(slot.get("label") == SLOT for slot in _slots(session)) else None


def _option(labels: set) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        session = _updated(tutorial, obs)
        return {} if session and labels <= _options(session) else None
    return match


# ------------------------------------------------------------------ result trial
def _trial_report(tutorial: Any, obs: Observation) -> tuple[Any, dict] | None:
    session = _session(tutorial, obs) if obs.action == "trial" else None
    report = (obs.result.get("report") or {}) if session else {}
    if session is None or report.get("missing_fields") or report.get("errors"):
        return None
    return session, report


def _field_trial(tutorial: Any, obs: Observation) -> dict | None:
    passed = _trial_report(tutorial, obs)
    return {} if passed and not passed[1].get("empty_fields") and passed[0].values.get("재배정기한") else None


def _names_filled(tutorial: Any, obs: Observation) -> dict | None:
    return {} if obs.action == "trial_fill_names" and _session(tutorial, obs) is not None else None


def _tested(session: Any) -> set:
    slot = next((item for item in _slots(session) if item.get("label") == SLOT), None)
    labels = {option.get("id"): option.get("label") for option in (slot or {}).get("options", [])}
    return {labels.get(option) for (slot_id, option), (revision, _digest) in session.trial_coverage_evidence.items()
            if slot and slot_id == slot.get("id") and revision == session.revision}


def _trial_of(labels: set) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        passed = _trial_report(tutorial, obs)
        return {} if passed and labels <= _tested(passed[0]) and labels <= _options(passed[0]) else None
    return match


# ------------------------------------------------------------------ saving and applying
def _saved(finish: tuple[str, str]) -> Matcher:
    def match(tutorial: Any, obs: Observation) -> dict | None:
        session = _session(tutorial, obs) if obs.action in {"save", "save_authoring_document"} else None
        authoring = tutorial.controllers["authoring"]
        if session is None or obs.result.get("ok") is not True or authoring._readiness(session)["state"] != "ready":
            return None
        path = obs.result["path"]
        tutorial._context().setdefault("saved_fingerprints", {})[path] = fingerprint(Path(path))
        tutorial._finish_result(finish[0], finish[1], "authoring", "save-template", [], count=1)
        return {}
    return match


def _impact_opened(tutorial: Any, obs: Observation) -> dict | None:
    return {} if obs.action == "impact" and _session(tutorial, obs) is not None else None


def _apply_ready(tutorial: Any, obs: Observation) -> dict | None:
    job = tutorial._context().get("job_name")
    return {} if (obs.action == "prepare_apply" and _session(tutorial, obs) is not None and job
                  and obs.payload.get("job_name") == job and obs.result.get("change_token")) else None


def _applied(tutorial: Any, obs: Observation) -> dict | None:
    applied = (obs.action == "apply_job" and _session(tutorial, obs) is not None
               and obs.result.get("job_name") == tutorial._context().get("job_name") and obs.result.get("is_current") is True)
    return {"applied": True} if applied else None


AUTHORING_MATCHERS: dict[str, Matcher] = {
    "practice_template_opened": _template_opened,
    "field_range_selected": _field_range,
    "item_range_selected": _item_range,
    "include_range_selected": _include_range,
    "omit_range_selected": _omit_range,
    "practice_field_created": _field_created,
    "practice_item_created": _item_created,
    "option_created": _option({INCLUDE}),
    "practice_options_created": _option({INCLUDE, OMIT}),
    "field_trial_passed": _field_trial,
    "trial_names_filled": _names_filled,
    "option_trial_passed": _trial_of({INCLUDE}),
    "practice_both_trials_passed": _trial_of({INCLUDE, OMIT}),
    "field_practice_saved": _saved(("내 필드 준비 완료", "재배정기한 필드를 시험하고 사용 준비 상태로 저장했습니다.")),
    "option_practice_saved": _saved(("항목과 선택 준비 완료", "두 선택을 시험하고 서식을 저장했습니다.")),
    "impact_tab_opened": _impact_opened,
    "prepare_apply_ready": _apply_ready,
    "option_change_applied": _applied,
}
