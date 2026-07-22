from __future__ import annotations

import io
import warnings
import zipfile
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"


def _zip_blob(entries: "list[tuple[str, bytes, int]]") -> bytes:
    """순서·압축·중복 이름까지 보존하는 적대 ZIP 생성기."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf, warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # duplicate-name fixture
        for name, data, compress_type in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = compress_type
            zf.writestr(info, data)
    return buf.getvalue()


VALID_MIMETYPE = (MIMETYPE_NAME, MIMETYPE_VALUE, zipfile.ZIP_STORED)
VALID_SECTION = ("Contents/section0.xml", b"<section/>", zipfile.ZIP_DEFLATED)

INVALID_ARCHIVES = [
    pytest.param([VALID_SECTION], "mimetype 엔트리 없음", id="missing-mimetype"),
    pytest.param(
        [(MIMETYPE_NAME, b"application/zip", zipfile.ZIP_STORED), VALID_SECTION],
        "mimetype 값",
        id="wrong-mimetype-value",
    ),
    pytest.param(
        [VALID_SECTION, VALID_MIMETYPE],
        "첫 항목",
        id="mimetype-not-first",
    ),
    pytest.param(
        [VALID_MIMETYPE, VALID_SECTION, VALID_SECTION],
        "중복 ZIP 엔트리",
        id="duplicate-entry",
    ),
]

DANGEROUS_NAMES = [
    pytest.param("/absolute.xml", id="posix-absolute"),
    pytest.param("C:/absolute.xml", id="windows-drive-absolute"),
    pytest.param("C:drive-relative.xml", id="windows-drive-relative"),
    pytest.param("../escape.xml", id="parent-prefix"),
    pytest.param("Contents/../../escape.xml", id="parent-nested"),
    pytest.param(r"Contents\..\escape.xml", id="backslash-traversal"),
]


def test_open_reads_entries():
    pkg = HwpxPackage.open(str(FIXTURE))
    assert MIMETYPE_NAME in pkg.entries
    assert pkg.entries[MIMETYPE_NAME] == b"application/hwp+zip"
    assert any(n.startswith("Contents/") for n in pkg.entries)


def test_roundtrip_preserves_ocf_rules(tmp_path):
    pkg = HwpxPackage.open(str(FIXTURE))
    out = tmp_path / "rt.hwpx"
    pkg.save(str(out))

    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
        # mimetype 은 반드시 첫 엔트리 + 무압축
        assert infos[0].filename == MIMETYPE_NAME
        assert infos[0].compress_type == zipfile.ZIP_STORED
        # 엔트리 집합 보존
        names = {i.filename for i in infos}
        assert names == set(pkg.entries)


def test_compressed_mimetype_is_accepted_then_normalized_to_stored():
    legacy_blob = _zip_blob(
        [
            (MIMETYPE_NAME, MIMETYPE_VALUE, zipfile.ZIP_DEFLATED),
            VALID_SECTION,
        ]
    )

    normalized = HwpxPackage.from_bytes(legacy_blob).to_bytes()

    with zipfile.ZipFile(io.BytesIO(normalized)) as zf:
        assert zf.infolist()[0].filename == MIMETYPE_NAME
        assert zf.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert zf.read(MIMETYPE_NAME) == MIMETYPE_VALUE


@pytest.mark.parametrize(("entries", "message"), INVALID_ARCHIVES)
def test_open_rejects_invalid_ocf_contract(entries, message):
    with pytest.raises(ValueError, match=message):
        HwpxPackage.from_bytes(_zip_blob(entries))


@pytest.mark.parametrize("name", DANGEROUS_NAMES)
def test_open_rejects_dangerous_zip_entry_names(name):
    entries = [VALID_MIMETYPE, (name, b"payload", zipfile.ZIP_DEFLATED)]
    with pytest.raises(ValueError):
        HwpxPackage.from_bytes(_zip_blob(entries))


@pytest.mark.parametrize(("entries", "message"), INVALID_ARCHIVES)
def test_rejection_leaves_source_and_existing_output_unchanged(
    tmp_path, entries, message
):
    _assert_rejection_preserves_files(tmp_path, _zip_blob(entries), message)


@pytest.mark.parametrize("name", DANGEROUS_NAMES)
def test_dangerous_path_rejection_leaves_files_unchanged(tmp_path, name):
    blob = _zip_blob(
        [VALID_MIMETYPE, (name, b"payload", zipfile.ZIP_DEFLATED)]
    )
    _assert_rejection_preserves_files(tmp_path, blob)


def _assert_rejection_preserves_files(tmp_path, source_before, message=None):
    source = tmp_path / "hostile.hwpx"
    output = tmp_path / "existing.hwpx"
    output_before = b"existing output must survive"
    source.write_bytes(source_before)
    output.write_bytes(output_before)

    with pytest.raises(ValueError, match=message):
        HwpxPackage.open(str(source)).save(str(output))

    assert source.read_bytes() == source_before
    assert output.read_bytes() == output_before
    assert {path.name for path in tmp_path.iterdir()} == {source.name, output.name}


def test_save_failure_leaves_existing_file_intact(tmp_path, monkeypatch):
    """RC-01 — 직렬화(to_bytes) 실패가 기존 산출물을 truncate 로 파괴하지 않는다.

    save 는 페이로드를 open 전에 선평가 + 임시 파일 원자 교체이므로, 어떤 단계가
    실패해도 기존 파일 바이트가 그대로 남는다(잔해 임시 파일도 없음).
    """
    pkg = HwpxPackage.open(str(FIXTURE))
    out = tmp_path / "doc.hwpx"
    pkg.save(str(out))
    existing = out.read_bytes()
    assert existing[:2] == b"PK"

    def _boom(self):
        raise RuntimeError("직렬화 실패 주입")

    monkeypatch.setattr(HwpxPackage, "to_bytes", _boom)
    with pytest.raises(RuntimeError):
        pkg.save(str(out))
    assert out.read_bytes() == existing                       # 기존 파일 무손상
    assert [p.name for p in tmp_path.iterdir()] == ["doc.hwpx"]  # 임시 파일 잔해 없음


def test_content_xml_names_targets_only_sections_headers_footers():
    pkg = HwpxPackage.open(str(FIXTURE))
    targets = pkg.content_xml_names()
    assert any("section" in t.lower() for t in targets)
    for t in targets:
        base = t.lower().rsplit("/", 1)[-1]
        assert base.startswith(("section", "header", "footer"))
        assert base.endswith(".xml")
