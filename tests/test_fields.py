from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.fields import FieldDocument, read_fields
from hwpxcore.package import HwpxPackage

FIXTURE = Path(__file__).parent / "fixtures" / "template_v1.hwpx"


def _first_doc_with_fields():
    pkg = HwpxPackage.open(str(FIXTURE))
    for name in pkg.content_xml_names():
        doc = FieldDocument(pkg.entries[name])
        fields = doc.required_fields()
        if fields:
            return FieldDocument(pkg.entries[name]), fields
    raise AssertionError("픽스처에 누름틀이 없습니다")


def test_required_fields_nonempty_and_unbraced():
    _, fields = _first_doc_with_fields()
    assert fields
    for f in fields:
        assert "{{" not in f and "}}" not in f


def test_set_field_injects_value_and_reparse_confirms():
    doc, fields = _first_doc_with_fields()
    target = fields[0]
    sentinel = "TESTVALUE_12345"

    assert doc.set_field(target, sentinel) is True
    assert doc.modified is True

    # 재직렬화 후 다시 파싱해도 값이 살아있는지
    reparsed = FieldDocument(doc.to_bytes())
    xml_text = reparsed.to_bytes().decode("utf-8")
    assert sentinel in xml_text


def test_read_field_reassembles_text_fragments():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
            xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
      <hp:p>
        <hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run>
        <hp:run><hp:t>정보</hp:t></hp:run>
        <hp:run><hp:t>시스템</hp:t><hp:t> 구축</hp:t></hp:run>
        <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
      </hp:p>
    </hs:sec>""".encode()
    assert FieldDocument(xml).read_field("계약명") == "정보시스템 구축"


def test_read_field_returns_placeholder_literal_and_none_for_unknown():
    doc, fields = _first_doc_with_fields()
    target = fields[0]
    placeholder = f"{{{{{target}}}}}"
    assert doc.set_field(target, placeholder) is True
    assert doc.read_field(target) == placeholder
    assert doc.read_field("존재하지않는필드명_zzz") is None


def test_set_then_read_roundtrip():
    doc, fields = _first_doc_with_fields()
    target = fields[0]
    value = "파편 경계 라운드트립"
    assert doc.set_field(target, value) is True
    assert FieldDocument(doc.to_bytes()).read_field(target) == value


def test_read_fields_collects_values_from_package():
    pkg = HwpxPackage.open(str(FIXTURE))
    for xml_name in pkg.content_xml_names():
        doc = FieldDocument(pkg.entries[xml_name])
        names = doc.required_fields()
        if not names:
            continue
        target = names[0]
        assert doc.set_field(target, "PACKAGE_VALUE") is True
        pkg.entries[xml_name] = doc.to_bytes()
        break
    else:
        raise AssertionError("픽스처에 누름틀이 없습니다")

    assert read_fields(pkg)[target] == "PACKAGE_VALUE"


def test_set_field_unknown_returns_false():
    doc, _ = _first_doc_with_fields()
    assert doc.set_field("존재하지않는필드명_zzz", "x") is False


def test_output_is_valid_xml_with_declaration():
    doc, _ = _first_doc_with_fields()
    out = doc.to_bytes()
    assert out.startswith(b"<?xml")
    assert b"UTF-8" in out[:60]


# ------------------------------------------------------- stale 줄배치 캐시(#95)
_LINESEG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p>
    <hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run>
    <hp:run><hp:t>기존값</hp:t></hp:run>
    <hp:run><hp:t/></hp:run>
    <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    <hp:linesegarray><hp:lineseg textpos="0"/></hp:linesegarray>
  </hp:p>
  <hp:p><hp:run><hp:t>무관 문단</hp:t></hp:run><hp:linesegarray/></hp:p>
</hs:sec>""".encode()


def test_to_bytes_preserves_lineseg_when_unmodified():
    """미변경 문서의 줄배치 캐시는 여전히 유효 — 보존한다(#95)."""
    assert b"linesegarray" in FieldDocument(_LINESEG_XML).to_bytes()


def test_refill_with_identical_value_is_not_a_modification():
    """동일 값 재채움(무변경 재생성)은 변형이 아니다 — 유효 캐시를 잃지 않는다(#95).

    반환값은 매칭 보고용이라 여전히 True(unmatched 오보 방지).
    """
    doc = FieldDocument(_LINESEG_XML)
    assert doc.set_field("계약명", "기존값") is True  # 픽스처의 현재 값 그대로
    assert doc.modified is False
    assert b"linesegarray" in doc.to_bytes()  # 캐시 보존
    # 직렬화까지 무변형 — 빈 파편 <hp:t/> 에 대한 무조건 "" 대입 churn 도 없다
    assert doc.to_bytes() == FieldDocument(_LINESEG_XML).to_bytes()


def test_to_bytes_strips_stale_lineseg_after_set_field():
    """채움으로 변형된 문서는 섹션 전체의 stale 캐시를 스트립한다(#95)."""
    doc = FieldDocument(_LINESEG_XML)
    assert doc.set_field("계약명", "새값") is True
    out = doc.to_bytes()
    assert b"linesegarray" not in out
    # 스트립이 필드·본문을 훼손하지 않는다
    assert FieldDocument(out).read_field("계약명") == "새값"
    assert "무관 문단" in out.decode("utf-8")
