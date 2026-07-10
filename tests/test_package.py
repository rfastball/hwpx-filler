from __future__ import annotations

import zipfile
from pathlib import Path

from hwpxcore.package import MIMETYPE_NAME, HwpxPackage

FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"


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


def test_content_xml_names_targets_only_sections_headers_footers():
    pkg = HwpxPackage.open(str(FIXTURE))
    targets = pkg.content_xml_names()
    assert any("section" in t.lower() for t in targets)
    for t in targets:
        base = t.lower().rsplit("/", 1)[-1]
        assert base.startswith(("section", "header", "footer"))
        assert base.endswith(".xml")
