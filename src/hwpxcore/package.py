"""HWPX 컨테이너(OCF ZIP) 열기/저장.

HWPX 는 EPUB/ODF 계열 OCF 패키지다. 규칙:
  - `mimetype` 엔트리는 반드시 아카이브의 첫 항목이며 무압축(STORED)으로 저장된다.
  - 나머지 엔트리는 DEFLATE 로 압축한다.
  - 이미 압축된 바이너리(png 등)는 원본 압축 방식을 유지하는 편이 안전하다.

기존 VBA 구현은 PowerShell 경유 .NET ``ZipFile.CreateFromDirectory`` 를 써서 이
순서·무압축 규칙을 보장하지 못했다(한컴 뷰어가 관대해 통과했을 뿐). 여기서는
바이트 단위로 정확히 재구성한다.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

MIMETYPE_NAME = "mimetype"
MIMETYPE_VALUE = b"application/hwp+zip"


@dataclass
class HwpxPackage:
    """메모리에 적재된 HWPX 아카이브.

    엔트리 이름 -> 바이트. 순서를 보존해 원본 레이아웃을 최대한 유지한다.
    """

    entries: "dict[str, bytes]" = field(default_factory=dict)
    # 원본에서 STORED(무압축)였던 엔트리 이름 집합 — 저장 시 그대로 재현.
    stored: "set[str]" = field(default_factory=set)

    # ------------------------------------------------------------------ load
    @classmethod
    def open(cls, path: str) -> "HwpxPackage":
        pkg = cls()
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                pkg.entries[info.filename] = zf.read(info.filename)
                if info.compress_type == zipfile.ZIP_STORED:
                    pkg.stored.add(info.filename)
        pkg._validate()
        return pkg

    @classmethod
    def from_bytes(cls, blob: bytes) -> "HwpxPackage":
        return cls.open(io.BytesIO(blob))  # type: ignore[arg-type]

    def _validate(self) -> None:
        if MIMETYPE_NAME not in self.entries:
            raise ValueError("유효한 HWPX 가 아닙니다: mimetype 엔트리 없음")

    # -------------------------------------------------------------- accessors
    def content_xml_names(self) -> "list[str]":
        """필드 주입 대상 XML 목록 (section*/header*/footer*, Contents/ 하위)."""
        out = []
        for name in self.entries:
            low = name.lower()
            base = low.rsplit("/", 1)[-1]
            if base.endswith(".xml") and (
                base.startswith("section")
                or base.startswith("header")
                or base.startswith("footer")
            ):
                out.append(name)
        return out

    # ------------------------------------------------------------------ save
    def save(self, path: str) -> None:
        with open(path, "wb") as fh:
            fh.write(self.to_bytes())

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # 1) mimetype 을 항상 첫 항목 + STORED 로.
            self._write_entry(zf, MIMETYPE_NAME, self.entries[MIMETYPE_NAME], stored=True)
            # 2) 나머지는 원래 순서대로.
            for name, data in self.entries.items():
                if name == MIMETYPE_NAME:
                    continue
                self._write_entry(zf, name, data, stored=name in self.stored)
        return buf.getvalue()

    @staticmethod
    def _write_entry(zf: zipfile.ZipFile, name: str, data: bytes, *, stored: bool) -> None:
        ctype = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
        info = zipfile.ZipInfo(name)
        info.compress_type = ctype
        # HWPX 내부는 UTF-8 파일명; 외부 속성/시간은 기본값으로 둔다(재현성 위해 고정).
        info.date_time = (1980, 1, 1, 0, 0, 0)
        zf.writestr(info, data)
