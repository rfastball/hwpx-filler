"""Filesystem effects for the template library."""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable

from ..domain.copy_name import first_free, numbered_file_name
from .text_registry import TextTemplateRegistry


class TemplateFileStore:
    def __init__(
        self,
        root: "Callable[[], Path]",
        text_registry: TextTemplateRegistry,
    ) -> None:
        # 루트는 **콜러블 하나**다(U6-A #975): hwpx·txt 가 사용자가 고른 같은 서식 폴더를
        # 쓰므로 매체별 루트를 들 자리가 없어졌고, 설정으로 바뀌는 값이라 Path 를 굳혀 들면
        # 재지정 뒤에도 옛 폴더에 복사한다(선언≠실제).
        self._root = root
        self.text_registry = text_registry
        self.import_lock = threading.Lock()
        self.hwpx_write_lock = threading.RLock()

    def _root_for(self, suffix_or_media: str) -> Path:
        """매체를 검증하고 **같은** 루트를 돌려준다 — 라우팅 축은 U6-A 에서 사라졌다."""
        if suffix_or_media in (".hwpx", "hwpx", ".txt", "txt"):
            return self._root()
        raise ValueError("가져올 수 있는 형식은 .hwpx 또는 .txt 입니다.")

    def _writer(self, suffix: str):
        return self.text_registry.write_lock() if suffix == ".txt" else self.hwpx_write_lock

    @staticmethod
    def _free_destination(root: Path, name: str) -> Path:
        """``name`` 이 비었으면 그대로, 있으면 ``이름 (2).ext``… — 덮어쓰지 않는다."""
        return root / first_free(
            lambda number: numbered_file_name(name, number),
            lambda candidate: (root / candidate).exists(),
        )

    def copy_into_library(self, src: Path) -> Path:
        root = self._root_for(src.suffix.lower())
        root.mkdir(parents=True, exist_ok=True)
        with self.import_lock, self._writer(src.suffix.lower()):
            dest = self._free_destination(root, src.name)
            try:
                shutil.copy2(src, dest)
            except Exception:
                dest.unlink(missing_ok=True)
                raise
        return dest

    def add_bytes(self, name: str, blob: bytes) -> Path:
        """bytes 를 서식 폴더에 **새 파일**로 들인다 — 이름이 있으면 사본 이름으로 비켜 간다.

        작업 꾸러미 불러오기의 몸통이다. 임시 파일에 다 쓴 뒤 이름을 붙이므로 중간 실패가 반쪽
        파일을 남기지 않는다. 이름 붙이기는 :func:`os.rename` 이라 Windows 에서 같은 이름이 그사이
        생겼으면 덮지 않고 실패한다(잠금 안의 존재 확인과 이중으로 막는다).
        """
        suffix = Path(name).suffix.lower()
        root = self._root_for(suffix)
        root.mkdir(parents=True, exist_ok=True)
        with self.import_lock, self._writer(suffix):
            dest = self._free_destination(root, name)
            pending = root / f".{dest.name}.{uuid.uuid4().hex}.tmp"
            try:
                pending.write_bytes(blob)
                os.rename(pending, dest)
            finally:
                pending.unlink(missing_ok=True)
        return dest

    @staticmethod
    def source_file_exists(path: Path) -> bool:
        return path.is_file()

    def remove(self, media: str, path: Path) -> None:
        """파일 하나를 **지운다** — 휴지통을 만들지 않는다(U6 §2.3).

        루트가 사용자 폴더가 되면서 앱이 거기에 ``.trash`` 를 짓는 일이 폐기됐다: 앱은 읽기와
        제자리 변환만 하고, 삭제 동사는 「폴더에서 보기」가 대신한다. 남은 유일한 호출자는
        동결 온보딩의 예제 제거(:func:`~hwpxfiller.external.example_pack.remove`)이고, 거기서
        되돌리기는 재설치라 잃는 원본이 없다(데이터 갈래가 이미 같은 규율로 ``unlink`` 한다).
        """
        self._root_for(media)  # 매체 열거 검증(오타는 시끄럽게)
        path.unlink()
