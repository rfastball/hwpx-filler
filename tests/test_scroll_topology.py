"""H-07 스크롤 토폴로지 정적 계약(#241).

실 레이아웃 판정은 통합 WebView2 프로브가 소유한다. 여기서는 허용된 내부 스크롤포트와
sticky/gutter/체이닝 CSS가 DOM에서 이탈하지 않도록 가드한다.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
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


def test_draft_map_header_sticks_inside_its_capped_host() -> None:
    """실제로 세로 스크롤되는 dmap host와 불투명 sticky 헤더를 함께 고정한다."""
    assert 'id="draftTokPanel" class="mapwrap"' in INDEX
    host = _declarations("#draftTokPanel")
    assert "max-height:" in host and "overflow:auto" in host

    header = _declarations("table.dmap th")
    assert "position:sticky" in header and "top:0" in header
    assert "z-index:1" in header
    assert "background:var(--a-window)" in header


def test_capped_scrollport_inventory_matches_dom_and_behavior_contract() -> None:
    """허용된 캡 스크롤러 6종은 DOM에 있고 gutter/overscroll 계약을 공유한다."""
    inventory = {
        ".tblwrap": EDITOR,
        ".mapwrap": INDEX,
        ".jobtbwrap": INDEX,
        ".tpllist": INDEX,
        ".sheet-list": INDEX,
        ".colpanel .cp-vals": DATAZONE,
    }
    dom_needles = {
        ".tblwrap": 'class="tblwrap"',
        ".mapwrap": 'class="mapwrap"',
        ".jobtbwrap": "jobtbwrap",
        ".tpllist": "tpllist",
        ".sheet-list": "sheet-list",
        ".colpanel .cp-vals": "cp-vals",
    }

    for selector, source in inventory.items():
        assert dom_needles[selector] in source, f"{selector}가 실제 DOM에서 사라졌습니다."
        declarations = _declarations(selector)
        assert "scrollbar-gutter:stable" in declarations, selector
        assert "overscroll-behavior:contain" in declarations, selector
