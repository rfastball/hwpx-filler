"""Filesystem effects for the template library."""

from __future__ import annotations

import hashlib
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .atomic import write_text_atomic
from .text_registry import TextTemplateRegistry


@dataclass(frozen=True)
class TextEditDrift:
    """「편집 창이 열린 사이 파일이 밖에서 바뀌었다」는 판정 — 쓰지 않고 되돌린 결과.

    :attr:`fingerprint` 는 **거절 시점 디스크 내용**의 지문이다. 호출자는 이 값을 사용자
    확인과 함께 되싣고(:meth:`TemplateFileStore.edit_text` 의 ``confirm_fingerprint``),
    그 사이 또 바뀌었으면 지문이 어긋나 다시 막힌다 — 사용자가 읽고 확정한 문안과 실제로
    덮이는 상태가 갈라지지 않는다(#216 이월 2 · screen_editor ``_overwrite_gate`` 동형).
    """

    fingerprint: str


def _content_fingerprint(content: str) -> str:
    """TXT 원문 지문 — 확인 왕복이 「그때 본 그 상태」를 지목하는 단일 형식."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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

    def _require_live_txt(self, path: "str | Path") -> Path:
        root = self.text_registry.directory.resolve()
        target = Path(path).resolve()
        for template in self.text_registry.list_templates():
            candidate = template.path
            if candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if resolved.is_relative_to(root) and resolved == target:
                return candidate
        raise ValueError("현재 TXT 라이브러리 목록에 없는 경로입니다.")

    def create_text(self, name: str, content: str) -> Path:
        path = self.text_registry.directory / f"{name}.txt"
        with self.text_registry.write_lock():
            if path.exists():
                raise ValueError(f"이미 같은 이름의 템플릿이 있습니다: {name}")
            self.text_registry.directory.mkdir(parents=True, exist_ok=True)
            write_text_atomic(str(path), content)
        return path

    def edit_text(
        self,
        path: "str | Path",
        content: str,
        *,
        baseline: str,
        confirm_fingerprint: str = "",
    ) -> "Path | TextEditDrift":
        """기존 TXT 템플릿 덮어쓰기 — **드리프트 판정~쓰기가 한 임계구역**(#216 이월 2).

        ``baseline`` 은 편집 창이 열릴 때 읽은 원문이다. 디스크가 그것과 다르면 편집 창이
        열린 사이 밖에서 바뀌었다는 뜻이고, 그대로 쓰면 그 변경을 **조용히** 지운다 —
        :class:`TextEditDrift` 로 되돌려 확인 왕복을 강제한다. 사용자가 그 상태를 보고
        확정하면 같은 지문을 ``confirm_fingerprint`` 로 되싣고, 그 사이 또 바뀌었으면
        지문이 어긋나 다시 막힌다.

        판정을 잠금 **밖**에서 먼저 내리지 않는다(screen_editor ``_save_locked`` #149 규율
        동형): 읽은 상태와 실제로 덮는 상태가 갈라지면 사용자가 읽고 확정한 문안이 실제로
        일어난 일과 달라진다 — 이 저장소의 지배 결함류다.
        """
        with self.text_registry.write_lock():
            target = self._require_live_txt(path)
            current = target.read_text(encoding="utf-8")
            if current != baseline:
                fingerprint = _content_fingerprint(current)
                if confirm_fingerprint != fingerprint:
                    return TextEditDrift(fingerprint)
            write_text_atomic(str(target), content)
        return target

    def read_text(self, path: "str | Path") -> str:
        return self._require_live_txt(path).read_text(encoding="utf-8")
