"""Pure identity rules for text templates."""

from __future__ import annotations

from pathlib import Path

from .template_status import TRASH_DIR_NAME

TEXT_TEMPLATE_SUFFIX = ".txt"


def text_template_name(root: Path, path: Path) -> str:
    return path.relative_to(root).with_suffix("").as_posix()


def is_live_text_template(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    return (
        path.suffix.lower() == TEXT_TEMPLATE_SUFFIX
        and TRASH_DIR_NAME not in relative.parts
    )


def text_template_path(root: Path, name: str) -> Path:
    return root / f"{name}{TEXT_TEMPLATE_SUFFIX}"
