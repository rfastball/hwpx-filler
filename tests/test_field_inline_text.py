"""누름틀 값의 인라인 요소 — 정본 판독·합성 쓰기·원장·필드 type 거름(#1080).

- H-1: 값 읽기·같은 값 판정·사후 검증이 ``hp:tab``/``hp:lineBreak`` 를 버리지 않는다.
- M-2: 값의 ``\\t``·``\\n``·U+2007 은 ``hp:tab``·``hp:lineBreak``·``hp:fwSpace`` 로 쓰여
  쓰기→읽기가 항등이다. CR LF 는 LF 로 접히고, 그 밖의 제어 문자는 변형 없이 거절된다.
- H-2: ``hp:t`` 의 미모델링 자식은 원장에 기록되고 같은 값 판정에서 같다고 보지 않는다.
- L-3: ``Paragraph.fields`` 에 BOOKMARK·(제품 거름 시) HYPERLINK 이름이 섞이지 않는다.
- L-7: 한 문서에서 빈 누름틀 여럿을 연달아 채운다.
"""

from __future__ import annotations

import pytest
from lxml import etree

from hwpxcore.field_occurrence import resolve_field_occurrences
from hwpxcore.native_admission import (
    FieldValueError,
    canonical_field_value,
    write_field_value_text,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.text_extract import (
    VALUE_INLINE_TEXT,
    CoverageLedger,
    InlineText,
    _blocks_from_container,
    extract_document,
    full_text,
    read_field_text,
    read_inline_text,
)
from hwpxfiller.domain.fields import (
    FieldDocument,
    FillNote,
    is_fill_target_field_type,
    read_fields,
)
from hwpxfiller.external.materialization_conformance import (
    FIELD_TEXT_MISMATCH,
    ConformanceFailure,
    ConformancePass,
    _occurrence_text,
    _read_field_values,
    verify_materialization_postconditions,
)
from tests._materialization_case import SECTION, CaseSpec, _build_case, _run

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
_HDR = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}" xmlns:x="urn:x">'
_ENTRY = "Contents/section0.xml"


def _field_xml(region: str, name: str = "F") -> bytes:
    """begin~end 사이에 ``region`` 을 끼운 단일 누름틀 섹션."""
    return (
        f"{_HDR}<hp:p>"
        f'<hp:run charPrIDRef="7"><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f"{region}"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
        "</hp:p></hs:sec>"
    ).encode("utf-8")


def _t(inner: str) -> etree._Element:
    return etree.fromstring(f'<hp:t xmlns:hp="{HP}" xmlns:x="urn:x">{inner}</hp:t>')


def _package_bytes(section: bytes) -> HwpxPackage:
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[_ENTRY] = section
    return pkg


def _package(section_inner: str) -> HwpxPackage:
    return _package_bytes(f"{_HDR}{section_inner}</hs:sec>".encode("utf-8"))


def _value_t(xml: bytes) -> etree._Element:
    """단일 누름틀 섹션의 (합성됐을 수도 있는) 첫 값 ``hp:t``."""
    root = etree.fromstring(xml)
    (occurrence,) = resolve_field_occurrences(_ENTRY, root).require_usable()
    return occurrence.texts[0]


# ─── 정본 판독기 ─────────────────────────────────────────────────────────────────
def test_reader_projects_value_inline_elements():
    t = _t('가<hp:tab width="1668" leader="0" type="1"/>나<hp:lineBreak/>다<hp:fwSpace/>라')
    assert read_inline_text(t) == InlineText("가\t나\n다 라")
    assert read_inline_text(t).exact


def test_reader_treats_markpen_as_textless_and_comments_as_nothing():
    t = _t("가<hp:markpenBegin/>나<hp:markpenEnd/><!-- 주석 -->다")
    assert read_inline_text(t) == InlineText("가나다")


