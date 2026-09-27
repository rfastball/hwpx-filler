"""Filesystem effects for the template library."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable

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

    def remove(self, media: str, path: Path) -> None:
        """파일 하나를 **지운다** — 휴지통을 만들지 않는다(U6 §2.3).

        루트가 사용자 폴더가 되면서 앱이 거기에 ``.trash`` 를 짓는 일이 폐기됐다: 앱은 읽기와
        제자리 변환만 하고, 삭제 동사는 「폴더에서 보기」가 대신한다. 남은 유일한 호출자는
        동결 온보딩의 예제 제거(:func:`~hwpxfiller.external.example_pack.remove`)이고, 거기서
        되돌리기는 재설치라 잃는 원본이 없다(데이터 갈래가 이미 같은 규율로 ``unlink`` 한다).
        """
        self._root_for(media)  # 매체 열거 검증(오타는 시끄럽게)
        path.unlink()
