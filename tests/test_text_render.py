"""텍스트 렌더 코어 — 순수 {{필드}} 치환(서식은 프로파일 소관, 인라인 포매터 없음)."""

from __future__ import annotations

from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_render import (
    FULLWIDTH_SPACE,
    SEG_BLANK,
    SEG_FILL,
    SEG_LITERAL,
    SEG_MISSING,
    align_fullwidth,
    align_segments,
    has_space_run,
    render_record,
    render_segments,
    segments_have_space_run,
    template_fields,
)


def test_basic_substitution_and_labeled_items():
    tpl = "계약명: {{계약명}}\n공고기관: {{공고기관}}"
    rec = {"계약명": "청사 유지보수", "공고기관": "조달청"}
    text, report = render_record(tpl, rec)
    assert text == "계약명: 청사 유지보수\n공고기관: 조달청"
    assert not report.has_issues


def test_missing_field_keeps_token_and_reports():
    text, report = render_record("담당: {{담당자}}", {"계약명": "X"})
    assert text == "담당: {{담당자}}"
    assert report.missing_fields == ["담당자"]
    assert report.has_issues


def test_empty_value_is_warned_not_fatal():
    text, report = render_record("비고: {{비고}}", {"비고": ""})
    assert text == "비고: "
    assert report.empty_fields == ["비고"]
    assert report.missing_fields == []
    assert not report.has_issues


def test_no_inline_formatter_pipe_token_left_literal():
    # 인라인 포매터는 폐기 — {{필드|amount}} 는 토큰으로 매칭되지 않고 원문에 남는다(신호).
    text, report = render_record("{{배정예산|amount}}", {"배정예산": "150000000"})
    assert text == "{{배정예산|amount}}"
    assert report.missing_fields == []  # 파이프 토큰은 필드로 안 잡힘


def test_template_fields_lists_referenced_names_in_order():
    tpl = "{{계약명}} / {{공고기관}} / {{계약명}}"
    assert template_fields(tpl) == ["계약명", "공고기관"]


def test_report_dedupes_repeated_missing_tokens():
    _, report = render_record("{{a}} {{a}} {{b}}", {})
    assert report.missing_fields == ["a", "b"]


def test_profile_supplies_display_format_then_pure_substitution():
    """D-6 통합: 프로파일이 표시형까지 서식한 값 → 순수 치환으로 텍스트에 꽂힌다."""
    profile = MappingProfile(mappings=[
        FieldMapping("배정예산", "asignBdgtAmt", type="amount"),      # 기본(원)
        FieldMapping("개찰일시", "opengDate", type="date", fmt="%Y-%m-%d"),
    ])
    record = profile.apply({"asignBdgtAmt": "150000000", "opengDate": "2026-06-15"})
    tpl = "예산: {{배정예산}} / 개찰: {{개찰일시}}"
    text, report = render_record(tpl, record)
    assert text == "예산: 150,000,000원 / 개찰: 2026-06-15"
    assert not report.has_issues


# ------------------------------------------------ 채움 표지 삼분(결정 22·33) — render_segments
def test_segments_three_way_marking():
    """원문/채움/미채움 + 빈값 4종 — 종류와 원문 텍스트가 정확히 분류된다."""
    tpl = "1. 건명: {{건명}}\n2. 기한: {{기한}}\n3. 담당: {{담당}}"
    rec = {"건명": "복사용지 구매", "기한": ""}  # 담당=미채움(레코드에 없음)
    segments, report = render_segments(tpl, rec)
    got = [(s.kind, s.text, s.name) for s in segments]
    assert got == [
        (SEG_LITERAL, "1. 건명: ", ""),
        (SEG_FILL, "복사용지 구매", "건명"),
        (SEG_LITERAL, "\n2. 기한: ", ""),
        (SEG_BLANK, "", "기한"),
        (SEG_LITERAL, "\n3. 담당: ", ""),
        (SEG_MISSING, "{{담당}}", "담당"),
    ]
    assert report.missing_fields == ["담당"]
    assert report.empty_fields == ["기한"]


