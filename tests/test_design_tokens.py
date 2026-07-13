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
    # V2 신설 셀렉터가 참조하는 토큰(UD-12 danger 버튼 hover·UD-16 drift 배경).
    assert 'MISSING_BG = "#fbe6e3"' in region
    assert 'DANGER = "#c0392b"' in region
    assert 'MUTED = "#656a72"' in region


def test_style_region_renders_v14_neutral_and_metric_tokens():
    """V14/UD-33 — 중성 회색·배지 틴트·metric 스케일이 <gen:tokens> 로 생성된다.

    이들은 수작성 BASE_QSS 가 raw hex/스케일밖 리터럴로 산재하던 것을 환원한 단일 출처다 —
    생성 영역에 빠지면 BASE_QSS f-string 이 NameError 로 시끄럽게 깨진다(조용한 드리프트 아님).
    """
    region = gen.render_style_region(gen.load_tokens())
    # 중성 회색 스케일(raw hex 12종 환원) + 배지 테두리 틴트.
    assert 'NEUTRAL_INK_CONTROL = "#2b3038"' in region
    assert 'NEUTRAL_TRACK = "#eef0f3"' in region
    assert 'MISSING_BORDER = "#e6a49c"' in region
    # metric 스케일은 정수 리터럴(따옴표 없음)로 생성 — QSS f-string 산술·뷰 여백이 참조.
    assert "RADIUS_PILL = 11" in region
    assert "RADIUS_MD = 6" in region
    assert "SPACE_MD = 12" in region
    assert "TYPE_KPI = 22" in region


def test_mockup_region_maps_app_palette():
    region = gen.render_mockup_region(gen.load_tokens())
    assert "--a-primary:#2874a6;" in region
    assert "--a-sel:#dce9f5;" in region
