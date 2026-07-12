"""전문(rows) 스트림 불변식 — 신구대비표 뷰의 데이터(equal 포함 정렬 스트림).

``DiffResult.rows`` 는 직렬화(골든) 밖의 파생물이지만 뷰가 전적으로 기대는 계약이라
여기서 헤드리스로 못박는다: equal 보존, 변경 seq 와의 1:1 대응, 순서 안정.
"""

from __future__ import annotations

from pathlib import Path

from hwpxdiff.diff import DocRow, diff_documents, diff_files, group_changes, row_group_key
from hwpxcore.text_extract import Cell, Document, Paragraph, Section, Table

CORPUS = Path(__file__).parent / "corpus" / "real"


def _doc(*texts: str) -> Document:
    return Document(sections=[Section(blocks=[Paragraph(t) for t in texts])])


def test_rows_preserve_equal_context():
    """변경 없는 문단도 rows 에 남는다 — 전문 뷰의 존재 이유(본문 맥락)."""
    old = _doc("서문은 그대로다.", "기준금액은 1억 이상이어야 한다.", "말미도 그대로다.")
    new = _doc("서문은 그대로다.", "기준금액은 2억 이상이어야 한다.", "말미도 그대로다.")
    r = diff_documents(old, new)

    assert [row.kind for row in r.rows] == ["equal", "changed", "equal"]
    eq = r.rows[0]
    assert eq.seq is None and eq.old_text == eq.new_text == "서문은 그대로다."
    ch = r.rows[1]
    assert ch.seq == r.changes[0].seq and ch.word_ops  # 앵커 키 + 인라인 강조 데이터


def test_rows_seq_matches_changes_order_real_corpus():
    """실코퍼스: rows 의 변경 seq 열 == changes 의 seq 열(1:1·순서 보존)."""
    r = diff_files(
        str(CORPUS / "spec_revision_2025.hwpx"),
        str(CORPUS / "spec_revision_2026.hwpx"),
    )
    assert [row.seq for row in r.rows if row.seq is not None] == [
        c.seq for c in r.changes
    ]
    # 전문은 변경보다 크다(equal 이 실제로 포함됨).
    n_equal = sum(1 for row in r.rows if row.kind == "equal")
    assert n_equal > 0 and len(r.rows) == len(r.changes) + n_equal


def test_rows_identical_documents_all_equal():
    doc = _doc("제1조 목적.", "제2조 정의.")
    r = diff_documents(doc, _doc("제1조 목적.", "제2조 정의."))
    assert not r.changes
    assert [row.kind for row in r.rows] == ["equal", "equal"]


# --------------------------------------------------- 변경 그룹(rows 인접 기준)
def test_group_changes_splits_on_equal_row_despite_consecutive_seq():
    """RC-11 회귀: seq 는 방출 서수라 항상 연속 — 사이 equal 행이 있으면 별개 그룹.

    diff 실산출에서 changes[i].seq == i 불변식이 성립하므로 'seq+1 인접' 판정은
    문서상 떨어진 독립 변경을 '연속 N건'으로 거짓 병합한다.
    """
    rows = [
        DocRow("changed", "paragraph", "본문 1 · 문단 1", "a", "b", seq=0),
        DocRow("changed", "paragraph", "본문 1 · 문단 2", "c", "d", seq=1),
        DocRow("equal", "paragraph", "본문 1 · 문단 3", "그대로", "그대로"),
        DocRow("changed", "paragraph", "본문 1 · 문단 4", "e", "f", seq=2),  # seq 연속!
    ]
    gs = group_changes(rows)
    assert [(g.kind, g.seqs) for g in gs] == [("changed", [0, 1]), ("changed", [2])]
    assert "연속 2건" in gs[0].detail and "연속" not in gs[1].detail
    assert gs[0].label == "본문 1 · 문단 1"  # 그룹 라벨 = 첫 변경 위치


def test_group_changes_merges_adjacent_same_kind_splits_kind_change():
    """rows 상 연속·같은 종류만 병합 — 종류가 갈리면 인접해도 새 그룹."""
    rows = [
        DocRow("changed", "paragraph", "본문 1 · 문단 3", "a", "b", seq=0),
        DocRow("changed", "paragraph", "본문 1 · 문단 4", "c", "d", seq=1),
        DocRow("added", "paragraph", "본문 1 · 문단 5", "", "e", seq=2),
    ]
    gs = group_changes(rows)
    assert [(g.kind, len(g.seqs)) for g in gs] == [("changed", 2), ("added", 1)]


def test_group_changes_end_to_end_separated_changes_not_merged():
    """실제 diff 산출로: equal 문단을 사이에 둔 독립 변경 2건은 그룹 2개."""
    old = _doc("갑 조항 본문 하나.", "그대로 유지되는 문단.", "을 조항 본문 둘.")
    new = _doc("갑 조항 본문 하나 변경.", "그대로 유지되는 문단.", "을 조항 본문 둘 변경.")
    r = diff_documents(old, new)

    assert [c.kind for c in r.changes] == ["changed", "changed"]
    assert [c.seq for c in r.changes] == [0, 1]           # seq 는 연속(방출 서수)
    assert [g.seqs for g in r.change_groups] == [[0], [1]]  # 그래도 그룹은 분리


def test_change_groups_never_span_equal_rows_real_corpus():
    """실코퍼스 불변식: 그룹 멤버는 rows 스트림에서 연속(사이 equal·타종류 0)."""
    r = diff_files(
        str(CORPUS / "spec_revision_2025.hwpx"),
        str(CORPUS / "spec_revision_2026.hwpx"),
    )
    assert r.change_groups
    idx = {row.seq: i for i, row in enumerate(r.rows) if row.seq is not None}
    for g in r.change_groups:
        first, last = idx[g.seqs[0]], idx[g.seqs[-1]]
        assert last - first == len(g.seqs) - 1, f"그룹 {g.label}: rows 비연속(거짓 병합)"
        assert all(r.rows[i].kind == g.kind for i in range(first, last + 1))
    # 그룹 seq 전체 = 변경 seq 전체(누락·중복 없음).
    flat = [s for g in r.change_groups for s in g.seqs]
    assert flat == [c.seq for c in r.changes]


# ------------------------------------------------------ 행 라벨 → 그룹 헤더 키
def test_row_group_key_matches_label_production():
    """row_group_key 는 diff 가 실제 생산하는 라벨과 한 몸 — 문단·셀 라벨로 검증."""
    row_cells = [
        Cell(blocks=[Paragraph("항목")], span={"colSpan": 1, "rowSpan": 1},
             addr={"colAddr": 0, "rowAddr": 0}),
        Cell(blocks=[Paragraph("값")], span={"colSpan": 1, "rowSpan": 1},
             addr={"colAddr": 1, "rowAddr": 0}),
    ]
    doc = Document(sections=[Section(blocks=[Paragraph("문단 본문."),
                                             Table(rows=[row_cells])])])
    r = diff_documents(doc, doc)
    labels = [row.label for row in r.rows]
    assert labels, "rows 가 비어 있다"
    for label in labels:
        key = row_group_key(label)
        assert label.startswith(key)
    para_label = next(lb for lb in labels if "문단" in lb)
    cell_label = next(lb for lb in labels if "셀(" in lb)
    assert row_group_key(para_label) == "본문 1"
    assert row_group_key(cell_label) == "본문 1 · 표 1"
