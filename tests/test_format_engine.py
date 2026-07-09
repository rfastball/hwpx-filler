"""표시형 서식 엔진(어댑터) — stdlib(포맷스펙+strftime), 파싱→서식→degrade."""

from __future__ import annotations

from hwpxfiller.core.format_engine import StdlibFormatEngine, presets, render


def test_amount_default_and_custom_codes():
    # 빈 코드 = 기본(원 붙임).
    assert render("amount", "", "150000000") == "150,000,000원"
    # 커스텀 str.format 스펙.
    assert render("amount", "{:,}", "150000000") == "150,000,000"
    assert render("amount", "{:,.2f}", "1234.5") == "1,234.50"
    assert render("amount", "일금 {:,}원정", "150000000") == "일금 150,000,000원정"


def test_amount_parses_leniently_and_degrades():
    # 콤마·접미 섞여도 수를 뽑는다.
    assert render("amount", "{:,}", "21,326,800원") == "21,326,800"
    # 수가 아니면 원본 그대로(degrade).
    assert render("amount", "{:,}원", "미정") == "미정"
    # 잘못된 서식 코드도 degrade(원본).
    assert render("amount", "{:Q}", "100") == "100"


def test_datetime_default_and_strftime_codes():
    # 빈 코드 = 한글 기본(월/일 비패딩), 시각 있으면 보존.
    assert render("datetime", "", "2026-06-15") == "2026년 6월 15일"
    assert render("datetime", "", "2026-06-15 18:00") == "2026년 6월 15일 18:00"
    # strftime 코드.
    assert render("datetime", "%Y-%m-%d", "2026-6-5") == "2026-06-05"
    assert render("datetime", "%Y.%m.%d", "2026-06-15") == "2026.06.15"


def test_datetime_degrades_on_unparseable():
    assert render("datetime", "%Y-%m-%d", "미정") == "미정"


def test_no_format_kind_passthrough():
    assert render("join", "%Y", "값") == "값"
    assert render("const", "{:,}", "값") == "값"


def test_presets_are_label_code_pairs():
    amount = dict(presets("amount"))
    assert amount["원"] == ""          # 기본
    assert amount["숫자"] == "{:,}"
    dt = dict(presets("datetime"))
    assert dt["한글"] == ""
    assert dt["ISO"] == "%Y-%m-%d"
    assert presets("join") == []       # 표시형 없는 kind


def test_engine_is_swappable_via_protocol():
    # 어댑터 이음새: 다른 FormatEngine 구현을 꽂을 수 있다.
    class DummyEngine:
        def render(self, kind, code, value):
            return f"<{kind}:{value}>"

        def presets(self, kind):
            return []

    import hwpxfiller.core.format_engine as fe

    original = fe.ENGINE
    try:
        fe.ENGINE = DummyEngine()
        assert fe.render("amount", "", "100") == "<amount:100>"
    finally:
        fe.ENGINE = original
    # 원복 확인.
    assert isinstance(fe.ENGINE, StdlibFormatEngine)
    assert render("amount", "", "100") == "100원"
