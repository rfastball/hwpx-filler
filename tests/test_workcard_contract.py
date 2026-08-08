"""H-09 workcard·큐 탐색 시각/스크롤 계약 가드 — 승계처 = 검토·복사 작업대.

「기안」 화면 사망(F6 PR-B)으로 계약의 주체가 이동했다: 카드 = #wbCard(.wb-preview 에
workbench.js 가 .wc-render·f-* 글꼴 클래스를 얹는다), 점 색인 = #wbDots(.wb-dots 판 위의
.wc-dot 항목 — 점·표지 CSS 는 「기안」 시절 그대로 재사용). 구 .wc-render 전용 부속
(scrollbar-gutter·overscroll-behavior)은 죽은 구 .zone.workcard 규칙과 함께 걷혔다
(승계처 .wb-preview 는 아직 선언하지 않는다).
"""
from __future__ import annotations

import re

from _web_source import SOURCE_INDEX, SOURCE_JS_DIR, SOURCE_ROOT, app_css


# 카드 수치(.wb-preview·.wb-dots)는 tail.css, 점·글꼴 클래스(.wc-dot·.wc-render.f-*)는
# draftcard.css 에 있다 — 이 창구를 거쳐야 한 검사가 승계 관계를 가로질러 본다.
CSS = app_css()
INDEX = SOURCE_INDEX.read_text(encoding="utf-8")
WORKBENCH = (SOURCE_ROOT / "src" / "screens" / "workbench.ts").read_text(encoding="utf-8")
# R5-99 B2 — legacy preserve.js 는 selftest 소유로 떠났다. 화면 전환을 가로지르는 스크롤
# 보존의 제품 승계자는 executor 다(`[id][data-preserve-scroll]` 전수를 전환 전 캡처·후 복원).
PRESERVE = (SOURCE_ROOT / "src" / "screens" / "product_screen_executor.ts").read_text(
    encoding="utf-8"
)


def _declarations(selector: str) -> str:
    bodies: list[str] = []
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in {part.strip() for part in selectors.split(",")}:
            bodies.append(re.sub(r"\s+", "", body))
    assert bodies, f"missing selector: {selector}"
    return ";".join(bodies)


def test_workbench_card_is_a_bounded_preserved_scrollport():
    """카드 스크롤포트 승계(H-09→작업대): 높이 경계·overflow·스크롤 보존 마크가 산다.

    **경계를 무엇이 주는가는 열 수에 달렸다**(U2 §2.2 리뷰 R1). 2열에서는 좌 pane 과 같은
    방식으로 `flex:1` 로 남는 높이를 받는다 — 고정 캡은 창이 낮아지면 `.wb-body` 를 넘쳐
    뒤따르는 footer 가 내용 위에 그려졌고, 좌우 캡을 서로 맞춰 두는 방식은 한쪽만 고쳐지는
    날이 온다. 1열 퇴화에서만 캡이 돌아온다(세로로 줄을 서면 나눠 가질 높이가 없다).
    min-height 는 빈 카드가 접히지 않게 하는 바닥이라 두 regime 모두에서 산다.
    """
    # R4-02 — 면·id·보존 마크 셋이 정적 HTML 에서 React 요소 props 로 함께 옮겨 왔다.
    assert re.search(
        r'h\("article", \{\s*className: `wb-preview[^`]*`,\s*id: "wbCard", "data-preserve-scroll": true,',
        WORKBENCH)
    rule = _declarations(".wb-preview")
    assert "min-height:180px" in rule
    assert "flex:1" in rule, "2열에서 남는 높이를 안 받으면 캡 시절의 끝단 어긋남이 돌아온다."
    assert "max-height:320px" in rule, "1열 퇴화의 캡이 없으면 카드가 무한정 늘어난다."
    assert "overflow:auto" in rule
    assert "scrollTop" in PRESERVE and '[id][data-preserve-scroll]' in PRESERVE, (
        "executor 가 보존 마크를 읽지 않습니다 — 카드가 단 data-preserve-scroll 이 사어가 됩니다."
    )


def test_workbench_card_wears_the_render_and_font_classes():
    """기안 카드 시각 계약 승계 — 렌더 판(.wc-render)과 대상 글꼴 클래스(f-*)를 JS 가 얹는다."""
    # R4-02 — 문자열 이어붙이기가 템플릿 리터럴이 됐다. 세 조각(면·렌더 판·글꼴)이
    # 한 자리에서 함께 붙는다는 계약은 그대로다.
    assert 'className: `wb-preview wc-render f-${snapshot.target_font || "gulimche"}`' in WORKBENCH
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
    assert "const degenerate = !!card.queue_degenerate;" in WORKBENCH
    assert "hidden: degenerate," in WORKBENCH
