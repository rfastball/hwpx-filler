"""출력 이름 kernel — 해석·조립·안전 판정·배치 충돌의 단일 출처 (#798 · #1081 PR1).

managed 배달과 표시·legacy 표면이 같은 함수를 부르므로, 여기 규칙이 곧 두 표면의 규칙이다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

import hwpxfiller.application.generation_delivery as gd
from hwpxfiller.domain.output_name import (
    OUTPUT_NAME_PATTERN_INVALID,
    OUTPUT_PATH_ESCAPE_DETECTED,
    FieldValueToken,
    LiteralSegment,
    OutputNameError,
    ReservedDateToken,
    ReservedSequenceToken,
    clean_filename,
    collision_key,
    dedupe_output_names,
    format_date_token,
    format_seq_token,
    guard_output_name,
    parse_filename_pattern,
    render_output_name,
)
from hwpxfiller.naming import plan_output_names

_NOW = datetime(2026, 9, 30, 9, 0, 0)


# ─── sanitation · 예약 토큰 서식(종전 kernel 범위) ─────────────────────────────────
def test_clean_filename_replaces_forbidden_chars() -> None:
    assert clean_filename('a\\b/c:d*e?f"g<h>i|j\r\n\tk') == "a_b_c_d_e_f_g_h_i_j___k"
    assert clean_filename("정상 이름") == "정상 이름"  # 공백은 보존


def test_format_date_token_default_and_full_spec() -> None:
    now = datetime(2026, 3, 4, 9, 15, 7)
    assert format_date_token(None, now) == "20260304"  # 기본 YYYYMMDD
    assert format_date_token("YY-MM-DD HH:mm:SS", now) == "26-03-04 09_15_07"  # ':' → '_'


def test_format_seq_token_pad_and_nopad() -> None:
    assert format_seq_token(None, 7) == "7"
    assert format_seq_token("001", 7) == "007"  # pad 길이가 폭


# ─── 해석 ────────────────────────────────────────────────────────────────────────
def test_parse_splits_literals_reserved_and_field_tokens():
    assert parse_filename_pattern("공고-{{date:YYYY}}-{{seq:001}}-{{이름}}") == (
        LiteralSegment("공고-"),
        ReservedDateToken("YYYY"),
        LiteralSegment("-"),
        ReservedSequenceToken("001"),
        LiteralSegment("-"),
        FieldValueToken("이름"),
    )


@pytest.mark.parametrize("pattern", ["", "{{이름", "a{{}}b", "{{a{b}}", "x-{{date"])
def test_malformed_patterns_are_loud(pattern):
    with pytest.raises(OutputNameError) as info:
        parse_filename_pattern(pattern)
    assert info.value.code == OUTPUT_NAME_PATTERN_INVALID


def test_single_braces_stay_literal():
    assert parse_filename_pattern("a{b}c") == (LiteralSegment("a{b}c"),)


# ─── 조립 ────────────────────────────────────────────────────────────────────────
def test_render_cleans_values_but_not_literals():
    name, parts = render_output_name(
        parse_filename_pattern("{{이름}}-{{date:YYYY/MM}}"), {"이름": "a/b"}, seq=1, now=_NOW
    )
    assert name == "a_b-2026_09.hwpx"
    assert [p.kind for p in parts] == ["FIELD", "DATE"]


def test_render_unresolved_token_is_an_error_unless_asked_to_keep_it():
    tokens = parse_filename_pattern("{{없음}}")
    with pytest.raises(KeyError):
        render_output_name(tokens, {}, seq=1, now=_NOW)
    name, _ = render_output_name(tokens, {}, seq=1, now=_NOW, keep_unresolved=True)
    assert name == "{{없음}}.hwpx"


# ─── 안전 판정(#798) ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name",
    [
        "../x.hwpx", "..x.hwpx", "..", ".",               # 상위 경로
        "a/b.hwpx", "a\\b.hwpx",                          # 경로 구분자
        "C:x.hwpx", "x:stream.hwpx",                      # drive-relative·ADS
        'a*b.hwpx', 'a?b.hwpx', 'a"b.hwpx', "a<b.hwpx", "a>b.hwpx", "a|b.hwpx",
        "a\x00b.hwpx", "a\x01b.hwpx",                     # NUL·제어문자
        ".hwpx", ".HWPX",                                 # 빈 stem
        "name.", "name ", "name.hwpx.", "name.hwpx ",     # 끝 점·공백(Windows 가 지워 저장)
        "CON", "con.hwpx", "Con.hwpx", "CON .hwpx", "con.backup.hwpx",
        "PRN.hwpx", "AUX.hwpx", "NUL.hwpx",
        "COM1.hwpx", "com9.hwpx", "LPT1.hwpx", "lpt9.hwpx",
    ],
)
def test_unsafe_names_are_refused(name):
    with pytest.raises(OutputNameError) as info:
        guard_output_name(name)
    assert info.value.code == OUTPUT_PATH_ESCAPE_DETECTED


@pytest.mark.parametrize(
    "name",
    ["보고서.hwpx", "CONSOLE.hwpx", "COM10.hwpx", "LPT0x.hwpx", "a.b.hwpx",
     "name..hwpx", "name .hwpx", "{{미해소}}.hwpx", "x.HWPX"],
)
def test_ordinary_names_pass(name):
    guard_output_name(name)


# ─── 배치 충돌 ───────────────────────────────────────────────────────────────────
def test_collision_key_is_case_insensitive():
    assert collision_key("Report.HWPX") == collision_key("report.hwpx")


def test_dedupe_is_case_insensitive_and_keeps_spelling():
    assert dedupe_output_names(["A.hwpx", "a.hwpx", "b.hwpx"]) == [
        "A.hwpx", "a_1.hwpx", "b.hwpx",
    ]


def test_dedupe_respects_occupied_names_with_the_same_key():
    assert dedupe_output_names(["Report.hwpx"], occupied_names=["REPORT.hwpx"]) == [
        "Report_1.hwpx"
    ]


# (기존 파일 충돌의 같은 키 판정은 legacy ``existing_output_paths`` 가 퇴역하며 배달 계획의 점유
#  관찰로 옮겼다 — ``test_generation_delivery``·``test_cli::test_cli_case_twins_*`` 가 잰다.)


# ─── 표시 표면 == 배달 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("pattern", "records"),
    [
        ("{{ID}}", [{"ID": "Report"}, {"ID": "report"}, {"ID": "B"}]),
        ("{{date:YYYYMMDD}}-{{seq:001}}-{{ID}}", [{"ID": "x/y"}, {"ID": "x/y"}]),
        ("공고-{{ID}}.HWPX", [{"ID": "a"}, {"ID": "A"}]),
    ],
)
def test_display_plan_equals_the_delivery_assembly(pattern, records):
    """「문서」 열(naming 어댑터)과 배달(generation_delivery)이 같은 입력에서 같은 이름을 낸다."""
    tokens = gd.parse_filename_pattern(
        pattern, filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID
    )
    base = []
    for ordinal, record in enumerate(records):
        name, _ = gd._render_item(tokens, record, ordinal=ordinal, clock=_NOW)
        gd._guard_relative_path(name)
        base.append(name)
    assert plan_output_names(pattern, records, now=_NOW) == gd._dedupe_batch(base)


@pytest.mark.parametrize(
    ("pattern", "records", "code"),
    [
        ("{{ID", [{"ID": "1"}], OUTPUT_NAME_PATTERN_INVALID),
        ("../{{ID}}", [{"ID": "1"}], OUTPUT_PATH_ESCAPE_DETECTED),
        ("{{ID}}", [{"ID": "CON"}], OUTPUT_PATH_ESCAPE_DETECTED),
    ],
)
def test_display_and_delivery_refuse_the_same_inputs(pattern, records, code):
    with pytest.raises(OutputNameError) as display:
        plan_output_names(pattern, records, now=_NOW)
    assert display.value.code == code
    with pytest.raises((gd._PatternInvalidSignal, gd._DeliveryContextSignal)) as delivery:
        tokens = gd.parse_filename_pattern(
            pattern, filename_pattern_contract_id=gd.FILENAME_PATTERN_CONTRACT_ID
        )
        name, _ = gd._render_item(tokens, records[0], ordinal=0, clock=_NOW)
        gd._guard_relative_path(name)
    if isinstance(delivery.value, gd._DeliveryContextSignal):
        assert delivery.value.code == code
    else:
        assert code == OUTPUT_NAME_PATTERN_INVALID
