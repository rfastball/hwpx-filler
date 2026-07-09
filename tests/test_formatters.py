"""공용 포매터 레지스트리 + 토큰 엔진(리프) — 헤드리스."""

from __future__ import annotations

from hwpxfiller.core.formatters import (
    apply_chain,
    apply_formatter,
    parse_chain,
    referenced_fields,
    render_tokens,
)


def test_individual_formatters():
    assert apply_formatter("amount", "150000000", None) == "150,000,000원"
    assert apply_formatter("datetime", "2026-06-15", None) == "2026년 6월 15일"
    assert apply_formatter("datetime", "2026-06-15 09:00", None) == "2026년 6월 15일 09:00"
    assert apply_formatter("date", "2026-6-5", "YYYY-MM-DD") == "2026-06-05"
    assert apply_formatter("upper", "abc", None) == "ABC"
    assert apply_formatter("lower", "ABC", None) == "abc"
    assert apply_formatter("trim", "  x  ", None) == "x"
    assert apply_formatter("default", "", "없음") == "없음"
    assert apply_formatter("default", "값", "없음") == "값"


def test_unknown_formatter_returns_none():
    assert apply_formatter("nope", "x", None) is None


def test_amount_and_date_passthrough_on_unparseable():
    assert apply_formatter("amount", "미정", None) == "미정"
    assert apply_formatter("date", "미정", "YYYY") == "미정"


def test_parse_chain():
    assert parse_chain(None) == []
    assert parse_chain("|trim|upper") == [("trim", None), ("upper", None)]
    assert parse_chain("|date:YYYY-MM-DD") == [("date", "YYYY-MM-DD")]
    assert parse_chain("|default:없음") == [("default", "없음")]


def test_apply_chain_reports_unknown_and_keeps_value():
    value, unknown = apply_chain("abc", [("trim", None), ("nope", None), ("upper", None)])
    assert value == "ABC"  # 미지 포매터는 건너뛰고 나머지 적용
    assert unknown == ["nope"]


def test_render_tokens_keeps_token_on_unknown_in_chain():
    text, missing, empty, unknown = render_tokens("{{x|trim|nope}}", {"x": "  a  "})
    assert text == "{{x|trim|nope}}"  # 체인에 미지 포매터 → 토큰 통째 유지(글라링)
    assert unknown == ["nope"]


def test_referenced_fields_dedup_in_order():
    assert referenced_fields("{{a}} {{b|upper}} {{a}}") == ["a", "b"]


def test_field_names_with_internal_spaces():
    text, missing, _, _ = render_tokens("{{공 고 명}}", {"공 고 명": "청소용역"})
    assert text == "청소용역"
    assert missing == []