@pytest.mark.parametrize(
    ("inner", "text", "unmodelled"),
    (
        ("앞<x:unknown>x</x:unknown>뒤", "앞뒤", ("{urn:x}unknown",)),
        ("a<hp:nbSpace/>b", "ab", ("nbSpace",)),
        ('a<hp:insertBegin Id="1" TcId="2"/>b<hp:insertEnd Id="1" TcId="2"/>', "ab",
         ("insertBegin", "insertEnd")),
        ("a<hp:tab>x</hp:tab>b", "ab", ("tab",)),  # 내용을 품은 탭은 탭으로 읽지 않는다
        ("a<hp:fwSpace><hp:x/></hp:fwSpace>b", "ab", ("fwSpace",)),
    ),
)
def test_reader_names_unmodelled_children(inner: str, text: str, unmodelled: tuple):
    read = read_inline_text(_t(inner))
    assert read == InlineText(text, unmodelled)
    assert not read.exact


def test_field_reader_joins_fragments_and_unmodelled_names():
    read = read_field_text([_t("가<hp:tab/>"), _t("<hp:nbSpace/>나")])
    assert read == InlineText("가\t나", ("nbSpace",))


# ─── H-1: 세 읽기 지점이 같은 판독 ──────────────────────────────────────────────────
def test_h1_tab_is_not_lost_by_read_same_value_guard_and_postcheck():
    """재현: ``A<hp:tab/>B`` 를 "AB" 로 읽어 "AB" 채움이 무연산으로 끝나던 결함."""
    xml = _field_xml("<hp:run><hp:t>A<hp:tab/>B</hp:t></hp:run>")
    doc = FieldDocument(xml)
    assert doc.read_field("F") == "A\tB"

    occurrence = resolve_field_occurrences(_ENTRY, etree.fromstring(xml)).occurrences[0]
    assert _occurrence_text(occurrence) == InlineText("A\tB")
    assert full_text(extract_document(_package_bytes(xml))) == "A\tB"

    assert doc.set_field("F", "AB") is True
    assert doc.modified is True  # 과거: modified False, 탭 잔존
    out = doc.to_bytes()
    assert b"hp:tab" not in out
    assert FieldDocument(out).read_field("F") == "AB"
    assert doc.notes == []  # 값의 탭은 값 자체 — 「인라인 요소 제거」 노트가 아니다


def test_h1_same_tab_value_is_a_true_noop():
    xml = _field_xml('<hp:run><hp:t>A<hp:tab width="1668" leader="0" type="1"/>B</hp:t></hp:run>')
    doc = FieldDocument(xml)
    assert doc.set_field("F", "A\tB") is True
    assert doc.modified is False
    assert doc.to_bytes() == FieldDocument(xml).to_bytes()


# ─── M-2: 합성 쓰기 왕복 ──────────────────────────────────────────────────────────
_MIXED = "가\t나\n다 라"


def test_m2_value_controls_become_hangul_inline_elements():
    doc = FieldDocument(_field_xml("<hp:run><hp:t>구값</hp:t></hp:run>"))
    assert doc.set_field("F", _MIXED) is True
    out = doc.to_bytes()
    t = _value_t(out)
    assert etree.tostring(t, encoding="unicode", with_tail=False).endswith(
        '>가<hp:tab width="0" leader="0" type="1"/>나<hp:lineBreak/>다<hp:fwSpace/>라</hp:t>'
    )
    # 제어 문자가 날것으로 hp:t 에 남지 않는다
    assert all("\t" not in s and "\n" not in s for s in t.itertext())
    assert doc.read_field("F") == _MIXED
    assert FieldDocument(out).read_field("F") == _MIXED


@pytest.mark.parametrize(
    "value", ("\t", "\n\n", "\t머리", "꼬리\n", "a\t\tb", " ", "", "평문", "a\n\tb ")
)
def test_m2_write_read_is_identity(value: str):
    t = _t("")
    assert write_field_value_text(t, value) is (value != "")
    assert read_inline_text(t) == InlineText(value)
    reparsed = etree.fromstring(etree.tostring(t))
    assert read_inline_text(reparsed) == InlineText(value)


