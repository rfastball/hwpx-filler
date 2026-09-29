"""HWPX 컨테이너(OCF ZIP)의 메모리 모델과 결정적 bytes codec.

HWPX 는 EPUB/ODF 계열 OCF 패키지다. 규칙:
  - `mimetype` 엔트리는 반드시 아카이브의 첫 항목이며 무압축(STORED)으로 저장된다.
  - 나머지 엔트리는 DEFLATE 로 압축한다.
  - 이미 압축된 바이너리(png 등)는 원본 압축 방식을 유지하는 편이 안전하다.

파싱에서는 실제 한컴 산출물과의 호환성을 위해 첫 `mimetype`의 DEFLATED만 허용하되,
직렬화할 때는 반드시 STORED로 정규화한다. 값과 순서는 완화하지 않는다.

기존 VBA 구현은 PowerShell 경유 .NET ``ZipFile.CreateFromDirectory`` 를 써서 이
순서·무압축 규칙을 보장하지 못했다(한컴 뷰어가 관대해 통과했을 뿐). 여기서는
바이트 단위로 정확히 재구성한다.

입력 경계는 자원 예산(:class:`HwpxPackageLimits`)을 **payload 를 읽기 전에** central
directory 선언값으로 먼저 잰다(#800). 예산은 I/O 없는 상수 묶음이라 형식 커널에 둔다 —
파일 크기 확인(stat) 같은 환경 효과는 External adapter 가 같은 한도로 수행한다.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

MIMETYPE_NAME = "mimetype"
MIMETYPE_VALUE = b"application/hwp+zip"

_MIB = 1024 * 1024
#: HWPX(OCF)가 쓰는 압축 방식. 그 밖의 방식은 읽기 전에 거절한다.
_SUPPORTED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_FLAG_ENCRYPTED = 0x1
_FLAG_PATCHED_DATA = 0x20
_FLAG_STRONG_ENCRYPTION = 0x40
_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"


class HwpxPackageBudgetError(ValueError):
    """HWPX 입력이 자원 예산을 넘었다(#800) — 관측값과 한도를 함께 싣는다.

    ``ValueError`` 계열이라 기존 「열 수 없는 HWPX」 거절 경로(사유 문자열 그대로 표시)를
    그대로 탄다. ``dimension`` 은 기계가 읽는 차원 이름이다.
    """

    def __init__(self, dimension: str, observed: float, limit: float, detail: str) -> None:
        super().__init__(f"HWPX 자원 한도 초과: {detail}")
        self.dimension = dimension
        self.observed = observed
        self.limit = limit


def _fmt_bytes(size: int) -> str:
    if size >= _MIB:
        return f"{size / _MIB:.1f} MiB"
    return f"{size} B"


@dataclass(frozen=True)
class HwpxPackageLimits:
    """HWPX 입력의 자원 예산(#800) — 정상 사무 문서는 닿지 않고, 메모리는 묶이는 한도.

    크기는 모두 바이트다(``max_archive_bytes`` 만 압축 상태의 파일 크기, 나머지는 비압축).
    압축률 한도는 비압축 ``ratio_min_entry_bytes`` 를 넘는 엔트리에만 적용해, 작고 반복적인
    XML 이 높은 압축률 때문에 거절되지 않게 한다. 제품 계층이 한도를 바꿔야 하면 새 인스턴스를
    넘긴다(기본값은 :data:`DEFAULT_PACKAGE_LIMITS`).
    """

    max_archive_bytes: int = 1024 * _MIB
    max_entries: int = 4096
    max_entry_bytes: int = 256 * _MIB
    max_total_bytes: int = 1024 * _MIB
    max_compression_ratio: int = 500
    ratio_min_entry_bytes: int = 1 * _MIB
    #: central directory 파싱 전 상한. ``zipfile`` 은 EOCD 의 엔트리 수가 아니라 디렉터리
    #: 바이트를 끝까지 읽어 ``ZipInfo`` 를 만들므로, 그 수는 blob 안 서명 개수를 넘지 못한다.
    #: 압축 데이터·내장 ZIP 의 우연한 서명을 감안해 ``max_entries`` 보다 넉넉히 둔다.
    max_directory_signatures: int = 65536

    def check_archive_size(self, size: int) -> None:
        """아카이브 파일 자체의 크기 — External 은 읽기 전 stat 으로, 커널은 blob 길이로 잰다."""
        if size > self.max_archive_bytes:
            raise HwpxPackageBudgetError(
                "archive_bytes",
                size,
                self.max_archive_bytes,
                f"파일 크기 {_fmt_bytes(size)} > {_fmt_bytes(self.max_archive_bytes)}",
            )

    def check_blob(self, blob: bytes) -> None:
        """``zipfile`` 이 central directory 를 파싱하기 전에 blob 만으로 잰다."""
        self.check_archive_size(len(blob))
        signatures = blob.count(_CENTRAL_DIRECTORY_SIGNATURE)
        if signatures > self.max_directory_signatures:
            raise HwpxPackageBudgetError(
                "directory_signatures",
                signatures,
                self.max_directory_signatures,
                f"ZIP 디렉터리 서명 수 {signatures} > {self.max_directory_signatures}",
            )

    def check_infos(self, infos: "list[zipfile.ZipInfo]") -> None:
        """central directory 선언값만으로 예산을 잰다 — 어떤 payload 도 읽기 전이다."""
        if len(infos) > self.max_entries:
            raise HwpxPackageBudgetError(
                "entries",
                len(infos),
                self.max_entries,
                f"ZIP 엔트리 수 {len(infos)} > {self.max_entries}",
            )
        for info in infos:
            size = info.file_size
            if size > self.max_entry_bytes:
                raise HwpxPackageBudgetError(
                    "entry_bytes",
                    size,
                    self.max_entry_bytes,
                    f"엔트리 {info.filename!r} {_fmt_bytes(size)} > "
                    f"{_fmt_bytes(self.max_entry_bytes)}",
                )
            if size > self.ratio_min_entry_bytes:
                ratio = size / max(info.compress_size, 1)
                if ratio > self.max_compression_ratio:
                    raise HwpxPackageBudgetError(
                        "compression_ratio",
                        ratio,
                        self.max_compression_ratio,
                        f"엔트리 {info.filename!r} 압축률 {ratio:.0f}:1 > "
                        f"{self.max_compression_ratio}:1",
                    )
        total = sum(info.file_size for info in infos)
        if total > self.max_total_bytes:
            raise HwpxPackageBudgetError(
                "total_bytes",
                total,
                self.max_total_bytes,
                f"비압축 합계 {_fmt_bytes(total)} > {_fmt_bytes(self.max_total_bytes)}",
            )


#: 입력 경계의 기본 예산. 근거(실측 여유)는 ``docs/product.md`` 의 지원 규모 절이 소유한다.
DEFAULT_PACKAGE_LIMITS = HwpxPackageLimits()


@dataclass
class HwpxPackage:
    """메모리에 적재된 HWPX 아카이브.

    엔트리 이름 -> 바이트. 순서를 보존해 원본 레이아웃을 최대한 유지한다.
    """

    entries: "dict[str, bytes]" = field(default_factory=dict)
    # 원본에서 STORED(무압축)였던 엔트리 이름 집합 — 저장 시 그대로 재현.
    stored: "set[str]" = field(default_factory=set)

    # ----------------------------------------------------------------- parse
    @classmethod
    def from_bytes(
        cls, blob: bytes, *, limits: HwpxPackageLimits = DEFAULT_PACKAGE_LIMITS
    ) -> "HwpxPackage":
        limits.check_blob(blob)
        with zipfile.ZipFile(io.BytesIO(blob), "r") as zf:
            infos = zf.infolist()
            cls._validate_archive_infos(infos)
            limits.check_infos(infos)

            # ``mimetype`` 값도 나머지 payload를 읽기 전에 확인한다. 구조 검증을
            # 마친 ZipInfo 자체로 읽어 duplicate-name lookup의 모호성을 피한다.
            if cls._read_entry(zf, infos[0]) != MIMETYPE_VALUE:
                raise ValueError("유효한 HWPX 가 아닙니다: 잘못된 mimetype 값")

            entries: "dict[str, bytes]" = {}
            stored: "set[str]" = set()
            for info in infos:
                entries[info.filename] = cls._read_entry(zf, info)
                if info.compress_type == zipfile.ZIP_STORED:
                    stored.add(info.filename)
        pkg = cls(entries=entries, stored=stored)
        pkg._validate()
        return pkg

    @staticmethod
    def _read_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
        """예산 검사를 마친 선언 크기만큼만 읽는다 — 거짓 central directory 로 우회하지 못한다.

        ``ZipExtFile`` 은 선언 크기에서 읽기를 끊는다(실제가 더 크면 잘린 데이터의 CRC 가
        어긋나 ``BadZipFile``). 그래서 할당은 언제나 선언 ``file_size`` 이하다. 실제가 선언보다
        작으면 길이 불일치로 거절한다.
        """
        with zf.open(info) as fh:
            data = fh.read(info.file_size + 1)
        if len(data) != info.file_size:
            raise HwpxPackageBudgetError(
                "declared_size",
                len(data),
                info.file_size,
                f"엔트리 {info.filename!r} 실제 {len(data)} B != 선언 {info.file_size} B",
            )
        return data

    @classmethod
    def _validate_archive_infos(cls, infos: "list[zipfile.ZipInfo]") -> None:
        """ZIP central directory를 payload 처리 전에 fail-closed 검증한다."""
        names = [info.filename for info in infos]
        if MIMETYPE_NAME not in names:
            raise ValueError("유효한 HWPX 가 아닙니다: mimetype 엔트리 없음")
        if names[0] != MIMETYPE_NAME:
            raise ValueError("유효한 HWPX 가 아닙니다: mimetype 엔트리가 첫 항목이 아님")
        if infos[0].compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ValueError("유효한 HWPX 가 아닙니다: 지원하지 않는 mimetype 압축 방식")

        seen: "set[str]" = set()
        for info in infos:
            name = info.filename
            if name in seen:
                raise ValueError(f"유효한 HWPX 가 아닙니다: 중복 ZIP 엔트리 {name!r}")
            seen.add(name)
            cls._validate_entry_name(name)
            cls._validate_entry_features(info)

    @staticmethod
    def _validate_entry_features(info: zipfile.ZipInfo) -> None:
        """암호화·비표준 압축 등 HWPX(OCF)가 쓰지 않는 ZIP 기능은 읽기 전에 거절한다."""
        name = info.filename
        if info.flag_bits & (_FLAG_ENCRYPTED | _FLAG_STRONG_ENCRYPTION):
            raise ValueError(f"유효한 HWPX 가 아닙니다: 암호화된 ZIP 엔트리 {name!r}")
        if info.flag_bits & _FLAG_PATCHED_DATA:
            raise ValueError(f"유효한 HWPX 가 아닙니다: 지원하지 않는 ZIP 기능 {name!r}")
        if info.compress_type not in _SUPPORTED_COMPRESSION:
            raise ValueError(
                f"유효한 HWPX 가 아닙니다: 지원하지 않는 압축 방식 {name!r} "
                f"(method {info.compress_type})"
            )

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


def to_package(pkg_or_blob: object) -> HwpxPackage:
    """package/bytes → 열린 package 의 메모리 정규화 입구(P3-03, #591).

    ``HwpxPackage`` 는 그대로 통과하고 bytes 는 ``from_bytes`` 로 파싱한다. 경로 I/O는
    External adapter 소유이므로 str/Path를 포함한 그 외 입력은 TypeError(loud).
    """
    if isinstance(pkg_or_blob, HwpxPackage):
        return pkg_or_blob
    if isinstance(pkg_or_blob, (bytes, bytearray)):
        return HwpxPackage.from_bytes(bytes(pkg_or_blob))
    raise TypeError(f"지원하지 않는 입력 타입: {type(pkg_or_blob)!r}")
