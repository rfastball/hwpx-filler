"""Guidance projection and UI-fact observation of the onboarding controller (#1127).

Free functions over :class:`~hwpxfiller.webapp.onboarding.OnboardingController`, the same shape
as :mod:`.onboarding_practice`. One beat is one boxed control: its text, its box and its screen
come from the curriculum alone. Nothing here substitutes another beat's text or moves the box
between screens; a lost box only offers the existing way back to the beat's own screen.
"""

from __future__ import annotations

from typing import Any

from ..viewmodel.tutorial_lessons import BY_ID, UI_PRESS_EVENTS
from .onboarding_match_authoring import guide_range, practice_template_open

__all__ = ["advance_current", "guide_beat", "picker_hint", "observe_ui_press", "rewind_unmet_inputs",
           "rewind_unopened_template"]

#: The first beat of opening the practice TXT from the template list (``tutorial_lessons._open_template``).
_OPEN_TEMPLATE = "open_list"

#: Editor inputs later editor beats stand on: (template file, data sheet). The beats that choose
#: them are ``template`` and ``data`` in both lessons.
_EDITOR_INPUTS = {
    "first_hwpx": ("물품 구매입찰 공고.hwpx", "공고"),
    "contract_txt": ("낙찰자 선정 및 계약체결 안내.txt", "계약"),
}


def guide_beat(tutorial: Any, beat: dict) -> None:
    """Resolve what the curriculum names symbolically: seeded pool keys, and the text range a range beat paints
    on the open practice document (``range``; the web only draws it)."""
    arg = beat.get("arg") or ""
    if arg.startswith("pool:"):
        beat["arg"] = tutorial._context().get("pool_keys", {}).get(arg[len("pool:"):], "")
    if beat.get("target") == "authoring-range":
        current = tutorial.progress.beat()
        beat["range"] = guide_range(tutorial, current.event if current else None)


def picker_hint(tutorial: Any, kind: str, screen: str) -> str:
    """The practice file the current beat asks for; the native picker still accepts any file."""
    beat = tutorial.progress.beat()
    if beat is None or (screen and screen != beat.screen):
        return ""
    if kind == "data" and beat.event == "data_file_picked":
        return tutorial._context().get("derived_data_path", "")
    return ""


def observe_ui_press(tutorial: Any, payload: dict) -> bool:
    """The web reports only that the current beat's own boxed control was pressed.

    Whether that completes the beat is decided here: the report must name the selected lesson,
    the current checkpoint and the current beat's anchor, and that beat must be one whose press
    runs no product command (:data:`UI_PRESS_EVENTS`). Anything else is ignored.
    """
    progress = tutorial.progress
    beat = progress.beat()
    if (not progress.active or beat is None or beat.event not in UI_PRESS_EVENTS
            or payload.get("scenario_id") != progress.selected
            or payload.get("checkpoint") != progress.record(progress.selected)["checkpoint"]
            or payload.get("anchor") != beat.target):
        return False
    return progress.observed(beat.event)


def advance_current(tutorial: Any, screen: str, action: str, payload: dict, result: Any) -> bool:
    """One returned product command completes at most the current beat: no beat passes unseen."""
    beat = tutorial.progress.beat()
    event = beat.event if beat is not None else None
    if event is None or event in UI_PRESS_EVENTS:
        return False
    context = tutorial._matches(event, screen, action, payload, result)
    return context is not None and tutorial.progress.observed(event, context=context)


def rewind_unopened_template(tutorial: Any) -> bool:
    """Back to opening the practice TXT once a template-authoring beat stands without it (#1146).

    A lesson resumed after a restart, or a closed tab, leaves the authoring beats with no document to act on;
    the user then opens it again the way the lesson taught instead of facing a beat that cannot pass.
    """
    progress = tutorial.progress
    beat = progress.beat()
    if beat is None or beat.screen != "authoring" or practice_template_open(tutorial):
        return False
    lesson = BY_ID[progress.selected]
    return any(item.id == _OPEN_TEMPLATE for item in lesson.beats) and progress.rewind(_OPEN_TEMPLATE)


def rewind_unmet_inputs(tutorial: Any) -> bool:
    """Back to the beat that chose the editor's template or data once it no longer holds.

    The beat shown is then that earlier beat with its own text and box — never a later beat's
    progress number over an earlier beat's words.
    """
    progress = tutorial.progress
    lesson, beat = progress.selected, progress.beat()
    inputs = _EDITOR_INPUTS.get(lesson or "")
    if inputs is None or beat is None or beat.screen != "editor":
        return False
    template, sheet = inputs
    edit = tutorial._editor().edit
    if edit.template_path != tutorial._asset(template):
        return progress.rewind("template")
    if edit.data_path != tutorial._asset("공고목록.xlsx") or edit.data_sheet != sheet:
        return progress.rewind("data")
    return False

