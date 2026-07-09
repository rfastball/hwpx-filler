"""렌더러 스모크 테스트 — HTML/텍스트 요약이 핵심 내용을 담고 잘 형성된다."""

from __future__ import annotations

from hwpxfiller.core.diff import (
    diff_documents,
    render_html,
    render_summary,
)
from hwpxfiller.core.text_extract import Document, Paragraph, Section


def _doc(*texts: str) -> Document:
    return Document(sections=[Section(blocks=[Paragraph(t) for t in texts])])


def _sample():
    old = _doc("요율은 3% 이다.", "삭제될 문단.")
    new = _doc("요율은 3.5% 이다.", "제5조(신설) 추가 조항.")
    return diff_documents(old, new)


def test_render_summary_contains_counts_and_items():
    r = _sample()
    text = render_summary(r)
    assert "변경 요약" in text
    assert "주요 변경 항목" in text
    assert "3%" in text and "3.5%" in text


def test_render_html_self_contained_and_escaped():
    r = _sample()
    html = render_html(r)
    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html  # 인라인 CSS(자체 완결)
    assert "charset='utf-8'" in html
    # 인라인 낱말 강조.
    assert "<del>" in html and "<ins>" in html
    # 변경 항목 배지.
    assert "b-number" in html


def test_render_html_no_changes():
    r = diff_documents(_doc("동일."), _doc("동일."))
    html = render_html(r)
    assert "변경 없음" in html


def test_render_html_escapes_markup():
    """본문에 <, & 가 있어도 HTML 로 새지 않는다."""
    r = diff_documents(_doc("a < b & c 원본"), _doc("a < b & c 변경"))
    html = render_html(r)
    assert "&lt;" in html and "&amp;" in html
