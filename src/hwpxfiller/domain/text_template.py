"""Pure identity rules for text templates."""

from __future__ import annotations

from pathlib import Path

from .template_status import is_excluded_subtree, library_display_name

TEXT_TEMPLATE_SUFFIX = ".txt"


def text_template_name(root: Path, path: Path) -> str:
    """TXT 항목의 표시명 — hwpx 와 **같은 규칙**이다(U6-A: `library_display_name` 위임)."""
    return library_display_name(root, path)


def is_live_text_template(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    return (
        path.suffix.lower() == TEXT_TEMPLATE_SUFFIX
        and not is_excluded_subtree(relative.parts)
    )


def text_template_path(root: Path, name: str) -> Path:
    return root / f"{name}{TEXT_TEMPLATE_SUFFIX}"
