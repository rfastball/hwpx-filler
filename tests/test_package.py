from __future__ import annotations

import io
import warnings
import zipfile
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage, to_package
from hwpxfiller.external.hwpx_package_io import read_hwpx_package, write_hwpx_package

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
        [(MIMETYPE_NAME, MIMETYPE_VALUE, zipfile.ZIP_BZIP2), VALID_SECTION],
        "압축 방식",
        id="unsupported-mimetype-compression",
    ),
    pytest.param(
        [VALID_MIMETYPE, VALID_SECTION, VALID_SECTION],
        "중복 ZIP 엔트리",
        id="duplicate-entry",
    ),
]

DANGEROUS_NAMES = [
    pytest.param("", id="empty"),
    pytest.param("/absolute.xml", id="posix-absolute"),
    pytest.param("C:/absolute.xml", id="windows-drive-absolute"),
    pytest.param("C:drive-relative.xml", id="windows-drive-relative"),
    pytest.param("../escape.xml", id="parent-prefix"),
    pytest.param("Contents/../../escape.xml", id="parent-nested"),
    pytest.param(r"Contents\..\escape.xml", id="backslash-traversal"),
]


def test_open_reads_entries():
    pkg = read_hwpx_package(FIXTURE)
    assert MIMETYPE_NAME in pkg.entries
    assert pkg.entries[MIMETYPE_NAME] == b"application/hwp+zip"
    assert any(n.startswith("Contents/") for n in pkg.entries)


def test_roundtrip_preserves_ocf_rules():
    pkg = HwpxPackage.from_bytes(FIXTURE.read_bytes())
    serialized = pkg.to_bytes()
    assert pkg.to_bytes() == serialized
    assert HwpxPackage.from_bytes(serialized).to_bytes() == serialized

    with zipfile.ZipFile(io.BytesIO(serialized)) as zf:
        infos = zf.infolist()
        # mimetype 은 반드시 첫 엔트리 + 무압축
        assert infos[0].filename == MIMETYPE_NAME
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
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


def test_save_failure_leaves_existing_file_intact(tmp_path, monkeypatch):
    """RC-01 — 직렬화(to_bytes) 실패가 기존 산출물을 truncate 로 파괴하지 않는다.

    path adapter는 페이로드를 선평가 + 임시 파일 원자 교체하므로, 어떤 단계가
    실패해도 기존 파일 바이트가 그대로 남는다(잔해 임시 파일도 없음).
    """
    pkg = read_hwpx_package(FIXTURE)
    out = tmp_path / "doc.hwpx"
    write_hwpx_package(out, pkg)
    existing = out.read_bytes()
    assert existing[:2] == b"PK"

    def _boom(self):
        raise RuntimeError("직렬화 실패 주입")

    monkeypatch.setattr(HwpxPackage, "to_bytes", _boom)
    with pytest.raises(RuntimeError):
        write_hwpx_package(out, pkg)
    assert out.read_bytes() == existing                       # 기존 파일 무손상
    assert [p.name for p in tmp_path.iterdir()] == ["doc.hwpx"]  # 임시 파일 잔해 없음


def test_content_xml_names_targets_only_sections_headers_footers():
    pkg = HwpxPackage.from_bytes(FIXTURE.read_bytes())
    targets = pkg.content_xml_names()
    assert any("section" in t.lower() for t in targets)
    for t in targets:
        base = t.lower().rsplit("/", 1)[-1]
        assert base.startswith(("section", "header", "footer"))
        assert base.endswith(".xml")


def test_to_package_is_the_single_normalization_entrance():
    """kernel 정규화는 package/bytes만 받고 path는 loud 거절한다(P3-03 #591).

    path는 External adapter만 열어야 하므로 str/Path 수용 뒷문을 함께 막는다.
    """
    pkg = HwpxPackage.from_bytes(FIXTURE.read_bytes())
    assert to_package(pkg) is pkg                      # 이미 열린 package 는 통과
    from_bytes = to_package(pkg.to_bytes())            # bytes → from_bytes
    assert from_bytes.entries.keys() == pkg.entries.keys()
    for unsupported in (FIXTURE, str(FIXTURE), 1234):
        with pytest.raises(TypeError, match="지원하지 않는 입력"):
            to_package(unsupported)
