"""#187 — 복합 표와 반복·이동 문단의 diff pairing 적대 계약."""

from __future__ import annotations

from lxml import etree

from hwpxcore.text_extract import (
    CoverageLedger,
    Document,
    Paragraph,
    Section,
    Table,
    _blocks_from_container,
)
from hwpxdiff.diff import DiffResult, diff_documents

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"


def _doc_from_xml(inner: str) -> Document:
    root = etree.fromstring(
        f'<hs:sec xmlns:hs="{HS_NS}" xmlns:hp="{HP_NS}">{inner}</hs:sec>'.encode()
    )
    ledger = CoverageLedger()
    blocks = _blocks_from_container(root, ledger, "section0")
    assert ledger.counts == {}
    return Document(sections=[Section(blocks=blocks)])


def _paragraph_doc(*texts: str) -> Document:
    return Document(sections=[Section(blocks=[Paragraph(text) for text in texts])])


def _facts(result: DiffResult) -> "list[tuple[str, str, str]]":
    """FP/FN 판정을 위한 전체 change 정본(kind, old, new)."""
    return [(change.kind, change.old_text, change.new_text) for change in result.changes]


def _merged_table(value: str) -> Document:
    return _doc_from_xml(
        f"""
        <hp:p><hp:run><hp:tbl>
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:cellSpan colSpan="2" rowSpan="1"/>
              <hp:subList><hp:p><hp:run><hp:t>병합 계약금: {value}</hp:t></hp:run></hp:p></hp:subList>
            </hp:tc>
            <hp:tc>
              <hp:cellAddr colAddr="2" rowAddr="0"/>
              <hp:cellSpan colSpan="1" rowSpan="1"/>
              <hp:subList><hp:p><hp:run><hp:t>형제 고정</hp:t></hp:run></hp:p></hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl></hp:run></hp:p>
        """
    )


def _nested_table(value: str) -> Document:
    return _doc_from_xml(
        f"""
        <hp:p><hp:run><hp:tbl>
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:cellSpan colSpan="1" rowSpan="1"/>
              <hp:subList>
                <hp:p><hp:run><hp:t>부모 고정</hp:t></hp:run></hp:p>
                <hp:p><hp:run><hp:tbl>
                  <hp:tr><hp:tc>
                    <hp:cellAddr colAddr="4" rowAddr="3"/>
                    <hp:cellSpan colSpan="1" rowSpan="1"/>
                    <hp:subList><hp:p><hp:run><hp:t>중첩 금액: {value}</hp:t></hp:run></hp:p></hp:subList>
                  </hp:tc></hp:tr>
                </hp:tbl></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
            <hp:tc>
              <hp:cellAddr colAddr="1" rowAddr="0"/>
              <hp:cellSpan colSpan="1" rowSpan="1"/>
              <hp:subList><hp:p><hp:run><hp:t>형제 고정</hp:t></hp:run></hp:p></hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl></hp:run></hp:p>
        """
    )


def test_merged_cell_value_change_has_exact_grid_location_without_sibling_fp():
    old = _merged_table("100만원")
    new = _merged_table("120만원")

    result = diff_documents(old, new)

    # 기대 1건이 FP/FN 정본: 병합 셀만 changed, 형제 셀은 0건.
    assert _facts(result) == [
        ("changed", "병합 계약금: 100만원", "병합 계약금: 120만원")
    ]
    change = result.changes[0]
    assert change.location == {
        "region": "본문",
        "region_index": 0,
        "unit": "cell",
        "table_index": 0,
        "rowAddr": 0,
        "colAddr": 0,
    }
    table = old.sections[0].blocks[0]
    assert isinstance(table, Table)
    assert table.rows[0][0].span == {"colSpan": 2, "rowSpan": 1}


def test_nested_cell_change_is_not_misattributed_to_parent_or_sibling():
    result = diff_documents(_nested_table("100만원"), _nested_table("120만원"))

    # 부모/형제 셀 changed는 FP, 중첩 셀 누락은 FN이다. 정확히 중첩 1건만 허용.
    assert _facts(result) == [
        ("changed", "중첩 금액: 100만원", "중첩 금액: 120만원")
    ]
    change = result.changes[0]
    assert change.location["table_path"] == [0, 0]
    assert change.location["parent_cells"] == [{"rowAddr": 0, "colAddr": 0}]
    assert change.location["rowAddr"] == 3
    assert change.location["colAddr"] == 4
    assert "중첩 표 1" in change.location_label
    assert change.location_label.endswith("셀(3,4)")


