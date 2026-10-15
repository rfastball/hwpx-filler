"""작업 꾸러미 zip 쓰기·읽기 테스트(WP-01 · #1188).

읽기는 꾸러미를 신뢰하지 않는다: 배치 밖 엔트리·경로 탈출·크기 폭탄·digest 불일치는
전부 사유가 담긴 :class:`WorkPackageError` 하나로 거절되고 부분 결과는 없다.
"""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest

from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.domain.work_package import (
    PackagedJob,
    PackagedTemplate,
    WorkPackageError,
    WorkPackageManifest,
    encode_work_package,
)
from hwpxfiller.external import work_package_io
from hwpxfiller.external.work_package_io import (
    MANIFEST_NAME,
    build_work_package_bytes,
    read_work_package,
    read_work_package_bytes,
    write_work_package,
)

NOW = "2026-10-15T09:00:00"
HWPX_BYTES = b"PK\x03\x04 fake hwpx template bytes"
TXT_BYTES = "공고명: {{공고명}}\n".encode("utf-8")
HWPX_DIGEST = hashlib.sha256(HWPX_BYTES).hexdigest()
TXT_DIGEST = hashlib.sha256(TXT_BYTES).hexdigest()


def _job(name: str, media: str, digest: str) -> PackagedJob:
    return PackagedJob(
        name=name,
        media=media,
        template_digest=digest,
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="공고명")]),
        filename_pattern="공고서-{{seq:001}}",
    )


def _manifest() -> WorkPackageManifest:
    return WorkPackageManifest(
        created_at=NOW,
        templates=(
            PackagedTemplate(HWPX_DIGEST, "hwpx", "공고서.hwpx", len(HWPX_BYTES)),
            PackagedTemplate(TXT_DIGEST, "txt", "기안.txt", len(TXT_BYTES)),
        ),
        jobs=(
            _job("공고서 A", "hwpx", HWPX_DIGEST),
            _job("공고서 B", "hwpx", HWPX_DIGEST),
            _job("기안", "txt", TXT_DIGEST),
        ),
    )


def _templates() -> dict[str, bytes]:
    return {HWPX_DIGEST: HWPX_BYTES, TXT_DIGEST: TXT_BYTES}


def _manifest_bytes(manifest: WorkPackageManifest | None = None) -> bytes:
    return json.dumps(encode_work_package(manifest or _manifest()), ensure_ascii=False).encode()


