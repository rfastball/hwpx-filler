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


def _renumber_sample():
    """조항 삽입으로 뒤 번호가 밀린(재번호) + 진짜 숫자변경이 섞인 표본."""
    old = _doc(
        "3.2.1 앞 조항 본문.",
        "3.2.2 뒤 조항 본문.",
        "요율은 3% 로 한다.",
    )
    new = _doc(
        "3.2.1 앞 조항 본문.",
        "3.2.2 신설된 조항 본문.",   # 삽입
        "3.2.3 뒤 조항 본문.",         # 재번호(본문 동일)
        "요율은 5% 로 한다.",          # 실질 숫자변경
    )
    return diff_documents(old, new)


def test_render_summary_separates_renumber_section():
    """요약은 재번호를 실질 항목과 섞지 않고 별도 저순위 헤딩(건수 포함)으로 낸다."""
    r = _renumber_sample()
    text = render_summary(r)
    assert "번호 변경" in text          # 별도 섹션
    assert "- 번호 변경:" in text        # 요약 카운트 줄
    # 재번호는 '주요 변경 항목'(실질) 목록엔 badge 로 섞이지 않는다.
    main = text.split("번호 변경")[0]
    assert "renumber" not in main


def test_render_html_renumber_collapsed_group():
    """HTML 은 재번호를 기본 접힘·흐린 그룹으로 데모트(숨기지 않되 눈에 덜 띄게)."""
    r = _renumber_sample()
    html = render_html(r)
    # 접이식 그룹(기본 접힘: 'open' 없이), 흐린 스타일 클래스.
    assert "renumber-group" in html
    assert "<details class='renumber-group'>" in html  # open 아님 -> 접힘
    # 실질 항목 배지는 그대로, 재번호는 실질 배지 테이블에 섞이지 않는다.
    assert "b-number" in html


def test_category_palette_single_source():
    """배지 팔레트·라벨은 코어 단일 출처 — 전 범주에 색이 있고 CSS 는 dict 에서 생성된다."""
    from hwpxfiller.core.diff import CATEGORY_COLORS, CATEGORY_LABELS

    assert set(CATEGORY_COLORS) == set(CATEGORY_LABELS)  # 범주 추가 시 색 누락 방지
    html = render_html(_sample())
    for cat, color in CATEGORY_COLORS.items():
        assert f".b-{cat}{{background:{color}}}" in html, f"CSS 규칙 없음: {cat}"
