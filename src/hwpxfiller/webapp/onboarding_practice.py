"""Practice workspace steps of the onboarding controller (#1126).

Free functions over :class:`~hwpxfiller.webapp.onboarding.OnboardingController`, the same shape
as :mod:`.onboarding_match_results`: seeding a lesson home, checking its files, and returning
the user to the screen the web left. The controller keeps ownership of state and persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..external.job_store import JobRegistry
from ..external.tutorial_practice import ORIGINALS, fingerprint
from ..viewmodel.tutorial_lessons import BY_ID
from .onboarding_seed import DERIVED, TXT_NAME, seed_after_switch, seed_before_switch

__all__ = ["NO_RETURN_SCREEN", "capture_return", "merge_practice_snapshot", "note_practice_save",
           "practice_resources", "restore_screen", "start_fresh", "transition_loss"]

NO_RETURN_SCREEN = "돌아갈 화면을 확인할 수 없습니다."

from ..external.tutorial_workspace import MODIFIED_REASON as _MODIFIED

_READY = "연습 파일 4건이 준비됐습니다."
_NOT_READY = "연습 파일이 준비되지 않았습니다. 예제로 시작하세요."
_EDITOR_LOSS = "저장하지 않은 작업 편집 내용이 사라집니다. 계속할까요?"
#: The window-close prompt's lead (``shell/app.ts``) with its condition taken off: the practice workspace a
#: transition replaces is about to leave memory, where the window-close guard could still have asked (#1130 review).
_PRACTICE_LOSS = "지금 연습의 다음 진행 상태가 사라집니다:"
_AUTHORING_LESSONS = {"field_trial", "option_apply", "change_apply"}


def practice_resources(tutorial: Any) -> tuple[bool, str]:
    """Are the current lesson's practice files the ones it seeded (or recorded saves of them)?"""
    if not tutorial.progress.selected:
        return False, "과정을 고르세요."
    ctx = tutorial._context()
    entries, home = ctx.get("assets"), ctx.get("home")
    if not isinstance(home, str) or not isinstance(entries, dict) or set(entries) != set(ORIGINALS):
        return False, _NOT_READY
    saved = ctx.get("saved_fingerprints", {})
    for entry in entries.values():
        ok, reason = _entry_ready(tutorial.workspace, entry, home, saved)
        if not ok:
            return False, reason
    if not _seeded_job_ready(ctx.get("job_name"), Path(home)):
        return False, _NOT_READY
    return _derived_ready(tutorial.workspace, ctx.get("derived_entry"), home)


def _seeded_job_ready(name: Any, home: Path) -> bool:
    """The lesson's seeded job (:mod:`.onboarding_seed`) still loads under the exact name its beats box."""
    if not name:
        return True
    try:
        job = JobRegistry(home / "jobs", template_root=lambda: home / "templates").load(name)
    except Exception:  # noqa: BLE001 — absent, damaged or unreadable is not ready, never a fallback
        return False
    return job.name == name


def transition_loss(tutorial: Any, screen: str, action: str, scenario: Any) -> str:
    """What a tutorial transition would discard, as its confirm text; empty when nothing is lost.

    Replacing the practice workspace drops its graph from memory, where the window-close guard could
    still have asked about it — so the practice controllers' own close-guard reasons are asked here.
    """
    lines = [_EDITOR_LOSS] if screen == "editor" and tutorial._editor().has_unsaved_work() else []
    reasons = _replaced_practice_reasons(tutorial, action, scenario)
    if reasons:
        lines.append("\n\n• ".join([_PRACTICE_LOSS, "\n• ".join(reasons)]))
    return "\n\n".join(lines)


def _replaced_practice_reasons(tutorial: Any, action: str, scenario: Any) -> list[str]:
    practice = getattr(tutorial.switch, "practice", None)
    if practice is None or action not in {"start", "select", "restart", "resume"}:
        return []
    if action != "restart" and _keeps_practice_home(tutorial, action, scenario, practice.home):
        return []
    reasons = (getattr(controller, "close_guard_reason", lambda: "")()
               for controller in practice.controllers.values())
    return [reason for reason in reasons if reason]


def _keeps_practice_home(tutorial: Any, action: str, scenario: Any, home: Path) -> bool:
    """Would this start/select/resume re-enter the practice home already in memory (``_select``/``_resume``)?"""
    lesson = tutorial.progress.selected if action == "resume" else scenario
    if lesson not in BY_ID:
        return False
    record = tutorial.progress.record(lesson)
    resumable = action == "resume" or 0 < record["checkpoint"] < len(BY_ID[lesson].beats)
    return resumable and record["context"].get("home") == str(home)


