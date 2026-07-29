"""H-07 스크롤 토폴로지 정적 계약(#241).

실 레이아웃 판정은 통합 WebView2 프로브가 소유한다. 여기서는 허용된 내부 스크롤포트와
sticky/gutter/체이닝 CSS가 DOM에서 이탈하지 않도록 가드한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from _web_css import app_css


ROOT = Path(__file__).resolve().parents[1]
CSS = app_css()
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
EDITOR = (ROOT / "web" / "js" / "screens" / "editor.js").read_text(encoding="utf-8")
DATAZONE = (ROOT / "web" / "js" / "datazone.js").read_text(encoding="utf-8")


def _declarations(selector: str) -> str:
    """단순 top-level 규칙에서 selector에 걸린 선언을 합친다."""
    bodies: list[str] = []
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        members = {part.strip() for part in selectors.split(",")}
        if selector in members:
            bodies.append(re.sub(r"\s+", "", body))
    return ";".join(bodies)


def test_wizard_tables_share_a_real_vertical_scrollport() -> None:
    """위저드 표 3벌의 sticky 기준은 높이 제한이 있는 공용 tblwrap이다."""
    for table in ("schema-fields", "data-preview", "map"):
        assert f'<div class="tblwrap"><table class="{table}">' in EDITOR

    wrap = _declarations(".tblwrap")
    assert "max-height:" in wrap
    assert "overflow:auto" in wrap
    assert "overflow-x:auto" not in wrap

    for header in ("table.schema-fields th", "table.data-preview th", "table.map th"):
        rule = _declarations(header)
        assert "position:sticky" in rule
        assert "top:0" in rule


def test_workbench_map_header_sticks_inside_its_capped_host() -> None:
    """실제로 세로 스크롤되는 dmap host 와 불투명 sticky 헤더를 함께 고정한다.

    「기안」 사망(F6 PR-B)으로 dmap 표의 생존 host 는 작업대 좌 pane(#wbMapPanel) —
    표 클래스(dmap)와 sticky 헤더 계약은 그대로 승계됐다.
    """
    assert 'id="wbMapPanel"' in INDEX
    host = _declarations("#wbMapPanel")
    assert "max-height:" in host and "overflow:auto" in host

    header = _declarations("table.dmap th")
    assert "position:sticky" in header and "top:0" in header
    assert "z-index:1" in header
    assert "background:var(--a-window)" in header


def test_capped_scrollport_inventory_matches_dom_and_behavior_contract() -> None:
    """허용된 캡 스크롤러는 DOM 에 있고 gutter/overscroll 계약을 공유한다.

    (「기안」 사망 정산 — F6 PR-B: .mapwrap 은 DOM 소비자가 죽어 목록에서 빠졌다.)

    **#wbMapPanel 편입(U2 §2.2).** 인벤토리 주석은 처음부터 「캡+헤더 지속 표」 셋에
    #wbMapPanel 을 세어 「이 여섯 종류」라고 적어 뒀는데 선택자 목록엔 다섯만 있었다 —
    주석과 규칙이 갈린 자리였다. 작업대 좌 pane 은 행 수가 매 작업점마다 바뀌는 캡 표라
    stable gutter 가 없으면 스크롤바 출현·소멸이 그대로 폭 점프가 된다. 우 pane
    .wb-preview 는 계속 목록 밖이다 — 표가 아니라 본문 면이고 주석의 여섯에도 없다.
    """
    inventory = {
        ".tblwrap": EDITOR,
        ".jobtbwrap": INDEX,
        "#wbMapPanel": INDEX,
        ".tpllist": INDEX,
        ".sheet-list": INDEX,
        ".colpanel .cp-vals": DATAZONE,
    }
    dom_needles = {
        ".tblwrap": 'class="tblwrap"',
        ".jobtbwrap": "jobtbwrap",
        "#wbMapPanel": 'id="wbMapPanel"',
        ".tpllist": "tpllist",
        ".sheet-list": "sheet-list",
        ".colpanel .cp-vals": "cp-vals",
    }

    for selector, source in inventory.items():
        assert dom_needles[selector] in source, f"{selector}가 실제 DOM에서 사라졌습니다."
        declarations = _declarations(selector)
        assert "scrollbar-gutter:stable" in declarations, selector
        assert "overscroll-behavior:contain" in declarations, selector
