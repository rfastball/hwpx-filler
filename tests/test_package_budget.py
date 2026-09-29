"""HWPX 입력 자원 예산(#800) — 경계값·초과·압축폭탄·거짓 central directory·암호화."""

from __future__ import annotations

import io
import struct
import tracemalloc
import zipfile
from pathlib import Path

import pytest

import hwpxfiller.external.hwpx_package_io as package_io
from hwpxcore.package import (
    DEFAULT_PACKAGE_LIMITS,
    MIMETYPE_NAME,
    MIMETYPE_VALUE,
    HwpxPackage,
    HwpxPackageBudgetError,
    HwpxPackageLimits,
)

ROOT = Path(__file__).resolve().parent.parent
MIB = 1024 * 1024

# central directory file header 필드 오프셋(APPNOTE 4.3.12).
_CD_SIGNATURE = b"PK\x01\x02"
_CD_FLAGS = 8
_CD_UNCOMPRESSED_SIZE = 24
_CD_NAME_LENGTH = 28
_CD_NAME = 46


def _zip(entries: "list[tuple[str, bytes, int]]") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data, compress_type in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = compress_type
            zf.writestr(info, data)
    return buf.getvalue()


def _hwpx(*extra: "tuple[str, bytes]", compress_type: int = zipfile.ZIP_DEFLATED) -> bytes:
    entries = [(MIMETYPE_NAME, MIMETYPE_VALUE, zipfile.ZIP_STORED)]
    entries += [(name, data, compress_type) for name, data in extra]
    return _zip(entries)


def _patch_central_directory(blob: bytes, name: str, offset: int, fmt: str, value: int) -> bytes:
    """central directory 의 한 엔트리 필드만 고친다 — 로컬 헤더·payload 는 그대로 둔다."""
    out = bytearray(blob)
    target = name.encode()
    idx = out.find(_CD_SIGNATURE)
    while idx != -1:
        (name_length,) = struct.unpack_from("<H", out, idx + _CD_NAME_LENGTH)
        if bytes(out[idx + _CD_NAME : idx + _CD_NAME + name_length]) == target:
            struct.pack_into(fmt, out, idx + offset, value)
            return bytes(out)
        idx = out.find(_CD_SIGNATURE, idx + 4)
    raise AssertionError(f"central directory 에 {name!r} 없음")


def _declare_size(blob: bytes, name: str, size: int) -> bytes:
    return _patch_central_directory(blob, name, _CD_UNCOMPRESSED_SIZE, "<I", size)


def _forbid_payload_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """예산 거절이 어떤 엔트리 payload 도 열기 **전에** 일어났음을 증명한다."""

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("예산 검사 전에 ZIP 엔트리를 열었다")

    monkeypatch.setattr(zipfile.ZipFile, "open", _refuse)
    monkeypatch.setattr(zipfile.ZipFile, "read", _refuse)


def _budget_error(blob: bytes, limits: HwpxPackageLimits) -> HwpxPackageBudgetError:
    with pytest.raises(HwpxPackageBudgetError) as caught:
        HwpxPackage.from_bytes(blob, limits=limits)
    return caught.value


# ------------------------------------------------------------------ 경계값


def test_budget_error_is_a_value_error_with_observed_and_limit():
    blob = _hwpx(("a.xml", b"x"), ("b.xml", b"y"))
    error = _budget_error(blob, HwpxPackageLimits(max_entries=2))
    assert isinstance(error, ValueError)
    assert (error.dimension, error.observed, error.limit) == ("entries", 3, 2)
    assert str(error) == "HWPX 자원 한도 초과: ZIP 엔트리 수 3 > 2"


def test_entry_count_at_limit_passes_and_one_over_is_refused():
    blob = _hwpx(("a.xml", b"x"), ("b.xml", b"y"))
    assert len(HwpxPackage.from_bytes(blob, limits=HwpxPackageLimits(max_entries=3)).entries) == 3
    assert "3 > 2" in str(_budget_error(blob, HwpxPackageLimits(max_entries=2)))


def test_entry_size_at_limit_passes_and_one_over_is_refused():
    blob = _hwpx(("BinData/x.bin", b"\x01" * 1000))
    HwpxPackage.from_bytes(blob, limits=HwpxPackageLimits(max_entry_bytes=1000))
    error = _budget_error(blob, HwpxPackageLimits(max_entry_bytes=999))
    assert error.dimension == "entry_bytes"
    assert str(error) == "HWPX 자원 한도 초과: 엔트리 'BinData/x.bin' 1000 B > 999 B"


