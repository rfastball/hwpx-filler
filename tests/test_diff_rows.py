"""전문(rows) 스트림 불변식 — 신구대비표 뷰의 데이터(equal 포함 정렬 스트림).

``DiffResult.rows`` 는 직렬화(골든) 밖의 파생물이지만 뷰가 전적으로 기대는 계약이라
여기서 헤드리스로 못박는다: equal 보존, 변경 seq 와의 1:1 대응, 순서 안정.
"""

from __future__ import annotations

from pathlib import Path

from hwpxdiff.diff import diff_documents, diff_files
from hwpxcore.text_extract import Document, Paragraph, Section

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
