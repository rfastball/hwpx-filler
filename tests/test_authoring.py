"""저작 보조(토큰→누름틀 컴파일) 테스트 — 라운드트립·멱등·명시성·충실도.

핵심 증명: 작성자가 타이핑한 평문 ``{{X}}`` 를 컴파일하면 기존 파이프라인(schema 인식 +
fields 채우기)이 그대로 동작하고, 재컴파일은 무해(멱등)하다.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from hwpxfiller.core.authoring import compile_document, scan_tokens
from hwpxfiller.core.fields import FieldDocument
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.core.schema import extract_schema

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
CORPUS = Path(__file__).parent / "corpus" / "real"


def _pkg(section_inner: str) -> HwpxPackage:
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec
    return pkg


def _root(pkg: HwpxPackage) -> etree._Element:
    return etree.fromstring(pkg.entries["Contents/section0.xml"])


# --------------------------------------------------------------- 미리보기(scan)
def test_scan_is_readonly_and_lists_compilable():
    """scan 은 워크북을 변형하지 않고 컴파일 가능한 토큰을 나열한다(명시성: 미리보기)."""
    xml = '<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>'
    pkg = _pkg(xml)
    before = pkg.entries["Contents/section0.xml"]
    sites = scan_tokens(pkg)
    assert pkg.entries["Contents/section0.xml"] == before  # 무변형
    assert [(s.name, s.compilable) for s in sites] == [("계약명", True)]
    assert sites[0].context == "계약명: {{계약명}}"


# ------------------------------------------------------------- 컴파일 + 라운드트립
def test_compile_makes_token_a_real_field():
    """토큰이 진짜 누름틀이 되어 스키마가 인식한다."""
    xml = '<hp:p><hp:run><hp:t>{{공고명}}</hp:t></hp:run></hp:p>'
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["공고명"]
    assert report.modified is True
    assert extract_schema(pkg).field_names() == ["공고명"]


def test_roundtrip_compile_then_fill():
    """컴파일된 필드를 fields.set_field 로 채우면 값이 들어간다(전체 파이프라인)."""
    xml = '<hp:p><hp:run><hp:t>계약명: {{계약명}} / 예산 {{사업예산}}</hp:t></hp:run></hp:p>'
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명", "사업예산"]

    doc = FieldDocument(pkg.entries["Contents/section0.xml"])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    assert doc.set_field("사업예산", "1억원") is True
    filled = doc.to_bytes().decode("utf-8")
    assert "정보시스템 구축" in filled and "1억원" in filled


def test_surrounding_text_preserved():
    """토큰 전후 평문과 순서가 보존된다."""
    xml = '<hp:p><hp:run><hp:t>앞 {{계약명}} 뒤</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    # 문단 전체 텍스트(placeholder 유지)가 원문과 동일해야 한다.
    from hwpxcore.text_extract import extract_document, full_text

    assert full_text(extract_document(pkg)) == "앞 {{계약명}} 뒤"


# ------------------------------------------------------------------- 충실도
def test_generated_field_mirrors_corpus_attrs_and_links():
    """생성 누름틀은 실코퍼스 속성(type=CLICK_HERE 등) + begin/end id 링크를 갖는다."""
    xml = '<hp:p><hp:run charPrIDRef="7"><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    root = _root(pkg)
    fb = root.find(f".//{{{HP}}}fieldBegin")
    fe = root.find(f".//{{{HP}}}fieldEnd")
    assert fb.get("type") == "CLICK_HERE"
    assert fb.get("name") == "계약명"
    assert fb.get("editable") == "1"
    # fieldEnd 가 fieldBegin 을 정확히 참조(id 링크 무결성).
    assert fe.get("beginIDRef") == fb.get("id")
    assert fe.get("fieldid") == fb.get("fieldid")
    # 생성 런들이 원본 서식(charPrIDRef)을 승계.
    for run in root.iter(f"{{{HP}}}run"):
        assert run.get("charPrIDRef") == "7"


def test_generated_ids_do_not_collide_with_existing():
    """id 는 기존 정수 id 최댓값 위에서 할당돼 충돌하지 않는다."""
    xml = (
        '<hp:p><hp:run charPrIDRef="1"><hp:t id="9000">{{계약명}}</hp:t></hp:run></hp:p>'
    )
    pkg, _ = compile_document(_pkg(xml))
    fb = _root(pkg).find(f".//{{{HP}}}fieldBegin")
    assert int(fb.get("id")) > 9000


# ------------------------------------------------------------------- 멱등성
def test_idempotent_recompile_noop():
    """이미 누름틀이 된 문서를 재컴파일하면 아무것도 바뀌지 않는다."""
    xml = '<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>'
    pkg, _ = compile_document(_pkg(xml))
    pkg2, report2 = compile_document(pkg)
    assert report2.compiled == []
    assert report2.modified is False


def test_token_already_in_field_not_recompiled():
    """이미 누름틀 값으로 든 ``{{X}}`` 는 이중 래핑하지 않는다(멱등의 핵심)."""
    xml = """
    <hp:p>
      <hp:run><hp:ctrl><hp:fieldBegin name="수요기관"/></hp:ctrl></hp:run>
      <hp:run><hp:t>{{수요기관}}</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    assert scan_tokens(_pkg(xml)) == []  # 이미 field 영역 안 → 미리보기에 안 뜸
    _, report = compile_document(_pkg(xml))
    assert report.compiled == []


# ----------------------------------------------------- 못 바꾸는 토큰 시끄럽게 신고
def test_split_token_reported_not_silently_dropped():
    """파편에 걸친 토큰은 조용히 넘기지 않고 skipped 로 신고한다."""
    xml = """
    <hp:p>
      <hp:run><hp:t>{{계약</hp:t></hp:run>
      <hp:run><hp:t>명}}</hp:t></hp:run>
    </hp:p>
    """
    _, report = compile_document(_pkg(xml))
    assert report.compiled == []
    assert any("파편" in s.reason for s in report.skipped)


# ------------------------------------------------------------- 실제 코퍼스 멱등
def test_corpus_already_compiled_yields_no_new_fields():
    """실제 입찰공고(이미 누름틀 완비)를 스캔하면 새로 컴파일할 토큰이 없다."""
    path = CORPUS / "bid_notice_limited_under100m.hwpx"
    compilable = [s for s in scan_tokens(str(path)) if s.compilable]
    assert compilable == []