def _raw_zip(entries: list[tuple[Any, bytes]]) -> bytes:
    """검증을 거치지 않은 임의 zip — 변조·악성 꾸러미 재현용.

    ``ZipInfo`` 는 이름을 다듬으므로(역슬래시·NUL) 다듬기 전 이름을 그대로 적는다.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            info = name
            if isinstance(name, str):
                info = zipfile.ZipInfo(name)
                info.filename = name
                info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def _valid_entries() -> list[tuple[Any, bytes]]:
    return [
        (MANIFEST_NAME, _manifest_bytes()),
        (f"templates/{HWPX_DIGEST}.hwpx", HWPX_BYTES),
        (f"templates/{TXT_DIGEST}.txt", TXT_BYTES),
    ]


def _rejects(blob: bytes, match: str) -> None:
    with pytest.raises(WorkPackageError, match=match):
        read_work_package_bytes(blob)


# ------------------------------------------------------------------ 왕복
def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "작업.narumi"
    write_work_package(path, _manifest(), _templates())
    contents = read_work_package(path)
    assert encode_work_package(contents.manifest) == encode_work_package(_manifest())
    assert dict(contents.templates) == _templates()
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == sorted(name for name, _ in _valid_entries())


def test_build_is_deterministic_and_stores_template_once() -> None:
    first = build_work_package_bytes(_manifest(), _templates())
    assert first == build_work_package_bytes(_manifest(), _templates())
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert names[0] == MANIFEST_NAME
        assert names.count(f"templates/{HWPX_DIGEST}.hwpx") == 1
        assert archive.getinfo(f"templates/{HWPX_DIGEST}.hwpx").compress_type == zipfile.ZIP_STORED


def test_written_manifest_has_no_data_values_or_paths(tmp_path: Path) -> None:
    path = tmp_path / "작업.narumi"
    write_work_package(path, _manifest(), _templates())
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME))
    for job in manifest["jobs"]:
        assert not {"data_path", "data_sheet", "authority_id", "tags"} & set(job)
        assert job["mapping"]["provenance"] == {}


def test_raw_valid_package_is_accepted() -> None:
    contents = read_work_package_bytes(_raw_zip(_valid_entries()))
    assert [job.name for job in contents.manifest.jobs] == ["공고서 A", "공고서 B", "기안"]
    with pytest.raises(TypeError):
        contents.templates[HWPX_DIGEST] = b"x"  # type: ignore[index]


# ------------------------------------------------------------------ 쓰기 거절
def test_write_rejects_mismatched_template_bytes(tmp_path: Path) -> None:
    with pytest.raises(WorkPackageError, match="digest·크기"):
        build_work_package_bytes(_manifest(), {HWPX_DIGEST: b"other", TXT_DIGEST: TXT_BYTES})
    with pytest.raises(WorkPackageError, match="bytes 집합"):
        build_work_package_bytes(_manifest(), {HWPX_DIGEST: HWPX_BYTES})
    path = tmp_path / "x.narumi"
    with pytest.raises(WorkPackageError):
        write_work_package(path, _manifest(), {})
    assert not path.exists()


def test_write_rejects_non_json_contract() -> None:
    manifest = _manifest()
    job = PackagedJob(**{**manifest.jobs[0].__dict__, "data_contract": {"x": {1, 2}}})
    broken = WorkPackageManifest(NOW, manifest.templates, (job, *manifest.jobs[1:]))
    with pytest.raises(WorkPackageError, match="JSON"):
        build_work_package_bytes(broken, _templates())


# ------------------------------------------------------------------ 변조·손상
def test_digest_mismatch_is_rejected() -> None:
    entries = _valid_entries()
    entries[1] = (entries[1][0], HWPX_BYTES[:-1] + b"!")
    _rejects(_raw_zip(entries), "digest 와 다릅니다")


def test_declared_size_mismatch_is_rejected() -> None:
    template = _manifest().templates[0]
    lying = PackagedTemplate(template.digest, "hwpx", "공고서.hwpx", template.size + 1)
    manifest = WorkPackageManifest(NOW, (lying, _manifest().templates[1]), _manifest().jobs)
    entries = _valid_entries()
    entries[0] = (MANIFEST_NAME, _manifest_bytes(manifest))
    _rejects(_raw_zip(entries), "크기가 manifest 선언과 다릅니다")


def test_template_extension_must_match_manifest_media() -> None:
    entries = _valid_entries()
    entries[2] = (f"templates/{TXT_DIGEST}.hwpx", TXT_BYTES)
    _rejects(_raw_zip(entries), "형식이 manifest 선언과 다릅니다")


def test_same_template_in_two_media_is_rejected() -> None:
    entries = [*_valid_entries(), (f"templates/{TXT_DIGEST}.hwpx", TXT_BYTES)]
    _rejects(_raw_zip(entries), "두 번")


def test_missing_and_undeclared_template_files_are_rejected() -> None:
    _rejects(_raw_zip(_valid_entries()[:2]), "선언과 다릅니다")
    other = b"another"
    entries = [*_valid_entries(), (f"templates/{hashlib.sha256(other).hexdigest()}.txt", other)]
    _rejects(_raw_zip(entries), "선언과 다릅니다")


def test_missing_manifest_is_rejected() -> None:
    _rejects(_raw_zip(_valid_entries()[1:]), "manifest.json 이 없습니다")


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (b"\xff\xfe", "읽을 수 없습니다"),
        (b"{not json", "읽을 수 없습니다"),
        (b'{"schema_version": "work-package/v1", "schema_version": "x"}', "두 번"),
        (b'{"size": NaN}', "JSON 이 아닌 값"),
        (b'{"schema_version": "work-package/v9"}', "모르는 꾸러미 버전"),
    ],
)
def test_malformed_manifest_is_rejected(payload: bytes, match: str) -> None:
    entries = _valid_entries()
    entries[0] = (MANIFEST_NAME, payload)
    _rejects(_raw_zip(entries), match)


def test_unknown_manifest_field_is_rejected() -> None:
    data = encode_work_package(_manifest())
    data["data"] = [{"공고명": "값"}]
    entries = _valid_entries()
    entries[0] = (MANIFEST_NAME, json.dumps(data).encode())
    _rejects(_raw_zip(entries), "모르는 필드")


def test_not_a_zip_is_rejected() -> None:
    _rejects(b"not a zip at all", "압축을 풀 수 없습니다")


def test_corrupted_payload_is_rejected() -> None:
    blob = bytearray(build_work_package_bytes(_manifest(), _templates()))
    offset = blob.index(HWPX_BYTES)
    blob[offset + 5] ^= 0xFF
    _rejects(bytes(blob), "압축을 풀 수 없습니다")


# ------------------------------------------------------------------ 경로·배치
@pytest.mark.parametrize(
    ("name", "match"),
    [
        ("../x", "상위 폴더"),
        ("templates/../manifest.json", "상위 폴더"),
        ("/abs/manifest.json", "절대 경로"),
        ("C:/x.txt", "절대 경로"),
        ("templates\\x.txt", "역슬래시"),
        ("..\\x", "역슬래시"),
        ("manifest.json\0.txt", "NUL"),
        ("readme.txt", "허용되지 않은 항목"),
        ("templates/abc.txt", "허용되지 않은 항목"),
        (f"templates/{HWPX_DIGEST.upper()}.hwpx", "허용되지 않은 항목"),
        (f"templates/{HWPX_DIGEST}.exe", "허용되지 않은 항목"),
        (f"nested/templates/{HWPX_DIGEST}.hwpx", "허용되지 않은 항목"),
    ],
)
def test_unexpected_or_escaping_entry_is_rejected(name: str, match: str) -> None:
    entries = [*_valid_entries(), (name, b"x")]
    _rejects(_raw_zip(entries), match)


def test_directory_entry_is_rejected() -> None:
    entries = [*_valid_entries(), ("templates/", b"")]
    _rejects(_raw_zip(entries), "폴더")


def test_symlink_entry_is_rejected() -> None:
    link = zipfile.ZipInfo(f"templates/{TXT_DIGEST}.txt")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    entries = [*_valid_entries()[:2], (link, TXT_BYTES)]
    _rejects(_raw_zip(entries), "링크")


def test_duplicate_entry_name_is_rejected() -> None:
    with pytest.warns(UserWarning):
        blob = _raw_zip([*_valid_entries(), (MANIFEST_NAME, _manifest_bytes())])
    _rejects(blob, "겹칩니다")


def test_nameless_entry_is_rejected() -> None:
    _rejects(_raw_zip([("", b"x"), *_valid_entries()]), "이름 없는 항목")


def test_unsupported_compression_is_rejected() -> None:
    entry = zipfile.ZipInfo(f"templates/{TXT_DIGEST}.txt")
    entry.compress_type = zipfile.ZIP_BZIP2
    _rejects(_raw_zip([*_valid_entries()[:2], (entry, TXT_BYTES)]), "압축 방식")


def test_entry_shorter_than_its_declared_size_is_rejected() -> None:
    """central directory 가 실제보다 큰 크기를 말하면 읽은 bytes 와 대조해 거절한다."""
    stored = zipfile.ZipInfo(MANIFEST_NAME)
    stored.compress_type = zipfile.ZIP_STORED
    blob = bytearray(_raw_zip([(stored, _manifest_bytes()), *_valid_entries()[1:]]))
    central = blob.index(b"PK\x01\x02")
    declared = int.from_bytes(blob[central + 24:central + 28], "little")
    blob[central + 24:central + 28] = (declared + 1).to_bytes(4, "little")
    _rejects(bytes(blob), "실제 크기가 선언과 다릅니다")


def test_encrypted_entry_is_rejected() -> None:
    blob = bytearray(_raw_zip(_valid_entries()))
    central = blob.index(b"PK\x01\x02")
    blob[central + 8] |= 0x1  # general purpose flag: encrypted
    _rejects(bytes(blob), "암호화")


# ------------------------------------------------------------------ 자원 상한
def test_oversized_entry_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_package_io, "MAX_TEMPLATE_BYTES", len(HWPX_BYTES) - 1)
    _rejects(_raw_zip(_valid_entries()), "항목이 너무 큽니다")


def test_oversized_manifest_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_package_io, "MAX_MANIFEST_BYTES", 10)
    _rejects(_raw_zip(_valid_entries()), "항목이 너무 큽니다")


def test_oversized_total_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_package_io, "MAX_TOTAL_BYTES", len(HWPX_BYTES))
    _rejects(_raw_zip(_valid_entries()), "합계")


def test_too_many_entries_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_package_io, "MAX_ENTRIES", 2)
    _rejects(_raw_zip(_valid_entries()), "항목이 너무 많습니다")


def test_compression_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_package_io, "RATIO_MIN_ENTRY_BYTES", 1024)
    bomb = b"\0" * (4 * 1024 * 1024)
    bomb_digest = hashlib.sha256(bomb).hexdigest()
    entries = [*_valid_entries(), (f"templates/{bomb_digest}.txt", bomb)]
    _rejects(_raw_zip(entries), "압축률")


def test_oversized_archive_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "큰.narumi"
    write_work_package(path, _manifest(), _templates())
    monkeypatch.setattr(work_package_io, "MAX_ARCHIVE_BYTES", 16)
    with pytest.raises(WorkPackageError, match="너무 큽니다"):
        read_work_package(path)
    _rejects(path.read_bytes(), "너무 큽니다")


def test_directory_signature_flood_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(work_package_io, "MAX_DIRECTORY_SIGNATURES", 2)
    _rejects(_raw_zip(_valid_entries()), "서명")


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(WorkPackageError, match="열 수 없습니다"):
        read_work_package(tmp_path / "없음.narumi")
