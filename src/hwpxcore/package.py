"""HWPX 컨테이너(OCF ZIP) 열기/저장.

HWPX 는 EPUB/ODF 계열 OCF 패키지다. 규칙:
  - `mimetype` 엔트리는 반드시 아카이브의 첫 항목이며 무압축(STORED)으로 저장된다.
  - 나머지 엔트리는 DEFLATE 로 압축한다.
  - 이미 압축된 바이너리(png 등)는 원본 압축 방식을 유지하는 편이 안전하다.

읽기에서는 실제 한컴 산출물과의 호환성을 위해 첫 `mimetype`의 DEFLATED만 허용하되,
다시 저장할 때는 반드시 STORED로 정규화한다. 값과 순서는 완화하지 않는다.

기존 VBA 구현은 PowerShell 경유 .NET ``ZipFile.CreateFromDirectory`` 를 써서 이
순서·무압축 규칙을 보장하지 못했다(한컴 뷰어가 관대해 통과했을 뿐). 여기서는
바이트 단위로 정확히 재구성한다.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from .atomic import write_bytes_atomic

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
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            cls._validate_archive_infos(infos)

            # ``mimetype`` 값도 나머지 payload를 읽기 전에 확인한다. 구조 검증을
            # 마친 ZipInfo 자체로 읽어 duplicate-name lookup의 모호성을 피한다.
            if zf.read(infos[0]) != MIMETYPE_VALUE:
                raise ValueError("유효한 HWPX 가 아닙니다: 잘못된 mimetype 값")

            entries: "dict[str, bytes]" = {}
            stored: "set[str]" = set()
            for info in infos:
                entries[info.filename] = zf.read(info)
                if info.compress_type == zipfile.ZIP_STORED:
                    stored.add(info.filename)
        pkg = cls(entries=entries, stored=stored)
        pkg._validate()
        return pkg

    @classmethod
    def from_bytes(cls, blob: bytes) -> "HwpxPackage":
        return cls.open(io.BytesIO(blob))  # type: ignore[arg-type]

    @classmethod
    def _validate_archive_infos(cls, infos: "list[zipfile.ZipInfo]") -> None:
        """ZIP central directory를 payload 처리 전에 fail-closed 검증한다."""
        names = [info.filename for info in infos]
        if MIMETYPE_NAME not in names:
            raise ValueError("유효한 HWPX 가 아닙니다: mimetype 엔트리 없음")
        if names[0] != MIMETYPE_NAME:
            raise ValueError("유효한 HWPX 가 아닙니다: mimetype 엔트리가 첫 항목이 아님")

        seen: "set[str]" = set()
        for info in infos:
            name = info.filename
            if name in seen:
                raise ValueError(f"유효한 HWPX 가 아닙니다: 중복 ZIP 엔트리 {name!r}")
            seen.add(name)
            cls._validate_entry_name(name)

    @staticmethod
    def _validate_entry_name(name: str) -> None:
        """추출 여부와 무관하게 위험한 ZIP member 이름을 입력 경계에서 거절한다."""
        if not name:
            raise ValueError("유효한 HWPX 가 아닙니다: 빈 ZIP 엔트리 이름")
        if "\\" in name:
            raise ValueError(f"유효한 HWPX 가 아닙니다: 역슬래시 ZIP 경로 {name!r}")
        windows_drive_path = len(name) >= 2 and name[0].isalpha() and name[1] == ":"
        if name.startswith("/") or windows_drive_path:
            raise ValueError(f"유효한 HWPX 가 아닙니다: 절대 ZIP 경로 {name!r}")
        if ".." in name.split("/"):
            raise ValueError(f"유효한 HWPX 가 아닙니다: 상위 경로 ZIP 엔트리 {name!r}")

    def _validate(self) -> None:
        if MIMETYPE_NAME not in self.entries:
            raise ValueError("유효한 HWPX 가 아닙니다: mimetype 엔트리 없음")
        if self.entries[MIMETYPE_NAME] != MIMETYPE_VALUE:
            raise ValueError("유효한 HWPX 가 아닙니다: 잘못된 mimetype 값")
        for name in self.entries:
            self._validate_entry_name(name)

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
        # 페이로드를 **먼저** 완성한다 — 직렬화 실패·쓰기 중단이 기존 파일을 파괴하지
        # 않도록(선평가 + 임시 파일 원자 교체, RC-01).
        write_bytes_atomic(path, self.to_bytes())

    def to_bytes(self) -> bytes:
        self._validate()
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
