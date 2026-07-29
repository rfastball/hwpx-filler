"""H-09 workcard·큐 탐색 시각/스크롤 계약 가드 — 승계처 = 검토·복사 작업대.

「기안」 화면 사망(F6 PR-B)으로 계약의 주체가 이동했다: 카드 = #wbCard(.wb-preview 에
workbench.js 가 .wc-render·f-* 글꼴 클래스를 얹는다), 점 색인 = #wbDots(.wb-dots 판 위의
.wc-dot 항목 — 점·표지 CSS 는 「기안」 시절 그대로 재사용). 캡 수치는 .wb-preview 의 것
(180~420px)이고, 구 .wc-render 전용 부속(scrollbar-gutter·overscroll-behavior)은 죽은
구 .zone.workcard 규칙과 함께 걷혔다(승계처 .wb-preview 는 아직 선언하지 않는다).
"""
from __future__ import annotations

import re
from pathlib import Path

from _web_css import app_css


ROOT = Path(__file__).resolve().parents[1]
# 카드 수치(.wb-preview·.wb-dots)는 tail.css, 점·글꼴 클래스(.wc-dot·.wc-render.f-*)는
# draftcard.css 에 있다 — 이 창구를 거쳐야 한 검사가 승계 관계를 가로질러 본다.
CSS = app_css()
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
WORKBENCH = (ROOT / "web" / "js" / "screens" / "workbench.js").read_text(encoding="utf-8")
PRESERVE = (ROOT / "web" / "js" / "preserve.js").read_text(encoding="utf-8")


def _declarations(selector: str) -> str:
    bodies: list[str] = []
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in {part.strip() for part in selectors.split(",")}:
            bodies.append(re.sub(r"\s+", "", body))
    assert bodies, f"missing selector: {selector}"
    return ";".join(bodies)


def test_workbench_card_is_a_capped_preserved_scrollport():
    """카드 스크롤포트 승계(H-09→작업대): 캡·overflow·스크롤 보존 마크가 산다."""
    assert re.search(r'<article class="wb-preview" id="wbCard"[^>]*data-preserve-scroll', INDEX)
    rule = _declarations(".wb-preview")
    assert "min-height:180px" in rule and "max-height:420px" in rule
    assert "overflow:auto" in rule
    assert "scrollTop" in PRESERVE and "marked[i].scrollTop" in PRESERVE


def test_workbench_card_wears_the_render_and_font_classes():
    """기안 카드 시각 계약 승계 — 렌더 판(.wc-render)과 대상 글꼴 클래스(f-*)를 JS 가 얹는다."""
    assert '"wb-preview wc-render f-" + (s.target_font || "gulimche")' in WORKBENCH
    # 글꼴 클래스의 CSS 실체(사어 클래스 명중 방지) — 세 글꼴 전부.
    for font in ("gulimche", "dotumche", "malgun"):
        assert f".wc-render.f-{font}" in CSS, f".wc-render.f-{font} 규칙이 없습니다"


def test_queue_dots_wrap_without_an_inner_scrollport():
    dots = _declarations(".wb-dots")
    assert "display:flex" in dots and "flex-wrap:wrap" in dots
    assert "max-height:" not in dots and "overflow:auto" not in dots
    assert ".wb-dots[hidden]{display:none}" in CSS


def test_queue_dot_keeps_fourteen_pixel_mark_inside_24px_hit_target():
    hit = _declarations(".wc-dot")
    mark = _declarations(".wc-dot::before")
    assert "width:24px" in hit and "height:24px" in hit
    assert "width:14px" in mark and "height:14px" in mark
    assert "top:5px" in mark and "left:5px" in mark
    assert "border-radius:var(--rad-pill)" in hit
    assert "border-radius:var(--rad-pill)" in mark


def test_degenerate_queue_hiding_survives():
    """퇴화 큐(1건) = 점 색인 은닉 — 승계 규칙이 workbench.js 에 산다."""
    assert "host.hidden = !!c.queue_degenerate" in WORKBENCH
