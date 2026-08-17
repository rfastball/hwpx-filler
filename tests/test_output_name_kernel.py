"""domain output-name kernel — naming·delivery 가 공유하는 sanitation·서식 단일 출처."""

from __future__ import annotations

from datetime import datetime

from hwpxfiller.domain.output_name import (
    clean_filename,
    format_date_token,
    format_seq_token,
)


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
