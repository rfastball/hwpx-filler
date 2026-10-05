"""Settings-backed lifecycle actions of the onboarding controller (#1147).

Free functions over :class:`~hwpxfiller.webapp.onboarding.OnboardingController`, the same shape
as :mod:`.onboarding_practice`. Both replace or mutate ``tutorial.progress`` from a payload the
dispatch gate already validated; persistence/typing rejection is settings.py's own
confirm-or-alarm (no duplicate check here — a second check would add a second user sentence).
"""

from __future__ import annotations

from typing import Any, cast

from ..external import settings
from ..viewmodel.tutorial_lessons import LessonProgress

__all__ = ["reset_progress", "set_entry_visible"]


def reset_progress(tutorial: Any, payload: dict) -> None:
    """Wipe learning position/history; the entry-visible toggle is a settings value, not progress."""
    if payload.get("confirm") is not True:
        raise ValueError("모든 학습 기록을 지울지 확인하세요.")
    entry_visible = tutorial.progress.entry_visible
    tutorial.progress = LessonProgress({"version": 1, "invite_seen": True})
    tutorial.progress.entry_visible = entry_visible
    tutorial._recovery = None


def set_entry_visible(tutorial: Any, payload: dict) -> None:
    """Persist the HUD/invitation toggle and mirror it onto the live progress view."""
    visible = cast(bool, payload.get("visible"))  # pyright-only; settings rejects a non-bool
    settings.save_tutorial_entry_visible(visible)
    tutorial.progress.entry_visible = visible