def test_total_size_at_limit_passes_and_one_over_is_refused():
    blob = _hwpx(("a.xml", b"x" * 100), ("b.xml", b"y" * 100))
    total = len(MIMETYPE_VALUE) + 200
    HwpxPackage.from_bytes(blob, limits=HwpxPackageLimits(max_total_bytes=total))
    error = _budget_error(blob, HwpxPackageLimits(max_total_bytes=total - 1))
    assert (error.dimension, error.observed, error.limit) == ("total_bytes", total, total - 1)
    assert f"비압축 합계 {total} B > {total - 1} B" in str(error)


def test_archive_size_at_limit_passes_and_one_over_is_refused():
    blob = _hwpx(("a.xml", b"x"))
    HwpxPackage.from_bytes(blob, limits=HwpxPackageLimits(max_archive_bytes=len(blob)))
    error = _budget_error(blob, HwpxPackageLimits(max_archive_bytes=len(blob) - 1))
    assert error.dimension == "archive_bytes"
    assert f"파일 크기 {len(blob)} B > {len(blob) - 1} B" in str(error)


def test_default_limit_message_reports_mebibytes():
    info = zipfile.ZipInfo("BinData/x.png")
    info.file_size = 300 * MIB
    info.compress_size = 300 * MIB
    with pytest.raises(HwpxPackageBudgetError) as caught:
        DEFAULT_PACKAGE_LIMITS.check_infos([info])
    assert str(caught.value) == (
        "HWPX 자원 한도 초과: 엔트리 'BinData/x.png' 300.0 MiB > 256.0 MiB"
    )


# ------------------------------------------------------------------ 압축률


def test_compression_ratio_applies_only_above_the_absolute_floor():
    # 작은 반복 XML: 압축률이 한도를 훌쩍 넘어도 floor 이하라 통과한다.
    small = _hwpx(("Contents/section0.xml", b"<a/>" * 4096))
    limits = HwpxPackageLimits(max_compression_ratio=2, ratio_min_entry_bytes=64 * 1024)
    HwpxPackage.from_bytes(small, limits=limits)

    big = _hwpx(("Contents/section0.xml", b"<a/>" * 65536))
    error = _budget_error(big, limits)
    assert error.dimension == "compression_ratio"
    assert error.limit == 2
    assert "엔트리 'Contents/section0.xml' 압축률 " in str(error)
    assert ":1 > 2:1" in str(error)


def test_compression_ratio_at_limit_passes():
    data = b"<a/>" * 65536
    blob = _hwpx(("Contents/section0.xml", data))
    info = zipfile.ZipFile(io.BytesIO(blob)).getinfo("Contents/section0.xml")
    exact = len(data) // info.compress_size  # floor → 실제 압축률 이상이면 통과해야 한다
    limits = HwpxPackageLimits(max_compression_ratio=exact + 1, ratio_min_entry_bytes=1)
    HwpxPackage.from_bytes(blob, limits=limits)


def test_compression_bomb_is_refused_before_any_payload_is_read(monkeypatch):
    bomb = _hwpx(("BinData/zero.bin", bytes(8 * MIB)))
    assert len(bomb) < 64 * 1024  # 디스크 위는 작고 선언은 크다
    _forbid_payload_reads(monkeypatch)

    tracemalloc.start()
    try:
        with pytest.raises(HwpxPackageBudgetError) as caught:
            HwpxPackage.from_bytes(bomb)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert caught.value.dimension == "compression_ratio"
    assert "'BinData/zero.bin'" in str(caught.value)
    assert "> 500:1" in str(caught.value)
    assert peak < 1 * MIB


def test_declared_oversize_entry_is_refused_before_allocation(monkeypatch):
    blob = _declare_size(_hwpx(("BinData/x.png", b"tiny")), "BinData/x.png", 300 * MIB)
    _forbid_payload_reads(monkeypatch)
    with pytest.raises(HwpxPackageBudgetError, match=r"'BinData/x.png' 300\.0 MiB > 256\.0 MiB"):
        HwpxPackage.from_bytes(blob)


def test_mimetype_entry_is_also_under_budget(monkeypatch):
    blob = _declare_size(_hwpx(("a.xml", b"x")), MIMETYPE_NAME, 300 * MIB)
    _forbid_payload_reads(monkeypatch)
    with pytest.raises(HwpxPackageBudgetError, match="'mimetype'"):
        HwpxPackage.from_bytes(blob)


def test_directory_signature_count_is_bounded_before_zip_parsing(monkeypatch):
    blob = _hwpx(("a.xml", b"x"), ("b.xml", b"y"), ("c.xml", b"z"))

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("서명 수 검사 전에 central directory 를 파싱했다")

    monkeypatch.setattr(zipfile, "ZipFile", _refuse)
    error = _budget_error(blob, HwpxPackageLimits(max_directory_signatures=3))
    assert str(error) == "HWPX 자원 한도 초과: ZIP 디렉터리 서명 수 4 > 3"


# ------------------------------------------------------- 거짓 central directory