def note_practice_save(tutorial: Any, screen: str, action: str, result: Any) -> None:
    """A save of the open practice TXT is the user's own edit: its new digest stays valid."""
    if (tutorial.progress.selected not in _AUTHORING_LESSONS or screen != "authoring"
            or action not in {"save", "save_authoring_document"}
            or not isinstance(result, dict) or result.get("ok") is not True):
        return
    path = result.get("path")
    authoring = tutorial.controllers["authoring"]
    session = authoring.sessions.get(authoring.active_id)
    if (isinstance(path, str) and path == tutorial._asset(TXT_NAME)
            and session is not None and session.source_path == path):
        tutorial._context().setdefault("saved_fingerprints", {})[path] = fingerprint(Path(path))


def _entry_ready(workspace: Any, entry: dict, home: str, saved: dict) -> tuple[bool, str]:
    ok, reason = workspace.validate(entry, home)
    if ok or reason != _MODIFIED:
        return ok, reason
    # Saved authoring edits are allowed only if their exact new digest was recorded.
    path = Path(entry.get("path", ""))
    expected = saved.get(str(path))
    if expected and path.is_file() and not path.is_symlink() and fingerprint(path) == expected:
        return True, ""
    return False, reason


def _derived_ready(workspace: Any, derived_entry: Any, home: str) -> tuple[bool, str]:
    if derived_entry is None:
        return True, _READY
    if not isinstance(derived_entry, dict):
        return False, "다른 연습 데이터 기록을 확인할 수 없습니다."
    valid, reason = workspace.validate(derived_entry, home)
    return (True, _READY) if valid else (False, reason)


def start_fresh(tutorial: Any, lesson_id: str) -> None:
    """Seed a new lesson home with this lesson's preconditions and switch to it."""
    tutorial.progress.restart(lesson_id)
    derived, derived_name, derived_sheet = DERIVED.get(lesson_id, ("", "", ""))
    seeded = tutorial.workspace.seed(lesson_id, derived=derived, derived_name=derived_name)
    ctx = tutorial._context()
    ctx.clear()
    ctx.update(home=seeded["home"], batch=seeded["batch"], assets=seeded["assets"])
    if seeded["derived_entry"] is not None:
        ctx.update(derived_entry=seeded["derived_entry"],
                   derived_data_path=seeded["derived_entry"]["path"], derived_sheet=derived_sheet)
    seed_before_switch(tutorial, lesson_id, Path(seeded["home"]))
    tutorial.switch.enter(Path(seeded["home"]))
    try:
        seed_after_switch(tutorial, lesson_id)
    except BaseException:
        # A half-seeded lesson is never left active: the window returns to the user's workspace.
        tutorial.switch.leave()
        tutorial._return_context = None
        raise
    tutorial.workspace.sweep(lesson_id, seeded["home"])


def capture_return(tutorial: Any, screen: str) -> dict:
    """Only the screen the web is about to leave; the user's workspace stays in memory."""
    return {"screen": screen,
            "editor_job": tutorial._editor().edit.base.name if tutorial._editor().edit.base else "",
            "authoring_id": tutorial.controllers["authoring"].active_id,
            "workbench_row": (tutorial._workbench().snapshot().get("card") or {}).get("source_row")}


def restore_screen(tutorial: Any, original: dict) -> tuple[str, str]:
    """Reopen the screen the web left; data, rows and job selection were never touched.

    Called after the switch is already back in the user's workspace: a screen that cannot
    reopen (e.g. its job was deleted meanwhile) lands on the library with that said, never
    on a failed exit that would keep the practice badge over the user's real data.
    """
    try:
        return _reopen_screen(tutorial, original)
    except (ValueError, OSError, KeyError):
        return "library", NO_RETURN_SCREEN


def _reopen_screen(tutorial: Any, original: dict) -> tuple[str, str]:
    screen = original["screen"]
    if screen == "editor" and original["editor_job"]:
        tutorial._editor().load_job(original["editor_job"])
    elif screen == "editor":
        screen = "job" if tutorial._job().work.name else "library"
    elif screen == "authoring" and original["authoring_id"]:
        tutorial.controllers["authoring"].dispatch("activate", {"session_id": original["authoring_id"]})
    elif screen == "workbench":
        return _reopen_workbench(tutorial, original["workbench_row"])
    return screen, ""


def _reopen_workbench(tutorial: Any, row) -> tuple[str, str]:
    opened = tutorial._job().dispatch("open_workbench", {})
    if opened.get("ok") is not True:
        return "job", opened.get("error") or ""
    card = tutorial._workbench().snapshot().get("card") or {}
    index = next((item["index"] for item in card.get("index_map", []) if item["row"] == row), None)
    if index is not None:
        tutorial._workbench().dispatch("set_current", {"index": index})
    return "workbench", ""


def merge_practice_snapshot(tutorial: Any, snap: dict) -> None:
    """Fold the live practice zone and the entry-visible override (#1147) into one snapshot.

    The HUD stays up mid-practice even with the settings toggle off; only the first-launch
    invitation (``snap["entry"]`` set before this call) stays toggle-only.
    """
    practice_active = tutorial._return_context is not None
    snap["practice"] = {"active": practice_active,
                        "return_screen": tutorial._return_context.get("screen") if practice_active else None}
    snap["entry"]["visible"] = snap["entry"]["visible"] or practice_active
