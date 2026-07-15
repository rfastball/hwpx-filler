"""디자인 토큰 단일 출처 동기화 가드 — Qt/QApplication 불필요(순수 stdlib).

색 hex 를 웹 CSS·목업 여러 곳에 손으로 중복하던 드리프트를 봉쇄하는 계약 테스트:
``design_tokens.json`` 이 생성하는 영역과 디스크 내용이 어긋나면 실패. Qt style.py 생성
타깃은 PySide6 제거(#23)로 폐기됐다 — 팔레트는 이제 웹 CSS 변수로만 소비된다.
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


def test_web_region_renders_expected_palette_and_tints():
    """웹 CSS 변수 영역이 핵심 팔레트·배지/중성 틴트를 design_tokens.json 에서 생성한다."""
    region = gen.render_web_region(gen.load_tokens())
    assert "--a-primary:#2874a6;" in region
    assert "--a-sel:#dce9f5;" in region            # 선택 하이라이트
    assert "--a-unconf:#fff3bf;" in region         # 미확정 배경
    # 배지·중성 틴트(V14/UD-33 환원)가 웹 변수로 실린다.
    assert "--fb-missing-bg:#fbe6e3;" in region
    assert "--n-ink-control:#2b3038;" in region
    assert "--n-track:#eef0f3;" in region


def test_mockup_region_maps_app_palette():
    region = gen.render_mockup_region(gen.load_tokens())
    assert "--a-primary:#2874a6;" in region
    assert "--a-sel:#dce9f5;" in region
