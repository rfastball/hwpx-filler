"""작업 꾸러미(``.narumi``) 파일의 zip 쓰기·읽기 (WP-01 · #1188).

배치는 둘뿐이다: ``manifest.json`` 과 ``templates/<sha256>.<hwpx|txt>``. manifest 의 의미
불변식은 :mod:`hwpxfiller.domain.work_package` 가 소유하고, 이 모듈은 bytes 경계를 진다.

읽기는 꾸러미를 **신뢰하지 않는 입력**으로 다룬다. central directory 선언값으로 엔트리 수·
크기·압축률·이름을 payload 를 읽기 전에 재고(:mod:`hwpxcore.package` 의 #800 예산과 같은
방식), 허용 배치 밖 엔트리·경로 탈출·디렉터리·심볼릭 링크·암호화를 거절한 뒤, 템플릿마다
sha256 을 다시 계산해 파일 이름·manifest 선언과 대조한다. 실패는 사유가 담긴
:class:`~hwpxfiller.domain.work_package.WorkPackageError` 하나이고 부분 결과는 없다.

쓰기는 읽기 판정을 그대로 통과하는 bytes 만 원자적으로 남긴다(확인-또는-경보).
"""

from __future__ import annotations

import io
import json
import re
import stat
import zipfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from ..domain.work_package import (
    WorkPackageError,
    WorkPackageManifest,
    decode_work_package,
    encode_work_package,
)
from .atomic import write_bytes_atomic

MANIFEST_NAME = "manifest.json"
TEMPLATE_DIR = "templates"

_MIB = 1024 * 1024
#: 고유 템플릿 수 상한 — 사람이 골라 건네는 작업 묶음이 닿지 않을 넉넉한 위.
MAX_TEMPLATES = 256
#: 엔트리 수 상한 — 허용 배치가 manifest 하나와 템플릿뿐이라 그 합이다.
MAX_ENTRIES = MAX_TEMPLATES + 1
#: manifest 비압축 상한 — 값 없는 연결·프리셋·계약 JSON 이 닿지 않을 크기.
MAX_MANIFEST_BYTES = 16 * _MIB
#: 템플릿 한 개의 비압축 상한 — HWPX 커널의 엔트리 상한(256 MiB)과 같은 눈금.
MAX_TEMPLATE_BYTES = 256 * _MIB
#: 비압축 합계 상한 — 모두 메모리에 올리므로 HWPX 커널의 아카이브 상한(1 GiB)으로 묶는다.
MAX_TOTAL_BYTES = 1024 * _MIB
#: 꾸러미 파일 자체의 크기 상한 — 합계 상한과 같다(템플릿은 대개 이미 압축된 bytes 다).
MAX_ARCHIVE_BYTES = 1024 * _MIB
#: 압축률 상한 — 텍스트·JSON 의 정상 압축률(수십 배)은 통과하고 zip bomb 은 막는 값.
MAX_COMPRESSION_RATIO = 200
#: 압축률을 재는 최소 비압축 크기 — 작고 반복적인 JSON 이 높은 비율만으로 거절되지 않게.
RATIO_MIN_ENTRY_BYTES = 1 * _MIB
#: central directory 파싱 전 서명 수 상한 — 무압축 HWPX 안의 서명까지 감안해 넉넉히 둔다.
MAX_DIRECTORY_SIGNATURES = 65536

_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
_TEMPLATE_ENTRY = re.compile(rf"{TEMPLATE_DIR}/([0-9a-f]{{64}})\.(hwpx|txt)")
_SUPPORTED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_FLAG_ENCRYPTED = 0x1
_FLAG_PATCHED_DATA = 0x20
_FLAG_STRONG_ENCRYPTION = 0x40
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class WorkPackageContents:
    """읽기에 성공한 꾸러미 — manifest 와 ``{digest: 템플릿 bytes}`` (읽기 전용)."""

    manifest: WorkPackageManifest
    templates: Mapping[str, bytes]


# ─── 쓰기 ─────────────────────────────────────────────────────────────────────

def _check_template_blobs(manifest: WorkPackageManifest, templates: Mapping[str, bytes]) -> None:
    declared = manifest.template_by_digest()
    if set(templates) != set(declared):
        raise WorkPackageError("템플릿 bytes 집합이 manifest 선언과 다릅니다")
    for digest, template in declared.items():
        blob = templates[digest]
        if sha256(blob).hexdigest() != digest or len(blob) != template.size:
            raise WorkPackageError(f"템플릿 bytes 가 선언 digest·크기와 다릅니다: {digest}")


