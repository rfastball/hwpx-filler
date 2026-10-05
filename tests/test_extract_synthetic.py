"""SYNTHETIC 엣지 케이스 — 손으로 만든 최소 ``hp:`` XML 조각으로 정밀 검증.

패키지 없이 XML 을 직접 파싱하도록 내부 헬퍼(``_blocks_from_container``)를 쓴다.
각 조각은 섹션 루트 한 개로 감싸 섹션 컨테이너처럼 다룬다.
"""

from __future__ import annotations

from lxml import etree

from hwpxcore.text_extract import (
    CoverageLedger,
    Document,
    Paragraph,
    Section,
    Table,
    TextBox,
    _blocks_from_container,
    _has_body_text,
    extract_document,
    iter_paragraph_texts,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC = "http://www.hancom.co.kr/hwpml/2011/core"


def _blocks(inner_xml: str, ledger: "CoverageLedger | None" = None):
    """``<sec>...</sec>`` 로 감싼 조각을 파싱해 최상위 블록 목록 반환."""
    xml = f'<sec xmlns:hp="{HP}" xmlns:hc="{HC}">{inner_xml}</sec>'
    root = etree.fromstring(xml.encode("utf-8"))
    return _blocks_from_container(root, ledger or CoverageLedger(), "sec")


def test_fragments_across_multiple_runs_join():
    """한 문단 텍스트가 3개 이상 런의 ``hp:t`` 로 쪼개져도 순서대로 이어붙는다."""
    xml = """
    <hp:p>
      <hp:run><hp:t>계약</hp:t></hp:run>
      <hp:run><hp:t>명은 </hp:t></hp:run>
      <hp:run><hp:t>홍길동</hp:t></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    assert len(blocks) == 1
    assert isinstance(blocks[0], Paragraph)
    assert blocks[0].text == "계약명은 홍길동"


def test_linebreak_and_tab_inside_t():
    """``hp:tab`` 은 \\t, ``hp:lineBreak`` 은 \\n 으로 복원(하나의 hp:t 혼합 콘텐츠)."""
    xml = """
    <hp:p>
      <hp:run><hp:t>가<hp:tab/>나<hp:lineBreak/>다</hp:t></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    assert blocks[0].text == "가\t나\n다"


def test_linebreak_and_tab_run_level():
    """런 직속 ``hp:tab``/``hp:lineBreak`` 도 처리한다."""
    xml = """
    <hp:p>
      <hp:run><hp:t>A</hp:t><hp:tab/><hp:t>B</hp:t><hp:lineBreak/><hp:t>C</hp:t></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    assert blocks[0].text == "A\tB\nC"


def test_empty_paragraph_preserved():
    """텍스트도 표도 없는 문단은 빈 Paragraph 로 보존된다."""
    xml = "<hp:p><hp:run/></hp:p>"
    blocks = _blocks(xml)
    assert len(blocks) == 1
    assert isinstance(blocks[0], Paragraph)
    assert blocks[0].text == ""


def test_cell_with_multiple_paragraphs_and_nested_table():
    """표 셀이 여러 문단을 갖고, 셀 안에 표가 중첩된 경우까지 복원한다."""
    xml = """
    <hp:p>
      <hp:run>
        <hp:tbl>
          <hp:tr>
            <hp:tc>
              <hp:subList>
                <hp:p><hp:run><hp:t>첫째 문단</hp:t></hp:run></hp:p>
                <hp:p><hp:run><hp:t>둘째 문단</hp:t></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
            <hp:tc>
              <hp:subList>
                <hp:p><hp:run>
                  <hp:tbl>
                    <hp:tr>
                      <hp:tc><hp:subList>
                        <hp:p><hp:run><hp:t>중첩셀</hp:t></hp:run></hp:p>
                      </hp:subList></hp:tc>
                    </hp:tr>
                  </hp:tbl>
                </hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl>
      </hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    assert len(blocks) == 1
    tbl = blocks[0]
    assert isinstance(tbl, Table)
    assert len(tbl.rows) == 1 and len(tbl.rows[0]) == 2

    cell0 = tbl.rows[0][0]
    texts0 = [b.text for b in cell0.blocks if isinstance(b, Paragraph)]
    assert texts0 == ["첫째 문단", "둘째 문단"]

    cell1 = tbl.rows[0][1]
    nested = [b for b in cell1.blocks if isinstance(b, Table)]
    assert len(nested) == 1
    inner_cell = nested[0].rows[0][0]
    assert inner_cell.blocks[0].text == "중첩셀"


def test_field_region_text_captured_and_recorded():
    """``hp:fieldBegin``/``fieldEnd`` 사이 텍스트는 잡히고, 소속 필드명이 기록된다."""
    xml = """
    <hp:p>
      <hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run>
      <hp:run><hp:t>정보시스템 구축</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    assert blocks[0].text == "정보시스템 구축"
    assert blocks[0].fields == ["계약명"]


def test_text_before_table_splits_into_separate_blocks():
    """문단 중간에 표가 오면 앞 텍스트가 별도 Paragraph 로 분리되고 순서가 보존된다."""
    xml = """
    <hp:p>
      <hp:run><hp:t>표 앞 문구</hp:t></hp:run>
      <hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>
        <hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p>
      </hp:subList></hp:tc></hp:tr></hp:tbl></hp:run>
      <hp:run><hp:t>표 뒤 문구</hp:t></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    assert [type(b).__name__ for b in blocks] == ["Paragraph", "Table", "Paragraph"]
    assert blocks[0].text == "표 앞 문구"
    assert blocks[2].text == "표 뒤 문구"


def test_random_ids_absent_from_output():
    """랜덤 ID(id, fieldid, charPrIDRef 등)는 to_dict() 출력에 전혀 남지 않는다."""
    import json

    xml = """
    <hp:p id="3121190098" paraPrIDRef="7" styleIDRef="2">
      <hp:run charPrIDRef="99">
        <hp:ctrl><hp:fieldBegin id="2073595120" fieldid="627272811" name="금액"/></hp:ctrl>
      </hp:run>
      <hp:run charPrIDRef="12"><hp:t>1,000,000원</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd instId="55"/></hp:ctrl></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml)
    dumped = json.dumps([b.to_dict() for b in blocks], ensure_ascii=False)
    for noise in ("3121190098", "2073595120", "627272811", "charPrIDRef", "paraPrIDRef", "instId", "styleIDRef"):
        assert noise not in dumped, f"랜덤 ID 누출: {noise}"
    assert blocks[0].text == "1,000,000원"
    assert blocks[0].fields == ["금액"]


def test_merged_cell_span_metadata_captured():
    """병합 셀의 ``cellSpan``(colSpan/rowSpan)·``cellAddr``(colAddr/rowAddr)가 보존된다."""
    xml = """
    <hp:p><hp:run>
      <hp:tbl>
        <hp:tr>
          <hp:tc>
            <hp:cellAddr colAddr="0" rowAddr="0"/>
            <hp:cellSpan colSpan="3" rowSpan="1"/>
            <hp:cellSz width="1000" height="500"/>
            <hp:subList><hp:p><hp:run><hp:t>병합 헤더</hp:t></hp:run></hp:p></hp:subList>
          </hp:tc>
        </hp:tr>
        <hp:tr>
          <hp:tc>
            <hp:cellAddr colAddr="0" rowAddr="1"/>
            <hp:cellSpan colSpan="1" rowSpan="2"/>
            <hp:subList><hp:p><hp:run><hp:t>세로병합</hp:t></hp:run></hp:p></hp:subList>
          </hp:tc>
        </hp:tr>
      </hp:tbl>
    </hp:run></hp:p>
    """
    blocks = _blocks(xml)
    tbl = blocks[0]
    assert isinstance(tbl, Table)
    top = tbl.rows[0][0]
    assert top.span == {"colSpan": 3, "rowSpan": 1}
    assert top.addr == {"colAddr": 0, "rowAddr": 0}
    bottom = tbl.rows[1][0]
    assert bottom.span == {"colSpan": 1, "rowSpan": 2}
    assert bottom.addr == {"colAddr": 0, "rowAddr": 1}
    # to_dict 결정적으로 병합 메타 노출.
    d = tbl.to_dict()
    assert d["rows"][0][0]["span"] == {"colSpan": 3, "rowSpan": 1}


def test_coverage_ledger_records_unknown_child():
    """결정 지점에 미지의 ``hp:`` 태그가 오면 원장에 소리 나게 기록된다."""
    ledger = CoverageLedger()
    # hp:p 직속에 처리도 허용목록도 아닌 hp:someNewThing 을 넣는다.
    xml = """
    <hp:p>
      <hp:run><hp:t>정상</hp:t></hp:run>
      <hp:someNewThing/>
    </hp:p>
    """
    _blocks(xml, ledger)
    assert ledger.counts.get("someNewThing") == 1
    assert "someNewThing" in ledger.examples


def test_coverage_ledger_clean_for_known_structure():
    """알려진 구조(run/t/linesegarray/tbl/셀 메타)는 원장을 더럽히지 않는다."""
    ledger = CoverageLedger()
    xml = """
    <hp:p>
      <hp:run><hp:t>가</hp:t><hp:secPr/></hp:run>
      <hp:linesegarray><hp:lineseg/></hp:linesegarray>
      <hp:run><hp:tbl>
        <hp:sz/><hp:pos/>
        <hp:tr><hp:tc>
          <hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellMargin/>
          <hp:subList><hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p></hp:subList>
        </hp:tc></hp:tr>
      </hp:tbl></hp:run>
    </hp:p>
    """
    _blocks(xml, ledger)
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_table_caption_text_extracted():
    """``hp:tbl`` 밑 ``hp:caption`` 의 본문 텍스트가 표 앞 문단으로 추출된다.

    캡션은 셀과 동형(``caption`` > ``subList`` > ``hp:p``)이며 표 앞(문서 순서)에 온다.
    이 처리를 끄면(캡션 미추출) 아래 캡션 문자열이 사라져 파일 레벨 무결성 테스트
    ``test_no_silent_text_drop`` 이 실패한다 — 즉 이 테스트는 하중을 진다.
    """
    ledger = CoverageLedger()
    xml = """
    <hp:p><hp:run>
      <hp:tbl>
        <hp:sz/><hp:pos/>
        <hp:caption>
          <hp:subList>
            <hp:p><hp:run><hp:t>&lt;표 1&gt; 유압식 잭(30톤) 주요제원</hp:t></hp:run></hp:p>
          </hp:subList>
        </hp:caption>
        <hp:tr><hp:tc><hp:subList>
          <hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p>
        </hp:subList></hp:tc></hp:tr>
      </hp:tbl>
    </hp:run></hp:p>
    """
    blocks = _blocks(xml, ledger)
    # 캡션 문단이 표 블록 앞에 문서 순서로 배치된다.
    assert [type(b).__name__ for b in blocks] == ["Paragraph", "Table"]
    assert isinstance(blocks[0], Paragraph)
    assert blocks[0].text == "<표 1> 유압식 잭(30톤) 주요제원"
    assert isinstance(blocks[1], Table)
    # 캡션 처리로 원장이 더럽혀지지 않는다(caption/subList 는 명시 처리).
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_pic_object_no_text_keeps_ledger_clean():
    """런 안의 캡션 없는 그림 객체 ``hp:pic`` 은 본문 텍스트가 없고 원장을 더럽히지 않는다.

    pic 의 이미지·기하 자식은 도형 결정표의 허용 메타라 유령 텍스트를 만들지 않고, 블록이
    없으니 문단도 쪼개지 않는다.
    """
    ledger = CoverageLedger()
    xml = """
    <hp:p>
      <hp:run><hp:t>본문 문구</hp:t></hp:run>
      <hp:run><hp:pic><hp:img/><hp:sz/><hp:pos/><hp:shapeComment/></hp:pic></hp:run>
    </hp:p>
    """
    blocks = _blocks(xml, ledger)
    assert len(blocks) == 1
    assert isinstance(blocks[0], Paragraph)
    assert blocks[0].text == "본문 문구"  # 그림은 유령 텍스트를 만들지 않는다
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_header_footer_body_text_captured():
    """머리말/꼬리말 XML 의 본문 문단이 별도 영역으로 잡히고 본문에 섞이지 않는다.

    실제 코퍼스는 ``Contents/header.xml`` 이 스타일 전용 ``hp:head`` 라 이 경로를
    태우지 못한다. 여기서 본문 문단을 담은 머리말/꼬리말을 합성해 코드 경로를 증명한다.
    """
    from hwpxcore.package import HwpxPackage, MIMETYPE_NAME, MIMETYPE_VALUE

    def sec(text: str) -> bytes:
        return (
            f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
            f'xmlns:hp="{HP}">'
            f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p></hs:sec>"
        ).encode("utf-8")

    # hp:head 스타일 전용 파일(본문 아님) — 제외되어야 한다.
    style_head = (
        '<hp:head xmlns:hp="' + HP + '"><hp:refList/></hp:head>'
    ).encode("utf-8")

    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec("본문 문단")
    pkg.entries["Contents/header.xml"] = style_head  # 스타일 전용 → 제외
    pkg.entries["Contents/header0.xml"] = sec("머리말 문단")  # 본문 → 포함
    pkg.entries["Contents/footer0.xml"] = sec("꼬리말 문단")  # 본문 → 포함

    doc = extract_document(pkg)
    assert isinstance(doc, Document)
    # 스타일 전용 header.xml 은 제외, 본문 있는 header0/footer0 만 포함.
    assert len(doc.headers) == 1
    assert len(doc.footers) == 1
    assert doc.headers[0].blocks[0].text == "머리말 문단"
    assert doc.footers[0].blocks[0].text == "꼬리말 문단"
    # 본문 섹션에 머리말/꼬리말이 섞이지 않는다.
    body_texts = [
        b.text for s in doc.sections for b in s.blocks if isinstance(b, Paragraph)
    ]
    assert body_texts == ["본문 문단"]
    assert doc.unhandled == {}


def test_style_only_header_not_treated_as_body():
    """스타일 전용 ``hp:head`` 루트는 본문 영역으로 오인되지 않는다."""
    head = etree.fromstring(
        ('<hp:head xmlns:hp="' + HP + '"><hp:refList/></hp:head>').encode("utf-8")
    )
    assert _has_body_text(head) is False


def test_extract_document_rejects_path_input_loudly():
    """파서 의미론 층은 파일 IO 를 개시하지 않는다(P2-19R #576 음성 oracle).

    경로/바이트 수용 뒷문이 되살아나면 이 단언이 RED 다 — 경로는 External adapter로
    읽고 bytes는 format kernel에서 package로 변환해 넘겨야 한다(loud 재진술 포함).
    """
    import pytest

    with pytest.raises(TypeError, match="열린 HWPX package"):
        extract_document("some/template.hwpx")
    with pytest.raises(TypeError, match="열린 HWPX package"):
        extract_document(b"PK\x03\x04")


# ------------------------------------------------------- 도형 글상자·캡션(shape_text)
def _rect(inner: str) -> str:
    """실 문서(한글 2024 글상자)와 같은 기하·렌더 메타를 두른 ``hp:rect`` 조각."""
    return (
        "<hp:rect><hp:offset/><hp:orgSz/><hp:curSz/><hp:flip/><hp:rotationInfo/>"
        "<hp:renderingInfo/><hp:lineShape/><hp:shadow/>"
        f"{inner}"
        "<hc:pt0/><hc:pt1/><hc:pt2/><hc:pt3/><hp:sz/><hp:pos/><hp:outMargin/></hp:rect>"
    )


def _draw_text(paragraphs: str) -> str:
    return (
        "<hp:drawText><hp:subList>"
        f"{paragraphs}"
        "</hp:subList><hp:textMargin/></hp:drawText>"
    )


def _p(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def test_textbox_paragraphs_field_and_table_extracted_in_anchor_order():
    """글상자(``drawText`` > ``subList``)의 여러 문단·누름틀·표가 앵커 자리에 TextBox 로 온다.

    글상자 앞뒤 본문은 표와 같은 규칙으로 갈라지고, 글상자 안 누름틀 이름은 그 문단의
    ``fields`` 에 실린다. 문서 순서 순회(``iter_paragraph_texts``)는 글상자 안까지 걷는다.
    """
    ledger = CoverageLedger()
    inner = _draw_text(
        _p("첫 줄")
        + "<hp:p><hp:run><hp:ctrl><hp:fieldBegin type=\"CLICK_HERE\" name=\"담당자\"/>"
        "</hp:ctrl></hp:run><hp:run><hp:t>홍길동</hp:t></hp:run>"
        "<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run></hp:p>"
        + "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>"
        + _p("상자 속 셀")
        + "</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )
    xml = f"<hp:p><hp:run><hp:t>앞 문구(</hp:t>{_rect(inner)}<hp:t>) 뒤 문구</hp:t></hp:run></hp:p>"
    blocks = _blocks(xml, ledger)

    assert [type(b).__name__ for b in blocks] == ["Paragraph", "TextBox", "Paragraph"]
    box = blocks[1]
    assert isinstance(box, TextBox)
    assert [type(b).__name__ for b in box.blocks] == ["Paragraph", "Paragraph", "Table"]
    assert box.blocks[1] == Paragraph("홍길동", ["담당자"])
    assert box.to_dict()["type"] == "textbox"
    assert iter_paragraph_texts(Document(sections=[Section(blocks)])) == [
        "앞 문구(", "첫 줄", "홍길동", "상자 속 셀", ") 뒤 문구",
    ]
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_container_children_keep_document_order_and_textless_shape_emits_nothing():
    """묶음 ``hp:container`` 는 자식 도형을 문서 순서로 재귀하고, 글상자 없는 도형은 블록이 없다."""
    ledger = CoverageLedger()
    xml = (
        "<hp:p><hp:run><hp:t>가</hp:t><hp:container><hp:offset/><hp:sz/><hp:pos/>"
        + _rect(_draw_text(_p("첫째 상자")))
        + "<hp:ellipse><hp:offset/><hc:center/><hc:ax1/><hc:ax2/></hp:ellipse>"
        + "<hp:polygon><hc:pt/><hc:pt/><hp:shapeComment/></hp:polygon>"
        + "<hp:ellipse><hc:center/>" + _draw_text(_p("둘째 상자")) + "</hp:ellipse>"
        + "</hp:container><hp:t>나</hp:t></hp:run></hp:p>"
    )
    blocks = _blocks(xml, ledger)

    assert [type(b).__name__ for b in blocks] == [
        "Paragraph", "TextBox", "TextBox", "Paragraph",
    ]
    assert iter_paragraph_texts(Document(sections=[Section(blocks)])) == [
        "가", "첫째 상자", "둘째 상자", "나",
    ]
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_shape_caption_precedes_textbox():
    """도형 캡션은 표 캡션과 같은 규칙으로 개체 블록 앞(문서 순서) 문단이 된다."""
    ledger = CoverageLedger()
    caption = f"<hp:caption><hp:subList>{_p('[그림 1] 처리 흐름')}</hp:subList></hp:caption>"
    xml = f"<hp:p><hp:run>{_rect(_draw_text(_p('상자 본문')) + caption)}</hp:run></hp:p>"
    blocks = _blocks(xml, ledger)

    assert [type(b).__name__ for b in blocks] == ["Paragraph", "TextBox"]
    assert blocks[0] == Paragraph("[그림 1] 처리 흐름", [])
    assert isinstance(blocks[1], TextBox)
    assert blocks[1].blocks == [Paragraph("상자 본문", [])]
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_polygon_without_text_emits_no_block_and_does_not_split_paragraph():
    """``drawText`` 없는 도형(실 코퍼스 ``metatag_s1`` 의 폴리곤 형상)은 블록도 원장도 없다."""
    ledger = CoverageLedger()
    xml = (
        "<hp:p><hp:run><hp:t>앞</hp:t><hp:polygon><hp:offset/><hp:orgSz/><hp:curSz/>"
        "<hp:flip/><hp:rotationInfo/><hp:renderingInfo/><hp:lineShape/><hp:shadow/>"
        "<hc:pt/><hc:pt/><hc:pt/><hp:sz/><hp:pos/><hp:outMargin/>"
        "<hp:shapeComment>다각형입니다.</hp:shapeComment><hp:metaTag>{}</hp:metaTag>"
        "</hp:polygon><hp:t>뒤</hp:t></hp:run></hp:p>"
    )
    blocks = _blocks(xml, ledger)

    assert blocks == [Paragraph("앞뒤", [])]
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"


def test_unknown_shape_children_are_recorded_loudly():
    """도형·글상자 결정표에 없는 자식은 원장에 경로와 함께 소리 나게 남는다."""
    ledger = CoverageLedger()
    xml = (
        "<hp:p><hp:run>"
        + _rect(
            "<hp:futureShapePart/><hc:futurePoint/>"
            "<hp:drawText><hp:futureTextPart/><hp:subList>"
            + _p("상자")
            + "</hp:subList></hp:drawText>"
        )
        + "</hp:run></hp:p>"
    )
    blocks = _blocks(xml, ledger)

    assert isinstance(blocks[0], TextBox)  # 미지 자식이 있어도 아는 본문은 복원한다
    assert ledger.counts == {
        "futureShapePart": 1,
        f"{{{HC}}}futurePoint": 1,
        "futureTextPart": 1,
    }
    assert ledger.examples["futureShapePart"] == "sec/p/run/rect/futureShapePart"
    assert ledger.examples["futureTextPart"] == "sec/p/run/rect/drawText/futureTextPart"


def test_pic_caption_text_preserved():
    """캡션을 품은 그림 ``hp:pic`` 은 캡션 문단을 그림 자리에 남긴다(이미지 메타는 무시)."""
    ledger = CoverageLedger()
    xml = (
        "<hp:p><hp:run><hp:t>본문 문구</hp:t><hp:pic><hp:offset/><hp:orgSz/><hp:curSz/>"
        "<hp:flip/><hp:rotationInfo/><hp:renderingInfo/><hc:img/><hp:imgRect/><hp:imgClip/>"
        "<hp:inMargin/><hp:imgDim/><hp:effects/><hp:sz/><hp:pos/><hp:outMargin/>"
        "<hp:shapeComment/>"
        f"<hp:caption><hp:subList>{_p('[사진 1] 현장 전경')}</hp:subList></hp:caption>"
        "</hp:pic></hp:run></hp:p>"
    )
    blocks = _blocks(xml, ledger)

    assert blocks == [Paragraph("본문 문구", []), Paragraph("[사진 1] 현장 전경", [])]
    assert ledger.counts == {}, f"예상치 못한 원장 항목: {ledger.counts}"
