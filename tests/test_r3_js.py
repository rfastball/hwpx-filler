"""코드리뷰 3차(js-shared 클러스터) 회귀 가드 — 공유 이스케이퍼(K1)·pool.js 헤더(K11).

K1: 동일 3줄 HTML 이스케이퍼가 web/js 9곳(화면 7 + 피커 2)에 복붙돼 있었다.
``web/js/esc.js`` 의 ``window.escHtml`` 하나로 통일하고, 사본이 조용히 재유입되거나
로드 순서(공유 파일이 소비 화면보다 먼저)가 깨지는 회귀를 정적으로 차단한다.
txt.js 사본만 ``"`` 를 escape 하지 않는 변종이었는데 ``title="…"``·``value="…"``
속성 컨텍스트에도 쓰이고 있어 따옴표 포함 값이 속성을 깨는 잠복 결함 — 통일이 봉합.

K11: pool.js 헤더 주석이 '기대 DOM…브리지 메서드 추가 예정'이라는 미래형(거짓)
기술이었다 — 실제로는 전부 배선돼 있다. 현재형 기술로 고치고 재퇴행을 가드한다.
"""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
WEB_INDEX = WEB / "index.html"
WEB_JS = WEB / "js"

# 공유 이스케이퍼를 소비하는 파일들 — 전부 esc.js 뒤에 로드돼야 한다.
ESC_CONSUMERS = (
    "sheet_picker.js", "pool_picker.js",
    "screens/home.js", "screens/txt.js", "screens/editor.js", "screens/run.js",
    "screens/template.js", "screens/pool.js",
)


def test_esc_helper_exists_and_escapes_superset():
    """esc.js 가 window.escHtml 을 노출하고 & < > " 넉 자를 전부 다룬다(txt.js 변종 봉합)."""
    src = (WEB_JS / "esc.js").read_text(encoding="utf-8")
    assert "window.escHtml" in src, "esc.js 가 window.escHtml 을 노출하지 않습니다(K1)."
    for ent in ("&amp;", "&lt;", "&gt;", "&quot;"):
        assert ent in src, f"esc.js 이스케이프 맵에 {ent} 가 없습니다 — 속성 컨텍스트 안전 초집합 회귀(K1)."


def test_esc_loaded_before_all_consumers():
    """index.html 로드 순서 — esc.js 가 모든 소비 스크립트보다 먼저 와야 한다(K1)."""
    index = WEB_INDEX.read_text(encoding="utf-8")
    assert 'src="js/esc.js"' in index, "esc.js 가 index.html 에 로드되지 않았습니다(K1)."
    esc_pos = index.index('src="js/esc.js"')
    for rel in ESC_CONSUMERS:
        needle = f'src="js/{rel}"'
        assert needle in index, f"{rel} 이 index.html 에 로드되지 않았습니다."
        assert index.index(needle) > esc_pos, (
            f"{rel} 이 esc.js 보다 먼저 로드됩니다 — window.escHtml 미정의 시점 참조(K1)."
        )


def test_no_local_escaper_copies_remain():
    """web/js 어디에도 로컬 이스케이퍼 함수 사본이 재유입되지 않아야 한다(K1 9중복 회귀 가드).

    esc.js(단일 출처) 밖에서 `function esc…` 정의나 escape 치환 맵 리터럴이 보이면
    복붙 사본이 되살아난 것 — 전부 window.escHtml 참조여야 한다.
    """
    copy_def = re.compile(r"function\s+esc(Html)?\s*\(")
    escape_map = re.compile(r"""["']&["']\s*:\s*["']&amp;["']""")
    for path in WEB_JS.rglob("*.js"):
        src = path.read_text(encoding="utf-8")
        if path.name == "esc.js":
            continue
        assert not copy_def.search(src), (
            f"{path.name} 에 로컬 이스케이퍼 정의가 재유입됐습니다 — window.escHtml 을 쓰세요(K1)."
        )
        assert not escape_map.search(src), (
            f"{path.name} 에 escape 치환 맵 사본이 재유입됐습니다 — window.escHtml 을 쓰세요(K1)."
        )
    # 소비 파일들은 실제로 공유 헬퍼를 참조해야 한다(정의 삭제만 하고 미배선 방지).
    for rel in ESC_CONSUMERS:
        src = (WEB_JS / rel).read_text(encoding="utf-8")
        assert "window.escHtml" in src, f"{rel} 이 window.escHtml 을 참조하지 않습니다(K1)."


def test_pool_header_describes_delivered_state():
    """pool.js 헤더가 배달된 현재 상태를 기술해야 한다 — 미래형 거짓 기술 재퇴행 가드(K11)."""
    src = (WEB_JS / "screens" / "pool.js").read_text(encoding="utf-8")
    header = src.split("(function", 1)[0]  # IIFE 이전 = 파일 헤더 주석
    for stale in ("통합 단계에서 index.html 에 추가", "브리지 메서드 추가 예정", "그때까지 경로 직접 입력"):
        assert stale not in header, (
            f"pool.js 헤더에 낡은 미래형 기술('{stale}')이 남아 있습니다 — 배선은 이미 존재(K11)."
        )
    # 헤더가 기술하는 배선이 실제로 존재하는지 상호 검증(주석-코드 정합).
    assert "pickPoolDataFile" in header and "poolRegBrowse" in header, (
        "pool.js 헤더가 실제 배선(poolRegBrowse→Bridge.pickPoolDataFile)을 기술하지 않습니다(K11)."
    )
    assert "poolRegBrowse" in src.split("(function", 1)[1], "헤더가 기술한 poolRegBrowse 배선이 코드에 없습니다."
