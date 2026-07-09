"""SYNTHETIC 엣지 케이스 — 손으로 만든 최소 ``hp:`` XML 조각으로 정밀 검증.

패키지 없이 XML 을 직접 파싱하도록 내부 헬퍼(``_blocks_from_container``)를 쓴다.
각 조각은 섹션 루트 한 개로 감싸 섹션 컨테이너처럼 다룬다.
"""

from __future__ import annotations

from lxml import etree

from hwpxfiller.core.text_extract import (
    Paragraph,
    Table,
    _blocks_from_container,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _blocks(inner_xml: str):
    """``<sec>...</sec>`` 로 감싼 조각을 파싱해 최상위 블록 목록 반환."""
    xml = f'<sec xmlns:hp="{HP}">{inner_xml}</sec>'
    root = etree.fromstring(xml.encode("utf-8"))
    return _blocks_from_container(root)


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
