"""SYNTHETIC 엣지 케이스 — 손으로 만든 최소 ``hp:`` XML 조각으로 정밀 검증.

패키지 없이 XML 을 직접 파싱하도록 내부 헬퍼(``_blocks_from_container``)를 쓴다.
각 조각은 섹션 루트 한 개로 감싸 섹션 컨테이너처럼 다룬다.
"""

from __future__ import annotations

from lxml import etree

from hwpxfiller.core.text_extract import (
    CoverageLedger,
    Document,
    Paragraph,
    Table,
    _blocks_from_container,
    _has_body_text,
    extract_document,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _blocks(inner_xml: str, ledger: "CoverageLedger | None" = None):
    """``<sec>...</sec>`` 로 감싼 조각을 파싱해 최상위 블록 목록 반환."""
    xml = f'<sec xmlns:hp="{HP}">{inner_xml}</sec>'
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


def test_header_footer_body_text_captured():
    """머리말/꼬리말 XML 의 본문 문단이 별도 영역으로 잡히고 본문에 섞이지 않는다.

    실제 코퍼스는 ``Contents/header.xml`` 이 스타일 전용 ``hp:head`` 라 이 경로를
    태우지 못한다. 여기서 본문 문단을 담은 머리말/꼬리말을 합성해 코드 경로를 증명한다.
    """
    from hwpxfiller.core.package import HwpxPackage, MIMETYPE_NAME, MIMETYPE_VALUE

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
