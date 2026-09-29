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
from hwpxfiller.external.hwpx_package_io import read_hwpx_package

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
CORPUS = Path(__file__).parent / "corpus" / "real"
REAL_FILES = sorted(CORPUS.glob("*.hwpx"))


def _raw_text_segments(pkg: HwpxPackage) -> "list[str]":
    """섹션 XML 에서 ``hp:t`` 안의 **모든** 문자 데이터 조각을 lxml 로 독립 추출.

    본문·자식 tail 뿐 아니라 자식 요소 **내부**의 글자까지 모은다(#1080). 추출기가 미모델링
    자식의 내용을 투영에서 빼므로, 그런 자식이 코퍼스에 나타나면 이 기대값이 그것을 요구해
    소리 나게 실패한다 — 판독기와 같은 사각(자식 내용 무시)을 공유하지 않는다.
    """
    segments: "list[str]" = []
    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name])
        for t in root.iter(f"{{{HP_NS}}}t"):
            segments.extend(s for s in t.itertext() if s)
    return segments


#: 판독기 정책과 **독립으로** 적은 ``hp:t`` 안 인라인 요소 → 기대 글자. 여기 없는 요소가
#: 실 코퍼스 ``hp:t`` 에 나타나면 아래 테스트가 새 결정을 요구한다.
_EXPECTED_T_CHILDREN = {
    "tab": "\t",
    "lineBreak": "\n",
    "fwSpace": " ",
    "markpenBegin": "",
    "markpenEnd": "",
}


def _section_texts(doc) -> str:
    """본문 섹션만의 문단 텍스트(머리말·꼬리말 제외)를 모은다."""

    def walk(blocks):
        for block in blocks:
            if block["type"] == "paragraph":
                yield block["text"]
            else:
                for row in block["rows"]:
                    for cell in row:
                        yield from walk(cell["blocks"])

    return "".join(
        text for section in doc.to_dict()["sections"] for text in walk(section["blocks"])
    )


def test_corpus_not_empty():
    assert REAL_FILES, "코퍼스에 실제 HWPX 파일이 없다"


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_no_silent_text_drop(path: Path):
    """모든 비공백 ``hp:t`` 조각이 추출 결과 어딘가에 나타나야 한다(무결성 핵심)."""
    pkg = read_hwpx_package(path)
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
    doc = extract_document(read_hwpx_package(path))
    assert doc.unhandled == {}, (
        f"미처리 구조 발견 {path.name}: {doc.unhandled} "
        f"(예: {doc.unhandled_examples}). 처리 브랜치 추가 또는 KNOWN_IGNORED 허용목록에 "
        f"이유와 함께 등록할 것."
    )


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_inline_t_children_are_decided_and_projected(path: Path):
    """``hp:t`` 안 인라인 요소는 모두 의식적으로 결정됐고, 고정폭 빈칸은 U+2007 로 남는다.

    과거 판독기는 ``hp:fwSpace`` 를 조용히 버렸고 원장도 비어 있었다(#1080 H-2). 여기서는
    원문 XML 을 독립으로 세어 추출 텍스트의 U+2007 개수와 맞춘다.
    """
    pkg = read_hwpx_package(path)
    fw_spaces = 0
    for name in section_xml_names(pkg):
        root = etree.fromstring(pkg.entries[name])
        for t in root.iter(f"{{{HP_NS}}}t"):
            fw_spaces += (t.text or "").count(" ")
            for child in t:
                fw_spaces += (child.tail or "").count(" ")
                if not isinstance(child.tag, str):
                    continue
                local = etree.QName(child).localname
                assert local in _EXPECTED_T_CHILDREN, (
                    f"hp:t 안 새 인라인 요소 {local!r} ({path.name}) — 판독기 정책을 정할 것"
                )
                fw_spaces += local == "fwSpace"
    assert _section_texts(extract_document(pkg)).count(" ") == fw_spaces


def test_real_fw_space_is_modelled_not_dropped():
    """실 코퍼스의 ``hp:t`` 안 ``hp:fwSpace`` 2건이 텍스트에 남고 원장은 비어 있다."""
    pkg = read_hwpx_package(CORPUS / "spec_revision_2025.hwpx")
    raw = sum(
        len(etree.fromstring(pkg.entries[name]).findall(f".//{{{HP_NS}}}t/{{{HP_NS}}}fwSpace"))
        for name in section_xml_names(pkg)
    )
    doc = extract_document(pkg)
    assert raw == 2
    assert full_text(doc).count(" ") == 2
    assert doc.unhandled == {}


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_deterministic(path: Path):
    """같은 파일을 두 번 추출하면 to_dict() 가 완전히 동일하다."""
    first = extract_document(read_hwpx_package(path)).to_dict()
    second = extract_document(read_hwpx_package(path)).to_dict()
    assert first == second


@pytest.mark.parametrize("path", REAL_FILES, ids=lambda p: p.name)
def test_container_round_trip(path: Path):
    """open -> to_bytes -> reopen 이 엔트리와 mimetype-우선/STORED 규칙을 보존한다."""
    import io
    import zipfile

    pkg = read_hwpx_package(path)
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
    pkg = read_hwpx_package(path)
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