def test_writer_and_reader_maps_are_inverse():
    """쓰기 합성 요소가 판독기의 값 글자 요소와 정확히 같은 대응이다."""
    for local, char in VALUE_INLINE_TEXT.items():
        t = _t("")
        write_field_value_text(t, char)
        assert [etree.QName(c).localname for c in t] == [local]


def test_m2_refill_same_is_noop_and_different_rewrites():
    first = FieldDocument(_field_xml("<hp:run><hp:t>구값</hp:t></hp:run>"))
    first.set_field("F", _MIXED)
    filled = first.to_bytes()

    same = FieldDocument(filled)
    assert same.set_field("F", _MIXED) is True
    assert same.modified is False
    assert same.to_bytes() == FieldDocument(filled).to_bytes()

    other = FieldDocument(filled)
    assert other.set_field("F", "가\t나") is True
    assert other.modified is True
    assert other.notes == []
    t = _value_t(other.to_bytes())
    assert [etree.QName(c).localname for c in t] == ["tab"]
    assert FieldDocument(other.to_bytes()).read_field("F") == "가\t나"


def test_crlf_folds_to_lf_and_refill_is_noop():
    assert canonical_field_value("a\r\nb\rc\n") == "a\nb\nc\n"
    doc = FieldDocument(_field_xml("<hp:run><hp:t>구값</hp:t></hp:run>"))
    assert doc.set_field("F", "줄1\r\n줄2\r줄3") is True
    out = doc.to_bytes()
    assert b"&#13;" not in out and b"\r" not in out
    assert FieldDocument(out).read_field("F") == "줄1\n줄2\n줄3"
    again = FieldDocument(out)
    assert again.set_field("F", "줄1\r\n줄2\r줄3") is True
    assert again.modified is False


@pytest.mark.parametrize(
    ("value", "points"),
    (
        ("a\x0bb", ("U+000B",)),
        ("\x00", ("U+0000",)),
        ("x\x7f\x85", ("U+007F", "U+0085")),
        ("\x1f\x0c", ("U+000C", "U+001F")),
        ("￾", ("U+FFFE",)),
        ("\ud800", ("U+D800",)),
    ),
)
def test_other_control_characters_are_rejected_before_mutation(value: str, points: tuple):
    xml = _field_xml("<hp:run><hp:t>구<hp:markpenBegin/>값<hp:markpenEnd/></hp:t></hp:run>")
    doc = FieldDocument(xml)
    with pytest.raises(FieldValueError) as caught:
        doc.set_field("F", value)
    assert caught.value.code_points == points
    assert all(point in str(caught.value) for point in points)
    assert doc.modified is False
    assert doc.to_bytes() == FieldDocument(xml).to_bytes()  # 표지·값 그대로


def test_allowed_characters_pass_canonicalisation_unchanged():
    value = "탭\t줄\n고정 묶음 하이픈­기호 &<>"
    assert canonical_field_value(value) == value


# ─── H-2: 미모델링 자식 ──────────────────────────────────────────────────────────
def test_h2_unknown_child_never_compares_equal():
    """``앞<x:unknown>x</x:unknown>뒤`` 에 "앞뒤" 를 채워도 조용한 무연산이 아니다.

    같은 값으로 보지 않으므로 admission 을 거치고, 미지원 인라인 객체로 막혀 소리 나게
    기입 불가가 된다(바이트 불변).
    """
    xml = _field_xml("<hp:run><hp:t>앞<x:unknown>x</x:unknown>뒤</hp:t></hp:run>")
    doc = FieldDocument(xml)
    assert doc.read_field("F") == "앞뒤"
    assert doc.set_field("F", "앞뒤") is False
    assert doc.notes == [FillNote("F", "occurrence_unfillable")]
    assert doc.to_bytes() == FieldDocument(xml).to_bytes()


def test_h2_tracked_change_markers_are_rewritten_not_skipped():
    """변경 추적 표지는 글자를 정하지 못하므로 같은 글자여도 값을 다시 쓴다."""
    xml = _field_xml(
        '<hp:run><hp:t>A<hp:insertBegin Id="1" TcId="2"/>B<hp:insertEnd Id="1" TcId="2"/>'
        "</hp:t></hp:run>"
    )
    doc = FieldDocument(xml)
    assert doc.read_field("F") == "AB"
    assert doc.set_field("F", "AB") is True
    assert doc.modified is True
    assert doc.notes == [FillNote("F", "inline_stripped", ("insertBegin", "insertEnd"))]
    assert b"insertBegin" not in doc.to_bytes()