def test_central_directory_declaring_more_than_actual_is_refused():
    blob = _declare_size(_hwpx(("Contents/x.xml", b"A" * 5000)), "Contents/x.xml", 100_000)
    error = _budget_error(blob, DEFAULT_PACKAGE_LIMITS)
    assert error.dimension == "declared_size"
    assert str(error) == (
        "HWPX 자원 한도 초과: 엔트리 'Contents/x.xml' 실제 5000 B != 선언 100000 B"
    )


@pytest.mark.parametrize("compress_type", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_central_directory_declaring_less_than_actual_cannot_allocate_past_it(
    monkeypatch, compress_type
):
    blob = _declare_size(
        _hwpx(("Contents/x.xml", b"A" * 5000), compress_type=compress_type),
        "Contents/x.xml",
        10,
    )
    requests: "list[tuple[str, int | None]]" = []
    real_read = zipfile.ZipExtFile.read

    def _spy_read(self: zipfile.ZipExtFile, n: "int | None" = -1) -> bytes:
        requests.append((self.name, n))
        return real_read(self, n)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", _spy_read)
    # 선언 크기에서 끊긴 데이터는 CRC 가 어긋나 loud 하게 거절된다.
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        HwpxPackage.from_bytes(blob)
    # 읽기 요청은 언제나 선언 크기(+1 불일치 탐지)로 묶인다 — 무제한 read() 가 없다.
    assert ("Contents/x.xml", 11) in requests
    assert all(n is not None and 0 <= n <= 20 for _name, n in requests)


# ------------------------------------------------------- 지원하지 않는 ZIP 기능


@pytest.mark.parametrize(
    ("flag", "message"),
    [
        pytest.param(0x1, "암호화된 ZIP 엔트리 'Contents/x.xml'", id="encrypted"),
        pytest.param(0x40, "암호화된 ZIP 엔트리 'Contents/x.xml'", id="strong-encryption"),
        pytest.param(0x20, "지원하지 않는 ZIP 기능 'Contents/x.xml'", id="patched-data"),
    ],
)
def test_unsupported_zip_flags_are_refused_before_reading(monkeypatch, flag, message):
    blob = _hwpx(("Contents/x.xml", b"<x/>"))
    blob = _patch_central_directory(blob, "Contents/x.xml", _CD_FLAGS, "<H", flag)
    _forbid_payload_reads(monkeypatch)
    with pytest.raises(ValueError, match=message):
        HwpxPackage.from_bytes(blob)


@pytest.mark.parametrize("compress_type", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_non_ocf_compression_is_refused(monkeypatch, compress_type):
    blob = _hwpx(("Contents/x.xml", b"<x/>"), compress_type=compress_type)
    _forbid_payload_reads(monkeypatch)
    with pytest.raises(ValueError, match="지원하지 않는 압축 방식 'Contents/x.xml'"):
        HwpxPackage.from_bytes(blob)


# ------------------------------------------------------------------ path adapter


def test_path_adapter_refuses_oversize_file_before_reading_it(tmp_path, monkeypatch):
    path = tmp_path / "big.hwpx"
    path.write_bytes(_hwpx(("a.xml", b"x")))
    size = path.stat().st_size
    monkeypatch.setattr(
        package_io, "DEFAULT_PACKAGE_LIMITS", HwpxPackageLimits(max_archive_bytes=size - 1)
    )

    def _refuse(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("크기 검사 전에 파일을 읽었다")

    monkeypatch.setattr(Path, "read_bytes", _refuse)
    with pytest.raises(HwpxPackageBudgetError, match=f"파일 크기 {size} B > {size - 1} B"):
        package_io.read_hwpx_package(path)


# ------------------------------------------------------------------ 실제 문서


def _real_documents() -> "list[Path]":
    roots = [ROOT / "tests" / "corpus", ROOT / "tests" / "fixtures", ROOT / "examples"]
    found = sorted(
        path for root in roots for pattern in ("*.hwpx", "*.hwpt") for path in root.rglob(pattern)
    )
    assert found, "corpus 가 비었다"
    return found


def test_every_corpus_and_bundled_document_stays_far_inside_the_budget():
    """정상 문서가 한도의 1% 에도 닿지 않음을 고정한다 — 기본값을 줄일 때의 경보선."""
    limits = DEFAULT_PACKAGE_LIMITS
    for path in _real_documents():
        blob = path.read_bytes()
        package = package_io.read_hwpx_package(path)
        infos = zipfile.ZipFile(io.BytesIO(blob)).infolist()
        assert len(package.entries) == len(infos), path
        assert len(infos) * 100 <= limits.max_entries, path
        assert sum(info.file_size for info in infos) * 100 <= limits.max_total_bytes, path
        for info in infos:
            ratio = info.file_size / max(info.compress_size, 1)
            assert ratio * 5 <= limits.max_compression_ratio, (path, info.filename)
