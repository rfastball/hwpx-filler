"""Pure identity rules for text templates."""

from __future__ import annotations

from pathlib import Path

from .template_status import (
    OUTPUT_SUBDIR_NAME,
    TRASH_DIR_NAME,
    library_display_name,
)

TEXT_TEMPLATE_SUFFIX = ".txt"

#: 재귀 나열에서 건너뛰는 하위트리 이름 — 산출물(``Results``)과 삭제 보관소(``.trash``).
#: hwpx 스캐너(:meth:`~hwpxfiller.gui.template_manager_state.TemplateManagerViewModel._discover`)
#: 와 **같은 목록**이어야 한다: U6-A 이후 두 매체가 사용자가 고른 같은 루트를 읽으므로,
#: 한쪽만 산출물 폴더를 거르면 실행할수록 TXT 목록이 완성 문서로 오염된다.
EXCLUDED_DIR_NAMES = (TRASH_DIR_NAME, OUTPUT_SUBDIR_NAME)


def text_template_name(root: Path, path: Path) -> str:
    """TXT 항목의 표시명 — hwpx 와 **같은 규칙**이다(U6-A: `library_display_name` 위임)."""
    return library_display_name(root, path)


def is_live_text_template(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    return (
        path.suffix.lower() == TEXT_TEMPLATE_SUFFIX
        and not any(name in relative.parts for name in EXCLUDED_DIR_NAMES)
    )


def text_template_path(root: Path, name: str) -> Path:
    return root / f"{name}{TEXT_TEMPLATE_SUFFIX}"
