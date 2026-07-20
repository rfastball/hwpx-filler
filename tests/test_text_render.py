"""텍스트 렌더 코어 — 순수 {{필드}} 치환(서식은 프로파일 소관, 인라인 포매터 없음)."""

from __future__ import annotations

from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_render import (
    SEG_BLANK,
    SEG_FILL,
    SEG_LITERAL,
    SEG_MISSING,
    render_record,
    render_segments,
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
