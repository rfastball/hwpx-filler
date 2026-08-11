"""Filesystem effects for the template library."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable

from ..domain.template_status import TRASH_DIR_NAME
from .atomic import write_text_atomic
from .text_registry import TextTemplateRegistry


class TemplateFileStore:
    def __init__(
        self,
        hwpx_root: "str | Path",
        text_registry: TextTemplateRegistry,
        *,
        clock: "Callable[[], float]",
        new_id: "Callable[[], str]",
    ) -> None:
        self.hwpx_root = Path(hwpx_root)
        self.text_registry = text_registry
        self._clock = clock
        self._new_id = new_id
        self.import_lock = threading.Lock()
        self.hwpx_write_lock = threading.RLock()

    def _root_for(self, suffix_or_media: str) -> Path:
        if suffix_or_media in (".hwpx", "hwpx"):
            return self.hwpx_root
        if suffix_or_media in (".txt", "txt"):
            return self.text_registry.directory
        raise ValueError("가져올 수 있는 형식은 .hwpx 또는 .txt 입니다.")

    def folder_candidates(self, folder: "str | Path") -> "tuple[Path, list[Path], int, bool]":
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"폴더를 찾을 수 없습니다: {folder}")
        entries = list(root.iterdir())
        files = sorted((p for p in entries if p.is_file()), key=lambda p: p.name.casefold())
        candidates = [p for p in files if p.suffix.lower() in (".hwpx", ".txt")]
        return root, candidates, len(files) - len(candidates), any(p.is_dir() for p in entries)

    def import_dest_taken(self, src: Path) -> bool:
        return (self._root_for(src.suffix.lower()) / src.name).exists()

    def copy_into_library(self, src: Path) -> Path:
        root = self._root_for(src.suffix.lower())
        root.mkdir(parents=True, exist_ok=True)
        writer = (
            self.text_registry.write_lock()
            if src.suffix.lower() == ".txt"
            else self.hwpx_write_lock
        )
        with self.import_lock, writer:
            dest = root / src.name
            number = 2
            while dest.exists():
                dest = root / f"{src.stem} ({number}){src.suffix}"
                number += 1
            try:
                shutil.copy2(src, dest)
            except Exception:
                dest.unlink(missing_ok=True)
                raise
        return dest

    @staticmethod
    def source_file_exists(path: Path) -> bool:
        return path.is_file()

    def trash(self, media: str, path: Path) -> Path:
        root = self._root_for(media)
        trash = root / TRASH_DIR_NAME
        trash.mkdir(parents=True, exist_ok=True)
        cutoff = self._clock() - 30 * 24 * 60 * 60
        for old in trash.iterdir():
            try:
                if old.is_file() and old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                continue
        trashed = trash / f"{int(self._clock())}-{self._new_id()}-{path.name}"
        path.replace(trashed)
        return trashed

    def restore(
        self,
        media: str,
        path: Path,
        trashed: Path,
        after_restore: "Callable[[], None]",
    ) -> "str | None":
        writer = (
            self.text_registry.write_lock() if media == "txt" else self.hwpx_write_lock
        )
        with writer:
            if not trashed.exists():
                return "되돌릴 템플릿 파일을 찾을 수 없습니다."
            if path.exists():
                return "같은 이름의 템플릿이 이미 있어 복원할 수 없습니다."
            path.parent.mkdir(parents=True, exist_ok=True)
            trashed.replace(path)
            try:
                after_restore()
            except Exception:
                path.replace(trashed)
                raise
        return None

    def _require_live_txt(self, path: "str | Path") -> Path:
        target = Path(path).resolve()
        live = {template.path.resolve() for template in self.text_registry.list_templates()}
        if target not in live:
            raise ValueError("현재 TXT 라이브러리 목록에 없는 경로입니다.")
        return target

    def create_text(self, name: str, content: str) -> Path:
        path = self.text_registry.directory / f"{name}.txt"
        with self.text_registry.write_lock():
            if path.exists():
                raise ValueError(f"이미 같은 이름의 템플릿이 있습니다: {name}")
            self.text_registry.directory.mkdir(parents=True, exist_ok=True)
            write_text_atomic(str(path), content)
        return path

    def edit_text(self, path: "str | Path", content: str) -> Path:
        with self.text_registry.write_lock():
            target = self._require_live_txt(path)
            write_text_atomic(str(target), content)
        return target

    def read_text(self, path: "str | Path") -> str:
        return self._require_live_txt(path).read_text(encoding="utf-8")
