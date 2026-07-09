"""SYNTHETIC 정밀 테스트 — 정확히 알려진 델타를 심어 diff 가 그것만 잡는지 검증.

Document 데이터클래스를 직접 조립해(패키지/XML 없이) 변경을 통제한다. 각 테스트는
'정확히 이 변경, 그 이상도 이하도 아님'을 단언한다 — 뮤테이션 테스트에 견디는 하중.
"""

from __future__ import annotations

from hwpxfiller.core.diff import diff_documents
from hwpxfiller.core.text_extract import (
    Cell,
    Document,
    Paragraph,
    Section,
    Table,
)


def _doc(*texts: str) -> Document:
    """문단 텍스트들로 단일 본문 섹션 Document 조립."""
    return Document(sections=[Section(blocks=[Paragraph(t) for t in texts])])


def _cats(result):
    return [it.category for it in result.change_items]


# ------------------------------------------------------------ 재작성 문장
def test_reworded_sentence_is_changed_with_word_ops():
    """한 문장 재작성 -> changed 하나 + 올바른 낱말 op(교체 부분만)."""
    old = _doc("계약 상대자는 납품기한을 준수하여야 한다.")
    new = _doc("계약 상대자는 납품기한을 반드시 준수하여야 한다.")
    r = diff_documents(old, new)

    assert len(r.changes) == 1
    c = r.changes[0]
    assert c.kind == "changed" and c.unit == "paragraph"
    assert c.old_text.endswith("준수하여야 한다.")
    # 낱말 op 로 '반드시 ' 삽입이 잡혀야 한다(equal 사이 insert).
    inserts = [w.new for w in c.word_ops if w.op == "insert"]
    assert any("반드시" in x for x in inserts)
    # 재작성은 숫자 변경이 아니므로 text_changed 로 분류.
    assert _cats(r) == ["text_changed"]


# ------------------------------------------------------------ 숫자 변경
def test_number_change_1eok_to_2eok():
    """1억 -> 2억 은 change_items 에 number 로 표면화된다."""
    old = _doc("기준금액은 1억 이상이어야 한다.")
    new = _doc("기준금액은 2억 이상이어야 한다.")
    r = diff_documents(old, new)

    assert len(r.changes) == 1 and r.changes[0].kind == "changed"
    nums = [it for it in r.change_items if it.category == "number"]
    assert len(nums) == 1
    assert "1억" in nums[0].detail and "2억" in nums[0].detail
    assert nums[0].priority == 0  # 최우선


def test_percent_change_surfaced_as_number():
    """요율 3% -> 3.5% 도 number 항목으로."""
    old = _doc("낙찰 요율은 3% 로 한다.")
    new = _doc("낙찰 요율은 3.5% 로 한다.")
    r = diff_documents(old, new)
    nums = [it for it in r.change_items if it.category == "number"]
    assert len(nums) == 1
    assert "3%" in nums[0].detail and "3.5%" in nums[0].detail


# ------------------------------------------------------------ 조항 추가
def test_added_clause_flagged():
    """제5조 조항 추가 -> added + clause_added 로 표시."""
    old = _doc("제4조(납품) 납품은 지정장소에 한다.")
    new = _doc(
        "제4조(납품) 납품은 지정장소에 한다.",
        "제5조(검사) 검사는 수요기관이 수행한다.",
    )
    r = diff_documents(old, new)

    assert len(r.changes) == 1
    c = r.changes[0]
    assert c.kind == "added" and c.new_text.startswith("제5조")
    assert _cats(r) == ["clause_added"]
    assert r.change_items[0].priority == 1


# ------------------------------------------------------------ 문단 삭제
def test_removed_paragraph():
    """문단 삭제 -> removed 하나. (조항 아니므로 text_removed)"""
    old = _doc("첫째 문단.", "둘째 문단(삭제 대상).", "셋째 문단.")
    new = _doc("첫째 문단.", "셋째 문단.")
    r = diff_documents(old, new)

    assert len(r.changes) == 1
    c = r.changes[0]
    assert c.kind == "removed" and c.old_text == "둘째 문단(삭제 대상)."
    assert _cats(r) == ["text_removed"]


# ------------------------------------------------------------ 표 셀 변경
def _table_doc(cell_text: str) -> Document:
    """1x2 표 한 개를 담은 본문 섹션. 두 셀 addr 는 (0,0),(0,1)."""
    row = [
        Cell(blocks=[Paragraph("항목")], span={"colSpan": 1, "rowSpan": 1},
             addr={"colAddr": 0, "rowAddr": 0}),
        Cell(blocks=[Paragraph(cell_text)], span={"colSpan": 1, "rowSpan": 1},
             addr={"colAddr": 1, "rowAddr": 0}),
    ]
    return Document(sections=[Section(blocks=[Table(rows=[row])])])


def test_changed_table_cell_with_addr_location():
    """표 셀 값 변경 -> 셀 단위 changed + 정확한 addr 위치."""
    old = _table_doc("1억")
    new = _table_doc("2억")
    r = diff_documents(old, new)

    assert len(r.changes) == 1
    c = r.changes[0]
    assert c.unit == "cell" and c.kind == "changed"
    assert c.location["colAddr"] == 1 and c.location["rowAddr"] == 0
    assert c.location["table_index"] == 0
    assert c.old_text == "1억" and c.new_text == "2억"
    # 셀 안 숫자 변경도 number 로 표면화.
    assert _cats(r) == ["number"]


def test_table_identical_no_change():
    """동일 표는 변경 0(셀 정렬이 헛집어내지 않음)."""
    r = diff_documents(_table_doc("동일"), _table_doc("동일"))
    assert r.changes == [] and r.change_items == []


# ------------------------------------------------------------ 항등(명시)
def test_unchanged_doc_no_changes():
    """완전 동일 문서 -> 변경 0, 항목 0 (중복이지만 명시적)."""
    d = _doc("가.", "나.", "다.")
    r = diff_documents(d, d)
    assert r.changes == []
    assert r.change_items == []
    assert r.summary == {"added": 0, "removed": 0, "changed": 0, "change_items": 0}


# ------------------------------------------------------------ 우선순위 정렬
def test_change_items_ranked_numbers_and_clauses_first():
    """여러 변경이 섞여도 number/clause 가 add/remove 문구보다 앞선다."""
    old = _doc(
        "요율은 3% 이다.",           # -> 숫자 변경
        "부가 설명 문단.",            # -> 삭제
        "제2조(기간) 30일.",         # 유지
    )
    new = _doc(
        "요율은 5% 이다.",           # 숫자 변경
        "제2조(기간) 30일.",         # 유지
        "제7조(신설) 새 조항.",       # 조항 추가
    )
    r = diff_documents(old, new)
    cats = _cats(r)
    # number 가 가장 앞, 그 다음 clause_added, 마지막에 text_removed.
    assert cats[0] == "number"
    assert "clause_added" in cats
    assert cats.index("number") < cats.index("clause_added")
    assert cats.index("clause_added") < cats.index("text_removed")


# ------------------------------------------------------------ 빈 문단 노이즈
def test_blank_paragraph_shifts_are_not_reported():
    """빈 문단이 하나 더 끼어도 변경으로 보고하지 않는다(노이즈 억제)."""
    old = _doc("실질 문단 A.", "실질 문단 B.")
    new = _doc("실질 문단 A.", "", "실질 문단 B.")
    r = diff_documents(old, new)
    assert r.changes == []
