"""파일 불문 INVARIANTS — tests/corpus/real/ 모든 파일에서 성립해야 한다.

추출기의 가장 중요한 안전장치: 원문 ``hp:t`` 텍스트가 조용히 사라지지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from hwpxcore.package import HwpxPackage
from hwpxcore.text_extract import (
    extract_document,
    full_text,
    section_xml_names,
)

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
CORPUS = Path(__file__).parent / "corpus" / "real"
REAL_FILES = sorted(CORPUS.glob("*.hwpx"))


def _raw_text_segments(pkg: HwpxPackage) -> "list[str]":
    """섹션 XML 에서 원문 ``hp:t`` 텍스트 조각(본문 + 자식 tail)을 lxml 로 독립 추출."""
    segments: "list[str]" = []
    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name])
        for t in root.iter(f"{{{HP_NS}}}t"):
            if t.text:
                segments.append(t.text)
            for child in t:
                if child.tail:
                    segments.append(child.tail)
    return segments


def test_corpus_not_empty():
    assert REAL_FILES, "코퍼스에 실제 HWPX 파일이 없다"


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_no_silent_text_drop(path: Path):
    """모든 비공백 ``hp:t`` 조각이 추출 결과 어딘가에 나타나야 한다(무결성 핵심)."""
    pkg = HwpxPackage.open(str(path))
    doc = extract_document(pkg)
    haystack = full_text(doc)
    for seg in _raw_text_segments(pkg):
        needle = seg.strip()
        if needle:
            assert needle in haystack, f"원문 텍스트 누락: {needle!r} ({path.name})"


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_coverage_ledger_empty(path: Path):
    """모든 자식 태그가 결정 지점에서 처리 또는 명시 허용됐다(원장 비어 있음).

    새 HWPX 요소가 등장하면 침묵 누락이 아니라 여기서 실패한다 — 의식적 결정 강제.
    """
    doc = extract_document(str(path))
    assert doc.unhandled == {}, (
        f"미처리 구조 발견 {path.name}: {doc.unhandled} "
        f"(예: {doc.unhandled_examples}). 처리 브랜치 추가 또는 KNOWN_IGNORED 허용목록에 "
        f"이유와 함께 등록할 것."
    )


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_deterministic(path: Path):
    """같은 파일을 두 번 추출하면 to_dict() 가 완전히 동일하다."""
    first = extract_document(str(path)).to_dict()
    second = extract_document(str(path)).to_dict()
    assert first == second


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_container_round_trip(path: Path):
    """open -> to_bytes -> reopen 이 엔트리와 mimetype-우선/STORED 규칙을 보존한다."""
    import io
    import zipfile

    pkg = HwpxPackage.open(str(path))
    blob = pkg.to_bytes()
    reopened = HwpxPackage.from_bytes(blob)

    assert set(reopened.entries) == set(pkg.entries)
    for name, data in pkg.entries.items():
        assert reopened.entries[name] == data, f"엔트리 내용 불일치: {name}"

    # mimetype 은 첫 항목이며 무압축(STORED).
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.namelist()[0] == "mimetype", "mimetype 이 첫 엔트리가 아니다"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_paragraph_order_matches_document_order(path: Path):
    """추출한 문단 텍스트 순서가 원문 ``hp:t`` 등장 순서와 일치한다.

    원문에서 (누름틀 파라미터 등 ``hp:ctrl`` 하위를 제외한) ``hp:t`` 텍스트를 문서
    순서대로 뽑아, 추출 전체 텍스트에서 각 조각이 단조 증가 위치에 나타나는지 본다.
    """
    pkg = HwpxPackage.open(str(path))
    doc = extract_document(pkg)
    haystack = full_text(doc)

    # 원문 hp:t 를 문서 순서로 순회하되, hp:ctrl(필드 파라미터 문자열) 하위는 제외.
    ordered: "list[str]" = []
    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name])
        for t in root.iter(f"{{{HP_NS}}}t"):
            anc = t.getparent()
            under_ctrl = False
            while anc is not None:
                if anc.tag == f"{{{HP_NS}}}ctrl":
                    under_ctrl = True
                    break
                anc = anc.getparent()
            if under_ctrl:
                continue
            txt = (t.text or "").strip()
            if txt:
                ordered.append(txt)

    # 각 조각이 추출 텍스트에서 단조 증가 위치에 나타나야 한다(순서 보존 증명).
    last = -1
    for seg in ordered:
        idx = haystack.find(seg, last + 1)
        assert idx != -1, f"문단 순서 이탈: {seg!r} ({path.name})"
        last = idx
