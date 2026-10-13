"""Content-selection facts consumed by the document-creation workbench."""

from __future__ import annotations

from dataclasses import dataclass

from .document_creation_vocabulary import BLOCKER_CODES

REPAIR_TEMPLATE = BLOCKER_CODES[5]
CHOOSE_CONTENT = BLOCKER_CODES[6]


@dataclass(frozen=True)
class ContentSelectionSummary:
    """Backend-projected choices and whether selection or template repair is needed."""

    selected_option_ids: tuple[str, ...] = ()
    has_unselected_required_content: bool = False
    requires_template_repair: bool = False


def content_selection_blockers(summary: ContentSelectionSummary) -> tuple[str, ...]:
    """Map already-projected content facts to their distinct recovery verbs."""
    return tuple(
        code for needed, code in (
            (summary.has_unselected_required_content, CHOOSE_CONTENT),
            (summary.requires_template_repair, REPAIR_TEMPLATE),
        ) if needed
    )
