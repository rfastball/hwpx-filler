"""텍스트 렌더 코어 — 순수 문자열 치환(헤드리스, PySide6 무관)."""

from __future__ import annotations

from hwpxfiller.core.text_render import RenderReport, render_record, template_fields


def test_basic_substitution_and_labeled_items():
    tpl = "계약명: {{계약명}}\n공고기관: {{공고기관}}"
    rec = {"계약명": "청사 유지보수", "공고기관": "조달청"}
    text, report = render_record(tpl, rec)
    assert text == "계약명: 청사 유지보수\n공고기관: 조달청"
    assert not report.has_issues


def test_formatter_reuse_amount_and_datetime():
    # 포매터는 mapping.apply_transform 을 그대로 재사용한다(어휘 포크 없음).
    text, report = render_record("예산: {{배정예산|amount}}", {"배정예산": "150000000"})
    assert text == "예산: 150,000,000원"
    assert not report.has_issues

    text, _ = render_record("개찰: {{개찰일시|datetime}}", {"개찰일시": "2026-06-15"})
    assert text == "개찰: 2026년 6월 15일"


def test_join_is_combiner_only_not_inline_formatter():
    # join 은 mapping 의 결합자(N→1)일 뿐, 인라인 1→1 포매터가 아니다 → 미지로 신고.
    text, report = render_record("{{지역|join:, }}", {"지역": "서울"})
    assert text == "{{지역|join:, }}"
    assert report.unknown_formatters == ["join"]


def test_formatter_chaining_left_to_right():
    text, report = render_record("{{계약명|trim|upper}}", {"계약명": "  abc  "})
    assert text == "ABC"
    assert not report.has_issues


def test_default_rescues_empty_and_suppresses_empty_report():
    text, report = render_record("{{비고|default:없음}}", {"비고": ""})
    assert text == "없음"
    assert report.empty_fields == []  # default 가 살렸으니 빈필드 신고 안 함
    assert not report.has_issues


def test_date_formatter_reformats_data_value():
    text, _ = render_record("{{개찰일시|date:YYYY-MM-DD}}", {"개찰일시": "2026-6-5"})
    assert text == "2026-06-05"


def test_missing_field_keeps_token_and_reports():
    # 데이터에 없는 필드는 조용히 지우지 않고 토큰을 남긴다(누락은 시끄럽게).
    text, report = render_record("담당: {{담당자}}", {"계약명": "X"})
    assert text == "담당: {{담당자}}"
    assert report.missing_fields == ["담당자"]
    assert report.has_issues


def test_empty_value_is_warned_not_fatal():
    text, report = render_record("비고: {{비고}}", {"비고": ""})
    assert text == "비고: "
    assert report.empty_fields == ["비고"]
    assert report.missing_fields == []
    assert not report.has_issues  # 빈 값은 경고일 뿐 치명 아님


def test_whitespace_value_is_rendered_faithfully_but_flagged():
    # 공백뿐인 값을 몰래 "" 로 뭉개지 않는다(충실도). 다만 경고로 신고.
    text, report = render_record("비고: {{비고}}", {"비고": "   "})
    assert text == "비고:    "  # 콜론 뒤 1칸 + 값 3칸
    assert report.empty_fields == ["비고"]


def test_unknown_formatter_keeps_token_and_reports():
    text, report = render_record("{{금액|daetime}}", {"금액": "100"})
    assert text == "{{금액|daetime}}"
    assert report.unknown_formatters == ["daetime"]
    assert report.has_issues


def test_const_formatter_is_not_inline_reported_as_unknown():
    # const 는 소스 값을 무시하므로 인라인에선 미지로 신고(오타를 감추지 않음).
    _, report = render_record("{{x|const}}", {"x": "값"})
    assert report.unknown_formatters == ["const"]


def test_template_fields_lists_referenced_names_in_order():
    tpl = "{{계약명}} / {{공고기관}} / {{계약명}} / {{배정예산|amount}}"
    assert template_fields(tpl) == ["계약명", "공고기관", "배정예산"]


def test_report_dedupes_repeated_tokens():
    text, report = render_record("{{a}} {{a}} {{b}}", {})
    assert report.missing_fields == ["a", "b"]
