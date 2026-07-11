"""디자인 토큰 단일 출처 동기화 가드 — Qt/QApplication 불필요(순수 stdlib).

색 hex 를 ``style.py``·``mapping_table.py``·목업 세 곳에 손으로 중복하던 드리프트를
봉쇄하는 계약 테스트: ``design_tokens.json`` 이 생성하는 영역과 디스크 내용이 어긋나면 실패.
어긋났을 때 복구는 ``python scripts/gen_design_tokens.py``.
"""
from __future__ import annotations

import gen_design_tokens as gen


def test_tokens_in_sync():
    problems = gen.check()
    assert not problems, (
        "토큰 드리프트: " + "; ".join(problems)
        + " — `python scripts/gen_design_tokens.py` 로 재생성하세요."
    )


def test_style_region_renders_expected_constants():
    region = gen.render_style_region(gen.load_tokens())
    assert 'PRIMARY = "#2874a6"' in region
    assert 'SELECT_BG = "#dce9f5"' in region      # BASE_QSS 선택 하이라이트가 참조
    assert 'UNCONFIRMED_BG = "#fff3bf"' in region  # mapping_table 이 임포트


def test_mockup_region_maps_app_palette():
    region = gen.render_mockup_region(gen.load_tokens())
    assert "--a-primary:#2874a6;" in region
    assert "--a-sel:#dce9f5;" in region
