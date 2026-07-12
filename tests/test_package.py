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


def test_save_failure_leaves_existing_file_intact(tmp_path, monkeypatch):
    """RC-01 — 직렬화(to_bytes) 실패가 기존 산출물을 truncate 로 파괴하지 않는다.

    save 는 페이로드를 open 전에 선평가 + 임시 파일 원자 교체이므로, 어떤 단계가
    실패해도 기존 파일 바이트가 그대로 남는다(잔해 임시 파일도 없음).
    """
    import pytest

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
