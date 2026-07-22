"""H-09 기안 workcard·큐 탐색 시각/스크롤 계약 가드."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
DRAFT = (ROOT / "web" / "js" / "draftsession.js").read_text(encoding="utf-8")
PRESERVE = (ROOT / "web" / "js" / "preserve.js").read_text(encoding="utf-8")


def _declarations(selector: str) -> str:
    bodies: list[str] = []
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in {part.strip() for part in selectors.split(",")}:
            bodies.append(re.sub(r"\s+", "", body))
    assert bodies, f"missing selector: {selector}"
    return ";".join(bodies)


def test_draft_card_render_is_a_capped_preserved_scrollport():
    assert re.search(
        r'<pre class="wc-render" id="draftCardRender"[^>]*data-preserve-scroll', INDEX
    )
    rule = _declarations(".zone.workcard .wc-render")
    assert "min-height:180px" in rule and "max-height:360px" in rule
    assert "overflow:auto" in rule
    assert "scrollbar-gutter:stable" in rule and "overscroll-behavior:contain" in rule
    assert "scrollTop" in PRESERVE and "marked[i].scrollTop" in PRESERVE


def test_queue_dots_wrap_without_an_inner_scrollport():
    dots = _declarations(".wc-dots")
    assert "display:flex" in dots and "flex-wrap:wrap" in dots
    assert "overflow:visible" in dots
    assert "max-height:" not in dots and "overflow:auto" not in dots


def test_queue_dot_keeps_fourteen_pixel_mark_inside_24px_hit_target():
    hit = _declarations(".wc-dot")
    mark = _declarations(".wc-dot::before")
    assert "width:24px" in hit and "height:24px" in hit
    assert "width:14px" in mark and "height:14px" in mark
    assert "top:5px" in mark and "left:5px" in mark
    assert "border-radius:var(--rad-pill)" in hit
    assert "border-radius:var(--rad-pill)" in mark


def test_degenerate_queue_hiding_and_inset_removal_survive():
    assert "$(id.cardDots).hidden = degen" in DRAFT
    assert ".wc-dots[hidden]{display:none}" in CSS
    render = _declarations(".wc-render")
    assert "box-shadow:" not in render