def test_h2_extraction_records_unmodelled_t_children():
    ledger = CoverageLedger()
    root = etree.fromstring(
        f'<sec xmlns:hp="{HP}" xmlns:x="urn:x"><hp:p><hp:run>'
        "<hp:t>앞<x:unknown>x</x:unknown>뒤</hp:t>"
        "<hp:t>a<hp:nbSpace/>b<hp:fwSpace/>c<hp:markpenBegin/>d<hp:markpenEnd/></hp:t>"
        "</hp:run></hp:p></sec>".encode()
    )
    (paragraph,) = _blocks_from_container(root, ledger, "sec")
    assert paragraph.text == "앞뒤ab cd"
    assert ledger.counts == {"{urn:x}unknown": 1, "nbSpace": 1}
    assert ledger.examples == {
        "{urn:x}unknown": "sec/p/run/t/unknown",
        "nbSpace": "sec/p/run/t/nbSpace",
    }


def test_h2_unmodelled_child_is_reported_as_unhandled():
    payload = extract_document(
        _package("<hp:p><hp:run><hp:t>앞<x:unknown>x</x:unknown>뒤</hp:t></hp:run></hp:p>")
    ).to_dict()
    assert payload["unhandled"] == {"{urn:x}unknown": 1}


# ─── L-3: Paragraph.fields type 거름 ─────────────────────────────────────────────
_TYPED_FIELDS = (
    "<hp:p>"
    '<hp:run><hp:ctrl><hp:fieldBegin id="1" type="BOOKMARK" name="구간"/></hp:ctrl></hp:run>'
    "<hp:run><hp:t>구간 글</hp:t></hp:run>"
    '<hp:run><hp:ctrl><hp:fieldBegin id="2" type="CLICK_HERE" name="계약명"/></hp:ctrl></hp:run>'
    "<hp:run><hp:t>값</hp:t></hp:run>"
    # 구간의 끝이 누름틀보다 먼저 와도 누름틀을 닫지 않는다(beginIDRef 짝)
    '<hp:run><hp:ctrl><hp:fieldEnd beginIDRef="1"/></hp:ctrl></hp:run>'
    "<hp:run><hp:t>값 뒤</hp:t></hp:run>"
    '<hp:run><hp:ctrl><hp:fieldEnd beginIDRef="2"/></hp:ctrl></hp:run>'
    '<hp:run><hp:ctrl><hp:fieldBegin id="3" type="HYPERLINK" name="링크"/></hp:ctrl></hp:run>'
    "<hp:run><hp:t>https://example.invalid</hp:t></hp:run>"
    '<hp:run><hp:ctrl><hp:fieldEnd beginIDRef="3"/></hp:ctrl></hp:run>'
    "</hp:p>"
)


def test_l3_bookmark_is_never_a_paragraph_field():
    (paragraph,) = extract_document(_package(_TYPED_FIELDS)).sections[0].blocks
    assert paragraph.fields == ["계약명", "링크"]


def test_l3_product_filter_keeps_only_fill_targets():
    doc = extract_document(_package(_TYPED_FIELDS), field_filter=is_fill_target_field_type)
    (paragraph,) = doc.sections[0].blocks
    assert paragraph.fields == ["계약명"]


def test_l3_field_end_for_unopened_begin_closes_nothing():
    inner = (
        "<hp:p>"
        '<hp:run><hp:ctrl><hp:fieldBegin id="5" name="이름"/></hp:ctrl></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd beginIDRef="99"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>값</hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd beginIDRef="5"/></hp:ctrl></hp:run>'
        "</hp:p>"
    )
    (paragraph,) = extract_document(_package(inner)).sections[0].blocks
    assert paragraph.fields == ["이름"]


