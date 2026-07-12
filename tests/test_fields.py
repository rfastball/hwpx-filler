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
