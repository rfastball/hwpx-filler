"""렌더러 스모크 테스트 — HTML/텍스트 요약이 핵심 내용을 담고 잘 형성된다."""

from __future__ import annotations

from hwpxdiff.diff import (
    NO_CHANGES_MESSAGE,
    WordOp,
    coalesce_word_ops,
    diff_documents,
    render_html,
    render_summary,
)
from hwpxcore.text_extract import Document, Paragraph, Section


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
    assert NO_CHANGES_MESSAGE in html  # 빈 상태 카피는 3표면 공유(RC-32)


def test_render_summary_no_changes_uses_shared_copy():
    """CLI 텍스트 요약의 0건 카피도 공유 상수 — 표면별 하드코딩 금지(RC-32)."""
    r = diff_documents(_doc("동일."), _doc("동일."))
    assert NO_CHANGES_MESSAGE in render_summary(r)


def test_render_html_summary_cards_include_renumber():
    """HTML 상단 카드에 번호변경 포함 — GUI KPI 타일과 같은 지표 집합(RC-32)."""
    r = _renumber_sample()
    html = render_html(r)
    n = r.summary["renumber"]
    assert n > 0
    assert f"<div class='card'><div class='n'>{n}</div><div class='l'>번호변경</div></div>" in html


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
    from hwpxdiff.diff import CATEGORY_COLORS, CATEGORY_LABELS

    assert set(CATEGORY_COLORS) == set(CATEGORY_LABELS)  # 범주 추가 시 색 누락 방지
    html = render_html(_sample())
    for cat, color in CATEGORY_COLORS.items():
        assert f".b-{cat}{{background:{color}}}" in html, f"CSS 규칙 없음: {cat}"


def test_html_inline_palette_single_source():
    """del/ins 강조·틴트도 코어 단일 출처(KIND_COLORS/KIND_TINTS)에서 CSS 생성(RC-17)."""
    from hwpxdiff.diff import KIND_COLORS, KIND_TINTS

    html = render_html(_sample())
    assert f"del{{background:{KIND_TINTS['removed']};color:{KIND_COLORS['removed']};" in html
    assert f"ins{{background:{KIND_TINTS['added']};color:{KIND_COLORS['added']};" in html


# ------------------------------------------------ 낱말 성형(coalesce) 공유
def test_coalesce_ops_absorbs_short_equal_between_changes():
    """변경 사이 한두 글자 equal 은 흡수, 낱말 경계(선두/후미/공백)는 보존(순수 함수)."""
    ops = [
        WordOp("equal", old="제"),
        WordOp("replace", old="3", new="4"),
        WordOp("equal", old="조"),
        WordOp("replace", old="갑", new="을"),
        WordOp("equal", old=" 이하 같다"),
    ]
    out = coalesce_word_ops(ops)
    assert [o.op for o in out] == ["equal", "replace", "equal"]
    assert out[1].old == "3조갑" and out[1].new == "4조을"

    # 공백 equal 은 낱말 경계 — 흡수하지 않는다.
    ops2 = [
        WordOp("replace", old="가", new="나"),
        WordOp("equal", old=" "),
        WordOp("replace", old="다", new="라"),
    ]
    assert [o.op for o in coalesce_word_ops(ops2)] == ["replace", "equal", "replace"]


def test_render_html_applies_same_coalescing_as_gui():
    """RC-17 회귀: CLI HTML 도 coalesce 성형을 거친다 — GUI 와 같은 낱말 덩어리 강조.

    성형 없이는 '제3조 갑'→'제4조 을'이 <del>3</del>…<del>갑</del> 파편으로 렌더돼
    GUI 검토자와 HTML 회람자가 같은 변경을 다른 강조로 읽는다.
    """
    r = diff_documents(_doc("제3조 갑 이하 같다"), _doc("제4조 을 이하 같다"))
    (c,) = r.changes
    assert c.kind in ("changed", "renumber") and c.word_ops
    html = render_html(r)
    merged = coalesce_word_ops(c.word_ops)
    # coalesce 결과의 replace 덩어리가 그대로 del/ins 로 나타난다(파편 렌더 아님).
    reps = [w for w in merged if w.op == "replace"]
    assert reps, "coalesce 가 replace 덩어리를 만들지 않았다"
    for w in reps:
        assert f"<del>{w.old}</del>" in html
        assert f"<ins>{w.new}</ins>" in html