def _zip_info(name: str, compression: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
    info.compress_type = compression
    return info


def build_work_package_bytes(
    manifest: WorkPackageManifest, templates: Mapping[str, bytes]
) -> bytes:
    """manifest 와 템플릿 bytes → 꾸러미 bytes. 결과는 읽기 판정을 통과한 것만 돌려준다.

    HWPX 는 이미 압축된 zip 이라 무압축으로, manifest·TXT 는 DEFLATE 로 담는다. 시각은
    고정해 같은 입력이 같은 bytes 가 되게 한다.
    """
    _check_template_blobs(manifest, templates)
    try:
        text = json.dumps(
            encode_work_package(manifest), ensure_ascii=False, indent=2, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise WorkPackageError(f"manifest 를 JSON 으로 쓸 수 없습니다: {exc}") from exc
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(_zip_info(MANIFEST_NAME, zipfile.ZIP_DEFLATED), text.encode("utf-8"))
        for template in sorted(manifest.templates, key=lambda item: item.digest):
            compression = zipfile.ZIP_STORED if template.media == "hwpx" else zipfile.ZIP_DEFLATED
            name = f"{TEMPLATE_DIR}/{template.digest}.{template.media}"
            archive.writestr(_zip_info(name, compression), templates[template.digest])
    blob = buffer.getvalue()
    read_work_package_bytes(blob)
    return blob


def write_work_package(
    path: "str | Path", manifest: WorkPackageManifest, templates: Mapping[str, bytes]
) -> None:
    """꾸러미를 먼저 bytes 로 완성·검증한 뒤 원자적으로 저장한다(RC-01)."""
    write_bytes_atomic(path, build_work_package_bytes(manifest, templates))


# ─── 읽기: 엔트리 선언 검사(payload 이전) ────────────────────────────────────

def _check_blob(blob: bytes) -> None:
    if len(blob) > MAX_ARCHIVE_BYTES:
        raise WorkPackageError(f"꾸러미 파일이 너무 큽니다({len(blob)} B)")
    if blob.count(_CENTRAL_DIRECTORY_SIGNATURE) > MAX_DIRECTORY_SIGNATURES:
        raise WorkPackageError("꾸러미의 ZIP 디렉터리 서명이 너무 많습니다")


def _check_entry_name(info: zipfile.ZipInfo) -> None:
    """허용 배치 대조 전에 경로 탈출 모양을 **원래 이름**으로 거절한다(사유를 정확히 남기려고).

    ``zipfile`` 은 읽을 때 이름을 다듬는다(Windows 에서 역슬래시→슬래시, NUL 뒤 절단). 다듬은
    이름만 보면 그 흔적이 사라지므로 아카이브에 적힌 ``orig_filename`` 을 본다.
    """
    name = info.orig_filename
    if not name:
        raise WorkPackageError("꾸러미에 이름 없는 항목이 있습니다")
    if "\0" in name:
        raise WorkPackageError(f"꾸러미 항목 이름에 NUL 문자가 있습니다: {name!r}")
    if "\\" in name:
        raise WorkPackageError(f"꾸러미 항목 경로에 역슬래시가 있습니다: {name!r}")
    drive = len(name) >= 2 and name[0].isalpha() and name[1] == ":"
    if name.startswith("/") or drive:
        raise WorkPackageError(f"꾸러미 항목 경로가 절대 경로입니다: {name!r}")
    if ".." in name.split("/"):
        raise WorkPackageError(f"꾸러미 항목 경로가 상위 폴더를 가리킵니다: {name!r}")


def _check_entry_kind(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if info.is_dir() or stat.S_ISDIR(info.external_attr >> 16):
        raise WorkPackageError(f"꾸러미에 폴더 항목이 있습니다: {name!r}")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise WorkPackageError(f"꾸러미에 링크 항목이 있습니다: {name!r}")
    if info.flag_bits & (_FLAG_ENCRYPTED | _FLAG_STRONG_ENCRYPTION | _FLAG_PATCHED_DATA):
        raise WorkPackageError(f"꾸러미 항목이 암호화됐거나 지원하지 않는 ZIP 기능을 씁니다: {name!r}")
    if info.compress_type not in _SUPPORTED_COMPRESSION:
        raise WorkPackageError(f"꾸러미 항목의 압축 방식을 지원하지 않습니다: {name!r}")


def _entry_limit(name: str) -> int:
    """허용 배치에 든 이름의 비압축 상한. 배치 밖 이름은 loud."""
    if name == MANIFEST_NAME:
        return MAX_MANIFEST_BYTES
    if _TEMPLATE_ENTRY.fullmatch(name):
        return MAX_TEMPLATE_BYTES
    raise WorkPackageError(f"꾸러미에 허용되지 않은 항목이 있습니다: {name!r}")


def _check_entry_size(info: zipfile.ZipInfo, limit: int) -> None:
    size = info.file_size
    if size > limit:
        raise WorkPackageError(f"꾸러미 항목이 너무 큽니다: {info.filename!r} ({size} B)")
    if size > RATIO_MIN_ENTRY_BYTES and size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
        raise WorkPackageError(f"꾸러미 항목의 압축률이 비정상입니다: {info.filename!r}")


def _admit_entries(infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    """central directory 선언만으로 배치·이름·종류·크기를 판정한다 — payload 를 읽기 전이다."""
    if len(infos) > MAX_ENTRIES:
        raise WorkPackageError(f"꾸러미 항목이 너무 많습니다({len(infos)}개)")
    admitted: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        _check_entry_name(info)
        name = info.filename
        if name in admitted:
            raise WorkPackageError(f"꾸러미 항목 이름이 겹칩니다: {name!r}")
        _check_entry_kind(info)
        _check_entry_size(info, _entry_limit(name))
        admitted[name] = info
    if sum(info.file_size for info in infos) > MAX_TOTAL_BYTES:
        raise WorkPackageError("꾸러미의 압축 해제 합계가 너무 큽니다")
    if MANIFEST_NAME not in admitted:
        raise WorkPackageError("꾸러미에 manifest.json 이 없습니다")
    return admitted


# ─── 읽기: payload ───────────────────────────────────────────────────────────

def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """선언 크기만큼만 읽는다 — 거짓 central directory 로 할당을 키우지 못한다."""
    with archive.open(info) as handle:
        data = handle.read(info.file_size + 1)
    if len(data) != info.file_size:
        raise WorkPackageError(f"꾸러미 항목의 실제 크기가 선언과 다릅니다: {info.filename!r}")
    return data


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record = dict(pairs)
    if len(record) != len(pairs):
        raise WorkPackageError("manifest 에 같은 키가 두 번 있습니다")
    return record


def _reject_constant(token: str) -> object:
    raise WorkPackageError(f"manifest 에 JSON 이 아닌 값이 있습니다: {token}")


def _parse_manifest(blob: bytes) -> WorkPackageManifest:
    try:
        data = json.loads(
            blob.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkPackageError(f"manifest.json 을 읽을 수 없습니다: {exc}") from exc
    return decode_work_package(data)


def _read_templates(
    archive: zipfile.ZipFile, admitted: dict[str, zipfile.ZipInfo], manifest: WorkPackageManifest
) -> dict[str, bytes]:
    """manifest 선언과 템플릿 엔트리가 일대일이고 digest·형식·크기가 모두 맞을 때만 bytes 를 준다."""
    declared = manifest.template_by_digest()
    present = {
        match.group(1): (info, match.group(2))
        for name, info in admitted.items()
        if (match := _TEMPLATE_ENTRY.fullmatch(name))
    }
    if len(present) != len(admitted) - 1:
        raise WorkPackageError("같은 템플릿이 다른 형식으로 두 번 들어 있습니다")
    if set(present) != set(declared):
        raise WorkPackageError("꾸러미의 템플릿 파일이 manifest 선언과 다릅니다")
    blobs: dict[str, bytes] = {}
    for digest, (info, media) in present.items():
        template = declared[digest]
        if media != template.media:
            raise WorkPackageError(f"템플릿 파일 형식이 manifest 선언과 다릅니다: {digest}")
        if info.file_size != template.size:
            raise WorkPackageError(f"템플릿 크기가 manifest 선언과 다릅니다: {digest}")
        blob = _read_entry(archive, info)
        if sha256(blob).hexdigest() != digest:
            raise WorkPackageError(f"템플릿 내용이 digest 와 다릅니다(손상·변조): {digest}")
        blobs[digest] = blob
    return blobs


def _read_archive(blob: bytes) -> WorkPackageContents:
    with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
        admitted = _admit_entries(archive.infolist())
        manifest = _parse_manifest(_read_entry(archive, admitted[MANIFEST_NAME]))
        templates = _read_templates(archive, admitted, manifest)
    return WorkPackageContents(manifest=manifest, templates=MappingProxyType(templates))


def read_work_package_bytes(blob: bytes) -> WorkPackageContents:
    """꾸러미 bytes → 검증된 내용. 어느 단계든 실패하면 :class:`WorkPackageError` 하나."""
    _check_blob(blob)
    try:
        return _read_archive(blob)
    except WorkPackageError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, NotImplementedError,
            RuntimeError, ValueError) as exc:
        raise WorkPackageError(f"꾸러미 압축을 풀 수 없습니다: {exc}") from exc


def read_work_package(path: "str | Path") -> WorkPackageContents:
    """경로의 꾸러미를 읽는다. 크기를 먼저 재 상한을 넘는 파일은 메모리에 올리지 않는다."""
    source = Path(path)
    try:
        size = source.stat().st_size
        if size > MAX_ARCHIVE_BYTES:
            raise WorkPackageError(f"꾸러미 파일이 너무 큽니다({size} B)")
        blob = source.read_bytes()
    except OSError as exc:
        raise WorkPackageError(f"꾸러미 파일을 열 수 없습니다: {exc}") from exc
    return read_work_package_bytes(blob)


__all__ = [
    "MANIFEST_NAME",
    "MAX_ARCHIVE_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_ENTRIES",
    "MAX_MANIFEST_BYTES",
    "MAX_TEMPLATES",
    "MAX_TEMPLATE_BYTES",
    "MAX_TOTAL_BYTES",
    "WorkPackageContents",
    "build_work_package_bytes",
    "read_work_package",
    "read_work_package_bytes",
    "write_work_package",
]