# ─── L-7: 빈 누름틀 여럿 연속 채움 ────────────────────────────────────────────────
_EMPTY_FIELDS = (
    "<hp:p>"
    '<hp:run charPrIDRef="1"><hp:ctrl><hp:fieldBegin name="가"/></hp:ctrl></hp:run>'
    "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
    "<hp:run><hp:t> 사이 </hp:t></hp:run>"
    '<hp:run charPrIDRef="2"><hp:ctrl><hp:fieldBegin name="나"/></hp:ctrl></hp:run>'
    "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
    "</hp:p>"
    "<hp:p>"
    '<hp:run charPrIDRef="3"><hp:ctrl><hp:fieldBegin name="다"/></hp:ctrl>'
    "<hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
    "</hp:p>"
    "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p>"
    '<hp:run><hp:ctrl><hp:fieldBegin name="라"/></hp:ctrl></hp:run>'
    "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>"
    "</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
)


def test_l7_consecutive_fills_of_several_empty_fields():
    values = {"가": "첫째", "나": "둘\t째", "다": "셋\n째", "라": "넷 째"}
    doc = FieldDocument(f"{_HDR}{_EMPTY_FIELDS}</hs:sec>".encode())
    for name, value in values.items():
        assert doc.set_field(name, value) is True
        assert doc.read_field(name) == value
    # 뒤의 합성이 앞 자리를 흔들지 않았다
    assert dict(doc.field_values()) == values
    assert doc.notes == [FillNote(name, "slot_synthesized") for name in values]
    out = doc.to_bytes()

    pkg = _package_bytes(out)
    assert read_fields(pkg) == values
    assert full_text(extract_document(pkg)) == "첫째 사이 둘\t째\n셋\n째\n넷 째"

    again = FieldDocument(out)
    for name, value in values.items():
        assert again.set_field(name, value) is True
    assert again.modified is False
    assert again.notes == []


# ─── 사후 검증(materialization conformance) ──────────────────────────────────────
def _inline_case() -> CaseSpec:
    return CaseSpec(
        root_fields=("본문", "줄"),
        bindings={"본문": ("SOURCE", "k본문"), "줄": ("CONST", "첫\r\n둘")},
        source_values={"k본문": _MIXED},
    )


def test_conformance_passes_synthesized_inline_values():
    case = _build_case(_inline_case())
    output = _run(case)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=output, plan=case.plan,
        structure=case.structure, vdr=case.vdr,
    )
    assert isinstance(result, ConformancePass), result
    values = dict(_read_field_values(HwpxPackage.from_bytes(output)))
    assert values == {"본문": _MIXED, "줄": "첫\n둘"}
    section = HwpxPackage.from_bytes(output).entries[SECTION]
    assert b'<hp:tab width="0" leader="0" type="1"/>' in section
    assert b"<hp:fwSpace/>" in section


def _tamper(output: bytes, old: bytes, new: bytes) -> bytes:
    pkg = HwpxPackage.from_bytes(output)
    assert old in pkg.entries[SECTION]
    pkg.entries[SECTION] = pkg.entries[SECTION].replace(old, new, 1)
    return pkg.to_bytes()


@pytest.mark.parametrize(
    ("old", "new"),
    (
        # 탭이 빠진 값 — 과거 itertext 판독은 "가나…" 를 그대로 대조했다
        (b'<hp:tab width="0" leader="0" type="1"/>', b""),
        # 글자는 같지만 판독하지 못한 요소가 남은 값 — 과거엔 거짓 통과
        (b"<hp:fwSpace/>", b"<hp:fwSpace/><hp:nbSpace/>"),
    ),
)
def test_conformance_rejects_lost_or_unreadable_inline(old: bytes, new: bytes):
    case = _build_case(_inline_case())
    tampered = _tamper(_run(case), old, new)
    result = verify_materialization_postconditions(
        source_bytes=case.bytes, output_bytes=tampered, plan=case.plan,
        structure=case.structure, vdr=case.vdr,
    )
    assert isinstance(result, ConformanceFailure)
    assert result.code == FIELD_TEXT_MISMATCH