def _nested_at(row: int, col: int) -> Document:
    """중첩 셀 좌표만 매개변수 — 부모 셀의 평탄화 전문은 좌표와 무관하게 동일해진다."""
    return _doc_from_xml(
        f"""
        <hp:p><hp:run><hp:tbl>
          <hp:tr>
            <hp:tc>
              <hp:cellAddr colAddr="0" rowAddr="0"/>
              <hp:cellSpan colSpan="1" rowSpan="1"/>
              <hp:subList>
                <hp:p><hp:run><hp:t>부모 고정</hp:t></hp:run></hp:p>
                <hp:p><hp:run><hp:tbl>
                  <hp:tr><hp:tc>
                    <hp:cellAddr colAddr="{col}" rowAddr="{row}"/>
                    <hp:cellSpan colSpan="1" rowSpan="1"/>
                    <hp:subList><hp:p><hp:run><hp:t>중첩 금액: 100만원</hp:t></hp:run></hp:p></hp:subList>
                  </hp:tc></hp:tr>
                </hp:tbl></hp:run></hp:p>
              </hp:subList>
            </hp:tc>
          </hp:tr>
        </hp:tbl></hp:run></hp:p>
        """
    )


def test_nested_move_with_equal_flat_text_still_attributes_nested_cells():
    """#254 리뷰 — 부모 셀의 평탄화 전문이 같아도 중첩 재귀는 돌아야 한다: 같은 값이 중첩
    좌표 사이를 이동하면 평탄화 등호 조기 반환은 변경 0건으로 조용히 삼켜, table_path/실셀
    귀속을 스스로 무력화한다. 이동 = 옛 좌표 removed + 새 좌표 added 로 정확 귀속."""
    result = diff_documents(_nested_at(3, 4), _nested_at(0, 0))

    facts = sorted(_facts(result))
    assert facts == [
        ("added", "", "중첩 금액: 100만원"),
        ("removed", "중첩 금액: 100만원", ""),
    ]
    for change in result.changes:
        assert change.location["table_path"] == [0, 0]
        assert change.location["parent_cells"] == [{"rowAddr": 0, "colAddr": 0}]
    removed = next(c for c in result.changes if c.kind == "removed")
    added = next(c for c in result.changes if c.kind == "added")
    assert (removed.location["rowAddr"], removed.location["colAddr"]) == (3, 4)
    assert (added.location["rowAddr"], added.location["colAddr"]) == (0, 0)


def test_repeated_and_similar_paragraphs_pair_only_their_position_owner():
    old = _paragraph_doc(
        "반복 안내: 증빙을 제출합니다.",
        "장비 A 점검 주기는 10일입니다.",
        "반복 안내: 증빙을 제출합니다.",
        "장비 A 점검 주기는 20일입니다.",
        "종료 문단.",
    )
    new = _paragraph_doc(
        "반복 안내: 증빙을 제출합니다.",
        "장비 A 점검 주기는 11일입니다.",
        "반복 안내: 증빙을 제출합니다.",
        "장비 A 점검 주기는 21일입니다.",
        "종료 문단.",
    )

    result = diff_documents(old, new)

    # 두 유사 문단의 제자리 변경만 owner다. 반복 문단 extra=FP, 둘 중 누락=FN.
    assert _facts(result) == [
        ("changed", "장비 A 점검 주기는 10일입니다.", "장비 A 점검 주기는 11일입니다."),
        ("changed", "장비 A 점검 주기는 20일입니다.", "장비 A 점검 주기는 21일입니다."),
    ]


def test_exact_paragraph_move_is_removed_plus_added_not_changed():
    old = _paragraph_doc(
        "반복 기준 문단.",
        "이동 대상 문단.",
        "반복 기준 문단.",
        "고정 끝 문단.",
    )
    new = _paragraph_doc(
        "반복 기준 문단.",
        "반복 기준 문단.",
        "고정 끝 문단.",
        "이동 대상 문단.",
    )

    result = diff_documents(old, new)

    # move 전용 op가 없으므로 정책은 old 위치 removed + new 위치 added다.
    assert _facts(result) == [
        ("removed", "이동 대상 문단.", ""),
        ("added", "", "이동 대상 문단."),
    ]


def test_edited_paragraph_move_stays_removed_plus_added_not_false_changed_pair():
    old = _paragraph_doc(
        "장비 점검 금액은 100만원입니다.",
        "고정 첫 문단.",
        "고정 둘째 문단.",
    )
    new = _paragraph_doc(
        "고정 첫 문단.",
        "고정 둘째 문단.",
        "장비 점검 금액은 120만원입니다.",
    )

    result = diff_documents(old, new)

    # 서로 떨어진 delete/insert block은 위치 이동으로 본다. changed 오짝은 FP.
    assert _facts(result) == [
        ("removed", "장비 점검 금액은 100만원입니다.", ""),
        ("added", "", "장비 점검 금액은 120만원입니다."),
    ]
