"""파일명 생성 테스트 — Qt 불필요(순수 로직).

``{{키}}`` 하위호환 + 날짜/연번 예약 토큰 + ``OutputNamer`` 의 충돌 접미사·배치 상태.
날짜·연번은 ``now``/``seq`` 를 주입해 결정적으로 검증한다.
"""

from __future__ import annotations

from datetime import datetime

from hwpxfiller.naming import OutputNamer, clean_filename, make_output_filename

_NOW = datetime(2026, 7, 9, 14, 5, 3)


# ------------------------------------------------------------- 하위호환/위생
def test_key_substitution_backward_compatible():
    assert make_output_filename("공고서-{{ID}}", {"ID": "A1"}) == "공고서-A1.hwpx"


def test_illegal_chars_sanitized_in_value():
    out = make_output_filename("{{name}}", {"name": "a/b:c*d"})
    assert out == "a_b_c_d.hwpx"


def test_hwpx_extension_enforced_case_insensitive():
    assert make_output_filename("x.HWPX", {}) == "x.HWPX"
    assert make_output_filename("x", {}) == "x.hwpx"


def test_missing_key_left_untouched():
    # 데이터에 없는 키 토큰은 그대로 남는다(기존 동작).
    assert make_output_filename("{{a}}-{{b}}", {"a": "1"}) == "1-{{b}}.hwpx"


def test_field_formatter_in_filename_shares_vocab():
    # 파일명 필드 토큰도 공용 포매터 어휘를 쓴다(데이터 값 date 재서식).
    out = make_output_filename("{{개찰일시|date:YYYYMMDD}}", {"개찰일시": "2026-06-15"})
    assert out == "20260615.hwpx"


def test_field_default_formatter_in_filename():
    assert make_output_filename("{{비고|default:없음}}", {"비고": ""}) == "없음.hwpx"


# ------------------------------------------------------------------- 날짜 토큰
def test_date_default_is_yyyymmdd():
    assert make_output_filename("{{date}}", {}, now=_NOW) == "20260709.hwpx"


def test_date_custom_format():
    assert make_output_filename("{{date:YYYY-MM-DD}}", {}, now=_NOW) == "2026-07-09.hwpx"


def test_date_month_vs_minute_case_sensitive():
    # MM=월(07), mm=분(05) — 대소문자 구분이 하중.
    assert make_output_filename("{{date:MM-mm}}", {}, now=_NOW) == "07-05.hwpx"


def test_date_time_components():
    assert make_output_filename("{{date:HHmmSS}}", {}, now=_NOW) == "140503.hwpx"


def test_date_slash_in_format_is_sanitized():
    assert make_output_filename("{{date:YYYY/MM}}", {}, now=_NOW) == "2026_07.hwpx"


def test_date_mixed_with_key():
    out = make_output_filename("{{date:YYYYMMDD}}-{{ID}}", {"ID": "7"}, now=_NOW)
    assert out == "20260709-7.hwpx"


# ------------------------------------------------------------------- 연번 토큰
def test_seq_unpadded():
    assert make_output_filename("{{seq}}", {}, seq=12) == "12.hwpx"


def test_seq_padded_width_from_literal():
    assert make_output_filename("{{seq:001}}", {}, seq=7) == "007.hwpx"


def test_seq_default_is_one_when_absent():
    assert make_output_filename("{{seq:00}}", {}) == "01.hwpx"


# ------------------------------------------------------------- OutputNamer 상태
def test_namer_seq_increments_per_next():
    namer = OutputNamer("doc-{{seq:001}}", now=_NOW)
    assert namer.next({}) == "doc-001.hwpx"
    assert namer.next({}) == "doc-002.hwpx"
    assert namer.next({}) == "doc-003.hwpx"


def test_namer_collision_appends_suffix():
    namer = OutputNamer("doc-{{ID}}", now=_NOW)
    assert namer.next({"ID": "A1"}) == "doc-A1.hwpx"
    assert namer.next({"ID": "A1"}) == "doc-A1_1.hwpx"
    assert namer.next({"ID": "A1"}) == "doc-A1_2.hwpx"


def test_namer_collision_does_not_clobber_explicit_suffix():
    # 명시적 _1 이 먼저 등장하면, 이후 base 충돌은 _2 로 건너뛴다.
    namer = OutputNamer("{{ID}}", now=_NOW)
    assert namer.next({"ID": "doc_1"}) == "doc_1.hwpx"
    assert namer.next({"ID": "doc"}) == "doc.hwpx"
    assert namer.next({"ID": "doc"}) == "doc_2.hwpx"


def test_namer_date_constant_across_batch():
    namer = OutputNamer("{{date:YYYYMMDD}}-{{seq}}", now=_NOW)
    a = namer.next({})
    b = namer.next({})
    assert a == "20260709-1.hwpx"
    assert b == "20260709-2.hwpx"


def test_namer_deterministic_given_order():
    recs = [{"ID": "A"}, {"ID": "A"}, {"ID": "B"}]
    n1 = OutputNamer("{{ID}}", now=_NOW)
    n2 = OutputNamer("{{ID}}", now=_NOW)
    assert [n1.next(r) for r in recs] == [n2.next(r) for r in recs]


def test_clean_filename_direct():
    assert clean_filename('a\\b/c:d') == "a_b_c_d"
