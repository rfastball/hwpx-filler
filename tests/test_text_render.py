"""텍스트 렌더 코어 — 순수 {{필드}} 치환(서식은 프로파일 소관, 인라인 포매터 없음)."""

from __future__ import annotations

from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_render import render_record, template_fields


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