def test_segments_text_join_equals_render_record():
    """불변식: 세그먼트 텍스트 연결 == render_record 텍스트(표지는 앱 렌더 전용·평문 불변)."""
    tpl = "{{a}} 사이 {{b}} 끝 {{c}}"
    rec = {"a": "값A", "b": ""}  # c 미채움
    segments, _ = render_segments(tpl, rec)
    text, _ = render_record(tpl, rec)
    assert "".join(s.text for s in segments) == text


def test_segments_adjacent_tokens_no_empty_literal():
    """토큰이 붙어 있으면 빈 literal 조각을 내지 않는다(양끝·사이 모두)."""
    segments, _ = render_segments("{{a}}{{b}}", {"a": "1", "b": "2"})
    assert [(s.kind, s.text) for s in segments] == [(SEG_FILL, "1"), (SEG_FILL, "2")]


def test_segments_consecutive_literals_merged():
    """토큰 없는 순수 원문은 literal 한 조각으로 합쳐진다."""
    segments, _ = render_segments("머리말만 있는 문장", {})
    assert [(s.kind, s.text) for s in segments] == [(SEG_LITERAL, "머리말만 있는 문장")]


def test_segments_empty_template_yields_nothing():
    segments, report = render_segments("", {})
    assert segments == []
    assert not report.has_issues


# --------------------------------------- 선언-조건부 정렬 린트(R-flow 블록 3 결정 17)

def test_space_run_predicate_ignores_single_space():
    """1칸 공백은 낱말 사이라 정렬 의도가 아니다 — 경보 남발 차단."""
    assert has_space_run("건 명: 전산장비") is False
    assert has_space_run("건    명: 전산장비") is True
    assert has_space_run("들여쓰기\n  둘째 줄") is True  # 줄 첫머리 정렬도 런


def test_align_fullwidth_preserves_width_and_odd_remainder():
    """반각 2칸 = 전각 1칸(폭 보존). 홀수 잔여 1칸은 반각으로 남는다."""
    assert align_fullwidth("건    명") == "건" + FULLWIDTH_SPACE * 2 + "명"
    assert align_fullwidth("건   명") == "건" + FULLWIDTH_SPACE + " 명"
    assert align_fullwidth("건 명") == "건 명"  # 1칸은 불변


def test_align_closes_the_lint_predicate():
    """술어와 처방이 서로를 닫는다 — 치환 후엔 경보가 재발하지 않는다(무한 잔소리 금지)."""
    for src in ("건    명", "건   명", "a  b   c    d"):
        assert has_space_run(align_fullwidth(src)) is False


def test_align_segments_keeps_join_invariant_and_kinds():
    """세그먼트별 치환도 '이어붙이면 클립보드 평문' 불변식과 표지 종류를 지킨다."""
    tpl = "건    명: {{공고명}}\n금    액: {{금액}}"
    rec = {"공고명": "전산장비  구매", "금액": ""}
    segments, _ = render_segments(tpl, rec)
    assert segments_have_space_run(segments) is True
    aligned = align_segments(segments)
    assert [s.kind for s in aligned] == [s.kind for s in segments]
    assert [s.name for s in aligned] == [s.name for s in segments]
    assert segments_have_space_run(aligned) is False
    joined = "".join(s.text for s in aligned)
    assert FULLWIDTH_SPACE in joined and "  " not in joined
    # 값 안의 런도 함께 치환된다(데이터에서 온 정렬도 목적지에선 같은 취약점).
    assert "전산장비" + FULLWIDTH_SPACE + "구매" in joined


def test_align_segments_leaves_empty_segments_untouched():
    """빈 값(blank) 조각은 그대로 — 표지 계약(빈 텍스트)이 치환으로 변질되지 않는다."""
    segments, _ = render_segments("{{a}}  끝", {"a": ""})
    aligned = align_segments(segments)
    assert aligned[0].text == "" and aligned[0].kind == SEG_BLANK
